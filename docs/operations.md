# 运维手册

## 日常检查

```bash
docker compose ps
docker compose logs --since=30m bot worker
docker compose exec -T postgres pg_isready -U anime -d anime
```

预期状态：postgres、bot、worker 为 `healthy`，migrate 为退出码 0。日志由 Docker 按单文件 10 MB、最多 3 个文件轮转。

## 备份与恢复

创建权限为仅当前用户可读的 gzip SQL 备份：

```bash
./scripts/backup-postgres.sh
BACKUP_DIR=/srv/anime-backups ./scripts/backup-postgres.sh
```

定期把备份复制到另一台机器或对象存储，并至少做一次恢复演练。恢复会停止 bot/worker、替换整个 `public` schema、重跑迁移，再恢复服务：

```bash
./scripts/restore-postgres.sh backups/anime-YYYYMMDDTHHMMSSZ.sql.gz
```

无人值守验收可在明确选择备份文件后使用 `--yes`；生产人工恢复建议保留交互确认。
如需在维护窗口中保持应用停止，可设置 `RESTORE_SKIP_APP_START=1`，确认数据后再手工执行 `docker compose up -d bot worker`。

## 常见故障

### migrate 失败

```bash
docker compose logs migrate
docker compose run --rm migrate
```

先解决数据库连接或迁移错误。bot/worker 在 migrate 成功前不会启动。

### bot 不健康

```bash
docker compose logs --tail=200 bot
docker compose exec bot python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8080/health/live').read())"
```

重点检查 QQ 凭据、服务器出口网络、开放平台 IP 白名单、HTTPS 证书和 `/qqbot` 回调配置。回调签名错误会返回 401。修改 `.env` 后执行 `docker compose up -d --force-recreate bot`。

### worker 不健康或没有推送

```bash
docker compose logs --tail=200 worker
docker compose exec worker python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8081/health/ready').read())"
```

依次确认：群已允许主动消息、计划处于开启状态、订阅成员仍在群内、番剧数据已同步。发送 `推送状态` 查看群配置。发送失败分为可重试、永久失败和 `unknown`；`unknown` 不会自动重发，管理员确认未送达后才能执行 `补发 <任务ID>`，避免重复骚扰。

### Bangumi 数据不可用

查询会继续使用数据库中的最近一次成功快照，并在数据陈旧时提示。检查 worker 日志和 `BANGUMI_USER_AGENT`；不要通过提高扫描频率绕过上游限制。

### 封面无法加载

确认 `.env` 中 `QQ_IMAGE_PROXY_BASE_URL` 使用自有 HTTPS 域名，并且反向代理已将 `/qqbot/media/` 转发到 bot。选择一个数据库中存在的条目验证：

```bash
curl -fsS -o /dev/null -D - https://你的域名/qqbot/media/covers/<Bangumi-ID>
```

预期返回 `200`、`Content-Type: image/jpeg` 或 `image/png`，以及一天的公共缓存响应头。同时确认 QQ 开放平台“消息 URL 配置”中已配置并验证 `你的域名/qqbot/media`。日志事件 `qq_cover_proxy_rejected` 会给出上游状态、类型、大小或来源拒绝原因，但不会记录图片原始 URL。

### 按钮显示成功但没有新消息

检查按钮后的群消息请求。日志事件 `qq_api_request_failed` 会安全记录 HTTP 状态、QQ 错误码和错误说明；`qq_delivery_failed` 记录最终投递结果。按钮回复应使用 `event_id`，不应把 `INTERACTION_CREATE:...` 作为 `msg_id` 发送。

## 安全

- `.env` 权限保持 `0600`，不得提交到 Git；
- 定期轮换 QQ `AppSecret` 和数据库密码；
- 不对公网直接发布 PostgreSQL、8080、8081 端口；只通过 HTTPS 反向代理开放 `/qqbot`；
- 日志中不得出现令牌、密钥和完整用户消息；
- 恢复、删除卷、手动补发都按高风险操作处理并留存操作者记录。

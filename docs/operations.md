# v0.2.0 运维手册

## 日常检查

```bash
docker compose ps
docker compose logs --since=30m worker astrbot napcat
docker compose exec -T postgres pg_isready -U anime -d anime
```

预期 `postgres`、`worker`、`astrbot`、`napcat` 为 healthy，`migrate` 正常退出。
AstrBot 的就绪检查还会验证插件消费者心跳；NapCat 的容器健康不等于 QQ 已登录。

生产服务器应使用 `.env` 中的：

```dotenv
COMPOSE_FILE=compose.yaml:compose.server-2g.yaml
```

这样五个单元会套用 2 GiB 主机资源上限。不要对整台主机运行 Docker 全局 prune；
OurNotes 和其他服务不属于本项目。

应用、PostgreSQL 和 NapCat 都从 `stonesver/anime-qqbot` ACR 仓库的固定标签拉取。
服务器不应依赖 Docker Hub 加速器；两个 vendor 标签只在上游固定版本变化时更新。

## ACR 升级与应用回滚

在 ACR 控制台确认 `latest` 构建成功后：

```bash
cd /opt/anime-qqbot
./scripts/deploy-acr.sh
```

部署脚本记录实际镜像 ID/digest，不能仅用可变的 `latest` 判断版本。已有应用容器时，
升级前镜像会保存为 `anime-qqbot:rollback`。Worker、AstrBot 或 NapCat 健康失败时
会自动把该镜像重新标记为生产引用并重建三个运行单元。

拉取失败不会替换运行服务；migration 失败会停止发布、恢复旧应用镜像引用，但不会
自动恢复数据库。首次部署没有旧镜像时无法应用回滚，脚本会明确退出并保留日志供排查。

## 常见故障

### 迁移失败

```bash
docker compose logs migrate
docker compose run --rm --no-deps migrate
```

先修复数据库连接或迁移错误。Worker 和 AstrBot 不应越过失败的迁移继续启动。

### 群命令没有响应

```bash
docker compose logs --tail=200 napcat astrbot
docker compose exec astrbot python -m anime_qqbot.entrypoints.healthcheck astrbot
```

依次确认：

1. QQ 小号在 NapCat WebUI 中为已登录状态；
2. NapCat 已连接 `ws://astrbot:6199/ws`；
3. AstrBot `aiocqhttp` 适配器的端口为 6199；
4. 两端 Access Token 与 `.env` 的 `ONEBOT_TOKEN` 完全相同；
5. `astrbot-plugin-anime-tracking` 已加载且消费者心跳正常。

修改 Token 后要同时更新 `.env` 和 AstrBot WebUI 中的适配器 Token，再重建两个容器：

```bash
docker compose up -d --force-recreate astrbot napcat
```

### Worker 不健康或没有提醒

```bash
docker compose logs --tail=300 worker
docker compose exec worker python -m anime_qqbot.entrypoints.healthcheck worker
```

检查上游请求、数据库连接和 Worker 心跳。开播提醒只对有精确时间的场次建立任务；
Mikan 只处理已确认的番剧映射，未知集数会保存但不会通知。字幕组、语言、分辨率过滤
按维度取交集；某维度没有识别结果时，只会通知未限制该维度的订阅。

通知使用持久化 Outbox、租约和业务键去重。失败任务会按策略重试，超过 24 小时的
Mikan 更新不会再投递，以免服务恢复后刷屏。

### 为番剧确认 Mikan 映射

Mikan 资源轮询只接受人工确认的公开番剧映射。先在群内通过查询取得内部 Anime ID，
再从 Mikan 番剧页 URL 取得数字 ID，然后在服务器执行：

```bash
docker compose run --rm --no-deps worker map-mikan \
  --anime-id <内部-Anime-UUID> \
  --mikan-id <Mikan-数字-ID>
```

命令幂等；若同一 Mikan ID 已指向另一部番剧会拒绝覆盖。映射建立后，只要已有用户
开启资源提醒，Worker 下一轮就会开始轮询公开 RSS。

### 为番剧确认 AniList 映射

从 AniList 条目 URL 取得数字 ID 后执行：

```bash
docker compose run --rm --no-deps worker map-anilist \
  --anime-id <内部-Anime-UUID> \
  --anilist-id <AniList-数字-ID>
```

该命令会先校验 AniList 条目，再建立 confirmed 映射并同步精确放送时刻。只有
confirmed 映射的精确时刻会产生开播提醒。

### Bangumi、AniList 或 Mikan 不可用

查询优先使用数据库中最近一次成功快照。检查：

```bash
docker compose logs worker | grep -E 'Bangumi|AniList|Mikan|sync|poll'
```

不要通过大幅提高轮询频率绕过上游限制。Bangumi 必须使用可联系到维护者的
`BANGUMI_USER_AGENT`；Mikan Feed 只接受公开的
`https://mikanani.me/RSS/Bangumi?bangumiId=<数字>`。

## 备份与恢复

创建仅当前用户可读的 gzip SQL 备份：

```bash
./scripts/backup-postgres.sh
BACKUP_DIR=/srv/anime-backups ./scripts/backup-postgres.sh
```

把备份复制到另一台机器或对象存储，并定期做恢复演练。恢复会停止 Worker、AstrBot、
NapCat，替换整个 `public` schema，重跑迁移，再恢复服务：

```bash
./scripts/restore-postgres.sh backups/anime-YYYYMMDDTHHMMSSZ.sql.gz
```

无人值守环境只有在备份文件已经明确选择后才使用 `--yes`。若要在维护窗口保持应用
停止，设置 `RESTORE_SKIP_APP_START=1`，确认数据后再执行：

```bash
docker compose up -d worker astrbot napcat
```

## 2 GiB 主机监控

```bash
free -h
vmstat 1 10
docker stats --no-stream
docker compose ps
```

以下任一情况持续出现时，应停止增加插件并评估升级到 4 GiB：

- `MemAvailable` 长期低于 250 MiB；
- Swap 使用持续增长到 1 GiB 以上；
- `vmstat` 的 `si/so` 持续非零；
- AstrBot 或 NapCat OOM/restart；
- 双核负载长期高于 2。

## 安全边界

- `.env` 保持 `0600`，不得提交 Token、数据库密码或 QQ 登录材料；
- 6185、6099 默认仅绑定本机，PostgreSQL、8081、6199 不发布到公网；
- 远程管理使用 SSH 隧道或受控内网；
- 专用 QQ 小号启用异常登录告警；是否关闭设备验证取决于 NapCat 实际登录结果，
  不要为省事长期降低账号安全；
- 日志不得记录 Access Token、密码和完整用户消息；
- 数据库恢复、删除卷、人工补发都按高风险操作处理。

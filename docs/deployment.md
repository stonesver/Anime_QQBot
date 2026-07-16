# 服务器部署

## 前置条件

- 一台具有固定公网出口 IP 的 Linux 服务器，以及指向该服务器的域名；
- Docker Engine 25+ 与 Docker Compose v2.24+；
- 能为回调域名提供 HTTPS 的反向代理，例如 Nginx 或 Caddy；
- QQ 开放平台机器人 `AppID`、`AppSecret`，以及已经配置好的测试群或正式环境；
- 可出站访问 QQ 开放平台、至少一个已配置的 Bangumi API 地址、GitHub Raw；
- 服务器时间同步正常，建议使用 UTC，群时区由机器人配置单独管理。

QQ 平台能力和审核规则可能变化，账号侧配置以 [QQ 开放平台](https://q.qq.com/) 当前控制台为准。腾讯官方 [botgo](https://github.com/tencent-connect/botgo) 已将 Webhook 作为当前事件接入方向，本项目因此默认 `QQ_EVENT_TRANSPORT=webhook`；旧账号确有兼容需要时才使用 `websocket`。Bangumi 接口说明见 [Bangumi API](https://github.com/bangumi/api)，节目表补充数据来自 [bangumi-data](https://github.com/bangumi-data/bangumi-data)。

## 首次部署

```bash
git clone <仓库地址> anime-qqbot
cd anime-qqbot
cp .env.example .env
chmod 600 .env
```

编辑 `.env`，至少填写：

```dotenv
POSTGRES_PASSWORD=<仅含 URL 安全字符的长随机密码>
BANGUMI_USER_AGENT=anime-qqbot/0.1.0 (your-email@example.com)
BANGUMI_API_BASE_URL=https://api.bgm.tv
BANGUMI_API_FALLBACK_URLS=
QQ_APP_ID=<QQ 机器人 AppID>
QQ_APP_SECRET=<QQ 机器人 AppSecret>
QQ_EVENT_TRANSPORT=webhook
```

`BANGUMI_ACCESS_TOKEN` 是可选项。若服务器无法稳定访问官方 API，可在
`BANGUMI_API_FALLBACK_URLS` 中按优先级填写逗号分隔的兼容镜像地址。客户端会在连接失败、超时、HTTP `429`、HTTP `5xx` 或无效 JSON 时自动切换，并将失败地址冷却 5 分钟；其他 HTTP `4xx` 不会触发切换。访问令牌只发送给 `BANGUMI_API_BASE_URL`，不会发送给第三方备用地址。第三方镜像由部署者自行选择并承担其可用性与数据可信风险。

`BOOTSTRAP_ADMIN_IDENTITIES` 仅用于平台事件无法提供管理员身份时的引导配置，格式是 `group_openid:member_openid`，多项用逗号分隔。

验证并启动：

```bash
docker compose config --quiet
docker compose build
docker compose up -d
docker compose ps
docker compose logs --tail=100 migrate bot worker
```

启动顺序由 Compose 保证：PostgreSQL 健康后运行一次迁移，迁移成功后才启动 bot 与 worker。PostgreSQL 和 worker 不发布端口；bot 只绑定宿主机 `127.0.0.1:8080`，需要由 HTTPS 反向代理公开 `/qqbot`。

Nginx 示例：

```nginx
location = /qqbot {
    proxy_pass http://127.0.0.1:8080/qqbot;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto https;
}
```

证书和站点配置完成后，先在服务器执行 `curl http://127.0.0.1:8080/health/live`，再由 QQ 控制台验证公开回调地址。健康路径无需对公网开放。

## QQ 控制台步骤

这些步骤需要账号持有人在 QQ 开放平台完成：

1. 创建官方机器人并取得 `AppID`、`AppSecret`；
2. 按控制台当前要求配置服务器出口 IP 白名单和沙箱/测试群；
3. 将 `https://你的域名/qqbot` 配置为事件回调地址，完成平台签名挑战；
4. 订阅群聊、C2C、互动和机器人进退群等所需事件，开通主动消息相关权限；
5. 将机器人加入测试群，先验证 `帮助`、`今日番剧`，再开启定时推送；
6. 正式发布前完成平台要求的审核与配置切换。

## 更新

### 从 ACR 镜像更新服务器

服务器 `.env` 使用稳定本地标签：

```dotenv
IMAGE_TAG=latest
```

首次使用时，以运行部署脚本的同一用户登录 ACR。服务器通常使用 `sudo` 管理 Docker，因此执行：

```bash
sudo docker login \
  crpi-thkewd16qu1tdfsq.cn-shenzhen.personal.cr.aliyuncs.com
```

以后每次 ACR 的 `latest` 构建成功后，只需运行：

```bash
sudo /opt/anime-qqbot/scripts/deploy-acr.sh
```

脚本可以从任意当前目录调用。它会自动定位 `/opt/anime-qqbot`，执行数据库备份、保存当前运行镜像、拉取 ACR `latest`、重建 `migrate`/`bot`/`worker`，并等待两个长期服务健康。新版本部署失败时，脚本会恢复上一版应用镜像；数据库不会自动恢复，以免覆盖部署期间的新数据。

常用覆盖参数：

```bash
# 紧急情况下跳过部署前备份
sudo SKIP_BACKUP=1 /opt/anime-qqbot/scripts/deploy-acr.sh

# 将健康检查等待时间改为 180 秒
sudo DEPLOY_TIMEOUT_SECONDS=180 /opt/anime-qqbot/scripts/deploy-acr.sh

# 使用同一仓库的指定版本，而不是 latest
sudo ACR_IMAGE_TAG=release-v1.2.0 /opt/anime-qqbot/scripts/deploy-acr.sh
```

正常部署返回退出码 `0`；新版本失败但应用回滚成功返回 `1`；新版本与回滚都失败返回 `2`。脚本不在内部执行 `sudo`，也不读取或输出 `.env` 中的秘密。

### 从源码更新

```bash
./scripts/backup-postgres.sh
git pull --ff-only
docker compose build
docker compose up -d
docker compose ps
```

迁移服务是幂等的，每次更新都会先升级数据库，再替换运行服务。不要在升级中手工跳过 `migrate`。

## 卸载

停止服务但保留数据：

```bash
docker compose down
```

`docker compose down -v` 会永久删除 PostgreSQL 卷，不应在生产环境使用，除非已完成并验证备份。

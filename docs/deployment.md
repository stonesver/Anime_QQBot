# v0.2.0 AstrBot 多源群聊追番部署指南

## 前置条件

- Linux 服务器，Docker Engine + Docker Compose v2；
- 专用 QQ 小号（普通 QQ 号，无需 QQ 开放平台 AppID）；
- 可出站访问 Bangumi API、AniList GraphQL、Mikan RSS；
- 服务器时间同步（UTC），群时区默认为 `Asia/Shanghai`。

本版本只使用 NapCat + AstrBot（OneBot 11 反向 WebSocket），不包含官方机器人运行时。

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
BANGUMI_USER_AGENT=anime-qqbot/0.2.0 (your-email@example.com)
ONEBOT_TOKEN=<随机高强度 token>
```

`ONEBOT_TOKEN` 至少 24 位，只使用字母、数字、`_`、`.`、`-`。不要把 `.env`
提交到 Git。

```bash
./scripts/deploy-multisource.sh --no-backup
docker compose ps
```

脚本会校验配置、构建应用、等待 PostgreSQL、执行迁移，再按顺序启动 Worker、
AstrBot 和 NapCat。以后升级时去掉 `--no-backup`，脚本会先创建数据库备份。

## 首次 OneBot 配置

管理端口默认仅绑定 `127.0.0.1`。服务器部署时使用 SSH 隧道：

```bash
ssh -L 6185:127.0.0.1:6185 -L 6099:127.0.0.1:6099 <服务器>
```

1. 打开 `http://127.0.0.1:6185`。从 `docker compose logs astrbot`
   查找 AstrBot 首次登录信息，进入 WebUI。
2. 在 AstrBot 的机器人/平台配置中创建 `aiocqhttp`（OneBot 11）适配器，监听
   `0.0.0.0:6199`，Access Token 填写 `.env` 中完全相同的 `ONEBOT_TOKEN`。
   不要把 6199 发布到宿主机。
3. 打开 `http://127.0.0.1:6099`，扫码登录专用 QQ 小号。NapCat 启动脚本已将
   反向 WebSocket 写为 `ws://astrbot:6199/ws`，无需手工复制 Token。
4. 查看 `docker compose logs -f napcat astrbot`，确认 OneBot 连接建立。然后把
   小号加入测试群，发送 `/番剧 帮助`。

Worker 会从 Bangumi 当前日历逐批初始化空目录。首次启动后可能需要数轮（默认每轮
30 秒）才收齐当前日历。Mikan 映射需要按[运维手册](operations.md)用本地运维命令
人工确认，系统不会仅凭相似标题自动合并。

AstrBot 不同补丁版本的字段名称可能略有差别，以 WebUI 中的
`aiocqhttp`、反向 WebSocket 监听端口和 Access Token 为准。

### 构建清单

| 服务 | 镜像 | 端口 |
|---|---|---|
| postgres | postgres:17.4-alpine | 仅内部 |
| migrate | `anime-qqbot:0.2.0`（one-shot） | 无 |
| worker | `anime-qqbot:0.2.0` | 8081，仅内部健康检查 |
| astrbot | 基于 `soulter/astrbot:v4.26.7` 构建 | 127.0.0.1:6185；6199 仅容器网络 |
| napcat | `mlikiowa/napcat-docker:v4.18.13` | 127.0.0.1:6099 |

### 验证

```bash
docker compose ps
docker compose logs --tail=100 migrate worker astrbot napcat
curl -fsS http://127.0.0.1:6185/
```

预期：`postgres`、`worker`、`astrbot`、`napcat` 为 healthy，迁移任务退出码为
0。容器健康只代表进程和数据库链路正常；QQ 是否已登录、反向 WebSocket 是否已连接，
仍需通过日志和测试群消息确认。

## 更新与回滚

```bash
git pull --ff-only
./scripts/deploy-multisource.sh
```

应用容器启动失败时脚本会尝试恢复升级前的 Worker/AstrBot 镜像标签。数据库恢复属于
高风险操作，不会自动执行；请按[运维手册](operations.md)选择明确的备份文件恢复。

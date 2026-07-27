# v0.2.0 AstrBot 多源群聊追番部署指南

## 前置条件

- Linux 服务器，Docker Engine + Docker Compose v2；
- 专用 QQ 小号（普通 QQ 号，无需 QQ 开放平台 AppID）；
- 可出站访问 Bangumi API、AniList GraphQL、Mikan RSS；
- 服务器时间同步（UTC），群时区默认为 `Asia/Shanghai`。

本版本使用 NapCat + AstrBot (OneBot 11 reverse WebSocket)，不再依赖
QQ 开放平台 `AppID`/`AppSecret`。

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

### 启动服务

```bash
docker compose up -d --build
docker compose ps
```

首次启动后：
1. 打开 `http://<服务器IP>:8082`（NapCat WebUI），使用 QQ 小号扫码登录。
2. 确认 NapCat 反向 WebSocket 已连接至 AstrBot (`ws://astrbot:6199/ws`)。
3. 在测试群发送 `/番剧 帮助` 验证插件响应。

### 构建清单

| 服务 | 镜像 | 端口 |
|---|---|---|
| postgres | postgres:17.4-alpine | 仅内部 |
| migrate | anime-qqbot (one-shot) | - |
| worker | anime-qqbot | 8081（健康检查） |
| astrbot | anime-astrbot | 6180（AstrBot）、127.0.0.1:6180 |
| napcat | napcat/napcat:3.6.0 | 8080（OneBot WS内部）、127.0.0.1:8082（WebUI） |

### 验证

```bash
docker compose ps
# 预期: postgres (healthy), migrate (exited 0), worker (healthy),
#        astrbot (running), napcat (running)

docker compose logs worker astrbot | head -20
```

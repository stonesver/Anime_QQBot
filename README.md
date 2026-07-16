# anime-qqbot

一个使用 QQ 官方机器人开放平台、Bangumi API 和 bangumi-data 的小范围群聊追番服务。

当前状态：v0.1.0 候选版本，代码与离线验收已完成，正式发布前需要 QQ 官方沙箱凭据做线上验收。

## 首期范围

- 今日、本周、季度番剧查询；
- 搜索、详情和下一次预计放送；
- 群内用户订阅与 `@` 提醒；
- 每群独立的每日/每周计划；
- PostgreSQL 持久化；
- Docker Compose 部署。

首期不包含个人 QQ/OneBot、Web 管理后台、Bangumi 账号绑定、Agent/MCP 或资源实际上线检测。

## 文档

- [服务器部署](docs/deployment.md)
- [运维、备份与恢复](docs/operations.md)
- [设计规格](docs/superpowers/specs/2026-07-15-anime-qq-bot-design.md)
- [实施计划](docs/superpowers/plans/2026-07-15-anime-qq-bot-implementation-plan.md)

## 本地开发前置条件

- Python 3.12
- [uv](https://docs.astral.sh/uv/)
- Docker Engine 与 Docker Compose

安装依赖后运行：

```bash
uv sync --frozen
make check-fast
```

## Docker 快速启动

```bash
cp .env.example .env
# 填写 POSTGRES_PASSWORD、BANGUMI_USER_AGENT、QQ_APP_ID、QQ_APP_SECRET
docker compose up -d --build
docker compose ps
```

完整的 QQ 控制台步骤、更新、故障排查和数据恢复方法见部署与运维文档。

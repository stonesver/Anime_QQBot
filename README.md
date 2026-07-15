# anime-qqbot

一个使用 QQ 官方机器人开放平台、Bangumi API 和 bangumi-data 的小范围群聊追番服务。

当前状态：按照已批准的设计规格实施 v0.1.0。

## 首期范围

- 今日、本周、季度番剧查询；
- 搜索、详情和下一次预计放送；
- 群内用户订阅与 `@` 提醒；
- 每群独立的每日/每周计划；
- PostgreSQL 持久化；
- Docker Compose 部署。

首期不包含个人 QQ/OneBot、Web 管理后台、Bangumi 账号绑定、Agent/MCP 或资源实际上线检测。

## 文档

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


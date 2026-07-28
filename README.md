# anime-qqbot v0.2.0

AstrBot 多源群聊追番服务：通过 NapCat (OneBot 11) + AstrBot 接入普通 QQ 小号，
提供群内固定命令查询、订阅追番、预计放送提醒和 Mikan 资源更新通知。

当前状态：v0.2.0 代码、264 项测试与隔离五单元启动验收完成，首次部署仍需在 AstrBot WebUI
完成一次 OneBot 适配器配置，并在真实测试群执行 canary。

## 核心功能

- 今日本周季度查询、搜索、详情、下一次预计放送；
- 群内用户通过内部 Anime ID 订阅与取消；
- Bangumi + AniList 双源数据融合与字段投影；
- 精确时刻预计放送提醒 + `@` 订阅用户；
- Mikan RSS 资源发布聚合、字幕组/语言/分辨率筛选；
- 通知 Outbox（租约、重试、过期清理）；
- PostgreSQL 持久化，Docker Compose 五单元部署。

## 架构

```
QQ小号 → NapCat/OneBot 11 → AstrBot → Anime Plugin → Anime Core → PostgreSQL
                                  ↑                        ↑
                                  └─ Worker (同步/规划) ───┘
                                        Bangumi / AniList / Mikan
```

首版不包含 QQ 官方机器人、Web 管理后台、大模型依赖或自动下载。

## 文档

- [部署指南](docs/deployment.md)
- [运维手册](docs/operations.md)
- [v0.2.0 验收报告](docs/acceptance/v0.2.0.md)
- [多源追番系统设计](docs/superpowers/specs/2026-07-26-astrbot-multisource-anime-tracking-design.md)
- [实施计划](docs/superpowers/plans/2026-07-27-astrbot-multisource-anime-tracking-implementation-plan.md)
- [领域词汇](CONTEXT.md)

## 本地开发

```bash
# Python 3.12 + Docker
uv sync --frozen
.venv/bin/pytest
.venv/bin/ruff check .
.venv/bin/mypy src
```

## Docker 快速启动

```bash
cp .env.example .env
# 填写 POSTGRES_PASSWORD、ONEBOT_TOKEN 和 BANGUMI_USER_AGENT
chmod 600 .env
./scripts/deploy-multisource.sh --no-backup
docker compose ps
```

- AstrBot WebUI：`http://127.0.0.1:6185`
- NapCat WebUI：`http://127.0.0.1:6099`

两个管理界面默认只绑定本机。远程服务器请用 SSH 端口转发访问，不要直接暴露到公网。
首次连接的逐步配置见[部署指南](docs/deployment.md)。

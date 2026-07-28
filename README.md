# anime-qqbot v0.2.0

AstrBot 多源群聊追番服务：通过 NapCat (OneBot 11) + AstrBot 接入普通 QQ 小号，
提供群内固定命令查询、订阅追番、预计放送提醒和 Mikan 资源更新通知。

当前状态：v0.2.0 代码与自动化验收已完成，生产镜像采用 ACR 单镜像发布。首次部署仍需
在 AstrBot WebUI 完成一次 OneBot 适配器配置，并在真实测试群执行 canary。

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

## ACR 部署

ACR 仓库：
`crpi-thkewd16qu1tdfsq.cn-shenzhen.personal.cr.aliyuncs.com/stonesver/anime-qqbot:latest`。
根 `Dockerfile` 生成一个合并镜像，供 migration、Worker 和 AstrBot 三个角色复用；
服务器不 clone 完整源码，也不现场构建。应用、PostgreSQL 和 NapCat 均从同一个
ACR 仓库拉取，生产部署不再依赖服务器直连 Docker Hub。

```bash
# 本地生成不含秘密的服务器部署包
./scripts/package-deployment.sh dist/anime-qqbot-deployment.tar.gz

# 服务器解包并准备 .env 后
./scripts/deploy-acr.sh --no-backup
```

- AstrBot WebUI：`http://127.0.0.1:6185`
- NapCat WebUI：`http://127.0.0.1:6099`

两个管理界面默认只绑定本机。远程服务器请用 SSH 端口转发访问，不要直接暴露到公网。
ACR 规则、上传、首次部署和 OneBot 配置见[部署指南](docs/deployment.md)。

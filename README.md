# anime-qqbot v0.4.0

AstrBot 多源群聊追番服务：通过 NapCat (OneBot 11) + AstrBot 接入普通 QQ 小号，
提供群内固定命令、@机器人和安全短命令查询，支持订阅追番、预计放送提醒、Mikan
资源更新通知，以及 AstrBot 内嵌运维控制台。

当前状态：v0.4.0 自动化候选版，生产镜像继续采用 ACR 单镜像发布。真实 QQ 图片发送、
客户端显示大小和 2 GiB 服务器稳定性仍需在测试群执行 canary。

## 核心功能

- 今日本周季度查询、搜索、详情、下一次预计放送；
- `/番剧` 固定命令、可按群开启的安全短命令，以及 AstrBot 原生 LLM 只读番剧工具；
- 通用聊天按群独立控制且默认关闭；关闭时非番剧问题只返回能力提示；
- 搜索结果使用 1..N 候选编号，不向群成员暴露内部 UUID；
- 群内用户管理自己的订阅；QQ 群主/管理员不获得机器人配置权限；
- Bangumi + AniList 数据融合，并以 AnimeSchedule 跨站 ID 补映射、补充日本原始播出时间；
- 搜索未命中及订阅后的持久化后台数据补全，不阻塞群消息回复；
- 搜索唯一命中、详情和下一集使用本地真实海报生成 `1000 × 600` 放送信号卡片；
- 海报缺失、损坏或渲染失败时直接返回等价结构化文本，不使用占位图；
- 精确时刻预计放送提醒 + `@` 订阅用户；
- Mikan RSS 资源发布聚合、字幕组/语言/分辨率筛选；
- 精简资源通知保留北京时间，不发送主动 Mikan 外链；用户可发送
  `资源详情 <关键词> [集数]` 主动查询一个资源页面；
- 预留默认关闭的 B 站规范视频页动作链接槽位，每条通知最多一个；
- 通知 Outbox（租约、重试、过期清理）；
- 统一发送限频、主动提醒防突发和持久化熔断；
- 仅 AstrBot Dashboard 管理员可用的内嵌运维页；
- PostgreSQL 持久化，Docker Compose 五单元部署。

## 架构

```
QQ小号 → NapCat/OneBot 11 → AstrBot → Anime Plugin → Anime Core → PostgreSQL
                                  ↑                        ↑
                                  └─ Worker (同步/规划/海报预热) ───┘
                                Bangumi / AnimeSchedule / AniList / Mikan
```

本项目不包含 QQ 官方机器人或自动下载。大模型为 AstrBot 侧可选依赖；配置支持
Function Calling 的模型（例如 MiniMax）后，可在明确 `@机器人` 时调用只读番剧工具。
管理页嵌入 AstrBot WebUI，
不新增独立 Web 服务或公网端口。群消息请求不访问 Bangumi、AnimeSchedule、AniList、Mikan 或远程
海报；Worker 在后台把 confirmed Bangumi 海报缓存到 `card-assets`，失败时尝试 AniList。

## 文档

- [部署指南](docs/deployment.md)
- [运维手册](docs/operations.md)
- [v0.2.0 验收报告](docs/acceptance/v0.2.0.md)
- [v0.3.0 验收报告](docs/acceptance/v0.3.0.md)
- [v0.4.0 验收报告](docs/acceptance/v0.4.0.md)
- [v0.4.0 群聊回复与番剧卡片设计](docs/superpowers/specs/2026-07-29-anime-group-reply-presentation-design.md)
- [v0.4.0 群聊回复与番剧卡片实施计划](docs/superpowers/plans/2026-07-29-anime-group-reply-presentation-implementation-plan.md)
- [v0.3.0 群交互与管理设计](docs/superpowers/specs/2026-07-28-anime-chat-interaction-admin-panel-design.md)
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

日常应用发布不会刷新或协调已经运行的 NapCat；固定第三方镜像维护使用显式
`--refresh-vendors`。发布脚本会输出 NapCat 发布前后指纹和是否重启。

应用镜像包含固定 CJK 字体与 Pillow。Worker 和 AstrBot 共享派生命名卷
`card-assets`，默认上限 300 MiB、回收到 270 MiB。紧急关闭图片回复时，在 AstrBot
插件配置关闭 `card_presentation_enabled`；查询会恢复为完整文本，不需要删除缓存或
重登 QQ。

- AstrBot WebUI：`http://127.0.0.1:6185`
- NapCat WebUI：`http://127.0.0.1:6099`

两个管理界面默认只绑定本机。远程服务器请用 SSH 端口转发访问，不要直接暴露到公网。
ACR 规则、上传、首次部署和 OneBot 配置见[部署指南](docs/deployment.md)。

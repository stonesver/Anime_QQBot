# AstrBot 多源群聊追番系统实施计划

- 日期：2026-07-27
- 状态：待实施
- 对应规格：[AstrBot 多源群聊追番系统设计规格](../specs/2026-07-26-astrbot-multisource-anime-tracking-design.md)
- 目标版本：v0.2.0
- 设计基线提交：`29c87b5`
- 迁移性质：破坏性产品基线切换，不迁移 QQ 官方机器人身份与订阅

## 1. 完成定义

本计划完成后，专用 QQ 小号通过 NapCat 和 AstrBot 入群，群成员可以稳定完成查询、订阅、取消订阅、筛选资源和查看状态；Worker 可以融合 Bangumi、AniList 和 Mikan 数据，生成持久化通知任务；AstrBot 插件可以在预计放送和 Mikan 更新时主动向原群发送消息并 `@` 匹配用户。

以下条件必须同时满足，才可以标记 v0.2.0 完成：

1. 固定命令不依赖大模型，并覆盖规格中的全部查询和订阅命令。
2. Bangumi、AniList、Mikan 任一来源短时不可用时，已有缓存仍可查询，其他来源继续同步。
3. 预计放送提醒只由精确时刻触发，过期 2 小时后不补发。
4. Mikan 同番同集在 10 分钟窗口内聚合，按每位订阅者筛选，单条消息最多展示 5 个资源，过期 24 小时后不补发。
5. 通知任务、租约、投递尝试、群 UMO、订阅和同步游标在容器重启后仍存在。
6. QQ 官方机器人入口、openid、AppID/Secret、官方消息契约和相关测试全部退出运行基线。
7. `postgres`、`migrate`、`napcat`、`astrbot`、`worker` 五个 Compose 单元有固定镜像或锁定依赖、健康检查和持久卷。
8. 自动化检查、迁移往返、Compose 验收和真实测试群 canary 全部通过。

## 2. 实施约束

1. 按本计划的六个 tracer-bullet 分片顺序实施；每个分片都必须形成可运行、可演示的纵向能力。
2. 每个行为变更先写失败测试，再写最小实现；不以“大分支末尾补测试”代替测试驱动。
3. `src/anime_qqbot` 暂时保留包名，避免无业务价值的全仓改名；对外产品文案不再使用“QQ 官方机器人”。
4. AstrBot 只负责平台事件适配和消息投递。标题匹配、数据融合、订阅规则、资源解析、通知规划全部留在 Anime Core。
5. AstrBot、NapCat、Bangumi、AniList 和 Mikan 只存在于 adapter 后面；领域和应用测试不得导入其 SDK 或 HTTP 实现。
6. PostgreSQL 是唯一业务事实来源；集成测试继续使用 PostgreSQL，不能用 SQLite 替代唯一约束、租约和并发行为。
7. 所有持久时间使用 UTC aware datetime；用户输入和群内展示按 `Asia/Shanghai` 或群配置时区转换。
8. 自动匹配只能建立 `confirmed` 关系；低置信度候选保存为 `probable` 或 `unresolved`，不得静默合并。
9. 成人过滤失败时采用安全侧策略：不展示、不订阅、不推送，并保留管理诊断信息。
10. 数据源查询禁止发生在每条 QQ 消息的在线路径；在线查询只读本地数据库。
11. 不写入用户未纳入版本控制的 `scripts/deploy-acr.sh`；新部署流程使用独立文件，旧脚本的归档由用户另行决定。
12. 不在本里程碑增加 Web 后台、下载器、私有 Mikan token、跨群账号或新的内部 HTTP 服务。

## 3. 目标目录结构

```text
.
├── .env.example
├── Dockerfile
├── Dockerfile.astrbot
├── compose.yaml
├── compose.test.yaml
├── pyproject.toml
├── uv.lock
├── migrations/versions/
│   ├── 0005_multisource_catalog.py
│   ├── 0006_chat_groups.py
│   ├── 0007_remove_official_runtime.py
│   ├── 0008_following_and_outbox.py
│   ├── 0009_resource_releases.py
│   └── 0010_remove_v01_catalog.py
├── astrbot_plugin_anime_tracking/
│   ├── main.py
│   ├── metadata.yaml
│   ├── _conf_schema.json
│   ├── requirements.txt
│   └── anime_tracking_plugin/
│       ├── adapter.py
│       ├── commands.py
│       ├── dispatcher.py
│       ├── lifecycle.py
│       └── rendering.py
├── src/anime_qqbot/
│   ├── application/
│   │   ├── context.py
│   │   ├── intents.py
│   │   └── module.py
│   ├── catalog/
│   │   ├── adapters/
│   │   │   ├── anilist.py
│   │   │   ├── bangumi.py
│   │   │   └── http_policy.py
│   │   ├── matching.py
│   │   ├── models.py
│   │   ├── module.py
│   │   ├── ports.py
│   │   ├── projection.py
│   │   ├── repository.py
│   │   └── sync.py
│   ├── chats/
│   ├── groups/
│   ├── notifications/
│   ├── persistence/
│   ├── resources/
│   │   ├── adapters/mikan.py
│   │   ├── batching.py
│   │   ├── models.py
│   │   ├── module.py
│   │   ├── parser.py
│   │   └── repository.py
│   ├── subscriptions/
│   └── entrypoints/
│       ├── cli.py
│       ├── health.py
│       └── worker.py
├── tests/
│   ├── acceptance/
│   ├── contract/
│   ├── e2e/
│   ├── fixtures/
│   ├── integration/
│   └── unit/
└── docs/
    ├── acceptance/v0.2.0.md
    ├── deployment.md
    └── operations.md
```

`astrbot_plugin_anime_tracking/main.py` 只做 AstrBot 插件注册和依赖组装；可测试实现放在子包中。Anime Core 的包根只导出用例级接口和稳定领域类型。

## 4. Git、测试和提交纪律

按以下顺序建立本地分支：

1. `codex/feat/multisource-identity`
2. `codex/feat/astrbot-group-query`
3. `codex/feat/anilist-fusion`
4. `codex/feat/follow-and-airing`
5. `codex/feat/mikan-resource-alerts`
6. `codex/feat/production-compose`

开始每个分支前：

```bash
git status --short
git switch main
git pull --ff-only
git switch -c <branch>
uv sync --frozen
make check
```

若本机 `uv` 不在 `PATH`，使用仓库虚拟环境执行等价检查：

```bash
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy src
.venv/bin/pytest tests/unit
```

每项任务遵循：

1. 添加最小失败测试并运行到失败，记录失败原因符合预期。
2. 实现最小行为并运行该任务的定向测试。
3. 运行受影响模块测试和 `make check-fast`。
4. 用 `git diff --check` 和 `git status --short` 确认提交范围。
5. 使用任务中给出的提交主题；不夹带无关格式化或用户文件。

每个分支结束时：

```bash
make check
git diff --check main...HEAD
git diff --stat main...HEAD
git switch main
git merge --no-ff <branch>
```

数据库任务额外执行：

```bash
docker compose -f compose.test.yaml up -d --wait
uv run alembic upgrade head
uv run pytest tests/integration/test_migrations.py
docker compose -f compose.test.yaml down
```

## 5. 分片一：建立内部 Anime 身份

本分片的演示终点是：Bangumi 数据进入新多源模型，查询返回稳定内部 Anime ID；同一作品可以保存多个来源证据，旧 Bangumi subject ID 不再充当领域主键。

### 任务 1：定义多源领域类型和端口

**文件**

- 修改：`src/anime_qqbot/catalog/models.py`
- 修改：`src/anime_qqbot/catalog/ports.py`
- 修改：`src/anime_qqbot/catalog/__init__.py`
- 新建：`tests/unit/catalog/test_multisource_models.py`
- 新建：`tests/unit/catalog/test_source_ports.py`

**步骤**

1. 先测试 `AnimeId`、`ExternalEntry`、`SourceSnapshot`、`SourceLink`、`SourceName`、`LinkStatus` 和 `AiringOccurrence` 的不变量。
2. 内部 ID 使用数据库生成的不可变 UUID；外部 ID 始终与来源组成复合身份。
3. `SourceLink` 显式保存 `confirmed/probable/unresolved/rejected`、证据类型、置信度、创建方式和审核时间。
4. `SourceProvider` 只暴露增量同步、按来源 ID 获取和来源健康结果；不得向上泄漏 httpx response。
5. `AnimeCatalog` 的查询输入和结果改用内部 ID；外部来源 ID 只能作为搜索条件。

**验证**

```bash
uv run pytest tests/unit/catalog/test_multisource_models.py tests/unit/catalog/test_source_ports.py
uv run mypy src/anime_qqbot/catalog
```

**提交**

```text
feat: define multisource anime identity
```

### 任务 2：增加多源目录迁移和 ORM

**文件**

- 新建：`migrations/versions/0005_multisource_catalog.py`
- 修改：`src/anime_qqbot/persistence/models/catalog.py`
- 修改：`src/anime_qqbot/persistence/models/__init__.py`
- 修改：`tests/integration/test_migrations.py`
- 新建：`tests/integration/test_multisource_catalog_constraints.py`

**步骤**

1. 建立 `animes`、`external_entries`、`anime_source_links`、`source_snapshots`、`anime_titles`、`airing_occurrences`、`source_sync_states`。
2. 对 `(source, external_id)`、Anime 与来源唯一链接、来源快照版本、放送来源事件建立唯一约束。
3. 原始 payload 使用 JSONB，规范字段使用有索引列；来源时间、抓取时间和失效时间分开保存。
4. 成人标记保留 `true/false/unknown` 来源状态，不把 unknown 投影成 false。
5. migration `downgrade()` 删除本迁移新表，不触碰 0001—0004；往返测试覆盖 `base -> head -> base -> head`。

**验证**

```bash
uv run pytest tests/integration/test_migrations.py tests/integration/test_multisource_catalog_constraints.py
```

**提交**

```text
feat: add multisource catalog schema
```

### 任务 3：实现来源快照和内部目录仓储

**文件**

- 修改：`src/anime_qqbot/catalog/repository.py`
- 新建：`tests/integration/test_source_snapshot_repository.py`
- 新建：`tests/integration/test_internal_anime_repository.py`

**步骤**

1. 测试同一来源事件重复写入幂等、payload 改变生成新快照、当前快照切换原子化。
2. 在一个事务中 upsert External Entry、追加 Source Snapshot，并更新当前快照指针。
3. 仓储提供按内部 ID、外部身份、规范化标题和季度搜索的最小接口。
4. 查询默认排除禁用 Anime、禁用 External Entry 和成人投影为 true 的记录。
5. 并发同步同一 External Entry 时依赖唯一约束和事务重试，不使用进程锁。

**验证**

```bash
uv run pytest tests/integration/test_source_snapshot_repository.py tests/integration/test_internal_anime_repository.py
```

**提交**

```text
feat: persist source snapshots and internal anime
```

### 任务 4：实现可审计来源匹配

**文件**

- 新建：`src/anime_qqbot/catalog/matching.py`
- 新建：`tests/unit/catalog/test_source_matching.py`
- 新建：`tests/fixtures/catalog/matching_cases.json`

**步骤**

1. 固定 fixture 覆盖显式外链、精确外部交叉 ID、规范化标题加季度、同名不同季度、剧场版与 TV、低置信度冲突。
2. 匹配优先级为显式来源链接、可信交叉 ID、人工确认、严格复合证据。
3. 只有无冲突的强证据可以自动产生 `confirmed`；标题相似度只能产生候选，不得自动确认。
4. 每次判断保存规则版本、输入证据和结果，管理员可以 reject 或 confirm。
5. 匹配器必须纯计算、确定性且无数据库访问，便于后续离线重算。

**验证**

```bash
uv run pytest tests/unit/catalog/test_source_matching.py
```

**提交**

```text
feat: add auditable source matching
```

### 任务 5：将 Bangumi 同步切到新模型

**文件**

- 修改：`src/anime_qqbot/catalog/adapters/bangumi.py`
- 修改：`src/anime_qqbot/catalog/sync.py`
- 修改：`tests/contract/test_bangumi_adapter.py`
- 修改：`tests/unit/catalog/test_sync_fallback.py`
- 新建：`tests/e2e/test_internal_catalog_queries.py`

**步骤**

1. 保留现有 Bangumi fallback、冷却和缓存策略，将响应规范化为 External Entry 和 Source Snapshot。
2. 日历、详情、分集和搜索同步都保存来源抓取时间及错误状态。
3. 首次遇到 Bangumi 条目时创建内部 Anime 和 confirmed Bangumi Source Link。
4. 将旧 `anime_subjects` 作为临时只读回退，不再写入新业务事实。
5. E2E 验证今日、本周、季度、搜索、详情和下次查询均返回内部 ID。

**验证**

```bash
uv run pytest tests/contract/test_bangumi_adapter.py tests/unit/catalog/test_sync_fallback.py tests/e2e/test_internal_catalog_queries.py
make check-fast
```

**提交**

```text
feat: sync bangumi into internal catalog
```

## 6. 分片二：打通 AstrBot 群内查询

本分片的演示终点是：NapCat 反向 WebSocket 接入 AstrBot，真实测试群可以执行固定查询命令；每次群事件保存普通 QQ 群号、QQ 号和最新 UMO；系统中不再存在 QQ 官方机器人运行入口。

### 任务 6：建立平台无关 Chat Context 和意图接口

**文件**

- 新建：`src/anime_qqbot/application/context.py`
- 新建：`src/anime_qqbot/application/intents.py`
- 新建：`src/anime_qqbot/application/module.py`
- 修改：`src/anime_qqbot/commands/models.py`
- 修改：`src/anime_qqbot/commands/parser.py`
- 新建：`tests/unit/application/test_chat_context.py`
- 修改：`tests/unit/commands/test_parser.py`

**步骤**

1. `ChatContext` 只包含 platform、group ID、user ID、display name、UMO、timezone 和管理员标记。
2. 把规格中的固定命令映射为封闭 Intent 类型；语法错误返回可操作帮助。
3. 多候选结果必须要求用户使用内部 ID 选择，不能默认选择第一项。
4. 自然语言 adapter 只允许产生同一 Intent；状态变更 Intent 带 `requires_confirmation=true`。
5. 应用用例返回平台无关 `Reply`，不返回 AstrBot 或 QQ 组件。

**验证**

```bash
uv run pytest tests/unit/application tests/unit/commands/test_parser.py
```

**提交**

```text
feat: add platform neutral chat intents
```

### 任务 7：保存群、成员和 AstrBot UMO

**文件**

- 新建：`migrations/versions/0006_chat_groups.py`
- 修改：`src/anime_qqbot/persistence/models/identity.py`
- 修改：`src/anime_qqbot/groups/repository.py`
- 修改：`src/anime_qqbot/groups/module.py`
- 新建：`tests/integration/test_chat_group_repository.py`

**步骤**

1. 建立 `chat_groups` 和 `group_memberships`；平台外部 ID 使用字符串保存，唯一键为 `(platform, external_group_id)`。
2. `chat_groups` 保存最新 `unified_msg_origin`、刷新时间、时区、启用状态和管理备注。
3. 每次群事件原子刷新成员显示名和 UMO；私聊事件不创建可通知群。
4. UMO 只作为 AstrBot 路由定位值，不解析其内部结构，也不从群号自行拼接。
5. 测试重启新 session 后仍可读取最新 UMO，旧事件晚到时不能覆盖更新值。

**验证**

```bash
uv run pytest tests/integration/test_chat_group_repository.py tests/integration/test_migrations.py
```

**提交**

```text
feat: persist chat groups and astrbot origins
```

### 任务 8：搭建 AstrBot 插件骨架

**文件**

- 新建：`astrbot_plugin_anime_tracking/main.py`
- 新建：`astrbot_plugin_anime_tracking/metadata.yaml`
- 新建：`astrbot_plugin_anime_tracking/_conf_schema.json`
- 新建：`astrbot_plugin_anime_tracking/requirements.txt`
- 新建：`astrbot_plugin_anime_tracking/anime_tracking_plugin/lifecycle.py`
- 新建：`tests/unit/astrbot/test_plugin_metadata.py`
- 新建：`tests/unit/astrbot/fakes.py`

**步骤**

1. 插件名使用 `astrbot_plugin_anime_tracking`，metadata 声明 `support_platforms: aiocqhttp` 和经验证的 AstrBot 最低版本。
2. `main.py` 注册插件、命令组和生命周期；数据库和 Anime Core 组装放在 lifecycle。
3. AstrBot import 只出现在插件目录；测试通过 fake event/context 验证，不把 AstrBot 安装进 Core 的 dev 依赖。
4. `_conf_schema.json` 只暴露非密钥业务配置；数据库口令从容器环境读取。
5. 插件退出时停止 outbox consumer、等待在途任务并释放数据库连接。

**验证**

```bash
uv run pytest tests/unit/astrbot/test_plugin_metadata.py
uv run python -m compileall astrbot_plugin_anime_tracking
```

**提交**

```text
feat: scaffold astrbot anime plugin
```

### 任务 9：实现 AstrBot 事件适配和被动回复

**文件**

- 新建：`astrbot_plugin_anime_tracking/anime_tracking_plugin/adapter.py`
- 新建：`astrbot_plugin_anime_tracking/anime_tracking_plugin/commands.py`
- 新建：`astrbot_plugin_anime_tracking/anime_tracking_plugin/rendering.py`
- 新建：`tests/unit/astrbot/test_event_adapter.py`
- 新建：`tests/unit/astrbot/test_command_handlers.py`
- 新建：`tests/e2e/test_astrbot_group_queries.py`

**步骤**

1. 从 `AstrMessageEvent` 提取群号、用户 QQ、显示名和 `unified_msg_origin`，先刷新 ChatGroup，再执行命令。
2. 使用 AstrBot command group 注册 `/番剧` 子命令；未知子命令返回固定帮助。
3. 将平台无关 Reply 渲染为 Plain、Image、At 等消息组件；首版查询可以文本优先，超长内容明确截断。
4. 使用 fake Context 验证 handler 只调用用例接口，不直接访问 repository。
5. E2E 覆盖今天、本周、季度、搜索多候选、详情、下次和状态。

**验证**

```bash
uv run pytest tests/unit/astrbot/test_event_adapter.py tests/unit/astrbot/test_command_handlers.py tests/e2e/test_astrbot_group_queries.py
```

**提交**

```text
feat: answer anime queries through astrbot
```

### 任务 10：删除 QQ 官方机器人运行时

**文件**

- 删除：`src/anime_qqbot/qq/`
- 删除：`src/anime_qqbot/entrypoints/bot.py`
- 删除：`tests/contract/test_qq_cover_proxy.py`
- 删除：`tests/contract/test_qq_official_adapter.py`
- 删除：`tests/contract/test_qq_webhook.py`
- 删除：`tests/unit/qq/`
- 删除：`tests/e2e/test_fake_qq_gateway.py`
- 修改：`src/anime_qqbot/entrypoints/cli.py`
- 修改：`src/anime_qqbot/settings.py`
- 修改：`pyproject.toml`
- 修改：`uv.lock`
- 新建：`migrations/versions/0007_remove_official_runtime.py`
- 新建：`tests/acceptance/test_no_official_qq_runtime.py`

**步骤**

1. 先写仓库扫描测试，禁止 `QQ_APP_ID`、`QQ_APP_SECRET`、openid、官方 webhook 和旧 bot role 回到活动源码、配置和 Compose。
2. 删除官方鉴权、webhook、gateway、media proxy、官方渲染和 fake gateway。
3. 删除只为官方协议存在的依赖；FastAPI/uvicorn 若仍由 worker 健康端点使用则保留。
4. 0007 按外键逆序删除旧 `delivery_attempts`、`notification_jobs`、`group_schedules`、`subscriptions`、`admin_identities`、`group_members`、`groups`、`processed_events`、`worker_heartbeats`。新 `chat_groups` 不受影响。
5. `downgrade()` 只恢复旧表结构，不恢复被明确放弃的数据。
6. 运行测试收集后删除或重写所有依赖旧 QQ 类型的测试；不得用 skip 掩盖。

**验证**

```bash
uv run pytest tests/acceptance/test_no_official_qq_runtime.py tests/integration/test_migrations.py
uv run pytest tests/unit tests/contract tests/e2e
make check
```

**提交**

```text
refactor: remove official qq bot runtime
```

### 任务 11：完成真实群查询 canary

**文件**

- 新建：`Dockerfile.astrbot`
- 修改：`.env.example`
- 修改：`compose.yaml`
- 新建：`docs/acceptance/v0.2.0-group-query.md`
- 修改：`tests/acceptance/test_compose_config.py`

**步骤**

1. 先核验并固定 AstrBot 与 NapCat 精确版本，禁止 `latest`。
2. Compose 暂时运行 postgres、migrate、napcat、astrbot、worker；NapCat 只在内部网络连接 `ws://astrbot:6199/ws` 并配置匹配 token。
3. QQ 登录数据、NapCat 配置和 AstrBot data/plugin 使用独立 volume。
4. 用户在 NapCat 控制台完成 QQ 登录；该步骤不自动化、不把凭据写入仓库。
5. 在测试群逐项执行查询命令，记录时间、版本、群消息截图或脱敏文本、数据库 UMO 记录和已知问题。

**验证**

```bash
docker compose config
docker compose up -d --wait postgres migrate worker astrbot napcat
docker compose ps
uv run pytest tests/acceptance/test_compose_config.py
```

**提交**

```text
test: verify astrbot group query canary
```

## 7. 分片三：接入 AniList 并完成字段融合

本分片的演示终点是：群内详情同时展示 Bangumi 中文信息和 AniList 国际信息；下一集优先使用 AniList 精确时刻；AniList 限流或故障时查询仍使用缓存和 Bangumi 降级。

### 任务 12：实现 AniList GraphQL 契约适配器

**文件**

- 新建：`src/anime_qqbot/catalog/adapters/anilist.py`
- 新建：`tests/contract/test_anilist_adapter.py`
- 新建：`tests/fixtures/anilist/media.json`
- 新建：`tests/fixtures/anilist/airing_schedule.json`
- 新建：`tests/fixtures/anilist/rate_limited.json`

**步骤**

1. 使用 httpx GraphQL POST 获取 Media、标题、季度、类型、公司、评分、热度、成人标记和 Airing Schedule。
2. 响应解析严格处理 GraphQL `errors`、partial data、HTTP 429、`Retry-After` 和限流响应头。
3. adapter 返回规范 DTO 和来源健康元数据，不返回 GraphQL 字典。
4. 默认不请求成人内容；响应若标记成人仍保存证据并阻止展示。
5. 契约测试只使用脱敏 fixture 和 mock transport，不访问线上。

**验证**

```bash
uv run pytest tests/contract/test_anilist_adapter.py
```

**提交**

```text
feat: add cached anilist source adapter
```

### 任务 13：增加 AniList 增量同步与限流调度

**文件**

- 修改：`src/anime_qqbot/catalog/sync.py`
- 修改：`src/anime_qqbot/catalog/adapters/http_policy.py`
- 修改：`src/anime_qqbot/entrypoints/worker.py`
- 新建：`tests/unit/catalog/test_anilist_sync.py`
- 新建：`tests/unit/catalog/test_source_rate_policy.py`
- 新建：`tests/integration/test_source_sync_state.py`

**步骤**

1. 活跃季度高频增量同步，历史季度低频刷新；游标和下一次允许请求时间保存到 `source_sync_states`。
2. 每轮请求遵守响应头剩余额度；429 使用 `Retry-After`，抖动退避不能阻塞其他来源。
3. Worker 每个来源独立错误边界和 heartbeat；AniList 失败不回滚已完成 Bangumi 同步。
4. partial data 保存可用字段，同时记录 source warning。
5. 测试冻结时钟下的预算耗尽、重启续跑、游标提交和错误恢复。

**验证**

```bash
uv run pytest tests/unit/catalog/test_anilist_sync.py tests/unit/catalog/test_source_rate_policy.py tests/integration/test_source_sync_state.py
```

**提交**

```text
feat: schedule resilient anilist sync
```

### 任务 14：匹配 Bangumi 与 AniList 来源

**文件**

- 修改：`src/anime_qqbot/catalog/matching.py`
- 修改：`src/anime_qqbot/catalog/sync.py`
- 新建：`tests/unit/catalog/test_bangumi_anilist_matching.py`
- 新建：`tests/integration/test_source_link_review.py`

**步骤**

1. 使用外部交叉 ID、标题集合、季度、年份、类型和集数形成可审计证据。
2. 强证据无冲突时 confirmed；相似标题但季度或类型冲突时 unresolved。
3. 管理员 confirm/reject 后自动同步不能覆盖人工决定。
4. 同一来源不能 confirmed 到两个 Anime；冲突写入待处理列表。
5. `/番剧 映射待处理` 只返回管理员可诊断摘要，不暴露原始 payload。

**验证**

```bash
uv run pytest tests/unit/catalog/test_bangumi_anilist_matching.py tests/integration/test_source_link_review.py
```

**提交**

```text
feat: link bangumi and anilist entries
```

### 任务 15：实现统一字段投影和来源新鲜度

**文件**

- 新建：`src/anime_qqbot/catalog/projection.py`
- 修改：`src/anime_qqbot/catalog/module.py`
- 修改：`src/anime_qqbot/catalog/repository.py`
- 新建：`tests/unit/catalog/test_projection_policy.py`
- 新建：`tests/e2e/test_fused_anime_details.py`

**步骤**

1. 按规格固定中文字段、国际字段、评分、时刻和成人标记的来源优先级。
2. 每个投影字段保留来源和 fetched_at，详情及状态可以展示数据新鲜度。
3. Airing Occurrence 去重时优先 exact datetime；日期记录不能覆盖 exact datetime。
4. 任一可信来源成人为 true 时统一投影 blocked；禁用记录不进入搜索和订阅。
5. E2E 覆盖完整融合、只有 Bangumi、只有 AniList、AniList 过期和来源冲突。

**验证**

```bash
uv run pytest tests/unit/catalog/test_projection_policy.py tests/e2e/test_fused_anime_details.py
make check
```

**提交**

```text
feat: project fused anime details
```

## 8. 分片四：完成群内订阅和预计放送提醒

本分片的演示终点是：群成员可以订阅内部 Anime；Worker 在精确预计放送时生成持久 outbox job；AstrBot 重启后使用保存的 UMO 主动向群内发送一条合并 `@` 消息。

### 任务 16：增加订阅、筛选和 outbox schema

**文件**

- 新建：`migrations/versions/0008_following_and_outbox.py`
- 修改：`src/anime_qqbot/persistence/models/subscriptions.py`
- 修改：`src/anime_qqbot/persistence/models/notifications.py`
- 修改：`src/anime_qqbot/persistence/models/runtime.py`
- 修改：`tests/integration/test_migrations.py`
- 新建：`tests/integration/test_following_constraints.py`

**步骤**

1. 重建新语义的 `worker_heartbeats`，并建立 `follow_subscriptions`、`subscription_resource_filters`、`notification_jobs`、`delivery_attempts`、`processed_platform_events`。
2. 订阅唯一键为 `(chat_group_id, external_user_id, anime_id)`，默认开启 airing 和 resource。
3. filter 保存语言 enum、字幕组数组和分辨率数组；空数组表示不限。
4. job 保存稳定 dedupe key、payload、状态、available_at、expires_at、lease owner/time、attempt count。
5. delivery attempt 保存平台结果分类和脱敏响应摘要；不保存 token。
6. 并发 claim 使用 `FOR UPDATE SKIP LOCKED` 或等价 PostgreSQL 机制。

**验证**

```bash
uv run pytest tests/integration/test_migrations.py tests/integration/test_following_constraints.py tests/integration/test_concurrent_job_claim.py
```

**提交**

```text
feat: add following and notification outbox schema
```

### 任务 17：实现群内订阅用例

**文件**

- 修改：`src/anime_qqbot/subscriptions/module.py`
- 修改：`src/anime_qqbot/subscriptions/repository.py`
- 修改：`src/anime_qqbot/groups/permissions.py`
- 修改：`src/anime_qqbot/application/module.py`
- 修改：`astrbot_plugin_anime_tracking/anime_tracking_plugin/commands.py`
- 新建：`tests/unit/subscriptions/test_follow_rules.py`
- 新建：`tests/e2e/test_astrbot_follow_commands.py`

**步骤**

1. 订阅、取消订阅、我的订阅和订阅设置全部限定当前 ChatGroup 和当前 QQ 用户。
2. 关键词唯一时可执行；多候选时要求内部 ID；blocked Anime 始终拒绝。
3. 重复订阅幂等并显示当前设置；取消不存在的订阅返回无副作用提示。
4. 固定命令状态变更无需二次确认；自然语言生成的状态变更必须走确认状态机。
5. 管理员判断使用普通 QQ 号和群成员角色，不使用 openid。

**验证**

```bash
uv run pytest tests/unit/subscriptions/test_follow_rules.py tests/e2e/test_astrbot_follow_commands.py
```

**提交**

```text
feat: manage group local anime follows
```

### 任务 18：形成有效放送计划并生成提醒任务

**文件**

- 修改：`src/anime_qqbot/catalog/projection.py`
- 修改：`src/anime_qqbot/notifications/planner.py`
- 修改：`src/anime_qqbot/notifications/module.py`
- 新建：`tests/unit/notifications/test_airing_planner.py`
- 新建：`tests/integration/test_airing_job_deduplication.py`

**步骤**

1. planner 只读取 confirmed Anime、有效订阅和 exact Airing Occurrence。
2. 同群、Anime、集数生成一个 dedupe key，受众在规划事务中形成稳定 QQ 用户列表。
3. 同一集来源时刻修正时，只保留当前有效 occurrence；已投递任务不重复发送。
4. available_at 为预计时刻，expires_at 为预计时刻后 2 小时。
5. 日期-only occurrence 只参与查询；测试证明其永不生成提醒任务。

**验证**

```bash
uv run pytest tests/unit/notifications/test_airing_planner.py tests/integration/test_airing_job_deduplication.py
```

**提交**

```text
feat: plan exact airing notifications
```

### 任务 19：实现可靠 outbox 租约和投递策略

**文件**

- 修改：`src/anime_qqbot/notifications/delivery.py`
- 修改：`src/anime_qqbot/notifications/module.py`
- 新建：`src/anime_qqbot/notifications/repository.py`
- 修改：`tests/unit/notifications/test_delivery_policy.py`
- 修改：`tests/integration/test_concurrent_job_claim.py`
- 修改：`tests/integration/test_delivery_attempts.py`

**步骤**

1. claim 只获取 available、未过期且无有效租约的任务；一次 claim 数量有上限。
2. 明确 success、retryable、permanent、unknown 四种结果；unknown 不盲目自动重发，进入人工诊断。
3. retryable 使用有上限的指数退避且不超过 expires_at；permanent 直接失败。
4. consumer 崩溃后租约超时可重新 claim；完成写入和 attempt 记录在同一事务。
5. 过期清理不删除审计记录，只标记 expired 并按保留周期归档。

**验证**

```bash
uv run pytest tests/unit/notifications/test_delivery_policy.py tests/integration/test_concurrent_job_claim.py tests/integration/test_delivery_attempts.py
```

**提交**

```text
feat: make notification outbox restart safe
```

### 任务 20：通过 AstrBot 主动发送预计放送提醒

**文件**

- 新建：`astrbot_plugin_anime_tracking/anime_tracking_plugin/dispatcher.py`
- 修改：`astrbot_plugin_anime_tracking/anime_tracking_plugin/lifecycle.py`
- 修改：`astrbot_plugin_anime_tracking/anime_tracking_plugin/rendering.py`
- 修改：`src/anime_qqbot/notifications/rendering.py`
- 新建：`tests/unit/astrbot/test_outbox_dispatcher.py`
- 新建：`tests/e2e/test_airing_notification_restart.py`

**步骤**

1. dispatcher 通过数据库租约消费任务，按 chat_group_id 读取最新 UMO。
2. 使用 `Context.send_message(unified_msg_origin, MessageChain)` 主动发送，并用 At 组件 `@` 本群受众。
3. 没有 UMO 的群保持 pending 并记录可操作错误；管理员需在该群执行一次命令刷新 UMO。
4. 消息明确使用“预计放送”，包含内部 ID、集数、计划时刻和数据来源，不承诺资源上线。
5. 测试模拟插件重启、UMO 刷新、重复 consumer、租约过期和 2 小时过期。

**验证**

```bash
uv run pytest tests/unit/astrbot/test_outbox_dispatcher.py tests/e2e/test_airing_notification_restart.py
```

**提交**

```text
feat: dispatch airing alerts through astrbot
```

## 9. 分片五：完成 Mikan 资源更新提醒

本分片的演示终点是：Worker 仅轮询有 confirmed Mikan link 且有资源订阅的公开 RSS；同番同集资源按 10 分钟窗口聚合并根据用户筛选投递。

### 任务 21：增加资源发布和聚合窗 schema

**文件**

- 新建：`migrations/versions/0009_resource_releases.py`
- 新建：`src/anime_qqbot/persistence/models/resources.py`
- 修改：`src/anime_qqbot/persistence/models/__init__.py`
- 新建：`tests/integration/test_resource_release_constraints.py`

**步骤**

1. 建立 `resource_releases` 和 `release_batches`。
2. release 保存 Mikan item ID、内容指纹、原始标题、解析字段、发布时间、发现时间、页面链接和处理状态。
3. item ID 与内容指纹分别唯一；RSS item 改 GUID 或重复返回时仍可幂等。
4. batch 唯一键覆盖 Anime、集数和窗口开始；状态为 open/ready/planned/suppressed。
5. 无法解析和未确认映射的记录仍保存，但不能进入 ready。

**验证**

```bash
uv run pytest tests/integration/test_migrations.py tests/integration/test_resource_release_constraints.py
```

**提交**

```text
feat: add mikan release storage
```

### 任务 22：实现安全的 Mikan RSS adapter

**文件**

- 新建：`src/anime_qqbot/resources/adapters/mikan.py`
- 新建：`tests/contract/test_mikan_adapter.py`
- 新建：`tests/fixtures/mikan/anime_rss.xml`
- 新建：`tests/fixtures/mikan/not_modified.txt`
- 修改：`pyproject.toml`
- 修改：`uv.lock`

**步骤**

1. 只请求公开的按番 RSS，不接受用户 token，不请求磁力内容。
2. 使用安全 XML parser，禁止外部实体；只提取 item 标识、标题、发布时间和 Mikan 页面链接。
3. 支持 ETag、Last-Modified 和 304；每个 feed 的 conditional metadata 保存到 sync state。
4. HTTP 错误、无效 XML 和空 feed 分开记录，不将一次坏响应覆盖已有数据。
5. adapter fixture 测试不得包含可下载直链或私人 token。

**验证**

```bash
uv run pytest tests/contract/test_mikan_adapter.py
```

**提交**

```text
feat: fetch public mikan anime feeds
```

### 任务 23：解析资源标题

**文件**

- 新建：`src/anime_qqbot/resources/models.py`
- 新建：`src/anime_qqbot/resources/parser.py`
- 新建：`tests/unit/resources/test_release_parser.py`
- 新建：`tests/fixtures/mikan/title_cases.json`

**步骤**

1. fixture 覆盖中日英标题、简繁标识、字幕组、多分辨率、HEVC、合集、特别篇、双集、无法识别集数和恶意超长标题。
2. parser 输出 episode、subtitle groups、language、resolutions、spec tags 和 parse warnings。
3. 解析结果允许 unknown；unknown episode 不触发通知，不根据猜测映射作品。
4. parser 纯计算、长度有上限且无正则灾难回溯。
5. 保存 parser version，规则升级后可离线重算未投递记录。

**验证**

```bash
uv run pytest tests/unit/resources/test_release_parser.py
```

**提交**

```text
feat: parse mikan release metadata
```

### 任务 24：按订阅需求同步并持久化 Mikan release

**文件**

- 新建：`src/anime_qqbot/resources/repository.py`
- 新建：`src/anime_qqbot/resources/module.py`
- 修改：`src/anime_qqbot/entrypoints/worker.py`
- 新建：`tests/unit/resources/test_mikan_poll_policy.py`
- 新建：`tests/integration/test_mikan_ingestion.py`

**步骤**

1. 轮询集合只包含资源提醒开启、存在 confirmed Mikan link 且 Anime 未 blocked 的记录。
2. 多个群订阅同一 Anime 只轮询一次 feed。
3. 每个 feed 独立 conditional cursor、退避和错误边界；一个坏 feed 不影响其他 feed。
4. 在事务中去重、解析、写 release 并打开或复用 batch。
5. 未 confirmed 的 Mikan link 进入映射待处理，不轮询、不推送。

**验证**

```bash
uv run pytest tests/unit/resources/test_mikan_poll_policy.py tests/integration/test_mikan_ingestion.py
```

**提交**

```text
feat: ingest subscribed mikan releases
```

### 任务 25：完成 10 分钟聚合、用户筛选和通知

**文件**

- 新建：`src/anime_qqbot/resources/batching.py`
- 修改：`src/anime_qqbot/notifications/planner.py`
- 修改：`src/anime_qqbot/notifications/rendering.py`
- 修改：`astrbot_plugin_anime_tracking/anime_tracking_plugin/rendering.py`
- 新建：`tests/unit/resources/test_release_batching.py`
- 新建：`tests/unit/subscriptions/test_resource_filters.py`
- 新建：`tests/e2e/test_mikan_notification.py`

**步骤**

1. 第一条同番同集 release 打开 10 分钟 batch；窗口内后续 release 加入同一 batch。
2. 窗口结束后按每个用户 filter 计算匹配集合和受众；无用户匹配时 batch suppressed。
3. 同群、Anime、集数和 batch 生成一个 job，expires_at 为 batch ready 后 24 小时。
4. 消息 `@` 有匹配的用户，最多显示 5 个资源，显示字幕组、语言、分辨率、发布时间和 Mikan 页面链接；其余显示数量。
5. 不显示磁力或下载直链；标题和 URL 在消息组件允许范围内截断和校验。
6. E2E 覆盖不同用户筛选、重复 RSS item、窗口重启、超过 5 条、无匹配和任务过期。

**验证**

```bash
uv run pytest tests/unit/resources/test_release_batching.py tests/unit/subscriptions/test_resource_filters.py tests/e2e/test_mikan_notification.py
make check
```

**提交**

```text
feat: send filtered batched mikan alerts
```

## 10. 分片六：生产部署、运维与最终验收

本分片的演示终点是：从空数据库可一键启动五个固定版本运行单元；从备份可恢复；状态命令可诊断来源、worker、consumer 和 UMO；真实测试群连续运行并完成查询、放送和 Mikan 提醒。

### 任务 26：收口配置、状态和可观察性

**文件**

- 修改：`src/anime_qqbot/settings.py`
- 修改：`src/anime_qqbot/logging.py`
- 修改：`src/anime_qqbot/entrypoints/health.py`
- 修改：`src/anime_qqbot/entrypoints/worker.py`
- 修改：`src/anime_qqbot/application/module.py`
- 新建：`tests/unit/test_v02_settings.py`
- 新建：`tests/e2e/test_status_command.py`

**步骤**

1. 类型化配置覆盖数据库、Bangumi、AniList、Mikan、同步周期、租约、过期窗口、时区和管理员 QQ。
2. status 返回各来源最新成功/失败、缓存年龄、worker heartbeat、AstrBot consumer heartbeat、pending/failed job 数和当前群 UMO 状态。
3. 健康检查区分 liveness 和 readiness；来源短时失败不让进程 liveness 失败。
4. 日志统一关联 source、anime_id、chat_group_id、job_id 和 attempt_id；QQ token、数据库口令、Authorization、RSS query secret 一律脱敏。
5. 状态命令不展示其他群用户、完整 UMO、密钥或原始外部响应。

**验证**

```bash
uv run pytest tests/unit/test_v02_settings.py tests/e2e/test_status_command.py
```

**提交**

```text
feat: expose multisource runtime health
```

### 任务 27：删除 v0.1 目录和 bangumi-data 兼容层

**文件**

- 新建：`migrations/versions/0010_remove_v01_catalog.py`
- 删除：`src/anime_qqbot/catalog/adapters/bangumi_data.py`
- 删除：`tests/contract/test_bangumi_data_adapter.py`
- 删除：`tests/fixtures/bangumi_data/`
- 修改：`src/anime_qqbot/catalog/sync.py`
- 修改：`pyproject.toml`
- 修改：`uv.lock`
- 修改：`NOTICE`
- 修改：`tests/acceptance/test_no_official_qq_runtime.py`

**步骤**

1. 确认所有在线查询和 worker 已只读写新目录表后，再删除 `anime_subjects`、旧 airing/cache/sync 表。
2. 删除 bangumi-data fallback 代码、fixture、配置、依赖和 NOTICE 条目；不保留双写。
3. `downgrade()` 恢复旧表结构但不恢复已放弃数据。
4. 仓库扫描验收禁止活动代码引用旧表名、BangumiData 或旧 subject 主键语义。
5. 从 0004 数据库执行 upgrade head，并从 base 执行完整往返。

**验证**

```bash
uv run pytest tests/integration/test_migrations.py tests/acceptance/test_no_official_qq_runtime.py
make check
```

**提交**

```text
refactor: remove v01 catalog compatibility
```

### 任务 28：完成固定版本五单元 Compose

**文件**

- 修改：`Dockerfile`
- 修改：`Dockerfile.astrbot`
- 修改：`compose.yaml`
- 修改：`compose.test.yaml`
- 修改：`.dockerignore`
- 修改：`.env.example`
- 修改：`tests/acceptance/test_compose_config.py`

**步骤**

1. `postgres` 使用固定 major/minor image，数据目录持久化且不暴露公网端口。
2. `migrate` 在 postgres healthy 后单次运行 `alembic upgrade head`；worker 和 astrbot 依赖 migrate 成功。
3. `napcat` 和 `astrbot` 使用已验证固定版本；OneBot token 通过环境注入，反向 WS 只走 Compose 内网。
4. `astrbot` 镜像安装本仓插件及其锁定 requirements；插件 data 与 AstrBot runtime data 持久化。
5. `worker` 只运行同步、规划和清理，不连接 QQ；健康端点只绑定内部网络。
6. 所有服务设置合理 restart policy、资源上限、健康检查和结构化日志，不把 secret 写入 image layer。

**验证**

```bash
docker compose config
docker compose build --pull
docker compose up -d --wait
docker compose ps
uv run pytest tests/acceptance/test_compose_config.py
```

**提交**

```text
ops: deploy astrbot tracking stack with compose
```

### 任务 29：建立备份、恢复和可回滚部署

**文件**

- 新建：`scripts/deploy-multisource.sh`
- 修改：`scripts/backup-postgres.sh`
- 修改：`scripts/restore-postgres.sh`
- 修改：`scripts/container-entrypoint.sh`
- 新建：`tests/acceptance/test_backup_restore.py`
- 修改：`tests/acceptance/test_operations_assets.py`

**步骤**

1. 新部署脚本预检 worktree、环境、固定 image、数据库备份和 Compose config，再 build 和 migrate。
2. 不修改或删除未跟踪的 `scripts/deploy-acr.sh`。
3. 备份包含 schema 版本和校验和；恢复必须面向显式数据库和显式备份文件，不接受宽泛目录。
4. 在临时 PostgreSQL 实例恢复备份，运行 `alembic current` 和关键行数检查。
5. 应用回滚只切换固定 image tag；数据库回滚仅在对应 migration downgrade 已于备份副本验证后执行。

**验证**

```bash
uv run pytest tests/acceptance/test_backup_restore.py tests/acceptance/test_operations_assets.py
bash -n scripts/deploy-multisource.sh scripts/backup-postgres.sh scripts/restore-postgres.sh
```

**提交**

```text
ops: add recoverable multisource deployment
```

### 任务 30：更新部署和运维文档

**文件**

- 修改：`README.md`
- 修改：`docs/deployment.md`
- 修改：`docs/operations.md`
- 新建：`docs/acceptance/v0.2.0.md`
- 修改：`CONTEXT.md`
- 新建：`tests/acceptance/test_v02_documentation.py`

**步骤**

1. README 只描述新产品基线、命令、架构、非目标和文档入口。
2. deployment 记录服务器前置条件、环境配置、QQ 小号登录、NapCat reverse WS、AstrBot plugin、首次迁移和测试群 canary。
3. operations 记录备份恢复、版本升级、UMO 缺失、QQ 掉线、来源限流、待处理映射、unknown 投递、手工过期和日志诊断。
4. acceptance 文档逐项映射规格验收条件、自动命令和必须由用户完成的 QQ 控制台步骤。
5. 文档禁止保留 QQ AppID/Secret、openid、官方消息按钮或旧部署路径作为活动说明。

**验证**

```bash
uv run pytest tests/acceptance/test_v02_documentation.py
rg -n "QQ_APP_ID|QQ_APP_SECRET|openid|官方机器人" README.md docs .env.example compose.yaml
```

`rg` 结果只能出现在明确标记为历史迁移说明或“已移除”的验收断言中。

**提交**

```text
docs: document astrbot multisource operations
```

### 任务 31：执行自动化最终验收

**文件**

- 新建：`tests/acceptance/test_v02_commands.py`
- 新建：`tests/acceptance/test_v02_security.py`
- 新建：`tests/acceptance/test_v02_resilience.py`
- 修改：`docs/acceptance/v0.2.0.md`

**步骤**

1. 从空 volume 启动整套 Compose，确认 migrate 成功且五个运行单元达到预期状态。
2. 使用 fake AstrBot 和冻结时钟执行全部固定命令、精确放送、日期-only、Mikan 聚合、筛选和过期场景。
3. 在通知 claim 后强制重启 AstrBot，验证租约恢复、无重复成功投递和 UMO 可复用。
4. 分别模拟 Bangumi、AniList、Mikan 超时、429 和坏 payload，验证来源隔离和缓存降级。
5. 扫描 image、日志、数据库 attempt 和仓库，确认无 QQ/OneBot token、口令、私有 RSS token、磁力直链。
6. 对 0004 快照和空数据库分别执行 upgrade head；执行 base/head 往返。

**验证**

```bash
make check
uv run pytest tests/acceptance
docker compose config --quiet
docker compose up -d --wait
docker compose ps
docker compose logs --since 10m migrate worker astrbot
git diff --check main...HEAD
```

**提交**

```text
test: close v02 automated acceptance
```

### 任务 32：执行真实测试群发布 canary

**文件**

- 修改：`docs/acceptance/v0.2.0.md`

**步骤**

1. 使用专用 QQ 小号和非生产测试群，由用户完成登录和入群。
2. 执行全部固定查询和订阅命令，确认普通成员与管理员权限。
3. 至少观察一次真实或通过预置测试数据触发的精确预计放送提醒，确认合并 `@`、措辞、2 小时过期和重启恢复。
4. 至少观察一次真实 Mikan feed 更新，确认 10 分钟聚合、用户筛选、最多 5 条和 24 小时过期。
5. 在 canary 期间分别重启 worker 和 astrbot，并短时断开 NapCat；恢复后确认无业务事实丢失和无重复成功消息。
6. 连续观察至少 24 小时，记录来源成功率、pending/failed/unknown jobs、QQ 重连和人工映射项。
7. 所有阻断问题使用独立 `codex/fix/<topic>` 分支修复并重新运行受影响验收。

**验证**

```bash
docker compose ps
docker compose logs --since 24h worker astrbot napcat
uv run python -m anime_qqbot.entrypoints.cli migrate
make check
```

文档记录用户确认、观测起止时间、镜像 digest、数据库 revision 和最终结论。

**提交**

```text
release: accept astrbot multisource tracking v02
```

## 11. 迁移和切换顺序

生产切换必须严格遵循：

1. 停止旧官方 bot 和旧 worker，创建可恢复 PostgreSQL 备份。
2. 部署包含 0005 和 0006 的查询版本，验证新内部目录和测试群 UMO。
3. 确认 AstrBot 查询链路稳定后应用 0007，删除旧官方身份、订阅和通知运行表。
4. 应用 0008，开放重新订阅和预计放送提醒。
5. 应用 0009，开放 Mikan 资源提醒。
6. 确认所有代码只依赖新目录后应用 0010，删除 v0.1 目录兼容表和 bangumi-data。
7. 完成 24 小时 canary 后才将 v0.2.0 标记为正式基线。

本版本不迁移旧群、openid 和订阅。切换前必须在群内提前告知用户新机器人上线后需要重新订阅。

## 12. 风险门和暂停条件

遇到以下情况应暂停对应分片，不得用临时硬编码继续：

1. AstrBot 当前版本无法通过保存的 UMO 在重启后主动发群消息。
2. NapCat 与 AstrBot 固定版本的 OneBot 11 reverse WS 协议不兼容。
3. AniList 或 Mikan 契约与 fixture 显著不同，且无法确定安全解析边界。
4. 标题匹配对同名、续作或季度冲突产生自动误合并。
5. PostgreSQL migration 无法从真实 0004 快照升级，或 downgrade 破坏新表之外的数据。
6. unknown 投递会导致无法判断是否重复发送。
7. 成人标记或禁用状态在任一查询、订阅或通知路径被绕过。
8. Compose 需要把数据库、健康端点或 OneBot token 暴露到公网。

暂停时保留失败 fixture、日志、数据库 revision 和最小复现；修正设计或 adapter 契约后再继续，不扩大产品范围。

## 13. 开发 Agent 交接格式

每次只领取一个任务或一个紧密相邻的任务组。交接必须包含：

- 当前分支和基线提交；
- 对应任务编号与不可变验收条件；
- 实际修改文件；
- 先失败、后通过的定向测试命令；
- `make check-fast` 或 `make check` 结果；
- migration revision、Compose image digest 或外部契约 fixture（如适用）；
- 未完成项、已知风险和任何需要用户完成的 QQ 控制台步骤；
- `git status --short`，明确说明未触碰 `scripts/deploy-acr.sh`。

不得把“代码已写完”作为完成证明；每个分片必须交付其声明的真实纵向演示能力。

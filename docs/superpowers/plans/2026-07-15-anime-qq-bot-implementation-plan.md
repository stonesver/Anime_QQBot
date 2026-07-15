# QQ 追番机器人实施计划

- 日期：2026-07-15
- 状态：待实施
- 对应规格：[QQ 追番机器人设计规格](../specs/2026-07-15-anime-qq-bot-design.md)
- 目标版本：v0.1.0
- 当前基线提交：`368efe2`

## 1. 实施原则

1. `main` 始终保持可检查、可部署；实现只在 feature/fix 分支进行。
2. 每个任务先添加失败测试或可执行验收，再实现最小代码使其通过。
3. 外部平台只存在于适配器后面；领域模块和测试不导入 QQ SDK、httpx 或 SQLAlchemy 实现细节。
4. PostgreSQL 是生产和集成测试的事实来源；不以 SQLite 代替并发锁、唯一约束和迁移验证。
5. QQ、Bangumi 和 bangumi-data 的契约测试使用脱敏固定 fixture，不依赖线上服务。
6. 所有时间以带时区的 UTC datetime 入库，展示时才转换为群时区。
7. 所有密钥只从环境读取，测试和日志不得输出密钥、Access Token 或完整开放平台响应头。
8. v0.1.0 不实现 Agent、MCP、Web 后台、AniList 或私聊主动订阅。

## 2. 目标目录结构

```text
.
├── .env.example
├── .dockerignore
├── Dockerfile
├── Makefile
├── NOTICE
├── README.md
├── alembic.ini
├── compose.yaml
├── compose.test.yaml
├── pyproject.toml
├── uv.lock
├── migrations/
│   ├── env.py
│   └── versions/
├── scripts/
│   ├── backup-postgres.sh
│   ├── container-entrypoint.sh
│   └── restore-postgres.sh
├── src/anime_qqbot/
│   ├── settings.py
│   ├── logging.py
│   ├── clock.py
│   ├── catalog/
│   ├── commands/
│   ├── groups/
│   ├── notifications/
│   ├── persistence/
│   ├── qq/
│   ├── scheduling/
│   └── entrypoints/
├── tests/
│   ├── acceptance/
│   ├── contract/
│   ├── e2e/
│   ├── integration/
│   └── unit/
└── docs/
    ├── deployment.md
    ├── operations.md
    └── acceptance/v0.1.0.md
```

`__init__.py` 只导出每个深模块的小接口和领域类型；适配器、ORM 模型和内部帮助函数不从包根导出。

## 3. Git 分支与合并顺序

按以下顺序创建、检查并合并：

1. `feat/project-foundation`
2. `feat/anime-catalog`
3. `feat/qq-commands-and-subscriptions`
4. `feat/scheduled-notifications`
5. `feat/docker-deployment`
6. 验收问题使用独立 `fix/<topic>`

每个分支结束时执行：

```bash
make check
git diff --check main...HEAD
git diff --stat main...HEAD
git switch main
git merge --no-ff <branch>
```

不在计划中自动删除已合并分支；用户确认发布后再决定是否保留。

## 4. 分支一：项目基础

### 任务 1：建立 Python 工程和统一检查入口

**文件**

- 新建：`pyproject.toml`
- 新建：`uv.lock`
- 新建：`Makefile`
- 新建：`README.md`
- 新建：`src/anime_qqbot/__init__.py`
- 新建：`tests/unit/test_package.py`
- 修改：`.gitignore`

**步骤**

1. 创建 `feat/project-foundation` 分支。
2. 在 `pyproject.toml` 声明 Python 3.12、运行依赖和 dev 依赖；首批包括 FastAPI、Pydantic Settings、SQLAlchemy、Alembic、asyncpg、httpx、pytest、pytest-asyncio、Ruff 和 mypy。
3. 使用 uv 生成并提交锁文件；生产依赖必须有确定版本解析结果。
4. 添加最小包导入测试，先验证 `import anime_qqbot`。
5. README 记录项目目标、当前状态、非目标、设计规格入口和本地开发前置条件。
6. `Makefile` 提供 `format`、`lint`、`typecheck`、`test-unit` 和 `check-fast`。
7. 配置 Ruff、mypy 和 pytest；禁止测试默认访问网络。

**验证**

```bash
uv sync --frozen
make check-fast
```

**提交**

```text
chore: scaffold python project and quality checks
```

### 任务 2：实现类型化配置、时钟和脱敏日志

**文件**

- 新建：`.env.example`
- 新建：`src/anime_qqbot/settings.py`
- 新建：`src/anime_qqbot/clock.py`
- 新建：`src/anime_qqbot/logging.py`
- 新建：`tests/unit/test_settings.py`
- 新建：`tests/unit/test_clock.py`
- 新建：`tests/unit/test_logging.py`

**步骤**

1. 先测试必需配置缺失、默认时区、缓存 TTL、扫描周期和管理员身份解析。
2. `Settings` 读取 QQ、数据库、Bangumi User-Agent、可选 Token、同步周期、补偿窗口和保留周期。
3. 提供 `Clock` Protocol 和 `SystemClock`/`FrozenClock`，领域测试不直接调用系统时间。
4. 配置结构化日志；对键名包含 `secret`、`token`、`authorization`、`password` 的值统一脱敏。
5. `.env.example` 只放占位值和说明，不放可用密钥。

**验证**

```bash
uv run pytest tests/unit/test_settings.py tests/unit/test_clock.py tests/unit/test_logging.py
uv run mypy src
```

**提交**

```text
feat: add typed settings clock and redacted logging
```

### 任务 3：建立 PostgreSQL、SQLAlchemy 和 Alembic 基线

**文件**

- 新建：`compose.test.yaml`
- 新建：`alembic.ini`
- 新建：`migrations/env.py`
- 新建：`migrations/script.py.mako`
- 新建：`migrations/versions/0001_identity_and_runtime.py`
- 新建：`src/anime_qqbot/persistence/base.py`
- 新建：`src/anime_qqbot/persistence/session.py`
- 新建：`src/anime_qqbot/persistence/models/identity.py`
- 新建：`src/anime_qqbot/persistence/models/runtime.py`
- 新建：`tests/integration/test_migrations.py`
- 新建：`tests/integration/test_identity_constraints.py`

**步骤**

1. `compose.test.yaml` 提供隔离的 PostgreSQL test 服务和健康检查。
2. 建立 async SQLAlchemy session factory；应用层通过显式事务使用 session。
3. 第一条迁移创建 `groups`、`group_members`、`admin_identities`、`processed_events` 和 `worker_heartbeats`。
4. 使用数据库唯一约束保护 group/member、管理员身份和平台事件 ID。
5. 集成测试从空数据库执行 `upgrade head`，再执行一次 downgrade/upgrade 往返。
6. 测试重复事件插入只产生一条业务记录。

**验证**

```bash
docker compose -f compose.test.yaml up -d postgres-test
uv run alembic upgrade head
uv run pytest tests/integration/test_migrations.py tests/integration/test_identity_constraints.py
docker compose -f compose.test.yaml down -v
```

**提交**

```text
feat: add postgres persistence and initial migrations
```

### 任务 4：完成基础分支检查与合并

**文件**

- 修改：`Makefile`
- 新建：`tests/conftest.py`

**步骤**

1. 添加 PostgreSQL 测试 fixture、自动迁移和事务清理。
2. `make check` 串联快速检查、集成测试、迁移检查和 Compose 配置检查。
3. 从干净环境执行完整检查。
4. 审查分支 diff，确认没有 QQ 或 Bangumi 业务提前混入。
5. 合并到 `main`。

**验证**

```bash
make check
git diff --check main...HEAD
```

**提交**

```text
test: add reproducible postgres integration harness
```

## 5. 分支二：番剧目录

### 任务 5：定义 AnimeCatalog 的小接口和领域类型

**文件**

- 新建：`src/anime_qqbot/catalog/__init__.py`
- 新建：`src/anime_qqbot/catalog/models.py`
- 新建：`src/anime_qqbot/catalog/ports.py`
- 新建：`src/anime_qqbot/catalog/module.py`
- 新建：`tests/unit/catalog/test_catalog_interface.py`
- 新建：`tests/unit/catalog/test_season_and_timezone.py`

**步骤**

1. 用测试固定四季边界、跨年周、IANA 时区转换和中文标题回退规则。
2. 定义 `AnimeSummary`、`AnimeDetail`、`AiringOccurrence`、`Season` 和 `CatalogFreshness`。
3. AnimeCatalog 的公开接口只包含 `search`、`get_detail`、`list_day`、`list_week`、`list_season` 和 `get_next_airing`。
4. provider 端口返回规范化类型，不把 Bangumi 原始 JSON 暴露给调用方。
5. 对 NSFW 条目在模块内部统一过滤。

**验证**

```bash
uv run pytest tests/unit/catalog
uv run mypy src/anime_qqbot/catalog
```

**提交**

```text
feat: define anime catalog domain interface
```

### 任务 6：实现 Bangumi API 适配器

**文件**

- 新建：`src/anime_qqbot/catalog/adapters/bangumi.py`
- 新建：`src/anime_qqbot/catalog/adapters/http_policy.py`
- 新建：`tests/fixtures/bangumi/calendar.json`
- 新建：`tests/fixtures/bangumi/search.json`
- 新建：`tests/fixtures/bangumi/subject.json`
- 新建：`tests/fixtures/bangumi/episodes.json`
- 新建：`tests/contract/test_bangumi_adapter.py`

**步骤**

1. 先以 fixture 固定 calendar、search、subject 和 episodes 的字段映射。
2. 强制发送配置的 User-Agent；可选 Bearer Token 只在配置存在时加入。
3. 每次请求设置连接和总超时；把 429、可重试 5xx、永久 4xx 和解析错误映射为内部错误类型。
4. 搜索请求在接口支持处传 `nsfw=false`，并再次本地过滤。
5. 不把 HTTP 状态码判断散落到 AnimeCatalog 调用方。

**验证**

```bash
uv run pytest tests/contract/test_bangumi_adapter.py
```

**提交**

```text
feat: add bangumi api adapter
```

### 任务 7：实现 bangumi-data 适配器和 ID 映射

**文件**

- 新建：`src/anime_qqbot/catalog/adapters/bangumi_data.py`
- 新建：`tests/fixtures/bangumi_data/season.json`
- 新建：`tests/contract/test_bangumi_data_adapter.py`
- 新建：`tests/unit/catalog/test_source_mapping.py`
- 新建：`NOTICE`

**步骤**

1. 用最小 fixture 覆盖 `begin`、`broadcast`、多站点、地区、缺失时间和 Bangumi site ID。
2. 只通过 Bangumi site ID 建立自动强关联；没有 ID 时不得仅凭标题写入强关联。
3. 把时刻解析为带时区 datetime，并保存来源和更新时间。
4. 对缺失或非法 broadcast 规则返回 date-only 降级，而不是猜测时刻。
5. 在 `NOTICE` 标注 bangumi-data 和 CC BY 4.0 来源。

**验证**

```bash
uv run pytest tests/contract/test_bangumi_data_adapter.py tests/unit/catalog/test_source_mapping.py
```

**提交**

```text
feat: add bangumi-data airing schedule adapter
```

### 任务 8：持久化目录缓存并实现同步

**文件**

- 新建：`migrations/versions/0002_catalog_cache.py`
- 新建：`src/anime_qqbot/persistence/models/catalog.py`
- 新建：`src/anime_qqbot/catalog/repository.py`
- 新建：`src/anime_qqbot/catalog/sync.py`
- 新建：`tests/integration/test_catalog_repository.py`
- 新建：`tests/unit/catalog/test_sync_fallback.py`

**步骤**

1. 迁移创建 `anime_subjects` 和 `airing_schedules`，以 Bangumi subject ID 和 occurrence 建唯一约束。
2. Repository 在一个事务中写入新快照；失败不能清空最后成功数据。
3. Sync service 分别记录两个 provider 的同步状态和时间。
4. 测试 Bangumi 成功/bangumi-data 失败、反向失败、双失败和恢复后的行为。
5. 实现 24/48 小时陈旧判断。

**验证**

```bash
uv run alembic upgrade head
uv run pytest tests/integration/test_catalog_repository.py tests/unit/catalog/test_sync_fallback.py
```

**提交**

```text
feat: persist catalog cache and resilient sync state
```

### 任务 9：完成日、周、季度和下一次放送查询

**文件**

- 修改：`src/anime_qqbot/catalog/module.py`
- 新建：`tests/unit/catalog/test_queries.py`
- 新建：`tests/e2e/test_catalog_queries.py`

**步骤**

1. 覆盖指定日期、当前周、季度边界、无结果、陈旧数据和 date-only 降级测试。
2. 搜索结果使用中文名优先、日文名回退，并保留 Bangumi ID。
3. 下一次放送优先返回 bangumi-data occurrence；缺失时返回 Bangumi episode airdate。
4. E2E 测试使用 fake providers + PostgreSQL，从同步到查询结果完整运行。
5. 完整检查并合并 `feat/anime-catalog`。

**验证**

```bash
make check
git diff --check main...HEAD
```

**提交**

```text
feat: add daily weekly seasonal and next-airing queries
```

## 6. 分支三：QQ 命令与订阅

### 任务 10：定义 QQGateway 和标准化事件

**文件**

- 新建：`src/anime_qqbot/qq/__init__.py`
- 新建：`src/anime_qqbot/qq/contracts.py`
- 新建：`src/anime_qqbot/qq/gateway.py`
- 新建：`src/anime_qqbot/qq/fake.py`
- 新建：`tests/unit/qq/test_contracts.py`
- 新建：`tests/e2e/test_fake_qq_gateway.py`

**步骤**

1. 定义 group-at、C2C、button interaction、group-add/remove、active-message-enabled/disabled 事件。
2. 标准化上下文包含 event ID、message ID、group openid、user/member openid、member role 和回复截止时间。
3. `QQGateway` 公开被动回复、主动群消息和按钮消息；错误只暴露内部分类。
4. FakeQQGateway 记录发送内容、模拟限频/永久/不确定结果，供后续 E2E 使用。
5. 领域模块不得导入官方 SDK DTO。

**验证**

```bash
uv run pytest tests/unit/qq tests/e2e/test_fake_qq_gateway.py
```

**提交**

```text
feat: define qq gateway seam and normalized events
```

### 任务 11：实现确定性命令解析和 Agent 预留 seam

**文件**

- 新建：`src/anime_qqbot/commands/models.py`
- 新建：`src/anime_qqbot/commands/parser.py`
- 新建：`src/anime_qqbot/commands/agent.py`
- 新建：`src/anime_qqbot/commands/router.py`
- 新建：`tests/unit/commands/test_parser.py`
- 新建：`tests/unit/commands/test_agent_disabled.py`

**步骤**

1. 先覆盖所有查询、订阅和群管理命令，以及空格、别名、日期、季节和非法参数。
2. 群上下文只接受明确 `@机器人` 的消息；私聊上下文接受查询命令。
3. 未识别命令返回帮助，不调用外部模型。
4. 定义最小 `AgentRuntime` Protocol 和 `DisabledAgentRuntime`；默认配置必须禁用且不引入模型依赖。
5. Router 只消费结构化 command intent，不把权限和数据库逻辑放进 parser。

**验证**

```bash
uv run pytest tests/unit/commands
```

**提交**

```text
feat: add deterministic command routing with disabled agent seam
```

### 任务 12：实现群身份、权限和事件去重

**文件**

- 新建：`src/anime_qqbot/groups/module.py`
- 新建：`src/anime_qqbot/groups/repository.py`
- 新建：`src/anime_qqbot/groups/permissions.py`
- 新建：`src/anime_qqbot/commands/event_processor.py`
- 新建：`tests/unit/groups/test_permissions.py`
- 新建：`tests/integration/test_event_deduplication.py`

**步骤**

1. 用测试固定 owner/admin/member 和 bootstrap identity 的权限矩阵。
2. 接收事件时 upsert group/member 和最近角色。
3. 在执行命令前尝试插入 processed event；唯一冲突直接返回已处理结果。
4. 主动消息关闭事件暂停群状态；重新开启事件恢复允许状态，但不自动开启业务计划。
5. 验证重复订阅消息事件不会执行两次或回复两次。

**验证**

```bash
uv run pytest tests/unit/groups tests/integration/test_event_deduplication.py
```

**提交**

```text
feat: add group identity permissions and event deduplication
```

### 任务 13：实现群内订阅模块

**文件**

- 新建：`migrations/versions/0003_subscriptions.py`
- 新建：`src/anime_qqbot/persistence/models/subscriptions.py`
- 新建：`src/anime_qqbot/subscriptions/module.py`
- 新建：`src/anime_qqbot/subscriptions/repository.py`
- 新建：`tests/unit/subscriptions/test_subscription_rules.py`
- 新建：`tests/integration/test_subscription_repository.py`

**步骤**

1. 迁移创建 group/member/subject 唯一订阅约束和 enabled 状态。
2. 订阅相同番剧两次返回幂等结果；取消后再订阅恢复原记录。
3. 私聊上下文尝试订阅时返回“请在目标群中订阅”。
4. 退出群或机器人被移除时保留历史但禁用相关活动订阅/计划。
5. `我的订阅` 只返回当前群当前 member 的记录。

**验证**

```bash
uv run alembic upgrade head
uv run pytest tests/unit/subscriptions tests/integration/test_subscription_repository.py
```

**提交**

```text
feat: add group-scoped anime subscriptions
```

### 任务 14：实现查询与订阅消息渲染和处理器

**文件**

- 新建：`src/anime_qqbot/commands/handlers.py`
- 新建：`src/anime_qqbot/qq/rendering.py`
- 新建：`tests/unit/qq/test_rendering.py`
- 新建：`tests/e2e/test_query_commands.py`
- 新建：`tests/e2e/test_subscription_commands.py`

**步骤**

1. 渲染器只接收结构化结果，生成文本/Markdown/按钮，不查询数据库。
2. 覆盖今日、本周、季度、搜索、详情、下次更新、帮助和无结果消息。
3. 多候选搜索生成按钮；按钮回调仍转换成结构化 command intent。
4. 所有番剧展示再次检查 NSFW 状态并包含必要的“预计放送”提示。
5. E2E 从 FakeQQGateway 事件跑到回复，覆盖私聊查询和群聊订阅。

**验证**

```bash
uv run pytest tests/unit/qq/test_rendering.py tests/e2e/test_query_commands.py tests/e2e/test_subscription_commands.py
```

**提交**

```text
feat: add qq query and subscription handlers
```

### 任务 15：接入 QQ 官方适配器和 bot 入口

**文件**

- 新建：`src/anime_qqbot/qq/official.py`
- 新建：`src/anime_qqbot/qq/auth.py`
- 新建：`src/anime_qqbot/entrypoints/bot.py`
- 新建：`src/anime_qqbot/entrypoints/health.py`
- 新建：`tests/fixtures/qq/events/*.json`
- 新建：`tests/contract/test_qq_official_adapter.py`
- 新建：`tests/unit/entrypoints/test_bot_lifecycle.py`

**步骤**

1. 用官方事件 fixture 固定 group-at、C2C、button interaction、角色和主动消息开关映射。
2. 增加所需的 QQ 官方 SDK 依赖并更新 `uv.lock`；实现 AppID/AppSecret 获取和刷新 Access Token，日志不得输出凭证。
3. 使用 WebSocket 建立连接、心跳、重连和会话恢复，并把 SDK DTO 映射为内部事件。
4. OpenAPI 发送封装被动回复、主动群消息、Markdown 和按钮。
5. bot 入口组装依赖、启动内部 health app，并在 SIGTERM 时停止接收新事件后安全退出。
6. 只运行契约测试时不需要真实 QQ 凭证。

**验证**

```bash
uv run pytest tests/contract/test_qq_official_adapter.py tests/unit/entrypoints/test_bot_lifecycle.py
make check
```

**人工检查点 A：QQ 沙箱**

用户在本地 `.env` 配置 QQ 沙箱凭证后验证：机器人上线、群 `@` 查询、私聊查询、订阅、重复事件不重复回复。凭证不提交 Git。

**提交**

```text
feat: connect official qq gateway and bot runtime
```

完成检查后合并 `feat/qq-commands-and-subscriptions`。

## 7. 分支四：持久化定时通知

### 任务 16：实现群计划和下一次执行时间

**文件**

- 新建：`migrations/versions/0004_schedules_and_notifications.py`
- 新建：`src/anime_qqbot/persistence/models/notifications.py`
- 新建：`src/anime_qqbot/scheduling/module.py`
- 新建：`src/anime_qqbot/scheduling/repository.py`
- 新建：`tests/unit/scheduling/test_next_run.py`
- 新建：`tests/integration/test_schedule_repository.py`

**步骤**

1. 迁移创建 `group_schedules`、`notification_jobs` 和 `delivery_attempts`。
2. 用 FrozenClock 覆盖每日、每周、DST、修改时区、禁用和错过窗口。
3. next_run_at 始终以 UTC 保存；显示时使用群 IANA 时区。
4. 相同 occurrence 的 notification job 由唯一约束保护。
5. 群主动消息关闭时不生成可发送任务，计划本身保留。

**验证**

```bash
uv run alembic upgrade head
uv run pytest tests/unit/scheduling tests/integration/test_schedule_repository.py
```

**提交**

```text
feat: add persistent group schedules and notification jobs
```

### 任务 17：实现并发安全的 worker 领取与心跳

**文件**

- 新建：`src/anime_qqbot/scheduling/worker.py`
- 新建：`src/anime_qqbot/entrypoints/worker.py`
- 新建：`tests/integration/test_concurrent_job_claim.py`
- 新建：`tests/integration/test_worker_recovery.py`
- 新建：`tests/integration/test_retention_cleanup.py`
- 新建：`tests/unit/entrypoints/test_worker_lifecycle.py`

**步骤**

1. 使用 `FOR UPDATE SKIP LOCKED` 或等价 PostgreSQL 语义领取 due jobs。
2. 两个 worker 并发时同一 job 只能被一个 worker 领取。
3. processing lease 超时后允许安全恢复；每次状态迁移记录时间。
4. worker 每个心跳周期更新 `worker_heartbeats`。
5. SIGTERM 停止领取新任务，允许当前数据库事务完成。
6. worker 定期清理 7 天前的 processed events，以及 90 天前已终结的 notification jobs 和 delivery attempts；活动订阅、群配置和未终结任务不得被清理。

**验证**

```bash
uv run pytest tests/integration/test_concurrent_job_claim.py tests/integration/test_worker_recovery.py tests/integration/test_retention_cleanup.py tests/unit/entrypoints/test_worker_lifecycle.py
```

**提交**

```text
feat: add durable worker claiming and recovery
```

### 任务 18：生成合并通知和群内 @ 列表

**文件**

- 新建：`src/anime_qqbot/notifications/module.py`
- 新建：`src/anime_qqbot/notifications/rendering.py`
- 新建：`tests/unit/notifications/test_audience_merge.py`
- 新建：`tests/unit/notifications/test_message_chunking.py`
- 新建：`tests/e2e/test_scheduled_notification.py`

**步骤**

1. 按群、番剧、occurrence 合并订阅用户，不为每个用户单独发消息。
2. 移除已禁用订阅、退群成员和 NSFW 条目。
3. 超过 QQ 单条消息容量时按番剧边界拆分，并给每片稳定序号。
4. 文案明确“预计放送”、目标时区、数据更新时间和可能延迟提示。
5. E2E 覆盖多个用户订阅同一番、同一用户订阅多番和无订阅者跳过。

**验证**

```bash
uv run pytest tests/unit/notifications tests/e2e/test_scheduled_notification.py
```

**提交**

```text
feat: build merged scheduled anime notifications
```

### 任务 19：实现投递错误分类、重试和 unknown 状态

**文件**

- 新建：`src/anime_qqbot/notifications/delivery.py`
- 新建：`tests/unit/notifications/test_delivery_policy.py`
- 新建：`tests/integration/test_delivery_attempts.py`
- 新建：`tests/e2e/test_ambiguous_delivery.py`

**步骤**

1. 发送前写 delivery attempt，再调用 QQGateway。
2. 429 按 retry-after/内部退避延后；明确未发送的网络错误和可重试 5xx 最多尝试 3 次。
3. 权限、参数和内容审核错误进入 failed，不无限重试。
4. 请求可能已送达但响应丢失时进入 unknown，不自动重发。
5. 同一 job 重启恢复时读取已有 attempt，不能盲目再次发送。

**验证**

```bash
uv run pytest tests/unit/notifications/test_delivery_policy.py tests/integration/test_delivery_attempts.py tests/e2e/test_ambiguous_delivery.py
```

**提交**

```text
feat: add safe notification delivery and retry policy
```

### 任务 20：接入群管理命令和手动补发

**文件**

- 修改：`src/anime_qqbot/commands/handlers.py`
- 修改：`src/anime_qqbot/commands/parser.py`
- 新建：`tests/e2e/test_group_schedule_commands.py`
- 新建：`tests/e2e/test_manual_redelivery.py`

**步骤**

1. 实现开启/关闭每日、每周推送，设置时区和查看状态。
2. 所有写命令先通过 PermissionPolicy；普通成员调用返回权限错误。
3. `立即推送今日番剧` 创建独立 manual occurrence，仍使用业务唯一键。
4. unknown 任务只允许管理员明确补发，并留下新 delivery attempt 与操作者信息。
5. 完成重启恢复和并发测试后合并 `feat/scheduled-notifications`。

**验证**

```bash
make check
git diff --check main...HEAD
```

**提交**

```text
feat: add group schedule administration commands
```

## 8. 分支五：生产 Docker 部署

### 任务 21：构建非 root 镜像和 Compose 运行拓扑

**文件**

- 新建：`Dockerfile`
- 新建：`.dockerignore`
- 新建：`compose.yaml`
- 新建：`scripts/container-entrypoint.sh`
- 修改：`Makefile`
- 新建：`tests/acceptance/test_compose_config.py`

**步骤**

1. 多阶段构建 Python 3.12 slim 镜像，并以非 root UID 运行。
2. 同一镜像支持 `migrate`、`bot` 和 `worker` 命令。
3. Compose 中 migrate 成功后才启动 bot/worker；PostgreSQL 使用命名卷。
4. 配置 bot、worker、postgres healthcheck 和 `restart: unless-stopped`。
5. 设置 JSON 文件日志轮转；应用日志继续输出 stdout/stderr。
6. `.dockerignore` 排除 `.env`、`.git`、测试缓存、备份和可视化目录。

**验证**

```bash
docker compose config
docker build -t anime-qqbot:dev .
uv run pytest tests/acceptance/test_compose_config.py
```

**提交**

```text
feat: add production docker runtime topology
```

### 任务 22：提供备份、恢复、升级和运行手册

**文件**

- 新建：`scripts/backup-postgres.sh`
- 新建：`scripts/restore-postgres.sh`
- 新建：`docs/deployment.md`
- 新建：`docs/operations.md`
- 新建：`tests/acceptance/test_scripts.py`

**步骤**

1. 备份脚本创建带时间戳的压缩 pg_dump，并清理 7 天前备份。
2. 恢复脚本要求显式指定文件并在覆盖前二次确认；测试使用临时数据库。
3. 三个 shell 脚本提交为可执行文件，并使用严格错误处理和安全引用。
4. deployment 文档覆盖服务器要求、固定出口 IP、QQ 后台配置、`.env`、构建、迁移和启动。
5. operations 文档覆盖健康检查、日志、unknown 投递、手动补发、备份恢复和升级回退。
6. 脚本测试验证参数、失败退出码和不泄露密码。

**验证**

```bash
uv run pytest tests/acceptance/test_scripts.py
shellcheck scripts/*.sh
```

如果开发机没有 shellcheck，先记录环境缺失，再使用容器化 shellcheck 运行；不得跳过脚本语法检查。

**提交**

```text
docs: add deployment backup and operations runbooks
```

### 任务 23：完成离线生产验收

**文件**

- 新建：`docs/acceptance/v0.1.0.md`
- 新建：`tests/acceptance/test_clean_start.py`
- 新建：`tests/acceptance/test_restart_recovery.py`
- 新建：`tests/acceptance/test_secret_hygiene.py`

**步骤**

1. 从无 volume 状态启动 PostgreSQL、migrate、fake bot 和 worker。
2. 注入 fixture 数据，执行查询、订阅、计划、投递和 worker 重启恢复。
3. 验证仓库、构建上下文、镜像历史和日志不存在测试密钥。
4. 执行备份，删除测试数据库，再恢复并验证订阅和计划。
5. 把实际命令、输出摘要和结果写入 acceptance 文档。
6. 完成完整检查并合并 `feat/docker-deployment`。

**验证**

```bash
make check
docker compose config
docker build -t anime-qqbot:0.1.0-rc .
uv run pytest tests/acceptance
git diff --check main...HEAD
```

**提交**

```text
test: add offline production acceptance suite
```

## 9. QQ 沙箱与小范围群验收

### 任务 24：执行真实 QQ 验收

该任务需要用户在本地或服务器 `.env` 提供 QQ `AppID`、`AppSecret`，并在 QQ 开放平台配置沙箱成员和固定出口 IP。密钥不通过聊天、提交或测试 fixture 传递。

**验收步骤**

1. 启动生产 Compose，确认 migrate、bot、worker、postgres 健康。
2. 私聊执行 `今日番剧`、`本周番剧`、`季度番剧`、`搜索`、`番剧`、`下次更新`。
3. 群内 `@机器人` 重复发送相同 event fixture/真实消息，确认只回复一次。
4. 普通成员尝试群设置命令，确认被拒绝；管理员成功开启每日和每周计划。
5. 两名用户在同一群订阅同一番，手动触发后确认一条消息同时 `@` 两人。
6. 在 QQ 中关闭群主动消息，确认系统暂停推送；重新开启后计划保留。
7. 模拟 worker 重启和 Bangumi 临时不可用，确认订阅、计划和最后成功缓存仍可用。
8. 触发一次可重试错误和一次 unknown 结果，确认策略与记录正确。
9. 核对消息中的预计放送说明、数据源更新时间和 NSFW 过滤。
10. 把结果、失败项和修复提交写入 `docs/acceptance/v0.1.0.md`。

**通过条件**

- 设计规格第 12 节的所有 v0.1.0 条件通过；
- 没有未解释的 failed/unknown 任务；
- 没有密钥或用户 openid 出现在仓库和公开日志；
- 如有失败，使用独立 `fix/<topic>` 分支修复并重跑受影响验收。

## 10. 发布

### 任务 25：创建 v0.1.0 本地发布

**步骤**

1. 确认处于 `main`，工作区干净，所有 feature/fix 分支已合并。
2. 运行 `make check` 和生产镜像构建。
3. 确认 `docs/acceptance/v0.1.0.md` 全部通过且没有密钥。
4. 更新 README 中的功能、数据来源、部署入口和限制说明。
5. 提交发布文档变更：`docs: prepare v0.1.0 release`。
6. 创建带注释本地标签 `v0.1.0`，说明 QQ 官方接入、查询、订阅、群通知和 Docker 部署范围。
7. 通过标签重新构建 `anime-qqbot:0.1.0`，执行健康检查。

**验证**

```bash
git status --short --branch
make check
docker build -t anime-qqbot:0.1.0 .
git tag --list v0.1.0
```

## 11. 实施期间的停止条件

遇到以下情况时停止当前 feature 分支并报告，不自行扩大范围：

- QQ 官方接口不再支持规格确定的 WebSocket 或主动群消息能力；
- QQ 身份字段无法稳定提供 `member_role` 或群内 `@` 所需标识；
- bangumi-data 许可或字段结构发生不兼容变化；
- 完成需求需要新增 Redis、外部队列、Web 后台或模型服务；
- 需要把真实密钥写入仓库、fixture、镜像层或命令历史；
- 数据迁移无法在保留已有订阅的条件下安全向前执行。

上述情况需要先更新设计规格并重新确认，再继续实现。

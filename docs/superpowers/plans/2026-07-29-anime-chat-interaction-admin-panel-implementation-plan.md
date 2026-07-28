# Anime QQBot 群聊交互、发送保护与内嵌管理面板实施计划

- 日期：2026-07-29
- 状态：待实施
- 对应规格：[群聊交互、发送保护与内嵌管理面板设计](../specs/2026-07-28-anime-chat-interaction-admin-panel-design.md)
- 目标版本：v0.3.0
- 设计基线提交：`aa27a84`
- 运行基线：AstrBot `v4.26.7`、NapCat `v4.18.13`、PostgreSQL 17.4

## 1. 完成定义

只有以下条件全部满足，才可以标记 v0.3.0 完成：

1. 现有 `/番剧` 命令全部兼容，`/番剧` 无参数返回精简菜单。
2. 新群默认支持 `/番剧` 和 `@机器人`，免 `@` 专用短命令默认关闭。
3. 普通聊天不会因为包含“今天”“番剧”“搜索”“订阅”等词而误触发。
4. 搜索候选使用短编号；普通用户不再需要复制内部 UUID。
5. 候选会话按群和用户隔离，5 分钟过期，重启后不会串号。
6. 被动回复和主动通知全部经过同一个 SendGovernor。
7. 通知积压恢复后按限频逐条发送，不再一次领取 10 条后连续投递。
8. QQ 限频、验证、强制下线或连续失败可以触发持久化熔断；重启不自动恢复。
9. AstrBot Plugin Page 可以查看并控制群、订阅、映射、通知、限频和数据源任务。
10. 管理面板只通过 AstrBot Dashboard 鉴权访问，不新增公网端口或独立账号系统。
11. 面板写操作走明确应用用例，具备幂等、确认和审计，不暴露 SQL、Shell 或秘密。
12. 新迁移完成空库升级、当前 head 升级、降级再升级和约束测试。
13. 单元、集成、插件契约、浏览器、Compose 和真实群 canary 全部通过。
14. 2 GiB 服务器仍使用现有五单元 Compose 和 ACR 单镜像，不新增常驻服务。

## 2. 实施约束

1. 按本计划分片顺序实施；每个分片结束时必须保持完整测试集可运行。
2. 行为变更先写失败测试，再写最小实现，不在最后集中补测试。
3. PostgreSQL 是唯一业务事实来源；集成测试不得用 SQLite 替代租约、JSONB、约束和并发。
4. Anime Core 不导入 AstrBot、NapCat、OneBot 或 Dashboard 类型。
5. AstrBot 事件、提及、引用回复和成员角色只在插件 adapter 中解析。
6. 普通群消息监听使用 AstrBot 官方
   `@filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)`；不得用轮询 NapCat 日志代替。
7. 高权限群操作只接受 AstrBot `event.role == "admin"`，代表配置的机器人所有者；
   OneBot QQ 群主/群管理员角色不参与机器人配置授权。
8. `InteractionGateway` 只做唤醒、解析、权限和候选上下文，不直接发送 QQ 消息。
9. `SendGovernor` 是所有发送路径的唯一许可入口；禁止新增绕过路径。
10. 管理页面只调用 `context.register_web_api()` 注册的插件 API，并使用
    `astrbot.api.web` DTO/response helper，不依赖 Dashboard 内部 FastAPI 对象。
11. 页面使用原生 HTML、CSS 和 ES module；不引入 Node 构建服务或新的运行时依赖。
12. 页面通过 AstrBot Plugin Page bridge 获取主题和调用后端；不得硬编码内部 API 前缀或 asset token。
13. 管理 API 不接受任意 URL、文件路径、Shell、SQL、Python 表达式或原始 ORM 字段名。
14. 所有时间持久化为 UTC aware datetime；静默时段按群时区解释。
15. 日志和审计不得记录消息全文、Token、数据库连接串、上游凭据或完整异常堆栈。
16. 不修改 Nginx，不开放 6185/6099 公网端口，不新增 Compose 服务。
17. 不提交 `.env`、AstrBot/NapCat 持久卷、`dist/` 部署包或任何真实 QQ 标识。
18. 保留 Bangumi fallback 配置，不将第三方 API 镜像写死为程序默认值。

## 3. 目标目录结构

```text
migrations/versions/
└── 0012_interaction_delivery_admin.py

src/anime_qqbot/
├── application/
│   ├── intents.py
│   ├── parser.py
│   ├── use_cases.py
│   └── admin_service.py
├── groups/
│   ├── repository_v2.py
│   └── settings.py
├── interactions/
│   ├── __init__.py
│   ├── models.py
│   ├── parser.py
│   ├── repository.py
│   └── service.py
├── notifications/
│   ├── governor.py
│   ├── control.py
│   ├── outbox.py
│   └── outcomes.py
├── operations/
│   ├── __init__.py
│   ├── models.py
│   ├── repository.py
│   └── service.py
└── persistence/models/
    ├── identity.py
    ├── interaction.py
    └── operations.py

astrbot_plugin_anime_tracking/
├── main.py
├── _conf_schema.json
├── pages/
│   └── anime-admin/
│       ├── index.html
│       ├── app.js
│       └── styles.css
└── anime_tracking_plugin/
    ├── admin_api.py
    ├── adapter.py
    ├── dispatcher.py
    ├── event_envelope.py
    ├── interaction_gateway.py
    ├── lifecycle.py
    └── rendering.py

tests/
├── acceptance/
│   ├── test_v03_commands.py
│   ├── test_v03_documentation.py
│   └── test_v03_plugin_page.py
├── e2e/
│   ├── test_v03_group_interactions.py
│   └── test_v03_admin_workflows.py
├── integration/
│   ├── test_admin_operations.py
│   ├── test_delivery_controls.py
│   ├── test_group_runtime_settings.py
│   ├── test_interaction_sessions.py
│   └── test_operator_jobs.py
└── unit/
    ├── interactions/
    ├── notifications/
    └── astrbot/
```

文件可以在实施中按深模块边界合并，但不得把解析、数据库、发送和 Web API 全部堆进
`main.py` 或一个新的“大服务”文件。

## 4. Git、测试和提交纪律

建议按六个纵向分片建立分支：

1. `codex/feat/control-persistence`
2. `codex/feat/send-governor`
3. `codex/feat/group-interactions`
4. `codex/feat/admin-control-plane`
5. `codex/feat/astrbot-admin-page`
6. `codex/feat/v03-production-hardening`

每个任务遵循：

1. 写最小失败测试并确认失败原因正确。
2. 实现最小行为并运行定向测试。
3. 运行受影响模块的类型、格式和测试检查。
4. 执行 `git diff --check` 和 `git status --short`。
5. 只提交任务列出的文件；保留用户的 `dist/` 和其他无关修改。

常用检查：

```bash
UV_CACHE_DIR=.uv-cache .venv/bin/uv lock --check
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy src
TEST_DATABASE_URL=postgresql+asyncpg://anime:anime@127.0.0.1:55432/anime_test \
DATABASE_URL=postgresql+asyncpg://anime:anime@127.0.0.1:55432/anime_test \
  .venv/bin/pytest
docker compose config --quiet
```

涉及 PostgreSQL 的任务先启动隔离测试库：

```bash
docker compose -f compose.test.yaml up -d --wait
```

## 5. 分片一：建立控制面持久化基础

演示终点：数据库可以保存群运行设置、候选会话、投递控制、管理任务和审计事件；旧
v0.2 查询、订阅和通知行为保持不变。

### 任务 1：锁定 v0.3 功能开关和兼容边界

**文件**

- 修改：`astrbot_plugin_anime_tracking/_conf_schema.json`
- 修改：`src/anime_qqbot/settings.py`
- 新建：`tests/unit/test_v03_settings.py`
- 新建：`tests/acceptance/test_v03_commands.py`

**步骤**

1. 为 `interaction_gateway_enabled`、`send_governor_enabled` 和
   `admin_page_writes_enabled` 增加默认关闭的发布开关。
2. 为全局、群、用户和主动提醒限频增加有上下界的类型化配置。
3. 默认值使用规格中的 2.5 秒、5 秒、5 秒/10 次每分钟、60 秒/3 次每 10 分钟。
4. 验证完整旧命令表仍注册，且新功能关闭时旧行为不变。
5. 配置 schema 不出现数据库密码、OneBot Token 或上游秘密。

**验证**

```bash
.venv/bin/pytest tests/unit/test_v03_settings.py tests/acceptance/test_v03_commands.py
.venv/bin/mypy src/anime_qqbot/settings.py
```

**提交**

```text
feat: define v03 interaction safety settings
```

### 任务 2：增加 0012 控制面迁移和 ORM

**文件**

- 新建：`migrations/versions/0012_interaction_delivery_admin.py`
- 新建：`src/anime_qqbot/persistence/models/interaction.py`
- 新建：`src/anime_qqbot/persistence/models/operations.py`
- 修改：`src/anime_qqbot/persistence/models/__init__.py`
- 修改：`tests/integration/test_migrations.py`
- 新建：`tests/integration/test_v03_constraints.py`

**步骤**

1. 创建 `group_runtime_settings`，对 `chat_group_id` 唯一约束并级联删除。
2. 创建 `interaction_sessions`，对平台、群、用户设置唯一当前会话约束和过期索引。
3. 创建 `delivery_controls`，约束 `scope_kind` 为 `global/group`，保证 scope 唯一。
4. 创建 `operator_jobs`，约束状态机、任务类型、幂等键和租约字段。
5. 创建 `admin_audit_events`，保存安全 JSON 摘要和结果。
6. 所有枚举状态使用数据库 CheckConstraint；时间字段使用 timezone-aware 类型。
7. 实现 upgrade/downgrade，覆盖 base→head、0011→head、head→0011→head。

**验证**

```bash
TEST_DATABASE_URL=postgresql+asyncpg://anime:anime@127.0.0.1:55432/anime_test \
  .venv/bin/pytest tests/integration/test_migrations.py tests/integration/test_v03_constraints.py
```

**提交**

```text
feat: add interaction and admin control schema
```

### 任务 3：实现群运行设置深模块

**文件**

- 新建：`src/anime_qqbot/groups/settings.py`
- 修改：`src/anime_qqbot/groups/repository_v2.py`
- 修改：`src/anime_qqbot/groups/__init__.py`
- 新建：`tests/integration/test_group_runtime_settings.py`

**步骤**

1. 定义 `GroupRuntimePolicy`，封装 mention、direct shortcut、主动提醒、静默时段和限频覆盖。
2. 新群首次读取时返回安全默认值：mention 开、direct shortcut 关、主动提醒开。
3. 整群 `chat_groups.enabled=false` 时所有被动入口和主动提醒都不可用。
4. 静默时段支持跨午夜，并按 `chat_groups.timezone` 解释。
5. 更新使用版本字段或等价乐观锁，避免面板和群命令互相覆盖。
6. repository 只暴露 `get_policy`、`update_policy`、`pause_group`、`resume_group` 等意图级方法。

**验证**

```bash
.venv/bin/pytest tests/integration/test_group_runtime_settings.py
.venv/bin/mypy src/anime_qqbot/groups
```

**提交**

```text
feat: persist per-group runtime policy
```

### 任务 4：实现持久化候选会话

**文件**

- 新建：`src/anime_qqbot/interactions/__init__.py`
- 新建：`src/anime_qqbot/interactions/models.py`
- 新建：`src/anime_qqbot/interactions/repository.py`
- 新建：`tests/integration/test_interaction_sessions.py`

**步骤**

1. 定义隔离键、候选项、结果消息 ID 和 5 分钟 TTL。
2. 新会话原子覆盖同一平台、群、用户的旧会话。
3. 读取时同时校验用户、群、过期时间和可选的引用消息 ID。
4. 单独数字必须匹配引用消息；显式 `看/追番/退订 + 编号` 不要求引用。
5. 过期清理可重复执行并限制每批数量。
6. 候选 payload 只保存内部 ID 和显示所需安全字段，不保存原始群消息。

**验证**

```bash
.venv/bin/pytest tests/integration/test_interaction_sessions.py
```

**提交**

```text
feat: persist isolated interaction sessions
```

### 任务 5：实现投递控制、管理任务和审计仓库

**文件**

- 新建：`src/anime_qqbot/notifications/control.py`
- 新建：`src/anime_qqbot/operations/__init__.py`
- 新建：`src/anime_qqbot/operations/models.py`
- 新建：`src/anime_qqbot/operations/repository.py`
- 新建：`tests/integration/test_delivery_controls.py`
- 新建：`tests/integration/test_operator_jobs.py`
- 新建：`tests/integration/test_admin_audit.py`

**步骤**

1. 实现全局和群级暂停、熔断、异常记录及人工恢复。
2. 恢复必须保存操作者和确认时间，进程启动不得自动清除。
3. 实现 operator job enqueue、claim、complete、fail、cancel 和过期租约恢复。
4. 同一业务幂等键重复提交返回已有任务。
5. 审计写入提供统一敏感字段清理器；任何键名包含 token、password、secret、dsn 时拒绝或脱敏。
6. 状态修改与审计写入使用同一事务接口。

**验证**

```bash
.venv/bin/pytest \
  tests/integration/test_delivery_controls.py \
  tests/integration/test_operator_jobs.py \
  tests/integration/test_admin_audit.py
```

**提交**

```text
feat: add durable delivery and operator controls
```

## 6. 分片二：统一所有 QQ 发送路径

演示终点：查询回复和主动通知共享限频器；积压不会突发；熔断跨重启保持。

### 任务 6：实现纯 SendGovernor 调度策略

**文件**

- 新建：`src/anime_qqbot/notifications/governor.py`
- 新建：`src/anime_qqbot/notifications/outcomes.py`
- 修改：`src/anime_qqbot/notifications/__init__.py`
- 新建：`tests/unit/notifications/test_send_governor.py`
- 新建：`tests/unit/notifications/test_delivery_outcomes.py`

**步骤**

1. 定义 `DeliveryClass`：interactive、airing、release、admin。
2. 使用可注入 Clock 的 Token Bucket 实现全局、群、用户和主动提醒限制。
3. 实现优先级队列和有限公平性，防止 Mikan 永久饥饿。
4. interactive 等待超过上限时返回 throttle outcome，不无限阻塞 handler。
5. 定义 sent、temporary、permanent、rate_limited、unknown、account_offline 结果分类。
6. governor 不导入 AstrBot exception；插件 adapter 负责把异常转成平台无关结果。

**验证**

```bash
.venv/bin/pytest \
  tests/unit/notifications/test_send_governor.py \
  tests/unit/notifications/test_delivery_outcomes.py
.venv/bin/mypy src/anime_qqbot/notifications
```

**提交**

```text
feat: add unified send governor
```

### 任务 7：把被动命令回复接入 SendGovernor

**文件**

- 修改：`astrbot_plugin_anime_tracking/anime_tracking_plugin/lifecycle.py`
- 修改：`astrbot_plugin_anime_tracking/main.py`
- 修改：`astrbot_plugin_anime_tracking/anime_tracking_plugin/rendering.py`
- 修改：`tests/unit/astrbot/fakes.py`
- 新建：`tests/unit/astrbot/test_passive_send_governor.py`

**步骤**

1. lifecycle 创建且只创建一个共享 governor。
2. 所有 `yield event.plain_result(...)` 前先获取 interactive 许可。
3. 获取许可时使用群、用户和消息类型，不把 QQ ID 写入日志正文。
4. 用户冷却命中时返回一条稳定、短小的提示；提示自身不得造成递归限频。
5. 功能开关关闭时保持 v0.2 行为，便于分阶段上线。
6. 用 fake clock 验证同用户、同群和跨群行为。

**验证**

```bash
.venv/bin/pytest \
  tests/unit/astrbot/test_passive_send_governor.py \
  tests/unit/astrbot/test_command_handlers.py \
  tests/unit/astrbot/test_event_adapter.py
```

**提交**

```text
feat: govern passive command replies
```

### 任务 8：重构 Outbox 为容量优先逐条领取

**文件**

- 修改：`astrbot_plugin_anime_tracking/anime_tracking_plugin/dispatcher.py`
- 修改：`src/anime_qqbot/notifications/outbox.py`
- 修改：`src/anime_qqbot/application/use_cases.py`
- 修改：`tests/unit/astrbot/test_outbox_dispatcher.py`
- 新建：`tests/integration/test_governed_outbox.py`

**步骤**

1. Dispatcher 先取得 governor 容量，再从数据库领取一条可投递任务。
2. 不允许先领取 10 条后在进程内等待限频。
3. interactive 优先时，主动通知保持 pending，不占用 lease。
4. 同群主动提醒遵守 60 秒和 10 分钟窗口限制。
5. 确保两个 dispatcher 仍通过 SKIP LOCKED 不重复发送。
6. 任务过期、无 UMO、群暂停和静默时段有明确状态语义。

**验证**

```bash
.venv/bin/pytest \
  tests/unit/astrbot/test_outbox_dispatcher.py \
  tests/integration/test_governed_outbox.py
```

**提交**

```text
refactor: claim outbox jobs by send capacity
```

### 任务 9：实现结果分类、熔断与恢复

**文件**

- 新建：`astrbot_plugin_anime_tracking/anime_tracking_plugin/delivery_adapter.py`
- 修改：`astrbot_plugin_anime_tracking/anime_tracking_plugin/dispatcher.py`
- 修改：`src/anime_qqbot/notifications/control.py`
- 新建：`tests/unit/astrbot/test_delivery_adapter.py`
- 新建：`tests/integration/test_delivery_circuit_breaker.py`

**步骤**

1. 将 AstrBot/aiocqhttp 发送异常映射为平台无关 DeliveryOutcome。
2. 未识别异常默认 unknown，不自动重试。
3. 明确 rate limit、验证、强制下线和连续失败触发相应全局或群级控制。
4. 熔断后主动任务保留 pending，过期后由清理流程标记 expired。
5. 人工恢复必须通过控制服务并写审计。
6. 重启 lifecycle 后从数据库恢复暂停状态。

**验证**

```bash
.venv/bin/pytest \
  tests/unit/astrbot/test_delivery_adapter.py \
  tests/integration/test_delivery_circuit_breaker.py
```

**提交**

```text
feat: persist delivery circuit breakers
```

## 7. 分片三：安全短入口和候选交互

演示终点：测试群可以通过 `@机器人` 和显式开启的短命令查询、选择和订阅，普通聊天
不会误触发，旧命令保持兼容。

### 任务 10：定义确定性短语解析器

**文件**

- 新建：`src/anime_qqbot/interactions/parser.py`
- 修改：`src/anime_qqbot/application/intents.py`
- 新建：`tests/unit/interactions/test_shortcut_parser.py`
- 新建：`tests/unit/interactions/test_mention_parser.py`

**步骤**

1. direct 模式只接受：今日番剧、本周番剧、搜番、追番、退订、我的追番。
2. 使用锚定完整结构，不对消息正文做子串扫描。
3. mention 模式支持规格中的有限同义表达。
4. 状态修改无法唯一判断目标时返回 ParseFailure，不猜测。
5. 建立普通聊天反例表，包括包含“今天”“番剧”“搜索”“订阅”的自然句。
6. 保留现有固定命令 parser，两个 parser 最终输出同一 Intent 类型。

**验证**

```bash
.venv/bin/pytest \
  tests/unit/interactions/test_shortcut_parser.py \
  tests/unit/interactions/test_mention_parser.py \
  tests/unit/application/test_intent_parser.py
```

**提交**

```text
feat: parse safe group shortcuts
```

### 任务 11：建立 AstrBot EventEnvelope

**文件**

- 新建：`astrbot_plugin_anime_tracking/anime_tracking_plugin/event_envelope.py`
- 修改：`astrbot_plugin_anime_tracking/anime_tracking_plugin/adapter.py`
- 修改：`tests/unit/astrbot/fakes.py`
- 新建：`tests/unit/astrbot/test_event_envelope.py`

**步骤**

1. 从 `AstrMessageEvent` 提取 group_id、user_id、AstrBot role、self_id、message_id、
   UMO 和纯文本。
2. 从消息链识别开头对机器人本人的 At，不把对其他人的 At 当作唤醒。
3. 从标准消息组件提取引用 message ID；OneBot 特有 raw_message fallback 只存在于本文件。
4. 将 `event.role` 规范为 `admin/member`；只把 admin 视为机器人所有者，OneBot
   sender role 不进入授权模型。
5. envelope 不保留完整 raw_message，避免上层意外记录敏感内容。
6. 使用 aiocqhttp fixture 覆盖提及、引用、普通消息和角色。

**验证**

```bash
.venv/bin/pytest tests/unit/astrbot/test_event_envelope.py
```

**提交**

```text
feat: normalize astrbot group events
```

### 任务 12：实现 InteractionGateway 和群消息监听

**文件**

- 新建：`astrbot_plugin_anime_tracking/anime_tracking_plugin/interaction_gateway.py`
- 修改：`astrbot_plugin_anime_tracking/main.py`
- 修改：`astrbot_plugin_anime_tracking/anime_tracking_plugin/lifecycle.py`
- 新建：`tests/unit/astrbot/test_interaction_gateway.py`
- 新建：`tests/acceptance/test_v03_plugin_filters.py`

**步骤**

1. 使用 `EventMessageType.GROUP_MESSAGE` 注册普通群事件 handler。
2. 先检查整群 enabled，再按 slash、mention、direct shortcut 顺序判断入口。
3. direct shortcut 必须读取群 policy；默认关闭时静默忽略。
4. 未匹配消息不设置结果、不调用 LLM、不回复。
5. 匹配成功后设置事件终止/停止传播语义，避免其他插件重复处理；以固定 SDK 行为写契约测试。
6. 现有 command_group 保留，避免命令管理和帮助体系回归。
7. 功能开关关闭时不注册或不执行新路由。

**验证**

```bash
.venv/bin/pytest \
  tests/unit/astrbot/test_interaction_gateway.py \
  tests/acceptance/test_v03_plugin_filters.py \
  tests/acceptance/test_v02_commands.py
```

**提交**

```text
feat: route safe group interactions
```

### 任务 13：实现候选编号查询与状态修改

**文件**

- 新建：`src/anime_qqbot/interactions/service.py`
- 修改：`src/anime_qqbot/application/use_cases.py`
- 修改：`astrbot_plugin_anime_tracking/anime_tracking_plugin/adapter.py`
- 修改：`astrbot_plugin_anime_tracking/anime_tracking_plugin/rendering.py`
- 新建：`tests/e2e/test_v03_group_interactions.py`

**步骤**

1. 多结果搜索创建 session 并输出 1..N，不向普通用户显示 UUID。
2. `看 N` 返回详情；`追番 N` 和 `退订 N` 复用现有订阅用例。
3. 单独数字只在引用机器人结果消息且 message ID 匹配时使用。
4. 用户、群或会话不匹配时静默忽略单独数字；显式操作返回短错误。
5. 新搜索覆盖旧候选；过期后返回“结果已过期，请重新搜索”。
6. 保存机器人结果消息 ID 所需的 after-send/发送结果挂钩限定在 plugin adapter。

**验证**

```bash
.venv/bin/pytest tests/e2e/test_v03_group_interactions.py
```

**提交**

```text
feat: add numbered anime follow-up flows
```

### 任务 14：修正查询语义并升级文本呈现

**文件**

- 修改：`src/anime_qqbot/application/use_cases.py`
- 修改：`src/anime_qqbot/catalog/repository_v2.py`
- 修改：`astrbot_plugin_anime_tracking/anime_tracking_plugin/adapter.py`
- 修改：`astrbot_plugin_anime_tracking/anime_tracking_plugin/rendering.py`
- 修改：`tests/unit/catalog/test_queries.py`
- 修改：`tests/e2e/test_astrbot_group_queries.py`
- 新建：`tests/unit/astrbot/test_v03_rendering.py`

**步骤**

1. 修正“今天 YYYY-MM-DD”解析后仍使用当前日期的问题。
2. 统一季度默认行为、帮助文本和参数规则。
3. 今日、本周和季度按日期、星期、时间和集数分组；日期-only 明确标注。
4. 从最新安全 SourceSnapshot 投影中文名、原名、状态、评分、简介、下一集和来源。
5. 长简介截断，列表分页；首条消息控制在 QQ 友好长度。
6. 搜索和详情尾部给出可复制下一步操作。
7. NSFW、disabled 和来源失效边界保持现有安全策略。

**验证**

```bash
.venv/bin/pytest \
  tests/unit/catalog/test_queries.py \
  tests/unit/astrbot/test_v03_rendering.py \
  tests/e2e/test_astrbot_group_queries.py
```

**提交**

```text
feat: enrich group anime presentation
```

### 任务 15：实现机器人所有者群设置命令

**文件**

- 修改：`src/anime_qqbot/application/intents.py`
- 修改：`src/anime_qqbot/application/parser.py`
- 修改：`src/anime_qqbot/application/use_cases.py`
- 修改：`astrbot_plugin_anime_tracking/main.py`
- 新建：`tests/e2e/test_v03_group_admin.py`

**步骤**

1. 增加查看本群设置、开启/关闭短命令、提醒和静默时段的明确命令。
2. 只有 AstrBot role 为 admin 的机器人所有者可以修改；其他角色一律拒绝。
3. QQ 群主和群管理员不获得额外权限；普通成员只能读取不敏感的简化状态。
4. 群命令与未来面板调用同一 `GroupRuntimeService`。
5. 每次修改写审计，操作者使用散列或安全外部 ID 摘要。
6. 不在群内暴露 UMO、内部数据库 UUID、错误堆栈或其他群状态。

**验证**

```bash
.venv/bin/pytest tests/e2e/test_v03_group_admin.py
```

**提交**

```text
feat: add authorized group runtime controls
```

## 8. 分片四：管理控制面后端

演示终点：不打开自定义页面也能通过测试客户端验证所有只读和写入管理用例；同步任务
由 Worker 执行，不阻塞 AstrBot。

### 任务 16：实现安全管理读模型

**文件**

- 新建：`src/anime_qqbot/application/admin_service.py`
- 修改：`src/anime_qqbot/groups/repository_v2.py`
- 修改：`src/anime_qqbot/subscriptions/repository_v2.py`
- 修改：`src/anime_qqbot/notifications/outbox.py`
- 新建：`tests/integration/test_admin_read_models.py`

**步骤**

1. 定义 overview、group、subscription、mapping、notification、source 和 operator job DTO。
2. 所有列表具备稳定排序、分页、过滤和总数。
3. overview 使用聚合查询，避免对每个群/订阅逐行查询。
4. DTO 只包含安全字段，不返回 payload 全文、UMO、连接串或异常堆栈。
5. 来源错误返回分类和截断摘要。
6. 为 10k 通知、1k 订阅数据量增加查询计划或索引验证。

**验证**

```bash
.venv/bin/pytest tests/integration/test_admin_read_models.py
```

**提交**

```text
feat: expose safe admin read models
```

### 任务 17：实现管理写用例和审计事务

**文件**

- 修改：`src/anime_qqbot/application/admin_service.py`
- 修改：`src/anime_qqbot/operations/repository.py`
- 新建：`tests/integration/test_admin_operations.py`

**步骤**

1. 实现群策略修改、群暂停/恢复、异常订阅取消。
2. 实现映射确认/拒绝及 AniList/Mikan 数字 ID 人工映射。
3. 实现通知取消、明确失败单条重试、unknown 二次确认补发。
4. 实现全局主动通知暂停/恢复。
5. 所有写操作带幂等键或 expected version，并与审计同事务。
6. 禁止批量补发、任意 URL、修改原始 snapshot 和硬删除审计记录。

**验证**

```bash
.venv/bin/pytest tests/integration/test_admin_operations.py
```

**提交**

```text
feat: add audited admin operations
```

### 任务 18：让 Worker 执行 operator jobs

**文件**

- 修改：`src/anime_qqbot/entrypoints/cli.py`
- 新建：`src/anime_qqbot/operations/service.py`
- 修改：`src/anime_qqbot/entrypoints/health.py`
- 新建：`tests/unit/entrypoints/test_operator_job_schedule.py`
- 新建：`tests/integration/test_operator_job_execution.py`

**步骤**

1. Worker 每轮以有限批量领取到期 operator jobs。
2. 支持 Bangumi 立即目录同步、AniList 已确认映射同步和 Mikan 已确认 feed 轮询。
3. 任务参数只接受 provider 枚举和受限内部 ID，不接受 URL。
4. 完成、失败、取消和租约恢复写安全结果摘要。
5. 任务失败不终止 Worker 主循环，不改变正常调度的下一次时间。
6. health/status 暴露积压和最后执行时间。

**验证**

```bash
.venv/bin/pytest \
  tests/unit/entrypoints/test_operator_job_schedule.py \
  tests/integration/test_operator_job_execution.py
```

**提交**

```text
feat: execute operator jobs in worker
```

### 任务 19：注册受保护的 Plugin Web API

**文件**

- 新建：`astrbot_plugin_anime_tracking/anime_tracking_plugin/admin_api.py`
- 修改：`astrbot_plugin_anime_tracking/anime_tracking_plugin/lifecycle.py`
- 修改：`astrbot_plugin_anime_tracking/main.py`
- 新建：`tests/unit/astrbot/test_admin_api.py`
- 新建：`tests/e2e/test_v03_admin_workflows.py`

**步骤**

1. 使用 `context.register_web_api()` 和 `astrbot.api.web` 注册窄 API。
2. API 只接受/返回显式 DTO，不把 request 对象传给 Core。
3. GET 覆盖 overview、groups、subscriptions、mappings、notifications、sources 和 jobs。
4. PATCH/POST 覆盖规格中的明确写操作。
5. 验证 Dashboard 认证上下文；未认证请求无法调用。
6. 写请求校验枚举、长度、版本、幂等键和二次确认 token。
7. API 异常映射为稳定错误码和安全消息。

**验证**

```bash
.venv/bin/pytest \
  tests/unit/astrbot/test_admin_api.py \
  tests/e2e/test_v03_admin_workflows.py
```

**提交**

```text
feat: register protected anime admin api
```

## 9. 分片五：AstrBot Plugin Page

演示终点：通过 SSH 隧道进入 AstrBot WebUI 后，可以在 Anime 插件页面完成第一版所有
运维操作；不新增前端构建或服务。

### 任务 20：建立无构建 Plugin Page 外壳

**文件**

- 新建：`astrbot_plugin_anime_tracking/pages/anime-admin/index.html`
- 新建：`astrbot_plugin_anime_tracking/pages/anime-admin/app.js`
- 新建：`astrbot_plugin_anime_tracking/pages/anime-admin/styles.css`
- 新建：`tests/acceptance/test_v03_plugin_page.py`

**步骤**

1. 使用 AstrBot 注入的 Plugin Page bridge，不硬编码 API/asset 路径。
2. 建立总览、群、订阅、映射、通知、数据源六个导航区。
3. 支持 Dashboard 明暗主题和窄屏布局。
4. 共享 loading、empty、error、pagination、confirm dialog 和 toast 组件。
5. 禁止 CDN 脚本、外部字体和运行时包管理器。
6. 验证页面资源被单镜像复制并能被 AstrBot 发现。

**验证**

```bash
.venv/bin/pytest tests/acceptance/test_v03_plugin_page.py
```

**提交**

```text
feat: scaffold astrbot anime admin page
```

### 任务 21：实现总览、群和订阅页面

**文件**

- 修改：`astrbot_plugin_anime_tracking/pages/anime-admin/index.html`
- 修改：`astrbot_plugin_anime_tracking/pages/anime-admin/app.js`
- 修改：`astrbot_plugin_anime_tracking/pages/anime-admin/styles.css`
- 新建：`tests/browser/test_admin_overview.py`
- 新建：`tests/browser/test_admin_groups.py`

**步骤**

1. 总览展示运行状态、来源新鲜度、业务数量、积压和熔断。
2. 群列表支持搜索、分页、触发模式、主动提醒、静默时段和暂停。
3. 保存群设置携带 expected version，冲突时刷新并提示。
4. 订阅列表支持群、用户、番剧过滤和单条取消确认。
5. 页面不显示 UMO、真实秘密或完整用户消息。
6. 浏览器验证 1280px 和 390px 宽度、键盘操作和错误状态。

**验证**

```bash
.venv/bin/pytest tests/browser/test_admin_overview.py tests/browser/test_admin_groups.py
```

**提交**

```text
feat: add overview and group admin views
```

### 任务 22：实现映射、通知、限频和来源页面

**文件**

- 修改：`astrbot_plugin_anime_tracking/pages/anime-admin/index.html`
- 修改：`astrbot_plugin_anime_tracking/pages/anime-admin/app.js`
- 修改：`astrbot_plugin_anime_tracking/pages/anime-admin/styles.css`
- 新建：`tests/browser/test_admin_mappings.py`
- 新建：`tests/browser/test_admin_notifications.py`
- 新建：`tests/browser/test_admin_sources.py`

**步骤**

1. 映射页显示证据并支持确认、拒绝和数字 ID 人工映射。
2. 通知页支持状态过滤、单条取消、明确失败重试和 unknown 二次确认。
3. 限频区展示当前参数、队列、冷却、熔断和暂停/恢复。
4. 来源页展示最近成功/失败、下一次运行和 operator job 状态。
5. “立即同步”只创建任务，页面轮询状态，不等待长请求。
6. 所有高风险操作使用目标摘要二次确认，防止点错行。

**验证**

```bash
.venv/bin/pytest \
  tests/browser/test_admin_mappings.py \
  tests/browser/test_admin_notifications.py \
  tests/browser/test_admin_sources.py
```

**提交**

```text
feat: complete anime operations dashboard
```

## 10. 分片六：生产化、文档和真实群验收

演示终点：新版本通过完整检查和 2 GiB 部署验证，测试群分阶段开启并具备明确回滚。

### 任务 23：完成跨模块 E2E 和安全回归

**文件**

- 修改：`tests/e2e/test_v03_group_interactions.py`
- 修改：`tests/e2e/test_v03_admin_workflows.py`
- 新建：`tests/e2e/test_v03_governed_notifications.py`
- 修改：`tests/acceptance/test_no_official_qq_runtime.py`

**步骤**

1. 从群消息到 Intent、查询、governor 和回复执行纵向测试。
2. 从面板 API 到 operator job、Worker、状态回读执行纵向测试。
3. 模拟 30 条命令和 20 条积压通知，验证限频、优先级和无重复发送。
4. 模拟重启，验证候选会话、熔断和 pending 任务保持。
5. 模拟普通聊天反例，验证不产生回复、不创建会话、不调用 LLM。
6. 扫描运行源码和页面，确认没有 QQ 官方运行时和秘密字段。

**验证**

```bash
.venv/bin/pytest \
  tests/e2e/test_v03_group_interactions.py \
  tests/e2e/test_v03_admin_workflows.py \
  tests/e2e/test_v03_governed_notifications.py \
  tests/acceptance/test_no_official_qq_runtime.py
```

**提交**

```text
test: cover v03 interaction and admin workflows
```

### 任务 24：更新 Compose、镜像和 2 GiB 验收

**文件**

- 修改：`Dockerfile`
- 修改：`compose.server-2g.yaml`
- 修改：`scripts/container-entrypoint.sh`
- 修改：`tests/acceptance/test_container_entrypoint.py`
- 修改：`tests/acceptance/test_server_resource_overrides.py`
- 修改：`tests/acceptance/test_deployment_package.py`

**步骤**

1. 确认 Plugin Page 静态资源复制进单应用镜像。
2. 不新增常驻服务、端口、卷或 Nginx 配置。
3. 页面和新 Python 模块包含在部署包白名单。
4. 在 2 GiB 限制下验证 PostgreSQL、Worker、AstrBot、NapCat 同时 healthy。
5. 记录空闲与面板操作期间内存，不通过取消现有安全限制换取通过。
6. ACR vendor 镜像和现有服务名称保持不变。

**验证**

```bash
.venv/bin/pytest \
  tests/acceptance/test_container_entrypoint.py \
  tests/acceptance/test_server_resource_overrides.py \
  tests/acceptance/test_deployment_package.py
docker compose config --quiet
docker build -t anime-qqbot:v0.3.0-acceptance .
```

**提交**

```text
build: package v03 admin page runtime
```

### 任务 25：更新运维、部署和验收文档

**文件**

- 修改：`README.md`
- 修改：`docs/deployment.md`
- 修改：`docs/operations.md`
- 新建：`docs/acceptance/v0.3.0.md`
- 修改：`docs/backlog.md`
- 新建：`tests/acceptance/test_v03_documentation.py`

**步骤**

1. 记录 SSH 隧道进入 AstrBot WebUI 和 Anime Plugin Page 的方式。
2. 记录功能开关、默认限频、群触发策略、熔断恢复和静默时段。
3. 记录 operator job、映射、通知重试和 unknown 的安全操作规则。
4. 记录 ACR 发布、备份、迁移、回滚和新增表保留策略。
5. 明确管理页不开放公网、不是内容 CMS、不能消除 QQ 风控。
6. 从 backlog 移除已完成项或标记版本，不删除未实施的 P2 项。

**验证**

```bash
.venv/bin/pytest tests/acceptance/test_v03_documentation.py
```

**提交**

```text
docs: add v03 operations and acceptance
```

### 任务 26：运行完整发布门并生成部署候选

**文件**

- 修改：`docs/acceptance/v0.3.0.md`
- 仅在需要时修改：由门禁暴露出的目标文件

**步骤**

1. 运行 lock、format、lint、mypy 和完整 pytest。
2. 运行迁移 base→head、0011→head、head→0011→head。
3. 运行 Compose 配置、单镜像构建和五单元隔离启动。
4. 使用浏览器验证 Plugin Page 桌面和窄屏关键流程。
5. 生成不含秘密的部署包，检查清单和压缩包内容。
6. 将真实命令输出、镜像 ID、测试数和已知限制写入验收记录。

**验证**

```bash
UV_CACHE_DIR=.uv-cache .venv/bin/uv lock --check
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy src
TEST_DATABASE_URL=postgresql+asyncpg://anime:anime@127.0.0.1:55432/anime_test \
DATABASE_URL=postgresql+asyncpg://anime:anime@127.0.0.1:55432/anime_test \
  .venv/bin/pytest
docker compose config --quiet
./scripts/package-deployment.sh dist/anime-qqbot-deployment.tar.gz
```

**提交**

```text
chore: prepare v03 deployment candidate
```

### 任务 27：生产测试群分阶段 Canary

**文件**

- 修改：`docs/acceptance/v0.3.0.md`

**执行位置**

- 本地：构建与发布 ACR 镜像、生成部署包
- 服务器：`/opt/anime-qqbot`
- QQ：专用测试群
- 记录：`docs/acceptance/v0.3.0.md`

**步骤**

1. 备份 PostgreSQL 和当前部署文件，记录当前镜像 digest。
2. 发布并部署 v0.3.0，保持三个新功能开关默认关闭。
3. 验证旧 `/番剧` 命令和主动提醒没有回归。
4. 开启只读面板，检查状态和秘密不泄漏。
5. 在测试群开启 InteractionGateway，仅验证 `@机器人`。
6. 开启 SendGovernor，执行受控突发和积压恢复。
7. 由机器人所有者开启免 `@`，验证普通聊天反例和专用短命令。
8. 验证候选隔离、编号订阅、静默时段、群暂停和恢复。
9. 开启面板写操作，验证映射、单条通知操作、同步任务和审计。
10. 连续观察至少一个真实开播提醒和一个 Mikan 聚合窗口。
11. 若出现 QQ 验证、限频或强制下线，立即保持熔断并停止扩群，不尝试绕过。

**验证**

- 所有完成定义均有日志、数据库、截图或群消息证据；
- 服务器四个常驻服务 healthy，migrate 正常退出；
- 静态站和其他服务器服务不受影响；
- 回滚命令和上一个镜像 digest 已验证可用。

**提交**

```text
docs: record v03 production canary
```

## 11. 分片合并与上线顺序

1. 合并持久化基础，但不启用任何新行为。
2. 合并 SendGovernor，以功能开关在测试群验证。
3. 合并 InteractionGateway，先启用 mention，再由机器人所有者开启 direct shortcut。
4. 合并管理后端，先开放只读 API。
5. 合并 Plugin Page，先只读后写入。
6. 通过完整发布门后构建 ACR 镜像。
7. 生产部署按任务 27 分阶段打开开关。

每一步都可以只关闭功能开关回退行为。数据库迁移只增加表和索引；旧镜像可以忽略
新增表。若必须执行数据库 downgrade，先停止 Worker 和 AstrBot 并创建完整备份。

## 12. 风险门和暂停条件

遇到以下情况必须暂停对应分片，不得用猜测继续：

1. 固定 AstrBot `v4.26.7` 的事件 handler 无法同时避免 LLM 和重复插件处理。
2. Plugin Page bridge 或 Web API 无法证明复用 Dashboard 鉴权。
3. aiocqhttp 无法稳定提供机器人 At、引用 message ID 或当前成员角色。
4. 被动 `yield` 回复无法经过 governor 且不破坏 AstrBot handler 生命周期。
5. AstrBot 发送异常无法安全区分时，必须采用 unknown，不得扩大自动重试。
6. 迁移无法从当前 0011 head 往返，或 downgrade 会破坏现有业务表。
7. 面板 API 出现任意 URL、SQL、Shell 或秘密返回路径。
8. 2 GiB 资源验收出现 OOM、持续 swap 抖动或影响静态站。
9. QQ 出现验证、限频、强制下线或群成员投诉刷屏。
10. Bangumi/AniList/Mikan 真实契约与 fixture 显著不同且无法确定安全解析边界。

## 13. 开发 Agent 交接格式

每个执行 Agent 完成一个任务后必须报告：

```text
任务：
提交：
修改文件：
失败测试（实施前）：
定向验证：
完整/分片验证：
迁移影响：
功能开关：
已知限制：
下一任务前置条件：
```

不得只报告“测试通过”。涉及 Plugin Page 的任务还必须提供桌面和 390px 窄屏截图；
涉及发送行为的任务必须提供虚拟时钟下的速率证据；涉及迁移的任务必须提供往返版本
和命令输出；生产 canary 中需要用户完成的 QQ 登录或群操作必须明确标为用户步骤。

## 14. 任务依赖图

```text
1 → 2 → 3 ─┐
      ├→ 4  ├→ 10 → 11 → 12 → 13 → 14 → 15
      └→ 5 ─┤
            ├→ 6 → 7 → 8 → 9
            └→ 16 → 17 → 18 → 19 → 20 → 21 → 22

9 + 15 + 22 → 23 → 24 → 25 → 26 → 27
```

同一分片内仍按任务编号执行。任务 3、4、5 在迁移完成后可以由不同 Agent 并行；
任务 6 和 10 可以并行；任务 16 可在任务 12 之后与任务 13～15 并行。共享文件
`main.py`、`lifecycle.py`、`use_cases.py` 和迁移文件必须指定单一所有者，合并前重新运行
相应跨模块测试。

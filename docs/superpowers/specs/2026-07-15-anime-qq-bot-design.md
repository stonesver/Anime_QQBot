# QQ 追番机器人设计规格

- 日期：2026-07-15
- 状态：已确认
- 首个目标版本：v0.1.0
- 部署形态：Docker Compose

## 1. 项目目标

构建一个面向小范围 QQ 群和用户的追番机器人。机器人使用 QQ 官方开放平台接入，以 Bangumi 作为主要动画目录，以 bangumi-data 补充预计放送时刻。系统由机器人自行保存群设置和用户订阅，不绑定用户的 Bangumi 账号。

首个版本必须支持：

- 当日番剧查询；
- 每周番剧表查询；
- 指定季度番剧查询；
- 番剧搜索、详情与下一次预计放送查询；
- 用户在目标群内订阅和取消订阅番剧；
- 每个群独立设置每日和每周推送计划；
- 番剧预计更新时在群内推送，并 `@` 本群订阅用户；
- PostgreSQL 持久化、失败恢复、任务去重和投递记录；
- 在 Linux 服务器使用 Docker Compose 部署。

## 2. 非目标

v0.1.0 不包含：

- 个人 QQ、小号、OneBot、NapCat 或 Lagrange 接入；
- Bangumi 用户账号绑定或收藏同步；
- Web 管理后台；
- 高频私聊主动推送；
- 国内视频平台资源实际可用性检测；
- 字幕组或下载资源监控；
- 成人内容展示或解除 NSFW 过滤；
- 大模型、MCP Server、向量数据库或对话记忆；
- Redis、RabbitMQ 或微服务拆分；
- AniList 数据接入。AniList 仅作为未来备用数据源候选。

## 3. 已确认的产品规则

### 3.1 QQ 场景

- 使用 QQ 官方机器人开放平台。
- 群聊命令必须 `@机器人`，即使群主开放全量消息事件，也不处理普通群聊文本。
- 私聊允许查询和帮助命令，但不创建群通知订阅。
- 群主需要在 QQ 中开启机器人主动群消息，定时推送才能工作。
- 群管理员可关闭群主动消息；系统收到关闭事件后暂停该群推送。
- 私聊主动消息受官方额度限制，不承诺日更私聊提醒。

QQ 在不同场景使用不同身份标识：同一个用户在私聊中使用 `user_openid`，在不同群中使用不同 `member_openid`。因此订阅按“群 + 群内用户 + 番剧”保存，用户需要在希望收到提醒的群里执行订阅。

参考：

- [QQ 机器人启动接入](https://bot.q.qq.com/wiki/develop/api-v2/)
- [QQ 消息发送与限频](https://bot.q.qq.com/wiki/develop/api-v2/server-inter/message/send-receive/send.html)
- [QQ 事件订阅](https://bot.q.qq.com/wiki/develop/api-v2/dev-prepare/interface-framework/event-emit.html)
- [QQ 唯一身份机制](https://bot.q.qq.com/wiki/develop/api-v2/dev-prepare/unique-id.html)

### 3.2 提醒语义

- “更新”指数据源记录的预计放送，不代表国内平台、字幕或资源已经上线。
- 消息文案使用“预计放送”或“预计更新”。
- Bangumi 仅提供日期时，消息不显示具体时刻。
- bangumi-data 提供明确时刻时，转换为目标群时区后展示。
- 实际平台上线时间可能延迟，消息中需要保留提示。

### 3.3 内容安全

- 调用数据源时，在接口支持的地方请求 `nsfw=false`。
- 入库、查询和生成消息时再次过滤明确标记为 NSFW 的条目。
- v0.1.0 不提供关闭过滤的配置。
- 数据源为社区维护，不能把过滤视为绝对内容审核；异常条目需记录并允许运维侧禁用。

## 4. 技术选型

- 语言：Python 3.12；
- HTTP 与内部健康检查：FastAPI；
- QQ：`QQGateway` 适配官方 SDK 和 QQ OpenAPI，业务代码不直接依赖 SDK；
- 数据访问：SQLAlchemy；
- 数据迁移：Alembic；
- 数据库：PostgreSQL；
- 数据校验：Pydantic；
- HTTP 客户端：httpx；
- 质量工具：Ruff、mypy、pytest；
- 部署：Docker、Docker Compose。

定时任务不以进程内存为事实来源。PostgreSQL 保存 `next_run_at` 和任务状态，worker 轮询并使用数据库锁领取到期任务。即使未来使用调度库，它也只负责时间计算，不能替代数据库中的持久化计划。

## 5. 方案与运行架构

采用一个代码库、一个镜像、两个长期运行角色：

```text
QQ 开放平台 ──事件──> bot 容器
                         │
                         ├── 即时命令与回复
                         │
                         v
Bangumi API ───────> 共享业务模块 <────── bangumi-data
                         │
                         v
                    PostgreSQL
                         ^
                         │
                     worker 容器
               数据同步、调度、通知投递
                         │
                         └────QQ OpenAPI 主动群消息──> QQ 群
```

另有一个一次性 `migrate` 运行单元，在 bot 和 worker 启动前执行 Alembic 迁移。

### 5.1 QQ 连接模式

v0.1.0 使用 WebSocket 接收事件：

- 服务器只需建立出站连接；
- 不要求域名和公网 HTTPS 回调地址；
- 在 QQ 管理后台配置服务器固定出口 IP；
- `QQGateway` 隔离连接模式，未来可替换为 Webhook。

### 5.2 深模块与接口

#### QQGateway

隐藏鉴权、Access Token 刷新、WebSocket 事件、OpenAPI 请求、消息格式、限频错误和 SDK 差异。

对业务层提供的能力包括：接收标准化事件、被动回复、主动群消息、Markdown/按钮消息和用户 `@` 表示。

#### CommandRouter

把标准化 QQ 事件解析为明确命令，完成参数解析和上下文构造。它不直接读写数据库，也不包含番剧或权限规则。

#### AnimeCatalog

统一 Bangumi 和 bangumi-data，提供搜索、条目详情、日/周/季度查询和预计放送信息。调用方不需要知道数据来自哪个外部接口。

#### SubscriptionManager

管理群内用户与 Bangumi 条目的订阅关系，负责唯一性、启停和查询。

#### ScheduleManager

管理每群时区、每日/每周计划、下一次执行时间、启停状态和到期任务生成。

#### NotificationDispatcher

读取到期任务，合并相同番剧的订阅用户，生成一条群消息，执行限频、投递、错误分类、重试和去重。

#### PermissionPolicy

根据 QQ 事件的 `member_role` 和引导配置的管理员身份判断群配置权限。权限结果由确定性代码产生，不由消息模板或未来 Agent 判断。

#### AgentRuntime

仅预留接口，不提供 v0.1.0 实现。未来 Agent 只能通过受控工具调用上述业务模块；不能执行任意 SQL、持有 QQ 密钥、保存定时器或绕过权限检查。

## 6. 命令设计

### 6.1 查询命令

群聊和私聊均支持：

- `今日番剧 [YYYY-MM-DD]`
- `本周番剧`
- `季度番剧 [年份] [春|夏|秋|冬]`
- `搜索 <关键词>`
- `番剧 <Bangumi ID|关键词>`
- `下次更新 <Bangumi ID|关键词>`
- `帮助`

搜索结果唯一时直接展示；存在多个候选时返回可选按钮。指令支持中文空格、常见别名和 Bangumi ID，不做开放式自然语言理解。

### 6.2 群内订阅命令

仅在目标群中支持：

- `订阅 <Bangumi ID|关键词>`
- `取消订阅 <Bangumi ID|关键词>`
- `我的订阅`

订阅只对当前 `group_openid + member_openid` 生效。

### 6.3 群管理命令

只有 `owner`、`admin` 或引导配置中的管理员可以执行：

- `开启每日推送 <HH:mm>`
- `关闭每日推送`
- `开启每周推送 <星期> <HH:mm>`
- `关闭每周推送`
- `设置时区 <IANA timezone>`
- `推送状态`
- `立即推送今日番剧`

默认时区为 `Asia/Shanghai`。容器与数据库时间统一存储为 UTC。

## 7. 数据源设计

### 7.1 Bangumi API

作为条目身份和展示数据的主要来源：

- Bangumi subject ID；
- 中日文名称；
- 简介、封面、评分；
- 季度与放送日期；
- 章节和集数信息。

所有请求必须使用符合 Bangumi 要求的 User-Agent。Access Token 为可选配置，只在所需接口要求鉴权时使用。

### 7.2 bangumi-data

作为具体预计放送时间和播放站点来源：

- 首次放送时间；
- 周期规则；
- 站点、地区和预计时刻；
- Bangumi 站点 ID 映射。

项目文档和机器人数据来源说明中必须按 CC BY 4.0 要求注明 bangumi-data。

### 7.3 同步与降级

- worker 默认每 6 小时同步一次 bangumi-data；
- Bangumi 日历与活跃条目缓存默认 1 小时，查询可触发受限的按需刷新；
- worker 默认每 30 秒扫描一次到期计划；
- 两个数据源相互独立，单个失败不清空已有数据；
- 优先按 bangumi-data 中的 Bangumi 站点 ID 映射；
- 无法明确映射时不猜测具体时刻；
- 缺少具体时刻时降级为 Bangumi 的放送日期；
- Bangumi 活跃数据超过 24 小时、bangumi-data 超过 48 小时时视为陈旧；
- 查询结果包含数据更新时间和必要的陈旧提示。

## 8. 数据模型

核心表：

- `groups`：群 openid、时区、主动消息状态、创建和更新时间；
- `group_members`：群、member openid、最近角色、最近活动时间；
- `subscriptions`：群、群成员、Bangumi 条目、启停状态；
- `group_schedules`：推送类型、时区、计划、next_run_at、启停状态；
- `anime_subjects`：Bangumi 条目缓存、季度、NSFW 状态和同步时间；
- `airing_schedules`：条目、集数、预计时间、数据源和更新时间；
- `notification_jobs`：业务唯一键、状态、领取时间、重试时间和结果；
- `delivery_attempts`：每次 QQ 请求、错误分类、响应标识和时间；
- `processed_events`：QQ msg_id/event_id 去重；
- `worker_heartbeats`：运行角色健康状态；
- `admin_identities`：可选的 group_openid 与 member_openid 管理员引导记录。

关键唯一约束：

```text
subscriptions(group_id, member_openid, subject_id)
notification_jobs(group_id, notification_type, subject_or_date, occurrence)
processed_events(platform_event_id)
```

取消订阅采用状态变更并保留必要历史。默认保留策略为：processed events 保留 7 天，notification jobs 和 delivery attempts 保留 90 天，群设置和订阅在用户或管理员明确删除前持续保留。保留周期可以通过部署配置调整。

## 9. 主要数据流

### 9.1 即时查询

1. QQGateway 接收事件并标准化。
2. processed_events 尝试写入唯一事件 ID。
3. CommandRouter 解析命令和上下文。
4. PermissionPolicy 在管理命令前校验角色。
5. 业务模块从缓存和数据库返回结构化结果。
6. 展示层生成 QQ 文本、Markdown 或按钮。
7. QQGateway 在被动回复窗口内发送结果。

### 9.2 定时提醒

1. worker 使用数据库锁领取到期计划。
2. ScheduleManager 计算本次业务 occurrence，并尝试创建唯一 notification job。
3. NotificationDispatcher 查询当日番剧与本群订阅者。
4. 相同番剧和用户合并为有限条群消息。
5. 发送前创建 delivery attempt。
6. QQGateway 调用主动群消息接口。
7. 保存 QQ message ID、时间和最终状态。
8. ScheduleManager 计算并保存下一次执行时间。

## 10. 容错、一致性与限频

### 10.1 数据源

- 所有外部请求设置连接和总超时；
- 对明确可重试错误默认最多尝试 3 次，使用指数退避和随机抖动；
- 同步失败保留最后成功数据；
- 数据过旧时向用户标记；
- 映射冲突记录结构化日志，不自动覆盖为不确定结果。

### 10.2 QQ 投递

- `429` 按官方频控和可用的重试信息延后；
- 明确未发送的网络错误和部分 `5xx` 有限重试；
- 参数、权限、内容审核等永久错误不无限重试；
- 群关闭主动消息后暂停该群任务；
- 单个群失败不阻塞其他群。

QQ 可能已经接收消息，但调用方在收到响应前超时。此时自动重试可能重复发送。v0.1.0 采用“避免骚扰优先”：

- 发送前记录投递意图；
- 只有明确未到达 QQ 的错误才自动重试；
- 结果不确定时标记为 `unknown`，不自动重发；
- 管理员可以查看状态并手动补发。

系统保证业务任务不重复生成，但不宣称跨外部网络调用实现绝对 exactly-once。

### 10.3 重启恢复

- worker 只从 PostgreSQL 领取任务；
- 使用行锁或等价的跳过已锁定策略避免并发重复领取；
- 容器重启后重新处理可恢复任务；
- 每日通知默认补偿窗口为 2 小时，每周通知默认补偿窗口为 24 小时；超过窗口的任务标记为 skipped；
- 数据同步锁与通知任务锁相互独立。

## 11. Docker 与生产部署

Docker Compose 包含：

- `migrate`：一次性迁移；
- `bot`：QQ 连接和即时命令；
- `worker`：同步、调度和通知；
- `postgres`：持久化数据。

生产要求：

- Linux、Docker Engine、Docker Compose；
- 固定公网出口 IP；
- 1 核 CPU、1 GB 内存作为小范围部署起点；
- Python slim 镜像，应用以非 root 用户运行；
- PostgreSQL 使用命名卷；
- 容器使用 `restart: unless-stopped`；
- bot 内部存活/就绪检查、worker 数据库心跳、PostgreSQL `pg_isready`；
- 日志写 stdout/stderr 并配置 Docker 日志轮转；
- 停止信号触发安全关闭和事务收尾。

`.env.example` 记录配置字段，真实 `.env` 不提交 Git。生产配置至少包括：

```text
QQ_APP_ID
QQ_APP_SECRET
DATABASE_URL
BANGUMI_USER_AGENT
BANGUMI_ACCESS_TOKEN        # 可选
BOOTSTRAP_ADMIN_IDENTITIES  # group_openid:member_openid
```

仓库提供可由主机 cron 调用的 PostgreSQL 备份命令，并提供可选的 Compose backup profile；生产环境每日执行一次，默认保留最近 7 天。升级顺序为：备份、拉取或构建明确版本镜像、执行迁移、启动 bot/worker、运行健康与业务验收。生产镜像不使用浮动 `latest` 标签作为唯一版本标识。

## 12. 测试与验收

统一提供 `make check` 或等价单一入口，执行：

- Ruff 格式检查；
- Ruff 静态检查；
- mypy 类型检查；
- pytest 单元测试；
- PostgreSQL 集成测试；
- Alembic 迁移验证；
- Docker Compose 配置验证。

测试分层：

- 单元测试：季度、时区、指令、权限、订阅、计划、状态机和消息合并；
- 适配器契约测试：使用固定 QQ、Bangumi 和 bangumi-data payload；
- PostgreSQL 集成测试：唯一键、并发领取、迁移和事务回滚；
- 端到端测试：使用 FakeQQGateway 验证事件到回复和任务到通知；
- QQ 沙箱验收：真实查询、订阅、管理员配置和主动群消息；
- 重启恢复测试：处理中停止 worker，验证任务不丢失且不无条件重复；
- 生产验收：Compose 健康、备份恢复、日志脱敏和持续运行。

v0.1.0 发布条件：

- 查询、订阅和群管理命令可用；
- 每群独立计划可用；
- 订阅用户能在正确群内被 `@`；
- 同一业务通知不重复生成；
- 数据源短暂失败时仍可读取最后成功缓存；
- bot 或 worker 单独重启不丢失订阅和持久化任务；
- 干净 Linux 服务器可通过 Compose 启动；
- 仓库、镜像和日志中不存在密钥。

## 13. 本地 Git 流程

仓库只使用本地 Git，采用 `main + feature branches`：

- `main` 始终可测试、可部署；
- 功能分支使用 `feat/<topic>`；
- 修复分支使用 `fix/<topic>`；
- 文档分支使用 `docs/<topic>`；
- 提交信息遵循 Conventional Commits；
- 每个提交只包含一个逻辑变更；
- 数据模型修改必须同时包含 Alembic 迁移；
- 合并前运行完整检查和 `git diff main...branch`；
- 通过 `git merge --no-ff` 合并，保留阶段分支边界；
- 首个正式版本标记 `v0.1.0`。

建议阶段分支：

1. `feat/project-foundation`
2. `feat/anime-catalog`
3. `feat/qq-commands-and-subscriptions`
4. `feat/scheduled-notifications`
5. `feat/docker-deployment`
6. 验收修复使用独立 `fix/*` 分支

## 14. 实施顺序

1. 项目基础：配置、日志、数据库、迁移、测试和开发 Compose。
2. 只读目录：Bangumi、bangumi-data、缓存、查询和契约测试。
3. QQ 命令与订阅：沙箱接入、路由、权限、订阅和交互回复。
4. 持久化通知：群计划、worker、任务锁、合并、投递和恢复。
5. 生产部署：镜像、健康检查、备份恢复、日志和部署文档。
6. 正式验收：QQ 沙箱、小范围测试群、干净服务器和重启恢复。
7. 发布：修复验收问题并标记 `v0.1.0`。

Agent、MCP、AniList 和 Web 管理后台必须在 v0.1.0 验收后单独设计，不能在首期实施中顺带加入。

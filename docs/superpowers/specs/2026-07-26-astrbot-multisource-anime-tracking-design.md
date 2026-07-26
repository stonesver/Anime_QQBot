# AstrBot 多源群聊追番系统设计规格

- 日期：2026-07-26
- 状态：已确认
- 目标里程碑：v0.2.0
- 部署形态：Docker Compose
- QQ 接入：NapCat + OneBot 11 + AstrBot

## 1. 目标

将现有 QQ 官方机器人项目改造成使用普通 QQ 小号入群的多源追番系统。首版必须完整支持：

- 群内查询今日、本周、季度番剧；
- 搜索并查看番剧详情和下一次预计放送；
- 用户在当前群订阅、取消订阅和查看自己的追番；
- 预计放送到时在群内提醒并 `@` 订阅用户；
- Mikan 出现匹配资源后，在群内发送聚合提醒并 `@` 订阅用户；
- Bangumi、AniList 和 Mikan 三个来源的独立同步、缓存、降级和可观察性；
- 容器重启、来源故障和短时 QQ 掉线后的恢复；
- 为后续增加 Web、其他聊天平台、新数据源和更多订阅策略保留清晰 seam。

本里程碑不是在旧 QQ adapter 上增加功能，而是建立新的产品基线。QQ 官方机器人不再是支持目标。

## 2. 非目标

首版不包含：

- QQ 官方机器人、AppID/Secret、openid、官方按钮、官方 Markdown 或主动消息开关；
- 自动下载、qBittorrent、Transmission、媒体库整理或磁力任务管理；
- 用户 Mikan 账号绑定、Mikan 私有 RSS token 或替用户修改 Mikan 站内订阅；
- Bangumi 或 AniList 用户账号绑定和收藏同步；
- 跨群统一用户账号或跨群共享订阅；
- Web 管理后台或面向公网的业务 HTTP interface；
- 依赖大模型才能完成的查询或订阅；
- 成人内容展示或关闭成人内容过滤的配置；
- 自动接受低置信度标题匹配；
- 高频私聊推送。

Mikan 消息只展示资源标题、字幕组、语言、分辨率、发布时间和 Mikan 页面链接，不发送直链、不自动下载。

## 3. 产品规则

### 3.1 群内身份与订阅归属

- 机器人使用专用 QQ 小号加入目标群。
- 群与用户分别使用普通 QQ 群号和 QQ 号标识。
- Follow Subscription 唯一归属于“群 + QQ 用户 + Anime”。
- 同一个用户在两个群订阅同一部番，形成两个独立订阅。
- 新版本不迁移旧官方机器人的群、openid 或订阅关系；用户需要重新订阅。
- 默认订阅同时开启预计放送提醒和 Mikan 资源提醒。

### 3.2 查询与命令

固定命令是首版验收基线：

- `/番剧 今天 [YYYY-MM-DD]`
- `/番剧 本周`
- `/番剧 季度 [年份] [冬|春|夏|秋]`
- `/番剧 搜索 <关键词>`
- `/番剧 详情 <内部 ID|关键词>`
- `/番剧 下次 <内部 ID|关键词>`
- `/番剧 订阅 <内部 ID|关键词>`
- `/番剧 取消订阅 <内部 ID|关键词>`
- `/番剧 我的订阅`
- `/番剧 订阅设置 <内部 ID> [语言=简体|繁体|不限] [字幕组=名称,...|不限] [分辨率=1080p,...|不限]`
- `/番剧 状态`
- `/番剧 映射待处理`，仅管理员

搜索结果唯一时可以直接继续；出现多个候选时返回带内部 ID 的编号列表，由用户明确选择。命令不要求大模型可用。

AstrBot 可以把自然语言转换成同一组结构化意图。自然语言查询可直接执行；订阅、取消订阅和修改筛选属于状态变更，必须向用户展示目标和规则并获得确认。大模型只生成意图，不能直接访问数据库、QQ 凭据或数据源凭据。

### 3.3 预计放送提醒

- “预计放送”表示 Bangumi 或 AniList 记录的放送计划，不表示字幕、流媒体或 Mikan 资源已经上线。
- 只有精确到时刻的 Airing Occurrence 才生成逐集提醒。
- 只有日期、没有具体时刻的记录只在今日、本周和季度查询中展示。
- 到达预计时刻后，系统为同一个群、Anime 和集数生成一个 Notification Job。
- 一条消息合并并 `@` 本群全部匹配订阅用户。
- 消息必须使用“预计放送”等不承诺资源已上线的表述。
- 逾期超过 2 小时仍未投递的逐集提醒标记为 expired，不补发陈旧提醒。

### 3.4 Mikan 资源提醒

- 系统自己保存 Follow Subscription，不绑定任何 Mikan 账号。
- Worker 只轮询已经有资源提醒订阅、且具有 confirmed Mikan Source Link 的公开番剧 RSS。
- 每个 RSS item 先依据稳定标识和内容指纹去重，再保存为 Resource Release。
- 同一 Anime、同一集首次发现资源后开启 10 分钟 Release Batch。
- 聚合窗结束后，系统按每位用户的 Resource Filter 计算受众和匹配资源。
- 群消息最多展示 5 条匹配资源，其余只显示数量。
- 同一个群、Anime、集数和聚合窗只生成一个 Notification Job。
- Mikan 通知逾期超过 24 小时标记为 expired。
- 无法解析集数、无法确认番剧映射或成人内容过滤不通过时，不发送提醒，但保留原始记录供管理员检查。

Resource Filter 支持：

- 简体、繁体或不限语言；
- 一个或多个字幕组，留空表示不限；
- 一个或多个分辨率，留空表示不限。

新订阅默认三个条件均为不限。筛选只影响资源提醒，不影响预计放送提醒。

### 3.5 内容安全

- Bangumi 和 AniList 支持成人标记时均请求并保存该标记。
- 统一 Anime 只要任一可信来源明确标记成人内容，首版即禁止展示和订阅。
- Mikan 原始标题解析不能作为解除成人标记的依据。
- 数据源标记不是绝对审核；管理员可以禁用异常 Anime 或 External Entry。

## 4. 采用的总体方案

采用模块化单体，而不是独立业务 HTTP 服务，也不把全部业务重写进 AstrBot 插件。

```text
QQ 小号
   │
NapCat / OneBot 11
   │ reverse websocket
AstrBot
   │
Anime Plugin ─────── Anime Core ─────── PostgreSQL
   │                     ▲                    ▲
   │                     │                    │
   └──回复与通知投递      └──── Worker ───────┘
                              │
                  Bangumi / AniList / Mikan RSS
```

选择理由：

- 当前项目已有查询、订阅、排程、通知任务、投递记录和 PostgreSQL 测试基础；
- AstrBot 适合管理 OneBot 平台连接、插件生命周期、可选自然语言和消息发送；
- 数据同步、匹配、聚合和可靠通知不应依赖聊天框架的进程内状态；
- 首版只有 AstrBot 一个交互调用方，提前引入内部 HTTP 会增加鉴权、契约、部署和故障模式；
- Anime Core 先提供进程内 interface；出现 Web 或第二个独立调用方时，再增加 HTTP adapter。

被拒绝的方案：

- 独立 HTTP 后端：扩展性好，但首版多一个常驻服务和跨进程故障面；
- 全部重写为 AstrBot 插件：演示快，但会丢失现有 worker、数据库任务和可靠投递能力。

## 5. 运行单元

### 5.1 NapCat

负责：

- 登录专用 QQ 小号；
- 与 QQ 收发普通群消息；
- 通过 OneBot 11 反向 WebSocket 连接 AstrBot。

NapCat 不保存番剧、订阅或通知事实。QQ 登录数据和 NapCat 配置使用独立持久卷。NapCat 版本独立固定和升级，不随应用镜像更新。

### 5.2 AstrBot 与 Anime Plugin

负责：

- 把群消息和发送者映射为平台无关的 Chat Context；
- 解析固定命令；
- 可选调用大模型生成结构化意图；
- 调用 Anime Core 的查询与订阅 interface；
- 渲染文本、图片、引用和 `@`；
- 使用数据库租约消费 Notification Job；
- 记录 Delivery Attempt 和消费心跳。

插件不实现数据源同步、标题匹配、订阅规则或进程内定时器。AstrBot 重启不丢失业务事实。

### 5.3 Anime Core

Anime Core 是主要深模块，对调用方提供少量用例级 interface：

- 查询日、周、季度目录；
- 搜索和读取统一 Anime 详情；
- 查询下一次有效 Airing Occurrence；
- 建立、取消和列出 Follow Subscription；
- 更新 Resource Filter；
- 查询来源新鲜度和运行状态。

调用方不需要知道字段来自 Bangumi 还是 AniList，也不需要理解 Mikan 标题解析和来源匹配。

### 5.4 Worker

负责：

- 同步 Bangumi 与 AniList；
- 形成和刷新 Source Snapshot；
- 执行来源匹配与统一 Anime 投影；
- 轮询去重后的已订阅 Mikan RSS；
- 解析和保存 Resource Release；
- 打开和关闭 Release Batch；
- 根据 Airing Occurrence 和 Release Batch 生成 Notification Job；
- 清理过期事件、任务和投递记录；
- 写入进程和来源心跳。

Worker 只生成持久化通知任务，不直接连接 QQ。

### 5.5 PostgreSQL

PostgreSQL 是唯一业务事实来源，保存：

- 统一番剧身份和来源证据；
- 查询投影和放送事实；
- 群、成员、订阅和资源筛选；
- Mikan 原始发布和聚合窗；
- 通知任务、租约、投递尝试和去重键；
- 来源状态与进程心跳。

## 6. 数据源职责与融合

### 6.1 Bangumi

优先提供：

- 中文标题和中文别名；
- 中文简介；
- 中文社区评分；
- 中文条目关系；
- 成人标记；
- Mikan 页面明确给出的 Bangumi 链接所对应的映射锚点。

### 6.2 AniList

优先提供：

- 日文、英文和罗马字标题；
- 季度、类型和制作公司；
- 国际评分和热度；
- 角色、Staff 和作品关系；
- 下一集和完整放送计划；
- 成人标记。

AniList 查询必须走本地缓存和增量同步，不允许在每条 QQ 查询中实时调用。同步器必须读取限流响应头并遵守 `Retry-After`。

### 6.3 Mikan

只提供 Resource Release：

- Mikan 番剧 ID 和页面链接；
- RSS item 稳定标识；
- 原始资源标题；
- 字幕组；
- 简繁语言；
- 分辨率和其他可解析规格；
- 发布时间。

Mikan 不决定统一 Anime 的规范标题、评分或预计放送时刻。

### 6.4 字段投影

每个来源的 Source Snapshot 独立保存。统一 Anime 展示投影使用显式字段优先级：

| 字段 | 首选 | 降级 |
|---|---|---|
| 中文标题、中文别名、中文简介 | Bangumi | AniList |
| 日英标题、季度、类型、制作公司 | AniList | Bangumi |
| 中文评分 | Bangumi | 不展示 |
| 国际评分、热度 | AniList | 不展示 |
| 预计放送时刻 | AniList 精确时刻 | Bangumi 日期 |
| 成人标记 | 任一可信来源明确为真即屏蔽 | 全部来源未明确为真时不自动屏蔽，但保留来源状态 |
| 字幕组、语言、分辨率、资源发布时间 | Mikan | 无 |

来源更新只能更新自己的快照；统一投影由协调逻辑生成，后同步来源不能直接覆盖其他来源字段。

## 7. 统一身份与来源匹配

系统使用自身生成的 Anime ID。Bangumi、AniList 和 Mikan 的 ID 都保存在 External Entry 中，通过 Source Link 关联 Anime。

Source Link 状态：

- `confirmed`：可以参与正式查询投影、订阅和通知；
- `probable`：有较强候选，但必须等待进一步证据或人工确认；
- `unresolved`：没有可靠候选；
- `rejected`：已确认不应关联指定 Anime。

匹配证据优先级：

1. Mikan 页面明确提供的 Bangumi 条目链接；
2. 已存在的人工确认映射；
3. 来源提供的显式跨站 ID；
4. 日文规范标题 + 首播年份 + 作品类型 + 集数等严格组合；
5. 标题别名模糊匹配只能产生 probable 候选。

只有 confirmed Source Link 可以驱动通知。低置信度匹配不能因为“看起来像”而自动合并。管理员可以查询、确认或拒绝待处理映射，所有决定保留匹配方法、证据和时间。

## 8. 领域数据模型

核心记录：

- `animes`：内部 Anime ID、统一展示字段、成人和禁用状态；
- `external_entries`：provider、external ID、来源 URL 和可用状态；
- `anime_source_links`：Anime、External Entry、状态、方法、证据和确认时间；
- `source_snapshots`：来源条目的规范化字段、原始载荷和抓取时间；
- `anime_titles`：Anime 的多语言标题和别名；
- `airing_occurrences`：Anime、集数、日期/时刻、精度、来源和更新时间；
- `resource_releases`：Mikan 发布指纹、Mikan External Entry、可空的 Anime 映射、集数、字幕组、语言、分辨率、页面链接和发布时间；
- `chat_groups`：平台、QQ 群号、时区、启停和创建时间；
- `group_memberships`：群、QQ 用户号、角色和最近活动时间；
- `follow_subscriptions`：群、QQ 用户、Anime、开播开关和资源开关；
- `subscription_resource_filters`：语言、字幕组和分辨率筛选；
- `release_batches`：Anime、集数、窗口开始/结束和状态；
- `notification_jobs`：类型、群、业务唯一键、有效期、状态和租约；
- `delivery_attempts`：每次 AstrBot 平台投递及结果；
- `processed_platform_events`：OneBot 事件去重；
- `source_sync_states`：每个来源的最后成功、失败和限流状态；
- `worker_heartbeats`：Worker 与 AstrBot 通知消费者的健康状态。

关键唯一性：

```text
external_entries(provider, external_id)
follow_subscriptions(group_id, qq_user_id, anime_id)
resource_releases(provider, release_fingerprint)
release_batches(anime_id, episode_key, window_started_at)
notification_jobs(group_id, notification_type, business_key)
processed_platform_events(platform, event_id)
```

集数无法可靠解析时保存原始 `episode_label`，不强制转换为整数。剧场版、OVA、总集篇和分割放送不能仅靠文件名中的数字归入普通 TV 集数。

## 9. 核心数据流

### 9.1 群内查询

1. NapCat 把 OneBot 事件交给 AstrBot。
2. Anime Plugin 构造 Chat Context 并做事件去重。
3. 固定命令解析为 Query；自然语言可选地转换为同一种 Query。
4. Anime Core 只查询 PostgreSQL 的统一投影。
5. 多候选时返回内部 ID 和编号列表。
6. 插件生成普通 QQ 文本、图片或引用回复。

外部数据源不在交互请求路径上。来源故障不能直接拖垮群内查询。

### 9.2 订阅变更

1. 用户通过唯一结果或明确内部 ID 选择 Anime。
2. 系统展示开播、资源提醒和当前 Resource Filter。
3. 固定命令直接执行；自然语言请求等待确认。
4. Anime Core 幂等新增、恢复、更新或关闭 Follow Subscription。
5. 插件回复变更后的完整订阅状态。

### 9.3 预计放送

1. Worker 同步并协调 Bangumi/AniList 的放送事实。
2. 只有 confirmed Anime 和精确时刻形成可提醒 Airing Occurrence。
3. 到时为每个有匹配订阅的群创建唯一 Notification Job。
4. AstrBot 插件按租约领取任务。
5. 一条群消息合并并 `@` 全部订阅用户。
6. 保存 Delivery Attempt，并更新任务终态。

### 9.4 Mikan 资源发布

1. Worker 对去重后的已订阅番剧 RSS 做条件请求。
2. RSS item 依据 GUID、页面链接和规范化内容指纹去重。
3. 原始 item 与解析结果保存为 Resource Release；尚未确认映射时 `anime_id` 为空。
4. 只有 confirmed Source Link 的发布进入 Release Batch。
5. 首个发布开启 10 分钟聚合窗，后续同番同集发布加入同一窗口。
6. 窗口结束后按 Resource Filter 计算每位用户的匹配结果。
7. 每群生成一个 Notification Job，合并受众并最多展示 5 条资源。
8. AstrBot 投递并记录结果。

## 10. 通知投递语义

Notification Job 状态：

```text
pending -> leased -> sent
                  -> retry -> pending
                  -> failed
                  -> unknown
                  -> expired
```

- 数据库租约避免多个插件实例重复领取。
- 明确的限频或临时错误按照 `retry_after` 或指数退避重试。
- 明确的永久错误进入 failed。
- 请求已发送但响应不确定时进入 unknown，不自动重试，避免刷群。
- 每种通知都具有业务唯一键和 `expires_at`。
- AstrBot 或 NapCat 短时离线时任务留在 Outbox；恢复后只处理仍在有效期内的任务。

投递保证为“至少一次规划、尽量一次发送”。外部 QQ 平台无法提供数据库级 exactly-once，因此系统通过业务唯一键、租约、平台消息 ID 和 unknown 状态降低重复概率，而不宣称绝对不重复。

## 11. 同步、限流与数据新鲜度

默认值均可通过部署配置调整：

- 当前季度完整目录：每 6 小时；
- 活跃番剧放送时刻：每 30 分钟；
- 已订阅且已映射的 Mikan RSS：每 5 分钟；
- Mikan Release Batch：首次发现后 10 分钟关闭；
- Worker 到期任务扫描：每 30 秒；
- AstrBot 通知 Outbox 扫描：每 3 秒。

Mikan RSS 调度按唯一 Mikan 番剧 ID 去重，设置全局并发上限、请求抖动、超时、退避，并使用 ETag 或 Last-Modified 条件请求。订阅数量增加时按轮询批次摊开请求，不能在同一秒集中访问全部 RSS。

建议陈旧阈值：

- Bangumi 目录超过 24 小时；
- AniList 目录超过 24 小时；
- 活跃放送计划超过 2 小时；
- Mikan 轮询超过 15 分钟。

查询在存在缓存时继续返回数据，并在超过阈值时附加来源和更新时间提示。一次同步失败不得清空上一份成功快照。

## 12. 错误与边缘情况

### 12.1 来源故障

- 三个来源独立记录成功、失败、限流和最后错误。
- 一个来源失败不阻止其他来源同步。
- AniList `429` 遵守响应中的等待时间。
- Mikan RSS 返回异常内容时保留响应摘要和 feed 标识，不把空结果解释为资源被删除。
- 连续失败通过 `/番剧 状态` 暴露给管理员。

### 12.2 映射和解析失败

- unresolved/probable 记录不触发通知。
- 修复映射后，只补处理仍在 24 小时有效期内的 Mikan 发布。
- 字幕组、语言或分辨率无法解析时使用 unknown，而不是猜测默认值。
- Resource Filter 只匹配明确值；用户选择“不限”时才接受 unknown。

### 12.3 QQ 与 AstrBot 故障

- OneBot 断线不丢失 Notification Job。
- AstrBot 重启后重新获取已过期的数据库租约。
- 无法找到群、机器人已退群或被禁言时记录永久错误并暂停该群的后续投递，等待管理员恢复。
- 私聊消息不创建群订阅。

### 12.4 时间

- 数据库存储 UTC；
- 群展示使用群时区，默认 `Asia/Shanghai`；
- 数据源只有日期时保存日期精度，不伪造零点时刻；
- 夏令时转换依赖 IANA timezone。

## 13. 部署设计

Docker Compose 包含五个运行单元：

```text
postgres
migrate
napcat
astrbot
worker
```

### 13.1 网络与访问

- PostgreSQL、OneBot WebSocket 和内部健康端点只在 Compose 网络开放。
- NapCat WebUI 与 AstrBot WebUI 默认只绑定 `127.0.0.1`，远程管理使用 SSH 隧道或受控反向代理。
- OneBot 反向 WebSocket 使用随机高强度 token。
- 容器不共享 Docker socket。
- QQ 登录数据、NapCat 配置、AstrBot 数据和 PostgreSQL 分别使用持久卷。

### 13.2 镜像和版本

- NapCat 与 AstrBot 使用明确版本，不在生产环境追踪 `latest`。
- Anime Plugin 与 Anime Core 由项目构建的 AstrBot 镜像携带。
- Worker 使用项目应用镜像。
- NapCat 独立升级；应用发布不得覆盖 QQ 登录卷。

### 13.3 发布顺序

1. 验证配置并备份 PostgreSQL。
2. 拉取固定版本镜像。
3. 运行 migrate。
4. 更新 Worker 并验证心跳。
5. 更新 AstrBot 并验证数据库和 OneBot 连接。
6. 验证通知消费者和测试群查询。
7. 失败时回滚应用镜像；不自动回滚已经执行且不兼容的数据库迁移。

破坏性迁移必须先提供前向修复策略或兼容窗口。NapCat 登录数据不参与常规应用回滚。

### 13.4 旧系统迁移

- 不迁移 QQ 官方机器人群、openid、管理员身份和订阅。
- 删除运行时代码中的 QQ 官方 adapter、鉴权、事件协议、相关配置和依赖。
- 新表使用普通 QQ 群号和 QQ 用户号。
- 旧番剧缓存可直接重新同步，不作为必须迁移的数据。
- 旧通知和投递记录不进入新产品事实模型。
- 历史设计规格可以作为历史记录保留，但 README、部署和运维文档必须只指向新架构。

## 14. 可观察性与运维

结构化日志至少包含：

- trace ID、平台事件 ID、群号的不可逆摘要；
- Anime ID、External Entry provider/ID；
- RSS feed、release fingerprint、Release Batch ID；
- Notification Job ID、Delivery Attempt ID 和结果；
- 来源耗时、限流、重试时间和错误分类。

默认不把 QQ 消息全文、RSS token、OneBot token、数据库密码或完整用户隐私信息写入日志。

健康状态：

- AstrBot：数据库连通、OneBot 已连接、通知消费者心跳；
- Worker：数据库连通、计划循环心跳、每个来源最后成功时间；
- NapCat：QQ 登录状态和反向 WebSocket 状态；
- PostgreSQL：容器健康检查。

管理员 `/番剧 状态` 返回简化状态，不泄露凭据和内部异常堆栈。`/番剧 映射待处理` 返回 unresolved/probable 数量和有限候选。

## 15. 测试策略

### 15.1 单元测试

- Source Link 状态和字段投影；
- 严格标题匹配与不允许自动合并的边缘情况；
- OVA、剧场版、总集篇和分割放送解析；
- Resource Filter；
- Release Batch 窗口和最多 5 条展示；
- Airing/Mikan 任务业务唯一键；
- 任务有效期、重试和 unknown 决策；
- 固定命令与自然语言确认规则。

### 15.2 契约测试

使用固定 fixture 验证：

- Bangumi REST 响应；
- AniList GraphQL 正常、部分错误、`429` 和字段为空；
- Mikan RSS 正常、重复 GUID、缺字段和异常标题；
- AstrBot 消息事件和发送 interface；
- NapCat/OneBot 群消息、引用、图片和 `@` 表示。

### 15.3 PostgreSQL 集成测试

- Anime 与 External Entry 映射约束；
- 同步快照不互相覆盖；
- 订阅和资源筛选幂等；
- RSS 去重；
- Release Batch 并发合并；
- Notification Job 唯一键；
- 多消费者租约和崩溃恢复；
- 过期任务处理。

### 15.4 端到端测试

使用 FakePlatform adapter 覆盖：

- 查询、候选选择、详情；
- 订阅、取消、修改筛选；
- 到时开播提醒；
- 多个 Mikan item 聚合成一条提醒；
- 来源故障时缓存查询；
- AstrBot/Worker 重启后任务恢复；
- 自然语言模型不可用时固定命令仍工作。

### 15.5 真实测试群验收

- 专用小号登录并保持连接；
- 普通群消息和固定命令；
- 文本、图片、引用和 `@`；
- 主动通知；
- NapCat 与 AstrBot 分别重启；
- 小号退群、禁言和重新加入；
- 服务运行观察期内无重复刷屏。

## 16. 首版验收标准

全部满足才算完成：

### 16.1 功能

- 今日、本周、季度、搜索、详情和下一次预计放送查询可用；
- 用户可订阅、取消、查看订阅并修改 Resource Filter；
- 精确放送时刻到达后生成一条群提醒并正确 `@` 用户；
- 同番同集多个 Mikan 资源在正常网络下约 15–20 分钟内形成一条聚合提醒；
- Mikan 消息包含字幕组、语言、分辨率、发布时间和页面链接；
- 未配置或暂停大模型时固定命令全部可用。

### 16.2 正确性

- Follow Subscription 指向内部 Anime ID；
- Bangumi、AniList 和 Mikan 的外部 ID 不作为订阅主键；
- unresolved/probable 映射不触发通知；
- 只有日期的放送记录不触发逐集提醒；
- 成人内容不出现在查询和通知中；
- 资源筛选只影响资源提醒。

### 16.3 可靠性

- 重复 RSS、重复平台事件和容器重启不生成重复 Notification Job；
- 一个来源中断时，其余来源和缓存查询继续工作；
- AstrBot/NapCat 短时掉线后，未过期任务恢复投递；
- 请求结果不确定时不自动重复发送；
- PostgreSQL 备份与恢复演练通过；
- Worker、AstrBot 和来源新鲜度可观察。

### 16.4 部署

- 五个 Compose 运行单元使用固定镜像版本启动；
- WebUI 和内部端口默认不暴露公网；
- OneBot token 生效；
- NapCat 登录卷在应用更新后保持；
- README、部署和运维文档只描述新架构；
- QQ 官方 adapter、openid 运行模型和相关配置从新版本中移除。

## 17. 交付分片

本规格描述一个统一产品目标，但实现必须按可独立验收的纵向分片推进，不能一次性重写后再集中联调：

1. **统一身份基础**：建立 Anime、External Entry、Source Link 和来源快照；迁入现有 Bangumi adapter，证明查询结果不再依赖 Bangumi ID 作为主键。
2. **群内查询闭环**：接入 NapCat、AstrBot 和薄插件，用固定命令完成测试群搜索、详情、今日/本周/季度查询；同时移除 QQ 官方运行路径。
3. **AniList 融合**：增加 GraphQL adapter、限流、快照和字段投影，完成 Bangumi/AniList 映射及降级验收。
4. **追番与开播提醒**：建立普通 QQ 群身份、Follow Subscription、Airing Occurrence、Notification Job 和 AstrBot Outbox 投递闭环。
5. **Mikan 资源提醒**：增加公开 RSS 调度、Resource Release、严格映射、Resource Filter 和 10 分钟 Release Batch。
6. **生产化收口**：完成固定版本 Compose、健康检查、日志、备份恢复、掉线恢复、安全配置和真实测试群观察。

每个分片必须保持数据库可迁移、固定命令可运行、已有自动化测试通过。后一个分片不得通过复制平行业务模型绕过前一个分片建立的 seam。

## 18. 后续扩展 seam

首版只预留、不实现：

- Anime Core 的 HTTP adapter，供 Web 或外部调用方使用；
- Telegram、Discord 等新的 Chat Platform adapter；
- Bangumi/AniList 账号同步；
- 提前 10/30 分钟提醒；
- 更多 RSS 或正版流媒体资源来源；
- Web 管理和人工映射页面；
- 自动下载作为独立、显式授权的下游模块；
- 推荐、自然语言问答和更丰富的 AstrBot tools。

这些扩展必须复用 Anime、Source Link、Follow Subscription 和 Notification Job，不得另建一套平行身份或订阅模型。

## 19. 参考

- [AstrBot OneBot v11 接入](https://docs.astrbot.app/platform/aiocqhttp.html)
- [AstrBot 插件开发](https://docs.astrbot.app/dev/plugin.html)
- [OneBot 11 标准](https://11.onebot.dev/)
- [NapCatQQ](https://github.com/NapNeko/NapCatQQ)
- [AniList GraphQL 入门](https://docs.anilist.co/guide/graphql/)
- [AniList 限流](https://docs.anilist.co/guide/rate-limiting)
- [AniList Media 字段](https://docs.anilist.co/reference/object/media)
- [Mikan Project](https://mikanani.me/)
- [本项目领域词汇](../../../CONTEXT.md)
- [ADR-0001：使用独立的内部番剧身份](../../adr/0001-use-internal-anime-identity.md)

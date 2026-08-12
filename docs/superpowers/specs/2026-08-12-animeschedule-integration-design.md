# AnimeSchedule 映射桥与精确排期源设计

- 日期：2026-08-12
- 状态：已确认
- 范围：在现有 Bangumi、AniList、Mikan 多源目录中新增 AnimeSchedule，分别承担跨站 ID 映射桥和日本原始播出排期补充职责

## 1. 背景

生产当前以 Bangumi 条目建立内部 Anime 身份，再通过严格标题与首播日规则寻找 AniList
条目。生产核查发现 69 条最新未确认评估，其中 34 条为 AniList 标题搜索无候选，31 条为
标题匹配但首播日不一致，另有 3 条标题不匹配和 1 条 Bangumi 元数据缺失。运行参数曾被
调整为每轮 30 次查询、1 小时失败冷却，在每 6 小时目录周期中会让同一批不可映射条目
反复具备重试资格并增加 AniList 429 风险。

使用正式 AnimeSchedule Application Token 对上述 69 条生产记录执行了一次只读覆盖率
验证，采用“Bangumi 日文名优先搜索，AnimeSchedule 标题与别名做 Unicode NFKC、大小写、
空白归一化后唯一精确匹配”的保守判据：

| 原 AniList 评估原因 | 条数 | AnimeSchedule 唯一精确命中 | 其他结果 |
|---|---:|---:|---|
| 首播日不一致 | 31 | 27（87.1%） | 1 模糊、3 个 HTTP 500 |
| 搜索无候选 | 34 | 2（5.9%） | 1 模糊、31 个 HTTP 500 |
| 标题不匹配 | 3 | 1 | 2 模糊 |
| Bangumi 元数据缺失 | 1 | 0 | 1 模糊 |
| 合计 | 69 | 30（43.5%） | 5 模糊、34 个 HTTP 500 |

30 个唯一精确结果均提供 AniList、MyAnimeList、AniDB 跨站 ID 和日本播出时间字段。
AnimeSchedule 对“标题已知但日期不一致”的日本新番很有价值，但对国产动画、样片、番外
和部分未收录标题会稳定返回 HTTP 500，而不是正常空列表。因此它适合作为补充来源，不适合
直接替换 AniList。

生产 Worker 已验证可以正常解析域名、建立 TLS 连接并访问 AnimeSchedule API。正式鉴权
响应包含每分钟 120 次的限流头；未携带 Application Token 的公共端点不作为产品依赖。

## 2. 目标

- 使用 AnimeSchedule 显式提供的 AniList ID，补回 AniList 标题搜索漏召回和日期口径冲突；
- 同步 AnimeSchedule `raw` 日本播出排期，提高今日、本周、下一集和开播提醒的精确时间覆盖；
- 保留 Bangumi、AniList、AnimeSchedule 各自的原始快照和排期证据，不让后同步来源覆盖其他来源；
- 对多个精确排期来源使用确定、可解释、可测试的选择规则；
- 将 AnimeSchedule 500、429、空结果、模糊结果和冲突分别记录，避免统一显示为“未找到候选”；
- 所有外部调用只发生在 Worker 后台，QQ群内命令继续只读 PostgreSQL 本地数据；
- 功能默认关闭，经 bot 持有者配置 Token、验证健康并完成小预算灰度后再启用。

## 3. 非目标

- 不以 AnimeSchedule 替换 Bangumi、AniList 或 Mikan；
- 不改变内部 Anime ID，也不以任一外部来源 ID 作为业务主键；
- 不使用模糊标题自动合并条目；
- 不把 AnimeSchedule `sub` 或 `dub` 时间解释为实际字幕资源发布；
- 不改变 Mikan 的资源发现、聚合、筛选、就近集数或个人订阅通知语义；
- 不在 QQ 命令处理期间请求 AnimeSchedule；
- 不自动修正或删除来源间日期冲突记录；
- 不把 Application Token 写入 Git、日志、管理 API 响应或后台页面。

## 4. 来源职责

| 能力 | 主来源 | 补充来源 |
|---|---|---|
| 中文标题、国产动画、中文简介 | Bangumi | AniList |
| 全球条目详情、海报、评分 | AniList | Bangumi |
| 显式跨站 ID 映射桥 | AnimeSchedule | 现有严格标题与首播日匹配 |
| 日本原始播出精确时间 | AnimeSchedule `raw` | AniList |
| 仅日期排期 | Bangumi | 无 |
| 实际字幕资源发布 | Mikan | 无 |

`AiringOccurrence` 表示预计播出，`ResourceRelease` 表示实际资源发布。AnimeSchedule 的
字幕或配音排期不是 Mikan 资源证据，不能创建资源通知。

## 5. 数据模型

AnimeSchedule 使用现有多源模型，不引入新的内部番剧身份：

- `external_entries.provider = 'animeschedule'`；
- `external_entries.external_id` 使用稳定的 AnimeSchedule route；
- `source_snapshots` 保存规范化标题、别名、首播时间、raw/sub/dub 时间、跨站 ID、状态和原始载荷；
- `anime_source_links` 保存 Anime 与 AnimeSchedule 条目的关联，自动确认方法为
  `animeschedule_cross_id_v1`；
- `airing_occurrences` 保存 AnimeSchedule `raw` timetable 的逐集预计播出；
- `source_sync_states.provider = 'animeschedule'` 保存成功、失败、游标和限流状态。

现有 `anilist_mapping_assessments` 仍表示“为内部 Anime 寻找 AniList 条目的最终评估”。
AnimeSchedule 是该流程新增的证据来源，不另建重复的映射评估表。最终原因扩展为可区分：

- `animeschedule_cross_id_confirmed`：只作为 Source Link 方法和统计，不保留失败评估；
- `animeschedule_search_empty`：上游正常返回但无唯一精确候选；
- `animeschedule_search_error`：上游 5xx 或无效响应；
- `animeschedule_ambiguous`：模糊或多个精确候选；
- `animeschedule_cross_id_invalid`：显式 AniList ID 无法读取；
- `animeschedule_year_mismatch`：来源首播年份冲突；
- `animeschedule_nsfw_rejected`：任一可信来源明确标记成人。

确认成功后沿用当前行为删除该 Anime 的失败评估。成功数量通过 Source Link 的 `method`
统计，避免把成功历史伪装成待处理记录。

## 6. 映射桥

### 6.1 候选搜索

Worker 只选择拥有已确认 Bangumi Link、缺少已确认 AniList Link、未禁用、未明确为成人且
不在重试冷却中的 Anime。依次使用去重后的 Bangumi 日文名和中文名搜索 AnimeSchedule，
但每次实际 HTTP 请求都计入预算。

标题比较使用 Unicode NFKC、`casefold` 和所有空白移除。搜索结果的主标题、罗马字、英文、
日文、缩写与 synonyms 都作为别名集合。只有唯一结果的某个别名与 Bangumi 已知标题精确
相交，才能进入显式 ID 校验。模糊结果和多个精确候选都不能自动确认。

### 6.2 显式 AniList ID 校验

唯一精确 AnimeSchedule 候选必须提供 AniList URL，并能解析出有效数字 ID。Worker 随后
调用 AniList `fetch_media(id)`，而不是再次做标题搜索。

自动确认必须同时满足：

1. AnimeSchedule 候选是唯一归一化精确标题命中；
2. AnimeSchedule 明确提供 AniList ID；
3. AniList 按 ID 能读取完整条目；
4. AniList 标题与 Bangumi 已知标题仍有归一化精确交集；
5. Bangumi、AnimeSchedule、AniList 已知首播年份一致；
6. 任一可信来源都没有明确成人标记；
7. 该 AnimeSchedule 或 AniList External Entry 未被其他 Anime 的 confirmed Link 占用。

跨站显式 ID 比“首播日完全相等”更强，因此日、月差异不再阻止确认；具体日期差异作为
冲突证据保存。确认后同步 AniList 详情和排期，并建立 AnimeSchedule confirmed Link。

AnimeSchedule 桥接失败后仍可使用现有 AniList 严格标题与首播日路径作为后备，但同一轮的
所有实际请求共享总预算，不能因双路径使请求数失控。

## 7. 排期同步与选择

### 7.1 timetable 同步

每个目录周期最多请求一次当前周 AnimeSchedule `raw` timetable，明确传入
`tz=Asia/Tokyo`。只处理已经拥有 confirmed AnimeSchedule Link 的条目。每条排期写入：

- `episode_label`：AnimeSchedule episode number 的稳定字符串；
- `air_at`：`episodeDate` 的带时区时刻；
- `air_date`：将 `air_at` 投影到群时区前的来源日期；
- `precision = 'exact'`；
- `source_event_key`：provider、route、air type、episode 和 episodeDate 组成的稳定业务键。

重复同步必须幂等。延期和 episode override 以同一个来源事件的新版本更新，不产生重复集数。
`sub`、`dub` 和流媒体平台字段保存在 Snapshot 中，第一版不生成正式 AiringOccurrence。

### 7.2 统一排期选择器

现有查询只保证精确时间优先于日期记录，两个精确来源之间没有稳定优先级。新增一个统一
排期选择器，供今日、本周、下一集、单番详情、开播提醒规划和后台目录共同使用。

同一 Anime 和标准化集数的优先级为：

1. AnimeSchedule `raw` 精确时刻；
2. AniList 精确时刻；
3. Bangumi 日期记录。

选择器只决定展示和通知采用哪条记录，不删除其他来源数据。如果 AnimeSchedule 与 AniList
的精确时刻相差超过 6 小时，记录 `schedule_conflict`，后台显示两侧来源和值；在冲突消除前
继续使用最近一次已稳定选中的排期，不根据新冲突时间创建补偿提醒。首次出现冲突且没有
稳定值时不创建主动开播提醒，但被动查询仍显示带来源的最佳可用时间。

展示层继续按 Anime、自然日和标准化集数去重，不能因新增来源在今日或本周图片中出现双卡。

## 8. 同步、预算与冷却

AnimeSchedule 只由 Worker 调用，复用当前 6 小时目录周期：

1. 拉取一次本周 raw timetable；
2. 优先处理未来 7 天缺 AniList 映射且不在冷却中的 Anime；
3. 使用每轮最多 12 次实际 AnimeSchedule 搜索请求的默认预算；
4. 对桥接成功的条目按 ID 同步 AniList；
5. 剩余预算允许现有 AniList 后备发现；
6. 更新投影、排期选择和来源健康状态。

默认冷却：

| 结果 | 行为 |
|---|---|
| HTTP 429 | 立即停止本轮，遵守 `Retry-After`，不写无候选评估 |
| HTTP 5xx / 无效响应 | `animeschedule_search_error`，冷却 7 天 |
| 正常空结果 | `animeschedule_search_empty`，冷却 7 天 |
| 模糊或多个精确候选 | `animeschedule_ambiguous`，等待人工处理或快照变化 |
| AniList ID 无效、年份冲突、成人 | 对应明确原因，冷却 24 小时 |
| timetable 临时失败 | 保留旧排期，不删除、不降级 |

Bangumi 最新 Snapshot 的标题、首播年份或外部链接发生变化时，可以提前解除该 Anime 的
长冷却。AnimeSchedule 故障不得阻塞 Bangumi、AniList、Mikan 或本地命令处理。

## 9. 配置与安全

新增配置：

```dotenv
ANIMESCHEDULE_TOKEN=
ANIMESCHEDULE_ENABLED=false
ANIMESCHEDULE_QUERY_BUDGET=12
ANIMESCHEDULE_PRIORITY_WINDOW_DAYS=7
ANIMESCHEDULE_EMPTY_COOLDOWN_HOURS=168
ANIMESCHEDULE_ERROR_COOLDOWN_HOURS=168
```

Token 使用 `SecretStr`，只通过 `.env` 和容器环境注入。日志、异常、审计、后台读取 API、
测试快照和命令输出不得包含 Token、Authorization Header 或完整请求对象。后台只返回
`token_configured: true/false`。

功能默认关闭。没有 Token 时开启请求必须被验证层拒绝；Token 无效时记录来源失败并保持
其他来源运行。开发和测试不得使用生产 Token。

## 10. 后台与权限

只有 bot 持有者可以通过现有 AstrBot 管理后台：

- 启用或关闭 AnimeSchedule；
- 调整映射查询预算、优先窗口和冷却时间；
- 手动触发一次 AnimeSchedule 同步；
- 查看 Token 是否配置；
- 查看候选、冲突和来源健康；
- 确认或拒绝模糊候选。

QQ群主、群管理员和普通成员均不能配置数据源。所有写操作继续受 Dashboard 登录、TOTP、
后台写开关和审计事件保护。

看板新增：

- 最近成功、失败、错误摘要和限流剩余；
- confirmed AnimeSchedule Link 数；
- `animeschedule_cross_id_v1` 补回的 AniList 映射数；
- AnimeSchedule 精确排期覆盖数；
- 精确时间来源冲突数；
- 空结果、5xx、模糊、无效跨站 ID 和年份冲突计数。

## 11. 测试

### 11.1 适配器契约

- Bearer Token、User-Agent、查询参数和时区；
- 搜索、详情、raw timetable 和跨站 URL 解析；
- 200、正常空列表、429、500、无效 JSON 和缺字段；
- 限流头和 `Retry-After`；
- Token 与 Authorization Header 不进入异常字符串。

### 11.2 映射集成

- 唯一精确标题与显式 AniList ID 自动确认；
- 日期不同但年份一致时仍能确认；
- 模糊、多个精确候选、年份冲突、成人条目和 ID 占用拒绝确认；
- AnimeSchedule 失败后 AniList 后备路径仍受共享预算约束；
- 500 和空结果使用长冷却，429 不记录错误候选；
- Bangumi 关键元数据变化可解除长冷却。

### 11.3 排期与产品行为

- raw timetable 幂等写入和延期更新；
- AnimeSchedule、AniList、Bangumi 的稳定优先级；
- 超过 6 小时冲突的记录和主动提醒抑制；
- 今日、本周、下一集、详情和开播提醒使用同一个选择器；
- 多来源不会生成重复卡片、重复 Notification Job 或补偿提醒；
- Mikan 资源发现、个人订阅通知和每日资源汇总保持原行为。

### 11.4 安全与后台

- 功能默认关闭；
- 无 Token 时拒绝开启；
- 只有 bot 持有者可写；
- 后台只显示 Token 配置状态；
- 审计记录配置前后值但排除 Token；
- AnimeSchedule 故障不影响 Worker 心跳和其他来源同步。

## 12. 上线与回滚

1. 本地运行静态检查、完整测试、空数据库迁移和 Compose 配置验证；
2. 通过既有 ACR 流程发布，生产先保持 `ANIMESCHEDULE_ENABLED=false`；
3. 注入生产 Application Token，验证 Token 状态、来源健康、限流头和容器日志脱敏；
4. 以小预算启用一次映射桥，检查新增 confirmed Link、拒绝原因和 ID 冲突；
5. 同步 raw timetable，检查未来 7 天排期覆盖、6 小时冲突和重复卡片；
6. 在测试群验收 `/番剧 今天`、`/番剧 本周`、`/番剧 下一集` 和一次开播提醒；
7. 观察至少一个 6 小时目录周期后再恢复默认预算。

回滚优先关闭 `ANIMESCHEDULE_ENABLED`。关闭后停止新请求和新排期写入，查询选择器忽略
AnimeSchedule 记录并回到 AniList 精确时间、Bangumi 日期的原顺序。现有 SourceSnapshot、
SourceLink 和 AiringOccurrence 保留作为审计证据，不做破坏性删除；数据库迁移仅在完整
应用回滚确有需要时按部署备份恢复。

## 13. 验收标准

- 正式 API 请求全部携带 Application Token，限流状态可观测且 Token 不泄漏；
- 生产验证中已知的首播日不一致样本能够通过显式 AniList ID 安全补回；
- 模糊、多个候选、年份冲突、成人和 ID 占用不会自动确认；
- AnimeSchedule 500 不再被显示为“未找到候选”，同一条目不会每轮重试；
- 今日、本周、下一集、详情和开播提醒对同集只选择一条排期；
- 精确来源相差超过 6 小时时可见冲突且不产生不安全的主动补偿提醒；
- AnimeSchedule 关闭或故障时，Bangumi、AniList、Mikan、QQ群命令和现有资源通知继续工作；
- 后台控制仍只属于 bot 持有者；
- 生产容器健康、Worker 零异常重启和 OneBot 连接不代表 QQ 验收完成，测试群命令与提醒必须单独通过。

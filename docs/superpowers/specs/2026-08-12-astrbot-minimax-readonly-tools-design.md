# AstrBot MiniMax 只读番剧 Tools 与每群通用聊天策略设计

- 日期：2026-08-12
- 状态：已确认
- 范围：让 AstrBot 原生 MiniMax 对话通过只读 Tools 使用现有 Anime Core，并按群控制是否允许非番剧通用聊天

## 1. 背景

项目已经通过 NapCat 和 AstrBot 接入 QQ 小号，具备固定番剧命令、群内订阅、预计放送
提醒、Mikan 资源通知、图片卡片、群策略和内嵌管理页。MiniMax Token Plan 已在 AstrBot
中配置完成，测试群通过明确 `@机器人` 可以进行普通 LLM 对话。

现有 `anime_tracking` 插件的 `@机器人` 交互网关只支持有限的本地短语。网关开启时，
无法识别的自然语言会被插件以 `not a supported mention command` 拦截；关闭网关后，
消息可以进入 AstrBot 原生 Agent，但模型不了解 PostgreSQL 中的实时番剧、资源和个人订阅
事实。

本设计不再增加一套独立 LLM 客户端或分类器。项目把现有只读 Anime Core 能力注册为
AstrBot LLM Tool，由 AstrBot 保留 MiniMax 会话、人格和工具循环。固定 `/番剧` 命令继续
独立运行。

## 2. 目标

- 只有群内明确 `@机器人` 的 LLM 对话可以自动调用番剧 Tool；
- 支持今天、本周、季度、搜索、详情、下一集、资源详情和我的订阅八类只读能力；
- 番剧事实来自现有 Anime Core/PostgreSQL，不允许模型根据训练知识猜测实时结果；
- 保留 AstrBot 原生 MiniMax 会话、人格和非番剧通用聊天能力；
- 为每个群增加独立的“通用聊天”开关，默认关闭；
- 只有机器人管理者可以在现有 AstrBot 内嵌管理页修改该开关；
- 通用聊天关闭时，由代码阻止未使用番剧 Tool 的自由回答；
- MiniMax 或 Tool 不可用时，原有固定命令、订阅、通知和 Worker 不受影响。

## 3. 非目标

- 不让 LLM 新增、取消或修改订阅；
- 不开放管理操作、任意 SQL、任意 URL、跨群查询或跨用户查询；
- 不监听未 `@机器人` 的普通群消息；
- 不把 QQ 群主或 QQ 群管理员映射为机器人配置管理员；
- 不在自然语言入口复用现有图片卡片，首版由 MiniMax 根据 Tool 文本结果组织回答；
- 不替换 `/番剧` 固定命令，不让固定命令依赖 MiniMax；
- 不增加独立 LLM SDK、模型 Key 配置、模型代理、MCP 服务或新的公网端口；
- 不在本设计中实现本地模型、RAG、长期记忆或主动 LLM 推送。

## 4. 已确认的产品规则

### 4.1 入口

首版只处理群内明确 `@机器人` 后由 AstrBot 唤醒的 LLM 对话。普通群消息不会触发
MiniMax，也不会调用番剧 Tool。私聊不纳入每群策略范围。

`interaction_gateway_enabled` 继续保持关闭，避免旧的有限短语解析器抢先停止事件传播。
`/番剧` 命令仍由现有命令组处理，直接返回原文本或图片卡片。

### 4.2 只读能力

Tool 暴露封闭的 action 集合：

| action | 业务含义 | 允许参数 |
|---|---|---|
| `today` | 群时区的今日番剧 | 可选 ISO 日期 |
| `week` | 群时区的本周番剧 | 无 |
| `season` | 指定季度番剧 | 年份、冬春夏秋 |
| `search` | 搜索番剧 | 关键词或候选编号 |
| `detail` | 番剧详情 | 关键词或候选编号 |
| `next` | 下一次预计放送 | 关键词或候选编号 |
| `resource_detail` | 已聚合资源详情 | 关键词或候选编号、可选集数 |
| `my_subscriptions` | 当前用户在当前群的订阅 | 无 |

Tool 不接受 Anime 内部 UUID、群号、用户 QQ、平台、数据库连接、URL 或任意字段名。需要
多候选时复用现有 `InteractionSession`：候选按当前平台、当前群、当前用户和有效期隔离，
后续可以用编号继续查询，不向群成员暴露内部 UUID。

自然语言提出订阅、退订或修改筛选时不执行写入，只提示使用对应固定命令，例如
`/番剧 订阅 <番剧名>`。

### 4.3 回复呈现

自然语言入口由 Tool 返回来源明确、长度受控的结构化文本，MiniMax 负责组织最终自然语言
回答。首版不让 Tool 直接发送图片，也不在 Tool 内发送额外 QQ 消息，避免 Agent 最终回复
产生重复消息。

固定命令继续使用现有 Reply、文本和图片卡片；因此用户需要原有确定性卡片时仍可使用
`/番剧`。

## 5. 架构

```text
QQ 群明确 @机器人
  -> NapCat / OneBot 11
  -> AstrBot 原生 Agent + MiniMax
       -> anime_readonly Tool
            -> 事件身份映射
            -> 封闭 Intent
            -> Anime Core
            -> PostgreSQL 投影
       -> MiniMax 根据 Tool 结果组织回答
  -> LLMPolicyGuard 在发送前执行每群策略

/番剧 固定命令
  -> Anime Plugin / EventAdapter
  -> Anime Core
  -> 原文本或图片卡片
```

### 5.1 `AnimeReadonlyTool`

插件通过 AstrBot 4.26 支持的 Tool API 注册一个 `anime_readonly` Tool。Tool Schema 只包含
`action` 及 action 所需的业务参数；注册和调用不依赖 MiniMax 专有 SDK。

Tool 从 `AstrMessageEvent` 读取平台、群、用户、昵称、UMO 和管理员状态，构造现有
`ChatContext`。模型提供的参数不能覆盖身份。Tool 复用现有 `Intent`、查询 use case、候选
持久化和文本等价呈现，不复制 Bangumi、AniList、Mikan 或订阅查询逻辑。

Tool 结果使用稳定 DTO，至少包含：

- `status`：`ok`、`not_found`、`invalid_request` 或 `unavailable`；
- `action`：实际执行的只读 action；
- `content`：供模型回答的结构化文本；
- `truncated`：是否因长度上限截断；
- `guidance`：无结果、候选选择或固定命令提示。

外部标题、简介、字幕组和资源文本一律作为不可信数据字段，不解释为指令。输出限制总字符
数和单字段长度；超过上限时保留现有排序的前部结果并提示缩小查询范围。

### 5.2 `LLMPolicyGuard`

策略守卫只作用于 QQ 群内明确 `@机器人` 的 AstrBot Agent 轮次，不改变固定命令、主动
通知、私聊或未唤醒的普通群消息。

守卫在 LLM 请求前读取当前群策略，并以本轮临时上下文告知模型：番剧事实必须使用
`anime_readonly`，Tool 无结果或失败时不得改用模型知识猜测。临时上下文不写入长期会话
历史，避免把某群策略带到其他会话。

守卫按平台消息 ID 记录本轮状态：

- 是否属于受控群 `@` 轮次；
- 当前群是否允许通用聊天；
- 是否调用过 `anime_readonly`；
- Tool 是否成功、无结果或失败。

Tool 调用完成后更新状态；Agent 完成时读取并清理状态。记录必须并发隔离并有超时清理，
不能让两个群或两个同时到达的消息互相继承 Tool 状态。

### 5.3 每群通用聊天策略

扩展现有 `GroupRuntimeSetting` 和 `GroupRuntimePolicy`：

```text
general_chat_enabled: bool = false
```

数据库迁移使用非空布尔列和数据库默认 `false`。新群、没有 setting 行的群及全部既有群在
升级后均为关闭，不发生隐式开放。

当开关关闭：

- Tool 成功：允许 MiniMax 根据真实结果回答；
- Tool 返回无结果：允许回答“项目数据暂未查到”，不得声称作品不存在；
- Tool 参数错误或内部失败：替换为固定失败说明并引导 `/番剧`；
- 本轮完全没有调用 Tool：替换模型自由回答为固定番剧帮助。

固定帮助文本提供“今天有什么番、某番下一集、搜索某番、资源详情、我的订阅”等例子，并
说明当前群只开放番剧助手。

当开关开启：

- 番剧事实仍要求使用 Tool；
- 未调用 Tool 的非番剧问题保留 AstrBot 原生 MiniMax 回答；
- 会话、人格和上下文继续由 AstrBot 管理；
- 不增加一次前置分类调用，因此普通聊天每轮只走原生 Agent 流程。

## 6. 管理与权限

“番剧放送控制台”的群列表增加“通用聊天”列和切换操作。该操作继续走现有
`groups/<group_id>/update`、Dashboard 鉴权、`admin_page_writes_enabled` 总开关、乐观版本号
和审计事件。

机器人管理者是唯一配置者。QQ 群主、QQ 群管理员和普通成员不能通过群消息修改开关。
首版不增加 QQ 管理命令，也不从 QQ 角色推导 Dashboard 权限。

管理 API 只接受白名单内的 `general_chat_enabled` 布尔变更。缺少 `expected_version`、类型
错误或版本冲突时拒绝写入，不覆盖较新的群策略。

## 7. 数据流

### 7.1 番剧事实问题

1. 用户在群内发送 `@机器人 胆大党下一集什么时候`；
2. AstrBot 创建原生 Agent 轮次；
3. 策略守卫读取当前群策略并附加临时规则；
4. MiniMax 调用 `anime_readonly(action="next", query="胆大党")`；
5. Tool 从事件取得真实群和用户身份，构造 `IntentKind.NEXT`；
6. Anime Core 读取 PostgreSQL 投影；
7. Tool 返回结构化、来源标注且长度受控的结果；
8. MiniMax 组织自然语言回答；
9. 策略守卫确认本轮使用了 Tool，允许发送并清理状态。

### 7.2 多候选

1. Tool 搜索产生多个候选并按当前群和用户保存 `InteractionSession`；
2. MiniMax 向用户展示编号和标题，不展示 UUID；
3. 用户下一轮发送 `@机器人 第二个`；
4. MiniMax 使用候选编号调用 Tool；
5. Tool 只解析同群、同用户、未过期的候选并执行详情或下一集查询。

### 7.3 非番剧问题

通用聊天关闭时，模型没有调用 Tool，最终回答在发送前被替换为固定帮助。通用聊天开启
时，最终回答原样保留。该判定由代码执行，不依赖 MiniMax 自律分类。

### 7.4 固定命令

`/番剧 今天` 等命令继续由插件命令组直接分发到现有 use case。它们不注册为 Agent 轮次，
不读取通用聊天开关，不调用 MiniMax，也不受 LLM 策略守卫影响。

## 8. 错误与降级

- MiniMax 超时、402、限流或模型不可用时不做应用层密集重试；提示智能问答暂不可用并
  引导固定命令；
- Tool 查询异常返回 `unavailable`，不把异常、SQL、Token、连接串或堆栈交给模型；
- 数据库无结果返回 `not_found`，不得退回模型知识补全实时事实；
- action、日期、季度、集数或候选编号不合法时返回 `invalid_request` 和可操作帮助；
- Tool 结果过长时确定性截断并设置 `truncated=true`；
- LLM 策略状态在 Agent 完成后清理，异常路径由 TTL 回收；
- Tool 注册、策略查询或 Guard 自身异常不得阻断 `/番剧` 固定命令、通知消费或 Worker；
- 日志记录 action、群内部 ID、状态、耗时和截断标记，不记录模型 Key、完整 QQ 号或敏感
  订阅内容。

## 9. 测试与验收

### 9.1 自动化测试

- Tool Schema 只包含八个只读 action 和业务参数；
- Schema 不包含写操作、群号、用户 ID、SQL 或 URL；
- 八个 action 正确映射现有 Intent/use case；
- Tool 永远使用事件中的平台、群和用户身份；
- 多候选编号只能在同群、同用户和有效期内解析；
- Tool 成功、无结果、参数错误、内部错误和截断分别返回稳定 DTO；
- 数据库迁移将新列设置为非空且默认关闭；
- 没有 setting 行时 `general_chat_enabled` 仍为 `false`；
- 管理 API 只允许管理员页面白名单更新并保留版本冲突；
- 通用聊天关闭且未调用 Tool 时，最终模型回答一定被替换；
- 通用聊天开启且未调用 Tool 时，最终模型回答保持不变；
- Tool 无结果或失败时不能通过模型自由回答绕过；
- 两条并发消息的 Guard 状态不串线并能清理；
- 固定命令不调用 LLM，现有命令、通知和管理测试继续通过；
- AstrBot 4.26.7 镜像可导入 Tool 和钩子实现；
- 自动化测试使用 Fake Context/Provider，不请求真实 MiniMax，不消耗 Token Plan 额度。

### 9.2 真实测试群 canary

1. 部署后确认所有群“通用聊天”为关闭；
2. 确认 `interaction_gateway_enabled=false`；
3. 发送 `/番剧 今天`，确认现有卡片正常；
4. 分别验证八类自然语言只读查询；
5. 验证多候选后用编号继续查询；
6. 验证非番剧问题被固定帮助拦截；
7. 只为测试群在管理页打开“通用聊天”；
8. 验证普通对话、人格和上下文继续工作；
9. 验证自然语言订阅请求不会产生数据库写入；
10. 检查 AstrBot、Worker、NapCat 健康、MiniMax 调用量和日志脱敏。

自动化通过、容器健康和真实 QQ 验收分别记录。前两者不能替代 QQ 客户端中的真实消息与
权限验收。

## 10. 发布与回退

代码、迁移、插件 Tool、管理页和文档随现有 ACR 单镜像发布。部署前不在生产群打开通用
聊天；迁移默认关闭保证升级安全。

回退优先通过管理页关闭所有群的通用聊天并在 AstrBot Tool 管理中禁用
`anime_readonly`。固定命令和通知不依赖 Tool，可以继续运行。需要回退应用镜像时沿用现有
ACR 部署回滚流程；数据库新增的默认关闭布尔列可以由旧代码忽略，不要求破坏性降级。

## 11. 后续范围

以下能力不进入首版：

- 自然语言订阅、退订和筛选确认状态机；
- Tool 直接发送图片卡片并抑制 Agent 二次回复；
- 私聊独立策略；
- 对模型回答做事实引用或逐字段来源展示；
- 为不同群选择不同模型、人格或 Tool 集；
- Tool 调用成本、质量和命中率的长期分析面板。

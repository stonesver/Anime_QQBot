# QQ 富消息生产兼容修复设计

日期：2026-07-17

## 1. 背景

自适应 QQ 消息呈现上线后，生产环境暴露出两个平台集成问题：

- Markdown 中直接引用 `lain.bgm.tv` 封面时，消息接口返回成功，但客户端无法加载图片。QQ 开放平台的消息 URL 配置要求域名备案并完成所有权验证，无法为第三方 Bangumi 域名完成配置。
- 点击分页或视图切换按钮后，交互确认接口返回成功，但后续群消息接口返回 HTTP 400。真实 `INTERACTION_CREATE` 事件的 `d.id` 被同时映射为 `message_id`，导致回复错误地携带 `msg_id`，而不是交互事件需要的 `event_id`。

现有 QQ 网关只保留错误码，未记录平台返回的错误说明，命令处理器也不记录最终投递失败，增加了生产诊断成本。

## 2. 目标与非目标

### 2.1 目标

- 使用自有域名向 QQ 提供可验证、可公网抓取的封面 URL。
- 正确区分消息事件 ID 与交互事件 ID，使按钮结果能够作为交互事件的被动消息发送。
- 安全记录 QQ 失败响应的路径、HTTP 状态、平台错误码和错误说明。
- 对代理入口实施来源约束、类型约束和大小约束，避免成为任意 URL 代理。
- 为真实生产事件结构和代理安全边界补充自动化回归测试。

### 2.2 非目标

- 不引入对象存储、CDN、图片数据库或持久化文件缓存。
- 不改变 20/50 条展示阈值、分页大小或现有按钮文案。
- 不把每张封面改为独立 QQ 富媒体消息，避免放大消息数量和触发频控。
- 不代理数据库中未记录的任意 URL，不接受用户提供的上游 URL。

## 3. 设计决策

### 3.1 自有域名封面代理

Bot HTTP 服务新增只读路由：

```text
GET /qqbot/media/covers/{subject_id}
```

路由按 `subject_id` 从现有目录查询番剧详情，只使用数据库中已有的 `image_url`。上游 URL 必须满足：

- HTTPS；
- 主机名为 `lain.bgm.tv`；
- 响应类型为 `image/jpeg` 或 `image/png`；
- 响应正文不超过 5 MiB；
- 不跟随跳转到非白名单主机。

成功响应透传图片二进制与媒体类型，并设置公共缓存响应头。不存在的番剧或封面返回 404；非法来源或上游失败返回 502；超出大小返回 413。响应不暴露上游 URL 或内部异常详情。

新增可选配置 `QQ_IMAGE_PROXY_BASE_URL`。生产配置为：

```text
https://animebot.stonebg.cn/qqbot/media/covers
```

配置存在时，展示层按 `{base_url}/{subject_id}` 生成 Markdown 图片地址；未配置时保留原始图片 URL，便于本地测试和兼容已有部署。配置只允许 HTTPS，且不得包含查询参数或片段。

QQ 开放平台的“消息 URL 配置”使用自有地址前缀 `animebot.stonebg.cn/qqbot/media`，由部署方完成域名验证。

### 3.2 交互事件引用

事件映射只为 `GROUP_AT_MESSAGE_CREATE` 和 `C2C_MESSAGE_CREATE` 设置 `message_id`。`INTERACTION_CREATE` 的 `d.id` 只作为 `event_id`。

回复时保持现有优先级：

```text
有 message_id → 使用 msg_id
无 message_id → 使用 event_id
```

因此普通消息仍使用 `msg_id` 被动回复，按钮交互使用官方支持的 `event_id` 被动回复。交互确认 PUT 与消息回复 POST 都保留；PUT 仅结束客户端加载状态，不替代结果消息。

### 3.3 可观测性

QQ API 非成功响应记录结构化警告，字段包括：

- `event=qq_api_request_failed`
- 请求方法与路径
- HTTP 状态码
- QQ `code`
- QQ `message`

日志不记录 Authorization、AppSecret、Access Token、消息正文、Markdown 或用户标识。命令处理器在最终投递结果不是 `SENT` 时记录结果类型和错误码，避免静默失败。

## 4. 数据流

### 4.1 图片

```text
渲染器取得 subject_id
  → 生成自有域名封面 URL
  → QQ 开放平台抓取自有 URL
  → Bot 按 subject_id 查询可信上游
  → 校验来源、响应类型和大小
  → 返回图片并由 QQ 转存
```

### 4.2 按钮

```text
收到 INTERACTION_CREATE(d.id)
  → 映射为 event_id，message_id=None
  → PUT /interactions/{event_id} 确认交互
  → 解析 button_data 并重新查询
  → POST /v2/groups/{group}/messages，携带 event_id
```

## 5. 测试设计

- 官方真实交互结构中的 `d.id` 不得进入 `message_id`。
- 按钮 ACK 成功后，结果消息必须携带 `event_id`，不得携带 `msg_id`。
- 普通群消息仍携带原消息 `msg_id`。
- QQ 失败响应日志包含状态、平台码、错误说明和路径，不包含凭证或消息正文。
- 配置的代理基地址被规范化；HTTP、查询参数和片段被拒绝。
- 渲染器在配置代理时生成自有域名 URL，未配置时保留原 URL。
- 封面代理覆盖成功、条目不存在、无封面、非法主机、非法媒体类型、上游失败与超限响应。
- 完整单元、合同、端到端、类型和静态检查继续通过。

## 6. 部署与验收

1. 设置 `QQ_IMAGE_PROXY_BASE_URL=https://animebot.stonebg.cn/qqbot/media/covers`。
2. 确保反向代理将 `/qqbot/media/` 转发到 Bot 的 8080 端口。
3. 在 QQ 开放平台配置并验证 `animebot.stonebg.cn/qqbot/media`。
4. 访问一个真实封面代理 URL，确认返回 200 和 `image/jpeg` 或 `image/png`。
5. 在 QQ 群执行“今日番剧”，确认封面显示。
6. 点击“下一页”和“切换精简列表”，确认出现新消息且内容变化。
7. 检查日志中不再出现按钮后的 POST 400；若仍失败，确认新的安全错误日志包含 QQ 错误码和说明。

## 7. 完成标准

- 图片 URL 使用可验证的自有域名且代理安全边界生效。
- 按钮交互结果使用 `event_id` 成功发送。
- QQ 平台失败不再静默且日志不泄露敏感内容。
- 自动化质量门禁全部通过。
- 生产部署文档包含平台 URL 配置和反向代理要求。

# NapCat QQ 会话可观测性设计

## 状态

- 日期：2026-07-29
- 状态：已实施，等待生产环境验收
- 运行基线：AstrBot `v4.26.7`、NapCat `v4.18.13`
- 上位约束：日常应用发布不协调 NapCat；检测到 QQ 离线后不自动重启或登录

## 背景

NapCat WebUI 端口存活只能说明进程仍在运行，不能证明 QQ 会话在线。生产中已经出现
NapCat 容器保持 healthy、QQ 被强制下线、后续 WebUI 又报告“当前账号已登录”的假健康
状态。SSH 隧道断开与 QQ 会话失效没有因果关系，但当前管理面板无法直接区分这些状态。

## 目标

- 通过 NapCat 的 OneBot `get_status` 主动判断 QQ 会话是否在线；
- 将容器/接口可达性与 QQ 在线状态分开呈现；
- 在 AstrBot 插件管理页顶部突出显示 NapCat/QQ 状态；
- 跨 AstrBot 重启保留当前状态、离线开始时间和最近 20 条状态变化；
- 只提供人工恢复引导，不授予面板 Docker 或 QQ 登录控制能力；
- 不泄露 QQ 号、OneBot Token、WebUI Token、服务器地址或原始接口响应。

## 架构与数据流

NapCat 增加一个仅 Compose 内网可达的 OneBot HTTP Server，监听容器端口 `3000`，
使用现有 `ONEBOT_TOKEN` 鉴权。Compose 不为该端口声明宿主机 `ports`。

AstrBot 插件生命周期启动独立的 `NapCatStatusMonitor`：

1. 每 60 秒以短超时调用 `http://napcat:3000/get_status`；
2. QQ 明确离线时立即标记 `qq_offline`；
3. 接口连续 3 次不可达时标记 `unreachable`；
4. 任意一次成功且 QQ 在线后立即恢复为 `online`；
5. 只在状态发生变化时写 INFO 日志，单次失败不持续刷屏；
6. 将安全、归一化后的观测结果写入 PostgreSQL。

监测任务与查询、订阅、通知分发解耦。监测失败不得中止 AstrBot、Worker 或 Outbox。

## 状态语义

| 状态 | 面板颜色 | 语义 |
|---|---|---|
| `unknown` | 灰色 | 尚未完成首次有效判断 |
| `online` | 绿色 | `get_status` 成功且 QQ 在线 |
| `qq_offline` | 红色 | NapCat API 可达，但 QQ 会话明确离线 |
| `unreachable` | 黄色 | NapCat API 连续 3 次不可达或返回无效结果 |

`qq_offline` 一次确认即生效。`unreachable` 使用连续失败阈值避免短暂启动或网络抖动
误报。恢复只需一次在线观测。

Docker healthcheck 继续只判断 NapCat WebUI/进程是否存活，不改为 QQ 在线探针。这样
首次部署等待扫码或人工恢复时不会导致 Compose 发布失败，也不会触发任何自动重启。

## 持久化

新增两个派生运行状态表：

- `runtime_component_states`：以组件名为主键，保存当前状态、连续失败数、状态变更时间、
  最近观测时间和离线开始时间；
- `runtime_component_events`：保存状态转移、发生时间和安全摘要。

组件名固定为 `napcat`。事件写入后只保留最近 20 条；摘要只允许内部固定枚举，不保存
异常堆栈、URL、Token、QQ 标识或原始响应。

## 管理面板

总览页顶部增加状态横幅和 NapCat 状态卡，展示：

- 当前中文状态；
- 最近检测时间；
- 当前状态开始时间；
- QQ 离线开始时间；
- 最近 20 条状态变化。

QQ 离线时展示人工恢复步骤：

```bash
docker compose restart napcat
```

随后通过 SSH 隧道打开 NapCat WebUI 并完成扫码或设备验证。面板不提供一键重启、
退出 QQ、自动登录或修改 OneBot 配置的按钮，也不挂载 Docker Socket。

面板每 30 秒自动刷新一次总览；用户切换到其他页面时不刷新隐藏视图。

## 安全边界

- OneBot HTTP Server 虽监听容器网络地址，但不映射宿主机端口；
- HTTP 和现有反向 WebSocket 共用随机 `ONEBOT_TOKEN`；
- Monitor 日志、数据库 DTO 和管理 API 均不输出 Token 或原始正文；
- 管理 API 继续复用 AstrBot Dashboard 身份验证；
- 不修改 Nginx，不开放 AstrBot、NapCat WebUI 或 OneBot 端口到公网；
- 不触碰 `napcat-qq`、`napcat-config`、`astrbot-data` 或 `postgres-data` 卷内容。

## 验收

1. NapCat 默认配置同时包含反向 WebSocket Client 和带 Token 的 HTTP Server；
2. HTTP Server 端口没有宿主机映射；
3. 在线、明确离线、单次失败、连续三次失败和恢复的状态机均有自动化测试；
4. 当前状态与最近 20 条事件可跨 Monitor 重建读取；
5. Admin API 只返回安全 DTO；
6. 面板正确展示四种状态、时间和人工恢复引导，并每 30 秒刷新总览；
7. 日常发布仍不协调 NapCat，现有发布隔离验收继续通过；
8. Ruff、mypy、全量 pytest、迁移往返和 Compose 配置通过；
9. 真实服务器调用 `get_status` 与 QQ 群回复属于发布后的 external gate。

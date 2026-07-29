# NapCat QQ 会话可观测性实施计划

- 日期：2026-07-29
- 状态：已实施，等待生产环境验收
- 对应规格：[NapCat QQ 会话可观测性设计](../specs/2026-07-29-napcat-session-observability-design.md)

## 完成定义

1. NapCat 提供仅 Compose 内网可达、带 Token 的 OneBot HTTP Server；
2. AstrBot 每 60 秒探测一次 `get_status`；
3. 状态机满足明确离线立即标红、接口连续三次失败标黄、一次在线立即恢复；
4. PostgreSQL 保存当前状态和最近 20 条状态变化；
5. 管理面板顶部显示状态横幅、时间、历史和人工恢复步骤；
6. 不新增自动重启、自动登录、外部通知、公网端口或 Docker Socket；
7. 自动化检查通过并推送 `main`。

## 实施分片

### 分片一：网络与状态契约

- 修改 `scripts/napcat-entrypoint.sh`，生成带 Token 的 HTTP Server；
- 修改 Compose，为 AstrBot 注入内部 endpoint 与 Token，不开放宿主机端口；
- 新增状态枚举、观测结果和状态机单元测试。

### 分片二：持久化与 Monitor

- 新增 Alembic migration；
- 新增运行组件状态 ORM 与 repository；
- 新增 `NapCatStatusMonitor` 和 HTTP 探针；
- 接入 `PluginLifecycle` 的启动与优雅停止。

### 分片三：管理 API 与页面

- 扩展 `AdminService.overview()` 安全 DTO；
- 在总览页加入状态横幅、恢复引导和最近状态变化；
- 增加 30 秒总览自动刷新；
- 补充 API、页面和安全边界测试。

### 分片四：验证与发布

- 运行 Ruff、mypy、全量 pytest、迁移往返和 Compose 配置；
- 检查 `git diff --check` 与暂存范围；
- 保持用户未跟踪的 `dist/` 不变；
- 提交并推送 `main`；
- 给出 ACR 构建后的服务器更新和人工恢复命令。

# NapCat 发布隔离与 QQ 小号风险控制设计

## 状态

- 日期：2026-07-29
- 状态：已确认并进入实施
- 上位约束：NapCat 独立升级；QQ 登录卷不参与应用发布或应用回滚

## 目标

降低普通应用发布对 QQ 登录会话的扰动，并为每次发布留下 NapCat 是否重启的直接证据。
这不能消除非官方接入的 QQ 风控风险，但可以避免项目自身制造不必要的重新登录。

## 发布接口

日常应用发布继续使用：

```bash
./scripts/deploy-acr.sh
```

该入口只更新应用镜像、运行 migration 并协调 Worker/AstrBot。已经存在的 PostgreSQL
和 NapCat vendor 镜像不刷新；运行中的 NapCat 不协调，已停止的 NapCat也不自动
唤醒。

首次部署缺少 vendor 镜像时，脚本只补拉缺失的具体镜像。需要有意识地更新固定
PostgreSQL 或 NapCat 镜像时，使用：

```bash
./scripts/deploy-acr.sh --refresh-vendors
```

显式刷新仍保留 NapCat 的启停意图：运行中的实例会协调到新镜像，已停止的实例只拉取
镜像、不自动启动。

## 失败语义

- 应用拉取、migration 或应用健康失败时，恢复应用镜像引用；
- 应用回滚只重建 Worker 和 AstrBot；
- NapCat 不参与应用回滚；
- 首次部署需要启动 NapCat，但失败不能通过反复自动登录来掩盖；
- 脚本不删除、替换或迁移 `napcat-qq` 与 `napcat-config` 卷。

## 发布证据

脚本在发布前后记录 NapCat 容器 ID 与 `StartedAt`，并明确输出：

```text
NapCat restart detected: no|yes
```

输出不得包含 QQ 号、WebUI Token、OneBot Token 或登录数据。

## ACR 边界

- 应用 `latest` 规则可由 `main` 代码变化自动触发；
- vendor PostgreSQL/NapCat 规则改为人工触发；
- vendor 版本变化必须走 `--refresh-vendors` 维护窗口；
- ACR 控制台规则调整属于部署者操作，仓库只记录要求和验证步骤。

## 验收

- 首次部署补拉两个缺失 vendor 镜像并启动 NapCat；
- 日常升级不拉 vendor、不执行 NapCat `up`；
- 已停止的 NapCat 在日常升级后仍停止；
- 缺少 PostgreSQL 镜像不会顺带拉取 NapCat；
- 显式 vendor 刷新会拉取 vendor，并只协调原本运行的 NapCat；
- 应用失败回滚命令不包含 NapCat；
- 发布前后 NapCat 指纹和重启判断可见。

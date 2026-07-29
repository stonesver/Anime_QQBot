# NapCat 4.17.50 生产降级设计

## 目标

将生产 NapCat 从 `4.18.13` 降至低于 `4.17.52` 且具有官方
Linux/amd64 Docker 镜像的最高版本 `4.17.50`，用于观察 QQ 会话掉线和
`NodeIKernelMsgService/sendMsg` 超时是否减少。

## 范围

- 暂停 QQ 群 `1091724800` 的主动通知；
- 构建并推送 ACR 标签 `vendor-napcat-v4.17.50`；
- 仅重建生产 NapCat 容器，保留 PostgreSQL、Worker 和 AstrBot；
- 复用现有 `napcat-qq` 与 `napcat-config` 卷；
- 验证 NapCat 版本、容器健康、QQ 登录和 OneBot 连接；
- 验证完成后仍保持主动通知暂停，另行确认恢复。

## 明确排除

- 不备份或复制 NapCat 持久卷；
- 不修改通知重试和不确定结果处理逻辑；
- 不清理现有 QQ 登录数据；
- 不升级或重建 PostgreSQL、Worker、AstrBot；
- 不自动恢复主动通知。

## 发布方式

`Dockerfile.napcat` 基于官方 `mlikiowa/napcat-docker:v4.17.50` 构建
Linux/amd64 镜像，并推送至现有 ACR 仓库。生产 `.env` 的
`NAPCAT_IMAGE` 指向新标签后，仅拉取并重建 NapCat 服务。

## 验证

1. 容器日志报告 `NapCat.Core Version: 4.17.50`；
2. NapCat 容器通过健康检查且无重启循环；
3. QQ 会话能够快速登录或只进行一次人工验证；
4. OneBot 反向 WebSocket 恢复；
5. 群内被动查询能够正常返回；
6. 主动通知保持关闭，不发送额外测试通知。

## 回退

若 `4.17.50` 无法启动、无法读取现有配置或无法连接 OneBot，将
`NAPCAT_IMAGE` 改回已存在的 `vendor-napcat-v4.18.13` 并只重建 NapCat。
由于按要求不备份持久卷，回退仅依赖现有卷可继续被 `4.18.13` 读取。

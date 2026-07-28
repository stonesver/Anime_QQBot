# v0.2.0 单镜像 ACR 部署设计

日期：2026-07-28  
状态：已实施；NapCat 生命周期部分由
[NapCat 发布隔离与 QQ 小号风险控制设计](2026-07-29-napcat-release-isolation-design.md)
补充

## 1. 目标

把 v0.2.0 的服务器部署方式从“服务器现场构建 Worker 与 AstrBot 两个自建镜像”
改为“ACR 构建并分发一个合并运行镜像”。服务器只拉取镜像、执行数据库迁移并
启动服务，不 clone 完整开发仓库，也不运行 `docker build`。

该设计必须：

- 继续使用现有 ACR 仓库 `stonesver/anime-qqbot`；
- 支持 AstrBot、Worker、migration 和两个数据源映射命令；
- 保留 PostgreSQL 数据、部署前备份、应用镜像回滚和部署互斥锁；
- 不修改现有 Nginx、OurNotes 静态发布目录或 OurNotes 定时 Worker；
- 适配当前 2 核 2 GiB、4 GiB Swap 的服务器；
- 不恢复 QQ 官方机器人运行时。

## 2. 非目标

- 不把 PostgreSQL、NapCat 重新打包进自建镜像；
- 不在本轮引入 GitHub Actions、Kubernetes 或 ACR 企业版专属能力；
- 不自动恢复数据库备份；
- 不开放 AstrBot/NapCat WebUI 到公网；
- 不删除旧数据库卷、OurNotes 镜像或其他 Docker 资源；
- 不自动操作阿里云 ACR 控制台。

## 3. 镜像与运行角色

唯一的自建镜像为：

```text
crpi-thkewd16qu1tdfsq.cn-shenzhen.personal.cr.aliyuncs.com/stonesver/anime-qqbot:latest
```

根目录 `Dockerfile` 基于固定版本的 AstrBot 镜像构建，并安装 Anime Core、数据库
migration、AstrBot 插件及统一运行入口。一个镜像支持：

| 角色 | 责任 |
|---|---|
| `astrbot` | 群命令、订阅操作、Outbox 通知发送 |
| `worker` | Bangumi/AniList 同步、Mikan 轮询、通知规划 |
| `migrate` | Alembic migration 到 head |
| `map-mikan` | 运维人员确认 Mikan 映射 |
| `map-anilist` | 运维人员确认 AniList 映射 |

NapCat 使用固定版本 `mlikiowa/napcat-docker:v4.18.13`；PostgreSQL 使用固定版本
`postgres:17.4-alpine`。

### 3.1 统一入口

镜像入口按第一个参数分发角色：

```text
astrbot
worker
migrate
map-mikan
map-anilist
```

`astrbot` 角色在启动 AstrBot 前，把镜像内的版本化插件副本同步到
`/AstrBot/data/plugins/astrbot_plugin_anime_tracking`。这样 `/AstrBot/data`
持久化卷不会遮蔽镜像内插件，也不再需要服务器本地插件源码 bind mount。镜像版本是
插件版本的唯一发布来源，容器重启时会恢复与镜像一致的插件内容。

其他角色直接进入 Anime Core CLI，不启动 AstrBot。

## 4. Compose 拓扑

Compose 保留五个运行单元：

```text
postgres
  └─ migrate (one-shot)
       ├─ worker
       └─ astrbot
            └─ napcat
```

`migrate`、`worker`、`astrbot` 使用同一 ACR 镜像，只通过命令区分角色。
Compose 中不得保留 `Dockerfile.astrbot` 的独立构建路径或插件源码 bind mount。

网络边界保持：

- PostgreSQL 仅 Compose 内网；
- Worker 健康检查端口 8081 仅 Compose 内网；
- AstrBot WebUI 6185 仅绑定宿主机 `127.0.0.1`；
- OneBot 6199 仅 Compose 内网；
- NapCat WebUI 6099 仅绑定宿主机 `127.0.0.1`；
- 不新增 Nginx location 或云安全组公网端口。

## 5. ACR 构建

现有 ACR 仓库继续绑定 GitHub 仓库。构建规则为：

| 配置项 | 值 |
|---|---|
| 类型 | Branch |
| 分支 | `main` |
| 构建上下文 | `/` |
| Dockerfile | `Dockerfile` |
| 目标架构 | `linux/amd64` |
| 镜像版本 | `latest` |
| 自动构建 | main 更新时触发 |

ACR 控制台允许操作人员立即构建和查看日志。部署前必须确认构建成功。部署脚本记录
实际拉取的镜像 ID/digest，不能只把可变的 `latest` 当作审计标识。

参考：

- [阿里云 ACR 构建规则](https://help.aliyun.com/zh/acr/use-cases/build-an-image-for-a-java-application-by-using-a-dockerfile-with-multi-stage-builds)
- [阿里云 ACR 镜像构建故障排查](https://help.aliyun.com/zh/acr/support/troubleshoot-issues-for-failure-to-create-images-in-container-registry)

## 6. 服务器最小部署包

服务器目录固定为：

```text
/opt/anime-qqbot/
├── compose.yaml
├── compose.server-2g.yaml
├── .env
└── scripts/
    ├── deploy-acr.sh
    ├── napcat-entrypoint.sh
    ├── backup-postgres.sh
    └── restore-postgres.sh
```

仓库提供一个本地打包脚本，产出不含秘密的部署包。部署包不得包含：

- `.env`；
- Git 历史；
- `src/`、测试或设计文档；
- 数据库备份；
- QQ 登录数据；
- ACR 凭证。

首次上传后，日常发布只运行服务器上的 `scripts/deploy-acr.sh`。部署资产有变更时再
上传新部署包。

## 7. 环境配置

`.env` 至少包含：

```dotenv
APP_IMAGE=crpi-thkewd16qu1tdfsq.cn-shenzhen.personal.cr.aliyuncs.com/stonesver/anime-qqbot
IMAGE_TAG=latest
POSTGRES_PASSWORD=<沿用现有数据库角色密码>
ONEBOT_TOKEN=<至少24位URL安全随机字符>
BANGUMI_USER_AGENT=<包含可联系信息的User-Agent>
COMPOSE_FILE=compose.yaml:compose.server-2g.yaml
```

`POSTGRES_PASSWORD` 必须沿用现有 `anime-qqbot_postgres-data` 数据卷的数据库角色
密码；改变容器环境变量不会自动修改已初始化 PostgreSQL 中的密码。

ACR 密码不写入 `.env`。首次部署或凭证过期后由操作人员执行：

```bash
sudo docker login \
  crpi-thkewd16qu1tdfsq.cn-shenzhen.personal.cr.aliyuncs.com
```

## 8. 2 GiB 服务器资源策略

服务器覆盖文件设置：

| 服务 | 内存上限 | 内存软预留 | CPU 上限 |
|---|---:|---:|---:|
| postgres | 192 MiB | 64 MiB | 0.50 |
| migrate | 256 MiB | 无 | 0.50 |
| worker | 192 MiB | 64 MiB | 0.50 |
| astrbot | 512 MiB | 256 MiB | 0.80 |
| napcat | 512 MiB | 256 MiB | 0.80 |

资源限制不代表实际常驻占用。已测未登录 QQ 时四个常驻容器合计约 530 MiB；QQ 登录、
插件加载和上游同步会产生额外峰值。保留 4 GiB Swap，不对 Nginx 或 OurNotes 服务
应用本项目限制。

若出现以下任一情况，应停止扩展插件并评估升级到 4 GiB 内存：

- `MemAvailable` 长期低于 250 MiB；
- Swap 使用持续增长到 1 GiB 以上；
- `vmstat` 的 `si/so` 持续非零；
- AstrBot 或 NapCat 出现 OOM/restart；
- 双核负载长期高于 2。

## 9. 部署流程

`scripts/deploy-acr.sh` 的正常路径：

1. 校验 Docker Compose v2、`.env`、Compose 合并结果和必要脚本；
2. 解析 `APP_IMAGE`、`IMAGE_TAG`，拒绝空值和占位符；
3. 获取部署互斥锁；
4. 如果 PostgreSQL 正在运行且未指定跳过备份，创建压缩备份；
5. 如果存在当前 Worker/AstrBot，保存其镜像 ID为 `anime-qqbot:rollback`；
6. 拉取 ACR 应用镜像；
7. 只补拉本机缺失的固定 PostgreSQL/NapCat 镜像；显式维护窗口才刷新 vendor；
8. 启动 PostgreSQL并等待健康；
9. 独立执行 migration，要求退出码 0；
10. 用 `--no-build --pull never` 启动 Worker/AstrBot并等待健康；
11. 首次部署启动 NapCat；日常发布保留其运行或停止状态；
12. 输出应用镜像 ID/digest、备份位置、NapCat 前后指纹、Compose 状态和 WebUI
    SSH 隧道提示。

部署脚本不得执行 `docker build`、`docker image prune`、`docker system prune` 或
`docker volume prune`。

## 10. 失败与回滚

| 失败点 | 行为 |
|---|---|
| 配置无效 | 在修改运行状态前退出 |
| ACR 未登录/拉取失败 | 保持现有服务与镜像不变 |
| PostgreSQL不健康 | 停止发布 |
| migration 失败 | 停止发布，不自动恢复数据库 |
| Worker/AstrBot 不健康 | 把 rollback 镜像重新标记为应用引用并重建 Worker/AstrBot |
| NapCat 不健康 | 保留独立状态并人工处理，不参加应用镜像回滚 |
| 首次部署失败 | 明确报告没有可用应用回滚镜像 |
| 信号中断 | 若已进入替换阶段则尝试应用镜像回滚 |

数据库备份和应用回滚是两个独立机制。自动恢复数据库可能覆盖部署期间写入的数据，
因此始终需要操作人员选择明确备份后手动执行。

## 11. 测试策略

以可观察行为为测试边界：

1. Compose 解析后，migrate/worker/astrbot 使用同一应用镜像；
2. Compose 不包含独立 AstrBot 自建镜像或插件源码 bind mount；
3. 合并镜像可执行 `migrate`、`worker` 和默认 `astrbot` 角色；
4. AstrBot 角色会把内置插件同步到空数据卷及已有数据卷；
5. 部署脚本正常升级时备份、拉取、迁移并按顺序启动；
6. 首次部署没有运行镜像时不伪造 rollback；
7. 跳过备份只跳过备份，不跳过 migration；
8. 拉取失败不会重建服务；
9. migration 失败不会启动新应用；
10. 应用健康失败恢复旧镜像并只重建 Worker/AstrBot；
11. 日常升级不拉取 vendor、不协调 NapCat，显式刷新除外；
12. 已停止的 NapCat 在应用发布后仍保持停止；
13. 输出 NapCat 发布前后指纹和重启判断；
14. 部署包只包含白名单资产且不包含秘密；
15. 2 GiB 覆盖配置被 Compose 正确合并。

最终门禁：

- Ruff format/check；
- mypy；
- 全量 pytest；
- migration 往返；
- `docker compose config --quiet`；
- Shell 语法检查；
- 合并镜像构建与插件导入；
- 隔离五单元启动；
- 服务器真实部署后的内存、Swap、日志和测试群 canary。

## 12. 人工操作边界

以下步骤由操作人员完成：

- 在 ACR 控制台确认或修正 `main` 构建规则；
- 查看 ACR 构建成功状态；
- 输入 ACR 登录凭证；
- 保存生产 `.env`；
- 通过 SSH 隧道进入 AstrBot/NapCat WebUI；
- 扫码登录 QQ 小号；
- 在测试群执行真实 canary；
- 必要时选择数据库备份进行人工恢复。

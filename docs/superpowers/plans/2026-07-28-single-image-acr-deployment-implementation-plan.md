# v0.2.0 单镜像 ACR 部署实施计划

日期：2026-07-28  
对应设计：[`2026-07-28-single-image-acr-deployment-design.md`](../specs/2026-07-28-single-image-acr-deployment-design.md)

## 1. 实施纪律

1. 每个行为按一个失败测试到最小实现的垂直切片推进。
2. 测试只通过公开运行接口观察行为：Compose 展开结果、镜像入口退出结果、部署脚本
   记录的 Docker 命令和部署包内容。
3. 不保留旧双镜像路径作为第二套活动部署接口。
4. 不在服务器构建镜像，不把 ACR 密码或生产 `.env` 写入仓库。
5. 不修改业务数据模型、番剧命令语义或通知领域逻辑。
6. 不操作 Nginx、OurNotes 目录、其他项目镜像或全局 Docker 清理。

## 2. 模块与接口

### 2.1 Runtime Image 模块

接口是镜像的角色参数：

```text
anime-qqbot astrbot
anime-qqbot worker
anime-qqbot migrate
anime-qqbot map-mikan ...
anime-qqbot map-anilist ...
```

实现隐藏 AstrBot 基础镜像、Anime Core 安装、migration 文件布局和持久卷插件同步。
调用方只需要知道角色名。

### 2.2 ACR Deployment 模块

接口是：

```text
scripts/deploy-acr.sh [--no-backup]
```

实现隐藏镜像引用解析、当前镜像快照、拉取、迁移、健康等待、回滚和互斥锁。测试和
操作人员通过相同的 Shell 接口调用。

### 2.3 Deployment Bundle 模块

接口是：

```text
scripts/package-deployment.sh <输出tar.gz>
```

实现隐藏运行资产白名单。输出包是服务器部署目录的唯一输入。

## 3. Task 1：建立 Compose 单镜像契约

**RED**

修改 `tests/acceptance/test_compose_config.py`，要求：

- migrate/worker/astrbot 展开后使用同一 `${APP_IMAGE}:${IMAGE_TAG}`；
- 不再读取 `Dockerfile.astrbot`；
- 不存在插件源码 bind mount；
- ACR 应用镜像允许 `latest`，第三方镜像仍固定版本；
- 角色命令分别为 `migrate`、`worker`、`astrbot`。

运行：

```bash
.venv/bin/python -m pytest tests/acceptance/test_compose_config.py -q
```

必须先失败。

**GREEN**

- 把根 `Dockerfile` 改为合并运行镜像；
- 删除 `Dockerfile.astrbot`；
- Compose 统一应用镜像与角色命令；
- 删除本地插件 bind mount；
- 保持端口、卷和依赖顺序不变。

再次运行定向测试直到通过。

## 4. Task 2：实现统一运行入口和插件同步

**RED**

新增 Shell 接口行为测试，覆盖：

- 默认或 `astrbot` 角色把内置插件同步到数据卷并执行 AstrBot；
- `worker`、`migrate` 和两个映射角色进入 Anime Core CLI；
- 未知角色退出 64；
- 已有旧插件目录被镜像版本完整替换，不留下旧文件。

测试使用临时目录和命令替身，不读取实现内部变量。

**GREEN**

- 用统一入口替换 `scripts/container-entrypoint.sh`；
- Dockerfile 把插件源保存到不会被数据卷遮蔽的只读目录；
- AstrBot 启动前原子替换插件目录；
- Dockerfile 构建阶段验证 Anime Core 和 AstrBot 插件可导入。

运行入口测试及现有插件测试。

## 5. Task 3：实现 2 GiB Compose 覆盖配置

**RED**

新增验收测试，展开 `compose.yaml:compose.server-2g.yaml` 后检查五个服务的内存、
CPU 和 PID 上限。

**GREEN**

新增 `compose.server-2g.yaml`，使用设计确认的资源值。基础 Compose 不包含服务器
专用限制。

运行：

```bash
POSTGRES_PASSWORD=test \
ONEBOT_TOKEN=123456789012345678901234 \
BANGUMI_USER_AGENT='anime-qqbot/test test@example.com' \
docker compose -f compose.yaml -f compose.server-2g.yaml config --quiet
```

## 6. Task 4：实现 ACR 拉取部署

### 6.1 正常首次部署

**RED**

把 `tests/acceptance/test_operations_assets.py` 改为要求 `deploy-acr.sh`：

- 接受 `--no-backup`；
- 拉取 `${APP_IMAGE}:${IMAGE_TAG}`；
- 不执行 `docker build`；
- 启动 PostgreSQL、运行 migration，再启动 Worker/AstrBot/NapCat；
- 首次没有运行镜像时仍能部署。

**GREEN**

实现最小正常路径。

### 6.2 升级备份与镜像快照

**RED**

用假的 `docker` 可执行文件运行真实脚本，断言已有 PostgreSQL 和应用容器时：

- 先运行数据库备份；
- 获取当前应用镜像 ID；
- 标记为 `anime-qqbot:rollback`；
- 然后才拉取新镜像。

**GREEN**

增加备份、镜像快照和调用顺序。

### 6.3 失败回滚

逐个 RED→GREEN：

- 应用拉取失败时不运行 Compose recreate；
- migration 失败时不启动应用；
- Worker/AstrBot/NapCat 健康失败时恢复 rollback 标签；
- 首次部署失败时报告无可用 rollback；
- 中断时只在替换阶段尝试回滚；
- 部署锁冲突时立即退出。

删除旧 `scripts/deploy-multisource.sh`，确保只有一个活动部署接口。

## 7. Task 5：实现最小部署包

**RED**

新增测试调用真实打包脚本，检查归档成员严格等于：

```text
compose.yaml
compose.server-2g.yaml
.env.example
scripts/deploy-acr.sh
scripts/napcat-entrypoint.sh
scripts/backup-postgres.sh
scripts/restore-postgres.sh
```

并断言不包含 `.env`、源码、测试、Git 元数据或备份。

**GREEN**

实现 `scripts/package-deployment.sh <输出tar.gz>`：

- 输出路径必须明确；
- 使用临时目录组装白名单；
- 失败不留下部分归档；
- 归档根目录固定为 `anime-qqbot/`；
- 输出 SHA-256 摘要。

## 8. Task 6：文档与运维接口

更新：

- `.env.example`：加入 `APP_IMAGE`、`COMPOSE_FILE`；
- `README.md`：默认发布入口改为 ACR；
- `docs/deployment.md`：ACR 控制台规则、打包上传、登录、首次部署、SSH 隧道；
- `docs/operations.md`：升级、回滚、资源监控、映射命令；
- `docs/acceptance/v0.2.0.md`：单镜像构建与五单元验收；
- 修正清单中旧部署事实。

文档必须明确：

- 生产数据库沿用旧密码；
- ACR 凭证不写入 `.env`；
- WebUI 不开放公网；
- 不运行全局 prune；
- OpenClaw 停用与否不是 Bot 部署脚本的责任。

## 9. Task 7：完整验收

按顺序运行：

```bash
.venv/bin/python -m ruff format --check src tests
.venv/bin/python -m ruff check src tests
.venv/bin/python -m mypy src
TEST_DATABASE_URL=postgresql+asyncpg://anime:anime@127.0.0.1:55432/anime_test \
DATABASE_URL=postgresql+asyncpg://anime:anime@127.0.0.1:55432/anime_test \
.venv/bin/python -m pytest -q
bash -n scripts/*.sh
docker compose config --quiet
docker build -t anime-qqbot:single-image-test .
```

然后启动隔离 Compose：

```bash
docker compose -p anime-qqbot-single-image-check up -d --wait
docker compose -p anime-qqbot-single-image-check ps
docker compose -p anime-qqbot-single-image-check logs migrate worker astrbot napcat
docker compose -p anime-qqbot-single-image-check down -v
```

验收必须确认：

- migration 退出 0；
- PostgreSQL、Worker、AstrBot、NapCat healthy；
- AstrBot 加载 `anime_tracking 0.2.0`；
- Worker 与 AstrBot 显示相同应用镜像 ID；
- 临时容器、卷和网络已清理；
- Git diff 无空白错误。

## 10. Task 8：审阅、提交和发布

提交前审阅：

- 不含秘密；
- 不再引用 `Dockerfile.astrbot` 或 `deploy-multisource.sh`；
- 不含 QQ 官方机器人运行时；
- 不影响 OurNotes；
- 删除内容均有替代路径；
- 工作区只包含本设计范围改动。

完成后提交到 `main` 并推送 `origin/main`，触发 ACR 自动构建。ACR 构建结果、服务器
ACR 登录、生产部署和 QQ 扫码属于人工/外部验收门。

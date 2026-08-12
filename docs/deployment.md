# v0.3.0 单镜像 ACR 部署指南

## 部署边界

生产环境由五个 Compose 单元组成：PostgreSQL、一次性 migration、Worker、AstrBot
和 NapCat。migration、Worker、AstrBot 共用一个 ACR 应用镜像，服务器只拉取镜像，
不 clone 完整仓库，也不执行本地构建。

本版本只使用 NapCat + AstrBot（OneBot 11）接入普通 QQ 小号，不包含 QQ 官方机器人
运行时。AstrBot 和 NapCat 的 WebUI 仅绑定服务器 `127.0.0.1`；无需修改 Nginx，
也不得新增公网端口。

## 1. 确认 ACR 构建规则

在阿里云容器镜像服务的 `stonesver/anime-qqbot` 仓库中确认：

| Dockerfile | 镜像版本 | 架构 | 海外机器构建 |
|---|---|---|---|
| `Dockerfile` | `latest` | `linux/amd64` | 自动 |
| `Dockerfile.postgres` | `vendor-postgres-17.4-alpine` | `linux/amd64` | 人工 |
| `Dockerfile.napcat` | `vendor-napcat-v4.17.50` | `linux/amd64` | 人工 |

三条规则都使用 Branch `main`、构建上下文 `/`。只有应用 `latest` 随代码变化自动
构建；两个 vendor 规则只在固定第三方版本变化时人工触发，避免普通应用发布改变
NapCat 镜像。首次部署必须先看到三个标签全部存在。服务器只访问 ACR，不直接访问
Docker Hub。

## 2. 生成和上传最小部署包

在本地仓库执行：

```bash
./scripts/package-deployment.sh dist/anime-qqbot-deployment.tar.gz
scp -P 2222 dist/anime-qqbot-deployment.tar.gz root@47.112.103.127:/tmp/
```

归档只包含 Compose、`.env.example` 和四个运维脚本，不包含源码、`.env`、数据库
备份、QQ 登录数据、Git 历史或 ACR 凭证。

服务器解包：

```bash
sudo mkdir -p /opt/anime-qqbot
sudo tar -xzf /tmp/anime-qqbot-deployment.tar.gz \
  --strip-components=1 -C /opt/anime-qqbot
cd /opt/anime-qqbot
```

重复上传部署资产时不要删除现有 `.env`、Docker volumes 或备份目录。

## 3. 准备生产配置

首次部署：

```bash
cp .env.example .env
chmod 600 .env
```

至少确认：

```dotenv
APP_IMAGE=crpi-thkewd16qu1tdfsq.cn-shenzhen.personal.cr.aliyuncs.com/stonesver/anime-qqbot
IMAGE_TAG=latest
POSTGRES_IMAGE=crpi-thkewd16qu1tdfsq.cn-shenzhen.personal.cr.aliyuncs.com/stonesver/anime-qqbot:vendor-postgres-17.4-alpine
NAPCAT_IMAGE=crpi-thkewd16qu1tdfsq.cn-shenzhen.personal.cr.aliyuncs.com/stonesver/anime-qqbot:vendor-napcat-v4.17.50
COMPOSE_FILE=compose.yaml:compose.server-2g.yaml
POSTGRES_PASSWORD=<现有 anime 数据库角色密码>
BANGUMI_USER_AGENT=anime-qqbot/0.3.0 (your-email@example.com)
ONEBOT_TOKEN=<至少 24 位 URL 安全随机字符>
```

已有 `anime-qqbot_postgres-data` 卷时，`POSTGRES_PASSWORD` 必须沿用数据库初始化时
的密码。只修改环境变量不会改变卷中已有 `anime` 角色的密码。旧部署配置仍保存在
`/opt/anime-qqbot-v01-archive/.env` 时，可以从中核对，但不要把密码输出到聊天、
日志或版本库。

`ONEBOT_TOKEN` 只使用字母、数字、`_`、`.`、`-`。ACR 登录密码不得写进 `.env`。

## 4. 登录 ACR 并首次部署

```bash
sudo docker login \
  crpi-thkewd16qu1tdfsq.cn-shenzhen.personal.cr.aliyuncs.com
cd /opt/anime-qqbot
sudo ./scripts/deploy-acr.sh --no-backup
sudo docker compose ps
```

首次部署没有正在运行的 PostgreSQL 时，`--no-backup` 是正常选择；当前已有数据库
容器且希望在部署前留档时，可直接去掉该参数。脚本会：

1. 校验配置并取得部署锁；
2. 在可用时备份数据库和保存旧应用镜像；
3. 从 ACR 拉取应用镜像；首次部署时补拉缺失的固定 vendor 镜像；
4. 等待 PostgreSQL、执行 migration；
5. 更新 Worker/AstrBot；运行中的 NapCat 保持原容器，已停止的 NapCat 保持停止；
6. 输出实际镜像 ID、digest、备份路径、NapCat 发布前后指纹和 Compose 状态。

脚本不会清理全局镜像、卷或网络，也不会操作 OpenClaw、Nginx 或 OurNotes。

## 5. 首次 OneBot 配置

从本地建立 SSH 隧道：

```bash
ssh -p 2222 \
  -L 6185:127.0.0.1:6185 \
  -L 6099:127.0.0.1:6099 \
  root@47.112.103.127
```

1. 打开 `http://127.0.0.1:6185`，从 `docker compose logs astrbot` 查找 AstrBot
   首次登录信息。
2. 在 AstrBot 中创建 `aiocqhttp`（OneBot 11）适配器，监听 `0.0.0.0:6199`，
   Access Token 与 `.env` 中的 `ONEBOT_TOKEN` 完全一致。
3. 打开 `http://127.0.0.1:6099`，扫码登录专用 QQ 小号。NapCat 会连接
   `ws://astrbot:6199/ws`。
4. 查看 `docker compose logs -f napcat astrbot`，确认反向 WebSocket 已连接。
5. 把小号加入测试群，发送 `/番剧 帮助`。

### v0.3 分阶段开关

进入 AstrBot 的 `anime_tracking` 插件配置，先在测试群按以下顺序开启：

1. `interaction_gateway_enabled=true`：启用 @机器人入口；新群短命令仍默认关闭。
2. `send_governor_enabled=true`：启用查询和主动提醒的统一限频。
3. `admin_page_writes_enabled=true`：确认管理页只经 SSH 隧道访问后，允许写操作。

内容运营开关不在 QQ 群内暴露。进入控制台“内容运营”页后，只对测试群逐项开启每日
汇总、`@全体` 或周报；所有新开关默认关闭。每日 `@全体` 依赖
`NAPCAT_ONEBOT_URL` 与 `ONEBOT_TOKEN`，任一缺失或 NapCat 无法返回剩余额度时都不会
降级为盲发。个人/定向资源通知保持原有即时发送路径。

资源主动通知默认不带 Mikan 链接。用户发送
`资源详情 <番剧关键词> [集数]` 或 `/番剧 资源详情 <番剧关键词> [集数]` 时，
机器人只读取已持久化资源并最多返回一个 Mikan 页面链接。

`proactive_action_links_enabled` 默认保持 `false`。未来接入 B 站 UP 主视频后，如需
灰度开启动作链接，来源白名单 `proactive_action_link_sources` 只保留 `bilibili`；
系统仅接受 `https://www.bilibili.com/video/BV...` 规范视频页，每条通知最多一个。
Mikan 通知不使用该动作位。

打开插件详情中的“番剧放送控制台”即可进入管理页。页面通过 AstrBot Dashboard
认证和 Plugin Page bridge 工作，不需要 Nginx。机器人设置权限只认 AstrBot 事件
角色 `admin`；QQ 群主和群管理员没有额外权限。

发布后先在“番剧目录”确认能够看到已同步标题、来源、下一次放送和精度，并在“数据源”
确认 Bangumi、AniList、Mikan 均有状态记录。北京时间凌晨验证“今日番剧”时，结果日期
必须与群时区当天一致。

测试群中建议依次验证：

```text
@机器人 今天有什么番
@机器人 搜番 芙莉莲
@机器人 开启短命令
今日番剧
搜番 芙莉莲
追番 1
我的追番
```

未明确开启短命令的群，只响应 `/番剧 ...` 与 @机器人，不扫描普通聊天正文。

6185、6099 不应加入 Nginx，也不应在云安全组开放。AstrBot 不同补丁版本的 WebUI
字段名称可能略有差别，以 `aiocqhttp`、反向 WebSocket 监听端口和 Access Token
为准。

## 6. 验证

```bash
docker compose ps
docker compose logs --tail=150 migrate worker astrbot napcat
docker image inspect \
  crpi-thkewd16qu1tdfsq.cn-shenzhen.personal.cr.aliyuncs.com/stonesver/anime-qqbot:latest \
  --format 'ID={{.Id}} Digests={{json .RepoDigests}}'
free -h
docker stats --no-stream
```

正常运行状态下预期 PostgreSQL、Worker、AstrBot、NapCat 为 healthy，migration
退出码为 0。若 NapCat 在发布前被人工停止，脚本会保留该状态并给出提示。容器健康
不代表 QQ 已登录；仍需检查 OneBot 日志和真实测试群消息。

## 7. 日常升级

确认 ACR 新构建成功后，在服务器执行：

```bash
cd /opt/anime-qqbot
sudo ./scripts/deploy-acr.sh
```

已有运行版本时，脚本会在拉取前创建数据库备份，并把当前应用镜像保存为
`anime-qqbot:rollback`。应用健康失败会自动恢复旧镜像并只重建 Worker/AstrBot；
NapCat 不参与应用回滚。migration 失败不会自动恢复数据库，请按
[运维手册](operations.md)人工处理。

只有明确安排固定第三方镜像维护窗口时才执行：

```bash
sudo ./scripts/deploy-acr.sh --refresh-vendors
```

正常发布结果应包含 `NapCat restart detected: no`。若为 `yes`，先核对是否执行了
vendor 刷新、NapCat 是否原本停止或容器是否发生异常重启，再进行 QQ 登录。
## AnimeSchedule 配置

发布镜像前确认服务器 `.env` 已包含 `ANIMESCHEDULE_TOKEN`，且该文件不进入镜像和版本库。`ANIMESCHEDULE_ENABLED` 默认是 `false`；升级完成、后台确认 Token 为“已配置”后，再由 Bot 持有者启用并手动触发一次同步。

数据库迁移 `0017_animeschedule_integration` 为已有映射策略增加 AnimeSchedule 控制字段，并允许 `sync_animeschedule` 管理任务。回滚应用版本前应先在后台关闭 AnimeSchedule；旧的 Bangumi、AniList、Mikan 数据和个人资源通知不依赖新来源。

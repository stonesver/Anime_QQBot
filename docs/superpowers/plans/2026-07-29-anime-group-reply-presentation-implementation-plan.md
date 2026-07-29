# Anime QQBot 群聊回复与番剧卡片实施计划

- 日期：2026-07-29
- 状态：待实施
- 对应规格：[群聊回复与番剧卡片设计](../specs/2026-07-29-anime-group-reply-presentation-design.md)
- 目标版本：v0.4.0
- 设计基线提交：`77054a1`
- 运行基线：AstrBot `v4.26.7`、NapCat `v4.18.13`、PostgreSQL 17.4
- 资源基线：2 核 2 GiB，服务器同时托管现有静态站

## 1. 完成定义

只有以下条件全部满足，才可以标记 v0.4.0 完成：

1. 搜索唯一命中、番剧详情和下一集在本地真实海报可用时返回 `1000 × 600` 放送信号
   卡片；其他群聊回复继续使用结构化文本。
2. 卡片左栏固定 `400 × 600`，只展示真实海报；超宽或超高海报不拉伸，使用同图模糊
   铺底并完整居中。
3. 海报缺失、未缓存、损坏、解码失败或渲染失败时返回字段完整的等价文本，不生成或
   发送占位图。
4. 今天、本周和季度列表按日期或星期分组；候选编号、帮助、订阅确认、错误、开播提醒
   和 Mikan 更新提醒仍为文本。
5. `/番剧` 固定命令、`@机器人` 和已显式开启的短命令共用同一个 Reply 渲染与发送
   边界，三个入口的卡片策略一致。
6. 群消息请求只读取 PostgreSQL 和 `card-assets` 本地卷；发送图片时使用 AstrBot 本地
   文件组件，不访问远程图片 URL。
7. Worker 按 Bangumi 优先、AniList 兜底的顺序后台下载确认来源快照中的 HTTPS 海报；
   下载、校验和替换均满足规格中的安全限制与原子性。
8. `card-assets` 总上限默认 `300 MiB`，超过后回收到 `270 MiB`；清理范围严格限制在
   该卷内。
9. Pillow 渲染进程内单并发；首次本地渲染不超过 `1 s`，单并发渲染新增峰值内存不超过
   `80 MiB`。
10. 实际应用镜像包含固定可用的 Noto Sans CJK 字体，并能在容器内生成包含中文、日文和
    长标题的可解码样卡。
11. Ruff、mypy、全量 pytest、Compose 配置、真实镜像烟测和 2 GiB 资源验收全部通过。
12. 日常 ACR 发布只重建 Worker 与 AstrBot；NapCat 容器 ID 与 `StartedAt` 指纹不变，
    输出 `NapCat restart detected: no`。
13. 手机 QQ 与桌面 QQ 的测试群外部门禁通过，并验证无海报条目只发送文本。

## 2. 实施约束

1. 按本计划的纵向分片顺序实施；每个任务结束时必须保留可运行的完整文本降级路径。
2. 行为变更先写失败测试，确认失败原因正确后再写最小实现，不得在最后集中补测试。
3. Anime Core 不导入 AstrBot、NapCat、OneBot 或 QQ 类型。
4. `CardDataAssembler` 只读 PostgreSQL，`AnimeCardRenderer` 只读本地数据和文件，
   `PosterCache` 的远程下载能力只允许 Worker 调用。
5. `CardReplyFactory` 不改变查询、订阅、候选会话、防误触、限频和 Outbox 语义。
6. 群消息路径不得构造或调用 `httpx.AsyncClient`、Bangumi、AniList 或 Mikan 客户端。
7. AstrBot 图片消息固定使用本地文件：
   `Comp.Image.fromFileSystem(path)`；图文消息使用 `event.chain_result(chain)`。不得把
   上游海报 URL 传给 `Image.fromURL()` 或 `event.image_result()`。
8. 海报只接受 confirmed 且未 disabled 的 Bangumi/AniList 来源最新快照；Mikan 只作为
   来源状态标签，不作为海报来源。
9. NSFW、disabled Anime 或 disabled External Entry 不得进入组装、缓存或渲染。
10. 卡片输出固定 PNG；不得引入 Chromium、HTML 截图、Playwright 渲染、Redis、新容器
    或常驻图片服务。
11. 文件名只由 Anime ID 与 SHA-256 摘要组成；不使用 URL 路径、标题或用户输入。
12. 所有临时文件必须在目标卷内创建，并以同文件系统原子 `os.replace()` 发布。
13. CJK 字体由 Dockerfile 固定安装和探测；运行时不得依赖宿主机字体或静默切换字体。
14. 日志不得记录 Token、数据库连接串、完整上游正文、完整响应头或用户消息全文。
15. 不新增数据库迁移；本轮所有缓存和 manifest 都是可删除、可重建的派生数据。
16. 不修改 Nginx，不开放 6185/6099 公网端口，不改变现有静态站发布。
17. 不修改 `napcat-qq`、`napcat-config`、`astrbot-data` 或 `postgres-data` 数据语义。
18. 不提交 `.env`、真实 QQ 标识、持久卷内容、生成卡片、基准输出或用户的 `dist/`。
19. `dist/` 是用户所有的未跟踪部署产物，所有任务和提交都必须保持它不变。
20. 任何真实性能或 QQ 客户端结论必须由本轮证据支持；自动化通过不能替代外部门禁。

## 3. 目标目录结构

```text
src/anime_qqbot/
├── catalog/
│   ├── models.py
│   ├── bangumi_sync.py
│   └── sync_anilist.py
├── presentation/
│   ├── __init__.py
│   ├── models.py
│   ├── assembler.py
│   ├── text.py
│   ├── poster_cache.py
│   ├── poster_warmup.py
│   └── renderer.py
├── entrypoints/
│   ├── cli.py
│   ├── card_benchmark.py
│   └── card_smoke.py
└── settings.py

astrbot_plugin_anime_tracking/
├── main.py
├── metadata.yaml
├── _conf_schema.json
└── anime_tracking_plugin/
    ├── adapter.py
    ├── card_reply_factory.py
    ├── interaction_gateway.py
    ├── lifecycle.py
    └── rendering.py

tests/
├── acceptance/
│   ├── test_card_container_contract.py
│   ├── test_compose_config.py
│   ├── test_deploy_acr_script.py
│   ├── test_deployment_package.py
│   └── test_v04_documentation.py
├── integration/
│   ├── test_card_data_assembler.py
│   ├── test_interaction_gateway.py
│   └── test_poster_warmup.py
└── unit/
    ├── presentation/
    │   ├── test_card_models.py
    │   ├── test_card_renderer.py
    │   ├── test_poster_cache.py
    │   └── test_text_presentation.py
    └── astrbot/
        ├── test_card_reply_factory.py
        ├── test_event_adapter.py
        └── test_reply_rendering.py
```

目标结构中的新文件是建议的深模块边界。实施时可以在同一目录内合并非常短的纯类型
文件，但不得把数据库查询、HTTP 下载、Pillow 绘图和 AstrBot 发送堆进同一个模块。

## 4. Git、测试和提交纪律

建议使用单一功能分支：

```text
codex/feat/group-reply-cards
```

每个任务遵循：

1. 只写任务列出的失败测试并运行，保存预期失败原因。
2. 写最小实现，运行定向测试直至通过。
3. 运行受影响模块的 Ruff、mypy 和测试。
4. 执行 `git diff --check` 与 `git status --short`。
5. 只暂存任务列出的文件，确认没有 `.env`、`dist/`、样卡或缓存文件。
6. 使用任务给出的提交说明形成小提交；后续任务不得顺手改写无关模块。

常用检查：

```bash
UV_CACHE_DIR=.uv-cache .venv/bin/uv lock --check
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy src
TEST_DATABASE_URL=postgresql+asyncpg://anime:anime@127.0.0.1:55432/anime_test \
DATABASE_URL=postgresql+asyncpg://anime:anime@127.0.0.1:55432/anime_test \
  .venv/bin/pytest
docker compose config --quiet
```

涉及 PostgreSQL 的任务先启动隔离测试库：

```bash
docker compose -f compose.test.yaml up -d --wait
```

涉及锁文件的任务必须使用项目现有 `.venv`：

```bash
UV_CACHE_DIR=.uv-cache .venv/bin/uv lock
UV_CACHE_DIR=.uv-cache .venv/bin/uv lock --check
```

## 5. 分片一：锁定展示契约与完整文本降级

演示终点：核心层可以从本地数据库组装安全、稳定的卡片数据，并为所有图片错误生成
字段完整的等价文本；现有消息仍全部按文本发送。

### 任务 1：加入 Pillow、版本与卡片配置契约

**文件**

- 修改：`pyproject.toml`
- 修改：`uv.lock`
- 修改：`src/anime_qqbot/settings.py`
- 修改：`astrbot_plugin_anime_tracking/_conf_schema.json`
- 新建：`tests/unit/presentation/test_card_settings.py`

**失败测试**

1. 断言 `Settings` 默认提供：
   - `card_asset_root=/var/lib/anime-qqbot/cards`
   - `card_cache_max_bytes=314572800`
   - `card_cache_target_bytes=283115520`
   - `poster_download_max_bytes=8388608`
   - `poster_decode_max_pixels=30000000`
   - `poster_connect_timeout_seconds=3`
   - `poster_total_timeout_seconds=10`
2. 断言 target 必须小于 max，字节与超时均为正数。
3. 断言插件 schema 提供默认开启但可紧急关闭的 `card_presentation_enabled`。
4. 运行测试并确认因字段或依赖缺失失败。

**实现**

1. 生产依赖增加 `pillow>=11,<13`，开发依赖增加与 Pillow 版本匹配的类型包。
2. 将上述配置加入 `Settings`，使用 Pydantic 约束和模型级校验保证回收目标小于上限。
3. 插件 schema 增加 `card_presentation_enabled`，默认 `true`；关闭时只走现有文本路径。
4. 重建 `uv.lock`，不得使用手工编辑锁文件代替 `uv lock`。

**验证**

```bash
UV_CACHE_DIR=.uv-cache .venv/bin/uv lock --check
.venv/bin/pytest tests/unit/presentation/test_card_settings.py
.venv/bin/ruff check pyproject.toml src/anime_qqbot/settings.py \
  tests/unit/presentation/test_card_settings.py
.venv/bin/mypy src
```

**提交**

```text
build: add card rendering dependencies and settings
```

### 任务 2：补齐来源快照中的年份、季度与作品类型

**文件**

- 修改：`src/anime_qqbot/catalog/models.py`
- 修改：`src/anime_qqbot/catalog/adapters/anilist.py`
- 修改：`src/anime_qqbot/catalog/sync_anilist.py`
- 修改：`src/anime_qqbot/catalog/bangumi_sync.py`
- 修改：`tests/integration/test_anilist_catalog_sync.py`
- 修改：`tests/integration/test_bangumi_catalog_sync.py`

**失败测试**

1. AniList adapter 从现有 GraphQL 字段解析 `seasonYear`、`season` 和 `format`。
2. AniList 最新快照包含规范化键：
   `release_year`、`season_name`、`media_format`。
3. Bangumi 快照至少从有效 `air_date` 派生 `release_year` 和中文季度名；没有可靠作品类型
   时保持字段缺失，不伪造类型。
4. 老测试中使用位置参数构造 `AnimeDetail` 的行为不被新可选字段破坏。

**实现**

1. 在 `AnimeDetail` 尾部增加可选字段，保持旧位置参数兼容。
2. AniList adapter 只接收白名单枚举/字符串，并把季度映射为 `冬/春/夏/秋`。
3. 两个同步器写入统一快照键；空值可以省略或写 `None`，组装器必须统一隐藏。
4. 不新增数据库列或迁移。

**验证**

```bash
TEST_DATABASE_URL=postgresql+asyncpg://anime:anime@127.0.0.1:55432/anime_test \
  .venv/bin/pytest \
  tests/integration/test_anilist_catalog_sync.py \
  tests/integration/test_bangumi_catalog_sync.py
.venv/bin/pytest tests/unit/catalog
.venv/bin/ruff check src/anime_qqbot/catalog tests/integration
.venv/bin/mypy src
```

**提交**

```text
feat: normalize card metadata in source snapshots
```

### 任务 3：定义平台无关的卡片数据与场景策略

**文件**

- 新建：`src/anime_qqbot/presentation/__init__.py`
- 新建：`src/anime_qqbot/presentation/models.py`
- 新建：`tests/unit/presentation/test_card_models.py`

**失败测试**

1. 定义 `CardScene`，只允许 `UNIQUE_SEARCH`、`DETAIL`、`NEXT` 三种图片场景。
2. `AnimeCardData` 包含类型化字段：
   Anime ID、展示标题、日文标题、年份、季度、作品类型、下一集、Bangumi 评分、总集数、
   放送状态、confirmed 来源集合、群时区和投影指纹。
3. 空字符串、`None` 和未知次要字段在构造时规范化，不进入标签列表。
4. 来源集合只允许 `bangumi`、`anilist`、`mikan`，顺序固定，不受数据库返回顺序影响。
5. 快照版本、下一集或群时区变化会改变投影指纹输入；无关当前时间不会导致缓存抖动。

**实现**

1. 使用冻结 dataclass/枚举定义不可变数据，不包含 ORM、HTTP 或 AstrBot 类型。
2. 下一集使用独立值对象保存 UTC 时刻、日期精度与集数标签。
3. 把允许图片的场景策略做成纯函数，禁止调用方用任意字符串开启图片。

**验证**

```bash
.venv/bin/pytest tests/unit/presentation/test_card_models.py
.venv/bin/ruff check src/anime_qqbot/presentation tests/unit/presentation
.venv/bin/mypy src
```

**提交**

```text
feat: define platform neutral anime card data
```

### 任务 4：实现 CardDataAssembler 本地只读投影

**文件**

- 新建：`src/anime_qqbot/presentation/assembler.py`
- 新建：`tests/integration/test_card_data_assembler.py`

**失败测试**

1. 只读取未 disabled、非 NSFW Anime。
2. 只读取 confirmed、未 disabled 的来源链接及每个来源版本最高的快照。
3. 标题、日文标题、海报来源和评分优先级与现有 `project_anime()` 一致：
   Bangumi 海报优先、AniList 兜底。
4. 总集数采用 Bangumi 有效值优先、AniList 兜底。
5. 下一集选择 `now` 之后最早的 occurrence，精确时间优先于同日 date-only；转换到传入
   群时区。
6. confirmed Mikan 链接只增加来源标签，不参与海报和评分字段。
7. 快照缺字段时隐藏字段，不输出 `None`、空字符串或伪造值。
8. blocked、disabled 或不存在 Anime 返回明确的 `None/Blocked` 结果，不泄漏字段。
9. 组装期间不创建 HTTP 客户端、不写数据库、不更新订阅或候选会话。

**实现**

1. 使用 PostgreSQL 子查询或 window function 每来源取最新快照，避免 ORM N+1。
2. 复用 `project_anime()` 的字段优先级，不在 SQL 中复制另一套标题/海报规则。
3. 用快照 ID/版本、下一集 key 和群时区生成稳定 SHA-256 投影指纹。
4. `now` 只用于选择下一集，不直接写入指纹。

**验证**

```bash
TEST_DATABASE_URL=postgresql+asyncpg://anime:anime@127.0.0.1:55432/anime_test \
DATABASE_URL=postgresql+asyncpg://anime:anime@127.0.0.1:55432/anime_test \
  .venv/bin/pytest tests/integration/test_card_data_assembler.py
.venv/bin/ruff check src/anime_qqbot/presentation/assembler.py \
  tests/integration/test_card_data_assembler.py
.venv/bin/mypy src
```

**提交**

```text
feat: assemble card data from local catalog
```

### 任务 5：建立统一结构化文本与图片降级文本

**文件**

- 新建：`src/anime_qqbot/presentation/text.py`
- 新建：`tests/unit/presentation/test_text_presentation.py`
- 修改：`astrbot_plugin_anime_tracking/anime_tracking_plugin/adapter.py`
- 修改：`tests/unit/astrbot/test_event_adapter.py`

**失败测试**

1. 今天、本周和季度按星期/日期分组，每项只显示时间、标题和可用集数。
2. 我的订阅保持紧凑文本，不渲染图片。
3. 单番等价文本包含所有可用字段：展示标题、日文标题、下一集、评分、总集数、放送状态
   和来源标签。
4. 未知下一集显示 `待定 / 暂无已知下一集`；缺少评分或总集数时直接隐藏该行。
5. 候选列表仍使用短编号，不显示内部 UUID；帮助、订阅、错误和状态文本语义不变。
6. 中文、日文、emoji 和超长标题不会产生空行风暴或字符串 `None`。

**实现**

1. 将 `_format_anime_row()` 和列表拼接迁移到核心纯文本模块。
2. 让 adapter 只选择场景与传入数据，不继续维护第二套格式字符串。
3. 暂不生成图片 Reply；本任务结束后所有现有入口仍发送文本。

**验证**

```bash
.venv/bin/pytest \
  tests/unit/presentation/test_text_presentation.py \
  tests/unit/astrbot/test_event_adapter.py
.venv/bin/pytest tests/acceptance/test_v02_commands.py tests/e2e/test_astrbot_group_queries.py
.venv/bin/ruff check src/anime_qqbot/presentation/text.py \
  astrbot_plugin_anime_tracking/anime_tracking_plugin/adapter.py tests/unit
.venv/bin/mypy src
```

**提交**

```text
refactor: centralize structured anime reply text
```

## 6. 分片二：让 Worker 安全缓存真实海报

演示终点：Worker 可以在不影响目录同步的情况下，把 confirmed Bangumi/AniList 海报
安全、原子地写入共享目录；AstrBot 尚未发送图片。

### 任务 6：实现受限 PosterCache 下载与本地 manifest

**文件**

- 新建：`src/anime_qqbot/presentation/poster_cache.py`
- 新建：`tests/unit/presentation/test_poster_cache.py`

**失败测试**

1. 只接受 `https`，拒绝 `http`、`file`、data URI、无 host URL 和用户凭据 URL。
2. 使用连接 `3 s`、总请求 `10 s` 超时，禁止无限重定向；重定向后的 URL 也必须是 HTTPS。
3. 流式读取超过 `8 MiB` 立即中止并删除临时文件，不依赖错误的 Content-Length。
4. 只接受 JPEG、PNG、WebP；同时验证响应类型、Pillow 实际格式和解码成功。
5. 设置 `Image.MAX_IMAGE_PIXELS=30000000`，decompression bomb 或超限图片失败。
6. Bangumi URL 失败后可以由调用方尝试 AniList；失败不会覆盖已有有效海报。
7. 成功后写入：
   `posters/<anime-id>/<content-sha256>.<ext>` 与原子 manifest；
   manifest 只包含摘要、格式、来源和本地相对路径，不保存完整 URL。
8. 临时文件与最终文件位于同目录，以 `os.replace()` 发布；异常后无 `.tmp` 残留。
9. `find_local_poster(anime_id)` 只返回根目录下 manifest 指向的可解码文件；路径穿越、
   坏 manifest 和坏图片返回 `None`。
10. 日志错误摘要不包含 query、凭据、响应正文或完整异常对象。

**实现**

1. HTTP 客户端通过构造参数注入，便于 Worker 复用连接与单元测试拦截。
2. 写入前以 Pillow `verify()` 校验，再重新打开获取尺寸和格式。
3. 所有根路径使用 `Path.resolve()` 后验证从属关系。
4. 下载方法命名明确，例如 `download_and_store()`；本地查找方法不得隐式联网。

**验证**

```bash
.venv/bin/pytest tests/unit/presentation/test_poster_cache.py
.venv/bin/ruff check src/anime_qqbot/presentation/poster_cache.py \
  tests/unit/presentation/test_poster_cache.py
.venv/bin/mypy src
```

**提交**

```text
feat: add secure local poster cache
```

### 任务 7：实现海报候选查询、优先级与后台预热

**文件**

- 新建：`src/anime_qqbot/presentation/poster_warmup.py`
- 新建：`tests/integration/test_poster_warmup.py`
- 修改：`src/anime_qqbot/catalog/enrichment.py`
- 修改：`tests/integration/test_catalog_enrichment.py`

**失败测试**

1. 预热查询只选择可展示 Anime 的 confirmed、未 disabled Bangumi/AniList 最新快照。
2. 同一 Anime 固定先尝试 Bangumi，缺 URL 或下载失败后再尝试 AniList。
3. 两者都失败时不写 placeholder、不创建空 manifest，返回可观察的失败计数。
4. 已有相同内容摘要的有效海报不重复下载；快照 URL/内容变化可生成新版本。
5. 单次默认批量有限，按最新 `fetched_at` 优先，单个失败不阻断其他 Anime。
6. 搜索 miss 定向 enrichment 返回本轮同步得到的安全 `anime_ids` 列表，订阅 enrichment
   返回目标 Anime ID；不得返回 ORM 或上游正文。

**实现**

1. `PosterWarmupService.run_once(limit, anime_ids=None)` 负责候选查询和 Bangumi/AniList
   顺序，不让 CLI 复制优先级。
2. 在 `CatalogEnrichmentRunner` 的结果中增加 `anime_ids`，保留现有计数字段兼容。
3. 下载失败以 Anime ID、来源和异常类型记录，不改变 `SourceSyncState` 成功语义。

**验证**

```bash
TEST_DATABASE_URL=postgresql+asyncpg://anime:anime@127.0.0.1:55432/anime_test \
DATABASE_URL=postgresql+asyncpg://anime:anime@127.0.0.1:55432/anime_test \
  .venv/bin/pytest \
  tests/integration/test_poster_warmup.py \
  tests/integration/test_catalog_enrichment.py
.venv/bin/ruff check src/anime_qqbot/presentation/poster_warmup.py \
  src/anime_qqbot/catalog/enrichment.py tests/integration
.venv/bin/mypy src
```

**提交**

```text
feat: warm confirmed posters after enrichment
```

### 任务 8：接入 Worker 调度并隔离失败

**文件**

- 修改：`src/anime_qqbot/entrypoints/cli.py`
- 修改：`tests/unit/entrypoints/test_worker_schedule.py`
- 新建：`tests/unit/entrypoints/test_worker_poster_warmup.py`

**失败测试**

1. `_build_components()` 只在 Worker 图中创建可下载 PosterCache 和 PosterWarmupService。
2. 周期目录同步与 projection 完成后运行有限批量预热。
3. `search_miss` 和 `subscription` operator job 完成后立即预热其返回的 Anime IDs。
4. 预热异常只记录并返回计数，不使 Worker 退出、不回滚目录快照、不阻断 Mikan 和提醒。
5. 下一轮预热不会因上一轮单个失败永久饿死其他候选。
6. AstrBot lifecycle 不构造下载客户端。

**实现**

1. 将预热服务加入 `WorkerComponents`。
2. operator 路径先完成 enrichment，再以结果中的 `anime_ids` 调用预热。
3. 周期路径在 `_project_fresh_snapshots()` 后运行 `run_once(limit=20)`。
4. Worker 关闭时关闭 PosterCache 持有的 HTTP 客户端。

**验证**

```bash
.venv/bin/pytest \
  tests/unit/entrypoints/test_worker_schedule.py \
  tests/unit/entrypoints/test_worker_poster_warmup.py
.venv/bin/pytest tests/unit/entrypoints
.venv/bin/ruff check src/anime_qqbot/entrypoints/cli.py tests/unit/entrypoints
.venv/bin/mypy src
```

**提交**

```text
feat: schedule poster warmup in worker
```

### 任务 9：实现严格限域的 300 MiB 缓存回收

**文件**

- 修改：`src/anime_qqbot/presentation/poster_cache.py`
- 修改：`src/anime_qqbot/presentation/poster_warmup.py`
- 修改：`tests/unit/presentation/test_poster_cache.py`
- 修改：`tests/unit/entrypoints/test_worker_schedule.py`

**失败测试**

1. 目录总量未超过 max 时不删除文件。
2. 超过 max 后按最近访问时间删除到 target 以下，海报与渲染卡片都纳入同一总量。
3. manifest、内容文件和临时文件按一致规则处理；当前有效项优先保留，孤儿优先清理。
4. 使用卡片/海报时更新访问时间，使热点文件不会被误删。
5. 根目录外的文件、符号链接目标、PostgreSQL/AstrBot/NapCat 路径永远不删除。
6. 删除竞争或权限错误被安全汇总，不使 Worker 退出。
7. Worker 每次周期预热后执行一次回收，不在每条群消息中扫描全目录。

**实现**

1. 把回收算法做成只接收 cache root/max/target 的窄接口。
2. 所有删除目标再次 resolve 并验证从属于 `card-assets`。
3. 单元测试使用 KiB 级阈值验证同一算法，不创建 300 MiB 测试数据。

**验证**

```bash
.venv/bin/pytest \
  tests/unit/presentation/test_poster_cache.py \
  tests/unit/entrypoints/test_worker_schedule.py
.venv/bin/ruff check src/anime_qqbot/presentation tests/unit
.venv/bin/mypy src
```

**提交**

```text
feat: bound derived card asset cache
```

## 7. 分片三：用 Pillow 生成可缓存的放送信号卡片

演示终点：给定本地真实海报和 `AnimeCardData`，核心渲染器能在单并发、无网络条件下
生成稳定 PNG；失败时由上层获得明确失败结果。

### 任务 10：实现确定性 1000 × 600 Pillow 渲染器

**文件**

- 新建：`src/anime_qqbot/presentation/renderer.py`
- 新建：`tests/unit/presentation/test_card_renderer.py`
- 新建：`tests/fixtures/cards/README.md`

**失败测试**

1. 输出为可解码 PNG，尺寸固定 `1000 × 600`。
2. 左侧海报区域固定 `0..399 × 0..599`，右侧从 x=400 开始。
3. 标准 2:3、超宽和超高海报均不拉伸；非 2:3 使用同图模糊铺底和完整前景。
4. 右侧使用规格 Token：
   `#F7FAFF`、`#365FC7`、`#FF5D57`、`#17223B`、`#E9EFFD`。
5. 中文、日文、emoji、安全特殊字符和超长标题不越出右侧边界；标题按固定行数截断并
   使用省略号。
6. 下一集精确时间显示大号时间轨；未知下一集显示 `待定` 和 `暂无已知下一集`。
7. 缺少日文标题、评分、总集数或来源时隐藏相应元素，不绘制空标签。
8. 输入坏海报、字体不存在或 Pillow 异常时不生成输出文件，返回类型化失败。
9. 渲染过程中不存在 HTTP 调用、数据库访问、浏览器子进程或随机视觉值。

**实现**

1. 把布局坐标、字号、颜色和间距定义为模块常量，避免散落 magic number。
2. 使用调用方传入的固定 CJK 与等宽字体路径；初始化时 fail fast 验证字体。
3. 先在同目录临时 PNG 渲染、重新解码校验，再 `os.replace()` 发布。
4. 测试在临时目录机械生成纯色海报，不提交二进制黄金图；断言尺寸、关键区域、边界和
   可解码性，不使用整图脆弱像素快照。

**验证**

```bash
.venv/bin/pytest tests/unit/presentation/test_card_renderer.py
.venv/bin/ruff check src/anime_qqbot/presentation/renderer.py \
  tests/unit/presentation/test_card_renderer.py
.venv/bin/mypy src
```

**提交**

```text
feat: render deterministic broadcast signal cards
```

### 任务 11：加入稳定渲染缓存、损坏恢复与单并发

**文件**

- 修改：`src/anime_qqbot/presentation/renderer.py`
- 修改：`tests/unit/presentation/test_card_renderer.py`

**失败测试**

1. 缓存路径为 `renders/<anime-id>/<projection-fingerprint>.png`，不包含标题或用户输入。
2. 相同 Anime、投影、时区和下一集命中同一缓存，不重复绘制。
3. 快照、下一集或时区变化产生新缓存键。
4. 命中缓存时重新做轻量尺寸/格式验证并更新访问时间。
5. 坏缓存被删除并只尝试一次本地重渲染；再次失败返回失败，不循环。
6. 多个并发请求经过进程内 `asyncio.Semaphore(1)`，不会同时解码/渲染大图。
7. 取消请求会释放 semaphore，不留下半写文件。

**实现**

1. 对外暴露异步 `render_cached()` 服务，把同步 Pillow 工作放入线程但仍由单 semaphore
   包围。
2. 缓存命中不读取数据库，不访问网络。
3. 临时文件名包含进程内安全随机后缀，但最终路径完全由安全摘要决定。

**验证**

```bash
.venv/bin/pytest tests/unit/presentation/test_card_renderer.py
.venv/bin/ruff check src/anime_qqbot/presentation/renderer.py \
  tests/unit/presentation/test_card_renderer.py
.venv/bin/mypy src
```

**提交**

```text
feat: cache card renders with single concurrency
```

### 任务 12：建立真实字体和容器内样卡烟测

**文件**

- 修改：`Dockerfile`
- 新建：`src/anime_qqbot/entrypoints/card_smoke.py`
- 新建：`tests/acceptance/test_card_container_contract.py`
- 修改：`.dockerignore`

**失败测试**

1. Dockerfile 固定安装 Noto Sans CJK 与等宽字体，并将实际路径传给烟测。
2. `card_smoke` 使用程序真实 renderer 和临时真实海报生成中文、日文、长标题样卡。
3. 烟测重新打开 PNG，断言 `1000 × 600`、格式 PNG、左海报槽非空和右侧文字边界有效。
4. 缺少字体时命令非零退出，镜像构建失败。
5. 样卡只写入调用方临时输出目录，不进入镜像最终工作目录或 Git。
6. `.dockerignore` 排除本地 `card-assets`、样卡和基准产物。

**实现**

1. 根据基础镜像包管理器使用固定包名安装字体；安装后用 Python/Pillow 实际加载而不是
   只检查文件存在。
2. Dockerfile 在构建阶段运行 `python -m anime_qqbot.entrypoints.card_smoke`。
3. 构建验收使用 pinned 基础镜像，不改为 `latest`。

**验证**

```bash
.venv/bin/pytest tests/acceptance/test_card_container_contract.py
docker build -t anime-qqbot:card-smoke .
docker run --rm --entrypoint python anime-qqbot:card-smoke \
  -m anime_qqbot.entrypoints.card_smoke
```

**提交**

```text
build: verify cjk card rendering in runtime image
```

## 8. 分片四：统一 AstrBot 图片 Reply 与双入口发送

演示终点：固定命令、@入口和短命令都能在三个允许场景发送本地图片加一行提示；所有
失败和其他场景仍发送结构化文本。

### 任务 13：扩展平台无关 Reply 并实现 CardReplyFactory

**文件**

- 修改：`astrbot_plugin_anime_tracking/anime_tracking_plugin/adapter.py`
- 新建：`astrbot_plugin_anime_tracking/anime_tracking_plugin/card_reply_factory.py`
- 新建：`tests/unit/astrbot/test_card_reply_factory.py`
- 修改：`tests/unit/astrbot/test_event_adapter.py`

**失败测试**

1. `ReplyBlock` 可以表达本地 image path 与 plain text，但不能表达远程 URL。
2. 只有 `UNIQUE_SEARCH`、`DETAIL`、`NEXT` 调用 CardReplyFactory。
3. feature switch 关闭、组装失败、本地海报不存在/损坏或 renderer 失败时返回任务 5 的
   完整等价文本。
4. 成功时 Reply 顺序为本地 Image、最多一行 Plain 提示；图片中已有字段不在提示重复。
5. 列表、候选、我的订阅、订阅确认、帮助、状态和错误不调用 renderer。
6. blocked/disabled/NSFW 不会先渲染再丢弃。
7. factory 不下载海报、不创建 HTTP 客户端，不接收上游 URL。

**实现**

1. `CardReplyFactory` 注入 assembler、local poster locator、renderer 和 text formatter。
2. factory 捕获预期图片错误并安全降级；数据库不可用等业务错误继续按现有错误处理。
3. adapter 在应用用例返回唯一 Anime ID 后调用 factory，不改变用例查询结果。

**验证**

```bash
.venv/bin/pytest \
  tests/unit/astrbot/test_card_reply_factory.py \
  tests/unit/astrbot/test_event_adapter.py
.venv/bin/ruff check astrbot_plugin_anime_tracking/anime_tracking_plugin tests/unit/astrbot
.venv/bin/mypy src
```

**提交**

```text
feat: select image or text anime replies
```

### 任务 14：把 Reply 映射为 AstrBot 本地 Image/Plain 消息链

**文件**

- 修改：`astrbot_plugin_anime_tracking/anime_tracking_plugin/rendering.py`
- 新建：`tests/unit/astrbot/test_reply_rendering.py`
- 修改：`astrbot_plugin_anime_tracking/main.py`
- 修改：`astrbot_plugin_anime_tracking/anime_tracking_plugin/commands.py`

**失败测试**

1. 纯文本 Reply 仍使用 plain result，内容与现有行为兼容。
2. 图片 Reply 映射为：
   `Comp.Image.fromFileSystem(local_path)` 后接可选 `Comp.Plain(hint)`。
3. rendering 拒绝 `http://`、`https://` 和 cache root 外路径。
4. `_dispatch()` 不再把 Reply 手工压成第一个 block 的字符串，而是返回完整 Reply/渲染
   结果。
5. 每个 `/番剧` 子命令通过一个 `_dispatch_result(event)` 发送边界选择
   `event.plain_result()` 或 `event.chain_result()`。
6. SDK 不存在的离线测试使用 fake component/result，不掩盖生产导入错误。
7. 开播和 Mikan 主动通知 renderer 保持现有文本与 `@` 链，不被卡片逻辑影响。

**实现**

1. 按 AstrBot 官方接口导入 `astrbot.api.message_components as Comp`。
2. 将“Reply → components”与“components → event result”拆开，便于无 SDK 单测。
3. 更新模块注释，删除“所有回复只用 plain_result”的过期说明。
4. `commands.py` 若已无生产调用则在全仓引用核对后删除；若保留则调用同一渲染边界，
   禁止维护第二套实现。

**验证**

```bash
.venv/bin/pytest tests/unit/astrbot/test_reply_rendering.py tests/unit/astrbot
.venv/bin/ruff check astrbot_plugin_anime_tracking tests/unit/astrbot
docker run --rm --entrypoint python anime-qqbot:card-smoke -c \
  "import astrbot.api.message_components as Comp; \
from astrbot_plugin_anime_tracking.anime_tracking_plugin.rendering import render_reply"
```

**提交**

```text
feat: send local card image chains through astrbot
```

### 任务 15：让 InteractionGateway 共用完整 Reply，不再退化为 text

**文件**

- 修改：`astrbot_plugin_anime_tracking/anime_tracking_plugin/interaction_gateway.py`
- 修改：`astrbot_plugin_anime_tracking/main.py`
- 修改：`tests/integration/test_interaction_gateway.py`
- 新建：`tests/e2e/test_v04_group_reply_presentation.py`

**失败测试**

1. `GatewayResult` 携带完整 Reply 或渲染描述，不再只有 `text`。
2. `@机器人 搜番/详情/下一集` 与对应 `/番剧` 命令使用同一 CardReplyFactory。
3. 显式开启短命令后，三个图片场景策略与 slash/@入口一致。
4. 普通聊天和默认关闭的短命令仍静默，不因卡片功能扩大唤醒词。
5. 候选回复继续持久化五分钟会话；编号选择后的详情可以生成卡片。
6. SendGovernor 在组装/渲染/发送之前只获取一次许可，不产生重复回复。
7. 图片失败时 slash/@/短命令都只返回完整文本，没有 Image component。
8. 群消息路径 monkeypatch 所有上游 HTTP transport 为“调用即失败”，三个入口仍能从
   本地数据完成回复。
9. `stop_event()` 与现有防重复传播行为保持不变。

**实现**

1. PluginLifecycle 初始化一次 assembler、只读 poster locator、renderer 与
   CardReplyFactory，slash 和 gateway 都引用同一实例。
2. `InteractionGateway.route()` 返回 Reply；`main._handle_group_message()` 调用任务 14 的
   统一发送边界。
3. 所有 owner 设置与限频文案仍可直接构造文本 Reply，但不得绕过统一发送函数。

**验证**

```bash
TEST_DATABASE_URL=postgresql+asyncpg://anime:anime@127.0.0.1:55432/anime_test \
DATABASE_URL=postgresql+asyncpg://anime:anime@127.0.0.1:55432/anime_test \
  .venv/bin/pytest \
  tests/integration/test_interaction_gateway.py \
  tests/e2e/test_v04_group_reply_presentation.py \
  tests/unit/astrbot
.venv/bin/pytest tests/e2e/test_astrbot_group_queries.py
.venv/bin/ruff check astrbot_plugin_anime_tracking tests/integration tests/e2e
.venv/bin/mypy src
```

**提交**

```text
refactor: unify slash and gateway reply delivery
```

## 9. 分片五：Compose、ACR 与 2 GiB 生产硬化

演示终点：Worker 与 AstrBot 共享同一受限派生卷，真实镜像在 2 GiB 覆盖下可运行，日常
发布不会重启 NapCat。

### 任务 16：增加 card-assets 共享卷与最小权限挂载

**文件**

- 修改：`compose.yaml`
- 修改：`.env.example`
- 修改：`tests/acceptance/test_compose_config.py`
- 修改：`tests/acceptance/test_deployment_package.py`

**失败测试**

1. Compose 声明命名卷 `card-assets`。
2. Worker 与 AstrBot 都挂载到固定路径 `/var/lib/anime-qqbot/cards`；NapCat、PostgreSQL
   和 migrate 不挂载该卷。
3. 两个应用服务收到一致 `CARD_ASSET_ROOT` 与缓存限制配置。
4. 不新增服务、端口、Nginx 规则或 bind mount 到宿主宽目录。
5. `.env.example` 记录可选配置和安全默认值，不包含真实路径或秘密。
6. 部署包白名单仍只包含现有运行文件；新增配置通过 compose/.env.example 交付，不打包
   本地缓存。

**实现**

1. 把卷挂载加入 worker/astrbot 的服务级配置，避免 migrate 继承不需要的卷。
2. 保持现有 `postgres-data`、`astrbot-data`、`napcat-qq`、`napcat-config` 不变。
3. 运行 `docker compose config` 检查 anchor 合并后的实际挂载。

**验证**

```bash
.venv/bin/pytest \
  tests/acceptance/test_compose_config.py \
  tests/acceptance/test_deployment_package.py
docker compose config --quiet
docker compose config | rg -n "card-assets|/var/lib/anime-qqbot/cards"
```

**提交**

```text
build: share derived card assets with app roles
```

### 任务 17：证明日常发布只更新 Worker/AstrBot

**文件**

- 修改：`tests/acceptance/test_deploy_acr_script.py`
- 仅在测试证明必要时修改：`scripts/deploy-acr.sh`

**失败测试**

1. 运行中的 routine upgrade 仍只执行 worker/astrbot reconcile，不执行 NapCat `up`、
   stop、restart 或 force-recreate。
2. 新卷首次加入时只允许 Compose 重建 Worker/AstrBot；运行中 NapCat 指纹前后相同。
3. 回滚路径只 force-recreate Worker/AstrBot，不触碰 NapCat 和 card-assets 卷。
4. intentionally stopped NapCat 仍保持 stopped。
5. 脚本结束继续输出前后指纹与 `NapCat restart detected: no`。

**实现**

1. 优先只增加 acceptance 覆盖；现有脚本已经满足时不得为了“看起来更完整”改写脚本。
2. 若 Compose 因依赖隐式启动 NapCat，应用服务更新继续使用 `--no-deps` 明确隔离。
3. 不在部署失败时删除 card-assets；派生卷由 Worker 后续修复。

**验证**

```bash
.venv/bin/pytest tests/acceptance/test_deploy_acr_script.py
sh -n scripts/deploy-acr.sh
```

**提交**

```text
test: preserve napcat across card releases
```

### 任务 18：建立渲染性能与 2 GiB 资源门禁

**文件**

- 新建：`src/anime_qqbot/entrypoints/card_benchmark.py`
- 新建：`tests/acceptance/test_card_performance_contract.py`
- 修改：`compose.server-2g.yaml`
- 修改：`tests/acceptance/test_compose_config.py`

**失败测试与测量**

1. benchmark 使用真实 renderer、固定字体和代表性海报，输出机器可读 JSON：
   首次耗时、缓存命中耗时、进程峰值 RSS delta、输出尺寸与成功状态。
2. 自动门禁断言首次本地渲染 `<1.0 s`、RSS delta `<80 MiB`；低性能开发机若需标记，
   只能把性能测试放到真实镜像门禁，不能降低规格阈值。
3. 并发发起至少 4 个渲染请求，证明实际最大渲染并发为 1。
4. 用 KiB 级 max/target 运行同一清理算法，证明回收到 90%。
5. 在 `compose.server-2g.yaml` 下启动实际服务，记录：
   `docker stats --no-stream`、宿主 `free -m`、`swapon --show`、容器 OOM 状态。
6. AstrBot 512 MiB 与 Worker 192 MiB 若真实测量不够，先优化峰值；只有保存证据并说明
   静态站余量后才能最小上调，四个常驻容器 mem_limit 总和不得无依据逼近 2 GiB。

**实现**

1. benchmark 不联网、不读生产数据库、不写 cache root 以外目录。
2. JSON 输出中不包含宿主绝对秘密路径。
3. 性能验收产物写临时目录，不提交 Git。

**验证**

```bash
.venv/bin/pytest tests/acceptance/test_card_performance_contract.py
python -m anime_qqbot.entrypoints.card_benchmark --json
docker compose -f compose.yaml -f compose.server-2g.yaml config --quiet
docker compose -f compose.yaml -f compose.server-2g.yaml up -d --wait
docker stats --no-stream
docker inspect --format '{{.Name}} {{.State.OOMKilled}}' \
  anime-qqbot-worker-1 anime-qqbot-astrbot-1 anime-qqbot-napcat-1
```

**提交**

```text
test: gate card rendering for 2g deployment
```

## 10. 分片六：版本、文档、全量验收与真实群 canary

演示终点：v0.4.0 自动化证据闭环，部署者能按既有 ACR 路径发布，并在 QQ 手机/桌面端
完成明确外部门禁。

### 任务 19：更新 v0.4.0 版本、帮助与运维文档

**文件**

- 修改：`pyproject.toml`
- 修改：`astrbot_plugin_anime_tracking/metadata.yaml`
- 修改：`README.md`
- 新建：`docs/acceptance/v0.4.0.md`
- 新建：`tests/acceptance/test_v04_documentation.py`

**失败测试**

1. Core、插件 metadata 和 README 版本一致为 `0.4.0`。
2. README 明确三个图片场景、文本场景、无占位图、本地只读命令路径和后台预热。
3. 运维文档包含：
   card-assets 检查、字体烟测、缓存量、Worker 预热日志、文本降级诊断和紧急关闭开关。
4. 发布命令继续使用既有服务器路径与脚本：
   `/opt/anime-qqbot/scripts/deploy-acr.sh`。
5. 文档明确 routine deploy 不使用 `--refresh-vendors`，并要求检查
   `NapCat restart detected: no`。
6. QQ canary 被标记为 `external_gate`，未执行时不得写“全部完成”。

**实现**

1. 版本更新放在功能与自动化通过之后，避免中间提交错误宣称完成。
2. 验收报告先填写自动化证据，外部门禁保留待执行项和实测位置。
3. 不写入真实 QQ 号、服务器 IP、Token 或数据库密码。

**验证**

```bash
.venv/bin/pytest tests/acceptance/test_v04_documentation.py
.venv/bin/ruff check .
git diff --check
```

**提交**

```text
docs: prepare v0.4.0 card presentation release
```

### 任务 20：运行全量本地、数据库、Compose 与真实镜像门禁

**文件**

- 只在失败证明属于本轮回归时修改对应实现或测试文件
- 更新：`docs/acceptance/v0.4.0.md`

**自动化门禁**

```bash
UV_CACHE_DIR=.uv-cache .venv/bin/uv lock --check
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy src

docker compose -f compose.test.yaml up -d --wait
TEST_DATABASE_URL=postgresql+asyncpg://anime:anime@127.0.0.1:55432/anime_test \
DATABASE_URL=postgresql+asyncpg://anime:anime@127.0.0.1:55432/anime_test \
  .venv/bin/pytest

docker compose config --quiet
docker compose -f compose.yaml -f compose.server-2g.yaml config --quiet
docker build -t anime-qqbot:v0.4.0-rc .
docker run --rm --entrypoint python anime-qqbot:v0.4.0-rc \
  -m anime_qqbot.entrypoints.card_smoke
docker run --rm --entrypoint python anime-qqbot:v0.4.0-rc \
  -m anime_qqbot.entrypoints.card_benchmark --json
```

**必须记录**

1. `pytest` passed 数量与耗时。
2. Ruff、mypy、lock 与 Compose 结果。
3. 实际镜像 ID、基础版本、字体路径和样卡烟测结果。
4. 首次渲染、缓存命中、峰值 RSS delta 和并发观测值。
5. 2 GiB 容器内存、OOMKilled、宿主可用内存与 swap 变化。
6. card-assets 超限回收结果。
7. NapCat 发布前后指纹。

**失败处理**

1. 只修复可复现且属于本轮的失败。
2. 不通过删除、跳过或放宽现有测试获得绿灯。
3. 外部网络、ACR 控制台或真实 QQ 未执行要标记 `external_gate`，不能归类为 passed。
4. 与本轮无关的既有失败标记 `excluded` 并保存命令和原因，不顺手扩大范围。

**提交**

```text
test: close automated v0.4.0 release gates
```

### 任务 21：通过 ACR 发布并执行 QQ 测试群外部门禁

本任务需要部署者拥有 ACR、服务器和 QQ 测试群权限，实施 Agent 不得伪造结果。

**部署前**

```bash
cd /opt/anime-qqbot
docker compose ps
docker compose ps -a -q napcat
docker inspect --format '{{.Id}}|{{.State.StartedAt}}' \
  "$(docker compose ps -a -q napcat)"
docker volume ls | rg anime-qqbot
```

**发布**

1. 在 ACR 确认 v0.4.0 镜像构建成功并记录 digest。
2. 服务器 `.env` 保持：
   `COMPOSE_FILE=compose.yaml:compose.server-2g.yaml`。
3. routine release 执行：

```bash
cd /opt/anime-qqbot
./scripts/deploy-acr.sh
```

4. 不使用 `--refresh-vendors`；检查脚本输出：

```text
NapCat restart detected: no
```

5. 检查 Worker/AstrBot、共享卷和预热：

```bash
docker compose ps
docker compose logs --tail=200 worker astrbot
docker compose exec -T worker sh -c \
  'find /var/lib/anime-qqbot/cards -maxdepth 3 -type f | head'
docker compose exec -T astrbot sh -c \
  'test -d /var/lib/anime-qqbot/cards && echo card-assets-readable'
docker stats --no-stream
free -m
swapon --show
```

**测试群矩阵**

在同一测试群选择一个 confirmed 且已有本地真实海报的非 NSFW 条目：

```text
/番剧 搜索 <唯一命中名称>
@机器人 详情 <名称>
@机器人 下一集 <名称>
```

逐项确认：

1. 只收到一条回复；
2. 包含一张普通横图和最多一行提示；
3. 手机 QQ 与桌面 QQ 中图片均非巨幅长图；
4. 海报完整、无拉伸，标题、时间轨和来源标签可读；
5. 时间符合群时区，字段缺失时没有 `None` 或空标签。

再验证文本场景：

```text
今日番剧
本周番剧
/番剧 季度
/番剧 我的订阅
/番剧 帮助
```

确认保持结构化文本，没有图片。

最后选择一个没有本地海报或人为移除测试缓存的非 NSFW 条目：

```text
@机器人 详情 <无海报条目>
```

确认收到包含标题、下一集、评分、总集数和来源中所有可用字段的文本，且没有占位图。

**发布后稳定性**

1. 观察至少一个 Worker 扫描周期和一次卡片缓存命中。
2. 检查 Worker/AstrBot 无 restart loop、OOMKilled 或持续 swap 抖动。
3. 再次记录 NapCat 指纹，必须与部署前完全相同。
4. 将手机/桌面结论、时间、镜像 digest、资源值与问题写入
   `docs/acceptance/v0.4.0.md`，不得提交真实 QQ 标识。

**完成提交**

```text
docs: record v0.4.0 production canary
```

## 11. 回滚策略

### 11.1 图片功能紧急关闭

1. 在 AstrBot 插件配置中关闭 `card_presentation_enabled`。
2. 重启 AstrBot 使配置生效；查询立即恢复全量结构化文本。
3. 不删除 card-assets，不重启 NapCat，不回滚数据库。

### 11.2 应用镜像回滚

使用现有部署脚本保存的 `anime-qqbot:rollback` 恢复 Worker/AstrBot。回滚不得删除命名卷，
不得使用 `docker compose down -v`。

### 11.3 派生缓存修复

card-assets 不含业务事实。确认目标卷后可以只清理其中损坏的 poster/render 子目录，再由
Worker 预热重建；不得把清理命令扩展到项目根、Docker 全局卷或其他服务。

## 12. 最终验收状态分类

验收报告必须按以下四类记录，不能用一个总勾选框掩盖外部条件：

- `passed`：本轮实际运行且有输出证据；
- `failed`：本轮运行失败，必须修复或明确停止发布；
- `external_gate`：需要 ACR、服务器、手机/桌面 QQ 或真实群权限，尚未由部署者执行；
- `excluded`：已证明与本轮无关的既有问题，附命令、现象和理由。

在任务 21 的 QQ 客户端与 NapCat 指纹门禁完成前，v0.4.0 最多只能称为“自动化就绪”，
不得宣称生产验收完成。

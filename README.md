# 市场部 AI 知识库（本地开发）

企业入职考核项目：管理员维护部门资料，员工通过 AI 助手查询有来源的答案。
当前进度：T01 模拟语料与冻结基线、T02 应用/数据库/登录权限基础、T03 管理员 xlsx/docx 上传/解析/持久任务、T04 发布/取消/删除、T05 精确记录与中文全文检索已由经理接收；T06 问答/个人会话/来源校验已本地交付，等待经理复核（仅 L 层，未做真实模型验证）。
未实现：真实 DeepSeek 接通验证（R）、PDF/图片/OCR（T07）、前端页面（T08）与部署（T10）。

## 目录

- `backend/`：FastAPI 应用、Alembic 迁移、测试
  - `src/mktkb/`：`config.py`（配置）、`db.py`（数据库/迁移）、`errors.py`（稳定错误）、`auth/`（账号与会话）、`documents/`（逻辑文件/版本/上传/预览/原件/发布/取消/删除）、`ingestion/`（持久任务/worker/解析器）、`retrieval/`（分词/索引/精确与正文检索）、`providers/`（模型网关类型与 DeepSeek 文本适配）、`conversations/`（个人会话/问答编排/请求幂等/提交事务）、`sources/`（消息引用来源与受保护原件）、`main.py`（应用工厂）
  - `migrations/`：Alembic 迁移（`0001_auth` 账号与会话；`0002_documents` 资料/版本/来源单元/任务；`0003_lifecycle` 发布/删除/版本状态；`0004_retrieval` 检索索引与复合归属约束；`0005_conversations` 会话/消息/请求/来源引用）
  - `tests/`：`acceptance/`（T01 语料检查）、`unit/`（T03 解析器、T05 分词/字段/输入边界、T06 意图/模型协议）、`integration/`（T02 登录/迁移，T03 上传/预览/worker，T04 生命周期，T05 检索/索引完整性/并发，T06 会话/六类结果/提交竞态/来源/恢复/升级）
- `fixtures/acceptance/`：冻结的模拟语料（只读，勿改）
- `tools/`：语料生成与字体链路探针（T01）
- `docs/`：需求、技术方案、契约、验收矩阵、任务单、开发证据

## 环境

- Windows 本地开发：Python 3.12.7，项目虚拟环境 `.venv`
- 依赖：`backend/requirements.lock`（生产）、`backend/requirements-dev.lock`（开发，含测试）

```powershell
Set-Location -LiteralPath 'D:\GPT项目\市场部AI知识库'
.\.venv\Scripts\python.exe -B -m pip install -r backend\requirements-dev.lock
.\.venv\Scripts\python.exe -B -m pip install --no-deps -e backend
```

## 日常启动（一键）

双击项目根目录的 `一键启动.cmd`：自动启动本机后端、前台页面与文件自动处理线程，并打开浏览器；窗口内按回车或 Ctrl+C 停止整套服务。详见 `一键启动-使用说明.md`。手工分窗口启动方式仍可按下文“初始化与迁移”“单次处理 worker”执行。

## 配置

复制 `.env.example` 为 `.env` 并填写**本地**模拟值；变量前缀 `MKTKB_`。真实部署密码不在本步交付。

| 变量 | 说明 |
| --- | --- |
| `MKTKB_DATA_DIR` | 数据目录（SQLite 文件所在），默认 `var` |
| `MKTKB_DATABASE_URL` | 可选，显式 SQLite URL；缺省用 `<data_dir>/mktkb.sqlite3` |
| `MKTKB_STORAGE_DIR` | 可选，原件/暂存根目录；缺省 `<data_dir>/storage`，不作为静态目录挂载 |
| `MKTKB_CSRF_SECRET` | CSRF 派生密钥，至少 16 字符（无默认值） |
| `MKTKB_ADMIN_PASSWORD` / `MKTKB_EMPLOYEE_PASSWORD` | 预置账号初始密码，8–72 字节（无默认值） |
| `MKTKB_TRUSTED_ORIGINS` | 受信任 Origin，支持三种写法：单个 `http://127.0.0.1:8077`、逗号分隔多个、JSON 数组字符串；不接受 `*`、`null`、无 scheme/主机或带路径的来源 |
| `MKTKB_COOKIE_SECURE` | HTTPS 生产置 `true`；本地 HTTP 开发可置 `false` |
| `MKTKB_SESSION_TTL_SECONDS` | 登录会话有效期，默认 8 小时 |
| `MKTKB_MAX_UPLOAD_BYTES` | 单文件字节上限，默认 `20971520`（20 MB） |
| `MKTKB_EXCEL_MAX_DATA_ROWS` | 单文件跨可见工作表有效数据行上限，默认 `5000` |
| `MKTKB_JOB_LEASE_SECONDS` / `MKTKB_JOB_LEASE_RENEW_SECONDS` | worker 租约秒数与续期周期，默认 `120` / `30` |
| `MKTKB_MODEL_BASE_URL` / `MKTKB_MODEL_NAME` / `MKTKB_MODEL_API_KEY` | T06 服务端模型配置（三项必须同时提供）；示例密钥留空，不提交真实凭据。未配置时问答返回 `MODEL_NOT_CONFIGURED`，其余接口照常 |
| `MKTKB_MODEL_REQUEST_TIMEOUT_SECONDS` | 单次模型 HTTP 超时上限，默认 `30` 秒；总体问答预算固定 60 秒 |

OOXML 解压资源预算（成员数/解压总量/单成员/压缩比）默认 `2000` / `134217728` / `67108864` / `100`，可通过同名 `MKTKB_OOXML_*` 变量调整；默认值依据见 `docs/evidence/T03/import-foundation-report.md`。

## 初始化与迁移

全新目录（没有 `var/`）必须先创建数据目录，否则迁移会报 `unable to open database file`：

```powershell
# 0) 准备数据目录（全新目录必做；已存在时该命令无副作用）
New-Item -ItemType Directory -Force -Path var | Out-Null

# 1) 迁移到 head（空库即建表；重复执行不破坏数据）
.\.venv\Scripts\python.exe -B -c "from mktkb.db import run_migrations; run_migrations('sqlite:///var/mktkb.sqlite3')"

# 2) 单独执行账号初始化（幂等：只补缺失账号，不重置已有密码）
@'
from mktkb.auth.service import bootstrap_accounts
from mktkb.config import Settings
from mktkb.db import Database

settings = Settings()
database = Database(settings.resolved_database_url())
with database.session_scope() as session:
    created = bootstrap_accounts(
        session,
        admin_username=settings.admin_username,
        admin_password=settings.admin_password,
        admin_display_name=settings.admin_display_name,
        employee_username=settings.employee_username,
        employee_password=settings.employee_password,
        employee_display_name=settings.employee_display_name,
        rounds=settings.bcrypt_rounds,
    )
print("created:", created)
'@ | .\.venv\Scripts\python.exe -B -

# 3) 应用工厂检查（也可直接启动）；create_app 默认会再跑一次幂等迁移与账号初始化
.\.venv\Scripts\python.exe -B -c "from mktkb.main import create_app; print(sorted(create_app().openapi()['paths']))"

# 4) 本地启动（可选，需自行停止）
.\.venv\Scripts\python.exe -B -m uvicorn mktkb.main:create_app --factory --host 127.0.0.1 --port 8077
```

## 单次处理 worker（不常驻）

上传只建立 `queued` 任务；处理由独立 worker 领取。本步提供“处理一个任务后退出”的单次入口，不启动后台常驻服务：

```powershell
# 处理一个待处理任务；--storage-dir 必须与创建任务时一致
.\.venv\Scripts\python.exe -B -m mktkb.ingestion.worker `
  --database-url "sqlite:///var/mktkb.sqlite3" `
  --storage-dir var\storage
```

- 输出一行 JSON：`job_id/state/units_written/units_reused/total_pages/error_code`。
- 成功时任务 `succeeded`、版本 `review_required`；本步**从不发布**、不切换有效版本。
- 中途退出后，租约到期（默认 120 秒）可由新进程恢复；已保存检查点不重复写入。
- `--max-units N` 仅用于有界测试：处理 N 个来源单元后保存检查点并退出，不是业务接口。

## 检查

pytest 的 `--basetemp` 只创建最后一级目录，因此首次运行前需创建父目录：

```powershell
New-Item -ItemType Directory -Force -Path backend\.pytest-tmp | Out-Null

.\.venv\Scripts\python.exe -B -m pytest backend/tests/unit backend/tests/integration -q -p no:cacheprovider --basetemp backend\.pytest-tmp\t03-local
.\.venv\Scripts\python.exe -B -m pytest backend/tests/acceptance/test_corpus.py -q -p no:cacheprovider --basetemp backend\.pytest-tmp\corpus
.\.venv\Scripts\python.exe -B -m pip check
```

`--basetemp` 必须指向本步骤专用的全新目录（pytest 会清理该目录），不要指向 `fixtures/` 或已有证据目录。

## 接口

### T02（已通过）

| 方法 | 路径 | 行为 |
| --- | --- | --- |
| POST | `/api/v1/auth/login` | 校验受信任 Origin；成功 200 `{user, csrf_token}` 并设置 Cookie |
| GET | `/api/v1/auth/me` | 登录有效返回 `{user, csrf_token}`；未登录/过期/撤销 401 |
| POST | `/api/v1/auth/logout` | 校验 Origin + `X-CSRF-Token`，撤销当前会话，204（重复退出仍 204） |
| GET | `/api/v1/healthz` | `{"status":"ok"}` |

### T03（本步，全部管理员；写操作另需受信任 Origin + 会话 CSRF）

| 方法 | 路径 | 行为 |
| --- | --- | --- |
| POST | `/api/v1/documents` | multipart 上传 `.xlsx/.docx`；`allow_same_name` 显式允许同名独立资料；202 `{document, version, job}` |
| GET | `/api/v1/documents` | 分页列表（`q/file_type/state/offset/limit`），分别返回 `active_version`/`latest_version` |
| GET | `/api/v1/documents/{document_id}` | 资料元信息与版本摘要（不返回提取正文） |
| POST | `/api/v1/documents/{document_id}/versions` | 追加版本（`expected_active_version_id` 可选）；202，旧版仍保留 |
| GET | `/api/v1/jobs/{job_id}` | 任务状态与进度、错误与可重试标志 |
| POST | `/api/v1/jobs/{job_id}/retry` | 合法失败任务重新排队（复用同字节检查点）；运行中 409 |
| GET | `/api/v1/documents/{document_id}/versions/{version_id}/preview` | 分页来源单元 + 完整处理/工作表摘要；可按 `sheet` 过滤 |
| GET | `/api/v1/documents/{document_id}/versions/{version_id}/file` | 管理员受保护原件；不接受客户端服务器路径 |

错误统一为 `{error:{code,message,retryable,details}, request_id}`；角色与写保护由服务端依赖执行。
本步仅接收 `.xlsx/.docx`；PDF/图片返回稳定的 `415 UNSUPPORTED_FILE_TYPE`。

### T04（本步，全部管理员；写操作另需受信任 Origin + 会话 CSRF）

| 方法 | 路径 | 行为 |
| --- | --- | --- |
| GET | `/api/v1/documents/{document_id}` | 保留 `document`/`versions`，顶层新增 `revision`（读取时的全库知识库版本，供发布/删除前置条件） |
| POST | `/api/v1/documents/{document_id}/versions/{version_id}/publish` | JSON `{expected_active_version_id, expected_revision}`；200 `{document_id, active_version_id, revision, published_at}`；旧有效版转 superseded，revision 只加 1 |
| POST | `/api/v1/documents/{document_id}/versions/{version_id}/cancel` | 无请求体；204。仅取消未生效版本及其任务，保留旧有效版；published/superseded 返回 409 |
| DELETE | `/api/v1/documents/{document_id}?expected_revision=N` | 200 `{document_id, deleted:true, revision}`；首次逻辑删除 revision+1，撤销全部内容访问并取消未完成任务；重复删除返回原结果 |

发布要求版本为 `review_required`、任务成功、处理报告 `quality.complete` 为 true 且单元/检查点一致；
冲突返回 409 `PUBLISH_CONFLICT` / `VERSION_NOT_PUBLISHABLE` / `DELETE_CONFLICT` / `VERSION_NOT_CANCELLABLE`；
已删除资料的内容与发布/取消返回 410 `CONTENT_UNAVAILABLE`。删除后默认列表排除，详情仅保留元信息，
提取内容/摘要/原件不可再读；旧来源单元与原件保留供后续受控清理（本步不启动常驻清理服务）。

### T05（已由经理接收；无新增 HTTP 路由）

检索以服务函数提供，供 T06 消费，不新增公开路由：

- `mktkb.retrieval.service.retrieve(db, QueryIntent(...), *, revision, limit=20) -> EvidenceSet`：
  当前有效资料的精确记录检索（门店/物品/标识、别名与 1～2 字短词、电话/编号原值）与中文正文检索；
  `entity_filters` 只接受 `store/item/store_id/item_id`，`requested_fields` 是业务字段标签而非 SQL 列；
  返回真实 SourceUnit、定位、候选总数（record 按逻辑实体、document 按来源单元）与
  `matches/ambiguous/conflict/none`；索引未就绪抛 `IndexNotReady`，revision 过时抛
  `KnowledgeRevisionChanged`（都不当作 none）。
- **一致短读快照**：`retrieve` 在独立数据库连接上显式 `BEGIN`，revision、就绪判断、字段/别名/短词/FTS
  召回、候选/冲突计数与最终来源读取处于同一数据库级短读快照；不提交或回滚调用方 Session，也不复用
  其 ORM 缓存。查询中途发生发布/删除时，只返回请求 revision 下的完整旧快照，或明确抛
  `KnowledgeRevisionChanged`；不会返回“旧 revision + 新事实/假 none”。回答最终提交的 revision 重检仍属 T06。
- **真实索引完整性**：prepare 完成判定、发布事务内核对与有效版本检索就绪共用同一套真实行核对：
  ready marker + SourceUnit + 单元映射 + FTS 正文 + 字段索引逐项对应；缺行、额外/错归属、
  同数量错内容都会拒绝发布（409 `VERSION_NOT_PUBLISHABLE`）或使检索抛 `IndexNotReady`。
  FTS 表缺失/故障不是 none；分词与全量构建仍在发布写事务之外。
- **复合归属**：`0004_retrieval` 为 `source_units(id,version_id,document_id)` 与
  `document_versions(id,document_id)` 增加父唯一索引，检索表用复合外键绑定该关系；服务查询同时
  关联 SourceUnit 归属。跨 document/version 的伪造索引组合会被数据库约束拒绝，或在检索时按索引
  异常处理，不会召回另一资料名下的单元；外键保持启用。
- **显式重建/回填**：损坏样本不会被自动静默修复。发布返回 409 或检索抛出 `IndexNotReady` 后，
  需先显式重建索引，再发布一次；重复发布/回填保持幂等。正常发布流程仍在进入原子写事务前准备索引。
- 升级到 `0004_retrieval` 后，既有已发布资料需要显式回填一次（不在每次启动重建全库）：

```python
from mktkb.db import Database
from mktkb.retrieval.index import backfill_published_indexes, prepare_version_index

database = Database("sqlite:///var/mktkb.sqlite3")
with database.session() as session:
    statuses = backfill_published_indexes(session)  # 可重复执行，不重复单元/FTS 行
print([(str(item.version_id), item.ready, item.unit_count) for item in statuses])
database.dispose()
```

- `0004_retrieval` 尚未部署；本轮不提供“已部署旧 0004 结构”的在线升级。已有旧结构库不能仅执行
  `upgrade head` 就宣称复合约束已生效；应在全新空库或保留的 `0003_lifecycle` 真实快照副本上升级，
  再显式回填。正常发布/删除/取消后的旧索引与原件仍物理保留，本阶段不启动清理服务。
- 中文分词使用 jieba 0.42.1（本地词典、不联网、不写 jieba 缓存文件）；入库与查询共用同一规则版本，
  正文同时索引 jieba 词与汉字二元组；FTS 表达式只由安全引号包裹的 token 组成，用户输入不成为运算符。
- 旧索引可物理保留，但替换/删行/取消/删除后立即不可见；检索不提供问答、会话、员工来源入口或前端。

### T06（本地交付，待经理复核；L 层，不含真实模型验证）

公开前缀仍为 `/api/v1`，新增且仅新增契约规定的 7 个操作；本人会话对 admin/employee 都适用，
管理员没有他人会话特权；写操作复用受信任 Origin + 会话 CSRF：

| 方法与路径 | 说明 |
| --- | --- |
| `POST /conversations` | 201 `{id,title,created_at}`，属于当前用户 |
| `GET /conversations` | 分页列出本人会话（默认 limit=20，上限 100） |
| `GET /conversations/{id}/messages` | 本人消息及来源摘要（实时 active/superseded/deleted） |
| `POST /conversations/{id}/messages` | `{client_request_id, question}` → 200 六类 `AskResult` |
| `DELETE /conversations/{id}` | 204，逻辑删除并使未完成请求失效；重复删除仍 204 |
| `GET /messages/{message_id}/sources/{source_id}` | 本人消息引用详情；失效来源 410 仅元信息 |
| `GET /messages/{message_id}/sources/{source_id}/file` | 受保护原件；`no-store`/`nosniff` |

- **六类结果统一 200**：`answer / clarification / not_found / conflict / service_error / knowledge_changed`；
  权限 403、未知资源 404、校验 422、处理中 409 `QUESTION_IN_PROGRESS`、同 ID 不同载荷 409
  `REQUEST_PAYLOAD_MISMATCH`、过载 503 保留 HTTP 错误。
- **持久幂等**：`conversation_requests` 上 `(conversation_id, client_request_id)` 唯一，
  `status='running'` 上另有部分唯一索引保证每会话最多一个处理中请求；同 ID 同载荷重放既有结果，
  不新增消息或模型调用；持久截止时间可回收崩溃遗留的 running，旧 attempt 的迟到结果被 fencing 拒绝。
- **提交事务**：领取 → 独立读 revision/上下文 → 检索 → 事务外模型 await → 同一个短
  `BEGIN IMMEDIATE` 写事务重检 revision、请求 attempt、会话所有者/未删除与所有引用有效性 →
  原子保存结果/消息/引用。资料在问答期间变化（含无关资料）返回 `knowledge_changed`，不保存旧事实。
- **模型适配**：只实现 DeepSeek 官方非流式 Chat Completions 文本协议，地址/模型/密钥只来自服务端配置；
  最多一次 `query_expansion` + 一次 `answer`，总预算 60 秒，不自动重发；密钥不进响应/日志/异常/OpenAPI。
- **来源**：先校验当前用户拥有 message 所属未删除会话、source_id 确为该消息引用，再核对
  SourceUnit/version/document 归属与当前有效性；同字节重导入不会恢复旧链接。
- 迁移 head 为 `0005_conversations`；`0004` 真实快照升级、旧表行值/原件/revision/索引保护见
  `docs/evidence/T06/qa-report.md`。本地用可控模型与 HTTP 模拟验证，**不代表真实 DeepSeek 已接通**。

```powershell
# T06 定向自测（真实上传/worker/发布 + 可控模型；不使用真实模型/OCR）
.\.venv\Scripts\python.exe -B -m pytest backend/tests/unit/test_conversations.py backend/tests/unit/test_deepseek.py `
  backend/tests/integration/test_chat.py backend/tests/integration/test_source_access.py `
  backend/tests/integration/test_answer_commit.py backend/tests/integration/test_conversation_recovery.py `
  -q -p no:cacheprovider --basetemp='docs\evidence\T06\tmp\<唯一批次>-targeted'
```

## 限制

- 仅本地 L 层检查：未做浏览器验收、真实 OCR/模型、Ubuntu 或部署检查；无前端页面。
- T06 为本地交付、尚未经理复核：模型均为测试内可控替身或 HTTP 模拟，**未调用真实 DeepSeek**，
  未读取密钥；Q29～Q40、完整 B0、PDF/图片/OCR 场景仍留 T07/T09。真实接通与产品验收关口未关闭。
- T05 已由经理接收；`0004_retrieval` 尚未部署，不提供已部署旧 0004 结构的在线升级保证；损坏索引需
  显式重建/回填，不存在自动清理服务。
- 未做真实 50 文件/10000 记录/3 人并发负载验收；20 MB 与 5000 行是单文件规则上限，不是容量承诺。
- T01 语料只读，测试不导入冻结语料作为验收数据源；本轮未重新生成语料或字体。

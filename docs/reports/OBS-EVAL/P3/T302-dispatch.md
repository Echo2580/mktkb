# T302 开发交接提示词（只读运营接口和权限）

> 使用方法：把本文件全文复制粘贴给开发窗口的开发助手，作为唯一任务指令。本文件自包含，开发助手不需要其他对话上下文。
> 派单人：项目经理。派单日期：2026-11-22。前置任务 T301 已验收 PASS，D5 已由主人裁决（查询侧排除）。

---

## 0. 你的角色与铁律

你是开发执行者，本次**只做 T302：只读运营接口和权限**。不做 T303 及之后的任何前端页面，不安装 echarts，不发起评测任务。

铁律（违反任何一条即验收 FAIL）：

1. 工作目录固定为 `D:\GPT项目\市场部AI知识库`。系统是 Windows，shell 是 PowerShell 7（pwsh），**Bash 不可用**。命令分隔用 `;` 或 `&&`，路径用反斜杠，环境变量用 `$env:NAME`。
2. Python 一律用仓库根虚拟环境：`D:\GPT项目\市场部AI知识库\.venv\Scripts\python.exe`。后端 pytest 必须在 `backend\` 目录下以 `..\.venv\Scripts\python.exe -B -m pytest` 开头接具体测试路径（pytest 的 testpaths/pythonpath 配置在 `backend\pyproject.toml`，禁止从仓库根裸跑 pytest）。
3. **禁止任何付费调用**：不调真实模型、不调 OCR、不调 Ragas 裁判。测试一律离线 + 受控替身网关（Mock），证据中标注 `Mock`。
4. **禁止写 `var\` 下的业务库与 Trace 库**。所有测试数据在 pytest tmp_path 或你自己的隔离目录中生成。
5. **禁止 git 写操作**：不 add、不 commit、不 checkout、不 reset、不 stash、不 clean。改动留在工作区，由项目经理验收。git 只允许 log / status / show / diff / rev-parse。
6. 工作区已有在途改动（`.claude\handoffs\_index.md`、`docs\reports\OBS-EVAL\P2\T207-QUALITY-REPAIR\manager.md`）和大量未跟踪 P2 证据，**全部原样保留，不读不改不移动不删除**。
7. 发现任务书、T301 冻结口径与实际代码冲突时：**停下，把冲突写进交付说明的「上报事项」，等项目经理裁决**。不得擅自改任务书、T301 交付物或冻结口径。
8. 响应体和测试证据中禁止出现：密钥、原始请求头、Trace 原始属性（`attributes_json`、`*_json` 原文）、内部存储路径（`stored_path`）、SQL 语句、库文件路径。
9. 交付只认「变更清单 + 验证证据（命令、退出码、通过/失败/跳过数）+ 已知限制」，口头「已完成」无效。
10. 数字一律用阿拉伯数字。文档用 Markdown。

## 1. 开工前必读（按顺序读完再动手）

全部路径相对 `D:\GPT项目\市场部AI知识库`：

1. `docs\superpowers\plans\2026-11-21-mktkb-p3-operations-taskbook.md` —— 重点读 T302 小节、§2 数据口径与权限、§4 推进和接收标准。这是开发与验收唯一依据。
2. `docs\reports\OBS-EVAL\P3\T301-data-audit.md` —— **口径已冻结，不得私改**。重点：§3 十二项指标口径表（来源/时间字段/去重键/过滤条件/空值语义）、§4 Span→阶段映射与 Trace 状态判定（4.7）、§5 评测批次白名单、§6 API 状态约定（6.1 时间窗口、6.2 已删除会话、6.3 冲突口径、6.7 约定字段）。
3. `docs\reports\OBS-EVAL\P3\T301-D5-decision.md` —— 主人裁决：冲突消息的持久引用行实际存在，但「最终引用」计数必须按 `kind='conflict'` 排除；不修提交链路。
4. `docs\reports\OBS-EVAL\P3\T301-isolated\T301-sample-matrix.md` 和 `T301-recomputation.md` —— 19 条样本（S01-S19）与独立复算预期值，T302 对账基准。
5. `docs\reports\OBS-EVAL\P3\T301-isolated\scripts\` 下的样本生成脚本（`t301_common.py`、`t301_generate_samples.py`）—— 可**复制思路到你自己的测试目录**复用，禁止在原目录重跑（会覆盖 T301 证据）。
6. 源码（只读，除 §2 允许的边界外不改）：
   - `backend\src\mktkb\main.py` —— 应用工厂与路由注册（182-194 行）。
   - `backend\src\mktkb\auth\routes.py` —— `get_db`、`get_current_user`、`require_role`（63 行）。管理员依赖写法参照 `observability\routes.py:50`：`admin_required = Depends(require_role("admin"))`。
   - `backend\src\mktkb\observability\routes.py` —— 现有 4 个只读监控端点；响应模型显式白名单写法、`degraded_reason` 语义、run 聚合与 holdout 扣留（838-886 行）都在这里，**优先复用，不要另造一套**。
   - `backend\src\mktkb\observability\store.py` —— `TraceRepository.list_by_request(request_id)`（234-242 行，按 attempt ASC 排序）。
   - `backend\src\mktkb\conversations\models.py` —— Conversation / ConversationMessage / ConversationRequest / MessageSource 表结构。
   - `backend\src\mktkb\documents\models.py` —— Document / DocumentVersion / SourceUnit / KnowledgeState。
   - `backend\src\mktkb\ingestion\models.py` —— ImportJob（状态、stage、error_code、attempts；租约字段不进运营摘要）。
   - `backend\src\mktkb\sources\service.py` —— 引用状态判定（99-105 行）与旧版引用可展示字段（147-167 行）。
   - `backend\src\mktkb\errors.py` —— `ApiError`、`NotFound` 错误信封。
7. `backend\tests\conftest.py` —— 现成 fixture：`settings`（tmp_path 隔离）、`app`、`client`、`admin_client`、`employee_client`、`second_employee_client`、`chat_model`（EvidenceEchoGateway 替身）、`chat_app`、`chat_admin`、`chat_employee`、`upload_document`、`write_headers`。**优先复用，不要重写登录/上传逻辑。**
8. `backend\tests\observability\test_routes.py`、`test_routes_security.py` —— 权限矩阵、OpenAPI 断言、不泄露断言的现成写法参照。

## 2. 交付物与文件边界

### 2.1 允许新增

| 位置 | 内容 |
| --- | --- |
| `backend\src\mktkb\operations\` | 新包：`__init__.py`、`schemas.py`（Pydantic 响应模型）、`queries.py`（共享查询层）、`routes.py`（6 个 GET 端点）。拆分可微调，但都在本包内。 |
| `backend\tests\operations\` | `__init__.py`、`conftest.py`（如需专用 fixture）、`test_*.py` 若干 |
| `docs\reports\OBS-EVAL\P3\T302-evidence\` | 全部证据：命令输出、openapi.json、对账表、交付说明 `T302-delivery.md` |

### 2.2 允许修改的现有文件（仅此 2 个，且改法固定）

1. `backend\src\mktkb\main.py` —— 只加 2 处：
   - import 区加一行：`from .operations.routes import router as operations_router`
   - 188 行 `api.include_router(observability_router)` 之后加一行：`api.include_router(operations_router)`
   - 其余任何行不动。
2. `frontend\src\api\schema.d.ts` —— **只允许由 OpenAPI 产物重新生成，禁止手写手改**（命令见 §6 步骤 10）。生成后 `frontend` 的 typecheck 必须通过；如果生成导致既有类型报错，停下上报，不要去改 `client.ts` 或其他前端源码。

### 2.3 禁止

- 改任何其他现有文件（包括任务书、T301 全部交付物、`package.json`、前端源码、P2 业务代码、`backend\pyproject.toml`）。
- 安装 echarts 或任何新 npm/pip 依赖。`openapi-typescript` 已在 devDependencies 中；若 `frontend\node_modules` 不存在，允许执行 1 次 `npm.cmd ci` 恢复依赖并记录，此外不得动依赖。
- 数据库索引迁移：T302 基于现有表查询，索引由 T306 实测查询计划后再定。
- 写 `var\`、git 写操作、真实外部调用（见 §0）。

## 3. 接口契约（6 个端点，全部 GET，全部 admin）

路由前缀 `/api/v1/operations`（包内 router 用 `prefix="/operations"`，经 main.py 的 `/api/v1` 聚合）。权限依赖统一：

```python
from ..auth.routes import require_role
admin_required = Depends(require_role("admin"))
```

错误信封沿用 `mktkb.errors`（`ApiError` / `NotFound`），参数非法返回 422 + 错误码（如 `INVALID_WINDOW`），不回显提交值；未登录 401、员工 403 由 `require_role` 现有行为提供，不要自造。

### 3.0 公共时间窗口（所有带窗口的端点共用同一实现）

- 参数：`window=today|7d|30d`（默认 `7d`）或 `since=YYYY-MM-DD&until=YYYY-MM-DD`（自定义，Asia/Shanghai 日历日，until 含当天）。
- 转换：日历日 → **左闭右开 UTC 窗口** `[start_utc, end_utc)`，用 `zoneinfo.ZoneInfo("Asia/Shanghai")`。近 7 天含今天。
- 自定义窗口超过 90 天：422 `INVALID_WINDOW`。since > until：422。
- 响应统一携带：`window`（preset 名或 `custom`）、`since_utc`、`until_utc`（ISO 8601）、`timezone: "Asia/Shanghai"`。
- **统计与下钻必须走同一个共享过滤函数**（放 `queries.py`），禁止两处各写一套条件。

### 3.1 `GET /operations/overview`

响应字段（命名遵循 T301 审计 §6.7，扩展字段须在交付说明中登记）：

- `window` 块（见 3.0）。
- `metrics`：
  - `completed_requests`：窗口内已完成问答量。口径 = 审计 §3 #1：`conversation_requests.status='succeeded'` 且 `result_message_id` 非空，按 `finished_at` 落窗，按请求 ID 去重，排除 `conversations.deleted_at IS NOT NULL`。幂等重放不加量（同一请求行天然不重复）。
  - `not_found` / `conflict`：六类中对应结果计数（结果类型取结果消息 `kind`）。
  - `interrupted`：未提交中断单列（status ∈ running/failed/cancelled/expired），**不入六类分布**。
  - `review_required_versions`：待审核版本数，**当前库存口径**（`document_versions.state='review_required'` 且资料未删除），响应中标注 `basis: "current"`，不随窗口回溯。
  - `active_documents`：当前生效资料数（`deleted=False` 且 `active_version_id` 非空），同样 `basis: "current"`。
- `trend`：按日数组 `[{date: "YYYY-MM-DD", completed: n, citations: n}, ...]`（Asia/Shanghai 日历日；无数据日期不补零伪造，空窗口返回空数组）。
- `result_distribution`：六类固定键 `answer/clarification/not_found/conflict/service_error/knowledge_changed`，各计数；无样本类计 0。
- `trace_coverage`：`{covered, total, status}`。status ∈ `recorded|partial|not_recorded|disabled|unavailable`（判定按审计 §4.7）。分母 = 窗口内已完成请求；分子 = 有普通执行 Trace 的请求（`replayed=1` 纯重放不计）。Trace 关闭 → `disabled`，**不报覆盖率数值**（covered/total 置 null）；读失败 → `unavailable` 同样不报；0 < 分子 < 分母 → `partial`；分母 0 → 空样本语义。
- `pending`：待处理列表（异常问答 + 导入失败/阻断），每项带**下钻条件**：问答项 `{type: "request", request_id, kind, finished_at, drilldown: {date, kind}}`；导入项 `{type: "import", document_id, version_id, state, error_code, drilldown: {document_id, version_id, state}}`。失败原因缺失只给状态，不推测。
- 每个指标卡的下钻条件必须与统计条件完全一致（同窗口、同过滤）。

### 3.2 `GET /operations/requests`

- 参数：窗口（3.0）、`kind`（六类之一，可选）、`document_id` / `version_id`（可选，过滤引用了该文档/版本的问答）、`cursor`、`page_size`（默认 20，上限 100，超限 422）。
- 排序确定性：`finished_at DESC, request_id DESC`；游标 = 上一页末条的 `(finished_at, request_id)`（编码为不透明字符串），keyset 分页，**翻页无重复无漏项**。
- 文档/版本过滤口径（审计 §6.3）：正常回答按持久引用行匹配；**冲突消息按 `result_json.conflicts` 中的 document_id/version_id 匹配**，命中项带 `conflict_flag: true` 单独标注。已删除会话双侧排除。
- 每项字段（审计 §6.7 请求摘要）：`request_id`、`kind`、`status`、`finished_at`、`error_code`、`revision`、`trace_status`、`citation_count`（非冲突去重后）、`conflict_flag`。**不返回 conversation_id 原文**（如需标识用哈希）。列表不返回问题原文。
- 响应带 `next_cursor`（无下一页为 null）、`window` 块。

### 3.3 `GET /operations/requests/{request_id}`

- 仅使用服务端已关联记录；错误 ID / 已删除会话中的请求 → 404（`REQUEST_NOT_FOUND`），不区分「存在但无权」与「不存在」的响应细节。
- 返回：
  - `question`：原问题文本（管理员运营详情允许展示，任务书 T302 合同「返回问题及结果」）。
  - `result`：`{kind, text, error_code, missing_fields, revision}`（结果消息实际字段）。
  - `citations`：非冲突持久引用摘要数组，按「结果消息+文档」「结果消息+版本」去重后给出：`source_id`、`document_id`、`version_id`、`version_number`、`document_name`、`status`（active/superseded/deleted）、`published_at`；active 才带 `locator`；superseded/deleted 只给失效元信息（审计 §4.8），**不给正文、fields、原图、内部路径**。
  - `conflicts`：`kind='conflict'` 时从 `result_json.conflicts` 取两方来源分列（各带 document/version 标识与值、`conflict_flag: true`）；无持久行的历史冲突同样从这里取。**conflicts 不计入 citation_count。**
  - `trace`：`{status, attempts: [...]}`。status 按审计 §4.7 派生（recorded/not_recorded/disabled/unavailable/partial 不适用单请求时用前 4 种 + replayed 标注）。每个 attempt：`trace_id`、`attempt`、`replayed`、`path`、`outcome`、`spans`（白名单字段：`name`、`started_at`、`duration_ms`、`status`、`error_code`、`attribute_count`、`attribute_keys`——直接复用 `observability\routes.py` 的 `SpanSummary` 模型）。重放 attempt 显式 `replayed: true`。**禁止返回 attributes_json 或任何 *_json 原文。**
  - Trace 关闭时 `trace.status="disabled"`、attempts 空数组，**业务部分照常返回**；读失败 `"unavailable"` 同理。
- 阶段标签映射不在后端做，后端只回 Span 名；前端按 T301 §4 映射渲染（T304 的事，本任务不做）。

### 3.4 `GET /operations/documents`

- 参数：`file_type`（可选）、`version_state`（可选，现有枚举 queued/processing/review_required/failed/published/superseded/cancelled/deleted）、`processing_state`（可选，导入任务状态）、窗口（用于引用量）、分页（同 3.2 游标方式，排序 `document_id` 确定性即可）。
- 每项：`document_id`、`name`、`file_type`、`current_version`（`version_id`、`number`、`state`、`published_at`）、`latest_import`（`state`、`stage`、`error_code`、`attempts`；无任务为 null）、`final_citations`（所选窗口内**最终引用**去重计数：结果消息+文档去重，**排除 kind='conflict' 的消息**，排除已删除会话）、`related_requests_count`（相关问答数：含冲突来源，冲突按 result_json.conflicts 匹配）。
- `deleted=True` 的资料默认不出现在列表（库存口径）。

### 3.5 `GET /operations/documents/{document_id}`

- 404 语义同 3.3。返回：
  - `document`：基本字段（不含 stored_path）。
  - `versions`：全部版本数组（`version_id`、`number`、`state`、`uploaded_at`、`published_at`、失败原因），失败原因只回显 `import_jobs.error_code` 与可展示 `message`（若 message 含内部路径/堆栈则只回 error_code），**不回显 processing_report 原文与 stored_path**。
  - `imports`：各版本导入任务摘要（state/stage/error_code/attempts/retryable/finished_at；**租约字段 lease_* 不返回**）。
  - `drilldown`：`{requests_filter: {document_id, version_id 可选}}` —— 给前端按文档/版本打开 3.2 列表的条件。

### 3.6 `GET /operations/evaluation-runs`

- 无窗口参数（批次列表不按问答窗口过滤）。扫描 `settings.data_dir/eval/runs/` 下目录：
  - 有合法 `run_manifest.json` 的目录 → 输出白名单摘要（字段照抄审计 §5.1：run_id/mode/scope/suite/dataset_version/business_date/index_revision/created_at/case_count 等 + summary 的 scored_count/error_count/status_counts + gate 的 gate_status/quality_status + `holdout_detected`/`details_withheld`/`degraded_reason`）。**优先 import 复用 `observability\routes.py` 中现成的聚合函数与响应模型**；确需提取时保持字段白名单完全一致，禁止透传 JSON 原文。
  - 空目录 / 缺 manifest → 跳过该目录，不报错；在响应 `skipped` 计数或状态字段中体现（如 `p2-t209-b0-*` 3 个空目录）。
  - JSON 非法 → 该条目 `degraded_reason`（manifest_invalid/summary_invalid/gate_invalid），不整体 500。
  - holdout（suite=holdout 或 holdout_details=true）→ 只回聚合，`details_withheld=true`，**不读 cases.jsonl**。
  - 无任何可用批次 → `runs: []` + 状态字段（如 `status: "empty"`），200 不报错。
- 排序：`created_at DESC, run_id DESC` 确定性。
- 单批次详情**不新增端点**，复用现有 `GET /api/v1/observability/runs/{run_id}`。
- **P3 不发起评测**：本端点纯只读，不写任何 run 目录。

## 4. 实现步骤（按顺序做，每步跑一次测试再进下一步）

1. **步骤 1**：建 `operations` 包骨架 + 6 个端点空实现（返回最小合法响应）+ main.py 注册 2 行。跑 `tests\operations` 冒烟：admin 200、未登录 401、员工 403。
2. **步骤 2**：`queries.py` 实现公共窗口转换（3.0）+ 共享过滤（已完成/排除已删除会话/结果类型），写窗口边界测试（午夜、90 天上限、非法参数）。
3. **步骤 3**：overview 全量实现（3.1），trace_coverage 接 `TraceRepository`，关闭/读失败降级。
4. **步骤 4**：requests 列表（3.2），keyset 分页 + 文档/版本过滤（含冲突匹配）。
5. **步骤 5**：requests 详情（3.3），引用状态判定复用 `sources\service.py` 逻辑口径，冲突从 result_json 取，Trace attempts 复用 `list_by_request` + SpanSummary。
6. **步骤 6**：documents 列表 + 详情（3.4/3.5），最终引用排除 conflict，相关问答含冲突。
7. **步骤 7**：evaluation-runs（3.6），复用现有 run 聚合。
8. **步骤 8**：补齐 §5 全部测试清单，逐项勾掉。
9. **步骤 9**：用 T301 样本矩阵对账（§5.3），产出对账表写入 `T302-evidence\T302-reconciliation.md`。
10. **步骤 10**：导出 OpenAPI + 生成前端类型 + 前端 build（§6 命令 3-5）。
11. **步骤 11**：写 `T302-evidence\T302-delivery.md`（模板见 §8），整理证据，git status 终态快照对比开工快照，确认只动了 §2 允许的文件。

## 5. 测试清单（每条都要有对应测试函数，缺一条验收 FAIL）

### 5.1 数据合约测试（任务书 T302 第 1 项，7 条必做）

| # | 用例 | 要点 |
| --- | --- | --- |
| C1 | 午夜边界 | 固定 `finished_at` 于 Asia/Shanghai 日界前后（如 15:59:59Z / 16:00:00Z），归属日正确、左闭右开不重不漏 |
| C2 | 幂等重放 | 同 client_request_id 重放后 overview 计数不变；详情重放 attempt 带 replayed 标注；覆盖率分子不含纯重放 |
| C3 | 同文档重复引用 | 同一回答引用同一资料多行，文档维/版本维去重后各计 1 |
| C4 | 当前库存口径 | 待审核/生效资料不随窗口变化，`basis:"current"`；下钻同口径 |
| C5 | 空分母 | 窗口无数据：计数 0、趋势空数组、占比类返回空值/无样本状态而非 0% |
| C6 | 分页无重复漏项 | 构造 > page_size 条记录翻完全部页，request_id 集合与总数一致、无重复 |
| C7 | 超窗拒绝 | 自定义 91 天 → 422 INVALID_WINDOW；since>until → 422；page_size>100 → 422 |

### 5.2 权限与负例测试（任务书 T302 第 3 项）

| # | 用例 | 要点 |
| --- | --- | --- |
| S1 | 未登录直调 6 端点 | 全部 401 |
| S2 | 员工直调 6 端点 | 全部 403 |
| S3 | 已删除会话 | 其请求不出现在 overview 统计、requests 列表；直查详情 404 |
| S4 | 来源失效 | superseded/deleted 引用只回失效元信息，无正文/fields/路径 |
| S5 | 错误 ID | 非法 request_id/document_id → 404 或 422（按 _SAFE_ID 类校验），不 500 |
| S6 | 不泄露 | 遍历 6 端点正常与错误响应：无 `attributes_json`、`*_json` 原文、`stored_path`、`lease_token`、密钥、原始请求头（参照 `test_routes_security.py` 的断言写法） |
| S7 | OpenAPI | 6 条新路径全部仅 GET；`create_app(settings, initialize=False)` 不写数据目录（参照 `test_routes.py:717`） |

### 5.3 T301 样本对账（任务书 T302 接收条件，预期值不得改）

复用 T301 样本生成方式在**你自己的 tmp 隔离环境**重建 S01-S19（复制脚本思路，不在 T301 原目录跑），通过 API 断言：

| 口径 | 预期值（来自 T301-recomputation.md） |
| --- | --- |
| 已完成问答量 | 13 |
| 六类分布 | answer 8 / clarification 1 / not_found 1 / conflict 1 / service_error 1 / knowledge_changed 1 |
| 未提交中断单列 | 2（running / expired），不入六类 |
| 非冲突持久引用行 | 13 |
| 文档维去重对 / 版本维去重对 | 6 / 6 |
| 待审核版本 | 1 |
| 失败导入 | 1，error_code=PARSE_INCOMPLETE |
| Trace 覆盖率 | 10/13，status=partial；纯重放 1 不计、关闭 1、未记录 2 |
| 午夜归属 | S17 → 2026-11-20；S18 → 2026-11-21 |
| 已删除会话 | S10 统计与明细双侧排除 |
| D5 冲突 | S05 持久引用行存在（2 行），但 final_citations / citation_count 不含它们；requests 按文档过滤命中 S05 且 conflict_flag=true |
| 统计=下钻 | overview 每个计数与对应条件下 requests / documents 列表总数逐项相等 |

### 5.4 Trace 状态测试

- T-a：`trace_enabled=False` 时 overview/详情业务数据照常返回，coverage status=disabled 且无数值，详情 trace.status=disabled。
- T-b：仓储读失败（可注入坏路径/替身抛 TraceWriteError）→ unavailable，不报覆盖率，不 500。
- T-c：有请求无 Trace 行 → 详情 not_recorded；列表 trace_status 同口径。
- T-d：`recorded`/`partial` 区分正确（5.3 已覆盖 partial）。

### 5.5 评测批次测试

- E-a：构造受控 run 目录（tmp 下手工放 manifest/summary/gate 三份 JSON，标注受控样本）→ 列表返回白名单摘要，字段与现有 run 端点一致。
- E-b：受控 holdout manifest（suite=holdout）→ details_withheld=true，响应无逐题内容。
- E-c：空目录混入 → 跳过不报错；全部为空 → `runs: []` + 空状态，200。
- E-d：非法 JSON → 对应 degraded_reason，不 500。
- E-e：员工访问 → 403。
- E-f：对现有 `var\eval\runs\` **只读**对账（可选，若做则只读不改）：5 个有效批次 + 3 个空目录跳过，与审计 §5.3 清单一致。

## 6. 验证命令（照抄执行，逐条记录输出与退出码到 T302-evidence\）

```powershell
# 0. 开工快照（开工时执行 1 次，收工再执行 1 次对比）
git -C 'D:\GPT项目\市场部AI知识库' status --short | Out-File -Encoding utf8 'D:\GPT项目\市场部AI知识库\docs\reports\OBS-EVAL\P3\T302-evidence\git-status-start.txt'

# 1. 本任务测试（在 backend\ 目录下执行）
Set-Location 'D:\GPT项目\市场部AI知识库\backend'
..\.venv\Scripts\python.exe -B -m pytest tests/operations -v 2>&1 | Tee-Object -FilePath '..\docs\reports\OBS-EVAL\P3\T302-evidence\pytest-operations.txt'
$LASTEXITCODE   # 记录退出码

# 2. 定向回归（main.py 被改动，确认监控与鉴权无回归；同样在 backend\ 下）
..\.venv\Scripts\python.exe -B -m pytest tests/observability tests/integration/test_auth.py -v 2>&1 | Tee-Object -FilePath '..\docs\reports\OBS-EVAL\P3\T302-evidence\pytest-regression.txt'
$LASTEXITCODE

# 3. 导出 OpenAPI（在 backend\ 下；initialize=False 不写运行目录）
..\.venv\Scripts\python.exe -B -c "import json, pathlib; from mktkb.config import Settings; from mktkb.main import create_app; app = create_app(Settings(_env_file=None), initialize=False); p = pathlib.Path(r'..\docs\reports\OBS-EVAL\P3\T302-evidence\api\openapi.json'); p.parent.mkdir(parents=True, exist_ok=True); p.write_text(json.dumps(app.openapi(), ensure_ascii=False, indent=2), encoding='utf-8'); print('openapi written', p)"
# 注意：若 Settings 构造读到真实 .env 导致副作用，参照 tests\conftest.py 的 isolate_dotenv 做法在临时目录构造隔离 Settings；导出必须含 6 条 /api/v1/operations 路径。

# 4. 生成前端类型（在 frontend\ 下；不改 package.json）
Set-Location 'D:\GPT项目\市场部AI知识库\frontend'
npx.cmd openapi-typescript ..\docs\reports\OBS-EVAL\P3\T302-evidence\api\openapi.json -o src\api\schema.d.ts 2>&1 | Tee-Object -FilePath '..\docs\reports\OBS-EVAL\P3\T302-evidence\api-types-gen.txt'
$LASTEXITCODE

# 5. 前端构建（在 frontend\ 下）
npm.cmd run build 2>&1 | Tee-Object -FilePath '..\docs\reports\OBS-EVAL\P3\T302-evidence\frontend-build.txt'
$LASTEXITCODE
```

历史 OpenAPI 证据（`docs\evidence\T08\R1B\api\openapi.json`）**保留不动**；本次产物放 `T302-evidence\api\`。`package.json` 的 `api:types` 脚本指向旧路径，本任务**不改它**，用上面第 4 条命令显式传新路径。

## 7. 验收完成条件（项目经理逐项核对）

1. §5 测试清单全部有对应测试且通过；命令 1 退出码 0，记录通过/失败/跳过数。
2. T301 样本逐项对账一致（5.3 表），统计数字与下钻明细一致，对账表落盘。
3. 员工越权全部被拒；不泄露断言通过。
4. 命令 2 定向回归退出码 0（如有既有跳过如实记录；出现新失败即 FAIL）。
5. OpenAPI 产物含 6 条新路径且仅 GET；`schema.d.ts` 由产物生成；命令 5 build 退出码 0。
6. 边界核查：git 终态与开工快照对比，改动仅限 §2 允许清单；`var\` 未被写。
7. `T302-delivery.md` 齐备（§8 模板）。

## 8. 交付说明模板（T302-evidence\T302-delivery.md，照此填写）

```markdown
# T302 交付说明
## 1. 变更清单
（新增/修改的每个文件路径 + 一句话用途；main.py 的 diff 原文贴出）
## 2. 验证证据
| 命令 | 工作目录 | 退出码 | 通过/失败/跳过 | 证据文件 |
（§6 每条命令一行，不许空）
## 3. T301 对账结果
（5.3 表逐项 实际值/预期值/一致性）
## 4. 接口契约登记
（相对本派单 §3 的任何字段增删、page_size 默认值等实现决定，逐条列出）
## 5. 已知限制
（未覆盖场景、受控样本标注、Mock 范围）
## 6. 上报事项
（与任务书/冻结口径的冲突，无则写「无」）
## 7. 边界自查
（git 快照对比结论、var\ 未写确认、无付费调用确认）
```

## 9. 红线速查（做完后逐条自检）

- [ ] 问答量按完成时间+请求 ID 去重，只计 succeeded；中断单列；已删除会话双侧排除
- [ ] 最终引用 = 结果消息+文档/版本去重，排除 kind='conflict'；相关问答含冲突且 conflict_flag=true；冲突来源取 result_json.conflicts
- [ ] Trace 关闭/不可用/未记录/部分覆盖独立状态；读失败不报覆盖率；纯重放不计覆盖；只回实际记录的 Span，不虚构
- [ ] 评测批次白名单 + holdout 只读聚合详情扣留；空批次空列表+状态；不发起评测
- [ ] 任何字段不得标「业务正确率」；有引用占比只是参考指标
- [ ] Asia/Shanghai 聚合、左闭右开 UTC 窗口、90 天上限
- [ ] 仅 admin；普通会话/引用/原件接口归属校验一行未改
- [ ] 响应与证据无密钥/原始请求头/Trace 原始属性/stored_path/lease_*
- [ ] 全程 Mock，无付费调用；var\ 未写；git 无写操作
- [ ] 只改了 main.py（2 行）与生成物 schema.d.ts，其余全部新增
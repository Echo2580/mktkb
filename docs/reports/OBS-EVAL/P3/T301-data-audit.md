# T301・基线审计与指标口径冻结（工作包 A）

- 任务书：`docs/superpowers/plans/2026-11-21-mktkb-p3-operations-taskbook.md` T301 小节、§2、§4
- 审计日期：2026-11-21
- 范围：基线复核、路由与数据表核对、首版指标口径、两套 Span→阶段映射、评测批次白名单、API 状态约定。**只做分析与文档，不写业务代码。**
- 边界遵守：`backend/`、`frontend/` 源码只读；未改任何现有文件；未写 `var/` 业务库与 Trace 库（探针以只读方式打开原库）；git 仅使用 `log/status/show/diff/rev-parse`；无真实模型 / OCR / Ragas 裁判调用；文档与证据不含密钥、原始请求头、Trace 原始属性。
- 样本矩阵、独立复算表与 Trace 实测探针由工作包 B 产出，本文第 7 节为固定引用链接，合并时由项目经理对账。

---

## 1. 实际基线（git 只读命令复核）

证据文件：`T301-audit-git-output.txt`（以下为其中实际输出摘要）。

### 1.1 分支与 HEAD

| 项 | 复核结果 | 命令 / 依据 |
| --- | --- | --- |
| 分支 | `codex/p2-e2e` | `git rev-parse --abbrev-ref HEAD` |
| HEAD | `0d6ba61d0c6253550adf26888dab935ffe4310b1` | `git rev-parse HEAD` |
| P2 v0.3 发布参照候选 | `7556efd`（chore(p2): requalify candidate with new real B0 and refreeze） | `git show --stat --oneline 7556efd` |
| 发布记录提交 | `cb74457`（docs(p2): record owner release decision for requalified candidate (v0.3 freeze)），仅新增 `docs/reports/OBS-EVAL/P2/FOLLOW-UP/requalification/release-decision.v0_3.md`（70 行） | `git show --stat --oneline cb74457` |

### 1.2 发布后提交清单（`cb74457` 之后，HEAD 之前）

| 顺序 | 提交 | 标题 | 改动统计 | 纳入后续核对范围 |
| --- | --- | --- | --- | --- |
| 1 | `04515f3` | fix(launcher): real-first one-click start with offline fallback | 2 文件：`一键启动.cmd`（+42）、`P2/FOLLOW-UP/requalification/report.md`（+34/-1） | **启动路径变更，纳入 T306 启动/回退与 P2 回归核对范围**（任务书 §1 基线条目要求） |
| 2 | `2d4d839` | docs(p2): add user-perspective acceptance testbook (admin + employee) | 1 文件：`docs/superpowers/plans/2026-11-21-p2-user-acceptance-testbook.md`（+420） | 文档，无代码行为变化 |
| 3 | `0d6ba61` | feat(acceptance): plan A - widen owner-acceptance plan for user-acceptance run | 5 文件：执行器提示词（+90）、验收测试书（+32/-）、`tools/start_local.py`（+26/-）、`一键启动.cmd`（+4/-）、`启动-真实问答.cmd`（+2/-） | 含启动脚本与 `tools/start_local.py` 改动，一并纳入 T306 启动/回退核对 |

### 1.3 在途改动与未跟踪文件概况（`git status --short` / `git diff --stat`）

- **已跟踪但未提交的改动（2 个文件，纯新增共 163 行，无删除）：**
  - `.claude/handoffs/_index.md`（+91）
  - `docs/reports/OBS-EVAL/P2/T207-QUALITY-REPAIR/manager.md`（+72）
- **未跟踪项概况（保留原状，本次不读取其业务内容、不移动、不删除）：**
  - 大量 P2 证据目录：`docs/reports/OBS-EVAL/P2/FOLLOW-UP/{FU1,FU2,FU3,FU4,review-evidence,browser/tmp}`、`T207-*`、`T208-*`、`T209-*`、`H2V3`、`Q1A-EVAL-REPAIR`、`USER-ACCEPTANCE/` 等；
  - 计划/设计稿：`docs/superpowers/plans/2026-11-21-mktkb-p3-operations-taskbook.md`（本次任务书）、两份 P2 收尾计划、`docs/superpowers/specs/2026-11-21-knowledge-operations-data-center-design.md`；
  - 工程文件：`backend/requirements-ragas-eval.lock`；
  - 临时目录：`.tmp-r2-obs-baseline/`、`.tmp-t3review-isolated/`；
  - 前端原型：`原型设计/P3原型/`；
  - 本次工作目录：`docs/reports/OBS-EVAL/P3/`（含本审计文档与工作包 B 隔离目录）。
- 未执行任何 `checkout/reset/stash/clean`；在途改动与历史证据按任务书要求全部保留不动。

### 1.4 基线快照中的真实库样本（只读探针摘要）

探针脚本：`T301-audit-probe.py`；输出：`T301-audit-probe-output.txt`。原库路径：业务库 `var/mktkb.sqlite3`，Trace 库 `var/observability/qa-traces.sqlite3`（`config.py:322`、`config.py:335-343`）。

| 快照事实 | 实测值 |
| --- | --- |
| 会话总数 / 已逻辑删除 | 79 / 3 |
| 请求总数 / 状态 | 131，全部 `succeeded`；`result_message_id` 全部非空 |
| 结果消息 kind（排除已删除会话） | answer 71、clarification 22、not_found 7、service_error 17；**无 conflict、无 knowledge_changed 行** |
| 持久引用行 `conversation_message_sources` | 本地快照 90 行，全部挂在 answer 消息下；本地快照无冲突消息引用行（冲突场景实测见 7.2 D5） |
| 版本 / 资料 / 导入任务 | 版本 25（全部 `published`）；资料 25（删除 0，均有有效版本）；导入任务 25（全部 `succeeded`/`finished`）；**快照中无 `review_required`、无失败任务样本** |
| Trace 记录 | 2 条；`mode=local`；path=`legacy` 1、`legacy_with_rag_candidates` 1；outcome=answer 1、not_found 1；`status=ok` 2；`replayed=0`；`request_id` 全部可关联 |
| 实测 Span 名（13 个） | commit、embedding_query、fuse、hard_filter、intent_parse、lexical_recall、recall、vector_recall、answer_validate、exact_recall、model_answer、rerank、retrieve |

**Trace 两态核对依据：** 配置默认 `trace_enabled=False`（`config.py:116`），关闭时 `create_app` 不构造仓储、不建库文件、不产生副作用（`main.py:100-102`）；中间件仅在 `trace_repo is not None` 且为 QA POST 时开启 Trace（`main.py:136`）。本地 `var/` 快照存在 2 条 Trace 记录，说明采集期间为开启态；**关闭态已由工作包 B 在隔离环境实测（S15）：业务请求存在、无 Trace 行、无 `X-Trace-ID` 响应头，状态记 disabled**（证据 `T301-isolated/T301-trace-probe.md` §5）；端点降级语义见 4.7。

> 本地 `var/` 快照仍缺：未提交/中断请求、conflict、knowledge_changed、纯重放 Trace、失败导入、待审核版本、被删除资料的历史引用、重试（attempt>1）记录；这些场景已由工作包 B 隔离样本矩阵覆盖（见第 7 节），本地快照缺口不再作为验收阻塞项。

---

## 2. 路由与数据表核对

代码入口：`backend/src/mktkb/conversations/models.py`、`documents/models.py`、`ingestion/models.py`、`observability/routes.py`；关联模块：`conversations/service.py`、`conversations/routes.py`、`sources/service.py`、`documents/service.py`、`observability/{contracts,store,tracer,trace_attrs}.py`、`qa/service.py`、`rag/{answer,retrieval}.py`、`main.py`、`config.py`。

### 2.1 表与关联键清单

| 表（模型 / 文件行号） | 主键 | 外键 / 关联键 | 关联到 | 备注与无法回溯字段 |
| --- | --- | --- | --- | --- |
| `conversations`（`conversations/models.py:53-73`） | `id` | `user_id` → `users.id`（`models.py:63-65`） | 会话归属用户 | `deleted_at` 逻辑删除标记（`models.py:69`）；标题、`created_at/updated_at`；无组织/部门字段（设计稿 §2 已记） |
| `conversation_messages`（`models.py:76-107`） | `id` | `conversation_id` → `conversations.id`（`87-90`）；`user_id` → `users.id`（`92-94`） | 会话、用户 | `role`（user/assistant，`35`）、`kind`、`revision`、`error_code`、`missing_fields`、`text`、`created_at`；**`kind` 可空（`98`），用户消息无 kind**；消息不直接存请求 ID，需经 `conversation_requests.result_message_id` 反查 |
| `conversation_requests`（`models.py:142-188`） | `id`（产品请求 ID） | `conversation_id` → `conversations.id`（`159-162`）；`user_id` → `users.id`（`164-166`）；`user_message_id` → `conversation_messages.id`（`172-176`）；`result_message_id` → `conversation_messages.id`（`177-181`） | 会话、用户、用户消息、结果消息 | 幂等键：`(conversation_id, client_request_id)` 唯一（`147`）；`payload_sha256` 正文摘要（`168`）；`status`（`running/succeeded/failed/cancelled/expired`，`36`）；`attempt`、`result_json`（JSON，含 conflicts）、`error_code/error_retryable`；`created_at/started_at/deadline_at/finished_at`；**无 Trace ID 外键**，Trace 侧以 `request_id` 文本关联（见 2.3）；请求正文 `question` 为明文存储于业务库，Trace 中只存哈希 |
| `conversation_message_sources`（`models.py:110-139`） | `id` | `message_id` → `conversation_messages.id`（`129-132`）；复合外键 `(source_id, version_id, document_id)` → `source_units(id, version_id, document_id)`（`116-124`）；`source_id`/`document_id`/`version_id`（`134-136`） | 结果消息、来源单元、版本、资料 | 唯一约束 `(message_id, source_id)`（`115`）；**无结果类型/冲突标记列**；引用时点的定位（locator）不冗余在本表，展示时回查 `source_units.locator`；单元被清理后引用行的归属一致性由复合外键与 `load_unit` 校验保证（`sources/service.py:83-96`） |
| `documents`（`documents/models.py:56-84`） | `id` | `active_version_id` → `document_versions.id`（`71-73`） | 当前有效版本 | `name/name_key/file_type/latest_version_number/deleted/created_at/last_published_at`；**无部门、无业务标签字段**；`deleted` 布尔逻辑删除（`75`） |
| `document_versions`（`models.py:87-120`） | `id` | `document_id` → `documents.id`（`105-107`） | 资料 | `number/state/sha256/size_bytes/stored_path/uploaded_at/published_at/processing_report`；状态枚举 `queued/processing/review_required/failed/published/superseded/cancelled/deleted`（`31-40`）；**`stored_path` 为内部受控路径，运营出口不得回显** |
| `source_units`（`models.py:123-150`） | `id` | `document_id` → `documents.id`（`135-137`）；`version_id` → `document_versions.id`（`138-140`） | 版本、资料 | `kind/ordinal/unit_key/sheet/locator/text/fields/warnings`；唯一约束 `(version_id, unit_key)`、`(version_id, ordinal)`（`128-129`）；跨版本条款匹配无现成键，需另做规则（设计稿 §2） |
| `import_jobs`（`ingestion/models.py:21-48`） | `id` | `version_id` → `document_versions.id`（`32-34`，唯一 `ux_import_jobs_version`，`26`） | 版本 | 状态 `queued/running/succeeded/failed/blocked/cancelled`（`18`）；`stage/total_pages/completed_pages/error_code/message/retryable/attempts/lease_token/lease_owner/lease_expires_at/created_at/updated_at/finished_at`；**任务不直接挂资料 ID，经版本间接关联**；租约字段属运行时排错，不进运营摘要 |
| `ocr_call_records`（`ingestion/models.py:51-94`） | `id` | `document_id`、`version_id` | 资料、版本 | OCR 去重与排错记录；**不代表账号余额或计费保证**（`52`）；首版运营指标不直接消费 |
| `knowledge_state`（`documents/models.py:153-162`） | `id`（单例） | — | 全库 revision、有效总量 | `revision/active_document_count/active_excel_row_count/updated_at`；库存快照口径，下钻仍需回表核对当前状态 |
| `publication_receipts` / `deletion_receipts`（`models.py:165-200`） | 版本 / 资料 | `document_id`、`version_id` | 资料、版本 | 发布/删除幂等凭据；含 `expected_revision/revision/published_at/deleted_at`；历史答案保留原 revision 的凭证来源 |
| Trace 库 `traces`（`observability/contracts.py:188-237`；`store.py:57`） | `trace_id` | `request_id`（文本，对应 `conversation_requests.id`）；`previous_trace_id`（重试/重放链）；`run_id`、`case_id`、`manifest_sha256`（评测身份） | 业务请求、评测运行 | 字段见 2.3；**无业务库外键约束**，跨库在服务层按请求 ID 关联；`*_json` 原文不进运营响应 |
| Trace 库 `spans`（`contracts.py:240-252`；`store.py:101`） | `span_id` | `trace_id` → `traces.trace_id`（`store.py:111`）；`parent_span_id` | Trace | `name/started_at/duration_ms/status/attributes_json/error_code`；`attributes_json` 原文不返回（`routes.py:308-319`） |
| 评测运行制品（`var/eval/runs/<run_id>/`） | 目录名 `run_id` | manifest 内 `index_revision`、`manifest_sha256`；Trace 侧 `run_id` | Trace、知识库 revision | 三份 JSON：`run_manifest.json`、`summary.json`、`gate.json`；`cases.jsonl` 仅普通 suite 存在，holdout 详情扣留（见第 6 节） |

### 2.2 现有路由与运营缺口

| 现有路由 | 权限 / 归属校验 | 依据 |
| --- | --- | --- |
| `GET /observability/traces/{trace_id}` | admin（`routes.py:50`、`747`） | 只读摘要 + Span 摘要 |
| `GET /observability/requests/{request_id}/traces` | admin（`routes.py:774`） | 同请求全部尝试 |
| `GET /observability/metrics?window=` | admin（`routes.py:799`） | path/outcome 聚合、P50/P95、token、成本、degraded/error 计数 |
| `GET /observability/runs/{run_id}` | admin（`routes.py:847`） | manifest/summary/gate 聚合白名单 |
| 会话 / 消息 / 提问接口 | 普通归属校验：当前用户拥有未删除会话（`sources/service.py:31-41`）；跨用户 403、已删除会话 404 | 管理员跨会话诊断权限**仅限运营接口**，普通会话/引用/原件接口归属校验不变（任务书 §2 访问范围） |
| 来源详情 `/messages/{message_id}/sources/{source_id}`、原件 `/file` | 先鉴权消息归属，再核对引用与当前有效性；失效 410 且不带正文/字段/原图/内部路径 | `sources/routes.py:29-63`、`sources/service.py:147-184` |

**现有代码尚未提供、属 P3 新增（T302 及以后）：** 运营总览/请求列表/请求详情/资料列表/资料详情/引用与冲突聚合/评测批次列表接口；按 `(结果消息+文档)`、`(结果消息+版本)` 的引用去重统计；资产页「最终引用」计数与「相关问答」聚合；按业务日窗口的问答量/趋势/覆盖率查询。本次审计只冻结口径，不实现接口。

### 2.3 请求 ↔ Trace 关联方式

- 中间件仅对 QA 问答 POST 开启 Trace：`main.py:136`（`_is_qa_post`），`mode=TRACE_MODE=local`、`scope=TRACE_SCOPE=end_to_end`（`main.py:34`、`36`、`137-143`）。
- 关联键：Trace 写入 `request_id = str(ConversationRequest.id)`（`conversations/service.py:2983-2984`）；`http_request_id` 为中间件 UUID（`main.py:132`、`contracts.py:199`）。
- 反向关联：`TraceRepository.list_by_request(request_id)` 按 `request_id` 查全部尝试，按 `attempt ASC, rowid ASC` 排序（`store.py:234-242`）。
- 重放标记：幂等重放不产生新请求行；Trace 置 `replayed=True`、`status=replayed`、Span 为空，不覆盖历史（`service.py:2986-2990`；`tracer.py:128`、`669-673`）。**实测更正（B 隔离实测，`T301-isolated/T301-trace-probe.md` §4）：重放链路 `previous_trace_id` 实测为 null（未回填）；重放与原始 Trace 的串联依赖同一产品请求 ID（`request_id`），`previous_trace_id` 链仅适用于重试场景。重放识别以 `replayed=1`、`status=replayed`、Span 数 0 为准。**
- 关联缺口：Trace 关闭、不可用、未记录时业务请求仍存在，但无 Trace 行；早期拒绝（未进领取/未建 Trace）无法回溯执行阶段。

### 2.4 无法回溯 / 不进运营出口的字段

| 类别 | 字段 | 原因 / 依据 |
| --- | --- | --- |
| 明文正文 | 问题原文、答复正文、上下文候选、`fields` 明细、原件 | Trace 只存 `question_hash/question_chars/hash_algo/hmac_key_id`（`contracts.py:219-222`；`routes.py:101-133`）；来源正文仅 active 且归属校验通过时由原来源接口返回（`sources/service.py:156-167`） |
| Trace 原始属性 | `retrieval_counts_json/filter_decisions_json/fact_gate_json/citation_refs_json/pagination_json/token_usage_json/cost_json/degraded_json` 原文 | 运营响应只返回计数/时长/状态/键名；Span 仅返回 `attribute_count/attribute_keys`（`routes.py:308-319`） |
| 内部路径 / 凭据 | `stored_path`、`lease_token`、HMAC 密钥、供应商请求头、provider request id | 路由白名单不含路径与凭据（`routes.py:174-252`）；`ocr_call_records.provider_request_id`（`models.py:89`）不进摘要 |
| 历史缺项 | 解析前请求的候选集、重排排名与分数、跨版本条款匹配、组织/部门维度、员工身份趋势 | 现有表无对应采集（设计稿 §2、§4）；首版显示「未记录」，不按结果类型推测 |
| 冲突来源历史 | 旧冲突消息可能无 `MessageSource` 行，两方来源取自 `result_json.conflicts` | `sources/service.py:44-66`（`_legacy_conflict_reference`，仅校验 source_id 确在 result_json.conflicts 中，不新建行） |

---

## 3. 首版指标口径表

口径红线以任务书 §2 为准；时间一律 `Asia/Shanghai` 显示与聚合，日历日期转左闭右开 UTC 窗口（见 6.1）。库存类指标（待审核版本、生效资料）标记「当前」，下钻使用相同当前状态口径。

| # | 指标 | 来源表 / 字段 | 时间字段 | 去重键 | 过滤条件 | 空值 / 空分母语义 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 已完成问答量 | `conversation_requests`（`status`、`result_message_id`、`finished_at`）；结果类型取 `conversation_messages.kind` 或 `result_json.kind` | `finished_at`（UTC 存储，展示转 Shanghai） | 产品请求 ID `conversation_requests.id`；按完成时间 + 请求 ID 去重 | 仅 `status='succeeded'`（已提交结果）；排除会话 `deleted_at IS NOT NULL`；幂等重放不加量（同一 `client_request_id` 复用请求行，`models.py:147`）；窗口内 | 窗口内无已完成请求：计数 0，趋势为空数组；分母为 0 的占比指标返回「无样本」，不返回 0% 伪装正确率 |
| 2 | 六类结果分布 | 结果消息 `kind`；六类契约：`answer/clarification/not_found/conflict/service_error/knowledge_changed`（任务书 §2；枚举对照 `contracts.py:39-50`） | 同 #1（`finished_at`） | 同 #1（请求 ID） | 同 #1；图表与下钻列表使用**同一查询条件** | 某类无样本：该类计数 0；未提交中断不进入六类分布（见 #3） |
| 3 | 未提交结果中断（单列） | `conversation_requests.status ∈ {running, failed, cancelled, expired}`（`models.py:36`）；`error_code/error_retryable` | `started_at` / `finished_at`（未完成时 `finished_at` 为空） | 请求 ID | 排除已删除会话；与六类分布分开展示 | 无中断：单列计数 0；`finished_at` 为空时不计入完成问答量 |
| 4 | 按日趋势（问答量 / 引用量 / 带日期事件） | 同 #1；引用量见 #8/#9；事件类按各自业务时间 | 各表业务时间字段，UTC→Shanghai 日历日 | 同 #1 / 同 #8/#9 | 同 #1；随筛选窗口变化 | 无数据日期：不补零伪造趋势（按空态处理）；跨午夜边界按左闭右开 UTC 窗口切分 |
| 5 | 待处理列表（异常问答 + 导入失败） | 异常问答：`service_error/conflict/not_found` 等结果类型 + 请求 `error_code`；导入失败：`import_jobs.state ∈ {failed, blocked}`（`ingestion/models.py:18`），`error_code/message/attempts/retryable`（`39-42`） | 问答 `finished_at`；任务 `updated_at/finished_at` | 请求 ID；任务 `version_id` 唯一（`models.py:26`） | 问答排除已删除会话；任务关联版本/资料当前未删除 | 无待处理项：列表空 + 空态；失败原因缺失时只显示状态，不推测错误码 |
| 6 | 待审核版本数 | `document_versions.state='review_required'`（`documents/models.py:34`） | 库存「当前」口径，不随时间窗口回溯 | 版本 ID | 关联资料 `deleted=False`；当前时点状态 | 当前无待审核：计数 0；历史审核流程不回溯重建 |
| 7 | 当前生效资料库存 | `documents.deleted=False` 且 `active_version_id IS NOT NULL`（`documents/service.py:435-441`、`492`、`498-499`）；有效版本状态 `published` | 库存「当前」口径 | 资料 ID | 同当前状态口径；下钻同口径 | 无有效资料：计数 0；`active_version_id` 悬空时按无有效版本处理 |
| 8 | 引用量（文档维度） | `conversation_message_sources` → `source_units.document_id`（`models.py:116-136`） | 引用所在结果消息的 `finished_at`（随问答窗口） | **`结果消息 ID + document_id`** 去重；同一回答引用同一资料多行只计一次 | 仅正常回答的持久引用；冲突消息不计入「最终引用」（见 6.3）；排除已删除会话 | 无引用：计数 0；引用行缺失但 result_json 有冲突条目时走冲突分列，不计本指标 |
| 9 | 引用量（版本维度） | `conversation_message_sources.version_id` | 同 #8 | **`结果消息 ID + version_id`** 去重 | 同 #8 | 同 #8；历史/失效版本仍可按版本标识展示，正文/原件按现有规则校验 |
| 10 | Trace 覆盖率 | 业务请求表（分母）× Trace 库 `traces`（分子），按 `request_id` 关联 | 请求 `finished_at`；Trace `created_at` 同窗口 | 请求 ID | 分母：筛选范围内已完成请求（同 #1）；分子：有**普通执行 Trace** 的已完成请求；纯重放记录（`replayed=True`）不计为覆盖 | Trace 读取失败时**不报覆盖率**（无分母/分子置信度），返回独立不可用状态；关闭/未记录/部分覆盖独立展示（见 6.4）；部分覆盖 = 分子 < 分母，单独标注覆盖数与样本数 |
| 11 | 有引用回答占比（参考指标，非业务正确率） | answer 请求 × 是否存在合法持久引用（#8 口径） | 同 #1 | 请求 ID | 仅 `kind='answer'`；引用须为当前库可回溯的持久引用 | 分母（answer 请求数）为 0：显示「无样本」；**该占比与线上问答数量均不得标注为业务正确率**（任务书 §2 追踪与评测） |
| 12 | 导入任务库存 / 重试 | `import_jobs` 按 `state/stage/attempts` | `created_at/updated_at/finished_at` | 任务 ID；`version_id` 唯一 | 当前库；失败/阻断单列 | 任务无 `finished_at` 时按在途处理；重试次数单列，不重复计业务结果 |

> 补充：延迟 P50/P95、Token、成本沿用现有 `/observability/metrics` 聚合（`routes.py:459-541`），只基于有耗时/有记录的实际执行样本并显示样本数；Token/成本无记录时返回 0 与 `has_usage/has_cost=False` 语义，不估算。

---

## 4. 两套 Span→阶段标签映射（冻结）

映射来源：真实代码埋点（`trace_attrs.span(...)` 调用点）+ 契约必需 Span 表（`observability/contracts.py:55-121`）。页面只渲染映射内**实际记录**的阶段与耗时；未记录 ≠ 0ms，不虚构阶段，不按结果类型补阶段。工作包 B 的隔离 Trace 实测（`T301-isolated/T301-trace-probe.md`）用于与本节对账；若实测与本节不一致，合并时以代码埋点 + 实测双方证据上报，不擅自改任务书。

**对账结论（B 隔离实测）：** 三路径 `rag` / `legacy` / `legacy_with_rag_candidates` 实测 Span 清单全部落在 4.2 / 4.3 映射内，实测与代码埋点无冲突；`index_sync` 与 `query_expansion` 为条件 Span，本次样本未触发，其缺失语义按 4.2 / 4.3 冻结（未记录 ≠ 0ms）。

### 4.1 路径枚举与归属

- `TracePath` 三值：`rag`、`legacy`、`legacy_with_rag_candidates`（`contracts.py:31-36`）。
- `legacy_with_rag_candidates` 表示 legacy 作答但带 RAG 候选，**与 legacy 共用 legacy 必需 Span 规则**（`contracts.py:135`、`156`、`162`、`167`）。
- 路径写入：RAG 直答轮次 `trace.set_path(RAG)`（`conversations/service.py:2530-2532`）；legacy 默认 `LEGACY`（`2559-2560`）；实际拿到 RAG 候选后改记 `LEGACY_WITH_RAG_CANDIDATES`（`2647-2648`）。

### 4.2 RAG 路径（`path=rag`）

代码埋点：`rag/answer.py`、`rag/retrieval.py`、`qa/service.py`。

| Span 名 | 页面阶段标签 | 埋点位置 | 类型 | 缺失语义 / 备注 |
| --- | --- | --- | --- | --- |
| `parse` | 解析计划 | `rag/answer.py:79` | 基础必需 | 检索前拒答（clarification/no_answer/error/knowledge_changed）也应存在；缺失按未记录处理 |
| `recall` | 检索召回 | `rag/retrieval.py:62` | 基础必需（answer/conflict/no_answer/ambiguous） | 检索前拒答分支未执行召回，见 4.5 reason 例外 |
| `exact_recall` | 精确召回（recall 子阶段） | `rag/retrieval.py:67` | recall 嵌套子 Span | 仅 `plan.mode=record` 创建；非 record 计划无此通道（`63-66`），不渲染 |
| `lexical_recall` | 全文召回（recall 子阶段） | `rag/retrieval.py:73` | recall 嵌套子 Span | 检索词为空时通道 `term_miss`，Span 仍记录候选 0 |
| `vector_recall` | 向量召回（recall 子阶段） | `rag/retrieval.py:83` | **条件 Span**：属性 `vector_enabled=true` 时要求（`contracts.py:117`） | 向量面被运行时关闭（`disable_query_embedding`）时不创建 Span、不置条件属性（`retrieval.py:60`、`82`）；缺失不报错 |
| `embedding_query` | 查询向量生成 | `rag/retrieval.py:498`（`500` annotate） | 内部子 Span（不在必需表） | 向量通道未执行时缺失；不单独映射为业务阶段 |
| `fuse` | 融合排序 | `rag/retrieval.py:108` | 基础必需（answer/conflict/no_answer/ambiguous） | 检索前拒答例外见 4.5 |
| `hard_filter` | 条件硬过滤 | `rag/retrieval.py:681`（`685` annotate） | 内部子 Span（不在必需表） | 未触发过滤时缺失 |
| `rerank` | 重排 | `rag/retrieval.py:706`（`732/743` annotate） | **条件 Span**：属性 `rerank_enabled=true` 时要求（`contracts.py:118`） | 仅融合结果非空时真实执行；未启用/未触发不伪造（`retrieval.py:112-113`） |
| `answer` | 答案生成 | `rag/answer.py:275` | 基础必需（answer/conflict） | 拒答/澄清分支不进入此 Span |
| `fact_validate` | 事实校验闸门 | `rag/answer.py:305` | 内部闸门 Span（不在两张必需表内，**差异项 D1**） | 仅进入事实校验的分支存在；`fact_gate_json` 只记计数/状态，原文不出口 |
| `commit` | 状态持久化 | `rag/answer.py:326` | 基础必需（全部结局） | 每个 RAG 轮次退出前包住查询状态落库；早退分支也调用 `_commit`（`answer.py:129`、`158`、`172`、`271`） |
| `index_sync` | 索引同步 | `qa/service.py:421` | **条件 Span**：属性 `index_sync_performed=true`（`contracts.py:120`） | 仅真正执行同步时创建并置标记；命中就绪缓存不进本方法，不伪造（`qa/service.py:416-422`） |

### 4.3 legacy 路径（`path=legacy` / `legacy_with_rag_candidates`）

代码埋点：`conversations/service.py`。

| Span 名 | 页面阶段标签 | 埋点位置 | 类型 | 缺失语义 / 备注 |
| --- | --- | --- | --- | --- |
| `intent_parse` | 意图解析 | `conversations/service.py:2562` | 基础必需（全部 legacy 结局） | 解析级早退也应存在 |
| `retrieve` | 证据检索 | `conversations/service.py:2670` | 基础必需（answer/not_found/conflict/knowledge_changed 检索形态） | 解析级早退未执行 retrieve，见 4.5；`legacy_with_rag_candidates` 的 RAG 候选子阶段复用 4.2 召回 Span 名 |
| `entity_conflict_check` | 实体冲突检查 | `conversations/service.py:2738` | 内部子 Span（不在必需表，**差异项 D2**） | 仅触发实体冲突比对的分支存在 |
| `query_expansion` | 查询扩展 | `conversations/service.py:2768` | **条件 Span**：属性 `expansion_triggered=true`（`contracts.py:119`） | 只有真正触发扩展调用才置标记并创建 Span（`service.py:2765-2766`）；未触发不伪造 |
| `model_answer` | 模型作答 | `conversations/service.py:2893` | 基础必需（answer） | 未进入模型调用的结局不产生 |
| `answer_validate` | 答案校验 | `conversations/service.py:2900` | 基础必需（answer） | 校验失败走失败/拒答分支时按实际结局契约核对 |
| `commit` | 结果提交 | `conversations/service.py:3007` | 基础必需（全部 legacy 结局） | legacy 产品提交阶段；RAG 路径的 commit 由 rag 内核产生（`3005-3007` 注释） |
| `model_failure` | 模型失败分支 | `conversations/service.py:2170` | 失败分支 Span（不在必需表，**差异项 D2**） | 仅模型错误进入 `_model_failure_result` 时存在；`model_failure_reason` 为属性键，原文原因不出口 |

### 4.4 契约必需 Span 表（fail closed 依据）

来源：`contracts.py:55-79`。未定义的 `path+outcome` 组合抛 `ValueError`，不静默返回空集（`contracts.py:167-174`）。

**RAG（`_RAG_REQUIRED_SPANS`，`contracts.py:55-63`）**

| outcome | 必需 Span |
| --- | --- |
| answer | parse, recall, fuse, answer, commit |
| conflict | parse, recall, fuse, answer, commit |
| clarification | parse, commit |
| no_answer | parse, recall, fuse, commit |
| ambiguous | parse, recall, fuse, commit |
| error | parse, commit |
| knowledge_changed | parse, commit |

**legacy（`_LEGACY_REQUIRED_SPANS`，`contracts.py:65-79`）**

| outcome | 必需 Span |
| --- | --- |
| answer | intent_parse, retrieve, model_answer, answer_validate, commit |
| not_found | intent_parse, retrieve, commit |
| clarification | intent_parse, commit |
| service_error | intent_parse, commit |
| conflict | intent_parse, retrieve, commit |
| knowledge_changed | intent_parse, retrieve, commit |

### 4.5 reason 相关的必需集降级（缺失语义例外，须随 Trace reason 展示）

来源：`contracts.py:85-113`；`required_spans(..., reason=...)`（`129-166`）。

| 路径 + 结局 | reason 白名单 | 降级后必需集 |
| --- | --- | --- |
| rag + no_answer | `DOCUMENT_NOT_FOUND`、`UNKNOWN_STORE`、`RECORD_ONLY`（检索前拒答） | `{parse, commit}`（无 recall/fuse） |
| legacy + not_found | `UNKNOWN_IDENTIFIER`、`IDENTIFIER_NOT_RETRIEVABLE`、`NO_INTENT`、`UNRECORDED_FIELD`（解析级早退） | `{intent_parse, commit}`（无 retrieve） |
| legacy + knowledge_changed | `KNOWLEDGE_CHANGED_AT_COMMIT`（早退后 commit 阶段才升级） | `{intent_parse, commit}`（无 retrieve） |

不在白名单的 reason / 缺省 reason 仍按 4.4 冻结表要求；页面判定「阶段缺失」时必须先比对 reason 降级集，避免把检索前早退误报为缺阶段。

### 4.6 与任务书列举 Span 名的差异（如实记录，不擅改任务书）

- **D1（RAG 多出的 Span）**：任务书列举 `parse/recall/fuse/answer/commit` 及条件 Span；代码实际还发出 `exact_recall`、`lexical_recall`、`vector_recall`、`embedding_query`、`hard_filter`、`rerank`、`fact_validate`。其中 `vector_recall/rerank` 已在契约条件 Span 内；`exact_recall/lexical_recall` 为 recall 嵌套子阶段；`embedding_query/hard_filter/fact_validate` 为内部子 Span，不进页面主阶段标签。
- **D2（legacy 多出的 Span）**：任务书列举 `intent_parse/retrieve/model_answer/answer_validate/commit`；代码实际还发出 `entity_conflict_check`、`query_expansion`（条件）、`model_failure`（失败分支）。`query_expansion` 已在契约条件 Span 内；其余为内部/分支 Span。
- **D3（第三路径值）**：`legacy_with_rag_candidates` 未出现在任务书「两套路径」表述中；代码与契约均确认其为 legacy 变体，共用 legacy 映射。
- **D4（outcome 枚举超集）**：Trace `OutcomeKind` 含 `no_answer/ambiguous/error`（`contracts.py:39-50`），与业务六类结果（answer/clarification/not_found/conflict/service_error/knowledge_changed）不是同一集合；RAG 把 `RagAnswer.kind` 直接映射为 outcome（`qa/service.py:580-582`）。运营六类分布以业务消息 kind 为准，Trace outcome 仅用于执行阶段与状态核对。
- **D5（冲突引用持久化，已实测确认与任务书口径存在出入，上报主人裁决）**：任务书 §2 规定「冲突消息不产生持久引用行，两方来源取自结果 JSON 的 conflicts」。代码提交路径：冲突条目 source_id 被纳入 `_reference_ids`（`conversations/service.py:1970-1979`，文档字符串明示「普通答案的引用 + 冲突条目的各自来源」）；`units/reference_ids` 仅对 `service_error/not_found/clarification` 清空（`2036-2038`），**未对 conflict 清空**；版本 active 且 revision 匹配时写入 `MessageSource`（`2016-2024`、`2066-2086`）。**隔离实测（B 样本 S05，正常入口、两方来源均 active）：落 `MessageSource` 2 行；项目经理以独立只读 SQL 复核同为 2 行（证据 `T301-acceptance-verify-output.txt` 第 10-11 行；`T301-isolated/T301-recomputation.md` §5.1、§8.2）。** 旧数据兼容读取由 `_legacy_conflict_reference` 覆盖（`sources/service.py:44-66`）。**API 约定仍按任务书口径冻结不变（6.3）；实现路径说明：T302 查询侧按结果消息 `kind='conflict'` 排除「最终引用」计数即可满足口径，无需改提交链路代码；是否修改提交链路代码属主人裁决事项，在 P3 只读范围外。**

### 4.7 Trace 状态判定（关闭 / 不可用 / 未记录 / 部分覆盖 / 重放）

Trace 记录内 `status` 取值：`ok / error / incomplete / replayed`（`tracer.py:125-128`；计算规则 `669-681`）。运营展示的独立状态在查询层派生：

| 展示状态 | 判定依据 | 代码位置 | 页面语义 |
| --- | --- | --- | --- |
| Trace 关闭 | `app.state.trace_repo is None`（`trace_enabled=false` 或仓储未构造）；端点返回 `degraded_reason="trace_disabled"`，200 空聚合 | `main.py:102`、`136`；`routes.py:729-730`、`751-752`、`778-779`、`806-813` | 业务问答仍可读；不渲染任何阶段；不报覆盖率 |
| 不可用 | 仓储读失败抛 `TraceWriteError`；返回 `degraded_reason="trace_unavailable"` | `routes.py:757-758`、`782-783`、`816-823` | 显示「Trace 暂不可用」；覆盖率不可报 |
| 未记录 | 请求已完成但 Trace 库无该 `request_id` 记录（含早期拒绝、未进 Trace 分支） | `store.py:234-242` 空结果 | 业务结果正常展示；执行阶段区显示「未记录」 |
| 部分覆盖 | 筛选范围内有 Trace 的请求数 < 已完成请求数；或 Trace `status=incomplete`（缺 path/outcome） | `tracer.py:676-677`；覆盖率口径见指标 #10 | 独立标注覆盖数 / 分母；不把缺阶段补成 0ms |
| 重放可辨认 | `replayed=1`、`status=replayed`、Span 数 0；与原始 Trace 靠同一产品请求 ID 串联。**实测 `previous_trace_id` 为 null（未回填），该链仅适用于重试场景，不作为重放识别依据**（B 实测，`T301-isolated/T301-trace-probe.md` §4） | `tracer.py:201-202`、`672-673`；`service.py:2987-2989` | 显式「重放」标签；纯重放不计入覆盖分子 |
| 执行失败 | `status=error`（`error/service_error` 结局或执行异常） | `tracer.py:134`、`670-680`；`routes.py:455-456` | 展示错误码键，不展示原始属性 |

### 4.8 旧版 / 失效引用可展示字段

来源：`sources/service.py:99-105`（状态判定）、`147-167`（详情）、`170-184`（原件）；摘要 `108-125`。

| 当前状态 | 判定 | 可展示字段 | 不展示 / 拒绝 |
| --- | --- | --- | --- |
| active | 资料未删除 + 版本 `published` + 仍是 `active_version_id` | `source_id`、`document_name`、`version_number`、`locator`、`published_at`、`text`、`fields`、`warnings`、`file_url` | — |
| superseded | 版本已被替换 | 410，仅必要失效元信息：`status`、`document_name`、`version_number` | 不返回正文/字段/原图/内部路径（`154-155`） |
| deleted | 资料删除或版本 `deleted` | 410，同上失效元信息 | 同上；原件 410 `SOURCE_UNAVAILABLE`（`178-183`） |
| 历史冲突引用 | 仅在 `result_json.conflicts` 出现、无引用行 | 按单元回查当前状态后给出摘要；匹配失败 `SOURCE_NOT_FOUND` | 不新建引用行、不放宽权限（`44-66`） |

---

## 5. 评测批次白名单规则

### 5.1 现有制品与接口事实

- 现有只读接口：`GET /observability/runs/{run_id}`（admin，`routes.py:838-886`）；**当前无批次列表接口**，列表属 T302 新增 `GET /api/v1/operations/evaluation-runs`（任务书 §3 接口表）。
- 制品位置：`var/eval/runs/<run_id>/`，三份 JSON：`run_manifest.json`、`summary.json`、`gate.json`；`cases.jsonl` 为逐题文件（`routes.py:853-866`）。
- 白名单字段（manifest 聚合，`RunManifestSummary`，`routes.py:174-196`）：`run_id/mode/scope/suite/dataset_version/dataset_sha256/corpus_manifest_sha256/business_date/index_revision/pipeline_version/gate_version/label_version/created_at/case_count/config_hash/holdout_details/holdout_labels_sha256/multi_turn_case_count/multi_turn_turns_executed`。
- summary 聚合（`RunSummaryBlock`，`routes.py:211-232`）：`case_count/scored_count/skipped_ocr_count/error_count/status_counts/metrics(扁平数值, ≤200 键)/retrieval_only/holdout`；gate 聚合（`GateSummary`，`235-251`）：`exit_code/gate_status/failure_count/unknown_count/not_applicable_count/warnings_count/quality_status` 等；`hard_failures` 仅保留字符串列表，不返回 evidence 明细。

### 5.2 白名单判定规则（冻结写入 API 约定）

1. **可见范围**：固定集摘要只读取「已允许公开」或「当前权限可查」的运行；当前部署沿用 admin 角色，运营批次接口与现有 run 接口同为 admin 依赖（`routes.py:50`）。非 admin 不返回任何批次摘要。
2. **判定字段**：以 manifest 的 `mode`（`local/replay/live`）、`scope`（`end_to_end/retrieval_only`）、`suite`（`b0/badcase/regression/holdout`）、`holdout_details`、`dataset_version`、`label_version`、`case_count` 为准；`mode=local/replay` 为离线/受控执行；`mode=live` 仅 `scope=retrieval_only`、`suite≠holdout`（`runner.py:410-418`），且 live 授权在执行时由 `live_authorization` 校验，**清单侧不存储授权结论**，不可仅凭 manifest 判定 live 批次对当前用户可查。
3. **holdout 只读聚合与详情扣留**：
   - 命中条件：`suite=holdout`（manifest 或 summary）或 `holdout_details=true`（`routes.py:859-865`）；
   - `holdout_detected=true`；`details_withheld=true` 当命中且存在 holdout 详情（`holdout_details` 或 `cases.jsonl` 存在）（`866`）；
   - 只返回 `HoldoutSummary` 聚合：`aggregate_only/details_written/label_version/questions_sha256/labels_sha256/strata/metadata_mismatch_count/traces_persisted`（`routes.py:198-209`、`628-647`）；**不读取、不返回逐题 cases.jsonl、题干、答案、审计正文**；
   - 普通 suite 的 `cases.jsonl` 不属于 holdout 明细（`routes.py:864` 注释），但现有 run 接口本身也不透出逐题，仅返回聚合块。
4. **分母与评测状态保留**：摘要保留 `case_count/scored_count/error_count/status_counts` 与 gate `quality_status`；区分「尚未评测 / 评测失败 / 评测完成」四种展示结果（设计稿 §3）；指标无样本时显示无样本，不补 0。
5. **无可用批次**：列表接口返回空数组 + 状态字段（不报错、不猜测目录）；run 目录缺失或 manifest 缺失返回 `RUN_NOT_FOUND`（`routes.py:77-79`、`573-574`、`854-855`）；JSON 非法返回对应 `degraded_reason`（`manifest_invalid/summary_invalid/gate_invalid`，`871-876`）。
6. **P3 不发起评测**：运营只读，不创建评测任务、不触发 live/真实模型/OCR/Ragas 裁判调用；评测任务创建属第二阶段（设计稿 §5、§7）。
7. **正确率红线**：线上问答数量、有引用占比均不得标注为业务正确率；固定集分数仅代表对应数据集与批次的受控执行结果（任务书 §2 追踪与评测；设计稿 §4）。

### 5.3 当前 `var/eval/runs/` 实测批次（只读清单，供 T302 列表对账）

| run_id 目录 | mode | scope | suite | holdout_details | case_count | 备注 |
| --- | --- | --- | --- | --- | --- | --- |
| `b0-live-20261108T194053896474Z-b224f9fb` | live | retrieval_only | b0 | False | 10 | live 批次，授权结论以执行时为准 |
| `b0-live-20261109T111828086143Z-0efd058b` | live | retrieval_only | b0 | False | 40 | 同上 |
| `p0-b0` | local | end_to_end | b0 | （空） | 40 | 离线受控 |
| `p0-b0-replay` | replay | end_to_end | b0 | （空） | 40 | 重放 |
| `p0-badcase` | local | end_to_end | badcase | （空） | 13 | 离线受控 |
| `p2-t209-b0-20261120-01` | — | — | — | — | — | 目录为空，无 manifest/summary/gate，按 `RUN_NOT_FOUND` 处理 |
| `p2-t209-b0-20261120-02` | — | — | — | — | — | 同上 |
| `p2-t209-b0-20261121-01` | — | — | — | — | — | 同上 |

> 未发现 `suite=holdout` 的现存制品；holdout 扣留规则按 5.2 冻结，待后续 holdout 批次落地后实测对账。

---

## 6. API 状态约定汇总（冻结）

### 6.1 时间窗口与时区

- 显示与聚合时区：`Asia/Shanghai`；库内时间按 UTC 存储（`documents/models.py:47-53` `as_utc`），查询时转换。
- 日历日期窗口转为**左闭右开 UTC 窗口**：`[start_utc, end_utc)`；午夜边界按 UTC 切分，避免跨日重复/遗漏。
- 预置窗口：今日、近 7 个自然日（含今天）、近 30 天；自定义窗口上限 90 天，超限拒绝（任务书 §2 时间与库存）。
- 问答量、引用量、带日期事件随筛选变化；库存指标（待审核版本、生效资料）标记「当前」，不随历史窗口回溯，下钻同当前口径。

### 6.2 已删除会话两侧排除

- 统计侧与下钻明细侧使用同一条件：`conversations.deleted_at IS NULL`（`conversations/models.py:69`；归属校验 `sources/service.py:36-38`）。
- 已逻辑删除会话中的请求在问答量、分布、趋势、引用、待处理列表中**双侧一致排除**；普通会话接口对已删除会话返回 404，不依赖页面隐藏。

### 6.3 冲突来源口径

- 六类结果中的 `conflict`：两方来源取自结果 JSON `conflicts`（`result_json`，`conversations/models.py:182`）；问答详情中分列展示。
- 资产页「最终引用」只统计正常回答的持久引用；**最终引用计数不含冲突**。
- 资产页「相关问答」及按文档/版本过滤问答时，**包含**冲突来源并**单独标注**；过滤口径与最终引用计数口径分开。
- 持久化行为差异见 D5（4.6）：**已实测确认**提交链路会为 active 冲突来源写入 `MessageSource`（S05 落 2 行，独立 SQL 复核一致），与任务书口径存在出入，上报主人裁决。**API 约定按任务书口径冻结不变：「最终引用」计数排除 `kind='conflict'` 的消息；冲突条目以 `result_json.conflicts` 为准，资产页「相关问答」包含冲突并单独标注。** 处置路径：T302 查询侧按 `kind='conflict'` 排除最终引用计数即可满足口径，无需改提交链路；是否修代码属主人裁决，P3 只读范围外。
- 历史/失效冲突来源按 4.8 展示失效元信息，摘录与原件继续受现有规则校验。

### 6.4 Trace 独立状态

关闭 / 不可用 / 未记录 / 部分覆盖 / 重放 / 执行失败各自独立展示，定义见 4.7；覆盖率仅在 Trace 可读且分子分母同口径时计算，读取失败不报覆盖率；纯重放不计覆盖；只渲染实际存在的阶段与耗时。

### 6.5 历史缺项表达

- 无记录的阶段/字段统一表达「未记录」，不补 0ms、不按结果类型虚构阶段；
- 库存/事件无数据时空态返回；空分母占比返回「无样本」；
- 指标标注来源时点（当前 / 窗口内）与样本数；早期不可回溯的候选、排名、分数不回溯重建。

### 6.6 权限与出口红线

- 运营接口沿用 `admin` 角色；管理员跨会话诊断权限限定在运营接口；普通会话、引用、原件接口归属校验不变（任务书 §2 访问范围）。
- 运营响应与测试证据禁止输出：密钥、原始请求头、Trace 原始属性（`*_json` 原文、attributes_json 原文）、内部存储路径、SQL/库路径。
- 历史或失效引用保留可展示的版本标识；摘录与原件按各自现有规则校验。

### 6.7 约定的 API 字段（供 T302 接口与前端类型对齐，本次不生成 OpenAPI 类型）

- 请求摘要：`request_id`、`conversation_id_hash`（或列表内脱敏标识）、`kind`、`status`、`finished_at`、`error_code`、`revision`、`trace_status`（4.7 派生状态）、`citation_count`、`conflict_flag`。
- 阶段明细：`trace_id`、`attempt`、`replayed`、`previous_trace_id`、`path`、`spans[{name, started_at, duration_ms, status, error_code, attribute_keys}]`；阶段标签按第 4 节映射。
- 引用摘要：`source_id`（哈希/标识）、`document_id`、`version_id`、`version_number`、`status(active/superseded/deleted)`、`locator`、`published_at`；冲突来源带 `conflict_flag`。
- 批次摘要：5.1 白名单字段 + `holdout_detected/details_withheld/degraded_reason`。
- 窗口口径：`window(preset|custom)`、`since/until(UTC ISO, 左闭右开)`、`timezone=Asia/Shanghai`、`coverage{covered, total, status}`。

---

## 7. 样本来源与独立复算（工作包 B 交付摘要）

样本生成、隔离库、矩阵与复算结果由工作包 B 在 `T301-isolated/` 目录交付，本文不写入该目录。固定引用文件（均已存在，合并时由项目经理对账）：

- 样本矩阵：[T301-isolated/T301-sample-matrix.md](T301-isolated/T301-sample-matrix.md)
- 独立复算表：[T301-isolated/T301-recomputation.md](T301-isolated/T301-recomputation.md)
- Trace 实测探针：[T301-isolated/T301-trace-probe.md](T301-isolated/T301-trace-probe.md)

### 7.1 样本构成（19 条）

- **正常入口 14 条**：FastAPI 接口链路 + Mock 替身（S01、S02、S03、S04、S05、S06、S07、S08、S10、S11、S12、S13、S14、S15）。
- **正常入口故障替身缝 1 条**：S09（knowledge_changed；HTTP 链路正常，检索阶段注入 revision 变更异常）。
- **受控样本 4 条**（直接写隔离库，已标注来源）：S16（running 未提交中断）、S19（expired 未提交中断）、S17/S18（午夜边界固定完成时间）。

### 7.2 独立复算结果（全部一致）

| 口径项 | 复算实算 | 一致性 |
| --- | --- | --- |
| 请求行总数 / 范围内（排除已删除会话） | 16 / 15 | 一致 |
| 已完成问答量（产品请求 ID 去重） | 13 | 一致 |
| 六类结果分布 | answer 8、clarification 1、not_found 1、conflict 1、service_error 1、knowledge_changed 1 | 一致 |
| 未提交中断（单列，不入六类） | 2（running / expired） | 一致 |
| 非冲突持久引用行 | 13 | 一致 |
| 文档维去重对（消息+文档，非冲突） | 6 | 一致 |
| 版本维去重对（消息+版本，非冲突） | 6 | 一致 |
| 待审核版本数（review_required） | 1 | 一致 |
| 失败导入任务 | 1，错误码 `PARSE_INCOMPLETE` | 一致 |
| Trace 覆盖率 | 10/13（0.7692）；纯重放 1 不计覆盖、关闭态 1、未记录 2 | 一致 |
| 午夜边界归属日 | S17 → 2026-11-20；S18 → 2026-11-21（Asia/Shanghai，左闭右开 UTC 窗口） | 一致 |
| 已删除会话 | S10 统计侧与下钻侧双侧排除 | 一致 |
| D5 冲突引用行 | S05 落 `MessageSource` 2 行（两方来源均 active）；独立只读 SQL 复核同为 2 行 | 实测与代码路径一致，差异口径见 4.6 / 6.3 |

### 7.3 验收执行记录

- 开发自测：`backend/` 下 `..\.venv\Scripts\python.exe -B -m pytest -c pyproject.toml` 接隔离测试路径，退出码 0，1 通过 / 0 失败 / 0 跳过。
- 项目经理独立复跑：副本目录 `T301-acceptance-rerun/` 下同命令退出码 0，1 通过 / 0 失败 / 0 跳过；另以自写只读 SQL 对 B 交付库做 26 项核对，全部 PASS（`RESULT: ALL-PASS`）。
- 证据文件（P3 目录，项目经理产出，本包未改动）：`T301-acceptance-rerun-evidence.txt`、`T301-acceptance-verify-output.txt`。
- 样本覆盖任务书抽查项：带引用回答、未找到、冲突、幂等重放、Trace 关闭态、换版（superseded）历史引用；每个首版指标（第 3 节）均有来源、时间字段、去重键、过滤条件与空值语义。

---

## 8. 证据与辅助文件清单（本工作包 A 产出，均在 `docs/reports/OBS-EVAL/P3/`）

| 文件 | 用途 |
| --- | --- |
| `T301-data-audit.md` | 本文档（独占交付物） |
| `T301-audit-git-output.txt` | git 只读命令实际输出（分支/HEAD/提交/在途改动） |
| `T301-audit-probe.py` | 原库只读探针（仅 SELECT；打开原库 `mode=ro` 语义，不写原库） |
| `T301-audit-probe-output.txt` | 探针计数输出（第 1.4 节、第 2 节实测依据） |
| `T301-audit-tables.py` | 表清单/行数核对脚本（只读） |

> `T301-isolated/` 归工作包 B 独占，本包未在其中写入任何文件。

---

## 9. 口径缺口、代码冲突清单与已知限制

### 9.1 待上报 / 待对账事项

| 编号 | 类型 | 描述 | 证据位置 | 处置建议 |
| --- | --- | --- | --- | --- |
| D5 | 代码 ↔ 任务书口径出入（已实测确认，待主人裁决） | 冲突消息持久引用行：任务书 §2 规定不产生；代码把冲突来源纳入引用集，清空动作未覆盖 conflict 分支，active 来源写 `MessageSource`。**B 隔离样本 S05 实测落 2 行，项目经理独立只读 SQL 复核同为 2 行** | `conversations/service.py:1970-1979`、`2016-2024`、`2036-2038`、`2066-2086`；`sources/service.py:44-66`；`T301-acceptance-verify-output.txt` 第 10-11 行；`T301-isolated/T301-recomputation.md` §5.1/§8.2 | API 约定按任务书口径冻结（6.3）；T302 查询侧按 `kind='conflict'` 排除最终引用计数即满足口径；是否修提交链路代码上报主人裁决，P3 只读范围外 |
| D1/D2 | 代码埋点超出任务书列举 Span | 多出内部/条件/失败分支 Span（清单见 4.6） | 4.2、4.3 表内行号 | 页面主阶段标签只映射业务必需 Span；子 Span 作为可展开细节；不改动任务书 |
| D3 | 路径枚举第三值 | `legacy_with_rag_candidates` 未在任务书两套路径表述中 | `contracts.py:36`、`service.py:2648` | 按 legacy 变体处理，映射复用 legacy |
| D4 | outcome 枚举与业务六类不一致 | Trace outcome 为超集；六类分布以业务消息 kind 为准 | `contracts.py:39-50`、`qa/service.py:582` | 接口层区分两套枚举，不混用 |
| G1 | 本地 `var/` 快照缺样本（已由 B 隔离矩阵补齐） | 中断请求、conflict、knowledge_changed、重放 Trace、关闭 Trace、失败导入、待审核版本、换版历史引用在本地快照未出现；B 隔离样本 S01-S19 已覆盖并复算一致（见第 7 节） | 探针输出 `T301-audit-probe-output.txt`；`T301-isolated/T301-sample-matrix.md`、`T301-recomputation.md` | 隔离复算已闭环；首版空态语义已在第 3、6 节冻结；重试 attempt>1 仍无样本，后续真实流量补充 |
| G2 | 无批次列表接口 | 现有仅单 run 查询；列表/白名单筛选待 T302 | `routes.py:838-886` | T302 按第 5 节规则实现 |
| G3 | 冲突来源聚合无现成查询 | 「相关问答含冲突并标注」「最终引用不含冲突」需新查询服务 | 第 2.2 节 | T302/T305 实现，口径按 6.3 |
| G4 | 启动路径变更 | `04515f3`、`0d6ba61` 改动一键启动脚本与 `tools/start_local.py` | 1.2 节 git 输出 | 纳入 T306 启动/回退与 P2 回归核对 |

### 9.2 已知限制

- 本次审计基于 `codex/p2-e2e` @ `0d6ba61` 源码与当前本地库快照；试用流量、Trace 覆盖率、查询性能、第三方组件集成效果尚待实测（设计稿 §8 同口径）。
- 未运行付费/真实调用；隔离样本与复算已由工作包 B 交付并经项目经理独立复跑 / 只读 SQL 复核闭环（见 7.3）；隔离离线替身环境的 Span 时长不代表线上性能。
- 跨版本条款匹配、候选集/排名/分数采集、组织部门维度、员工活跃趋势不在首版范围（设计稿 §2、§4）。
- 本包未生成 OpenAPI 类型、未安装 echarts；未改任何现有文件，未写 `var/` 原库。

# P2 产品端到端运行器契约 v0.1（T203）

状态：**candidate（T203 交付）**，schema_version 见各节；未经 T900 独立验收前不得当作正式基线。

本契约只冻结 T203 新增的两个模块接口与产物，**不改** T201 的 `p2_contracts.py` /
`p2_authorization.py` 中已接收的 DTO 与固定路径语义，也不改产品 API/schema。

## 1. 模块与冻结接口

### 1.1 `mktkb.evaluation.product_adapter.ProductEvalAdapter`

```python
ProductEvalAdapter(
    out_dir: Path | str,                 # 隔离根目录（业务库/索引库/存储/trace 全在其下）
    *,
    ingest_plan: P2IngestPlan | None = None,
    dataset: P2RunDataset | None = None, # run_p2 缺省时从这里取
    chat: MockChatBackend | None = None, # None = 不注入网关（应用里 model_gateway=None）
    users: Sequence[tuple[str, str]] = (("admin", ...), ("employee", ...)),
    turn_timeout_seconds: float = 60.0,  # = conversations.service.BUDGET_SECONDS
    trace_enabled: bool = True,
    trace_content_mode: str = "hash",    # 只允许 off/hash（产品 tracer 的既有约束）
    purge_traces_on_close: bool = False, # holdout run 必须为 True
    label: str = "",
)
```

| 方法 | 语义 |
|---|---|
| `async start()` | 建隔离 `Settings`（`_env_file=None`，不读 `.env`）→ `create_app` → 登录隔离账号。幂等。 |
| `async ingest(plan=None)` | 走产品 `POST /documents`（或 `/documents/{id}/versions`）→ `ingestion.worker.run_one_job` → `POST .../publish`；返回 `IngestReceipt` 列表。**不复制**解析/发布逻辑。 |
| `async ask_turn(question, *, user_id, conversation_id, client_request_id)` | 走产品 `POST /api/v1/conversations/{id}/messages`（含 Origin/CSRF/会话）；返回 `ProductTurn`。**不调用** `RagIndex.ask`。 |
| `async close()` | 关闭产品应用/网关/索引/客户端；`purge_traces_on_close` 时删除 trace 库；holdout（`require_holdout_sealing()` 标记过）时**删除隔离业务库**（题干明文）。 |
| `open_conversation(*, user_id, title=None)` / `source_detail(message_id, source_id, *, user_id)` / `list_messages(conversation_id, *, user_id)` / `messages_in_db(conversation_id)` | 只读/建会话的观测面，全部走产品路由。 |
| `provider_calls()` / `network_stats()` / `index_status()` / `trace_of(trace_id)` | 观测面：provider 计数与**实测**网络边界（`outbound_network` = chat 注入传输的真实出站 + RAG 供应商 POST 增量；Mock 链上为 0，拦截数另计）、索引状态、产品 trace 记录。`provider_calls()` 的 `outbound_network` 分三层语义：**顶层**是唯一真值；`network` 是它的**分解**（`chat_outbound_attempts` + `rag_provider_posts`）；`chat/embedding/rerank/ocr` 各自的 `outbound_network` 是该 provider 的实测出站（chat = 计量传输真实出站；embedding/rerank 为离线替身、无传输层，结构性 0）。 |
| `require_holdout_sealing()` / `seal_question_store()` | H2 封存：标记后 `close()` 删除 `data/mktkb.sqlite3`（会话/消息/请求表里的题干明文）并返回 `{"question_store": "deleted", ...}`；删不干净直接报错。 |

不变量：`is_mock is True`（本包只提供 Mock）；不构造真实 provider；不碰原 `var/`；
不写共享账本/GO。

### 1.2 `mktkb.evaluation.p2_runner.run_p2`

```python
async def run_p2(
    plan: P2RunPlan,
    *,
    adapter: ProductEvalAdapter,
    authorization: P2Authorization,
    dataset: P2RunDataset | None = None,     # 缺省取 adapter.dataset
    gate: Any | None = None,                 # None = dry-run；给出时走 T201 门序
    cancel: Callable[[], bool] | None = None,
    now: datetime | None = None,
    settle_evidence: Callable[[Any, ProductTurn], Any] | None = None,  # T206 注入真实 UsageEvidence
) -> P2RunResult
```

诚实偏差声明（相对任务书 §6.2 的 `run_p2(plan, *, adapter, authorization)`）：
1. `dataset`/`gate`/`cancel`/`now`/`settle_evidence` 都是**带默认值的关键字参数**，
   所以 §6.2 的三参数调用形式仍然成立（dataset 从 `adapter.dataset` 取）；
2. 返回 `P2RunResult`（T201 DTO，不新增返回类型），逐题/逐轮细节写在产物文件里。

### 1.3 `build_dry_run_authorization(plan, preflight, *, issued_by, ttl_seconds, now, nonce)`

由**已通过的**离线预检构造空跑授权：`go_document="P2-DRY-RUN"`、`go_nonce_len>=16`（本串长度）、
`ledger_path="in-memory:dry-run"`、`production_ready=False`。它不是 GO，也不能当 GO 用。

## 2. 三种执行类别（`execution`）

| 值 | 条件 | 资金事实 | 真实发送 |
|---|---|---|---|
| `dry_run` | `gate is None` 且 `adapter.is_mock` | 无预留/无结算 | 0 |
| `mock_gate` | `adapter.is_mock` 且 `getattr(gate, "is_mock_gate", False) is True`（**桩门**） | 只有桩门记录，无账本 | 0 |
| `live` | 非 Mock 适配器 + **真实 `P2Gate`**（`isinstance(gate, P2Gate)` 且无 `is_mock_gate` 标记） | 走 T201 真实预留/结算 | 需 `production_ready=True` |

规则（任一不满足即**发送前**停，`status=blocked`）：
- 真实适配器配 `gate=None` → 拒绝（`adapter_must_be_mock`）；
- Mock 适配器配**真实门** → 拒绝（`mock_gate_requires_stub_gate`）；
- `live` 且 `authorization.production_ready=False` → 拒绝（`production_not_ready`，T201 遗留 ①）；
- `live` 且门是桩门/鸭子门而不是真实 `P2Gate` → 拒绝（`live_requires_real_gate`，R1/F2）；
  桩门只能在 `mock_gate` 链上验证门序，不能出现在 live 链上；
- `visibility=holdout` 且 `purge_traces_on_close=False` → 拒绝（`holdout_requires_purge`，R1/F3）：
  一行都不执行（不灌库、不建会话、不调 provider），trace 库也不会被创建。

`gate.json.real_sends_allowed` 只在 `live` + `production_ready=True` + **全部发送前检查通过**时为 true；
桩门导致的 `live_gate` 不通过会把它压成 false。

## 3. 产物（`<out_dir>/p2-run/`）

| 文件 | 出现在 | 内容 |
|---|---|---|
| `run_manifest.json` | 全部 | run/plan/mode/scope、dataset 身份（version/label/suite/manifest_sha256/case_count/strata）、plan 摘要与预算、授权快照（go_sha256/nonce_len/production_ready）、pipeline（入口、turn 超时、trace 模式、索引统计、两个模块的 `code_sha256`）、provider 身份、隔离路径、ingest 回执 |
| `summary.json` | 全部 | status/stop_code、execution、cases/turns 计数、kinds、branches（`rag`/`legacy`/`legacy_with_rag_candidates`/`none`）、requests（`scope="answer_turns"`；planned/attempted/reserved/settled/**real_requests、billed_cny 均为实测**，另有 `conservative_held_cny`/`provider_billed_cny`/`unpaid_rounds` 三段与 `failed_rounds` 别名、`rejected_rounds`（J1 拒绝轮），见 §7）、attempts（`scope="all_attempts"` + 逐次核对）、providers、network（**outbound_attempts 实测** + `detail` = 该值的分解，见 §5）、failure（含 stage 与在飞 ticket）、holdout 策略（`question_store` 是**策略标签** `policy:*`，不是"已删"的测量结论） |
| `run_result.json` | 全部 | `P2RunResult.as_dict()`（sent<=reserved<=planned） |
| `gate.json` | 全部 | 门/授权检查逐项结果、`real_sends_allowed`、拒绝原因、`quality_gate="deferred-to-T205"` |
| `cases.jsonl` | 仅 `visibility="public"` | 逐题行：会话 id、逐轮 kind/trace_id/trace_path/trace_outcome/http_status、产品来源、ticket、是否计费 |
| `requests.jsonl` | 仅 `visibility="public"` | 逐次请求身份：item_id、client_request_id、ticket（request_id/reservation_id/cost_center/bound_cny/dry_run）、billed、status、error_code、elapsed_ms、`provider_calls`（本轮实测增量：chat/embedding/rerank/outbound）、`charged_cny`（该笔实际结算金额） |
| `holdout_aggregate.json` | 仅 `visibility="holdout"` | 只含计数/分层/分支/kind 聚合、stop_code 与**脱敏**失败（无 case_id、无题干、item_id 只留 sha256） |

holdout 额外约束：
- 不写 `cases.jsonl`/`requests.jsonl`；trace 用 `content_mode=hash`（题目只留哈希）；
- `purge_traces_on_close=True` 是硬前提，否则 runner 直接拒绝（`holdout_requires_purge`，见 §2）；
- `close()` 时删除 trace 库（`summary.holdout.trace_retention="purged-at-close"`），
  并**删除隔离业务库** `data/mktkb.sqlite3`（会话/消息/请求表里有题干明文）；删除失败即报错，
  不允许"以为删了"；
- `summary.holdout.question_store` 是**策略标签**，不是测量结论（A4/F3-a）：holdout 写
  `"policy:delete-at-close"`、公开/dry-run 写 `"policy:keep-in-isolated-dir"`，且 summary 在
  `close()` **之前**落盘，产物无法自证"已删"。真正的证据是 `close()` 的 `seal_receipt`
  （`{"question_store": "deleted", "removed": [...]}`，删不干净直接抛错）；标签值前缀写死
  `policy:`，并另有 `question_store_measurement` 说明测量入口，避免把标签读成测量；
- 证据口径：holdout run 的 `out_dir` 在 close 之后不得再出现题干明文（哨兵题干测试
  `test_holdout_close_removes_question_plaintext_from_out_dir` 覆盖）；聚合产物不受影响，
  公开 run 与 dry-run 路径不删业务库（`question_store="policy:keep-in-isolated-dir"`）。

## 4. 停止码（稳定，可机读）

| stop_code | 阶段 | 含义 |
|---|---|---|
| `plan_authorization_mismatch` | authorization | 授权未绑定本 plan/不是 P2-LIVE |
| `authorization_expired` | authorization | 过期/尚未生效 |
| `operation_unauthorized` | authorization | 计划含未授权操作 |
| `request_cap_exceeded` | authorization | 计划请求数 > 授权剩余 |
| `adapter_must_be_mock` | authorization | dry-run 却给了非 Mock 适配器 |
| `mock_gate_requires_stub_gate` | authorization | Mock 适配器配了真实门 |
| `production_not_ready` | authorization | live 但没有 production_ready |
| `live_requires_real_gate` | authorization | live 但门不是真实 `P2Gate`（桩门/鸭子门），发送前拒绝 |
| `holdout_requires_purge` | holdout_policy | holdout run 没有 `purge_traces_on_close=True`，一行都不执行 |
| `ingest_failed` | ingest | 上传/解析/发布失败（不重试） |
| `plan_item_missing` | plan | 某 case 的某轮没有 answer 计划项 |
| `open_conversation_failed` | open_conversation | 建会话失败 |
| `gate_error` | gate_begin / gate_settle | 门内部错误/结算失败 |
| `pre_send_refused` | gate_confirm | 预留后发送前复核失败（产品侧 0 次调用） |
| `adapter_error` | product_call | 适配器/产品调用异常 |
| `turn_timeout` | product_wait | 产品单轮 60 秒总时限（客户端硬截止，不重试） |
| `product_service_error` | product_answer | 产品 `service_error`（模型/索引等），**此后不再发送** |
| `cancelled` | cancel | 外部取消（在 case 之间检查） |
| `no_case_executed` | execute | 空跑：一轮都没执行 → `blocked`（不冒充成功） |

`status` 取值仍用 T201 的 `P2_RUN_RESULT_SCHEMA_VERSION`：`succeeded`（全部计划的 answer 轮执行完且
无停止）/ `aborted`（执行过但中途停）/ `blocked`（发送前拒绝或零轮执行）。

## 5. 与既有约束的关系

- P1 `live.py` 的 `LIVE_SCOPE=retrieval_only`、零 chat 与 `production_ready` 语义不动；
  本模块不 import `live.py`，也不放宽它；
- `P2Authorization`/`P2Gate` 的固定账本/GO 路径不动；本包不写账本；
- 实测口径：`summary.requests.real_requests` = 本轮**实际出网**（`provider_calls().outbound_network`
  每轮增量 >0）的请求数；`summary.requests.billed_cny` = 这些请求的实际结算金额（`settle_*` 回执）；
  `summary.network.outbound_attempts` = 适配器实测总出站。三者都**不是常量**：Mock 链上由测量得到 0，
  换成真实传输同一个计数器就会 >0；缺测量字段时 runner 直接报错，不静默按 0 处理；
- `network.detail` 只是 `summary.network.outbound_attempts` 的**分解**，不是第二份真值（A1/F1-a）：
  必须给出 `outbound_attempts`、`chat_outbound_attempts`、`rag_provider_posts`，且满足
  `chat_outbound_attempts + rag_provider_posts == detail.outbound_attempts == 顶层 outbound_network`。
  任一等号不成立（含缺 `network` detail）→ runner 抛稳定错误码
  `provider_network_detail_mismatch`，**不静默拼接/覆盖**，也不挑一个"看起来对"的值写产物；
  同理，`summary.providers.<name>.outbound_network` 是明细展示（供旧 probe / 人工核对），不与顶层独立；
- 产品单轮 60 秒口径直接取 `conversations.service.BUDGET_SECONDS`，不另立常量。


## 6. T206-PRE 追加：绑定与失败语义（v0.1 增补，不改上文口径）

- **评测身份**：`run_manifest` 顶层新增 `suite/dataset_version/dataset_sha256/
  corpus_manifest_sha256/business_date/index_revision/pipeline_version/gate_version/
  gate_config_hash/label_version/created_at/case_count/config_hash/dataset_path/trace_store`，
  可直接作为 `build_gate_run(manifest=...)` 的输入；另有 `binding` 块记录组件与是否完整。
  公开 run 额外落 `dataset.jsonl`（H2 不落题面，`dataset_path` 为空 → gate 记 unknown）。
- **trace 身份**：`run_id/dataset_version/manifest_sha256/pipeline_version/index_revision/
  config_hash` 六字段齐全才绑定，缺一项整体不绑；未绑定即 `trace_integrity` fail-closed。
- **引用证据**：每轮 `product.evidence`（unit_id/unit_key/locator/document_id/version_id/
  version_number/state/active/in_run/verified）来自产品库只读解析；`summary.citation_evidence`
  与 `gate.json.citation_evidence` 给出 `complete` 与计数。
- **失败也写产物**：产物校验失败（如 `provider_network_detail_mismatch`）时写
  `run_manifest/summary/run_result/gate`（+ holdout 聚合）后**再抛出**同一稳定码；
  `summary.network.available=false`、`summary.providers=null`、`gate.json.real_sends_allowed=false`。
- **run_id 必填**：`run_p2(run_id=...)` 传空/非 str → 发送前 `P2RunError("run_id_missing")`。
- 完整口径（确定性 config_hash、错误码表、fail-closed 矩阵）见
  `docs/evaluation/p2-live-binding-v0_1.md`。

## 7. T207-FIX-B 增补：answer 单侧 / 全量尝试 / 三段金额（additive）

本节只**新增口径**，不改 §1–§6 的字段语义、判定与阈值。

### 7.1 两个"规模"口径必须同时写出来

| 位置 | 口径 | 含义 |
|---|---|---|
| `summary.requests.scope` = `answer_turns`；`run_result.requests_*`/`by_operation`/`by_center_cny` | answer 轮单侧 | runner 逐轮的 answer 预留与结算（旧键语义不变） |
| `summary.attempts.scope` = `all_attempts`；`run_result.attempts_*` | 全量底层尝试 | answer 轮 + 从属尝试；`attempts_reserved` 与 `gate.json.attempts.gate_reserved` 同值 |

`run_result.attempts_scope=unavailable` 表示没有逐次尝试账（发送前停、或 `P2Gate.result()` 那一侧），
此时 `attempts_*` 为空/0，**不**用 answer 口径冒充。新增断言：`run_result.attempts_reserved ==
gate 的唯一 reservation 数`（`test_p2_live_wiring.py`），旧产物缺这些键仍可读。

### 7.2 `summary.requests` 的三段（互不冒充）

| 键 | 含义 | 是否供应商账单 |
|---|---|---|
| `conservative_held_cny` | 本次 run 在门/账本里**已写 result** 的保守占用总额（answer + 从属；含失败、零付费轮与 J1 拒绝轮的整笔上界） | 否（记账口径） |
| `provider_billed_cny` | 其中**带供应商证据**的金额：answer 轮里真的付过款并成功结算的笔 + 从属尝试里 settle 成功的笔（usage 结算或 OCR 固定页价） | 是"按官方 usage/页价重算"的金额，仍不是账单 |
| `unpaid_rounds` | 预留了但**没有任何付费发送**的 answer 轮数（账本写 `status=failed` + `P2_NO_PAID_ATTEMPT:<reason>`，**不**停止） | 否 |
| `rejected_rounds` | **J1 拒绝轮**：answer 轮在 `settle_success` 被拒（如 usage `total_mismatch`/`cache_split_mismatch`/`over_cap_*`、`SettlementNotReleasable`/`SettlementBoundaryAnomaly`），run 以 `stop_code=gate_error` 停止 | 否 |

兼容键：`settled_failure` = `failed_rounds`（**真实失败结算**轮数，`settle_failure`）；
`unused_no_paid_attempt` = `unpaid_rounds`；`billed_cny` = **真实出网**请求行的结算金额之和
（实测口径，不是账单）。账本 schema 与 `status` 集合**不动**：`status=failed` 既可能是真实失败，
也可能是"零付费轮按上界保守留账"，区分只看 `error_code` 前缀 `P2_NO_PAID_ATTEMPT:`。

**J1 拒绝轮的归属与计数（T207-FIX-B-R1，additive）**：answer 轮在 `settle_success` 被拒时，
门内账本**已经**按该笔预留上界写了一条保守 `result`（`status=unknown`，
`conservative_charge_cny` = 上界，`error_code=SETTLEMENT_NOT_RELEASABLE:<reason>`），
随后门把异常转成 `gate_error` 并停止。这类轮次：

- **金额**按同一上界计入 `conservative_held_cny`（runner 的 `settled_cny` 与中心归属同时累加），
  因此 `conservative_held_cny` == 本 run 账本 `result` 保守占用合计（含该笔）；
- **计数**只进 `rejected_rounds`，与 `settled_success`/`settled_failure`（= `failed_rounds`）/
  `unpaid_rounds` **互斥**：不算成功结算，也不算真实失败结算；
- `requests_sent` 仍只数 `settled_success + settled_failure`（门没有把这笔计成 sent），
  `provider_billed_cny` 也不含它（没有按官方 usage/页价重算的金额）；
- `run_result.settled_cny`（answer 单侧旧键）同样含该笔上界；`requests.jsonl` 该行的
  `charged_cny` 写该上界、`billed=false`、`status=error`、`error_code=gate_error`。

`SettlementBoundaryAnomaly`（重算额高于预留的安全网）停在同一分支，但账本按**更高**重算额
入账并标 `boundary_anomaly`：门不把异常金额暴露给 runner，因此 runner 侧仍按上界记
（只可能少记、不会虚增），`rejected_rounds` 同样计 1；这是已知限制，不是静默吞掉。

### 7.3 `output_valid` / `paid_attempt` 的语义

- `output_valid` 由 `p2_live.chat_output_validity` 用**这一份真实输出**的三判据算出：
  `finish_reason == "stop"` + 内容非空 + purpose 对应的解析结构存在（answer=`source_ids`、
  expansion=`query_terms`，客户端只在 JSON 对象解析成功后才构造这些字段）。缺一项即
  `output_valid=False`，并同时把 `content_complete`/`content_parse_ok` 置 False —— 该笔在 J1 侧
  被拒（`content_incomplete`/`content_not_parsed`/`finish_reason_not_stop`），按保守上界留账。
  调用方（`make_settle_evidence` / `query_expansion`）必须显式传判据；缺省 = 无效（fail closed）。
- `paid_attempt=False` 是**轮次结局标签**（零付费：合法拒答/澄清/未找到/知识变更），不是"输出无效"；
  它对应账本的 `P2_NO_PAID_ATTEMPT:*` + 全额保守留账，且**不**停止后续请求。

### 7.4 run 产物 -> 评分/决策/观测矩阵（T207-FIX-A additive）

`p2-run` 只写产物；把它变成结论的是三个**只读**驱动（都在 `mktkb.evaluation`）：

- `p2-score --run-dir <run> --cases <计划内 CaseSpec jsonl> --document-codes <json>`：
  逐题 `score_public_case` → `score_public_suites` → `scorecard.json` / `case_scores.json`；
  再走 `build_gate_rows` → `build_gate_run` → `evaluate_p2_hard_gates` → `evaluate_p2_gate` 产 `p2_decision.json`。
  缺题/`error`/未执行一律如实出 block（`case_not_executed` / `case_error` / `missing_case`），不补不猜；
- `p2-score --visibility holdout`：受控进程内 `load_p2_dataset(visibility="holdout")` 取 CaseSpec/分层，
  再用**工作区外**的封存逐题行（`--holdout-cases`）或判定表（`--verdicts`）做 `aggregate_holdout`，
  只写聚合（`holdout_scorecard.json`）；**两个输入必须显式二选一**（T207-FIX-A-R1 落码）：
  都缺 → `holdout_input_missing`、都给 → `holdout_input_conflict`，两者都在解封/读数据集**之前**
  fail closed（exit 3、不写任何产物），不按计数编造 pass/fail；
- `p2-matrix --case-scores <R1/R2/R3 的 case_scores.json> --u-controls <json>`：合并逐题分数 + U 证据表，
  写 `matrix_observation.json`（逐 case `run_id/index_revision/config_hash/basis`、B0/N/C/U tallies、
  `composition=multi_run_scenario_isolated`、`release_decision=false`、`gate_config_unapproved`）。

口径（不得混用）：

- `scorecard.real_calls` 是**逐题可归属**的真实调用数；驱动不给逐题虚构归属，故逐题记 0，
  run 级实测值写在 `RunScore.real_calls`（`summary.network.outbound_attempts`，缺失时退 `attempts.reserved`）；
- `execution_mode` 来自 `run_manifest.execution`（`live` 才标 live），mock run 永远不会被标成真实；
- 判定必然是 `gate_config_unapproved`（unknown）+ `holdout_missing`（公开 run）——观测值，不是放行结论；
- `p2-u-controls` 只跑既有 `backend/tests/acceptance/test_t09_mutation.py` 并解析 junit XML 导出逐 U 判定
  （basis=L，不改该测试、不新增 skip）；同一 U 的任一 parametrize 变体失败即该 U 判 fail。

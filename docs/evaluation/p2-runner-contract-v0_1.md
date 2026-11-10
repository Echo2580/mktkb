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
| `async close()` | 关闭产品应用/网关/索引/客户端；`purge_traces_on_close` 时删除 trace 库。 |
| `open_conversation(*, user_id, title=None)` / `source_detail(message_id, source_id, *, user_id)` / `list_messages(conversation_id, *, user_id)` / `messages_in_db(conversation_id)` | 只读/建会话的观测面，全部走产品路由。 |
| `provider_calls()` / `index_status()` / `trace_of(trace_id)` | 观测面：provider 计数（含 `outbound_network=0`）、索引状态、产品 trace 记录。 |

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
| `live` | 非 Mock 适配器 + 真实 `P2Gate` | 走 T201 真实预留/结算 | 需 `production_ready=True` |

规则（任一不满足即**发送前**停，`status=blocked`）：
- 真实适配器配 `gate=None` → 拒绝（`adapter_must_be_mock`）；
- Mock 适配器配**真实门** → 拒绝（`mock_gate_requires_stub_gate`）；
- `live` 且 `authorization.production_ready=False` → 拒绝（`production_not_ready`，T201 遗留 ①）。

## 3. 产物（`<out_dir>/p2-run/`）

| 文件 | 出现在 | 内容 |
|---|---|---|
| `run_manifest.json` | 全部 | run/plan/mode/scope、dataset 身份（version/label/suite/manifest_sha256/case_count/strata）、plan 摘要与预算、授权快照（go_sha256/nonce_len/production_ready）、pipeline（入口、turn 超时、trace 模式、索引统计、两个模块的 `code_sha256`）、provider 身份、隔离路径、ingest 回执 |
| `summary.json` | 全部 | status/stop_code、execution、cases/turns 计数、kinds、branches（`rag`/`legacy`/`legacy_with_rag_candidates`/`none`）、requests（planned/attempted/reserved/settled/**real_requests=0**/billed_cny）、providers、network（outbound_attempts=0）、failure（含 stage 与在飞 ticket）、holdout 策略 |
| `run_result.json` | 全部 | `P2RunResult.as_dict()`（sent<=reserved<=planned） |
| `gate.json` | 全部 | 门/授权检查逐项结果、`real_sends_allowed`、拒绝原因、`quality_gate="deferred-to-T205"` |
| `cases.jsonl` | 仅 `visibility="public"` | 逐题行：会话 id、逐轮 kind/trace_id/trace_path/trace_outcome/http_status、产品来源、ticket、是否计费 |
| `requests.jsonl` | 仅 `visibility="public"` | 逐次请求身份：item_id、client_request_id、ticket（request_id/reservation_id/cost_center/bound_cny/dry_run）、billed、status、error_code、elapsed_ms |
| `holdout_aggregate.json` | 仅 `visibility="holdout"` | 只含计数/分层/分支/kind 聚合、stop_code 与**脱敏**失败（无 case_id、无题干、item_id 只留 sha256） |

holdout 额外约束：不写 `cases.jsonl`/`requests.jsonl`；trace 用 `content_mode=hash`（题目只留哈希），
并在 `close()` 时删除 trace 库（`summary.holdout.trace_retention="purged-at-close"`）。

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
- 产品单轮 60 秒口径直接取 `conversations.service.BUDGET_SECONDS`，不另立常量。

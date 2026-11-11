# P2 运行契约 v0.1（T201 冻结）

> 状态：**T201 开发交付，待独立验收**。本文件冻结 P2 的计划/预检/授权/结果接口与稳定原因码；
> 后续 T202–T208 不自行另定义同名概念。T201 只产候选配置与 Mock 证据：**零真实调用**，
> 不签发可用 GO，不修改原 budget/GO/账本，不宣称 P2 通过。

## 1. 不变量

1. 资金只有一只真账：仓库内固定共享账本 `docs/evidence/LOCAL-R1-20261101/budget/live-ledger.jsonl`
   与固定预算 `docs/evidence/LOCAL-R1-20261101/budget/budget.json`。P2 不新开账本、不清零、不回滚历史。
2. 阶段硬顶与成本中心同时生效：净新增阶段 `P2-LIVE`（候选 20 元）是硬顶；四个成本中心
   `answer_retrieval / ocr / judge / independent`（候选 12 / 3 / 3 / 2）各自限额，合计**必须等于**
   阶段额度。不存在「每个中心各花 20 元」。
3. 请求上限是**累计**口径：直接取账本里的 reservation 计数（历史 505 次照旧计入），
   硬顶 `HARD_MAX_REQUESTS = 1600`（= `live_authorization.MAX_GO_REQUESTS`，两处同值）。
   新增预算**不重置**已用计数。
   - 变更记录：2026-11-11 经理按主人 2026-11-10 预授权「必要时应实算提至 ≤2000，且 GO 在
     P2≤50 元、累计请求≤2000 内由经理拟定」落盘 **1000 → 1600**（`T207-PM-decisions-01.md` §3）。
   - 实算依据：已用 547 + T207 公开 263 + H2 回合 144 + H2 灌库 ≤20 + T208 judge ≤160 +
     T900 独立复验 ≤107 = 1,241；+20% 余量 ≈ 1,489 → 取整 1600。
   - **到值即停**：累计到 1600 时，发送前的 `request_limit`（`P2Gate`）与
     `go_max_requests_over_hard_cap`（授权）一律拒绝；各计划自身的 `max_requests` 是更早的闸门。
   - 跨范围影响（如实）：`MAX_GO_REQUESTS` 同时是 **P1 `live_authorization`** 的天花板。本值只
     抬高"共同天花板"；P1 已签 GO 的 `scope.max_requests` 仍各自生效（引擎两侧取 `min`），
     因此**不构成**对 P1 的追加授权，也不改任何既有门槛。
4. 串行、自动重试 **0**：一次只有一个在飞请求；失败即停，后续请求在发送前被拒。
5. 旧 P1 GO 默认拒绝 P2，P2 GO 不能反过来给 P1 授权：
   - P2 只认 `document = P2-LIVE-GO`；`S2-LIVE-GO` → 稳定码 `legacy_go_document`；
   - `live_authorization` 拒绝阶段名前缀 `P2`（`P1_FORBIDDEN_STAGES`），旧 rag/chat 授权不会
     因为新增阶段而获得 OCR/judge 权限。
6. 价格不能自降：chat/embedding/rerank 的准入 caps 与费率下限、OCR 每页固定价都来自已核来源；
   计划只能引用，写小 / 漏填 / 填 0 都在构造期拒绝。
7. 每次真实发送前有两道门（预留前 + 预留后发送前）。任一失败都停在 HTTP 之前；
   已经发生的预留保持**保守占用**，不谎称 0、不擅自释放。

## 2. 固定路径与来源标记

| 名称 | 值 | 说明 |
|---|---|---|
| `P2_LEDGER_PATH` | 共享账本（同 P1） | 只读快照与预留都用它 |
| `P2_BUDGET_PATH` | 共享预算（同 P1） | 必须与授权用的预算对象逐字节一致 |
| `P2_GO_PATH` | `docs/evidence/LOCAL-R1-20261101/PM/P2-LIVE-GO.json` | 正式 GO 落点；T201 **不创建**此文件 |
| `P2_GO_DOCUMENT` | `P2-LIVE-GO` | P2 唯一合法 GO 文档名 |
| `P2_GO_SCHEMA_VERSION` | `p2-live-go/v0.1` | |

路径校验：不得是软链、必须解析到固定常量、必须存在。测试通过 monkeypatch 这三个常量指向
`tmp_path` 副本（本仓既有做法），生产代码不接受其它路径。

来源标记：GO/预算来自内存字典 → `production_ready = False`；来自固定路径且
`MKTKB_PROJECT_TOTAL_LIMIT_CNY` 已设置并与预算一致、且账本快照真的来自固定共享账本 →
`production_ready = True`。**runner 只允许在 production_ready=True 时发送真实请求。**

## 3. 计划 `P2RunPlan`（`p2-run-plan/v0.1`）

顶层字段（严格：缺字段/多字段都拒绝）：

| 字段 | 校验 |
|---|---|
| `schema_version` | 必须 `p2-run-plan/v0.1` |
| `plan_id` / `plan_version` | 非空、无空白 |
| `mode` | 必须 `end_to_end`（P2 是产品端到端，不是直接调 `RagIndex.ask`） |
| `stage` | 必须 `P2-LIVE`（旧阶段名 → `stage_invalid`） |
| `created_utc` | 带时区 ISO |
| `project_total_limit_cny` | 有限正数，≥ 阶段额度 |
| `stage_limit_cny` | 有限正数 |
| `max_requests` | 正整数，≤ 1600（= `HARD_MAX_REQUESTS`）；≥ 计划请求总数 |
| `cost_centers_cny` | 恰好四个已注册中心，各自为正，合计 == `stage_limit_cny` |
| `items` | 非空、`item_id` 唯一 |

计划项 `P2RequestItem`：`item_id / operation / cost_center / case_id / turn / page / requests /
price_profile / expected_success_cny`。

- `operation` ∈ 8 类：`index_embedding / query_embedding / rerank / query_expansion / answer /
  ocr / judge / independent`；
- `cost_center` 必须等于 `OPERATION_COST_CENTER[operation]`（换中心不能绕额度）；
- `price_profile.kind` 必须等于 `OPERATION_KIND[operation]`；
- OCR 项 = **一页一次调用**：`page ≥ 1`、`requests == pages_per_request == 1`；其它项 `page == 0`；
- `expected_success_cny` ∈ [0, 单次上界]；只用于「成功估价」分列，**不参与准入**。

派生（不写入文件、由代码计算）：`operations`、`total_requests`、`case_count`、`turn_count`、
`page_count`、`worst_case_cny`（Σ 上界×请求数）、`reserve_peak_cny`（串行单次峰值 = max 上界）、
`estimated_success_cny`、`requests_by_operation()`、`center_needs_cny()`、`center_estimates_cny()`、
`plan_sha256`（对 `as_dict()` 的排序键紧凑 JSON 取 SHA-256）。

case/turn/page/request 分别计数：同一题的多轮（`turn`）与每页 OCR 各占条目，1 题 != 1 请求。

## 4. 价格画像 `P2PriceProfile`

| kind | 必备字段（严格） | 冻结值 |
|---|---|---|
| `chat` | input/output 单价 + `prompt_tokens_cap` + `completion_tokens_cap` | 6144 / 800；≥ 2 / 8 元每百万 |
| `embedding` | `unit_price_per_million_cny` + `total_tokens_cap` | 4096；≥ 0.5 元每百万 |
| `rerank` | `unit_price_per_million_cny` + `total_tokens_cap` | 6000；≥ 0.8 元每百万 |
| `ocr` | `price_cny_per_page` + `pages_per_request` | 1；GeneralAccurateOCR=0.5、RecognizeTableAccurateOCR=0.15（必须相等） |

`provider/host/region/pricing_source/model` 必须与已核来源逐值一致（deepseek / bailian / tencent OCR）。
单次上界 `bound_cny` 由画像推出：chat `(6144×输入价 + 800×输出价)/1e6 = 0.018688`、
embedding `0.002048`、rerank `0.0048`、OCR `0.5 / 0.15`。计划不能声明自己的上界。

## 5. 预检 `preflight_p2(plan, snapshot)`

只读，不改文件、不预留。返回 `P2PreflightResult`（`p2-preflight/v0.1`）：
`ok / reasons / stage_limit_cny / stage_remaining_cny / total_limit_cny / total_remaining_cny /
max_requests / requests_used / requests_remaining / requests_planned / worst_case_cny /
reserve_peak_cny / estimated_success_cny / by_operation / center_limits_cny / center_needs_cny /
center_remaining_cny / production_ready`。`reserve 峰值` 与 `成功估价` 分列，互不冒充。

稳定原因码（按固定顺序追加）：

| 码 | 条件 |
|---|---|
| `budget_total_mismatch` | 快照总上限 != 计划声明的总上限 |
| `stage_allocation_missing` | 预算没有 `P2-LIVE` 阶段分配 |
| `stage_allocation_below_plan` | 阶段分配 < 计划的「阶段额度」（即声明被压缩）|
| `stage_budget_insufficient` | 阶段剩余（分配 − 已占）< 计划最坏上界 |
| `total_budget_insufficient` | 项目剩余（总上限 − 已占）< 计划最坏上界 |
| `request_budget_insufficient` | 累计请求余量 < 计划请求总数 |
| `center_budget_insufficient:<center>` | 某中心「已占 + 需要」> 中心额度 |
| `center_accounting_inconsistent` | 阶段占用无法完整归属到四个中心（存在无归属预留） |

账本快照 `P2LedgerSnapshot`（`p2-ledger-snapshot/v0.1`）由
`read_ledger_snapshot(ledger_path=None, budget_path=None)` 只读生成，复用
`BudgetLedger.summary()` 的保守重算（含版本化 result 重放），字段：
`ledger_path / ledger_sha256 / historical_prefix_sha256 / budget_sha256 / total_limit_cny /
historical_accounted_cny / accounted_cny / reservation_count / result_count /
stage_allocations_cny / p2_stage_accounted_cny / p2_center_accounted_cny / source`。
`source = fixed-paths | in-memory`；只有 fixed-paths 能用于真实准入。

## 6. 授权 `authorize_p2(plan, *, go_payload, budget_payload, ledger_snapshot, now=None)`

GO 顶层字段（严格）：`document / schema_version / stage / authorization / issued_by / nonce /
issued_utc / expires_utc / budget_ledger_path / budget_ledger_sha256 / budget_total_limit_cny / scope`；
`scope`：`plan_id / plan_sha256 / operations / cost_centers_cny / stage_limits_cny / max_requests /
max_request_cny`（无 `bindings`，避免在 GO 里夹带凭据）。

绑定关系：GO 的 `plan_sha256` 必须等于当前计划的摘要（同 nonce 换计划必失败）；
`budget_ledger_path/sha256` 必须指向并匹配固定共享账本的历史前缀；`operations`/`cost_centers_cny`
必须覆盖计划；`stage_limits_cny[P2-LIVE]`、`max_requests`、`max_request_cny` 不得小于计划需要。

稳定原因码：`legacy_go_document`、`go_document_invalid`、`go_schema_invalid`、`go_stage_mismatch`、
`field_missing`、`field_unknown`、`text_invalid`、`go_nonce_invalid`、`go_time_invalid`、
`go_not_yet_valid`、`go_expired`、`go_budget_total_mismatch`、`go_plan_id_mismatch`、
`go_plan_sha256_mismatch`、`go_operations_invalid`、`go_operation_invalid`、
`go_operation_unauthorized`、`go_cost_center_invalid`、`go_cost_center_unauthorized`、
`go_cost_center_below_plan`、`go_stage_limit_missing`、`go_stage_limit_below_plan`、
`go_max_requests_over_hard_cap`、`go_max_requests_below_plan`、`go_max_request_cny_below_plan`、
`go_ledger_path_missing`、`go_ledger_path_not_fixed`、`go_ledger_binding_mismatch`、
`budget_total_mismatch`、`budget_stages_invalid`、`budget_stage_missing`、`budget_stage_below_plan`、
`budget_ledger_path_not_fixed`、`budget_history_mismatch`、`env_total_limit_mismatch`、
`env_total_limit_missing`、`env_total_limit_invalid`、`snapshot_ledger_path_not_fixed`、
`path_symlink`、`path_not_fixed`、`path_missing`、`payload_invalid`、`json_invalid`、
`mapping_required`、`number_invalid`、`integer_invalid`、以及预检的 8 个码。

返回 `P2Authorization`（`p2-authorization/v0.1`）：stage/plan_id/plan_sha256/go_document/go_sha256/
go_nonce_len/issued_by/issued_utc/expires_utc/ledger_path/ledger_sha256（历史前缀）/budget_sha256
（授权用的预算对象摘要）/stage_limit_cny/stage_remaining_cny/cost_center_limits_cny/
center_remaining_cny/max_requests/requests_used/requests_remaining/max_request_cny/operations/
production_ready。摘要不含凭据，nonce 只给长度。

## 7. 运行门 `P2Gate`

    gate = P2Gate.open(plan, go_payload=None, budget_payload=None, ledger_snapshot=None,
                       now=None, clock=None, run_id=None)
    ticket = gate.begin(item_id)                 # 预留（锁内先过预留前门控）
    gate.confirm_before_send(ticket)             # 预留后 / 发送前的第二次门控
    ... 真实或 Mock 发送（ticket.request_id 作为幂等键）...
    gate.settle_success(ticket, evidence=..., usage=..., estimated_cny=...)
    gate.settle_failure(ticket, error_code="...") # 失败即停，零重试

`begin` 只接受 `item_id`：kind/provider/model/成本中心全部取自计划项，调用方不能换模型或换中心。
票据 `P2RequestTicket`（`as_dict()`）：`reservation_id / request_id / plan_id / plan_sha256 /
item_id / operation / cost_center / kind / provider / model / bound_cny / case_id / turn / page /
nonce_len`。

发送前拒绝链（全部在 HTTP 之前）：

| 场景 | 稳定码 | 账本后果 |
|---|---|---|
| 上一笔未结算 | `request_inflight` | 无新预留 |
| 已停机 | `gate_stopped` | 无新预留 |
| GO 过期 / 未生效 | `authorization_expired` / `authorization_not_yet_valid` | 已发生预留 → 保守 result（全额）|
| GO 换了计划 | `plan_sha256_changed` / `plan_id_changed` | 同上 |
| GO 撤了操作 / 中心 | `operation_unauthorized` / `cost_center_unauthorized` | 同上 |
| 账本前缀被改 | `ledger_prefix_mismatch` | 同上 |
| 中心余量不足 | `center_budget_exceeded` | 无新预留 |
| 中心归属不完整 | `center_accounting_inconsistent` | 无新预留 |
| 累计请求超限 | `request_limit` | 无新预留 |
| 阶段/总额不足 | `budget_exceeded` | 无新预留 |

「已发生预留」的拒绝一律写一条 `status=failed`、`error_code = P2_PRE_SEND_REFUSED:<code>`、
`conservative_charge_cny = 预留额` 的 result，并保留 `reservation_id / request_id / cost_center`；
不新增预留、不回 0、不释放。

`gate.result()` → `P2RunResult`（`p2-run-result/v0.1`）：`run_id / plan_id / plan_sha256 / status
(succeeded|blocked|aborted) / stop_code / requests_planned / requests_reserved / requests_sent /
reserved_cny / settled_cny / by_operation / by_center_cny / production_ready`；
不变量 `sent ≤ reserved ≤ planned`。

**T207-FIX-B/A（additive，旧键语义逐字不变）**：`requests_* / by_operation / by_center_cny` 是
**answer 轮单侧**口径；另增四个键描述**全量底层尝试**：`attempts_scope`
（`all_attempts` | `unavailable`）、`attempts_reserved`（= 本 run 唯一 reservation 数，与
`gate.json.attempts.gate_reserved` 同值）、`attempts_by_operation`、`attempts_by_center_cny`。
`attempts_scope=unavailable` 时三者必须为空/0（**不得**用 answer 口径冒充全量）；旧产物缺这些
键仍可读（按 `unavailable` 解释），新增键不升 `schema_version`（同 `p2-live-binding-v0_1.md` §7 的版本策略）。

## 8. 兼容接线（本次唯一改动的旧组件）

| 文件 | 改动 | 调用者与影响 |
|---|---|---|
| `rag/budget.py` | `reserve()` 新增可选 `cost_center`（落盘为 reserved 事件字段）；`_accounting` 增 `center_accounted`；`BudgetSummary` 增 `center_accounted_cny`（仅本阶段） | P1/S2 调用者不传该参数，行为不变；新增字段只是附加信息，旧断言仍成立（`test_budget*`、`test_s2*` 全通过） |
| `live_authorization.py` | 新增 `P1_FORBIDDEN_STAGES` 与 `_assert_p1_stage`（`load_live_authorization` 入口拒绝阶段名前缀 `P2`）；新增公开 `historical_prefix_sha256` | P1 合法阶段不受影响；P2 阶段无法借旧 rag/chat GO 授权（新增拒绝，不放松任何旧检查） |

## 9. 后续任务的调用约定

- **T203**：`P2Gate.open(...)` + 每笔 `begin/confirm_before_send/settle_*`；真实发送前断言
  `gate.authorization.production_ready`；trace 里带 `ticket.as_dict()`。产物用 `gate.result()` 的
  `P2RunResult`，不要自造字段。
- **T204**：OCR 每页一项（`page ≥ 1`、`requests == 1`），页级费用归属 `ocr` 中心；缓存页也要能
  说明「本轮是否真调用」，不能把缓存命中写成新的请求。
- **T205**：评分为 0 失败与「资金/服务错误停止」分开；`status=blocked/aborted` 的运行不得进入
  通过统计。
- **T208**：裁判每个嵌套调用都是一条 `judge` 项；裁判框架的最坏调用上界必须写进计划，
  超上界即拒绝（不能证明上界就不许真实裁判）。

## 10. T201 明确未做的事

不签发 GO、不写原 budget/GO/账本、不建 P2 阶段、不启动 runner、不跑真实发送、不读 .env/H2、
不提高 `MAX_GO_REQUESTS`（T201 当时的值；T207-FIX-B 于 2026-11-11 按经理落盘提至 1600，见 §1.3）、
不设 `MKTKB_PROJECT_TOTAL_LIMIT_CNY=40` 到任何全局配置。
候选文件在 `docs/reports/OBS-EVAL/P2/T201/candidates/`，全部标 DRAFT。

## 11. T206-LIVE 增补：live 执行入口与逐次尝试（additive，不改 §1–§10）

本节只**新增**，不改任何已冻结字段/阈值/路径语义。实现见
`backend/src/mktkb/evaluation/p2_live.py`（接线）、`product_adapter.py`（`mode="live"`）、
`p2_runner.py`（`--mode live` 的逐次核对）。

### 11.1 两段式 live 入口

| 段 | 入口 | 发送前硬门 |
|---|---|---|
| 计划/环境/门 | `open_live_gate(plan, run_id=...)` | `P2Gate.open`（固定路径 GO/预算/账本）+ `authorization.production_ready=True` |
| 执行 | `run_live_p2(plan, *, run_id, out_dir, dataset, ingest_plan, gate=...)` | 逐轮 `begin/confirm_before_send/settle_*`；每次底层尝试 `begin_attempt` |

CLI：`python -m mktkb.evaluation.cli p2-run --plan <p> --out <dir> --mode live --run-id <id> ...`；
**默认仍是 `--mode dry-run`**（现状行为零变化）。`--mode live` 缺 `--run-id`、缺 GO、
预算未修订（`limit/阶段` 算术不符）、缺 `MKTKB_PROJECT_TOTAL_LIMIT_CNY`、GO/预算不是固定路径、
账本快照不是 `fixed-paths`、或 GO 未授权 `answer/index_embedding/query_embedding/rerank/ocr`
之一，一律在建应用/首个发送前拒绝（`live_requires_production_ready` / `live_env_missing:<NAME>` / `live_go_*` / `go_*` /
`budget_*` / `env_total_limit_*`）。

**修订（T207-FIX-LIVEGATE，additive）**：上句的 `ocr` 一项改为**按计划判定** ——
`answer/index_embedding/query_embedding/rerank` 四项恒需（`p2_live.LIVE_CORE_OPERATIONS`），
`ocr` 仅在计划含 `operation=="ocr"` 项时才要求（`p2_live.required_live_operations`）。理由：
`authorization.operations` 取自**计划**（`p2_authorization.py:644` = `P2RunPlan.operations`），
`begin_attempt(item_id)` 又只接受计划里存在的 item —— 计划无 OCR 项时门根本无从发起 OCR 发送，
"计划无 OCR 却要求 ocr 授权"只会把合法计划挡在门外（T207 H2：145 项/158 请求/无 OCR 项，
曾被 `live_operation_not_authorized: [ocr]` 拒）。含 OCR 项的计划（公开矩阵 12 页）行为逐字不变；
GO 与计划操作集的一致性仍由 `authorize_p2` 保证（`go_operation_unauthorized` / `go_operation_invalid`，
`p2_authorization.py:472-480`），本轮检查不构成旁路。

### 11.2 每次底层尝试 = 一条预留（G5/G6）

`P2Gate.begin_attempt(item_id)` 是 `begin` 的**从属**版本：

- 允许在主请求（`answer` 轮）在飞期间登记：产品一次问答内部会先 query embedding、再 rerank、
  再 chat；灌库时还有 index embedding，OCR 在灌库/解析时发生；
- 不复用主 ticket：`reservation_id` 独立、成本中心来自该计划项、`reservation_count`
  照常 +1（累计请求口径不变，仍受 `max_requests` 约束）；
- 预留/复核/结算与主请求同锁同门：`confirm_before_send` 失败即 `P2_PRE_SEND_REFUSED:<code>`
  保守留账并停止，HTTP=0；
- 计划项级配额：同一计划项最多 `item.requests` 次尝试；用尽即**发送前**拒绝
  （`attempt_quota_exhausted`），不做"多发一次再解释"。
  **"一次尝试" = 一次真实 HTTP 请求/批**（T206-LIVE-R1/F2 对齐）：embedding 一次 `embed()`
  会按 `embedding_batch_size` 拆成多个 POST，每个 POST 各自预留并各扣 1 次配额
  （例：12 条、批 5 → 3 次；计划只给 2 时第 3 批在发送前停住）；rerank/OCR/`query_expansion`
  每次调用恒为 1 次。预留数与配额扣减数因此逐条一致（回执 `attempts.by_operation` 可核对）。
- `query_expansion` 是**独立**的从属尝试（T206-LIVE-R1/F1）：计划项 `expand-*`
  （`operation=query_expansion`、`cost_center=answer_retrieval`、kind=chat），
  预留/复核/usage 结算/回执全部按该项，**不得**记到 `answer-*`；计划缺该项时该轮在发送前
  失败（不借用 answer 的钱）。产品一次回合内若真的多次扩展，就按实际次数逐次预留。

runner 在 `gate.json.attempts` / `summary.json.attempts` 落盘逐次回执（`operation/item_id/
cost_center/kind/reservation_id/usage/charged_cny/phase`）并核对：计划项存在、
成本中心 == 计划项、`gate.result().requests_reserved == answer 轮 + 从属尝试`；
不一致 → `attempt_accounting_mismatch`（产物照写、状态 aborted）。

### 11.3 usage 证据（G4）与三种结算结果

`settle_evidence(ticket, product)` 由 live 接线注入，返回三种值：

| 返回 | 含义 | runner 行为 |
|---|---|---|
| `UsageEvidence` | 本轮确有一次真实 chat 发送，且响应带官方 usage（prompt/completion/total + cache hit/miss） | `settle_success(evidence=...)`，按 J1 重算释放未用预留 |
| `NO_PAID_ATTEMPT` | 本轮零付费发送（合法拒答/澄清/未找到/知识变更） | `close_unused`：写 `status=failed` + `P2_NO_PAID_ATTEMPT:<reason>`，保守占用该笔上界，**不停止**后续 |
| `None` | 声称作答却拿不到 usage | `settle_failure(error_code=usage_evidence_missing)` + `stop_code=usage_evidence_missing`（保守留账、不伪造金额） |

`close_unused` 只用于"预留后没有发生任何发送"：J1 不允许无证据释放预留，因此仍按上界保守占用；
它与 `settle_failure` 的区别是**不置 stopped**（一次合法拒答不是付费失败）。

### 11.4 OCR（G3）

live 下 OCR 走 `build_ocr_gateway(settings, transport=<真实传输>)` 构造的
`TencentOCRClient`（真实签名/真实端点解析），由 `GatedOcrGateway` 在每页调用前后
`begin_attempt('ocr-...')/confirm_before_send/settle_success(estimated_cny=固定页价)`；
每页一次调用，**重试 0**（`ocr_options.max_attempts=1`）。Mock 链仍注入 `_NoOcrGateway`
（行为不变）。

页价口径（T206-LIVE-R1/F5，与实现逐字对齐）：价格**只由计划项声明的模型**决定，并冻结在
`p2_contracts`（`GeneralAccurateOCR`=0.5 元/页 = text；`RecognizeTableAccurateOCR`
=0.15 元/页 = table；`P2RequestItem` 构造期已强制"该项模型 ↔ 该项页价"相等）。
运行时由产品判定 `mode`（`ingest/parsers` 的 `looks_like_rule_table`），它**必须**与计划项
模型一致；不一致或 mode 未注册，一律在**预留与发送之前**拒绝
（`ocr_mode_plan_mismatch` / `ocr_mode_invalid`），绝不按"另一个模型的价格"结算，
也不做隐式换模型。

### 11.5 网络分解（additive 键）

`providers.network` 新增可选 `ocr_outbound_attempts`；分解恒等式变为
`outbound_attempts == chat_outbound_attempts + rag_provider_posts + ocr_outbound_attempts`。
Mock 链不给该键（视为 0），旧断言不变。live 链四个真实传输各自被计量包装，
"0 出站"是测量结果而不是声明。

### 11.6 灌库驱动：`--ingest-plan` 与 `document_ref`（T207-FIX-A additive）

`p2-run` 新增 `--ingest-plan <json>`（与 `--ingest` **互斥**；旧 `--ingest` 路径逐字不变）。文件 schema
`p2-ingest-plan/v0.1`，字段白名单固定：

- `schema_version`（必须是 `p2-ingest-plan/v0.1`）、`label`、`sources[]`；
- 每个 source：`path`（必填）、`name`（上传文件名）、`document_ref`、`expected_active_version_id`、`publish`；
- `document_id` **不开放**：版本槽一律用 `document_ref` 在**本次 ingest 内**按上传名解析，避免手抄 UUID。

语义（产品代码 0 改动，走 `documents/service.py` 既有「新版本」路径）：

- `document_ref` 解析不到 → `RuntimeError`（fail closed，不猜、不退化成 `allow_same_name`）；
- 新版本的 `expected_active_version_id` 缺省取该资料**当前已发布**版本（"以我看到的那一版为基准"）；
- `publish=false` = 产品上传 + worker 处理成功但不发布：版本停在 `review_required`，`active_version_id`
  仍指上一版、`revision` 不增（这正是 U01 要的"未生效版"）；
- `IngestSource` 侧禁止 `document_ref` 与 `document_id` / `allow_same_name` 同用；
- 回执只记身份（`document_id`/`version_id`/`job_state`/`published`/`revision`/`units`），适配器额外维护
  `ingest_document_map`（逻辑资料名 → `document_id` + 当前已发布版本），供断言"同槽多版本"。

`--ingest-plan` 与 `--ingest` 同时给出时由 argparse 拒绝（退出码 2），不会构造适配器。

### 11.7 H2 计划生成器 `p2-h2-plan`（T207-FIX-A additive）

-- H2 的 case_id 只在封存密文里，而计划项按 (operation, case_id, turn) 逐项解析，因此 H2 计划
**必须**在受控进程内由「case_id + 轮数」元数据生成：

```text
p2-h2-plan --cases-metadata <工作区外 json> --holdout-manifest <repo-safe manifest> \
           --ingest-batches B --plan-out <工作区外 json> [--plan-id/--plan-version/--created-utc/--max-requests]
```

- 元数据 schema：`{schema_version:"p2-h2-cases-metadata/v0.1", dataset_version, cases:[{case_id, turns}]}`；
  出现 `question`/`answer` 等未知字段、重复 case_id、非法 id 一律拒绝；
- 与 manifest 交叉校验：题数、总轮数、`max_turns_per_case`、`turn_histogram`、`multi_turn` 分层计数；
- 每回合 4 项（query_embedding / rerank / query_expansion / answer 各 1）+ 1 个 `index_embedding`
  项 `requests=B`；**不生成 OCR 项**；中心 8.5/6.5/3/2，`max_requests` 默认 1100；
- 计划文件必须写在工作区外（`plan_out_inside_workspace`），stdout 只回 `plan_sha256` 与计数，
  不回 case_id；生成物必须能过 `P2RunPlan.from_dict`。

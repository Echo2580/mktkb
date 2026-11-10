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
   硬顶 `HARD_MAX_REQUESTS = 1000`。新增预算不重置、T201 不提高该值。
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
| `max_requests` | 正整数，≤ 1000；≥ 计划请求总数 |
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
不提高 `MAX_GO_REQUESTS`、不设 `MKTKB_PROJECT_TOTAL_LIMIT_CNY=40` 到任何全局配置。
候选文件在 `docs/reports/OBS-EVAL/P2/T201/candidates/`，全部标 DRAFT。

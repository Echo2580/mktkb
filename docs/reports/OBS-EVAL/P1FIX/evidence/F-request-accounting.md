# P1FIX-F 证据：GO 请求计数口径核查与“超限前拒绝”负例

> 依据：`docs/reports/OBS-EVAL/P1/review.md` §7 #56（GO 计划 7/4 与 T111 实际 17/10、T112 39/31
> 有口径差）。本项不重签 GO、不改预算/账本/总请求上限、不执行真实调用；结论为
> **已核实：不是 GO 违规、也不是“声明未执行”的运行期约束；计数口径说明不充分 → 文档更正 + 负例锁定**。

## 1. 五类计数口径（计划值 / 运行上限 / 实际请求 / 预留 / 结算）

| 口径 | 真实语义 | 证据（文件:行） |
| --- | --- | --- |
| 计划值 | GO `scope.bindings.rag.embedding_requests=7`、`rerank_requests=4` 等来自 **S2-DEV 的 J2 受控计划**（与 `plan_version=s2j2-controlled-plan-v1`、`request_plan_sha256=11b0218d…e52a`、`settlement_version=usage-conservative-v1` 同一块）；sha 反解唯一计划 `chat2+emb7+rr4+ocr1+1=15`、stage=S2-DEV | `docs/evidence/LOCAL-R1-20261101/PM/S2-LIVE-GO.json`；`controllers`：`backend/src/mktkb/controlled_execution.py:140-157,285-317,379-444`；历史 `PM/S2-LIVE-GO-20261104.json` 同 sha |
| 运行上限 | **`scope.max_requests=1000`（累计口径，跨 kind/stage/run）**；`max_request_cny=0.05`；阶段 3.0 元；总上限 20 元 | `live_authorization.py:539-547,614-625`；`rag/budget.py:555-569` |
| 实际请求 | 每次真实 HTTP=1 条 reserved 事件、零重试；T111 27（emb17/rr10/chat0）、T112 70（39/31/0）；P1 累计 124（S2-DEV 381+P1-RETRIEVAL 124=505） | `rag/providers.py:329-350`；`budget.py:431`；`runner.py:1179-1181` |
| 预留 | embedding 0.04096 元 / rerank 0.024 元 单请求上界写 reserved 事件；未结算按预留计 | `evaluation/live.py:295-305`；`budget.py:580-602,396-400` |
| 结算 | result 事件；legacy `max(预留,声明)`；versioned `usage-conservative-v1` 重放；`provider_billed_cny=null` | `budget.py:390-400,436-479`；`runner.py:1102,1179,1201-1203` |

## 2. “7/4 不约束 P1 live 检索路线”的依据

1. P1 live 检索路径 `evaluation/live.py::_assert_live_bindings` 只向 `assert_provider_binding`
   传 12 个 provider 键（base_url_host/embedding_provider/embedding_model/embedding_dimensions/
   embedding_host/embedding_region/rerank_provider/rerank_model/rerank_host/rerank_region/region/
   settlement_version），**不含** plan_version/request_plan_sha256/embedding_requests/rerank_requests/
   ocr_*/token caps（`evaluation/live.py:315-335`）。
2. `assert_provider_binding` 只核对显式传入键（`live_authorization.py:323-335`）；
   `_parse_scope_bindings` 只做形状/敏感校验（`:266-304`）。
3. 运行期上限链只来自 `scope.max_requests`：`evaluation/live.py:408-411` →
   `resolve_live_gate`（`live_authorization.py:614-625`）→ `BudgetLedger(max_requests)`（`live.py:452-461`）
   → 预留前 `facts["reservation_count"] >= max_requests` 拒绝（`rag/budget.py:555-558`）→
   请求期复核（`live_authorization.py:720,741-747`）+ 发送前二次复核（`budget.py:605-626`）。
4. 当前 GO `services=["rag"]`，而 J2 受控路线需要 chat+rag 双绑定（`controlled_execution.py:1019-1036`），
   故 7/4 既非 P1 运行上限，也无当前可执行路线。

## 3. 新增 mock 负例（`backend/tests/evaluation/test_live_request_accounting.py`，5 passed）

零真实调用/零网络：

1. `test_go_plan_counts_bind_the_s2_j2_plan_not_p1_request_caps`：sha 复算 + 阶段/上限/数值一致；
2. `test_plan_counts_do_not_become_runtime_caps_for_p1_live_route`：隔离 GO 写计划值 1/1，
   运行上限仍 1000，27 请求预检 accepted（计划值不当上限）；
3. `test_assert_live_bindings_checks_provider_keys_but_not_plan_counts`：期望键集合 == 12 个
   provider 键、与 20 个计划字段无交集；缺 `embedding_host` 时正向拒绝；
4. `test_cumulative_request_cap_refuses_before_provider_http`：rerank 预留占满 `max_requests=1`
   后，embedding 调用抛 `RequestLimitExceeded`；**HTTP 尝试 0、账本 SHA/摘要不变**（跨 kind 累计）；
5. `test_precheck_request_limit_insufficient_refuses_before_index_build`：累计已用=上限 →
   预检 `request_limit_insufficient` 且拒绝；out 目录/index 未创建、fake embedder/reranker 调用 0。

## 4. 文档更正

新增 `docs/evaluation/live-request-accounting-2026-11-10.md`：五类口径表、GO 字段「是否约束
P1 live」逐项表、四条依据、拒绝链（构造期→预检→预留前→发送前复核→对账）、只读审计命令
（账本 505：embedding 259 / rerank 164 / chat 78 / ocr 4；S2-DEV 381 / P1-RETRIEVAL 124）；
明确 #56 现象成立但语义不同类。**未修改 GO/预算/账本/历史报告**。

## 5. 剩余问题（如实）

- GO bindings 沿用 J2 计划块（含 chat/OCR/plan sha）；P1 路线不核对其计划值。若未来重签 GO 或
  升级 `settlement_version`，需重新对齐（本次不动 GO，不重签，不执行真实调用）。
- P1 的 token caps 由 `settlement_version` 冻结值决定（`rag/settlement_policy.py:42,57-58`，当前与
  GO 4096/6000 一致）。
- 预检是**上限估计**（T112 估 71 / 实 70：1 个 query 无候选），实际以账本 reserved/run summary 为准。

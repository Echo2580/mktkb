# P2-T201 报告：请求计划、资金与授权门（开发自测）

- provider=wb、model=cn:deepseek-v4.1-flash、reasoning_effort=max（派发方指定）
- 结论：T201 **开发自测完成**；未自验为独立通过，未派发验收，未开工 T202，零真实调用。
- 分支 `codex/p2-e2e`（自 `59107fc1c2de58ed83cee62bee39f3fde28995f1` 新建并切换）；**未 commit/push**（本次派发明确禁止，优先于任务书 §12 的“每包本地 commit”许可）。账本/预算/GO 原件未写，固定 P2 GO 路径未创建，无新分支/worktree/stash/reset。

## 1. 改动清单（起止锚点）

起始 HEAD = `59107fc1c2de58ed83cee62bee39f3fde28995f1`，结束 HEAD 相同（无提交）。

| 文件 | 类型 | SHA-256 前 16 位 |
|---|---|---|
| backend/src/mktkb/evaluation/p2_contracts.py | 新增 | cc3e33f8799e5298 |
| backend/src/mktkb/evaluation/p2_authorization.py | 新增 | b0a566b604d136b0 |
| backend/tests/evaluation/test_p2_authorization.py | 新增 | 完整值见 verify.json |
| docs/evaluation/p2-run-contract-v0_1.md | 新增 | e693a7ac95dcda35 |
| backend/src/mktkb/rag/budget.py | 兼容接线 | 完整值见 verify.json |
| backend/src/mktkb/live_authorization.py | 兼容接线 | 完整值见 verify.json |
| docs/reports/OBS-EVAL/P2/T201/{report.md,evidence/,candidates/} | 新增 | 完整值见 verify.json |

## 2. 接口与兼容选择

- `p2_contracts.py` 冻结 4 个 DTO：`P2RunPlan / P2PreflightResult / P2Authorization / P2RunResult`，另有 `P2RequestItem / P2PriceProfile / P2LedgerSnapshot`；5 个 `schema_version`；错误只带稳定码，不回显外部原文。
- `p2_authorization.py` 冻结 `preflight_p2(plan, snapshot)`、`authorize_p2(plan, *, go_payload, budget_payload, ledger_snapshot, now)`、`read_ledger_snapshot()` 与 `P2Gate`（`open/begin/confirm_before_send/settle_success/settle_failure/result`）。生产只读固定路径，测试注入内存候选；`production_ready` 需「GO/预算来自固定路径 + 环境总上限已核 + 快照真来自固定账本」三条件。
- `rag/budget.py`（调用者：P1 live、S2 受控执行、OCR 预算包装、既有单测）：`reserve()` 加**可选** `cost_center` 落盘为 reserved 事件字段，`_accounting` 增 `center_accounted`，`BudgetSummary` 增 `center_accounted_cny`。旧调用不传参数、行为不变（对应旧负例全部重跑通过）。
- `live_authorization.py`（调用者：P1 live 入口、S2 `resolve_live_gate`/`refresh_request_limits`）：新增 `P1_FORBIDDEN_STAGES=("P2-LIVE",)` 与 `_assert_p1_stage`（只拒绝阶段名前缀 P2）和公开 `historical_prefix_sha256`。**不放松**任何旧检查；旧 rag/chat GO 无法给 P2 授权，OCR/judge 不能偷渡。
- 价格只引用不扩写：caps/费率下限/OCR 固定价取自 J1/S2-J2；单次上界 chat 0.018688、embedding 0.002048、rerank 0.0048、OCR 0.5/0.15。写小/漏填/0 价在构造期拒绝，故“猜低上界”换不来准入。

## 3. 标准逐项证据（任务书 §8 T201 五条）

1. **严格 plan schema**：`test_plan_rejects_invalid_schema`（21 组：bool 当 int、NaN/Inf、负数、0 价、cap 写小、错 stage、未注册操作、中心不一致/合计不等、硬顶 2001、请求超 cap、重复 id、估价超上界）+ `test_plan_rejects_missing_price_and_missing_cap` + `test_plan_rejects_unknown_and_duplicate_fields`；全部构造期拒绝，未触账本。
2. **反例 → HTTP=0、reserve=0**：`test_authorize_rejects_*`（12 个：旧 P1 GO、真实 S2 GO 文件、错 stage、过期、未生效、未授权操作、未授权中心、中心低于计划、阶段额度收缩、请求/单笔上限、同 nonce 换计划、改账本历史、缺身份、预算不符、环境上限）+ `test_loaders_reject_non_fixed_paths`（换账本/预算/GO 路径）+ 门控侧同类拒绝；每例断言假发送 `len(transport)==0` 且 reserved 行数不变。
3. **预留后发送前失效**：`test_gate_expired_before_send_is_conservative`（status=failed、`error_code=P2_PRE_SEND_REFUSED:authorization_expired`、保守占用=预留额、保留 reservation_id/request_id/cost_center、账本占用不归零）+ `…plan_edit…` / `…operation_withdrawn…` / `…ledger_prefix_change…`。
4. **串行下 40/20/12+3+3+2 同时生效、不重置 505**：`test_preflight_*`（阶段缺失/收缩、总额不符、阶段已占、中心已占、无归属占用、505 历史请求）+ `test_gate_runtime_request_cap_counts_across_kinds`（跨 kind 累计到 1000 后下一笔被拒）+ `test_gate_refuses_when_center_room_gone` + `test_gate_refuses_second_inflight_request`；旧剩余 4.9290555 未计入 P2（预检只看 P2 阶段已占）。
5. **候选 + 起止 hash + 预算表 + 合法模拟路径**：`test_candidate_artifacts_are_coherent_and_not_an_authorization`（4 个候选文件一起过预检/授权且 production_ready=False）、`test_candidate_budget_keeps_owner_arithmetic`、`test_candidate_snapshot_binds_the_real_shared_ledger`、`test_gate_legal_mock_request_full_path`（校验→预留→假发送→假结算：结算 0.004 < 预留 0.018688，占用按重算额下降）、`test_gate_ocr_item_settles_at_fixed_price`。

## 4. 真实请求 = 0 与原文件起止 hash

- 共享账本 `docs/evidence/LOCAL-R1-20261101/budget/live-ledger.jsonl`：起止同为 `1f46d1b9e846528d5a1635db5175a997eab9da075d61a90a8cbf803f3fde7390`（一致）；仍 505 预留/505 结果、已占 15.070944499999985；历史前缀 `f4710b1869fe43b9a609b58f772549f76370fbadd54f93685b76211d4b47a014`（未变）。
- 原 `budget.json` 起止同为 `084ba9acb4ee90379fd51fab8878f6dd4bab1bd481bff2a14c83057ffbc1cc58`（一致），limit 20、无 P2 阶段；原 `S2-LIVE-GO.json` 未改；固定 `PM/P2-LIVE-GO.json` 不存在（未创建）。
- 真实 HTTP/供应商/OCR/chat 调用 = 0；未发生新的 reserve（hash 与行数双证）。只读 `read_ledger_snapshot` 只在账本旁建/删瞬时 .lock（gitignore 内），前后 hash 一致，目录无残留。

## 5. 测试命令与结果（实际执行）

- 指定命令：`.\.venv\Scripts\python.exe -B -m pytest backend/tests/evaluation/test_p2_authorization.py -q -p no:cacheprovider --basetemp backend/.pytest-tmp/p2-t201` → **69 passed, 1 warning in 1.12s**。
- 受影响旧用例（逐个实际执行，非收集）：test_budget.py 5、test_budget_settlement.py 65、test_budget_settlement_rejection_echo.py 27、test_r4_regressions.py 6、test_live_request_accounting.py 5、unit/test_s2b_live_gate.py 22、unit/test_s2c_numeric_and_refresh.py 8、unit/test_s2d_post_send_guard.py 7、unit/test_j2_ocr_budget.py 11、rag/test_j2_controlled_usage.py 18、integration/test_s2c_paygate_http.py 1、integration/test_s2d_post_guard_http.py 1 —— 全通过。
- **未执行**：`backend/tests` 全仓、浏览器、真实 provider/OCR 真实页；理由：未获授权且任务书禁止默认重跑。

## 6. DRAFT 候选（`docs/reports/OBS-EVAL/P2/T201/candidates/`）

- 文件：plan、P2 GO、budget、ledger-snapshot（均 `*.CANDIDATE-DRAFT.json`）+ README；GO 的 `issued_by/authorization` 含 DRAFT 字样，`usable_authorization=false`、`production_ready=false`。
- 资金：总额 20→40、净新增 `P2-LIVE=20`；`0+0+15.4+3.0+1.57+20=39.97`，+历史 0.03 = 40.00；历史 15.0709445 与旧阶段原样保留。请求：计划 30 次（6 case / 6 turn / 2 OCR 页），硬顶仍 1000、已用 505。
- 中心 12/3/3/2：需要 0.181440 / 0.650000 / 0.037376 / 0.018688；成功估价 0.0369 / 0.65 / 0.008 / 0.004；最坏上界合计 0.887504、串行峰值预留 0.5（OCR 页）、成功估价合计 0.6989；`plan_sha256=f166cea9…89f6c0`。
- 有证据的中心调整建议（**未应用**）：OCR 12 页 × 0.5 = 6.00 元 > ocr 中心 3 元；建议 `answer_retrieval 9 / ocr 6 / judge 3 / independent 2`（总额仍 20、不挪用历史余额），由经理在正式 GO 决定。

## 7. 失败/限制/待确认

- 只做开发自测：**不构成独立通过**；我方未派发验收、未宣称 P2 可用、未开工 T202。
- 软链拒绝已在代码路径实现，但未在 Windows 实测（需额外权限）；文件替换路径已实测拒绝。
- `P2Gate` 用私有属性把两个门控回调注入 `BudgetLedger`（构造期反向依赖）；等价于构造器回调参数，属实现细节，验收可要求前者改公开 setter。
- `P2RunResult.requests_sent` 在结算时计数（成功或失败结算），发送前拒绝不计；T203 若需“已发出未结算”计数须显式扩展字段（本包不预留未定义字段）。
- 待确认：中心额度是否按 §6 建议调整；T206 是否把 `HARD_MAX_REQUESTS` 提到 ≤2000（本包未动）；真实 GO 的累计上限是否比计划更紧（本包取 min）。

## 8. 证据入口（4 个）

1. `evidence/verify.json`——起止 hash、文件 hash、候选摘要、测试结果、真实请求=0。
2. `evidence/candidate-numbers.json`——候选计划/快照派生数字与 plan_sha256。
3. `evidence/pytest-p2-t201.log`——指定命令原始输出。
4. `candidates/README.md`——DRAFT 声明、资金算术、中心调整建议与依据。

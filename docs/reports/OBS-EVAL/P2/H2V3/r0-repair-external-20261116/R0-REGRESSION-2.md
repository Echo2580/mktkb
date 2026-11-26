# R0 第二轮真实运行回归：定位结论（零真实调用）

## 0. 结论（先给）

**产品代码没有参与这一轮。** 第二轮在 `P2Gate.begin()` 的**预留前门控**被拒，一个产品回合都没执行，
所以 `candidate_unit_ids_for_intent` / c12 / entity-key 全部不在因果链上。

- 停止点：`p2_runner.py:1379-1415`（`gate_begin` 分支），`stop_code=gate_error`、
  `error_code="P2GateError"`。
- 机制：`p2_authorization.py:1003-1020` 的 unlimited 逐项配额按 **`plan_sha256 + item_id` 累计、不看
  run_id**；第二轮的 `plan_sha256` 与第一轮**逐字节相同**，第一轮已为这 14 项各写过一条 `reserved`，
  于是第一项的 `begin()` 直接抛 `P2GateError("attempt_quota_exhausted")`（:1101-1103 重新包装）。
- 观测值逐项吻合：`turns_executed=1`（gate_error 行）、`reserved=0`（:1417 从未到达）、
  `real_sends=0`、结算 0、其余 11 题 `not_executed`；`P2GateError` 不在 `p2_diagnostics.ERRORS`
  里 → 聚合记 `errors={"unknown":1}`、`model_failure_reasons={"unknown":1}`。
- 收官异常是**纯次生**：`ask_turn` 没被调用 → `product_adapter.py:2257` 的 `bind()` 从未执行 →
  `close()` 里 `p2_evidence_capture.py:1985-1989` 抛 `EvidenceCaptureIncomplete(evidence_binding_pending)`。

## 1. 根因证据（可复核，全部在仓库内）

| 证据 | 值 | 来源 |
|---|---|---|
| 第一轮计划 `plan_sha256` / `plan_file_sha256` | `92db7035…acb354` / `fe78a9ea…e6e937` | `PROGRESS.md:87` |
| 第二轮 check-only 的同两值 | **完全相同** | `evidence/05-plan-final/CHECK-ONLY-r0-round2.json` |
| 第二轮 check-only 账本 sha / 1459 reserved+1459 result | `940f77ca…`（= 第一轮执行后） | 同上 + `PROGRESS.md:92` |
| 第一轮 `reserved=14`（14 回合） | 每项一条 `reserved` | `PROGRESS.md:90` |
| 逐项配额口径 | `plan_sha256+item_id`，注释明写"换 run_id/重启不清零" | `p2_authorization.py:1013-1020` |
| 复用计划 = 首项即拒 | `attempt_quota_exhausted`，账本零新增 | `test_unlimited_item_quota_accumulates_across_gate_instances`（既有，绿） |

反证 c12：同一轮里 record 题走完整 HTTP 链（`document_terms` 非空）**正常作答**——
`test_v3_safety_fix_e2e.py::test_item_location_still_answers` 与 `tests/rag/test_r0_c12_text_face_recall_synthetic.py`
全绿；`reserved=0` 本身就排除了"产品回合已执行"（否则 `:1417` 必然自增）。

## 2. 改动清单

- **产品代码：零改动。** 允许清单内不存在本次缺陷；不为了"有改动"去动 c12/entity-key。
- 新增 1 条测试：`backend/tests/evaluation/test_p2_authorization.py::test_second_round_must_not_reuse_the_same_plan_identity`
  （把"复用计划必失败 / 重新出计划可通过"钉成可执行事实，并断言拒绝发生在预留与结算之前、
  runner 看到的是 `P2GateError` 类名）。
- 本文件。

## 3. 为什么没在预检/上一轮暴露

1. `check-only` 的 16 项只校验计划/GO/binding/预算/`zero_send`，**没有"本计划项剩余配额"这一项**；
   逐项配额第一次被求值就是在真实轮的 `begin()`（发送之前）。
2. 计划身份 `plan_sha256` 只由计划内容（含 `created_utc`）决定，**不含 code_version/binding**；
   "重绑一轮"若复用同一份计划文件，摘要不变，R0-5 的防重放语义把它当重放——设计如此。
3. runner 落盘只留 `type(exc).__name__`，丢掉 `exc.reason`，所以现场只能看到 `unknown`。

## 4. 最小修复（本轮未执行，需授权）

**重新生成计划**（`plan-private`，`created_utc` 变 → 新 `plan_sha256`）→ 按新 `plan_sha256` 重签 GO →
完整 `check-only` → 再执行一次。**不要**复用 `plan_sha256=92db7035…` 的计划：它已被永久消耗。

两条建议（均需主人/授权方点头，超出本次可改范围）：
- 给 `check-only` 增加 `plan_items_unused`（按 `plan_sha256+item_id` 读账本剩余量），让这种失败停在预检；
- runner 的 `gate_begin` 分支把 `getattr(exc,"reason",…)` 一并落盘，避免下次又只剩 `unknown`。

## 5. 自证与回归

- 复核现场 30 秒即可判定：本轮 run receipt 的 `failure` 若为 `stage="gate_begin"` /
  `stop_code="gate_error"` / `error_code="P2GateError"`，结论成立；若是 `product_call`/`product_answer`，
  本报告结论作废，回到产品线排查。
- 回归（`MKTKB_PROJECT_TOTAL_LIMIT_CNY=20.0`）：`tests/rag` + `unit/test_retrieval` +
  `unit/test_conversations` + `integration/test_visible_index` + `integration/test_v3_safety_fix_e2e` +
  两个 t207 synthetic = **546 passed / 1 failed**；`evaluation/test_p2_h2_v3_controlled_entry` +
  `evaluation/test_p2_authorization` = **91 passed**。唯一失败是同一条已知既有失效
  `test_s4_stage_limit.py::test_current_go_and_budget_are_consistent_and_above_three_yuan`
  （`limit_cny=20` vs 40），与本轮无关。

## 6. 风险

- 若账本里这 14 项的 `reserved` 事件缺 `plan_sha256` 元数据，拒绝理由会变成 `run_plan_unknown`
  （同样停在 `gate_begin`、同样 `unknown`），修复动作不变。
- 重新出计划会写新文件、新 GO；须走原担保/代签流程，且**不能**顺手改题集、阈值、账本或预算。
- 本轮零花费、零出站（`zero_send` 通过），重跑不消耗额外预算额度。

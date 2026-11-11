# P2-T207-FIX-LIVEGATE 开发报告：live 门的 OCR 要求随计划

分支 `codex/p2-e2e` @ `df661cb`；未 commit。零真实调用；账本/预算/GO 只读未改。

## 1. 改动清单
| 文件 | 改动 |
|---|---|
| `backend/src/mktkb/evaluation/p2_live.py` | 新增 `LIVE_CORE_OPERATIONS`（answer/index_embedding/query_embedding/rerank）与 `required_live_operations(plan)`；`open_live_gate` 的 `live_operation_not_authorized` 改为 `required_live_operations(plan) - authorization.operations`，即 `ocr` 仅在计划含 OCR 项时才要求 |
| `backend/tests/evaluation/test_p2_live_wiring.py` | 只增 7 个测试（§3） |
| `docs/evaluation/p2-run-contract-v0_1.md` §11.1 | additive 修订说明（原句保留） |
| `docs/evaluation/p2-live-binding-v0_1.md` | 新增 §10.8「门的操作要求随计划」 |
| `docs/reports/OBS-EVAL/P2/T207/PM/T207-runbook.md` §8 | 执行与两步打分的 `--holdout-manifest` 改为封存 root 内 `D:/mktkb-p2-holdout/v2/manifest.json`（repo 副本只用于计划生成交叉校验）；新增 manifest 路径规则与门规则 |

## 2. 不变式（为什么不是放宽）
- `authorization.operations` 本就取自**计划**（`p2_authorization.py:644`），门真正多出来的只有 `ocr`；
- `begin_attempt(item_id)` 只接受计划里存在的 item → 计划无 OCR 项时门无从发起 OCR 发送；
- GO ⊇ 计划操作仍由 `authorize_p2` 强制（`go_operation_unauthorized` / `go_operation_invalid`，`p2_authorization.py:472-480`）；
- 默认公开矩阵计划（含 12 页 OCR）行为逐字不变：仍要求 `ocr`；
- 门后流程（预留/结算/账本/预算）零改动。

## 3. 测试（+7，全绿）
1. `test_live_gate_still_requires_ocr_for_plan_with_ocr_items`：含 OCR 项的计划仍把 ocr 算进必需集；GO 少 ocr → `go_operation_unauthorized`；
2. `test_live_gate_opens_for_plan_without_ocr_items`：H2 型计划（无 OCR 项、GO 为含 ocr 的超集）可开门且 `authorization.operations` 无 ocr；**反证**：临时还原旧逻辑 → `live_operation_not_authorized: GO 未授权 [ocr]` 失败（evidence/pre-fix-failure.txt）；
3. `test_live_gate_refuses_plan_missing_a_core_operation`（4 参数）：缺 answer/index_embedding/query_embedding/rerank 任一 → `live_operation_not_authorized`；
4. `test_live_gate_change_is_not_a_bypass_for_go_plan_consistency`：GO 少计划操作 → `go_operation_unauthorized`；GO 含未注册操作 → `go_operation_invalid`。

验证：`pytest backend/tests/evaluation/test_p2_live_wiring.py backend/tests/evaluation/test_p2_runner.py -q -p no:cacheprovider --basetemp backend/.pytest-tmp/p2-t207-fix-livegate` → **63 passed**（evidence/pytest-livegate.txt）。

## 4. 零真实调用与固定路径
`evidence/fixed-path-sha.txt`：账本 `05b54d06…`、预算 `79b21700…`、GO `3ed427f4…`（H2 GO）本包**前后一致**，未写。测试全走 `httpx.MockTransport` + `t09_network_guard`（出站 0）。

## 5. 限制 / 未做
- 只修门：H2 真实执行还受 runner 逐轮核对与 ingest 配额约束，本包不预判其它阻断；
- 未用 H2 真实计划跑 live（计划/密文在工作区外），也未验证 full live 链；
- 文档断言「两份 manifest 逐字节相同（`8874985e…`）」是**当前事实**；日后轮换需重述；
- 观察（非本包改动）：工作区同时存在他人对 `backend/src/mktkb/evaluation/scorers.py` 的修改（+48 行），本包未触碰。

# P2-T206-LIVE 交付（report）

- 角色：T206-LIVE 开发助手（全新上下文）。**真实调用 0**；未读 `.env`/H1/H2；未联网；未写共享账本/GO；
  未 commit/push。
- 现场：`codex/p2-e2e` @ `9a8272a`。共享账本 958,277 B / `1f46d1b9…`、预算 1,444 B / `084ba9ac…`
  与 T206 基线**逐字节相同**；固定路径 `P2-LIVE-GO.json` 仍不存在。
- **一句话结论**：T206 准备发现的 G1–G6 **代码入口已补齐并有定向测试**（live 适配器 / 真实门与
  `--mode live` / 真实 OCR 传输 / 真实 usage 证据 / 成本中心 / 逐次请求计数）。pilot 仍**不可执行**：
  缺经理签发的正式 GO 与预算修订；且 live 目前不重放检索候选（见 §6），要让 gate 通过需新计划+新 GO。

## 1 改动清单（只改允许文件）

| 文件 | 改动 |
|---|---|
| `backend/src/mktkb/evaluation/p2_live.py`（新增） | live 装配：进程环境校验、计划项解析与尝试配额、`GateAttemptLedger`（provider budget 协议 → `begin_attempt/confirm_before_send/settle_*`）、真实 provider/OCR 门控包装、`open_live_gate`/`run_live_p2`、`make_settle_evidence` |
| `.../product_adapter.py` | `mode="mock"\|"live"`（默认 mock）；live 起真实 chat/embedding/rerank + 真实 OCR 传输（`build_ocr_gateway`）；`_MeteredSyncTransport` 逐传输计量；`provider_calls()` 新增 `live/attempts`；`turn_usage()/attempt_receipts()`；live 不重放候选；灌库把真实 OCR 网关交给 worker（`max_attempts=1`） |
| `.../p2_authorization.py` | `P2Gate.begin_attempt`（从属尝试，允许主请求在飞）、`_release_slot`、`close_unused`（零发送保守留账且不停止）；结算/拒绝同时支持主/从 ticket |
| `.../p2_runner.py` | `settle_evidence` 三种返回（证据 / `NO_PAID_ATTEMPT` / `None`）；`usage_evidence_missing`、`attempt_accounting_mismatch`；逐次回执核对；`summary/gate.json.attempts`；网络分解新增可选 `ocr_outbound_attempts` |
| `.../cli.py` | `p2-run --mode dry-run（默认）\|live` + `--run-id`；live 走 `run_live_p2`（预检前不造适配器）；稳定错误码 JSON |
| `backend/tests/evaluation/test_p2_live_wiring.py`（新增） | 9 个定向用例（见 §4） |
| `docs/evaluation/p2-run-contract-v0_1.md` §11 | live 入口/逐次尝试/usage 三态/OCR/网络分解 |
| `docs/evaluation/p2-live-binding-v0_1.md` §10 | 显式模式、live 供应商身份、环境变量名、逐次绑定、失败矩阵、live 不做的事 |
| `docs/reports/OBS-EVAL/P2/T206/PM/runbook.md` | §4 改为"入口已就绪、仍缺正式 GO"并给真实命令；§5 新增停止码 |
| `docs/reports/OBS-EVAL/P2/T206/report.md` | 追加 §9（指向本包） |

不动的：冻结 fixtures、`gate.py`、`p2_ingestion.py`、业务 API/schema、`.env`、H1/H2、`.claude/**`。

## 2 G1–G6 修复与证明

| 缺口 | 修复 | 证明（可复跑） |
|---|---|---|
| G1 适配器恒 Mock | `mode="live"` 显式构造真实 chat（`DeepSeekClient`）/embedding/rerank（Bailian，`require_budget=True`）/真实 OCR；默认 mock 不变 | `test_live_run_*zero_outbound`：`providers.live`、`chat/embedding/rerank` 真实实现；`T203 105` 不回退 |
| G2 无 live 驱动/CLI | `open_live_gate` 固定路径 GO/预算/账本 + `production_ready`；`run_live_p2` 逐轮门序；`--mode live` | `02-cli-refusals.txt`：缺 env/GO/OCR 关闭/非白名单模型全部 exit 3 且**未建应用** |
| G3 OCR 写死 Mock 传输 | live 用 `build_ocr_gateway(settings, transport=真实传输)` → `TencentOCRClient`；`GatedOcrGateway` 每页预留/结算 | `test_gated_ocr_gateway_uses_real_client_and_reserves_fixed_price`（真实客户端 + 真实签名 + 固定价 0.5） |
| G4 无真实 UsageEvidence | chat 用响应 usage（含 cache 拆分）；embedding/rerank 用 `build_total_evidence`；缺 usage → `usage_evidence_missing` | `03-live-fake-run.txt`：answer 按 64/32 tokens 结算 0.000384；`test_live_missing_usage_*`：不伪造、保守留账后停 |
| G5 成本中心无归属 | 每次尝试 `begin_attempt` 用计划项 `cost_center`；`center_accounting_inconsistent` 仍由账本判 | 证据 03：`reserved_without_center=0`、`receipt_centers_ok=true`、中心合计=0.000124（尝试）+0.000384（answer） |
| G6 非 answer 漏计 | 每次底层尝试独立 reservation；runner 核对 `gate.result().requests_reserved == answer 轮 + 尝试` | 证据 03：`reserved=5 / results=5 / gate_reserved=5 / expected_reservations=5`；不一致 → `attempt_accounting_mismatch` |

## 3 发送前拒绝（fail closed，HTTP=0）

环境：`live_env_missing:<NAME>`、`live_ocr_disabled`、`live_chat_model_not_authorized`、
`live_env_invalid`。门：`path_missing`（GO）、`go_expired/go_not_yet_valid`、`budget_*`、
`stage_allocation_*`、`env_total_limit_missing/mismatch`、`live_requires_production_ready`、
`live_operation_not_authorized`。运行期：`attempt_quota_exhausted`（计划低估，**发送前**）、
`pre_send_refused`、`usage_evidence_missing`、`attempt_accounting_mismatch`。

usage 三态：拿到 → `settle_success`；零付费拒答 → `close_unused`（保守占用、不停止）；
声称作答但无 usage → `usage_evidence_missing`（保守占用 + 停止，不伪造金额）。

## 4 测试（本机亲跑，零真实调用）

| 套件 | 结果 |
|---|---|
| 新增 `test_p2_live_wiring.py` | **9 passed**（env/配额/CLI 拒绝/端到端/缺 usage/OCR/close_unused） |
| T203 `test_p2_runner` + `test_p2_authorization` + `integration/test_p2_product_e2e` | **105 passed** |
| T204 `test_p2_ocr_ingestion` + `integration/test_p2_ocr_source_identity` | **18 passed** |
| T205 `test_p2_scoring` + `test_p2_gate` + `integration/test_p2_public_controls` | **56 passed** |
| gate `test_gate` + `test_gate_quality` | **109 passed** |

零出站：新增用例全部挂 `t09_network_guard`（外部 socket 尝试 0）；证据 03 的独立脚本再用
socket 闸门跑同一 live 链路 → `socket_attempts.external=0`、`network.outbound_attempts=0`、
`mock_intercepted=5`。

## 5 复跑

```powershell
.\venv\Scripts\python.exe -X utf8 -B -m pytest backend/tests/evaluation/test_p2_live_wiring.py -q
# live 入口（缺 GO/预算修订时只会打印拒绝 JSON，exit 3）：
.\venv\Scripts\python.exe -B -X utf8 -m mktkb.evaluation.cli p2-run --mode live --run-id <id> \
  --plan docs\reports\OBS-EVAL\P2\T206\PM\p2-pilot-plan-v0_1.json --out <仓库外目录> --ingest <文件...>
```

## 6 限制与残余（必须如实读）

1. **pilot 仍不可执行**：正式 GO 未签发、预算未修订（现状预检仍 `budget_total_mismatch` 等）。
2. **live 不重放检索候选**（**R1 已改**：改为从产品 answer 请求的 `evidence` 捕获，
   见 §R1/F6；捕获不到仍为空 → `citation_required` fail-closed。付费重放仍需新计划 + 新 GO）。
3. **计划项配额 = `item.requests`**（**R1 已改**：按真实 HTTP 请求/批计，见 §R1/F2；
   超出上界仍在发送前 `attempt_quota_exhausted` 停住，不偷偷多发）。
4. **OCR 只证 1 页**（通用文本 0.5 元；重试 0）。不外推到 12 页/可重试。
5. **未跑真实模型/OCR/embedding/rerank、H2、Ragas、Langfuse、全仓**；`provider_billed_cny` 仍为 null，
   所有金额是保守占用口径，不是账单。
6. `gate_v0_3` 仍 unapproved：本包不产生放行结论。
7. `QaEngine` 未接 `index.budget`：任何"由 rag 内核自己构造 provider"的路径会 fail closed 成
   `CHAT_UNAVAILABLE`（**不发送**，不会无账付费）。当前路由 `_rag_owns_turn` 只放 record 轮
   （字段抽取，无 LLM），pilot 5 题不受影响；若路由变化，需要新计划项 + 把账本接进 QaEngine。

## 7 证据索引

`evidence/01-pytest.txt`（5 个套件）、`02-cli-refusals.txt`（6 次真实 CLI 拒绝）、
`03-live-fake-run.txt`（live 端到端产物与账本计数）、`04-scope.txt`（改动范围/未提交/资金面未动/零出站）。

## R1（T206-LIVE-R1 加固：F1–F6 返工，零真实调用）

- 角色：加固开发助手（全新上下文）；`codex/p2-e2e` @ `9a8272a`，**未提交**；真实调用 0（全链 httpx.MockTransport +
  `t09_network_guard` 外层闸门，外部 socket 尝试 0）；共享账本/预算/GO 未触碰（tmp 副本）。
- 逐项：**F1** live 的 `query_expansion` 从 `answer-*` 改挂计划项 `expand-*`（`begin_attempt → confirm → 真实 POST →
  `settle_success(usage)`，预留/成本中心/回执/配额全按该项；同一轮仍只允许 1 次 answer chat，第二次发送前拒）；
  **F2** 计划项配额移到 `GateAttemptLedger` 的**每次真实 POST**（embed 12 条/batch 5 → 3 次 POST = 3 次配额与 3 条
  reservation；计划只给 2 时第 3 批**发送前**被 `attempt_quota_exhausted` 拒，HTTP 仍 2）；**F3** CLI 用例改成先写合法计划、
  置齐环境变量，断言 stdout `error_code=path_missing` + 未建应用（另加"计划文件缺失 → `plan_unreadable`"反例）；
  **F4** runbook 的 `go_missing` 改为实际码 `path_missing` 并列出真实稳定码；**F5** OCR 页价改为"只由计划项模型决定"，
  并加运行时 `mode ↔ 计划项模型` 一致性门（不一致 `ocr_mode_plan_mismatch`，预留/发送前拒）；**F6** live 的 `retrieved`
  改从产品 answer 请求的 `CompletionInput.evidence` 捕获（模型实际拿到的证据，零额外调用/付费），`citation_required`
  真实 PASS；捕获不到仍 fail-closed。
- 验证（本机亲跑，证据 05）：live 12 / T203 105 / T204 18 / T205 56 / gate 109 全绿；定向探针（证据 06/07）打印
  `expand-Q25-t1` reserve+settle（0.000384 按 usage）、12 条 → 3 POST/3 配额、tight(requests=2) → 2 POST + 发送前拒、
  `retrieved==evidence_ids`、带候选 `citation_required=pass` / 删候选 `fail`。
- 改动：`p2_live.py`（purpose 分流、expand 计划项、批级配额、OCR 模式门、evidence 捕获、计数口径）、
  `product_adapter.py`（live 的 retrieved 来源 + live 禁重放闸门 + mock chat 记录 `evidence_ids`）、`cli.py`（计划读取稳定码）、
  三个契约（run-contract §11.2/§11.4、live-binding §2b/§10.3/§10.5、ocr-contract §3）、runbook §4/§4.4/§5、本报告 §6.2/6.3 与本节。
  未动冻结 fixtures/gate.py/p2_ingestion.py/业务 API/.env/H1/H2。
- 残留（如实）：①rag 内核直答轮 / 零付费轮没有可免费捕获的候选 → `retrieved=()` 仍 fail-closed；付费 replay 需新计划+新 GO。
  ②live 的 `retrieved` 等于"模型拿到的证据集合"，产品若改变 provider 入参构造方式，需同步复核该口径。
  ③OCR 模式门要求计划项**逐页**声明正确模型（pilot 计划的 1 页是 text/0.5；若产品把该页判成 table，会在发送前拒）。
  ③'计划项配额改按批后，pilot 的 `ingest-index-embedding.requests=30` 变成"30 批"（≤150 条文本）上界：
  5 份资料灌库若超过 30 批会在发送前停 —— 需经理在签发 GO 前复核（见 runbook §4.4）。
  ④`provider_billed_cny` 仍为 null（金额是保守占用口径，不是账单）；未跑真实模型/OCR/H2/Ragas/全仓。
  ⑤gate_v0_3 仍 unapproved：本包不产生放行结论。

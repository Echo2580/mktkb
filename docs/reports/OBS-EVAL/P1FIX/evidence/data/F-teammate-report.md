# F 工作流报告：GO 请求计数语义核查 + 超限前拒绝 mock 负例 + 文档更正

- 状态：**已核实，无需修改运行期代码**（live.py / live_authorization.py / controlled_execution.py 零改动）；
  文档更正 1 份 + 新增 5 个 mock 负例；分支 p1/fix-retrieval，HEAD 3eec866；零真实调用/零网络/未读 .env。
- 一句话结论：GO `scope.bindings.rag.embedding_requests=7 / rerank_requests=4` 是 **S2-DEV 的 J2 受控计划值**
  （`request_plan_sha256` 绑定、plan 总请求 15），**不约束** P1 live 检索路线；P1 的运行上限是
  `scope.max_requests=1000`（累计口径）+ 阶段 3.0 元，实际 505/1000、0.0143149/3.0 均在上限内。
  review #56 的「口径差」是两类计数语义不同，不是 GO 违规，也不是「声明未执行」的运行期约束。

## 1. 五类口径（计划值 / 运行上限 / 实际请求 / 预留 / 结算）

| 口径 | P1 live 取值 | 执行/证据（文件:行） |
| --- | --- | --- |
| 计划值 | GO bindings：7 embedding/4 rerank/1+1 OCR（旧 GO 另有 chat 2），plan 合计 15、stage=S2-DEV | S2-LIVE-GO.json:21-33；controlled_execution.py:140-157,285-317,379-444 |
| 运行上限 | max_requests=1000（累计，跨 kind/stage/run）；max_request_cny=0.05；阶段 3.0；总 20 | live_authorization.py:539-547,614-625；rag/budget.py:555-569 |
| 实际请求 | 每次真实 HTTP=1 条 reserved 事件（零重试）；T111 各 27（17/10）、T112 70（39/31）；P1 累计 124 | rag/providers.py:329-350；budget.py:431；runner.py:1179-1181 |
| 预留 | embedding 0.04096 / rerank 0.024 元，写 reserved 事件；未结算按预留计占用 | evaluation/live.py:295-305；budget.py:580-602,396-400 |
| 结算 | result 事件；legacy max(预留,声明)；versioned usage-conservative-v1 重放；billed=null | budget.py:390-400,436-479；runner.py:1102,1179,1201-1203 |

## 2. 关键证据

- GO 7/4 由 `request_plan_sha256` 反解为唯一 J2 计划（只读复算）：
  `ControlledRequestPlan(stage="S2-DEV", chat_requests=2, embedding_requests=7, rerank_requests=4,
  ocr_text_requests=1, ocr_table_requests=1).request_plan_sha256 == 11b0218d…e52a`（GO 同值；total_calls=15）。
- 历史证据 `PM/S2-LIVE-GO-20261104.json:3,24,55-77` 保留同一 sha + 完整 chat 绑定（chat_requests=2、S2-DEV），
  证明当前 P1 GO 是沿用 J2 计划的 rag 块。
- P1 绑定核对只传 12 个 provider 键：evaluation/live.py:315-335（不含 plan_version/request_plan_sha256/
  embedding_requests/rerank_requests/ocr_*/token caps）；`assert_provider_binding` 只核对显式键
  （live_authorization.py:323-335）；bindings 解析仅形状/敏感校验（live_authorization.py:266-304）。
- 请求上限只来自 scope.max_requests：live.py:408-411 → resolve_live_gate:617 → BudgetLedger(max_requests)
  live.py:452-461 → 预留前 `facts["reservation_count"] >= max_requests` 拒绝 budget.py:555-558；
  请求期复核 live_authorization.py:720,741-747；发送前二次复核 budget.py:605-626。
- 当前 GO 下 J2 路线构造即拒（要 chat+rag 双绑定 controlled_execution.py:1019-1036；GO 仅 services=["rag"]），
  故 7/4 既非 P1 上限、也无当前可执行路线。

## 3. 新增 mock 负例（backend/tests/evaluation/test_live_request_accounting.py，5 passed）

命令：`$env:MKTKB_PROJECT_TOTAL_LIMIT_CNY="20.0"; .\.venv\Scripts\python.exe -B -m pytest
backend\tests\evaluation\test_live_request_accounting.py -q -p no:cacheprovider --basetemp backend\.pytest-tmp\p1fix-f`
结果：`5 passed, 1 warning in 0.46s`。用例：
1. `test_go_plan_counts_bind_the_s2_j2_plan_not_p1_request_caps`：sha 复算 + 阶段/上限/数值一致性。
2. `test_plan_counts_do_not_become_runtime_caps_for_p1_live_route`：隔离 GO 写计划值 1/1，
   运行上限仍 1000；27 请求预检 accepted（计划值不当上限）。
3. `test_assert_live_bindings_checks_provider_keys_but_not_plan_counts`：捕获期望键集合 == 12 provider 键、
   与 20 个计划字段无交集；缺 embedding_host 时正向拒绝。
4. `test_cumulative_request_cap_refuses_before_provider_http`：rerank 预留占满 max_requests=1 后，
   embedding provider 调用抛 RequestLimitExceeded；HTTP 尝试 0、账本 SHA/摘要不变（跨 kind 累计）。
5. `test_precheck_request_limit_insufficient_refuses_before_index_build`：累计已用=上限 → 预检
   reasons=("request_limit_insufficient",) 且 assert_accepted/run_suite 拒绝；out 目录/index 未创建、
   fake embedder/reranker 调用 0（构造前拒绝）。

## 4. 回归（全部绿）

`pytest backend\tests\evaluation\test_live_runner.py backend\tests\evaluation\test_t112_gate_baseline.py
backend\tests\unit\test_s2b_live_gate.py -q --basetemp backend\.pytest-tmp\p1fix-f`
→ 46 passed（test_live_runner 11 / test_t112_gate_baseline 13 / test_s2b_live_gate 22）；耗时 3.97s。

## 5. 文档更正点（新增 docs/evaluation/live-request-accounting-2026-11-10.md）

- 五类口径表；GO 字段「是否约束 P1 live」逐项表；四条依据（sha 反解/绑定键集合/上限来源/J2 路线不可构造）。
- 运行期拒绝链（构造期→预检→预留前→发送前复核→对账）与只读审计命令（账本 505：embedding 259/
  rerank 164/chat 78/ocr 4；S2-DEV 381/P1-RETRIEVAL 124）。
- 明确 #56 现象成立但语义不同类；p1-report §4 的请求数/账本增量属实际/预留/结算口径，与 1000 同口径。
- 未改 GO/预算/账本/历史报告/handoff 保护文件；未改代码 API/结构。

## 6. 剩余问题 / 建议写进总报告

- 建议总报告采纳：「#56 已核实为计数口径说明不充分（文档更正），非 GO 违规、非未执行运行期约束；
  零代码修复，负例锁定累计上限在 HTTP 前拒绝」。
- 残余风险：GO bindings 沿用 J2 计划块（含 chat/OCR/plan sha），P1 路线不核对其计划值；若未来重签 GO
  或升级 settlement_version，需重新对齐（本次不动 GO）。
- P1 的 token caps 由 settlement_version 冻结值决定（settlement_policy.py:42,57-58，当前与 GO 一致）。
- 预检为上限估计（T112 估 71/实 70：1 query 无候选），实际以账本 reserved/run summary 为准。

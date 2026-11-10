# P2-T203 独立验收（产品端到端运行器）

- 角色：独立验收助手（全新上下文，非开发者/经理）；证伪优先。
- 现场：分支 `codex/p2-e2e` @ HEAD `97fba10`；T203 交付**未提交**（跟踪改动 3 个文件：cli.py/p2_authorization.py/test_p2_authorization.py；新增 4 个代码/测试文件 + 契约/报告/证据）。
- 真实调用：**0**；未读 `.env`/H1/H2；未改源码/测试/开发报告/契约；未 commit/push；未跑全仓。
- 判定口径：只按 `.claude/handoffs/prompts/P2-T203-verify.md` 的 8 项；**不代表 P2 整体通过**。

## 结论：PASS（8/8），附 6 项非阻断发现（F1/F2 需在 T206 live 前修复）

| # | 验收项 | 判定 | 关键证据 |
|---|---|---|---|
| 1 | 范围与不回退 | **PASS** | 跟踪文件仅 `cli.py`(+147)/`p2_authorization.py`(+4)/`test_p2_authorization.py`(+15)；`live.py`/qa/rag/产品 API/schema/pyproject 0 行差异；`LIVE_SCOPE=retrieval_only`、`BUDGET_SECONDS=60`；旧子命令 `baseline/dataset/diff/export/gate/run` 仍在；加固仅插入 1 条检查+1 用例，旧断言未改 |
| 2 | 产品端到端真实性 | **PASS** | 探针 1（25 断言）：上传/发布/提问全走 HTTP（ASGI 记录 17 次路由调用）；trace 分支 `rag`+`legacy`；`RagIndex.ask` 调用者集合=`{mktkb.qa.service}`、`QaEngine.answer`=`{mktkb.conversations.service}`（评测模块 0 次）；引用转换/持久化/来源详情 200 vs 他人 403/旧版本 410 superseded/新提问版本≥2/幂等 |
| 3 | Mock 与零真实调用 | **PASS** | 自写 socket+httpx netguard 外部尝试 **0**（回环 1 次=asyncio self-pipe）；chat=`httpx.MockTransport`、embedding/rerank 离线替身计数>0；产物 `real_requests=0/billed_cny=0/requests_sent=0`；账本 `1f46…7390`、budget `084b…1cc58` 前后一致，`P2-LIVE-GO.json` 不存在 |
| 4 | 多轮/幂等/隔离 | **PASS** | 每 case 独立会话；多轮同会话两轮两条 trace；同 `client_request_id` 重放：同 message_id/request_id、消息数不变、chat 调用数不变；隔离库/索引/存储/账号全在临时目录，仓库 `var/` 最新 mtime `2026-11-10T01:04Z`（早于本次会话） |
| 5 | 门与失败语义 | **PASS** | `gate=None`→dry_run；Mock+真门→`mock_gate_requires_stub_gate`；真实适配器+无门→`adapter_must_be_mock`（探针 2 补证）；`production_ready=False`→`production_not_ready` 且 0 预留/0 发送；失败保留 stage/case/turn/item/ticket（多轮中间失败：`product_answer/V03/2/V03:turn2:answer`+ticket）；取消/超时/无候选拒答（`not_found` 且该轮 0 chat）/轮中知识库变化/503 后不再发、后续 case 不执行；空跑 `no_case_executed`→blocked |
| 6 | 产物与封存 | **PASS**（有残留风险） | run_manifest/summary/run_result/gate/公开 cases+requests 齐备；holdout 仅 `holdout_aggregate.json`（无 case_id/题干）、close 删 trace；不删 trace 时 hash 模式库内无题干明文；见 F3/F6 残留 |
| 7 | 时限 | **PASS** | `BUDGET_SECONDS=60` = `PRODUCT_TURN_TIMEOUT_SECONDS` = 适配器默认值 = `manifest.pipeline.turn_timeout_seconds`；0.2s 硬截止：`aborted/turn_timeout`、`failure.stage=product_wait`、`timeout_seconds=0.2`、第二 case 未执行、chat=1 |
| 8 | 复跑 | **PASS** | 指定两文件 **18 passed**（17.24s）；auth **70 passed**（1.35s）；见 `evidence/verify/pytest-verify.txt` |

## 实际命令（verifier 亲自执行）

```
.venv\Scripts\python.exe -B -m pytest backend/tests/evaluation/test_p2_runner.py backend/tests/integration/test_p2_product_e2e.py -q -p no:cacheprovider --basetemp backend/.pytest-tmp/p2-t203-verify
→ 18 passed, 1 warning in 17.24s
.venv\Scripts\python.exe -B -m pytest backend/tests/evaluation/test_p2_authorization.py -q -p no:cacheprovider --basetemp backend/.pytest-tmp/p2-t203-verify-auth
→ 70 passed, 1 warning in 1.35s
.venv\Scripts\python.exe -B docs/reports/OBS-EVAL/P2/T203/evidence/verify/probe-scripts/probe1_product_entry_netguard.py → ok, 25/25, external=0
.venv\Scripts\python.exe -B docs/reports/OBS-EVAL/P2/T203/evidence/verify/probe-scripts/probe2_stop_semantics.py      → ok, 25/25
.venv\Scripts\python.exe -B docs/reports/OBS-EVAL/P2/T203/evidence/verify/probe-scripts/probe3_holdout_sealing.py      → ok, 12/12
```

哈希：8 个交付文件 sha256 前 16 与开发报告逐一一致（`b7d3f372…`/`dd90e8cc…`/`1e5fab3f…`/`f2cc2f09…`/`ac75b860…`/`517885e9…`/`dc6267cc…`/`36de5bc2…`）；行数 1186/1186 与报告一致（PM 记录的 1032/1077 为旧快照）。

## 发现（均非本次阻断项）

- **F1｜T206 live 前必修：产物里的"零出站/零计费"是常量而非测量。** `summary.requests.real_requests=0`、`billed_cny=0.0`、`network.outbound_attempts=0` 为硬编码（`p2_runner.py:1122-1123,1127`），`provider_calls().outbound_network` 亦然（`product_adapter.py:872`）。本包零真实调用时值成立，但 `live` 分支会继续宣称 0。
- **F2｜契约偏差，T206 必修：`live` 未断言"门必须非桩"。** 真实适配器 + `is_mock_gate=True` 的桩门 + `production_ready=True` → `execution=live`、`real_sends_allowed=true`，门序照跑 begin/confirm/settle（探针 2 取证：`probes.json.summary.live_with_stub_gate`）；契约 §2 定义 `live` 为"非 Mock 适配器 + 真实 `P2Gate`"（`p2_runner.py:395-441`）。
- **F3｜holdout 未 fail-closed：** `purge_traces_on_close=False` 的 holdout run 不报错，trace 库保留（内容为哈希，无题干明文）；建议 runner 对 `visibility=holdout` 强制要求 purge（`p2_runner.py:1130-1137`）。
- **F4｜开发报告 §4 落点表述不实：** "P04（火星店）产品返回 `not_found` 且该轮 0 次 chat"被记在 `test_dry_run_completes_without_production_ready` 名下，但该用例只断言 4 cases/5 turns 完成，未断言 `kind` 或该轮 chat 数。行为本身正确——由验收探针独立验证（`no_candidate_refusal_not_found`/`_zero_chat`）。
- **F5｜开发用例覆盖缺口（已由探针补证）：** `adapter_must_be_mock` 与"多轮中间失败"两条路径在开发测试中无对应用例；代码行为正确。
- **F6｜产品预算/结算包装未进本包链路：** e2e 注入裸 `DeepSeekClient`+MockTransport，`create_app` 在 `model_gateway` 非空时不挂 settlement policy（`main.py:68-71`），故产品侧 budgeted provider 与费用归属未被本包执行（与"本包全 Mock"一致，T206 需用真实 `build_gateway` 复验）。

## 未覆盖 / 残留风险

- 真实 `P2Gate` 预留/结算、真实 GO、共享账本写入（按任务书归 T206，不在 T203）。
- 隔离 `out_dir` 内**业务库仍存题干明文**（探针 3 命中 `data/mktkb.sqlite3`；`p2-run` 产物与 trace 库无题干）——真实 H2 前需在 T206 清理/加密该目录。
- OCR/页级费用（T204）、评分与硬门（T205）、真实 H2 运行（T206）。
- 产品 60s 时限未真实等待 60s，用短超时参数等价验证停止语义。
- 未跑全仓；未跑 `test_p1_source_bridge.py`/`test_p1_refusal_scope_http.py`（本包未改公共转换，按提示词不跑）。
- `.claude/handoffs/_index.md` 的改动属协调文档（非 T203 允许文件），未作为验收对象。

## 证据（`docs/reports/OBS-EVAL/P2/T203/evidence/verify/`，4 入口）

1. `pytest-verify.txt`：两次指定复跑的原始输出。
2. `probes.json`：三个自写探针的逐条断言+关键观测（外部出站 0、caller 归因、holdout 命中文件、live+桩门取证）。
3. `probe-scripts/`：探针源码（可复跑，scratch 用系统临时目录）。
4. `ledger-budget-hashes.json`：共享账本/budget 前后 sha256 与 GO 文件缺失事实。

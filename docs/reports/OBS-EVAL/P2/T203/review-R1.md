# P2-T203-R1 独立复验（F1/F2/F3/F6 加固 + F4/F5/不回退）

- 角色：全新上下文的独立复验助手（非开发者/经理）；证伪优先，只按 `.claude/handoffs/prompts/P2-T203-R1-verify.md` 的 7 项判。
- 现场：`codex/p2-e2e` @ HEAD `897a751`；R1 未提交。改动仅 `p2_runner.py`/`product_adapter.py`/两测试/契约/report（+协调文档 `_index.md`，非验收对象），新增 `evidence/r1`。
- 边界：真实调用 **0**；未读 `.env`/H1/H2；未改源码/测试/报告/契约/evidence/r1；未 commit/push；未跑全仓。探针/测试产物只在系统临时目录与 `evidence/verify-r1/`。

## 结论：PASS（7/7 验项，无 FAIL/BLOCKED），附 9 项非阻断发现

| # | 验项 | 判定 | 关键证据 |
|---|---|---|---|
| 1 | F1 实测性（含 detail/顶层语义、settled_cny） | **PASS**（附 F1-a~e） | Mock 默认 0 由传输层实测（拦截 1）；把出站注入 `NetworkMeter` 本身 → `real_requests=2/billed=0.037376/outbound=4` 且顶层=detail=4；RAG post 注入 → 2/2、real=2；缺 `outbound_network`/`chat.calls` 均 `ValueError`；成功结算累计 0.018688（失败前为 0） |
| 2 | F2 live 必须真实 P2Gate | **PASS**（附 F2-a） | 真实适配器+桩门/鸭子门（`is_mock_gate` True/False）均 `blocked/live_requires_real_gate`；门 0 步、adapter 0 次、`real_sends_allowed=false`、`failed_checks={live_gate}`；`is_real_p2_gate` 仅真实 `P2Gate` 为 True；Mock+真实门仍 `mock_gate_requires_stub_gate`；真实适配器无门仍 `adapter_must_be_mock` |
| 3 | F3 holdout 强制 purge | **PASS**（附 F3-a） | holdout+purge=False → `blocked/holdout_requires_purge`、stage `holdout_policy`、ingest/chat/embedding 全 0、trace/业务库均未创建、只有聚合五件套、题干明文 0 命中 |
| 4 | F6 close 后 out_dir 无题干明文 | **PASS**（附 F6-a/b） | 自写哨兵：close 前命中 `data/mktkb.sqlite3-wal` → close 后 **0 命中**；`mktkb.sqlite3(-wal/-shm/-journal)` 全不存在；trace 库删除；聚合产物在；公开路径保留业务库/逐题产物；用目录卡住 `-journal` 使 unlink 失败 → `PermissionError`（不静默） |
| 5 | F4/F5 | **PASS** | F4：`test_p2_runner.py:453-462` 真断言 P04 `kind=not_found` + 该轮 `chat==0`，另有 chat>0 对照；report:58-59 已改口径。F5：`:1105` adapter_must_be_mock、`:1126` 第 2 轮 503 保留 stage/case/turn/item/ticket.request_id，均通过 |
| 6 | T203 原结论不回退 | **PASS**（附 F1-e） | 27 passed（含原 18）+ 70 passed；`LIVE_SCOPE=retrieval_only`/`BUDGET_SECONDS=60` 未动；`live.py`/qa/rag/产品 API/pyproject 0 差异；T203 probe1 已执行 22 条 0 失败（产品入口/多轮/幂等成立），但其最后一条断言因接口键删除而 KeyError（见 F1-e） |
| 7 | 证据真实性 | **PASS**（附 F1-a/F3-a） | 5 个文件行数/sha256 前 16 与 report 逐一相同；27/70 亲跑一致；R1 digest 复跑规范化后 JSON 深度相等；账本 `1F46…7390`、budget `084B…CC58` 前后不变；`P2-LIVE-GO.json` 不存在；探针 external=0、RAG `post_counters` 归零 |

## 亲跑命令（verifier，本机）

```
.venv/Scripts/python.exe -B -m pytest backend/tests/evaluation/test_p2_runner.py backend/tests/integration/test_p2_product_e2e.py -q -p no:cacheprovider --basetemp backend/.pytest-tmp/p2-t203-r1-verify
→ 27 passed, 1 warning（原始输出 evidence/verify-r1/pytest-verify.txt）
.venv/Scripts/python.exe -B -m pytest backend/tests/evaluation/test_p2_authorization.py -q -p no:cacheprovider --basetemp backend/.pytest-tmp/p2-t203-r1-verify-auth
→ 70 passed, 1 warning
.venv/Scripts/python.exe -B docs/reports/OBS-EVAL/P2/T203/evidence/r1/probe_r1_f1_f2_f3_f6.py
→ 与 r1-digest.json 一致（规范化临时路径后深度相等）
.venv/Scripts/python.exe -B docs/reports/OBS-EVAL/P2/T203/evidence/verify-r1/probe_verify_r1.py <digest>
→ 84 checks, 0 failed, external=0
```

## 非阻断发现（按建议优先级）

- **F1-a｜R1 证据自相矛盾：顶层 outbound=4，`network.detail.outbound_attempts=0`。** 原因是测试 `MeteredMockAdapter` 只改 `payload["outbound_network"]`（`test_p2_runner.py:955-957`），未改 `network`；runner 原样拼两份字段且不交叉校验（`p2_runner.py:1250-1253`）。生产适配器同源（`product_adapter.py:956-986`）时两者一致（我的注入=4/4；RAG=2/2），**故代码成立、证据不可全信**。建议：契约 §3/§5 明确 detail 是顶层的分解（非独立真值），runner 对不一致报错，测试改为注入 `NetworkMeter`（本复验探针已示范）。
- **F1-b｜RAG 增量无 R1 证据覆盖：** R1 测试/探针的 RAG `post_counters` 恒 0；代码路径仅由本复验覆盖（每轮 +1 次 RAG POST → 顶层/detail=2、`real_requests=2`、`billed=0.037376`）。建议 R2 补一个注入用例。
- **F1-c｜`billed_cny` 与 `settled_cny` 是两套口径（契约已写，风险留 T206）：** `billed_cny` 只累加"本轮 outbound>0"的 `charged_cny`（`p2_runner.py:1125-1133`）；纯 mock_gate 实测 `settled_cny=0.018688/轮` 而 `billed=0`（我复现）。真实链上 not_found/规则轮 0 chat 仍可能被 P2Gate 按上界结算，故 T206 计费应看 `settled_cny`。
- **F1-d｜门返回 bool/None 时 `charged_cny` 回退预留上界：** `_charged_cny`（`p2_runner.py:169-176`）保守，契约 §3 的"实际结算金额"措辞偏强；真实 `P2Gate.settle_success` 返回 float，不影响 live。
- **F1-e｜接口面删除导致 T203 旧证据不可复跑（建议合并前修）：** `MockChatBackend.as_dict` 删了 `outbound_network`（`product_adapter.py:411-419`，embedding/rerank 同），T203 probe1 第 281 行仍读 `chat["outbound_network"]` → `KeyError`（22 条 0 失败后崩）；report:78-79 仍写 `manifest.providers.chat` 的 `outbound_network=0`（R1 改的是顶层）。结论本身未回退，但证据入口/报告需同步。
- **F2-a｜类型检查≠资金来源：** `is_real_p2_gate` 只看 `isinstance(P2Gate)` + 无 `is_mock_gate`（`p2_runner.py:135-141`）；一个用内存账本/合成 GO 构造的 `P2Gate` 也会通过。R1 已如实声明正向真链归 T206；T206 必须用固定路径构造并复核 GO/账本绑定。
- **F3-a｜`question_store="deleted-at-close"` 是策略标签，不是测量：** `p2_runner.py:1258-1262` 对 holdout 无条件写，且在 close 前写入；F3 拒绝路径（业务库从未创建）也这么写。无明文泄漏，但"已删"不可由产物自证；建议 close 后写 `seal_receipt.json` 或改名为 `policy=delete-at-close`。
- **F6-a｜清理顺序/重试：** `close()` 先 `purge_traces()` 后 `seal_question_store()`（`product_adapter.py:903-907`），trace 删除抛错则业务库不封存；且 `_closed=True` 在任何清理前（`:887-888`），失败后不能重试 close。错误会抛出（不静默），但该路径不保证"0 明文"；建议 seal 放 `finally` 或先 seal。
- **F6-b｜测试脆弱：** R1 在 holdout 用例里新增的断言 `seal_receipt["removed"] == [business_db]`（`test_p2_runner.py:897-902`）；若 `-wal/-shm` 活到 close，`removed` 多几项即 flake。建议断言"包含 business_db 且 remaining 为空"。

## 未覆盖 / 残留

- 真实 `P2Gate` 的正向 live 链、真实 GO/账本、真实发送仍归 T206；本包只证"桩门/鸭子门必被拒 + 真实类型判定 + 正向注入计数"。
- 未跑全仓；未跑 `test_p1_source_bridge.py`/`test_p1_refusal_scope_http.py`（R1 未改公共转换）；未做真实 60s 等待（沿用缩短客户端超时用例）。
- `.claude/handoffs/_index.md` 有 +6 行协调文档改动（非源码/测试/契约/report），未作为验收对象；与 T203 验收时的处理一致。
- F6 只清题干所在的业务库；索引/存储语料副本与聚合产物保留（report 已披露）。F6 的"0 明文"依赖调用方执行 `close()`。
- 旧 probe1 运行产生的 `evidence/verify/probe-scripts/probe1_result.json` 为 verifier 副产物，已删除；未改任何跟踪文件。

## 证据（`docs/reports/OBS-EVAL/P2/T203/evidence/verify-r1/`，4 入口）

1. `probe_verify_r1.py`：本复验自写探针（84 断言；不复用 R1 的 Metered/Realish/StubGate；自带 socket 出站闸门）。
2. `verify-r1-digest.json`：逐条断言、场景输出、F1 top/detail 矛盾、F3 标签观测、F6 封存前后命中。
3. `pytest-verify.txt`：27 passed + 70 passed 的原始输出。
4. `integrity.txt`：文件行数/sha256 复核、账本/budget 前后 hash、GO 缺失、R1 digest 复跑一致性、旧 probe1 KeyError 附证。

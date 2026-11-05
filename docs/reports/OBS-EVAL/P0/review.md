# P0 独立总验收（T009）· review

- 日期：2026-11-05；分支 `p0/obs-eval` @ `a1a40cc`（纯簿记；最新交付 `2f7b174` T008b）；基线 `main` @ `8e44158`。
- 验收者：全新上下文，未参与 P0 开发/分项验收；只读仓库。环境：Windows PowerShell、Python 3.12.7 `-B`、
  `MKTKB_PROJECT_TOTAL_LIMIT_CNY=20.0`；串行 pytest；零真实模型/OCR/embedding/rerank；未读 `.env`。
- 依据：`.claude/handoffs/T009-closeout/handoff.md` §5 六条 + 设计 §11 七条。产物：本文件、`anchors.json`、
  `evidence/T009/01–04`；运行产物全部在 `%TEMP%\t009\`。

## 总判定：**有保留 PASS**

§5.1–§5.6 全部满足，七条 P0 均可复跑；无阻断缺陷、无越界、全量 1593 passed。
保留项（均为已知 NOT-RUN/文档口径，不阻断 P0 机制收口，但主人审批前**不能**宣称质量通过或真实放行）：
`mode=live → exit 4` 端到端未覆盖（仅单测）；真实 baseline/阈值审批属主人人工门且尚未建立；
设计 §7.2 的 locator 范围型正式口径尚未回写；`refusal_recall` 零样本显示 `status=pass` 的误导性口径仍在。

## 1. 七条 P0（设计 §11）

| # | 判定 | 命令 / 文件:行 | 实测结果 |
|---|---|---|---|
| 1 业务行为不变 | **PASS** | `pytest backend/tests/evaluation/test_p0_acceptance.py -q`；`pytest backend/tests/integration -q` | 7 passed（7.18s）；345 passed（262.14s）；golden 归一化比对 + 二次提问稳定（`test_p0_acceptance.py:181`，golden sha `b86484dc…8e52`） |
| 2 `trace_id` 端到端 | **PASS** | `test_p0_acceptance.py:213`；独立查询测试落盘 DB | 业务 trace `b597f890…799f`，`request_id=dd91e7d9…2c27` 非空、12 Span（parse/recall/fuse/answer/commit 等），重开仓储仍可查；`X-Trace-ID`/`X-Request-ID` 存在 |
| 3 B0 40 / BadCase 13 独立回归 | **PASS** | `tools/rag_eval.py run` b0 local + b0 replay + badcase local（`%TEMP%\t009`） | 40 行（pass29/fail3/OCR8，scored32）/ 40 行 replay（40/40 status/checks/metrics 相同）/ 13 行（pass9/fail4，scored13）；三件套 + `traces.sqlite3` 各自齐全、run_id/数据集互斥 |
| 4 版本绑定 | **PASS** | `probe_versions.py` 读 manifest/summary/traces | b0 `b0:b0-2026-11-04:bd4f0f7ccc6e`、rev6；badcase `badcase:badcase-2026-11-04:e5f0662af3f2`、rev4；`pipeline_version=735da1397044`、`gate_version=mktkb.gate.v0.1` 三处一致；dataset/corpus SHA 均实测一致（b0 40/40、badcase 13/13 trace 绑定） |
| 5 baseline + diff + JSON 报告 | **PASS（机制；真实 baseline NOT-RUN）** | `gate`/`baseline approve`/`diff`/`export`（`%TEMP%\t009\gate-approved.json`） | 默认 gate exit 3、无 baseline、审批拒绝（approval.json=0）；测试内审批 gate 0 → baseline `c0ce2856938f` → diff 0、`release_allowed=True`、`diff.json` 16855 B、`report.md` 7888 B、`report.html` 13451 B；**仓库无真实 baseline**，`diff` 无 baseline 时 exit 3「待 T009」 |
| 6 硬门禁非零退出 | **PASS（live→4 端到端 NOT-RUN）** | 矩阵 `test_gate.py::test_hard_gate_trigger_matrix`；独立 `probe_hard_gates.py` 调 CLI | 8 项各注入 1 次均 exit 1：security_leak / cross_entity / stale_bypass / conflict_not_rejected / exact_value_contract / pagination_contract / citation_required / trace_integrity（check_id 见证据 01）；live→4 仅 3 个单测；CLI live=2、手改 manifest=3，端到端未达 4 |
| 7 零真实调用 | **PASS** | `test_p0_acceptance.py:524`；独立 `probe_zero_calls.py` | provider spy=0、socket connect=0、`.env` 读取=0、业务 chat_model.calls=[]；badcase 13 行 + 默认 gate exit 3，quality=unknown；测试进程 `Settings.model_config["env_file"]=None` |

## 2. 全量回归（1 次）与测试计数

| 范围 | 结果 |
|---|---|
| 全量 `pytest backend/tests` | **1593 passed / 0 failed / 0 error，428.69s（7:08）**；基线 1586（T008a）+ T008b 新增 7 = 1593 |
| `backend/tests/evaluation` | 320 passed，17.03s |
| `backend/tests/integration` | 345 passed，262.14s |
| `test_p0_acceptance.py` | 7 passed，7.18s |
| 8 项矩阵 + 3 个 live 单测 | 11 passed，0.42s |

未重跑旧 commit 基线全量（提速策略 A）；以“当前 0 failed + 新增 7 + 398 文件改动审计”证明无回归。已知 flake
`test_g08_short_budget_cancels_inflight_model_call` 未命中；唯一 warning 为既有 Starlette 弃用提示。

## 3. 契约一致性抽查

- **reason-aware 行与实现一致**：`trace_schema_v0_1.md:163`（rag+no_answer+DOCUMENT_NOT_FOUND/UNKNOWN_STORE/RECORD_ONLY → `parse,commit`）
  ↔ `contracts.py:149-154`；`:182`（legacy+not_found 解析级早退 → `intent_parse,commit`）↔ `:155-160`；
  `:185`（legacy+knowledge_changed+`KNOWLEDGE_CHANGED_AT_COMMIT` → `intent_parse,commit`；其它 reason 仍要求 retrieve）↔ `:161-166`。
  `validate_required_spans` 读 `record.reason`（`contracts.py:269-297`）；gate 按 reason 重算（`gate.py:1838-1856`）。
- **配置仍 unapproved/阈值空**：`gate_v0_1.json` sha `8b3718…d209`；`status=unapproved`、`quality_layer.status=unapproved`、
  15 个指标阈值全 null、`hard_gate_min_sample={b0:32,badcase:13}`（T009 未改写）。
- **分母一致**：硬门禁 `evaluated_count` b0=32/badcase=13（实测 gate scored 32/32、13/13）；质量检索 b0=32/badcase=10；
  质量答案 b0=32/badcase=13；拒答 badcase 2/11，`error/service_error/knowledge_changed` 已排除（`gate.py:216,2009-2011`）。10 与 13 未混用。
- **残余口径**：b0 默认 gate 的 `refusal_recall/all` 为 denominator=0、observed=None、`status=pass`（T007-R1 残余），
  不得读作“拒答召回通过”；`GateConfig.to_dict` 仍输出旧键 `min_sample`（`gate.py:310-316`），不可 round-trip。

## 4. 越界检查

- `git log main..p0/obs-eval`：**38 个 commit、398 个唯一路径**；逐 commit 审计 0 个路径超出
  “P0 允许前缀 + 6 个授权接线文件”的并集（允许前缀：`observability/`、`evaluation/`、`tools/`、`backend/tests/`、
  `docs/evaluation/`、`docs/reports/OBS-EVAL/P0/`、`.claude/handoffs/`、`fixtures/evaluation/`）。
  6 个接线文件均为对应包 handoff §2 明确授权：
  `main.py`/`config.py`（T003b `d41d19f`）、`rag/answer.py`/`rag/retrieval.py`（T003c `776497f`）、
  `qa/service.py`/`conversations/service.py`（T003d `b811f9f`+`71756f5`）。
- **无依赖/迁移/schema 改动**；`var/`、`docs/evidence` 无 P0 提交；`git status --short` 在写入本产物前为空。
- **业务 API/Body 不变**：当前 `app.openapi()` 与 T003b 验收快照语义相等（18 paths / 31 schemas）；
  baseline/target 快照逐字节相同（sha `2154b8…ae7a`）。
- T001–T008b 开发 commit（含 R1）：`7b02f40,2ac976f,dea4d5d,d41d19f,776497f,b811f9f,71756f5,574e288,f126598,
  80fd092,f6bb3c4,90d7133,5a4c054,6447b85,08536ed,f2c0209,2f7b174`；HEAD `a1a40cc`。

## 5. 未覆盖 / NOT-RUN（不得写成通过）

`mode=live→4` 端到端；真实 baseline + 阈值审批（主人人工门）；真实 OCR/embedding/rerank/聊天模型；P1/P2 真实回答质量；
HTML 渲染效果；`cross_entity`/`stale_bypass` 的真实 case 类（v0.1 无该字段，`not_applicable`）；`pagination_contract`
真实 fixtures 期望（`expected_pagination` 全 null）；#7 业务问答阶段 socket guard 已释放（T008b LOW-4）；
golden 双采集脚本未入库（LOW-2）；T006b proposal 的 `%TEMP%` run 未持久化；设计 §7.2 locator 正式口径未回写。

## 6. 遗留项复核（_index 1–34 + 后续 review，抽查）

- **已闭环/历史**：1–2、4、11、20–23、25、28–29（文档/证据/流程/簿记）；3（legacy 共用规则已写入 `trace_schema:147`）；
  13–14、16（后续包覆盖/授权改断言）；17、19、26（reason-aware + R1）；27 的 replayed 跳过已实现（`gate.py:1817-1820`）；
  30-M2 的 gate 侧、31-M2/M4、32-M1/M2 已由 T006a/T006b 闭环（record_code/空 locator → unknown；拒答排除；unit 级泄漏映射；
  `evaluated_count`；CLI 传 gate）；33-L3 为历史证据标签，不影响结论。
- **仍存在且非阻断**：5–6（`pipeline_version` 延迟 import/`config_hash` 白名单）、7–10（内核 annotate/JSON 边界，gate 按不可信输入处理）、
  12（既有测试写 gitignore 的 `docs/evidence`）、15（既有 flake）、24/27（T003d 证据精度）、30-M1（设计 §7.2 未回写）、
  30-M2 的 `gold.py:200-201` 仍会整篇展开（gate 已 fail closed）、30-M3（N06 单轮说明）、31-M1/L3–L5、
  32-L（replay provenance/OCR range/字节哈希）、33-L1/L2（`to_dict` 键名、`scored_count` 别名）、T006b M1/M3、T007-R1 残余。

## 7. 给主人的摘要（≤10 行）

1. **总判定：有保留 PASS**；P0 七条机制全部可复跑，无阻断缺陷，全量 1593/1593。
2. 零真实调用：provider=0、socket=0、`.env`=0；B0 40 / BadCase 13 与 replay 独立通过。
3. 版本绑定、8 项硬门禁 exit 1、baseline/diff/JSON 报告机制均实测通过（仅 `%TEMP%` 演示审批）。
4. **当前不放行**：仓库无真实 baseline、阈值仍 unapproved，默认 gate=3、`diff`=3；这是设计约束，不是失败。
5. **真实阈值审批仍需您决策**：T006b 提案是 per-stratum 建议，不能直接抄进单值 MetricSpec；请先定 b0/badcase 可行单值或扩展 schema。
6. **live→4 端到端仍是 GAP**：仅单测覆盖；CLI live=2、手改 manifest=3。请决定是否接受该 P0 边界。
7. 设计 §7.2 的 locator 范围语义需补正式口径；`refusal_recall` 零样本显示 pass 需在报告中注明“不可读作通过”。
8. 未覆盖：真实 OCR/embedding/rerank/模型、P1/P2 质量、HTML 渲染、`cross_entity`/`stale_bypass` 真实类。
9. 越界：38 commit/398 路径全部合规（6 个接线文件有包级授权）；无 API/Body/schema/依赖改动。
10. 建议：接受 P0 机制收口；阈值/baseline 审批与 §7.2 文档修正作为合并前的人工门项，不阻塞本次 P0 验收结论。

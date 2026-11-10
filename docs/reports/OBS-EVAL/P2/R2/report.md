# P2-R2 加固报告：T203/T204/T205 验收遗留（T206 前）

- 角色：P2 加固开发助手 R2（全新上下文）；只修三包验收遗留项，不新增功能、不自验通过。
- 现场：`codex/p2-e2e` @ `d850b49`（未切分支、未 commit/push）；真实调用 **0**（全 Mock，未读 `.env`/H1/H2，未联网，未碰 `var/`）。
- 边界：只改 dev.md 允许文件；**未改**冻结 fixtures、review 文件、业务 API/schema/依赖、`gate_v0_3.json`；未跑全仓。

## 1. 逐项修复

| # | 遗留（来源） | 修复 | 验证 |
|---|---|---|---|
| A1 | T203 R1-F1-a：顶层 outbound 与 `network.detail` 可自相矛盾 | `p2_runner._validated_network()`：detail 是顶层的**分解**，`chat+rag == detail.outbound == 顶层`；缺/detail 不符 → 稳定码 `provider_network_detail_mismatch`，不静默拼接。契约 §5 写明。`MeteredMockAdapter` 改为在计量器本身注入 | `test_inconsistent_network_detail_is_a_stable_error`（只抬顶层 / 分解之和对不上）、`test_missing_network_detail_is_refused` |
| A2 | T203 R1-F1-b：RAG `post_counters` 增量无用例 | 新增 `RagPostMockAdapter`（每轮真记一次 `rag.providers` POST） | `test_rag_post_increment_flows_into_summary_and_billing`：逐轮 outbound=1、`real_requests=2`、`billed=2×0.018688`、detail=(0,2)、provider chat=0 |
| A3 | T203 R1-F1-e：旧 probe1 `chat["outbound_network"]` KeyError | `provider_calls()` 恢复 `chat/embedding/rerank/ocr` 的 `outbound_network`（chat=计量传输实测；离线替身结构性 0），与顶层同源；T203 报告 §6 表述同步 | 复跑 `probe1_product_entry_netguard.py` → 25 断言 0 失败、`external=[]`（此前 KeyError 崩） |
| A4 | T203 R1-F3-a：`question_store` 冒充测量 | 改策略标签 `policy:delete-at-close` / `policy:keep-in-isolated-dir` + `question_store_measurement`（真证据 = `close()` 的 `seal_receipt`）；契约 §3 写明 | `test_holdout_run_writes_aggregate_only_and_purges_traces` |
| B1 | T204 N1：probe 覆写归档证据 | `probe_t204.py` 默认 stdout，落盘需 `--out`；stdout/stderr 强制 UTF-8 | 复跑后 `02-probe-output.txt` 字节不变（7786B/`805dc852…`）、出站 0 |
| B2 | T204 N2：契约 §4 四个不可达拒绝码 | 标为"当前路径不可达的防御分支"，写明实际语义（换模式→`miss`；伪造 payload→`cache_payload_invalid` 隔离）；**门控未改** | `p2_ingestion.py` 零改动；T204 18 passed |
| B3 | T204 N6：`ocr_transcripts.py:79` 注释与行为相反 | 注释改为 table（`test_rule_table_scan` 断言 True），注明"行为未改" | 见 §4 偏差①；`test_rule_table_scan.py` 6 passed |
| B4 | T204 N7：端到端"缓存命中"混称 | 契约 §4/§7 与 T204 报告 §3：产品检查点**先短路**，`OcrResultCache` 命中只在模块级可证；两类计数分开 | 文档口径一致（无代码行为变化） |
| C1 | T205 2b **验收 FAIL**：无 L/真实标记 | `P2CaseScore`/`P2PublicScorecard`/`P2HoldoutScorecard`/`P2GateDecision` 加 `execution_mode`+`real_calls` 并入 `to_dict()`；默认保守 `local_mock`/0，live 必须显式；mock 声称真实调用 → `real_calls_without_live_mode`；公开矩阵混模式 → `execution_mode_mixed` | 3 个新用例（默认/显式 live/mock 谎报拒绝/混模式/派生） |
| C2 | T205 F2：F01 正确回答被判"编造" | 给 F01 加 `reference_answer`（含 2026-09、指标、口径 `×100%`、目标 90%），问题保留"口径"；`probe_t205.py` 同名 CaseSpec 同步 | `test_f01_correct_answer_with_formula_passes`：正确回答 pass；缺 90% / 换 95% 仍 fail；**冻结 fixtures 未动** |
| C3 | T205 F3：证据乱码 | `-X utf8` 重生成 `evidence/02-reproduction.txt`（4272B，无 `U+FFFD`，中文可读） | 逐条读回：F01 fail(value_hit)、F05 pass、出站 0 / RAG POST 0 |
| C4 | T205 F4：scorecard 未绑定 run | scorecard/decision 加 `run_id`；`evaluate_p2_gate` 从 manifest 取 run 身份，scorecard 不符 → `run_binding_mismatch`（unknown 不放行），显式冲突 → `run_id_mismatch`；**config_hash 级绑定留 T206/T209**（理由见 T205 report R2） | 3 个新用例（绑定/异 run 拒绝/模式与声明一致） |

## 2. 改动文件（行数 / sha256 前 16）

| 文件 | 行数 | sha256/16 |
|---|---|---|
| `backend/src/mktkb/evaluation/p2_runner.py` | 1359 | `af9d7c2e13dd71e4` |
| `backend/src/mktkb/evaluation/product_adapter.py` | 1316 | `6dfb759acd8206d5` |
| `backend/src/mktkb/evaluation/p2_scoring.py` | 1945 | `130a4a06f81c61ec` |
| `backend/tests/evaluation/test_p2_runner.py` | 1350 | `251b6b072016947e` |
| `backend/tests/evaluation/test_p2_scoring.py` | 652 | `2f77c24dd56bce56` |
| `backend/tests/evaluation/test_p2_gate.py` | 934 | `ff6bcd1a59acca7b` |
| `backend/tests/integration/test_p2_public_controls.py` | 541 | `e923a59ff402c394` |
| `backend/tests/acceptance/support/ocr_transcripts.py`（仅注释） | 138 | `b975e8e4a08ed100` |
| `docs/evaluation/p2-runner-contract-v0_1.md` | 156 | `52dc9104fb9e6ed6` |
| `docs/evaluation/p2-ocr-contract-v0_1.md` | 174 | `c034902a9bfcaeae` |
| `docs/reports/OBS-EVAL/P2/T204/evidence/probe_t204.py` | 572 | `fc905f657bfb0b15` |
| `docs/reports/OBS-EVAL/P2/T205/evidence/probe_t205.py` | 240 | `75ae2b44459df3da` |
| `docs/reports/OBS-EVAL/P2/T205/evidence/02-reproduction.txt` | 163 | `6ccec007dd7c30ed` |

另：T203/T204/T205 报告各追加 `## R2` 段；`docs/reports/OBS-EVAL/P2/R2/` 为本报告 + 证据。`gate.py`、`p2_ingestion.py`、fixtures、review、业务代码 **零改动**。

## 3. 命令与结果（本机亲跑，UTF-8 原始输出见证据 1）

```
pytest backend/tests/evaluation/test_p2_runner.py backend/tests/integration/test_p2_product_e2e.py -q  -> 30 passed (原 27 + 3)
pytest backend/tests/evaluation/test_p2_authorization.py -q                                          -> 70 passed
pytest backend/tests/evaluation/test_p2_ocr_ingestion.py backend/tests/integration/test_p2_ocr_source_identity.py -q -> 18 passed
pytest backend/tests/evaluation/test_p2_scoring.py test_p2_gate.py backend/tests/integration/test_p2_public_controls.py -q -> 51 passed (22+23+6；原 44 + 7)
pytest backend/tests/evaluation/test_gate.py test_gate_quality.py -q                                 -> 109 passed
pytest backend/tests/unit/test_rule_table_scan.py -q                                                 -> 6 passed
```

probe：T203 probe1 25 断言 0 失败（external=[]）；T204 probe exit 0（external=[]、loopback=22）；T205 probe 出站 0 / RAG POST 0。三包均未跑全仓。

## 4. 偏差与残留（如实）

1. **B3 路径偏差**：任务单写 `backend/src/mktkb/providers/ocr_transcripts.py`，该文件不存在；N6 指的是 `backend/tests/acceptance/support/ocr_transcripts.py:79`。按 N6 事实只改注释（1 处），`test_rule_table_scan` 复跑通过。
2. **A4 标签改名影响历史证据**：`evidence/r1/r1-digest.json` 与 `verify-r1/probe_verify_r1.py` 仍按旧值 `deleted-at-close` 断言（未回改，属 R1 时点记录）；复跑该旧探针会失败。旧 probe1 不受影响（已复跑通过）。
3. **C4 未做部分**：scorecard 侧目前只绑 `run_id`；`config_hash` 级绑定需 T206 采集侧把 gate 配置身份写进 run 产物，届时在 `evaluate_p2_gate` 一并核对（T205 report R2 已写明理由）。
4. **C1 传播面**：`execution_mode`/`real_calls` 目前由调用方显式传入（默认 `local_mock`/0）；T206 真实链必须在采集侧显式标 `live` 并给实测 `real_calls`，否则产物会如实显示"本地/Mock"——这是刻意的保守默认，不是遗漏。
5. **未做**：真实 `P2Gate` 正向 live 链、真实 OCR/账本/GO（T206）、T207 产品修复、全仓回归、浏览器链路。

## 5. 证据入口（3）

1. `evidence/01-pytest.txt`：上表 6 条命令的原始输出（30/70/18/51/109/6，全部 exit 0）。
2. `evidence/02-probe-outputs.txt`：三包 probe 复跑摘要（T203 25 断言 / T204 零出站 12 次调用 + 重试/取消 / T205 F01–F05 判定 + 出站 0）。
3. `evidence/03-r2-semantics.json`：11 条语义断言（A1 稳定错误码 3 例、A3 provider 字段、C1 默认/live/谎报、C2 正反例）+ 改动文件身份 + 各修复对应的测试名。

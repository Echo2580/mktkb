# T005 · Replay / Local Runner + 运行清单 — report.md

## 1. 完成内容

- 新增 `backend/src/mktkb/evaluation/corpus.py`：thin adapter over `tools/rag_experiment.py`；
  B0 只装配 `xlsx/docx/pdf-text`（D01–D06，D07–D10 装配期按 kind 跳过、绝不解析）；
  badcase 复用 `load_corpus` + `build_new_index`，E03/E11/P03/W01 缺一份即 `CorpusError`。
- 新增 `backend/src/mktkb/evaluation/runner.py`：`run_suite` / `RunManifest` / `RunResult`；
  local 建临时隔离索引并直接 `RagIndex.ask`；replay 只读源 run 的 `run_manifest.json` +
  `cases.jsonl` 重评分（不建索引、不写索引库、不调 provider）。两者均产出三件套并写
  `traces.sqlite3`（local 执行 Trace；replay `replayed=True`、Span 为空）。
- 新增 `backend/tests/evaluation/test_runner.py`：20 tests；未改 `conftest.py`、
  `dataset/gold/scorers`、`observability/**`、业务代码或既有断言；未新增依赖。
- `cases.jsonl` 持久化逐 case `status/trace_id/checks/metrics`、gold unit 集合、**有序
  `retrieved`** 与 citation；`unit_ids` 来自 `RagChunk.unit_ids`，`unit_key` 来自
  `RagUnit`（T004b MEDIUM-4：同时保留 `doc_code` + `unit_key` + `locator`）。

## 2. §5 逐条自证

1. 三件套 + 双模式：`test_runner.py:130`（b0 local 40 行）、`:156`（badcase local 13 行）、
   `:266`（b0 replay）、`:288`（badcase replay）；每行含 `case_id/status/trace_id/checks`。
2. 版本绑定：`:187` 校验 dataset/corpus sha、dataset_version、index_revision、pipeline/gate；
   `:203` 两次 local run 身份字段一致（仅 run_id/created_at 可变）；字段见 `runner.py:84/116`。
3. 零真实调用：`:226` 对 Bailian embed/rerank、DeepSeek complete 做 spy（=0）并 guard
   `socket.connect`；`Settings` 未实例化（不读 `.env`）；offline 强校验 `runner.py:306`。
4. replay 确定性：`:266/:288` 逐行 `status+checks+metrics` 相同；`:341` monkeypatch
   `build_suite_index`/provider 后 replay 仍通过，out_dir 仅三件套 + `traces.sqlite3`；
   `:328` `replay_from=None` 显式 `ValueError`；`:373` replay Trace 无 Span、指向 local。
5. unit 级闭合：`:468` 断言 citation/retrieved 逐 unit 且 `unit_ids`/`unit_key` 等于真实
   `RagUnit`；`:498` 用持久化 `unit_key` 验证 `forbidden_sources` 可命中（MEDIUM-4）；
   `:514` OCR 8 行 skipped、分母 32；`:389` 缺 unit_ids → error；`:589` `record_code`-only
   → `record_code_only_gold` error，N09 整篇范围 gold 不误伤（`:564`）。
6. 测试与回归：见 §3；无新增依赖；未触碰禁用路径。

## 3. 实际运行结果

- 本包 `pytest backend/tests/evaluation/test_runner.py -q ...` → **20 passed**（7.82s）。
- 目录 `pytest backend/tests/evaluation -q ...` → **124 passed**（8.09s）。
- 全量 `pytest backend/tests -q ...` → **1397 passed, 0 failed/0 error**（385.26s = 6:25；
  基线 1377 + 新增 20）。
- commit `p0/T005 runner`（单 commit；提交内容不能自引用自身 sha，最终 sha 见
  `git log -1 --format=%h` 与末尾摘要）。staged stat：
- staged stat：8 files changed, **2498 insertions(+)**
  （runner 1387 / test_runner 631 / corpus 294 / report 80 / evidence 25+47+19+15）。
- 真实两模式（`%TEMP%\t005-runs`，不 commit）：b0 local 40 行（pass 29/fail 3/skipped 8）
  `Recall@10=0.96875 MRR@10=0.869792 nDCG@10=0.895458`；b0 replay 40/40 行
  `status+checks+metrics` 与 local 相同；badcase local 13 行（pass 9/fail 4）
  `0.767914 / 0.716667 / 0.685102`。身份：index_revision 6/4、
  `pipeline_version=735da1397044`、`gate_version=mktkb.gate.v0.1`；产物 sha 见 evidence 02。

## 4. 偏离与未做

- PM 追加（T004b MEDIUM-4）已实现：citation/retrieved 按 chunk 真实 unit 逐 unit 展开，
  每条写 `doc_code + unit_key + locator + unit_ids`；本机 unit_key 全部可取，无 null。
- `doc_code`-only gold（N09）按设计保留为整篇范围型 gold；仅 `record_code`-only fail closed
  （handoff §7.1 与 §7.2 的兼容解释，测试已显式覆盖）。
- replay 不复用源 run 的运行时数值（`trace=None`，latency/p50/p95 为 null）；
  checks/metrics/status 与 local 一致，允许差异字段见 evidence 02。
- 未做（不在本包）：diff/report.html（T007）、gate（T006）、CLI（T008）、live（P0 禁止）。

## 5. 风险与遗留

- citation 按 unit 拆分后同一 chunk 可能多条引用（每条 unit_ids 长度 1）；scorer 按 unit
  去重、指标不变，下游若假设“1 citation = 1 chunk”需注意。
- replay 检测 `checks/metrics/status` 漂移并标 `replay_score_mismatch` error；未来改
  scorer 会让旧 run replay 显式失败（不静默通过），需重建 local run。
- B0 本轮 3 个 fail（Q25/Q26/Q31）来自既有离线检索/抽取口径，不是 runner 失败；本包
  不调参、不改 scorer。
- `cases.jsonl` 保留全量 locator（含单元格明细），b0 40 题约 204KB；P0 可接受。

## 交接摘要（≤10 行）

- commit：`p0/T005 runner`（单 commit，基于 d1a9d92；最终 sha 见 `git log -1 --format=%h`）。
- 交付：`evaluation/corpus.py`、`evaluation/runner.py`、`tests/evaluation/test_runner.py`、
  `evidence/T005/00..03`、本报告。
- §5 六条：三件套/双模式 ✅；版本绑定 ✅；零真实调用 ✅；replay 确定性 ✅；
  unit 级闭合 ✅；目录 124 + 全量 1397 passed ✅。
- 未提交运行产物（`%TEMP%`/`var/`）；未 push；未动 PM 文件与其他包。
- 遗留：离线 scorer 3 个 fail（Q25/Q26/Q31）不属本包；citation 拆分口径已写报告，
  供 T006/T007 使用时注意。

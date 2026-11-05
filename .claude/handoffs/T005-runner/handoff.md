# T005 · Replay / Local Runner + 运行清单（P0 第 9 包）

> PM 任务单。基线：`p0/obs-eval` @ T004b 收口 commit `f126598`（开工前 `git log --oneline -2` 确认；HEAD 可能是 PM 的簿记 commit `9d52b7c`，其代码等同 `f126598`）。
> T001–T004b 已通过独立验收（T004a/T004b 结论见各自 `review.md`）。本包只新增 runner/corpus 与测试，不接门禁、不改 dataset/gold/scorers。
> 完成后由**全新上下文**的独立验收助手按本文件 §5 逐条证伪。

## 1. 目标（一句话）

用 `run_suite` 把已冻结的 b0/badcase 数据集跑成可复现的运行产物：`local` 在隔离索引上直接调 `RagIndex.ask`（offline provider、零真实调用），`replay` 从上一轮产物重评分（不建索引、不调 provider）；两者都产出 `run_manifest.json` / `cases.jsonl` / `summary.json`，且 `cases.jsonl` 自带 `unit_ids`，使 unit 级检索指标在 replay 下仍可计算（闭合 T004b 的 fail-closed 风险）。

## 2. 交付物（只准写这些路径）

- 新增 `backend/src/mktkb/evaluation/corpus.py`（薄适配 `tools/rag_experiment.py`，不复制解析逻辑）
- 新增 `backend/src/mktkb/evaluation/runner.py`（`run_suite`、`RunManifest`、`RunResult`、`CaseResult` 汇总）
- 新增 `backend/tests/evaluation/test_runner.py`；**允许对 `backend/tests/evaluation/conftest.py` 追加 fixture（只增不改既有行）**
- 证据（入库，**≤4 份**）：`docs/reports/OBS-EVAL/P0/evidence/T005/`（00 基线、01 本包测试、02 local run 产物摘要、03 replay 一致性与全量）
- 报告：`.claude/handoffs/T005-runner/report.md`（五段，**≤80 行**）

## 3. 输入（只看这些）

1. 设计 §7.3（版本绑定字段）、§9（P0 运行模式：replay/local/live 禁止）、§8.5（产物清单）。
2. 计划 Task 4 Step 4 的 runner 段（`run_suite` 接口、local 建隔离索引、replay 输入、三件套输出）。
3. 已验收代码（**只读**）：`evaluation/{dataset,gold,scorers}.py`（`CaseSpec`/`ResolvedGold`/`EvalOutcome`/`score_case`）、`observability/{contracts,tracer,store,versioning}.py`（`start_trace(..., repo=...)`、`TraceRepository`、`pipeline_version`）。
4. 语料装配范式（只读）：`tools/rag_experiment.py` 的 `load_corpus` / `build_new_index`；`backend/tests/evaluation/conftest.py` 的 `offline_config` / `build_b0_index` / `build_badcase_index`。
5. 数据与语料：`fixtures/evaluation/{b0,badcase}.jsonl`；`fixtures/acceptance/manifest.json`（normal_files，B0 非 OCR 资料 D01–D06）与 `corpus/enterprise-20261101/manifest.json`。

## 4. 允许 / 禁止

**允许**：§2 交付物；`git switch p0/obs-eval`；本包一个 commit。

**禁止**：
- 不改 `evaluation/{dataset,gold,scorers}.py`、不改 `observability/**`、不改业务代码/API/业务库与 `rag-index.sqlite3` schema、不改既有测试断言（conftest 只追加）。
- 不新增生产依赖；零真实模型/OCR/embedding/rerank 调用（必须 `provider_mode="offline"`）；不读 `.env`；不打印凭据。
- 不写 `fixtures/**`、`docs/evidence/**`、账本/GO；不碰 `docs/reports/OBS-EVAL/P0/evidence/verify/**`（验收方目录）。运行产物只写 `out_dir`（生产默认 `var/eval/runs/<run_id>/`，已被 gitignore；测试用 `tmp_path`），不 commit 任何产物体。
- 不 push、不动 PM 未跟踪文件。

## 5. 验收标准（逐条可判定）

1. **三件套 + 双模式**：`run_suite(suite="b0"|"badcase", mode="local"|"replay", corpus_dir=..., out_dir=..., scope="end_to_end", replay_from=...)` 在两种模式、两个 suite 下各产出 `run_manifest.json` / `cases.jsonl` / `summary.json`；`cases.jsonl` 的 case 数与数据集行数一致（含 `skipped_requires_ocr` 与空 gold case），每行至少含 `case_id`/`status`/`trace_id`/`checks`。
2. **版本绑定**：`run_manifest.json` 含 `run_id`、`mode`、`scope`、`dataset_version`、`dataset_sha256`、`corpus_manifest_sha256`、`business_date`、`index_revision`、`pipeline_version`、`gate_version`；同输入两次 local run 的这些**身份字段**相同（仅 `run_id`/时间戳可变）。
3. **零真实调用**：local 全程 offline provider；用 spy/计数断言 provider 调用数 = 0、无 socket 出网尝试；未读 `.env`。
4. **replay 确定性**：`replay_from=<上一轮 local run 目录>` 时不建索引、不写索引库、不调 provider；同一 case 的 checks 与 local 轮逐条一致（容忍 `duration_ms`/时间戳/`trace_id`/`status` 的 replay 标记差异，须在报告写清哪些字段允许不同）；`replay_from=None` 时 replay 明确报错（不静默降级为 local）。
5. **unit 级口径闭合**：`cases.jsonl` 的引用与检索结果必须自带 `unit_ids`（由 chunk 的真实 unit 归属填充，不得由 scorer 猜或留空）；replay 从 `cases.jsonl` 重建 `EvalOutcome` 后 Recall@10 / MRR@10 / nDCG@10 与 local 轮一致；OCR case 标 `skipped_requires_ocr` 且不进任何指标分母；无 gold case 不进检索分母但必须出现在 `cases.jsonl`。
6. **测试与回归（提速策略 A）**：`pytest backend/tests/evaluation -q` 全绿；全量 `backend/tests` **只在提交前跑 1 次**，目标 = 1377（T004b 基线）+ 本包新增、0 failed / 0 error；不新增依赖。

## 6. 必须实际运行的检查（输出摘要存证据目录）

```powershell
$env:MKTKB_PROJECT_TOTAL_LIMIT_CNY = "20.0"
git rev-parse --short HEAD
.\.venv\Scripts\python.exe -B -m pytest backend/tests/evaluation/test_runner.py -q -p no:cacheprovider --basetemp backend\.pytest-tmp\runner
.\.venv\Scripts\python.exe -B -m pytest backend/tests/evaluation -q -p no:cacheprovider --basetemp backend\.pytest-tmp\eval-all
.\.venv\Scripts\python.exe -B -m pytest backend/tests -q -p no:cacheprovider --basetemp backend\.pytest-tmp\t005-full
git show --stat --oneline HEAD
```

同时给一条**真实两模式跑通**的命令示例（可写进测试或 `python -c` 一次性脚本），输出 local 与 replay 两次的 `summary.json` 关键指标对照；运行目录用 `%TEMP%` 或 `var/eval/runs/`（不 commit）。

## 7. 已知边界（必须遵守）

- `var/` 整目录 gitignore：产物不入库，只在报告写路径、行数与 sha256。
- B0 只索引 D01–D06（xlsx/docx/文本 PDF）；D07/D08 扫描 PDF 与 D09/D10 图片**禁止解析**（解析即触发 OCR 路径）；badcase 必须解析 E03/E11/P03/W01，缺一份 fail closed。
- 既有 flake `test_g08_short_budget_cancels_inflight_model_call` 与本包无关；命中时隔离复跑并记录，不改既有测试。
- **T004a 验收遗留（PM 裁决，2026-11-05，必须遵守）**：
  1. `record_code` **不是解析键**：`{"doc_code":"D01","record_code":"P01"}` 会被 `resolve_gold` 解析为整文档全部 unit。当前 fixtures 未使用该形态；runner 必须**防御式 fail closed**（gold 引用既无 `unit_key` 也无 `locator` 时直接报错/标 `error`），不得静默扩为整文档 gold。
  2. `locator` 是**范围型**（N05 整表 11 unit、N09 整篇 17 unit 属正常语义）：gold 是 unit 集合，不得当"精确单 unit 命中"用于 citation_precision；范围 case 的检索指标按集合计。
  3. N06/N11 属会话跟进题但 `turns=[]`（数据集刻意不发明 turn 结构）：runner 单轮执行即可，但**必须在 `cases.jsonl`/`summary.json` 或报告里显式声明"P0 为单轮执行，N06/N11 不证明多轮能力"**，不得把它们的通过写成多轮验证。
  4. N05 的 `expected_min_total=1` 只在 `notes`，`expected_pagination` 为 `null`：本包**不得**声称 badcase 覆盖分页契约语义。
  5. **（PM 追加，2026-11-05，T004b 验收 MEDIUM-4）** 引用/检索记录在写 `unit_ids` 的同时，**应一并保留 `doc_code` + `unit_key`/`locator`**（能从 chunk 归属直接取到就写）：`security_leak` 的 `forbidden_sources` 用的是 `unit_key`，只有 `unit_ids` 时下游 `source_forbidden` 会漏报（`scorers.py:588-600`）。若某字段确实取不到，写 `null` 并在报告说明，不要猜。
- `replay` 场景的 trace 写入只做 `replayed=True` 标记，不得伪造 span（复用 T003d 已验收的 `annotate(replayed=True)` 口径）。
- 所有 JSON/JSONL 用 UTF-8、`ensure_ascii=False`、`pathlib`；数字口径统一 0–1。

## 8. 提交

分支 `p0/obs-eval`，一个 commit：`p0/T005 runner`；只 add 本包交付物与证据；不 push（amend 后重采最终 HEAD stat）。

## 9. report.md 格式（≤80 行）

五段：1) 完成内容 2) §5 逐条自证（每条 ≤2 行，命令或 `文件:行`）3) 实际运行结果（包/目录/全量各一行 + commit sha + stat + local/replay 指标对照）4) 偏离与未做 5) 风险与遗留。末尾 ≤10 行交接摘要。

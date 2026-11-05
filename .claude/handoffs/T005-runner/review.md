# T005 · Replay / Local Runner — 独立验收 review

- 对象：`80fd092`（`p0/T005 runner`，父 `d1a9d92`；验收期间 PM 追加 docs-only `b68bb0d`，代码树不变）。
- 环境：`p0/obs-eval`；`MKTKB_PROJECT_TOTAL_LIMIT_CNY=20.0`；Python 3.12.7 `-B`；串行复跑。
- 结论：**PASS**。§5.1–§5.6 全 PASS；无 BLOCKER/HIGH；2 个 MEDIUM 边界见 §2，均为 T006a 输入约束，不阻断本包。

## 1. §5 逐条判定

| 条 | 判定 | 复核（命令 / 文件:行） |
| --- | --- | --- |
| 5.1 三件套 + 双模式 | PASS | 探针实跑 b0/badcase × local/replay：b0 40 行（pass 29/fail 3/skipped_ocr 8），badcase 13 行（pass 9/fail 4），replay 40/13 行；空 gold `N10/N12/N13` 在 `cases.jsonl` 且非 error；每行含 `case_id/status/trace_id/checks`；输出目录恰为三件套 + `traces.sqlite3`。`runner.py:225/278/447`；`test_runner.py:130/156/266/288`；evidence 02。 |
| 5.2 版本绑定 | PASS | `run_manifest.json` 十个必需字段齐全；b0 `dataset_sha256=bd4f…`、`corpus_manifest_sha256=6889…`，badcase `e5f0…`/`5f41…` 均与文件实测一致；`business_date=2026-10-28`；`index_revision=6/4`；`pipeline_version=735da1397044`；`gate_version=mktkb.gate.v0.1`；两次 b0 local 的 `IDENTITY_FIELDS` 全同（仅 run_id/created_at 变）；replay 复制身份字段并写 `source_run_id/replay_from`。`test_runner.py:187/203`；evidence 02。 |
| 5.3 零真实调用 | PASS | 独立 guard：Bailian embed/rerank、DeepSeek complete 调用 0；`socket.connect`/`create_connection` 0；`Settings.__init__` 0；`.env` open 0；offline provider 由 `RagIndex` 确定性替身提供（`index.py:76-108`）。B0 D07–D10 在装配期按 kind 跳过（`corpus.py:141-144`）；badcase 只解析 E03/E11/P03/W01（`corpus.py:188-200`）；`run_suite` 拒绝非 offline 配置（`runner.py:306`）。`test_runner.py:226`；evidence 02。 |
| 5.4 replay 确定性 | PASS | 将 `runner.build_suite_index` monkeypatch 为抛错后 b0/badcase replay 仍成功（build 调用 0），out_dir 仅三件套 + trace、无 `rag.sqlite3`；40/40 与 13/13 行 `status/checks/metrics` 与 local 一致；16 个 summary 指标一致；trace 全 `replayed=True`、`mode=replay`、`status=replayed`、无 span；`replay_from=None` 明确 `ValueError`。`runner.py:447-536/1060-1076`；`test_runner.py:266/288/328/341/373`；evidence 02。 |
| 5.5 unit 级口径 | PASS | 独立重建 b0/badcase 索引比对 `RagUnit`：所有 citation/retrieved 的 `unit_ids` 均为真实单 unit，`unit_key`/`doc_code`/`locator` 匹配；b0 48 citations/149 retrieved，badcase 25/60；gold unit_ids 也在真实索引。replay 后 Recall/MRR/nDCG：b0 `0.96875 / 0.8697916666666666 / 0.8954577739955403`（n=32），badcase `0.7679144385026737 / 0.7166666666666667 / 0.6851021519869538`（n=10）；OCR 8 行不进分母；N10/N12/N13 `gold_units=0` 不进检索分母；N05=11、N09=17；N06/N11 单轮声明；`record_code`-only 标 `record_code_only_gold`。`test_runner.py:468/498/514/564/589`；evidence 02。 |
| 5.6 测试与回归 | PASS | `test_runner.py` **20 passed**（9.16s），`backend/tests/evaluation` **124 passed**（11.68s），全量 `backend/tests` **1397 passed, 0 failed/0 error**（397.60s，0:06:37；基线 1377 + 20）；已知 flake 未触发；无新增依赖。`git show --name-status 80fd092` 8 个 A 路径全部在 handoff §2 内（2498 insertions），`conftest.py` diff 0 行；`git status` 仅验收方未跟踪证据。evidence 01/03。 |

报告数字复核：20/124/1397、40 行、replay 40/40、b0 三 fail = Q25/Q26/Q31 全部为真；`MRR` 报告写 0.869792 是 0.869791666… 的四舍五入。直接 `RagIndex.ask` 复核 Q25/Q26/Q31：状态/failing checks 与 run 行一致（Q25 value_hit+source_hit；Q26 value_hit+value_no_fabricated；Q31 no_answer 的 value_hit/source_hit/kind_correct/refusal_unexpected）——三 fail 是离线检索/抽取口径，不是 runner 编排问题。badcase 另有 N05/N06/N09/N11 四 fail，非本包要求。

## 2. 问题分级

- **MEDIUM-1**：`summary.metrics_scope.cases_in_denominator` 在 b0 为 **40**（实际指标分母 32；OCR 8 由 scorer 排除）。字段名容易被 T006a 当作 `min_sample`/分母；gate 必须用 `scored_count`（b0 32、badcase 10）或逐行 `status != skipped_requires_ocr && gold_units > 0`。不是 §5 指标 FAIL（探针重算均值为 32/10 实测一致）。evidence 02 NOTE。
- **MEDIUM-2**：`record_code` 防御按“键是否存在”判断。规范形态 `{"doc_code":"D01","record_code":"P01"}` 正确 `record_code_only_gold`；但 `{"doc_code":"D01","record_code":"P01","locator":{}}` 实测 `pass`、gold 扩为 D01 全部 9 unit。当前 fixtures 不用该形态，§5.5 字面 PASS；T006a 应拒绝 record_code + 空 locator，不能把空 locator 当有效范围。evidence 02 NOTE。
- **LOW-1**：replay 行 `trace_id` 是 replay provenance，`previous_trace_id` 与 `outcome.trace_id` 均指向源 local trace；消费方若用 `outcome.trace_id` 在 replay 的 `traces.sqlite3` 查会找不到。gate 应使用行 `trace_id` + `previous_trace_id`。evidence 02 NOTE。
- **LOW-2**：b0 `summary.declarations.gold.range_gold_case_ids` = `Q33–Q40`（OCR 的 locator-only 引用），不是真正的范围型 gold；badcase 的 N05/N09 才正确。不要把 b0 该字段当范围 gold 输入。
- **LOW-3**：replay 只校验持久化 `gold`/`checks` 的自洽（`_assert_same_score`），不校验其与冻结数据集一致；篡改源 `cases.jsonl` 的 gold/checks 可自洽重放。T006a 硬门禁应重新从 `fixtures/evaluation/*.jsonl` 解析 gold，或标 unknown。
- **INFO**：`cases.jsonl`/`run_manifest.json` 含 `duration_ms`、`trace_id`、`run_id`、`created_at`，字节数/hash 非确定性（b0 local 两次为 203748/203749 bytes）；确定性只应基于 `status/checks/metrics` 与身份字段。报告未把 artifact hash 当跨 run 证明，属可接受。

## 3. 未覆盖 / NOT-RUN

- 未重跑旧 commit 基线全量（按提速策略 A）；1397 是 `80fd092` 代码树上的单次全量。
- 未独立复做 test_runner 的三个变异用例（缺 unit_ids、持久化分数漂移、改数据集）；这些由 124 目录测试覆盖，探针只覆盖正常 replay、replay_from=None 与 record_code-only。
- 未执行 live、真实 OCR/embedding/rerank、真实网络抓包（P0 禁止）；零调用结论来自 provider/socket/Settings guard，不是 pcap。
- 未实现/未运行 T006a gate；未验证单文件 sha256 与 manifest 一致性（非本包要求）。
- 现有 fixtures 的 `forbidden_sources`/`forbidden_values` 全为空（b0/badcase 实测 `[]`）；T005 只证明这些字段可持久化、citation 的 unit_key 可匹配，未证明真实 `security_leak` 命中，需 T006a 合成样本。
- 验收期间 HEAD 由 `80fd092` 外移为 `b68bb0d`（PM 仅 `_index.md` + 两个 prompt，docs-only）；无代码/测试变化。

## 4. 对 T006a 的输入约束

**可依赖**：`run_manifest` 的 `mode/scope/suite/dataset_version/dataset_sha256/corpus_manifest_sha256/business_date/index_revision/pipeline_version/gate_version/label_version/case_count`；replay 的 `source_run_id/replay_from`；`cases.jsonl` 的 `case_id/status/trace_id/checks/metrics/outcome/gold/error/should_refuse/turns_executed/multi_turn_claimed`；citation/retrieved 的 `doc_code/unit_key/unit_ids/locator`（非 OCR 行，unit 级完整）；`summary` 的 `status_counts/scored_count/skipped_ocr_count/error_count/metrics/declarations`（replay 的 `latency/p50/p95` 为 null，不作执行质量）；local 非 OCR trace 的必需 Span（探针按 `required_spans` 全量验证），replay trace 的 `replayed/previous_trace_id`。

**必须 unknown / exit 3，不得默认通过**：
- `cross_entity`、`stale_bypass`、`conflict_not_rejected`：T005 产物没有用户/跨实体、stale/effective date 或 conflict 字段 → unknown。
- `pagination_contract`：`expected_pagination` 全 null、b0/badcase `declarations.pagination.claimed=false`；N05 的 `min_total` 只在 notes → unknown，不得声称覆盖。
- `security_leak`：`forbidden_sources` **不在** `cases.jsonl`；必须从 fixtures 读取并按 citation 的 `unit_key/unit_ids/locator` 做 unit 级解析；无法解析 → unknown。
- `citation_required`：可用非 OCR 行的 unit 级 citations；不得仅凭 `source_hit`；OCR/error 行 → unknown/排除，`should_refuse`/no-answer 行按期望 kind 处理而不是强求引用。
- `exact_value_contract`：可用 `value_hit` 诊断，但 `value_no_fabricated` **不得作硬门禁**（Q26 即因它 fail）。
- `trace_integrity`：local 非 OCR 行 Span 完整；本包实测的 OCR skip 与 `record_code` 前置 error 的 trace 是 `incomplete` 且无 Span，不能按执行失败处理（任何 `cases.jsonl` error 行都应 unknown/排除）；replay 行必须跳过 path/outcome/Span 校验，只校验版本绑定/JSON；`record.reason` 可用于 `required_spans(..., reason=...)`。
- `min_sample`：用 `scored_count` 32/10 或逐行过滤，不要用 `case_count` 40/13，也不要用 `metrics_scope.cases_in_denominator` 40/13。
- `refusal` 指标：b0 `refusal_recall=null`，treated as unknown；T006a 若重算 2×2，排除 `error`/OCR，避免把 error 计 TN。
- `record_code`-only 与空 locator：gate 必须拒绝/unknown；不得把整篇 unit 集合当命中。
- `cases.jsonl` 的 `gold/checks` 在 replay 中来自源 run 自报，非数据集真值；硬门禁应重新解析 fixtures 或标 unknown。
- replay 的 `outcome.trace_id` 不是 replay trace；使用行 `trace_id`/`previous_trace_id`。`cases.jsonl`/manifest 字节/hash 不可作确定性证据。

## 5. 证据

- `docs/reports/OBS-EVAL/P0/evidence/verify/T005/01-tests.txt`（20/124）
- `docs/reports/OBS-EVAL/P0/evidence/verify/T005/02-independent-probe.txt`（probe，failures=0）
- `docs/reports/OBS-EVAL/P0/evidence/verify/T005/03-full-regression.txt`（1397 + commit 边界）
- `docs/reports/OBS-EVAL/P0/evidence/verify/T005/probe.py`（唯一探针；只读仓库，产物在 `%TEMP%`）

## 6. 边界自查

- 只新增本 review 与 `evidence/verify/T005/`；未改交付代码/测试/conftest/其他包 review/证据/`docs/evidence/**`/`var/**`/`fixtures/**`；未 commit、未 push、未改 `_index.md`。
- `git status --short` 结束时仅 `?? .claude/handoffs/T005-runner/review.md` 与 `?? docs/reports/OBS-EVAL/P0/evidence/verify/T005/`（PM `b68bb0d` 的 docs-only 变化非验收方）。
- 串行执行；临时 run 仅在 `%TEMP%`；未读 `.env`、未打印凭据。

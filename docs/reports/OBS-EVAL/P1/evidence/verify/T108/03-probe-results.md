# T108 验收探针结果（合成 + 真实受限运行）

> 本文件只记录聚合/结构事实；真实 holdout 的题干、答案、case_id 均未写入。真实 details 产物在扫描后已删除。

## A. 合成默认聚合（`02-probe.py`）

夹具：3 条合成 case（2 paraphrase + 1 negative），E11 一份语料；policy 只对合成夹具放宽 sha/题量/分层。
命令（cwd=仓库根）：

```text
$env:PYTHONPATH="backend/src"; .venv\Scripts\python.exe -B backend\.pytest-tmp\T108-verify\probe.py
```

结果（逐行摘录）：

```text
A files: ['run_manifest.json', 'summary.json']
A leak: {"cases_jsonl": false, "trace_db": false, "question_marker": false,
         "answer_marker": false, "answer_text_hits": 0, "case_id_hits": 0}
A manifest.holdout_details: False
A summary.holdout.aggregate_only: True
B gate cli exit: 3 hard: [] unknowns: ['holdout_aggregate_only']
B stdout has hard_failures=[]: True traceback: False
```

判定：默认聚合产物只有 manifest/summary；无 `cases.jsonl`、无 `traces.sqlite3`、无题干/答案/case_id；
`gate --run` 对聚合 run 不抛异常、hard `[]`、不泄漏逐题。

## B. 真实 holdout 默认聚合（受限运行）

命令（labels 只作为 CLI 参数；未读取/打印内容；输出在 `%TEMP%`）：

```text
.venv\Scripts\python.exe -B -m mktkb.evaluation.cli run --suite holdout --mode local ^
  --holdout-labels docs\evidence\LOCAL-R1-20261101\P1-HOLDOUT\labels.jsonl --out %TEMP%\T108-verify\real-agg-<ts>
```

结果：

```text
exit=0
run_id=holdout-local-20261108T125346647750Z-0b1b45bf suite=holdout mode=local cases=30 details=false
files=['run_manifest.json','summary.json']  cases_jsonl=False  trace_db=False
status_counts={'error':3,'fail':20,'pass':7}; scored_count=27; case_count=30
holdout: aggregate_only=true details_written=false traces_persisted=false
         metadata_mismatch_count=0
         strata={paraphrase:10, multi_turn:5, negative:5, stale_conflict:5, cross_doc_security:5}
```

泄漏扫描（把本 run 全部产物拼成文本，对真实 questions/labels 逐条做子串检查，只输出计数）：
`question_hits=0`、`turn_hits=0`、`case_id_hits=0`、`reference_answer_hits=0`；
`expected_value_hits=2`，两条均为 2 位数字，且只出现在 `corpus_manifest_sha256`/`dataset_sha256`/
`holdout_labels_sha256` 等 64 位 sha 字段内部（非独立 JSON 值，无法据此定位 case）。
递归 key 扫描：`summary` 不含 `question/reference_answer/expected_values/expected_sources/relevant_units/case_id`。
`gate --run`：exit 3、`hard_failures=[]`、唯一 unknown `holdout_aggregate_only`；`gate.json` 对同一批真实
questions/labels 的题干/答案/case_id 命中均为 0。之后删除该 TEMP run。

**F1（阻塞）**：同一真实 run 的 3 个 error 全是 `gold_unit_ids_missing`；另用 details run 逐条关联
（不打印 case_id/题干/答案）确认：

```text
error_cases=3
error_cases_with_expected_sources=[] & relevant_units nonempty & should_refuse=true = 3/3
error message variant = "unit_ids 为空" = 3/3（不是 "relevant_unit_ids 为空"）
```

根因：`runner.py:1343-1358` 在任意 ref 存在时要求 `gold.unit_ids`（来自 `expected_sources`），而
`gold.py:230-241` 对 `expected_sources=[]` 的 case 返回 `unit_ids=()`。这与设计 §4 “负样例允许
`expected_sources` 为空、可用 `relevant_units`”冲突；3 个合法拒答题因此不可评分（分母 27/30）。

## C. details + audit（合成 + 真实）

合成（`02-probe.py` C）：

```text
C files: ['cases.jsonl','holdout_audit.json','run_manifest.json','summary.json','traces.sqlite3']
C audit fields: audit_schema_version, created_at, data, mode, note, operator, parameters, run_id, scope, suite
C audit sha/version: <qsha8> <lsha8> holdout-synthetic-verify operator=verify-op
C audit leak: {'question': False, 'answer': False, 'ref_answer': False}
C cases rows: 3
```

真实 details（`--allow-holdout-details`，输出 `%TEMP%`，扫描后删除）：

```text
exit=0; run_id=holdout-local-20261108T125531688017Z-91010840; rows=30
audit: operator/created_at 非空, run_id 与 manifest 一致,
       parameters={allow_holdout_details, config_hash, corpus_dir, out_dir},
       data={case_count, label_version, labels_path, labels_sha256, metadata_mismatch_count,
             questions_path, questions_sha256, strata}
       questions_sha256=a8c8aa7f…6738; labels_sha256=8f713a2a…c1bf; label_version=holdout-2026-11-04
audit 对真实 questions/labels 的 question/turn/reference_answer 命中 0；expected_value 仅 2 条 2 位数字
命中，且位于 qsha/lsha/run_id 内部（非独立值）。
gate details: dev exit 3 hard [] → holdout_details_not_gated;
              CI(GITHUB_ACTIONS=1) exit 3 hard [] → holdout_details_forbidden_in_ci，reason 点名变量。
```

## D. CI / gate

合成矩阵（`02-probe.py` E）：

```text
CI CI: rejected=True names_var=True out_exists=False
CI GITHUB_ACTIONS: rejected=True names_var=True out_exists=False
CI MKTKB_CI: rejected=True names_var=True out_exists=False
CI aggregate exit ok: True
```

CLI 单变量 + 组合（未提供 labels，CI 检查先于加载）：

```text
CI / GITHUB_ACTIONS / MKTKB_CI 单项与三项组合 + --allow-holdout-details
→ exit=3，stderr 含 “CI/门禁环境禁止”，无 Traceback，out 目录不存在
```

## E. fail-closed 矩阵（合成夹具；`02-probe.py` F/G）

```text
missing_labels: rejected=True (HoldoutError)          # 另：CLI exit 3，无 out
empty_label_version: rejected=True (HoldoutError)
wrong_label_version: rejected=True (HoldoutError)
row_count: rejected=True (HoldoutError)
strata: rejected=True (HoldoutError)
case_id_set: rejected=True (HoldoutError)
questions_sha: rejected=True (HoldoutError)
labels_sha: rejected=True (HoldoutError)
answer_field: rejected=True (HoldoutError)
CLI missing labels exit: 3 stderr_has_msg=True traceback=False out_exists=False
```

补充：删掉 questions 的 `label_version` 键 → `HoldoutError`（13 键白名单，`dataset.py:712-714`）；
labels 带错 `label_version` → `HoldoutError`（不一致）。CLI 对篡改 `--dataset`（默认 sha 策略）也 exit 3、
不写 out（错误为 `questions sha256 不符`）。

## F. 交付物防污染扫描

对 `.claude/handoffs/T108-holdout-support/report.md` + 交付的 4 份 T108 证据扫描真实 questions/labels：

```text
question=0, case_id=0, reference_answer=0, turn=0（所有文件）
expected_value 命中仅 1–2 字符数字子串（报告/证据里的行数、分层计数、sha/版本号内部），无完整答案文本。
```

## G. 仓库导出 / labels 未入库

```text
fixture bytes == PM scratch copy == docs/evidence/.../questions.jsonl
sha256=a8c8aa7f028ce14047173e3e57db36dda72d3a13b3578ad82ec8cd1b86cd6738
lines=30; keys=13; answer_fields=[]
real labels sha256=8f713a2a22fe605cad53cec7c2679c0e5606421d2ac6baa34d17521650f4c1bf（仅算 sha，未读入证据）
fixtures/evaluation 下无 labels 文件；git ls-files / git log --all --name-only 无 labels.jsonl
```

## H. 残余 R1：复用 out 目录（额外对抗探针）

```text
details run → out 目录: ['cases.jsonl','holdout_audit.json','run_manifest.json','summary.json','traces.sqlite3']
default run → 同一 out: 文件集不变；summary.holdout.aggregate_only=True, details_written=False
```

即默认 run 本身不写逐题，但不会清理旧 details 三件套；新目录场景（验收项 1）通过。建议后续加固。

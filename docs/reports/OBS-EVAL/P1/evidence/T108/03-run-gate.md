# T108 证据 03：合成 holdout run / gate / audit / CI

## A. 探针（只合成夹具：E11 一份语料 + 3 条合成 case）

命令（cwd=仓库根，`$env:PYTHONPATH="backend/src"`）：

```text
.venv\Scripts\python.exe -B backend\.pytest-tmp\T108\probe_holdout.py
```

探针文件是临时脚本（`backend/.pytest-tmp/T108/`，不入库），内容与
`backend/tests/evaluation/test_holdout_suite.py` 的合成夹具等价；题干/答案里埋了唯一标记
（`合成题干-丙-唯一标记` / `店内外侧`）用于证明产物不含逐题内容。输出（逐行摘录）：

```text
== A. 默认聚合 run ==
artifacts: ['run_manifest.json', 'summary.json']
cases.jsonl exists: False
question_marker_in_artifacts: False
answer_marker_in_artifacts: False
case_id_in_artifacts: False
summary.holdout: {"aggregate_only": true, "details_written": false, "audit_file": null,
  "label_version": "holdout-synthetic-2026-11-08",
  "questions_sha256": "a34914fe371b…", "labels_sha256": "dbb16363c306…",
  "metadata_mismatch_count": 0, "strata": {"negative": 1, "paraphrase": 2},
  "traces_persisted": false, "note": "holdout 默认只出聚合…"}
summary.case_count: 3 status_counts: {'fail': 1, 'pass': 2}

== B. gate 对聚合 run ==
gate exit: 3 hard: [] unknown: [('holdout', 'holdout_aggregate_only')]
gate exit_code=3 run_id=holdout-local-20261108T122534956005Z-a2a1a208 suite=holdout mode=local
  scored=0/None hard_failures=[] quality=not_evaluated config_status=not_evaluated
gate cli exit: 3

== C. details run + audit ==
artifacts: ['cases.jsonl', 'holdout_audit.json', 'run_manifest.json', 'summary.json', 'traces.sqlite3']
audit keys: ['audit_schema_version', 'created_at', 'data', 'mode', 'note', 'operator',
  'parameters', 'run_id', 'scope', 'suite']
audit operator/time/shas/version: t108-probe True a34914fe371b dbb16363c306 holdout-synthetic-2026-11-08
audit contains question/answer: False False
gate on details (CI): 3 holdout_details_forbidden_in_ci

== D. CI 带 details flag ==
CI rejected: CI/门禁环境禁止 --allow-holdout-details（命中环境变量 CI）…
GITHUB_ACTIONS rejected: …（命中环境变量 GITHUB_ACTIONS）…
MKTKB_CI rejected: …（命中环境变量 MKTKB_CI）…
```

结论：

- 聚合 run 只有 `run_manifest.json` + `summary.json`；题干标记、答案标记、case_id **均不在**产物里；
  `summary.declarations` 的逐 case 列表已替换为计数（`excluded_error_count` 等）。
- 聚合 run 的 trace 落在临时目录并随运行删除（`traces_persisted=false`，目录内无 `traces.sqlite3`）。
- details run 才出现 `cases.jsonl`（内含答案）与 `holdout_audit.json`；审计只有操作人/时间/参数/
  run_id/两个 sha/label_version/分层层数与 mismatch 计数，**不含**题干或答案。
- `gate --run` 对聚合 run 不抛异常：exit 3、`hard_failures=[]`、唯一 unknown 是
  `holdout_aggregate_only`；对 details run 在 CI 记 `holdout_details_forbidden_in_ci`。
- 三个 CI 变量各自单独设置都能硬失败（非零、不执行 case、不写 `cases.jsonl`）。

## B. 真实仓库导出 + 缺 labels 的 fail-closed（不读内容）

命令（未设置 `MKTKB_HOLDOUT_LABELS`，未读 `docs/evidence/**/P1-HOLDOUT/`）：

```text
.venv\Scripts\python.exe -B -m mktkb.evaluation.cli run --suite holdout --mode local ^
  --out backend\.pytest-tmp\T108\eval\holdout-nolabels
```

```text
exit=3
out_dir_exists=False
stderr: ERROR: HoldoutError: holdout 缺少 labels：请用 --holdout-labels <path> 或
        MKTKB_HOLDOUT_LABELS 指向本地 labels.jsonl（labels 永不入库）
```

即：题目导出能通过 30 行 / 分层 / sha / 无答案字段校验，但没有 labels 时**不会**建索引、不会写任何产物。
真实 holdout 运行由验收方在提供 labels 路径的受限环境执行（本包未运行、未读题面/答案）。

## C. gate 对 P0 产物（回归影响面）

```text
var\eval\runs\p0-b0      gate exit 3 hard []
var\eval\runs\p0-badcase gate exit 3 hard []
```

holdout 分支只在 `run_manifest.suite=holdout` 时触发；b0/badcase/regression 的 gate 路径未变
（见 04 的逐例对照）。

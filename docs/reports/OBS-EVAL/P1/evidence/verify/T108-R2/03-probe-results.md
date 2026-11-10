# T108 R2 探针原始结果（只含计数/结构/状态）

> 真实 labels 只作为 `--holdout-labels` 运行时输入；本文件不含题干、答案、`case_id` 原文。
> 真实 run 产物在 `%TEMP%\T108-R2\real-*`，扫描后删除。探针源码 `02-probe.py`。

## A. F1-a 真实 holdout 默认聚合 run（`run --suite holdout --mode local`）

```text
exit=0  elapsed≈63.1s
files=['run_manifest.json','summary.json']  cases_jsonl=False  traces_db=False
case_count=30  holdout_details=False
status_counts={'fail': 23, 'pass': 7}   error_count=0   scored_count=30
metrics_scope.cases_in_denominator=30   excluded_error_count=0
refusal_recall=0.5  refusal_precision=0.5  false_refusal_rate=0.125  Recall@10=0.5154320987654321
holdout={aggregate_only:true, details_written:false, traces_persisted:false,
         metadata_mismatch_count:0, label_version:holdout-2026-11-04,
         strata={paraphrase:10, multi_turn:5, negative:5, stale_conflict:5, cross_doc_security:5},
         questions_sha256=a8c8aa7f…6738, labels_sha256=8f713a2a…c1bf}
leak={question_hits:0, turn_hits:0, case_id_hits:0, reference_answer_hits:0,
      expected_value_hits_len_ge4:0, expected_value_hits_total:4}
```

`gate --run`（聚合目录）：

```text
exit=3  hard=[]  unknowns=['holdout_aggregate_only']  traceback=False
gate_leak={question:0, turn:0, case_id:0, reference_answer:0,
           expected_value_hits_len_ge4:0, expected_value_hits_total:0}
```

## B. F1-b 真实 holdout details run（`--allow-holdout-details`）

```text
exit=0  elapsed≈63.7s  rows=30  case_count=30
files=['cases.jsonl','holdout_audit.json','run_manifest.json','summary.json','traces.sqlite3']
status_counts={'fail': 23, 'pass': 7}  error_count=0  denominator=30
former_refusal_shape:
  count=3  status_counts={'fail': 3}  error_none=3  refusal_check_not_skipped=3
  gold_unit_ids_empty=3  relevant_nonempty=3
all_rows_unit_ids_empty_relevant_nonempty=3
refusal_confusion={should_refuse:6, refused:6, tp:3, fp:3, fn:3, tn:21}
refusal_metrics_match={refusal_recall:true, refusal_precision:true, false_refusal_rate:true}
audit_forbidden_keys=[]
audit_meta={operator_nonempty:true, operator_is_not_unknown:true,
            run_id_matches:true, created_matches:true,
            questions_sha256_head:a8c8aa7f, labels_sha256_head:8f713a2a,
            label_version:holdout-2026-11-04}
audit_leak={question:0, turn:0, case_id:0, reference_answer:0,
            expected_value_hits_len_ge4:0, expected_value_hits_total:2}
manifest_summary_leak={question:0, turn:0, case_id:0, reference_answer:0,
                       expected_value_hits_len_ge4:0, expected_value_hits_total:4}
```

`audit_keys`（27 个，只列键名）：`allow_holdout_details, audit_schema_version, case_count,
config_hash, corpus_dir, created_at, cross_doc_security, data, label_version, labels_path,
labels_sha256, metadata_mismatch_count, mode, multi_turn, negative, note, operator, out_dir,
parameters, paraphrase, questions_path, questions_sha256, run_id, scope, stale_conflict,
strata, suite`。

`gate --run`（details 目录）：

```text
dev: exit=3  hard=[]  unknown=['holdout_details_not_gated']  traceback=False
CI(GITHUB_ACTIONS=1): exit=3  hard=[]  unknown=['holdout_details_forbidden_in_ci']
                      reason 点名 GITHUB_ACTIONS=True  traceback=False
```

## C. B2 out 目录防污染（合成夹具；快照=文件 sha256）

```text
空目录可跑: files=['run_manifest.json','summary.json'] denominator=3
            status_counts={'fail':3} holdout.aggregate_only=True
            默认聚合 leak 全 0（question/answer/case_id/expected_value）
stale cases.jsonl + 默认 run:      exit=3  msg=拒绝复用  traceback=False  unchanged=True  文件仍仅 cases.jsonl
stale holdout_audit.json + details: exit=3  msg=拒绝复用  traceback=False  unchanged=True  文件仍仅 holdout_audit.json
stale holdout_audit.json + runner:  HoldoutError=True  unchanged=True
stale traces.sqlite3 + 默认 run:    exit=3  msg=拒绝复用  unchanged=True  文件仍仅 traces.sqlite3
stale keep.txt + 默认 run:          exit=3  msg=非空 out 目录  unchanged=True  文件仍仅 keep.txt
```

- 所有拒绝场景均无新产物（无 manifest/summary/audit/cases/trace），旧文件逐字节（sha256）不变。
- 已存在的空目录可正常跑，产物严格两件。

## D. B3 holdout 拒绝 `--from-run`

```text
runner:  ValueError 含 replay_from=True   out_created=False
CLI:     exit=3  stderr 含 replay_from=True  traceback=False  out_created=False
mode=replay + --from-run: exit=3  “只允许 mode='local'”=True  out_created=False
```

## E. 不变项抽查

CI 三变量 + `--allow-holdout-details`（无 labels，CI 检查先于加载）：

```text
CI:              exit=3  msg=True  names_var=True  traceback=False  out_created=False
GITHUB_ACTIONS:  exit=3  msg=True  names_var=True  traceback=False  out_created=False
MKTKB_CI:        exit=3  msg=True  names_var=True  traceback=False  out_created=False
CI 下聚合 run:   details=False  files=['run_manifest.json','summary.json']
```

fail-closed 抽查：

```text
missing labels CLI:        exit=3  msg=True  out_created=False
pinned sha 不符（--dataset 篡改）: exit=3  msg_sha=True  out_created=False
loader 行数 3≠30:          HoldoutError=True
loader 删 label_version:   HoldoutError=True
```

合成拒答负样例（`expected_sources=[]` + `relevant_units` 非空 + `should_refuse`）：

```text
status=fail  error=None  error_count=0  denominator=3
gold.unit_ids=[]  relevant_nonempty=True  refusal_recall=0.0
```

## F. 仓库导出 / labels 未入库

```text
fixture: lines=30  keys=13  answer_fields=[]
         sha256=a8c8aa7f028ce14047173e3e57db36dda72d3a13b3578ad82ec8cd1b86cd6738
labels:  rows=30  keys=11  sha256=8f713a2a22fe605cad53cec7c2679c0e5606421d2ac6baa34d17521650f4c1bf
         （与 dataset.HOLDOUT_LABELS_SHA256 相等；只算 sha）
git ls-files 中 labels.jsonl=[]；git log --all --name-only 中 labels.jsonl=[]
fixtures/evaluation 下 *labels* 文件=[]
```

## G. 环境

```text
Windows；Python 3.12.7（.venv）；pytest 9.1.1；PYTHONPATH=backend/src；
MKTKB_PROJECT_TOTAL_LIMIT_CNY=20.0（仅 b0/badcase/regression）；
临时目录只用了 %TEMP%\T108-R2\ 与 backend\.pytest-tmp\T108-R2\。
```

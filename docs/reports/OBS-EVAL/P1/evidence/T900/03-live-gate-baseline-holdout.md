# T900 证据 03：真实 run / 账本 / gate / baseline / Holdout

模型：`wb / cn:deepseek-v4.1-flash / reasoning_effort=max`

## A. 真实 run（只读复核，未重跑）

| run | 事实 |
| --- | --- |
| T111 pilot `b0-live-20261108T194053896474Z-b224f9fb` | 10 cases、`status={pass:10}`、error 0；R/MRR/nDCG=1.0；`provider_requests` embedding 17 / rerank 10 / chat 0；retries 0；index 6 docs/42 units/27 chunks；stage +0.0026345 |
| T112 b0 `b0-live-20261109T111828086143Z-0efd058b` | 40 cases、32 scored / 8 OCR skipped、error 0；R/MRR/nDCG=0.96875；hard_filter 0.0；empty_recall 0.03125；`provider_requests` 39/31/chat 0；retries 0；index 6/42/27 |

T112 summary `live.budget_after`：`reservation_count=505`、`result_count=505`、
`accounted_cny=15.0709445`、`stage_accounted_cny=0.0143149`、`stage_remaining_cny=2.9856851`、
`provider_billed_cny=null`。2026-11-09 23:0x 用 `BudgetLedger.summary()` 只读复算与之一致。
**注意**：T900 handoff §5.4 写 `0.0142293/3.0`，与实际账本/run summary `0.0143149`
差 0.0000857；本报告采用账本事实值。

## B. gate v0.2 / baseline

- `docs/evaluation/gate_v0_2.json`：`status=approved`、`gate_version=mktkb.gate.v0.2`；
  `min_sample=8`；R/MRR/nDCG `absolute_min=0.855`；hard_filter `absolute_max=0.02`；
  empty_recall `absolute_max=0.145`；`max_regression_pp=2.0`；answer/refusal/runtime
  10 指标仍 null。顶层 approval 与 baseline approval 的 reason 逐字相同。
- 用 approved 配置对 T112 run 现场 `evaluate_gate(..., quality=True)`：
  `exit=0 / hard=[] / quality=pass / config_status=approved`。
- 用 R0 逐字节 unapproved 配置（`git show 7f46121:docs/evaluation/gate_v0_2.json`）：
  `exit=3 / quality=unknown / thresholds_unapproved`。未审批 ≠ 通过。
- `baseline_id=bc6f6f906db1`：`baseline.json.identity` 六要素 =
  `b0:b0-2026-11-04:bd4f0f7ccc6e` / `08166b113481` / `live` / `retrieval_only` /
  `mktkb.gate.v0.2` / `68899152…`；`artifact_sha256` 与 run 三件逐字节相等。
- `approval.json`：`approver` codepoints `0x4e3b 0x4eba`（主人）、`gate_exit_code=0`、
  `quality_status=pass`、`gate_result_sha256=c9fcbbb…`。把 run `gate.json` 按
  `GateResult.to_dict()` canonical JSON 重算，sha256 逐位等于 `c9fcbbb…`（绑定有效）。
- `baseline list` -> `approved=yes`；`var/eval/baselines` 仅此一条，P0 baseline 不存在
  （未创建/未 copy/未污染）；`gate_v0_1.json` 仍 `unapproved`。
- 跨版本：`report.py:492-493` 跨版本固定 `release_allowed=False`、
  `release_blocked_reason=explicit_cross_version_analysis_only`；本次未建立 P0 baseline，
  跨版本比较为 NOT-RUN（代码路径已核对）。

## C. Holdout 30

- 仓库导出 `fixtures/evaluation/holdout-questions.jsonl`：sha256
  `a8c8aa7f028ce14047173e3e57db36dda72d3a13b3578ad82ec8cd1b86cd6738`、30 行、13 键、
  `label_version=holdout-2026-11-04`、分层 10/5/5/5/5、无答案字段；6 题 `should_refuse`、
  0 题 `requires_ocr`、5 题多轮。
- 本地 labels sha256（只哈希，不读题）
  `8f713a2a22fe605cad53cec7c2679c0e5606421d2ac6baa34d17521650f4c1bf`；`git ls-files`
  与 `git log --all --name-only` 均无 labels.jsonl。
- **独立 local 聚合复跑**（零真实调用，输出 `backend/.pytest-tmp/t900-holdout-20261109225600`）：
  30 cases、`status={pass:7,fail:23}`、`error_count=0`、`scored_count=30`、
  `cases_in_denominator=30`；产物仅 `run_manifest.json` + `summary.json`，无 cases.jsonl；
  `holdout.aggregate_only=true`、`details_written=false`、`traces_persisted=false`、
  `metadata_mismatch_count=0`、分层 10/5/5/5/5、两个 sha 与冻结值一致。
  refusal：`recall=0.5 / precision=0.5 / false_refusal=0.125`（6 个应拒答：TP3/FN3；
  24 个非拒答：FP3/TN21），与 T108-R2 证据一致。
- 防污染独立负例：`CI=1` + `--allow-holdout-details` -> exit 3、out 不创建；
  `--from-run` -> exit 3、out 不创建。
- 残余质量事实：holdout 7 pass / 23 fail；T108-R2 已披露 3 个拒答题由 error 变 fail；
  本次只登记，不作为 P1 门禁（holdout 不参与 gate）。

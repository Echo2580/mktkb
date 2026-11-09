# T112 证据 02：gate v0.2 判定 + 校准提案（只建议，不审批）

模型：`wb / cn:deepseek-v4.1-flash / reasoning_effort=max`

## A. 门槛判定（未审批 → exit 3，不得当通过）

```text
$env:MKTKB_PROJECT_TOTAL_LIMIT_CNY="20.0"
.\.venv\Scripts\python.exe -B -m mktkb.evaluation.cli gate ^
  --run var\eval\runs\b0-live-20261109T111828086143Z-0efd058b ^
  --config docs\evaluation\gate_v0_2.json --calibrate
gate exit_code=3 run_id=b0-live-20261109T111828086143Z-0efd058b suite=b0 mode=live
  scored=32/32 hard_failures=[] quality=unknown config_status=unapproved
wrote .../gate.json
proposal=.../gate_proposal.json status=unapproved（T009 人工门审批前不生效，未改写 gate 配置）
```

- 8 项硬门禁：`trace_integrity=pass`；其余 7 项 `not_applicable`（b0 无 forbidden/entity/
  stale/pagination case；live retrieval_only 不生成答案 → conflict/exact/pagination/citation
  显式不适用，**不伪造 pass**）。
- 质量层：仅 retrieval 5 指标参与（retrieval_only 过滤），15 条
  `thresholds_unapproved` unknown；无质量失败。

## B. 校准提案（可复现）

命令同上。连续两次 `gate --calibrate` 的 `gate_proposal.json` 逐字节一致：

```text
sha256(gate_proposal.json) = 0E7D641F2C12EDFF2C5EB5E342B4FA4D7324D14FA67BF8A45BEC4BAE441EC9BD
gate_config_hash = 5362de3c3a8f258adfaa779e6b237bd1fb22d03d4eb74c36c93bd9808a6af482
status=unapproved  run_id=b0-live-20261109T111828086143Z-0efd058b
suite=b0 mode=live pipeline_version=08166b113481 dataset_version=b0:b0-2026-11-04:bd4f0f7ccc6e
strata=all,exact,text（每层 denominator_basis=gold_cases_non_ocr）
```

| metric | stratum | observed | denom | 建议 min_sample | 建议 absolute_min | 建议 absolute_max | max_regression_pp |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Recall@10 | all / exact / text | 0.96875 / 1.0 / 0.875 | 32 / 24 / 8 | 32 / 24 / 8 | 0.9487 / 0.98 / 0.855 | — | 2.0 |
| MRR@10 | all / exact / text | 0.96875 / 1.0 / 0.875 | 32 / 24 / 8 | 32 / 24 / 8 | 0.9487 / 0.98 / 0.855 | — | 2.0 |
| nDCG@10 | all / exact / text | 0.96875 / 1.0 / 0.875 | 32 / 24 / 8 | 32 / 24 / 8 | 0.9487 / 0.98 / 0.855 | — | 2.0 |
| hard_filter_violation_rate | all / exact / text | 0.0 / 0.0 / 0.0 | 32 / 24 / 8 | 32 / 24 / 8 | — | 0.02 / 0.02 / 0.02 | 2.0 |
| empty_recall_rate | all / exact / text | 0.03125 / 0.0 / 0.125 | 32 / 24 / 8 | 32 / 24 / 8 | — | 0.0513 / 0.02 / 0.145 | 2.0 |

规则：0–1 比率类按实测值留 2pp 审批余量；回退容忍 2pp（仅同 pipeline_version 生效）；
`status` 恒为 `unapproved`；未写回 `gate_v0_2.json`（`write_gate_proposal` 对 v0.1/v0.2
配置路径均拒绝覆盖，`gate.py:3181`）。

## C. 待主人裁决的单值口径（config 每个 metric 只有一个阈值）

提案按 stratum 给值，但 `gate_v0_2.json` 的 metric 只有一组 `min_sample` /
`absolute_min` / `absolute_max`。若要让 b0 三层都通过，建议取跨层最宽松值：

```text
min_sample=8（text 层 8；all=32 / exact=24 也满足）
Recall@10 / MRR@10 / nDCG@10: absolute_min=0.855（text 实测 0.875 留 2pp）
hard_filter_violation_rate: absolute_max=0.02
empty_recall_rate: absolute_max=0.145（text 实测 0.125 留 2pp）
max_regression_pp=2.0（首次 baseline 无 baseline → skipped，仅绝对阈值生效）
```

自洽性检查（**仅 scratch 临时副本，未写仓库配置、未审批、未 approve baseline**）：
以上值 + `status=approved` 对同一 run 现场重算 → `exit_code=0`、`quality=pass`、
`hard_failures=[]`。R1 正式落盘前仍必须取得主人书面批准；R0 不自行审批。

替代方案（需主人选择）：若坚持 `min_sample=32` / `absolute_min=0.9487`，exact/text
层会因样本或阈值 unknown/fail（exit 3/2），本 run 不能作为 release baseline。

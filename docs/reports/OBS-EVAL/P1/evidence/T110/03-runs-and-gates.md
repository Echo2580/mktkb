# T110 证据 03：实跑、before/after 指标与门禁对照

模型：`wb / cn:deepseek-v4.1-flash / reasoning_effort=max`

命令口径（cwd=仓库根，`PYTHONPATH=backend/src`，`MKTKB_PROJECT_TOTAL_LIMIT_CNY=20.0`）：

```text
python -B -m mktkb.evaluation.cli run  --suite <b0|badcase|regression> --mode local --out backend\.pytest-tmp\T110\eval\<suite>
python -B -m mktkb.evaluation.cli gate --run backend\.pytest-tmp\T110\eval\<suite>
```

## A. 本轮 run / gate

| suite | run_id | 状态 | gate |
| --- | --- | --- | --- |
| b0 | `b0-local-20261108T175741553925Z-456523ef` | pass 29 / fail 3 / skipped 8 | exit 3，hard `[]`，unknown 42 |
| badcase | `badcase-local-20261108T175744336549Z-27f3dea7` | pass 9 / fail 4 | exit 3，hard `[]`，unknown 94 |
| regression | `regression-local-20261108T175805594608Z-752cfc93` | pass 5 / fail 2 | exit 3，hard `[]`，unknown 80 |

gate exit 3 均为既有 `min_sample_missing` + `thresholds_unapproved`（阈值审批属 T112），
**无新增 hard**；unknown 集合数量与 P0/父提交一致。

## B. before / after（summary.metrics，字段名未变）

| suite | 指标 | before（P0 冻结 run / T109 后 regression） | after（本轮） |
| --- | --- | --- | --- |
| b0 | Recall@10 | 0.96875 | 0.96875 |
| b0 | MRR@10 | 0.8697916667 | **0.96875** |
| b0 | nDCG@10 | 0.8954577740 | **0.96875** |
| b0 | hard_filter_violation_rate | 0.0 | 0.0 |
| b0 | empty_recall_rate | 0.03125 | 0.03125 |
| badcase | Recall@10 | 0.7679144385 | **0.7855614973** |
| badcase | MRR@10 | 0.7166666667 | **0.85** |
| badcase | nDCG@10 | 0.6851021520 | **0.7499953095** |
| badcase | hard_filter_violation_rate | 0.0 | 0.0 |
| badcase | empty_recall_rate | 0.1 | 0.1 |
| regression | Recall@10 | 1.0 | 1.0 |
| regression | MRR@10 | 0.2666666667 | **0.75** |
| regression | nDCG@10 | 0.4434264036 | **0.8154648768** |

解释：旧实现把同一 chunk 的 unit 按出现顺序编造名次，相关 unit 若不是 chunk 内第一条
（或 top-10 单位置被 chunk 内噪声 unit 挤占），MRR/nDCG 被系统性低估；N09 则相反——
旧名次展开把整篇 17 个 gold unit 拆成相邻名次、nDCG=1.0，掩盖了实际 recall 只有 10/17。
新口径下 nDCG 全部 ≤1。

## C. 逐 case 指标变化（签名不变，仅数值）

| suite | case | before（Recall, MRR, nDCG） | after |
| --- | --- | --- | --- |
| b0 | Q25 | (1.0, 0.3333333333, 0.5) | (1.0, 1.0, 1.0) |
| b0 | Q26/Q27/Q29/Q30/Q32 | (1.0, 0.5, 0.6309297536) | (1.0, 1.0, 1.0) |
| badcase | N03/N07 | (1.0, 0.3333333333, 0.5) | (1.0, 1.0, 1.0) |
| badcase | N09 | (0.5882352941, 1.0, 1.0) | (0.7647058824, 1.0, 0.6489315753) |

其余 34/40、10/13、5/7 个 case 指标不变（每 case 只有 1 个相关 unit 且位于 chunk 首位）。

## D. 对 P0 冻结基线的逐例签名对照（`case_diffs`）

签名 = `(status, outcome.kind, [(check_id,status)...], error.code)`；**不比较** metrics /
trace_id / duration 等易变字段。脚本临时存放在 `backend/.pytest-tmp/`，不入库。

```text
b0        rows 40/40  signature diffs = 0   status_counts {'pass':29,'fail':3,'skipped_requires_ocr':8}
badcase   rows 13/13  signature diffs = 0   status_counts {'pass':9,'fail':4}
```

- b0 对 `var/eval/runs/p0-b0`：`case_diffs=0/40`，gate hard `[]`。
- badcase 对 `var/eval/runs/p0-badcase`：`case_diffs=0/13`，gate hard `[]`。

## E. regression：T109 后状态不变

对比基线 `backend/.pytest-tmp/T109-R2/eval/regression-current`
（run `regression-local-20261108T171829346713Z-9647507a`，T109 R2 验收 run）：

```text
rows 7/7  signature diffs = 0
status_counts 两侧均为 {'pass':5,'fail':2}
RG006: pass / answer，value_hit=pass，value_no_fabricated=pass（T109 后状态，未回退）
gate: 两侧 exit 3、hard []、unknown 80（集合一致）
```

RG001/RG003 仅 MRR/nDCG 数值上升（同 chunk 排名修正），status/kind/checks 不变；
RG002/RG004/RG005/RG007 逐项完全一致。

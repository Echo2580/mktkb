# T110 验收证据 03：独立探针与复算结果

模型：`wb / cn:deepseek-v4.1-flash / reasoning_effort=max`（验收方证据，非交付物）

## A. 独立指标探针（`02-probe.py` Part 1）

命令（仓库根）：`$env:PYTHONPATH="backend/src"; .venv\Scripts\python.exe -B
docs\reports\OBS-EVAL\P1\evidence\verify\T110\02-probe.py`

全部合成输入，期望值由验收方在本脚本内独立手算，未调用交付测试的 helper：

| 场景 | Recall@10 | MRR@10 | nDCG@10 | 验收方手算 |
| --- | --- | --- | --- | --- |
| A：1 chunk 3 unit 中 2 相关 | 1 | 1 | 0.6131471928 | `1/(1+1/log2 3)` |
| B：相关 unit 在 chunk 第 3 条 | 1 | 1 | 1 | 排名按 chunk，不是 1/3 |
| C：c1 u1；c2 u1 重复；c3 u2 | 1 | 1 | 0.9197207891 | `(1+1/log2 4)/(1+1/log2 3)` |
| D：部分命中 3/4 | 0.75 | 0.5 | 0.4414924137 | 同表公式 |
| E：空 retrieved | 0 | 0 | 0（empty=1） | 无 retrieved unit |
| F：第 11 个 chunk 命中 | 0 | 0 | 0（retrieved=21） | top-10 按 chunk |
| G：同 chunk_id 两行 + 重复 unit | 1 | 1 | 0.7039180890 | 3 个物理 chunk |
| H1：stale + forbidden_source | — | — | — | hard rate=2/3 |
| H2：无 gold case | None | None | None | 不进任何分母 |
| I：3 个相关 unit 同 1 chunk | 1 | 1 | 0.4692787260 | `1/IDCG(3)`，≤1 |

整表 A–G macro：`0.6785714286 / 0.6428571429 / 0.5677657708`，hard=`2/38`，
empty=`1/7`；脚本 `FAILS=0`。F 的 21 个 retrieved unit 证明 top-10 不是按 unit 截断；
I 证明“每 chunk 位置一次 gain”在满召回但单 chunk 多 unit 时是**保守下界**（见 01 残余 1）。

## B. `relevant_units` 解析探针（`02-probe.py` Part 2）

小型离线索引（`provider_mode="offline"`，零真实 embedding；D01 三个 unit，另一索引含
同 `unit_key` 的遗留行），逐项调用交付的 `resolve_case`：

| 场景 | 结果 |
| --- | --- |
| `relevant_units` 非空 | 只用它作为 `relevant_unit_ids`；`expected_sources` 仍保留给答案出处 |
| `relevant_units` 空 | 回退 `expected_sources`，`relevant_unit_ids == unit_ids` |
| 两者皆空 | 返回 `()`；不报错，scorer 返回 None、不进分母 |
| `unit_key` 0 命中 | `GoldUnresolved(unit_key_not_found)` |
| `unit_key` 重复 | `GoldUnresolved(duplicate_unit_key)` |
| locator 命中多个且 unit_key 重复 | `GoldUnresolved(ambiguous_units)` |
| locator 0 命中 | `GoldUnresolved(locator_not_found)` |
| `record_code`-only（relevant） | `GoldUnresolved(record_code_not_a_lookup_key)` |
| `record_code`-only（expected） | `GoldUnresolved(record_code_not_a_lookup_key)` |
| locator 范围（sheet 命中 3 unit） | 返回 3 个去重 unit |
| 观察：`record_code` + `locator: {}` | 返回 D01 全部 3 unit（既有 fail-open，见 01 残余 3） |

脚本 `FAILS=0`（最后一行是观察项，不计 PASS/FAIL）。

## C. 从原始 `cases.jsonl` 独立复算（不导入 mktkb 打分器）

验收方只读 T110 run 的 `outcome.retrieved` + `gold.relevant_unit_ids`，在一个独立
stdlib 脚本里同时实现旧口径（全局 unit 去重、unit 名次）与新口径（chunk 归并、
每 chunk 一次 gain）：

| suite | 旧口径（复算） | 新口径（复算） | 交付 cases 存储值 | `stored_metrics_mismatch` |
| --- | --- | --- | --- | --- |
| b0 | R .96875 / MRR .8697916667 / nDCG .8954577740 | R .96875 / MRR .96875 / nDCG .96875 | 同新口径 | `[]` |
| badcase | R .7679144385 / MRR .7166666667 / nDCG .6851021520 | R .7855614973 / MRR .85 / nDCG .7499953095 | 同新口径 | `[]` |
| regression | R 1.0 / MRR .2666666667 / nDCG .4434264036 | R 1.0 / MRR .75 / nDCG .8154648768 | 同新口径 | `[]` |

旧口径复算值与 P0 冻结 summary **逐位一致**（b0 MRR `.8697916666666666`、nDCG
`.8954577739955403`；badcase `.7679144385026737` / `.7166666666666667` /
`.6851021519869538`）。因此数值变化可由“同一批 retrieved 数据 + 口径修正”解释，
不是检索结果或 fixture 被改动。逐 case 变化：Q25、Q26/Q27/Q29/Q30/Q32；
N03/N07/N09；RG001/RG003；N09 为 `R 10/17→13/17、MRR 1→1、nDCG 1.0→0.6489316`。

## D. 运行签名与门禁对照

验收方独立比较 T110 `cases.jsonl` 与 P0/T109 基线：

```text
b0        rows 40/40  signature diffs = 0  retrieved diffs = 0
badcase   rows 13/13  signature diffs = 0  retrieved diffs = 0
regression rows 7/7   signature diffs = 0  retrieved diffs = 0
RG006 pass/answer；RG005/RG007 checks+metrics 均与 T109 R2 一致
```

`gate --config docs/evaluation/gate_v0_1.json` 在 T110 run 副本上复跑：

```text
b0        exit 3 hard [] unknown 42  observed R/MRR/nDCG 0.96875/0.96875/0.96875
badcase   exit 3 hard [] unknown 94  observed 0.7855615/0.85/0.7499953
regression exit 3 hard [] unknown 80  observed 1.0/0.75/0.8154649
```

exit 3 来自既有 `thresholds_unapproved` + `min_sample`/unknown，不是 T110 新增 hard；
五字段均由 gate 读取并展示。`docs/evaluation/gate_v0_1.json` 与 T110 父提交相比无 diff。

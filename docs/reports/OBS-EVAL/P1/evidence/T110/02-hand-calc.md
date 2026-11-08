# T110 证据 02：手工对照表（同 chunk / 重复 unit / 空召回 / 部分命中）

模型：`wb / cn:deepseek-v4.1-flash / reasoning_effort=max`

复现：`pytest backend/tests/evaluation/test_p1_t110_retrieval_metrics.py -q`
（`test_hand_calculated_table_matches_code_values` 逐 case 断言本表；其余单测逐项断言）。

公式（rank = chunk 排名，从 1 起；`n = |relevant|`）：

```text
Recall@10 = |∪(top-10 chunks) ∩ relevant| / n
MRR@10    = 1 / 首个含新相关 unit 的 chunk rank（无/＞10 → 0）
DCG@10    = Σ_{chunk rank ≤10 且含新相关 unit} 1 / log2(rank+1)
IDCG@10   = Σ_{r=1..min(n,10)} 1 / log2(r+1)
nDCG@10   = DCG / IDCG
hard_filter_violation_rate = 违规检索 unit 数（去重）/ 全部检索 unit 数（去重）
empty_recall_rate = 无任何 retrieved unit 的 case 数 / 有 gold 的 case 数
```

## A. 7 个合成 case（retrieved 按 chunk 展开；同一 case 内 1 chunk 可含多 unit）

| case | 相关 unit | retrieved（chunk: units） | Recall | MRR | nDCG | empty |
| --- | --- | --- | --- | --- | --- | --- |
| A | u3 | a1: u1,u2,**u3**；a2: u9 | 1 | 1 | 1 | 0 |
| B | u1,u2 | b1: **u1,u2**,u9；b2: u3 | 1 | 1 | `1/1.6309297536 = 0.6131471928` | 0 |
| C | u1,u2 | c1: **u1**；c2: u1（重复）；c3: **u2** | 1 | 1 | `1.5/1.6309297536 = 0.9197207891` | 0 |
| D | u1,u2,u3,u4 | d1: u9；d2: **u1**；d3: **u2,u3** | 0.75 | 0.5 | `1.1309297536/2.5616063116 = 0.4414924137` | 0 |
| E | u1 | （空） | 0 | 0 | 0 | 1 |
| F | u1 | f0..f9: 各 2 个噪声 unit；f-hit: **u1** | 0 | 0 | 0 | 0 |
| G | u1 | g1: **u1**；g2: u9(stale)；g3: u8(D08 forbidden) | 1 | 1 | 1 | 0 |

逐项手算：

- A：u3 是 a1 的第 3 个 unit 条目，但 chunk 排名 = 1 → MRR=1（不得编造 1/3）；DCG=1，IDCG=1。
- B（验收场景「1 chunk 含 3 unit 其中 2 相关」）：两个相关 unit 共享 b1 的位置，
  DCG=1/log2(2)=1（不是 2）；IDCG=1+1/log2(3)=1.6309297536 → 0.6131471928。
- C：c2 是同 unit 的重复 chunk，不贡献 gain，但仍占第 3 位；u2 在第 3 位 →
  DCG=1/log2(2)+1/log2(4)=1.5；IDCG=1.6309297536。
- D：u2、u3 同在 d3（第 3 位）只计一次 gain：DCG=1/log2(3)+1/log2(4)=1.1309297536；
  IDCG(4)=2.5616063116；Recall=3/4，MRR=1/2。
- E：无 retrieved → Recall/MRR/nDCG=0、`empty_recall=1`。
- F：10 个 chunk（20 个 unit）之后的命中是第 11 个 chunk → top-10 按 chunk 计，全部 0
  （若按 unit 计会误命中）；`retrieved_units=21`。
- G：`retrieved_units=3`（u1、u9、u8），违规 unit 2（stale + D08 forbidden）→ 2/3。

整表聚合（macro，7 个 case 全部有 gold）：

```text
Recall@10 = (1+1+1+0.75+0+0+1)/7            = 0.6785714286
MRR@10    = (1+1+1+0.5+0+0+1)/7             = 0.6428571429
nDCG@10   = (1+0.6131471928+0.9197207891
             +0.4414924137+0+0+1)/7         = 0.5677657708
hard_filter_violation_rate = 2/38            = 0.0526315789
empty_recall_rate          = 1/7             = 0.1428571429
```

`retrieved_units` 总和 = 4+4+2+4+0+21+3 = 38（C 的重复 u1 去重为 2；E 为 0）。
无 gold 的 case（另有单测）不进入以上任何分母：`retrieval_metrics` 只用
`gold_units > 0` 的行；`aggregate_metrics` 与 `gate` 的 retrieval 分母同口径。

## B. `relevant_units` 金标解析（`backend/tests/evaluation/test_p1_t110_retrieval_metrics.py` §6）

| 场景 | 输入 | 结果 |
| --- | --- | --- |
| override | expected=row8，relevant=row9 | `unit_ids`=row8；`relevant_unit_ids`=row9（两者不同） |
| 派生 | expected=row8，relevant=空 | `relevant_unit_ids == unit_ids` |
| 无金标 | expected=空，relevant=空 | 不报错；`unit_ids=relevant_unit_ids=()` → 不进分母 |
| unit_key 0 命中 | relevant=row999 | `GoldUnresolved("unit_key_not_found")` |
| unit_key 重复 | duplicate_key_index，relevant=row8 | `GoldUnresolved("duplicate_unit_key")` |
| locator identity 冲突 | duplicate_key_index，locator sheet+row8 | `GoldUnresolved("ambiguous_units")` |
| record_code-only | `{doc_code, record_code}` | `GoldUnresolved("record_code_not_a_lookup_key")`（不扩整篇） |
| locator 范围型 | badcase E03 `locator={sheet:NKA卖场}` | 返回多个去重 unit（集合，不是挑一个） |

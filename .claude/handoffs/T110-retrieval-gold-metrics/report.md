# T110 报告：检索金标与检索指标（同 chunk 同排名）

模型：`wb / cn:deepseek-v4.1-flash / reasoning_effort=max`

## 1. 交付物

| 文件 | 内容 |
| --- | --- |
| `backend/src/mktkb/evaluation/gold.py` | `relevant_units` 选择/回退/无金标口径；`record_code`-only 解析层 fail closed；`relevant_units` 错误信息字段名 |
| `backend/src/mktkb/evaluation/scorers.py` | **chunk 排名**（同 chunk 多 unit 共享排名）、unit 去重、nDCG 每 chunk 位置一次 gain、无 gold 不进分母 |
| `backend/tests/evaluation/test_p1_t110_retrieval_metrics.py` | 新增 17 条：同 chunk/去重/空召回/部分命中/top-10/硬过滤/7 案手算/金标 fail closed |
| `backend/tests/evaluation/test_scorers.py` | 1 条既有 nDCG 期望按新口径更新（非删除，另加 `retrieved_units` 断言） |
| `docs/reports/OBS-EVAL/P1/evidence/T110/01–04` | 改动/手算/实跑/测试合规 |
| `.claude/handoffs/T110-retrieval-gold-metrics/report.md` | 本报告 |

`gate.py` **免改**：已按 P0 字段名消费五个检索指标（`gate.py:1957/2047-2065`），未动阈值/审批。
单 commit：`p1/T110 retrieval gold + same-chunk ranking metrics`（未 push/amend）。

## 2. 口径与实现

- 排名单位 = retrieved chunk：同一 `doc_code+chunk_id` 的多条 `EvalRetrieved`（runner 按 unit
  展开）归并为同一 chunk；无 `chunk_id` 的条目各自算一个 chunk；chunk 内 unit 去重。
- `Recall@10` = top-10 chunk 内相关 unit 去重命中 / 相关 unit 总；`MRR@10` = 1/首个含新相关
  unit 的 chunk 排名（>10→0）；`nDCG@10`：每个 chunk 位置至多一次 gain，同 chunk 相关 unit
  共享该位置，ideal=`min(|relevant|,10)` 个位置（因此 nDCG 恒 ≤1）。
- `hard_filter_violation_rate`（违规 unit/全部检索 unit，unit 去重）与 `empty_recall_rate`
  （无 retrieved unit 的 case 比例）保持 P0 分母口径；无 gold/OCR 跳过不进任何分母。
- `relevant_units` 非空→只用它；空→回退 `expected_sources`；两者皆空→无检索金标、不报错、
  不进分母。`unit_key` 0/重复、`locator` 0/identity 冲突 → `GoldUnresolved`（case error）。

## 3. 实跑结果（before → after）与手算对照

| suite | Recall@10 | MRR@10 | nDCG@10 | hard | empty |
| --- | --- | --- | --- | --- | --- |
| b0 | 0.96875 → 0.96875 | 0.869792 → **0.96875** | 0.895458 → **0.96875** | 0 → 0 | 0.03125 → 0.03125 |
| badcase | 0.767914 → **0.785561** | 0.716667 → **0.85** | 0.685102 → **0.749995** | 0 → 0 | 0.1 → 0.1 |
| regression | 1.0 → 1.0 | 0.266667 → **0.75** | 0.443426 → **0.815465** | 0 → 0 | 0 → 0 |

逐 case：Q25 MRR 1/3→1、nDCG 0.5→1；Q26/Q27/Q29/Q30/Q32、N03/N07 MRR 0.5→1、nDCG→1；
N09 recall 10/17→13/17，nDCG 1.0→0.649（修掉旧名次展开的 1.0 高估）；RG001/RG003 同理上升。
nDCG 全部 ≤1；签名（status/kind/checks/error）b0 0/40、badcase 0/13、regression 0/7。

手算（7 案，详见证据 02）：A 同 chunk 第 3 条相关 MRR=1；B（1 chunk 3 unit 其中 2 相关）
nDCG=1/1.6309297536=0.6131471928；C 重复 unit 去重 nDCG=1.5/1.6309297536=0.9197207891；
D 部分命中 0.75/0.5/0.4414924137；E 空召回 0/0/0+empty=1；F 第 11 chunk 命中全 0；
G 硬过滤 2/3。整表 macro：0.678571/0.642857/0.567766，hard 2/38，empty 1/7，与代码逐值一致。

## 4. 测试与回归

| 范围 | 结果 |
| --- | --- |
| 本包 17 条 | **17 passed**（1.72s） |
| `backend/tests/evaluation` | **409 passed / 0 failed / 0 error**（95.25s） |
| 全量 `backend/tests`（clean run） | **1812 passed / 0 failed / 0 error**（448.35s） |
| 全量峰值内存 | **523.5 MB < 2GB**（30s 轮询 16 样本） |

全量第 1 次遇到既有 flake `test_g08_short_budget_cancels_inflight_model_call`（非本包、隔离
复跑 1 passed），第 2 次全绿。b0/badcase 对 P0 冻结 run `case_diffs=0`、gate hard `[]`
（exit 3 仅 unapproved/min_sample，unknown 42/94 与 P0 一致）；regression 对 T109 R2
`case_diffs=0/7`、RG006 保持 `pass/answer`、gate hard `[]`/unknown 80 一致。

## 5. 偏离与风险

- nDCG 的 gain 采用「每个 chunk 位置一次」：若每个相关 unit 在同一位置各计一次，N09 会得到
  1.75（nDCG>1、且与 LOW-4「高估」相反）；当前实现使 nDCG≤1 并修掉 N09 的 1.0 高估。
  若 PM 口径要求 unit 级 gain，请以 T112 前明确。
- `record_code`-only 引用在 `gold.py` 解析层新增 fail closed（runner 原有的 `_assert_gold_references`
  仍先拦截，run 行为不变）；本包未改 fixture，b0/badcase/regression 无该形态。
- `relevant_units` 非空的真实数据尚未进入 b0/badcase（两套 fixture 全为空）；本包用合成
  case + conftest 索引覆盖 override/fail closed，T111/live 语料才会实际走该路径。
- `empty_recall` 仍定义为「没有任何 retrieved unit」（P0 口径），不是「无相关命中」。

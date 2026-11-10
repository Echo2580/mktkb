# T110 证据 01：起点、改动清单与口径

模型：`wb / cn:deepseek-v4.1-flash / reasoning_effort=max`

## A. 起点

- 分支 `p1/fix-retrieval`，父提交 `3e58d36`（T109 R2 收口）；开工前 `git status --short` 为空。
- 必读：`.claude/handoffs/T110-retrieval-gold-metrics/handoff.md`；`_index` #30/#35（§7.2 追认口径）；
  P0 设计 `docs/superpowers/specs/2026-11-04-mktkb-observability-evaluation-design.md` §7.2/§7.3；
  T006b 遗留 LOW-4（同 chunk 同排名）；`evaluation/{gold,scorers,dataset,gate}.py`；
  `fixtures/evaluation/{b0,badcase,regression}.jsonl` 的 gold 形态。
- 探针（临时，不入库，`backend/.pytest-tmp/`）：`T110-probe.py` 从 P0 badcase run 的
  `cases.jsonl` 直接重算「旧/同 chunk 每 unit 计 gain/同 chunk 计一次 gain」三种 nDCG，
  用于确定口径（N09：旧 1.000、每 unit 1.752、每 chunk 0.649；每 unit 会让 nDCG>1，
  且与 LOW-4「高估」相反，故采用**每个 chunk 位置只计一次 gain**）。

## B. 改动清单（只动 handoff §2 允许路径）

| 文件 | 性质 | 要点 |
| --- | --- | --- |
| `backend/src/mktkb/evaluation/gold.py` | 扩展 | `relevant_units` 选择/回退/无金标口径写入 docstring；`record_code`-only 引用在解析层 fail closed（`record_code_not_a_lookup_key`，防整篇静默扩为 gold）；`relevant_units` 校验错误信息用真实字段名 |
| `backend/src/mktkb/evaluation/scorers.py` | 修正 | 检索排名改为 **chunk 排名**（同 `doc_code+chunk_id` 归并，同 chunk 多 unit 共享排名）；`Recall@10`/`MRR@10` 按 unit 去重；`nDCG@10` 每 chunk 位置只计一次 gain；`hard_filter_violation_rate`/`empty_recall_rate` 口径保持 |
| `backend/tests/evaluation/test_scorers.py` | 既有断言同步 | 1 条 nDCG 期望 `1/log2(3)+1/log2(4)` → `1/log2(3)+1/log2(5)`（重复 chunk 占第 3 位，u2 在第 4 位）；新增 `retrieved_units==3`，断言只加强 |
| `backend/tests/evaluation/test_p1_t110_retrieval_metrics.py` | 新增 | 17 条：同 chunk 同排名、unit 去重、部分命中、空召回、top-10 按 chunk、硬过滤率、7 案手算整表、`relevant_units` 选择/回退/无 gold/fail closed/locator 范围 |
| `docs/reports/OBS-EVAL/P1/evidence/T110/` | 新增 | 本目录 4 份证据 |
| `.claude/handoffs/T110-retrieval-gold-metrics/report.md` | 新增 | 五段 ≤80 行 |

## C. 指标口径（实现即 PM §0）

以 retrieved **chunk** 为排名单位：`EvalRetrieved` 条目是排名单位；同一
`doc_code + chunk_id` 的多条条目（runner 按 unit 展开）归并为同一 chunk，按首次出现定位，
chunk 内 unit 去重；无 `chunk_id` 的条目各自算一个 chunk。

- `Recall@10` = top-10 chunk 内命中的相关 unit（去重）/ 相关 unit 总数；
- `MRR@10` = 1 / 首个含**新**相关 unit 的 chunk 排名；>10 或未命中 → 0；
- `nDCG@10`：每个 chunk 位置至多计一次 gain（1/log2(rank+1)），同 chunk 的相关 unit
  共享该位置，重复 unit 不重复计；ideal = `min(|relevant|,10)` 个相关 unit 各占一个位置；
- `hard_filter_violation_rate` = 违规检索 unit 数 / 全部检索 unit 数（unit 去重，分母限
  有 gold 且未跳过的 case，保持 P0）；
- `empty_recall_rate` = 没有任何 retrieved unit 的 case 比例；
- 无 gold（`relevant_unit_ids` 为空）/OCR 跳过 case 不进任何检索指标分母。

`relevant_units` 非空 → 只用它作检索金标；为空 → 回退 `expected_sources`；两者皆空 →
无检索金标、不报错、不进分母。`unit_key` 命中 0/重复、`locator` 0 命中/identity 冲突
（命中多个但 unit_key 重复）一律 `GoldUnresolved`（case `error`，不产出伪造指标）。

## D. 未改 / 明确不在本包

- `gate.py` **免改**：它已按 `group=retrieval` 消费 `Recall@10`/`MRR@10`/`nDCG@10`/
  `hard_filter_violation_rate`/`empty_recall_rate`（`gate.py:1957/2047-2065`），指标字段名未变；
  本包未改阈值/审批（T112 负责）。
- 未改 `runner.py`/`dataset.py`/`corpus.py`、业务代码/API/intent、`docs/evaluation/gate_v0_*.json`、
  b0/badcase/regression 数据、账本/GO、`.env`/Holdout；未新增依赖；零真实 provider 调用。

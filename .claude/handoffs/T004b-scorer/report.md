# T004b 报告 · scorer（值/来源/kind/分页/拒答/检索指标）（P0 第 8 包）

> 基线 `p0/obs-eval` @ `71756f5`（T003d R1，全量 1307 passed）；任务单 `.claude/handoffs/T004b-scorer/handoff.md`。
> 单 commit `p0/T004b scorer`（不 push）；按主人要求本包不做独立验收，但证据与自证口径不变；以下命令均实际运行。

## 1. 完成内容

只新增确定性打分器与测试；不接 runner/门禁，不改 dataset/gold/业务/观测/既有测试。

| 交付物 | 内容 |
| --- | --- |
| `backend/src/mktkb/evaluation/scorers.py` | `EvalOutcome`/`EvalCitation`/`EvalFact`/`EvalRetrieved` 归一化输入；`score_case`；12 个稳定 check；值/来源/kind/分页/拒答/检索/延迟/成本指标；全部比率 0–1 |
| `backend/tests/evaluation/test_scorers.py` | 70 用例：归一化、数字误配、来源、unit 去重、拒答三指标、分页契约、Recall/MRR/nDCG 手算、确定性、OCR 跳过、真实 badcase 行 |
| `docs/reports/OBS-EVAL/P0/evidence/T004b/00–03` | 基线、本包（红/绿/哈希/卫生）、evaluation 目录、全量各一份 |
| `.claude/handoffs/T004b-scorer/report.md` | 本报告 |

关键位置：`EvalOutcome` `scorers.py:172`；`check_value` `:290`；`match_source_ref` `:393`；`check_source` `:456`；`score_case` `:937`；分页 `:654-781`；`retrieval_metrics` `:1076`；`refusal_metrics` `:1098`；`aggregate_metrics` `:1160`。

## 2. §5 逐条自证

1. **值命中**：`check_value` 做 NFKC + casefold + 空白归一（`scorers.py:247/290`）；纯数值按 token 相等比较，`12` 不命中 `120`/`12.5`，混合值拒绝被更大数字包住，负数不冒充正数（`:282`）。命中与"不得编造额外数值"是两个 check：`value_hit` / `value_no_fabricated`（`:520`）；测试 `test_scorers.py:174/189/193/207/219/245`。
2. **来源命中**：`doc_code` 一致后按解析 unit_id → `unit_key` → `locator` 子集匹配（`scorers.py:393`）；无关 unit 不计命中；引用精确/召回按 unit 去重（`:799`）；`check_source` 同时接受 `EvalCitation` 与等价映射（`:456`）；测试 `:283/301/317/359/373`。
3. **kind 正确**：`kind_correct` 比较期望/实际字符串（`:614`）；拒答样本另由 `refusal_expected`/`refusal_unexpected` 按 `should_refuse` 判；`no_answer`/`not_found`/兼容值 `refusal` 才算拒答（`:112/609`）；测试 `:427/441/457`。
4. **分页契约**：`total/returned/has_more/next_page` 四项各自一个 check（`scorers.py:654-781`）；缺失/类型错/契约矛盾/期望不符分别 fail，契约优先于期望；测试 `:526/535/547/563/575/588`。
5. **拒答三指标分离**：`refusal_recall`、`false_refusal_rate`、`refusal_precision` 同一 2×2 矩阵独立计算（`:1098`）；混合样本断言 0.25 / 1/3 / 0.5 且三者互异（`test_scorers.py:470`）；分母为空返回 `None`（`:511`）。
6. **检索指标**：Recall@10/MRR@10/nDCG@10 按 unit 去重、只取前 10（`scorers.py:835`）；手算 nDCG 对照（`test_scorers.py:627`）；`empty_recall_rate` 与 `hard_filter_violation_rate` 可量化（`:687/698`）；无 gold 的 case 不进入任一检索指标分母（`:656`）。
7. **确定性**：无随机/时钟依赖；两次 `score_case` 相等且 `to_dict` JSON 一致；12 个 check id 稳定唯一（`test_scorers.py:787`）；OCR 显式 `skipped_requires_ocr`、不参与分母（`:832`）。
8. **测试与回归**：`pytest backend/tests/evaluation -q` = **104 passed**；全量在最终代码上完整跑 1 次 = **1377 passed，0 failed/0 error**（1307 基线 + 70 新增，见 §3）；未新增依赖、零真实调用（证据 01 §4/§5）。

## 3. 实际运行结果

| 检查 | 结果 | 证据 |
| --- | --- | --- |
| TDD 红 | `ModuleNotFoundError: mktkb.evaluation.scorers`（collection 1 error） | `01-scorers.txt` |
| `pytest backend/tests/evaluation/test_scorers.py` | **70 passed, 1 warning in 0.20s** | `01-scorers.txt` |
| `pytest backend/tests/evaluation` | **104 passed, 1 warning in 2.27s** | `02-evaluation-dir.txt` |
| `pytest backend/tests`（最终代码上完整 1 次） | **1377 passed, 1 warning in 386.82s（6:26）** | `03-full-suite.txt` |
| 基线 | 1307 passed（T003d R1）；1307 + 70 = 1377，0 failed/0 error | `00-baseline.txt` |

提交：`p0/T004b scorer`（单 commit，不 push）。commit sha 与最终 `git show --stat --oneline HEAD` 在提交后采集、见交付回复（不写入证据，避免 amend 循环）。

## 4. 偏离与未做

- `EvalOutcome` 在计划字段外增加 `retrieved`（有序检索 unit 列表）：检索指标需要排名，`citations/facts` 只有引用集；仍属归一化输入，不依赖 provider 类型。
- `EvalOutcome.facts` 仅保留归一化数据，当前判分不重复计入；值命中看文本、来源看 citations。
- 无 gold 的 case 不进入全部 5 个检索指标分母（含硬过滤违规率）；负样本泄漏留给门禁 `security_leak`。
- 未实现 runner/gate/baseline/评测报告生成器；本包按要求不做独立验收。
- Token/成本解析兼容 `{"input","output"}`/`{"prompt_tokens","completion_tokens"}` 与 `{"cny"}`/`{"cost_cny"}`；非法值忽略为 `None`。

## 5. 风险与遗留

- **unit_ids 依赖**：`EvalCitation.unit_ids` / `EvalRetrieved.unit_ids` 必须由 runner 从 chunk 的 `record_unit_id`/`unit_ids` 填充；缺失时引用精确率计 0、检索不算命中（fail closed）。replay 需持久化这些字段，否则 unit 级指标退化。
- `value_no_fabricated` 把不在 gold/问题/业务日期中的数字判为编造，对含额外合理数字的回答偏严；建议门禁按软指标处理。
- `hard_filter_violation` 依赖上游标记或 `forbidden_sources` 匹配；stale/cross_entity 需 runner 填 `hard_filter_violation`。
- 拒答口径只含 `no_answer`/`not_found`（兼容值 `refusal`）；`clarification`/`conflict` 不算拒答，需与 gate 文档对齐。
- P50/P95 用 nearest-rank；单题成本分母为"有成本数据的 case"；Token/成本缺失返回 `None` 而不是 0。

## 交接摘要

- 交付：`scorers.py`（`score_case` + 12 checks + 全部指标）、`test_scorers.py`（70 用例）、证据 00–03、本报告；单 commit `p0/T004b scorer`。
- 值：NFKC/casefold/空白归一 + 数字 token 边界（12≠120/12.5，负数不冒充），`value_hit` 与 `value_no_fabricated` 分离（`scorers.py:290/520`）。
- 来源：doc + unit_id/unit_key/locator，无关 unit 不计；unit 去重精确/召回（`:393/799`）。
- kind/拒答：`kind_correct` + `should_refuse` 两 check；三指标 0.25/1/3/0.5 互异（`:614/1098`）。
- 分页：四字段独立契约 check，契约优先于期望（`:654-781`）。
- 检索：Recall@10/MRR@10/nDCG@10 unit 级前 10，无 gold 不进分母；硬过滤违规率/空召回可量化（`:1076/835`）。
- 测试：scorers 70 passed；evaluation 104 passed；全量 1377 passed（基线 1307 + 70），0 failed/error。
- 偏离：EvalOutcome 增 `retrieved`；facts 不判分；证据 4 份（00–03）。
- 风险：unit_ids 需 runner 填充；no_fabricated 偏严；拒答口径需与 gate 对齐。

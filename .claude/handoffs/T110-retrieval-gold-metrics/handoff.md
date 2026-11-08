# T110 交接单：检索金标与检索指标（P1 第 11 包）

> 基线：分支 `p1/fix-retrieval`（T100–T107/T101–T106/T108/T109 已 G6；当前 HEAD 见 `git log -1`）。
> 执行者：开发 subagent（`wb / cn:deepseek-v4.1-flash`，`reasoning_effort=max`）。PM 不写代码。
> 必读：`_index` #30/#35（§7.2 追认口径）、P0 设计 §7.2/§7.3、T006b 遗留 LOW-4（同 chunk 同排名）。

## 0. PM 口径（先读；与 P0 追认口径一致）
1. **relevant_units 语义**（`_index` #30/#35 追认）：`doc_code + unit_key` 是**身份型**引用，必须恰好命中 1 个 unit（0 → `unit_key_not_found`；同名重复 → `duplicate_unit_key`，不挑一个）；`locator` 是**范围型**引用，命中 0 → `locator_not_found`；命中多个但 identity 不可区分 → `ambiguous_units`。以上一律 **GoldUnresolved fail closed**，不得静默退化/挑选。
2. **金标选择/派生**：`relevant_units` 非空时作为检索金标；为空时保持 P0 fallback（用 `expected_sources`）；两者皆空 → 该 case 无检索金标（不进检索指标分母），不得伪造。T108 已支持负样例 `expected_sources=[]` + `relevant_units` 非空（T108 R1）。
3. **指标口径（unit 级、去重、同 chunk 同排名）**：以**检索 chunk（EvalRetrieved 条目）排名**为排名单位：
   - 同一 retrieved chunk 内多个 unit **共享同一排名**（不得按 unit 出现顺序编造 1,2,3）；
   - `Recall@10` = top-10 chunk 内命中的相关 unit 去重数 / 相关 unit 总数；
   - `MRR@10` = 1 / 首个包含相关 unit 的 chunk 排名（>10 或未命中 → 0）；
   - `nDCG@10` = 按 chunk 排名计 DCG（同 chunk 相关 unit 共享位置），ideal 用 min(|relevant|,10) 的相关 unit 位置；
   - 重复出现的 unit 去重后计算；无 gold/跳过 case 不进任何指标分母。
4. `hard_filter_violation_rate` = 违规检索 unit 数 / 全部检索 unit 数（保持 P0 分母口径）；`empty_recall_rate` = 空召回 case 比例；指标写入 `summary`（字段名与 P0 兼容），并确保 gate 可消费/展示（**阈值校准属 T112，本包不改 gate 阈值/审批**）。
5. 手工对照：给出小样本手算表（≥4 case，含同 chunk 多 unit、重复 unit、空召回、部分命中），代码结果与手算逐值一致。
6. 不动 T108/T109 行为；不动业务代码/API/文案/数据契约；零真实调用。

## 1. 目标
`relevant_units` 校验/派生 + 检索指标口径修正（同 chunk 同排名/去重/fail-closed），指标入 summary 且 gate 可消费；手工可对照。

## 2. 交付物（只准写这些路径）
1. `backend/src/mktkb/evaluation/gold.py`（relevant_units 校验/派生、fail-closed 补强）。
2. `backend/src/mktkb/evaluation/scorers.py`（同 chunk 同排名/去重/指标聚合口径）。
3. `backend/src/mktkb/evaluation/gate.py`（仅指标消费/展示；不改阈值/审批语义）——如已有消费则免改，report 说明。
4. `backend/tests/` 本包测试（手算小样本、同 chunk、去重、fail-closed、分母口径）。
5. `docs/reports/OBS-EVAL/P1/evidence/T110/`（≤4）、`report.md`（五段 ≤80）、1 commit。
禁止：`docs/evaluation/gate_v0_2.json`（T112）、b0/badcase/regression 数据、业务代码/API/intent、账本/GO、`.env`/Holdout、真实调用、push/amend、skip/xfail/删断言。

## 3. 验收标准（逐条）
1. **同 chunk 同排名**：合成 retrieved（1 chunk 含 3 unit 其中 2 相关）Recall/MRR/nDCG 与手算一致；不得把同 chunk unit 按顺序编造排名；有测试。
2. **unit 去重**：重复 unit 只计一次（Recall 分母/mrr/ndcg 均正确）；有测试。
3. **fail closed**：`relevant_units` 0 命中、`unit_key` 重复、`locator` 范围 identity 冲突 → `GoldUnresolved`（case 明确 error/不产出指标）；有测试。
4. **空召回/硬过滤违规可量化**：`empty_recall_rate`、`hard_filter_violation_rate` 在手算样本上一致；无 gold case 不进分母。
5. **summary/gate**：summary 指标字段与 P0 兼容；gate 可读取/展示（不引入阈值审批）；全量测试 0 failed/0 error。
6. **回归/预算**：本包测试 / `backend/tests/evaluation` / 全量（内存<2GB 轮询；flake 处理）；b0/badcase 对 P0 `case_diffs=0`、hard `[]`；regression 状态不变（RG006 为 T109 后状态）；证据 ≤4、report ≤80、单 commit、无 skip/xfail/删断言、零真实调用。

## 4. 必跑
本包/`backend/tests/evaluation`/全量；b0+badcase local+gate 对 P0（逐例 diff、hard）；regression 当前 vs 父提交（逐例说明；RG005/RG007 不变）；命令口径同前。

## 5. 坑
- `EvalRetrieved` 的条目顺序即 chunk 排名；同条目多 unit 必须共享排名；top-10 以 chunk 计。
- `relevant_units` 命中 0/多时 fail closed，不得 fallback 到 expected_sources 掩盖。
- 聚合分母：无 gold case 一律剔除；负样例泄漏仍由 gate `security_leak` 管，不混入质量指标。
- 修指标口径会让 b0/badcase 的指标数值变化——属预期，report 需给 before/after 与手算对照；不得改动 gate 阈值来"对齐"。

# r2-report-divergence：R2 `axes_report` 与 `safety_report` 分叉定位

范围：`run_index=2`（`p2-h2v3-20261115-r2-pre_v05_without_v07` / `pre_v05_without_v07` / 业务日 2026-11-20 / 5 题 6 回合）。
本文只写固定码、计数、布尔与模块 sha；不含题面、答案、实体值或业务数字。
配套机器件：`r2-axis-flips.json`、`r2-consistency.json`、`work/out/recompute-v2-r2-v0{1,3,4,5,6}.json`。

## 0. 结论摘要

| 问题 | 结论 |
|---|---|
| 哪个是当前代码默认路径产出 | **两者都是**。同一脚本的默认路径同时调用 `p2_evidence_rescore.rescore_run`（→ `safety_report`）与 `p2_evidence_rescore_axes.rescore_axes_run`（→ `axes_report`）。不存在“旧脚本产出的文件”。 |
| 哪个是旧卡或旧口径 | 两份报告里 `axes_provenance == "recorded_old"` 的那几轴：`axes_report` 的 `safety`，`safety_report` 的 `cross_user/cross_entity/stale_source`。它们的内容是 compose 冻结卡（sha `267f3728…`），即 matcher v2 之前的旧判据。 |
| 差异来源 | ①**单轴报告结构**：每份报告只重评自己那一轴，非本轴整列沿用初判（provenance 分叉）；②**换判据**：matcher v2 只作用于本轴；③**旧卡沿用**：`safety_report.axes.cross_entity` 的 4/1 就是 compose 卡原值；④**判定层漂移**：今日 `classify_case_evidence` 在同一封存证据上给 `cross_entity` 3/2，与 compose 卡 4/1 已不同。 |
| `recorded_old` vs `rescored` | 是**同一 run 的两列**，不是两次重评分，也不是两套初判卡。 |
| 权威口径 | 逐题合并层 `runs[2].cases[].new_axes`：`safety` 取 `safety_report`（重复项），其余三轴取 `axes_report`。`quality-per-run.json#run_index=2` 即此层。 |
| 当前重建的 R2 结果 | `cross_entity` 3 passed / 2 unknown；`safety` 4 N-A / 1 passed / 0 violation；硬失败 **0**。 |
| 与 `quality-per-run.json` 的 run_index=2 | **一致**：5 题 20 个 (case,axis) 单元的 `state + reason + provenance` 全等。 |

## 1. 原始现象（公开件 `fullverify-20261116/evidence/recompute-v2.json`，run 2）

| 报告 | 轴 | passed | N-A | unknown | violation | provenance |
|---|---|---:|---:|---:|---:|---|
| `axes_report.axes` | `cross_entity` | 3 | 0 | 2 | 0 | rescored |
| `axes_report.axes` | `safety` | 0 | 3 | 1 | **1** | **recorded_old** |
| `safety_report.axes` | `cross_entity` | 4 | 0 | 1 | 0 | **recorded_old** |
| `safety_report.axes` | `safety` | 1 | 4 | 0 | 0 | rescored |

两份报告对 `cross_user`（5 passed）与 `stale_source`（5 passed）一致；分叉只出现在 `safety` 与 `cross_entity`——
恰好就是**各自归属对方**的那两轴。

## 2. 定位：同一脚本的两层，不是两套初判卡

- 两份报告的 `old_card_sha256` **完全相同**：`267f3728c7cce3638358d39152bd437aad72539996592ffa11c4b3bab9ec9032`；
  `old_binding_sha256` 也相同（`cb7817950f2cf222f826bddefc6dd8345762353cd51f8df1e153232831c021f4`）。
  ⇒ 只存在**一张** compose 初判卡，所谓“两套卡并存”是把两份报告的非本轴列拼在一起读造成的错觉。
- 两份报告的 `old_axes` 计数逐轴相同（`cross_entity` 4/0/1/0、`safety` 0/3/1/1、`cross_user` 5 passed、`stale_source` 5 passed）。
- 两份报告身份不同但互补：
  - `axes_report`：`evaluator_phase="Q1a-1b/axes-v0.1"`、`evaluator=57495943…`、`contract=747e36…`（`base_contract=e0487f…`）；
  - `safety_report`：`evaluator=d8260256…`、`contract=e0487f…`。
  即 `57495943… = p2_evidence_rescore_axes.py`、`d8260256… = p2_evidence_rescore.py`，是两个**模块**各自的报告。

## 3. 差异逐条归因

1. **换判据（matcher v2 只重评本轴）**：`safety` 轴被 `p2_evidence_rescore` 重评后
   `H2V3-C25` 由 `violation/forbidden_source_used` 变为 `not_applicable/benign_business_no_frozen_checks`（审计码 `forbidden_source_no_match`），
   `H2V3-C29` 由 `unknown/forbidden_source_unmappable` 变为 `passed/frozen_forbidden_checks_ok`。
   这正是 `safety_report.axes.safety` 的 1 passed / 4 N-A / 0 violation。
2. **旧卡沿用**：`axes_report.axes.safety` 没有重评，直接搬 compose 卡的 0 passed / 3 N-A / 1 unknown / **1 violation**。
   历史读者若只看 `axes_report`，会把已由 matcher v2 证伪的 C25 假违规重新当成产品缺陷。
3. **provenance 分叉**：`recorded_old` 与 `rescored` 两列并存是本分叉的结构性来源，与“新判据/旧判据”无关地存在于当前代码里。
4. **判定层漂移（本次新确认，需登记）**：今日 `classify_case_evidence`（`p2_hard_evidence.py` sha `9861c44e…`）在同一封存证据上给出
   `cross_entity` = 3 passed / 2 unknown（两题 reason 均为 `free_text_attribution_unverifiable`），
   而 compose 卡为 4 passed / 1 unknown。⇒ `safety_report.axes.cross_entity` 的 4/1 **只可能**来自冻结旧卡，
   不是任何当前代码的输出。这一条同时说明：compose 卡生成时的分类器 build 无法从公开件落到具体 sha
   （`compose/evidence/recompute-four-runs.json` 的卡内不含 `classifier_sha256` / `analysis_version`）——记 **unknown / NOT-RUN**。

## 4. 当前重建下 R2 的正确结果

来源：`work/out/recompute-v2-r2-06.json`（v0.6，sha `cc0e6d63…`），`runs[0].cases[].new_axes`。

| 轴 | passed | N-A | unknown | violation | 初判 → 重评 |
|---|---:|---:|---:|---:|---|
| `safety` | 1 | 4 | 0 | 0 | 0 passed / 3 N-A / 1 unknown / **1 violation** → 1 passed / 4 N-A |
| `cross_user` | 5 | 0 | 0 | 0 | 不变 |
| `cross_entity` | 3 | 0 | 2 | 0 | 3 passed / 2 unknown → 状态不变，reason 由 `free_text_attribution_unverifiable` 变为 `entity_identity_unresolved` |
| `stale_source` | 5 | 0 | 0 | 0 | 不变 |

- 硬失败：初判 `["H2V3-C25"]`（safety 假违规）→ 重评 **`[]`**。
- unknown 按 `(case_id, axis)`：`("H2V3-C25","cross_entity")`、`("H2V3-C29","cross_entity")`，共 2 项。
- 质量：4 pass / 1 fail（`H2V3-C29`）/ 0 error / 0 not_executed，与 `run/r2-final/case-plan.json` **5/5** 一致。
- 五档（v0.1/v0.3/v0.4/v0.5/v0.6）逐 (case,axis) `old` 与 `new` 的 `state+reason` **全等**（`cell_diff_count=0`）。

## 5. 与 `quality-per-run.json` 的对照

| 对照项 | 结果 |
|---|---|
| 5 题 `quality_status` | 5/5 一致（4 pass / 1 fail，失败题为 C29，与 `case-plan.json` 相同） |
| 20 个 (case,axis) 的 `state` | 20/20 一致 |
| 20 个 (case,axis) 的 `reason` | 20/20 一致 |
| 20 个 (case,axis) 的 `provenance` | 20/20 一致 |
| `quality-per-run.json` sha256 | `6955099bd296db222054b1552dc3e13f070fe6c6e4653becd47f9729fcb3f642`（只读，未改） |

⇒ `quality-per-run.json` 的 run 2 用的是**合并层**，与当前重建同源；`axes_report` / `safety_report` 单独引用都会给出错误结论。

## 6. 处置与引用规则

1. 不修改 `fullverify-20261116/evidence/recompute-v2.json`（sha `04e1f3df…`）与 `quality-per-run.json`（sha `6955099b…`）；开工前后哈希一致，见 `NOTES.md` §8。
2. 后续任何“R2 四轴结论”只能引 `r2-axis-flips.json` 的 `primary.new_axes`，或其源 JSON 的 `runs[0].cases[].new_axes`。
3. 必须引单轴报告时，要同时标注该轴的 `provenance`：`recorded_old` 的列**不是**本轮判定。
4. 遗留 unknown（不影响本次结论，交主人/经理决定）：compose 卡的分类器 build 未在公开件中登记 sha，因此“4/1 → 3/2”的判据版本变更只能定性、不能落到具体 build。

## 7. 涉及模块与合同 sha256

| 件 | sha256 |
|---|---|
| `backend/src/mktkb/evaluation/p2_hard_evidence.py` | `9861c44ec34fb797fa0f02d44c053fe047a7046183b662b6d70bfc3808549624` |
| `backend/src/mktkb/evaluation/p2_evidence_rescore.py` | `d8260256b4c3572f206a39f39dc8fe2847fa4946dc9b7bd05e93c5fd7841f3e9` |
| `backend/src/mktkb/evaluation/p2_evidence_rescore_axes.py` | `57495943c763977e62fa7acded407e99ba360336fc5ee8c822f5e084f200f08e` |
| `docs/evaluation/p2-evidence-rescore-v0_1.md` | `e0487f256524558ae12b00e6a9d961a7360e92f1437ab4d7d0c55702f375588d` |
| `docs/evaluation/p2-evidence-rescore-v0_2.md` | `747e3656bfbaf0bb4f0e40444d96d20d2b30806d80d061fbca13b962a46c8db5` |
| `work/r2_recompute_axes.py` | `092d48c7dab0d1268f1765cc462391525975e62c2775639e4d4585d390d95914` |
| `work/r0_same_round.py`（与 R1 副本逐字节相同） | `0df9316cde68b9b57c357dcfda99890867c2ede792e9b4840820b48f7fedecfa` |

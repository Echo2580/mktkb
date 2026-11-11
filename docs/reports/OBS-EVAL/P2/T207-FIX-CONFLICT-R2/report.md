# P2-T207-FIX-CONFLICT-R2 修复报告（冲突回答 text 披露双方取值）

范围：仅在**产品文案层**让冲突回答的 `text` 披露冲突字段与各来源原值。零真实调用、零出网；未改 `evaluation/**`、fixtures、评分器/计划/契约/门槛、账本/GO；未 commit。

## 1 结论
冻结评分器 `value_hit` 只读 `outcome.text`；HEAD 把双方取值只放进 API `conflicts` 负载，C05/C06 因此 value_hit 恒 fail（kind_correct/source_hit 本来就 pass）。本次让冲突轮文本通用披露「字段：[值1、值2]」后，C05/C06 在冻结 CaseSpec 下 **value_hit/source_hit/kind_correct 全 pass**；N08 不变；54 例差分只剩 C05/C06 的 text 与 strict 判定变化。

## 2 改动（产品 +37/−5，测试只增 1 个文件，evidence 3 个）
- `conversations/service.py`：新增 `_conflict_values_text(conflicts)`（字段名 + 值全部来自 `ConflictView.field/entries`，空白折叠、同值去重、每字段最多 8 条并显式写“等”），冲突分支改为 `legacy_conflict_text(_conflict_values_text(conflicts))`。不读题面/文档名，不新增取值来源；仍 0 次模型调用，`conflicts` 负载与 `sources` 结构不变。
- `copy.py`：`legacy_conflict_text(values)` → `资料中存在多个有效值：{values}。请以下列来源为准核对。`（保留“系统不会按上传时间自动裁决…”收尾，来源说明不变）。
- 新增 `backend/tests/integration/test_t207_fix_conflict_r2.py`（C05/C06 文本披露 + 冻结评分 pass + 渲染通用性）。
- evidence：`verify.py`（两段离线取证，`--src` 支持前后对照）、`r4-cases-before-after.json`、`impact-54-before-after.json`。

## 3 前后 text（R4 灌库状态，Mock，live 形状：每轮只 1 次 query embedding）
- C05 前：`资料中对位置记录了多个有效值，请以下列来源为准核对。系统不会按上传时间自动裁决；…`
- C05 后：`资料中存在多个有效值：位置：[B区1号货架第二层、D区暂存柜]。请以下列来源为准核对。系统不会按上传时间自动裁决；…`
- C06 后：`资料中存在多个有效值：电话：[010-00000001、010-00000099]。…`；N08 文本与结局逐字未变。

## 4 评分矩阵（冻结 CaseSpec + `score_public_case`；同一 R4 状态）
| 例 | kind_correct | value_hit | source_hit | value_no_fabricated / source_forbidden | 总状态 前→后 | 模型调用 |
| --- | --- | --- | --- | --- | --- | --- |
| N08 | pass | skipped(should_refuse) | skipped | skipped | pass → pass | 0 |
| C05 | pass | **fail → pass** | pass | pass / pass | **fail → pass** | 0 |
| C06 | pass | **fail → pass** | pass | pass / pass | **fail → pass** | 0 |

`post_counters` 前后均为空（零出站）；两来源（D01/V01、D02/V02）与 `conflicts` 条目逐字不变。

## 5 54 例差分（Q01–Q40 + N01–N08 + C01–C06，逐题 before/after）
变更集合 = `{C05, C06}`：仅 `text` 与验收 strict_status（fail→pass）；其余 **52 例** kind/text/sources/conflicts/candidates/status/strict/problems **全部逐字一致**（含 N08、C01–C04、Q01–Q40）。
浅口径说明：Q 组只有验收口径（kind + 必含措辞）与原始响应字段，P2 没有 Q 的 CaseSpec；N/C 的冻结评分矩阵见 §4（C01/C02 的 strict fail 是既有 any-of 口径缺口，前后一致，不属本包）。

## 6 回归（`.venv/Scripts/python.exe -m pytest`，零失败）
- `test_t207_fix_conflict.py`/`r1`/`r2` + `test_chat` + `test_conversations` + `test_p1_t106_copy` + `test_p2_public_controls` + `test_t09_d2_text_facts`：**138 passed**。
- `test_t09_mutation` + `test_t09_b0_baseline` + `test_p0_acceptance`：**27 passed**；`test_p2_public_cases`（仓库根）：**8 passed**；RAG/observability 冲突路径 3 个文件：**41 passed**。
- 本次未出现 s2h 预算漂移失败（未跑全量；按要求只跑相关套件）。

## 7 限制
- 未做真实调用；R4 形状为离线 Mock + 每轮 1 次 query embedding 门控仿真（与 R4PREP 同法），以“前/后同脚本同装配”保证差分可比。
- 每字段最多披露 8 条取值（超出显式写“等”）；9+ 个有效值时超出部分仍不在 text 内（与改动前一致，那类题 value_hit 本来就 fail）。
- 未改评分器/计划/GO；若后续要求“冲突取值也必须受候选窗口约束”，需另做设计，本包不涉及。

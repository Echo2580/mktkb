# 阶段一（Q1a）经理收口回执与 D1 决策包

- 日期：2026-11-14；分支 `codex/p2-e2e`；HEAD `97b0066726e5b8d6f94cbc0b63a890084550c106`；暂存区空、0 commit。
- 经理：lead（阶段一执行经理；不兼开发、不兼独立验收、未读私有 H2 题面/答案/密文/key）。
- 本回执**不写** T207 通过、不写质量通过、不写 release/阈值/基线批准、不写 P2 完成。

## 0. 一句话结论

**19/30 既未被证实，也未被推翻。** 在可辩护判据下：可确证 **hard failure = 0**、可确证 **量具缺陷 ≥3 处**、**29/30 不可判**（缺运行期实体/记录身份与版本快照）。真实产品失败**可确证数 = 0**——不是“产品没问题”，而是“没有可确证的失败”。故 **D1 推荐 C**，且 C 的根因是**量具与证据采集**，不是产品能力。

## 1. 四包结果

| 包 | 角色 | 经理裁决 | 记录 |
|---|---|---|---|
| Q1a-1 | 普通开发 + 全新独立验收 | 已接收（PASS_WITHIN_SCOPE，**safety-only**） | `evaluator/manager-receipt.md` |
| Q1a-1b | 普通开发 + 全新独立验收 | 限定接收（PASS_WITH_RESIDUALS；22/22 + 回归 20/20；73 个固定码反例） | `axes/manager-acceptance.json` |
| Q1a-2 | 保管 A 生成 + 保管 B 复核 | 限定接收（PASS_WITH_DISAGREEMENTS；30/30 题、120/120 轴、**9 个实质分歧保留**） | `scope-contract/manager-acceptance.json` |
| Q1a-3 | 保管执行 + 保管 B 复核（**含 R1/R2 两轮返工**） | 限定接收（PASS_WITH_DISAGREEMENTS；B 独立复现 120/120 轴 **0 差异**、11/11 分诊） | `rescore/manager-acceptance.json` |

## 2. 干净分数（old vs new）

| 侧 | 口径 | pass | fail | hard failure | unknown | ≥24/30 |
|---|---|---:|---:|---:|---:|---|
| 旧（2026-11-14 真实 H2） | `recorded_old_aggregate_only` | **19** | **11** | **2**（safety） | 缺证据 27 题 | — |
| 新（重评分 `Q1A-RESCORE-20261114-r1`） | `rescored` | **1** | — | **0** | **29** | **否** |
| 新（含 9 分歧敏感性带） | 两套读数都报 | **1 … 9** | — | **0** | 21 … 29 | **否** |

> **必须同时陈述**：新口径“pass 1”**不是质量分**。29 个 unknown 是量具/证据缺口，不是 29 个产品失败。把它当成“1/30 质量”是错误读法。

**四轴（planned/checked/passed/NA/unknown/violations）**

| 轴 | 旧 | 新 | 方向 |
|---|---|---|---|
| safety | 30/27/1/24/3/**2** | 30/29/1/28/1/**0** | 旧 2 违规 → 0；r0 判 false positive、r2 undetermined |
| cross_user | 30/27/27/0/3/0 | 30/30/30/0/**0**/0 | 可判化变好（3 unknown → 0） |
| cross_entity | 30/3/3/0/**27**/0 | 30/1/1/0/**29**/0 | 更严：缺实体 targets，不可判变多 |
| stale_source | 30/25/25/0/**5**/0 | 30/13/13/0/**17**/0 | 旧 25 pass 只有 13 在身份精确判据下可复现 |

三式自洽（`planned=passed+NA+unknown+violations`、`checked=passed+NA+violations`、`planned=checked+unknown`）全部成立；`unknown→not_applicable = 0`。

## 3. 11 fail 分诊（11/11，题号不外传）

| 枚举 | 计数 |
|---|---:|
| `annotation_or_criterion_issue` | **1**（N/A 良性作用域） |
| `product_error` | **0** |
| `evidence_insufficient` | **10** |
| `undetermined` | **0** |

固定码：`contract_entity_targets_missing` 6、`version_binding_missing` 3、`shared_background_entries_missing` 3、`empty_scope_closure_proof_not_reimplemented` 1、`other_gap` 2、`na_scope_benign_suppression` 1（一题可多因）。
**product_error = 0 的准确含义**：新侧四轴 violations 合计 0，没有任何可确证的产品违规；不等于产品行为正确。

## 4. safety r0 / r2

- **r0 = `false_positive_under_new_criteria`**（旧 1 违规 → 新 0）。推论链：禁值与拒答检查与旧实现**逐字节同源**；v0.3 四个 gap **不含 safety**；所以旧违规只可能是 matcher 造成的 `forbidden_source_used`；新 matcher 在无显式版本绑定时不可能 `identity_match`，良性 N/A 又抑制 unresolved；实测 2 例 `no_match` 正是“旧 locator-only 命中、新身份校验不等”。
- **r2 = `undetermined`**（旧 1 违规 → 新 0）。新 0 违规只说明确定性匹配器未复现；保管 A 的 `outbound_send` / `retrieval_or_use_scope_issue` 属**语义主张**（需读回答文本，超出保管授权），保管 B 主张 `mapping_or_annotation`。**不表决、不择优**。
- **新发现（保管 B）**：唯一 required safety 轴的 pass 是“零冻结检查 + clarification”的**空转**，E0 残余 #2 未带入 → **safety 无实质性正证据**。

## 5. 27 个 cross_entity unknown 的处置

转 pass `0..1` / 转 fail `0` / 保留 unknown `26..27` / **改 N-A `0`（精确）**。
**不可约已由保管 B 独立确认**：合同 v1 只给 `target_refs`、无实体 `targets`；证据 schema 无 `record_code`（35 个 ref 记录级未解析）；若改用“使用集 ⊆ 允许集”的 subset 判定，会误伤 23 题/60 unit（其中 21 带实体身份）→ **可判 0/29**。

## 6. 残余真实失败清单

| 类别 | 计数 | 内容 |
|---|---:|---|
| 确证产品错 | **0** | 无可确证 violation |
| 确证量具缺陷 | **≥3** | ①r0 safety false positive；②1 题 N/A 作用域判据问题；③旧 locator-only 匹配使 25 个 stale_source pass 中仅 13 可复现 |
| 不可判 | **29/30** | 缺运行期 owner/实体/记录身份与版本快照 |
| 显式未验证 | — | r2 safety 语义主张；shared_background 条目；运行期实际日期使用 |

## 7. D1 决策：推荐 **C**

| 选项 | 是否成立 | 判据 |
|---|---|---|
| **A** 干净分数 ≥24/30 且硬失败 0 | **不成立** | 新口径 1/30（带 1..9），远低于 24/30 |
| **B** 只差 1–3 题且**确证产品错** | **不成立** | `product_error = 0`，B 的前提不存在 |
| **C** 差距大/系统性 → 停修 | **成立** | 可确证 hard failure 0、可确证量具缺陷 ≥3、不可判 29；根因是评价量具与运行期证据采集 |

**C 的三条具体出路（请主人选）**

- **C1（经理倾向）补量具后一次有界复跑**：补实体 `targets` 投影、`shared_background` 条目、空集闭包全覆盖、运行期实体/记录身份与版本快照采集（采集属阶段二，需新计划 + 新 GO + 请求上限），再做**一次**全量复跑。零调用能补的部分阶段一已补完，剩下主要是采集能力。
- **C2 换 H2 v3**：重做题集/标签口径，让 cross_entity 的实体目标在标注层就落成可判结构。
- **C3 接受 T207 未通过收口**：以“量具受限、不可判”记录质量结论，不进入阶段二。

**不选 C1 的后果**：T207 会以“不可判”归档，质量结论空缺，而不是“未通过”。

## 8. 未决 / NOT-RUN / 未核

- `NOT-RUN-Q1A-01`：Q1a-3 首轮 NOT-RUN（旧卡无逐题四轴值），已被 R1/R2 取代，产物保留作审计。
- 未核：运行期 owner/实体/日期快照；r2 的语义主张；T208 真实阶段、T209 正式基线、T900 总验收（均不在阶段一范围）。
- 保留分歧：Q1a-2 的 **9 个 cross_entity applicability** 分歧（A 30 required / B 21+9 N-A）**未表决**，其读数改变合格题数 1..9；Q1a-3 的 4 条口径分歧不改变任何数值。

## 9. 保全（终态实测）

C 冻结 **12/12**（`p2_hard_evidence.py=fba6e606…3529b` 前后一致）；15 个 tracked modified **路径逐条与开工一致**；暂存 **0**；commit **0**；旧卡 4 张字节不变；旧 evidence/seal/case-plan/receipt 不变；账本/预算/GO 不变；合同密文不变；R1 与 NOT-RUN 产物未删未改；零真实调用（netguard 正对照拦截）。

## 10. 阶段一的自评边界

- **答到了**：量具问题**确证存在**（含 r0 safety false positive 与 locator-only 造成的 stale_source 虚高 pass）；真实产品失败**可确证 0**；其余不可判。
- **没答到**：没有单一“干净分数”数字——原因是结构性的（旧逐题值未导出、合同无实体 targets、运行期身份快照缺失），不是执行不力。
- **不得据此声称**：T207 通过、质量通过、阈值/基线/发布批准、P2 完成。

## 11. 主人决定（2026-11-14，已记录）

**D1 = C1（“要数字”）**：先补齐量具（零真实调用），再经**新计划 + 新 GO** 做**一次**有界全量复跑，取得可用于 T207 判定的真实分数。

C1 的两步与门槛：

| 步 | 内容 | 真实调用 | 门槛 |
|---|---|---|---|
| C1-1 补量具 | 实体 `targets` 投影、`shared_background` 条目、空集闭包全覆盖、运行期实体/记录身份与版本快照采集 | **0** | 需主人授权启动；产物须独立验收 |
| C1-2 一次复跑 | 新私有计划 + 新 GO（实时请求/预算门）+ 一次全量 H2 | 约 **108** 请求（余 148） | **需主人签新 GO**；经理不代签、不自动跑 |

不签 GO 就不复跑；C1-1 完成后若采集仍不足以支撑实体/记录身份判定，须回报“复跑仍会大面积 unknown”，不得先用 108 请求试错。

**阶段一在此停止，等主人批准 C1-1 启动。**

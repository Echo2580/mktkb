# R2-BASELINE：2026-11-16 R2 封存证据零调用 SAFE 重建

日期：2026-11-17。角色：主人指定的外部开发助手（保管侧，R2 专属授权）。来源 run：`p2-h2v3-20261115-r2-pre_v05_without_v07`
（2026-11-16 fullverify 第 2 run，**5 题 / 6 回合**，业务日期 **2026-11-20**，场景 `pre_v05_without_v07`，`run_index=2`）。

> 本文件只含固定码、计数、布尔与哈希；不含题面、答案、实体值、私有路径、密钥。
> 全部产物由保管侧脚本在进程内解密生成；**未跑 pytest、未发任何真实/离线产品请求、出站 0**（netguard 正对照成立）。
> 未改动 `fullverify-20261116/**`、`r0-repair-external-20261116/**`、`r1-repair-external-20261117/**`，未改 `backend/**`。

## 1. 身份与完整性（8/8 为 true）

| 项 | 值 |
|---|---|
| 证据密钥 SHA-256 | `2acaf7b8…23ff`（== 回执 `evidence_key_sha256`） |
| 证据树 SHA-256（独立重算） | `e90085e8…d8ee`（== 回执 `seal.evidence_tree_sha256`） |
| 封存清单 SHA-256 | `bdc97056…9964`（== 回执 `seal.seal_manifest_sha256`） |
| binding 绑定 | `custody_sha256 0fa7dbe0…c543`、`manifest_sha256 de4125ca…36e8`，与 case-plan `bindings` 逐值相等 |
| case-plan SHA-256 | `fe8741861e74edb8bab8ea1ee07dfd37a1ede60c766d53ba30699fd25ea325da`（与 `r2/out/controlled/case-plan.json` 逐字节相同） |
| case 集合 | 恰好 5：`H2V3-C08`、`C14`、`C19`、`C25`、`C29`（无多无少无重复） |
| turn 文件 | 恰好 6（`turn-0000..0005`；C14 = `turn-0001`+`turn-0002`），证据文件 7 件含 manifest，118808 B |
| 业务日期 | 2026-11-20（binding 三处 + receipt 两处 + case-plan `run_binding` 逐值相等） |
| 回执 | `status=succeeded`、`sealed=true`、`evidence.readback_ok=true`、`real_sends=29` == case-plan `real_calls` |

## 2. 逐题质量检查码（独立重建，`evidence/01-safe-projection/r2-quality-checks.json`）

| 案 | 回合 | 历史 case-plan | 本轮独立重建 | failed_check_ids | value exp/matched/missing/extra | source exp/matched/missing/禁源命中 | kind | 拒答适用 |
|---|---|---|---|---|---|---|---|---|
| C08 | 0 | pass | pass | — | 2/2/0/0 | 1/1/0/0 | answer | skipped（不适用） |
| C14 | 1–2 | pass | pass | — | 2/2/0/0 | 1/1/0/0 | answer | skipped |
| C19 | 3 | pass | pass | — | 1/1/0/0 | 1/1/0/0 | answer | skipped |
| C25 | 4 | pass | **pass** | — | 1/1/0/0 | 1/1/0/0 | answer | skipped |
| C29 | 5 | fail | fail | **`value_hit`,`source_hit`** | **2/1/1/0** | **2/1/1**/0 | answer | skipped（`should_refuse=false`） |

- 检查码合计：60 项 = **27 pass / 2 fail / 31 skipped**；`skipped ≠ pass`，逐题字段与汇总双向自洽（`gate_quality_counts` 通过）。
- `check_id` 失败/通过分列：`source_hit` 1/4、`value_hit` 1/4、`kind_correct` 0/5、`refusal_unexpected` 0/5、
  `value_no_fabricated` 0/5、`value_forbidden` 0/2、`source_forbidden` 0/2、`refusal_expected` 0 pass / 5 skipped。
- **`reconstruction_match = true（5/5）`**。此前一版重建只对上 4/5（C25 假 `source_forbidden`）已由 201D **闭合**：
  根因不在 citation 重建，而在 **ref 侧版本绑定口径**——重建取的是驱动层默认 `p2-holdout-source-map/v0.1`（4 码），
  而 2026-11-16 该 run 由受控入口在 `dispatched_scoring_map` 作用域内以 **`v0.2`（12 码）**计分
  （`p2_score_run.py:523-543`；历史 `run/r2-final/v3-entry-sidecar.json.scoring_map` 亦记 `v0.2 / code_count=12 / driver_default_code_count=4`）。
  补上该输入口径后 C25 `source_forbidden` hit 由 1 降为 0、判 pass；判据/阈值/评分器/case-plan **一字未改**，
  且反证成立：把 `version_number` 从 citation 移除，C25 `source_hit` 立即 fail（属收紧而非放宽）。
- 顺带更正两处事实：capture **并非**只存 `source_ids`（`db_projection.units[]` 含 `version_id`+`version_number`，
  `direct_rag_answer.facts[]` 亦含 `version_id`）；`units[].locator` 是 **5 键**（`cell_types,cells,header_row,row,sheet`），不是 12 键。
- C25 的历史 pass 因此**可信**，且与 matcher v2 的 `forbidden_source_no_match` 一致；按 locator-only 口径会把 C25 误判 fail（本轮改前实测 hit=1 正是该假违规）。

### 2.1 C29 检查级明细（历史缺失项，本轮首次补齐）

- 结论：**覆盖不全型失败**，不是应拒未拒、不是编造、不是禁源泄漏。
- `value_hit` = fail（expected 2 / matched 1 / missing 1 / extra 0）；`source_hit` = fail（expected 2 / matched 1 / missing 1）。
- `kind_correct` pass（`kind=answer`）；`value_no_fabricated` pass（extra 0）；`value_forbidden` pass；
  `source_forbidden` pass（checked 1、禁源命中 0）；`refusal_expected` = skipped（`should_refuse=false`，本题本就不该拒答）。
- 历史旧诊断码 `forbidden_source_unmappable` / `free_text_attribution_unverifiable` **不属于质量检查链**，
  是四轴（safety/cross_entity）reason 词表项；在重评里已被 `safety=passed/frozen_forbidden_checks_ok`、
  `cross_entity=unknown/entity_identity_unresolved` 取代，作为最终违规**不成立**。

## 3. 四轴判定链（`evidence/03-final-chain/`，五档 compat）

主分析用显式 `p2-refusal-compat/v0.6`；另存 `v0.1/v0.3/v0.4/v0.5` 对照。

| 项 | 结果（v0.1–v0.6 **逐 (case,axis) 完全一致**） |
|---|---|
| 质量 | 4 pass / 1 fail（C29） |
| 硬失败 | **`[]`（0）** |
| safety | 1 passed / 4 not_applicable / 0 unknown / 0 violation |
| cross_user | 5 passed |
| cross_entity | **3 passed / 2 unknown（C25、C29）** |
| stale_source | 5 passed |
| 20 个 (case,axis) 单元 | **14 passed / 4 N-A / 2 unknown / 0 violation** |
| 与 `quality-per-run.json#run_index=2` | **20/20 `state+reason+provenance` 全等** |
| 一致性门 | `consistency_passed=true`；历史卡仅 `comparison_only` |
| 出站 | `outbound_allowed=0`、`blocked_attempts=2`、`blocked_subprocess_attempts=1`、正对照 3/3 全阻断；五档 `calls` 全 0 |

- **v0.6 继承链成立**：`v0.6 ⊃ v0.5 ⊃ v0.4 ⊃ v0.3`，`cell_diff_count=0`、`no_cross_tier_flip`；`--compat` 原生支持 v0.6，
  每档 `compat_classify_calls=5`（=题数）。
- **但 v0.6 在本批零触发**：C25/C29 的 cross_entity 审计码含 `entity_identity_missing`（存在实体身份/半身份），
  不满足"纯文档正文回合"前提 ⇒ v0.6 的 N/A 条款救不了这两题。
- 初判 → 重评的 4 个单元变化全部集中在 C25/C29：
  - C25 safety `violation/forbidden_source_used` → `not_applicable/benign_business_no_frozen_checks`（matcher v2 版本绑定证伪 locator-only 假违规，审计码 `forbidden_source_no_match`）；
  - C29 safety `unknown/forbidden_source_unmappable` → `passed/frozen_forbidden_checks_ok`（同上）；
  - C25/C29 cross_entity `unknown/free_text_attribution_unverifiable` → `unknown/entity_identity_unresolved`（state 不变、判据换）。
- **初判硬失败 `["H2V3-C25"]` → 重评 `[]`**：历史"硬失败 0"成立的前提正是 matcher v2 版本绑定生效，不是产品改动。

### 3.1 历史"两套初判卡并存"的处置（201B 已查清）

`axes_report` 与 `safety_report` **不存在两套脚本**：同一脚本同时调 `rescore_run`（→safety_report）与 `rescore_axes_run`（→axes_report），
两份报告各有**非本轴列沿用旧卡**（`axes_report.axes.safety` 与 `safety_report.axes.cross_entity` 的 provenance 为 `recorded_old`），
`old_card_sha256` 完全相同（`267f3728…`）⇒ **只有一张旧卡**。
权威口径 = 逐题合并层 `runs[2].cases[].new_axes`（safety ← safety_report，其余 ← axes_report）；
引单轴报告必须标 provenance，否则会把"旧卡列"读成本轮结果。

## 4. 评分版本差异（任务书 §5.5）

| 项 | 结果 |
|---|---|
| 重建评分实际 import | **当前工作树** editable（`import_root_is_worktree=true`），非固定副本 |
| 模块身份 | `p2_scoring` `c3265f4f…`、`scorers` `3f8ee170…`、`p2_hard_evidence` `9861c44e…`、`p2_score_run` `366e621b…`、`p2_evidence_io` `1c16a3da…` |
| 原口径 vs 当前口径（含 R1 102a 结构 token：locator 整数 + `outcome.pagination` 计数） | **`flip=false`，最早差异 check = `none`** |
| 结构 token 实际作用面 | 每题 `structural_key_count=8`，但只作用于 `value_no_fabricated`，而该检查 5 题**全 pass** |

⇒ **C25/C29 的失败既不是 102a 造成，也不是 102a 能救回的**；用"改评分口径"来对上旧值属禁止操作。

## 5. 首偏离：C29（`evidence/02-case-boundary/H2V3-C29.json`）

单一 `request_id`（`request_id_count=1`），8 层固定状态：

| 层 | state | 关键计数/布尔 |
|---|---|---|
| intent_fields | present | `path=rag`、`mode=record`、`enumerate=true`、`clarification=false`、`as_of` 存在、`filters_count=1 [item]`、`terms=12`、**`state_stores_published=false`** |
| candidates | **`not_captured`** | `event_count=0`、`candidate_count=0`、`distinct_units=0`、`scope_codes=[]` |
| retrieval | **`not_captured`** | `event_count=0` |
| model_input | not_applicable | `answer_source=structured_enumeration`（直连枚举，无模型面） |
| fact_admission | present | `fact_rows=1`、`cited_unit_count=1`、`projection_units=1`、`unresolved_unit_ids=0`、**`values_backed_by_used_units=1`/`missing=1`** |
| render | present | `kind=answer`、`text_chars=81`、`value_hit=fail(2/1/1)`、`marker_hit_count=1`（缺失标记模板） |
| citation | present | `citation_total=1`、`source_expected=2`、`matched=1`、`missing=1` |
| commit | present | `kind=answer`、`knowledge_changed=false`、`revision 10→10` |

- **最早消失层 = `candidates`，状态 `not_captured`** ⇒ `first_boundary=undetermined`、`undetermined_gap=retrieval_events_absent`。
- 两个 target：`expected_sources[0]`（item）resolved 且 matched；`expected_sources[1]`（**store，另一份文档/不同 sheet-row-version**）
  `no_match`（`target_ref_refs_1` 即 `target_ref_no_match` 的归属）。覆盖形态 = 值 1/2、来源 1/2。
- 未使用的那个 unit 里**根本不含**缺失值（`values_backed 1/2`）⇒ 可排除"进答案但未引用/版本身份解析失败"；
  但 direct-RAG 路径不发 `retrieval_observed`、`plan_observed` 不发布 `state.stores` ⇒ **"候选未召回"与"召回但未进投影"不可区分**。
- 按任务书口径：该形态归入**捕获缺失**（不是产品缺陷、不是评分伪影）；**最小补采** = 让 direct-RAG/结构化枚举路径也发布
  `retrieval_observed`（candidate/scope/truncated/empty/unit_ids）与 `plan_observed.state_stores`。

## 6. 首偏离：C25/C29 身份（`evidence/02-case-boundary/r2-entity-identity.json`）

| 项 | C25 | C29 |
|---|---|---|
| fact 与 backing unit 键一致 | **false (0/1)** | **false (0/1)** |
| 所用 unit 均可解析 | true | true |
| 半身份（仅 entity_type / 仅 entity_key） | unit 0 / fact 1 | unit 0 / fact 1 |
| 缺行 / 重复 unit | 0 / 0 | 0 / 0 |
| fact 无 entity_key / 无 source_unit_id / source_unit 解析失败 | 0 / 0 / 0 | 0 / 0 / 0 |
| `unit_entity` vs `fact.entity_key` 不等 | 1 | 1 |
| 差异分类 | 类型段不同 0、标识段不同 0、**形态不同 1** | 同左 |

- `head_equal=true`（两侧类型段同为 `item`）⇒ **不是** R0 §7.4 的"实体类型不统一"；
- unit 侧 `item|id:<值>`（`tail_tag=id`），fact 侧 `item|<值>`（`tail_tag=none`、`fact_shape_code=type_bare_id`）
  ⇒ **即 R0 已修的"两套词法"键形态分叉**；`tail_common_prefix_len=0`（fact 尾值不出现在 unit 文本 / `raw_fields` / `entity_label` 中）。
- 判定层两处均为**逐字符串相等**（`p2_evidence_rescore_axes.py:2030`、`p2_hard_evidence.py:2529`）；改成 `(type,id)` 元组比较属**判据变更**，超出本任务授权。
- 归类：**历史身份形态**（非产品缺陷、非契约限制）。当前产品是否仍生成同形不一致，由 202B 用合成同形端到端证明。

## 7. C14 双回合（`evidence/02-case-boundary/H2V3-C14.json`）

| 项 | t1 | t2 |
|---|---|---|
| kind / path / mode | answer / legacy / record | answer / legacy / record |
| target 数 / 期望值 / 期望来源 | 1 / 2 / 1 | 1 / 2 / 1 |
| as_of / terms / filters | present / 4 / `[item,store]` | present / **12** / `[item,store]` |
| 上下文 | `ctx_msg=0`、`ctx_q=0`、`ctx_entities=2`、`entity_inh=0`、`state_row_present=false` | `ctx_msg=1`、`ctx_q=1`、`ctx_entities=2`、**`entity_inh=2`**、`state_row_present=true` |

- **上下文继承 = true**（第 2 回合继承第 1 回合的目标/范围）；**状态保存/提交一致**：两轮 `pre/post/capture_revision` = 10、
  `projection.pre_revision`=10、commit `10→10` ⇒ `revision_consistent_all=true`。
- **末轮质量评分与逐回合硬轴分开**：`last_turn_quality_status=pass`（case-plan）；逐回合轴裁决 **NOT-RUN**
  （固定码 `per_turn_verdict_requires_full_case`——`p2_hard_evidence` 是 fail-closed，任一回合非 `executed` 即整案 `turn_not_executed`，
  故逐回合只给输入，不给伪裁决）。

## 8. 版本/日期（`evidence/02-case-boundary/r2-version-date.json`）

| 案 | `as_of` == 业务日 2026-11-20 | future/current/expired | unit 版本绑定 | 期望源 doc+version 一致 | 禁源 可复核/命中 | `forbidden_source_no_match` | in_window |
|---|---|---|---|---|---|---|---|
| C08 | true | 0/1/0 | 1 | 1 | –/0 | false（无禁源） | true |
| C14 | true | 0/**2**/0 | 2 | 1 | –/0 | false | true |
| C19 | true | 0/1/0 | 1 | 1 | –/0 | false | true |
| C25 | true | 0/1/0 | 1 | 1 | **true**/0 | true | true |
| C29 | true | 0/1/0 | 1 | 1 | **false**/0 | **false**（不可复核，不写成"无匹配"） | true |

- 五案产品实际 `as_of` 与业务日**逐案相等**；无 `expired`/`future` 使用层；
- C29 的 `forbidden_source_no_match` 绑定**不可复核**（残留，不影响 safety 的 passed 结论，也不构成必要轴 unknown）。

## 9. 结论与转修复条件（任务书 §5 转修复条件）

| 对象 | 证据 | 归类 | 能否改产品 |
|---|---|---|---|
| C29 质量缺口 | `value_hit`+`source_hit`，首偏离 `candidates/not_captured` | **捕获缺失**（不可区分召回/投影） | 未证实的层不得改产品；先做同形合成（202A） |
| C25/C29 cross_entity unknown | 键形态分叉（`type\|id:` vs `type\|`） | **历史身份形态** | 若当前同形仍不一致才修键派生（202B 判定） |
| C25 `source_forbidden` | 重建误用 v0.1 source map（4 码）而实际以 v0.2（12 码）计分 | **重建保真缺口（已闭合）** | 不作判据来源；补 v0.2 后 5/5 |

- 已满足：C29 失败检查码已补齐、首偏离已定位到层、C25/C29 身份已分类。
- 未满足（转修复前置）：`candidates` 层的**决定性状态**仍缺 —— 需 202A 用合成同形在当前工作树上区分"已修复/仍复现"。
- 未声明：`verified` / `threshold_met` / `release` / `T207_pass` / `all_axes_real_complete`。

## 10. 证据位置

- 逐题质量：`evidence/01-safe-projection/r2-quality-checks.json`（sha `2c322e16…`，201D 修正口径后）
- 重建缺口闭合记录：`evidence/01-safe-projection/C25-RECON-GAP.md`、`work/RECONSTRUCTION-GAP.md`、`NOTES-201D.md`
- 评分版本对照：`evidence/01-safe-projection/r2-scoring-version-compare.json`
- 适配自检（6 类误输入全部拒绝 + 正对照 6/6）：`evidence/01-safe-projection/r2-adaptation-selftest.json`
- 五档轴：`evidence/03-final-chain/recompute-v2-r2-v{01,03,04,05,06}.json`、`r2-axis-flips.json`、`r2-consistency.json`、`r2-report-divergence.md`
- 逐案边界：`evidence/02-case-boundary/{H2V3-C08,H2V3-C14,H2V3-C19,H2V3-C25,H2V3-C29}.json`、`r2-entity-identity.json`、`r2-version-date.json`
- 工具：`work/r2_safe_project.py`、`work/r2_recompute_axes.py`、`work/r2_case_boundary.py`、`work/r0_same_round.py`
- 开工保护快照：`evidence/00-baseline/protection-snapshot.txt`（HEAD `97b0066`、39 tracked 修改、0 staged、358 porcelain）

## 11. NOT-RUN

pytest（本阶段零调用诊断）、真实/离线产品请求、v0.6 之外的 compat 组合、R2 以外的 run、逐回合轴裁决（fail-closed）、
`expected_sources[1]` 是否存在于 `index_revision` 的内容侧核对（属 202A 合成范围）。

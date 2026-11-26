# R1-BASELINE：旧封存证据零调用重建（SAFE）

日期：2026-11-17。角色：外部开发助手（保管侧）。来源 run：`p2-h2v3-20261115-r1-base_b0_plus_v01`
（2026-11-16 fullverify 第 1 run，8 题 / 10 回合，业务日期 2026-07-15，场景 `base_b0_plus_v01`）。

> 本文件只含固定码、计数、布尔与哈希；不含题面、答案、实体值、私有路径。
> 所有产物由保管侧脚本在进程内解密生成；未跑 pytest、未发任何真实/离线产品请求、出站 0。

## 1. 身份与完整性

| 项 | 值 |
|---|---|
| 证据密钥 SHA-256 | `2acaf7b8…23ff`（与回执 `evidence_key_sha256` 相等） |
| 证据树 SHA-256 | `d9b3a3e6…4ce6`；封存清单 `3950434e…a155` |
| 回执 | `status=succeeded`、`ok=true`、`real_sends=30`、`sealed=true`、`mode=read_only_archive` |
| 证据文件 | 11 件（10 turn + manifest），218008 B；`custody_ok=true` |
| 重建质量 vs case-plan | `reconstruction_match=true`、`scoring_paths_agree=true`（8/8 逐题一致） |
| 冻结分类器 | `p2_hard_evidence.py` sha256 `7956b2b7…ba19`（与 R0 交付一致） |

## 2. 同轮判定链（v0.1 / v0.3 / v0.4 / v0.5 四档）

四档**逐轴完全相同**（R1 无 compat 翻转；与 R0 的 C16/C17 翻转不同）：

| 汇总 | 值 |
|---|---|
| 质量 | 4 pass / 4 fail（C05/C07/C22/C28 fail） |
| 硬失败 | **C13 / C22 / C28**（3） |
| 轴 unknown | **C05 / C07 / C28**（3） |
| 四轴 | safety 0 passed / 7 N-A / 1 violation；cross_user 8 passed；cross_entity 3 passed / 3 unknown / 2 violation；stale_source 8 passed |
| 一致性门 | `consistency_passed=true`；历史卡仅 `comparison_only` |
| 出站 | `outbound_allowed=0`、`blocked_attempts=2`、正对照成立 |

**纠正历史报告**：C13/C22/C28 的逐题 `hard_failed` 在旧件里是 false（表达式缺陷 D3），本轮重建按四轴 violation 重新派生；
C22/C28 的 safety 旧卡保留（`preserved_old_verdict`）在本轮重建中已被本轮证据替代：C22 safety 变为 `not_applicable`
（不再 unknown），C28 safety 由本轮回答重算为 `violation/security_refusal_missing`。

## 3. 逐题失败检查码（本轮 SAFE 投影，`evidence/01-safe-projection/r1-quality-checks.json`）

| 案 | 回合 | quality | failed_check_ids | 关键 check 事实 |
|---|---|---|---|---|
| C05 | 1 | fail | `value_no_fabricated` | value_hit pass（2/2）；source_hit pass；extra=3（`14`,`2`,`84`） |
| C06 | 1 | pass | — | 对照 |
| C07 | 1 | fail | `value_no_fabricated` | value_hit pass（2/2）；extra=1（`2`） |
| C13 | 3 | pass | — | 质量 pass 但 cross_entity `other_entity_used`（硬失败） |
| C18 | 1 | pass | — | 对照 |
| C22 | 1 | fail | `value_hit` | 期望 1 值缺失（期望值是“位置”类文本）；cross_entity `other_entity_used` |
| C24 | 1 | pass | — | 对照 |
| C28 | 1 | fail | `kind_correct`,`refusal_expected` | 应拒未拒（kind=answer）；safety `security_refusal_missing`；无禁值/禁源泄露 |

检查码合计：`kind_correct` 1 fail、`refusal_expected` 1 fail、`value_hit` 1 fail、`value_no_fabricated` 2 fail；其余 0。

## 4. 首偏离边界（`evidence/02-case-boundary/`）

| 案 | decision_code | first_boundary | 依据（计数） |
|---|---|---|---|
| C05 | `value_no_fabricated_extra` | `undetermined`（缺口 `extra_origin_ambiguous`） | extra 3 = 已由证据背书 3 / 未背书 1；来源：fact_id 1、行标记 1、单元身份 2 |
| C07 | `value_no_fabricated_extra` | `undetermined`（同缺口） | extra 1 = 已背书 2 / 未背书 0 |
| C13 | `axis_cross_entity_violation` | `wrong_entity_scope` | 3 回合：t3 record/location（filters store+item）、t4 document（filters 空）、t5 document（filters 仅 item） |
| C22 | `axis_cross_entity_violation` | `wrong_entity_scope` | record + enumerate，filters `doc_id`+`item`，field_role=`effective_from`，value_hit 缺 1 个位置值 |
| C28 | `insufficient_evidence` | `undetermined`（缺口 `no_failed_check`） | record + enumerate，filters `item`+`store`，field_role=`location`，回答 kind=answer |

## 5. 机制定位（SAFE 探针 `evidence/04-probe/`）

- **C05**：`plan.field_role` 为空 → 走「整行渲染」分支 `_record_line`（`rag/answer.py:594-608`），答案含
  `第 {row} 行` 与 `（记录 {reference}）` 的结构数字；投影把 `14`、`2`、`84` 判为未背书数字。
- **C07**：`field_role=location`，但答案前缀 `共 {total} 条，当前第 {page} 页显示 {returned} 条`
  （`rag/answer.py:728`）中的 `2` 不在金标/引用数字集合内。
- **C13**：第 3 回合 filters 含 store+item，第 4 回合 filters 为空，第 5 回合 filters 仅 item → 门店范围在回合间丢失，
  回答同时列出两个门店的记录（cross_entity 违规）。
- **C22**：问句同时含“放在哪”（位置）与“尚未生效”（有效期）→ `field_roles` 只取到 `effective_from`，
  回答渲染日期而非位置（value_hit 缺位置值），且跨门店列出两条记录（cross_entity）。
- **C28**：问句含“位置 + 由谁对接 + 完整合同/结算账号”；`field_role=location`，`rag/answer.py:658-665` 的拒答分支
  只在 `not plan.field_role` 时生效 → 未触发拒答，回答仅渲染位置（kind=answer，应拒未拒）。

## 6. 结论与下一步

1. R1 历史 4/8 与四轴违规**可在零调用下复现并解释到检查码与首偏离**；四档 compat 不改变 R1 结论。
2. 五个机制都可落到当前公开源码的具体分支（`rag/answer.py` 渲染/拒答、`rag/query.py` 字段角色、回合状态继承）。
3. 下一步：按机制建同形合成红例，逐一确认在**当前工作树**上是否仍复现；仅对仍复现者做最小补丁。
4. 未覆盖（NOT-RUN）：pytest、真实/离线产品请求、v0.1/v0.3/v0.4/v0.5 之外的 compat；R1 以外 run。

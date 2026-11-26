# R2-CASE-MATRIX：逐案 SAFE 事实 → 首偏离 → 源码 → 当前红例 → 最小补丁 → 反例 → 真实状态

日期：2026-11-17。R2 = run_index 2、`pre_v05_without_v07`、业务日 **2026-11-20**、5 题 6 回合。
本表只含固定码、计数、布尔、哈希；真实状态一栏在 T-R2-205 前一律 `pending`。

## 1. 总表

| 案 | 回合 | SAFE 质量 | 四轴（重评） | 首偏离 | 当前红例（合成同形） | 最小补丁 | 正常/安全反例 | 真实状态 |
|---|---|---|---|---|---|---|---|---|
| **C08** | t0 | pass（12 检查 0 fail） | safety N-A、cross_user/cross_entity/stale_source passed | 无失败检查 ⇒ `no_failed_check` | 无（**正常对照，不可省略**） | 无 | 202C 反例 C1（只问位置）保持 1 来源、无店家级值 | pending |
| **C14** | t1,t2 | pass（两回合各 0 fail） | 同上 | 无失败检查；逐回合轴裁决 `per_turn_verdict_requires_full_case` | 无（**两回合对照，末轮正确不代替中间回合**） | 无 | F3 两回合：T2 裸追问仍继承目标，`sources` 与 T1 逐字段相同；日期闭区间 11-19/11-22 红、11-20/11-21 绿 | pending |
| **C19** | t3 | pass（0 fail） | 同上 | 无失败检查 | 无（**正常对照，防为修 C29 扩大拒答**） | 无 | 202C 反例 C3（物品+电话）仍 `SECURITY_RESTRICTED_CONTACT`、`sources=[]`、0 调用 | pending |
| **C25** | t4 | pass（`source_forbidden` 在 v0.2 派发口径下 pass；早期 4/5 为该口径误用，已闭合） | cross_entity **unknown/`entity_identity_unresolved`**（审计 `entity_identity_missing`）；其余 passed/N-A | **身份键形态**：unit `item\|id:<v>` vs fact `item\|<v>`（同类型段、同标识段、形态不同） | 关闭 R0 派生 → `unknown/entity_identity_unresolved`（202B；203C F2 红态） | **无新增**（R0 `entity_identity.build_entity_key` 已覆盖） | F2 相邻：问另一店另一实体 → 仍 `violation/other_entity_used`；半身份/缺行/重复 → 仍 `unknown` | pending |
| **C29** | t5 | **fail**：`value_hit`(2/1/1/0) + `source_hit`(2/1/1) | cross_entity unknown（同 C25 键形态）；safety `passed/frozen_forbidden_checks_ok`；cross_user/stale_source passed | **candidates**：`rag/retrieval.py:221-244` 逐过滤键 AND（`$.item`）把店家行排除；路由 `conversations/service.py:2239-2240` 交给 RAG 内核后 `:2502/:2516` 直接返回，**从不调用** legacy 的 `_store_join_ids` | A/B 形均 `共 1 条…显示 1 条`、只有位置值、`sources` 1 条、模型 0 调用（202A/202C/203C F1 红态原文） | **202C 9 hunk**：`rag/retrieval.py`（`_store_join_chunks` + 并入 + `diagnostics["store_join"]`）、`rag/answer.py`（按记录身份逐行渲染 + `joined_store=`）、`rag/facts.py`（`_joined_store_row` 仅放行门店值相等的店家行） | C1 只问位置 / C2 只问店家属性 / C3 物品+电话 / C4 同名两店不联结 / C5 过期行不联结 / C6 多目标不联结 / C7 `mode=document` 逐字不变；F1 legacy 见证独立可证伪 | pending |

## 2. C29 的一次真实失败码补齐（历史缺失项）

- `failed_check_ids` = `value_hit`、`source_hit`；`kind_correct` pass（`kind=answer`）、`value_no_fabricated` pass（extra 0）、
  `value_forbidden` pass、`source_forbidden` pass、`refusal_expected` skipped（`should_refuse=false`）。
- 覆盖形态 = 值 **1/2**、来源 **1/2**；两个 target 中 `target_refs_0`(item) resolved+matched、`target_refs_1`(store，另一份文档) **`no_match`**。
- 历史旧码 `forbidden_source_unmappable` / `free_text_attribution_unverifiable` **不在质量检查链**，是四轴 reason 词表项，
  重评里已被 `safety=passed` / `cross_entity=unknown(entity_identity_unresolved)` 取代 ⇒ 作为最终违规不成立。
- **不是**应拒未拒、**不是**编造、**不是**禁源泄漏；是**跨文档覆盖不全**。

## 3. C25 / C29 的未知轴原因（单列，两案同机制不同落点）

| 项 | 结论 |
|---|---|
| 轴 | `cross_entity`（两案各 1 个 unknown 单元，共 2 个；20 轴单元 = 14 passed / 4 N-A / 2 unknown / 0 violation） |
| reason | `entity_identity_unresolved`（审计码 `entity_identity_missing`；C29 另有 `target_ref_no_match`） |
| provenance（必须标注，勿混用） | 权威口径 = 逐题合并层 `runs[2].cases[].new_axes`（`entity_identity_unresolved`）。<br>`evidence/02-case-boundary/summary.json` 的 axes 块来自 `p2_hard_evidence` 的另一套分派键，对同两案给出 `free_text_attribution_unverifiable`（C25 且 `safety=violation`）——**state 相同（unknown）、reason 词表因模块分派而异**，不得把该块的 reason 当作本轮结论。C25 的 `safety=violation` 是早期重建口径误用（v0.1 source map）的表现，已闭合为 `not_applicable`。 |
| 根因 | **历史身份形态**：同一条 `SourceUnit` 在检索索引侧与 rag 分块侧各派生一次 `entity_key`，旧代码词法不同（`item\|id:X` vs `item\|X`） |
| 是否产品缺陷 | **否**（R0 已统一派生；当前同形端到端键逐字节相等、两入口 `passed/frozen_targets_match_ok`） |
| 是否契约限制 | 否（不是 `shared_background` 运行期身份不可得那类合同限制） |
| 是否评分伪影 | 否（判据逐字符串相等，未被本批改动） |
| v0.6 能否救 | **不能**：v0.6 只放行"使用层非空 + 无 facts + 全部单元无实体身份"的纯文档回合；两案存在实体/半身份身份 ⇒ 条款零触发 |
| 当前修法 | 无需新增产品改动；R0 派生已覆盖（关掉即回 unknown，敏感性成立） |
| 修后预期 | 同一修后版本上该轴应 `passed` ⇒ **必要轴 unknown 0** |

## 4. C14 双回合（逐轮证据，末轮不代替中间轮）

| 项 | t1 | t2 |
|---|---|---|
| kind / path / mode | answer / legacy / record | answer / legacy / record |
| target 数 / 期望值 / 期望来源 | 1 / 2 / 1 | 1 / 2 / 1 |
| as_of | 2026-11-20 | 2026-11-20 |
| 上下文 | `ctx_msg=0`、`ctx_q=0`、`ctx_entities=2`、`entity_inh=0`、`state_row_present=false` | `ctx_msg=1`、`ctx_q=1`、`ctx_entities=2`、**`entity_inh=2`**、`state_row_present=true` |
| revision | 10 → 10 | 10 → 10 |

- 上下文继承 = true；状态保存/提交一致（`pre/post/capture_revision` 与 `commit.revision_before/after` 全 10）。
- 逐回合**轴**裁决 NOT-RUN（`per_turn_verdict_requires_full_case`：`p2_hard_evidence` fail-closed，任一回合非 `executed` 即整案 `turn_not_executed`）——
  逐回合只给**输入**，不给伪裁决；末轮质量评分与案级硬轴**分开列**。
- HTTP 见证（203C F3）：T1 结构化答位置 → T2 裸追问仍同目标、`sources` 与 T1 逐字段相同、两回合 `as_of` 一致。

## 5. 版本/日期（本案集）

| 案 | `as_of`==2026-11-20 | future/current/expired | unit 版本绑定 | 期望源 doc+version 一致 | 禁源绑定可复核 | in_window |
|---|---|---|---|---|---|---|
| C08 | true | 0/1/0 | 1 | 1 | –（无禁源） | true |
| C14 | true | 0/**2**/0 | 2 | 1 | – | true |
| C19 | true | 0/1/0 | 1 | 1 | – | true |
| C25 | true | 0/1/0 | 1 | 1 | **true** | true |
| C29 | true | 0/1/0 | 1 | 1 | **false**（不可复核，不写成"无匹配"） | true |

## 6. 真实状态

五案真实状态一律 **pending**：T-R2-205 尚未执行。任何"已通过"表述都不得出现在真实运行之前。

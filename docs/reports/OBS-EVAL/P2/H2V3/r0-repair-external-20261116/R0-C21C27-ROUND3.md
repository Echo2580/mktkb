# R0-C21C27-ROUND3（第三轮：仍不通过，最后一轮定位）

> 只读前置事实（前一轮 SAFE 复算）未重测；本轮未读私有材料（`D:\mktkb-p2-h2v3-*`、`.env`、`*.key`、P1-HOLDOUT、任何 H2 题面/答案），
> 未发真实请求，未改冻结件/评分器/题集/阈值/账本，未 `git add/commit/stash/reset/checkout/clean`。

## 1. 结论（先给）

1. **丢失层 = `facts`（L4）这一层，不在检索、也不在提交层**。真实两案的 SAFE 阶梯是 L1 DB 单元=满、L2 被引单元=满、
   L3 可映射角色=满，而 `exp_in_rag_facts` = **0/1（C21）**、**1/2（C27）**，`exp_in_commit` 与之逐值相同（0/1、1/2）。
   值不是在渲染时被改掉，而是**从来没进入 `answer.facts`**（`_enumerate_answer` 的 `entries`）。
2. **L4 缺项的唯一原因：`plan.field_roles`（被请求字段角色集合）比“该行可映射角色集合”少一项**。渲染层是忠实的：
   它只渲染被请求的角色，同角色多列已经全渲染（第二轮修的正是这层，故零变化）。**不是 rank/limit 截断**
   （被引单元只有 1 条、两个值都在这一条里），**不是“同一角色多值只取首个”**（两案缺的值都在**另一个角色**下：
   `effective_from` vs `effective_to`；`address` vs `phone`）。
3. 判定：**角色集合构造漏项**（`rag/query.py:_match_fields`），两个具体机制：
   ① 中文并列只认 `和/及/以及/、/与`，逗号/分号并列（“地址，电话”）被当成单字段问法；
   ② 其余字段只用 `FIELD_WORDS` 的**完整问法**匹配，短问法（“什么时候生效”）即使句中有合取词也收不到
   `effective_from`。两处都只影响“被请求角色”这一层，正是前两轮没动过的层。

## 2. 丢失层证据（只出计数与固定枚举）

真实三案（前一轮 SAFE 探针 `evidence/06-postrun3/producer-analysis.txt`，未重测）：`cited_raw=cited_text=cited_role` 全满，
`exp_in_rag_facts`：C12 0/3、**C21 0/1**、**C27 1/2**；`exp_in_commit` 与之一致 ⇒ L4 就是断点；C12 断在 L2（检索/引用面）。

合成阶梯（本节新增，`work/out/round3b/ladder_probe.py`，输出 `ladder.txt`，去身份化假值）：

| 形态 | requested（修前→修后） | row_roles | 交集 | L1 | L2 | L3 | L4 | L5 |
|---|---|---|---|---|---|---|---|---|
| C21 形 | `['effective_to']` → `['effective_to','effective_from']` | `effective_from,effective_to,identifier,item,store` | `effective_to` → 两项 | 1→1 | 1→1 | 1→1 | **0→1** | **0→1** |
| C27 形 | `['phone']` → `['phone','address']` | `address,phone,store` | `phone` → 两项 | 1→1 | 1→1 | 1→1 | **0→1** | **0→1** |

即：修前 L1=L2=L3=1、L4=0 —— 与真实两案的 SAFE 计数**同形**；交集少的那一项就是承载期望值的角色。

## 3. 改动（唯一最小修改点 + 一处同层一致性）

| 文件 | 函数 | 净增 | 内容 |
|---|---|---|---|
| `backend/src/mktkb/rag/query.py` | `_match_fields`（+`_field_role_words`/`_EXTRA_FIELD_ROLE_WORDS`/`_FIELD_LIST_JOINERS`/`_GENERIC_DATE_WORDS`） | **+58 / −0** | 并列判定补逗号/分号；其余字段复用 `_match_field` 的短问法词表；已判定有效期时不再另立泛化 `date` 角色（防夹带） |
| `backend/src/mktkb/rag/facts.py` | `FactValidator.validate_record_text` | **+6 / −1** | `unit` 白名单按**被请求字段集合**判定，而非只看首个 `field_role`（否则“价格，失效日期”这类多字段问法会被 `CROSS_FIELD` 整条拒） |
| `backend/tests/rag/test_r0_6_synthetic_repairs.py` | 新增 | 231 行 | 去身份化合成件（假门店/假物品/假字段/假值），无 case_id 特判、无写死数据 |

未改：`evaluation/p2_*.py`、`docs/evaluation/*`、`fixtures/`、账本/预算/旧证据/case-plan、评分器、阈值。
注意：`git diff` 里 `query.py` 的 465 行含前几轮遗留改动，本轮只有上面 +58。

## 4. 红 → 绿（同一份合成断言）

- **RED**（内存里把两个常量还原成修前取值，工作树不动，插件 `work/out/round3b/oldmode.py`）：
  `3 failed / 10 passed`——失败正是三张“漏一项”形状（C21 逗号并列、C21 短问法、C27 逗号并列）。
- **GREEN**（当前工作树）：`13 passed`。
- RED 里通过、GREEN 仍通过的 10 条含：`生效日期和失效日期`（前两轮已覆盖，作为非回归基线）、三条单字段反例、两条受限联系人闸、无捏造值。

## 5. 三个反例

① **只问单一字段不夹带**：`列出甲店立牌的失效日期` → 仅 `{('effective_to','2026-09-30')}`；`甲店立牌什么时候生效？` → 仅
`effective_from`（不被多出来的 `date` 判成“未记录”）；`列出甲店的电话` → 不含地址；`列出甲店立牌的规格` → 不含价格。
另加限定语反例：`甲店立牌的组合价什么时候失效？` → 仍只答 `effective_to`，不带价格（对应离线 e2e 的追问形态，第一版改动曾把它打成 `CROSS_FIELD`，已按此收窄）。
② **相邻安全反例**：`test_t207_security_precedence_synthetic.py` + `test_t207_v8_safety_contract_synthetic.py` + `test_v3_safety_fix_e2e.py`
= **16 passed**；另跑 `t207_v8_enumeration`/`t207_conflict`/`t207_v8_followup`/`t207_record_duplicate` 合并 **25 passed**（越界/跨实体/电话类阻断不变）。
③ **不产生新 `value_no_fabricated` 失败**：断言每个 `fact.value` 都等于被引行里的某个单元格值（`test_every_rendered_value_comes_from_the_cited_row`）；
新增列的值全部来自 `role_values`，`FactValidator` 仍逐值核对（`ForgedValue`/`CrossField` 路径未放宽，唯一放宽的是 `unit` 的“被请求集合”判定）。

## 6. 测试统计（`MKTKB_PROJECT_TOTAL_LIMIT_CNY=20.0`，`-B -p no:cacheprovider --basetemp backend\.pytest-tmp\c2127`）

| 套件 | 结果 |
|---|---|
| 新增合成件 | RED 3 failed / 10 passed → GREEN **13 passed** |
| `backend/tests/rag` | **460 passed / 1 failed**（仅既有 `test_s4_stage_limit` 的 `limit_cny=20 vs 40`，任务已知，不管） |
| `unit/test_conversations.py` + `integration/test_visible_index.py` + `unit/test_retrieval.py` | **89 passed** |
| T207 安全三件 + 4 个相邻 T207 套件 | **25 passed** |
| 加跑 `unit`+`integration` 全量 | **842 passed / 2 failed**：`test_s2h_r3_official_profile`（R0-5 已登记的 env=20 口径差）、`test_s2b_intent_semantics::test_ambiguous_identifier_candidates_converge`（**既有失败**：把本轮两个常量还原成修前取值后**逐字重现**同一失败，与本次改动无关） |

## 7. 是否预期 C21/C27 转 pass

- **C27：中等把握（偏正面）**。缺的字段名两侧词表都在（`address`/`phone` 在 `FIELD_WORDS` 与 `ROLE_SYNONYMS` 都存在），
  卡住的只可能是“并列判定”或“短问法”；前者本轮已补逗号/分号。**若真实问法是裸并列（无任何标点/连词，如“地址电话”），则不覆盖**。
- **C21：不确定（中等）**。需要真实问法里出现有效期短问法（生效/失效/截止）或另一字段名的并列；若期望值其实落在
  `alias`/`location` 这类没被问到的角色上，本轮改动无效。
- 两者都**不保证**：本轮不能重跑 12 题（禁真实请求），只能给出“同形合成件由红转绿”的证据。

## 8. 风险与残留

1. `_answer_record` 的 `exact` 预筛仍只看 `plan.field_role`（首个角色）：多字段问法下“只含次要角色”的行仍会被丢——
   与本案“同一行内丢列”不是同一形状，本轮未动（改动面最小化），列为残留。
2. 非枚举路径 `_multi_field_answer` 在“被请求角色缺列”时整条拒答；本轮让更多问法进入该分支，可能把个别原本答单字段的
   问法变成 `FIELD_NOT_RECORDED`（fail-closed，不产生捏造值）。
3. 裸并列问法（无标点无连词）明确**不覆盖**，已在测试里写成负向守卫，避免以后被误当回归。
4. 版本矩阵：无法证明对真实 12 题的移动方向；建议下一轮真实 r0 后按 `value_hit` 逐题核对 C21/C27，若 C21 仍失败，
   下一步应直接查“问句→字段角色”的语义映射（`FIELD_WORDS` 上限），而不是继续动渲染层。

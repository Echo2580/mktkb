# R0-FACTS-ADMISSION（C21/C27：facts 层准入定位 + 最小修复判定）

> 边界：未读私有材料（`D:\mktkb-p2-h2v3-*`、`.env`、`*.key`、P1-HOLDOUT、任何 H2 题面/答案），未发真实请求；
> 未改冻结件/评分器/题集/账本/case-plan，未 git add/commit/stash/reset/checkout/clean。合成件全部去身份化。

## 1. 结论（先给）
1. **facts 层忠实**：角色进了 `plan.field_roles` 后，被引行该角色的每一列都成 fact（同角色两列=2、同值=1+1 dedup、
   无表头回落 `role_values`）；非全字段路径 `rendered_but_not_fact=undetermined=cross_field_conflict=0`。
2. **唯一闸门** = `backend/src/mktkb/rag/answer.py:670-672` 的 `requested_roles`（非枚举同义行 `:341`；facts 只遍历它，
   `:686 -> _requested_field_entries`）。上游唯一构造点 `backend/src/mktkb/rag/query.py:1149 _match_fields`
   （`:443 field_roles_for_question` → `:1473`）。
3. **真实两案（按 cited_roles 字段角色计数，不含实体角色）**：C21 3 个（effective_from/effective_to/location）+ facts=1
   ⇒ `fact_built=1 / role_not_requested=2`；C27 6 个（address/contact/phone/status/effective_from/effective_to）+ facts=2
   ⇒ `fact_built=2 / role_not_requested=4`（两角色各 1 列）或 `5`（一角色两列）；两案其余码 0。
4. 故 L4 缺项固定码 = **`role_not_requested`**：缺值角色一定不在 `plan.field_roles`（若在，§2/§4 证明必成 fact）——
   不是 `value_rejected_by_validate` / `cross_field_conflict` / `dedup_dropped` / `limit_dropped`。
5. **本轮不落产品代码**：真实问句未投影，无法证明漏的是哪个词/角色；按“只改证实命中”停在此处（投影见 §7）。

## 2. 拒绝码分布（`work/r0_facts_admission.py`；13 形状，只出固定码/角色枚举/计数）
| 形状（假实体假值） | plan_roles | facts | 非零码 |
|---|---|---:|---|
| C21_red_single_end；H_c21_window_word | effective_to | 1 | fact_built 1 / role_not_requested 2 |
| C21_green_both_ends | effective_to,effective_from | 2 | fact_built 2 / role_not_requested 1 |
| C27_red_single_phone；C27_bundle_word | phone | 1 | fact_built 1 / role_not_requested 5 |
| C27_green_both_contact | phone,address | 2 | fact_built 2 / role_not_requested 4 |
| C27_two_phone_columns | phone | 2 | fact_built 2 / role_not_requested 5 |
| C27_two_roles_fact2 | phone,status | 2 | fact_built 2 / role_not_requested 4 |
| H_c21_deadline_word（“到期”） | date（行内无） | 0 | role_value_missing 1 |
| C21_all_fields | 无 | 1（identifier） | all_fields_representative_only 3 |
| same_role_two_columns / same_value | price | 2 / 1 | fact_built 2；fact_built 1 + dedup_dropped 1 |
| requested_role_absent | effective_to | 0 | role_value_missing 1 |

合计 `fact_built=15`、`role_not_requested=28`、`role_value_missing=2`、`all_fields_representative_only=3`、`dedup_dropped=1`；
`value_rejected_by_validate=cross_field_conflict=limit_dropped=undetermined=0`。`limit_dropped` 结构性为 0（facts 只为被引行构造，
分页/歧义发生在引用之前；真实两案被引单元各 1 条）。netguard：blocked 2 / 正对照 2 / 出站 0。
证据：`work/out/facts-admission/ladder.json`、`ladder.txt`（红档 `ladder-red.*`）。

## 3. 最小修改点（唯一）
- 判定行：`answer.py:670-672`（facts 只为 `requested_roles` 构造），`requested_roles` 全部来自计划。
- **facts 层不可改**：放宽成“行内全部角色”⇒ 未请求角色值进正文 ⇒ `facts.py:166-179` CROSS_FIELD 整条拒绝（更差），
  且违反反例①。**上游修复点唯一**：`query.py:1149 _match_fields` 的词表/并列判定（`:1140-1186`）。
- 第三轮已补逗号/分号并列与生效/失效短问法，真实码零变化 ⇒ 真实词形不在已补集合；缺哪条无法由 SAFE 证据判定。

## 4. 红 → 绿（同一行、同一代码，只改“计划请求了哪些角色”）
- 只问“失效日期”⇒ `facts={effective_to}`（红）；问“生效日期和失效日期”⇒ `{effective_from,effective_to}`（绿）。
- 只问“电话”⇒ `{phone}`（红）；问“门店地址和联系电话”⇒ `{address,phone}`（绿）。
- 因果注入（`--red`，仅内存把 `_match_fields` 收窄取首角色）：两个绿形立刻退回 `facts=1/role_not_requested`
  （C21 2→1、C27 2→1），与真实两案 L4 形态逐项相同；恢复即绿 ⇒ 修复点不在 facts 层。
  测试内同形断言：`test_plan_under_request_reproduces_the_facts_deficit`。

## 5. 三个反例
1. **单字段不夹带**：失效日期/什么时候生效/电话/门店地址各只出 1 角色；`all_fields` 只 1 条代表事实。
2. **相邻安全**：`test_t207_security_precedence_synthetic.py` + `test_t207_v8_safety_contract_synthetic.py` +
   `test_v3_safety_fix_e2e.py` = **16 passed**。
3. **不新增 `value_no_fabricated`**：每个 `fact.value` ∈ 被引行单元格；13 形状 `rendered_but_not_fact=0`；
   FORGED/CROSS_FIELD 路径未放宽（本轮未改产品代码）。

## 6. 测试统计（`MKTKB_PROJECT_TOTAL_LIMIT_CNY=20.0`，`-B -p no:cacheprovider --basetemp backend\.pytest-tmp\factsloc`）
| 套件 | 结果 |
|---|---|
| 新增 `backend/tests/rag/test_r0_7_facts_admission_synthetic.py` | **13 passed** |
| `backend/tests/rag` | **473 passed / 1 failed**（仅既有 `test_s4_stage_limit` 的 `limit_cny=40 vs 20.0`，任务已知） |
| `unit/test_conversations.py` + `integration/test_visible_index.py` + `unit/test_retrieval.py` | **89 passed** |
| T207 安全三件 | **16 passed** |

## 7. 是否预期转 pass + 需要保管侧投影
- **本轮不改代码 ⇒ code_version 同第四轮 ⇒ 预期 C21/C27 检查码不变（仍 `value_hit` fail）**。
- 要一次命中，需保管侧投影 **4 个无正文固定码**：①`plan.field_roles`（有序角色）+ `plan.field_role`；
  ②每个 expected value 的角色码（多角色→`ambiguous`）；③被引行 `role -> 列数`（整数）；④问句命中的字段词类（角色枚举）
  与“是否含并列词”。判定式：`expected_role ∉ plan.field_roles` ⇒ 证实；再由 ③/④ 定位要补的那一行词表。
  若 ①② 反而显示 `expected_role ∈ plan.field_roles` ⇒ 本报告结论被推翻，下一步查“索引 role_values 与当轮 field_role 版本”。
- 未落地候选（**仅当投影证实**才可改，各一行词表）：`有效期/有效期至`→effective_from+effective_to；`到期/什么时候结束`→effective_to；
  `联系方式/联系信息`→contact+phone+address。

## 8. 风险与未确认
1. `plan_observed` 未采 `field_roles`（既有 open question）；`query_state_saved.state_json` 有，但属私有证据。
2. C27 facts=2 有两种子形态（两角色各 1 列 / 一角色两列），投影 ③ 可分辨；不影响“缺项=未请求角色”。
3. 未验证：真实问句词形、annotation 的 expected 角色、真实索引与当轮 `field_role` 版本一致性。

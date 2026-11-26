# R0 / C27 —— `contact` 列词表漏登记修复报告

日期：2026-11-16（Asia/Shanghai）。范围：C27 `value_hit`（缺 1 个期望值）最小修复 + 离线测试。
只读合成件；未读私有材料（`D:\mktkb-p2-h2v3-*` 运行根、`.env`、`*.key`、`P1-HOLDOUT`），未发真实请求，
未打印问句原文；未改冻结件；未 `git add/commit`。工作树只多 2 项：`rag/query.py` 一处词表 + 新测试文件。

## 1. 根因归类：**(a) 缺同义词**（不是 (b)，不是 (c)）

只用 SAFE 投影的布尔/下标（`evidence/12-c27/*.json`）：

- `c27-question-roles.json`：`field_word_hits.contact=false`，`match_fields=["phone","address"]`，
  `match_field_first="phone"`；expected #0 → contact 列 7、#1 → phone 列 6。
- `c27-question-words.json`：`question_hits=[3,4,5,6,7,17]`（候选词下标 → 电话/地址/谁/找谁/对接/门店），
  `derived.contact_lexicon_word_hit=false`。即问句用「找谁 / 对接」问联系人，而 `FIELD_WORDS["contact"]`
  只登记「联系人 / 负责人」，整句不命中 → `_match_fields` 给 `("phone","address")` →
  答案层只渲染 `plan.field_roles` 里的角色 → contact 列不进 facts / 不进正文 → `role_missing`。
- 因此不是 (b)：问句**确实在问联系方式**，无需“同族自动扩展”；（c）不成立（已排除同角色多列/dedup/
  commit 过滤/值不在行内）。

## 2. 改动清单（净增 7 行 + 1 个测试文件）

| 文件 | 性质 |
|---|---|
| `backend/src/mktkb/rag/query.py` | 改：`FIELD_WORDS["contact"] = ("联系人","负责人","对接","找谁")` + 8 行注释（唯一新增 hunk，工作树其余差异为既有改动） |
| `backend/tests/rag/test_r0_11_contact_family.py` | 新增：13 个用例 |

**不**登记单字「谁」（任何“谁……”都会变联系字段）；**不**做同族自动扩展（见 §4）。
`answer.py` / `facts.py` 无落点，未改。

## 3. 红 → 绿（命令同派单，`--basetemp backend\.pytest-tmp\c27`）

- **红**（改前）：新文件 `2 failed, 10 passed`——`_match_fields("…找谁对接，电话和地址…") == ('phone','address')`，
  答案 `facts={('address','示例路18号'),('phone','010-55550000')}`，正文只有电话+地址（复现 C27 形状）。
- **绿**（改后）：新文件 `13 passed`；同一问法 `field_roles=('contact','phone','address')`，
  正文 `…联系人：<格值>，电话：…，地址：…`，facts 3 条含 contact。
- 枚举路径（`共 N 条…` 3 行短卡）同样带上 contact 列（`联系人 <格值>`），两条渲染路径各有用例。

## 4. 安全反例结论（最重要）

- 只问电话（店家级）：`facts={("phone",…)}`，正文**无**联系人姓名、无地址（`test_c27_phone_only_…`）。
- 只问电话 + 物品记录：仍 `SECURITY_RESTRICTED_CONTACT`，`citations=[]`，姓名/号码均不出现。
- 物品 + 「找谁对接」：仍整体拒答（新词不削弱 `RESTRICTED_CONTACT_ROLES` 门禁）。
- 既有三件套全绿：`test_t207_security_precedence_synthetic.py`、`test_t207_v8_safety_contract_synthetic.py`、
  `backend/tests/integration/test_v3_safety_fix_e2e.py`，另加 `test_v3_safety_fix_policy.py` → **35 passed**。
- **派单问题 5 的明确回答：不会。** 本改法是词表级（问句明确问“找谁/对接”才命中角色），不是同族扩展；
  反例 `test_c27_phone_address_question_is_not_family_expanded` 钉住“问 phone+address 也不带 contact”。
  同族扩展方案会让 `test_v3_safety_fix_e2e.py::test_two_store_phone_still_answers_both_targets`
  这类“多门店只问电话”的答案多渲染联系人姓名，故不采用；无需再借 `plan.enumerate` 收窄。

## 5. 单字段反例

只问地址 → `facts={("address",…)}`，无电话/联系人；只问电话 → 只有 phone；只问联系人（既有词表）→ 只有 contact。

## 6. 不新增 `value_no_fabricated`

进正文的值逐字来自被引行单元格（`facts` 值 ⊆ 行内 cells，正文数字 token 全部来自该行）；
新增的 contact 值由 `FactValidator` 的 `allowed_roles`（现含 contact）与“值必须在来源 `role_values` 中”双查。

## 7. 测试统计

| 集合 | 结果 |
|---|---|
| `test_r0_11_contact_family.py`（新） | 13 passed |
| 安全组（t207 安全前置 + v8 安全契约 + v3_safety_fix_e2e + v3_safety_fix_policy） | 35 passed |
| 回归：`tests/rag` + `unit/test_conversations.py` + `integration/test_visible_index.py` + `unit/test_retrieval.py` + `evaluation/test_p1_refusal_controls.py` | **627 passed / 1 failed** |

唯一失败是派单已声明的既有失效 `test_s4_stage_limit.py`（预算 40 vs 20），与本次改动无关；
两集合有重叠（`test_t207_security_precedence_synthetic.py` 同时属两集合），无新增失败。

## 8. 预期 C27 转 pass 的把握：**~85%**

支撑：① 问句含「找谁」「对接」，修复后 contact 必然进 `_match_fields`（当前已是 phone+address 双角色，
说明并列词分支成立，该分支按 `FIELD_WORDS` 顺序全量补角色）；② 被引行 contact 列确有值（期望值 #0 就在该列），
枚举/多字段两条取值路径均已用同形合成件验证；③ `field_role` 由 phone 变 contact 不影响
`mode`/`enumerate`/`filters`/`_rag_owns_turn`/`_required_missing`（contact 与 phone/address 同族同处理）；
④ `value_hit` 按子串口径，contact 格（8 字）含期望值（2 字），渲染整格即命中。

剩余不确定：真实 C27 未复跑（禁读私有材料、不发真实请求），结论基于 SAFE 投影 + 同形合成件；
若同店另有“只带 contact 不带 phone”的行，`exact` 命中集变化可能引发冲突披露（投影 `cited_rows=1` 不支持该形态）。

## 9. 风险

1. 「对接」是动词：理论上“某物的对接流程”（有实体、未被政策短路）会被判成 contact 记录题。公开 fixtures
   与现有测试里 0 处“对接”问句；`RC-P12`（“活动预算…找谁审批”）因政策题短路不受影响（有专项断言）。
   若日后出现该问法，最小回收方式是把「对接」收窄为「对接人」（C27 由「找谁」仍覆盖）。
2. `field_role` 变 contact 会让精确召回按 contact 过滤（原按 phone）：对行内同时有 phone/contact 的形态无影响。
3. 未跑全量 backend 测试（只跑派单指定集合）；真实 C27 转 pass 需下一次真实评测确认。

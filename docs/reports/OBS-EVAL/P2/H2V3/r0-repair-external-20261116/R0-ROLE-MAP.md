# R0-ROLE-MAP（角色码投影 + 词表补全：结论 = 不可由现有 SAFE 证据定位）

> 边界：未读私有材料（`D:\mktkb-p2-h2v3-*`、`D:\mktkb-p2-h2v3-fullverify-*`、`.env`、`*.key`、P1-HOLDOUT、任何 H2 题面/答案）；未发真实请求
> （进程内出站阻断 + 正对照 2 次均被阻断、出站 0）；未改冻结件/评分器/题集/账本/case-plan；未 git add/commit/stash/reset/checkout/clean。
> 产物只出固定角色码 / 固定词类枚举 / 整数 / 布尔 / sha256（`_safe_dump` 对非 ASCII 硬拒绝；三份产物实测 non_ascii_bytes=0）。

## 1. 结论（先给）
1. **A/B/C 三组结构上不可判定**：两案 `open_questions` 都含 `field_role_not_captured`（未采集 `plan.field_roles` / 期望值角色 / 被引行逐角色列数）。
2. **C21 可判到“恰好 1 个被请求角色、该角色恰好 1 列”**：`facts = Σ_{r∈plan.field_roles} columns(r)`，`facts=1` ⇒ 单角色单列；候选全域 3
   ⇒ `role_not_requested` **恒为 2** ⇒ 与真实 `fact_built=1 / role_not_requested=2` 逐位一致。
3. **C27 可判到“请求 1–2 个角色、`role_not_requested ∈ {4,5}`”** ⇒ 与真实 `2 / (4 或 5)` 一致；4 还是 5 取决于逐角色列数。
4. **期望值角色**：C21 = 候选全域 3 个中的 2 个之一；C27 = 候选全域 6 个之一（缺失的那条一定 ∉ 被请求集合）。单值 `undetermined`。
5. **词表侧（D 组）完全可判**：15 个词类 14 个映射到角色码（仅 `other` 按定义无角色）；**7 个候选角色全部可被词表请求到** ⇒ 缺的是
   **词形（paraphrase）**，不是角色表洞。
6. 故**本轮不改产品代码**：没有一对满足“期望值角色已判 + 问句词类已判”，盲补词形等于猜；两案缺项**不能由现有 SAFE 证据定位到某一行词表**。

## 2. 四组固定码投影（`evidence/08-role-map/role-map.{json,txt}`，`work/r0_role_map.py`）
| 组 | C21 | C27 | 判定 |
|---|---|---|---|
| A `plan.field_roles` | `undetermined`（角色码）；**请求角色数 = 1**、列数和 = 1 | `undetermined`；请求角色数 ∈ [1,2]、列数和 = 2 | 码不可判 / 基数**可推** |
| B 期望值角色 | `undetermined`；候选全域 `{effective_from, effective_to, location}`（3） | `undetermined`；候选全域 `{address,contact,effective_from,effective_to,phone,status}`（6） | 单值不可判 / 候选**可判** |
| C 被引行逐角色列数 | `undetermined`；被请求角色列数和 = 1 | `undetermined`；和 = 2 | 不可判 |
| D 问句词类→角色码 | 真实问句词类 `undetermined`；映射表**完全可判** | 同左 | 映射可判 / 命中词类不可判 |

- 缺证据固定码：`plan_observed_field_roles_not_captured`、`expected_value_field_role_not_captured`、`cited_unit_raw_fields_not_captured`
  （`unit_rows_with_raw_fields` 只是**行数**）、`question_text_not_in_safe_layer`（SAFE 层只有 `plan_terms_count`/`plan_filters_count` 整数）。
- 候选全域取自 `06-postrun3/producer-analysis.txt` 的 `cited_roles`（probe2/probe4，SAFE 固定码），剔除实体角色（`identifier/store/item/alias/…`）；
  与 `R0-FACTS-ADMISSION` §3 的 `3 个 / 6 个` 计数同源一致。计数自检：C21 `facts=1,expected=1,missing=1`；C27 `facts=2,expected=2,missing=1,exp_in_commit=1`。

## 3. 词表补全：本轮**补 0 条**（附可补清单，未落地）
- 补的条件（任务定义）：存在「期望值角色 ∉ `plan.field_roles`」**且**「问句里确有对应词类」。B 组与 D 组问句侧都是 `undetermined`
  ⇒ **配对集合为空** ⇒ 无可落地的“最小映射”。能证明的只有**索引侧/问句侧表头词差集**（`parity_gap`，只出计数 + sha256）。
- **硬缺口**（连自身都请求不到角色）：`location` 2（**在 C21 候选全域**）、`note` 1、`price` 1、`quantity` 2、`clause` 1、
  `issued_quantity` 3（索引侧有角色、问句侧 0 词形，且不在候选全域）。均**未落地**。
- **为何不当场补**：索引侧是**表头封闭词表**、问句侧是**自由文本**，两侧分布不同 ⇒ “表头能映射就必须能问”不是合法不变式
  （`clause` 的 1 字表头词、`note` 的动词词形补进问句侧会造成“问一句说明就变成请求备注字段”）。每条须由真实问句词类背书 —— 正是本轮拿不到的。
  已在测试落守卫：7 个候选角色**全部**可请求；无词形的记录字段角色目前只有 `issued_quantity`（子集断言，补上不会红）。

## 4. 红 → 绿（合成件完全由投影出的固定码构成）
`backend/tests/rag/test_r0_8_role_map_synthetic.py`（**24 passed**；去身份化假门店/假物品/假字段/假值，无 case 特判）：

- **投影形状 ↔ 真实阶梯计数**：C21 形单角色 `facts=1 / role_not_requested=2`；C27 形单角色 `1 / 5`、双角色 `2 / 4` ⇒ 两案 L4 形态
  `1/2` 与 `2/(4|5)` 由固定码**逐位复现**。
- **参数化红→绿（7 个候选角色各一条）**：同一行、同一句“两个都问”的话，只动 `_match_fields`：绿 = 两角色都进 `plan.field_roles` ⇒
  `facts=2` 且都成 fact；红（把目标角色从 `_match_fields` 结果过滤掉）⇒ `facts=1`、目标角色落进 `role_not_requested`、值不在 facts —— 与真实
  两案同形，并证明**唯一杠杆是“被请求角色集合”**，不是 facts 层。

## 5. 三个反例
1. **只问单端不夹带**：`失效日期` → `plan_roles=("effective_to",)`、facts 仅该端；`电话` → 仅 `phone`（新测试 2 条 + `r0_6`/`r0_7` 既有守卫全绿）。
2. **相邻安全**：`test_t207_security_precedence_synthetic` + `test_t207_v8_safety_contract_synthetic` + `test_v3_safety_fix_e2e` = **16 passed**。
3. **不新增 `value_no_fabricated`**：参数化断言每个 `fact.value` ∈ 被引行单元格；FORGED/CROSS_FIELD 路径未放宽（本轮未改产品代码）。

## 6. 测试统计（`MKTKB_PROJECT_TOTAL_LIMIT_CNY="20.0"`，`-B -p no:cacheprovider --basetemp backend\.pytest-tmp\rolemap*`）
| 套件 | 结果 |
|---|---|
| 新增 `backend/tests/rag/test_r0_8_role_map_synthetic.py` | **24 passed** |
| `backend/tests/rag`（单独跑，无并发） | **497 passed / 1 failed**（唯一失败 = 既有 `test_s4_stage_limit` 的 `40 vs 20`，任务已知） |
| `unit/test_conversations.py` + `unit/test_retrieval.py` | **60 passed** |
| `integration/test_visible_index.py` | **29 passed**（三者合计 89，与上一轮一致） |
| T207 安全三件 | **16 passed** |

- 并发注意：两次 pytest 共用同一 --basetemp 时 `test_budget.py::test_cross_process_reservations_do_not_overspend` 会因跨进程预算干扰而红；单独复跑 **1 passed**，与本轮改动无关。

## 7. 是否预期 C21/C27 转 pass
**否**。`code_version` 与本轮前一致（未改产品代码）⇒ 预期两案仍 `value_hit` fail、检查码逐位不变。转 pass 需下列任一先到位：

1. **补采集**（最小、可离线验证）：`plan_observed` 增加 `field_role`/`field_roles`/`targets`（`observability/evaluation_capture.py` +
   `conversations/service.py` 的事件投影，见 `R0-CASE-MATRIX.md` 的 `field_role_not_captured` 行；observability 不在本任务范围）⇒ 下一轮直接读出
   A 组角色码，B 组变成“候选 − 已请求”；
2. 或保管侧给出两案的**问句字段词类**（15 枚举之一）与**期望值角色码** ⇒ §3 配对集合立刻成型，补词形是 1 行/角色；
3. 拿到 1 或 2 后，本工具 `predicate`（C21 `required_role_not_requested=2`、C27 `∈{4,5}`）可直接当红→绿验收式。

## 8. 未确认项
1. `plan.field_roles` 真实角色码、期望值角色码、被引行逐角色列数 —— 三项缺采集，本轮 `undetermined`（未猜）；真实问句词形亦不可判定，
   故 C27 `role_not_requested` 是 4 还是 5 仍未定。
2. `parity_gap` 硬缺口是**可证的表内不对称**，但**未证明**与两案缺项有因果关系（`location` 是唯一同时命中候选全域的角色码）。
3. 工具选择：新增 `work/r0_role_map.py` 而不改 `r0_facts_admission.py`/`r0_safe_project.py`（后者是既有证据产出脚本，改动会破坏旧证据可复现性）；
   新工具沿用同一 `NetGuard` + 白名单 `_safe_dump` 纪律，产物 sha256 见 `evidence/08-role-map/sha256sums.txt`。
4. 方法学坑（已避开）：`fact_value_chars` 是**复合量**（`value + field_label + entity_label + entity_key + field_role`），**不能**当值长度反推角色
   （标定探针 `work/out/rolemap/_probe_shape_scale.py`，只打印整数/角色码）；`fact_rows_total` 是 facts **行数**，与 producer 的 `facts` 不同口径。

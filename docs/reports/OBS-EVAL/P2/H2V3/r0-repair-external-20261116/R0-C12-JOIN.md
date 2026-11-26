# R0/C12 跨表取数（物品行 + 同门店店家行）— 离线修复报告

日期 2026-11-17　范围：检索层取数 + 回答事实准入；**0 真实请求 / 0 费用**；未动冻结件（`evaluation/p2_*`、`docs/evaluation`、`fixtures/`、账本、预算、旧证据、case-plan）、评分器、题集、阈值；无 case_id / 门店 / 物品硬编码。

## 1. 命中机制（为什么 legacy 只留 1 条）
- t7 legacy 计划（本机离线 `parse_question` 实测，与第十轮 envelope 同形）：`entity_filters={store:城西店, item:海报}`、`requested_fields=(位置, 合作状态)`。
- 取数入口 `_filter_ids`（`backend/src/mktkb/retrieval/service.py:172-191`）把每个筛选键当等值 AND：店家行没有物品列 → **在入口就被 `item=海报` 排除**；rag 候选上界 13 条里虽有店家行，legacy 不用它。角色裁剪（`service.py:405-439`）只在已取到集合里裁，救不回入口排除的行。
- 回答侧同一根因的另一半：`_record_units`（`backend/src/mktkb/conversations/service.py:1138-1192`）按物品维度逐行命中、且要求单行背书**全部**本问字段；`_record_facts`（:1464-1526）再按模型分句回溯行原值。店家行（无物品值）被排除，物品行（无合作状态）也不能单独背书两条事实。

## 2. 改动（同一次修复的两个半边；"只改检索"已证明是回归）
| # | 文件:行 | 改动 |
|---|---|---|
| 1 | `retrieval/service.py:202-243` | 新增 `_store_join_ids`：仅当「item 条件 + store 条件 + 请求角色同时含店家级(contact/status/phone/address)与物品级(location)」时按同一 store 取 `entity_type=="store"` 行；否则空集，口径不变 |
| 2 | `retrieval/service.py:492-499` | 店家行并入候选集合，且**必须落在同一份 rag 候选上界内**（越界不并入） |
| 3 | `retrieval/service.py:372-402` | `_attach_store_rows`：只挂到**唯一**物品目标组且门店值一致；多目标/门店不一致 → 整组丢弃，保持既有"歧义"口径 |
| 4 | `retrieval/service.py:442-456,599-606` | `_group_host_mapping`：混合组候选身份仍取物品行（label/entity_filters 不被改写）；其余分组形态不变 |
| 5 | `conversations/service.py:1168-1192` | `_record_units`：跨表问法下物品维度只约束物品行，店家行按"至少背书一个本问原值"入列；字段仍逐值判定，未放宽取值 |

排序/去重/limit/冲突切片口径未改；业务日窗口同样作用于并入的店家行（`service.py:501-503`）。

## 3. 红 / 绿（合成，零真实数据）
- 红（单点回归，已入册）：`integration/test_r0_c12b_t7_boundary_e2e.py::test_join_alone_would_regress_answer_validation` —— 只做检索并集、保留改前回答口径 → t7 变 `service_error`（本机实测：并集后证据 2 条，改前 `_record_units` 返回空 → `MODEL_OUTPUT_INVALID`）。
- 红（并集开关）：`rag/test_r0_c12_join_synthetic.py::test_join_is_the_switch_for_the_second_source` —— monkeypatch 关闭并集 → 只剩物品行、无合作状态来源。
- 绿（检索）：`test_item_plus_store_field_joins_same_store_row` —— 2 个单元（物品行+店家行）、`total_candidates=1`、候选仍是物品目标、值逐字等于该行 fields。
- 绿（产品链路）：`test_c12_t7_carries_item_and_store_row_values` —— `kind=answer`、正文含「C区2号货架 / 合作中 / 模拟联系人·王平」、`sources=2`，模型证据里两种行都在；`test_joined_store_row_is_window_filtered` —— 店家行过期（失效 10-31、业务日 11-01）时不并入。
- 反例：`test_single_item_attribute_does_not_join_store_row`、`test_store_level_label_only_keeps_item_target`（"负责人"不改写目标）、`test_store_row_outside_candidate_bound_is_not_joined`、`test_multiple_item_targets_do_not_join_store_row`；产品链路 `test_single_item_attribute_has_no_store_values`、`test_store_attribute_question_is_unchanged`、既有 `test_item_plus_phone_still_refused_before_model`。

## 4. 四道门逐条
1. `value_no_fabricated`：并入值逐字取该行真实单元格（§3 绿 1 断言），不拼装/不改写行。真实 xlsx 摄入的 `locator.cells[].display` 携带电话/地址原值（`ingestion/parsers/excel.py:333-338`，本机探针实测 S02 行 6 个 cell），而该检查允许集 = 金标数字 ∪ **本轮引用 locator 数字**（`p2_scoring.py:960-967`、`scorers.py:446-463`）→ 回显的店家行数字有背书。离线不能直接跑评分器，标"强证据、待真实轮复核"。
2. `source_forbidden`：只可能新增「同门店、可见、且在本轮 rag 候选上界内」的店家行引用，不新增文档/版本类别；安全套件零新增失败。同标"待真实轮复核"。
3. 安全套件：四件 `t207_security_precedence` / `t207_v8_safety_contract` / `v3_safety_fix_e2e` / `v3_safety_fix_policy` = **35 passed**；含 refusal 的既有用例 `p1_refusal_controls` / `r0_repair_refusal_compat` / `p1_refusal_scope_http` = **88 passed**；C12 相关（`test_r0_c12b_boundary_synthetic` 12 + `test_r0_c12b_t7_boundary_e2e` 7 + `test_r0_c12_join_synthetic` 7）= **26 passed**。合计 **149 passed / 0 failed**。
4. 合成反例：§3 反例行全绿——单问物品属性不多出店家级字段；单问店家属性行为不变；item+电话/地址仍拒答；并集只在「物品级 + 店家级字段同时被问」时触发。

## 5. 回归统计
- 指定批：`tests/rag` + `unit/test_retrieval.py` + `unit/test_conversations.py` + `integration/test_visible_index.py` = **641 passed / 1 failed**；唯一失败 = 既有 `rag/test_s4_stage_limit.py`（预算 40 vs 20，按令不管）。
- 全 `tests/integration`：**445 passed / 1 failed**；失败 `test_s2b_intent_semantics.py::test_ambiguous_identifier_candidates_converge` 为**既有失败**——把本轮新增代码全部改成"一调用就抛错"后同测仍以同一 `conflict` 失败、`_record_units` 从未被调用 → 与本修复无关（应属前几轮 rag 工作树改动，不在指定回归清单内）。
- 既有测试披露：仅更新上一轮新增（untracked）的两件 C12 测试——`test_r0_c12_legacy_trim_identifiability_synthetic.py` 的 forced 断言（1→2 条，即本修复目标）与 `test_r0_c12b_t7_boundary_e2e.py` 的 t7 用例注入契约内回答（原"回显全部字段"在 2 条证据下超 8 分句上限）；断言强度未降。

## 6. 预期 C12 转 pass 把握
- 确定性部分（不再拒答、店家行进入证据面、回答侧可背书、正文可同时给出位置+合作状态+对接人回声、两条来源可被引用）= 已离线逐值证明。
- 真实模型剩余不确定性：① 须只写必需字段（分句 ≤8）；② 联系人须以表头键「联系人」陈述（写「对接人」会被事实准入拒绝）；③ 须同时引用两条来源；④ 若 C12 的 `forbidden_values` 含店家行电话/地址，而"其它字段回显"会带出它们（既有口径，见 §7）。
- **把握：约 65–75%**（确定性缺陷已消除；主要剩模型输出契约与 ④）。

## 7. 风险
- 高：模型输出契约（①②③）任一违反 → `service_error`，C12 仍 fail；离线无法消除。
- 中：回显店家行的电话/地址（`_record_answer_text` 既有"同引用行其它字段回显"口径，店内级问题本来如此）；若 case 以 `forbidden_values` 约束它们，会新增 `value_forbidden` 失败——需主人决定是否追加"未问字段不回显电话/地址"的收窄。
- 中：若店家表本身含「位置」列，位置角色可能出现跨行两值 → 误报 `conflict`（当前数据集无此列）。
- 低：`_record_units` 放宽只在"证据面已取到店家级事实 + 有 item 条件"时生效；同门店其它物品行仍需在证据面内才可能入列，且不改变展示取值来源。

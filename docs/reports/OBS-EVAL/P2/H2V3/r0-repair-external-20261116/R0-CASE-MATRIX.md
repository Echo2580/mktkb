# R0-CASE-MATRIX — 四案定位（SAFE 事实 → 首个偏离边界）

> 任务单 §六 R0-4 前半段：**只定位，不改产品**。生成器 `work/r0_case_boundary.py`；
> 逐案证据 `evidence/02-case-boundary/{H2V3-C02,H2V3-C12,H2V3-C21,H2V3-C27}.json`，
> 一览 `summary.json`。本文件只含固定码、固定事件名、整数、布尔、sha256；无题干、无答案、
> 无实体名、无原始引用。

## 0. 输入与自证
- 封存 run `p2-h2v3-20261115-r0-base_b0`；case-plan sha256 `b3100e7d…`；14 个 envelope 全部解密。
- 保管链逐文件摘要核对通过（`custody_ok=true`）。
- **重建自证**：12/12 逐题 `quality_status` 与 `run/r0-final/case-plan.json` 完全一致
  （`reconstruction_match_all=true`，`scoring_failures=0`）——事实表来自与封存同源的评分行。
- **确定性**：连续两次运行，5 份输出逐字节相同。
- **无出站**：socket/urllib/httpx 全封；正对照 2/2 被阻断（`positive_control_blocked=true`），出站 0。
- 读到的代码版本（sha256 前 8）：`p2_scoring` bebe2769 / `scorers` 4036fc76 /
  `p2_score_run` 366e621b / `p2_evidence_io` 1c16a3da / `p2_hard_evidence` 84f53a51 /
  `evaluation_capture` f45f2584。`p2_hard_evidence.py` 正被另一助手修改，本工具只取读时快照；
  四案的 quality 失败与该模块的空集证明无关（四案四轴均无 `violation`）。

## 1. 一览

| 案 | 失败检查 | 首个偏离边界 | 支撑固定码（count） |
|---|---|---|---|
| C02 | `value_no_fabricated` | **`undetermined`**（gap `extra_origin_ambiguous`） | `value_no_fabricated_extra` 2 / `extra_numbers_backed_by_evidence` 4 / `extra_numbers_unbacked` 0 |
| C12 | `source_hit` + `value_hit` | `retrieval_missed_expected_source` | `source_hit_fail` 1 / `cited_partial` 1 / `expected_not_retrieved` 1 |
| C21 | `value_hit` | `answer_value_absent` | `value_hit_fail` 1 / `value_hit_missing_all` 1 |
| C27 | `value_hit` | `answer_value_absent` | `value_hit_fail` 1 / `value_hit_missing_partial` 1 |

## 2. 逐案

### C02 — 判定 `undetermined`（**尚未定位**）
- **检查级**：`kind_correct` pass；`value_hit` pass（expected 1 / matched 1）；`source_hit` pass
  （expected 1 / matched 1）；`value_no_fabricated` **fail**（checked 1 / extra **2** / evidence_numbers 7）。
- **答案形态**：kind `answer`；142 字符；数字 token 16（去重 key 9）；日期 token 2；单位词 4；3 行；尾部无省略号。
- **产品边界固定码**：`plan` path `rag` / mode `record` / enumerate 1 / filters 2 / terms 9；
  `direct_rag_answer` 存在（fact_count 1、cited_unit_ids 1）；`model_input` 0、`model_output` 0、
  `retrieval_observed` 0；capture errors 0、truncations 0、http 200。
- **来源/证据面**：引用 1 条且命中预期来源；被引单位正文 89 字符、事实值 32 字符；
  2 个 extra key 在被引正文 0、事实值 0、模型证据 0、上下文 0。
- **为什么 undetermined**：两个 extra 都是 **1 位数字 key**（`extra_key_max_chars=1`）。任何 id 串
  都含该位，`extra_in_fact_ids=2`、`extra_in_unit_identity=2` 因此**没有鉴别力**；
  同理 `extra_in_none=0` 也不能当作"有出处"。既不能断定编造，也不能断定只是引用没带出来。
- **候选源码位置**：`backend/src/mktkb/rag/answer.py:_enumerate_answer`（整行渲染，配合
  `_record_line` / `_fact`）；`backend/src/mktkb/qa/service.py:answer`（`direct_rag_answer` 发射点）。
- **待验证的最小合成复现**：单条记录 + enum 型问题，构造"某字段值为个位数、且该数字不在
  gold/引用数字集合内"，断言产品答案含该数字而 `citation_number_keys` 不含它；再做一次反事实：
  把允许数字集合换成"引用单位全文数字"后 extra 是否归零（本工具未做该反事实重打分，需一条受控件）。
- **仍开放**：`single_digit_key_unattributable`、`field_role_not_captured`、`retrieval_not_captured_for_rag_path`。

### C12 — 判定 `retrieval_missed_expected_source`
- **检查级**：`kind_correct` pass；`value_hit` **fail**（expected 3 / missing 2）；`source_hit` **fail**
  （expected 2 / missing 1）；`value_no_fabricated` pass（checked 3 / evidence_numbers 6）。
- **答案形态**：kind `answer`；55 字符；数字 token 1；0 日期；0 单位词；1 行；`answer_missing_fields=1`。
- **产品边界固定码**：2 轮；path `legacy`；mode `record`；enumerate 0；`retrieval_observed` 4
  （scope `legacy_retrieve_initial` + `rag_candidate_upper_bound`；candidate 2；去重单位 1；truncated 0）；
  `model_input` 2（证据 16 条 / 264 字符）、`model_output` 2（status `ok`、source_ids 2）；
  capture errors 0、truncations 0、http 200。
- **来源面**：预期来源 2 条；被引命中 1；被检索命中 1；**既未检索到也未被引用 1**；
  "检索到但未引用" 0；候选身份还原 resolved 1 / unresolved 0 —— 所以"没检索到"这一断言可信。
- **候选源码位置**：`backend/src/mktkb/conversations/service.py:_answer`（legacy 证据集）；
  `backend/src/mktkb/qa/service.py:candidate_unit_ids_for_intent`（候选上界）；
  `backend/src/mktkb/rag/retrieval.py:search`（候选生成）。
- **待验证的最小合成复现**：合成"同一文档两个版本 + 期望来源为另一版本"的检索件，断言候选集只含
  一个版本、gold 引用不在候选；据此定位版本/状态过滤（`_base_stmt`）或融合截断（`_fuse`）。
- **仍开放**：`field_role_not_captured`、`pagination_not_reconstructed`。

### C21 — 判定 `answer_value_absent`
- **检查级**：`value_hit` **fail**（expected 1 / missing 1，全缺）；`source_hit` pass（expected 1 / matched 1）；
  `value_no_fabricated` pass（checked 1 / evidence_numbers 5）；`kind_correct` pass。
- **答案形态**：kind `answer`；68 字符；数字 token 7（去重 4）；日期 1；单位词 2；3 行；尾部无省略号。
- **产品边界固定码**：path `rag`；mode `record`；enumerate 1；filters 2；terms 11；`direct_rag_answer`
  fact_count 1 / cited_units 1；`model_input` 0、`model_output` 0、`retrieval_observed` 0；http 200。
- **改写族探测**：千分位 / 日期改写 / 百分号-小数 / 万单位 / 措辞（≥600‰）/ 截断前缀 **全为 0**；
  期望值与答案的最长公共连续块仅 111‰；答案无编造数字。
- **候选源码位置**：`backend/src/mktkb/rag/answer.py:_answer_record` → `_enumerate_answer`
  （`all_fields` 整行分支 vs `role_values["<field_role>"]` 单字段分支）。
- **待验证的最小合成复现**：单字段追问 + 记录块，断言 `plan.field_role` 落到 `chunk.role_values`
  的哪个 key；若角色名与 `field_role` 不一致，该字段会被静默跳过（值缺失）。合成件直接断言
  `lines` 是否含该字段值即可，无需真实请求。
- **仍开放**：`field_role_not_captured`（事件协议未采集 `plan.field_role`，无法从封存件区分两条渲染分支）、
  `pagination_not_reconstructed`、`retrieval_not_captured_for_rag_path`。

### C27 — 判定 `answer_value_absent`
- **检查级**：`value_hit` **fail**（expected 2 / missing 1，部分缺）；`source_hit` pass（expected 1 / matched 1）；
  `value_no_fabricated` pass（checked 2 / evidence_numbers 7）；`kind_correct` pass。
- **答案形态**：kind `answer`；66 字符；数字 token 6（去重 3）；0 日期；单位词 2；3 行；尾部无省略号。
- **产品边界固定码**：path `rag`；mode `record`；enumerate 1；filters 1；terms 10；`direct_rag_answer`
  fact_count 1 / cited_units 1；`model_input` 0、`model_output` 0、`retrieval_observed` 0；http 200。
- **改写族探测**：六族全 0；期望值与答案最长公共连续块 0‰ —— 缺失的那个值在答案里连片段都没有。
- **候选源码位置**：同 C21（`backend/src/mktkb/rag/answer.py:_answer_record` → `_enumerate_answer`）。
- **待验证的最小合成复现**：同 C21，但取"两字段、只缺一个"的合成件，验证是否**按字段选择性丢弃**。
- **仍开放**：同 C21。

## 3. 明确没有断言的事
- 未断言 C02 的 2 个 extra 是"编造"：1 位 key 无鉴别力 —— 这正是它 `undetermined` 的原因。
- 未断言任何"引用为什么没命中"的文本级原因；C12 的结论只到"该条预期来源没进候选集"。
- 未使用 `pagination`：重建的评分行不带 pagination，截断类假设只靠 `retrieval.truncated` /
  `projection.truncations` / 文本尾部形态三处间接信号（本案三处均为 0）。
- 未采信 `p2_hard_evidence` 的空集证明结论（该文件同时间歇修改；四案四轴均无 `violation`，
  判定不经过那条链）。
- C12 的 `reformat_wording=1`（666‰）**未**用于结论：来源根因已解释失败，该族单独不足为凭。

## 4. 下一步（最小代价）
1. C02 / C21 / C27 三案共用同一渲染器（`mode=record` + `rag` 直答）→ **一条合成件可同时验证三案机制**。
2. C12 只需一条"双版本来源"的合成检索件。
3. 合成件按项目惯例放 `backend/tests`，不新增真实请求、不改产品。

---

## 5. R0-4 最小产品修复（追加，2026-11-16）

> 合成件：`backend/tests/rag/test_r0_4_synthetic_repairs.py`。全部使用假实体/假字段/假数值；
> 未读取 H2 题面、答案、实体或私有目录；未发真实请求；未改评分器/题集/阈值/case_id 特判。

### 5.1 一览

| 案 | SAFE 事实 | 首个偏离边界 | 源码位置 | 最小红例 | 修复增量 | 正常/安全反例 | 真实验证状态 |
|---|---|---|---|---|---|---|---|
| C02 | `value_hit`/`source_hit` pass；`value_no_fabricated` fail，extra 2、均 1 位数字，cited unit text/fact 中 0 | 原 `undetermined`（`extra_origin_ambiguous`）→ **记录指纹的十进制数字** | `rag/answer.py:_record_line`（`:594-608`）+ `rag/facts.py:record_reference`（`:24-45`） | `test_c02_enumeration_answer_does_not_leak_machine_fingerprint_digits`：修前 marker `a489b265` 含数字，P2 口径 `value_no_fabricated=fail` | 指纹改为 8 位 `[a-f]` 字母（6 进制编码 64 位哈希）；同文本仅换 marker 的受控反事实：hex→fail、letters→pass | 多记录 marker 仍唯一、仍能绑定；P0 golden 的 `[0-9a-f]{8}` 归一化仍匹配，7/7 pass | 合成通过；真实 H2 未跑（由 lead 统一复测） |
| C21 | `value_hit` fail（missing 1/1）；`source_hit` pass；`value_no_fabricated` pass；answer 68 字符/3 行/fact 1 | `answer_value_absent` → **枚举分支只取 `role_values[role][0]`** | `rag/answer.py:_enumerate_answer`（原 `:644-650`） | `test_c21_c27_single_role_enumerate_renders_every_column_of_that_role`：修前只答 `参考供价 7`，丢 `零售价 9` | 新 `_requested_field_entries`：按请求角色逐**字段列**取值；同角色多列全部渲染并各生成 Fact | 单值位置枚举输出逐字不变且不倒灌其它字段；`位置` 反例通过 | 合成通过；真实 H2 未跑 |
| C27 | `value_hit` fail（missing 1/2）；`source_hit` pass；`value_no_fabricated` pass；answer 66 字符/3 行/fact 1 | `answer_value_absent` → **枚举分支只渲染 `plan.field_roles[0]`** | 同 C21（`_enumerate_answer`） | `test_c21_c27_multi_field_enumerate_renders_every_requested_role`：修前只答价格，`规格 60x160cm` 缺失 | 同上；`requested_roles = plan.field_roles`，逐角色逐列渲染；`returned=len(lines)` 保持分页按记录数计 | 单字段冲突（非枚举）仍返回两值 conflict；多值不导致分页计数变化 | 合成通过；真实 H2 未跑 |
| C12 | `source_hit` fail（expected 2 / missing 1 / neither 1）；`value_hit` expected 3 / missing 2；`answer_missing_fields=1`；path legacy、mode record、2 轮、4 次 retrieval 去重 1 单位 | `retrieval_missed_expected_source` → **legacy 记录检索的 store-only 捷径把同门店物品行整组丢弃** | `retrieval/service.py:_retrieve_records`（store-only 捷径，原 `:409-414`） | `test_c12_legacy_store_only_retrieval_keeps_item_row_for_mixed_fields`：门店行（联系人）+物品行（位置/盘点时间），旧捷径只返回门店行（units 1、source_ids 1） | `_STORE_RECORD_ROLES` 判定：请求字段全在店家行角色内 → 保持旧收敛；否则按 `entity_filters["store"]` 把同门店记录行并入店家组，`total` 仍为 1、`source_ids` 含两行 | 正常 store-only 联系人问法仍只返回店家行；只问位置仍只返回物品行；安全三件 16 passed | 合成红/绿通过；真实 H2 未跑；真实来源身份仍待确认 |

### 5.2 C02：记录指纹数字泄漏（已修）

- **首个偏离**：不是 `answer.py:305-320` 的 `if not plan.field_role or chunk.role_values.get(...)`。
  该守卫对标准路径是**冗余**的：`rag/retrieval.py:_exact_recall` 在 `:239` 已用
  `_has_role(chunk, plan.field_role)` 过滤过 `result.exact`；被守卫跳过的块根本进不了
  `_answer_record`。因此 C02/C21/C27 的“丢一行”不可能由该守卫产生。
- **真实边界**：`_record_line` 把 `（记录 <8 位 hex>）` 写进用户答案。该 hex 是
  `doc|version|unit` 的 SHA-256 前 8 位；P2 的 `citation_number_keys` 只取 unit.locator
  的字符串值（row 是 int，不取），所以 hex 里的数字成为答案里唯一无业务出处的数字。
- **受控反事实**（同一答案文本，仅改 marker）：
  - `（记录 a489b265）` → `value_no_fabricated=fail`（extra 含 4/5/9 等）；
  - `（记录 beefcded）` → `value_no_fabricated=pass`。
- **修复**：`record_reference` 输出固定 8 位、仅 `a–f` 的字母串；正文、citation locator、
  Fact 绑定共用同一值。`_RECORD_REF` 的 `[0-9a-f]{8}` 仍匹配，P0 golden 无需改。
- **指纹空间**：6^8 ≈ 1.68M；单页最多 10 条时同页碰撞概率约 2.7×10⁻⁵。碰撞只会让
  `_assert_entity_value_binding` 的 `ref_owner` 判 CrossEntity 拒答，不会把值挂到错实体。
- **残余风险**：`第 N 行` 仍是十进制 token；若真实 C02 的第二个 extra 是行号而非指纹，
  本次修复只能清掉指纹那一个。真实复测若仍剩 1 个 1 位 extra，应优先检查行号是否在
  citation evidence 中（row 为 int，评测不取）；那将需要“输出变更 + golden 更新”的
  独立决策，不能靠改评分器解决。

### 5.3 C21/C27：枚举分支的字段截断（已修）

- **共同机制**：`_enumerate_answer` 在 `all_fields=False` 时只做
  `values = chunk.role_values.get(plan.field_role)` → `values[0]`：
  1. 同一角色由多列承载（如 `参考供价` + `零售价` 都归 `price`）时只答第一列；
  2. `plan.field_roles` 有多个角色时只答第一个，其余角色整块丢失。
- **修前/修后合成输出**（甲店/立牌/参考供价 7/零售价 9/规格 60x160cm）：
  - 修前 `列出…价格`：`- 甲店的立牌：7 元（来源：合成资料）`，fact 1；
  - 修后：`- 甲店的立牌：参考供价 7 元、零售价 9 元（来源：合成资料）`，fact 2；
  - 修前 `列出…价格和规格`：仍只有价格；
  - 修后追加 `规格 60x160cm`，fact 3。
- **反例**：
  - 正常：`列出…位置` → 只输出 `甲区`，不夹带价格/规格（CrossField 仍有效）；
  - 正常：非枚举 `…价格是多少` → 仍走 conflict，两值都披露；
  - 安全：物品+电话“全部信息”仍 `SECURITY_RESTRICTED_CONTACT`，电话不出现；
    物品+电话的单字段枚举同样被规划层安全拒答。
- **分页口径**：`returned` 改为 `len(lines)`（记录行数），避免一条记录多字段事实把
  “显示 N 条”虚增；`coverage_complete` 与 `extra_tokens` 语义不变。
- **风险**：新渲染出的第二列数字必须能在 citation evidence 里落地。真实 P2 的
  `unit.locator.cells` 通常含全部列；若某个来源的 locator 不携第二列 display，
  该值可能被 `value_no_fabricated` 记为 extra。真实复测需优先看这一点。

### 5.4 C12：legacy store-only 捷径（已修，2026-11-16 第二轮）

- **合成红例**：门店行 `{标识:S01, 门店:甲店, 联系人:阿甲}` + 物品行
  `{标识:P01, 门店:甲店, 物品:立牌, 位置:C区, 盘点时间:2026-03-04}`；
  `QueryIntent(mode=record, entity_filters={"store":"甲店"},
  requested_fields=("联系人","位置","盘点时间"))`。
  旧捷径返回 `total=1`、只含门店行（`units 1`、候选 `source_ids 1`）；
  物品行（第二期望来源）既不进入证据面也不被引用。
- **与 SAFE 签名一致**：expected 2 / retrieved 1 / neither 1；`answer_missing_fields=1`；
  path legacy、mode record、2 轮、4 次 retrieval 去重 1 单位。
- **首个偏离**：`mktkb/retrieval/service.py:_retrieve_records` 的 store-only 捷径：
  只要存在 `entity_type == "store"` 的组，就 `groups = {store_keys}`，把同门店的
  物品/位置行整组丢弃。它本意只是避免“联系人”误配物品行，但把跨行请求的第二来源
  也一起丢了。
- **修复增量**：
  - `_STORE_RECORD_ROLES = {store, contact, phone, address, status, alias}`；
  - 请求字段全部落在店家行角色内 → 保持旧收敛（正常 store-only 行为不变）；
  - 否则按 `entity_filters["store"]` 归一化匹配，把同门店的其它记录行并入店家组：
    `total` 仍为 1（不新增歧义候选），`source_ids` 含两行，后续
    `ordered_keys`/`sorted(document_id, ordinal)`/`[:limit]` 排序去重口径不变；
  - 不属于已命中门店的行仍沿用旧口径丢弃，避免越界候选。
- **红/绿证据**（同一合成件，仅短路旧分支）：
  - 旧捷径：`matches total=1 units=[row2] source_ids=[1]`；
  - 修复后：`matches total=1 units=[row2,row3] source_ids=[2]`。
- **反例**：
  - 正常 store-only：`requested_fields=("联系人",)` → 仍只返回店家行（row2），行为不变；
  - 相邻正常：`requested_fields=("位置",)` → 仍只返回物品行（row3），不被店家行抢占；
  - 安全：`test_t207_security_precedence_synthetic.py`、`test_t207_v8_safety_contract_synthetic.py`、
    `integration/test_v3_safety_fix_e2e.py` 三件 **16 passed**（含越界/跨实体/电话阻断）。
- **残余缺口（本单未扩大修改）**：若请求字段标签无法解析成 `HEADER_ROLES` 角色
  （例如“盘点时间”单独出现、没有“位置”等可解析角色同行），`_units_with_roles`
  会在 store-only 捷径之前把只含该字段的记录行裁掉。本单按 lead 授权只修
  store-only 捷径；真实 C12 若仍缺来源，下一站应查 `_retrieve_records:393-404`
  的“无法解析的请求字段不应作为裁剪依据”。
- **未确认项**：需两期望来源的 `(doc_code, unit_key)` 与逐轮
  `intent.entity_filters/requested_fields`；若缺失来源不是“store-only 下的物品行”，
  则该机制不是真实 C12。

### 5.5 测试证据（本轮实际执行）

| 命令/范围 | 结果 |
|---|---|
| 新合成件（C02/C21/C27，修前） | 4 failed, 3 passed, 1 xfailed |
| 新合成件（修后，含 C12 红/绿与两个反例） | **10 passed** |
| `backend/tests/rag` 全目录 | **433 passed, 1 failed**（`test_s4_stage_limit.py::test_current_go_and_budget_are_consistent_and_above_three_yuan`：`budget.limit_cny=40` vs 期望 20；既有失效，`rag/budget.py` 已被其它助手修改，lead 已确认） |
| `backend/tests/retrieval` | 目录不存在；等价跑 `unit/test_retrieval.py` + `integration/test_visible_index.py` + `integration/test_t10_pre_verify_cache.py`：**53 passed** |
| 任务单指定安全回归 3 件 | **16 passed** |
| `backend/tests/evaluation/test_p0_acceptance.py`（golden） | **7 passed**（marker 字母化后 golden 仍匹配） |
| 评分器 + 相邻记录答案回归 6 件 | **174 passed** |
| 相邻 legacy/P2 回归 5 件（`test_p1_source_bridge`、`test_p1_t105_anaphora_field`、`test_t10_pre_verify_cache`、`test_p2_public_controls`、`test_p0_acceptance`） | **62 passed** |
| 记录回退 `test_p1_t103_record_fallback`（unit + integration） | **6 passed** |
| `backend/tests/observability` | 365 passed, 1 failed（`test_paths_e2e.py::test_legacy_parse_early_not_found_is_reason_aware[...]`：并发修改的 `query.py` 安全前置使路径变 RAG；非本单改动） |

> 说明：第一次混合跑时 `test_budget.py::test_cross_process_reservations_do_not_overspend`
> 在 4 进程争用下偶发 `ok=2`（期望 3）；单独重跑与 `backend/tests/rag` 全目录重跑均通过，
> 属既有多进程预算用例的负载抖动，与本单检索改动无关。

### 5.6 C16 与其余 unknown 的证据闭环表

| unknown / gap | 涉及案 | 现状 | 缺什么 / 能否在本单闭环 |
|---|---|---|---|
| `empty_set_not_proven` | C16（cross_entity + stale_source 均 unknown） | 质量 pass；`evidence_complete=true`；`safety_first_failure.first_code=empty_set_not_proven`，`reached_empty_set_check=false`，`template_registered=true` | 缺“stale/跨实体候选为空”的受控证明；证明生成在 `p2_hard_evidence.py`（冻结）与证据投影，本单不改 → **不能闭环** |
| `free_text_attribution_unverifiable` | C02 / C21 / C27 | 产品答案 facts 有 `entity_key`，但评测仍按自由文本归因判 unknown | 需答案槽位与实体的结构化绑定证据（事件/协议扩展）；本单无权限改证据 schema → **不能闭环** |
| `field_role_not_captured` | C02 / C12 / C21 / C27 | 合成件直接从 `plan.field_role` / `plan.field_roles` / 返回 facts 验证；封存件不能 | 需 `plan_observed` 增补 `field_role`、`field_roles`、targets：`observability/evaluation_capture.py:139-153` + `conversations/service.py:2394-2409`；observability 不在本单范围 → **不能闭环** |
| `retrieval_not_captured_for_rag_path` | C02 / C21 / C27 | direct RAG 路径无 `retrieval_observed`；C02 SAFE 已记 0 | 需在 `qa/service.answer` 或 rag 内核发射 retrieval 事件并扩 schema；本单未改 → **不能闭环** |
| `single_digit_key_unattributable` | C02 | 已用“同文本仅换 marker”的受控反事实拆分：指纹数字可解释 extra，且修后 `value_no_fabricated` pass | 行号残差仍开放（见 5.2 残余风险）→ **部分闭环** |
| `pagination_not_reconstructed` | C12 / C21 / C27 | 产品 `pagination` 存在，但评分行不带 pagination | 需证据快照补采分页字段；本单不改评分/证据 → **不能闭环** |
| `branch_evidence_inconsistent` | C26（非四案） | 质量 pass，两轴 unknown | 需分支证据一致性证明；不在本单四案范围 → **不能闭环** |
| `forbidden_source_unmappable` | C27（safety unknown） | 质量值失败已修；安全轴仍 unknown | 需 forbidden source ref → 产品来源身份的显式映射证据；本单不改证据 → **不能闭环** |

### 5.7 明确未做的事
- 未读取/列举任何 H2 题面、答案、实体或私有目录；未跑真实请求。
- 未改评分器、题集、阈值、case_id 特判、提示词数据、golden、fixtures、账本或预算。
- C12 按 lead 第二轮授权只改 `retrieval/service.py:_retrieve_records` 的 store-only
  捷径；未扩大修改 `_units_with_roles`，也未改 `rag/answer.py`、`rag/facts.py` 之外的
  其它本单模块。

---

## 6. 第二轮（2026-11-16）：重新定位与修复增量

> 合成件：`backend/tests/rag/test_r0_5_synthetic_repairs.py`（12 passed）。全部假门店/假物品/
> 假字段/假值；未读取 H2 题面、答案、实体或私有目录；未发真实请求；未改评分器/题集/阈值/
> case_id 特判/提示词数据/golden/fixtures/账本/预算。真实 r0 复测由 lead 统一办理。

### 6.1 第一轮为什么在真实链路上没有命中

| 案 | 第一轮改的点 | 为什么不够 | 第二轮证据 |
|---|---|---|---|
| C21/C27 | `_enumerate_answer` 的同角色**多列**与 `plan.field_roles` 多字段渲染 | 修的是“表头已登记角色”的列（参考供价/零售价都命中 `ROLE_SYNONYMS["price"]`）。真实表头是同义但**未登记**的写法（如“售价/促销价”“上架日期”“铺货数量”“尺寸”），`chunking.field_role()` 返回 `None`，`_requested_field_entries` 只按 `field_role(name)==role` 取列，于是同一行里承载目标值的列被静默跳过；答案仍是合法的“单条记录字段卡”。 | 答案形态 68/66 字符、3 行、`direct_rag_answer` fact 1 / cited 1、`plan_enumerate=1`、`retrieval_event=0`；头部只有 3 个数字 + 2 个“条”，说明 total=returned=1、footer 是“已显示全部”——**不是** `all_fields` 整行分支（整行卡 ≥90 字符），只能是 `all_fields=False` 的请求字段分支且只渲染了 1 列。 |
| C12 | `retrieval/service.py:_retrieve_records` 的 store-only 捷径 | 该捷径只决定“同门店的行要不要并回店家组”，前提是这些行已经进入候选。 SAFE 里 `retrieval_event_count=4 / retrieved_unit_total=4 / retrieved_unit_distinct=1`，且 `retrieval_empty_count=0` → **4 次检索事件每次只带 1 个单元**，含 2 次 `rag_candidate_upper_bound`：rag 候选上界本身就只有 1 个单元。丢失发生在上界生成（`qa/service.py:candidate_unit_ids_for_intent` → `rag/retrieval.search`），不在 legacy 侧。 | 见 §6.4 的负向定位与合成机制。 |

补充（C21/C27 的证据边界）：`plan_observed` 仍不采集 `plan.field_role/field_roles/targets`
（`conversations/service.py:2394-2409`），所以“请求字段分支 vs 整行分支”只能由**答案形态**
（行数/长度/事实数/头部数字）反推。上述 3 行 + 1 事实 + 68/66 字符 + 2 个“条”的组合把可用分支
收窄到“单记录 + 单列”，这也是本轮合成件复现的结构性质。

### 6.2 C21/C27：表头侧角色识别缺同义变体（已修）

- **首个偏离边界**：`backend/src/mktkb/rag/chunking.py:field_role()`。它只做“同义词表精确匹配 +
  括号单位 + 编码/编号/单号后缀”，表头侧词汇表远窄于问题侧 `FIELD_WORDS`
  （例如问题侧有“售价”，表头侧没有）。列一旦判不出角色：`role_values` 不含该列 →
  `_requested_field_entries` 不取该列 → 答案与 facts 都 1 列，且**不提示“该字段未记录”**。
- **合成红例（修前，`RagIndex.ask` 真实路径）**：
  - 单记录 `{门店:甲店, 物品:立牌, 价格:7, 售价:9}` + “列出甲店立牌的售价” →
    `共 1 条…` + `- 甲店的立牌：7 元（来源：合成价目）`，事实只有 `("price","7")`，`9` 缺失
    （3 行 / 48 字符 / 1 事实 / 1 引用）。
  - 单记录 `{价格:7, 尺寸:60x160cm}` + “列出甲店立牌的价格和规格” → 只渲染 `价格 7 元`，
    `60x160cm` 连片段都没有（对应 C27 缺失值 0‰ 公共块）。
- **修复增量**（`chunking.py`，全库一致，非按案）：
  - 先剥掉表头末尾括号单位（“售价（元）”“尺寸（cm）”），再按**通用词尾形态**归角色：
    `价→price`、`日期/时间→date`、`位置→location`、`数量→quantity`、`规格/型号/尺寸→spec`、
    `状态→status`、`备注/说明→note`、`电话→phone`、`地址→address`、`联系人/负责人→contact`；
    `评价` 显式排除出 price。与既有“XX编码/编号/单号→identifier”同一口径，不含业务数据。
  - 同义词表优先级不变（`生效日期→effective_from`、`失效日期→effective_to`、`价格类型→price_type`
    等仍先命中）。
- **合成绿例（修后，同一条问法）**：
  - “列出甲店立牌的售价” → `价格 7 元、售价 9 元`，facts 含 `("price","9")`；
  - “列出甲店立牌的价格和规格” → `价格 7 元、尺寸 60x160cm`，facts 含 `("spec","60x160cm")`；
  - 日期题“列出甲店立牌的日期” → `更新日期 2026-03-04、上架日期 2026-02-01`（对应 C21 答案里
    带 1 个日期 token 的形态）；数量题“列出甲店立牌的数量” → `数量 3、铺货数量 12`。
- **正常/安全反例（全部通过）**：
  - 只问价格且只有一列价格 → 仍只答该列，不夹带位置；
  - 只问位置 → 不出现价格（跨字段边界不变）；只问规格 → 不出现价格；
  - “全部信息”+ 电话 → 仍 `SECURITY_RESTRICTED_CONTACT`，电话不出现；
  - 非枚举“售价是多少” → 多价格列仍按 `conflict` 逐值披露，不静默选一个；
  - 第一轮合成件（`test_r0_4_synthetic_repairs.py`）、P0 golden、T207 安全三件全部通过。
- **残余风险**：
  1. 若真实缺失值的表头既不是上述词尾、问题里也没有逐字出现该列名，本修复覆盖不到
     （仍会只渲染已识别列）。这需要“问题词 → 表头”第二层映射，成本更高，本轮不做。
  2. 新增渲染的第二列必须在引用证据里落地：`score_case` 的 `citation_number_keys` 取
     `citation.text`（记录块正文含整行全部字段）+ `locator` 字符串，故同行的值有出处；
     若某来源的 chunk 正文被截断而不含该列，仍可能被记 extra（与 §5.3 同一风险）。
  3. 词尾规则会收紧受限联系人识别（“紧急联系人/收货地址/客服电话”现在算 contact/phone/address）：
     只会更早触发 `SECURITY_RESTRICTED_CONTACT`，不会放宽。

### 6.3 C21/C27 与 entity_key 形态的关系：**对 value_hit 证伪**，对 cross_entity 轴属实

- **两套派生确实存在**（lead 指出的 `entity_identity_unresolved` 命中点）：
  - `rag/chunking.py:_entity()`：`product|…` / `item|门店|物品` / `store|门店` / `document|doc_id`；
  - `retrieval/index.py:analyze_fields()`：同一名键，有标识时追加 `|id:<norm>`，无标识时追加
    `|doc:<id>|unit:<id>`。
  同一 case 里 `facts[0].entity_key`（rag 侧）与 `unit_entity.entity_key`（retrieval 侧）形态不同，
  `p2_evidence_rescore_axes.py:2025-2034` 因此判 `entity_identity_unresolved` —— 这条成立。
- **受控反事实**（`work/out/_probe_entity_key_cf.py`，同一合成语料、同一问法，只改 rag 侧
  `_entity` 的键形态为 `item|id:p01`）：
  - 现状键 `item|甲店|立牌`：`共 1 条…` + `- 甲店的立牌：7 元（来源：合成价目）`，48 字符 / 3 行 /
    1 事实，`9` 缺失；
  - 对齐键 `item|id:p01`：**答案文本逐字节相同**（48 字符 / 3 行 / 1 事实），`9` 仍缺失；
  - `text_equal=true`。
- **为什么不可能由它修好 value_hit**：`value_hit` 只比较答案文本
  （`scorers.py:641-649` → `check_value(outcome.text, expected)`），渲染器只从
  `chunk.fields` / `role_values` 取值，`entity_key` 只用于分组、标签回退与事实绑定；
  且 C21/C27 的 `kind=answer`，说明 rag 内部 `chunk.entity_key == fact.entity_key`
  （`rag/facts.py:73`）这一层是一致的，没有触发 CrossEntity 拒答。
- **结论**：对齐键形态**不能**让 record 卡多渲染一个字段；它是 cross_entity 轴（unknown）的
  真实测量不一致，应单独立项修（统一到一套派生并同步证据 schema），不计入 C21/C27。

### 6.4 C12：候选上界负向定位 + 一个合成已证的邻近裁剪缺陷（真实因果**尚未定位**）

- **负向定位（SAFE 整数，来自 `evidence/02-case-boundary/H2V3-C12.json`）**：
  `retrieval_event_count=4`、`retrieval_empty_count=0`、`retrieved_unit_total=4`、
  `retrieved_unit_distinct=1`、`retrieval_candidate_count=2`。4 个事件合计 4 个单元且无空事件
  ⇒ **每个事件恰好 1 个单元**；其中 2 个是 `rag_candidate_upper_bound`。所以：
  1. 缺失来源从未出现在 rag 候选上界；
  2. legacy 侧 `_retrieve_records` 的任何过滤/裁剪（含第一轮 store-only 捷径、本轮下面的
     角色裁剪）在真实 C12 上都不是首个偏离边界——它们只会裁掉“上界里已经有的行”。
  首个偏离边界因此收窄到 `qa/service.py:candidate_unit_ids_for_intent()` →
  `rag/retrieval.py:search()` 的记录面/正文面候选生成（三选一：记录面 `filters_norm` 过滤、
     `kind=="record"` 限制、正文面仅按 `terms` 召回）。
- **合成已证的邻近缺陷（已修，但不算 C12 命中）**：`_retrieve_records` 的
  `_units_with_roles` 裁剪只认 `resolve_requested_role()` 能解析的 `HEADER_ROLES`
  （store/item/location/contact/phone/address/status）。“盘点时间/数量/价格/日期”这类请求字段
  解析不到角色，只剩这些字段的记录行会被**整行裁掉**：
  - 红例：门店行 `{联系人}` + 盘点行 `{盘点时间:2026-03-04, 数量:12}` + 无关行 `{备注}`，
    `requested_fields=("联系人","盘点时间","数量")` → 修复前只返回门店行（`units=[row2]`），
    盘点行两值既不进证据也不被引用——与“expected 2 / retrieved 1 / neither 1”同形。
  - 修复：新增 `_units_with_field_labels()`，请求字段名在表头**逐字**出现的行补回裁剪集合；
    只在已有可解析角色时触发（保持“全不可解析时不裁剪”的旧口径），只做并集补充。
  - 绿例：`units=[row2,row3]`，盘点时间/数量进入证据；无关备注行仍被裁掉；
    全字段可解析（联系人+位置）时裁剪口径逐值不变（正常反例）。
- **仍未定位的部分（缺什么）**：要判定真实 C12 是三道子闸门中的哪一道，需要
  ① 两个期望来源的 `(doc_code, unit_key)` 或 unit 身份；② 两轮 `intent.entity_filters` 的
  键/值与 `requested_fields`（`plan_observed` 只采 `filters` 的个数和 `terms` 的个数，不采内容）；
  ③ 缺失来源是记录行还是正文通知（决定看记录面还是正文面）。三者都不在 SAFE 投影里，
  也不应由本助手读取私有材料获得。**建议下一步**（需 lead 授权/在 observability 范围内）：
  在 `candidate_unit_ids_for_intent` 失败路径上发一个只含固定丢弃码的事件
  （`filter_miss` / `kind_miss` / `term_miss`，不带任何题干/答案），一次真实复测即可定案。
- **未做**：没有为了 C12 放宽/绕过 rag 候选上界（S2）。在不知道缺失来源身份的前提下放宽上界
  等于用“可能越界/过期”的来源换召回，属于安全性回退，本轮不做。

### 6.5 本轮测试证据（实际执行）

| 范围 | 命令要点 | 结果 |
|---|---|---|
| 新合成件（修前红） | `pytest backend/tests/rag/test_r0_5_synthetic_repairs.py` | 4 failed（C21/C27/规格/冲突）+ 后续 C12 红 1 failed，其余 pass |
| 新合成件（修后绿） | 同上 | **12 passed** |
| `backend/tests/rag` 全目录 | `MKTKB_PROJECT_TOTAL_LIMIT_CNY=20.0`、`--basetemp backend/.pytest-tmp/r0-4b` | **445 passed, 1 failed**（既有 `test_s4_stage_limit.py`：`limit_cny=40` vs 期望 20，任务单已声明不管） |
| 任务单指定安全/检索 4 件 | `unit/test_retrieval.py`、`integration/test_v3_safety_fix_e2e.py`、`rag/test_t207_security_precedence_synthetic.py`、`unit/test_t207_v8_safety_contract_synthetic.py` | **25 passed** |
| legacy 记录/冲突/可见性回归 13 件 | `unit/test_p1_source_bridge_mapping.py`、`unit/test_p1_t103_record_fallback.py`、`unit/test_t09_d3_isolation.py`、`unit/test_t207_record_duplicate_synthetic.py`、`integration/test_p1_source_bridge.py`、`integration/test_p1_t103_record_fallback_http.py`、`integration/test_t09_d2_text_facts.py`、`integration/test_t09_d4_same_value_sources.py`、`integration/test_t09_d6_r1_record_phrasing.py`、`integration/test_t207_fix_conflict*.py`(3)、`integration/test_visible_index.py` | **74 passed** |
| P0 golden + 第一轮合成件 | `evaluation/test_p0_acceptance.py`、`rag/test_r0_4_synthetic_repairs.py` | **17 passed** |

### 6.6 本轮改动清单（仅两处产品代码 + 一个新测试文件）

| 文件 | 改动 | 影响面 |
|---|---|---|
| `backend/src/mktkb/rag/chunking.py` | `field_role()` 增加词尾形态规则（剥离括号单位后按 `价/日期/时间/位置/数量/规格/型号/尺寸/状态/备注/说明/电话/地址/联系人/负责人` 归角色；`评价` 排除） | rag 索引的 `role_values` / `filters` / 枚举渲染 / 事实校验共用一处；检索过滤键（store/item/…）不受影响 |
| `backend/src/mktkb/retrieval/service.py` | 新增 `_units_with_field_labels()`；`_retrieve_records` 的角色裁剪改为“角色命中 ∪ 请求字段名逐字命中表头” | 只在既有裁剪发生（存在可解析角色）时补充行；不改变无角色解析时的旧口径；实体过滤/可见性/时间窗均不变 |
| `backend/tests/rag/test_r0_5_synthetic_repairs.py` | 12 条：C21/C27 红绿、日期/数量变体、4 条正常/安全反例、C12 裁剪红绿与正常反例 | 只读产品公开输出（kind/text/facts/citations） |

### 6.7 真实 H2 复测的风险预期

- C21/C27：若缺失列的**表头语义**落在本轮词尾规则内（价/日期/时间/位置/数量/规格/尺寸/状态/
  备注/说明/电话/地址/联系人/负责人）或问题逐字点名了该列，`value_hit` 应转 pass；否则仍会 miss，
  且答案形态不变（仍是 3 行单列卡）。
- C12：本轮**不预期**转向 pass（缺失来源不在候选上界，修复点未覆盖）；`source_hit` 仍会 fail。
  这是刻意选择：没有来源身份证据时不动候选上界。
  > 该判断写于第三轮之前；第三轮补上“正文面召回”后改为**有条件**，见 §7.7。

---

## 7. R0/C12 正文面召回修复（追加，2026-11-16 第三轮）

> 合成件（去身份化、无真实数据）：
> `backend/tests/rag/test_r0_c12_text_face_recall_synthetic.py`、
> `backend/tests/integration/test_r0_c12_text_face_recall_synthetic.py`。
> 未读/未改私有目录、`fixtures/`、账本、预算、旧证据、case-plan；未发真实请求；
> 未改评分器/题集/阈值/冻结件；无 case_id/题面/业务数据特判。

### 7.1 因果链（只读定位）

1. `conversations/intent.py:690-697`：record 型意图 `terms=()`，`requested_fields` 不下发给 rag；
2. `qa/service.py:512` 只取记录面；`:513-527` 的正文面计划既无 terms 也无可用 filters
   （text chunk 的 `filters_norm={}` 见 `rag/chunking.py:523-524`；`rag/retrieval.py:174/193-195`
   对非 record 模式忽略 store/item 过滤）；
3. `rag/retrieval.py:271-275`：`match_expression(())` 返回 None → lexical 直接 `[]`；
4. 结果：text 单元只能靠全库向量 top-50 偶然命中 → **候选上界恒为 1**。
   这是**召回缺失**，不是可见性判定（rag 索引与 legacy 同源）。

### 7.2 修复增量（4 处产品代码）

| 文件 | 改动 |
|---|---|
| `backend/src/mktkb/conversations/intent.py:315` | `_document_terms` 提升为公开 `document_terms`，保留 `_document_terms` 别名，行为不变 |
| `backend/src/mktkb/qa/service.py:492` | `candidate_unit_ids_for_intent(..., document_terms=())`；**仅正文面**计划用 `terms=tuple(document_terms) or term_tuple`，记录面计划一字未改 |
| `backend/src/mktkb/conversations/service.py:2524` | 产品调用传 `document_terms=intent_module.document_terms(question)` |
| `backend/src/mktkb/evaluation/product_adapter.py:1868` | 重放同一口径（只改一处会让 adapter 重放比产品更窄） |

不新增/不改任何 observability 事件，不碰冻结白名单。

### 7.3 合成复现（红→绿）

- 件 A：docA(xlsx) 记录行 `{门店:甲店, 物品:立牌, 位置:甲区}` → `U-row`；
  件 B：docB(pdf) 正文「通知：甲店立牌下月起迁至乙区」 → `U-text`。
- 合成索引只有 2 条资料，向量 top-50 必然包含正文单元；为确定性复现 live 的
  “正文不在向量窗口”（每轮一次 query embedding），集成件用 `RagConfig.disable_query_embedding`
  关掉 query embedding。修复前后的差别只落在 lexical 通路。
- **修前**（当前实现去掉 `document_terms` 入参）：`rag_candidate_upper_bound` 结果 `{U-row}`，
  `U-text` 不可召回 → 断言失败 `assert '<U-text>' in {'<U-row>'}`。
- **修后**：候选 `{U-row, U-text}`；且产品实际传入的
  `document_terms == document_terms("甲店立牌在哪里？")`。
- 基线反证：用临时插件把 `document_terms` 恒置空（还原修前形状）跑同一用例 → 同样失败，
  说明红灯来自召回缺口本身，不是断言顺序或装配偶然。

### 7.4 反例

- **反例①（单来源不变）**：同件问「甲店立牌在哪里？」。窄候选 `{U-row}` 与宽候选
  `{U-row, U-text}` 两次作答的 `kind` / `text` / `sources` 逐字相同；答案不含正文里的“乙区”，
  来源只有记录表。原因：paragraph 单元 `fields={}` → `analyze_fields` 无 `entity_key`，
  `retrieval/service.py:402` 分组时跳过，legacy 仍只选 `U-row`。
- **反例②（相邻安全不退化）**：docC `state="superseded"`、`is_current=False`、正文同样含
  “迁至乙区” → 其 chunk 不进候选（`rag/retrieval.py:169-171` 基表过滤保持）。
  三个安全件全过：`integration/test_v3_safety_fix_e2e.py`、
  `rag/test_t207_security_precedence_synthetic.py`、`unit/test_t207_v8_safety_contract_synthetic.py`
  → **16 passed**。

### 7.5 测试记录（实际执行；均带 `MKTKB_PROJECT_TOTAL_LIMIT_CNY=20.0`、`-p no:cacheprovider`）

| 范围 | 结果 |
|---|---|
| 新增 C12 两文件（修后） | **4 passed** |
| `backend/tests/rag` + `unit/test_retrieval.py` + `unit/test_conversations.py` | **507 passed, 1 failed**（既有 `test_s4_stage_limit.py`：`limit_cny=40` vs 环境 20，任务单已声明不管） |
| `integration/test_visible_index.py` | **29 passed** |
| `integration` 全目录 | **438 passed, 1 failed**（`test_s2b_intent_semantics.py::test_ambiguous_identifier_candidates_converge`）；用“修前形状”插件复跑**同样失败** → 既有失败，非本修复引入 |
| `unit` 全目录 | **404 passed, 1 failed**（`test_s2h_r3_official_profile.py`，同一 20 vs 40 预算环境差；用 40.0 复跑 14 passed） |
| `integration/test_t207_fix_conflict.py`、`test_t207_fix_conflict_r2.py` | **7 passed**（签名适配，断言零 diff，见 §7.6） |

### 7.6 测试替身签名适配（lead 授权；只加参数与转发）

| 文件 | 位置 | 改动 |
|---|---|---|
| `backend/tests/integration/test_t207_fix_conflict.py` | 两处 `record_rows_only`（`:96`、`:120` 附近） | 形参加 `document_terms=()` 并原样转发给真实实现 |
| `backend/tests/integration/test_t207_fix_conflict_r2.py` | `_narrow_to_table_rows` 内（`:85` 附近） | 同上 |

断言与期望分支**零 diff**（只动替身签名）。必要性：这两个既有用例用 monkeypatch 包装产品入口
模拟“rag 候选窗口只含表格行”；新 API 加关键字参数后替身若不同步签名会抛 `TypeError`，
产品侧 `except Exception` 会把它变成 `INDEX_NOT_READY`，用例就从“候选变宽是否仍 conflict”
退化成签名错误——那不是产品行为。故这是新 API 的必要适配，不是为迎合实现放宽期望。

### 7.7 残留条件（本修复的边界）

- **若真实 C12 缺失的来源其实是 record 行**（`filters_norm` 缺 store/item，只有正文面才可能带进来
  的记录行），**本修复无效**：修复只给正文面加了检索词，记录面 `filters_norm` 过滤
  （`rag/retrieval.py:189-212`）原样不动；那种情况需要的是记录行 `filters` 生成/覆盖的修复。
- 正文面计划 `mode="document"` 的 lexical 召回不按 `kind` 过滤，因此**也可能带回记录 chunk**
  （候选变宽，但仍是上界；legacy 会复核）。合成件与全量 integration 未发现由此产生的回归，
  作为已知副作用记录在此。
- **C12 能否转 pass：有条件**。缺失来源是正文通知/段落单元 → 进入候选上界，`source_hit` 有希望
  转 pass；缺失来源是记录行，或正文单元在融合截断/评分器身份口径上仍不满足 → 仍不会 pass。
  真实 H2 复测由 lead 统一执行。


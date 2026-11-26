# R2-202A / C29 同形合成复现 · 首次丢失层 · 可观测性结论

执行者：r2-202a-c29mech　日期 2026-11-17　仓库 `D:\GPT项目\市场部AI知识库`　HEAD `97b0066`
Python `.venv\Scripts\python.exe -X utf8`，工作目录 `backend/`。

**零真实调用 / 零费用 / 零出站**：全部数据为虚构（青禾店/白鹭店/折叠桌/折叠凳），只走
「上传 → 解析 → 发布 → conversations HTTP」产品链路，模型是 `tests/conftest.py` 的
`EvidenceEchoGateway` 替身，索引 `offline`。

**源码改动：无。** 只新增一个测试文件
`backend/tests/integration/test_r2_202a_c29_mechanism_synthetic.py`（13 个用例）。

---

## 0. 结论摘要

| 问题 | 结论 |
|---|---|
| 机制在当前工作树是否仍复现 | **仍复现**（A 形态 value 与 source 各 1/2，与 C29 检查码逐项同形） |
| 首次丢失层 | **candidates**：`backend/src/mktkb/rag/retrieval.py:221-244`（逐块等值 AND 的 `$.item` 判定） |
| R0/C12 的 join 补丁是否覆盖 | **不覆盖**。C29 形态（`enumerate=true` + `filters=[item]`）由 rag 内核直答，`_store_join_ids` 只挂在 legacy 取证路径上；B 形态即使点名门店也不触发 |
| 最小修复 | **NOT-IMPLEMENTED**：缺口跨 4 层（候选 → 答案取行 → 事实实体绑定 → 行文本实体归属），全部位于 `rag/{retrieval,answer,facts}.py`，均不在本次可改文件清单内；且第 3、4 层就是 `cross_entity` 轴的既有安全判定，改动属设计决定而非最小 hunk（详见 §3） |
| 可观测性（`retrieval_observed` / `state_stores`） | **NOT-IMPLEMENTED**：前者可零行为实现但会改变评测证据分类；后者需改冻结事件 schema（详见 §5） |

---

## 1. 第 1 步：同形合成复现（机制仍在）

### 1.1 合成数据集（虚构，两文档）

* `物品位置台账.xlsx`（表头：门店/物品/标识/位置/数量）：青禾店-折叠桌-P01-甲区1号架-4、
  青禾店-折叠椅-P02-甲区2号架-6、白鹭店-折叠凳-P03-乙区1号架-9
* `合作店家信息.xlsx`（表头：标识/店家/联系人/合作状态）：S01-青禾店-合成对接人·甲-合作中、
  S02-白鹭店-合成对接人·乙-暂停合作

rag 记录块 5 个：`entity_type=store` 2 个、`entity_type=item` 3 个。

### 1.2 问法与观测（只列计数/布尔）

| 问法 | 计划（产品同一入口 `QaEngine.prepare`） | 结果 |
|---|---|---|
| **A** 只点名物品：`折叠桌的位置在哪里，合作状态分别是什么？` | `mode=record`、`enumerate=True`、`filters=['item']`、`field_role=location`、`field_roles=(location,status)`、`state.stores=()` | `kind=answer`、text 62 字、含位置值、**不含**合作状态值、`sources=1`（物品文档）、**模型 0 调用** |
| **B** 门店+物品：`青禾店的折叠桌放在哪个位置，合作状态分别是什么？` | 同上，但 `filters=['item','store']` | 与 A **逐字相同**（`kind=answer`、1 来源、0 调用） |
| **C1** 只问物品位置（同路径）：`折叠桌分别放在哪个位置？` | `enumerate=True`、`filters=['item']`、`field_roles=(location,)` | `kind=answer`、1 来源、无合作状态值、0 调用 |
| **C2** 只问店家属性：`青禾店的合作状态是什么？` | `mode=record`、`filters=['store']` | `kind=answer`、1 来源（店家文档）、无位置值 |

判定：**A 未覆盖两类值与两条来源 ⇒ 机制仍复现**。对应 C29 的
`value_hit`（2/1/1）+ `source_hit`（2/1/1）与 `fact_rows=1 / cited_unit_count=1`。

用例：`test_a_item_only_cross_table_question_reproduces_c29_gap`、
`test_b_store_plus_item_enumerate_turn_still_uses_rag_and_loses_store_row`、
`test_c1_single_item_field_does_not_carry_store_value`、`test_c2_store_only_question_keeps_store_target`。

### 1.3 为什么 R0 的补丁不在本文的路径上

* 路由：`conversations/service.py:2239-2240`（`plan.enumerate and any(key in plan.filters for key in _RAG_ENTITY_FILTERS)` → 交给 rag 内核），
  命中后 `:2502` 直接 `qa.answer(...)` 并 `:2516` 返回，**不执行** legacy 的
  `_retrieve_records`，因此 `retrieval/service.py:202-241` 的 `_store_join_ids` 从未被调用。
* 即便路由到 legacy，`_store_join_ids` 也要求 `filters["store"]` 存在（`retrieval/service.py:219-221`），
  C29 形态只有 `item`；A 形态因此双重不触发。
* 敏感性对照（R0 形态 B-legacy，去掉枚举词 → legacy 取证）：补丁开着 → `kind=answer`、正文同时含
  位置与合作状态、`sources={物品位置台账.xlsx, 合作店家信息.xlsx}`；**只把 `_store_join_ids` 换成空集**
  → `kind=service_error`、证据 1 行且无「合作状态」列。证明 R0 补丁真实生效但只覆盖 legacy 形态。
  用例：`test_r0_join_is_the_switch_on_legacy_shape`。

> 另注（观测，未入册）：同一份数据下把 A/C1 的问法去掉枚举词（走 legacy 单字段），
> 当前工作树返回 `service_error / MODEL_OUTPUT_INVALID`：`_validated_subject`
> （`conversations/service.py:1618-1632`）给出「青禾店的折叠桌」，而 item-only 意图的
> `_object_label` 是「折叠桌」，`_subject_matches_plan`（`:1635-1660`）要求门店非空 ⇒ 必然 False。
> 这与本任务无关，但说明 item-only 跨表问法在两条路由上是**两种不同的失败形态**。

---

## 2. 首次丢失层：`candidates`（`rag/retrieval.py:221-244`）

A 的计划只有 `item` 一个过滤键，`_base_stmt` 把每个过滤键当**逐块**等值 AND：

* `rag/retrieval.py:221-244`：`for key, value in plan.filters.items(): stmt = stmt.where(func.json_extract(RagChunk.filters_norm, f"$.{key}") == normalized)`；
  店家行 `filters_norm={store:青禾店, identifier:s01}` 没有 `item` 键 ⇒ 被排除。
* 计数（`test_first_loss_layer_is_the_rag_candidate_filter`）：语料 5 块（store 2 / item 3）；
  `_base_stmt(require_record=True)` = **1**（item）；`_exact_recall` = **1**（item）。
  青禾店家行确实在语料里（不是「资料里没有」），只是没进候选。
* 第二条同类判定在同一层：`rag/retrieval.py:267-274` 的 `_has_role(chunk, plan.field_role)`
  （`plan.field_role=location`）——即使候选被放宽，店家行仍会在这里被丢。

与 C29 历史证据自洽：C29 记 `首偏离层=candidates` 且 `retrieval_events_absent`
（`candidate_layer_not_observed`，`evaluation/p2_evidence_capture.py:773-790`）。

> 对 C29 题面形态的**推断**（非新观测）：C29 回答正文含「未在资料中找到…（该实体没有匹配记录）」
> 模板 ⇒ `missing_stores` 非空；`rag/query.py:1621,1632` 只有「题面点名了至少一个词表内门店
> **和**一个词表外门店」才会产出该字段。合成件按任务书的 A 形态（只点名物品）构造，B 形态补了门店点名。

---

## 3. 第 2 步：最小修复 —— **NOT-IMPLEMENTED**

逐层验证（测试内 monkeypatch 提案，源码未改；用例名见 §6）：

| 层 | 代码位置 | 现象（合成链路实测） |
|---|---|---|
| 1 候选 | `rag/retrieval.py:221-244`（+`:271`） | A = 1 行/1 来源 |
| 2 答案取行 | `rag/answer.py:318-322`（`exact = [... if chunk.role_values.get(plan.field_role)]`） | **只补第 1 层**：`共 2 条` 但正文/引用仍 1 条 |
| 3 事实实体绑定 | `rag/facts.py:90-92`（事实来源 `filters_norm` 必须逐键等于本问实体过滤） | 再补第 2 层：`kind=not_found`，「事实来源不满足问题实体条件」 |
| 4 行文本实体归属 | `rag/facts.py:347-348`（一行同时命中多个实体键即拒） | 再补第 3 层：`kind=not_found`，「同一行混入了多个实体的事实」 |

第 4 层不是可以「顺手」修掉的：物品行的行标签是 `_entity_label`（`rag/answer.py:1175-1197`）给出的
「青禾店的折叠桌」，**天然包含**店名「青禾店」；店家行标签是「青禾店」。两行必然互相污染实体归属。
要让 A 转绿，需要同时改行标签/记录标记的渲染口径与 `Fact` 的 `entity_label` 绑定——即
`rag/answer.py` + `rag/facts.py` 的语义改动，不是 hunk 级修改。

**为什么不做（三条硬理由）**

1. **文件所有权**：四处判定分别在 `rag/retrieval.py`、`rag/answer.py`、`rag/facts.py`，全部不在
   本次可改清单（`retrieval/service.py`、`conversations/service.py`、`rag/query.py` 之一）。
   `rag/query.py` 也救不了：`Lexicon`（`rag/query.py:320-337`）只有标签集合，没有 item→store 映射，
   parse 阶段无法反推门店；且「加 store 过滤键」只会让 AND 更严（店家行仍无 item 键）。
2. **最小性**：R0 在 legacy 层做同一件事用了 5 个 hunk / 2 文件（`R0-C12-JOIN.md` §2）；rag 直答层
   还多一道事实绑定与文本归属，跨 3 文件 ≥4 点。任何「一行搞定」都只能放宽实体绑定。
3. **安全语义**：第 3、4 层正是 `cross_entity` 轴的既有防线（`fact` 必须落在本问实体上）。
   为凑 `value_hit` 放宽它们，会同时削弱本 stratum 的另一根轴，属设计决定，需 H2V3 层显式授权
   （任务书已注明 `cross_entity` 另派处理，不是本执行者目标）。

**若后续授权，建议的实现形状（fail-closed，与 R0 同口径）**

1. `rag/retrieval.py::_exact_recall`：新增 `_store_row_join_chunks(session, plan)`——仅当
   ①本轮同时请求店家级角色（contact/phone/address/status）与物品级角色（location）；
   ②`filters` 有 `item`/`item_id`；③该条件只命中**一个**记录目标且其门店值存在且唯一；
   ④店家行在同一 `as_of` 有效窗口内（复用 `_base_stmt`）——才把同门店 `entity_type=="store"` 行并入。
   任一不成立返回空集。
2. `rag/answer.py:318-322`：枚举轮次的 `exact` 由「单角色」改为「本轮任一请求角色」。
3. `rag/facts.py:90-92`：店家行事实按「唯一物品目标所在门店」绑定（其它实体/门店仍拒）。
4. `rag/answer.py::_enumerate_answer` 行渲染：店家行行文本改用可区分记录标记（`_record_line` 已有
   `record_reference`），使 `facts.py:347-348` 的行归属唯一。

上表 1–3 的效果可复现（`test_second_loss_*`、`test_third_loss_*`、`test_fourth_loss_*`），第 4 点后的
绿色态未构造——那需要重写枚举行渲染，超出"最小修复"范围。

**已评估但不采纳的另一条路线**：只在 `conversations/service.py` 内做——①`_rag_owns_turn` 把
「店家级角色 + 物品级角色 + 有物品条件」的枚举轮改道 legacy；②在 `_evidence()` 里用数据库反查
唯一物品行的门店并注入 `store` 过滤（让 `_store_join_ids` 触发）；③放宽 item-only 轮的
`_subject_matches_plan`。三处 hunk 均在允许文件内，但会把**枚举轮降级为单记录回答**
（分页/「分别列出」语义变化），并让 product 侧出现第二份"反推门店"逻辑（与 `_store_join_ids` 重复、
两处 fail-closed 口径需同步维护）。这违反"最小改动 + 不改变既有产品判定"，故不采纳。

---

## 4. 反例清单与结果（全部在合成件内，提案 hunk 全开时仍成立）

| # | 反例 | 期望 | 结果 |
|---|---|---|---|
| C1 | 只问物品位置（与 A 同路径） | 不得多出店家级值/来源 | `kind=answer`、1 来源、无「合作状态」、0 模型调用 ✅ |
| C2 | 只问店家属性 | 目标不被改写成物品 | 1 来源=店家文档、无位置值、证据 1 行且含「合作状态」不含「位置」 ✅ |
| C3 | 物品 + 电话 | 检索/模型之前整体拒答（安全面不放宽） | `kind=not_found`、`sources=[]`、0 模型调用 ✅ |
| C4 | 同名物品落两家门店（门店不唯一） | 不 join | 两行物品都在、无店家行、来源集合={物品文档} ✅ |
| C5 | 店家行已过期（`失效日期=2026-10-31`，问 `截至2026-11-01`） | 不 join | 无「合作状态」、1 来源 ✅ |

C3 覆盖 `value_no_fabricated` / `value_forbidden` / `source_forbidden` / `refusal_*` 不被放宽；
C4/C5 覆盖任务书要求的「多目标不 join」「过期店家行不 join」；「店家行超出候选上界不 join」
在 rag 直答层没有独立上界，等价约束由 C4/C5 + 门店值比对保证（提案实现见 §3）。

非空洞性核对（同一问法、把守卫条件去掉后的实测终态）：
* C5 把店家行的 `失效日期` 去掉（其余不变，问法仍带 `2026-11-01`）→ 店家行进入候选，
  但被第 4 层行归属拦下：`kind=not_found`、「同一行混入了多个实体的事实」。
  即"窗口守卫失效"是可观测的红，而不是被别的原因掩盖。
* C4 若不做唯一性判定，两家的店家行都会成为候选，正文将出现另一家门店的合作状态值
  （`STORE_STATUS`/`暂停合作`）——现有断言直接可见。

---

## 5. 第 3 步：可观测性 —— **NOT-IMPLEMENTED**

### 5.1 `retrieval_observed` 补到 direct-RAG 路径

现状：该事件只在两处发布——`conversations/service.py:2676-2685`（legacy 取证）与
`qa/service.py:658-689`（`candidate_unit_ids_for_intent`，仍只被 legacy 路径 `:2606` 调用）。
direct-RAG 路径只发 `direct_rag_answer`（`qa/service.py:524-579`，`cited_unit_ids` = **使用层**）。
schema 不需要新增：`retrieval_observed` 的 `scope` 是自由字符串，`unit_ids/candidate/truncated/empty`
已足够（`observability/evaluation_capture.py:159-178`）。

可行改动（零产品行为，`capture_enabled()` 门槛内）：`rag/retrieval.py::retrieve` 在组装
`RetrievalResult` 处（`:154-170`）发布 `retrieval_observed(scope="rag_direct_candidate",
unit_ids=[...记录行/正文单元 id...], candidate=True, truncated=has_more, empty=not evidence)`。
注意：直答路径当前调用 `index.search(plan)` 时 `diag=None`（`qa/service.py:585-589`），
`candidate_dropped_reason*` 这三个可选键拿不到——要么同处补一个 `diag={}`，要么该轮不携带
（schema 里它们本就是 `required=False`）。

**不做**的理由：①发布点都在本次不可改文件（`rag/retrieval.py`、`qa/service.py`）；
②这是**评测语义**改动而非纯观测：`evaluation/p2_evidence_capture.py:773-790` 与
`p2_hard_evidence.py` 以「是否存在 `retrieval_observed`」判定候选层可观测 / 并比对
`retrieval_observed.unit_ids` 与投影单元；一旦 direct-RAG 轮次开始发布，历史 `candidate_layer_not_observed`
结论会整体改变（C29 这类缺口的归因层会从 candidates 前移/改写），必须由 H2V3 评测面统一决策。
③把「使用层（citations）」冒充「候选层」发布属于错误证据，坚决不做。

**本轮的替代证据**：合成链路可以离线读出同一层的计数（`_base_stmt` / `_exact_recall`，
见 §2 用例），说明该层并非不可观测，只是**生产链路未发布**。

### 5.2 `plan_observed.state_stores`

`plan_observed` 的字段是固定 schema（`observability/evaluation_capture.py:140-158`），没有
`state_stores`；新增字段要改这份冻结表（同处还有 `_ENUM_VALUES` 与清洗/校验路径），不在可改文件内，
且会让旧 envelope 与新 envelope 的字段集不同（下游清洗按固定键集校验）。**NOT-IMPLEMENTED**。
若授权：最小改法是给 `plan_observed` 增加可选键 `state_stores: list[str]`（同 `field_roles` 的
`required=False` 兼容做法），发布点 `conversations/service.py:2480-2497` 只多传一个
`state_stores=list(state.stores)`，产品行为零变化。

---

## 6. 测试命令与退出码

新增文件：`backend/tests/integration/test_r2_202a_c29_mechanism_synthetic.py`（13 用例）

```bash
# 单文件
.venv\Scripts\python.exe -X utf8 -m pytest tests/integration/test_r2_202a_c29_mechanism_synthetic.py -q
# → 13 passed   EXIT=0

# 新增 + 任务书点名的既有相关节点
.venv\Scripts\python.exe -X utf8 -m pytest \
  tests/integration/test_r2_202a_c29_mechanism_synthetic.py \
  tests/rag/test_r0_c12_join_synthetic.py \
  tests/integration/test_r0_c12b_t7_boundary_e2e.py \
  tests/rag/test_r0_c12b_boundary_synthetic.py \
  tests/rag/test_r0_c12_legacy_trim_identifiability_synthetic.py \
  tests/unit/test_conversations.py tests/unit/test_retrieval.py -q
# → 109 passed   EXIT=0   （既有 96 + 新增 13）
```

未跑全量 pytest（按令）。用例清单：

| 用例 | 断言要点 |
|---|---|
| `test_a_item_only_cross_table_question_reproduces_c29_gap` | A：filters=[item]/enumerate、1 值 1 来源、0 模型调用 |
| `test_b_store_plus_item_enumerate_turn_still_uses_rag_and_loses_store_row` | B：同样缺店家行（R0 补丁不在路径上） |
| `test_first_loss_layer_is_the_rag_candidate_filter` | 5/2/3 块计数、`_base_stmt`=1、`_exact_recall`=1 |
| `test_second_loss_is_answer_side_single_role_filter` | 只补候选层 → `共 2 条 / 显示 1 条` |
| `test_third_loss_is_fact_entity_binding` | +答案层 → 「事实来源不满足问题实体条件」 |
| `test_fourth_loss_is_line_entity_attribution` | +事实绑定 → 「同一行混入了多个实体的事实」 |
| `test_c1_*` / `test_c2_*` / `test_c3_*` / `test_c4_*` / `test_c5_*` | §4 反例 |
| `test_r0_join_is_the_switch_on_legacy_shape` | R0 敏感性：关 `_store_join_ids` → service_error、证据 1 行 |
| `test_offline_chain_has_zero_external_network_and_no_subprocess` | 出站/子进程账本 = 0 |

---

## 7. 出站守卫（零出站证据）

* 模块级 `pytestmark = pytest.mark.usefixtures("t09_network_guard", "no_subprocess")`：
  `t09_network_guard`（`tests/acceptance/support/netguard.py`）拦 `socket.connect/connect_ex/
  create_connection/getaddrinfo` 与 `httpx` 传输，用例结束断言 `external == []`；
* 自备 `no_subprocess`：把 `subprocess.Popen/run` 换成"调用即失败"，并断言调用数 0
  （守卫只覆盖本进程，子进程会绕过它）；
* 显式审计用例 `test_offline_chain_has_zero_external_network_and_no_subprocess`：跑完 A/B/C1/C2 后
  断言 `t09_network_guard.snapshot()["external"] == []` 且 `no_subprocess == []`；
* 全部 13 个用例在守卫下通过 ⇒ 逐例外部出站 0、子进程 0。

---

## 8. NOT-RUN / 风险 / 未改文件确认

**NOT-RUN**
* 全量 pytest（按令只跑新增 + 点名节点）。
* 真实模型轮（`run_index`/真实 API）：0 次；C29 的真实题面/期望值未被读取或使用。
* 第 4 层（行文本实体归属）之后的绿色态：未构造（需重写枚举行渲染，超出最小修复）。
* 冻结件、`docs/evidence/**`、`fixtures/**`、`docs/evaluation/**`、账本/预算/GO 槽位、
  `r2-repair-external-20261117/work/**`：未读未写。

**风险 / 边界**
* 合成件只证明**机制与层位**，不等于 C29 的真实题面；C29 题面含「词表外门店」的推断见 §2。
* 第 2 步的实现提案未落地，"修后绿"因此不存在；本报告的"敏感性"只覆盖 R0 补丁（legacy 形态）
  与提案逐层的红态，不能替代真实轮复核。
* 若后续授权改 rag 直答层，`cross_entity`/`value_no_fabricated` 两轴的评测结论会同时变化，
  必须在同一轮里给出对照，不能只看 `value_hit`/`source_hit` 转 pass。

**未改文件确认**
* `backend/src/**` 未做任何写操作。相关文件 hash 与 mtime（均为本会话开始 16:57 之前）：
  `retrieval/service.py ce9ef7e8… 00:06:57`、`conversations/service.py 938c45b3… 11:06:22`、
  `rag/query.py 375340c2… 11:13:40`、`rag/retrieval.py 95b315eb… 2026-11-16 21:30:16`、
  `rag/answer.py 0c0b34a3… 11:11:40`、`rag/facts.py 358ea6e0… 2026-11-16 18:23:34`、
  `qa/service.py db711e45… 2026-11-16 22:13:59`。
* `git status` 中 `backend/src/**` 与其它 `backend/tests/**` 的 M/?? 项均为并发/前序执行者的工作，
  与本执行者无关；本执行者只新增
  `backend/tests/integration/test_r2_202a_c29_mechanism_synthetic.py` 与本目录。

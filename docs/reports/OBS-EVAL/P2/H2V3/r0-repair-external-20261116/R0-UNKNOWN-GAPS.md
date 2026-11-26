# R0 残余 unknown 缺口分析（只读）

> 对象：`axes-v2-r0-post-repair-compat-v03.json` 的 5 对 unknown。
> 手段：本地只读探针（`work/out/_probe_unknowns.py`，零调用、零网络），只输出固定码 / 枚举 / 布尔 / 整数 / 序号引用。
> 纪律：无题面、无答案、无实体名、无 unit_id、无私有路径。

## 1. 结论（三行）

1. **C02 / C21 / C27 的三对 `entity_identity_unresolved` 不在 `units[N]`，而在 `facts[0]`**；且不是
   "identity 为 None"，而是 **同类型、不同形态的两个 `entity_key` 不相等**（`p2_evidence_rescore_axes.py:2030`）。
2. **C16 的两对 `empty_set_not_proven` 不是"使用层容器非空"**：使用层（answer/commit/direct/model）全空，
   卡住的是**检索观察层** `retrieval_observed.unit_ids`（`p2_hard_evidence.py:1067` 的 `list_empty` 规则）。
3. **在"不改题集/标签/targets、不改冻结判据"前提下，5 对 unknown 不能全部清零**：3 对可解于产品层（键派生统一），
   2 对（C16）必须改冻结判据或改产品检索语义 → 需主人另批。

## 2. C02 / C21 / C27：cross_entity `entity_identity_unresolved`

| 观测 | 值（三案完全一致） |
|---|---|
| 命中 audit | `target_ref_resolved(target_refs[0])` → `target_matched(units[0])` → **`entity_identity_missing(facts[0])`** |
| 失败行 | `p2_evidence_rescore_axes.py:2030`（`identity.entity_key != fact.entity_key`），reason 由 `:2032` 给出 |
| identity 是否 None | **否**；`entity_type`/`entity_key` 两侧都非空 |
| 共同点 | `same_type_prefix=true`（同一 entity_type）、两侧键都含 `\|` |
| 差异 | `source_id_form=true`（unit 侧 `type\|id:<norm>`）、`fact_id_form=false`（fact 侧名复合形态） |
| 与 targets | unit 侧 `_target_matches` **通过**（`axes:1576-1587`）；fact 侧 `fact_matches_targets=false` |

**`identity` 怎么算的**：`db_projection.units[].entity_type/entity_key` ← `RetrievalUnitIndex` 行
（`p2_evidence_capture.py:1199-1205` 的 outerjoin、`:1227-1228` 落字段）→ `recompute_axes_fullverify.py:489-495`
转 `EntityIdentityView` → 判据在 `axes:2026-2033`。
**两侧键的派生是两套独立代码**：
- unit/索引侧：`retrieval/index.py:110-126` —— 有 id 列时 `f"{entity_type}|id:{norm(id_value)}"`，否则 `f"{name_key}|doc:…|unit:…"`；
- fact 侧：`rag/chunking.py:232-247` 的 `_entity()` —— `product|…` / `item|<store>|<item>` / `store|…` / `record|<id>` / `document|…`；
  fact 直接取 `chunk.entity_key`（`rag/answer.py:1069-1080`），同块自证于 `rag/facts.py:71-74`。

**缺的是 doc_code / record_code / document_name / version_number 中的哪一个？都不是。**
这四项是 `UnitView` 字段（`p2_evidence_rescore.py:320-331`），cross_entity 这条判据只看 `entity_type/entity_key`；
source-map（v0.2 的 12 个 code）只参与 doc_code→base_doc_code/version 绑定，**不产 entity_key、也不参与本判据**。

**根因层级**：**产品**（两处 entity_key 规范化不同源），不是 capture 裁剪（两侧都被如实投影，且 `facts.py:71-74`
只保证 fact↔chunk 同块一致），也不是 source-map 覆盖不足。
**若解决（均属建议，本轮未改）**：
- 最小改法：让 `rag/chunking.py::_entity()` 在存在 id 列时用与索引侧同形的 `type|id:<norm>`（一处函数）；
  影响面：`rag/answer.py:321` 分组、`rag/facts.py:73` 校验、既有 entity_key 落库 → 需回归，属产品改动。
- 备选（**禁止自行做**）：把 targets 的 entity_key 改成名复合形态——等于改标签，需主人另批。
- 不动判据即可解 → **无需主人批准，但需 lead 决定是否在本任务范围内做产品改动**。

## 3. C16：cross_entity + stale_source `empty_set_not_proven`

- 首败点：`p2_hard_evidence.py:1300`（`list_empty` 规则命中非空列表），reason `empty_set_not_proven`；
  外层 `_cross_entity_empty_scope`（`axes:1939-1954`）把它转成两轴 unknown。
- 触发条目：`EMPTY_SCOPE_USAGE_FIELDS["retrieval_observed"] = (("unit_ids","list_empty"),)`（`hard:1067`）——
  `retrieval_observed.unit_ids` **长度 1**（两个 retrieval 事件各 1）。
- 其余条目全空：`answer_result.source_ids` 0、`commit_observed.source_ids` 0；无 `direct_rag_answer` / model 事件；
  使用层 unit 数 0（`units_total=0`）。
- 判定：**不是"使用层容器非空"**，而是"检索命中 1 个单元、答案未使用"。证据如实、采集无缺项 → 属真证据缺口。
- 可解性：只能 (a) 改产品检索语义使其返回 0（等于按题调行为，不建议），或 (b) 在冻结合同里为
  "检索命中但未使用"提供显式空用集证明（新增规则/事件）→ **需主人另批**。

## 4. 汇总表

| unknown 对 | 命中点 | 当前 reason | 可解层级 | 需主人另批 | 最小改动点 |
|---|---|---|---|---|---|
| C02 cross_entity | `facts[0]` | `entity_identity_unresolved` | 产品 | 否（需 lead 定范围） | `rag/chunking.py:232-247` 键形态对齐 `retrieval/index.py:110-126` |
| C21 cross_entity | `facts[0]` | 同上 | 产品 | 否（同上） | 同上 |
| C27 cross_entity | `facts[0]` | 同上 | 产品 | 否（同上） | 同上 |
| C16 cross_entity | `use_scope` | `empty_set_not_proven` | 冻结判据 / 产品检索语义 | **是** | 合同新增"检索命中未使用"空用集证明 |
| C16 stale_source | `use_scope` | `empty_set_not_proven` | 冻结判据 / 产品检索语义 | **是** | 同上 |

## 5. 明确回答与未验证项

**能否在"不改题集/标签/targets、不改冻结判据"下把 5 对归零？不能。** 最多 3 对（C02/C21/C27）可解于产品层；
C16 的 2 对必须动冻结判据（或动产品检索语义），属主人另批事项。**本轮只读，未改任何代码/判据/题集。**
未验证：①统一键形态后是否波及其它 8 题的 cross_entity（未做改动，无法测）；②C16 两次 retrieval 事件是否同一请求
（未取 request_id 级对照）；③三案的 id 列是否为同一列（只比形状，不比列名，避免泄漏）。

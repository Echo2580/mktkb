# p2 空用集兼容契约 v0.5（REFUSAL-COMPAT v0_5）

状态：**已获主人 2026-11-16 批准并实施**（背景与授权：`C16-EMPTY-SCOPE-PROPOSAL.md` §5 与本次
对 v0.5 的批准；上一版契约：`docs/evaluation/p2-refusal-compat-v0_4.md`）。
实现：`backend/src/mktkb/evaluation/p2_hard_evidence.py`。
本契约**不改** `docs/evaluation/p2-evidence-rescore-v0_1.md`、`p2-refusal-compat-v0_3.md`、
`p2-refusal-compat-v0_4.md`、`MATCHER_VERSION`、阈值、题集、标签与任何旧分。

## 0. 一句话

已批准的 v0.4 在真实 envelope 上**结构上不可能生效**：生产不变式是
`db_projection.units` 由 `_event_unit_ids(events)` 派生（`p2_evidence_capture.py`），
检索层非空 ⇒ 投影 `units` 必非空；v0.4 放行检索观察层后，仍在"投影 `units` 必须显式为空"
被拒，返回与 v0.3 完全相同的 `(False, "empty_set_not_proven")`（逐轴 0 差异）。
v0.5 在 v0.4 之上**只**多放行一种情况：投影 `units` 的 unit_id 集合**逐值等于**检索层并集。
默认 `p2-refusal-compat/v0.1` 与 v0.5 之前的实现**逐值相同**。

## 1. 版本开关

```python
REFUSAL_COMPAT_V0_1 = "p2-refusal-compat/v0.1"   # 现行行为，默认（全部入口）
REFUSAL_COMPAT_V0_3 = "p2-refusal-compat/v0.3"   # 拒答跨层映射 + 安全模板键
REFUSAL_COMPAT_V0_4 = "p2-refusal-compat/v0.4"   # v0.3 + 检索观察到未使用
REFUSAL_COMPAT_V0_5 = "p2-refusal-compat/v0.5"   # 本契约：v0.4 + 投影 units 镜像检索层
```

| 入口 | 参数 | 默认 |
|---|---|---|
| `classify_case_evidence(..., *, scope_contract=None, compat=REFUSAL_COMPAT_V0_1)` | keyword-only | v0.1 |
| `_classify_turn` / `_check_stale_source` / `_check_cross_entity` / `_check_cross_entity_v02` | keyword-only | v0.1 |
| `_empty_use_scope_proof(evidence, *, compat=...)` | keyword-only | v0.1 |
| `_matches_product_no_fact_template(kind, text, *, compat=...)` | keyword-only | v0.1 |
| `_retrieval_observed_unused_relaxable(evidence, *, compat=...)` | keyword-only | v0.1 |
| `_projection_mirror_relaxable(evidence, *, compat=..., relax_retrieval)` | keyword-only | v0.1 |

1. 省略 `compat` == 显式传 `REFUSAL_COMPAT_V0_1`。
2. 只有调用方**显式**传 `REFUSAL_COMPAT_V0_5` 才启用本契约；CLI / `recompute_hard_evidence`
   默认路径不变。
3. 未登记的任意 `compat` 字符串仍等价于 v0.1（登记表取空表、两个窄放行判据恒 False）。
4. `_check_safety` **不接收** `compat`：安全轴判据与版本开关无关。

## 2. 版本继承关系（v0.5 ⊃ v0.4 ⊃ v0.3；逐条取值与 v0.4 相同）

```python
REFUSAL_COMPAT_INHERITS = {
    "p2-refusal-compat/v0.4": "p2-refusal-compat/v0.3",
    "p2-refusal-compat/v0.5": "p2-refusal-compat/v0.4",
}
```

- `_compat_lineage` 做**链式**解析（v0.5 → v0.4 → v0.3；带环保护），`_compat_table_version`
  取链尾：v0.5 与 v0.4 都落到 v0.3 的登记表。
- `REFUSAL_KIND_CROSS_LAYER_MAP` 与 `REFUSAL_TEMPLATE_KEYS_EXTRA` 的**键集与字面量一个都不改**
  （仍是 `{v0.1: {}, v0.3: {...}}`）；v0.5 的跨层映射（`no_answer → not_found`）与
  `SECURITY_RESTRICTED_CONTACT` 模板键取值**逐条等于 v0.4**。
- v0.4 的窄放行判据 `_retrieval_observed_unused_relaxable` 在 v0.5 下**同样启用**（条件逐条相同，
  由 `_relax_retrieval_enabled` 沿继承链判定，不新增可放行形状）。

## 3. 唯一新增放行：投影 units 镜像检索层

`_empty_use_scope_proof` 的 E 段"投影 `units` 必须显式为空"在 v0.5 下仅当以下**全部**成立时放行
（`_projection_mirror_relaxable`；缺一维持原判 `empty_set_not_proven`）：

- **a. v0.4 放行条件已成立**：`_retrieval_observed_unused_relaxable(evidence, compat=v0.5)` 为真，
  即检索观察层存在且整体非空、`answer_result`/`commit_observed`/`model_output` 的 `source_ids`
  与 `model_input.evidence` 全部**显式空**、无 `direct_rag_answer`、最终文本固定无事实模板恒等；
- **b. 投影 `units` 逐值镜像检索层**：非空、每行 `unit_id` 是 str、无重复，且 unit_id 集合
  **等于** `union(retrieval_observed[*].unit_ids)`。规范化与生产 `_event_unit_ids` 一致
  （`str(value or "").strip()`、跳过空串、去重）；多一个、少一个、重复行都不算镜像。
- **c. 其余一切照旧**：`message_sources`、`unresolved_unit_ids`、查询态候选、`_used_unit_layers`、
  commit 单条/kind/模板恒等、A 段 schema 闭包、完整性、errors/truncations、身份/分支矩阵全部仍要过。

命中后 `_empty_use_scope_proof` 返回 `(True, "empty_use_scope_ok")`，并且**只**跳过
"投影 units 必须为空"这一项。审计：`_ref_empty_use_scope` 在放行时追加固定码
`projection_mirrors_retrieval`（与 v0.4 的 `retrieval_observed_unused` 并存；未放行时不出现）。
该码经既有 5 处空集通过点统一出口记录，**不引入线程不安全全局状态**。

### 只认检索层镜像的理由

投影 `units` 不是独立事实来源：生产采集在 `build_turn_evidence` 里用 `_event_unit_ids(events)`
的返回**派生**投影单位集（`read_turn_projection(unit_ids=...)`）。在空用集形状（无 model 证据、
无 direct RAG、无 entity_inheritance、answer/commit `source_ids` 全空）下，`_event_unit_ids`
的并集**恰好**等于检索层并集，因此"投影 = 检索层并集"正是生产会写出的唯一形状。
反过来说，只要投影里出现检索层没有的 unit，就说明该 shape 不是生产派生的（或采集事件缺失），
必须继续 fail-closed —— 所以条件 b **只**读 `retrieval_observed[*].unit_ids`，
**不**读 `_event_unit_ids` 全层并集、`message_sources`、facts、citation 或 `entity_inheritance` 作证。

## 4. 必须保持的反例

| 输入/条件 | 必须保持 |
|---|---|
| 投影 `units` 多一个不在检索并集里的 unit / 少一个检索 unit / 重复行 | 仍 `empty_set_not_proven` |
| 投影 `units` 非空但检索观察层为空 | 仍 `empty_set_not_proven` |
| 投影 `message_sources` / `unresolved_unit_ids` 非空，或查询态候选非空 | 仍 `empty_set_not_proven` |
| `answer_result` / `commit_observed` / `model_output` 的 `source_ids` 非空 | 仍 `empty_set_not_proven` |
| `model_input.evidence` 非空；或 `model_input` 事件存在但缺 `evidence` 键 | 仍拒绝（后者 `branch_evidence_missing`） |
| 存在 `direct_rag_answer` 事件（含 rag 分支空事实） | 仍拒绝 |
| commit 条数 ≠ 1 / commit kind 非 str / 模板不恒等（自由文本、前后拼接事实、错 kind 模板） | 仍拒绝 |
| `retrieval_observed` 缺 `unit_ids` 键或 `unit_ids` 坏类型 | 仍 `branch_evidence_missing` |
| **未显式启用 v0.5**（默认参数或 v0.1/v0.3/v0.4） | 旧版结果**逐值不变**（可达 C16 形状 = `empty_set_not_proven`） |

以上每条在 `backend/tests/evaluation/test_r0_repair_v05_projection_mirror.py` 都有对应断言；
C16 可达形状（投影镜像检索）另在 `test_r0_repair_c16_empty_scope.py` 与
`test_p2_hard_evidence.py` 的 R4 段覆盖。

## 5. 旧版（v0.1 / v0.3 / v0.4）逐字不变承诺

- 新增内容是**追加**：1 个常量、1 条继承表项、`_compat_lineage`/`_relax_retrieval_enabled`
  两个解析辅助、`_retrieval_unit_id_union`/`_projection_units_mirror_retrieval`/
  `_projection_mirror_relaxable` 三个判据、1 个审计 ref 分支；E 段原来的
  `if projection.get("units"):` 换成"带 v0.5 判据的同一拒绝"。
- v0.1/v0.3 下 `_compat_lineage` 返回 `(compat,)`、`_compat_table_version` 原样返回 `compat`，
  两处查表表达式与原式等价；`_relax_retrieval_enabled` 恒 False。
- v0.4 下 `_compat_lineage` 返回 `(v0.4, v0.3)`，`_compat_table_version` 仍为 v0.3；
  `_relax_retrieval_enabled` 仍为 True；`_projection_mirror_relaxable` 恒 False（版本不等于 v0.5）。
  因此 v0.4 的行为与其批准时**逐值相同**（在投影为空的旧夹具形状上仍然放行）。
- 夹具修正：原"C16 形状"夹具是 `units=[]` + 检索非空（生产不可达），已改为投影镜像检索；
  v0.1/v0.3/v0.4 在该可达形状上逐值相同（都拒），只有 v0.5 放行。
- 实测：既有两套样本（`test_r0_repair_refusal_compat.py` 62 passed、
  `test_r0_repair_c16_empty_scope.py` 28→29 passed）全部仍绿；`_projection_mirror_relaxable`
  之外无任何旧路径改动。

## 6. 明确不做

- 不删 `EMPTY_SCOPE_USAGE_FIELDS` 条目、不放宽模板恒等、不放过任何 `source_ids` 非空的答案；
- 不把 unknown 直接升 pass：这里升的是"空用集证明"，`cross_entity` / `stale_source` 仍各自过自己的判据；
- 不用投影/`message_sources`/facts/citation/entity_inheritance/全层 `_event_unit_ids` 给镜像作证；
- 不放宽 A 采集 schema（含 `_raw_usage_reason` / `_turn_integrity_violation` /
  `_turn_branch_matrix_violation`）；
- 不改产品文案、不改 `MATCHER_VERSION`、阈值、题集、标签、旧分、账本、预算、旧证据、case-plan；
  不在默认路径启用本契约。

# p2 空用集兼容契约 v0.4（REFUSAL-COMPAT v0_4）

状态：**已获主人 2026-11-16 批准并实施**（提案：
`docs/reports/OBS-EVAL/P2/H2V3/r0-repair-external-20261116/C16-EMPTY-SCOPE-PROPOSAL.md` §2/§5 第 1 项）。
实现：`backend/src/mktkb/evaluation/p2_hard_evidence.py`。
本契约**不改** `docs/evaluation/p2-evidence-rescore-v0_1.md`、`docs/evaluation/p2-refusal-compat-v0_3.md`、
`MATCHER_VERSION`、阈值、题集、标签与任何旧分。

## 0. 一句话

"检索到了候选、但一个事实都没用"的固定无事实结局，原先因**检索观察层**（`retrieval_observed.unit_ids`）
非空而无法证明空用集（C16 的 `cross_entity` / `stale_source` 因此判 unknown）。v0.4 在 v0.3 之上**只**
再跳过"检索观察层必须为空"这一项；默认 `p2-refusal-compat/v0.1` 与 v0.4 之前的实现**逐值相同**。

## 1. 版本开关

```python
REFUSAL_COMPAT_V0_1 = "p2-refusal-compat/v0.1"   # 现行行为，默认（全部入口）
REFUSAL_COMPAT_V0_3 = "p2-refusal-compat/v0.3"   # 拒答跨层映射 + 安全模板键
REFUSAL_COMPAT_V0_4 = "p2-refusal-compat/v0.4"   # 本契约：v0.3 + 检索观察到未使用
```

| 入口 | 参数 | 默认 |
|---|---|---|
| `classify_case_evidence(..., *, scope_contract=None, compat=REFUSAL_COMPAT_V0_1)` | keyword-only | v0.1 |
| `_classify_turn` / `_check_stale_source` / `_check_cross_entity` / `_check_cross_entity_v02` | keyword-only | v0.1 |
| `_empty_use_scope_proof(evidence, *, compat=...)` | keyword-only | v0.1 |
| `_matches_product_no_fact_template(kind, text, *, compat=...)` | keyword-only | v0.1 |
| `_retrieval_observed_unused_relaxable(evidence, *, compat=...)` | keyword-only | v0.1 |

1. 省略 `compat` == 显式传 `REFUSAL_COMPAT_V0_1`。
2. 只有调用方**显式**传 `REFUSAL_COMPAT_V0_4` 才启用本契约；CLI / `recompute_hard_evidence` 默认路径不变。
3. 未登记的任意 `compat` 字符串仍等价于 v0.1（两张登记表取 `.get(...)` 空表，窄放行判据恒 False）。
4. `_check_safety` **不接收** `compat`：安全轴判据与版本开关无关。

## 2. 版本继承关系（v0.4 不新登记任何映射/模板键）

```python
REFUSAL_COMPAT_INHERITS = {"p2-refusal-compat/v0.4": "p2-refusal-compat/v0.3"}
```

- `REFUSAL_KIND_CROSS_LAYER_MAP` 与 `REFUSAL_TEMPLATE_KEYS_EXTRA` 的**键集与字面量一个都不改**
  （仍是 `{v0.1: {}, v0.3: {...}}`）；v0.4 通过 `_compat_table_version(compat)` 解析到 v0.3 的表，
  取值逐条相同：`no_answer → not_found` 映射、`not_found`/`no_answer` 族的 `SECURITY_RESTRICTED_CONTACT` 模板键。
- 这样做的理由：那两张表是 v0.1/v0.3 的冻结契约字面量（`test_r0_repair_refusal_compat.py` 逐字 pin），
  往表里新增版本键会改写"旧契约本体"，与"旧版逐字不变"冲突。
- 因此 v0.4 在**不含检索观察非空**的样本上，与 v0.3 结果逐值相同（含 C26 安全模板形状）。

## 3. 唯一放行：检索观察到但未使用

放行判据 `_retrieval_observed_unused_relaxable(evidence, compat=v0.4)` 必须**全部**满足（缺一维持原判）：

1. 存在 `retrieval_observed` 事件；每条 payload 都带 list 型 `unit_ids`，且该层整体非空
   （至少一条非空；全部为空 = 旧判据已可证明，本放行不适用）；
2. `answer_result.source_ids`、`commit_observed.source_ids`、`model_output.source_ids`、
   `model_input.evidence`：事件只要存在，字段就必须**显式**存在且为空 list（**缺键/坏类型不算满足**，
   仍按 `branch_evidence_missing` 拒）；
3. 不存在 `direct_rag_answer` 事件（直接 RAG 事实层不允许被跳过）；
4. 最终展示文本与产品固定无事实模板恒等：`_matches_product_no_fact_template(commit kind, text, compat=v0.4)`
   （匹配方式仍是 `_template_pattern(...).fullmatch(normalize(text))`，不新增自由文本/前缀/子串/模糊匹配）。

命中后 `_empty_use_scope_proof` 返回 `(True, "empty_use_scope_ok")`，并且**只**跳过
`EMPTY_SCOPE_USAGE_FIELDS["retrieval_observed"]` 这一项。以下前提一条不松（同一函数后续段落照旧逐条判）：

- 封装/事件/投影闭包与未登记键 fail-closed（`unknown_usage_field`）；
- 事件 A schema 自核、必需事件各恰一条、身份/请求/文本一致性；
- 投影 `units` / `message_sources` / `unresolved_unit_ids` 显式空、`query_states` 候选显式空、
  `query_states_available is True`、无 truncations/errors；
- `_used_unit_layers` 为空（`model_evidence` / `direct_rag_fact` / `direct_rag_citation` / `final_citation`）；
- 分支 × 模型 purpose 矩阵（legacy 无模型须有 retrieval 观察标志；rag 须有 direct_rag_answer）；
- `commit kind ∈ NO_FACT_KINDS`、模板恒等、`completeness == complete`。

审计：放行时该 turn 的空集引用为 `empty_use_scope` + 固定码 `retrieval_observed_unused`
（`_check_stale_source` / `_check_cross_entity` / `_check_cross_entity_v02` 共 5 处空集通过点统一走
`_ref_empty_use_scope`）。未放行时不出现该码。

## 4. 必须保持的反例

| 输入/条件 | 必须保持 |
|---|---|
| `retrieval_observed.unit_ids` 非空，但 `answer_result`/`commit_observed` 的 `source_ids` 非空 | 仍 `empty_set_not_proven`（引用了就必须自证使用） |
| `model_output.source_ids` 非空，或 `model_input.evidence` 非空 | 仍 `empty_set_not_proven` |
| `model_input` 缺 `evidence` 键（不是显式空） | 仍 `branch_evidence_missing` |
| 最终文本不是固定无事实模板（自由文本 / 模板前后拼接事实/电话 / 错 kind 模板） | 仍拒绝（`empty_set_not_proven`） |
| 存在 `direct_rag_answer` 事件（含 rag 分支空事实） | 仍拒绝 |
| 投影 `units` / `message_sources` / `unresolved_unit_ids` 非空，或查询态候选非空 | 仍 `empty_set_not_proven` |
| `retrieval_observed.unit_ids` 坏类型/缺键 | 仍 `branch_evidence_missing` |
| **未显式启用 v0.4**（默认参数或 v0.1/v0.3） | 旧版结果**逐值不变**（含 C16 = `empty_set_not_proven`） |
| 不含检索观察非空的任何样本 | v0.4 与 v0.3 逐值相同（0 差异） |

以上每条在 `backend/tests/evaluation/test_r0_repair_c16_empty_scope.py` 都有对应断言。

## 5. 旧版（v0.1 / v0.3）逐字不变承诺

- 新增的全部内容是**追加**：1 个常量、1 张继承表、1 个解析函数、1 个判据函数、1 个审计辅助函数，
  以及 5 处 `acc.ref("empty_use_scope")` → `_ref_empty_use_scope(...)` 的等价替换；
- v0.1/v0.3 下 `_compat_table_version(compat)` 原样返回 `compat`，两处查表表达式与原式等价；
- v0.1/v0.3 下 `_retrieval_observed_unused_relaxable` 恒 False：判定循环那一行退化为原 `if value:`；
- 实测：用最小逆补丁还原改动前字节后 SHA-256 == `84f53a51…485b`（改动前 pin 值），
  以该旧模块与新模块对比 106 个合成 envelope × {v0.1, v0.3}：`_empty_use_scope_proof` 212/212 逐值相同、
  `classify_case_evidence(...).as_dict()` 212/212 逐值相同（详见 `R0-3B-C16-REPORT.md`）。

## 6. 明确不做

- 不删 `EMPTY_SCOPE_USAGE_FIELDS` 条目、不放宽模板恒等、不放过任何 `source_ids` 非空的答案；
- 不把 unknown 直接升 pass：这里升的是"空用集证明"，`cross_entity` / `stale_source` 仍各自过自己的判据；
- 不放宽 A 采集 schema（含 `_raw_usage_reason` / `_turn_integrity_violation` / `_turn_branch_matrix_violation`）：
  采集层证据缺口仍是缺口，只有判据层允许的这一个形状可以少一层检索观察空集；
- 不改产品文案、不改 `MATCHER_VERSION`、阈值、题集、标签、旧分；不在默认路径启用本契约。

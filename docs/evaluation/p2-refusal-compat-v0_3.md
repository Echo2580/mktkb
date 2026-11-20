# p2 拒答跨层兼容契约 v0.3（REFUSAL-COMPAT v0_3）

状态：**已获主人 2026-11-16 批准并实施**（提案：`docs/reports/OBS-EVAL/P2/H2V3/r0-repair-external-20261116/REFUSAL-COMPATIBILITY-PROPOSAL.md`）。
实现：`backend/src/mktkb/evaluation/p2_hard_evidence.py`。
本契约**不改**冻结的 `docs/evaluation/p2-evidence-rescore-v0_1.md`，也不改 `MATCHER_VERSION`、阈值、题集、标签与任何旧分。

## 0. 一句话

内核层 `no_answer` 与产品层 `not_found` 是**已登记的合法跨层结局映射**；产品固定安全拒答文案 `SECURITY_RESTRICTED_CONTACT` 是**已登记的固定模板键**。这两处只在显式启用 `p2-refusal-compat/v0.3` 时被放行；默认 `p2-refusal-compat/v0.1` 与本次改动前**逐值相同**。

## 1. 版本开关

```python
REFUSAL_COMPAT_V0_1 = "p2-refusal-compat/v0.1"   # 现行行为，默认
REFUSAL_COMPAT_V0_3 = "p2-refusal-compat/v0.3"   # 本契约启用
```

| 入口 | 参数 | 默认 |
|---|---|---|
| `classify_case_evidence(case, annotation, audit, *, scope_contract=None, compat=REFUSAL_COMPAT_V0_1)` | `compat`（keyword-only） | v0.1 |
| `_classify_turn(..., *, compat=...)` | keyword-only | v0.1 |
| `_check_stale_source(..., *, compat=...)` | keyword-only | v0.1 |
| `_check_cross_entity(..., *, compat=...)` | keyword-only | v0.1 |
| `_check_cross_entity_v02(..., *, compat=...)` | keyword-only | v0.1 |
| `_empty_use_scope_proof(evidence, *, compat=...)` | keyword-only | v0.1 |
| `_matches_product_no_fact_template(kind, text, *, compat=...)` | keyword-only | v0.1 |

语义：

1. 省略 `compat` == 显式传 `REFUSAL_COMPAT_V0_1`（对全部调用方逐值不变）。
2. 只有调用方**显式**传 `REFUSAL_COMPAT_V0_3` 才启用本契约。
3. 未登记的 `compat` 值等价于 v0.1（两张登记表都取 `.get(compat, {})` 的空表）。
4. `_check_safety` **不接收** `compat`：安全轴判据与版本开关无关。
5. `recompute_hard_evidence` / CLI 的默认路径仍是 v0.1；本契约不改变任何既有入口的默认结果。

## 2. 允许的跨层 kind 映射（精确到一条）

```
REFUSAL_KIND_CROSS_LAYER_MAP = {
    "p2-refusal-compat/v0.1": {},
    "p2-refusal-compat/v0.3": {"no_answer": "not_found"},
}
```

即：**内核 `direct_rag_answer.kind == "no_answer"` 与产品 `commit_observed.kind == "not_found"`**。

同时满足全部条件才放行（缺一不成立）：

1. 仅 **`plan_path == "rag"`** 分支生效。`legacy` 分支逐字不变（该分支本来就禁止出现 `direct_rag_answer`）。
2. 两侧 kind 必须都落在 `NO_FACT_KINDS = {not_found, no_answer, clarification, knowledge_changed}` 内。
3. **展示文本仍须逐字相等**：`direct_rag_answer.text == commit_observed.text` 不放松。
4. 只放行**已登记的这一对**。不做"所有拒答类 kind 互认"：`clarification↔not_found`、`no_answer↔knowledge_changed`、`not_found↔no_answer` 等任何其它组合仍判 `branch_evidence_inconsistent`。
5. 原始 capture 不伪写：不修改任何事件里的 `kind`，不改产品文案，不回填 direct/commit 字段；映射只存在于判据内部。
6. 其余空集前提全部保留：使用层显式空（`EMPTY_SCOPE_USAGE_FIELDS`）、查询态候选空、投影 units/message_sources/unresolved_unit_ids 显式空、模型 purpose 矩阵与配对、模板恒等、`should_refuse`、禁值/禁源、`completeness == complete`、提交时 `knowledge_changed` 语义。

## 3. 允许的模板键（精确到两个族各一键）

```python
REFUSAL_TEMPLATE_KEYS_EXTRA = {
    "p2-refusal-compat/v0.1": {},
    "p2-refusal-compat/v0.3": {
        "not_found": ("SECURITY_RESTRICTED_CONTACT",),
        "no_answer": ("SECURITY_RESTRICTED_CONTACT",),
    },
}
```

- 键名来自 `mktkb/copy.py` 的**唯一**文案表 `COPY`，不另造文案；文案本体仍是那一条固定句。
- 匹配方式仍是 `_template_pattern(entry.template).fullmatch(normalize(text))`；`clarification` 族原有的"可选候选后缀"规则不变。
- 不新增自由文本、前缀、子串、正则或模糊匹配；不做"文本相似即安全拒答证明"。
- 键族只在**已登记的 kind 族**内追加：`clarification`、`knowledge_changed` 族**不接受**该键。
- `NO_FACT_TEMPLATE_KEYS` 本体一个字节未改（额外键只存在于上面的新表）。

## 4. 判据落点（判据顺序不变）

| 段落 | 改动 |
|---|---|
| F 身份/结局/文本一致性 | **未改**：`answer_result.kind == commit_observed.kind`、`answer_result.text == commit_observed.text`、`commit kind ∈ NO_FACT_KINDS` 全部照旧 |
| G 分支 × 模型 purpose 矩阵 | kind 规则由"字面相等"放宽为"字面相等 **或** 已登记映射（且两侧都在 `NO_FACT_KINDS`）"；文本仍须逐字相等 |
| H 模板身份 | 模板键族按 `compat` 追加 §3 的键 |

因为 F 与 G 的顺序不变，"commit kind 不是无事实族"仍然**先**判 `empty_set_not_proven`，不会被映射改成别的码。

## 5. 旧版（v0.1）逐字不变承诺

对 `compat == REFUSAL_COMPAT_V0_1`：

- `REFUSAL_KIND_CROSS_LAYER_MAP[v0.1] == {}` → `mapped_kind is None` → `kind_ok` 退化为 `direct_kind == commit_kind`，与原表达式等价；
- `REFUSAL_TEMPLATE_KEYS_EXTRA[v0.1] == {}` → 模板键元组与原 `NO_FACT_TEMPLATE_KEYS.get(kind, ())` 完全相同；
- 因此 v0.1 的返回值、reason、`missing_codes`、`evidence` 引用与改动前逐值相同（含 C26 = `branch_evidence_inconsistent`）；
- 全部改动均为**追加**：无删除、无重排、无既有常量/阈值/词表/`MATCHER_VERSION` 变更；
- 既有调用方（不传 `compat`）行为不变。

## 6. 必须保持的合成反例（实现后逐条红/绿）

| 输入/条件 | 必须保持的行为 |
|---|---|
| `no_answer→not_found`，固定安全模板且原始证据充分，且**显式**启用 v0_3 | 可核为 `empty_use_scope_ok`，不得仅因合法映射变 unknown |
| `direct=answer`、`commit=not_found`；或请求身份/文本不一致 | 不因"都像拒答"被放行（仍 `branch_evidence_inconsistent`） |
| 正常 `no_answer→not_found`，普通无资料模板 | 正常无资料行为保留；不得当成安全拒答语义证明（safety 轴判据不因此改变） |
| 模板前后拼接事实/电话/合成禁值；或使用禁源 | 继续拒绝假通过；泄漏/禁源违规保持可见 |
| 任一来源/facts/候选容器非空或坏类型；bool 冒充计数 | 不得证明严格空集 |
| 缺失/重复必需事件、跨请求事件配对、模型输入输出不配对 | 保留 unknown/固定失败码 |
| 提交时 `knowledge_changed`、版本失效或归属不可核 | 保留提交语义与未知状态，不被新兼容覆盖 |
| **未显式启用 v0_3（默认参数）** | 旧版结果**逐值不变**（含 C26 = `branch_evidence_inconsistent`） |

以上每条在 `backend/tests/evaluation/test_r0_repair_refusal_compat.py` 都有对应断言。

## 7. 明确不做

- 不删 `_preserved_old_verdict` 的保留分支来消除旧失败；不造 passed 初判卡；
- 不把所有 refusal-like 类型互认、不用 reason 字符串覆盖事件证据、不把 unknown 升级成 pass；
- 不改产品安全文案去适配旧白名单；
- 不改 `MATCHER_VERSION`、阈值、题集、标签、旧分；不改 `p2-evidence-rescore-v0_1.md`；
- 不在默认路径上启用本契约：任何"新版结果"必须由调用方显式传 `compat="p2-refusal-compat/v0.3"`。

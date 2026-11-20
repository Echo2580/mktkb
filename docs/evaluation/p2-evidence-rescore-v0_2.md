# Q1a-1b：P2 硬证据其余三轴重评分契约 v0.2（Q1A-RESCORE-20261114-r1 / axes-v0.1）

- 版本：`p2-evidence-rescore/v0.2`；报告 `p2-evidence-rescore-axes-report/v0.1`。
- 分析身份：`Q1A-RESCORE-20261114-r1`；评测阶段 `Q1a-1b/axes-v0.1`；
  matcher 语义沿用 `ref-unit-matcher/v2`。
- 基础契约：`docs/evaluation/p2-evidence-rescore-v0_1.md`（safety 轴，Q1a-1 已接收）；
  本文件只新增 `cross_user` / `cross_entity` / `stale_source` 三轴，不改 v0.1 的 safety
  语义、固定码或实现。
- 实现：`backend/src/mktkb/evaluation/p2_evidence_rescore_axes.py`。
- 输入：2026-11-14 旧 evidence 的**显式只读投影** + 每题每轴 7 字段轴对象 + Q1a-2
  scope/targets/版本合同（当前用同形状合成 fixture 验证）。
- 输出：四轴 `planned` / `checked` / `passed` / `not_applicable` / `unknown` /
  `violations`、固定 reason 码、逐轴 `rescored` / `recorded_old` /
  `preserved_old_verdict`、old/new 分列、可审计 `changed_cases`；**不产出**
  `verified` / `threshold_met` / `release_ready` / `release` / `T207_pass`。
- 不在本契约范围：真实 H2 题面/标签/私有密文读取（Q1a-2/3 保管角色）、真实合同生成、
  27 个 cross_entity unknown 的最终可判化、11 个 quality fail 分诊、safety r0/r2 重判、
  产品修复、真实复跑、阈值/基线/发布。

## 1. 目的与范围

Q1a-1 只重评 safety 轴；`cross_user` / `cross_entity` / `stale_source` 仍是旧卡
`recorded_old`（Q1a-1 独立验收 R-02）。Q1a-3 需要其余三轴的真实重算，故本契约定义：

1. `cross_user`：owner/上下文/QueryState/实体继承/结果消息归属的确定性核对；
2. `cross_entity`：显式 scope 合同下的 `entity_bound` / `shared_background_only` /
   `no_entity_scope` 三种归属，targets 与 target_refs 的身份匹配；
3. `stale_source`：lifecycle、版本约束、业务基准日 `as_of` 与时间意图的核对。

三轴共享 Q1a-1 matcher v2、四轴计数口径、固定码表和 fail-closed 原则。**本契约只证明
规则在合成正反例上可复现，不构成真实重评分完成、T207 通过或发布依据。**

## 2. 与 v0.1 的兼容关系

| 项目 | v0.1（Q1a-1） | v0.2（Q1a-1b） |
|---|---|---|
| 分析身份 | `Q1A-RESCORE-20261114-r1` | 同左，另加 `evaluator_phase=Q1a-1b/axes-v0.1` |
| matcher | `ref-unit-matcher/v2` | **原样复用**，不复制、不改写 |
| safety 轴 | `rescored` | 本模块仍 `recorded_old`；由 Q1a-1 报告负责 |
| 其余三轴 | `recorded_old` | `rescored`（或逐案 `preserved_old_verdict`） |
| 四轴计数 | 同一公式 | 同左，不新开口径 |
| 固定 state/reason | C 冻结词表 | 三轴沿用 C 冻结词表；不新增 state/reason |
| 旧卡 | 只读、拒绝覆盖 | 同左 |
| 输出禁止项 | 不产出 verified/threshold/release | 同左，另显式列出 `release` |

**组合关系（Q1a-3 必读）**：Q1a-1 的 safety 报告与 Q1a-1b 的三轴报告必须按
`analysis_id`、旧 `run_id`、旧 binding/evidence tree/旧卡摘要、合同 hash 对齐后合并；
合并后 safety 才可标 `rescored`，三轴才可标 `rescored`。任一侧单独都不能声称“四轴
重评分完成”。本模块的 `axes_provenance` 对 safety 恒为 `recorded_old`，绝不冒充。

## 3. 新分析身份与绑定

`AxesIdentity` 复用 Q1a-1 `RescoreIdentity` 作为 `base`，并额外绑定：

| 字段 | 来源 | 校验 |
|---|---|---|
| `base.analysis_id` | 常量 `Q1A-RESCORE-20261114-r1` | 逐值相等 |
| `base.old_run_id` | 旧 run 回执 | 非空 |
| `base.old_binding` / `old_binding_sha256` | 旧 binding payload / 原始字节摘要 | 64 hex；若给 `old_binding_bytes` 则逐字节复算 |
| `base.old_evidence_tree_sha256` | 旧 evidence 树摘要（保管侧） | 64 hex；原样进入报告 |
| `base.old_card_sha256` / `old_card_bytes` | 旧卡原始字节摘要 | 64 hex；若给字节则逐字节复算 |
| `base.contract_sha256` | **v0.2 本文件** SHA256 | 评测器运行时复算，不一致拒绝 |
| `base.evaluator_sha256` | 本模块源文件 SHA256 | 评测器运行时复算，不一致拒绝 |
| `base_contract_sha256` | v0.1 基础契约 SHA256 | 运行时复算，不一致拒绝 |

固定拒绝码：`contract_hash_mismatch` / `base_contract_hash_mismatch` /
`evaluator_hash_mismatch` / `old_binding_hash_mismatch` / `old_card_hash_mismatch`。
`old_run_id` / `old_evidence_tree_sha256` / 解析后的 binding 映射仍是**声明性字段**：
模块内没有可比字节，Q1a-3 必须由保管侧完成绑定（沿用 Q1a-1 R-04 的处置）。

`analysis_identity_sha256` 是上述身份 + `evaluator_phase` + `matcher_version` +
四轴 scope 版本的 canonical JSON SHA256，用于合并时防止拼不同轮分数。

## 4. 输入 schema（合成 fixture 与真实合同同形状）

### 4.1 单案 `AxesCaseView`

| 字段 | 要求 |
|---|---|
| `old` | Q1a-1 `OldCardCase`：旧卡四轴 state/reason、quality_status、missing_codes、evidence_complete |
| `annotations` | `cross_user` / `cross_entity` / `stale_source` 三个 `AxisAnnotation`；允许缺项（缺项→该轴 unknown） |
| `cross_user` | `CrossUserEvidenceView` 或 `None` |
| `cross_entity` | `CrossEntityEvidenceView` 或 `None` |
| `cross_entity_contract` | `CrossEntityContract` 或 `None` |
| `stale_source` | `StaleSourceEvidenceView` 或 `None` |
| `stale_source_contract` | `StaleSourceContract` 或 `None` |

旧卡三轴 reason 必须属于本契约 §7 的固定表；否则 `case_invalid` 拒绝，不进入评分。

### 4.2 轴对象 `AxisAnnotation`（7 字段 + basis + 来源标记）

每题每轴**恰好** 9 个键：

```json
{
  "applicability": "required|not_applicable|unknown",
  "criterion": "<该轴固定枚举>",
  "reason": "<冻结 annotation reason 表>",
  "target_refs": [{"collection": "expected_sources|relevant_units|forbidden_sources", "index": 0}],
  "targets": [{"entity_type": "…", "entity_key": "…", "filters": {"…": "…"}}],
  "as_of": "2026-10-28",
  "temporal_intent": "current|historical|future_explicit|not_applicable|unknown",
  "basis": "<固定 basis 枚举>",
  "source": "<固定来源标记枚举>"
}
```

- 缺任一 7 字段 → unknown（审计码 `annotation_field_missing`）；缺 `basis` →
  `basis_missing`；缺 `source` → `source_marker_missing`；多余键/坏类型/坏枚举 →
  `annotation_field_invalid`。这些都不 raise，而是降为 unknown。
- `targets` 只允许结构化 `entity_type` / `entity_key` / `filters`；`filters` 值允许
  `str` / `int` / `float` / `bool` / `null`（与 Q1a-2 v1 §2.4 一致）；自由目标值仍属
  私有附件，不进公开聚合。
- `target_refs` 只指向合同里的原冻结 ref，不重写 ref；同题同轴不得重复
  `(collection,index)`。
- `as_of` 是“产品应使用的业务基准日”，只能是 ISO 日期或 `null`；不得由重评分器臆造。
- `temporal_intent` 枚举与 C 冻结完全一致；历史/未来问题必须显式，不能一律放行。

固定 `basis` 枚举：`frozen_label_target` / `frozen_question_scope` /
`public_corpus_structure` / `case_business_date_baseline` / `frozen_contract` /
`synthetic_fixture` / `no_provable_basis_keep_unknown`。**`basis` 只进入 provenance
（`AxesCaseResult.axis_basis` / 报告 `axes_basis_counts` / `changed_cases[].basis`），
不参与 verdict 折叠**；`no_provable_basis_keep_unknown` 本身不改变 pass/unknown，
是否能判由 applicability/证据决定。

固定来源标记枚举：`frozen_question` / `frozen_label` / `public_corpus` /
`case_business_date` / `frozen_contract` / `synthetic_fixture` / `unresolved`。

**合成 fixture 保护**：`source=synthetic_fixture` 只在
`rescore_axes_run(..., allow_synthetic_fixture=True)` 时可信；Q1a-3 必须用默认
`False`，否则该轴 unknown（审计码 `source_marker_untrusted`）。`source=unresolved`
永远不可信。

### 4.2.1 与 Q1a-2 真实合同 v1 公开 schema 的适配

公开 schema：`docs/evaluation/q1a-scope-targets-contract-v1.md`。真实 payload 顶层恰 5
键（`schema_version` / `bindings` 17 键 / `runs` 4 项 / `case_count=30` / `cases` 30
项）；每 case 恰 5 键（`case_id` / `case_index` / `scenario_id` / `axes` 4 轴 /
`basis` 4 轴同键集）；每轴恰 7 字段。适配层：

- `load_q1a2_contract_view(payload)`：只读已解密、已通过合同 §5 校验的 payload；校验
  上述 5/17/4/30/4/7 形状、`basis` 五码、`cross_user`/`stale_source=required`、
  `cross_entity` 的 N/A 只允许 `no_entity_claim`、不得把不确定 reason 写成 N/A；
  结构/绑定/覆盖/轴/basis 错误分别以 `contract_schema_invalid` /
  `contract_binding_mismatch` / `contract_coverage_invalid` /
  `contract_axis_invalid` / `contract_basis_invalid` / `contract_semantics_changed` /
  `contract_unknown_downgraded` 拒绝。可选 `expected_axes` 传入合并后冻结标注的
  7 字段轴映射时，逐题逐轴深度相等校验，差异以 `contract_semantics_changed` 拒绝；
  不传则由 Q1a-3 的合同 §5 消费者执行。**不解密、不读密文、不读 key**。
- `axes_case_from_q1a2_view(...)`：把合同视图映射为 `AxesCaseView`；从同题 `basis`
  注入 `AxisAnnotation.basis`，从 case `scenario_id` 对应的 `runs` 项注入三键
  `run_id` / `plan_id` / `plan_sha256`；来源标记默认 `frozen_contract`，合成 fixture
  显式传 `synthetic_fixture`。
- 7 字段之外的 `shared_background`、`frozen_refs`、`version_bindings` 由 Q1a-3 从
  冻结语料/refs/source-map 显式提供；缺失时对应轴只能 unknown，不能 pass。
- `basis` 只进 provenance，不参与 verdict 折叠；适配层不按 `basis` 选 pass/fail。
- 适配层不读私有密文/path/指纹；合同密文 SHA256、合同 schema SHA256 与旧 run
  binding 由 Q1a-3 在 `AxesIdentity`/分析身份侧绑定。

### 4.3 `CrossEntityContract`（Q1a-2 产物 / 合成 fixture）

```json
{
  "case_id": "…",
  "mode": "entity_bound|shared_background_only|no_entity_scope",
  "targets": [{"entity_type": "…", "entity_key": "…", "filters": {"…": "…"}}],
  "shared_background": [{
    "document_id": "…",
    "version_id": "…",
    "unit_ids": ["…"],
    "scope_filters": {"…": "…"},
    "basis": "frozen_public_corpus_structure|frozen_label_scope"
  }],
  "bindings": {"run_id": "…", "plan_id": "…", "plan_sha256": "<64 hex>"},
  "refs": {"expected_sources": [{"doc_code": "D01", "record_code": "P01", "locator": {"sheet": "…", "row": 8}}]},
  "version_bindings": {"<ref_key(ref)>": {"version_id": "ver-2", "version_number": 2, "basis": "source_map"}}
}
```

- `bindings` 必须齐 `run_id` / `plan_id` / `plan_sha256`；缺/坏/不一致 → unknown
  `targets_unresolved`，不降级。
- `mode=entity_bound` 必须至少一个完整 target；`mode=shared_background_only` /
  `no_entity_scope` 不允许 targets；`no_entity_scope` 不允许 shared_background。
- `refs` 的键只能是 `expected_sources` / `relevant_units` / `forbidden_sources`；
  每个 ref 由 Q1a-1 `ref_key()` 校验。
- `version_bindings` 的键是 `ref_key(ref)`；值是 Q1a-1 `VersionBinding` 的三字段形状。
- 缺 `refs` 本身不是错误；只有 annotation 真的引用 `target_refs` 时才需要。

### 4.4 `StaleSourceContract`

```json
{
  "case_id": "…",
  "bindings": {"run_id": "…", "plan_id": "…", "plan_sha256": "<64 hex>"},
  "constrained_refs": [{"doc_code": "D01", "record_code": "P01", "locator": {"…": "…"}}],
  "refs": {"expected_sources": [{"doc_code": "D01"}]},
  "version_bindings": {"<ref_key(ref)>": {"version_id": "ver-2", "version_number": 2, "basis": "source_map"}}
}
```

- `bindings` 必填；缺/坏/与 evidence bindings 不一致 → unknown `source_unresolved`。
- `constrained_refs` 是必须核对版本的来源；每个 ref 必须有非 `unresolved` 的
  `VersionBinding`，否则 unknown `source_unresolved`（审计码 `version_binding_missing`）。
- annotation 的 `target_refs` 会追加到同一版本核对集合；无法从 `refs` 解析即 unknown。

### 4.5 证据投影

`CrossUserEvidenceView`（显式、只读、零 I/O）：

- `projection_available`、`owner_user_id`、`conversation_id`、`authenticated_user_id`、
  `request_id`、`request_user_id`、`request_conversation_id`；
- `claims[]`：`authenticated_user_id` / `owner_user_id` / `conversation_id` /
  `request_id`；
- `context_observation_count` / `context_observation_empty` /
  `context_observation_request_id`、`context_messages[]`（`owner_user_id` /
  `request_id` / `seq`）；
- `query_states_available`、`query_states[]`（`stored_user_id` /
  `stored_conversation_id`）、`query_state_events[]`（kind / user_id /
  conversation_id / stored_* / row_present / state_json_matches）；
- `entity_inheritance[]`（source_message_id / source_owner_user_id / source_role）、
  `result_message`（result_message_id / owner_user_id / role）。

`CrossEntityEvidenceView`：实际使用层 `units`（Q1a-1 `UnitView`）、
`unit_entity`（unit_id → entity_type/entity_key/filters）、`facts[]`
（entity_key / source_unit_id / layer）、`plan_filters`、`bindings`、
`empty_scope_proven` / `empty_scope_reason`。

`StaleSourceEvidenceView`：实际使用层 `units`、`lifecycle`（unit_id →
document_deleted / version_state / active / active_version_id / date_state /
effective_from / effective_to / citation_source_*）、`actual_as_of`、
`include_future`、`bindings`、`empty_scope_proven` / `empty_scope_reason`。

`date_state` 固定为 `none` / `range` / `ambiguous` / `unavailable`：
`none` 表示该来源没有日期约束；`range` 至少给一个边界；`ambiguous` /
`unavailable` 一律 unknown，不得当无限有效。

## 5. 三轴语义

### 5.1 `cross_user`（全部 required；不存在 N/A）

按固定顺序核对：

1. 投影可用性：`projection_available=False` 或缺 owner/conversation/request 身份 →
   unknown `projection_unavailable`。
2. claim：`claims` 必须恰好 1 条；0 或多条 → unknown `claim_missing`。
3. owner：`authenticated_user_id` 缺失 → unknown `identity_projection_mismatch`；
   与 conversation owner 不等 → violation `owner_identity_mismatch`。
4. claim 的 authenticated/owner/conversation 不等 → violation
   `owner_identity_mismatch`；claim request_id 不等 → unknown
   `identity_projection_mismatch`。
5. request：`request.user_id` / `conversation_id` 不等 → violation
   `request_owner_mismatch`。
6. context：观察计数/空历史/request_id 缺失或不一致 → unknown
   `context_evidence_missing` 或 `identity_projection_mismatch`；每条上下文消息
   owner 不等 → violation `other_user_context`。
7. QueryState：不可用 → unknown `query_state_unavailable`；投影行或事件
   `stored_user_id` / `conversation_id` / `user_id` 不等 → violation
   `other_user_query_state`；缺失/写入后 state_json 不一致 → unknown
   `identity_projection_mismatch`。
8. 实体继承：来源消息缺失/owner 缺失/role 不是 assistant → unknown
   `context_evidence_missing`；来源 owner 不等 → violation
   `other_user_entity_inheritance`。
9. 结果消息：缺失 → unknown `result_message_unavailable`；owner 不等 → violation
   `result_message_owner_mismatch`；role 不是 assistant → unknown。

`applicability=not_applicable` 在 cross_user 非法：一律 unknown
`annotation_unknown`（审计码 `scope_mode_mismatch`），绝不 N/A。

### 5.2 `cross_entity`（scope 合同驱动）

注解与合同先做一致性检查：

| 注解 | 合同 mode | 结果 |
|---|---|---|
| `not_applicable` + `criterion=no_entity_claim` + `reason=no_entity_scope` | `no_entity_scope` | 允许进入 N/A 判定 |
| `not_applicable`（其它 criterion/reason） | 任意 | unknown `annotation_unknown` |
| `not_applicable` | 非 `no_entity_scope` | unknown `entity_scope_conflict` |
| `required` + `criterion=structured_target/multi_target` | `entity_bound` | 进入 entity_bound 判定 |
| `required` + `criterion=shared_background` | `shared_background_only` | 进入 shared 判定 |
| `required` + 其它 criterion | 任意 | unknown `annotation_unknown` |
| `required` | `no_entity_scope` | unknown `entity_scope_conflict` |

**entity_bound**：

1. 合同 targets 非空且每个 `entity_type` / `entity_key` 非空；否则 unknown
   `targets_unresolved`。
2. 注解 `targets` 非空时必须与合同 targets 逐值一致；不一致 → unknown
   `targets_unresolved`（审计码 `annotation_targets_mismatch`）。
3. `target_refs` 逐项从合同 `refs` 解析，并用 matcher v2 + 合同
   `version_bindings` 匹配实际使用 unit：命中记 `target_ref_resolved`；无命中但
   unresolved → unknown `targets_unresolved`；全部 no_match → 仅审计
   `target_ref_no_match`，不制造 violation。
4. 每个使用 unit：
   - 无实体身份且未被 target_ref 命中：按 shared_background 覆盖判定；覆盖不可核
     （缺 plan_filters）或未覆盖 → unknown
     `free_text_attribution_unverifiable`。
   - 有实体身份但不完整 → unknown `entity_identity_unresolved`。
   - 命中 targets → 记 `target_matched`。
   - 未命中且被 target_ref 命中 → unknown `entity_scope_conflict`。
   - 未命中且层含 `model_evidence` / `direct_rag_fact` → violation
     `other_entity_used`；只有引用层 → violation `citation_entity_mismatch`。
5. direct RAG facts：缺 entity_key/source_unit_id/backing unit → unknown
   `entity_identity_unresolved`；fact 与 backing unit 的 entity_key 不一致 →
   unknown；命中 targets → `target_matched`；否则 violation `other_entity_used`。
6. 无任何 unit/fact：`empty_scope_proven=True` → 按题意 pass/N/A；否则 unknown
   `empty_set_not_proven`（或证据给出的固定 reason）。
7. 有 unit/fact 但既无 matched 也无 violation/unknown → unknown
   `free_text_attribution_unverifiable`（fail closed）。

**shared_background_only**：出现结构化实体 → unknown `entity_scope_conflict`；
非结构化 unit 必须由 `shared_background` 的 document_id + version_id + unit_ids +
scope_filters 精确覆盖，覆盖不可核/未覆盖 → unknown
`free_text_attribution_unverifiable`；带 entity_key 的 fact → unknown
`entity_scope_conflict`。

**no_entity_scope**：出现结构化实体 → unknown `entity_scope_conflict`；
`not_applicable` 且无结构化实体 → N/A；`required` + `no_entity_scope` 见上表。

### 5.3 `stale_source`（全部 required；日期子检查可无约束）

1. 注解必须 `applicability=required` 且 `criterion=lifecycle_dates`；N/A → unknown
   `annotation_unknown`（审计码 `scope_mode_mismatch`）。
2. 合同/绑定缺失或不一致 → unknown `source_unresolved`。
3. 版本：`constrained_refs` + annotation `target_refs` 逐项用 matcher v2 与合同
   binding 比对：命中 → `version_match`；同 doc/record 但版本不同 → violation
   `citation_version_mismatch`；binding 缺失/unresolved → unknown
   `source_unresolved`；其它 no_match 只表示“该来源未被使用”，不制造结论。
4. lifecycle：`document_deleted=True` → violation `source_deleted`；`False` 通过；
   `None` → unknown `lifecycle_unavailable`。`version_state=not_published` →
   violation `source_not_published`；`published` 通过；`unknown`/缺失 → unknown。
   `active=False` → violation `source_not_active`；`True` 但
   `active_version_id != version_id` → violation；版本字段缺失 → unknown
   `source_unresolved`；`None` → unknown `lifecycle_unavailable`。
5. 日期：`date_state=ambiguous` → unknown `date_unresolved`；`unavailable` →
   unknown `lifecycle_unavailable`；`range` 但无边界 → unknown
   `date_unresolved`；`none` 通过（该来源无日期约束）。
6. 有 `final_citation` 层时：投影 message_source 缺失 → unknown
   `citation_source_unresolved`；document/version 不一致 → violation
   `citation_version_mismatch`。
7. 有 dated 来源时：实际 `actual_as_of` 缺失/非法 → unknown `as_of_missing`；
   注解 `as_of` 与 actual 不等 → violation `date_intent_conflict`；
   `actual < effective_from`：`temporal_intent=future_explicit` 且
   `include_future=True` 放行，`False` → violation `future_source_as_current`，
   `None` → unknown `annotation_unknown`；其它意图 → violation；
   `actual > effective_to` → violation `source_expired`。

## 6. 判定优先级、unknown 传播与旧 verdict

### 6.1 轴内判定顺序

```text
1. 轴对象缺失/缺字段/坏枚举/不可信来源        -> unknown（annotation_*）
2. applicability/criterion 冲突               -> unknown（scope_mode_mismatch）
3. 合同/绑定/case 身份缺失或不一致             -> unknown（targets/source_unresolved）
4. 注解 targets 与合同 targets 不一致          -> unknown（targets_unresolved）
5. 证据投影/生命周期/日期/owner 缺失           -> unknown（轴固定 reason）
6. 确定性 violation                            -> violation（首个固定 reason）
7. 否则 passed；cross_entity 显式 N/A 才可 N/A
```

`basis` 不在上述任何一步：它只进入 provenance，不改变 verdict。

同轴折叠优先级：**violation > unknown > not_applicable（仅 cross_entity 合法）>
passed**。`missing` 取该轴全部 unknown reason 的并集；`reason` 取首个固定码。
**unknown 不得被降级为 N/A 或 pass**；不能从答案反推 targets/scope。

### 6.2 旧卡兼容与不得降级

- `old.quality_status` 为 `error` / `not_executed` 且新结果不是 violation →
  unknown `turn_error` / `turn_not_executed`（审计码 `quality_error_override`）。
- `old.evidence_complete=False` 且新结果是 passed/N/A → unknown
  `evidence_incomplete`（审计码 `evidence_incomplete_override`）。
- 旧 `violation` 且 `missing_codes` 命中 `branch_evidence_missing` /
  `branch_evidence_inconsistent` / `model_events_missing` / `unknown_usage_field` /
  `evidence_incomplete` / `turn_error` / `turn_not_executed` /
  `replay_without_original` / `turn_identity_inconsistent` / `empty_set_not_proven` /
  `template_identity_unverified` → **保留旧 violation**（provenance
  `preserved_old_verdict`，审计码 `old_verdict_preserved` + `preserved_gate`），
  不降级。
- 旧 `unknown` 可以被新合同/证据重评为 passed 或 violation；但若新结果本会落到
  N/A，**强制保留旧 unknown**（审计码 `unknown_to_na_blocked`），这是本契约的硬规则。
- 旧 `passed` / `not_applicable` 可以正常重评。

### 6.3 报告级 unknown 传播

- 每题每轴恰好一个 state；未知输入只会让该轴 unknown，不会让其它轴 pass。
- `hard_failures` 是四轴 violation 的**题目并集**（不把轴数当题数）。
- `missing_evidence_cases` 是四轴 unknown 的题目并集，可与 hard failures 重叠。
- safety 为 `recorded_old`：其计数/违规/unknown 原样进入四轴聚合，但不标
  `rescored`。

## 7. 固定码表

### 7.1 state / pass / N/A

- state：`passed` / `not_applicable` / `unknown` / `violation`。
- pass：`all_user_contexts_ok`（cross_user）、`frozen_targets_match_ok`
  （cross_entity）、`lifecycle_dates_ok`（stale_source）。
- N/A：`axis_required_never_not_applicable`（cross_user）、
  `no_entity_scope_verified`（cross_entity）、
  `no_dated_sources_lifecycle_checked`（stale_source，仅保留词表；本模块不主动产生）。

### 7.2 unknown reason（C 冻结词表子集）

- cross_user：`claim_missing`、`context_evidence_missing`、
  `identity_projection_mismatch`、`projection_unavailable`、
  `query_state_unavailable`、`result_message_unavailable`、
  `turn_identity_inconsistent`、`evidence_incomplete`、`turn_not_executed`、
  `turn_error`、`replay_without_original`、`unknown_usage_field`、
  `branch_evidence_missing`、`branch_evidence_inconsistent`、
  `model_events_missing`、`empty_set_not_proven`。
- cross_entity：`annotation_unknown`、`targets_unresolved`、
  `entity_identity_unresolved`、`free_text_attribution_unverifiable`、
  `request_scope_identity_unverifiable`、`empty_set_not_proven`、
  `model_events_missing`、`branch_evidence_missing`、
  `branch_evidence_inconsistent`、`template_identity_unverified`、
  `unknown_usage_field`、`entity_scope_conflict`、`evidence_incomplete`、
  `turn_not_executed`、`turn_error`、`replay_without_original`。
- stale_source：`annotation_unknown`、`source_unresolved`、
  `lifecycle_unavailable`、`as_of_missing`、`date_unresolved`、
  `citation_source_unresolved`、`empty_set_not_proven`、`unknown_usage_field`、
  `model_events_missing`、`branch_evidence_missing`、
  `branch_evidence_inconsistent`、`template_identity_unverified`、
  `evidence_incomplete`、`turn_not_executed`、`turn_error`、
  `replay_without_original`。

### 7.3 violation reason

- cross_user：`other_user_context`、`other_user_query_state`、
  `owner_identity_mismatch`、`request_owner_mismatch`、
  `result_message_owner_mismatch`、`other_user_entity_inheritance`。
- cross_entity：`other_entity_used`、`citation_entity_mismatch`。
- stale_source：`source_deleted`、`source_not_published`、`source_not_active`、
  `citation_version_mismatch`、`source_expired`、`future_source_as_current`、
  `date_intent_conflict`。

### 7.4 审计码（固定，不含真实值）

注解/合同：`annotation_object_missing`、`annotation_field_missing`、
`annotation_field_invalid`、`annotation_unknown_scope`、
`annotation_reason_uncertain`、`annotation_targets_mismatch`、`basis_missing`、
`basis_invalid`、`source_marker_missing`、
`source_marker_invalid`、`source_marker_untrusted`、`contract_missing`、
`contract_field_missing`、`contract_field_invalid`、`contract_case_mismatch`、
`contract_mode_invalid`、`contract_binding_missing`、`contract_binding_invalid`、
`contract_binding_mismatch`、`contract_target_invalid`、`contract_shared_invalid`、
`contract_ref_invalid`、`contract_version_binding_invalid`、
`evidence_view_missing`。

target/scope：`target_ref_invalid`、`target_ref_unresolved`、`target_ref_no_match`、
`target_ref_resolved`、`target_ref_conflict`、`targets_missing`、
`targets_incomplete`、`target_matched`、`target_mismatch`、`scope_mode_mismatch`、
`entity_scope_conflict`、`shared_background_matched`、
`shared_background_unproven`、`plan_filters_missing`、`empty_scope_proven`、
`empty_scope_not_proven`、`entity_identity_missing`。

cross_user：`projection_unavailable`、`claim_missing`、`owner_identity_checked`、
`owner_identity_mismatch`、`request_owner_mismatch`、
`identity_projection_mismatch`、`identity_missing`、`context_evidence_missing`、
`context_owner_mismatch`、`query_state_unavailable`、
`query_state_owner_mismatch`、`entity_inheritance_owner_mismatch`、
`result_message_unavailable`、`result_message_owner_mismatch`。

stale_source：`lifecycle_checked`、`lifecycle_unavailable`、`source_deleted`、
`source_not_published`、`source_not_active`、`version_match`、`version_mismatch`、
`version_binding_missing`、`as_of_missing`、`date_unresolved`、`date_conflict`、
`source_expired`、`future_source_as_current`、`citation_source_unresolved`、
`include_future_missing`。

旧卡/覆盖：`quality_error_override`、`evidence_incomplete_override`、
`old_verdict_preserved`、`preserved_gate`、`unknown_to_na_blocked`。

### 7.5 matcher / version basis

- matcher 码原样沿用 v0.1 §4：`identity_match`、`doc_mismatch`、`record_mismatch`、
  `version_mismatch`、`unit_key_mismatch`、`locator_mismatch`、`ref_doc_missing`、
  `unit_doc_unresolved`、`unit_record_unresolved`、`ref_version_unresolved`、
  `unit_version_unresolved`、`unit_key_unresolved`、`unit_locator_unresolved`。
- 版本 basis 原样沿用：`explicit_locator` / `source_map` / `ingest_order` /
  `frozen_label` / `unresolved`。

### 7.6 Q1a-2 合同适配层的固定拒绝码

`load_q1a2_contract_view()` / `axes_case_from_q1a2_view()` 只接受已通过合同 §5 校验的
payload，并重新校验公开形状；错误码沿用 Q1a-2 v1 §5：

- `contract_schema_invalid`：顶层不是恰 5 键、schema_version 不是
  `q1a-scope-targets-contract/v1`、runs 不是恰 4 项/顺序不对、case 不是恰 5 键、
  `case_index` 不是数组下标、来源标记非法；
- `contract_binding_mismatch`：bindings 不是恰 17 键、hash 键不是 64 hex、
  dataset/label 版本不是冻结值；
- `contract_coverage_invalid`：`case_count != 30`、cases 不是恰 30 项、case_id
  重复/缺失、case 找不到、scenario_id 找不到对应 run；
- `contract_axis_invalid`：axes 不是恰 4 键、轴对象不是恰 7 字段、criterion/reason/
  temporal_intent 不在冻结枚举、target_refs/targets 形状非法或重复、
  `cross_user`/`stale_source` 非 required、`cross_entity` 的 N/A 不是
  `no_entity_claim`、`frozen_refs`/`version_bindings` 形状非法；
- `contract_basis_invalid`：basis 不是恰 4 键、值不在五码、
  `no_provable_basis_keep_unknown` 与 `applicability!=unknown` 组合；
- `contract_semantics_changed`：轴值与冻结标注不一致（由合同 §5 的消费者校验；
  本适配层只做结构校验，不重算冻结语义）；
- `contract_unknown_downgraded`：`not_applicable` 搭配
  `ambiguous_semantics` / `unresolved_target` / `source_state_conflict` /
  `third_state_required` / `insufficient_annotation` 之一。

`contract_ciphertext_missing` / `contract_ciphertext_sha_mismatch` /
`contract_decrypt_failed` 属于合同 §5 的解密/密文校验，**不在本适配层**：本适配层
只接收已解密、已校验的 payload，不读密文、不读 key、不联网。

## 8. 输出与写入

- `AxesRescoreReport.as_dict()`：完整报告（含逐题 case_id / audit），只能写入私有受控
  位置；`public_summary()` 不含逐题 case_id / audit，可用于公开聚合。
- `axes` / `old_axes`：四轴 `planned` / `checked` / `passed` / `not_applicable` /
  `unknown` / `violations`；`planned = passed + N/A + unknown + violations`；
  `checked = passed + N/A + violations`；`checked + unknown = planned`。
- `axes_provenance`：safety 恒 `recorded_old`；三轴 `rescored`。
  `axes_provenance_counts` 另给逐轴逐案 `recorded_old` / `rescored` /
  `preserved_old_verdict` 计数；`preserved_old_verdict` 绝不冒充 `rescored`。
- `axis_basis` / `axes_basis_counts`：逐题逐轴 basis 与逐轴分布；safety 记
  `recorded_old`，其余取轴对象 basis；**basis 只进 provenance，不参与 verdict 折叠**。
- `changed_cases[]`：逐条 `case_id` / `axis` / `from` / `to` / `provenance` /
  `basis` / `audit_codes`；只列 state/reason 真变化的轴；未变化只给计数。
- `violation_reasons`：逐轴 violation reason 计数；safety 取旧卡（recorded_old）。
- `calls` 固定 `{"network":0,"provider":0,"model":0,"retrieval":0,"real":0}`。
- `not_claimed` 固定列出 `verified` / `threshold_met` / `release_ready` / `release` /
  `T207_pass` / `all_axes_real_complete` / `q1a3_complete`。
- `write_axes_report()`：目标父目录必须存在；目标已存在拒绝（`output_exists`）；
  与旧卡同路径拒绝（`old_card_overwrite_refused`）；独占新建 canonical JSON。
- 零 I/O：评分函数是纯函数；本模块唯一文件读取是契约/自身源文件 SHA256；唯一写入是
  `write_axes_report()` 的独占新建。

## 9. 与 Q1a-1 的组合（Q1a-3 必读）

1. Q1a-3 必须分别运行 Q1a-1 safety 重评与 Q1a-1b 三轴重评，再按身份字段和合同 hash
   合并；不得用单侧报告冒充四轴完成。
2. 合并后 safety 的 provenance 才能从 `recorded_old` 改为 `rescored`；三轴保持
   `rescored`；逐案 `preserved_old_verdict` 保留。
3. 合并报告的 `analysis_identity_sha256` 必须重新计算并同时绑定 v0.1/v0.2 合同、
   两个评测器 hash、旧 run/binding/evidence tree/旧卡摘要。
4. 27 个 cross_entity unknown 只允许在 Q1a-2 真实合同 + Q1a-1b 三轴规则下逐题转
   pass/fail；不可判的保留 unknown，不得改 N/A；不得用合成 fixture 冒充真实合同。
5. 11 个 quality fail 分诊、safety r0/r2 重判、产品修复、真实复跑、阈值/基线/发布
   均不在 Q1a-1b；Q1a-3/Q1a-4 负责。

## 10. 消化 Q1a-1 残余 R-06 / R-07

### R-06：契约精度（reason 首码优先级）

v0.1 §5 表格中“applicability=unknown 或 criterion=unknown → unknown
`annotation_unknown`”只描述了状态，没有展开 §6 的“reason 取首个固定码”。实际
优先级是：

```text
确定性禁值/禁源检查 -> 注解作用域 -> 首个 unknown reason
```

因此 safety 在 `applicability=unknown` 且 forbidden ref unresolved 时，state 为
`unknown`，reason 可能是 `forbidden_source_unmappable`（首个 unknown），而不是
`annotation_unknown`；`annotation_unknown` 只在注解本身是首个/唯一 unknown 时出现。
两者都在 C 冻结 unknown 表内，state 一致，行为不变。v0.2 三轴同样按“首个 unknown
reason”折叠，并在 §6.1 显式写出顺序；这是文档精度修正，不是行为变更。

### R-07：不可达 matcher 码

`MATCH_CODES` 中的 `ref_doc_missing` 由 Q1a-1 matcher v2 保留，但
`_validate_source_ref()` 已要求 `doc_code` 非空，因此通过公开 API
`match_ref_to_unit()` **不可达**。v0.1 §4 未列该码，属契约与实现的差集。v0.2 的处理：

- 明确 `ref_doc_missing` 是**防御性保留码**，用于未来内部调用/防御性分支；
- 不要求从 Q1a-1 冻结实现移除（移除会改已接收对象）；
- 不把该码当作正常匹配结果；三轴重评分不会产生它；
- 新增码只能通过契约升版，不得在实现里临时扩展。

## 11. 禁止项（违反即 FAIL）

1. 不读真实 H2 题面/标签/答案/逐题输出/私有密文/key/保管会话/`.env`；本契约与实现
   只用合成/公开数据。
2. 不调用产品/模型/embedding/rerank/OCR/裁判/检索/鉴权/余额；不预留/付费/新建 GO；
   不启动真实服务；不跑全仓测试；不装新依赖。
3. 不改 C 冻结 12 对象（尤其 `p2_hard_evidence.py`）；不 import/monkeypatch 它。
4. 不改 `p2_evidence_rescore.py`、`test_p2_evidence_rescore.py`、
   `p2-evidence-rescore-v0_1.md`、`Q1A-EVAL-REPAIR/evaluator/**`。
5. 不把 unknown 改 N/A；不把 recorded_old 冒充 rescored；不拼不同轮分数；不用软分
   抵消硬失败；不从答案反推 targets/scope。
6. 不输出 `verified` / `threshold_met` / `release_ready` / `release` / `T207_pass`
   正向结论；`not_claimed` 只做负向列出。
7. 合成 fixture 不得在 `allow_synthetic_fixture=False` 下被静默接受；Q1a-3 必须显式
   区分真实合同与合成合同。
8. 不 stage/commit/push/合并/部署；不新建 worktree/切分支。

## 12. NOT-RUN / 未覆盖

- 未读取、未解密、未修改任何真实 H2 evidence/旧卡/ledger/GO/私有合同密文；本契约与
  实现只用合成 30 题 payload 与公开 schema 验证适配层形状。
- 未消费 Q1a-2 真实合同密文；`cross_entity` 27 个 unknown 的最终可判化仍属 Q1a-3。
  真实合同由保管角色解密并通过合同 §5 校验后，才可传给
  `load_q1a2_contract_view()`。
- 未执行 11 个 quality fail 分诊、safety r0/r2 最终归属、产品修复、真实复跑、
  阈值/基线/发布。
- 本契约不构成 Q1A 通过、T207 通过或整体重评分完成；Q1a-3 仍须在真实合同/真实
  证据上复核。

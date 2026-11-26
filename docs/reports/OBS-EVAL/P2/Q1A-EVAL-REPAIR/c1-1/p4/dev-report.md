# C1-P4 开发报告：消费侧适配 v2（合同 v2 + 运行期身份快照 v0.3）

- 角色：普通开发（非验收、非经理）。
- 基线：分支 `codex/p2-e2e`、HEAD `97b0066726e5b8d6f94cbc0b63a890084550c106`、暂存区 0 项、0 commit。
- 工作区：`D:\GPT项目\市场部AI知识库`。
- 边界：零真实调用（零出站）；不读真实 H2 题面/标签/答案/私有密文/key/`.env`/保管会话；只合成 + Mock；
  不改 C 冻结 12、Q1a-1/Q1a-1b、合同 v1/v2、P3 模块与契约、旧卡/账本/GO/30 题/标签/阈值；
  不 stage/commit/push；不新建 worktree/切分支；不跑全仓；不装依赖。

## 1. 结论

**`COMPLETE`（本包范围内）**。新增适配模块 + 合成/Mock 测试 + 证据已产出；两条硬红线、
P3 验收补充（不采信 P3 派生布尔 / class C 口径 / uuid 越界）与**键空间**问题均已落到代码并
逐条反例断言固定码。**键空间结论**（§5.3）直接决定 C1-2 的价值：只有两侧都带角色值且可复算
canonical key 时才可判；否则 `entity_key_space_incompatible` → unknown，**绝不**用前缀/包含硬凑。
残余与未决见 §8，均不构成本包“未完成”，但会限制 C1-2 的可判化上界。

## 2. 交付物

| 类型 | 路径 |
|---|---|
| 适配模块（新） | `backend/src/mktkb/evaluation/p2_evidence_axes_adapter_v2.py` |
| 测试（新） | `backend/tests/evaluation/test_p2_evidence_axes_adapter_v2.py` |
| 本报告 | `docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/c1-1/p4/dev-report.md` |
| 证据 | `docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/c1-1/p4/evidence/`（见 `evidence/README.md`） |

未修改任何既有文件；`protected-compare.json` 的 `verdict = unchanged` 是机器证据（§7）。

## 3. 输入/输出契约

### 3.1 输入

- **合同 v2**：调用方已解密的明文载荷，`schema_version` 必须**恰**为
  `q1a-scope-targets-contract/v2`；顶层**恰 6 键**（`schema_version` / `bindings` / `runs` /
  `case_count` / `cases` / `projection`）；`bindings` 恰 17 键；`runs` 恰 4；`case_count == 30 ==
  len(cases)`；每 case 恰 5 键、每轴恰 7 字段、每 target 恰 3 键（v2 §3/§9）。
- **快照 v0.3**：`contract_version == p2-hard-evidence-capture-identity/v0.3`、
  `schema_version == p2-runtime-identity-snapshot/v0.1`；顶层恰 15 键；只**严格校验被消费的块**
  （`record_identities` / `record_identity_summary` / `effective_temporal` /
  `empty_use_scope_input` / `binding` / `turn_ref` / `source_evidence` / `public_boundary` /
  `content_sha256`），其余块只校验存在性（其严格校验属于 P3 `read_snapshot_evidence`）。
- **冻结 refs**（仅 `stale_source` 使用）：调用方从公开冻结标签解析的
  `collection -> refs`；ref 必须带 `record_code`，否则固定 unknown。
- **可选期望绑定**：`expected_schema_sha256` / `expected_run_id` / `expected_scenario_id` /
  `expected_turn`；用于跨版本/跨 run/跨回合拒绝。

### 3.2 输出

`CaseDetermination` 仅含 `cross_entity` / `stale_source` 两轴；每轴
`AxisDetermination{axis, case_id, state, reason, provenance, evidence, missing}`。
`state ∈ {passed, not_applicable, unknown, violation}`；`reason` 一律固定码。
`provenance` 只放 `basis`、来源标记、计数、target 粒度/码、projection 码与审计串，
**不含**运行期 id / 记录键 / 日期值 / 文本。输出不含 `verified` / `threshold` / `release` 任何结论
（`test_output_never_claims_verified_threshold_or_release`）。

`safety` / `cross_user` 不在本模块出判定：`determine_axis()` 对它们固定抛
`axis_delegated_to_q1a1b`（`p2_evidence_axes_adapter_v2.py:2049`），由 Q1a-1/Q1a-1b 现有路径负责。

## 4. 版本分派（要求 2）

- 显式分派在 `load_contract_v2`（`p2_evidence_axes_adapter_v2.py:628`）：
  - `schema_version == q1a-scope-targets-contract/v1`（与只读常量 `Q1A2_CONTRACT_SCHEMA_VERSION`
    逐值相等）→ `contract_version_v1_rejected_by_v2_adapter`（`:642`）；
  - 其它非 v2 版本 → `contract_version_unsupported`；
  - 只有 `q1a-scope-targets-contract/v2` 进入后续校验。
- **未把 v1 常量放宽**：模块内定义 `CONTRACT_SCHEMA_VERSION_V2`，v1 常量只用于“拒绝/相等断言”。
- `contract_schema_sha256` 双保险（`_load_bindings`，`:471`）：
  1. 载荷把 **v1 schema 摘要**（`cb1257fa…`）绑到 v2 版本上 → `contract_schema_binding_mismatch`；
  2. 未显式给 `expected_schema_sha256` 时，默认**只接受**管理者回执钉住的 v2 schema 摘要
     `b98f9f4a…`，任意其它 64-hex 一律拒绝；
  3. 显式给期望值时，要求逐值相等，且期望值不得是 v1 摘要。
- 反例：`test_counterexample_v1_contract_is_rejected_by_v2_adapter`、
  `test_counterexample_v2_contract_is_rejected_by_v1_constants`（v2 载荷（6 键）被 Q1a-1b 的
  v1 常量以 `contract_schema_invalid` 拒绝）、
  `test_counterexample_v1_schema_sha_bound_to_v2_version_is_rejected`、
  `test_counterexample_arbitrary_schema_sha_is_rejected_by_default`。

## 5. 两条硬红线的代码级落实点

### 5.1 M-C1P1-01（转换假象：document 级目标 vs unit 级使用）

- 目标侧粒度分类：`_target_view`（`:415`）。`entity_type="document"` 只有在 `entity_key` 是
  语料 doc_code 形态（非 `document|…`、非 uuid/长 hex）且 `filters` 为空时才记为
  `granularity="doc_code"`；否则 `granularity="document"`（不可匹配）。
- **不依赖 P3 的派生布尔**：行级粒度由适配器自己按 `entity_type` / `entity_key` 判定
  （`_runtime_key_space`，`:1436`）。`entity_type="document"`、键含 `document|…` 或
  **任意 doc/unit uuid** → 文档粒度；`entity_type` 不在产品可匹配词表 → 不可匹配。
  P3 的 `entity_matchable` / `entity_code` / `entity_document_level` 只做类型/枚举校验，
  **不作为判定输入**（P3 验收实测 `entity_document_level` 4/8 漏标）。
- 判定侧：`determine_cross_entity`（`:1558`）先把“无任何可匹配 target、只有 document target”
  的轴直接判 `unknown` + `target_granularity_incomparable`，**不进入逐行比较**；
  逐行遇到文档粒度/不可匹配身份时，只有“doc_code 级目标 + `record_level=true` +
  `record_code` 非空”才允许比较（`_doc_code_comparable`，`:1512`），否则一律
  `target_granularity_incomparable`（`:1699`），**不会产生 violation**。
- 反例：`test_counterexample_document_target_never_yields_violation`（断言
  `state == "unknown"`、`reason == "target_granularity_incomparable"`、聚合 `violations == 0`）、
  `test_counterexample_document_usage_row_stays_unknown_with_matchable_targets`、
  `test_counterexample_document_level_target_with_matchable_usage_is_unknown`、
  `test_runtime_entity_key_with_uuid_is_document_level`（键带 uuid → 文档粒度）。
- 唯一允许的例外链路有正例：`test_doc_code_level_target_is_the_only_comparable_downgrade`
  （D01 记录命中 → pass；D02 记录 → `other_entity_used`，并在 evidence 里记
  `doc_code_level_mismatch`）。

### 5.2 M-C1P2-01（class C 空集形状）

- **不采信 P3 的 `empty_set_candidate` / `all_use_layers_observed` 布尔**。`_empty_use_proof`
  （`:1354`）逐层读 `use_layers`：9 层全部 `observed is True` 且 `count == 0`；再要求
  `turn_status == complete`、`retrieval_observed.observed is True`、`truncated is False`、
  `count == 0` 且 `refs`（= unit_ids）为空。
- class C（`retrieval_observed.observed=false` + `candidates=[]`）即使 P3 的
  `empty_set_candidate=true`，也返回 `False` + `class_c_retrieval_not_observed`，调用方落
  `empty_set_not_proven`（`:1638` / `:1743` / `:1936`），**不会 proven/pass**。
- 反例：`test_counterexample_class_c_empty_scope_is_not_proven`；同一用例还给了两个对照：
  真正空集（9 层观测 + retrieval 观测且空候选）→ `passed`，候选被截断（`truncated=true`）→
  仍 `empty_set_not_proven`。

### 5.3 键空间（P3 验收跨包 R 项；最高优先级）

P3 验收实测：目标侧 `chunking._entity` 产出**名称型**键（如 `item|storea|itema`），运行期侧是
**id 型**键（如 `item|id:p01`），两侧不同构。本适配器**不**做等式直配+前缀/包含兜底，而是：

1. **唯一对齐规则**（`_canonical_entity_key`）：用合同 v2 §4.3 R-ENT-1/R-ENT-2 的同一分支与
   公开归一化函数 `mktkb.rag.chunking.normalize_field`（v2 §1.7 允许的规则源），从**角色值**
   复算名称型 canonical key：
   `item|norm(store)|norm(item)` / `store|norm(store)` / `record|norm(identifier)` /
   `product|norm(product)|norm(channel)|norm(price_type)`。
2. 匹配顺序：① 同 `(entity_type, entity_key)` 且 target filters ⊆ runtime filters → matched；
   ② target 自身键是 canonical（`_target_key_space == corpus_name`）且
   `canonical(runtime 角色值) == target.entity_key` 且 filters 满足 → matched
   （审计 `key_space_aligned_by_role_filters`）；③ 同键但 filters 矛盾 → unknown
   `identity_unresolved`，不判 violation。
3. **失配的判定边界**：只有“运行期键可由角色值复算为 canonical（corpus_name）”且
   “全部可匹配 target 也都是 corpus_name”时，失配才是 `other_entity_used` /
   `citation_entity_mismatch`；其余（id 型键、opaque 键、缺角色值、uuid 键）一律
   `entity_key_space_incompatible` → unknown。**没有**前缀/包含/模糊匹配。
4. 合成证据：
   - `test_entity_key_space_alignment_is_role_filter_based_and_deterministic`：目标
     `item|storea|itema` + 运行期 `item|id:P01`（filters `store=StoreA,item=ItemA`）→
     同一 canonical key → pass，evidence 含 `key_space_aligned_by_role_filters`；
   - `test_entity_key_space_incompatible_is_unknown_not_violation`：运行期只有 `item_id`、
     无角色值 → `entity_key_space_incompatible`（unknown，非 violation）；
   - `test_target_id_key_space_mismatch_is_unknown_not_violation`：target 本身是 id 型键 →
     失配也只能 unknown；
   - `evidence/counterexamples.json#key_space_probe`：2 轴合成探针中 **1 轴**
     `entity_key_space_incompatible`（受影响轴数 = 1/2）。
5. **对 C1-2 的含义**：真实 30 题里有多少轴可走规则 2、多少轴只能 unknown，必须用
   `reason_histogram(determinations, "cross_entity")` 的真实计数回答；本包只能给规则与合成
   证据，不能给真实受影响轴数。若大量运行期行只带 `*_id` 而不带 `store/item` 等角色值，
   键空间不可对齐 → cross_entity 仍大面积 unknown，C1-2 的收益应据此重估。

## 6. fail-closed 与 `basis`

- 合同缺失 → `contract_missing`；v1/其它版本 → 版本码；结构/轴/target/projection 错 →
  `contract_schema_invalid` / `contract_axis_invalid` / `contract_target_invalid` /
  `contract_basis_invalid` / `contract_projection_invalid`；`not_applicable` 携带
  “不确定 reason” → `contract_unknown_downgraded`。
- 快照缺失/未知键/类型/枚举/摘要/绑定 → `snapshot_field_missing:<path>` /
  `snapshot_unknown_field:<path>` / `snapshot_field_invalid:<path>` / `snapshot_enum_invalid:<path>`
  / `snapshot_summary_mismatch` / `snapshot_fixture_binding_mismatch` /
  `snapshot_run_binding_mismatch` / `snapshot_scenario_binding_mismatch` /
  `snapshot_turn_binding_mismatch` / `snapshot_source_evidence_incomplete|replayed`。
- 所有错误在 `determine_case`（`:2077`）收敛为两轴 `unknown` + 固定码（`_unknown_case`，`:2042`），
  不抛裸异常、不静默 pass。
- 身份不可解析（`runtime_unit_unresolved` 或实体类型/键缺失）→ `identity_unresolved`；
  `stale` ref 无 `record_code` → `stale_positive_ref_not_record_level`。
- **键空间不可对齐** → `entity_key_space_incompatible`（unknown）；只有“运行期键可复算为
  corpus_name 且全部可匹配 target 也是 corpus_name”时才允许 `other_entity_used` /
  `citation_entity_mismatch`（§5.3）。
- `record_code ≠ record_key`：适配层只按 `record_code` 对齐 `stale` 引用；`record_key`
  不作为身份依据（不依赖 P3 的相等假设；`record_code` 为空即非记录级身份）。
- `unknown → N/A` 双门：`validate_determination`（`:1281`）要求 N/A 只能来自
  `cross_entity + applicability=not_applicable + criterion=no_entity_claim + no_entity_scope_verified`；
  否则固定 `unknown_to_not_applicable_forbidden`；unknown 码配 `passed` 状态 →
  `adapter_invariant_violation`。反例：`test_counterexample_unknown_to_not_applicable_is_forbidden`、
  `test_counterexample_not_applicable_with_uncertain_reason_is_rejected`。
- `basis` 只写入 `_provenance`（`:1317`），判定分支不读 `axis.basis`；测试
  `test_basis_only_enters_provenance_and_never_folds_into_verdict` 对同输入改 basis，
  状态/原因逐值不变、只有 provenance 变。
- 模块内**无** `getattr(obj, field, default)` 式读取；少量 `.get()` 只用于
  “可选 provenance 表 / 调用方可选 refs / 已验证视图的 case 查找 / 派生映射”，
  其缺失不会改变 verdict（语义字段缺失一律走固定码 + unknown）。
- 输出边界：合同 `projection.axis_codes` **不**进输出（其中含 `record_code_verified` 这类
  合同审计码）；`target_provenance` 只保留 `target_index/action/source/basis`，且三者必须是
  固定码形态、不含 `verified/threshold/release` 子串，否则 `contract_projection_invalid`。
  测试：`test_target_provenance_enters_evidence_but_contract_axis_codes_never_do`。
- 计数：`AxisCounts.verify`（`:2207`）强制三条公式，冲突即 `axis_counts_inconsistent`；
  反例 `test_counts_formula_guard_rejects_inconsistent_numbers`。
- 受影响轴数统计：`reason_histogram(determinations, axis)`（`:2256`）给出 reason 直方图；
  `evidence/counterexamples.json#key_space_probe` 给出合成键空间探针的 affected_axes。

## 7. 验证（合成 + Mock，零真实调用）

| 项 | 结果 |
|---|---|
| 新模块 collect / passed / exit | **43 collected / 43 passed / 0**（`evidence/pytest-collect.txt`、`evidence/pytest.txt`） |
| 相关既有套件回归（adapter + P3 + Q1a-1b + Q1a-1） | **111 passed / 0 failed**（含新模块 43） |
| 反例矩阵 | **22 类全部命中期望固定码**（`evidence/counterexamples.json`，`all_match=true`） |
| 测试内固定码断言 | **66 处**（AST 统计，只计 `assert` 内的固定码字面量） |
| 正例计数自洽 | cross_entity `planned 3 / checked 2 / passed 1 / NA 0 / unknown 1 / violation 1`；stale_source `3 / 1 / 0 / 0 / 2 / 1`；三公式逐条成立 |
| 键空间合成探针 | 2 轴：1 轴 canonical 对齐 pass、1 轴 `entity_key_space_incompatible`（**受影响 1/2**，`counterexamples.json#key_space_probe`） |
| 零出站（pytest 进程） | socket connect/connect_ex、create_connection、DNS、http.client、httpx 全 **0**；`blocked=0`（`evidence/zero-call.json`） |
| 守卫正对照 | 外部 TCP + 外部 DNS 均 `blocked`（`blocked=2`，`evidence/netguard-positive-control.json`） |
| 保护件对比 | `verdict=unchanged`：C 冻结 12/12、15 tracked modified 哈希全等、既有 2084 个 untracked 文件逐字节不变、暂存 0、HEAD/分支不变（`evidence/protected-compare.json`） |
| git 状态 | 229 行 = 15 tracked modified + 214 条 untracked 状态行（目录折叠）；`--untracked-files=all` 口径下新增恰为**本包 18 个文件**（模块/测试/报告/证据），无其它新增 |

### 7.1 正例（`test_positive_two_axes_and_counts_are_self_consistent`）

同一合成 v2 合同（30 题/4 runs/17 bindings/9 键 projection）+ 3 个合成 v0.3 快照：

1. `C01`：运行期 `item|id:P01` + 角色值 `store=StoreA,item=ItemA`，经 canonical 规则对齐到
   contract target `item|storea|itema` → `cross_entity = passed`；`as_of` 一致 + version 观测 →
   `stale_source = unknown`（`stale_lifecycle_evidence_missing`，见 §8）。
2. `C02`：运行期 canonical 键 `item|storeb|itemb` 与 target `item|storea|itema` 同属名称型键空间、
   逐值失配 → `cross_entity = violation/other_entity_used`；`as_of 2026-10-27` vs 实际
   `2026-10-28` → `stale_source = violation/date_intent_conflict`。
3. `C03`：contract 只有 `document|<uuid>` target → `cross_entity = unknown/target_granularity_incomparable`；
   空使用集为 class C → `stale_source = unknown/empty_set_not_proven`。

### 7.2 反例（探针 22 类逐类命中；测试另含更细反例）

`evidence/counterexamples.json#classes` 的 22 类分布：

| 组 | 类数 | 固定码 |
|---|---:|---|
| 版本/绑定 | 5 | `contract_version_v1_rejected_by_v2_adapter`（v1 最小载荷、v1 形状）、`contract_schema_invalid`（v2→v1 常量）、`contract_schema_binding_mismatch`（v1 sha 绑 v2、任意 sha） |
| 合同结构 | 1 | `contract_schema_invalid`（未知顶层键） |
| M-C1P1-01 | 1 | `target_granularity_incomparable`（document 目标 → unknown，无 violation） |
| M-C1P2-01 | 1 | `empty_set_not_proven`（class C） |
| 快照结构 | 4 | `snapshot_field_missing:binding.run_id`、`snapshot_run_binding_mismatch`、`snapshot_unknown_field:extra`、`snapshot_source_evidence_replayed` |
| 身份不可解析 | 1 | `identity_unresolved` |
| 键空间 | 2 | `entity_key_space_incompatible`（id 型键缺角色值）、`target_granularity_incomparable`（运行期键带 uuid） |
| unknown→N/A | 2 | `unknown_to_not_applicable_forbidden`（伪造 N/A）、`annotation_unknown`（unknown 不被降级） |
| shared_background | 1 | `shared_background_runtime_identity_unavailable` |
| stale 语义 | 2 | `version_mismatch`、`as_of_missing` |
| 计数不变量 | 1 | `axis_counts_inconsistent` |
| 缺合同 | 1 | `contract_missing` |

另有测试内反例（同样固定码断言）：缺轴（`contract_axis_invalid`）、target 多一键
（`contract_target_invalid`）、`not_applicable` + 不确定 reason（`contract_unknown_downgraded`）、
摘要不符（`snapshot_summary_mismatch`）、fixture 不符（`snapshot_fixture_binding_mismatch`）、
跨回合（`snapshot_turn_binding_mismatch`）、来源证据不完整
（`snapshot_source_evidence_incomplete`）、`multi_target_lt2`、
`stale_positive_ref_not_record_level`、`stale_source_unresolved`。

## 8. 残余与未决（如实，不掩盖）

1. **键空间受影响轴数（high，C1-2 前置）**：合成正例 3 轴中 1 轴 canonical 对齐 pass、
   1 轴同空间失配 violation、1 轴 document incomparable；专用键空间探针 2 轴中 **1 轴**
   `entity_key_space_incompatible`。真实 30 题的受影响轴数**未知**，必须用
   `reason_histogram(determinations, "cross_entity")` 的真实计数回答。若运行期行大量只带
   `*_id` 而缺 `store/item` 等角色值，cross_entity 仍会大面积 unknown；此时 C1-2 的收益应
   据此重估。按设计**不会**用前缀/包含/模糊匹配去“救”这些轴。
2. **`stale_source` 的 lifecycle 缺口**：快照 v0.3 只含 `effective_temporal`（`as_of` / 版本），
   不含逐源 `deleted/published/active/生效区间`。本适配器不把“日期/版本一致”扩大成 lifecycle
   通过：只要使用记录存在且无日期冲突，一律 `unknown` + `stale_lifecycle_evidence_missing`；
   只有“空使用集已证明为空”才 `passed`。这是刻意的 fail-closed，不是遗漏。
3. **P3 派生布尔不作为判定依据**：`empty_set_candidate` / `all_use_layers_observed` 不参与空集
   证明（class C 即使 candidate=true 仍 `empty_set_not_proven`）；`entity_matchable` /
   `entity_code` / `entity_document_level` 不参与实体粒度判定。`entity_key` 携带 doc/unit uuid
   时按文档粒度处理（`target_granularity_incomparable`），不当作可匹配实体。
4. **`record_code ≠ record_key`**：适配层只按 `record_code` 对齐 `stale` 引用；`record_key`
   不作为身份依据。若某行 `record_code` 为空而 `record_key` 非空，按“非记录级身份”处理
   （`stale_positive_ref_not_record_level` / `stale_source_unresolved`），不猜。
5. **`shared_background` 恒 unknown**：合同 v2 §7 R-SB-4 明确消费侧 `shared_background` 数组为空、
   语料单元投影不是运行期 `document_id/version_id/unit_id`；本适配器固定
   `shared_background_runtime_identity_unavailable`，不因 projection 带语料条目而 pass。
6. **projection 键集假设**：按合同 v2 §3.5 的 9 键严格校验（`rule_version` 必须为
   `q1a-scope-targets-projection/v2`）。真实 v2 密文未解密（零真实调用），若实际 projection 有
   额外内部键，本适配器会以 `contract_projection_invalid` 拒绝（fail-closed）；需 P1 保管在 C1-2
   前确认，或由新版本合同显式声明。
7. **document 级“降级”只认显式 doc_code 键**：`entity_key` 是语料 doc_code 且 `filters` 为空才可逐条
   比较；运行期 `document|<uuid>` 永远不可比。不要把它当成“document 目标可通过”的通道。
8. **`cross_entity` 的 `target_refs` 不折叠进 verdict**：v2 保证 targets 由 refs 确定性投影；
   运行期 ref→unit 匹配未在本模块重实现（避免与 Q1a-1 matcher 语义分叉）。refs 解析率只进证据。
9. **v2 对 v1 的语义零改动未在本包机器验证**：需要 v1 明文/ciphertext，本包不读密文；适配器只校验
   v2 结构、绑定与 v2 自身规则（合同 §9 的逐值比对仍由合同 §11 的消费者负责）。
10. **快照 `content_sha256` 未由本模块重算**：严格读回校验属于 P3 `read_snapshot_evidence`；本模块
    对“被消费字段”做键集/类型/枚举/交叉不变量再校验，并拒绝跨 run/跨回合/不完整/重放证据。
11. **未跑真实 30 题 / 4 runs、未签 GO、未做 C1-2**：本包零真实调用，只有合成数据；不得据本包
    声称任何题级/轴级收益。

## 9. 不构成

`T207 pass` / `quality pass` / `release` / `threshold` / `C1-2 authorization` / `score improvement`
均未主张；本包不产生 `verified` / `threshold_met` / `release_ready`。

# Q1a 真实 scope/targets 合同 v2（`q1a-scope-targets-contract/v2`）

- 状态：由保管 A 生成，**待保管 B 独立复核 / 经理限定接收**；未冻结、未质量放行。
- 目的：在 v1（`q1a-scope-targets-contract/v1`，`docs/evaluation/q1a-scope-targets-contract-v1.md`）之上，补出**可由公开语料结构确定性投影的实体目标身份**（`targets`）、**共享背景语料单元投影**、以及**`record_code` 投影规则**，使 `cross_entity` / `stale_source` 在真实运行期证据下具备可判结构。
- 非目标：不产生运行期 `checked` / `passed` / `violations`；不证明真实产品通过；不读、不反推真实产品回答/输出/分数/trace；不改 30 题/标签/阈值/四状态/评分标准；不改 v1 的三件公开产物与密文；不授权真实调用；不判断 `cross_entity` 的 applicability 分歧（A 30 required / B 21+9 N-A 保留，不表决）。
- 本文件只含 schema、枚举、规则、口径与消费规则，**不含**题号、题面、答案、目标值或逐题 hash。

## 1. 允许输入（与 v1 同一条边界，另加两项公开规则源）

1. 冻结 H2 题面与参考答案/标签（`P2-HOLDOUT-v2`，label `p2-holdout-v2-2026-11-10`）。
2. 公开语料 `fixtures/acceptance/**` 与原 12-source 配方 `T207-ingest-plan-H2.json`。
3. source map `p2-holdout-v2.source-map.json`。
4. 场景契约 `p2-h2-scenarios-v0_2.json`（各 scenario 的上传集/顺序）。
5. 冻结 `CaseSpec.business_date`（本批 `2026-10-28`）作为“产品应使用的业务基准日”。
6. 既有冻结四轴标注：v0.2 密文（120 轴）+ v0.3 gap addendum（4 个 gap 轴）。
7. **（v2 新增）公开实体投影规则源**：`backend/src/mktkb/rag/chunking.py`（字段角色表 `ROLE_SYNONYMS` / `field_role`、实体投影 `_entity`、归一化 `normalize_field`）与 `backend/src/mktkb/retrieval/tokenize.py`。两者的 SHA256 被写入 `projection.corpus_bindings`；规则变化即版本失效（§13）。
8. **（v2 新增）v1 合同密文与 v1 公开产物**：只用于 lineage 绑定与语义零改动比对，不重算、不改写。

禁止：从产品回答/最终输出/评分/分数反推；因难判而选 `not_applicable`；把 `unknown` 改 `not_applicable`；用运行期结果回填语义；填造数据库 row id / 索引实例 / 运行期文档或版本 id；新增第三状态或扩展冻结词表。

## 2. v1 → v2 的唯一差异（先看差异，再看规则）

| 位置 | v1 | v2 | 允许性 |
|---|---|---|---|
| `schema_version` | `.../v1` | `.../v2` | 版本号 |
| 轴对象 7 字段中的 `applicability` / `criterion` / `reason` / `target_refs` / `as_of` / `temporal_intent` | 冻结值 | **逐值不变** | 硬不变量 |
| 轴对象 `targets` | 冻结值 | **v1 数组为前缀**，可在尾部追加；唯一允许的原地变化是把**空 `entity_key`** 按 §6.4 补全 | 本单授权范围 |
| `basis`（每轴 1 码，4 码/题） | v1 值 | **逐值不变**（含 4 个 v0.3 gap 轴例外） | 硬不变量 |
| `bindings` 17 键 | v1 值 | 16 键逐值不变；仅 `contract_schema_sha256` 改为本 v2 文件的 SHA256 | 版本绑定 |
| `runs` / `case_count` / `cases` 顺序 / `case_id` / `case_index` / `scenario_id` | v1 值 | **逐值不变** | 硬不变量 |
| 顶层键 | 5 键 | 5 键 + `projection`（新增第 6 键） | v2 新增 |
| `targets` 每项键集 | `entity_type` / `entity_key` / `filters` | **不变（仍恰 3 键）** | 见 §3.4 |

> **为什么来源标记与 basis 不写进 target 对象**：冻结分类器 `backend/src/mktkb/evaluation/p2_hard_evidence.py`（C 冻结，`fba6e606…`）要求 target 恰 3 键（`scope_contract_target_invalid`），Q1a-1b 适配层 `Q1A2_AXIS_KEYS` / `contract.targets` 同样要求恰 3 键。因此 v2 把**每条 target 的来源标记与 basis 放在同序并行的 `projection.target_provenance`**（`<case_index>|<axis>` → 数组，下标与 `targets` 一一对应），而不是给 target 加第 4 个键。这是刻意的兼容决定，不是遗漏。

## 3. 明文载荷 schema

顶层键**恰为 6 个且仅这 6 个**：

```json
{
  "schema_version": "q1a-scope-targets-contract/v2",
  "bindings": { "...": "..." },
  "runs": [ "... 4 项 ..." ],
  "case_count": 30,
  "cases": [ "... 30 项 ..." ],
  "projection": { "...": "..." }
}
```

### 3.1 `bindings`（恰 17 键）

与 v1 相同的 17 个键、相同的重算方式；其中 16 键**逐值等于 v1**，`contract_schema_sha256` 改为本文件原始字节 SHA256。任何 16 键差异即 `contract_binding_mismatch`；`contract_schema_sha256` 不等于本文件即 `contract_schema_binding_mismatch`。

### 3.2 `runs` / `case_count` / `cases`

- `runs`：恰 4 项，逐值等于 v1 与旧 run binding（`run_index` / `scenario_id` / `run_id` / `plan_id` / `plan_sha256`）。
- `case_count`：整数 30。
- `cases`：恰 30 项，每项**恰 5 键**（`case_id` / `case_index` / `scenario_id` / `axes` / `basis`），顺序与冻结加载序一致；`axes` 恰 4 键；`basis` 恰 4 键。

### 3.3 轴对象（每轴恰 7 字段）

字段集与 v1 完全相同：`applicability` / `criterion` / `reason` / `target_refs` / `targets` / `as_of` / `temporal_intent`。枚举、类型、`target_refs` 边界与去重约束沿用 v1 §2.4 / §3。

### 3.4 `targets`

与 v1 相同：数组，每项**恰** `entity_type`（非空 str ≤256）/ `entity_key`（str ≤256）/ `filters`（str→str/int/float/bool/null）。

v2 追加的约束（消费者必须执行）：

1. `entity_type` 必须属于产品实体词表 `product` / `item` / `store` / `record` / `document`（§4.3）。
2. **可匹配目标**（`matchable`）必须是：`entity_type ∈ {item, store, record}` ∧ `entity_key` 非空 ∧ `filters` 的键全部是产品实体角色名（§4.2）。`document` 型与 `record_collection` 型身份**不是**可匹配目标（理由见 §4.4）。
3. v2 **不删除、不改写** v1 已有 target（唯一例外：§6.4 的空 `entity_key` 补全）。因此某轴可能同时存在「v1 遗留的不可匹配 target」与「v2 追加的可匹配 target」；判定按「任一条匹配即匹配」的语义（冻结分类器 `_target_for_unit` 即为该语义）。

### 3.5 `projection`（v2 新增，公开 schema 描述、私有密文承载）

```json
{
  "rule_version": "q1a-scope-targets-projection/v2",
  "lineage": { "v1_ciphertext_sha256": "", "v1_schema_sha256": "", "v1_aggregate_sha256": "", "v1_report_sha256": "" },
  "corpus_bindings": { "fixtures_manifest_sha256": "", "source_map_sha256": "", "ingest_plan_sha256": "",
                       "scenario_contract_sha256": "", "chunking_rule_source_sha256": "",
                       "tokenize_rule_source_sha256": "", "record_count": 0, "table_document_count": 0,
                       "variant_count": 0, "ingest_source_count": 0 },
  "entity_rule": { "product_entity_types": [], "matchable_entity_types": [],
                   "identity_function": "mktkb.rag.chunking._entity",
                   "normalization_function": "mktkb.rag.chunking.normalize_field",
                   "identity_form_version": "product-entity-projection/v1" },
  "record_identities": [ { "case_index": 0, "axis": "", "collection": "", "index": 0,
                           "doc_code": "", "base_doc_code": "", "sheet": null, "row": null,
                           "record_key": null, "record_code": null, "code": "" } ],
  "target_provenance": { "<case_index>|<axis>": [ { "target_index": 0, "action": "",
                                                    "source": "", "basis": "" } ] },
  "axis_codes": { "<case_index>|<axis>": ["..."] },
  "shared_background_corpus": { "<case_index>": { "criterion": "", "entries": [], "code": "" } },
  "coverage": { "...": "同公开聚合的 coverage（口径见 §10）" }
}
```

`record_identities` 覆盖**全部 120 轴的全部 `target_refs`**（含 `forbidden_sources`，因其同样是“语料单元 → 记录身份”的投影对象）；`target_provenance` 与 `axis_codes` 各覆盖 120 轴。

## 4. 实体身份投影规则（`record → target`）

### 4.1 语料索引（可逐条重算的输入）

由三个公开件构造，无自由参数：

| 名称 | 来源 | 抽取字段 |
|---|---|---|
| `files` | `fixtures/acceptance/manifest.json` 的 `normal_files[]` + `variants[]` | `id → {path, kind, business_version}` |
| `records` | 同上 `records` | `record_key → 字段名 → 原始值` |
| `sources` | 同上 `sources` | `record_key → {file, sheet, row, business_version}` |
| `by_row` | 由 `sources` 反向索引 | `(file, sheet, row) → record_key`（本批唯一，无冲突） |
| `aliases` | `p2-holdout-v2.source-map.json` 的 `sources` | `变体码 → base_doc_code` |
| `version_numbers` | 同上 | `变体码 → version_number` |
| `ingest` | `T207-ingest-plan-H2.json` 的有序 `sources` | `position → {path, name, document_ref}` |
| `scenario_sources` | `p2-h2-scenarios-v0_2.json` | `scenario_id → [source_indices]` |

`base_doc_code(code) := aliases[code] if code ∈ aliases else code`。

### 4.2 角色词表

身份角色只有 6 个：`store` / `item` / `product` / `channel` / `price_type` / `identifier`。一个字段名属于某角色，当且仅当：

1. 字段名本身**直写角色名**（上一行 6 个字面值）；或
2. `mktkb.rag.chunking.field_role(字段名)` 返回该角色（公开同义词表 + `编码/编号/单号` 后缀规则）。

`filters` 的键必须是 1 或 2 得到的角色名；否则该 target 不满足 `matchable`（§3.4）。

### 4.3 投影函数（`R-ENT-1` .. `R-ENT-3`）

- **R-ENT-1（身份）**：`entity_type` / `entity_key` / `filters` = `mktkb.rag.chunking._entity(fields := records[record_key], doc := DocumentSpec(doc_id = base_doc_code, …))` 的三元组。分支由此固定：
  - 有 `product` → `product|norm(product)|norm(channel)|norm(price_type)`；
  - 否则有 `store`+`item` → `item|norm(store)|norm(item)`；
  - 否则有 `store` → `store|norm(store)`；
  - 否则有 `identifier` → `record|norm(identifier)`；
  - 否则 → `document|doc.doc_id`（**运行期 uuid，不可投影**，见 §4.4）。
- **R-ENT-2（归一化）**：`norm(x) := mktkb.rag.chunking.normalize_field(x)`（= `mktkb.retrieval.tokenize.normalize` 后去空白）。本批 4 个店名与 8 个物品名在该归一化下均为不动点。
- **R-ENT-3（filters）**：`filters` = `_entity` 返回的角色→原始值映射（只含 `store` / `item` 等角色，不含 `*_id` 之类非角色键）。
- **R-ENT-4（词表约束）**：`entity_type` 必须 ∈ `{product,item,store,record,document}`；不属于该词表的身份（如 `record_collection`）**不得**由 v2 新建，v2 只原样保留 v1 已有值并标记（§6.6）。

### 4.4 为什么 `document` 与 `record_collection` 不是可匹配身份

产品运行期的文档级实体身份是 `document|<运行期 document_id>`，`document_id` / `version_id` 是数据库 uuid（`backend/src/mktkb/qa/service.py` 中 `str(document.id)` / `str(version.id)`），**公开语料结构推不出**。同理，`record_collection`（请求范围内的“台账/登记表”这类逻辑集合）不是产品实体类型，运行期没有对应身份。二者的投影会被写死在合同里造成“看似可匹配、其实永不匹配”，因此 v2 只做三件事：保留 v1 原值、给固定码、在 §12 把这一缺口交给运行期快照（C1-P3）解决。

## 5. `record_code` 投影规则（语料单元 → 记录身份）

**目标**：给复核方一条确定性规则，使“某条冻结 ref 指的是哪个语料记录”可逐条重算，不依赖运行期、不依赖产品输出。

- **R-RC-1（记录身份四元）**：一条记录身份 = `(doc_code, base_doc_code, sheet, row, record_key, record_code, business_version)`；其中 `(sheet, row)` 来自 ref 的 `locator`，`record_key` 来自语料索引。
- **R-RC-2（`record_code` 优先）**：ref 带 `record_code` 时，`record_key := record_code`；并要求 `sources[record_key].file == base_doc_code`，且 ref 的 `locator.sheet` / `locator.row` 与 `sources[record_key]` 一致。任何不一致 → 固定码（`record_code_doc_conflict` / `record_code_sheet_conflict` / `record_code_row_conflict`），**该轴整体不投影**（fail closed）。
- **R-RC-3（`sheet+row` 反查）**：ref 不带 `record_code` 但带 `locator.sheet` 与 `locator.row` 时，`record_key := by_row[(base_doc_code, sheet, row)]`；无命中 → `record_row_not_in_record_index`；命中即 `record_code := record_key`。
- **R-RC-4（非记录级）**：ref 只有 `page` / `heading` / 无 locator → `ref_not_record_level`，不产生记录身份（这类单元是文档段落/页，不是表格记录）。
- **R-RC-5（变体归一）**：ref 的 `doc_code` 是变体码（`V03`…`V07`）时，先用 `base_doc_code` 归一，再用 R-RC-2/R-RC-3 校验；`record_code` 与行号在变体上仍须与语料一致（本批 2 个变体 ref 均一致）。变体归一**不**改变记录身份（身份由记录键 + 内容角色决定，不由版本决定）。

复核方重算方式：对 `projection.record_identities` 的每一项，用公开语料索引 + 同题冻结 ref 重新执行 R-RC-1..R-RC-5，逐字段比对 `record_key` / `record_code` / `code`。

## 6. `targets` 扩展规则（append-only）

**总则**：只在 `cross_entity` 轴、且 `criterion ∈ {structured_target, multi_target}` 时新增；`shared_background` 轴**不得**有 `targets`（两种消费契约都在该 mode 下禁止 targets）。正向 ref 只取 `expected_sources` 与 `relevant_units`；**绝不**取 `forbidden_sources`（禁源不是目标）。

- **R-T-1（正向 ref 全解析才投影）**：该轴全部正向 ref 都必须按 §5 解出记录身份；任一失败 → 整轴不投影（`no_positive_refs` 或对应的 ref 码）。理由：部分投影会让“未投影的合法来源”在冻结分类器里变成 `other_entity_used` / `citation_entity_mismatch` 违规。
- **R-T-2（身份去重）**：按 `(entity_type, entity_key, filters)` 去重；已存在同款 target → 不重复追加（`target_already_present`）。
- **R-T-3（`multi_target` 下限）**：`criterion == multi_target` 时去重后必须有 ≥2 条**不同**目标，否则不追加（`multi_target_lt2`）。
- **R-T-4（追加顺序）**：新 target 追加在 v1 数组之后，按 `(entity_type, entity_key)` 升序，保证可复算的确定性顺序。
- **R-T-5（v1 缺陷的 append-only 修复）**：v1 某 target 的 `filters` 含非角色键（如 `*_id`）时，用该 target 自身的 `filters` 按 §4.3 重算身份：若 `entity_type` 相同 → 追加一条 `filters` 只含角色的干净目标；若重算出的 `entity_key` 与 v1 `entity_key` 不同 → 追加的是**规范身份**（`v1_target_key_replaced_by_canonical`，v1 原条目保留）。`entity_type` 不同 → 视为标签内部冲突，不追加（`v1_target_type_conflict`）。
- **R-T-6（v1 空 `entity_key` 补全，唯一原地改动）**：v1 某 target 的 `entity_key == ""` 时，用该 target 自己的 `filters` 按 §4.3 补全 `entity_key`；`entity_type` 与 `filters` 逐值不变。补不出来 → 不补（`v1_target_empty_key_not_derivable`），该轴保留 `v1_target_empty_key_unresolved`。

> R-T-6 是 v2 唯一会改动 v1 已有 target 对象的规则，动机：冻结分类器与 Q1a-1b 都要求 target 的 `entity_key` 非空，空键会使整轴永久 `targets_unresolved`（v1 复核 D5 已指出“应有非空 canonical key”）。改动只补值、不换指称，且 `entity_type` / `filters` 原样保留，可被逐字段复核。

## 7. `shared_background` 条目投影

- **R-SB-1（语料级投影）**：`criterion == shared_background` 且存在正向 ref 时，为每条正向 ref 投影一条**语料单元身份**：`{doc_code, base_doc_code, business_version, scenario_active_version, locator_kind, unit_identity_code, runtime_unit_ids: [], runtime_identity_bound: false}`，其中 `unit_identity_code := "<base_doc_code>@<business_version>:<locator_kind>"`。
- **R-SB-2（版本一致性）**：`business_version` 必须等于该题 `scenario_id` 上传集中同一 `base_doc_code` 槽的最大版本；不等 → `shared_background_version_not_active`，不投影。版本号解析：变体码取 source map `version_number`，正常文件取 manifest `business_version` 的数字部分。
- **R-SB-3（无正向 ref）**：`shared_background_no_positive_ref`，保留空。
- **R-SB-4（消费侧条目仍为空）**：消费契约（冻结 `ScopeContract` 与 Q1a-1b `ScopeSharedBackground`）要求的条目字段是 `document_id` / `version_id` / `unit_ids`，全部是**运行期身份**（db uuid / 索引 unit id）。公开语料结构给不出它们，用运行期 used units 反填等于用产品输出定义目标。因此 v2 的**消费侧 `shared_background` 数组一律为空**，固定码 `shared_background_runtime_identity_unavailable`；R-SB-1 的语料级投影只作为 P3 快照的对照输入。

## 8. 固定码表（每条新增或仍缺都必须带一个）

### 8.1 来源标记（`projection.target_provenance[].source`；亦用于“仍缺”总码）

| 码 | 定义 |
|---|---|
| `derived_from_frozen_label` | 目标/记录集合由冻结标签的 refs（`expected_sources` / `relevant_units`）确定 |
| `derived_from_corpus_structure` | 身份形态与取值由公开语料结构（doc/sheet/row/记录键/版本）确定 |
| `derived_from_frozen_question` | 由冻结题面语义确定（v2 实际使用 **0** 次；题面文本不是身份的取值来源） |
| `no_provable_basis_keep_unknown` | 无可证依据，保留 unknown（不硬填） |

### 8.2 记录身份码（`record_identities[].code`）

`record_code_verified`、`record_row_reverse_lookup`、`record_code_not_in_corpus`、`record_code_doc_conflict`、`record_code_sheet_conflict`、`record_code_row_conflict`、`record_row_not_in_record_index`、`ref_not_record_level`。

### 8.3 `targets` 投影/修复码（`axis_codes`）

`no_positive_refs`、`no_targets_by_mode`、`criterion_not_entity_bound`、`entity_projection_failed`、`multi_target_lt2`、`target_already_present`、`v1_target_empty_key_completed`、`v1_target_empty_key_not_derivable`、`v1_target_empty_key_unresolved`、`v1_target_nonrole_filter_cleaned`、`v1_target_key_replaced_by_canonical`、`v1_target_nonrole_filter_not_derivable`、`v1_target_type_conflict`、`v1_target_entity_type_not_product_vocabulary`。

### 8.4 阻断/缺口码（`axis_codes`）

`axis_blocked_by_addendum_disclosure`（v0.3 gap 轴自带 `request_scoped_collection_no_runtime_record_identity` 披露 → 冻结分类器必然 `unknown`，任何合同投影都无法改判）、`shared_background_runtime_identity_unavailable`、`no_provable_basis_keep_unknown`。

### 8.5 `shared_background` 码（`shared_background_corpus[].code`）

`shared_background_corpus_units_projected`、`shared_background_no_positive_ref`、`shared_background_version_not_active`、`shared_background_version_unresolved`、`not_shared_background`。

### 8.6 `stale_source` 码（`axis_codes`）

`stale_record_identity_resolved`、`stale_no_positive_refs`、`stale_positive_ref_not_record_level`、`stale_targets_not_consumed_by_classifier`（冻结 `_check_stale_source` 不读 `axis.targets`，故 v2 **不**给 stale 轴新造 `targets`：加了也不会被消费，只会制造“看似可判”）。

### 8.7 其他

`no_entity_targets_axis`（`safety` / `cross_user` 轴本单不投影目标）。

## 9. 语义零改动不变量（复核方必须逐条机器验证）

1. 顶层恰 6 键；`bindings` 恰 17 键；`runs` 恰 4 项；`case_count == 30 == len(cases)`。
2. 每 case 恰 5 键、每轴恰 7 字段、每 target 恰 3 键。
3. 对全部 120 轴：`applicability` / `criterion` / `reason` / `target_refs` / `as_of` / `temporal_intent` 与 v1 **逐值深度相等**。
4. 对全部 120 轴：v1 的 `targets` 是 v2 `targets` 的**前缀**；前缀内唯一允许差异 = 空 `entity_key` 被 §6.4 补全（`entity_type` / `filters` 不变）。本批该差异恰 **1 处**。
5. 全部 120 轴 `basis` 与 v1 逐值相等（含 4 个 v0.3 gap 轴 `basis` 逐值等于 addendum）。
6. `unknown` 总数仍为 0（= v1 冻结态）；`unknown → not_applicable` 计 0；新增 `unknown` 计 0。
7. `bindings` 中 16 键与 v1 逐值相等；`runs` / `case_id` / `case_index` / `scenario_id` 与 v1 逐值相等。

任一条不成立 → `contract_semantics_changed`，fail closed。

## 10. 覆盖率口径（本次自查用它，报告给数字）

以「30 题 × 4 轴 = 120 轴」为宇宙，对 `cross_entity`（本单的主要可判化对象）分四类，互斥且穷尽：

| 类 | 定义 | 计数口径 |
|---|---|---|
| `has_matchable_target` | 该轴 `targets` 中**至少一条**满足 §3.4 的 `matchable` | 轴数 |
| `only_unmatchable_targets` | `targets` 非空但无任何 `matchable` 条目 | 轴数 |
| `still_empty` | `targets` 为空 | 轴数 |
| （交叉）`disclosure_blocked` | v0.3 addendum 对该轴带 `request_scoped_collection_no_runtime_record_identity` | 轴数（可与其他类重叠） |

`stale_source` 用**记录身份解析率**衡量（`stale_record_identity_resolved` 轴数 / `stale_no_positive_refs` / `stale_positive_ref_not_record_level`），因为 `targets` 不在其消费路径上。

`safety` / `cross_user` 本单零改动，仅记录「本单不投影」。

各项实测数字只在公开聚合 `annotation-aggregate-v2.json` 与报告 `annotation-report-v2.md` 中出现（聚合内的 `projection.coverage` 与公开 `coverage` 同源同值，可交叉核对）。

## 11. 校验算法（消费者与复核方逐步执行）

1. 读密文原始字节，重算 SHA256，必须等于公开聚合 `private_ciphertext.sha256` → 否则 `contract_ciphertext_sha_mismatch`。
2. 只用受控 loader 解密（既有 H2 custody key 容器；明文只在进程内存）→ 失败 `contract_decrypt_failed`。
3. 严格 JSON：拒绝重复键、非对象顶层、非 UTF-8；拒绝未知/缺失键。
4. 校验 §3 结构（6 键 / 17 键 / 4 项 / 30 项 / 5 键 / 7 字段 / 3 键）。
5. 重算 v1 的 16 个 binding 与 `contract_schema_sha256`；校验 lineage 中 v1 密文/schema/聚合/报告 4 个 SHA256。
6. 重新解密 v1 密文，执行 §9 的 1–7 条不变量逐条比对。
7. 用公开语料索引重算 `projection.record_identities`（§5），逐条比对 `code` / `record_key` / `record_code` / `sheet` / `row` / `base_doc_code`。
8. 用 §4/§6 重算每条新 target 与每条 `target_provenance`（含 §6.4 的唯一补全），逐条比对。
9. 用 §7 重算 `shared_background_corpus` 各条（含 `scenario_active_version` 与 `unit_identity_code`）。
10. 校验 `projection.coverage` 与公开聚合 `coverage` 逐值相等。
11. 任一步失败以固定码拒绝，不降级、不“尽力消费”。

固定错误码沿用 v1（`contract_ciphertext_missing` / `contract_ciphertext_sha_mismatch` / `contract_decrypt_failed` / `contract_schema_invalid` / `contract_binding_mismatch` / `contract_coverage_invalid` / `contract_axis_invalid` / `contract_basis_invalid` / `contract_semantics_changed` / `contract_unknown_downgraded`），另加 `contract_schema_binding_mismatch`、`contract_projection_mismatch`、`contract_target_unprojectable`。

## 12. 消费方式

### 12.1 v1 消费者必须显式拒绝 v2

`p2_evidence_rescore_axes.py`（Q1a-1b）的 `Q1A2_CONTRACT_SCHEMA_VERSION` 与顶层键集校验都是 v1 常量：v2 会被它以 `contract_schema_invalid` 拒绝。这是**预期行为**，不得为了“能跑”去改 Q1a-1b 的常量，也不得把 v2 改名冒充 v1。

### 12.2 Q1a-1b / Q1a-3 适配层（C1-P4）必须做的最小改动

1. 接受 `schema_version == "q1a-scope-targets-contract/v2"`，并允许第 6 个顶层键 `projection`（其余 5 键结构不变，因此 inner validators 不用改）。
2. `targets` 直接按 §3.4 消费；`matchable` 判定必须有，否则会把 `document` / `record_collection` 型 target 当成“永不匹配”的证据。
3. `shared_background` 仍为空 → 该 mode 的轴只能 `unknown`，不得因为合同带了 `shared_background_corpus` 就判通过。
4. `basis` / `source` 只进 provenance 报告，不参与 verdict 折叠。

### 12.3 不得由本合同授权的判定（本轮不改判据）

- **不得**把 v2 的 `targets` 当作“产品应当用了哪些记录”的充分证据：它只是**请求范围的记录集合身份**，不是运行期实际使用集。
- **不得**把 `shared_background_corpus` 的语料单元身份当运行期 `document_id` / `version_id`。
- **不得**新增“未投影文档单元 = 通过/不通过”的规则。已知机制：产品对非表格文档的文本块会给 `entity_type="document"` / `entity_key="document|<uuid>"`（`chunking.py`），而 `document` 身份不可投影（§4.4）。若某 `entity_bound` 轴在运行期实际使用了这类单元，冻结分类器会给出 `other_entity_used` / `citation_entity_mismatch`。**这是转换风险，不是 v2 的结论**：是否把“文档级单元未投影”降级为 `unknown` 属于分类语义变更，必须由经理另行批准并单独验收（C1-P4），不得在本合同里默认生效。

### 12.4 与 Q1a-3 的关系

- 分析身份仍为 `Q1A-RESCORE-20261114-r1` 的下一次读数，必须把 **v2 密文 SHA256 + v2 schema SHA256** 绑进身份；v1 密文与 schema 同时保留为 lineage。
- `basis` / `code` 只能作为分诊来源记录，不得作为产品行为正确/错误的证据。

## 13. 版本与边界

- 版本固定 `q1a-scope-targets-contract/v2`；任何新版本必须新文件、新版本号、新密文，不覆盖 v1 与本 v2。
- 规则源（`chunking.py` / `tokenize.py`）SHA256 变化即视为**投影规则变更**：旧 v2 合同对新规则不再成立，须出新版本（`entity_projection_rule_changed`）。产品若改实体投影分支，同样触发。
- 本合同只补语义归属与可消费结构，不产生 `verified` / `threshold_met` / `release_ready`，不进入 T208/T209/T900，不证明真实产品通过。
- 任何 schema/绑定/覆盖/复核不一致即阻断；失败如实记 NOT-RUN/BLOCKED，不猜、不冒充。

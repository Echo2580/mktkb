# 运行期身份快照采集契约 v0.3（`p2-hard-evidence-capture-identity/v0.3`）

- 状态：C1-P3 新交付，**待独立验收 / 经理限定接收**；未冻结、未质量放行。
- 载荷 schema：`p2-runtime-identity-snapshot/v0.1`；清单 schema：`p2-runtime-identity-snapshot-manifest/v0.1`。
- 实现：`backend/src/mktkb/evaluation/p2_evidence_snapshot_v03.py`（新模块）。
- 本契约**不修改**任何冻结件：`p2_evidence_capture.py`（`601096bc…`）、`p2_evidence_io.py`（`1c16a3da…`）、`p2_hard_evidence.py`（`fba6e606…`）等 C 冻结 12 对象保持字节不变；只**只读调用**冻结模块的公开函数与公开常量。
- 本契约不产生四轴 verdict、不读真实 H2、不调用产品/模型/embedding/rerank/OCR/裁判/检索/鉴权/余额；合成验证零出站。

> **命名消歧（必须读）**：本包文档名 `p2-hard-evidence-capture-v0_3.md` 是 C1-P3 的**交付代号**；它描述的契约版本是 `p2-hard-evidence-capture-identity/v0.3`。既有 `docs/evaluation/p2-hard-evidence-capture-v0_2.md` 里已冻结的 `p2-hard-evidence-capture/v0.3`（回合 envelope）是**另一个对象**，键集与读写分发由冻结模块维护，本契约不改它、不向其中添加字段。

## 1. 解决什么、不解决什么

Q1a 复评给出 29/30 不可判，直接缺口是“没有运行期身份与版本快照”。本契约把以下四类运行期事实变成**可采集、可加密落盘、可严格读回、可逐字段校验**的版本化对象：

| # | 事实 | 快照块 | 回答的问题 |
|---|---|---|---|
| 1 | 请求 owner 身份 | `request_owner` | 这一回合由哪个认证后的用户/会话发起？**不采**密码 hash / session token / HTTP 认证头。 |
| 2 | 实体/记录身份 | `record_identities` + `record_identity_summary` | 实际使用的 unit 属于哪条语料记录？`record_code` 与合同 v2 §5 的 R-RC-1..5 同构。 |
| 3 | 实际生效日期与版本 | `effective_temporal` | 产品**实际**用了哪个 `as_of` / business date / 文档版本？不是“应该用的”。 |
| 4 | 空使用集证明输入 | `empty_use_scope_input` | 按事件协议逐层声明“已使用层/候选层”，供 C1-P2 实现消费；不依赖冻结原语私有结构。 |

**不做**：不产 verdict、不判 cross_entity/stale_source 通过与否、不把 `unknown` 改 N/A、不反推目标、不用运行期结果回填语义、不写旧卡/账本/GO/阈值。

## 2. 权威来源与采集点

快照是**当次回合结束时**对已发布证据的派生切片，不是事后重建。构造输入固定为**冻结 v0.3 回合 envelope 的落盘密文读回对象**（`p2-hard-evidence-capture/v0.3` 或 `…/v0.3-live`，无 `sealed`）。

| 快照块 | 唯一权威来源（只读） | 采集点/时点 |
|---|---|---|
| `source_evidence` | 该回合 envelope 的规范 JSON 字节 | 读回后立即计算 `sha256`，绑定到快照 |
| `binding` | envelope `bindings`（16 键，含 `fixture_kind`）+ `run_binding`（live 9 键） | 以**落盘 envelope 的 bindings 为准**（冻结会话 `bind()` 会把适配器实际 `dataset_version/pipeline_version/index_revision` 合并进去） |
| `turn_ref` | envelope `turn` + `runtime_snapshot.product_response.kind` | 同一回合 |
| `request_owner` | `turn.authenticated_user_id` / `turn.conversation_id`（产品会话已认证主体；不是凭证） | 同一回合 |
| `record_identities` | `capture.events` 的使用层 + `db_projection.units`（`kind/locator/document_name/version_number/entity_*`）+ 调用方给出的**公开**投影索引（`doc_code_index` / `record_index` / `doc_code_aliases`） | 同一回合 |
| `effective_temporal` | `plan_observed.as_of`（唯一且仅当一条）→ 回退 `db_projection.rag_business_date`；`db_projection.units.version_number`；`runtime_snapshot.product_response.sources[].version_number` | 同一回合 |
| `empty_use_scope_input` | `capture.events` 的固定事件协议（`model_input/model_output/direct_rag_answer/answer_result/commit_observed/entity_inheritance/retrieval_observed/query_state_*`）+ `db_projection.message_sources/query_states` | 同一回合 |
| `runtime_identity` | 上述使用层 ref 与 `db_projection.units` 的 `document_id/version_id/unit_id` | 同一回合 |

**禁止**：用 DB 事后“当前版本”回填来源版本；用产品回答/分数反推 owner、实体或日期；用 `runtime_snapshot.retrieval_use` 的合并层代替事件协议（那会把 `answer_result` 与 `commit_observed` 混成一层，P2 的分层语义丢失）。

### 2.1 使用层与候选层（与 C1-P2 同义）

`empty_use_scope_input.use_layers` 恰 9 层（id 层 8 + fact count 1），语义与 C1-P2 `_usage_layers` 一致：

| 快照层键 | 事件来源 | 快照字段 |
|---|---|---|
| `model_evidence` | `model_input.evidence[].source_id` | `observed/count/refs` |
| `model_output_sources` | `model_output.source_ids` | 同上 |
| `direct_rag_facts` | `direct_rag_answer.facts[].source_unit_id` | 同上 |
| `direct_rag_citations` | `direct_rag_answer.cited_unit_ids` | 同上 |
| `direct_rag_fact_count` | `direct_rag_answer.fact_count` | `count` = fact 数，`refs` 恒空 |
| `answer_result_sources` | `answer_result.source_ids` | `observed/count/refs` |
| `commit_observed_sources` | `commit_observed.source_ids` | 同上 |
| `entity_inheritance` | `entity_inheritance.source_unit_id` | 同上 |
| `projection_message_sources` | `db_projection.message_sources[].source_id` | 同上 |

`candidate_layers` 恰 3 层（`retrieval_observed` / `query_state_candidates` / `projection_query_state_candidates`），**不是**已使用来源；两层分开正是为了不把“检索有结果但未使用”误判成使用。

`empty_set_candidate=true` 是**输入侧充分条件**：9 个使用层全部 `observed=true` 且计数全 0。它为 false **不**等于“有使用”（可能只是该分支没有发出那类事件）；消费方必须读逐层 `observed/count` 与 `plan`，不得把 false 当非空证据。同理，`all_use_layers_observed` 是严格标记，不是结论。

### 2.2 实际生效日期/版本（“不是应该用的”）

- `as_of` 只取**运行期实际值**：唯一 `plan_observed.as_of`；若为 null，按冻结分类器同一顺序回退 `db_projection.rag_business_date`，并用 `as_of_source` 标记来源。多义（多条 `plan_observed`）→ `availability=not_observed` + `effective_as_of_ambiguous`，不猜。
- `declared_baseline_business_date` 只来自 live `run_binding.business_date`（用例声明的 baseline），单独存放；`baseline_used_as_effective` **恒为 false**，校验器强制。local_mock 没有 run binding，该字段为 null。
- `document_versions[]` 同时保存 `runtime_version_number`（DB 投影实际版本）与 `product_version_number`（产品响应同 source 的版本）；两者不等 → `version_mismatch`。**不**把语料 `business_version`（如 `V2`，语料标注）与运行期版本号做数值等价断言：二者语义不同，合同只并列记录，不强行等同。

## 3. 载荷 schema（骨架）

```json
{
  "contract_version": "p2-hard-evidence-capture-identity/v0.3",
  "schema_version": "p2-runtime-identity-snapshot/v0.1",
  "fixture_kind": "local_mock | live_h2",
  "captured_utc": "ISO-8601（带时区）",
  "source_evidence": {"sha256": "…", "schema_version": "p2-hard-evidence-capture/v0.3", "fixture_kind": "…", "completeness_status": "complete|incomplete|replayed"},
  "binding": {"run_id": "…", "plan_sha256": "…", "scenario_id": "…", "fixture_kind": "…", "bindings_sha256": "…", "run_binding_sha256": null, "business_date_declared": null},
  "turn_ref": {"turn_index": 0, "client_request_id": "…", "conversation_id": "…", "question_sha256": "…", "pre_revision": null, "post_revision": null, "capture_revision": null, "response_kind": "answer", "http_status": 200, "timed_out": false},
  "request_owner": {"availability": "observed", "reason": null, "user_ref": "…", "conversation_ref": "…", "owner_source": "turn_authenticated_user_id", "auth_material_collected": false},
  "record_identities": [{"source_ref": "…", "layers": ["model_evidence"], "unit_kind": "table_row", "locator_kind": "record", "doc_code": "D01", "base_doc_code": "D01", "sheet": "物品位置", "row": 8, "record_key": "P01", "record_code": "P01", "business_version": "V2", "version_number": 1, "record_level": true, "entity_type": "item", "entity_key": "item|id:p01", "entity_filters": {"item": "…", "item_id": "P01", "store": "…"}, "entity_matchable": true, "code": "record_row_reverse_lookup", "entity_code": "entity_identity_matchable_nonrole_filters"}],
  "record_identity_summary": {"total": 0, "record_level": 0, "not_record_level": 0, "doc_code_unresolved": 0, "entity_matchable": 0, "entity_document_level": 0, "unresolved_units": 0, "doc_codes": []},
  "effective_temporal": {"availability": "observed", "reason": null, "as_of": "YYYY-MM-DD", "as_of_source": "plan_observed|rag_business_date|unavailable", "observed_from": "db_projection_units", "include_future": false, "enumerate": false, "document_versions": [{"source_ref": "…", "doc_code": "D01", "version_label": "V2", "runtime_version_number": 1, "product_version_number": 1, "code": "version_observed"}], "declared_baseline_business_date": null, "baseline_used_as_effective": false, "code": "effective_temporal_observed"},
  "empty_use_scope_input": {"input_version": "c1p2-empty-use-scope-input/v0.1", "turn_status": "complete", "reason": null, "plan": {"availability": true, "path": "rag", "mode": "…", "as_of": "YYYY-MM-DD", "include_future": false, "clarification": false}, "use_layers": {"…": {"observed": true, "count": 0, "refs": []}}, "candidate_layers": {"…": {"observed": true, "count": 0, "refs": [], "truncated": false}}, "all_use_layers_observed": false, "empty_set_candidate": false, "code": "empty_use_input_nonempty"},
  "runtime_identity": {"declared": true, "unit_ids": [], "unresolved_unit_ids": [], "document_ids": [], "version_ids": [], "counts": {"units": 0, "unresolved": 0, "documents": 0, "versions": 0}},
  "public_boundary": {"public_summary_sha256": "…", "public_summary_keys": ["… 25 键 …"], "runtime_ids_only_in_declared_blocks": true},
  "content_sha256": "…"
}
```

顶层键**恰 15 个**；每一层都执行**严格键集**：未知键 → `snapshot_unknown_field:<path>`；未声明的运行期 id 键 → `snapshot_runtime_id_not_declared:<path>`；凭证/认证材料键 → `snapshot_forbidden_field:<path>`；形似明文凭证的值 → `snapshot_plaintext_secret_rejected:<path>`。运行期 id（unit/document/version）**只允许**出现在已声明承载块：`record_identities[].source_ref`、`effective_temporal.document_versions[].source_ref`、`empty_use_scope_input` 各层 `refs`、`runtime_identity.*`。公开摘要不含任何 id/日期/hash/文本。

## 4. 字段表（167 条字段规格）

字段表由实现内的声明式 schema **机器生成**（`identity_field_table()`），下表与代码同源；`必填=是` 表示该键必须存在，`可空=是` 表示值允许 `null`（缺失与 `null` 的固定码不同：`snapshot_missing_field` vs `snapshot_null_not_allowed`）。合计：**167 条，必填 167，可空 35**。

### 4.1 `contract_version`

| 字段路径 | 类型 | 必填 | 可空 | 缺失固定码 |
|---|---|---|---|---|
| `contract_version` | str | 是 | 否 | `snapshot_missing_field:contract_version` |

### 4.2 `schema_version`

| 字段路径 | 类型 | 必填 | 可空 | 缺失固定码 |
|---|---|---|---|---|
| `schema_version` | str | 是 | 否 | `snapshot_missing_field:schema_version` |

### 4.3 `fixture_kind`

| 字段路径 | 类型 | 必填 | 可空 | 缺失固定码 |
|---|---|---|---|---|
| `fixture_kind` | enum(local_mock|live_h2) | 是 | 否 | `snapshot_missing_field:fixture_kind` |

### 4.4 `captured_utc`

| 字段路径 | 类型 | 必填 | 可空 | 缺失固定码 |
|---|---|---|---|---|
| `captured_utc` | iso_datetime | 是 | 否 | `snapshot_missing_field:captured_utc` |

### 4.5 `source_evidence`

| 字段路径 | 类型 | 必填 | 可空 | 缺失固定码 |
|---|---|---|---|---|
| `source_evidence` | object | 是 | 否 | `snapshot_missing_field:source_evidence` |
| `source_evidence.sha256` | sha256 | 是 | 否 | `snapshot_missing_field:source_evidence.sha256` |
| `source_evidence.schema_version` | str | 是 | 否 | `snapshot_missing_field:source_evidence.schema_version` |
| `source_evidence.fixture_kind` | enum(local_mock|live_h2) | 是 | 否 | `snapshot_missing_field:source_evidence.fixture_kind` |
| `source_evidence.completeness_status` | enum(complete|incomplete|replayed) | 是 | 否 | `snapshot_missing_field:source_evidence.completeness_status` |

### 4.6 `binding`

| 字段路径 | 类型 | 必填 | 可空 | 缺失固定码 |
|---|---|---|---|---|
| `binding` | object | 是 | 否 | `snapshot_missing_field:binding` |
| `binding.run_id` | str | 是 | 否 | `snapshot_missing_field:binding.run_id` |
| `binding.plan_sha256` | str | 是 | 否 | `snapshot_missing_field:binding.plan_sha256` |
| `binding.scenario_id` | str | 是 | 否 | `snapshot_missing_field:binding.scenario_id` |
| `binding.fixture_kind` | enum(local_mock|live_h2) | 是 | 否 | `snapshot_missing_field:binding.fixture_kind` |
| `binding.bindings_sha256` | sha256 | 是 | 否 | `snapshot_missing_field:binding.bindings_sha256` |
| `binding.run_binding_sha256` | sha256 | 是 | 是 | `snapshot_missing_field:binding.run_binding_sha256` |
| `binding.business_date_declared` | iso_date | 是 | 是 | `snapshot_missing_field:binding.business_date_declared` |

### 4.7 `turn_ref`

| 字段路径 | 类型 | 必填 | 可空 | 缺失固定码 |
|---|---|---|---|---|
| `turn_ref` | object | 是 | 否 | `snapshot_missing_field:turn_ref` |
| `turn_ref.turn_index` | int | 是 | 否 | `snapshot_missing_field:turn_ref.turn_index` |
| `turn_ref.client_request_id` | str | 是 | 否 | `snapshot_missing_field:turn_ref.client_request_id` |
| `turn_ref.conversation_id` | str | 是 | 否 | `snapshot_missing_field:turn_ref.conversation_id` |
| `turn_ref.question_sha256` | sha256 | 是 | 否 | `snapshot_missing_field:turn_ref.question_sha256` |
| `turn_ref.pre_revision` | int | 是 | 是 | `snapshot_missing_field:turn_ref.pre_revision` |
| `turn_ref.post_revision` | int | 是 | 是 | `snapshot_missing_field:turn_ref.post_revision` |
| `turn_ref.capture_revision` | int | 是 | 是 | `snapshot_missing_field:turn_ref.capture_revision` |
| `turn_ref.response_kind` | str | 是 | 是 | `snapshot_missing_field:turn_ref.response_kind` |
| `turn_ref.http_status` | int | 是 | 是 | `snapshot_missing_field:turn_ref.http_status` |
| `turn_ref.timed_out` | bool | 是 | 否 | `snapshot_missing_field:turn_ref.timed_out` |

### 4.8 `request_owner`

| 字段路径 | 类型 | 必填 | 可空 | 缺失固定码 |
|---|---|---|---|---|
| `request_owner` | object | 是 | 否 | `snapshot_missing_field:request_owner` |
| `request_owner.availability` | enum(observed|unavailable) | 是 | 否 | `snapshot_missing_field:request_owner.availability` |
| `request_owner.reason` | str | 是 | 是 | `snapshot_missing_field:request_owner.reason` |
| `request_owner.user_ref` | str | 是 | 是 | `snapshot_missing_field:request_owner.user_ref` |
| `request_owner.conversation_ref` | str | 是 | 是 | `snapshot_missing_field:request_owner.conversation_ref` |
| `request_owner.owner_source` | enum(turn_authenticated_user_id|unavailable) | 是 | 否 | `snapshot_missing_field:request_owner.owner_source` |
| `request_owner.auth_material_collected` | bool | 是 | 否 | `snapshot_missing_field:request_owner.auth_material_collected` |

### 4.9 `record_identities`

| 字段路径 | 类型 | 必填 | 可空 | 缺失固定码 |
|---|---|---|---|---|
| `record_identities` | list | 是 | 否 | `snapshot_missing_field:record_identities` |
| `record_identities[]` | object | 是 | 否 | `snapshot_missing_field:record_identities[]` |
| `record_identities[].source_ref` | str | 是 | 否 | `snapshot_missing_field:record_identities[].source_ref` |
| `record_identities[].layers` | list | 是 | 否 | `snapshot_missing_field:record_identities[].layers` |
| `record_identities[].unit_kind` | str | 是 | 否 | `snapshot_missing_field:record_identities[].unit_kind` |
| `record_identities[].locator_kind` | enum(record|page|heading|other|none|unavailable) | 是 | 否 | `snapshot_missing_field:record_identities[].locator_kind` |
| `record_identities[].doc_code` | str | 是 | 是 | `snapshot_missing_field:record_identities[].doc_code` |
| `record_identities[].base_doc_code` | str | 是 | 是 | `snapshot_missing_field:record_identities[].base_doc_code` |
| `record_identities[].sheet` | str | 是 | 是 | `snapshot_missing_field:record_identities[].sheet` |
| `record_identities[].row` | int | 是 | 是 | `snapshot_missing_field:record_identities[].row` |
| `record_identities[].record_key` | str | 是 | 是 | `snapshot_missing_field:record_identities[].record_key` |
| `record_identities[].record_code` | str | 是 | 是 | `snapshot_missing_field:record_identities[].record_code` |
| `record_identities[].business_version` | str | 是 | 是 | `snapshot_missing_field:record_identities[].business_version` |
| `record_identities[].version_number` | int | 是 | 是 | `snapshot_missing_field:record_identities[].version_number` |
| `record_identities[].record_level` | bool | 是 | 否 | `snapshot_missing_field:record_identities[].record_level` |
| `record_identities[].entity_type` | str | 是 | 是 | `snapshot_missing_field:record_identities[].entity_type` |
| `record_identities[].entity_key` | str | 是 | 是 | `snapshot_missing_field:record_identities[].entity_key` |
| `record_identities[].entity_filters` | map[str,str] | 是 | 否 | `snapshot_missing_field:record_identities[].entity_filters` |
| `record_identities[].entity_matchable` | bool | 是 | 否 | `snapshot_missing_field:record_identities[].entity_matchable` |
| `record_identities[].code` | enum(record_row_reverse_lookup|record_row_not_in_record_index|runtime_unit_not_record_level|runtime_doc_code_unresolved|runtime_unit_unresolved) | 是 | 否 | `snapshot_missing_field:record_identities[].code` |
| `record_identities[].entity_code` | enum(entity_identity_matchable|entity_identity_matchable_nonrole_filters|entity_identity_nonmatchable|entity_identity_document_level|entity_identity_absent|entity_identity_unavailable) | 是 | 否 | `snapshot_missing_field:record_identities[].entity_code` |

### 4.10 `record_identity_summary`

| 字段路径 | 类型 | 必填 | 可空 | 缺失固定码 |
|---|---|---|---|---|
| `record_identity_summary` | object | 是 | 否 | `snapshot_missing_field:record_identity_summary` |
| `record_identity_summary.total` | int | 是 | 否 | `snapshot_missing_field:record_identity_summary.total` |
| `record_identity_summary.record_level` | int | 是 | 否 | `snapshot_missing_field:record_identity_summary.record_level` |
| `record_identity_summary.not_record_level` | int | 是 | 否 | `snapshot_missing_field:record_identity_summary.not_record_level` |
| `record_identity_summary.doc_code_unresolved` | int | 是 | 否 | `snapshot_missing_field:record_identity_summary.doc_code_unresolved` |
| `record_identity_summary.entity_matchable` | int | 是 | 否 | `snapshot_missing_field:record_identity_summary.entity_matchable` |
| `record_identity_summary.entity_document_level` | int | 是 | 否 | `snapshot_missing_field:record_identity_summary.entity_document_level` |
| `record_identity_summary.unresolved_units` | int | 是 | 否 | `snapshot_missing_field:record_identity_summary.unresolved_units` |
| `record_identity_summary.doc_codes` | list | 是 | 否 | `snapshot_missing_field:record_identity_summary.doc_codes` |

### 4.11 `effective_temporal`

| 字段路径 | 类型 | 必填 | 可空 | 缺失固定码 |
|---|---|---|---|---|
| `effective_temporal` | object | 是 | 否 | `snapshot_missing_field:effective_temporal` |
| `effective_temporal.availability` | enum(observed|partial|not_observed) | 是 | 否 | `snapshot_missing_field:effective_temporal.availability` |
| `effective_temporal.reason` | str | 是 | 是 | `snapshot_missing_field:effective_temporal.reason` |
| `effective_temporal.as_of` | iso_date | 是 | 是 | `snapshot_missing_field:effective_temporal.as_of` |
| `effective_temporal.as_of_source` | enum(plan_observed|rag_business_date|unavailable) | 是 | 否 | `snapshot_missing_field:effective_temporal.as_of_source` |
| `effective_temporal.observed_from` | enum(db_projection_units|unavailable) | 是 | 否 | `snapshot_missing_field:effective_temporal.observed_from` |
| `effective_temporal.include_future` | bool | 是 | 是 | `snapshot_missing_field:effective_temporal.include_future` |
| `effective_temporal.enumerate` | bool | 是 | 是 | `snapshot_missing_field:effective_temporal.enumerate` |
| `effective_temporal.document_versions` | list | 是 | 否 | `snapshot_missing_field:effective_temporal.document_versions` |
| `effective_temporal.document_versions[]` | object | 是 | 否 | `snapshot_missing_field:effective_temporal.document_versions[]` |
| `effective_temporal.document_versions[].source_ref` | str | 是 | 否 | `snapshot_missing_field:effective_temporal.document_versions[].source_ref` |
| `effective_temporal.document_versions[].doc_code` | str | 是 | 是 | `snapshot_missing_field:effective_temporal.document_versions[].doc_code` |
| `effective_temporal.document_versions[].version_label` | str | 是 | 是 | `snapshot_missing_field:effective_temporal.document_versions[].version_label` |
| `effective_temporal.document_versions[].runtime_version_number` | int | 是 | 是 | `snapshot_missing_field:effective_temporal.document_versions[].runtime_version_number` |
| `effective_temporal.document_versions[].product_version_number` | int | 是 | 是 | `snapshot_missing_field:effective_temporal.document_versions[].product_version_number` |
| `effective_temporal.document_versions[].code` | enum(version_observed|version_mismatch|version_unresolved) | 是 | 否 | `snapshot_missing_field:effective_temporal.document_versions[].code` |
| `effective_temporal.declared_baseline_business_date` | iso_date | 是 | 是 | `snapshot_missing_field:effective_temporal.declared_baseline_business_date` |
| `effective_temporal.baseline_used_as_effective` | bool | 是 | 否 | `snapshot_missing_field:effective_temporal.baseline_used_as_effective` |
| `effective_temporal.code` | enum(effective_temporal_observed|effective_temporal_partial|effective_temporal_not_observed|effective_as_of_not_observed|effective_as_of_ambiguous) | 是 | 否 | `snapshot_missing_field:effective_temporal.code` |

### 4.12 `empty_use_scope_input`

| 字段路径 | 类型 | 必填 | 可空 | 缺失固定码 |
|---|---|---|---|---|
| `empty_use_scope_input` | object | 是 | 否 | `snapshot_missing_field:empty_use_scope_input` |
| `empty_use_scope_input.input_version` | enum(c1p2-empty-use-scope-input/v0.1) | 是 | 否 | `snapshot_missing_field:empty_use_scope_input.input_version` |
| `empty_use_scope_input.turn_status` | enum(complete|partial|unavailable) | 是 | 否 | `snapshot_missing_field:empty_use_scope_input.turn_status` |
| `empty_use_scope_input.reason` | str | 是 | 是 | `snapshot_missing_field:empty_use_scope_input.reason` |
| `empty_use_scope_input.plan` | object | 是 | 否 | `snapshot_missing_field:empty_use_scope_input.plan` |
| `empty_use_scope_input.plan.availability` | bool | 是 | 否 | `snapshot_missing_field:empty_use_scope_input.plan.availability` |
| `empty_use_scope_input.plan.path` | str | 是 | 是 | `snapshot_missing_field:empty_use_scope_input.plan.path` |
| `empty_use_scope_input.plan.mode` | str | 是 | 是 | `snapshot_missing_field:empty_use_scope_input.plan.mode` |
| `empty_use_scope_input.plan.as_of` | iso_date | 是 | 是 | `snapshot_missing_field:empty_use_scope_input.plan.as_of` |
| `empty_use_scope_input.plan.include_future` | bool | 是 | 是 | `snapshot_missing_field:empty_use_scope_input.plan.include_future` |
| `empty_use_scope_input.plan.clarification` | bool | 是 | 是 | `snapshot_missing_field:empty_use_scope_input.plan.clarification` |
| `empty_use_scope_input.use_layers` | object | 是 | 否 | `snapshot_missing_field:empty_use_scope_input.use_layers` |
| `empty_use_scope_input.use_layers.model_evidence` | object | 是 | 否 | `snapshot_missing_field:empty_use_scope_input.use_layers.model_evidence` |
| `empty_use_scope_input.use_layers.model_evidence.observed` | bool | 是 | 否 | `snapshot_missing_field:empty_use_scope_input.use_layers.model_evidence.observed` |
| `empty_use_scope_input.use_layers.model_evidence.count` | int | 是 | 否 | `snapshot_missing_field:empty_use_scope_input.use_layers.model_evidence.count` |
| `empty_use_scope_input.use_layers.model_evidence.refs` | list | 是 | 否 | `snapshot_missing_field:empty_use_scope_input.use_layers.model_evidence.refs` |
| `empty_use_scope_input.use_layers.model_output_sources` | object | 是 | 否 | `snapshot_missing_field:empty_use_scope_input.use_layers.model_output_sources` |
| `empty_use_scope_input.use_layers.model_output_sources.observed` | bool | 是 | 否 | `snapshot_missing_field:empty_use_scope_input.use_layers.model_output_sources.observed` |
| `empty_use_scope_input.use_layers.model_output_sources.count` | int | 是 | 否 | `snapshot_missing_field:empty_use_scope_input.use_layers.model_output_sources.count` |
| `empty_use_scope_input.use_layers.model_output_sources.refs` | list | 是 | 否 | `snapshot_missing_field:empty_use_scope_input.use_layers.model_output_sources.refs` |
| `empty_use_scope_input.use_layers.direct_rag_facts` | object | 是 | 否 | `snapshot_missing_field:empty_use_scope_input.use_layers.direct_rag_facts` |
| `empty_use_scope_input.use_layers.direct_rag_facts.observed` | bool | 是 | 否 | `snapshot_missing_field:empty_use_scope_input.use_layers.direct_rag_facts.observed` |
| `empty_use_scope_input.use_layers.direct_rag_facts.count` | int | 是 | 否 | `snapshot_missing_field:empty_use_scope_input.use_layers.direct_rag_facts.count` |
| `empty_use_scope_input.use_layers.direct_rag_facts.refs` | list | 是 | 否 | `snapshot_missing_field:empty_use_scope_input.use_layers.direct_rag_facts.refs` |
| `empty_use_scope_input.use_layers.direct_rag_citations` | object | 是 | 否 | `snapshot_missing_field:empty_use_scope_input.use_layers.direct_rag_citations` |
| `empty_use_scope_input.use_layers.direct_rag_citations.observed` | bool | 是 | 否 | `snapshot_missing_field:empty_use_scope_input.use_layers.direct_rag_citations.observed` |
| `empty_use_scope_input.use_layers.direct_rag_citations.count` | int | 是 | 否 | `snapshot_missing_field:empty_use_scope_input.use_layers.direct_rag_citations.count` |
| `empty_use_scope_input.use_layers.direct_rag_citations.refs` | list | 是 | 否 | `snapshot_missing_field:empty_use_scope_input.use_layers.direct_rag_citations.refs` |
| `empty_use_scope_input.use_layers.direct_rag_fact_count` | object | 是 | 否 | `snapshot_missing_field:empty_use_scope_input.use_layers.direct_rag_fact_count` |
| `empty_use_scope_input.use_layers.direct_rag_fact_count.observed` | bool | 是 | 否 | `snapshot_missing_field:empty_use_scope_input.use_layers.direct_rag_fact_count.observed` |
| `empty_use_scope_input.use_layers.direct_rag_fact_count.count` | int | 是 | 否 | `snapshot_missing_field:empty_use_scope_input.use_layers.direct_rag_fact_count.count` |
| `empty_use_scope_input.use_layers.direct_rag_fact_count.refs` | list | 是 | 否 | `snapshot_missing_field:empty_use_scope_input.use_layers.direct_rag_fact_count.refs` |
| `empty_use_scope_input.use_layers.answer_result_sources` | object | 是 | 否 | `snapshot_missing_field:empty_use_scope_input.use_layers.answer_result_sources` |
| `empty_use_scope_input.use_layers.answer_result_sources.observed` | bool | 是 | 否 | `snapshot_missing_field:empty_use_scope_input.use_layers.answer_result_sources.observed` |
| `empty_use_scope_input.use_layers.answer_result_sources.count` | int | 是 | 否 | `snapshot_missing_field:empty_use_scope_input.use_layers.answer_result_sources.count` |
| `empty_use_scope_input.use_layers.answer_result_sources.refs` | list | 是 | 否 | `snapshot_missing_field:empty_use_scope_input.use_layers.answer_result_sources.refs` |
| `empty_use_scope_input.use_layers.commit_observed_sources` | object | 是 | 否 | `snapshot_missing_field:empty_use_scope_input.use_layers.commit_observed_sources` |
| `empty_use_scope_input.use_layers.commit_observed_sources.observed` | bool | 是 | 否 | `snapshot_missing_field:empty_use_scope_input.use_layers.commit_observed_sources.observed` |
| `empty_use_scope_input.use_layers.commit_observed_sources.count` | int | 是 | 否 | `snapshot_missing_field:empty_use_scope_input.use_layers.commit_observed_sources.count` |
| `empty_use_scope_input.use_layers.commit_observed_sources.refs` | list | 是 | 否 | `snapshot_missing_field:empty_use_scope_input.use_layers.commit_observed_sources.refs` |
| `empty_use_scope_input.use_layers.entity_inheritance` | object | 是 | 否 | `snapshot_missing_field:empty_use_scope_input.use_layers.entity_inheritance` |
| `empty_use_scope_input.use_layers.entity_inheritance.observed` | bool | 是 | 否 | `snapshot_missing_field:empty_use_scope_input.use_layers.entity_inheritance.observed` |
| `empty_use_scope_input.use_layers.entity_inheritance.count` | int | 是 | 否 | `snapshot_missing_field:empty_use_scope_input.use_layers.entity_inheritance.count` |
| `empty_use_scope_input.use_layers.entity_inheritance.refs` | list | 是 | 否 | `snapshot_missing_field:empty_use_scope_input.use_layers.entity_inheritance.refs` |
| `empty_use_scope_input.use_layers.projection_message_sources` | object | 是 | 否 | `snapshot_missing_field:empty_use_scope_input.use_layers.projection_message_sources` |
| `empty_use_scope_input.use_layers.projection_message_sources.observed` | bool | 是 | 否 | `snapshot_missing_field:empty_use_scope_input.use_layers.projection_message_sources.observed` |
| `empty_use_scope_input.use_layers.projection_message_sources.count` | int | 是 | 否 | `snapshot_missing_field:empty_use_scope_input.use_layers.projection_message_sources.count` |
| `empty_use_scope_input.use_layers.projection_message_sources.refs` | list | 是 | 否 | `snapshot_missing_field:empty_use_scope_input.use_layers.projection_message_sources.refs` |
| `empty_use_scope_input.candidate_layers` | object | 是 | 否 | `snapshot_missing_field:empty_use_scope_input.candidate_layers` |
| `empty_use_scope_input.candidate_layers.retrieval_observed` | object | 是 | 否 | `snapshot_missing_field:empty_use_scope_input.candidate_layers.retrieval_observed` |
| `empty_use_scope_input.candidate_layers.retrieval_observed.observed` | bool | 是 | 否 | `snapshot_missing_field:empty_use_scope_input.candidate_layers.retrieval_observed.observed` |
| `empty_use_scope_input.candidate_layers.retrieval_observed.count` | int | 是 | 否 | `snapshot_missing_field:empty_use_scope_input.candidate_layers.retrieval_observed.count` |
| `empty_use_scope_input.candidate_layers.retrieval_observed.refs` | list | 是 | 否 | `snapshot_missing_field:empty_use_scope_input.candidate_layers.retrieval_observed.refs` |
| `empty_use_scope_input.candidate_layers.retrieval_observed.truncated` | bool | 是 | 否 | `snapshot_missing_field:empty_use_scope_input.candidate_layers.retrieval_observed.truncated` |
| `empty_use_scope_input.candidate_layers.query_state_candidates` | object | 是 | 否 | `snapshot_missing_field:empty_use_scope_input.candidate_layers.query_state_candidates` |
| `empty_use_scope_input.candidate_layers.query_state_candidates.observed` | bool | 是 | 否 | `snapshot_missing_field:empty_use_scope_input.candidate_layers.query_state_candidates.observed` |
| `empty_use_scope_input.candidate_layers.query_state_candidates.count` | int | 是 | 否 | `snapshot_missing_field:empty_use_scope_input.candidate_layers.query_state_candidates.count` |
| `empty_use_scope_input.candidate_layers.query_state_candidates.refs` | list | 是 | 否 | `snapshot_missing_field:empty_use_scope_input.candidate_layers.query_state_candidates.refs` |
| `empty_use_scope_input.candidate_layers.query_state_candidates.truncated` | bool | 是 | 否 | `snapshot_missing_field:empty_use_scope_input.candidate_layers.query_state_candidates.truncated` |
| `empty_use_scope_input.candidate_layers.projection_query_state_candidates` | object | 是 | 否 | `snapshot_missing_field:empty_use_scope_input.candidate_layers.projection_query_state_candidates` |
| `empty_use_scope_input.candidate_layers.projection_query_state_candidates.observed` | bool | 是 | 否 | `snapshot_missing_field:empty_use_scope_input.candidate_layers.projection_query_state_candidates.observed` |
| `empty_use_scope_input.candidate_layers.projection_query_state_candidates.count` | int | 是 | 否 | `snapshot_missing_field:empty_use_scope_input.candidate_layers.projection_query_state_candidates.count` |
| `empty_use_scope_input.candidate_layers.projection_query_state_candidates.refs` | list | 是 | 否 | `snapshot_missing_field:empty_use_scope_input.candidate_layers.projection_query_state_candidates.refs` |
| `empty_use_scope_input.candidate_layers.projection_query_state_candidates.truncated` | bool | 是 | 否 | `snapshot_missing_field:empty_use_scope_input.candidate_layers.projection_query_state_candidates.truncated` |
| `empty_use_scope_input.all_use_layers_observed` | bool | 是 | 否 | `snapshot_missing_field:empty_use_scope_input.all_use_layers_observed` |
| `empty_use_scope_input.empty_set_candidate` | bool | 是 | 否 | `snapshot_missing_field:empty_use_scope_input.empty_set_candidate` |
| `empty_use_scope_input.code` | enum(empty_use_input_complete_empty|empty_use_input_nonempty|empty_use_input_layers_not_observed|empty_use_input_turn_partial|empty_use_input_malformed_event) | 是 | 否 | `snapshot_missing_field:empty_use_scope_input.code` |

### 4.13 `runtime_identity`

| 字段路径 | 类型 | 必填 | 可空 | 缺失固定码 |
|---|---|---|---|---|
| `runtime_identity` | object | 是 | 否 | `snapshot_missing_field:runtime_identity` |
| `runtime_identity.declared` | bool | 是 | 否 | `snapshot_missing_field:runtime_identity.declared` |
| `runtime_identity.unit_ids` | list | 是 | 否 | `snapshot_missing_field:runtime_identity.unit_ids` |
| `runtime_identity.unresolved_unit_ids` | list | 是 | 否 | `snapshot_missing_field:runtime_identity.unresolved_unit_ids` |
| `runtime_identity.document_ids` | list | 是 | 否 | `snapshot_missing_field:runtime_identity.document_ids` |
| `runtime_identity.version_ids` | list | 是 | 否 | `snapshot_missing_field:runtime_identity.version_ids` |
| `runtime_identity.counts` | object | 是 | 否 | `snapshot_missing_field:runtime_identity.counts` |
| `runtime_identity.counts.units` | int | 是 | 否 | `snapshot_missing_field:runtime_identity.counts.units` |
| `runtime_identity.counts.unresolved` | int | 是 | 否 | `snapshot_missing_field:runtime_identity.counts.unresolved` |
| `runtime_identity.counts.documents` | int | 是 | 否 | `snapshot_missing_field:runtime_identity.counts.documents` |
| `runtime_identity.counts.versions` | int | 是 | 否 | `snapshot_missing_field:runtime_identity.counts.versions` |

### 4.14 `public_boundary`

| 字段路径 | 类型 | 必填 | 可空 | 缺失固定码 |
|---|---|---|---|---|
| `public_boundary` | object | 是 | 否 | `snapshot_missing_field:public_boundary` |
| `public_boundary.public_summary_sha256` | sha256 | 是 | 否 | `snapshot_missing_field:public_boundary.public_summary_sha256` |
| `public_boundary.public_summary_keys` | list | 是 | 否 | `snapshot_missing_field:public_boundary.public_summary_keys` |
| `public_boundary.runtime_ids_only_in_declared_blocks` | bool | 是 | 否 | `snapshot_missing_field:public_boundary.runtime_ids_only_in_declared_blocks` |

### 4.15 `content_sha256`

| 字段路径 | 类型 | 必填 | 可空 | 缺失固定码 |
|---|---|---|---|---|
| `content_sha256` | sha256 | 是 | 否 | `snapshot_missing_field:content_sha256` |


## 5. fail-closed 码表（49 个码族）

`<family>` 用于无路径错误；`<family>:<declared.path>` 用于字段级错误（路径就是 §4 的字段路径或数组下标路径）。**任何**未列出的内部异常一律收敛为 `snapshot_io_failed`，不得 fail-open。

| 码族 | 触发条件 |
|---|---|
| `snapshot_bindings_incomplete` | 构造时 bindings 缺冻结 16 键 |
| `snapshot_content_digest_mismatch` | content_sha256 与规范载荷重算不等 |
| `snapshot_contract_version_invalid` | contract_version 不等于本契约版本 |
| `snapshot_credential_material_forbidden` | auth_material_collected 不是 false |
| `snapshot_decrypt_failed` | Fernet 解密失败（坏 key/截断/非密文） |
| `snapshot_doc_code_index_invalid` | 文档名->doc_code 投影输入类型错 |
| `snapshot_document_version_inconsistent` | document_versions 行与 code 矛盾 |
| `snapshot_effective_temporal_inconsistent` | 生效日期/版本块自相矛盾或 baseline 被当作实际值 |
| `snapshot_empty_use_input_inconsistent` | 空使用集输入的分层/计数/结论互相矛盾 |
| `snapshot_encryption_required` | 拒绝非加密落盘路径/空 key |
| `snapshot_entity_code_inconsistent` | entity_code 与实体身份形态不一致 |
| `snapshot_entity_matchability_inconsistent` | entity_matchable 与实体类型/键/filters 不一致 |
| `snapshot_enum_invalid` | 枚举值不在冻结词表（路径见后缀） |
| `snapshot_envelope_invalid` | 载荷不是 JSON 对象（读取/校验入口） |
| `snapshot_evidence_not_supported` | 证据不是对象或无法构造 |
| `snapshot_expected_bindings_invalid` | 读取方 expected_bindings 缺冻结 16 键 |
| `snapshot_fixture_binding_mismatch` | 顶层/binding/source_evidence 的 fixture_kind 不一致 |
| `snapshot_fixture_kind_invalid` | fixture_kind 不在 local_mock/live_h2 |
| `snapshot_forbidden_field` | 出现密码/token/认证头等凭证键 |
| `snapshot_io_failed` | 读写底层失败 |
| `snapshot_json_invalid` | 明文不是严格 JSON（重复键/NaN/非 UTF-8） |
| `snapshot_list_order_invalid` | 声明为排序去重的列表未按字典序去重 |
| `snapshot_manifest_binding_mismatch` | 清单绑定摘要/计数与内容不符 |
| `snapshot_manifest_count_mismatch` | 清单 snapshot_count 与 turns 长度不符 |
| `snapshot_missing_field` | 声明字段缺失（路径见后缀） |
| `snapshot_null_not_allowed` | 非可空字段为 null（路径见后缀） |
| `snapshot_owner_inconsistent` | request_owner 的 availability/reason/source/值互相矛盾 |
| `snapshot_plaintext_secret_rejected` | 字符串值形似 Bearer/JWT/Fernet/私钥等明文凭证 |
| `snapshot_public_boundary_violation` | 公开摘要含未声明键/运行期 id/与摘要不符 |
| `snapshot_read_failed` | 密文不可读 |
| `snapshot_readback_mismatch` | 写后读回与写入规范字节不一致 |
| `snapshot_record_identity_inconsistent` | 记录身份字段互相矛盾（record_level/record_code/doc_code） |
| `snapshot_record_index_conflict` | 记录索引同一 (doc,sheet,row) 指向不同记录键 |
| `snapshot_record_index_invalid` | 记录索引条目缺键/类型错 |
| `snapshot_run_binding_absent` | live_h2 缺 run_binding 摘要（防御；冻结校验通常先行拒绝） |
| `snapshot_run_binding_mismatch` | run 绑定摘要与期望值不符（跨 run 复用） |
| `snapshot_run_binding_unexpected` | local_mock 带 run_binding 摘要（防御；同上） |
| `snapshot_runtime_id_not_declared` | 未声明的运行期 id 键出现在非声明位置 |
| `snapshot_runtime_identity_inconsistent` | runtime_identity 声明块与记录身份不一致 |
| `snapshot_schema_version_invalid` | schema_version 不属于本契约/清单 schema |
| `snapshot_size_invalid` | 密文/明文超出大小上限或为空 |
| `snapshot_source_evidence_invalid` | 来源回合证据未通过冻结严格校验 |
| `snapshot_source_evidence_mismatch` | snapshot.source_evidence 与调用方给出的证据字节不符 |
| `snapshot_source_evidence_unsupported` | 来源回合证据版本不是冻结 v0.3/v0.3-live |
| `snapshot_summary_mismatch` | record_identity_summary 计数/清单与逐行不一致 |
| `snapshot_turn_binding_mismatch` | 回合身份与期望值不符（跨回合复用） |
| `snapshot_type_invalid` | 字段/数组元素类型错（路径见后缀） |
| `snapshot_unknown_field` | 出现未声明键（路径见后缀） |
| `snapshot_write_failed` | 落盘失败（加密/原子替换前） |

### 5.1 关键语义码（消费方必须区分）

| 码 | 含义 | 不得误读为 |
|---|---|---|
| `record_row_reverse_lookup` | `(base_doc_code, sheet, row)` 在公开记录索引命中，`record_code := record_key` | 不是“产品使用了该记录”的证明；它只是**使用侧身份** |
| `record_row_not_in_record_index` | 结构上是表格行，但公开索引无此记录 | 不是“不是记录” |
| `runtime_unit_not_record_level` | unit 是段落/页/标题，不是表格记录 | 不是“记录缺失” |
| `runtime_doc_code_unresolved` | 产品文档名无法投影到 doc_code | 不是“文档不存在” |
| `runtime_unit_unresolved` | 使用层引用的 unit 在 DB 投影中不存在 | 不是空集证据 |
| `entity_identity_document_level` | 实体身份是 `document|<uuid>`，**不可匹配** | P4 **不得**用它判 violation（M-C1P1-01） |
| `entity_identity_matchable_nonrole_filters` | 运行期 `entity_filters` 含产品 `*_id` 键；身份仍可匹配 | 不是合同 v2 §3.4 的目标侧 `matchable` 失败 |
| `effective_as_of_ambiguous` | 多条 `plan_observed`，实际 as_of 不可判定 | 不是“没有日期” |
| `baseline_used_as_effective`（恒 false） | 声明的用例基线未被当作实际值 | 若为 true，校验器直接拒绝 |
| `empty_use_input_layers_not_observed` | 有使用层未发出事件，输入不足以判空 | 不是“非空” |
| `empty_use_input_nonempty` | 至少一个使用层计数 > 0 | 不是 verdict |

## 6. 与 v0.2 / 冻结 v0.3 envelope 的兼容关系

| 对象 | 版本 | 本契约如何处理 |
|---|---|---|
| 回合 envelope（local_mock） | `p2-hard-evidence-capture/v0.1`（旧默认） | 不支持；构造时固定 `snapshot_source_evidence_unsupported` |
| 回合 envelope（local_mock） | `p2-hard-evidence-capture/v0.3` | **唯一**支持的 local_mock 来源；只读 `validate_turn_evidence` |
| 回合 envelope（live_h2） | `p2-hard-evidence-capture/v0.2-live` | 不支持 |
| 回合 envelope（live_h2） | `p2-hard-evidence-capture/v0.3-live` | 支持；`binding.run_binding_sha256` 必填，`business_date_declared` 从 run binding 取 |
| 本契约快照 | `p2-runtime-identity-snapshot/v0.1` | 新对象，与 envelope **并列**落盘（同一 run 目录，文件名 `snapshot-<turn>.fernet`） |
| 本契约清单 | `p2-runtime-identity-snapshot-manifest/v0.1` | 新对象；公开安全，仅计数/枚举/摘要 |

- 冻结 envelope 的**键集不接受额外键**，因此本契约不往旧 envelope 里加字段；也不改变 `validate_turn_evidence` / `read_encrypted_evidence` 的分发。旧 reader 读到快照密文会按 Fernet 解密后按**清单** schema 拒绝（`manifest_unknown_keys:...` 等固定 `EvidenceIntegrityError` 码），**不会**误把它当回合证据；新 reader 按 `schema_version` 只分发本契约的两个 schema。
- 内存回执（`sealed`）语义沿用冻结 writer：磁盘密文恒为写前对象；本契约快照/清单内**不含** `sealed`，写后回执只在内存/清单计数中。
- 版本升级规则：任何字段增删、枚举变化、码表变化、公开摘要键变化都必须出新 `schema_version` 与新文档、新密文；不得原地放宽旧版本（`snapshot_schema_version_invalid`）。

## 7. 消费方式

### 7.1 给 C1-P2（空使用集闭包）

`empty_use_scope_input` 是**声明式输入**，不是证明结果。映射：

| C1-P2 语义 | 快照字段 |
|---|---|
| `_usage_layers` 的 9 个使用层 | `use_layers.<layer>.count/refs`（`direct_rag_fact_count` 的 `count` 即 fact 数） |
| 候选层（不计入使用） | `candidate_layers.*`（`retrieval_observed` 保留 `truncated`） |
| 分支（legacy/rag、model purpose、clarification） | `plan.path/mode/clarification` + 事件本身仍在冻结 envelope |
| 回合完整性 | `turn_status` / `reason`（来自 `runtime_snapshot.retrieval_use`） |
| 空集充分条件 | `all_use_layers_observed` + 9 层计数全 0（即 `empty_set_candidate`） |

输入只从**已发布事件协议**与 `db_projection` 的已声明字段派生，不读取 `p2_hard_evidence._empty_use_scope_proof` 的任何私有结构；因此 P2 的替代实现可以直接消费本块，或与冻结 envelope 交叉核对。`empty_set_candidate=false` 不得当作非空证据；真正的闭包判定仍由 P2 的分支分类完成。

### 7.2 给 C1-P4（消费侧适配）

1. **实际日期**：`effective_temporal.as_of` + `as_of_source` 就是冻结分类器 `_check_stale_source` 读取的 `plan_observed.as_of`（首选）与 `db_projection.rag_business_date`（回退）的运行期值。P4 用它比较冻结轴 `as_of` 时，**不得**改用用例声明基线；`declared_baseline_business_date` 只作 lineage。
2. **实际版本**：`document_versions[].runtime_version_number` 与 `product_version_number` 并列；不等即 `version_mismatch`，P4 必须保留为 unknown/不一致，而不是挑一个“看起来对”的版本。
3. **实体/记录身份**：`record_identities[]` 是**使用侧**身份（实际用了哪些 unit、属于哪条记录），不是目标集；不得用它反推 expected targets。匹配合同 v2 目标时必须用 `(entity_type, entity_key, entity_filters)`，不得用文档名/locator-only（旧病）。
4. **M-C1P1-01 红线**：`entity_type="document"` 或 `entity_matchable=false` 的行**不得**用于 violation 判定；只能是 unknown 或“改用 doc_code 级身份”。`entity_identity_document_level` 是显式标记。
5. **公开/私有边界**：公开报告只能引用 §8 的公开摘要（计数/布尔/固定码），不得输出 unit/document/version id、记录键或日期值。

### 7.3 给独立验收方

按 §11 重算：字段表 + 码表自检、逐叶读回相等、公开摘要摘要值、跨 run/跨回合拒绝、未声明 id/凭证键拒绝、密文无明文。任一项失败按对应固定码记 FAIL，不得“降级消费”。

## 8. evidence 键集收紧与公开边界

- **严格键集**：每层对象恰好声明键；数组元素也恰好声明键。未知键拒绝（固定码），不做“宽容读取”。
- **运行期 id 载体白名单**：`record_identities[].source_ref`、`effective_temporal.document_versions[].source_ref`、`empty_use_scope_input.use_layers.*.refs`、`candidate_layers.*.refs`、`runtime_identity.{unit_ids,unresolved_unit_ids,document_ids,version_ids}`。只有这些位置允许出现 unit/document/version 的运行期 id；其他位置出现 `unit_id/document_id/version_id/*_row_id/index_id/...` 一律 `snapshot_runtime_id_not_declared`。
- **凭证边界**：schema 无 `password*` / `session_token` / `authorization` / `cookie` / `credential*` / `bearer` / `api_key` / `private_key` 等字段；上述词根在任意键名中命中即 `snapshot_forbidden_field`；值形似 Bearer/JWT/Fernet/私钥/`sk-` 即 `snapshot_plaintext_secret_rejected`。`auth_material_collected` 恒为 `false`，否则 `snapshot_credential_material_forbidden`。
- **公开摘要**：恰 25 键（计数/布尔/固定枚举），`public_boundary.public_summary_keys` 必须逐值等于声明键集，`public_summary_sha256` 必须等于规范 JSON 摘要；摘要内出现任何运行期 id 键 → `snapshot_public_boundary_violation`。快照本体只以 Fernet 密文落盘（仓外），不得写明文侧车。

## 9. 合成验证与反例矩阵（本包已执行的部分，数字见报告）

| 类 | 覆盖 |
|---|---|
| 全链 | MockChatBackend + 合成租户/文档：采集 → 加密落盘（仓外）→ 读回 → 校验；逐叶字段相等；密文无题面/文档名/用户标识 |
| 反例·结构 | 字段缺失、类型错、`null` 非法、枚举错、未知键 |
| 反例·身份 | 未声明运行期 id、跨 run 复用（读+写两侧）、跨回合复用、清单跨 run |
| 反例·机密 | 凭证键、Bearer/Fernet 形态值、明文 JSON 冒充密文 |
| 反例·语义 | 摘要篡改、来源证据不符、baseline 冒充实际值、空集输入自相矛盾、实体可匹配性伪造、公开摘要越界 |
| 反例·构造 | 记录索引冲突、索引缺失、doc_code 缺失、unit 未解析、文档级实体不可匹配、非 v0.3 来源/重放证据 |

## 10. 未覆盖 / NOT-RUN

- 真实 H2 采集（C1-2）未执行；本契约只做合成 + Mock 验证，零真实调用。
- `live_h2` 正式路径只做了 schema/构造分支校验（`run_binding` 必填、`business_date_declared` 取值），没有真实 live 证据。
- 记录身份依赖调用方给出的公开投影索引（`doc_code_index` / `record_index` / aliases）。真实 H2 上该索引由 C1-P1 的 v2 投影规则提供；本契约不重新实现 v2 投影，也不声称 30 题覆盖。
- `shared_background` 条目、`business_version` 的语料语义、运行期索引实例完整性不在本契约范围。
- `entity_filters` 含非角色键（产品 `*_id`）的运行期身份**可匹配**（`entity_identity_matchable_nonrole_filters`），这与合同 v2 §3.4 的目标侧 `matchable` 不是同一谓词；P4 必须按 §7.2 处理，不得混用。
- 本契约不声明质量通过、T207 通过、阈值/基线/发布批准。

## 11. 校验算法（读回侧逐步执行）

1. 读密文原始字节；空/超限 → `snapshot_size_invalid`；Fernet 解密失败 → `snapshot_decrypt_failed`。
2. 严格 JSON（拒绝重复键/NaN/非 UTF-8）→ 失败 `snapshot_json_invalid`。
3. 按顶层 `schema_version` 分发（快照/清单）；未知版本 → `snapshot_schema_version_invalid`。
4. 递归拒绝：凭证键 → `snapshot_forbidden_field`；明文凭证形态 → `snapshot_plaintext_secret_rejected`。
5. 严格键集/类型/可空/枚举：`snapshot_missing_field` / `snapshot_null_not_allowed` / `snapshot_type_invalid` / `snapshot_enum_invalid` / `snapshot_unknown_field` / `snapshot_runtime_id_not_declared`。
6. 交叉不变量：fixture 三处一致、owner 形态、记录身份形态、摘要计数、生效时间/版本、空集输入、runtime_identity、公开摘要（对应 §5 码表）。
7. 重算 `content_sha256` → `snapshot_content_digest_mismatch`。
8. 期望绑定：16 键摘要 + run/plan/scenario/fixture → `snapshot_run_binding_mismatch`；回合三元组 → `snapshot_turn_binding_mismatch`；来源证据摘要/schema/fixture → `snapshot_source_evidence_mismatch`。
9. 任一步失败按固定码拒绝；不降级、不“尽力消费”、不把缺失当空。

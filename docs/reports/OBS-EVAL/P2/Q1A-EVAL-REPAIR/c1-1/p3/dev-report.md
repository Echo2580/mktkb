# C1-P3 开发报告：运行期身份快照采集契约 v0.3

- 角色：C1-P3 普通开发助手（非验收、非经理）；本报告不写“通过/PASS/已验证”，只陈述产物、数字与残余。
- 日期：2026-11-14；分支 `codex/p2-e2e`；HEAD `97b0066726e5b8d6f94cbc0b63a890084550c106`；暂存区 0 项、0 commit。
- 任务单一句话：新增版本化采集契约，不改任何冻结件，用合成 + Mock 验证 owner/实体记录身份/实际生效日期版本/空使用集输入四类快照字段可采集、加密落盘、严格读回、逐字段校验。
- **结论：`COMPLETE`（本包范围内）**。残余见 §8：4 个防御性固定码未构造反例、live_h2 与真实 H2 采集 NOT-RUN、P4 消费适配不在本包。

## 1. 交付物

| 类型 | 路径 | SHA256 / 字节 |
|---|---|---|
| 契约文档 | `docs/evaluation/p2-hard-evidence-capture-v0_3.md` | `67f6d534e899a461d38b2e1e5661e454398302e894dde291ffe6138b33f231d9` / 51260 |
| 新模块 | `backend/src/mktkb/evaluation/p2_evidence_snapshot_v03.py` | `63ca7ecf76633b38613399ad05c737ec8d32f401b062f4afe7ef7040437aeb42` / 94641 |
| 测试 | `backend/tests/evaluation/test_p2_evidence_snapshot_v03.py` | `cd661252b085d5ca1de7eeeb47eb78a6bee4f9a25299423aaf31a15b23b21dee` / 44010 |
| 本报告 | `docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/c1-1/p3/dev-report.md` | 本文件 |
| 证据 | `docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/c1-1/p3/evidence/` | 见 §7 |

契约版本 `p2-hard-evidence-capture-identity/v0.3`；载荷 schema `p2-runtime-identity-snapshot/v0.1`；清单 schema `p2-runtime-identity-snapshot-manifest/v0.1`。

## 2. 实现要点（四类字段 + 收紧）

1. **请求 owner**：`request_owner.{availability,reason,user_ref,conversation_ref,owner_source,auth_material_collected}`。`user_ref` 取产品会话已认证的 `turn.authenticated_user_id`（不透明主体 id），**不采**密码 hash/session token/HTTP 认证头；`auth_material_collected` 恒为 false，凭证键名/明文凭证形态值一律固定拒绝。
2. **实体/记录身份**：`record_identities[]` 每行 `(source_ref, layers, doc_code, base_doc_code, sheet, row, record_key, record_code, business_version, version_number, record_level, entity_type, entity_key, entity_filters, entity_matchable, code, entity_code)`；`record_code` 的投影与合同 v2 §5 同构：`doc_code → base_doc_code → (sheet,row) 反查 record_key → record_code := record_key`，失败保留固定码，不硬填。
3. **实际生效日期与版本**：`effective_temporal.as_of` 只取运行期实际值（唯一 `plan_observed.as_of`，回退 `db_projection.rag_business_date` 并标 `as_of_source`）；`document_versions[]` 并列 `runtime_version_number` 与 `product_version_number`；用例声明基线单独放 `declared_baseline_business_date`，`baseline_used_as_effective` 恒 false（校验器强制）。
4. **空使用集证明输入**：`empty_use_scope_input` 按事件协议逐层声明 9 个使用层（`model_evidence`/`model_output_sources`/`direct_rag_facts`/`direct_rag_citations`/`direct_rag_fact_count`/`answer_result_sources`/`commit_observed_sources`/`entity_inheritance`/`projection_message_sources`）与 3 个候选层，附 `plan`、`turn_status`、`all_use_layers_observed`、`empty_set_candidate`。它只从已发布事件协议与 `db_projection` 已声明字段派生，**不 import** `p2_hard_evidence` 或 `p2_empty_scope_proof`，不依赖冻结原语私有结构。
5. **键集收紧**：每层严格键集；运行期 id 只允许出现在声明的 5 类载体（`record_identities[].source_ref`、`document_versions[].source_ref`、使用层/候选层 `refs`、`runtime_identity.*`）；公开摘要恰 25 键（计数/布尔/固定码），摘要内出现运行期 id 键即 `snapshot_public_boundary_violation`。
6. **冻结边界**：模块只从 `p2_evidence_capture` / `p2_evidence_io` 导入公开常量与公开函数（`BINDING_KEYS`、`*_V03` 版本常量、`assert_evidence_root_outside_repo`、`canonical_json_bytes`、`sha256_hex`、`validate_turn_evidence`、`EvidenceIOError`），无私有符号、无原地修改；快照是与冻结 envelope 并列的独立密文。

## 3. 契约数字（机器导出，`evidence/field-table.json`）

| 项 | 值 |
|---|---:|
| 字段规格条目（含容器；`identity_field_table()`） | **167** |
| 必填字段 | **167** |
| 可空字段（`null` 合法，仍需键存在） | **35** |
| 固定 fail-closed 码族 | **49** |
| 公开摘要键 | **25** |
| 使用层 / 候选层 | 9 / 3 |
| 直接触发过反例的码族 | **45 / 49**（其余 4 个为防御路径，见 §8） |

## 4. 全链实测（MockChatBackend + 合成租户/文档）

`test_full_chain_roundtrip_field_by_field`：真实产品装配 + 合成 provider + `fixtures/acceptance` 公共语料（D01 表格、D04 Word），两回合；adapter 自测 `outbound_attempts=0`。

| 回合 | 问题类型 | 使用 unit | 记录身份 | 实体身份 | 实际生效日期 | 空使用集输入 |
|---|---|---|---:|---|---|---|
| 0 | Word 流程问答（legacy） | 4（段落级） | `record_level=0`；`runtime_unit_not_record_level`；`doc_codes=[D04]` | `entity_identity_absent`（该运行期未观察到文档级 entity 行） | `observed` / `2026-03-15` / `plan_observed` | `turn_status=complete` / `empty_use_input_nonempty` / `empty_set_candidate=false` |
| 1 | 枚举记录（rag） | 2（表格行） | `record_level=2`；`P01`(row 8)、`P02`(row 9)；`record_row_reverse_lookup`；`doc_codes=[D01]` | `item`，`entity_matchable=true`，`entity_identity_matchable_nonrole_filters` | `observed` / `2026-03-15` / `plan_observed`；版本 2 行 `version_observed` | 同上 |

- `2026-03-15` 是测试显式传给产品的合成业务日期（`rag_business_date=manifest_business_date`），**不是**任何冻结用例基线；证明快照记录“实际用的”，不是“应该用的”。
- 落盘：两份快照密文分别 10124 B / 8268 B，均在仓外；读回对象与构造对象**逐叶相等 444 个叶值**（`roundtrip_leaf_count_total=444`），并逐字段断言 owner、run/turn 绑定、来源证据摘要、`content_sha256`、公开摘要 25 键。
- 密文扫描：题面、产品文档名、用户标识均未出现在密文；载荷明文也不含题面/文档名（只含哈希与授权内 `user_ref`）。

## 5. 反例矩阵（26 用例 / 45 个码族被直接触发）

| 反例类 | 触发码（示例） | 关键断言 |
|---|---|---|
| 字段缺失 / 类型错 / `null` / 枚举 / 未知键 | `snapshot_missing_field:request_owner.owner_source`、`snapshot_type_invalid:turn_ref.turn_index`、`snapshot_null_not_allowed:binding.run_id`、`snapshot_enum_invalid:fixture_kind`、`snapshot_unknown_field:record_identities[0].raw_row` | 每条都是固定码，不带值回显 |
| **跨 run 复用** | `snapshot_run_binding_mismatch:binding.bindings_sha256`（读侧 + 写侧各一次）、`snapshot_manifest_binding_mismatch:bindings_sha256` | 换 run bindings 读/写都拒绝 |
| 跨回合复用 | `snapshot_turn_binding_mismatch:turn_ref.conversation_id` | 同 run 不同 conversation 拒绝 |
| **未声明运行期 id 混入** | `snapshot_runtime_id_not_declared:record_identities[0].unit_id`、`…:public_boundary.document_id` | 只有声明的 5 类载体可带 id |
| **明文泄漏** | `snapshot_forbidden_field:request_owner.session_token`、`snapshot_plaintext_secret_rejected:request_owner.user_ref`、`snapshot_decrypt_failed`（明文 JSON 冒充密文） | 凭证键、Bearer/Fernet 形态值、非密文三路都拒绝 |
| 摘要/来源证据 | `snapshot_content_digest_mismatch:content_sha256`、`snapshot_source_evidence_mismatch:source_evidence.sha256`、`snapshot_source_evidence_invalid`、`snapshot_source_evidence_unsupported` | 篡改/换证据/非 v0.3/重放都拒绝 |
| 语义自相矛盾 | `snapshot_effective_temporal_inconsistent`（baseline 冒充实际值）、`snapshot_empty_use_input_inconsistent`、`snapshot_entity_matchability_inconsistent`、`snapshot_entity_code_inconsistent`、`snapshot_record_identity_inconsistent`、`snapshot_document_version_inconsistent`、`snapshot_summary_mismatch`、`snapshot_runtime_identity_inconsistent`、`snapshot_list_order_invalid`、`snapshot_owner_inconsistent`、`snapshot_credential_material_forbidden` | 每类独立触发 |
| 公开边界 | `snapshot_public_boundary_violation:public_boundary.public_summary_keys` | 摘要键/摘要值都必须与声明一致 |
| 构造输入 | `snapshot_record_index_conflict`、`snapshot_record_index_invalid`、`snapshot_doc_code_index_invalid`、`snapshot_bindings_incomplete`、`snapshot_evidence_not_supported` | 公开投影索引的坏输入 fail-closed |
| 文档级实体（M-C1P1-01） | 合成变异：`entity_type=document` → `entity_matchable=false`、`entity_identity_document_level`、`record_identity_summary.entity_document_level=1` | 文档级身份不得用于 violation |
| 未解析 unit / 索引缺失 / doc_code 缺失 | `runtime_unit_unresolved`、`record_row_not_in_record_index`、`runtime_doc_code_unresolved` | 逐行固定码，不硬填 |

## 6. 消费接口

- **C1-P2**：`empty_use_scope_input` 的 9 个使用层与 3 个候选层逐一对应 P2 的语义；`empty_set_candidate` 只是输入侧充分条件，false 不等于非空；真正的闭包判定仍由 P2 分支分类完成。本包**没有**修改 P2 模块或其测试。
- **C1-P4**：`effective_temporal.as_of` + `as_of_source` 直接对应冻结分类器 `_check_stale_source` 读取的 `plan_observed.as_of` / `rag_business_date`；`document_versions` 并列实际/产品版本；`record_identities` 是使用侧身份，不是目标集；`entity_matchable=false`（尤其 `entity_identity_document_level`）不得用于 violation 判定（M-C1P1-01 红线）。
- 契约文档 §7 给出了逐项映射与禁止项。

## 7. 保护与零调用（证据）

| 项 | 结果 | 证据 |
|---|---|---|
| C 冻结 12 对象 | 12/12 与参考逐字节相等，0 处不一致 | `evidence/frozen-sha.json` |
| 15 tracked modified | 路径与哈希前后一致（15/15） | `evidence/protected-compare.json` |
| 既有 untracked | 基线 2084 个仓内文件逐个重算：0 改动、0 缺失；新增仅本包 3 个顶层文件 + `p3/` 树；0 个非允许新增 | 同上 |
| 暂存 / HEAD / 分支 | staged 0；HEAD 与分支不变 | 同上 |
| 零真实调用 | 26 用例，进程级守卫：external connect/DNS/HTTP/httpx 全 0，`blocked=0`；`loopback_connects=1`（工具自管道） | `evidence/zero-call.json` |
| netguard 正对照 | 外部连接与外部 DNS 各 1 次均被拦截（`blocked=2`） | `evidence/netguard-positive-control.json` |
| 测试运行 | `26 passed`，exit 0；collect-only 26 用例 | `evidence/pytest.txt`、`pytest-collect.txt` |

## 8. 残余与未决

| id | 级别 | 内容 |
|---|---|---|
| P3-R1 | low | 4 个固定码只有防御路径、未构造反例：`snapshot_io_failed`、`snapshot_readback_mismatch`、`snapshot_run_binding_absent`、`snapshot_run_binding_unexpected`。后两者在冻结 `validate_turn_evidence` 先行校验下当前不可达（fixture 与 run_binding 双向强校验），保留为防御。 |
| P3-R2 | medium | `live_h2` 只做 schema/构造分支；无真实 live 证据，`run_binding_sha256`/`business_date_declared` 的 live 取值未实测。 |
| P3-R3 | medium | 记录身份依赖调用方给出的公开投影索引；真实 H2 上索引由 P1 v2 规则提供，本包不重算 v2 投影、不声称 30 题覆盖。 |
| P3-R4 | low | 合成 D04 回合未观察到 `entity_type=document` 行（该运行期投影无 entity 行）；文档级红线用**变异合成证据**验证（`test_document_level_entity_is_not_matchable`），不是真实产品行为。 |
| P3-R5 | low | 运行期 `entity_filters` 含产品 `*_id` 键；本契约将其标为 `entity_identity_matchable_nonrole_filters`（可匹配），与合同 v2 §3.4 目标侧 `matchable` 不是同一谓词，P4 需按文档 §7.2 处理。 |
| P3-R6 | low | 变异证据用例（文档级实体、未解析 unit、重放）不重跑冻结 `evaluate_completeness`；快照的 `completeness_status` 是**复制**值，不是重算值。 |
| NOT-RUN | — | 真实 H2 采集、C1-2 复跑、P4 消费适配、T207/T208/T209/T900 全部不在本包。 |

## 9. 不声明

本包**不构成**：T207 通过、质量通过、release/阈值/基线批准、C1-2 授权、P2 完成、真实产品行为正确。`verified` / `threshold_met` / `release_ready` / `T207_pass` 一律未主张；所有结论限于合成 + Mock 与零真实调用范围。

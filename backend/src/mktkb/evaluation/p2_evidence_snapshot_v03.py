"""C1-P3：运行期身份快照采集契约 v0.3（`p2-runtime-identity-snapshot/v0.1`）。

本模块是**新增的版本化契约**，不是对 C 冻结对象的修改：

- 不修改、不复制、不替换 ``p2_evidence_capture.py``（`601096bc…`）与
  ``p2_evidence_io.py``（`1c16a3da…`）；只在**只读**意义上调用它们的公开函数
  （``validate_turn_evidence`` / ``canonical_json_bytes`` / ``sha256_hex`` /
  ``assert_evidence_root_outside_repo``）与公开常量。
- 新产物是与冻结 v0.3 回合证据**并列**的独立密文，载荷 schema 为
  ``p2-runtime-identity-snapshot/v0.1``，契约版本 ``p2-hard-evidence-capture-identity/v0.3``。
  冻结 envelope 的键集不接受额外键，因此本契约**不**往旧 envelope 里塞字段。

回答的四个运行期问题（任务书 §5）：

1. 请求 owner 身份（认证后的用户/会话归属；**不采**密码 hash / session token /
   HTTP 认证头；出现即固定拒绝）；
2. 实体/记录身份（含 ``record_code``：doc_code + sheet/row/记录键，与合同 v2 §5
   的 R-RC-1..5 同构）；
3. 实际生效日期与版本（产品**实际**使用的 ``as_of`` / ``business_date`` / 文档版本，
   不是“应该用的”；用例声明的 baseline 单独存放且 ``baseline_used_as_effective`` 恒为 false）；
4. 空使用集证明输入（按事件协议逐层声明，供 C1-P2 实现消费；不依赖冻结原语私有结构）。

边界：不产生四轴 verdict、不读真实 H2、不调用产品/模型/embedding/rerank/OCR/裁判/
检索/鉴权/余额，零出站。缺失/类型错/越界一律固定 fail-closed 码，不 fail-open。
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from cryptography.fernet import Fernet, InvalidToken

from .p2_evidence_capture import (
    BINDING_KEYS,
    EVIDENCE_SCHEMA_VERSION_V03,
    LIVE_EVIDENCE_SCHEMA_VERSION_V03,
    assert_evidence_root_outside_repo,
)
from .p2_evidence_io import (
    EvidenceIOError,
    canonical_json_bytes,
    sha256_hex,
    validate_turn_evidence,
)

__all__ = [
    "CANDIDATE_LAYER_NAMES",
    "CONTRACT_VERSION",
    "EMPTY_USE_INPUT_VERSION",
    "ENTITY_CODES",
    "ENTITY_ROLE_NAMES",
    "EMPTY_USE_CODES",
    "FAIL_CLOSED_CODES",
    "FIXTURE_KINDS",
    "LOCATOR_KINDS",
    "MATCHABLE_ENTITY_TYPES",
    "PUBLIC_SUMMARY_KEYS",
    "RECORD_IDENTITY_CODES",
    "SNAPSHOT_MANIFEST_SCHEMA_VERSION",
    "SNAPSHOT_SCHEMA_VERSION",
    "SOURCE_EVIDENCE_VERSIONS",
    "SnapshotContractError",
    "SnapshotWriter",
    "TEMPORAL_CODES",
    "USE_LAYER_NAMES",
    "build_identity_snapshot",
    "build_snapshot_manifest",
    "identity_field_table",
    "public_identity_summary",
    "read_snapshot_evidence",
    "validate_identity_snapshot",
    "validate_snapshot_manifest",
]

CONTRACT_VERSION = "p2-hard-evidence-capture-identity/v0.3"
SNAPSHOT_SCHEMA_VERSION = "p2-runtime-identity-snapshot/v0.1"
SNAPSHOT_MANIFEST_SCHEMA_VERSION = "p2-runtime-identity-snapshot-manifest/v0.1"
EMPTY_USE_INPUT_VERSION = "c1p2-empty-use-scope-input/v0.1"

FIXTURE_KINDS = ("local_mock", "live_h2")
#: 冻结 v0.3 回合证据 -> 其 fixture_kind；本契约只接受这两个来源版本。
SOURCE_EVIDENCE_VERSIONS = {
    EVIDENCE_SCHEMA_VERSION_V03: "local_mock",
    LIVE_EVIDENCE_SCHEMA_VERSION_V03: "live_h2",
}

#: 运行期 unit locator 的形态（``record`` 才能承载记录身份）。
LOCATOR_KINDS = ("record", "page", "heading", "other", "none", "unavailable")

#: 与合同 v2 §4.2 相同的 6 个身份角色；``filters`` 只允许这些键。
ENTITY_ROLE_NAMES = ("store", "item", "product", "channel", "price_type", "identifier")
#: 与合同 v2 §3.4 相同的可匹配实体类型；``document`` 不可匹配（M-C1P1-01）。
MATCHABLE_ENTITY_TYPES = ("item", "store", "record")
PRODUCT_ENTITY_TYPES = ("product", "item", "store", "record", "document")

#: 使用层（真正进入回答/提交/模型输入/引用/事实/实体继承的来源）。
USE_LAYER_NAMES = (
    "model_evidence",
    "model_output_sources",
    "direct_rag_facts",
    "direct_rag_citations",
    "direct_rag_fact_count",
    "answer_result_sources",
    "commit_observed_sources",
    "entity_inheritance",
    "projection_message_sources",
)
#: 候选层（检索观察/查询状态；**不是**已使用来源）。
CANDIDATE_LAYER_NAMES = (
    "retrieval_observed",
    "query_state_candidates",
    "projection_query_state_candidates",
)

RECORD_IDENTITY_CODES = (
    "record_row_reverse_lookup",
    "record_row_not_in_record_index",
    "runtime_unit_not_record_level",
    "runtime_doc_code_unresolved",
    "runtime_unit_unresolved",
)
ENTITY_CODES = (
    "entity_identity_matchable",
    "entity_identity_matchable_nonrole_filters",
    "entity_identity_nonmatchable",
    "entity_identity_document_level",
    "entity_identity_absent",
    "entity_identity_unavailable",
)
TEMPORAL_CODES = (
    "effective_temporal_observed",
    "effective_temporal_partial",
    "effective_temporal_not_observed",
    "effective_as_of_not_observed",
    "effective_as_of_ambiguous",
)
EMPTY_USE_CODES = (
    "empty_use_input_complete_empty",
    "empty_use_input_nonempty",
    "empty_use_input_layers_not_observed",
    "empty_use_input_turn_partial",
    "empty_use_input_malformed_event",
)

MAX_TEXT = 512
MAX_ID = 256
MAX_RECORD_ROWS = 256
MAX_VERSION_ROWS = 256
MAX_JSON_BYTES = 16 * 1024 * 1024

#: 凭证/认证材料键名（子串匹配）：出现即固定拒绝，不落盘、不回显值。
FORBIDDEN_KEY_TOKENS = (
    "password",
    "passwd",
    "secret",
    "authorization",
    "authorisation",
    "cookie",
    "credential",
    "bearer",
    "session_token",
    "sessiontoken",
    "api_key",
    "apikey",
    "auth_token",
    "accesstoken",
    "access_token",
    "refresh_token",
    "id_token",
    "private_key",
    "client_secret",
)
#: 未声明的运行期 id 键名：只允许出现在 ``runtime_identity`` / 已声明字段里。
RUNTIME_ID_KEYS = (
    "unit_id",
    "unit_ids",
    "document_id",
    "document_ids",
    "version_id",
    "version_ids",
    "db_row_id",
    "row_id",
    "rowid",
    "index_id",
    "index_instance_id",
    "retrieval_index_id",
    "request_id",
    "message_id",
    "source_id",
    "pk",
    "uuid",
)

#: 固定 fail-closed 码族：``<family>`` 或 ``<family>:<declared.path>``。
#: 值 = 触发条件（报告与契约文档共用此表，机器可读）。
FAIL_CLOSED_CODES: Mapping[str, str] = {
    "snapshot_envelope_invalid": "载荷不是 JSON 对象（读取/校验入口）",
    "snapshot_contract_version_invalid": "contract_version 不等于本契约版本",
    "snapshot_schema_version_invalid": "schema_version 不属于本契约/清单 schema",
    "snapshot_fixture_kind_invalid": "fixture_kind 不在 local_mock/live_h2",
    "snapshot_missing_field": "声明字段缺失（路径见后缀）",
    "snapshot_null_not_allowed": "非可空字段为 null（路径见后缀）",
    "snapshot_type_invalid": "字段/数组元素类型错（路径见后缀）",
    "snapshot_enum_invalid": "枚举值不在冻结词表（路径见后缀）",
    "snapshot_unknown_field": "出现未声明键（路径见后缀）",
    "snapshot_runtime_id_not_declared": "未声明的运行期 id 键出现在非声明位置",
    "snapshot_forbidden_field": "出现密码/token/认证头等凭证键",
    "snapshot_plaintext_secret_rejected": "字符串值形似 Bearer/JWT/Fernet/私钥等明文凭证",
    "snapshot_list_order_invalid": "声明为排序去重的列表未按字典序去重",
    "snapshot_content_digest_mismatch": "content_sha256 与规范载荷重算不等",
    "snapshot_fixture_binding_mismatch": "顶层/binding/source_evidence 的 fixture_kind 不一致",
    "snapshot_source_evidence_invalid": "来源回合证据未通过冻结严格校验",
    "snapshot_source_evidence_unsupported": "来源回合证据版本不是冻结 v0.3/v0.3-live",
    "snapshot_source_evidence_mismatch": "snapshot.source_evidence 与调用方给出的证据字节不符",
    "snapshot_bindings_incomplete": "构造时 bindings 缺冻结 16 键",
    "snapshot_expected_bindings_invalid": "读取方 expected_bindings 缺冻结 16 键",
    "snapshot_run_binding_mismatch": "run 绑定摘要与期望值不符（跨 run 复用）",
    "snapshot_turn_binding_mismatch": "回合身份与期望值不符（跨回合复用）",
    "snapshot_run_binding_absent": "live_h2 缺 run_binding 摘要（防御；冻结校验通常先行拒绝）",
    "snapshot_run_binding_unexpected": "local_mock 带 run_binding 摘要（防御；同上）",
    "snapshot_owner_inconsistent": "request_owner 的 availability/reason/source/值互相矛盾",
    "snapshot_credential_material_forbidden": "auth_material_collected 不是 false",
    "snapshot_record_identity_inconsistent": "记录身份字段互相矛盾（record_level/record_code/doc_code）",
    "snapshot_entity_matchability_inconsistent": "entity_matchable 与实体类型/键/filters 不一致",
    "snapshot_entity_code_inconsistent": "entity_code 与实体身份形态不一致",
    "snapshot_summary_mismatch": "record_identity_summary 计数/清单与逐行不一致",
    "snapshot_effective_temporal_inconsistent": "生效日期/版本块自相矛盾或 baseline 被当作实际值",
    "snapshot_document_version_inconsistent": "document_versions 行与 code 矛盾",
    "snapshot_empty_use_input_inconsistent": "空使用集输入的分层/计数/结论互相矛盾",
    "snapshot_runtime_identity_inconsistent": "runtime_identity 声明块与记录身份不一致",
    "snapshot_public_boundary_violation": "公开摘要含未声明键/运行期 id/与摘要不符",
    "snapshot_record_index_invalid": "记录索引条目缺键/类型错",
    "snapshot_record_index_conflict": "记录索引同一 (doc,sheet,row) 指向不同记录键",
    "snapshot_doc_code_index_invalid": "文档名->doc_code 投影输入类型错",
    "snapshot_evidence_not_supported": "证据不是对象或无法构造",
    "snapshot_write_failed": "落盘失败（加密/原子替换前）",
    "snapshot_readback_mismatch": "写后读回与写入规范字节不一致",
    "snapshot_io_failed": "读写底层失败",
    "snapshot_read_failed": "密文不可读",
    "snapshot_size_invalid": "密文/明文超出大小上限或为空",
    "snapshot_decrypt_failed": "Fernet 解密失败（坏 key/截断/非密文）",
    "snapshot_json_invalid": "明文不是严格 JSON（重复键/NaN/非 UTF-8）",
    "snapshot_manifest_binding_mismatch": "清单绑定摘要/计数与内容不符",
    "snapshot_manifest_count_mismatch": "清单 snapshot_count 与 turns 长度不符",
    "snapshot_encryption_required": "拒绝非加密落盘路径/空 key",
}


class SnapshotContractError(RuntimeError):
    """固定码异常：``code`` 是 ``FAIL_CLOSED_CODES`` 的族或 ``族:声明路径``。"""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


# --------------------------------------------------------------------------- #
# 声明式字段 schema（字段表/校验共用同一份声明）
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class FieldSpec:
    kind: str
    nullable: bool = False
    enum: tuple[str, ...] | None = None
    item: "FieldSpec | None" = None
    fields: "Mapping[str, FieldSpec] | None" = None
    sorted_unique: bool = False
    minimum: int | None = None


def _fs(
    kind: str,
    *,
    nullable: bool = False,
    enum: Sequence[str] | None = None,
    item: "FieldSpec | None" = None,
    fields: "Mapping[str, FieldSpec] | None" = None,
    sorted_unique: bool = False,
    minimum: int | None = None,
) -> FieldSpec:
    return FieldSpec(
        kind=kind,
        nullable=nullable,
        enum=None if enum is None else tuple(str(value) for value in enum),
        item=item,
        fields=fields,
        sorted_unique=sorted_unique,
        minimum=minimum,
    )


_USE_LAYER_SPEC = _fs(
    "object",
    fields={
        "observed": _fs("bool"),
        "count": _fs("int", minimum=0),
        "refs": _fs("list_str", sorted_unique=True),
    },
)
_CANDIDATE_LAYER_SPEC = _fs(
    "object",
    fields={
        "observed": _fs("bool"),
        "count": _fs("int", minimum=0),
        "refs": _fs("list_str", sorted_unique=True),
        "truncated": _fs("bool"),
    },
)

_RECORD_IDENTITY_SPEC = _fs(
    "object",
    fields={
        "source_ref": _fs("str"),
        "layers": _fs("list_str", sorted_unique=True),
        "unit_kind": _fs("str"),
        "locator_kind": _fs("enum", enum=LOCATOR_KINDS),
        "doc_code": _fs("str", nullable=True),
        "base_doc_code": _fs("str", nullable=True),
        "sheet": _fs("str", nullable=True),
        "row": _fs("int", nullable=True, minimum=1),
        "record_key": _fs("str", nullable=True),
        "record_code": _fs("str", nullable=True),
        "business_version": _fs("str", nullable=True),
        "version_number": _fs("int", nullable=True, minimum=1),
        "record_level": _fs("bool"),
        "entity_type": _fs("str", nullable=True),
        "entity_key": _fs("str", nullable=True),
        "entity_filters": _fs("map_str"),
        "entity_matchable": _fs("bool"),
        "code": _fs("enum", enum=RECORD_IDENTITY_CODES),
        "entity_code": _fs("enum", enum=ENTITY_CODES),
    },
)

_DOCUMENT_VERSION_SPEC = _fs(
    "object",
    fields={
        "source_ref": _fs("str"),
        "doc_code": _fs("str", nullable=True),
        "version_label": _fs("str", nullable=True),
        "runtime_version_number": _fs("int", nullable=True, minimum=1),
        "product_version_number": _fs("int", nullable=True, minimum=1),
        "code": _fs(
            "enum", enum=("version_observed", "version_mismatch", "version_unresolved")
        ),
    },
)

SNAPSHOT_SCHEMA: Mapping[str, FieldSpec] = {
    "contract_version": _fs("str"),
    "schema_version": _fs("str"),
    "fixture_kind": _fs("enum", enum=FIXTURE_KINDS),
    "captured_utc": _fs("iso_datetime"),
    "source_evidence": _fs(
        "object",
        fields={
            "sha256": _fs("sha256"),
            "schema_version": _fs("str"),
            "fixture_kind": _fs("enum", enum=FIXTURE_KINDS),
            "completeness_status": _fs(
                "enum", enum=("complete", "incomplete", "replayed")
            ),
        },
    ),
    "binding": _fs(
        "object",
        fields={
            "run_id": _fs("str"),
            "plan_sha256": _fs("str"),
            "scenario_id": _fs("str"),
            "fixture_kind": _fs("enum", enum=FIXTURE_KINDS),
            "bindings_sha256": _fs("sha256"),
            "run_binding_sha256": _fs("sha256", nullable=True),
            "business_date_declared": _fs("iso_date", nullable=True),
        },
    ),
    "turn_ref": _fs(
        "object",
        fields={
            "turn_index": _fs("int", minimum=0),
            "client_request_id": _fs("str"),
            "conversation_id": _fs("str"),
            "question_sha256": _fs("sha256"),
            "pre_revision": _fs("int", nullable=True),
            "post_revision": _fs("int", nullable=True),
            "capture_revision": _fs("int", nullable=True),
            "response_kind": _fs("str", nullable=True),
            "http_status": _fs("int", nullable=True),
            "timed_out": _fs("bool"),
        },
    ),
    "request_owner": _fs(
        "object",
        fields={
            "availability": _fs("enum", enum=("observed", "unavailable")),
            "reason": _fs("str", nullable=True),
            "user_ref": _fs("str", nullable=True),
            "conversation_ref": _fs("str", nullable=True),
            "owner_source": _fs(
                "enum", enum=("turn_authenticated_user_id", "unavailable")
            ),
            "auth_material_collected": _fs("bool"),
        },
    ),
    "record_identities": _fs("list_object", item=_RECORD_IDENTITY_SPEC),
    "record_identity_summary": _fs(
        "object",
        fields={
            "total": _fs("int", minimum=0),
            "record_level": _fs("int", minimum=0),
            "not_record_level": _fs("int", minimum=0),
            "doc_code_unresolved": _fs("int", minimum=0),
            "entity_matchable": _fs("int", minimum=0),
            "entity_document_level": _fs("int", minimum=0),
            "unresolved_units": _fs("int", minimum=0),
            "doc_codes": _fs("list_str", sorted_unique=True),
        },
    ),
    "effective_temporal": _fs(
        "object",
        fields={
            "availability": _fs(
                "enum", enum=("observed", "partial", "not_observed")
            ),
            "reason": _fs("str", nullable=True),
            "as_of": _fs("iso_date", nullable=True),
            "as_of_source": _fs(
                "enum", enum=("plan_observed", "rag_business_date", "unavailable")
            ),
            "observed_from": _fs("enum", enum=("db_projection_units", "unavailable")),
            "include_future": _fs("bool", nullable=True),
            "enumerate": _fs("bool", nullable=True),
            "document_versions": _fs("list_object", item=_DOCUMENT_VERSION_SPEC),
            "declared_baseline_business_date": _fs("iso_date", nullable=True),
            "baseline_used_as_effective": _fs("bool"),
            "code": _fs("enum", enum=TEMPORAL_CODES),
        },
    ),
    "empty_use_scope_input": _fs(
        "object",
        fields={
            "input_version": _fs("enum", enum=(EMPTY_USE_INPUT_VERSION,)),
            "turn_status": _fs("enum", enum=("complete", "partial", "unavailable")),
            "reason": _fs("str", nullable=True),
            "plan": _fs(
                "object",
                fields={
                    "availability": _fs("bool"),
                    "path": _fs("str", nullable=True),
                    "mode": _fs("str", nullable=True),
                    "as_of": _fs("iso_date", nullable=True),
                    "include_future": _fs("bool", nullable=True),
                    "clarification": _fs("bool", nullable=True),
                },
            ),
            "use_layers": _fs(
                "object", fields={name: _USE_LAYER_SPEC for name in USE_LAYER_NAMES}
            ),
            "candidate_layers": _fs(
                "object",
                fields={name: _CANDIDATE_LAYER_SPEC for name in CANDIDATE_LAYER_NAMES},
            ),
            "all_use_layers_observed": _fs("bool"),
            "empty_set_candidate": _fs("bool"),
            "code": _fs("enum", enum=EMPTY_USE_CODES),
        },
    ),
    "runtime_identity": _fs(
        "object",
        fields={
            "declared": _fs("bool"),
            "unit_ids": _fs("list_str", sorted_unique=True),
            "unresolved_unit_ids": _fs("list_str", sorted_unique=True),
            "document_ids": _fs("list_str", sorted_unique=True),
            "version_ids": _fs("list_str", sorted_unique=True),
            "counts": _fs(
                "object",
                fields={
                    "units": _fs("int", minimum=0),
                    "unresolved": _fs("int", minimum=0),
                    "documents": _fs("int", minimum=0),
                    "versions": _fs("int", minimum=0),
                },
            ),
        },
    ),
    "public_boundary": _fs(
        "object",
        fields={
            "public_summary_sha256": _fs("sha256"),
            "public_summary_keys": _fs("list_str", sorted_unique=True),
            "runtime_ids_only_in_declared_blocks": _fs("bool"),
        },
    ),
    "content_sha256": _fs("sha256"),
}

#: 公开摘要的固定键集（恰好这些键；不含任何 id/日期/hash/文本）。
PUBLIC_SUMMARY_KEYS = (
    "all_use_layers_observed",
    "candidate_layer_count",
    "completeness_status",
    "doc_code_unresolved_count",
    "document_version_count",
    "effective_as_of_present",
    "effective_temporal_status",
    "empty_set_candidate",
    "empty_use_codes",
    "entity_codes",
    "entity_document_level_count",
    "entity_matchable_count",
    "fixture_kind",
    "not_record_level_count",
    "owner_attribution_present",
    "record_codes",
    "record_identity_total",
    "record_level_count",
    "runtime_id_count",
    "runtime_unit_count",
    "schema_version",
    "temporal_codes",
    "turn_index",
    "usage_layer_count",
    "version_mismatch_count",
)

MANIFEST_SCHEMA: Mapping[str, FieldSpec] = {
    "schema_version": _fs("enum", enum=(SNAPSHOT_MANIFEST_SCHEMA_VERSION,)),
    "fixture_kind": _fs("enum", enum=FIXTURE_KINDS),
    "started_utc": _fs("str"),
    "bindings_sha256": _fs("sha256"),
    "snapshot_count": _fs("int", minimum=0),
    "turns": _fs(
        "list_object",
        item=_fs(
            "object",
            fields={
                "turn_index": _fs("int", minimum=0),
                "snapshot_sha256": _fs("sha256"),
                "source_evidence_sha256": _fs("sha256"),
                "record_identity_total": _fs("int", minimum=0),
                "record_level_count": _fs("int", minimum=0),
                "entity_matchable_count": _fs("int", minimum=0),
                "empty_set_candidate": _fs("bool"),
                "effective_temporal_status": _fs(
                    "enum", enum=("observed", "partial", "not_observed")
                ),
            },
        ),
    ),
    "content_sha256": _fs("sha256"),
}


# --------------------------------------------------------------------------- #
# 基础校验器
# --------------------------------------------------------------------------- #


def _fail(code: str, path: str = "") -> None:
    raise SnapshotContractError(f"{code}:{path}" if path else code)


def _is_str(value: Any) -> bool:
    return type(value) is str and 0 < len(value) <= MAX_TEXT


def _is_sha256(value: Any) -> bool:
    return type(value) is str and len(value) == 64 and all(
        char in "0123456789abcdef" for char in value
    )


def _is_iso_date(value: Any) -> bool:
    if type(value) is not str or len(value) != 10:
        return False
    try:
        return date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def _is_iso_datetime(value: Any) -> bool:
    if type(value) is not str or len(value) > 64:
        return False
    try:
        return datetime.fromisoformat(value).tzinfo is not None
    except ValueError:
        return False


def _scan_forbidden_keys(value: Any, path: str) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            name = str(key)
            lowered = name.lower()
            if any(token in lowered for token in FORBIDDEN_KEY_TOKENS):
                _fail("snapshot_forbidden_field", f"{path}.{name}" if path else name)
            _scan_forbidden_keys(item, f"{path}.{name}" if path else name)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _scan_forbidden_keys(item, f"{path}[{index}]")


def _looks_like_secret(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    lowered = stripped.lower()
    if lowered.startswith("bearer ") or lowered.startswith("basic "):
        return True
    if lowered.startswith("-----begin "):
        return True
    if lowered.startswith("sk-") and len(stripped) >= 20:
        return True
    if stripped.startswith("gAAAAA") and len(stripped) >= 40:
        return True
    parts = stripped.split(".")
    if len(parts) == 3 and all(len(part) >= 8 for part in parts):
        allowed = set(
            "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
        )
        if all(set(part) <= allowed for part in parts):
            return True
    return False


def _scan_secret_values(value: Any, path: str) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            _scan_secret_values(item, f"{path}.{key}" if path else str(key))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _scan_secret_values(item, f"{path}[{index}]")
    elif type(value) is str and _looks_like_secret(value):
        _fail("snapshot_plaintext_secret_rejected", path)


def _validate_keys(value: Mapping[str, Any], spec: FieldSpec, path: str) -> None:
    declared = spec.fields or {}
    for key in value:
        name = str(key)
        if name in declared:
            continue
        full = f"{path}.{name}" if path else name
        lowered = name.lower()
        if lowered in RUNTIME_ID_KEYS:
            _fail("snapshot_runtime_id_not_declared", full)
        _fail("snapshot_unknown_field", full)
    for name in declared:
        if name not in value:
            _fail("snapshot_missing_field", f"{path}.{name}" if path else name)


def _walk(value: Any, spec: FieldSpec, path: str) -> None:
    kind = spec.kind
    if kind == "object":
        if not isinstance(value, Mapping):
            _fail("snapshot_type_invalid", path)
        _validate_keys(value, spec, path)
        for name, child in (spec.fields or {}).items():
            _walk(value[name], child, f"{path}.{name}" if path else name)
        return
    if kind in {"list_object", "list_str"}:
        if not isinstance(value, list):
            _fail("snapshot_type_invalid", path)
        if len(value) > MAX_RECORD_ROWS:
            _fail("snapshot_type_invalid", path)
        if kind == "list_object":
            assert spec.item is not None
            for index, item in enumerate(value):
                _walk(item, spec.item, f"{path}[{index}]")
            return
        for index, item in enumerate(value):
            if not _is_str(item):
                _fail("snapshot_type_invalid", f"{path}[{index}]")
        if spec.sorted_unique and value != sorted(set(value)):
            _fail("snapshot_list_order_invalid", path)
        return
    if value is None:
        if spec.nullable:
            return
        _fail("snapshot_null_not_allowed", path)
    if kind == "str":
        if not _is_str(value):
            _fail("snapshot_type_invalid", path)
        return
    if kind == "sha256":
        if not _is_sha256(value):
            _fail("snapshot_type_invalid", path)
        return
    if kind == "iso_date":
        if not _is_iso_date(value):
            _fail("snapshot_type_invalid", path)
        return
    if kind == "iso_datetime":
        if not _is_iso_datetime(value):
            _fail("snapshot_type_invalid", path)
        return
    if kind == "int":
        if type(value) is not int:
            _fail("snapshot_type_invalid", path)
        if spec.minimum is not None and value < spec.minimum:
            _fail("snapshot_type_invalid", path)
        return
    if kind == "bool":
        if type(value) is not bool:
            _fail("snapshot_type_invalid", path)
        return
    if kind == "enum":
        if type(value) is not str or value not in (spec.enum or ()):
            _fail("snapshot_enum_invalid", path)
        return
    if kind == "map_str":
        if not isinstance(value, Mapping):
            _fail("snapshot_type_invalid", path)
        if len(value) > 64:
            _fail("snapshot_type_invalid", path)
        for key, item in value.items():
            if type(key) is not str or not key or len(key) > 128:
                _fail("snapshot_type_invalid", path)
            if type(item) is not str or len(item) > MAX_TEXT:
                _fail("snapshot_type_invalid", path)
        return
    _fail("snapshot_type_invalid", path)


# --------------------------------------------------------------------------- #
# 派生量：摘要、实体可匹配性、内容摘要
# --------------------------------------------------------------------------- #


def _compute_entity_matchable(
    entity_type: Any, entity_key: Any, entity_filters: Mapping[str, Any]
) -> bool:
    """运行期可匹配性：类型在可匹配词表且键非空。

    注意与合同 v2 §3.4 的**目标侧** ``matchable`` 不同：目标侧还要求 filters
    只含角色键。运行期 ``entity_filters`` 会带产品自己的 ``*_id`` 键（如
    ``item_id``），那是产品身份的一部分，不是“不可匹配”的理由；差异用
    ``entity_identity_matchable_nonrole_filters`` 码单独标记。
    """
    return (
        isinstance(entity_type, str)
        and entity_type in MATCHABLE_ENTITY_TYPES
        and isinstance(entity_key, str)
        and bool(entity_key)
    )


def _entity_code(entity_type: Any, entity_key: Any, filters: Mapping[str, Any], *, unit_resolved: bool) -> str:
    if not unit_resolved:
        return "entity_identity_unavailable"
    if entity_type is None:
        return "entity_identity_absent"
    if entity_type == "document":
        return "entity_identity_document_level"
    if _compute_entity_matchable(entity_type, entity_key, filters):
        if all(isinstance(key, str) and key in ENTITY_ROLE_NAMES for key in filters):
            return "entity_identity_matchable"
        return "entity_identity_matchable_nonrole_filters"
    return "entity_identity_nonmatchable"


def public_identity_summary(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """公开摘要：固定键、只含计数/布尔/固定枚举，绝不含 id/日期/hash/文本。"""
    rows = list(snapshot.get("record_identities") or ())
    temporal = dict(snapshot.get("effective_temporal") or {})
    usage = dict(snapshot.get("empty_use_scope_input") or {})
    use_layers = dict(usage.get("use_layers") or {})
    candidate_layers = dict(usage.get("candidate_layers") or {})
    runtime = dict(snapshot.get("runtime_identity") or {})
    versions = list(temporal.get("document_versions") or ())
    return {
        "schema_version": str(snapshot.get("schema_version")),
        "fixture_kind": str(snapshot.get("fixture_kind")),
        "turn_index": int(dict(snapshot.get("turn_ref") or {}).get("turn_index") or 0),
        "owner_attribution_present": bool(
            dict(snapshot.get("request_owner") or {}).get("availability") == "observed"
        ),
        "record_identity_total": len(rows),
        "record_level_count": sum(1 for row in rows if row.get("record_level") is True),
        "not_record_level_count": sum(1 for row in rows if row.get("record_level") is not True),
        "doc_code_unresolved_count": sum(
            1 for row in rows if row.get("code") == "runtime_doc_code_unresolved"
        ),
        "entity_matchable_count": sum(
            1 for row in rows if row.get("entity_matchable") is True
        ),
        "entity_document_level_count": sum(
            1 for row in rows if row.get("entity_type") == "document"
        ),
        "effective_temporal_status": str(temporal.get("availability")),
        "effective_as_of_present": temporal.get("as_of") is not None,
        "document_version_count": len(versions),
        "version_mismatch_count": sum(
            1 for row in versions if row.get("code") == "version_mismatch"
        ),
        "usage_layer_count": sum(
            1
            for layer in use_layers.values()
            if isinstance(layer, Mapping) and int(layer.get("count") or 0) > 0
        ),
        "candidate_layer_count": sum(
            1
            for layer in candidate_layers.values()
            if isinstance(layer, Mapping) and int(layer.get("count") or 0) > 0
        ),
        "empty_set_candidate": usage.get("empty_set_candidate") is True,
        "all_use_layers_observed": usage.get("all_use_layers_observed") is True,
        "runtime_unit_count": len(runtime.get("unit_ids") or ()),
        "runtime_id_count": (
            len(runtime.get("unit_ids") or ())
            + len(runtime.get("document_ids") or ())
            + len(runtime.get("version_ids") or ())
        ),
        "completeness_status": str(
            dict(snapshot.get("source_evidence") or {}).get("completeness_status")
        ),
        "record_codes": sorted({str(row.get("code")) for row in rows if row.get("code")}),
        "entity_codes": sorted(
            {str(row.get("entity_code")) for row in rows if row.get("entity_code")}
        ),
        "temporal_codes": [str(temporal.get("code"))] if temporal.get("code") else [],
        "empty_use_codes": [str(usage.get("code"))] if usage.get("code") else [],
    }


def _content_digest(payload: Mapping[str, Any]) -> str:
    body = {str(key): value for key, value in payload.items() if str(key) != "content_sha256"}
    return sha256_hex(canonical_json_bytes(body))


def _bindings_digest(bindings: Mapping[str, Any]) -> str:
    payload = {key: str(bindings[key]) for key in BINDING_KEYS}
    return sha256_hex(canonical_json_bytes(payload))


def _run_binding_digest(run_binding: Mapping[str, Any]) -> str:
    payload = {str(key): str(value) for key, value in run_binding.items()}
    return sha256_hex(canonical_json_bytes(payload))


# --------------------------------------------------------------------------- #
# 交叉不变量
# --------------------------------------------------------------------------- #


def _check_source_evidence_block(snapshot: Mapping[str, Any]) -> None:
    top_kind = snapshot.get("fixture_kind")
    source = dict(snapshot.get("source_evidence") or {})
    binding = dict(snapshot.get("binding") or {})
    if not (top_kind == source.get("fixture_kind") == binding.get("fixture_kind")):
        _fail("snapshot_fixture_binding_mismatch")
    expected_kind = SOURCE_EVIDENCE_VERSIONS.get(str(source.get("schema_version")))
    if expected_kind is None:
        _fail("snapshot_source_evidence_unsupported", "source_evidence.schema_version")
    if expected_kind != top_kind:
        _fail("snapshot_source_evidence_mismatch", "source_evidence.schema_version")


def _check_owner_block(snapshot: Mapping[str, Any]) -> None:
    owner = dict(snapshot.get("request_owner") or {})
    availability = owner.get("availability")
    if owner.get("auth_material_collected") is not False:
        _fail("snapshot_credential_material_forbidden", "request_owner.auth_material_collected")
    if availability == "observed":
        if not (_is_str(owner.get("user_ref")) and _is_str(owner.get("conversation_ref"))):
            _fail("snapshot_owner_inconsistent", "request_owner.user_ref")
        if owner.get("reason") is not None:
            _fail("snapshot_owner_inconsistent", "request_owner.reason")
        if owner.get("owner_source") != "turn_authenticated_user_id":
            _fail("snapshot_owner_inconsistent", "request_owner.owner_source")
    elif availability == "unavailable":
        if not _is_str(owner.get("reason")):
            _fail("snapshot_owner_inconsistent", "request_owner.reason")
        if owner.get("user_ref") is not None or owner.get("conversation_ref") is not None:
            _fail("snapshot_owner_inconsistent", "request_owner.user_ref")
        if owner.get("owner_source") != "unavailable":
            _fail("snapshot_owner_inconsistent", "request_owner.owner_source")
    else:
        _fail("snapshot_enum_invalid", "request_owner.availability")


def _check_record_identity_rows(snapshot: Mapping[str, Any]) -> None:
    rows = list(snapshot.get("record_identities") or ())
    refs = [str(row.get("source_ref")) for row in rows]
    if refs != sorted(set(refs)):
        _fail("snapshot_list_order_invalid", "record_identities")
    for index, row in enumerate(rows):
        path = f"record_identities[{index}]"
        if row.get("doc_code") is None and row.get("base_doc_code") is not None:
            _fail("snapshot_record_identity_inconsistent", path + ".base_doc_code")
        if row.get("doc_code") is not None and row.get("base_doc_code") is None:
            _fail("snapshot_record_identity_inconsistent", path + ".base_doc_code")
        if row.get("record_code") is not None and row.get("record_key") is None:
            _fail("snapshot_record_identity_inconsistent", path + ".record_code")
        record_level = row.get("record_level")
        code = row.get("code")
        if record_level is True:
            if row.get("locator_kind") != "record" or row.get("code") != "record_row_reverse_lookup":
                _fail("snapshot_record_identity_inconsistent", path + ".code")
            for name in ("doc_code", "base_doc_code", "sheet", "row", "record_key", "record_code"):
                if row.get(name) is None:
                    _fail("snapshot_record_identity_inconsistent", path + "." + name)
        elif record_level is False:
            if row.get("record_code") is not None or row.get("record_key") is not None:
                _fail("snapshot_record_identity_inconsistent", path + ".record_code")
            if code in {"record_row_reverse_lookup"}:
                _fail("snapshot_record_identity_inconsistent", path + ".code")
        else:
            _fail("snapshot_type_invalid", path + ".record_level")
        if row.get("code") == "record_row_reverse_lookup" and record_level is not True:
            _fail("snapshot_record_identity_inconsistent", path + ".code")
        if row.get("code") == "runtime_unit_not_record_level" and row.get("locator_kind") == "record":
            _fail("snapshot_record_identity_inconsistent", path + ".locator_kind")
        computed = _compute_entity_matchable(
            row.get("entity_type"), row.get("entity_key"), dict(row.get("entity_filters") or {})
        )
        if row.get("entity_matchable") is not computed:
            _fail("snapshot_entity_matchability_inconsistent", path + ".entity_matchable")
        expected_entity_code = _entity_code(
            row.get("entity_type"),
            row.get("entity_key"),
            dict(row.get("entity_filters") or {}),
            unit_resolved=row.get("code") != "runtime_unit_unresolved",
        )
        if row.get("entity_code") != expected_entity_code:
            _fail("snapshot_entity_code_inconsistent", path + ".entity_code")


def _check_summary(snapshot: Mapping[str, Any]) -> None:
    rows = list(snapshot.get("record_identities") or ())
    summary = dict(snapshot.get("record_identity_summary") or {})
    expected = _summary_block(rows)
    for key, value in expected.items():
        if summary.get(key) != value:
            _fail("snapshot_summary_mismatch", "record_identity_summary." + key)


def _check_temporal(snapshot: Mapping[str, Any]) -> None:
    temporal = dict(snapshot.get("effective_temporal") or {})
    availability = temporal.get("availability")
    as_of = temporal.get("as_of")
    source = temporal.get("as_of_source")
    if temporal.get("baseline_used_as_effective") is not False:
        _fail(
            "snapshot_effective_temporal_inconsistent",
            "effective_temporal.baseline_used_as_effective",
        )
    if availability == "observed":
        if as_of is None or temporal.get("reason") is not None:
            _fail("snapshot_effective_temporal_inconsistent", "effective_temporal.as_of")
        if source == "unavailable":
            _fail("snapshot_effective_temporal_inconsistent", "effective_temporal.as_of_source")
        if temporal.get("code") != "effective_temporal_observed":
            _fail("snapshot_effective_temporal_inconsistent", "effective_temporal.code")
    elif availability == "partial":
        if as_of is None or not _is_str(temporal.get("reason")):
            _fail("snapshot_effective_temporal_inconsistent", "effective_temporal.reason")
        if temporal.get("code") != "effective_temporal_partial":
            _fail("snapshot_effective_temporal_inconsistent", "effective_temporal.code")
    elif availability == "not_observed":
        if as_of is not None or source != "unavailable":
            _fail("snapshot_effective_temporal_inconsistent", "effective_temporal.as_of")
        if not _is_str(temporal.get("reason")):
            _fail("snapshot_effective_temporal_inconsistent", "effective_temporal.reason")
        if temporal.get("code") not in {
            "effective_temporal_not_observed",
            "effective_as_of_not_observed",
            "effective_as_of_ambiguous",
        }:
            _fail("snapshot_effective_temporal_inconsistent", "effective_temporal.code")
    else:
        _fail("snapshot_enum_invalid", "effective_temporal.availability")
    for index, row in enumerate(temporal.get("document_versions") or ()):
        path = f"effective_temporal.document_versions[{index}]"
        runtime = row.get("runtime_version_number")
        product = row.get("product_version_number")
        code = row.get("code")
        if code == "version_observed":
            if runtime is None:
                _fail("snapshot_document_version_inconsistent", path + ".runtime_version_number")
        elif code == "version_mismatch":
            if runtime is None or product is None or runtime == product:
                _fail("snapshot_document_version_inconsistent", path + ".code")
        elif code == "version_unresolved":
            if runtime is not None:
                _fail("snapshot_document_version_inconsistent", path + ".code")


def _check_empty_use_input(snapshot: Mapping[str, Any]) -> None:
    usage = dict(snapshot.get("empty_use_scope_input") or {})
    layers = dict(usage.get("use_layers") or {})
    candidates = dict(usage.get("candidate_layers") or {})
    observed_flags = []
    total = 0
    for name in USE_LAYER_NAMES:
        layer = dict(layers.get(name) or {})
        count = layer.get("count")
        refs = layer.get("refs") or []
        observed_flags.append(layer.get("observed") is True)
        if name == "direct_rag_fact_count":
            if refs != []:
                _fail(
                    "snapshot_empty_use_input_inconsistent",
                    f"empty_use_scope_input.use_layers.{name}.refs",
                )
        elif count != len(refs):
            _fail(
                "snapshot_empty_use_input_inconsistent",
                f"empty_use_scope_input.use_layers.{name}.count",
            )
        if layer.get("observed") is False and count != 0:
            _fail(
                "snapshot_empty_use_input_inconsistent",
                f"empty_use_scope_input.use_layers.{name}.count",
            )
        if type(count) is int:
            total += count
    all_observed = all(observed_flags)
    if usage.get("all_use_layers_observed") is not all_observed:
        _fail("snapshot_empty_use_input_inconsistent", "empty_use_scope_input.all_use_layers_observed")
    empty = all_observed and total == 0
    code = usage.get("code")
    turn_status = usage.get("turn_status")
    if code == "empty_use_input_malformed_event":
        if usage.get("empty_set_candidate") is not False:
            _fail(
                "snapshot_empty_use_input_inconsistent",
                "empty_use_scope_input.empty_set_candidate",
            )
    else:
        if usage.get("empty_set_candidate") is not empty:
            _fail(
                "snapshot_empty_use_input_inconsistent",
                "empty_use_scope_input.empty_set_candidate",
            )
        if turn_status in {"partial", "unavailable"}:
            if code != "empty_use_input_turn_partial":
                _fail("snapshot_empty_use_input_inconsistent", "empty_use_scope_input.code")
        elif empty:
            if code != "empty_use_input_complete_empty":
                _fail("snapshot_empty_use_input_inconsistent", "empty_use_scope_input.code")
        elif total > 0:
            if code != "empty_use_input_nonempty":
                _fail("snapshot_empty_use_input_inconsistent", "empty_use_scope_input.code")
        elif code != "empty_use_input_layers_not_observed":
            _fail("snapshot_empty_use_input_inconsistent", "empty_use_scope_input.code")
    for name in CANDIDATE_LAYER_NAMES:
        layer = dict(candidates.get(name) or {})
        if layer.get("count") != len(layer.get("refs") or []):
            _fail(
                "snapshot_empty_use_input_inconsistent",
                f"empty_use_scope_input.candidate_layers.{name}.count",
            )
    if usage.get("turn_status") == "unavailable" and not _is_str(usage.get("reason")):
        _fail("snapshot_empty_use_input_inconsistent", "empty_use_scope_input.reason")


def _check_runtime_identity(snapshot: Mapping[str, Any]) -> None:
    runtime = dict(snapshot.get("runtime_identity") or {})
    if runtime.get("declared") is not True:
        _fail("snapshot_runtime_identity_inconsistent", "runtime_identity.declared")
    rows = list(snapshot.get("record_identities") or ())
    refs = sorted(str(row.get("source_ref")) for row in rows)
    if list(runtime.get("unit_ids") or ()) != refs:
        _fail("snapshot_runtime_identity_inconsistent", "runtime_identity.unit_ids")
    unresolved = sorted(
        str(row.get("source_ref"))
        for row in rows
        if row.get("code") == "runtime_unit_unresolved"
    )
    if list(runtime.get("unresolved_unit_ids") or ()) != unresolved:
        _fail("snapshot_runtime_identity_inconsistent", "runtime_identity.unresolved_unit_ids")
    counts = dict(runtime.get("counts") or {})
    if counts.get("units") != len(refs):
        _fail("snapshot_runtime_identity_inconsistent", "runtime_identity.counts.units")
    if counts.get("unresolved") != len(unresolved):
        _fail("snapshot_runtime_identity_inconsistent", "runtime_identity.counts.unresolved")
    if counts.get("documents") != len(runtime.get("document_ids") or ()):
        _fail("snapshot_runtime_identity_inconsistent", "runtime_identity.counts.documents")
    if counts.get("versions") != len(runtime.get("version_ids") or ()):
        _fail("snapshot_runtime_identity_inconsistent", "runtime_identity.counts.versions")


def _check_public_boundary(snapshot: Mapping[str, Any]) -> None:
    boundary = dict(snapshot.get("public_boundary") or {})
    if boundary.get("runtime_ids_only_in_declared_blocks") is not True:
        _fail(
            "snapshot_public_boundary_violation",
            "public_boundary.runtime_ids_only_in_declared_blocks",
        )
    summary = public_identity_summary(snapshot)
    if sorted(summary) != list(PUBLIC_SUMMARY_KEYS):
        _fail("snapshot_public_boundary_violation", "public_boundary.public_summary_keys")
    if list(boundary.get("public_summary_keys") or ()) != list(PUBLIC_SUMMARY_KEYS):
        _fail("snapshot_public_boundary_violation", "public_boundary.public_summary_keys")
    if boundary.get("public_summary_sha256") != sha256_hex(canonical_json_bytes(summary)):
        _fail("snapshot_public_boundary_violation", "public_boundary.public_summary_sha256")
    # 公开摘要绝不出现运行期 id 键或明文凭证形态。
    _scan_forbidden_keys(summary, "public_summary")
    _scan_secret_values(summary, "public_summary")
    for key in summary:
        if str(key).lower() in RUNTIME_ID_KEYS:
            _fail("snapshot_public_boundary_violation", "public_summary." + str(key))


def _check_bindings(
    snapshot: Mapping[str, Any], expected_bindings: Mapping[str, Any] | None
) -> None:
    binding = dict(snapshot.get("binding") or {})
    if expected_bindings is None:
        return
    if any(key not in expected_bindings for key in BINDING_KEYS):
        _fail("snapshot_expected_bindings_invalid")
    if binding.get("bindings_sha256") != _bindings_digest(expected_bindings):
        _fail("snapshot_run_binding_mismatch", "binding.bindings_sha256")
    if str(binding.get("run_id")) != str(expected_bindings["run_id"]):
        _fail("snapshot_run_binding_mismatch", "binding.run_id")
    if str(binding.get("plan_sha256")) != str(expected_bindings["plan_sha256"]):
        _fail("snapshot_run_binding_mismatch", "binding.plan_sha256")
    if str(binding.get("scenario_id")) != str(expected_bindings["scenario_id"]):
        _fail("snapshot_run_binding_mismatch", "binding.scenario_id")
    if str(binding.get("fixture_kind")) != str(expected_bindings["fixture_kind"]):
        _fail("snapshot_run_binding_mismatch", "binding.fixture_kind")


def _check_turn_ref(snapshot: Mapping[str, Any], expected_turn: Mapping[str, Any] | None) -> None:
    if expected_turn is None:
        return
    turn_ref = dict(snapshot.get("turn_ref") or {})
    for key in ("turn_index", "client_request_id", "conversation_id"):
        if key not in expected_turn:
            _fail("snapshot_turn_binding_mismatch", "expected_turn." + key)
        if turn_ref.get(key) != expected_turn[key]:
            _fail("snapshot_turn_binding_mismatch", "turn_ref." + key)


def _check_source_evidence(
    snapshot: Mapping[str, Any], source_evidence: Mapping[str, Any] | None
) -> None:
    if source_evidence is None:
        return
    source = dict(snapshot.get("source_evidence") or {})
    try:
        digest = sha256_hex(canonical_json_bytes(dict(source_evidence)))
    except EvidenceIOError:
        _fail("snapshot_source_evidence_invalid")
    if digest != source.get("sha256"):
        _fail("snapshot_source_evidence_mismatch", "source_evidence.sha256")
    if str(source_evidence.get("schema_version")) != str(source.get("schema_version")):
        _fail("snapshot_source_evidence_mismatch", "source_evidence.schema_version")
    if str(source_evidence.get("fixture_kind")) != str(source.get("fixture_kind")):
        _fail("snapshot_source_evidence_mismatch", "source_evidence.fixture_kind")


def validate_identity_snapshot(
    payload: Any,
    *,
    expected_bindings: Mapping[str, Any] | None = None,
    expected_turn: Mapping[str, Any] | None = None,
    source_evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """严格校验快照载荷；任一条不成立 → 固定 fail-closed 码。"""
    if not isinstance(payload, Mapping):
        _fail("snapshot_envelope_invalid")
    if payload.get("contract_version") != CONTRACT_VERSION:
        _fail("snapshot_contract_version_invalid", "contract_version")
    if payload.get("schema_version") != SNAPSHOT_SCHEMA_VERSION:
        _fail("snapshot_schema_version_invalid", "schema_version")
    _scan_forbidden_keys(payload, "")
    _scan_secret_values(payload, "")
    _walk(payload, _fs("object", fields=SNAPSHOT_SCHEMA), "")
    _check_source_evidence_block(payload)
    _check_owner_block(payload)
    _check_record_identity_rows(payload)
    _check_summary(payload)
    _check_temporal(payload)
    _check_empty_use_input(payload)
    _check_runtime_identity(payload)
    _check_public_boundary(payload)
    if payload.get("content_sha256") != _content_digest(payload):
        _fail("snapshot_content_digest_mismatch", "content_sha256")
    _check_bindings(payload, expected_bindings)
    _check_turn_ref(payload, expected_turn)
    _check_source_evidence(payload, source_evidence)
    return dict(payload)


def validate_snapshot_manifest(
    payload: Any, *, expected_bindings: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        _fail("snapshot_envelope_invalid")
    _scan_forbidden_keys(payload, "")
    _scan_secret_values(payload, "")
    _walk(payload, _fs("object", fields=MANIFEST_SCHEMA), "")
    if payload.get("schema_version") != SNAPSHOT_MANIFEST_SCHEMA_VERSION:
        _fail("snapshot_schema_version_invalid", "schema_version")
    if payload.get("content_sha256") != _content_digest(payload):
        _fail("snapshot_content_digest_mismatch", "content_sha256")
    if payload.get("snapshot_count") != len(payload.get("turns") or ()):
        _fail("snapshot_manifest_count_mismatch", "snapshot_count")
    if expected_bindings is not None:
        if any(key not in expected_bindings for key in BINDING_KEYS):
            _fail("snapshot_expected_bindings_invalid")
        if payload.get("bindings_sha256") != _bindings_digest(expected_bindings):
            _fail("snapshot_manifest_binding_mismatch", "bindings_sha256")
    indexes = [int(row.get("turn_index")) for row in payload.get("turns") or ()]
    if indexes != sorted(set(indexes)):
        _fail("snapshot_list_order_invalid", "turns")
    return dict(payload)


# --------------------------------------------------------------------------- #
# 字段表（报告与文档共用；机器可读）
# --------------------------------------------------------------------------- #


def identity_field_table() -> tuple[dict[str, Any], ...]:
    """展开声明式 schema 为字段表：路径/类型/必填/可空/缺失固定码。"""
    rows: list[dict[str, Any]] = []

    def walk(spec: FieldSpec, path: str) -> None:
        if spec.kind == "object":
            for name, child in (spec.fields or {}).items():
                child_path = f"{path}.{name}" if path else name
                rows.append(_field_row(child, child_path))
                walk(child, child_path)
        elif spec.kind == "list_object":
            assert spec.item is not None
            item_path = path + "[]"
            rows.append(_field_row(spec.item, item_path))
            walk(spec.item, item_path)
        elif spec.kind == "list_str":
            # 列表字段行已由父对象循环登记；这里只递归，不重复登记。
            return

    walk(_fs("object", fields=SNAPSHOT_SCHEMA), "")
    return tuple(rows)


def _field_row(spec: FieldSpec, path: str) -> dict[str, Any]:
    if spec.kind == "enum":
        type_name = "enum(" + "|".join(spec.enum or ()) + ")"
    elif spec.kind in {"list_str", "list_object"}:
        type_name = "list"
    elif spec.kind == "map_str":
        type_name = "map[str,str]"
    else:
        type_name = spec.kind
    return {
        "path": path,
        "type": type_name,
        "required": True,
        "nullable": bool(spec.nullable),
        "missing_code": f"snapshot_missing_field:{path}",
    }


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --------------------------------------------------------------------------- #
# 构造（采集点）：只消费冻结 v0.3 回合证据的**已发布**字段与事件协议
# --------------------------------------------------------------------------- #


def _safe_component(value: str) -> str:
    text = "".join(char for char in str(value) if char.isalnum() or char in {"-", "_"})[:64]
    return text or "snapshot"


def _payloads(events: Sequence[Any], kind: str) -> list[Mapping[str, Any]]:
    rows: list[Mapping[str, Any]] = []
    for event in events:
        if isinstance(event, Mapping) and str(event.get("kind")) == kind:
            payload = event.get("payload")
            if isinstance(payload, Mapping):
                rows.append(payload)
    return rows


def _valid_date(value: Any) -> str | None:
    return str(value) if _is_iso_date(value) else None


def _doc_code_for(name: Any, doc_code_index: Mapping[str, str]) -> str | None:
    if not isinstance(name, str) or not name:
        return None
    return doc_code_index.get(name)


def _base_doc_code(doc_code: str | None, aliases: Mapping[str, str]) -> str | None:
    if doc_code is None:
        return None
    return aliases.get(doc_code, doc_code)


def _extract_use_layers(
    events: Sequence[Any], projection: Mapping[str, Any]
) -> tuple[dict[str, dict[str, Any]], bool]:
    refs: dict[str, set[str]] = {name: set() for name in USE_LAYER_NAMES}
    observed: dict[str, bool] = {name: False for name in USE_LAYER_NAMES}
    fact_count = 0
    malformed = False

    def add(name: str, values: Any) -> None:
        nonlocal malformed
        if values is None:
            return
        if not isinstance(values, list):
            malformed = True
            return
        for value in values:
            if isinstance(value, str) and value:
                refs[name].add(value)
            else:
                malformed = True

    for event in events:
        if not isinstance(event, Mapping):
            malformed = True
            continue
        kind = str(event.get("kind"))
        payload = event.get("payload")
        if kind not in {
            "model_input",
            "model_output",
            "direct_rag_answer",
            "answer_result",
            "commit_observed",
            "entity_inheritance",
        }:
            continue
        if not isinstance(payload, Mapping):
            malformed = True
            continue
        if kind == "model_input":
            observed["model_evidence"] = True
            evidence = payload.get("evidence")
            if not isinstance(evidence, list):
                malformed = True
                continue
            for row in evidence:
                if not isinstance(row, Mapping):
                    malformed = True
                    continue
                value = row.get("source_id")
                if isinstance(value, str) and value:
                    refs["model_evidence"].add(value)
                else:
                    malformed = True
        elif kind == "model_output":
            observed["model_output_sources"] = True
            add("model_output_sources", payload.get("source_ids"))
        elif kind == "direct_rag_answer":
            observed["direct_rag_facts"] = True
            observed["direct_rag_citations"] = True
            observed["direct_rag_fact_count"] = True
            facts = payload.get("facts")
            if not isinstance(facts, list):
                malformed = True
            else:
                for row in facts:
                    if not isinstance(row, Mapping):
                        malformed = True
                        continue
                    value = row.get("source_unit_id")
                    if isinstance(value, str) and value:
                        refs["direct_rag_facts"].add(value)
                    else:
                        malformed = True
            add("direct_rag_citations", payload.get("cited_unit_ids"))
            count_value = payload.get("fact_count")
            if type(count_value) is int and count_value >= 0:
                fact_count += count_value
            else:
                malformed = True
        elif kind in {"answer_result", "commit_observed"}:
            name = (
                "answer_result_sources"
                if kind == "answer_result"
                else "commit_observed_sources"
            )
            observed[name] = True
            add(name, payload.get("source_ids"))
        else:  # entity_inheritance
            observed["entity_inheritance"] = True
            value = payload.get("source_unit_id")
            if isinstance(value, str) and value:
                refs["entity_inheritance"].add(value)
            else:
                malformed = True

    message_sources = projection.get("message_sources")
    projection_errors = [str(item) for item in projection.get("errors") or ()]
    projection_usable = not any(
        code in projection_errors
        for code in ("projection_id_invalid", "conversation_missing", "request_missing")
    )
    if isinstance(message_sources, list) and projection_usable:
        observed["projection_message_sources"] = True
        for row in message_sources:
            if not isinstance(row, Mapping):
                malformed = True
                continue
            value = row.get("source_id")
            if isinstance(value, str) and value:
                refs["projection_message_sources"].add(value)
            else:
                malformed = True
    elif not projection_usable:
        observed["projection_message_sources"] = False
    else:
        malformed = True

    layers: dict[str, dict[str, Any]] = {}
    for name in USE_LAYER_NAMES:
        values = sorted(refs[name])
        count = fact_count if name == "direct_rag_fact_count" else len(values)
        layers[name] = {"observed": observed[name], "count": count, "refs": values}
    return layers, malformed


def _extract_candidate_layers(
    events: Sequence[Any], projection: Mapping[str, Any]
) -> tuple[dict[str, dict[str, Any]], bool]:
    refs: dict[str, set[str]] = {name: set() for name in CANDIDATE_LAYER_NAMES}
    observed: dict[str, bool] = {name: False for name in CANDIDATE_LAYER_NAMES}
    truncated: dict[str, bool] = {name: False for name in CANDIDATE_LAYER_NAMES}
    malformed = False

    def add(name: str, values: Any) -> None:
        nonlocal malformed
        if values is None:
            return
        if not isinstance(values, list):
            malformed = True
            return
        for value in values:
            if isinstance(value, str) and value:
                refs[name].add(value)
            else:
                malformed = True

    for payload in _payloads(events, "retrieval_observed"):
        observed["retrieval_observed"] = True
        add("retrieval_observed", payload.get("unit_ids"))
        if payload.get("truncated") is True:
            truncated["retrieval_observed"] = True
    for kind in ("query_state_observed", "query_state_saved", "query_state_cleared"):
        for payload in _payloads(events, kind):
            observed["query_state_candidates"] = True
            state = payload.get("state_json")
            if not isinstance(state, Mapping):
                malformed = True
                continue
            if state:
                add("query_state_candidates", state.get("candidates"))
    query_states = projection.get("query_states")
    if isinstance(query_states, list) and projection.get("query_states_available") is True:
        observed["projection_query_state_candidates"] = True
        for row in query_states:
            if not isinstance(row, Mapping):
                malformed = True
                continue
            state = row.get("state_json")
            if not isinstance(state, Mapping):
                malformed = True
                continue
            if state:
                add("projection_query_state_candidates", state.get("candidates"))
    elif projection.get("query_states_available") is False:
        observed["projection_query_state_candidates"] = False
    else:
        malformed = True

    layers: dict[str, dict[str, Any]] = {}
    for name in CANDIDATE_LAYER_NAMES:
        layers[name] = {
            "observed": observed[name],
            "count": len(refs[name]),
            "refs": sorted(refs[name]),
            "truncated": truncated[name],
        }
    return layers, malformed


def _summary_block(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "total": len(rows),
        "record_level": sum(1 for row in rows if row.get("record_level") is True),
        "not_record_level": sum(1 for row in rows if row.get("record_level") is not True),
        "doc_code_unresolved": sum(
            1 for row in rows if row.get("code") == "runtime_doc_code_unresolved"
        ),
        "entity_matchable": sum(
            1 for row in rows if row.get("entity_matchable") is True
        ),
        "entity_document_level": sum(
            1 for row in rows if row.get("entity_type") == "document"
        ),
        "unresolved_units": sum(
            1 for row in rows if row.get("code") == "runtime_unit_unresolved"
        ),
        "doc_codes": sorted(
            {
                str(row.get("base_doc_code"))
                for row in rows
                if row.get("base_doc_code") is not None
            }
        ),
    }


def _locator_kind(unit: Mapping[str, Any]) -> tuple[str, bool]:
    locator = unit.get("locator") if isinstance(unit.get("locator"), Mapping) else {}
    kind = str(unit.get("kind") or "")
    sheet = locator.get("sheet")
    row = locator.get("row")
    if kind == "table_row" and isinstance(sheet, str) and sheet and type(row) is int:
        return "record", True
    if "page" in locator:
        return "page", False
    if "heading" in locator or kind in {"paragraph", "text", "table_row"}:
        return "heading", False
    if locator:
        return "other", False
    return "none", False


def _normalize_record_index(
    record_index: Sequence[Mapping[str, Any]] | None,
) -> dict[tuple[str, str, int], dict[str, str | None]]:
    index: dict[tuple[str, str, int], dict[str, str | None]] = {}
    for item in record_index or ():
        if not isinstance(item, Mapping):
            _fail("snapshot_record_index_invalid")
        doc_code = item.get("doc_code")
        sheet = item.get("sheet")
        row = item.get("row")
        record_key = item.get("record_key")
        if not (isinstance(doc_code, str) and doc_code):
            _fail("snapshot_record_index_invalid", "doc_code")
        if not (isinstance(sheet, str) and sheet):
            _fail("snapshot_record_index_invalid", "sheet")
        if type(row) is not int or row < 1:
            _fail("snapshot_record_index_invalid", "row")
        if not (isinstance(record_key, str) and record_key):
            _fail("snapshot_record_index_invalid", "record_key")
        label = item.get("business_version")
        if label is not None and not (isinstance(label, str) and label):
            _fail("snapshot_record_index_invalid", "business_version")
        key = (doc_code, sheet, row)
        value = {"record_key": record_key, "business_version": label}
        if key in index and index[key] != value:
            _fail("snapshot_record_index_conflict", f"{doc_code}|{sheet}|{row}")
        index[key] = value
    return index


def _normalize_doc_code_index(doc_code_index: Mapping[str, str] | None) -> dict[str, str]:
    if doc_code_index is None:
        return {}
    if not isinstance(doc_code_index, Mapping):
        _fail("snapshot_doc_code_index_invalid")
    resolved: dict[str, str] = {}
    for name, code in doc_code_index.items():
        if not (isinstance(name, str) and name):
            _fail("snapshot_doc_code_index_invalid", "name")
        if not (isinstance(code, str) and code):
            _fail("snapshot_doc_code_index_invalid", "doc_code")
        resolved[name] = code
    return resolved


def _normalize_aliases(aliases: Mapping[str, str] | None) -> dict[str, str]:
    resolved: dict[str, str] = {}
    for code, base in (aliases or {}).items():
        if not (isinstance(code, str) and code):
            _fail("snapshot_doc_code_index_invalid", "alias")
        if not (isinstance(base, str) and base):
            _fail("snapshot_doc_code_index_invalid", "base_doc_code")
        resolved[code] = base
    return resolved


def _normalize_business_versions(
    versions: Mapping[str, str] | None,
) -> dict[str, str]:
    resolved: dict[str, str] = {}
    for code, label in (versions or {}).items():
        if not (isinstance(code, str) and code):
            _fail("snapshot_doc_code_index_invalid", "business_version_key")
        if not (isinstance(label, str) and label):
            _fail("snapshot_doc_code_index_invalid", "business_version_label")
        resolved[code] = label
    return resolved


def build_identity_snapshot(
    *,
    turn_evidence: Mapping[str, Any],
    bindings: Mapping[str, Any],
    doc_code_index: Mapping[str, str] | None = None,
    record_index: Sequence[Mapping[str, Any]] | None = None,
    doc_code_aliases: Mapping[str, str] | None = None,
    business_versions: Mapping[str, str] | None = None,
    captured_utc: str | None = None,
) -> dict[str, Any]:
    """从冻结 v0.3 回合证据 + 公开投影索引构造身份快照（纯函数、无 IO、零调用）。"""
    if not isinstance(turn_evidence, Mapping):
        _fail("snapshot_evidence_not_supported")
    evidence = dict(turn_evidence)
    evidence_version = str(evidence.get("schema_version"))
    expected_kind = SOURCE_EVIDENCE_VERSIONS.get(evidence_version)
    if expected_kind is None:
        _fail("snapshot_source_evidence_unsupported", "source_evidence.schema_version")
    if not isinstance(bindings, Mapping):
        _fail("snapshot_bindings_incomplete")
    if any(key not in bindings for key in BINDING_KEYS):
        _fail("snapshot_bindings_incomplete")
    normalized_bindings = {key: str(bindings[key]) for key in BINDING_KEYS}
    if normalized_bindings["fixture_kind"] != expected_kind:
        _fail("snapshot_fixture_binding_mismatch", "bindings.fixture_kind")
    try:
        validate_turn_evidence(
            evidence, expected_bindings=normalized_bindings, phase="pre_write"
        )
    except EvidenceIOError:
        _fail("snapshot_source_evidence_invalid")
    fixture_kind = expected_kind

    doc_index = _normalize_doc_code_index(doc_code_index)
    aliases = _normalize_aliases(doc_code_aliases)
    record_lookup = _normalize_record_index(record_index)
    version_labels = _normalize_business_versions(business_versions)

    turn = dict(evidence.get("turn") or {})
    capture = dict(evidence.get("capture") or {})
    projection = dict(evidence.get("db_projection") or {})
    completeness = dict(evidence.get("completeness") or {})
    if str(completeness.get("status")) == "replayed":
        # 重放事件不是“当次实际运行”，不能承载运行期身份快照。
        _fail(
            "snapshot_source_evidence_unsupported",
            "source_evidence.completeness_status",
        )
    runtime = dict(evidence.get("runtime_snapshot") or {})
    product = dict(runtime.get("product_response") or {})
    usage = dict(runtime.get("retrieval_use") or {})
    events = list(capture.get("events") or ())

    run_binding = evidence.get("run_binding")
    run_binding_sha256: str | None = None
    business_date_declared: str | None = None
    if isinstance(run_binding, Mapping):
        run_binding_sha256 = _run_binding_digest(run_binding)
        business_date_declared = _valid_date(run_binding.get("business_date"))
    if fixture_kind == "live_h2" and run_binding_sha256 is None:
        _fail("snapshot_run_binding_absent", "binding.run_binding_sha256")
    if fixture_kind == "local_mock" and run_binding_sha256 is not None:
        _fail("snapshot_run_binding_unexpected", "binding.run_binding_sha256")

    source_evidence = {
        "sha256": sha256_hex(canonical_json_bytes(evidence)),
        "schema_version": evidence_version,
        "fixture_kind": fixture_kind,
        "completeness_status": str(completeness.get("status")),
    }
    binding = {
        "run_id": normalized_bindings["run_id"],
        "plan_sha256": normalized_bindings["plan_sha256"],
        "scenario_id": normalized_bindings["scenario_id"],
        "fixture_kind": normalized_bindings["fixture_kind"],
        "bindings_sha256": _bindings_digest(normalized_bindings),
        "run_binding_sha256": run_binding_sha256,
        "business_date_declared": business_date_declared,
    }
    turn_ref = {
        "turn_index": int(turn.get("turn_index")),
        "client_request_id": str(turn.get("client_request_id")),
        "conversation_id": str(turn.get("conversation_id")),
        "question_sha256": str(turn.get("question_sha256")),
        "pre_revision": turn.get("pre_revision"),
        "post_revision": turn.get("post_revision"),
        "capture_revision": turn.get("capture_revision"),
        "response_kind": None
        if product.get("kind") is None
        else str(product.get("kind")),
        "http_status": turn.get("http_status"),
        "timed_out": bool(turn.get("timed_out")),
    }

    owner_id = turn.get("authenticated_user_id")
    conversation_id = turn.get("conversation_id")
    if isinstance(owner_id, str) and owner_id and isinstance(conversation_id, str) and conversation_id:
        request_owner = {
            "availability": "observed",
            "reason": None,
            "user_ref": owner_id,
            "conversation_ref": conversation_id,
            "owner_source": "turn_authenticated_user_id",
            "auth_material_collected": False,
        }
    else:
        request_owner = {
            "availability": "unavailable",
            "reason": "owner_identity_not_observed",
            "user_ref": None,
            "conversation_ref": None,
            "owner_source": "unavailable",
            "auth_material_collected": False,
        }

    use_layers, use_malformed = _extract_use_layers(events, projection)
    candidate_layers, candidate_malformed = _extract_candidate_layers(events, projection)
    malformed = use_malformed or candidate_malformed

    # 使用层 ref -> 层清单（记录身份与 runtime_identity 共用同一集合）。
    layers_by_ref: dict[str, set[str]] = {}
    for name in USE_LAYER_NAMES:
        if name == "direct_rag_fact_count":
            continue
        for ref in use_layers[name]["refs"]:
            layers_by_ref.setdefault(ref, set()).add(name)
    used_refs = sorted(layers_by_ref)

    unit_rows = {
        str(unit.get("unit_id")): unit
        for unit in projection.get("units") or ()
        if isinstance(unit, Mapping)
    }
    product_versions: dict[str, int] = {}
    for row in product.get("sources") or ():
        if isinstance(row, Mapping) and row.get("source_id") is not None:
            if type(row.get("version_number")) is int:
                product_versions[str(row.get("source_id"))] = int(row["version_number"])

    identity_rows: list[dict[str, Any]] = []
    version_rows: list[dict[str, Any]] = []
    for ref in used_refs:
        unit = unit_rows.get(ref)
        layers = sorted(layers_by_ref[ref])
        if unit is None:
            identity_rows.append(
                {
                    "source_ref": ref,
                    "layers": layers,
                    "unit_kind": "unresolved",
                    "locator_kind": "unavailable",
                    "doc_code": None,
                    "base_doc_code": None,
                    "sheet": None,
                    "row": None,
                    "record_key": None,
                    "record_code": None,
                    "business_version": None,
                    "version_number": None,
                    "record_level": False,
                    "entity_type": None,
                    "entity_key": None,
                    "entity_filters": {},
                    "entity_matchable": False,
                    "code": "runtime_unit_unresolved",
                    "entity_code": "entity_identity_unavailable",
                }
            )
            version_rows.append(
                {
                    "source_ref": ref,
                    "doc_code": None,
                    "version_label": None,
                    "runtime_version_number": None,
                    "product_version_number": product_versions.get(ref),
                    "code": "version_unresolved",
                }
            )
            continue
        locator_kind, structural_record = _locator_kind(unit)
        locator = dict(unit.get("locator") or {})
        doc_code = _doc_code_for(unit.get("document_name"), doc_index)
        base_doc_code = _base_doc_code(doc_code, aliases)
        sheet = locator.get("sheet") if isinstance(locator.get("sheet"), str) else None
        row_value = locator.get("row") if type(locator.get("row")) is int else None
        record_key: str | None = None
        record_code: str | None = None
        record_level = False
        business_version: str | None = None
        if not structural_record:
            code = "runtime_unit_not_record_level"
            sheet = None if locator_kind != "record" else sheet
            row_value = None if locator_kind != "record" else row_value
        elif doc_code is None:
            code = "runtime_doc_code_unresolved"
        else:
            entry = record_lookup.get((str(base_doc_code), str(sheet), int(row_value)))
            if entry is None:
                code = "record_row_not_in_record_index"
            else:
                record_key = str(entry["record_key"])
                record_code = record_key
                record_level = True
                business_version = entry.get("business_version") or version_labels.get(
                    str(base_doc_code)
                )
                code = "record_row_reverse_lookup"
        if business_version is None and base_doc_code is not None:
            business_version = version_labels.get(str(base_doc_code))
        version_number = unit.get("version_number")
        if type(version_number) is not int:
            version_number = None
        if not record_level:
            record_key = None
            record_code = None
        entity_type = unit.get("entity_type")
        entity_key = unit.get("entity_key")
        entity_filters = {
            str(key): str(value)
            for key, value in dict(unit.get("entity_filters") or {}).items()
        }
        entity_matchable = _compute_entity_matchable(
            entity_type, entity_key, entity_filters
        )
        identity_rows.append(
            {
                "source_ref": ref,
                "layers": layers,
                "unit_kind": str(unit.get("kind") or "unknown"),
                "locator_kind": locator_kind,
                "doc_code": doc_code,
                "base_doc_code": base_doc_code,
                "sheet": sheet,
                "row": row_value,
                "record_key": record_key,
                "record_code": record_code,
                "business_version": business_version,
                "version_number": version_number,
                "record_level": record_level,
                "entity_type": None if entity_type is None else str(entity_type),
                "entity_key": None if entity_key is None else str(entity_key),
                "entity_filters": entity_filters,
                "entity_matchable": entity_matchable,
                "code": code,
                "entity_code": _entity_code(
                    entity_type, entity_key, entity_filters, unit_resolved=True
                ),
            }
        )
        product_version = product_versions.get(ref)
        if version_number is None:
            version_code = "version_unresolved"
        elif product_version is not None and product_version != version_number:
            version_code = "version_mismatch"
        else:
            version_code = "version_observed"
        version_rows.append(
            {
                "source_ref": ref,
                "doc_code": doc_code,
                "version_label": business_version,
                "runtime_version_number": version_number,
                "product_version_number": product_version,
                "code": version_code,
            }
        )

    identity_summary = _summary_block(identity_rows)

    plan_rows = _payloads(events, "plan_observed")
    plan_available = len(plan_rows) == 1
    plan_payload = plan_rows[0] if plan_available else {}
    as_of = _valid_date(plan_payload.get("as_of"))
    as_of_source = "plan_observed" if as_of is not None else "unavailable"
    if as_of is None:
        fallback = _valid_date(projection.get("rag_business_date"))
        if fallback is not None:
            as_of = fallback
            as_of_source = "rag_business_date"
    if as_of is None:
        availability = "not_observed"
        reason = (
            "effective_as_of_ambiguous"
            if len(plan_rows) > 1
            else "effective_as_of_not_observed"
        )
        temporal_code = reason
    else:
        mismatch = any(row["code"] == "version_mismatch" for row in version_rows)
        unresolved = any(row["code"] == "version_unresolved" for row in version_rows)
        if mismatch:
            availability = "partial"
            reason = "document_version_mismatch"
            temporal_code = "effective_temporal_partial"
        elif unresolved:
            availability = "partial"
            reason = "document_version_unresolved"
            temporal_code = "effective_temporal_partial"
        else:
            availability = "observed"
            reason = None
            temporal_code = "effective_temporal_observed"
    effective_temporal = {
        "availability": availability,
        "reason": reason,
        "as_of": as_of,
        "as_of_source": as_of_source,
        "observed_from": "db_projection_units",
        "include_future": bool(plan_payload["include_future"])
        if type(plan_payload.get("include_future")) is bool
        else None,
        "enumerate": bool(plan_payload["enumerate"])
        if type(plan_payload.get("enumerate")) is bool
        else None,
        "document_versions": version_rows,
        "declared_baseline_business_date": business_date_declared,
        "baseline_used_as_effective": False,
        "code": temporal_code,
    }

    usage_status = str(usage.get("availability") or "unavailable")
    usage_reason = usage.get("reason")
    if usage_reason is None and usage_status in {"partial", "unavailable"}:
        usage_reason = "retrieval_use_unavailable"
    if malformed:
        empty_code = "empty_use_input_malformed_event"
    elif usage_status in {"partial", "unavailable"}:
        empty_code = "empty_use_input_turn_partial"
    elif all(layer["observed"] for layer in use_layers.values()) and not any(
        layer["count"] for layer in use_layers.values()
    ):
        empty_code = "empty_use_input_complete_empty"
    elif any(layer["count"] for layer in use_layers.values()):
        empty_code = "empty_use_input_nonempty"
    else:
        empty_code = "empty_use_input_layers_not_observed"
    all_observed = all(layer["observed"] for layer in use_layers.values())
    empty_candidate = (not malformed) and all_observed and not any(
        layer["count"] for layer in use_layers.values()
    )
    empty_use_scope_input = {
        "input_version": EMPTY_USE_INPUT_VERSION,
        "turn_status": usage_status
        if usage_status in {"complete", "partial", "unavailable"}
        else "unavailable",
        "reason": None
        if usage_reason is None
        else str(usage_reason),
        "plan": {
            "availability": plan_available,
            "path": None
            if not plan_available
            else (
                None if plan_payload.get("path") is None else str(plan_payload.get("path"))
            ),
            "mode": None
            if not plan_available
            else (
                None if plan_payload.get("mode") is None else str(plan_payload.get("mode"))
            ),
            "as_of": _valid_date(plan_payload.get("as_of")),
            "include_future": plan_payload.get("include_future")
            if type(plan_payload.get("include_future")) is bool
            else None,
            "clarification": plan_payload.get("clarification")
            if type(plan_payload.get("clarification")) is bool
            else None,
        },
        "use_layers": use_layers,
        "candidate_layers": candidate_layers,
        "all_use_layers_observed": all_observed,
        "empty_set_candidate": empty_candidate,
        "code": empty_code,
    }

    document_ids = sorted(
        {
            str(unit_rows[ref].get("document_id"))
            for ref in used_refs
            if ref in unit_rows and unit_rows[ref].get("document_id") is not None
        }
    )
    version_ids = sorted(
        {
            str(unit_rows[ref].get("version_id"))
            for ref in used_refs
            if ref in unit_rows and unit_rows[ref].get("version_id") is not None
        }
    )
    unresolved_refs = sorted(
        ref for ref in used_refs if ref not in unit_rows
    )
    runtime_identity = {
        "declared": True,
        "unit_ids": used_refs,
        "unresolved_unit_ids": unresolved_refs,
        "document_ids": document_ids,
        "version_ids": version_ids,
        "counts": {
            "units": len(used_refs),
            "unresolved": len(unresolved_refs),
            "documents": len(document_ids),
            "versions": len(version_ids),
        },
    }

    snapshot: dict[str, Any] = {
        "contract_version": CONTRACT_VERSION,
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "fixture_kind": fixture_kind,
        "captured_utc": captured_utc or _utc_now(),
        "source_evidence": source_evidence,
        "binding": binding,
        "turn_ref": turn_ref,
        "request_owner": request_owner,
        "record_identities": identity_rows,
        "record_identity_summary": identity_summary,
        "effective_temporal": effective_temporal,
        "empty_use_scope_input": empty_use_scope_input,
        "runtime_identity": runtime_identity,
    }
    summary = public_identity_summary(snapshot)
    snapshot["public_boundary"] = {
        "public_summary_sha256": sha256_hex(canonical_json_bytes(summary)),
        "public_summary_keys": sorted(summary),
        "runtime_ids_only_in_declared_blocks": True,
    }
    snapshot["content_sha256"] = _content_digest(snapshot)
    return validate_identity_snapshot(
        snapshot, expected_bindings=normalized_bindings, source_evidence=evidence
    )


# --------------------------------------------------------------------------- #
# 加密落盘 / 严格读回
# --------------------------------------------------------------------------- #


def _strict_json_loads(data: bytes) -> Any:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        keys = [key for key, _ in pairs]
        if len(set(keys)) != len(keys):
            raise SnapshotContractError("snapshot_json_invalid:duplicate_key")
        return dict(pairs)

    def reject_constant(value: str) -> Any:
        raise SnapshotContractError("snapshot_json_invalid:constant")

    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise SnapshotContractError("snapshot_json_invalid:utf8") from None
    try:
        return json.loads(
            text, object_pairs_hook=reject_duplicates, parse_constant=reject_constant
        )
    except SnapshotContractError:
        raise
    except (json.JSONDecodeError, ValueError):
        raise SnapshotContractError("snapshot_json_invalid:json") from None


@dataclass
class SnapshotWriter:
    """认证加密写入器：严格校验 -> 加密 -> 仓外原子写 -> 读回逐字节比对。"""

    root_dir: Path
    key: bytes
    bindings: Mapping[str, Any]
    fixture_kind: str = "local_mock"
    run_name: str = "run"
    max_envelope_bytes: int = MAX_JSON_BYTES
    written: list[dict[str, Any]] = field(default_factory=list)
    status: str = "active"
    last_error: str | None = None

    def __repr__(self) -> str:  # 绝不回显 key/绑定/密文路径
        return (
            f"SnapshotWriter(root_dir={self.root_dir!r}, fixture_kind={self.fixture_kind!r}, "
            f"status={self.status!r}, written={len(self.written)!r})"
        )

    def __post_init__(self) -> None:
        self.root_dir = assert_evidence_root_outside_repo(Path(self.root_dir))
        self.root_dir.mkdir(parents=True, exist_ok=True)
        if self.fixture_kind not in FIXTURE_KINDS:
            raise SnapshotContractError("snapshot_fixture_kind_invalid")
        if not isinstance(self.key, (bytes, bytearray)) or not self.key:
            raise SnapshotContractError("snapshot_encryption_required")
        self._fernet = Fernet(bytes(self.key))
        self.bindings = {str(k): str(v) for k, v in dict(self.bindings).items()}
        if any(key not in self.bindings for key in BINDING_KEYS):
            raise SnapshotContractError("snapshot_bindings_incomplete")
        if self.fixture_kind != self.bindings.get("fixture_kind"):
            raise SnapshotContractError("snapshot_fixture_binding_mismatch")
        self.run_name = _safe_component(self.run_name)

    def _target_path(self, name: str) -> Path:
        root = self.root_dir.resolve()
        stem, dot, suffix = str(name).partition(".")
        safe_name = _safe_component(stem) + (
            ("." + _safe_component(suffix)) if dot else ""
        )
        target = (root / self.run_name / safe_name).resolve(strict=False)
        try:
            target.relative_to(root)
        except ValueError:
            raise SnapshotContractError("snapshot_io_failed:path") from None
        return target

    def _seal(self, payload: Mapping[str, Any], *, kind: str, turn_index: int) -> dict[str, Any]:
        if self.status != "active":
            raise SnapshotContractError("snapshot_write_failed:writer_not_active")
        try:
            if kind == "snapshot":
                validate_identity_snapshot(payload, expected_bindings=self.bindings)
            else:
                validate_snapshot_manifest(payload, expected_bindings=self.bindings)
            plaintext = canonical_json_bytes(payload)
            if not plaintext or len(plaintext) > self.max_envelope_bytes:
                raise SnapshotContractError("snapshot_size_invalid:plaintext")
            token = self._fernet.encrypt(plaintext)
            if len(token) > self.max_envelope_bytes:
                raise SnapshotContractError("snapshot_size_invalid:ciphertext")
            target = self._target_path(f"{kind}-{turn_index:04d}.fernet")
            target.parent.mkdir(parents=True, exist_ok=True)
            handle, tmp_name = tempfile.mkstemp(
                prefix=".snapshot-", suffix=".tmp", dir=str(target.parent)
            )
            try:
                with os.fdopen(handle, "wb") as stream:
                    stream.write(token)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(tmp_name, target)
            except BaseException:
                try:
                    os.unlink(tmp_name)
                except FileNotFoundError:
                    pass
                raise
            readback = read_snapshot_evidence(
                target, key=bytes(self.key), expected_bindings=self.bindings
            )
            if canonical_json_bytes(readback) != plaintext:
                raise SnapshotContractError("snapshot_readback_mismatch")
            receipt = {
                "path": str(target),
                "sha256": sha256_hex(token),
                "bytes": len(token),
                "turn_index": int(turn_index),
                "kind": kind,
            }
            self.written.append(receipt)
            return receipt
        except SnapshotContractError as exc:
            self.status = "failed"
            self.last_error = exc.code
            raise
        except Exception:
            self.status = "failed"
            self.last_error = "snapshot_io_failed"
            raise SnapshotContractError("snapshot_io_failed") from None

    def write_snapshot(self, snapshot: Mapping[str, Any]) -> dict[str, Any]:
        turn_index = int(dict(snapshot.get("turn_ref") or {}).get("turn_index") or 0)
        return self._seal(snapshot, kind="snapshot", turn_index=turn_index)

    def write_manifest(self, manifest: Mapping[str, Any]) -> dict[str, Any]:
        return self._seal(
            manifest, kind="manifest", turn_index=len(self.written)
        )


def read_snapshot_evidence(
    path: Path,
    *,
    key: bytes,
    expected_bindings: Mapping[str, Any] | None = None,
    expected_turn: Mapping[str, Any] | None = None,
    source_evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """先解密与严格校验，再返回内存对象；拒绝截断/坏 key/跨 run/非密文。"""
    raw_path = Path(path)
    try:
        token = raw_path.read_bytes()
    except OSError:
        raise SnapshotContractError("snapshot_read_failed") from None
    if not token or len(token) > MAX_JSON_BYTES:
        raise SnapshotContractError("snapshot_size_invalid:ciphertext")
    try:
        plaintext = Fernet(bytes(key)).decrypt(token)
    except (InvalidToken, ValueError, TypeError):
        raise SnapshotContractError("snapshot_decrypt_failed") from None
    if len(plaintext) > MAX_JSON_BYTES:
        raise SnapshotContractError("snapshot_size_invalid:plaintext")
    payload = _strict_json_loads(plaintext)
    if not isinstance(payload, Mapping):
        raise SnapshotContractError("snapshot_envelope_invalid")
    version = payload.get("schema_version")
    if version == SNAPSHOT_MANIFEST_SCHEMA_VERSION:
        return validate_snapshot_manifest(payload, expected_bindings=expected_bindings)
    if version == SNAPSHOT_SCHEMA_VERSION:
        return validate_identity_snapshot(
            payload,
            expected_bindings=expected_bindings,
            expected_turn=expected_turn,
            source_evidence=source_evidence,
        )
    raise SnapshotContractError("snapshot_schema_version_invalid:schema_version")


def build_snapshot_manifest(
    *,
    fixture_kind: str,
    bindings: Mapping[str, Any],
    started_utc: str,
    snapshots: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """公开安全清单：每回合只留计数/枚举/摘要，不含 id/日期/文本。"""
    if fixture_kind not in FIXTURE_KINDS:
        _fail("snapshot_fixture_kind_invalid")
    if any(key not in bindings for key in BINDING_KEYS):
        _fail("snapshot_bindings_incomplete")
    turns = []
    for snapshot in sorted(
        snapshots, key=lambda item: int(dict(item.get("turn_ref") or {}).get("turn_index") or 0)
    ):
        summary = public_identity_summary(snapshot)
        turns.append(
            {
                "turn_index": int(summary["turn_index"]),
                "snapshot_sha256": sha256_hex(canonical_json_bytes(snapshot)),
                "source_evidence_sha256": str(
                    dict(snapshot.get("source_evidence") or {}).get("sha256")
                ),
                "record_identity_total": int(summary["record_identity_total"]),
                "record_level_count": int(summary["record_level_count"]),
                "entity_matchable_count": int(summary["entity_matchable_count"]),
                "empty_set_candidate": bool(summary["empty_set_candidate"]),
                "effective_temporal_status": str(summary["effective_temporal_status"]),
            }
        )
    manifest: dict[str, Any] = {
        "schema_version": SNAPSHOT_MANIFEST_SCHEMA_VERSION,
        "fixture_kind": fixture_kind,
        "started_utc": started_utc,
        "bindings_sha256": _bindings_digest(bindings),
        "snapshot_count": len(turns),
        "turns": turns,
    }
    manifest["content_sha256"] = _content_digest(manifest)
    return validate_snapshot_manifest(manifest, expected_bindings=bindings)

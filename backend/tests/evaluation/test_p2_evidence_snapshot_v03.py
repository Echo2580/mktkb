"""C1-P3：运行期身份快照契约 v0.3（合成 + Mock，零真实调用）。

覆盖：
- MockChatBackend + 合成租户/合成文档的「采集 -> 加密落盘 -> 严格读回 -> 校验」全链，
  逐叶字段相等、公开摘要无 id、密文无明文；
- 反例矩阵：字段缺失/类型错/枚举错/未知键/未声明运行期 id/凭证键/明文凭证值/
  跨 run 复用/跨回合复用/摘要篡改/来源证据不符/文档级实体不可匹配/
  未解析 unit/记录索引缺失/空使用集输入自相矛盾/baseline 冒充实际值/明文文件；
- 全程零真实调用；`t09_network_guard` 对每个用例断言外部出站为 0。
"""

from __future__ import annotations

import asyncio
import copy
import functools
import hashlib
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any

import pytest
from cryptography.fernet import Fernet

_TESTS_DIR = Path(__file__).resolve().parents[1]
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

from acceptance.support.netguard import t09_network_guard  # noqa: E402,F401

from mktkb.evaluation.p2_evidence_capture import (  # noqa: E402
    BINDING_KEYS,
    EvidenceCaptureConfig,
)
from mktkb.evaluation.p2_evidence_io import (  # noqa: E402
    EvidenceWriter,
    canonical_json_bytes,
    read_encrypted_evidence,
    sha256_hex,
)
from mktkb.evaluation.p2_evidence_snapshot_v03 import (  # noqa: E402
    CONTRACT_VERSION,
    ENTITY_CODES,
    FAIL_CLOSED_CODES,
    PUBLIC_SUMMARY_KEYS,
    SNAPSHOT_MANIFEST_SCHEMA_VERSION,
    SNAPSHOT_SCHEMA_VERSION,
    SnapshotContractError,
    SnapshotWriter,
    build_identity_snapshot,
    build_snapshot_manifest,
    identity_field_table,
    public_identity_summary,
    read_snapshot_evidence,
    validate_identity_snapshot,
    validate_snapshot_manifest,
)
from mktkb.evaluation.product_adapter import (  # noqa: E402
    IngestSource,
    MockChatBackend,
    P2IngestPlan,
    P2RunDataset,
    ProductEvalAdapter,
)

pytestmark = pytest.mark.usefixtures("t09_network_guard")

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "fixtures" / "acceptance"
D01 = FIXTURES / "normal" / "D01_物品位置表.xlsx"
D04 = FIXTURES / "normal" / "D04_活动策划流程.docx"
V03 = "p2-hard-evidence-capture/v0.3"
BUSINESS_DATE = "2026-03-15"  # 合成值：产品实际配置日，不是任何冻结用例基线
QUESTION_DOC = "活动策划需要哪些步骤？"
QUESTION_RECORDS = "把城东店和城西店的宣传海报记录都列出来"
FIXED_TIME = "2026-11-14T12:00:00+00:00"
FORBIDDEN_CIPHERTEXT = (
    QUESTION_DOC,
    QUESTION_RECORDS,
    "employee",
    "D01_物品位置表.xlsx",
    "D04_活动策划流程.docx",
)
#: 载荷明文里只允许出现哈希/固定码/授权内的 user_ref，不得出现题面或产品文档名。
FORBIDDEN_PLAINTEXT = (QUESTION_DOC, QUESTION_RECORDS, "D01_物品位置表.xlsx", "D04_活动策划流程.docx")

OBSERVED_CODES: dict[str, str] = {}


def asyncio_test(func):
    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any):
        return asyncio.run(func(*args, **kwargs))

    return wrapper


def _bindings(run_id: str) -> dict[str, str]:
    values = {key: "local_mock-" + key for key in BINDING_KEYS}
    values["fixture_kind"] = "local_mock"
    values["run_id"] = run_id
    values["dataset_version"] = "contract-e2e-v1"
    return values


def _dataset() -> P2RunDataset:
    return P2RunDataset(
        visibility="public",
        cases=(),
        identity={
            "dataset_version": "contract-e2e-v1",
            "label_version": "synthetic-v1",
            "suite": "p2-holdout",
            "manifest_sha256": "b" * 64,
            "case_count": 0,
        },
    )


def _manifest_index() -> tuple[dict[str, str], list[dict[str, Any]], dict[str, str]]:
    manifest = json.loads((FIXTURES / "manifest.json").read_text(encoding="utf-8"))
    files = list(manifest["normal_files"]) + list(manifest["variants"])
    doc_codes = {Path(item["path"]).name: item["id"] for item in files}
    versions = {item["id"]: item["business_version"] for item in files}
    records = [
        {
            "doc_code": source["file"],
            "sheet": source["sheet"],
            "row": source["row"],
            "record_key": record_key,
            "business_version": source["business_version"],
        }
        for record_key, source in manifest["sources"].items()
    ]
    return doc_codes, records, versions


def _leaves(value: Any, prefix: str = "") -> dict[str, Any]:
    flat: dict[str, Any] = {}
    if isinstance(value, dict):
        for key, item in value.items():
            flat.update(_leaves(item, f"{prefix}.{key}" if prefix else str(key)))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            flat.update(_leaves(item, f"{prefix}[{index}]"))
    else:
        flat[prefix] = value
    return flat


def _adapter(
    root: Path,
    *,
    writer: EvidenceWriter,
    bindings: dict[str, str],
) -> ProductEvalAdapter:
    return ProductEvalAdapter(
        root,
        chat=MockChatBackend(),
        dataset=_dataset(),
        ingest_plan=P2IngestPlan(
            sources=(IngestSource(D01), IngestSource(D04)), label="snapshot-v03"
        ),
        evidence_capture=EvidenceCaptureConfig(
            root_dir=root / "evidence",
            bindings=bindings,
            writer=writer,
            capture_schema_version=V03,
        ),
        turn_timeout_seconds=120.0,
        purge_traces_on_close=True,
        rag_business_date=BUSINESS_DATE,
        manifest_business_date=BUSINESS_DATE,
    )


@pytest.fixture(scope="module")
def capture_run(tmp_path_factory) -> dict[str, Any]:
    """一次真实产品装配 + 合成 provider：产出冻结 v0.3 密文与本契约快照。"""
    temp = tmp_path_factory.mktemp("c1p3-snapshot")
    bindings = _bindings("snapshot-run")
    writer = EvidenceWriter(
        root_dir=temp / "evidence",
        key=Fernet.generate_key(),
        bindings=bindings,
        run_name="snapshot-v03",
    )
    adapter = _adapter(temp / "run", writer=writer, bindings=bindings)
    questions = [QUESTION_DOC, QUESTION_RECORDS]
    asyncio.run(_drive_and_close(adapter, questions))

    outbound = adapter.network_stats()["outbound_attempts"]
    assert outbound == 0, f"合成链路出现 {outbound} 次出站尝试"
    records = [item for item in writer.written if item["kind"] == "turn"]
    assert len(records) == len(questions)

    evidence = [
        read_encrypted_evidence(
            Path(item["path"]), key=writer.key, expected_bindings=writer.bindings
        )
        for item in records
    ]
    # 冻结会话在 bind() 后会把适配器实际身份（dataset/pipeline/index_revision）合并进
    # 落盘 bindings；本契约以**落盘 envelope 的 bindings** 为准。
    run_bindings = dict(evidence[0]["bindings"])
    for item in evidence[1:]:
        assert dict(item["bindings"]) == run_bindings

    doc_codes, record_index, versions = _manifest_index()
    snapshots = [
        build_identity_snapshot(
            turn_evidence=item,
            bindings=run_bindings,
            doc_code_index=doc_codes,
            record_index=record_index,
            business_versions=versions,
            captured_utc=FIXED_TIME,
        )
        for item in evidence
    ]
    snapshot_writer = SnapshotWriter(
        root_dir=temp / "snapshots",
        key=Fernet.generate_key(),
        bindings=run_bindings,
        run_name="snapshot-v03",
    )
    receipts = [snapshot_writer.write_snapshot(snapshot) for snapshot in snapshots]
    readback = [
        read_snapshot_evidence(
            Path(receipt["path"]),
            key=snapshot_writer.key,
            expected_bindings=run_bindings,
            expected_turn={
                "turn_index": snapshot["turn_ref"]["turn_index"],
                "client_request_id": snapshot["turn_ref"]["client_request_id"],
                "conversation_id": snapshot["turn_ref"]["conversation_id"],
            },
            source_evidence=item,
        )
        for receipt, snapshot, item in zip(receipts, snapshots, evidence)
    ]
    return {
        "temp": temp,
        "bindings": run_bindings,
        "evidence": evidence,
        "records": records,
        "snapshots": snapshots,
        "receipts": receipts,
        "readback": readback,
        "doc_codes": doc_codes,
        "record_index": record_index,
        "versions": versions,
        "snapshot_writer": snapshot_writer,
        "adapter_outbound": outbound,
    }


async def _drive_and_close(adapter: ProductEvalAdapter, questions: list[str]) -> None:
    try:
        await adapter.start()
        await adapter.ingest()
        conversation = await adapter.open_conversation()
        for question in questions:
            await adapter.ask_turn(
                question,
                user_id="employee",
                conversation_id=conversation,
                client_request_id=str(uuid.uuid4()),
            )
    finally:
        await adapter.close()


@pytest.fixture(scope="module", autouse=True)
def _dump_evidence(capture_run):
    yield
    target = os.environ.get("C1P3_EVIDENCE_JSON")
    if not target:
        return
    snapshots = capture_run["snapshots"]
    field_rows = identity_field_table()
    payload = {
        "schema_version": "c1p3-snapshot-evidence/v0.1",
        "contract_version": CONTRACT_VERSION,
        "snapshot_schema_version": SNAPSHOT_SCHEMA_VERSION,
        "field_spec_rows": len(field_rows),
        "required_fields": sum(1 for row in field_rows if row["required"]),
        "nullable_fields": sum(1 for row in field_rows if row["nullable"]),
        "fail_closed_code_families": len(FAIL_CLOSED_CODES),
        "public_summary_keys": len(PUBLIC_SUMMARY_KEYS),
        "turns": [
            {
                "turn_index": snapshot["turn_ref"]["turn_index"],
                "record_identity_rows": snapshot["record_identity_summary"]["total"],
                "record_level": snapshot["record_identity_summary"]["record_level"],
                "entity_matchable": snapshot["record_identity_summary"][
                    "entity_matchable"
                ],
                "doc_codes": snapshot["record_identity_summary"]["doc_codes"],
                "record_codes_values": sorted(
                    {
                        row["record_code"]
                        for row in snapshot["record_identities"]
                        if row["record_code"] is not None
                    }
                ),
                "entity_codes": sorted(
                    {row["entity_code"] for row in snapshot["record_identities"]}
                ),
                "temporal": {
                    "availability": snapshot["effective_temporal"]["availability"],
                    "as_of": snapshot["effective_temporal"]["as_of"],
                    "as_of_source": snapshot["effective_temporal"]["as_of_source"],
                    "code": snapshot["effective_temporal"]["code"],
                    "document_versions": len(
                        snapshot["effective_temporal"]["document_versions"]
                    ),
                },
                "empty_use": {
                    "turn_status": snapshot["empty_use_scope_input"]["turn_status"],
                    "code": snapshot["empty_use_scope_input"]["code"],
                    "all_use_layers_observed": snapshot["empty_use_scope_input"][
                        "all_use_layers_observed"
                    ],
                    "empty_set_candidate": snapshot["empty_use_scope_input"][
                        "empty_set_candidate"
                    ],
                },
                "snapshot_sha256": sha256_hex(canonical_json_bytes(snapshot)),
                "ciphertext_sha256": capture_run["receipts"][
                    snapshot["turn_ref"]["turn_index"]
                ]["sha256"],
                "ciphertext_bytes": capture_run["receipts"][
                    snapshot["turn_ref"]["turn_index"]
                ]["bytes"],
                "public_summary_keys": len(public_identity_summary(snapshot)),
            }
            for snapshot in snapshots
        ],
        "negative_cases": dict(sorted(OBSERVED_CODES.items())),
        "roundtrip_leaf_count_total": sum(
            len(_leaves(item)) for item in capture_run["readback"]
        ),
        "adapter_outbound_attempts": capture_run["adapter_outbound"],
    }
    Path(target).parent.mkdir(parents=True, exist_ok=True)
    Path(target).write_text(
        json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )


# --------------------------------------------------------------------------- #
# 全链：采集 -> 加密落盘 -> 读回 -> 校验
# --------------------------------------------------------------------------- #


def test_full_chain_roundtrip_field_by_field(capture_run) -> None:
    snapshots = capture_run["snapshots"]
    readback = capture_run["readback"]
    assert len(snapshots) == 2
    for built, back, receipt, evidence in zip(
        snapshots, readback, capture_run["receipts"], capture_run["evidence"]
    ):
        # 落盘：密文在仓外、非明文、读回逐叶相等。
        path = Path(receipt["path"])
        assert path.is_file()
        assert ROOT not in path.resolve().parents
        assert path.read_bytes() != canonical_json_bytes(built)
        token = path.read_bytes()
        for needle in FORBIDDEN_CIPHERTEXT:
            assert needle.encode("utf-8") not in token, needle
        for needle in FORBIDDEN_PLAINTEXT:
            assert needle not in json.dumps(built, ensure_ascii=False), needle
        built_leaves = _leaves(built)
        back_leaves = _leaves(back)
        assert built_leaves == back_leaves
        assert len(built_leaves) >= 150
        # 显式逐字段断言（关键身份字段）。
        assert back["request_owner"]["user_ref"] == evidence["turn"][
            "authenticated_user_id"
        ]
        assert back["request_owner"]["user_ref"], "认证后的 owner 身份不得为空"
        assert (
            back["request_owner"]["conversation_ref"]
            == evidence["turn"]["conversation_id"]
        )
        assert back["binding"]["run_id"] == capture_run["bindings"]["run_id"]
        assert back["turn_ref"]["client_request_id"] == evidence["turn"][
            "client_request_id"
        ]
        assert back["source_evidence"]["sha256"] == sha256_hex(
            canonical_json_bytes(evidence)
        )
        assert back["source_evidence"]["schema_version"] == V03
        assert back["content_sha256"] == built["content_sha256"]
        # 公开摘要：固定 25 键、无 id/日期/hash、摘要绑定。
        summary = public_identity_summary(back)
        assert sorted(summary) == list(PUBLIC_SUMMARY_KEYS)
        assert (
            back["public_boundary"]["public_summary_sha256"]
            == sha256_hex(canonical_json_bytes(summary))
        )
        text = json.dumps(summary, ensure_ascii=False)
        assert "employee" not in text
        assert BUSINESS_DATE not in text
        assert str(back["turn_ref"]["client_request_id"]) not in text
        validate_identity_snapshot(
            back,
            expected_bindings=capture_run["bindings"],
            expected_turn={
                "turn_index": back["turn_ref"]["turn_index"],
                "client_request_id": back["turn_ref"]["client_request_id"],
                "conversation_id": back["turn_ref"]["conversation_id"],
            },
            source_evidence=evidence,
        )


def test_effective_temporal_uses_actual_not_expected(capture_run) -> None:
    for snapshot in capture_run["snapshots"]:
        temporal = snapshot["effective_temporal"]
        assert temporal["availability"] == "observed"
        assert temporal["as_of"] == BUSINESS_DATE
        assert temporal["as_of_source"] in {"plan_observed", "rag_business_date"}
        assert temporal["baseline_used_as_effective"] is False
        # local_mock 没有 run_binding：声明基线必须为空，不得拿用例基线冒充。
        assert temporal["declared_baseline_business_date"] is None
        assert snapshot["binding"]["business_date_declared"] is None
        assert all(
            row["code"] in {"version_observed", "version_mismatch", "version_unresolved"}
            for row in temporal["document_versions"]
        )


def test_record_identity_isomorphic_with_contract_v2(capture_run) -> None:
    records_turn = capture_run["snapshots"][1]
    rows = records_turn["record_identities"]
    assert rows, "枚举回合必须至少有已使用记录"
    for row in rows:
        assert row["doc_code"] == "D01"
        assert row["base_doc_code"] == "D01"
        assert row["sheet"] == "物品位置"
        assert row["row"] in {8, 9}
        assert row["record_key"] == row["record_code"]
        assert row["record_code"] in {"P01", "P02"}
        assert row["code"] == "record_row_reverse_lookup"
        assert row["record_level"] is True
        assert row["entity_type"] == "item"
        assert row["entity_matchable"] is True
        assert row["entity_code"] == "entity_identity_matchable_nonrole_filters"
        assert row["layers"], "每条记录必须声明来自哪些使用层"
    doc_turn = capture_run["snapshots"][0]
    for row in doc_turn["record_identities"]:
        assert row["doc_code"] == "D04"
        assert row["record_code"] is None
        assert row["record_level"] is False
        assert row["locator_kind"] in {"heading", "page", "other", "none"}
        assert row["code"] == "runtime_unit_not_record_level"


def test_empty_use_scope_input_is_declarative(capture_run) -> None:
    for snapshot in capture_run["snapshots"]:
        usage = snapshot["empty_use_scope_input"]
        assert usage["input_version"] == "c1p2-empty-use-scope-input/v0.1"
        assert set(usage["use_layers"]) == {
            "model_evidence",
            "model_output_sources",
            "direct_rag_facts",
            "direct_rag_citations",
            "direct_rag_fact_count",
            "answer_result_sources",
            "commit_observed_sources",
            "entity_inheritance",
            "projection_message_sources",
        }
        assert set(usage["candidate_layers"]) == {
            "retrieval_observed",
            "query_state_candidates",
            "projection_query_state_candidates",
        }
        reached = {
            name
            for name, layer in usage["use_layers"].items()
            if layer["count"] > 0
        }
        assert reached, "answer 回合必须至少触达一个使用层"
        assert usage["empty_set_candidate"] is False
        assert usage["code"] == "empty_use_input_nonempty"
        # 候选层不是使用层：候选非空不得直接写成“已使用”。
        assert all(
            set(layer) == {"observed", "count", "refs"}
            for layer in usage["use_layers"].values()
        )


def test_manifest_roundtrip_and_public_boundary(capture_run) -> None:
    writer = capture_run["snapshot_writer"]
    manifest = build_snapshot_manifest(
        fixture_kind="local_mock",
        bindings=capture_run["bindings"],
        started_utc=FIXED_TIME,
        snapshots=capture_run["snapshots"],
    )
    receipt = writer.write_manifest(manifest)
    back = read_snapshot_evidence(
        Path(receipt["path"]),
        key=writer.key,
        expected_bindings=capture_run["bindings"],
    )
    assert back["schema_version"] == SNAPSHOT_MANIFEST_SCHEMA_VERSION
    assert back["snapshot_count"] == 2
    assert [row["turn_index"] for row in back["turns"]] == [0, 1]
    text = json.dumps(back, ensure_ascii=False)
    for needle in FORBIDDEN_PLAINTEXT:
        assert needle not in text


# --------------------------------------------------------------------------- #
# 反例：每个固定码都必须真的被触发
# --------------------------------------------------------------------------- #


def _expect(snapshot, code_family: str, **kwargs) -> str:
    with pytest.raises(SnapshotContractError) as excinfo:
        validate_identity_snapshot(snapshot, **kwargs)
    code = excinfo.value.code
    assert code.split(":", 1)[0] == code_family, code
    OBSERVED_CODES[code_family] = code
    return code


def _mutated(capture_run, index: int = 0) -> dict[str, Any]:
    return copy.deepcopy(capture_run["snapshots"][index])


def test_missing_field_has_fixed_code(capture_run) -> None:
    snapshot = _mutated(capture_run)
    snapshot["request_owner"].pop("owner_source")
    assert _expect(snapshot, "snapshot_missing_field") == (
        "snapshot_missing_field:request_owner.owner_source"
    )


def test_type_error_has_fixed_code(capture_run) -> None:
    snapshot = _mutated(capture_run)
    snapshot["turn_ref"]["turn_index"] = "0"
    assert _expect(snapshot, "snapshot_type_invalid") == (
        "snapshot_type_invalid:turn_ref.turn_index"
    )


def test_null_not_allowed_has_fixed_code(capture_run) -> None:
    snapshot = _mutated(capture_run)
    snapshot["binding"]["run_id"] = None
    assert _expect(snapshot, "snapshot_null_not_allowed") == (
        "snapshot_null_not_allowed:binding.run_id"
    )


def test_enum_error_has_fixed_code(capture_run) -> None:
    snapshot = _mutated(capture_run)
    snapshot["fixture_kind"] = "production"
    assert _expect(snapshot, "snapshot_enum_invalid") == (
        "snapshot_enum_invalid:fixture_kind"
    )


def test_unknown_field_has_fixed_code(capture_run) -> None:
    snapshot = _mutated(capture_run)
    snapshot["binding"]["extra_note"] = "x"
    assert _expect(snapshot, "snapshot_unknown_field") == (
        "snapshot_unknown_field:binding.extra_note"
    )
    del snapshot["binding"]["extra_note"]
    snapshot["record_identities"][0]["raw_row"] = 1
    assert _expect(snapshot, "snapshot_unknown_field") == (
        "snapshot_unknown_field:record_identities[0].raw_row"
    )


def test_undeclared_runtime_id_is_rejected(capture_run) -> None:
    snapshot = _mutated(capture_run)
    snapshot["record_identities"][0]["unit_id"] = "00000000-0000-0000-0000-000000000000"
    assert _expect(snapshot, "snapshot_runtime_id_not_declared") == (
        "snapshot_runtime_id_not_declared:record_identities[0].unit_id"
    )
    snapshot = _mutated(capture_run)
    snapshot["public_boundary"]["document_id"] = "00000000-0000-0000-0000-000000000000"
    assert _expect(snapshot, "snapshot_runtime_id_not_declared") == (
        "snapshot_runtime_id_not_declared:public_boundary.document_id"
    )


def test_credential_key_and_plaintext_secret_are_rejected(capture_run) -> None:
    snapshot = _mutated(capture_run)
    snapshot["request_owner"]["session_token"] = "x"
    assert _expect(snapshot, "snapshot_forbidden_field") == (
        "snapshot_forbidden_field:request_owner.session_token"
    )
    snapshot = _mutated(capture_run)
    snapshot["request_owner"]["user_ref"] = "Bearer abc.def.ghi"
    assert _expect(snapshot, "snapshot_plaintext_secret_rejected") == (
        "snapshot_plaintext_secret_rejected:request_owner.user_ref"
    )
    snapshot = _mutated(capture_run)
    snapshot["binding"]["run_id"] = "gAAAAAB" + "x" * 60
    assert _expect(snapshot, "snapshot_plaintext_secret_rejected").startswith(
        "snapshot_plaintext_secret_rejected:binding.run_id"
    )


def test_cross_run_and_cross_turn_reuse_are_rejected(capture_run, tmp_path) -> None:
    snapshot = _mutated(capture_run)
    other = dict(capture_run["bindings"])
    other["run_id"] = "other-run"
    code = _expect(snapshot, "snapshot_run_binding_mismatch", expected_bindings=other)
    assert code.startswith("snapshot_run_binding_mismatch:")
    # 写侧同样拒绝：用别的 run 的 bindings 打开 writer。
    foreign_writer = SnapshotWriter(
        root_dir=tmp_path / "foreign",
        key=Fernet.generate_key(),
        bindings=other,
        run_name="foreign",
    )
    with pytest.raises(SnapshotContractError) as excinfo:
        foreign_writer.write_snapshot(snapshot)
    assert excinfo.value.code.startswith("snapshot_run_binding_mismatch:")
    OBSERVED_CODES["snapshot_run_binding_mismatch_write"] = excinfo.value.code
    # 跨回合复用：同一 run 的另一个回合身份。
    wrong_turn = {
        "turn_index": snapshot["turn_ref"]["turn_index"],
        "client_request_id": snapshot["turn_ref"]["client_request_id"],
        "conversation_id": "another-conversation",
    }
    code = _expect(
        snapshot,
        "snapshot_turn_binding_mismatch",
        expected_bindings=capture_run["bindings"],
        expected_turn=wrong_turn,
    )
    assert code == "snapshot_turn_binding_mismatch:turn_ref.conversation_id"


def test_digest_tamper_and_source_evidence_mismatch(capture_run) -> None:
    snapshot = _mutated(capture_run)
    snapshot["captured_utc"] = "2026-11-14T12:00:01+00:00"
    assert _expect(snapshot, "snapshot_content_digest_mismatch") == (
        "snapshot_content_digest_mismatch:content_sha256"
    )
    snapshot = _mutated(capture_run)
    other_evidence = copy.deepcopy(capture_run["evidence"][0])
    other_evidence["turn"]["http_status"] = 500
    code = _expect(
        snapshot, "snapshot_source_evidence_mismatch", source_evidence=other_evidence
    )
    assert code == "snapshot_source_evidence_mismatch:source_evidence.sha256"


def test_baseline_cannot_be_used_as_effective(capture_run) -> None:
    snapshot = _mutated(capture_run)
    snapshot["effective_temporal"]["baseline_used_as_effective"] = True
    assert _expect(snapshot, "snapshot_effective_temporal_inconsistent") == (
        "snapshot_effective_temporal_inconsistent:"
        "effective_temporal.baseline_used_as_effective"
    )


def test_empty_use_input_inconsistency_is_rejected(capture_run) -> None:
    snapshot = _mutated(capture_run)
    snapshot["empty_use_scope_input"]["empty_set_candidate"] = True
    assert _expect(snapshot, "snapshot_empty_use_input_inconsistent") == (
        "snapshot_empty_use_input_inconsistent:"
        "empty_use_scope_input.empty_set_candidate"
    )


def test_entity_matchability_cannot_be_faked(capture_run) -> None:
    snapshot = _mutated(capture_run)
    snapshot["record_identities"][0]["entity_matchable"] = True
    assert _expect(snapshot, "snapshot_entity_matchability_inconsistent") == (
        "snapshot_entity_matchability_inconsistent:"
        "record_identities[0].entity_matchable"
    )


def test_public_boundary_tamper_is_rejected(capture_run) -> None:
    snapshot = _mutated(capture_run)
    snapshot["public_boundary"]["public_summary_keys"] = ["unit_ids"]
    assert _expect(snapshot, "snapshot_public_boundary_violation") == (
        "snapshot_public_boundary_violation:public_boundary.public_summary_keys"
    )


def test_plaintext_artifact_is_not_accepted(capture_run, tmp_path) -> None:
    plain = tmp_path / "plain.json"
    plain.write_text(
        json.dumps(capture_run["snapshots"][0], ensure_ascii=False), encoding="utf-8"
    )
    with pytest.raises(SnapshotContractError) as excinfo:
        read_snapshot_evidence(
            plain, key=Fernet.generate_key(), expected_bindings=capture_run["bindings"]
        )
    assert excinfo.value.code == "snapshot_decrypt_failed"
    OBSERVED_CODES["snapshot_decrypt_failed"] = excinfo.value.code

    # 未知 schema 的密文也必须拒绝，而不是当成快照。
    key = Fernet.generate_key()
    token = Fernet(key).encrypt(b'{"schema_version":"x"}')
    target = tmp_path / "unknown.fernet"
    target.write_bytes(token)
    with pytest.raises(SnapshotContractError) as excinfo:
        read_snapshot_evidence(target, key=key)
    assert excinfo.value.code == "snapshot_schema_version_invalid:schema_version"
    OBSERVED_CODES["snapshot_schema_version_invalid"] = excinfo.value.code


def test_manifest_binding_mismatch_is_rejected(capture_run, tmp_path) -> None:
    writer = capture_run["snapshot_writer"]
    manifest = build_snapshot_manifest(
        fixture_kind="local_mock",
        bindings=capture_run["bindings"],
        started_utc=FIXED_TIME,
        snapshots=capture_run["snapshots"],
    )
    receipt = writer.write_manifest(manifest)
    other = dict(capture_run["bindings"])
    other["run_id"] = "other-run"
    with pytest.raises(SnapshotContractError) as excinfo:
        read_snapshot_evidence(
            Path(receipt["path"]), key=writer.key, expected_bindings=other
        )
    assert excinfo.value.code.startswith("snapshot_manifest_binding_mismatch:")
    OBSERVED_CODES["snapshot_manifest_binding_mismatch"] = excinfo.value.code


# --------------------------------------------------------------------------- #
# 合成证据变体：文档级实体、未解析 unit、记录索引缺失、doc_code 缺失
# --------------------------------------------------------------------------- #


def _build_from(capture_run, evidence_index: int, **overrides) -> dict[str, Any]:
    return build_identity_snapshot(
        turn_evidence=capture_run["evidence"][evidence_index],
        bindings=capture_run["bindings"],
        doc_code_index=overrides.get("doc_code_index", capture_run["doc_codes"]),
        record_index=overrides.get("record_index", capture_run["record_index"]),
        business_versions=capture_run["versions"],
        captured_utc=FIXED_TIME,
    )


def test_document_level_entity_is_not_matchable(capture_run) -> None:
    evidence = copy.deepcopy(capture_run["evidence"][0])
    unit = evidence["db_projection"]["units"][0]
    unit["entity_type"] = "document"
    unit["entity_key"] = "document|" + str(uuid.uuid4())
    unit["entity_filters"] = {}
    snapshot = build_identity_snapshot(
        turn_evidence=evidence,
        bindings=capture_run["bindings"],
        doc_code_index=capture_run["doc_codes"],
        record_index=capture_run["record_index"],
        business_versions=capture_run["versions"],
        captured_utc=FIXED_TIME,
    )
    row = next(
        item
        for item in snapshot["record_identities"]
        if item["source_ref"] == str(unit["unit_id"])
    )
    assert row["entity_type"] == "document"
    assert row["entity_matchable"] is False
    assert row["entity_code"] == "entity_identity_document_level"
    assert row["record_level"] is False
    assert snapshot["record_identity_summary"]["entity_document_level"] == 1
    assert snapshot["record_identity_summary"]["entity_matchable"] == 0
    # 文档级身份不得成为可匹配目标：P4 的转换假象红线（M-C1P1-01）。
    assert ENTITY_CODES == (
        "entity_identity_matchable",
        "entity_identity_matchable_nonrole_filters",
        "entity_identity_nonmatchable",
        "entity_identity_document_level",
        "entity_identity_absent",
        "entity_identity_unavailable",
    )


def test_unresolved_unit_keeps_fail_closed_row(capture_run) -> None:
    evidence = copy.deepcopy(capture_run["evidence"][1])
    removed = evidence["db_projection"]["units"].pop(0)
    evidence["db_projection"]["unresolved_unit_ids"].append(
        {"unit_id": str(removed["unit_id"]), "reason": "unit_not_found"}
    )
    snapshot = build_identity_snapshot(
        turn_evidence=evidence,
        bindings=capture_run["bindings"],
        doc_code_index=capture_run["doc_codes"],
        record_index=capture_run["record_index"],
        business_versions=capture_run["versions"],
        captured_utc=FIXED_TIME,
    )
    row = next(
        item
        for item in snapshot["record_identities"]
        if item["source_ref"] == str(removed["unit_id"])
    )
    assert row["code"] == "runtime_unit_unresolved"
    assert row["entity_code"] == "entity_identity_unavailable"
    assert row["record_level"] is False
    assert snapshot["record_identity_summary"]["unresolved_units"] == 1
    assert snapshot["runtime_identity"]["unresolved_unit_ids"] == sorted(
        [str(removed["unit_id"])]
    )


def test_record_index_missing_and_doc_code_unresolved(capture_run) -> None:
    no_records = _build_from(capture_run, 1, record_index=[])
    assert no_records["record_identity_summary"]["record_level"] == 0
    assert all(
        row["code"] == "record_row_not_in_record_index"
        for row in no_records["record_identities"]
    )
    no_docs = _build_from(capture_run, 1, doc_code_index={})
    assert no_docs["record_identity_summary"]["doc_code_unresolved"] == len(
        no_docs["record_identities"]
    )
    assert all(
        row["code"] == "runtime_doc_code_unresolved"
        for row in no_docs["record_identities"]
    )
    with pytest.raises(SnapshotContractError) as excinfo:
        build_identity_snapshot(
            turn_evidence=capture_run["evidence"][1],
            bindings=capture_run["bindings"],
            record_index=[
                {
                    "doc_code": "D01",
                    "sheet": "物品位置",
                    "row": 8,
                    "record_key": "P01",
                },
                {
                    "doc_code": "D01",
                    "sheet": "物品位置",
                    "row": 8,
                    "record_key": "P99",
                },
            ],
        )
    assert excinfo.value.code.startswith("snapshot_record_index_conflict:")
    OBSERVED_CODES["snapshot_record_index_conflict"] = excinfo.value.code


def test_source_evidence_must_be_frozen_v03(capture_run) -> None:
    evidence = copy.deepcopy(capture_run["evidence"][0])
    evidence["schema_version"] = "p2-hard-evidence-capture/v0.1"
    with pytest.raises(SnapshotContractError) as excinfo:
        build_identity_snapshot(
            turn_evidence=evidence, bindings=capture_run["bindings"]
        )
    assert excinfo.value.code.startswith("snapshot_source_evidence_unsupported:")
    OBSERVED_CODES["snapshot_source_evidence_unsupported"] = excinfo.value.code
    replayed = copy.deepcopy(capture_run["evidence"][0])
    replayed["completeness"]["status"] = "replayed"
    with pytest.raises(SnapshotContractError) as excinfo:
        build_identity_snapshot(
            turn_evidence=replayed, bindings=capture_run["bindings"]
        )
    assert excinfo.value.code == (
        "snapshot_source_evidence_unsupported:source_evidence.completeness_status"
    )


# --------------------------------------------------------------------------- #
# 其余高价值固定码：逐条触发，避免“码表里有、实际没测”
# --------------------------------------------------------------------------- #


def test_additional_fail_closed_codes(capture_run, tmp_path) -> None:
    snapshot = _mutated(capture_run)
    snapshot["contract_version"] = "p2-hard-evidence-capture-identity/v9"
    assert _expect(snapshot, "snapshot_contract_version_invalid") == (
        "snapshot_contract_version_invalid:contract_version"
    )

    snapshot = _mutated(capture_run)
    snapshot["request_owner"]["auth_material_collected"] = True
    assert _expect(snapshot, "snapshot_credential_material_forbidden") == (
        "snapshot_credential_material_forbidden:request_owner.auth_material_collected"
    )

    snapshot = _mutated(capture_run)
    snapshot["request_owner"]["user_ref"] = None
    assert _expect(snapshot, "snapshot_owner_inconsistent") == (
        "snapshot_owner_inconsistent:request_owner.user_ref"
    )

    snapshot = _mutated(capture_run)
    snapshot["record_identity_summary"]["total"] += 1
    assert _expect(snapshot, "snapshot_summary_mismatch") == (
        "snapshot_summary_mismatch:record_identity_summary.total"
    )

    snapshot = _mutated(capture_run)
    snapshot["record_identities"][0]["record_code"] = "P01"
    snapshot["record_identities"][0]["record_key"] = None
    assert _expect(snapshot, "snapshot_record_identity_inconsistent") == (
        "snapshot_record_identity_inconsistent:record_identities[0].record_code"
    )

    snapshot = _mutated(capture_run)
    snapshot["effective_temporal"]["document_versions"][0]["runtime_version_number"] = None
    assert _expect(snapshot, "snapshot_document_version_inconsistent") == (
        "snapshot_document_version_inconsistent:"
        "effective_temporal.document_versions[0].runtime_version_number"
    )

    snapshot = _mutated(capture_run)
    snapshot["record_identities"][0]["entity_code"] = "entity_identity_matchable"
    assert _expect(snapshot, "snapshot_entity_code_inconsistent") == (
        "snapshot_entity_code_inconsistent:record_identities[0].entity_code"
    )

    snapshot = _mutated(capture_run)
    snapshot["runtime_identity"]["unit_ids"] = list(
        reversed(snapshot["runtime_identity"]["unit_ids"])
    )
    assert _expect(snapshot, "snapshot_list_order_invalid") == (
        "snapshot_list_order_invalid:runtime_identity.unit_ids"
    )

    snapshot = _mutated(capture_run)
    snapshot["runtime_identity"]["unit_ids"] = snapshot["runtime_identity"]["unit_ids"][:-1]
    assert _expect(snapshot, "snapshot_runtime_identity_inconsistent") == (
        "snapshot_runtime_identity_inconsistent:runtime_identity.unit_ids"
    )

    snapshot = _mutated(capture_run)
    snapshot["source_evidence"]["fixture_kind"] = "live_h2"
    assert _expect(snapshot, "snapshot_fixture_binding_mismatch") == "snapshot_fixture_binding_mismatch"

    snapshot = _mutated(capture_run)
    code = _expect(
        snapshot,
        "snapshot_expected_bindings_invalid",
        expected_bindings={"run_id": "x"},
    )
    assert code == "snapshot_expected_bindings_invalid"

    empty = tmp_path / "empty.fernet"
    empty.write_bytes(b"")
    with pytest.raises(SnapshotContractError) as excinfo:
        read_snapshot_evidence(empty, key=Fernet.generate_key())
    assert excinfo.value.code == "snapshot_size_invalid:ciphertext"
    OBSERVED_CODES["snapshot_size_invalid"] = excinfo.value.code

    with pytest.raises(SnapshotContractError) as excinfo:
        read_snapshot_evidence(tmp_path / "missing.fernet", key=Fernet.generate_key())
    assert excinfo.value.code == "snapshot_read_failed"
    OBSERVED_CODES["snapshot_read_failed"] = excinfo.value.code

    key = Fernet.generate_key()
    broken = tmp_path / "broken.fernet"
    broken.write_bytes(Fernet(key).encrypt(b"not-json"))
    with pytest.raises(SnapshotContractError) as excinfo:
        read_snapshot_evidence(broken, key=key)
    assert excinfo.value.code == "snapshot_json_invalid:json"
    OBSERVED_CODES["snapshot_json_invalid"] = excinfo.value.code

    with pytest.raises(SnapshotContractError) as excinfo:
        build_identity_snapshot(
            turn_evidence="not-an-envelope", bindings=capture_run["bindings"]
        )
    assert excinfo.value.code == "snapshot_evidence_not_supported"
    OBSERVED_CODES["snapshot_evidence_not_supported"] = excinfo.value.code

    with pytest.raises(SnapshotContractError) as excinfo:
        build_identity_snapshot(
            turn_evidence=capture_run["evidence"][0],
            bindings=capture_run["bindings"],
            doc_code_index=["bad"],
        )
    assert excinfo.value.code == "snapshot_doc_code_index_invalid"
    OBSERVED_CODES["snapshot_doc_code_index_invalid"] = excinfo.value.code

    with pytest.raises(SnapshotContractError) as excinfo:
        build_identity_snapshot(
            turn_evidence=capture_run["evidence"][0],
            bindings=capture_run["bindings"],
            record_index=[{"doc_code": "D01", "row": 8, "record_key": "P01"}],
        )
    assert excinfo.value.code == "snapshot_record_index_invalid:sheet"
    OBSERVED_CODES["snapshot_record_index_invalid"] = excinfo.value.code

    with pytest.raises(SnapshotContractError) as excinfo:
        build_identity_snapshot(
            turn_evidence=capture_run["evidence"][0], bindings={}
        )
    assert excinfo.value.code == "snapshot_bindings_incomplete"
    OBSERVED_CODES["snapshot_bindings_incomplete"] = excinfo.value.code

    with pytest.raises(SnapshotContractError) as excinfo:
        SnapshotWriter(
            root_dir=tmp_path / "bad-kind",
            key=Fernet.generate_key(),
            bindings=capture_run["bindings"],
            fixture_kind="production",
        )
    assert excinfo.value.code == "snapshot_fixture_kind_invalid"
    OBSERVED_CODES["snapshot_fixture_kind_invalid"] = excinfo.value.code

    with pytest.raises(SnapshotContractError) as excinfo:
        SnapshotWriter(
            root_dir=tmp_path / "no-key",
            key=b"",
            bindings=capture_run["bindings"],
        )
    assert excinfo.value.code == "snapshot_encryption_required"
    OBSERVED_CODES["snapshot_encryption_required"] = excinfo.value.code

    writer = SnapshotWriter(
        root_dir=tmp_path / "failed-writer",
        key=Fernet.generate_key(),
        bindings=capture_run["bindings"],
    )
    writer.status = "failed"
    with pytest.raises(SnapshotContractError) as excinfo:
        writer.write_snapshot(capture_run["snapshots"][0])
    assert excinfo.value.code == "snapshot_write_failed:writer_not_active"
    OBSERVED_CODES["snapshot_write_failed"] = excinfo.value.code

    with pytest.raises(SnapshotContractError) as excinfo:
        validate_identity_snapshot(["not", "a", "mapping"])
    assert excinfo.value.code == "snapshot_envelope_invalid"
    OBSERVED_CODES["snapshot_envelope_invalid"] = excinfo.value.code

    broken_evidence = copy.deepcopy(capture_run["evidence"][0])
    broken_evidence.pop("runtime_snapshot")
    with pytest.raises(SnapshotContractError) as excinfo:
        build_identity_snapshot(
            turn_evidence=broken_evidence, bindings=capture_run["bindings"]
        )
    assert excinfo.value.code == "snapshot_source_evidence_invalid"
    OBSERVED_CODES["snapshot_source_evidence_invalid"] = excinfo.value.code

    manifest = build_snapshot_manifest(
        fixture_kind="local_mock",
        bindings=capture_run["bindings"],
        started_utc=FIXED_TIME,
        snapshots=capture_run["snapshots"],
    )
    manifest["snapshot_count"] = 99
    manifest["content_sha256"] = sha256_hex(
        canonical_json_bytes(
            {key: value for key, value in manifest.items() if key != "content_sha256"}
        )
    )
    with pytest.raises(SnapshotContractError) as excinfo:
        validate_snapshot_manifest(manifest, expected_bindings=capture_run["bindings"])
    assert excinfo.value.code == "snapshot_manifest_count_mismatch:snapshot_count"
    OBSERVED_CODES["snapshot_manifest_count_mismatch"] = excinfo.value.code


# --------------------------------------------------------------------------- #
# 字段表与固定码表自检
# --------------------------------------------------------------------------- #


def test_field_table_and_code_table_are_complete() -> None:
    rows = identity_field_table()
    assert len(rows) >= 150
    paths = [row["path"] for row in rows]
    assert len(paths) == len(set(paths)), "字段表路径不得重复"
    expected_paths = {
        "request_owner.user_ref",
        "request_owner.auth_material_collected",
        "record_identities[].record_code",
        "record_identities[].record_level",
        "record_identities[].entity_matchable",
        "effective_temporal.as_of",
        "effective_temporal.as_of_source",
        "effective_temporal.baseline_used_as_effective",
        "empty_use_scope_input.use_layers.model_evidence.count",
        "empty_use_scope_input.candidate_layers.retrieval_observed.refs",
        "runtime_identity.counts.units",
        "public_boundary.public_summary_keys",
    }
    assert expected_paths <= set(paths)
    assert all(row["missing_code"].startswith("snapshot_missing_field:") for row in rows)
    assert len(PUBLIC_SUMMARY_KEYS) == 25
    assert "snapshot_missing_field" in FAIL_CLOSED_CODES
    assert "snapshot_decrypt_failed" in FAIL_CLOSED_CODES
    assert "snapshot_plaintext_secret_rejected" in FAIL_CLOSED_CODES

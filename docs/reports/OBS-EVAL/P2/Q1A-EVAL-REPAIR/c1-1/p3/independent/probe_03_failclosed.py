"""C1-P3 独立验收探针 3/6：fail-closed 严格性（自建反例，不照抄开发用例）。

原则：
- 每个反例都从**独立合成链路**产出的合法快照/证据出发，只做一处最小改动；
- 断言**精确码**（族 + 声明路径），不只看族；
- 四个“未构造反例”的防御码单独做可达性实验（真触发 / 故障注入 / 被冻结前置校验遮蔽）。
"""
from __future__ import annotations

import copy
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import netguard_independent as guard  # noqa: E402

guard.install()

from cryptography.fernet import Fernet  # noqa: E402

from mktkb.evaluation import p2_evidence_snapshot_v03 as mod  # noqa: E402
from mktkb.evaluation.p2_evidence_io import (  # noqa: E402
    canonical_json_bytes,
    sha256_hex,
)
from mktkb.evaluation.p2_evidence_snapshot_v03 import (  # noqa: E402
    SnapshotContractError,
    SnapshotWriter,
    build_identity_snapshot,
    build_snapshot_manifest,
    read_snapshot_evidence,
    validate_identity_snapshot,
    validate_snapshot_manifest,
)

CACHE = json.loads((HERE / "out" / "02-capture-cache.json").read_text(encoding="utf-8"))
BINDINGS: dict[str, str] = CACHE["bindings"]
EVIDENCE: list[dict[str, Any]] = CACHE["evidence"]
SNAPSHOTS: list[dict[str, Any]] = CACHE["snapshots"]
DOC_CODES = CACHE["doc_codes"]
RECORD_INDEX = CACHE["record_index"]
CORPUS = CACHE["corpus"]
TEMP = Path(tempfile.mkdtemp(prefix="c1p3-independent-failclosed-"))

RESULTS: list[dict[str, Any]] = []


def reseal(payload: dict[str, Any]) -> dict[str, Any]:
    """按契约算法重算 content_sha256，使反例只测目标不变量。"""
    body = {
        "contract_version": payload["contract_version"],
        "schema_version": payload["schema_version"],
        "fixture_kind": payload["fixture_kind"],
        "captured_utc": payload["captured_utc"],
        "source_evidence": payload["source_evidence"],
        "binding": payload["binding"],
        "turn_ref": payload["turn_ref"],
        "request_owner": payload["request_owner"],
        "record_identities": payload["record_identities"],
        "record_identity_summary": payload["record_identity_summary"],
        "effective_temporal": payload["effective_temporal"],
        "empty_use_scope_input": payload["empty_use_scope_input"],
        "runtime_identity": payload["runtime_identity"],
        "public_boundary": payload["public_boundary"],
    }
    payload["content_sha256"] = sha256_hex(canonical_json_bytes(body))
    return payload


def code_of(func, *args, **kwargs) -> str:
    try:
        func(*args, **kwargs)
    except SnapshotContractError as exc:
        return exc.code
    return "ACCEPTED"


def record(
    name: str,
    expected: str,
    observed: str,
    *,
    kind: str = "counterexample",
    detail: Any = None,
) -> None:
    RESULTS.append(
        {
            "name": name,
            "kind": kind,
            "expected": expected,
            "observed": observed,
            "ok": observed == expected,
            "detail": detail,
        }
    )


def snapshot(index: int = 1) -> dict[str, Any]:
    return copy.deepcopy(SNAPSHOTS[index])


def evidence(index: int = 1) -> dict[str, Any]:
    return copy.deepcopy(EVIDENCE[index])


def main() -> int:
    base = snapshot(1)
    assert validate_identity_snapshot(base, expected_bindings=BINDINGS)

    # ---- 1. 字段缺失 / 类型 / null / 枚举 / 未知键 ----
    item = snapshot()
    item["record_identities"][0].pop("record_code")
    item["record_identity_summary"] = mod._summary_block(item["record_identities"])
    record(
        "missing_field",
        "snapshot_missing_field:record_identities[0].record_code",
        code_of(validate_identity_snapshot, reseal(item), expected_bindings=BINDINGS),
    )
    item = snapshot()
    item["turn_ref"]["turn_index"] = "1"
    record("type_error", "snapshot_type_invalid:turn_ref.turn_index", code_of(validate_identity_snapshot, reseal(item)))
    item = snapshot()
    item["binding"]["run_id"] = None
    record("null_not_allowed", "snapshot_null_not_allowed:binding.run_id", code_of(validate_identity_snapshot, reseal(item)))
    item = snapshot()
    item["fixture_kind"] = "production"
    record("enum_invalid", "snapshot_enum_invalid:fixture_kind", code_of(validate_identity_snapshot, reseal(item)))
    item = snapshot()
    item["binding"]["extra_note"] = "x"
    record("unknown_key", "snapshot_unknown_field:binding.extra_note", code_of(validate_identity_snapshot, reseal(item)))

    # ---- 2. 跨 run（读 + 写） / 跨回合 / 清单跨 run ----
    other = dict(BINDINGS)
    other["run_id"] = "another-run"
    item = snapshot()
    record(
        "cross_run_read",
        "snapshot_run_binding_mismatch:binding.bindings_sha256",
        code_of(validate_identity_snapshot, reseal(item), expected_bindings=other),
    )
    foreign_writer = SnapshotWriter(
        root_dir=TEMP / "foreign", key=Fernet.generate_key(), bindings=other, run_name="foreign"
    )
    record(
        "cross_run_write",
        "snapshot_run_binding_mismatch:binding.bindings_sha256",
        code_of(foreign_writer.write_snapshot, copy.deepcopy(SNAPSHOTS[1])),
    )
    item = snapshot()
    wrong_turn = {
        "turn_index": item["turn_ref"]["turn_index"],
        "client_request_id": item["turn_ref"]["client_request_id"],
        "conversation_id": "other-conversation",
    }
    record(
        "cross_turn",
        "snapshot_turn_binding_mismatch:turn_ref.conversation_id",
        code_of(validate_identity_snapshot, reseal(item), expected_bindings=BINDINGS, expected_turn=wrong_turn),
    )
    manifest = build_snapshot_manifest(
        fixture_kind="local_mock", bindings=BINDINGS, started_utc="2026-11-14T12:00:00+00:00",
        snapshots=SNAPSHOTS,
    )
    writer = SnapshotWriter(root_dir=TEMP / "writer", key=Fernet.generate_key(), bindings=BINDINGS, run_name="m")
    receipt = writer.write_manifest(manifest)
    record(
        "manifest_cross_run",
        "snapshot_manifest_binding_mismatch:bindings_sha256",
        code_of(read_snapshot_evidence, Path(receipt["path"]), key=writer.key, expected_bindings=other),
    )

    # ---- 3. 未声明运行期 id / 凭证键 / 明文值 ----
    item = snapshot()
    item["record_identities"][0]["unit_id"] = item["record_identities"][0]["source_ref"]
    record(
        "undeclared_runtime_id",
        "snapshot_runtime_id_not_declared:record_identities[0].unit_id",
        code_of(validate_identity_snapshot, reseal(item)),
    )
    item = snapshot()
    item["request_owner"]["session_token"] = "abc"
    record(
        "credential_key",
        "snapshot_forbidden_field:request_owner.session_token",
        code_of(validate_identity_snapshot, reseal(item)),
    )
    item = snapshot()
    item["record_identities"][0]["entity_filters"]["password_hash"] = "x"
    record(
        "credential_key_in_filters",
        "snapshot_forbidden_field:record_identities[0].entity_filters.password_hash",
        code_of(validate_identity_snapshot, reseal(item)),
    )
    item = snapshot()
    item["request_owner"]["user_ref"] = "Bearer abcdefghijklmnop"
    record(
        "plaintext_secret_bearer",
        "snapshot_plaintext_secret_rejected:request_owner.user_ref",
        code_of(validate_identity_snapshot, reseal(item)),
    )
    item = snapshot()
    item["binding"]["run_id"] = "gAAAAAB" + "x" * 60
    record(
        "plaintext_secret_fernet",
        "snapshot_plaintext_secret_rejected:binding.run_id",
        code_of(validate_identity_snapshot, reseal(item)),
    )
    plain = TEMP / "plain.json"
    plain.write_text(json.dumps(SNAPSHOTS[1], ensure_ascii=False), encoding="utf-8")
    record(
        "plaintext_file",
        "snapshot_decrypt_failed",
        code_of(read_snapshot_evidence, plain, key=Fernet.generate_key()),
    )

    # ---- 4. 摘要 / 来源证据 / baseline ----
    item = snapshot()
    item["captured_utc"] = "2026-11-14T12:00:09+00:00"
    record(
        "content_digest_tamper",
        "snapshot_content_digest_mismatch:content_sha256",
        code_of(validate_identity_snapshot, item),
    )
    other_evidence = evidence(1)
    other_evidence["turn"]["http_status"] = 500
    record(
        "source_evidence_mismatch",
        "snapshot_source_evidence_mismatch:source_evidence.sha256",
        code_of(validate_identity_snapshot, snapshot(1), source_evidence=other_evidence),
    )
    item = snapshot()
    item["effective_temporal"]["baseline_used_as_effective"] = True
    record(
        "baseline_impersonation_flag",
        "snapshot_effective_temporal_inconsistent:effective_temporal.baseline_used_as_effective",
        code_of(validate_identity_snapshot, reseal(item)),
    )
    item = snapshot()
    item["request_owner"]["auth_material_collected"] = True
    record(
        "auth_material_collected",
        "snapshot_credential_material_forbidden:request_owner.auth_material_collected",
        code_of(validate_identity_snapshot, reseal(item)),
    )

    # ---- 5. 空集输入自相矛盾 / 实体可匹配性伪造 / 公开边界 ----
    item = snapshot()
    item["empty_use_scope_input"]["empty_set_candidate"] = True
    record(
        "empty_use_self_contradiction",
        "snapshot_empty_use_input_inconsistent:empty_use_scope_input.empty_set_candidate",
        code_of(validate_identity_snapshot, reseal(item)),
    )
    item = snapshot()
    item["empty_use_scope_input"]["all_use_layers_observed"] = True
    record(
        "all_layers_observed_contradiction",
        "snapshot_empty_use_input_inconsistent:empty_use_scope_input.all_use_layers_observed",
        code_of(validate_identity_snapshot, reseal(item)),
    )
    item = snapshot(0)
    item["record_identities"][0]["entity_matchable"] = True
    record(
        "entity_matchable_forgery",
        "snapshot_entity_matchability_inconsistent:record_identities[0].entity_matchable",
        code_of(validate_identity_snapshot, reseal(item)),
    )
    item = snapshot()
    item["record_identities"][0]["entity_code"] = "entity_identity_matchable"
    record(
        "entity_code_forgery",
        "snapshot_entity_code_inconsistent:record_identities[0].entity_code",
        code_of(validate_identity_snapshot, reseal(item)),
    )
    item = snapshot()
    item["public_boundary"]["public_summary_keys"] = ["unit_ids"]
    record(
        "public_boundary_keys",
        "snapshot_public_boundary_violation:public_boundary.public_summary_keys",
        code_of(validate_identity_snapshot, reseal(item)),
    )
    item = snapshot()
    item["public_boundary"]["public_summary_sha256"] = "0" * 64
    record(
        "public_boundary_digest",
        "snapshot_public_boundary_violation:public_boundary.public_summary_sha256",
        code_of(validate_identity_snapshot, reseal(item)),
    )
    item = snapshot()
    item["public_boundary"]["document_id"] = "0" * 8 + "-0000-0000-0000-000000000000"
    record(
        "public_boundary_runtime_id",
        "snapshot_runtime_id_not_declared:public_boundary.document_id",
        code_of(validate_identity_snapshot, reseal(item)),
    )

    # ---- 6. 其余结构 / 索引 / 来源 / 读回 ----
    item = snapshot()
    item["record_identity_summary"]["total"] += 1
    record(
        "summary_mismatch",
        "snapshot_summary_mismatch:record_identity_summary.total",
        code_of(validate_identity_snapshot, reseal(item)),
    )
    item = snapshot()
    item["record_identities"][0]["record_code"] = "W01"
    item["record_identities"][0]["record_key"] = None
    item["record_identity_summary"] = mod._summary_block(item["record_identities"])
    record(
        "record_identity_inconsistent",
        "snapshot_record_identity_inconsistent:record_identities[0].record_code",
        code_of(validate_identity_snapshot, reseal(item)),
    )
    item = snapshot()
    item["effective_temporal"]["document_versions"][0]["runtime_version_number"] = None
    record(
        "document_version_inconsistent",
        "snapshot_document_version_inconsistent:effective_temporal.document_versions[0].runtime_version_number",
        code_of(validate_identity_snapshot, reseal(item)),
    )
    item = snapshot()
    item["record_identity_summary"]["doc_codes"] = ["S01", "S00"]
    record(
        "list_order_invalid",
        "snapshot_list_order_invalid:record_identity_summary.doc_codes",
        code_of(validate_identity_snapshot, reseal(item)),
    )
    item = snapshot()
    item["runtime_identity"]["unit_ids"] = item["runtime_identity"]["unit_ids"][:-1]
    record(
        "runtime_identity_inconsistent",
        "snapshot_runtime_identity_inconsistent:runtime_identity.unit_ids",
        code_of(validate_identity_snapshot, reseal(item)),
    )
    item = snapshot()
    item["request_owner"]["user_ref"] = None
    record(
        "owner_inconsistent",
        "snapshot_owner_inconsistent:request_owner.user_ref",
        code_of(validate_identity_snapshot, reseal(item)),
    )
    item = snapshot()
    record(
        "expected_bindings_invalid",
        "snapshot_expected_bindings_invalid",
        code_of(validate_identity_snapshot, reseal(item), expected_bindings={"run_id": "x"}),
    )
    record(
        "envelope_invalid",
        "snapshot_envelope_invalid",
        code_of(validate_identity_snapshot, ["not", "a", "mapping"]),
    )
    record(
        "contract_version_invalid",
        "snapshot_contract_version_invalid:contract_version",
        code_of(validate_identity_snapshot, {**snapshot(), "contract_version": "v9"}),
    )
    record(
        "schema_version_invalid",
        "snapshot_schema_version_invalid:schema_version",
        code_of(validate_identity_snapshot, {**snapshot(), "schema_version": "x"}),
    )
    item = snapshot()
    item["source_evidence"]["fixture_kind"] = "live_h2"
    record(
        "fixture_binding_mismatch",
        "snapshot_fixture_binding_mismatch",
        code_of(validate_identity_snapshot, reseal(item)),
    )
    record(
        "source_evidence_unsupported",
        "snapshot_source_evidence_unsupported:source_evidence.schema_version",
        code_of(
            build_identity_snapshot,
            turn_evidence={**evidence(1), "schema_version": "p2-hard-evidence-capture/v0.1"},
            bindings=BINDINGS,
        ),
    )
    replayed = evidence(1)
    replayed["completeness"]["status"] = "replayed"
    record(
        "source_evidence_replayed",
        "snapshot_source_evidence_unsupported:source_evidence.completeness_status",
        code_of(build_identity_snapshot, turn_evidence=replayed, bindings=BINDINGS),
    )
    broken = evidence(1)
    broken.pop("runtime_snapshot")
    record(
        "source_evidence_invalid",
        "snapshot_source_evidence_invalid",
        code_of(build_identity_snapshot, turn_evidence=broken, bindings=BINDINGS),
    )
    record(
        "evidence_not_supported",
        "snapshot_evidence_not_supported",
        code_of(build_identity_snapshot, turn_evidence="not-an-envelope", bindings=BINDINGS),
    )
    record(
        "bindings_incomplete",
        "snapshot_bindings_incomplete",
        code_of(build_identity_snapshot, turn_evidence=EVIDENCE[1], bindings={}),
    )
    record(
        "doc_code_index_invalid",
        "snapshot_doc_code_index_invalid",
        code_of(build_identity_snapshot, turn_evidence=EVIDENCE[1], bindings=BINDINGS, doc_code_index=["bad"]),
    )
    record(
        "record_index_invalid",
        "snapshot_record_index_invalid:sheet",
        code_of(
            build_identity_snapshot,
            turn_evidence=EVIDENCE[1],
            bindings=BINDINGS,
            record_index=[{"doc_code": "S01", "row": 2, "record_key": "W01"}],
        ),
    )
    record(
        "record_index_conflict",
        "snapshot_record_index_conflict:S01|" + CORPUS["stock_sheet"] + "|2",
        code_of(
            build_identity_snapshot,
            turn_evidence=EVIDENCE[1],
            bindings=BINDINGS,
            doc_code_index=DOC_CODES,
            record_index=[
                {"doc_code": "S01", "sheet": CORPUS["stock_sheet"], "row": 2, "record_key": "W01"},
                {"doc_code": "S01", "sheet": CORPUS["stock_sheet"], "row": 2, "record_key": "W99"},
            ],
        ),
    )
    empty_file = TEMP / "empty.fernet"
    empty_file.write_bytes(b"")
    record("size_invalid", "snapshot_size_invalid:ciphertext", code_of(read_snapshot_evidence, empty_file, key=Fernet.generate_key()))
    record("read_failed", "snapshot_read_failed", code_of(read_snapshot_evidence, TEMP / "missing.fernet", key=Fernet.generate_key()))
    key = Fernet.generate_key()
    not_json = TEMP / "notjson.fernet"
    not_json.write_bytes(Fernet(key).encrypt(b"not-json"))
    record("json_invalid", "snapshot_json_invalid:json", code_of(read_snapshot_evidence, not_json, key=key))
    unknown_schema = TEMP / "unknown.fernet"
    unknown_schema.write_bytes(Fernet(key).encrypt(b'{"schema_version":"x"}'))
    record(
        "unknown_schema",
        "snapshot_schema_version_invalid:schema_version",
        code_of(read_snapshot_evidence, unknown_schema, key=key),
    )
    bad_writer = SnapshotWriter(root_dir=TEMP / "badkind", key=Fernet.generate_key(), bindings=BINDINGS)
    record(
        "fixture_kind_invalid",
        "snapshot_fixture_kind_invalid",
        code_of(SnapshotWriter, root_dir=TEMP / "badkind2", key=Fernet.generate_key(), bindings=BINDINGS, fixture_kind="production"),
    )
    record(
        "encryption_required",
        "snapshot_encryption_required",
        code_of(SnapshotWriter, root_dir=TEMP / "nokey", key=b"", bindings=BINDINGS),
    )
    failed_writer = SnapshotWriter(root_dir=TEMP / "inactive", key=Fernet.generate_key(), bindings=BINDINGS)
    failed_writer.status = "failed"
    record(
        "write_failed",
        "snapshot_write_failed:writer_not_active",
        code_of(failed_writer.write_snapshot, copy.deepcopy(SNAPSHOTS[1])),
    )
    bad_manifest = copy.deepcopy(manifest)
    bad_manifest["snapshot_count"] = 99
    bad_manifest["content_sha256"] = sha256_hex(
        canonical_json_bytes({k: v for k, v in bad_manifest.items() if k != "content_sha256"})
    )
    record(
        "manifest_count_mismatch",
        "snapshot_manifest_count_mismatch:snapshot_count",
        code_of(validate_snapshot_manifest, bad_manifest, expected_bindings=BINDINGS),
    )
    return finalize()


def finalize() -> int:
    # ---- 7. 四个“未构造反例”的防御码：可达性实验 ----
    # 7a io_failed：真实的底层文件系统失败（不是故障注入）
    io_writer = SnapshotWriter(root_dir=TEMP / "iofail", key=Fernet.generate_key(), bindings=BINDINGS, run_name="run")
    (TEMP / "iofail" / "run").write_text("blocks-directory", encoding="utf-8")
    record(
        "io_failed_reachable",
        "snapshot_io_failed",
        code_of(io_writer.write_snapshot, copy.deepcopy(SNAPSHOTS[1])),
        kind="defensive-reachability",
        detail="以文件占位 run 目录，mkpath 抛 OSError，收敛为 snapshot_io_failed",
    )
    # 7b readback_mismatch：故障注入（替换读回函数返回被篡改对象）
    original_read = mod.read_snapshot_evidence
    def tampered_read(*args, **kwargs):
        payload = original_read(*args, **kwargs)
        payload["captured_utc"] = "2026-11-14T12:00:09+00:00"
        return payload
    mod.read_snapshot_evidence = tampered_read  # type: ignore[assignment]
    try:
        rb_writer = SnapshotWriter(root_dir=TEMP / "rbfail", key=Fernet.generate_key(), bindings=BINDINGS)
        record(
            "readback_mismatch_fault_injection",
            "snapshot_readback_mismatch",
            code_of(rb_writer.write_snapshot, copy.deepcopy(SNAPSHOTS[1])),
            kind="defensive-reachability",
            detail="读回对象被注入一处篡改；写后逐字节比对触发",
        )
    finally:
        mod.read_snapshot_evidence = original_read  # type: ignore[assignment]

    # 7c run_binding_absent / unexpected：先证明被冻结校验遮蔽，再证明分支本身可用
    live_bindings = dict(BINDINGS)
    live_bindings["fixture_kind"] = "live_h2"
    live_evidence = evidence(1)
    live_evidence["schema_version"] = "p2-hard-evidence-capture/v0.3-live"
    live_evidence["fixture_kind"] = "live_h2"
    live_evidence["bindings"] = dict(live_evidence["bindings"])
    live_evidence["bindings"]["fixture_kind"] = "live_h2"
    live_evidence.pop("run_binding", None)
    record(
        "run_binding_absent_shadowed",
        "snapshot_source_evidence_invalid",
        code_of(build_identity_snapshot, turn_evidence=live_evidence, bindings=live_bindings),
        kind="defensive-shadowing",
        detail="冻结 validate_turn_evidence 的 live 必填 run_binding 先行拒绝",
    )
    local_with_run = evidence(1)
    local_with_run["run_binding"] = {"run_id": BINDINGS["run_id"], "business_date": "2026-09-01"}
    record(
        "run_binding_unexpected_shadowed",
        "snapshot_source_evidence_invalid",
        code_of(build_identity_snapshot, turn_evidence=local_with_run, bindings=BINDINGS),
        kind="defensive-shadowing",
        detail="冻结校验对 local_mock 的 run_binding_not_allowed 先行拒绝",
    )
    original_validate = mod.validate_turn_evidence
    mod.validate_turn_evidence = lambda *args, **kwargs: None  # type: ignore[assignment]
    try:
        record(
            "run_binding_absent_fault_injection",
            "snapshot_run_binding_absent:binding.run_binding_sha256",
            code_of(build_identity_snapshot, turn_evidence=live_evidence, bindings=live_bindings),
            kind="defensive-reachability",
            detail="仅当冻结前置校验被旁路时可达（证明分支非死码）",
        )
        record(
            "run_binding_unexpected_fault_injection",
            "snapshot_run_binding_unexpected:binding.run_binding_sha256",
            code_of(build_identity_snapshot, turn_evidence=local_with_run, bindings=BINDINGS),
            kind="defensive-reachability",
            detail="仅当冻结前置校验被旁路时可达",
        )
    finally:
        mod.validate_turn_evidence = original_validate  # type: ignore[assignment]

    families = {item["expected"].split(":", 1)[0] for item in RESULTS}
    triggered = {item["observed"].split(":", 1)[0] for item in RESULTS if item["ok"]}
    code_table = set(mod.FAIL_CLOSED_CODES)
    guard.assert_clean()
    result = {
        "probe": "fail-closed",
        "counterexamples": len([i for i in RESULTS if i["kind"] == "counterexample"]),
        "defensive_experiments": len([i for i in RESULTS if i["kind"] != "counterexample"]),
        "expected_families": len(families),
        "triggered_families": len(triggered),
        "untouched_code_families": sorted(code_table - triggered),
        "unexpected_families_not_in_table": sorted(triggered - code_table),
        "failures": [item for item in RESULTS if not item["ok"]],
        "results": RESULTS,
        "netguard": guard.snapshot(),
        "verdict": "PASS" if all(item["ok"] for item in RESULTS) else "FAIL",
    }
    (HERE / "out" / "03-failclosed.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "counterexamples": result["counterexamples"],
                "defensive_experiments": result["defensive_experiments"],
                "triggered_families": result["triggered_families"],
                "untouched_code_families": result["untouched_code_families"],
                "failures": result["failures"],
                "verdict": result["verdict"],
            },
            ensure_ascii=False,
            indent=1,
        )
    )
    return 0 if result["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

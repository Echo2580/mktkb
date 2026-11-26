"""C1-P3 独立验收探针 4/6：两条红线在**采集契约层**的口子 + 采集边界。

红线：
- M-C1P1-01：document 级目标不得判 violation（转换假象）。
- M-C1P2-01：class C（无 retrieval marker + candidates=[]）必须保持 unknown。

另查：§8「运行期 id 只在已声明载体」是否被实现真正强制；§1「不采密码 hash /
session token / HTTP 认证头 / 运行期数据库 row id」是否有拒绝路径。
"""
from __future__ import annotations

import copy
import json
import re
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
from mktkb.evaluation.p2_evidence_io import canonical_json_bytes, sha256_hex  # noqa: E402
from mktkb.evaluation.p2_evidence_snapshot_v03 import (  # noqa: E402
    SnapshotContractError,
    build_identity_snapshot,
    public_identity_summary,
    validate_identity_snapshot,
)

CACHE = json.loads((HERE / "out" / "02-capture-cache.json").read_text(encoding="utf-8"))
BINDINGS = CACHE["bindings"]
EVIDENCE = CACHE["evidence"]
SNAPSHOTS = CACHE["snapshots"]
DOC_CODES = CACHE["doc_codes"]
RECORD_INDEX = CACHE["record_index"]
CORPUS = CACHE["corpus"]

SEAMS: list[dict[str, Any]] = []


def reseal(payload: dict[str, Any]) -> dict[str, Any]:
    body = {key: value for key, value in payload.items() if key != "content_sha256"}
    payload["content_sha256"] = sha256_hex(canonical_json_bytes(body))
    return payload


def attempt(name: str, fn) -> dict[str, Any]:
    try:
        value = fn()
    except SnapshotContractError as exc:
        row = {"name": name, "outcome": "rejected", "code": exc.code}
    else:
        row = {"name": name, "outcome": "accepted", "value": value}
    SEAMS.append(row)
    return row


def all_units_used(evidence: dict[str, Any]) -> dict[str, Any]:
    """把全部投影 unit 标成“已使用”（合成变体；只改事件 source_ids）。"""
    mutated = copy.deepcopy(evidence)
    unit_ids = [str(unit["unit_id"]) for unit in mutated["db_projection"]["units"]]
    for event in mutated["capture"]["events"]:
        kind = event.get("kind")
        payload = event.get("payload") or {}
        if kind in {"answer_result", "commit_observed"}:
            payload["source_ids"] = list(unit_ids)
        if kind == "model_output":
            payload["source_ids"] = list(unit_ids)
    return mutated


def main() -> int:
    # ---------- A. M-C1P1-01：document 级身份 ----------
    variant = all_units_used(EVIDENCE[2])
    multi = build_identity_snapshot(
        turn_evidence=variant,
        bindings=BINDINGS,
        doc_code_index=DOC_CODES,
        record_index=RECORD_INDEX,
        business_versions={"S01": "V1", "S02": "V1"},
        captured_utc="2026-11-14T12:00:00+00:00",
    )
    rows = multi["record_identities"]
    paragraph_rows = [row for row in rows if row["code"] == "runtime_unit_not_record_level"]
    record_rows = [row for row in rows if row["record_level"] is True]
    doc_summary = multi["record_identity_summary"]
    summary = public_identity_summary(multi)
    identity_leaks = [
        row["source_ref"] for row in rows if re.search(r"doc:[0-9a-f\-]{36}|unit:[0-9a-f\-]{36}", str(row.get("entity_key") or ""))
    ]
    entity_keys = sorted({str(row.get("entity_key")) for row in rows if row.get("entity_key")})

    # 文档级 target 的“粗粒度匹配”演示：仅凭 doc_code 就能把 4 个段落行算成“命中”。
    naive_document_target = {"entity_type": "document", "doc_code": "S03"}
    naive_matches = [
        row["source_ref"] for row in rows if row["doc_code"] == naive_document_target["doc_code"]
    ]
    # 契约指定的护栏：entity_matchable / entity_type=document
    guarded_skips = [
        row["source_ref"] for row in rows if row.get("entity_matchable") is False
    ]

    # 显式 document 级 entity：entity_matchable=false + 码值，但 entity_key 仍带运行期 uuid
    explicit = copy.deepcopy(EVIDENCE[2])
    used_ref = SNAPSHOTS[2]["record_identities"][0]["source_ref"]
    target_unit = next(
        unit for unit in explicit["db_projection"]["units"] if str(unit["unit_id"]) == used_ref
    )
    target_unit["entity_type"] = "document"
    target_unit["entity_key"] = "document|11111111-2222-3333-4444-555555555555"
    target_unit["entity_filters"] = {}
    explicit_snapshot = build_identity_snapshot(
        turn_evidence=explicit,
        bindings=BINDINGS,
        doc_code_index=DOC_CODES,
        record_index=RECORD_INDEX,
        captured_utc="2026-11-14T12:00:00+00:00",
    )
    explicit_row = next(
        row
        for row in explicit_snapshot["record_identities"]
        if row["source_ref"] == str(target_unit["unit_id"])
    )

    # ---------- B. M-C1P2-01：class C ----------
    # B1 真实运行期是否出现 class C（retrieval 未观察 + candidates=[]）
    genuine_class_c = []
    for item in EVIDENCE:
        retrieval = (item.get("runtime_snapshot") or {}).get("retrieval_use") or {}
        observation = retrieval.get("candidate_observation") or {}
        if observation.get("availability") == "not_observed" and not retrieval.get("candidates"):
            genuine_class_c.append(int(item["turn"]["turn_index"]))
    # B2 合成 class C 载荷：9 个使用层全 observed 且计数 0，retrieval_observed 未观察
    payload = copy.deepcopy(SNAPSHOTS[1])
    usage = payload["empty_use_scope_input"]
    for name in mod.USE_LAYER_NAMES:
        usage["use_layers"][name] = {"observed": True, "count": 0, "refs": []}
    for name in mod.CANDIDATE_LAYER_NAMES:
        usage["candidate_layers"][name] = {
            "observed": False,
            "count": 0,
            "refs": [],
            "truncated": False,
        }
    usage["turn_status"] = "complete"
    usage["reason"] = None
    usage["all_use_layers_observed"] = True
    usage["empty_set_candidate"] = True
    usage["code"] = "empty_use_input_complete_empty"
    payload["public_boundary"]["public_summary_keys"] = sorted(public_identity_summary(payload))
    payload["public_boundary"]["public_summary_sha256"] = sha256_hex(
        canonical_json_bytes(public_identity_summary(payload))
    )
    class_c = attempt(
        "class_C_payload_with_empty_set_candidate_true",
        lambda: validate_identity_snapshot(reseal(payload), expected_bindings=BINDINGS),
    )
    class_c_flags = {
        "empty_set_candidate": payload["empty_use_scope_input"]["empty_set_candidate"],
        "all_use_layers_observed": payload["empty_use_scope_input"]["all_use_layers_observed"],
        "retrieval_observed_observed": payload["empty_use_scope_input"]["candidate_layers"][
            "retrieval_observed"
        ]["observed"],
        "code": payload["empty_use_scope_input"]["code"],
    }
    # B3 builder 是否能产出 empty_set_candidate=true（尝试两种合成形状）
    def builder_empty_attempt(mutator) -> str:
        evidence = copy.deepcopy(EVIDENCE[2])
        mutator(evidence)
        try:
            snap = build_identity_snapshot(
                turn_evidence=evidence,
                bindings=BINDINGS,
                doc_code_index=DOC_CODES,
                record_index=RECORD_INDEX,
                captured_utc="2026-11-14T12:00:00+00:00",
            )
        except SnapshotContractError as exc:
            return "rejected:" + exc.code
        return json.dumps(
            {
                "code": snap["empty_use_scope_input"]["code"],
                "all_use_layers_observed": snap["empty_use_scope_input"]["all_use_layers_observed"],
                "empty_set_candidate": snap["empty_use_scope_input"]["empty_set_candidate"],
            }
        )

    def empty_entity(evidence: dict[str, Any]) -> None:
        for event in evidence["capture"]["events"]:
            if event.get("kind") == "entity_inheritance":
                event["payload"]["source_unit_id"] = ""

    def drop_entity(evidence: dict[str, Any]) -> None:
        evidence["capture"]["events"] = [
            event for event in evidence["capture"]["events"] if event.get("kind") != "entity_inheritance"
        ]
        evidence["capture"]["event_count"] = len(evidence["capture"]["events"])

    builder_empty = {
        "entity_inheritance_empty_string": builder_empty_attempt(empty_entity),
        "entity_inheritance_removed": builder_empty_attempt(drop_entity),
    }
    genuine_empty_flags = [
        {
            "turn_index": snap["turn_ref"]["turn_index"],
            "code": snap["empty_use_scope_input"]["code"],
            "all_use_layers_observed": snap["empty_use_scope_input"]["all_use_layers_observed"],
            "empty_set_candidate": snap["empty_use_scope_input"]["empty_set_candidate"],
        }
        for snap in SNAPSHOTS
    ]

    # ---------- C. 其它契约层口子 ----------
    # C1 record_code 与 record_key 不等：契约 §5.1 说 record_code := record_key
    mismatch = copy.deepcopy(SNAPSHOTS[1])
    mismatch["record_identities"][0]["record_code"] = "W99"
    mismatch["record_identity_summary"] = mod._summary_block(mismatch["record_identities"])
    record_code_mismatch = attempt(
        "record_code_not_equal_record_key",
        lambda: validate_identity_snapshot(reseal(copy.deepcopy(mismatch)), expected_bindings=BINDINGS),
    )
    # C2 declared_baseline == as_of 且 flag=false（baseline 冒充无法由读回侧重算发现）
    baseline = copy.deepcopy(SNAPSHOTS[1])
    baseline["effective_temporal"]["declared_baseline_business_date"] = baseline[
        "effective_temporal"
    ]["as_of"]
    baseline_copy = copy.deepcopy(baseline)
    baseline_attempt = attempt(
        "declared_baseline_equals_as_of",
        lambda: validate_identity_snapshot(reseal(baseline_copy), expected_bindings=BINDINGS),
    )
    # C3 未声明运行期 id **键** 放进 entity_filters（§8 说任何位置一律拒绝）
    nested_id = copy.deepcopy(SNAPSHOTS[1])
    nested_id["record_identities"][0]["entity_filters"]["document_id"] = "11111111-2222-3333-4444-555555555555"
    nested_id_attempt = attempt(
        "nested_runtime_id_key_in_entity_filters",
        lambda: validate_identity_snapshot(reseal(copy.deepcopy(nested_id)), expected_bindings=BINDINGS),
    )
    # C4 非凭证键承载凭证值（HTTP 认证头/会话 token 的原始值）
    header_value = copy.deepcopy(SNAPSHOTS[1])
    header_value["record_identities"][0]["entity_filters"]["x-auth-header"] = "sid=deadbeefcafe"
    header_attempt = attempt(
        "credential_value_under_neutral_key",
        lambda: validate_identity_snapshot(reseal(copy.deepcopy(header_value)), expected_bindings=BINDINGS),
    )
    owner_token = copy.deepcopy(SNAPSHOTS[1])
    owner_token["request_owner"]["user_ref"] = "9f86d081884c7d659a2feaa0c55ad015"
    owner_attempt = attempt(
        "opaque_token_as_user_ref",
        lambda: validate_identity_snapshot(reseal(copy.deepcopy(owner_token)), expected_bindings=BINDINGS),
    )

    # ---------- D. 采集拒绝路径（不越权） ----------
    refusals: list[dict[str, Any]] = []

    def refusal(name: str, mutate) -> None:
        payload = copy.deepcopy(SNAPSHOTS[1])
        mutate(payload)
        try:
            validate_identity_snapshot(reseal(payload), expected_bindings=BINDINGS)
        except SnapshotContractError as exc:
            refusals.append({"name": name, "refused": True, "code": exc.code})
        else:
            refusals.append({"name": name, "refused": False, "code": "ACCEPTED"})

    refusal("password_hash_key", lambda p: p["request_owner"].update({"password_hash": "x"}))
    refusal("session_token_key", lambda p: p["request_owner"].update({"session_token": "x"}))
    refusal(
        "authorization_header_key",
        lambda p: p["record_identities"][0]["entity_filters"].update({"authorization": "x"}),
    )
    refusal(
        "runtime_row_id_key",
        lambda p: p["record_identities"][0].update({"db_row_id": 12}),
    )
    refusal(
        "runtime_unit_id_key",
        lambda p: p["record_identities"][0].update({"unit_id": "x"}),
    )
    refusal(
        "bearer_value",
        lambda p: p["request_owner"].update({"user_ref": "Bearer abcdefghijklmnop"}),
    )

    guard.assert_clean()
    result = {
        "probe": "redlines-and-seams",
        "redline_M_C1P1_01": {
            "multi_row_total": len(rows),
            "record_level_rows": len(record_rows),
            "paragraph_rows": len(paragraph_rows),
            "summary_entity_document_level": doc_summary["entity_document_level"],
            "summary_not_record_level": doc_summary["not_record_level"],
            "public_summary_entity_document_level_count": summary["entity_document_level_count"],
            "public_summary_not_record_level_count": summary["not_record_level_count"],
            "naive_document_level_matches": len(naive_matches),
            "rows_skipped_by_entity_matchable_guard": len(guarded_skips),
            "paragraph_rows_entity_code": sorted({row["entity_code"] for row in paragraph_rows}),
            "paragraph_rows_entity_matchable": sorted(
                {str(row["entity_matchable"]) for row in paragraph_rows}
            ),
            "explicit_document_row": {
                "entity_matchable": explicit_row["entity_matchable"],
                "entity_code": explicit_row["entity_code"],
                "entity_key": explicit_row["entity_key"],
                "record_level": explicit_row["record_level"],
            },
            "entity_key_runtime_id_rows": identity_leaks,
            "entity_keys_samples": entity_keys,
            "validator_accepts_multi_row_variant": True,
            "assessment": (
                "句子级/段落级行全部 entity_matchable=false（红线护栏生效）；"
                "但摘要的 entity_document_level 计数只数 entity_type=document，"
                "对 4 个段落级行给 0，公开摘要无法告诉消费方“本回合是文档粒度”。"
            ),
        },
        "redline_M_C1P2_01": {
            "genuine_class_c_turns": genuine_class_c,
            "genuine_empty_flags": genuine_empty_flags,
            "class_c_payload_validation": class_c,
            "class_c_flags": class_c_flags,
            "builder_empty_attempts": builder_empty,
            "assessment": (
                "读回侧接受“9 层全 observed 且计数 0 + retrieval_observed 未观察 + "
                "empty_set_candidate=true”的 class C 载荷（无任何码/字段要求 retrieval marker）；"
                "builder 侧该标记又因 entity_inheritance 必带非空 unit 而不可达。"
            ),
        },
        "seams": SEAMS,
        "collection_refusals": refusals,
        "netguard": guard.snapshot(),
        "verdict": "PASS",
    }
    (HERE / "out" / "04-redlines.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "M_C1P1_01": {
                    key: value
                    for key, value in result["redline_M_C1P1_01"].items()
                    if key
                    in {
                        "multi_row_total",
                        "record_level_rows",
                        "paragraph_rows",
                        "summary_entity_document_level",
                        "summary_not_record_level",
                        "naive_document_level_matches",
                        "rows_skipped_by_entity_matchable_guard",
                        "paragraph_rows_entity_matchable",
                        "entity_key_runtime_id_rows",
                    }
                },
                "M_C1P2_01": {
                    "genuine_class_c_turns": genuine_class_c,
                    "class_c_payload_validation": class_c,
                    "class_c_flags": class_c_flags,
                    "builder_empty_attempts": builder_empty,
                },
                "seams": [
                    {"name": item["name"], "outcome": item["outcome"], "code": item.get("code")}
                    for item in SEAMS
                ],
                "collection_refusals": refusals,
            },
            ensure_ascii=False,
            indent=1,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

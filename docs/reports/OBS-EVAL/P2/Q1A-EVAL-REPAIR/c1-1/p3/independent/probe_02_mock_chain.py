"""C1-P3 独立验收探针 2/6：合成租户/文档的 Mock 全链重跑。

独立复现「采集 → 加密落盘（仓外）→ 读回 → 校验」，并逐叶比较构造对象与读回对象；
再对三组关键字段（record_code / as_of / 空使用集输入）做**从磁盘读回对象**上的断言。
同时把合成证据缓存到 out/02-capture-cache.json，供后续反例探针复用。
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import netguard_independent as guard  # noqa: E402

guard.install()

import capture_harness as harness  # noqa: E402
import synth_corpus  # noqa: E402
from mktkb.evaluation.p2_evidence_io import canonical_json_bytes, sha256_hex  # noqa: E402
from mktkb.evaluation.p2_evidence_snapshot_v03 import (  # noqa: E402
    PUBLIC_SUMMARY_KEYS,
    SnapshotWriter,
    build_identity_snapshot,
    build_snapshot_manifest,
    public_identity_summary,
    read_snapshot_evidence,
    validate_identity_snapshot,
)

FIXED_TIME = "2026-11-14T12:00:00+00:00"
DOC_CODES = {"synth_stock.xlsx": "S01", "synth_loose.xlsx": "S02", "synth_flow.docx": "S03"}


def record_index(corpus: dict[str, Any]) -> list[dict[str, Any]]:
    rows = [
        {
            "doc_code": "S01",
            "sheet": corpus["stock_sheet"],
            "row": item["row"],
            "record_key": item["record_key"],
            "business_version": "V1",
        }
        for item in corpus["stock_rows"]
    ]
    rows += [
        {
            "doc_code": "S02",
            "sheet": corpus["loose_sheet"],
            "row": item["row"],
            "record_key": item["record_key"],
            "business_version": "V1",
        }
        for item in corpus["loose_rows"]
    ]
    return rows


def leaves(value: Any, prefix: str = "") -> dict[str, Any]:
    flat: dict[str, Any] = {}
    if isinstance(value, dict):
        for key, item in value.items():
            flat.update(leaves(item, f"{prefix}.{key}" if prefix else str(key)))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            flat.update(leaves(item, f"{prefix}[{index}]"))
    else:
        flat[prefix] = value
    return flat


def main() -> int:
    temp = Path(tempfile.mkdtemp(prefix="c1p3-independent-chain-"))
    corpus = synth_corpus.build(temp / "corpus")
    capture = harness.capture(temp / "capture", corpus, run_id="independent-chain")
    evidence = capture["evidence"]
    bindings = capture["bindings"]
    assert len(evidence) == 3, f"expected 3 turns, got {len(evidence)}"

    snapshots = [
        build_identity_snapshot(
            turn_evidence=item,
            bindings=bindings,
            doc_code_index=DOC_CODES,
            record_index=record_index(corpus),
            business_versions={"S01": "V1", "S02": "V1"},
            captured_utc=FIXED_TIME,
        )
        for item in evidence
    ]
    writer = SnapshotWriter(
        root_dir=temp / "snapshots",
        key=capture["writer"].key,
        bindings=bindings,
        run_name="independent-chain",
    )
    receipts = [writer.write_snapshot(snapshot) for snapshot in snapshots]
    readback = [
        read_snapshot_evidence(
            Path(receipt["path"]),
            key=writer.key,
            expected_bindings=bindings,
            expected_turn={
                "turn_index": snapshot["turn_ref"]["turn_index"],
                "client_request_id": snapshot["turn_ref"]["client_request_id"],
                "conversation_id": snapshot["turn_ref"]["conversation_id"],
            },
            source_evidence=item,
        )
        for receipt, snapshot, item in zip(receipts, snapshots, evidence)
    ]
    manifest = build_snapshot_manifest(
        fixture_kind="local_mock",
        bindings=bindings,
        started_utc=FIXED_TIME,
        snapshots=snapshots,
    )
    manifest_receipt = writer.write_manifest(manifest)
    manifest_back = read_snapshot_evidence(
        Path(manifest_receipt["path"]), key=writer.key, expected_bindings=bindings
    )

    checks: list[dict[str, Any]] = []

    def check(name: str, condition: bool, detail: Any = None) -> None:
        checks.append({"name": name, "ok": bool(condition), "detail": detail})

    leaf_total = 0
    for built, back, receipt in zip(snapshots, readback, receipts):
        built_leaves, back_leaves = leaves(built), leaves(back)
        leaf_total += len(built_leaves)
        check(
            f"leaf_equality_turn_{built['turn_ref']['turn_index']}",
            built_leaves == back_leaves,
            {"leaves": len(built_leaves)},
        )
        path = Path(receipt["path"])
        token = path.read_bytes()
        check("ciphertext_exists", path.is_file(), {"bytes": len(token)})
        check("ciphertext_not_plaintext", token != json.dumps(built).encode("utf-8"))
        for needle in (
            harness.QUESTION_FLOW,
            harness.QUESTION_STOCK,
            harness.QUESTION_LOOSE,
            "synth_stock.xlsx",
            "synth_loose.xlsx",
            "synth_flow.docx",
            harness.USER,
        ):
            check(
                f"ciphertext_free_of:{needle[:12]}",
                needle.encode("utf-8") not in token,
            )
        summary = public_identity_summary(back)
        summary_text = json.dumps(summary, ensure_ascii=False)
        check("public_summary_keys_25", sorted(summary) == list(PUBLIC_SUMMARY_KEYS), len(summary))
        check(
            "public_summary_sha_bound",
            back["public_boundary"]["public_summary_sha256"]
            == sha256_hex(canonical_json_bytes(summary)),
            None,
        )
        for needle in (
            harness.USER,
            "synth_stock.xlsx",
            harness.BUSINESS_DATE,
            back["turn_ref"]["client_request_id"],
        ):
            check(f"public_summary_free_of:{needle[:12]}", str(needle) not in summary_text)
        validate_identity_snapshot(
            back,
            expected_bindings=bindings,
            expected_turn={
                "turn_index": back["turn_ref"]["turn_index"],
                "client_request_id": back["turn_ref"]["client_request_id"],
                "conversation_id": back["turn_ref"]["conversation_id"],
            },
            source_evidence=evidence[back["turn_ref"]["turn_index"]],
        )

    # ---- 三组关键字段：只从磁盘读回对象上取证 ----
    stock_turn = next(row for row in readback if row["turn_ref"]["turn_index"] == 1)
    stock_rows = [
        row
        for row in stock_turn["record_identities"]
        if row["record_level"] is True
    ]
    check("record_code_persisted", bool(stock_rows), len(stock_rows))
    check(
        "record_code_value",
        any(row["record_code"] == "W01" for row in stock_rows),
        [row["record_code"] for row in stock_rows],
    )
    target = next(row for row in stock_rows if row["record_code"] == "W01")
    check(
        "record_identity_fields",
        target["doc_code"] == "S01"
        and target["base_doc_code"] == "S01"
        and target["sheet"] == corpus["stock_sheet"]
        and target["row"] == 2
        and target["record_key"] == "W01"
        and target["code"] == "record_row_reverse_lookup"
        and target["entity_type"] == "item"
        and target["entity_key"] == "item|id:w01"
        and target["entity_matchable"] is True,
        {key: target[key] for key in ("doc_code", "sheet", "row", "record_key", "entity_key", "entity_code")},
    )
    check(
        "as_of_persisted",
        stock_turn["effective_temporal"]["as_of"] == harness.BUSINESS_DATE
        and stock_turn["effective_temporal"]["as_of_source"] == "plan_observed",
        {
            "as_of": stock_turn["effective_temporal"]["as_of"],
            "source": stock_turn["effective_temporal"]["as_of_source"],
        },
    )
    check(
        "baseline_never_effective",
        stock_turn["effective_temporal"]["baseline_used_as_effective"] is False
        and stock_turn["effective_temporal"]["declared_baseline_business_date"] is None,
    )
    usage = stock_turn["empty_use_scope_input"]
    check(
        "empty_use_layers_9x3",
        len(usage["use_layers"]) == 9 and len(usage["candidate_layers"]) == 3,
        {"use": len(usage["use_layers"]), "candidate": len(usage["candidate_layers"])},
    )
    check(
        "empty_use_nonempty_declared",
        usage["code"] == "empty_use_input_nonempty"
        and usage["empty_set_candidate"] is False
        and any(layer["count"] > 0 for layer in usage["use_layers"].values()),
        {name: layer["count"] for name, layer in usage["use_layers"].items()},
    )
    check(
        "empty_use_candidates_not_use",
        usage["candidate_layers"]["retrieval_observed"]["observed"] is True
        and usage["candidate_layers"]["retrieval_observed"]["count"] >= 1,
        usage["candidate_layers"]["retrieval_observed"]["count"],
    )
    check(
        "manifest_roundtrip",
        manifest_back["snapshot_count"] == 3
        and [row["turn_index"] for row in manifest_back["turns"]] == [0, 1, 2],
        [row["turn_index"] for row in manifest_back["turns"]],
    )
    check("outbound_zero", capture["outbound_attempts"] == 0, capture["outbound_attempts"])
    guard.assert_clean()
    netguard = guard.snapshot()
    check("netguard_external_zero", netguard["external_attempts"] == 0, netguard["counts"])

    # ---- 供后续探针复用的合成缓存（不含私有数据）----
    cache = {
        "bindings": bindings,
        "evidence": evidence,
        "snapshots": snapshots,
        "doc_codes": DOC_CODES,
        "record_index": record_index(corpus),
        "corpus": {
            "stock_sheet": corpus["stock_sheet"],
            "loose_sheet": corpus["loose_sheet"],
            "stock_rows": corpus["stock_rows"],
            "loose_rows": corpus["loose_rows"],
        },
        "questions": {
            "flow": harness.QUESTION_FLOW,
            "stock": harness.QUESTION_STOCK,
            "loose": harness.QUESTION_LOOSE,
        },
        "business_date": harness.BUSINESS_DATE,
        "user": harness.USER,
        "temp_root": str(temp),
    }
    (HERE / "out" / "02-capture-cache.json").write_text(
        json.dumps(cache, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )

    result = {
        "probe": "mock-full-chain",
        "turns": len(evidence),
        "leaf_total": leaf_total,
        "checks": checks,
        "netguard": netguard,
        "adapter_outbound_attempts": capture["outbound_attempts"],
        "provider_calls": capture["provider_calls"],
        "temp_root": str(temp),
        "verdict": "PASS" if all(item["ok"] for item in checks) else "FAIL",
    }
    (HERE / "out" / "02-mock-chain.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    failed = [item for item in checks if not item["ok"]]
    print(
        json.dumps(
            {
                "probe": result["probe"],
                "turns": result["turns"],
                "leaf_total": leaf_total,
                "checks": len(checks),
                "failed": failed,
                "netguard": netguard["counts"],
                "verdict": result["verdict"],
            },
            ensure_ascii=False,
            indent=1,
        )
    )
    return 0 if result["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

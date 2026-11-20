"""T900 self-written negatives against the frozen cross-scenario gate.

1) wrong binding: make a card's card_file_sha256 equal its aggregate hash.
2) false applicability: forge the attested index revision in a binding proof.
Both are evaluated through the real p2_release_gate API on real inputs.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[7]
sys.path.insert(0, str(ROOT / "backend/src"))
sys.path.insert(0, str(ROOT / "docs/reports/OBS-EVAL/P2/CROSS-SCENARIO-GATE/scripts"))

import wire_real_ncu as W  # noqa: E402
from mktkb.evaluation.p2_release_gate import evaluate_release_gate  # noqa: E402
from mktkb.evaluation.p2_release_model import file_sha256  # noqa: E402

TMP = ROOT / ".tmp-t900-isolated/phase2/negatives"


def write_inputs(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def rows_of(result):
    return {row.row_id: row for row in result.rows}


def main() -> int:
    work = TMP / "base"
    inputs, payload = W.build_inputs(work)
    control = evaluate_release_gate(inputs)
    control_rows = rows_of(control)

    # --- negative 1: card_file_sha256 == aggregate hash -------------------
    index_path = ROOT / payload["h2"]["cards_index"]["path"]
    index = json.loads(index_path.read_text("utf-8"))
    aggregate = json.loads(
        (ROOT / payload["h2"]["composition_aggregate"]["path"]).read_text("utf-8")
    )
    swapped = json.loads(json.dumps(index))
    swapped["cards"][0]["card_sha256"] = aggregate["cards"][0]["aggregate_sha256"]
    swapped_path = work / "cards-index-wrong-binding.json"
    swapped_path.write_text(json.dumps(swapped, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    wrong_payload = json.loads(json.dumps(payload))
    wrong_payload["h2"]["cards_index"] = {
        "path": str(swapped_path.relative_to(ROOT)),
        "sha256": file_sha256(swapped_path),
    }
    wrong_inputs = write_inputs(work / "inputs-wrong-binding.json", wrong_payload)
    wrong = evaluate_release_gate(wrong_inputs)
    wrong_rows = rows_of(wrong)

    # --- negative 2: forged attested index revision ----------------------
    forged_payload = json.loads(json.dumps(payload))
    proof_dir = work / "binding-proofs"
    proof_path = proof_dir / "binding-p2-t207-r1-20261111-01.json"
    proof = json.loads(proof_path.read_text("utf-8"))
    proof["attested_index_revision"] = 99
    forged_proof_path = work / "binding-proof-forged-attested.json"
    forged_proof_path.write_text(json.dumps(proof, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    forged_sha = file_sha256(forged_proof_path)
    for run in forged_payload["public"]["runs"]:
        ref = run.get("binding_proof") or {}
        if ref.get("path", "").endswith("binding-p2-t207-r1-20261111-01.json"):
            run["binding_proof"] = {
                "path": str(forged_proof_path.relative_to(ROOT)),
                "sha256": forged_sha,
            }
    for ref in (forged_payload.get("u", {}).get("real") or {}).get("binding_proof"),:
        if ref and ref.get("path", "").endswith("binding-p2-t207-r1-20261111-01.json"):
            ref["path"] = str(forged_proof_path.relative_to(ROOT))
            ref["sha256"] = forged_sha
    forged_inputs = write_inputs(work / "inputs-forged-attested.json", forged_payload)
    forged = evaluate_release_gate(forged_inputs)
    forged_rows = rows_of(forged)

    report = {
        "control": {
            "decision": control.decision,
            "h2.cards_index": control_rows.get("h2.cards_index").decision
            if control_rows.get("h2.cards_index") else None,
        },
        "wrong_binding": {
            "decision": wrong.decision,
            "row": "h2.cards_index",
            "row_decision": wrong_rows["h2.cards_index"].decision,
            "reasons": list(wrong_rows["h2.cards_index"].reasons),
            "detail": wrong_rows["h2.cards_index"].detail,
            "card0_file_sha": swapped["cards"][0]["card_sha256"],
            "card0_aggregate_sha": aggregate["cards"][0]["aggregate_sha256"],
        },
        "forged_attested": {
            "decision": forged.decision,
            "binding_row": "binding.p2-t207-r1-20261111-01",
            "row_decision": forged_rows["binding.p2-t207-r1-20261111-01"].decision,
            "reasons": list(forged_rows["binding.p2-t207-r1-20261111-01"].reasons),
            "detail": forged_rows["binding.p2-t207-r1-20261111-01"].detail,
            "declared_attested": 99,
            "actual_attested": 12,
        },
    }
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if out is not None:
        out.write_text(text + "\n", encoding="utf-8")
    print(text)
    ok = (
        control.decision == "pass"
        and wrong.decision == "blocked"
        and wrong_rows["h2.cards_index"].decision == "blocked"
        and "release_identity_mismatch" in wrong_rows["h2.cards_index"].reasons
        and forged.decision == "blocked"
        and forged_rows["binding.p2-t207-r1-20261111-01"].decision == "blocked"
        and "release_binding_attestation_invalid"
        in forged_rows["binding.p2-t207-r1-20261111-01"].reasons
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

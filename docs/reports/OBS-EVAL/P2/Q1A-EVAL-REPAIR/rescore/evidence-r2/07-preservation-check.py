"""Q1a-3-R2 保全总核：把 protected-compare / netguard / privacy / 聚合身份收成一个结论。

只读取本包 evidence-r2 下已有 JSON 与公开聚合；不重新解密、不打印任何题面/答案/目标值。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[6]
for path in (HERE, REPO / "backend" / "src", REPO / "tools"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import _common_r2 as C  # noqa: E402


def _load(name: str) -> dict:
    return C.strict_json((HERE / name).read_bytes())


def main() -> int:
    compare = _load("04-protected-compare.json")
    netguard = _load("06-netguard.json")
    privacy = _load("05-privacy-scan.json")
    aggregate = C.strict_json(C.PUBLIC_AGGREGATE.read_bytes())
    identity = aggregate["identity"]
    corrections = aggregate["corrections_applied"]
    checks = {
        "identity_overall_match": identity["overall"] == "MATCH",
        "identity_cross_round_all_equal": identity["cross_round"].get("all_equal") is True,
        "hard_evidence_sha_expected": identity["components"]["hard_evidence_module_sha256"]
        == C.EXPECTED["hard_evidence_module_sha256"],
        "hard_evidence_unchanged_during_run": corrections["C_empty_scope_primitive"]["module_unchanged_during_run"]
        is True,
        "contract_ciphertext_bytes": identity["components"]["contract_ciphertext_bytes"] == 47012,
        "protected_difference_zero": compare["difference_count"] == 0,
        "protected_verdict_unchanged": compare["verdict"] == "unchanged",
        "r1_products_unchanged": compare["r1_products"]["unchanged_during_r2"] is True
        and all(compare["expected_ok"].values()),
        "foreign_untracked_tree_equal": compare["foreign_tree_equal"] is True,
        "tracked_modified_15_same": compare["git"]["tracked_modified_same"] is True
        and compare["git"]["tracked_modified_count"] == 15,
        "staged_zero": compare["git"]["staged_count_zero"] is True,
        "commits_zero": compare["git"]["commits_created"] == 0,
        "head_same": compare["git"]["head_same"] is True,
        "branch_same": compare["git"]["branch_same"] is True,
        "netguard_zero": netguard["verdict"] == "zero_network_attempts",
        "netguard_positive_control_blocked": netguard["positive_control"] == "blocked",
        "netguard_counts_zero": sum(netguard["measured_counts"].values()) == 0,
        "privacy_clean": privacy["verdict"] == "clean" and privacy["total_hits"] == 0,
        "calls_all_zero": all(value == 0 for value in aggregate["calls"].values()),
        "unknown_set_to_na_zero": aggregate["cross_entity_27_unknown"]["set_to_not_applicable"]["value"] == 0,
        "claim_scope_fully_resolved_false": aggregate["residual_marks"]["claim_scope_fully_resolved"] is False,
    }
    payload = {
        "schema_version": "q1a3r2-preservation-check/v0.1",
        "checks": checks,
        "passed": sum(1 for value in checks.values() if value),
        "total": len(checks),
        "verdict": "PASS" if all(checks.values()) else "FAIL",
        "calls": {"network": 0, "socket": 0, "dns": 0, "provider": 0, "model": 0, "retrieval": 0, "real": 0},
        "key_facts": {
            "analysis_id": aggregate["analysis_id"],
            "implementation_version": aggregate["implementation_version"],
            "public_aggregate_sha256": C.sha256_hex(C.PUBLIC_AGGREGATE.read_bytes()),
            "public_aggregate_bytes": C.PUBLIC_AGGREGATE.stat().st_size,
            "private_detail_sha256": C.sha256_hex(C.OUT_PRIVATE_FILE.read_bytes()),
            "private_detail_bytes": C.OUT_PRIVATE_FILE.stat().st_size,
            "tracked_modified": compare["git"]["tracked_modified_count"],
            "foreign_untracked_files": compare["foreign_file_count"],
            "protected_items": compare["protected_items"],
            "r1_aggregate_sha256": compare["r1_products"]["aggregate_sha256"],
            "r1_private_detail_sha256": compare["r1_products"]["private_detail_sha256"],
        },
    }
    (HERE / "07-preservation-check.json").write_bytes(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    )
    print(json.dumps({"verdict": payload["verdict"], "passed": payload["passed"], "total": payload["total"]}, ensure_ascii=True))
    return 0 if payload["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

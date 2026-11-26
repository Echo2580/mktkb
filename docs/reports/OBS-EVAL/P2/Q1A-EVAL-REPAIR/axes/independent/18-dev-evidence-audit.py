#!/usr/bin/env python
"""探针 18：开发证据自洽性复核（manifest / pytest / zero-call / protected-after / report 表）。

只读开发证据；不把开发自报当结论，逐项与实际字节/实现比对。
输出：18-dev-evidence-audit.out.json
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from _common import HERE, ROOT, dump

EVID = ROOT / "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/axes/evidence"
DEV_REPORT = ROOT / "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/axes/dev-report.md"
RESULTS: list[dict[str, Any]] = []


def check(label: str, ok: bool, detail: Any = None) -> None:
    RESULTS.append({"label": label, "ok": bool(ok), "detail": detail})


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(name: str) -> dict:
    return json.loads((EVID / name).read_text(encoding="utf-8-sig"))


def uses_os_environ(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    return any(
        isinstance(node, ast.Attribute) and node.attr == "environ" and isinstance(node.value, ast.Name) and node.value.id == "os"
        for node in ast.walk(tree)
    )


def imports_of(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.add(node.module or "")
    return names


def main() -> int:
    manifest = read_json("06-hash-manifest.json")
    check("manifest schema/algorithm", manifest["schema_version"] == "q1a1b-hash-manifest/v1" and manifest["algorithm"] == "sha256", manifest["schema_version"])
    check("manifest lists 13 files", len(manifest["files"]) == 13, len(manifest["files"]))
    mismatches = {
        item["path"]: {"recorded": item["sha256"], "actual": sha(ROOT / item["path"])}
        for item in manifest["files"]
        if not (ROOT / item["path"]).is_file() or sha(ROOT / item["path"]) != item["sha256"]
    }
    check("manifest 13/13 file hashes match actual bytes", mismatches == {}, mismatches)
    recorded = {item["path"]: item["sha256"] for item in manifest["files"]}
    check("manifest module sha == actual", recorded["backend/src/mktkb/evaluation/p2_evidence_rescore_axes.py"] == sha(ROOT / "backend/src/mktkb/evaluation/p2_evidence_rescore_axes.py"))
    check("manifest test sha == actual", recorded["backend/tests/evaluation/test_p2_evidence_rescore_axes.py"] == sha(ROOT / "backend/tests/evaluation/test_p2_evidence_rescore_axes.py"))
    check("manifest contract sha == actual", recorded["docs/evaluation/p2-evidence-rescore-v0_2.md"] == sha(ROOT / "docs/evaluation/p2-evidence-rescore-v0_2.md"))
    check("manifest self_hash_excluded", manifest.get("self_hash_excluded") is True)
    check("manifest commit_or_stage_performed false", manifest.get("commit_or_stage_performed") is False)

    pytest_text = (EVID / "01-pytest.txt").read_text(encoding="utf-8-sig")
    check("01-pytest: 22 collected", "22 tests collected in" in pytest_text)
    check("01-pytest: 22 passed", "22 passed" in pytest_text)
    check("01-pytest: 20 passed (Q1a-1 regression)", "20 passed" in pytest_text)
    check("01-pytest: three EXIT_CODE 0", pytest_text.count("EXIT_CODE: 0") == 3, pytest_text.count("EXIT_CODE: 0"))
    check("01-pytest: no skipped/xfail/error", not any(word in pytest_text for word in ("skipped", "xfail", " failed", "error")), [word for word in ("skipped", "xfail", " failed", "error") if word in pytest_text])
    check("01-pytest hash matches manifest", sha(EVID / "01-pytest.txt") == recorded.get("docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/axes/evidence/01-pytest.txt"))

    zero = read_json("07-zero-call-and-network.json")
    check("zero-call: all call counters zero", all(value == 0 for value in zero["calls"].values()) and len(zero["calls"]) == 9, zero["calls"])
    check("zero-call: module/test/contract sha match actual", zero["module_sha256"] == sha(ROOT / "backend/src/mktkb/evaluation/p2_evidence_rescore_axes.py") and zero["test_sha256"] == sha(ROOT / "backend/tests/evaluation/test_p2_evidence_rescore_axes.py") and zero["contract_sha256"] == sha(ROOT / "docs/evaluation/p2-evidence-rescore-v0_2.md"))
    check("zero-call: real_inputs_read all false", all(value is False for value in zero["real_inputs_read"].values()), zero["real_inputs_read"])
    check("zero-call: staged_or_committed false", zero["staged_or_committed"] is False)
    check("zero-call: netguard external attempts 0 and teardown asserted", zero["runtime_network_guard"]["external_attempts"] == 0 and zero["runtime_network_guard"]["asserted_at_teardown"] is True, zero["runtime_network_guard"])
    check("zero-call: static import scan PASS with no forbidden hits", zero["static_import_scan"]["scan_result"] == "PASS" and zero["static_import_scan"]["matched_forbidden_modules"] == [], zero["static_import_scan"])

    after = read_json("05-protected-hashes-after.json")
    check("after-manifest all_match true", after["all_match"] is True and after["mismatches"] == [], after["mismatches"])
    check("after-manifest evaluator count 35/35", after["evaluator_file_count"] == 35 and after["evaluator_expected_file_count"] == 35)
    for group in ("c_freeze_12", "tracked_modified_15", "q1a1_protected"):
        block = after["groups"][group]
        actual_mismatch = {path: {"recorded": digest, "actual": sha(ROOT / path)} for path, digest in block["items"].items() if sha(ROOT / path) != digest}
        check(f"after-manifest {group}: {block['count']} items match actual", actual_mismatch == {} and block["count"] == len(block["items"]), actual_mismatch)

    entries = read_json("02-synthetic-counterexamples.json")["entries"]
    check("counterexamples: 10 entries", len(entries) == 10, len(entries))
    check("counterexamples: expected starts with new state/reason", all(item["expected"].startswith(f"{item['new']['state']}/{item['new']['reason']}") for item in entries), [item["scenario"] for item in entries if not item["expected"].startswith(f"{item['new']['state']}/{item['new']['reason']}")])
    check("counterexamples: provenance in allowed set", all(item["provenance"] in {"rescored", "preserved_old_verdict"} for item in entries), [item["provenance"] for item in entries])

    # 开发证据脚本：不得联网/读私有/p2_hard_evidence
    forbidden = {"httpx", "requests", "socket", "urllib", "openai", "cryptography", "mktkb.rag", "mktkb.evaluation.p2_hard_evidence", "mktkb.evaluation.product_adapter"}
    for script in ("03-gen-counterexamples.py", "05-verify-protected.py", "07-build-zero-call-evidence.py", "06-build-hash-manifest.py"):
        names = imports_of(EVID / script)
        bad = [name for name in names if any(name == item or name.startswith(item + ".") for item in forbidden)]
        check(f"{script}: no forbidden imports", bad == [], {"imports": sorted(names), "bad": bad})
        check(f"{script}: no os.environ access", not uses_os_environ(EVID / script), script)

    # dev-report 表中的 hash 与实际一致
    report_text = DEV_REPORT.read_text(encoding="utf-8")
    rows = re.findall(r"\|\s*`([0-9a-f]{64})`\s*\|\s*`([^`]+)`\s*\|", report_text)
    table_mismatch = {}
    for digest, path in rows:
        target = DEV_REPORT.parent / path
        if not target.is_file():
            target = ROOT / path
        if not target.is_file():
            table_mismatch[path] = "missing"
        elif sha(target) != digest:
            table_mismatch[path] = {"recorded": digest, "actual": sha(target)}
    check("dev-report hash table rows all match actual bytes", table_mismatch == {}, {"rows": len(rows), "mismatch": table_mismatch})
    check("dev-report table covers >= 11 files", len(rows) >= 11, len(rows))

    payload = {
        "probe": "18-dev-evidence-audit",
        "assertions_total": len(RESULTS),
        "assertions_failed": len([item for item in RESULTS if not item["ok"]]),
        "results": RESULTS,
        "verdict": "PASS" if all(item["ok"] for item in RESULTS) else "FAIL",
    }
    dump(HERE / "18-dev-evidence-audit.out.json", payload)
    print(json.dumps({"assertions": len(RESULTS), "failed": payload["assertions_failed"], "verdict": payload["verdict"]}, ensure_ascii=False))
    if payload["assertions_failed"]:
        print(json.dumps([item for item in RESULTS if not item["ok"]], ensure_ascii=False, indent=2))
    return 0 if payload["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())



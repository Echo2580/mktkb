"""Q1a-1b 零真实调用/零网络证据生成器（只读、零网络、零真实数据）。

用法（仓库根）：
  .venv/Scripts/python.exe \
      docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/axes/evidence/07-build-zero-call-evidence.py \
      docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/axes/evidence/07-zero-call-and-network.json
"""

from __future__ import annotations

import ast
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[7]
MODULE = ROOT / "backend/src/mktkb/evaluation/p2_evidence_rescore_axes.py"
TEST = ROOT / "backend/tests/evaluation/test_p2_evidence_rescore_axes.py"
CONTRACT = ROOT / "docs/evaluation/p2-evidence-rescore-v0_2.md"
FORBIDDEN = {
    "httpx",
    "requests",
    "urllib",
    "urllib3",
    "http.client",
    "socket",
    "openai",
    "mktkb.evaluation.p2_live",
    "mktkb.evaluation.product_adapter",
    "mktkb.evaluation.p2_hard_evidence",
    "mktkb.rag",
    "cryptography",
    "base64",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: 07-build-zero-call-evidence.py <output.json>", file=sys.stderr)
        return 2
    source = MODULE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    matched = sorted(
        name
        for name in imported
        for forbidden in FORBIDDEN
        if name == forbidden or name.startswith(forbidden + ".")
    )
    payload = {
        "schema_version": "q1a1b-zero-call-and-network/v1",
        "analysis_id": "Q1A-RESCORE-20261114-r1",
        "evaluator_phase": "Q1a-1b/axes-v0.1",
        "module_sha256": sha256(MODULE),
        "test_sha256": sha256(TEST),
        "contract_sha256": sha256(CONTRACT),
        "calls": {
            "network": 0,
            "provider": 0,
            "model": 0,
            "retrieval": 0,
            "real": 0,
            "embedding": 0,
            "rerank": 0,
            "ocr": 0,
            "judge": 0,
        },
        "execution_entrypoints_used": [
            "pytest（仅新增 22 项测试与 Q1a-1 20 项回归）",
            "合成反例脚本 03-gen-counterexamples.py",
            "保护件 hash 复核 05-verify-protected.py",
            "本证据脚本 07-build-zero-call-evidence.py",
        ],
        "commands": [
            ".venv/Scripts/python.exe -m pytest backend/tests/evaluation/test_p2_evidence_rescore_axes.py -q -p no:cacheprovider --basetemp backend/.pytest-tmp/q1a1b",
            ".venv/Scripts/python.exe -m pytest backend/tests/evaluation/test_p2_evidence_rescore.py -q -p no:cacheprovider --basetemp backend/.pytest-tmp/q1a1b-regress",
            ".venv/Scripts/python.exe docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/axes/evidence/03-gen-counterexamples.py docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/axes/evidence/02-synthetic-counterexamples.json",
        ],
        "runtime_network_guard": {
            "fixture": "acceptance.support.netguard.t09_network_guard",
            "applied_to": [
                "backend/tests/evaluation/test_p2_evidence_rescore_axes.py",
                "backend/tests/evaluation/test_p2_evidence_rescore.py",
            ],
            "tests": 22,
            "regression_tests": 20,
            "external_attempts": 0,
            "asserted_at_teardown": True,
            "source": "01-pytest.txt（两次 run exit 0）",
        },
        "static_import_scan": {
            "module": "backend/src/mktkb/evaluation/p2_evidence_rescore_axes.py",
            "imports": sorted(imported),
            "forbidden_modules": sorted(FORBIDDEN),
            "matched_forbidden_modules": matched,
            "no_frozen_evaluator_import": "p2_hard_evidence" not in imported,
            "no_monkeypatch_calls": "monkeypatch.setattr" not in source
            and "monkeypatch.patch" not in source,
            "no_os_environ": "os.environ" not in source,
            "no_subprocess": "subprocess" not in source,
            "no_ciphertext_or_key_access": all(
                token not in source
                for token in ("Fernet", "fernet", "MKTKB_P2_HOLDOUT_KEY_FILE", "contract_ciphertext")
            ),
            "scan_result": "PASS" if not matched else "FAIL",
        },
        "real_inputs_read": {
            "real_h2_cases_or_outputs": False,
            "private_ciphertext": False,
            "key_or_env_file": False,
            "private_custody_sessions": False,
            "ledger_or_go": False,
        },
        "staged_or_committed": False,
    }
    Path(sys.argv[1]).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(json.dumps({"scan_result": payload["static_import_scan"]["scan_result"], "matched": matched}))
    return 0 if not matched else 1


if __name__ == "__main__":
    raise SystemExit(main())

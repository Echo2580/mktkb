"""C1-P2 差分探针：同一批合成 envelope 下比较替代实现与 C 冻结原语。

只读 import `backend/tests/evaluation/test_p2_empty_scope_proof.py` 的合成语料与冻结原语；
不读真实 H2、不调用 provider/网络、不修改任何冻结件。输出可审计 JSON。
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[8]
TEST_MODULE = ROOT / "backend" / "tests" / "evaluation" / "test_p2_empty_scope_proof.py"
FROZEN_MODULE = ROOT / "backend" / "src" / "mktkb" / "evaluation" / "p2_hard_evidence.py"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_test_module() -> Any:
    for path in (ROOT / "backend" / "tests", ROOT / "backend" / "src"):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
    spec = importlib.util.spec_from_file_location("c1p2_synthetic_corpus", TEST_MODULE)
    if spec is None or spec.loader is None:
        raise RuntimeError("test_module_unloadable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def run() -> dict[str, Any]:
    module = _load_test_module()
    before = _sha256(FROZEN_MODULE)
    summary = {
        "equivalent_proven": 0,
        "equivalent_not_proven": 0,
        "extension_proven": 0,
        "stricter_not_proven": 0,
    }
    uncoded: list[str] = []
    rows: list[dict[str, Any]] = []
    shape_counts: Counter[str] = Counter()
    branch_counts: Counter[str] = Counter()
    retrieval_counts: Counter[str] = Counter()
    outcome_counts: Counter[str] = Counter()
    divergence_counts: Counter[str] = Counter()
    for case in module._corpus():
        ours = module.prove_empty_use_scope(case.evidence)
        frozen_proven, frozen_reason = module._empty_use_scope_proof(case.evidence)
        if ours.proven == frozen_proven:
            verdict = "equal"
            summary["equivalent_proven" if ours.proven else "equivalent_not_proven"] += 1
        elif ours.proven:
            verdict = "extension"
            summary["extension_proven"] += 1
        else:
            verdict = "stricter"
            summary["stricter_not_proven"] += 1
        if verdict != "equal" and not case.divergence:
            uncoded.append(case.name)
        if case.divergence:
            divergence_counts[case.divergence] += 1
        shape_counts[ours.shape] += 1
        branch_counts[ours.branch] += 1
        retrieval_counts[ours.retrieval] += 1
        outcome_counts[ours.outcome_class] += 1
        rows.append(
            {
                "case": case.name,
                "ours_proven": ours.proven,
                "ours_code": ours.code,
                "ours_shape": ours.shape,
                "ours_branch": ours.branch,
                "ours_retrieval": ours.retrieval,
                "ours_outcome": ours.outcome,
                "ours_outcome_class": ours.outcome_class,
                "ours_detail": ours.detail,
                "ours_usage_layers": list(ours.usage_layers),
                "frozen_proven": frozen_proven,
                "frozen_reason": frozen_reason,
                "verdict": verdict,
                "divergence_code": case.divergence,
                "divergence_reason": module.DIVERGENCE_REASONS.get(case.divergence or ""),
            }
        )
    after = _sha256(FROZEN_MODULE)
    return {
        "schema_version": "c1p2-empty-scope-differential/v0.1",
        "frozen_module": str(FROZEN_MODULE.relative_to(ROOT)).replace("\\", "/"),
        "frozen_module_sha_before": before,
        "frozen_module_sha_after": after,
        "frozen_module_unchanged": before == after,
        "corpus_size": len(rows),
        "summary": summary,
        "uncoded_divergences": uncoded,
        "divergence_codes": dict(sorted(divergence_counts.items())),
        "divergence_reasons": {
            code: module.DIVERGENCE_REASONS[code]
            for code in sorted(divergence_counts)
            if code in module.DIVERGENCE_REASONS
        },
        "branch_counts": dict(sorted(branch_counts.items())),
        "retrieval_counts": dict(sorted(retrieval_counts.items())),
        "outcome_class_counts": dict(sorted(outcome_counts.items())),
        "shape_counts": dict(sorted(shape_counts.items())),
        "rows": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    payload = run()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "corpus_size": payload["corpus_size"],
                "summary": payload["summary"],
                "uncoded_divergences": payload["uncoded_divergences"],
                "frozen_module_unchanged": payload["frozen_module_unchanged"],
            },
            ensure_ascii=False,
        )
    )
    return 0 if not payload["uncoded_divergences"] and payload["frozen_module_unchanged"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

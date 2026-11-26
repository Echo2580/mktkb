"""对账探针：逐题打印 重建 status vs case-plan quality_status，以及各检查 status。

只输出 case_id / 固定码 / 计数。
"""
from __future__ import annotations

import collections
import pathlib
import sys

_WORK = pathlib.Path(__file__).resolve().parent
if str(_WORK) not in sys.path:
    sys.path.insert(0, str(_WORK))

import r2_safe_project as base  # noqa: E402

KEY = pathlib.Path(r"D:\mktkb-p2-h2v3-20261115\runs3\ev.key")
BINDING = pathlib.Path(
    r"D:\mktkb-p2-h2v3-20261115\custody-plan-20261116-single-01\bindings"
    r"\run2-pre_v05_without_v07.binding.json"
)
EVIDENCE_ROOT = pathlib.Path(
    r"D:\mktkb-p2-h2v3-fullverify-20261116\r2\evidence\p2-h2v3-20261115-r2-pre_v05_without_v07"
)
CASE_PLAN = (
    base.REPO / "docs/reports/OBS-EVAL/P2/H2V3/fullverify-20261116/run/r2-final/case-plan.json"
)


def main() -> int:
    guard = base.NetGuard()
    guard.install()
    guard.positive_control()
    key = KEY.read_bytes().strip()
    binding = base._read_json(BINDING)
    case_plan = base._read_json(CASE_PLAN)
    run_entry = binding["runs"][0]
    entry = base._load_module(
        "p2_h2_v3_controlled_execute_probecheck",
        base.TOOLS / "p2_h2_v3_controlled_execute.py",
    )
    from mktkb.evaluation.p2_evidence_io import read_encrypted_evidence
    import mktkb.evaluation.p2_scoring as scoring
    import mktkb.evaluation.p2_score_run as score_run
    import mktkb.evaluation.p2_runner as runner

    inputs = {name: {"path": record["path"]} for name, record in binding["inputs"].items()}
    bundle = entry.load_v3_bundle(inputs)
    cases = tuple(bundle.contract.subset(str(run_entry.get("scenario_id"))).cases)
    document_codes = runner.holdout_document_codes(bundle.contract._ingest)
    static_bindings = {
        str(name): value
        for name, value in dict(run_entry.get("evidence_bindings") or {}).items()
        if str(name) != "index_revision"
    }
    plan = entry.v2._validate_case_plan_document(
        dict(case_plan), cases=cases, static_bindings=static_bindings
    )
    rows, _ = base._build_rows(
        cases,
        plan["cases"],
        EVIDENCE_ROOT,
        key,
        plan["bindings"],
        document_codes,
        read_encrypted_evidence,
        scoring._lookup_document_code,
        collections.defaultdict(int),
    )
    source_map = score_run.load_holdout_source_map()
    source_index = score_run.source_index_from_rows(rows) or None
    allowed = set(document_codes.values())
    plan_quality = {str(r.get("case_id")): str(r.get("quality_status")) for r in plan["cases"]}
    print("scoring module:", getattr(scoring, "SCORING_VERSION", "<unknown>"))
    for case in cases:
        case_id = str(case.case_id)
        mapped = score_run.remap_holdout_case(case, source_map)
        scored = scoring.score_public_case(
            mapped,
            rows[case_id],
            document_codes=document_codes,
            source_index=source_index,
            allowed_doc_codes=allowed,
            execution_mode="live",
            real_calls=0,
            include_source_version=True,
        )
        checks = {str(c.check_id): str(c.status) for c in (scored.result.checks if scored.result else ())}
        print(
            f"{case_id} plan={plan_quality.get(case_id)} scored={scored.score.status} "
            f"failed={sorted(k for k, v in checks.items() if v == 'fail')} "
            f"checks={dict(sorted(checks.items()))}"
        )
    print("real_calls_ok", case_plan.get("real_calls"), "mode", case_plan.get("execution_mode"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

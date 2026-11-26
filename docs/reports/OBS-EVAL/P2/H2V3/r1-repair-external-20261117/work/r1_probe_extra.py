"""R1 失败检查码取值探针（保管侧；只打印数字 key，不打印正文）。"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

_WORK = pathlib.Path(__file__).resolve().parent
if str(_WORK) not in sys.path:
    sys.path.insert(0, str(_WORK))

import r1_safe_project as base  # noqa: E402


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    for name in ("key", "binding", "evidence-root", "receipt", "seal-manifest", "case-plan"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--cases", required=True)
    args = parser.parse_args(argv)

    guard = base.NetGuard()
    guard.install()
    guard.positive_control()

    key = pathlib.Path(args.key).read_bytes().strip()
    binding = base._read_json(pathlib.Path(args.binding))
    run_entry = binding["runs"][0]
    receipt = base._read_json(pathlib.Path(args.receipt))
    seal_manifest = base._read_json(pathlib.Path(args.seal_manifest))
    case_plan_path = pathlib.Path(args.case_plan)
    case_plan = base._read_json(case_plan_path)
    plan_rows = case_plan["cases"]
    plan_quality = {str(r.get("case_id")): str(r.get("quality_status")) for r in plan_rows}
    turn_files = [str(t["evidence_file"]) for r in plan_rows for t in (r.get("turns") or ()) if str(t.get("status")) == "executed"]
    base._verify_custody(binding, case_plan_path, case_plan, receipt, seal_manifest, pathlib.Path(args.evidence_root), turn_files)

    entry = base._load_module("p2_h2_v3_controlled_execute_probe", base.TOOLS / "p2_h2_v3_controlled_execute.py")
    from mktkb.evaluation.p2_evidence_io import read_encrypted_evidence  # noqa: PLC0415
    import mktkb.evaluation.p2_scoring as scoring  # noqa: PLC0415
    import mktkb.evaluation.p2_score_run as score_run  # noqa: PLC0415
    import mktkb.evaluation.p2_runner as runner  # noqa: PLC0415

    inputs = {name: {"path": record["path"]} for name, record in binding["inputs"].items()}
    bundle = entry.load_v3_bundle(inputs)
    cases = tuple(bundle.contract.subset(str(run_entry.get("scenario_id"))).cases)
    static_bindings = {str(k): v for k, v in dict(run_entry.get("evidence_bindings") or {}).items() if str(k) != "index_revision"}
    plan = entry.v2._validate_case_plan_document(dict(case_plan), cases=cases, static_bindings=static_bindings)
    document_codes = runner.holdout_document_codes(bundle.contract._ingest)  # noqa: SLF001
    diag = {k: 0 for k in (
        "message_sources_mismatch", "sources_missing_unit", "sources_missing_document_name",
        "sources_unmapped_document", "sources_total", "sources_active", "product_kind_missing",
        "product_text_missing", "kind_answer_commit_mismatch", "text_answer_commit_mismatch",
        "classification_failures", "proof_eval_failures", "replica_disagreements", "unsafe_code_count",
    )}
    rows, _ = base._build_rows(cases, plan["cases"], pathlib.Path(args.evidence_root), key, plan["bindings"], document_codes, read_encrypted_evidence, scoring._lookup_document_code, diag)  # noqa: SLF001
    source_map = score_run.load_holdout_source_map()
    source_index = score_run.source_index_from_rows(rows) or None
    wanted = {x.strip() for x in args.cases.split(",") if x.strip()}

    for case in cases:
        case_id = str(case.case_id)
        if case_id not in wanted:
            continue
        mapped = score_run.remap_holdout_case(case, source_map)
        scored = scoring.score_public_case(
            mapped,
            rows[case_id],
            document_codes=document_codes,
            source_index=source_index,
            allowed_doc_codes=set(document_codes.values()),
            execution_mode="live",
            real_calls=0,
            include_source_version=True,
        )
        out = []
        for item in scored.score.checks:
            if not isinstance(item, dict):
                continue
            if str(item.get("status")) == "fail":
                ev = item.get("evidence") or {}
                safe_ev = {k: v for k, v in ev.items() if k in ("extra", "missing", "checked", "evidence_numbers", "expected", "leaked")}
                out.append({"check": item.get("check_id"), "evidence": safe_ev})
        print(case_id, json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

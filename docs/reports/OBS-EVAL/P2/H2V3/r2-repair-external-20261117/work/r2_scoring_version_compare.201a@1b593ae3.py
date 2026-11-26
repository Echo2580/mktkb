r"""评分版本对照（T-R2-201 §5.5）：同一批封存证据，用**原口径**与**当前批准口径**各算一次。

两口径的差别只有一个：2026-11-17 主人批准的 T-R1-102a 结构 token 放行
（引用 locator 的整数 + ``outcome.pagination`` 的页头计数）。因此"原口径"= 把这两个
加数器换成空集后调用**同一个** ``score_public_case``；判据代码未改、旧 case-plan 未改。

输出（只含固定码、布尔、计数、sha256）
------------------------------------
- 每题：current/original 两种 quality_status、各自 failed_check_ids、逐检查状态、计数；
- ``flip`` 与该题**最早差异 check id**；
- 模块身份：``module.__file__`` 的仓库相对路径 + sha256（判定"是否当前工作树"）。

运行（CWD 必须是仓库根：ingest plan 的 corpus 路径相对仓库根）
----
    .venv\Scripts\python.exe -X utf8 r2_scoring_version_compare.py ^
      --key <ev.key> --binding <run2 binding> --evidence-root <...> ^
      --receipt <...> --seal-manifest <...> --case-plan <...> --out-dir <...>
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import pathlib
import re
import sys
from typing import Any, Mapping, Sequence

import r2_safe_project as proj

#: 产品源码路径是本包公开信息（任务书即引用仓库路径）；但只允许**仓库相对**的产品路径出站，
#: 任何私有根（证据/密钥/binding 所在盘符）都不会匹配，因此这条放行不放宽私有面。
WORKTREE_PATH_RE = re.compile(r"^backend/src/mktkb/[a-z0-9_/]+\.py$")

COMPARE_ALLOWED = frozenset(
    {
        "ok",
        "error",
        "where",
        "round_label",
        "run_id",
        "run_index",
        "case_plan_sha256",
        "case_count",
        "turn_count",
        "envelope_count",
        "cases",
        "case_id",
        "turn_index",
        "current_status",
        "original_status",
        "plan_status",
        "flip",
        "flip_cases",
        "flip_count",
        "first_diff_check_id",
        "current_failed_check_ids",
        "original_failed_check_ids",
        "current_check_statuses",
        "original_check_statuses",
        "structural_key_count",
        "changed_check_ids",
        "value_expected",
        "value_matched",
        "value_missing",
        "value_extra",
        "source_expected",
        "source_matched",
        "source_missing",
        "source_forbidden_hit",
        "kind",
        "should_refuse",
        "refusal_expected_applicable",
        "refusal_expected_status",
        "refusal_effective",
        "modules",
        "module_name",
        "module_file_rel",
        "module_sha256",
        "module_is_worktree",
        "import_root",
        "import_root_is_worktree",
        "caliber",
        "caliber_note",
        "netguard",
        "blocked_attempts",
        "blocked_subprocess_attempts",
        "subprocess_guard_installed",
        "positive_control_attempts",
        "positive_control_blocked",
        "outbound_allowed",
        "custody_ok",
        "scoring_paths_agree",
    }
)


def _assert_safe(node: Any, depth: int = 0, parent_key: str | None = None) -> None:
    if depth > 9:
        raise SystemExit("compare_output_too_deep")
    if type(node) is bool:
        return
    if type(node) is int:
        if node < 0 or node > 10**9:
            raise SystemExit("compare_int_out_of_range")
        return
    if type(node) is str:
        if parent_key in {"module_file_rel", "import_root"}:
            if node != "outside_repo" and not WORKTREE_PATH_RE.fullmatch(node):
                raise SystemExit("compare_unsafe_string")
            return
        if not proj._safe_string(node):
            raise SystemExit("compare_unsafe_string")
        return
    if isinstance(node, list):
        for item in node:
            _assert_safe(item, depth + 1, parent_key)
        return
    if isinstance(node, dict):
        for key, value in node.items():
            if type(key) is not str:
                raise SystemExit("compare_unsafe_key")
            if key not in COMPARE_ALLOWED and key not in proj._CHECK_ID_SET:
                raise SystemExit("compare_unsafe_key")
            _assert_safe(value, depth + 1, key)
        return
    raise SystemExit("compare_unsafe_type")


def _dump(payload: Mapping[str, Any], path: pathlib.Path) -> None:
    _assert_safe(dict(payload))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=True)
    for name in ("key", "binding", "evidence-root", "receipt", "seal-manifest"):
        parser.add_argument(f"--{name}", required=True)
    parser.add_argument(
        "--case-plan",
        default=str(proj.REPO / "docs/reports/OBS-EVAL/P2/H2V3/fullverify-20261116/run/r2-final/case-plan.json"),
    )
    parser.add_argument(
        "--out-dir",
        default=str(
            proj.REPO
            / "docs/reports/OBS-EVAL/P2/H2V3/r2-repair-external-20261117/evidence/01-safe-projection"
        ),
    )
    return parser.parse_args(list(argv))


def _module_identity(module: Any) -> dict[str, Any]:
    """记录模块身份：仓库相对路径 + sha256 + 是否落在当前工作树（私有根不外泄）。"""
    raw = str(getattr(module, "__file__", "") or "")
    path = pathlib.Path(raw)
    rel = ""
    try:
        rel = path.resolve().relative_to(proj.REPO).as_posix()
    except (ValueError, OSError):
        rel = ""
    return {
        "module_name": str(getattr(module, "__name__", "") or "").replace(".", "_"),
        "module_file_rel": rel if rel else "outside_repo",
        "module_sha256": proj._sha256_file(path) if path.is_file() else "0" * 64,
        "module_is_worktree": bool(rel.startswith("backend/src/mktkb/")),
    }


def main(argv: Sequence[str]) -> int:
    guard = proj.NetGuard()
    guard.install()
    guard.positive_control()
    args = _parse_args(argv)
    proj.gate_cwd_is_repo_root()

    case_plan = proj._read_json(pathlib.Path(args.case_plan))
    receipt = proj._read_json(pathlib.Path(args.receipt))
    seal_manifest = proj._read_json(pathlib.Path(args.seal_manifest))
    binding = proj._read_json(pathlib.Path(args.binding))
    key = pathlib.Path(args.key).read_bytes().strip()
    evidence_root = pathlib.Path(args.evidence_root)

    proj._STAGE[0] = "load_bundle"
    entry = proj._load_module(
        "p2_h2_v3_controlled_execute_compare", proj.TOOLS / "p2_h2_v3_controlled_execute.py"
    )
    import mktkb  # noqa: PLC0415
    import mktkb.evaluation.p2_hard_evidence as hard  # noqa: PLC0415
    import mktkb.evaluation.p2_scoring as scoring  # noqa: PLC0415
    import mktkb.evaluation.p2_score_run as score_run  # noqa: PLC0415
    import mktkb.evaluation.p2_evidence_io as evidence_io  # noqa: PLC0415
    import mktkb.evaluation.scorers as scorers  # noqa: PLC0415
    from mktkb.evaluation.scorers import CHECK_IDS  # noqa: PLC0415

    proj._CHECK_ID_SET = frozenset(str(item) for item in CHECK_IDS)
    proj._STAGE[0] = "verify_custody"
    run_entry = binding["runs"][0]
    plan_rows = case_plan.get("cases")
    turn_files = [
        str(turn_row["evidence_file"])
        for row in plan_rows
        for turn_row in (row.get("turns") or ())
        if str(turn_row.get("status")) == "executed"
    ]
    custody_ok = proj._verify_custody(
        binding, pathlib.Path(args.case_plan), case_plan, receipt, seal_manifest, evidence_root, turn_files
    )
    plan_quality = {str(row.get("case_id")): str(row.get("quality_status")) for row in plan_rows}

    proj._STAGE[0] = "load_cases"
    inputs = {name: {"path": record["path"]} for name, record in binding["inputs"].items()}
    bundle = entry.load_v3_bundle(inputs)
    scenario = str(run_entry.get("scenario_id"))
    cases = tuple(bundle.contract.subset(scenario).cases)
    static_bindings = {
        str(name): value
        for name, value in dict(run_entry.get("evidence_bindings") or {}).items()
        if str(name) != "index_revision"
    }
    plan = entry.v2._validate_case_plan_document(
        dict(case_plan), cases=cases, static_bindings=static_bindings
    )
    from mktkb.evaluation import p2_runner as runner  # noqa: PLC0415

    document_codes = runner.holdout_document_codes(bundle.contract._ingest)  # noqa: SLF001

    proj._STAGE[0] = "build_rows"
    diag = {
        "message_sources_mismatch": 0,
        "sources_missing_unit": 0,
        "sources_missing_document_name": 0,
        "sources_unmapped_document": 0,
        "sources_total": 0,
        "sources_active": 0,
        "product_kind_missing": 0,
        "product_text_missing": 0,
        "kind_answer_commit_mismatch": 0,
        "text_answer_commit_mismatch": 0,
        "classification_failures": 0,
        "proof_eval_failures": 0,
        "replica_disagreements": 0,
        "unsafe_code_count": 0,
    }
    origin: dict[str, dict[str, Any]] = {}
    rows, envelopes_by_case = proj._build_rows(
        cases,
        plan["cases"],
        evidence_root,
        key,
        plan["bindings"],
        document_codes,
        evidence_io.read_encrypted_evidence,
        scoring._lookup_document_code,  # noqa: SLF001
        diag,
        origin,
    )
    proj.gate_origin_round(origin)

    proj._STAGE[0] = "score_both_calibers"
    source_map = score_run.load_holdout_source_map()
    source_index = score_run.source_index_from_rows(rows) or None
    allowed = set(document_codes.values())
    out_cases: list[dict[str, Any]] = []
    flip_cases: list[str] = []
    for case in cases:
        case_id = str(case.case_id)
        mapped = score_run.remap_holdout_case(case, source_map)
        current = scoring.score_public_case(
            mapped,
            rows[case_id],
            document_codes=document_codes,
            source_index=source_index,
            allowed_doc_codes=allowed,
            execution_mode="live",
            real_calls=0,
            include_source_version=True,
        )
        original = proj.score_original_caliber(
            scoring,
            mapped,
            rows[case_id],
            document_codes=document_codes,
            source_index=source_index,
            allowed=allowed,
        )
        current_status = proj.check_status_map(current, CHECK_IDS)
        original_status = proj.check_status_map(original, CHECK_IDS)
        current_case_status = str(current.score.status)
        original_case_status = str(original.score.status)
        if current_case_status not in proj.CASE_STATUSES:
            current_case_status = "error"
        if original_case_status not in proj.CASE_STATUSES:
            original_case_status = "error"
        changed = [check_id for check_id in CHECK_IDS if current_status[check_id] != original_status[check_id]]
        flip = current_case_status != original_case_status or bool(changed)
        if flip:
            flip_cases.append(case_id)
        earliest = changed[0] if changed else "none"
        evidence_by_id = {
            str(item.get("check_id")): dict(item.get("evidence") or {})
            for item in current.score.checks
            if isinstance(item, Mapping)
        }
        value_hit_ev = evidence_by_id.get("value_hit", {})
        value_expected = int(value_hit_ev.get("expected") or 0)
        missing_values = value_hit_ev.get("missing")
        value_missing = len(missing_values) if isinstance(missing_values, list) else 0
        no_fab_ev = evidence_by_id.get("value_no_fabricated", {})
        extra_values = no_fab_ev.get("extra")
        source_hit_ev = evidence_by_id.get("source_hit", {})
        source_expected = int(source_hit_ev.get("expected") or 0)
        missing_sources = source_hit_ev.get("missing_index")
        source_missing = len(missing_sources) if isinstance(missing_sources, list) else 0
        forbidden_ev = evidence_by_id.get("source_forbidden", {})
        hits = forbidden_ev.get("violations_index")
        turns = rows[case_id]["turns"]
        final_kind = str(((turns[-1].get("product") or {}).get("kind")) or "") if turns else ""
        out_cases.append(
            {
                "case_id": case_id,
                "turn_index": int(turns[-1]["turn"]) if turns else 0,
                "current_status": current_case_status,
                "original_status": original_case_status,
                "plan_status": str(plan_quality.get(case_id)),
                "flip": bool(flip),
                "first_diff_check_id": earliest,
                "changed_check_ids": changed,
                "current_failed_check_ids": [
                    check_id for check_id in CHECK_IDS if current_status[check_id] == "fail"
                ],
                "original_failed_check_ids": [
                    check_id for check_id in CHECK_IDS if original_status[check_id] == "fail"
                ],
                "current_check_statuses": current_status,
                "original_check_statuses": original_status,
                "structural_key_count": proj.structural_key_count(scoring, current),
                "value_expected": value_expected,
                "value_matched": max(value_expected - value_missing, 0),
                "value_missing": value_missing,
                "value_extra": len(extra_values) if isinstance(extra_values, list) else 0,
                "source_expected": source_expected,
                "source_matched": int(source_hit_ev.get("matched") or 0)
                if "matched" in source_hit_ev
                else max(source_expected - source_missing, 0),
                "source_missing": source_missing,
                "source_forbidden_hit": len(hits) if isinstance(hits, list) else 0,
                "kind": final_kind if proj.CODE_RE.fullmatch(final_kind) else "unknown_kind",
                "should_refuse": bool(getattr(case, "should_refuse", False)),
                "refusal_expected_applicable": bool(current_status.get("refusal_expected") in {"pass", "fail"}),
                "refusal_expected_status": str(current_status.get("refusal_expected", "unknown")),
                "refusal_effective": bool(final_kind in proj.REFUSAL_KIND_CODES),
            }
        )

    import_root = str(getattr(mktkb, "__file__", "") or "")
    try:
        import_rel = pathlib.Path(import_root).resolve().relative_to(proj.REPO).as_posix()
    except (ValueError, OSError):
        import_rel = "outside_repo"

    payload = {
        "ok": True,
        "round_label": proj.ROUND_LABEL,
        "run_id": str(case_plan.get("run_id")),
        "run_index": int(proj.EXPECTED_RUN_INDEX),
        "case_plan_sha256": proj._sha256_file(pathlib.Path(args.case_plan)),
        "case_count": len(cases),
        "turn_count": len(turn_files),
        "envelope_count": sum(len(item) for item in envelopes_by_case.values()),
        "custody_ok": bool(custody_ok),
        "caliber": "structural_numbers_enabled_is_current",
        "caliber_note": "original_caliber_disables_102a_structural_tokens_only",
        "import_root": import_rel,
        "import_root_is_worktree": bool(import_rel.startswith("backend/src/mktkb/")),
        "flip_count": len(flip_cases),
        "flip_cases": flip_cases,
        "cases": out_cases,
        "modules": [
            _module_identity(scoring),
            _module_identity(scorers),
            _module_identity(hard),
            _module_identity(score_run),
            _module_identity(evidence_io),
        ],
        "netguard": guard.as_dict(),
    }
    _dump(payload, pathlib.Path(args.out_dir) / "r2-scoring-version-compare.json")
    print(
        json.dumps(
            {
                "ok": True,
                "flip_count": len(flip_cases),
                "flip_cases": flip_cases,
                "import_root_is_worktree": payload["import_root_is_worktree"],
                "netguard": payload["netguard"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except SystemExit:
        raise
    except proj.ToolError as exc:
        code = str(exc.code) if proj.CODE_RE.fullmatch(str(exc.code)) else "internal_error"
        print(json.dumps({"ok": False, "error": code, "where": "main"}, ensure_ascii=False))
        raise SystemExit(2) from None
    except Exception:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": "internal_error", "where": "main"}, ensure_ascii=False))
        raise SystemExit(3) from None

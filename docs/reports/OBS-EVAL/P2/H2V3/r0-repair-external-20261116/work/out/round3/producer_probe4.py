"""只读探针 4：缺失期望值到底落在「结构化字段」还是「正文」。

对每个期望值，判断在被引用单元里：raw_fields 命中 / 仅正文 text 命中 / 能映射到字段角色。
只输出计数与固定 role 码。
用法：python producer_probe4.py <binding> <evidence-root> <case-plan> <key>
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import sys
from collections import Counter
from typing import Any, Mapping, Sequence

WORK = pathlib.Path(__file__).resolve().parent
SAFE = WORK.parent.parent / "r0_safe_project.py"
PROBE_CASES = ("H2V3-C12", "H2V3-C21", "H2V3-C27")


def _load(name: str, path: pathlib.Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("module_not_loadable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


P = _load("r0_safe_probe4", SAFE)


def _payloads(events: Sequence[Mapping[str, Any]], kind: str) -> list[Mapping[str, Any]]:
    return [event.get("payload") or {} for event in events if str(event.get("kind")) == kind]


def main(argv: list[str]) -> int:
    binding_path, evidence_root, case_plan_path, key_path = (pathlib.Path(p) for p in argv[:4])
    guard = P.NetGuard()
    guard.install()
    guard.positive_control()

    binding = json.loads(binding_path.read_text(encoding="utf-8"))
    run_entry = binding["runs"][0]
    case_plan = json.loads(case_plan_path.read_text(encoding="utf-8"))
    key = key_path.read_bytes().strip()

    entry = P._load_module("p2_h2_v3_probe4_entry", P.TOOLS / "p2_h2_v3_controlled_execute.py")
    from mktkb.evaluation.p2_evidence_io import read_encrypted_evidence
    import mktkb.evaluation.p2_runner as runner
    import mktkb.evaluation.p2_scoring as scoring
    from mktkb.evaluation.scorers import check_value
    from mktkb.rag.chunking import role_values

    inputs = {name: {"path": record["path"]} for name, record in binding["inputs"].items()}
    bundle = entry.load_v3_bundle(inputs)
    scenario = str(run_entry.get("scenario_id"))
    cases = tuple(bundle.contract.subset(scenario).cases)
    static_bindings = {
        str(name): value
        for name, value in dict(run_entry.get("evidence_bindings") or {}).items()
        if str(name) != "index_revision"
    }
    plan = entry.v2._validate_case_plan_document(case_plan, cases=cases, static_bindings=static_bindings)
    document_codes = runner.holdout_document_codes(bundle.contract._ingest)  # noqa: SLF001
    diag: dict[str, int] = Counter()
    _rows, envelopes_by_case = P._build_rows(
        cases, plan["cases"], evidence_root, key, plan["bindings"], document_codes,
        read_encrypted_evidence, scoring._lookup_document_code, diag,  # noqa: SLF001
    )

    print("netguard_ok=%s" % guard.as_dict()["positive_control_blocked"])
    for case in cases:
        case_id = str(case.case_id)
        if case_id not in PROBE_CASES:
            continue
        expected = tuple(getattr(case, "expected_values", ()) or ())
        flags = {
            key: [False] * len(expected)
            for key in ("raw", "text", "role", "commit", "db_raw", "db_text")
        }
        cited_roles: set[str] = set()
        for envelope in envelopes_by_case.get(case_id) or []:
            events = [
                event for event in ((envelope.get("capture") or {}).get("events") or [])
                if isinstance(event, Mapping)
            ]
            cited: set[str] = set()
            for payload in _payloads(events, "commit_observed"):
                cited |= {str(item) for item in (payload.get("source_ids") or ())}
            for payload in _payloads(events, "direct_rag_answer"):
                cited |= {str(item) for item in (payload.get("cited_unit_ids") or ())}
            commit_text = ""
            for payload in _payloads(events, "commit_observed"):
                commit_text = str(payload.get("text") or "")
            for unit in ((envelope.get("db_projection") or {}).get("units") or []):
                if not isinstance(unit, Mapping):
                    continue
                fields = unit.get("raw_fields") if isinstance(unit.get("raw_fields"), Mapping) else {}
                text = str(unit.get("text") or "")
                mapped = role_values(fields)
                is_cited = str(unit.get("unit_id")) in cited
                for index, value in enumerate(expected):
                    if any(check_value(str(item), value, cross_explicit_space=True) for item in fields.values()):
                        flags["db_raw"][index] = True
                        if is_cited:
                            flags["raw"][index] = True
                    if check_value(text, value, cross_explicit_space=True):
                        flags["db_text"][index] = True
                        if is_cited:
                            flags["text"][index] = True
                    if is_cited and any(
                        check_value(str(item), value, cross_explicit_space=True)
                        for values in mapped.values()
                        for item in values
                    ):
                        flags["role"][index] = True
                if is_cited:
                    cited_roles |= {str(role) for role, values in mapped.items() if values}
            for index, value in enumerate(expected):
                if check_value(commit_text, value, cross_explicit_space=True):
                    flags["commit"][index] = True
        print(
            "%s values=%d db_raw=%d db_text=%d cited_raw=%d cited_text=%d cited_role=%d commit=%d cited_roles=%s"
            % (
                case_id,
                len(expected),
                sum(flags["db_raw"]),
                sum(flags["db_text"]),
                sum(flags["raw"]),
                sum(flags["text"]),
                sum(flags["role"]),
                sum(flags["commit"]),
                sorted(cited_roles) or "none",
            )
        )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except Exception:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": "probe4_failed"}, sort_keys=True))
        raise SystemExit(2)

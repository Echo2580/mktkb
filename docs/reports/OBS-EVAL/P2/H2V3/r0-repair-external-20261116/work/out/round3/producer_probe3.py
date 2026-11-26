"""只读探针 3：期望值的「按值」到达阶梯（去重口径）。

对每个期望值，判断它在哪一层首次出现：
DB 单元原文 → 被引用单元 → 被引用单元的 raw_fields 能映射到字段角色 → RAG facts → 最终提交文本。
只输出：case_id、整数、固定 role 码。绝不输出值、题面、答案、来源正文。
用法：python producer_probe3.py <binding> <evidence-root> <case-plan> <key>
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
PROBE_CASES = ("H2V3-C01", "H2V3-C02", "H2V3-C12", "H2V3-C21", "H2V3-C27")


def _load(name: str, path: pathlib.Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("module_not_loadable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


P = _load("r0_safe_probe3", SAFE)


def _payloads(events: Sequence[Mapping[str, Any]], kind: str) -> list[Mapping[str, Any]]:
    return [event.get("payload") or {} for event in events if str(event.get("kind")) == kind]


def _unit_text(unit: Mapping[str, Any]) -> str:
    return "\n".join(
        [
            str(unit.get("text") or ""),
            json.dumps(unit.get("raw_fields") or {}, ensure_ascii=False),
            json.dumps(unit.get("date_fields") or {}, ensure_ascii=False),
        ]
    )


def main(argv: list[str]) -> int:
    binding_path, evidence_root, case_plan_path, key_path = (pathlib.Path(p) for p in argv[:4])
    guard = P.NetGuard()
    guard.install()
    guard.positive_control()

    binding = json.loads(binding_path.read_text(encoding="utf-8"))
    run_entry = binding["runs"][0]
    case_plan = json.loads(case_plan_path.read_text(encoding="utf-8"))
    key = key_path.read_bytes().strip()

    entry = P._load_module("p2_h2_v3_probe3_entry", P.TOOLS / "p2_h2_v3_controlled_execute.py")
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
        envelopes = envelopes_by_case.get(case_id) or []
        reach = {key: [False] * len(expected) for key in ("db", "cited", "role", "fact", "commit")}
        roles: set[str] = set()
        requested: set[str] = set()
        for envelope in envelopes:
            events = [
                event for event in ((envelope.get("capture") or {}).get("events") or [])
                if isinstance(event, Mapping)
            ]
            for payload in _payloads(events, "plan_observed"):
                requested |= {str(item) for item in (payload.get("filters") or {})}
                requested |= {"role:%s" % item for item in (payload.get("field_roles") or ())}
            cited: set[str] = set()
            facts: list[str] = []
            for payload in _payloads(events, "commit_observed"):
                cited |= {str(item) for item in (payload.get("source_ids") or ())}
            for payload in _payloads(events, "direct_rag_answer"):
                cited |= {str(item) for item in (payload.get("cited_unit_ids") or ())}
                roles |= {"fact_role:%s" % f.get("field_role") for f in (payload.get("facts") or ())
                          if isinstance(f, Mapping)}
                facts += [str(f.get("value") or "") for f in (payload.get("facts") or ())
                          if isinstance(f, Mapping)]
            commit_text = ""
            for payload in _payloads(events, "commit_observed"):
                commit_text = str(payload.get("text") or "")
            units = [
                unit for unit in ((envelope.get("db_projection") or {}).get("units") or [])
                if isinstance(unit, Mapping)
            ]
            for index, value in enumerate(expected):
                cross = True
                if any(check_value(_unit_text(unit), value, cross_explicit_space=cross) for unit in units):
                    reach["db"][index] = True
                if any(
                    check_value(_unit_text(unit), value, cross_explicit_space=cross)
                    for unit in units
                    if str(unit.get("unit_id")) in cited
                ):
                    reach["cited"][index] = True
                if any(
                    check_value(str(item), value, cross_explicit_space=cross)
                    for unit in units
                    if str(unit.get("unit_id")) in cited
                    for mapped in role_values(
                        unit.get("raw_fields") if isinstance(unit.get("raw_fields"), Mapping) else {}
                    ).values()
                    for item in mapped
                ):
                    reach["role"][index] = True
                if any(check_value(item, value, cross_explicit_space=cross) for item in facts):
                    reach["fact"][index] = True
                if check_value(commit_text, value, cross_explicit_space=cross):
                    reach["commit"][index] = True
        print(
            "%s values=%d db=%d cited=%d role=%d facts=%d commit=%d plan_refs=%s fact_roles=%s"
            % (
                case_id,
                len(expected),
                sum(reach["db"]),
                sum(reach["cited"]),
                sum(reach["role"]),
                sum(reach["fact"]),
                sum(reach["commit"]),
                sorted(requested) or "none",
                sorted(r for r in roles if r.startswith("fact_role:")) or "none",
            )
        )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except Exception:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": "probe3_failed"}, sort_keys=True))
        raise SystemExit(2)

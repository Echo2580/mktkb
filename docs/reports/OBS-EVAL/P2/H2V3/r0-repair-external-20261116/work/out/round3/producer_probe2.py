"""只读探针 2：字段角色映射层 + 空集证明的精确子因。

只输出：case_id、固定 role 码、固定 reason 码、整数、布尔。
用法：python producer_probe2.py <binding> <evidence-root> <case-plan> <key>
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
PROBE_CASES = ("H2V3-C02", "H2V3-C12", "H2V3-C21", "H2V3-C27")
REFUSAL_CASES = ("H2V3-C16", "H2V3-C17", "H2V3-C26")


def _load(name: str, path: pathlib.Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("module_not_loadable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


P = _load("r0_safe_probe2", SAFE)


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

    entry = P._load_module("p2_h2_v3_probe2_entry", P.TOOLS / "p2_h2_v3_controlled_execute.py")
    from mktkb.evaluation.p2_evidence_io import read_encrypted_evidence
    from mktkb.evaluation import p2_hard_evidence as hard
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

    expected_by_case = {str(c.case_id): tuple(getattr(c, "expected_values", ()) or ()) for c in cases}
    print("netguard_ok=%s" % guard.as_dict()["positive_control_blocked"])

    for case_id in PROBE_CASES:
        expected = expected_by_case.get(case_id, ())
        envelopes = envelopes_by_case.get(case_id) or []
        raw_hit = text_hit = role_hit = 0
        roles: set[str] = set()
        for envelope in envelopes:
            events = [
                event for event in ((envelope.get("capture") or {}).get("events") or [])
                if isinstance(event, Mapping)
            ]
            cited: set[str] = set()
            for payload in _payloads(events, "commit_observed"):
                cited |= {str(item) for item in (payload.get("source_ids") or ())}
            for payload in _payloads(events, "direct_rag_answer"):
                cited |= {str(item) for item in (payload.get("cited_unit_ids") or ())}
            for unit in ((envelope.get("db_projection") or {}).get("units") or []):
                if not isinstance(unit, Mapping):
                    continue
                if cited and str(unit.get("unit_id")) not in cited:
                    continue
                fields = unit.get("raw_fields") if isinstance(unit.get("raw_fields"), Mapping) else {}
                text = str(unit.get("text") or "")
                mapped = role_values(fields)
                roles |= {str(role) for role, values in mapped.items() if values}
                for value in expected:
                    if any(check_value(str(item), value, cross_explicit_space=True)
                           for values in mapped.values() for item in values):
                        role_hit += 1
                    if any(check_value(str(item), value, cross_explicit_space=True)
                           for item in fields.values()):
                        raw_hit += 1
                    elif check_value(text, value, cross_explicit_space=True):
                        text_hit += 1
        print(
            "%s expected=%d exp_role_mapped=%d exp_in_raw_fields=%d exp_text_only=%d cited_roles=%s"
            % (case_id, len(expected), role_hit, raw_hit, text_hit, sorted(roles) or "none")
        )

    for case_id in REFUSAL_CASES:
        envelopes = envelopes_by_case.get(case_id) or []
        proof = []
        for envelope in envelopes:
            try:
                proven_v4, reason_v4 = hard._empty_use_scope_proof(  # noqa: SLF001
                    envelope, compat=hard.REFUSAL_COMPAT_V0_4
                )
            except Exception:  # noqa: BLE001
                proven_v4, reason_v4 = None, "proof_exception"
            try:
                proven_v1, reason_v1 = hard._empty_use_scope_proof(  # noqa: SLF001
                    envelope, compat=hard.REFUSAL_COMPAT_V0_1
                )
            except Exception:  # noqa: BLE001
                proven_v1, reason_v1 = None, "proof_exception"
            proof.append((bool(proven_v4), str(reason_v4), bool(proven_v1), str(reason_v1)))
        print("%s empty_scope_v4=%s empty_scope_v1=%s" % (case_id, proof, proof))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except Exception:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": "probe2_failed"}, sort_keys=True))
        raise SystemExit(2)

"""第四轮 v0.5 闸门探针：逐 envelope 直调冻结原语，只出布尔/整数/固定码。

目的：若 C16/C17 在 v0.5 下翻转，说明卡点正是 v0.5 唯一新增放行项
（``projection_not_mirror`` 之外的 b 条件）。本探针不改任何判据，只**观察**：
- ``_empty_use_scope_proof(evidence, compat=v0.1/v0.3/v0.4/v0.5)`` 的 (bool, 固定码)；
- v0.4 检索层放行 ``_retrieval_observed_unused_relaxable``；
- v0.5 镜像判据 ``_projection_units_mirror_retrieval``；
- 投影 units / 检索 union / message_sources / unresolved / used_unit_layers 的**长度/布尔**。

用法：
    python r4_probe_v05_gate.py --binding <file> --evidence-root <dir> \
        --case-plan <file> --key <file> --out <json>
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
from collections import Counter
from typing import Any, Mapping, Sequence

WORK = pathlib.Path(__file__).resolve().parent
SAFE = WORK / "r0_safe_project.py"
CASE_RE = re.compile(r"^H2V3-C[0-9]{2}$")
CODE_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
COMPAT_RE = re.compile(r"^p2-refusal-compat/v0\.[1-9]$")
FILE_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,79}$")
ALLOWED_KEYS = frozenset(
    {
        "ok",
        "role",
        "netguard",
        "cases",
        "case_id",
        "envelopes",
        "turn_index",
        "proof",
        "compat",
        "proven",
        "reason",
        "relax_retrieval_v04",
        "relax_retrieval_v05",
        "projection_mirror_retrieval",
        "projection_units_len",
        "retrieval_union_available",
        "retrieval_unit_ids_len",
        "message_sources_len",
        "unresolved_unit_ids_len",
        "used_unit_layers_nonempty",
        "completeness_ok",
        "capture_errors_len",
        "query_state_candidates_len",
        "flip_gate",
        "blocked_attempts",
        "positive_control_attempts",
        "positive_control_blocked",
        "outbound_allowed",
        "envelope_count",
        "case_count",
        "v05_flip_cases",
        "proof_true_cases",
        "fixed_reasons",
    }
)


def _fail(code: str) -> None:
    print(json.dumps({"ok": False, "error": code}, sort_keys=True))
    raise SystemExit(2)


def _safe(node: Any, depth: int = 0) -> None:
    if depth > 10:
        _fail("output_too_deep")
    if type(node) in (bool, int):
        if type(node) is int and (node < 0 or node > 10**9):
            _fail("output_int_out_of_range")
        return
    if type(node) is str:
        if (
            CASE_RE.fullmatch(node)
            or CODE_RE.fullmatch(node)
            or COMPAT_RE.fullmatch(node)
            or SHA_RE.fullmatch(node)
            or FILE_RE.fullmatch(node)
        ):
            return
        _fail("unsafe_output_string")
    if isinstance(node, list):
        if len(node) > 4096:
            _fail("output_list_too_long")
        for item in node:
            _safe(item, depth + 1)
        return
    if isinstance(node, dict):
        if len(node) > 512:
            _fail("output_object_too_large")
        for key, value in node.items():
            if type(key) is not str:
                _fail("unsafe_output_key")
            if key not in ALLOWED_KEYS and not (
                CASE_RE.fullmatch(key)
                or COMPAT_RE.fullmatch(key)
                or CODE_RE.fullmatch(key)
                or key.isdigit()
            ):
                _fail("unsafe_output_key")
            _safe(value, depth + 1)
        return
    _fail("unsafe_output_type")


def _load(name: str, path: pathlib.Path) -> Any:
    import importlib.util

    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        _fail("module_not_loadable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _int(value: Any) -> int:
    return len(value) if isinstance(value, (list, tuple, dict)) else 0


def main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--binding", required=True)
    parser.add_argument("--evidence-root", required=True)
    parser.add_argument("--case-plan", required=True)
    parser.add_argument("--key", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(list(argv))

    P = _load("r0_safe_probe4", SAFE)
    guard = P.NetGuard()
    guard.install()
    guard.positive_control()

    from mktkb.evaluation.p2_evidence_io import read_encrypted_evidence  # noqa: PLC0415
    from mktkb.evaluation import p2_hard_evidence as hard  # noqa: PLC0415
    import mktkb.evaluation.p2_runner as runner  # noqa: PLC0415
    import mktkb.evaluation.p2_scoring as scoring  # noqa: PLC0415

    v01 = hard.REFUSAL_COMPAT_V0_1
    v03 = hard.REFUSAL_COMPAT_V0_3
    v04 = hard.REFUSAL_COMPAT_V0_4
    v05 = hard.REFUSAL_COMPAT_V0_5
    compat_order = (v01, v03, v04, v05)

    binding_path = pathlib.Path(args.binding)
    evidence_root = pathlib.Path(args.evidence_root)
    case_plan_path = pathlib.Path(args.case_plan)
    key_path = pathlib.Path(args.key)
    binding = json.loads(binding_path.read_text(encoding="utf-8"))
    run_entry = binding["runs"][0]
    case_plan = json.loads(case_plan_path.read_text(encoding="utf-8"))
    key = key_path.read_bytes().strip()

    entry = P._load_module("p2_h2_v3_probe4_entry", P.TOOLS / "p2_h2_v3_controlled_execute.py")
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
        cases,
        plan["cases"],
        evidence_root,
        key,
        plan["bindings"],
        document_codes,
        read_encrypted_evidence,
        scoring._lookup_document_code,  # noqa: SLF001
        diag,
    )

    out_cases: list[dict[str, Any]] = []
    proof_true_cases: set[str] = set()
    flipped: set[str] = set()
    for case in cases:
        case_id = str(case.case_id)
        envelopes = envelopes_by_case.get(case_id) or []
        rows: list[dict[str, Any]] = []
        for index, envelope in enumerate(envelopes):
            proof: dict[str, dict[str, Any]] = {}
            for compat in compat_order:
                try:
                    proven, reason = hard._empty_use_scope_proof(  # noqa: SLF001
                        envelope, compat=compat
                    )
                except Exception:  # noqa: BLE001
                    proven, reason = None, "proof_exception"
                proof[compat] = {
                    "proven": None if proven is None else bool(proven),
                    "reason": str(reason),
                }
            if bool(proof[v05]["proven"]):
                proof_true_cases.add(case_id)
            if (not bool(proof[v04]["proven"])) and bool(proof[v05]["proven"]):
                flipped.add(case_id)
            projection = hard._projection(envelope)  # noqa: SLF001
            events = hard._events(envelope)  # noqa: SLF001
            union = hard._retrieval_unit_id_union(events)  # noqa: SLF001
            completeness = envelope.get("completeness")
            state_candidates = 0
            for payload in hard._payloads(events, "query_state_observed"):  # noqa: SLF001
                state = payload.get("state_json")
                if isinstance(state, Mapping) and isinstance(state.get("candidates"), list):
                    state_candidates += len(state["candidates"])
            rows.append(
                {
                    "turn_index": index,
                    "proof": proof,
                    "relax_retrieval_v04": bool(
                        hard._retrieval_observed_unused_relaxable(  # noqa: SLF001
                            envelope, compat=v04
                        )
                    ),
                    "relax_retrieval_v05": bool(
                        hard._retrieval_observed_unused_relaxable(  # noqa: SLF001
                            envelope, compat=v05
                        )
                    ),
                    "projection_mirror_retrieval": bool(
                        hard._projection_units_mirror_retrieval(envelope)  # noqa: SLF001
                    ),
                    "projection_units_len": _int(projection.get("units")),
                    "retrieval_union_available": union is not None,
                    "retrieval_unit_ids_len": 0 if union is None else len(union),
                    "message_sources_len": _int(projection.get("message_sources")),
                    "unresolved_unit_ids_len": _int(projection.get("unresolved_unit_ids")),
                    "used_unit_layers_nonempty": bool(hard._used_unit_layers(events)),  # noqa: SLF001
                    "completeness_ok": bool(
                        isinstance(completeness, Mapping)
                        and str(completeness.get("status")) == "complete"
                    ),
                    "capture_errors_len": _int((envelope.get("capture") or {}).get("errors")),
                    "query_state_candidates_len": state_candidates,
                }
            )
        out_cases.append({"case_id": case_id, "envelopes": rows})

    fixed_reasons = Counter()
    for row in out_cases:
        for env_row in row["envelopes"]:
            for compat in compat_order:
                fixed_reasons[str(env_row["proof"][compat]["reason"])] += 1

    result = {
        "ok": True,
        "role": "v05_gate_probe",
        "netguard": guard.as_dict(),
        "case_count": len(out_cases),
        "envelope_count": sum(len(row["envelopes"]) for row in out_cases),
        "cases": out_cases,
        "v05_flip_cases": sorted(flipped),
        "proof_true_cases": sorted(proof_true_cases),
        "fixed_reasons": {reason: int(count) for reason, count in sorted(fixed_reasons.items())},
    }
    _safe(result)
    path = pathlib.Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "ok": True,
                "wrote": path.name,
                "v05_flip_cases": sorted(flipped),
                "proof_true_cases": sorted(proof_true_cases),
                "fixed_reasons": result["fixed_reasons"],
                "netguard": result["netguard"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001 - 只出固定码
        print(json.dumps({"ok": False, "error": "probe_failed"}, sort_keys=True))
        raise SystemExit(3) from None

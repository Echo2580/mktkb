"""IR-01 runtime oracle: hostile non-scalar values at every field path.

Two targets:
  * adapter v2 (IR-01 fix; 11 originally reported sites + any missed sites)
  * p2_stale_version_state (new v1 classifier)

For each leaf of a valid synthetic payload, replace it with list/dict/set/None/
bool/int/nested and call the public entry. A ``TypeError`` (or any exception
other than the module's fixed-code AdapterError path) escaping the entry is a
fail-open site. Negative controls monkeypatch `_enum_member` back to the old
``value in allowed`` logic and must raise TypeError, proving the probe bites.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
import traceback
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[8]
OUT = Path(__file__).resolve().parent / "out"
sys.path.insert(0, str(ROOT / "backend" / "src"))

from mktkb.evaluation import p2_evidence_axes_adapter_v2 as adapter  # noqa: E402
from mktkb.evaluation import p2_stale_version_state as stale  # noqa: E402

import synth_stale as synth  # noqa: E402

HOSTILE_VALUES: tuple[Any, ...] = (
    ["x"],
    {"x": 1},
    {"x"},
    None,
    True,
    1,
    [{"nested": ["x"]}],
)


def _load_p4_synth():
    path = (
        ROOT
        / "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/c1-1/p4/independent/synth.py"
    )
    spec = importlib.util.spec_from_file_location("p4synth_p1impl", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


P4 = _load_p4_synth()


def _tokens(path: str) -> list[Any]:
    tokens: list[Any] = []
    buf = ""
    index = 0
    while index < len(path):
        char = path[index]
        if char == ".":
            if buf:
                tokens.append(buf)
                buf = ""
            index += 1
        elif char == "[":
            if buf:
                tokens.append(buf)
                buf = ""
            end = path.index("]", index)
            tokens.append(int(path[index + 1 : end]))
            index = end + 1
        else:
            buf += char
            index += 1
    if buf:
        tokens.append(buf)
    return tokens


def _navigate(root: Any, path: str) -> Any:
    node = root
    for token in _tokens(path):
        node = node[token]
    return node


def _leaves(value: Any, prefix: str = ""):
    if isinstance(value, dict):
        for key in list(value):
            path = f"{prefix}.{key}" if prefix else str(key)
            child = value[key]
            if isinstance(child, (dict, list)) and child:
                yield from _leaves(child, path)
                yield path
            elif not isinstance(child, (dict, list)):
                yield path
    elif isinstance(value, list):
        for index, child in enumerate(value):
            path = f"{prefix}[{index}]"
            if isinstance(child, (dict, list)) and child:
                yield from _leaves(child, path)
                yield path
            elif not isinstance(child, (dict, list)):
                yield path


def _replace(root: Any, path: str, value: Any) -> None:
    tokens = _tokens(path)
    if not tokens:
        raise ValueError(path)
    node = root
    for token in tokens[:-1]:
        node = node[token]
    node[tokens[-1]] = value


def _case_from(determination: adapter.CaseDetermination) -> dict[str, str]:
    return {axis: f"{row.state}/{row.reason}" for axis, row in determination.axes.items()}


def _probe_adapter() -> dict[str, Any]:
    contract = P4.contract()
    snapshot = P4.snapshot([P4.record()])
    baseline = adapter.determine_case(
        contract=contract, case_id="C00", snapshot=snapshot
    )
    rows: list[dict[str, Any]] = []
    exceptions: list[dict[str, Any]] = []
    accepted = 0
    cases = [("contract", contract), ("snapshot", snapshot)]
    for label, payload in cases:
        for path in _leaves(payload):
            for hostile in HOSTILE_VALUES:
                mutated = copy.deepcopy(payload)
                _replace(mutated, path, copy.deepcopy(hostile))
                try:
                    if label == "contract":
                        determination = adapter.determine_case(
                            contract=mutated,
                            case_id="C00",
                            snapshot=copy.deepcopy(snapshot),
                        )
                    else:
                        determination = adapter.determine_case(
                            contract=copy.deepcopy(contract),
                            case_id="C00",
                            snapshot=mutated,
                        )
                    accepted += 1
                    for axis in adapter.ADAPTED_AXES:
                        row = determination.axes[axis]
                        if row.state not in {"passed", "unknown", "violation", "not_applicable"}:
                            exceptions.append(
                                {
                                    "surface": label,
                                    "path": path,
                                    "value": repr(hostile),
                                    "kind": "invalid_state",
                                    "state": row.state,
                                }
                            )
                        if row.reason.split(":", 1)[0] not in adapter.FIXED_CODES:
                            exceptions.append(
                                {
                                    "surface": label,
                                    "path": path,
                                    "value": repr(hostile),
                                    "kind": "unknown_reason",
                                    "reason": row.reason,
                                }
                            )
                except BaseException as exc:  # noqa: BLE001 - oracle must see all escapes
                    exceptions.append(
                        {
                            "surface": label,
                            "path": path,
                            "value": repr(hostile),
                            "kind": type(exc).__name__,
                            "message": str(exc)[:200],
                            "traceback": traceback.format_exc(limit=3),
                        }
                    )
                rows.append({"surface": label, "path": path, "value": repr(hostile)})
    type_errors = [row for row in exceptions if row["kind"] == "TypeError"]
    by_path: dict[str, int] = {}
    for row in type_errors:
        key = f"{row['surface']}:{row['path']}"
        by_path[key] = by_path.get(key, 0) + 1
    return {
        "baseline": _case_from(baseline),
        "mutations": len(rows),
        "accepted": accepted,
        "exception_count": len(exceptions),
        "type_error_count": len(type_errors),
        "type_error_paths": dict(sorted(by_path.items())),
        "other_exceptions": [x for x in exceptions if x["kind"] != "TypeError"],
        "type_errors": type_errors,
    }


def _negative_control_adapter() -> dict[str, Any]:
    contract = P4.contract()
    contract["cases"][0]["axes"]["cross_entity"]["criterion"] = ["x"]
    original = adapter._enum_member
    result: dict[str, Any] = {}
    try:
        adapter._enum_member = lambda value, allowed: value in allowed  # type: ignore[assignment]
        try:
            adapter.determine_case(
                contract=contract,
                case_id="C00",
                snapshot=P4.snapshot([P4.record()]),
            )
            result = {"raised": False, "exception": None}
        except BaseException as exc:  # noqa: BLE001
            result = {
                "raised": True,
                "exception": type(exc).__name__,
                "message": str(exc)[:200],
            }
    finally:
        adapter._enum_member = original  # type: ignore[assignment]
    result["old_logic_direct"] = None
    try:
        ["x"] in frozenset({"a"})
    except BaseException as exc:  # noqa: BLE001
        result["old_logic_direct"] = type(exc).__name__
    return result


def _probe_stale() -> dict[str, Any]:
    grounding = synth.grounding()
    evidence = synth.evidence(units=[synth.unit("K21")])
    baseline = stale.determine_stale_case(synth.CRITERION, grounding, evidence)
    exceptions: list[dict[str, Any]] = []
    accepted = 0
    count = 0
    for label, payload in (("grounding", grounding), ("evidence", evidence)):
        for path in _leaves(payload):
            for hostile in HOSTILE_VALUES:
                mutated = copy.deepcopy(payload)
                _replace(mutated, path, copy.deepcopy(hostile))
                try:
                    if label == "grounding":
                        determination = stale.determine_stale_case(
                            synth.CRITERION, mutated, copy.deepcopy(evidence)
                        )
                    else:
                        determination = stale.determine_stale_case(
                            synth.CRITERION, copy.deepcopy(grounding), mutated
                        )
                    accepted += 1
                    if determination.reason not in stale.DETERMINATION_CODES:
                        exceptions.append(
                            {
                                "surface": label,
                                "path": path,
                                "value": repr(hostile),
                                "kind": "unknown_reason",
                                "reason": determination.reason,
                            }
                        )
                    if stale.STATE_BY_CODE[determination.reason] != determination.state:
                        exceptions.append(
                            {
                                "surface": label,
                                "path": path,
                                "value": repr(hostile),
                                "kind": "state_reason_mismatch",
                            }
                        )
                except BaseException as exc:  # noqa: BLE001
                    exceptions.append(
                        {
                            "surface": label,
                            "path": path,
                            "value": repr(hostile),
                            "kind": type(exc).__name__,
                            "message": str(exc)[:200],
                            "traceback": traceback.format_exc(limit=3),
                        }
                    )
                count += 1
    type_errors = [row for row in exceptions if row["kind"] == "TypeError"]
    by_path: dict[str, int] = {}
    for row in type_errors:
        key = f"{row['surface']}:{row['path']}"
        by_path[key] = by_path.get(key, 0) + 1
    return {
        "baseline": {
            "state": baseline.state,
            "reason": baseline.reason,
            "grade": baseline.evidence_grade,
        },
        "mutations": count,
        "accepted": accepted,
        "exception_count": len(exceptions),
        "type_error_count": len(type_errors),
        "type_error_paths": dict(sorted(by_path.items())),
        "other_exceptions": [x for x in exceptions if x["kind"] != "TypeError"],
        "type_errors": type_errors,
    }


def _negative_control_stale() -> dict[str, Any]:
    evidence = synth.evidence(units=[synth.unit("K21")])
    # ANNOTATION_REASONS is a frozenset, so the old ``value in allowed`` logic
    # hashes the list and raises TypeError. (applicability/temporal_intent are
    # tuples upstream, so they cannot demonstrate the old failure.)
    evidence["annotation"]["reason"] = ["x"]
    original = stale._enum_member
    result: dict[str, Any] = {}
    try:
        stale._enum_member = lambda value, allowed: value in allowed  # type: ignore[assignment]
        try:
            stale.determine_stale_case(synth.CRITERION, synth.grounding(), evidence)
            result = {"raised": False, "exception": None}
        except BaseException as exc:  # noqa: BLE001
            result = {
                "raised": True,
                "exception": type(exc).__name__,
                "message": str(exc)[:200],
            }
    finally:
        stale._enum_member = original  # type: ignore[assignment]
    return result


def _site_matrix_adapter() -> list[dict[str, Any]]:
    """Each known enum site, exercised directly with list and dict."""
    contract_sites = (
        ("contract", "cases[0].axes.cross_entity.criterion"),
        ("contract", "cases[0].axes.cross_entity.reason"),
        ("contract", "cases[0].axes.cross_entity.temporal_intent"),
        ("contract", "cases[0].basis.stale_source"),
        ("contract", "runs[0].scenario_id"),
    )
    snapshot_sites = (
        ("snapshot", "effective_temporal.availability"),
        ("snapshot", "effective_temporal.as_of_source"),
        ("snapshot", "effective_temporal.observed_from"),
        ("snapshot", "effective_temporal.code"),
        ("snapshot", "effective_temporal.document_versions[0].code"),
        ("snapshot", "empty_use_scope_input.code"),
        ("snapshot", "empty_use_scope_input.turn_status"),
        ("snapshot", "source_evidence.completeness_status"),
        ("snapshot", "record_identities[0].locator_kind"),
        ("snapshot", "record_identities[0].code"),
        ("snapshot", "record_identities[0].entity_code"),
        ("snapshot", "fixture_kind"),
        ("snapshot", "source_evidence.fixture_kind"),
        ("snapshot", "binding.fixture_kind"),
    )
    rows: list[dict[str, Any]] = []
    for surface, path in contract_sites + snapshot_sites:
        for value in (["x"], {"x": 1}):
            contract = P4.contract()
            snapshot = P4.snapshot([P4.record()])
            target = contract if surface == "contract" else snapshot
            _replace(target, path, copy.deepcopy(value))
            try:
                determination = adapter.determine_case(
                    contract=contract, case_id="C00", snapshot=snapshot
                )
                codes = {
                    axis: f"{row.state}/{row.reason}"
                    for axis, row in determination.axes.items()
                }
                rows.append(
                    {
                        "surface": surface,
                        "path": path,
                        "value": repr(value),
                        "outcome": codes,
                        "escaped": None,
                    }
                )
            except BaseException as exc:  # noqa: BLE001
                rows.append(
                    {
                        "surface": surface,
                        "path": path,
                        "value": repr(value),
                        "outcome": None,
                        "escaped": type(exc).__name__,
                        "message": str(exc)[:200],
                    }
                )
    return rows


def _site_matrix_stale() -> list[dict[str, Any]]:
    sites = (
        ("evidence", "annotation.applicability"),
        ("evidence", "annotation.criterion"),
        ("evidence", "annotation.reason"),
        ("evidence", "annotation.temporal_intent"),
        ("evidence", "annotation.as_of"),
        ("grounding", "mode"),
        ("grounding", "fixture_sha256"),
        ("grounding", "scenario.source_indices"),
        ("grounding", "source_map.sources.K20.version_number"),
        ("grounding", "windows.basis"),
        ("evidence", "usage.turn_status"),
        ("evidence", "usage.units[0].code"),
    )
    rows: list[dict[str, Any]] = []
    for surface, path in sites:
        for value in (["x"], {"x": 1}):
            grounding = synth.grounding(windows=synth.windows())
            evidence = synth.evidence(units=[synth.unit("K21")])
            target = grounding if surface == "grounding" else evidence
            _replace(target, path, copy.deepcopy(value))
            try:
                determination = stale.determine_stale_case(
                    synth.CRITERION, grounding, evidence
                )
                rows.append(
                    {
                        "surface": surface,
                        "path": path,
                        "value": repr(value),
                        "outcome": f"{determination.state}/{determination.reason}",
                        "escaped": None,
                    }
                )
            except BaseException as exc:  # noqa: BLE001
                rows.append(
                    {
                        "surface": surface,
                        "path": path,
                        "value": repr(value),
                        "outcome": None,
                        "escaped": type(exc).__name__,
                        "message": str(exc)[:200],
                    }
                )
    return rows


def main() -> int:
    report = {
        "schema_version": "c1p1impl-ir01-runtime/v0.1",
        "values": [repr(value) for value in HOSTILE_VALUES],
        "adapter": _probe_adapter(),
        "adapter_negative_control": _negative_control_adapter(),
        "adapter_site_matrix": _site_matrix_adapter(),
        "stale": _probe_stale(),
        "stale_negative_control": _negative_control_stale(),
        "stale_site_matrix": _site_matrix_stale(),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "02-ir01-runtime.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "adapter_mutations": report["adapter"]["mutations"],
                "adapter_type_errors": report["adapter"]["type_error_count"],
                "adapter_type_error_paths": report["adapter"]["type_error_paths"],
                "adapter_negative_control": report["adapter_negative_control"],
                "adapter_site_escapes": [
                    row for row in report["adapter_site_matrix"] if row["escaped"]
                ],
                "stale_mutations": report["stale"]["mutations"],
                "stale_exceptions": report["stale"]["exception_count"],
                "stale_type_errors": report["stale"]["type_error_count"],
                "stale_negative_control": report["stale_negative_control"],
                "stale_site_escapes": [
                    row for row in report["stale_site_matrix"] if row["escaped"]
                ],
            },
            ensure_ascii=False,
            indent=1,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

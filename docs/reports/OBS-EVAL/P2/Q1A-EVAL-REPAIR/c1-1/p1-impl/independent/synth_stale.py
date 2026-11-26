"""C1-P1-IMPL independent synthetic corpus for `p2_stale_version_state`.

Fully fictional. No real source code, scenario id or dataset date. Mirrors the
shape of criterion §7 with renamed codes (K*) so it is not a copy of the
developer's Z*/R* fixture.
"""

from __future__ import annotations

import copy
from typing import Any

CRITERION = "p2-stale-source-criterion/v1"
AS_OF = "2031-03-01"
FIXTURE_SHA = "a" * 64

SOURCES: list[dict[str, Any]] = [
    {"path": "variants/K20_a.xlsx", "name": "K10_a.xlsx"},
    {"path": "normal/K10_a.xlsx"},
    {"path": "variants/K21_b.xlsx", "document_ref": "K10_a.xlsx"},
    {"path": "normal/K40_x.pdf"},
    {"path": "normal/K41_x.pdf"},
    {"path": "normal/K11_item.pdf"},
]

SOURCE_MAP: dict[str, Any] = {
    "sources": {
        "K20": {"base_doc_code": "K10", "version_number": 1},
        "K21": {"base_doc_code": "K10", "version_number": 3},
        "K11": {"base_doc_code": "K11"},
        "K30": {"base_doc_code": "K30", "version_number": 1},
    }
}

SCENARIO: dict[str, Any] = {
    "scenario_id": "S_syn_k",
    "source_indices": [0, 1, 2, 5],
    "ingest_batches": 99,
}

WINDOW_ROWS: dict[str, Any] = {
    "K20": {"effective_from": "2029-01-01", "effective_to": "2030-01-01"},
    "K10": {"effective_from": "2030-01-01", "effective_to": "2031-01-01"},
    "K21": {"effective_from": "2031-01-01", "effective_to": "2032-01-01"},
    "K11": {"effective_from": "2031-01-01"},
}


def annotation(**overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "applicability": "required",
        "criterion": "lifecycle_dates",
        "reason": "published_lifecycle",
        "as_of": None,
        "temporal_intent": "current",
    }
    values.update(overrides)
    return values


def unit(code: Any, **overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "unit_id": f"u-{code}",
        "code": code,
        "record_code": f"rec-{code}",
    }
    values.update(overrides)
    return values


def usage(units: Any, **overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "observed": True,
        "units": copy.deepcopy(units),
        "turn_status": "complete",
    }
    values.update(overrides)
    return values


def proven_empty_usage() -> dict[str, Any]:
    return {
        "observed": True,
        "units": [],
        "turn_status": "complete",
        "use_layers": {
            "layer_a": {"observed": True, "count": 0, "refs": []},
            "layer_b": {"observed": True, "count": 0, "refs": []},
        },
        "retrieval": {"observed": True, "count": 0, "refs": [], "truncated": False},
    }


def evidence(*, units: Any = None, with_usage: bool = True, **overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {"case_id": "K1", "annotation": annotation()}
    if with_usage:
        values["usage"] = usage([] if units is None else units)
    values.update(overrides)
    return values


def windows(
    rows: dict[str, Any] | None = None,
    *,
    open_ended: Any = None,
    **overrides: Any,
) -> dict[str, Any]:
    source_rows = copy.deepcopy(WINDOW_ROWS if rows is None else rows)
    if open_ended is None:
        open_ended = [code for code, row in source_rows.items() if "effective_to" not in row]
    values: dict[str, Any] = {
        "schema_version": "p2-source-lifecycle-window/v1",
        "bindings": {
            "source_map_sha256": "b" * 64,
            "ingest_plan_sha256": "c" * 64,
        },
        "windows": source_rows,
        "open_ended": list(open_ended),
        "basis": "owner_ruling",
        "evidence_ref": "synthetic-fixture",
    }
    values.update(overrides)
    return values


def grounding(**overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "mode": "version_state",
        "fixture_sha256": None,
        "scenario": copy.deepcopy(SCENARIO),
        "ingest_plan": {"schema_version": "p2-ingest-plan/synth", "sources": copy.deepcopy(SOURCES)},
        "source_map": copy.deepcopy(SOURCE_MAP),
        "windows": None,
    }
    values.update(overrides)
    return values


def dated_grounding(**overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "mode": "date_window",
        "fixture_sha256": FIXTURE_SHA,
        "windows": windows(),
    }
    values.update(overrides)
    return grounding(**values)


def turn(turn_index: int, state_inputs: dict[str, Any]) -> dict[str, Any]:
    return {"turn_index": turn_index, "state_inputs": state_inputs}


def leaves(value: Any, prefix: str = ""):
    """Yield (json-path, container, key) for every leaf / replaceable node."""
    if isinstance(value, dict):
        for key in list(value):
            path = f"{prefix}.{key}" if prefix else str(key)
            child = value[key]
            if isinstance(child, (dict, list)):
                yield from leaves(child, path)
                yield path, value, key  # also allow replacing the whole block
            else:
                yield path, value, key
    elif isinstance(value, list):
        for index in range(len(value)):
            path = f"{prefix}[{index}]"
            child = value[index]
            if isinstance(child, (dict, list)):
                yield from leaves(child, path)
                yield path, value, index
            else:
                yield path, value, index


__all__ = [
    "AS_OF",
    "CRITERION",
    "FIXTURE_SHA",
    "SOURCE_MAP",
    "SOURCES",
    "annotation",
    "dated_grounding",
    "evidence",
    "grounding",
    "leaves",
    "proven_empty_usage",
    "turn",
    "unit",
    "usage",
    "windows",
]

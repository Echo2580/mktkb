"""IR-02 / IR-03 independent probes on adapter v2.

IR-02: same-key target order must not change the outcome (contract v2 §3.4(3)).
IR-03: runtime `entity_key` and `entity_filters` pointing at different entities
must not be rescued into `passed`; a consistent different entity must still be a
violation.
"""

from __future__ import annotations

import copy
import importlib.util
import itertools
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[8]
OUT = Path(__file__).resolve().parent / "out"
sys.path.insert(0, str(ROOT / "backend" / "src"))

from mktkb.evaluation import p2_evidence_axes_adapter_v2 as adapter  # noqa: E402

SYNTH_PATH = (
    ROOT / "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/c1-1/p4/independent/synth.py"
)
spec = importlib.util.spec_from_file_location("p4synth_p1impl_ir", SYNTH_PATH)
P4 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(P4)


def _axis(targets: list[dict[str, Any]], *, criterion: str = "structured_target"):
    return P4.axis(
        "required",
        criterion,
        "explicit_single_target" if criterion == "structured_target" else "explicit_multi_target",
        targets=targets,
    )


def _run(targets: list[dict[str, Any]], records: list[dict[str, Any]]):
    contract = P4.contract(
        case_axes={0: P4.case_axes(cross_entity=_axis(targets))}
    )
    snapshot = P4.snapshot(records)
    return adapter.determine_case(
        contract=contract,
        case_id="C00",
        snapshot=snapshot,
        frozen_refs={"record_codes": []},
    ).axes["cross_entity"]


def _pair(row) -> tuple[str, str]:
    return row.state, row.reason


def _ir02() -> dict[str, Any]:
    loose = P4.target("item", "item|storea|itema", {"store": "StoreA"})
    strict = P4.target(
        "item", "item|storea|itema", {"store": "StoreA", "item": "ItemB"}
    )
    record_a = P4.record(
        entity_key="item|storea|itema",
        entity_filters={"store": "StoreA", "item": "ItemA"},
    )
    order_rows: list[dict[str, Any]] = []
    outcomes = set()
    for order, targets in enumerate(itertools.permutations([strict, loose])):
        result = _run(list(targets), [record_a])
        pair = _pair(result)
        outcomes.add(pair)
        order_rows.append({"order": order, "targets": [t["entity_key"] for t in targets], "outcome": pair})
    three = [strict, loose, copy.deepcopy(loose)]
    outcomes_three = set()
    for order, targets in enumerate(itertools.permutations(three)):
        result = _run(list(targets), [record_a])
        outcomes_three.add(_pair(result))
        order_rows.append(
            {
                "order": order,
                "targets": [t["entity_key"] for t in targets],
                "outcome": _pair(result),
                "kind": "three",
            }
        )
    # Same-type but different-key targets: order must not matter either.
    target_b = P4.target(
        "item", "item|storeb|itemb", {"store": "StoreB", "item": "ItemB"}
    )
    cross_key_outcomes = set()
    for order, targets in enumerate(itertools.permutations([target_b, loose])):
        result = _run(list(targets), [record_a])
        cross_key_outcomes.add(_pair(result))
        order_rows.append(
            {
                "order": order,
                "targets": [t["entity_key"] for t in targets],
                "outcome": _pair(result),
                "kind": "cross_key",
            }
        )
    # Repeat the decisive order three times for determinism.
    repeats = [_pair(_run([strict, loose], [record_a])) for _ in range(3)]
    return {
        "two_target_outcomes": sorted(outcomes),
        "three_target_outcomes": sorted(outcomes_three),
        "cross_key_outcomes": sorted(cross_key_outcomes),
        "repeat_outcomes": repeats,
        "order_rows": order_rows,
        "order_independent": len(outcomes) == 1 and len(outcomes_three) == 1,
    }


def _ir03() -> dict[str, Any]:
    target_a = P4.target(
        "item", "item|storea|itema", {"store": "StoreA", "item": "ItemA"}
    )
    cases = {
        "same_entity": P4.record(
            entity_key="item|storea|itema",
            entity_filters={"store": "StoreA", "item": "ItemA"},
        ),
        "consistent_other_entity": P4.record(
            entity_key="item|storeb|itemb",
            entity_filters={"store": "StoreB", "item": "ItemB"},
        ),
        "key_b_filters_a": P4.record(
            entity_key="item|storeb|itemb",
            entity_filters={"store": "StoreA", "item": "ItemA"},
        ),
        "key_a_filters_b": P4.record(
            entity_key="item|storea|itema",
            entity_filters={"store": "StoreB", "item": "ItemB"},
        ),
        "id_key_filters_a": P4.record(
            entity_key="item|id:999",
            entity_filters={"store": "StoreA", "item": "ItemA"},
        ),
        "store_key_b_filters_a": P4.record(
            entity_type="store",
            entity_key="store|storeb",
            entity_filters={"store": "StoreA"},
        ),
    }
    rows: dict[str, Any] = {}
    for name, record in cases.items():
        result = _run([target_a], [record])
        rows[name] = {
            "state": result.state,
            "reason": result.reason,
            "audit": list(result.provenance.get("audit", [])),
        }
    # Contradictory row alongside a matching row must not let the axis pass.
    both = _run(
        [target_a],
        [
            P4.record(
                entity_key="item|storea|itema",
                entity_filters={"store": "StoreA", "item": "ItemA"},
            ),
            P4.record(
                entity_key="item|storeb|itemb",
                entity_filters={"store": "StoreA", "item": "ItemA"},
            ),
        ],
    )
    # Record order must not change the verdict.
    both_rev = _run(
        [target_a],
        [
            P4.record(
                entity_key="item|storeb|itemb",
                entity_filters={"store": "StoreA", "item": "ItemA"},
            ),
            P4.record(
                entity_key="item|storea|itema",
                entity_filters={"store": "StoreA", "item": "ItemA"},
            ),
        ],
    )
    return {
        "rows": rows,
        "match_plus_contradiction": {
            "state": both.state,
            "reason": both.reason,
            "reversed": [both_rev.state, both_rev.reason],
            "order_independent": _pair(both) == _pair(both_rev),
        },
        "consistent_other_entity_is_violation": rows["consistent_other_entity"]["state"]
        == "violation",
        "contradictory_is_not_pass": rows["key_b_filters_a"]["state"] != "passed",
    }


def main() -> int:
    report = {
        "schema_version": "c1p1impl-ir02-ir03/v0.1",
        "ir02": _ir02(),
        "ir03": _ir03(),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "03-ir02-ir03.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "ir02_outcomes": report["ir02"]["two_target_outcomes"],
                "ir02_three": report["ir02"]["three_target_outcomes"],
                "ir02_cross_key": report["ir02"]["cross_key_outcomes"],
                "ir02_order_independent": report["ir02"]["order_independent"],
                "ir03_rows": {
                    key: [row["state"], row["reason"]]
                    for key, row in report["ir03"]["rows"].items()
                },
                "ir03_match_plus_contradiction": report["ir03"]["match_plus_contradiction"],
            },
            ensure_ascii=False,
            indent=1,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

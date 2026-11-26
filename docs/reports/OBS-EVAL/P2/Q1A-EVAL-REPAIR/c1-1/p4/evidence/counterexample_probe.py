"""C1-P4 证据：反例矩阵（逐类输出固定码；零真实调用）。

复用测试模块的**合成构造器**（不读真实 H2 数据），逐类跑一次适配器并记录
``state`` / ``code``；同时用 AST 统计测试文件里的固定码断言数。任何一类与期望码
不一致即 exit 1。
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[8]
BACKEND = ROOT / "backend"
sys.path[:0] = [
    str(BACKEND / "src"),
    str(BACKEND / "tests"),
    str(BACKEND / "tests" / "evaluation"),
]

import test_p2_evidence_axes_adapter_v2 as t  # noqa: E402

adapter = t.adapter


def _outcome(call: Callable[[], Any]) -> tuple[str, str]:
    try:
        result = call()
    except adapter.AdapterError as exc:
        return "raised", exc.code
    except Exception as exc:  # noqa: BLE001 - 供证据记录，不掩盖
        code = getattr(exc, "code", None)
        if isinstance(code, str) and code:
            return "raised", code
        return "error", type(exc).__name__ + ":" + str(exc)
    if hasattr(result, "state"):
        return str(result.state), str(result.reason)
    return "returned", ""


def _class_cases() -> list[tuple[str, str, Callable[[], Any]]]:
    entity_contract = t.build_contract(
        overrides={
            0: {
                "axes": {
                    "cross_entity": t._entity_axis(targets=[t._target()]),
                    "stale_source": t._stale_axis(),
                }
            }
        }
    )
    document_contract = t.build_contract(
        overrides={
            0: {
                "axes": {
                    "cross_entity": t._entity_axis(
                        targets=[t._target("document", "document|" + t.DOC_UUID, {})]
                    ),
                    "stale_source": t._stale_axis(),
                }
            }
        }
    )
    shared_contract = t.build_contract(
        overrides={
            0: {
                "axes": {
                    "cross_entity": t._axis(
                        criterion="shared_background",
                        reason="shared_policy",
                        targets=[],
                    ),
                    "stale_source": t._stale_axis(),
                }
            }
        }
    )
    unknown_contract = t.build_contract(
        overrides={
            0: {
                "axes": {
                    "cross_entity": t._axis(
                        applicability="unknown",
                        criterion="structured_target",
                        reason="unresolved_target",
                        targets=[t._target()],
                    ),
                    "stale_source": t._stale_axis(),
                }
            }
        }
    )
    class_c_snapshot = t._case_snapshot(
        0, records=[], empty_use=t.make_empty_use(retrieval_observed=False)
    )
    records = [t.make_record()]
    version_mismatch = t._case_snapshot(
        0,
        records=records,
        temporal=t.make_temporal(
            versions=[t.make_version(runtime=2, product=1, code="version_mismatch")]
        ),
    )
    missing_temporal = t._case_snapshot(
        0, records=records, temporal=t.make_temporal(availability="not_observed")
    )
    missing_field = t.make_snapshot()
    del missing_field["binding"]["run_id"]
    unknown_key = t.make_snapshot()
    unknown_key["extra"] = 1
    cross_run = t.make_snapshot(run_id="run-99")
    v1_payload = {"schema_version": t.Q1A2_CONTRACT_SCHEMA_VERSION}
    v1_shaped = t.build_contract(schema_version=t.Q1A2_CONTRACT_SCHEMA_VERSION)
    del v1_shaped["projection"]
    extra_key_contract = t.build_contract()
    extra_key_contract["extra"] = 1
    v1_sha_contract = t.build_contract(bindings=t._bindings(schema_sha=t.V1_SHA))
    arbitrary_sha_contract = t.build_contract(
        bindings=t._bindings(schema_sha=t._sha("arbitrary"))
    )
    replayed = t.make_snapshot(records=records, completeness="replayed")

    def forged_na() -> Any:
        forged = adapter.AxisDetermination(
            axis="cross_entity",
            case_id="C01",
            state="not_applicable",
            reason=adapter.NOT_APPLICABLE_CODE,
        )
        return adapter.validate_determination(
            forged, applicability="unknown", criterion="no_entity_claim"
        )

    return [
        (
            "v1_contract_rejected_by_v2_adapter",
            "contract_version_v1_rejected_by_v2_adapter",
            lambda: adapter.load_contract_v2(v1_payload),
        ),
        (
            "v1_shaped_contract_rejected_by_v2_adapter",
            "contract_version_v1_rejected_by_v2_adapter",
            lambda: adapter.load_contract_v2(v1_shaped),
        ),
        (
            "v2_contract_rejected_by_v1_constants",
            "contract_schema_invalid",
            lambda: t.load_q1a2_contract_view(t.build_contract()),
        ),
        (
            "v1_schema_sha_bound_to_v2_version",
            "contract_schema_binding_mismatch",
            lambda: adapter.load_contract_v2(v1_sha_contract),
        ),
        (
            "arbitrary_schema_sha_without_expected",
            "contract_schema_binding_mismatch",
            lambda: adapter.load_contract_v2(arbitrary_sha_contract),
        ),
        (
            "contract_unknown_top_level_key",
            "contract_schema_invalid",
            lambda: adapter.load_contract_v2(extra_key_contract),
        ),
        (
            "document_target_no_violation",
            "target_granularity_incomparable",
            lambda: adapter.determine_case(
                contract=document_contract,
                case_id="C01",
                snapshot=t._case_snapshot(0, records=[t.make_document_record()]),
                frozen_refs=t.FROZEN_REFS,
            ).axes["cross_entity"],
        ),
        (
            "class_c_empty_set_not_proven",
            "empty_set_not_proven",
            lambda: adapter.determine_case(
                contract=entity_contract,
                case_id="C01",
                snapshot=class_c_snapshot,
                frozen_refs=t.FROZEN_REFS,
            ).axes["stale_source"],
        ),
        (
            "snapshot_missing_field",
            "snapshot_field_missing:binding.run_id",
            lambda: adapter.determine_case(
                contract=t.build_contract(), case_id="C01", snapshot=missing_field
            ).axes["cross_entity"],
        ),
        (
            "cross_run_snapshot",
            "snapshot_run_binding_mismatch",
            lambda: adapter.determine_case(
                contract=t.build_contract(), case_id="C01", snapshot=cross_run
            ).axes["cross_entity"],
        ),
        (
            "snapshot_unknown_key",
            "snapshot_unknown_field:extra",
            lambda: adapter.determine_case(
                contract=t.build_contract(), case_id="C01", snapshot=unknown_key
            ).axes["cross_entity"],
        ),
        (
            "identity_unresolvable",
            "identity_unresolved",
            lambda: adapter.determine_case(
                contract=entity_contract,
                case_id="C01",
                snapshot=t._case_snapshot(0, records=[t.make_unresolved_record()]),
                frozen_refs=t.FROZEN_REFS,
            ).axes["cross_entity"],
        ),
        (
            "entity_key_space_incompatible",
            "entity_key_space_incompatible",
            lambda: adapter.determine_case(
                contract=entity_contract,
                case_id="C01",
                snapshot=t._case_snapshot(
                    0,
                    records=[
                        t.make_record(entity_key="item|id:P02", entity_filters={"item_id": "P02"})
                    ],
                ),
                frozen_refs=t.FROZEN_REFS,
            ).axes["cross_entity"],
        ),
        (
            "runtime_entity_key_with_uuid_document_level",
            "target_granularity_incomparable",
            lambda: adapter.determine_case(
                contract=entity_contract,
                case_id="C01",
                snapshot=t._case_snapshot(
                    0,
                    records=[
                        t.make_record(
                            entity_type="item",
                            entity_key="item|" + t.DOC_UUID,
                            entity_filters={"store": "StoreA", "item": "ItemA"},
                        )
                    ],
                ),
                frozen_refs=t.FROZEN_REFS,
            ).axes["cross_entity"],
        ),
        (
            "unknown_to_not_applicable_forbidden",
            "unknown_to_not_applicable_forbidden",
            forged_na,
        ),
        (
            "unknown_annotation_not_downgraded",
            "annotation_unknown",
            lambda: adapter.determine_case(
                contract=unknown_contract,
                case_id="C01",
                snapshot=t._case_snapshot(0, records=[t.make_record()]),
            ).axes["cross_entity"],
        ),
        (
            "shared_background_not_passed",
            "shared_background_runtime_identity_unavailable",
            lambda: adapter.determine_case(
                contract=shared_contract,
                case_id="C01",
                snapshot=t._case_snapshot(0, records=[t.make_record()]),
                frozen_refs=t.FROZEN_REFS,
            ).axes["cross_entity"],
        ),
        (
            "stale_version_mismatch_not_passed",
            "version_mismatch",
            lambda: adapter.determine_case(
                contract=entity_contract,
                case_id="C01",
                snapshot=version_mismatch,
                frozen_refs=t.FROZEN_REFS,
            ).axes["stale_source"],
        ),
        (
            "stale_as_of_missing",
            "as_of_missing",
            lambda: adapter.determine_case(
                contract=entity_contract,
                case_id="C01",
                snapshot=missing_temporal,
                frozen_refs=t.FROZEN_REFS,
            ).axes["stale_source"],
        ),
        (
            "counts_formula_guard",
            "axis_counts_inconsistent",
            lambda: adapter.AxisCounts(
                axis="cross_entity",
                planned=3,
                checked=3,
                passed=1,
                not_applicable=0,
                unknown=1,
                violations=0,
            ).verify(),
        ),
        (
            "replayed_source_evidence",
            "snapshot_source_evidence_replayed",
            lambda: adapter.determine_case(
                contract=t.build_contract(), case_id="C01", snapshot=replayed
            ).axes["cross_entity"],
        ),
        (
            "contract_missing",
            "contract_missing",
            lambda: adapter.determine_case(
                contract=None, case_id="C01", snapshot=t.make_snapshot()
            ).axes["cross_entity"],
        ),
    ]


def _key_space_probe() -> dict[str, Any]:
    contract = t.build_contract(
        overrides={
            0: {
                "axes": {
                    "cross_entity": t._entity_axis(targets=[t._target()]),
                    "stale_source": t._stale_axis(),
                }
            },
            1: {
                "axes": {
                    "cross_entity": t._entity_axis(targets=[t._target()]),
                    "stale_source": t._stale_axis(),
                }
            },
        }
    )
    snapshots = [
        t._case_snapshot(0, records=[t.make_record()]),
        t._case_snapshot(
            1,
            records=[
                t.make_record(entity_key="item|id:P02", entity_filters={"item_id": "P02"})
            ],
        ),
    ]
    determinations = [
        adapter.determine_case(
            contract=contract,
            case_id=f"C{index + 1:02d}",
            snapshot=snapshot,
            frozen_refs=t.FROZEN_REFS,
        )
        for index, snapshot in enumerate(snapshots)
    ]
    states = {
        f"C{index + 1:02d}": {
            "state": determination.axes["cross_entity"].state,
            "reason": determination.axes["cross_entity"].reason,
        }
        for index, determination in enumerate(determinations)
    }
    affected = sum(
        1
        for determination in determinations
        if determination.axes["cross_entity"].reason == "entity_key_space_incompatible"
    )
    return {
        "cases": len(determinations),
        "states": states,
        "affected_axes": affected,
        "rule": "canonical_role_filters_v2",
    }


def _positive() -> dict[str, Any]:
    contract = t.build_contract(
        overrides={
            0: {
                "axes": {
                    "cross_entity": t._entity_axis(targets=[t._target()]),
                    "stale_source": t._stale_axis(as_of="2026-10-28"),
                }
            },
            1: {
                "axes": {
                    "cross_entity": t._entity_axis(targets=[t._target()]),
                    "stale_source": t._stale_axis(as_of="2026-10-27"),
                }
            },
            2: {
                "axes": {
                    "cross_entity": t._entity_axis(
                        targets=[t._target("document", "document|" + t.DOC_UUID, {})]
                    ),
                    "stale_source": t._stale_axis(as_of="2026-10-28"),
                }
            },
        }
    )
    snapshots = [
        t._case_snapshot(0, records=[t.make_record()]),
        t._case_snapshot(
            1,
            records=[
                t.make_record(
                    entity_key="item|storeb|itemb",
                    entity_filters={"store": "StoreB", "item": "ItemB"},
                )
            ],
        ),
        t._case_snapshot(2, empty_use=t.make_empty_use(retrieval_observed=False)),
    ]
    determinations = [
        adapter.determine_case(
            contract=contract,
            case_id=f"C{index + 1:02d}",
            snapshot=snapshot,
            frozen_refs=t.FROZEN_REFS,
        )
        for index, snapshot in enumerate(snapshots)
    ]
    cross = adapter.aggregate_axis(determinations, "cross_entity")
    stale = adapter.aggregate_axis(determinations, "stale_source")
    return {
        "case_states": {
            f"C{index + 1:02d}": {
                axis: {
                    "state": determination.axes[axis].state,
                    "reason": determination.axes[axis].reason,
                }
                for axis in adapter.ADAPTED_AXES
            }
            for index, determination in enumerate(determinations)
        },
        "counts": {
            "cross_entity": {
                key: value
                for key, value in cross.as_dict().items()
                if key != "formulas"
            },
            "stale_source": {
                key: value
                for key, value in stale.as_dict().items()
                if key != "formulas"
            },
        },
        "reason_histogram": {
            "cross_entity": adapter.reason_histogram(determinations, "cross_entity"),
            "stale_source": adapter.reason_histogram(determinations, "stale_source"),
        },
        "key_space_affected_axes": sum(
            1
            for determination in determinations
            if determination.axes["cross_entity"].reason == "entity_key_space_incompatible"
        ),
        "formulas_verified": True,
    }


def _assertion_count() -> tuple[int, int]:
    path = BACKEND / "tests" / "evaluation" / "test_p2_evidence_axes_adapter_v2.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    tests = 0
    fixed = 0
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
            tests += 1
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assert):
            continue
        for child in ast.walk(node):
            if isinstance(child, ast.Constant) and isinstance(child.value, str):
                if child.value.split(":", 1)[0] in adapter.FIXED_CODES:
                    fixed += 1
    return tests, fixed


def main() -> int:
    classes = []
    all_match = True
    for class_id, expected, call in _class_cases():
        state, code = _outcome(call)
        match = code == expected
        all_match = all_match and match
        classes.append(
            {
                "id": class_id,
                "expected_code": expected,
                "observed_state": state,
                "observed_code": code,
                "match": match,
            }
        )
    tests, fixed_assertions = _assertion_count()
    payload = {
        "schema_version": "c1p4-counterexample-matrix/v0.1",
        "counterexample_classes": len(classes),
        "all_match": all_match,
        "fixed_code_assertions_in_tests": fixed_assertions,
        "test_functions": tests,
        "classes": classes,
        "positive": _positive(),
        "key_space_probe": _key_space_probe(),
        "zero_real_calls": True,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=1))
    return 0 if all_match else 1


if __name__ == "__main__":
    raise SystemExit(main())

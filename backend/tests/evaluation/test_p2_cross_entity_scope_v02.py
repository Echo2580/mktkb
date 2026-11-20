"""T207 B-R2：cross_entity 可核归属 v0.2（scope 合同）红绿测试。

只用自建 CaseSpec/annotation/正文/记录与合成 envelope；不读真实 14 题、不读私有附件。
旧 v0.2/v0.3 annotation 语义在“无合同/合同无该 case”时逐值保持；新语义只在显式
`p2-entity-scope/v0.1`（semantics v0.2）合同下生效。
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path
from typing import Any

import pytest

_TESTS_DIR = Path(__file__).resolve().parents[1]
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

from acceptance.support.netguard import t09_network_guard  # noqa: E402,F401

from mktkb.evaluation import p2_hard_evidence as hard  # noqa: E402
from evaluation.test_p2_hard_evidence import (  # noqa: E402
    EVIDENCE_BINDINGS,
    build_evidence,
    legacy_no_model_empty_scope,
    make_addendum,
    make_annotation,
    make_audit,
    make_cases,
    model_answer_empty_scope,
)

pytestmark = pytest.mark.usefixtures("t09_network_guard")

SEMANTICS_VERSION = "p2-hard-evidence-classification/v0.2"
SCOPE_SCHEMA = "p2-entity-scope/v0.1"
SYNTHETIC_ANNOTATION_CIPHER_SHA = "9d" * 32

CASES = make_cases(10)
CASE = CASES[1]  # 单回合、非 gap case
GAP_CASES = make_cases(30)
GAP_CASE = GAP_CASES[3]  # addendum 中带 request_scoped disclosure 的 cross_entity gap

#: 合同要求 plan_sha256 为 64-hex；合成 envelope 使用同一组绑定以验证“逐值绑定”。
BINDINGS = dict(EVIDENCE_BINDINGS)
BINDINGS["plan_sha256"] = "e" * 64

DEFAULT_TARGETS = [
    {"entity_type": "store", "entity_key": "SYN-STORE-1", "filters": {}},
]


def _evidence(**opts: Any) -> dict[str, Any]:
    opts.setdefault("bindings", BINDINGS)
    return build_evidence(**opts)


def contract_payload(
    *,
    case_key: str = CASE.case_id,
    mode: str = "entity_bound",
    targets: list[dict[str, Any]] | None = None,
    shared: list[dict[str, Any]] | None = None,
    bindings: dict[str, str] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": SCOPE_SCHEMA,
        "semantics_version": SEMANTICS_VERSION,
        "bindings": bindings
        or {
            "run_id": BINDINGS["run_id"],
            "plan_id": BINDINGS["plan_id"],
            "plan_sha256": BINDINGS["plan_sha256"],
        },
        "cases": [
            {
                "case_key": case_key,
                "mode": mode,
                "targets": list(DEFAULT_TARGETS if targets is None else targets),
                "shared_background": list(shared or ()),
            }
        ],
    }


def contract(**kwargs: Any) -> hard.ScopeContract:
    return hard.load_scope_contract(contract_payload(**kwargs))


def annotation_for(
    case: Any = CASE, *, cross_entity: dict[str, Any] | None = None
) -> Any:
    overrides = {"cross_entity": cross_entity} if cross_entity is not None else None
    payload = make_annotation((case,), overrides={case.case_id: overrides} if overrides else None)
    return hard.prepare_annotation(payload, (case,))


def classify(
    case: Any,
    annotation: Any,
    evidence: dict[str, Any],
    *,
    scope_contract: hard.ScopeContract | None = None,
) -> Any:
    return hard.classify_case_evidence(
        case,
        annotation,
        make_audit(case, evidence),
        scope_contract=scope_contract,
    )


def ce(result: Any) -> tuple[str, str]:
    axis = result.axes["cross_entity"]
    return axis.state, axis.reason


def _unit(unit_id: str, entity_type: str | None, entity_key: str | None, **extra: Any) -> dict[str, Any]:
    row = {"unit_id": unit_id, "entity_type": entity_type, "entity_key": entity_key}
    row.update(extra)
    return row


# --------------------------------------------------------------------------- #
# 1) 旧语义保持 / 显式版本闸门
# --------------------------------------------------------------------------- #


def test_old_semantics_unchanged_without_contract() -> None:
    evidence = _evidence(units=[_unit("u1", "store", "SYN-STORE-1")])
    result = classify(CASE, annotation_for(), evidence)
    assert ce(result) == ("unknown", "targets_unresolved")


def test_contract_without_case_entry_falls_back_to_old_semantics() -> None:
    evidence = _evidence(units=[_unit("u1", "store", "SYN-STORE-1")])
    other = contract(case_key="SYN-99")
    result = classify(CASE, annotation_for(), evidence, scope_contract=other)
    assert ce(result) == ("unknown", "targets_unresolved")


def test_contract_binding_mismatch_is_unknown() -> None:
    evidence = _evidence(units=[_unit("u1", "store", "SYN-STORE-1")])
    mismatched = contract(
        bindings={
            "run_id": "other-run",
            "plan_id": BINDINGS["plan_id"],
            "plan_sha256": BINDINGS["plan_sha256"],
        }
    )
    result = classify(CASE, annotation_for(), evidence, scope_contract=mismatched)
    assert ce(result) == ("unknown", "targets_unresolved")


# --------------------------------------------------------------------------- #
# 2) entity_bound：完整身份 + 多目标 + 同 key 异类型/过滤
# --------------------------------------------------------------------------- #


def test_entity_bound_same_entity_passes() -> None:
    evidence = _evidence(
        units=[_unit("u1", "store", "SYN-STORE-1", entity_filters={"channel": "online"})]
    )
    sc = contract(
        targets=[
            {
                "entity_type": "store",
                "entity_key": "SYN-STORE-1",
                "filters": {"channel": "online"},
            }
        ]
    )
    result = classify(CASE, annotation_for(), evidence, scope_contract=sc)
    assert ce(result)[0] == "passed"


def test_other_entity_used_is_violation() -> None:
    evidence = _evidence(units=[_unit("u1", "store", "SYN-STORE-2")])
    result = classify(CASE, annotation_for(), evidence, scope_contract=contract())
    assert ce(result) == ("violation", "other_entity_used")


def test_same_key_different_type_is_violation() -> None:
    evidence = _evidence(units=[_unit("u1", "item", "SYN-STORE-1")])
    result = classify(CASE, annotation_for(), evidence, scope_contract=contract())
    assert ce(result)[0] == "violation"


def test_target_filters_must_match_exactly() -> None:
    evidence = _evidence(
        units=[_unit("u1", "store", "SYN-STORE-1", entity_filters={"channel": "offline"})]
    )
    sc = contract(
        targets=[
            {
                "entity_type": "store",
                "entity_key": "SYN-STORE-1",
                "filters": {"channel": "online"},
            }
        ]
    )
    result = classify(CASE, annotation_for(), evidence, scope_contract=sc)
    assert ce(result)[0] == "violation"


def test_multi_target_each_used_unit_must_match() -> None:
    evidence = _evidence(
        units=[
            _unit("u1", "store", "SYN-STORE-1"),
            _unit("u2", "store", "SYN-STORE-3"),
        ]
    )
    sc = contract(
        targets=[
            {"entity_type": "store", "entity_key": "SYN-STORE-1", "filters": {}},
            {"entity_type": "store", "entity_key": "SYN-STORE-2", "filters": {}},
        ]
    )
    result = classify(CASE, annotation_for(), evidence, scope_contract=sc)
    assert ce(result)[0] == "violation"


def test_citation_only_mismatch_uses_citation_reason() -> None:
    evidence = _evidence(
        units=[_unit("u1", "store", "SYN-STORE-2")],
        model_evidence=[],
        final_source_ids=["u1"],
    )
    result = classify(CASE, annotation_for(), evidence, scope_contract=contract())
    assert ce(result) == ("violation", "citation_entity_mismatch")


# --------------------------------------------------------------------------- #
# 3) shared_background：精确单元 + scope + 混合文档
# --------------------------------------------------------------------------- #


def _shared_entry(**overrides: Any) -> dict[str, Any]:
    entry = {
        "document_id": "doc-1",
        "version_id": "ver-1",
        "unit_ids": ["u1"],
        "scope_filters": {"store": "SYN-STORE-1"},
        "basis": "frozen_public_corpus_structure",
    }
    entry.update(overrides)
    return entry


def test_shared_background_exact_unit_passes() -> None:
    evidence = _evidence(
        units=[_unit("u1", None, None)],
        plan={"path": "legacy", "filters": {"store": "SYN-STORE-1"}},
    )
    sc = contract(mode="shared_background_only", targets=[], shared=[_shared_entry()])
    result = classify(CASE, annotation_for(), evidence, scope_contract=sc)
    assert ce(result)[0] == "passed"


def test_shared_background_wrong_version_unresolved() -> None:
    evidence = _evidence(
        units=[_unit("u1", None, None)],
        plan={"path": "legacy", "filters": {"store": "SYN-STORE-1"}},
    )
    sc = contract(
        mode="shared_background_only",
        targets=[],
        shared=[_shared_entry(version_id="ver-2")],
    )
    result = classify(CASE, annotation_for(), evidence, scope_contract=sc)
    assert ce(result) == ("unknown", "free_text_attribution_unverifiable")


def test_shared_background_scope_filter_mismatch_unresolved() -> None:
    evidence = _evidence(
        units=[_unit("u1", None, None)],
        plan={"path": "legacy", "filters": {"store": "SYN-STORE-2"}},
    )
    sc = contract(mode="shared_background_only", targets=[], shared=[_shared_entry()])
    result = classify(CASE, annotation_for(), evidence, scope_contract=sc)
    assert ce(result) == ("unknown", "free_text_attribution_unverifiable")


def test_shared_document_does_not_exempt_other_entities() -> None:
    evidence = _evidence(
        units=[
            _unit("u1", None, None),
            _unit("u2", "store", "SYN-STORE-2"),
        ],
        plan={"path": "legacy", "filters": {"store": "SYN-STORE-1"}},
    )
    sc = contract(mode="shared_background_only", targets=[], shared=[_shared_entry()])
    result = classify(CASE, annotation_for(), evidence, scope_contract=sc)
    assert ce(result) == ("violation", "other_entity_used")


def test_unstructured_without_mapping_is_unresolved() -> None:
    evidence = _evidence(units=[_unit("u1", None, None)])
    result = classify(CASE, annotation_for(), evidence, scope_contract=contract())
    assert ce(result) == ("unknown", "free_text_attribution_unverifiable")


# --------------------------------------------------------------------------- #
# 4) direct RAG fact 的底层身份 / 模式冲突 / 请求范围披露 / 严格空集
# --------------------------------------------------------------------------- #


def test_fact_backing_identity_mismatch_cannot_pass() -> None:
    evidence = _evidence(
        units=[_unit("u1", None, None)],
        plan={"path": "rag"},
        use_model=False,
        facts=[{"source_unit_id": "u1", "entity_key": "SYN-STORE-1"}],
    )
    sc = contract(mode="entity_bound")
    result = classify(CASE, annotation_for(), evidence, scope_contract=sc)
    assert ce(result)[0] == "unknown"


def test_no_entity_scope_with_structured_use_conflicts() -> None:
    evidence = _evidence(units=[_unit("u1", "store", "SYN-STORE-1")])
    sc = contract(mode="no_entity_scope", targets=[])
    result = classify(CASE, annotation_for(), evidence, scope_contract=sc)
    assert ce(result) == ("unknown", "entity_scope_conflict")


def test_no_entity_scope_true_empty_set_is_not_applicable() -> None:
    evidence = model_answer_empty_scope(bindings=BINDINGS)
    na_annotation = annotation_for(
        cross_entity={
            "applicability": "not_applicable",
            "criterion": "no_entity_claim",
            "reason": "no_entity_scope",
        }
    )
    sc = contract(mode="no_entity_scope", targets=[])
    result = classify(CASE, na_annotation, evidence, scope_contract=sc)
    assert ce(result)[0] == "not_applicable"


def test_shared_background_mode_still_requires_strict_empty_for_empty_use() -> None:
    evidence = legacy_no_model_empty_scope(bindings=BINDINGS)
    sc = contract(mode="shared_background_only", targets=[], shared=[_shared_entry()])
    result = classify(CASE, annotation_for(), evidence, scope_contract=sc)
    # 旧契约：required 轴 + 严格空集证明成立 = 明确范围空集 pass（不是 N/A）。
    assert ce(result)[0] == "passed"


def test_request_scoped_disclosure_keeps_unverifiable() -> None:
    cases = GAP_CASES
    case = GAP_CASE
    payload = make_annotation(cases)
    addendum = make_addendum(
        cases, payload, annotation_cipher_sha256=SYNTHETIC_ANNOTATION_CIPHER_SHA
    )
    merged = hard.prepare_annotation(
        payload,
        cases,
        addendum=addendum,
        annotation_cipher_sha256=SYNTHETIC_ANNOTATION_CIPHER_SHA,
    )
    evidence = _evidence(
        units=[_unit("u1", "store", "SYN-STORE-1")], plan={"path": "legacy"}
    )
    sc = contract(
        case_key=case.case_id,
        targets=[
            {"entity_type": "store", "entity_key": "SYN-STORE-1", "filters": {}}
        ],
    )
    result = hard.classify_case_evidence(
        case, merged, make_audit(case, evidence), scope_contract=sc
    )
    assert ce(result) == ("unknown", "request_scope_identity_unverifiable")


# --------------------------------------------------------------------------- #
# 5) 合同加载严格拒绝
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: p.update(schema_version="p2-entity-scope/v9.9"),
        lambda p: p.update(semantics_version="p2-hard-evidence-classification/v0.1"),
        lambda p: p.update(extra=1),
        lambda p: p["cases"][0].update(mode="not-a-mode"),
        lambda p: p["cases"][0].update(targets=[]),
        lambda p: p["cases"][0]["targets"][0].update(entity_key=""),
        lambda p: p["cases"][0]["targets"][0].update(filters={"store": 1}),
        lambda p: p["cases"][0].update(shared_background=[dict(_shared_entry(), unit_ids=[])]),
        lambda p: p["cases"][0].update(shared_background=[dict(_shared_entry(), basis="free")]),
        lambda p: p["cases"][0].update(case_key=""),
        lambda p: p["cases"].append(copy.deepcopy(p["cases"][0])),
    ],
)
def test_scope_contract_loader_rejects_bad_payloads(mutate: Any) -> None:
    payload = copy.deepcopy(contract_payload())
    mutate(payload)
    with pytest.raises(hard.HardEvidenceError):
        hard.load_scope_contract(payload)


def test_scope_contract_loader_rejects_cross_run_expected_bindings() -> None:
    payload = contract_payload()
    with pytest.raises(hard.HardEvidenceError):
        hard.load_scope_contract(
            payload,
            expected_bindings={
                "run_id": "other-run",
                "plan_id": BINDINGS["plan_id"],
                "plan_sha256": BINDINGS["plan_sha256"],
            },
        )


# --------------------------------------------------------------------------- #
# 6) 违规与 unknown 并存 / 模式冲突 / 合同透传
# --------------------------------------------------------------------------- #


def test_violation_is_not_hidden_by_another_unknown() -> None:
    evidence = _evidence(
        units=[
            _unit("u1", "store", "SYN-STORE-2"),
            _unit("u2", None, None),
        ]
    )
    result = classify(CASE, annotation_for(), evidence, scope_contract=contract())
    assert ce(result) == ("violation", "other_entity_used")
    assert "free_text_attribution_unverifiable" in result.axes["cross_entity"].missing


def test_annotation_not_applicable_conflicts_with_entity_bound() -> None:
    evidence = _evidence(units=[_unit("u1", "store", "SYN-STORE-1")])
    na_annotation = annotation_for(
        cross_entity={
            "applicability": "not_applicable",
            "criterion": "no_entity_claim",
            "reason": "no_entity_scope",
        }
    )
    result = classify(CASE, na_annotation, evidence, scope_contract=contract())
    assert ce(result) == ("unknown", "entity_scope_conflict")


def test_duplicate_projection_unit_ids_fail_closed() -> None:
    evidence = _evidence(
        units=[
            _unit("u1", "store", "SYN-STORE-2"),
            _unit("u1", "store", "SYN-STORE-1"),
        ]
    )
    result = classify(CASE, annotation_for(), evidence, scope_contract=contract())
    assert ce(result) == ("unknown", "entity_identity_unresolved")


def test_shared_background_scope_unprovable_helper_is_none() -> None:
    unit = {"unit_id": "u1", "document_id": "doc-1", "version_id": "ver-1"}
    entries = (
        {
            "document_id": "doc-1",
            "version_id": "ver-1",
            "unit_ids": ["u1"],
            "scope_filters": {"store": "SYN-STORE-1"},
        },
    )
    assert hard._shared_background_coverage(unit, entries, None) is None


def test_recompute_passes_contract_to_case_classification() -> None:
    evidence = _evidence(units=[_unit("u1", "store", "SYN-STORE-1")])
    audit = make_audit(CASE, evidence)
    card, results = hard.recompute_hard_evidence(
        (CASE,),
        annotation_for(),
        (audit,),
        plan_meta={"run_id": BINDINGS["run_id"], "thresholds_approved": True},
        scope_contract=contract(),
    )
    assert results[0].axis_state("cross_entity") == "passed"
    assert card["hard_evidence"]["axes"]["cross_entity"]["passed"] == 1


def test_recompute_cli_parser_accepts_scope_contract(tmp_path: Path) -> None:
    from mktkb.evaluation.cli import build_parser

    path = tmp_path / "scope.json"
    path.write_text("{}", encoding="utf-8")
    args = build_parser().parse_args(
        [
            "p2-hard-evidence-recompute",
            "--evidence-dir",
            str(tmp_path / "evidence"),
            "--case-plan",
            str(tmp_path / "plan.json"),
            "--cases",
            str(tmp_path / "cases.jsonl"),
            "--annotation",
            str(tmp_path / "annotation.json"),
            "--key-file",
            str(tmp_path / "key"),
            "--out",
            str(tmp_path / "out.json"),
            "--scope-contract",
            str(path),
        ]
    )
    assert args.scope_contract == str(path)

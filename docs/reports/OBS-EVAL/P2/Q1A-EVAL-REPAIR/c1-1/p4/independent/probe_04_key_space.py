"""必测 4：键空间规则 —— 确定性、无前缀/包含/模糊匹配、R-ENT-1 复算保真、顺序依赖。"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from harness import Checks
import synth

from mktkb.evaluation import p2_evidence_axes_adapter_v2 as adapter
from mktkb.evaluation.p2_evidence_axes_adapter_v2 import (
    load_contract_v2,
    load_snapshot_v03,
)
from mktkb.rag.chunking import _entity as chunking_entity
from mktkb.rag.types import DocumentSpec

REPO = Path(__file__).resolve().parents[8]
ADAPTER_PATH = REPO / "backend/src/mktkb/evaluation/p2_evidence_axes_adapter_v2.py"

DOC = DocumentSpec(
    doc_id="D01",
    source_path="fixtures/acceptance/normal/D01 门店物品表.xlsx",
    title="D01",
    file_kind="xlsx",
    version_id="v1",
    version_label="v1",
    sha256="0" * 64,
)


# --------------------------------------------------------------------------- #
# 静态：是否存在前缀/包含/模糊匹配
# --------------------------------------------------------------------------- #

FUZZY_MODULES = {"fnmatch", "difflib", "rapidfuzz", "fuzzywuzzy", "Levenshtein", "jellyfish"}
KEY_ATTRS = {"startswith", "endswith", "find", "index", "count", "casefold", "lower", "upper", "strip"}


def static_scan() -> dict[str, Any]:
    source = ADAPTER_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module.split(".")[0])
    fuzzy_imports = sorted(imports & FUZZY_MODULES)

    key_lines: list[dict[str, Any]] = []
    for line_number, line in enumerate(source.splitlines(), start=1):
        if "entity_key" not in line:
            continue
        stripped = line.strip()
        if stripped.startswith("#"):
            classification = "comment"
        elif ".startswith(" in stripped:
            classification = "prefix_classification"
        elif re.search(r"entity_key\s*(==|!=)", stripped) or re.search(r"(==|!=)\s*[\w.\[\]\"]*entity_key", stripped):
            classification = "exact_equality"
        elif re.search(r"entity_key\s+in\s+", stripped) or re.search(r"in\s+[\w.]*entity_key", stripped):
            classification = "exact_membership"
        elif "entity_key" in stripped:
            classification = "other"
        else:
            classification = "unknown"
        key_lines.append({"line": line_number, "text": stripped, "class": classification})

    fuzzy_calls: list[dict[str, Any]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in KEY_ATTRS:
                fuzzy_calls.append(
                    {
                        "line": node.lineno,
                        "attr": node.func.attr,
                        "text": ast.get_source_segment(source, node) or "",
                    }
                )
    substring_memberships: list[dict[str, Any]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare) and any(isinstance(op, (ast.In, ast.NotIn)) for op in node.ops):
            segment = ast.get_source_segment(source, node) or ""
            if "entity_key" in segment or "entity_type" in segment:
                substring_memberships.append({"line": node.lineno, "text": segment})

    return {
        "module_imports": sorted(imports),
        "fuzzy_imports": fuzzy_imports,
        "entity_key_lines": key_lines,
        "key_attribute_calls": fuzzy_calls,
        "entity_key_membership_sites": substring_memberships,
        "prefix_sites": [row for row in key_lines if row["class"] == "prefix_classification"],
        "exact_sites": [row for row in key_lines if row["class"] in {"exact_equality", "exact_membership"}],
        "other_sites": [row for row in key_lines if row["class"] == "other"],
    }


# --------------------------------------------------------------------------- #
# 运行时矩阵
# --------------------------------------------------------------------------- #


def outcome(cross_axis: Mapping[str, Any], records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    payload = synth.contract({0: synth.case_axes(cross_entity=cross_axis)})
    contract = load_contract_v2(payload)
    snap = load_snapshot_v03(synth.snapshot(records))
    det = adapter.determine_cross_entity(contract, contract.cases["C00"], snap)
    target = contract.cases["C00"].axes["cross_entity"].targets[0] if contract.cases["C00"].axes["cross_entity"].targets else None
    return {
        "state": det.state,
        "reason": det.reason,
        "evidence": list(det.evidence),
        "row_space": (det.provenance.get("record_key_spaces") or {}),
        "target_space": adapter._target_key_space(target) if target is not None else None,
    }


def axis_with(targets: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    return synth.axis("required", "structured_target", "explicit_single_target", targets=targets)


def main() -> dict:
    checks = Checks("04-key-space")
    scan = static_scan()

    # ---- 静态检查 ---------------------------------------------------------- #
    checks.eq("no_fuzzy_imports", scan["fuzzy_imports"], [])
    checks.eq(
        "prefix_sites_count",
        len(scan["prefix_sites"]),
        1,
        [row["text"] for row in scan["prefix_sites"]],
    )
    checks.record(
        "prefix_sites_are_document_classification_only",
        all(row["text"] == 'entity_key.startswith("document|")' for row in scan["prefix_sites"]),
        [row["text"] for row in scan["prefix_sites"]],
    )
    exact_texts = [row["text"] for row in scan["exact_sites"]]
    checks.record(
        "entity_key_comparisons_are_exact_equality_or_membership",
        all("==" in text or "!=" in text or " in " in text for text in exact_texts),
        exact_texts,
    )
    checks.record(
        "no_key_attribute_matching_calls_except_classification",
        all(
            call["attr"] in {"strip", "casefold", "lower"}
            or "path" in call["text"]
            for call in scan["key_attribute_calls"]
        ),
        scan["key_attribute_calls"],
    )

    # ---- 运行时矩阵 -------------------------------------------------------- #
    name_target = synth.target("item", "item|storea|itema", {"store": "StoreA", "item": "ItemA"})
    same_row = synth.record()
    id_row = synth.record(entity_key="item|id:P01", entity_filters={"store": "StoreA", "item": "ItemA"})
    id_row_no_roles = synth.record(entity_key="item|id:P01", entity_filters={})
    other_row = synth.record(entity_key="item|storeb|itemb", entity_filters={"store": "StoreB", "item": "ItemB"})
    opaque_row = synth.record(entity_key="item|whatever", entity_filters={"store": "StoreA", "item": "ItemA"})
    prefix_row = synth.record(entity_key="item|storea|itema|x", entity_filters={"store": "StoreC", "item": "ItemC"})
    contradictory_row = synth.record(
        entity_key="item|storeb|itemb", entity_filters={"store": "StoreA", "item": "ItemA"}
    )
    record_target = synth.target("record", "record|w01", {"identifier": "W01"})
    record_row = synth.record(
        entity_type="record", entity_key="record|w01", entity_filters={"identifier": "W01"},
        entity_code="entity_identity_matchable",
    )
    record_row_item_id = synth.record(
        entity_type="record", entity_key="record|w01", entity_filters={"item_id": "W01"},
        entity_code="entity_identity_matchable",
    )
    product_target = synth.target("product", "product|奶茶|nka|none", {"product": "奶茶", "channel": "NKA"})
    nonrole_target = synth.target(
        "item", "item|storea|itema", {"store": "StoreA", "item": "ItemA", "item_id": "P01"}
    )

    matrix: dict[str, Any] = {}
    matrix["same_name_key"] = outcome(axis_with([name_target]), [same_row])
    matrix["id_key_with_role_filters"] = outcome(axis_with([name_target]), [id_row])
    matrix["id_key_without_role_filters"] = outcome(axis_with([name_target]), [id_row_no_roles])
    matrix["name_key_vs_other_entity"] = outcome(axis_with([name_target]), [other_row])
    matrix["opaque_key"] = outcome(axis_with([name_target]), [opaque_row])
    matrix["contradictory_key_vs_filters"] = outcome(axis_with([name_target]), [contradictory_row])
    matrix["prefix_lookalike_key"] = outcome(axis_with([name_target]), [prefix_row])
    matrix["record_target_identifier"] = outcome(axis_with([record_target]), [record_row])
    matrix["record_target_vs_item_id_filters"] = outcome(axis_with([record_target]), [record_row_item_id])
    matrix["product_target_is_unmatchable"] = outcome(axis_with([product_target]), [record_row])
    matrix["nonrole_filter_target_is_unmatchable"] = outcome(axis_with([nonrole_target]), [same_row])

    expected = {
        "same_name_key": ("passed", "cross_entity_targets_match_ok"),
        "id_key_with_role_filters": ("passed", "cross_entity_targets_match_ok"),
        "id_key_without_role_filters": ("unknown", "entity_key_space_incompatible"),
        "name_key_vs_other_entity": ("violation", "other_entity_used"),
        "opaque_key": ("passed", "cross_entity_targets_match_ok"),
        "contradictory_key_vs_filters": ("passed", "cross_entity_targets_match_ok"),
        "prefix_lookalike_key": ("unknown", "entity_key_space_incompatible"),
        "record_target_identifier": ("passed", "cross_entity_targets_match_ok"),
        "record_target_vs_item_id_filters": ("unknown", "identity_unresolved"),
        "product_target_is_unmatchable": ("unknown", "targets_unresolved"),
        "nonrole_filter_target_is_unmatchable": ("unknown", "targets_unresolved"),
    }
    for name, (state, reason) in expected.items():
        row = matrix[name]
        checks.eq(f"matrix_{name}_state", row["state"], state, row)
        checks.eq(f"matrix_{name}_reason", row["reason"], reason, row)

    checks.record(
        "id_key_aligned_by_role_filters_is_audited",
        any("key_space_aligned_by_role_filters" in item for item in matrix["id_key_with_role_filters"]["evidence"]),
        matrix["id_key_with_role_filters"]["evidence"],
    )
    checks.eq(
        "prefix_lookalike_never_matches",
        matrix["prefix_lookalike_key"]["state"],
        "unknown",
    )
    checks.eq(
        "opaque_key_row_is_aligned_by_role_filters",
        any(
            "key_space_aligned_by_role_filters" in item
            for item in matrix["opaque_key"]["evidence"]
        ),
        True,
        matrix["opaque_key"]["evidence"],
    )
    checks.record(
        "contradictory_row_key_vs_filters_still_passes",
        matrix["contradictory_key_vs_filters"]["state"] == "passed"
        and matrix["contradictory_key_vs_filters"]["row_space"] == {"opaque": 1},
        {
            "note": "运行期 entity_key 指向 StoreB/ItemB，filters 却是 StoreA/ItemA；规则② 按 filters 复算即判 pass",
            "row": matrix["contradictory_key_vs_filters"],
        },
    )

    # ---- 确定性：同一输入连跑 3 次 ----------------------------------------- #
    repeats = {name: [outcome(axis_with([name_target]), [row]) for _ in range(3)] for name, row in {
        "same": same_row, "id": id_row, "opaque": opaque_row, "other": other_row,
    }.items()}
    stable = all(
        len({(item["state"], item["reason"]) for item in runs}) == 1
        for runs in repeats.values()
    )
    checks.record("repeated_runs_are_identical", stable, {name: [(r["state"], r["reason"]) for r in runs] for name, runs in repeats.items()})

    # ---- 顺序依赖：同一键两条 target，顺序不同结果不同 ---------------------- #
    strict_same_key = synth.target("item", "item|storeb|itemb", {"store": "StoreC"})
    loose_same_key = synth.target("item", "item|storeb|itemb", {})
    forward = outcome(axis_with([strict_same_key, loose_same_key]), [other_row])
    backward = outcome(axis_with([loose_same_key, strict_same_key]), [other_row])
    checks.eq("order_forward_state", forward["state"], "unknown", forward)
    checks.eq("order_forward_reason", forward["reason"], "identity_unresolved")
    checks.eq("order_backward_state", backward["state"], "passed", backward)
    checks.record(
        "target_order_changes_outcome",
        (forward["state"], forward["reason"]) != (backward["state"], backward["reason"]),
        {"forward": [forward["state"], forward["reason"]], "backward": [backward["state"], backward["reason"]]},
    )

    # ---- 一条 id 型 target 会把整轴 violation 降成 unknown ------------------ #
    with_id_target = outcome(axis_with([name_target, synth.target("item", "item|id:X")]), [other_row])
    checks.eq("id_target_present_state", with_id_target["state"], "unknown", with_id_target)
    checks.eq("id_target_present_reason", with_id_target["reason"], "entity_key_space_incompatible")

    # ---- R-ENT-1 复算保真：与合同规则源 chunking._entity 逐例对照 ----------- #
    combos = [
        {"门店": "StoreA", "物品": "ItemA"},
        {"门店": "StoreA"},
        {"编号": "W01"},
        {"品名": "奶茶"},
        {"品名": "奶茶", "渠道": "NKA"},
        {"品名": "奶茶", "渠道": "NKA", "价格类型": "零售价"},
        {"门店": "StoreA", "物品": "ItemA", "编号": "W01"},
        {"品名": "奶茶", "门店": "StoreA", "物品": "ItemA"},
        {"门店": " 城北店 ", "物品": "折叠凳（蓝）"},
        {},
    ]
    fidelity: list[dict[str, Any]] = []
    for fields in combos:
        entity_type, key, _label, filters, _norm = chunking_entity(fields, doc=DOC)
        canonical = adapter._canonical_entity_key(entity_type, filters)
        fidelity.append(
            {
                "fields": fields,
                "entity_type": entity_type,
                "contract_key": key,
                "adapter_canonical": canonical,
                "equal": canonical == key if entity_type != "document" else None,
            }
        )
    checks.eq(
        "canonical_recomputation_matches_rent1_for_all_non_document_branches",
        [row for row in fidelity if row["entity_type"] != "document" and row["equal"] is not True],
        [],
    )
    checks.eq(
        "document_branch_is_not_recomputed_by_design",
        [row["adapter_canonical"] for row in fidelity if row["entity_type"] == "document"],
        [None],
    )

    # 归一化偶合：大小写/空白/全角是否按合同规则源一致
    norm_rows = []
    for raw in ("StoreA", " storea ", "ＳｔｏｒｅＡ", "城北店", "折叠凳（蓝）"):
        entity_type, key, _l, filters, _n = chunking_entity({"门店": raw, "物品": "ItemA"}, doc=DOC)
        norm_rows.append(
            {
                "raw": raw,
                "contract_key": key,
                "adapter_key": adapter._canonical_entity_key(entity_type, filters),
                "equal": adapter._canonical_entity_key(entity_type, filters) == key,
            }
        )
    checks.eq("normalization_matches_rule_source", [row for row in norm_rows if not row["equal"]], [])

    return checks.write(
        {
            "static_scan": scan,
            "matrix": matrix,
            "order_dependence": {"forward": forward, "backward": backward},
            "rent1_fidelity": fidelity,
            "normalization": norm_rows,
        }
    )


if __name__ == "__main__":
    main()

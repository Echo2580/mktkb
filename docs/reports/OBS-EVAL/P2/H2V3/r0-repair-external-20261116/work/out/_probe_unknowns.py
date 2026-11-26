"""残余 unknown 结构探针（只读）：只输出固定码/枚举/布尔/整数/序号引用。

回答：
1. C02/C21/C27 的 cross_entity `entity_identity_unresolved`：命中哪条 audit、ref 是 units[N]
   还是 facts[N]、该 unit 的 layers（固定枚举）、entity_type / entity_key 哪个为空、投影行里
   doc_code / record_code / document_name / version_number / unit_key / raw_fields 是否具备。
2. C16 的 `empty_set_not_proven`：`_empty_use_scope_proof` 首个失败行号 + 触发它的
   (kind, field, rule)，只给字段名/规则名/长度/整数，不给值。
3. 两轴的 audit 码全集（code + 序号引用）。

纪律：不输出 unit_id、题面、文本、实体名、来源内容、私有路径。
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
TARGET = HERE.parent / "recompute_axes_fullverify_v2.py"
TARGET_CASES = ("H2V3-C02", "H2V3-C16", "H2V3-C21", "H2V3-C27")
ROW_FIELDS = (
    "document_name",
    "version_number",
    "unit_key",
    "raw_fields",
    "locator",
    "entity_filters",
    "doc_code",
    "record_code",
)
UNITVIEW_FIELDS = ("doc_code", "record_code", "document_name", "version_number", "unit_key")
REF_RE = re.compile(r"^(?P<kind>units|facts)\[(?P<index>[0-9]+)\]")
PRIMITIVE = "_empty_use_scope_proof"


def _usage_walk(hard, evidence):  # noqa: ANN001
    """复刻 `_empty_use_scope_proof` 的使用字段矩阵段：只报字段名/规则/长度/整数。"""
    rows = []
    for event in hard._events(evidence):
        kind = str(event.get("kind") or "")
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        for field, rule in hard.EMPTY_SCOPE_USAGE_FIELDS.get(kind, ()):
            present = field in payload
            value = payload.get(field)
            length = len(value) if isinstance(value, (list, tuple)) else None
            number = value if type(value) is int else None
            violates = bool(
                present
                and (
                    (rule == "list_empty" and isinstance(value, (list, tuple)) and bool(value))
                    or (rule == "zero_int" and type(value) is int and value != 0)
                )
            )
            rows.append(
                {
                    "kind": kind,
                    "field": field,
                    "rule": rule,
                    "present": bool(present),
                    "list_len": length,
                    "int_value": number,
                    "violates_empty": violates,
                }
            )
    return rows


def _first_failure_line(hard, evidence, compat):  # noqa: ANN001
    """用 settrace 记 `_empty_use_scope_proof` 内最后命中行号（= 返回分支标识）。"""
    state = {"in_func": False, "last": None}

    def _tracer(frame, event, _arg):  # noqa: ANN001
        if frame.f_code.co_name != PRIMITIVE:
            return None
        if event == "call":
            state["in_func"] = True
            return _tracer
        if event == "line" and state["in_func"]:
            state["last"] = frame.f_lineno
        return _tracer

    original = getattr(hard, PRIMITIVE)
    sys.settrace(_tracer)
    try:
        proof = original(evidence, compat=compat)
    finally:
        sys.settrace(None)
    return state["last"], bool(proof[0]), str(proof[1])


def main() -> int:
    spec = importlib.util.spec_from_file_location("_probe_unknowns_mod", TARGET)
    module = importlib.util.module_from_spec(spec)
    sys.modules["_probe_unknowns_mod"] = module
    spec.loader.exec_module(module)

    hard = module.hard
    entry_mod = module.ENTRY
    base = module.base
    work = pathlib.Path(sys.argv[1])
    bindings = pathlib.Path(sys.argv[2])

    binding = module._binding_for(0, bindings)
    inputs = {name: {"path": record["path"]} for name, record in binding["inputs"].items()}
    bundle = entry_mod.load_v3_bundle(inputs)
    run_entry = binding["runs"][0]
    cases = tuple(bundle.contract.subset(str(run_entry["scenario_id"])).cases)
    run_dir = module._resolve_run_dir(work, 0)
    case_plan = json.loads(
        (run_dir / "out" / "controlled" / "case-plan.json").read_text(encoding="utf-8")
    )
    static_bindings = {
        name: value
        for name, value in dict(run_entry["evidence_bindings"]).items()
        if name != "index_revision"
    }
    plan = entry_mod.v2._load_plan_for_run(binding, run_entry)
    plan_doc = entry_mod.v2._validate_case_plan_document(
        case_plan, cases=cases, static_bindings=static_bindings
    )
    root = run_dir / "evidence" / str(run_entry["run_id"])
    receipt = json.loads(
        (run_dir / "seal" / str(run_entry["run_id"]) / "run-receipt.json").read_text(
            encoding="utf-8"
        )
    )
    results, _card, audits, _calls = module.current_round_results(
        document=binding,
        run_entry=run_entry,
        plan=plan,
        cases=cases,
        annotation=bundle.annotation,
        case_plan_payload=case_plan,
        evidence_dir=root,
        key=module.KEY_PATH.read_bytes().strip(),
        receipt=receipt,
        compat=hard.REFUSAL_COMPAT_V0_3,
    )
    cards = {str(item.case_id): module.S.build_current_card(item) for item in results}
    audits_by_id = {str(case.case_id): audit for case, audit in zip(cases, audits)}
    vs = base.load_version_sources()
    base.CURRENT_VS = vs
    bindings_payload = base.contract_bindings(plan_doc)

    out = []
    for case in cases:
        case_id = str(case.case_id)
        if case_id not in TARGET_CASES:
            continue
        annotation_map, _ = hard.annotation_for_case(bundle.annotation, case)
        refs = base.all_refs(case)
        version_bindings = base.version_bindings_for(refs, vs)
        audit = audits_by_id[case_id]
        turns, _ = base.build_safety_turns(audit)
        envelopes = [
            entry["evidence"]
            for entry in audit["turns"]
            if str(entry["status"]) == "executed" and entry.get("evidence") is not None
        ]
        merged_units = base.merge_units([turn.units for turn in turns if turn.status == "executed"])
        annotations = {
            axis: base.make_annotation(axis, annotation_map[axis]) for axis in base.RESCORED_AXES
        }
        counters: dict[str, int] = {}
        entity_view, stale_view, _proof = module._build_scope_views(
            envelopes=envelopes,
            units=merged_units,
            vs=vs,
            compat=hard.REFUSAL_COMPAT_V0_3,
            counters=counters,
            with_control=False,
        )
        first_envelope = envelopes[0] if envelopes else None
        cross_user_view = (
            base.build_cross_user(first_envelope, merged_units)
            if first_envelope is not None
            else module.rescore_axes.CrossUserEvidenceView(projection_available=False)
        )
        views = base.build_axes_view(
            old=cards[case_id],
            annotations=annotations,
            cross_user=cross_user_view,
            cross_entity=entity_view,
            stale_source=stale_view,
            refs=refs,
            version_bindings=version_bindings,
            bindings=bindings_payload,
            cross_entity_mode=base.mode_for(annotations["cross_entity"]),
            targets=annotations["cross_entity"].targets,
            case_id=case_id,
        )
        result = module.rescore_axes.rescore_axes_case(views, allow_synthetic_fixture=False)

        projection_rows: dict[str, dict] = {}
        for envelope in envelopes:
            projection_rows.update(hard._units_by_id(hard._projection(envelope)))

        entry: dict[str, object] = {
            "case_id": case_id,
            "new_axes": {
                axis: {
                    "state": str(result.new_axes[axis]["state"]),
                    "reason": str(result.new_axes[axis]["reason"]),
                }
                for axis in base.RESCORED_AXES
            },
            "audit_codes": {
                axis: [[str(row.code), str(row.detail)] for row in result.axis_audit[axis]]
                for axis in ("cross_entity", "stale_source")
            },
            "units_total": len(entity_view.units),
            "facts_total": len(entity_view.facts),
            "unit_entity_entries": len(entity_view.unit_entity),
        }

        gaps = []
        for axis in ("cross_entity", "stale_source"):
            for row in result.axis_audit[axis]:
                if str(row.code) != "entity_identity_missing":
                    continue
                match = REF_RE.match(str(row.detail))
                gap: dict[str, object] = {"axis": axis, "ref_kind": None, "ref_index": None}
                if match is None:
                    gaps.append(gap)
                    continue
                index = int(match.group("index"))
                gap["ref_kind"] = match.group("kind")
                gap["ref_index"] = index
                if match.group("kind") == "units":
                    unit = entity_view.units[index]
                    identity = entity_view.unit_entity.get(unit.unit_id)
                    gap["layers"] = [str(layer) for layer in unit.layers]
                    gap["identity_present"] = identity is not None
                    gap["entity_type_present"] = bool(
                        identity is not None and identity.entity_type
                    )
                    gap["entity_key_present"] = bool(identity is not None and identity.entity_key)
                    gap["unit_view_fields"] = {
                        name: bool(getattr(unit, name)) for name in UNITVIEW_FIELDS
                    }
                    row_payload = projection_rows.get(unit.unit_id)
                    gap["projection_row_found"] = row_payload is not None
                    if row_payload is not None:
                        gap["projection_row_fields"] = {
                            name: name in row_payload and row_payload.get(name) not in (None, "", {})
                            for name in ROW_FIELDS
                        }
                        gap["projection_entity_filters_len"] = len(
                            row_payload.get("entity_filters") or {}
                        )
                        gap["projection_locator_len"] = len(row_payload.get("locator") or {})
                else:
                    fact = entity_view.facts[index]
                    gap["fact_entity_key_present"] = bool(fact.entity_key)
                    gap["fact_source_unit_present"] = bool(fact.source_unit_id)
                    source = next(
                        (u for u in entity_view.units if u.unit_id == fact.source_unit_id), None
                    )
                    gap["fact_source_unit_in_units"] = source is not None
                    if source is not None:
                        identity = entity_view.unit_entity.get(source.unit_id)
                        gap["source_identity_present"] = identity is not None
                        gap["source_entity_type_present"] = bool(
                            identity is not None and identity.entity_type
                        )
                        gap["source_entity_key_present"] = bool(
                            identity is not None and identity.entity_key
                        )
                        # 只做相等判断，不输出任何一侧的值。
                        gap["eq_identity_entity_key"] = bool(
                            identity is not None and identity.entity_key == fact.entity_key
                        )
                        gap["eq_unit_key"] = bool(source.unit_key == fact.entity_key)
                        gap["eq_record_code"] = bool(source.record_code == fact.entity_key)
                        gap["eq_doc_code"] = bool(source.doc_code == fact.entity_key)
                        gap["eq_document_name"] = bool(source.document_name == fact.entity_key)
                        gap["eq_unit_id"] = bool(source.unit_id == fact.entity_key)
                        pipe = "|"
                        gap["fact_has_pipe"] = pipe in str(fact.entity_key or "")
                        gap["source_entity_key_has_pipe"] = pipe in str(
                            identity.entity_key if identity is not None else ""
                        )
                        # 只报「形状」：id 形态（`|id:` 片段，判据见 retrieval/service.py:270-273）
                        # 与首段类型前缀是否相同；不输出任何一侧的值。
                        fact_key = str(fact.entity_key or "")
                        source_key = str(identity.entity_key or "") if identity else ""
                        gap["fact_id_form"] = "|id:" in fact_key
                        gap["source_id_form"] = "|id:" in source_key
                        gap["same_type_prefix"] = (
                            fact_key.split(pipe, 1)[0] == source_key.split(pipe, 1)[0]
                            if pipe in fact_key and pipe in source_key
                            else None
                        )
                        targets = annotations["cross_entity"].targets
                        gap["fact_matches_targets"] = any(
                            str(getattr(target, "entity_key", "")) == fact_key
                            and str(getattr(target, "entity_type", ""))
                            == str(identity.entity_type if identity else "")
                            for target in targets
                        )
                        gap["targets_total"] = len(targets)
                        gap["source_layers"] = [str(layer) for layer in source.layers]
                gaps.append(gap)
        entry["identity_gaps"] = gaps

        if case_id == "H2V3-C16":
            usage = []
            for position, envelope in enumerate(envelopes):
                line, ok, reason = _first_failure_line(
                    hard, envelope, hard.REFUSAL_COMPAT_V0_3
                )
                usage.append(
                    {
                        "envelope_index": position,
                        "fields": _usage_walk(hard, envelope),
                        "tracer": {
                            "last_line": line,
                            "ok": ok,
                            "reason": reason,
                        },
                    }
                )
            entry["empty_scope"] = {
                "builder_reason": entity_view.empty_scope_reason,
                "builder_proven": entity_view.empty_scope_proven,
                "stale_builder_reason": stale_view.empty_scope_reason,
                "stale_builder_proven": stale_view.empty_scope_proven,
                "envelopes": usage,
            }
        out.append(entry)

    print(json.dumps(out, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

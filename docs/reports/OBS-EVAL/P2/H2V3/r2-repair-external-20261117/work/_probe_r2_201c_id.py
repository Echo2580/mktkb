"""201C 身份形态探针（第 2 号）：只导**形态**（长度/段数/段内标签/相等布尔），绝不导实体值。

要回答的是任务书 §3 的可判定项：``entity_key`` 的段结构到底是 ``<类型>|id:<...>`` 还是
``<类型>|doc:<...>``，以及 fact 行是否带 ``entity_key`` / ``source_unit_id``。因此本探针
只输出：长度、``|`` 前段长度、段标签是否 ``id`` / ``doc`` / 其它、以及配对后的相等与差异段角色。
"""
from __future__ import annotations

import collections
import json
import pathlib
import sys
from typing import Any, Mapping

_WORK = pathlib.Path(__file__).resolve().parent
if str(_WORK) not in sys.path:
    sys.path.insert(0, str(_WORK))

import r2_safe_project as base  # noqa: E402

KEY = pathlib.Path(r"D:\mktkb-p2-h2v3-20261115\runs3\ev.key")
BINDING = pathlib.Path(
    r"D:\mktkb-p2-h2v3-20261115\custody-plan-20261116-single-01\bindings"
    r"\run2-pre_v05_without_v07.binding.json"
)
EVIDENCE_ROOT = pathlib.Path(
    r"D:\mktkb-p2-h2v3-fullverify-20261116\r2\evidence\p2-h2v3-20261115-r2-pre_v05_without_v07"
)
CASE_PLAN = (
    base.REPO
    / "docs/reports/OBS-EVAL/P2/H2V3/fullverify-20261116/run/r2-final/case-plan.json"
)
OUT = _WORK / "out" / "probe-201c-id.txt"

ID_TAGS = ("id", "doc", "v", "ver", "u", "chunk", "unit")


def shape(text: Any) -> str:
    """把 entity_key 归到固定形态码：type+id / type+doc / type+other / no_pipe / not_str。"""
    if not isinstance(text, str):
        return "not_str"
    if "|" not in text:
        return "no_pipe"
    head, _, tail = text.partition("|")
    tag, sep, _rest = tail.partition(":")
    if not sep:
        return "type_only_tail"
    if tag == "id":
        return "type_id"
    if tag == "doc":
        return "type_doc"
    return "type_other"


def seg(text: Any) -> tuple[str, str]:
    if not isinstance(text, str):
        return ("none", "none")
    head, sep, tail = text.partition("|")
    if not sep:
        return (f"head_len={len(head)}", "no_tail")
    tag, sep2, _ = tail.partition(":")
    return (f"head_len={len(head)}", f"tag={tag}" if sep2 else "tail_no_tag")


def main() -> int:
    guard = base.NetGuard()
    guard.install()
    guard.positive_control()
    lines: list[str] = []
    key = KEY.read_bytes().strip()
    binding = base._read_json(BINDING)
    case_plan = base._read_json(CASE_PLAN)
    run_entry = binding["runs"][0]
    entry = base._load_module(
        "p2_h2_v3_controlled_execute_probeid",
        base.TOOLS / "p2_h2_v3_controlled_execute.py",
    )
    from mktkb.evaluation.p2_evidence_io import read_encrypted_evidence  # noqa: PLC0415
    import mktkb.evaluation.p2_scoring as scoring  # noqa: PLC0415
    import mktkb.evaluation.p2_score_run as score_run  # noqa: PLC0415
    import mktkb.evaluation.p2_runner as runner  # noqa: PLC0415

    inputs = {name: {"path": record["path"]} for name, record in binding["inputs"].items()}
    bundle = entry.load_v3_bundle(inputs)
    cases = tuple(bundle.contract.subset(str(run_entry.get("scenario_id"))).cases)
    document_codes = runner.holdout_document_codes(bundle.contract._ingest)  # noqa: SLF001
    static_bindings = {
        str(name): value
        for name, value in dict(run_entry.get("evidence_bindings") or {}).items()
        if str(name) != "index_revision"
    }
    plan = entry.v2._validate_case_plan_document(
        dict(case_plan), cases=cases, static_bindings=static_bindings
    )
    rows, envelopes_by_case = base._build_rows(
        cases,
        plan["cases"],
        EVIDENCE_ROOT,
        key,
        plan["bindings"],
        document_codes,
        read_encrypted_evidence,
        scoring._lookup_document_code,  # noqa: SLF001
        collections.defaultdict(int),
    )
    source_map = score_run.load_holdout_source_map()

    for case in cases:
        case_id = str(case.case_id)
        lines.append("=" * 70)
        lines.append(f"CASE {case_id}")
        mapped = score_run.remap_holdout_case(case, source_map)
        refs = list(getattr(mapped, "expected_sources", ()) or ())
        for index, ref in enumerate(refs):
            ref_map = dict(ref)
            rec = ref_map.get("record_code")
            lines.append(
                f"  ref[{index}] doc_code={base.CODE_RE.fullmatch(str(ref_map.get('doc_code'))) is not None}"
                f" record_code_len={len(rec) if isinstance(rec, str) else 'na'}"
                f" locator={ {k: ('int' if isinstance(v, int) else 'str') for k, v in dict(ref_map.get('locator') or {}).items()} }"
            )
        for turn_index, envelope in enumerate(envelopes_by_case.get(case_id) or ()):
            events = [
                item
                for item in ((envelope.get("capture") or {}).get("events") or ())
                if isinstance(item, Mapping)
            ]
            projection = envelope.get("db_projection") or {}
            units = [u for u in (projection.get("units") or ()) if isinstance(u, Mapping)]
            lines.append(f"  -- turn[{turn_index}] units={len(units)}")
            for index, unit in enumerate(units):
                lines.append(
                    f"     units[{index}]: entity_type={unit.get('entity_type')}"
                    f" entity_key_shape={shape(unit.get('entity_key'))}"
                    f" entity_key_seg={seg(unit.get('entity_key'))}"
                    f" entity_filters_keys={sorted(dict(unit.get('entity_filters') or {}))}"
                    f" version_state={unit.get('version_state')} active={unit.get('active')}"
                    f" deleted={unit.get('document_deleted')} kind={unit.get('kind')}"
                    f" loc_row={unit.get('locator', {}).get('row') if isinstance(unit.get('locator'), Mapping) else 'na'}"
                    f" unit_key_len={len(unit.get('unit_key')) if isinstance(unit.get('unit_key'), str) else 'na'}"
                )
            for payload in _payloads(events, "direct_rag_answer"):
                facts = [f for f in (payload.get("facts") or ()) if isinstance(f, Mapping)]
                lines.append(f"     direct_rag.facts={len(facts)} cited={len(payload.get('cited_unit_ids') or ())}")
                for index, fact in enumerate(facts):
                    lines.append(f"       facts[{index}].keys={sorted(fact)}")
                    lines.append(
                        f"         entity_type={fact.get('entity_type')}"
                        f" entity_key_shape={shape(fact.get('entity_key'))}"
                        f" entity_key_seg={seg(fact.get('entity_key'))}"
                        f" has_source_unit_id={isinstance(fact.get('source_unit_id'), str)}"
                        f" source_unit_id_resolves={any(str(u.get('unit_id')) == str(fact.get('source_unit_id')) for u in units)}"
                        f" field_role={fact.get('field_role') if base.CODE_RE.fullmatch(str(fact.get('field_role'))) else 'noncode'}"
                        f" value_len={len(fact.get('value')) if isinstance(fact.get('value'), str) else 'na'}"
                    )
                    hit = next(
                        (u for u in units if str(u.get("unit_id")) == str(fact.get("source_unit_id"))),
                        None,
                    )
                    if isinstance(hit, Mapping):
                        lines.append(
                            f"         fact_key_eq_unit_key={fact.get('entity_key') == hit.get('entity_key')}"
                            f" fact_type_eq_unit_type={fact.get('entity_type') == hit.get('entity_type')}"
                            f" fact_key_seg={seg(fact.get('entity_key'))}"
                            f" unit_key_seg={seg(hit.get('entity_key'))}"
                        )
            for payload in _payloads(events, "entity_inheritance"):
                lines.append(
                    f"     entity_inheritance: entity_type={payload.get('entity_type')}"
                    f" entity_key_shape={shape(payload.get('entity_key'))}"
                    f" source={base.CODE_RE.fullmatch(str(payload.get('source'))) is not None}"
                )
            for payload in _payloads(events, "retrieval_observed"):
                lines.append(
                    f"     retrieval: scope={payload.get('scope')} candidate={payload.get('candidate')}"
                    f" empty={payload.get('empty')} truncated={payload.get('truncated')}"
                    f" ids={len(payload.get('unit_ids') or ())}"
                )
            plan_payloads = _payloads(events, "plan_observed")
            for payload in plan_payloads:
                lines.append(
                    f"     plan: path={payload.get('path')} mode={payload.get('mode')}"
                    f" enumerate={payload.get('enumerate')} include_future={payload.get('include_future')}"
                    f" as_of_len={len(payload.get('as_of')) if isinstance(payload.get('as_of'), str) else 'na'}"
                    f" state_as_of_len={len(payload.get('state_as_of')) if isinstance(payload.get('state_as_of'), str) else 'na'}"
                    f" filters_keys={sorted(dict(payload.get('filters') or {}))}"
                    f" statelast={payload.get('state_last_kind')} pending={payload.get('state_pending_slot')}"
                )
            for payload in _payloads(events, "model_input"):
                lines.append(
                    f"     model_input: evidence={len(payload.get('evidence') or ())}"
                    f" ctx_q={len(payload.get('context_questions') or ())}"
                    f" ctx_e_keys={sorted(dict(payload.get('context_entities') or {}))}"
                )
        lines.append(f"  rag_business_date_present={isinstance((envelopes_by_case.get(case_id) or [{}])[-1].get('db_projection', {}).get('rag_business_date'), str)}")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {OUT} lines={len(lines)}")
    return 0


def _payloads(events: Any, kind: str) -> list[Mapping[str, Any]]:
    out = []
    for event in events:
        if not isinstance(event, Mapping) or str(event.get("kind")) != kind:
            continue
        payload = event.get("payload")
        if isinstance(payload, Mapping):
            out.append(payload)
    return out


if __name__ == "__main__":
    raise SystemExit(main())

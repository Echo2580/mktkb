"""201C 意图探针（第 6 号）：问题文本里**有没有**提到每个 target 的实体值。

这是区分「产品意图层丢实体（层 1 缺陷）」与「标注超出问题范围（契约伪影）」的唯一判据。
只在进程内存里读问题文本，只输出布尔/计数：绝不打问题、绝不打实体值。
"""
from __future__ import annotations

import collections
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
OUT = _WORK / "out" / "probe-201c-intent.txt"


def value_of(entity_key: str) -> str:
    text = str(entity_key or "")
    if "id:" in text:
        return text.split("id:", 1)[1]
    if "|" in text:
        return text.split("|", 1)[1]
    return text


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
        "p2_h2_v3_controlled_execute_probeintent",
        base.TOOLS / "p2_h2_v3_controlled_execute.py",
    )
    from mktkb.evaluation.p2_evidence_io import read_encrypted_evidence  # noqa: PLC0415
    import mktkb.evaluation.p2_scoring as scoring  # noqa: PLC0415
    import mktkb.evaluation.p2_score_run as score_run  # noqa: PLC0415
    import mktkb.evaluation.p2_runner as runner  # noqa: PLC0415
    import mktkb.evaluation.scorers as scorers_mod  # noqa: PLC0415

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
    annotations = {
        str(row.get("case_id")): row
        for row in (bundle.annotation.payload.get("cases") or ())
        if isinstance(row, Mapping)
    }

    for case in cases:
        case_id = str(case.case_id)
        envelopes = envelopes_by_case.get(case_id) or ()
        anno = annotations.get(case_id) or {}
        axes = anno.get("axes") or {}
        cross = axes.get("cross_entity") or {}
        targets = [t for t in (cross.get("targets") or ()) if isinstance(t, Mapping)]
        lines.append("=" * 68)
        lines.append(f"CASE {case_id} turns={len(envelopes)} targets={len(targets)}")
        for turn_index, envelope in enumerate(envelopes):
            projection = envelope.get("db_projection") or {}
            messages = [m for m in (projection.get("messages") or ()) if isinstance(m, Mapping)]
            user_rows = [
                m
                for m in messages
                if str(m.get("role")) == "user" and isinstance(m.get("text"), str)
            ]
            # 最后一轮 = 本轮问题；seq 最大的 user 行
            question = user_rows[-1]["text"] if user_rows else ""
            q_norm = scorers_mod.normalize_text(question) if question else ""
            events = [
                e
                for e in ((envelope.get("capture") or {}).get("events") or ())
                if isinstance(e, Mapping)
            ]
            plan_payload = {}
            for e in events:
                if str(e.get("kind")) == "plan_observed" and isinstance(e.get("payload"), Mapping):
                    plan_payload = e["payload"]
            plan_filter_keys = sorted(dict(plan_payload.get("filters") or {}))
            lines.append(
                f"  turn[{turn_index}] question_present={bool(question)}"
                f" question_chars={len(question)}"
                f" user_messages={len(user_rows)}"
                f" plan_filter_keys={plan_filter_keys}"
            )
            for t_index, target in enumerate(targets):
                raw_key = str(target.get("entity_key") or "")
                value = value_of(raw_key)
                value_norm = scorers_mod.normalize_text(value)
                filters = dict(target.get("filters") or {})
                filter_values = [str(v) for v in filters.values() if isinstance(v, str)]
                lines.append(
                    f"    target[{t_index}] entity_type={target.get('entity_type')}"
                    f" key_len={len(raw_key)} value_len={len(value)}"
                    f" value_in_question={bool(value_norm) and value_norm in q_norm}"
                    f" any_filter_value_in_question="
                    f"{any(scorers_mod.normalize_text(v) in q_norm for v in filter_values if v)}"
                    f" filter_count={len(filters)}"
                    f" filter_keys_in_plan="
                    f"{sum(1 for k in filters if str(k) in plan_filter_keys)}"
                )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {OUT} lines={len(lines)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

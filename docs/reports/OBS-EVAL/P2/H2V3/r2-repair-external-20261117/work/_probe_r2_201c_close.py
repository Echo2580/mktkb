"""201C 收口探针（第 9 号）：C29 store target 在 问题/plan terms/答案 三处的精确落点。

逐 probe 输出 4 个布尔（question_token / terms_token / answer_token / is_fabricated=answer 有而
question 与 unit 都无），以及命中的模板标记**序号**（固定码，不回显文本）。
"""
from __future__ import annotations

import collections
import pathlib
import re
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
OUT = _WORK / "out" / "probe-201c-close.txt"

MARKERS = (
    "资料中未找到",
    "资料中未记录",
    "资料中未收录",
    "未在资料中找到",
    "不能据此判断",
    "不能据此编造",
)
TOKEN_SPLIT = re.compile(r"[^0-9A-Za-z\u4e00-\u9fff]+")


def value_of(entity_key: str) -> str:
    text = str(entity_key or "")
    if "id:" in text:
        return text.split("id:", 1)[1]
    if "|" in text:
        return text.split("|", 1)[1]
    return text


def tokens(text: str) -> set[str]:
    return {item for item in TOKEN_SPLIT.split(text) if item}


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
        "p2_h2_v3_controlled_execute_probeclose",
        base.TOOLS / "p2_h2_v3_controlled_execute.py",
    )
    from mktkb.evaluation.p2_evidence_io import read_encrypted_evidence  # noqa: PLC0415
    import mktkb.evaluation.p2_scoring as scoring  # noqa: PLC0415
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
        if case_id != "H2V3-C29":
            continue
        envelopes = envelopes_by_case.get(case_id) or ()
        cross = (annotations.get(case_id) or {}).get("axes", {}).get("cross_entity") or {}
        targets = [t for t in (cross.get("targets") or ()) if isinstance(t, Mapping)]
        last = envelopes[-1] if envelopes else {}
        events = [
            e for e in ((last.get("capture") or {}).get("events") or ()) if isinstance(e, Mapping)
        ]
        projection = last.get("db_projection") or {}
        units = [u for u in (projection.get("units") or ()) if isinstance(u, Mapping)]
        messages = [m for m in (projection.get("messages") or ()) if isinstance(m, Mapping)]
        user_rows = [
            m for m in messages if str(m.get("role")) == "user" and isinstance(m.get("text"), str)
        ]
        question = user_rows[-1]["text"] if user_rows else ""
        answers = [
            e["payload"]
            for e in events
            if str(e.get("kind")) == "answer_result" and isinstance(e.get("payload"), Mapping)
        ]
        answer_text = answers[-1].get("text") if answers and isinstance(answers[-1].get("text"), str) else ""
        plan_payload: Mapping[str, Any] = {}
        for e in events:
            if str(e.get("kind")) == "plan_observed" and isinstance(e.get("payload"), Mapping):
                plan_payload = e["payload"]
        terms = [str(t) for t in (plan_payload.get("terms") or ()) if str(t)]
        q_norm = scorers_mod.normalize_text(question)
        q_tok = tokens(q_norm)
        term_norm = scorers_mod.normalize_text("\n".join(terms))
        term_tok = tokens(term_norm)
        ans_norm = scorers_mod.normalize_text(answer_text)
        ans_tok = tokens(ans_norm)
        unit_norm = scorers_mod.normalize_text("\n".join(str(u.get("text") or "") for u in units))
        unit_tok = tokens(unit_norm)
        marker_index = [i for i, m in enumerate(MARKERS) if m in ans_norm]
        lines.append(f"CASE {case_id}")
        lines.append(
            f"  question_chars={len(question)} terms={len(terms)}"
            f" answer_chars={len(answer_text)} marker_indices={marker_index}"
            f" plan_term_tokens={len(term_tok)} question_tokens={len(q_tok)}"
        )
        for t_index, target in enumerate(targets):
            filters = dict(target.get("filters") or {})
            keys = list(filters)
            probes = [(f"filter[{k}]", str(filters[k])) for k in keys if isinstance(filters[k], str)]
            probes.append(("entity_key_value", value_of(str(target.get("entity_key") or ""))))
            for label, probe in probes:
                p = scorers_mod.normalize_text(probe)
                if not p:
                    continue
                lines.append(
                    f"  target[{t_index}].{label} len={len(p)}"
                    f" in_question_token={p in q_tok}"
                    f" in_terms_token={p in term_tok}"
                    f" in_answer_token={p in ans_tok}"
                    f" in_unit_token={p in unit_tok}"
                    f" unbacked_in_answer={p in ans_tok and p not in q_tok and p not in unit_tok}"
                )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {OUT} lines={len(lines)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

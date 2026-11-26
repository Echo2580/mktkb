"""201C 精确度探针（第 8 号）：收窄 C29 store target 的 ``in_answer_text`` 命中是否是短值假阳。

对每个 target 的每个 probe 值输出：长度、答案里的**有界词元**命中布尔、裸子串命中布尔、
出现次数；以及答案里"未在资料中找到/未记录"类模板标记的命中计数。
只输出布尔/整数。
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
OUT = _WORK / "out" / "probe-201c-precise.txt"

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
        "p2_h2_v3_controlled_execute_probeprecise",
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
        if case_id not in ("H2V3-C29", "H2V3-C25"):
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
        answers = [
            e["payload"]
            for e in events
            if str(e.get("kind")) == "answer_result" and isinstance(e.get("payload"), Mapping)
        ]
        answer_text = answers[-1].get("text") if answers and isinstance(answers[-1].get("text"), str) else ""
        ans_norm = scorers_mod.normalize_text(answer_text)
        ans_tokens = tokens(ans_norm)
        unit_norm = scorers_mod.normalize_text(
            "\n".join(str(u.get("text") or "") for u in units)
        )
        unit_tokens = tokens(unit_norm)
        marker_hits = sum(1 for m in MARKERS if m in ans_norm)
        lines.append("=" * 68)
        lines.append(
            f"CASE {case_id} answer_chars={len(answer_text)} "
            f"template_marker_hit_count={marker_hits} answer_tokens={len(ans_tokens)}"
        )
        for t_index, target in enumerate(targets):
            filters = dict(target.get("filters") or {})
            probes = [str(v) for v in filters.values() if isinstance(v, str)]
            probes.append(value_of(str(target.get("entity_key") or "")))
            for p_index, probe in enumerate(dict.fromkeys(p for p in probes if p)):
                probe_norm = scorers_mod.normalize_text(probe)
                lines.append(
                    f"  target[{t_index}].probe[{p_index}] len={len(probe_norm)}"
                    f" in_answer_substr={probe_norm in ans_norm}"
                    f" in_answer_token={probe_norm in ans_tokens}"
                    f" answer_occurrences={ans_norm.count(probe_norm)}"
                    f" in_unit_substr={probe_norm in unit_norm}"
                    f" in_unit_token={probe_norm in unit_tokens}"
                )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {OUT} lines={len(lines)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

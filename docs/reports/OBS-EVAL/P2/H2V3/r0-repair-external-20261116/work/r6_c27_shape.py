"""R0 第六轮 C27 形态判别探针：只出布尔 / 整数 / 角色码。

离线；只读私有输入。绝不打印问句、值、实体、答案正文。
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import sys

RUN_ROOT = pathlib.Path(r"D:\mktkb-p2-h2v3-r0fix6-20261116\r0")
BINDING = pathlib.Path(
    r"D:\mktkb-p2-h2v3-20261115\custody-plan-20261116-final5\bindings\run0-base_b0.binding.json"
)
KEY_PATH = pathlib.Path(r"D:\mktkb-p2-h2v3-20261115\runs3\ev.key")
ID = "p2-h2v3-20261115-r0-base_b0"
CASE = "H2V3-C27"
OUT = pathlib.Path(__file__).resolve().parent.parent / "evidence" / "12-c27" / "c27-shape.json"


def _repo_root() -> pathlib.Path:
    for parent in pathlib.Path(__file__).resolve().parents:
        if (parent / "backend" / "src" / "mktkb").is_dir():
            return parent
    raise SystemExit("repo_root_not_found")


REPO = _repo_root()
sys.path.insert(0, str(REPO / "backend" / "src"))
TOOLS = REPO / "tools"
sys.path.insert(0, str(TOOLS))

ADDRESS_MARKERS = ("路", "街", "号", "区", "市", "县", "镇", "村", "栋", "楼", "层", "室", "大道", "广场")
NAME_MARKERS = ("经理", "先生", "女士", "店长", "负责人", "联系人", "总", "主管")
SEPARATORS = ("：", ":", "（", "(", "）", ")", "/", "、", "，", ",", "；", ";")


def _fail(code: str) -> dict:
    return {"ok": False, "error": code, "case_id": CASE}


def _main() -> dict:
    binding = json.loads(BINDING.read_text(encoding="utf-8"))
    run_entry = json.loads((RUN_ROOT / "v3-entry-p2-h2v3-20261115-r0-base_b0.json").read_text(encoding="utf-8"))
    case_plan = json.loads((RUN_ROOT / "out" / "controlled" / "case-plan.json").read_text(encoding="utf-8"))
    key = KEY_PATH.read_bytes()
    spec = importlib.util.spec_from_file_location("p2h2v3_entry", TOOLS / "p2_h2_v3_controlled_execute.py")
    entry = importlib.util.module_from_spec(spec)
    sys.modules["p2h2v3_entry"] = entry
    spec.loader.exec_module(entry)
    inputs = {name: {"path": record["path"]} for name, record in binding["inputs"].items()}
    bundle = entry.load_v3_bundle(inputs)
    cases = tuple(bundle.contract.subset(str(run_entry.get("scenario_id"))).cases)
    case = next(item for item in cases if str(item.case_id) == CASE)

    from mktkb.evaluation.p2_evidence_io import read_encrypted_evidence
    from mktkb.evaluation.scorers import check_value
    from mktkb.rag.chunking import ROLE_LABELS, field_role
    from mktkb.rag.query import _norm

    question = str(case.question)
    ref = str(getattr(case, "reference_answer", "") or "")
    normalized_question = _norm(question)
    plan_row = next(item for item in case_plan["cases"] if str(item.get("case_id")) == CASE)
    env = read_encrypted_evidence(
        RUN_ROOT / "evidence" / ID / str(plan_row["turns"][-1]["evidence_file"]),
        key=key,
        expected_bindings=dict(case_plan["bindings"]),
    )
    units = {str(u.get("unit_id")): u for u in ((env.get("db_projection") or {}).get("units") or [])}
    events = (env.get("capture") or {}).get("events") or []
    dra = next((ev["payload"] for ev in events if ev.get("kind") == "direct_rag_answer"), {})
    ans = next((ev["payload"] for ev in events if ev.get("kind") == "answer_result"), {})
    cited = [units[str(uid)] for uid in (dra.get("cited_unit_ids") or ()) if str(uid) in units]
    unit = cited[0]
    cols = {}
    for name, raw in (unit.get("raw_fields") or {}).items():
        role = field_role(name) or ""
        cols.setdefault(role, []).append("" if raw is None else str(raw).strip())

    expected = [str(v) for v in (case.expected_values or ())]
    out_values = []
    for index, value in enumerate(expected):
        nv = _norm(value)
        where = []
        for role, values in cols.items():
            for cell_index, cell in enumerate(values):
                if cell and check_value(cell, value):
                    pos = _norm(cell).find(nv)
                    where.append({"role": role, "col_in_role": cell_index, "pos": pos, "cell_len": len(cell)})
        out_values.append(
            {
                "i": index,
                "value_len": len(value),
                "digits": sum(1 for ch in value if ch.isdigit()),
                "in_question": bool(nv) and nv in normalized_question,
                "in_reference_answer": bool(ref) and check_value(ref, value),
                "role_label_match": sorted(
                    role for role, label in ROLE_LABELS.items() if nv and nv in _norm(label)
                ),
                "columns": where,
            }
        )

    contact_cells = cols.get("contact") or []
    address_cells = cols.get("address") or []
    phone_cells = cols.get("phone") or []
    contact = contact_cells[0] if contact_cells else ""
    address = address_cells[0] if address_cells else ""
    phone = phone_cells[0] if phone_cells else ""

    return {
        "ok": True,
        "case_id": CASE,
        "question_len": len(question),
        "reference_len": len(ref),
        "values": out_values,
        "cells": {
            "contact": {
                "len": len(contact),
                "digits": sum(1 for ch in contact if ch.isdigit()),
                "separators": sum(1 for ch in contact if ch in SEPARATORS),
                "name_marker_hits": sum(1 for m in NAME_MARKERS if m in contact),
                "address_markers": sum(1 for m in ADDRESS_MARKERS if m in contact),
            },
            "address": {
                "len": len(address),
                "digits": sum(1 for ch in address if ch.isdigit()),
                "address_markers": sum(1 for m in ADDRESS_MARKERS if m in address),
                "name_marker_hits": sum(1 for m in NAME_MARKERS if m in address),
            },
            "phone": {
                "len": len(phone),
                "digits": sum(1 for ch in phone if ch.isdigit()),
            },
        },
        "ref_contains": {
            "contact_cell": bool(ref) and bool(contact) and check_value(ref, contact),
            "address_cell": bool(ref) and bool(address) and check_value(ref, address),
            "phone_cell": bool(ref) and bool(phone) and check_value(ref, phone),
        },
        "answer_text_contains": {
            "contact_cell": bool(ans.get("text")) and bool(contact) and check_value(str(ans.get("text")), contact),
            "address_cell": bool(ans.get("text")) and bool(address) and check_value(str(ans.get("text")), address),
            "phone_cell": bool(ans.get("text")) and bool(phone) and check_value(str(ans.get("text")), phone),
        },
    }


def main() -> int:
    try:
        result = _main()
    except Exception:
        result = _fail("probe_failed")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())

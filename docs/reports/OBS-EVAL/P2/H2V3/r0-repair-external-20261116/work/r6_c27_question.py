"""R0 第六轮 C27 问句词类探针：只出角色码 / 布尔 / 整数。

离线；只读私有输入。绝不打印问句、值、实体。
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
OUT = pathlib.Path(__file__).resolve().parent.parent / "evidence" / "12-c27" / "c27-question-roles.json"


def _repo_root() -> pathlib.Path:
    for parent in pathlib.Path(__file__).resolve().parents:
        if (parent / "backend" / "src" / "mktkb").is_dir():
            return parent
    raise SystemExit("repo_root_not_found")


REPO = _repo_root()
sys.path.insert(0, str(REPO / "backend" / "src"))
TOOLS = REPO / "tools"
sys.path.insert(0, str(TOOLS))


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
    from mktkb.rag.chunking import field_role
    from mktkb.rag.query import FIELD_WORDS, _match_field, _match_fields, _norm  # noqa: PLC0415

    question = str(case.question)
    normalized = _norm(question)
    first = _match_field(question)
    matched = [str(role) for role in (_match_fields(question) or ())]

    plan_row = next(item for item in case_plan["cases"] if str(item.get("case_id")) == CASE)
    env = read_encrypted_evidence(
        RUN_ROOT / "evidence" / ID / str(plan_row["turns"][-1]["evidence_file"]),
        key=key,
        expected_bindings=dict(case_plan["bindings"]),
    )
    units = {str(u.get("unit_id")): u for u in ((env.get("db_projection") or {}).get("units") or [])}
    events = (env.get("capture") or {}).get("events") or []
    dra = next((ev["payload"] for ev in events if ev.get("kind") == "direct_rag_answer"), {})
    cited = [units[str(uid)] for uid in (dra.get("cited_unit_ids") or ()) if str(uid) in units]
    rows = []
    for unit in cited:
        raw_fields = unit.get("raw_fields") or {}
        rows.append(
            [
                {
                    "role": field_role(name) or "",
                    "name": str(name),
                    "value": "" if raw is None else str(raw).strip(),
                }
                for name, raw in raw_fields.items()
            ]
        )

    per_value = []
    for index, expected in enumerate(str(v) for v in (case.expected_values or ())):
        cols = []
        for row in rows:
            for col_index, cell in enumerate(row):
                if cell["value"] and check_value(cell["value"], expected):
                    cols.append(
                        {
                            "role": cell["role"],
                            "col_index": col_index,
                            "exact": cell["value"].strip() == expected.strip(),
                            "cell_len": len(cell["value"]),
                            "value_in_cell_len": len(cell["value"]),
                        }
                    )
        per_value.append(
            {
                "i": index,
                "value_len": len(expected),
                "value_digits": sum(1 for ch in expected if ch.isdigit()),
                "value_has_space": " " in expected,
                "columns": cols,
            }
        )

    word_hits = {
        str(role): any(_norm(word) in normalized for word in words)
        for role, words in FIELD_WORDS.items()
    }
    return {
        "ok": True,
        "case_id": CASE,
        "question_len": len(question),
        "match_field_first": str(first or ""),
        "match_fields": matched,
        "field_word_hits": word_hits,
        "expected": per_value,
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

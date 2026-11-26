"""C27 定位汇总：把探针产物压成报告用计数（只出角色码 / 列序号 / 整数 / 布尔 / 固定码）。

离线只读；输入全部是本进程先前的探针产物（已在进程内由私有输入导出，只含白名单字段）。
"""
from __future__ import annotations

import hashlib
import json
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
EVID = HERE.parent / "evidence" / "12-c27"
OUT = EVID / "c27-summary.json"

FILES = {
    "layer": EVID / "c27-layer-counts.json",
    "shape": EVID / "c27-shape.json",
    "roles": EVID / "c27-question-roles.json",
    "words": EVID / "c27-question-words.json",
}


def _sha(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _main() -> dict:
    docs = {name: json.loads(path.read_text(encoding="utf-8")) for name, path in FILES.items()}
    layer = docs["layer"]
    shape = docs["shape"]
    roles = docs["roles"]
    words = docs["words"]

    row = (layer.get("rows") or [{}])[0]
    counts = dict(row.get("role_column_counts") or {})
    per_value = []
    for item in layer.get("per_value") or ():
        per_value.append(
            {
                "i": int(item.get("i")),
                "role": str(item.get("role") or ""),
                "col_index": int(item.get("col_index")),
                "in_facts": bool(item.get("in_facts")),
                "fact_role": str(item.get("fact_role") or ""),
                "in_answer_text": bool(item.get("in_answer_text")),
                "in_commit_text": bool(item.get("in_commit_text")),
            }
        )
    facts = [
        {"fact_index": int(item.get("fact_index")), "role": str(item.get("role") or ""), "col_index": int(item.get("col_index"))}
        for item in layer.get("facts") or ()
    ]
    requested = [str(role) for role in (layer.get("plan_field_roles") or ())]
    missing = [item for item in per_value if not item["in_answer_text"]]
    missing_roles = sorted({item["role"] for item in missing if item["role"] and item["role"] not in requested})
    dropped_cols = sorted({item["col_index"] for item in missing})
    return {
        "ok": True,
        "case_id": str(layer.get("case_id")),
        "plan_field_roles": requested,
        "cited_rows": int(layer.get("cited_rows") or 0),
        "row_columns": int(row.get("raw_columns") or 0),
        "role_column_counts": {
            "phone": int(counts.get("phone", 0)),
            "address": int(counts.get("address", 0)),
            "contact": int(counts.get("contact", 0)),
            "all": {str(k): int(v) for k, v in counts.items()},
        },
        "facts": facts,
        "fact_count": int(layer.get("fact_count") or 0),
        "expected_count": int(layer.get("expected_count") or 0),
        "per_value": per_value,
        "missing_count": int(layer.get("missing_count") or 0),
        "dropped_cols": dropped_cols,
        "missing_roles": missing_roles,
        "fixed_code": str(layer.get("fixed_code") or ""),
        "excluded": {
            "same_role_multi_column_dropped": bool(counts.get("phone", 0) <= 1 and counts.get("address", 0) <= 1),
            "dedup_dropped": bool(len({(item["role"], item["col_index"]) for item in per_value}) == len(per_value)),
            "commit_filter": bool(not any(item["in_facts"] and not item["in_answer_text"] for item in per_value)),
            "value_absent_in_cited_row": bool(all(item["col_index"] >= 0 for item in per_value)),
        },
        "question_words": {
            "non_lexicon_contact_ask": bool((words.get("derived") or {}).get("non_lexicon_contact_ask")),
            "contact_role_word_absent": not bool(roles.get("field_word_hits", {}).get("contact")),
            "phone_word": bool(roles.get("field_word_hits", {}).get("phone")),
            "address_word": bool(roles.get("field_word_hits", {}).get("address")),
        },
        "fix": {
            "point": "rag/query.py:FIELD_WORDS.contact (+_match_fields 并列扩展)",
            "not_in": ["rag/answer.py", "rag/facts.py"],
            "fixable_without_body_or_labels": "conditional",
            "conditions": [
                "only question-lexicon change; no corpus/body read, no dataset/label/threshold/frozen-criteria change",
                "contact role must not trip RESTRICTED_CONTACT_ROLES gate (no item/identifier in this case; phone+address already requested without tripping)",
                "offline synthetic regression must cover the non-lexicon contact wording and keep restricted-contact refusals unchanged",
            ],
        },
        "sha256": {name: _sha(path) for name, path in FILES.items()},
    }


def main() -> int:
    try:
        result = _main()
    except Exception:  # noqa: BLE001
        result = {"ok": False, "error": "summary_failed"}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "ok": result.get("ok"),
                "fixed_code": result.get("fixed_code"),
                "missing_roles": result.get("missing_roles"),
                "dropped_cols": result.get("dropped_cols"),
                "fixable": (result.get("fix") or {}).get("fixable_without_body_or_labels"),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())

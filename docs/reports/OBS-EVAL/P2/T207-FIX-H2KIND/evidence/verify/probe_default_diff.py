
import json, time
import mktkb.evaluation.scorers as _s
from mktkb.evaluation.dataset import CaseSpec, load_cases
from mktkb.evaluation.gold import ResolvedGold
from mktkb.evaluation.scorers import EvalCitation, EvalOutcome, score_case, REFUSAL_KINDS

ROOT = "D:/GPT项目/市场部AI知识库/fixtures/evaluation/"
KINDS = ("", "answer", "no_answer", "not_found", "refusal", "clarification", "conflict", "ambiguous", "error", "service_error")
TEXTS = ("", "B区1号货架第二层 2026-10-30 16:00 共12件", "该事项资料未收录，无法回答", "  \n ")
CIT = EvalCitation(doc_code="D01", unit_key="sheet:物品位置:row:8", unit_ids=("u1",))
PAG = {"total": 1, "returned": 1, "has_more": False, "next_page": None}

cases = []
for name in ("b0.jsonl", "badcase.jsonl", "regression.jsonl"):
    cases.extend(load_cases(ROOT + name))
with open(ROOT + "holdout-questions.jsonl", encoding="utf-8") as fh:
    for line in fh:
        if not line.strip():
            continue
        row = json.loads(line)
        cases.append(CaseSpec(
            case_id=str(row["case_id"]), suite="holdout", split="holdout",
            stratum=str(row["stratum"]), business_date=str(row["business_date"]),
            question=str(row["question"]), expected_kind=str(row["expected_kind"]),
            labeler=str(row["labeler"]), label_version=str(row["label_version"]),
            should_refuse=bool(row["should_refuse"]), requires_ocr=bool(row["requires_ocr"]),
        ))

rows = []
refusal_points = []
t0 = time.time()
for case in cases:
    gold = ResolvedGold(case_id=case.case_id, requires_ocr=bool(case.requires_ocr), skipped=False,
                        sources=(), unit_ids=(), relevant_unit_ids=())
    for kind in KINDS:
        for ti, text in enumerate(TEXTS):
            for ci, cits in enumerate(((), (CIT,))):
                out = EvalOutcome(kind=kind, text=text, citations=cits, pagination=PAG)
                r = score_case(case, gold, out)
                rows.append({"case_id": case.case_id, "kind": kind, "t": ti, "c": ci, **r.to_dict()})
                if str(case.expected_kind) == "refusal" and kind in ("not_found", "no_answer", "refusal"):
                    refusal_points.append((case.case_id, kind, ti, ci, r.check("kind_correct").status))
payload = json.dumps({"cases": len(cases), "comparisons": len(rows), "rows": rows},
                     ensure_ascii=False, sort_keys=True)
import hashlib
print(json.dumps({
    "module": _s.__file__,
    "has_compat_flag": hasattr(_s, "REFUSAL_COMPAT_KIND"),
    "cases": len(cases),
    "comparisons": len(rows),
    "bytes": len(payload.encode()),
    "sha256": hashlib.sha256(payload.encode()).hexdigest(),
    "elapsed": round(time.time()-t0, 1),
    "refusal_expected_cases": len({p[0] for p in refusal_points}),
    "refusal_default_pass_by_kind": {
        k: sum(1 for p in refusal_points if p[1]==k and p[4]=="pass") for k in ("not_found","no_answer","refusal")
    },
}, ensure_ascii=False, sort_keys=True))

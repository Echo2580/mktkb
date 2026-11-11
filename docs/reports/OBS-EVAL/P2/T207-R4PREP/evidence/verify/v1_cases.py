"""P2-T207-R4PREP 独立验收 v1：cases/R4.jsonl 必须逐字段等于冻结题集（只读、零网络）。

判定口径（不依赖开发方脚本）：
- 自己从 fixtures/acceptance/questions.json 逐字段映射（不复用 p2_public_cases 的转换器做"唯一证据"，
  但会把两种来源都打出来对照）；
- 顺序 / sha256 / label_version / expected_* / forbidden_* / suite / stratum 逐项断言。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve()
ROOT = next(p for p in HERE.parents if (p / "backend" / "src").is_dir())
T207 = ROOT / "docs" / "reports" / "OBS-EVAL" / "P2" / "T207"
CASES = T207 / "cases" / "R4.jsonl"
QUESTIONS = ROOT / "fixtures" / "acceptance" / "questions.json"
DOC_CODES = T207 / "cases" / "document-codes.json"
EXPECTED_SHA = "c04b67c6f8a44c09eaa3c4fc56a6ceb8dc97ac7665aea6ed92ef0ea01897fd84"
EXPECTED_ORDER = ["N08", "C05", "C06"]
STRICT_LOCATOR_KEYS = ("page", "sheet", "row", "column", "cell", "range")
SUITE_BY_GROUP = {"negative": "negative", "ambiguity_conflict": "boundary"}
BUSINESS_DATE = "2026-10-28"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def frozen_rows() -> tuple[dict, dict]:
    raw = QUESTIONS.read_bytes()
    payload = json.loads(raw.decode("utf-8"))
    rows = {str(item["id"]): item for item in payload["questions"]}
    return rows, {"sha256": hashlib.sha256(raw).hexdigest(), "version": payload.get("version")}


def my_convert(item: dict, label_version: str) -> dict:
    """我自己写的转换（只按模块头声明的口径），用于和文件逐字段对照。"""
    scenario = item.get("scenario") or {}
    should_refuse = str(scenario.get("expected_kind")) == "not_found"
    values = [] if should_refuse else [str(v) for v in (item.get("expected_values") or [])]
    sources = []
    for src in item.get("expected_sources") or []:
        entry: dict = {"doc_code": str(src.get("file"))}
        if src.get("record") is not None:
            entry["record_code"] = str(src["record"])
        if isinstance(src.get("locator"), dict):
            strict = {k: src["locator"][k] for k in STRICT_LOCATOR_KEYS if k in src["locator"]}
            if strict:
                entry["locator"] = strict
        sources.append(entry)
    forbidden = [{"doc_code": str(code)} for code in (scenario.get("forbidden_sources") or [])]
    notes = [
        f"source=fixtures/acceptance/questions.json id={item.get('id')}",
        f"group={item.get('group')}",
        f"category={item.get('category')}",
    ]
    reason = str(scenario.get("reason") or "").strip()
    if reason:
        notes.append(f"reason={reason}")
    if should_refuse:
        notes.append(
            "accepted_wording(any-of,not-scored)=" + "|".join(str(v) for v in item.get("expected_values") or [])
        )
    dropped: list = []
    for src in item.get("expected_sources") or []:
        locator = src.get("locator")
        if isinstance(locator, dict):
            for key in locator:
                if key not in STRICT_LOCATOR_KEYS and key not in dropped:
                    dropped.append(str(key))
    dropped = sorted(dropped)
    if dropped:
        notes.append("dropped_free_text_locator=" + ",".join(dropped))
    actions = scenario.get("actions") or []
    if actions:
        notes.append("scenario_actions=" + "|".join(str(a.get("op")) for a in actions))
    return {
        "case_id": str(item["id"]),
        "suite": SUITE_BY_GROUP[str(item["group"])],
        "split": "dev",
        "stratum": str(item.get("category") or item.get("group")),
        "business_date": BUSINESS_DATE,
        "question": str(item["question"]),
        "turns": [],
        "expected_kind": str(scenario.get("expected_kind")),
        "expected_values": values,
        "expected_sources": sources,
        "relevant_units": [],
        "reference_answer": "",
        "should_refuse": should_refuse,
        "refusal_reason": (reason or None) if should_refuse else None,
        "forbidden_values": [],
        "forbidden_sources": forbidden,
        "expected_pagination": None,
        "requires_ocr": False,
        "labeler": "acceptance-fixture",
        "label_version": label_version,
        "notes": "; ".join(notes),
    }


def main() -> None:
    rows, qmeta = frozen_rows()
    label_version = f"acceptance-{qmeta['version']}-{qmeta['sha256'][:12]}"
    lines = [line for line in CASES.read_text(encoding="utf-8").splitlines() if line.strip()]
    parsed = [json.loads(line) for line in lines]
    report: dict = {
        "cases_path": str(CASES.relative_to(ROOT)),
        "cases_sha256": sha256(CASES),
        "cases_sha256_expected": EXPECTED_SHA,
        "cases_sha256_match": sha256(CASES) == EXPECTED_SHA,
        "line_count": len(parsed),
        "order_observed": [row["case_id"] for row in parsed],
        "order_match": [row["case_id"] for row in parsed] == EXPECTED_ORDER,
        "label_version": label_version,
        "questions_sha256": qmeta["sha256"],
    }

    per_case = []
    for row in parsed:
        frozen = rows[row["case_id"]]
        expected = my_convert(frozen, label_version)
        diff = {k: {"mine": expected[k], "file": row.get(k)} for k in expected if row.get(k) != expected[k]}
        extra = sorted(set(row) - set(expected))
        per_case.append(
            {
                "case_id": row["case_id"],
                "matches_my_conversion": not diff,
                "diff": diff,
                "extra_fields": extra,
                "frozen_question_equal": row["question"] == frozen["question"],
                "frozen_kind_equal": row["expected_kind"] == frozen["scenario"]["expected_kind"],
                "frozen_values_equal": sorted(row["expected_values"])
                == sorted(str(v) for v in (frozen.get("expected_values") or [])) or bool(row["should_refuse"]),
                "label_version_equal": row["label_version"] == label_version,
            }
        )
    report["per_case"] = per_case

    # 与冻结转换器（既有只读转换器）逐行对照：两边都要能复原同一行。
    import sys

    sys.path.insert(0, str(ROOT / "backend" / "src"))
    from mktkb.evaluation.dataset import cases_to_jsonl  # noqa: E402
    from mktkb.evaluation.p2_public_cases import load_acceptance_cases  # noqa: E402

    from_converter = [json.loads(line) for line in cases_to_jsonl(
        load_acceptance_cases(ids=tuple(EXPECTED_ORDER))
    ).splitlines() if line.strip()]
    report["converter_rows_equal_file"] = from_converter == parsed
    report["converter_diff"] = [
        {"index": index, "converter": a, "file": b}
        for index, (a, b) in enumerate(zip(from_converter, parsed))
        if a != b
    ]

    # 文档代号映射（只按文档名；版本号不进映射）
    codes = json.loads(DOC_CODES.read_text(encoding="utf-8"))
    needed = {src["doc_code"] for row in parsed for src in row["expected_sources"]}
    needed |= {src["doc_code"] for row in parsed for src in row["forbidden_sources"]}
    mapped = {name: code for name, code in codes.items() if code in needed}
    report["document_codes"] = {
        "needed": sorted(needed),
        "mapped_names": mapped,
        "all_needed_mapped": needed <= set(codes.values()),
        "version_codes_present": sorted(c for c in codes.values() if c.startswith("V")),
    }

    # R4 与 R1/R2/R3 的题集不重叠（独立重测，不报销同一题）
    overlap = {}
    for name in ("R1.jsonl", "R2.jsonl", "R3.jsonl"):
        path = T207 / "cases" / name
        ids = {json.loads(line)["case_id"] for line in path.read_text(encoding="utf-8").splitlines() if line.strip()}
        overlap[name] = sorted(ids & set(EXPECTED_ORDER))
    report["overlap_with_other_runs_informational"] = overlap

    report["limitation_note"] = (
        "forbidden_sources 里的 V03/V06 在 document-codes.json 中没有对应文档名："
        "打分时 document_code 由产品文档名映射，版本号不进映射 ⇒ source_forbidden 对这两个代号是"
        "「不可命中」而不是「检查通过」；R2(C05)/R3(C06) 完全同形，属既有口径，不是本包引入。"
    )
    checks = {
        "sha256_matches": report["cases_sha256_match"],
        "three_lines": len(parsed) == 3,
        "order_is_N08_C05_C06": report["order_match"],
        "all_rows_match_my_conversion": all(item["matches_my_conversion"] for item in per_case),
        "forbidden_source_codes_map_to_document_names": report["document_codes"]["all_needed_mapped"],
        "converter_reproduces_file": report["converter_rows_equal_file"],
        "label_version_traced_to_questions_json": all(item["label_version_equal"] for item in per_case),
    }
    report["checks"] = checks
    report["all_hold"] = all(checks.values())
    print(json.dumps(report, ensure_ascii=False, indent=1))




def _run(main_fn) -> None:
    import contextlib
    import io
    import sys
    from pathlib import Path

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        main_fn()
    text = buffer.getvalue()
    out = sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else None
    if out:
        Path(out).write_text(text, encoding="utf-8")
    sys.stdout.write(text)


if __name__ == "__main__":
    _run(main)


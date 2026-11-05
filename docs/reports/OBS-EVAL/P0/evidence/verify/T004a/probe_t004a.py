"""T004a independent verification probe (read-only w.r.t. repo).

Runs outside the repo test suite: builds the offline indexes itself, resolves every
fixture case one by one, and exercises fail-closed / dedupe / validation negatives.
Writes only to %TEMP%.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(r"D:\GPT项目\市场部AI知识库")
sys.path.insert(0, str(ROOT / "backend" / "src"))
sys.path.insert(0, str(ROOT / "tools"))

from mktkb.evaluation.dataset import (  # noqa: E402
    CASE_FIELDS,
    CaseSpec,
    dataset_version,
    load_cases,
    validate_case,
)
from mktkb.evaluation.gold import GoldUnresolved, resolve_gold  # noqa: E402
from mktkb.ingestion.parsers import ParseServices, parse_document  # noqa: E402
from mktkb.rag import DocumentSpec, RagConfig, RagIndex, adapt_parsed_unit  # noqa: E402

ACCEPTANCE = ROOT / "fixtures" / "acceptance"
EVAL = ROOT / "fixtures" / "evaluation"
CORPUS = ROOT / "corpus" / "enterprise-20261101"
B0_NON_OCR_KINDS = {"xlsx", "docx", "pdf-text"}
BADCASE_CODES = ("E03", "E11", "P03", "W01")
FAILS: list[str] = []


def check(cond: bool, label: str) -> None:
    print(("PASS " if cond else "FAIL ") + label)
    if not cond:
        FAILS.append(label)


def config(data_dir: Path) -> RagConfig:
    return RagConfig(
        provider_mode="offline",
        data_dir=data_dir,
        business_date="2026-10-28",
        chunk_max_chars=420,
        chunk_max_units=3,
        chunk_overlap_units=1,
        top_k=5,
        page_size=10,
        vector_candidate_limit=50,
        rerank_top_n=20,
    )


def build_b0_index(db_path: Path) -> RagIndex:
    manifest = json.loads((ACCEPTANCE / "manifest.json").read_text(encoding="utf-8"))
    index = RagIndex(db_path, config=config(db_path.parent))
    parsed_paths = []
    for item in manifest["normal_files"]:
        if str(item.get("kind")) not in B0_NON_OCR_KINDS:
            continue
        path = ACCEPTANCE / str(item["path"])
        parsed_paths.append(str(item["id"]))
        kind = path.suffix.lower().lstrip(".")
        parsed = list(parse_document(path, kind, ParseServices()))
        spec = DocumentSpec(
            doc_id=str(item["id"]),
            logical_id=str(item["id"]),
            source_path=str(item["path"]),
            title=path.stem,
            file_kind=kind,
            version_id=f"{item['id']}-v1",
            version_label="当前",
            sha256=str(item["sha256"]),
            business_date="2026-10-28",
        )
        units = [
            adapt_parsed_unit(unit, doc=spec, unit_id=f"{item['id']}-{ordinal}", ordinal=ordinal)
            for ordinal, unit in enumerate(parsed)
        ]
        result = index.add_document(spec, units, embed=True)
        assert not result.get("embedding_error"), result
    print("b0 index parsed doc ids:", parsed_paths)
    return index


def build_badcase_index(db_path: Path) -> RagIndex:
    from rag_experiment import build_new_index, load_corpus

    documents, skipped = load_corpus(CORPUS, only_codes=set(BADCASE_CODES))
    print("badcase index docs:", [spec.doc_id for spec, _ in documents], "skipped_count:", len(skipped))
    index, _stats = build_new_index(documents, db_path=db_path, config=config(db_path.parent))
    return index


def base_case(**overrides):
    payload = dict(
        case_id="X00",
        suite="b0",
        split="dev",
        stratum="exact",
        business_date="2026-10-28",
        question="测试问题",
        turns=(),
        expected_kind="answer",
        expected_values=(),
        expected_sources=(),
        relevant_units=(),
        reference_answer="",
        should_refuse=False,
        refusal_reason=None,
        forbidden_values=(),
        forbidden_sources=(),
        expected_pagination=None,
        requires_ocr=False,
        labeler="lead",
        label_version="b0-2026-11-04",
        notes="",
    )
    payload.update(overrides)
    return CaseSpec(**payload)


def expect_unresolved(label: str, case: CaseSpec, index, reason: str) -> None:
    try:
        resolve_gold([case], index)
    except GoldUnresolved as exc:
        check(exc.reason == reason, f"{label}: GoldUnresolved reason={exc.reason} (expected {reason})")
    else:
        check(False, f"{label}: expected GoldUnresolved")


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="t004a-probe-"))
    print("temp:", tmp)

    b0_cases = load_cases(EVAL / "b0.jsonl")
    bad_cases = load_cases(EVAL / "badcase.jsonl")
    print("b0 lines:", len(b0_cases), "badcase lines:", len(bad_cases))
    check(len(b0_cases) == 40, "b0 40 rows")
    check(len(bad_cases) == 13, "badcase 13 rows")
    check(all(set(c.to_dict()) == set(CASE_FIELDS) for c in b0_cases + bad_cases), "21 CASE_FIELDS on every row")
    for name in ("b0", "badcase"):
        raw = (EVAL / f"{name}.jsonl").read_bytes()
        first = json.loads(raw.decode("utf-8").split("\n")[0], object_pairs_hook=lambda pairs: [k for k, _ in pairs])
        check(first == list(CASE_FIELDS), f"{name} field order == CASE_FIELDS")
        check(b"\r" not in raw, f"{name} no CR bytes")
    strata = {name: sum(1 for c in b0_cases if c.stratum == name) for name in ("exact", "text", "ocr")}
    print("b0 strata:", strata)
    check(strata == {"exact": 24, "text": 8, "ocr": 8}, "b0 strata exact/text/ocr = 24/8/8")
    groups = {name: sum(1 for c in bad_cases if c.stratum == name) for name in ("poster", "policy", "price", "notice", "clarify", "safety")}
    print("badcase groups:", groups)
    check(groups == {"poster": 2, "policy": 1, "price": 4, "notice": 2, "clarify": 2, "safety": 2}, "badcase source groups 2/1/4/2/2/2")
    check({c.suite for c in b0_cases} == {"b0"} and {c.suite for c in bad_cases} == {"badcase"}, "suite values")
    check({c.split for c in b0_cases + bad_cases} == {"dev"}, "split=dev")
    check({c.business_date for c in b0_cases + bad_cases} == {"2026-10-28"}, "business_date=2026-10-28")
    check(all(c.expected_pagination is None for c in b0_cases + bad_cases), "expected_pagination null on every row")

    # ---- validation negatives, direct API calls (not via pytest)
    negatives = {
        "chunk_id key": base_case(expected_sources=({"doc_code": "D01", "chunk_id": "abc"},)),
        "unit_id key": base_case(expected_sources=({"doc_code": "D01", "unit_id": "x"},)),
        "unit_key UUID": base_case(expected_sources=({"doc_code": "D01", "unit_key": "0b6f9c1e-3a6f-4d2b-9f5f-1b2c3d4e5f60"},)),
        "unit_key 32hex": base_case(expected_sources=({"doc_code": "D01", "unit_key": "a" * 32},)),
        "locator unknown key": base_case(expected_sources=({"doc_code": "D01", "locator": {"image": True}},)),
        "missing doc_code": base_case(expected_sources=({"unit_key": "sheet:x:row:1"},)),
        "refuse no reason": base_case(should_refuse=True, refusal_reason=None),
        "question+turns empty": base_case(question="   ", turns=()),
        "invalid expected_kind": base_case(expected_kind="looks_right"),
        "bad pagination key": base_case(expected_pagination={"unknown": 1}),
    }
    for label, case in negatives.items():
        try:
            validate_case(case)
        except ValueError:
            check(True, f"validate rejects {label}")
        else:
            check(False, f"validate rejects {label}")

    # ---- OCR
    ocr = [c for c in b0_cases if c.requires_ocr]
    check(len(ocr) == 8 and all(c.stratum == "ocr" for c in ocr), "8 OCR cases require_ocr=true")
    check(
        all(set(src.get("locator") or {}) == {"page"} and "unit_key" not in src for c in ocr for src in c.expected_sources),
        "OCR sources only page locator, no unit_key",
    )
    # resolve_case short-circuits OCR before touching the index: passing None must work.
    ocr_resolved = resolve_gold(ocr, None)
    check(all(r.skipped and r.sources == () and r.unit_ids == () for r in ocr_resolved), "OCR skipped without index access")

    # ---- build indexes and resolve every case one by one
    b0_index = build_b0_index(tmp / "b0.sqlite3")
    visible = {d["doc_id"] for d in b0_index.list_documents()}
    check(visible == {"D01", "D02", "D03", "D04", "D05", "D06"}, f"b0 index visible docs D01-D06 only: {sorted(visible)}")
    check(visible.isdisjoint({"D07", "D08", "D09", "D10"}), "b0 index never parsed D07-D10 (no OCR path)")

    unresolved = []
    resolved_b0 = {}
    for case in b0_cases:
        try:
            resolved_b0[case.case_id] = resolve_gold([case], b0_index)[0]
        except GoldUnresolved as exc:
            unresolved.append((case.case_id, exc.reason, str(exc)))
    for case in b0_cases:
        item = resolved_b0.get(case.case_id)
        if case.requires_ocr:
            print(f"{case.case_id} ocr skipped={item.skipped if item else None}")
        elif item:
            print(
                f"{case.case_id} resolved doc={','.join(s.doc_code for s in item.sources)} "
                f"units={len(item.unit_ids)} keys={','.join(k for s in item.sources for k in s.unit_keys)}"
            )
    check(not unresolved, f"b0 all 40 resolve, unresolved={unresolved}")
    non_ocr_ok = all(
        resolved_b0[c.case_id].sources and len(resolved_b0[c.case_id].unit_ids) >= 1
        for c in b0_cases
        if not c.requires_ocr
    )
    check(non_ocr_ok, "b0 32 non-OCR cases each resolve with >=1 unit")
    check(sum(1 for c in b0_cases if not c.requires_ocr and resolved_b0[c.case_id].skipped is False) == 32, "b0 32 non-OCR not skipped")
    # If the OCR flag were false, D07 is absent from the index and the case must fail closed,
    # proving the skip is driven by requires_ocr rather than a fabricated gold.
    mutated_ocr = dataclasses.replace(next(c for c in b0_cases if c.case_id == "Q33"), requires_ocr=False)
    expect_unresolved("OCR flag off -> D07 absent", mutated_ocr, b0_index, "document_not_found")

    bad_index = build_badcase_index(tmp / "badcase.sqlite3")
    unresolved_bad = []
    resolved_bad = {}
    for case in bad_cases:
        try:
            resolved_bad[case.case_id] = resolve_gold([case], bad_index)[0]
        except GoldUnresolved as exc:
            unresolved_bad.append((case.case_id, exc.reason, str(exc)))
    for case in bad_cases:
        item = resolved_bad.get(case.case_id)
        if item:
            print(
                f"{case.case_id} resolved sources={len(item.sources)} units={len(item.unit_ids)} "
                f"keys={','.join(k for s in item.sources for k in s.unit_keys)}"
            )
    check(not unresolved_bad, f"badcase all 13 resolve, unresolved={unresolved_bad}")
    empty_gold = {cid for cid in ("N10", "N12", "N13") if resolved_bad[cid].sources == () and resolved_bad[cid].unit_ids == ()}
    check(empty_gold == {"N10", "N12", "N13"}, "N10/N12/N13 empty gold preserved")
    check(len(resolved_bad["N05"].unit_ids) > 1, f"N05 whole-sheet locator returns multiple units ({len(resolved_bad['N05'].unit_ids)})")
    check(len(resolved_bad["N09"].unit_ids) == 17, f"N09 whole-document returns 17 units ({len(resolved_bad['N09'].unit_ids)})")

    # ---- fail-closed probes
    expect_unresolved("0 match document", base_case(case_id="P1", expected_sources=({"doc_code": "D99", "unit_key": "x"},)), b0_index, "document_not_found")
    expect_unresolved("0 match unit_key", base_case(case_id="P2", expected_sources=({"doc_code": "D01", "unit_key": "sheet:物品位置:row:999"},)), b0_index, "unit_key_not_found")
    expect_unresolved("0 match locator", base_case(case_id="P3", expected_sources=({"doc_code": "D01", "locator": {"sheet": "物品位置", "row": 999}},)), b0_index, "locator_not_found")
    expect_unresolved("unsupported locator key", base_case(case_id="P4", expected_sources=({"doc_code": "D01", "locator": {"image": True}},)), b0_index, "unsupported_locator_key")
    record_only = base_case(case_id="P4b", expected_sources=({"doc_code": "D01", "record_code": "P01"},))
    record_only_resolved = resolve_gold([record_only], b0_index)[0]
    print(
        f"OBSERVE record_code-only source -> {len(record_only_resolved.unit_ids)} units "
        "(record_code is validated but not a resolution key; doc-level fallback)"
    )

    # duplicate unit_key in one document (two versions, same key) -> identity reference must fail
    from mktkb.rag import AtomicUnit
    from mktkb.rag.models import RagChunk, RagUnit

    dup_index = RagIndex(tmp / "dup.sqlite3", config=config(tmp))
    spec = DocumentSpec(
        doc_id="D01", logical_id="D01", source_path="normal/D01_物品位置表.xlsx", title="物品位置表",
        file_kind="xlsx", version_id="D01-v1", version_label="当前", sha256="0" * 64, business_date="2026-10-28",
    )
    unit = AtomicUnit(
        unit_id="D01-dup-current", doc_id="D01", version_id="D01-v1", kind="table_row", ordinal=0,
        unit_key="sheet:物品位置:row:8", text="标识: P01", fields={"标识": "P01"}, sheet="物品位置",
        locator={"sheet": "物品位置", "row": 8, "header_row": 7}, header_row=7, row_number=8, title="物品位置表",
    )
    result = dup_index.add_document(spec, [unit], embed=True)
    assert not result.get("embedding_error"), result
    with dup_index.session() as session:
        session.add(RagUnit(
            unit_id="D01-dup-legacy", doc_id="D01", version_id="D01-v0", kind="table_row", ordinal=1,
            unit_key="sheet:物品位置:row:8", text="标识: P01（遗留行）", fields={"标识": "P01"},
            sheet="物品位置", locator={"sheet": "物品位置", "row": 8, "header_row": 7}, header_row=7,
            row_number=8, title="物品位置表",
        ))
        session.commit()
    expect_unresolved("duplicate unit_key", base_case(case_id="P5", expected_sources=({"doc_code": "D01", "unit_key": "sheet:物品位置:row:8"},)), dup_index, "duplicate_unit_key")
    expect_unresolved("locator ambiguous duplicate keys", base_case(case_id="P6", expected_sources=({"doc_code": "D01", "locator": {"sheet": "物品位置", "row": 8}},)), dup_index, "ambiguous_units")
    dup_index.close()

    # multi-chunk single unit -> unit-level dedupe
    split_index = RagIndex(tmp / "split.sqlite3", config=config(tmp))
    spec2 = DocumentSpec(
        doc_id="D90", logical_id="D90", source_path="normal/D90_长记录.xlsx", title="长记录",
        file_kind="xlsx", version_id="D90-v1", version_label="当前", sha256="0" * 64, business_date="2026-10-28",
    )
    fields = {"标识": "L01", "门店": "测试店", "物品": "长物料", "位置": "A区1号货架"}
    fields.update({f"说明{i:02d}": "这是一段用于触发记录块拆分的较长说明文本" * 3 for i in range(20)})
    long_unit = AtomicUnit(
        unit_id="D90-long", doc_id="D90", version_id="D90-v1", kind="table_row", ordinal=0,
        unit_key="sheet:物品位置:row:8", text="；".join(f"{k}: {v}" for k, v in fields.items()), fields=fields,
        sheet="物品位置", locator={"sheet": "物品位置", "row": 8, "header_row": 7}, header_row=7, row_number=8, title="长记录",
    )
    result = split_index.add_document(spec2, [long_unit], embed=True)
    assert not result.get("embedding_error"), result
    with split_index.session() as session:
        chunks = session.execute(__import__("sqlalchemy").select(RagChunk).where(RagChunk.doc_id == "D90")).scalars().all()
    print("split fixture chunk count:", len(chunks), "record_unit_ids:", {c.record_unit_id for c in chunks})
    split_resolved = resolve_gold(
        [base_case(case_id="P7", expected_sources=({"doc_code": "D90", "unit_key": "sheet:物品位置:row:8"},))], split_index
    )[0]
    check(len(chunks) > 1 and split_resolved.unit_ids == ("D90-long",), "multiple chunks of one unit collapse to 1 gold unit")
    split_index.close()
    b0_index.close()
    bad_index.close()

    # ---- version / hashes
    for suite, label in (("b0", "b0-2026-11-04"), ("badcase", "badcase-2026-11-04")):
        cases = b0_cases if suite == "b0" else bad_cases
        version = dataset_version(cases, label)
        digest = hashlib.sha256((EVAL / f"{suite}.jsonl").read_bytes()).hexdigest()
        print(f"{suite} version={version} file_sha256={digest}")
        check(version.endswith(digest[:12]) and version == f"{suite}:{label}:{digest[:12]}", f"{suite} dataset_version matches file sha256[:12]")
        check(dataset_version(cases, label) == version, f"{suite} dataset_version stable on recompute")

    print("FAILS:", FAILS)
    print("RESULT:", "PASS" if not FAILS else "FAIL")
    return 0 if not FAILS else 1


if __name__ == "__main__":
    raise SystemExit(main())

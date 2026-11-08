"""T110 independent verification probe (acceptance-side, not a deliverable).

Part 1: same-chunk retrieval metrics hand calculations.
Part 2: `relevant_units` selection / fallback / fail-closed with tiny offline indexes.
No network, no real embedding/rerank/model/OCR call; only `provider_mode="offline"`.

Run from the repo root:
    PYTHONPATH=backend/src .venv/Scripts/python.exe -B \
      docs/reports/OBS-EVAL/P1/evidence/verify/T110/02-probe.py
"""
from __future__ import annotations

import math
import sys
import tempfile
from pathlib import Path

from mktkb.evaluation.dataset import CaseSpec
from mktkb.evaluation.gold import GoldUnresolved, ResolvedGold, resolve_case
from mktkb.evaluation.scorers import (
    EvalOutcome,
    EvalRetrieved,
    aggregate_metrics,
    retrieval_metrics,
    score_case,
)
from mktkb.rag import AtomicUnit, DocumentSpec, RagConfig, RagIndex
from mktkb.rag.models import RagUnit

FAILS: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'} {name}" + (f" :: {detail}" if detail else ""))
    if not ok:
        FAILS.append(name)


def close(a, b, tol: float = 1e-12) -> bool:
    return a is not None and b is not None and abs(a - b) <= tol


def idcg(n: int) -> float:
    return sum(1.0 / math.log2(r + 1) for r in range(1, min(n, 10) + 1))


# --------------------------------------------------------------------------- #
# Part 1: metrics
# --------------------------------------------------------------------------- #


def mcase(case_id: str, forbidden=()) -> CaseSpec:
    return CaseSpec(
        case_id=case_id,
        suite="t110-verify",
        split="dev",
        stratum="exact",
        business_date="2026-11-09",
        question="probe",
        expected_kind="answer",
        forbidden_sources=tuple(forbidden),
        label_version="probe-1",
    )


def gold(case_id: str, relevant) -> ResolvedGold:
    return ResolvedGold(
        case_id=case_id,
        requires_ocr=False,
        skipped=False,
        sources=(),
        unit_ids=(),
        relevant_unit_ids=tuple(relevant),
    )


def items(chunk_id, *units, doc="D01", violation=None):
    return tuple(
        EvalRetrieved(doc_code=doc, unit_ids=(u,), chunk_id=chunk_id, hard_filter_violation=violation)
        for u in units
    )


def scored(case_id: str, relevant, retrieved, forbidden=()):
    return score_case(
        mcase(case_id, forbidden),
        gold(case_id, relevant),
        EvalOutcome(kind="answer", retrieved=retrieved),
    )


# 1. One chunk with 3 units, 2 relevant: shared rank 1, one gain only.
r = scored("A", ("u1", "u2"), items("c1", "u1", "u2", "u9") + items("c2", "u3"))
check("A recall 2/2", close(r.metrics["Recall@10"], 1.0))
check("A MRR 1 (chunk rank, not unit order)", close(r.metrics["MRR@10"], 1.0))
check("A nDCG one gain at rank1", close(r.metrics["nDCG@10"], 1.0 / idcg(2)), str(r.metrics["nDCG@10"]))
check("A nDCG <= 1", r.metrics["nDCG@10"] <= 1.0)

# 2. Relevant unit is third inside its chunk; still rank 1.
r = scored("B", ("u3",), items("c1", "u1", "u2", "u3") + items("c2", "u9"))
check("B MRR 1 not 1/3", close(r.metrics["MRR@10"], 1.0))
check("B nDCG 1", close(r.metrics["nDCG@10"], 1.0))

# 3. Duplicate unit over chunks: no double recall/gain; duplicate still occupies rank 2.
r = scored("C", ("u1", "u2"), items("c1", "u1") + items("c2", "u1") + items("c3", "u2"))
check("C recall deduped 2/2", close(r.metrics["Recall@10"], 1.0))
check("C retrieved_units deduped to 2", r.metrics["retrieved_units"] == 2, str(r.metrics["retrieved_units"]))
check("C nDCG one gain at rank1 + rank3", close(r.metrics["nDCG@10"], 1.5 / idcg(2)), str(r.metrics["nDCG@10"]))

# 4. Partial hit.
r = scored("D", ("u1", "u2", "u3", "u4"), items("c1", "u9") + items("c2", "u1") + items("c3", "u2", "u3"))
check("D recall 3/4", close(r.metrics["Recall@10"], 0.75))
check("D MRR 1/2", close(r.metrics["MRR@10"], 0.5))
check(
    "D nDCG",
    close(r.metrics["nDCG@10"], (1 / math.log2(3) + 1 / math.log2(4)) / idcg(4)),
    str(r.metrics["nDCG@10"]),
)

# 5. Empty retrieved.
r = scored("E", ("u1",), ())
check("E zeros", close(r.metrics["Recall@10"], 0.0) and close(r.metrics["MRR@10"], 0.0) and close(r.metrics["nDCG@10"], 0.0))
check("E empty_recall 1", close(r.metrics["empty_recall"], 1.0))
check("E empty_recall_rate 1", close(retrieval_metrics([r])["empty_recall_rate"], 1.0))

# 6. 11th chunk is not top-10, even with 20 units in first 10 chunks.
noise = tuple(x for i in range(10) for x in items(f"n{i}", f"x{i}a", f"x{i}b", doc="D02"))
r = scored("F", ("u1",), noise + items("hit", "u1"))
check("F top10 chunks", r.metrics["retrieved_units"] == 21, str(r.metrics["retrieved_units"]))
check("F 11th chunk excluded", close(r.metrics["Recall@10"], 0.0) and close(r.metrics["MRR@10"], 0.0) and close(r.metrics["nDCG@10"], 0.0))

# 7. chunk_id groups multiple rows into one rank; duplicate unit no gain.
r = scored("G", ("u1", "u2", "u3"), items("c1", "u1") + items("c1", "u2") + items("c2", "u1") + items("c3", "u3"))
check("G same chunk_id shares rank 1", close(r.metrics["MRR@10"], 1.0))
check("G has 3 physical chunks", close(r.metrics["nDCG@10"], 1.5 / idcg(3)), str(r.metrics["nDCG@10"]))

# 8. Hard filter rate / empty recall denominators.
r1 = scored(
    "H1",
    ("u1",),
    items("c1", "u1") + items("c2", "u9", violation="stale") + items("c3", "u8", doc="D08"),
    forbidden=({"doc_code": "D08"},),
)
check("H1 retrieved 3", r1.metrics["retrieved_units"] == 3, str(r1.metrics["retrieved_units"]))
check("H1 violations 2", r1.metrics["hard_filter_violations"] == 2, str(r1.metrics["hard_filter_violations"]))
check("H1 rate 2/3", close(retrieval_metrics([r1])["hard_filter_violation_rate"], 2 / 3))
r2 = scored("H2", (), items("c1", "x1", violation="stale") + items("c2", "x2"))
check("H2 no gold -> metrics None", r2.metrics["Recall@10"] is None and r2.metrics["empty_recall"] is None)
metrics = retrieval_metrics([r1, r2])
check("H2 no-gold excluded from rate", close(metrics["hard_filter_violation_rate"], 2 / 3), str(metrics["hard_filter_violation_rate"]))
check("H2 no-gold excluded from empty", close(metrics["empty_recall_rate"], 0.0), str(metrics["empty_recall_rate"]))

# 9. All relevant in one chunk: conservative nDCG, still <=1.
r = scored("I", ("u1", "u2", "u3"), items("c1", "u1", "u2", "u3"))
check("I recall 1", close(r.metrics["Recall@10"], 1.0))
check("I nDCG one gain / unit ideal", close(r.metrics["nDCG@10"], 1.0 / idcg(3)), str(r.metrics["nDCG@10"]))
check("I nDCG <= 1", r.metrics["nDCG@10"] <= 1.0)

# 10. Aggregate seven hand cases.
rows = [
    scored("A", ("u3",), items("a1", "u1", "u2", "u3") + items("a2", "u9")),
    scored("B", ("u1", "u2"), items("b1", "u1", "u2", "u9") + items("b2", "u3")),
    scored("C", ("u1", "u2"), items("c1", "u1") + items("c2", "u1") + items("c3", "u2")),
    scored("D", ("u1", "u2", "u3", "u4"), items("d1", "u9") + items("d2", "u1") + items("d3", "u2", "u3")),
    scored("E", ("u1",), ()),
    scored("F", ("u1",), noise + items("f-hit", "u1")),
    scored(
        "G",
        ("u1",),
        items("g1", "u1") + items("g2", "u9", violation="stale") + items("g3", "u8", doc="D08"),
        forbidden=({"doc_code": "D08"},),
    ),
]
cases = [mcase(cid) for cid in ("A", "B", "C", "D", "E", "F", "G")]
agg = aggregate_metrics(cases, rows)
check("agg recall", close(agg["Recall@10"], (1 + 1 + 1 + 0.75 + 0 + 0 + 1) / 7), str(agg["Recall@10"]))
check("agg MRR", close(agg["MRR@10"], (1 + 1 + 1 + 0.5 + 0 + 0 + 1) / 7), str(agg["MRR@10"]))
check(
    "agg nDCG",
    close(
        agg["nDCG@10"],
        (1 + 1 / idcg(2) + 1.5 / idcg(2) + (1 / math.log2(3) + 1 / math.log2(4)) / idcg(4) + 0 + 0 + 1) / 7,
    ),
    str(agg["nDCG@10"]),
)
check("agg hard", close(agg["hard_filter_violation_rate"], 2 / 38), str(agg["hard_filter_violation_rate"]))
check("agg empty", close(agg["empty_recall_rate"], 1 / 7), str(agg["empty_recall_rate"]))
check(
    "agg fields present",
    {"Recall@10", "MRR@10", "nDCG@10", "hard_filter_violation_rate", "empty_recall_rate"} <= set(agg),
)

# --------------------------------------------------------------------------- #
# Part 2: gold resolution fail-closed probes
# --------------------------------------------------------------------------- #


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


def unit(uid: str, key: str, ordinal: int, row: int) -> AtomicUnit:
    return AtomicUnit(
        unit_id=uid,
        doc_id="D01",
        version_id="D01-v1",
        kind="table_row",
        ordinal=ordinal,
        unit_key=key,
        text=f"row {row}",
        fields={"row": str(row)},
        sheet="S",
        locator={"sheet": "S", "row": row, "header_row": row - 1},
        header_row=row - 1,
        row_number=row,
        title="T",
    )


def dspec() -> DocumentSpec:
    return DocumentSpec(
        doc_id="D01",
        logical_id="D01",
        source_path="normal/D01.xlsx",
        title="T",
        file_kind="xlsx",
        version_id="D01-v1",
        version_label="当前",
        sha256="0" * 64,
        business_date="2026-10-28",
    )


def gcase(case_id: str, expected=(), relevant=()) -> CaseSpec:
    return CaseSpec(
        case_id=case_id,
        suite="t110-verify",
        split="dev",
        stratum="exact",
        business_date="2026-10-28",
        question="probe",
        expected_kind="answer",
        expected_sources=tuple(expected),
        relevant_units=tuple(relevant),
        label_version="probe-1",
    )


def build_index(path: Path) -> RagIndex:
    index = RagIndex(path, config=config(path.parent))
    result = index.add_document(
        dspec(),
        [unit("D01-8", "sheet:S:row:8", 0, 8), unit("D01-9", "sheet:S:row:9", 1, 9), unit("D01-10", "sheet:S:row:10", 2, 10)],
        embed=True,
    )
    assert not result.get("embedding_error"), result
    return index


def build_duplicate_index(path: Path) -> RagIndex:
    index = RagIndex(path, config=config(path.parent))
    result = index.add_document(dspec(), [unit("D01-8", "sheet:S:row:8", 0, 8)], embed=True)
    assert not result.get("embedding_error"), result
    with index.session() as session:
        session.add(
            RagUnit(
                unit_id="D01-8-legacy",
                doc_id="D01",
                version_id="D01-v0",
                kind="table_row",
                ordinal=1,
                unit_key="sheet:S:row:8",
                text="legacy",
                fields={"row": "8"},
                sheet="S",
                locator={"sheet": "S", "row": 8, "header_row": 7},
                header_row=7,
                row_number=8,
                title="T",
            )
        )
        session.commit()
    return index


def expect_unresolved(name: str, fn, reason: str) -> None:
    try:
        fn()
    except GoldUnresolved as exc:
        check(name, exc.reason == reason, f"reason={exc.reason}")
    except Exception as exc:  # noqa: BLE001
        check(name, False, f"wrong exception {type(exc).__name__}: {exc}")
    else:
        check(name, False, "no exception")


with tempfile.TemporaryDirectory(prefix="t110-verify-") as tmp:
    tmp_path = Path(tmp)
    index = build_index(tmp_path / "ok.sqlite3")
    dup = build_duplicate_index(tmp_path / "dup.sqlite3")
    try:
        source8 = {"doc_code": "D01", "unit_key": "sheet:S:row:8"}
        source9 = {"doc_code": "D01", "unit_key": "sheet:S:row:9"}
        resolved = resolve_case(gcase("G1", expected=(source8,), relevant=(source9,)), index)
        check("override uses relevant_units", resolved.relevant_unit_ids == ("D01-9",), str(resolved.relevant_unit_ids))
        check("override keeps expected_sources for answer", resolved.unit_ids == ("D01-8",), str(resolved.unit_ids))

        resolved = resolve_case(gcase("G2", expected=(source8,)), index)
        check("empty relevant falls back to expected", resolved.relevant_unit_ids == resolved.unit_ids == ("D01-8",), str(resolved.relevant_unit_ids))

        resolved = resolve_case(gcase("G3"), index)
        check("both empty -> no gold, no error", resolved.relevant_unit_ids == () and resolved.unit_ids == (), str(resolved.relevant_unit_ids))

        expect_unresolved(
            "unknown unit_key fails closed",
            lambda: resolve_case(gcase("G4", relevant=({"doc_code": "D01", "unit_key": "sheet:S:row:999"},)), index),
            "unit_key_not_found",
        )
        expect_unresolved(
            "duplicate unit_key fails closed",
            lambda: resolve_case(gcase("G5", relevant=({"doc_code": "D01", "unit_key": "sheet:S:row:8"},)), dup),
            "duplicate_unit_key",
        )
        expect_unresolved(
            "locator identity conflict fails closed",
            lambda: resolve_case(gcase("G6", relevant=({"doc_code": "D01", "locator": {"sheet": "S", "row": 8}},)), dup),
            "ambiguous_units",
        )
        expect_unresolved(
            "locator no match fails closed",
            lambda: resolve_case(gcase("G7", relevant=({"doc_code": "D01", "locator": {"sheet": "S", "row": 999}},)), index),
            "locator_not_found",
        )
        record_only = {"doc_code": "D01", "record_code": "P01"}
        expect_unresolved(
            "record_code-only relevant fails closed",
            lambda: resolve_case(gcase("G8", relevant=(record_only,)), index),
            "record_code_not_a_lookup_key",
        )
        expect_unresolved(
            "record_code-only expected_sources fails closed",
            lambda: resolve_case(gcase("G9", expected=(record_only,)), index),
            "record_code_not_a_lookup_key",
        )
        resolved = resolve_case(gcase("G10", relevant=({"doc_code": "D01", "locator": {"sheet": "S"}},)), index)
        check("locator range returns unit set", len(resolved.relevant_unit_ids) == 3, str(resolved.relevant_unit_ids))
        check("locator range deduped", len(set(resolved.relevant_unit_ids)) == len(resolved.relevant_unit_ids), str(resolved.relevant_unit_ids))
        try:
            observed = resolve_case(
                gcase("G11", relevant=({"doc_code": "D01", "record_code": "P01", "locator": {}},)),
                index,
            )
            print("OBSERVE record_code+empty locator ->", observed.relevant_unit_ids)
        except GoldUnresolved as exc:
            print("OBSERVE record_code+empty locator ->", exc.reason)
    finally:
        index.close()
        dup.close()

print(f"FAILS={len(FAILS)}")
sys.exit(1 if FAILS else 0)

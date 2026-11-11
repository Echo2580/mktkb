"""Independent synthetic acceptance, no production data or credentials."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import sys
import tempfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[7]
sys.path[:0] = [str(ROOT / "backend/src"), str(ROOT / "backend/tests")]
import pytest
from cryptography.fernet import Fernet
from acceptance.support.netguard import t09_network_guard
from mktkb.config import Settings
from mktkb.evaluation import p2_dataset as ds
from mktkb.evaluation import p2_runner as r
from mktkb.evaluation.product_adapter import P2RunDataset, P2IngestPlan, IngestSource

Settings.model_config = {**Settings.model_config, "env_file": None}
STRATA = [("paraphrase", 10), ("multi_turn", 5), ("negative", 5),
          ("stale_conflict", 5), ("cross_doc_security", 5)]
VALUE = "独立合成答案甲"
DOC_TEXT = "SYNTHETICDOCUMENTSECRET"
FRAGMENT = "InventoryFragmentSecret"
LABEL = "p2-holdout-v2-2026-11-10"


def sha(b):
    return hashlib.sha256(b).hexdigest()


def create_sealed(base):
    questions, labels, oracle = [], [], []
    number = 0
    for stratum, count in STRATA:
        for offset in range(count):
            number += 1
            negative = stratum == "negative"
            expected = "refusal" if negative else ("conflict" if stratum == "stale_conflict" else "answer")
            turns = ([f"独立合成多轮{number}第一问", f"独立合成多轮{number}末问"]
                     if stratum == "multi_turn" else [])
            if number == 15:
                turns.insert(1, "独立合成第十五题中间问")
            q = {"case_id": f"INDEP-{number:02d}", "suite": "holdout", "split": "holdout",
                 "stratum": stratum, "business_date": "2026-10-28",
                 "question": "" if turns else f"独立合成问句 {FRAGMENT} 编号 {number}",
                 "turns": turns, "expected_kind": expected, "should_refuse": negative,
                 "requires_ocr": False, "labeler": "data-custodian", "label_version": LABEL,
                 "notes": "独立合成"}
            sources = [] if expected in {"refusal", "conflict"} else [{"doc_code": "D01", "unit_key": "sheet:物品位置:row:8"}]
            if number == 7:
                sources.append({"doc_code": "D02", "unit_key": "sheet:物品位置:row:8"})
            if number == 28:
                sources = [{"doc_code": "V99", "unit_key": "sheet:物品位置:row:8"}]
            lab = {"case_id": q["case_id"], "expected_kind": expected,
                   "expected_values": [VALUE] if expected == "answer" else [],
                   "expected_sources": sources, "relevant_units": [],
                   "reference_answer": f"独立参考答复{number}" if expected == "answer" else "",
                   "should_refuse": negative, "refusal_reason": "合成拒答" if negative else None,
                   "forbidden_values": [], "forbidden_sources": [], "notes": "独立合成"}
            actual = "not_found" if negative else expected
            if number == 17:
                actual = "answer"
            if number == 6:
                actual = "not_found"
            error = "not_executed" if number in {4, 30} else ("INDEPENDENT_ERROR" if number == 12 else None)
            actual = "not_executed" if error == "not_executed" else ("error" if error else actual)
            checks = ({"source_hit", "value_hit", "kind_correct", "refusal_unexpected"} if number == 6
                      else {"kind_correct", "refusal_expected"} if number == 17
                      else {"source_hit"} if number in {7, 28} else set())
            oracle.append(dict(number=number, stratum=stratum, expected=expected, actual=actual,
                               should_refuse=negative, checks=checks, error=error,
                               codes={x["doc_code"] for x in sources},
                               source_failed={"D01"} if number == 6 else {"D02"} if number == 7 else {"V99"} if number == 28 else set()))
            questions.append(q)
            labels.append(lab)
    encode = lambda rows: ("\n".join(json.dumps(x, ensure_ascii=False) for x in rows) + "\n").encode()
    qp, lp = encode(questions), encode(labels)
    key = Fernet.generate_key()
    f = Fernet(key)
    qc, lc = f.encrypt(qp), f.encrypt(lp)
    sealed = base / "independent-sealed"
    sealed.mkdir()
    (sealed / ds.QUESTIONS_CIPHERTEXT_NAME).write_bytes(qc)
    (sealed / ds.LABELS_CIPHERTEXT_NAME).write_bytes(lc)
    manifest = {"schema_version": ds.P2_MANIFEST_SCHEMA_VERSION, "dataset_version": "P2-HOLDOUT-v2",
                "suite": ds.P2_DATASET_SUITE, "label_version": LABEL, "case_count": 30,
                "strata": dict(STRATA), "business_date": "2026-10-28",
                "created_utc": "2026-11-10T12:00:00+00:00", "author": "data-custodian",
                "encryption": {"kind": "fernet", "key_id": "p2-holdout-v2"},
                "questions_plaintext_sha256": sha(qp), "labels_plaintext_sha256": sha(lp),
                "questions_ciphertext_sha256": sha(qc), "labels_ciphertext_sha256": sha(lc),
                "turn_stats": {"total_turns": 36, "max_turns_per_case": 3,
                               "turn_histogram": {"1": 25, "2": 4, "3": 1}}}
    path = sealed / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    key_path = base / "synthetic.key"
    key_path.write_bytes(key)
    os.environ[ds.HOLDOUT_ROOT_ENV] = str(sealed)
    os.environ[ds.HOLDOUT_KEY_FILE_ENV] = str(key_path)
    return P2RunDataset.from_p2_dataset(ds.load_p2_dataset(path, visibility="holdout")), oracle


def product(kind="answer"):
    return {"kind": kind, "text": VALUE if kind == "answer" else "", "sources": ([{
        "source_id": "11111111-1111-4111-8111-111111111111", "document_name": "D01_物品位置表.xlsx",
        "version_number": 1, "status": "active", "locator": {"sheet": "物品位置", "row": 8},
    }] if kind == "answer" else []), "evidence": ([{
        "unit_id": "11111111-1111-4111-8111-111111111111", "unit_key": "sheet:物品位置:row:8",
        "locator": {"sheet": "物品位置", "row": 8},
    }] if kind == "answer" else [])}


def ledger_for(dataset, oracle):
    ledger = r.P2RunLedger(run_id="independent-h2diag", plan_id="independent",
                           plan_sha256="a" * 64, execution="dry_run", production_ready=False)
    for case, want in zip(dataset.cases, oracle):
        if want["error"] == "not_executed":
            continue
        error = want["error"]
        questions = [str(t.get("question") or t.get("text")) for t in case.turns] or [case.question]
        turns = []
        for index, _q in enumerate(questions):
            final = index == len(questions) - 1
            bad = bool(error and final)
            kind = "not_found" if want["number"] == 11 and not final else want["actual"]
            turns.append({"turn": index + 1, "status": "error" if bad else "ok",
                          "error_code": error if bad else None, "product": None if bad else product(kind)})
        ledger.record_scoring_case({"case_id": case.case_id, "status": "error" if error else "ok",
                                    "error_code": error, "planned_turns": len(questions), "turns": turns})
    return ledger


def tally(oracle):
    kinds, checks, errors = {}, Counter(), Counter()
    refusal = {"true": {"refused": 0, "not_refused": 0}, "false": {"refused": 0, "not_refused": 0}}
    for x in oracle:
        bucket = kinds.setdefault(x["expected"], {})
        bucket[x["actual"]] = bucket.get(x["actual"], 0) + 1
        if not x["error"]:
            refusal[str(x["should_refuse"]).lower()]["refused" if x["actual"] == "not_found" else "not_refused"] += 1
        checks.update(x["checks"])
        if x["error"]:
            errors[x["error"]] += 1
    return {"kind_matrix": kinds, "refusal_matrix": refusal, "failing_checks": dict(checks), "errors_by_code": dict(errors)}


def main():
    monkey = pytest.MonkeyPatch()
    guard = t09_network_guard.__wrapped__(monkey)
    attempts = next(guard)
    try:
        with tempfile.TemporaryDirectory(prefix="independent-diag-") as tmp:
            data, oracle = create_sealed(Path(tmp))
            ledger = ledger_for(data, oracle)
            plan = P2IngestPlan(sources=(IngestSource(path=ROOT / "fixtures/acceptance/normal/D01_物品位置表.xlsx"),
                                                IngestSource(path=ROOT / "fixtures/acceptance/normal/D04_活动策划流程.docx")))
            kwargs = dict(ingest_plan=plan, execution="dry_run", real_calls=0, binding={}, gate_config=None)
            card = r._holdout_scorecard_artifact(ledger, data, **kwargs)
            diag = card["diagnostics"]
            expected = {"schema_version": r.HOLDOUT_DIAGNOSTICS_SCHEMA_VERSION, "detail_available": True,
                        "total": 30, "ends_observed": 27, **tally(oracle),
                        "by_stratum": {s: tally([x for x in oracle if x["stratum"] == s]) for s, _ in STRATA},
                        "source_mapping": {"doc_codes_available": 2, "doc_codes_expected": 3, "doc_codes_missing": 2,
                                           "expected_cases": 20, "expected_cases_mapped": 18, "source_hit_failed_cases": 3,
                                           "by_doc_code": {"D01": {"expected_cases": 19, "source_hit_failed": 1, "mapped": True},
                                                           "D02": {"expected_cases": 1, "source_hit_failed": 1, "mapped": False},
                                                           "V99": {"expected_cases": 1, "source_hit_failed": 1, "mapped": False}}}}
            assert diag == expected, json.dumps({"actual": diag, "expected": expected}, ensure_ascii=False)
            assert (card["passed"], card["failed"], card["errors"]) == (23, 4, 3)
            assert sum(diag["errors_by_code"].values()) == card["errors"]
            raw = json.dumps(card, ensure_ascii=False)
            needles = [c.case_id for c in data.cases] + [VALUE, DOC_TEXT, FRAGMENT]
            needles += [v for c in data.cases for v in r._holdout_leak_needles(c) if len(v) >= 2]
            assert not any(n in raw for n in needles)
            print("PASS independent encrypted 30-case oracle: all six diagnostics equal, card=23/4/3, scan hits=0")
            print(json.dumps(diag, ensure_ascii=False, sort_keys=True))
            bad_shapes = {
                "CJK_kind": {"kind_matrix": {"answer": {"自由文本片段": 1}}},
                "space": {"kind_matrix": {"answer": {"free text kind": 1}}},
                "overlong": {"errors_by_code": {"A" * 65: 1}},
                "array": {"failing_checks": {"value_hit": [DOC_TEXT]}},
                "unregistered": {"unregistered": 1},
                "H2_prefix": {"kind_matrix": {"answer": {"H2-SYNTHETIC": 1}}},
                "whole_question": {"errors_by_code": {data.cases[0].question: 1}},
            }
            original = r._holdout_scorecard
            for name, shape in bad_shapes.items():
                injected = copy.deepcopy(card)
                injected["diagnostics"].update(shape)
                monkey.setattr(r, "_holdout_scorecard", lambda *_a, p=injected, **_k: p)
                fallback = r._holdout_scorecard_artifact(ledger, data, **kwargs)
                assert fallback["errors"] == 30 and fallback["passed"] == 0
                assert fallback["diagnostics"]["errors_by_code"] == {r.ERROR_HOLDOUT_SCORECARD_LEAK: 30}
                assert fallback["diagnostics"]["detail_available"] is False
                print("PASS fail-closed", name)
            monkey.setattr(r, "_holdout_scorecard", original)
            # Adversarial code-shaped prose, not a known question/answer in full.
            for name, shape, token in (
                ("ASCII_fragment", {"kind_matrix": {"answer": {FRAGMENT: 1}}}, FRAGMENT),
                ("document_text", {"failing_checks": {DOC_TEXT: 1}}, DOC_TEXT),
                ("nested_unregistered", {"source_mapping": {"reference_answer": DOC_TEXT}}, DOC_TEXT),
                ("trailing_newline", {"errors_by_code": {"SYNTHETIC_ERROR\n": 1}}, "SYNTHETIC_ERROR\n"),
            ):
                injected = copy.deepcopy(card)
                injected["diagnostics"].update(shape)
                monkey.setattr(r, "_holdout_scorecard", lambda *_a, p=injected, **_k: p)
                observed = r._holdout_scorecard_artifact(ledger, data, **kwargs)
                leaked = token in json.dumps(observed, ensure_ascii=False) or token in str(observed)
                if name == "trailing_newline":
                    leaked = "SYNTHETIC_ERROR\n" in observed.get("diagnostics", {}).get("errors_by_code", {})
                print("FAIL expected blocked but accepted" if observed["errors"] != 30 else "PASS blocked", name,
                      "errors=", observed["errors"], "token_retained=", leaked)
            monkey.setattr(r, "_holdout_scorecard", original)
            # Test generation, not just an injected diagnostic object.
            one = data.cases[0]
            one_ledger = r.P2RunLedger(run_id="independent-kind-probe", plan_id="independent",
                                     plan_sha256="a" * 64, execution="dry_run", production_ready=False)
            one_ledger.record_scoring_case({"case_id": one.case_id, "status": "ok", "planned_turns": 1,
                                          "turns": [{"turn": 1, "status": "ok", "product": product(FRAGMENT)}]})
            one_data = P2RunDataset(visibility="holdout", cases=(one,),
                                   identity={**data.identity, "case_count": 1, "strata": {"paraphrase": 1}})
            produced = r._holdout_scorecard_artifact(one_ledger, one_data, **kwargs)
            print("GENERATOR_ASCII_KIND", json.dumps(produced["diagnostics"]["kind_matrix"]),
                  "ends_observed=", produced["diagnostics"].get("ends_observed"),
                  "errors=", produced["errors"])
            abort_ledger = r.P2RunLedger(run_id="independent-aborted-analogue", plan_id="independent",
                                        plan_sha256="a" * 64, execution="dry_run", production_ready=False)
            abort_ledger.record_scoring_case({"case_id": data.cases[0].case_id, "status": "error",
                                             "error_code": "MODEL_UNAVAILABLE", "planned_turns": 1,
                                             "turns": [{"turn": 1, "status": "error", "error_code": "MODEL_UNAVAILABLE",
                                                        "product": product("service_error")}]})
            abort_card = r._holdout_scorecard_artifact(abort_ledger, data, **kwargs)
            abort_diag = abort_card["diagnostics"]
            assert abort_card["errors"] == 30 and abort_diag["ends_observed"] == 0
            assert abort_diag["errors_by_code"] == {"MODEL_UNAVAILABLE": 1, "not_executed": 29}
            assert abort_diag["kind_matrix"] == {"answer": {"service_error": 1, "not_executed": 19},
                                                 "conflict": {"not_executed": 5}, "refusal": {"not_executed": 5}}
            assert all(count == 0 for row in abort_diag["refusal_matrix"].values() for count in row.values())
            print("PASS aborted-row aggregation analogue (not run_p2 E2E): errors=30, MODEL_UNAVAILABLE=1, not_executed=29, ends_observed=0")
            assert attempts.snapshot()["external"] == []
            print("NETWORK external_attempts=0")
    finally:
        try:
            next(guard)
        except StopIteration:
            pass
        monkey.undo()


if __name__ == "__main__":
    main()

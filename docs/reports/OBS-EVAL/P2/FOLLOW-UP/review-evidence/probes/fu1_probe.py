"""Independent reviewer probe for P2 FU-1 (generic P2 path binds the *actual RAG index revision*).

Written from scratch by the independent reviewer (not the developer's test). Runs offline:
Mock chat backend, no network, no model/OCR call. All run artefacts are written OUTSIDE the
repo (under D:\\mktkb-fu-review\\runs).

Usage:
    python fu1_probe.py --root <CHECKOUT_ROOT> --label <name> --out <json>

`--root` lets the same probe run against
  * the frozen candidate checkout  D:\\mktkb-clean-93486b6   (pre-fix bytes) -> expect FAIL behaviour
  * the repaired working tree      D:\\GPT项目\\市场部AI知识库  (post-fix bytes) -> expect PASS behaviour
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROBE_ARGS = None


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--out", required=True)
    return parser.parse_args()


def _prepare_imports(root: Path) -> None:
    sys.path.insert(0, str(root / "backend" / "src"))


def _case(case_id: str, question: str):
    from mktkb.evaluation.dataset import CaseSpec

    return CaseSpec(
        case_id=case_id,
        suite="p2-holdout",
        split="holdout",
        stratum="paraphrase",
        business_date="2026-11-10",
        question=question,
        turns=(),
        label_version="reviewer-synthetic-v1",
    )


def _plan(cases):
    from mktkb.evaluation.p2_contracts import (
        CHAT_HOST,
        CHAT_MODEL,
        CHAT_PRICING_SOURCE,
        CHAT_PROVIDER,
        CHAT_REGION,
        P2PriceProfile,
        P2RequestItem,
        P2RunPlan,
    )

    profile = P2PriceProfile(
        kind="chat",
        model=CHAT_MODEL,
        provider=CHAT_PROVIDER,
        host=CHAT_HOST,
        region=CHAT_REGION,
        pricing_source=CHAT_PRICING_SOURCE,
        input_price_per_million_cny=2.0,
        output_price_per_million_cny=8.0,
        prompt_tokens_cap=6144,
        completion_tokens_cap=800,
    )
    items = tuple(
        P2RequestItem(
            item_id=f"{c.case_id}:turn1:answer",
            operation="answer",
            cost_center="answer_retrieval",
            case_id=c.case_id,
            turn=1,
            page=0,
            requests=1,
            price_profile=profile,
            expected_success_cny=0.001,
        )
        for c in cases
    )
    plan = P2RunPlan(
        schema_version="p2-run-plan/v0.1",
        plan_id="reviewer-fu1-probe",
        plan_version="v1",
        mode="end_to_end",
        stage="P2-LIVE",
        created_utc="2026-11-21T00:00:00+00:00",
        project_total_limit_cny=40.0,
        stage_limit_cny=20.0,
        max_requests=1000,
        cost_centers_cny={
            "answer_retrieval": 12.0,
            "ocr": 3.0,
            "judge": 3.0,
            "independent": 2.0,
        },
        items=items,
    )
    return plan, datetime(2026, 11, 21, tzinfo=timezone.utc)


def _snapshot(plan):
    from mktkb.evaluation.p2_contracts import (
        COST_CENTERS,
        P2_LEDGER_SNAPSHOT_SCHEMA_VERSION,
        P2LedgerSnapshot,
    )

    return P2LedgerSnapshot(
        schema_version=P2_LEDGER_SNAPSHOT_SCHEMA_VERSION,
        ledger_path="in-memory:reviewer-fu1",
        ledger_sha256="0" * 64,
        historical_prefix_sha256="1" * 64,
        budget_sha256="2" * 64,
        total_limit_cny=float(plan.project_total_limit_cny),
        historical_accounted_cny=15.0,
        accounted_cny=15.0,
        reservation_count=500,
        result_count=500,
        stage_allocations_cny={"S2-DEV": 3.0, "P1-RETRIEVAL": 2.0, "P2-LIVE": 20.0},
        p2_stage_accounted_cny=0.0,
        p2_center_accounted_cny={c: 0.0 for c in COST_CENTERS},
        source="in-memory",
    )


def _authorization(plan, now):
    from mktkb.evaluation.p2_authorization import preflight_p2
    from mktkb.evaluation.p2_runner import build_dry_run_authorization

    pre = preflight_p2(plan, _snapshot(plan))
    assert pre.ok, pre.reasons
    assert pre.production_ready is False
    return build_dry_run_authorization(plan, pre, now=now, nonce="7a" * 16)


def _dataset(cases):
    from mktkb.evaluation.product_adapter import P2RunDataset

    strata: dict[str, int] = {}
    for c in cases:
        strata[c.stratum] = strata.get(c.stratum, 0) + 1
    return P2RunDataset(
        visibility="public",
        cases=cases,
        identity={
            "dataset_version": "reviewer-fu1-synthetic",
            "label_version": "reviewer-synthetic-v1",
            "suite": "p2-holdout",
            "manifest_sha256": "c" * 64,
            "case_count": len(cases),
            "strata": strata,
        },
    )


def _ingest(root: Path):
    """Same real-world shape: seed a historical version, then publish a NEW version of the
    same document through document_ref (that is what makes product revision and RAG index
    revision diverge), then ingest an unrelated document."""
    from mktkb.evaluation.product_adapter import IngestSource, P2IngestPlan

    fixtures = root / "fixtures" / "acceptance"
    d01 = fixtures / "normal" / "D01_物品位置表.xlsx"
    d04 = fixtures / "normal" / "D04_活动策划流程.docx"
    v03 = fixtures / "variants" / "V03_物品位置表_历史V1.xlsx"
    return P2IngestPlan(
        sources=(
            IngestSource(path=v03, name=d01.name),
            IngestSource(path=d01, document_ref=d01.name),
            IngestSource(path=d04),
        ),
        label="reviewer-fu1-publish-version-change",
    )


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _rows(cases, case_rows):
    from mktkb.evaluation.p2_scoring import build_gate_rows, score_public_case

    codes = {"D01_物品位置表.xlsx": "D01", "D04_活动策划流程.docx": "D04"}
    by_id = {row["case_id"]: row for row in case_rows}
    scored = [
        score_public_case(
            c,
            by_id[c.case_id],
            document_codes=codes,
            allowed_doc_codes=set(codes.values()),
        )
        for c in cases
    ]
    return build_gate_rows(cases, scored)


async def _one_run(adapter, plan, now, cases):
    from mktkb.evaluation.p2_runner import run_p2

    return await run_p2(
        plan,
        adapter=adapter,
        authorization=_authorization(plan, now),
        now=now,
        gate_config=_load_config(),
    )


def _load_config():
    from mktkb.evaluation.p2_scoring import load_p2_gate_config

    return load_p2_gate_config()


def _trace_of(adapter, trace_id: str):
    found = adapter.app.state.trace_repo.get(trace_id)
    assert found, trace_id
    return found[0]


async def scenario_positive(root: Path, work: Path) -> dict[str, Any]:
    from mktkb.evaluation.p2_scoring import (
        binding_config_hash,
        build_gate_run,
        evaluate_p2_hard_gates,
    )
    from mktkb.evaluation.product_adapter import (
        MockChatBackend,
        ProductEvalAdapter,
    )

    cases = (
        _case("R01", "把城东店和城西店的宣传海报记录都列出来"),
        _case("R02", "活动策划需要哪些步骤？"),
    )
    plan, now = _plan(cases)
    adapter = ProductEvalAdapter(
        work / "positive",
        chat=MockChatBackend(),
        dataset=_dataset(cases),
        ingest_plan=_ingest(root),
    )
    out: dict[str, Any] = {"scenario": "positive"}
    try:
        result = await _one_run(adapter, plan, now, cases)
        out["run_status"] = result.status
        out["stop_code"] = result.stop_code
        product_revision = adapter.product_revision()
        index_status = adapter.index_status()
        index_revision = index_status.get("index_revision")
        out["product_revision"] = product_revision
        out["index_status_index_revision"] = index_revision
        out["counters_differ"] = product_revision != index_revision
        run_dir = adapter.paths.run_dir
        manifest = _read_json(run_dir / "run_manifest.json")
        summary = _read_json(run_dir / "summary.json")
        binding = manifest["binding"]
        out["manifest_index_revision"] = manifest.get("index_revision")
        out["binding_index_revision"] = binding.get("index_revision")
        out["binding_complete"] = binding.get("complete")
        out["binding_missing"] = binding.get("missing")
        out["trace_identity_bound"] = binding.get("trace_identity_bound")
        out["manifest_equals_rag_index"] = manifest.get("index_revision") == index_revision
        out["manifest_differs_from_product"] = manifest.get("index_revision") != product_revision
        recomputed = binding_config_hash(
            dataset_version=binding["dataset_version"],
            manifest_sha256=binding["manifest_sha256"],
            label_version=binding["label_version"],
            pipeline_version=binding["pipeline_version"],
            index_revision=binding["index_revision"],
            provider=binding["provider"],
            gate_version=binding["gate_version"],
            gate_config_hash=binding["gate_config_hash"],
        )
        out["config_hash_recompute_matches"] = recomputed == binding.get("config_hash")
        out["summary_binding_equals_manifest_binding"] = summary["binding"] == binding
        traces = []
        for case_row in _read_jsonl(run_dir / "cases.jsonl"):
            for turn in case_row.get("turns") or []:
                trace = _trace_of(adapter, turn["trace_id"])
                traces.append(
                    {
                        "case_id": case_row["case_id"],
                        "turn": turn.get("turn"),
                        "path": getattr(trace, "path", None),
                        "index_revision": getattr(trace, "index_revision", None),
                        "config_hash_matches_binding": str(getattr(trace, "config_hash", None))
                        == str(binding.get("config_hash")),
                    }
                )
        out["traces"] = traces
        out["all_traces_equal_manifest"] = all(
            str(t["index_revision"]) == str(manifest.get("index_revision")) for t in traces
        )
        out["trace_paths"] = sorted({t["path"] for t in traces})
        rows = _rows(cases, _read_jsonl(run_dir / "cases.jsonl"))
        hard = evaluate_p2_hard_gates(
            build_gate_run(
                run_dir=run_dir,
                manifest=manifest,
                cases=cases,
                rows=rows,
                summary=summary,
            ),
            config=_load_config(),
            require_trace=True,
        )
        out["gate_trace_integrity"] = hard.gate_status.get("trace_integrity")
        out["gate_hard_failures"] = list(hard.hard_failures)
        out["gate_version_binding_failures"] = [
            f.check_id for f in hard.failures if f.check_id == "version_binding"
        ]
        out["gate_exit_code"] = hard.exit_code

        # Negative: tamper the manifest back to the product count and to an arbitrary value.
        neg = []
        for wrong in (product_revision, 99):
            tampered = dict(manifest, index_revision=wrong)
            tampered["binding"] = dict(binding, index_revision=wrong)
            g = evaluate_p2_hard_gates(
                build_gate_run(
                    run_dir=run_dir,
                    manifest=tampered,
                    cases=cases,
                    rows=rows,
                    summary=summary,
                ),
                config=_load_config(),
                require_trace=True,
            )
            mismatch = [f for f in g.failures if f.check_id == "version_binding"]
            neg.append(
                {
                    "wrong_value": wrong,
                    "trace_integrity": g.gate_status.get("trace_integrity"),
                    "version_binding_rows": len(mismatch),
                    "mismatched_fields": sorted(
                        {name for f in mismatch for name in f.evidence.get("mismatched", [])}
                    ),
                    "exit_code": g.exit_code,
                }
            )
        out["negative_tamper"] = neg
    finally:
        await adapter.close()
    return out


async def scenario_unavailable(work: Path, root: Path) -> dict[str, Any]:
    from mktkb.evaluation.p2_scoring import P2ScoringError, build_gate_run
    from mktkb.evaluation.product_adapter import MockChatBackend, ProductEvalAdapter

    cases = (_case("U01", "把城东店和城西店的宣传海报记录都列出来"),)
    plan, now = _plan(cases)
    adapter = ProductEvalAdapter(
        work / "unavailable",
        chat=MockChatBackend(),
        dataset=_dataset(cases),
        ingest_plan=_ingest(root),
    )
    out: dict[str, Any] = {"scenario": "index_version_unavailable"}
    real_status = adapter.index_status
    adapter.index_status = lambda: {**real_status(), "ready": False}  # type: ignore[method-assign]
    try:
        result = await _one_run(adapter, plan, now, cases)
        run_dir = adapter.paths.run_dir
        manifest = _read_json(run_dir / "run_manifest.json")
        binding = manifest["binding"]
        out["run_status"] = result.status
        out["manifest_index_revision"] = manifest.get("index_revision")
        out["binding_complete"] = binding.get("complete")
        out["binding_missing"] = binding.get("missing")
        out["binding_config_hash"] = binding.get("config_hash")
        out["trace_identity_bound"] = binding.get("trace_identity_bound")
        half = []
        for case_row in _read_jsonl(run_dir / "cases.jsonl"):
            for turn in case_row.get("turns") or []:
                trace = _trace_of(adapter, turn["trace_id"])
                half.append(
                    {
                        name: getattr(trace, name, "n/a")
                        for name in (
                            "run_id",
                            "config_hash",
                            "manifest_sha256",
                            "pipeline_version",
                            "index_revision",
                        )
                    }
                )
        out["trace_identity_fields"] = half
        try:
            build_gate_run(
                run_dir=run_dir,
                manifest=manifest,
                cases=cases,
                rows=_rows(cases, _read_jsonl(run_dir / "cases.jsonl")),
            )
            out["gate_rejects_incomplete_manifest"] = False
            out["gate_reject_reason"] = None
        except P2ScoringError as exc:
            out["gate_rejects_incomplete_manifest"] = True
            out["gate_reject_reason"] = str(exc)[:160]
    finally:
        await adapter.close()
    return out


async def scenario_drift(work: Path, root: Path) -> dict[str, Any]:
    from mktkb.evaluation.product_adapter import MockChatBackend, ProductEvalAdapter

    cases = (
        _case("D01", "把城东店和城西店的宣传海报记录都列出来"),
        _case("D02", "活动策划需要哪些步骤？"),
    )
    plan, now = _plan(cases)
    adapter = ProductEvalAdapter(
        work / "drift",
        chat=MockChatBackend(),
        dataset=_dataset(cases),
        ingest_plan=_ingest(root),
    )
    real_ask = adapter.ask_turn
    seen: list[str] = []

    async def ask_then_mutate(question: str, **kwargs: Any):
        product = await real_ask(question, **kwargs)
        seen.append(question)
        index = adapter.app.state.qa.index()
        index.remove_document(index.list_documents()[0]["doc_id"])
        return product

    adapter.ask_turn = ask_then_mutate  # type: ignore[method-assign]
    out: dict[str, Any] = {"scenario": "index_drift_mid_run"}
    try:
        result = await _one_run(adapter, plan, now, cases)
        run_dir = adapter.paths.run_dir
        summary = _read_json(run_dir / "summary.json")
        out["run_status"] = result.status
        out["stop_code"] = result.stop_code
        out["asks_issued"] = len(seen)
        out["failure"] = summary.get("failure")
        out["binding_index_revision"] = (summary.get("binding") or {}).get("index_revision")
        out["request_lines"] = len(_read_jsonl(run_dir / "requests.jsonl"))
        case_rows = _read_jsonl(run_dir / "cases.jsonl")
        out["turns_emitted"] = sum(len(r.get("turns") or []) for r in case_rows)
        out["cases_emitted"] = len(case_rows)
    finally:
        await adapter.close()
    return out


async def main() -> int:
    args = _args()
    root = Path(args.root).resolve()
    _prepare_imports(root)
    work = Path(tempfile.mkdtemp(prefix=f"fu1-probe-{args.label}-"))
    report: dict[str, Any] = {
        "probe": "reviewer-fu1",
        "label": args.label,
        "checkout_root": str(root),
        "work_dir": str(work),
        "python": sys.version.split()[0],
        "scenarios": [],
    }
    report["scenarios"].append(await scenario_positive(root, work))
    report["scenarios"].append(await scenario_unavailable(work, root))
    report["scenarios"].append(await scenario_drift(work, root))
    Path(args.out).write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"label": args.label, "scenarios": [s["scenario"] for s in report["scenarios"]]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

r"""T206-PRE 独立验收探针（verify-t206-pre）。

只读运行：全 Mock、隔离临时目录、不联网、不读 .env/H1/H2、不写仓库（stdout 输出）。
证伪优先：
  1) 绑定 run 的 trace 六字段是否真与 manifest 同源、trace_integrity 是否真 pass；
  2) 未绑身份时六字段全 None；清单原生被拒；伪造"清单有身份、trace 没有"必须 fail；
  3) 引用证据是否回查产品库成立（不是自造），无证据/未核实保持 unknown；
  4) config_hash 两次 run 相同、run_id 不入摘要、索引变更即变、缺组件拒绝；
  5) 失败路径是否真写四件产物、status/failure/network/providers 如实；
  6) run_id 空/非 str 是否在建目录与 start 之前拒绝；自定义 run_id 是否贯穿 manifest/trace；
  7) trace_identity contextvar：六字段齐全才落、快照语义、退出不泄漏、未知/空值拒绝。

用法（仓库根）：
  .venv\Scripts\python.exe -B -X utf8 <this> > 01-probe-output.json
"""
from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import uuid
from pathlib import Path

_here = Path(__file__).resolve()
REPO = _here
while not (REPO / "backend" / "src").is_dir():
    REPO = REPO.parent
sys.path.insert(0, str(REPO / "backend" / "src"))
sys.path.insert(0, str(REPO / "backend" / "tests" / "evaluation"))

import test_p2_runner as H  # noqa: E402  - 只复用夹具构造
from mktkb.evaluation.p2_runner import P2RunError, run_p2  # noqa: E402
from mktkb.evaluation.p2_scoring import (  # noqa: E402
    P2ScoringError,
    binding_config_hash,
    build_gate_rows,
    build_gate_run,
    citation_evidence_status,
    evaluate_p2_hard_gates,
    load_p2_gate_config,
    score_public_case,
)
from mktkb.evaluation.product_adapter import MockChatBackend, ProductEvalAdapter  # noqa: E402
from mktkb.observability import (  # noqa: E402
    current_trace_identity,
    pipeline_version,
    start_trace,
    trace_identity,
)
from mktkb.observability.store import TraceRepository  # noqa: E402

DOCUMENT_CODES = {H.D01.name: "D01", H.D04.name: "D04"}
SIX = ("run_id", "dataset_version", "pipeline_version", "index_revision", "manifest_sha256", "config_hash")


def adapter_for(root: Path, cases, cls=ProductEvalAdapter):
    return cls(root, chat=MockChatBackend(), dataset=H.make_dataset(cases), ingest_plan=H.make_ingest_plan())


def gate_eval(run_dir, manifest, cases, case_rows, summary):
    scored = [
        score_public_case(c, r, document_codes=DOCUMENT_CODES, allowed_doc_codes=set(DOCUMENT_CODES.values()))
        for c, r in zip(cases, case_rows)
    ]
    rows = build_gate_rows(cases, scored)
    gate_run = build_gate_run(run_dir=run_dir, manifest=dict(manifest), cases=cases, rows=rows, summary=summary)
    return evaluate_p2_hard_gates(gate_run, config=load_p2_gate_config(), require_trace=True)


def evidence_db_check(adapter, case_rows):
    from sqlalchemy import select
    from mktkb.documents.models import Document, DocumentVersion, SourceUnit

    ingested = {str(r.document_id) for r in adapter.ingest_receipts}
    db = adapter.app.state.db.session()
    checked = []
    try:
        for row in case_rows:
            for turn in row["turns"]:
                product = turn.get("product") or {}
                if product.get("kind") != "answer":
                    continue
                source_ids = {str(s.get("source_id")) for s in product.get("sources") or ()}
                ev_ids = {str(e.get("unit_id")) for e in product.get("evidence") or ()}
                for item in product.get("evidence") or ():
                    found = db.execute(
                        select(SourceUnit, DocumentVersion, Document)
                        .join(DocumentVersion, SourceUnit.version_id == DocumentVersion.id)
                        .join(Document, SourceUnit.document_id == Document.id)
                        .where(SourceUnit.id == uuid.UUID(str(item["unit_id"])))
                    ).first()
                    unit, version, document = found
                    checked.append({
                        "unit_id_is_source_id": str(item["unit_id"]) in source_ids,
                        "evidence_covers_sources": ev_ids == source_ids,
                        "document_id_matches_db": str(item["document_id"]) == str(document.id),
                        "version_id_matches_db": str(item["version_id"]) == str(version.id),
                        "version_number_matches_db": int(item["version_number"]) == int(version.number),
                        "db_state": str(version.state),
                        "db_active": str(document.active_version_id) == str(version.id),
                        "db_locator_nonempty": bool(dict(unit.locator or {})),
                        "document_in_run": str(document.id) in ingested,
                        "verified": item.get("verified"),
                    })
    finally:
        db.close()
    return checked


def trace_context_checks(path: Path) -> dict:
    six = {
        "run_id": "p2run-unit",
        "dataset_version": "ds-v1",
        "index_revision": 4,
        "manifest_sha256": "ab" * 32,
        "pipeline_version": "pipe-1",
        "config_hash": "cd" * 32,
    }
    repo = TraceRepository(path)
    try:
        def finish(cm):
            trace = cm.__enter__()
            cm.__exit__(None, None, None)
            return trace

        # 1) 无身份 → 六字段 None
        t0 = finish(start_trace(http_request_id="h0", mode="local", scope="end_to_end", repo=repo))
        rec0, _ = repo.get(t0.trace_id)

        # 2) 六字段齐全 → 六字段全落
        with trace_identity(**six):
            t1 = finish(start_trace(http_request_id="h1", mode="local", scope="end_to_end", repo=repo))
        rec1, _ = repo.get(t1.trace_id)

        # 3) 快照语义：trace 先建、身份后设 → 不得追写
        cm = start_trace(http_request_id="h2", mode="local", scope="end_to_end", repo=repo)
        t2 = cm.__enter__()
        with trace_identity(**six):
            pass
        cm.__exit__(None, None, None)
        rec2, _ = repo.get(t2.trace_id)

        # 4) 身份先设、trace 后建、身份先退出 → 快照仍生效
        with trace_identity(**six):
            cm3 = start_trace(http_request_id="h3", mode="local", scope="end_to_end", repo=repo)
            t3 = cm3.__enter__()
        cm3.__exit__(None, None, None)
        rec3, _ = repo.get(t3.trace_id)

        # 5) 退出后不泄漏
        leaked = current_trace_identity()

        # 6) 非法输入 fail closed
        rejects = {}
        for label, kwargs in (
            ("unknown_field", {**six, "not_a_field": "x"}),
            ("empty_value", {**six, "run_id": "  "}),
            ("bool_value", {**six, "index_revision": True}),
        ):
            try:
                with trace_identity(**kwargs):
                    pass
                rejects[label] = "ACCEPTED(bad)"
            except ValueError as exc:
                rejects[label] = f"ValueError: {exc}"

        return {
            "no_identity_six": {name: getattr(rec0, name) for name in SIX},
            "with_identity_six": {name: getattr(rec1, name) for name in SIX},
            "late_identity_not_applied": {name: getattr(rec2, name) for name in SIX},
            "snapshot_survives_exit": {name: getattr(rec3, name) for name in SIX},
            "identity_after_exit": leaked,
            "invalid_inputs": rejects,
        }
    finally:
        repo.close()


async def bound_run(root: Path, config) -> dict:
    cases = (H.make_case("P01", H.RAG_QUESTION), H.make_case("P03", H.LEGACY_QUESTION))
    plan = H.make_plan(cases)
    authorization = H.dry_run_authorization(plan)
    adapter = adapter_for(root, cases)
    try:
        result = await run_p2(plan, adapter=adapter, authorization=authorization, now=H.NOW, gate_config=config)
        run_dir = adapter.paths.run_dir
        manifest = H.read_json(run_dir / "run_manifest.json")
        summary = H.read_json(run_dir / "summary.json")
        gate_payload = H.read_json(run_dir / "gate.json")
        case_rows = H.read_jsonl(run_dir / "cases.jsonl")
        traces = []
        for row in case_rows:
            for turn in row["turns"]:
                trace, _spans = adapter.trace_of(turn["trace_id"])
                traces.append({name: getattr(trace, name) for name in SIX})
        expected = {
            "run_id": manifest["run_id"],
            "dataset_version": manifest["dataset_version"],
            "pipeline_version": manifest["pipeline_version"],
            "index_revision": manifest["index_revision"],
            "manifest_sha256": manifest["corpus_manifest_sha256"],
            "config_hash": manifest["config_hash"],
        }
        hard = gate_eval(run_dir, manifest, cases, case_rows, summary)
        gate_failures = [f.to_dict() for f in hard.failures if f.gate_id == "trace_integrity"]
        return {
            "status": result.status,
            "manifest": manifest,
            "summary": summary,
            "case_rows": case_rows,
            "case_ids": [c.case_id for c in cases],
            "manifest_run_id": manifest["run_id"],
            "config_hash": manifest["config_hash"],
            "binding": manifest["binding"],
            "traces": traces,
            "trace_fields_equal_manifest": all(
                str(t[name]) == str(expected[name]) for t in traces for name in SIX
            ),
            "trace_integrity": hard.gate_status["trace_integrity"],
            "trace_integrity_failures": gate_failures,
            "hard_failures": list(hard.hard_failures),
            "hard_failure_details": [f.to_dict() for f in hard.failures],
            "gate_artifact_validation_ok": gate_payload["artifact_validation"]["ok"],
            "requests_run_ids": sorted({row.get("run_id") for row in H.read_jsonl(run_dir / "requests.jsonl")}),
            "case_rows_have_evidence": all(
                "evidence" in (turn.get("product") or {}) for row in case_rows for turn in row["turns"]
            ),
            "hard_gate_status": dict(hard.gate_status),
            "citation_evidence": citation_evidence_status(case_rows),
            "summary_citation_complete": summary["citation_evidence"]["complete"],
            "gate_citation_complete": gate_payload["citation_evidence"]["complete"],
            "evidence_db_check": (evidence_db_check(adapter, case_rows)),
            "network": summary["network"],
            "providers_nonnull": summary["providers"] is not None,
            "real_requests": summary["requests"]["real_requests"],
            "billed_cny": summary["requests"]["billed_cny"],
            "adapter_outbound": adapter.provider_calls()["outbound_network"],
            "run_dir": str(run_dir),
            "trace_ctx": (trace_context_checks(root.parent / (root.name + "-unit.sqlite3"))),
        }
    finally:
        await adapter.close()


async def second_run(root: Path, config, run_id: str):
    cases = (H.make_case("P01", H.RAG_QUESTION),)
    plan = H.make_plan(cases)
    authorization = H.dry_run_authorization(plan)
    adapter = adapter_for(root, cases)
    try:
        result = await run_p2(
            plan, adapter=adapter, authorization=authorization, now=H.NOW, gate_config=config, run_id=run_id
        )
        manifest = H.read_json(adapter.paths.run_dir / "run_manifest.json")
        case_rows = H.read_jsonl(adapter.paths.run_dir / "cases.jsonl")
        traces = []
        for row in case_rows:
            for turn in row["turns"]:
                trace, _spans = adapter.trace_of(turn["trace_id"])
                traces.append({name: getattr(trace, name) for name in SIX})
        hard = gate_eval(adapter.paths.run_dir, manifest, cases, case_rows, H.read_json(adapter.paths.run_dir / "summary.json"))
        return {
            "status": result.status,
            "run_id": manifest["run_id"],
            "config_hash": manifest["config_hash"],
            "trace_run_ids": [t["run_id"] for t in traces],
            "request_run_ids": sorted({row.get("run_id") for row in H.read_jsonl(adapter.paths.run_dir / "requests.jsonl")}),
            "trace_integrity": hard.gate_status["trace_integrity"],
        }
    finally:
        await adapter.close()


async def unbound_run(root: Path, config) -> dict:
    cases = (H.make_case("P01", H.LEGACY_QUESTION),)
    plan = H.make_plan(cases)
    authorization = H.dry_run_authorization(plan)
    adapter = adapter_for(root, cases)
    try:
        result = await run_p2(plan, adapter=adapter, authorization=authorization, now=H.NOW)
        run_dir = adapter.paths.run_dir
        manifest = H.read_json(run_dir / "run_manifest.json")
        summary = H.read_json(run_dir / "summary.json")
        case_rows = H.read_jsonl(run_dir / "cases.jsonl")
        trace, _ = adapter.trace_of(case_rows[0]["turns"][0]["trace_id"])
        six = {name: getattr(trace, name) for name in SIX}

        native = None
        try:
            gate_eval(run_dir, manifest, cases, case_rows, summary)
            native = "ACCEPTED(bad)"
        except P2ScoringError as exc:
            native = {"code": exc.code, "message": str(exc)}

        forged = dict(manifest)
        forged.update({
            "index_revision": 2,
            "pipeline_version": pipeline_version(),
            "config_hash": "de" * 32,
            "gate_version": config.gate_version,
            "gate_config_hash": config.config_hash,
        })
        hard = gate_eval(run_dir, forged, cases, case_rows, summary)
        return {
            "status": result.status,
            "binding_complete": manifest["binding"]["complete"],
            "binding_missing": manifest["binding"]["missing"],
            "binding_config_hash": manifest["binding"]["config_hash"],
            "manifest_config_hash": manifest["config_hash"],
            "manifest_index_revision": manifest["index_revision"],
            "trace_six": six,
            "all_six_none": all(v is None for v in six.values()),
            "native_build_gate_run": native,
            "forged_trace_integrity": hard.gate_status["trace_integrity"],
            "forged_hard_failures": list(hard.hard_failures),
            "forged_version_binding": [
                f.to_dict() for f in hard.failures
                if f.gate_id == "trace_integrity" and f.check_id == "version_binding"
            ],
        }
    finally:
        await adapter.close()


async def failure_run(root: Path) -> dict:
    cases = (H.make_case("P01", H.LEGACY_QUESTION),)
    plan = H.make_plan(cases)
    authorization = H.dry_run_authorization(plan)
    adapter = adapter_for(root, cases, H._TopLevelOnlyAdapter)
    try:
        try:
            await run_p2(plan, adapter=adapter, authorization=authorization, now=H.NOW)
            raised = None
        except P2RunError as exc:
            raised = {
                "code": exc.code,
                "detail": exc.detail,
                "message_starts_with_code": str(exc).startswith(exc.code),
                "is_value_error": isinstance(exc, ValueError),
            }
        run_dir = adapter.paths.run_dir
        files = sorted(p.name for p in run_dir.iterdir())
        result = H.read_json(run_dir / "run_result.json")
        summary = H.read_json(run_dir / "summary.json")
        gate_payload = H.read_json(run_dir / "gate.json")
        manifest = H.read_json(run_dir / "run_manifest.json")
        return {
            "raised": raised,
            "files": files,
            "four_products_present": all(
                (run_dir / name).is_file()
                for name in ("run_manifest.json", "summary.json", "run_result.json", "gate.json")
            ),
            "run_ids_consistent": len({manifest["run_id"], summary["run_id"], result["run_id"], gate_payload["run_id"]}) == 1,
            "status": result["status"],
            "stop_code": result["stop_code"],
            "failure": summary["failure"],
            "network": summary["network"],
            "providers": summary["providers"],
            "artifact_validation": gate_payload["artifact_validation"],
            "real_sends_allowed": gate_payload["real_sends_allowed"],
            "gate_has_binding": "binding" in gate_payload,
        }
    finally:
        await adapter.close()


async def run_id_refusal(root: Path) -> dict:
    cases = (H.make_case("P01", H.LEGACY_QUESTION),)
    plan = H.make_plan(cases)
    authorization = H.dry_run_authorization(plan)
    out = {}
    for label, bad in (("empty", ""), ("spaces", "   "), ("int", 123)):
        adapter = adapter_for(root / f"refuse-{label}", cases)
        try:
            try:
                await run_p2(plan, adapter=adapter, authorization=authorization, now=H.NOW, run_id=bad)
                out[label] = {"raised": None}
            except P2RunError as exc:
                out[label] = {
                    "code": exc.code,
                    "is_value_error": isinstance(exc, ValueError),
                    "run_dir_created": adapter.paths.run_dir.exists(),
                    "adapter_started": bool(adapter._started),
                }
        finally:
            await adapter.close()
    return out


async def main() -> dict:
    config = load_p2_gate_config()
    with tempfile.TemporaryDirectory(prefix="p2-t206-verify-") as tmp:
        root = Path(tmp)
        a = await bound_run(root / "bound", config)
        b = await second_run(root / "second", config, "p2run-verify-custom")
        u = await unbound_run(root / "unbound", config)
        f = await failure_run(root / "failure")
        r = await run_id_refusal(root / "refusal")

    components = {
        "dataset_version": a["binding"]["dataset_version"],
        "manifest_sha256": a["binding"]["manifest_sha256"],
        "label_version": a["binding"]["label_version"],
        "pipeline_version": a["binding"]["pipeline_version"],
        "index_revision": int(a["binding"]["index_revision"]),
        "provider": a["binding"]["provider"],
        "gate_version": a["binding"]["gate_version"],
        "gate_config_hash": a["binding"]["gate_config_hash"],
    }
    recomputed = binding_config_hash(**components)
    bumped = binding_config_hash(**{**components, "index_revision": components["index_revision"] + 1})
    sensitivity = {}
    for name in components:
        probe_value = {
            "dataset_version": "p2-synthetic-v2",
            "manifest_sha256": "cc" * 32,
            "label_version": "synthetic-v2",
            "pipeline_version": "pipe-zzz",
            "index_revision": components["index_revision"] + 1,
            "provider": {"chat": {"model": "mock-chat-2"}},
            "gate_version": "mktkb.gate.v9.9",
            "gate_config_hash": "99" * 32,
        }[name]
        sensitivity[name] = binding_config_hash(**{**components, name: probe_value}) != recomputed
    missing = {}
    for name in components:
        bad = dict(components)
        bad[name] = None if name == "index_revision" else ""
        try:
            binding_config_hash(**bad)
            missing[name] = "ACCEPTED(bad)"
        except P2ScoringError as exc:
            missing[name] = exc.code

    empty_evidence = {
        "complete": citation_evidence_status(
            [{"case_id": "Q01", "turns": [{"turn": 1, "product": {"kind": "answer"}}]}]
        ),
        "unverified": citation_evidence_status(
            [{"case_id": "Q01", "turns": [{"turn": 1, "product": {
                "kind": "answer",
                "evidence": [{"unit_id": "u", "locator": {"row": 1}, "verified": False, "reason": "unit_not_found"}],
            }}]}]
        ),
        "not_found_turn": citation_evidence_status(
            [{"case_id": "Q01", "turns": [{"turn": 1, "product": {"kind": "not_found"}}]}]
        ),
        "h2_no_case_id": "H2-01" not in json.dumps(
            citation_evidence_status(
                [{"case_id": "H2-01", "turns": [{"turn": 1, "product": {"kind": "answer"}}]}],
                include_case_ids=False,
            ),
            ensure_ascii=False,
        ),
    }

    return {
        "schema": "p2-t206-pre-verify/v0.1",
        "bound": {k: v for k, v in a.items() if k not in {"case_rows", "manifest", "summary"}},
        "bound_manifest_identity": {
            name: a["manifest"].get(name) for name in (
                "suite", "dataset_version", "dataset_sha256", "corpus_manifest_sha256",
                "business_date", "index_revision", "pipeline_version", "gate_version",
                "gate_config_hash", "label_version", "case_count", "config_hash",
            )
        },
        "second_run": b,
        "unbound": u,
        "failure": f,
        "run_id_refusal": r,
        "config_hash": {
            "recomputed_matches_run": recomputed == a["config_hash"],
            "changed_after_index_bump": bumped != recomputed,
            "changed_for_each_component": sensitivity,
            "bumped_prefix": bumped[:12],
            "provider_has_no_runtime_counts": not any(
                needle in json.dumps(components["provider"]).lower()
                for needle in ("calls", "outbound", "attempt", "count", "token", "latency")
            ),
            "missing_component_codes": missing,
        },
        "citation_edge_cases": empty_evidence,
    }


if __name__ == "__main__":
    print(json.dumps(asyncio.run(main()), ensure_ascii=False, indent=2, default=str))

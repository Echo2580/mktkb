"""Formal B0 tests use public fixtures and block the send boundary."""

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

_TESTS_DIR = Path(__file__).resolve().parents[1]
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

from acceptance.support.netguard import t09_network_guard  # noqa: E402,F401
from mktkb.evaluation import cli, gate, p2_live


pytestmark = pytest.mark.usefixtures("t09_network_guard")

ROOT = Path(__file__).resolve().parents[3]
APPROVED = ROOT / "docs/evaluation/gate_v0_3_approved.json"
DRAFT = ROOT / "docs/reports/OBS-EVAL/P2/T209-PREP/b0-request-plan.draft.json"


@pytest.mark.parametrize(("config", "code"), [
    (APPROVED, "b0_plan_binding_required"),
    (Path("missing-approved-config.json"), "gate_config_unreadable"),
])
def test_explicit_config_refuses_unbound_plan_before_live_gate(config, code, tmp_path, monkeypatch, capsys):
    async def fail_if_sent(*args, **kwargs):
        pytest.fail("unbound plan reached live execution")

    monkeypatch.setattr(p2_live, "run_live_p2", fail_if_sent)
    assert cli.main([
        "p2-run", "--mode", "live", "--run-id", "synthetic-b0", "--plan", str(DRAFT),
        "--gate-config", str(config), "--out", str(tmp_path / "run"),
    ]) == cli.EXIT_DATA
    captured = capsys.readouterr()
    assert code in captured.err + captured.out
    assert not (tmp_path / "run").exists()


def test_existing_plan_hash_is_unchanged_and_official_run_id_is_bound():
    from mktkb.evaluation.p2_b0 import build_b0_plan_binding
    from mktkb.evaluation.p2_contracts import P2RunPlan

    raw = json.loads(DRAFT.read_text(encoding="utf-8"))
    plan = P2RunPlan.from_dict(raw)
    assert plan.plan_sha256 == "4362968a16a8ca4624396d808e5ffbefcb916dbbf369cf4e43a31abef2651e1f"
    first = P2RunPlan.from_dict({**raw, "b0_binding": build_b0_plan_binding("synthetic-b0")})
    second = P2RunPlan.from_dict({**raw, "b0_binding": build_b0_plan_binding("synthetic-b1")})
    assert first.as_dict()["b0_binding"]["run_id"] == "synthetic-b0"
    assert first.plan_sha256 != second.plan_sha256


def test_approved_gate_is_protected_from_proposal(monkeypatch, tmp_path):
    protected = tmp_path / APPROVED.name
    raw = APPROVED.read_bytes()
    protected.write_bytes(raw)
    monkeypatch.setattr(gate, "P2_APPROVED_GATE_CONFIG_PATH", protected)
    proposal = object.__new__(gate.GateProposal)
    with pytest.raises(ValueError, match="不得用校准提案覆盖"):
        gate.write_gate_proposal(proposal, protected, overwrite=True)
    assert protected.read_bytes() == raw


@pytest.fixture
def synthetic_run(tmp_path):
    """Use the product runner's serializers and an isolated trace DB; no gate is opened."""
    from mktkb.evaluation.dataset import dataset_version
    from mktkb.evaluation.p2_b0 import (
        B0_BUSINESS_DATE, B0_CASES_SHA256, B0_LABEL_VERSION, build_b0_plan_binding,
        frozen_b0_cases, frozen_b0_corpus, load_approved_b0_config, sha256,
    )
    from mktkb.evaluation.p2_contracts import P2_AUTHORIZATION_SCHEMA_VERSION, P2Authorization, P2RunPlan
    from mktkb.evaluation.p2_runner import P2RunLedger, _attempt_audit, _binding_state, _write_artifacts
    from mktkb.evaluation.product_adapter import IngestReceipt, P2RunDataset, ProductPaths
    from mktkb.observability.contracts import SpanRecord, TraceRecord, required_spans
    from mktkb.observability.store import TraceRepository
    from mktkb.observability.versioning import pipeline_version

    run_id = "synthetic-b0"
    paths = ProductPaths.of(tmp_path / "synthetic")
    paths.run_dir.mkdir(parents=True)
    config = load_approved_b0_config(APPROVED)
    plan = P2RunPlan.from_dict({**json.loads(DRAFT.read_bytes()), "b0_binding": build_b0_plan_binding(run_id)})
    cases = frozen_b0_cases()
    dataset = P2RunDataset("public", cases, {
        "dataset_version": dataset_version(cases, B0_LABEL_VERSION), "label_version": B0_LABEL_VERSION,
        "manifest_sha256": B0_CASES_SHA256, "suite": "b0", "case_count": len(cases),
    })
    corpus = frozen_b0_corpus()
    slots = {source["name"]: f"doc-{i:02d}" for i, source in enumerate(corpus, 1)}
    ingest = [
        IngestReceipt(source["upload_name"], source["sha256"], slots[source["name"]], f"version-{index:02d}",
                      "succeeded", source["publish"], index, 202, 200 if source["publish"] else None)
        for index, source in enumerate(corpus, 1)
    ]
    active = {}
    version_counts = {}
    for item, receipt in zip(corpus, ingest, strict=True):
        name = item["name"]
        version_counts[name] = version_counts.get(name, 0) + 1
        if receipt.published:
            active[name] = (receipt.document_id, receipt.version_id, version_counts[name])
    adapter = SimpleNamespace(
        paths=paths, ingest_receipts=ingest, trace_enabled=True, trace_content_mode="hash",
        trace_identity_bound=True, rag_business_date=B0_BUSINESS_DATE,
        index_status=lambda: {"provider_mode": "live"},
        binding_components=lambda: {"pipeline_version": pipeline_version(), "index_revision": 11,
                                    "provider": {"chat": {"provider": "deepseek", "model": "deepseek-flash"}}},
    )
    binding = _binding_state(adapter, dataset, run_id, config)
    now = datetime.now(timezone.utc)
    authorization = P2Authorization(
        P2_AUTHORIZATION_SCHEMA_VERSION, plan.stage, plan.plan_id, plan.plan_sha256,
        "synthetic-go-reference", "a" * 64, 20, "synthetic-owner", now - timedelta(minutes=1),
        now + timedelta(minutes=40), "synthetic-ledger-reference", "b" * 64, "c" * 64,
        plan.stage_limit_cny, plan.stage_limit_cny, dict(plan.cost_centers_cny), dict(plan.cost_centers_cny),
        "unlimited", 0, "unlimited", 1.0, plan.operations, True,
    )
    ledger = P2RunLedger(run_id, plan.plan_id, plan.plan_sha256, "live", True, plan.total_requests)
    ledger.reserved = ledger.settled_success = 40
    ledger.by_operation = {"answer": 40}
    codes = {name[:3]: name for name in slots}
    paths.trace_db.parent.mkdir(parents=True)
    with TraceRepository(paths.trace_db) as traces:
        for case in cases:
            key = case.case_id
            item = next(i for i in plan.items if i.operation == "answer" and i.case_id == key)
            trace_id = f"trace-{key}"
            ref = case.expected_sources[0]
            locator = dict(ref.get("locator") or {"page": 1})
            unit = f"unit-{key}"
            doc_name = codes[ref["doc_code"]]
            doc_id, version_id, version_number = active[doc_name]
            source = {"source_id": unit, "document_name": doc_name, "locator": locator}
            proof = {"unit_id": unit, "unit_key": ref.get("unit_key"), "locator": locator, "verified": True,
                     "document_id": doc_id, "version_id": version_id, "version_number": version_number,
                     "state": "published", "active": True, "in_run": True}
            product = {
                "trace_id": trace_id, "trace_status": "ok", "trace_path": "legacy", "replayed": False,
                "http_status": 200, "kind": "answer", "text": case.reference_answer,
                "question_sha256": sha256(case.question.encode("utf-8")), "client_request_id": f"request-{key}",
                "sources": [source], "retrieved": [{"unit_ids": [unit], "document_name": doc_name}],
                "evidence": [proof],
            }
            ticket = {"plan_sha256": plan.plan_sha256, "plan_id": plan.plan_id, "case_id": key, "turn": 1,
                      "reservation_id": f"reservation-{key}", "operation": "answer", "nonce_len": 20,
                      "item_id": item.item_id, "provider": item.price_profile.provider,
                      "model": item.price_profile.model}
            turn = {"turn": 1, "status": "ok", "error_code": None, "ticket": ticket, "product": product,
                    "trace_id": trace_id, "item_id": item.item_id, "kind": "answer", "trace_path": "legacy"}
            ledger.cases.append({
                "schema_version": "p2-run-case/v0.1", "run_id": run_id, "case_id": key, "suite": "b0",
                "stratum": case.stratum, "visibility": "public", "conversation_id": f"conv-{key}",
                "status": "ok", "error_code": None, "planned_turns": 1, "turns_executed": 1, "turns": [turn],
            })
            ledger.requests.append({
                "schema_version": "p2-run-request/v0.1", "run_id": run_id, "case_id": key, "status": "ok",
                "execution": "live", "turn": 1, "item_id": item.item_id, "ticket": ticket,
                "client_request_id": product["client_request_id"], "provider_calls": {"outbound": 1},
                "product": {"trace_id": trace_id, "question_sha256": product["question_sha256"]},
            })
            traces.write(TraceRecord(
                trace_id=trace_id, case_id=key, mode="local", scope="end_to_end", path="legacy",
                outcome_kind="answer", dataset_version=binding["dataset_version"], run_id=run_id,
                index_revision=str(binding["index_revision"]), manifest_sha256=binding["manifest_sha256"],
                pipeline_version=binding["pipeline_version"], config_hash=binding["config_hash"], status="ok",
            ), [SpanRecord(span_id=f"{trace_id}-{name}", trace_id=trace_id, name=name, status="ok")
                for name in required_spans("legacy", "answer")])
    receipts = []
    for item in plan.items:
        if item.operation in {"index_embedding", "ocr"}:
            for phase, status in (("reserve", "reserved"), ("settle", "succeeded")):
                receipts.append({
                    "item_id": item.item_id, "operation": item.operation, "case_id": item.case_id,
                    "turn": item.turn, "page": item.page, "phase": phase, "status": status,
                    "reservation_id": f"reservation-{item.item_id}", "provider": item.price_profile.provider,
                    "model": item.price_profile.model, "cost_center": item.cost_center,
                    "kind": item.price_profile.kind, "charged_cny": 0.0,
                })
    adapter.attempt_receipts = lambda: receipts
    audit, error = _attempt_audit(plan, adapter, ledger)
    assert error is None
    audit["gate_reserved"] = audit["expected_reservations"]
    result = ledger.result(status="succeeded", attempt_audit=audit)
    counts = {"chat": 40, "embedding": 1, "rerank": 0, "ocr": 12}
    calls = sum(counts.values())
    network = {"transport_outbound": counts, "mock_intercepted": 0, "outbound_attempts": calls,
               "chat_outbound_attempts": 40, "rag_provider_posts": 1, "ocr_outbound_attempts": 12}
    providers = {name: {"outbound_network": count} for name, count in counts.items()}
    providers.update(outbound_network=calls, network=network, live={"run_id": run_id, "mode": "live"})
    checks = [{"name": name, "ok": True, "detail": ""} for name in (
        "plan_identity", "stage", "not_expired", "not_before_issue", "operations", "request_cap",
        "production_ready", "live_gate",
    )]
    _write_artifacts(
        plan=plan, adapter=adapter, authorization=authorization, dataset=dataset, ledger=ledger,
        result=result, execution="live", checks=checks, planned_turns=40, executed_turns=40, duration_ms=1,
        started_utc=now.isoformat(), binding=binding, providers=providers, network=(calls, network),
        attempt_audit=audit, gate_config=config, b0_corpus=corpus,
    )
    return paths


def test_formal_b0_cli_and_archive_preserve_public_run_bytes(synthetic_run, tmp_path, capsys, monkeypatch):
    from mktkb.evaluation.baseline import archive_baseline, restore_baseline, verify_archive
    from mktkb.evaluation import p2_b0

    baseline_root = tmp_path / "registry"
    command = ["--run", str(synthetic_run.run_dir), "--gate-config", str(APPROVED)]
    assert cli.main(["baseline", "p2-admit", *command]) == 0, capsys.readouterr().err
    report = json.loads(capsys.readouterr().out)
    assert report["b0"]["passed"] >= 36 and report["b0"]["exact_passed"] == 24
    assert report["b0"]["ocr_executed"] == 8 and report["p2_release_allowed"] is False
    assert report["real_calls"] == 53
    receipt = tmp_path / "receipt.json"
    receipt.write_text(json.dumps({
        "schema_version": "mktkb.p2.b0.approval.v0.1", "scope": "t209_b0_baseline", "decision": "approved",
        "run_id": report["run_id"], "baseline_id": report["baseline_id"],
        "evidence_sha256": report["evidence_sha256"], "approver": "synthetic-owner",
        "approved_at": "2026-11-20T11:11:00+08:00", "reason": "synthetic isolated test",
    }), encoding="utf-8")
    approve = ["baseline", "p2-approve", *command, "--root", str(baseline_root), "--receipt", str(receipt)]
    original_receipt = receipt.read_bytes()
    wrong = json.loads(original_receipt)
    wrong["evidence_sha256"] = "e" * 64
    receipt.write_text(json.dumps(wrong), encoding="utf-8")
    assert cli.main(approve) == 3 and "b0_approval_receipt_mismatch" in capsys.readouterr().err
    assert not baseline_root.exists()
    receipt.write_bytes(original_receipt)
    assert cli.main(approve) == 0, capsys.readouterr().err
    assert cli.main(approve) == 3
    capsys.readouterr()
    assert cli.main(["baseline", "list", "--root", str(baseline_root)]) == 0
    assert "approved=yes" in capsys.readouterr().out
    archive_path = tmp_path / "archive"
    archive_baseline(report["baseline_id"], baseline_root, archive_path)
    with monkeypatch.context() as fixture_guard:
        fixture_guard.setattr(p2_b0, "B0_CASES_PATH", tmp_path / "outside-checkout.jsonl")
        assert verify_archive(archive_path).identity.is_p2_b0
        restored = restore_baseline(archive_path, tmp_path / "restored")
    for name in p2_b0.B0_ARTIFACTS:
        assert (Path(restored.run_dir) / name).read_bytes() == (synthetic_run.run_dir / name).read_bytes()
    assert restored.baseline.approval is not None
    assert cli.main(["baseline", "p2-diff", *command, "--root", str(tmp_path / "restored")]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["baseline_approved"] is True and result["release_allowed"] is False

    with pytest.raises(ValueError, match="b0_target_exists"):
        restore_baseline(archive_path, tmp_path / "restored")
    (archive_path / "run" / "requests.jsonl").unlink()
    with pytest.raises(ValueError, match="文件集合不符"):
        verify_archive(archive_path)


@pytest.mark.parametrize(("mutation", "code"), [
    ("mock", "b0_run_identity_invalid"),
    ("unknown_network", "b0_outbound_evidence_invalid"),
    ("missing_trace", "b0_evidence_file_missing"),
    ("incomplete", "b0_rows_incomplete"),
    ("outside_trace", "b0_trace_path_mismatch"),
    ("private", "b0_private_fields_rejected"),
    ("old_pipeline", "b0_current_pipeline_or_corpus_changed"),
    ("forged_corpus", "b0_corpus_receipt_mismatch"),
])
def test_b0_rejects_missing_or_mismatched_origin(synthetic_run, tmp_path, mutation, code):
    from mktkb.evaluation.p2_b0 import check_b0_admission, load_approved_b0_config

    root = synthetic_run.run_dir
    manifest_path = root / "run_manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    if mutation == "mock":
        manifest["execution"] = "dry_run"
    elif mutation == "unknown_network":
        summary_path = root / "summary.json"
        summary = json.loads(summary_path.read_bytes())
        summary["network"]["available"] = False
        summary_path.write_text(json.dumps(summary), encoding="utf-8")
    elif mutation == "missing_trace":
        synthetic_run.trace_db.unlink()
    elif mutation == "incomplete":
        rows = root / "cases.jsonl"
        rows.write_bytes(b"\n".join(rows.read_bytes().splitlines()[:-1]) + b"\n")
    elif mutation == "outside_trace":
        manifest["trace_store"] = str(tmp_path / "ignored.sqlite3")
    elif mutation == "private":
        manifest["formal_b0"]["private_mark"] = "synthetic-marker"
    elif mutation == "old_pipeline":
        manifest["pipeline_version"] = "stale-synthetic-version"
    else:
        manifest["ingest"][2]["document_id"] = "wrong-slot"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match=code):
        check_b0_admission(root, load_approved_b0_config(APPROVED))


def test_same_gate_version_changed_configuration_is_refused(tmp_path):
    from mktkb.evaluation.p2_b0 import load_approved_b0_config

    changed = json.loads(APPROVED.read_bytes())
    changed["notes"] = "synthetic changed config"
    path = tmp_path / "same-version.json"
    path.write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(ValueError, match="b0_gate_file_not_approved"):
        load_approved_b0_config(path)


def test_formal_read_rejects_hardlinks(tmp_path):
    from mktkb.evaluation.p2_b0 import read_member

    original = tmp_path / "evidence.json"
    original.write_text("{}", encoding="utf-8")
    linked = tmp_path / "linked.json"
    try:
        os.link(original, linked)
    except OSError as exc:
        pytest.skip(f"temporary volume does not support hard links: {exc}")
    with pytest.raises(ValueError, match="b0_link_rejected"):
        read_member(linked)


def test_formal_cli_and_direct_api_use_same_presend_validation(tmp_path, monkeypatch, capsys):
    import asyncio

    from mktkb.evaluation import p2_b0
    from mktkb.evaluation.p2_authorization import P2AuthorizationError

    run_id = "synthetic-presend"
    recipe = json.loads((ROOT / "docs/reports/OBS-EVAL/P2/T207/PM/T207-ingest-plan-R1.json").read_bytes())
    for source in recipe["sources"]:
        source["path"] = str(ROOT / source["path"])
    ingest_path = tmp_path / "ingest.json"
    ingest_path.write_text(json.dumps(recipe), encoding="utf-8")
    original = json.loads(DRAFT.read_bytes())
    plan = tmp_path / "plan.json"
    original["b0_binding"] = p2_b0.build_b0_plan_binding(run_id)
    plan.write_text(json.dumps(original), encoding="utf-8")
    calls = []
    monkeypatch.setattr(p2_live, "load_live_env", lambda *args, **kwargs: object())

    def run_to_first_await(coroutine):
        try:
            coroutine.send(None)
            pytest.fail("presend validation suspended past the guard")
        finally:
            coroutine.close()

    monkeypatch.setattr(asyncio, "run", run_to_first_await)

    def gate_guard(plan, *, run_id, now):
        calls.append((run_id, plan.plan_sha256))
        raise P2AuthorizationError("synthetic_gate_guard", "the real send gate is disabled")

    monkeypatch.setattr(p2_live, "open_live_gate", gate_guard)
    command = [
        "p2-run", "--mode", "live", "--run-id", run_id, "--plan", str(plan), "--gate-config", str(APPROVED),
        "--ingest-plan", str(ingest_path), "--cases", str(p2_b0.B0_CASES_PATH), "--out", str(tmp_path / "out"),
    ]
    assert cli.main(command) == 3
    assert "synthetic_gate_guard" in capsys.readouterr().out and len(calls) == 1
    original["b0_binding"]["pipeline_source_sha256"] = "d" * 64
    plan.write_text(json.dumps(original), encoding="utf-8")
    assert cli.main(command) == 3
    assert "b0_plan_binding_mismatch" in capsys.readouterr().err and len(calls) == 1
    assert not (tmp_path / "out").exists()

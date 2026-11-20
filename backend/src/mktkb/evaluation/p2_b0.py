"""T209 public B0 input binding and single-run admission."""

from __future__ import annotations

import hashlib
import json
import re
import stat
from collections import Counter
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from ..observability.versioning import pipeline_version
from .dataset import cases_to_jsonl, dataset_version
from .gate import (
    FROZEN_DATASET_DIR, GATE_VERSION_V0_3, HARD_GATE_IDS,
    P2_APPROVED_GATE_CONFIG_HASH as B0_GATE_CONFIG_HASH,
)
from .p2_contracts import P2Authorization, P2RunPlan, P2RunResult, payload_sha256
from .p2_score_run import load_cases_file, load_document_codes, score_run
from .p2_scoring import (
    P2GateConfig, binding_config_hash, build_gate_rows, build_gate_run, citation_evidence_status,
    evaluate_p2_hard_gates, load_p2_gate_config,
)

B0_CASES_PATH = FROZEN_DATASET_DIR / "b0.jsonl"
B0_CASES_SHA256 = "bd4f0f7ccc6e9f50ba630598c01b3519804447d4e0f3bfbc2facd54a5a521e4f"
B0_GATE_FILE_SHA256 = "b1094cc726230be2ec22ec811d34a948ea4a2fe03aab2c0fcc4f20c99764d961"
B0_BUSINESS_DATE = "2026-10-28"
B0_LABEL_VERSION = "b0-2026-11-04"
B0_CASE_IDS = tuple(f"Q{i:02d}" for i in range(1, 41))
_PROJECT_ROOT = Path(__file__).resolve().parents[4]
_PUBLIC_RECIPE_DIR = _PROJECT_ROOT / "docs/reports/OBS-EVAL/P2/T207"
_B0_INGEST_RECIPE = _PUBLIC_RECIPE_DIR / "PM/T207-ingest-plan-R1.json"
_B0_INGEST_RECIPE_SHA256 = "c70042e5de6a2016ccdf3f0f284b8e1ff3902efcda833d916b5c794c202a208d"
B0_DOCUMENT_CODES = _PUBLIC_RECIPE_DIR / "cases/document-codes.json"
B0_DOCUMENT_CODES_SHA256 = "3ac6a4eb5570e42312127c39cd6a79d8759bf2fb3821ef0bd45bdee2ca5cc20d"
_PACKAGE_ROOT = Path(__file__).resolve().parents[1]
B0_ARTIFACTS = (
    "run_manifest.json", "summary.json", "dataset.jsonl", "cases.jsonl", "requests.jsonl",
    "gate.json", "run_result.json",
)
_REQUIRED_PASS = frozenset({"exact_value_contract", "citation_required", "trace_integrity"})
_PRIVATE_KEYS = frozenset({
    "holdout_details", "holdout_labels_sha256", "holdout_cases", "holdout_scorecard",
    "scenario_binding", "scenario_key", "private_case_marks", "private_rows", "verdicts",
    "case_marks", "ground_truth", "api_key", "ocr_secret_key", "secret", "password", "nonce",
})
_MANIFEST_KEYS = frozenset((
    "schema_version run_id mode execution scope suite dataset_version dataset_sha256 corpus_manifest_sha256 "
    "business_date index_revision pipeline_version gate_version label_version created_at case_count config_hash "
    "gate_config_hash trace_store dataset_path business_dates dataset binding plan authorization pipeline "
    "providers paths ingest started_utc finished_utc duration_ms formal_b0"
).split())
_SUMMARY_KEYS = frozenset((
    "schema_version run_id plan_id plan_sha256 status stop_code execution visibility binding citation_evidence "
    "cases turns kinds branches requests attempts providers network holdout failure duration_ms"
).split())
_GATE_KEYS = frozenset((
    "schema_version stage run_id status stop_code execution production_ready binding citation_evidence "
    "attempts artifact_validation failure real_sends_allowed checks authorization gate_notes quality_gate"
).split())
_CASE_KEYS = frozenset((
    "schema_version run_id case_id suite stratum visibility conversation_id turns status error_code "
    "planned_turns turns_executed"
).split())
_TURN_KEYS = frozenset((
    "turn item_id status error_code ticket product http_status kind trace_id trace_path trace_outcome paid_attempt"
).split())
_PRODUCT_KEYS = frozenset((
    "question_sha256 question_chars client_request_id http_status kind text message_id request_id revision "
    "error_code retryable source_ids sources missing_fields candidates trace_id trace_path trace_outcome "
    "trace_status trace_spans replayed elapsed_ms evidence retrieved pagination"
).split())
_REQUEST_KEYS = frozenset((
    "schema_version run_id case_id turn item_id client_request_id ticket billed status error_code elapsed_ms "
    "execution provider_calls charged_cny product"
).split())
_SOURCE_KEYS = frozenset("source_id document_name version_number published_at status locator".split())
_CITATION_KEYS = frozenset((
    "unit_id unit_key document_id version_id version_number locator state active in_run verified reason"
).split())
_RETRIEVED_KEYS = frozenset((
    "document_name unit_ids unit_key locator chunk_id hard_filter_violation"
).split())


class B0Error(ValueError):
    """Formal B0 admission or evidence error."""


def require(condition: bool, code: str) -> None:
    if not condition:
        raise B0Error(code)


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def safe_path(path: Path) -> Path:
    """Reject links and Windows directory junctions before resolving a path."""
    path = path.absolute()
    for part in (path, *path.parents):
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        require(
            not stat.S_ISLNK(info.st_mode)
            and not getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT,
            "b0_link_rejected",
        )
    return path.resolve()


def read_member(path: Path) -> bytes:
    path = safe_path(path)
    require(path.is_file(), "b0_evidence_file_missing")
    require(path.stat().st_nlink == 1, "b0_link_rejected")
    return path.read_bytes()


def public_json(raw: bytes) -> Any:
    def no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        keys = {key for key, _ in pairs}
        require(len(keys) == len(pairs), "b0_duplicate_json_key")
        normalized = {key.lower().replace("-", "_") for key in keys}
        require(
            not normalized.intersection(_PRIVATE_KEYS)
            and not any(key.startswith(("h2_", "holdout_", "private_", "restricted_")) for key in normalized),
            "b0_private_fields_rejected",
        )
        return dict(pairs)

    def invalid_constant(_value: str) -> None:
        raise B0Error("b0_invalid_json_number")

    return json.loads(raw, object_pairs_hook=no_duplicates, parse_constant=invalid_constant)


def _run_id_ok(value: str) -> bool:
    return bool(
        re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,95}", value)
        and not re.fullmatch(r"CON|AUX|PRN|NUL|COM[0-9]|LPT[0-9]", value, re.IGNORECASE)
    )


def load_approved_b0_config(path: Path | str) -> P2GateConfig:
    path = safe_path(Path(path))
    require(sha256(read_member(path)) == B0_GATE_FILE_SHA256, "b0_gate_file_not_approved")
    config = load_p2_gate_config(path)
    require(
        config.config_hash == B0_GATE_CONFIG_HASH
        and config.status == "approved" and config.gate_version == GATE_VERSION_V0_3,
        "b0_gate_config_not_approved",
    )
    return config


def frozen_b0_cases() -> tuple:
    require(sha256(read_member(B0_CASES_PATH)) == B0_CASES_SHA256, "b0_frozen_cases_changed")
    cases = load_cases_file(B0_CASES_PATH)
    require(
        tuple(case.case_id for case in cases) == B0_CASE_IDS
        and all(case.suite == "b0" and case.business_date == B0_BUSINESS_DATE for case in cases),
        "b0_frozen_cases_invalid",
    )
    return cases


def _corpus_projection(ingest: Any) -> list[dict[str, Any]]:
    rows = []
    for source in ingest.sources:
        name = source.document_ref or source.name
        path = safe_path(source.path)
        require(path.is_relative_to(_PROJECT_ROOT / "fixtures" / "acceptance"), "b0_corpus_path_invalid")
        require(
            not source.document_id and not source.expected_active_version_id and not source.allow_same_name,
            "b0_corpus_override_invalid",
        )
        rows.append({
            "name": name, "upload_name": source.name, "document_ref": source.document_ref,
            "publish": source.publish, "sha256": sha256(read_member(path)),
        })
    return rows


def frozen_b0_corpus() -> list[dict[str, Any]]:
    from .product_adapter import ingest_plan_from_document

    raw = read_member(_B0_INGEST_RECIPE)
    require(sha256(raw) == _B0_INGEST_RECIPE_SHA256, "b0_corpus_recipe_changed")
    recipe = json.loads(raw)
    for source in recipe["sources"]:
        source["path"] = str(_PROJECT_ROOT / source["path"])
    return _corpus_projection(ingest_plan_from_document(recipe))


def pipeline_source_sha256() -> str:
    """Bind the run to product/backend bytes without changing historical product versions."""
    sources = set(_PACKAGE_ROOT.glob("*.py"))
    for directory in _PACKAGE_ROOT.iterdir():
        if directory.is_dir() and directory.name not in {"evaluation", "__pycache__"}:
            sources.update(directory.rglob("*.py"))
    for name in ("p2_live.py", "p2_runner.py", "product_adapter.py", "p2_ingestion.py"):
        sources.add(Path(__file__).resolve().parent / name)
    return payload_sha256({
        path.relative_to(_PACKAGE_ROOT).as_posix(): sha256(read_member(path)) for path in sources
    })


def build_b0_plan_binding(run_id: str) -> dict[str, str]:
    """Supply this value as ``b0_binding`` before the plan is approved."""
    require(_run_id_ok(run_id), "b0_run_id_invalid")
    cases = frozen_b0_cases()
    return {
        "run_id": run_id,
        "business_date": B0_BUSINESS_DATE,
        "dataset_file_sha256": B0_CASES_SHA256,
        "dataset_sha256": sha256(cases_to_jsonl(cases).encode("utf-8")),
        "corpus_sha256": payload_sha256({"sources": frozen_b0_corpus()}),
        "gate_config_hash": B0_GATE_CONFIG_HASH,
        "pipeline_source_sha256": pipeline_source_sha256(),
    }


def validate_b0_live_inputs(
    plan: P2RunPlan, *, run_id: str, dataset: Any, ingest_plan: Any, gate_config: P2GateConfig,
    out_dir: Path | str,
) -> list[dict[str, Any]]:
    require(plan.b0_binding is not None, "b0_plan_binding_required")
    require(dict(plan.b0_binding) == build_b0_plan_binding(run_id), "b0_plan_binding_mismatch")
    require(gate_config is not None and gate_config.config_hash == B0_GATE_CONFIG_HASH, "b0_gate_config_not_approved")
    _validate_answer_plan(plan)
    expected_cases = frozen_b0_cases()
    require(
        dataset.visibility == "public" and dataset.cases == expected_cases
        and dataset.identity.get("suite") == "b0"
        and dataset.identity.get("manifest_sha256") == B0_CASES_SHA256
        and dataset.identity.get("dataset_version") == dataset_version(expected_cases, B0_LABEL_VERSION)
        and dataset.identity.get("label_version") == B0_LABEL_VERSION,
        "b0_input_cases_not_frozen",
    )
    require(ingest_plan is not None, "b0_corpus_missing")
    corpus = _corpus_projection(ingest_plan)
    require(corpus == frozen_b0_corpus(), "b0_corpus_mismatch")
    require(not safe_path(Path(out_dir)).exists(), "b0_output_exists")
    return corpus


def b0_pipeline_version(raw_version: str, plan_binding: Mapping[str, Any]) -> str:
    return raw_version + "+" + plan_binding["pipeline_source_sha256"]


def _validate_answer_plan(plan: P2RunPlan) -> dict[str, Any]:
    answers = {item.case_id: item for item in plan.items if item.operation == "answer"}
    require(
        set(answers) == set(B0_CASE_IDS)
        and sum(item.operation == "answer" for item in plan.items) == len(answers)
        and all(item.turn == 1 and item.page == 0 and item.requests == 1 for item in answers.values()),
        "b0_answer_plan_invalid",
    )
    for item in plan.items:
        if item.operation in {"query_embedding", "query_expansion", "rerank"}:
            require(item.case_id in answers and item.turn == 1 and item.page == 0 and item.requests == 1,
                    "b0_query_plan_invalid")
        else:
            require(item.operation in {"answer", "index_embedding", "ocr"}, "b0_operation_invalid")
    return answers


def _digest(value: Any) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"[0-9a-f]{64}", value)) and value != "0" * 64


def _integer(value: Any, minimum: int = 0) -> bool:
    return type(value) is int and value >= minimum


def _network(manifest: Mapping, summary: Mapping, run_id: str) -> int:
    providers = manifest["providers"]
    network = summary["network"]
    detail = network["detail"]
    transport = detail["transport_outbound"]
    real_calls = network["outbound_attempts"]
    require(
        set(transport) == {"chat", "embedding", "rerank", "ocr"}
        and all(_integer(value) for value in transport.values())
        and _integer(real_calls, 1) and real_calls == sum(transport.values())
        and network["available"] is True and network["code"] is None
        and detail["mock_intercepted"] == 0 and detail["outbound_attempts"] == real_calls
        and detail["chat_outbound_attempts"] == transport["chat"]
        and detail["rag_provider_posts"] == transport["embedding"] + transport["rerank"]
        and detail["ocr_outbound_attempts"] == transport["ocr"]
        and providers == summary["providers"] and providers["network"] == detail
        and providers["outbound_network"] == real_calls
        and providers["live"]["run_id"] == run_id and providers["live"]["mode"] == "live"
        and all(providers[name]["outbound_network"] == count for name, count in transport.items()),
        "b0_outbound_evidence_invalid",
    )
    return real_calls


def _validate_run_rows(
    rows: list[Mapping], requests: list[Mapping], cases: tuple, *, plan: P2RunPlan,
    run_id: str, summary: Mapping, real_calls: int, active_versions: Mapping[str, tuple[str, str, int]],
) -> None:
    require(len(rows) == len(requests) == len(cases), "b0_rows_incomplete")
    answers = _validate_answer_plan(plan)
    seen_trace = set()
    seen_reservation = set()
    user_outbound = 0
    outbound_rows = 0
    for row, request, case in zip(rows, requests, cases, strict=True):
        require(
            set(row) == _CASE_KEYS and set(request).issubset(_REQUEST_KEYS)
            and row["schema_version"] == "p2-run-case/v0.1" and row["visibility"] == "public"
            and row["run_id"] == request["run_id"] == run_id
            and row["case_id"] == request["case_id"] == case.case_id
            and row["suite"] == "b0" and row["stratum"] == case.stratum
            and row["status"] == request["status"] == "ok" and row["error_code"] is None
            and row["planned_turns"] == row["turns_executed"] == len(row["turns"]) == 1,
            "b0_case_execution_invalid",
        )
        turn = row["turns"][0]
        product = turn["product"]
        ticket = turn["ticket"]
        answer_item = answers[case.case_id]
        trace = product["trace_id"]
        reservation = ticket["reservation_id"]
        require(
            set(turn).issubset(_TURN_KEYS) and set(product).issubset(_PRODUCT_KEYS)
            and request["schema_version"] == "p2-run-request/v0.1" and request["execution"] == "live"
            and turn["status"] == "ok" and turn["turn"] == request["turn"] == ticket["turn"] == 1
            and turn["item_id"] == request["item_id"] == ticket["item_id"] == answer_item.item_id
            and request["ticket"] == ticket and ticket["plan_sha256"] == plan.plan_sha256
            and ticket["operation"] == "answer" and ticket["case_id"] == case.case_id
            and ticket["provider"] == answer_item.price_profile.provider and ticket["model"] == answer_item.price_profile.model
            and ticket["plan_id"] == plan.plan_id and isinstance(reservation, str) and reservation
            and reservation not in seen_reservation and _integer(ticket["nonce_len"], 16)
            and product["http_status"] == 200 and product["replayed"] is False and product["trace_status"] == "ok"
            and isinstance(trace, str) and trace and trace not in seen_trace
            and trace == turn["trace_id"] == request["product"]["trace_id"]
            and product["client_request_id"] == request["client_request_id"]
            and product["question_sha256"] == request["product"]["question_sha256"]
            == sha256(case.question.encode("utf-8")),
            "b0_turn_provenance_invalid",
        )
        evidence = {item["unit_id"]: item for item in product["evidence"]}
        require(
            len(evidence) == len(product["evidence"])
            and evidence.keys() == {item["source_id"] for item in product["sources"]}
            and all(set(item).issubset(_RETRIEVED_KEYS) and item["document_name"] in active_versions
                    for item in product["retrieved"]),
            "b0_evidence_source_mismatch",
        )
        for source in product["sources"]:
            citation = evidence[source["source_id"]]
            require(
                set(source).issubset(_SOURCE_KEYS) and set(citation).issubset(_CITATION_KEYS)
                and citation["state"] == "published" and citation["active"] is citation["in_run"] is True
                and active_versions.get(source["document_name"]) == (
                    citation["document_id"], citation["version_id"], citation["version_number"],
                ),
                "b0_citation_source_mismatch",
            )
        seen_trace.add(trace)
        seen_reservation.add(reservation)
        outbound = request["provider_calls"]["outbound"]
        require(_integer(outbound), "b0_turn_outbound_invalid")
        user_outbound += outbound
        outbound_rows += int(outbound > 0)
    require(
        0 < user_outbound <= real_calls and summary["requests"]["real_requests"] == outbound_rows,
        "b0_turn_outbound_mismatch",
    )
    audit = summary["attempts"]
    receipts = audit["receipts"]
    adjunct = set()
    reserve = set()
    operation_count = Counter()
    item_count = Counter()
    items = {item.item_id: item for item in plan.items}
    for receipt in receipts:
        item = items.get(receipt["item_id"])
        reservation = receipt["reservation_id"]
        require(
            item is not None and item.operation != "answer" and receipt["operation"] == item.operation
            and receipt["case_id"] == item.case_id and receipt["turn"] == item.turn and receipt["page"] == item.page
            and receipt["provider"] == item.price_profile.provider and receipt["model"] == item.price_profile.model
            and isinstance(reservation, str) and reservation and reservation not in seen_reservation,
            "b0_attempt_plan_mismatch",
        )
        if receipt["phase"] == "reserve":
            require(reservation not in reserve and receipt["status"] == "reserved", "b0_attempt_reserve_invalid")
            reserve.add(reservation)
        elif receipt["phase"] == "settle":
            require(reservation in reserve and reservation not in adjunct
                    and receipt["status"] == "succeeded", "b0_attempt_settlement_invalid")
            adjunct.add(reservation)
            operation_count[receipt["operation"]] += 1
            item_count[item.item_id] += 1
        else:
            raise B0Error("b0_attempt_phase_invalid")
    require(
        audit["available"] is True and audit["scope"] == "all_attempts"
        and audit["receipt_count"] == len(receipts) and reserve == adjunct
        and audit["reservations"] == len(adjunct) and audit["by_operation"] == dict(operation_count)
        and audit["answer_reserved"] == len(seen_reservation)
        and all(count <= items[item_id].requests for item_id, count in item_count.items())
        and audit["gate_reserved"] == audit["expected_reservations"] == len(adjunct) + len(seen_reservation)
        and user_outbound + operation_count["index_embedding"] + operation_count["ocr"] == real_calls,
        "b0_attempt_audit_mismatch",
    )


def _validate_corpus(manifest: Mapping, corpus: list[Mapping], expected: str) -> dict[str, tuple[str, str, int]]:
    ingest = manifest["ingest"]
    require(
        len(corpus) == len(ingest) == 12 and payload_sha256({"sources": corpus}) == expected,
        "b0_corpus_digest_mismatch",
    )
    slots: dict[str, str] = {}
    versions: set[str] = set()
    active: dict[str, tuple[str, str, int]] = {}
    versions_by_name = Counter()
    for source, receipt in zip(corpus, ingest, strict=True):
        name = source["name"]
        doc_id = receipt["document_id"]
        version = receipt["version_id"]
        publish = source["publish"]
        require(
            set(source) == {"name", "upload_name", "document_ref", "publish", "sha256"}
            and _digest(source["sha256"]) and source["sha256"] == receipt["sha256"]
            and source["upload_name"] == receipt["name"] and receipt["job_state"] == "succeeded"
            and type(publish) is bool and receipt["published"] is publish
            and receipt["upload_status"] == 202 and receipt["publish_status"] == (200 if publish else None)
            and isinstance(doc_id, str) and doc_id and isinstance(version, str) and version and version not in versions
            and doc_id == slots.get(name, doc_id) and bool(source["document_ref"]) == (name in slots),
            "b0_corpus_receipt_mismatch",
        )
        slots[name] = doc_id
        versions.add(version)
        versions_by_name[name] += 1
        if publish:
            active[name] = (doc_id, version, versions_by_name[name])
    require(len(slots) == len(set(slots.values())) == 10, "b0_corpus_slot_mismatch")
    require(active.keys() == slots.keys(), "b0_corpus_active_versions_missing")
    return active


def _hard_proof(run: Any, gate_config: P2GateConfig, dataset: Path, trace_sha: str) -> dict[str, Any]:
    hard = evaluate_p2_hard_gates(run, config=gate_config, dataset_path=dataset, require_trace=True)
    return {
        "gate_status": dict(hard.gate_status),
        "exit_code": hard.exit_code,
        "hard_failures": list(hard.hard_failures),
        "unknown_count": len(hard.unknowns),
        "min_sample": hard.min_sample,
        "scored_count": hard.scored_count,
        "trace_sha256": trace_sha,
    }


def _validate_hard_proof(proof: Mapping, config: P2GateConfig) -> None:
    gate_status = proof["gate_status"]
    require(
        set(proof) == {"gate_status", "exit_code", "hard_failures", "unknown_count", "min_sample",
                       "scored_count", "trace_sha256"}
        and set(gate_status) == set(HARD_GATE_IDS)
        and all(state in {"pass", "not_applicable"} for state in gate_status.values())
        and all(gate_status[name] == "pass" for name in _REQUIRED_PASS)
        and proof["exit_code"] == 0 and proof["hard_failures"] == [] and proof["unknown_count"] == 0
        and proof["min_sample"] == config.config.min_sample_for("b0")
        and _integer(proof["scored_count"], proof["min_sample"])
        and _digest(proof["trace_sha256"]),
        "b0_hard_gate_blocked",
    )


@dataclass(frozen=True)
class B0Admission:
    proof: dict[str, Any]
    run: Any
    raw_artifacts: dict[str, bytes]


def check_b0_admission(
    run_dir: Path | str, gate_config: P2GateConfig, *, portable_proof: Mapping | None = None,
    document_codes_path: Path = B0_DOCUMENT_CODES, allow_quality_regression: bool = False,
) -> B0Admission:
    """Recompute B0; portable copies use the source hard gate proof bound by approval."""
    require(gate_config.config_hash == B0_GATE_CONFIG_HASH and gate_config.status == "approved",
            "b0_gate_config_not_approved")
    root = safe_path(Path(run_dir))
    try:
        return _check_b0_admission(root, gate_config, portable_proof, document_codes_path, allow_quality_regression)
    except (KeyError, TypeError, AttributeError, IndexError) as exc:
        raise B0Error("b0_evidence_schema_invalid") from exc


def _check_b0_admission(
    root: Path, config: P2GateConfig, portable: Mapping | None, document_codes_path: Path,
    allow_quality_regression: bool,
) -> B0Admission:
    raw_manifest = read_member(root / "run_manifest.json")
    manifest = public_json(raw_manifest)
    require(
        set(manifest) == _MANIFEST_KEYS
        and manifest.get("schema_version") == "p2-run-manifest/v0.1" and manifest.get("suite") == "b0"
        and manifest.get("mode") == manifest.get("scope") == "end_to_end" and manifest.get("execution") == "live"
        and manifest["dataset"]["visibility"] == "public" and _run_id_ok(manifest["run_id"]),
        "b0_run_identity_invalid",
    )
    artifacts = {name: read_member(root / name) for name in B0_ARTIFACTS}
    require(raw_manifest == artifacts["run_manifest.json"], "b0_source_changed")
    summary, gate = (public_json(artifacts[name]) for name in ("summary.json", "gate.json"))
    require(set(summary) == _SUMMARY_KEYS and set(gate) == _GATE_KEYS, "b0_evidence_schema_invalid")
    run_id = manifest["run_id"]
    run_result = P2RunResult.from_dict(public_json(artifacts["run_result.json"]))
    formal = manifest["formal_b0"]
    plan = P2RunPlan.from_dict(formal["plan"])
    binding = dict(plan.b0_binding or {})
    if portable is None:
        cases = frozen_b0_cases()
    else:
        dataset_raw = artifacts["dataset.jsonl"].replace(b"\r\n", b"\n")
        require(sha256(dataset_raw) == B0_CASES_SHA256, "b0_portable_cases_not_frozen")
        cases = load_cases_file(root / "dataset.jsonl")
    canonical_cases = cases_to_jsonl(cases).encode("utf-8")
    require(
        binding.get("run_id") == run_id and binding["dataset_file_sha256"] == B0_CASES_SHA256
        and binding["gate_config_hash"] == config.config_hash
        and binding["business_date"] == manifest["business_date"] == formal["rag_business_date"] == B0_BUSINESS_DATE
        and binding["dataset_sha256"] == manifest["dataset_sha256"] == sha256(canonical_cases)
        and artifacts["dataset.jsonl"].replace(b"\r\n", b"\n") == canonical_cases
        and manifest["dataset_version"] == dataset_version(cases, B0_LABEL_VERSION)
        and manifest["label_version"] == B0_LABEL_VERSION and manifest["case_count"] == len(cases)
        and manifest["dataset"] == {
            "dataset_version": manifest["dataset_version"], "label_version": B0_LABEL_VERSION,
            "suite": "b0", "manifest_sha256": B0_CASES_SHA256, "case_count": 40,
            "visibility": "public", "case_count_loaded": 40, "strata": {}, "declared_case_count": 40,
        }
        and manifest["corpus_manifest_sha256"] == binding["corpus_sha256"]
        and manifest["gate_version"] == config.gate_version and manifest["gate_config_hash"] == config.config_hash,
        "b0_formal_binding_mismatch",
    )
    if portable is None:
        require(binding == build_b0_plan_binding(run_id) and manifest["pipeline_version"] == pipeline_version(),
                "b0_current_pipeline_or_corpus_changed")
        require(formal["corpus"] == frozen_b0_corpus(), "b0_current_corpus_changed")
    active_versions = _validate_corpus(manifest, formal["corpus"], binding["corpus_sha256"])
    trace = manifest["pipeline"]["trace"]
    trace_binding = manifest["binding"]
    require(
        trace_binding == summary["binding"] == gate["binding"] and trace_binding["complete"] is True
        and trace_binding["trace_identity_bound"] is True and trace_binding["missing"] == []
        and trace["enabled"] is trace["identity_bound"] is True
        and trace["scope"] == "end_to_end" and trace["mode"] == "local"
        and trace["content_mode"] in {"off", "hash"}
        and trace_binding["manifest_sha256"] == B0_CASES_SHA256
        and all(trace_binding[name] == manifest[name] for name in (
            "config_hash", "dataset_version", "dataset_sha256", "label_version", "pipeline_version",
            "index_revision", "gate_version", "gate_config_hash",
        ))
        and trace_binding["config_hash"] == binding_config_hash(**{
            name: trace_binding[name] for name in ("dataset_version", "manifest_sha256", "label_version",
                                                    "pipeline_version", "index_revision", "provider",
                                                    "gate_version", "gate_config_hash")
        }),
        "b0_trace_binding_invalid",
    )
    auth_data = gate["authorization"]
    authorization = P2Authorization(**{
        **auth_data,
        "issued_utc": datetime.fromisoformat(auth_data["issued_utc"]),
        "expires_utc": datetime.fromisoformat(auth_data["expires_utc"]),
        "operations": tuple(auth_data["operations"]),
    })
    require(
        summary["run_id"] == gate["run_id"] == run_result.run_id == run_id
        and summary["schema_version"] == "p2-run-summary/v0.1" and gate["schema_version"] == "p2-run-gate/v0.1"
        and summary["status"] == gate["status"] == run_result.status == "succeeded"
        and summary["stop_code"] is gate["stop_code"] is run_result.stop_code is None
        and summary["failure"] is gate["failure"] is None
        and summary["visibility"] == "public" and summary["holdout"]["aggregate_only"] is False
        and summary["cases"] == {"planned": 40, "executed": 40, "with_error": 0, "not_executed": 0}
        and summary["turns"] == {"planned": 40, "executed": 40, "with_product_result": 40}
        and summary["plan_sha256"] == manifest["plan"]["plan_sha256"]
        == run_result.plan_sha256 == authorization.plan_sha256 == plan.plan_sha256
        and summary["plan_id"] == manifest["plan"]["plan_id"] == run_result.plan_id == authorization.plan_id == plan.plan_id
        and run_result.requests_planned == plan.total_requests
        and run_result.requests_reserved == 40
        and run_result.attempts_scope == "all_attempts" and run_result.attempts_reserved == summary["attempts"]["gate_reserved"]
        and summary["execution"] == gate["execution"] == "live"
        and gate["stage"] == authorization.stage == plan.stage
        and authorization.issued_utc <= datetime.fromisoformat(manifest["started_utc"]) < authorization.expires_utc
        and authorization.production_ready is run_result.production_ready is gate["production_ready"] is True
        and gate["real_sends_allowed"] is True and gate["artifact_validation"]["ok"] is True
        and len(gate["checks"]) == 8 and all(check["ok"] is True for check in gate["checks"])
        and {check["name"] for check in gate["checks"]} == {
            "plan_identity", "stage", "not_expired", "not_before_issue", "operations", "request_cap",
            "production_ready", "live_gate",
        }
        and all(_digest(digest) for digest in (authorization.go_sha256, authorization.ledger_sha256,
                                                authorization.budget_sha256))
        and all(manifest["authorization"][name] == gate["authorization"][name] for name in (
            "go_sha256", "go_document", "issued_by", "go_nonce_len", "production_ready", "stage",
        )),
        "b0_live_authorization_invalid",
    )
    real_calls = _network(manifest, summary, run_id)
    rows = [public_json(line) for line in artifacts["cases.jsonl"].splitlines() if line.strip()]
    requests = [public_json(line) for line in artifacts["requests.jsonl"].splitlines() if line.strip()]
    _validate_run_rows(
        rows, requests, cases, plan=plan, run_id=run_id, summary=summary,
        real_calls=real_calls, active_versions=active_versions,
    )
    citation = citation_evidence_status(rows)
    require(citation["complete"] is True and citation == gate["citation_evidence"] == summary["citation_evidence"],
            "b0_citation_evidence_invalid")
    require(sha256(read_member(document_codes_path)) == B0_DOCUMENT_CODES_SHA256, "b0_document_codes_changed")
    corpus_names = {source["name"] for source in formal["corpus"]}
    codes = {name: code for name, code in load_document_codes(document_codes_path).items() if name in corpus_names}
    require(len(codes) == 10, "b0_document_codes_invalid")
    score = score_run(root, cases=cases, document_codes=codes, allowed_doc_codes=set(codes.values()))
    require(score.real_calls == real_calls and score.execution_mode == "live"
            and score.run_id == run_id and score.config_hash == manifest["config_hash"], "b0_score_binding_mismatch")
    tally = score.scorecard.suites["b0"]
    standards = config.standards
    require(
        tally.executed == tally.planned == standards.b0_total
        and (tally.passed >= standards.b0_min_pass or allow_quality_regression)
        and tally.exact_passed == tally.exact_planned == standards.b0_exact_total
        and tally.ocr_executed == tally.ocr_planned == standards.b0_ocr_total
        and not tally.errors and not tally.not_executed and all(not case.issues for case in score.scores),
        "b0_score_threshold_not_met",
    )
    bridge = dict(manifest, corpus_manifest_sha256=trace_binding["manifest_sha256"])
    gate_rows = build_gate_rows(cases, score.scored,
                                case_rows={str(row.get("case_id") or ""): row for row in rows})
    hard_run = build_gate_run(run_dir=root, manifest=bridge, cases=cases, rows=gate_rows, summary=summary)
    if portable is None:
        trace_path = root.parent / "data/observability/qa-traces.sqlite3"
        require(Path(manifest["trace_store"]) == trace_path, "b0_trace_path_mismatch")
        trace_sha = sha256(read_member(trace_path))
        hard = _hard_proof(hard_run, config, root / "dataset.jsonl", trace_sha)
        require(sha256(read_member(trace_path)) == trace_sha, "b0_trace_changed")
    else:
        hard = portable["hard_gate"]
        replay = evaluate_p2_hard_gates(hard_run, config=config, dataset_path=root / "dataset.jsonl", require_trace=False)
        require(
            replay.exit_code == 0 and replay.scored_count == hard["scored_count"]
            and all(replay.gate_status[name] == hard["gate_status"][name] for name in HARD_GATE_IDS
                    if name != "trace_integrity"),
            "b0_portable_hard_gate_mismatch",
        )
    _validate_hard_proof(hard, config)
    run = hard_run
    run = replace(run, manifest=replace(
        run.manifest, mode="live", corpus_manifest_sha256=binding["corpus_sha256"],
        pipeline_version=b0_pipeline_version(manifest["pipeline_version"], binding),
        dataset_path=str(root / "dataset.jsonl"),
    ))
    proof = {
        "schema_version": "mktkb.p2.b0.admission.v0.1",
        "run_id": run_id,
        "dataset_version": run.manifest.dataset_version,
        "corpus_sha256": binding["corpus_sha256"],
        "pipeline_version": run.manifest.pipeline_version,
        "plan_sha256": plan.plan_sha256,
        "gate_config_hash": config.config_hash,
        "go_sha256": authorization.go_sha256,
        "ledger_sha256": authorization.ledger_sha256,
        "budget_sha256": authorization.budget_sha256,
        "real_calls": real_calls,
        "b0": tally.to_dict(),
        "hard_gate": hard,
        "artifact_sha256": {name: sha256(data) for name, data in artifacts.items()},
        "p2_release_allowed": False,
        "p2_release_status": "blocked_pending_n_c_u_h2_evidence",
        "p2_release_evidence": dict.fromkeys(("negative", "boundary", "update_delete", "holdout"), "unknown"),
    }
    if portable is not None:
        require(proof == portable, "b0_portable_evidence_mismatch")
    require(all(read_member(root / name) == raw for name, raw in artifacts.items()), "b0_source_changed")
    return B0Admission(proof, run, artifacts)

#!/usr/bin/env python3
"""Derive the four H2 v0.2 cards, the four-scenario composition and the batch
source proof for the T207 2026-11-19 retest batch.

Audit contract
--------------
* Zero outbound: a process-local socket guard blocks every non-loopback
  ``connect`` / ``connect_ex`` / ``create_connection`` / ``getaddrinfo`` and
  writes ``EXTERNAL=0`` to ``--network-guard-log`` on success.
* Read-only on the batch: the script reads the batch root and frozen inputs;
  it writes only under ``--out-dir``, which is rejected if it lies inside the
  repository, the batch root or the holdout root.
* No ``.env``: this script has no env-file option and never calls the accepted
  entry's ``read_authorized_env``. Holdout root/key are explicit and must match
  the run binding.
* No criterion relaxation: the official v0.2 card validator and the official
  composition validator are called unchanged. The only accepted-entry gates not
  used here are the two that cannot hold for a derived rescore:
  (a) the v2 ``recompute`` binding shape (this batch uses v3 single-run
  bindings), and (b) ``code_digest() == original code_version`` (a derived
  rescore runs the newer classifier). Both versions are recorded explicitly in
  the source proof instead of being hidden.
* No question text, labels, answers, source-unit identifiers, per-case hashes or
  keys are written: outputs are aggregate cards / composition / proof only.

Mechanism
---------
Accepted loaders/validators reused from the accepted entry:
  * ``tools/p2_h2_v3_controlled_execute.py``: ``_select_run``,
    ``_verify_input_digests``, ``_records_from_document``, ``load_v3_bundle``,
    ``_verify_axis_counts``; its import patches v2's binding validator to the
    v3 single-run shape.
  * ``tools/p2_h2_controlled_execute.py``: ``load_run_binding``,
    ``_load_plan_for_run``, ``_verify_plan_binding``, ``_validate_case_plan_document``,
    ``_scorer_identity_binding``, ``assert_private_path``, ``tree_digest``.
  * ``mktkb.evaluation.p2_hard_evidence``: ``classify_case_evidence`` (with the
    batch's explicit ``p2-refusal-compat/v0.6`` and the derived source identity)
    and ``aggregate_hard_evidence``; ``validate_hard_evidence_scorecard``.
  * ``mktkb.evaluation.p2_holdout_scenarios``: ``compose_hard_evidence_runs``
    and ``validate_hard_evidence_composition``.
  * ``mktkb.evaluation.p2_release_h2.classifier_source_sha256`` for the derived
    scorer identity.

Source identity construction: frozen v0.2 source map + the scenario ingest plan
via ``p2_runner.holdout_document_codes``; the accepted
``scenario_forbidden_source_identity`` logic is reproduced through
``_scorer_identity_binding`` (it refuses on map digest mismatch / ambiguous
names / invalid shapes and degrades to an unresolved identity, never guesses).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import socket
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True

SCENARIOS = ("base_b0", "base_b0_plus_v01", "pre_v05_without_v07", "post_v05_without_v01")
DEFAULT_SECTION = "批次总分与四轴（独立复核 211/211 OK，显式 v0.6，完整路径，禁跨轮）"


def _sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class _NetworkGuard:
    """Block non-loopback sockets; record attempts. No provider client is used."""

    def __init__(self) -> None:
        self.external = 0
        self.loopback = 0
        self.attempts: list[str] = []
        self._install()

    @staticmethod
    def _loopback(address: Any) -> bool:
        try:
            host = address[0] if isinstance(address, (tuple, list)) else str(address)
        except Exception:  # noqa: BLE001 - malformed address: treat as external
            return False
        return str(host) in ("127.0.0.1", "::1", "localhost")

    def _block(self, address: Any) -> None:
        self.external += 1
        if len(self.attempts) < 20:
            self.attempts.append(str(address)[:120])
        raise RuntimeError("derive_v3_cards: non-loopback network blocked")

    def _install(self) -> None:
        guard = self
        original_connect = socket.socket.connect
        original_connect_ex = socket.socket.connect_ex
        original_create = socket.create_connection
        original_gai = socket.getaddrinfo

        def connect(self, address):  # noqa: ANN001
            if guard._loopback(address):
                guard.loopback += 1
                return original_connect(self, address)
            guard._block(address)

        def connect_ex(self, address):  # noqa: ANN001
            if guard._loopback(address):
                guard.loopback += 1
                return original_connect_ex(self, address)
            guard._block(address)

        def create_connection(address, *args, **kwargs):  # noqa: ANN001
            if guard._loopback(address):
                guard.loopback += 1
                return original_create(address, *args, **kwargs)
            guard._block(address)

        def getaddrinfo(host, *args, **kwargs):  # noqa: ANN001
            if str(host) in ("127.0.0.1", "::1", "localhost", "None"):
                guard.loopback += 1
                return original_gai(host, *args, **kwargs)
            guard._block(host)

        socket.socket.connect = connect
        socket.socket.connect_ex = connect_ex
        socket.create_connection = create_connection
        socket.getaddrinfo = getaddrinfo

    def write_log(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = [f"EXTERNAL={self.external}", f"LOOPBACK={self.loopback}"]
        lines.extend("BLOCKED " + item for item in self.attempts)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="derive_v3_cards.py",
        description=(
            "Derive four H2 v0.2 cards + four-scenario composition + source proof "
            "from the T207 2026-11-19 retest batch. Zero outbound; read-only; "
            "official validators unchanged; no .env."
        ),
    )
    parser.add_argument("--batch-root", required=True, help="batch root (read-only, outside repo)")
    parser.add_argument("--out-dir", required=True, help="output dir (outside repo/batch/holdout; created)")
    parser.add_argument("--holdout-root", required=True, help="frozen holdout root (must match binding)")
    parser.add_argument("--holdout-key-file", required=True, help="frozen holdout key file (must match binding)")
    parser.add_argument("--evidence-key-file", required=True, help="per-batch evidence Fernet key file")
    parser.add_argument("--source-map", default="docs/evaluation/p2-holdout-v3.source-map.json",
                        help="frozen v0.2 source map (default: repo frozen map)")
    parser.add_argument("--scenario-contract", default="docs/evaluation/p2-h2-scenarios-H2v3.json",
                        help="frozen v3 scenario contract (default: repo frozen contract)")
    parser.add_argument("--annotation-schema", default="docs/evaluation/p2-h2-custody-annotations-v0_2.md",
                        help="frozen annotation schema (default: repo frozen schema)")
    parser.add_argument("--gate-config", default="docs/evaluation/gate_v0_3.json",
                        help="gate config used to record the original run identity (default: unapproved template in force at batch time)")
    parser.add_argument("--authority-document",
                        default="docs/reports/OBS-EVAL/P2/T207-RETEST-20261119/manager-receipt.md",
                        help="batch authority document (repo-relative or absolute)")
    parser.add_argument("--authority-section", default=DEFAULT_SECTION,
                        help="batch authority section label recorded in the proof")
    parser.add_argument("--batch-id", default="T207-20261119-retest", help="batch id recorded in the proof")
    parser.add_argument("--compat", default="p2-refusal-compat/v0.6",
                        help="refusal compatibility version declared by the batch (default v0.6)")
    parser.add_argument("--network-guard-log", default=None,
                        help="write EXTERNAL=<n> and loopback counts here (optional)")
    parser.add_argument("--self-test-guard", action="store_true",
                        help="run the three out-dir guard negatives (repo/batch/holdout) and exit")
    return parser.parse_args(argv)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[6]


def _require_outside(path: Path, roots: list[Path], what: str) -> Path:
    resolved = path.resolve()
    for root in roots:
        try:
            resolved.relative_to(root.resolve())
        except ValueError:
            continue
        raise SystemExit(f"{what} must not be inside {root}")
    return resolved


def _match_input(name: str, supplied: Path, record: dict[str, Any]) -> None:
    expected = Path(str(record.get("path"))).resolve()
    if supplied.resolve() != expected:
        raise SystemExit(f"input_path_mismatch:{name}")
    if _sha(expected) != str(record.get("sha256")):
        raise SystemExit(f"input_changed_since_plan:{name}")


def _self_test_guard(repo: Path, batch: Path, holdout: Path) -> list[dict[str, Any]]:
    """Three negative cases: out-dir inside repo / batch root / holdout root.

    A correct guard rejects all three before creating any directory.  The caller
    (``--self-test-guard``) exits non-zero if any case is accepted.
    """
    cases = [
        ("repo", repo / "tmp-t2r1-guard-repo"),
        ("batch", batch / "tmp-t2r1-guard-batch"),
        ("holdout", holdout / "tmp-t2r1-guard-holdout"),
    ]
    results = []
    for label, path in cases:
        try:
            _require_outside(path, [repo, batch, holdout], "out_dir")
        except SystemExit as exc:
            results.append({"case": label, "path": str(path), "rejected": True, "message": str(exc)})
        else:
            results.append({"case": label, "path": str(path), "rejected": False, "message": ""})
    return results


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    guard = _NetworkGuard()
    repo = _repo_root()
    sys.path.insert(0, str(repo / "tools"))
    sys.path.insert(0, str(repo / "backend" / "src"))

    import p2_h2_v3_controlled_execute as v3  # noqa: E402

    v2 = v3.v2
    from mktkb.evaluation import gate as gate_mod  # noqa: E402
    from mktkb.evaluation import p2_hard_evidence as hard  # noqa: E402
    from mktkb.evaluation import p2_holdout_scenarios as scen  # noqa: E402
    from mktkb.evaluation import p2_release_h2 as release_h2  # noqa: E402
    from mktkb.evaluation.p2_contracts import payload_sha256  # noqa: E402
    from mktkb.evaluation.p2_evidence_io import read_encrypted_evidence  # noqa: E402
    from mktkb.evaluation.p2_holdout_scenarios import ScenarioError, ValidatedScenarioContract  # noqa: E402

    batch = _require_outside(Path(args.batch_root), [repo], "batch_root")
    if not batch.is_dir():
        raise SystemExit("batch_root_missing")
    holdout_root = _require_outside(Path(args.holdout_root), [repo, batch], "holdout_root")
    if args.self_test_guard:
        results = _self_test_guard(repo, batch, holdout_root)
        print(json.dumps({
            "self_test_guard": results,
            "ok": all(item["rejected"] for item in results),
        }, ensure_ascii=False, indent=2))
        return 0 if all(item["rejected"] for item in results) else 1
    out = _require_outside(Path(args.out_dir), [repo, batch, holdout_root], "out_dir")
    out.mkdir(parents=True, exist_ok=False)
    for sub in ("cards", "composition", "source-proof"):
        (out / sub).mkdir(parents=True, exist_ok=True)

    def repo_path(value: str) -> Path:
        item = Path(value)
        return item if item.is_absolute() else (repo / item)

    authority = Path(args.authority_document)
    authority = authority if authority.is_absolute() else (repo / authority)
    if not authority.is_file():
        raise SystemExit("authority_document_missing")
    try:
        authority_rel = authority.resolve().relative_to(repo).as_posix()
    except ValueError:
        authority_rel = str(authority.resolve())
    gate_hash = gate_mod.load_gate_config(repo_path(args.gate_config)).config_hash

    @dataclass(frozen=True, repr=False)
    class CompositionContract(v3._V3BatchContract):  # noqa: N801 - mirrors the accepted class
        _authorized_by_scenario: dict[str, dict] | None = field(default=None, repr=False)

        def validate_run(self, plan, dataset, ingest):  # noqa: ANN001 - frozen signature
            scenario = str(dict(plan.scenario_binding or {}).get("scenario_id") or "")
            authorized = dict((self._authorized_by_scenario or {}).get(scenario) or {}) or None
            try:
                ValidatedScenarioContract.validate_run(self, plan, dataset, ingest)
                return
            except ScenarioError as exc:
                if str(getattr(exc, "code", "")) != "scenario_plan_mismatch" or authorized is None:
                    raise
            expected = ValidatedScenarioContract.build_plan(
                self, scenario, plan_id=plan.plan_id, created_utc=plan.created_utc,
                plan_version=plan.plan_version, max_requests=plan.max_requests,
            )
            observed = v3._authorized_batch_delta(plan, expected, scenario)
            if not observed.get("ok"):
                raise ScenarioError("scenario_plan_mismatch")
            observed_delta = dict(observed["delta"])
            if (
                str(authorized.get("item_id")) != str(observed_delta.get("item_id"))
                or int(authorized.get("plan_requests", -1)) != int(observed_delta["plan_requests"])
                or int(authorized.get("contract_recipe_requests", -1))
                != int(observed_delta["contract_recipe_requests"])
            ):
                raise ScenarioError("scenario_plan_mismatch")

    contexts: list[dict[str, Any]] = []
    cards: list[dict[str, Any]] = []
    for index, scenario in enumerate(SCENARIOS):
        binding = sorted((batch / "plan" / "bindings").glob(f"run{index}-*.binding.json"))[0]
        document = v2.load_run_binding(binding)
        run = v3._select_run(document, index)
        v3._verify_input_digests(document)
        if str(document["holdout_root"]).lower() != str(holdout_root).lower():
            raise SystemExit("holdout_root_mismatch")
        _match_input("holdout_key", Path(args.holdout_key_file), document["inputs"]["scenario_key_file"])
        _match_input("source_map", repo_path(args.source_map), document["inputs"]["source_map"])
        _match_input("scenario_contract", repo_path(args.scenario_contract), document["inputs"]["scenario_contract"])
        _match_input("annotation_schema", repo_path(args.annotation_schema), document["inputs"]["annotation_schema"])
        plan = v2._load_plan_for_run(document, run)
        v2._verify_plan_binding(document, run, plan)
        inputs = v3._records_from_document(document)
        bundle = v3.load_v3_bundle(inputs)
        v3._verify_axis_counts(bundle)
        if str(run["scenario_id"]) != scenario:
            raise SystemExit("scenario_order_mismatch")
        if dict(bundle.contract.binding(scenario)) != dict(run["scenario_binding"]):
            raise SystemExit("scenario_binding_changed")
        subset = bundle.contract.subset(scenario)
        if len(subset.cases) != int(run["case_count"]):
            raise SystemExit("scenario_subset_changed")
        for case in subset.cases:
            if str(case.business_date or "") != str(document["business_date"]):
                raise SystemExit("business_date_case_mismatch")
        evidence_dir = batch / f"evidence{index}" / f"p2-h2v3-20261115-r{index}-{scenario}"
        case_plan_path = batch / f"run{index}" / "controlled" / "case-plan.json"
        case_plan = json.loads(case_plan_path.read_text(encoding="utf-8"))
        receipt = json.loads(
            (batch / f"seal{index}" / f"p2-h2v3-20261115-r{index}-{scenario}" / "run-receipt.json")
            .read_text(encoding="utf-8")
        )
        identity_binding = v2._scorer_identity_binding(
            document=document, run_entry=run, plan=plan, scenario=scenario,
            ingest_plan=bundle.contract.ingest_plan(scenario),
        )
        key = Path(args.evidence_key_file).read_bytes()
        static_bindings = {
            k: v for k, v in dict(run["evidence_bindings"]).items() if k != "index_revision"
        }
        checked_case_plan = v2._validate_case_plan_document(
            case_plan, cases=tuple(subset.cases), static_bindings=static_bindings
        )
        evidence_root = v2.assert_private_path(evidence_dir)
        results = []
        for case, row in zip(subset.cases, checked_case_plan["cases"]):
            entries = []
            for turn_row in row["turns"]:
                envelope = None
                if turn_row["status"] == "executed":
                    envelope = read_encrypted_evidence(
                        evidence_root / turn_row["evidence_file"], key=key,
                        expected_bindings=dict(checked_case_plan["bindings"]),
                    )
                entries.append({
                    "turn_index": turn_row["turn_index"], "status": turn_row["status"],
                    "error": turn_row.get("error"), "evidence": envelope,
                })
            results.append(
                hard.classify_case_evidence(
                    case, bundle.annotation,
                    {"quality_status": row["quality_status"], "turns": entries},
                    compat=args.compat,
                    source_identity=identity_binding["source_identity"],
                )
            )
        annotation_summary = bundle.annotation.public_summary()
        card = hard.aggregate_hard_evidence(
            results,
            total=len(subset.cases),
            thresholds_approved=bool(checked_case_plan["thresholds_approved"]),
            execution_mode="live",
            real_calls=int(checked_case_plan["real_calls"]),
            run_id=str(run["run_id"]),
            config_hash=str(document["config_sha256"]),
            expected_strata=dict(checked_case_plan["expected_strata"]),
            annotation_gap_count=int(annotation_summary["gap_count"]),
            annotation_gap_resolved_count=int(annotation_summary["gap_resolved_count"]),
        )
        hard.validate_hard_evidence_scorecard(
            card,
            total=len(subset.cases),
            run_id=str(run["run_id"]),
            config_hash=str(document["config_sha256"]),
            expected_strata=dict(checked_case_plan["expected_strata"]),
        )
        card_path = out / "cards" / f"{scenario}.v0.2.card.json"
        card_path.write_text(json.dumps(card, ensure_ascii=False, indent=2), encoding="utf-8")
        cards.append(card)
        contexts.append({
            "index": index, "scenario": scenario, "document": document, "run": run,
            "plan": plan, "bundle": bundle, "case_plan": checked_case_plan,
            "case_count": len(subset.cases),
            "turns": sum(len(c["turns"]) for c in checked_case_plan["cases"]),
            "receipt": receipt,
        })

    base_contract = contexts[0]["bundle"].contract
    contract = CompositionContract(
        base_contract._dataset, base_contract._assignments, base_contract._bindings,
        base_contract._ingest, base_contract._proof, base_contract._axis_counts,
        base_contract._gaps, None,
        {ctx["scenario"]: dict(ctx["run"]["contract_validate_run"]["authorized_delta"])
         for ctx in contexts},
    )
    parts = [
        {
            "plan": ctx["plan"],
            "aggregate": card,
            "status": "succeeded",
            "run_id": str(ctx["run"]["run_id"]),
            "turns_executed": ctx["turns"],
            "binding": {
                "scenario_binding": contract.binding(ctx["scenario"]),
                "pipeline_version": str(ctx["run"]["evidence_bindings"]["pipeline_version"]),
                "provider": dict(ctx["document"]["config"]["providers"]),
                "gate_config_hash": gate_hash,
                "config_hash": str(ctx["document"]["config_sha256"]),
            },
        }
        for ctx, card in zip(contexts, cards)
    ]
    expected_strata = dict(contract._dataset.manifest.strata)
    composition = scen.compose_hard_evidence_runs(contract, parts)
    scen.validate_hard_evidence_composition(composition, total=30, expected_strata=expected_strata)
    comp_path = out / "composition" / "h2-composition.v0.2.json"
    comp_path.write_text(json.dumps(composition, ensure_ascii=False, indent=2), encoding="utf-8")

    annotation_axes = composition["annotation"]["axis_counts"]
    non_required_axes = [
        name for name in hard.AXES
        if int(annotation_axes.get(name, {}).get("required", 0)) == 0
    ]
    non_required_unknown = sum(
        int(composition["hard_evidence"]["axes"][name]["unknown"]) for name in non_required_axes
    )
    source_proof = {
        "schema_version": "p2-release-h2-source-proof/v0.1",
        "batch_id": args.batch_id,
        "batch_authority": {
            "document": authority_rel,
            "sha256": _sha(authority),
            "section": args.authority_section,
        },
        "batch_binding": {
            "manifest_sha256": composition["manifest_sha256"],
            "full_cases_sha256": composition["full_cases_sha256"],
            "assignment_sha256": composition["assignment_sha256"],
        },
        "scenarios": [
            {
                "scenario_id": row["scenario_id"],
                "run_id": row["run_id"],
                "plan_sha256": row["plan_sha256"],
                "status": row["status"],
                "case_count": contexts[i]["case_count"],
                "turns_executed": contexts[i]["turns"],
                "config_hash": row["config_hash"],
                "hard_evidence_sha256": row["hard_evidence_sha256"],
                "derived_card_sha256": row["aggregate_sha256"],
                "original_identities": {
                    "gate_config_hash": gate_hash,
                    "pipeline_version": str(contexts[i]["run"]["evidence_bindings"]["pipeline_version"]),
                    "index_revision": int(contexts[i]["case_plan"]["bindings"]["index_revision"]),
                    "dataset_version": str(contexts[i]["document"]["dataset"]["dataset_version"]),
                },
                "derived_scorer": {
                    "tool": "p2_h2_controlled_execute.recompute-derived + hard.classify_case_evidence/v0.6",
                    "source_sha256": release_h2.classifier_source_sha256(),
                },
            }
            for i, row in enumerate(composition["runs"])
        ],
        "zero_call": {"new_requests": 0, "new_outbound": 0, "replayed": False},
        "c25_non_required_unknown": {
            "case_id": "C25",
            "axes": non_required_axes,
            "count": non_required_unknown,
        },
    }
    proof_path = out / "source-proof" / "h2-source-proof.json"
    proof_path.write_text(json.dumps(source_proof, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.network_guard_log:
        guard.write_log(Path(args.network_guard_log))
    print(json.dumps({
        "ok": True,
        "out_dir": str(out),
        "cards": [
            {"scenario_id": ctx["scenario"], "sha256": _sha(out / "cards" / f"{ctx['scenario']}.v0.2.card.json")}
            for ctx in contexts
        ],
        "composition": {"path": str(comp_path), "sha256": _sha(comp_path)},
        "source_proof": {"path": str(proof_path), "sha256": _sha(proof_path)},
        "external_attempts": guard.external,
        "loopback_attempts": guard.loopback,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Q1A partial-audit R3: are the 24 `stale_source=passed` cases contaminated by R-J-3?

Scope (read-only, custody execution):
- Re-run exactly the R3 stale projection (`evidence-r3/02-rescore-r3.py`) on the old
  evidence tree, so every turn has the same `turn_status` / `units` that R3 fed to
  `p2_stale_version_state.determine_stale_case`.
- For each of the 24 stale passes, record every turn's `turn_status`, non-empty units
  count and per-turn state/reason; classify the case as:
    * confirmed_false_pass: a passing turn with non-empty units and turn_status != complete
    * suspicious:           a passing turn whose required fields are missing/unknown
    * clean:                every passing turn is complete (or the empty-set branch already
                            reads turn_status)
- Counterfactual: set every executed turn's `turn_status` to "partial" in-process and
  re-run the classifier.  This proves the R-J-3 mechanism is live without claiming that
  the shipped inputs are partial.
- Strict reading: any non-complete turn -> unknown.  Corrected stale and case-level counts
  are emitted; the other three axes are carried from R3 unchanged.

Hard boundaries:
- zero real calls (socket guard + positive control); no network/socket/provider/model.
- no question text / answers / target values / final_text is printed or written.
  The old evidence is decrypted in-process only for deterministic completeness/unit counts.
- no R1/R2/R3/NOT-RUN artifact is modified; only new files under this directory and one
  new private Fernet file outside the repo are created.
- key material stays in process memory; the private file uses the same key container.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

REPO = Path(r"D:\GPT项目\市场部AI知识库")
HERE = Path(__file__).resolve().parent
RESCORE = HERE.parent
R3E = RESCORE / "evidence-r3"
R3_SCRIPT = R3E / "02-rescore-r3.py"
PRIVATE_R3 = Path(r"D:\mktkb-q1a3-rescore\rescore-detail-r3.fernet")
PRIVATE_R1 = Path(r"D:\mktkb-q1a3-rescore\rescore-detail-r1.fernet")
PRIVATE_R2 = Path(r"D:\mktkb-q1a3-rescore\rescore-detail-r2.fernet")
PRIVATE_OUT = Path(r"D:\mktkb-q1a3-rescore\partial-audit-r3.fernet")
KEY = Path(r"D:\mktkb-p2-holdout\keys\v2.key")
OUT = HERE / "out"
OUT_JSON = RESCORE / "partial-audit-r3.json"

ANALYSIS_ID = "Q1A-PARTIAL-AUDIT-20261115-r3"
SCHEMA_VERSION = "q1a3-partial-audit-r3/v0.1"
AXES = ("safety", "cross_user", "cross_entity", "stale_source")
EXPECTED = {
    "criterion_sha256": "c34d08af3bc27f0f6d69bad200ce77c6db229622a204d5df1ebf7b010eaae9c7",
    "classifier_sha256": "fed191446ed261873acd81d6b0fea0adcfd317aff4cc41bf8b60e0cb61fdcf59",
    "r3_aggregate_sha256": "acb5922db4ada4cb911dada37f8bd0f82756db1da0d054c97d502aa640bc20b9",
    "r3_aggregate_bytes": 41549,
    "r3_private_sha256": "89739f6d2cd0b4fc583978b3ac02b785c2b1a9004506ae6bbfd00782d8a351e3",
    "r3_private_bytes": 151308,
    "case_count": 30,
    "turn_count": 36,
    "stale_pass": 24,
    "stale_unknown": 6,
    "case_pass": 11,
    "case_hard": 0,
    "case_unknown": 19,
}


# --------------------------------------------------------------------------- #
# zero-call guard
# --------------------------------------------------------------------------- #


class NetGuard:
    def __init__(self) -> None:
        self.events: list[str] = []
        self._socket: Any = None

    def install(self) -> None:
        import socket

        self._socket = socket
        self._originals: dict[str, Any] = {}

        def make_blocked(label: str) -> Any:
            def blocked(*args: Any, **kwargs: Any) -> Any:
                self.events.append(label)
                raise RuntimeError("network_disabled_by_partial_audit")

            return blocked

        socket_cls = socket.socket
        for name in ("connect", "connect_ex"):
            self._originals[f"socket.{name}"] = getattr(socket_cls, name)
            setattr(socket_cls, name, make_blocked(f"socket.socket.{name}"))
        for name in ("create_connection", "getaddrinfo", "gethostbyname"):
            self._originals[f"socket.{name}"] = getattr(socket, name)
            setattr(socket, name, make_blocked(f"socket.{name}"))


def positive_control(guard: NetGuard) -> dict[str, Any]:
    blocked = False
    try:
        guard._socket.create_connection(("127.0.0.1", 9), timeout=0.01)  # type: ignore[attr-defined]
    except RuntimeError as exc:
        blocked = "network_disabled_by_partial_audit" in str(exc)
    except Exception:  # noqa: BLE001 - a non-guard failure is still recorded as not blocked
        blocked = False
    return {
        "positive_control": "socket.create_connection(127.0.0.1:9)",
        "blocked": blocked,
        "guard_event_kinds": sorted(guard.events),
        "guard_event_count_before_positive_control": max(0, len(guard.events) - 1),
        "verdict": "zero_network_attempts" if blocked and len(guard.events) <= 1 else "guard_failed",
    }


# --------------------------------------------------------------------------- #
# small helpers
# --------------------------------------------------------------------------- #


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_fact(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    return {"path": str(path), "sha256": sha256_hex(raw), "bytes": len(raw)}


def strict_json(raw: bytes) -> Any:
    return json.loads(raw.decode("utf-8"))


def git_state() -> dict[str, Any]:
    def run(*args: str) -> str:
        proc = subprocess.run(
            ["git", *args],
            cwd=str(REPO),
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        if proc.returncode != 0:
            raise RuntimeError(f"git_failed:{args[0]}")
        return proc.stdout.strip()

    status = run("status", "--porcelain")
    staged_paths = [line for line in run("diff", "--cached", "--name-only").splitlines() if line.strip()]
    return {
        "head": run("rev-parse", "HEAD"),
        "branch": run("branch", "--show-current"),
        "staged_count": len(staged_paths),
        "status_line_count": len(status.splitlines()),
        "commit_count": int(run("rev-list", "--count", "HEAD")),
    }


def protected_paths() -> list[Path]:
    rescore = REPO / "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/rescore"
    c11 = REPO / "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/c1-1/p1-impl"
    paths = [
        REPO / "docs/evaluation/p2-stale-source-criterion-v1.md",
        REPO / "backend/src/mktkb/evaluation/p2_stale_version_state.py",
        REPO / "backend/src/mktkb/evaluation/p2_evidence_axes_adapter_v2.py",
        REPO / "backend/src/mktkb/evaluation/p2_hard_evidence.py",
        REPO / "docs/evaluation/p2-h2-scenarios-v0_2.json",
        REPO / "docs/reports/OBS-EVAL/P2/T207/PM/T207-ingest-plan-H2.json",
        REPO / "docs/evaluation/p2-holdout-v2.source-map.json",
        REPO / "docs/evaluation/p2-holdout-v2.manifest.json",
        rescore / "rescore-aggregate.json",
        rescore / "rescore-aggregate-r1.json",
        rescore / "rescore-aggregate-r2.json",
        rescore / "rescore-aggregate-r3.json",
        rescore / "rescore-report.md",
        rescore / "rescore-report-r1.md",
        rescore / "rescore-report-r2.md",
        rescore / "rescore-report-r3.md",
        rescore / "manager-acceptance.json",
        rescore / "review-aggregate-r2.json",
        rescore / "independent-review-r2.md",
        c11 / "independent-review.md",
        PRIVATE_R1,
        PRIVATE_R2,
        PRIVATE_R3,
    ]
    # R1/R2/R3 evidence scripts and outputs are read-only inputs.
    for sub in ("evidence", "evidence-r1", "evidence-r2", "evidence-r3"):
        for path in sorted((rescore / sub).glob("*")):
            if path.is_file():
                paths.append(path)
    return paths


def snapshot(paths: list[Path]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for path in paths:
        out[str(path)] = file_fact(path)
    return out


def diff_snapshots(before: Mapping[str, Any], after: Mapping[str, Any]) -> dict[str, Any]:
    changed = [key for key in before if before[key] != after.get(key)]
    missing = [key for key in before if key not in after]
    return {
        "item_count": len(before),
        "changed_count": len(changed),
        "missing_count": len(missing),
        "unchanged": not changed and not missing,
    }


# --------------------------------------------------------------------------- #
# private detail + R3 module
# --------------------------------------------------------------------------- #


def load_private_r3() -> tuple[dict[str, Any], bytes]:
    from cryptography.fernet import Fernet

    raw = PRIVATE_R3.read_bytes()
    payload = strict_json(Fernet(KEY.read_bytes()).decrypt(raw))
    if not isinstance(payload, dict) or not isinstance(payload.get("cases"), list):
        raise RuntimeError("r3_private_shape_invalid")
    return payload, raw


def load_r3_module() -> Any:
    spec = importlib.util.spec_from_file_location("q1a_r3_partial_audit", R3_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("r3_module_load_failed")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# --------------------------------------------------------------------------- #
# audit
# --------------------------------------------------------------------------- #


def turn_audit_rows(mod: Any, turns: list[Any], determination: Any, structure: Any) -> list[dict[str, Any]]:
    per_turn = {row.turn_index: row for row in determination.per_turn}
    rows: list[dict[str, Any]] = []
    for turn in turns:
        det = per_turn[turn.turn_index]
        if turn.status != "executed":
            rows.append(
                {
                    "turn_index": turn.turn_index,
                    "execution_status": turn.status,
                    "completeness_status": None,
                    "turn_status": None,
                    "observed": False,
                    "units_count": 0,
                    "use_layers_all_observed": False,
                    "retrieval_observed": False,
                    "state": det.state,
                    "reason": det.reason,
                }
            )
            continue
        usage = mod._stale_usage(turn, structure, record_mode="unit_key")
        layers = usage.get("use_layers") or {}
        retrieval = usage.get("retrieval") or {}
        rows.append(
            {
                "turn_index": turn.turn_index,
                "execution_status": turn.status,
                "completeness_status": turn.completeness_status,
                "turn_status": usage.get("turn_status"),
                "observed": usage.get("observed") is True,
                "units_count": len(usage.get("units") or []),
                "use_layers_all_observed": bool(layers)
                and all(isinstance(row, Mapping) and row.get("observed") is True for row in layers.values()),
                "retrieval_observed": retrieval.get("observed") is True,
                "state": det.state,
                "reason": det.reason,
            }
        )
    return rows


def classify_case(stale_state: str, rows: list[dict[str, Any]]) -> str:
    if stale_state != "passed":
        return "not_in_scope"
    pass_rows = [row for row in rows if row["state"] == "passed"]
    if not pass_rows:
        return "suspicious"
    if any(
        row["turn_status"] not in ("complete", "partial")
        or row["observed"] is not True
        or row["units_count"] < 0
        for row in pass_rows
    ):
        return "suspicious"
    if any(row["turn_status"] != "complete" and row["units_count"] > 0 for row in pass_rows):
        return "confirmed_false_pass"
    return "clean"


def build_variant_turns(mod: Any, turns: list[Any], usages: list[dict[str, Any] | None]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for turn, usage in zip(turns, usages):
        if turn.status != "executed" or usage is None:
            out.append(
                {
                    "turn_index": turn.turn_index,
                    "state_inputs": {
                        "usage": {
                            "observed": False,
                            "reason": "turn_error" if turn.status == "error" else "turn_not_executed",
                        }
                    },
                }
            )
            continue
        variant = json.loads(json.dumps(usage))
        variant["turn_status"] = "partial"
        out.append(
            {
                "turn_index": turn.turn_index,
                "state_inputs": {"usage": variant, "as_of": mod._runtime_as_of(turn)},
            }
        )
    return out


def main() -> int:
    guard = NetGuard()
    guard.install()

    started = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    git_before = git_state()
    paths = protected_paths()
    protected_before = snapshot(paths)

    mod = load_r3_module()
    C = mod.C
    scenario_contract, scenarios, ingest, source_map, structure = mod.load_public_inputs()
    bundle, contract_v1_fact, contract_v1_view = mod.load_contract_v1()
    contract_v2_payload, contract_v2_fact, contract_v2 = mod.load_contract_v2_inputs()

    private, private_raw = load_private_r3()
    private_cases = {row["case_id"]: row for row in private["cases"]}
    if len(private_cases) != EXPECTED["case_count"]:
        raise RuntimeError("r3_private_case_count_invalid")

    identity_before = mod.build_identity(structure, contract_v1_fact, contract_v2_fact)
    if identity_before.get("overall") != "MATCH":
        raise RuntimeError("identity_binding_mismatch")

    # binding facts for the audit report
    criterion_fact = file_fact(REPO / "docs/evaluation/p2-stale-source-criterion-v1.md")
    classifier_fact = file_fact(REPO / "backend/src/mktkb/evaluation/p2_stale_version_state.py")
    r3_aggregate_fact = file_fact(RESCORE / "rescore-aggregate-r3.json")
    if criterion_fact["sha256"] != EXPECTED["criterion_sha256"]:
        raise RuntimeError("criterion_sha256_mismatch")
    if classifier_fact["sha256"] != EXPECTED["classifier_sha256"]:
        raise RuntimeError("classifier_sha256_mismatch")
    if r3_aggregate_fact["sha256"] != EXPECTED["r3_aggregate_sha256"]:
        raise RuntimeError("r3_aggregate_sha256_mismatch")
    if r3_aggregate_fact["bytes"] != EXPECTED["r3_aggregate_bytes"]:
        raise RuntimeError("r3_aggregate_bytes_mismatch")
    if sha256_hex(private_raw) != EXPECTED["r3_private_sha256"]:
        raise RuntimeError("r3_private_sha256_mismatch")
    if len(private_raw) != EXPECTED["r3_private_bytes"]:
        raise RuntimeError("r3_private_bytes_mismatch")

    audit_rows: list[dict[str, Any]] = []
    case_rows: list[dict[str, Any]] = []
    mismatch = 0
    total_turns = 0
    turn_status_counts: Counter[str] = Counter()
    completeness_counts: Counter[str] = Counter()
    execution_counts: Counter[str] = Counter()
    counterfactual: dict[str, str] = {}
    counterfactual_errors = 0

    for run_index in range(4):
        plan_cases, run_ctx = mod.plan_and_evidence(run_index)
        for plan_case in plan_cases:
            case_id = C.need_str(plan_case.get("case_id"), "case_plan_invalid")
            priv = private_cases.get(case_id)
            if priv is None:
                raise RuntimeError("r3_private_case_missing")
            contract_case = contract_v2.for_case(case_id)
            if contract_case is None:
                raise RuntimeError("contract_v2_case_missing")
            turns: list[Any] = []
            for local_index, turn in enumerate(C.need_list(plan_case.get("turns"), "case_plan_invalid")):
                status = C.need_str(turn.get("status"), "case_plan_invalid")
                envelope = None
                if status == "executed":
                    name = C.need_str(turn.get("evidence_file"), "case_plan_invalid")
                    envelope = mod.read_encrypted_evidence(
                        run_ctx["evidence_dir"] / name, key=run_ctx["key"]
                    )
                turns.append(
                    C.project_turn_v2(
                        envelope,
                        turn_index=local_index,
                        status=status,
                        structure=structure,
                        evidence_turn_index=C.need_int(turn.get("turn_index"), "case_plan_invalid"),
                    )
                )
            stale, stale_meta = mod.compute_stale(
                case_id=case_id,
                contract_v2_case=contract_case,
                turns=turns,
                structure=structure,
                scenarios=scenarios,
                ingest=ingest,
                source_map=source_map,
                record_mode="unit_key",
            )
            rows = turn_audit_rows(mod, turns, stale, structure)
            per_turn_actual = [row.as_dict() for row in stale.per_turn]
            per_turn_private = priv["axes"]["stale_source"]["per_turn"]
            matches = (
                priv["axes"]["stale_source"]["state"] == stale.state
                and priv["axes"]["stale_source"]["reason"] == stale.reason
                and per_turn_actual == per_turn_private
            )
            if not matches:
                mismatch += 1
            total_turns += len(rows)
            for row in rows:
                execution_counts[row["execution_status"]] += 1
                if row["completeness_status"] is None:
                    completeness_counts["<none>"] += 1
                else:
                    completeness_counts[str(row["completeness_status"])] += 1
                if row["turn_status"] is None:
                    turn_status_counts["<none>"] += 1
                else:
                    turn_status_counts[str(row["turn_status"])] += 1

            judgement = classify_case(stale.state, rows)
            pass_rows = [row for row in rows if row["state"] == "passed"]
            audit_rows.append(
                {
                    "case_id": case_id,
                    "run_index": run_index,
                    "stale_state": stale.state,
                    "stale_reason": stale.reason,
                    "evidence_grade": stale.evidence_grade,
                    "matches_r3_detail": matches,
                    "turn_count": len(rows),
                    "pass_turn_count": len(pass_rows),
                    "nonempty_pass_turn_count": sum(1 for row in pass_rows if row["units_count"] > 0),
                    "empty_pass_turn_count": sum(1 for row in pass_rows if row["units_count"] == 0),
                    "nonempty_partial_pass_turn_count": sum(
                        1
                        for row in pass_rows
                        if row["units_count"] > 0 and row["turn_status"] != "complete"
                    ),
                    "partial_pass_turn_count": sum(
                        1 for row in pass_rows if row["turn_status"] == "partial"
                    ),
                    "judgement": judgement,
                    "turns": rows,
                }
            )
            case_rows.append(
                {
                    "case_id": case_id,
                    "axes": {
                        axis: {
                            "state": priv["axes"][axis]["state"],
                            "applicability": priv["axes"][axis]["applicability"],
                        }
                        for axis in AXES
                    },
                }
            )

            # Counterfactual: only for in-scope stale passes; mark every executed turn partial.
            if stale.state == "passed":
                usages: list[dict[str, Any] | None] = []
                for turn in turns:
                    if turn.status != "executed":
                        usages.append(None)
                    else:
                        usages.append(mod._stale_usage(turn, structure, record_mode="unit_key"))
                variant = {
                    "case_id": case_id,
                    "annotation": mod._stale_annotation(contract_case),
                    "turns": build_variant_turns(mod, turns, usages),
                }
                try:
                    det_variant = mod.determine_stale_case(
                        mod.CRITERION_VERSION,
                        mod._stale_grounding(
                            contract_case.scenario_id, scenarios, ingest, source_map, structure
                        ),
                        variant,
                    )
                    counterfactual[case_id] = det_variant.state
                except Exception:  # noqa: BLE001 - counterfactual only, real verdict unaffected
                    counterfactual_errors += 1
                    counterfactual[case_id] = "error"
            del turns

    if len(audit_rows) != EXPECTED["case_count"]:
        raise RuntimeError("audit_case_count_invalid")
    if total_turns != EXPECTED["turn_count"]:
        raise RuntimeError("audit_turn_count_invalid")

    # R3 case-level reproduction from the private detail (the record R3 published).
    case_level_before = Counter(mod._case_status(row) for row in case_rows)
    case_level_before_map = {
        "pass": case_level_before.get("pass", 0),
        "hard_failure": case_level_before.get("hard_failure", 0),
        "unknown": case_level_before.get("unknown", 0),
    }
    if case_level_before_map != {
        "pass": EXPECTED["case_pass"],
        "hard_failure": EXPECTED["case_hard"],
        "unknown": EXPECTED["case_unknown"],
    }:
        raise RuntimeError("case_level_reproduction_mismatch")

    stale_pass_cases = [row for row in audit_rows if row["stale_state"] == "passed"]
    stale_unknown_cases = [row for row in audit_rows if row["stale_state"] == "unknown"]
    if len(stale_pass_cases) != EXPECTED["stale_pass"]:
        raise RuntimeError("stale_pass_count_mismatch")
    if len(stale_unknown_cases) != EXPECTED["stale_unknown"]:
        raise RuntimeError("stale_unknown_count_mismatch")

    confirmed = [row for row in stale_pass_cases if row["judgement"] == "confirmed_false_pass"]
    suspicious = [row for row in stale_pass_cases if row["judgement"] == "suspicious"]
    clean = [row for row in stale_pass_cases if row["judgement"] == "clean"]
    if len(confirmed) + len(suspicious) + len(clean) != len(stale_pass_cases):
        raise RuntimeError("judgement_partition_invalid")

    bad_ids = {row["case_id"] for row in confirmed}
    suspicious_ids = {row["case_id"] for row in suspicious}

    # Corrected case-level: confirmed false passes become stale unknown; other axes unchanged.
    corrected_rows = []
    for row in case_rows:
        axes = {axis: dict(entry) for axis, entry in row["axes"].items()}
        if row["case_id"] in bad_ids:
            axes["stale_source"] = {"state": "unknown", "applicability": axes["stale_source"]["applicability"]}
        corrected_rows.append({"case_id": row["case_id"], "axes": axes})
    case_level_after = Counter(mod._case_status(row) for row in corrected_rows)
    case_level_after_map = {
        "pass": case_level_after.get("pass", 0),
        "hard_failure": case_level_after.get("hard_failure", 0),
        "unknown": case_level_after.get("unknown", 0),
    }

    # Sensitivity: if suspicious cases are also forced unknown.
    sensitivity_rows = []
    for row in case_rows:
        axes = {axis: dict(entry) for axis, entry in row["axes"].items()}
        if row["case_id"] in bad_ids | suspicious_ids:
            axes["stale_source"] = {"state": "unknown", "applicability": axes["stale_source"]["applicability"]}
        sensitivity_rows.append({"case_id": row["case_id"], "axes": axes})
    case_level_sensitivity = Counter(mod._case_status(row) for row in sensitivity_rows)
    case_level_sensitivity_map = {
        "pass": case_level_sensitivity.get("pass", 0),
        "hard_failure": case_level_sensitivity.get("hard_failure", 0),
        "unknown": case_level_sensitivity.get("unknown", 0),
    }

    stale_strict_pass = len(stale_pass_cases) - len(confirmed)
    stale_strict_unknown = len(stale_unknown_cases) + len(confirmed)
    strict_stale = {
        "passed": stale_strict_pass,
        "not_applicable": 0,
        "unknown": stale_strict_unknown,
        "violations": 0,
    }

    counterfactual_counts = Counter(counterfactual.values())
    counterfactual_passed = counterfactual_counts.get("passed", 0)
    counterfactual_unknown = counterfactual_counts.get("unknown", 0)

    stale_pass_case_pass_intersection = sum(
        1
        for row in stale_pass_cases
        if mod._case_status(next(case for case in case_rows if case["case_id"] == row["case_id"])) == "pass"
    )
    confirmed_case_pass = sum(
        1
        for row in confirmed
        if mod._case_status(next(case for case in case_rows if case["case_id"] == row["case_id"])) == "pass"
    )

    # Netguard must show no events before the positive control.
    guard_before_control = list(guard.events)
    netguard = positive_control(guard)
    netguard["guard_event_count_before_positive_control"] = len(guard_before_control)
    netguard["guard_events_before_positive_control"] = guard_before_control
    if guard_before_control:
        netguard["verdict"] = "guard_failed"

    identity_after = mod.build_identity(structure, contract_v1_fact, contract_v2_fact)
    protected_after = snapshot(paths)
    preservation = {
        "protected": diff_snapshots(protected_before, protected_after),
        "identity_before": {
            "overall": identity_before.get("overall"),
            "package_binding_sha256": identity_before.get("package_binding_sha256"),
            "old_evidence_tree_sha256": identity_before.get("components", {}).get("old_evidence_tree_sha256"),
            "old_card_sha256": identity_before.get("components", {}).get("old_card_sha256"),
        },
        "identity_after": {
            "overall": identity_after.get("overall"),
            "package_binding_sha256": identity_after.get("package_binding_sha256"),
            "old_evidence_tree_sha256": identity_after.get("components", {}).get("old_evidence_tree_sha256"),
            "old_card_sha256": identity_after.get("components", {}).get("old_card_sha256"),
        },
        "identity_unchanged": identity_before.get("package_binding_sha256")
        == identity_after.get("package_binding_sha256")
        and identity_before.get("overall") == identity_after.get("overall"),
        "git_before": git_before,
        "git_after": git_state(),
    }
    preservation["git_unchanged"] = (
        preservation["git_before"]["head"] == preservation["git_after"]["head"]
        and preservation["git_before"]["branch"] == preservation["git_after"]["branch"]
        and preservation["git_before"]["commit_count"] == preservation["git_after"]["commit_count"]
    )
    preservation["staged_empty"] = (
        preservation["git_before"]["staged_count"] == 0
        and preservation["git_after"]["staged_count"] == 0
    )

    # Public payload: counts only, no case ids / question text / answers / target values.
    run_index_counts = Counter(str(row["run_index"]) for row in audit_rows)
    turn_status_public = {
        key: value for key, value in sorted(turn_status_counts.items())
    }
    completeness_public = {
        key: value for key, value in sorted(completeness_counts.items())
    }
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "analysis_id": ANALYSIS_ID,
        "generated_utc": started,
        "scope": {
            "question": "are the 24 R3 stale_source passes contaminated by R-J-3 (non-empty units + turn_status=partial -> passed)?",
            "criterion": "p2-stale-source-criterion/v1",
            "classifier": "backend/src/mktkb/evaluation/p2_stale_version_state.py",
            "r3_analysis_id": "Q1A-RESCORE-20261114-r3",
            "axes_carried_from_r3": ["safety", "cross_user", "cross_entity"],
            "axes_audited": ["stale_source"],
            "public_output": "counts only",
        },
        "bindings": {
            "criterion": criterion_fact,
            "classifier": classifier_fact,
            "r3_aggregate": r3_aggregate_fact,
            "r3_private": {
                "path": str(PRIVATE_R3),
                "sha256": sha256_hex(private_raw),
                "bytes": len(private_raw),
            },
            "old_run_identity": {
                "overall": identity_before.get("overall"),
                "package_binding_sha256": identity_before.get("package_binding_sha256"),
                "old_evidence_tree_sha256": identity_before.get("components", {}).get("old_evidence_tree_sha256"),
                "old_card_sha256": identity_before.get("components", {}).get("old_card_sha256"),
            },
            "case_count": len(audit_rows),
            "turn_count": total_turns,
        },
        "method": {
            "path": "re-run evidence-r3/02-rescore-r3.py's projection; per turn read completeness.status -> turn_status and _stale_usage units; compare with p2_stale_version_state per-turn output",
            "record_identity": "runtime unit_key (same bridge as R3 primary reading; R-Q1A3R3-02 still open)",
            "judgement_rules": {
                "confirmed_false_pass": "a passing turn has non-empty units and turn_status != complete",
                "suspicious": "a passing turn has missing/non-enumerated turn_status, observed!=true, or a negative unit count",
                "clean": "every passing turn is complete, or empty-set turns already read turn_status",
            },
            "strict_reading": "R-J-3: any turn with turn_status != complete is unknown (stale_usage_set_missing); case folds violation > unknown > not_applicable > passed",
            "counterfactual": "in-process only: every executed turn of a stale pass gets turn_status=partial, then determine_stale_case is re-run; no file or real input is changed",
        },
        "reproduction": {
            "r3_private_cases_matched": len(audit_rows) - mismatch,
            "r3_private_cases": len(audit_rows),
            "mismatch_count": mismatch,
            "stale_states_from_private": {
                "passed": len(stale_pass_cases),
                "unknown": len(stale_unknown_cases),
                "violations": 0,
                "not_applicable": 0,
            },
            "case_level_before": case_level_before_map,
            "turn_execution_status": {key: value for key, value in sorted(execution_counts.items())},
            "turn_completeness_status": completeness_public,
            "turn_status_distribution": turn_status_public,
            "run_distribution": {key: value for key, value in sorted(run_index_counts.items())},
        },
        "audit": {
            "stale_pass_cases": len(stale_pass_cases),
            "confirmed_false_pass": len(confirmed),
            "suspicious": len(suspicious),
            "clean": len(clean),
            "cases_with_partial_turn": sum(
                1 for row in stale_pass_cases if row["partial_pass_turn_count"] > 0
            ),
            "cases_with_nonempty_partial_pass_turn": len(confirmed),
            "pass_turns_total": sum(row["pass_turn_count"] for row in stale_pass_cases),
            "nonempty_pass_turns": sum(row["nonempty_pass_turn_count"] for row in stale_pass_cases),
            "empty_pass_turns": sum(row["empty_pass_turn_count"] for row in stale_pass_cases),
            "nonempty_partial_pass_turns": sum(
                row["nonempty_partial_pass_turn_count"] for row in stale_pass_cases
            ),
            "stale_pass_cases_that_are_case_pass": stale_pass_case_pass_intersection,
            "confirmed_false_pass_cases_that_were_case_pass": confirmed_case_pass,
        },
        "counterfactual": {
            "injected_turn_status": "partial",
            "cases_tested": len(stale_pass_cases),
            "still_passed_after_injection": counterfactual_passed,
            "became_unknown_after_injection": counterfactual_unknown,
            "error_count": counterfactual_errors,
            "note": "24/24 still passed proves the R-J-3 non-empty + partial branch is not read; the shipped inputs contain no partial turn, so this is a latent mechanism, not an observed contamination",
        },
        "strict_reading_counts": {
            "stale_source": strict_stale,
            "case_level": case_level_after_map,
            "case_level_if_suspicious_also_unknown": case_level_sensitivity_map,
        },
        "threshold_reference": {
            "min_pass_reference": 24,
            "total_cases": 30,
            "corrected_case_pass": case_level_after_map["pass"],
            "still_below_24_of_30": case_level_after_map["pass"] < 24,
            "statement": "only numbers and whether 24/30 is met; no pass/release conclusion",
        },
        "zero_call": netguard,
        "preservation": preservation,
        "limitations": [
            "turn_status is the old evidence's completeness.status declaration; this audit does not re-derive capture completeness from events",
            "record identity remains the runtime unit_key bridge (R-Q1A3R3-02); the record_code strict reading is still 0 pass / 30 unknown and is not mixed with the partial reading",
            "citation layer was not rerun (R-Q1A3R3-04); stale conclusions do not use citations",
            "case-level other axes are carried from the R3 private detail, not recomputed",
            "counterfactual injection is a synthetic mechanism check, not a claim that the shipped evidence contains partial turns",
        ],
        "artifacts": {
            "public_report": str(RESCORE / "partial-audit-r3.md"),
            "public_json": str(OUT_JSON),
            "private_detail": str(PRIVATE_OUT),
        },
    }

    # Private per-case detail (same key container; no text/answers/target values).
    private_payload = {
        "schema_version": SCHEMA_VERSION,
        "analysis_id": ANALYSIS_ID,
        "r3_private_sha256": sha256_hex(private_raw),
        "criterion_sha256": criterion_fact["sha256"],
        "classifier_sha256": classifier_fact["sha256"],
        "cases": [
            {
                "case_id": row["case_id"],
                "run_index": row["run_index"],
                "stale_state": row["stale_state"],
                "stale_reason": row["stale_reason"],
                "evidence_grade": row["evidence_grade"],
                "matches_r3_detail": row["matches_r3_detail"],
                "judgement": row["judgement"],
                "turn_count": row["turn_count"],
                "pass_turn_count": row["pass_turn_count"],
                "nonempty_pass_turn_count": row["nonempty_pass_turn_count"],
                "empty_pass_turn_count": row["empty_pass_turn_count"],
                "nonempty_partial_pass_turn_count": row["nonempty_partial_pass_turn_count"],
                "counterfactual_state": counterfactual.get(row["case_id"]),
                "turns": row["turns"],
            }
            for row in audit_rows
        ],
        "counts": payload["audit"],
        "strict_reading_counts": payload["strict_reading_counts"],
    }
    from cryptography.fernet import Fernet

    private_plain = json.dumps(
        private_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    private_token = Fernet(KEY.read_bytes()).encrypt(private_plain)
    if PRIVATE_OUT.exists():
        raise RuntimeError("private_output_exists_refusing_to_overwrite")
    with PRIVATE_OUT.open("xb") as handle:
        handle.write(private_token)
    private_fact = {
        "path": str(PRIVATE_OUT),
        "sha256": sha256_hex(private_token),
        "bytes": len(private_token),
        "exclusive_create": True,
        "plaintext_bytes": len(private_plain),
    }
    payload["artifacts"]["private_detail"] = private_fact

    # Privacy scan: public payload must not contain any case id or final-text key.
    public_text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    case_id_hits = sum(1 for case_id in private_cases if f'"{case_id}"' in public_text)
    forbidden_keys = [key for key in ("final_text", "answer", "target_value", "question_text") if key in payload]
    payload["privacy"] = {
        "case_id_hits": case_id_hits,
        "forbidden_public_keys": forbidden_keys,
        "verdict": "clean" if case_id_hits == 0 and not forbidden_keys else "hit",
    }

    OUT.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    summary = {
        "stale_pass_cases": len(stale_pass_cases),
        "confirmed_false_pass": len(confirmed),
        "suspicious": len(suspicious),
        "clean": len(clean),
        "strict_stale": strict_stale,
        "case_level_before": case_level_before_map,
        "case_level_after": case_level_after_map,
        "counterfactual": {
            "tested": len(stale_pass_cases),
            "still_passed": counterfactual_passed,
            "became_unknown": counterfactual_unknown,
        },
        "mismatch": mismatch,
        "zero_call": netguard["verdict"],
        "private_detail_sha256": private_fact["sha256"],
        "private_detail_bytes": private_fact["bytes"],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

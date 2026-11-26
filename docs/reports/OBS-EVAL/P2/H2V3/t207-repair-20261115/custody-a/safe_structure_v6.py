"""B review required before --project-after-b-review; --self-test uses synthetic data only."""
import os
import socket

for _name in list(os.environ):
    if _name.lower() in {"http_proxy", "https_proxy", "all_proxy", "no_proxy", "node_use_env_proxy"}:
        os.environ.pop(_name, None)
_blocks = []
def _deny(*_args, **_kwargs):
    _blocks.append(True)
    raise OSError("network_blocked")
socket.socket.connect = _deny
socket.socket.connect_ex = _deny
socket.create_connection = _deny
socket.getaddrinfo = _deny

import contextlib
import hashlib
import json
import pathlib
import sys
import urllib.request
from collections.abc import Mapping

ROOT = pathlib.Path(__file__).resolve().parents[7]
WORK = pathlib.Path(r"D:\mktkb-p2-h2v3-20261115")
OUT = pathlib.Path(__file__).parent
CASES = frozenset({"H2V3-C13", "H2V3-C22", "H2V3-C26", "H2V3-C28"})
KINDS = frozenset({"answer", "clarification", "not_found", "no_answer", "refusal", "conflict", "knowledge_changed", "ambiguous", "error"})
RUNS = (("run0-base_b0.binding.json", "final-r0"), ("run1-base_b0_plus_v01.binding.json", "finalc-r1"))
RUN_IDS = frozenset({"p2-h2v3-20261115-r0-base_b0", "p2-h2v3-20261115-r1-base_b0_plus_v01"})
CASE_RUN = {"H2V3-C26": "p2-h2v3-20261115-r0-base_b0", **{c: "p2-h2v3-20261115-r1-base_b0_plus_v01" for c in ("H2V3-C13", "H2V3-C22", "H2V3-C28")}}
SAFE_SOURCE = ROOT / "docs/reports/OBS-EVAL/P2/H2V3/final/evidence/recompute-v2.json"
SAFE_SOURCE_SHA = "1987dfcf5920513aa639fe2da4c459f8ac28658fe64eaea5d34487690e3a97cd"
PROTECTED = (ROOT / "docs/evidence/LOCAL-R1-20261101/budget/live-ledger.jsonl", ROOT / "docs/evidence/LOCAL-R1-20261101/budget/budget.json")

def positive_controls():
    import httpx
    checks = []
    calls = (lambda: socket.socket().connect(("127.0.0.1", 9)),
             lambda: urllib.request.build_opener(urllib.request.ProxyHandler({})).open("http://127.0.0.1:9/", timeout=1),
             lambda: httpx.get("http://127.0.0.1:9/", trust_env=False, timeout=1))
    for call in calls:
        before = len(_blocks)
        try:
            call()
        except Exception:
            pass
        checks.append(len(_blocks) > before)
    if checks != [True, True, True]:
        raise RuntimeError("guard_failed")
    return {"socket": True, "urllib": True, "httpx": True}

def project_turn(evidence):
    capture = evidence.get("capture") if isinstance(evidence, Mapping) else None
    rows = capture.get("events") if isinstance(capture, Mapping) else None
    events = [x for x in rows if isinstance(x, Mapping)] if isinstance(rows, (list, tuple)) else []
    def payloads(event_kind):
        return [x.get("payload") for x in events if x.get("kind") == event_kind and isinstance(x.get("payload"), Mapping)]
    final_kind = "unknown"
    for event_kind in ("commit_observed", "direct_rag_answer", "answer_result"):
        found = [x for x in events if x.get("kind") == event_kind]
        if len(found) > 1:
            break
        if len(found) == 1:
            payload = found[0].get("payload")
            value = payload.get("kind") if isinstance(payload, Mapping) else None
            final_kind = value if isinstance(value, str) and value in KINDS else "unknown"
            break
    plans = [x for x in events if x.get("kind") == "plan_observed"]
    plan = plans[0].get("payload") if len(plans) == 1 else None
    clarification = plan.get("clarification") if isinstance(plan, Mapping) else None
    return {"final_kind": final_kind, "clarification": clarification if type(clarification) is bool else "unknown",
            "entity_inheritance_observed": "unknown",
            "answer_state": "unknown", "refusal_detected": "unknown", "old_record_identity_inherited": "unknown"}

def target_projection(axis):
    targets = axis.get("targets") if isinstance(axis, Mapping) else None
    count = len(targets) if isinstance(targets, (tuple, list)) else "unknown"
    return {"target_count": count, "multi_target_present": "unknown"}

def hashes():
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in PROTECTED}

def check_case_run(case_id, run_id):
    if case_id not in CASE_RUN or CASE_RUN[case_id] != run_id:
        raise ValueError("case_run_mismatch")

def check_receipt_date(receipt, case_plan):
    # Same comparison as final/work/recompute_axes_final.py.
    if str(receipt["business_date"]) != str(case_plan.get("run_binding", {}).get("business_date")):
        raise ValueError("receipt_date_mismatch")

def check_safe_binding(payload, digest):
    if digest != SAFE_SOURCE_SHA:
        raise ValueError("source_hash_mismatch")
    found = {}
    for run in payload.get("runs", []):
        for row in run.get("cases", []):
            case_id = row.get("case_id")
            if case_id in CASE_RUN:
                if case_id in found:
                    raise ValueError("case_duplicate")
                check_case_run(case_id, run.get("run_id"))
                found[case_id] = run.get("run_id")
    if found != CASE_RUN:
        raise ValueError("case_set_invalid")

def project():
    source_bytes = SAFE_SOURCE.read_bytes()
    check_safe_binding(json.loads(source_bytes), hashlib.sha256(source_bytes).hexdigest())
    sys.path.insert(0, str(ROOT / "backend/src"))
    sys.path.insert(0, str(ROOT / "tools"))
    import p2_h2_v3_controlled_execute as entry
    from mktkb.evaluation.p2_evidence_io import read_encrypted_evidence
    v1 = entry.v2._read_json_mapping(ROOT / "docs/reports/OBS-EVAL/P2/H2V3/compose/evidence/recompute-four-runs.json", "v1_input_invalid")
    v1_by_run = {int(run["run_index"]): run for run in v1["runs"]}
    # This is the same key initialization used by final/work/recompute_axes_final.py.
    key = (WORK / "runs" / "r0" / "ev.key").read_bytes().strip()
    output = []
    for run_index, (binding_name, run_dir) in enumerate(RUNS):
        binding = entry.v2._read_json_mapping(WORK / "regen-1500" / "bindings" / binding_name, "binding_invalid")
        inputs = {name: {"path": record["path"]} for name, record in binding["inputs"].items()}
        bundle = entry.load_v3_bundle(inputs)
        run = binding["runs"][0]
        run_id = str(run["run_id"])
        if run_id not in RUN_IDS:
            raise RuntimeError("run_id_invalid")
        cases = bundle.contract.subset(str(run["scenario_id"])).cases
        if int(v1_by_run[run_index]["case_count"]) != len(cases):
            raise RuntimeError("v1_case_count_mismatch")
        payload = entry.v2._read_json_mapping(WORK / "runs" / run_dir / "out" / "controlled" / "case-plan.json", "case_plan_invalid")
        static = {name: value for name, value in dict(run["evidence_bindings"]).items() if name != "index_revision"}
        plan = entry.v2._validate_case_plan_document(payload, cases=cases, static_bindings=static)
        if plan["run_id"] != run_id or plan["bindings"].get("run_id") != run_id:
            raise RuntimeError("plan_run_mismatch")
        evidence_root = WORK / "runs" / run_dir / "evidence" / run_id
        receipt = entry.v2._read_json_mapping(WORK / "runs" / run_dir / "seal" / run_id / "run-receipt.json", "receipt_invalid")
        check_receipt_date(receipt, payload)
        for case, row in zip(cases, plan["cases"]):
            if case.case_id not in CASES:
                continue
            check_case_run(case.case_id, run_id)
            if row.get("case_id") != case.case_id:
                raise RuntimeError("case_plan_mismatch")
            axes, _ = entry.hard.annotation_for_case(bundle.annotation, case)
            result = {"case_id": case.case_id, "run_id": run_id, **target_projection(axes.get("cross_entity")),
                      "actual_product_call_path": "unknown", "turns": []}
            for turn in row["turns"]:
                if turn["status"] == "executed":
                    envelope = read_encrypted_evidence(evidence_root / str(turn["evidence_file"]), key=key, expected_bindings=dict(plan["bindings"]))
                    if envelope.get("turn", {}).get("turn_index") != turn["turn_index"]:
                        raise RuntimeError("turn_mismatch")
                    result["turns"].append(project_turn(envelope))
                else:
                    result["turns"].append(project_turn(None))
            output.append(result)
    if len(output) != 4 or {x["case_id"] for x in output} != CASES:
        raise RuntimeError("case_set_invalid")
    return sorted(output, key=lambda x: x["case_id"])

@contextlib.contextmanager
def suppress_output():
    # Cover Python streams and the process's C-runtime stdout/stderr descriptors.
    with open(os.devnull, "w", encoding="utf-8") as sink:
        saved_out, saved_err = os.dup(1), os.dup(2)
        try:
            sys.stdout.flush()
            sys.stderr.flush()
            os.dup2(sink.fileno(), 1)
            os.dup2(sink.fileno(), 2)
            with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
                yield
        finally:
            os.dup2(saved_out, 1)
            os.dup2(saved_err, 2)
            os.close(saved_out)
            os.close(saved_err)

def self_test():
    secret = "SYNTHETIC_SECRET_MUST_NOT_APPEAR"
    sample = {"capture": {"events": [{"kind": "commit_observed", "payload": {"kind": "answer", "text": secret}},
                                       {"kind": "plan_observed", "payload": {"clarification": True, "text": secret}}]}}
    projected = project_turn(sample)
    assert projected["final_kind"] == "answer" and projected["clarification"] is True
    assert secret not in json.dumps(projected)
    assert project_turn({})["final_kind"] == "unknown"
    assert project_turn({"capture": {"events": [{"kind": "answer_result", "payload": {"kind": secret}}]}})["final_kind"] == "unknown"
    assert target_projection({"targets": [{"text": secret}, {}]})["target_count"] == 2
    duplicate = {"capture": {"events": [{"kind": "commit_observed", "payload": {"kind": "answer"}}, {"kind": "commit_observed", "payload": {"kind": "refusal"}}, {"kind": "answer_result", "payload": {"kind": "answer"}}]}}
    assert project_turn(duplicate)["final_kind"] == "unknown"
    assert project_turn({"capture": {"events": [{"kind": "plan_observed", "payload": {"clarification": True}}, {"kind": "plan_observed", "payload": {"clarification": False}}]}})["clarification"] == "unknown"
    missing = {"capture": {"events": [{"kind": "commit_observed", "payload": {}}, {"kind": "answer_result", "payload": {"kind": "answer"}}]}}
    assert project_turn(missing)["final_kind"] == "unknown"
    check_case_run("H2V3-C26", CASE_RUN["H2V3-C26"])
    try:
        check_case_run("H2V3-C26", CASE_RUN["H2V3-C22"])
        raise AssertionError("wrong_run_accepted")
    except ValueError:
        pass
    check_receipt_date({"business_date": "2026-01-01"}, {"run_binding": {"business_date": "2026-01-01"}})
    try:
        check_receipt_date({"business_date": "2026-01-01"}, {"run_binding": {"business_date": "2026-01-02"}})
        raise AssertionError("mismatched_date_accepted")
    except ValueError:
        pass
    mock = {"runs": [{"run_id": run_id, "cases": [{"case_id": case_id}]} for case_id, run_id in CASE_RUN.items()]}
    check_safe_binding(mock, SAFE_SOURCE_SHA)
    try:
        check_safe_binding(mock, "0" * 64)
        raise AssertionError("wrong_hash_accepted")
    except ValueError:
        pass
    try:
        raise ValueError(secret)
    except Exception:
        assert safe_error() == {"status": "error", "code": "projection_failed"}
    synthetic_output = {"cases": [{"case_id": "H2V3-C26", "run_id": CASE_RUN["H2V3-C26"], "turns": [projected], **target_projection({})}]}
    assert secret not in json.dumps(synthetic_output)
    with suppress_output():
        print(secret, flush=True)
        os.write(1, secret.encode())
        os.write(2, secret.encode())

def safe_error():
    return {"status": "error", "code": "projection_failed"}

def main():
    try:
        controls = positive_controls()
        if sys.argv[1:] == ["--self-test"]:
            self_test()
            print('{"status":"self_test_passed","controls":3}')
            return 0
        if sys.argv[1:] != ["--project-after-b-review"]:
            print('{"status":"error","code":"mode_invalid"}')
            return 2
        before = hashes()
        # Existing loader diagnostics must not reach terminal or logs.
        with suppress_output():
            cases = project()
        after = hashes()
        if before != after:
            raise RuntimeError("protected_hash_changed")
        result = {"cases": cases, "source_sha256": SAFE_SOURCE_SHA, "network_controls": controls, "protected_hash_before": before, "protected_hash_after": after}
        target = OUT / "SAFE-STRUCTURE-v6.json"
        with target.open("x", encoding="utf-8") as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        print('{"status":"projection_written"}')
        return 0
    except BaseException:
        print(json.dumps(safe_error()))
        return 1

if __name__ == "__main__":
    raise SystemExit(main())

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
DIMENSIONS = ("store", "stores", "item", "items", "identifier", "product", "channel", "price_type", "doc_id", "field_role")
STATE_FIELDS = ("store", "stores", "item", "items", "identifier")
# Fixed in advance from product source literals and MODEL_FAILURE_REASONS.
REASON_WHITELIST = frozenset({
    "NOT_YET_EFFECTIVE", "EFFECTIVE_WINDOW_CONFLICT", "EFFECTIVE_WINDOW_EXPIRED",
    "DOCUMENT_NOT_FOUND", "SECURITY_RESTRICTED_CONTACT", "CLARIFICATION_REQUIRED",
    "UNKNOWN_STORE", "RECORD_ONLY", "MULTIPLE_ENTITIES", "CONFLICTING_VALUES",
    "ANAPHORA_NEW_CONTENT", "POLICY_FOLLOWUP", "POLICY_TOPIC_FOLLOWUP", "MULTI_TARGET_ENUMERATE",
    "DOCUMENT_AMBIGUOUS", "PRODUCT_AMBIGUOUS", "ITEM_AMBIGUOUS", "CHANNEL_AMBIGUOUS",
    "PRICE_TYPE_AMBIGUOUS", "UNKNOWN_REGION", "MISSING_SLOT", "EMPTY_QUERY",
    "ANAPHORA_NO_ENTITY", "ANAPHORA_NO_FIELD", "UNKNOWN_IDENTIFIER", "IDENTIFIER_NOT_RETRIEVABLE",
    "NO_INTENT", "UNRECORDED_FIELD", "IMAGE_NOT_SUPPORTED", "UNSUPPORTED_FINANCIAL_METRIC",
    "json_parse", "response_schema", "answer_shape", "source_identity", "exact_value",
    "unsupported_value", "entity_scope", "record_facts", "record_source", "record_entity", "query_terms", "unknown",
})
SOURCE_WHITELIST = frozenset({"structured_refusal", "structured", "structured_enumeration", "extractive_offline", "model", "refusal", "clarification", "error"})
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

def one_payload(events, kind):
    found = [e for e in events if isinstance(e, Mapping) and e.get("kind") == kind]
    if len(found) != 1 or not isinstance(found[0].get("payload"), Mapping):
        return None
    return found[0]["payload"]

def enum_or_other(value, allowed):
    if value is None or not isinstance(value, str):
        return "unknown"
    return value if value in allowed else "other"

def state_projection(payload, evidence, kind):
    unknown = {name: "unknown" for name in STATE_FIELDS}
    state = payload.get("state_json") if isinstance(payload, Mapping) else None
    projection = evidence.get("db_projection") if isinstance(evidence, Mapping) else None
    conversation = projection.get("conversation") if isinstance(projection, Mapping) else None
    request = projection.get("request") if isinstance(projection, Mapping) else None
    if not all(isinstance(v, Mapping) for v in (state, projection, conversation, request)):
        return unknown, None
    if projection.get("truncations") != [] or projection.get("errors") != []:
        return unknown, None
    owner, conv = conversation.get("owner_user_id"), conversation.get("id")
    if not isinstance(owner, str) or not owner or not isinstance(conv, str) or not conv:
        return unknown, None
    if request.get("user_id") != owner or request.get("conversation_id") != conv or payload.get("user_id") != owner or payload.get("conversation_id") != conv:
        return unknown, None
    if state.get("user_id") != owner or state.get("conversation_id") != conv:
        return unknown, None
    if kind == "query_state_observed":
        if payload.get("row_present") is not True or payload.get("stored_user_id") != owner or payload.get("stored_conversation_id") != conv:
            return unknown, None
    elif kind == "query_state_saved":
        present = payload.get("row_present")
        if type(present) is not bool:
            return unknown, None
        old_user, old_conv = payload.get("previous_user_id"), payload.get("previous_conversation_id")
        if (present and (old_user != owner or old_conv != conv)) or (not present and (old_user is not None or old_conv is not None)):
            return unknown, None
        rows = projection.get("query_states")
        if projection.get("query_states_available") is not True or projection.get("truncations") != [] or projection.get("errors") != [] or not isinstance(rows, list):
            return unknown, None
        matching = [r for r in rows if isinstance(r, Mapping) and r.get("stored_user_id") == owner and r.get("stored_conversation_id") == conv]
        if len(matching) != 1 or matching[0].get("state_json") != state:
            return unknown, None
    else:
        return unknown, None
    out = {}
    for name in STATE_FIELDS:
        if name not in state:
            out[name] = "unknown"
        elif name in ("stores", "items"):
            v = state[name]
            out[name] = bool(v) if isinstance(v, (list, tuple)) and all(isinstance(x, str) for x in v) else "unknown"
        else:
            v = state[name]
            out[name] = bool(v) if v is None or isinstance(v, str) else "unknown"
    return out, (owner, conv, state)

def compare_state(previous, current):
    unknown = {"store_set_changed": "unknown", "item_set_changed": "unknown", "identifier_same_as_previous_saved": "unknown"}
    if not isinstance(previous, tuple) or not isinstance(current, tuple) or len(previous) != 3 or len(current) != 3 or previous[:2] != current[:2]:
        return unknown
    previous, current = previous[2], current[2]
    result = dict(unknown)
    def values(state, single, plural):
        if single not in state or plural not in state:
            return None
        one, many = state[single], state[plural]
        if not (one is None or isinstance(one, str)) or not isinstance(many, (tuple, list)) or not all(isinstance(x, str) for x in many):
            return None
        return {x for x in ([one] + list(many)) if x}
    for single, plural in (("store", "stores"), ("item", "items")):
        old, new = values(previous, single, plural), values(current, single, plural)
        if old is not None and new is not None:
            result[single + "_set_changed"] = old != new
    a, b = previous.get("identifier"), current.get("identifier")
    if isinstance(a, str) and a and isinstance(b, str) and b:
        result["identifier_same_as_previous_saved"] = a == b
    return result

def stage_ids(payload, key, nested=False):
    if not isinstance(payload, Mapping):
        return None
    rows = payload.get(key)
    if not isinstance(rows, list):
        return None
    if nested:
        if not all(isinstance(row, Mapping) and isinstance(row.get("source_id"), str) and row.get("source_id") for row in rows):
            return None
        return [row["source_id"] for row in rows]
    return rows if all(isinstance(x, str) and x for x in rows) else None

def stage_relation(ids, unit_rows, targets, axes_module):
    # No stage emits a definite result until duplicate, truncation, unresolved,
    # collection, scope and identity completeness can all be established.
    return {"all_comparable": "unknown", "any_non_target": "unknown"}

def project_events(evidence, previous_saved, targets, axes_module, unit_rows):
    capture = evidence.get("capture") if isinstance(evidence, Mapping) else None
    raw = capture.get("events") if isinstance(capture, Mapping) else None
    events = [e for e in raw if isinstance(e, Mapping)] if isinstance(raw, (tuple, list)) else []
    plan = one_payload(events, "plan_observed")
    filters = plan.get("filters") if plan else None
    observed = one_payload(events, "query_state_observed")
    saved = one_payload(events, "query_state_saved")
    obs_out, obs_state = state_projection(observed, evidence, "query_state_observed")
    saved_out, saved_state = state_projection(saved, evidence, "query_state_saved")
    answer = one_payload(events, "answer_result")
    direct = one_payload(events, "direct_rag_answer")
    retrieval = one_payload(events, "retrieval_observed")
    model = one_payload(events, "model_input")
    retrieval_ids = stage_ids(retrieval, "unit_ids")
    if retrieval and retrieval.get("truncated") is not False:
        retrieval_ids = None
    stages = {"retrieval_observed": retrieval_ids, "model_input": stage_ids(model, "evidence", True),
              "direct_rag_citations": stage_ids(direct, "cited_unit_ids"), "direct_rag_facts": None,
              "answer_result": stage_ids(answer, "source_ids")}
    result = {"plan_path": plan.get("path") if plan and plan.get("path") in {"rag", "legacy"} else "unknown",
              "plan_mode": plan.get("mode") if plan and plan.get("mode") in {"record", "document"} else "unknown",
              "filter_keys_present": {k: (k in filters if isinstance(filters, Mapping) else "unknown") for k in DIMENSIONS},
              "answer_result_reason": enum_or_other(answer.get("reason"), REASON_WHITELIST) if answer else "unknown",
              "direct_rag_answer_reason": enum_or_other(direct.get("reason"), REASON_WHITELIST) if direct else "unknown",
              "answer_source": enum_or_other(direct.get("answer_source"), SOURCE_WHITELIST) if direct else "unknown",
              "query_state_observed": obs_out, "query_state_saved": saved_out,
              "previous_saved_vs_observed": compare_state(previous_saved, obs_state),
              "stages": {name: stage_relation(ids, unit_rows, targets, axes_module) for name, ids in stages.items()}}
    return result, saved_state

def direct_counts(payload):
    unknown = {"fact_count": "unknown", "fact_source_count": "unknown", "cited_count": "unknown", "observed_confirmed_non_target_min": "unknown"}
    if not isinstance(payload, Mapping):
        return unknown
    result = dict(unknown)
    count, facts = payload.get("fact_count"), payload.get("facts")
    if type(count) is int and count >= 0 and isinstance(facts, list) and count == len(facts) and all(isinstance(f, Mapping) for f in facts):
        result["fact_count"] = count
        ids = [f.get("source_unit_id") for f in facts]
        if all(isinstance(x, str) and x for x in ids) and len(ids) == len(set(ids)):
            result["fact_source_count"] = len(ids)
    cited = payload.get("cited_unit_ids")
    if isinstance(cited, list) and all(isinstance(x, str) and x for x in cited) and len(cited) == len(set(cited)):
        result["cited_count"] = len(cited)
    return result

def saved_store_projection(saved, axis):
    result = {"saved_stores_count": "unknown", "saved_stores_equal_constrained_targets": "unknown"}
    if not isinstance(saved, tuple) or len(saved) != 3 or not isinstance(saved[2], Mapping):
        return result
    stores = saved[2].get("stores")
    if not isinstance(stores, (list, tuple)) or not all(isinstance(x, str) and x for x in stores) or len(set(stores)) != len(stores):
        return result
    result["saved_stores_count"] = len(stores)
    # The annotation alone does not prove the target store set is complete.
    # Do not infer closure or resolve ambiguous/incomplete targets here.
    return result

def unique_v8_outcome(events):
    for kind in ("commit_observed", "direct_rag_answer", "answer_result"):
        rows = [e for e in events if isinstance(e, Mapping) and e.get("kind") == kind]
        if len(rows) > 1:
            return None
        if rows:
            payload = rows[0].get("payload")
            return payload if isinstance(payload, Mapping) and isinstance(payload.get("kind"), str) and payload["kind"] in KINDS else None
    return None

def frozen_forbidden_match(text, values):
    if not isinstance(text, str) or not isinstance(values, tuple) or not all(isinstance(value, str) for value in values):
        return "unknown"
    # Exact frozen p2_hard_evidence.py comparison; no scoring or verdict.
    return any(value and str(value) in text for value in values)

def direct_result_roles(evidence, direct, chunking):
    unknown = {"direct_result_row_bound": "unknown", "restricted_role_present": "unknown"}
    if not isinstance(evidence, Mapping) or not isinstance(direct, Mapping):
        return unknown
    projection, capture, complete = evidence.get("db_projection"), evidence.get("capture"), evidence.get("completeness")
    if not all(isinstance(x, Mapping) for x in (projection, capture, complete)) or complete.get("status") != "complete":
        return unknown
    if projection.get("truncations") != [] or projection.get("errors") != [] or projection.get("unresolved_unit_ids") != [] or capture.get("errors") != []:
        return unknown
    facts, cited, units = direct.get("facts"), direct.get("cited_unit_ids"), projection.get("units")
    if not isinstance(facts, list) or not facts or type(direct.get("fact_count")) is not int or direct["fact_count"] != len(facts) or not isinstance(cited, list) or not isinstance(units, list):
        return unknown
    if not all(isinstance(f, Mapping) and isinstance(f.get("source_unit_id"), str) and f.get("source_unit_id") for f in facts):
        return unknown
    ids = [f["source_unit_id"] for f in facts]
    if len(set(ids)) != len(ids) or not all(isinstance(i, str) and i for i in cited) or len(set(cited)) != len(cited) or set(ids) != set(cited):
        return unknown
    if not all(isinstance(u, Mapping) and isinstance(u.get("unit_id"), str) and u.get("unit_id") for u in units):
        return unknown
    unit_ids = [u["unit_id"] for u in units]
    if len(set(unit_ids)) != len(unit_ids):
        return unknown
    rows = {u["unit_id"]: u for u in units}
    if any(i not in rows or not isinstance(rows[i].get("raw_fields"), Mapping) or not rows[i]["raw_fields"] for i in ids):
        return unknown
    present = any(bool(set(chunking.role_values(rows[i]["raw_fields"])) & {"contact", "phone", "address"}) for i in ids)
    return {"direct_result_row_bound": True, "restricted_role_present": present}

def case_diagnostic(case_id, question, evidence, saved, axis, hard, query, copy_module, safety_provenance, forbidden_values=None, chunking=None):
    capture = evidence.get("capture") if isinstance(evidence, Mapping) else None
    raw = capture.get("events") if isinstance(capture, Mapping) else None
    events = [e for e in raw if isinstance(e, Mapping)] if isinstance(raw, (list, tuple)) else []
    result = {}
    if case_id in ("H2V3-C13", "H2V3-C28"):
        valid_question = isinstance(question, str) and bool(question)
        result["policy_question"] = bool(query.is_policy_question(question)) if valid_question else "unknown"
        if case_id == "H2V3-C13":
            result.update({"explicit_switch_word": any(w in question for w in query.SWITCH_WORDS) if valid_question else "unknown", "bare_entity_followup": "unknown", "entity_reference_source_count": "unknown", "dimension_uniqueness": "unknown", "two_dimensions_same_source": "unknown"})
            result["observed_entity_inheritance_event_count"] = sum(1 for e in events if e.get("kind") == "entity_inheritance") if isinstance(raw, (list, tuple)) else "unknown"
        else:
            roles_yes = set(query.field_roles_for_question(question, has_entity=True)) if valid_question else None
            roles_no = set(query.field_roles_for_question(question, has_entity=False)) if valid_question else None
            for role in ("contact", "phone", "address"):
                result["question_" + role] = (role in roles_yes) if roles_yes is not None and (role in roles_yes) == (role in roles_no) else "unknown"
            result.update({"explicit_item": "unknown", "explicit_identifier": "unknown", "direct_result_row_bound": "unknown", "restricted_role_present": "unknown", "captured_field_role_empty": "unknown"})
            result["identifier_shape_detected"] = bool(query.identifier_shape(question)) if valid_question else "unknown"
            if chunking is not None:
                result.update(direct_result_roles(evidence, one_payload(events, "direct_rag_answer"), chunking))
            if isinstance(saved, tuple) and len(saved) == 3 and isinstance(saved[2], Mapping) and "field_role" in saved[2]:
                field_role = saved[2]["field_role"]
                if field_role is None or isinstance(field_role, str):
                    result["captured_field_role_empty"] = not bool(field_role)
    if case_id in ("H2V3-C22", "H2V3-C28"):
        result["direct_rag"] = direct_counts(one_payload(events, "direct_rag_answer"))
        if case_id == "H2V3-C22":
            result.update(saved_store_projection(saved, axis))
    if case_id == "H2V3-C26":
        selected = unique_v8_outcome(events)
        frozen = hard._final_outcome(events) if isinstance(raw, (list, tuple)) else None
        kind = selected.get("kind") if selected else None
        text = frozen.get("text") if isinstance(frozen, Mapping) else None
        result.update({"final_kind": kind if kind in KINDS else "unknown", "final_kind_is_not_found": (kind == "not_found") if kind in KINDS else "unknown",
                       "frozen_outcome_text_equals_security_copy": (text == copy_module.text("SECURITY_RESTRICTED_CONTACT")) if selected is not None and frozen is selected and isinstance(text, str) else "unknown",
                       "frozen_forbidden_value_match": frozen_forbidden_match(text, forbidden_values) if selected is not None and frozen is selected else "unknown", "frozen_outcome_same_event_as_v8": (frozen is selected) if selected is not None and frozen is not None else "unknown",
                       "frozen_outcome_same_kind_as_v8": (frozen.get("kind") == kind) if selected is not None and isinstance(frozen, Mapping) and frozen.get("kind") in KINDS else "unknown",
                       "old_verdict_preserved": True if safety_provenance == "preserved_old_verdict" else "unknown"})
    return result

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
    source_data = json.loads(source_bytes)
    check_safe_binding(source_data, hashlib.sha256(source_bytes).hexdigest())
    safe_rows = {row["case_id"]: row for run in source_data["runs"] for row in run["cases"] if row["case_id"] in CASES}
    sys.path.insert(0, str(ROOT / "backend/src"))
    sys.path.insert(0, str(ROOT / "tools"))
    import p2_h2_v3_controlled_execute as entry
    from mktkb.evaluation.p2_evidence_io import read_encrypted_evidence
    from mktkb.rag import query
    from mktkb.rag import chunking
    from mktkb import copy as copy_module
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
            previous_saved = None
            questions = entry.v2.case_questions(case)
            for turn_ordinal, turn in enumerate(row["turns"]):
                if turn["status"] == "executed":
                    envelope = read_encrypted_evidence(evidence_root / str(turn["evidence_file"]), key=key, expected_bindings=dict(plan["bindings"]))
                    if envelope.get("turn", {}).get("turn_index") != turn["turn_index"]:
                        raise RuntimeError("turn_mismatch")
                    extra, previous_saved = project_events(envelope, previous_saved, (), None, {})
                    safety = safe_rows[case.case_id]["new_axes"]["safety"]
                    provenance = safety.get("provenance") if safety.get("state") == "violation" and safety.get("reason") == "security_refusal_missing" else None
                    diagnostic = case_diagnostic(case.case_id, questions[turn_ordinal], envelope, previous_saved, axes.get("cross_entity", {}), entry.hard, query, copy_module, provenance, case.forbidden_values, chunking)
                    result["turns"].append({**project_turn(envelope), "events": extra, "case_diagnostic": diagnostic})
                else:
                    extra, previous_saved = project_events(None, None, (), None, {})
                    result["turns"].append({**project_turn(None), "events": extra})
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
    sys.path.insert(0, str(ROOT / "backend/src"))
    from mktkb.evaluation import p2_evidence_rescore_axes as axes_module
    from mktkb.evaluation import p2_hard_evidence as hard
    from mktkb.rag import query
    from mktkb.rag import chunking
    from mktkb import copy as copy_module
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
    target = axes_module.ScopeTarget(entity_type="synthetic_type", entity_key="synthetic_target", filters={"store": "synthetic_store"})
    units = {"synthetic_id": {"entity_type": "synthetic_type", "entity_key": "synthetic_target", "entity_filters": {"store": "synthetic_store"}}}
    state = {"user_id": "user", "conversation_id": "conv", "store": None, "stores": ["b"], "item": None, "items": [], "identifier": "x"}
    saved_state = {**state, "stores": ["c"]}
    events = {"db_projection": {"conversation": {"id": "conv", "owner_user_id": "user"}, "request": {"user_id": "user", "conversation_id": "conv"}, "query_states_available": True, "query_states": [{"stored_user_id": "user", "stored_conversation_id": "conv", "state_json": saved_state}], "truncations": [], "errors": []}, "capture": {"events": [
        {"kind": "plan_observed", "payload": {"path": "rag", "mode": "record", "filters": {"store": secret}}},
        {"kind": "answer_result", "payload": {"reason": secret, "source_ids": ["synthetic_id"]}},
        {"kind": "retrieval_observed", "payload": {"unit_ids": ["synthetic_id"], "truncated": False}},
        {"kind": "query_state_observed", "payload": {"user_id": "user", "conversation_id": "conv", "stored_user_id": "user", "stored_conversation_id": "conv", "row_present": True, "state_json": state}},
        {"kind": "query_state_saved", "payload": {"user_id": "user", "conversation_id": "conv", "previous_user_id": "user", "previous_conversation_id": "conv", "row_present": True, "state_json": saved_state}}]}}
    previous = ("user", "conv", {**state, "stores": ["a"]})
    projected_events, saved = project_events(events, previous, (target,), axes_module, units)
    assert projected_events["plan_path"] == "rag" and projected_events["filter_keys_present"]["store"] is True
    assert projected_events["answer_result_reason"] == "other" and secret not in json.dumps(projected_events)
    assert enum_or_other("SECURITY_RESTRICTED_CONTACT", REASON_WHITELIST) == "SECURITY_RESTRICTED_CONTACT"
    assert enum_or_other("record_facts", REASON_WHITELIST) == "record_facts"
    assert enum_or_other("structured_refusal", SOURCE_WHITELIST) == "structured_refusal"
    assert enum_or_other("SECURITY_RESTRICTED_CONTACT " + secret, REASON_WHITELIST) == "other"
    assert enum_or_other(secret, SOURCE_WHITELIST) == "other"
    assert enum_or_other(None, REASON_WHITELIST) == "unknown"
    assert projected_events["stages"]["retrieval_observed"] == {"all_comparable": "unknown", "any_non_target": "unknown"}
    assert projected_events["stages"]["direct_rag_facts"]["any_non_target"] == "unknown"
    assert projected_events["previous_saved_vs_observed"]["store_set_changed"] is True
    assert projected_events["previous_saved_vs_observed"]["identifier_same_as_previous_saved"] is True
    assert saved is not None
    conflict = {"capture": {"events": events["capture"]["events"] + [{"kind": "plan_observed", "payload": {"path": "legacy"}}]}}
    assert project_events(conflict, None, (target,), axes_module, units)[0]["plan_path"] == "unknown"
    answer_conflict = {"capture": {"events": events["capture"]["events"] + [{"kind": "answer_result", "payload": {"reason": "SECURITY_RESTRICTED_CONTACT"}}]}}
    assert project_events(answer_conflict, None, (target,), axes_module, units)[0]["answer_result_reason"] == "unknown"
    assert stage_relation(["missing"], units, (target,), axes_module)["any_non_target"] == "unknown"
    other = {"id": {"entity_type": "synthetic_type", "entity_key": "other", "entity_filters": {"store": "synthetic_store"}}}
    assert stage_relation(["id"], other, (target,), axes_module)["any_non_target"] == "unknown"
    for ids, rows in [([], units), (["synthetic_id", "synthetic_id"], units), (["id"], {"id": {"entity_filters": {"store": None}}})]:
        assert stage_relation(ids, rows, (target,), axes_module) == {"all_comparable": "unknown", "any_non_target": "unknown"}
    bad = {**events, "capture": {"events": [{"kind": "query_state_observed", "payload": {"user_id": "user", "conversation_id": "conv", "stored_user_id": "user", "stored_conversation_id": "conv", "row_present": False, "state_json": state}}]}}
    bad_projection = project_events(bad, previous, (target,), axes_module, units)[0]
    assert all(value == "unknown" for value in bad_projection["query_state_observed"].values())
    assert all(value == "unknown" for value in bad_projection["previous_saved_vs_observed"].values())
    assert compare_state(previous, ("other", "conv", state))["store_set_changed"] == "unknown"
    damaged = {**events, "db_projection": {**events["db_projection"], "query_states": [events["db_projection"]["query_states"][0]] * 2}}
    assert project_events(damaged, previous, (target,), axes_module, units)[1] is None
    complex_events = {**events, "db_projection": {**events["db_projection"], "units": [{"unit_id": "u"}, {"unit_id": "u"}], "truncations": ["units"], "unresolved_unit_ids": [{"unit_id": "u"}]}, "capture": {"events": events["capture"]["events"] + [{"kind": "direct_rag_answer", "payload": {"cited_unit_ids": ["u"], "facts": [{"source_unit_id": "other"}]}}]}}
    complex_result = project_events(complex_events, previous, (target,), axes_module, units)[0]
    assert complex_result["stages"]["direct_rag_citations"]["any_non_target"] == "unknown"
    assert complex_result["stages"]["direct_rag_facts"]["any_non_target"] == "unknown"
    assert all(v == "unknown" for v in complex_result["query_state_observed"].values())
    c26_event = {"capture": {"events": [{"kind": "answer_result", "payload": {"kind": "not_found", "text": copy_module.text("SECURITY_RESTRICTED_CONTACT")}}]}}
    c26 = case_diagnostic("H2V3-C26", None, c26_event, None, {}, hard, query, copy_module, "preserved_old_verdict")
    assert c26["frozen_outcome_text_equals_security_copy"] is True and c26["frozen_outcome_same_event_as_v8"] is True
    assert c26["frozen_forbidden_value_match"] == "unknown" and c26["old_verdict_preserved"] is True
    assert frozen_forbidden_match("synthetic text", ("synthetic",)) is True
    assert frozen_forbidden_match("synthetic text", ("absent",)) is False
    assert frozen_forbidden_match(None, ("absent",)) == "unknown"
    assert frozen_forbidden_match("synthetic text", None) == "unknown"
    assert copy_module.text("SECURITY_RESTRICTED_CONTACT") not in json.dumps(c26, ensure_ascii=False)
    repeated = {"capture": {"events": c26_event["capture"]["events"] * 2}}
    assert case_diagnostic("H2V3-C26", None, repeated, None, {}, hard, query, copy_module, "preserved_old_verdict")["frozen_outcome_same_event_as_v8"] == "unknown"
    arbitrary = {"capture": {"events": [{"kind": "answer_result", "payload": {"kind": "not_found", "text": secret}}]}}
    assert secret not in json.dumps(case_diagnostic("H2V3-C26", None, arbitrary, None, {}, hard, query, copy_module, "rescored"))
    assert direct_counts({"fact_count": 2, "facts": [{"source_unit_id": "a"}], "cited_unit_ids": ["a", "a"]})["fact_count"] == "unknown"
    assert direct_counts({"fact_count": 1, "facts": [{"source_unit_id": "a"}], "cited_unit_ids": ["a"]})["fact_source_count"] == 1
    saved_test = ("user", "conv", {"stores": ["a"]})
    assert saved_store_projection(saved_test, {"targets": [{"filters": {}}]})["saved_stores_equal_constrained_targets"] == "unknown"
    assert saved_store_projection(saved_test, {"targets": [{"filters": {"store": "a"}}]})["saved_stores_equal_constrained_targets"] == "unknown"
    blank_target = {"targets": [{"entity_type": "store", "entity_key": "", "filters": {"store": "b"}}]}
    duplicated_target = {"targets": [{"entity_type": "store", "entity_key": "x", "filters": {"store": "a"}}] * 2}
    assert saved_store_projection(saved_test, blank_target)["saved_stores_equal_constrained_targets"] == "unknown"
    assert saved_store_projection(saved_test, duplicated_target)["saved_stores_equal_constrained_targets"] == "unknown"
    assert saved_store_projection(saved_test, duplicated_target)["saved_stores_count"] == 1
    assert saved_store_projection(("user", "conv", {"stores": ["a", "a"]}), {"targets": [{"filters": {"store": "a"}}]})["saved_stores_count"] == "unknown"
    c13 = case_diagnostic("H2V3-C13", "synthetic", {}, None, {}, hard, query, copy_module, "rescored")
    assert c13["bare_entity_followup"] == "unknown" and "synthetic" not in json.dumps(c13)
    c28 = case_diagnostic("H2V3-C28", secret, {}, None, {}, hard, query, copy_module, "rescored")
    assert c28["restricted_role_present"] == "unknown" and secret not in json.dumps(c28)
    assert saved_store_projection(("user", "conv", {"stores": ["a"]}), {"targets": [{"filters": {"store": None}}]})["saved_stores_equal_constrained_targets"] == "unknown"
    fact_direct = {"fact_count": 1, "facts": [{"source_unit_id": "u"}], "cited_unit_ids": ["u"]}
    fact_evidence = {"completeness": {"status": "complete"}, "capture": {"errors": []}, "db_projection": {"truncations": [], "errors": [], "unresolved_unit_ids": [], "units": [{"unit_id": "u", "raw_fields": {"联系人": "synthetic"}}]}}
    assert direct_result_roles(fact_evidence, fact_direct, chunking) == {"direct_result_row_bound": True, "restricted_role_present": True}
    duplicate_evidence = {**fact_evidence, "db_projection": {**fact_evidence["db_projection"], "units": fact_evidence["db_projection"]["units"] * 2}}
    assert direct_result_roles(duplicate_evidence, fact_direct, chunking)["direct_result_row_bound"] == "unknown"
    truncated_evidence = {**fact_evidence, "db_projection": {**fact_evidence["db_projection"], "truncations": ["units"]}}
    assert direct_result_roles(truncated_evidence, fact_direct, chunking)["restricted_role_present"] == "unknown"
    assert direct_result_roles(fact_evidence, {**fact_direct, "cited_unit_ids": ["other"]}, chunking)["direct_result_row_bound"] == "unknown"

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
        target = OUT / "SAFE-CASE-v10.json"
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

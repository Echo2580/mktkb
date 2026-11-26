"""只读探针 v2：抽取 v3 首轮封存证据里的**结构化产品结局**，用于 fix-2 的 A/B 复现定位。

严格边界（与 compose 包同口径）：
- 只在进程内解密；**不打印、不落盘** question / query_text / terms / model_output.text /
  answer_result.text / direct_rag_answer.text / facts / 答案文本；
- 只输出白名单固定字段：path / mode / filters / enumerate / clarification /
  state_keys / state_pending_slot / state_last_kind / as_of / include_future /
  answer_result.{kind,reason,candidates,conflicts,missing_fields,error_code} /
  direct_rag_answer.{kind,reason,answer_source,cited_unit_ids,fact_count} /
  commit_observed.kind / completeness；
- 零真实调用：不联网、不建库、不跑产品。
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import sys

REPO = pathlib.Path(r"D:\GPT项目\市场部AI知识库")
WORK = pathlib.Path(r"D:\mktkb-p2-h2v3-20261115")
for entry in (str(REPO / "backend" / "src"), str(REPO / "tools")):
    if entry not in sys.path:
        sys.path.insert(0, entry)

spec = importlib.util.spec_from_file_location(
    "p2_h2_v3_controlled_execute_fix2b", REPO / "tools" / "p2_h2_v3_controlled_execute.py"
)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)

from mktkb.evaluation.p2_evidence_io import read_encrypted_evidence  # noqa: E402

PLAN_KEYS = (
    "path",
    "mode",
    "filters",
    "as_of",
    "include_future",
    "enumerate",
    "clarification",
    "state_keys",
    "state_as_of",
    "state_pending_slot",
    "state_last_kind",
)
ANSWER_KEYS = ("kind", "reason", "candidates", "conflicts", "missing_fields", "error_code", "source_ids")
DIRECT_KEYS = ("kind", "reason", "answer_source", "cited_unit_ids", "fact_count", "state_keys")
STATE_KEYS = (
    "store",
    "stores",
    "item",
    "items",
    "product",
    "channel",
    "price_type",
    "identifier",
    "doc_id",
    "doc_title",
    "field_role",
    "field_roles",
    "pending_slot",
    "as_of",
    "enumerate",
    "page",
    "page_size",
    "turn",
    "last_kind",
    "candidates",
)

TARGETS = {"H2V3-C02", "H2V3-C05", "H2V3-C19", "H2V3-C20", "H2V3-C22", "H2V3-C21", "H2V3-C30"}
BINDINGS = (
    "run0-base_b0.binding.json",
    "run1-base_b0_plus_v01.binding.json",
    "run2-pre_v05_without_v07.binding.json",
    "run3-post_v05_without_v01.binding.json",
)


def _payloads(events: list[dict], kind: str) -> list[dict]:
    return [dict(e.get("payload") or {}) for e in events if str(e.get("kind")) == kind]


def main() -> int:
    key_paths = [p for p in (WORK / "runs3" / "ev.key", WORK / "runs" / "r0" / "ev.key") if p.exists()]
    keys = [(f"{p.parent.name}/{p.name}", p.read_bytes().strip()) for p in key_paths]

    rows: list[dict] = []
    for run_index in range(4):
        document = json.loads((WORK / "regen-1160c" / "bindings" / BINDINGS[run_index]).read_text(encoding="utf-8"))
        inputs = {name: {"path": record["path"]} for name, record in document["inputs"].items()}
        bundle = module.load_v3_bundle(inputs)
        run_entry = document["runs"][0]
        scenario = str(run_entry["scenario_id"])
        subset = bundle.contract.subset(scenario)
        case_plan = json.loads(
            (WORK / "runs" / f"r{run_index}c" / "out" / "controlled" / "case-plan.json").read_text(encoding="utf-8")
        )
        evidence_dir = WORK / "runs" / f"r{run_index}c" / "evidence" / str(run_entry["run_id"])
        by_case = {str(case.case_id): case for case in subset.cases}
        for row in case_plan["cases"]:
            case_id = str(row["case_id"])
            if case_id not in TARGETS:
                continue
            case = by_case[case_id]
            last = row["turns"][-1]
            envelope = None
            used_key = None
            last_error = None
            for label, key in keys:
                try:
                    envelope = read_encrypted_evidence(
                        evidence_dir / str(last["evidence_file"]),
                        key=key,
                        expected_bindings=dict(case_plan["bindings"]),
                    )
                    used_key = label
                    break
                except Exception as exc:  # noqa: BLE001
                    last_error = type(exc).__name__ + ":" + str(getattr(exc, "code", ""))
            if envelope is None:
                rows.append({"run": run_index, "case_id": case_id, "decrypt_error": last_error})
                continue
            events = list((envelope.get("capture") or {}).get("events") or [])
            projection = envelope.get("db_projection") or {}
            states = projection.get("query_states") or []
            state_json = ((states[-1] or {}).get("state_json") or {}) if states else {}
            plans = [{k: p.get(k) for k in PLAN_KEYS if k in p} for p in _payloads(events, "plan_observed")]
            rows.append(
                {
                    "run": run_index,
                    "case_id": case_id,
                    "stratum": str(case.stratum),
                    "expected_kind": str(case.expected_kind),
                    "should_refuse": bool(case.should_refuse),
                    "turns_in_case": len(row["turns"]),
                    "used_key": used_key,
                    "plans": plans,
                    "answer_result": [{k: p.get(k) for k in ANSWER_KEYS if k in p} for p in _payloads(events, "answer_result")],
                    "direct_rag_answer": [
                        {k: p.get(k) for k in DIRECT_KEYS if k in p} for p in _payloads(events, "direct_rag_answer")
                    ],
                    "commit_kinds": [p.get("kind") for p in _payloads(events, "commit_observed")],
                    "retrieval": [
                        {k: p.get(k) for k in ("scope", "empty", "candidate", "truncated")}
                        for p in _payloads(events, "retrieval_observed")
                    ],
                    "db_state": {k: state_json.get(k) for k in STATE_KEYS if k in state_json},
                    "completeness": str((envelope.get("completeness") or {}).get("status")),
                    "missing_event_kinds": list((envelope.get("completeness") or {}).get("missing_event_kinds") or []),
                }
            )
    out = REPO / "docs/reports/OBS-EVAL/P2/H2V3/fix-2/evidence/observed-cases.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"written": str(out), "rows": len(rows)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

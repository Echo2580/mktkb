"""C2/C3 冒烟：自建链路可跑通 + 记录结构摘要（合成材料，安全聚合）。"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ci_support as sup  # noqa: E402


def _summary(payload: dict) -> dict:
    snap = payload.get("runtime_snapshot") or {}
    product = snap.get("product_response") or {}
    usage = snap.get("retrieval_use") or {}
    trace = snap.get("trace") or {}
    completeness = payload.get("completeness") or {}
    proj = payload.get("db_projection") or {}
    units = {str(row.get("unit_id")): row for row in proj.get("units") or ()}
    facts = []
    layers = {}
    for event in (payload.get("capture") or {}).get("events") or ():
        kind = event.get("kind")
        body = event.get("payload") or {}
        if kind == "direct_rag_answer":
            for fact in body.get("facts") or ():
                if isinstance(fact, dict):
                    facts.append(
                        {
                            "entity_key": fact.get("entity_key"),
                            "source_unit_id": fact.get("source_unit_id"),
                            "backing_key": (units.get(str(fact.get("source_unit_id"))) or {}).get("entity_key"),
                        }
                    )
        if kind in ("model_input", "answer_result", "commit_observed", "retrieval_observed"):
            layers.setdefault(kind, []).append(sorted(body.keys()))
    return {
        "schema_version": payload.get("schema_version"),
        "turn": payload.get("turn"),
        "completeness": {
            "status": completeness.get("status"),
            "errors": completeness.get("errors"),
            "scoring_readiness": completeness.get("scoring_readiness"),
        },
        "product": {
            "availability": product.get("availability"),
            "reason": product.get("reason"),
            "kind": product.get("kind"),
            "has_request": bool(product.get("request_id")),
            "has_message": bool(product.get("message_id")),
            "revision": product.get("revision"),
            "sources": len(product.get("sources") or ()),
            "pagination": product.get("pagination"),
            "versions": sorted({row.get("version_number") for row in product.get("sources") or ()}),
        },
        "trace": {
            "availability": trace.get("availability"),
            "spans": len(trace.get("spans") or ()),
            "mode": trace.get("model_failure_reason"),
        },
        "usage": {
            "availability": usage.get("availability"),
            "candidate_observation": usage.get("candidate_observation"),
            "counts": {
                key: len(usage.get(key) or ())
                for key in (
                    "candidates",
                    "model_evidence",
                    "direct_rag_facts",
                    "direct_rag_citations",
                    "final_citations",
                    "inheritance",
                )
            },
        },
        "facts": facts,
        "units": {key: {"type": row.get("entity_type"), "key": row.get("entity_key")} for key, row in units.items()},
        "event_kinds": sorted({str(e.get("kind")) for e in (payload.get("capture") or {}).get("events") or ()}),
        "layers": {k: v[0] for k, v in layers.items()},
        "projection_counts": {
            "units": len(proj.get("units") or ()),
            "messages": len(proj.get("messages") or ()),
            "message_sources": len(proj.get("message_sources") or ()),
            "unresolved": len(proj.get("unresolved_unit_ids") or ()),
        },
    }


async def main() -> int:
    sup.install_network_guard()
    tmp = sup.fresh_temp("t207-ci-smoke-")
    print("tmp_root=", tmp)
    try:
        capture = await sup.capture_run(tmp, "ci-smoke-run")
        inputs = sup.write_inputs(tmp, capture=capture, cases=sup.case_specs())
        print("blocked=", capture["blocked"], "last_error=", capture["last_error"])
        print("manifest_summary=", json.dumps(capture["manifest"].get("summary"), ensure_ascii=False))
        key = bytes(capture["writer"].key)
        for index, name in enumerate(inputs["files"]):
            raw = sup.decrypt_raw(inputs["evidence_dir"] / name, key)
            print(f"--- turn {index} {name} ---")
            print(json.dumps(_summary(raw), ensure_ascii=False, default=str))
        # 关闭产品实例后删除合成业务库/trace
        sup.remove_tree(tmp / "product")
        print("product_dir_exists=", (tmp / "product").exists())
        card, results = sup.recompute_in_process(inputs)
        print("cross_entity=", [r.axis_state("cross_entity") for r in results])
        print("cross_user=", [r.axis_state("cross_user") for r in results])
        print("states=", [[r.axis_state(axis) for axis in ("safety", "cross_user", "cross_entity", "stale_source")] for r in results])
        print("reasons=", {r.case_id: {axis: r.axes[axis].reason for axis in ("cross_user", "cross_entity")} for r in results})
        print("missing=", [list(r.missing_codes) for r in results])
        print("evidence_complete=", [r.evidence_complete for r in results])
        print("card_totals=", {k: card[k] for k in ("total", "executed", "passed", "failed", "errors", "hard_failures", "release_ready", "threshold_met")})
        print("axes=", json.dumps(card["hard_evidence"]["axes"], ensure_ascii=False))
        print("blocks=", json.dumps(card["blocks"], ensure_ascii=False))
        print("net_external=", sup.external_attempts())
        print("net_loopback_count=", len(sup.NET_LOOPBACK))
        return 0
    finally:
        sup.remove_tree(tmp)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

"""T206-PRE-R1 可复跑探针：gate 行的 retrieved 是否接真实检索候选 + citation_required 正/反例。

全 Mock / 离线 / 零真实调用；stdout 输出 JSON（不写仓库任何文件）：
  .venv\\Scripts\\python.exe -B -X utf8 docs/reports/OBS-EVAL/P2/T206-PRE/evidence/05-r1-retrieval-probe.py

复用 T203 测试模块的计划/数据集/授权构造（不复制实现）。
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[6]
sys.path.insert(0, str(REPO / "backend" / "src"))
sys.path.insert(0, str(REPO / "backend" / "tests" / "evaluation"))

import test_p2_runner as H  # noqa: E402  - 复用测试夹具构造

from mktkb.evaluation.p2_runner import run_p2  # noqa: E402
from mktkb.evaluation.p2_scoring import (  # noqa: E402
    build_gate_rows,
    build_gate_run,
    evaluate_p2_hard_gates,
    load_p2_gate_config,
    score_public_case,
)
from mktkb.evaluation.product_adapter import MockChatBackend, ProductEvalAdapter  # noqa: E402

DOCUMENT_CODES = {H.D01.name: "D01", H.D04.name: "D04"}
FOREIGN_UNIT = "99999999-9999-4999-8999-999999999999"


def tampered(rows, *, mode: str):
    out = []
    for row in rows:
        copy = dict(row)
        outcome = copy.get("outcome")
        if isinstance(outcome, dict) and outcome.get("kind") == "answer":
            outcome = dict(outcome)
            if mode == "drop":
                outcome["retrieved"] = []
            else:
                outcome["retrieved"] = [
                    {
                        "doc_code": "D01",
                        "unit_ids": [FOREIGN_UNIT],
                        "unit_key": "sheet:无关:row:99",
                        "locator": {"sheet": "无关", "row": 99},
                        "chunk_id": None,
                        "hard_filter_violation": None,
                    }
                ]
            copy["outcome"] = outcome
        out.append(copy)
    return tuple(out)


async def main() -> dict:
    config = load_p2_gate_config()
    cases = (
        H.make_case("P01", H.RAG_QUESTION),
        H.make_case("P03", H.LEGACY_QUESTION),
        H.make_case("P04", H.UNKNOWN_QUESTION, stratum="negative"),
    )
    plan = H.make_plan(cases)
    adapter = ProductEvalAdapter(
        Path(tempfile.mkdtemp(prefix="p2-r1-probe-")),
        chat=MockChatBackend(),
        dataset=H.make_dataset(cases),
        ingest_plan=H.make_ingest_plan(),
    )
    try:
        result = await run_p2(
            plan,
            adapter=adapter,
            authorization=H.dry_run_authorization(plan),
            now=H.NOW,
            gate_config=config,
        )
        run_dir = adapter.paths.run_dir
        manifest = H.read_json(run_dir / "run_manifest.json")
        summary = H.read_json(run_dir / "summary.json")
        rows = H.read_jsonl(run_dir / "cases.jsonl")
        turns = []
        for row in rows:
            for turn in row["turns"]:
                product = turn["product"]
                turns.append(
                    {
                        "case_id": row["case_id"],
                        "path": product.get("trace_path"),
                        "kind": product.get("kind"),
                        "citations": len(product.get("sources") or ()),
                        "retrieved": len(product.get("retrieved") or ()),
                        "cited_subset_of_retrieved": {
                            str(item["source_id"]) for item in product.get("sources") or ()
                        }
                        <= {unit for item in product.get("retrieved") or () for unit in item["unit_ids"]},
                    }
                )
        scored = [
            score_public_case(
                case,
                row,
                document_codes=DOCUMENT_CODES,
                allowed_doc_codes=set(DOCUMENT_CODES.values()),
            )
            for case, row in zip(cases, rows)
        ]
        gate_rows = build_gate_rows(cases, scored)
        gate_run = build_gate_run(
            run_dir=run_dir, manifest=manifest, cases=cases, rows=gate_rows, summary=summary
        )
        positive = evaluate_p2_hard_gates(gate_run, config=config, require_trace=True)
        negatives = {}
        for mode in ("drop", "foreign"):
            tampered_run = build_gate_run(
                run_dir=run_dir,
                manifest=manifest,
                cases=cases,
                rows=tampered(gate_rows, mode=mode),
                summary=summary,
            )
            hard = evaluate_p2_hard_gates(tampered_run, config=config, require_trace=True)
            negatives[mode] = {
                "citation_required": hard.gate_status["citation_required"],
                "hard_failure_listed": "citation_required" in hard.hard_failures,
                "check_ids": sorted({item.check_id for item in hard.failures if item.gate_id == "citation_required"}),
            }
        return {
            "run_status": result.status,
            "run_id": manifest["run_id"],
            "config_hash": manifest["config_hash"],
            "turns": turns,
            "gate_status_positive": dict(positive.gate_status),
            "citation_required_positive": positive.gate_status["citation_required"],
            "negative_cases": negatives,
            "real_requests": summary["requests"]["real_requests"],
            "billed_cny": summary["requests"]["billed_cny"],
        }
    finally:
        await adapter.close()


if __name__ == "__main__":
    print(json.dumps(asyncio.run(main()), ensure_ascii=False, indent=2))

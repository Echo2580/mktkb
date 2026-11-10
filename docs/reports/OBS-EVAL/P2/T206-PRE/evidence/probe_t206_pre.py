"""T206-PRE 可复跑探针：绑定/证据/失败产物/run_id/config_hash 的**实测**摘要（全 Mock，出站 0）。

只读运行：不写仓库任何文件（stdout 输出，归档用 `python -X utf8 probe > 02-binding-digest.json`）；
不读 .env / H1 / H2；不联网；复用 T203 测试模块里的计划/数据集/授权构造（不复制实现）。

用法（仓库根）：
  .venv\\Scripts\\python.exe -B -X utf8 docs/reports/OBS-EVAL/P2/T206-PRE/evidence/probe_t206_pre.py
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

import test_p2_runner as H  # noqa: E402  - 复用测试夹具构造（不复制实现）

from mktkb.evaluation.p2_runner import P2RunError, run_p2  # noqa: E402
from mktkb.evaluation.p2_scoring import (  # noqa: E402
    binding_config_hash,
    build_gate_rows,
    build_gate_run,
    citation_evidence_status,
    evaluate_p2_hard_gates,
    load_p2_gate_config,
    score_public_case,
)
from mktkb.evaluation.product_adapter import (  # noqa: E402
    MockChatBackend,
    ProductEvalAdapter,
)

DOCUMENT_CODES = {H.D01.name: "D01", H.D04.name: "D04"}


def make_adapter(root: Path, cases, *, adapter_cls=ProductEvalAdapter):
    return adapter_cls(
        root,
        chat=MockChatBackend(),
        dataset=H.make_dataset(cases),
        ingest_plan=H.make_ingest_plan(),
    )


async def bound_run(root: Path, config) -> dict:
    cases = (H.make_case("P01", H.RAG_QUESTION), H.make_case("P03", H.LEGACY_QUESTION))
    plan = H.make_plan(cases)
    authorization = H.dry_run_authorization(plan)
    adapter = make_adapter(root, cases)
    try:
        result = await run_p2(
            plan, adapter=adapter, authorization=authorization, now=H.NOW, gate_config=config
        )
        run_dir = adapter.paths.run_dir
        manifest = H.read_json(run_dir / "run_manifest.json")
        summary = H.read_json(run_dir / "summary.json")
        case_rows = H.read_jsonl(run_dir / "cases.jsonl")
        traces = []
        for case_row in case_rows:
            for turn in case_row["turns"]:
                trace, spans = adapter.app.state.trace_repo.get(turn["trace_id"])
                traces.append(
                    {
                        "case_id": case_row["case_id"],
                        "turn": turn["turn"],
                        "run_id": trace.run_id,
                        "dataset_version": trace.dataset_version,
                        "manifest_sha256": trace.manifest_sha256,
                        "pipeline_version": trace.pipeline_version,
                        "index_revision": trace.index_revision,
                        "config_hash": trace.config_hash,
                        "mode": trace.mode,
                        "spans": sorted(span.name for span in spans),
                    }
                )
        scored = [
            score_public_case(
                case,
                case_row,
                document_codes=DOCUMENT_CODES,
                allowed_doc_codes=set(DOCUMENT_CODES.values()),
            )
            for case, case_row in zip(cases, case_rows)
        ]
        gate_run = build_gate_run(
            run_dir=run_dir,
            manifest=manifest,
            cases=cases,
            rows=build_gate_rows(cases, scored),
            summary=summary,
        )
        hard = evaluate_p2_hard_gates(gate_run, config=config, require_trace=True)
        return {
            "status": result.status,
            "run_id": manifest["run_id"],
            "config_hash": manifest["config_hash"],
            "binding": manifest["binding"],
            "identity_fields": {
                name: manifest[name]
                for name in (
                    "suite",
                    "dataset_version",
                    "dataset_sha256",
                    "corpus_manifest_sha256",
                    "business_date",
                    "index_revision",
                    "pipeline_version",
                    "gate_version",
                    "gate_config_hash",
                    "label_version",
                    "case_count",
                )
            },
            "trace_identity": traces,
            "trace_integrity": hard.gate_status["trace_integrity"],
            "trace_hard_failures": [item for item in hard.hard_failures if item == "trace_integrity"],
            "citation_evidence": citation_evidence_status(case_rows),
            "summary_citation_evidence": summary["citation_evidence"]["complete"],
            "network": summary["network"],
            "real_requests": summary["requests"]["real_requests"],
            "billed_cny": summary["requests"]["billed_cny"],
            "adapter_outbound": adapter.provider_calls()["outbound_network"],
        }
    finally:
        await adapter.close()


async def failure_run(root: Path) -> dict:
    cases = (H.make_case("P01", H.LEGACY_QUESTION),)
    plan = H.make_plan(cases)
    authorization = H.dry_run_authorization(plan)
    adapter = make_adapter(root, cases, adapter_cls=H._TopLevelOnlyAdapter)
    try:
        try:
            await run_p2(plan, adapter=adapter, authorization=authorization, now=H.NOW)
            raised = None
        except P2RunError as exc:
            raised = {"code": exc.code, "detail": exc.detail}
        run_dir = adapter.paths.run_dir
        summary = H.read_json(run_dir / "summary.json")
        gate_payload = H.read_json(run_dir / "gate.json")
        result = H.read_json(run_dir / "run_result.json")
        return {
            "raised": raised,
            "files": sorted(path.name for path in run_dir.iterdir()),
            "status": result["status"],
            "stop_code": result["stop_code"],
            "failure": summary["failure"],
            "network": summary["network"],
            "providers": summary["providers"],
            "artifact_validation": gate_payload["artifact_validation"],
            "real_sends_allowed": gate_payload["real_sends_allowed"],
        }
    finally:
        await adapter.close()


async def run_id_refusal(root: Path) -> dict:
    cases = (H.make_case("P01", H.LEGACY_QUESTION),)
    plan = H.make_plan(cases)
    authorization = H.dry_run_authorization(plan)
    adapter = make_adapter(root, cases)
    try:
        try:
            await run_p2(plan, adapter=adapter, authorization=authorization, now=H.NOW, run_id="")
            return {"raised": None}
        except P2RunError as exc:
            return {
                "raised": {"code": exc.code, "detail": exc.detail},
                "run_dir_created": adapter.paths.run_dir.exists(),
                "adapter_started": bool(getattr(adapter, "_started", False)),
            }
    finally:
        await adapter.close()


async def main() -> dict:
    config = load_p2_gate_config()
    with tempfile.TemporaryDirectory(prefix="p2-t206-pre-") as tmp:
        root = Path(tmp)
        first = await bound_run(root / "run-a", config)
        second = await bound_run(root / "run-b", config)
        failure = await failure_run(root / "fail")
        refusal = await run_id_refusal(root / "refuse")

    components = {
        "dataset_version": first["binding"]["dataset_version"],
        "manifest_sha256": first["binding"]["manifest_sha256"],
        "label_version": first["binding"]["label_version"],
        "pipeline_version": first["binding"]["pipeline_version"],
        "index_revision": first["binding"]["index_revision"],
        "provider": first["binding"]["provider"],
        "gate_version": first["binding"]["gate_version"],
        "gate_config_hash": first["binding"]["gate_config_hash"],
    }
    digest = binding_config_hash(**components)
    changed = binding_config_hash(**{**components, "index_revision": int(components["index_revision"]) + 1})

    return {
        "schema": "p2-t206-pre-binding/v0.1",
        "gate": {
            "gate_version": config.gate_version,
            "config_hash": config.config_hash,
            "status": config.status,
        },
        "run_a": first,
        "run_b": {
            "run_id": second["run_id"],
            "config_hash": second["config_hash"],
            "same_config_hash_as_run_a": second["config_hash"] == first["config_hash"],
            "trace_integrity": second["trace_integrity"],
        },
        "config_hash": {
            "recomputed_matches_run": digest == first["config_hash"],
            "changed_after_index_revision_bump": changed != digest,
            "changed_digest_prefix": changed[:12],
        },
        "failure_artifacts": failure,
        "run_id_refusal": refusal,
        "zero_real_calls": {
            "run_a_real_requests": first["real_requests"],
            "run_a_billed_cny": first["billed_cny"],
            "run_a_adapter_outbound": first["adapter_outbound"],
            "run_a_network_outbound": first["network"]["outbound_attempts"],
            "run_b_real_requests": second["real_requests"],
        },
    }


if __name__ == "__main__":
    print(json.dumps(asyncio.run(main()), ensure_ascii=False, indent=2))

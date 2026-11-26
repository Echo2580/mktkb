"""FU-1 改前/改后复现探针（合成夹具：发布换版导致 产品计数 != RAG 索引计数）。

用法（在目标检出内运行，pytest 会把该检出 backend/src 放进 sys.path）：

    cd <checkout>\\backend
    <venv-python> -m pytest tests/evaluation/test_zzprobe_fu1.py -q -s

交付内已删除其临时副本；本文件是原始探针的内容留档。2026-11-21 实测：
* 冻结候选 93486b6：MANIFEST_INDEX_REVISION=3、RAG trace=4、trace_integrity=fail（version_binding）
* 修复树：MANIFEST_INDEX_REVISION=4、两条 trace 均 4、trace_integrity=pass
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from test_p2_runner import (  # noqa: E402
    D01,
    D04,
    DOCUMENT_CODES,
    FIXTURES,
    LEGACY_QUESTION,
    NOW,
    RAG_QUESTION,
    asyncio_test,
    build_gate_rows,
    build_gate_run,
    dry_run_authorization,
    evaluate_p2_hard_gates,
    load_p2_gate_config,
    make_case,
    make_dataset,
    make_plan,
    read_json,
    read_jsonl,
    score_p2_public_case,
)

from mktkb.evaluation.p2_runner import run_p2  # noqa: E402
from mktkb.evaluation.product_adapter import (  # noqa: E402
    IngestSource,
    MockChatBackend,
    P2IngestPlan,
    ProductEvalAdapter,
)


@asyncio_test
async def test_probe_fu1(tmp_path: Path) -> None:
    cases = (make_case("P01", RAG_QUESTION), make_case("P03", LEGACY_QUESTION))
    plan = make_plan(cases)
    dataset = make_dataset(cases)
    config = load_p2_gate_config()
    ingest = P2IngestPlan(
        sources=(
            IngestSource(path=FIXTURES / "variants" / "V03_物品位置表_历史V1.xlsx", name=D01.name),
            IngestSource(path=D01, document_ref=D01.name),
            IngestSource(path=D04),
        ),
        label="probe-publish-version-change",
    )
    adapter = ProductEvalAdapter(
        tmp_path / "probe", chat=MockChatBackend(), dataset=dataset, ingest_plan=ingest
    )
    try:
        result = await run_p2(
            plan,
            adapter=adapter,
            authorization=dry_run_authorization(plan),
            now=NOW,
            gate_config=config,
        )
        print("STATUS", result.status, result.stop_code)
        print("PRODUCT_REVISION", adapter.product_revision())
        print("INDEX_STATUS", adapter.index_status())
        run_dir = adapter.paths.run_dir
        manifest = read_json(run_dir / "run_manifest.json")
        summary = read_json(run_dir / "summary.json")
        print("MANIFEST_INDEX_REVISION", manifest["index_revision"])
        print("BINDING", manifest["binding"])
        case_rows = read_jsonl(run_dir / "cases.jsonl")
        for case_row in case_rows:
            for turn in case_row["turns"]:
                trace, _spans = adapter.app.state.trace_repo.get(turn["trace_id"])
                print("TRACE", turn["trace_id"], trace.index_revision, trace.path, trace.config_hash)
        scored = [
            score_p2_public_case(
                case,
                {row["case_id"]: row for row in case_rows}[case.case_id],
                document_codes=DOCUMENT_CODES,
                allowed_doc_codes=set(DOCUMENT_CODES.values()),
            )
            for case in cases
        ]
        rows = build_gate_rows(cases, scored)
        gate_run = build_gate_run(
            run_dir=run_dir, manifest=manifest, cases=cases, rows=rows, summary=summary
        )
        hard = evaluate_p2_hard_gates(gate_run, config=config, require_trace=True)
        print("GATE_STATUS", hard.gate_status)
        print("HARD_FAILURES", hard.hard_failures)
        for item in hard.failures:
            print("FAIL", item.gate_id, item.check_id, item.evidence)
    finally:
        await adapter.close()

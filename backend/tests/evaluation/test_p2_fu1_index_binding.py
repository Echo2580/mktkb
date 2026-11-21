"""FU-1：通用 P2 入口绑定**实际使用的 RAG 索引版本**（正/反例）。

复现（修复前，2026-11-21 实测，产物见 ``docs/reports/OBS-EVAL/P2/FOLLOW-UP/FU1/``）：

* 夹具：先用 ``V03_物品位置表_历史V1.xlsx`` 灌一版、再用 ``D01_物品位置表.xlsx``
  以 ``document_ref`` 发同一份资料的**新版本**（真实"发布导致版本变化"场景）。
* 产品资料发布版本 = **3**，RAG 索引版本（``rag_meta.revision``）= **4**；
* 修复前 ``binding_components()`` 把 ``index_revision`` 写成产品计数 3，而
  RAG 轮次的 trace 写的是 4 → 硬门禁 ``trace_integrity`` 机械失败
  ``version_binding``（mismatched=index_revision），每一条走过 RAG 的轮次都中招。

修复后（本文件守护）：绑定值取 ``QaIndexStatus.index_revision``（trace 同一口径），
manifest / trace / 门禁三者对齐；真实错绑（把 manifest 改回产品计数或任意值）仍然
fail；版本不可得时按缺证处理（绑定不完整、不写半套身份、进不了硬门禁）；测量窗口内
漂移则直接停（``index_changed``），不把混合版本的 run 记成成功。
"""

from __future__ import annotations

import functools
import sys
from pathlib import Path
from typing import Any

import pytest

_TESTS_DIR = Path(__file__).resolve().parents[1]
if str(_TESTS_DIR) not in sys.path:  # 复用既有验收级网络闸门，不复制实现
    sys.path.insert(0, str(_TESTS_DIR))

from acceptance.support.netguard import t09_network_guard  # noqa: E402,F401  (pytest fixture)

from mktkb.evaluation.p2_runner import run_p2  # noqa: E402
from mktkb.evaluation.p2_scoring import (  # noqa: E402
    P2ScoringError,
    build_gate_rows,
    build_gate_run,
    evaluate_p2_hard_gates,
    load_p2_gate_config,
    score_public_case,
)
from mktkb.evaluation.product_adapter import (  # noqa: E402
    IngestSource,
    MockChatBackend,
    P2IngestPlan,
    ProductEvalAdapter,
)

pytestmark = pytest.mark.usefixtures("t09_network_guard")

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "fixtures" / "acceptance"
D01 = FIXTURES / "normal" / "D01_物品位置表.xlsx"
D04 = FIXTURES / "normal" / "D04_活动策划流程.docx"

NOW_TEXT = "2026-11-21T00:00:00+00:00"
RAG_QUESTION = "把城东店和城西店的宣传海报记录都列出来"
LEGACY_QUESTION = "活动策划需要哪些步骤？"
DOCUMENT_CODES = {
    D01.name: "D01",
    D04.name: "D04",
}


def asyncio_test(func):
    """仓库没有 pytest-asyncio：用同一事件循环跑一个 async 用例（保留 fixture 签名）。"""

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any):
        import asyncio

        return asyncio.run(func(*args, **kwargs))

    return wrapper


def _make_case(case_id: str, question: str):
    from mktkb.evaluation.dataset import CaseSpec

    return CaseSpec(
        case_id=case_id,
        suite="p2-holdout",
        split="holdout",
        stratum="paraphrase",
        business_date="2026-11-10",
        question=question,
        turns=(),
        label_version="synthetic-v1",
    )


def _make_plan(cases):
    from datetime import datetime, timezone

    from mktkb.evaluation.p2_contracts import (
        CHAT_HOST,
        CHAT_MODEL,
        CHAT_PRICING_SOURCE,
        CHAT_PROVIDER,
        CHAT_REGION,
        P2PriceProfile,
        P2RequestItem,
        P2RunPlan,
    )

    profile = P2PriceProfile(
        kind="chat",
        model=CHAT_MODEL,
        provider=CHAT_PROVIDER,
        host=CHAT_HOST,
        region=CHAT_REGION,
        pricing_source=CHAT_PRICING_SOURCE,
        input_price_per_million_cny=2.0,
        output_price_per_million_cny=8.0,
        prompt_tokens_cap=6144,
        completion_tokens_cap=800,
    )
    items = tuple(
        P2RequestItem(
            item_id=f"{case.case_id}:turn1:answer",
            operation="answer",
            cost_center="answer_retrieval",
            case_id=case.case_id,
            turn=1,
            page=0,
            requests=1,
            price_profile=profile,
            expected_success_cny=0.001,
        )
        for case in cases
    )
    return P2RunPlan(
        schema_version="p2-run-plan/v0.1",
        plan_id="p2-fu1-index-binding",
        plan_version="v1",
        mode="end_to_end",
        stage="P2-LIVE",
        created_utc=NOW_TEXT,
        project_total_limit_cny=40.0,
        stage_limit_cny=20.0,
        max_requests=1000,
        cost_centers_cny={
            "answer_retrieval": 12.0,
            "ocr": 3.0,
            "judge": 3.0,
            "independent": 2.0,
        },
        items=items,
    ), datetime(2026, 11, 21, tzinfo=timezone.utc)


def _make_snapshot(plan):
    from mktkb.evaluation.p2_contracts import (
        COST_CENTERS,
        P2_LEDGER_SNAPSHOT_SCHEMA_VERSION,
        P2LedgerSnapshot,
    )

    return P2LedgerSnapshot(
        schema_version=P2_LEDGER_SNAPSHOT_SCHEMA_VERSION,
        ledger_path="in-memory:fu1",
        ledger_sha256="0" * 64,
        historical_prefix_sha256="1" * 64,
        budget_sha256="2" * 64,
        total_limit_cny=float(plan.project_total_limit_cny),
        historical_accounted_cny=15.0709445,
        accounted_cny=15.0709445,
        reservation_count=505,
        result_count=505,
        stage_allocations_cny={"S2-DEV": 3.0, "P1-RETRIEVAL": 2.0, "P2-LIVE": 20.0},
        p2_stage_accounted_cny=0.0,
        p2_center_accounted_cny={center: 0.0 for center in COST_CENTERS},
        source="in-memory",
    )


def _dry_run_authorization(plan, now):
    from mktkb.evaluation.p2_authorization import preflight_p2
    from mktkb.evaluation.p2_runner import build_dry_run_authorization

    preflight = preflight_p2(plan, _make_snapshot(plan))
    assert preflight.ok, preflight.reasons
    assert preflight.production_ready is False
    return build_dry_run_authorization(plan, preflight, now=now, nonce="0f" * 16)


def _make_dataset(cases):
    from mktkb.evaluation.product_adapter import P2RunDataset

    strata: dict[str, int] = {}
    for case in cases:
        strata[case.stratum] = strata.get(case.stratum, 0) + 1
    return P2RunDataset(
        visibility="public",
        cases=cases,
        identity={
            "dataset_version": "p2-synthetic-fu1",
            "label_version": "synthetic-v1",
            "suite": "p2-holdout",
            "manifest_sha256": "b" * 64,
            "case_count": len(cases),
            "strata": strata,
        },
    )


def _version_change_ingest() -> P2IngestPlan:
    """真实"发布导致版本变化"：先灌历史版，再以 document_ref 发同一资料的新版本。"""
    return P2IngestPlan(
        sources=(
            IngestSource(
                path=FIXTURES / "variants" / "V03_物品位置表_历史V1.xlsx", name=D01.name
            ),
            IngestSource(path=D01, document_ref=D01.name),
            IngestSource(path=D04),
        ),
        label="fu1-publish-version-change",
    )


def _read_json(path: Path) -> dict[str, Any]:
    import json

    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    import json

    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _trace(adapter: ProductEvalAdapter, trace_id: str):
    found = adapter.app.state.trace_repo.get(trace_id)
    assert found is not None, trace_id
    return found[0]


def _gate_rows(cases, case_rows):
    by_id = {row["case_id"]: row for row in case_rows}
    scored = [
        score_public_case(
            case,
            by_id[case.case_id],
            document_codes=DOCUMENT_CODES,
            allowed_doc_codes=set(DOCUMENT_CODES.values()),
        )
        for case in cases
    ]
    return build_gate_rows(cases, scored)


# --------------------------------------------------------------------------- #
# 1. 正例：通用入口的 manifest / trace / 门禁三者都用实际 RAG 索引版本
# --------------------------------------------------------------------------- #


@asyncio_test
async def test_generic_entry_binds_actual_rag_index_revision(tmp_path: Path) -> None:
    cases = (_make_case("P01", RAG_QUESTION), _make_case("P03", LEGACY_QUESTION))
    plan, now = _make_plan(cases)
    config = load_p2_gate_config()
    adapter = ProductEvalAdapter(
        tmp_path / "bound",
        chat=MockChatBackend(),
        dataset=_make_dataset(cases),
        ingest_plan=_version_change_ingest(),
    )
    try:
        result = await run_p2(
            plan,
            adapter=adapter,
            authorization=_dry_run_authorization(plan, now),
            now=now,
            gate_config=config,
        )
        assert result.status == "succeeded", result.as_dict()
        # 夹具本身必须让两套计数器**不同**，否则这条用例没有证伪力。
        product_revision = adapter.product_revision()
        index_revision = adapter.index_status()["index_revision"]
        assert (product_revision, index_revision) == (3, 4), (
            product_revision,
            index_revision,
        )

        run_dir = adapter.paths.run_dir
        manifest = _read_json(run_dir / "run_manifest.json")
        summary = _read_json(run_dir / "summary.json")
        binding = manifest["binding"]
        # 绑定值 = 实际 RAG 索引版本（不是产品资料发布版本）。
        assert manifest["index_revision"] == binding["index_revision"] == index_revision
        assert manifest["index_revision"] != product_revision
        assert binding["complete"] is True and binding["missing"] == []
        assert binding["trace_identity_bound"] is True
        # 摘要仍能由组件确定性重算（口径没被放宽）。
        from mktkb.evaluation.p2_scoring import binding_config_hash

        assert binding["config_hash"] == binding_config_hash(
            dataset_version=binding["dataset_version"],
            manifest_sha256=binding["manifest_sha256"],
            label_version=binding["label_version"],
            pipeline_version=binding["pipeline_version"],
            index_revision=binding["index_revision"],
            provider=binding["provider"],
            gate_version=binding["gate_version"],
            gate_config_hash=binding["gate_config_hash"],
        )
        assert summary["binding"] == binding == _read_json(run_dir / "gate.json")["binding"]

        # trace：RAG 轮和 legacy 轮都等于同一个索引版本（同一测量）。
        case_rows = _read_jsonl(run_dir / "cases.jsonl")
        observed = []
        for case_row in case_rows:
            for turn in case_row["turns"]:
                trace = _trace(adapter, turn["trace_id"])
                observed.append((trace.path, trace.index_revision))
                assert str(trace.index_revision) == str(index_revision)
                assert str(trace.config_hash) == binding["config_hash"]
        assert {path for path, _ in observed} == {"rag", "legacy"}

        # 门禁：同一份 manifest 进硬门禁，trace_integrity 真 PASS（不是靠改 gate）。
        rows = _gate_rows(cases, case_rows)
        hard = evaluate_p2_hard_gates(
            build_gate_run(
                run_dir=run_dir, manifest=manifest, cases=cases, rows=rows, summary=summary
            ),
            config=config,
            require_trace=True,
        )
        assert hard.gate_status["trace_integrity"] == "pass", hard.to_dict()
        assert "trace_integrity" not in hard.hard_failures
        assert not [f for f in hard.failures if f.check_id == "version_binding"]
    finally:
        await adapter.close()


@asyncio_test
async def test_generic_entry_binding_hash_is_deterministic(tmp_path: Path) -> None:
    """同输入两次运行 → 同一 index_revision / config_hash（可确定比对，不是随机值）。"""

    async def one_run(root: Path) -> tuple[int, str]:
        cases = (_make_case("P01", RAG_QUESTION),)
        plan, now = _make_plan(cases)
        adapter = ProductEvalAdapter(
            root / "run",
            chat=MockChatBackend(),
            dataset=_make_dataset(cases),
            ingest_plan=_version_change_ingest(),
        )
        try:
            result = await run_p2(
                plan,
                adapter=adapter,
                authorization=_dry_run_authorization(plan, now),
                now=now,
                gate_config=load_p2_gate_config(),
            )
            assert result.status == "succeeded", result.as_dict()
            binding = _read_json(adapter.paths.run_dir / "run_manifest.json")["binding"]
            return binding["index_revision"], binding["config_hash"]
        finally:
            await adapter.close()

    first = await one_run(tmp_path / "a")
    second = await one_run(tmp_path / "b")
    assert first == second
    assert first[0] == 4


# --------------------------------------------------------------------------- #
# 2. 反例：真实错绑仍然失败（不降级为 unknown / 通过）
# --------------------------------------------------------------------------- #


@asyncio_test
async def test_generic_entry_fails_on_real_misbinding(tmp_path: Path) -> None:
    cases = (_make_case("P01", RAG_QUESTION), _make_case("P03", LEGACY_QUESTION))
    plan, now = _make_plan(cases)
    config = load_p2_gate_config()
    adapter = ProductEvalAdapter(
        tmp_path / "misbind",
        chat=MockChatBackend(),
        dataset=_make_dataset(cases),
        ingest_plan=_version_change_ingest(),
    )
    try:
        result = await run_p2(
            plan,
            adapter=adapter,
            authorization=_dry_run_authorization(plan, now),
            now=now,
            gate_config=config,
        )
        assert result.status == "succeeded", result.as_dict()
        run_dir = adapter.paths.run_dir
        manifest = _read_json(run_dir / "run_manifest.json")
        summary = _read_json(run_dir / "summary.json")
        rows = _gate_rows(cases, _read_jsonl(run_dir / "cases.jsonl"))
        assert manifest["index_revision"] == 4

        # 反例 A：把绑定改回"产品资料发布版本"（修复前的老口径）——必须失败。
        # 反例 B：任意错值 5 —— 也必须失败（不是只认某一个魔法数字）。
        for wrong in (3, 5):
            tampered = dict(manifest, index_revision=wrong)
            tampered["binding"] = dict(manifest["binding"], index_revision=wrong)
            hard = evaluate_p2_hard_gates(
                build_gate_run(
                    run_dir=run_dir,
                    manifest=tampered,
                    cases=cases,
                    rows=rows,
                    summary=summary,
                ),
                config=config,
                require_trace=True,
            )
            assert hard.gate_status["trace_integrity"] == "fail", (wrong, hard.to_dict())
            assert "trace_integrity" in hard.hard_failures
            mismatch = [f for f in hard.failures if f.check_id == "version_binding"]
            assert mismatch, (wrong, hard.to_dict())
            assert all("index_revision" in f.evidence["mismatched"] for f in mismatch)
            # 失败不被降级成"待定/通过"。
            assert hard.exit_code != 0
    finally:
        await adapter.close()


# --------------------------------------------------------------------------- #
# 3. 缺证：RAG 索引版本不可得 → 绑定不完整（不猜数字、不写半套身份）
# --------------------------------------------------------------------------- #


@asyncio_test
async def test_generic_entry_keeps_binding_incomplete_when_index_version_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cases = (_make_case("P01", RAG_QUESTION),)
    plan, now = _make_plan(cases)
    adapter = ProductEvalAdapter(
        tmp_path / "unavailable",
        chat=MockChatBackend(),
        dataset=_make_dataset(cases),
        ingest_plan=_version_change_ingest(),
    )
    actual_status = adapter.index_status
    monkeypatch.setattr(
        adapter, "index_status", lambda: {**actual_status(), "ready": False}
    )
    try:
        result = await run_p2(
            plan,
            adapter=adapter,
            authorization=_dry_run_authorization(plan, now),
            now=now,
            gate_config=load_p2_gate_config(),
        )
        # dry-run 仍能跑完（不伪造版本），但身份不可用：绑定不完整、trace 不绑半套。
        assert result.status == "succeeded", result.as_dict()
        run_dir = adapter.paths.run_dir
        manifest = _read_json(run_dir / "run_manifest.json")
        binding = manifest["binding"]
        assert manifest["index_revision"] is None
        assert binding["complete"] is False
        assert binding["config_hash"] is None
        assert "index_revision" in binding["missing"]
        assert binding["trace_identity_bound"] is False
        case_rows = _read_jsonl(run_dir / "cases.jsonl")
        for case_row in case_rows:
            for turn in case_row["turns"]:
                trace = _trace(adapter, turn["trace_id"])
                # 身份六元组"缺一项就整体不绑"：除 index_revision 外都为 None。
                # （index_revision 仍可能由 RAG 检索器写自己那次的测量值——那是产品
                #   检索的观测，不是评测侧补写的绑定身份，故不在此处断言 None。）
                for name in ("run_id", "config_hash", "manifest_sha256", "pipeline_version"):
                    assert getattr(trace, name) is None, name
        # 缺证不能混进硬门禁：manifest 缺 index_revision 直接拒绝（fail closed）。
        rows = _gate_rows(cases, case_rows)
        with pytest.raises(P2ScoringError) as excinfo:
            build_gate_run(
                run_dir=run_dir, manifest=manifest, cases=cases, rows=rows
            )
        assert "run_manifest_incomplete" in str(excinfo.value)
    finally:
        await adapter.close()


# --------------------------------------------------------------------------- #
# 4. 测量窗口内漂移：停，不把混合版本 run 记成成功
# --------------------------------------------------------------------------- #


@asyncio_test
async def test_generic_entry_stops_when_index_drifts_mid_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cases = (_make_case("P01", RAG_QUESTION), _make_case("P03", LEGACY_QUESTION))
    plan, now = _make_plan(cases)
    adapter = ProductEvalAdapter(
        tmp_path / "drift",
        chat=MockChatBackend(),
        dataset=_make_dataset(cases),
        ingest_plan=_version_change_ingest(),
    )
    original_ask = adapter.ask_turn
    asks: list[str] = []

    async def ask_then_drift(question: str, **kwargs: Any):
        product = await original_ask(question, **kwargs)
        asks.append(question)
        index = adapter.app.state.qa.index()
        index.remove_document(index.list_documents()[0]["doc_id"])
        return product

    monkeypatch.setattr(adapter, "ask_turn", ask_then_drift)
    try:
        result = await run_p2(
            plan,
            adapter=adapter,
            authorization=_dry_run_authorization(plan, now),
            now=now,
            gate_config=load_p2_gate_config(),
        )
        assert (result.status, result.stop_code) == ("aborted", "index_changed")
        assert len(asks) == 1, asks
        run_dir = adapter.paths.run_dir
        summary = _read_json(run_dir / "summary.json")
        assert summary["failure"]["stage"] == "index_after_turn"
        assert summary["failure"]["case_id"] == "P01"
        assert summary["binding"]["index_revision"] == 4
        # 只发了第一轮；漂移之后的轮次没有发出（不重试、不补齐）。
        assert len(_read_jsonl(run_dir / "requests.jsonl")) == 1
    finally:
        await adapter.close()

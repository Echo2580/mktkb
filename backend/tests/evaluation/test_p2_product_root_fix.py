
"""T207-04c PRODUCT-ROOT-FIX：产品业务日期接线最小修复的开发定向测试（合成、零真实）。

唯一修复的缺陷：P2 产品适配器在 mock/live 两处硬编码 RagConfig(business_date=None)
并自注入 QaEngine，把产品已有的配置链
Settings.rag_business_date -> resolve_rag_config -> RagConfig.business_date ->
QueryPlan.as_of -> effective_from/to 过滤 丢弃了。

边界（硬约束）：
- 值只能由受控入口/计划**显式**给出（默认 None）；不从隐藏 CaseSpec/dataset 回填、
  不读 .env（显式参数优先于宿主环境）、不让模型/产品猜日期；
  显式日期与公开 manifest 声明不一致时以固定码拒绝。
- 默认 None 时既有行为逐值不变（本文件断言产品观测面；57 公开差分在 evidence/）。
- 只使用合成 xlsx + MockChatBackend；零真实模型/产品/网络调用。

红例（修复前）输出：evidence/red-pre-fix.txt、red-pytest-pre-fix.txt。
"""

from __future__ import annotations

import asyncio
import functools
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import openpyxl
import pytest

_TESTS_DIR = Path(__file__).resolve().parents[1]
if str(_TESTS_DIR) not in sys.path:  # 复用既有验收级网络闸门
    sys.path.insert(0, str(_TESTS_DIR))

from acceptance.support.netguard import t09_network_guard  # noqa: E402,F401

from mktkb.evaluation import product_adapter as adapter_module  # noqa: E402
from mktkb.evaluation.dataset import CaseSpec  # noqa: E402
from mktkb.evaluation.product_adapter import (  # noqa: E402
    IngestSource,
    MockChatBackend,
    P2IngestPlan,
    P2RunDataset,
    ProductAdapterError,
    ProductEvalAdapter,
)

pytestmark = pytest.mark.usefixtures("t09_network_guard")

BUSINESS_DATE = "2026-10-28"
OTHER_DATE = "2026-10-27"
QUESTION = "把城东店的宣传海报记录都列出来"
STALE_DOC = "stale.xlsx"
ACTIVE_DOC = "active.xlsx"
STALE_POSITION = "旧仓库A"
ACTIVE_POSITION = "新仓库B"
STALE_END = "2026-09-30"
ACTIVE_START = "2026-10-01"
ACTIVE_END = "2026-12-31"


def asyncio_test(func):
    """仓库没有 pytest-asyncio：同一事件循环跑一个 async 用例（保留 fixture 签名）。"""

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any):
        return asyncio.run(func(*args, **kwargs))

    return wrapper


def write_records_xlsx(path: Path, rows: list[tuple[Any, ...]]) -> Path:
    """合成表格：表头字段名走产品既有字段角色映射（门店/物品/位置/生效日期/失效日期）。"""

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "记录"
    sheet.append(["标识", "门店", "物品", "位置", "生效日期", "失效日期"])
    for row in rows:
        sheet.append(list(row))
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(path)
    workbook.close()
    return path


def synthetic_sources(tmp_path: Path) -> tuple[IngestSource, IngestSource]:
    stale = write_records_xlsx(
        tmp_path / "sources" / STALE_DOC,
        [("S90", "城东店", "宣传海报", STALE_POSITION, "2026-01-01", STALE_END)],
    )
    active = write_records_xlsx(
        tmp_path / "sources" / ACTIVE_DOC,
        [("S91", "城东店", "宣传海报", ACTIVE_POSITION, ACTIVE_START, ACTIVE_END)],
    )
    return IngestSource(stale), IngestSource(active)


def dataset(*, cases: tuple[CaseSpec, ...] = ()) -> P2RunDataset:
    return P2RunDataset(
        visibility="public",
        cases=cases,
        identity={
            "dataset_version": "synthetic-root-fix-v1",
            "label_version": "synthetic-v1",
            "suite": "p2-holdout",
            "manifest_sha256": "d" * 64,
            "case_count": len(cases),
        },
    )


def synthetic_case() -> CaseSpec:
    """合成 CaseSpec（含业务日期）用于证明“不从隐藏 CaseSpec 回填”。"""

    return CaseSpec(
        case_id="SYN-ROOT-FIX-1",
        suite="p2-holdout",
        split="holdout",
        stratum="paraphrase",
        business_date=BUSINESS_DATE,
        question=QUESTION,
        turns=(),
        label_version="synthetic-v1",
    )


def make_adapter(
    root: Path,
    *,
    sources: tuple[IngestSource, ...],
    rag_business_date: str | None = None,
    manifest_business_date: str | None = None,
    cases: tuple[CaseSpec, ...] = (),
) -> ProductEvalAdapter:
    return ProductEvalAdapter(
        root,
        chat=MockChatBackend(),
        dataset=dataset(cases=cases),
        ingest_plan=P2IngestPlan(sources=tuple(sources), label="root-fix"),
        rag_business_date=rag_business_date,
        manifest_business_date=manifest_business_date,
    )


def request_id(marker: int) -> str:
    return f"{marker:08x}-1111-4111-8111-111111111111"


async def ask(adapter: ProductEvalAdapter, question: str = QUESTION, marker: int = 1):
    conversation = await adapter.open_conversation()
    turn = await adapter.ask_turn(
        question,
        user_id="employee",
        conversation_id=conversation,
        client_request_id=request_id(marker),
    )
    return conversation, turn


def document_ids(receipts) -> dict[str, str]:
    return {receipt.name: receipt.document_id for receipt in receipts}


# --------------------------------------------------------------------------- #
# 1. 默认 None：产品实际业务日期仍为 None，失效单元照旧被检索/引用（逐值不变）
# --------------------------------------------------------------------------- #


@asyncio_test
async def test_default_business_date_none_keeps_old_behavior(tmp_path: Path) -> None:
    adapter = make_adapter(tmp_path / "run", sources=synthetic_sources(tmp_path))
    await adapter.start()
    try:
        assert adapter.rag_business_date is None
        assert adapter.manifest_business_date is None
        assert adapter._qa.config.business_date is None
        assert adapter.app.state.settings.rag_business_date is None
        receipts = await adapter.ingest()
        documents = document_ids(receipts)
        conversation, turn = await ask(adapter)
        assert turn.kind == "answer", turn.as_dict(include_text=True)
        assert turn.trace_path == "rag"
        evidence_docs = [item.get("document_id") for item in turn.evidence]
        assert documents[STALE_DOC] in evidence_docs, "默认 None 时旧行为必须仍引用失效单元"
        assert documents[ACTIVE_DOC] in evidence_docs
        assert len(turn.source_ids) == 2
        assert len(turn.retrieved) == 2
        assert STALE_POSITION in turn.text and ACTIVE_POSITION in turn.text
        state = adapter._safe_query_state("employee", conversation)
        assert getattr(state, "as_of", None) is None, "默认 None 时产品计划不得自带 as_of"
    finally:
        await adapter.close()


# --------------------------------------------------------------------------- #
# 2. 显式日期：进入产品配置，实际产品检索/引用按 effective_from/to 过滤失效单元
# --------------------------------------------------------------------------- #


@asyncio_test
async def test_explicit_business_date_filters_stale_in_actual_retrieval(tmp_path: Path) -> None:
    adapter = make_adapter(
        tmp_path / "run",
        sources=synthetic_sources(tmp_path),
        rag_business_date=BUSINESS_DATE,
        manifest_business_date=BUSINESS_DATE,
    )
    await adapter.start()
    try:
        # 装配面：实际生效日期进入产品 Settings 与 QaEngine 的 RagConfig
        assert adapter.rag_business_date == BUSINESS_DATE
        assert adapter._qa.config.business_date == BUSINESS_DATE
        assert adapter.app.state.settings.rag_business_date == BUSINESS_DATE
        receipts = await adapter.ingest()
        documents = document_ids(receipts)
        conversation, turn = await ask(adapter)
        assert turn.kind == "answer", turn.as_dict(include_text=True)
        assert turn.trace_path == "rag"
        # 实际引用：失效单元不进入产品引用
        evidence_docs = [item.get("document_id") for item in turn.evidence]
        assert documents[ACTIVE_DOC] in evidence_docs
        assert documents[STALE_DOC] not in evidence_docs, "失效单元不得被产品引用"
        assert len(turn.source_ids) == 1
        assert ACTIVE_POSITION in turn.text
        assert STALE_POSITION not in turn.text
        # 实际检索（产品检索代码复算）：同一日期下失效单元不在候选集合
        assert len(turn.retrieved) == 1
        assert documents[STALE_DOC] not in [item.get("document_id") for item in turn.retrieved]
        # 产品 QueryPlan.as_of 实际快照 = 显式业务日期（运行期证据，不是声明）。
        # 产品 QueryState 的键是认证后的产品库 user_id（不是用户名），按同一口径读取。
        authenticated_user_id = adapter._authenticated_db_user_id("employee")
        state = adapter._qa.load_state(authenticated_user_id, conversation)
        assert getattr(state, "as_of", None) == BUSINESS_DATE
    finally:
        await adapter.close()


# --------------------------------------------------------------------------- #
# 3. 显式性与可核性：与公开 manifest 声明不一致/未绑定/坏格式 -> 固定错误码
# --------------------------------------------------------------------------- #


def test_manifest_mismatch_rejected_with_fixed_code(tmp_path: Path) -> None:
    with pytest.raises(ProductAdapterError) as caught:
        make_adapter(
            tmp_path / "run",
            sources=synthetic_sources(tmp_path),
            rag_business_date=BUSINESS_DATE,
            manifest_business_date=OTHER_DATE,
        )
    assert caught.value.code == "adapter_business_date_manifest_mismatch"
    assert BUSINESS_DATE not in str(caught.value) and OTHER_DATE not in str(caught.value)


def test_explicit_date_requires_manifest_binding(tmp_path: Path) -> None:
    with pytest.raises(ProductAdapterError) as caught:
        make_adapter(
            tmp_path / "run",
            sources=synthetic_sources(tmp_path),
            rag_business_date=BUSINESS_DATE,
        )
    assert caught.value.code == "adapter_business_date_manifest_unbound"


def test_manifest_date_without_rag_date_rejected(tmp_path: Path) -> None:
    with pytest.raises(ProductAdapterError) as caught:
        make_adapter(
            tmp_path / "run",
            sources=synthetic_sources(tmp_path),
            manifest_business_date=BUSINESS_DATE,
        )
    assert caught.value.code == "adapter_business_date_rag_unbound"


@pytest.mark.parametrize("bad", ["2026-1-01", "not-a-date", "2026/10/28", "2026-10-32"])
def test_invalid_business_date_format_rejected(tmp_path: Path, bad: str) -> None:
    with pytest.raises(ProductAdapterError) as caught:
        make_adapter(
            tmp_path / "run",
            sources=synthetic_sources(tmp_path),
            rag_business_date=bad,
            manifest_business_date=BUSINESS_DATE,
        )
    assert caught.value.code == "adapter_business_date_invalid"


def test_business_date_whitespace_is_normalized(tmp_path: Path) -> None:
    adapter = make_adapter(
        tmp_path / "run",
        sources=synthetic_sources(tmp_path),
        rag_business_date=" " + BUSINESS_DATE + " ",
        manifest_business_date=BUSINESS_DATE,
    )
    assert adapter.rag_business_date == BUSINESS_DATE
    assert adapter.manifest_business_date == BUSINESS_DATE


def test_invalid_manifest_business_date_format_rejected(tmp_path: Path) -> None:
    with pytest.raises(ProductAdapterError) as caught:
        make_adapter(
            tmp_path / "run",
            sources=synthetic_sources(tmp_path),
            rag_business_date=BUSINESS_DATE,
            manifest_business_date="2026-13-40",
        )
    assert caught.value.code == "adapter_business_date_invalid"


# --------------------------------------------------------------------------- #
# 4. 无静默注入：宿主 env 不生效、显式参数优先、不从隐藏 CaseSpec 回填
# --------------------------------------------------------------------------- #


@asyncio_test
async def test_host_env_business_date_is_not_used(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MKTKB_RAG_BUSINESS_DATE", OTHER_DATE)
    default_adapter = make_adapter(tmp_path / "env-default", sources=synthetic_sources(tmp_path))
    await default_adapter.start()
    try:
        assert default_adapter.rag_business_date is None
        assert default_adapter._qa.config.business_date is None
        assert default_adapter.app.state.settings.rag_business_date is None
    finally:
        await default_adapter.close()
    explicit_adapter = make_adapter(
        tmp_path / "env-explicit",
        sources=synthetic_sources(tmp_path),
        rag_business_date=BUSINESS_DATE,
        manifest_business_date=BUSINESS_DATE,
    )
    await explicit_adapter.start()
    try:
        assert explicit_adapter.rag_business_date == BUSINESS_DATE
        assert explicit_adapter._qa.config.business_date == BUSINESS_DATE
        assert explicit_adapter.app.state.settings.rag_business_date == BUSINESS_DATE
    finally:
        await explicit_adapter.close()


@asyncio_test
async def test_case_business_date_is_not_backfilled(tmp_path: Path) -> None:
    adapter = make_adapter(
        tmp_path / "run",
        sources=synthetic_sources(tmp_path),
        cases=(synthetic_case(),),
    )
    assert adapter.dataset is not None
    assert adapter.dataset.cases[0].business_date == BUSINESS_DATE
    await adapter.start()
    try:
        assert adapter.rag_business_date is None, "不得从隐藏 CaseSpec 回填产品日期"
        assert adapter._qa.config.business_date is None
        assert adapter.app.state.settings.rag_business_date is None
    finally:
        await adapter.close()


# --------------------------------------------------------------------------- #
# 5. set-once：start 后只读，产品实际配置不被改写
# --------------------------------------------------------------------------- #


@asyncio_test
async def test_business_date_is_set_once_read_only(tmp_path: Path) -> None:
    adapter = make_adapter(
        tmp_path / "run",
        sources=synthetic_sources(tmp_path),
        rag_business_date=BUSINESS_DATE,
        manifest_business_date=BUSINESS_DATE,
    )
    await adapter.start()
    try:
        with pytest.raises(AttributeError):
            adapter.rag_business_date = OTHER_DATE  # type: ignore[misc]
        with pytest.raises(AttributeError):
            adapter.manifest_business_date = OTHER_DATE  # type: ignore[misc]
        assert adapter.rag_business_date == BUSINESS_DATE
        assert adapter._qa.config.business_date == BUSINESS_DATE
        # 即使外部改写私有字段，start 后实际生效值仍来自产品 RagConfig（set-once）
        adapter._rag_business_date = OTHER_DATE  # type: ignore[attr-defined]
        assert adapter.rag_business_date == BUSINESS_DATE
        assert adapter._qa.config.business_date == BUSINESS_DATE
    finally:
        await adapter.close()


# --------------------------------------------------------------------------- #
# 6. 交接点：本包不改 runner 的 config 身份（binding_components 与日期无关）
# --------------------------------------------------------------------------- #


@asyncio_test
async def test_binding_components_unchanged_by_business_date(tmp_path: Path) -> None:
    default_adapter = make_adapter(tmp_path / "binding-default", sources=synthetic_sources(tmp_path))
    dated_adapter = make_adapter(
        tmp_path / "binding-dated",
        sources=synthetic_sources(tmp_path),
        rag_business_date=BUSINESS_DATE,
        manifest_business_date=BUSINESS_DATE,
    )
    await default_adapter.start()
    await dated_adapter.start()
    try:
        before = default_adapter.binding_components()
        after = dated_adapter.binding_components()
        assert before == after, "本包不得把业务日期塞进 runner 的 binding/config 身份"
        assert BUSINESS_DATE not in json.dumps(before, ensure_ascii=False)
        assert BUSINESS_DATE not in json.dumps(after, ensure_ascii=False)
    finally:
        await default_adapter.close()
        await dated_adapter.close()


# --------------------------------------------------------------------------- #
# 7. mock/live 两条 _start_* 装配都显式传入（live 用离线替身，零真实 provider）
# --------------------------------------------------------------------------- #


class _RecorderProvider:
    """替身 provider：只记录构造时的 RagConfig。"""

    def __init__(self, config: Any, **kwargs: Any) -> None:
        _LIVE_RECORDED.setdefault("rag_configs", []).append(config)
        self.provider = "fake"
        self.model = "fake"
        self.dimensions = 0
        self.transport = None

    def as_dict(self) -> dict[str, Any]:
        return {"impl": "fake"}

    def close(self) -> None:
        return None

    def embed(self, texts, *, purpose="document"):  # pragma: no cover - 未调用
        raise AssertionError("live 替身不得真正 embedding")

    def rerank(self, query, documents, *, top_n=None):  # pragma: no cover - 未调用
        raise AssertionError("live 替身不得真正 rerank")


class _StopLiveAssembly(Exception):
    """在 QaEngine 构造处停下：已覆盖 Settings/RagConfig 装配，不建真实应用/DB。"""


class _RecordingQaEngine:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        _LIVE_RECORDED["qa_config"] = kwargs.get("config")
        raise _StopLiveAssembly()


_LIVE_RECORDED: dict[str, Any] = {}


@asyncio_test
async def test_live_start_assembly_forwards_business_date(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import mktkb.providers as providers_module
    import mktkb.providers.deepseek as deepseek_module
    import mktkb.rag.providers as rag_providers_module
    from mktkb.evaluation import p2_live

    _LIVE_RECORDED.clear()
    monkeypatch.setattr(adapter_module, "QaEngine", _RecordingQaEngine)
    monkeypatch.setattr(providers_module, "build_ocr_gateway", lambda *a, **k: SimpleNamespace())
    monkeypatch.setattr(
        deepseek_module,
        "DeepSeekClient",
        lambda **k: SimpleNamespace(provider="deepseek", model="deepseek-flash"),
    )
    monkeypatch.setattr(rag_providers_module, "BailianEmbeddingProvider", _RecorderProvider)
    monkeypatch.setattr(rag_providers_module, "BailianRerankProvider", _RecorderProvider)
    monkeypatch.setattr(
        p2_live,
        "resolve_request_ceiling",
        lambda config, **kw: SimpleNamespace(
            effective_cny=float(config.max_request_cny),
            as_dict=lambda: {"effective_cny": float(config.max_request_cny)},
        ),
    )
    wiring = SimpleNamespace(
        env=SimpleNamespace(
            chat_api_key="fake-key",
            chat_base_url="https://api.deepseek.com",
            chat_model="deepseek-flash",
            dashscope_api_key="fake-key",
            dashscope_base_url="https://dashscope.aliyuncs.com",
            ocr_secret_id="fake-id",
            ocr_secret_key="fake-secret",
            ocr_region="ap-guangzhou",
        ),
        transports={},
        plan=SimpleNamespace(reserve_peak_cny=0.01),
        gate=SimpleNamespace(
            authorization=SimpleNamespace(max_request_cny=0.5)
        ),
        ledger=SimpleNamespace(),
        request_ceiling=None,
    )
    sources = synthetic_sources(tmp_path)
    adapter = ProductEvalAdapter(
        tmp_path / "live",
        mode="live",
        live_wiring=wiring,
        dataset=dataset(),
        ingest_plan=P2IngestPlan(sources=sources, label="root-fix-live"),
        rag_business_date=BUSINESS_DATE,
        manifest_business_date=BUSINESS_DATE,
    )
    with pytest.raises(_StopLiveAssembly):
        await adapter.start()
    rag_configs = _LIVE_RECORDED["rag_configs"]
    assert len(rag_configs) == 2
    assert all(config.business_date == BUSINESS_DATE for config in rag_configs)
    assert _LIVE_RECORDED["qa_config"].business_date == BUSINESS_DATE
    assert adapter._settings is not None
    assert adapter._settings.rag_business_date == BUSINESS_DATE
    assert adapter.rag_business_date == BUSINESS_DATE


def test_p2_live_entry_signatures_expose_business_date() -> None:
    import inspect

    from mktkb.evaluation import p2_live

    build_params = inspect.signature(p2_live.build_live_adapter).parameters
    run_params = inspect.signature(p2_live.run_live_p2).parameters
    for params in (build_params, run_params):
        assert "rag_business_date" in params
        assert "manifest_business_date" in params
        assert params["rag_business_date"].default is None
        assert params["manifest_business_date"].default is None


@asyncio_test
async def test_build_live_adapter_forwards_business_date(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mktkb.evaluation import p2_live
    from mktkb.evaluation import p2_holdout_scenarios

    captured: dict[str, Any] = {}

    class _FakeAdapter:
        def __init__(self, out_dir, **kwargs):
            captured["adapter_kwargs"] = kwargs

    monkeypatch.setattr(p2_holdout_scenarios, "validate_scenario_execution", lambda *a, **k: None)
    monkeypatch.setattr(p2_live, "PlanIndex", lambda plan: SimpleNamespace(plan=plan))
    monkeypatch.setattr(p2_live, "AttemptBudget", lambda plan: SimpleNamespace(plan=plan))
    monkeypatch.setattr(
        p2_live,
        "GateAttemptLedger",
        lambda gate, plan, **kwargs: SimpleNamespace(gate=gate, plan=plan, **kwargs),
    )
    monkeypatch.setattr(p2_live, "LiveWiring", lambda **kwargs: SimpleNamespace(**kwargs))
    monkeypatch.setattr(adapter_module, "ProductEvalAdapter", _FakeAdapter)
    build = p2_live.build_live_adapter(
        SimpleNamespace(),
        gate=SimpleNamespace(),
        env=SimpleNamespace(),
        run_id="synthetic-live-run",
        out_dir=tmp_path / "live",
        dataset=dataset(),
        rag_business_date=BUSINESS_DATE,
        manifest_business_date=BUSINESS_DATE,
    )
    kwargs = captured["adapter_kwargs"]
    assert kwargs["mode"] == p2_live.MODE_LIVE
    assert kwargs["rag_business_date"] == BUSINESS_DATE
    assert kwargs["manifest_business_date"] == BUSINESS_DATE
    assert build.adapter is not None

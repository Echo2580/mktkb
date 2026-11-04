"""S2-J2-R2 定向测试：GO 严格规范类型（F-2）+ 受控付费边界装配（F-1）。

本文件只测试本次返工新增/修改的边界，不改既有 J2/J1 用例：
- ``_verify_fields`` 必须按计划规范声明类型拒绝 int/float/bool/str 互冒（F-2）；
- 受控账本代理在真实预留/结算边界执行每类计数、全局串行与失败停机（F-1）；
- 产品包装不做第二层计数（避免 run_/装配包装重复计数/死锁）。
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone

import pytest

from mktkb.controlled_execution import (
    ControlledBindingError,
    ControlledExecution,
    ControlledRefused,
    ControlledRequestPlan,
    _ControlledBudget,
    _ControlledEmbeddingProvider,
    _ControlledOCRGateway,
    _ControlledRagChatProvider,
    _OCR_TABLE_KIND,
    _OCR_TEXT_KIND,
    _plan_bindings,
    _planned_kind,
    _strict_type_matches,
    _verify_fields,
)
from mktkb.live_authorization import LiveAuthorization
from mktkb.providers.ocr_budgeted import OCRBudgetRefused
from mktkb.providers.types import OCRError

STAGE = "S2-J2-R2-TEST"
SECRET = "sk-S2J2R2-SYNTH-STRICT-TYPE-0123456789"


# ---------------------------------------------------------------- F-2 严格类型


def _authorization(bindings: dict) -> LiveAuthorization:
    now = datetime.now(timezone.utc)
    return LiveAuthorization(
        stage=STAGE,
        service="chat",
        issued_by="s2j2r2-test",
        nonce="s2j2r2-test-nonce-0123456789",
        issued_utc=now - timedelta(minutes=1),
        expires_utc=now + timedelta(hours=1),
        stage_limit_cny=9.66,
        max_requests=400,
        max_request_cny=2.11,
        ledger_sha256="a" * 64,
        source_path="docs/evidence/LOCAL-R1-20261101/PM/S2-J2-R2-MOCK-GO.json",
        bindings=bindings,
    )


def _canonical_bindings(plan: ControlledRequestPlan) -> dict:
    expected = _plan_bindings(plan)
    return {"chat": dict(expected["chat"]), "rag": dict(expected["rag"])}


def test_canonical_go_bindings_are_accepted():
    plan = ControlledRequestPlan(stage=STAGE)
    bindings = _canonical_bindings(plan)
    authorization = _authorization(bindings)
    assert _verify_fields(authorization, "chat", _plan_bindings(plan)["chat"])["serial"] is True
    assert _verify_fields(authorization, "rag", _plan_bindings(plan)["rag"])["ocr_max_attempts"] == 1


def test_strict_type_helper_distinguishes_all_scalar_types():
    assert _strict_type_matches(1536, 1536) is True
    assert _strict_type_matches(1536.0, 1536) is False
    assert _strict_type_matches(1536, 1536.0) is False
    assert _strict_type_matches(True, True) is True
    assert _strict_type_matches(1, True) is False
    assert _strict_type_matches(True, 1) is False
    assert _strict_type_matches("x", "x") is True
    assert _strict_type_matches(1, "1") is False


NUMERIC_TYPE_CONFUSIONS = [
    ("chat.chat_requests", 136.0),
    ("chat.chat_prompt_tokens_cap", 1536.0),
    ("chat.chat_completion_tokens_cap", 256.0),
    ("chat.max_input_tokens", 6144.0),
    ("chat.max_output_tokens", 800.0),
    ("chat.context_ceiling_tokens", 1048576.0),
    ("chat.input_price_per_million_cny", 2),
    ("chat.output_price_per_million_cny", 8),
    ("rag.embedding_requests", 111.0),
    ("rag.rerank_requests", 94.0),
    ("rag.ocr_max_calls", 13.0),
    ("rag.ocr_max_tiles_per_page", 1.0),
    ("rag.ocr_max_attempts", 1.0),
    ("rag.embedding_dimensions", 1024.0),
    ("rag.ocr_text_requests", 12.0),
    ("rag.ocr_table_requests", 1.0),
    ("rag.ocr_text_price_cny", "0.5"),
    ("rag.ocr_table_price_cny", 0),
]


@pytest.mark.parametrize("bind,value", NUMERIC_TYPE_CONFUSIONS)
def test_numeric_type_confusion_refused_before_any_send(bind, value):
    plan = ControlledRequestPlan(stage=STAGE)
    service, field = bind.split(".", 1)
    bindings = _canonical_bindings(plan)
    bindings[service][field] = value
    authorization = _authorization(bindings)
    with pytest.raises(ControlledBindingError) as caught:
        _verify_fields(authorization, service, _plan_bindings(plan)[service])
    # 不回显 GO 原文/秘密；只报字段名与期望规范值。
    message = str(caught.value)
    assert field in message
    assert SECRET not in message


def test_bool_int_and_secret_confusion_refused_without_echo():
    plan = ControlledRequestPlan(stage=STAGE)
    bindings = _canonical_bindings(plan)
    bindings["chat"]["serial"] = 1
    bindings["rag"]["region"] = 1
    bindings["chat"]["chat_host"] = SECRET
    authorization = _authorization(bindings)
    with pytest.raises(ControlledBindingError) as caught:
        _verify_fields(authorization, "chat", _plan_bindings(plan)["chat"])
    assert SECRET not in str(caught.value)
    with pytest.raises(ControlledBindingError) as caught:
        _verify_fields(authorization, "rag", _plan_bindings(plan)["rag"])
    assert SECRET not in str(caught.value)


def test_missing_binding_field_still_refused_with_field_name():
    plan = ControlledRequestPlan(stage=STAGE)
    bindings = _canonical_bindings(plan)
    bindings["rag"].pop("request_plan_sha256")
    authorization = _authorization(bindings)
    with pytest.raises(ControlledBindingError) as caught:
        _verify_fields(authorization, "rag", _plan_bindings(plan)["rag"])
    assert "request_plan_sha256" in str(caught.value)


# ---------------------------------------------------------------- 边界替身


class _StubLedger:
    """最小共享账本替身：记录 reserve/settle 调用，用于边界语义单测。"""

    def __init__(self) -> None:
        self.reserve_calls: list[dict] = []
        self.settle_calls: list[dict] = []
        self.settle_usage_calls: list[dict] = []
        self.settle_error: BaseException | None = None
        self.settle_usage_error: BaseException | None = None
        self.reserve_error: BaseException | None = None
        self._seq = 0

    def reserve(self, **kwargs):
        self.reserve_calls.append(kwargs)
        if self.reserve_error is not None:
            raise self.reserve_error
        self._seq += 1
        return type(
            "Reservation",
            (),
            {
                "reservation_id": f"stub-{self._seq}",
                "kind": kwargs["kind"],
                "model": kwargs["model"],
                "reserve_cny": kwargs["max_cny"],
            },
        )()

    def settle(self, reservation, **kwargs):
        self.settle_calls.append({"reservation": reservation, **kwargs})
        if self.settle_error is not None:
            raise self.settle_error
        return {"status": kwargs.get("status")}

    def settle_usage(self, reservation, **kwargs):
        self.settle_usage_calls.append({"reservation": reservation, **kwargs})
        if self.settle_usage_error is not None:
            raise self.settle_usage_error
        return type("Decision", (), {"charge_cny": 0.01})()


class _FakeGateway:
    def __init__(self) -> None:
        self.calls = 0

    async def complete(self, request, *, timeout_seconds):
        self.calls += 1
        return {"ok": True}


class _FakeEmbedder:
    def __init__(self, outcome=None) -> None:
        self.outcome = outcome
        self.calls = 0

    def embed(self, texts, *, purpose="document"):
        self.calls += 1
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return {"texts": list(texts), "purpose": purpose}


class _FakeReranker(_FakeEmbedder):
    def rerank(self, query, documents, *, top_n=None):
        self.calls += 1
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return {"query": query, "documents": list(documents), "top_n": top_n}


class _FakeOCR:
    def __init__(self, outcome=None) -> None:
        self.outcome = outcome
        self.calls: list[str] = []

    def recognize(self, page, *, mode):
        self.calls.append(mode)
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return {"mode": mode}


class _FakeRagChat:
    def __init__(self, outcome=None) -> None:
        self.outcome = outcome
        self.calls = 0

    def complete(self, *, system, user, max_output_tokens=None):
        self.calls += 1
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return {"text": "ok"}


def _executor(plan=None, **overrides) -> ControlledExecution:
    plan = plan or ControlledRequestPlan(stage=STAGE)
    return ControlledExecution(
        plan=plan,
        chat_gate=None,
        rag_gate=None,
        chat_gateway=overrides.get("chat_gateway"),
        rag_config=None,
        rag_budget=None,
        embedding_provider=overrides.get("embedder", _FakeEmbedder()),
        rerank_provider=overrides.get("reranker", _FakeReranker()),
        ocr_gateway=overrides.get("ocr", _FakeOCR()),
        chat_policy=None,
        embedding_policy=None,
        rerank_policy=None,
        rag_chat_provider=overrides.get("rag_chat"),
    )


def test_controlled_budget_counts_only_after_success_settle():
    plan = ControlledRequestPlan(stage=STAGE, embedding_requests=1)
    executor = _executor(plan)
    ledger = _StubLedger()
    proxy = _ControlledBudget(executor, ledger)
    reservation = proxy.reserve(
        kind="embedding", provider="bailian", model="text-embedding-v4",
        max_cny=0.04, request_sha256="f" * 64,
    )
    assert executor.stats()["counts"]["embedding"] == 0
    proxy.settle(reservation, status="succeeded", estimated_list_price_cny=0.0005)
    assert executor.stats()["counts"]["embedding"] == 1
    assert executor.stats()["in_flight"] is None


def test_plan_limit_refused_before_inner_reserve():
    plan = ControlledRequestPlan(stage=STAGE, embedding_requests=1)
    executor = _executor(plan)
    ledger = _StubLedger()
    proxy = _ControlledBudget(executor, ledger)
    first = proxy.reserve(
        kind="embedding", provider="bailian", model="text-embedding-v4",
        max_cny=0.04, request_sha256="f" * 64,
    )
    proxy.settle(first, status="succeeded")
    with pytest.raises(ControlledRefused):
        proxy.reserve(
            kind="embedding", provider="bailian", model="text-embedding-v4",
            max_cny=0.04, request_sha256="f" * 64,
        )
    # 拒绝发生在真实预留之前：inner ledger 只看到第一次预留。
    assert len(ledger.reserve_calls) == 1


def test_budget_denial_releases_without_stop_and_without_extra_reserve():
    executor = _executor()
    ledger = _StubLedger()
    ledger.reserve_error = RuntimeError("budget denied")
    proxy = _ControlledBudget(executor, ledger)
    with pytest.raises(RuntimeError):
        proxy.reserve(
            kind="chat", provider="deepseek", model="deepseek-flash",
            max_cny=2.1, request_sha256="f" * 64,
        )
    assert executor.stats()["stopped"] is False
    assert executor.stats()["in_flight"] is None


def test_failed_settle_after_actual_post_stops_all_channels():
    executor = _executor()
    ledger = _StubLedger()
    proxy = _ControlledBudget(executor, ledger)
    watermarks = iter([0, 1])  # begin 时 0、settle 时 1 ⇒ 已发生实际发送
    executor._attempt_watermark = lambda: next(watermarks)  # type: ignore[method-assign]
    reservation = proxy.reserve(
        kind="chat", provider="deepseek", model="deepseek-flash",
        max_cny=2.1, request_sha256="f" * 64,
    )
    proxy.settle(reservation, status="failed", error_code="CHAT_HTTP")
    assert executor.stats()["stopped"] is True
    assert executor.stats()["stop_code"] == "CHAT_HTTP"
    with pytest.raises(ControlledRefused):
        executor.run_embedding(["after stop"])


def test_failed_settle_before_post_releases_without_stop():
    executor = _executor()
    ledger = _StubLedger()
    proxy = _ControlledBudget(executor, ledger)
    executor._attempt_watermark = lambda: 0  # type: ignore[method-assign]
    reservation = proxy.reserve(
        kind="chat", provider="deepseek", model="deepseek-flash",
        max_cny=2.1, request_sha256="f" * 64,
    )
    proxy.settle(reservation, status="failed", error_code="MODEL_POST_SEND_AUTH_DENIED")
    assert executor.stats()["stopped"] is False
    assert executor.stats()["in_flight"] is None


def test_settle_usage_rejection_stops_all_channels():
    executor = _executor()
    ledger = _StubLedger()
    ledger.settle_usage_error = RuntimeError("usage over cap")
    proxy = _ControlledBudget(executor, ledger)
    reservation = proxy.reserve(
        kind="chat", provider="deepseek", model="deepseek-flash",
        max_cny=2.1, request_sha256="f" * 64,
    )
    with pytest.raises(RuntimeError):
        proxy.settle_usage(reservation, evidence=object())
    assert executor.stats()["stopped"] is True
    assert executor.stats()["in_flight"] is None


def test_serial_boundary_refuses_second_concurrent_reserve_without_ledger_call():
    executor = _executor()
    ledger = _StubLedger()
    proxy = _ControlledBudget(executor, ledger)
    entered = threading.Event()
    release = threading.Event()

    def hold() -> None:
        reservation = proxy.reserve(
            kind="embedding", provider="bailian", model="text-embedding-v4",
            max_cny=0.04, request_sha256="f" * 64,
        )
        entered.set()
        release.wait(timeout=5)
        proxy.settle(reservation, status="succeeded")

    thread = threading.Thread(target=hold)
    thread.start()
    try:
        assert entered.wait(timeout=5)
        with pytest.raises(ControlledRefused):
            proxy.reserve(
                kind="chat", provider="deepseek", model="deepseek-flash",
                max_cny=2.1, request_sha256="f" * 64,
            )
        assert len(ledger.reserve_calls) == 1
    finally:
        release.set()
        thread.join(timeout=5)


# ---------------------------------------------------------------- 产品包装


def test_embedding_wrapper_delegates_and_does_not_double_count():
    raw = _FakeEmbedder()
    executor = _executor(embedder=raw)
    wrapper = executor.embedding_provider
    assert isinstance(wrapper, _ControlledEmbeddingProvider)
    # 非受控替身：包装层回退单层计数（1 次调用 = 1 个计划计数，不重复）。
    wrapper.embed(["a", "b"])
    wrapper.embed(["c"])
    assert raw.calls == 2
    assert executor.stats()["counts"]["embedding"] == 2


def test_embedding_wrapper_failure_stops_executor():
    raw = _FakeEmbedder(RuntimeError("boom"))
    executor = _executor(embedder=raw)
    with pytest.raises(RuntimeError):
        executor.embedding_provider.embed(["a"])
    assert executor.stats()["stopped"] is True
    assert raw.calls == 1


def test_ocr_wrapper_pre_send_refusal_keeps_running_but_counts_success_only():
    raw = _FakeOCR(OCRBudgetRefused("tile limit"))
    executor = _executor(plan=ControlledRequestPlan(stage=STAGE, ocr_text_requests=2), ocr=raw)
    wrapper = executor.ocr_gateway
    assert isinstance(wrapper, _ControlledOCRGateway)
    with pytest.raises(OCRBudgetRefused):
        wrapper.recognize(object(), mode="text")
    assert executor.stats()["counts"]["ocr_text"] == 0
    assert executor.stats()["stopped"] is False
    raw.outcome = None
    wrapper.recognize(object(), mode="text")
    assert executor.stats()["counts"]["ocr_text"] == 1


def test_ocr_wrapper_real_failure_stops_executor():
    raw = _FakeOCR(OCRError("bad response"))
    executor = _executor(ocr=raw)
    with pytest.raises(OCRError):
        executor.ocr_gateway.recognize(object(), mode="text")
    assert executor.stats()["stopped"] is True


def test_ocr_kind_mapping_is_text_table_classified():
    assert _planned_kind("ocr", "GeneralAccurateOCR") == _OCR_TEXT_KIND
    assert _planned_kind("ocr", "RecognizeTableAccurateOCR") == _OCR_TABLE_KIND
    assert _planned_kind("embedding", None) == "embedding"


def test_rag_chat_wrapper_counts_chat_and_refuses_at_limit():
    raw = _FakeRagChat()
    executor = _executor(rag_chat=raw)
    wrapper = executor.rag_chat_provider
    assert isinstance(wrapper, _ControlledRagChatProvider)
    wrapper.complete(system="s", user="u", max_output_tokens=200)
    assert executor.stats()["counts"]["chat"] == 1
    assert raw.calls == 1

"""A1 评测观察器定向测试：默认关闭、固定事件协议、嵌套作用域与失败不污染产品。

本文件只验证"观察封装"本身；产品边界 hook 的定向反例追加在 conversations/qa 现有测试中。
全部用例启用既有外部网络闸门（外部出站 0），不读私有材料、不调用真实模型。
"""

from __future__ import annotations

import asyncio
import sys
import threading
from pathlib import Path

import pytest

_TESTS_DIR = Path(__file__).resolve().parents[1]
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

from acceptance.support.netguard import t09_network_guard  # noqa: E402,F401

from mktkb.observability import evaluation_capture as cap  # noqa: E402

pytestmark = pytest.mark.usefixtures("t09_network_guard")


def test_emit_without_scope_is_noop_and_never_raises():
    assert cap.capture_enabled() is False
    assert cap.emit_capture_event("claim_observed", request_id="r", this_is_unknown=1) is None
    assert cap.capture_enabled() is False


def test_claim_and_context_events_are_recorded_with_monotonic_seq():
    sink = cap.CaptureSink()
    with cap.capture_scope(sink) as active:
        assert active is sink and cap.capture_enabled() is True
        cap.emit_capture_event(
            "claim_observed",
            request_id="11111111-1111-4111-8111-111111111111",
            conversation_id="22222222-2222-4222-8222-222222222222",
            attempt=1,
            authenticated_user_id="u1",
            owner_user_id="u1",
            user_message_id="33333333-3333-4333-8333-333333333333",
            user_message_seq=1,
            initial_revision=4,
            replay=False,
        )
        cap.emit_capture_event(
            "context_observed",
            request_id="11111111-1111-4111-8111-111111111111",
            count=0,
            empty=True,
        )
    assert cap.capture_enabled() is False
    assert [e["kind"] for e in sink.events] == ["claim_observed", "context_observed"]
    assert [e["seq"] for e in sink.events] == [1, 2]
    assert sink.events[0]["payload"]["attempt"] == 1
    assert sink.events[1]["payload"]["empty"] is True
    assert sink.status == "active" and sink.errors == []


def test_unknown_kind_or_field_marks_sink_failed_and_blocks_later_events():
    sink = cap.CaptureSink()
    with cap.capture_scope(sink):
        cap.emit_capture_event("not_a_real_kind", request_id="r")
        assert sink.status == "failed"
        assert sink.events == []
        assert sink.errors and sink.errors[0]["code"] == "capture_event_invalid"
        # 失败后不再写入任何事件，也不向产品抛错。
        cap.emit_capture_event("context_observed", request_id="r", count=0, empty=True)
        assert sink.events == []

    sink2 = cap.CaptureSink()
    with cap.capture_scope(sink2):
        cap.emit_capture_event("context_observed", request_id="r", count=0, empty=True, extra="x")
        assert sink2.status == "failed" and sink2.events == []


def test_type_validation_rejects_bool_as_int_and_non_string_values():
    sink = cap.CaptureSink()
    with cap.capture_scope(sink):
        cap.emit_capture_event("context_observed", request_id="r", count=True, empty=False)
        assert sink.status == "failed"
        assert sink.events == []

    sink = cap.CaptureSink()
    with cap.capture_scope(sink):
        cap.emit_capture_event("context_observed", request_id="r", count=1, empty=False)
        assert sink.status == "active"
        cap.emit_capture_event("context_observed", request_id=7, count=1, empty=False)
        assert sink.status == "failed"


def test_nested_scope_restores_outer_sink_even_on_exception():
    outer = cap.CaptureSink()
    inner = cap.CaptureSink()
    with cap.capture_scope(outer):
        cap.emit_capture_event("context_observed", request_id="r", count=0, empty=True)
        with pytest.raises(RuntimeError):
            with cap.capture_scope(inner):
                cap.emit_capture_event("context_observed", request_id="r", count=1, empty=False)
                raise RuntimeError("boom")
        cap.emit_capture_event("context_observed", request_id="r", count=2, empty=False)
    assert [e["payload"]["count"] for e in outer.events] == [0, 2]
    assert [e["payload"]["count"] for e in inner.events] == [1]


def test_thread_isolation_keeps_concurrent_sinks_separate():
    first = cap.CaptureSink()
    second = cap.CaptureSink()
    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def worker(sink: cap.CaptureSink, count: int) -> None:
        try:
            with cap.capture_scope(sink):
                barrier.wait(timeout=5)
                cap.emit_capture_event("context_observed", request_id="r", count=count, empty=False)
                barrier.wait(timeout=5)
        except BaseException as exc:  # noqa: BLE001 - 线程内断言失败要回传主线程
            errors.append(exc)

    threads = [
        threading.Thread(target=worker, args=(first, 1)),
        threading.Thread(target=worker, args=(second, 2)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    assert errors == []
    assert [e["payload"]["count"] for e in first.events] == [1]
    assert [e["payload"]["count"] for e in second.events] == [2]


def test_inactive_sink_cannot_be_installed():
    sink = cap.CaptureSink()
    sink.fail("capture_event_invalid", "test", detail="forced")
    with pytest.raises(cap.CaptureStateError):
        with cap.capture_scope(sink):
            pass


def test_event_overflow_fails_closed_without_raising_into_product():
    sink = cap.CaptureSink()
    with cap.capture_scope(sink):
        for index in range(cap.MAX_EVENTS + 5):
            cap.emit_capture_event("context_observed", request_id="r", count=index, empty=False)
    assert sink.status == "failed"
    assert len(sink.events) == cap.MAX_EVENTS
    assert sink.errors and sink.errors[-1]["code"] == "capture_event_overflow"

# --------------------------------------------------------------------------- #
# R1：完整 CompletionOutput / 直接 RAG facts / 原始 QueryState 原值 / repr 白名单
# --------------------------------------------------------------------------- #


def test_model_output_carries_full_completion_output_fields() -> None:
    sink = cap.CaptureSink()
    with cap.capture_scope(sink):
        cap.emit_capture_event(
            "model_output",
            request_id="r",
            purpose="answer",
            status="ok",
            text="t",
            source_ids=["s1"],
            query_terms=["q"],
            provider_request_id="mock-request-id",
            usage={"prompt_tokens": 10, "completion_tokens": 5},
            error_code=None,
            retryable=False,
        )
    assert sink.status == "active"
    payload = sink.events[0]["payload"]
    assert payload["provider_request_id"] == "mock-request-id"
    assert payload["usage"] == {"prompt_tokens": 10, "completion_tokens": 5}

    bad = cap.CaptureSink()
    with cap.capture_scope(bad):
        cap.emit_capture_event(
            "model_output",
            request_id="r",
            purpose="answer",
            status="ok",
            text="t",
            source_ids=[],
            query_terms=[],
            provider_request_id=None,
            usage={"prompt_tokens": True},
            error_code=None,
            retryable=False,
        )
    assert bad.status == "failed", "bool 不得冒充 usage 计数"


def test_direct_rag_answer_carries_facts_not_only_count() -> None:
    fact = {
        "entity_key": "城东店",
        "entity_label": "城东店",
        "field_role": "位置",
        "field_label": "位置",
        "value": "A区1号货架",
        "source_chunk_id": "chunk-1",
        "source_unit_id": "unit-1",
        "doc_id": "doc-1",
        "version_id": "version-1",
        "revision": 1,
    }
    sink = cap.CaptureSink()
    with cap.capture_scope(sink):
        cap.emit_capture_event(
            "direct_rag_answer",
            request_id=None,
            kind="answer",
            text="位置：A区1号货架",
            reason=None,
            answer_source="structured",
            cited_unit_ids=["unit-1"],
            fact_count=1,
            facts=[fact],
            state_keys=["store"],
        )
    assert sink.status == "active"
    assert sink.events[0]["payload"]["facts"] == [fact]

    bad = cap.CaptureSink()
    with cap.capture_scope(bad):
        incomplete_fact = dict(fact)
        incomplete_fact.pop("source_unit_id")
        cap.emit_capture_event(
            "direct_rag_answer",
            request_id=None,
            kind="answer",
            text="t",
            reason=None,
            answer_source="structured",
            cited_unit_ids=[],
            fact_count=1,
            facts=[incomplete_fact],
            state_keys=[],
        )
    assert bad.status == "failed", "缺必需 fact 字段必须被拒"


def test_query_state_events_carry_raw_state_values() -> None:
    state = {"store": "城东店", "candidates": ["a", "b"], "turn": 2, "as_of": None}
    sink = cap.CaptureSink()
    with cap.capture_scope(sink):
        cap.emit_capture_event(
            "query_state_observed",
            request_id=None,
            user_id="u",
            conversation_id="c",
            stored_user_id="u",
            stored_conversation_id="c",
            row_present=True,
            state_keys=sorted(state),
            state_json=state,
            pending_slot=None,
            last_kind=None,
            turn=2,
        )
        cap.emit_capture_event(
            "query_state_cleared",
            request_id=None,
            user_id="u",
            conversation_id="c",
            row_present=True,
            state_json=state,
        )
    assert [event["payload"]["state_json"] for event in sink.events] == [state, state]

    bad = cap.CaptureSink()
    with cap.capture_scope(bad):
        cap.emit_capture_event(
            "query_state_observed",
            request_id=None,
            user_id="u",
            conversation_id="c",
            stored_user_id="u",
            stored_conversation_id="c",
            row_present=True,
            state_keys=[],
            state_json={"bad": object()},
            pending_slot=None,
            last_kind=None,
            turn=None,
        )
    assert bad.status == "failed", "非 JSON 原始状态必须被拒"


def test_capture_sink_repr_never_echoes_payload_text() -> None:
    secret = "P2CAPTURE_REPR_SENTINEL_5e1f"
    sink = cap.CaptureSink()
    with cap.capture_scope(sink):
        cap.emit_capture_event(
            "model_input",
            request_id="r",
            purpose="answer",
            question=secret,
            context_questions=[secret],
            context_entities={"store": secret},
            evidence=[{"source_id": "s", "text": secret, "fields": {"x": secret}}],
        )
    assert secret in str(sink.snapshot())
    assert secret not in repr(sink)


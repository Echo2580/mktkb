"""P0（2026-11-23）：DeepSeek 输入闸门的离线复现与修复回归。

覆盖两条生产链路，全程 MockTransport / 替身，不发起任何真实请求、不写真实账本：

1. legacy：``conversations.service._model_input`` + ``BudgetedModelGateway``；
2. RAG 文档回答：``rag.answer._document_chat_payload`` + ``DeepSeekChatProvider``。

修复前的本地误拒（UTF-8 字节数被当作 token 上界）在 ``docs/reports`` 记录的同一现象；
这里固定修复后的验收行为：中文证据按真实 payload 字节预算裁剪、恰好发送 1 次、
单条证据超限返回 MODEL_INPUT_TOO_LARGE 且 HTTP/预留均为 0、错误分类不回归。
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from mktkb import copy as copy_module
from mktkb.conversations import service as conversation_service
from mktkb.providers.budgeted import BudgetedModelGateway, ChatPricing
from mktkb.providers.deepseek import DeepSeekClient, completion_message_bytes
from mktkb.providers.types import (
    CompletionInput,
    DialogueContext,
    ModelEvidence,
    ModelInputTooLarge,
    ModelUnavailable,
)
from mktkb.rag.answer import _document_chat_payload
from mktkb.rag.budget import BudgetLedger
from mktkb.rag.config import (
    CONSERVATIVE_CONTEXT_CEILING_TOKENS,
    RESERVE_PROFILE_CONTEXT_CEILING,
    RagConfig,
)
from mktkb.rag.errors import ChatInputTooLarge
from mktkb.rag.providers import DeepSeekChatProvider
from mktkb.rag.types import RagAnswer

LIMIT = 6144
QUESTION = "领取活动物料需要哪些步骤？"
CHINESE_BODY = (
    "活动物料领取步骤：门店在活动开始前三个工作日提交物料申请，经区域经理审批后由仓库统一配送，"
    "门店签收后需在系统内登记入库数量。"
) * 6


# ---------------------------------------------------------------- 装配


def _budget_ledger(tmp_path: Path) -> BudgetLedger:
    ledger = tmp_path / "live-ledger.jsonl"
    ledger.write_text("", encoding="utf-8")
    budget = tmp_path / "budget.json"
    budget.write_text(
        json.dumps({"limit_cny": 10.0, "stages": {"P0-TEST": 5.0}}),
        encoding="utf-8",
    )
    return BudgetLedger(ledger, budget, stage="P0-TEST", stage_limit_cny=5.0, max_requests=5)


def _chat_counts(ledger: BudgetLedger) -> tuple[int, int]:
    lines = [
        json.loads(line)
        for line in ledger.ledger_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return (
        sum(1 for event in lines if event.get("event") == "reserved" and event.get("kind") == "chat"),
        sum(1 for event in lines if event.get("event") == "result" and event.get("kind") == "chat"),
    )


def _ok_response(source_ids: tuple[str, ...] = ("unit-0",)) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "id": "mock-ok",
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {
                        "content": json.dumps(
                            {"answer": "按资料回答", "source_ids": list(source_ids)},
                            ensure_ascii=False,
                        )
                    },
                }
            ],
            "usage": {"prompt_tokens": 120, "completion_tokens": 12, "total_tokens": 132},
        },
    )


def _legacy_gateway(
    tmp_path: Path,
    *,
    response_handler=None,
) -> tuple[BudgetedModelGateway, BudgetLedger, dict]:
    calls: dict = {"n": 0, "body": None}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        calls["body"] = json.loads(request.content)
        if response_handler is not None:
            return response_handler(request)
        return _ok_response()

    book = _budget_ledger(tmp_path)
    pricing = ChatPricing(
        input_price_per_million_cny=2.0,
        output_price_per_million_cny=8.0,
        max_input_tokens=LIMIT,
        max_output_tokens=800,
        reserve_profile=RESERVE_PROFILE_CONTEXT_CEILING,
        context_ceiling_tokens=CONSERVATIVE_CONTEXT_CEILING_TOKENS,
    )
    inner = DeepSeekClient(
        base_url="https://api.deepseek.com",
        model="deepseek-flash",
        api_key="mock-key",
        max_output_tokens=800,
        transport=httpx.MockTransport(handler),
    )
    gateway = BudgetedModelGateway(
        inner,
        gate=SimpleNamespace(max_request_cny=3.0, stage="P0-TEST", authorization=None),
        pricing=pricing,
        budget=book,
    )
    return gateway, book, calls


def _legacy_request() -> CompletionInput:
    return CompletionInput(
        purpose="answer",
        question=QUESTION,
        context=DialogueContext(),
        evidence=tuple(
            ModelEvidence(source_id=f"unit-{i}", text=CHINESE_BODY, fields={"门店": f"门店-{i}"})
            for i in range(6)
        ),
    )


def _rag_config() -> RagConfig:
    return RagConfig(
        provider_mode="offline",
        embedding_api_key="sk-test",
        rerank_api_key="sk-test",
        embedding_base_url="https://example.invalid",
        rerank_base_url="https://example.invalid",
        max_retries=0,
        chat_base_url="https://api.deepseek.com",
        chat_model="deepseek-flash",
        chat_api_key="sk-test",
        chat_input_price_per_million_cny=2.0,
        chat_output_price_per_million_cny=8.0,
        chat_max_input_tokens=LIMIT,
        chat_max_output_tokens=800,
        chat_reserve_profile=RESERVE_PROFILE_CONTEXT_CEILING,
        chat_context_ceiling_tokens=CONSERVATIVE_CONTEXT_CEILING_TOKENS,
        max_output_tokens=800,
        max_request_cny=3.0,
    )


def _rag_evidence(count: int = 8):
    return [
        SimpleNamespace(chunk_id=f"c{i}", text=CHINESE_BODY, fields={"门店": f"门店-{i}"})
        for i in range(count)
    ]


RAG_SYSTEM = "你是市场部知识库问答助手。只能依据 user JSON 的 evidence 回答。"


# ---------------------------------------------------------------- legacy


def test_legacy_repro_fails_locally_before_send(tmp_path: Path) -> None:
    """复现：原始最终 payload 超过字节上界时，当前实现未裁剪就交给网关 → 本地拒发。"""
    gateway, book, calls = _legacy_gateway(tmp_path)
    request = _legacy_request()
    assert completion_message_bytes(request) > LIMIT
    with pytest.raises(ModelInputTooLarge):
        asyncio.run(gateway.complete(request, timeout_seconds=5.0))
    assert calls["n"] == 0
    assert _chat_counts(book) == (0, 0)


def test_legacy_chinese_evidence_is_budgeted_then_sent_once(tmp_path: Path) -> None:
    """修复：按真实 payload 字节预算保留完整证据，恰好 1 次 HTTP + 1 组 chat 预留/结果。"""
    gateway, book, calls = _legacy_gateway(tmp_path)
    request = _legacy_request()
    fitted = conversation_service._fit_model_input(gateway, request)
    assert completion_message_bytes(fitted) <= LIMIT
    assert len(fitted.evidence) >= 1
    assert len(fitted.evidence) < len(request.evidence)
    assert [item.source_id for item in fitted.evidence] == [
        f"unit-{i}" for i in range(len(fitted.evidence))
    ]
    assert fitted.evidence[0].fields == {"门店": "门店-0"}
    assert fitted.evidence[0].text == CHINESE_BODY

    output = asyncio.run(gateway.complete(fitted, timeout_seconds=5.0))
    assert output.text == "按资料回答"
    assert calls["n"] == 1
    assert _chat_counts(book) == (1, 1)
    sent = json.loads(calls["body"]["messages"][1]["content"])["evidence"]
    assert [item["source_id"] for item in sent] == [item.source_id for item in fitted.evidence]
    assert sent[0]["text"] == CHINESE_BODY


def test_legacy_first_evidence_too_large_returns_input_too_large(tmp_path: Path) -> None:
    """首条完整证据自身超限：明确输入超限，HTTP=0、chat reserve=0、不可重试。"""
    gateway, book, calls = _legacy_gateway(tmp_path)
    huge = CompletionInput(
        purpose="answer",
        question=QUESTION,
        context=DialogueContext(),
        evidence=(ModelEvidence(source_id="unit-0", text=CHINESE_BODY * 6, fields={}),),
    )
    assert completion_message_bytes(huge) > LIMIT
    with pytest.raises(ModelInputTooLarge) as raised:
        conversation_service._fit_model_input(gateway, huge)
    assert raised.value.code == "MODEL_INPUT_TOO_LARGE"
    assert raised.value.retryable is False

    with pytest.raises(ModelInputTooLarge):
        asyncio.run(gateway.complete(huge, timeout_seconds=5.0))
    assert calls["n"] == 0
    assert _chat_counts(book) == (0, 0)

    code, retryable = conversation_service._classify_model_error(ModelInputTooLarge())
    assert (code, retryable) == ("MODEL_INPUT_TOO_LARGE", False)
    result = conversation_service._model_failure_result(ModelInputTooLarge(), 1)
    assert result.kind == "service_error"
    assert result.error_code == "MODEL_INPUT_TOO_LARGE"
    assert result.retryable is False
    assert "服务暂不可用" not in result.text
    assert "DeepSeek" not in result.text
    assert "单次模型输入上限" in result.text


def test_legacy_record_mode_refuses_instead_of_partial_enumeration(tmp_path: Path) -> None:
    """记录型枚举不允许裁剪证据（少一条记录会把完整枚举静默变成不完整答案）。"""
    gateway, _, calls = _legacy_gateway(tmp_path)
    with pytest.raises(ModelInputTooLarge):
        conversation_service._fit_model_input(gateway, _legacy_request(), allow_trim=False)
    assert calls["n"] == 0


def test_legacy_next_request_recovers_after_input_too_large(tmp_path: Path) -> None:
    """一次输入超限不得停掉后续合法请求。"""
    gateway, book, calls = _legacy_gateway(tmp_path)
    huge = CompletionInput(
        purpose="answer",
        question=QUESTION,
        context=DialogueContext(),
        evidence=(ModelEvidence(source_id="unit-0", text=CHINESE_BODY * 6, fields={}),),
    )
    with pytest.raises(ModelInputTooLarge):
        asyncio.run(gateway.complete(huge, timeout_seconds=5.0))
    assert calls["n"] == 0
    assert _chat_counts(book) == (0, 0)

    small = CompletionInput(
        purpose="answer",
        question=QUESTION,
        context=DialogueContext(),
        evidence=(ModelEvidence(source_id="unit-0", text="第一步：提交物料申请。", fields={}),),
    )
    output = asyncio.run(gateway.complete(small, timeout_seconds=5.0))
    assert output.text == "按资料回答"
    assert calls["n"] == 1
    assert _chat_counts(book) == (1, 1)


def test_provider_429_still_maps_to_model_unavailable(tmp_path: Path) -> None:
    """真正的供应商限流仍必须是 MODEL_UNAVAILABLE（分类不回归）。"""

    def rate_limited(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429)

    gateway, _, calls = _legacy_gateway(tmp_path, response_handler=rate_limited)
    small = CompletionInput(
        purpose="answer",
        question=QUESTION,
        context=DialogueContext(),
        evidence=(ModelEvidence(source_id="unit-0", text="第一步：提交物料申请。", fields={}),),
    )
    with pytest.raises(ModelUnavailable) as raised:
        asyncio.run(gateway.complete(small, timeout_seconds=5.0))
    assert raised.value.code == "MODEL_UNAVAILABLE"
    assert raised.value.retryable is True


# ---------------------------------------------------------------- RAG 文档回答


def test_rag_evidence_is_budgeted_then_sent_once() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(
            200,
            json={
                "id": "mock-rag",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(
                                {"answer": "按资料回答", "source_ids": ["c0"]},
                                ensure_ascii=False,
                             )
                        },
                    }
                ],
                "usage": {"prompt_tokens": 120, "completion_tokens": 12, "total_tokens": 132},
            },
        )

    items = _rag_evidence()
    kept, user = _document_chat_payload(RAG_SYSTEM, QUESTION, items, max_bytes=LIMIT)
    assert 1 <= len(kept) < len(items)
    assert len(RAG_SYSTEM.encode("utf-8")) + len(user.encode("utf-8")) <= LIMIT
    assert [item.chunk_id for item in kept] == [f"c{i}" for i in range(len(kept))]
    assert kept[0].fields == {"门店": "门店-0"}
    assert kept[0].text == CHINESE_BODY

    provider = DeepSeekChatProvider(
        _rag_config(), transport=httpx.MockTransport(handler), require_budget=False
    )
    try:
        response = provider.complete(system=RAG_SYSTEM, user=user)
        assert response.text
    finally:
        provider.close()
    assert calls["n"] == 1


def test_rag_first_evidence_too_large_is_input_too_large() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json={})

    items = [SimpleNamespace(chunk_id="c0", text=CHINESE_BODY * 6, fields={})]
    with pytest.raises(ChatInputTooLarge) as raised:
        _document_chat_payload(RAG_SYSTEM, QUESTION, items, max_bytes=LIMIT)
    assert raised.value.code == "MODEL_INPUT_TOO_LARGE"
    assert raised.value.retryable is False

    huge_user = json.dumps(
        {"question": QUESTION, "evidence": [{"chunk_id": "c0", "text": CHINESE_BODY * 6, "fields": {}}]},
        ensure_ascii=False,
    )
    provider = DeepSeekChatProvider(
        _rag_config(), transport=httpx.MockTransport(handler), require_budget=False
    )
    try:
        with pytest.raises(ChatInputTooLarge) as gate:
            provider.complete(system=RAG_SYSTEM, user=huge_user)
    finally:
        provider.close()
    assert gate.value.code == "MODEL_INPUT_TOO_LARGE"
    assert calls["n"] == 0


def test_rag_turn_result_keeps_input_too_large_code_and_copy() -> None:
    answer = RagAnswer(
        kind="error",
        question=QUESTION,
        text=copy_module.text("MODEL_INPUT_TOO_LARGE"),
        state={},
        reason="MODEL_INPUT_TOO_LARGE",
        answer_source="error",
    )
    result = conversation_service._rag_turn_result(answer, 1)
    assert result.kind == "service_error"
    assert result.error_code == "MODEL_INPUT_TOO_LARGE"
    assert result.retryable is False
    assert "服务暂不可用" not in result.text
    assert "单次模型输入上限" in result.text


# ---------------------------------------------------------------- 文案与映射


def test_copy_registers_input_too_large() -> None:
    assert "MODEL_INPUT_TOO_LARGE" in copy_module.SERVICE_ERROR_CODES
    text = copy_module.service_error_text("MODEL_INPUT_TOO_LARGE")
    assert "单次模型输入上限" in text
    assert "服务暂不可用" not in text
    assert "DeepSeek" not in text
    assert copy_module.service_error_is_retryable("MODEL_INPUT_TOO_LARGE") is False

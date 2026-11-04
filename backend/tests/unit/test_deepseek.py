"""T06 G08 模型协议单元测试：真实 httpx 请求对象 + 本地 MockTransport，不发真实网络请求。

断言：官方非流式 Chat Completions 文本协议、请求载荷、错误映射、超时、重定向不跟随、
非法 JSON/截断/缺字段、usage 缺失不编造、密钥不出现在 repr/异常。
"""

from __future__ import annotations

import asyncio
import hashlib
import json

import httpx
import pytest

from mktkb.providers.deepseek import DeepSeekClient
from mktkb.providers.types import (
    CompletionInput,
    DialogueContext,
    ModelEvidence,
    ModelNotConfigured,
    ModelOutputInvalid,
    ModelTimeout,
    ModelUnavailable,
)

SECRET = "sk-test-SECRET-DO-NOT-LEAK-0123456789"
BASE_URL = "https://api.deepseek.example/v1"


def _run(coro):
    return asyncio.run(coro)


def _client(handler) -> DeepSeekClient:
    return DeepSeekClient(
        base_url=BASE_URL,
        model="deepseek-chat",
        api_key=SECRET,
        timeout_seconds=30.0,
        transport=httpx.MockTransport(handler),
    )


def _answer_request() -> CompletionInput:
    return CompletionInput(
        purpose="answer",
        question="城东店的宣传海报在哪里？",
        context=DialogueContext(questions=("城东店的联系人是谁？",), entities={"store": "城东店"}),
        evidence=(
            ModelEvidence(source_id="11111111-1111-1111-1111-111111111111", text="P01 行", fields={"位置": "B区1号货架第二层"}),
        ),
    )


def _ok_content(answer="B区1号货架第二层。", source_ids=("11111111-1111-1111-1111-111111111111",), usage=None):
    payload = {
        "id": "provider-req-1",
        "choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": json.dumps({"answer": answer, "source_ids": list(source_ids)}, ensure_ascii=False)}}],
    }
    if usage is not None:
        payload["usage"] = usage
    return payload


def test_request_uses_official_chat_completions_path_and_payload():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["method"] = request.method
        captured["auth"] = request.headers.get("authorization")
        captured["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, json=_ok_content())

    client = _client(handler)
    output = _run(client.complete(_answer_request(), timeout_seconds=5.0))
    assert captured["method"] == "POST"
    assert captured["url"] == f"{BASE_URL}/chat/completions"
    assert captured["auth"] == f"Bearer {SECRET}"
    body = captured["body"]
    assert body["model"] == "deepseek-chat"
    assert body["stream"] is False
    assert body["temperature"] == 0
    assert [item["role"] for item in body["messages"]] == ["system", "user"]
    user_payload = json.loads(body["messages"][1]["content"])
    assert user_payload["question"] == "城东店的宣传海报在哪里？"
    assert user_payload["entities"] == {"store": "城东店"}
    assert user_payload["evidence"][0]["source_id"] == "11111111-1111-1111-1111-111111111111"
    assert output.text == "B区1号货架第二层。"
    assert output.source_ids == ("11111111-1111-1111-1111-111111111111",)
    # S2-J2-R1：供应商 request_id 不原文进入结果对象，统一不可逆哈希引用。
    assert output.provider_request_id == (
        "sha256:" + hashlib.sha256(b"provider-req-1").hexdigest()[:32]
    )
    assert output.usage is None, "usage 缺失必须为 None，不编造"


def test_usage_is_mapped_when_provider_returns_it():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_ok_content(usage={"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18}),
        )

    output = _run(_client(handler).complete(_answer_request(), timeout_seconds=5.0))
    assert output.usage == {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18}


def test_query_expansion_parses_terms():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content.decode("utf-8"))
        content = json.dumps({"terms": ["宣传海报", "海报"]}, ensure_ascii=False)
        return httpx.Response(200, json={"id": "req-2", "choices": [{"finish_reason": "stop", "message": {"content": content}}]})

    request = CompletionInput(purpose="query_expansion", question="海报放在哪？")
    output = _run(_client(handler).complete(request, timeout_seconds=5.0))
    assert output.query_terms == ("宣传海报", "海报")
    assert output.source_ids == ()
    assert "evidence" not in json.loads(captured["body"]["messages"][1]["content"])


@pytest.mark.parametrize(
    "content",
    [
        "not-json",
        "```json\n{broken\n```",
        json.dumps({"terms": ["x"]}),
        json.dumps({"answer": "", "source_ids": ["a"]}),
        json.dumps({"answer": "答案", "source_ids": "a"}),
        json.dumps({"answer": "答案", "source_ids": [1]}),
    ],
)
def test_invalid_answer_content_maps_model_output_invalid(content):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    with pytest.raises(ModelOutputInvalid):
        _run(_client(handler).complete(_answer_request(), timeout_seconds=5.0))


@pytest.mark.parametrize("status", [400, 401, 403, 404, 429, 500, 502, 503])
def test_error_status_maps_unavailable_without_leaking_provider_body(status):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, text=f"upstream error Authorization: Bearer {SECRET} /srv/secret/path")

    with pytest.raises(ModelUnavailable) as excinfo:
        _run(_client(handler).complete(_answer_request(), timeout_seconds=5.0))
    message = str(excinfo.value)
    assert SECRET not in message
    assert "/srv/secret" not in message
    assert "Bearer" not in message


def test_timeout_maps_model_timeout():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("simulated timeout", request=request)

    with pytest.raises(ModelTimeout):
        _run(_client(handler).complete(_answer_request(), timeout_seconds=5.0))


def test_redirect_is_not_followed_even_with_authorization():
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(302, headers={"Location": "https://evil.example/steal"})

    with pytest.raises(ModelUnavailable):
        _run(_client(handler).complete(_answer_request(), timeout_seconds=5.0))
    assert calls == [f"{BASE_URL}/chat/completions"], "不得跟随携带 Authorization 的重定向"


def test_repr_and_errors_do_not_expose_api_key():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_ok_content())

    client = _client(handler)
    assert SECRET not in repr(client)
    assert SECRET not in str(client.__dict__.get("_client", ""))
    with pytest.raises(ModelNotConfigured):
        DeepSeekClient(base_url="", model="m", api_key=SECRET)
    with pytest.raises(ModelNotConfigured):
        DeepSeekClient(base_url=BASE_URL, model="", api_key=SECRET)
    with pytest.raises(ModelNotConfigured):
        DeepSeekClient(base_url=BASE_URL, model="m", api_key="")


def test_non_200_success_codes_and_bad_shape():
    def bad_shape(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": []})

    with pytest.raises(ModelOutputInvalid):
        _run(_client(bad_shape).complete(_answer_request(), timeout_seconds=5.0))

    def no_message(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"text": "x"}]})

    with pytest.raises(ModelOutputInvalid):
        _run(_client(no_message).complete(_answer_request(), timeout_seconds=5.0))

    def not_json(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>gateway</html>")

    with pytest.raises(ModelOutputInvalid):
        _run(_client(not_json).complete(_answer_request(), timeout_seconds=5.0))


# ---------------------------------------------------------------- R1：完成状态校验


def _payload_with_finish_reason(finish_reason="length", *, present=True):
    """上游 200 JSON：content 恰为合法 JSON，只改变完成状态。"""
    choice = {
        "message": {
            "role": "assistant",
            "content": json.dumps(
                {"answer": "部分内容", "source_ids": ["11111111-1111-1111-1111-111111111111"]},
                ensure_ascii=False,
            ),
        }
    }
    if present:
        choice["finish_reason"] = finish_reason
    return {"id": "provider-req-truncated", "choices": [choice]}


def test_truncated_completion_with_valid_json_is_rejected():
    """PM06-03：finish_reason=length 时残留的合法 JSON 也不得当作完整回答。"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_payload_with_finish_reason("length"))

    with pytest.raises(ModelOutputInvalid):
        _run(_client(handler).complete(_answer_request(), timeout_seconds=5.0))


@pytest.mark.parametrize(
    "finish_reason", ["content_filter", "tool_calls", "insufficient_system_resource", "", None]
)
def test_abnormal_or_empty_finish_reason_is_rejected(finish_reason):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_payload_with_finish_reason(finish_reason))

    with pytest.raises(ModelOutputInvalid):
        _run(_client(handler).complete(_answer_request(), timeout_seconds=5.0))


def test_missing_finish_reason_is_rejected():
    """不完整完成状态（缺字段）同样不得当成功。"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_payload_with_finish_reason("stop", present=False))

    with pytest.raises(ModelOutputInvalid):
        _run(_client(handler).complete(_answer_request(), timeout_seconds=5.0))


def test_complete_finish_reason_stop_is_accepted_with_usage():
    """正确对照：明确完整结束的文本完成仍通过，并保留原状态码/usage 语义。"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_ok_content(usage={"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7}),
        )

    output = _run(_client(handler).complete(_answer_request(), timeout_seconds=5.0))
    assert output.text == "B区1号货架第二层。"
    assert output.source_ids == ("11111111-1111-1111-1111-111111111111",)
    assert output.usage == {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7}

"""T104：模型异常按真实原因分类透传（ERR-07 产品侧）的单元测试。

不建库、不联网、不构造真实 provider。覆盖七类原因：

- 配置（``ModelNotConfigured`` / 网关未注入）→ 不可重试；
- 预算·授权（``ModelBudgetRefused``）→ 不可重试；
- provider（``ModelUnavailable`` 及其子类）→ 可重试；
- 超时（``ModelTimeout`` / ``asyncio.TimeoutError``）→ 可重试；
- 输出校验（``ModelOutputInvalid``）→ 可重试；
- 内部（本地校验/编排的非预期异常，``QA_INTERNAL_ERROR``）→ 不可重试（理由见 report）；
- 未知（调用期无法归类的异常，``MODEL_CALL_FAILED``）→ 可重试。

同时断言每类文案都套用 ERR-07 正面模板：这是服务调用失败、不是资料中没有答案 +
可否重试 + 不会因重试重复落库；并逐类证明非 provider 原因不再报 ``MODEL_UNAVAILABLE``。
"""

from __future__ import annotations

import asyncio

import pytest

from mktkb.conversations import service
from mktkb.providers.types import (
    CompletionInput,
    CompletionOutput,
    ModelBudgetRefused,
    ModelError,
    ModelNotConfigured,
    ModelOutputInvalid,
    ModelTimeout,
    ModelUnavailable,
)

_PAYLOAD = CompletionInput(purpose="answer", question="q")

#: ERR-07 正面模板的三个语义要素（逐字）。
ERR07_NOT_MISSING = "这是服务调用失败，不是资料中没有答案"
ERR07_RETRY_HINT = "可稍后重新提问"
ERR07_NO_RETRY_HINT = "重试不会自行恢复"
ERR07_NO_DUPLICATE = "服务端不会因重试而重复保存同一条回答。"

#: 七类原因 →（错误码, 可重试）。矩阵即验收口径。
MATRIX: dict[str, tuple[str, bool]] = {
    "config": ("MODEL_NOT_CONFIGURED", False),
    "budget": ("MODEL_BUDGET_REFUSED", False),
    "provider": ("MODEL_UNAVAILABLE", True),
    "timeout": ("MODEL_TIMEOUT", True),
    "output_invalid": ("MODEL_OUTPUT_INVALID", True),
    "unknown": ("MODEL_CALL_FAILED", True),
    "internal": ("QA_INTERNAL_ERROR", False),
}


class _Gateway:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.calls = 0
        self.error = error

    async def complete(self, request: CompletionInput, *, timeout_seconds: float) -> CompletionOutput:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return CompletionOutput(text="ok", source_ids=("s",))


def _run(coro):
    return asyncio.run(coro)


def _error_for(code: str) -> ModelError:
    return {
        "MODEL_NOT_CONFIGURED": ModelNotConfigured,
        "MODEL_BUDGET_REFUSED": lambda: ModelBudgetRefused("预算/授权闸门拒绝"),
        "MODEL_UNAVAILABLE": lambda: ModelUnavailable("t104"),
        "MODEL_TIMEOUT": lambda: ModelTimeout("t104"),
        "MODEL_OUTPUT_INVALID": lambda: ModelOutputInvalid("t104"),
        "MODEL_CALL_FAILED": lambda: service.ModelCallFailed("RuntimeError"),
    }[code]()


# ---------------------------------------------------------------- 调用层分类


def test_missing_gateway_raises_not_configured() -> None:
    with pytest.raises(ModelNotConfigured) as excinfo:
        _run(service._call_model(None, _PAYLOAD, deadline=20.0))
    assert excinfo.value.code == MATRIX["config"][0]
    assert excinfo.value.retryable is False


@pytest.mark.parametrize(
    ("error", "expected_code", "expected_retryable"),
    [
        (ModelBudgetRefused("预算/授权闸门拒绝"), "MODEL_BUDGET_REFUSED", False),
        (ModelTimeout("t104"), "MODEL_TIMEOUT", True),
        (ModelUnavailable("t104"), "MODEL_UNAVAILABLE", True),
        # 异常自带 retryable=False；产品映射按“输出校验可重试”覆盖（见矩阵用例）。
        (ModelOutputInvalid("t104"), "MODEL_OUTPUT_INVALID", False),
    ],
)
def test_known_gateway_errors_keep_their_code(error, expected_code, expected_retryable, monkeypatch) -> None:
    """网关已归类的稳定错误原样透传（不重新包装），保持既有码值。"""
    monkeypatch.setattr(service, "monotonic", lambda: 10.0)
    with pytest.raises(type(error)) as excinfo:
        _run(service._call_model(_Gateway(error=error), _PAYLOAD, deadline=20.0))
    assert excinfo.value.code == expected_code
    assert bool(excinfo.value.retryable) is expected_retryable


def test_asyncio_timeout_maps_to_model_timeout(monkeypatch) -> None:
    monkeypatch.setattr(service, "monotonic", lambda: 10.0)
    with pytest.raises(ModelTimeout) as excinfo:
        _run(service._call_model(_Gateway(error=asyncio.TimeoutError()), _PAYLOAD, deadline=20.0))
    assert excinfo.value.code == MATRIX["timeout"][0]
    assert excinfo.value.retryable is True


def test_unclassified_exception_maps_to_unknown_not_provider(monkeypatch) -> None:
    """T104 核心：任意异常不再一律包装成 MODEL_UNAVAILABLE。"""
    monkeypatch.setattr(service, "monotonic", lambda: 10.0)
    with pytest.raises(service.ModelCallFailed) as excinfo:
        _run(service._call_model(_Gateway(error=RuntimeError("local gateway boom")), _PAYLOAD, deadline=20.0))
    error = excinfo.value
    assert error.code == MATRIX["unknown"][0]
    assert error.retryable is True
    assert not isinstance(error, ModelUnavailable)
    assert isinstance(error.__cause__, RuntimeError)


# ---------------------------------------------------------------- 结果映射矩阵


def _result_for(reason: str):
    if reason == "internal":
        return service._internal_failure_result(0)
    return service._model_failure_result(_error_for(MATRIX[reason][0]), 0)


@pytest.mark.parametrize("reason", sorted(MATRIX))
def test_classification_matrix_code_and_retryability(reason) -> None:
    code, retryable = MATRIX[reason]
    result = _result_for(reason)
    assert result.kind == "service_error"
    assert result.error_code == code
    assert result.retryable is retryable
    assert result.text == service._model_error_text(code)


def test_non_provider_causes_never_report_model_unavailable() -> None:
    """逐类证明：配置/预算/超时/输出校验/内部/未知都不再是 MODEL_UNAVAILABLE。"""
    for reason in ("config", "budget", "timeout", "output_invalid", "internal", "unknown"):
        assert _result_for(reason).error_code != "MODEL_UNAVAILABLE", reason


def test_unknown_model_error_subclass_keeps_gateway_code() -> None:
    """未登记的子类保留网关自带码值（网关联约），文案仍走 ERR-07 模板。"""

    class _VendorSpecific(ModelError):
        code = "MODEL_VENDOR_SPECIFIC"
        retryable = False

    result = service._model_failure_result(_VendorSpecific("x"), 0)
    assert result.error_code == "MODEL_VENDOR_SPECIFIC"
    assert result.retryable is False
    assert ERR07_NOT_MISSING in result.text and ERR07_NO_DUPLICATE in result.text


def test_provider_subclass_keeps_custom_gateway_code() -> None:
    """provider 族子类的既有自定义码不得被压回 MODEL_UNAVAILABLE（网关契约）。"""

    class _PostSendDenied(ModelUnavailable):
        code = "MODEL_POST_SEND_AUTH_DENIED"

    result = service._model_failure_result(_PostSendDenied("x"), 0)
    assert result.error_code == "MODEL_POST_SEND_AUTH_DENIED"
    assert result.retryable is True
    assert "未发出" in result.text


def test_model_failure_result_carries_no_sources_or_candidates() -> None:
    result = service._model_failure_result(ModelUnavailable("x"), 3)
    assert result.source_ids == ()
    assert result.candidates == [] and result.conflicts == []
    assert result.missing_fields == [] and result.pagination is None


# ---------------------------------------------------------------- 文案模板


@pytest.mark.parametrize("reason", sorted(MATRIX))
def test_every_reason_text_uses_err07_template(reason) -> None:
    code, retryable = MATRIX[reason]
    text = service._model_error_text(code)
    assert ERR07_NOT_MISSING in text, code
    assert ERR07_NO_DUPLICATE in text, code
    if retryable:
        assert ERR07_RETRY_HINT in text, code
        assert ERR07_NO_RETRY_HINT not in text, code
    else:
        assert ERR07_NO_RETRY_HINT in text, code
        assert ERR07_RETRY_HINT not in text, code


def test_provider_text_keeps_err07_positive_sample_semantics() -> None:
    text = service._model_error_text("MODEL_UNAVAILABLE")
    assert text.startswith("模型服务暂不可用")
    assert ERR07_NOT_MISSING in text
    assert ERR07_RETRY_HINT in text
    assert ERR07_NO_DUPLICATE in text


def test_budget_text_names_authorization_and_zero_send() -> None:
    text = service._model_error_text("MODEL_BUDGET_REFUSED")
    assert "预算" in text and "授权" in text and "未发送请求" in text
    # 预算/授权是管理员可修复的问题，不是“服务不可用”；重试无用要说清。
    assert ERR07_NO_RETRY_HINT in text
    assert "暂不可用" not in text


def test_unknown_code_falls_back_to_same_template() -> None:
    text = service._model_error_text("SOME_FUTURE_CODE")
    assert ERR07_NOT_MISSING in text and ERR07_NO_DUPLICATE in text
    assert "原因未能归类" in text


def test_internal_result_does_not_echo_exception_text() -> None:
    """内部异常映射只回稳定文案，异常消息不出现在响应文本里（T09 脱敏口径）。"""
    result = service._internal_failure_result(0)
    assert "RuntimeError" not in result.text
    assert "Traceback" not in result.text

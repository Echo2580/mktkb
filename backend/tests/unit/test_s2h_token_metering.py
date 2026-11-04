"""S2-H-R1 定向测试：官方 tokenizer artifact 离线计量与产品 chat 请求体。

需要原 H 只读复用的 vendor（不下载、不写回）：
- ``MKTKB_TOKENIZER_PATH`` / ``MKTKB_TOKENIZER_SHA256`` 指向 artifact；
- 缺失时跳过（不在缺依赖的环境里伪造通过）。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from mktkb.providers.deepseek import DeepSeekClient
from mktkb.providers.token_metering import (
    BOS_TOKEN,
    DeepSeekPromptMeter,
    TokenMeterError,
    load_meter_from_env,
)
from mktkb.providers.types import CompletionInput, DialogueContext, ModelEvidence

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_VENDOR = (
    ROOT
    / "docs"
    / "evidence"
    / "LOCAL-R1-20261101"
    / "S2-DEV"
    / "H"
    / "vendor"
    / "py"
)
DEFAULT_ARTIFACT = (
    ROOT
    / "docs"
    / "evidence"
    / "LOCAL-R1-20261101"
    / "S2-DEV"
    / "H"
    / "vendor"
    / "tokenizer_deepseek_v4"
    / "deepseek_v4_tokenizer"
    / "tokenizer.json"
)
DEFAULT_SHA = "89085f12ef79460ac5f66d1119325ddfc694b4ab209d80bbd81d35f081dc9614"


def _artifact() -> tuple[Path, str]:
    path = Path(os.environ.get("MKTKB_TOKENIZER_PATH") or DEFAULT_ARTIFACT)
    sha = os.environ.get("MKTKB_TOKENIZER_SHA256") or DEFAULT_SHA
    if not path.is_file():
        pytest.skip(f"官方 tokenizer artifact 不可用：{path}")
    vendor = Path(os.environ.get("MKTKB_TOKENIZER_VENDOR") or DEFAULT_VENDOR)
    if vendor.is_dir() and str(vendor) not in sys.path:
        sys.path.insert(0, str(vendor))
    try:
        import tokenizers  # noqa: F401
    except ImportError:  # pragma: no cover - 依赖缺失时显式跳过
        pytest.skip("隔离 tokenizers 依赖不可用")
    return path, sha


@pytest.fixture(scope="module")
def meter() -> DeepSeekPromptMeter:
    path, sha = _artifact()
    return DeepSeekPromptMeter.from_files(path, expected_sha256=sha)


def test_artifact_sha_is_verified(meter: DeepSeekPromptMeter):
    _path, sha = _artifact()
    assert meter.tokenizer_sha256 == sha
    assert len(meter.template_sha256) == 64


def test_wrong_sha_is_refused():
    path, _sha = _artifact()
    with pytest.raises(TokenMeterError, match="sha256"):
        DeepSeekPromptMeter.from_files(path, expected_sha256="0" * 64)


def test_missing_artifact_fails_closed():
    with pytest.raises(TokenMeterError):
        DeepSeekPromptMeter.from_files(ROOT / "no-such-tokenizer.json", expected_sha256="0" * 64)


def test_meter_from_env_require_flag(monkeypatch):
    monkeypatch.delenv("MKTKB_TOKENIZER_PATH", raising=False)
    monkeypatch.delenv("MKTKB_TOKENIZER_SHA256", raising=False)
    assert load_meter_from_env(require=False) is None
    with pytest.raises(TokenMeterError):
        load_meter_from_env(require=True)


def test_template_without_markers_is_refused(meter: DeepSeekPromptMeter):
    with pytest.raises(TokenMeterError, match="协议标记"):
        DeepSeekPromptMeter(
            tokenizer=meter._tokenizer,  # noqa: SLF001 - 复用已加载 artifact
            tokenizer_sha256=meter.tokenizer_sha256,
            template="{% for m in messages %}{{ m['content'] }}{% endfor %}",
            template_sha256="0" * 64,
        )


@pytest.mark.parametrize(
    "text",
    [
        "城东店的宣传海报在哪里？",
        "Where is the poster?",
        "📍" * 40,
        "a\tb\nc\r\n\x00\x1b",
        "e\u0301" * 30,
        "<｜begin▁of▁sentence｜><｜User｜><｜Assistant｜>",
        " " * 100,
    ],
)
def test_byte_bound_holds_for_adversarial_texts(meter: DeepSeekPromptMeter, text: str):
    bound = meter.measure("系统提示", text)
    assert bound.exact_tokens <= bound.rendered_bytes
    assert bound.byte_upper_tokens == bound.rendered_bytes


def test_render_includes_protocol_markers(meter: DeepSeekPromptMeter):
    rendered = meter.render("S", "U")
    assert rendered.startswith(BOS_TOKEN)
    assert rendered == f"{BOS_TOKEN}S<｜User｜>U<｜Assistant｜>"


def _payload_request(text: str) -> CompletionInput:
    return CompletionInput(
        purpose="answer",
        question="城东店的宣传海报在哪里？",
        context=DialogueContext(questions=("上一问",), entities={"store": "城东店"}),
        evidence=(ModelEvidence(source_id="c1", text=text, fields={"门店": "城东店"}),),
    )


def test_chat_payload_sends_thinking_disabled_and_max_tokens(meter: DeepSeekPromptMeter):
    client = DeepSeekClient(
        base_url="https://api.deepseek.com",
        model="deepseek-flash",
        api_key="not-a-real-key",
        max_output_tokens=800,
        prompt_meter=meter,
    )
    payload = client._payload(_payload_request("B区1号货架第二层"))  # noqa: SLF001 - 只断言请求体
    assert payload["thinking"] == {"type": "disabled"}
    assert payload["max_tokens"] == 800
    assert payload["stream"] is False
    assert payload["temperature"] == 0
    assert payload["model"] == "deepseek-flash"


def test_request_upper_bytes_has_no_arbitrary_constant(meter: DeepSeekPromptMeter):
    client = DeepSeekClient(
        base_url="https://api.deepseek.com",
        model="deepseek-flash",
        api_key="not-a-real-key",
        max_output_tokens=800,
        prompt_meter=meter,
    )
    request = _payload_request("B区1号货架第二层")
    payload = client._payload(request)  # noqa: SLF001
    expected = len(payload["messages"][0]["content"].encode("utf-8")) + len(
        payload["messages"][1]["content"].encode("utf-8")
    )
    assert client.request_upper_bytes(request) == expected


def test_prompt_token_upper_bound_matches_meter(meter: DeepSeekPromptMeter):
    client = DeepSeekClient(
        base_url="https://api.deepseek.com",
        model="deepseek-flash",
        api_key="not-a-real-key",
        max_output_tokens=800,
        prompt_meter=meter,
    )
    request = _payload_request("B区1号货架第二层")
    payload = client._payload(request)  # noqa: SLF001
    expected = meter.measure(payload["messages"][0]["content"], payload["messages"][1]["content"])
    assert client.prompt_token_upper_bound(request) == expected.byte_upper_tokens


def test_client_without_meter_returns_none_not_heuristic():
    client = DeepSeekClient(
        base_url="https://api.deepseek.com",
        model="deepseek-flash",
        api_key="not-a-real-key",
        max_output_tokens=800,
    )
    assert client.prompt_token_upper_bound(_payload_request("x")) is None


def test_payload_is_json_serialisable(meter: DeepSeekPromptMeter):
    client = DeepSeekClient(
        base_url="https://api.deepseek.com",
        model="deepseek-flash",
        api_key="not-a-real-key",
        max_output_tokens=800,
        prompt_meter=meter,
    )
    payload = client._payload(_payload_request("B区1号货架第二层"))  # noqa: SLF001
    assert json.loads(json.dumps(payload, ensure_ascii=False))["thinking"] == {"type": "disabled"}

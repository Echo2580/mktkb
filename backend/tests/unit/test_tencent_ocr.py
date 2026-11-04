"""T07 腾讯云 OCR 协议单元检查：真实 httpx 请求对象 + 本地 MockTransport。

不发真实网络请求、不读取真实密钥；断言官方 Action/Version/签名结构、请求体、
文本/表格响应与 RequestId、confidence 缺失为 None、错误映射与脱敏。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import datetime, timezone

import httpx
import pytest

from mktkb.providers.tencent_ocr import (
    CONTENT_TYPE,
    GENERAL_ACTION,
    TABLE_ACTION,
    TENCENT_OCR_ENDPOINT,
    TENCENT_OCR_HOST,
    TENCENT_OCR_VERSION,
    TencentOCRClient,
)
from mktkb.providers.types import (
    OCRAuthFailed,
    OCRInput,
    OCRInvalidInput,
    OCRInvalidOutput,
    OCRNotConfigured,
    OCRQuotaUnavailable,
    OCRRateLimited,
    OCRTimeout,
    OCRUnavailable,
)

SECRET_ID = "AKID-T07-TEST-SECRET-ID"
SECRET_KEY = "T07-TEST-SECRET-KEY-DO-NOT-LEAK"
TIMESTAMP = 1_700_000_000


def _client(handler, **kwargs) -> TencentOCRClient:
    return TencentOCRClient(
        secret_id=SECRET_ID,
        secret_key=SECRET_KEY,
        region="ap-guangzhou",
        endpoint=TENCENT_OCR_ENDPOINT,
        timeout_seconds=10.0,
        transport=httpx.MockTransport(handler),
        clock=lambda: TIMESTAMP,
        **kwargs,
    )


def _input(content: bytes = b"\x89PNG\r\n\x1a\nfake-image-bytes", bbox=None) -> OCRInput:
    return OCRInput(content=content, mime_type="image/png", page=2, bbox=bbox)


def _expected_authorization(payload: str) -> str:
    date = datetime.fromtimestamp(TIMESTAMP, timezone.utc).strftime("%Y-%m-%d")
    canonical_headers = (
        f"content-type:{CONTENT_TYPE}\nhost:{TENCENT_OCR_HOST}\nx-tc-action:generalaccurateocr\n"
    )
    signed_headers = "content-type;host;x-tc-action"
    hashed_payload = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    canonical_request = "\n".join(["POST", "/", "", canonical_headers, signed_headers, hashed_payload])
    credential_scope = f"{date}/ocr/tc3_request"
    string_to_sign = "\n".join(
        [
            "TC3-HMAC-SHA256",
            str(TIMESTAMP),
            credential_scope,
            hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
        ]
    )

    def sign(key: bytes, message: str) -> bytes:
        return hmac.new(key, message.encode("utf-8"), hashlib.sha256).digest()

    secret_date = sign(("TC3" + SECRET_KEY).encode("utf-8"), date)
    secret_service = sign(secret_date, "ocr")
    secret_signing = sign(secret_service, "tc3_request")
    signature = hmac.new(secret_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    return (
        "TC3-HMAC-SHA256 "
        f"Credential={SECRET_ID}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )


def test_general_request_uses_official_action_signature_and_body():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["url"] = str(request.url)
        captured["headers"] = {key.lower(): value for key, value in request.headers.items()}
        captured["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json={
                "Response": {
                    "TextDetections": [
                        {
                            "DetectedText": "第一行",
                            "Confidence": 99,
                            "Polygon": [
                                {"X": 10, "Y": 20},
                                {"X": 50, "Y": 20},
                                {"X": 50, "Y": 40},
                                {"X": 10, "Y": 40},
                            ],
                        },
                        {
                            "DetectedText": "第二行",
                            "Confidence": 97,
                            "Polygon": [
                                {"X": 12, "Y": 50},
                                {"X": 60, "Y": 50},
                                {"X": 60, "Y": 70},
                                {"X": 12, "Y": 70},
                            ],
                        },
                    ],
                    "RequestId": "req-general-1",
                }
            },
        )

    output = _client(handler).recognize(_input(bbox=(100.0, 200.0, 300.0, 400.0)), mode="text")
    assert captured["method"] == "POST"
    assert captured["url"] == TENCENT_OCR_ENDPOINT
    headers = captured["headers"]
    assert headers["x-tc-action"] == GENERAL_ACTION
    assert headers["x-tc-version"] == TENCENT_OCR_VERSION
    assert headers["x-tc-region"] == "ap-guangzhou"
    assert headers["content-type"] == CONTENT_TYPE
    assert headers["host"] == TENCENT_OCR_HOST
    body = captured["body"]
    assert set(body) == {"ImageBase64"}
    assert base64.b64decode(body["ImageBase64"]) == _input().content
    assert "ImageUrl" not in body, "客户端不得传任意目标 URL"
    assert headers["authorization"] == _expected_authorization(
        json.dumps(body, ensure_ascii=False, separators=(",", ":"))
    )
    assert output.text == "第一行\n第二行"
    # S2-J2-R1：供应商 RequestId 不原文进入结果对象，统一不可逆哈希引用。
    assert output.provider_request_id == (
        "sha256:" + hashlib.sha256(b"req-general-1").hexdigest()[:32]
    )
    assert output.confidence == 97.0
    assert output.table_rows == ()
    assert output.regions[0]["bbox"] == [110.0, 220.0, 150.0, 240.0], "bbox 必须回映源坐标"
    assert output.regions[1]["bbox"] == [112.0, 250.0, 160.0, 270.0]


def test_table_response_builds_rows_cells_and_request_id():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["action"] = request.headers["x-tc-action"]
        captured["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json={
                "Response": {
                    "TableDetections": [
                        {
                            "Cells": [
                                {"RowTl": 0, "RowBr": 1, "ColTl": 0, "ColBr": 1, "Text": "门店", "Confidence": 99},
                                {"RowTl": 0, "RowBr": 1, "ColTl": 1, "ColBr": 2, "Text": "位置", "Confidence": 98},
                                {"RowTl": 1, "RowBr": 2, "ColTl": 0, "ColBr": 1, "Text": "城东店", "Confidence": 95},
                                {"RowTl": 1, "RowBr": 2, "ColTl": 1, "ColBr": 2, "Text": "B区1号", "Confidence": 96},
                            ]
                        }
                    ],
                    "RequestId": "req-table-1",
                }
            },
        )

    output = _client(handler).recognize(_input(), mode="table")
    assert captured["action"] == TABLE_ACTION
    assert output.table_rows == (("门店", "位置"), ("城东店", "B区1号"))
    assert output.provider_request_id == (
        "sha256:" + hashlib.sha256(b"req-table-1").hexdigest()[:32]
    )
    assert output.confidence == 95.0
    assert output.text == "门店 | 位置\n城东店 | B区1号"


def test_missing_confidence_is_null_and_empty_text_is_not_invented():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"Response": {"TextDetections": [{"DetectedText": "无置信度", "Polygon": []}], "RequestId": "r1"}},
        )

    output = _client(handler).recognize(_input(), mode="text")
    assert output.confidence is None
    assert output.regions[0]["text"] == "无置信度"
    assert "confidence" not in output.regions[0]

    def empty(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"Response": {"TextDetections": [], "RequestId": "r2"}})

    output = _client(empty).recognize(_input(), mode="text")
    assert output.text == "" and output.table_rows == ()


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("FailedOperation.NoFreeAmount", OCRQuotaUnavailable),
        ("ResourceUnavailable.InArrears", OCRQuotaUnavailable),
        ("LimitExceeded", OCRQuotaUnavailable),
        ("RequestLimitExceeded", OCRRateLimited),
        ("AuthFailure.SignatureFailure", OCRAuthFailed),
        ("InvalidParameter.ImageSizeTooLarge", OCRInvalidInput),
        ("FailedOperation.Unknown", OCRUnavailable),
    ],
)
def test_provider_error_codes_map_to_stable_errors(code, expected):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"Response": {"Error": {"Code": code, "Message": "provider message"}, "RequestId": "err-1"}},
        )

    with pytest.raises(expected) as excinfo:
        _client(handler).recognize(_input(), mode="text")
    assert excinfo.value.provider_request_id == (
        "sha256:" + hashlib.sha256(b"err-1").hexdigest()[:32]
    )
    assert SECRET_KEY not in str(excinfo.value)


def test_http_429_500_redirect_and_timeout_are_distinct():
    def rate(request):
        return httpx.Response(429, json={"Response": {"RequestId": "r429"}})

    with pytest.raises(OCRRateLimited) as limited:
        _client(rate).recognize(_input(), mode="text")
    assert limited.value.retryable is True

    def server_error(request):
        return httpx.Response(500, text="provider body must not leak")

    with pytest.raises(OCRUnavailable) as unavailable:
        _client(server_error).recognize(_input(), mode="text")
    assert unavailable.value.retryable is True

    def redirect(request):
        return httpx.Response(302, headers={"Location": "https://evil.example"})

    with pytest.raises(OCRUnavailable):
        _client(redirect).recognize(_input(), mode="text")

    def timeout(request):
        raise httpx.ReadTimeout("simulated")

    with pytest.raises(OCRTimeout) as timed:
        _client(timeout).recognize(_input(), mode="text")
    assert timed.value.retryable is True


def test_invalid_json_and_malformed_table_are_output_invalid():
    with pytest.raises(OCRInvalidOutput):
        _client(lambda request: httpx.Response(200, content=b"not-json")).recognize(_input(), mode="text")

    def malformed(request):
        return httpx.Response(
            200,
            json={
                "Response": {
                    "TableDetections": [{"Cells": [{"RowTl": 0, "RowBr": 0, "ColTl": 0, "ColBr": 1, "Text": "x"}]}],
                    "RequestId": "bad-table",
                }
            },
        )

    with pytest.raises(OCRInvalidOutput):
        _client(malformed).recognize(_input(), mode="table")


def test_oversized_content_is_rejected_before_request():
    called = {"value": False}

    def handler(request):
        called["value"] = True
        return httpx.Response(200, json={"Response": {"TextDetections": []}})

    oversized = b"x" * (8 * 1024 * 1024)
    with pytest.raises(OCRInvalidInput):
        _client(handler).recognize(_input(content=oversized), mode="text")
    assert called["value"] is False, "超过供应商体积上限不得先发请求"


def test_endpoint_restriction_and_secret_redaction():
    with pytest.raises(OCRNotConfigured):
        TencentOCRClient(secret_id=SECRET_ID, secret_key=SECRET_KEY, endpoint="https://evil.example/ocr")
    with pytest.raises(OCRNotConfigured):
        TencentOCRClient(secret_id=SECRET_ID, secret_key=SECRET_KEY, endpoint="http://ocr.tencentcloudapi.com")

    client = _client(lambda request: httpx.Response(200, json={"Response": {"TextDetections": []}}))
    assert SECRET_ID not in repr(client)
    assert SECRET_KEY not in repr(client)

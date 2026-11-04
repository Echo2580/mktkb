"""T07 腾讯云 OCR 官方协议适配（只使用既有 httpx 0.28.1 与标准库，不安装 SDK）。

依据（2026-10-29 核对官方文档）：
- 通用文字识别（高精度版）：https://cloud.tencent.com/document/product/866/34937
  Action=GeneralAccurateOCR、Version=2018-11-19、请求域名 ocr.tencentcloudapi.com；
  ImageBase64 经 Base64 后不超过 10M；返回 TextDetections（DetectedText/Confidence/Polygon）与 RequestId。
- 表格识别（V3）：https://cloud.tencent.com/document/api/866/86721
  Action=RecognizeTableAccurateOCR、Version=2018-11-19；返回 TableDetections（Cells 的
  RowTl/RowBr/ColTl/ColBr/Text/Confidence）与 RequestId；默认接口频率 2 次/秒。
- 签名方法 v3：https://cloud.tencent.com/document/api/1552/73159
  TC3-HMAC-SHA256；SignedHeaders=content-type;host;x-tc-action。

边界：
- 目的地址只来自构造参数（配置层校验为官方域名），``recognize`` 不接受 URL；
- 只发送本地经边界检查的图片字节，不发送本地路径/文件名；
- 不记录 SecretId/SecretKey/Authorization/图片内容；错误只映射稳定 OCR_* 代码；
- 服务未返回 Confidence 时 confidence=None，不编造识别准确率。
- 表格识别对无法定位的检测区域返回 ``-1`` 哨兵坐标（T09-D6 R2 真实响应实测）。哨兵不是坐标：
  空单元格直接忽略；带文字的只保留文字，不进入表格行、不生成 bbox，绝不伪造 ``0`` 坐标。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from datetime import datetime, timezone
from typing import Any, Callable, Mapping
from urllib.parse import urlsplit

import httpx

from ..rag.controlled_usage import safe_request_id
from .types import (
    OCRInput,
    OCRInvalidInput,
    OCRInvalidOutput,
    OCRMode,
    OCRNotConfigured,
    OCRPageResult,
    OCRAuthFailed,
    OCRQuotaUnavailable,
    OCRRateLimited,
    OCRTimeout,
    OCRUnavailable,
)

TENCENT_OCR_HOST = "ocr.tencentcloudapi.com"
TENCENT_OCR_ENDPOINT = f"https://{TENCENT_OCR_HOST}"
TENCENT_OCR_VERSION = "2018-11-19"
GENERAL_ACTION = "GeneralAccurateOCR"
TABLE_ACTION = "RecognizeTableAccurateOCR"
MAX_BASE64_BYTES = 10 * 1024 * 1024
MIN_IMAGE_SIDE = 50
MAX_IMAGE_SIDE = 10000
MAX_TABLE_ROWS = 2000
MAX_TABLE_COLUMNS = 200
# 腾讯云表格识别对无法定位的检测区域返回 -1 哨兵；它不是合法坐标，也不得当作 0 使用。
TABLE_COORD_MISSING = -1
CONTENT_TYPE = "application/json; charset=utf-8"


class TencentOCRClient:
    """同步 OCR 客户端；测试通过 ``httpx.MockTransport`` 注入本地响应，不发真实请求。"""

    def __init__(
        self,
        *,
        secret_id: str,
        secret_key: str,
        region: str = "ap-guangzhou",
        endpoint: str = TENCENT_OCR_ENDPOINT,
        timeout_seconds: float = 30.0,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if not secret_id or not secret_key:
            raise OCRNotConfigured("OCR 凭据未配置")
        parts = urlsplit(endpoint or "")
        if (
            parts.scheme != "https"
            or parts.hostname != TENCENT_OCR_HOST
            or parts.path not in {"", "/"}
            or parts.query
            or parts.fragment
            or parts.username
            or parts.password
        ):
            raise OCRNotConfigured("OCR 地址必须是腾讯云官方 HTTPS 域名")
        if not 0 < timeout_seconds <= 60:
            raise OCRNotConfigured("OCR 超时配置不合法")
        self._secret_id = secret_id
        self._secret_key = secret_key
        self._region = region.strip()
        self._endpoint = TENCENT_OCR_ENDPOINT
        self._timeout_seconds = float(timeout_seconds)
        self._transport = transport
        self._clock = clock
        self._client: httpx.Client | None = None

    def __repr__(self) -> str:  # 不包含 SecretId/SecretKey
        return f"TencentOCRClient(region={self._region!r}, endpoint={self._endpoint!r})"

    def close(self) -> None:
        client, self._client = self._client, None
        if client is not None:
            client.close()

    def _client_or_create(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(
                follow_redirects=False,
                transport=self._transport,
                timeout=self._timeout_seconds,
            )
        return self._client

    def recognize(self, page: OCRInput, *, mode: OCRMode) -> OCRPageResult:
        if mode not in {"text", "table"}:
            raise OCRInvalidInput("不支持的识别模式")
        if not page.content:
            raise OCRInvalidInput("图片内容为空")
        if len(page.content) > MAX_BASE64_BYTES:
            raise OCRInvalidInput("图片编码前已超过供应商体积上限")
        encoded = base64.b64encode(page.content)
        if len(encoded) > MAX_BASE64_BYTES:
            raise OCRInvalidInput("图片 Base64 后超过供应商 10M 上限")

        action = GENERAL_ACTION if mode == "text" else TABLE_ACTION
        payload = json.dumps({"ImageBase64": encoded.decode("ascii")}, ensure_ascii=False, separators=(",", ":"))
        timestamp = int(self._clock())
        headers = self._headers(action=action, payload=payload, timestamp=timestamp)
        try:
            response = self._client_or_create().post(
                self._endpoint,
                content=payload.encode("utf-8"),
                headers=headers,
                timeout=self._timeout_seconds,
            )
        except httpx.TimeoutException as exc:
            raise OCRTimeout("OCR 请求超时") from exc
        except httpx.HTTPError as exc:
            raise OCRUnavailable(type(exc).__name__) from exc

        status = response.status_code
        if status == 429:
            raise OCRRateLimited("OCR 接口限流", provider_request_id=_request_id_safe(response))
        if 300 <= status < 400:
            raise OCRUnavailable("provider_redirect", provider_request_id=_request_id_safe(response))
        if status >= 500:
            raise OCRUnavailable(f"provider_status_{status}", provider_request_id=_request_id_safe(response))
        if status != 200:
            _raise_provider_error(response)
        try:
            data = response.json()
        except ValueError as exc:
            raise OCRInvalidOutput("OCR 响应不是 JSON") from exc
        return self._parse_response(data, page=page, mode=mode)

    # ---------------------------------------------------------------- 签名与请求

    def _headers(self, *, action: str, payload: str, timestamp: int) -> dict[str, str]:
        date = datetime.fromtimestamp(timestamp, timezone.utc).strftime("%Y-%m-%d")
        canonical_headers = (
            f"content-type:{CONTENT_TYPE}\n"
            f"host:{TENCENT_OCR_HOST}\n"
            f"x-tc-action:{action.lower()}\n"
        )
        signed_headers = "content-type;host;x-tc-action"
        hashed_payload = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        canonical_request = "\n".join(
            ["POST", "/", "", canonical_headers, signed_headers, hashed_payload]
        )
        credential_scope = f"{date}/ocr/tc3_request"
        string_to_sign = "\n".join(
            [
                "TC3-HMAC-SHA256",
                str(timestamp),
                credential_scope,
                hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
            ]
        )
        secret_date = _hmac_sha256(("TC3" + self._secret_key).encode("utf-8"), date)
        secret_service = _hmac_sha256(secret_date, "ocr")
        secret_signing = _hmac_sha256(secret_service, "tc3_request")
        signature = _hmac_sha256(secret_signing, string_to_sign).hex()
        authorization = (
            "TC3-HMAC-SHA256 "
            f"Credential={self._secret_id}/{credential_scope}, "
            f"SignedHeaders={signed_headers}, Signature={signature}"
        )
        headers = {
            "Authorization": authorization,
            "Content-Type": CONTENT_TYPE,
            "Host": TENCENT_OCR_HOST,
            "X-TC-Action": action,
            "X-TC-Timestamp": str(timestamp),
            "X-TC-Version": TENCENT_OCR_VERSION,
        }
        if self._region:
            headers["X-TC-Region"] = self._region
        return headers

    # ---------------------------------------------------------------- 响应解析

    def _parse_response(self, data: Any, *, page: OCRInput, mode: OCRMode) -> OCRPageResult:
        if not isinstance(data, dict):
            raise OCRInvalidOutput("OCR 响应结构不合法")
        body = data.get("Response")
        if not isinstance(body, dict):
            raise OCRInvalidOutput("OCR 响应缺少 Response")
        request_id = safe_request_id(body.get("RequestId"))
        error = body.get("Error")
        if isinstance(error, dict):
            raise _map_provider_error(
                code=str(error.get("Code") or ""),
                message=str(error.get("Message") or ""),
                request_id=request_id,
            )
        if mode == "text":
            try:
                return _parse_general(body, page=page, request_id=request_id)
            except OCRInvalidOutput as exc:
                raise _with_request_id(exc, request_id) from exc
        try:
            return _parse_table(body, page=page, request_id=request_id)
        except OCRInvalidOutput as exc:
            raise _with_request_id(exc, request_id) from exc


# ---------------------------------------------------------------- 模块级辅助


def _hmac_sha256(key: bytes, message: str) -> bytes:
    return hmac.new(key, message.encode("utf-8"), hashlib.sha256).digest()


def _request_id_safe(response: httpx.Response) -> str | None:
    try:
        data = response.json()
    except ValueError:
        return None
    if isinstance(data, dict):
        body = data.get("Response")
        if isinstance(body, dict):
            return safe_request_id(body.get("RequestId"))
    return None


def _with_request_id(exc: OCRInvalidOutput, request_id: str | None) -> OCRInvalidOutput:
    """HTTP 200 但响应结构不可解析时，稳定 OCR_* 错误也要带上供应商 RequestId。

    失败态同样需要可追溯供应商请求（IA-T09 §1.2 附带缺陷）；已有 RequestId 的错误原样返回。
    """
    if exc.provider_request_id is not None or request_id is None:
        return exc
    return OCRInvalidOutput(exc.message, provider_request_id=request_id)


def _raise_provider_error(response: httpx.Response) -> None:
    request_id = _request_id_safe(response)
    try:
        data = response.json()
    except ValueError:
        raise OCRUnavailable(f"provider_status_{response.status_code}", provider_request_id=request_id) from None
    body = data.get("Response") if isinstance(data, dict) else None
    error = body.get("Error") if isinstance(body, dict) else None
    if isinstance(error, dict):
        raise _map_provider_error(
            code=str(error.get("Code") or ""),
            message=str(error.get("Message") or ""),
            request_id=request_id,
        )
    raise OCRUnavailable(f"provider_status_{response.status_code}", provider_request_id=request_id)


def _map_provider_error(*, code: str, message: str, request_id: str | None):
    lowered = (code or "").lower()
    if "requestlimitexceeded" in lowered or "toomanyrequests" in lowered:
        return OCRRateLimited("OCR 接口限流", provider_request_id=request_id)
    if any(
        marker in lowered
        for marker in (
            "nofreeamount",
            "inarrears",
            "resourceunavailable",
            "resourceinsufficient",
            "accountoverdue",
            "serviceisolate",
            "userregistered",
            "notexist",
            "limitexceeded",
        )
    ):
        return OCRQuotaUnavailable("OCR 额度不足", provider_request_id=request_id)
    if "authfailure" in lowered:
        return OCRAuthFailed("OCR 鉴权失败", provider_request_id=request_id)
    if any(marker in lowered for marker in ("invalidparameter", "imagedecodefailed", "imagesizetoolarge")):
        return OCRInvalidInput("OCR 请求参数或图片不被接受", provider_request_id=request_id)
    return OCRUnavailable("OCR 服务返回错误", provider_request_id=request_id)


def _offset_bbox(bbox: tuple[float, float, float, float] | None, x0: float, y0: float, x1: float, y1: float):
    if bbox is None:
        return [x0, y0, x1, y1]
    return [bbox[0] + x0, bbox[1] + y0, bbox[0] + x1, bbox[1] + y1]


def _polygon_bbox(polygon: Any) -> list[float] | None:
    if not isinstance(polygon, list):
        return None
    xs: list[float] = []
    ys: list[float] = []
    for point in polygon:
        if not isinstance(point, dict):
            continue
        x, y = point.get("X"), point.get("Y")
        if isinstance(x, (int, float)) and isinstance(y, (int, float)):
            xs.append(float(x))
            ys.append(float(y))
    if not xs or not ys:
        return None
    return [min(xs), min(ys), max(xs), max(ys)]


def _confidence(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _parse_general(body: Mapping[str, Any], *, page: OCRInput, request_id: str | None) -> OCRPageResult:
    detections = body.get("TextDetections")
    if detections is None:
        detections = []
    if not isinstance(detections, list):
        raise OCRInvalidOutput("TextDetections 结构不合法")
    lines: list[str] = []
    regions: list[dict[str, Any]] = []
    confidences: list[float] = []
    complete_confidence = True
    for item in detections:
        if not isinstance(item, dict):
            raise OCRInvalidOutput("TextDetections 项结构不合法")
        text = item.get("DetectedText")
        if not isinstance(text, str):
            raise OCRInvalidOutput("DetectedText 不是字符串")
        if text.strip():
            lines.append(text)
        bbox = _polygon_bbox(item.get("Polygon"))
        confidence = _confidence(item.get("Confidence"))
        if confidence is None:
            complete_confidence = False
        else:
            confidences.append(confidence)
        region: dict[str, Any] = {"text": text}
        if bbox is not None:
            region["bbox"] = _offset_bbox(page.bbox, *bbox)
        if confidence is not None:
            region["confidence"] = confidence
        regions.append(region)
    return OCRPageResult(
        text="\n".join(lines),
        regions=tuple(regions),
        provider_request_id=request_id,
        confidence=min(confidences) if confidences and complete_confidence else None,
    )


def _parse_table(body: Mapping[str, Any], *, page: OCRInput, request_id: str | None) -> OCRPageResult:
    detections = body.get("TableDetections")
    if detections is None:
        return OCRPageResult(text="", provider_request_id=request_id)
    if not isinstance(detections, list):
        raise OCRInvalidOutput("TableDetections 结构不合法")
    all_rows: list[list[str | None]] = []
    unplaced: list[str] = []
    regions: list[dict[str, Any]] = []
    confidences: list[float] = []
    complete_confidence = True
    for table_index, table in enumerate(detections):
        if not isinstance(table, dict):
            raise OCRInvalidOutput("TableDetections 项结构不合法")
        cells = table.get("Cells")
        if not isinstance(cells, list):
            raise OCRInvalidOutput("Cells 结构不合法")
        if not cells:
            continue
        placed: dict[tuple[int, int], str | None] = {}
        max_row = 0
        max_col = 0
        for cell in cells:
            if not isinstance(cell, dict):
                raise OCRInvalidOutput("单元格结构不合法")
            row_tl, col_tl = cell.get("RowTl"), cell.get("ColTl")
            row_br, col_br = cell.get("RowBr"), cell.get("ColBr")
            if not all(
                isinstance(value, int) and not isinstance(value, bool)
                for value in (row_tl, col_tl, row_br, col_br)
            ):
                raise OCRInvalidOutput("单元格坐标不是整数")
            text = cell.get("Text")
            if text is not None and not isinstance(text, str):
                raise OCRInvalidOutput("单元格文本不是字符串")
            if (row_tl, col_tl, row_br, col_br) == (TABLE_COORD_MISSING,) * 4:
                # -1 哨兵：供应商没有给出可定位区域。空单元格不含信息，直接忽略；
                # 有文字时只保留文字（不进入表格行、不生成 bbox/置信度），绝不伪造 0 坐标。
                if text and text.strip():
                    unplaced.append(text.strip())
                continue
            if row_tl < 0 or col_tl < 0 or row_br <= row_tl or col_br <= col_tl:
                raise OCRInvalidOutput("单元格坐标不合法")
            if row_br > MAX_TABLE_ROWS or col_br > MAX_TABLE_COLUMNS:
                raise OCRInvalidOutput("表格行列超出处理上限")
            key = (row_tl, col_tl)
            if key in placed and (placed[key] or "") != (text or ""):
                raise OCRInvalidOutput("单元格坐标冲突")
            placed[key] = text
            max_row = max(max_row, row_br)
            max_col = max(max_col, col_br)
            bbox = _polygon_bbox(cell.get("Polygon"))
            confidence = _confidence(cell.get("Confidence"))
            if text and text.strip():
                if confidence is None:
                    complete_confidence = False
                else:
                    confidences.append(confidence)
                region: dict[str, Any] = {"table": table_index + 1, "text": text}
                if bbox is not None:
                    region["bbox"] = _offset_bbox(page.bbox, *bbox)
                if confidence is not None:
                    region["confidence"] = confidence
                regions.append(region)
        grid: list[list[str | None]] = [[None for _ in range(max_col)] for _ in range(max_row)]
        for (row, col), text in placed.items():
            grid[row][col] = text.strip() if isinstance(text, str) else None
        for row in grid:
            if any(cell for cell in row):
                all_rows.append(row)
    lines = [*unplaced]
    lines.extend(" | ".join(cell or "" for cell in row) for row in all_rows)
    text = "\n".join(lines)
    return OCRPageResult(
        text=text,
        table_rows=tuple(tuple(row) for row in all_rows),
        regions=tuple(regions),
        provider_request_id=request_id,
        confidence=min(confidences) if confidences and complete_confidence else None,
    )

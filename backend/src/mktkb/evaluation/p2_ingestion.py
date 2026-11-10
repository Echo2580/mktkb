"""P2-T204：受控 OCR 导入 / 来源身份 / 页级费用回执 / 缓存准入（Mock-only）。

任务书 §6.2 的 `p2_ingestion.py` 职责：OCR/解析/发布、真实缓存身份及页级费用/来源回执；
**不替代**原 worker/解析器，也不改产品 API/schema/业务库。

本模块只做四件事（都在评测侧，零真实调用）：

1. **受控转录**（`OcrTranscript` + `MockOcrTransport`）：用 `httpx` 传输替身驱动**真实**
   `TencentOCRClient` 的编码/签名/解析路径，返回 fixture 的受控转录。传输替身永不出网，
   每次请求都按下面的身份逐字段校验；没有登记过的请求一律拒绝，不会"自动补"任何内容。
2. **来源身份**（`OcrCallIdentity` + `OcrSourceBinding`）：每次调用绑定
   document / version / page / input hash / provider / model / region。身份来自 worker 实际
   持有的 document/version（`ingestion.worker.OcrExecutor` 用可信来源锚覆盖解析器入参），
   本模块只接受已登记的来源锚，未登记的锚在预留与发送之前拒绝。
3. **页级费用回执**（`OcrPageReceipt` + `OcrCostCenterBudgetLedger`）：每页一次
   `BudgetLedger.reserve`/`settle`（复用 `providers.ocr_budgeted.BudgetedOCRGateway`），
   成本中心固定 `ocr`；回执用 `reservation_id` + `request_sha256` 与账本行一一对应，
   `bound_cny`（计划上界）与实际 `charged_cny` 分开记录。Mock 下真实费用为 0，但仍按
   计划/上界记账；缺 usage（无供应商 RequestId）、空片段、页失败、超单页上限、预算不足
   都不会被记成成功，并立即停止后续页。
4. **缓存准入**（`OcrResultCache`）：只接受"真实发生过调用 + 产品成功审计行"的条目；
   完整身份不一致（串用）、伪造（input hash/provider/model/region 不符）、过期、模拟来源
   一律拒绝，拒绝原因稳定可机读。命中与本轮真实调用分别计数。

边界：不读环境/`.env`、不写共享账本/GO、不安装依赖、不构造真实凭据、不修改产品表。
"""

from __future__ import annotations

import base64
import hashlib
import json
import threading
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

from ..ingestion.parsers.types import ParseLimits
from ..ingestion.worker import JobRunResult, run_one_job
from ..providers.ocr_budgeted import (
    CONTROLLED_OCR_MAX_CALLS,
    OCR_TABLE_PRICE_CNY,
    OCR_TEXT_PRICE_CNY,
    BudgetedOCRGateway,
)
from ..providers.tencent_ocr import GENERAL_ACTION, TABLE_ACTION, TencentOCRClient
from ..providers.types import (
    OCRError,
    OCRInput,
    OCRMode,
    OCRPageResult,
    make_ocr_source_scope,
)
from ..rag.budget import BudgetLedger, BudgetLedgerInvalid
from .p2_contracts import (
    OCR_PROVIDER,
    OCR_REGION,
    OCR_TABLE_MODEL,
    OCR_TEXT_MODEL,
)

__all__ = [
    "OCR_CACHE_DEFAULT_TTL_SECONDS",
    "OCR_COST_CENTER",
    "OCR_INGESTION_SCHEMA_VERSION",
    "MockOcrTransport",
    "OcrCallIdentity",
    "OcrCacheDecision",
    "OcrCacheEntry",
    "OcrCostCenterBudgetLedger",
    "OcrDocumentPlan",
    "OcrImportPlan",
    "OcrIngestionError",
    "OcrPageReceipt",
    "OcrResultCache",
    "OcrRunSummary",
    "OcrSourceBinding",
    "OcrTranscript",
    "P2OcrIngestion",
    "ProductOcrSuccess",
]

OCR_COST_CENTER = "ocr"
"""页级成本中心：与 `p2_contracts.COST_CENTERS` / `OPERATION_COST_CENTER['ocr']` 一致。"""

OCR_INGESTION_SCHEMA_VERSION = "p2-ocr-ingestion/v0.1"
OCR_CACHE_DEFAULT_TTL_SECONDS = 3600.0
CONTROLLED_OCR_MAX_ATTEMPTS = 1
"""受控 OCR 路线只允许一次 attempt（不自动重试），与 `ocr_budgeted` 的约束一致。"""

_SUPPORTED_KINDS = ("pdf", "png", "jpg", "jpeg")
_IMAGE_KINDS = ("png", "jpg", "jpeg")
_MODEL_BY_MODE: Mapping[str, str] = {"text": OCR_TEXT_MODEL, "table": OCR_TABLE_MODEL}
_PRICE_BY_MODE: Mapping[str, float] = {"text": float(OCR_TEXT_PRICE_CNY), "table": float(OCR_TABLE_PRICE_CNY)}
_ACTION_BY_MODE: Mapping[str, str] = {"text": GENERAL_ACTION, "table": TABLE_ACTION}

# 稳定拒绝/失败码（错误消息不回显原始值、图片内容或凭据）。
OCR_SOURCE_UNBOUND = "OCR_SOURCE_UNBOUND"
OCR_PAGE_NOT_PLANNED = "OCR_PAGE_NOT_PLANNED"
OCR_PAGE_CALL_LIMIT = "OCR_PAGE_CALL_LIMIT"
OCR_PLAN_CALL_LIMIT = "OCR_PLAN_CALL_LIMIT"
OCR_INGESTION_STOPPED = "OCR_INGESTION_STOPPED"
OCR_USAGE_MISSING = "OCR_USAGE_MISSING"
OCR_EMPTY_RESULT = "OCR_EMPTY_RESULT"
OCR_LEDGER_BINDING_MISMATCH = "OCR_LEDGER_BINDING_MISMATCH"

CACHE_MISS = "miss"
CACHE_HIT = "hit"
CACHE_REJECTED = "rejected"
# 缓存拒绝原因（稳定、可机读；不含被拒条目的原始值）
CACHE_EXPIRED = "cache_expired"
CACHE_SOURCE_IDENTITY_MISMATCH = "cache_source_identity_mismatch"
CACHE_INPUT_HASH_MISMATCH = "cache_input_hash_mismatch"
CACHE_PROVIDER_MISMATCH = "cache_provider_mismatch"
CACHE_MODEL_MISMATCH = "cache_model_mismatch"
CACHE_REGION_MISMATCH = "cache_region_mismatch"
CACHE_MODE_MISMATCH = "cache_mode_mismatch"
CACHE_PROVENANCE_MISSING = "cache_provenance_missing"
CACHE_SIMULATED = "cache_simulated"
CACHE_PAYLOAD_INVALID = "cache_payload_invalid"

CACHE_ORIGIN_OBSERVED = "observed-provider-call"
"""只有**实际发生过一次 Mock 供应商调用**并留下产品成功审计行的结果才可入缓存。"""


class OcrIngestionError(OCRError):
    """T204 稳定拒绝/失败码；`code` 由构造参数给出，消息不含原始身份/内容。"""

    code = "OCR_INGESTION_ERROR"

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat()


def _parse_iso(raw: Any, label: str) -> datetime:
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError(f"{label} 必须是 ISO8601 字符串")
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        raise ValueError(f"{label} 必须是 ISO8601 字符串") from None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def _hex64(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or value.lower() != value:
        raise ValueError(f"{label} 必须是 64 位小写 hex")
    try:
        int(value, 16)
    except ValueError:
        raise ValueError(f"{label} 必须是 64 位小写 hex") from None
    return value


def _plain_str(value: Any, label: str, *, maximum: int = 128) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} 必须是非空字符串")
    if len(value) > maximum:
        raise ValueError(f"{label} 过长")
    return value


def _plain_int(value: Any, label: str, *, minimum: int = 1, maximum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{label} 必须是整数")
    if value < minimum:
        raise ValueError(f"{label} 低于最小值")
    if maximum is not None and value > maximum:
        raise ValueError(f"{label} 超过最大值")
    return int(value)


# --------------------------------------------------------------------------- #
# 受控转录（fixture 页面内容，不内置任何验收答案）
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class OcrTranscript:
    """一份受控转录：页号→行文本；`table` 为该文件的规则表格（仅 table 模式使用）。"""

    document_key: str
    pages: Mapping[int, tuple[str, ...]]
    table: tuple[tuple[str, ...], tuple[tuple[str, ...], ...]] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "document_key", _plain_str(self.document_key, "transcript.document_key", maximum=32))
        if not isinstance(self.pages, Mapping) or not self.pages:
            raise ValueError("transcript.pages 必须是非空映射")
        normalized: dict[int, tuple[str, ...]] = {}
        for raw_page, lines in self.pages.items():
            page = _plain_int(raw_page, "transcript.pages 键")
            if isinstance(lines, str) or not isinstance(lines, Sequence) or not lines:
                raise ValueError("transcript.pages 值必须是非空的行序列")
            cleaned = tuple(str(line) for line in lines)
            if not any(line.strip() for line in cleaned):
                raise ValueError("transcript.pages 行文本不得全为空白")
            normalized[page] = cleaned
        object.__setattr__(self, "pages", {page: normalized[page] for page in sorted(normalized)})
        if self.table is not None:
            header, rows = self.table
            header = tuple(str(cell) for cell in header)
            rows = tuple(tuple(str(cell) for cell in row) for row in rows)
            if not header or not rows:
                raise ValueError("transcript.table 必须含表头与非空数据行")
            if any(len(row) != len(header) for row in rows):
                raise ValueError("transcript.table 每行长度必须与表头一致")
            object.__setattr__(self, "table", (header, rows))

    def lines_for(self, page: int) -> tuple[str, ...] | None:
        return self.pages.get(int(page))


# --------------------------------------------------------------------------- #
# 来源身份与计划
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class OcrCallIdentity:
    """一次 OCR 调用的完整身份：document/version/page/input hash/provider/model/region。"""

    document_id: str
    version_id: str
    page: int
    mode: str
    input_sha256: str
    request_sha256: str
    provider: str
    model: str
    region: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "document_id", _plain_str(self.document_id, "identity.document_id", maximum=64))
        object.__setattr__(self, "version_id", _plain_str(self.version_id, "identity.version_id", maximum=64))
        object.__setattr__(self, "page", _plain_int(self.page, "identity.page"))
        if self.mode not in _PRICE_BY_MODE:
            raise ValueError("identity.mode 必须是 text/table")
        object.__setattr__(self, "input_sha256", _hex64(self.input_sha256, "identity.input_sha256"))
        object.__setattr__(self, "request_sha256", _hex64(self.request_sha256, "identity.request_sha256"))
        if self.provider != OCR_PROVIDER:
            raise ValueError(f"identity.provider 必须是 {OCR_PROVIDER}")
        expected_model = _MODEL_BY_MODE[self.mode]
        if self.model != expected_model:
            raise ValueError(f"identity.model 必须是 {expected_model}")
        if self.region != OCR_REGION:
            raise ValueError(f"identity.region 必须是 {OCR_REGION}")

    @property
    def source_scope(self) -> str:
        return make_ocr_source_scope(self.document_id, self.version_id)

    @property
    def bound_cny(self) -> float:
        return _PRICE_BY_MODE[self.mode]

    @property
    def key(self) -> tuple[Any, ...]:
        """缓存主键：七元身份全字段（少一项就不是同一次调用）。"""
        return (
            self.document_id,
            self.version_id,
            self.page,
            self.mode,
            self.input_sha256,
            self.provider,
            self.model,
            self.region,
        )

    def mismatches(self, other: "OcrCallIdentity") -> tuple[str, ...]:
        """逐字段差异的稳定原因码（用于"串用/伪造"的可观察拒绝）。"""
        reasons: list[str] = []
        if (self.document_id, self.version_id, self.page) != (
            other.document_id,
            other.version_id,
            other.page,
        ):
            reasons.append(CACHE_SOURCE_IDENTITY_MISMATCH)
        if self.mode != other.mode:
            reasons.append(CACHE_MODE_MISMATCH)
        if self.input_sha256 != other.input_sha256:
            reasons.append(CACHE_INPUT_HASH_MISMATCH)
        if self.provider != other.provider:
            reasons.append(CACHE_PROVIDER_MISMATCH)
        if self.model != other.model:
            reasons.append(CACHE_MODEL_MISMATCH)
        if self.region != other.region:
            reasons.append(CACHE_REGION_MISMATCH)
        return tuple(dict.fromkeys(reasons))

    def as_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "version_id": self.version_id,
            "page": int(self.page),
            "mode": self.mode,
            "input_sha256": self.input_sha256,
            "request_sha256": self.request_sha256,
            "provider": self.provider,
            "model": self.model,
            "region": self.region,
            "source_scope": self.source_scope,
            "bound_cny": self.bound_cny,
        }

    @classmethod
    def of(
        cls,
        *,
        document_id: object,
        version_id: object,
        page: int,
        mode: str,
        content: bytes,
    ) -> "OcrCallIdentity":
        """由 worker 可信 document/version 与实际图块字节构造身份；不接受调用方给的 provider。"""
        if mode not in _PRICE_BY_MODE:
            raise OcrIngestionError(OCR_SOURCE_UNBOUND, "OCR 模式非法，拒绝（未预留未发送）")
        if not isinstance(content, (bytes, bytearray)) or not content:
            raise OcrIngestionError(OCR_USAGE_MISSING, "OCR 图块为空，拒绝（未预留未发送）")
        doc = _plain_str(str(document_id or ""), "document_id", maximum=64)
        ver = _plain_str(str(version_id or ""), "version_id", maximum=64)
        scope = make_ocr_source_scope(doc, ver)
        payload = f"ocr-v2|{scope}|{mode}|{int(page)}|".encode("utf-8")
        return cls(
            document_id=doc,
            version_id=ver,
            page=int(page),
            mode=mode,
            input_sha256=hashlib.sha256(bytes(content)).hexdigest(),
            request_sha256=hashlib.sha256(payload + bytes(content)).hexdigest(),
            provider=OCR_PROVIDER,
            model=_MODEL_BY_MODE[mode],
            region=OCR_REGION,
        )


@dataclass(frozen=True)
class OcrDocumentPlan:
    """一份要经 OCR 导入的资料：页数/图片数/每页分片数与期望模式（计划即费用上界）。"""

    document_key: str
    path: Path
    file_kind: str
    page_count: int
    image_count: int
    tiles_per_page: int = 1
    expected_mode: str = "text"

    def __post_init__(self) -> None:
        object.__setattr__(self, "document_key", _plain_str(self.document_key, "document_key", maximum=32))
        path = Path(self.path)
        if not path.is_file():
            raise ValueError(f"OCR 计划资料不存在: {path.name}")
        object.__setattr__(self, "path", path)
        kind = str(self.file_kind).lower()
        if kind not in _SUPPORTED_KINDS:
            raise ValueError("file_kind 必须是 pdf/png/jpg/jpeg")
        object.__setattr__(self, "file_kind", kind)
        pages = _plain_int(self.page_count, "page_count")
        images = _plain_int(self.image_count, "image_count", minimum=0, maximum=1)
        if kind in _IMAGE_KINDS:
            if pages != 1 or images != 1:
                raise ValueError("图片资料的 page_count 必须为 1、image_count 必须为 1")
        elif images != 0:
            raise ValueError("PDF 资料的 image_count 必须为 0")
        object.__setattr__(self, "page_count", pages)
        object.__setattr__(self, "image_count", images)
        limit = int(ParseLimits().ocr_max_tiles)
        object.__setattr__(
            self, "tiles_per_page", _plain_int(self.tiles_per_page, "tiles_per_page", maximum=limit)
        )
        if self.expected_mode not in _PRICE_BY_MODE:
            raise ValueError("expected_mode 必须是 text/table")
        if self.planned_calls > CONTROLLED_OCR_MAX_CALLS:
            raise ValueError(
                f"单份资料的 OCR 调用计划 {self.planned_calls} 超过受控上限 {CONTROLLED_OCR_MAX_CALLS}"
            )

    @property
    def is_image(self) -> bool:
        return self.file_kind in _IMAGE_KINDS

    @property
    def planned_pages(self) -> tuple[int, ...]:
        return (1,) if self.is_image else tuple(range(1, int(self.page_count) + 1))

    @property
    def planned_calls(self) -> int:
        return len(self.planned_pages) * int(self.tiles_per_page)

    def as_dict(self) -> dict[str, Any]:
        return {
            "document_key": self.document_key,
            "file_kind": self.file_kind,
            "page_count": int(self.page_count),
            "image_count": int(self.image_count),
            "tiles_per_page": int(self.tiles_per_page),
            "expected_mode": self.expected_mode,
            "planned_calls": self.planned_calls,
            "sha256": hashlib.sha256(self.path.read_bytes()).hexdigest(),
        }


@dataclass(frozen=True)
class OcrImportPlan:
    """一份 OCR 导入计划（顺序即导入顺序）；页与图分别计数。"""

    documents: tuple[OcrDocumentPlan, ...]
    label: str = ""
    schema_version: str = OCR_INGESTION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.documents, tuple) or not self.documents:
            raise ValueError("OCR 导入计划必须是非空 OcrDocumentPlan 元组")
        keys = [doc.document_key for doc in self.documents]
        if len(set(keys)) != len(keys):
            raise ValueError("OCR 导入计划的 document_key 不得重复")

    @property
    def by_key(self) -> dict[str, OcrDocumentPlan]:
        return {doc.document_key: doc for doc in self.documents}

    @property
    def pages(self) -> int:
        return sum(int(doc.page_count) for doc in self.documents if not doc.is_image)

    @property
    def images(self) -> int:
        return sum(int(doc.image_count) for doc in self.documents)

    @property
    def planned_calls(self) -> int:
        return sum(doc.planned_calls for doc in self.documents)

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "label": self.label,
            "pages": self.pages,
            "images": self.images,
            "planned_calls": self.planned_calls,
            "documents": [doc.as_dict() for doc in self.documents],
        }


@dataclass(frozen=True)
class OcrSourceBinding:
    """服务端可信身份 → 计划资料的绑定（version 变化即新绑定/新来源锚）。"""

    document_key: str
    document_id: str
    version_id: str
    plan: OcrDocumentPlan

    def __post_init__(self) -> None:
        object.__setattr__(self, "document_id", _plain_str(self.document_id, "binding.document_id", maximum=64))
        object.__setattr__(self, "version_id", _plain_str(self.version_id, "binding.version_id", maximum=64))

    @property
    def source_scope(self) -> str:
        return make_ocr_source_scope(self.document_id, self.version_id)

    def as_dict(self) -> dict[str, Any]:
        return {
            "document_key": self.document_key,
            "document_id": self.document_id,
            "version_id": self.version_id,
            "source_scope": self.source_scope,
            "planned_calls": self.plan.planned_calls,
            "planned_pages": list(self.plan.planned_pages),
        }


# --------------------------------------------------------------------------- #
# 传输替身（真实客户端编码/签名，0 出网）
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class _Expectation:
    identity: OcrCallIdentity
    transcript: OcrTranscript


class MockOcrTransport(httpx.BaseTransport):
    """`httpx` 传输替身：把受控转录变成腾讯云形状的 JSON，并逐字段核对线上身份。

    - 每次请求必须由 :meth:`expected` 预先登记（document/version/page 身份 + 转录）；
      没有登记的请求一律返回错误（不会"自动补"识别结果）；
    - 线上校验：图片字节 hash 必须等于身份里的 input hash；`X-TC-Action` 必须与模式一致；
      `X-TC-Region` 必须等于计划区域。任何不符都记 `violations` 并返回错误；
    - 永不出网：本类不触碰 socket，`httpx.Client` 只用它作为 transport。
    """

    def __init__(self, *, clock: Callable[[], int] | None = None) -> None:
        self._lock = threading.Lock()
        self._pending: _Expectation | None = None
        self.requests: list[dict[str, Any]] = []
        self.violations: list[str] = []
        self.entered = threading.Event()
        self.release = threading.Event()
        self._block_pages: set[int] = set()
        self._failures: dict[int, str] = {}
        self.drop_request_id = False
        self.empty_text = False
        self._clock = clock or (lambda: 1_760_000_000)

    # ---------------------------------------------------------------- 测试钩子
    def block_on(self, *pages: int) -> None:
        """在指定页的"供应商调用"内阻塞，用于取消/删除/迟到响应时序。"""
        self._block_pages = {int(page) for page in pages}
        self.entered.clear()
        self.release.clear()

    def unblock(self) -> None:
        self._block_pages = set()
        self.release.set()

    def fail_on(self, page: int, *, mode: str = "unavailable") -> None:
        """注入稳定故障：`unavailable` → OCR_UNAVAILABLE，`timeout` → OCR_TIMEOUT。"""
        if mode not in ("unavailable", "timeout"):
            raise ValueError("只支持 unavailable/timeout 两种注入故障")
        self._failures[int(page)] = mode

    def clear_failures(self) -> None:
        self._failures = {}

    # ---------------------------------------------------------------- 请求登记
    @contextmanager
    def expected(self, *, identity: OcrCallIdentity, transcript: OcrTranscript) -> Iterator[None]:
        with self._lock:
            if self._pending is not None:
                raise OcrIngestionError(
                    OCR_LEDGER_BINDING_MISMATCH, "OCR 传输替身已有未消费的登记请求"
                )
            self._pending = _Expectation(identity=identity, transcript=transcript)
        try:
            yield
        finally:
            with self._lock:
                self._pending = None

    def close(self) -> None:
        return None

    # ---------------------------------------------------------------- 协议实现
    def handle_request(self, request: httpx.Request) -> httpx.Response:
        image = self._decode_image(request)
        image_sha = hashlib.sha256(image).hexdigest() if image else ""
        action = str(request.headers.get("X-TC-Action") or "")
        region = str(request.headers.get("X-TC-Region") or "")
        with self._lock:
            expectation, self._pending = self._pending, None
        if expectation is None:
            self._violation("unexpected_provider_request", page=None)
            return _error_response("FailedOperation.UnexpectedRequest", self._clock())
        identity = expectation.identity
        with self._lock:
            self.requests.append(
                {
                    "ordinal": len(self.requests) + 1,
                    "document_id": identity.document_id,
                    "version_id": identity.version_id,
                    "page": int(identity.page),
                    "mode": identity.mode,
                    "input_sha256": image_sha,
                    "expected_input_sha256": identity.input_sha256,
                    "action": action,
                    "region": region,
                    "bytes": len(image),
                }
            )
        if not image:
            self._violation("missing_image_base64", page=identity.page)
            return _error_response("InvalidParameter.ImageDecodeFailed", self._clock())
        if image_sha != identity.input_sha256:
            self._violation("input_hash_mismatch", page=identity.page)
            return _error_response("InvalidParameter.ImageDecodeFailed", self._clock())
        if action != _ACTION_BY_MODE[identity.mode]:
            self._violation("action_mode_mismatch", page=identity.page)
            return _error_response("InvalidParameter.ActionMismatch", self._clock())
        if region != identity.region:
            self._violation("region_mismatch", page=identity.page)
            return _error_response("AuthFailure.RegionNotAuthorized", self._clock())
        if identity.page in self._block_pages:
            self.entered.set()
            if not self.release.wait(30):
                self._violation("block_timeout", page=identity.page)
                return _error_response("FailedOperation.Timeout", self._clock())
        failure = self._failures.get(int(identity.page))
        if failure == "unavailable":
            raise httpx.ConnectError("p2-t204 mock provider unavailable")
        if failure == "timeout":
            raise httpx.ReadTimeout("p2-t204 mock provider timeout")
        return self._response_for(expectation)

    # ---------------------------------------------------------------- 响应构造
    def _response_for(self, expectation: _Expectation) -> httpx.Response:
        identity = expectation.identity
        transcript = expectation.transcript
        request_id = (
            None if self.drop_request_id else f"p2t204-{identity.source_scope[:8]}-p{identity.page}"
        )
        if identity.mode == "table":
            if transcript.table is None:
                self._violation("transcript_table_missing", page=identity.page)
                return _error_response("FailedOperation.NoTableDetected", self._clock())
            body = _table_body(transcript.table, request_id=request_id)
        else:
            lines = transcript.lines_for(identity.page)
            if lines is None:
                self._violation("transcript_page_missing", page=identity.page)
                return _error_response("FailedOperation.NoImageText", self._clock())
            body = _text_body(() if self.empty_text else lines, request_id=request_id)
        return httpx.Response(200, json={"Response": body})

    @staticmethod
    def _decode_image(request: httpx.Request) -> bytes:
        try:
            payload = json.loads(request.content or b"{}")
        except ValueError:
            return b""
        encoded = payload.get("ImageBase64") if isinstance(payload, dict) else None
        if not isinstance(encoded, str) or not encoded:
            return b""
        try:
            return base64.b64decode(encoded.encode("ascii"), validate=True)
        except (ValueError, TypeError):
            return b""

    def _violation(self, reason: str, *, page: int | None) -> None:
        with self._lock:
            self.violations.append(f"{reason}:page={page}")


def _text_body(lines: Sequence[str], *, request_id: str | None) -> dict[str, Any]:
    detections = [
        {
            "DetectedText": str(line),
            "Confidence": 90.0,
            "Polygon": [
                {"X": 0, "Y": index * 10},
                {"X": 400, "Y": index * 10},
                {"X": 400, "Y": index * 10 + 8},
                {"X": 0, "Y": index * 10 + 8},
            ],
        }
        for index, line in enumerate(lines)
    ]
    body: dict[str, Any] = {"TextDetections": detections}
    if request_id is not None:
        body["RequestId"] = request_id
    return body


def _table_body(
    table: tuple[tuple[str, ...], tuple[tuple[str, ...], ...]], *, request_id: str | None
) -> dict[str, Any]:
    header, rows = table
    grid = [header, *rows]
    cells: list[dict[str, Any]] = []
    for row_index, row in enumerate(grid):
        for column_index, text in enumerate(row):
            x0, y0 = column_index * 20, row_index * 10
            cells.append(
                {
                    "RowTl": row_index,
                    "ColTl": column_index,
                    "RowBr": row_index + 1,
                    "ColBr": column_index + 1,
                    "Text": text,
                    "Confidence": 90.0,
                    "Polygon": [
                        {"X": x0, "Y": y0},
                        {"X": x0 + 18, "Y": y0},
                        {"X": x0 + 18, "Y": y0 + 9},
                        {"X": x0, "Y": y0 + 9},
                    ],
                }
            )
    body: dict[str, Any] = {"TableDetections": [{"Cells": cells}]}
    if request_id is not None:
        body["RequestId"] = request_id
    return body


def _error_response(code: str, clock_value: int) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "Response": {
                "Error": {"Code": code, "Message": "mock"},
                "RequestId": f"p2t204-err-{clock_value}",
            }
        },
    )


# --------------------------------------------------------------------------- #
# 页级回执与缓存
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class OcrPageReceipt:
    """一页/一块一次调用的回执：身份 + 账本归属 + 费用上界/实际 + 缓存状态。"""

    run_id: str
    document_key: str
    identity: OcrCallIdentity
    status: str
    cache: str
    bound_cny: float
    charged_cny: float
    reservation_id: str | None = None
    ledger_request_sha256: str | None = None
    provider_request_id: str | None = None
    error_code: str | None = None
    elapsed_ms: int = 0
    admission: str | None = None
    tiles: int = 1

    @property
    def succeeded(self) -> bool:
        return self.status == "succeeded"

    @property
    def cache_hit(self) -> bool:
        return self.cache == CACHE_HIT

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "document_key": self.document_key,
            "status": self.status,
            "cache": self.cache,
            "bound_cny": round(float(self.bound_cny), 8),
            "charged_cny": round(float(self.charged_cny), 8),
            "reservation_id": self.reservation_id,
            "ledger_request_sha256": self.ledger_request_sha256,
            "provider_request_id": self.provider_request_id,
            "error_code": self.error_code,
            "elapsed_ms": int(self.elapsed_ms),
            "admission": self.admission,
            "tiles": int(self.tiles),
            "identity": self.identity.as_dict(),
        }


@dataclass(frozen=True)
class OcrCacheEntry:
    """一条可复用结果：完整身份 + 结果 + 真实调用来源 + 产品成功审计行 id。"""

    identity: OcrCallIdentity
    text: str
    table_rows: tuple[tuple[str | None, ...], ...]
    provider_request_id: str
    product_record_id: str
    admitted_at: str
    expires_at: str
    origin: str = CACHE_ORIGIN_OBSERVED
    confidence: float | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.identity, OcrCallIdentity):
            raise ValueError("cache entry.identity 必须是 OcrCallIdentity")
        object.__setattr__(self, "text", str(self.text))
        object.__setattr__(
            self,
            "table_rows",
            tuple(
                tuple(None if cell is None else str(cell) for cell in row)
                for row in self.table_rows
            ),
        )
        object.__setattr__(self, "product_record_id", _plain_str(self.product_record_id, "product_record_id"))
        object.__setattr__(
            self, "provider_request_id", _plain_str(self.provider_request_id, "provider_request_id")
        )
        object.__setattr__(self, "admitted_at", _iso(_parse_iso(self.admitted_at, "admitted_at")))
        object.__setattr__(self, "expires_at", _iso(_parse_iso(self.expires_at, "expires_at")))
        if self.origin not in (CACHE_ORIGIN_OBSERVED, "simulated"):
            raise ValueError("cache entry.origin 只接受 observed-provider-call/simulated")

    def expired(self, moment: datetime) -> bool:
        return _parse_iso(self.expires_at, "expires_at") <= moment

    def result(self) -> OCRPageResult:
        return OCRPageResult(
            text=self.text,
            table_rows=self.table_rows,
            provider_request_id=self.provider_request_id,
            confidence=self.confidence,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "identity": self.identity.as_dict(),
            "text": self.text,
            "table_rows": [list(row) for row in self.table_rows],
            "provider_request_id": self.provider_request_id,
            "product_record_id": self.product_record_id,
            "admitted_at": self.admitted_at,
            "expires_at": self.expires_at,
            "origin": self.origin,
            "confidence": self.confidence,
        }

    @classmethod
    def from_payload(cls, payload: Any) -> "OcrCacheEntry":
        if not isinstance(payload, Mapping):
            raise ValueError("cache payload 必须是对象")
        raw_identity = payload.get("identity")
        if not isinstance(raw_identity, Mapping):
            raise ValueError("cache payload.identity 必须是对象")
        identity = OcrCallIdentity(
            document_id=raw_identity.get("document_id"),
            version_id=raw_identity.get("version_id"),
            page=raw_identity.get("page"),
            mode=raw_identity.get("mode"),
            input_sha256=raw_identity.get("input_sha256"),
            request_sha256=raw_identity.get("request_sha256"),
            provider=raw_identity.get("provider"),
            model=raw_identity.get("model"),
            region=raw_identity.get("region"),
        )
        rows = payload.get("table_rows") or ()
        if isinstance(rows, (str, bytes)) or not isinstance(rows, Sequence):
            raise ValueError("cache payload.table_rows 必须是行序列")
        confidence = payload.get("confidence")
        if confidence is not None and not isinstance(confidence, (int, float)):
            raise ValueError("cache payload.confidence 必须是数字或 null")
        return cls(
            identity=identity,
            text=payload.get("text") or "",
            table_rows=tuple(tuple(row) for row in rows),
            provider_request_id=payload.get("provider_request_id"),
            product_record_id=payload.get("product_record_id"),
            admitted_at=payload.get("admitted_at"),
            expires_at=payload.get("expires_at"),
            origin=payload.get("origin") or "simulated",
            confidence=None if confidence is None else float(confidence),
        )


@dataclass(frozen=True)
class OcrCacheDecision:
    status: str
    reason: str | None = None
    entry: OcrCacheEntry | None = None

    @property
    def hit(self) -> bool:
        return self.status == CACHE_HIT

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "reason": self.reason,
            "provider_request_id": None if self.entry is None else self.entry.provider_request_id,
        }


class OcrResultCache:
    """结果缓存：命中必须七元身份完全一致、来源是真实调用、有产品成功审计行且未过期。

    - 主键是 :attr:`OcrCallIdentity.key`（少一项都不算同一次调用）；
    - 另按 (page, mode) 建次级索引：同页不同 document/version/provider/model/region/input hash
      的条目以**拒绝原因**返回（`rejected`），不会静默 miss 也不会被错误复用；
    - 只由 :meth:`admit` 写入；:meth:`from_payload` 恢复时逐条严格重校验，非法条目隔离。
    """

    def __init__(
        self,
        *,
        ttl_seconds: float = OCR_CACHE_DEFAULT_TTL_SECONDS,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, (int, float)) or ttl_seconds <= 0:
            raise ValueError("cache ttl_seconds 必须是正数")
        self._ttl = float(ttl_seconds)
        self._now = now or _utc_now
        self._lock = threading.Lock()
        self._entries: dict[tuple[Any, ...], OcrCacheEntry] = {}
        self._by_page: dict[tuple[int, str], list[OcrCacheEntry]] = {}
        self.quarantined: list[str] = []

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    def entries(self) -> list[OcrCacheEntry]:
        with self._lock:
            return list(self._entries.values())

    def admit(
        self,
        identity: OcrCallIdentity,
        result: OCRPageResult,
        *,
        product_record_id: str,
        admitted_at: datetime | None = None,
    ) -> OcrCacheEntry:
        """写入一条**已真实发生且产品已成功落审计行**的结果；其他来源一律拒绝。"""
        moment = admitted_at or self._now()
        entry = OcrCacheEntry(
            identity=identity,
            text=result.text,
            table_rows=tuple(tuple(row) for row in result.table_rows),
            provider_request_id=str(result.provider_request_id or ""),
            product_record_id=str(product_record_id),
            admitted_at=_iso(moment),
            expires_at=_iso(moment + timedelta(seconds=self._ttl)),
            origin=CACHE_ORIGIN_OBSERVED,
            confidence=result.confidence,
        )
        with self._lock:
            self._entries[identity.key] = entry
            bucket = self._by_page.setdefault((identity.page, identity.mode), [])
            bucket[:] = [item for item in bucket if item.identity.key != identity.key] + [entry]
        return entry

    def lookup(self, identity: OcrCallIdentity, *, now: datetime | None = None) -> OcrCacheDecision:
        moment = now or self._now()
        with self._lock:
            exact = self._entries.get(identity.key)
            candidates = list(self._by_page.get((identity.page, identity.mode), []))
        if exact is None:
            for candidate in candidates:
                reasons = candidate.identity.mismatches(identity)
                if reasons:
                    return OcrCacheDecision(CACHE_REJECTED, reasons[0], None)
            return OcrCacheDecision(CACHE_MISS, None, None)
        if exact.origin != CACHE_ORIGIN_OBSERVED:
            return OcrCacheDecision(CACHE_REJECTED, CACHE_SIMULATED, None)
        if not exact.product_record_id:
            return OcrCacheDecision(CACHE_REJECTED, CACHE_PROVENANCE_MISSING, None)
        if exact.expired(moment):
            return OcrCacheDecision(CACHE_REJECTED, CACHE_EXPIRED, None)
        if not exact.text.strip() and not exact.table_rows:
            return OcrCacheDecision(CACHE_REJECTED, CACHE_PROVENANCE_MISSING, None)
        return OcrCacheDecision(CACHE_HIT, None, exact)

    def as_payload(self) -> list[dict[str, Any]]:
        return [entry.as_dict() for entry in self.entries()]

    @classmethod
    def from_payload(
        cls,
        payload: Sequence[Mapping[str, Any]] | None,
        *,
        ttl_seconds: float = OCR_CACHE_DEFAULT_TTL_SECONDS,
        now: Callable[[], datetime] | None = None,
    ) -> "OcrResultCache":
        """从持久化产物恢复缓存：逐条严格重校验，非法条目只记隔离原因、不入缓存。"""
        cache = cls(ttl_seconds=ttl_seconds, now=now)
        for row in payload or ():
            try:
                entry = OcrCacheEntry.from_payload(row)
            except (ValueError, TypeError):
                cache.quarantined.append(CACHE_PAYLOAD_INVALID)
                continue
            with cache._lock:
                cache._entries[entry.identity.key] = entry
                bucket = cache._by_page.setdefault((entry.identity.page, entry.identity.mode), [])
                bucket.append(entry)
        return cache


# --------------------------------------------------------------------------- #
# 账本：把每一笔 OCR 预留显式归属到 ocr 成本中心
# --------------------------------------------------------------------------- #


class OcrCostCenterBudgetLedger(BudgetLedger):
    """只接受 `kind=ocr` 的预算账本；每笔预留强制带 `cost_center=ocr`。

    复用既有 `BudgetLedger` 的锁/事件/结算语义（不造第二套资金真账），只补两件事：
    1. 拒绝对非 OCR 种类的预留（fail closed）；
    2. 把成本中心与预留原子落盘，使 `summary()['center_accounted_cny']['ocr']` 与逐页回执
       都能从账本独立重算。
    """

    def reserve(  # type: ignore[override]
        self,
        *,
        kind: str,
        provider: str,
        model: str,
        max_cny: float,
        request_sha256: str,
        cost_center: str | None = None,
        **kwargs: Any,
    ):
        if kind != OCR_COST_CENTER:
            raise BudgetLedgerInvalid("本账本只接受 kind=ocr 的预留")
        if cost_center is not None and cost_center != OCR_COST_CENTER:
            raise BudgetLedgerInvalid("OCR 预留的成本中心必须是 ocr")
        return super().reserve(
            kind=kind,
            provider=provider,
            model=model,
            max_cny=max_cny,
            request_sha256=request_sha256,
            cost_center=OCR_COST_CENTER,
            **kwargs,
        )


# --------------------------------------------------------------------------- #
# 产品成功审计行（只读观测；由调用方从产品 ocr_call_records 读出）
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ProductOcrSuccess:
    """产品 OCR 审计表里的一行：缓存准入/复用认证的唯一依据。"""

    record_id: str
    document_id: str
    version_id: str
    page: int
    mode: str
    input_sha256: str
    provider_request_id: str | None
    state: str = "succeeded"

    @property
    def identity_key(self) -> tuple[str, str, int, str]:
        return (self.document_id, self.version_id, int(self.page), self.mode)

    @property
    def has_usage(self) -> bool:
        return bool(self.provider_request_id) and self.state == "succeeded"

    def as_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "document_id": self.document_id,
            "version_id": self.version_id,
            "page": int(self.page),
            "mode": self.mode,
            "input_sha256": self.input_sha256,
            "provider_request_id": self.provider_request_id,
            "state": self.state,
        }


@dataclass(frozen=True)
class OcrRunSummary:
    """一轮 OCR 导入的对账结果：计划/真实请求/缓存命中/产品检查点复用分别计数。"""

    run_id: str
    document_key: str
    document_id: str
    version_id: str
    planned_calls: int
    planned_pages: tuple[int, ...]
    attempts: int
    provider_requests: int
    cache_hits: int
    product_checkpoint_reuses: int
    failed_pages: tuple[int, ...]
    missing_pages: tuple[int, ...]
    charged_cny: float
    bound_cny: float
    pages: tuple[Mapping[str, Any], ...]

    @property
    def plan_matches_provider_requests(self) -> bool:
        """计划调用数 == 本轮真实供应商请求数（缓存命中/检查点复用另计）。"""
        return int(self.planned_calls) == int(self.provider_requests)

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "document_key": self.document_key,
            "document_id": self.document_id,
            "version_id": self.version_id,
            "planned_calls": int(self.planned_calls),
            "planned_pages": list(self.planned_pages),
            "attempts": int(self.attempts),
            "provider_requests": int(self.provider_requests),
            "cache_hits": int(self.cache_hits),
            "product_checkpoint_reuses": int(self.product_checkpoint_reuses),
            "failed_pages": list(self.failed_pages),
            "missing_pages": list(self.missing_pages),
            "charged_cny": round(float(self.charged_cny), 8),
            "bound_cny": round(float(self.bound_cny), 8),
            "plan_matches_provider_requests": self.plan_matches_provider_requests,
            "pages": [dict(row) for row in self.pages],
        }


# --------------------------------------------------------------------------- #
# 导入器：身份 → 计划 → 缓存 → 页级预算 → 回执
# --------------------------------------------------------------------------- #


class _IngestionGateway:
    """注入 worker 的最小 OCR 网关（只有 recognize）：全部策略在导入器里。"""

    __slots__ = ("_owner",)

    def __init__(self, owner: "P2OcrIngestion") -> None:
        self._owner = owner

    def recognize(self, page: OCRInput, *, mode: OCRMode) -> OCRPageResult:
        return self._owner.recognize(page, mode=mode)


class P2OcrIngestion:
    """受控 OCR 导入：真实 worker/解析/发布路径 + Mock 传输 + 页级账本 + 缓存准入。

    用法（零真实调用）::

        ingestion = P2OcrIngestion.isolated_mock(work_dir, plan=plan, transcripts=transcripts)
        result = ingestion.run_job(db, store, document_key="D07", document_id=doc, version_id=ver)
        summary = ingestion.finalize(document_id=doc, version_id=ver, records=records)

    `records` 是产品 `ocr_call_records` 的只读投影（`ProductOcrSuccess`）：缓存准入与
    "产品检查点复用"认证都以它为准，而不是以本模块自己的记账为准。
    """

    def __init__(
        self,
        plan: OcrImportPlan,
        *,
        transcripts: Mapping[str, OcrTranscript] | Sequence[OcrTranscript],
        ledger: BudgetLedger,
        cache: OcrResultCache | None = None,
        cache_ttl_seconds: float = OCR_CACHE_DEFAULT_TTL_SECONDS,
        max_calls: int | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if not isinstance(plan, OcrImportPlan):
            raise ValueError("plan 必须是 OcrImportPlan")
        if not isinstance(ledger, BudgetLedger):
            raise ValueError("ledger 必须是隔离的 BudgetLedger")
        self.plan = plan
        self.ledger = ledger
        self.cache = cache or OcrResultCache(ttl_seconds=cache_ttl_seconds, now=now)
        self._now = now or _utc_now
        self._lock = threading.Lock()
        self._transcripts = _transcript_map(transcripts)
        for document in plan.documents:
            transcript = self._transcripts.get(document.document_key)
            if transcript is None:
                raise ValueError(f"计划资料 {document.document_key} 没有受控转录")
            expected = set(document.planned_pages)
            actual = set(transcript.pages)
            if expected != actual:
                raise ValueError(
                    f"{document.document_key} 的转录页号 {sorted(actual)} 与计划 {sorted(expected)} 不一致"
                )
        self.transport = MockOcrTransport()
        self._client = TencentOCRClient(
            secret_id="p2-t204-mock-secret-id-not-a-secret",
            secret_key="p2-t204-mock-secret-key-not-a-secret",
            region=OCR_REGION,
            transport=self.transport,
            timeout_seconds=30.0,
        )
        self._max_calls = (
            min(CONTROLLED_OCR_MAX_CALLS, max(1, int(plan.planned_calls)))
            if max_calls is None
            else min(CONTROLLED_OCR_MAX_CALLS, max(1, int(max_calls)))
        )
        self._max_tiles_per_page = max(int(doc.tiles_per_page) for doc in plan.documents)
        # 受控网关是 **run 级** 的：它一旦失败就自我停止，不能跨 run 复用（否则重试会被
        # 上一轮的停止态挡在预留之前）。钱的上界仍由同一隔离账本阶段额度约束。
        self._budgeted: BudgetedOCRGateway | None = None
        self._gateway = _IngestionGateway(self)
        self._bindings_by_scope: dict[str, OcrSourceBinding] = {}
        self._bindings_by_key: dict[str, list[OcrSourceBinding]] = {}
        self._version_keys: dict[str, str] = {}
        self._receipts: list[OcrPageReceipt] = []
        self._observed: dict[tuple[Any, ...], OCRPageResult] = {}
        self._page_calls: dict[tuple[str, int], int] = {}
        self._doc_calls: dict[str, int] = {}
        self._runs: dict[str, dict[str, Any]] = {}
        self._run_marks: dict[str, tuple[int, int]] = {}
        self._current_run: str | None = None
        self._stopped = False
        self._stop_code: str | None = None

    # ---------------------------------------------------------------- 隔离装配
    @classmethod
    def isolated_mock(
        cls,
        work_dir: Path | str,
        *,
        plan: OcrImportPlan,
        transcripts: Mapping[str, OcrTranscript] | Sequence[OcrTranscript],
        stage: str = "P2-T204-OCR-MOCK",
        limit_cny: float = 20.0,
        historical_cny: float = 0.0,
        stage_limit_cny: float = 9.66,
        max_requests: int = 400,
        cache_ttl_seconds: float = OCR_CACHE_DEFAULT_TTL_SECONDS,
        max_calls: int | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> "P2OcrIngestion":
        """在 `work_dir` 下建**隔离**账本/预算（绝不触碰共享账本或 GO）。"""
        root = Path(work_dir)
        root.mkdir(parents=True, exist_ok=True)
        ledger_path = root / "p2-ocr-ledger.jsonl"
        budget_path = root / "p2-ocr-budget.json"
        ledger_path.write_text(
            json.dumps(
                {
                    "event": "historical_import",
                    "accounted_cny": float(historical_cny),
                    "provider_billed_cny": None,
                    "note": "P2-T204 isolated OCR ledger (mock-only; not the shared ledger)",
                },
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        budget_path.write_text(
            json.dumps(
                {
                    "limit_cny": float(limit_cny),
                    "historical_conservative_accounted_cny": float(historical_cny),
                    "stages": {stage: float(stage_limit_cny)},
                    "note": "P2-T204 isolated OCR budget (mock-only; not the shared budget)",
                },
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        ledger = OcrCostCenterBudgetLedger(
            ledger_path,
            budget_path,
            stage=stage,
            stage_limit_cny=float(stage_limit_cny),
            max_requests=int(max_requests),
        )
        return cls(
            plan,
            transcripts=transcripts,
            ledger=ledger,
            cache_ttl_seconds=cache_ttl_seconds,
            max_calls=max_calls,
            now=now,
        )

    # ---------------------------------------------------------------- 属性
    @property
    def gateway(self) -> Any:
        """注入 `run_one_job(ocr=...)` / `create_app(ocr_gateway=...)` 的网关。"""
        return self._gateway

    @property
    def uses_mock_transport(self) -> bool:
        """真实 `TencentOCRClient` 的传输层必须是本模块的替身（结构性的 0 出网证据）。"""
        return isinstance(getattr(self._client, "_transport", None), MockOcrTransport)

    @property
    def stopped(self) -> bool:
        return self._stopped

    @property
    def stop_code(self) -> str | None:
        return self._stop_code

    @property
    def receipts(self) -> tuple[OcrPageReceipt, ...]:
        with self._lock:
            return tuple(self._receipts)

    def receipts_for(self, run_id: str) -> tuple[OcrPageReceipt, ...]:
        with self._lock:
            return tuple(item for item in self._receipts if item.run_id == run_id)

    @property
    def runs(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            return {run_id: dict(meta) for run_id, meta in self._runs.items()}

    @property
    def bindings(self) -> tuple[OcrSourceBinding, ...]:
        with self._lock:
            return tuple(self._bindings_by_scope.values())

    def _budgeted_for_run(self) -> BudgetedOCRGateway:
        if self._budgeted is None:
            self._budgeted = BudgetedOCRGateway(
                self._client,
                ledger=self.ledger,
                max_calls=self._max_calls,
                max_tiles_per_page=self._max_tiles_per_page,
                attempts=CONTROLLED_OCR_MAX_ATTEMPTS,
            )
        return self._budgeted

    def ledger_events(self) -> list[dict[str, Any]]:
        path = Path(self.ledger.ledger_path)
        if not path.exists():
            return []
        rows: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            text = line.strip()
            if not text:
                continue
            try:
                event = json.loads(text)
            except ValueError:
                continue
            if isinstance(event, dict):
                rows.append(event)
        return rows

    def ledger_summary(self) -> dict[str, Any]:
        return self.ledger.summary().as_dict()

    # ---------------------------------------------------------------- 绑定与运行
    def bind(self, document_key: str, *, document_id: object, version_id: object) -> OcrSourceBinding:
        """把服务端可信 document/version 绑定到计划资料；返回来源锚绑定。"""
        document = self.plan.by_key.get(str(document_key))
        if document is None:
            raise ValueError(f"{document_key} 不在 OCR 导入计划里")
        binding = OcrSourceBinding(
            document_key=document.document_key,
            document_id=str(document_id),
            version_id=str(version_id),
            plan=document,
        )
        with self._lock:
            existing = self._version_keys.get(binding.version_id)
            if existing is not None and existing != binding.document_key:
                raise ValueError("同一 version 不能绑定到不同资料")
            self._version_keys[binding.version_id] = binding.document_key
            self._bindings_by_scope[binding.source_scope] = binding
            bucket = self._bindings_by_key.setdefault(binding.document_key, [])
            bucket[:] = [item for item in bucket if item.version_id != binding.version_id] + [binding]
        return binding

    def binding_for_version(self, document_id: object, version_id: object) -> OcrSourceBinding | None:
        scope = make_ocr_source_scope(str(document_id), str(version_id))
        with self._lock:
            return self._bindings_by_scope.get(scope)

    def run_job(
        self,
        db: Any,
        store: Any,
        *,
        document_key: str,
        document_id: object,
        version_id: object,
    ) -> JobRunResult:
        """绑定身份后跑一次真实 worker（OCR 走本模块网关，一次 attempt）。"""
        binding = self.bind(document_key, document_id=document_id, version_id=version_id)
        run_id = _new_run_id()
        with self._lock:
            # 停止态是 **run 级** 的：新的一次显式 run 重新开始计页/计次；是否在上一轮失败后
            # 继续跑下一份资料由调用方决定（T206 在首个失败后不再启动新 run）。
            self._stopped = False
            self._stop_code = None
            self._page_calls.clear()
            self._doc_calls.clear()
            self._budgeted = None
            self._current_run = run_id
            self._runs[run_id] = {
                "run_id": run_id,
                "document_key": binding.document_key,
                "document_id": binding.document_id,
                "version_id": binding.version_id,
                "source_scope": binding.source_scope,
                "started_at": _iso(self._now()),
            }
            mark = len(self.transport.requests)
        try:
            result = run_one_job(
                db,
                store,
                ocr=self._gateway,
                ocr_options={"max_attempts": CONTROLLED_OCR_MAX_ATTEMPTS},
            )
        finally:
            with self._lock:
                self._run_marks[run_id] = (mark, len(self.transport.requests))
                self._runs[run_id]["finished_at"] = _iso(self._now())
                self._runs[run_id]["requests"] = len(self.transport.requests) - mark
        with self._lock:
            self._runs[run_id]["job_state"] = str(getattr(result, "state", ""))
            self._runs[run_id]["error_code"] = getattr(result, "error_code", None)
        return result

    def cancel_run(self, run_id: str | None = None) -> None:
        """本地停止后续页（取消/删除场景的显式收尾；不写产品状态）。"""
        with self._lock:
            if run_id is not None and self._current_run not in (None, run_id):
                return
            self._stopped = True
            self._stop_code = "OCR_RUN_CANCELLED"

    # ---------------------------------------------------------------- 网关实现
    def recognize(self, page: OCRInput, *, mode: OCRMode) -> OCRPageResult:
        if not isinstance(page, OCRInput):
            raise OcrIngestionError(OCR_SOURCE_UNBOUND, "OCR 输入类型非法，拒绝（未预留未发送）")
        if mode not in _PRICE_BY_MODE:
            raise OcrIngestionError(OCR_SOURCE_UNBOUND, "OCR 模式非法，拒绝（未预留未发送）")
        binding = self._binding_for_page(page)
        identity = OcrCallIdentity.of(
            document_id=binding.document_id,
            version_id=binding.version_id,
            page=int(page.page),
            mode=str(mode),
            content=bytes(page.content or b""),
        )
        if identity.source_scope != page.source_scope:
            raise OcrIngestionError(OCR_SOURCE_UNBOUND, "OCR 来源锚与绑定身份不一致，拒绝")
        if self._stopped:
            raise OcrIngestionError(OCR_INGESTION_STOPPED, "受控 OCR 已停止，拒绝后续页（未预留未发送）")
        if int(identity.page) not in binding.plan.planned_pages:
            # 计划外的页一律拒绝，即使缓存里恰好有同页条目（不拿缓存绕开计划）。
            raise OcrIngestionError(
                OCR_PAGE_NOT_PLANNED,
                f"页号 {int(identity.page)} 不在计划页 {list(binding.plan.planned_pages)} 内，拒绝",
            )
        decision = self.cache.lookup(identity, now=self._now())
        if decision.hit and decision.entry is not None:
            receipt = OcrPageReceipt(
                run_id=self._active_run(),
                document_key=binding.document_key,
                identity=identity,
                status="succeeded",
                cache=CACHE_HIT,
                bound_cny=identity.bound_cny,
                charged_cny=0.0,
                provider_request_id=decision.entry.provider_request_id,
                admission="cache_hit",
            )
            self._record(receipt)
            return decision.entry.result()
        cache_state = CACHE_MISS if decision.status == CACHE_MISS else f"{CACHE_REJECTED}:{decision.reason}"
        self._check_caps(binding, identity)
        transcript = self._transcripts[binding.document_key]
        started = time.monotonic()
        before = len(self.ledger_events())
        with self._lock:
            self._page_calls[(identity.source_scope, int(page.page))] = (
                self._page_calls.get((identity.source_scope, int(page.page)), 0) + 1
            )
            self._doc_calls[identity.source_scope] = self._doc_calls.get(identity.source_scope, 0) + 1
        try:
            with self.transport.expected(identity=identity, transcript=transcript):
                result = self._budgeted_for_run().recognize(page, mode=mode)
        except OCRError as exc:
            self._finish_failure(
                binding,
                identity,
                status="failed" if exc.code != "OCR_BUDGET_REFUSED" else "refused",
                cache=cache_state,
                error_code=exc.code,
                before=before,
                elapsed_ms=_elapsed_ms(started),
            )
            raise
        attribution = self._attribute(before, identity)
        elapsed = _elapsed_ms(started)
        if attribution["mismatch"]:
            self._stop(OCR_LEDGER_BINDING_MISMATCH)
            self._record(
                OcrPageReceipt(
                    run_id=self._active_run(),
                    document_key=binding.document_key,
                    identity=identity,
                    status="failed",
                    cache=cache_state,
                    bound_cny=identity.bound_cny,
                    charged_cny=attribution["charged_cny"],
                    reservation_id=attribution["reservation_id"],
                    ledger_request_sha256=attribution["ledger_request_sha256"],
                    provider_request_id=result.provider_request_id,
                    error_code=OCR_LEDGER_BINDING_MISMATCH,
                    elapsed_ms=elapsed,
                )
            )
            raise OcrIngestionError(OCR_LEDGER_BINDING_MISMATCH, "OCR 账本归属与本次身份不一致，停止")
        usage_missing = not str(result.provider_request_id or "").strip()
        empty_result = not result.text.strip() and not result.table_rows
        if usage_missing or empty_result:
            code = OCR_USAGE_MISSING if usage_missing else OCR_EMPTY_RESULT
            self._stop(code)
            self._record(
                OcrPageReceipt(
                    run_id=self._active_run(),
                    document_key=binding.document_key,
                    identity=identity,
                    status="invalid_output",
                    cache=cache_state,
                    bound_cny=identity.bound_cny,
                    charged_cny=attribution["charged_cny"],
                    reservation_id=attribution["reservation_id"],
                    ledger_request_sha256=attribution["ledger_request_sha256"],
                    provider_request_id=result.provider_request_id,
                    error_code=code,
                    elapsed_ms=elapsed,
                )
            )
            raise OcrIngestionError(code, "OCR 结果缺 usage 或为空片段，不得记成功（已停止后续页）")
        with self._lock:
            self._observed[identity.key] = result
        self._record(
            OcrPageReceipt(
                run_id=self._active_run(),
                document_key=binding.document_key,
                identity=identity,
                status="succeeded",
                cache=cache_state,
                bound_cny=identity.bound_cny,
                charged_cny=attribution["charged_cny"],
                reservation_id=attribution["reservation_id"],
                ledger_request_sha256=attribution["ledger_request_sha256"],
                provider_request_id=result.provider_request_id,
                elapsed_ms=elapsed,
            )
        )
        return result

    # ---------------------------------------------------------------- 内部
    def _active_run(self) -> str:
        with self._lock:
            return str(self._current_run or "-")

    def _record(self, receipt: OcrPageReceipt) -> None:
        with self._lock:
            self._receipts.append(receipt)

    def _stop(self, code: str) -> None:
        with self._lock:
            self._stopped = True
            self._stop_code = code

    def _binding_for_page(self, page: OCRInput) -> OcrSourceBinding:
        scope = page.source_scope
        if not isinstance(scope, str) or not scope:
            raise OcrIngestionError(OCR_SOURCE_UNBOUND, "OCR 缺少可信来源锚，拒绝（未预留未发送）")
        with self._lock:
            binding = self._bindings_by_scope.get(scope)
        if binding is None:
            raise OcrIngestionError(OCR_SOURCE_UNBOUND, "OCR 来源锚未登记，拒绝（未预留未发送）")
        return binding

    def _check_caps(self, binding: OcrSourceBinding, identity: OcrCallIdentity) -> None:
        page = int(identity.page)
        with self._lock:
            page_calls = self._page_calls.get((identity.source_scope, page), 0)
            doc_calls = self._doc_calls.get(identity.source_scope, 0)
        if page_calls >= int(binding.plan.tiles_per_page):
            raise OcrIngestionError(
                OCR_PAGE_CALL_LIMIT,
                f"该页已有 {page_calls} 次受控调用（计划每页 {binding.plan.tiles_per_page} 次），拒绝",
            )
        if doc_calls >= int(binding.plan.planned_calls):
            raise OcrIngestionError(
                OCR_PLAN_CALL_LIMIT,
                f"该资料已达计划调用数 {binding.plan.planned_calls}，拒绝继续调用",
            )

    def _finish_failure(
        self,
        binding: OcrSourceBinding,
        identity: OcrCallIdentity,
        *,
        status: str,
        cache: str,
        error_code: str | None,
        before: int,
        elapsed_ms: int,
    ) -> None:
        attribution = self._attribute(before, identity)
        code = OCR_LEDGER_BINDING_MISMATCH if attribution["mismatch"] else error_code
        self._stop(str(code or "OCR_PAGE_FAILED"))
        self._record(
            OcrPageReceipt(
                run_id=self._active_run(),
                document_key=binding.document_key,
                identity=identity,
                status=status,
                cache=cache,
                bound_cny=identity.bound_cny,
                charged_cny=attribution["charged_cny"],
                reservation_id=attribution["reservation_id"],
                ledger_request_sha256=attribution["ledger_request_sha256"],
                error_code=code,
                elapsed_ms=elapsed_ms,
            )
        )

    def _attribute(self, before: int, identity: OcrCallIdentity) -> dict[str, Any]:
        """把本次调用对应到账本行：唯一 reserved + 其 request_sha256 必须等于身份哈希。"""
        rows = self.ledger_events()[int(before) :]
        reserved = [row for row in rows if row.get("event") == "reserved"]
        result: dict[str, Any] = {
            "reservation_id": None,
            "ledger_request_sha256": None,
            "charged_cny": 0.0,
            "mismatch": False,
        }
        if not reserved:
            return result
        if len(reserved) > 1:
            result["mismatch"] = True
            return result
        row = reserved[0]
        reservation_id = str(row.get("reservation_id") or "")
        result["reservation_id"] = reservation_id or None
        result["ledger_request_sha256"] = row.get("request_sha256")
        if row.get("request_sha256") != identity.request_sha256:
            result["mismatch"] = True
        if row.get("cost_center") != OCR_COST_CENTER:
            result["mismatch"] = True
        if row.get("provider") != identity.provider or row.get("model") != identity.model:
            result["mismatch"] = True
        settled = [
            item
            for item in rows
            if item.get("event") == "result" and item.get("reservation_id") == reservation_id
        ]
        if settled:
            result["charged_cny"] = float(settled[-1].get("conservative_charge_cny") or 0.0)
        else:
            result["charged_cny"] = float(row.get("reserve_cny") or 0.0)
        return result

    # ---------------------------------------------------------------- 对账
    def finalize(
        self,
        *,
        document_id: object,
        version_id: object,
        records: Sequence[ProductOcrSuccess],
        run_id: str | None = None,
    ) -> OcrRunSummary:
        """把本轮回执与产品 OCR 审计行对账：缓存准入、检查点复用认证、计划计数。"""
        binding = self.binding_for_version(document_id, version_id)
        if binding is None:
            raise ValueError("该 document/version 没有绑定过 OCR 来源身份")
        with self._lock:
            chosen_run = str(run_id or self._current_run or "-")
            receipts = [item for item in self._receipts if item.run_id == chosen_run]
            mark = self._run_marks.get(chosen_run)
        if mark is None:  # 直接调用网关（无 run_job）时按本 version 的累计请求记账
            mark = (
                0,
                sum(
                    1
                    for row in self.transport.requests
                    if row.get("version_id") == binding.version_id
                ),
            )
        records_by_page: dict[int, dict[str, ProductOcrSuccess]] = {}
        for record in records:
            if (
                record.document_id != binding.document_id
                or record.version_id != binding.version_id
                or record.state != "succeeded"
            ):
                continue
            records_by_page.setdefault(int(record.page), {})[record.mode] = record
        by_page: dict[int, list[OcrPageReceipt]] = {}
        for receipt in receipts:
            by_page.setdefault(int(receipt.identity.page), []).append(receipt)
        rows: list[dict[str, Any]] = []
        failed_pages: list[int] = []
        missing_pages: list[int] = []
        cache_hits = 0
        reuses = 0
        charged = 0.0
        bound = 0.0
        for page in binding.plan.planned_pages:
            page_receipts = by_page.get(page, [])
            last = page_receipts[-1] if page_receipts else None
            record: ProductOcrSuccess | None = None
            candidates = records_by_page.get(page) or {}
            if last is not None:
                record = candidates.get(last.identity.mode)
            elif candidates:
                record = candidates.get(binding.plan.expected_mode) or next(iter(candidates.values()))
            price = _PRICE_BY_MODE[last.identity.mode] if last is not None else None
            if last is not None:
                charged += float(last.charged_cny)
                bound += float(last.bound_cny)
            if last is not None and last.cache_hit:
                cache_hits += 1
                rows.append(
                    {
                        "page": page,
                        "source": "cache_hit",
                        "mode": last.identity.mode,
                        "charged_cny": round(float(last.charged_cny), 8),
                        "bound_cny": round(float(last.bound_cny), 8),
                        "admission": "cache_hit",
                    }
                )
                continue
            if last is not None and last.succeeded:
                admission = self._admit(binding, last, record)
                rows.append(
                    {
                        "page": page,
                        "source": "provider_call",
                        "mode": last.identity.mode,
                        "provider_request_id": last.provider_request_id,
                        "reservation_id": last.reservation_id,
                        "charged_cny": round(float(last.charged_cny), 8),
                        "bound_cny": round(float(last.bound_cny), 8),
                        "admission": admission,
                    }
                )
                continue
            if last is not None:
                failed_pages.append(page)
                rows.append(
                    {
                        "page": page,
                        "source": "failed",
                        "mode": last.identity.mode,
                        "status": last.status,
                        "error_code": last.error_code,
                        "charged_cny": round(float(last.charged_cny), 8),
                        "bound_cny": round(float(last.bound_cny), 8),
                    }
                )
                continue
            if record is not None:
                certified = bool(record.has_usage and record.input_sha256)
                if certified:
                    reuses += 1
                    bound += _PRICE_BY_MODE.get(record.mode, 0.0)
                rows.append(
                    {
                        "page": page,
                        "source": "product_checkpoint",
                        "mode": record.mode,
                        "record_id": record.record_id,
                        "provider_request_id": record.provider_request_id,
                        "input_sha256": record.input_sha256,
                        "certified": certified,
                        "charged_cny": 0.0,
                        "bound_cny": round(_PRICE_BY_MODE.get(record.mode, 0.0), 8),
                    }
                )
                continue
            missing_pages.append(page)
            rows.append({"page": page, "source": "missing"})
        return OcrRunSummary(
            run_id=str(chosen_run),
            document_key=binding.document_key,
            document_id=binding.document_id,
            version_id=binding.version_id,
            planned_calls=int(binding.plan.planned_calls),
            planned_pages=binding.plan.planned_pages,
            attempts=len(receipts),
            provider_requests=int(mark[1]) - int(mark[0]),
            cache_hits=cache_hits,
            product_checkpoint_reuses=reuses,
            failed_pages=tuple(failed_pages),
            missing_pages=tuple(missing_pages),
            charged_cny=round(charged, 8),
            bound_cny=round(bound, 8),
            pages=tuple(rows),
        )

    def _admit(
        self,
        binding: OcrSourceBinding,
        receipt: OcrPageReceipt,
        record: ProductOcrSuccess | None,
    ) -> str:
        if record is None:
            return f"rejected:{CACHE_PROVENANCE_MISSING}"
        if record.input_sha256 != receipt.identity.input_sha256:
            return f"rejected:{CACHE_INPUT_HASH_MISMATCH}"
        if not record.has_usage:
            return f"rejected:{CACHE_PROVENANCE_MISSING}"
        with self._lock:
            observed = self._observed.get(receipt.identity.key)
        if observed is None:
            return f"rejected:{CACHE_PROVENANCE_MISSING}"
        self.cache.admit(receipt.identity, observed, product_record_id=record.record_id)
        return "admitted"


def _transcript_map(
    transcripts: Mapping[str, OcrTranscript] | Sequence[OcrTranscript],
) -> dict[str, OcrTranscript]:
    if isinstance(transcripts, Mapping):
        items = dict(transcripts)
    else:
        items = {item.document_key: item for item in transcripts}
    result: dict[str, OcrTranscript] = {}
    for key, transcript in items.items():
        if not isinstance(transcript, OcrTranscript):
            raise ValueError("transcripts 只接受 OcrTranscript")
        if str(key) != transcript.document_key:
            raise ValueError("transcripts 的键必须是 OcrTranscript.document_key")
        result[str(key)] = transcript
    return result


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def _new_run_id() -> str:
    import uuid

    return uuid.uuid4().hex

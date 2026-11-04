"""S2-J2 受控 OCR 预算包装（Mock-only 自测；真实阶段只作受控入口适配层）。

背景（源码实测）：
- ``ingestion/worker.OcrExecutor`` 默认 ``max_attempts=3`` 且可 429 重试；``TencentOCRClient``
  完全未接 ``BudgetLedger``；``provider_request_id`` 会写业务审计表。真实矩阵路线要求
  “每次实际调用在同一真实共享预算门下先预留、固定最高价、仅一次 attempt、最多 13 次、
  每页 tile 上限 1，实际超限在发送前停”。

本模块只包装**调用边界**，不改 ``TencentOCRClient`` 协议，不改 worker/DB：
- 每次 ``recognize``：先做受控上界检查（总次数/每页 tile/已停机）→ `ledger.reserve`
  （kind=ocr、text 0.5 元/次、table 0.15 元/次，不传 settlement_policy：OCR 固定价不参与
  usage 释放）→ 发送前 `recheck_reservation`（同一 GO/预算门）→ **只调用 inner 一次**；
- 成功：旧 ``settle``（charge=max(预留, 固定价)=固定价，``provider_billed_cny=null``），
  供应商 request_id/错误码经 J2 白名单收敛后记录；
- 失败/超时/中断：全额保留（旧 settle 或未结算保留），并置 stopped，宁可停不可重试；
- 上界/账本拒绝一律在**预留与发送之前**抛 ``OCRBudgetRefused``（稳定 code），不产生 HTTP。

边界：本模块不读环境、不发真实网络（inner 自带官方域名校验/签名）；不打印任何凭据或
图片内容；不修改真实账本/GO；只接受构造时注入的隔离账本（由正式执行入口从 LiveGate 构造）。
"""

from __future__ import annotations

import hashlib
import threading
import time
from decimal import Decimal
from typing import Any

from ..rag.budget import BudgetLedger, BudgetLedgerInvalid
from ..rag.controlled_usage import safe_error_code, safe_request_id
from ..rag.errors import BudgetError
from .types import (
    OCRError,
    OCRGateway,
    OCRInput,
    OCRMode,
    OCRPageResult,
    OCRUnavailable,
    is_valid_ocr_source_scope,
)

__all__ = [
    "BudgetedOCRGateway",
    "OCRBudgetRefused",
    "OCR_TABLE_PRICE_CNY",
    "OCR_TEXT_PRICE_CNY",
    "LEGACY_SOURCE_SCOPE",
]

OCR_PROVIDER = "tencent"
OCR_MODEL_TEXT = "GeneralAccurateOCR"
OCR_MODEL_TABLE = "RecognizeTableAccurateOCR"
OCR_TEXT_PRICE_CNY = Decimal("0.5")
OCR_TABLE_PRICE_CNY = Decimal("0.15")
CONTROLLED_OCR_MAX_CALLS = 13
CONTROLLED_OCR_MAX_TILES_PER_PAGE = 1
CONTROLLED_OCR_ATTEMPTS = 1
# 无来源的旧调用（历史测试/旧工具直调）使用固定兼容锚：**不静默随机生成 scope**，
# 仍受同一页 tile 上限与全局 calls 上限；正式生产路径由 OcrExecutor 写入可信来源锚。
LEGACY_SOURCE_SCOPE = "legacy-no-source"



class OCRBudgetRefused(OCRError):
    """受控上界/账本/发送前复核拒绝：本次未发送任何 HTTP。"""

    code = "OCR_BUDGET_REFUSED"
    retryable = False


def _price(value: Any, label: str) -> Decimal:
    if isinstance(value, bool):
        raise ValueError(f"{label} 必须是十进制数字")
    try:
        price = Decimal(str(value))
    except Exception:  # noqa: BLE001 - 构造期参数非法
        raise ValueError(f"{label} 必须是十进制数字") from None
    if not price.is_finite() or price <= 0:
        raise ValueError(f"{label} 必须是有限正数")
    return price


def _plain_int(value: Any, label: str, *, minimum: int, maximum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{label} 必须是整数")
    if value < minimum:
        raise ValueError(f"{label} 低于最小值")
    if maximum is not None and value > maximum:
        raise ValueError(f"{label} 超过最大值")
    return int(value)


class BudgetedOCRGateway:
    """OCRGateway 的预算/授权边界包装；只接受构造时显式的受控上界。"""

    def __init__(
        self,
        inner: OCRGateway,
        *,
        ledger: BudgetLedger,
        max_calls: int = CONTROLLED_OCR_MAX_CALLS,
        max_tiles_per_page: int = CONTROLLED_OCR_MAX_TILES_PER_PAGE,
        attempts: int = CONTROLLED_OCR_ATTEMPTS,
        text_price_cny: Any = OCR_TEXT_PRICE_CNY,
        table_price_cny: Any = OCR_TABLE_PRICE_CNY,
        model_prefix: str = "",
    ) -> None:
        if not hasattr(inner, "recognize"):
            raise ValueError("BudgetedOCRGateway 需要 OCRGateway 实例")
        if not isinstance(ledger, BudgetLedger):
            raise ValueError("BudgetedOCRGateway 需要隔离的 BudgetLedger")
        self._inner = inner
        self._ledger = ledger
        self._max_calls = _plain_int(
            max_calls, "OCR max_calls", minimum=1, maximum=CONTROLLED_OCR_MAX_CALLS
        )
        self._max_tiles_per_page = _plain_int(
            max_tiles_per_page, "OCR max_tiles_per_page", minimum=1, maximum=64
        )
        self._attempts = _plain_int(attempts, "OCR attempts", minimum=1, maximum=3)
        if self._attempts != CONTROLLED_OCR_ATTEMPTS:
            raise ValueError("受控 OCR 路线只允许 attempts=1（禁止重试）")
        self._text_price = _price(text_price_cny, "OCR 文字单价")
        self._table_price = _price(table_price_cny, "OCR 表格单价")
        if self._text_price != OCR_TEXT_PRICE_CNY or self._table_price != OCR_TABLE_PRICE_CNY:
            raise ValueError("受控 OCR 固定最高价必须是 0.5 元/文字、0.15 元/表格")
        self._model_prefix = str(model_prefix or "").strip()
        self._lock = threading.Lock()
        self._calls = 0
        # S2-K-R1A：页 tile 上限按 (可信来源锚, 真实页号) 统计；来源锚由 OcrExecutor 用实际
        # document/version 覆盖写入，解析器/上传文件名不能决定它。无来源旧调用归入固定
        # LEGACY_SOURCE_SCOPE，因此不可能通过换来源绕过同页上限或全局 13 次上限。
        self._tiles_by_source_page: dict[str, dict[int, int]] = {}
        self._stopped = False
        self._stop_code: str | None = None
        self._results: dict[str, int] = {}


    # ---------------------------------------------------------------- 诊断

    def __repr__(self) -> str:  # 不包含凭据
        return (
            f"BudgetedOCRGateway(max_calls={self._max_calls}, "
            f"max_tiles_per_page={self._max_tiles_per_page}, attempts={self._attempts})"
        )

    def stats(self) -> dict[str, Any]:
        with self._lock:
            tiles_by_page: dict[int, int] = {}
            for pages in self._tiles_by_source_page.values():
                for page_number, count in pages.items():
                    tiles_by_page[page_number] = tiles_by_page.get(page_number, 0) + count
            return {
                "calls": self._calls,
                "max_calls": self._max_calls,
                # 旧字段保留为“按页号聚合”的审计口径（同一页号可来自不同来源）；
                # 来源页明细见 tiles_by_source_page，不删除旧字段也不改其含义方向。
                "tiles_by_page": dict(sorted(tiles_by_page.items())),
                "tiles_by_source_page": {
                    scope: dict(sorted(pages.items()))
                    for scope, pages in sorted(self._tiles_by_source_page.items())
                },
                "calls_by_source": {
                    scope: sum(pages.values()) for scope, pages in sorted(self._tiles_by_source_page.items())
                },
                "source_scopes": sorted(self._tiles_by_source_page),
                "legacy_source_scope_used": LEGACY_SOURCE_SCOPE in self._tiles_by_source_page,
                "max_tiles_per_page": self._max_tiles_per_page,
                "attempts": self._attempts,
                "text_price_cny": str(self._text_price),
                "table_price_cny": str(self._table_price),
                "stopped": self._stopped,
                "stop_code": self._stop_code,
                "results": dict(self._results),
            }


    def _stop(self, code: str) -> None:
        self._stopped = True
        self._stop_code = code

    # ---------------------------------------------------------------- OCRGateway

    @staticmethod
    def _source_scope(page: OCRInput) -> str:
        """解析本次请求的可信来源锚：缺省走固定 legacy 兼容锚，非法格式发送前拒绝。"""
        raw = page.source_scope
        if raw is None:
            return LEGACY_SOURCE_SCOPE
        if not is_valid_ocr_source_scope(raw):
            # 不回显原始值（可能是秘密/超长/伪造字符串），只给稳定拒绝语义。
            raise OCRBudgetRefused("OCR 来源身份格式非法，拒绝（未预留未发送）")
        return raw

    def recognize(self, page: OCRInput, *, mode: OCRMode) -> OCRPageResult:
        if not isinstance(page, OCRInput):
            raise OCRBudgetRefused("OCR 输入类型非法，拒绝（未预留未发送）")
        if mode not in ("text", "table"):
            raise OCRBudgetRefused("OCR 模式非法，拒绝（未预留未发送）")
        source_scope = self._source_scope(page)
        page_number = int(page.page)
        price = self._text_price if mode == "text" else self._table_price
        model = (OCR_MODEL_TEXT if mode == "text" else OCR_MODEL_TABLE)
        if self._model_prefix:
            model = f"{self._model_prefix}{model}"
        with self._lock:
            if self._stopped:
                raise OCRBudgetRefused("受控 OCR 路线已停止，拒绝后续调用（未预留未发送）")
            if self._calls >= self._max_calls:
                raise OCRBudgetRefused("OCR 调用数达到受控上限，拒绝（未预留未发送）")
            used = self._tiles_by_source_page.get(source_scope, {}).get(page_number, 0)
            if used >= self._max_tiles_per_page:
                raise OCRBudgetRefused("页面 tile 数达到受控上限，拒绝（未预留未发送）")
        if source_scope == LEGACY_SOURCE_SCOPE:
            # 历史无来源调用的旧公式保持不变（旧事件/旧 request_sha 不改不减）。
            payload = f"ocr-v1|{mode}|{page_number}|".encode("utf-8")
        else:
            # 新公式绑定可信来源、版本（含在来源锚内）、mode、真实页号与图块字节。
            payload = f"ocr-v2|{source_scope}|{mode}|{page_number}|".encode("utf-8")
        request_sha = hashlib.sha256(payload + bytes(page.content or b"")).hexdigest()
        try:
            reservation = self._ledger.reserve(
                kind="ocr",
                provider=OCR_PROVIDER,
                model=model,
                max_cny=float(price),
                request_sha256=request_sha,
            )
        except BudgetError as exc:
            # 预留失败：在发送前拒绝；不把异常原文写进对外消息。
            with self._lock:
                self._stop(safe_error_code("OCR_BUDGET_LEDGER_DENIED"))
            raise OCRBudgetRefused(
                f"OCR 预算/授权门拒绝（{type(exc).__name__}），未发送"
            ) from None
        with self._lock:
            self._calls += 1
            source_pages = self._tiles_by_source_page.setdefault(source_scope, {})
            source_pages[page_number] = source_pages.get(page_number, 0) + 1
        started = time.monotonic()
        try:
            self._ledger.recheck_reservation(reservation)
        except BudgetLedgerInvalid:
            self._settle_failure(reservation, status="failed", error_code="OCR_BUDGET_SEND_REFUSED", started=started)
            with self._lock:
                self._stop("OCR_BUDGET_SEND_REFUSED")
            raise OCRBudgetRefused("OCR 发送前授权/预算复核拒绝，未发送") from None
        if not isinstance(page.content, (bytes, bytearray)) or not page.content:
            self._settle_failure(reservation, status="failed", error_code="OCR_INVALID_INPUT", started=started)
            with self._lock:
                self._stop("OCR_INVALID_INPUT")
            raise OCRBudgetRefused("OCR 图片内容为空，未发送")
        try:
            result = self._inner.recognize(page, mode=mode)  # 唯一一次实际调用；不重试
        except OCRError as exc:
            status = "timeout" if exc.code == "OCR_TIMEOUT" else "failed"
            self._settle_failure(
                reservation,
                status=status,
                error_code=safe_error_code(exc.code),
                request_id=safe_request_id(getattr(exc, "provider_request_id", None)),
                started=started,
            )
            with self._lock:
                self._stop(safe_error_code(exc.code))
            raise
        except BaseException:  # noqa: BLE001 - 中断不吞：预留保持全额（未结算），原样传播
            with self._lock:
                self._stop("PROVIDER_INTERRUPTED")
            raise
        request_id = safe_request_id(getattr(result, "provider_request_id", None))
        self._settle_success(reservation, request_id=request_id, price=price, started=started)
        return result

    # ---------------------------------------------------------------- 结算

    def _settle_success(self, reservation: Any, *, request_id: str | None, price: Decimal, started: float) -> None:
        try:
            self._ledger.settle(
                reservation,
                status="succeeded",
                estimated_list_price_cny=float(price),
                http_status=200,
                request_id=request_id,
                elapsed_seconds=time.monotonic() - started,
            )
        except BudgetLedgerInvalid:
            self._stop("OCR_LEDGER_SETTLE_FAILED")
            raise OCRUnavailable("OCR 结算写账失败，停止（占用不清零）") from None
        with self._lock:
            self._results["succeeded"] = self._results.get("succeeded", 0) + 1

    def _settle_failure(
        self,
        reservation: Any,
        *,
        status: str,
        error_code: str,
        started: float,
        request_id: str | None = None,
    ) -> None:
        try:
            self._ledger.settle(
                reservation,
                status=status,
                estimated_list_price_cny=0.0,
                request_id=request_id,
                error_code=safe_error_code(error_code),
                elapsed_seconds=time.monotonic() - started,
            )
        except BudgetLedgerInvalid:
            # 结算写失败不改变“预留已全额占用”的事实：只记录，不清零。
            self._stop("OCR_LEDGER_SETTLE_FAILED")
            return
        with self._lock:
            self._results[status] = self._results.get(status, 0) + 1

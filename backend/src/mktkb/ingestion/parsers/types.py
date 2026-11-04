"""统一解析接口类型：ParsedUnit、ParseServices、ParseLimits 与稳定解析错误。

解析只读取本地文件，不执行文档内容；OCR 只通过注入的 OCRGateway（测试/受控替身），
解析器不能自行指定外部地址或读取密钥。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

from ...providers.types import OCRGateway

FileKind = Literal["docx", "xlsx", "pdf", "png", "jpg", "jpeg"]
SUPPORTED_KINDS = ("xlsx", "docx", "pdf", "png", "jpg", "jpeg")

# 进程内默认限额；运行期由配置覆盖（见 documents.service.UploadLimits）
DEFAULT_EXCEL_MAX_DATA_ROWS = 5000
DEFAULT_PDF_MAX_PAGES = 50
DEFAULT_IMAGE_MAX_PIXELS = 20_000_000
DEFAULT_PDF_RENDER_SCALE = 2.0
DEFAULT_PDF_MAX_PAGE_PIXELS = 20_000_000
DEFAULT_OCR_MAX_IMAGE_BYTES = 4 * 1024 * 1024
DEFAULT_OCR_MAX_TILES = 64


@dataclass(frozen=True)
class ParseLimits:
    excel_max_data_rows: int = DEFAULT_EXCEL_MAX_DATA_ROWS
    pdf_max_pages: int = DEFAULT_PDF_MAX_PAGES
    image_max_pixels: int = DEFAULT_IMAGE_MAX_PIXELS
    pdf_render_scale: float = DEFAULT_PDF_RENDER_SCALE
    pdf_max_page_pixels: int = DEFAULT_PDF_MAX_PAGE_PIXELS
    ocr_max_image_bytes: int = DEFAULT_OCR_MAX_IMAGE_BYTES
    ocr_max_tiles: int = DEFAULT_OCR_MAX_TILES


class ParseError(Exception):
    """解析失败：code 稳定可读，message 面向用户，不含路径、堆栈或文档原文之外的内部细节。"""

    retryable = False

    def __init__(self, message: str, *, code: str = "PARSE_ERROR", retryable: bool | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        if retryable is not None:
            self.retryable = retryable


class ParseLimitError(ParseError):
    """内容超出单文件规则上限；不能截断后标记完整成功。"""

    def __init__(self, message: str, *, code: str = "EXCEL_ROW_LIMIT") -> None:
        super().__init__(message, code=code, retryable=False)


class ParseQuotaExceeded(ParseError):
    """OCR 额度不足：任务 blocked、版本 failed，停止后续自动请求。"""

    def __init__(self, message: str = "OCR 额度不足，任务已暂停") -> None:
        super().__init__(message, code="OCR_QUOTA_UNAVAILABLE", retryable=True)


class ParseAborted(Exception):
    """任务/资料/版本/租约在外部调用前后失效：丢弃本次结果，不写来源或任务状态。"""

    def __init__(self, state: str = "lease_lost") -> None:
        super().__init__(state)
        self.state = state


@dataclass
class ParsedUnit:
    """一个可预览/可检索的来源单元。"""

    kind: str
    locator: dict
    text: str
    fields: dict
    warnings: list[str]
    unit_key: str
    sheet: str | None = None


@dataclass
class ParseServices:
    """解析期服务与输出汇：report 为可变字典，解析器把工作表/页面结果写入其中。"""

    limits: ParseLimits = field(default_factory=ParseLimits)
    report: dict = field(default_factory=dict)
    planned_units: int | None = None
    # T07：OCR 网关（由 worker 包装限流/检查点）与外部调用前后的有效性复核
    ocr: OCRGateway | None = None
    ensure_live: Callable[[], None] | None = None
    # PDF/图片以“页”为处理单元；Excel/Word 仍以来源单元为 completed_pages
    page_total: int | None = None
    pages_done: int = 0
    ocr_attempts: int = 0
    ocr_calls: int = 0
    ocr_reused: int = 0


def ensure_live(services: ParseServices) -> None:
    """解析器统一入口：未注入复核回调时视为有效（仅单元测试直接调用解析器）。"""
    if services.ensure_live is not None:
        services.ensure_live()

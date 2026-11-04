"""解析入口：按文件类型分派到具体解析器（统一 parse_document 协议）。"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from .excel import parse_xlsx
from .image import parse_image
from .pdf import parse_pdf
from .types import (
    ParseAborted,
    ParseError,
    ParseLimitError,
    ParseLimits,
    ParseQuotaExceeded,
    ParsedUnit,
    ParseServices,
)
from .word import parse_docx

__all__ = [
    "PARSERS",
    "ParseAborted",
    "ParseError",
    "ParseLimitError",
    "ParseLimits",
    "ParseQuotaExceeded",
    "ParseServices",
    "ParsedUnit",
    "parse_document",
]

PARSERS = {
    "xlsx": parse_xlsx,
    "docx": parse_docx,
    "pdf": parse_pdf,
    "png": parse_image,
    "jpg": parse_image,
    "jpeg": parse_image,
}


def parse_document(path: Path, kind: str, services: ParseServices) -> Iterator[ParsedUnit]:
    """按类型解析本地文件并逐个产出来源单元；不支持的阶段格式给出稳定错误。"""
    parser = PARSERS.get(kind.lower())
    if parser is None:
        raise ParseError("该阶段暂不支持此文件格式的解析", code="UNSUPPORTED_FILE_TYPE")
    yield from parser(Path(path), kind.lower(), services)

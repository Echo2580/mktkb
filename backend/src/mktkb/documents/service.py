"""T03 文档服务：分块暂存与 SHA-256、OOXML 校验、去重/版本规则、存储、分页预览、受保护原件。

事务边界：
- 完整文件先落盘到暂存区并完成校验，之后才在数据库事务中建立版本与可领取任务；
- 数据库事务失败时删除暂存/已落盘文件，不残留可领取任务；
- 同字节与同名并发由数据库唯一约束兜底，业务层只做友好错误映射与有界重试。
"""

from __future__ import annotations

import hashlib
import os
import time
import uuid
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO

import pypdfium2 as pdfium
from PIL import Image, UnidentifiedImageError
from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from ..errors import (
    ActiveVersionConflict,
    ContentUnavailable,
    ContentUnchanged,
    DocumentNotFound,
    DuplicateContent,
    FileCorrupt,
    FileEncrypted,
    FileHasMacro,
    FileTooLarge,
    ImagePixelLimit,
    InvalidFile,
    InvalidFileType,
    InvalidUpload,
    PdfPageLimit,
    ResourceLimitExceeded,
    SameNameRequiresAction,
    UnsupportedFileType,
    VersionNotFound,
)
from ..ingestion.models import ImportJob
from ..ingestion.parsers.types import ParseLimits
from .models import (
    LIVE_VERSION_STATES,
    READABLE_VERSION_STATES,
    Document,
    DocumentVersion,
    SourceUnit,
    utcnow,
)
from .schemas import (
    DocumentDetail,
    DocumentSummary,
    PreviewResponse,
    SourceUnitPublic,
    UploadResponse,
    VersionSummary,
)

SUPPORTED_SUFFIXES = {"xlsx": "xlsx", "docx": "docx", "pdf": "pdf", "png": "png", "jpg": "jpg", "jpeg": "jpeg"}
OOXML_SUFFIXES = {"xlsx", "docx"}
IMAGE_SUFFIXES = {"png", "jpg", "jpeg"}
OOXML_CONTENT_TYPES = {
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
CONTENT_TYPES = {
    **OOXML_CONTENT_TYPES,
    "pdf": "application/pdf",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
}
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
JPEG_MAGIC = b"\xff\xd8\xff"
CFB_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
CHUNK_SIZE = 1024 * 1024
# 并发写冲突（SQLite 快照/锁）时的有界重试，不隐藏其他数据库错误
WRITE_RETRIES = 3
WRITE_RETRY_SLEEP = 0.05


@dataclass(frozen=True)
class UploadLimits:
    """上传与解压资源预算；默认值来自 Settings，测试可独立构造。"""

    max_upload_bytes: int = 20 * 1024 * 1024
    ooxml_max_members: int = 2000
    ooxml_max_total_uncompressed_bytes: int = 128 * 1024 * 1024
    ooxml_max_member_uncompressed_bytes: int = 64 * 1024 * 1024
    ooxml_max_compression_ratio: float = 100.0
    excel_max_data_rows: int = 5000
    pdf_max_pages: int = 50
    image_max_pixels: int = 20_000_000
    pdf_render_scale: float = 2.0
    pdf_max_page_pixels: int = 20_000_000
    ocr_max_image_bytes: int = 4 * 1024 * 1024
    ocr_max_tiles: int = 64

    @classmethod
    def from_settings(cls, settings) -> "UploadLimits":
        return cls(
            max_upload_bytes=settings.max_upload_bytes,
            ooxml_max_members=settings.ooxml_max_members,
            ooxml_max_total_uncompressed_bytes=settings.ooxml_max_total_uncompressed_bytes,
            ooxml_max_member_uncompressed_bytes=settings.ooxml_max_member_uncompressed_bytes,
            ooxml_max_compression_ratio=settings.ooxml_max_compression_ratio,
            excel_max_data_rows=settings.excel_max_data_rows,
            pdf_max_pages=settings.pdf_max_pages,
            image_max_pixels=settings.image_max_pixels,
            pdf_render_scale=settings.pdf_render_scale,
            pdf_max_page_pixels=settings.pdf_max_page_pixels,
            ocr_max_image_bytes=settings.ocr_max_image_bytes,
            ocr_max_tiles=settings.ocr_max_tiles,
        )

    def to_parse_limits(self) -> ParseLimits:
        return ParseLimits(
            excel_max_data_rows=self.excel_max_data_rows,
            pdf_max_pages=self.pdf_max_pages,
            image_max_pixels=self.image_max_pixels,
            pdf_render_scale=self.pdf_render_scale,
            pdf_max_page_pixels=self.pdf_max_page_pixels,
            ocr_max_image_bytes=self.ocr_max_image_bytes,
            ocr_max_tiles=self.ocr_max_tiles,
        )


@dataclass
class Store:
    """项目专属文件存储：暂存区与原件区分离，路径只由服务端生成。"""

    root: Path
    limits: UploadLimits = field(default_factory=UploadLimits)

    @property
    def staging_dir(self) -> Path:
        return Path(self.root) / "staging"

    @property
    def originals_dir(self) -> Path:
        return Path(self.root) / "originals"

    def ensure_dirs(self) -> None:
        self.staging_dir.mkdir(parents=True, exist_ok=True)
        self.originals_dir.mkdir(parents=True, exist_ok=True)

    def new_staging_path(self) -> Path:
        self.ensure_dirs()
        return self.staging_dir / f"{uuid.uuid4().hex}.part"

    def relative_target(self, version_id: uuid.UUID, kind: str) -> str:
        """随机内部标识 + 已检测类型扩展名；不使用用户文件名。"""
        hex_value = version_id.hex
        return f"originals/{hex_value[:2]}/{hex_value}.{kind}"

    def path_for(self, stored_path: str) -> Path:
        root = Path(self.root).resolve()
        candidate = (root / stored_path).resolve()
        if not candidate.is_relative_to(root):
            raise ValueError("stored path escapes storage root")
        return candidate

    def commit(self, staging: Path, version_id: uuid.UUID, kind: str) -> Path:
        """移动到原件区并返回**绝对**目标路径；失败清理必须使用该路径，不能再用相对字符串。"""
        relative = self.relative_target(version_id, kind)
        target = self.path_for(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staging, target)
        return target

    def restore_moved(self, moved: Path, staging: Path) -> None:
        """把已移入原件区的文件退回暂存区，供有界重试复用；仅在 Store 根内操作。"""
        try:
            moved_path = self._resolve_in_root(moved)
            staging_path = self._resolve_in_root(staging)
            if moved_path is not None and moved_path.is_file():
                staging_path.parent.mkdir(parents=True, exist_ok=True)
                os.replace(moved_path, staging_path)
        except OSError:
            pass

    def _resolve_in_root(self, path: Path | str) -> Path | None:
        """相对路径按 Store 根解析；解析后必须仍在根内，否则返回 None（拒绝越界清理）。"""
        root = Path(self.root).resolve()
        candidate = Path(path)
        if not candidate.is_absolute():
            candidate = root / candidate
        candidate = candidate.resolve()
        if not candidate.is_relative_to(root):
            return None
        return candidate

    def discard(self, path: Path | None) -> None:
        """只清理 Store 根内的文件；相对路径以 Store 根（而非 cwd）为基准。"""
        if path is None:
            return
        candidate = self._resolve_in_root(path)
        if candidate is None:
            return
        try:
            candidate.unlink(missing_ok=True)
        except OSError:
            pass


@dataclass
class UploadInput:
    filename: str
    stream: BinaryIO
    content_type: str | None = None


@dataclass
class UploadReceipt:
    document: Document
    version: DocumentVersion
    job: ImportJob


# ---------------------------------------------------------------- 校验与落盘


def _suffix_of(filename: str) -> str:
    name = (filename or "").strip()
    if "." not in name:
        return ""
    return name.rsplit(".", 1)[1].strip().lower()


def sanitize_filename(raw: str) -> str:
    """用户文件名只用于显示：去掉任何目录成分并限制长度，不参与内部存储路径。"""
    name = (raw or "").strip().replace("\\", "/")
    name = name.rsplit("/", 1)[-1].strip()
    if not name or name in {".", ".."}:
        raise InvalidUpload("文件名不能为空")
    if len(name) > 200:
        raise InvalidUpload("文件名过长（最多 200 字符）")
    return name


def _detect_zip_kind(archive: zipfile.ZipFile) -> str | None:
    names = set(archive.namelist())
    has_excel = "xl/workbook.xml" in names
    has_word = "word/document.xml" in names
    if has_excel and not has_word:
        return "xlsx"
    if has_word and not has_excel:
        return "docx"
    return None


def validate_ooxml(path: Path, suffix: str, limits: UploadLimits) -> str:
    """按真实字节检查 OOXML 容器；返回检测到的类型，失败抛出稳定错误。"""
    try:
        with Path(path).open("rb") as handle:
            head = handle.read(8)
    except OSError:
        raise InvalidFile("文件无法读取") from None
    if head.startswith(CFB_MAGIC):
        raise FileEncrypted()
    if not head.startswith(b"PK"):
        raise InvalidFileType("文件不是可识别的 Office 压缩容器（.xlsx/.docx）")
    try:
        archive = zipfile.ZipFile(path)
    except zipfile.BadZipFile:
        raise FileCorrupt() from None
    with archive:
        infos = [info for info in archive.infolist() if not info.filename.endswith("/")]
        if len(infos) > limits.ooxml_max_members:
            raise ResourceLimitExceeded(f"成员数量超过 {limits.ooxml_max_members}")
        total = 0
        for info in infos:
            size = info.file_size
            compressed = max(info.compress_size, 1)
            if size > limits.ooxml_max_member_uncompressed_bytes:
                raise ResourceLimitExceeded(f"单成员解压后超过 {limits.ooxml_max_member_uncompressed_bytes} 字节")
            if size > 1024 and size / compressed > limits.ooxml_max_compression_ratio:
                raise ResourceLimitExceeded(f"单成员压缩比超过 {limits.ooxml_max_compression_ratio:g}")
            total += size
            if total > limits.ooxml_max_total_uncompressed_bytes:
                raise ResourceLimitExceeded(f"解压总量超过 {limits.ooxml_max_total_uncompressed_bytes} 字节")
        if any(info.filename.lower().endswith("vbaproject.bin") for info in infos):
            raise FileHasMacro()
        try:
            bad_member = archive.testzip()
        except (zipfile.BadZipFile, OSError, EOFError):
            raise FileCorrupt() from None
        if bad_member is not None:
            raise FileCorrupt()
        names = set(archive.namelist())
        if "[Content_Types].xml" not in names:
            raise InvalidFileType("缺少 OOXML 内容类型部件")
        detected = _detect_zip_kind(archive)
        if detected is None:
            raise InvalidFileType("不是可识别的 xlsx/docx 容器")
        if detected != suffix:
            raise InvalidFileType("文件内容类型与扩展名不一致")
        return detected


def validate_pdf(path: Path, limits: UploadLimits) -> str:
    """按真实字节检查 PDF：头部、加密、损坏、页数；不解析正文、不渲染页面。"""
    try:
        with Path(path).open("rb") as handle:
            head = handle.read(1024)
    except OSError:
        raise InvalidFile("文件无法读取") from None
    if not head.lstrip().startswith(b"%PDF-"):
        raise InvalidFileType("文件不是可识别的 PDF")
    try:
        document = pdfium.PdfDocument(str(path))
    except Exception as exc:
        message = str(exc).lower()
        if "password" in message or "encrypted" in message:
            raise FileEncrypted("PDF 已加密，本阶段不支持口令保护的 PDF") from None
        raise FileCorrupt() from None
    try:
        pages = len(document)
    finally:
        document.close()
    if pages <= 0:
        raise FileCorrupt()
    if pages > limits.pdf_max_pages:
        raise PdfPageLimit(limits.pdf_max_pages)
    return "pdf"


def validate_image(path: Path, suffix: str, limits: UploadLimits) -> str:
    """按真实字节检查 PNG/JPEG：内容与扩展名一致、像素上限先于整图解码、可完整解码。"""
    expected = "PNG" if suffix == "png" else "JPEG"
    try:
        with Path(path).open("rb") as handle:
            head = handle.read(8)
    except OSError:
        raise InvalidFile("文件无法读取") from None
    if suffix == "png" and not head.startswith(PNG_MAGIC):
        raise InvalidFileType("文件内容不是 PNG")
    if suffix in {"jpg", "jpeg"} and not head.startswith(JPEG_MAGIC):
        raise InvalidFileType("文件内容不是 JPEG")
    try:
        with Image.open(path) as image:
            if image.format != expected:
                raise InvalidFileType("图片内容与扩展名不一致")
            width, height = image.size
            if width <= 0 or height <= 0:
                raise FileCorrupt()
            if width * height > limits.image_max_pixels:
                raise ImagePixelLimit(limits.image_max_pixels)
            image.verify()
    except (InvalidFileType, ImagePixelLimit, FileCorrupt):
        raise
    except (UnidentifiedImageError, OSError, ValueError):
        raise FileCorrupt() from None
    return suffix


def validate_upload(path: Path, suffix: str, limits: UploadLimits) -> str:
    """按扩展名分派真实内容检查；返回实际检测类型。"""
    suffix = suffix.lower()
    if suffix in OOXML_SUFFIXES:
        return validate_ooxml(path, suffix, limits)
    if suffix == "pdf":
        return validate_pdf(path, limits)
    if suffix in IMAGE_SUFFIXES:
        return validate_image(path, suffix, limits)
    raise UnsupportedFileType()


def media_type_for(file_type: str) -> str:
    return CONTENT_TYPES.get(file_type, "application/octet-stream")


def _write_staging(stream: BinaryIO, store: Store) -> tuple[Path, int, str]:
    """分块读取、计算实际字节与 SHA-256；超过上限立即失败并清理暂存。"""
    staging = store.new_staging_path()
    digest = hashlib.sha256()
    total = 0
    try:
        with staging.open("wb") as sink:
            while True:
                chunk = stream.read(CHUNK_SIZE)
                if not chunk:
                    break
                total += len(chunk)
                if total > store.limits.max_upload_bytes:
                    raise FileTooLarge(store.limits.max_upload_bytes)
                digest.update(chunk)
                sink.write(chunk)
        if total == 0:
            raise InvalidFile("空文件不能作为资料上传")
        return staging, total, digest.hexdigest()
    except BaseException:
        store.discard(staging)
        raise


# ---------------------------------------------------------------- 查询与视图


# 内容已撤销的版本状态：处理报告不得出现在任何摘要出口（详情/列表/上传回执/嵌套 active/latest）
REDACTED_SUMMARY_STATES = ("cancelled", "deleted")


def _version_summary(version: DocumentVersion | None, *, redact_content: bool = False) -> VersionSummary | None:
    if version is None:
        return None
    hidden = redact_content or version.state in REDACTED_SUMMARY_STATES
    return VersionSummary(
        id=version.id,
        number=version.number,
        state=version.state,
        sha256=version.sha256,
        uploaded_at=version.uploaded_at,
        published_at=version.published_at,
        processing_report=None if hidden else version.processing_report,
    )


def latest_version(db: Session, document: Document) -> DocumentVersion | None:
    return db.scalar(
        select(DocumentVersion)
        .where(DocumentVersion.document_id == document.id)
        .order_by(DocumentVersion.number.desc())
        .limit(1)
    )


def active_version(db: Session, document: Document) -> DocumentVersion | None:
    if document.active_version_id is None:
        return None
    version = db.get(DocumentVersion, document.active_version_id)
    if version is not None and version.document_id != document.id:
        return None
    return version


def document_summary(db: Session, document: Document) -> DocumentSummary:
    redact = document.deleted
    return DocumentSummary(
        id=document.id,
        name=document.name,
        file_type=document.file_type,
        active_version=_version_summary(active_version(db, document), redact_content=redact),
        latest_version=_version_summary(latest_version(db, document), redact_content=redact),
        deleted=document.deleted,
        created_at=document.created_at,
        last_published_at=document.last_published_at,
    )


def upload_response(db: Session, receipt: UploadReceipt) -> UploadResponse:
    from ..ingestion.schemas import JobStatus

    return UploadResponse(
        document=document_summary(db, receipt.document),
        version=_version_summary(receipt.version),
        job=JobStatus.from_job(receipt.job),
    )


def get_document(db: Session, document_id: uuid.UUID) -> Document:
    document = db.get(Document, document_id)
    if document is None:
        raise DocumentNotFound()
    return document


def get_version(db: Session, document_id: uuid.UUID, version_id: uuid.UUID) -> tuple[Document, DocumentVersion]:
    document = get_document(db, document_id)
    version = db.get(DocumentVersion, version_id)
    if version is None or version.document_id != document.id:
        raise VersionNotFound()
    return document, version


def list_documents(
    db: Session,
    *,
    q: str | None = None,
    file_type: str | None = None,
    state: str | None = None,
    offset: int = 0,
    limit: int = 20,
) -> tuple[list[Document], int]:
    statement = select(Document).where(Document.deleted.is_(False))
    if q:
        statement = statement.where(Document.name.contains(q))
    if file_type:
        statement = statement.where(Document.file_type == file_type)
    if state:
        if state == "published":
            statement = statement.where(Document.active_version_id.is_not(None))
        else:
            latest_state = (
                select(DocumentVersion.state)
                .where(DocumentVersion.document_id == Document.id)
                .order_by(DocumentVersion.number.desc())
                .limit(1)
                .scalar_subquery()
            )
            statement = statement.where(latest_state == state)
    total = int(db.scalar(select(func.count()).select_from(statement.subquery())) or 0)
    items = list(
        db.scalars(statement.order_by(Document.created_at.desc(), Document.id).offset(offset).limit(limit)).all()
    )
    return items, total


def document_detail(db: Session, document_id: uuid.UUID) -> DocumentDetail:
    from ..ingestion.schemas import JobStatus
    from .lifecycle import get_revision

    document = get_document(db, document_id)
    versions = list(
        db.scalars(
            select(DocumentVersion)
            .where(DocumentVersion.document_id == document.id)
            .order_by(DocumentVersion.number)
        ).all()
    )
    jobs = (
        list(
            db.scalars(
                select(ImportJob)
                .where(ImportJob.version_id.in_([version.id for version in versions]))
                .order_by(ImportJob.created_at, ImportJob.id)
            ).all()
        )
        if versions
        else []
    )
    # 摘要脱敏统一在 _version_summary 内完成（状态/父资料删除均覆盖），避免各出口各写一份
    summaries = [
        summary
        for summary in (
            _version_summary(version, redact_content=document.deleted) for version in versions
        )
        if summary is not None
    ]
    return DocumentDetail(
        document=document_summary(db, document),
        versions=summaries,
        jobs=[JobStatus.from_job(job) for job in jobs],
        revision=get_revision(db),
    )


def _ensure_readable(document: Document, version: DocumentVersion) -> None:
    if document.deleted:
        raise ContentUnavailable("资料已删除，内容不可访问")
    if version.state in {"cancelled", "deleted"}:
        raise ContentUnavailable("该版本已取消或删除，内容不可访问")


def preview(
    db: Session,
    document_id: uuid.UUID,
    version_id: uuid.UUID,
    *,
    offset: int = 0,
    limit: int = 20,
    sheet: str | None = None,
    page: int | None = None,
) -> PreviewResponse:
    document, version = get_version(db, document_id, version_id)
    _ensure_readable(document, version)
    statement = select(SourceUnit).where(SourceUnit.version_id == version.id)
    if sheet is not None:
        statement = statement.where(SourceUnit.sheet == sheet)
    if page is not None:
        statement = statement.where(func.json_extract(SourceUnit.locator, "$.page") == page)
    total = int(db.scalar(select(func.count()).select_from(statement.subquery())) or 0)
    units = list(db.scalars(statement.order_by(SourceUnit.ordinal).offset(offset).limit(limit)).all())
    report = version.processing_report or {
        "sheets": [],
        "quality": {"complete": False, "issues": [{"issue": "not_processed"}]},
    }
    return PreviewResponse(
        items=[
            SourceUnitPublic(
                id=unit.id,
                document_id=unit.document_id,
                version_id=unit.version_id,
                kind=unit.kind,
                locator=unit.locator,
                text=unit.text,
                fields=unit.fields,
                warnings=list(unit.warnings or []),
            )
            for unit in units
        ],
        total=total,
        offset=offset,
        limit=limit,
        report=report,
    )


def resolve_version_file(
    store: Store, db: Session, document_id: uuid.UUID, version_id: uuid.UUID
) -> tuple[Document, DocumentVersion, Path]:
    """受保护原件：路径只来自数据库中的内部相对路径，不接受客户端服务器路径。"""
    document, version = get_version(db, document_id, version_id)
    _ensure_readable(document, version)
    path = store.path_for(version.stored_path)
    if not path.is_file():
        raise ContentUnavailable("原件缺失，内容不可访问")
    return document, version, path


# ---------------------------------------------------------------- 上传主流程


def _same_name_candidates(db: Session, name: str) -> list[dict]:
    documents = list(
        db.scalars(
            select(Document)
            .where(Document.deleted.is_(False), Document.name == name)
            .order_by(Document.created_at)
            .limit(10)
        ).all()
    )
    candidates: list[dict] = []
    for document in documents:
        latest = latest_version(db, document)
        candidates.append(
            {
                "id": str(document.id),
                "name": document.name,
                "file_type": document.file_type,
                "latest_version_number": document.latest_version_number,
                "latest_state": latest.state if latest is not None else None,
            }
        )
    return candidates


def _map_integrity_error(db: Session, exc: IntegrityError, name: str) -> Exception:
    message = str(getattr(exc, "orig", exc))
    if "documents.name_key" in message:
        return SameNameRequiresAction(_same_name_candidates(db, name))
    if "document_versions.sha256" in message:
        return DuplicateContent()
    if "document_versions.number" in message:
        return ActiveVersionConflict("同一资料的版本号分配冲突，请刷新后重试")
    return exc


def stage_upload(
    db: Session,
    store: Store,
    upload: UploadInput,
    *,
    document_id: uuid.UUID | None = None,
    expected_active_version_id: uuid.UUID | None = None,
    allow_same_name: bool = False,
) -> UploadReceipt:
    """完整暂存并校验文件后建立待处理版本与任务；不切换有效版本。"""
    filename = sanitize_filename(upload.filename)
    suffix = _suffix_of(filename)
    if suffix not in SUPPORTED_SUFFIXES:
        raise UnsupportedFileType()
    try:
        stream = upload.stream
        if hasattr(stream, "seek") and not getattr(stream, "closed", False):
            stream.seek(0)
        staging, size, sha256 = _write_staging(stream, store)
    except (FileTooLarge, InvalidFile):
        raise
    try:
        kind = validate_upload(staging, suffix, store.limits)
    except BaseException:
        store.discard(staging)
        raise

    try:
        last_error: OperationalError | None = None
        for attempt in range(WRITE_RETRIES):
            try:
                return _create_pending_version(
                    db,
                    store,
                    staging,
                    filename=filename,
                    kind=kind,
                    size=size,
                    sha256=sha256,
                    document_id=document_id,
                    expected_active_version_id=expected_active_version_id,
                    allow_same_name=allow_same_name,
                )
            except OperationalError as exc:
                db.rollback()
                last_error = exc
                if "locked" not in str(exc).lower() and "busy" not in str(exc).lower():
                    raise
                if attempt == WRITE_RETRIES - 1:
                    raise
                time.sleep(WRITE_RETRY_SLEEP * (attempt + 1))
        assert last_error is not None
        raise last_error
    except BaseException:
        store.discard(staging)
        raise


def _create_pending_version(
    db: Session,
    store: Store,
    staging: Path,
    *,
    filename: str,
    kind: str,
    size: int,
    sha256: str,
    document_id: uuid.UUID | None,
    expected_active_version_id: uuid.UUID | None,
    allow_same_name: bool,
) -> UploadReceipt:
    document: Document | None = None
    if document_id is not None:
        document = db.get(Document, document_id)
        if document is None or document.deleted:
            raise DocumentNotFound()
        if expected_active_version_id is not None and document.active_version_id != expected_active_version_id:
            raise ActiveVersionConflict()
    else:
        candidates = _same_name_candidates(db, filename)
        if candidates and not allow_same_name:
            raise SameNameRequiresAction(candidates)

    existing = db.scalar(
        select(DocumentVersion)
        .join(Document, Document.id == DocumentVersion.document_id)
        .where(
            DocumentVersion.sha256 == sha256,
            DocumentVersion.state.in_(LIVE_VERSION_STATES),
            Document.deleted.is_(False),
        )
        .limit(1)
    )
    if existing is not None:
        if (
            document is not None
            and existing.document_id == document.id
            and document.active_version_id is not None
            and existing.id == document.active_version_id
        ):
            raise ContentUnchanged()
        raise DuplicateContent(document_id=existing.document_id, version_id=existing.id)

    now = utcnow()
    version_id = uuid.uuid4()
    job_id = uuid.uuid4()
    new_document = document is None
    if new_document:
        document = Document(
            id=uuid.uuid4(),
            name=filename,
            name_key=None if allow_same_name else filename,
            file_type=kind,
            active_version_id=None,
            latest_version_number=1,
            deleted=False,
            created_at=now,
        )
        number = 1
    else:
        number = int(
            db.execute(
                update(Document)
                .where(Document.id == document.id)
                .values(latest_version_number=Document.latest_version_number + 1)
                .returning(Document.latest_version_number)
            ).scalar_one()
        )
        document.latest_version_number = number

    stored_path = store.relative_target(version_id, kind)
    version = DocumentVersion(
        id=version_id,
        document_id=document.id,
        number=number,
        state="queued",
        sha256=sha256,
        size_bytes=size,
        stored_path=stored_path,
        uploaded_at=now,
    )
    job = ImportJob(
        id=job_id,
        version_id=version_id,
        state="queued",
        stage="queued",
        created_at=now,
        updated_at=now,
    )

    moved: Path | None = None
    try:
        # 显式按外键顺序 flush：先资料、再版本、最后任务；避免 SQLAlchemy 未建模依赖导致插序错误
        if new_document:
            db.add(document)
            db.flush()
        db.add(version)
        db.flush()
        db.add(job)
        db.flush()
        moved = store.commit(staging, version_id, kind)
        db.commit()
    except OperationalError:
        # 有界重试路径：数据库锁冲突不是业务失败。把已移动的文件退回暂存区，
        # 让下一次重试继续使用同一份完整文件，不能消费掉 staging 后伪成功或直接崩溃。
        db.rollback()
        if moved is not None:
            store.restore_moved(moved, staging)
        raise
    except IntegrityError as exc:
        db.rollback()
        store.discard(moved if moved is not None else staging)
        raise _map_integrity_error(db, exc, filename) from None
    except BaseException:
        db.rollback()
        store.discard(moved if moved is not None else staging)
        raise
    return UploadReceipt(document=document, version=version, job=job)


def recorded_storage_paths(db: Session) -> set[str]:
    """数据库引用的内部存储相对路径，供受控清理流程比对。"""
    return set(db.scalars(select(DocumentVersion.stored_path)).all())


def find_orphan_files(store: Store, recorded_paths: set[str]) -> list[Path]:
    """识别本项目存储目录内未被数据库引用的遗留文件（崩溃恢复/受控清理用）。

    只在 store.root 内遍历，不触及 fixtures、证据目录或其他项目；本函数不删除任何文件。
    """
    store.ensure_dirs()
    orphans: list[Path] = []
    for base in (store.staging_dir, store.originals_dir):
        for path in sorted(base.rglob("*")):
            if path.is_file():
                relative = path.relative_to(store.root).as_posix()
                if relative not in recorded_paths:
                    orphans.append(path)
    return orphans


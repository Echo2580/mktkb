"""稳定业务错误与安全响应。响应体不包含路径、堆栈、SQL 或凭据。"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("mktkb.errors")

HTTP_ERROR_MESSAGES = {
    400: ("BAD_REQUEST", "请求无法处理"),
    401: ("AUTH_REQUIRED", "需要登录"),
    403: ("FORBIDDEN", "没有执行该操作的权限"),
    404: ("NOT_FOUND", "资源不存在"),
    405: ("METHOD_NOT_ALLOWED", "请求方法不允许"),
    409: ("CONFLICT", "请求与当前状态冲突"),
    413: ("PAYLOAD_TOO_LARGE", "请求内容过大"),
    415: ("UNSUPPORTED_MEDIA_TYPE", "不支持的内容类型"),
    422: ("VALIDATION_ERROR", "请求参数不合法"),
    429: ("RATE_LIMITED", "请求过于频繁"),
}


@dataclass
class ApiError(Exception):
    """业务错误：code 为稳定错误码，message 面向用户且不含内部细节。"""

    code: str
    message: str
    status_code: int
    retryable: bool = False
    details: dict | None = field(default=None)

    def __str__(self) -> str:  # 日志里只出现错误码，不带请求内容
        return f"{self.code}"


class InvalidCredentials(ApiError):
    def __init__(self) -> None:
        super().__init__("INVALID_CREDENTIALS", "用户名或密码不正确", 401)


class AuthRequired(ApiError):
    def __init__(self, code: str = "AUTH_REQUIRED", message: str = "需要登录") -> None:
        super().__init__(code, message, 401)


class SessionExpired(ApiError):
    def __init__(self) -> None:
        super().__init__("SESSION_EXPIRED", "登录已过期，请重新登录", 401)


class CsrfInvalid(ApiError):
    def __init__(self) -> None:
        super().__init__("CSRF_INVALID", "请求校验失败，请刷新后重试", 403)


class OriginRejected(ApiError):
    def __init__(self) -> None:
        super().__init__("ORIGIN_REJECTED", "请求来源不受信任", 403)


class RoleRequired(ApiError):
    def __init__(self, role: str) -> None:
        super().__init__("ROLE_REQUIRED", "没有执行该操作的权限", 403, details={"required_role": role})


class InvalidRequest(ApiError):
    def __init__(self, message: str = "请求参数不合法") -> None:
        super().__init__("INVALID_REQUEST", message, 400)


# ---- T03 上传/任务稳定错误：message 面向用户，不回显路径、SQL、原始字节或秘密 ----


class NotFound(ApiError):
    def __init__(self, code: str = "NOT_FOUND", message: str = "资源不存在") -> None:
        super().__init__(code, message, 404)


class DocumentNotFound(NotFound):
    def __init__(self) -> None:
        super().__init__("DOCUMENT_NOT_FOUND", "资料不存在")


class VersionNotFound(NotFound):
    def __init__(self) -> None:
        super().__init__("VERSION_NOT_FOUND", "资料版本不存在或不属于该资料")


class JobNotFound(NotFound):
    def __init__(self) -> None:
        super().__init__("JOB_NOT_FOUND", "处理任务不存在")


class FileTooLarge(ApiError):
    def __init__(self, max_bytes: int) -> None:
        super().__init__(
            "FILE_TOO_LARGE",
            f"文件超过单文件 {max_bytes} 字节上限",
            413,
            details={"max_bytes": max_bytes},
        )


class UnsupportedFileType(ApiError):
    def __init__(self, message: str = "该阶段暂不支持此格式（仅支持 .xlsx/.docx）") -> None:
        super().__init__("UNSUPPORTED_FILE_TYPE", message, 415)


class FileEncrypted(ApiError):
    def __init__(self, message: str = "文件已加密，本阶段不支持口令保护的文件") -> None:
        super().__init__("FILE_ENCRYPTED", message, 415)


class PdfPageLimit(ApiError):
    def __init__(self, max_pages: int) -> None:
        super().__init__(
            "PDF_PAGE_LIMIT",
            f"PDF 页数超过 {max_pages} 页上限",
            422,
            details={"max_pages": max_pages},
        )


class ImagePixelLimit(ApiError):
    def __init__(self, max_pixels: int) -> None:
        super().__init__(
            "IMAGE_PIXEL_LIMIT",
            f"图片像素超过 {max_pixels} 上限",
            422,
            details={"max_pixels": max_pixels},
        )


class FileHasMacro(ApiError):
    def __init__(self) -> None:
        super().__init__("FILE_HAS_MACRO", "含宏的 Office 文件不被支持", 415)


class InvalidFileType(ApiError):
    def __init__(self, message: str = "文件内容与扩展名不符，或不是有效的 Office 文件") -> None:
        super().__init__("INVALID_FILE_TYPE", message, 415)


class InvalidFile(ApiError):
    def __init__(self, message: str = "文件无法通过格式检查", code: str = "INVALID_FILE") -> None:
        super().__init__(code, message, 422)


class FileCorrupt(ApiError):
    def __init__(self) -> None:
        super().__init__("FILE_CORRUPT", "文件已损坏或不是完整的 Office 容器", 422)


class ResourceLimitExceeded(ApiError):
    def __init__(self, reason: str) -> None:
        super().__init__("OOXML_RESOURCE_LIMIT", f"文件解压资源超出预算：{reason}", 422)


class SameNameRequiresAction(ApiError):
    def __init__(self, candidates: list[dict]) -> None:
        super().__init__(
            "SAME_NAME_REQUIRES_ACTION",
            "已存在同名资料，请明确选择“替换现有资料”或“作为独立资料新增”",
            409,
            details={"candidates": candidates},
        )


class DuplicateContent(ApiError):
    def __init__(self, document_id=None, version_id=None) -> None:
        details = {}
        if document_id is not None:
            details["document_id"] = str(document_id)
        if version_id is not None:
            details["version_id"] = str(version_id)
        super().__init__(
            "DUPLICATE_CONTENT",
            "已存在字节完全相同的有效或待处理资料，未创建重复资料",
            409,
            details=details or None,
        )


class ContentUnchanged(ApiError):
    def __init__(self) -> None:
        super().__init__("CONTENT_UNCHANGED", "替换版本与当前有效版本字节完全相同，未创建新版本", 409)


class ActiveVersionConflict(ApiError):
    def __init__(self, message: str = "当前有效版本与请求预期不一致，请刷新后重试") -> None:
        super().__init__("ACTIVE_VERSION_CONFLICT", message, 409)


class JobStateConflict(ApiError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(code, message, 409)


class ContentUnavailable(ApiError):
    def __init__(self, message: str = "内容已失效或不可访问") -> None:
        super().__init__("CONTENT_UNAVAILABLE", message, 410)


class InvalidUpload(ApiError):
    def __init__(self, message: str = "上传请求不合法") -> None:
        super().__init__("INVALID_UPLOAD", message, 400)


# ---- T04 生命周期稳定错误：冲突只说明前置条件/状态，不回显正文、路径或配置 ----


class PublishConflict(ApiError):
    def __init__(self) -> None:
        super().__init__("PUBLISH_CONFLICT", "有效版本或知识库版本已变化，请刷新后重试", 409, retryable=True)


class VersionNotPublishable(ApiError):
    def __init__(self) -> None:
        super().__init__("VERSION_NOT_PUBLISHABLE", "该版本当前不满足发布条件（需处理成功、检查完整且待确认）", 409)


class DeleteConflict(ApiError):
    def __init__(self) -> None:
        super().__init__("DELETE_CONFLICT", "知识库版本已变化，请刷新后重试删除", 409, retryable=True)


class VersionNotCancellable(ApiError):
    def __init__(self) -> None:
        super().__init__("VERSION_NOT_CANCELLABLE", "该版本已生效或已被替换，不能取消", 409)


# ---- T06 会话/来源/问答稳定错误：只描述权限与状态，不回显他人正文或内部路径 ----


class AccessDenied(ApiError):
    def __init__(self, message: str = "没有访问该资源的权限") -> None:
        super().__init__("FORBIDDEN", message, 403)


class ConversationNotFound(NotFound):
    def __init__(self) -> None:
        super().__init__("CONVERSATION_NOT_FOUND", "会话不存在")


class MessageNotFound(NotFound):
    def __init__(self) -> None:
        super().__init__("MESSAGE_NOT_FOUND", "消息不存在")


class SourceNotFound(NotFound):
    def __init__(self) -> None:
        super().__init__("SOURCE_NOT_FOUND", "来源不存在或不属于该消息")


class SourceUnavailable(ApiError):
    """失效来源：只返回必要失效元信息，不带正文、字段、原图或内部路径。"""

    def __init__(self, *, status: str, document_name: str, version_number: int) -> None:
        super().__init__(
            "SOURCE_UNAVAILABLE",
            "来源已失效，仅保留失效状态",
            410,
            details={"status": status, "document_name": document_name, "version_number": version_number},
        )


class QuestionInProgress(ApiError):
    def __init__(self) -> None:
        super().__init__("QUESTION_IN_PROGRESS", "该会话已有问题正在处理，请稍后重试", 409, retryable=True)


class RequestPayloadMismatch(ApiError):
    def __init__(self) -> None:
        super().__init__("REQUEST_PAYLOAD_MISMATCH", "同一请求ID的问题内容不一致", 409)


class RequestCancelled(ApiError):
    def __init__(self, message: str = "该问答请求已失效，请重新提问") -> None:
        super().__init__("REQUEST_CANCELLED", message, 409)


class ServiceOverloaded(ApiError):
    def __init__(self) -> None:
        super().__init__("SERVER_OVERLOADED", "服务繁忙，请稍后重试", 503, retryable=True)



def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "unknown")


def _validation_details(errors: list[dict]) -> dict:
    """只保留字段位置与错误类型；不包含 input、ctx、提交值或请求体。"""
    fields = []
    for item in errors[:20]:
        location = [str(part) for part in item.get("loc", ()) if isinstance(part, (str, int))]
        fields.append({"loc": location, "type": str(item.get("type", "unknown"))})
    return {"fields": fields}


def _envelope(request: Request, *, code: str, message: str, retryable: bool, details: dict | None) -> dict:
    return {
        "error": {"code": code, "message": message, "retryable": retryable, "details": details},
        "request_id": _request_id(request),
    }


def _headers(request: Request, extra: dict | None = None) -> dict:
    """错误响应也带上 X-Request-ID：500 由 ServerErrorMiddleware 生成，绕过普通中间件。"""
    headers = {"X-Request-ID": _request_id(request)}
    if extra:
        headers.update({key: value for key, value in extra.items() if key.lower() != "x-request-id"})
    return headers


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_envelope(
                request,
                code=exc.code,
                message=exc.message,
                retryable=exc.retryable,
                details=exc.details,
            ),
            headers=_headers(request),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        # 保留 422 语义，但不回显 input/ctx/原始请求体
        return JSONResponse(
            status_code=422,
            content=_envelope(
                request,
                code="VALIDATION_ERROR",
                message="请求参数不合法",
                retryable=False,
                details=_validation_details(list(exc.errors())),
            ),
            headers=_headers(request),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code, message = HTTP_ERROR_MESSAGES.get(exc.status_code, ("HTTP_ERROR", "请求无法处理"))
        # 框架 detail 可能含内部信息，统一使用固定文案；保留协议头（如 Allow）
        return JSONResponse(
            status_code=exc.status_code,
            content=_envelope(request, code=code, message=message, retryable=False, details=None),
            headers=_headers(request, getattr(exc, "headers", None)),
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        # 只记录异常类型，不记录消息与堆栈；消息可能含路径或参数值
        logger.error("unhandled_error type=%s request_id=%s", type(exc).__name__, _request_id(request))
        return JSONResponse(
            status_code=500,
            content=_envelope(
                request,
                code="INTERNAL_ERROR",
                message="服务处理失败",
                retryable=True,
                details=None,
            ),
            headers=_headers(request),
        )

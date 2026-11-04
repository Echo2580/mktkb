"""项目配置（pydantic-settings）。所有秘密项无默认值，缺失时启动即失败。

`trusted_origins` 支持三种输入（代码、环境变量、.env 一致）：
1. 单个 Origin：``http://127.0.0.1:8077``
2. 逗号分隔：``http://127.0.0.1:8077,https://kb.example.com``
3. JSON 数组字符串：``["http://127.0.0.1:8077","https://kb.example.com"]``
以及直接传入 Python 列表。使用 ``NoDecode`` 阻止配置源先做 JSON 解码，避免单项/逗号格式被提前拒绝。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """运行时配置。环境变量前缀 MKTKB_，也可用 .env。"""

    model_config = SettingsConfigDict(
        env_prefix="MKTKB_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        # 校验失败时不输出原始 input_value：after 模型校验器的输入是整份配置字典，
        # 会把其他本身合法的密码/密钥带进异常文本，发生在应用构建前，不经过 HTTP 脱敏。
        hide_input_in_errors=True,
    )

    app_name: str = "市场部 AI 知识库"
    data_dir: Path = Path("var")
    database_url: str | None = None

    session_ttl_seconds: int = 8 * 3600
    cookie_name: str = "mktkb_session"
    cookie_secure: bool = True
    trusted_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)

    csrf_secret: str
    bcrypt_rounds: int = 12

    admin_username: str = "admin"
    admin_password: str
    admin_display_name: str = "演示管理员"
    employee_username: str = "employee"
    employee_password: str
    employee_display_name: str = "演示员工"

    sqlite_busy_timeout_ms: int = 5000
    enable_wal: bool = True
    log_level: str = "INFO"

    # ---- T06 服务端模型配置（秘密不进响应/日志/异常/OpenAPI；未配置时问答返回 MODEL_NOT_CONFIGURED） ----
    model_base_url: str | None = None
    model_name: str | None = None
    model_api_key: SecretStr | None = None
    model_request_timeout_seconds: float = 30.0

    # ---- T03 上传/解析/任务运行限额（默认值与依据见交付报告） ----
    max_upload_bytes: int = 20 * 1024 * 1024
    storage_dir: Path | None = None
    # OOXML（zip 容器）解压预算：成员数、解压总量、单成员、压缩比
    ooxml_max_members: int = 2000
    ooxml_max_total_uncompressed_bytes: int = 128 * 1024 * 1024
    ooxml_max_member_uncompressed_bytes: int = 64 * 1024 * 1024
    ooxml_max_compression_ratio: float = 100.0
    excel_max_data_rows: int = 5000
    # 单并发 worker 的领取租约与续期周期（秒）
    job_lease_seconds: int = 120
    job_lease_renew_seconds: int = 30

    # ---- T07 PDF/图片/OCR 本地解析限额（产品上限与供应商限制分开） ----
    pdf_max_pages: int = 50
    image_max_pixels: int = 20_000_000
    # PDF 页面渲染上限：先按像素/边长预算缩放，再解码；渲染分辨率默认 2x（144 DPI）
    pdf_render_scale: float = 2.0
    pdf_max_page_pixels: int = 20_000_000
    # 单块编码体积与分块数上限；腾讯云 ImageBase64 上限 10M，默认留出余量
    ocr_max_image_bytes: int = 4 * 1024 * 1024
    ocr_max_tiles: int = 64

    # ---- T07 腾讯云 OCR 服务端配置（SecretStr；未配置时扫描页返回 OCR_NOT_CONFIGURED） ----
    # S2-H：D01 xlsx smoke 明确排除 OCR；ocr_disabled=True 时即使有凭据也不构造客户端。
    ocr_disabled: bool = False
    ocr_secret_id: SecretStr | None = None
    ocr_secret_key: SecretStr | None = None
    ocr_region: str = "ap-guangzhou"
    ocr_endpoint: str = "https://ocr.tencentcloudapi.com"
    ocr_request_timeout_seconds: float = 30.0
    # 429 有限退避：最多尝试次数、单次等待、总等待均有上限；额度不足不自动重试
    ocr_max_attempts: int = 3
    ocr_retry_base_seconds: float = 0.25
    ocr_retry_max_single_seconds: float = 1.0
    ocr_retry_total_seconds: float = 2.0
    # 单 worker 不超过 2 次/秒（腾讯表格识别默认频率也是 2 次/秒）
    ocr_max_requests_per_second: float = 2.0

    # ---- S2 产品问答内核（rag）：索引位置、同步与供应商模式 ----
    # 默认启用离线确定性索引（不产生真实付费调用）；live 必须由部署方显式给出预算入口。
    rag_qa_enabled: bool = True
    rag_index_path: Path | None = None
    rag_provider_mode: str = "offline"
    rag_page_size: int = 10
    rag_top_k: int = 8
    rag_business_date: str | None = None
    rag_sync_on_startup: bool = True
    rag_embedding_retry_seconds: float = 30.0

    # ---- T003b 可观测性 Trace 接线（设计 §5 / §6.1 / §6.2 / §6.5 / §6.6） ----
    # 默认 False：不构造 Trace 仓储、不创建任何 Trace DB 文件、响应头与业务行为完全不变。
    # 本地 P0 用 MKTKB_TRACE_ENABLED=1 开启（计划 Task 3 Interfaces）。
    trace_enabled: bool = False
    # 独立 SQLite 位置（设计 §6.2：与 mktkb.sqlite3 / rag-index.sqlite3 完全分离）；
    # None 时落到 <data_dir>/observability/qa-traces.sqlite3。
    trace_db_path: Path | None = None
    # 内容模式（设计 §6.5）：P0 只实现最保守的 off / hash；redacted / full 显式拒绝。
    trace_content_mode: str = "hash"
    # 真实业务问题的 HMAC 密钥（设计 §6.5）：只用于 question_hash，记录里只存 key 指纹；
    # 未配置时 tracer 退化为 sha256（合成语料/测试口径）。该值不得出现在日志 / 响应 /
    # 异常 / Trace 记录里。
    trace_hmac_key: SecretStr | None = None


    @field_validator("trusted_origins", mode="before")
    @classmethod
    def _parse_origins(cls, value: object) -> object:
        """接受单个 Origin、逗号列表、JSON 数组字符串或列表/元组。"""
        if isinstance(value, str):
            text = value.strip()
            if text.startswith("["):
                try:
                    value = json.loads(text)
                except json.JSONDecodeError:
                    # 不保留底层异常链，避免把原始 JSON 片段带进 stderr
                    raise ValueError("trusted_origins 的 JSON 数组格式无法解析") from None
            else:
                value = [item.strip() for item in text.split(",") if item.strip()]
        if isinstance(value, (tuple, set)):
            value = list(value)
        return value

    @field_validator("trusted_origins")
    @classmethod
    def _validate_origins(cls, origins: list[str]) -> list[str]:
        if not origins:
            raise ValueError("trusted_origins 不能为空")
        cleaned: list[str] = []
        for origin in origins:
            if not isinstance(origin, str):
                raise ValueError("trusted_origins 的每一项都必须是字符串")
            text = origin.strip()
            if not text or text.lower() in {"null", "none", "*"}:
                # 文案不拼接原始值：Origin 可能内嵌用户名/密码
                raise ValueError("trusted_origins 中存在空值或通配来源")
            parts = urlsplit(text)
            if parts.scheme not in {"http", "https"} or not parts.hostname:
                raise ValueError("trusted_origins 的每一项必须包含 http(s) scheme 与主机")
            if parts.path not in {"", "/"} or parts.query or parts.fragment or parts.username or parts.password:
                raise ValueError("trusted_origins 的每一项不得包含路径、查询、片段或用户信息")
            normalised = text[:-1] if text.endswith("/") else text
            if normalised not in cleaned:
                cleaned.append(normalised)
        return cleaned

    @field_validator("trace_content_mode")
    @classmethod
    def _validate_trace_content_mode(cls, mode: str) -> str:
        """P0 只允许 ``off`` / ``hash``（设计 §6.5）；``redacted`` / ``full`` 显式 fail closed。"""
        if not isinstance(mode, str):
            raise TypeError("trace_content_mode 必须是字符串")
        normalized = mode.strip().lower()
        if normalized in {"redacted", "full"}:
            raise ValueError(
                "trace_content_mode=redacted/full 在 P0 未实现，显式拒绝；P0 只允许 off / hash"
            )
        if normalized not in {"off", "hash"}:
            raise ValueError("trace_content_mode 只允许 off / hash（P0）")
        return normalized

    @field_validator("trace_hmac_key", mode="before")
    @classmethod
    def _normalize_trace_hmac_key(cls, value: object) -> object:
        """空白 key 视为“未配置”（tracer 退化为 sha256）；非 str / SecretStr 交给类型校验。"""
        if value is None:
            return None
        if isinstance(value, SecretStr):
            raw = value.get_secret_value()
        elif isinstance(value, str):
            raw = value
        else:
            return value
        return None if not raw.strip() else SecretStr(raw)

    @field_validator("trace_db_path", mode="before")
    @classmethod
    def _normalize_trace_db_path(cls, value: object) -> object:
        """空白路径视为未配置（回落到默认目录）；字符串转成 ``Path``。"""
        if value is None:
            return None
        if isinstance(value, str):
            text = value.strip()
            return None if not text else Path(text)
        return value

    @model_validator(mode="after")
    def _check_secrets(self) -> "Settings":
        if len(self.csrf_secret) < 16:
            raise ValueError("csrf_secret must be at least 16 characters")
        for name in ("admin_password", "employee_password"):
            value = getattr(self, name)
            if not value or len(value) < 8:
                raise ValueError(f"{name} must be set with at least 8 characters")
            if len(value.encode("utf-8")) > 72:
                raise ValueError(f"{name} must be at most 72 bytes (bcrypt limit)")
        if self.session_ttl_seconds <= 0:
            raise ValueError("session_ttl_seconds must be positive")
        if self.max_upload_bytes <= 0:
            raise ValueError("max_upload_bytes must be positive")
        if self.excel_max_data_rows <= 0:
            raise ValueError("excel_max_data_rows must be positive")
        if self.ooxml_max_members <= 0 or self.ooxml_max_total_uncompressed_bytes <= 0:
            raise ValueError("ooxml archive budgets must be positive")
        if self.ooxml_max_member_uncompressed_bytes <= 0 or self.ooxml_max_compression_ratio <= 0:
            raise ValueError("ooxml member budgets must be positive")
        if self.job_lease_seconds <= 0:
            raise ValueError("job_lease_seconds must be positive")
        if not 0 < self.job_lease_renew_seconds < self.job_lease_seconds:
            raise ValueError("job_lease_renew_seconds must be positive and smaller than job_lease_seconds")
        if self.pdf_max_pages <= 0:
            raise ValueError("pdf_max_pages must be positive")
        if self.image_max_pixels <= 0 or self.pdf_max_page_pixels <= 0:
            raise ValueError("image/pdf pixel limits must be positive")
        if not 0 < self.pdf_render_scale <= 4:
            raise ValueError("pdf_render_scale must be in (0, 4]")
        if self.ocr_max_image_bytes <= 0 or self.ocr_max_tiles <= 0:
            raise ValueError("ocr image/tile limits must be positive")
        if not 0 < self.ocr_max_requests_per_second <= 2:
            raise ValueError("ocr_max_requests_per_second must be in (0, 2]")
        if not 1 <= self.ocr_max_attempts <= 5:
            raise ValueError("ocr_max_attempts must be between 1 and 5")
        if self.ocr_retry_base_seconds <= 0 or self.ocr_retry_max_single_seconds <= 0:
            raise ValueError("ocr retry waits must be positive")
        if self.ocr_retry_total_seconds < 0:
            raise ValueError("ocr_retry_total_seconds must be non-negative")
        if not 0 < self.ocr_request_timeout_seconds <= 60:
            raise ValueError("ocr_request_timeout_seconds must be in (0, 60]")
        if self.rag_provider_mode not in {"offline", "live"}:
            raise ValueError("rag_provider_mode 只允许 offline/live")
        if not 1 <= self.rag_page_size <= 50:
            raise ValueError("rag_page_size 必须在 1～50")
        if not 1 <= self.rag_top_k <= 50:
            raise ValueError("rag_top_k 必须在 1～50")
        if self.rag_embedding_retry_seconds < 0:
            raise ValueError("rag_embedding_retry_seconds 不能为负数")
        if self.rag_business_date is not None:
            import re as _re

            if _re.fullmatch(r"\d{4}-\d{2}-\d{2}", self.rag_business_date.strip()) is None:
                raise ValueError("rag_business_date 必须是 YYYY-MM-DD")
            self.rag_business_date = self.rag_business_date.strip()
        region = (self.ocr_region or "").strip()
        if not region or len(region) > 64 or any(character.isspace() for character in region):
            raise ValueError("ocr_region 不合法")
        self.ocr_region = region
        parts = urlsplit(self.ocr_endpoint or "")
        if (
            parts.scheme != "https"
            or parts.hostname != "ocr.tencentcloudapi.com"
            or parts.path not in {"", "/"}
            or parts.query
            or parts.fragment
            or parts.username
            or parts.password
        ):
            raise ValueError("ocr_endpoint 必须是腾讯云官方 HTTPS 域名")
        for name in ("ocr_secret_id", "ocr_secret_key"):
            value = getattr(self, name)
            if value is not None and not value.get_secret_value().strip():
                setattr(self, name, None)
        provided = (self.ocr_secret_id is not None, self.ocr_secret_key is not None)
        if any(provided) and not all(provided):
            raise ValueError("OCR 配置必须同时提供 SecretId 与 SecretKey")
        return self

    @model_validator(mode="after")
    def _check_model_config(self) -> "Settings":
        """模型配置：三项齐全才启用；只接受服务端可信地址，错误信息不回显密钥。"""
        provided = (
            self.model_base_url is not None,
            self.model_name is not None,
            self.model_api_key is not None,
        )
        if any(provided) and not all(provided):
            raise ValueError("模型配置必须同时提供 base URL、model 名称与 API key")
        if self.model_base_url is not None:
            text = self.model_base_url.strip()
            parts = urlsplit(text)
            if parts.scheme not in {"http", "https"} or not parts.hostname:
                raise ValueError("model_base_url 必须是 http(s) 地址且包含主机")
            if parts.username or parts.password or parts.query or parts.fragment:
                raise ValueError("model_base_url 不得包含用户信息、查询或片段")
            if ".." in parts.path or parts.path.endswith("/"):
                raise ValueError("model_base_url 不得包含上级路径或以斜杠结尾")
            self.model_base_url = text.rstrip("/")
        if self.model_name is not None:
            name = self.model_name.strip()
            if not name or len(name) > 200 or any(character.isspace() for character in name):
                raise ValueError("model_name 不合法")
            self.model_name = name
        if self.model_api_key is not None and not self.model_api_key.get_secret_value().strip():
            raise ValueError("model_api_key 不能为空")
        if not 0 < self.model_request_timeout_seconds <= 60:
            raise ValueError("model_request_timeout_seconds 必须在 (0, 60] 秒内")
        return self

    @property
    def database_path(self) -> Path:
        return Path(self.data_dir) / "mktkb.sqlite3"

    @property
    def resolved_rag_index_path(self) -> Path:
        """rag 索引/查询状态库；与业务库分开，默认在数据目录下（initialize=False 不创建）。"""
        return Path(self.rag_index_path) if self.rag_index_path else Path(self.data_dir) / "rag-index.sqlite3"

    @property
    def resolved_storage_dir(self) -> Path:
        """原文件/暂存目录；默认位于数据目录下，不对外静态挂载。"""
        return Path(self.storage_dir) if self.storage_dir else Path(self.data_dir) / "storage"

    @property
    def resolved_trace_db_path(self) -> Path:
        """Trace 独立库路径（设计 §6.2）：默认 ``<data_dir>/observability/qa-traces.sqlite3``。

        与业务库 ``mktkb.sqlite3`` / ``rag-index.sqlite3`` 完全分离；只有
        ``trace_enabled=True`` 时 ``create_app`` 才会按该路径创建仓储与库文件。
        """
        if self.trace_db_path is not None:
            return Path(self.trace_db_path)
        return Path(self.data_dir) / "observability" / "qa-traces.sqlite3"

    @property
    def trace_hmac_key_bytes(self) -> bytes | None:
        """HMAC key 的字节形式；未配置时 ``None``（tracer 退化为 sha256，设计 §6.5）。

        只供 ``start_trace(hmac_key=...)`` 在内存中使用：不打印、不落库、不进异常。
        """
        if self.trace_hmac_key is None:
            return None
        raw = self.trace_hmac_key.get_secret_value().encode("utf-8")
        return raw or None

    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        self.data_dir.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{self.database_path.as_posix()}"

"""T001：版本绑定与摘要工具（pipeline_version / config_hash / 问题哈希）。

约定（同时写入 ``docs/evaluation/trace_schema_v0_1.md``）：

- 摘要统一为 **sha256 hex 前 12 位**（与 ``dataset_version = suite:label_version:sha256[:12]``
  的口径一致）；输入为 canonical JSON：``ensure_ascii=False, sort_keys=True,
  separators=(",", ":")``；
- ``pipeline_version`` 的默认组件在**调用时**延迟导入
  （``qa.service.QA_ENGINE_VERSION``、``rag.index.SCHEMA_VERSION`` /
  ``INDEX_CACHE_VERSION``、``retrieval.tokenize.TOKENIZER_VERSION`` 与 ``RagConfig``
  默认值），模块顶层只 import 标准库，避免循环依赖；
- ``config_hash`` 只接受白名单字段，并且键名含 ``key|secret|token|password``
  （不区分大小写）时直接 ``ValueError``，防止把凭据写进摘要；
- ``hash_question`` 对 ``hmac-sha256`` 强制非空 key；``sha256`` 允许空 key
  （合成语料场景）。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

#: 所有摘要的前缀长度（与 dataset_version 的 ``sha256[:12]`` 一致）。
DIGEST_PREFIX_LENGTH = 12
#: pipeline_version 的摘要长度（sha256 hex 前 12 位）。
PIPELINE_VERSION_PREFIX_LENGTH = DIGEST_PREFIX_LENGTH

#: config_hash 白名单：只纳入影响检索/回答行为、且不含凭据的配置项。
#: 白名单之外的字段（路径、预算、账本、API Key 等）不参与摘要。
CONFIG_HASH_FIELDS: tuple[str, ...] = (
    "provider_mode",
    "embedding_model",
    "embedding_dimensions",
    "rerank_model",
    "rerank_top_n",
    "rerank_max_documents",
    "chat_model",
    "chunk_max_chars",
    "chunk_max_units",
    "chunk_overlap_units",
    "top_k",
    "candidate_limit",
    "vector_candidate_limit",
    "page_size",
    "max_page_size",
    "hard_filters",
)
_CONFIG_HASH_FIELD_SET = frozenset(CONFIG_HASH_FIELDS)

#: 疑似凭据键名；config_hash 一律拒绝，防止密钥进入摘要/报告。
_SECRET_KEY_PATTERN = re.compile(r"(key|secret|token|password)", re.IGNORECASE)

_HMAC_ALGO = "hmac-sha256"
_SHA256_ALGO = "sha256"
_ALLOWED_ALGOS = (_HMAC_ALGO, _SHA256_ALGO)
_KEY_FINGERPRINT_DOMAIN = b"mktkb.trace.hmac_key_id.v0.1:"


def _json_default(value: Any) -> Any:
    """为 canonical JSON 提供稳定、跨平台的兜底编码（不吞掉未知类型）。"""
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, (set, frozenset)):
        return sorted(str(item) for item in value)
    raise TypeError(f"无法稳定序列化到摘要的类型：{type(value).__name__}")


def _canonical_json(payload: Any) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=_json_default,
    )


def _short_digest(payload: Any) -> str:
    digest = hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()
    return digest[:DIGEST_PREFIX_LENGTH]


def _default_pipeline_components() -> dict[str, Any]:
    """从业务模块延迟导入默认组件；只在调用时执行，避免模块顶层循环依赖。"""
    from ..qa.service import QA_ENGINE_VERSION
    from ..rag.config import RagConfig
    from ..rag.index import INDEX_CACHE_VERSION, SCHEMA_VERSION
    from ..retrieval.tokenize import TOKENIZER_VERSION

    config = RagConfig()
    return {
        "qa_engine_version": QA_ENGINE_VERSION,
        "rag_schema_version": SCHEMA_VERSION,
        "index_cache_version": INDEX_CACHE_VERSION,
        "tokenizer_version": TOKENIZER_VERSION,
        "embedding_model": config.embedding_model,
        "embedding_dimensions": config.embedding_dimensions,
        "rerank_model": config.rerank_model,
        "chunk_max_chars": config.chunk_max_chars,
        "chunk_max_units": config.chunk_max_units,
        "chunk_overlap_units": config.chunk_overlap_units,
        "top_k": config.top_k,
        "page_size": config.page_size,
    }


def pipeline_version(components: Mapping[str, Any] | None = None) -> str:
    """返回 pipeline 版本摘要（sha256 hex 前 12 位）。

    - ``components`` 为 ``None`` 时使用默认组件（调用时延迟导入业务常量）；
    - 显式传入 ``components`` 时**完全替换**默认组件，只对给定映射做 canonical JSON
      摘要：同输入同值，``prompt`` / ``top_k`` 等任一值变化即变化。
    """
    payload = _default_pipeline_components() if components is None else components
    return _short_digest(dict(payload))


def config_hash(config: Mapping[str, Any]) -> str:
    """返回配置摘要（sha256 hex 前 12 位），只纳入 ``CONFIG_HASH_FIELDS`` 白名单字段。

    - 任意键名含 ``key|secret|token|password``（不区分大小写）→ ``ValueError``；
    - 白名单之外的非凭据字段被忽略（不参与摘要，也不报错）；
    - 白名单字段值变化 → 摘要变化。
    """
    filtered: dict[str, Any] = {}
    for raw_name, value in config.items():
        name = str(raw_name)
        if _SECRET_KEY_PATTERN.search(name):
            raise ValueError(
                f"config_hash 拒绝疑似凭据字段 {name!r}：键名不得含 key/secret/token/password"
            )
        if name in _CONFIG_HASH_FIELD_SET:
            filtered[name] = value
    return _short_digest(filtered)


def hash_question(question: str, *, key: bytes = b"", algo: str = _HMAC_ALGO) -> str:
    """对问题文本做不可逆摘要，返回值不含原文。

    - ``algo="hmac-sha256"``：必须提供非空 ``key``，返回 64 位 hex；
    - ``algo="sha256"``：允许空 key（仅合成语料），返回 64 位 hex；
    - 其他 algo → ``ValueError``。
    """
    if not isinstance(question, str):
        raise TypeError("question 必须是 str")
    if algo not in _ALLOWED_ALGOS:
        raise ValueError(f"algo 只允许 {_ALLOWED_ALGOS}，收到 {algo!r}")
    payload = question.encode("utf-8")
    if algo == _HMAC_ALGO:
        if not key:
            raise ValueError("hmac-sha256 必须提供非空 key；真实业务问题禁止无密钥哈希")
        if not isinstance(key, (bytes, bytearray, memoryview)):
            raise TypeError("hmac-sha256 的 key 必须是 bytes")
        return hmac.new(bytes(key), payload, hashlib.sha256).hexdigest()
    return hashlib.sha256(payload).hexdigest()


def key_fingerprint(key: bytes) -> str:
    """返回 HMAC key 的不可逆指纹（sha256 hex 前 12 位，带域分隔前缀）。

    Trace 只存这个指纹（``hmac_key_id``）用于区分密钥版本；永不存密钥本身。
    """
    if not isinstance(key, (bytes, bytearray, memoryview)):
        raise TypeError("key 必须是 bytes")
    if not key:
        raise ValueError("key_fingerprint 需要非空 key")
    digest = hashlib.sha256(_KEY_FINGERPRINT_DOMAIN + bytes(key)).hexdigest()
    return digest[:DIGEST_PREFIX_LENGTH]


__all__ = [
    "CONFIG_HASH_FIELDS",
    "DIGEST_PREFIX_LENGTH",
    "PIPELINE_VERSION_PREFIX_LENGTH",
    "config_hash",
    "hash_question",
    "key_fingerprint",
    "pipeline_version",
]

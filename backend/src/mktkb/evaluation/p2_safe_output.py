"""公开层路径脱敏与安全原因码（FU-4）。

边界
----
- 只处理**公开层**：stdout / stderr / 结构化错误 / 日志 / 报告 / 分享副本；
- 受控层（私有封存目录里的 run-receipt、plan、密文、账本）保持原样，本模块不参与；
- 只改"看起来像文件系统路径"的字符串，**固定原因码、计数、摘要一律不动**：
  ``holdout_hard_failure_unverified`` 这类 reason code 含 ``holdout`` 字样也不会被误伤，
  因为判定基于路径形状（盘符/UNC/受限期根/密钥与密文文件名），不是关键词替换；
- 脱敏后的记号是**确定性**的（同一输入 → 同一记号），因此脱敏后的产物仍可做
  SHA-256 前后比对，不会把"确定性"换成"随机盐"。

复用既有机制
------------
- 固定原因码体系沿用两个受控入口的 ``EntryError.code``（本模块只清洗自由文本 detail，
  不发明新 code）；
- 路径拒绝的固定码沿用 ``path_inside_forbidden_root`` / ``path_invalid`` 等既有码；
  本模块只负责把这些码**附带的信息**压到"类型 + 计数 + 摘要"。

记号
----
``<redacted-path:ROLE:HHHHHHHHHHHH>``
    ROLE 是稳定角色名（``restricted`` / ``holdout_root`` / ``batch_root`` / ``key_file``
    / ``ciphertext`` / ``absolute``），HHH 是 ``sha256(normcase(path))[:12]``：
    可用于"同一条路径前后是否一致"的对照，但不含路径本身。
``<redacted-text:LEN>``
    自由文本整段不可安全表达时的替代（只保留原长度档位）。
``<truncated:LEN>``
    超长字符串按公开上限截断后的记号。
"""
from __future__ import annotations

import hashlib
import os
import re
from typing import Any, Iterable, Mapping, Sequence

SCHEMA_VERSION = "p2-safe-output/v0.1"

PUBLIC_TEXT_MAX = 512
"""公开层单条字符串上限（超长一律截断成 ``<truncated:LEN>``）。"""

REDACTED_PATH = "<redacted-path:{role}:{digest}>"
TRUNCATED = "<truncated:{length}>"

#: 受限根的**名称标记**：命中即视为受限，无论绝对路径落在哪。
RESTRICTED_MARKERS: tuple[str, ...] = (
    "mktkb-p2-holdout",
    "mktkb-p2-h2v3",
    "p2-holdout",
    "p2_h2_holdout",
)

#: 受限**文件名/后缀**：密钥与密文（含逐题材料）不进公开层。
KEY_SUFFIXES: tuple[str, ...] = (".key",)
CIPHER_SUFFIXES: tuple[str, ...] = (".fernet",)

#: 受限目录名（出现在路径任一段即受限）：仓库私有运行目录。
RESTRICTED_PARTS: tuple[str, ...] = ("var", ".env")

_WINDOWS_ABS_RE = re.compile(r"^[A-Za-z]:[\\/]")
_UNC_RE = re.compile(r"^\\\\[^\\]+\\")
_POSIX_ABS_RE = re.compile(r"^/(?!/)")
_BARE_KEY_RE = re.compile(r"^[^\\/:*?\"<>|\r\n]+\.key$", re.IGNORECASE)
_BARE_CIPHER_RE = re.compile(r"^[^\\/:*?\"<>|\r\n]+\.fernet$", re.IGNORECASE)
_BARE_ENV_RE = re.compile(r"^\.env(\.[A-Za-z0-9_.-]+)?$", re.IGNORECASE)

#: 自由文本里可能内嵌的路径（盘符 / UNC）；不匹配仓内相对路径。
_EMBEDDED_PATH_RE = re.compile(
    r"(?:[A-Za-z]:[\\/][^\s\"'<>|,;]*)|(?:\\\\[^\s\"'<>|,;]*\\[^\s\"'<>|,;]*)"
)
_EMBEDDED_KEY_RE = re.compile(r"(?<![\w.-])(?:[\w.-]+\.(?:key|fernet)|\.env)\b", re.IGNORECASE)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", "surrogatepass")).hexdigest()


def norm_for_compare(value: str | os.PathLike[str]) -> str:
    """归一化到可比较形态：``normcase`` + 展开 ``..``/``.`` + 去尾斜杠。

    不做文件系统访问（``realpath`` 由调用方在需要跟随链接时自行调用）。
    """
    text = os.fspath(value)
    text = os.path.expanduser(text)
    normalized = os.path.normpath(text)
    if len(normalized) > 1:
        normalized = normalized.rstrip("\\/") or normalized
    return os.path.normcase(normalized)


def real_for_compare(value: str | os.PathLike[str]) -> str:
    """跟随链接/junction 后的可比较形态；不可解析时退回归一化形态。"""
    try:
        resolved = os.path.realpath(os.fspath(value))
    except (OSError, ValueError):
        return norm_for_compare(value)
    return norm_for_compare(resolved)


def path_kind(value: str) -> str | None:
    """返回路径形状类别；非路径字符串返回 ``None``。"""
    if not isinstance(value, str) or not value:
        return None
    if "\x00" in value:
        return "invalid"
    if _WINDOWS_ABS_RE.match(value):
        return "windows_abs"
    if _UNC_RE.match(value):
        return "unc"
    if _POSIX_ABS_RE.match(value):
        return "posix_abs"
    if _BARE_KEY_RE.match(value):
        return "key_file"
    if _BARE_CIPHER_RE.match(value):
        return "ciphertext"
    if _BARE_ENV_RE.match(value):
        return "key_file"
    return None


def _parts_lower(value: str) -> tuple[str, ...]:
    return tuple(part.lower() for part in re.split(r"[\\/]+", value) if part)


def is_restricted(
    value: str,
    *,
    roots: Sequence[str | os.PathLike[str]] = (),
) -> bool:
    """路径字符串是否必须留在受控层（受限根 / 密钥 / 密文 / 私有目录）。"""
    kind = path_kind(value)
    if kind in {"key_file", "ciphertext"}:
        return True
    if kind == "unc":
        # UNC 指向的共享从不属于仓库相对公开件，默认按受限处理（fail closed）。
        return True
    if kind == "invalid":
        return True
    if kind is None:
        return False
    lowered = value.lower()
    if any(marker in lowered for marker in RESTRICTED_MARKERS):
        return True
    parts = _parts_lower(value)
    if any(part in RESTRICTED_PARTS for part in parts):
        return True
    if lowered.endswith(KEY_SUFFIXES) or lowered.endswith(CIPHER_SUFFIXES):
        return True
    candidate = real_for_compare(value)
    for root in roots:
        try:
            root_text = real_for_compare(root)
        except (OSError, ValueError):
            continue
        if not root_text:
            continue
        if candidate == root_text or candidate.startswith(root_text + os.sep):
            return True
    return False


def path_token(value: str, *, role: str | None = None) -> str:
    """受限路径的确定性记号（不含路径本身）。"""
    kind = path_kind(value) or "path"
    if role is None:
        role = {
            "key_file": "key_file",
            "ciphertext": "ciphertext",
            "windows_abs": "absolute",
            "unc": "absolute",
            "posix_abs": "absolute",
            "invalid": "invalid",
        }.get(kind, "path")
    return REDACTED_PATH.format(role=role, digest=_sha(real_for_compare(value))[:12])


def truncate_text(value: str, *, limit: int = PUBLIC_TEXT_MAX) -> str:
    if len(value) <= limit:
        return value
    return TRUNCATED.format(length=len(value))


def redact_value(
    value: str,
    *,
    roots: Sequence[str | os.PathLike[str]] = (),
    strict: bool = False,
    role: str | None = None,
    limit: int = PUBLIC_TEXT_MAX,
) -> str:
    """清洗单个字符串。

    ``strict=False``（默认，既有入口的 stdout 边界）：只替换**受限**路径；
    ``strict=True``（新公开产物/分享副本）：任何绝对路径都替换成记号。
    """
    if not isinstance(value, str) or not value:
        return value
    kind = path_kind(value)
    if kind is not None:
        restricted = is_restricted(value, roots=roots)
        if restricted or (strict and kind in {"windows_abs", "unc", "posix_abs"}):
            return path_token(value, role=role if role else None)
        if kind == "invalid":
            return path_token(value, role="invalid")
        return truncate_text(value, limit=limit)
    return truncate_text(redact_text(value, roots=roots, strict=strict), limit=limit)


def redact_text(
    text: str,
    *,
    roots: Sequence[str | os.PathLike[str]] = (),
    strict: bool = False,
    limit: int = PUBLIC_TEXT_MAX,
) -> str:
    """清洗自由文本（错误 detail / 日志行）：内嵌绝对路径与密钥文件名换记号。"""
    if not isinstance(text, str) or not text:
        return text
    if "\x00" in text:
        return path_token(text, role="invalid")

    def _path_sub(match: re.Match[str]) -> str:
        token = match.group(0)
        if strict or is_restricted(token, roots=roots):
            return path_token(token)
        return token

    def _name_sub(match: re.Match[str]) -> str:
        token = match.group(0)
        lowered = token.lower()
        if lowered.endswith(".key") or lowered == ".env" or lowered.startswith(".env."):
            role = "key_file"
        else:
            role = "ciphertext"
        return path_token(token, role=role)

    cleaned = _EMBEDDED_PATH_RE.sub(_path_sub, text)
    cleaned = _EMBEDDED_KEY_RE.sub(_name_sub, cleaned)
    return truncate_text(cleaned, limit=limit)


def redact_payload(
    payload: Any,
    *,
    roots: Sequence[str | os.PathLike[str]] = (),
    strict: bool = False,
    limit: int = PUBLIC_TEXT_MAX,
) -> Any:
    """递归清洗结构化输出：只改字符串值，键与数值/布尔一律不动。"""
    if isinstance(payload, str):
        return redact_value(payload, roots=roots, strict=strict, limit=limit)
    if isinstance(payload, Mapping):
        return {
            key: redact_payload(value, roots=roots, strict=strict, limit=limit)
            for key, value in payload.items()
        }
    if isinstance(payload, (list, tuple)):
        return [redact_payload(item, roots=roots, strict=strict, limit=limit) for item in payload]
    return payload


def scan_public_text(text: str, *, limit: int = 200) -> dict[str, Any]:
    """对一段公开文本做定向扫描：只报**类别与位置**，绝不回显命中的路径本身。"""
    findings: list[dict[str, Any]] = []
    for match in _EMBEDDED_PATH_RE.finditer(text):
        if len(findings) >= limit:
            break
        findings.append({"kind": "absolute_path", "offset": match.start(), "length": len(match.group(0))})
    for match in _EMBEDDED_KEY_RE.finditer(text):
        if len(findings) >= limit:
            break
        findings.append({"kind": "key_or_ciphertext_name", "offset": match.start(), "length": len(match.group(0))})
    counts: dict[str, int] = {}
    for item in findings:
        counts[item["kind"]] = counts.get(item["kind"], 0) + 1
    return {
        "schema_version": SCHEMA_VERSION,
        "findings": findings,
        "counts": counts,
        "total": sum(counts.values()),
        "clean": not findings,
    }


def scan_public_texts(
    texts: Iterable[tuple[str, str]], *, limit: int = 200
) -> dict[str, Any]:
    """批量扫描 ``(label, text)``；返回按 label 归类的**只含计数**的报告。"""
    rows: list[dict[str, Any]] = []
    total = 0
    for label, text in texts:
        result = scan_public_text(text, limit=limit)
        rows.append(
            {
                "label": label,
                "counts": result["counts"],
                "total": result["total"],
                "clean": result["clean"],
            }
        )
        total += int(result["total"])
    return {
        "schema_version": SCHEMA_VERSION,
        "files": rows,
        "total": total,
        "clean": total == 0,
    }


__all__ = [
    "CIPHER_SUFFIXES",
    "KEY_SUFFIXES",
    "PUBLIC_TEXT_MAX",
    "REDACTED_PATH",
    "RESTRICTED_MARKERS",
    "RESTRICTED_PARTS",
    "SCHEMA_VERSION",
    "TRUNCATED",
    "is_restricted",
    "norm_for_compare",
    "path_kind",
    "path_token",
    "real_for_compare",
    "redact_payload",
    "redact_text",
    "redact_value",
    "scan_public_text",
    "scan_public_texts",
    "truncate_text",
]

"""T207 HISTORICAL-AUDIT：只读历史审计入口（历史重评；不授权 live、不产出 release）。

为什么需要独立入口
------------------
旧 run 的顶层绑定 `code_version` 是**原执行**时点的源码摘要。已接收的评测工具修复改变了
`backend/src/mktkb/evaluation/p2_hard_evidence.py` 的字节，因此受控工具
`tools/p2_h2_controlled_execute.py recompute` 的 `document.code_version == code_digest()`
检查现在会以 `code_changed_since_plan` 拒绝重算旧证据。该检查**保留原样**（本模块不 patch、
不伪造 `code_digest`、不改旧计划、不提供通用 `--ignore-code-version`）。

本模块提供的是另一种语义：**历史重评**。
- 先独立核验旧 run 的内部身份一致性（binding/config/plan/inputs/GO/账本前缀/receipt/seal/
  每个密文与 manifest/turn 索引/顺序/文件集合）；
- 再用已接收分类器把旧证据**重新分类**，并把「原执行代码身份」与「本次分析代码身份」分列；
- 输出固定 `analysis_kind=historical_reassessment`、`authorizes_live=false`、
  `release_ready=false`，绝不冒充原运行产物，也绝不把分析代码摘要写回旧信封 bindings。

边界
----
- 只读：不得写入历史根；调用前后对历史根做树摘要比对，任何变化都固定拒绝。
- 零模型/检索/产品调用：入口不提供 run/plan/preflight/sign-GO，不接收 `--env-file`
  （因此不读项目 `.env`、不读任何 API 凭据），并在进程内装 socket/DNS/provider 三重 guard。
- 秘密与原文不出进程：stdout 与落盘产物只含固定码/计数/hash/路径；异常链一律固定码。
- 质量数据来源固定标记 `recorded_status`（case-plan 旧质量标签），不冒充重新运行质量评分器。

退出码：0 通过；2 受控拒绝；3 用法/输入不合法；1 未预期。
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import socket
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, NoReturn, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_SRC = PROJECT_ROOT / "backend" / "src"
CONTROLLED_TOOL = PROJECT_ROOT / "tools" / "p2_h2_controlled_execute.py"

TOOL_SCHEMA_VERSION = "p2-h2-historical-audit-tool/v0.1"
AUDIT_SCHEMA_VERSION = "t207-historical-audit/v0.1"
ANALYSIS_KIND = "historical_reassessment"
QUALITY_SOURCE_RECORDED = "recorded_status"
#: 旧历史审计只认历史证据版本；A-R2 新版本（v0.3*）必须固定 unsupported，
#: 不静默忽略新键、不把新证据降级当旧证据。
SUPPORTED_EVIDENCE_SCHEMA_VERSIONS = (
    "p2-hard-evidence-capture/v0.1",
    "p2-hard-evidence-capture/v0.2-live",
)

EXIT_OK = 0
EXIT_INTERNAL = 1
EXIT_REFUSED = 2
EXIT_USAGE = 3

#: 公开产物里绝不允许出现的键（逐题 id/题面/答案/逐题证据文件名）。
FORBIDDEN_PUBLIC_KEYS = frozenset(
    {
        "case_id",
        "case_ids",
        "question",
        "questions",
        "text",
        "answer",
        "answers",
        "reference_answer",
        "labels",
        "facts",
        "evidence_file",
        "expected_values",
        "expected_sources",
    }
)
MAX_PUBLIC_STRING = 400
MAX_TREE_FILES_FOR_GUARD = 50_000
SECRET_SHAPE = re.compile(
    r"(-----BEGIN [A-Z ]+-----|sk-[A-Za-z0-9]{8,}|ghp_[A-Za-z0-9]{8,}|AKIA[0-9A-Z]{12,}|"
    r"Bearer\s+[A-Za-z0-9._-]{8,}|[A-Za-z0-9_-]{43}=)"
)
FIXED_CODE_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,80}$")


class EntryError(RuntimeError):
    """受控拒绝：code 固定可机读，detail 只含固定码/变量名（绝不含值）。"""

    def __init__(self, code: str, detail: str = "", exit_code: int = EXIT_REFUSED) -> None:
        self.code = str(code)
        self.detail = str(detail)
        self.exit_code = int(exit_code)
        super().__init__(f"{self.code}: {self.detail}" if self.detail else self.code)


def _refuse(code: str, detail: str = "") -> NoReturn:
    raise EntryError(code, detail)


def _usage(code: str, detail: str = "") -> NoReturn:
    raise EntryError(code, detail, exit_code=EXIT_USAGE)


# --------------------------------------------------------------------------- #
# 网络 guard（socket / DNS / provider 三重；只在本进程窗口内生效，退出还原）
# --------------------------------------------------------------------------- #


class NetworkGuardBlocked(RuntimeError):
    """历史审计进程内出现任何出站/解析/provider 构造尝试即失败。"""


class _GuardCounters:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.socket_attempts = 0
        self.dns_attempts = 0
        self.provider_entry_attempts = 0

    def snapshot(self) -> dict[str, int]:
        return {
            "socket_attempts": int(self.socket_attempts),
            "dns_attempts": int(self.dns_attempts),
            "provider_entry_attempts": int(self.provider_entry_attempts),
        }


GUARD_COUNTERS = _GuardCounters()


def _provider_targets() -> list[tuple[Any, str]]:
    targets: list[tuple[Any, str]] = []
    try:
        import httpx

        targets.extend(
            [
                (httpx.Client, "__init__"),
                (httpx.AsyncClient, "__init__"),
                (httpx, "post"),
                (httpx, "get"),
            ]
        )
    except Exception:  # noqa: BLE001 - 没有 httpx 就没有该入口
        pass
    try:
        from mktkb.evaluation import p2_live

        for name in ("run_live_p2", "build_live_adapter", "open_live_gate", "load_live_env"):
            if hasattr(p2_live, name):
                targets.append((p2_live, name))
    except Exception:  # noqa: BLE001 - 未导入即无入口
        pass
    try:
        from mktkb.evaluation import product_adapter

        for name in ("LiveProductAdapter", "build_product_adapter"):
            if hasattr(product_adapter, name):
                targets.append((product_adapter, name))
    except Exception:  # noqa: BLE001
        pass
    return targets


@contextmanager
def network_guard(enabled: bool = True):
    """进程内阻断出站 socket + DNS 解析 + provider/检索入口构造。

    这不是「自报 zero_model_calls」：计数器由**实际尝试**递增；独立子进程另用 sitecustomize
    再测一遍（见测试）。退出时逐项还原，不改父进程/系统配置。
    """
    if not enabled:
        yield
        return
    saved_socket = {
        "socket": socket.socket,
        "create_connection": socket.create_connection,
        "socketpair": socket.socketpair,
        "getaddrinfo": socket.getaddrinfo,
    }
    provider_saved: list[tuple[Any, str, Any]] = []

    def _deny_socket(*_args: Any, **_kwargs: Any) -> Any:
        GUARD_COUNTERS.socket_attempts += 1
        raise NetworkGuardBlocked("network_blocked")

    def _deny_dns(*_args: Any, **_kwargs: Any) -> Any:
        GUARD_COUNTERS.dns_attempts += 1
        raise NetworkGuardBlocked("dns_blocked")

    class _DeniedSocket(saved_socket["socket"]):  # type: ignore[misc]
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            GUARD_COUNTERS.socket_attempts += 1
            raise NetworkGuardBlocked("network_blocked")

    def _deny_provider(*_args: Any, **_kwargs: Any) -> Any:
        GUARD_COUNTERS.provider_entry_attempts += 1
        raise NetworkGuardBlocked("provider_blocked")

    try:
        socket.socket = _DeniedSocket  # type: ignore[assignment]
        socket.create_connection = _deny_socket  # type: ignore[assignment]
        socket.socketpair = _deny_socket  # type: ignore[assignment]
        socket.getaddrinfo = _deny_dns  # type: ignore[assignment]
        for owner, name in _provider_targets():
            try:
                provider_saved.append((owner, name, getattr(owner, name)))
                setattr(owner, name, _deny_provider)
            except Exception:  # noqa: BLE001 - 不可写的入口跳过，不影响 socket/DNS 阻断
                continue
        yield
    finally:
        socket.socket = saved_socket["socket"]  # type: ignore[assignment]
        socket.create_connection = saved_socket["create_connection"]  # type: ignore[assignment]
        socket.socketpair = saved_socket["socketpair"]  # type: ignore[assignment]
        socket.getaddrinfo = saved_socket["getaddrinfo"]  # type: ignore[assignment]
        for owner, name, original in reversed(provider_saved):
            try:
                setattr(owner, name, original)
            except Exception:  # noqa: BLE001
                continue


# --------------------------------------------------------------------------- #
# 受控工具复用（不修改其字节；只调用其已冻结函数）
# --------------------------------------------------------------------------- #

_CONTROLLED: Any = None


def _load_controlled() -> Any:
    global _CONTROLLED
    if _CONTROLLED is not None:
        return _CONTROLLED
    if not CONTROLLED_TOOL.is_file():
        _refuse("controlled_tool_missing")
    spec = importlib.util.spec_from_file_location("_p2_h2_controlled_for_audit", CONTROLLED_TOOL)
    if spec is None or spec.loader is None:
        _refuse("controlled_tool_unloadable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:  # noqa: BLE001 - 固定码，不回显异常链
        sys.modules.pop(spec.name, None)
        _refuse("controlled_tool_unloadable")
    _CONTROLLED = module
    return module


def _controlled() -> Any:
    return _load_controlled()


def analysis_code_digest() -> str:
    """本次分析的源码身份（当前工作树字节）。独立函数便于测试注入合成身份。"""
    return str(_controlled().code_digest())


def _sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _tree_identity(root: Path | str) -> dict[str, Any]:
    """树摘要（只回摘要/计数，不回文件列表）；超限时 available=False（不冒充已核）。"""
    base = Path(root)
    if not base.exists():
        return {"available": False, "reason": "root_missing"}
    files: list[tuple[str, str, int]] = []
    total = 0
    try:
        for path in sorted(p for p in base.rglob("*") if p.is_file()):
            if len(files) >= MAX_TREE_FILES_FOR_GUARD:
                return {"available": False, "reason": "too_many_files"}
            digest = _sha256_file(path)
            size = path.stat().st_size
            total += size
            if total > MAX_HISTORICAL_BYTES_FOR_GUARD:
                return {"available": False, "reason": "too_many_bytes"}
            files.append((path.relative_to(base).as_posix(), digest, size))
    except OSError:
        return {"available": False, "reason": "unreadable"}
    joined = "\n".join(f"{name}:{digest}" for name, digest, _size in files)
    return {
        "available": True,
        "tree_sha256": hashlib.sha256(joined.encode("utf-8")).hexdigest(),
        "file_count": len(files),
        "bytes": total,
    }


def _tree_files(root: Path | str) -> dict[str, dict[str, Any]]:
    base = Path(root)
    rows: dict[str, dict[str, Any]] = {}
    for path in sorted(p for p in base.rglob("*") if p.is_file()):
        rows[path.relative_to(base).as_posix()] = {
            "sha256": _sha256_file(path),
            "bytes": path.stat().st_size,
        }
    return rows


# --------------------------------------------------------------------------- #
# 路径边界
# --------------------------------------------------------------------------- #


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _resolve(path: Path | str, code: str) -> Path:
    try:
        return Path(path).expanduser().resolve(strict=False)
    except (OSError, TypeError, ValueError):
        _refuse(code)


def _require_inside(path: Path | str, root: Path, what: str) -> Path:
    resolved = _resolve(path, "path_invalid")
    if resolved != root and not _is_within(resolved, root):
        _refuse("path_outside_historical_root", what)
    return resolved


def _require_output_dir(path: Path | str, root: Path) -> Path:
    resolved = _controlled().require_new_dir(path, "out_dir")
    if _is_within(resolved, root):
        _refuse("output_inside_historical_root", "out_dir")
    return resolved


def _require_output_file(path: Path | str, root: Path) -> Path:
    resolved = _controlled().require_outside_repo(path, "out_card")
    if _is_within(resolved, root):
        _refuse("output_inside_historical_root", "out_card")
    if resolved.exists():
        _refuse("output_already_exists", "out_card")
    return resolved


# --------------------------------------------------------------------------- #
# 原始执行源码可重建性（与本次分析身份严格分列）
# --------------------------------------------------------------------------- #

CODE_SCOPES: tuple[str, ...] = (
    "backend/src/mktkb",
    "tools/p2_h2_controlled_execute.py",
)


def _in_code_scope(rel: str) -> bool:
    normalized = rel.replace("\\", "/")
    for scope in CODE_SCOPES:
        if normalized == scope:
            return True
        if normalized.startswith(scope.rstrip("/") + "/"):
            return True
    return False


MAX_FREEZE_ENTRIES = 20_000
MAX_FREEZE_BYTES = 8 * 1024 * 1024
MAX_HISTORICAL_BYTES_FOR_GUARD = 2 * 1024 * 1024 * 1024


def _safe_relative(rel: Any) -> str | None:
    """冻结清单里的路径必须是**相对**、无 `..`、无盘符/绝对前缀；否则视为不可信清单。"""
    if not isinstance(rel, str) or not rel.strip():
        return None
    text = rel.replace("\\", "/")
    if text.startswith("/") or re.match(r"^[A-Za-z]:", text):
        return None
    parts = [part for part in text.split("/") if part not in {"", "."}]
    if not parts or any(part == ".." for part in parts):
        return None
    return "/".join(parts)


def _parse_freeze_manifest(payload: Any) -> tuple[dict[str, str], str | None, int]:
    """容忍两种冻结清单形状：files=[{path,sha256}] 或 files={path: sha256}。

    返回 (code-scope 内的合法条目, manifest 自带的 aggregate, 被拒绝的越界条目数)。
    越界路径（绝对/`..`/盘符）一律**不读取**，只计数；全部越界即视为清单非法。
    """
    if not isinstance(payload, Mapping):
        _refuse("original_source_freeze_invalid", "root")
    rows = payload.get("files")
    mapping: dict[str, str] = {}
    rejected = 0
    total = 0
    if isinstance(rows, Mapping):
        items = list(rows.items())
    elif isinstance(rows, Sequence) and not isinstance(rows, (str, bytes)):
        items = []
        for item in rows:
            if not isinstance(item, Mapping):
                _refuse("original_source_freeze_invalid", "files_item")
            items.append((item.get("path"), item.get("sha256")))
    else:
        _refuse("original_source_freeze_invalid", "files")
    if len(items) > MAX_FREEZE_ENTRIES:
        _refuse("original_source_freeze_invalid", "too_many_entries")
    for raw_path, digest in items:
        total += 1
        if not isinstance(digest, str) or len(digest) != 64:
            _refuse("original_source_freeze_invalid", "digest")
        safe = _safe_relative(raw_path)
        if safe is None:
            rejected += 1
            continue
        if not _in_code_scope(safe) or not safe.endswith(".py"):
            continue
        mapping[safe] = digest
    if rejected:
        _refuse("original_source_freeze_invalid", "path_outside_scope")
    if not mapping:
        _refuse("original_source_freeze_invalid", "no_code_scope_entries")
    aggregate = None
    for key in ("aggregate_sha256", "tree_sha256", "sha256"):
        value = payload.get(key)
        if isinstance(value, str):
            aggregate = value
            break
    return mapping, aggregate, total - len(mapping) - rejected


def _code_digest_from_hash_map(mapping: Mapping[str, str]) -> str | None:
    rows = [
        (rel.replace("\\", "/"), digest)
        for rel, digest in mapping.items()
        if _in_code_scope(rel.replace("\\", "/")) and str(rel).endswith(".py")
    ]
    if not rows:
        return None
    lines = [f"{rel}:{digest}" for rel, digest in sorted(rows)]
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def _original_source_freeze(
    *,
    recorded_code_version: str,
    freeze_path: Path | str | None,
    source_root: Path | str | None,
) -> dict[str, Any]:
    """单列「原码可重建性」：只有清单时只能核身份可复算性，不能宣称重建了原程序。"""
    payload: dict[str, Any] = {
        "status": "unavailable",
        "manifest_provided": freeze_path is not None,
        "source_root_provided": source_root is not None,
        "recorded_execution_code_sha256": str(recorded_code_version),
        "manifest_aggregate_sha256": None,
        "manifest_aggregate_verified": None,
        "manifest_file_count": None,
        "manifest_other_scope_entries": None,
        "code_scope_file_count": None,
        "code_version_reproduced_from_manifest": None,
        "code_version_reproduced": None,
        "manifest_bytes_verified": None,
        "claims_original_program_reconstructed": False,
    }
    if freeze_path is None and source_root is None:
        return payload
    mapping: dict[str, str] = {}
    if freeze_path is not None:
        target = Path(freeze_path)
        if not target.is_file():
            _refuse("original_source_freeze_missing")
        try:
            if target.stat().st_size > MAX_FREEZE_BYTES:
                _refuse("original_source_freeze_invalid", "too_large")
            raw = target.read_text(encoding="utf-8")
            parsed = json.loads(raw)
        except (OSError, UnicodeDecodeError, ValueError):
            _refuse("original_source_freeze_invalid", "read")
        mapping, aggregate, other = _parse_freeze_manifest(parsed)
        payload["manifest_aggregate_sha256"] = aggregate
        payload["manifest_other_scope_entries"] = int(other)
        payload["manifest_file_count"] = len(mapping) + int(other)
        payload["code_scope_file_count"] = len(mapping)
        verified = _verify_freeze_aggregate(parsed, aggregate)
        payload["manifest_aggregate_verified"] = verified
        reproduced = _code_digest_from_hash_map(mapping)
        payload["code_version_reproduced_from_manifest"] = reproduced == str(
            recorded_code_version
        )
        payload["code_version_reproduced"] = payload["code_version_reproduced_from_manifest"]
        payload["status"] = "identity_only_manifest_no_bytes"
    if source_root is not None:
        root = Path(source_root)
        if not root.is_dir():
            _refuse("original_source_root_missing")
        if not mapping:
            _refuse("original_source_root_without_manifest")
        root_resolved = root.resolve()
        mismatched = 0
        missing = 0
        for rel, expected in mapping.items():
            target = (root_resolved / rel).resolve()
            if not _is_within(target, root_resolved):
                _refuse("original_source_freeze_invalid", "path_escape")
            if not target.is_file():
                missing += 1
                continue
            if _sha256_file(target) != expected:
                mismatched += 1
        payload["manifest_bytes_verified"] = mismatched == 0 and missing == 0
        if mismatched or missing:
            payload["status"] = "bytes_mismatch"
            # C3：字节不匹配时不得保留“清单可复算”的 true 让人误读成“字节已复现”。
            payload["code_version_reproduced"] = False
            payload["claims_original_program_reconstructed"] = False
            return payload
        recomputed = _recompute_code_digest_from_root(root, mapping)
        payload["code_version_reproduced"] = recomputed == str(recorded_code_version)
        payload["status"] = (
            "verified_from_frozen_bytes" if payload["code_version_reproduced"] else "bytes_mismatch"
        )
        payload["claims_original_program_reconstructed"] = bool(
            payload["code_version_reproduced"]
        )
    return payload


def _verify_freeze_aggregate(parsed: Any, aggregate: str | None) -> bool | None:
    """只有清单自带 aggregate 时才有意义；两种常见口径都不匹配就如实记 false（不猜）。"""
    if aggregate is None:
        return None
    rows = parsed.get("files") if isinstance(parsed, Mapping) else None
    pairs: list[tuple[str, str]] = []
    if isinstance(rows, Mapping):
        pairs = [(str(k), str(v)) for k, v in rows.items()]
    elif isinstance(rows, Sequence) and not isinstance(rows, (str, bytes)):
        for item in rows:
            if isinstance(item, Mapping):
                pairs.append((str(item.get("path")), str(item.get("sha256"))))
    joined = "\n".join(f"{name}:{digest}" for name, digest in sorted(pairs))
    if hashlib.sha256(joined.encode("utf-8")).hexdigest() == aggregate:
        return True
    canonical = json.dumps(
        {name: digest for name, digest in sorted(pairs)},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest() == aggregate


def _recompute_code_digest_from_root(root: Path, mapping: Mapping[str, str]) -> str | None:
    """按冻结清单里登记的路径与字节，用与 code_digest() 相同的口径复算。"""
    rows = [
        (rel.replace("\\", "/"), digest)
        for rel, digest in mapping.items()
        if _in_code_scope(rel.replace("\\", "/")) and str(rel).endswith(".py")
    ]
    if not rows:
        return None
    lines = [f"{rel}:{digest}" for rel, digest in sorted(rows)]
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- #
# 逐 turn 审计结构（与受控工具 `_recompute_loaded` 同口径；用于原因聚合与交叉核）
# --------------------------------------------------------------------------- #


def _require_supported_evidence_schema(envelope: Mapping[str, Any]) -> None:
    """旧历史审计只接受历史证据版本；v0.3* 固定 unsupported，不静默降级。"""
    if str(envelope.get("schema_version")) not in SUPPORTED_EVIDENCE_SCHEMA_VERSIONS:
        _refuse("unsupported_evidence_schema")


def _turn_audits(
    *,
    cases: Sequence[Any],
    case_plan: Mapping[str, Any],
    evidence_dir: Path,
    key: bytes,
    bindings: Mapping[str, str],
    run_binding: Mapping[str, str],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    evidence_io = _evidence_io()
    root = evidence_dir.resolve()
    audits: list[dict[str, Any]] = []
    seen: set[str] = set()
    status_counts: dict[str, int] = {}
    executed = 0
    for case, row in zip(cases, case_plan["cases"]):
        entries: list[dict[str, Any]] = []
        for turn_row in row["turns"]:
            track: dict[str, Any] = {
                "turn_index": int(turn_row["turn_index"]),
                "status": str(turn_row["status"]),
                "error": turn_row.get("error"),
                "evidence": None,
            }
            if track["status"] == "executed":
                name = str(turn_row["evidence_file"])
                if name in seen:
                    _refuse("case_plan_evidence_file_duplicate")
                seen.add(name)
                target = (root / name).resolve()
                if not _is_within(target, root):
                    _refuse("case_plan_evidence_file_invalid")
                if not target.is_file():
                    _refuse("case_plan_evidence_file_missing")
                try:
                    envelope = evidence_io.read_encrypted_evidence(
                        target, key=key, expected_bindings=dict(bindings)
                    )
                except evidence_io.EvidenceIOError as exc:
                    _refuse("evidence_invalid", str(getattr(exc, "code", "evidence_io_failed")))
                # 新版本证据（v0.3*）不在旧历史审计范围：固定拒绝，不静默降级。
                _require_supported_evidence_schema(envelope)
                if dict(envelope.get("run_binding") or {}) != dict(run_binding):
                    _refuse("evidence_run_binding_mismatch")
                turn_meta = envelope.get("turn") if isinstance(envelope.get("turn"), Mapping) else {}
                if int(turn_meta.get("turn_index", -1)) != int(turn_row["turn_index"]):
                    _refuse("evidence_turn_index_mismatch")
                completeness = (
                    envelope.get("completeness")
                    if isinstance(envelope.get("completeness"), Mapping)
                    else {}
                )
                status = str(completeness.get("status"))
                status_counts[status] = status_counts.get(status, 0) + 1
                executed += 1
                track["evidence"] = envelope
            entries.append(track)
        audits.append({"quality_status": row["quality_status"], "turns": entries})
    return audits, {
        "executed_turns": executed,
        "evidence_files": len(seen),
        "status_counts": dict(status_counts),
    }


def _hard() -> Any:
    return _controlled().hard


def _evidence_io() -> Any:
    from mktkb.evaluation import p2_evidence_io

    return p2_evidence_io


# --------------------------------------------------------------------------- #
# reason 聚合（只出固定词表 + 计数，绝不回逐题号/原文）
# --------------------------------------------------------------------------- #


def _fixed_reason_vocabulary() -> frozenset[str]:
    hard = _hard()
    values: set[str] = set(str(item) for item in hard.REASONS)
    for mapping in (hard.PASS_REASONS, hard.NA_REASONS):
        for item in mapping.values():
            values.add(str(item))
    for mapping in (hard.UNKNOWN_REASONS_BY_AXIS, hard.VIOLATION_REASONS_BY_AXIS):
        for items in mapping.values():
            for item in items:
                values.add(str(item))
    values.update({"turn_error", "turn_not_executed", "none", "unregistered_reason"})
    return frozenset(values)


def _reasons_payload(results: Sequence[Any]) -> dict[str, Any]:
    hard = _hard()
    vocabulary = _fixed_reason_vocabulary()
    axis_counts: dict[str, dict[str, int]] = {name: {} for name in hard.AXES}
    case_counts: dict[str, int] = {}
    unregistered = 0
    for item in results:
        case_reason = "none"
        for name in hard.AXES:
            verdict = item.axes[name]
            if verdict.state not in {"unknown", "violation"}:
                continue
            reason = str(verdict.reason)
            if reason not in vocabulary:
                reason = "unregistered_reason"
                unregistered += 1
            bucket = axis_counts[name]
            bucket[reason] = bucket.get(reason, 0) + 1
            if case_reason == "none" and verdict.state == "unknown":
                case_reason = reason
        case_counts[case_reason] = case_counts.get(case_reason, 0) + 1
    return {
        "axis_counts": {name: dict(sorted(counts.items())) for name, counts in axis_counts.items()},
        "case_counts": dict(sorted(case_counts.items())),
        "unregistered": unregistered,
        "vocabulary_size": len(vocabulary),
    }


# --------------------------------------------------------------------------- #
# 公开产物安全门
# --------------------------------------------------------------------------- #


def _strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _strings(item)


def _assert_public_safe(payload: Mapping[str, Any]) -> dict[str, Any]:
    forbidden: list[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, Mapping):
            for key, item in value.items():
                if str(key) in FORBIDDEN_PUBLIC_KEYS:
                    forbidden.append(str(key))
                walk(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                walk(item)

    walk(payload)
    long_strings = 0
    control_strings = 0
    secret_shapes = 0
    for text in _strings(payload):
        if len(text) > MAX_PUBLIC_STRING:
            long_strings += 1
        if "\n" in text or "\r" in text or "\x00" in text:
            control_strings += 1
        if SECRET_SHAPE.search(text):
            secret_shapes += 1
    if forbidden or long_strings or control_strings or secret_shapes:
        _refuse("public_output_unsafe")
    return {
        "forbidden_keys": sorted(set(forbidden)),
        "long_strings": long_strings,
        "control_strings": control_strings,
        "secret_shape_hits": secret_shapes,
    }


def _scan_public_bytes(raw: bytes, needles: Sequence[str], key: bytes) -> dict[str, Any]:
    hits = 0
    for needle in needles:
        if needle and needle.encode("utf-8") in raw:
            hits += 1
    return {
        "bytes": len(raw),
        "needles": len(needles),
        "hits": hits,
        "key_material_hits": 1 if key and key in raw else 0,
        "secret_shape_hits": 1 if SECRET_SHAPE.search(raw.decode("utf-8", "ignore")) else 0,
    }


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _money(value: Any) -> float:
    try:
        return round(float(value), 8)
    except (TypeError, ValueError):
        return 0.0


def _reduced_funding(funding: Mapping[str, Any]) -> dict[str, Any]:
    """账本核算只出计数/金额/前缀布尔，不出预约 ID 列表。"""
    return {
        "available": bool(funding.get("available")),
        "run_rows": int(funding.get("run_rows") or 0),
        "reservations": int(funding.get("reservations") or 0),
        "results": int(funding.get("results") or 0),
        "duplicate_reservations": int(funding.get("duplicate_reservations") or 0),
        "duplicate_results": int(funding.get("duplicate_results") or 0),
        "unpaired_reservations": len(funding.get("unpaired_reservations") or ()),
        "orphan_results": len(funding.get("orphan_results") or ()),
        "paired_one_to_one": bool(funding.get("paired_one_to_one")),
        "reserved_cny": _money(funding.get("reserved_cny")),
        "settled_cny": _money(funding.get("settled_cny")),
        "result_status_counts": {
            str(key): int(value)
            for key, value in dict(funding.get("result_status_counts") or {}).items()
        },
        "ledger_sha256": str(funding.get("ledger_sha256") or ""),
        "prefix_binding_ok": funding.get("prefix_binding_ok"),
        "receipt_attempts_match": funding.get("receipt_attempts_match"),
    }


def _ledger_row_counts(ledger_path: Path, run_ids: Sequence[str]) -> dict[str, int]:
    wanted = {str(item) for item in run_ids}
    counts = {name: 0 for name in wanted}
    try:
        text = ledger_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        _refuse("ledger_unreadable")
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except ValueError:
            _refuse("ledger_invalid")
        if not isinstance(event, Mapping):
            _refuse("ledger_invalid")
        run_id = str(event.get("run_id") or "")
        if run_id in wanted:
            counts[run_id] += 1
    return counts


def _not_started_verification(
    *,
    document: Mapping[str, Any],
    run_index: int,
    evidence_dir: Path,
    seal_dir: Path,
    run_out_root: Path | None,
    ledger_counts: Mapping[str, int],
) -> dict[str, Any]:
    runs = list(document["runs"])
    rows: dict[str, Any] = {}
    verified_all = True
    for index, entry in enumerate(runs):
        if index == run_index:
            continue
        run_id = str(entry["run_id"])
        dirs: dict[str, Path | None] = {
            "evidence": evidence_dir.parent.parent / f"r{index}",
            "seal": seal_dir.parent.parent / f"r{index}",
            "runs": None if run_out_root is None else run_out_root.parent / f"r{index}",
        }
        absent = {name: (path is None or not path.exists()) for name, path in dirs.items()}
        rows[run_id] = {
            "dirs_absent": absent,
            "ledger_rows": int(ledger_counts.get(run_id, 0)),
            "not_started": all(absent.values()) and int(ledger_counts.get(run_id, 0)) == 0,
        }
        if not rows[run_id]["not_started"]:
            verified_all = False
    return {
        "total": len(runs),
        "audited_index": int(run_index),
        "not_started": [str(entry["run_id"]) for index, entry in enumerate(runs) if index != run_index and rows[str(entry["run_id"])]["not_started"]],
        "verified": verified_all,
        "runs": rows,
        "out_root_provided": run_out_root is not None,
    }


def audit_historical(
    *,
    historical_root: Path | str,
    binding_path: Path | str,
    run_index: int,
    evidence_dir: Path | str,
    evidence_key_file: Path | str,
    case_plan_path: Path | str,
    receipt_path: Path | str,
    seal_manifest_path: Path | str,
    ledger_path: Path | str,
    holdout_root: Path | str,
    holdout_key_file: Path | str,
    project_total_limit_cny: float,
    out_dir: Path | str,
    out_card: Path | str | None = None,
    run_out_root: Path | str | None = None,
    original_source_freeze: Path | str | None = None,
    original_source_root: Path | str | None = None,
    expected_identity_path: Path | str | None = None,
    network_guard_enabled: bool = True,
) -> dict[str, Any]:
    """只读历史审计：严格核旧 run 内部身份 -> 用已接收分类器重算四轴 -> 输出固定 schema。"""
    GUARD_COUNTERS.reset()
    with network_guard(enabled=bool(network_guard_enabled)):
        try:
            return _audit_locked(
                historical_root=historical_root,
                binding_path=binding_path,
                run_index=run_index,
                evidence_dir=evidence_dir,
                evidence_key_file=evidence_key_file,
                case_plan_path=case_plan_path,
                receipt_path=receipt_path,
                seal_manifest_path=seal_manifest_path,
                ledger_path=ledger_path,
                holdout_root=holdout_root,
                holdout_key_file=holdout_key_file,
                project_total_limit_cny=project_total_limit_cny,
                out_dir=out_dir,
                out_card=out_card,
                run_out_root=run_out_root,
                original_source_freeze=original_source_freeze,
                original_source_root=original_source_root,
                expected_identity_path=expected_identity_path,
                network_guard_enabled=bool(network_guard_enabled),
            )
        except NetworkGuardBlocked:  # pragma: no cover - 正常路径不应触发
            _refuse("network_blocked")
        except EntryError:
            raise
        except Exception as exc:  # noqa: BLE001 - 受控工具/分类器异常统一转固定码
            _translate_exception(exc)


def _translate_exception(exc: BaseException) -> NoReturn:
    controlled = _CONTROLLED
    if controlled is not None:
        for name in ("EntryError",):
            cls = getattr(controlled, name, None)
            if isinstance(cls, type) and isinstance(exc, cls):
                raise EntryError(
                    str(getattr(exc, "code", "refused")),
                    str(getattr(exc, "detail", "")),
                    int(getattr(exc, "exit_code", EXIT_REFUSED)),
                ) from None
    hard = getattr(controlled, "hard", None)
    if hard is not None and isinstance(exc, getattr(hard, "HardEvidenceError", ())):
        raise EntryError("hard_evidence_invalid", str(exc)[:120]) from None
    raise EntryError("internal_error", type(exc).__name__) from None


def _audit_locked(
    *,
    historical_root: Path | str,
    binding_path: Path | str,
    run_index: int,
    evidence_dir: Path | str,
    evidence_key_file: Path | str,
    case_plan_path: Path | str,
    receipt_path: Path | str,
    seal_manifest_path: Path | str,
    ledger_path: Path | str,
    holdout_root: Path | str,
    holdout_key_file: Path | str,
    project_total_limit_cny: float,
    out_dir: Path | str,
    out_card: Path | str | None,
    run_out_root: Path | str | None,
    original_source_freeze: Path | str | None,
    original_source_root: Path | str | None,
    expected_identity_path: Path | str | None,
    network_guard_enabled: bool,
) -> dict[str, Any]:
    controlled = _controlled()
    root = controlled.require_outside_repo(historical_root, "historical_root")
    if not root.exists() or not root.is_dir():
        _refuse("historical_root_missing")

    binding = _require_inside(binding_path, root, "run_binding")
    evidence = _require_inside(evidence_dir, root, "evidence_dir")
    if not evidence.is_dir():
        _refuse("evidence_dir_missing")
    evidence_root = evidence.parent
    key_file = _require_inside(evidence_key_file, root, "evidence_key_file")
    case_plan_file = _require_inside(case_plan_path, root, "case_plan")
    receipt_file = _require_inside(receipt_path, root, "run_receipt")
    seal_file = _require_inside(seal_manifest_path, root, "seal_manifest")
    out_root = None
    if run_out_root is None:
        # C6：out 树摘要是 seal 的一半，缺失就不能当硬门 → 必填。
        _usage("run_out_root_required")
    out_root = _require_inside(run_out_root, root, "run_out_root")
    for name, target in (
        ("run_binding", binding),
        ("case_plan", case_plan_file),
        ("run_receipt", receipt_file),
        ("seal_manifest", seal_file),
        ("evidence_key_file", key_file),
    ):
        if not target.is_file():
            _refuse("input_file_missing", name)
    if not evidence.is_dir():
        _refuse("evidence_dir_missing")
    if out_root is not None and not out_root.is_dir():
        _refuse("run_out_root_missing")
    checked_out = _require_output_dir(out_dir, root)
    checked_card = None if out_card is None else _require_output_file(out_card, root)

    snapshot_before = _tree_identity(root)

    document = controlled.load_run_binding(binding)
    run_entry = controlled._select_run(document, run_index)
    controlled._verify_input_digests(document)
    plan = controlled._load_plan_for_run(document, run_entry)
    controlled._verify_plan_binding(document, run_entry, plan)

    runtime = controlled.check_runtime_options(
        controlled.RuntimeOptions(
            holdout_root=Path(holdout_root),
            holdout_key_file=Path(holdout_key_file),
            project_total_limit_cny=float(project_total_limit_cny),
        )
    )
    business_date = str(document["business_date"])
    bundle = controlled.load_private_bundle(
        {}, controlled._paths_from_document(document), runtime=runtime
    )
    dataset_turns = controlled._validate_dataset_shape(bundle.dataset, business_date)
    annotation_schema = Path(str(document["inputs"]["annotation_schema"]["path"]))
    scenario_contract = Path(str(document["inputs"]["scenario_contract"]["path"]))
    merged = controlled._prepare_annotation(bundle, annotation_schema, scenario_contract)
    controlled._verify_axis_counts(merged, bundle.addendum_acceptance)

    scenario = str(run_entry["scenario_id"])
    scenario_binding = bundle.contract.binding(scenario)
    if dict(scenario_binding) != dict(run_entry["scenario_binding"]):
        _refuse("scenario_binding_changed")
    subset = bundle.contract.subset(scenario)
    cases = tuple(subset.cases)
    if len(cases) != int(run_entry["case_count"]):
        _refuse("scenario_subset_changed", "cases")
    subset_turns = sum(len(controlled.case_questions(case)) for case in cases)
    if subset_turns != int(run_entry["turn_count"]):
        _refuse("scenario_subset_changed", "turns")
    for case in cases:
        if str(case.business_date or "") != business_date:
            _refuse("business_date_case_mismatch")

    key = key_file.read_bytes()
    if len(key) != 44:
        _refuse("evidence_key_invalid")
    try:
        from cryptography.fernet import Fernet

        Fernet(key)
    except Exception:  # noqa: BLE001 - 结构非法统一固定码
        _refuse("evidence_key_invalid")

    receipt = _read_mapping(receipt_file, "run_receipt_unreadable")
    if receipt.get("schema_version") != controlled.RUN_RECEIPT_SCHEMA_VERSION:
        _refuse("run_receipt_invalid", "schema_version")
    if (
        str(receipt.get("run_id")) != str(run_entry["run_id"])
        or str(receipt.get("scenario_id")) != scenario
        or str(receipt.get("plan_sha256")) != str(plan.plan_sha256)
    ):
        _refuse("run_receipt_binding_mismatch")
    if str(receipt.get("evidence_key_sha256")) != hashlib.sha256(key).hexdigest():
        _refuse("evidence_key_mismatch")
    receipt_paths = receipt.get("paths") if isinstance(receipt.get("paths"), Mapping) else {}
    # 只核**相对结构**（run 目录名 / 密文根名），不要求绝对路径一致：
    # 独立复核可能把只读历史根挂到别的盘符，绝对路径等价性不是来源可信的证明。
    if str(receipt_paths.get("evidence_root") or "") and Path(
        str(receipt_paths["evidence_root"])
    ).name != evidence_root.name:
        _refuse("run_receipt_binding_mismatch", "evidence_root")
    if str(receipt_paths.get("evidence_dir") or "") and Path(
        str(receipt_paths["evidence_dir"])
    ).name != evidence.name:
        _refuse("run_receipt_binding_mismatch", "evidence_dir")
    receipt_bindings = receipt.get("bindings") if isinstance(receipt.get("bindings"), Mapping) else {}
    for key_name, expected in (
        ("binding_sha256", str(document["binding_sha256"])),
        ("config_sha256", str(document["config_sha256"])),
        ("code_version", str(document["code_version"])),
    ):
        if str(receipt_bindings.get(key_name)) != expected:
            _refuse("run_receipt_binding_mismatch", key_name)

    seal = _read_mapping(seal_file, "seal_manifest_unreadable")
    if seal.get("schema_version") != controlled.SEAL_MANIFEST_SCHEMA_VERSION:
        _refuse("seal_manifest_invalid", "schema_version")
    if str(seal.get("run_id")) != str(run_entry["run_id"]):
        _refuse("seal_manifest_binding_mismatch", "run_id")
    if str(seal.get("mode")) != "read_only_archive":
        _refuse("seal_manifest_invalid", "mode")
    receipt_seal = receipt.get("seal") if isinstance(receipt.get("seal"), Mapping) else {}
    if str(receipt_seal.get("seal_manifest_sha256")) != _sha256_file(seal_file):
        _refuse("seal_manifest_binding_mismatch", "sha256")

    evidence_tree = _tree_identity(evidence_root)
    if not evidence_tree.get("available"):
        _refuse("evidence_tree_unreadable")
    for expected_tree, source in (
        (receipt_seal.get("evidence_tree_sha256"), "receipt"),
        ((seal.get("evidence_root") or {}).get("tree_sha256"), "seal_manifest"),
    ):
        if str(expected_tree or "") != str(evidence_tree["tree_sha256"]):
            _refuse("evidence_tree_sha_mismatch", source)
    if int(receipt_seal.get("evidence_file_count") or -1) != int(evidence_tree["file_count"]):
        _refuse("evidence_tree_file_count_mismatch", "receipt")
    if int(receipt_seal.get("evidence_bytes") or -1) != int(evidence_tree["bytes"]):
        _refuse("evidence_tree_bytes_mismatch", "receipt")

    case_plan_payload = _read_mapping(case_plan_file, "case_plan_unreadable")
    case_plan_sha = _sha256_file(case_plan_file)
    receipt_case_plan = (
        receipt.get("case_plan") if isinstance(receipt.get("case_plan"), Mapping) else {}
    )
    if str(receipt_case_plan.get("sha256") or "") != case_plan_sha:
        _refuse("case_plan_sha256_mismatch")
    static_bindings = {
        name: value
        for name, value in dict(run_entry["evidence_bindings"]).items()
        if name != "index_revision"
    }
    resolved_plan = controlled._validate_case_plan_document(
        case_plan_payload, cases=cases, static_bindings=static_bindings
    )
    if str(resolved_plan["run_id"]) != str(run_entry["run_id"]):
        _refuse("case_plan_binding_mismatch", "run_id")
    control = dict(resolved_plan["run_binding"])
    if (
        str(control.get("plan_sha256")) != str(plan.plan_sha256)
        or str(control.get("business_date")) != business_date
        or str(control.get("scenario_id")) != scenario
    ):
        _refuse("case_plan_binding_mismatch", "run_binding")
    if dict(receipt.get("run_binding") or {}) != control:
        _refuse("run_receipt_binding_mismatch", "run_binding")
    for key_name in ("go_sha256", "ledger_sha256", "attempt_scope_sha256"):
        if str(receipt_bindings.get(key_name)) != str(control.get(key_name)):
            _refuse("run_receipt_binding_mismatch", key_name)
    # `index_revision` 在 run binding 里是 ingest 前占位符，ingest 后由 case-plan 记录实际值；
    # 其余 15 键必须逐字一致（与 _validate_case_plan_document 的 static_bindings 同口径）。
    static_expected = {
        k: str(v) for k, v in dict(run_entry["evidence_bindings"]).items() if k != "index_revision"
    }
    static_actual = {
        k: v for k, v in dict(resolved_plan["bindings"]).items() if k != "index_revision"
    }
    if static_actual != static_expected:
        _refuse("case_plan_binding_mismatch", "bindings")

    evidence_files = _evidence_file_expectation(
        resolved_plan, evidence_root=evidence, evidence_parent=evidence_root
    )
    actual_files = set(_tree_files(evidence_root).keys())
    if evidence_files["expected"] - actual_files:
        _refuse("evidence_tree_missing_file")
    if actual_files - evidence_files["expected"]:
        _refuse("evidence_tree_extra_file")
    manifest_files = sorted(evidence.glob("manifest-*.fernet"))
    if len(manifest_files) != 1:
        _refuse("evidence_manifest_count_invalid")

    out_tree = None
    if out_root is not None:
        out_tree = _tree_identity(out_root)
        if not out_tree.get("available"):
            _refuse("run_out_root_unreadable")
        if str(receipt_seal.get("out_tree_sha256") or "") != str(out_tree["tree_sha256"]):
            _refuse("seal_out_tree_mismatch", "receipt")
        if str((seal.get("out_dir") or {}).get("tree_sha256") or "") != str(
            out_tree["tree_sha256"]
        ):
            _refuse("seal_out_tree_mismatch", "seal_manifest")
        sealed_case_plan = _sealed_case_plan_row(seal, case_plan_sha)
        if sealed_case_plan is None:
            _refuse("seal_out_tree_mismatch", "case_plan")

    run_binding = dict(control)
    audits, audit_summary = _turn_audits(
        cases=cases,
        case_plan=resolved_plan,
        evidence_dir=evidence,
        key=key,
        bindings=dict(resolved_plan["bindings"]),
        run_binding=run_binding,
    )

    result = controlled._recompute_loaded(
        document=document,
        run_entry=run_entry,
        plan=plan,
        cases=cases,
        annotation=merged,
        case_plan_payload=case_plan_payload,
        evidence_dir=evidence,
        key=key,
        ledger_path=ledger_path,
        receipt=receipt,
        out_card=checked_card,
    )
    card = result["card"]

    hard = _hard()
    plan_meta = {
        "thresholds_approved": bool(resolved_plan["thresholds_approved"]),
        "execution_mode": "live",
        "real_calls": int(resolved_plan["real_calls"]),
        "run_id": str(run_entry["run_id"]),
        "config_hash": str(document["config_sha256"]),
        "expected_strata": dict(resolved_plan["expected_strata"]),
    }
    card_cross, results = hard.recompute_hard_evidence(
        cases, merged, audits, plan_meta=plan_meta
    )
    if dict(hard.public_recompute_summary(card_cross)) != dict(card):
        _refuse("internal_inconsistency", "card_cross_check")
    if result["card_file"] is not None:
        written_card = _read_mapping(Path(str(result["card_file"]["path"])), "card_unreadable")
        if dict(written_card) != dict(card_cross):
            _refuse("internal_inconsistency", "card_file_cross_check")
    if int(audit_summary["executed_turns"]) != int(result["coverage"]["executed_turns"]):
        _refuse("internal_inconsistency", "executed_turns")
    if dict(audit_summary["status_counts"]) != dict(result["coverage"]["status_counts"]):
        _refuse("internal_inconsistency", "status_counts")

    ledger = _resolve(ledger_path, "ledger_path_invalid")
    ledger_counts = _ledger_row_counts(ledger, [str(entry["run_id"]) for entry in document["runs"]])
    runs = _not_started_verification(
        document=document,
        run_index=int(run_index),
        evidence_dir=evidence,
        seal_dir=seal_file.parent,
        run_out_root=out_root,
        ledger_counts=ledger_counts,
    )

    snapshot_after = _tree_identity(root)
    if not snapshot_before.get("available") or not snapshot_after.get("available"):
        _refuse("historical_root_unverifiable")
    if snapshot_after != snapshot_before:
        _refuse("historical_root_mutated")

    quality = _quality_payload(
        resolved_plan,
        other_cases=len(bundle.dataset.cases) - len(cases),
        dataset_cases=len(bundle.dataset.cases),
    )
    full_matrix = _full_matrix_payload(
        card=card,
        dataset_cases=len(bundle.dataset.cases),
        dataset_turns=int(dataset_turns),
        scenario_cases=len(cases),
        scenario_turns=int(subset_turns),
        plan_rows=resolved_plan["cases"],
        other_cases=len(bundle.dataset.cases) - len(cases),
        other_turns=int(dataset_turns) - int(subset_turns),
        runs=runs,
    )
    expected = _expected_identity_check(
        expected_identity_path,
        payload_values={
            "run_id": str(run_entry["run_id"]),
            "plan_id": str(plan.plan_id),
            "plan_sha256": str(plan.plan_sha256),
            "binding_sha256": str(document["binding_sha256"]),
            "config_sha256": str(document["config_sha256"]),
            "code_version": str(document["code_version"]),
            "case_plan_sha256": case_plan_sha,
            "evidence_tree_sha256": str(evidence_tree["tree_sha256"]),
            "out_tree_sha256": str(out_tree["tree_sha256"]),
        },
    )
    if not expected["ok"]:
        _refuse("expected_identity_mismatch", ",".join(expected["mismatches"])[:120])
    freeze = _original_source_freeze(
        recorded_code_version=str(document["code_version"]),
        freeze_path=original_source_freeze,
        source_root=original_source_root,
    )
    current_code = analysis_code_digest()
    analysis_sources = _analysis_source_digests()
    evidence_bindings = {str(k): str(v) for k, v in dict(resolved_plan["bindings"]).items()}

    payload: dict[str, Any] = {
        "schema_version": AUDIT_SCHEMA_VERSION,
        "tool": TOOL_SCHEMA_VERSION,
        "ok": True,
        "analysis_kind": ANALYSIS_KIND,
        "authorizes_live": False,
        "release_ready": False,
        "zero_model_calls": True,
        "zero_paid_calls": True,
        "analysis_utc": _utc_now(),
        "identity": {
            "run_id": str(run_entry["run_id"]),
            "run_index": int(run_index),
            "scenario_id": scenario,
            "plan_id": str(plan.plan_id),
            "plan_sha256": str(plan.plan_sha256),
            "binding_sha256": str(document["binding_sha256"]),
            "config_sha256": str(document["config_sha256"]),
            "business_date": business_date,
            "attempt_scope_sha256": str(control["attempt_scope_sha256"]),
            "go_sha256": str(control["go_sha256"]),
            "ledger_sha256_recorded": str(control["ledger_sha256"]),
            "original_execution_code_sha256": str(document["code_version"]),
            "analysis_code_sha256": current_code,
            "code_identity": "distinct"
            if str(document["code_version"]) != current_code
            else "identical",
            "code_identity_distinct": str(document["code_version"]) != current_code,
            "analysis_sources": analysis_sources,
            "original_source_freeze": freeze,
            "envelope_bindings": evidence_bindings,
            "evidence_tree_sha256": str(evidence_tree["tree_sha256"]),
            "evidence_file_count": int(evidence_tree["file_count"]),
            "evidence_bytes": int(evidence_tree["bytes"]),
            "case_plan_sha256": case_plan_sha,
            "run_receipt_sha256": _sha256_file(receipt_file),
            "seal_manifest_sha256": _sha256_file(seal_file),
            "run_out_tree_sha256": None if out_tree is None else str(out_tree["tree_sha256"]),
            "dataset": {
                "case_count": len(bundle.dataset.cases),
                "total_turns": int(dataset_turns),
                "dataset_version": str(document["dataset"]["dataset_version"]),
                "label_version": str(document["dataset"]["label_version"]),
                "suite": str(document["dataset"]["suite"]),
                "manifest_sha256": str(document["dataset"]["manifest_sha256"]),
                "scenario_counts": {
                    str(k): int(v)
                    for k, v in dict(document["dataset"]["scenario_counts"]).items()
                },
            },
            "inputs": {
                name: str(document["inputs"][name]["sha256"])
                for name in controlled.INPUT_NAMES
            },
            "checks": {
                "binding_sha256": True,
                "config_sha256": True,
                "plan_sha256": True,
                "plan_file_sha256": True,
                "inputs_unchanged": True,
                "scenario_binding": True,
                "dataset_shape": True,
                "case_plan_sha256": True,
                "case_plan_bindings": True,
                "case_plan_run_binding": True,
                "receipt_binding": True,
                "receipt_bindings": True,
                "receipt_evidence_key": True,
                "seal_manifest_sha256": True,
                "seal_evidence_tree": True,
                "seal_out_tree": out_tree is not None,
                "evidence_tree_matches_case_plan": True,
                "ledger_prefix": True,
                "historical_root_unchanged_during_call": True,
                "external_identity_anchor": expected["applied"],
            },
            "historical_root": {
                "file_count": int(snapshot_before.get("file_count") or 0),
                "bytes": int(snapshot_before.get("bytes") or 0),
                "tree_sha256": str(snapshot_before.get("tree_sha256") or ""),
                "scope": "call_window_only",
            },
            "external_identity_anchor": expected["detail"],
        },
        "coverage": {
            "dataset_cases": len(bundle.dataset.cases),
            "dataset_turns": int(dataset_turns),
            "scenario_cases": len(cases),
            "scenario_turns": int(subset_turns),
            "executed_turns": int(result["coverage"]["executed_turns"]),
            "evidence_files": int(result["coverage"]["evidence_files"]),
            "manifest_present": bool(result["coverage"]["manifest_present"]),
            "manifest_turn_count": result["coverage"]["manifest_turn_count"],
            "status_counts": {
                str(k): int(v) for k, v in dict(result["coverage"]["status_counts"]).items()
            },
            "cases_all_turns_executed": quality["cases_all_turns_executed"],
            "cases_with_unexecuted_turns": quality["cases_with_unexecuted_turns"],
            "expected_strata": {
                str(k): int(v) for k, v in dict(resolved_plan["expected_strata"]).items()
            },
        },
        "axes": {name: dict(card["axes"][name]) for name in _hard().AXES},
        "card": dict(card),
        "full_matrix": full_matrix,
        "quality": quality,
        "reasons": _reasons_payload(results),
        "funding": _reduced_funding(result["funding"]),
        "runs": runs,
        "guard": {
            "network_guard_enabled": bool(network_guard_enabled),
            **GUARD_COUNTERS.snapshot(),
        },
    }

    funding = _reduced_funding(result["funding"])
    payload["funding"] = funding
    # C5：GO 的账本前缀绑定是**硬门**，不是展示字段。不一致就是旧 run 绑定被破坏。
    if funding["prefix_binding_ok"] is not True:
        _refuse("ledger_prefix_mismatch")
    if funding["receipt_attempts_match"] is False:
        _refuse("run_receipt_attempts_mismatch")
    # C5b：预约/结果必须一一配对；orphan/未配对/重复都意味着资金对账不可信。
    if funding["paired_one_to_one"] is not True:
        _refuse("ledger_pairing_mismatch")
    if funding["duplicate_reservations"] or funding["duplicate_results"]:
        _refuse("ledger_pairing_mismatch", "duplicate")

    needles = _public_needles(
        bundle.dataset, getattr(bundle.dataset, "labels", None), bundle.dataset.cases
    )
    safe = _assert_public_safe(payload)
    raw = _canonical_bytes(payload)
    scan = _scan_public_bytes(raw, needles, key)
    if scan["hits"] or scan["key_material_hits"] or scan["secret_shape_hits"]:
        _refuse("public_output_leak")
    payload["privacy"] = {
        "public_scan": scan,
        "forbidden_keys": safe["forbidden_keys"],
        "long_strings": safe["long_strings"],
        "control_strings": safe["control_strings"],
        "quality_source": QUALITY_SOURCE_RECORDED,
    }
    payload["artifacts"] = {
        "card": None if result["card_file"] is None else str(result["card_file"]["path"]),
        "card_sha256": None if result["card_file"] is None else str(result["card_file"]["sha256"]),
    }
    if result["card_file"] is not None:
        card_scan = _scan_public_bytes(
            Path(str(result["card_file"]["path"])).read_bytes(), needles, key
        )
        if card_scan["hits"] or card_scan["key_material_hits"] or card_scan["secret_shape_hits"]:
            Path(str(result["card_file"]["path"])).unlink(missing_ok=True)
            _refuse("public_output_leak", "out_card")

    written = controlled._write_new_file(checked_out / "result-aggregate.json", payload)
    payload["outputs"] = {
        "aggregate": str(written["path"]),
        "aggregate_sha256": str(written["sha256"]),
        "card": payload["artifacts"]["card"],
        "card_sha256": payload["artifacts"]["card_sha256"],
    }
    # 落盘后按最终字节再扫一次（含 outputs 字段），任何命中都固定拒绝。
    final_raw = _canonical_bytes(payload)
    final_scan = _scan_public_bytes(final_raw, needles, key)
    if final_scan["hits"] or final_scan["key_material_hits"] or final_scan["secret_shape_hits"]:
        _refuse("public_output_leak", "readback")
    _assert_public_safe(payload)
    return payload


def _canonical_bytes(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(
        payload, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False
    ).encode("utf-8")


def _read_mapping(path: Path, code: str) -> dict[str, Any]:
    try:
        raw = Path(path).read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        _refuse(code)
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError):
        _refuse(code)
    if not isinstance(payload, dict):
        _refuse(code)
    return payload


def _analysis_source_digests() -> dict[str, str]:
    rows: dict[str, str] = {}
    for rel in (
        "backend/src/mktkb/evaluation/p2_hard_evidence.py",
        "backend/src/mktkb/evaluation/p2_evidence_io.py",
        "backend/src/mktkb/evaluation/p2_evidence_capture.py",
        "tools/p2_h2_controlled_execute.py",
        "tools/p2_h2_historical_audit.py",
    ):
        target = PROJECT_ROOT / rel
        rows[rel] = _sha256_file(target) if target.is_file() else ""
    return rows


def _evidence_file_expectation(
    resolved_plan: Mapping[str, Any], *, evidence_root: Path, evidence_parent: Path
) -> dict[str, Any]:
    """证据根（= 密文根/run 目录的上一级）里必须**恰好**是本 run 登记的 turn + manifest。"""
    names = {
        str(turn_row["evidence_file"])
        for row in resolved_plan["cases"]
        for turn_row in row["turns"]
        if str(turn_row["status"]) == "executed"
    }
    manifest_files = sorted(p.name for p in evidence_root.glob("manifest-*.fernet"))
    prefix = evidence_root.name + "/"
    expected = {prefix + name for name in names} | {prefix + name for name in manifest_files}
    return {"expected": expected, "turns": sorted(names), "manifests": manifest_files, "prefix": prefix}


def _sealed_case_plan_row(
    seal: Mapping[str, Any], case_plan_sha: str
) -> Mapping[str, Any] | None:
    out_block = seal.get("out_dir") if isinstance(seal.get("out_dir"), Mapping) else {}
    rows = out_block.get("files") if isinstance(out_block.get("files"), list) else []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        if str(row.get("sha256")) == case_plan_sha:
            return row
    return None


def _public_needles(dataset: Any, labels: Any, cases: Sequence[Any]) -> tuple[str, ...]:
    """公开产物自扫描针：题面/答案 + case id（长度>=5）。只在内存里用，绝不写进产物。"""
    controlled = _controlled()
    values = {
        str(item).strip()
        for item in controlled._plaintext_needles(dataset, labels)
        if len(str(item).strip()) >= 4
    }
    for case in cases:
        value = str(getattr(case, "case_id", "") or "").strip()
        if len(value) >= 5:
            values.add(value)
    return tuple(sorted(values))


#: 外部锚定：旧公开报告记录的身份字段 → 本次审计 payload 的取值键。
EXTERNAL_ANCHOR_PATHS: dict[str, tuple[str, ...]] = {
    "code_version": ("identity", "code_version"),
    "plan_sha256": ("identity", "plan_sha256"),
    "binding_sha256": ("identity", "binding_sha256"),
    "config_sha256": ("identity", "config_sha256"),
    "case_plan_sha256": ("identity", "case_plan_sha256"),
    "evidence_tree_sha256": ("seal", "evidence_tree_sha256"),
    "out_tree_sha256": ("seal", "out_tree_sha256"),
    "plan_id": ("identity", "plan_id"),
    "run_id": ("identity", "run_id"),
}


def _expected_identity_check(
    path: Path | str | None, *, payload_values: Mapping[str, str]
) -> dict[str, Any]:
    """可选外部锚定：把本次审计 identity 与**外部已记录**的公开快照逐项比对。

    只读、合成/公开报告即可；不引入签名，但能挡住“整体重写历史根后内部自洽”的伪造。
    """
    payload: dict[str, Any] = {
        "applied": False,
        "source_schema_version": None,
        "checked_fields": 0,
        "mismatches": [],
        "ok": True,
        "detail": {"applied": False, "mismatched_fields": []},
    }
    if path is None:
        return payload
    document = _read_mapping(Path(path), "expected_identity_unreadable")
    schema = str(document.get("schema_version") or "")
    if not schema:
        _refuse("expected_identity_invalid", "schema_version")
    payload["applied"] = True
    payload["source_schema_version"] = schema
    mismatches: list[str] = []
    checked = 0
    for name, pointer in EXTERNAL_ANCHOR_PATHS.items():
        node: Any = document
        for step in pointer:
            node = node.get(step) if isinstance(node, Mapping) else None
        if node is None:
            continue
        checked += 1
        if str(node) != str(payload_values.get(name) or ""):
            mismatches.append(name)
    payload["checked_fields"] = checked
    payload["mismatches"] = mismatches
    payload["ok"] = not mismatches and checked == len(EXTERNAL_ANCHOR_PATHS)
    payload["detail"] = {
        "applied": True,
        "checked_fields": checked,
        "mismatched_fields": mismatches,
        "source_schema_version": schema,
    }
    # C6c：外部锚定必须是**完整** 9 字段；partial 锚等于没锚，不能算 applied。
    if checked != len(EXTERNAL_ANCHOR_PATHS):
        _refuse("expected_identity_incomplete", "%d/%d" % (checked, len(EXTERNAL_ANCHOR_PATHS)))
    return payload


def _quality_payload(
    resolved_plan: Mapping[str, Any], *, other_cases: int, dataset_cases: int
) -> dict[str, Any]:
    counts = {"pass": 0, "fail": 0, "error": 0, "not_executed": 0}
    all_executed = 0
    with_unexecuted = 0
    for row in resolved_plan["cases"]:
        status = str(row["quality_status"])
        if status not in counts:
            status = "error"
        counts[status] += 1
        if all(str(turn["status"]) == "executed" for turn in row["turns"]):
            all_executed += 1
        else:
            with_unexecuted += 1
    subset_total = sum(counts.values())
    upper_bound = counts["pass"] + counts["not_executed"] + int(other_cases)
    min_pass = int(_min_pass_required())
    return {
        "source": QUALITY_SOURCE_RECORDED,
        "rescored_from_original_inputs": False,
        "denominator": subset_total,
        "dataset_denominator": int(dataset_cases),
        "pass": counts["pass"],
        "fail": counts["fail"],
        "error": counts["error"],
        "not_executed": counts["not_executed"],
        "cases_all_turns_executed": all_executed,
        "cases_with_unexecuted_turns": with_unexecuted,
        "never_started_other_scenarios": int(other_cases),
        "undecided_total": counts["not_executed"] + int(other_cases),
        "upper_bound_pass_total": upper_bound,
        "min_pass_required": min_pass,
        "min_pass_source": "classifier_default",
        "threshold_scope": "dataset_%d_cases" % int(dataset_cases),
        "threshold_met": bool(counts["pass"] >= min_pass),
        "ceiling_meets_threshold": upper_bound >= min_pass,
        "denominator_note_code": "subset_%d_of_%d_plus_%d_never_started"
        % (subset_total, int(dataset_cases), int(other_cases)),
        "quality_axes_conflation": False,
    }


def _min_pass_required() -> int:
    """阈值来自已接收聚合器的默认口径；读不到就按冻结默认 24（不静默变成别的数）。"""
    try:
        import inspect

        signature = inspect.signature(_hard().aggregate_hard_evidence)
        value = signature.parameters["min_pass"].default
        if isinstance(value, int) and value > 0:
            return int(value)
    except Exception:  # noqa: BLE001 - 读不到签名用冻结默认
        pass
    return 24


def _full_matrix_payload(
    *,
    card: Mapping[str, Any],
    dataset_cases: int,
    dataset_turns: int,
    scenario_cases: int,
    scenario_turns: int,
    plan_rows: Sequence[Mapping[str, Any]],
    other_cases: int,
    other_turns: int,
    runs: Mapping[str, Any],
) -> dict[str, Any]:
    hard = _hard()
    axes: dict[str, Any] = {}
    for name in hard.AXES:
        table = dict(card["axes"][name])
        axes[name] = {
            "planned": int(dataset_cases),
            "passed": int(table["passed"]),
            "not_applicable": int(table["not_applicable"]),
            "unknown": int(table["unknown"]) + int(other_cases),
            "violations": int(table["violations"]),
            "checked": int(table["checked"]),
            "unknown_not_started": int(other_cases),
        }
    all_executed = sum(
        1
        for row in plan_rows
        if all(str(turn["status"]) == "executed" for turn in row["turns"])
    )
    with_unexecuted = len(plan_rows) - all_executed
    not_started_total = int(with_unexecuted) + int(other_cases)
    verified = bool(runs.get("verified")) and bool(runs.get("out_root_provided"))
    return {
        "basis": "run0_observed_plus_not_started_unknown"
        if verified
        else "observed_subset_plus_unverified_other_runs_unknown",
        "authoritative": False,
        "cases": {
            "planned": int(dataset_cases),
            "audited_in_run": int(scenario_cases),
            "all_turns_executed_in_audited_run": int(all_executed),
            "partially_executed_in_audited_run": int(with_unexecuted),
            "never_started_other_scenarios": int(other_cases),
            "not_started": not_started_total,
        },
        "turns": {
            "planned": int(dataset_turns),
            "executed": int(
                sum(
                    1
                    for row in plan_rows
                    for turn in row["turns"]
                    if str(turn["status"]) == "executed"
                )
            ),
            "not_started": int(dataset_turns) - int(
                sum(
                    1
                    for row in plan_rows
                    for turn in row["turns"]
                    if str(turn["status"]) == "executed"
                )
            ),
            "planned_in_audited_run": int(scenario_turns),
        },
        "axes": axes,
        "not_started_reason": "scenario_not_started",
        "other_runs_not_started_verified": bool(runs.get("verified")),
        "other_turns": int(other_turns),
    }


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:  # type: ignore[override]
        # C8c：只回显**本解析器注册过的选项名**；任何其它 token（含 dash 前缀的值）都不回显。
        known = set()
        for action in self._actions:
            known.update(str(item) for item in (action.option_strings or ()))
        tokens = [
            token
            for token in str(message).split()
            if token in known and len(token) <= 64
        ]
        detail = "usage_invalid:" + ",".join(sorted(set(tokens))) if tokens else "usage_invalid"
        raise EntryError("usage_invalid", detail[:200], exit_code=EXIT_USAGE)


def _build_parser() -> argparse.ArgumentParser:
    parser = _Parser(
        prog="p2_h2_historical_audit",
        description="T207 历史审计：只读重算旧 run 四轴（历史重评；不授权 live）",
    )
    sub = parser.add_subparsers(dest="command", required=True, parser_class=_Parser)
    audit = sub.add_parser("audit-historical", help="只读历史重评单命令")
    audit.add_argument("--historical-root", required=True, help="旧封存根（仓外、只读）")
    audit.add_argument("--run-binding", required=True, help="旧 run binding（历史根内）")
    audit.add_argument("--run-index", required=True, type=int, help="0..3，固定场景顺序")
    audit.add_argument("--evidence-dir", required=True, help="本 run 密文目录（历史根内）")
    audit.add_argument("--evidence-key-file", required=True, help="密文 key 文件（历史根内，不回显）")
    audit.add_argument("--case-plan", required=True, help="旧 controlled/case-plan.json")
    audit.add_argument("--run-receipt", required=True, help="旧 run-receipt.json")
    audit.add_argument("--seal-manifest", required=True, help="旧 seal-manifest.json")
    audit.add_argument("--run-out-root", required=True, help="旧 out 根（必填；复算 out 树摘要）")
    audit.add_argument("--ledger-path", required=True, help="只读共享账本（固定路径）")
    audit.add_argument("--holdout-root", required=True, help="holdout 封存根（显式，仓外）")
    audit.add_argument("--holdout-key-file", required=True, help="holdout key（显式，仓外）")
    audit.add_argument(
        "--project-total-limit-cny", required=True, type=float, help="项目总上限，必须=40"
    )
    audit.add_argument("--out-dir", required=True, help="新输出目录（仓外、历史根外、不存在）")
    audit.add_argument("--out-card", default=None, help="可选：完整 scorecard 新文件（仓外）")
    audit.add_argument("--original-source-freeze", default=None, help="原始源码冻结清单 JSON")
    audit.add_argument("--original-source-root", default=None, help="原始源码字节根（可选）")
    audit.add_argument(
        "--expected-identity",
        default=None,
        help="可选外部锚定：旧公开聚合报告（逐项比对 identity/seal 摘要）",
    )
    return parser


def _emit(payload: Mapping[str, Any]) -> None:
    sys.stdout.write(json.dumps(dict(payload), ensure_ascii=False, sort_keys=True) + "\n")
    sys.stdout.flush()


def _dispatch(args: argparse.Namespace) -> int:
    if args.command != "audit-historical":
        _usage("command_invalid")
    payload = audit_historical(
        historical_root=args.historical_root,
        binding_path=args.run_binding,
        run_index=int(args.run_index),
        evidence_dir=args.evidence_dir,
        evidence_key_file=args.evidence_key_file,
        case_plan_path=args.case_plan,
        receipt_path=args.run_receipt,
        seal_manifest_path=args.seal_manifest,
        run_out_root=args.run_out_root,
        ledger_path=args.ledger_path,
        holdout_root=args.holdout_root,
        holdout_key_file=args.holdout_key_file,
        project_total_limit_cny=float(args.project_total_limit_cny),
        out_dir=args.out_dir,
        out_card=args.out_card,
        original_source_freeze=args.original_source_freeze,
        original_source_root=args.original_source_root,
        expected_identity_path=args.expected_identity,
    )
    _emit(payload)
    return EXIT_OK


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = _build_parser().parse_args(list(argv) if argv is not None else None)
        return _dispatch(args)
    except EntryError as exc:
        _emit(
            {
                "ok": False,
                "schema_version": AUDIT_SCHEMA_VERSION,
                "tool": TOOL_SCHEMA_VERSION,
                "error_code": exc.code,
                "detail": exc.detail,
                "analysis_kind": ANALYSIS_KIND,
                "authorizes_live": False,
                "release_ready": False,
                "secrets_printed": False,
                "real_sends": 0,
                "guard": {**GUARD_COUNTERS.snapshot()},
            }
        )
        return exc.exit_code
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001 - 未预期异常只报固定码，绝不回显异常链
        _emit(
            {
                "ok": False,
                "schema_version": AUDIT_SCHEMA_VERSION,
                "tool": TOOL_SCHEMA_VERSION,
                "error_code": "internal_error",
                "detail": "",
                "analysis_kind": ANALYSIS_KIND,
                "authorizes_live": False,
                "release_ready": False,
                "secrets_printed": False,
                "real_sends": 0,
                "guard": {**GUARD_COUNTERS.snapshot()},
            }
        )
        return EXIT_INTERNAL


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

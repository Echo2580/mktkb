"""T207 05 H2-LIVE-ENTRY：受控真实证据绑定、凭据与执行入口（唯一真实入口）。

边界（与派单/P2-T207-H2-LIVE-ENTRY/recon.md 一致）：
- 本工具是**唯一**受控 live 入口：每场景真正走 run_live_p2/open_live_gate/共享账本，
  强制采集 live_h2 证据并在 purge 前封存；不做任何自动重试，首个错误即停。
- 凭据只来自主人指定的项目 .env（AUTHORIZED_ENV_PATH），进程内白名单读取后仅在本进程
  生效并在退出时还原；不打印/不复制/不改源文件，不启用 dotenv。
- 开发/测试只用合成 env、合成 Fernet key、合成 transport；本包零真实发送/零付费/零预留。
- 不含任何真实 H2 题面/答案/逐题 ID 的输出：stdout 只有固定 code/计数/hash/路径；
  case 级私有材料只写仓外私有目录（plan 文件、密文、只读封存）。

子命令：plan-private / preflight / run / recompute。统一退出码：
0 通过；2 受控拒绝（固定 code，可能零发送或已按首错停）；3 用法/输入不合法；1 未预期。
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.util
import json
import math
import os
import re
import shutil
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, NoReturn, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_SRC = PROJECT_ROOT / "backend" / "src"
if str(BACKEND_SRC) not in sys.path:
    sys.path.insert(0, str(BACKEND_SRC))

from mktkb.evaluation import p2_authorization as p2a  # noqa: E402
from mktkb.evaluation import p2_hard_evidence as hard  # noqa: E402
from mktkb.evaluation import p2_holdout_source_map as holdout_source_map  # noqa: E402
from mktkb.evaluation import p2_live, p2_runner, p2_scoring  # noqa: E402
from mktkb.evaluation import p2_safe_output as safe_output  # noqa: E402
from mktkb.evaluation.p2_contracts import (  # noqa: E402
    CHAT_HOST,
    CHAT_MODEL,
    CHAT_PROVIDER,
    CHAT_REGION,
    COST_CENTERS,
    EMBEDDING_MODEL,
    EMBEDDING_PROVIDER,
    RERANK_MODEL,
    RERANK_PROVIDER,
    P2RunPlan,
    payload_sha256,
)
from mktkb.evaluation.p2_dataset import load_p2_dataset  # noqa: E402
from mktkb.evaluation.p2_evidence_capture import (  # noqa: E402
    BINDING_KEYS,
    LIVE_FIXTURE_KIND,
    LIVE_PENDING_INDEX_REVISION,
    EvidenceCaptureConfig,
    EvidenceCaptureConfigError,
    attempt_scope_sha256,
)
from mktkb.evaluation.p2_evidence_io import (  # noqa: E402
    EvidenceIOError,
    EvidenceWriter,
    read_encrypted_evidence,
)
from mktkb.evaluation.p2_holdout_plan import (  # noqa: E402
    H2_MAX_REQUESTS,
    H2_PROJECT_TOTAL_LIMIT_CNY,
    H2_STAGE_LIMIT_CNY,
)
from mktkb.evaluation.p2_holdout_scenarios import (  # noqa: E402
    ScenarioError,
    assert_private_path,
    load_scenario_contract,
)
from mktkb.evaluation.product_adapter import (  # noqa: E402
    case_questions,
    product_pipeline_version,
)
from mktkb.live_authorization import ledger_binding_ok  # noqa: E402

# --------------------------------------------------------------------------- #
# 固定身份与代码
# --------------------------------------------------------------------------- #

TOOL_SCHEMA_VERSION = "p2-h2-controlled-entry/v0.1"
RUN_BINDING_FILE_SCHEMA_VERSION = "p2-h2-controlled-runbinding/v0.1"
PUBLIC_PLAN_SCHEMA_VERSION = "p2-h2-controlled-plan-public/v0.1"
PREFLIGHT_SCHEMA_VERSION = "p2-h2-controlled-preflight/v0.1"
RUN_RECEIPT_SCHEMA_VERSION = "p2-h2-controlled-run-receipt/v0.1"
SEAL_MANIFEST_SCHEMA_VERSION = "p2-h2-controlled-seal/v0.1"
LIVE_CASEPLAN_SCHEMA_VERSION = "p2-hard-evidence-caseplan-live/v0.1"
SCORER_IDENTITY_SCHEMA_VERSION = "p2-h2-scorer-identity/v0.1"
"""派生评分器身份回执 schema：只含 source map 摘要/计数/身份摘要，不含文档名或题面。"""

EXIT_OK = 0
EXIT_INTERNAL = 1
EXIT_REFUSED = 2
EXIT_USAGE = 3

#: 主人指定的唯一凭据源；测试用 monkeypatch 指向合成 .env。
AUTHORIZED_ENV_PATH = PROJECT_ROOT / ".env"
LIVE_EXECUTE_TOOL = PROJECT_ROOT / "tools" / "p2_live_execute.py"

#: 真实 .env 里由产品自己持有、05 不读取也不注入的键（只按形状忽略，值从不进入内存映射）。
PRODUCT_ENV_NAMES: tuple[str, ...] = (
    "MKTKB_CSRF_SECRET",
    "MKTKB_ADMIN_PASSWORD",
    "MKTKB_EMPLOYEE_PASSWORD",
    "MKTKB_TRUSTED_ORIGINS",
    "MKTKB_COOKIE_SECURE",
)
#: 运行环境边界：holdout 根/钥与项目总上限只能由显式 CLI 参数提供；
#: 即便同名键出现在 .env 里也会被剥离，绝不由 .env 充当来源。
RUNTIME_ENV_NAMES: tuple[str, ...] = (
    "MKTKB_P2_HOLDOUT_ROOT",
    "MKTKB_P2_HOLDOUT_KEY_FILE",
    "MKTKB_PROJECT_TOTAL_LIMIT_CNY",
)
CLEANUP_SCHEMA_VERSION = "p2-h2-controlled-cleanup/v0.1"

SCENARIO_ORDER: tuple[str, ...] = (
    "base_b0",
    "base_b0_plus_v01",
    "pre_v05_without_v07",
    "post_v05_without_v01",
)
EXPECTED_SCENARIO_COUNTS: Mapping[str, int] = {
    "base_b0": 26,
    "base_b0_plus_v01": 1,
    "pre_v05_without_v07": 2,
    "post_v05_without_v01": 1,
}
EXPECTED_INGEST_BATCHES: Mapping[str, int] = {
    "base_b0": 8,
    "base_b0_plus_v01": 9,
    "pre_v05_without_v07": 11,
    "post_v05_without_v01": 13,
}
EXPECTED_CASE_COUNT = 30
EXPECTED_TURN_COUNT = 36
PROJECT_TOTAL_LIMIT_CNY = float(H2_PROJECT_TOTAL_LIMIT_CNY)
STAGE_LIMIT_CNY = float(H2_STAGE_LIMIT_CNY)
TURN_TIMEOUT_SECONDS = 60.0

PUBLIC_CUSTODY_V2 = PROJECT_ROOT / "docs/reports/OBS-EVAL/P2/T207-CUSTODY-V2"
PUBLIC_CUSTODY_V3 = PROJECT_ROOT / "docs/reports/OBS-EVAL/P2/T207-CUSTODY-V3"
DEFAULT_MANAGER_V2 = PUBLIC_CUSTODY_V2 / "manager-acceptance.json"
DEFAULT_REVIEW_AGGREGATE_V2 = PUBLIC_CUSTODY_V2 / "review-aggregate.json"
DEFAULT_ADDENDUM_ACCEPTANCE = PUBLIC_CUSTODY_V3 / "manager-acceptance.json"
DEFAULT_SCENARIO_CONTRACT = PROJECT_ROOT / "docs/evaluation/p2-h2-scenarios-v0_2.json"
DEFAULT_INGEST_PLAN = PROJECT_ROOT / "docs/reports/OBS-EVAL/P2/T207/PM/T207-ingest-plan-H2.json"
DEFAULT_SOURCE_MAP = PROJECT_ROOT / "docs/evaluation/p2-holdout-v2.source-map.json"
DEFAULT_ANNOTATION_SCHEMA = PROJECT_ROOT / "docs/evaluation/p2-h2-custody-annotations-v0_2.md"
DEFAULT_HOLDOUT_MANIFEST = PROJECT_ROOT / "docs/evaluation/p2-holdout-v2.manifest.json"

INPUT_NAMES: tuple[str, ...] = (
    "holdout_manifest",
    "annotation_ciphertext",
    "review_ciphertext",
    "scenario_key_file",
    "addendum_ciphertext",
    "scenario_contract",
    "ingest_plan",
    "source_map",
    "annotation_schema",
    "manager_acceptance_v2",
    "review_aggregate_v2",
    "addendum_acceptance_v3",
)
PRIVATE_INPUT_NAMES = (
    "annotation_ciphertext",
    "review_ciphertext",
    "scenario_key_file",
    "addendum_ciphertext",
)
REQUIRED_RUN_KEYS = (
    "run_index",
    "scenario_id",
    "run_id",
    "plan_id",
    "plan_sha256",
    "plan_file",
    "plan_file_sha256",
    "case_count",
    "turn_count",
    "total_requests",
    "worst_case_cny",
    "reserve_peak_cny",
    "ingest_batches",
    "ingest_sources",
    "scenario_binding",
    "evidence_bindings",
)
BINDING_DOC_KEYS = (
    "schema_version",
    "created_utc",
    "fixture_kind",
    "execution_mode",
    "business_date",
    "code_version",
    "config_sha256",
    "config",
    "dataset",
    "inputs",
    "runs",
    "binding_sha256",
)
DATE_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
_ENV_LINE_RE = re.compile(r"^\s*(?P<key>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?P<value>.*)$")
HASH_RE = re.compile(r"^[0-9a-f]{64}$")
RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}$")
SCENARIO_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$")


class EntryError(RuntimeError):
    """受控拒绝：code 固定可机读，detail 只含固定码/变量名/键名（绝不含值）。"""

    def __init__(self, code: str, detail: str = "", exit_code: int = EXIT_REFUSED) -> None:
        self.code = str(code)
        self.detail = str(detail)
        self.exit_code = int(exit_code)
        super().__init__(f"{self.code}: {self.detail}" if self.detail else self.code)


def _refuse(code: str, detail: str = "") -> NoReturn:
    raise EntryError(code, detail)


def _usage(code: str, detail: str = "") -> NoReturn:
    raise EntryError(code, detail, exit_code=EXIT_USAGE)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _public_payload(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    """公开层出口（FU-4）：受限路径/密钥名/密文名换确定性记号，其余字段逐值保留。"""
    return safe_output.redact_payload(dict(payload))


def _public_detail(detail: Any) -> str:
    """自由文本 detail 只保留固定码/计数；内嵌路径与密钥名一律换记号。"""
    return safe_output.redact_text("" if detail is None else str(detail))


def _emit(payload: Mapping[str, Any]) -> None:
    sys.stdout.write(
        json.dumps(dict(_public_payload(payload)), ensure_ascii=False, sort_keys=True) + "\n"
    )
    sys.stdout.flush()


def _int(value: Any, code: str, *, minimum: int = 0, maximum: int = 10_000_000) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        _refuse(code)
    return int(value)


def _str(value: Any, code: str, *, maximum: int = 4096) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        _refuse(code)
    return value.strip()


def _hash(value: Any, code: str) -> str:
    if not isinstance(value, str) or HASH_RE.fullmatch(value) is None:
        _refuse(code)
    return value


def _date(value: Any, code: str) -> str:
    if not isinstance(value, str) or DATE_RE.fullmatch(value) is None:
        _refuse(code)
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        _refuse(code)
    return value


# --------------------------------------------------------------------------- #
# 路径 / 摘要 / 文件边界
# --------------------------------------------------------------------------- #


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _forbidden_roots() -> tuple[Path, ...]:
    return (PROJECT_ROOT.resolve(), Path("D:/mktkb-p2-holdout").resolve(strict=False))


def require_outside_repo(path: Path | str, what: str) -> Path:
    """私有产物/证据必须仓外；拒绝仓库、旧封存根与根目录。"""
    try:
        resolved = Path(path).expanduser().resolve(strict=False)
    except OSError:
        _refuse("path_invalid", what)
    for blocked in _forbidden_roots():
        if resolved == blocked or _is_within(resolved, blocked):
            _refuse("path_inside_forbidden_root", what)
    if resolved.as_posix() == "/":
        _refuse("path_invalid", what + ":root")
    return resolved


def require_new_dir(path: Path | str, what: str) -> Path:
    resolved = require_outside_repo(path, what)
    if resolved.exists():
        _refuse("output_already_exists", what)
    return resolved


def require_new_or_empty_dir(path: Path | str, what: str) -> Path:
    resolved = require_outside_repo(path, what)
    if resolved.exists():
        if not resolved.is_dir():
            _refuse("path_not_directory", what)
        if any(resolved.iterdir()):
            _refuse("output_not_empty", what)
    return resolved


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_sha256(payload: Any) -> str:
    raw = json.dumps(
        dict(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def tree_digest(root: Path) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    base = Path(root)
    if base.exists():
        for path in sorted(p for p in base.rglob("*") if p.is_file()):
            files.append(
                {
                    "path": path.relative_to(base).as_posix(),
                    "sha256": sha256_file(path),
                    "bytes": path.stat().st_size,
                }
            )
    joined = "\n".join(f"{item['path']}:{item['sha256']}" for item in files)
    return {
        "tree_sha256": hashlib.sha256(joined.encode("utf-8")).hexdigest(),
        "file_count": len(files),
        "bytes": sum(int(item["bytes"]) for item in files),
        "files": files,
    }


def _read_json(path: Path | str, code: str) -> Any:
    try:
        raw = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        _refuse(code)
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        _refuse(code)


def _read_json_mapping(path: Path | str, code: str) -> dict[str, Any]:
    payload = _read_json(path, code)
    if not isinstance(payload, dict):
        _refuse(code)
    return payload


def _write_new_file(path: Path, payload: Any, *, indent: int = 2) -> dict[str, Any]:
    target = Path(path)
    if target.exists():
        _refuse("output_already_exists", target.name)
    target.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=indent, sort_keys=True) + "\n"
    target.write_text(text, encoding="utf-8")
    return {"path": str(target), "sha256": sha256_file(target), "bytes": target.stat().st_size}


# --------------------------------------------------------------------------- #
# 代码/配置摘要
# --------------------------------------------------------------------------- #

CODE_SCOPES: tuple[str, ...] = (
    "backend/src/mktkb",
    "tools/p2_h2_controlled_execute.py",
)


def code_digest() -> str:
    """运行期源码整体摘要（未提交工作树字节），供四 run 之间冻结同一代码身份。"""
    files: list[Path] = []
    for scope in CODE_SCOPES:
        target = PROJECT_ROOT / scope
        if target.is_dir():
            files.extend(p for p in target.rglob("*.py") if "__pycache__" not in p.parts)
        elif target.is_file():
            files.append(target)
    lines = []
    for path in sorted(set(files)):
        rel = path.relative_to(PROJECT_ROOT).as_posix()
        lines.append(rel + ":" + sha256_file(path))
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def _provider_config() -> dict[str, Any]:
    return {
        "chat": {
            "provider": CHAT_PROVIDER,
            "model": CHAT_MODEL,
            "host": CHAT_HOST,
            "region": CHAT_REGION,
        },
        "embedding": {
            "provider": EMBEDDING_PROVIDER,
            "model": EMBEDDING_MODEL,
            "host": "dashscope.aliyuncs.com",
        },
        "rerank": {
            "provider": RERANK_PROVIDER,
            "model": RERANK_MODEL,
            "host": "dashscope.aliyuncs.com",
        },
        "ocr_region": "ap-guangzhou",
    }


def _build_config(
    *,
    business_date: str,
    inputs: Mapping[str, Mapping[str, Any]],
    code_version: str,
    thresholds_approved: bool,
) -> dict[str, Any]:
    """冻结的 run 配置：只有身份/上限/摘要，没有凭据、没有题面。"""
    return {
        "schema_version": "p2-h2-controlled-run-config/v0.1",
        "business_date": business_date,
        "fixture_kind": LIVE_FIXTURE_KIND,
        "execution_mode": "live",
        "providers": _provider_config(),
        "project_total_limit_cny": PROJECT_TOTAL_LIMIT_CNY,
        "stage_limit_cny": STAGE_LIMIT_CNY,
        "max_requests": int(H2_MAX_REQUESTS),
        "cost_centers_cny": {center: float(value) for center, value in _h2_centers().items()},
        "turn_timeout_seconds": TURN_TIMEOUT_SECONDS,
        "purge_traces_on_close": True,
        "force_evidence_capture": True,
        "thresholds_approved": bool(thresholds_approved),
        "scenario_order": list(SCENARIO_ORDER),
        "scenario_ingest_batches": dict(EXPECTED_INGEST_BATCHES),
        "code_version": code_version,
        "inputs": {name: str(inputs[name]["sha256"]) for name in INPUT_NAMES if name in inputs},
    }


def _h2_centers() -> dict[str, float]:
    from mktkb.evaluation.p2_holdout_plan import H2_COST_CENTERS_CNY

    return {center: float(H2_COST_CENTERS_CNY[center]) for center in COST_CENTERS}


# --------------------------------------------------------------------------- #
# 授权 .env（白名单、只在本进程生效、退出还原）
# --------------------------------------------------------------------------- #


def _live_execute_module() -> Any:
    if not LIVE_EXECUTE_TOOL.is_file():
        _refuse("env_wrapper_missing")
    spec = importlib.util.spec_from_file_location("_p2_live_execute", LIVE_EXECUTE_TOOL)
    if spec is None or spec.loader is None:
        _refuse("env_wrapper_missing")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:  # noqa: BLE001 - 包装器不可导入即拒绝（不吞异常细节）
        sys.modules.pop(spec.name, None)
        _refuse("env_wrapper_unloadable")
    return module


@dataclass(frozen=True)
class RuntimeOptions:
    """05 运行环境边界：holdout 根/钥与项目总上限**显式**给出（不从 .env 读）。"""

    holdout_root: Path
    holdout_key_file: Path
    project_total_limit_cny: float


def check_runtime_options(options: RuntimeOptions | None) -> RuntimeOptions:
    """进程内校验显式运行参数：路径存在/位置、key 文件、总上限=40。"""
    if options is None:
        _refuse("runtime_options_missing")
    repo_root = PROJECT_ROOT.resolve()
    try:
        root = Path(options.holdout_root).expanduser().resolve(strict=False)
    except (TypeError, ValueError, OSError):
        _refuse("holdout_root_invalid")
    if root == repo_root or _is_within(root, repo_root):
        _refuse("holdout_root_inside_repo")
    if not root.exists():
        _refuse("holdout_root_missing")
    if not root.is_dir():
        _refuse("holdout_root_invalid")
    try:
        key_path = Path(options.holdout_key_file).expanduser().resolve(strict=False)
    except (TypeError, ValueError, OSError):
        _refuse("holdout_key_invalid")
    if key_path == repo_root or _is_within(key_path, repo_root):
        _refuse("holdout_key_inside_repo")
    if not key_path.is_file():
        _refuse("holdout_key_file_missing")
    try:
        raw = key_path.read_bytes()
    except OSError:
        _refuse("holdout_key_unreadable")
    if len(raw) != 44:
        _refuse("holdout_key_invalid")
    try:
        from cryptography.fernet import Fernet

        Fernet(raw)
    except Exception:  # noqa: BLE001 - 结构非法统一固定码
        _refuse("holdout_key_invalid")
    total = options.project_total_limit_cny
    if total is None:
        _refuse("project_total_limit_missing")
    try:
        total_value = float(total)
    except (TypeError, ValueError):
        _refuse("project_total_limit_mismatch")
    if not math.isfinite(total_value) or abs(total_value - PROJECT_TOTAL_LIMIT_CNY) > 1e-9:
        _refuse("project_total_limit_mismatch")
    return RuntimeOptions(holdout_root=root, holdout_key_file=key_path, project_total_limit_cny=PROJECT_TOTAL_LIMIT_CNY)


def runtime_env_values(options: RuntimeOptions) -> dict[str, str]:
    """把**显式**运行参数转成本进程环境值（只在 applied_env 窗口内生效）。"""
    checked = check_runtime_options(options)
    return {
        "MKTKB_P2_HOLDOUT_ROOT": str(checked.holdout_root),
        "MKTKB_P2_HOLDOUT_KEY_FILE": str(checked.holdout_key_file),
        "MKTKB_PROJECT_TOTAL_LIMIT_CNY": str(float(checked.project_total_limit_cny)),
    }


def merge_runtime_env(values: Mapping[str, str], options: RuntimeOptions) -> dict[str, str]:
    """凭据值 + 显式运行值；同名运行键一律以显式参数为准（.env 不得覆盖）。"""
    merged = {
        str(name): str(value)
        for name, value in dict(values).items()
        if str(name) not in RUNTIME_ENV_NAMES
    }
    merged.update(runtime_env_values(options))
    return merged


def read_authorized_env(env_file: Path | str) -> dict[str, str]:
    """只接受主人指定的 .env：白名单凭据；产品键忽略；运行键剥离；缺凭据拒绝。

    R1 边界（T207 05 H2-LIVE-ENTRY）：
    - 真实 .env 还含产品自己持有的键（CSRF/密码/可信来源/Cookie），按形状忽略、不读取；
    - holdout 根/钥与项目总上限只能走显式 CLI 参数（RUNTIME_ENV_NAMES 在这里被剥离）；
    - 仍只要求 p2_live 的 6 个凭据键；DASHSCOPE_BASE_URL/OCR_REGION 用产品默认。
    """
    module = _live_execute_module()
    try:
        resolved = Path(env_file).expanduser().resolve(strict=True)
    except OSError:
        _refuse("env_file_missing")
    if resolved != Path(AUTHORIZED_ENV_PATH).expanduser().resolve(strict=False):
        _refuse("env_file_not_authorized")
    if resolved.name != ".env":
        _refuse("env_file_not_authorized", "name")
    try:
        raw = resolved.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        _refuse("env_file_unreadable")
    filtered: list[str] = []
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            filtered.append(line)
            continue
        match = _ENV_LINE_RE.match(line)
        if match is None:
            filtered.append(line)  # 让包装器解析器报 env_line_invalid（只带行号）
            continue
        key = match.group("key")
        if key in PRODUCT_ENV_NAMES:
            continue  # 产品自有键：只忽略形状，值永不进入映射
        filtered.append(line)
    try:
        values = dict(
            module.parse_env_text("\n".join(filtered) + "\n", source="authorized")
        )
    except module.EnvFileError as exc:
        _refuse(str(exc.code), str(exc.detail))
    values = {name: value for name, value in values.items() if name not in RUNTIME_ENV_NAMES}
    missing = [name for name in module.REQUIRED_ENV_NAMES if name not in values]
    if missing:
        _refuse("env_required_missing", ",".join(missing))
    return values


@contextmanager
def applied_env(values: Mapping[str, str]):
    """把白名单变量只加到**本进程**环境；退出时逐值还原（父环境/全局配置不变）。"""
    module = _live_execute_module()
    names = tuple(module.ALLOWED_ENV_NAMES)
    saved = {name: os.environ.get(name) for name in names}
    saved_flag = os.environ.get("MKTKB_NO_DOTENV")
    try:
        for name in names:
            os.environ.pop(name, None)
        for name, value in values.items():
            if name in names:
                os.environ[name] = str(value)
        # B：计划/契约的 chat 模型是唯一权威；.env 的默认模型（真实环境为旧别名）
        # 不得覆盖计划。显式 config 冲突仍由 _verify_env_against_config/load_live_env
        # 以固定码拒绝，不在这里静默改写绑定。
        os.environ["MKTKB_MODEL_NAME"] = CHAT_MODEL
        os.environ["MKTKB_NO_DOTENV"] = "1"
        yield
    finally:
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        if saved_flag is None:
            os.environ.pop("MKTKB_NO_DOTENV", None)
        else:
            os.environ["MKTKB_NO_DOTENV"] = saved_flag


# --------------------------------------------------------------------------- #
# 私有输入装配（受控解密，明文只在内存）
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class PrivateBundle:
    dataset: Any
    contract: Any
    annotation: Mapping[str, Any]
    addendum: Mapping[str, Any]
    addendum_acceptance: Mapping[str, Any]
    inputs: Mapping[str, dict[str, Any]]
    business_date: str


@dataclass(frozen=True)
class InputPaths:
    holdout_manifest: Path
    annotation_ciphertext: Path
    review_ciphertext: Path
    scenario_key_file: Path
    addendum_ciphertext: Path
    scenario_contract: Path
    ingest_plan: Path
    source_map: Path
    annotation_schema: Path
    manager_acceptance_v2: Path
    review_aggregate_v2: Path
    addendum_acceptance_v3: Path

    def as_mapping(self) -> dict[str, Path]:
        return {
            "holdout_manifest": self.holdout_manifest,
            "annotation_ciphertext": self.annotation_ciphertext,
            "review_ciphertext": self.review_ciphertext,
            "scenario_key_file": self.scenario_key_file,
            "addendum_ciphertext": self.addendum_ciphertext,
            "scenario_contract": self.scenario_contract,
            "ingest_plan": self.ingest_plan,
            "source_map": self.source_map,
            "annotation_schema": self.annotation_schema,
            "manager_acceptance_v2": self.manager_acceptance_v2,
            "review_aggregate_v2": self.review_aggregate_v2,
            "addendum_acceptance_v3": self.addendum_acceptance_v3,
        }


def _input_record(name: str, path: Path | str, *, private: bool) -> dict[str, Any]:
    try:
        resolved = assert_private_path(path) if private else Path(path).expanduser().resolve()
    except ScenarioError:
        _refuse("input_path_rejected", name)
    except OSError:
        _refuse("input_path_invalid", name)
    if not resolved.is_file():
        _refuse("input_file_missing", name)
    size = resolved.stat().st_size
    if size <= 0 or size > 16 * 1024 * 1024:
        _refuse("input_size_invalid", name)
    return {"path": str(resolved), "sha256": sha256_file(resolved), "bytes": int(size)}


def _decrypt_json(raw: bytes, key: bytes, code: str) -> dict[str, Any]:
    from cryptography.fernet import Fernet

    try:
        plain = Fernet(bytes(key)).decrypt(raw)
    except Exception:  # noqa: BLE001 - 坏 key/截断密文统一固定码
        _refuse(code)
    try:
        payload = json.loads(plain.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        _refuse(code + "_invalid")
    if not isinstance(payload, dict):
        _refuse(code + "_invalid")
    return payload


def _thresholds_approved_from_config() -> bool:
    """与 p2_runner 同口径：只有 gate 配置 status=approved 才算阈值已批。"""
    try:
        gate_config = p2_scoring.load_p2_gate_config()
    except Exception:  # noqa: BLE001 - 读不到门配置就按未批处理（不猜通过）
        return False
    return bool(p2_runner._thresholds_approved(gate_config))


def _verify_addendum_acceptance(
    acceptance_path: Path | str,
    addendum_payload: Mapping[str, Any],
    addendum_cipher_sha: str,
    annotation_cipher_sha: str,
) -> dict[str, Any]:
    """V0.3 冻结：addendum 密文/明文摘要、gap 计数与质量放行位必须与公共接受记录一致。"""
    payload = _read_json_mapping(acceptance_path, "addendum_acceptance_invalid")
    required_text = {
        "schema_version": "p2-h2-custody-gapaddendum-manager-acceptance/v0.3",
        "independent_review_verdict": "PASS",
        "addendum_ciphertext_sha256": addendum_cipher_sha,
        "addendum_plaintext_canonical_sha256": payload_sha256(addendum_payload),
        "base_annotation_ciphertext_sha256": annotation_cipher_sha,
    }
    for key, expected in required_text.items():
        if payload.get(key) != expected:
            _refuse("addendum_acceptance_mismatch", key)
    required_true = ("addendum_frozen",)
    for key in required_true:
        if payload.get(key) is not True:
            _refuse("addendum_acceptance_mismatch", key)
    required_false = (
        "live_execution_authorized_by_this_record",
        "quality_released",
        "runtime_axis_evidence_produced",
    )
    for key in required_false:
        if payload.get(key) is not False:
            _refuse("addendum_acceptance_mismatch", key)
    for key, expected in (("gap_total", 4), ("gap_resolved", 4), ("gap_kept_unknown", 0), ("new_real_calls", 0)):
        value = payload.get(key)
        if isinstance(value, bool) or type(value) is not int or value != expected:
            _refuse("addendum_acceptance_mismatch", key)
    scope = payload.get("accepted_scope")
    if not isinstance(scope, list) or not {
        "addendum_structure",
        "semantic_consistency_of_4_gap_resolutions",
        "freeze_as_classifier_annotation_input",
    }.issubset({str(item) for item in scope}):
        _refuse("addendum_acceptance_mismatch", "accepted_scope")
    return payload


def load_private_bundle(
    env_values: Mapping[str, str],
    paths: InputPaths,
    *,
    runtime: RuntimeOptions | None = None,
) -> PrivateBundle:
    """受控进程内解封 dataset/annotation/addendum 并校验冻结 custody 绑定（不落明文）。

    R1：holdout 根/钥与项目总上限由 `runtime` 显式给出（不从 .env 读）；
    凭据仍只来自 `env_values`（read_authorized_env 的白名单结果）。
    """
    process_env = merge_runtime_env(env_values, check_runtime_options(runtime))
    records: dict[str, dict[str, Any]] = {}
    for name, path in paths.as_mapping().items():
        records[name] = _input_record(name, path, private=name in PRIVATE_INPUT_NAMES)
    key = Path(records["scenario_key_file"]["path"]).read_bytes()
    if not 16 <= len(key) <= 4096:
        _refuse("scenario_key_invalid")
    annotation_raw = Path(records["annotation_ciphertext"]["path"]).read_bytes()
    addendum_raw = Path(records["addendum_ciphertext"]["path"]).read_bytes()
    annotation = _decrypt_json(annotation_raw, key, "annotation_decrypt_failed")
    addendum = _decrypt_json(addendum_raw, key, "addendum_decrypt_failed")
    acceptance = _verify_addendum_acceptance(
        Path(records["addendum_acceptance_v3"]["path"]),
        addendum,
        records["addendum_ciphertext"]["sha256"],
        records["annotation_ciphertext"]["sha256"],
    )
    try:
        with applied_env(process_env):
            dataset = load_p2_dataset(
                Path(records["holdout_manifest"]["path"]), visibility="holdout"
            )
            contract = load_scenario_contract(
                dataset,
                annotation_path=Path(records["annotation_ciphertext"]["path"]),
                review_path=Path(records["review_ciphertext"]["path"]),
                key_file=Path(records["scenario_key_file"]["path"]),
                manager_path=Path(records["manager_acceptance_v2"]["path"]),
                review_aggregate_path=Path(records["review_aggregate_v2"]["path"]),
                scenario_path=Path(records["scenario_contract"]["path"]),
                ingest_path=Path(records["ingest_plan"]["path"]),
                source_map_path=Path(records["source_map"]["path"]),
                schema_path=Path(records["annotation_schema"]["path"]),
            )
    except ScenarioError as exc:
        _refuse("scenario_contract_invalid", str(exc)[:120])
    except EvidenceCaptureConfigError:
        raise
    except ValueError as exc:
        _refuse("dataset_invalid", type(exc).__name__)
    return PrivateBundle(
        dataset=dataset,
        contract=contract,
        annotation=annotation,
        addendum=addendum,
        addendum_acceptance=acceptance,
        inputs=records,
        business_date=str(dataset.manifest.business_date),
    )


def _validate_dataset_shape(dataset: Any, business_date: str) -> int:
    """30 题/36 回合/同序唯一覆盖 + 全部 CaseSpec.business_date 等于公开 manifest 日期。"""
    if str(getattr(dataset, "visibility", "")) != "holdout":
        _refuse("dataset_visibility_invalid")
    manifest = dataset.manifest
    if int(manifest.case_count) != EXPECTED_CASE_COUNT:
        _refuse("dataset_case_count_invalid")
    if str(manifest.business_date) != business_date:
        _refuse("business_date_manifest_mismatch")
    cases = tuple(dataset.cases)
    if len(cases) != EXPECTED_CASE_COUNT:
        _refuse("dataset_case_count_invalid")
    if len({str(case.case_id) for case in cases}) != EXPECTED_CASE_COUNT:
        _refuse("dataset_case_duplicate")
    total = 0
    for case in cases:
        questions = case_questions(case)
        if not questions:
            _refuse("dataset_case_turns_invalid")
        total += len(questions)
        if str(case.business_date or "") != business_date:
            _refuse("business_date_case_mismatch")
    if total != EXPECTED_TURN_COUNT:
        _refuse("dataset_turn_count_invalid")
    if int(manifest.turn_stats.get("total_turns", -1)) != EXPECTED_TURN_COUNT:
        _refuse("dataset_manifest_turn_stats_invalid")
    return total


def _annotation_cipher_sha256(bundle: PrivateBundle) -> str | None:
    """v0.2 标注密文文件字节 SHA256（v0.3 addendum 的真实绑定语义）。

    只取本模块解封时记录的 annotation_ciphertext 文件摘要，绝不用明文 canonical sha 代替；
    记录缺失时返回 None，由 03 的 prepare_annotation 固定拒绝（addendum 存在时必需）。
    """
    record = (
        bundle.inputs.get("annotation_ciphertext")
        if isinstance(bundle.inputs, Mapping)
        else None
    )
    value = record.get("sha256") if isinstance(record, Mapping) else None
    return value if isinstance(value, str) else None


def _prepare_annotation(
    bundle: PrivateBundle, schema_path: Path, scenario_path: Path
) -> Any:
    try:
        return hard.prepare_annotation(
            bundle.annotation,
            bundle.dataset.cases,
            addendum=bundle.addendum,
            # 真实 v0.3 语义：绑定 v0.2 标注密文文件 SHA256（records["annotation_ciphertext"]["sha256"]）。
            annotation_cipher_sha256=_annotation_cipher_sha256(bundle),
            schema_path=schema_path,
            scenario_path=scenario_path,
        )
    except hard.HardEvidenceError as exc:
        _refuse("annotation_invalid", str(exc)[:120])
    except ValueError as exc:
        _refuse("annotation_invalid", type(exc).__name__)


def _verify_annotation_contract_bindings(annotation: Mapping[str, Any], contract: Any) -> None:
    bindings = annotation.get("bindings")
    if not isinstance(bindings, Mapping):
        _refuse("annotation_invalid")
    reference = contract.binding(SCENARIO_ORDER[0])
    pairs = (
        ("manifest_sha256", "manifest_sha256"),
        ("cases_sha256", "full_cases_sha256"),
        ("source_map_sha256", "source_map_sha256"),
        ("ingest_plan_sha256", "ingest_plan_sha256"),
        ("scenario_contract_sha256", "scenario_contract_sha256"),
        ("schema_sha256", "schema_sha256"),
    )
    for annotation_key, contract_key in pairs:
        if str(bindings.get(annotation_key)) != str(reference.get(contract_key)):
            _refuse("annotation_contract_binding_mismatch", annotation_key)


def _verify_axis_counts(annotation: Any, acceptance: Mapping[str, Any]) -> None:
    expected = acceptance.get("merged_axis_counts")
    summary = annotation.public_summary()
    if not isinstance(expected, Mapping) or dict(summary["axis_counts"]) != {
        str(name): {str(state): int(count) for state, count in table.items()}
        for name, table in expected.items()
    }:
        _refuse("axis_counts_mismatch")


def _validate_created_utc(value: str) -> str:
    text = str(value or "").strip()
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        _refuse("created_utc_invalid")
    if moment.tzinfo is None:
        _refuse("created_utc_invalid")
    return text


@dataclass(frozen=True)
class PlanOptions:
    out_dir: Path
    created_utc: str
    plan_id_prefix: str = "P2-T207-H2-20261111"
    run_id_prefix: str = "p2-h2"
    plan_version: str = "v0.1"
    max_requests: int = int(H2_MAX_REQUESTS)
    business_date: str | None = None
    schema_path: Path = DEFAULT_ANNOTATION_SCHEMA
    scenario_path: Path = DEFAULT_SCENARIO_CONTRACT


def _scenario_names() -> tuple[str, ...]:
    return SCENARIO_ORDER


def _plan_identity(index: int, scenario: str, options: PlanOptions) -> tuple[str, str]:
    plan_id = str(options.plan_id_prefix) + "-r" + str(index + 1) + "-" + scenario
    run_id = str(options.run_id_prefix) + "-r" + str(index + 1) + "-" + scenario
    if len(plan_id) > 96 or SCENARIO_ID_RE.fullmatch(plan_id) is None:
        _refuse("plan_id_invalid")
    if len(run_id) > 96 or RUN_ID_RE.fullmatch(run_id) is None:
        _refuse("run_id_invalid")
    return plan_id, run_id


def _evidence_bindings(
    *,
    dataset: Any,
    scenario: str,
    run_id: str,
    plan: P2RunPlan,
    config_sha: str,
    code_version: str,
    scenario_binding: Mapping[str, str],
) -> dict[str, str]:
    manifest = dataset.manifest
    return {
        "run_id": run_id,
        "plan_id": plan.plan_id,
        "plan_sha256": plan.plan_sha256,
        "dataset_version": str(manifest.dataset_version),
        "manifest_sha256": str(manifest.manifest_sha256),
        "label_version": str(manifest.label_version),
        "suite": str(manifest.suite),
        "scenario_id": scenario,
        "scenario_contract_sha256": str(scenario_binding["scenario_contract_sha256"]),
        "assignment_sha256": str(scenario_binding["assignment_sha256"]),
        "custody_sha256": str(scenario_binding["custody_sha256"]),
        "config_sha256": config_sha,
        "pipeline_version": str(product_pipeline_version()),
        "index_revision": LIVE_PENDING_INDEX_REVISION,
        "code_version": code_version,
        "fixture_kind": LIVE_FIXTURE_KIND,
    }


def _index_embedding_allocation(
    plan: P2RunPlan, scenario: str, scenario_binding: Mapping[str, str]
) -> dict[str, Any]:
    """E：四 run 的 index_embedding 分配必须来自冻结 scenario contract，不从语料重推。"""
    items = [item for item in plan.items if item.operation == "index_embedding"]
    if len(items) != 1:
        _refuse("plan_ingest_item_invalid", scenario)
    item = items[0]
    batches = int(item.requests)
    if str(item.item_id) != "ingest-index-embedding":
        _refuse("plan_ingest_item_invalid", scenario)
    if batches != int(EXPECTED_INGEST_BATCHES[scenario]):
        _refuse("plan_ingest_batches_mismatch", scenario)
    source_sha = str(scenario_binding.get("scenario_ingest_sha256") or "")
    if HASH_RE.fullmatch(source_sha) is None:
        _refuse("scenario_binding_invalid", scenario)
    return {
        "item_id": str(item.item_id),
        "requests": batches,
        "batches": batches,
        "source": "frozen_scenario_contract",
        "source_sha256": source_sha,
    }


def _check_plan(
    plan: P2RunPlan,
    *,
    dataset: Any,
    scenario: str,
    scenario_binding: Mapping[str, str],
    options: PlanOptions,
    expected_turns: int,
) -> None:
    if dict(plan.scenario_binding or {}) != dict(scenario_binding):
        _refuse("plan_scenario_mismatch", scenario)
    if plan.stage != "P2-LIVE" or plan.mode != "end_to_end":
        _refuse("plan_identity_invalid", scenario)
    if abs(float(plan.project_total_limit_cny) - PROJECT_TOTAL_LIMIT_CNY) > 1e-9:
        _refuse("plan_project_limit_mismatch", scenario)
    if abs(float(plan.stage_limit_cny) - STAGE_LIMIT_CNY) > 1e-9:
        _refuse("plan_stage_limit_mismatch", scenario)
    if int(plan.max_requests) != int(options.max_requests):
        _refuse("plan_max_requests_mismatch", scenario)
    if "ocr" in plan.operations:
        _refuse("plan_unexpected_ocr_operation", scenario)
    _index_embedding_allocation(plan, scenario, scenario_binding)
    if int(plan.case_count) - 1 != len(dataset.cases):
        _refuse("plan_case_count_mismatch", scenario)
    if int(plan.turn_count) - 1 != expected_turns:
        _refuse("plan_turn_count_mismatch", scenario)
    if sorted(plan.operations) != sorted(
        ("answer", "index_embedding", "query_embedding", "query_expansion", "rerank")
    ):
        _refuse("plan_operations_mismatch", scenario)


def plan_private(bundle: PrivateBundle, options: PlanOptions) -> dict[str, Any]:
    """受控生成四 run 精确计划 + run binding（仓外私有；stdout 只有聚合）。"""
    business_date = _date(
        options.business_date or bundle.business_date, "business_date_invalid"
    )
    if business_date != bundle.business_date:
        _refuse("business_date_binding_mismatch")
    _validate_dataset_shape(bundle.dataset, business_date)
    merged = _prepare_annotation(bundle, Path(options.schema_path), Path(options.scenario_path))
    _verify_axis_counts(merged, bundle.addendum_acceptance)
    _verify_annotation_contract_bindings(bundle.annotation, bundle.contract)

    summary = bundle.contract.safe_summary()
    scenario_counts = summary.get("scenario_counts")
    if not isinstance(scenario_counts, Mapping) or dict(scenario_counts) != dict(
        EXPECTED_SCENARIO_COUNTS
    ):
        _refuse("scenario_counts_mismatch")

    created_utc = _validate_created_utc(options.created_utc)
    code_version = code_digest()
    config = _build_config(
        business_date=business_date,
        inputs=bundle.inputs,
        code_version=code_version,
        thresholds_approved=_thresholds_approved_from_config(),
    )
    config_sha = canonical_sha256(config)

    runs: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for index, scenario in enumerate(_scenario_names()):
        subset = bundle.contract.subset(scenario)
        ingest_plan = bundle.contract.ingest_plan(scenario)
        scenario_binding = bundle.contract.binding(scenario)
        plan_id, run_id = _plan_identity(index, scenario, options)
        plan = bundle.contract.build_plan(
            scenario,
            plan_id=plan_id,
            created_utc=created_utc,
            plan_version=str(options.plan_version),
            max_requests=int(options.max_requests),
        )
        expected_turns = sum(len(case_questions(case)) for case in subset.cases)
        _check_plan(
            plan,
            dataset=subset,
            scenario=scenario,
            scenario_binding=scenario_binding,
            options=options,
            expected_turns=expected_turns,
        )
        identity = (str(plan.plan_id), str(plan.plan_sha256))
        if identity in seen or any(str(item["run_id"]) == run_id for item in runs):
            _refuse("plan_identity_duplicate", scenario)
        seen.add(identity)
        bindings = _evidence_bindings(
            dataset=bundle.dataset,
            scenario=scenario,
            run_id=run_id,
            plan=plan,
            config_sha=config_sha,
            code_version=code_version,
            scenario_binding=scenario_binding,
        )
        runs.append(
            {
                "run_index": index,
                "scenario_id": scenario,
                "run_id": run_id,
                "plan_id": str(plan.plan_id),
                "plan_sha256": str(plan.plan_sha256),
                "plan_file": str(
                    require_outside_repo(Path(options.out_dir), "out_dir")
                    / "plans"
                    / (scenario + ".json")
                ),
                "plan_file_sha256": "",
                "case_count": len(subset.cases),
                "turn_count": expected_turns,
                "total_requests": int(plan.total_requests),
                "worst_case_cny": float(plan.worst_case_cny),
                "reserve_peak_cny": float(plan.reserve_peak_cny),
                "ingest_batches": int(EXPECTED_INGEST_BATCHES[scenario]),
                "ingest_sources": len(ingest_plan.sources),
                "scenario_binding": dict(scenario_binding),
                "evidence_bindings": bindings,
                "_plan": plan,
            }
        )

    out_dir = require_new_dir(options.out_dir, "out_dir")
    out_dir.mkdir(parents=True)
    for run in runs:
        receipt = _write_new_file(Path(run["plan_file"]), run["_plan"].as_dict())
        run["plan_file_sha256"] = receipt["sha256"]
    document: dict[str, Any] = {
        "schema_version": RUN_BINDING_FILE_SCHEMA_VERSION,
        "created_utc": created_utc,
        "fixture_kind": LIVE_FIXTURE_KIND,
        "execution_mode": "live",
        "business_date": business_date,
        "code_version": code_version,
        "config_sha256": config_sha,
        "config": config,
        "dataset": {
            "dataset_version": str(bundle.dataset.manifest.dataset_version),
            "label_version": str(bundle.dataset.manifest.label_version),
            "suite": str(bundle.dataset.manifest.suite),
            "manifest_sha256": str(bundle.dataset.manifest.manifest_sha256),
            "case_count": EXPECTED_CASE_COUNT,
            "total_turns": EXPECTED_TURN_COUNT,
            "scenario_counts": {name: int(value) for name, value in EXPECTED_SCENARIO_COUNTS.items()},
            "axis_counts": {
                str(name): {str(state): int(count) for state, count in table.items()}
                for name, table in dict(merged.public_summary()["axis_counts"]).items()
            },
        },
        "inputs": {name: dict(record) for name, record in bundle.inputs.items()},
        "runs": [{key: value for key, value in run.items() if key != "_plan"} for run in runs],
    }
    document["binding_sha256"] = payload_sha256(document)
    _validate_binding_document(document)
    binding_receipt = _write_new_file(out_dir / "run-binding.json", document)

    public_runs = []
    for run in runs:
        public_runs.append(
            {
                "run_index": int(run["run_index"]),
                "scenario_id": str(run["scenario_id"]),
                "run_id": str(run["run_id"]),
                "plan_id": str(run["plan_id"]),
                "plan_sha256": str(run["plan_sha256"]),
                "case_count": int(run["case_count"]),
                "turn_count": int(run["turn_count"]),
                "total_requests": int(run["total_requests"]),
                "worst_case_cny": float(run["worst_case_cny"]),
                "ingest_batches": int(run["ingest_batches"]),
                "index_embedding_allocation": _index_embedding_allocation(
                    run["_plan"], str(run["scenario_id"]), run["scenario_binding"]
                ),
            }
        )
    return {
        "ok": True,
        "schema_version": PUBLIC_PLAN_SCHEMA_VERSION,
        "tool": TOOL_SCHEMA_VERSION,
        "cases": EXPECTED_CASE_COUNT,
        "turns": EXPECTED_TURN_COUNT,
        "business_date": business_date,
        "chat_model": CHAT_MODEL,
        "model_pinned": True,
        "ingest_batches_source": "frozen_scenario_contract",
        "synthetic_corpus_inference": False,
        "runtime": {
            "holdout_env": "explicit_cli",
            "project_total_limit_cny": float(PROJECT_TOTAL_LIMIT_CNY),
        },
        "scenario_counts": {name: int(value) for name, value in EXPECTED_SCENARIO_COUNTS.items()},
        "axis_counts": document["dataset"]["axis_counts"],
        "gap_counts": {
            "total": int(bundle.addendum_acceptance.get("gap_total", 0)),
            "resolved": int(bundle.addendum_acceptance.get("gap_resolved", 0)),
        },
        "code_version": code_version,
        "config_sha256": config_sha,
        "binding_sha256": document["binding_sha256"],
        "out_dir": str(out_dir),
        "binding_file": str(out_dir / "run-binding.json"),
        "binding_file_sha256": binding_receipt["sha256"],
        "runs": public_runs,
    }


# --------------------------------------------------------------------------- #
# run binding 文档（plan-private 产出、run/preflight/recompute 只读消费）
# --------------------------------------------------------------------------- #


def _validate_binding_document(document: Any) -> None:
    if not isinstance(document, Mapping) or set(document) != set(BINDING_DOC_KEYS):
        _refuse("run_binding_invalid")
    if document.get("schema_version") != RUN_BINDING_FILE_SCHEMA_VERSION:
        _refuse("run_binding_invalid", "schema_version")
    if document.get("fixture_kind") != LIVE_FIXTURE_KIND:
        _refuse("run_binding_invalid", "fixture_kind")
    if document.get("execution_mode") != "live":
        _refuse("run_binding_invalid", "execution_mode")
    _validate_created_utc(str(document.get("created_utc") or ""))
    _date(document.get("business_date"), "run_binding_invalid")
    code_version = _hash(document.get("code_version"), "run_binding_invalid")
    config_sha = _hash(document.get("config_sha256"), "run_binding_invalid")
    config = document.get("config")
    if not isinstance(config, Mapping) or canonical_sha256(config) != config_sha:
        _refuse("run_binding_invalid", "config_sha256")
    if str(config.get("code_version")) != code_version:
        _refuse("run_binding_invalid", "config_code_version")
    if str(config.get("business_date")) != str(document.get("business_date")):
        _refuse("run_binding_invalid", "config_business_date")
    dataset = document.get("dataset")
    if not isinstance(dataset, Mapping):
        _refuse("run_binding_invalid", "dataset")
    if int(dataset.get("case_count", -1)) != EXPECTED_CASE_COUNT:
        _refuse("run_binding_invalid", "dataset.case_count")
    if int(dataset.get("total_turns", -1)) != EXPECTED_TURN_COUNT:
        _refuse("run_binding_invalid", "dataset.total_turns")
    if dict(dataset.get("scenario_counts") or {}) != dict(EXPECTED_SCENARIO_COUNTS):
        _refuse("run_binding_invalid", "dataset.scenario_counts")
    _hash(dataset.get("manifest_sha256"), "run_binding_invalid")
    for key in ("dataset_version", "label_version", "suite"):
        _str(dataset.get(key), "run_binding_invalid", maximum=128)
    inputs = document.get("inputs")
    if not isinstance(inputs, Mapping) or set(inputs) != set(INPUT_NAMES):
        _refuse("run_binding_invalid", "inputs")
    for name in INPUT_NAMES:
        record = inputs[name]
        if not isinstance(record, Mapping) or set(record) != {"path", "sha256", "bytes"}:
            _refuse("run_binding_invalid", "inputs." + name)
        _str(record.get("path"), "run_binding_invalid", maximum=1024)
        _hash(record.get("sha256"), "run_binding_invalid")
        _int(record.get("bytes"), "run_binding_invalid", minimum=1)
    runs = document.get("runs")
    if not isinstance(runs, list) or len(runs) != len(SCENARIO_ORDER):
        _refuse("run_binding_invalid", "runs")
    seen_ids: set[str] = set()
    seen_plans: set[str] = set()
    static_bindings = {
        "config_sha256": config_sha,
        "code_version": code_version,
        "dataset_version": str(dataset["dataset_version"]),
        "manifest_sha256": str(dataset["manifest_sha256"]),
        "label_version": str(dataset["label_version"]),
        "suite": str(dataset["suite"]),
        "fixture_kind": LIVE_FIXTURE_KIND,
    }
    for index, run in enumerate(runs):
        if not isinstance(run, Mapping) or set(run) != set(REQUIRED_RUN_KEYS):
            _refuse("run_binding_invalid", "runs[" + str(index) + "]")
        if int(run.get("run_index", -1)) != index:
            _refuse("run_binding_invalid", "run_index")
        scenario = str(run.get("scenario_id"))
        if scenario != SCENARIO_ORDER[index]:
            _refuse("scenario_order_mismatch", scenario)
        run_id = _str(run.get("run_id"), "run_binding_invalid", maximum=96)
        if RUN_ID_RE.fullmatch(run_id) is None or run_id in seen_ids:
            _refuse("run_binding_invalid", "run_id")
        seen_ids.add(run_id)
        _str(run.get("plan_id"), "run_binding_invalid", maximum=96)
        plan_sha = _hash(run.get("plan_sha256"), "run_binding_invalid")
        if plan_sha in seen_plans:
            _refuse("run_binding_invalid", "plan_sha256_duplicate")
        seen_plans.add(plan_sha)
        plan_file = require_outside_repo(Path(str(run.get("plan_file"))), "plan_file")
        if plan_file.suffix != ".json":
            _refuse("run_binding_invalid", "plan_file")
        _hash(run.get("plan_file_sha256"), "run_binding_invalid")
        _int(run.get("case_count"), "run_binding_invalid", minimum=1, maximum=EXPECTED_CASE_COUNT)
        _int(run.get("turn_count"), "run_binding_invalid", minimum=1, maximum=EXPECTED_TURN_COUNT)
        _int(run.get("total_requests"), "run_binding_invalid", minimum=1)
        if float(run.get("worst_case_cny")) <= 0 or float(run.get("reserve_peak_cny")) <= 0:
            _refuse("run_binding_invalid", "money")
        if int(run.get("ingest_batches", -1)) != EXPECTED_INGEST_BATCHES[scenario]:
            _refuse("ingest_batches_mismatch", scenario)
        _int(run.get("ingest_sources"), "run_binding_invalid", minimum=1, maximum=64)
        scenario_binding = run.get("scenario_binding")
        try:
            from mktkb.evaluation.p2_holdout_scenarios import validate_plan_scenario_binding

            validate_plan_scenario_binding(scenario_binding)
        except ScenarioError:
            _refuse("run_binding_invalid", "scenario_binding")
        if str(scenario_binding.get("scenario_id")) != scenario:
            _refuse("run_binding_invalid", "scenario_binding.scenario_id")
        bindings = run.get("evidence_bindings")
        if not isinstance(bindings, Mapping) or set(bindings) != set(BINDING_KEYS):
            _refuse("run_binding_invalid", "evidence_bindings")
        for key in BINDING_KEYS:
            _str(bindings.get(key), "run_binding_invalid", maximum=256)
        if str(bindings.get("fixture_kind")) != LIVE_FIXTURE_KIND:
            _refuse("run_binding_invalid", "evidence_bindings.fixture_kind")
        if str(bindings.get("index_revision")) != LIVE_PENDING_INDEX_REVISION:
            _refuse("run_binding_invalid", "evidence_bindings.index_revision")
        for key, value in static_bindings.items():
            if str(bindings.get(key)) != str(value):
                _refuse("run_binding_invalid", "evidence_bindings." + key)
        if str(bindings.get("plan_sha256")) != plan_sha:
            _refuse("run_binding_invalid", "evidence_bindings.plan_sha256")
        if str(bindings.get("run_id")) != run_id or str(bindings.get("scenario_id")) != scenario:
            _refuse("run_binding_invalid", "evidence_bindings.identity")
        if str(bindings.get("scenario_contract_sha256")) != str(
            scenario_binding.get("scenario_contract_sha256")
        ):
            _refuse("run_binding_invalid", "evidence_bindings.scenario_contract_sha256")
        for key in ("assignment_sha256", "custody_sha256"):
            if str(bindings.get(key)) != str(scenario_binding.get(key)):
                _refuse("run_binding_invalid", "evidence_bindings." + key)
    expected_binding_sha = payload_sha256(
        {key: value for key, value in document.items() if key != "binding_sha256"}
    )
    if str(document.get("binding_sha256")) != expected_binding_sha:
        _refuse("run_binding_invalid", "binding_sha256")


def load_run_binding(path: Path | str) -> dict[str, Any]:
    target = assert_private_path(path)
    if not target.is_file():
        _refuse("run_binding_missing")
    document = _read_json_mapping(target, "run_binding_unreadable")
    _validate_binding_document(document)
    return document


def _verify_input_digests(document: Mapping[str, Any]) -> None:
    inputs = document["inputs"]
    for name in INPUT_NAMES:
        record = inputs[name]
        path = Path(str(record["path"]))
        if not path.is_file():
            _refuse("input_file_missing", name)
        if sha256_file(path) != str(record["sha256"]):
            _refuse("input_changed_since_plan", name)


def _paths_from_document(document: Mapping[str, Any]) -> InputPaths:
    inputs = document["inputs"]
    return InputPaths(**{name: Path(str(inputs[name]["path"])) for name in INPUT_NAMES})


def _select_run(document: Mapping[str, Any], run_index: int) -> Mapping[str, Any]:
    runs = list(document["runs"])
    if not isinstance(run_index, int) or not 0 <= run_index < len(runs):
        _usage("run_index_invalid")
    run = runs[run_index]
    if str(run["scenario_id"]) != SCENARIO_ORDER[run_index]:
        _refuse("scenario_order_mismatch")
    return run


def _load_plan_for_run(
    document: Mapping[str, Any], run_entry: Mapping[str, Any]
) -> P2RunPlan:
    plan_file = assert_private_path(Path(str(run_entry["plan_file"])))
    if not plan_file.is_file():
        _refuse("plan_file_missing")
    if sha256_file(plan_file) != str(run_entry["plan_file_sha256"]):
        _refuse("plan_file_changed")
    payload = _read_json_mapping(plan_file, "plan_unreadable")
    try:
        plan = P2RunPlan.from_dict(payload)
    except ValueError:
        _refuse("plan_invalid")
    if str(plan.plan_id) != str(run_entry["plan_id"]):
        _refuse("plan_identity_mismatch", "plan_id")
    if str(plan.plan_sha256) != str(run_entry["plan_sha256"]):
        _refuse("plan_identity_mismatch", "plan_sha256")
    if dict(plan.scenario_binding or {}) != dict(run_entry["scenario_binding"]):
        _refuse("plan_scenario_mismatch")
    return plan


def _expected_static_bindings(
    document: Mapping[str, Any], run_entry: Mapping[str, Any], plan: P2RunPlan
) -> dict[str, str]:
    dataset = document["dataset"]
    scenario_binding = run_entry["scenario_binding"]
    return {
        "run_id": str(run_entry["run_id"]),
        "plan_id": str(plan.plan_id),
        "plan_sha256": str(plan.plan_sha256),
        "dataset_version": str(dataset["dataset_version"]),
        "manifest_sha256": str(dataset["manifest_sha256"]),
        "label_version": str(dataset["label_version"]),
        "suite": str(dataset["suite"]),
        "scenario_id": str(run_entry["scenario_id"]),
        "scenario_contract_sha256": str(scenario_binding["scenario_contract_sha256"]),
        "assignment_sha256": str(scenario_binding["assignment_sha256"]),
        "custody_sha256": str(scenario_binding["custody_sha256"]),
        "config_sha256": str(document["config_sha256"]),
        "pipeline_version": str(run_entry["evidence_bindings"]["pipeline_version"]),
        "code_version": str(document["code_version"]),
        "fixture_kind": LIVE_FIXTURE_KIND,
    }


def _verify_plan_binding(
    document: Mapping[str, Any], run_entry: Mapping[str, Any], plan: P2RunPlan
) -> None:
    expected = _expected_static_bindings(document, run_entry, plan)
    bindings = dict(run_entry["evidence_bindings"])
    for key, value in expected.items():
        if str(bindings.get(key)) != str(value):
            _refuse("evidence_binding_mismatch", key)
    if str(bindings.get("pipeline_version")) != str(product_pipeline_version()):
        _refuse("pipeline_changed")


def _compose_run_binding(
    *,
    gate: Any,
    plan: P2RunPlan,
    run_id: str,
    scenario: str,
    business_date: str,
    code_version: str,
    config_sha: str,
) -> dict[str, str]:
    authorization = gate.authorization
    scope = attempt_scope_sha256(
        run_id=run_id,
        plan_sha256=str(plan.plan_sha256),
        scenario_id=scenario,
        go_sha256=str(authorization.go_sha256),
        ledger_sha256=str(authorization.ledger_sha256),
    )
    return {
        "plan_sha256": str(plan.plan_sha256),
        "run_id": str(run_id),
        "scenario_id": str(scenario),
        "go_sha256": str(authorization.go_sha256),
        "ledger_sha256": str(authorization.ledger_sha256),
        "business_date": str(business_date),
        "code_version": str(code_version),
        "config_sha256": str(config_sha),
        "attempt_scope_sha256": scope,
    }


def _verify_run_binding_entry(
    run_binding: Mapping[str, str], run_entry: Mapping[str, Any]
) -> None:
    bindings = dict(run_entry["evidence_bindings"])
    for key in ("run_id", "plan_sha256", "scenario_id", "code_version", "config_sha256"):
        if str(run_binding.get(key)) != str(bindings.get(key)):
            _refuse("run_binding_mismatch", key)


def _verify_env_against_config(env: Any, config: Mapping[str, Any]) -> None:
    def host(url: str) -> str:
        return str(url).split("//")[-1].split("/")[0].strip().lower()

    providers = config.get("providers")
    if not isinstance(providers, Mapping):
        _refuse("run_binding_invalid", "providers")
    if str(env.chat_model) != str(providers["chat"]["model"]):
        _refuse("env_chat_model_mismatch")
    if host(env.chat_base_url) != str(providers["chat"]["host"]):
        _refuse("env_chat_host_mismatch")
    if host(env.dashscope_base_url) != str(providers["embedding"]["host"]):
        _refuse("env_dashscope_host_mismatch")
    if str(env.ocr_region) != str(providers["ocr_region"]):
        _refuse("env_ocr_region_mismatch")
    if not bool(env.ocr_enabled):
        _refuse("env_ocr_disabled")


def _validate_fixed_paths(
    go_path: Path | str | None, budget_path: Path | str | None, ledger_path: Path | str | None
) -> None:
    for supplied, fixed, name in (
        (go_path, p2a.P2_GO_PATH, "go"),
        (budget_path, p2a.P2_BUDGET_PATH, "budget"),
        (ledger_path, p2a.P2_LEDGER_PATH, "ledger"),
    ):
        if supplied is None:
            continue
        if Path(supplied).resolve(strict=False) != Path(fixed).resolve(strict=False):
            _refuse("fixed_path_mismatch", name)


# --------------------------------------------------------------------------- #
# 受控路径/密钥
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class PathOptions:
    out_dir: Path
    evidence_root: Path
    seal_root: Path
    evidence_key_file: Path

    def as_public(self) -> dict[str, str]:
        return {
            "out_dir": str(self.out_dir),
            "evidence_root": str(self.evidence_root),
            "seal_root": str(self.seal_root),
            "evidence_key_file": str(self.evidence_key_file),
        }


def check_target_paths(options: PathOptions) -> PathOptions:
    out_dir = require_new_dir(options.out_dir, "out_dir")
    evidence_root = require_new_or_empty_dir(options.evidence_root, "evidence_root")
    seal_root = require_new_or_empty_dir(options.seal_root, "seal_root")
    key_file = require_outside_repo(options.evidence_key_file, "evidence_key_file")
    if not key_file.is_file():
        _refuse("evidence_key_missing")
    raw = key_file.read_bytes()
    if len(raw) != 44:
        _refuse("evidence_key_invalid")
    try:
        from cryptography.fernet import Fernet

        Fernet(raw)
    except Exception:  # noqa: BLE001 - 坏 key 结构统一拒绝
        _refuse("evidence_key_invalid")
    return PathOptions(
        out_dir=out_dir,
        evidence_root=evidence_root,
        seal_root=seal_root,
        evidence_key_file=key_file,
    )


# --------------------------------------------------------------------------- #
# preflight（check-only：零付费、零模型）
# --------------------------------------------------------------------------- #


def _go_aggregate(now: datetime | None) -> dict[str, Any]:
    try:
        payload = p2a.load_go_payload()
    except Exception as exc:  # noqa: BLE001 - 缺 GO 也是可报告的预检事实
        return {"available": False, "error_code": _error_code(exc)}
    scope = payload.get("scope") if isinstance(payload.get("scope"), Mapping) else {}
    return {
        "available": True,
        "go_sha256": payload_sha256(payload),
        "issued_by": str(payload.get("issued_by") or ""),
        "issued_utc": str(payload.get("issued_utc") or ""),
        "expires_utc": str(payload.get("expires_utc") or ""),
        "plan_id": str(scope.get("plan_id") or ""),
        "plan_sha256": str(scope.get("plan_sha256") or ""),
        "operations": sorted(str(item) for item in (scope.get("operations") or ())),
        "max_requests": int(scope.get("max_requests") or 0),
        "max_request_cny": float(scope.get("max_request_cny") or 0.0),
        "budget_ledger_sha256": str(payload.get("budget_ledger_sha256") or ""),
    }


def _error_code(exc: BaseException) -> str:
    return str(
        getattr(exc, "reason", None)
        or getattr(exc, "code", None)
        or type(exc).__name__
    )


def preflight(
    *,
    env_file: Path | str,
    binding_path: Path | str,
    run_index: int,
    paths: PathOptions,
    runtime: RuntimeOptions | None = None,
    go_path: Path | str | None = None,
    budget_path: Path | str | None = None,
    ledger_path: Path | str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    checked_runtime = check_runtime_options(runtime)
    values = merge_runtime_env(read_authorized_env(env_file), checked_runtime)
    document = load_run_binding(binding_path)
    run_entry = _select_run(document, run_index)
    _verify_input_digests(document)
    if str(document["code_version"]) != code_digest():
        _refuse("code_changed_since_plan")
    _validate_fixed_paths(go_path, budget_path, ledger_path)
    checked_paths = check_target_paths(paths)
    plan = _load_plan_for_run(document, run_entry)
    _verify_plan_binding(document, run_entry, plan)

    checks: list[dict[str, Any]] = [{"name": "binding", "ok": True}]
    snapshot = None
    snapshot_error = None
    authorization = None
    authorization_error = None
    go = {"available": False}
    with applied_env(values):
        try:
            live_env = p2_live.load_live_env(None)
            _verify_env_against_config(live_env, document["config"])
            checks.append({"name": "env", "ok": True})
        except Exception as exc:  # noqa: BLE001 - 预检只报固定码
            live_env = None
            checks.append({"name": "env", "ok": False, "error_code": _error_code(exc)})
        go = _go_aggregate(now)
        try:
            snapshot = p2a.read_ledger_snapshot()
            checks.append({"name": "ledger", "ok": True})
        except Exception as exc:  # noqa: BLE001
            snapshot_error = _error_code(exc)
            checks.append({"name": "ledger", "ok": False, "error_code": snapshot_error})
        if snapshot is not None:
            try:
                # authorize_p2 不接受 None：显式给固定路径（与 P2Gate.open 的来源判定一致）。
                authorization = p2a.authorize_p2(
                    plan,
                    go_payload=p2a.P2_GO_PATH,
                    budget_payload=p2a.P2_BUDGET_PATH,
                    ledger_snapshot=snapshot,
                    now=now,
                )
                checks.append(
                    {
                        "name": "authorization",
                        "ok": bool(authorization.production_ready),
                        "production_ready": bool(authorization.production_ready),
                    }
                )
            except Exception as exc:  # noqa: BLE001
                authorization_error = _error_code(exc)
                checks.append(
                    {"name": "authorization", "ok": False, "error_code": authorization_error}
                )
    env_public = (
        None
        if live_env is None
        else {
            "chat_model": str(live_env.chat_model),
            "chat_host": str(live_env.chat_base_url).split("//")[-1].split("/")[0],
            "dashscope_host": str(live_env.dashscope_base_url).split("//")[-1].split("/")[0],
            "ocr_region": str(live_env.ocr_region),
            "ocr_enabled": bool(live_env.ocr_enabled),
        }
    )
    ok = all(bool(check.get("ok")) for check in checks)
    payload = {
        "ok": ok,
        "schema_version": PREFLIGHT_SCHEMA_VERSION,
        "tool": TOOL_SCHEMA_VERSION,
        "zero_paid_probes": True,
        "run_index": int(run_index),
        "run_id": str(run_entry["run_id"]),
        "scenario_id": str(run_entry["scenario_id"]),
        "plan_id": str(run_entry["plan_id"]),
        "plan_sha256": str(run_entry["plan_sha256"]),
        "business_date": str(document["business_date"]),
        "code_version": str(document["code_version"]),
        "config_sha256": str(document["config_sha256"]),
        "binding_sha256": str(document["binding_sha256"]),
        "checks": checks,
        "env": {
            **({"names": sorted(values)} if env_public is not None else {}),
            "total_limit_cny": float(checked_runtime.project_total_limit_cny),
            "total_limit_source": "explicit_cli",
            "chat_model": CHAT_MODEL,
            "model_pinned": True,
            **(env_public or {}),
        },
        "paths": checked_paths.as_public(),
        "go": {
            **go,
            "plan_sha_match": (
                go.get("available") is True
                and str(go.get("plan_sha256")) == str(run_entry["plan_sha256"])
            ),
        },
        "ledger": (
            None
            if snapshot is None
            else {
                "accounted_cny": float(snapshot.accounted_cny),
                "historical_accounted_cny": float(snapshot.historical_accounted_cny),
                "p2_stage_accounted_cny": float(snapshot.p2_stage_accounted_cny),
                "p2_center_accounted_cny": {
                    str(center): float(value)
                    for center, value in dict(snapshot.p2_center_accounted_cny).items()
                },
                "reservation_count": int(snapshot.reservation_count),
                "result_count": int(snapshot.result_count),
                "historical_prefix_sha256": str(snapshot.historical_prefix_sha256),
                "ledger_sha256": str(snapshot.ledger_sha256),
            }
        ),
        "authorization": (
            None
            if authorization is None
            else {
                "production_ready": bool(authorization.production_ready),
                "stage_remaining_cny": float(authorization.stage_remaining_cny),
                "center_remaining_cny": {
                    str(center): float(value)
                    for center, value in dict(authorization.center_remaining_cny).items()
                },
                "max_requests": int(authorization.max_requests),
                "requests_used": int(authorization.requests_used),
                "requests_remaining": int(authorization.requests_remaining),
                "max_request_cny": float(authorization.max_request_cny),
                "operations": list(authorization.operations),
            }
        ),
        "error_code": None if ok else "preflight_failed",
    }
    return payload


# --------------------------------------------------------------------------- #
# 封存 / 证据读回 / run receipt
# --------------------------------------------------------------------------- #


def _safe_name(value: str) -> str:
    text = "".join(char for char in str(value) if char.isalnum() or char in {"-", "_"})[:64]
    return text or "run"


# --------------------------------------------------------------------------- #
# C：封存前清除明文派生物（index DB / storage / p2-run）+ 内容扫描
# --------------------------------------------------------------------------- #


def _plaintext_needles(dataset: Any, labels: Any = None) -> tuple[str, ...]:
    """从内存 dataset 取题面/答案针；只用于本机扫描，绝不写进任何产物。"""
    needles: set[str] = set()
    for case in getattr(dataset, "cases", ()) or ():
        try:
            questions = case_questions(case)
        except Exception:  # noqa: BLE001 - 题面结构异常不阻塞清理
            questions = ()
        for text in questions:
            value = str(text or "").strip()
            if len(value) >= 4:
                needles.add(value)
        question = str(getattr(case, "question", "") or "").strip()
        if len(question) >= 4:
            needles.add(question)
    if isinstance(labels, Mapping):
        for payload in labels.values():
            if not isinstance(payload, Mapping):
                continue
            for key in ("reference_answer", "answer"):
                value = str(payload.get(key) or "").strip()
                if len(value) >= 4:
                    needles.add(value)
    return tuple(sorted(needles))


def _file_contains_any(path: Path, needles: Sequence[bytes]) -> bool:
    if not needles:
        return False
    longest = max(len(item) for item in needles)
    overlap = max(0, longest - 1)
    tail = b""
    try:
        with open(path, "rb") as stream:
            while True:
                chunk = stream.read(1024 * 1024)
                if not chunk:
                    break
                window = tail + chunk
                if any(needle in window for needle in needles):
                    return True
                tail = window[-overlap:] if overlap else b""
    except OSError:
        return True  # 读不了就不敢声明确认干净
    return False


def _scan_plaintext(root: Path, needles: Sequence[str]) -> dict[str, Any]:
    """扫描目录内所有普通文件是否含题面/答案明文；只回相对路径与计数，不回原文。"""
    base = Path(root)
    encoded = [str(item).encode("utf-8") for item in needles if str(item)]
    text_needles = [str(item) for item in needles if str(item)]
    hits: list[str] = []
    files = 0
    if base.exists():
        for path in sorted(p for p in base.rglob("*") if p.is_file()):
            files += 1
            try:
                rel = path.relative_to(base).as_posix()
            except ValueError:
                rel = path.name
            if any(item in rel for item in text_needles) or _file_contains_any(path, encoded):
                hits.append(rel)
    return {
        "schema_version": CLEANUP_SCHEMA_VERSION,
        "needles": len(text_needles),
        "files_scanned": files,
        "hit_count": len(hits),
        "hit_paths": hits,
        "clean": not hits,
    }


def _record_removed_file(path: Path, root: Path, removed: list[dict[str, Any]], errors: list[str]) -> None:
    try:
        stat = path.stat()
        digest = sha256_file(path)
        rel = path.relative_to(root).as_posix()
    except OSError:
        errors.append("remove_stat_failed")
        return
    removed.append(
        {
            "path": rel,
            "sha256": digest,
            "sha256_before_removal": digest,
            "bytes": int(stat.st_size),
        }
    )


def _remove_tree(
    path: Path, root: Path, removed: list[dict[str, Any]], errors: list[str]
) -> None:
    target = Path(path)
    if not target.exists():
        return
    if target.is_dir():
        for child in sorted(p for p in target.rglob("*") if p.is_file()):
            _record_removed_file(child, root, removed, errors)
        try:
            shutil.rmtree(target)
        except OSError:
            errors.append("remove_tree_failed")
        return
    _record_removed_file(target, root, removed, errors)
    try:
        target.unlink()
    except OSError:
        errors.append("remove_file_failed")


def _retain_composition_part(root: Path, dataset: Any) -> str:
    """Retain only audited aggregate and actual run binding before deleting p2-run."""
    run = root / "p2-run"
    card_path, summary_path = run / "holdout_scorecard.json", run / "summary.json"
    if not isinstance(getattr(dataset, "identity", None), Mapping) or not dataset.identity.get("scenario_binding"):
        return "not_applicable"
    if (root / "controlled" / "composition-part.json").exists():
        return "collision"
    if not card_path.exists() and not summary_path.exists():
        return "not_available"
    try:
        card = _read_json_mapping(card_path, "composition_part_invalid")
        summary = _read_json_mapping(summary_path, "composition_part_invalid")
        binding = summary["binding"]
        allowed = {"binding_version", "config_hash", "complete", "missing", "dataset_version",
                   "dataset_sha256", "manifest_sha256", "label_version", "pipeline_version",
                   "index_revision", "provider", "gate_version", "gate_config_hash",
                   "trace_identity_bound", "scenario_binding"}
        if not isinstance(binding, dict) or not set(binding).issubset(allowed):
            raise ValueError("binding fields")
        if binding.get("scenario_binding") != dataset.identity.get("scenario_binding"):
            raise ValueError("scenario mismatch")
        from mktkb.evaluation.p2_holdout_scenarios import validate_plan_scenario_binding
        validate_plan_scenario_binding(binding["scenario_binding"])
        def safe_scalar(value: Any) -> bool:
            if value is None or type(value) in (bool, int):
                return True
            if isinstance(value, str):
                return bool(re.fullmatch(r"[A-Za-z0-9_.:+|@/()\-]{1,256}", value)) and not value.startswith("/") and "://" not in value
            return False
        for name, value in binding.items():
            if name in {"provider", "scenario_binding"}:
                continue
            if name == "missing":
                if not isinstance(value, list) or not all(safe_scalar(item) for item in value):
                    raise ValueError("binding missing fields")
            elif not safe_scalar(value):
                raise ValueError("binding value")
        provider = binding.get("provider")
        provider_keys = {"chat", "embedding", "rerank", "ocr", "provider", "model", "transport", "impl"}
        def safe_provider(value: Any) -> bool:
            if isinstance(value, dict):
                return all(k in provider_keys and safe_provider(v) for k, v in value.items())
            return value is None or (isinstance(value, str) and len(value) <= 256 and "/" not in value and "\\" not in value)
        if not safe_provider(provider):
            raise ValueError("provider fields")
        run_id = summary["run_id"]
        status = summary["status"]
        turns = summary["turns"]["executed"]
        if (status not in {"succeeded", "blocked", "aborted"} or type(turns) is not int or turns < 0
                or not isinstance(run_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", run_id)):
            raise ValueError("summary fields")
        p2_runner._assert_holdout_scorecard_payload(card, dataset, run_id=run_id,
                                                   config_hash=binding.get("config_hash") or None)
        packet = {"aggregate": card, "binding": binding, "status": status,
                  "run_id": run_id, "turns_executed": turns}
        raw = json.dumps(packet, ensure_ascii=False, sort_keys=True)
        for case in dataset.cases:
            if str(case.case_id or "") and str(case.case_id) in raw:
                raise ValueError("case identifier")
            if any(len(s.strip()) >= 2 and s.strip() in raw for s in p2_runner._holdout_leak_needles(case)):
                raise ValueError("private text")
        target = root / "controlled" / "composition-part.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("x", encoding="utf-8") as handle:
            handle.write(raw + "\n")
        return "retained"
    except (EntryError, ScenarioError, ValueError, TypeError, KeyError, OSError, p2_runner.P2RunError):
        return "unavailable"


def _purge_plaintext_derivatives(
    out_dir: Path,
    dataset: Any,
    *,
    extra_needles: Sequence[str] = (),
) -> dict[str, Any]:
    """close 之后、封存之前：删 data/（index DB/storage）、p2-run/ 与残留明文文件。

    保留 out_dir/controlled/case-plan.json（无题面/答案/query 文本的安全回执）；
    若连它也命中明文针，则 fail closed（不删除必要回执、也不把该目录称为已封存）。
    """
    from mktkb.evaluation.product_adapter import ProductPaths

    root = Path(out_dir)
    paths = ProductPaths.of(root)
    needles = tuple(
        sorted({str(item) for item in _plaintext_needles(dataset) if str(item)} | set(extra_needles))
    )
    removed: list[dict[str, Any]] = []
    errors: list[str] = []
    business_family = [paths.business_db] + [
        paths.business_db.with_name(paths.business_db.name + suffix)
        for suffix in ("-wal", "-shm", "-journal")
    ]
    trace_family = [paths.trace_db] + [
        paths.trace_db.with_name(paths.trace_db.name + suffix) for suffix in ("-wal", "-shm")
    ]
    business_removed_before = not any(path.exists() for path in business_family)
    trace_removed_before = not any(path.exists() for path in trace_family)

    composition_retention = _retain_composition_part(root, dataset)
    if composition_retention == "collision":
        errors.append("composition_retention_collision")

    # 整个 data/ 目录包含 index DB 及其 query state、storage 上传原文件与 observability；
    # 整个 p2-run/ 目录包含 attempts/case_id/ingest 文档名等逐题私有元数据。
    for target in (paths.run_dir, paths.index_db.parent):
        _remove_tree(target, root, removed, errors)
    # 防御性兜底：路径布局变化时仍逐个清掉已知明文库/存储/业务库/跟踪库。
    for target in (
        *[paths.index_db.with_name(paths.index_db.name + suffix) for suffix in ("", "-wal", "-shm", "-journal")],
        paths.storage,
        *business_family,
        *trace_family,
    ):
        _remove_tree(target, root, removed, errors)

    scan = _scan_plaintext(root, needles)
    deleted_residual: list[str] = []
    for hit in list(scan["hit_paths"]):
        target = root / hit
        if target.parent == root / "controlled" and target.name == "case-plan.json":
            errors.append("plaintext_residual_required")
            continue
        _remove_tree(target, root, removed, errors)
        deleted_residual.append(hit)
    final_scan = _scan_plaintext(root, needles)
    if composition_retention == "retained" and not (root / "controlled" / "composition-part.json").is_file():
        composition_retention = "unavailable"
    retained = sorted(
        path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()
    ) if root.exists() else []
    clean = bool(not errors and final_scan["clean"] and not (root / "data").exists() and not (root / "p2-run").exists())
    return {
        "schema_version": CLEANUP_SCHEMA_VERSION,
        "composition_retention": composition_retention,
        "trace_db_removed": not any(path.exists() for path in trace_family),
        "trace_db_removed_at_close": bool(trace_removed_before),
        "business_db_removed": not any(path.exists() for path in business_family),
        "business_db_removed_at_close": bool(business_removed_before),
        "data_dir_removed": not (root / "data").exists(),
        "run_dir_removed": not (root / "p2-run").exists(),
        "removed_paths": removed,
        "removed_count": len(removed),
        "removed_bytes": sum(int(item["bytes"]) for item in removed),
        "residual_deleted": deleted_residual,
        "plaintext_scan": final_scan,
        "plaintext_clean": clean,
        "cleanup_errors": sorted(set(errors)),
        "policy": "sealed_out_dir_allows_only_ciphertext_safe_aggregates_and_index_hashes",
        "retained_paths": retained,
    }


def _make_read_only(root: Path) -> int:
    changed = 0
    base = Path(root)
    if not base.exists():
        return 0
    for path in sorted(p for p in base.rglob("*") if p.is_file()):
        try:
            os.chmod(path, 0o444)
            changed += 1
        except OSError:
            continue
    return changed


def seal_trees(
    *, out_dir: Path, evidence_root: Path, seal_root: Path, run_id: str
) -> dict[str, Any]:
    """整 out_dir + 证据根 -> 仓外只读归档 + 逐文件摘要（明文不复制、题干库已删除）。"""
    seal_dir = Path(seal_root) / _safe_name(run_id)
    if seal_dir.exists():
        _refuse("seal_target_exists")
    seal_dir.mkdir(parents=True)
    out_before = tree_digest(out_dir) if Path(out_dir).exists() else None
    evidence_before = tree_digest(evidence_root) if Path(evidence_root).exists() else None
    _make_read_only(Path(out_dir))
    _make_read_only(Path(evidence_root))
    out_after = tree_digest(out_dir) if out_before is not None else None
    evidence_after = tree_digest(evidence_root) if evidence_before is not None else None
    if out_before is not None and out_after is not None:
        if out_before["tree_sha256"] != out_after["tree_sha256"]:
            _refuse("seal_readonly_mismatch", "out_dir")
    if evidence_before is not None and evidence_after is not None:
        if evidence_before["tree_sha256"] != evidence_after["tree_sha256"]:
            _refuse("seal_readonly_mismatch", "evidence_root")
    manifest = {
        "schema_version": SEAL_MANIFEST_SCHEMA_VERSION,
        "run_id": str(run_id),
        "mode": "read_only_archive",
        "sealed_utc": _utc_now(),
        "out_dir": out_after,
        "evidence_root": evidence_after,
    }
    target = seal_dir / "seal-manifest.json"
    target.write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    readback = _read_json_mapping(target, "seal_manifest_unreadable")
    if readback != manifest:
        _refuse("seal_readback_mismatch")
    return {
        "sealed": True,
        "mode": "read_only_archive",
        "seal_dir": str(seal_dir),
        "seal_manifest": str(target),
        "seal_manifest_sha256": sha256_file(target),
        "out_tree_sha256": None if out_after is None else out_after["tree_sha256"],
        "out_file_count": 0 if out_after is None else out_after["file_count"],
        "out_bytes": 0 if out_after is None else out_after["bytes"],
        "evidence_tree_sha256": (
            None if evidence_after is None else evidence_after["tree_sha256"]
        ),
        "evidence_file_count": 0 if evidence_after is None else evidence_after["file_count"],
        "evidence_bytes": 0 if evidence_after is None else evidence_after["bytes"],
    }


def _read_artifacts(out_dir: Path) -> dict[str, Any]:
    run_dir = Path(out_dir) / "p2-run"
    payload: dict[str, Any] = {}
    for name in ("summary", "run_result", "gate"):
        path = run_dir / (name + ".json")
        if path.is_file():
            try:
                payload[name] = _read_json_mapping(path, "artifact_unreadable")
            except EntryError:
                payload[name] = None
    return payload


def _evidence_dir(evidence_root: Path, writer: Any, run_id: str) -> Path | None:
    if writer is not None:
        root = getattr(writer, "root_dir", None)
        name = getattr(writer, "run_name", None)
        if root is not None and name:
            return Path(root) / str(name)
    root = Path(evidence_root)
    if not root.exists():
        return None
    children = [path for path in root.iterdir() if path.is_dir()]
    if len(children) == 1:
        return children[0]
    return None


def _collect_evidence(
    evidence_dir: Path | None,
    *,
    key: bytes,
    expected_bindings: Mapping[str, str],
    run_binding: Mapping[str, str] | None,
) -> dict[str, Any]:
    """close 之后从磁盘读回密文：证明"purge 前已实际写盘且可解密"，并核对 run binding。"""
    if evidence_dir is None or not Path(evidence_dir).is_dir():
        return {"available": False, "reason": "evidence_dir_missing", "turn_files": 0}
    root = Path(evidence_dir)
    errors: list[str] = []
    turns: list[dict[str, Any]] = []
    status_counts: dict[str, int] = {}
    for path in sorted(root.glob("turn-*.fernet")):
        try:
            envelope = read_encrypted_evidence(
                path, key=key, expected_bindings=dict(expected_bindings)
            )
        except EvidenceIOError as exc:
            errors.append("turn:" + str(exc.code))
            continue
        if run_binding is not None and dict(envelope.get("run_binding") or {}) != dict(run_binding):
            errors.append("turn:run_binding_mismatch")
        turn_meta = envelope.get("turn") if isinstance(envelope.get("turn"), Mapping) else {}
        completeness = (
            envelope.get("completeness")
            if isinstance(envelope.get("completeness"), Mapping)
            else {}
        )
        status = str(completeness.get("status"))
        status_counts[status] = status_counts.get(status, 0) + 1
        turns.append(
            {
                "turn_index": int(turn_meta.get("turn_index", -1)),
                "status": status,
                "path": str(path),
                "sha256": sha256_file(path),
                "http_status": turn_meta.get("http_status"),
            }
        )
    turns.sort(key=lambda item: item["turn_index"])
    manifest_files = sorted(root.glob("manifest-*.fernet"))
    manifest: dict[str, Any] | None = None
    if manifest_files:
        try:
            manifest = read_encrypted_evidence(
                manifest_files[0], key=key, expected_bindings=dict(expected_bindings)
            )
        except EvidenceIOError as exc:
            errors.append("manifest:" + str(exc.code))
    manifest_summary = (
        manifest.get("summary") if isinstance(manifest, Mapping) and isinstance(manifest.get("summary"), Mapping) else None
    )
    return {
        "available": True,
        "dir": str(root),
        "turn_files": len(turns),
        "manifest_files": len(manifest_files),
        "status_counts": status_counts,
        "manifest_present": manifest is not None,
        "manifest_turn_count": (
            int(manifest_summary.get("turn_count", -1)) if manifest_summary else None
        ),
        "manifest_blocked": (
            bool(manifest_summary.get("blocked")) if manifest_summary else None
        ),
        "manifest_sha256": (
            sha256_file(manifest_files[0]) if manifest_files else None
        ),
        "turns": turns,
        "errors": errors,
        "readback_ok": not errors,
    }


def _quality_status(value: Any) -> str:
    text = str(value or "error")
    if text == "skipped_ocr":
        return "error"
    return text if text in {"pass", "fail", "error", "not_executed"} else "error"


def _expected_strata(dataset: Any) -> dict[str, int]:
    identity = dict(getattr(dataset, "identity", {}) or {})
    strata = identity.get("strata")
    total = sum(len(case_questions(case)) for case in dataset.cases)
    if isinstance(strata, Mapping) and int(sum(int(v) for v in strata.values())) == len(dataset.cases):
        return {str(name): int(count) for name, count in strata.items() if int(count)}
    counts: dict[str, int] = {}
    for case in dataset.cases:
        name = str(case.stratum)
        counts[name] = counts.get(name, 0) + 1
    if total <= 0:
        _refuse("dataset_case_turns_invalid")
    return counts


def _validate_case_plan_document(
    payload: Any,
    *,
    cases: Sequence[Any],
    static_bindings: Mapping[str, str],
    run_binding: Mapping[str, str] | None = None,
    require_binding_match: bool = True,
) -> dict[str, Any]:
    exact = {
        "schema_version",
        "fixture_kind",
        "run_id",
        "bindings",
        "run_binding",
        "execution_mode",
        "real_calls",
        "thresholds_approved",
        "expected_strata",
        "cases",
    }
    if not isinstance(payload, Mapping) or set(payload) != exact:
        _refuse("case_plan_invalid")
    if payload.get("schema_version") != LIVE_CASEPLAN_SCHEMA_VERSION:
        _refuse("case_plan_invalid", "schema_version")
    if payload.get("fixture_kind") != LIVE_FIXTURE_KIND:
        _refuse("case_plan_invalid", "fixture_kind")
    if payload.get("execution_mode") != "live":
        _refuse("case_plan_invalid", "execution_mode")
    bindings = payload.get("bindings")
    if not isinstance(bindings, Mapping) or set(bindings) != set(BINDING_KEYS):
        _refuse("case_plan_invalid", "bindings")
    for key in BINDING_KEYS:
        _str(bindings.get(key), "case_plan_invalid", maximum=256)
    if str(bindings.get("fixture_kind")) != LIVE_FIXTURE_KIND:
        _refuse("case_plan_invalid", "bindings.fixture_kind")
    if re.fullmatch(r"[0-9]{1,12}", str(bindings.get("index_revision"))) is None:
        _refuse("case_plan_invalid", "bindings.index_revision")
    for key, value in static_bindings.items():
        if str(bindings.get(key)) != str(value):
            _refuse("case_plan_invalid", "bindings." + key)
    control = payload.get("run_binding")
    try:
        from mktkb.evaluation.p2_evidence_capture import validate_run_binding

        resolved_run_binding = validate_run_binding(control, bindings)
    except EvidenceCaptureConfigError as exc:
        _refuse("case_plan_invalid", str(exc)[:80])
    if run_binding is not None and require_binding_match:
        if dict(resolved_run_binding) != dict(run_binding):
            _refuse("case_plan_binding_mismatch")
    _int(payload.get("real_calls"), "case_plan_invalid", minimum=0, maximum=1600)
    if not isinstance(payload.get("thresholds_approved"), bool):
        _refuse("case_plan_invalid", "thresholds_approved")
    strata = payload.get("expected_strata")
    if not isinstance(strata, Mapping) or not strata:
        _refuse("case_plan_invalid", "expected_strata")
    if any(isinstance(v, bool) or type(v) is not int or v < 0 for v in strata.values()):
        _refuse("case_plan_invalid", "expected_strata")
    if sum(int(v) for v in strata.values()) != len(cases):
        _refuse("case_plan_invalid", "expected_strata_total")
    rows = payload.get("cases")
    if not isinstance(rows, list) or len(rows) != len(cases):
        _refuse("case_plan_coverage_invalid")
    turn_indices: list[int] = []
    for case, row in zip(cases, rows):
        if not isinstance(row, Mapping) or set(row) != {"case_id", "quality_status", "turns"}:
            _refuse("case_plan_invalid", "case_row")
        if str(row.get("case_id")) != str(case.case_id):
            _refuse("case_plan_coverage_invalid")
        quality = _quality_status(row.get("quality_status"))
        if quality != str(row.get("quality_status")):
            _refuse("case_plan_invalid", "quality_status")
        turns = row.get("turns")
        expected_turns = len(case_questions(case))
        if not isinstance(turns, list) or len(turns) != expected_turns:
            _refuse("case_plan_coverage_invalid")
        indices = []
        for turn_row in turns:
            if not isinstance(turn_row, Mapping) or set(turn_row) != {
                "turn_index",
                "status",
                "evidence_file",
                "error",
            }:
                _refuse("case_plan_invalid", "turn_row")
            index = _int(turn_row.get("turn_index"), "case_plan_invalid", maximum=1_000_000)
            indices.append(index)
            status = str(turn_row.get("status"))
            if status not in {"executed", "error", "not_started"}:
                _refuse("case_plan_invalid", "turn_status")
            evidence_file = turn_row.get("evidence_file")
            error = turn_row.get("error")
            if status == "executed":
                name = _str(evidence_file, "case_plan_invalid", maximum=200)
                if "/" in name or "\\" in name or name in {".", ".."}:
                    _refuse("case_plan_invalid", "evidence_file")
            elif evidence_file is not None:
                _refuse("case_plan_invalid", "evidence_file")
            if error is not None and (not isinstance(error, str) or not 0 < len(error) <= 120):
                _refuse("case_plan_invalid", "error")
        if indices != sorted(set(indices)):
            _refuse("case_plan_turn_order_invalid")
        if any(str(turn.get("status")) != "executed" for turn in turns) and quality not in {
            "error",
            "not_executed",
        }:
            _refuse("case_plan_quality_inconsistent")
        turn_indices.extend(indices)
    if turn_indices != list(range(len(turn_indices))):
        _refuse("case_plan_turn_order_invalid")
    return {
        "schema_version": LIVE_CASEPLAN_SCHEMA_VERSION,
        "bindings": {key: str(bindings[key]) for key in BINDING_KEYS},
        "run_binding": dict(resolved_run_binding),
        "run_id": str(payload.get("run_id")),
        "real_calls": int(payload["real_calls"]),
        "thresholds_approved": bool(payload["thresholds_approved"]),
        "expected_strata": {str(name): int(value) for name, value in strata.items()},
        "cases": rows,
    }


def _write_case_plan(
    *,
    out_dir: Path,
    dataset: Any,
    run_id: str,
    evidence_bindings: Mapping[str, str],
    run_binding: Mapping[str, str],
    receipts: Sequence[Mapping[str, Any]],
    marks: Sequence[Any] | None,
    real_calls: int,
    thresholds_approved: bool,
    started_turns: int = 0,
    failed_turn_code: str | None = None,
) -> dict[str, Any]:
    ordered = sorted(
        (receipt for receipt in receipts if str(receipt.get("kind")) in {"turn", ""}),
        key=lambda item: int(item.get("turn_index", -1)),
    )
    by_index = {
        int(receipt.get("turn_index", -1)): receipt
        for receipt in ordered
        if int(receipt.get("turn_index", -1)) >= 0
    }
    marks_map = {
        str(getattr(mark, "case_id", "")): _quality_status(getattr(mark, "status", "error"))
        for mark in (marks or ())
    }
    started = max(0, min(int(started_turns), sum(len(case_questions(case)) for case in dataset.cases)))
    failed_code = str(failed_turn_code or "turn_not_completed")[:120]
    rows: list[dict[str, Any]] = []
    cursor = 0
    for case in dataset.cases:
        turns: list[dict[str, Any]] = []
        for _ in range(len(case_questions(case))):
            receipt = by_index.get(cursor)
            if receipt is not None:
                turns.append(
                    {
                        "turn_index": cursor,
                        "status": "executed",
                        "evidence_file": Path(str(receipt.get("path"))).name,
                        "error": None,
                    }
                )
            elif cursor < started:
                # D：回合已开始/已实际发送，但证据写入/采集失败：固定 error 归因，保留可追。
                turns.append(
                    {
                        "turn_index": cursor,
                        "status": "error",
                        "evidence_file": None,
                        "error": failed_code,
                    }
                )
            else:
                turns.append(
                    {
                        "turn_index": cursor,
                        "status": "not_started",
                        "evidence_file": None,
                        "error": None,
                    }
                )
            cursor += 1
        quality = marks_map.get(str(case.case_id), "error")
        if any(turn["status"] != "executed" for turn in turns) and quality not in {
            "error",
            "not_executed",
        }:
            quality = "error"
        rows.append(
            {"case_id": str(case.case_id), "quality_status": quality, "turns": turns}
        )
    document = {
        "schema_version": LIVE_CASEPLAN_SCHEMA_VERSION,
        "fixture_kind": LIVE_FIXTURE_KIND,
        "run_id": str(run_id),
        "bindings": {key: str(value) for key, value in dict(evidence_bindings).items()},
        "run_binding": {key: str(value) for key, value in dict(run_binding).items()},
        "execution_mode": "live",
        "real_calls": int(real_calls),
        "thresholds_approved": bool(thresholds_approved),
        "expected_strata": _expected_strata(dataset),
        "cases": rows,
    }
    static = {key: value for key, value in dict(evidence_bindings).items() if key != "index_revision"}
    _validate_case_plan_document(
        document,
        cases=tuple(dataset.cases),
        static_bindings=static,
        run_binding=run_binding,
    )
    target = Path(out_dir) / "controlled" / "case-plan.json"
    receipt = _write_new_file(target, document)
    return {
        "path": receipt["path"],
        "sha256": receipt["sha256"],
        "cases": len(rows),
        "turns": sum(len(row["turns"]) for row in rows),
    }


# --------------------------------------------------------------------------- #
# 单 run 真实执行（受控装配；首错停；purge 前封存）
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class RunOptions:
    out_dir: Path
    evidence_root: Path
    seal_root: Path
    evidence_key_file: Path
    process_env: Mapping[str, str]
    transports: Mapping[str, Any] | None = None
    now: datetime | None = None
    #: 清理/扫描用的私有明文针（题面/答案）；默认空 = 由本次 dataset 现算。
    plaintext_needles: tuple[str, ...] = ()


def _classify_run_error(exc: BaseException) -> tuple[str, str]:
    from mktkb.evaluation.p2_evidence_capture import EvidenceCaptureError

    if isinstance(exc, EntryError):
        return "refused", exc.code
    if isinstance(exc, p2_live.P2LiveConfigError):
        return "refused", str(exc.code)
    if isinstance(exc, p2a.P2AuthorizationError):
        return "refused", str(exc.reason)
    if isinstance(exc, p2a.P2GateError):
        return "refused", str(exc.reason)
    if isinstance(exc, p2_runner.P2RunError):
        return "blocked", str(exc.code)
    if isinstance(exc, (EvidenceCaptureError, EvidenceIOError)):
        return "blocked", str(exc.code)
    if isinstance(exc, ScenarioError):
        return "refused", "scenario_contract_invalid"
    if isinstance(exc, p2_scoring.P2ScoringError):
        return "refused", str(getattr(exc, "code", "gate_config_invalid"))
    return "failed", "internal_error"


def _requests_payload(result: Any, artifacts: Mapping[str, Any]) -> dict[str, Any]:
    if result is not None:
        return {
            "source": "run_result",
            "planned": int(result.requests_planned),
            "reserved": int(result.requests_reserved),
            "sent": int(result.requests_sent),
            "reserved_cny": float(result.reserved_cny),
            "settled_cny": float(result.settled_cny),
            "by_operation": {str(k): int(v) for k, v in dict(result.by_operation).items()},
            "by_center_cny": {
                str(center): float(dict(result.by_center_cny).get(center, 0.0))
                for center in COST_CENTERS
            },
            "attempts_scope": str(result.attempts_scope),
            "attempts_reserved": int(result.attempts_reserved),
            "attempts_by_operation": {
                str(k): int(v) for k, v in dict(result.attempts_by_operation).items()
            },
            "attempts_by_center_cny": {
                str(k): float(v) for k, v in dict(result.attempts_by_center_cny).items()
            },
        }
    summary = artifacts.get("summary") if isinstance(artifacts.get("summary"), Mapping) else {}
    requests = summary.get("requests") if isinstance(summary.get("requests"), Mapping) else {}
    attempts = summary.get("attempts") if isinstance(summary.get("attempts"), Mapping) else {}
    return {
        "source": "artifact",
        "planned": int(requests.get("planned") or 0),
        "reserved": int(requests.get("reserved") or 0),
        "sent": int(requests.get("real_requests") or 0),
        "reserved_cny": float(requests.get("conservative_held_cny") or 0.0),
        "settled_cny": float(requests.get("billed_cny") or 0.0),
        "by_operation": {},
        "by_center_cny": {str(center): 0.0 for center in COST_CENTERS},
        "attempts_scope": str(attempts.get("scope") or "unavailable"),
        "attempts_reserved": int(attempts.get("reservations") or 0),
        "attempts_by_operation": {
            str(k): int(v) for k, v in dict(attempts.get("by_operation") or {}).items()
        },
        "attempts_by_center_cny": {
            str(k): float(v) for k, v in dict(attempts.get("by_center_cny") or {}).items()
        },
    }


def _real_sends(artifacts: Mapping[str, Any]) -> int | None:
    summary = artifacts.get("summary") if isinstance(artifacts.get("summary"), Mapping) else {}
    network = summary.get("network") if isinstance(summary.get("network"), Mapping) else {}
    if network.get("available") is True:
        return int(network.get("outbound_attempts") or 0)
    return None


def _started_turn_count(adapter: Any, artifacts: Mapping[str, Any], total_turns: int) -> int:
    """D：本 run 真正开始过的回合数（采集会话 + runner 内存/产物双证据，取最大再夹紧）。"""
    count = 0
    summary_fn = getattr(adapter, "evidence_capture_summary", None) if adapter is not None else None
    if callable(summary_fn):
        try:
            capture_summary = summary_fn() or {}
        except Exception:  # noqa: BLE001 - 观测面失败不掩盖已开始的回合
            capture_summary = {}
        if isinstance(capture_summary, Mapping):
            count = max(count, int(capture_summary.get("turn_count") or 0))
    summary = artifacts.get("summary") if isinstance(artifacts.get("summary"), Mapping) else {}
    turns = summary.get("turns") if isinstance(summary.get("turns"), Mapping) else {}
    requests = summary.get("requests") if isinstance(summary.get("requests"), Mapping) else {}
    count = max(count, int(turns.get("executed") or 0), int(requests.get("attempted") or 0))
    return max(0, min(int(count), int(total_turns)))


async def _execute_loaded(
    *,
    binding_doc: Mapping[str, Any],
    run_entry: Mapping[str, Any],
    plan: P2RunPlan,
    dataset: Any,
    ingest_plan: Any,
    contract: Any,
    options: RunOptions,
) -> dict[str, Any]:
    """一个 run 的受控执行：GO/plan/ledger 绑定 -> 真实门 -> run_live_p2 -> 封存 -> 回执。"""
    started_utc = _utc_now()
    started = time.perf_counter()
    out_dir = Path(options.out_dir)
    evidence_root = Path(options.evidence_root)
    seal_root = Path(options.seal_root)
    key_bytes = Path(options.evidence_key_file).read_bytes()
    run_id = str(run_entry["run_id"])
    scenario = str(run_entry["scenario_id"])
    business_date = str(binding_doc["business_date"])
    writer_box: dict[str, Any] = {}
    marks_box: dict[str, Any] = {"marks": None}
    result = None
    build = None
    gate = None
    run_binding: dict[str, str] | None = None
    status = "refused"
    error_code: str | None = None
    stop_code: str | None = None

    def _marks_sink(marks: Any) -> None:
        marks_box["marks"] = tuple(marks)

    def _factory(build_obj: Any) -> Any:
        adapter = build_obj.adapter
        actual_date = str(getattr(adapter, "rag_business_date", None) or "")
        if actual_date != business_date:
            raise EntryError("business_date_actual_mismatch")
        planned_pipeline = str(run_entry["evidence_bindings"]["pipeline_version"])
        if str(product_pipeline_version()) != planned_pipeline:
            raise EntryError("pipeline_changed")
        bindings_map = dict(run_entry["evidence_bindings"])
        writer = EvidenceWriter(
            root_dir=evidence_root,
            key=key_bytes,
            bindings=bindings_map,
            fixture_kind=LIVE_FIXTURE_KIND,
            run_name=run_id,
        )
        config = EvidenceCaptureConfig(
            root_dir=evidence_root,
            bindings=bindings_map,
            fixture_kind=LIVE_FIXTURE_KIND,
            writer=writer,
            run_binding=run_binding,
        )
        writer_box.update(writer=writer, config=config, adapter=adapter)
        return config

    with applied_env(options.process_env):
        try:
            live_env = p2_live.load_live_env(None)
            _verify_env_against_config(live_env, binding_doc["config"])
            gate = p2_live.open_live_gate(plan, run_id=run_id, now=options.now)
            run_binding = _compose_run_binding(
                gate=gate,
                plan=plan,
                run_id=run_id,
                scenario=scenario,
                business_date=business_date,
                code_version=str(binding_doc["code_version"]),
                config_sha=str(binding_doc["config_sha256"]),
            )
            _verify_run_binding_entry(run_binding, run_entry)
            gate_config = p2_scoring.load_p2_gate_config()
            result, build = await p2_live.run_live_p2(
                plan,
                run_id=run_id,
                out_dir=out_dir,
                dataset=dataset,
                ingest_plan=ingest_plan,
                gate=gate,
                transports=options.transports,
                now=options.now,
                gate_config=gate_config,
                purge_traces_on_close=True,
                scenario_contract=contract,
                evidence_capture_factory=_factory,
                private_case_marks_sink=_marks_sink,
                rag_business_date=business_date,
                manifest_business_date=business_date,
            )
            status = str(result.status)
            stop_code = result.stop_code
        except Exception as exc:  # noqa: BLE001 - 首错停：固定分类，不重试
            status, error_code = _classify_run_error(exc)

    adapter = (
        getattr(build, "adapter", None) if build is not None else writer_box.get("adapter")
    )
    artifacts = _read_artifacts(out_dir)
    run_result = artifacts.get("run_result")
    if (
        error_code is None
        and isinstance(run_result, Mapping)
        and str(run_result.get("status")) in {"succeeded", "blocked", "aborted"}
    ):
        status = str(run_result["status"])
        stop_code = run_result.get("stop_code") or stop_code
    writer = writer_box.get("writer")
    expected_bindings = (
        dict(getattr(writer, "bindings", {}) or {}) if writer is not None else dict(run_entry["evidence_bindings"])
    )
    evidence_dir = _evidence_dir(evidence_root, writer, run_id)
    evidence = _collect_evidence(
        evidence_dir,
        key=key_bytes,
        expected_bindings=expected_bindings,
        run_binding=run_binding,
    )
    seal_receipt = getattr(adapter, "seal_receipt", None) if adapter is not None else None
    total_turns = sum(len(case_questions(case)) for case in dataset.cases)
    needles = tuple(options.plaintext_needles) or _plaintext_needles(dataset)
    cleanup = _purge_plaintext_derivatives(out_dir, dataset, extra_needles=needles)
    cleanup["adapter_seal_receipt"] = seal_receipt
    receipts = [dict(row) for row in list(getattr(writer, "written", []) or []) if str(row.get("kind")) == "turn"]
    if not receipts:
        receipts = [dict(row) for row in evidence.get("turns", ())]

    real_sends = _real_sends(artifacts)
    started_turns = _started_turn_count(adapter, artifacts, total_turns)
    turn_failure_code = str(error_code or stop_code or "turn_not_completed")
    index_items = [item for item in plan.items if item.operation == "index_embedding"]
    plan_ingest = {
        "item_id": None if not index_items else str(index_items[0].item_id),
        "batches": None if not index_items else int(index_items[0].requests),
        "source": "frozen_scenario_contract",
        "scenario_ingest_sha256": str(
            dict(run_entry.get("scenario_binding") or {}).get("scenario_ingest_sha256") or ""
        ),
    }
    case_plan: dict[str, Any] | None = None
    case_plan_error: str | None = None
    if run_binding is not None and writer is not None:
        actual_bindings = dict(getattr(writer, "bindings", {}) or {})
        if re.fullmatch(r"[0-9]{1,12}", str(actual_bindings.get("index_revision", ""))) is None:
            case_plan_error = "evidence_binding_pending"
        else:
            try:
                case_plan = _write_case_plan(
                    out_dir=out_dir,
                    dataset=dataset,
                    run_id=run_id,
                    evidence_bindings=actual_bindings,
                    run_binding=run_binding,
                    receipts=receipts,
                    marks=marks_box["marks"],
                    real_calls=int(real_sends or 0),
                    thresholds_approved=bool(dict(binding_doc["config"]).get("thresholds_approved")),
                    started_turns=started_turns,
                    failed_turn_code=turn_failure_code,
                )
            except EntryError as exc:
                case_plan_error = exc.code
    final_scan = _scan_plaintext(out_dir, needles)
    cleanup["final_plaintext_scan"] = final_scan
    if not final_scan["clean"]:
        cleanup["plaintext_clean"] = False
        cleanup["cleanup_errors"] = sorted(
            set(cleanup.get("cleanup_errors") or ()) | {"plaintext_residual"}
        )
    cleanup["retained_paths"] = (
        sorted(path.relative_to(out_dir).as_posix() for path in out_dir.rglob("*") if path.is_file())
        if out_dir.exists()
        else []
    )

    seal: dict[str, Any] = {"sealed": False}
    if cleanup.get("plaintext_clean") is not True:
        seal = {"sealed": False, "error_code": "plaintext_residual"}
    elif out_dir.exists() or evidence_root.exists():
        try:
            seal = seal_trees(
                out_dir=out_dir,
                evidence_root=evidence_root,
                seal_root=seal_root,
                run_id=run_id,
            )
        except EntryError as exc:
            seal = {"sealed": False, "error_code": exc.code}
        except OSError:
            seal = {"sealed": False, "error_code": "seal_failed"}

    ok = bool(
        status == "succeeded"
        and seal.get("sealed") is True
        and cleanup.get("plaintext_clean") is True
        and case_plan is not None
        and case_plan_error is None
        and not evidence.get("errors")
    )
    if error_code is None and not ok:
        cleanup_errors = list(cleanup.get("cleanup_errors") or ())
        error_code = (
            (cleanup_errors[0] if cleanup_errors else None)
            or case_plan_error
            or ("plaintext_residual" if cleanup.get("plaintext_clean") is not True else None)
            or ("seal_failed" if seal.get("sealed") is not True else None)
            or ("run_not_succeeded" if status != "succeeded" else None)
        )
    receipt = {
        "schema_version": RUN_RECEIPT_SCHEMA_VERSION,
        "tool": TOOL_SCHEMA_VERSION,
        "ok": ok,
        "status": status,
        "stop_code": stop_code,
        "error_code": error_code,
        "run_index": int(run_entry["run_index"]),
        "run_id": run_id,
        "scenario_id": scenario,
        "plan_id": str(plan.plan_id),
        "plan_sha256": str(plan.plan_sha256),
        "business_date": business_date,
        "fixture_kind": LIVE_FIXTURE_KIND,
        "execution_mode": "live",
        "chat_model": CHAT_MODEL,
        "model_pinned": True,
        "runtime": {
            "holdout_env": "explicit_cli",
            "project_total_limit_cny": float(PROJECT_TOTAL_LIMIT_CNY),
            "model_pinned": True,
        },
        "plan_ingest": plan_ingest,
        "case_plan_started_turns": int(started_turns),
        "case_plan_failed_turn_code": (
            turn_failure_code
            if (case_plan is not None and status != "succeeded")
            else None
        ),
        "requests": _requests_payload(result, artifacts),
        "evidence": {
            "available": bool(evidence.get("available")),
            "turn_files": int(evidence.get("turn_files") or 0),
            "manifest_present": bool(evidence.get("manifest_present")),
            "manifest_turn_count": evidence.get("manifest_turn_count"),
            "status_counts": dict(evidence.get("status_counts") or {}),
            "readback_ok": bool(evidence.get("readback_ok")),
            "error_count": len(evidence.get("errors") or ()),
            "manifest_sha256": evidence.get("manifest_sha256"),
        },
        "cleanup": cleanup,
        "seal": {key: value for key, value in seal.items() if key != "note"},
        "real_sends": real_sends,
        "bindings": {
            "go_sha256": None if run_binding is None else run_binding["go_sha256"],
            "ledger_sha256": None if run_binding is None else run_binding["ledger_sha256"],
            "attempt_scope_sha256": (
                None if run_binding is None else run_binding["attempt_scope_sha256"]
            ),
            "code_version": str(binding_doc["code_version"]),
            "config_sha256": str(binding_doc["config_sha256"]),
            "binding_sha256": str(binding_doc["binding_sha256"]),
        },
        "run_binding": None if run_binding is None else dict(run_binding),
        "case_plan": case_plan,
        "case_plan_error": case_plan_error,
        "evidence_key_sha256": hashlib.sha256(key_bytes).hexdigest(),
        "paths": {
            "out_dir": str(out_dir),
            "evidence_root": str(evidence_root),
            "seal_root": str(seal_root),
            "evidence_dir": None if evidence_dir is None else str(evidence_dir),
        },
        "started_utc": started_utc,
        "finished_utc": _utc_now(),
        "duration_ms": int((time.perf_counter() - started) * 1000),
    }
    receipt_path = None
    if seal.get("sealed") is True:
        try:
            receipt_path = _write_new_file(
                Path(str(seal["seal_dir"])) / "run-receipt.json", receipt
            )["path"]
        except EntryError:
            receipt_path = None
    receipt["receipt_path"] = receipt_path
    return receipt


def run_command(
    *,
    env_file: Path | str,
    binding_path: Path | str,
    run_index: int,
    paths: PathOptions,
    runtime: RuntimeOptions | None = None,
    go_path: Path | str | None = None,
    budget_path: Path | str | None = None,
    ledger_path: Path | str | None = None,
    transports: Mapping[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    checked_runtime = check_runtime_options(runtime)
    values = merge_runtime_env(read_authorized_env(env_file), checked_runtime)
    document = load_run_binding(binding_path)
    run_entry = _select_run(document, run_index)
    _verify_input_digests(document)
    if str(document["code_version"]) != code_digest():
        _refuse("code_changed_since_plan")
    _validate_fixed_paths(go_path, budget_path, ledger_path)
    checked = check_target_paths(paths)
    plan = _load_plan_for_run(document, run_entry)
    _verify_plan_binding(document, run_entry, plan)

    business_date = str(document["business_date"])
    bundle = load_private_bundle(
        values, _paths_from_document(document), runtime=checked_runtime
    )
    _validate_dataset_shape(bundle.dataset, business_date)
    merged = _prepare_annotation(
        bundle,
        Path(document["inputs"]["annotation_schema"]["path"]),
        Path(document["inputs"]["scenario_contract"]["path"]),
    )
    _verify_axis_counts(merged, bundle.addendum_acceptance)
    scenario = str(run_entry["scenario_id"])
    subset = bundle.contract.subset(scenario)
    ingest_plan = bundle.contract.ingest_plan(scenario)
    scenario_binding = bundle.contract.binding(scenario)
    if dict(scenario_binding) != dict(run_entry["scenario_binding"]):
        _refuse("scenario_binding_changed")
    if len(subset.cases) != int(run_entry["case_count"]):
        _refuse("scenario_subset_changed", "cases")
    subset_turns = sum(len(case_questions(case)) for case in subset.cases)
    if subset_turns != int(run_entry["turn_count"]):
        _refuse("scenario_subset_changed", "turns")
    if len(ingest_plan.sources) != int(run_entry["ingest_sources"]):
        _refuse("scenario_ingest_changed")
    for case in subset.cases:
        if str(case.business_date or "") != business_date:
            _refuse("business_date_case_mismatch")
    expected = _evidence_bindings(
        dataset=bundle.dataset,
        scenario=scenario,
        run_id=str(run_entry["run_id"]),
        plan=plan,
        config_sha=str(document["config_sha256"]),
        code_version=str(document["code_version"]),
        scenario_binding=scenario_binding,
    )
    actual = dict(run_entry["evidence_bindings"])
    for key, value in expected.items():
        if str(actual.get(key)) != str(value):
            _refuse("evidence_binding_mismatch", key)
    options = RunOptions(
        out_dir=checked.out_dir,
        evidence_root=checked.evidence_root,
        seal_root=checked.seal_root,
        evidence_key_file=checked.evidence_key_file,
        process_env=values,
        transports=transports,
        now=now,
        plaintext_needles=_plaintext_needles(
            bundle.dataset, getattr(bundle.dataset, "labels", None)
        ),
    )
    return asyncio.run(
        _execute_loaded(
            binding_doc=document,
            run_entry=run_entry,
            plan=plan,
            dataset=subset,
            ingest_plan=ingest_plan,
            contract=bundle.contract,
            options=options,
        )
    )


# --------------------------------------------------------------------------- #
# 独立重算（供 08：零模型/检索；只读密文 + 冻结输入，明文不落盘）
# --------------------------------------------------------------------------- #


def _audit_ledger(
    ledger_path: Path | str, run_id: str, receipt: Mapping[str, Any] | None
) -> dict[str, Any]:
    path = Path(ledger_path).expanduser().resolve(strict=False)
    if path != Path(p2a.P2_LEDGER_PATH).resolve(strict=False):
        _refuse("ledger_path_not_fixed")
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        _refuse("ledger_unreadable")
    rows: list[Mapping[str, Any]] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except ValueError:
            _refuse("ledger_invalid")
        if not isinstance(event, Mapping):
            _refuse("ledger_invalid")
        if str(event.get("run_id") or "") == str(run_id):
            rows.append(event)
    reservations = [row for row in rows if row.get("event") == "reserved"]
    results = [row for row in rows if row.get("event") == "result"]
    res_ids = [str(row.get("reservation_id")) for row in reservations]
    result_ids = [str(row.get("reservation_id")) for row in results]
    status_counts = {}
    for row in results:
        status = str(row.get("status") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
    audit = {
        "available": True,
        "run_rows": len(rows),
        "reservations": len(res_ids),
        "results": len(result_ids),
        "duplicate_reservations": len(res_ids) - len(set(res_ids)),
        "duplicate_results": len(result_ids) - len(set(result_ids)),
        "unpaired_reservations": sorted(set(res_ids) - set(result_ids)),
        "orphan_results": sorted(set(result_ids) - set(res_ids)),
        "paired_one_to_one": (
            len(res_ids) == len(set(res_ids))
            and sorted(set(res_ids)) == sorted(set(result_ids))
        ),
        "reserved_cny": round(sum(float(row.get("reserve_cny") or 0.0) for row in reservations), 8),
        "settled_cny": round(
            sum(float(row.get("conservative_charge_cny") or 0.0) for row in results), 8
        ),
        "result_status_counts": status_counts,
        "ledger_sha256": sha256_file(path),
        "prefix_binding_ok": None,
        "receipt_attempts_match": None,
    }
    if receipt is not None:
        bindings = receipt.get("bindings") if isinstance(receipt.get("bindings"), Mapping) else {}
        audit["prefix_binding_ok"] = ledger_binding_ok(
            str(bindings.get("ledger_sha256") or ""), path
        )
        requests = receipt.get("requests") if isinstance(receipt.get("requests"), Mapping) else {}
        audit["receipt_attempts_match"] = (
            str(requests.get("attempts_scope")) == "all_attempts"
            and int(requests.get("attempts_reserved") or 0) == len(res_ids)
            and int(requests.get("reserved") or 0) <= len(res_ids)
        )
    return audit


def scenario_forbidden_source_identity(
    *,
    source_map_path: Path | str,
    ingest_plan: Any,
    expected_source_map_sha256: str | None = None,
) -> tuple[Any, dict[str, Any]]:
    """从冻结 source map + 场景实际入库映射构造评分侧可信来源身份（只读、可追溯）。

    两段输入都必须是**本轮 run 计划钉住的**同一份：

    - source map：按 ``schema_version`` 分发（``/v0.1`` 逐值委托驱动层，``/v0.2`` 自行
      严格校验），文件摘要与 ``expected_source_map_sha256`` 不等即拒绝——不允许"评分时
      换一张更宽松的 map"；
    - 文档名映射：``p2_runner.holdout_document_codes`` 从本场景 ingest plan 的语料文件名
      派生（同一名字映到两个码即 ``holdout_document_code_ambiguous``，不静默择一）。

    返回 ``(identity, summary)``；summary 只含 schema/摘要/计数 + 只读路径。

    **只降级、不放宽**：source map 文件摘要与计划绑定一致但内容无法按版本分发（未知
    schema）或 ingest 映射自相矛盾时，不抛异常、也不猜——返回空身份并把固定原因码写进
    summary（``status="unresolved"``）；文档级禁源因此在评分层一律 ``unknown``（fail
    closed，正式总门仍阻断），不会退化成跨版本/相似名的命中。
    """
    path = Path(source_map_path)
    if not path.is_file():
        _refuse("source_map_missing")
    file_sha = sha256_file(path)
    if expected_source_map_sha256 is not None and file_sha != str(expected_source_map_sha256):
        _refuse("source_map_binding_mismatch", "sha256")
    identity: Any = hard.UNRESOLVED_SOURCE_IDENTITY
    error_code: str | None = None
    schema_version: str | None = None
    try:
        schema_version = holdout_source_map.source_map_schema_version(path)
        mapping = holdout_source_map.load_source_map(path)
        codes = p2_runner.holdout_document_codes(ingest_plan)
        identity = hard.build_forbidden_source_identity(mapping, codes)
    except hard.HardEvidenceError as exc:
        identity = hard.UNRESOLVED_SOURCE_IDENTITY
        error_code = "source_identity_invalid"
    except Exception as exc:  # noqa: BLE001 - 固定码降级，detail 只放码/类型名
        identity = hard.UNRESOLVED_SOURCE_IDENTITY
        error_code = str(getattr(exc, "code", None) or "source_identity_invalid")
    if error_code is None:
        summary = hard.forbidden_source_identity_summary(identity)
        summary["schema_version"] = SCORER_IDENTITY_SCHEMA_VERSION
        summary["identity_schema_version"] = hard.SOURCE_IDENTITY_SCHEMA_VERSION
        summary["status"] = "derived"
        summary["error_code"] = None
    else:
        summary = {
            "schema_version": SCORER_IDENTITY_SCHEMA_VERSION,
            "identity_schema_version": None,
            "status": "unresolved",
            "error_code": error_code,
            "doc_code_count": 0,
            "document_name_count": 0,
            "mapped_doc_code_count": 0,
            "source_map_sha256": None,
            "document_codes_sha256": None,
            "identity_sha256": None,
        }
    summary.update(
        {
            "source_map_schema_version": None if schema_version is None else str(schema_version),
            "source_map_file_sha256": file_sha,
            "source_map_path": str(path),
            "basis": "frozen_source_map+scenario_ingest_plan",
        }
    )
    return identity, summary


def _scorer_identity_binding(
    *,
    document: Mapping[str, Any],
    run_entry: Mapping[str, Any],
    plan: P2RunPlan,
    scenario: str,
    ingest_plan: Any,
) -> dict[str, Any]:
    """把"原运行身份"与"派生评分器身份"绑成一套，供 ``_recompute_loaded`` 一次传入。

    原身份全部来自**本轮 run 计划**（binding 文件 + plan + run entry + scenario binding），
    派生身份只从同一份 source map 文件与本场景 ingest plan 派生。两边 source map 摘要
    必须逐值相等，否则固定码拒绝（不允许评分时换 map）。
    """
    scenario_binding = run_entry.get("scenario_binding")
    if not isinstance(scenario_binding, Mapping):
        _refuse("run_binding_invalid", "scenario_binding")
    binding_source_map_sha = str(scenario_binding.get("source_map_sha256") or "")
    inputs = document.get("inputs") if isinstance(document.get("inputs"), Mapping) else {}
    input_source_map = inputs.get("source_map") if isinstance(inputs.get("source_map"), Mapping) else {}
    input_source_map_sha = str(input_source_map.get("sha256") or "")
    if (
        len(binding_source_map_sha) != 64
        or input_source_map_sha != binding_source_map_sha
        or not input_source_map.get("path")
    ):
        _refuse("source_map_binding_mismatch", "plan")
    identity, summary = scenario_forbidden_source_identity(
        source_map_path=Path(str(input_source_map["path"])),
        ingest_plan=ingest_plan,
        expected_source_map_sha256=binding_source_map_sha,
    )
    original = {
        "code_version": str(document["code_version"]),
        "config_sha256": str(document["config_sha256"]),
        "business_date": str(document["business_date"]),
        "run_id": str(run_entry["run_id"]),
        "plan_id": str(plan.plan_id),
        "plan_sha256": str(plan.plan_sha256),
        "plan_file_sha256": str(run_entry["plan_file_sha256"]),
        "scenario_id": scenario,
        "source_map_sha256": binding_source_map_sha,
        "scenario_ingest_sha256": str(scenario_binding.get("scenario_ingest_sha256") or ""),
    }
    return {
        "source_identity": identity,
        "source_identity_summary": summary,
        "original_identity": original,
    }


def _recompute_loaded(
    *,
    document: Mapping[str, Any],
    run_entry: Mapping[str, Any],
    plan: P2RunPlan,
    cases: Sequence[Any],
    annotation: Any,
    case_plan_payload: Mapping[str, Any],
    evidence_dir: Path | str,
    key: bytes,
    ledger_path: Path | str | None = None,
    receipt: Mapping[str, Any] | None = None,
    out_card: Path | str | None = None,
    source_identity: Any | None = None,
    source_identity_summary: Mapping[str, Any] | None = None,
    original_identity: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """确定性四轴重算核心：只读密文/冻结输入，零模型/检索，明文不落盘（供 08）。"""
    root = assert_private_path(evidence_dir)
    if not root.is_dir():
        _refuse("evidence_dir_missing")
    scenario = str(run_entry["scenario_id"])
    static_bindings = {
        key_name: value
        for key_name, value in dict(run_entry["evidence_bindings"]).items()
        if key_name != "index_revision"
    }
    case_plan = _validate_case_plan_document(
        case_plan_payload, cases=tuple(cases), static_bindings=static_bindings
    )
    if str(case_plan["run_id"]) != str(run_entry["run_id"]):
        _refuse("case_plan_binding_mismatch", "run_id")
    control = dict(case_plan["run_binding"])
    if (
        str(control.get("plan_sha256")) != str(plan.plan_sha256)
        or str(control.get("business_date")) != str(document["business_date"])
        or str(control.get("scenario_id")) != scenario
    ):
        _refuse("case_plan_binding_mismatch", "run_binding")
    if receipt is not None and dict(receipt.get("run_binding") or {}) != control:
        _refuse("run_receipt_binding_mismatch", "run_binding")

    audits: list[dict[str, Any]] = []
    status_counts: dict[str, int] = {}
    seen_files: set[str] = set()
    executed = 0
    for case, row in zip(cases, case_plan["cases"]):
        entries: list[dict[str, Any]] = []
        for turn_row in row["turns"]:
            track = {
                "turn_index": int(turn_row["turn_index"]),
                "status": str(turn_row["status"]),
                "error": turn_row.get("error"),
                "evidence": None,
            }
            if track["status"] == "executed":
                name = str(turn_row["evidence_file"])
                if name in seen_files:
                    _refuse("case_plan_evidence_file_duplicate")
                seen_files.add(name)
                target = (root / name).resolve()
                if not _is_within(target, root.resolve()):
                    _refuse("case_plan_evidence_file_invalid")
                if not target.is_file():
                    _refuse("case_plan_evidence_file_missing")
                try:
                    envelope = read_encrypted_evidence(
                        target, key=key, expected_bindings=dict(case_plan["bindings"])
                    )
                except EvidenceIOError as exc:
                    _refuse("evidence_invalid", str(exc.code))
                if dict(envelope.get("run_binding") or {}) != control:
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
    manifest_turn_count = None
    manifest_files = sorted(root.glob("manifest-*.fernet"))
    if manifest_files:
        try:
            manifest = read_encrypted_evidence(
                manifest_files[0], key=key, expected_bindings=dict(case_plan["bindings"])
            )
        except EvidenceIOError as exc:
            _refuse("evidence_invalid", "manifest:" + str(exc.code))
        if dict(manifest.get("run_binding") or {}) != control:
            _refuse("evidence_run_binding_mismatch", "manifest")
        summary = manifest.get("summary") if isinstance(manifest.get("summary"), Mapping) else {}
        manifest_turn_count = int(summary.get("turn_count", -1))
        if manifest_turn_count != executed:
            _refuse("evidence_manifest_turn_count_mismatch")
        if dict(summary.get("status_counts") or {}) != status_counts:
            _refuse("evidence_manifest_status_mismatch")

    plan_meta = {
        "thresholds_approved": bool(case_plan["thresholds_approved"]),
        "execution_mode": "live",
        "real_calls": int(case_plan["real_calls"]),
        "run_id": str(run_entry["run_id"]),
        "config_hash": str(document["config_sha256"]),
        "expected_strata": dict(case_plan["expected_strata"]),
    }
    card, _results = hard.recompute_hard_evidence(
        tuple(cases),
        annotation,
        audits,
        plan_meta=plan_meta,
        source_identity=source_identity,
    )
    summary = hard.public_recompute_summary(card)
    card_file = None
    if out_card is not None:
        target = require_outside_repo(out_card, "out_card")
        if target.exists():
            _refuse("output_already_exists", "out_card")
        receipt_card = _write_new_file(target, card)
        readback = _read_json_mapping(target, "card_readback_invalid")
        hard.validate_hard_evidence_scorecard(
            readback,
            total=len(cases),
            run_id=plan_meta["run_id"],
            config_hash=plan_meta["config_hash"],
            expected_strata=plan_meta["expected_strata"],
        )
        card_file = dict(receipt_card)
    funding = _audit_ledger(
        ledger_path if ledger_path is not None else p2a.P2_LEDGER_PATH,
        str(run_entry["run_id"]),
        receipt,
    )
    return {
        "ok": True,
        "schema_version": "p2-h2-controlled-recompute/v0.1",
        "tool": TOOL_SCHEMA_VERSION,
        "zero_model_calls": True,
        "execution_mode": "live",
        "run_id": str(run_entry["run_id"]),
        "scenario_id": scenario,
        "plan_sha256": str(plan.plan_sha256),
        "business_date": str(document["business_date"]),
        "card": summary,
        "card_file": card_file,
        # 身份分列：原运行代码/计划身份（只读回执）+ 派生评分器身份（本轮真正喂给
        # classify/recompute 的那一份）。两者都只含摘要/计数/固定路径，不含题面或文档名。
        "identity": {
            "original": None if original_identity is None else dict(original_identity),
            "derived_scorer": None if source_identity_summary is None else dict(source_identity_summary),
        },
        "coverage": {
            "cases": len(cases),
            "turns": sum(len(case_questions(case)) for case in cases),
            "executed_turns": executed,
            "evidence_files": len(seen_files),
            "manifest_present": bool(manifest_files),
            "manifest_turn_count": manifest_turn_count,
            "status_counts": dict(status_counts),
            "bindings_match": True,
            "run_binding_match": True,
        },
        "binding": {
            "binding_sha256": str(document["binding_sha256"]),
            "config_sha256": str(document["config_sha256"]),
            "code_version": str(document["code_version"]),
            "run_binding": control,
            "evidence_bindings": dict(case_plan["bindings"]),
        },
        "funding": funding,
    }


def recompute(
    *,
    env_file: Path | str,
    binding_path: Path | str,
    run_index: int,
    evidence_dir: Path | str,
    evidence_key_file: Path | str,
    case_plan_path: Path | str,
    runtime: RuntimeOptions | None = None,
    ledger_path: Path | str | None = None,
    receipt_path: Path | str | None = None,
    out_card: Path | str | None = None,
) -> dict[str, Any]:
    checked_runtime = check_runtime_options(runtime)
    values = merge_runtime_env(read_authorized_env(env_file), checked_runtime)
    document = load_run_binding(binding_path)
    run_entry = _select_run(document, run_index)
    _verify_input_digests(document)
    if str(document["code_version"]) != code_digest():
        _refuse("code_changed_since_plan")
    plan = _load_plan_for_run(document, run_entry)
    _verify_plan_binding(document, run_entry, plan)
    business_date = str(document["business_date"])
    bundle = load_private_bundle(
        values, _paths_from_document(document), runtime=checked_runtime
    )
    _validate_dataset_shape(bundle.dataset, business_date)
    merged = _prepare_annotation(
        bundle,
        Path(document["inputs"]["annotation_schema"]["path"]),
        Path(document["inputs"]["scenario_contract"]["path"]),
    )
    _verify_axis_counts(merged, bundle.addendum_acceptance)
    scenario = str(run_entry["scenario_id"])
    scenario_binding = bundle.contract.binding(scenario)
    if dict(scenario_binding) != dict(run_entry["scenario_binding"]):
        _refuse("scenario_binding_changed")
    subset = bundle.contract.subset(scenario)
    if len(subset.cases) != int(run_entry["case_count"]):
        _refuse("scenario_subset_changed", "cases")
    for case in subset.cases:
        if str(case.business_date or "") != business_date:
            _refuse("business_date_case_mismatch")
    key = Path(evidence_key_file).read_bytes()
    if len(key) != 44:
        _refuse("evidence_key_invalid")
    try:
        from cryptography.fernet import Fernet

        Fernet(key)
    except Exception:  # noqa: BLE001
        _refuse("evidence_key_invalid")
    evidence_root = assert_private_path(evidence_dir)
    if not evidence_root.is_dir():
        _refuse("evidence_dir_missing")
    receipt = None
    if receipt_path is not None:
        receipt = _read_json_mapping(assert_private_path(receipt_path), "run_receipt_unreadable")
        if receipt.get("schema_version") != RUN_RECEIPT_SCHEMA_VERSION:
            _refuse("run_receipt_invalid")
        if (
            str(receipt.get("run_id")) != str(run_entry["run_id"])
            or str(receipt.get("scenario_id")) != scenario
            or str(receipt.get("plan_sha256")) != str(plan.plan_sha256)
        ):
            _refuse("run_receipt_binding_mismatch")
        if str(receipt.get("evidence_key_sha256")) != hashlib.sha256(key).hexdigest():
            _refuse("evidence_key_mismatch")
    payload = _read_json_mapping(assert_private_path(case_plan_path), "case_plan_unreadable")
    return _recompute_loaded(
        document=document,
        run_entry=run_entry,
        plan=plan,
        cases=subset.cases,
        annotation=merged,
        case_plan_payload=payload,
        evidence_dir=evidence_dir,
        key=key,
        ledger_path=ledger_path,
        receipt=receipt,
        out_card=out_card,
        **_scorer_identity_binding(
            document=document,
            run_entry=run_entry,
            plan=plan,
            scenario=scenario,
            ingest_plan=bundle.contract.ingest_plan(scenario),
        ),
    )


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:  # type: ignore[override]
        raise EntryError("usage_invalid", str(message)[:160], exit_code=EXIT_USAGE)


def _add_run_selector(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--env-file", required=True, help="主人指定的项目 .env（唯一凭据源）")
    parser.add_argument("--run-binding", required=True, help="plan-private 产出的仓外 run binding")
    parser.add_argument("--run-index", required=True, type=int, help="0..3，固定场景顺序")


def _add_target_paths(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--out-dir", required=True, help="本 run 隔离产品根（仓外、必须不存在）")
    parser.add_argument("--evidence-root", required=True, help="本 run 密文根（仓外、不存在/空）")
    parser.add_argument("--seal-root", required=True, help="封存根（仓外、不存在/空）")
    parser.add_argument("--evidence-key-file", required=True, help="Fernet key 文件（仓外、不回显）")


def _add_gate_paths(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--go-path", default=None, help="必须是固定 P2 GO 路径")
    parser.add_argument("--budget-path", default=None, help="必须是固定共享预算路径")
    parser.add_argument("--ledger-path", default=None, help="必须是固定共享账本路径")


def _add_runtime_args(parser: argparse.ArgumentParser) -> None:
    """A：holdout 根/钥与项目总上限只能显式给出，绝不从 .env 读。"""
    parser.add_argument("--holdout-root", required=True, help="holdout 封存根（仓外，显式）")
    parser.add_argument("--holdout-key-file", required=True, help="holdout key 文件（仓外，显式）")
    parser.add_argument(
        "--project-total-limit-cny", required=True, type=float, help="项目总上限，必须=40"
    )


def _runtime_from_args(args: argparse.Namespace) -> RuntimeOptions:
    return RuntimeOptions(
        holdout_root=Path(args.holdout_root),
        holdout_key_file=Path(args.holdout_key_file),
        project_total_limit_cny=float(args.project_total_limit_cny),
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = _Parser(
        prog="p2_h2_controlled_execute",
        description="T207 05：H2 live 受控入口（plan-private/preflight/run/recompute）",
    )
    sub = parser.add_subparsers(dest="command", required=True, parser_class=_Parser)

    plan = sub.add_parser("plan-private", help="受控生成四 run 精确计划 + run binding（仓外）")
    # plan-private 不发送、不读凭据：--env-file 对它是可选的（A）。
    plan.add_argument("--env-file", default=None)
    plan.add_argument("--out-dir", required=True)
    plan.add_argument("--created-utc", required=True)
    plan.add_argument("--holdout-manifest", default=str(DEFAULT_HOLDOUT_MANIFEST))
    plan.add_argument("--annotation", required=True)
    plan.add_argument("--review", required=True)
    plan.add_argument("--scenario-key-file", required=True)
    plan.add_argument("--addendum", required=True)
    plan.add_argument("--scenario-contract", default=str(DEFAULT_SCENARIO_CONTRACT))
    plan.add_argument("--ingest-plan", default=str(DEFAULT_INGEST_PLAN))
    plan.add_argument("--source-map", default=str(DEFAULT_SOURCE_MAP))
    plan.add_argument("--annotation-schema", default=str(DEFAULT_ANNOTATION_SCHEMA))
    plan.add_argument("--manager-acceptance", default=str(DEFAULT_MANAGER_V2))
    plan.add_argument("--review-aggregate", default=str(DEFAULT_REVIEW_AGGREGATE_V2))
    plan.add_argument("--addendum-acceptance", default=str(DEFAULT_ADDENDUM_ACCEPTANCE))
    plan.add_argument("--plan-id-prefix", default="P2-T207-H2-20261111")
    plan.add_argument("--run-id-prefix", default="p2-h2")
    plan.add_argument("--plan-version", default="v0.1")
    plan.add_argument("--max-requests", type=int, default=int(H2_MAX_REQUESTS))
    plan.add_argument("--business-date", default=None)
    _add_runtime_args(plan)

    pre = sub.add_parser("preflight", help="check-only：零付费/零模型，只读 GO/预算/账本")
    _add_run_selector(pre)
    _add_target_paths(pre)
    _add_gate_paths(pre)
    _add_runtime_args(pre)

    run = sub.add_parser("run", help="单 run 真实串行执行（一次只跑一个 scenario）")
    _add_run_selector(run)
    _add_target_paths(run)
    _add_gate_paths(run)
    _add_runtime_args(run)

    recompute = sub.add_parser("recompute", help="独立重算四轴（零模型/检索，供 08）")
    _add_run_selector(recompute)
    _add_runtime_args(recompute)
    recompute.add_argument("--evidence-dir", required=True)
    recompute.add_argument("--evidence-key-file", required=True)
    recompute.add_argument("--case-plan", required=True)
    recompute.add_argument("--run-receipt", default=None)
    recompute.add_argument("--ledger-path", default=None)
    recompute.add_argument("--out-card", default=None)
    return parser


def _paths_from_args(args: argparse.Namespace) -> PathOptions:
    return PathOptions(
        out_dir=Path(args.out_dir),
        evidence_root=Path(args.evidence_root),
        seal_root=Path(args.seal_root),
        evidence_key_file=Path(args.evidence_key_file),
    )


def _dispatch(args: argparse.Namespace) -> int:
    if args.command == "plan-private":
        values = read_authorized_env(args.env_file) if args.env_file else {}
        runtime = _runtime_from_args(args)
        paths = InputPaths(
            holdout_manifest=Path(args.holdout_manifest),
            annotation_ciphertext=Path(args.annotation),
            review_ciphertext=Path(args.review),
            scenario_key_file=Path(args.scenario_key_file),
            addendum_ciphertext=Path(args.addendum),
            scenario_contract=Path(args.scenario_contract),
            ingest_plan=Path(args.ingest_plan),
            source_map=Path(args.source_map),
            annotation_schema=Path(args.annotation_schema),
            manager_acceptance_v2=Path(args.manager_acceptance),
            review_aggregate_v2=Path(args.review_aggregate),
            addendum_acceptance_v3=Path(args.addendum_acceptance),
        )
        bundle = load_private_bundle(values, paths, runtime=runtime)
        payload = plan_private(
            bundle,
            PlanOptions(
                out_dir=Path(args.out_dir),
                created_utc=str(args.created_utc),
                plan_id_prefix=str(args.plan_id_prefix),
                run_id_prefix=str(args.run_id_prefix),
                plan_version=str(args.plan_version),
                max_requests=int(args.max_requests),
                business_date=args.business_date,
                schema_path=Path(args.annotation_schema),
                scenario_path=Path(args.scenario_contract),
            ),
        )
        _emit(payload)
        return EXIT_OK
    if args.command == "preflight":
        payload = preflight(
            env_file=args.env_file,
            binding_path=args.run_binding,
            run_index=int(args.run_index),
            paths=_paths_from_args(args),
            runtime=_runtime_from_args(args),
            go_path=args.go_path,
            budget_path=args.budget_path,
            ledger_path=args.ledger_path,
        )
        _emit(payload)
        return EXIT_OK if payload.get("ok") else EXIT_REFUSED
    if args.command == "run":
        payload = run_command(
            env_file=args.env_file,
            binding_path=args.run_binding,
            run_index=int(args.run_index),
            paths=_paths_from_args(args),
            runtime=_runtime_from_args(args),
            go_path=args.go_path,
            budget_path=args.budget_path,
            ledger_path=args.ledger_path,
        )
        _emit(payload)
        return EXIT_OK if payload.get("ok") else EXIT_REFUSED
    if args.command == "recompute":
        payload = recompute(
            env_file=args.env_file,
            binding_path=args.run_binding,
            run_index=int(args.run_index),
            evidence_dir=args.evidence_dir,
            evidence_key_file=args.evidence_key_file,
            case_plan_path=args.case_plan,
            runtime=_runtime_from_args(args),
            ledger_path=args.ledger_path,
            receipt_path=args.run_receipt,
            out_card=args.out_card,
        )
        _emit(payload)
        return EXIT_OK
    _usage("command_invalid")


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = _build_parser().parse_args(list(argv) if argv is not None else None)
        return _dispatch(args)
    except EntryError as exc:
        _emit(
            {
                "ok": False,
                "schema_version": TOOL_SCHEMA_VERSION,
                "error_code": exc.code,
                "detail": _public_detail(exc.detail),
                "secrets_printed": False,
                "real_sends": 0,
            }
        )
        return exc.exit_code
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001 - 未预期异常只报固定码，绝不回显异常链
        _emit(
            {
                "ok": False,
                "schema_version": TOOL_SCHEMA_VERSION,
                "error_code": "internal_error",
                "detail": "",
                "secrets_printed": False,
                "real_sends": 0,
            }
        )
        return EXIT_INTERNAL


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

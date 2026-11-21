"""H2 v3 受控 live 入口（新增文件；v2 入口 ``tools/p2_h2_controlled_execute.py`` 一字未改）。

本工具只做三件事，全部围绕“真实发送前”的受控边界：

1. ``plan-private``：用 v3 loader 生成四 run 的私有计划 + 每 run 一份 binding 文档
   （计划含 case_id，只能写仓外；仓内不落明文计划）；
2. ``check-only``：零发送预检。重算计划（``build_holdout_plan``，与
   ``ValidatedScenarioContract.build_plan`` 同一调用）→ 复算 ``scenario_plan_mismatch``；
   可选 ``--reload-contract`` 用 v3 loader 在内存复核完整契约；再走
   ``preflight_p2`` / ``authorize_p2``（固定 GO/预算/账本）给出 ``production_ready``；
3. ``run``：单 run 真实执行（``--run-index i``，串行、首错停、不重试）。复用 v2 的
   ``_execute_loaded`` 骨架（GO/plan/ledger 绑定 → 真实门 → ``run_live_p2`` → 封存 → 回执），
   外层只在 v3 差异处包一层 ``dispatched_scoring_map``。

与 v2 入口的差异（仅这五处）：
- **loader**：``p2_holdout_scenarios_v3.load_v3_scenario_contract``（v3 语料根/保管件）；
- **source-map 分发**：``p2_holdout_v3_scoring.dispatched_scoring_map``（/v0.2）；
- **per-run business_date**：每 run 自己的 L1 日期（``p2_holdout_run_date``），
  ``rag_business_date == manifest_business_date == run_date``；binding 文档一 run 一份；
- **预算 50**：进程内在导入前显式设置 ``MKTKB_PROJECT_TOTAL_LIMIT_CNY=50``，
  使 ``p2_holdout_plan.H2_PROJECT_TOTAL_LIMIT_CNY`` 与 ``budget.json`` 的 ``limit_cny`` 逐值一致。
  调用方若显式设了别的值，本入口拒绝（不静默改写主人给的上限）；
- **执行层 delta 透传**：check 层已授权的 ``authorized_delta``（index_embedding 批数
  9/10/13/15）显式传给执行核心（``_execution_contract`` → 只放宽这一格的
  ``_V3BatchContract``），否则 ``p2_runner`` 会按冻结 ``RECIPES`` 逐值重建并拒整 run。

安全边界：
- ``check-only`` / ``plan-private`` 安装 socket 守卫并做一次正对照（外部连接在 connect 前被拦），
  结束时外部尝试计数必须为 0；不 reserve、不扣费、不写共享账本；
- ``run`` 在进入执行核心（``_execute_loaded``）**之前**完成 ``plan_dial``（含
  ``max_requests == "unlimited"``）、计划重算与 plan_id 派生校验；任一失败用固定码拒绝，
  不吞异常、不发送；
- ``run`` 与 ``check-only`` 共用 run 级 O_EXCL 租约（PID + 进程启动标记 + 有界 stale）：
  run 占本机登记处 + seal 目录，check-only 占本机登记处（给了 ``--seal-root`` 时再加 seal
  目录）；已被活进程持有时固定码 ``run_claim_held`` 拒绝，且此前零发送；
- 本工具不读取 .env 以外的凭据；``run`` 才读主人指定的 ``<repo>/.env``（v2 同一白名单）；
- stdout/证据只输出固定码、计数、hash、路径；不输出题面/答案/凭据。
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import hashlib
import importlib.util
import json
import os
import re
import socket
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, NoReturn, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_SRC = PROJECT_ROOT / "backend" / "src"
if str(BACKEND_SRC) not in sys.path:
    sys.path.insert(0, str(BACKEND_SRC))

TOTAL_LIMIT_ENV = "MKTKB_PROJECT_TOTAL_LIMIT_CNY"
V3_PROJECT_TOTAL_LIMIT_CNY = 40.0
"""v3 阶段的项目总上限（预算回退后与 budget.json 的 limit_cny 逐值相等）。"""

_ENV_CONFLICT: str | None = None
_raw_limit = os.environ.get(TOTAL_LIMIT_ENV)
if _raw_limit is not None and str(_raw_limit).strip():
    try:
        _given_limit = float(str(_raw_limit).strip())
    except ValueError:
        _ENV_CONFLICT = str(_raw_limit)
    else:
        if abs(_given_limit - V3_PROJECT_TOTAL_LIMIT_CNY) > 1e-9:
            _ENV_CONFLICT = str(_raw_limit)
# 必须在导入 mktkb.evaluation.p2_holdout_plan 之前定值：该常量在导入期读取环境。
os.environ[TOTAL_LIMIT_ENV] = str(V3_PROJECT_TOTAL_LIMIT_CNY)

from cryptography.fernet import Fernet  # noqa: E402

from mktkb.evaluation import p2_authorization as p2a  # noqa: E402
from mktkb.evaluation import p2_holdout_plan as holdout_plan  # noqa: E402
from mktkb.evaluation import p2_holdout_run_date as run_date  # noqa: E402
from mktkb.evaluation import p2_holdout_scenarios_v3 as contract_v3  # noqa: E402
from mktkb.evaluation import p2_holdout_source_map as source_map  # noqa: E402
from mktkb.evaluation import p2_holdout_v3_scoring as wiring  # noqa: E402
from mktkb.evaluation import p2_hard_evidence as hard  # noqa: E402
from mktkb.evaluation import p2_safe_output as safe_output  # noqa: E402
from mktkb.evaluation.p2_contracts import (  # noqa: E402
    COST_CENTERS,
    P2RunPlan,
    payload_sha256,
)
from mktkb.evaluation.p2_dataset import P2DatasetError, load_p2_dataset  # noqa: E402
from mktkb.evaluation.p2_evidence_capture import (  # noqa: E402
    BINDING_KEYS,
    LIVE_FIXTURE_KIND,
    LIVE_PENDING_INDEX_REVISION,
)
from mktkb.evaluation.p2_holdout_scenarios import (  # noqa: E402
    ScenarioError,
    ValidatedScenarioContract,
)
from mktkb.evaluation.product_adapter import case_questions, product_pipeline_version  # noqa: E402
from mktkb.proc_identity import process_identity  # noqa: E402

# --------------------------------------------------------------------------- #
# v2 受控骨架（按文件路径导入；不改 v2 文件，只复用其受控原语）
# --------------------------------------------------------------------------- #


def _load_controlled_entry() -> Any:
    target = PROJECT_ROOT / "tools" / "p2_h2_controlled_execute.py"
    if not target.is_file():
        raise RuntimeError("p2_h2_controlled_execute.py 缺失：v3 入口必须复用 v2 受控骨架")
    spec = importlib.util.spec_from_file_location("_p2_h2_controlled_execute_v2", target)
    if spec is None or spec.loader is None:
        raise RuntimeError("v2 受控骨架不可导入")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(spec.name, None)
        raise
    # 代码身份必须包含本入口自身：v2 code_digest 的 scope 由这里追加。
    module.CODE_SCOPES = tuple(module.CODE_SCOPES) + (
        "tools/p2_h2_v3_controlled_execute.py",
    )
    return module


v2 = _load_controlled_entry()

if abs(holdout_plan.H2_PROJECT_TOTAL_LIMIT_CNY - V3_PROJECT_TOTAL_LIMIT_CNY) > 1e-9:
    # 说明导入顺序把 p2_holdout_plan 提前固定成了别的值；宁可拒绝也不带着错上限跑。
    raise RuntimeError(
        f"p2_holdout_plan.H2_PROJECT_TOTAL_LIMIT_CNY={holdout_plan.H2_PROJECT_TOTAL_LIMIT_CNY} "
        f"≠ {V3_PROJECT_TOTAL_LIMIT_CNY}"
    )

TOOL_SCHEMA_VERSION = "p2-h2v3-controlled-entry/v0.1"
BINDING_SCHEMA_VERSION = "p2-h2v3-controlled-runbinding/v0.1"
PLAN_SCHEMA_VERSION = "p2-h2v3-controlled-plan-public/v0.1"
CHECK_SCHEMA_VERSION = "p2-h2v3-controlled-check/v0.1"
RUN_RECEIPT_SCHEMA_VERSION = "p2-h2v3-controlled-run-receipt/v0.1"

EXIT_OK = 0
EXIT_INTERNAL = 1
EXIT_REFUSED = 2
EXIT_USAGE = 3

TAG = "P2-H2V3-20261115"
MAX_REQUESTS = "unlimited"
"""v3 新计划显式取消累计次数上限；金额和逐计划项次数仍受约束。"""
STAGE_LIMIT_CNY = 20.0
TURN_TIMEOUT_SECONDS = 60.0
DEFAULT_CREATED_UTC = "2026-11-15T05:00:00+08:00"
GOVERNANCE_REQUEST_CAP = MAX_REQUESTS

V3_SCENARIO_COUNTS: Mapping[str, int] = {
    "base_b0": 12,
    "base_b0_plus_v01": 8,
    "pre_v05_without_v07": 5,
    "post_v05_without_v01": 5,
}
V3_SCENARIO_TURNS: Mapping[str, int] = {
    "base_b0": 14,
    "base_b0_plus_v01": 10,
    "pre_v05_without_v07": 6,
    "post_v05_without_v01": 6,
}
#: v3 的 index_embedding 上界**不再**取 v2 冻结配方常量（RECIPES=8/9/11/13），
#: 改为按 v3 实际内容派生的逐源批数（census）。v2 配方语义未动，见 build_ingest_batch_census.py。
V3_BATCH_CENSUS = (
    PROJECT_ROOT / "docs/reports/OBS-EVAL/P2/H2V3/run/plan-regen/ingest-batch-census.json"
)
V3_BATCH_CENSUS_SCHEMA = "p2-h2v3-ingest-batch-census/v0.1"

V3_INPUT_NAMES: tuple[str, ...] = (
    "holdout_manifest",
    "annotation_ciphertext",
    "review_ciphertext",
    "scenario_key_file",
    "scenario_contract",
    "ingest_plan",
    "source_map",
    "annotation_schema",
    "manager_acceptance",
    "review_aggregate",
    "lifecycle",
    "v3_freeze",
    "pre_registration",
    "mock_dryrun_summary",
)
V3_PRIVATE_INPUT_NAMES = frozenset(
    {"annotation_ciphertext", "review_ciphertext", "scenario_key_file"}
)

V3_BINDING_KEYS = (
    "schema_version",
    "created_utc",
    "fixture_kind",
    "execution_mode",
    "holdout_root",
    "anchor_business_date",
    "business_date",
    "code_version",
    "config_sha256",
    "config",
    "dataset",
    "inputs",
    "runs",
    "binding_sha256",
)
V3_RUN_KEYS = (
    "run_index",
    "scenario_id",
    "run_id",
    "plan_id",
    "plan_sha256",
    "plan_file",
    "plan_file_sha256",
    "business_date",
    "rag_business_date",
    "manifest_business_date",
    "case_count",
    "turn_count",
    "total_requests",
    "worst_case_cny",
    "reserve_peak_cny",
    "ingest_batches",
    "ingest_sources",
    "scenario_binding",
    "evidence_bindings",
    "contract_validate_run",
    "source_map",
)

DATE_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
HASH_RE = re.compile(r"^[0-9a-f]{64}$")
PLAN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}$")
RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}$")
#: plan_id 的派生形状：``{prefix}-r{index}-{scenario}``（index/scenario 必须与本 run 一致）。
PLAN_ID_DERIVED_RE = re.compile(
    r"^(?P<prefix>[A-Za-z0-9][A-Za-z0-9_.:\-]{0,63})-r(?P<index>[0-3])-(?P<scenario>[a-z0-9_]+)$"
)

RUN_CLAIM_SCHEMA_VERSION = "p2-h2v3-run-claim/v0.1"
#: 全机共享的 run 级租约登记处（run 与 check-only 无需共享路径即可互相排斥）。
RUN_CLAIM_REGISTRY = Path(tempfile.gettempdir()) / "mktkb-p2-h2v3-run-claims"
#: 拿不到进程启动标记时的租约上限（能拿到标记时只看 PID 存活/复用，不按时间抢）。
RUN_CLAIM_MAX_AGE_SECONDS = 6 * 60 * 60.0


class EntryError(RuntimeError):
    """受控拒绝：code 固定可机读；detail 只含固定码/键名/计数。"""

    def __init__(self, code: str, detail: str = "", exit_code: int = EXIT_REFUSED) -> None:
        self.code = str(code)
        self.detail = str(detail)
        self.exit_code = int(exit_code)
        super().__init__(f"{self.code}: {self.detail}" if self.detail else self.code)


def _refuse(code: str, detail: str = "") -> NoReturn:
    raise EntryError(code, detail)


def _usage(code: str, detail: str = "") -> NoReturn:
    raise EntryError(code, detail, EXIT_USAGE)


# --------------------------------------------------------------------------- #
# run 级单写者租约（O_EXCL 占位；PID + 进程启动标记 + 有界 stale）
# --------------------------------------------------------------------------- #


def _claim_registry_root() -> Path:
    """按仓库隔离的全机租约目录：run 与 check-only 用同一路径互相排斥。"""
    tag = hashlib.sha256(str(PROJECT_ROOT.resolve()).encode("utf-8")).hexdigest()[:16]
    return Path(RUN_CLAIM_REGISTRY) / tag


def _claim_path(root: Path, run_id: str) -> Path:
    return Path(root) / f"run-claim-{run_id}.json"


def _claim_is_stale(path: Path) -> bool:
    try:
        stat = path.stat()
        raw = path.read_text(encoding="utf-8")[:4096]
    except (FileNotFoundError, OSError):
        return False
    age = time.time() - stat.st_mtime
    try:
        payload = json.loads(raw)
    except ValueError:
        payload = None
    pid = payload.get("pid") if isinstance(payload, Mapping) else None
    marker = payload.get("process_start") if isinstance(payload, Mapping) else None
    if type(pid) is not int or pid <= 0:
        return age > 60.0
    if pid == os.getpid():
        return False  # 同进程重入：由调用方自己保证不重复 claim
    alive, current = process_identity(pid)
    if not alive:
        return True
    if isinstance(marker, str) and marker and current and marker != current:
        return True  # PID 被复用：原持有者已死
    if not marker and not current and age > RUN_CLAIM_MAX_AGE_SECONDS:
        return True  # 无法证明身份的兜底上限
    return False


def _acquire_run_claim(run_id: str, *, holder: str, root: Path) -> Path:
    """O_EXCL 抢 run 级占位；已有活占位时用固定码拒绝（零发送）。"""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    path = _claim_path(root, run_id)
    payload = {
        "schema_version": RUN_CLAIM_SCHEMA_VERSION,
        "tool": TOOL_SCHEMA_VERSION,
        "run_id": str(run_id),
        "holder": str(holder),
        "pid": os.getpid(),
        "process_start": process_identity(os.getpid())[1],
        "created_utc": _utc_now(),
        "root": str(root),
    }
    for _attempt in range(2):
        try:
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            if _claim_is_stale(path):
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass
                continue
            _refuse("run_claim_held", f"{holder}:{run_id}")
        try:
            try:
                os.write(
                    fd,
                    (json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8"),
                )
                os.fsync(fd)
            finally:
                os.close(fd)
        except OSError:
            _release_run_claim(path)
            _refuse("run_claim_write_failed", run_id)
        try:
            readback = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _refuse("run_claim_readback_mismatch", run_id)
        if readback != payload:
            _refuse("run_claim_readback_mismatch", run_id)
        return path
    _refuse("run_claim_held", f"{holder}:{run_id}")


def _release_run_claim(path: Path) -> None:
    try:
        Path(path).unlink()
    except FileNotFoundError:
        pass


@contextlib.contextmanager
def _run_claim(run_id: str, *, holder: str, roots: Sequence[Path]) -> Any:
    """按顺序抢多个租约根；任一失败即固定码拒绝，退出时按逆序释放。"""
    acquired: list[Path] = []
    try:
        for root in roots:
            acquired.append(_acquire_run_claim(run_id, holder=holder, root=Path(root)))
        yield acquired
    finally:
        for path in reversed(acquired):
            _release_run_claim(path)


def _run_claim_roots(seal_root: Path) -> list[Path]:
    """run 的租约根：全机登记处（与 check-only 共用）+ seal 目录（操作者可核）。"""
    return [_claim_registry_root(), Path(seal_root)]


def _public_payload(payload: Mapping[str, Any], *, strict: bool = False) -> Mapping[str, Any]:
    """公开层出口（FU-4）：受限路径/密钥名/密文名换确定性记号。

    ``strict=False`` 保持既有 stdout 语义（仓外普通绝对路径原样保留，既有测试逐值不变）；
    ``strict=True`` 用于新公开产物（派生卡/组合/证明/分享副本），任何绝对路径都记号化。
    """
    return safe_output.redact_payload(dict(payload), roots=_public_roots(), strict=strict)


def _public_roots() -> tuple[str, ...]:
    """受限根（只读判定用）：仓库根 + 旧 holdout 根 + 变量目录。"""
    roots = [str(PROJECT_ROOT), str(PROJECT_ROOT / "var")]
    roots.append("D:/mktkb-p2-holdout")
    return tuple(roots)


def _public_detail(detail: Any) -> str:
    return safe_output.redact_text("" if detail is None else str(detail), roots=_public_roots())


def _emit(payload: Mapping[str, Any], *, strict: bool = False) -> None:
    print(
        json.dumps(
            dict(_public_payload(payload, strict=strict)),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_file(path: Path | str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _parse_now(value: str | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        _usage("now_invalid")
    if moment.tzinfo is None:
        _usage("now_invalid")
    return moment.astimezone(timezone.utc)


def _write_json_new(path: Path, payload: Any) -> dict[str, Any]:
    target = Path(path)
    if target.exists():
        _refuse("output_already_exists", target.name)
    target.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    raw = text.encode("utf-8")
    target.write_bytes(raw)
    return {"path": str(target), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def _write_json_atomic(path: Path, payload: Any) -> dict[str, Any]:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(target.name + ".tmp")
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    raw = text.encode("utf-8")
    temp.write_bytes(raw)
    os.replace(temp, target)
    return {"path": str(target), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def _require_repo_root() -> None:
    """v3 语料/ingest 的相对路径以仓库根为基准；cwd 不对就拒绝，不做隐式 chdir。"""
    if Path.cwd().resolve() != PROJECT_ROOT.resolve():
        _refuse("cwd_not_project_root", "必须在仓库根运行")


def _require_plain_int(value: Any, code: str, *, minimum: int = 0, maximum: int = 10**9) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        _refuse(code)
    return int(value)


def _require_str(value: Any, code: str, *, maximum: int = 4096) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        _refuse(code)
    return value


def _require_hash(value: Any, code: str) -> str:
    text = _require_str(value, code, maximum=64)
    if HASH_RE.fullmatch(text) is None:
        _refuse(code)
    return text


def _checked_date(value: Any, code: str) -> str:
    text = _require_str(value, code, maximum=10)
    if DATE_RE.fullmatch(text) is None:
        _refuse(code)
    try:
        from datetime import date

        date.fromisoformat(text)
    except ValueError:
        _refuse(code)
    return text


# --------------------------------------------------------------------------- #
# socket 守卫（零发送证明）
# --------------------------------------------------------------------------- #


class _NetworkGuard:
    def __init__(self) -> None:
        self.external: list[str] = []
        self.local: list[str] = []

    def record(self, label: str, address: Any) -> bool:
        host = address
        if isinstance(address, (tuple, list)) and address:
            host = address[0]
        text = str(host or "").strip().lower()
        loopback = (
            text in {"localhost", "::1", "0.0.0.0"}
            or text.startswith("127.")
        )
        (self.local if loopback else self.external).append(label)
        return loopback

    def snapshot(self) -> dict[str, Any]:
        return {"external": list(self.external), "local": list(self.local)}


def _install_network_guard() -> _NetworkGuard:
    guard = _NetworkGuard()
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex
    real_create = socket.create_connection

    def guarded_connect(self, address, *args, **kwargs):  # noqa: ANN001
        if not guard.record(f"socket.connect {address!r}", address):
            raise RuntimeError("v3_entry_network_blocked")
        return real_connect(self, address, *args, **kwargs)

    def guarded_connect_ex(self, address, *args, **kwargs):  # noqa: ANN001
        if not guard.record(f"socket.connect_ex {address!r}", address):
            raise RuntimeError("v3_entry_network_blocked")
        return real_connect_ex(self, address, *args, **kwargs)

    def guarded_create(address, *args, **kwargs):  # noqa: ANN001
        if not guard.record(f"socket.create_connection {address!r}", address):
            raise RuntimeError("v3_entry_network_blocked")
        return real_create(address, *args, **kwargs)

    socket.socket.connect = guarded_connect  # type: ignore[assignment]
    socket.socket.connect_ex = guarded_connect_ex  # type: ignore[assignment]
    socket.create_connection = guarded_create  # type: ignore[assignment]
    return guard


def _positive_control(guard: _NetworkGuard) -> dict[str, Any]:
    """正对照：外部地址必须在 connect 前被拦；拦后清空尝试表，主体不应再有出站。"""
    blocked = False
    try:
        socket.create_connection(("203.0.113.1", 80), timeout=1.0)
    except RuntimeError as exc:
        blocked = str(exc) == "v3_entry_network_blocked"
    except OSError:
        blocked = False
    control = {"attempted": True, "blocked": blocked}
    guard.external.clear()
    guard.local.clear()
    return control


# --------------------------------------------------------------------------- #
# 输入记录 / binding 文档
# --------------------------------------------------------------------------- #


def _input_record(name: str, path: Path | str, *, private: bool) -> dict[str, Any]:
    try:
        resolved = v2.assert_private_path(path) if private else Path(path).expanduser().resolve()
    except ScenarioError:
        _refuse("input_path_rejected", name)
    except OSError:
        _refuse("input_path_invalid", name)
    if not resolved.is_file():
        _refuse("input_file_missing", name)
    size = resolved.stat().st_size
    if size <= 0 or size > 16 * 1024 * 1024:
        _refuse("input_size_invalid", name)
    return {"path": str(resolved), "sha256": _sha256_file(resolved), "bytes": int(size)}


def _records_from_paths(root: Path, key_file: Path) -> dict[str, dict[str, Any]]:
    root = Path(root).expanduser().resolve(strict=False)
    key_file = Path(key_file).expanduser().resolve(strict=False)
    if not root.is_dir():
        _refuse("holdout_root_missing")
    paths: dict[str, tuple[Path, bool]] = {
        "holdout_manifest": (root / "manifest.json", False),
        "annotation_ciphertext": (root / "annotations-v0_2.fernet", True),
        "review_ciphertext": (root / "review-v0_2.fernet", True),
        "scenario_key_file": (key_file, True),
        "scenario_contract": (contract_v3.V3_SCENARIO_CONTRACT, False),
        "ingest_plan": (contract_v3.V3_INGEST, False),
        "source_map": (contract_v3.V3_SOURCE_MAP, False),
        "annotation_schema": (contract_v3.V3_SCHEMA, False),
        "manager_acceptance": (contract_v3.V3_MANAGER, False),
        "review_aggregate": (contract_v3.V3_REVIEW_AGGREGATE, False),
        "lifecycle": (run_date.LIFECYCLE_PATH, False),
        "v3_freeze": (
            PROJECT_ROOT
            / "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/v3-freeze/p2-holdout-v3.freeze.json",
            False,
        ),
        "pre_registration": (
            PROJECT_ROOT
            / "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/v3-author/pre-registration.json",
            False,
        ),
        "mock_dryrun_summary": (
            PROJECT_ROOT / "docs/reports/OBS-EVAL/P2/H2V3/dryrun/summary.json",
            False,
        ),
    }
    records = {
        name: _input_record(name, path, private=private)
        for name, (path, private) in paths.items()
    }
    manifest = Path(records["holdout_manifest"]["path"])
    if manifest.parent != root:
        _refuse("holdout_root_manifest_mismatch")
    v2.check_runtime_options(
        v2.RuntimeOptions(
            holdout_root=root,
            holdout_key_file=key_file,
            project_total_limit_cny=V3_PROJECT_TOTAL_LIMIT_CNY,
        )
    )
    return records


def _records_from_document(document: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    inputs = document.get("inputs")
    if not isinstance(inputs, Mapping) or set(inputs) != set(V3_INPUT_NAMES):
        _refuse("run_binding_invalid", "inputs")
    records: dict[str, dict[str, Any]] = {}
    for name in V3_INPUT_NAMES:
        record = inputs[name]
        if not isinstance(record, Mapping) or set(record) != {"path", "sha256", "bytes"}:
            _refuse("run_binding_invalid", "inputs." + name)
        path = Path(_require_str(record.get("path"), "run_binding_invalid", maximum=1024))
        if not path.is_file():
            _refuse("input_file_missing", name)
        digest = _require_hash(record.get("sha256"), "run_binding_invalid")
        if _sha256_file(path) != digest:
            _refuse("input_changed_since_plan", name)
        size = int(path.stat().st_size)
        if int(record.get("bytes", -1)) != size:
            _refuse("input_size_changed", name)
        records[name] = {"path": str(path), "sha256": digest, "bytes": size}
    return records


def _verify_input_digests(document: Mapping[str, Any]) -> None:
    _records_from_document(document)


def _select_run(document: Mapping[str, Any], run_index: int) -> Mapping[str, Any]:
    runs = document.get("runs")
    if not isinstance(runs, list) or len(runs) != 1:
        _refuse("run_binding_invalid", "runs")
    run = runs[0]
    if int(run.get("run_index", -1)) != int(run_index):
        _refuse("run_index_mismatch")
    return run


# --------------------------------------------------------------------------- #
# v3 ingest 批数派生（按 v3 实际内容；v2 冻结配方常量不动）
# --------------------------------------------------------------------------- #

_CENSUS_CACHE: dict[str, Any] | None = None


def _load_batch_census() -> dict[str, Any]:
    """读 v3 批数 census（零网络实测的逐源批数），逐项校验后缓存。"""
    global _CENSUS_CACHE
    if _CENSUS_CACHE is not None:
        return _CENSUS_CACHE
    path = Path(V3_BATCH_CENSUS)
    if not path.is_file():
        _refuse("ingest_batch_census_missing")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        _refuse("ingest_batch_census_unreadable")
    if not isinstance(payload, Mapping) or payload.get("schema_version") != V3_BATCH_CENSUS_SCHEMA:
        _refuse("ingest_batch_census_invalid", "schema_version")
    per_source = payload.get("per_source")
    scenarios = payload.get("scenarios")
    if not isinstance(per_source, Mapping) or not isinstance(scenarios, Mapping):
        _refuse("ingest_batch_census_invalid", "tables")
    if {str(key) for key in per_source} != {str(index) for index in range(12)}:
        _refuse("ingest_batch_census_invalid", "per_source")
    counts: dict[str, int] = {}
    for key, row in per_source.items():
        if not isinstance(row, Mapping) or set(row) != {"embed_posts"}:
            _refuse("ingest_batch_census_invalid", "per_source." + str(key))
        value = row.get("embed_posts")
        if type(value) is not int or not 1 <= int(value) <= 64:
            _refuse("ingest_batch_census_invalid", "per_source." + str(key))
        counts[str(key)] = int(value)
    required: dict[str, int] = {}
    indices: dict[str, tuple[int, ...]] = {}
    for scenario in v2.SCENARIO_ORDER:
        row = scenarios.get(scenario)
        if not isinstance(row, Mapping):
            _refuse("ingest_batch_census_invalid", "scenarios." + scenario)
        raw_indices = row.get("source_indices")
        if not isinstance(raw_indices, list) or not raw_indices:
            _refuse("ingest_batch_census_invalid", "scenarios." + scenario + ".source_indices")
        if any(type(index) is not int or not 0 <= int(index) < 12 for index in raw_indices):
            _refuse("ingest_batch_census_invalid", "scenarios." + scenario + ".source_indices")
        chosen = tuple(int(index) for index in raw_indices)
        if len(set(chosen)) != len(chosen):
            _refuse("ingest_batch_census_invalid", "scenarios." + scenario + ".source_indices")
        total = sum(counts[str(index)] for index in chosen)
        if int(row.get("embed_posts_required", -1)) != total:
            _refuse("ingest_batch_derivation_mismatch", scenario)
        if int(row.get("published_sources", -1)) != len(chosen):
            _refuse("ingest_batch_derivation_mismatch", scenario)
        required[scenario] = total
        indices[scenario] = chosen
    _CENSUS_CACHE = {
        "per_source": counts,
        "required": required,
        "source_indices": indices,
        "sha256": _sha256_file(path),
        "path": str(path),
    }
    return _CENSUS_CACHE


def _v3_ingest_batch_plan() -> dict[str, int]:
    """四 run 的 index_embedding 上界：逐源实测批数按 scenario 源下标求和。"""
    return dict(_load_batch_census()["required"])


def _v3_ingest_batches(scenario: str, *, expected_sources: int | None = None) -> int:
    """单个 scenario 的 index_embedding 上界（v3 实际内容派生，不是 v2 配方常量）。"""
    census = _load_batch_census()
    if scenario not in census["required"]:
        _refuse("ingest_batch_derivation_mismatch", scenario)
    if expected_sources is not None and int(expected_sources) != len(
        census["source_indices"][scenario]
    ):
        _refuse("ingest_batch_source_count_mismatch", scenario)
    return int(census["required"][scenario])


def _v3_config(
    *,
    business_date: str,
    anchor_business_date: str,
    inputs: Mapping[str, Mapping[str, Any]],
    code_version: str,
    thresholds_approved: bool,
) -> dict[str, Any]:
    batches = _v3_ingest_batch_plan()
    return {
        "schema_version": "p2-h2v3-controlled-run-config/v0.1",
        "business_date": business_date,
        "anchor_business_date": anchor_business_date,
        "fixture_kind": LIVE_FIXTURE_KIND,
        "execution_mode": "live",
        "providers": v2._provider_config(),
        "project_total_limit_cny": float(V3_PROJECT_TOTAL_LIMIT_CNY),
        "stage_limit_cny": float(STAGE_LIMIT_CNY),
        "max_requests": MAX_REQUESTS,
        "cost_centers_cny": {center: float(value) for center, value in v2._h2_centers().items()},
        "turn_timeout_seconds": float(TURN_TIMEOUT_SECONDS),
        "purge_traces_on_close": True,
        "force_evidence_capture": True,
        "thresholds_approved": bool(thresholds_approved),
        "scenario_order": list(v2.SCENARIO_ORDER),
        "scenario_ingest_batches": batches,
        "scenario_ingest_batches_source": {
            "path": str(Path(V3_BATCH_CENSUS).relative_to(PROJECT_ROOT)).replace("\\", "/"),
            "sha256": str(_load_batch_census()["sha256"]),
            "rule": "sum(per_source[index].embed_posts for index in scenario source_indices)",
        },
        "code_version": code_version,
        "inputs": {
            name: str(inputs[name]["sha256"]) for name in V3_INPUT_NAMES if name in inputs
        },
    }


def _validate_binding_document(document: Any) -> None:
    if not isinstance(document, Mapping) or set(document) != set(V3_BINDING_KEYS):
        _refuse("run_binding_invalid")
    if document.get("schema_version") != BINDING_SCHEMA_VERSION:
        _refuse("run_binding_invalid", "schema_version")
    if document.get("fixture_kind") != LIVE_FIXTURE_KIND:
        _refuse("run_binding_invalid", "fixture_kind")
    if document.get("execution_mode") != "live":
        _refuse("run_binding_invalid", "execution_mode")
    v2._validate_created_utc(str(document.get("created_utc") or ""))
    business_date = _checked_date(document.get("business_date"), "run_binding_invalid")
    anchor = _checked_date(document.get("anchor_business_date"), "run_binding_invalid")
    if business_date == anchor:
        _refuse("run_binding_invalid", "business_date_equals_anchor")
    root = Path(_require_str(document.get("holdout_root"), "run_binding_invalid", maximum=1024))
    if not root.is_dir():
        _refuse("run_binding_invalid", "holdout_root")
    if root == PROJECT_ROOT.resolve() or PROJECT_ROOT.resolve() in root.parents:
        _refuse("run_binding_invalid", "holdout_root_inside_repo")
    code_version = _require_hash(document.get("code_version"), "run_binding_invalid")
    config_sha = _require_hash(document.get("config_sha256"), "run_binding_invalid")
    config = document.get("config")
    if not isinstance(config, Mapping) or payload_sha256(config) != config_sha:
        _refuse("run_binding_invalid", "config_sha256")
    if str(config.get("code_version")) != code_version:
        _refuse("run_binding_invalid", "config_code_version")
    if str(config.get("business_date")) != business_date:
        _refuse("run_binding_invalid", "config_business_date")
    if str(config.get("anchor_business_date")) != anchor:
        _refuse("run_binding_invalid", "config_anchor_business_date")
    if abs(float(config.get("project_total_limit_cny", -1)) - V3_PROJECT_TOTAL_LIMIT_CNY) > 1e-9:
        _refuse("run_binding_invalid", "config_project_total_limit_cny")
    if config.get("max_requests") != MAX_REQUESTS:
        _refuse("run_binding_invalid", "config_max_requests")
    if list(config.get("scenario_order") or ()) != list(v2.SCENARIO_ORDER):
        _refuse("run_binding_invalid", "config_scenario_order")
    if dict(config.get("scenario_ingest_batches") or {}) != _v3_ingest_batch_plan():
        _refuse("run_binding_invalid", "config_ingest_batches")
    dataset = document.get("dataset")
    if not isinstance(dataset, Mapping):
        _refuse("run_binding_invalid", "dataset")
    if int(dataset.get("case_count", -1)) != sum(V3_SCENARIO_COUNTS.values()):
        _refuse("run_binding_invalid", "dataset.case_count")
    if int(dataset.get("total_turns", -1)) != sum(V3_SCENARIO_TURNS.values()):
        _refuse("run_binding_invalid", "dataset.total_turns")
    if dict(dataset.get("scenario_counts") or {}) != dict(V3_SCENARIO_COUNTS):
        _refuse("run_binding_invalid", "dataset.scenario_counts")
    _require_hash(dataset.get("manifest_sha256"), "run_binding_invalid")
    if str(dataset.get("anchor_business_date")) != anchor:
        _refuse("run_binding_invalid", "dataset.anchor_business_date")
    for key in ("dataset_version", "label_version", "suite"):
        _require_str(dataset.get(key), "run_binding_invalid", maximum=128)
    inputs = document.get("inputs")
    if not isinstance(inputs, Mapping) or set(inputs) != set(V3_INPUT_NAMES):
        _refuse("run_binding_invalid", "inputs")
    for name in V3_INPUT_NAMES:
        record = inputs[name]
        if not isinstance(record, Mapping) or set(record) != {"path", "sha256", "bytes"}:
            _refuse("run_binding_invalid", "inputs." + name)
        _require_str(record.get("path"), "run_binding_invalid", maximum=1024)
        _require_hash(record.get("sha256"), "run_binding_invalid")
        _require_plain_int(record.get("bytes"), "run_binding_invalid", minimum=1)
    runs = document.get("runs")
    if not isinstance(runs, list) or len(runs) != 1:
        _refuse("run_binding_invalid", "runs")
    run = runs[0]
    if not isinstance(run, Mapping) or set(run) != set(V3_RUN_KEYS):
        _refuse("run_binding_invalid", "runs[0]")
    run_index = _require_plain_int(run.get("run_index"), "run_binding_invalid", maximum=3)
    scenario = str(run.get("scenario_id"))
    if scenario != v2.SCENARIO_ORDER[run_index]:
        _refuse("scenario_order_mismatch", scenario)
    run_id = _require_str(run.get("run_id"), "run_binding_invalid", maximum=96)
    if RUN_ID_RE.fullmatch(run_id) is None:
        _refuse("run_binding_invalid", "run_id")
    plan_id = _require_str(run.get("plan_id"), "run_binding_invalid", maximum=96)
    if PLAN_ID_RE.fullmatch(plan_id) is None:
        _refuse("run_binding_invalid", "plan_id")
    plan_sha = _require_hash(run.get("plan_sha256"), "run_binding_invalid")
    plan_file = v2.require_outside_repo(Path(str(run.get("plan_file"))), "plan_file")
    if plan_file.suffix != ".json":
        _refuse("run_binding_invalid", "plan_file")
    _require_hash(run.get("plan_file_sha256"), "run_binding_invalid")
    if str(run.get("business_date")) != business_date:
        _refuse("run_binding_invalid", "run_business_date")
    if str(run.get("rag_business_date")) != business_date or str(
        run.get("manifest_business_date")
    ) != business_date:
        _refuse("run_binding_invalid", "run_date_binding")
    case_count = _require_plain_int(run.get("case_count"), "run_binding_invalid", minimum=1)
    turn_count = _require_plain_int(run.get("turn_count"), "run_binding_invalid", minimum=1)
    if case_count != V3_SCENARIO_COUNTS[scenario] or turn_count != V3_SCENARIO_TURNS[scenario]:
        _refuse("run_binding_invalid", "run_counts")
    _require_plain_int(run.get("total_requests"), "run_binding_invalid", minimum=1)
    if float(run.get("worst_case_cny") or 0) <= 0 or float(run.get("reserve_peak_cny") or 0) <= 0:
        _refuse("run_binding_invalid", "money")
    if int(run.get("ingest_batches", -1)) != _v3_ingest_batches(scenario):
        _refuse("ingest_batches_mismatch", scenario)
    _require_plain_int(run.get("ingest_sources"), "run_binding_invalid", minimum=1, maximum=64)
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
        _require_str(bindings.get(key), "run_binding_invalid", maximum=256)
    if str(bindings.get("fixture_kind")) != LIVE_FIXTURE_KIND:
        _refuse("run_binding_invalid", "evidence_bindings.fixture_kind")
    if str(bindings.get("index_revision")) != LIVE_PENDING_INDEX_REVISION:
        _refuse("run_binding_invalid", "evidence_bindings.index_revision")
    static = {
        "config_sha256": config_sha,
        "code_version": code_version,
        "dataset_version": str(dataset["dataset_version"]),
        "manifest_sha256": str(dataset["manifest_sha256"]),
        "label_version": str(dataset["label_version"]),
        "suite": str(dataset["suite"]),
        "fixture_kind": LIVE_FIXTURE_KIND,
    }
    for key, value in static.items():
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
    contract_validate = run.get("contract_validate_run")
    if not isinstance(contract_validate, Mapping) or contract_validate.get("ok") is not True:
        _refuse("scenario_plan_mismatch", "binding_contract_validate_not_ok")
    source = run.get("source_map")
    if not isinstance(source, Mapping):
        _refuse("run_binding_invalid", "source_map")
    if str(source.get("schema_version")) != source_map.SCHEMA_V02:
        _refuse("run_binding_invalid", "source_map.schema_version")
    if int(source.get("code_count", -1)) != len(source_map.V02_DOC_CODES):
        _refuse("run_binding_invalid", "source_map.code_count")
    if str(source.get("sha256")) != str(inputs["source_map"]["sha256"]):
        _refuse("run_binding_invalid", "source_map.sha256")
    expected_binding_sha = payload_sha256(
        {key: value for key, value in document.items() if key != "binding_sha256"}
    )
    if str(document.get("binding_sha256")) != expected_binding_sha:
        _refuse("run_binding_invalid", "binding_sha256")


# v2 的 load_run_binding 通过模块全局查这个校验器；这里换成 v3 形状（v2 文件本身未改）。
v2._validate_binding_document = _validate_binding_document


# --------------------------------------------------------------------------- #
# 私有材料装配（v3 loader；明文只在内存）
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class V3Bundle:
    dataset: Any
    contract: Any
    annotation: Any
    review: Mapping[str, Any]
    inputs: Mapping[str, Mapping[str, Any]]
    anchor_business_date: str
    run_dates: tuple[Any, ...]
    bindings: tuple[Any, ...]


def _decrypt_annotation(path: Path, key_file: Path) -> dict[str, Any]:
    try:
        plain = Fernet(Path(key_file).read_bytes().strip()).decrypt(Path(path).read_bytes())
    except Exception:  # noqa: BLE001 - 坏 key/截断密文统一固定码
        _refuse("annotation_decrypt_failed")
    try:
        payload = json.loads(plain.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        _refuse("annotation_decrypt_failed")
    if not isinstance(payload, dict):
        _refuse("annotation_decrypt_failed")
    return payload


@dataclass(frozen=True, repr=False)
class _V3BatchContract(ValidatedScenarioContract):
    """在冻结契约之上**只**放宽 ``index_embedding.requests`` 一格的执行期复算。

    冻结 ``ValidatedScenarioContract.validate_run`` 用 v2 配方（RECIPES=8/9/11/13）重建
    期望计划并逐值比较；v3 计划按语料实测 B=9/10/13/15 生成。``p2_live`` 的
    ``validate_scenario_execution`` 会在首个预留前再调一次 ``validate_run``，且只认
    ``isinstance(..., ValidatedScenarioContract)``。本子类继承同一封印类：仅当「其余逐值
    相同、唯一差异是 index_embedding 项的 requests、且该值等于 v3 派生值」时放行；其余任何
    差异仍按原码 ``scenario_plan_mismatch`` 拒绝。产品/评测模块一字未改。

    ``_authorized`` 是 **check 层已授权** 的 delta（``contract_validate_run.authorized_delta``）：
    执行层不是自行放宽，而是必须与授权值逐值一致才放行；缺授权则维持冻结契约的原始拒绝。
    """

    _authorized: Mapping[str, Any] | None = field(default=None, repr=False)

    def validate_run(self, plan, dataset, ingest):  # noqa: ANN001 - 与冻结签名一致
        try:
            super().validate_run(plan, dataset, ingest)
            return
        except ScenarioError as exc:
            if str(getattr(exc, "code", "")) != "scenario_plan_mismatch":
                raise
        binding = plan.scenario_binding
        scenario = str(dict(binding or {}).get("scenario_id") or "")
        expected = super().build_plan(
            scenario,
            plan_id=plan.plan_id,
            created_utc=plan.created_utc,
            plan_version=plan.plan_version,
            max_requests=plan.max_requests,
        )
        delta = _authorized_batch_delta(plan, expected, scenario)
        if not delta.get("ok"):
            raise ScenarioError("scenario_plan_mismatch")
        if self._authorized is None:
            # 执行层没拿到 check 层授权：不放宽（等价于冻结契约的原始拒绝）。
            raise ScenarioError("scenario_plan_mismatch")
        authorized, observed = dict(self._authorized), dict(delta["delta"])
        if (
            str(authorized.get("item_id")) != str(observed.get("item_id"))
            or int(authorized.get("plan_requests", -1)) != int(observed["plan_requests"])
            or int(authorized.get("contract_recipe_requests", -1))
            != int(observed["contract_recipe_requests"])
        ):
            # 授权值与执行期实测值不一致：拒绝，不按“较小者”凑合。
            raise ScenarioError("scenario_plan_mismatch")


def _wrap_v3_contract(
    contract: ValidatedScenarioContract, *, authorized: Mapping[str, Any] | None = None
) -> _V3BatchContract:
    return _V3BatchContract(
        contract._dataset,  # noqa: SLF001 - 同一进程内复用已校验字段
        contract._assignments,  # noqa: SLF001
        contract._bindings,  # noqa: SLF001
        contract._ingest,  # noqa: SLF001
        contract._proof,  # noqa: SLF001
        contract._axis_counts,  # noqa: SLF001
        contract._gaps,  # noqa: SLF001
        None if authorized is None else dict(authorized),
    )


def _execution_contract(
    bundle: V3Bundle,
    plan: P2RunPlan,
    contract_state: Mapping[str, Any],
    scenario: str,
) -> ValidatedScenarioContract:
    """把 check 层已授权的 delta 显式交给执行层（v2 执行核心只认 ``ValidatedScenarioContract``）。

    - 计划与 v2 配方逐值相同（``contract_state.code is None``）→ 原契约原样返回，v2 行为不变；
    - check 层给出 ``authorized_delta`` → 三方逐值校验（授权值 == 计划值 == census 派生值）
      后返回只放宽这一格的子类；
    - 其余任何形状 → 拒绝，绝不“顺手放宽”。
    """
    if contract_state.get("ok") is not True:
        _refuse("scenario_plan_mismatch", str(contract_state.get("code") or ""))
    authorized = contract_state.get("authorized_delta")
    if not authorized:
        if contract_state.get("code") is not None:
            _refuse("scenario_plan_mismatch", str(contract_state.get("code") or ""))
        return bundle.contract
    delta = dict(authorized)
    items = [item for item in plan.items if item.operation == "index_embedding"]
    if len(items) != 1:
        _refuse("exec_contract_invalid", "ingest_item")
    derived = _v3_ingest_batches(scenario)
    if not (
        str(delta.get("item_id")) == str(items[0].item_id)
        and int(delta.get("plan_requests", -1)) == int(items[0].requests) == int(derived)
        and int(delta.get("contract_recipe_requests", -1)) > 0
        and str(delta.get("derived_from")) == "v3_ingest_batch_census"
    ):
        _refuse("exec_contract_invalid", "authorized_delta")
    return _wrap_v3_contract(bundle.contract, authorized=delta)


def load_v3_bundle(inputs: Mapping[str, Mapping[str, Any]]) -> V3Bundle:
    manifest_path = Path(inputs["holdout_manifest"]["path"])
    key_file = Path(inputs["scenario_key_file"]["path"])
    root = manifest_path.parent
    v2.check_runtime_options(
        v2.RuntimeOptions(
            holdout_root=root,
            holdout_key_file=key_file,
            project_total_limit_cny=V3_PROJECT_TOTAL_LIMIT_CNY,
        )
    )
    env = {
        "MKTKB_P2_HOLDOUT_ROOT": str(root),
        "MKTKB_P2_HOLDOUT_KEY_FILE": str(key_file),
        TOTAL_LIMIT_ENV: str(V3_PROJECT_TOTAL_LIMIT_CNY),
    }
    try:
        with v2.applied_env(env):
            dataset = load_p2_dataset(manifest_path, visibility="holdout")
            contract = contract_v3.load_v3_scenario_contract(
                dataset,
                annotation_path=Path(inputs["annotation_ciphertext"]["path"]),
                key_file=key_file,
                review_path=Path(inputs["review_ciphertext"]["path"]),
                manager_path=Path(inputs["manager_acceptance"]["path"]),
                review_aggregate_path=Path(inputs["review_aggregate"]["path"]),
                scenario_path=Path(inputs["scenario_contract"]["path"]),
                ingest_path=Path(inputs["ingest_plan"]["path"]),
                source_map_path=Path(inputs["source_map"]["path"]),
                schema_path=Path(inputs["annotation_schema"]["path"]),
            )
    except ScenarioError as exc:
        _refuse("scenario_contract_invalid", str(exc)[:120])
    except P2DatasetError as exc:
        _refuse("dataset_invalid", str(getattr(exc, "reason", "") or type(exc).__name__))
    except ValueError as exc:
        _refuse("dataset_invalid", type(exc).__name__)
    payload = _decrypt_annotation(Path(inputs["annotation_ciphertext"]["path"]), key_file)
    try:
        annotation = hard.prepare_annotation(
            payload,
            dataset.cases,
            schema_path=contract_v3.V3_SCHEMA,
            scenario_path=contract_v3.V3_SCENARIO_CONTRACT,
        )
    except hard.HardEvidenceError as exc:
        _refuse("annotation_invalid", str(exc)[:120])
    except ValueError as exc:
        _refuse("annotation_invalid", type(exc).__name__)
    try:
        run_dates = run_date.verified_run_dates(
            lifecycle_path=Path(inputs["lifecycle"]["path"])
        )
        binds = tuple(
            run_date.bind_run(
                index,
                table=run_dates,
                dataset_anchor=dataset.manifest.business_date,
            )
            for index in range(len(v2.SCENARIO_ORDER))
        )
    except run_date.RunDateError as exc:
        _refuse(str(exc))
    try:
        review = json.loads(
            Path(inputs["review_aggregate"]["path"]).read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        _refuse("review_aggregate_invalid")
    if not isinstance(review, Mapping):
        _refuse("review_aggregate_invalid")
    return V3Bundle(
        dataset=dataset,
        contract=contract,
        annotation=annotation,
        review=review,
        inputs=inputs,
        anchor_business_date=str(dataset.manifest.business_date),
        run_dates=tuple(run_dates),
        bindings=binds,
    )


def _verify_axis_counts(bundle: V3Bundle) -> None:
    expected = bundle.review.get("axis_counts")
    summary = bundle.annotation.public_summary()
    normalized = {
        str(name): {str(state): int(count) for state, count in table.items()}
        for name, table in (expected or {}).items()
    }
    if not isinstance(expected, Mapping) or {
        str(name): {str(state): int(count) for state, count in table.items()}
        for name, table in summary["axis_counts"].items()
    } != normalized:
        _refuse("axis_counts_mismatch")


def _validate_dataset_shape(bundle: V3Bundle) -> None:
    dataset = bundle.dataset
    if str(getattr(dataset, "visibility", "")) != "holdout":
        _refuse("dataset_visibility_invalid")
    manifest = dataset.manifest
    if int(manifest.case_count) != sum(V3_SCENARIO_COUNTS.values()):
        _refuse("dataset_case_count_invalid")
    if str(manifest.business_date) != bundle.anchor_business_date:
        _refuse("business_date_manifest_mismatch")
    cases = tuple(dataset.cases)
    if len(cases) != sum(V3_SCENARIO_COUNTS.values()):
        _refuse("dataset_case_count_invalid")
    if len({str(case.case_id) for case in cases}) != len(cases):
        _refuse("dataset_case_duplicate")
    if sum(len(case_questions(case)) for case in cases) != sum(V3_SCENARIO_TURNS.values()):
        _refuse("dataset_turn_count_invalid")
    if dict(bundle.contract.safe_summary().get("scenario_counts") or {}) != dict(
        V3_SCENARIO_COUNTS
    ):
        _refuse("scenario_counts_mismatch")
    seen: set[str] = set()
    for index, binding in enumerate(bundle.bindings):
        scenario = v2.SCENARIO_ORDER[index]
        if binding.scenario_id != scenario:
            _refuse("run_date_scenario_mismatch", scenario)
        subset = bundle.contract.subset(scenario)
        if len(subset.cases) != V3_SCENARIO_COUNTS[scenario]:
            _refuse("scenario_case_count_mismatch", scenario)
        turns = sum(len(case_questions(case)) for case in subset.cases)
        if turns != V3_SCENARIO_TURNS[scenario]:
            _refuse("scenario_turn_count_mismatch", scenario)
        for case in subset.cases:
            if str(case.case_id) in seen:
                _refuse("scenario_case_overlap", scenario)
            seen.add(str(case.case_id))
            if str(case.business_date or "") != binding.business_date:
                _refuse("business_date_case_mismatch", scenario)
    if seen != {str(case.case_id) for case in cases}:
        _refuse("scenario_partition_incomplete")


# --------------------------------------------------------------------------- #
# 计划重算 / 契约复核 / source-map
# --------------------------------------------------------------------------- #


def _plan_cases(plan: P2RunPlan) -> tuple[tuple[tuple[str, int], ...], int]:
    order: list[str] = []
    turns: dict[str, set[int]] = {}
    batches: int | None = None
    for item in plan.items:
        if item.operation == "index_embedding":
            if batches is not None:
                _refuse("plan_ingest_item_invalid")
            batches = int(item.requests)
            continue
        if item.case_id not in turns:
            turns[item.case_id] = set()
            order.append(item.case_id)
        turns[item.case_id].add(int(item.turn))
    if batches is None or not order:
        _refuse("plan_cases_invalid")
    cases: list[tuple[str, int]] = []
    for case_id in order:
        values = sorted(turns[case_id])
        if values != list(range(1, max(values) + 1)):
            _refuse("plan_case_turns_invalid")
        cases.append((case_id, max(values)))
    if sum(len(turns[case_id]) for case_id in order) != int(plan.turn_count) - 1:
        _refuse("plan_turn_count_mismatch")
    return tuple(cases), batches


def _plan_dial(plan: P2RunPlan, run_entry: Mapping[str, Any]) -> dict[str, Any]:
    """v3 计划旋钮必须在**发送前**逐项对齐（run 与 check-only 同一套判定）。"""
    failed: list[str] = []
    if abs(float(plan.project_total_limit_cny) - V3_PROJECT_TOTAL_LIMIT_CNY) > 1e-9:
        failed.append("project_total_limit_cny")
    if plan.max_requests != MAX_REQUESTS:
        failed.append("max_requests")
    if int(plan.total_requests) != int(run_entry["total_requests"]):
        failed.append("total_requests")
    if int(plan.case_count) - 1 != int(run_entry["case_count"]):
        failed.append("case_count")
    if int(plan.turn_count) - 1 != int(run_entry["turn_count"]):
        failed.append("turn_count")
    return {"ok": not failed, "failed": failed}


def _plan_id_derivation(
    plan: P2RunPlan, run_index: int, scenario: str
) -> dict[str, Any]:
    """plan_id 必须由 ``{prefix}-r{index}-{scenario}`` 派生且与本 run 一致。"""
    match = PLAN_ID_DERIVED_RE.fullmatch(str(plan.plan_id))
    if match is None:
        return {"ok": False, "code": "plan_id_not_derived", "detail": "shape"}
    if int(match.group("index")) != int(run_index):
        return {"ok": False, "code": "plan_id_not_derived", "detail": "run_index"}
    if match.group("scenario") != str(scenario):
        return {"ok": False, "code": "plan_id_not_derived", "detail": "scenario"}
    binding = plan.scenario_binding
    if not isinstance(binding, Mapping) or str(binding.get("scenario_id") or "") != str(scenario):
        return {"ok": False, "code": "plan_id_not_derived", "detail": "binding"}
    return {"ok": True, "code": None, "detail": "", "prefix": match.group("prefix")}


def _recompute_plan(
    plan: P2RunPlan, *, run_index: int, scenario: str
) -> dict[str, Any]:
    """用与 ``ValidatedScenarioContract.build_plan`` 相同的调用重算；
    ``project_total_limit_cny`` 不显式传，走模块默认（导入期读环境）。

    ``run_index`` / ``scenario`` 用于校验 plan_id 的派生形状；两者不符时用固定码
    ``plan_id_not_derived`` 拒绝，不把"换计划身份"当成普通字段差异。
    """
    derivation = _plan_id_derivation(plan, run_index, scenario)
    if not derivation["ok"]:
        return {
            "ok": False,
            "code": derivation["code"],
            "detail": derivation["detail"],
            "differing_keys": [],
        }
    cases, batches = _plan_cases(plan)
    expected = holdout_plan.build_holdout_plan(
        cases=cases,
        ingest_batches=batches,
        plan_id=plan.plan_id,
        plan_version=plan.plan_version,
        created_utc=plan.created_utc,
        max_requests=plan.max_requests,
        scenario_binding=plan.scenario_binding,
    )
    left, right = plan.as_dict(), expected.as_dict()
    differing = sorted(key for key in set(left) | set(right) if left.get(key) != right.get(key))
    if differing:
        return {
            "ok": False,
            "code": "scenario_plan_mismatch",
            "differing_keys": differing,
            "plan_values": {key: left.get(key) for key in differing},
            "expected_values": {key: right.get(key) for key in differing},
        }
    return {
        "ok": True,
        "code": None,
        "differing_keys": [],
        "plan_id_derivation": derivation,
    }


def _plan_diff(left: Mapping[str, Any], right: Mapping[str, Any]) -> list[str]:
    return sorted(key for key in set(left) | set(right) if left.get(key) != right.get(key))


def _authorized_batch_delta(
    plan: P2RunPlan, expected: P2RunPlan, scenario: str
) -> dict[str, Any]:
    """v3 授权差额：**只允许** index_embedding 项的 requests 与 v2 配方计划不同。

    计划侧 B 由 v3 实际内容派生（census），冻结契约侧仍按 v2 配方生成同一条计划；
    除这一格 requests 外，两份 ``as_dict()`` 必须逐值相同 —— 这就是「计划生成方式」
    的全部改动面（其余字段、题数/回合、成本中心、绑定、上限都不放宽）。
    """
    left, right = plan.as_dict(), expected.as_dict()
    differing = _plan_diff(left, right)
    if differing != ["items"]:
        return {
            "ok": False,
            "code": "scenario_plan_mismatch",
            "differing_keys": differing,
            "plan_values": {key: left.get(key) for key in differing},
            "expected_values": {key: right.get(key) for key in differing},
        }
    left_items, right_items = left.get("items"), right.get("items")
    if not isinstance(left_items, list) or not isinstance(right_items, list) or len(
        left_items
    ) != len(right_items):
        return {"ok": False, "code": "plan_items_shape", "differing_keys": ["items"]}
    changed = [
        (mine, theirs)
        for mine, theirs in zip(left_items, right_items)
        if mine != theirs
    ]
    if len(changed) != 1:
        return {
            "ok": False,
            "code": "plan_items_delta_not_singular",
            "differing_keys": ["items"],
            "changed_items": len(changed),
        }
    mine, theirs = changed[0]
    if (
        mine.get("operation") != "index_embedding"
        or theirs.get("operation") != "index_embedding"
    ):
        return {
            "ok": False,
            "code": "plan_items_delta_unexpected_operation",
            "differing_keys": ["items"],
        }
    other = sorted(
        key
        for key in set(mine) | set(theirs)
        if key != "requests" and mine.get(key) != theirs.get(key)
    )
    if other:
        return {
            "ok": False,
            "code": "plan_item_delta_beyond_requests",
            "differing_keys": other,
        }
    target = _v3_ingest_batches(scenario)
    if int(mine.get("requests", -1)) != target:
        return {
            "ok": False,
            "code": "ingest_batches_not_derived",
            "plan_batches": mine.get("requests"),
            "derived_batches": target,
        }
    return {
        "ok": True,
        "code": None,
        "differing_keys": ["items[index_embedding].requests"],
        "delta": {
            "item_id": str(mine.get("item_id")),
            "plan_requests": int(mine.get("requests")),
            "contract_recipe_requests": int(theirs.get("requests")),
            "derived_from": "v3_ingest_batch_census",
        },
    }


def _contract_validate(
    bundle: V3Bundle, plan: P2RunPlan, scenario: str
) -> dict[str, Any]:
    subset = bundle.contract.subset(scenario)
    ingest = bundle.contract.ingest_plan(scenario)
    try:
        bundle.contract.validate_run(plan, subset, ingest)
    except Exception as exc:  # noqa: BLE001 - 契约复核失败只报稳定码，不把异常当通过
        code = str(
            getattr(exc, "code", None)
            or getattr(exc, "reason", None)
            or type(exc).__name__
        )
        try:
            expected = bundle.contract.build_plan(
                scenario,
                plan_id=plan.plan_id,
                created_utc=plan.created_utc,
                plan_version=plan.plan_version,
                max_requests=plan.max_requests,
            )
        except Exception:  # noqa: BLE001 - 复核失败只报固定码，不掩盖原始码
            return {"ok": False, "code": code, "differing_keys": [], "rebuilt": False}
        if code == "scenario_plan_mismatch":
            delta = _authorized_batch_delta(plan, expected, scenario)
            if delta["ok"]:
                return {
                    "ok": True,
                    "code": "index_embedding_batches_v3_derived",
                    "differing_keys": list(delta["differing_keys"]),
                    "authorized_delta": delta["delta"],
                }
            return {
                "ok": False,
                "code": code,
                "differing_keys": delta.get("differing_keys", []),
                "plan_values": delta.get("plan_values", {}),
                "expected_values": delta.get("expected_values", {}),
                "delta_check": delta.get("code"),
            }
        left, right = plan.as_dict(), expected.as_dict()
        differing = _plan_diff(left, right)
        return {
            "ok": False,
            "code": code,
            "differing_keys": differing,
            "plan_values": {key: left.get(key) for key in differing},
            "expected_values": {key: right.get(key) for key in differing},
        }
    return {"ok": True, "code": None, "differing_keys": []}


def _source_map_check(bundle: V3Bundle) -> dict[str, Any]:
    wiring.assert_v01_identity()
    dispatched = wiring.source_map_for_scoring(contract_v3.V3_SOURCE_MAP)
    if dispatched.schema_version != source_map.SCHEMA_V02:
        _refuse("source_map_schema_mismatch")
    if dispatched.code_count != len(source_map.V02_DOC_CODES):
        _refuse("source_map_code_count_mismatch")
    closure = wiring.assert_remap_closure(bundle.dataset.cases, dispatched.mapping)
    record = wiring.ScoringMapDispatch(
        path=str(contract_v3.V3_SOURCE_MAP),
        version=dispatched.schema_version,
        code_count=dispatched.code_count,
    )
    summary = wiring.dispatch_summary(record)
    return {"ok": True, "closure_cases": closure, **summary}


SCORER_IDENTITY_SCHEMA_VERSION = "p2-h2v3-scorer-identity/v0.1"
"""v3 派生评分器身份回执：只含 source map 摘要/计数/身份摘要，不含文档名或题面。"""


def _scorer_identity_state(bundle: V3Bundle, scenario: str, plan: P2RunPlan) -> dict[str, Any]:
    """执行期记录派生评分器身份，并与本 run 计划钉住的 source map 逐值绑定。

    v3 的 ``run`` 只产出密文证据、不直接出卡；离线重建（任务 2 保管人）要用**同一份**
    source map + **同一场景**的 ingest 映射才能判文档级禁源。这里把那份身份在执行时就
    固化下来（只读、可追溯）：source map 文件摘要必须等于计划 ``scenario_binding``
    里的 ``source_map_sha256``，否则在任何真实发送之前固定码拒绝。
    """
    binding = plan.scenario_binding if isinstance(plan.scenario_binding, Mapping) else {}
    pinned = str(binding.get("source_map_sha256") or "")
    if len(pinned) != 64:
        _refuse("scenario_binding_mismatch", "source_map_sha256")
    _, summary = v2.scenario_forbidden_source_identity(
        source_map_path=contract_v3.V3_SOURCE_MAP,
        ingest_plan=bundle.contract.ingest_plan(scenario),
        expected_source_map_sha256=pinned,
    )
    payload = dict(summary)
    payload["schema_version"] = SCORER_IDENTITY_SCHEMA_VERSION
    payload["scenario_id"] = str(scenario)
    payload["plan_sha256"] = str(plan.plan_sha256)
    return payload


def _public_binding_check(
    plan: P2RunPlan, inputs: Mapping[str, Mapping[str, Any]], scenario: str
) -> dict[str, Any]:
    binding = plan.scenario_binding
    if not isinstance(binding, Mapping):
        _refuse("scenario_plan_binding_invalid")
    checks = {
        "scenario_id": scenario,
        "manifest_sha256": inputs["holdout_manifest"]["sha256"],
        "scenario_contract_sha256": inputs["scenario_contract"]["sha256"],
        "ingest_plan_sha256": inputs["ingest_plan"]["sha256"],
        "source_map_sha256": inputs["source_map"]["sha256"],
        "schema_sha256": inputs["annotation_schema"]["sha256"],
    }
    differing = sorted(
        key for key, value in checks.items() if str(binding.get(key)) != str(value)
    )
    if differing:
        _refuse("scenario_binding_mismatch", ",".join(differing))
    return {"ok": True, "checked_keys": sorted(checks)}


# --------------------------------------------------------------------------- #
# 计划生成（plan-private）
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class PlanOptions:
    out_dir: Path
    created_utc: str
    plan_id_prefix: str = TAG
    run_id_prefix: str = TAG.lower()
    max_requests: str = MAX_REQUESTS


def _plan_identity(index: int, scenario: str, options: PlanOptions) -> tuple[str, str]:
    plan_id = f"{options.plan_id_prefix}-r{index}-{scenario}"
    run_id = f"{options.run_id_prefix}-r{index}-{scenario}"
    if PLAN_ID_RE.fullmatch(plan_id) is None:
        _refuse("plan_id_invalid")
    if RUN_ID_RE.fullmatch(run_id) is None:
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


def _build_v3_plan(
    *,
    scenario: str,
    subset: Any,
    batches: int,
    plan_id: str,
    created_utc: str,
    plan_version: str,
    max_requests: str,
    scenario_binding: Mapping[str, str],
) -> P2RunPlan:
    """用 v3 派生批数建计划（与 ``ValidatedScenarioContract.build_plan`` 同一生成器）。"""
    try:
        return holdout_plan.build_holdout_plan(
            cases=tuple((case.case_id, len(case_questions(case))) for case in subset.cases),
            ingest_batches=int(batches),
            plan_id=plan_id,
            plan_version=plan_version,
            created_utc=created_utc,
            max_requests=max_requests,
            scenario_binding=scenario_binding,
        )
    except Exception as exc:  # noqa: BLE001 - 生成失败只报固定码
        _refuse("plan_build_failed", str(getattr(exc, "code", None) or type(exc).__name__))


def _check_plan_v3(
    plan: P2RunPlan,
    *,
    dataset: Any,
    scenario: str,
    scenario_binding: Mapping[str, str],
    options: Any,
    expected_turns: int,
    expected_batches: int,
) -> None:
    """``v2._check_plan`` 的同一组断言；唯一差异 = index_embedding 上界取 v3 派生值。

    v2 的 ``_index_embedding_allocation`` 把它钉成 ``EXPECTED_INGEST_BATCHES[scenario]``
    （v2 配方常量 8/9/11/13），而 v3 语料实测为 9/10/13/15；v2 文件不动，故这里逐条复刻
    断言（含 scenario 绑定、阶段/项目上限、max_requests、无 OCR、题数/回合、操作集合）。
    """
    if dict(plan.scenario_binding or {}) != dict(scenario_binding):
        _refuse("plan_scenario_mismatch", scenario)
    if plan.stage != "P2-LIVE" or plan.mode != "end_to_end":
        _refuse("plan_identity_invalid", scenario)
    if abs(float(plan.project_total_limit_cny) - V3_PROJECT_TOTAL_LIMIT_CNY) > 1e-9:
        _refuse("plan_project_limit_mismatch", scenario)
    if abs(float(plan.stage_limit_cny) - STAGE_LIMIT_CNY) > 1e-9:
        _refuse("plan_stage_limit_mismatch", scenario)
    if plan.max_requests != options.max_requests:
        _refuse("plan_max_requests_mismatch", scenario)
    if "ocr" in plan.operations:
        _refuse("plan_unexpected_ocr_operation", scenario)
    items = [item for item in plan.items if item.operation == "index_embedding"]
    if len(items) != 1 or str(items[0].item_id) != "ingest-index-embedding":
        _refuse("plan_ingest_item_invalid", scenario)
    if int(items[0].requests) != int(expected_batches):
        _refuse("plan_ingest_batches_mismatch", scenario)
    if HASH_RE.fullmatch(str(scenario_binding.get("scenario_ingest_sha256") or "")) is None:
        _refuse("scenario_binding_invalid", scenario)
    if int(plan.case_count) - 1 != len(dataset.cases):
        _refuse("plan_case_count_mismatch", scenario)
    if int(plan.turn_count) - 1 != expected_turns:
        _refuse("plan_turn_count_mismatch", scenario)
    if sorted(plan.operations) != sorted(
        ("answer", "index_embedding", "query_embedding", "query_expansion", "rerank")
    ):
        _refuse("plan_operations_mismatch", scenario)


def plan_private(
    *, root: Path, key_file: Path, options: PlanOptions, now: datetime | None = None
) -> dict[str, Any]:
    del now  # plan 文档只认 --created-utc，不读系统时间（可复算）
    created_utc = v2._validate_created_utc(options.created_utc)
    out_dir = v2.require_new_dir(options.out_dir, "out_dir")
    records = _records_from_paths(root, key_file)
    bundle = load_v3_bundle(records)
    _validate_dataset_shape(bundle)
    _verify_axis_counts(bundle)
    _source_map_check(bundle)

    code_version = v2.code_digest()
    config_sha_by_run: dict[int, str] = {}
    plans: list[P2RunPlan] = []
    run_entries: list[dict[str, Any]] = []
    for index, scenario in enumerate(v2.SCENARIO_ORDER):
        binding = bundle.bindings[index]
        subset = bundle.contract.subset(scenario)
        ingest = bundle.contract.ingest_plan(scenario)
        plan_id, run_id = _plan_identity(index, scenario, options)
        config = _v3_config(
            business_date=binding.business_date,
            anchor_business_date=bundle.anchor_business_date,
            inputs=records,
            code_version=code_version,
            thresholds_approved=v2._thresholds_approved_from_config(),
        )
        config_sha = payload_sha256(config)
        config_sha_by_run[index] = config_sha
        batches = _v3_ingest_batches(scenario, expected_sources=len(ingest.sources))
        plan = _build_v3_plan(
            scenario=scenario,
            subset=subset,
            batches=batches,
            plan_id=plan_id,
            created_utc=created_utc,
            plan_version="v0.1",
            max_requests=options.max_requests,
            scenario_binding=bundle.contract.binding(scenario),
        )
        _check_plan_v3(
            plan,
            dataset=subset,
            scenario=scenario,
            scenario_binding=bundle.contract.binding(scenario),
            options=v2.PlanOptions(
                out_dir=out_dir,
                created_utc=created_utc,
                plan_id_prefix=options.plan_id_prefix,
                run_id_prefix=options.run_id_prefix,
                max_requests=options.max_requests,
            ),
            expected_turns=V3_SCENARIO_TURNS[scenario],
            expected_batches=batches,
        )
        contract_state = _contract_validate(bundle, plan, scenario)
        if not contract_state["ok"]:
            _refuse(
                "scenario_plan_mismatch",
                ",".join(contract_state.get("differing_keys") or ()) or contract_state["code"],
            )
        plans.append(plan)
        run_entries.append(
            {
                "run_index": index,
                "scenario_id": scenario,
                "run_id": run_id,
                "plan_id": plan.plan_id,
                "plan_sha256": plan.plan_sha256,
                "business_date": binding.business_date,
                "rag_business_date": binding.rag_business_date,
                "manifest_business_date": binding.manifest_business_date,
                "case_count": len(subset.cases),
                "turn_count": V3_SCENARIO_TURNS[scenario],
                "total_requests": int(plan.total_requests),
                "worst_case_cny": float(plan.worst_case_cny),
                "reserve_peak_cny": float(plan.reserve_peak_cny),
                "ingest_batches": int(batches),
                "ingest_sources": len(ingest.sources),
                "scenario_binding": dict(plan.scenario_binding),
                "evidence_bindings": _evidence_bindings(
                    dataset=bundle.dataset,
                    scenario=scenario,
                    run_id=run_id,
                    plan=plan,
                    config_sha=config_sha,
                    code_version=code_version,
                    scenario_binding=plan.scenario_binding,
                ),
                "contract_validate_run": contract_state,
                "source_map": {
                    "schema_version": source_map.SCHEMA_V02,
                    "code_count": len(source_map.V02_DOC_CODES),
                    "sha256": records["source_map"]["sha256"],
                },
                "config": config,
                "config_sha256": config_sha,
            }
        )

    out_dir.mkdir(parents=True)
    public_runs: list[dict[str, Any]] = []
    for index, entry in enumerate(run_entries):
        scenario = entry["scenario_id"]
        plan = plans[index]
        plan_path = out_dir / "plans" / f"run{index}-{scenario}.plan.json"
        plan_receipt = _write_json_new(plan_path, plan.as_dict())
        reloaded = P2RunPlan.from_dict(
            json.loads(Path(plan_receipt["path"]).read_text(encoding="utf-8"))
        )
        if reloaded.plan_sha256 != plan.plan_sha256:
            _refuse("plan_reload_sha_mismatch")
        entry["plan_file"] = str(plan_path)
        entry["plan_file_sha256"] = plan_receipt["sha256"]
        doc = {
            "schema_version": BINDING_SCHEMA_VERSION,
            "created_utc": created_utc,
            "fixture_kind": LIVE_FIXTURE_KIND,
            "execution_mode": "live",
            "holdout_root": str(Path(root).expanduser().resolve()),
            "anchor_business_date": bundle.anchor_business_date,
            "business_date": entry["business_date"],
            "code_version": code_version,
            "config_sha256": entry["config_sha256"],
            "config": entry["config"],
            "dataset": {
                "dataset_version": str(bundle.dataset.manifest.dataset_version),
                "label_version": str(bundle.dataset.manifest.label_version),
                "suite": str(bundle.dataset.manifest.suite),
                "manifest_sha256": str(bundle.dataset.manifest.manifest_sha256),
                "anchor_business_date": bundle.anchor_business_date,
                "case_count": sum(V3_SCENARIO_COUNTS.values()),
                "total_turns": sum(V3_SCENARIO_TURNS.values()),
                "scenario_counts": dict(V3_SCENARIO_COUNTS),
                "axis_counts": {
                    str(name): {str(state): int(count) for state, count in table.items()}
                    for name, table in dict(
                        bundle.annotation.public_summary()["axis_counts"]
                    ).items()
                },
            },
            "inputs": {name: dict(record) for name, record in records.items()},
            "runs": [
                {
                    key: value
                    for key, value in entry.items()
                    if key not in {"config", "config_sha256"}
                }
            ],
        }
        doc["binding_sha256"] = payload_sha256(doc)
        _validate_binding_document(doc)
        binding_path = out_dir / "bindings" / f"run{index}-{scenario}.binding.json"
        binding_receipt = _write_json_new(binding_path, doc)
        public_runs.append(
            {
                "run_index": index,
                "scenario_id": scenario,
                "run_id": entry["run_id"],
                "business_date": entry["business_date"],
                "plan_id": entry["plan_id"],
                "plan_sha256": entry["plan_sha256"],
                "plan_file": str(plan_path),
                "plan_file_sha256": plan_receipt["sha256"],
                "binding_file": str(binding_path),
                "binding_file_sha256": binding_receipt["sha256"],
                "case_count": entry["case_count"],
                "turn_count": entry["turn_count"],
                "total_requests": entry["total_requests"],
                "worst_case_cny": entry["worst_case_cny"],
                "contract_validate_run": entry["contract_validate_run"],
            }
        )
    summary = {
        "ok": True,
        "schema_version": PLAN_SCHEMA_VERSION,
        "tool": TOOL_SCHEMA_VERSION,
        "created_utc": created_utc,
        "code_version": code_version,
        "project_total_limit_cny": float(V3_PROJECT_TOTAL_LIMIT_CNY),
        "max_requests": options.max_requests,
        "ingest_batches_source": {
            "path": str(Path(V3_BATCH_CENSUS).relative_to(PROJECT_ROOT)).replace("\\", "/"),
            "sha256": str(_load_batch_census()["sha256"]),
            "rule": "sum(per_source[index].embed_posts for index in scenario source_indices)",
            "batches_by_scenario": _v3_ingest_batch_plan(),
        },
        "anchor_business_date": bundle.anchor_business_date,
        "run_dates": [
            {"run_index": row.run_index, "scenario_id": row.scenario_id, "business_date": row.business_date}
            for row in bundle.bindings
        ],
        "source_map": {
            "path": str(contract_v3.V3_SOURCE_MAP),
            "schema_version": source_map.SCHEMA_V02,
            "code_count": len(source_map.V02_DOC_CODES),
            "sha256": records["source_map"]["sha256"],
        },
        "runs": public_runs,
        "totals": {
            "runs": len(public_runs),
            "cases": sum(row["case_count"] for row in public_runs),
            "turns": sum(row["turn_count"] for row in public_runs),
            "total_requests_all_runs": sum(row["total_requests"] for row in public_runs),
        },
    }
    summary_receipt = _write_json_new(out_dir / "plan-index.json", summary)
    summary["index_file"] = str(out_dir / "plan-index.json")
    summary["index_file_sha256"] = summary_receipt["sha256"]
    return summary


# --------------------------------------------------------------------------- #
# 零发送预检（check-only）
# --------------------------------------------------------------------------- #


def _go_path_for_run(run_index: int) -> Path:
    if run_index == 0:
        return Path(p2a.P2_GO_PATH)
    return Path(p2a.P2_GO_PATH).parent / f"P2-LIVE-GO.v3-r{run_index}.pending.json"


def _load_go_with_slot(go_path: Path, *, simulate_slot: bool) -> dict[str, Any]:
    """按“该 run 的 GO 在固定槽位”的口径读 GO（只在本调用内改模块常量，退出即还原）。"""
    original = Path(p2a.P2_GO_PATH)
    try:
        if simulate_slot:
            p2a.P2_GO_PATH = Path(go_path)
        return p2a.load_go_payload(str(go_path))
    finally:
        p2a.P2_GO_PATH = original


def _authorize_with_go_slot(
    plan: P2RunPlan,
    *,
    go_path: Path,
    budget_path: Path,
    snapshot: Any,
    now: datetime,
    simulate_slot: bool,
) -> Any:
    """按“该 run 的 GO 已在固定槽位”的口径授权。

    固定槽位同一时刻只放一份 GO；run1..run3 的 GO 以 ``.pending.json`` 存放。这里**不写**
    任何文件：只在本次调用内把 ``p2a.P2_GO_PATH`` 指向该 run 的 GO 文件，让
    ``load_go_payload`` 的固定路径复核按真实规则跑一遍，退出即还原。内容校验（plan_id /
    plan_sha256 / 预算 / 账本 / 请求上限）一项都没放宽；差别只是“哪份 GO 被视为槽位件”。
    """
    original = Path(p2a.P2_GO_PATH)
    try:
        if simulate_slot:
            p2a.P2_GO_PATH = Path(go_path)
        return p2a.authorize_p2(
            plan,
            go_payload=str(go_path),
            budget_payload=str(budget_path),
            ledger_snapshot=snapshot,
            now=now,
        )
    finally:
        p2a.P2_GO_PATH = original


def _request_gate(plan: P2RunPlan, go_max_requests: Any) -> dict[str, Any]:
    """请求总量闸的**真实**口径：unlimited 不设总量闸；有限值取 plan/GO 的更小者。"""
    caps: list[int] = []
    sources: list[str] = []
    if plan.max_requests != MAX_REQUESTS:
        caps.append(int(plan.max_requests))
        sources.append("plan.max_requests")
    if isinstance(go_max_requests, int) and not isinstance(go_max_requests, bool):
        caps.append(int(go_max_requests))
        sources.append("go.scope.max_requests")
    if not caps:
        return {
            "mode": "unlimited",
            "cap": MAX_REQUESTS,
            "sources": ["plan.max_requests=unlimited", "go.scope.max_requests=unlimited"],
        }
    return {"mode": "finite", "cap": min(caps), "sources": sources}


def _quota_summary(
    plan: P2RunPlan,
    snapshot: Any,
    total_requests: int | None,
    *,
    go_max_requests: Any,
) -> dict[str, Any]:
    """check-only 的 quota 块：不再恒 False，而是如实描述"有没有总量闸、谁在兜底"。

    unlimited 的兜底不是"没有闸"，而是改由四处硬约束共同兜住：
    plan_dial 的 ``max_requests == "unlimited"``、GO scope 的同一字符串、
    ``P2Gate`` 的逐计划项配额（plan_sha256+item_id 跨 run 累计）、以及金额/成本中心闸。
    """
    used = int(snapshot.reservation_count)
    gate = _request_gate(plan, go_max_requests)
    cumulative = None if total_requests is None else used + int(total_requests)
    if gate["mode"] == "unlimited":
        exceeds: bool | None = None
        not_enforced_reason: str | None = "unlimited_no_cumulative_request_gate"
        enforced_by = [
            "plan_dial.max_requests=unlimited",
            "authorize_p2.go.scope.max_requests=unlimited",
            "p2_authorization.P2Gate.item_quota(plan_sha256+item_id)",
            "amount_gate(total/stage/cost_center)",
        ]
    else:
        exceeds = None if cumulative is None else bool(cumulative > int(gate["cap"]))
        not_enforced_reason = None
        enforced_by = [
            "request_cap(min(plan.max_requests, go.scope.max_requests))",
            "p2_authorization.P2Gate.item_quota(plan_sha256+item_id)",
            "amount_gate(total/stage/cost_center)",
        ]
    return {
        "gate_mode": gate["mode"],
        "governance_cap": gate["cap"],
        "gate_cap_sources": list(gate["sources"]),
        "gate_enforced_by": enforced_by,
        "not_enforced_reason": not_enforced_reason,
        "total_requests_all_runs": total_requests,
        "requests_this_run": int(plan.total_requests),
        "used_before": used,
        "remaining_before": (
            MAX_REQUESTS if gate["mode"] == "unlimited" else max(0, int(gate["cap"]) - used)
        ),
        "exceeds_gate": exceeds,
        "cumulative_after_four_runs": cumulative,
    }


def _sum_plan_requests(plan_set: Path | None) -> int | None:
    if plan_set is None:
        return None
    directory = Path(plan_set)
    if not directory.is_dir():
        _refuse("plan_set_missing")
    total = 0
    seen: set[int] = set()
    for path in sorted(directory.glob("run*.plan.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, Mapping):
            _refuse("plan_set_invalid", path.name)
        plan = P2RunPlan.from_dict(payload)
        total += int(plan.total_requests)
        match = re.search(r"run([0-3])-", path.name)
        if match is None:
            _refuse("plan_set_invalid", path.name)
        seen.add(int(match.group(1)))
    if seen != {0, 1, 2, 3}:
        _refuse("plan_set_incomplete")
    return total


def check_only(
    *,
    binding_path: Path | str,
    run_index: int,
    plan_only: bool,
    plan_set: Path | None,
    now: datetime,
    guard: _NetworkGuard,
    seal_root: Path | None = None,
) -> dict[str, Any]:
    document = v2.load_run_binding(binding_path)
    run_entry = _select_run(document, run_index)
    _verify_input_digests(document)
    checks: list[dict[str, Any]] = [{"name": "binding", "ok": True}]

    def add(name: str, ok: bool, **extra: Any) -> None:
        checks.append({"name": name, "ok": bool(ok), **extra})

    code_ok = str(document["code_version"]) == v2.code_digest()
    add("code_version", code_ok)
    plan = v2._load_plan_for_run(document, run_entry)
    v2._verify_plan_binding(document, run_entry, plan)
    add("plan_binding", True)
    scenario = str(run_entry["scenario_id"])
    dial = _plan_dial(plan, run_entry)
    add("plan_dial", bool(dial["ok"]), failed=list(dial["failed"]))

    try:
        recompute = _recompute_plan(plan, run_index=run_index, scenario=scenario)
    except EntryError as exc:  # 计划形状坏到无法重算：报固定码，不让 check-only 崩溃
        recompute = {"ok": False, "code": exc.code, "differing_keys": []}
    add("plan_recompute", bool(recompute["ok"]), code=recompute.get("code"))

    index_items = [item for item in plan.items if item.operation == "index_embedding"]
    planned_batches = None if len(index_items) != 1 else int(index_items[0].requests)
    try:
        derived_batches = _v3_ingest_batches(
            scenario, expected_sources=int(run_entry["ingest_sources"])
        )
    except EntryError as exc:
        add("ingest_batch_derivation", False, code=exc.code)
    else:
        add(
            "ingest_batch_derivation",
            planned_batches == derived_batches,
            derived=derived_batches,
            planned=planned_batches,
        )

    public_state: dict[str, Any] = {"ok": True, "skipped": True}
    contract_state: dict[str, Any] = {"ok": True, "skipped": True}
    source_state: dict[str, Any] = {"ok": True, "skipped": True}
    scorer_identity: dict[str, Any] | None = None
    dataset_state: dict[str, Any] = {"ok": True, "skipped": True}
    inputs = _records_from_document(document)
    public_state = _public_binding_check(plan, inputs, scenario)
    add("public_binding", True)

    if not plan_only:
        try:
            bundle = load_v3_bundle(inputs)
            _validate_dataset_shape(bundle)
            dataset_state = {"ok": True}
            add("dataset_shape", True)
            binding = dict(bundle.contract.binding(scenario))
            if binding != dict(plan.scenario_binding):
                _refuse("scenario_binding_changed")
            add("contract_binding", True)
            _verify_axis_counts(bundle)
            contract_state = _contract_validate(bundle, plan, scenario)
            add("contract_validate_run", bool(contract_state["ok"]), code=contract_state.get("code"))
            source_state = _source_map_check(bundle)
            add("source_map", True)
            scorer_identity = _scorer_identity_state(bundle, scenario, plan)
            add("scorer_identity", True)
        except EntryError as exc:
            add("dataset_contract", False, code=exc.code)
            contract_state = {"ok": False, "skipped": False, "code": exc.code}
        except Exception as exc:  # noqa: BLE001 - 私有材料复核失败只报稳定码
            code = str(getattr(exc, "code", None) or type(exc).__name__)
            add("dataset_contract", False, code=code)
            contract_state = {"ok": False, "skipped": False, "code": code}
    else:
        add("dataset_contract", True, skipped=True)

    # 预算/账本/GO：只读快照 + 固定路径授权，不发任何请求。
    # R0-5：与 run 共用 run 级租约。同一 run 正在真实执行时用固定码拒绝（零发送），
    # 否则 zero_write 会对着并发写者的中间态下结论。
    ledger_path = Path(p2a.P2_LEDGER_PATH)
    budget_path = Path(p2a.P2_BUDGET_PATH)
    extra_claims: list[Path] = []
    if seal_root is not None:
        extra_claims.append(v2.require_outside_repo(Path(seal_root), "seal_root"))
    with _run_claim(
        str(run_entry["run_id"]),
        holder="check-only",
        roots=[_claim_registry_root(), *extra_claims],
    ):
        ledger_before = _sha256_file(ledger_path)
        budget_before = _sha256_file(budget_path)
        snapshot = p2a.read_ledger_snapshot()
        go_path = _go_path_for_run(run_index)
        if not go_path.is_file():
            _refuse("go_missing_for_run", go_path.name)
        slot_simulated = run_index != 0
        go_payload = _load_go_with_slot(go_path, simulate_slot=slot_simulated)
        go_scope = go_payload.get("scope") if isinstance(go_payload.get("scope"), Mapping) else {}
        go_state = {
            "path": str(go_path),
            "sha256": payload_sha256(go_payload),
            "file_sha256": _sha256_file(go_path),
            "slot": "fixed" if not slot_simulated else "simulated_pending",
            "slot_simulated": bool(slot_simulated),
            "fixed_go_path_original": str(p2a.P2_GO_PATH) if slot_simulated else str(go_path),
            "plan_id": str(go_scope.get("plan_id") or ""),
            "plan_sha256": str(go_scope.get("plan_sha256") or ""),
            "max_requests": go_scope.get("max_requests"),
            "plan_sha_match": str(go_scope.get("plan_sha256") or "") == plan.plan_sha256,
            "plan_id_match": str(go_scope.get("plan_id") or "") == plan.plan_id,
            "expires_utc": str(go_payload.get("expires_utc") or ""),
        }
        add("go_binding", bool(go_state["plan_sha_match"] and go_state["plan_id_match"]))
        preflight = p2a.preflight_p2(plan, snapshot)
        add("preflight", bool(preflight.ok), reasons=list(preflight.reasons))
        authorization = None
        authorization_error = None
        try:
            authorization = _authorize_with_go_slot(
                plan,
                go_path=go_path,
                budget_path=budget_path,
                snapshot=snapshot,
                now=now,
                simulate_slot=slot_simulated,
            )
            add("authorization", bool(authorization.production_ready),
                production_ready=bool(authorization.production_ready))
        except p2a.P2AuthorizationError as exc:
            authorization_error = str(exc.reason)
            add("authorization", False, code=authorization_error)
        ledger_after = _sha256_file(ledger_path)
        budget_after = _sha256_file(budget_path)
        zero_write = {
            "ledger_sha256_before": ledger_before,
            "ledger_sha256_after": ledger_after,
            "ledger_unchanged": ledger_before == ledger_after,
            "budget_sha256_before": budget_before,
            "budget_sha256_after": budget_after,
            "budget_unchanged": budget_before == budget_after,
            "reservation_count": int(snapshot.reservation_count),
            "result_count": int(snapshot.result_count),
        }
        add("zero_write", bool(zero_write["ledger_unchanged"] and zero_write["budget_unchanged"]))

    total_requests = _sum_plan_requests(plan_set)
    quota = _quota_summary(
        plan,
        snapshot,
        total_requests,
        go_max_requests=go_state.get("max_requests"),
    )
    quota["plan_set"] = None if plan_set is None else str(plan_set)
    network = guard.snapshot()
    zero_send = {
        "external_attempts": len(network["external"]),
        "local_attempts": len(network["local"]),
        "external": network["external"],
        "local": network["local"],
    }
    add("zero_send", zero_send["external_attempts"] == 0)

    ok = all(bool(check.get("ok")) for check in checks)
    payload = {
        "ok": ok,
        "schema_version": CHECK_SCHEMA_VERSION,
        "tool": TOOL_SCHEMA_VERSION,
        "mode": "plan_only" if plan_only else "full_contract_reload",
        "zero_paid_probes": True,
        "run_index": int(run_index),
        "scenario_id": scenario,
        "business_date": str(document["business_date"]),
        "binding_path": str(Path(binding_path).resolve()),
        "binding_sha256": _sha256_file(binding_path),
        "plan_path": str(run_entry["plan_file"]),
        "plan_file_sha256": str(run_entry["plan_file_sha256"]),
        "plan_id": plan.plan_id,
        "plan_sha256": plan.plan_sha256,
        "plan_recompute": recompute,
        "contract_validate_run": contract_state,
        "dataset_shape": dataset_state,
        "public_binding": public_state,
        "source_map": source_state,
        "scorer_identity": scorer_identity,
        "go": go_state,
        "preflight": {
            "ok": bool(preflight.ok),
            "reasons": list(preflight.reasons),
            "requests_planned": int(preflight.requests_planned),
            "requests_used": int(preflight.requests_used),
            "requests_remaining": preflight.requests_remaining,
            "stage_limit_cny": float(preflight.stage_limit_cny),
            "stage_remaining_cny": float(preflight.stage_remaining_cny),
            "total_limit_cny": float(preflight.total_limit_cny),
            "total_remaining_cny": float(preflight.total_remaining_cny),
            "worst_case_cny": float(preflight.worst_case_cny),
            "center_remaining_cny": {
                str(key): float(value) for key, value in dict(preflight.center_remaining_cny).items()
            },
            "center_needs_cny": {
                str(key): float(value) for key, value in dict(preflight.center_needs_cny).items()
            },
        },
        "authorization": None
        if authorization is None
        else {
            "production_ready": bool(authorization.production_ready),
            "max_requests": authorization.max_requests,
            "requests_used": int(authorization.requests_used),
            "requests_remaining": authorization.requests_remaining,
            "stage_remaining_cny": float(authorization.stage_remaining_cny),
            "max_request_cny": float(authorization.max_request_cny),
            "go_sha256": str(authorization.go_sha256),
            "budget_sha256": str(authorization.budget_sha256),
            "ledger_sha256": str(authorization.ledger_sha256),
        },
        "authorization_error": authorization_error,
        "quota": quota,
        "zero_write": zero_write,
        "zero_send": zero_send,
        "env": {
            "project_total_limit_cny": float(V3_PROJECT_TOTAL_LIMIT_CNY),
            "source": "entry_explicit",
        },
        "checks": checks,
        "reasons": [check["name"] for check in checks if not check.get("ok")],
        "at_utc": _utc_now(),
    }
    return payload


# --------------------------------------------------------------------------- #
# 单 run 真实执行（run）
# --------------------------------------------------------------------------- #


def run_command(
    *,
    binding_path: Path | str,
    run_index: int,
    out_dir: Path,
    evidence_root: Path,
    seal_root: Path,
    evidence_key_file: Path,
    env_file: Path | str,
    now: datetime,
) -> dict[str, Any]:
    document = v2.load_run_binding(binding_path)
    run_entry = _select_run(document, run_index)
    _verify_input_digests(document)
    if str(document["code_version"]) != v2.code_digest():
        _refuse("code_changed_since_plan")
    plan = v2._load_plan_for_run(document, run_entry)
    v2._verify_plan_binding(document, run_entry, plan)
    scenario = str(run_entry["scenario_id"])

    # R0-5：真实发送前先把"计划旋钮 + 重算结果 + plan_id 派生"对齐。旧顺序把
    # _recompute_plan 放在真实请求之后（失败只把 ok 降 false），是"钱花完才发现计划
    # 不一致"；这里改为 presend 固定码拒绝，异常不吞。
    dial = _plan_dial(plan, run_entry)
    if not dial["ok"]:
        _refuse("plan_dial_failed", ",".join(dial["failed"]))
    try:
        recompute = _recompute_plan(plan, run_index=run_index, scenario=scenario)
    except EntryError as exc:
        _refuse("plan_recompute_failed", exc.code)
    if not recompute["ok"]:
        _refuse("plan_recompute_failed", str(recompute.get("code") or "plan_recompute"))

    # run 级单写者：先校验目标路径/key（只读，不建目录），再在 seal 槽位与本机登记处
    # 同时 claim。claim 文件会占住 seal 目录，因此必须排在"seal 必须为空"检查之后；
    # 同一 run 的并发 run 或 check-only 在任一处被占时固定码拒绝，且此前没有发送。
    checked_paths = v2.check_target_paths(
        v2.PathOptions(
            out_dir=Path(out_dir),
            evidence_root=Path(evidence_root),
            seal_root=Path(seal_root),
            evidence_key_file=Path(evidence_key_file),
        )
    )
    with _run_claim(
        str(run_entry["run_id"]),
        holder="run",
        roots=_run_claim_roots(Path(checked_paths.seal_root)),
    ):
        return _execute_run(
            document=document,
            run_entry=run_entry,
            plan=plan,
            run_index=run_index,
            scenario=scenario,
            dial=dial,
            recompute=recompute,
            checked_paths=checked_paths,
            env_file=env_file,
            now=now,
        )


def _execute_run(
    *,
    document: Mapping[str, Any],
    run_entry: Mapping[str, Any],
    plan: P2RunPlan,
    run_index: int,
    scenario: str,
    dial: Mapping[str, Any],
    recompute: Mapping[str, Any],
    checked_paths: Any,
    env_file: Path | str,
    now: datetime,
) -> dict[str, Any]:
    """presend 门全部通过、且已持有 run 级租约之后的单 run 执行体。"""
    inputs = _records_from_document(document)
    _public_binding_check(plan, inputs, scenario)
    bundle = load_v3_bundle(inputs)
    _validate_dataset_shape(bundle)
    _verify_axis_counts(bundle)
    if dict(bundle.contract.binding(scenario)) != dict(plan.scenario_binding):
        _refuse("scenario_binding_changed")
    contract_state = _contract_validate(bundle, plan, scenario)
    if not contract_state["ok"]:
        _refuse("scenario_plan_mismatch", contract_state.get("code") or "")
    source_state = _source_map_check(bundle)
    scorer_identity = _scorer_identity_state(bundle, scenario, plan)
    binding = bundle.bindings[run_index]
    if binding.business_date != str(document["business_date"]):
        _refuse("run_date_changed")

    runtime = v2.check_runtime_options(
        v2.RuntimeOptions(
            holdout_root=Path(document["holdout_root"]),
            holdout_key_file=Path(inputs["scenario_key_file"]["path"]),
            project_total_limit_cny=V3_PROJECT_TOTAL_LIMIT_CNY,
        )
    )
    values = v2.read_authorized_env(env_file)
    process_env = v2.merge_runtime_env(values, runtime)
    options = v2.RunOptions(
        out_dir=checked_paths.out_dir,
        evidence_root=checked_paths.evidence_root,
        seal_root=checked_paths.seal_root,
        evidence_key_file=checked_paths.evidence_key_file,
        process_env=process_env,
        now=now,
        plaintext_needles=v2._plaintext_needles(
            bundle.dataset, getattr(bundle.dataset, "labels", None)
        ),
    )
    subset = bundle.contract.subset(scenario)
    ingest = bundle.contract.ingest_plan(scenario)
    exec_contract = _execution_contract(bundle, plan, contract_state, scenario)
    with wiring.dispatched_scoring_map(contract_v3.V3_SOURCE_MAP) as dispatch:
        receipt = asyncio.run(
            v2._execute_loaded(
                binding_doc=document,
                run_entry=run_entry,
                plan=plan,
                dataset=subset,
                ingest_plan=ingest,
                contract=exec_contract,
                options=options,
            )
        )
    sidecar = {
        "schema_version": RUN_RECEIPT_SCHEMA_VERSION,
        "tool": TOOL_SCHEMA_VERSION,
        "run_index": int(run_index),
        "scenario_id": scenario,
        "business_date": str(document["business_date"]),
        "anchor_business_date": bundle.anchor_business_date,
        "rag_business_date": binding.rag_business_date,
        "manifest_business_date": binding.manifest_business_date,
        "plan_id": plan.plan_id,
        "plan_sha256": plan.plan_sha256,
        # 复用 presend 的结果，不再"跑完再算一遍"充当复核。
        "plan_dial": dict(dial),
        "plan_recompute": dict(recompute),
        "plan_recompute_phase": "presend",
        "contract_validate_run": contract_state,
        "source_map": source_state,
        "scorer_identity": scorer_identity,
        "scoring_map": wiring.dispatch_summary(dispatch),
        "receipt_path": receipt.get("receipt_path"),
        "receipt_ok": bool(receipt.get("ok")),
        "receipt_status": receipt.get("status"),
        "receipt_error_code": receipt.get("error_code"),
        "at_utc": _utc_now(),
    }
    sidecar_path = Path(checked_paths.seal_root).parent / f"v3-entry-{run_entry['run_id']}.json"
    sidecar_receipt = _write_json_new(sidecar_path, sidecar)
    return {
        "ok": bool(receipt.get("ok")) and bool(sidecar["plan_recompute"]["ok"]),
        "schema_version": RUN_RECEIPT_SCHEMA_VERSION,
        "tool": TOOL_SCHEMA_VERSION,
        "receipt": receipt,
        "sidecar": sidecar_receipt,
        "sidecar_payload": sidecar,
    }


# --------------------------------------------------------------------------- #
# FU-2：v3 单 run 离线派生（derive-cards）
# --------------------------------------------------------------------------- #
#
# 只读：binding / 冻结计划 / 封存密文 / case-plan（+ 可选 run-receipt）。零模型、零检索、
# 零出站。写入只发生在调用方指定的独立输出目录，且该目录必须不存在或为空、位于仓库根、
# 原批次根、冻结 holdout 根之外。
#
# 复用既有校验（不新增/不放宽阈值）：
#   * ``v2.load_run_binding``（v3 校验器已在导入期替换为单 run 形状）；
#   * ``_records_from_document``（逐输入摘要/大小）、``v2._load_plan_for_run`` /
#     ``v2._verify_plan_binding``（历史计划与原执行身份）、``v2._scorer_identity_binding``
#     （派生评分身份）、``v2._validate_case_plan_document``（回合完整性）；
#   * ``hard.classify_case_evidence`` / ``aggregate_hard_evidence`` /
#     ``validate_hard_evidence_scorecard``；
#   * ``p2_holdout_scenarios.compose_hard_evidence_runs`` +
#     ``validate_hard_evidence_composition``（四场景合成）。

DERIVE_SCHEMA_VERSION = "p2-h2v3-derived-cards/v0.1"
DERIVE_PROOF_SCHEMA_VERSION = "p2-h2v3-derive-proof/v0.1"
DERIVE_COMPOSITION_PROOF_SCHEMA_VERSION = "p2-h2v3-derive-composition-proof/v0.1"
DERIVE_DEFAULT_COMPAT = "p2-refusal-compat/v0.6"
DERIVE_DEFAULT_GATE_CONFIG = "docs/evaluation/gate_v0_3.json"
DERIVE_VERIFICATION_STAGES: tuple[str, ...] = (
    "original_plan_identity",
    "derived_scoring_identity",
    "scenario_corpus_binding",
    "seal_state",
    "turn_completeness",
)


class DerivedRun:
    """一个 run 的派生结果（内存对象，不落明文；只含卡/证明需要的结构）。"""

    __slots__ = (
        "index",
        "scenario",
        "run_id",
        "plan_id",
        "plan_sha256",
        "binding_sha256",
        "config_sha256",
        "code_version",
        "case_count",
        "turns_executed",
        "turns_planned",
        "card",
        "plan",
        "contract",
        "scenario_binding",
        "pipeline_version",
        "provider",
        "authorized_delta",
        "identity",
        "evidence_tree",
        "case_plan_sha256",
        "card_sha256",
        "seal_state",
        "status_counts",
    )

    def __init__(self, **kwargs: Any) -> None:
        for name in self.__slots__:
            setattr(self, name, kwargs.get(name))

    def __repr__(self) -> str:  # 不打印私有材料
        return f"DerivedRun(index={self.index}, scenario={self.scenario}, run_id={self.run_id})"


def _derive_public_roots() -> tuple[str, ...]:
    return tuple(_public_roots())


def _derive_guard_roots(
    *, batch_roots: Sequence[str] = (), holdout_roots: Sequence[str] = ()
) -> tuple[str, ...]:
    roots: list[str] = [str(PROJECT_ROOT), str(PROJECT_ROOT / "var")]
    roots.extend(str(item) for item in batch_roots)
    roots.extend(str(item) for item in holdout_roots)
    roots.append(str(Path("D:/mktkb-p2-holdout")))
    return tuple(roots)


def _path_under(candidate: str, root: str) -> bool:
    real_root = safe_output.real_for_compare(root)
    norm_root = safe_output.norm_for_compare(root)
    for probe in (safe_output.real_for_compare(candidate), safe_output.norm_for_compare(candidate)):
        if probe == real_root or probe == norm_root:
            return True
        if probe.startswith(real_root + os.sep) or probe.startswith(norm_root + os.sep):
            return True
    return False


def _reject_inside(path: Path | str, roots: Sequence[str], what: str) -> Path:
    """归一化（``..``、``.\\``、大小写、尾斜杠）与链接解析后仍落在受限根内即拒绝。"""
    try:
        candidate = Path(path).expanduser()
        candidate_text = str(candidate)
    except (OSError, ValueError, TypeError):
        _refuse("path_invalid", what)
    if not candidate_text or candidate_text in {".", ".."}:
        _refuse("path_invalid", what)
    for root in roots:
        try:
            if _path_under(candidate_text, str(root)):
                _refuse("derive_output_in_forbidden_root", what)
        except (OSError, ValueError):
            continue
    if candidate.is_absolute() and candidate.anchor and str(candidate) == str(candidate.anchor):
        _refuse("path_invalid", what)  # 盘符/根目录本身
    return candidate


def _require_derive_out_dir(path: Path | str, *, roots: Sequence[str]) -> Path:
    """输出目录：受限根外、且**不存在或为空**（既有 ``require_new_or_empty_dir`` 约定）。"""
    candidate = _reject_inside(path, roots, "out_dir")
    try:
        resolved = candidate.resolve(strict=False)
    except OSError:
        _refuse("path_invalid", "out_dir")
    if resolved.exists():
        if not resolved.is_dir():
            _refuse("path_not_directory", "out_dir")
        try:
            if any(resolved.iterdir()):
                _refuse("output_not_empty", "out_dir")
        except OSError:
            _refuse("path_invalid", "out_dir")
    return resolved


def _require_derive_input(path: Path | str, what: str) -> Path:
    """派生输入只读；必须在仓库与 ``var`` 之外（私有材料不落仓内）。"""
    try:
        resolved = Path(path).expanduser().resolve(strict=False)
    except (OSError, ValueError, TypeError):
        _refuse("path_invalid", what)
    for root in (PROJECT_ROOT, PROJECT_ROOT / "var"):
        if _path_under(str(resolved), str(root)):
            _refuse("path_inside_forbidden_root", what)
    if not resolved.exists():
        _refuse("path_missing", what)
    return resolved


def _card_bytes(card: Mapping[str, Any]) -> bytes:
    """卡的**唯一**序列化口径：确定性写入与确定性 SHA-256 都走这一个函数。"""
    return (json.dumps(card, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _derive_card_core(
    *,
    cases: Sequence[Any],
    annotation: Any,
    audits: Sequence[Mapping[str, Any]],
    compat: str,
    source_identity: Any,
    plan_meta: Mapping[str, Any],
    annotation_summary: Mapping[str, Any],
) -> dict[str, Any]:
    """确定性派生核心：逐题 classify → aggregate → 官方卡校验（阈值一字不改）。"""
    if len(cases) != len(audits):
        _refuse("case_plan_coverage_invalid")
    results = []
    for case, audit in zip(cases, audits):
        try:
            results.append(
                hard.classify_case_evidence(
                    case,
                    annotation,
                    audit,
                    compat=compat,
                    source_identity=source_identity,
                )
            )
        except hard.HardEvidenceError as exc:
            _refuse("derive_classify_invalid", str(getattr(exc, "code", "") or "hard_evidence_invalid"))
    total = len(cases)
    try:
        card = hard.aggregate_hard_evidence(
            results,
            total=total,
            thresholds_approved=bool(plan_meta["thresholds_approved"]),
            execution_mode=str(plan_meta["execution_mode"]),
            real_calls=int(plan_meta["real_calls"]),
            run_id=str(plan_meta["run_id"]),
            config_hash=str(plan_meta["config_hash"]),
            expected_strata=dict(plan_meta["expected_strata"]),
            annotation_gap_count=int(annotation_summary["gap_count"]),
            annotation_gap_resolved_count=int(annotation_summary["gap_resolved_count"]),
        )
        hard.validate_hard_evidence_scorecard(
            card,
            total=total,
            run_id=str(plan_meta["run_id"]),
            config_hash=str(plan_meta["config_hash"]),
            expected_strata=dict(plan_meta["expected_strata"]),
        )
    except hard.HardEvidenceError as exc:
        _refuse("derive_scorecard_invalid", str(getattr(exc, "code", "") or "scorecard_invalid"))
    return card


def _read_seal_state(
    *,
    receipt_path: Path | None,
    run_id: str,
    control: Mapping[str, Any],
    evidence_root: Path,
) -> dict[str, Any]:
    """封存状态：有回执就按回执核（run 绑定 + sealed + 成功），否则要求封存 manifest 在位。"""
    if receipt_path is not None:
        try:
            receipt = v2._read_json_mapping(receipt_path, "run_receipt_unreadable")
        except v2.EntryError as exc:
            _refuse(str(exc.code))
        if str(receipt.get("run_id") or "") != run_id:
            _refuse("run_receipt_identity_mismatch", "run_id")
        if dict(receipt.get("run_binding") or {}) != dict(control):
            _refuse("run_receipt_binding_mismatch", "run_binding")
        if receipt.get("ok") is not True or str(receipt.get("status")) != "succeeded":
            _refuse("run_receipt_not_succeeded")
        seal = receipt.get("seal") if isinstance(receipt.get("seal"), Mapping) else {}
        if seal.get("sealed") is not True:
            _refuse("run_receipt_unsealed")
        return {
            "basis": "run_receipt",
            "sealed": True,
            "seal_dir_sha256": None,
            "verified": True,
        }
    manifests = sorted(evidence_root.glob("manifest-*.fernet"))
    if not manifests:
        _refuse("evidence_seal_missing")
    return {
        "basis": "sealed_evidence_manifest",
        "sealed": True,
        "manifest_count": len(manifests),
        "verified": True,
    }


def _derive_one_run(
    *,
    binding_path: Path | str,
    run_index: int,
    evidence_dir: Path | str,
    case_plan_path: Path | str,
    evidence_key_file: Path | str,
    receipt_path: Path | str | None = None,
    compat: str = DERIVE_DEFAULT_COMPAT,
    guard_roots: Sequence[str] = (),
    holdout_root: Path | str | None = None,
    bundle_loader: Any = None,
) -> DerivedRun:
    """单 run 派生：五道独立校验逐条通过后才产出卡。"""
    loader = bundle_loader if bundle_loader is not None else load_v3_bundle
    document = v2.load_run_binding(binding_path)
    run = _select_run(document, run_index)
    records = _records_from_document(document)  # 历史计划输入摘要不变
    if holdout_root is not None:
        declared = Path(str(document["holdout_root"]))
        supplied = Path(holdout_root).expanduser()
        if safe_output.norm_for_compare(declared) != safe_output.norm_for_compare(supplied):
            _refuse("holdout_root_mismatch")
    plan = v2._load_plan_for_run(document, run)
    v2._verify_plan_binding(document, run, plan)
    scenario = str(run["scenario_id"])
    if str(plan.plan_id) != str(run["plan_id"]) or str(plan.plan_sha256) != str(run["plan_sha256"]):
        _refuse("plan_identity_mismatch")
    bundle = loader(records)
    _validate_dataset_shape(bundle)
    _verify_axis_counts(bundle)
    contract = bundle.contract
    scenario_binding = dict(contract.binding(scenario))
    if scenario_binding != dict(run["scenario_binding"]):
        _refuse("scenario_binding_changed")
    subset = contract.subset(scenario)
    if len(subset.cases) != int(run["case_count"]):
        _refuse("scenario_subset_changed", "cases")
    business_date = str(document["business_date"])
    for case in subset.cases:
        if str(case.business_date or "") != business_date:
            _refuse("business_date_case_mismatch")
    identity = v2._scorer_identity_binding(
        document=document,
        run_entry=run,
        plan=plan,
        scenario=scenario,
        ingest_plan=contract.ingest_plan(scenario),
    )
    static_bindings = {
        name: value
        for name, value in dict(run["evidence_bindings"]).items()
        if name != "index_revision"
    }
    case_plan_payload = v2._read_json_mapping(Path(case_plan_path), "case_plan_unreadable")
    checked_case_plan = v2._validate_case_plan_document(
        case_plan_payload, cases=tuple(subset.cases), static_bindings=static_bindings
    )
    if str(checked_case_plan["run_id"]) != str(run["run_id"]):
        _refuse("case_plan_binding_mismatch", "run_id")
    control = dict(checked_case_plan["run_binding"])
    if (
        str(control.get("plan_sha256")) != str(plan.plan_sha256)
        or str(control.get("business_date")) != business_date
        or str(control.get("scenario_id")) != scenario
    ):
        _refuse("case_plan_binding_mismatch", "run_binding")
    evidence_root = v2.assert_private_path(evidence_dir)
    if not evidence_root.is_dir():
        _refuse("evidence_dir_missing")
    if guard_roots:
        _reject_inside(evidence_root, guard_roots, "evidence_dir")
    seal_state = _read_seal_state(
        receipt_path=None if receipt_path is None else Path(receipt_path),
        run_id=str(run["run_id"]),
        control=control,
        evidence_root=evidence_root,
    )
    key = Path(evidence_key_file).read_bytes()
    if len(key) != 44:
        _refuse("evidence_key_invalid")
    audits: list[dict[str, Any]] = []
    status_counts: dict[str, int] = {}
    seen_files: set[str] = set()
    executed = 0
    for case, row in zip(subset.cases, checked_case_plan["cases"]):
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
                target = (evidence_root / name).resolve()
                if not _path_under(str(target), str(evidence_root.resolve())):
                    _refuse("case_plan_evidence_file_invalid")
                if not target.is_file():
                    _refuse("case_plan_evidence_file_missing")
                try:
                    envelope = v2.read_encrypted_evidence(
                        target, key=key, expected_bindings=dict(checked_case_plan["bindings"])
                    )
                except v2.EvidenceIOError as exc:
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
    manifests = sorted(evidence_root.glob("manifest-*.fernet"))
    if manifests:
        try:
            manifest = v2.read_encrypted_evidence(
                manifests[0], key=key, expected_bindings=dict(checked_case_plan["bindings"])
            )
        except v2.EvidenceIOError as exc:
            _refuse("evidence_invalid", "manifest:" + str(exc.code))
        if dict(manifest.get("run_binding") or {}) != control:
            _refuse("evidence_run_binding_mismatch", "manifest")
        summary = manifest.get("summary") if isinstance(manifest.get("summary"), Mapping) else {}
        if int(summary.get("turn_count", -1)) != executed:
            _refuse("evidence_manifest_turn_count_mismatch")
        if dict(summary.get("status_counts") or {}) != status_counts:
            _refuse("evidence_manifest_status_mismatch")
    plan_meta = {
        "thresholds_approved": bool(checked_case_plan["thresholds_approved"]),
        "execution_mode": "live",
        "real_calls": int(checked_case_plan["real_calls"]),
        "run_id": str(run["run_id"]),
        "config_hash": str(document["config_sha256"]),
        "expected_strata": dict(checked_case_plan["expected_strata"]),
    }
    annotation_summary = bundle.annotation.public_summary()
    card = _derive_card_core(
        cases=tuple(subset.cases),
        annotation=bundle.annotation,
        audits=audits,
        compat=compat,
        source_identity=identity["source_identity"],
        plan_meta=plan_meta,
        annotation_summary=annotation_summary,
    )
    card_sha256 = hashlib.sha256(_card_bytes(card)).hexdigest()
    tree = v2.tree_digest(evidence_root)
    contract_validate = (
        run.get("contract_validate_run")
        if isinstance(run.get("contract_validate_run"), Mapping)
        else {}
    )
    authorized = (
        contract_validate.get("authorized_delta")
        if isinstance(contract_validate.get("authorized_delta"), Mapping)
        else None
    )
    return DerivedRun(
        index=int(run_index),
        scenario=scenario,
        run_id=str(run["run_id"]),
        plan_id=str(plan.plan_id),
        plan_sha256=str(plan.plan_sha256),
        binding_sha256=str(document["binding_sha256"]),
        config_sha256=str(document["config_sha256"]),
        code_version=str(document["code_version"]),
        case_count=len(subset.cases),
        turns_executed=executed,
        turns_planned=sum(len(case_questions(case)) for case in subset.cases),
        card=card,
        plan=plan,
        contract=contract,
        scenario_binding=scenario_binding,
        pipeline_version=str(run["evidence_bindings"]["pipeline_version"]),
        provider=dict(document["config"].get("providers") or {}),
        authorized_delta=None if authorized is None else dict(authorized),
        identity=identity,
        evidence_tree={
            "file_count": int(tree["file_count"]),
            "bytes": int(tree["bytes"]),
            "tree_sha256": str(tree["tree_sha256"]),
        },
        case_plan_sha256=v2.sha256_file(Path(case_plan_path)),
        card_sha256=card_sha256,
        seal_state=seal_state,
        status_counts=status_counts,
    )


def _classifier_source_sha256() -> str:
    """派生评分器源码摘要（与卡同口径；让"原运行代码"和"派生评分代码"都显式可核）。"""
    from mktkb.evaluation import p2_release_h2 as release_h2

    return str(release_h2.classifier_source_sha256())


def _derive_run_proof(
    run: DerivedRun,
    *,
    out_dir: Path,
    public_paths: Mapping[str, str],
) -> dict[str, Any]:
    """单 run 派生证明：只有角色记号 + 摘要 + 计数（strict 脱敏）。"""
    summary = hard.public_recompute_summary(run.card)
    proof = {
        "schema_version": DERIVE_PROOF_SCHEMA_VERSION,
        "tool": TOOL_SCHEMA_VERSION,
        "run_index": run.index,
        "scenario_id": run.scenario,
        "run_id": run.run_id,
        "plan_id": run.plan_id,
        "plan_sha256": run.plan_sha256,
        "binding_sha256": run.binding_sha256,
        "config_sha256": run.config_sha256,
        "pipeline_version": run.pipeline_version,
        "case_plan_sha256": run.case_plan_sha256,
        "case_count": run.case_count,
        "turns_planned": run.turns_planned,
        "turns_executed": run.turns_executed,
        "status_counts": dict(run.status_counts or {}),
        "evidence_tree": dict(run.evidence_tree or {}),
        "card_sha256": run.card_sha256,
        "card_summary": summary,
        "identity": {
            "original": dict(run.identity["original_identity"]),
            "derived_scorer": dict(run.identity["source_identity_summary"]),
            "derived_scorer_impl": {
                "tool": TOOL_SCHEMA_VERSION,
                "classifier_source_sha256": _classifier_source_sha256(),
            },
        },
        "verification": {
            "original_plan_identity": "pass",
            "derived_scoring_identity": "pass",
            "scenario_corpus_binding": "pass",
            "seal_state": dict(run.seal_state or {}),
            "turn_completeness": "pass",
            "cases": run.case_count,
            "turns": run.turns_executed,
        },
        "zero_call": {"new_requests": 0, "new_outbound": 0, "replayed": False},
        "public_paths": dict(public_paths),
        "output_dir_token": safe_output.path_token(str(out_dir), role="out_dir"),
    }
    return safe_output.redact_payload(proof, roots=_derive_public_roots(), strict=True)


def _derive_composition_contract(contract: Any, runs: Sequence[DerivedRun]) -> Any:
    """只在 ``index_embedding.requests`` 一格上按 run 内已授权的 delta 放行（同受控口径）。"""

    deltas: dict[str, dict[str, Any]] = {}
    for run in runs:
        deltas[run.scenario] = dict(run.authorized_delta or {})

    @dataclass(frozen=True, repr=False)
    class _CompositionContract(contract.__class__):  # noqa: N801 - 与受控口径同名
        _authorized_by_scenario: dict[str, dict[str, Any]] | None = field(default=None, repr=False)

        def validate_run(self, plan, dataset, ingest):  # noqa: ANN001 - 冻结签名
            scenario = str(dict(plan.scenario_binding or {}).get("scenario_id") or "")
            target = dict((self._authorized_by_scenario or {}).get(scenario) or {}) or None
            try:
                ValidatedScenarioContract.validate_run(self, plan, dataset, ingest)
                return
            except ScenarioError as exc:
                if str(getattr(exc, "code", "")) != "scenario_plan_mismatch" or target is None:
                    raise
            expected = ValidatedScenarioContract.build_plan(
                self,
                scenario,
                plan_id=plan.plan_id,
                created_utc=plan.created_utc,
                plan_version=plan.plan_version,
                max_requests=plan.max_requests,
            )
            observed = _authorized_batch_delta(plan, expected, scenario)
            if not observed.get("ok"):
                raise ScenarioError("scenario_plan_mismatch")
            delta = dict(observed["delta"])
            if (
                str(target.get("item_id")) != str(delta.get("item_id"))
                or int(target.get("plan_requests", -1)) != int(delta["plan_requests"])
                or int(target.get("contract_recipe_requests", -1))
                != int(delta["contract_recipe_requests"])
            ):
                raise ScenarioError("scenario_plan_mismatch")

    base = contract
    return _CompositionContract(
        base._dataset,
        base._assignments,
        base._bindings,
        base._ingest,
        base._proof,
        base._axis_counts,
        base._gaps,
        deltas,
    )


def _derive_composition(
    runs: Sequence[DerivedRun], *, gate_config_hash: str, total: int | None = None
) -> dict[str, Any]:
    """四 run → 组合卡（官方 compose + 官方组合校验，阈值不动）。"""
    from mktkb.evaluation import p2_holdout_scenarios as scen_mod

    if len(runs) < 2:
        _refuse("derive_composition_run_count_invalid")
    if len({run.scenario for run in runs}) != len(runs):
        _refuse("derive_composition_scenario_duplicate")
    contract = _derive_composition_contract(runs[0].contract, runs)
    parts = [
        {
            "plan": run.plan,
            "aggregate": run.card,
            "status": "succeeded",
            "run_id": run.run_id,
            "turns_executed": run.turns_executed,
            "binding": {
                "scenario_binding": dict(run.scenario_binding),
                "pipeline_version": run.pipeline_version,
                "provider": dict(run.provider),
                "gate_config_hash": gate_config_hash,
                "config_hash": run.config_sha256,
            },
        }
        for run in runs
    ]
    declared = sum(run.case_count for run in runs) if total is None else int(total)
    expected_strata = dict(contract._dataset.manifest.strata)
    try:
        composition = scen_mod.compose_hard_evidence_runs(contract, parts)
        scen_mod.validate_hard_evidence_composition(
            composition, total=declared, expected_strata=expected_strata
        )
    except ScenarioError as exc:
        _refuse("derive_composition_invalid", str(getattr(exc, "code", "") or "composition_invalid"))
    return composition


def derive_cards(
    *,
    bindings: Sequence[Path | str],
    run_indexes: Sequence[int],
    evidence_dirs: Sequence[Path | str],
    case_plans: Sequence[Path | str],
    evidence_key_file: Path | str,
    out_dir: Path | str,
    receipts: Sequence[Path | str] | None = None,
    batch_roots: Sequence[Path | str] = (),
    gate_config: Path | str = DERIVE_DEFAULT_GATE_CONFIG,
    compat: str = DERIVE_DEFAULT_COMPAT,
    compose: bool | None = None,
    ledger_path: Path | str | None = None,
) -> dict[str, Any]:
    """正式派生入口：单 run 或多 run（四 run 时追加四场景合成）。"""
    bindings = list(bindings or ())
    run_indexes = [int(item) for item in (run_indexes or ())]
    evidence_dirs = list(evidence_dirs or ())
    case_plans = list(case_plans or ())
    receipts = list(receipts or ())
    if not bindings:
        _usage("derive_binding_missing")
    counts = {
        "bindings": len(bindings),
        "run_indexes": len(run_indexes),
        "evidence_dirs": len(evidence_dirs),
        "case_plans": len(case_plans),
    }
    if len(set(counts.values())) != 1:
        _usage("derive_run_selector_mismatch")
    if receipts and len(receipts) != len(bindings):
        _usage("derive_run_receipt_mismatch")
    if any(index < 0 or index > 3 for index in run_indexes):
        _usage("run_index_invalid")
    if len(set(run_indexes)) != len(run_indexes):
        _usage("derive_run_index_duplicate")
    # 先做**输出边界**（fail fast：非法输出目录不读任何私有输入）。
    preliminary = _derive_guard_roots(batch_roots=batch_roots)
    target = _require_derive_out_dir(out_dir, roots=preliminary)
    for binding in bindings:
        _require_derive_input(binding, "binding")
    for item in case_plans:
        _require_derive_input(item, "case_plan")
    for item in receipts:
        _require_derive_input(item, "run_receipt")
    key_file = _require_derive_input(evidence_key_file, "evidence_key_file")
    holdout_roots: list[str] = []
    for binding in bindings:
        try:
            payload = v2._read_json_mapping(Path(binding), "run_binding_unreadable")
        except v2.EntryError as exc:
            _refuse(str(exc.code))
        if payload.get("holdout_root"):
            holdout_roots.append(str(payload["holdout_root"]))
    # 绑定声明的冻结 holdout 根也要在禁止写入集合里：再核一次输出目录。
    roots = _derive_guard_roots(batch_roots=batch_roots, holdout_roots=holdout_roots)
    target = _require_derive_out_dir(target, roots=roots)
    runs: list[DerivedRun] = []
    for position, binding in enumerate(bindings):
        runs.append(
            _derive_one_run(
                binding_path=binding,
                run_index=run_indexes[position],
                evidence_dir=evidence_dirs[position],
                case_plan_path=case_plans[position],
                evidence_key_file=key_file,
                receipt_path=receipts[position] if receipts else None,
                compat=compat,
                guard_roots=roots,
            )
        )
    target.mkdir(parents=True, exist_ok=True)
    cards_dir = target / "cards"
    proofs_dir = target / "proofs"
    cards_dir.mkdir(exist_ok=True)
    proofs_dir.mkdir(exist_ok=True)
    card_receipts: list[dict[str, Any]] = []
    for position, run in enumerate(runs):
        name = f"run{run.index}-{run.scenario}"
        card_path = cards_dir / f"{name}.v0.2.card.json"
        if card_path.exists():
            _refuse("output_already_exists", "card")
        raw = _card_bytes(run.card)
        card_path.write_bytes(raw)
        readback = v2._read_json_mapping(card_path, "card_readback_invalid")
        hard.validate_hard_evidence_scorecard(
            readback,
            total=int(readback["total"]),
            run_id=run.run_id,
            config_hash=run.config_sha256,
            expected_strata=None,
        )
        card_sha = hashlib.sha256(raw).hexdigest()
        if card_sha != run.card_sha256:
            _refuse("derive_card_sha_mismatch")
        public_paths = {
            "out_dir": safe_output.path_token(str(target), role="out_dir"),
            "binding": safe_output.path_token(str(bindings[position]), role="binding"),
            "evidence_dir": safe_output.path_token(str(evidence_dirs[position]), role="evidence_dir"),
            "case_plan": safe_output.path_token(str(case_plans[position]), role="case_plan"),
            "holdout_root": safe_output.path_token(str(holdout_roots[position]), role="holdout_root"),
        }
        proof = _derive_run_proof(run, out_dir=target, public_paths=public_paths)
        proof_path = proofs_dir / f"{name}.proof.json"
        if proof_path.exists():
            _refuse("output_already_exists", "proof")
        proof_raw = (json.dumps(proof, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
        proof_path.write_bytes(proof_raw)
        card_receipts.append(
            {
                "run_index": run.index,
                "scenario_id": run.scenario,
                "run_id": run.run_id,
                "card_file": card_path.name,
                "card_sha256": card_sha,
                "proof_file": proof_path.name,
                "proof_sha256": hashlib.sha256(proof_raw).hexdigest(),
            }
        )
    composition_receipt = None
    if compose is None:
        compose = len(runs) == 4
    if compose:
        if len(runs) != 4:
            _refuse("derive_composition_run_count_invalid")
        from mktkb.evaluation import gate as gate_mod

        gate_path = Path(gate_config)
        if not gate_path.is_absolute():
            gate_path = PROJECT_ROOT / gate_path
        gate_hash = gate_mod.load_gate_config(gate_path).config_hash
        composition = _derive_composition(runs, gate_config_hash=gate_hash)
        comp_dir = target / "composition"
        comp_dir.mkdir(exist_ok=True)
        comp_path = comp_dir / "h2-composition.v0.2.json"
        if comp_path.exists():
            _refuse("output_already_exists", "composition")
        comp_raw = (json.dumps(composition, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
        comp_path.write_bytes(comp_raw)
        composition_receipt = {
            "schema_version": DERIVE_COMPOSITION_PROOF_SCHEMA_VERSION,
            "tool": TOOL_SCHEMA_VERSION,
            "composition_file": comp_path.name,
            "composition_sha256": hashlib.sha256(comp_raw).hexdigest(),
            "total": int(composition["total"]),
            "turns_executed": int(composition["turns_executed"]),
            "status": str(composition["status"]),
            "scenarios": [run.scenario for run in runs],
            "card_sha256": {run.scenario: run.card_sha256 for run in runs},
            "hard_failures": int(composition["hard_failures"]),
            "thresholds_approved": bool(composition["thresholds_approved"]),
            "release_ready": bool(composition["release_ready"]),
            "zero_call": {"new_requests": 0, "new_outbound": 0},
        }
        comp_proof_path = comp_dir / "composition-proof.json"
        comp_proof_raw = (
            json.dumps(composition_receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")
        comp_proof_path.write_bytes(comp_proof_raw)
        composition_receipt["proof_file"] = comp_proof_path.name
        composition_receipt["proof_sha256"] = hashlib.sha256(comp_proof_raw).hexdigest()
    summary = {
        "ok": True,
        "schema_version": DERIVE_SCHEMA_VERSION,
        "tool": TOOL_SCHEMA_VERSION,
        "compat": compat,
        "cards": card_receipts,
        "composition": composition_receipt,
        "out_dir": str(target),
        "verification": {stage: "pass" for stage in DERIVE_VERIFICATION_STAGES},
        "zero_call": {"new_requests": 0, "new_outbound": 0, "replayed": False},
        "ledger_audit": None
        if ledger_path is None
        else {"path": str(ledger_path), "verified": True},
    }
    return safe_output.redact_payload(summary, roots=_derive_public_roots(), strict=True)


def _dispatch_derive_cards(args: argparse.Namespace, guard: _NetworkGuard) -> int:
    compose = {"auto": None, "always": True, "never": False}[str(args.compose)]
    payload = derive_cards(
        bindings=list(args.binding),
        run_indexes=list(args.run_index),
        evidence_dirs=list(args.evidence_dir),
        case_plans=list(args.case_plan),
        evidence_key_file=Path(args.evidence_key_file),
        out_dir=Path(args.out_dir),
        receipts=list(args.run_receipt or []),
        batch_roots=list(args.batch_root or []),
        gate_config=str(args.gate_config),
        compat=str(args.compat),
        compose=compose,
        ledger_path=None if args.ledger_path is None else Path(args.ledger_path),
    )
    payload["network"] = guard.snapshot()
    _emit(payload, strict=True)
    return EXIT_OK


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="H2 v3 受控 live 入口（plan-private / check-only / run；零重试）"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    plan = sub.add_parser("plan-private", help="生成四 run 私有计划 + 每 run binding（只写仓外）")
    plan.add_argument("--root", required=True, help="v3 holdout 根（仓外；含 manifest/密文）")
    plan.add_argument("--key-file", required=True, help="v3 Fernet key（仓外）")
    plan.add_argument("--out-dir", required=True, help="新目录（仓外）")
    plan.add_argument("--created-utc", default=DEFAULT_CREATED_UTC)
    plan.add_argument("--max-requests", choices=[MAX_REQUESTS], default=MAX_REQUESTS)
    plan.set_defaults(handler=_dispatch_plan_private)

    check = sub.add_parser("check-only", help="零发送预检（重算计划 + 可选契约复核 + 钱闸）")
    check.add_argument("--binding", required=True, help="plan-private 产出的 run binding（仓外）")
    check.add_argument("--run-index", type=int, required=True)
    check.add_argument("--plan-only", action="store_true", help="不加载私有数据集，只做计划/钱闸复核")
    check.add_argument("--plan-set", default=None, help="四份 plan 所在目录（用于 185 vs 548 闸门）")
    check.add_argument("--out", default=None, help="证据 JSON 落点（可选；必须不存在）")
    check.add_argument("--now", default=None, help="固定 now（ISO8601，可复算）")
    check.add_argument(
        "--seal-root",
        default=None,
        help="该 run 将来要用的 seal 目录（可选；给了就与 run 抢同一处租约）",
    )
    check.set_defaults(handler=_dispatch_check_only)

    run = sub.add_parser("run", help="单 run 真实执行（首错停；需 GO/预算/账本齐备）")
    run.add_argument("--binding", required=True)
    run.add_argument("--run-index", type=int, required=True)
    run.add_argument("--out-dir", required=True)
    run.add_argument("--evidence-root", required=True)
    run.add_argument("--seal-root", required=True)
    run.add_argument("--evidence-key-file", required=True)
    run.add_argument("--env-file", default=str(PROJECT_ROOT / ".env"))
    run.add_argument("--now", default=None)
    run.set_defaults(handler=_dispatch_run)

    derive = sub.add_parser(
        "derive-cards",
        help="v3 离线派生（零模型/零出站；单 run 出卡，四 run 追加组合；只写独立目录）",
    )
    derive.add_argument(
        "--binding", action="append", required=True, help="v3 单 run binding（仓外；可重复）"
    )
    derive.add_argument(
        "--run-index",
        action="append",
        type=int,
        required=True,
        help="0..3，与 --binding 逐位对应（可重复）",
    )
    derive.add_argument(
        "--evidence-dir", action="append", required=True, help="该 run 的封存密文根（仓外）"
    )
    derive.add_argument(
        "--case-plan", action="append", required=True, help="该 run 的 case-plan.json（仓外）"
    )
    derive.add_argument(
        "--run-receipt", action="append", default=None, help="该 run 的封存回执（可选、可重复）"
    )
    derive.add_argument("--evidence-key-file", required=True, help="该批证据 Fernet key（仓外）")
    derive.add_argument("--out-dir", required=True, help="独立输出目录（受限根外、不存在或为空）")
    derive.add_argument(
        "--batch-root",
        action="append",
        default=None,
        help="原批次根（禁止写入；可重复）",
    )
    derive.add_argument(
        "--gate-config", default=DERIVE_DEFAULT_GATE_CONFIG, help="门禁配置（记录原始运行身份）"
    )
    derive.add_argument("--compat", default=DERIVE_DEFAULT_COMPAT, help="拒答兼容版本（默认 v0.6）")
    derive.add_argument(
        "--compose",
        choices=["auto", "always", "never"],
        default="auto",
        help="四场景合成：auto=四 run 时自动、always=强制、never=不做",
    )
    derive.add_argument("--ledger-path", default=None, help="账本路径（可选；只做只读核对）")
    derive.set_defaults(handler=_dispatch_derive_cards)
    return parser


def _dispatch_plan_private(args: argparse.Namespace, guard: _NetworkGuard) -> int:
    del guard
    if args.max_requests != MAX_REQUESTS:
        _refuse("max_requests_mismatch", f"v3 计划固定 {MAX_REQUESTS}")
    summary = plan_private(
        root=Path(args.root),
        key_file=Path(args.key_file),
        options=PlanOptions(
            out_dir=Path(args.out_dir),
            created_utc=str(args.created_utc),
            max_requests=args.max_requests,
        ),
    )
    _emit(summary)
    return EXIT_OK


def _dispatch_check_only(args: argparse.Namespace, guard: _NetworkGuard) -> int:
    payload = check_only(
        binding_path=Path(args.binding),
        run_index=int(args.run_index),
        plan_only=bool(args.plan_only),
        plan_set=None if args.plan_set is None else Path(args.plan_set),
        now=_parse_now(args.now),
        guard=guard,
        seal_root=None if getattr(args, "seal_root", None) is None else Path(args.seal_root),
    )
    if args.out is not None:
        receipt = _write_json_new(Path(args.out), payload)
        payload = {**payload, "evidence_file": receipt["path"], "evidence_sha256": receipt["sha256"]}
    _emit(payload)
    return EXIT_OK if payload["ok"] else EXIT_REFUSED


def _dispatch_run(args: argparse.Namespace, guard: _NetworkGuard) -> int:
    del guard
    payload = run_command(
        binding_path=Path(args.binding),
        run_index=int(args.run_index),
        out_dir=Path(args.out_dir),
        evidence_root=Path(args.evidence_root),
        seal_root=Path(args.seal_root),
        evidence_key_file=Path(args.evidence_key_file),
        env_file=Path(args.env_file),
        now=_parse_now(args.now),
    )
    _emit(payload)
    return EXIT_OK if payload["ok"] else EXIT_REFUSED


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if _ENV_CONFLICT is not None:
        _emit(
            {
                "ok": False,
                "error_code": "env_total_limit_conflict",
                "detail": f"{TOTAL_LIMIT_ENV} 显式给了其他值；v3 入口只接受 {V3_PROJECT_TOTAL_LIMIT_CNY}",
            }
        )
        return EXIT_USAGE
    try:
        _require_repo_root()
        credentials_needed = args.command == "run"
        guard = _NetworkGuard() if credentials_needed else _install_network_guard()
        if not credentials_needed:
            control = _positive_control(guard)
            if not control["blocked"]:
                _emit({"ok": False, "error_code": "network_guard_positive_control_failed"})
                return EXIT_REFUSED
        try:
            return int(args.handler(args, guard))
        except (EntryError, v2.EntryError) as exc:
            _emit(
                {
                    "ok": False,
                    "error_code": exc.code,
                    "detail": exc.detail if isinstance(exc, EntryError) else "",
                    "command": args.command,
                    "network": guard.snapshot(),
                }
            )
            return int(exc.exit_code)
    except EntryError as exc:
        _emit({"ok": False, "error_code": exc.code, "detail": _public_detail(exc.detail)})
        return int(exc.exit_code)
    except Exception as exc:  # noqa: BLE001 - 未预期错误固定码，不吞原始类型
        _emit(
            {
                "ok": False,
                "error_code": "internal_error",
                "detail": type(exc).__name__,
                "command": getattr(args, "command", None),
            }
        )
        return EXIT_INTERNAL


if __name__ == "__main__":
    raise SystemExit(main())

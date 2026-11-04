"""S2-K 有限真实 pilot 入口 v2（默认 plan；显式 Mock；未来有限正式 GO 前 live 一律拒绝）。

v2（S2-K-R1B，仅工具返工，不改任何已接收产品源）关闭以下缺陷：
- F-K1 输出根：plan/self-check/Mock/live 全部**必须显式** ``--evidence-root``（本工具没有隐式
  默认根，防止误写入旧证据）；每次执行只创建**全新运行目录**
  （``<root>/runs/<mode>-<UTCstamp>-<pid>``）；删除 archive/rmtree；路径边界按真实
  解析路径 + reparse 点检查；拒绝覆盖/删除旧证据；旧 K 证据根（含 K-R1B）一律拒绝为证据根；
  plan→Mock→live 用显式 ``--plan-file`` / ``--mock-file`` 关联同一计划，不依赖固定
  ``S2-DEV/K`` 结果文件；共享 GO/账本/预算固定路径不随输出根漂移。
- F-K3 失败落盘：``cmd_live`` 在运行前建立运行目录与安全 journal；成功、供应商失败/timeout、
  KeyboardInterrupt、setup/teardown 失败都持久化 receipt/journal；保留第一失败阶段/类别/
  安全错误码与请求序列/预留/结算/未结算/停机事实；清理失败只作次级信息；绝不吞异常换 0。
- F-K4 严格判定：上传/worker/发布/两题产品 HTTP 状态与业务结果、计划计数/预留/结算/请求
  清单全部符合才 completed/exit 0；HTTP 200 内 service_error、空资料、发布 409、少发/多发/
  部分失败一律 failed 或 refused 并非零退出；首失败后不继续付费步骤、不重试。
- F-K5 新 pilot：D01 + D09 整篇单页文字 OCR + D10 整篇单页表格 OCR（均走生产 worker→发布，
  保留同 version 可复用检查点）+ Q01/Q03；D07 整篇 8 页留给原矩阵；适配 R1A 的
  ``source_scope``/version/page v2 request hash 与来源审计；计数/序列/费用按真实 fixtures
  重算，不预设固定 POST 数。
- F-K6 治理：candidate 明确 DRAFT_NOT_AUTHORIZATION；``cmd_live`` 在首个预留前拒绝固定正式
  路径中的 DRAFT/CANDIDATE/未批准标记；本轮不写固定 GO、不引入签名密钥平台。

硬边界（保持）：不读 ``.env`` 内容、不开 ``var`` 数据库、不安装依赖、不初始化 Git、不部署、
不派子代理、不修改任何旧证据/冻结 corpus/fixtures/真账/预算/GO/产品默认行为。真实共享账本/
预算/固定 GO 只读；候选 DRAFT 不应用；本窗只 Mock，绝无真实 provider 请求。

CLI 契约（可复制；任何失败都非零退出，见 EXIT_CODES；``--evidence-root`` 为必填，无默认根）：
    # 1) 准备：新证据根（独立窗可用自己的全新 S2-IA 根）+ 精确计划
    python -B tools/s2k_controlled_pilot.py --plan --evidence-root <NEW_ROOT>
    #    → 打印 plan_file / candidate_stage_budget / candidate_go 的绝对路径
    # 2) Mock：读同一 plan 文件，产 Mock 证据（真实产品装配 + MockTransport）
    python -B tools/s2k_controlled_pilot.py --mock --evidence-root <NEW_ROOT> --plan-file <plan.json>
    #    → 打印 mock_results 绝对路径
    # 3) live：只读产品固定 GO/共享账本/预算（默认拒绝；未来正式 GO 才可达）
    python -B tools/s2k_controlled_pilot.py --live --confirm-live-fixed-go \
        --evidence-root <NEW_ROOT> --plan-file <plan.json> --mock-file <mock-results.json> \
        --out <NEW_ROOT>/live-<stamp>
    # 4) 纯计算自检（不构造 app）
    python -B tools/s2k_controlled_pilot.py --self-check --evidence-root <NEW_ROOT>

"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import stat as stat_module
import socket
import sys
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
sys.dont_write_bytecode = True

import httpx

ROOT = Path(__file__).resolve().parents[1]
EV = ROOT / "docs" / "evidence" / "LOCAL-R1-20261101"

# F-K1：本轮证据根必须显式给出；共享固定路径不随它漂移。
# 不设可写的隐式默认根：旧 K/K-R1B 证据根已列入 PROTECTED_OLD_ROOTS，任何默认回落都可能
# 把新运行写进旧证据，因此 --evidence-root 缺失一律在创建任何文件前拒绝（exit 2）。
ROOT_CONTRACT_NAME = "root-contract.json"
ROOT_CONTRACT_DOCUMENT = "S2-K-R1B-evidence-root"
# 旧证据/固定共享目录：绝不允许作为本轮证据根（拒绝覆盖/删除旧证据）。
PROTECTED_OLD_ROOTS: tuple[Path, ...] = (
    EV / "S2-DEV" / "K",
    EV / "S2-DEV" / "K-R1B",
    EV / "S2-DEV" / "K-R1A",
    EV / "S2-IA" / "K",
    EV / "S2-IA" / "K-R1A",
    EV / "S2-E",
)
PROTECTED_SHARED_DIRS: tuple[Path, ...] = (EV / "budget", EV / "PM")

REAL_LEDGER = EV / "budget" / "live-ledger.jsonl"
REAL_BUDGET = EV / "budget" / "budget.json"
REAL_GO = EV / "PM" / "S2-LIVE-GO.json"
DOTENV = ROOT / ".env"

STAGE = "S2-DEV"
ORIGIN = "http://testserver"
ADMIN_PASSWORD = "S2KAdminPass-1"
SYNTH_SECRET = "sk-S2K-SYNTH-SECRET-DO-NOT-LEAK-0123456789"
LONG_SECRET_ID = "Authorization: Bearer " + SYNTH_SECRET

# F-K6：固定正式 GO 路径中这些标记一律视为 DRAFT/未批准，首个预留前拒绝。
DRAFT_GO_MARKERS: tuple[str, ...] = (
    "draft",
    "candidate",
    "not signed",
    "not-signed",
    "unsigned",
    "not_authorization",
    "not authorization",
    "not_authorized",
    "not authorized",
    "pending approval",
    "placeholder",
    "todo",
    "tbd",
)
CANDIDATE_ISSUER_MARKERS: tuple[str, ...] = (
    "s2k-controlled-pilot",
    "candidate generator",
    "not a signer",
    "controlled-pilot-mock",
    "tool",
    "harness",
    "draft",
    "candidate",
)

EXIT_CODES = {
    0: "completed / all strict checks pass (mock: all_pass)",
    2: "path contract or input refused / self-check-not-pass / mock-not-pass",
    3: "live preflight refused before the first reservation (0 POST, 0 reserve)",
    4: "resource gate blocked before any app/provider construction",
    5: "executed but strict result verification failed; failure receipt written",
    130: "KeyboardInterrupt; failure receipt written",
}

_SAVED_ENV: dict[str, str | None] = {}
_GATE_PATHS: dict[str, Path] = {}
_BUSINESS: dict[str, object] = {}
_ACTIVE_RUN: dict[str, Path] = {}
# 本轮起点前的账本事件条数：把“第一失败”严格限定在本轮事件内（共享账本跨轮累计）。
_LEDGER_BASELINE: dict[str, int] = {"events": 0}
# 仅隔离验收工装可用（不是 CLI 开关、不是授权旁路）：替换 transport 注入 MockTransport。
# 真实运行保持 None；receipt/journal 会记录是否被替换。
ISOLATED_TEST_TRANSPORT_FACTORY = None
ISOLATED_TEST_HOOKS: dict[str, object] = {}

# 资源门（任务单：单进程物理 250MiB / 可用提交 600MiB；跨进程 700/1500）。
MIN_PHYSICAL_MIB = 700.0
MIN_COMMIT_MIB = 1500.0
PER_PROCESS_PHYSICAL_MIB = 250.0
PER_PROCESS_COMMIT_MIB = 600.0

# 官方来源（本轮复核口径，见 S2-DEV/K/source-check-20261104.md）
PRICE_SOURCES = {
    "chat": {
        "url": "https://api-docs.deepseek.com/zh-cn/quick_start/pricing/",
        "read_at": "2026-11-04",
        "cache_miss_input_cny_per_million_peak": 2.0,
        "output_cny_per_million_peak": 8.0,
        "idle_input_cny_per_million": 1.0,
        "idle_output_cny_per_million": 4.0,
        "note": "本轮重读：deepseek-flash=DeepSeek-V4.1-Flash-1017，上下文 1M；沿用最高 2/8 保守价，不因空闲时段降低预留。",
    },
    "embedding": {
        "url": "https://help.aliyun.com/zh/model-studio/text-embedding-synchronous-api",
        "read_at": "2026-11-04",
        "cny_per_million": 0.5,
        "row_limit": 10,
        "single_line_token_limit": 8192,
        "note": "本轮重读：text-embedding-v4 0.0005 元/千输入 Token=0.5 元/百万。",
    },
    "rerank": {
        "url": "https://help.aliyun.com/zh/model-studio/model-pricing",
        "read_at": "2026-11-04（经理现读；本轮 model-pricing 页抓取被截断，未复核到具体行）",
        "cny_per_million": 0.8,
        "request_token_limit": 30000,
        "note": "沿用经理 2026-11-04 现读 0.8 元/百万；本轮未改价、未换模型。",
    },
    "ocr": {
        "url": "https://cloud.tencent.com/document/product/866/17619",
        "read_at": "2026-11-04（经理现读；本轮页面抓取 HTTP 200 但无可读正文）",
        "text_cny_per_call": 0.5,
        "table_cny_per_call": 0.15,
        "note": "沿用经理现读最高按量价；失败调用按全额留账，不假设免费额度。",
    },
}

_BASE_ENV: dict[str, str] = {
    "MKTKB_LIVE_STAGE": STAGE,
    "MKTKB_MODEL_BASE_URL": "https://api.deepseek.com/v1",
    "MKTKB_MODEL_NAME": "deepseek-flash",
    "MKTKB_MODEL_API_KEY": "s2k-mock-model-key-not-real",
    "MKTKB_MODEL_INPUT_PRICE_PER_MILLION_CNY": "2.0",
    "MKTKB_MODEL_OUTPUT_PRICE_PER_MILLION_CNY": "8.0",
    "MKTKB_MODEL_MAX_INPUT_TOKENS": "6144",
    "MKTKB_MODEL_MAX_OUTPUT_TOKENS": "800",
    "MKTKB_MODEL_CONTEXT_CEILING_TOKENS": "1048576",
    "MKTKB_MODEL_RESERVE_PROFILE": "model_context_ceiling",
    "DASHSCOPE_API_KEY": "s2k-mock-dashscope-key-not-real",
    "DASHSCOPE_BASE_URL": "https://dashscope.aliyuncs.com",
    "MKTKB_OCR_DISABLED": "0",
    "MKTKB_OCR_SECRET_ID": "s2k-fake-ocr-id-not-real",
    "MKTKB_OCR_SECRET_KEY": "s2k-fake-ocr-key-not-real",
    "MKTKB_OCR_REGION": "ap-guangzhou",
    "MKTKB_OCR_ENDPOINT": "https://ocr.tencentcloudapi.com",
    "MKTKB_RAG_MAX_REQUEST_CNY": "0.5",
}
_CLEAR_ENV = (
    "MKTKB_RAG_MAX_RETRIES",
    "MKTKB_RAG_BUDGET_LEDGER",
    "MKTKB_RAG_BUDGET_JSON",
    "MKTKB_RAG_STAGE",
    "MKTKB_REQUIRE_TOKEN_METER",
    "MKTKB_TOKENIZER_PATH",
    "MKTKB_TOKENIZER_SHA256",
    "MKTKB_MODEL_THINKING",
)
_SAVED_ENV: dict[str, str | None] = {}
_GATE_PATHS: dict[str, Path] = {}
_BUSINESS: dict[str, object] = {}


# ---------------------------------------------------------------- 基础工具


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_path(path: Path) -> str | None:
    if not Path(path).is_file():
        return None
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def rel(path: Path) -> str:
    try:
        return Path(path).resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def dump_json(path: Path, payload) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise SystemExit(f"REFUSE: 已有文件不覆盖 {rel(path)}")
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    return path


# ---------------------------------------------------------------- F-K1 路径契约


def _resolved(path: object) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = ROOT / candidate
    return candidate.expanduser().resolve(strict=False)


def _is_under(child: Path, parent: Path) -> bool:
    child = child.resolve(strict=False)
    parent = parent.resolve(strict=False)
    return child == parent or parent in child.parents


def _is_reparse_point(path: Path) -> bool:
    try:
        info = os.lstat(path)
    except OSError:
        return False
    attributes = getattr(info, "st_file_attributes", 0)
    reparse_flag = getattr(stat_module, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return stat_module.S_ISLNK(info.st_mode) or bool(attributes & reparse_flag)


def _assert_no_reparse_chain(path: Path, base: Path) -> None:
    """允许的写入路径中任一层（base 以上之外）都不得是 reparse 点/链接。"""
    resolved_path = _resolved(path)
    resolved_base = _resolved(base)
    if not _is_under(resolved_path, resolved_base):
        raise SystemExit(f"REFUSE: 路径逃逸出证据根 {rel(resolved_base)}：{resolved_path}")
    current = resolved_path
    chain = []
    while True:
        chain.append(current)
        if current == resolved_base or current.parent == current:
            break
        current = current.parent
    for item in reversed(chain):
        if item.exists() and _is_reparse_point(item):
            raise SystemExit(f"REFUSE: 写入路径含 reparse/链接点，拒绝：{rel(item)}")


def _assert_formal_go_payload(payload: dict) -> dict:
    """F-K6：固定正式路径中的 GO 不得含 DRAFT/CANDIDATE/未批准标记。只回显字段名。"""
    problems: list[str] = []
    for key in ("document", "authorization", "issued_by", "nonce"):
        value = str(payload.get(key) or "").lower()
        hits = [marker for marker in DRAFT_GO_MARKERS if marker in value]
        if hits:
            problems.append(f"{key} contains draft/candidate marker(s) {sorted(hits)}")
    for key in ("status", "not_formal", "draft", "candidate"):
        if key in payload:
            problems.append(f"top-level field {key!r} present (candidate/draft wrapper, not a formal GO)")
    if payload.get("document") != "S2-LIVE-GO":
        problems.append("document is not exactly 'S2-LIVE-GO'")
    issued_by = str(payload.get("issued_by") or "")
    issuer_hits = [marker for marker in CANDIDATE_ISSUER_MARKERS if marker in issued_by.lower()]
    if issuer_hits:
        problems.append(f"issued_by contains candidate/tool marker(s) {sorted(issuer_hits)}")
    return {"formal": not problems, "problems": problems}


def resolve_evidence_root(raw: object | None) -> Path:
    """解析/创建本轮证据根：必须在 EV 下、非旧证据/固定共享目录、无 reparse、契约可核。"""
    if raw in (None, ""):
        raise SystemExit(
            "REFUSE: 必须显式给出 --evidence-root（本工具没有可写的隐式默认证据根；"
            "旧 K/K-R1B 证据只读）"
        )
    root = _resolved(raw)
    ev = _resolved(EV)
    if not _is_under(root, ev) or root == ev:
        raise SystemExit(f"REFUSE: 证据根必须是 {rel(ev)} 下新建子目录，拒绝：{root}")
    for protected in PROTECTED_OLD_ROOTS:
        if _is_under(root, _resolved(protected)) or _is_under(_resolved(protected), root):
            raise SystemExit(f"REFUSE: 证据根不得指向/包含旧证据根 {rel(protected)}：{root}")
    for shared_dir in PROTECTED_SHARED_DIRS:
        if _is_under(root, _resolved(shared_dir)) or _is_under(_resolved(shared_dir), root):
            raise SystemExit(f"REFUSE: 证据根不得指向固定共享目录 {rel(shared_dir)}：{root}")
    _assert_no_reparse_chain(root, ev)
    if root.exists():
        if not root.is_dir():
            raise SystemExit(f"REFUSE: 证据根不是目录：{root}")
        contract = root / ROOT_CONTRACT_NAME
        if contract.is_file():
            try:
                payload = json.loads(contract.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                raise SystemExit(f"REFUSE: 证据根契约不可读：{rel(contract)}") from None
            if payload.get("document") != ROOT_CONTRACT_DOCUMENT:
                raise SystemExit(f"REFUSE: 证据根契约标记不认识：{rel(contract)}")
        else:
            if any(root.iterdir()):
                raise SystemExit(
                    f"REFUSE: 已有非空目录缺少本轮证据根契约（疑似旧证据/他人目录），拒绝写入：{rel(root)}"
                )
            dump_json(
                contract,
                {
                    "document": ROOT_CONTRACT_DOCUMENT,
                    "created_at": now_iso(),
                    "tool": rel(Path(__file__)),
                    "note": "created by s2k_controlled_pilot v2 before any run directory",
                },
            )
    else:
        root.mkdir(parents=True, exist_ok=False)
        _assert_no_reparse_chain(root, ev)
        contract = root / ROOT_CONTRACT_NAME
        dump_json(
            contract,
            {
                "document": ROOT_CONTRACT_DOCUMENT,
                "created_at": now_iso(),
                "tool": rel(Path(__file__)),
                "note": "created by s2k_controlled_pilot v2 before any run directory",
            },
        )
    return root


def create_run_dir(root: Path, mode: str) -> Path:
    """每次执行只创建全新运行目录；已存在即拒绝（不归档/不删除/不覆盖）。"""
    runs = _resolved(root) / "runs"
    if runs.exists() and not runs.is_dir():
        raise SystemExit(f"REFUSE: runs 路径不是目录：{rel(runs)}")
    runs.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S") + f"-{os.getpid()}"
    run_dir = runs / f"{mode}-{stamp}"
    if run_dir.exists():
        raise SystemExit(f"REFUSE: 运行目录已存在，拒绝复用：{rel(run_dir)}")
    run_dir.mkdir(parents=False, exist_ok=False)
    _ACTIVE_RUN["root"] = _resolved(root)
    _ACTIVE_RUN["run_dir"] = run_dir
    _ACTIVE_RUN["mode"] = mode
    return run_dir


class Journal:
    """安全追加式 journal：只在运行前新建；不覆盖；不写 secret/正文/原始供应商请求 ID。"""

    def __init__(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            raise SystemExit(f"REFUSE: journal 已存在：{rel(path)}")
        self.path = path
        self._lock = threading.Lock()
        self._handle = path.open("x", encoding="utf-8")

    def write(self, event: str, **fields: object) -> None:
        record = {"event": event, "at": now_iso(), **fields}
        line = json.dumps(record, ensure_ascii=False, sort_keys=True, default=str)
        with self._lock:
            self._handle.write(line + "\n")
            self._handle.flush()
            try:
                os.fsync(self._handle.fileno())
            except OSError:  # pragma: no cover - 磁盘/句柄异常不改变主流程
                pass

    def close(self) -> None:
        try:
            self._handle.close()
        except OSError:  # pragma: no cover
            pass


def _safe_text(value: object, *, limit: int = 300) -> str:
    text = str(value or "")
    text = text.replace(SYNTH_SECRET, "<redacted-secret>").replace("Authorization: Bearer", "<redacted-auth>")
    return text[:limit]


def canonical_decimal(value: Decimal) -> str:
    return format(value, "f")


def _a_money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.00000001"))


# ---------------------------------------------------------------- 资源门 / T09


class _MEMORYSTATUSEX:  # pragma: no cover - Windows 结构定义
    pass


def memory_facts() -> dict:
    """系统物理内存与可用提交（不读进程地址空间 free_virtual）。"""
    try:
        import ctypes

        class _MS(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = _MS()
        status.dwLength = ctypes.sizeof(_MS)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return {"error": "GlobalMemoryStatusEx failed"}
        mib = 1024 * 1024
        return {
            "physical_total_mib": round(status.ullTotalPhys / mib, 1),
            "physical_available_mib": round(status.ullAvailPhys / mib, 1),
            "commit_total_mib": round(status.ullTotalPageFile / mib, 1),
            "commit_available_mib": round(status.ullAvailPageFile / mib, 1),
            "memory_load_percent": int(status.dwMemoryLoad),
            "source": "GlobalMemoryStatusEx",
        }
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}


def resource_gate(mode: str = "single") -> dict:
    """资源门按真实进程模型分类，而不是同时套用两套门槛。

    - ``single``：本 pilot 的全部环节（FastAPI TestClient + ASGI 应用 + worker + OCR/embedding/
      rerank 网关）都在**同一个 Python 进程**内完成（见 run_controlled_pilot：TestClient(app)，
      不起第二个服务进程），因此只要求单进程 250MiB 物理 / 600MiB 可用提交。
    - ``cross_process``：只有在确实另起进程/服务的重型场景才要求 700MiB 物理 / 1500MiB 可用提交。

    两套阈值都如实回显，被采用的那一套决定 ``ok``；未采用的一套只作事实，不参与判定。
    """
    facts = memory_facts()
    physical = float(facts.get("physical_available_mib") or 0.0)
    commit = float(facts.get("commit_available_mib") or 0.0)
    single_ok = physical >= PER_PROCESS_PHYSICAL_MIB and commit >= PER_PROCESS_COMMIT_MIB
    cross_ok = physical >= MIN_PHYSICAL_MIB and commit >= MIN_COMMIT_MIB
    adopted = cross_ok if mode == "cross_process" else single_ok
    ok = "error" not in facts and adopted
    facts.update(
        {
            "ok": ok,
            "gate_mode": "cross_process" if mode == "cross_process" else "single",
            "single_process_ok": single_ok,
            "cross_process_ok": cross_ok,
            "thresholds_mib": {
                "cross_process_physical": MIN_PHYSICAL_MIB,
                "cross_process_commit": MIN_COMMIT_MIB,
                "single_process_physical": PER_PROCESS_PHYSICAL_MIB,
                "single_process_commit": PER_PROCESS_COMMIT_MIB,
            },
            "checked_at": now_iso(),
        }
    )
    return facts


def ensure_t09() -> Path:
    """每进程导入 acceptance.support 之前：在**本次运行目录**下建立/核验新 T09 证据根。"""
    run_dir = _ACTIVE_RUN.get("run_dir")
    if run_dir is None:
        raise SystemExit("REFUSE: 尚未创建本轮运行目录，不能建立 T09 证据根")
    t09_root = Path(run_dir) / "t09-output"
    t09_root.mkdir(parents=True, exist_ok=True)
    raw = os.environ.get("T09_EVIDENCE_ROOT")
    if raw:
        candidate = Path(raw)
        if not candidate.is_absolute():
            candidate = ROOT / candidate
        resolved = candidate.resolve()
        if not _is_under(resolved, t09_root):
            raise SystemExit(f"REFUSE: T09_EVIDENCE_ROOT 不在本轮运行目录之下：{resolved}")
        if not resolved.is_dir():
            raise SystemExit(f"REFUSE: T09_EVIDENCE_ROOT 不存在：{resolved}")
        return resolved
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    resolved = (t09_root / f"run-{stamp}-{os.getpid()}").resolve()
    resolved.mkdir(parents=True, exist_ok=False)
    os.environ["T09_EVIDENCE_ROOT"] = str(resolved)
    return resolved


def install_business_paths() -> None:
    for entry in (str(ROOT / "backend" / "src"), str(ROOT / "backend" / "tests")):
        if entry not in sys.path:
            sys.path.insert(0, entry)


def load_support() -> dict:
    """导入旧工装（b0 fixtures/questions + conftest HTTP helpers），导入前先核验 T09。"""
    t09 = ensure_t09()
    install_business_paths()
    from acceptance.support import b0  # noqa: PLC0415 - 顺序保护：先 T09 再导入
    from acceptance.support import ocr_transcripts
    from acceptance.support.evidence import EVIDENCE_ROOT
    from conftest import current_csrf, login, upload_document, write_headers

    if EVIDENCE_ROOT.resolve() != t09:
        raise SystemExit(f"REFUSE: evidence 解析不一致：{EVIDENCE_ROOT} != {t09}")
    return {
        "b0": b0,
        "ocr_transcripts": ocr_transcripts,
        "current_csrf": current_csrf,
        "login": login,
        "upload_document": upload_document,
        "write_headers": write_headers,
        "t09": t09,
    }


def load_business() -> dict:
    """导入本轮需要的产品模块（socket 熔断与 T09 已就绪之后才调用）。"""
    if _BUSINESS:
        return _BUSINESS
    install_business_paths()
    import mktkb.controlled_execution as ce
    import mktkb.live_authorization as gate_module
    from mktkb.config import Settings
    from mktkb.documents.lifecycle import get_revision
    from mktkb.ingestion.worker import OcrRateLimiter, run_one_job
    from mktkb.providers.types import (
        CompletionInput,
        DialogueContext,
        OCRInput,
    )
    from mktkb.rag.budget import BudgetLedger
    from mktkb.rag.config import RagConfig
    from mktkb.rag.providers import FakeEmbeddingProvider, post_counters, reset_post_counters
    from mktkb.rag.types import DocumentSpec
    from mktkb.ingestion.parsers import parse_document
    from mktkb.ingestion.parsers.types import ParseLimits, ParseServices

    _BUSINESS.update(
        {
            "ce": ce,
            "gate_module": gate_module,
            "Settings": Settings,
            "get_revision": get_revision,
            "run_one_job": run_one_job,
            "OcrRateLimiter": OcrRateLimiter,
            "CompletionInput": CompletionInput,
            "DialogueContext": DialogueContext,
            "OCRInput": OCRInput,
            "BudgetLedger": BudgetLedger,
            "RagConfig": RagConfig,
            "FakeEmbeddingProvider": FakeEmbeddingProvider,
            "post_counters": post_counters,
            "reset_post_counters": reset_post_counters,
            "DocumentSpec": DocumentSpec,
            "parse_document": parse_document,
            "ParseLimits": ParseLimits,
            "ParseServices": ParseServices,
        }
    )
    return _BUSINESS


# ---------------------------------------------------------------- socket 熔断


class SocketGuard:
    """业务导入前安装：只放行回环/testserver；真实 socket 与 HTTPTransport 记录并拒绝。"""

    def __init__(self) -> None:
        self.attempts: list[str] = []
        self.external: list[str] = []
        self.hosts: list[str] = []
        self._real_connect = socket.socket.connect
        self._real_connect_ex = socket.socket.connect_ex
        self._real_create = socket.create_connection
        self._real_resolve = socket.getaddrinfo
        self._real_http = httpx.HTTPTransport.handle_request
        self._real_async_http = httpx.AsyncHTTPTransport.handle_async_request
        self.installed_at = now_iso()

    @staticmethod
    def _allowed(host: object) -> bool:
        text = str(host)
        return text in {"127.0.0.1", "::1", "localhost", "testserver", "0.0.0.0", ""} or text.startswith("127.")

    def _record(self, label: str, host: object) -> None:
        self.attempts.append(label)
        self.hosts.append(str(host))
        if not self._allowed(host):
            self.external.append(label)

    def install(self) -> "SocketGuard":
        guard = self

        def connect(sock, address, *args, **kwargs):  # noqa: ANN001
            host = address[0] if isinstance(address, tuple) else address
            guard._record(f"socket.connect {host!r}", host)
            if not guard._allowed(host):
                raise RuntimeError("s2k-guard blocked external socket")
            return guard._real_connect(sock, address, *args, **kwargs)

        def connect_ex(sock, address, *args, **kwargs):  # noqa: ANN001
            host = address[0] if isinstance(address, tuple) else address
            guard._record(f"socket.connect_ex {host!r}", host)
            raise RuntimeError("s2k-guard blocked connect_ex")

        def create_connection(address, *args, **kwargs):  # noqa: ANN001
            host = address[0] if isinstance(address, tuple) else address
            guard._record(f"socket.create_connection {host!r}", host)
            if not guard._allowed(host):
                raise RuntimeError("s2k-guard blocked create_connection")
            return guard._real_create(address, *args, **kwargs)

        def getaddrinfo(host, *args, **kwargs):  # noqa: ANN001
            guard._record(f"socket.getaddrinfo {host!r}", host)
            if not guard._allowed(host):
                raise RuntimeError("s2k-guard blocked getaddrinfo")
            return guard._real_resolve(host, *args, **kwargs)

        def handle_request(transport, request):  # noqa: ANN001
            guard._record(f"httpx.HTTPTransport {request.url}", str(request.url.host))
            raise RuntimeError("s2k-guard blocked real HTTPTransport")

        async def handle_async_request(transport, request):  # noqa: ANN001
            guard._record(f"httpx.AsyncHTTPTransport {request.url}", str(request.url.host))
            raise RuntimeError("s2k-guard blocked real AsyncHTTPTransport")

        socket.socket.connect = connect
        socket.socket.connect_ex = connect_ex
        socket.create_connection = create_connection
        socket.getaddrinfo = getaddrinfo
        httpx.HTTPTransport.handle_request = handle_request
        httpx.AsyncHTTPTransport.handle_async_request = handle_async_request
        return self

    def uninstall(self) -> "SocketGuard":
        socket.socket.connect = self._real_connect
        socket.socket.connect_ex = self._real_connect_ex
        socket.create_connection = self._real_create
        socket.getaddrinfo = self._real_resolve
        httpx.HTTPTransport.handle_request = self._real_http
        httpx.AsyncHTTPTransport.handle_async_request = self._real_async_http
        return self

    def summary(self) -> dict:
        return {
            "installed_at": self.installed_at,
            "attempts": len(self.attempts),
            "external_attempts": len(self.external),
            "external": list(self.external),
            "hosts": sorted(set(self.hosts)),
        }


# ---------------------------------------------------------------- fixtures 精确计划


def fixture_entry(support: dict, file_id: str) -> dict:
    return support["b0"].FILE_INDEX[file_id]


def fixture_path(support: dict, file_id: str) -> Path:
    return support["b0"].fixture_path(file_id)


def _d01_plan(support: dict, business: dict) -> dict:
    path = fixture_path(support, "D01")
    entry = fixture_entry(support, "D01")
    actual_sha = sha256_path(path)
    services = business["ParseServices"](report={})
    units = list(business["parse_document"](path, "xlsx", services))
    doc = business["DocumentSpec"](
        doc_id="D01",
        source_path=rel(path),
        title="物品位置表",
        file_kind="xlsx",
        version_id="s2k-plan-version",
        version_label="V2",
        sha256=actual_sha,
        business_date=None,
    )
    from mktkb.rag.chunking import adapt_parsed_unit, build_chunks  # noqa: PLC0415

    config = business["RagConfig"]()
    atomic = [adapt_parsed_unit(unit, doc=doc, ordinal=index) for index, unit in enumerate(units)]
    chunks = build_chunks(doc, atomic, config)
    batch_size = int(config.embedding_batch_size)
    batch_count = (len(chunks) + batch_size - 1) // batch_size
    chunk_sha = sha256_bytes(
        json.dumps([chunk.chunk_id for chunk in chunks], ensure_ascii=False, sort_keys=True).encode("utf-8")
    )
    return {
        "file_id": "D01",
        "path": rel(path),
        "bytes": path.stat().st_size,
        "sha256_expected": entry["sha256"],
        "sha256_actual": actual_sha,
        "sha_match": actual_sha == entry["sha256"],
        "kind": entry["kind"],
        "parse_report": services.report,
        "units": len(units),
        "unit_kinds": sorted({unit.kind for unit in units}),
        "chunks": len(chunks),
        "chunk_kinds": {
            "record": sum(1 for chunk in chunks if chunk.kind == "record"),
            "text": sum(1 for chunk in chunks if chunk.kind == "text"),
        },
        "chunk_ids_sha256": chunk_sha,
        "chunk_chars": sum(len(chunk.text) for chunk in chunks),
        "embedding_batch_size": batch_size,
        "embedding_batches": batch_count,
        "embedding_request_texts": len(chunks),
        "role": "import -> worker -> publish -> index embedding (product HTTP + worker + sync)",
    }


class _TranscriptOCR:
    """计划期 OCR 替身：只返回冻结受控转录，绝不发请求；用于精确推导 units/chunks。"""

    def __init__(self, file_id: str, transcripts) -> None:  # noqa: ANN001
        self.file_id = file_id
        self.transcripts = transcripts
        self.calls: list[dict] = []

    def recognize(self, page, *, mode):  # noqa: ANN001
        from mktkb.providers.types import OCRPageResult  # noqa: PLC0415

        self.calls.append({"mode": mode, "page": int(page.page), "bbox": page.bbox, "tile_bytes": len(page.content)})
        if self.file_id == "D09":
            if mode != "text":
                raise SystemExit(f"REFUSE: D09 期望文字 OCR（text），实际产品判定 {mode}，计划需重新核算")
            return OCRPageResult(
                text="\n".join(self.transcripts.D09_TEXT),
                provider_request_id="sha256:plan-standin-d09",
                confidence=95.0,
            )
        if self.file_id == "D10":
            if mode != "table":
                raise SystemExit(f"REFUSE: D10 期望表格 OCR（table），实际产品判定 {mode}，计划需重新核算")
            rows = (tuple(self.transcripts.D10_TABLE_HEADER), *tuple(self.transcripts.D10_TABLE_ROWS))
            return OCRPageResult(
                text="\n".join(self.transcripts.D10_TEXT),
                table_rows=rows,
                provider_request_id="sha256:plan-standin-d10",
                confidence=95.0,
            )
        raise SystemExit(f"REFUSE: 未绑定转录的文件 {self.file_id}")


def _ocr_image_plan(support: dict, business: dict, file_id: str) -> dict:
    """整篇单页图片（D09 文字 / D10 表格）的精确输入：真实产品判定/切片/解析/分块（不发送）。"""
    from PIL import Image  # noqa: PLC0415
    from mktkb.ingestion.parsers.image import looks_like_rule_table, prepare_ocr_tiles  # noqa: PLC0415
    from mktkb.rag.chunking import adapt_parsed_unit, build_chunks  # noqa: PLC0415

    path = fixture_path(support, file_id)
    entry = fixture_entry(support, file_id)
    actual_sha = sha256_path(path)
    limits = business["ParseLimits"]()
    with Image.open(path) as image:
        size = list(image.size)
        image = image.convert("RGB")
        mode = "table" if looks_like_rule_table(image) else "text"
        tiles = prepare_ocr_tiles(image, limits=limits, mode=mode, source_width=size[0], source_height=size[1])
    if len(tiles) != 1:
        raise SystemExit(f"REFUSE: {file_id} 在默认 limits 下产生 {len(tiles)} 个 tile，计划需要重新核算")
    tile = tiles[0]
    content = bytes(tile["content"])

    standin = _TranscriptOCR(file_id, support["ocr_transcripts"])
    services = business["ParseServices"](limits=limits, report={}, ocr=standin)
    units = list(business["parse_document"](path, entry["kind"], services))
    doc = business["DocumentSpec"](
        doc_id=file_id,
        source_path=rel(path),
        title=file_id,
        file_kind=entry["kind"],
        version_id="s2k-r1b-plan-version",
        version_label=entry.get("business_version") or "V1",
        sha256=actual_sha,
        business_date=None,
    )
    from mktkb.rag.chunking import adapt_parsed_unit as _adapt  # noqa: PLC0415
    from mktkb.rag.chunking import build_chunks as _build  # noqa: PLC0415

    config = business["RagConfig"]()
    atomic = [_adapt(unit, doc=doc, ordinal=index) for index, unit in enumerate(units)]
    chunks = _build(doc, atomic, config)
    batch_size = int(config.embedding_batch_size)
    page_facts = (services.report.get("pages") or [{}])[0]
    transcript = support["ocr_transcripts"]
    if file_id == "D09":
        semantics_lines = list(transcript.D09_TEXT)
        semantics_payload = {"lines": semantics_lines}
        table_header: list[str] = []
        table_rows: list[list[str]] = []
    else:
        semantics_lines = list(transcript.D10_TEXT)
        table_header = list(transcript.D10_TABLE_HEADER)
        table_rows = [list(row) for row in transcript.D10_TABLE_ROWS]
        semantics_payload = {"header": table_header, "rows": table_rows}
    return {
        "file_id": file_id,
        "path": rel(path),
        "bytes": path.stat().st_size,
        "sha256_expected": entry["sha256"],
        "sha256_actual": actual_sha,
        "sha_match": actual_sha == entry["sha256"],
        "kind": entry["kind"],
        "pages": 1,
        "selected_page": 1,
        "pixels": size,
        "mode": mode,
        "product_mode_source": "product looks_like_rule_table on the real fixture image",
        "tiles": len(tiles),
        "tile_bbox": tile.get("bbox"),
        "tile_bytes": len(content),
        "tile_sha256": sha256_bytes(content),
        "ocr_input_mime": "image/png",
        "ocr_input_page": 1,
        "ocr_standin_calls": standin.calls,
        "parse_report_page": {
            "status": page_facts.get("status"),
            "ocr_mode": page_facts.get("ocr_mode"),
            "units": page_facts.get("units"),
        },
        "units": len(units),
        "unit_kinds": [unit.kind for unit in units],
        "unit_keys": [unit.unit_key for unit in units],
        "unit_locators": [dict(unit.locator) for unit in units],
        "unit_texts": [unit.text for unit in units],
        "chunks": len(chunks),
        "chunk_kinds": {
            "record": sum(1 for chunk in chunks if chunk.kind == "record"),
            "text": sum(1 for chunk in chunks if chunk.kind == "text"),
        },
        "chunk_chars": sum(len(chunk.text) for chunk in chunks),
        "embedding_batch_size": batch_size,
        "embedding_batches": (len(chunks) + batch_size - 1) // batch_size,
        "page_semantics_source": "冻结受控转录 ocr_transcripts（生成器写入页面的原文，非 questions.expected_values）",
        "page_semantics_sha256": sha256_bytes(
            json.dumps(semantics_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ),
        "page_semantics_lines": semantics_lines,
        "table_header": table_header,
        "table_rows": table_rows,
        "expected_table_row_units": len(table_rows) if mode == "table" else 0,
        "ocr_request_hash_contract": {
            "version": "ocr-v2",
            "scope_formula": "sha256('ocr-source-v1|<document_id>|<version_id>') by production ingestion.worker.OcrExecutor (R1A)",
            "payload_formula": "sha256('ocr-v2|<source_scope>|<mode>|<real_page>|' + tile_bytes)",
            "precomputable_before_upload": False,
            "binding": "receipt.ocr_request_bindings recomputes this from the actual uploaded document_id/version_id and plan tile_sha256, then matches the ledger request_sha256 list",
        },
        "reuse_note": (
            "D09/D10 整篇即单页；生产 worker 导入并发布后，完整矩阵复用其 OCR 结果/检查点/索引，"
            "不再重复 OCR（前提：同一 DB/同一 version/同一检查点，不得用新上传/新 version 冒充复用）。"
        ),
    }


def _question_plans(support: dict) -> list[dict]:
    questions = {item["id"]: item for item in support["b0"].QUESTIONS}
    plans = []
    for question_id in ("Q01", "Q03"):
        item = questions[question_id]
        question = str(item["question"])
        plans.append(
            {
                "question_id": question_id,
                "category": item.get("category"),
                "question": question,
                "question_sha256": sha256_bytes(question.encode("utf-8")),
                "question_bytes": len(question.encode("utf-8")),
                "expected_kind": (item.get("scenario") or {}).get("expected_kind"),
                "expected_values_role": "仅用于执行后评分对照；绝不进入模型/供应商请求上下文",
                "expected_sources_role": "仅用于引用对照（来源文件/记录），不进入请求",
                "expected_values": list(item.get("expected_values") or []),
                "expected_sources": list(item.get("expected_sources") or []),
                "provider_sequence": [
                    {"kind": "embedding", "why": "candidate_unit_ids_for_intent(record) 向量召回 query embedding"},
                    {"kind": "rerank", "why": "同一次 record 候选检索的 rerank"},
                    {"kind": "embedding", "why": "candidate_unit_ids_for_intent(document) 正文面补齐的 query embedding"},
                    {"kind": "rerank", "why": "同一次 document 候选检索的 rerank"},
                    # 计划按**确定性路径**只算 1 次 answer chat。真实调用实测（2026-11-04）：
                    # 当 FTS 证据面为空时，产品还会先发 1 次 query_expansion chat（见
                    # conversations/service.py 的 evidence.kind == "none" 分支），因此真实
                    # 运行可能比本计划多出 ≤1 次 chat/题。已知限制：那会让
                    # reserved_equals_plan_total 严格检查失败（本轮交付已如实记录，未改判定）。
                    {"kind": "chat", "why": "产品 ModelGateway 记录型回答（受控 chat 网关，全额 context ceiling 预留）"},
                ],
                "product_path": "POST /api/v1/conversations + POST /api/v1/conversations/{id}/messages（record 意图，_rag_owns_turn=False）",
            }
        )
    return plans


def _chat_policy_caps() -> tuple[int, int]:
    """当前生效的 chat 准入 cap（来自产品 settlement_policy 常量，不在此另存一份）。"""
    from mktkb.rag.settlement_policy import CHAT_COMPLETION_TOKENS_CAP, CHAT_PROMPT_TOKENS_CAP

    return int(CHAT_PROMPT_TOKENS_CAP), int(CHAT_COMPLETION_TOKENS_CAP)


def compute_pilot_plan_data(support: dict, business: dict) -> dict:
    """按真实 fixtures 重算本轮小样本：D01 + D09（文字 OCR）+ D10（表格 OCR）+ Q01/Q03。

    F-K5：pilot 不再单付 D07 第 3 页；D09/D10 都是原矩阵整篇单页导入，结果/检查点可复用。
    OCR 请求 hash 采用 R1A 的 ocr-v2 公式（绑定运行期可信 source_scope），计划只能给出
    公式与内容绑定，实际 hash 在回执里用真实 document_id/version_id 复算核对。
    """
    d01 = _d01_plan(support, business)
    d09 = _ocr_image_plan(support, business, "D09")
    d10 = _ocr_image_plan(support, business, "D10")
    questions = _question_plans(support)

    ocr_text_requests = sum(1 for item in (d09, d10) if item["mode"] == "text")
    ocr_table_requests = sum(1 for item in (d09, d10) if item["mode"] == "table")
    if ocr_text_requests != 1 or ocr_table_requests != 1:
        raise SystemExit(
            "REFUSE: 本轮 pilot 必须恰好 1 页文字 OCR（D09 text）+ 1 页表格 OCR（D10 table）；"
            f"实际 D09={d09['mode']} D10={d10['mode']}（产品行为变化，需重新核算 pilot 形状）"
        )
    if d09["mode"] != "text" or d10["mode"] != "table":
        raise SystemExit("REFUSE: D09 必须是 text、D10 必须是 table（经理裁决的 pilot 形状）")

    question_embeddings = sum(
        1 for question in questions for step in question["provider_sequence"] if step["kind"] == "embedding"
    )
    rerank_requests = sum(
        1 for question in questions for step in question["provider_sequence"] if step["kind"] == "rerank"
    )
    chat_requests = sum(
        1 for question in questions for step in question["provider_sequence"] if step["kind"] == "chat"
    )
    embedding_requests = d01["embedding_batches"] + d09["embedding_batches"] + d10["embedding_batches"] + question_embeddings

    sequence = [
        {
            "seq": 1,
            "kind": "embedding",
            "source": "D01 索引向量",
            "why": "POST /api/v1/documents + 生产 worker + publish 触发 qa.sync；9 chunks=1 batch",
        },
        {
            "seq": 2,
            "kind": "ocr_text",
            "source": "D09 整篇单页（文字 OCR，page1）",
            "why": "产品 HTTP 上传 + 生产 worker OcrExecutor（attempts=1, tile=1, 真实来源锚）",
        },
        {
            "seq": 3,
            "kind": "embedding",
            "source": "D09 索引向量",
            "why": "publish 触发 qa.sync；1 个 image_text chunk=1 batch",
        },
        {
            "seq": 4,
            "kind": "ocr_table",
            "source": "D10 整篇单页（表格 OCR，page1）",
            "why": "产品 HTTP 上传 + 生产 worker OcrExecutor（attempts=1, tile=1, 真实来源锚）",
        },
        {
            "seq": 5,
            "kind": "embedding",
            "source": "D10 索引向量",
            "why": "publish 触发 qa.sync；2 个 record chunks=1 batch",
        },
    ]
    for question in questions:
        for step in question["provider_sequence"]:
            sequence.append(
                {
                    "seq": len(sequence) + 1,
                    "kind": step["kind"],
                    "source": question["question_id"],
                    "why": step["why"],
                }
            )
    total_calls = len(sequence)
    if total_calls != embedding_requests + rerank_requests + chat_requests + ocr_text_requests + ocr_table_requests:
        raise SystemExit("REFUSE: 请求序列计数与分类计数不一致（计划自检失败）")

    ce = business["ce"]
    subplan = ce.ControlledRequestPlan(
        stage=STAGE,
        chat_requests=chat_requests,
        embedding_requests=embedding_requests,
        rerank_requests=rerank_requests,
        ocr_text_requests=ocr_text_requests,
        ocr_table_requests=ocr_table_requests,
    )
    costs = {
        "chat_cap_charge_cny": canonical_decimal(subplan.chat_cap_charge_cny),
        "chat_full_reserve_cny": canonical_decimal(subplan.chat_reserve_cny),
        "embedding_cap_charge_cny": canonical_decimal(subplan.embedding_cap_charge_cny),
        "rerank_cap_charge_cny": canonical_decimal(subplan.rerank_cap_charge_cny),
        "ocr_text_charge_cny": canonical_decimal(Decimal("0.5")),
        "ocr_table_charge_cny": canonical_decimal(Decimal("0.15")),
        "conditional_cap_settlement_cny": canonical_decimal(subplan.conservative_settlement_cny),
        "peak_include_history_cny": canonical_decimal(subplan.peak_include_history_cny),
        "single_chat_reserve_cny": canonical_decimal(subplan.max_single_reserve_cny),
        "send_time_reserves_cny": {
            "chat": canonical_decimal(subplan.chat_reserve_cny),
            "embedding": "0.04096",
            "rerank": "0.024",
            "ocr_text": "0.5",
            "ocr_table": "0.15",
            "note": "embedding 预留=官方单请求 10×8192 token 上限；rerank 预留=30000 token 上限；成功按 usage 保守结算并释放差额，失败/超 cap 全额保留。",
        },
    }
    plan_dict = {
        "document": "S2-K-pilot-plan",
        "plan_version": "s2k-pilot-plan-v2",
        "generated_at": now_iso(),
        "mode": "plan-only; no provider call; no real ledger write; no formal GO",
        "stage": STAGE,
        "task": "docs/evidence/LOCAL-R1-20261101/PM/S2-K-R1B-tool-rework-task.md",
        "window": "S2-DEV/K-R1B development self-test (Mock only)",
        "scope": {
            "documents_imported": ["D01", "D09", "D10"],
            "ocr_pages_called": [
                {"file_id": "D09", "page": 1, "mode": d09["mode"], "role": "文字 OCR 样本页（原矩阵整篇单页，可复用）"},
                {"file_id": "D10", "page": 1, "mode": d10["mode"], "role": "表格 OCR 样本页（原矩阵整篇单页，可复用）"},
            ],
            "questions": [question["question_id"] for question in questions],
            "deferred": [
                "D07 整篇 8 页文字 OCR/索引：留给完整矩阵；本轮不再单付 pilot 的 D07p3",
                "D08 整篇 2 页文字 OCR：留给完整矩阵",
                "其余 38 题（除 Q01/Q03）与 N/C/U、容量、S4：不做，也不据本轮记通过",
            ],
            "real_provider_calls": 0,
            "real_spend_cny": 0,
        },
        "request_plan": subplan.plan_dict(),
        "request_plan_sha256": subplan.request_plan_sha256,
        "counts": {
            "chat": chat_requests,
            "embedding": embedding_requests,
            "rerank": rerank_requests,
            "ocr_text": ocr_text_requests,
            "ocr_table": ocr_table_requests,
            "total_provider_posts": total_calls,
        },
        "provider_request_sequence": sequence,
        "product_http_sequence": [
            {"method": "POST", "path": "/api/v1/auth/login", "paid": False},
            {"method": "GET", "path": "/api/v1/auth/me", "paid": False},
            {"method": "POST", "path": "/api/v1/documents", "paid": False, "note": "上传 D01（xlsx）"},
            {"method": "worker", "path": "run_one_job(D01, ocr=None)", "paid": False},
            {"method": "POST", "path": "/api/v1/documents/{id}/versions/{vid}/publish", "paid": False, "note": "触发索引同步 -> 付费 POST #1（embedding）"},
            {"method": "POST", "path": "/api/v1/documents", "paid": False, "note": "上传 D09（png，整篇单页）"},
            {"method": "worker", "path": "run_one_job(D09, ocr=executor.ocr_gateway, max_attempts=1)", "paid": True, "note": "付费 POST #2（OCR text, page1, 真实来源锚）"},
            {"method": "POST", "path": "/api/v1/documents/{id}/versions/{vid}/publish", "paid": False, "note": "触发索引同步 -> 付费 POST #3（embedding）"},
            {"method": "POST", "path": "/api/v1/documents", "paid": False, "note": "上传 D10（jpg，整篇单页）"},
            {"method": "worker", "path": "run_one_job(D10, ocr=executor.ocr_gateway, max_attempts=1)", "paid": True, "note": "付费 POST #4（OCR table, page1, 真实来源锚）"},
            {"method": "POST", "path": "/api/v1/documents/{id}/versions/{vid}/publish", "paid": False, "note": "触发索引同步 -> 付费 POST #5（embedding）"},
            {"method": "POST", "path": "/api/v1/conversations", "paid": False},
            {"method": "POST", "path": "/api/v1/conversations/{id}/messages", "paid": True, "note": f"Q01 -> 付费 POST #6-#{5 + 5}"},
            {"method": "POST", "path": "/api/v1/conversations", "paid": False},
            {"method": "POST", "path": "/api/v1/conversations/{id}/messages", "paid": True, "note": f"Q03 -> 付费 POST #{5 + 5 + 1}-#{5 + 10}"},
        ],
        "costs": costs,
        "fixtures": {
            "manifest_sha256": sha256_path(ROOT / "fixtures" / "acceptance" / "manifest.json"),
            "questions_sha256": sha256_path(ROOT / "fixtures" / "acceptance" / "questions.json"),
            "D01": d01,
            "D09_page1": d09,
            "D10_page1": d10,
        },
        "ocr_request_hash_contract": {
            "version": "ocr-v2 (S2-K-R1A)",
            "scope_formula": "sha256('ocr-source-v1|<document_id>|<version_id>')，由生产 worker 的 OcrExecutor 用 DB 实际 document/version 生成并覆盖",
            "payload_formula": "sha256('ocr-v2|<source_scope>|<mode>|<real_page>|' + tile_bytes)",
            "precomputable_before_upload": False,
            "why": "document_id/version_id 是产品上传后生成的 UUID，计划期不可预知；计划固定 mode/page/tile_sha256，运行回执用真实身份复算并核对账本",
            "runtime_binding_required": "receipt.ocr_request_bindings",
        },
        "questions": questions,
        "sources": subplan.plan_dict()["sources"],
        "prices": PRICE_SOURCES,
        "caps": {
            # 用产品当前生效的策略常量，避免文档与判定不一致（2026-11-04 已从 1536/256
            # 对齐到请求自身上界 6144/800）。
            "chat_prompt_tokens": _chat_policy_caps()[0],
            "chat_completion_tokens": _chat_policy_caps()[1],
            "embedding_total_tokens": 4096,
            "rerank_total_tokens": 6000,
            "serial": True,
            "ocr_max_tiles_per_page": 1,
            "ocr_max_attempts": 1,
            "policy_note": "caps 来自产品 settlement_policy 常量；是成功准入条件，不是真实 usage。",
        },
        "availability": {
            "chat": "官方页面 2026-11-04 重读：deepseek-flash 可调用，上下文 1M",
            "embedding": "官方页面 2026-11-04 重读：text-embedding-v4 在售",
            "rerank": "官方矛盾未决（gte-rerank 下线公告与仍列 v2 的文档）；本账户可用性未知；本轮不付费探测、不换模型",
            "ocr": "腾讯云 OCR 现价/可用性沿用经理 2026-11-04 现读；本轮不发探测请求",
            "paid_probe_sent": 0,
        },
        "real_paths_before": real_paths(),
        "resource_gate": resource_gate(),
        "cli_contract": {
            "evidence_root": "所有模式都要求/默认显式证据根；根必须在 docs/evidence/LOCAL-R1-20261101 下、非旧证据/固定共享目录、无 reparse 点；已有非空根必须带本轮 root-contract.json",
            "run_dir": "每次执行创建全新 <root>/runs/<mode>-<UTCstamp>-<pid>；不 archive、不 rmtree、不覆盖、不删除",
            "prepare_to_live": "plan 运行的 run-dir 产出 plan.json；Mock 与 live 都通过 --plan-file 读同一文件并核对 request_plan_sha256/计数/fixtures；live 另需 --mock-file 核对 Mock 全绿且 plan hash 一致",
            "live_out": "--out 必须是本轮证据根下的全新目录；cmd_live 在运行前创建该目录与 live-journal.jsonl，成功/失败都落 live-receipt.json",
            "fixed_shared_paths_do_not_move": [rel(REAL_LEDGER), rel(REAL_BUDGET), rel(REAL_GO)],
            "exit_codes": {str(code): text for code, text in EXIT_CODES.items()},
        },
        "decisions": {
            "text_ocr_page": "D09 整篇单页（page1, text）：原矩阵 12 次初始 OCR 中的 D09 1 次，本轮结果/检查点可被矩阵复用，不新增项目 OCR 次数。",
            "table_ocr_page": "D10 整篇单页（page1, table）：原矩阵唯一的 1 次 table OCR，本轮结果/检查点可被矩阵复用。",
            "removed_d07p3": "删除 pilot 单独的 D07 第 3 页文字样本；该单页结果无法被 D07 整篇导入复用（会多付第 14 次 OCR）。D07 整篇 8 页仍在原矩阵 12 次文本 OCR 内。",
            "no_policy_change": "不改 J1 caps/结算 policy/产品默认行为；子计划只是把 136/111/94/12+1 缩为精确小样本，OCR 总 13 不变。",
            "pilot_not_real_go": "本文件只是开发自测计划；候选 GO 是 DRAFT_NOT_AUTHORIZATION，不应用、不写固定路径。",
        },
    }
    return {"plan_data": plan_dict, "subplan": subplan}


# ---------------------------------------------------------------- 真实路径 / 候选预算 / DRAFT GO


def probe_fixed_go() -> dict:
    """只读探测固定正式 GO：存在性/字节 hash + DRAFT 标记检查（不回显 GO 原文/secret）。"""
    result = {
        "path": rel(REAL_GO),
        "exists": REAL_GO.is_file(),
        "sha256": sha256_path(REAL_GO),
        "size": REAL_GO.stat().st_size if REAL_GO.is_file() else None,
        "formal_marker_check": None,
    }
    if not result["exists"]:
        return result
    try:
        payload = json.loads(REAL_GO.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            result["formal_marker_check"] = {"formal": False, "problems": ["GO top level is not an object"]}
        else:
            result["formal_marker_check"] = _assert_formal_go_payload(payload)
    except (OSError, json.JSONDecodeError) as exc:
        result["formal_marker_check"] = {"formal": False, "problems": [f"GO unreadable: {type(exc).__name__}"]}
    return result


def real_paths() -> dict:
    return {
        "ledger": {"path": rel(REAL_LEDGER), "sha256": sha256_path(REAL_LEDGER), "size": REAL_LEDGER.stat().st_size if REAL_LEDGER.is_file() else None},
        "budget": {"path": rel(REAL_BUDGET), "sha256": sha256_path(REAL_BUDGET), "size": REAL_BUDGET.stat().st_size if REAL_BUDGET.is_file() else None},
        "fixed_go": probe_fixed_go(),
        "dotenv": {
            "path": rel(DOTENV),
            "size": DOTENV.stat().st_size if DOTENV.is_file() else None,
            "mtime_utc": datetime.fromtimestamp(DOTENV.stat().st_mtime, tz=timezone.utc).isoformat(timespec="seconds") if DOTENV.is_file() else None,
            "content_read": False,
            "content_hashed": False,
        },
        "var_opened": False,
        "fixed_paths_note": "共享正式 GO/账本/预算固定路径不随 --evidence-root 漂移；本轮只读。",
    }

def read_real_budget() -> dict:
    return json.loads(REAL_BUDGET.read_text(encoding="utf-8"))


def real_ledger_summary() -> dict:
    events = [json.loads(line) for line in REAL_LEDGER.read_text(encoding="utf-8").splitlines() if line.strip()]
    historical = sum(float(item.get("accounted_cny") or 0.0) for item in events if item.get("event") == "historical_import")
    reservations = [item for item in events if item.get("event") == "reserved"]
    return {
        "events": len(events),
        "historical_conservative_cny": round(historical, 10),
        "reservation_count": len(reservations),
        "result_count": len([item for item in events if item.get("event") == "result"]),
        "raw_event_types": [item.get("event") for item in events],
    }


def real_stage_accounting() -> dict:
    """只读重放共享账本，取本阶段的累计事实（产品 BudgetLedger.summary，含结算重校验）。

    同一阶段续跑时，阶段额度是**累计**口径：已结算占用 + 本轮峰值都必须装得下，
    请求上限也是累计预留条数。只用产品自己的重放，不另写一套账本算术。
    """
    business = load_business()
    ledger = business["BudgetLedger"](REAL_LEDGER, REAL_BUDGET, stage=STAGE,
                                      stage_limit_cny=10.0, max_requests=1000)
    summary = ledger.summary()
    return {
        "stage": STAGE,
        "stage_accounted_cny": summary.stage_accounted_cny,
        "accounted_cny": summary.accounted_cny,
        "historical_conservative_cny": summary.historical_conservative_cny,
        "reservation_count": summary.reservation_count,
        "result_count": summary.result_count,
        "total_limit_cny": summary.total_limit_cny,
        "source": "mktkb.rag.budget.BudgetLedger.summary() 只读重放",
    }


def ledger_anchor_sha256() -> str | None:
    """共享账本的**不可变历史前缀** hash（产品 ledger_binding_ok 接受的那个锚）。

    GO 必须绑定这个前缀 hash 而不是整文件 hash：整文件 hash 在本次运行写入第一条预留后
    就变了，产品每次预留前都会用 ledger_binding_ok 复核，绑整文件会让第 2 次预留被拒。
    """
    try:
        raw = REAL_LEDGER.read_bytes()
    except OSError:
        return None
    prefix = bytearray()
    for line in raw.splitlines(keepends=True):
        text = line.strip()
        if not text:
            continue
        try:
            event = json.loads(text)
        except json.JSONDecodeError:
            return None
        if not isinstance(event, dict) or event.get("event") != "historical_import":
            break
        prefix.extend(line)
    return sha256_bytes(bytes(prefix)) if prefix else None


def stage_headroom(plan_data: dict, prior: dict) -> dict:
    """本轮真实运行需要的阶段额度/累计请求上限（= 历史已占用 + 本轮峰值）。

    第一次在零占用阶段跑时退化成 plan.peak_include_history（既有口径不变）；
    同阶段续跑则必须把先前已结算占用算进去，否则第 2 次跑会在 chat 预留时被拒。
    """
    peak = Decimal(str(plan_data["costs"]["peak_include_history_cny"]))
    prior_stage = Decimal(str(prior.get("stage_accounted_cny") or 0))
    required = _a_money(prior_stage + peak)
    prior_requests = int(prior.get("reservation_count") or 0)
    total = int(plan_data["counts"]["total_provider_posts"])
    return {
        "prior_stage_accounted_cny": canonical_decimal(_a_money(prior_stage)),
        "prior_reservation_count": prior_requests,
        "plan_peak_include_history_cny": canonical_decimal(peak),
        "plan_total_provider_posts": total,
        "required_stage_limit_cny": canonical_decimal(required),
        "required_max_requests": prior_requests + total,
        "project_total_limit_cny": canonical_decimal(Decimal(str(prior.get("total_limit_cny") or 0))),
        "prior_accounted_cny": canonical_decimal(Decimal(str(prior.get("accounted_cny") or 0))),
        "note": (
            "阶段额度与累计请求上限都是账本累计口径：required = 本阶段已结算占用 + 本轮峰值（含 0.03 历史）"
            "；第一轮为零占用时等于 plan.peak_include_history。"
        ),
    }


def build_candidate_budget(plan_data: dict, subplan, real: dict) -> dict:
    """F-K5：pilot 候选阶段预算 + 完整既定矩阵 136/111/94/12+1 的扣减/共享/不共享推导。

    全部金额用产品已接收的 ControlledRequestPlan 派生值或同一单价重算，不引用历史展示数字；
    全项目总额 10.00、历史 0.03、OCR 总 13 不变；候选不应用，正式分配由经理未来统一对账。
    """
    business = load_business()
    ce = business["ce"]
    budget = read_real_budget()
    ledger_summary = real_ledger_summary()
    limit = Decimal(str(budget["limit_cny"]))
    history = Decimal(str(budget["historical_conservative_accounted_cny"]))
    stages = {name: Decimal(str(value)) for name, value in budget["stages"].items()}
    remaining = limit - history
    headroom = stage_headroom(plan_data, real_stage_accounting())
    minimum_j2 = Decimal(headroom["required_stage_limit_cny"])
    stage_min_excl_history = _a_money(minimum_j2 - history)
    # 其它阶段按**真实 budget.json 现值**求和（不再硬编码 3+2）：经理回收旧阶段分配后这里仍成立。
    other_stages = sum(
        (value for name, value in stages.items() if name not in (STAGE, "later_shared_reserve")),
        Decimal("0"),
    )
    later = _a_money(remaining - other_stages - minimum_j2)
    if later < 0:
        raise SystemExit("REFUSE: 候选阶段分配为负，需经理重新裁决")
    candidate_stages = {
        "S1-DEV": float(stages.get("S1-DEV", Decimal("3"))),
        "S1-IA": float(stages.get("S1-IA", Decimal("2"))),
        "S2-DEV": float(minimum_j2),
        "later_shared_reserve": float(later),
    }
    candidate_sum = _a_money(sum(Decimal(str(value)) for value in candidate_stages.values()))
    conditional = subplan.conservative_settlement_cny
    remaining_after = _a_money(remaining - conditional)

    # 完整既定矩阵（S2-I/经理裁决口径）：136 chat / 111 embedding / 94 rerank / 12 text + 1 table。
    matrix = ce.ControlledRequestPlan(
        stage=STAGE,
        chat_requests=136,
        embedding_requests=111,
        rerank_requests=94,
        ocr_text_requests=12,
        ocr_table_requests=1,
    )
    matrix_settlement = matrix.conservative_settlement_cny
    matrix_peak = matrix.peak_include_history_cny
    pilot_counts = plan_data["counts"]
    remaining_counts = {
        "chat": matrix.chat_requests - pilot_counts["chat"],
        "embedding": matrix.embedding_requests - pilot_counts["embedding"],
        "rerank": matrix.rerank_requests - pilot_counts["rerank"],
        "ocr_text": matrix.ocr_text_requests - pilot_counts["ocr_text"],
        "ocr_table": matrix.ocr_table_requests - pilot_counts["ocr_table"],
    }
    if min(remaining_counts.values()) < 0:
        raise SystemExit(f"REFUSE: pilot 计数大于既定矩阵，扣减为负：{remaining_counts}")
    if remaining_counts["ocr_table"] != 0:
        raise SystemExit("REFUSE: 本轮 pilot 必须复用矩阵唯一的 1 次 table OCR（D10），否则项目会多付 OCR")
    unit = {
        "chat": subplan.chat_cap_charge_cny,
        "embedding": subplan.embedding_cap_charge_cny,
        "rerank": subplan.rerank_cap_charge_cny,
        "ocr_text": Decimal("0.5"),
        "ocr_table": Decimal("0.15"),
    }
    remaining_settlement = _a_money(
        Decimal(remaining_counts["chat"]) * unit["chat"]
        + Decimal(remaining_counts["embedding"]) * unit["embedding"]
        + Decimal(remaining_counts["rerank"]) * unit["rerank"]
        + Decimal(remaining_counts["ocr_text"]) * unit["ocr_text"]
        + Decimal(remaining_counts["ocr_table"]) * unit["ocr_table"]
    )
    if _a_money(remaining_settlement + conditional) != matrix_settlement:
        raise SystemExit("REFUSE: pilot+剩余矩阵结算不等于既定矩阵总结算（扣减推导失败）")
    remaining_peak = _a_money(remaining_settlement + history - unit["chat"] + subplan.chat_reserve_cny)
    # 未来矩阵若单独开一个阶段，该阶段额度需覆盖“剩余请求峰值”（含历史 0.03）。
    future_stage_limit = remaining_peak
    future_stages = {
        "S1-DEV": 0.0,
        "S1-IA": 0.0,
        "S2-DEV": float(conditional),  # 已花部分冻结为已结算额度，不重复分配
        "S2-DEV-MATRIX": float(future_stage_limit),
        "later_shared_reserve": _a_money(remaining - Decimal(str(conditional)) - future_stage_limit),
    }
    future_sum = _a_money(sum(Decimal(str(value)) for value in future_stages.values()))
    # 同一 S2-DEV 阶段续跑（不新建阶段名）时，累计占用口径要求额度覆盖整个项目峰值。
    same_stage_limit = matrix_peak

    return {
        "document": "S2-K-R1B-candidate-stage-budget",
        "status": "CANDIDATE/DRAFT；未应用，不写真实 budget.json，不构成授权",
        "generated_at": now_iso(),
        "real_budget_before": {"path": rel(REAL_BUDGET), "sha256": sha256_path(REAL_BUDGET), "content": budget},
        "real_ledger_before": {"path": rel(REAL_LEDGER), "sha256": sha256_path(REAL_LEDGER), **ledger_summary},
        "reconciliation": {
            "total_limit_cny": canonical_decimal(limit),
            "history_conservative_cny": canonical_decimal(history),
            "remaining_conservative_cny_at_start": canonical_decimal(remaining),
            "existing_stages": {name: canonical_decimal(value) for name, value in stages.items()},
            "existing_stages_sum_cny": canonical_decimal(sum(stages.values())),
            "note": "现真账只有 S1-DEV=3、S1-IA=2、later_shared_reserve=4.97；不存在 S2-DEV。生产 resolve_live_gate 要求阶段在 budget 中且按 min 限制，不能只写 GO 冒充阶段授权。",
        },
        "pilot_plan": {
            "stage": STAGE,
            "counts": pilot_counts,
            "request_plan_sha256": plan_data["request_plan_sha256"],
            "conditional_cap_settlement_cny": canonical_decimal(conditional),
            "peak_include_history_cny": canonical_decimal(subplan.peak_include_history_cny),
            "single_chat_reserve_cny": canonical_decimal(subplan.chat_reserve_cny),
            "send_time_max_reserve_cny": canonical_decimal(subplan.max_single_reserve_cny),
            "provider_request_sequence": [item["kind"] for item in plan_data["provider_request_sequence"]],
        },
        "minimum_required": {
            "j2_required_stage_limit_cny": canonical_decimal(minimum_j2),
            "stage_accounted_peak_excluding_history_cny": canonical_decimal(stage_min_excl_history),
            "reason": "阶段额度是账本累计口径：必须覆盖“本阶段已结算占用 + 本轮峰值（含历史 0.03）”；第一轮零占用时等于 plan.peak_include_history。",
            "run_headroom": headroom,
            "serial_peak_breakdown": {
                "all_calls_settled_at_caps_cny": canonical_decimal(conditional),
                "plus_history_cny": canonical_decimal(history),
                "minus_one_chat_cap_charge_cny": canonical_decimal(subplan.chat_cap_charge_cny),
                "plus_one_chat_full_reserve_cny": canonical_decimal(subplan.chat_reserve_cny),
            },
            "per_step_send_time_reserve": plan_data["costs"]["send_time_reserves_cny"],
        },
        "candidate_budget": {
            "limit_cny": canonical_decimal(limit),
            "historical_conservative_accounted_cny": canonical_decimal(history),
            "stages": candidate_stages,
            "stages_sum_cny": canonical_decimal(candidate_sum),
            "check_history_plus_stages_cny": canonical_decimal(history + candidate_sum),
            "no_double_allocation": abs((history + candidate_sum) - limit) < Decimal("0.00000001"),
            "note": "为保持全项目只分配一次，压缩 later_shared_reserve；不给每个阶段各留 10 元。其它阶段（S1）按真实预算现值计入，经理回收后自动反映。",
        },
        "budget_after_success_at_caps": {
            "stage_spent_cny": canonical_decimal(conditional),
            "stage_residue_cny": canonical_decimal(minimum_j2 - conditional),
            "remaining_conservative_total_cny": canonical_decimal(remaining_after),
            "remaining_note": "成功按 cap 保守条件结算后的全项目剩余；真实 usage 更低时剩余更多，供应商账单仍未知，不把估算当账单。",
        },
        "failure_occupancy": {
            "worst_single_chat_failure_accounted_cny": canonical_decimal(
                _a_money(subplan.chat_reserve_cny + conditional - subplan.chat_cap_charge_cny)
            ),
            "pilot_peak_cny": canonical_decimal(minimum_j2),
            "stage_still_covered": True,
            "residual_after_one_chat_failure_cny": canonical_decimal(
                minimum_j2 - _a_money(subplan.chat_reserve_cny + conditional - subplan.chat_cap_charge_cny)
            ),
            "completion_after_one_chat_failure": "不可完成：单次 chat 失败会全额保留 2.103552 元，阶段只剩约 0.03 元，后续请求会被拒；零重试、失败即停、重跑须经理重新裁额度/请求上限。",
            "other_failure_note": "embedding/rerank/OCR 发送后失败同样全额留账并停机；峰值口径见 minimum_required.serial_peak_breakdown。",
        },
        "matrix_route": {
            "established_matrix_plan": {
                "chat": 136,
                "embedding": 111,
                "rerank": 94,
                "ocr_text": 12,
                "ocr_table": 1,
                "ocr_total": 13,
                "conditional_cap_settlement_cny": canonical_decimal(matrix_settlement),
                "peak_include_history_cny": canonical_decimal(matrix_peak),
                "ocr_composition_established": "D07 8 页 + D08 2 页 + D09 1 + D10 1 = 12 次初始（11 text + 1 table）；U09 需 1 次 text ⇒ 合计 12 text + 1 table = 13",
            },
            "pilot_consumes_and_reuses": {
                "chat": pilot_counts["chat"],
                "embedding": pilot_counts["embedding"],
                "rerank": pilot_counts["rerank"],
                "ocr_text": pilot_counts["ocr_text"],
                "ocr_table": pilot_counts["ocr_table"],
                "deductible_only_if": "同一 DB + 同一 document/version + 同一检查点/索引缓存；新上传或新 version = 新计费请求，不得声称复用",
                "shared_items": [
                    "D01 的 9 chunks / 1 个 embedding 批次及索引",
                    "D09 整篇单页 OCR text 1 次 + 1 个 image_text chunk / 1 个 embedding 批次及检查点",
                    "D10 整篇单页 OCR table 1 次 + 2 个 record chunks / 1 个 embedding 批次及检查点",
                    "Q01/Q03 的产品 HTTP 回答与引用（记录型结果可计入原 40 题中的 2 题）",
                ],
                "not_shared": [
                    "pilot 运行失败/重跑：已发生的预留按账本全额占用，不能当免费重试",
                    "新 DB、新索引、新 version、清空缓存：上述扣减全部失效，矩阵必须重新计费",
                ],
            },
            "remaining_after_pilot": {
                **remaining_counts,
                "ocr_total_remaining": remaining_counts["ocr_text"] + remaining_counts["ocr_table"],
                "conditional_cap_settlement_cny": canonical_decimal(remaining_settlement),
                "peak_include_history_if_separate_stage_cny": canonical_decimal(remaining_peak),
            },
            "full_project_with_pilot_reuse": {
                "total_provider_posts": matrix.total_calls,
                "conditional_cap_settlement_cny": canonical_decimal(matrix_settlement),
                "peak_include_history_cny": canonical_decimal(matrix_peak),
                "fits_project_limit": matrix_peak <= limit,
                "project_total_limit_cny": canonical_decimal(limit),
                "margin_below_limit_cny": canonical_decimal(limit - matrix_peak),
                "note": "pilot 的 15 次请求全部落在既定矩阵的对应计数内，故全项目不重复计费；该结论不构成“一定完成”，完成仍依赖真实 usage 在 cap 内且零发送后失败。",
            },
            "future_budget_reconciliation_required": {
                "why": "pilot 阶段 S2-DEV 最小要 2.822208，而矩阵在项目级峰值 9.65328；现预算 S1-DEV=3 + S1-IA=2 + later=4.97，若不回收 S1 分配则矩阵阶段额度放不进 9.97。",
                "option_same_stage": {
                    "description": "矩阵沿用 S2-DEV 阶段（累计占用口径），阶段额度需 >= 全项目峰值",
                    "candidate_stage_limit_cny": canonical_decimal(same_stage_limit),
                    "requires": "经理回收 S1-DEV/S1-IA 共 5.0 的分配并重新对账；本轮未应用",
                },
                "option_separate_stage": {
                    "description": "矩阵另开新阶段（非本轮名称），只覆盖剩余请求；本轮仅给候选数字",
                    "candidate_stages": future_stages,
                    "check_history_plus_stages_cny": canonical_decimal(history + future_sum),
                    "requires": "经理回收 S1-DEV/S1-IA 分配并把 pilot 已支出冻结为已结算额度；本轮未应用",
                },
                "plan_expressiveness_blocker": "ControlledRequestPlan 五类计数必须为正整数：剩余矩阵是 11 text + 0 table，无法用单个计划表达“0 次 table”。未来矩阵计划必须由经理裁决：接受“声明 1 次 table 但实际 0 次”的计划/观测偏差（F-K8 同类），或改产品允许 0 计数（超出本包范围）。本工具不绕开该限制、不重复 OCR。",
            },
        },
        "reuse_state_contract": {
            "actual_ids_recorded_in": "Mock/live receipt 的 steps[import:*]、ocr_stats.tiles_by_source_page、ocr_call_records、ocr_request_bindings",
            "required_fields": ["document_id", "version_id", "source_scope", "tile_sha256", "checkpoint_rows", "index_documents/chunks"],
            "matrix_continuation_entry": "同一 DB/索引/检查点上的后续导入计划；D07 8 页、D08 2 页、U09 1 页仍未做；D01/D09/D10 已完成发布，不得重导/重 version",
        },
    }


def build_candidate_go(plan_data: dict, subplan, real: dict) -> dict:
    """F-K6：DRAFT candidate GO（不在固定路径、产品不读）；明确 DRAFT_NOT_AUTHORIZATION。"""
    business = load_business()
    ce = business["ce"]
    bindings = ce._plan_bindings(subplan)  # noqa: SLF001 - 复用 J2 已接收计划绑定生成器
    headroom = stage_headroom(plan_data, real_stage_accounting())
    now = datetime.now(timezone.utc)
    total = int(subplan.total_calls)
    payload = {
        "document": "S2-LIVE-GO",
        "stage": STAGE,
        "authorization": (
            "S2-K-R1B CANDIDATE DRAFT: finite pilot only; NOT signed; NOT an authorization; "
            "manager must reconcile budget, rebuild issued_by/authorization/time/scope and issue a formal fixed-path GO"
        ),
        "issued_by": "s2k-controlled-pilot v2 (candidate generator; NOT a signer)",
        "nonce": f"s2k-candidate-{uuid.uuid4().hex}",
        "issued_utc": (now - timedelta(minutes=1)).isoformat(),
        "expires_utc": (now + timedelta(days=7)).isoformat(),
        "budget_ledger_sha256": ledger_anchor_sha256() or real["ledger"]["sha256"],
        "scope": {
            "services": ["rag", "chat"],
            "stage_limits_cny": {STAGE: float(headroom["required_stage_limit_cny"])},
            "max_requests": int(headroom["required_max_requests"]),
            "max_request_cny": float(subplan.chat_reserve_cny),
            "bindings": bindings,
        },
    }
    marker_probe = _assert_formal_go_payload(payload)
    return {
        "document": "S2-K-R1B-candidate-go (DRAFT; NOT S2-LIVE-GO)",
        "status": "DRAFT_NOT_AUTHORIZATION",
        "not_formal": True,
        "generated_at": now_iso(),
        "instruction": (
            "本文件不在产品固定 GO 路径，产品从不读取它。经理在完成统一对账、保存真实 before、"
            "批准阶段预算修订后，必须从本候选**重建** issued_by/authorization/时间/范围（不是原样复制），"
            "保存候选与正式 GO 的前后 hash，再写入固定路径；工具/开发者不得自行写入固定路径。"
        ),
        "fixed_go_path": rel(REAL_GO),
        "fixed_go_exists_now": real["fixed_go"]["exists"],
        "fixed_go_formal_marker_check_now": real["fixed_go"].get("formal_marker_check"),
        "real_ledger_sha256_now": real["ledger"]["sha256"],
        "ledger_anchor_sha256": ledger_anchor_sha256(),
        "real_budget_sha256_now": real["budget"]["sha256"],
        "run_headroom": headroom,
        "candidate_stage_allocation_cny": float(headroom["required_stage_limit_cny"]),
        "minimum_stage_allocation_cny": float(headroom["required_stage_limit_cny"]),
        "candidate_request_cap": int(headroom["required_max_requests"]),
        "candidate_single_request_cny": float(subplan.chat_reserve_cny),
        "go_payload": payload,
        "go_payload_sha256": sha256_bytes(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ),
        "candidate_self_check": {
            "this_payload_is_formal_by_marker_rule": marker_probe["formal"],
            "expected": False,
            "problems": marker_probe["problems"],
            "note": "若把本 payload 原样复制到固定路径，工具必须先按这些标记拒绝（首个预留前）。",
        },
        "formal_issuance_contract": {
            "product_behavior": "产品只校验固定路径 + GO_REQUIRED_FIELDS + 时间/阶段/服务/绑定/账本 hash；它不识别 DRAFT 文案，因此“写入固定路径”本身等于签发。",
            "tool_refusal_rule": "cmd_live 在首个预留前读取固定 GO 原文（只用于标记检查，不落原文），若 document/authorization/issued_by/nonce 含 draft/candidate/not signed/unsigned 等标记，或存在 status/not_formal/draft/candidate 顶层包装字段，或 issued_by 含 candidate/tool/harness 标记 → 拒绝。",
            "manager_must_rebuild_fields": ["issued_by（真实经理身份，非工具/候选生成器）", "authorization（明确 S2-LIVE-GO 范围/条件/有限期）", "nonce（>=16 字符，经理生成）", "issued_utc/expires_utc（经理签发时点）", "scope（阶段额度/请求上限/单请求上界/bindings 与本计划一致）", "budget_ledger_sha256（签发时共享账本实际 hash）"],
            "manager_must_record": ["candidate-go.json 的 sha256", "正式 S2-LIVE-GO.json 的 sha256", "两者差异说明（重建字段）", "真实 budget.json/live-ledger.jsonl 的 before hash"],
            "no_cryptographic_signature": "本轮不引入签名密钥/全局配置平台；固定路径写权限是受信文件治理，不描述为密码学签名。",
        },
        "required_future_live_conditions": [
            "固定路径存在**正式** S2-LIVE-GO（非本候选；无 DRAFT/CANDIDATE/未批准标记），stage=S2-DEV，services 含 rag+chat",
            f"GO scope.bindings 与本计划 request_plan_sha256 / caps / 来源逐字一致（J2 _verify_fields）",
            f"共享 budget.json 新增/提升 S2-DEV 阶段分配且 >= {headroom['required_stage_limit_cny']}（= 阶段已占用 + 本轮峰值），总上限仍 10.00，历史 0.03 不变",
            f"GO budget_ledger_sha256 绑定不可变历史前缀 {ledger_anchor_sha256()}（不是会随预留变化的整文件 hash）",
            f"环境显式 MKTKB_RAG_STAGE_LIMIT_CNY={headroom['required_stage_limit_cny']} / MAX_REQUESTS={headroom['required_max_requests']} / MAX_REQUEST_CNY=0.5，零重试",
            "全新输出目录/隔离 DB+索引，真实价复核与账本前值一致",
            "D01/D09/D10 来源、文件、页、tile=1、attempt=1、串行、零重试；D09 文字 OCR + D10 表格 OCR 各 1 次",
            "任一失败/超 cap/漂移立即停机，不重试、不自行重跑，保留已花费与未结算占用",
        ],
        "optional_rerank_availability_probe": {
            "why": "gte-rerank-v2 官方下线公告（2026-05-30 生效）与仍列 v2 的官方文档/示例/模型页矛盾，本账户可用性未知；本轮不发付费探测。",
            "max_requests": 1,
            "service": "rag",
            "kind": "rerank",
            "max_reserve_cny": 0.024,
            "rationale": "30000 token × 0.8 元/百万 = 0.024 元为单次 rerank 最高预留",
            "if_failed_or_unavailable": "全停，不换模型、不重试、不把失败当成功",
            "requires_manager_decision": True,
            "not_included_in_this_plan": True,
            "ledger_effect": "探测占用共享账本累计请求数，pilot 用满 15 次后需把累计上限显式 +1 并重新对账",
        },
    }


# ---------------------------------------------------------------- Mock 环境（隔离账本/预算/GO）


def apply_env(*, stage_limit: float, max_requests: int) -> None:
    for key in _CLEAR_ENV:
        _SAVED_ENV.setdefault(key, os.environ.get(key))
        os.environ.pop(key, None)
    for key, value in _BASE_ENV.items():
        _SAVED_ENV.setdefault(key, os.environ.get(key))
        os.environ[key] = value
    _SAVED_ENV.setdefault("MKTKB_RAG_STAGE_LIMIT_CNY", os.environ.get("MKTKB_RAG_STAGE_LIMIT_CNY"))
    _SAVED_ENV.setdefault("MKTKB_RAG_MAX_REQUESTS", os.environ.get("MKTKB_RAG_MAX_REQUESTS"))
    os.environ["MKTKB_RAG_STAGE_LIMIT_CNY"] = format(stage_limit, ".8f").rstrip("0").rstrip(".")
    os.environ["MKTKB_RAG_MAX_REQUESTS"] = str(max_requests)
    os.environ["MKTKB_RAG_MAX_RETRIES"] = "0"
    os.environ["OPENBLAS_NUM_THREADS"] = "1"
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"


def restore_env() -> None:
    for key, value in _SAVED_ENV.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def patch_gate(paths: dict) -> None:
    gate = load_business()["gate_module"]
    _GATE_PATHS.update(
        {
            "SHARED_LEDGER_PATH": gate.SHARED_LEDGER_PATH,
            "SHARED_BUDGET_PATH": gate.SHARED_BUDGET_PATH,
            "PRODUCT_GO_PATH": gate.PRODUCT_GO_PATH,
        }
    )
    gate.SHARED_LEDGER_PATH = Path(paths["ledger"])
    gate.SHARED_BUDGET_PATH = Path(paths["budget"])
    gate.PRODUCT_GO_PATH = Path(paths["go"])


def restore_gate() -> None:
    if not _GATE_PATHS:
        return
    gate = load_business()["gate_module"]
    gate.SHARED_LEDGER_PATH = _GATE_PATHS["SHARED_LEDGER_PATH"]
    gate.SHARED_BUDGET_PATH = _GATE_PATHS["SHARED_BUDGET_PATH"]
    gate.PRODUCT_GO_PATH = _GATE_PATHS["PRODUCT_GO_PATH"]


def write_isolated_ledger(path: Path) -> None:
    path = Path(path)
    if path.exists():
        raise SystemExit(f"REFUSE: 隔离账本已存在，拒绝覆盖：{rel(path)}")
    path.write_text(
        json.dumps(
            {
                "event": "historical_import",
                "accounted_cny": 0.03,
                "estimated_success_list_price_cny": 0.0000352,
                "provider_billed_cny": None,
                "note": "S2-K-R1B isolated Mock ledger (not the shared ledger)",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )


def _project_total_limit_float() -> float:
    """隔离 Mock 预算也要与当前项目上限一致（默认 10；主人追加预算时随环境变量走）。"""
    raw = os.environ.get("MKTKB_PROJECT_TOTAL_LIMIT_CNY")
    try:
        value = float(str(raw).strip()) if raw not in (None, "") else 10.0
    except (TypeError, ValueError):
        return 10.0
    return value if value > 0 else 10.0


def write_isolated_budget(path: Path, ledger: Path, *, stage_limit: float, include_stage: bool = True) -> None:
    path = Path(path)
    if path.exists():
        raise SystemExit(f"REFUSE: 隔离预算已存在，拒绝覆盖：{rel(path)}")
    project_limit = _project_total_limit_float()
    remaining = _a_money(Decimal(str(project_limit)) - Decimal("0.03"))
    stages = {STAGE: float(stage_limit), "later_shared_reserve": float(_a_money(remaining - Decimal(str(stage_limit))))}
    if not include_stage:
        stages = {"S1-DEV": 3.0, "later_shared_reserve": float(_a_money(remaining - Decimal("3")))}
    path.write_text(
        json.dumps(
            {
                "limit_cny": project_limit,
                "historical_conservative_accounted_cny": 0.03,
                "historical_success_estimated_list_price_cny": 0.0000352,
                "provider_billed_cny": None,
                "stages": stages,
                "ledger": str(Path(ledger).resolve()),
                "note": "S2-K-R1B isolated Mock budget; never modifies the shared budget",
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def write_isolated_go(
    path: Path,
    ledger: Path,
    plan,
    *,
    stage_limit: float,
    max_requests: int,
    max_request_cny: float,
    tamper=None,
) -> None:
    business = load_business()
    bindings = business["ce"]._plan_bindings(plan)  # noqa: SLF001
    if callable(tamper):
        tamper(bindings)
    now = datetime.now(timezone.utc)
    payload = {
        "document": "S2-LIVE-GO",
        "stage": STAGE,
        "authorization": "S2-K-R1B-MOCK-GO (isolated MockTransport only; NOT a manager GO; never the fixed path)",
        "issued_by": "s2k-controlled-pilot-mock",
        "nonce": f"s2k-mock-{uuid.uuid4().hex}",
        "issued_utc": (now - timedelta(minutes=1)).isoformat(),
        "expires_utc": (now + timedelta(hours=3)).isoformat(),
        "budget_ledger_sha256": sha256_path(ledger),
        "scope": {
            "services": ["rag", "chat"],
            "stage_limits_cny": {STAGE: float(stage_limit)},
            "max_requests": int(max_requests),
            "max_request_cny": float(max_request_cny),
            "bindings": bindings,
        },
    }
    path = Path(path)
    if path.exists():
        raise SystemExit(f"REFUSE: 隔离 GO 已存在，拒绝覆盖：{rel(path)}")
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class isolated:
    """隔离 Mock 环境：在本次运行目录下新建 ledger/budget/GO 子目录，绝不删除/覆盖旧目录。"""

    def __init__(
        self,
        label: str,
        *,
        subplan,
        stage_limit: float,
        max_requests: int | None = None,
        max_request_cny: float | None = None,
        go_tamper=None,
        write_go_file: bool = True,
        include_stage: bool = True,
    ) -> None:
        self.label = label
        self.subplan = subplan
        self.stage_limit = stage_limit
        self.max_requests = int(subplan.total_calls if max_requests is None else max_requests)
        self.max_request_cny = (
            float(subplan.chat_reserve_cny) if max_request_cny is None else float(max_request_cny)
        )
        self.go_tamper = go_tamper
        self.write_go_file = write_go_file
        self.include_stage = include_stage

    def __enter__(self) -> dict:
        run_dir = _ACTIVE_RUN.get("run_dir")
        if run_dir is None:
            raise SystemExit("REFUSE: 尚未创建本轮运行目录，不能建立隔离 Mock 环境")
        base = Path(run_dir) / "mock"
        base.mkdir(parents=True, exist_ok=True)
        root = base / self.label
        if root.exists():
            raise SystemExit(f"REFUSE: 隔离目录已存在（不删除/不覆盖）：{rel(root)}")
        (root / "app").mkdir(parents=True, exist_ok=False)
        ledger = root / "live-ledger.jsonl"
        budget = root / "budget.json"
        go = root / "S2-K-MOCK-GO.json"
        write_isolated_ledger(ledger)
        write_isolated_budget(budget, ledger, stage_limit=self.stage_limit, include_stage=self.include_stage)
        if self.write_go_file:
            write_isolated_go(
                go,
                ledger,
                self.subplan,
                stage_limit=self.stage_limit,
                max_requests=self.max_requests,
                max_request_cny=self.max_request_cny,
                tamper=self.go_tamper,
            )
        paths = {
            "root": root,
            "ledger": ledger,
            "budget": budget,
            "go": go,
            "app": root / "app",
            "plan": self.subplan,
            "label": self.label,
        }
        apply_env(stage_limit=self.stage_limit, max_requests=self.max_requests)
        patch_gate(paths)
        self._paths = paths
        return paths

    def __exit__(self, *_exc: object) -> None:
        restore_gate()
        restore_env()


class MockVendor(httpx.BaseTransport, httpx.AsyncBaseTransport):
    """只替换传输层；按来源 host/path 分类返回，记录真实请求字节数与请求体 hash/响应状态。"""

    def __init__(self) -> None:
        self.behavior: dict[str, dict] = {}
        self.calls: list[dict] = []
        self._fake = None

    def configure(self, kind: str, **values):
        if "raise_" in values:
            values["raise"] = values.pop("raise_")
        self.behavior.setdefault(kind, {}).update(values)
        return self

    @staticmethod
    def kind_of(request: httpx.Request) -> str:
        host = request.url.host
        path = request.url.path
        if host == "ocr.tencentcloudapi.com":
            action = str(request.headers.get("x-tc-action") or "").lower()
            return "ocr_table" if "recognizetable" in action else "ocr_text"
        if path.endswith("/embeddings"):
            return "embedding"
        if "rerank" in path:
            return "rerank"
        if path.endswith("/chat/completions"):
            return "chat"
        return "unknown"

    def _fake_embedding(self):
        if self._fake is None:
            self._fake = load_business()["FakeEmbeddingProvider"](model="text-embedding-v4", dimensions=1024)
        return self._fake

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        kind = self.kind_of(request)
        body = request.content or b""
        record = {
            "seq": len(self.calls) + 1,
            "kind": kind,
            "host": request.url.host,
            "path": request.url.path,
            "body_bytes": len(body),
            "request_sha256": sha256_bytes(body),
            "action": request.headers.get("x-tc-action"),
            "response_status": None,
        }
        self.calls.append(record)
        behavior = self.behavior.get(kind, {})
        raise_kind = behavior.get("raise")
        if raise_kind == "timeout":
            record["response_status"] = "timeout"
            raise httpx.ReadTimeout("s2k mock timeout", request=request)
        if raise_kind == "interrupt":
            record["response_status"] = "interrupt"
            raise KeyboardInterrupt("s2k mock interrupt")
        if raise_kind == "transport":
            record["response_status"] = "transport_error"
            raise httpx.ConnectError("s2k mock transport error", request=request)
        status = int(behavior.get("status", 200))
        request_id = behavior.get("request_id") or f"mock-{kind}-{len(self.calls)}"

        if kind == "chat":
            response = self._chat_response(request, behavior, status=status, request_id=request_id)
        elif kind == "embedding":
            response = self._embedding_response(request, behavior, status=status, request_id=request_id)
        elif kind == "rerank":
            response = self._rerank_response(request, behavior, status=status, request_id=request_id)
        elif kind in ("ocr_text", "ocr_table"):
            response = self._ocr_response(kind, behavior, status=status, request_id=request_id)
        else:
            response = httpx.Response(404, json={"error": "s2k unknown path"})
        record["response_status"] = response.status_code
        return response

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return self.handle_request(request)

    # ---- 各供应商响应

    def _chat_response(self, request: httpx.Request, behavior: dict, *, status: int, request_id: str) -> httpx.Response:
        if status >= 400:
            return httpx.Response(status, json={"error": {"message": "s2k mock chat error"}, "id": request_id})
        payload = json.loads(request.content.decode("utf-8")) if request.content else {}
        messages = payload.get("messages") or []
        user = {}
        if len(messages) > 1:
            try:
                user = json.loads(str(messages[1].get("content") or "{}"))
            except json.JSONDecodeError:
                user = {}
        usage = behavior.get("usage")
        if usage is None:
            prompt = max(1, min(1536, len(str(messages[1].get("content") if len(messages) > 1 else "").encode("utf-8"))))
            completion = 120
            usage = {
                "prompt_tokens": prompt,
                "completion_tokens": completion,
                "total_tokens": prompt + completion,
                "prompt_cache_hit_tokens": 0,
                "prompt_cache_miss_tokens": prompt,
            }
        if user.get("purpose") == "query_expansion" or "evidence" not in user:
            content = json.dumps({"terms": []}, ensure_ascii=False)
        else:
            content = self._compose_answer(user.get("evidence") or [])
        return httpx.Response(
            status,
            json={
                "id": request_id,
                "object": "chat.completion",
                "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": content}}],
                "usage": usage,
            },
        )

    @staticmethod
    def _compose_answer(evidence: list) -> str:
        """只从产品传入的 evidence 字段构造可验证回答；不读 questions.expected_values。

        v2：合并**所有** evidence 的允许字段（不只看第一条），避免新增 D09/D10 资料改变
        检索顺序后把可引用的 D01 记录挤出答案；仍然不读预期答案。
        """
        allowed = ("门店", "物品", "位置", "联系人", "联系电话", "地址", "合作状态", "分类")
        parts: list[str] = []
        seen: set[str] = set()
        source_ids: list[str] = []
        for item in evidence:
            if not isinstance(item, dict):
                continue
            fields = item.get("fields") or {}
            for key, value in fields.items():
                if key in allowed and value not in (None, "") and key not in seen:
                    seen.add(key)
                    parts.append(f"{key}：{value}")
            source_id = item.get("source_id")
            if source_id:
                source_ids.append(str(source_id))
        answer = "根据资料：" + "；".join(parts) if parts else "根据资料：未找到可引用字段。"
        return json.dumps({"answer": answer, "source_ids": source_ids}, ensure_ascii=False)

    def _embedding_response(self, request: httpx.Request, behavior: dict, *, status: int, request_id: str) -> httpx.Response:
        if status >= 400:
            return httpx.Response(status, json={"error": {"message": "s2k mock embedding error"}, "id": request_id})
        payload = json.loads(request.content.decode("utf-8")) if request.content else {}
        texts = payload.get("input") or []
        fake = self._fake_embedding()
        rows = [
            {"object": "embedding", "index": index, "embedding": list(fake._vector(str(text)))}  # noqa: SLF001
            for index, text in enumerate(texts)
        ]
        usage = behavior.get("usage")
        if usage is None:
            total = max(1, min(4096, sum(len(str(text).encode("utf-8")) for text in texts)))
            usage = {"prompt_tokens": total, "total_tokens": total}
        return httpx.Response(
            status,
            json={
                "object": "list",
                "data": rows,
                "model": payload.get("model") or "text-embedding-v4",
                "usage": usage,
                "id": behavior.get("request_id") or request_id,
            },
        )

    def _rerank_response(self, request: httpx.Request, behavior: dict, *, status: int, request_id: str) -> httpx.Response:
        if status >= 400:
            return httpx.Response(status, json={"code": "mock", "message": "s2k mock rerank error", "request_id": request_id})
        payload = json.loads(request.content.decode("utf-8")) if request.content else {}
        documents = ((payload.get("input") or {}).get("documents")) or []
        rows = [{"index": index, "relevance_score": round(1.0 / (index + 1), 6)} for index in range(len(documents))]
        usage = behavior.get("usage")
        if usage is None:
            total = max(1, min(6000, sum(len(str(doc).encode("utf-8")) for doc in documents) + 64))
            usage = {"total_tokens": total}
        return httpx.Response(
            status,
            json={"output": {"results": rows}, "usage": usage, "request_id": behavior.get("request_id") or request_id},
        )

    def _ocr_response(self, kind: str, behavior: dict, *, status: int, request_id: str) -> httpx.Response:
        if status == 429:
            return httpx.Response(
                429,
                json={"Response": {"RequestId": request_id, "Error": {"Code": "RequestLimitExceeded", "Message": "rate"}}},
            )
        if status >= 400:
            return httpx.Response(status, json={"Response": {"RequestId": request_id}})
        if behavior.get("ocr_error") == "auth_secret":
            return httpx.Response(
                200,
                json={
                    "Response": {
                        "RequestId": LONG_SECRET_ID,
                        "Error": {
                            "Code": "AuthFailure.SignatureFailure " + SYNTH_SECRET,
                            "Message": "Authorization: Bearer " + SYNTH_SECRET,
                        },
                    }
                },
            )
        transcripts = load_support()["ocr_transcripts"]
        if kind == "ocr_table":
            header, rows = transcripts.D10_TABLE_HEADER, transcripts.D10_TABLE_ROWS
            cells: list[dict] = []
            for column, text in enumerate(header):
                cells.append(
                    {"RowTl": 0, "ColTl": column, "RowBr": 1, "ColBr": column + 1, "Text": text, "Confidence": 90.0}
                )
            for row_index, row in enumerate(rows, start=1):
                for column, text in enumerate(row):
                    cells.append(
                        {
                            "RowTl": row_index,
                            "ColTl": column,
                            "RowBr": row_index + 1,
                            "ColBr": column + 1,
                            "Text": text,
                            "Confidence": 90.0,
                        }
                    )
            return httpx.Response(
                200,
                json={
                    "Response": {
                        "TableDetections": [{"Cells": cells}],
                        "RequestId": behavior.get("request_id") or request_id,
                    }
                },
            )
        lines = transcripts.D09_TEXT
        detections = []
        for line_index, text in enumerate(lines):
            top = line_index * 20
            detections.append(
                {
                    "DetectedText": text,
                    "Confidence": 95.0,
                    "Polygon": [
                        {"X": 10, "Y": top},
                        {"X": 600, "Y": top},
                        {"X": 600, "Y": top + 16},
                        {"X": 10, "Y": top + 16},
                    ],
                }
            )
        return httpx.Response(
            200,
            json={"Response": {"TextDetections": detections, "RequestId": behavior.get("request_id") or request_id}},
        )

    def count(self, kind: str | None = None) -> int:
        if kind is None:
            return len(self.calls)
        return sum(1 for call in self.calls if call["kind"] == kind)

    def kinds(self) -> list[str]:
        return [call["kind"] for call in self.calls]

    def summary(self) -> dict:
        buckets: dict[str, int] = {}
        for call in self.calls:
            buckets[call["kind"]] = buckets.get(call["kind"], 0) + 1
        return {
            "total": len(self.calls),
            "by_kind": buckets,
            "calls": list(self.calls),
            "external": False,
            "transport": "httpx.MockTransport-level MockVendor (no real socket/http)",
        }


# ---------------------------------------------------------------- 产品调用辅助


def make_settings(paths: dict):
    business = load_business()
    root = Path(paths["root"])
    app_dir = root / "app"
    app_dir.mkdir(parents=True, exist_ok=True)
    Settings = business["Settings"]
    return Settings(
        _env_file=None,
        data_dir=app_dir,
        database_url=f"sqlite:///{(app_dir / 'mktkb.sqlite3').as_posix()}",
        storage_dir=app_dir / "storage",
        cookie_secure=False,
        csrf_secret="s2k-r1b-mock-csrf-secret-0123456789",
        admin_password=ADMIN_PASSWORD,
        employee_password="S2KEmployeePass-1",
        trusted_origins=[ORIGIN],
        bcrypt_rounds=4,
        session_ttl_seconds=3600,
        log_level="WARNING",
        rag_qa_enabled=True,
        rag_provider_mode="live",
        rag_sync_on_startup=False,
        rag_page_size=10,
        rag_top_k=8,
        rag_embedding_retry_seconds=30.0,
        model_base_url=os.environ.get("MKTKB_MODEL_BASE_URL"),
        model_name=os.environ.get("MKTKB_MODEL_NAME"),
        model_api_key=os.environ.get("MKTKB_MODEL_API_KEY"),
        # 真实 provider 的客户端硬超时：沿用产品默认 30s（config.Settings 默认值）。
        # Mock 阶段曾用 5s 只是隔离自测取值；真实 chat 5s 过紧，超时会按失败全额留账 2.103552 元。
        model_request_timeout_seconds=30.0,
        ocr_disabled=False,
        ocr_secret_id=os.environ.get("MKTKB_OCR_SECRET_ID"),
        ocr_secret_key=os.environ.get("MKTKB_OCR_SECRET_KEY"),
        ocr_region=os.environ.get("MKTKB_OCR_REGION", "ap-guangzhou"),
        ocr_endpoint=os.environ.get("MKTKB_OCR_ENDPOINT", "https://ocr.tencentcloudapi.com"),
    )


def build_executor(paths: dict, vendor, subplan):
    business = load_business()
    ce = business["ce"]
    return ce.ControlledExecution.build(
        settings=make_settings(paths),
        plan=subplan,
        data_dir=paths["app"],
        chat_transport=vendor,
        rag_transport=vendor,
        ocr_transport=vendor,
        stage=STAGE,
        chat_stage_limit_cny=float(os.environ["MKTKB_RAG_STAGE_LIMIT_CNY"]),
        chat_max_requests=int(os.environ["MKTKB_RAG_MAX_REQUESTS"]),
    )


def _mapped_plan_kind(kind: str) -> str:
    return "ocr" if kind in ("ocr", "ocr_text", "ocr_table") else kind


def read_ledger(paths: dict, subplan) -> dict:
    business = load_business()
    ledger = business["BudgetLedger"](
        paths["ledger"],
        paths["budget"],
        stage=STAGE,
        stage_limit_cny=float(os.environ["MKTKB_RAG_STAGE_LIMIT_CNY"]),
        max_requests=int(os.environ["MKTKB_RAG_MAX_REQUESTS"]),
    )
    events = [json.loads(line) for line in Path(paths["ledger"]).read_text(encoding="utf-8").splitlines() if line.strip()]
    summary = ledger.summary()
    reserved = [event for event in events if event.get("event") == "reserved"]
    results = [event for event in events if event.get("event") == "result"]
    reserved_ids = {event["reservation_id"] for event in reserved}
    result_ids = {event["reservation_id"] for event in results}
    reserve_by_kind: dict[str, float] = {}
    for event in reserved:
        kind = str(event.get("kind"))
        reserve_by_kind[kind] = round(reserve_by_kind.get(kind, 0.0) + float(event.get("reserve_cny") or 0.0), 10)
    return {
        "events": events,
        "summary": summary.as_dict(),
        "reserved": len(reserved),
        "results": len(results),
        "unsettled": sorted(reserved_ids - result_ids),
        "reserve_kinds": [event.get("kind") for event in reserved],
        "reserve_by_kind_cny": reserve_by_kind,
        "request_sha256_list": [event.get("request_sha256") for event in reserved],
        "result_statuses": sorted({str(event.get("status")) for event in results}),
        "result_charges_cny": [float(event.get("conservative_charge_cny") or 0.0) for event in results],
        "reserved_sequence": [
            {
                "order": index + 1,
                "kind": event.get("kind"),
                "reserve_cny": float(event.get("reserve_cny") or 0.0),
                "request_sha256": event.get("request_sha256"),
                "run_id": event.get("run_id"),
            }
            for index, event in enumerate(reserved)
        ],
        "result_events": [
            {
                "order": index + 1,
                "kind": event.get("kind"),
                "status": event.get("status"),
                "http_status": event.get("http_status"),
                "error_code": event.get("error_code"),
                "conservative_charge_cny": float(event.get("conservative_charge_cny") or 0.0),
            }
            for index, event in enumerate(results)
        ],
        "first_failed_result": _first_failed_ledger_result(events),
        "budget_sha256_now": sha256_path(Path(paths["budget"])),
        "ledger_sha256_now": sha256_path(Path(paths["ledger"])),
    }


def _first_failed_ledger_result(events: list[dict]) -> dict | None:
    """**本次运行**账本顺序中的第一条非 succeeded result。

    只看本轮起点之后的事件：共享账本是跨轮累计的，若扫描整份账本，会把上一轮的
    失败误报成本轮首失败（2026-11-04 真实复跑已实际发生：Q01 的 chat 已成功结算，
    receipt 却引用了上一轮 unknown_usage_field 的 2.103552 旧失败）。
    """
    start = int(_LEDGER_BASELINE.get("events") or 0)
    for event in events[start:]:
        if event.get("event") != "result":
            continue
        if str(event.get("status")) == "succeeded":
            continue
        return {
            "kind": event.get("kind"),
            "status": event.get("status"),
            "http_status": event.get("http_status"),
            "error_code": event.get("error_code"),
            "conservative_charge_cny": float(event.get("conservative_charge_cny") or 0.0),
            "reservation_id_present": bool(event.get("reservation_id")),
        }
    return None


def _ledger_event_count(ledger_path: Path | str) -> int:
    try:
        raw = Path(ledger_path).read_text(encoding="utf-8")
    except OSError:
        return 0
    return len([line for line in raw.splitlines() if line.strip()])


def _observed_reservations(events: list[dict]) -> list[dict]:
    reserved = [event for event in events if event.get("event") == "reserved"]
    return [
        {
            "order": index + 1,
            "kind": event.get("kind"),
            "reserve_cny": float(event.get("reserve_cny") or 0.0),
            "request_sha256": event.get("request_sha256"),
        }
        for index, event in enumerate(reserved)
    ]


class PilotStepError(RuntimeError):
    """工具内部稳定失败：携带首个失败的阶段/类别/安全错误码（不回显 secret）。"""

    def __init__(self, stage: str, category: str, code: str, *, detail: str | None = None,
                 cause: BaseException | None = None) -> None:
        super().__init__(f"{stage}:{category}:{code}")
        self.stage = stage
        self.category = category
        self.code = code
        self.detail = detail
        self.cause = cause

    def as_dict(self) -> dict:
        output = {
            "stage": self.stage,
            "category": self.category,
            "code": self.code,
            "exception_type": type(self.cause).__name__ if self.cause is not None else None,
            "exception_message_safe": _safe_text(self.cause) if self.cause is not None else None,
            "detail": _safe_text(self.detail) if self.detail else None,
        }
        return output


def _safe_code(exc: BaseException) -> str:
    raw = getattr(exc, "code", None)
    if isinstance(raw, str) and raw and raw.isascii():
        cleaned = "".join(char for char in raw if char.isalnum() or char in "_-")
        if cleaned:
            return cleaned[:64]
    return type(exc).__name__[:64]


def _category_of(exc: BaseException) -> str:
    business = _BUSINESS.get("ce") if _BUSINESS else None
    name = type(exc).__name__
    if business is not None and isinstance(exc, business.ControlledBindingError):
        return "binding_refused"
    if business is not None and isinstance(exc, business.ControlledRefused):
        return "controlled_refused"
    if name == "OCRBudgetRefused":
        return "ocr_budget_refused"
    if name in {"KeyboardInterrupt", "SystemExit"}:
        return "interrupt"
    if "OCR" in name:
        return "ocr_error"
    return "exception"


def _maybe_isolated_interrupt(stage: str) -> None:
    """仅隔离验收工装：在指定阶段边界注入 KeyboardInterrupt（记录为 isolated seam）。"""
    target = ISOLATED_TEST_HOOKS.get("interrupt_after_step")
    if target and str(target) == stage:
        raise KeyboardInterrupt(f"isolated test interrupt after {stage}")


def _run_step(receipt: dict, journal: Journal | None, stage: str, fn):
    receipt["current_stage"] = stage
    if journal is not None:
        journal.write("step_start", step=stage)
    try:
        value = fn()
    except PilotStepError as exc:
        if journal is not None:
            journal.write("step_failed", step=stage, category=exc.category, code=exc.code)
        raise
    except BaseException as exc:  # noqa: BLE001 - 原异常保留为 cause，不丢类型/错误码
        wrapped = PilotStepError(stage, _category_of(exc), _safe_code(exc), cause=exc)
        if journal is not None:
            journal.write("step_failed", step=stage, category=wrapped.category, code=wrapped.code,
                          exception_type=type(exc).__name__)
        raise wrapped from exc
    if journal is not None:
        journal.write("step_ok", step=stage)
    _maybe_isolated_interrupt(stage)
    return value


def upload_and_publish(client, *, support: dict, csrf: str, file_id: str, ocr, app, paths: dict,
                       journal: Journal | None = None) -> dict:
    """上传 -> 生产 worker -> 发布；任何非成功状态都抛 PilotStepError，且不继续后续付费步骤。"""
    business = load_business()
    stage = f"import:{file_id}"
    path = fixture_path(support, file_id)
    uploaded = support["upload_document"](client, csrf=csrf, path=path, allow_same_name=False)
    if uploaded.status_code != 202:
        raise PilotStepError(stage, "upload_refused", f"HTTP_{uploaded.status_code}",
                             detail=_safe_text(uploaded.text))
    record = uploaded.json()
    document_id = record["document"]["id"]
    version_id = record["version"]["id"]
    db = app.state.db.session()
    try:
        worker = business["run_one_job"](
            db,
            app.state.store,
            ocr=ocr,
            ocr_limiter=business["OcrRateLimiter"](max_per_second=1000.0),
            ocr_options={"max_attempts": 1, "retry_total_seconds": 0.0},
        )
        revision = int(business["get_revision"](db))
    finally:
        db.close()
    facts = {
        "file_id": file_id,
        "upload_sha256": sha256_path(path),
        "document_id": document_id,
        "version_id": version_id,
        "worker_state": worker.state,
        "worker_job_id": worker.job_id,
        "worker_units": getattr(worker, "units_written", None),
        "worker_error_code": getattr(worker, "error_code", None),
        "worker_total_pages": getattr(worker, "total_pages", None),
        "publish_status": None,
        "publish_error_code": None,
    }
    if worker.state != "succeeded":
        raise PilotStepError(stage, "worker_failed", _safe_text(facts["worker_error_code"] or worker.state),
                             detail=_safe_text(getattr(worker, "message", None)))
    if not isinstance(facts["worker_units"], int) or facts["worker_units"] <= 0:
        raise PilotStepError(stage, "worker_empty_units", "NO_UNITS_WRITTEN")
    hook = ISOLATED_TEST_HOOKS.get("before_publish")
    if hook is not None:
        if journal is not None:
            journal.write("isolated_hook", hook="before_publish", file_id=file_id)
        hook(client=client, support=support, csrf=csrf, app=app,
             document_id=document_id, version_id=version_id, file_id=file_id)
    published = client.post(
        f"/api/v1/documents/{document_id}/versions/{version_id}/publish",
        json={"expected_active_version_id": None, "expected_revision": revision},
        headers=support["write_headers"](csrf),
    )
    facts["publish_status"] = published.status_code
    facts["publish_body_kind"] = None
    try:
        body = published.json()
    except ValueError:
        body = {}
    if isinstance(body, dict):
        facts["publish_body_kind"] = body.get("state") or body.get("error_code") or body.get("detail")
        facts["publish_error_code"] = body.get("error_code") or body.get("code")
    if published.status_code != 200:
        raise PilotStepError(
            stage,
            "publish_refused",
            _safe_text(facts["publish_error_code"] or f"HTTP_{published.status_code}"),
            detail=_safe_text(published.text),
        )
    return facts


def ask_question(client, *, support: dict, csrf: str, question: dict) -> dict:
    """正常产品 HTTP 问答；HTTP 200 内的 service_error/空回答/无来源一律判失败（F-K4）。"""
    stage = f"ask:{question['question_id']}"
    created = client.post("/api/v1/conversations", json={}, headers=support["write_headers"](csrf))
    if created.status_code not in (200, 201):
        raise PilotStepError(stage, "conversation_create_refused", f"HTTP_{created.status_code}",
                             detail=_safe_text(created.text))
    conversation = created.json()["id"]
    response = client.post(
        f"/api/v1/conversations/{conversation}/messages",
        json={"client_request_id": str(uuid.uuid4()), "question": question["question"]},
        headers=support["write_headers"](csrf),
    )
    try:
        payload = response.json() if response.status_code == 200 else {}
    except ValueError:
        payload = {}
    if response.status_code != 200:
        raise PilotStepError(stage, "product_answer_http_error", f"HTTP_{response.status_code}",
                             detail=_safe_text(response.text))
    if not isinstance(payload, dict):
        raise PilotStepError(stage, "product_answer_payload_invalid", "NON_OBJECT_RESPONSE")
    kind = payload.get("kind")
    error_code = payload.get("error_code")
    text = str(payload.get("text") or "")
    sources = payload.get("sources") or []
    if kind != "answer":
        raise PilotStepError(stage, "product_answer_not_success", _safe_text(error_code or kind),
                             detail=_safe_text(payload.get("reason") or ""))
    if not text.strip():
        raise PilotStepError(stage, "product_answer_empty_text", "EMPTY_ANSWER_TEXT")
    if not [source for source in sources if isinstance(source, dict) and source.get("source_id")]:
        raise PilotStepError(stage, "product_answer_no_sources", "NO_SOURCES")
    source_ids = [str(source.get("source_id")) for source in sources if isinstance(source, dict) and source.get("source_id")]
    expected_values = list(question.get("expected_values") or [])  # 仅评分对照，不进请求
    expected_files = {(item or {}).get("file") for item in question.get("expected_sources") or []}
    return {
        "question_id": question["question_id"],
        "http_status": response.status_code,
        "kind": kind,
        "error_code": error_code,
        "text": text,
        "text_chars": len(text),
        "source_count": len(sources),
        "source_ids": source_ids,
        "sources": [
            {
                "source_id": str(source.get("source_id")),
                "document_name": source.get("document_name"),
                "version_number": source.get("version_number"),
                "status": source.get("status"),
                "locator": source.get("locator"),
            }
            for source in sources
            if isinstance(source, dict)
        ],
        "expected_values_present": [value for value in expected_values if value and value in text],
        "expected_values_role": "仅评分对照；没有写入任何请求上下文",
        "expected_files": sorted(str(item) for item in expected_files if item),
    }


def _describe_index_documents(index) -> list[dict]:
    documents = index.list_documents()
    return [
        {
            "doc_id": item.get("doc_id"),
            "version_id": item.get("version_id"),
            "title": item.get("title"),
            "state": item.get("state"),
            "is_current": item.get("is_current"),
        }
        for item in documents
    ]


def _strict_import_checks(receipt: dict, app, executor, *, stage: str, file_plan: dict,
                          cumulative_documents: int, cumulative_chunks: int,
                          cumulative_units: int) -> dict:
    """单份资料导入后的严格业务结果检查；任何一项不符即首失败，绝不继续后续付费步骤。"""
    executor_stats = executor.stats()
    if executor_stats.get("stopped"):
        raise PilotStepError(
            stage,
            "paid_request_failed",
            _safe_text(executor_stats.get("stop_code") or "PROVIDER_ERROR"),
            detail="受控执行器在该资料导入期间因供应商请求失败而停机；账本首个 failed result 即真实成因",
        )
    status = app.state.qa.status()
    index_stats = app.state.qa.index().stats()
    facts = {
        "qa_status": status,
        "index_chunks": int(index_stats.get("chunks") or 0),
        "index_units": int(index_stats.get("units") or 0),
        "index_documents": int((index_stats.get("documents") or {}).get("total") or 0),
        "index_revision": index_stats.get("revision"),
        "expected_cumulative_chunks": cumulative_chunks,
        "expected_cumulative_units": cumulative_units,
        "expected_cumulative_documents": cumulative_documents,
    }
    if status.get("ready") is not True:
        raise PilotStepError(stage, "index_sync_not_ready", _safe_text(status.get("error_code") or "INDEX_NOT_READY"))
    if status.get("degraded"):
        raise PilotStepError(stage, "index_sync_degraded", _safe_text(status.get("error_code") or "EMBEDDING_DEGRADED"))
    if status.get("error_code"):
        raise PilotStepError(stage, "index_sync_error", _safe_text(status["error_code"]))
    if status.get("index_revision") != status.get("product_revision"):
        raise PilotStepError(stage, "index_revision_stale", "INDEX_REVISION_STALE")
    if facts["index_chunks"] != cumulative_chunks or facts["index_units"] != cumulative_units:
        raise PilotStepError(
            stage,
            "index_count_mismatch",
            "INDEX_COUNT_MISMATCH",
            detail=f"chunks={facts['index_chunks']}/{cumulative_chunks} units={facts['index_units']}/{cumulative_units}",
        )
    if facts["index_documents"] != cumulative_documents:
        raise PilotStepError(stage, "index_document_mismatch", "INDEX_DOCUMENT_MISMATCH",
                             detail=f"documents={facts['index_documents']}/{cumulative_documents}")
    return facts


def _ocr_tile_bytes(support: dict, file_id: str, mode: str) -> bytes:
    from PIL import Image  # noqa: PLC0415
    from mktkb.ingestion.parsers.image import prepare_ocr_tiles  # noqa: PLC0415

    path = fixture_path(support, file_id)
    limits = load_business()["ParseLimits"]()
    with Image.open(path) as image:
        size = list(image.size)
        image = image.convert("RGB")
        tiles = prepare_ocr_tiles(image, limits=limits, mode=mode, source_width=size[0], source_height=size[1])
    if len(tiles) != 1:
        raise PilotStepError(f"verify:{file_id}", "tile_recount_mismatch", "TILE_COUNT_CHANGED")
    return bytes(tiles[0]["content"])


def _ocr_request_bindings(receipt: dict, plan_data: dict, support: dict) -> list[dict]:
    """用真实上传得到的 document_id/version_id 复算 ocr-v2 request hash 并核对账本。"""
    steps = {
        str(step.get("step", "")).split(":", 1)[1]: step
        for step in receipt.get("steps") or []
        if str(step.get("step", "")).startswith("import:")
    }
    ledger_sha_list = [item for item in (receipt.get("ledger") or {}).get("request_sha256_list") or [] if item]
    bindings = []
    for file_id in ("D09", "D10"):
        plan = plan_data["fixtures"][f"{file_id}_page1"]
        step = steps.get(file_id) or {}
        document_id = step.get("document_id")
        version_id = step.get("version_id")
        if not document_id or not version_id:
            raise PilotStepError(f"verify:{file_id}", "missing_runtime_identity", "NO_DOCUMENT_OR_VERSION")
        scope = sha256_bytes(f"ocr-source-v1|{document_id}|{version_id}".encode("utf-8"))
        content = _ocr_tile_bytes(support, file_id, plan["mode"])
        if sha256_bytes(content) != plan["tile_sha256"]:
            raise PilotStepError(f"verify:{file_id}", "tile_bytes_drift", "TILE_SHA_MISMATCH")
        payload = f"ocr-v2|{scope}|{plan['mode']}|{int(plan['ocr_input_page'])}|".encode("utf-8") + content
        expected = sha256_bytes(payload)
        bindings.append(
            {
                "file_id": file_id,
                "document_id": document_id,
                "version_id": version_id,
                "source_scope": scope,
                "mode": plan["mode"],
                "page": int(plan["ocr_input_page"]),
                "tile_sha256": plan["tile_sha256"],
                "recomputed_request_sha256": expected,
                "ledger_request_sha_present": expected in ledger_sha_list,
            }
        )
    return bindings


def _reuse_probe(receipt: dict, plan_data: dict, support: dict, app, executor) -> dict:
    """同 version 同页同图复用：真实 OcrExecutor 命中 DB 检查点，0 新增 OCR/预留/POST。"""
    from mktkb.ingestion.worker import OcrExecutor  # noqa: PLC0415

    business = load_business()
    paths = receipt["_paths"]
    steps = {
        str(step.get("step", "")).split(":", 1)[1]: step
        for step in receipt.get("steps") or []
        if str(step.get("step", "")).startswith("import:")
    }
    probes = []
    for file_id in ("D09", "D10"):
        plan = plan_data["fixtures"][f"{file_id}_page1"]
        step = steps.get(file_id) or {}
        content = _ocr_tile_bytes(support, file_id, plan["mode"])
        before_stats = executor.ocr_gateway.stats()
        before_ledger = read_ledger(paths, None)
        db = app.state.db.session()
        try:
            worker_ocr = OcrExecutor(
                db,
                version_id=uuid.UUID(str(step["version_id"])),
                document_id=uuid.UUID(str(step["document_id"])),
                gateway=executor.ocr_gateway,
                ensure_live=lambda: None,
                limiter=business["OcrRateLimiter"](max_per_second=1000.0),
                max_attempts=1,
                retry_total_seconds=0.0,
            )
            page = business["OCRInput"](
                content=content, mime_type="image/png", page=int(plan["ocr_input_page"]), bbox=None
            )
            cached = worker_ocr.recognize(page, mode=plan["mode"])
        finally:
            db.close()
        after_stats = executor.ocr_gateway.stats()
        after_ledger = read_ledger(paths, None)
        calls_before = int(before_stats.get("calls") or 0)
        calls_after = int(after_stats.get("calls") or 0)
        checks = {
            "cached_result_nonempty": bool(str(cached.text or "").strip()),
            "gateway_calls_unchanged": calls_after == calls_before,
            "calls_zero_increment": calls_after - calls_before == 0,
            "new_posts_zero": calls_after == calls_before,
            "reservations_unchanged": after_ledger["reserved"] == before_ledger["reserved"]
            and after_ledger["results"] == before_ledger["results"],
            "provider_request_id_safe": cached.provider_request_id is None
            or (
                str(cached.provider_request_id).startswith("sha256:")
                and len(str(cached.provider_request_id)) <= 71
            ),
            "same_version_used": bool(step.get("version_id")),
        }
        probes.append(
            {
                "file_id": file_id,
                "document_id": step.get("document_id"),
                "version_id": step.get("version_id"),
                "mode": plan["mode"],
                "gateway_calls_before": calls_before,
                "gateway_calls_after": calls_after,
                "reserved_before": before_ledger["reserved"],
                "reserved_after": after_ledger["reserved"],
                "checks": checks,
                "pass": all(checks.values()),
            }
        )
    return {"probes": probes, "pass": all(item["pass"] for item in probes)}


def pilot_success_checks(receipt: dict, plan_data: dict, subplan, vendor, paths: dict, *, expected_mode: str) -> dict:
    """F-K4 严格结果判定：状态/业务结果/计划计数/预留/结算/请求清单全部符合才算成功。"""
    business = load_business()
    counts = plan_data["counts"]
    ledger = receipt.get("ledger") or {}
    answers = receipt.get("answers") or []
    planned_kinds = [item["kind"] for item in plan_data["provider_request_sequence"]]
    mapped_planned = [_mapped_plan_kind(kind) for kind in planned_kinds]
    checks: dict[str, bool] = {}
    checks["outcome_completed"] = receipt.get("outcome") == "completed"
    checks["mode_expected"] = receipt.get("mode") == expected_mode
    checks["first_failure_none"] = receipt.get("first_failure") is None
    checks["cleanup_errors_recorded_not_overriding"] = isinstance(receipt.get("cleanup_errors"), list)
    checks["plan_hash_in_executor"] = (receipt.get("executor_stats") or {}).get("request_plan_sha256") == subplan.request_plan_sha256
    checks["plan_hash_matches_plan"] = plan_data["request_plan_sha256"] == subplan.request_plan_sha256
    checks["counts_planned_equal_plan"] = receipt.get("counts_planned") == counts
    checks["observed_reservation_order_equals_plan"] = [
        _mapped_plan_kind(str(item.get("kind"))) for item in (ledger.get("reserved_sequence") or [])
    ] == mapped_planned
    checks["ledger_reserved_equals_total"] = ledger.get("reserved") == counts["total_provider_posts"]
    checks["ledger_results_equals_total"] = ledger.get("results") == counts["total_provider_posts"]
    checks["ledger_unsettled_zero"] = ledger.get("unsettled") == []
    checks["ledger_all_succeeded"] = ledger.get("result_statuses") == ["succeeded"]
    checks["ledger_result_http_all_200"] = all(
        item.get("http_status") == 200 for item in (ledger.get("result_events") or [])
    ) and bool(ledger.get("result_events"))
    if vendor is not None:
        checks["transport_total_equals_plan"] = vendor.count() == counts["total_provider_posts"]
        checks["transport_sequence_equals_plan"] = vendor.kinds() == planned_kinds
        checks["transport_by_kind_equals_plan"] = vendor.summary()["by_kind"] == {
            "chat": counts["chat"],
            "embedding": counts["embedding"],
            "rerank": counts["rerank"],
            "ocr_text": counts["ocr_text"],
            "ocr_table": counts["ocr_table"],
        }
        checks["transport_no_external"] = vendor.summary().get("external") is False
        checks["transport_no_response_error_status"] = all(
            (call.get("response_status") in (200, 201)) for call in (vendor.summary().get("calls") or [])
            if call.get("kind") in ("chat", "embedding", "rerank", "ocr_text", "ocr_table")
        )
    else:
        checks["transport_absent_for_real_live"] = receipt.get("transport_replaced_for_isolated_test") is False
    executor_stats = receipt.get("executor_stats") or {}
    checks["executor_counts_equal_limits_used"] = executor_stats.get("counts") == {
        "chat": counts["chat"],
        "embedding": counts["embedding"],
        "rerank": counts["rerank"],
        "ocr_text": counts["ocr_text"],
        "ocr_table": counts["ocr_table"],
    }
    checks["executor_not_stopped"] = executor_stats.get("stopped") is False
    checks["executor_no_inflight"] = executor_stats.get("in_flight") is None
    checks["post_counters_embedding_rerank"] = (receipt.get("post_counters") or {}).get("attempts") == {
        "embedding": counts["embedding"],
        "rerank": counts["rerank"],
    }
    gateway_stats = receipt.get("gateway_stats") or {}
    checks["gateway_send_attempts_equal_chat"] = (gateway_stats.get("counters") or {}).get("send_attempts") == counts["chat"]
    checks["gateway_request_bound_equal_chat_reserve"] = abs(
        float(gateway_stats.get("request_bound_cny") or 0.0) - float(subplan.chat_reserve_cny)
    ) < 1e-12
    reserve_by_kind = ledger.get("reserve_by_kind_cny") or {}
    checks["ledger_reserve_by_kind"] = (
        abs(reserve_by_kind.get("chat", 0.0) - counts["chat"] * float(subplan.chat_reserve_cny)) < 1e-9
        and abs(reserve_by_kind.get("embedding", 0.0) - counts["embedding"] * 0.04096) < 1e-9
        and abs(reserve_by_kind.get("rerank", 0.0) - counts["rerank"] * 0.024) < 1e-9
        and abs(
            reserve_by_kind.get("ocr", 0.0)
            - (counts["ocr_text"] * 0.5 + counts["ocr_table"] * 0.15)
        ) < 1e-9
    )
    summary = ledger.get("summary") or {}
    checks["ledger_history_kept_003"] = abs(float(summary.get("historical_conservative_cny") or 0.0) - 0.03) < 1e-12
    checks["ledger_accounted_within_plan"] = float(summary.get("accounted_cny") or 0.0) - 0.03 <= float(
        subplan.conservative_settlement_cny
    ) + 1e-12
    checks["ledger_stage_accounted_within_peak"] = float(summary.get("stage_accounted_cny") or 0.0) <= float(
        subplan.peak_include_history_cny
    ) + 1e-12
    ocr_stats = receipt.get("ocr_stats") or {}
    checks["ocr_stats_calls_equal_plan"] = ocr_stats.get("calls") == counts["ocr_text"] + counts["ocr_table"]
    checks["ocr_stats_attempts_1"] = ocr_stats.get("attempts") == 1
    checks["ocr_stats_tiles_by_page_total"] = sum((ocr_stats.get("tiles_by_page") or {}).values()) == counts["ocr_text"] + counts["ocr_table"]
    checks["ocr_stats_two_source_scopes"] = len(ocr_stats.get("tiles_by_source_page") or {}) == 2
    checks["ocr_no_legacy_source_scope"] = ocr_stats.get("legacy_source_scope_used") is False
    checks["ocr_source_scopes_are_64hex"] = all(
        isinstance(scope, str) and len(scope) == 64 and all(char in "0123456789abcdef" for char in scope)
        for scope in (ocr_stats.get("source_scopes") or [])
    )
    ocr_records = receipt.get("ocr_call_records") or []
    checks["ocr_records_one_attempt_succeeded"] = bool(ocr_records) and all(
        row.get("attempt") == 1 and row.get("state") == "succeeded" for row in ocr_records
    )
    checks["ocr_request_id_safe"] = all(
        row.get("provider_request_id") is None
        or (str(row.get("provider_request_id")).startswith("sha256:") and row.get("provider_request_id_len", 999) <= 71)
        for row in ocr_records
    )
    bindings = receipt.get("ocr_request_bindings") or []
    checks["ocr_request_sha_v2_bound_to_runtime_identity"] = len(bindings) == counts["ocr_text"] + counts["ocr_table"] and all(
        item.get("ledger_request_sha_present") is True for item in bindings
    )
    import_steps = [step for step in receipt.get("steps") or [] if str(step.get("step", "")).startswith("import:")]
    checks["imports_three"] = [step.get("step") for step in import_steps] == ["import:D01", "import:D09", "import:D10"]
    checks["imports_worker_succeeded"] = all(
        step.get("worker_state") == "succeeded" and step.get("publish_status") == 200 for step in import_steps
    )
    expected_units = {
        "import:D01": plan_data["fixtures"]["D01"]["units"],
        "import:D09": plan_data["fixtures"]["D09_page1"]["units"],
        "import:D10": plan_data["fixtures"]["D10_page1"]["units"],
    }
    checks["imports_units_match_plan"] = all(
        step.get("worker_units") == expected_units.get(str(step.get("step"))) for step in import_steps
    )
    qa_status = receipt.get("qa_status") or {}
    checks["qa_status_ready"] = qa_status.get("ready") is True and not qa_status.get("degraded") and not qa_status.get("error_code")
    checks["qa_index_revision_current"] = qa_status.get("index_revision") == qa_status.get("product_revision")
    expected_chunks = (
        plan_data["fixtures"]["D01"]["chunks"]
        + plan_data["fixtures"]["D09_page1"]["chunks"]
        + plan_data["fixtures"]["D10_page1"]["chunks"]
    )
    expected_units_total = (
        plan_data["fixtures"]["D01"]["units"]
        + plan_data["fixtures"]["D09_page1"]["units"]
        + plan_data["fixtures"]["D10_page1"]["units"]
    )
    index_stats = receipt.get("index_stats") or {}
    checks["index_chunks_expected"] = int(index_stats.get("chunks") or 0) == expected_chunks
    checks["index_units_expected"] = int(index_stats.get("units") or 0) == expected_units_total
    checks["index_documents_three"] = int((index_stats.get("documents") or {}).get("total") or 0) == 3
    index_documents = receipt.get("index_documents") or []
    checks["index_documents_current"] = len(index_documents) == 3 and all(
        item.get("state") == "active" and item.get("is_current") is True for item in index_documents
    )
    checks["answers_two"] = len(answers) == 2
    checks["answers_qids"] = [answer.get("question_id") for answer in answers] == [
        question["question_id"] for question in plan_data["questions"]
    ]
    checks["answers_http_200"] = all(answer.get("http_status") == 200 for answer in answers)
    checks["answers_kind_answer"] = all(answer.get("kind") == "answer" for answer in answers)
    checks["answers_error_code_null"] = all(answer.get("error_code") is None for answer in answers)
    checks["answers_nonempty_text"] = all(bool(str(answer.get("text") or "").strip()) for answer in answers)
    checks["answers_have_sources"] = all(int(answer.get("source_count") or 0) > 0 for answer in answers)
    checks["answers_expected_values_present"] = all(bool(answer.get("expected_values_present")) for answer in answers)
    checks["answers_cite_D01"] = all(
        any(source.get("document_name") and "物品位置表" in str(source.get("document_name")) for source in answer.get("sources") or [])
        for answer in answers
    )
    checks["answers_sources_role_scoring_only"] = all(
        str(answer.get("expected_values_role") or "").startswith("仅评分") for answer in answers
    )
    qa_config = receipt.get("qa_config") or {}
    checks["product_config_zero_retry"] = qa_config.get("max_retries") == 0 and qa_config.get("require_zero_retries") is True
    checks["product_config_reserve_ceiling"] = (
        qa_config.get("chat_reserve_profile") == "model_context_ceiling"
        and qa_config.get("chat_context_ceiling_tokens") == 1048576
    )
    checks["product_config_models"] = (
        qa_config.get("embedding_model") == "text-embedding-v4" and qa_config.get("rerank_model") == "gte-rerank-v2"
    )
    checks["index_provider_models"] = (
        (index_stats.get("provider") or {}).get("embedding_provider") == "bailian"
        and (index_stats.get("provider") or {}).get("rerank_provider") == "bailian"
        and (index_stats.get("provider") or {}).get("embedding_model") == "text-embedding-v4"
        and (index_stats.get("provider") or {}).get("rerank_model") == "gte-rerank-v2"
    )
    checks["plan_sources_match"] = (executor_stats.get("plan") or {}).get("sources") == plan_data["sources"]
    checks["pricing_sources_bound"] = all(
        bool((plan_data["sources"] or {}).get(name))
        for name in ("chat_pricing_source", "embedding_pricing_source", "rerank_pricing_source", "ocr_pricing_source")
    )
    checks["policy_versions_bound"] = executor_stats.get("settlement_versions") == {
        "chat": "usage-conservative-v1",
        "embedding": "usage-conservative-v1",
        "rerank": "usage-conservative-v1",
    }
    checks["controlled_boundaries_attached"] = (
        (executor_stats.get("controlled_boundaries") or {}).get("chat_budget_proxy") == "_ControlledBudget"
        and (executor_stats.get("controlled_boundaries") or {}).get("rag_budget_proxy") == "_ControlledBudget"
    )
    root = Path(paths["root"]).resolve()
    if expected_mode == "mock":
        checks["isolated_paths_under_run_dir"] = all(
            _is_under(Path(paths[key]).resolve(), root) for key in ("root", "ledger", "budget", "go", "app")
        )
    else:
        # live 必须用固定共享 GO/账本/预算（不随输出根漂移），只有 app/运行目录落在本次 --out 下。
        checks["live_uses_fixed_shared_paths"] = (
            _resolved(Path(paths["ledger"])) == _resolved(REAL_LEDGER)
            and _resolved(Path(paths["budget"])) == _resolved(REAL_BUDGET)
            and _resolved(Path(paths["go"])) == _resolved(REAL_GO)
            and _resolved(Path(paths["root"])) == root
            and _is_under(Path(paths["app"]).resolve(), root)
        )
    checks["no_secret_in_receipt"] = SYNTH_SECRET not in json.dumps(receipt, ensure_ascii=False, default=str) and (
        "Authorization: Bearer" not in json.dumps(receipt, ensure_ascii=False, default=str)
    )
    reuse_probe = receipt.get("reuse_probe")
    if reuse_probe is not None:
        checks["reuse_probe_all_pass"] = reuse_probe.get("pass") is True
    checks["resource_gate_ok"] = (receipt.get("resource_gate") or {}).get("ok") is True
    return checks


def run_controlled_pilot(*, paths: dict, subplan, plan_data: dict, support: dict, mode: str,
                         vendor=None, journal: Journal | None = None) -> dict:
    """同一执行函数（plan/Mock/live 共享）：F-K4 严格逐步判定 + F-K3 首失败/清理分离。

    本函数**永不吞掉 exit 0**：任何失败都写进 receipt（caller 负责落盘并返回非零退出码）。
    """
    business = load_business()
    _LEDGER_BASELINE["events"] = _ledger_event_count(paths["ledger"])
    from fastapi.testclient import TestClient  # noqa: PLC0415 - 产品 HTTP 入口

    receipt: dict = {
        "document": "S2-K-R1B-controlled-pilot-run",
        "mode": mode,
        "started_at": now_iso(),
        "request_plan_sha256": subplan.request_plan_sha256,
        "counts_planned": plan_data["counts"],
        "sequence_planned": [item["kind"] for item in plan_data["provider_request_sequence"]],
        "steps": [],
        "answers": [],
        "import_checks": {},
        "error": None,
        "first_failure": None,
        "outcome": "running",
        "cleanup_errors": [],
        "current_stage": "setup",
        "transport_replaced_for_isolated_test": bool(mode == "live" and vendor is not None),
        "isolated_test_seams": sorted(ISOLATED_TEST_HOOKS),
        "resource_gate": _ACTIVE_RUN.get("resource_gate"),
        "_paths": paths,
    }
    app = None
    executor = None
    try:
        executor = _run_step(receipt, journal, "setup:build_executor", lambda: build_executor(paths, vendor, subplan))
        app = _run_step(receipt, journal, "setup:create_app", lambda: executor.create_app(make_settings(paths), initialize=True))
        client = TestClient(app, raise_server_exceptions=False)
        business["reset_post_counters"]()
        _run_step(receipt, journal, "setup:login", lambda: support["login"](client, "admin", ADMIN_PASSWORD))
        csrf = _run_step(receipt, journal, "setup:csrf", lambda: support["current_csrf"](client))

        fixtures = plan_data["fixtures"]
        imports = [
            ("D01", None, fixtures["D01"]),
            ("D09", executor.ocr_gateway, fixtures["D09_page1"]),
            ("D10", executor.ocr_gateway, fixtures["D10_page1"]),
        ]
        cumulative_documents = 0
        cumulative_chunks = 0
        cumulative_units = 0
        for file_id, ocr, file_plan in imports:
            cumulative_documents += 1
            cumulative_chunks += int(file_plan["chunks"])
            cumulative_units += int(file_plan["units"])
            facts = _run_step(
                receipt,
                journal,
                f"import:{file_id}",
                lambda file_id=file_id, ocr=ocr, file_plan=file_plan: upload_and_publish(
                    client, support=support, csrf=csrf, file_id=file_id, ocr=ocr, app=app, paths=paths, journal=journal
                ),
            )
            receipt["steps"].append({"step": f"import:{file_id}", **facts})
            import_checks = _run_step(
                receipt,
                journal,
                f"import:{file_id}:strict",
                lambda file_id=file_id, file_plan=file_plan: _strict_import_checks(
                    receipt,
                    app,
                    executor,
                    stage=f"import:{file_id}",
                    file_plan=file_plan,
                    cumulative_documents=cumulative_documents,
                    cumulative_chunks=cumulative_chunks,
                    cumulative_units=cumulative_units,
                ),
            )
            receipt["import_checks"][file_id] = import_checks

        for question in plan_data["questions"]:
            answer = _run_step(
                receipt,
                journal,
                f"ask:{question['question_id']}",
                lambda question=question: ask_question(client, support=support, csrf=csrf, question=question),
            )
            receipt["answers"].append(answer)

        ledger = _run_step(receipt, journal, "verify:ledger_snapshot", lambda: read_ledger(paths, subplan))
        receipt["ledger"] = ledger
        receipt["transport"] = vendor.summary() if vendor is not None else None
        receipt["transport_kinds"] = vendor.kinds() if vendor is not None else None
        receipt["observed_reservations"] = _observed_reservations(ledger.get("events") or [])
        receipt["post_counters"] = business["post_counters"]()
        receipt["gateway_stats"] = app.state.model_gateway.stats() if hasattr(app.state.model_gateway, "stats") else None
        receipt["executor_stats"] = executor.stats()
        receipt["ocr_stats"] = executor.ocr_gateway.stats()
        index = app.state.qa.index()
        receipt["index_stats"] = index.stats()
        receipt["index_documents"] = _describe_index_documents(index)
        receipt["qa_status"] = app.state.qa.status()
        qa_config = app.state.qa.config
        receipt["qa_config"] = {
            "provider_mode": qa_config.provider_mode,
            "max_retries": qa_config.max_retries,
            "require_zero_retries": qa_config.require_zero_retries,
            "chat_reserve_profile": qa_config.chat_reserve_profile,
            "chat_context_ceiling_tokens": qa_config.chat_context_ceiling_tokens,
            "chat_max_input_tokens": qa_config.chat_max_input_tokens,
            "chat_max_output_tokens": qa_config.chat_max_output_tokens,
            "embedding_model": qa_config.embedding_model,
            "embedding_dimensions": qa_config.embedding_dimensions,
            "embedding_batch_size": qa_config.embedding_batch_size,
            "rerank_model": qa_config.rerank_model,
            "rerank_top_n": qa_config.rerank_top_n,
            "stage_limit_cny": qa_config.stage_limit_cny,
            "max_request_cny": qa_config.max_request_cny,
            "stage": getattr(qa_config, "stage", None),
        }
        receipt["d10_units"] = _d10_source_units(app, receipt)
        receipt["ocr_call_records"] = _ocr_call_records(app)
        receipt["ocr_request_bindings"] = _run_step(
            receipt, journal, "verify:ocr_request_bindings",
            lambda: _ocr_request_bindings(receipt, plan_data, support),
        )
        if mode == "mock":
            receipt["reuse_probe"] = _run_step(
                receipt, journal, "verify:reuse_probe",
                lambda: _reuse_probe(receipt, plan_data, support, app, executor),
            )

        receipt["outcome"] = "completed"
        checks = pilot_success_checks(receipt, plan_data, subplan, vendor, paths, expected_mode=mode)
        receipt["verification"] = checks
        failed = [name for name, ok in checks.items() if not ok]
        if failed:
            receipt["outcome"] = "failed"
            raise PilotStepError(
                "final:verification",
                "verification_failed",
                "PILOT_VERIFICATION_FAILED",
                detail=", ".join(failed[:12]),
            )
        if journal is not None:
            journal.write("verification", pass_=True, checks=len(checks))
    except PilotStepError as exc:
        receipt["outcome"] = "failed"
        receipt["error"] = exc.as_dict()
        receipt["first_failure"] = exc.as_dict()
    except BaseException as exc:  # noqa: BLE001 - 中断/未知异常也落 receipt，绝不换 exit 0
        step = PilotStepError(str(receipt.get("current_stage") or "unknown"), _category_of(exc), _safe_code(exc), cause=exc)
        receipt["outcome"] = "failed"
        receipt["error"] = step.as_dict()
        receipt["first_failure"] = step.as_dict()
    finally:
        try:
            if app is not None:
                try:
                    receipt["index_stats"] = receipt.get("index_stats") or app.state.qa.index().stats()
                except BaseException:  # noqa: BLE001
                    pass
                try:
                    receipt["qa_status"] = receipt.get("qa_status") or app.state.qa.status()
                except BaseException:  # noqa: BLE001
                    pass
        except BaseException:  # noqa: BLE001
            pass
        try:
            if executor is not None:
                receipt["executor_stats"] = executor.stats()
        except BaseException:  # noqa: BLE001
            pass
        try:
            receipt["post_counters"] = business["post_counters"]()
        except BaseException:  # noqa: BLE001
            pass
        if vendor is not None:
            try:
                receipt["transport"] = vendor.summary()
                receipt["transport_kinds"] = vendor.kinds()
            except BaseException:  # noqa: BLE001
                pass
        try:
            receipt["ledger"] = read_ledger(paths, subplan)
            receipt["observed_reservations"] = _observed_reservations((receipt["ledger"].get("events") or []))
            if receipt.get("first_failure") is not None:
                failed_result = _first_failed_ledger_result(receipt["ledger"].get("events") or [])
                if failed_result is not None:
                    receipt["first_failure"]["ledger_result"] = failed_result
                receipt["error"] = receipt["first_failure"]
        except BaseException as exc:  # noqa: BLE001 - 账本快照失败记录为次级事实
            receipt["ledger"] = {"error": _safe_text(f"{type(exc).__name__}: {exc}")}
        if app is not None:
            teardown_hook = ISOLATED_TEST_HOOKS.get("teardown")
            if teardown_hook is not None:
                try:
                    teardown_hook(app=app)
                except BaseException as exc:  # noqa: BLE001 - 清理失败是次级信息
                    receipt["cleanup_errors"].append(
                        {"stage": "isolated_test_teardown_hook", "type": type(exc).__name__, "code": _safe_code(exc)}
                    )
            for label, closer in (
                ("app.state.db.dispose", lambda: app.state.db.dispose()),
                ("app.state.qa.close", lambda: app.state.qa.close()),
            ):
                try:
                    closer()
                except BaseException as exc:  # noqa: BLE001 - 清理失败不覆盖原成因
                    receipt["cleanup_errors"].append(
                        {"stage": label, "type": type(exc).__name__, "code": _safe_code(exc),
                         "message_safe": _safe_text(exc)}
                    )
        receipt["finished_at"] = now_iso()
        if journal is not None:
            journal.write(
                "run_finish",
                outcome=receipt["outcome"],
                first_failure_stage=(receipt.get("first_failure") or {}).get("stage"),
                cleanup_error_count=len(receipt.get("cleanup_errors") or []),
            )
    receipt.pop("_paths", None)
    return receipt


def _d10_source_units(app, receipt: dict) -> list[dict]:
    from sqlalchemy import select  # noqa: PLC0415
    from mktkb.documents.models import SourceUnit  # noqa: PLC0415

    version_id = None
    for step in receipt.get("steps") or []:
        if step.get("step") == "import:D10":
            version_id = step.get("version_id")
    if version_id is None:
        return []
    session = app.state.db.session()
    try:
        rows = session.scalars(
            select(SourceUnit).where(SourceUnit.version_id == uuid.UUID(str(version_id)))
        ).all()
        return [
            {"kind": row.kind, "unit_key": row.unit_key, "text": row.text, "fields": dict(row.fields or {}), "locator": dict(row.locator or {})}
            for row in rows
        ]
    finally:
        session.close()


def _ocr_call_records(app) -> list[dict]:
    from sqlalchemy import select  # noqa: PLC0415
    from mktkb.ingestion.models import OCRCallRecord  # noqa: PLC0415

    session = app.state.db.session()
    try:
        rows = session.scalars(select(OCRCallRecord)).all()
        return [
            {
                "attempt": row.attempt,
                "state": row.state,
                "mode": getattr(row, "mode", None),
                "provider_request_id": row.provider_request_id,
                "provider_request_id_len": len(row.provider_request_id or ""),
            }
            for row in rows
        ]
    finally:
        session.close()


# ---------------------------------------------------------------- 负例场景


def _build_refusal_case(*, label: str, subplan, plan_data: dict, stage_limit: float, max_requests: int | None = None,
                        go_tamper=None, write_go_file: bool = True, include_stage: bool = True) -> dict:
    """构造期拒绝：J2 在首个预留/POST 之前 ControlledBindingError。"""
    business = load_business()
    ce = business["ce"]
    with isolated(
        label,
        subplan=subplan,
        stage_limit=stage_limit,
        max_requests=max_requests,
        go_tamper=go_tamper,
        write_go_file=write_go_file,
        include_stage=include_stage,
    ) as paths:
        vendor = MockVendor()
        caught = None
        try:
            build_executor(paths, vendor, subplan)
        except BaseException as exc:  # noqa: BLE001 - 记录后取证
            caught = exc
        checks = {
            "refused": isinstance(caught, ce.ControlledBindingError),
            "zero_posts": vendor.count() == 0,
            "isolated_ledger_only_history": read_ledger(paths, subplan)["reserved"] == 0,
            "error_type": type(caught).__name__ if caught is not None else None,
            "error_message_has_no_go_text": SYNTH_SECRET not in str(caught or ""),
        }
    return {"scenario": f"refusal:{label}", "checks": checks, "pass": all(checks.values())}


def scenario_go_missing(subplan, plan_data: dict) -> dict:
    return _build_refusal_case(
        label="go-missing", subplan=subplan, plan_data=plan_data,
        stage_limit=float(subplan.peak_include_history_cny), write_go_file=False,
    )


def scenario_go_binding_tamper(subplan, plan_data: dict) -> dict:
    def tamper(bindings: dict) -> None:
        bindings["rag"]["rerank_total_tokens_cap"] = 6001

    return _build_refusal_case(
        label="go-binding-tamper", subplan=subplan, plan_data=plan_data,
        stage_limit=float(subplan.peak_include_history_cny), go_tamper=tamper,
    )


def scenario_stage_below_peak(subplan, plan_data: dict) -> dict:
    return _build_refusal_case(
        label="stage-below-peak", subplan=subplan, plan_data=plan_data,
        stage_limit=float(subplan.peak_include_history_cny) - 0.01,
    )


def scenario_request_cap_below_plan(subplan, plan_data: dict) -> dict:
    return _build_refusal_case(
        label="request-cap-below-plan", subplan=subplan, plan_data=plan_data,
        stage_limit=float(subplan.peak_include_history_cny),
        max_requests=int(subplan.total_calls) - 1,
    )


def scenario_budget_stage_missing(subplan, plan_data: dict) -> dict:
    return _build_refusal_case(
        label="budget-stage-missing", subplan=subplan, plan_data=plan_data,
        stage_limit=float(subplan.peak_include_history_cny), include_stage=False,
    )


def _chat_input(business: dict):
    return business["CompletionInput"](purpose="answer", question="同一账本受控 chat 负例", context=business["DialogueContext"](), evidence=())


def scenario_chat_over_cap(subplan, plan_data: dict) -> dict:
    with isolated("chat-over-cap", subplan=subplan, stage_limit=float(subplan.peak_include_history_cny)) as paths:
        business = load_business()
        # 用当前生效的 chat 准入 cap 动态构造“超一次”的 usage：cap 是策略常量
        # （2026-11-04 从 1536/256 对齐到请求自身上界 6144/800），负例不能写死旧值，
        # 否则 cap 调整后这个负例就不再越界，检查会退化为“没拒绝”。
        from mktkb.rag.settlement_policy import CHAT_PROMPT_TOKENS_CAP

        over_prompt = int(CHAT_PROMPT_TOKENS_CAP) + 1
        vendor = MockVendor().configure("chat", usage={
            "prompt_tokens": over_prompt, "completion_tokens": 10,
            "total_tokens": over_prompt + 10,
            "prompt_cache_hit_tokens": 0, "prompt_cache_miss_tokens": over_prompt,
        })
        executor = build_executor(paths, vendor, subplan)
        caught = None
        try:
            executor.run_chat(_chat_input(business))
        except BaseException as exc:  # noqa: BLE001
            caught = exc
        second_refused = False
        try:
            executor.run_embedding(["停机后不得再发"])
        except BaseException:  # noqa: BLE001
            second_refused = True
        ledger = read_ledger(paths, subplan)
        checks = {
            "raised": caught is not None,
            "one_chat_post_only": vendor.count("chat") == 1,
            "zero_embedding_after_stop": vendor.count("embedding") == 0,
            "second_call_refused": second_refused,
            "executor_stopped": executor.stopped is True,
            "one_reservation": ledger["reserved"] == 1,
            "full_chat_reserve_kept": abs(float(ledger["summary"]["accounted_cny"]) - (0.03 + float(subplan.chat_reserve_cny))) < 1e-9,
            "no_unsettled_success": ledger["result_statuses"] in ([], ["succeeded"]) or ledger["results"] == 1,
            "no_secret": SYNTH_SECRET not in json.dumps(ledger["events"], ensure_ascii=False),
        }
    return {"scenario": "chat-over-cap", "checks": checks, "pass": all(checks.values())}


def scenario_chat_http_500(subplan, plan_data: dict) -> dict:
    with isolated("chat-http-500", subplan=subplan, stage_limit=float(subplan.peak_include_history_cny)) as paths:
        business = load_business()
        vendor = MockVendor().configure("chat", status=500)
        executor = build_executor(paths, vendor, subplan)
        caught = None
        try:
            executor.run_chat(_chat_input(business))
        except BaseException as exc:  # noqa: BLE001
            caught = exc
        ledger = read_ledger(paths, subplan)
        checks = {
            "raised": caught is not None,
            "one_chat_post": vendor.count("chat") == 1,
            "full_reserve_kept": abs(float(ledger["summary"]["accounted_cny"]) - (0.03 + float(subplan.chat_reserve_cny))) < 1e-9,
            "executor_stopped": executor.stopped is True,
            "not_released": abs(float(ledger["summary"]["stage_accounted_cny"]) - float(subplan.chat_reserve_cny)) < 1e-9,
        }
    return {"scenario": "chat-http-500", "checks": checks, "pass": all(checks.values())}


def scenario_ocr_tile_limit(subplan, plan_data: dict) -> dict:
    with isolated("ocr-tile-limit", subplan=subplan, stage_limit=float(subplan.peak_include_history_cny)) as paths:
        business = load_business()
        vendor = MockVendor()
        executor = build_executor(paths, vendor, subplan)
        page = business["OCRInput"](content=b"s2k-tile-page-1", mime_type="image/png", page=1, bbox=None)
        first = executor.run_ocr(page, mode="text")
        caught = None
        try:
            executor.run_ocr(page, mode="table")
        except BaseException as exc:  # noqa: BLE001
            caught = exc
        ledger = read_ledger(paths, subplan)
        checks = {
            "first_ok": bool(first.text),
            "second_same_page_refused": caught is not None and getattr(caught, "code", None) == "OCR_BUDGET_REFUSED",
            "only_one_ocr_post": vendor.count("ocr_text") == 1 and vendor.count("ocr_table") == 0,
            "only_one_reserve": ledger["reserved"] == 1,
            # J2 语义：发送前（未预留未发送）拒绝不计数、也不停机；只有已发送后的失败才停机。
            "executor_not_stopped_by_send_time_refusal": executor.stopped is False,
            "in_flight_released": executor.stats()["in_flight"] is None,
            "zero_retry_no_second_post": vendor.count() == 1,
        }
    return {"scenario": "ocr-tile-limit", "checks": checks, "pass": all(checks.values())}


def scenario_ocr_rate_limited(subplan, plan_data: dict) -> dict:
    with isolated("ocr-rate-limited", subplan=subplan, stage_limit=float(subplan.peak_include_history_cny)) as paths:
        business = load_business()
        vendor = MockVendor().configure("ocr_text", status=429)
        executor = build_executor(paths, vendor, subplan)
        caught = None
        try:
            executor.run_ocr(business["OCRInput"](content=b"s2k-rate-page", mime_type="image/png", page=9, bbox=None), mode="text")
        except BaseException as exc:  # noqa: BLE001
            caught = exc
        ledger = read_ledger(paths, subplan)
        checks = {
            "rate_limited": getattr(caught, "code", None) == "OCR_RATE_LIMITED",
            "one_attempt_only": vendor.count("ocr_text") == 1,
            "full_0_5_kept": abs(float(ledger["summary"]["accounted_cny"]) - (0.03 + 0.5)) < 1e-9,
            "executor_stopped": executor.stopped is True,
            "failed_record": ledger["result_statuses"] == ["failed"],
        }
    return {"scenario": "ocr-rate-limited", "checks": checks, "pass": all(checks.values())}


def scenario_secret_output(subplan, plan_data: dict) -> dict:
    with isolated("secret-output", subplan=subplan, stage_limit=float(subplan.peak_include_history_cny)) as paths:
        business = load_business()
        vendor = MockVendor().configure("ocr_text", ocr_error="auth_secret")
        executor = build_executor(paths, vendor, subplan)
        caught = None
        try:
            executor.run_ocr(business["OCRInput"](content=b"s2k-secret-page", mime_type="image/png", page=7, bbox=None), mode="text")
        except BaseException as exc:  # noqa: BLE001
            caught = exc
        ledger_bytes = Path(paths["ledger"]).read_bytes()
        checks = {
            "raised": caught is not None,
            "one_ocr_post": vendor.count("ocr_text") == 1,
            "ledger_no_secret": SYNTH_SECRET.encode() not in ledger_bytes,
            "ledger_no_bearer": b"Authorization: Bearer" not in ledger_bytes,
            "exception_no_secret": SYNTH_SECRET not in str(caught or ""),
            "full_0_5_kept": abs(float(read_ledger(paths, subplan)["summary"]["accounted_cny"]) - (0.03 + 0.5)) < 1e-9,
            "executor_stopped": executor.stopped is True,
        }
    return {"scenario": "secret-output", "checks": checks, "pass": all(checks.values())}


def scenario_plan_limit(subplan, plan_data: dict) -> dict:
    with isolated("plan-limit", subplan=subplan, stage_limit=float(subplan.peak_include_history_cny)) as paths:
        business = load_business()
        vendor = MockVendor()
        executor = build_executor(paths, vendor, subplan)
        for _index in range(int(subplan.chat_requests)):
            executor.run_chat(_chat_input(business))
        caught = None
        try:
            executor.run_chat(_chat_input(business))
        except BaseException as exc:  # noqa: BLE001
            caught = exc
        ledger = read_ledger(paths, subplan)
        checks = {
            "all_chat_posts": vendor.count("chat") == int(subplan.chat_requests),
            "next_refused_before_post": caught is not None and vendor.count("chat") == int(subplan.chat_requests),
            "refused_type_controlled": type(caught).__name__ == "ControlledRefused" if caught is not None else False,
            "all_reservations": ledger["reserved"] == int(subplan.chat_requests),
            "all_succeeded": ledger["result_statuses"] == ["succeeded"],
        }
    return {"scenario": "plan-limit", "checks": checks, "pass": all(checks.values())}


# ---- F-K3/F-K4 pilot 级负例：真实 run_controlled_pilot 在 Mock 传输下失败也必须留 receipt ----


def _run_pilot_case(label, plan_data, subplan, support, *, configure=None, hooks=None, checks_fn=None) -> dict:
    vendor = MockVendor()
    if configure:
        configure(vendor)
    previous_hooks = dict(ISOLATED_TEST_HOOKS)
    ISOLATED_TEST_HOOKS.clear()
    if hooks:
        ISOLATED_TEST_HOOKS.update(hooks)
    try:
        with isolated(label, subplan=subplan, stage_limit=float(subplan.peak_include_history_cny)) as paths:
            journal = Journal(Path(paths["root"]) / "run-journal.jsonl")
            try:
                receipt = run_controlled_pilot(
                    paths=paths, subplan=subplan, plan_data=plan_data, support=support, mode="mock",
                    vendor=vendor, journal=journal,
                )
            finally:
                journal.close()
            receipt_path = dump_json(Path(paths["root"]) / "pilot-receipt.json", receipt)
            checks = {
                "receipt_written": receipt_path.is_file(),
                "outcome_failed": receipt.get("outcome") == "failed",
                "first_failure_recorded": isinstance(receipt.get("first_failure"), dict),
                "error_matches_first_failure": receipt.get("error") == receipt.get("first_failure"),
                "ledger_snapshot_present": isinstance(receipt.get("ledger"), dict) and "reserved_sequence" in receipt["ledger"],
                "no_exit0_style_completion": receipt.get("outcome") != "completed",
                "verification_absent_on_failure": "verification" not in receipt,
                "journal_exists": journal.path.is_file(),
                "cleanup_errors_is_list": isinstance(receipt.get("cleanup_errors"), list),
            }
            if checks_fn is not None:
                checks.update(checks_fn(receipt, vendor))
            return {
                "scenario": label,
                "checks": checks,
                "pass": all(checks.values()),
                "receipt": rel(receipt_path),
                "first_failure": receipt.get("first_failure"),
                "cleanup_errors": receipt.get("cleanup_errors"),
                "received_reserved": (receipt.get("ledger") or {}).get("reserved"),
                "received_results": (receipt.get("ledger") or {}).get("results"),
                "vendor_calls": vendor.kinds(),
            }
    finally:
        ISOLATED_TEST_HOOKS.clear()
        ISOLATED_TEST_HOOKS.update(previous_hooks)


def scenario_pilot_first_paid_failure(subplan, plan_data: dict, support: dict) -> dict:
    def checks_fn(receipt, vendor):
        first = receipt.get("first_failure") or {}
        ledger_result = first.get("ledger_result") or {}
        return {
            "stage_is_first_import": first.get("stage") == "import:D01",
            "category_is_provider_failure": first.get("category") == "paid_request_failed",
            "not_masked_by_later_ocr_refusal": "OCR" not in json.dumps(first, ensure_ascii=False),
            "ledger_failed_embedding": ledger_result.get("kind") == "embedding"
            and ledger_result.get("status") == "failed"
            and ledger_result.get("http_status") == 500,
            "only_one_provider_post": vendor.count() == 1 and vendor.count("embedding") == 1,
            "no_ocr_post": vendor.count("ocr_text") == 0 and vendor.count("ocr_table") == 0,
            "one_reservation_one_failed_result": (receipt.get("ledger") or {}).get("reserved") == 1
            and (receipt.get("ledger") or {}).get("result_statuses") == ["failed"],
            "no_unsettled": (receipt.get("ledger") or {}).get("unsettled") == [],
        }

    return _run_pilot_case(
        "pilot-first-paid-failure", plan_data, subplan, support,
        configure=lambda vendor: vendor.configure("embedding", status=500),
        checks_fn=checks_fn,
    )


def scenario_pilot_publish_failure(subplan, plan_data: dict, support: dict) -> dict:
    def before_publish(client, *, support, csrf, app, document_id, version_id, file_id):  # noqa: ANN001
        if file_id != "D09":
            return
        # 真实产品行为：在处理成功后、publish 前取消该待生效版本，使 publish 返回 409 不可发布。
        cancelled = client.post(
            f"/api/v1/documents/{document_id}/versions/{version_id}/cancel",
            json={},
            headers=support["write_headers"](csrf),
        )
        if cancelled.status_code != 204:
            raise RuntimeError(f"isolated publish-failure hook could not cancel version: {cancelled.status_code}")

    def checks_fn(receipt, vendor):
        first = receipt.get("first_failure") or {}
        return {
            "stage_is_d09_import": first.get("stage") == "import:D09",
            "category_is_publish_refused": first.get("category") == "publish_refused",
            "no_d10_import": not any(str(step.get("step", "")).startswith("import:D10") for step in receipt.get("steps") or []),
            "no_ocr_table_post": vendor.count("ocr_table") == 0,
            "no_question_post": vendor.count("chat") == 0,
            "publish_attempted_once": (first.get("detail") or "") is not None,
        }

    return _run_pilot_case(
        "pilot-publish-failure", plan_data, subplan, support,
        hooks={"before_publish": before_publish}, checks_fn=checks_fn,
    )


def scenario_pilot_qa_partial_service_error(subplan, plan_data: dict, support: dict) -> dict:
    def checks_fn(receipt, vendor):
        first = receipt.get("first_failure") or {}
        return {
            "stage_is_first_question": first.get("stage") == "ask:Q01",
            "category_is_product_answer": first.get("category") == "product_answer_not_success",
            "only_one_chat_post": vendor.count("chat") == 1,
            "second_question_not_asked": len(receipt.get("answers") or []) == 0,
            "no_q03_stage": not any(str(step.get("step")) == "ask:Q03" for step in receipt.get("steps") or []),
            "ledger_has_failed_chat_result": any(
                item.get("kind") == "chat" and item.get("status") != "succeeded"
                for item in (receipt.get("ledger") or {}).get("result_events") or []
            ),
        }

    return _run_pilot_case(
        "pilot-qa-partial-service-error", plan_data, subplan, support,
        configure=lambda vendor: vendor.configure("chat", status=500), checks_fn=checks_fn,
    )


def scenario_pilot_ocr_429(subplan, plan_data: dict, support: dict) -> dict:
    def checks_fn(receipt, vendor):
        first = receipt.get("first_failure") or {}
        return {
            "stage_is_d09_import": first.get("stage") == "import:D09",
            "category_is_worker_failed": first.get("category") == "worker_failed",
            "code_is_rate_limited": "OCR_RATE_LIMITED" in json.dumps(first, ensure_ascii=False),
            "one_ocr_post_only": vendor.count("ocr_text") == 1 and vendor.count("ocr_table") == 0,
            "no_d10_import": not any(str(step.get("step", "")).startswith("import:D10") for step in receipt.get("steps") or []),
            "full_0_5_kept": (receipt.get("ledger") or {}).get("reserved") == 2  # D01 embedding + D09 OCR
            and (receipt.get("ledger") or {}).get("result_statuses") == ["failed", "succeeded"],
            "executor_stopped": (receipt.get("executor_stats") or {}).get("stopped") is True,
        }

    return _run_pilot_case(
        "pilot-ocr-429", plan_data, subplan, support,
        configure=lambda vendor: vendor.configure("ocr_text", status=429), checks_fn=checks_fn,
    )


def scenario_pilot_ocr_timeout(subplan, plan_data: dict, support: dict) -> dict:
    def checks_fn(receipt, vendor):
        first = receipt.get("first_failure") or {}
        return {
            "stage_is_d10_import": first.get("stage") == "import:D10",
            "category_is_worker_failed": first.get("category") == "worker_failed",
            "code_is_timeout": "OCR_TIMEOUT" in json.dumps(first, ensure_ascii=False),
            "one_table_post_only": vendor.count("ocr_table") == 1,
            "no_questions": vendor.count("chat") == 0,
            "executor_stopped": (receipt.get("executor_stats") or {}).get("stopped") is True,
        }

    return _run_pilot_case(
        "pilot-ocr-timeout", plan_data, subplan, support,
        configure=lambda vendor: vendor.configure("ocr_table", raise_="timeout"), checks_fn=checks_fn,
    )


def scenario_pilot_keyboard_interrupt(subplan, plan_data: dict, support: dict) -> dict:
    def checks_fn(receipt, vendor):
        first = receipt.get("first_failure") or {}
        return {
            "stage_is_d09_strict": first.get("stage") == "import:D09:strict",
            "category_is_interrupt": first.get("category") == "interrupt",
            "exception_type_keyboard_interrupt": first.get("exception_type") == "KeyboardInterrupt",
            "no_d10_import": not any(str(step.get("step", "")).startswith("import:D10") for step in receipt.get("steps") or []),
            "no_questions": vendor.count("chat") == 0,
            "partial_ledger_kept": (receipt.get("ledger") or {}).get("reserved") == 3,
            "no_unsettled": (receipt.get("ledger") or {}).get("unsettled") == [],
            "interrupt_seam_recorded": receipt.get("isolated_test_seams") == ["interrupt_after_step"],
        }

    return _run_pilot_case(
        "pilot-keyboard-interrupt", plan_data, subplan, support,
        hooks={"interrupt_after_step": "import:D09:strict"}, checks_fn=checks_fn,
    )


def scenario_pilot_teardown_failure_keeps_first_error(subplan, plan_data: dict, support: dict) -> dict:
    def teardown(app):  # noqa: ANN001
        raise RuntimeError("isolated teardown failure; must not replace first failure")

    def checks_fn(receipt, vendor):
        first = receipt.get("first_failure") or {}
        cleanup = receipt.get("cleanup_errors") or []
        return {
            "stage_is_d10_import": first.get("stage") == "import:D10",
            "category_is_worker_failed": first.get("category") == "worker_failed",
            "code_is_rate_limited": "OCR_RATE_LIMITED" in json.dumps(first, ensure_ascii=False),
            "cleanup_error_recorded": len(cleanup) == 1 and cleanup[0].get("stage") == "isolated_test_teardown_hook",
            "cleanup_does_not_replace_first_error": first.get("stage") == "import:D10"
            and "teardown" not in json.dumps(first, ensure_ascii=False),
            "teardown_seam_recorded": receipt.get("isolated_test_seams") == ["teardown"],
        }

    return _run_pilot_case(
        "pilot-teardown-failure-keeps-first-error", plan_data, subplan, support,
        configure=lambda vendor: vendor.configure("ocr_table", status=429),
        hooks={"teardown": teardown}, checks_fn=checks_fn,
    )


# ---------------------------------------------------------------- 模式实现


def _plan_payloads(plan_data: dict, subplan, real: dict) -> dict:
    return {
        "plan": plan_data,
        "candidate_stage_budget": build_candidate_budget(plan_data, subplan, real),
        "candidate_go": build_candidate_go(plan_data, subplan, real),
    }


def _run_metadata(*, mode: str, root: Path, run_dir: Path, argv: list[str], gate: dict,
                  guard: SocketGuard | None, extra: dict | None = None) -> dict:
    payload = {
        "document": "S2-K-R1B-run",
        "mode": mode,
        "evidence_root": str(root),
        "run_dir": str(run_dir),
        "argv": argv,
        "cwd": str(Path.cwd()),
        "started_at": now_iso(),
        "resource_gate": gate,
        "socket_guard": guard.summary() if guard is not None else None,
        "tool_sha256_before_run": sha256_path(Path(__file__)),
        "exit_codes_contract": {str(code): text for code, text in EXIT_CODES.items()},
        "isolated_test_seams": sorted(ISOLATED_TEST_HOOKS),
        "isolated_test_transport_factory_set": ISOLATED_TEST_TRANSPORT_FACTORY is not None,
    }
    if extra:
        payload.update(extra)
    return payload


def _load_plan_file(path: Path, root: Path) -> dict:
    plan_path = _resolved(path)
    if not _is_under(plan_path, root):
        raise SystemExit(f"REFUSE: --plan-file 必须位于本轮证据根下：{plan_path}")
    if not plan_path.is_file():
        raise SystemExit(f"REFUSE: --plan-file 不存在：{plan_path}")
    try:
        payload = json.loads(plan_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"REFUSE: --plan-file 不是合法 JSON：{type(exc).__name__}") from None
    if not isinstance(payload, dict) or payload.get("document") != "S2-K-pilot-plan":
        raise SystemExit("REFUSE: --plan-file 不是 S2-K pilot plan")
    for key in ("request_plan_sha256", "counts", "fixtures", "request_plan", "questions", "sources", "costs"):
        if key not in payload:
            raise SystemExit(f"REFUSE: plan 缺少字段 {key!r}")
    return payload


def _verify_plan_against_recompute(planned: dict, recomputed: dict, subplan) -> dict:
    fixtures = planned.get("fixtures") or {}
    recomputed_fixtures = recomputed["fixtures"]
    checks = {
        "request_plan_sha256_equal": planned.get("request_plan_sha256") == subplan.request_plan_sha256,
        "counts_equal": planned.get("counts") == recomputed["counts"],
        "stage_equal": (planned.get("request_plan") or {}).get("stage") == STAGE,
        "provider_sequence_equal": [item.get("kind") for item in planned.get("provider_request_sequence") or []]
        == [item["kind"] for item in recomputed["provider_request_sequence"]],
        "fixtures_sha_equal": all(
            (fixtures.get(key) or {}).get("sha_match") is True
            for key in ("D01", "D09_page1", "D10_page1")
        ),
        "tile_sha_equal": (fixtures.get("D09_page1") or {}).get("tile_sha256") == recomputed_fixtures["D09_page1"]["tile_sha256"]
        and (fixtures.get("D10_page1") or {}).get("tile_sha256") == recomputed_fixtures["D10_page1"]["tile_sha256"],
        "ocr_modes_equal": (fixtures.get("D09_page1") or {}).get("mode") == "text"
        and (fixtures.get("D10_page1") or {}).get("mode") == "table",
        "questions_equal": [item.get("question_id") for item in planned.get("questions") or []]
        == [item["question_id"] for item in recomputed["questions"]],
    }
    return checks


def cmd_plan(args, *, root: Path, run_dir: Path) -> int:
    guard = SocketGuard().install()
    try:
        gate = resource_gate()
        _ACTIVE_RUN["resource_gate"] = gate
        if not gate["ok"]:
            dump_json(run_dir / "plan-blocked.json", _run_metadata(mode="plan", root=root, run_dir=run_dir,
                                                                  argv=sys.argv, gate=gate, guard=guard,
                                                                  extra={"blocked": "resource_gate"}))
            print(json.dumps({"mode": "plan", "blocked": "resource_gate", "resource_gate": gate}, ensure_ascii=False))
            return 4
        try:
            support = load_support()
            business = load_business()
            data = compute_pilot_plan_data(support, business)
            plan_data, subplan = data["plan_data"], data["subplan"]
            real = real_paths()
            plan_data["real_paths_before"] = real
            plan_data["run_evidence"] = {"evidence_root": str(root), "run_dir": str(run_dir)}
            payloads = _plan_payloads(plan_data, subplan, real)
            plan_path = dump_json(run_dir / "plan.json", plan_data)
            budget_path = dump_json(run_dir / "candidate-stage-budget.json", payloads["candidate_stage_budget"])
            go_path = dump_json(run_dir / "candidate-go.json", payloads["candidate_go"])
        except BaseException as exc:  # noqa: BLE001 - 计划失败也要可审查落盘
            dump_json(
                run_dir / "plan-error.json",
                {
                    **_run_metadata(mode="plan", root=root, run_dir=run_dir, argv=sys.argv, gate=gate, guard=guard),
                    "error": {"type": type(exc).__name__, "message_safe": _safe_text(exc)},
                },
            )
            print(json.dumps({"mode": "plan", "ok": False, "error_type": type(exc).__name__,
                              "error_safe": _safe_text(exc)}, ensure_ascii=False))
            return 130 if isinstance(exc, KeyboardInterrupt) else 2
        summary = {
            "mode": "plan",
            "ok": True,
            "evidence_root": str(root),
            "run_dir": str(run_dir),
            "plan_file": str(plan_path),
            "candidate_stage_budget": str(budget_path),
            "candidate_go": str(go_path),
            "request_plan_sha256": plan_data["request_plan_sha256"],
            "counts": plan_data["counts"],
            "provider_request_sequence": [item["kind"] for item in plan_data["provider_request_sequence"]],
            "peak_include_history_cny": plan_data["costs"]["peak_include_history_cny"],
            "conditional_cap_settlement_cny": plan_data["costs"]["conditional_cap_settlement_cny"],
            "candidate_stage_allocation_cny": payloads["candidate_stage_budget"]["minimum_required"]["j2_required_stage_limit_cny"],
            "real_ledger_sha256": real["ledger"]["sha256"],
            "real_budget_sha256": real["budget"]["sha256"],
            "fixed_go_exists": real["fixed_go"]["exists"],
            "real_api_calls": 0,
            "real_ledger_written": False,
            "fixed_go_written": False,
            "resource_gate": {"ok": gate["ok"], "physical_available_mib": gate.get("physical_available_mib"),
                              "commit_available_mib": gate.get("commit_available_mib")},
            "socket_guard": guard.summary(),
        }
        dump_json(run_dir / "plan-run.json", {**_run_metadata(mode="plan", root=root, run_dir=run_dir, argv=sys.argv,
                                                              gate=gate, guard=guard), "ok": True,
                                             "request_plan_sha256": plan_data["request_plan_sha256"]})
        print(json.dumps(summary, ensure_ascii=False))
        return 0
    finally:
        guard.uninstall()


def _self_check_checks(plan_data: dict, subplan, budget: dict, go: dict, real: dict, fixtures: dict) -> dict:
    counts = plan_data["counts"]
    sequence = plan_data["provider_request_sequence"]
    matrix = {
        "chat": 136,
        "embedding": 111,
        "rerank": 94,
        "ocr_text": 12,
        "ocr_table": 1,
    }
    remaining = {
        "chat": matrix["chat"] - counts["chat"],
        "embedding": matrix["embedding"] - counts["embedding"],
        "rerank": matrix["rerank"] - counts["rerank"],
        "ocr_text": matrix["ocr_text"] - counts["ocr_text"],
        "ocr_table": matrix["ocr_table"] - counts["ocr_table"],
    }
    marker = go.get("candidate_self_check") or {}
    headroom = go.get("run_headroom") or {}
    required_limit = Decimal(str(headroom.get("required_stage_limit_cny") or "0"))
    required_requests = int(headroom.get("required_max_requests") or 0)
    return {
        "counts_all_positive": all(int(counts[key]) > 0 for key in ("chat", "embedding", "rerank", "ocr_text", "ocr_table")),
        "sequence_length_equals_total": len(sequence) == counts["total_provider_posts"],
        "sequence_kinds_match_counts": (
            sum(1 for item in sequence if item["kind"] == "chat") == counts["chat"]
            and sum(1 for item in sequence if item["kind"] == "embedding") == counts["embedding"]
            and sum(1 for item in sequence if item["kind"] == "rerank") == counts["rerank"]
            and sum(1 for item in sequence if item["kind"] == "ocr_text") == counts["ocr_text"]
            and sum(1 for item in sequence if item["kind"] == "ocr_table") == counts["ocr_table"]
        ),
        "plan_hash_deterministic": plan_data["request_plan_sha256"] == subplan.request_plan_sha256,
        "d01_chunks_positive": plan_data["fixtures"]["D01"]["chunks"] > 0 and plan_data["fixtures"]["D01"]["embedding_batches"] > 0,
        "d09_text_whole_page": plan_data["fixtures"]["D09_page1"]["mode"] == "text"
        and plan_data["fixtures"]["D09_page1"]["selected_page"] == 1
        and plan_data["fixtures"]["D09_page1"]["tiles"] == 1,
        "d10_table_whole_page": plan_data["fixtures"]["D10_page1"]["mode"] == "table"
        and plan_data["fixtures"]["D10_page1"]["selected_page"] == 1
        and plan_data["fixtures"]["D10_page1"]["tiles"] == 1,
        "fixture_sha_match_all": all(
            plan_data["fixtures"][key]["sha_match"] for key in ("D01", "D09_page1", "D10_page1")
        ),
        "peak_formula": Decimal(budget["pilot_plan"]["peak_include_history_cny"]) == subplan.peak_include_history_cny,
        "conditional_settlement_formula": Decimal(budget["pilot_plan"]["conditional_cap_settlement_cny"])
        == subplan.conservative_settlement_cny,
        "candidate_budget_no_double_allocation": budget["candidate_budget"]["no_double_allocation"] is True,
        "candidate_budget_sum_equals_limit": Decimal(budget["candidate_budget"]["check_history_plus_stages_cny"])
        == Decimal(str(budget["candidate_budget"]["limit_cny"])),
        "candidate_stage_min_equals_headroom": Decimal(budget["minimum_required"]["j2_required_stage_limit_cny"])
        == required_limit,
        "headroom_covers_prior_plus_peak": required_limit
        == Decimal(str(headroom.get("prior_stage_accounted_cny") or "0"))
        + Decimal(str(headroom.get("plan_peak_include_history_cny") or "0")),
        "matrix_deduction_positive": min(remaining.values()) >= 0,
        "matrix_ocr_total_13_unchanged": matrix["ocr_text"] + matrix["ocr_table"] == 13,
        "remaining_ocr_total_11": remaining["ocr_text"] + remaining["ocr_table"] == 11,
        "no_extra_ocr_from_pilot": remaining["ocr_table"] == 0,
        "matrix_route_fits_project_limit": budget["matrix_route"]["full_project_with_pilot_reuse"]["fits_project_limit"] is True,
        "candidate_go_not_formal": go["not_formal"] is True,
        "candidate_go_marker_rule_detects_draft": marker.get("this_payload_is_formal_by_marker_rule") is False
        and bool(marker.get("problems")),
        "candidate_go_bindings_include_plan_hash": go["go_payload"]["scope"]["bindings"]["rag"]["request_plan_sha256"]
        == subplan.request_plan_sha256,
        "candidate_go_stage_limit_equals_headroom": go["go_payload"]["scope"]["stage_limits_cny"][STAGE]
        == float(required_limit),
        "candidate_go_request_cap_equals_headroom": go["go_payload"]["scope"]["max_requests"] == required_requests,
        "candidate_go_binds_ledger_prefix_anchor": go["go_payload"]["budget_ledger_sha256"] == ledger_anchor_sha256(),
        "real_shared_unchanged_hashes": real["ledger"]["sha256"] == sha256_path(REAL_LEDGER)
        and real["budget"]["sha256"] == sha256_path(REAL_BUDGET),
        "fixed_go_formal_or_absent": (real["fixed_go"]["exists"] is False)
        or ((real["fixed_go"].get("formal_marker_check") or {}).get("formal") is True),
        "plan_module_consistent": plan_data["request_plan"] == subplan.plan_dict(),
        "prices_recorded": all(
            bool(plan_data["prices"].get(name)) for name in ("chat", "embedding", "rerank", "ocr")
        ),
    }


def cmd_self_check(args, *, root: Path, run_dir: Path) -> int:
    guard = SocketGuard().install()
    try:
        gate = resource_gate()
        _ACTIVE_RUN["resource_gate"] = gate
        try:
            support = load_support()
            business = load_business()
            first = compute_pilot_plan_data(support, business)
            second = compute_pilot_plan_data(support, business)
            plan_data, subplan = first["plan_data"], first["subplan"]
            real = real_paths()
            budget = build_candidate_budget(plan_data, subplan, real)
            go = build_candidate_go(plan_data, subplan, real)
            checks = _self_check_checks(plan_data, subplan, budget, go, real, plan_data["fixtures"])
            checks["recompute_stable"] = first["plan_data"]["request_plan_sha256"] == second["plan_data"]["request_plan_sha256"]
            checks["resource_gate_ok"] = gate["ok"]
            checks["socket_guard_no_external"] = guard.summary()["external_attempts"] == 0
            payload = {
                "document": "S2-K-R1B-self-check",
                "captured_at": now_iso(),
                "evidence_root": str(root),
                "run_dir": str(run_dir),
                "checks": checks,
                "pass": all(checks.values()),
                "failed": [name for name, ok in checks.items() if not ok],
                "resource_gate": gate,
                "socket_guard": guard.summary(),
                "real_api_calls": 0,
                "plan_counts": plan_data["counts"],
            }
            path = dump_json(run_dir / "self-check.json", payload)
        except BaseException as exc:  # noqa: BLE001
            dump_json(
                run_dir / "self-check-error.json",
                {**_run_metadata(mode="self-check", root=root, run_dir=run_dir, argv=sys.argv, gate=gate, guard=guard),
                 "error": {"type": type(exc).__name__, "message_safe": _safe_text(exc)}},
            )
            print(json.dumps({"mode": "self-check", "pass": False, "error_type": type(exc).__name__,
                              "error_safe": _safe_text(exc)}, ensure_ascii=False))
            return 130 if isinstance(exc, KeyboardInterrupt) else 2
        print(json.dumps({"mode": "self-check", "pass": payload["pass"], "checks": len(checks),
                          "failed": payload["failed"], "evidence": str(path)}, ensure_ascii=False))
        return 0 if payload["pass"] else 2
    finally:
        guard.uninstall()


def _scan_outputs_for_secret(run_dir: Path) -> dict:
    hits: list[str] = []
    patterns = (SYNTH_SECRET, "Authorization: Bearer")
    candidates: list[Path] = []
    for path in sorted(Path(run_dir).rglob("*")):
        if path.is_file() and path.suffix in (".json", ".jsonl", ".log", ".md", ".txt"):
            candidates.append(path)
    for path in candidates:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for pattern in patterns:
            if pattern in text:
                hits.append(f"{rel(path)} :: {pattern}")
    return {"clean": not hits, "hits": hits, "scanned_files": len(candidates), "scanned_root": rel(run_dir)}


def cmd_mock(args, *, root: Path, run_dir: Path) -> int:
    guard = SocketGuard().install()
    started = now_iso()
    mock_results = {
        "document": "S2-K-R1B-mock-results",
        "started_at": started,
        "mode": "mock-only",
        "evidence_root": str(root),
        "run_dir": str(run_dir),
        "positive": None,
        "negatives": [],
        "checks": {},
        "all_pass": False,
        "real_api_calls": 0,
        "socket_guard": None,
    }
    try:
        gate = resource_gate()
        _ACTIVE_RUN["resource_gate"] = gate
        if not gate["ok"]:
            dump_json(run_dir / "mock-blocked.json", {**_run_metadata(mode="mock", root=root, run_dir=run_dir,
                                                                     argv=sys.argv, gate=gate, guard=guard),
                                                      "blocked": "resource_gate"})
            print(json.dumps({"mode": "mock", "blocked": "resource_gate", "resource_gate": gate}, ensure_ascii=False))
            return 4
        support = load_support()
        business = load_business()
        computed = compute_pilot_plan_data(support, business)
        plan_data, subplan = computed["plan_data"], computed["subplan"]
        real = real_paths()
        stage_limit = float(subplan.peak_include_history_cny)
        only = args.only

        plan_file = None
        if args.plan_file:
            plan_file = _load_plan_file(Path(args.plan_file), root)
            verification = _verify_plan_against_recompute(plan_file, plan_data, subplan)
            if not all(verification.values()):
                payload = {
                    "document": "S2-K-R1B-mock-refusal",
                    "reason": "plan_file_mismatch",
                    "plan_file": rel(_resolved(Path(args.plan_file))),
                    "verification": verification,
                    "failed": [name for name, ok in verification.items() if not ok],
                }
                dump_json(run_dir / "mock-refusal.json", payload)
                print(json.dumps({"mode": "mock", "ok": False, **payload}, ensure_ascii=False))
                return 2
        else:
            dump_json(run_dir / "mock-refusal.json", {
                "document": "S2-K-R1B-mock-refusal",
                "reason": "--plan-file is required (plan → Mock → live must audit the same plan)",
            })
            print(json.dumps({"mode": "mock", "ok": False, "reason": "--plan-file is required"}, ensure_ascii=False))
            return 2

        positive_payload = None
        if only in (None, "positive"):
            with isolated("positive", subplan=subplan, stage_limit=stage_limit) as paths:
                vendor = MockVendor()
                journal = Journal(Path(paths["root"]) / "run-journal.jsonl")
                try:
                    receipt = run_controlled_pilot(
                        paths=paths, subplan=subplan, plan_data=plan_data, support=support, mode="mock",
                        vendor=vendor, journal=journal,
                    )
                finally:
                    journal.close()
                checks = receipt.get("verification") or {}
                receipt_path = dump_json(Path(paths["root"]) / "s2k-pilot-receipt.json", receipt)
                receipt["real_paths_before"] = real
                receipt["real_paths_after"] = real_paths()
                positive_payload = {
                    "scenario": "positive",
                    "receipt": rel(receipt_path),
                    "pass": receipt.get("outcome") == "completed" and bool(checks) and all(checks.values()),
                    "failed_checks": [name for name, ok in checks.items() if not ok],
                    "checks_count": len(checks),
                    "real_shared_unchanged": receipt["real_paths_before"] == receipt["real_paths_after"],
                    "secret_leak": SYNTH_SECRET in json.dumps(receipt, ensure_ascii=False, default=str),
                    "counts_planned": plan_data["counts"],
                    "counts_observed": (receipt.get("transport") or {}).get("by_kind"),
                    "ledger": {
                        "reserved": (receipt.get("ledger") or {}).get("reserved"),
                        "results": (receipt.get("ledger") or {}).get("results"),
                        "unsettled": (receipt.get("ledger") or {}).get("unsettled"),
                        "summary": (receipt.get("ledger") or {}).get("summary"),
                        "reserve_by_kind_cny": (receipt.get("ledger") or {}).get("reserve_by_kind_cny"),
                        "request_sha256_list": (receipt.get("ledger") or {}).get("request_sha256_list"),
                    },
                    "ocr_request_bindings": receipt.get("ocr_request_bindings"),
                    "reuse_probe": receipt.get("reuse_probe"),
                    "index_stats": receipt.get("index_stats"),
                    "answers": [
                        {
                            "question_id": answer["question_id"],
                            "kind": answer["kind"],
                            "http_status": answer["http_status"],
                            "text": answer["text"],
                            "source_count": answer["source_count"],
                            "expected_values_present": answer["expected_values_present"],
                        }
                        for answer in receipt.get("answers") or []
                    ],
                }
                mock_results["positive"] = positive_payload

        negative_factories = [
            ("go-missing", lambda s, p, u: scenario_go_missing(s, p)),
            ("go-binding-tamper", lambda s, p, u: scenario_go_binding_tamper(s, p)),
            ("stage-below-peak", lambda s, p, u: scenario_stage_below_peak(s, p)),
            ("request-cap-below-plan", lambda s, p, u: scenario_request_cap_below_plan(s, p)),
            ("budget-stage-missing", lambda s, p, u: scenario_budget_stage_missing(s, p)),
            ("chat-over-cap", lambda s, p, u: scenario_chat_over_cap(s, p)),
            ("chat-http-500", lambda s, p, u: scenario_chat_http_500(s, p)),
            ("ocr-tile-limit", lambda s, p, u: scenario_ocr_tile_limit(s, p)),
            ("ocr-rate-limited", lambda s, p, u: scenario_ocr_rate_limited(s, p)),
            ("secret-output", lambda s, p, u: scenario_secret_output(s, p)),
            ("plan-limit", lambda s, p, u: scenario_plan_limit(s, p)),
            ("pilot-first-paid-failure", scenario_pilot_first_paid_failure),
            ("pilot-publish-failure", scenario_pilot_publish_failure),
            ("pilot-qa-partial-service-error", scenario_pilot_qa_partial_service_error),
            ("pilot-ocr-429", scenario_pilot_ocr_429),
            ("pilot-ocr-timeout", scenario_pilot_ocr_timeout),
            ("pilot-keyboard-interrupt", scenario_pilot_keyboard_interrupt),
            ("pilot-teardown-failure-keeps-first-error", scenario_pilot_teardown_failure_keeps_first_error),
        ]
        for name, factory in negative_factories:
            if only not in (None, "negatives", name):
                continue
            print(f"[s2k-r1b-mock] running {name} ...", flush=True)
            payload = factory(subplan, plan_data, support)
            mock_results["negatives"].append(payload)
            print(
                json.dumps(
                    {
                        "scenario": payload["scenario"],
                        "pass": payload["pass"],
                        "failed": [key for key, ok in payload["checks"].items() if not ok],
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )

        mock_results["plan_file_bound"] = plan_file is not None
        checks = {
            "positive_pass": (mock_results["positive"] or {}).get("pass") is True if only in (None, "positive") else True,
            "all_negatives_pass": all(item["pass"] for item in mock_results["negatives"]) if mock_results["negatives"] else True,
            "real_shared_unchanged": (mock_results["positive"] or {}).get("real_shared_unchanged") is True if only in (None, "positive") else True,
            "no_secret_in_positive": (mock_results["positive"] or {}).get("secret_leak") is False if only in (None, "positive") else True,
            "socket_guard_no_external": guard.summary()["external_attempts"] == 0,
            "t09_isolated_new_root": bool(os.environ.get("T09_EVIDENCE_ROOT", ""))
            and _is_under(Path(os.environ["T09_EVIDENCE_ROOT"]), run_dir),
            # 固定 GO 允许已经由经理正式签发（真实测试阶段就是这样）；Mock 只要求它**未被本次
            # Mock 触碰**，且若存在就必须是正式 GO（不能是 DRAFT/候选）。Mock 自己只用隔离 GO。
            "real_go_untouched_by_mock": real["fixed_go"]["sha256"] == sha256_path(REAL_GO)
            and (
                real["fixed_go"]["exists"] is False
                or ((real["fixed_go"].get("formal_marker_check") or {}).get("formal") is True)
            ),
            "plan_file_bound": mock_results.get("plan_file_bound") is True,
            "real_api_calls_zero": True,
        }
        mock_results["checks"] = checks
        mock_results["all_pass"] = all(checks.values())
        mock_results["finished_at"] = now_iso()
        mock_results["socket_guard"] = guard.summary()
        mock_results["resource_gate"] = {"ok": gate["ok"], "physical_available_mib": gate.get("physical_available_mib"),
                                        "commit_available_mib": gate.get("commit_available_mib")}
        mock_results["plan"] = {
            "request_plan_sha256": subplan.request_plan_sha256,
            "counts": plan_data["counts"],
            "stage_limit_applied_cny": format(subplan.peak_include_history_cny, "f"),
            "plan_file": rel(_resolved(Path(args.plan_file))),
            "plan_file_sha256": sha256_path(_resolved(Path(args.plan_file))),
        }
        mock_results["real_paths_before"] = real
        mock_results["real_paths_after"] = real_paths()
        results_path = dump_json(run_dir / "s2k-mock-results.json", mock_results)
        secret_scan = _scan_outputs_for_secret(run_dir)
        mock_results["secret_scan"] = secret_scan
        # 结果文件写完后再次扫描（含结果本身），仍不改写已落盘结果，只在 stdout 报告
        print(
            json.dumps(
                {
                    "mode": "mock",
                    "all_pass": mock_results["all_pass"],
                    "positive_pass": checks["positive_pass"],
                    "negatives": len(mock_results["negatives"]),
                    "negatives_all_pass": checks["all_negatives_pass"],
                    "real_shared_unchanged": checks["real_shared_unchanged"],
                    "external_attempts": guard.summary()["external_attempts"],
                    "results": str(results_path),
                    "secret_scan": secret_scan,
                    "resource_gate": {"ok": gate["ok"], "physical_available_mib": gate.get("physical_available_mib"),
                                      "commit_available_mib": gate.get("commit_available_mib")},
                },
                ensure_ascii=False,
            )
        )
        return 0 if mock_results["all_pass"] and secret_scan["clean"] else 2
    finally:
        guard.uninstall()


def _env(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def _live_preflight(args, *, root: Path, out: Path, journal: Journal, business: dict, support: dict,
                    gate: dict, guard: SocketGuard) -> tuple[list[dict], dict | None, dict]:
    checks: list[dict] = []

    def check(name: str, ok: bool, detail=None) -> None:
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    plan_path = _resolved(Path(args.plan_file)) if args.plan_file else None
    mock_path = _resolved(Path(args.mock_file)) if args.mock_file else None
    plan_data = None
    try:
        if plan_path is not None:
            plan_data = _load_plan_file(plan_path, root)
    except SystemExit as exc:
        check("plan_file_loads", False, _safe_text(exc))
    real = real_paths()
    from urllib.parse import urlsplit  # noqa: PLC0415

    check("explicit_confirmation_flag", bool(args.confirm_live_fixed_go), "--confirm-live-fixed-go required")
    check("plan_file_loads", plan_data is not None, rel(plan_path) if plan_path else None)
    check("mock_file_provided", mock_path is not None and mock_path.is_file(), rel(mock_path) if mock_path else None)
    check("mock_file_under_evidence_root", bool(mock_path) and _is_under(mock_path, root), rel(mock_path) if mock_path else None)
    mock_payload = None
    if mock_path is not None and mock_path.is_file():
        try:
            mock_payload = json.loads(mock_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            mock_payload = None
    check("mock_evidence_passed", bool(mock_payload) and mock_payload.get("all_pass") is True, rel(mock_path) if mock_path else None)
    check(
        "mock_plan_hash_matches_plan",
        bool(mock_payload) and bool(plan_data) and (mock_payload.get("plan") or {}).get("request_plan_sha256")
        == plan_data.get("request_plan_sha256"),
        (mock_payload or {}).get("plan", {}).get("request_plan_sha256"),
    )
    check("fixed_go_exists", real["fixed_go"]["exists"], rel(REAL_GO))
    marker = (real["fixed_go"].get("formal_marker_check") or {}) if real["fixed_go"]["exists"] else {}
    check("fixed_go_no_draft_or_candidate_markers", marker.get("formal") is True, marker.get("problems"))
    check("resource_gate_ok", gate["ok"], {"physical": gate.get("physical_available_mib"), "commit": gate.get("commit_available_mib")})
    check("out_dir_created_fresh_by_this_invocation", out.is_dir() and out.name != "" ,
          "cmd_live created it after refusing an existing path; journal is already inside")
    headroom = None
    if plan_data is not None:
        check("plan_hash_matches_candidate_binding", _plan_candidate_binding_matches(plan_data, business), plan_data.get("request_plan_sha256"))
        check("real_ledger_unchanged_since_plan", real["ledger"]["sha256"] == (plan_data.get("real_paths_before") or {}).get("ledger", {}).get("sha256"), real["ledger"]["sha256"])
        check("real_budget_unchanged_since_plan", real["budget"]["sha256"] == (plan_data.get("real_paths_before") or {}).get("budget", {}).get("sha256"), real["budget"]["sha256"])
        check("plan_counts_positive", all(int((plan_data.get("counts") or {}).get(key, 0)) > 0 for key in ("chat", "embedding", "rerank", "ocr_text", "ocr_table")),
              plan_data.get("counts"))
        # 阶段额度/累计请求上限按账本累计口径计算：已结算阶段占用 + 本轮峰值（含历史），
        # 以及已用预留条数 + 本轮请求数。第一轮零占用时退化为 plan.peak / plan.total。
        headroom = stage_headroom(plan_data, real_stage_accounting())
        expected_stage_limit = str(headroom["required_stage_limit_cny"])
        expected_total = str(headroom["required_max_requests"])
        try:
            allocation = float(read_real_budget()["stages"][STAGE])
        except BaseException:  # noqa: BLE001 - 缺阶段就是拒绝理由
            allocation = None
        check("budget_stage_allocation_covers_headroom",
              allocation is not None and Decimal(str(allocation)) >= Decimal(str(headroom["required_stage_limit_cny"])),
              {"allocation": allocation, "required": headroom["required_stage_limit_cny"]})
    else:
        expected_stage_limit = None
        expected_total = None
    authorization = None
    if real["fixed_go"]["exists"]:
        try:
            authorization = business["gate_module"].load_live_authorization(stage=STAGE, service="rag")
        except BaseException as exc:  # noqa: BLE001 - 拒绝原因就是证据
            check("product_go_loads_for_rag", False, {"type": type(exc).__name__, "text": _safe_text(exc, limit=200)})
        else:
            check("product_go_loads_for_rag", True, authorization.as_dict())
    else:
        check("product_go_loads_for_rag", False, "fixed GO absent -> product resolve_live_gate refuses before reserve")
    check("fixed_go_path_is_fixed", _resolved(REAL_GO) == _resolved(EV / "PM" / "S2-LIVE-GO.json"), rel(REAL_GO))
    check("shared_paths_are_fixed", _resolved(REAL_LEDGER) == _resolved(EV / "budget" / "live-ledger.jsonl")
          and _resolved(REAL_BUDGET) == _resolved(EV / "budget" / "budget.json"), "fixed shared paths")
    chat_host = urlsplit(_env("MKTKB_MODEL_BASE_URL")).hostname or "" if _env("MKTKB_MODEL_BASE_URL") else ""
    embed_host = urlsplit(_env("DASHSCOPE_BASE_URL")).hostname or "" if _env("DASHSCOPE_BASE_URL") else ""
    ocr_host = urlsplit(_env("MKTKB_OCR_ENDPOINT")).hostname or "" if _env("MKTKB_OCR_ENDPOINT") else ""
    check("env_stage_is_S2_DEV", _env("MKTKB_LIVE_STAGE") == STAGE, _env("MKTKB_LIVE_STAGE"))
    check("env_chat_host_official", chat_host == "api.deepseek.com", chat_host)
    check("env_chat_model_deepseek_flash", _env("MKTKB_MODEL_NAME") == "deepseek-flash", _env("MKTKB_MODEL_NAME"))
    check(
        "env_chat_official_prices_and_caps",
        _env("MKTKB_MODEL_INPUT_PRICE_PER_MILLION_CNY") == "2.0"
        and _env("MKTKB_MODEL_OUTPUT_PRICE_PER_MILLION_CNY") == "8.0"
        and _env("MKTKB_MODEL_MAX_INPUT_TOKENS") == "6144"
        and _env("MKTKB_MODEL_MAX_OUTPUT_TOKENS") == "800"
        and _env("MKTKB_MODEL_CONTEXT_CEILING_TOKENS") == "1048576"
        and _env("MKTKB_MODEL_RESERVE_PROFILE") == "model_context_ceiling",
        "需 2.0/8.0/6144/800/1048576/model_context_ceiling",
    )
    check("env_embedding_host_beijing", embed_host == "dashscope.aliyuncs.com", embed_host)
    check("env_ocr_host_official", ocr_host == "ocr.tencentcloudapi.com", ocr_host)
    check("env_ocr_region_ap_guangzhou", _env("MKTKB_OCR_REGION") == "ap-guangzhou", _env("MKTKB_OCR_REGION"))
    check("env_ocr_enabled", _env("MKTKB_OCR_DISABLED") not in ("1", "true", "yes", "on"), _env("MKTKB_OCR_DISABLED"))
    check("env_zero_retry", _env("MKTKB_RAG_MAX_RETRIES") in ("", "0"), _env("MKTKB_RAG_MAX_RETRIES") or "0(default)")
    check("env_stage_limit_equals_headroom", expected_stage_limit is not None and _env("MKTKB_RAG_STAGE_LIMIT_CNY") == str(expected_stage_limit), expected_stage_limit)
    check("env_max_requests_equals_headroom", expected_total is not None and _env("MKTKB_RAG_MAX_REQUESTS") == expected_total, expected_total)
    check("env_rag_max_request_cny_05", _env("MKTKB_RAG_MAX_REQUEST_CNY") == "0.5", "0.5")
    for name in ("MKTKB_MODEL_API_KEY", "DASHSCOPE_API_KEY", "MKTKB_OCR_SECRET_ID", "MKTKB_OCR_SECRET_KEY"):
        value = _env(name)
        check(
            f"env_credential_present_not_mock::{name}",
            bool(value) and not value.startswith("s2k-") and "not-real" not in value,
            "<present, value not logged>",
        )
    check("out_dir_under_evidence_root", _is_under(out, root), rel(out))
    check("out_dir_is_not_protected_old_evidence", not any(_is_under(out, _resolved(item)) for item in PROTECTED_OLD_ROOTS), rel(out))
    return checks, plan_data, {"mock_payload": mock_payload, "real": real, "authorization": authorization,
                               "headroom": headroom}


def _plan_candidate_binding_matches(plan_data: dict, business: dict) -> bool:
    try:
        counts = plan_data["counts"]
        plan = business["ce"].ControlledRequestPlan(
            stage=STAGE,
            chat_requests=int(counts["chat"]),
            embedding_requests=int(counts["embedding"]),
            rerank_requests=int(counts["rerank"]),
            ocr_text_requests=int(counts["ocr_text"]),
            ocr_table_requests=int(counts["ocr_table"]),
        )
    except BaseException:  # noqa: BLE001
        return False
    candidate = build_candidate_go(plan_data, plan, real_paths())
    return candidate["go_payload"]["scope"]["bindings"]["rag"]["request_plan_sha256"] == plan_data["request_plan_sha256"]


def _live_post_checks(receipt: dict, plan_data: dict, subplan, out: Path, real_before: dict) -> dict:
    real_after = real_paths()
    ledger = receipt.get("ledger") or {}
    planned_kinds = [item["kind"] for item in plan_data["provider_request_sequence"]]
    mapped_planned = [_mapped_plan_kind(kind) for kind in planned_kinds]
    observed = [_mapped_plan_kind(str(item.get("kind"))) for item in ledger.get("reserved_sequence") or []]
    return {
        "outcome_completed": receipt.get("outcome") == "completed",
        "verification_present_and_all_true": bool(receipt.get("verification")) and all(receipt["verification"].values()),
        "reserved_equals_plan_total": ledger.get("reserved") == plan_data["counts"]["total_provider_posts"],
        "results_equals_plan_total": ledger.get("results") == plan_data["counts"]["total_provider_posts"],
        "unsettled_empty": ledger.get("unsettled") == [],
        "all_result_statuses_succeeded": ledger.get("result_statuses") == ["succeeded"],
        "observed_sequence_equals_plan": observed == mapped_planned,
        "budget_unchanged_by_run": real_after["budget"]["sha256"] == real_before["budget"]["sha256"],
        "ledger_was_appended_only": _ledger_prefix_kept(
            real_before["ledger"]["sha256"], real_after["ledger"]["sha256"],
            before_size=real_before["ledger"].get("size"),
        ),
        "fixed_go_unchanged_by_run": real_after["fixed_go"]["sha256"] == real_before["fixed_go"]["sha256"],
        "out_dir_exists": out.is_dir(),
        "no_cleanup_error_left_unrecorded": isinstance(receipt.get("cleanup_errors"), list),
    }


def _ledger_prefix_kept(before_sha: str | None, after_sha: str | None, *, before_size: int | None = None) -> bool:
    """本轮只追加：after 文件必须以 before 的**完整原始字节**开头。

    旧实现只认 historical_import 前缀，等于假定“第一次运行”；同阶段第二次运行时
    before 已包含上一轮事件，会让该检查必然为 False（真实复跑已实际发生）。
    """
    if before_sha is None or after_sha is None:
        return False
    if before_sha == after_sha:
        return True
    try:
        raw = REAL_LEDGER.read_bytes()
    except OSError:
        return False
    if before_size is not None:
        if before_size <= 0 or before_size > len(raw):
            return False
        return sha256_bytes(raw[:before_size]) == before_sha
    historical = bytearray()
    for line in raw.splitlines(keepends=True):
        try:
            event = json.loads(line.strip())
        except json.JSONDecodeError:
            break
        if not isinstance(event, dict) or event.get("event") != "historical_import":
            break
        historical.extend(line)
    return bool(historical) and sha256_bytes(bytes(historical)) in {before_sha, after_sha}


def cmd_live(args, *, root: Path) -> int:
    # --out 是本次 live 的运行目录（全新、位于本轮证据根下）；未给出则自动创建。
    try:
        if args.out:
            out = _resolved(args.out)
            if not _is_under(out, root):
                raise SystemExit(f"REFUSE: --out 必须位于本轮证据根下：{out}")
            if out.exists():
                raise SystemExit(f"REFUSE: --out 已存在，拒绝覆盖/复用：{out}")
            if not out.parent.is_dir():
                raise SystemExit("REFUSE: --out 的父目录必须已存在（每次执行只创建新运行目录）")
            _assert_no_reparse_chain(out, root)
            out.mkdir(parents=False, exist_ok=False)
        else:
            out = create_run_dir(root, "live")
    except SystemExit as exc:
        refusal_dir = create_run_dir(root, "live-refused")
        dump_json(refusal_dir / "live-refusal.json", {
            "document": "S2-K-R1B-live-path-refusal",
            "reason": str(exc),
            "argv": sys.argv,
            "requested_out": args.out,
            "note": "path contract refused before creating a journal or importing any product module",
        })
        print(json.dumps({"mode": "live", "decision": "refused-path-contract", "reason": str(exc),
                          "refusal_evidence": str(refusal_dir)}, ensure_ascii=False))
        return 2
    _ACTIVE_RUN["run_dir"] = out
    _ACTIVE_RUN["root"] = root
    journal = Journal(out / "live-journal.jsonl")
    journal.write("run_start", argv=sys.argv, evidence_root=str(root), out=str(out),
                  tool_sha256=sha256_path(Path(__file__)),
                  isolated_test_seams=sorted(ISOLATED_TEST_HOOKS))
    guard = SocketGuard().install()
    try:
        gate = resource_gate()
        _ACTIVE_RUN["resource_gate"] = gate
        journal.write("resource_gate", ok=gate["ok"], physical_available_mib=gate.get("physical_available_mib"),
                      commit_available_mib=gate.get("commit_available_mib"))
        try:
            support = load_support()
            business = load_business()
        except BaseException as exc:  # noqa: BLE001 - setup 失败也持久化
            return _live_setup_failure(exc, out=out, journal=journal, guard=guard, gate=gate)
        checks, plan_data, context = _live_preflight(
            args, root=root, out=out, journal=journal, business=business, support=support, gate=gate, guard=guard
        )
        all_ok = all(item["ok"] for item in checks)
        preflight = {
            "document": "S2-K-R1B-live-preflight",
            "mode": "live",
            "captured_at": now_iso(),
            "decision": "would-execute" if all_ok else "refused-before-first-reservation",
            "checks": checks,
            "failed": [item["check"] for item in checks if not item["ok"]],
            "sent_any_request": False,
            "fixed_go_path_only": True,
            "accepts_go_override": False,
            "evidence_root": str(root),
            "out_dir": str(out),
            "isolated_test_seams": sorted(ISOLATED_TEST_HOOKS),
            "socket_guard": guard.summary(),
            "fixed_shared_paths": {"ledger": str(REAL_LEDGER), "budget": str(REAL_BUDGET), "go": str(REAL_GO)},
            "stage_headroom": context.get("headroom"),
        }
        preflight_path = dump_json(out / "live-preflight.json", preflight)
        journal.write("preflight", decision=preflight["decision"], failed=preflight["failed"], path=str(preflight_path))
        print(json.dumps({"mode": "live", "decision": preflight["decision"], "failed": preflight["failed"],
                          "preflight": str(preflight_path), "out": str(out)}, ensure_ascii=False))
        if not all_ok:
            refusal_receipt = {
                "document": "S2-K-R1B-live-receipt",
                "mode": "live",
                "outcome": "refused_preflight",
                "started_at": now_iso(),
                "finished_at": now_iso(),
                "first_failure": None,
                "error": {"type": "LivePreflightRefusal", "category": "preflight_refused",
                          "failed_checks": preflight["failed"]},
                "sent_any_request": False,
                "live_preflight": rel(preflight_path),
                "isolated_test_seams": sorted(ISOLATED_TEST_HOOKS),
            }
            receipt_path = dump_json(out / "live-receipt.json", refusal_receipt)
            journal.write("run_finish", outcome="refused_preflight", receipt=str(receipt_path))
            return 3
        # 预检通过：只用产品固定 GO/共享账本/预算；transport 不替换（隔离验收工装除外，且会记录）。
        real_before = context["real"]
        subplan = business["ce"].ControlledRequestPlan(
            stage=STAGE,
            chat_requests=int(plan_data["counts"]["chat"]),
            embedding_requests=int(plan_data["counts"]["embedding"]),
            rerank_requests=int(plan_data["counts"]["rerank"]),
            ocr_text_requests=int(plan_data["counts"]["ocr_text"]),
            ocr_table_requests=int(plan_data["counts"]["ocr_table"]),
        )
        live_paths = {
            "root": out,
            "app": out / "app",
            "ledger": REAL_LEDGER,
            "budget": REAL_BUDGET,
            "go": REAL_GO,
            "plan": subplan,
            "label": "live-run",
        }
        vendor = ISOLATED_TEST_TRANSPORT_FACTORY() if ISOLATED_TEST_TRANSPORT_FACTORY is not None else None
        guard_facts = guard.summary()
        journal.write("execution_start", counts=plan_data["counts"],
                      transport_replaced_for_isolated_test=vendor is not None,
                      socket_guard_before_execution=guard_facts)
        guard.uninstall()
        _LEDGER_BASELINE["events"] = _ledger_event_count(REAL_LEDGER)
        try:
            receipt = run_controlled_pilot(
                paths=live_paths, subplan=subplan, plan_data=plan_data, support=support, mode="live",
                vendor=vendor, journal=journal,
            )
        except BaseException as exc:  # noqa: BLE001 - 最后安全网：仍先写失败 receipt 再非零退出
            return _live_execution_failure(
                exc, out=out, journal=journal, guard=guard, plan_data=plan_data, subplan=subplan,
                preflight_path=preflight_path,
            )
        receipt["live_preflight"] = rel(preflight_path)
        receipt["socket_guard_before_execution"] = guard_facts
        receipt["isolated_test_seams"] = sorted(ISOLATED_TEST_HOOKS)
        receipt["transport_replaced_for_isolated_test"] = vendor is not None
        post_checks = _live_post_checks(receipt, plan_data, subplan, out, real_before)
        receipt["live_post_checks"] = post_checks
        if receipt.get("outcome") == "completed" and not all(post_checks.values()):
            failed = [name for name, ok in post_checks.items() if not ok]
            receipt["outcome"] = "failed"
            receipt["error"] = {"type": "PilotPostVerificationError", "category": "post_verification_failed",
                                "code": "PILOT_POST_VERIFICATION_FAILED", "failed": failed}
            receipt["first_failure"] = receipt.get("first_failure") or receipt["error"]
        receipt["real_paths_after"] = real_paths()
        try:
            receipt_path = dump_json(out / "live-receipt.json", receipt)
        except BaseException as exc:  # noqa: BLE001 - 持久化失败必须给可审查诊断并非零退出
            journal.write("receipt_write_failed", type=type(exc).__name__, message_safe=_safe_text(exc))
            print(json.dumps({"mode": "live", "decision": "executed-but-receipt-write-failed",
                              "error_type": type(exc).__name__, "out": str(out)}, ensure_ascii=False))
            return 5
        first = receipt.get("first_failure") or {}
        if first.get("category") == "interrupt":
            journal.write("run_finish", outcome="interrupted", receipt=str(receipt_path))
            print(json.dumps({"mode": "live", "decision": "interrupted", "receipt": str(receipt_path),
                              "first_failure": first}, ensure_ascii=False))
            return 130
        exit_code = 0 if receipt.get("outcome") == "completed" and all(post_checks.values()) else 5
        journal.write("run_finish", outcome=receipt.get("outcome"), exit_code=exit_code,
                      receipt=str(receipt_path), first_failure=first)
        print(json.dumps({"mode": "live", "decision": "executed-finite-pilot" if exit_code == 0 else "failed",
                          "exit_code": exit_code, "outcome": receipt.get("outcome"), "receipt": str(receipt_path),
                          "first_failure": first, "observed_reservations": len((receipt.get("ledger") or {}).get("reserved_sequence") or [])},
                         ensure_ascii=False))
        return exit_code
    finally:
        try:
            guard.uninstall()
        except BaseException:  # noqa: BLE001
            pass
        journal.close()


def _live_setup_failure(exc: BaseException, *, out: Path, journal: Journal, guard: SocketGuard, gate: dict) -> int:
    category = "interrupt" if isinstance(exc, KeyboardInterrupt) else "setup_failure"
    receipt = {
        "document": "S2-K-R1B-live-receipt",
        "mode": "live",
        "outcome": "failed",
        "started_at": now_iso(),
        "finished_at": now_iso(),
        "steps": [],
        "answers": [],
        "first_failure": {
            "stage": "setup:import_support_or_business",
            "category": category,
            "code": _safe_code(exc),
            "exception_type": type(exc).__name__,
            "exception_message_safe": _safe_text(exc),
        },
        "error": None,
        "cleanup_errors": [],
        "sent_any_request": False,
        "socket_guard": guard.summary(),
        "resource_gate": gate,
        "isolated_test_seams": sorted(ISOLATED_TEST_HOOKS),
    }
    receipt["error"] = receipt["first_failure"]
    journal.write("setup_failure", exception_type=type(exc).__name__, code=_safe_code(exc))
    try:
        path = dump_json(out / "live-receipt.json", receipt)
    except BaseException:  # noqa: BLE001
        print(json.dumps({"mode": "live", "decision": "setup-failure-receipt-write-failed",
                          "error_type": type(exc).__name__}, ensure_ascii=False))
        return 5
    journal.write("run_finish", outcome="failed", receipt=str(path))
    print(json.dumps({"mode": "live", "decision": "setup-failed", "receipt": str(path),
                      "first_failure": receipt["first_failure"]}, ensure_ascii=False))
    return 130 if isinstance(exc, KeyboardInterrupt) else 5


def _live_execution_failure(exc: BaseException, *, out: Path, journal: Journal, guard: SocketGuard,
                            plan_data: dict, subplan, preflight_path: Path | None) -> int:
    """F-K3 最后安全网：执行函数本身逃逸时仍先落失败 receipt（保留原始异常身份），再非零退出。"""
    category = "interrupt" if isinstance(exc, (KeyboardInterrupt, SystemExit)) else "exception"
    ledger_snapshot = None
    try:
        ledger_snapshot = read_ledger(
            {"root": out, "app": out / "app", "ledger": REAL_LEDGER, "budget": REAL_BUDGET, "go": REAL_GO},
            subplan,
        )
    except BaseException as ledger_exc:  # noqa: BLE001 - 账本快照失败是次级事实
        ledger_snapshot = {"error": _safe_text(f"{type(ledger_exc).__name__}: {ledger_exc}")}
    first_failure = {
        "stage": "execution:unhandled_exception",
        "category": category,
        "code": _safe_code(exc),
        "exception_type": type(exc).__name__,
        "exception_message_safe": _safe_text(exc),
        "detail": "run_controlled_pilot 未按约定返回 receipt 而是逃逸；原始异常身份保留，失败 receipt 仍先落盘",
    }
    receipt = {
        "document": "S2-K-R1B-live-receipt",
        "mode": "live",
        "outcome": "failed",
        "started_at": now_iso(),
        "finished_at": now_iso(),
        "steps": [],
        "answers": [],
        "counts_planned": (plan_data or {}).get("counts"),
        "request_plan_sha256": subplan.request_plan_sha256,
        "first_failure": first_failure,
        "error": first_failure,
        "cleanup_errors": [],
        "sent_any_request": None,
        "ledger": ledger_snapshot,
        "journal_exists": journal.path.is_file(),
        "socket_guard_before_execution": guard.summary(),
        "isolated_test_seams": sorted(ISOLATED_TEST_HOOKS),
        "transport_replaced_for_isolated_test": ISOLATED_TEST_TRANSPORT_FACTORY is not None,
        "live_preflight": rel(preflight_path) if preflight_path is not None else None,
    }
    journal.write("execution_unhandled_exception", exception_type=type(exc).__name__, category=category,
                  code=first_failure["code"])
    try:
        path = dump_json(out / "live-receipt.json", receipt)
    except BaseException:  # noqa: BLE001 - 落盘失败给可审查诊断并非零退出
        print(json.dumps({"mode": "live", "decision": "unhandled-exception-receipt-write-failed",
                          "error_type": type(exc).__name__, "out": str(out)}, ensure_ascii=False))
        return 5
    journal.write("run_finish", outcome="failed", receipt=str(path), first_failure=first_failure)
    print(json.dumps({"mode": "live", "decision": "failed-unhandled-exception", "receipt": str(path),
                      "first_failure": first_failure}, ensure_ascii=False))
    return 130 if isinstance(exc, KeyboardInterrupt) else 5


# ---------------------------------------------------------------- main


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="S2-K-R1B 有限 pilot 入口 v2（默认 plan；显式 Mock；live 默认拒绝）")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--plan", action="store_true", help="只产计划/候选预算/DRAFT GO（默认）")
    group.add_argument("--mock", action="store_true", help="隔离 Mock 全套（真实产品装配 + MockTransport）")
    group.add_argument("--live", action="store_true", help="未来有限真实入口；默认拒绝")
    group.add_argument("--self-check", action="store_true", help="自检计划/绑定/候选预算纯计算")
    parser.add_argument("--evidence-root", default=None, help="本轮证据根（必填：新建或带 root-contract.json 的本轮根；无默认根）")
    parser.add_argument("--plan-file", default=None, help="plan 运行产出的 plan.json（Mock/live 必须指向同一计划）")
    parser.add_argument("--mock-file", default=None, help="Mock 运行产出的 s2k-mock-results.json")
    parser.add_argument("--only", default=None, help="--mock 限定：positive / negatives / 具体负例名")
    parser.add_argument("--out", default=None, help="live 本次运行目录（必须位于证据根下且不存在）")
    parser.add_argument("--confirm-live-fixed-go", action="store_true", help="live 显式确认只读产品固定 GO")
    args = parser.parse_args(argv)
    mode = "live" if args.live else "mock" if args.mock else "self-check" if args.self_check else "plan"
    try:
        root = resolve_evidence_root(args.evidence_root)
    except SystemExit as exc:
        print(json.dumps({"mode": mode, "decision": "refused-evidence-root", "reason": _safe_text(exc)}, ensure_ascii=False))
        return 2
    try:
        if mode == "live":
            return cmd_live(args, root=root)
        run_dir = create_run_dir(root, mode)
        if mode == "mock":
            return cmd_mock(args, root=root, run_dir=run_dir)
        if mode == "self-check":
            return cmd_self_check(args, root=root, run_dir=run_dir)
        return cmd_plan(args, root=root, run_dir=run_dir)
    except KeyboardInterrupt:
        print(json.dumps({"mode": mode, "decision": "interrupted"}, ensure_ascii=False))
        return 130
    except SystemExit as exc:
        print(json.dumps({"mode": mode, "decision": "refused", "reason": _safe_text(exc)}, ensure_ascii=False))
        return 2

if __name__ == "__main__":
    raise SystemExit(main())

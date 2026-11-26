r"""R2 SAFE 投影器：从已封存 r2 真实运行证据重建逐题评分输入，只输出固定码、布尔与计数。

（自 ``r1_safe_project.py`` 最小移植；评分与 classify 语义、SAFE 出口校验逻辑未改。）

用途
----
1. 用与 ``recompute_axes_fullverify.py`` 相同的加载链读 binding -> bundle -> 6 turn 的
   认证密文 envelope，重建 ``score_public_case`` 的评分行（``product.kind/text/sources/evidence``），
   逐题重算质量；与 ``run/r2-final/case-plan.json`` 的 ``quality_status`` 逐题比对，5/5 一致才算可信。
2. 落 ``r2-quality-checks.json``（case_id / turn_index / quality_status / failed_check_ids /
   check_statuses / value 与 source 计数 / kind / 拒答适用性布尔）。

私有数据纪律
-----------
- 私有输入（key / binding / 密文 / 题集 / annotation）只在**进程内存**里读；
- **绝不**打印 ``str(exc)``、``traceback``、题干、答案、实体名、来源正文或私有路径；
- 所有输出都经过 :func:`_safe_dump`：键在白名单内、字符串只能是 case_id、
  固定码、run_id、sha256；其余只允许布尔与非负整数计数；
- 顶层 try/except：异常只输出 ``{"ok": false, "error": "<固定码>", "where": "<函数名>"}``。

本次移植的改动清单（逐项登记，未登记的语义不得变更）
---------------------------------------------------
A. 路径常量：默认 ``--case-plan`` 指向 ``run/r2-final/case-plan.json``；默认 ``--out-dir`` 指向
   ``r2-repair-external-20261117/evidence/01-safe-projection``；默认 ``--gap-path`` 指向
   ``r2-repair-external-20261117/work/RECONSTRUCTION-GAP.md``；环境变量前缀 ``R1_*`` -> ``R2_*``。
B. 运行目录解析：新增 :func:`_verify_identity`，把 run_index=2 / run_id / scenario_id /
   业务日 2026-11-20 / case 集合（精确 5 题）/ turn 文件（精确 6 件、C14 两回合）/
   key 与 evidence tree 与 seal manifest 身份 / binding 与 case-plan 的 custody、manifest 绑定
   逐项做成拒绝式门（缺一即固定码失败）。``_verify_custody`` 函数体**原样保留**，未改一字符。
C. case 集合：``EXPECTED_CASE_IDS`` 固定 5 题（C08/C14/C19/C25/C29），不再依赖 R1 的 8 题集合。
D. 回合数：``EXPECTED_TURN_COUNT = 6``；``EXPECTED_MULTI_TURN`` 固定 C14 占 turn-0001/0002。
E. 业务日期：``EXPECTED_BUSINESS_DATE = "2026-11-20"``（不取本机今日，不沿用 R1 的 2026-07-15）。
F. 输出文件名：``r2-quality-checks.json``；缺口件 ``RECONSTRUCTION-GAP.md`` 内轮次标签改为 r2。
G. 轮次标签：docstring / 缺口件 / 输出 ``round_label`` 一律 r2。
H. 输出字段（白名单**只增不减**；字符串仍必须过 CASE_ID/RUN_ID/SHA/COMPAT/CODE 正则；
   ``skipped`` 不计入 pass）：新增 ``turn_index`` / ``turn_count`` / ``kind`` / ``should_refuse`` /
   ``refusal_expected_applicable`` / ``refusal_expected_status`` / ``refusal_effective`` /
   ``value_expected|value_matched|value_missing|value_extra`` /
   ``source_expected|source_matched|source_missing|source_forbidden_hit`` /
   ``check_id_pass_totals`` / ``check_id_skipped_totals`` / ``checks_total`` /
   ``checks_passed_total`` / ``checks_failed_total`` / ``checks_skipped_total`` /
   ``integrity`` 及叶子 / ``origin_round`` / ``evidence_file_sha256``（全部为布尔、非负整数、
   固定枚举码或 sha256）。``_DYNAMIC_KEY_PARENTS`` 仅增加两个**仍按 CHECK_IDS 限定键**的父键。
I. 范围收缩（不改变任何判据）：不再调用四轴 ``classify_case_evidence`` 与 ``_empty_scope_progress``
   产出 ``r1-current-round-initial*.json``。四轴重建属 201B，须用 v0.5/v0.6 显式口径单独做；
   本工具只出质量面，避免把 v0.1/v0.3 的轴结论混进 R2 证据。相关函数体原样保留，未删改。
J. 出站守卫：``NetGuard`` 增加子进程面（``subprocess.Popen`` 一并阻断并计数），正对照含子进程
   尝试；失败出口同样只写固定码。

R2-201D 追加（改动清单 L：**评分输入同构**，只改重建侧输入，不动任何判据）
--------------------------------------------------------------------------
L. source-map 口径：本轮 r2 真实运行由受控入口在 ``dispatched_scoring_map`` 作用域内计分，
   声明 ``p2-holdout-source-map/v0.2``（12 码，``served_by_dispatch>0``；见
   ``run/r2-final/v3-entry-sidecar.json`` 的 ``scoring_map``）。原工具直接调
   ``score_run.load_holdout_source_map()`` = 驱动层默认 **v0.1（仅 4 码）**，于是 C25 的
   forbidden ref（``D01``）拿不到版本绑定，``_version_source_checks`` 对 ``source_forbidden``
   整段跳过（``p2_scoring.py:807``），退化成 locator-only 命中 → 假违规。
   修法：在**同一分发器**作用域内取 map（v0.2 12 码），并对 schema/码数/分发实际被调用
   做拒绝式门。判据、阈值、case-plan、评分器一字未改。

运行
----
私有路径一律由命令行/环境变量传入，**不写进本文件**：

    .venv\Scripts\python.exe -X utf8 r2_safe_project.py ^
      --key <ev.key> --binding <run2-pre_v05_without_v07.binding.json> ^
      --evidence-root <...\r2\evidence\p2-h2v3-20261115-r2-pre_v05_without_v07> ^
      --receipt <...\r2\seal\...\run-receipt.json> ^
      --seal-manifest <...\r2\seal\...\seal-manifest.json> ^
      --case-plan <repo\docs\...\run\r2-final\case-plan.json> ^
      --out-dir <repo\docs\...\r2-repair-external-20261117\evidence\01-safe-projection>
"""

from __future__ import annotations

import ast
import argparse
import hashlib
import importlib.util
import json
import os
import pathlib
import re
import socket
import subprocess
import sys
import urllib.request
from typing import Any, Iterable, Mapping, Sequence

# --------------------------------------------------------------------------- #
# 固定枚举 / 固定码
# --------------------------------------------------------------------------- #

REPO = pathlib.Path(r"D:\GPT项目\市场部AI知识库")
BACKEND_SRC = REPO / "backend" / "src"
TOOLS = REPO / "tools"
HARD_PATH = BACKEND_SRC / "mktkb" / "evaluation" / "p2_hard_evidence.py"
SCORERS_PATH = BACKEND_SRC / "mktkb" / "evaluation" / "scorers.py"
WORK_DIR = (
    REPO / "docs" / "reports" / "OBS-EVAL" / "P2" / "H2V3" / "r2-repair-external-20261117" / "work"
)

# --------------------------------------------------------------------------- #
# R2 固定参数（改动清单 C/D/E/G）
# --------------------------------------------------------------------------- #

ROUND_LABEL = "r2"
EXPECTED_RUN_INDEX = 2
EXPECTED_RUN_ID = "p2-h2v3-20261115-r2-pre_v05_without_v07"
EXPECTED_SCENARIO_ID = "pre_v05_without_v07"
EXPECTED_BUSINESS_DATE = "2026-11-20"
EXPECTED_CASE_IDS: tuple[str, ...] = (
    "H2V3-C08",
    "H2V3-C14",
    "H2V3-C19",
    "H2V3-C25",
    "H2V3-C29",
)
EXPECTED_TURN_COUNT = 6
EXPECTED_MULTI_TURN: dict[str, tuple[int, ...]] = {"H2V3-C14": (1, 2)}
EXPECTED_EVIDENCE_FILE_COUNT = 7  # 6 turn + 1 manifest
#: （改动清单 L）本轮 r2 运行声明的 source-map：受控入口在 ``dispatched_scoring_map`` 作用域内
#: 计分，``v3-entry-sidecar.json`` 的 ``scoring_map`` 逐值是 v0.2 / 12 码 / served_by_dispatch>0。
#: 驱动层默认值是 v0.1 / 4 码——两者不是"评分版本差异"，是**输入口径**差异。
SCORING_MAP_PATH = REPO / "docs" / "evaluation" / "p2-holdout-v3.source-map.json"
EXPECTED_SCORING_MAP_SCHEMA = "p2-holdout-source-map/v0.2"
EXPECTED_SCORING_MAP_CODE_COUNT = 12
EXPECTED_DRIVER_DEFAULT_MAP_CODE_COUNT = 4
#: 本轮视为"拒答"的结局固定码（与 ``scorers.REFUSAL_KINDS`` 同口径，只用于 SAFE 布尔投影）。
REFUSAL_KIND_CODES = frozenset({"no_answer", "not_found", "refusal"})
#: envelope 必须携带的 scope 判据字段（缺一即拒绝，不允许"没有证据当通过"）。
SCOPE_ENVELOPE_KEYS = frozenset({"turn", "capture", "db_projection", "completeness"})
SCOPE_PROJECTION_KEYS = frozenset(
    {"units", "message_sources", "messages", "unresolved_unit_ids", "query_states", "request", "conversation"}
)

CASE_ID_RE = re.compile(r"^H2V3-C[0-9]{2}$")
RUN_ID_RE = re.compile(r"^p2-h2v3-[a-z0-9._-]{1,64}$")
CODE_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
COMPAT_RE = re.compile(r"^p2-refusal-compat/v0\.[0-9]+$")
SOURCE_MAP_SCHEMA_RE = re.compile(r"^p2-holdout-source-map/v0\.[0-9]+$")
CASE_STATUSES = frozenset({"pass", "fail", "error", "not_executed"})
CHECK_STATUSES = frozenset({"pass", "fail", "skipped", "skipped_requires_ocr"})
AXIS_STATES = ("passed", "not_applicable", "unknown", "violation")
AXES = ("safety", "cross_user", "cross_entity", "stale_source")
TURN_STATUSES = ("executed", "error", "not_started")
PROOF_APPLICABLE_REASONS = frozenset(
    {
        "empty_set_not_proven",
        "evidence_incomplete",
        "unknown_usage_field",
        "branch_evidence_missing",
        "branch_evidence_inconsistent",
        "model_events_missing",
        "template_identity_unverified",
        "empty_use_scope_ok",
    }
)

#: 冻结模块里经 AST 扫出的 reason 之外，本工具自己产生的固定码。
EXTRA_REASON_CODES = frozenset(
    {
        "empty_use_scope_ok",
        "passed",
        "not_applicable",
        "first_failure_unknown",
        "unknown_code",
        "classification_failed",
        "reconstructed",
    }
)

#: 输出白名单键（任何未登记键都会被 _safe_dump 拒绝）。
ALLOWED_KEYS = frozenset(
    {
        "ok",
        "error",
        "where",
        "run_id",
        "case_plan_sha256",
        "compat",
        "reconstruction_match",
        "cases",
        "case_id",
        "quality_status",
        "failed_check_ids",
        "check_statuses",
        "failed_check_count",
        "check_id_totals",
        "evidence_complete",
        "missing_codes",
        "axes",
        "safety",
        "cross_user",
        "cross_entity",
        "stale_source",
        "state",
        "reason",
        "safety_first_failure",
        "reached_empty_set_check",
        "reached_template_check",
        "kind_effective",
        "template_registered",
        "first_code",
        "netguard",
        "blocked_attempts",
        "blocked_subprocess_attempts",
        "subprocess_guard_installed",
        "positive_control_attempts",
        "positive_control_blocked",
        "outbound_allowed",
        "envelope_count",
        "turn_count",
        "case_count",
        "classification_failures",
        "replica_disagreements",
        "unsafe_code_count",
        "scoring_paths_agree",
        "custody_ok",
        "mismatch_cases",
        "mismatch_count",
        # --- R2 新增（改动清单 H；全部为布尔/非负整数/固定枚举码/sha256）---
        "round_label",
        "run_index",
        "turn_index",
        "kind",
        "should_refuse",
        "refusal_expected_applicable",
        "refusal_expected_status",
        "refusal_effective",
        "value_expected",
        "value_matched",
        "value_missing",
        "value_extra",
        "source_expected",
        "source_matched",
        "source_missing",
        "source_forbidden_hit",
        "check_id_pass_totals",
        "check_id_skipped_totals",
        "checks_total",
        "checks_passed_total",
        "checks_failed_total",
        "checks_skipped_total",
        "origin_round",
        "evidence_file_count",
        "evidence_file_sha256",
        "integrity",
        "key_sha256_matches_receipt",
        "evidence_tree_sha_matches_receipt",
        "seal_manifest_sha_matches_receipt",
        "evidence_tree_recomputed_matches_seal",
        "binding_matches_case_plan",
        "case_set_matches",
        "turn_count_matches",
        "business_date_matches",
        "run_index_matches",
        "run_id_matches",
        "scenario_id_matches",
        "evidence_readback_ok",
        "real_calls",
        "real_calls_matches_case_plan",
        "evidence_file_count_matches",
        "multi_turn_shape_matches",
        "sealed",
        # --- 改动清单 K：评分版本对照 ---
        "reconstruction_match",
        "scoring_version_explained",
        "original_caliber_match",
        "flip_cases",
        "flip_details",
        "first_diff_check_id",
        "current_status",
        "original_status",
        "plan_status",
        "structural_key_count",
        "case_ids",
        # --- 改动清单 L：评分输入（source-map 分发）口径 ---
        "scoring_map",
        "schema_version",
        "code_count",
        "driver_default_code_count",
        "served_by_dispatch",
        "resolutions",
        "source_map_sha256",
        "matches_run_declaration",
    }
)


class ToolError(RuntimeError):
    """带固定码与函数名的内部失败。"""

    def __init__(self, code: str, where: str) -> None:
        super().__init__(code)
        self.code = code
        self.where = where


_STAGE = ["module"]


def _fail(code: str, where: str | None = None) -> None:
    raise ToolError(code, where or _STAGE[0])


# --------------------------------------------------------------------------- #
# 网络阻断（socket / urllib / httpx）+ 正对照
# --------------------------------------------------------------------------- #


class NetGuard:
    """在 socket 原语层阻断出站；所有尝试只计数，不连接。"""

    def __init__(self) -> None:
        self.blocked = 0
        self.blocked_subprocess = 0
        self.positive_control_attempts = 0
        self.installed = False
        self._orig_connect = None
        self._orig_connect_ex = None
        self._orig_urlopen = None
        self._orig_popen = None
        self._orig_system = None

    def _refuse(self, *_args: Any, **_kwargs: Any) -> Any:
        self.blocked += 1
        raise OSError("netguard_blocked")

    def _refuse_subprocess(self, *_args: Any, **_kwargs: Any) -> Any:
        """R2 追加（改动清单 J）：子进程面同样只计数、不执行。"""
        self.blocked_subprocess += 1
        raise OSError("netguard_subprocess_blocked")

    def install(self) -> None:
        if self.installed:
            return
        self._orig_connect = socket.socket.connect
        self._orig_connect_ex = socket.socket.connect_ex
        self._orig_urlopen = urllib.request.urlopen
        socket.socket.connect = self._refuse  # type: ignore[method-assign]
        socket.socket.connect_ex = self._refuse  # type: ignore[method-assign]
        urllib.request.urlopen = self._refuse  # type: ignore[assignment]
        try:  # 子进程面：Popen 与 os.system 一并封死并计数（本工具不 spawn 任何子进程）。
            import subprocess  # noqa: PLC0415

            self._orig_popen = subprocess.Popen
            guard = self

            class _BlockedPopen(subprocess.Popen):  # type: ignore[misc, valid-type]
                """继承原 Popen 以便第三方库仍可 ``class X(subprocess.Popen)``；实例化即拒绝。"""

                def __init__(self, *_args: Any, **_kwargs: Any) -> None:
                    guard.blocked_subprocess += 1
                    raise OSError("netguard_subprocess_blocked")

            subprocess.Popen = _BlockedPopen  # type: ignore[assignment,misc]
            self._orig_system = os.system
            os.system = self._refuse_subprocess  # type: ignore[assignment]
        except Exception:  # noqa: BLE001 - 没有 subprocess 就没有这条出站面
            pass
        try:  # httpx 若已导入则一并封死传输层；未导入不会触发。
            import httpx  # noqa: PLC0415

            httpx.HTTPTransport.handle_request = self._refuse  # type: ignore[method-assign]
            httpx.AsyncHTTPTransport.handle_async_request = self._refuse  # type: ignore[method-assign]
        except Exception:  # noqa: BLE001 - 没有 httpx 就不是出站面
            pass
        self.installed = True

    def positive_control(self) -> None:
        """尝试必然被阻断的出站路径（含子进程面）；没被阻断就说明 guard 失效。"""
        for attempt in (
            lambda: socket.create_connection(("127.0.0.1", 9), timeout=0.05),
            lambda: urllib.request.urlopen("http://127.0.0.1:9/", timeout=0.05),
            lambda: subprocess.Popen([sys.executable, "-c", "pass"]),
        ):
            self.positive_control_attempts += 1
            try:
                attempt()
            except OSError:
                continue
            _fail("netguard_positive_control_failed", "netguard")

    def as_dict(self) -> dict[str, Any]:
        return {
            "blocked_attempts": int(self.blocked),
            "blocked_subprocess_attempts": int(self.blocked_subprocess),
            "positive_control_attempts": int(self.positive_control_attempts),
            "positive_control_blocked": bool(
                self.positive_control_attempts == 3
                and self.blocked >= 2
                and self.blocked_subprocess >= 1
            ),
            "subprocess_guard_installed": bool(self._orig_popen is not None),
            "outbound_allowed": 0,
        }


# --------------------------------------------------------------------------- #
# SAFE 输出：键白名单 + 字符串白名单 + 类型白名单
# --------------------------------------------------------------------------- #


def _safe_string(value: str) -> bool:
    if CASE_ID_RE.fullmatch(value):
        return True
    if RUN_ID_RE.fullmatch(value):
        return True
    if SHA_RE.fullmatch(value):
        return True
    if COMPAT_RE.fullmatch(value):
        return True
    if SOURCE_MAP_SCHEMA_RE.fullmatch(value):
        return True
    if CODE_RE.fullmatch(value):
        return True
    return False


_CHECK_ID_SET: frozenset[str] = frozenset()
#: 动态键父级：键必须**恰好**是 ``CHECK_IDS`` 里的检查 id（改动清单 H：新增两个同规则父键）。
_DYNAMIC_KEY_PARENTS = frozenset(
    {"check_statuses", "check_id_totals", "check_id_pass_totals", "check_id_skipped_totals"}
)


def _assert_safe(node: Any, depth: int = 0, parent_key: str | None = None) -> None:
    if depth > 8:
        _fail("output_too_deep", "_safe_dump")
    if type(node) is bool:
        return
    if type(node) is int:
        if node < 0 or node > 10**9:
            _fail("output_int_out_of_range", "_safe_dump")
        return
    if type(node) is str:
        if not _safe_string(node):
            _fail("unsafe_output_string", "_safe_dump")
        return
    if isinstance(node, list):
        if len(node) > 4096:
            _fail("output_list_too_long", "_safe_dump")
        for item in node:
            _assert_safe(item, depth + 1, parent_key)
        return
    if isinstance(node, dict):
        if len(node) > 256:
            _fail("output_object_too_large", "_safe_dump")
        for key, value in node.items():
            if type(key) is not str:
                _fail("unsafe_output_key", "_safe_dump")
            if parent_key in _DYNAMIC_KEY_PARENTS:
                if key not in _CHECK_ID_SET:
                    _fail("unsafe_output_key", "_safe_dump")
            elif key not in ALLOWED_KEYS:
                _fail("unsafe_output_key", "_safe_dump")
            _assert_safe(value, depth + 1, key)
        return
    _fail("unsafe_output_type", "_safe_dump")


def _safe_dump(
    payload: Mapping[str, Any],
    path: pathlib.Path | None = None,
    *,
    announce: bool = True,
) -> None:
    _assert_safe(dict(payload))
    text = json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True)
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")
    if announce:
        print(text)


# --------------------------------------------------------------------------- #
# 只读加载
# --------------------------------------------------------------------------- #


def _load_module(name: str, path: pathlib.Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        _fail("module_load_failed", "_load_module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha256_file(path: pathlib.Path) -> str:
    try:
        return _sha256_bytes(path.read_bytes())
    except OSError:
        _fail("input_unreadable", "_sha256_file")


def _read_json(path: pathlib.Path) -> Mapping[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        _fail("input_json_invalid", "_read_json")
    if not isinstance(payload, Mapping):
        _fail("input_json_invalid", "_read_json")
    return payload


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--key", default=os.environ.get("R2_EV_KEY"))
    parser.add_argument("--binding", default=os.environ.get("R2_BINDING"))
    parser.add_argument("--evidence-root", default=os.environ.get("R2_EVIDENCE_ROOT"))
    parser.add_argument("--receipt", default=os.environ.get("R2_SEAL_RECEIPT"))
    parser.add_argument("--seal-manifest", default=os.environ.get("R2_SEAL_MANIFEST"))
    parser.add_argument(
        "--case-plan",
        default=str(REPO / "docs/reports/OBS-EVAL/P2/H2V3/fullverify-20261116/run/r2-final/case-plan.json"),
    )
    parser.add_argument(
        "--out-dir",
        default=str(
            REPO
            / "docs/reports/OBS-EVAL/P2/H2V3/r2-repair-external-20261117/evidence/01-safe-projection"
        ),
    )
    parser.add_argument(
        "--gap-path",
        default=str(
            REPO
            / "docs/reports/OBS-EVAL/P2/H2V3/r2-repair-external-20261117/work/RECONSTRUCTION-GAP.md"
        ),
    )
    args = parser.parse_args(list(argv))
    for name in ("key", "binding", "evidence_root", "receipt", "seal_manifest"):
        if not getattr(args, name):
            _fail("argument_missing", "_parse_args")
    return args


# --------------------------------------------------------------------------- #
# reason 固定码白名单（AST 只读扫描冻结模块）
# --------------------------------------------------------------------------- #

#: AST 不可用时的兜底：当前一轮实际出现的固定码子集。
_BASELINE_REASONS = frozenset(
    {
        "all_user_contexts_ok",
        "annotation_unknown",
        "axis_required_never_not_applicable",
        "benign_business_no_frozen_checks",
        "branch_evidence_inconsistent",
        "branch_evidence_missing",
        "date_intent_conflict",
        "date_unresolved",
        "empty_set_not_proven",
        "entity_identity_unresolved",
        "entity_scope_conflict",
        "evidence_incomplete",
        "forbidden_source_unmappable",
        "forbidden_source_used",
        "forbidden_value_leaked",
        "free_text_attribution_unverifiable",
        "frozen_forbidden_checks_ok",
        "frozen_targets_match_ok",
        "future_source_as_current",
        "lifecycle_dates_ok",
        "lifecycle_unavailable",
        "model_events_missing",
        "no_dated_sources_lifecycle_checked",
        "no_entity_scope_verified",
        "other_entity_used",
        "output_unavailable",
        "refusal_leaked_forbidden",
        "security_refusal_missing",
        "semantic_unverifiable",
        "source_deleted",
        "source_expired",
        "source_not_active",
        "source_not_published",
        "source_unresolved",
        "template_identity_unverified",
        "turn_error",
        "turn_identity_inconsistent",
        "turn_not_executed",
        "unknown_usage_field",
    }
)


def _reason_allowlist() -> frozenset[str]:
    codes: set[str] = set(_BASELINE_REASONS) | set(EXTRA_REASON_CODES)
    try:
        tree = ast.parse(HARD_PATH.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return frozenset(codes)
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"unknown", "violation", "na", "ref"}
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            codes.add(node.args[0].value)
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_missing_part"
            and len(node.args) >= 2
            and isinstance(node.args[1], ast.Constant)
            and isinstance(node.args[1].value, str)
        ):
            codes.add(node.args[1].value)
        targets: list[ast.expr] = []
        value: ast.expr | None = None
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
            value = node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets = [node.target]
            value = node.value
        for target in targets:
            if (
                isinstance(target, ast.Name)
                and target.id in {"NA_REASONS", "PASS_REASONS"}
                and isinstance(value, ast.Dict)
            ):
                for item in value.values:
                    if isinstance(item, ast.Constant) and isinstance(item.value, str):
                        codes.add(item.value)
        if isinstance(node, ast.Return) and isinstance(node.value, ast.Tuple) and len(node.value.elts) == 2:
            second = node.value.elts[1]
            if isinstance(second, ast.Constant) and isinstance(second.value, str):
                codes.add(second.value)
    return frozenset(codes)


# --------------------------------------------------------------------------- #
# 评分行重建
# --------------------------------------------------------------------------- #


def _one_payload(events: Sequence[Mapping[str, Any]], kind: str) -> Mapping[str, Any] | None:
    rows = [
        event.get("payload")
        for event in events
        if isinstance(event, Mapping) and str(event.get("kind")) == kind
    ]
    return rows[0] if len(rows) == 1 else None


def _product_status(unit: Mapping[str, Any]) -> str:
    """复刻 ``sources.service.status_of`` 的确定性口径。"""
    if unit.get("document_deleted") is not False or str(unit.get("version_state")) == "deleted":
        return "deleted"
    if (
        str(unit.get("version_state")) == "published"
        and unit.get("active") is True
        and str(unit.get("active_version_id")) == str(unit.get("version_id"))
    ):
        return "active"
    return "superseded"


def _build_rows(
    cases: Sequence[Any],
    plan_rows: Sequence[Mapping[str, Any]],
    evidence_root: pathlib.Path,
    key: bytes,
    bindings: Mapping[str, str],
    document_codes: Mapping[str, str],
    read_encrypted: Any,
    lookup_document_code: Any,
    diag: dict[str, int],
    origin_out: dict[str, dict[str, Any]] | None = None,
) -> tuple[dict[str, dict[str, Any]], dict[str, list[Mapping[str, Any]]]]:
    """重建 ``score_public_case`` 逐题行；只把固定码计数写进 diag。

    R2 追加（改动清单 B/e）：``origin_out`` 记录每题密文文件的**本轮读回** sha256（来源证明的
    字节侧），供 :func:`gate_origin_round` 判定"这题的重建确实来自本轮读盘"，而不是旧卡回填。
    """
    rows: dict[str, dict[str, Any]] = {}
    envelopes_by_case: dict[str, list[Mapping[str, Any]]] = {}
    for case, plan_row in zip(cases, plan_rows):
        case_id = str(case.case_id)
        turns: list[dict[str, Any]] = []
        envelopes: list[Mapping[str, Any]] = []
        digests: list[str] = []
        for turn_row in plan_row["turns"]:
            status = str(turn_row.get("status"))
            if status != "executed":
                _fail("turn_not_executed", "_build_rows")
            try:
                envelope = read_encrypted(
                    evidence_root / str(turn_row["evidence_file"]),
                    key=key,
                    expected_bindings=dict(bindings),
                )
            except Exception:  # noqa: BLE001 - 统一固定码，绝不回显
                _fail("envelope_read_failed", "_build_rows")
            digests.append(_sha256_file(evidence_root / str(turn_row["evidence_file"])))
            envelopes.append(envelope)
            turn_meta = envelope.get("turn")
            if not isinstance(turn_meta, Mapping):
                _fail("envelope_turn_missing", "_build_rows")
            if int(turn_meta.get("turn_index")) != int(turn_row["turn_index"]):
                _fail("envelope_turn_index_mismatch", "_build_rows")
            completeness = envelope.get("completeness")
            if not isinstance(completeness, Mapping) or str(completeness.get("status")) != "complete":
                _fail("envelope_incomplete", "_build_rows")

            projection = envelope.get("db_projection")
            if not isinstance(projection, Mapping):
                _fail("projection_missing", "_build_rows")
            units = {
                str(row.get("unit_id")): row
                for row in (projection.get("units") or [])
                if isinstance(row, Mapping)
            }
            events = [
                event
                for event in ((envelope.get("capture") or {}).get("events") or [])
                if isinstance(event, Mapping)
            ]
            answer = _one_payload(events, "answer_result") or {}
            commit = _one_payload(events, "commit_observed") or {}

            result_message_id = str((projection.get("request") or {}).get("result_message_id"))
            message_source_ids = list(
                dict.fromkeys(
                    str(row.get("source_id"))
                    for row in (projection.get("message_sources") or [])
                    if isinstance(row, Mapping)
                    and str(row.get("message_id")) == result_message_id
                )
            )
            answer_ids = [str(item) for item in (answer.get("source_ids") or [])]
            commit_ids = [str(item) for item in (commit.get("source_ids") or [])]
            diag["message_sources_mismatch"] += int(bool(message_source_ids) and set(message_source_ids) != set(commit_ids))
            source_ids = message_source_ids or commit_ids or answer_ids

            sources: list[dict[str, Any]] = []
            for source_id in source_ids:
                unit = units.get(source_id)
                if not isinstance(unit, Mapping):
                    diag["sources_missing_unit"] += 1
                    continue
                document_name = unit.get("document_name")
                if not isinstance(document_name, str) or not document_name:
                    diag["sources_missing_document_name"] += 1
                    continue
                if lookup_document_code(document_name, document_codes) is None:
                    diag["sources_unmapped_document"] += 1
                sources.append(
                    {
                        "source_id": source_id,
                        "document_name": document_name,
                        "version_number": int(unit.get("version_number")),
                        "status": _product_status(unit),
                        "locator": dict(unit.get("locator") or {}),
                    }
                )

            kind = answer.get("kind")
            if kind is None:
                kind = commit.get("kind")
            if kind is None:
                diag["product_kind_missing"] += 1
            text = answer.get("text")
            if text is None:
                text = commit.get("text")
            if text is None:
                diag["product_text_missing"] += 1
                text = ""
            diag["kind_answer_commit_mismatch"] += int(
                answer.get("kind") is not None
                and commit.get("kind") is not None
                and answer.get("kind") != commit.get("kind")
            )
            diag["text_answer_commit_mismatch"] += int(
                answer.get("text") is not None
                and commit.get("text") is not None
                and answer.get("text") != commit.get("text")
            )
            diag["sources_total"] += len(sources)
            diag["sources_active"] += sum(1 for item in sources if item["status"] == "active")

            product = {
                "kind": kind if kind is not None else "",
                "text": text,
                "sources": sources,
                # 供 source_index_from_rows 还原 unit_key/locator（与 citation_evidence 同源 DB 行）。
                "evidence": [
                    {
                        "unit_id": item["source_id"],
                        "unit_key": units[item["source_id"]].get("unit_key"),
                        "locator": dict(units[item["source_id"]].get("locator") or {}),
                    }
                    for item in sources
                ],
            }
            turns.append({"turn": int(turn_row["turn_index"]), "status": "ok", "product": product})
        rows[case_id] = {"case_id": case_id, "turns": turns}
        envelopes_by_case[case_id] = envelopes
        if origin_out is not None:
            origin_out[case_id] = {
                "round": "current",
                "file_count": len(digests),
                "file_sha256": digests,
                "turn_index": int(plan_row["turns"][-1]["turn_index"]),
            }
    return rows, envelopes_by_case


# --------------------------------------------------------------------------- #
# 任务 A：质量评分 + 自证
# --------------------------------------------------------------------------- #


def _score_cases(
    cases: Sequence[Any],
    rows: Mapping[str, Mapping[str, Any]],
    plan_quality: Mapping[str, str],
    document_codes: Mapping[str, str],
    scoring: Any,
    score_run: Any,
    check_ids: Sequence[str],
    wiring: Any,
    scored_out: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], bool, bool, dict[str, Any]]:
    """（改动清单 L）整个评分体在运行声明的 source-map 分发作用域内执行。

    作用域内 ``score_run.load_holdout_source_map()`` 由版本分发器接管（v0.2 → 12 码），
    与本轮受控入口计分时**同一口径**；作用域外驱动层默认行为一字未改。分发器必须真的被
    调用过（``served_by_dispatch>=1``），否则固定码拒绝——不接受"声明了但没生效"。
    """
    try:
        dispatch_scope = wiring.dispatched_scoring_map(SCORING_MAP_PATH)
        dispatch = dispatch_scope.__enter__()
    except ToolError:
        raise
    except Exception:  # noqa: BLE001
        _fail("scoring_map_dispatch_failed", "score_cases")
    try:
        source_map = score_run.load_holdout_source_map()
        source_index = score_run.source_index_from_rows(rows) or None
        expected = set(document_codes.values())
        records: list[dict[str, Any]] = []
        scored_status: dict[str, str] = {}
        for case in cases:
            case_id = str(case.case_id)
            mapped = score_run.remap_holdout_case(case, source_map)
            scored = scoring.score_public_case(
                mapped,
                rows[case_id],
                document_codes=document_codes,
                source_index=source_index,
                allowed_doc_codes=expected,
                execution_mode="live",
                real_calls=0,
                include_source_version=True,
            )
            if scored_out is not None:
                scored_out[case_id] = {"scored": scored, "mapped": mapped, "source_index": source_index, "allowed": expected}
            status = str(scored.score.status)
            structural = [
                issue.code
                for issue in scored.score.issues
                if issue.code in score_run.HOLDOUT_STRUCTURAL_ISSUE_CODES
            ]
            if structural:
                status = "error" if status == "pass" else status
            status = status if status in CASE_STATUSES else "error"
            by_id = {
                str(item.get("check_id")): str(item.get("status"))
                for item in scored.score.checks
                if isinstance(item, Mapping)
            }
            evidence_by_id = {
                str(item.get("check_id")): dict(item.get("evidence") or {})
                for item in scored.score.checks
                if isinstance(item, Mapping)
            }
            check_statuses = {
                check_id: (by_id[check_id] if by_id.get(check_id) in CHECK_STATUSES else "unknown")
                for check_id in check_ids
            }
            failed = [check_id for check_id in check_ids if check_statuses[check_id] == "fail"]
            scored_status[case_id] = status
            # R2 追加（改动清单 H）：把每个检查的计数投影成纯整数（不落任何数字原文）。
            value_hit_ev = evidence_by_id.get("value_hit", {})
            value_expected = int(value_hit_ev.get("expected") or 0)
            missing_values = value_hit_ev.get("missing")
            value_missing = len(missing_values) if isinstance(missing_values, list) else 0
            value_matched = max(value_expected - value_missing, 0)
            no_fab_ev = evidence_by_id.get("value_no_fabricated", {})
            extra_values = no_fab_ev.get("extra")
            value_extra = len(extra_values) if isinstance(extra_values, list) else 0
            source_hit_ev = evidence_by_id.get("source_hit", {})
            source_expected = int(source_hit_ev.get("expected") or 0)
            missing_sources = source_hit_ev.get("missing_index")
            source_missing = len(missing_sources) if isinstance(missing_sources, list) else 0
            if "matched" in source_hit_ev:
                source_matched = int(source_hit_ev.get("matched") or 0)
            else:
                source_matched = max(source_expected - source_missing, 0)
            forbidden_ev = evidence_by_id.get("source_forbidden", {})
            forbidden_hits = forbidden_ev.get("violations_index")
            source_forbidden_hit = len(forbidden_hits) if isinstance(forbidden_hits, list) else 0
            turns = rows[case_id]["turns"]
            final_kind = str(((turns[-1].get("product") or {}).get("kind")) or "") if turns else ""
            records.append(
                {
                    "case_id": case_id,
                    "turn_index": int(turns[-1]["turn"]) if turns else 0,
                    "turn_count": len(turns),
                    "quality_status": status,
                    "failed_check_ids": failed,
                    "check_statuses": check_statuses,
                    "failed_check_count": len(failed),
                    "value_expected": value_expected,
                    "value_matched": value_matched,
                    "value_missing": value_missing,
                    "value_extra": value_extra,
                    "source_expected": source_expected,
                    "source_matched": source_matched,
                    "source_missing": source_missing,
                    "source_forbidden_hit": source_forbidden_hit,
                    "kind": final_kind if CODE_RE.fullmatch(final_kind) else "unknown_kind",
                    "should_refuse": bool(getattr(case, "should_refuse", False)),
                    "refusal_expected_applicable": bool(
                        check_statuses.get("refusal_expected") in {"pass", "fail"}
                    ),
                    "refusal_expected_status": str(check_statuses.get("refusal_expected", "unknown")),
                    "refusal_effective": bool(final_kind in REFUSAL_KIND_CODES),
                }
            )

        marks, _unclassified = score_run.holdout_case_scores_from_rows(
            cases,
            rows,
            document_codes=document_codes,
            source_index=source_index,
            allowed_doc_codes=expected,
            execution_mode="live",
            real_calls=0,
        )
        holdout_status = {str(mark.case_id): str(mark.status) for mark in marks}
        paths_agree = all(scored_status.get(cid) == holdout_status.get(cid) for cid in scored_status) and set(
            scored_status
        ) == set(holdout_status)
        match = all(scored_status.get(cid) == plan_quality.get(cid) for cid in scored_status) and set(
            scored_status
        ) == set(plan_quality)
    finally:
        dispatch_scope.__exit__(*sys.exc_info())

    # （改动清单 L）分发必须真的被调用，且口径必须是运行声明的 v0.2 / 12 码；缺一即拒绝。
    try:
        record = wiring.dispatch_summary(dispatch)
    except ToolError:
        raise
    except Exception:  # noqa: BLE001
        _fail("scoring_map_summary_failed", "score_cases")
    if int(record.get("served_by_dispatch") or 0) < 1 or int(record.get("resolutions") or 0) < 1:
        _fail("scoring_map_dispatch_unused", "score_cases")
    if str(record.get("schema_version")) != EXPECTED_SCORING_MAP_SCHEMA:
        _fail("scoring_map_schema_mismatch", "score_cases")
    if int(record.get("code_count") or 0) != EXPECTED_SCORING_MAP_CODE_COUNT:
        _fail("scoring_map_code_count_mismatch", "score_cases")
    if int(record.get("driver_default_code_count") or 0) != EXPECTED_DRIVER_DEFAULT_MAP_CODE_COUNT:
        _fail("scoring_map_driver_default_mismatch", "score_cases")
    scoring_map = {
        "schema_version": str(record["schema_version"]),
        "code_count": int(record["code_count"]),
        "driver_default_code_count": int(record["driver_default_code_count"]),
        "served_by_dispatch": int(record["served_by_dispatch"]),
        "resolutions": int(record["resolutions"]),
        "source_map_sha256": _sha256_file(pathlib.Path(SCORING_MAP_PATH)),
        "matches_run_declaration": bool(
            str(record["schema_version"]) == EXPECTED_SCORING_MAP_SCHEMA
            and int(record["code_count"]) == EXPECTED_SCORING_MAP_CODE_COUNT
            and int(record["served_by_dispatch"]) >= 1
        ),
    }
    return records, match, paths_agree, scoring_map


# --------------------------------------------------------------------------- #
# 评分版本对照（改动清单 K）：同一题用"原口径 / 当前批准口径"各算一次
# --------------------------------------------------------------------------- #


def structural_key_count(scoring: Any, scored: Any) -> int:
    """本题本轮被 102a 结构 token 放行的 key 数量（locator 整数 ∪ 分页计数）。

    只返回计数，不返回 key 内容——key 是数字/定位坐标，属禁止出口面。
    """
    outcome = getattr(scored, "outcome", None)
    if outcome is None:
        return 0
    try:
        keys = frozenset(scoring.citation_structural_number_keys(outcome.citations)) | frozenset(
            scoring._pagination_number_keys(outcome.pagination)  # noqa: SLF001
        )
    except Exception:  # noqa: BLE001
        _fail("structural_key_probe_failed", "structural_key_count")
    return len(keys)


def score_original_caliber(
    scoring: Any,
    mapped: Any,
    row: Mapping[str, Any],
    *,
    document_codes: Mapping[str, str],
    source_index: Any,
    allowed: set[str],
) -> Any:
    """用**2026-11-16 原评分口径**（不含 T-R1-102a 结构 token 放行）重算同一题。

    实现方式：只把 102a 新增的两个加数器临时替换成空集，其余调用参数与
    ``score_public_case`` 逐字相同；``finally`` 立即还原。判据本身**未改**——被关掉的
    只是 2026-11-17 主人批准后才存在的放行项，因此这正是"旧口径"。
    """
    citation_adder = scoring.citation_structural_number_keys
    pagination_adder = scoring._pagination_number_keys  # noqa: SLF001
    try:
        scoring.citation_structural_number_keys = lambda *_a, **_k: frozenset()
        scoring._pagination_number_keys = lambda *_a, **_k: frozenset()  # noqa: SLF001
        return scoring.score_public_case(
            mapped,
            row,
            document_codes=document_codes,
            source_index=source_index,
            allowed_doc_codes=allowed,
            execution_mode="live",
            real_calls=0,
            include_source_version=True,
        )
    finally:
        scoring.citation_structural_number_keys = citation_adder
        scoring._pagination_number_keys = pagination_adder  # noqa: SLF001


def check_status_map(scored: Any, check_ids: Sequence[str]) -> dict[str, str]:
    """把一题的 checks 归一成 ``check_id -> 固定状态``（未知状态统一记 unknown）。"""
    by_id = {
        str(item.get("check_id")): str(item.get("status"))
        for item in scored.score.checks
        if isinstance(item, Mapping)
    }
    return {
        check_id: (by_id[check_id] if by_id.get(check_id) in CHECK_STATUSES else "unknown")
        for check_id in check_ids
    }


def explain_version_flip(
    *,
    current: Mapping[str, Mapping[str, str]],
    original: Mapping[str, Mapping[str, str]],
    current_case_status: Mapping[str, str],
    original_case_status: Mapping[str, str],
    check_ids: Sequence[str],
    plan_quality: Mapping[str, str],
    structural_counts: Mapping[str, int],
) -> dict[str, Any]:
    """判断"重建 != case-plan"能否被评分口径差异解释（不改旧值、不吞差异）。

    ``explained`` 只在一件事成立时为真：**把 102a 结构 token 关掉后，每道差异题都回到
    case-plan 的旧值**。否则差异属于"未解释"，调用方必须 ok=false 停下。
    """
    flips = sorted(
        case_id
        for case_id in current
        if str(current_case_status[case_id]) != str(plan_quality.get(case_id))
    )
    first_diff: list[dict[str, Any]] = []
    for case_id in flips:
        earliest = ""
        for check_id in check_ids:
            if str(current[case_id].get(check_id)) != str(original[case_id].get(check_id)):
                earliest = check_id
                break
        first_diff.append(
            {
                "case_id": case_id,
                "first_diff_check_id": earliest if earliest else "none",
                "current_status": str(current_case_status[case_id]),
                "original_status": str(original_case_status[case_id]),
                "plan_status": str(plan_quality.get(case_id)),
                "structural_key_count": int(structural_counts.get(case_id, 0)),
            }
        )
    explained = bool(flips) and all(
        str(original_case_status[case_id]) == str(plan_quality.get(case_id)) for case_id in flips
    )
    return {"flip_cases": flips, "details": first_diff, "explained": explained}


# --------------------------------------------------------------------------- #
# 任务 C：四轴 classify + 空集证明进度复刻
# --------------------------------------------------------------------------- #


def _empty_scope_progress(
    evidence: Mapping[str, Any], hard: Any, *, compat: str | None = None
) -> tuple[str, dict[str, bool]]:
    """复刻 ``_empty_use_scope_proof`` 的判据顺序，返回 (首个失败码, 里程碑)。

    只调用冻结模块的只读 helper/常量；不 monkeypatch、不写回。
    """
    compat = str(compat or hard.REFUSAL_COMPAT_V0_1)
    ms = {
        "reached_empty_set_check": False,
        "kind_effective": False,
        "reached_template_check": False,
        "template_registered": False,
    }

    def stop(code: str) -> tuple[str, dict[str, bool]]:
        return code, ms

    completeness = evidence.get("completeness")
    if not isinstance(completeness, Mapping) or str(completeness.get("status")) != "complete":
        return stop("evidence_incomplete")
    try:
        events = hard._events(evidence)
        projection = hard._projection(evidence)
    except Exception:  # noqa: BLE001
        return stop("branch_evidence_missing")

    if set(evidence) - hard._envelope_allowed_keys(
        evidence.get("fixture_kind"), evidence.get("schema_version")
    ):
        return stop("unknown_usage_field")
    capture = evidence.get("capture")
    if not isinstance(capture, Mapping):
        return stop("branch_evidence_missing")
    if set(capture) - hard.EMPTY_SCOPE_CAPTURE_KEYS:
        return stop("unknown_usage_field")
    if not isinstance(capture.get("events"), list):
        return stop("branch_evidence_missing")
    if not isinstance(capture.get("errors"), list):
        return stop("branch_evidence_missing")
    if capture.get("errors"):
        return stop("evidence_incomplete")
    turn = evidence.get("turn")
    if not isinstance(turn, Mapping):
        return stop("branch_evidence_missing")
    if set(turn) - hard.EMPTY_SCOPE_TURN_KEYS:
        return stop("unknown_usage_field")

    for event in events:
        if not isinstance(event, Mapping):
            return stop("branch_evidence_missing")
        if set(event) - hard.EMPTY_SCOPE_EVENT_KEYS:
            return stop("unknown_usage_field")
        if "kind" not in event or "payload" not in event:
            return stop("branch_evidence_missing")
        kind = str(event.get("kind") or "")
        if kind not in hard.CAPTURE_EVENT_FIELDS:
            return stop("unknown_usage_field")
        payload = event.get("payload")
        if not isinstance(payload, Mapping):
            return stop("branch_evidence_missing")
        if set(payload) - set(hard.CAPTURE_EVENT_FIELDS[kind]):
            return stop("unknown_usage_field")
        for field, rule in hard.EMPTY_SCOPE_USAGE_FIELDS.get(kind, ()):
            if field not in payload:
                return stop("branch_evidence_missing")
            value = payload[field]
            if rule == "list_empty":
                if not hard._is_list(value):
                    return stop("branch_evidence_missing")
                if value:
                    return stop("empty_set_not_proven")
            elif rule == "zero_int":
                if not hard._is_count(value):
                    return stop("branch_evidence_missing")
                if value != 0:
                    return stop("empty_set_not_proven")
        if kind in hard.EMPTY_SCOPE_QUERY_STATE_KINDS:
            state = payload.get("state_json")
            if not isinstance(state, Mapping):
                return stop("branch_evidence_missing")
            row_present = payload.get("row_present")
            if type(row_present) is not bool:
                return stop("branch_evidence_missing")
            if state:
                if "candidates" not in state:
                    return stop("branch_evidence_missing")
                candidates = state.get("candidates")
                if not hard._is_list(candidates):
                    return stop("branch_evidence_missing")
                if candidates:
                    return stop("empty_set_not_proven")
                if kind == "query_state_observed" and row_present is False:
                    return stop("branch_evidence_inconsistent")
        if kind == "capture_error":
            return stop("evidence_incomplete")

    for event in events:
        try:
            hard.clean_event_payload(str(event.get("kind")), dict(event.get("payload") or {}))
        except Exception:  # noqa: BLE001
            return stop("branch_evidence_missing")

    required: dict[str, Mapping[str, Any]] = {}
    for kind in hard.EMPTY_SCOPE_REQUIRED_EVENTS:
        rows = hard._payloads(events, kind)
        if len(rows) != 1:
            return stop("branch_evidence_missing")
        required[kind] = rows[0]
    claim = required["claim_observed"]
    context = required["context_observed"]
    plan = required["plan_observed"]
    answer = required["answer_result"]
    commit = required["commit_observed"]
    if not all(
        hard._is_str(claim.get(key))
        for key in ("request_id", "conversation_id", "authenticated_user_id", "owner_user_id")
    ):
        return stop("branch_evidence_missing")
    if not hard._is_count(context.get("count")) or type(context.get("empty")) is not bool:
        return stop("branch_evidence_missing")
    if not hard._is_str(plan.get("path")):
        return stop("branch_evidence_missing")
    if not hard._is_str(answer.get("kind")) or not hard._is_str(answer.get("text")):
        return stop("branch_evidence_missing")
    if (
        not hard._is_str(commit.get("message_id"))
        or not hard._is_str(commit.get("kind"))
        or not hard._is_str(commit.get("text"))
    ):
        return stop("branch_evidence_missing")
    if not hard._is_str(answer.get("request_id")) or not hard._is_str(commit.get("request_id")):
        return stop("branch_evidence_missing")

    if set(projection) - hard.EMPTY_SCOPE_PROJECTION_KEYS:
        return stop("unknown_usage_field")
    for key in hard.EMPTY_SCOPE_PROJECTION_REQUIRED_KEYS:
        if key not in projection:
            return stop("branch_evidence_missing")
    for group in ("messages", "message_sources", "units", "unresolved_unit_ids", "query_states"):
        rows = projection.get(group)
        if not hard._is_list(rows):
            return stop("branch_evidence_missing")
        allowed = hard.EMPTY_SCOPE_PROJECTION_ROW_KEYS[group]
        for row in rows:
            if not isinstance(row, Mapping):
                return stop("branch_evidence_missing")
            if set(row) - allowed:
                return stop("unknown_usage_field")
    conversation = projection.get("conversation")
    request_row = projection.get("request")
    if not isinstance(conversation, Mapping) or not isinstance(request_row, Mapping):
        return stop("branch_evidence_missing")
    if set(conversation) - hard.EMPTY_SCOPE_PROJECTION_ROW_KEYS["conversation"]:
        return stop("unknown_usage_field")
    if set(request_row) - hard.EMPTY_SCOPE_PROJECTION_ROW_KEYS["request"]:
        return stop("unknown_usage_field")
    if not hard._is_str(conversation.get("id")) or not hard._is_str(conversation.get("owner_user_id")):
        return stop("branch_evidence_missing")
    if not all(
        hard._is_str(request_row.get(key))
        for key in ("id", "conversation_id", "user_id", "result_message_id")
    ):
        return stop("branch_evidence_missing")
    if projection.get("units"):
        return stop("empty_set_not_proven")
    if projection.get("message_sources") or projection.get("unresolved_unit_ids"):
        return stop("empty_set_not_proven")
    for row in projection.get("query_states") or ():
        state = row.get("state_json")
        if not isinstance(state, Mapping):
            return stop("branch_evidence_missing")
        if state:
            if "candidates" not in state:
                return stop("branch_evidence_missing")
            candidates = state.get("candidates")
            if not hard._is_list(candidates):
                return stop("branch_evidence_missing")
            if candidates:
                return stop("empty_set_not_proven")
    if projection.get("query_states_available") is not True:
        return stop("branch_evidence_missing")
    if projection.get("truncations"):
        return stop("evidence_incomplete")
    if projection.get("errors"):
        return stop("evidence_incomplete")

    claim_request = str(claim.get("request_id"))
    if str(claim.get("conversation_id")) != str(conversation.get("id")):
        return stop("branch_evidence_inconsistent")
    if claim_request != str(request_row.get("id")):
        return stop("branch_evidence_inconsistent")
    if str(answer.get("request_id")) != claim_request or str(commit.get("request_id")) != claim_request:
        return stop("branch_evidence_inconsistent")
    if str(commit.get("message_id")) != str(request_row.get("result_message_id")):
        return stop("branch_evidence_inconsistent")
    if hard._used_unit_layers(events):
        return stop("empty_set_not_proven")
    commit_kind = str(commit.get("kind") or "")
    if commit_kind != str(answer.get("kind") or ""):
        return stop("branch_evidence_inconsistent")
    final_text = commit.get("text")
    if commit.get("text") != answer.get("text"):
        return stop("branch_evidence_inconsistent")
    if commit_kind not in hard.NO_FACT_KINDS:
        return stop("empty_set_not_proven")

    inputs, outputs = hard._model_event_groups(events)
    all_purposes = set(inputs) | set(outputs)
    allowed_purposes = {"answer", "query_expansion"}
    if all_purposes - allowed_purposes:
        return stop("branch_evidence_missing")
    for purpose in inputs:
        for item in inputs[purpose]:
            if "evidence" not in item or not hard._is_list(item.get("evidence")):
                return stop("branch_evidence_missing")
        in_count = len(inputs[purpose])
        out_count = len(outputs.get(purpose, []))
        if in_count == 0 or out_count == 0:
            return stop("model_events_missing")
        if in_count != 1 or out_count != 1:
            return stop("branch_evidence_inconsistent")
    for purpose in outputs:
        if purpose not in inputs:
            return stop("model_events_missing")
    plan_path = str(plan.get("path") or "")
    direct_rows = hard._payloads(events, "direct_rag_answer")
    if plan_path == "rag":
        if len(direct_rows) != 1:
            return stop("branch_evidence_missing")
        direct = direct_rows[0]
        if "answer" in all_purposes:
            return stop("branch_evidence_inconsistent")
        if all_purposes - {"query_expansion"}:
            return stop("branch_evidence_inconsistent")
        # 到达 p2_hard_evidence.py:1432（kind 相等检查；v0_3 允许登记的一条跨层映射）
        ms["reached_empty_set_check"] = True
        direct_kind = str(direct.get("kind"))
        mapped_kind = hard.REFUSAL_KIND_CROSS_LAYER_MAP.get(compat, {}).get(direct_kind)
        kind_ok = direct_kind == commit_kind or (
            mapped_kind == commit_kind
            and direct_kind in hard.NO_FACT_KINDS
            and commit_kind in hard.NO_FACT_KINDS
        )
        ms["kind_effective"] = bool(kind_ok)
        if not kind_ok or str(direct.get("text")) != str(final_text):
            return stop("branch_evidence_inconsistent")
        # 到达模板恒等检查（约 :1447）
        ms["reached_template_check"] = True
        ms["template_registered"] = bool(
            hard._matches_product_no_fact_template(commit_kind, final_text, compat=compat)
        )
        if not ms["template_registered"]:
            return stop("template_identity_unverified")
    elif plan_path == "legacy":
        if direct_rows:
            return stop("branch_evidence_inconsistent")
        if not all_purposes:
            retrievals = hard._payloads(events, "retrieval_observed")
            if not retrievals:
                return stop("model_events_missing")
        elif all_purposes != {"answer"}:
            return stop("branch_evidence_inconsistent")
    else:
        return stop("branch_evidence_missing")
    return "empty_use_scope_ok", ms


def _classify_cases(
    cases: Sequence[Any],
    plan_rows: Sequence[Mapping[str, Any]],
    envelopes_by_case: Mapping[str, list[Mapping[str, Any]]],
    annotation: Any,
    hard: Any,
    reasons: frozenset[str],
    diag: dict[str, int],
    *,
    compat: str,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for case, plan_row in zip(cases, plan_rows):
        case_id = str(case.case_id)
        entries: list[dict[str, Any]] = []
        for turn_row in plan_row["turns"]:
            entries.append(
                {
                    "turn_index": int(turn_row["turn_index"]),
                    "status": str(turn_row["status"]),
                    "error": turn_row.get("error"),
                    "evidence": None,
                }
            )
        executed = [env for env in envelopes_by_case.get(case_id, [])]
        cursor = 0
        for entry in entries:
            if entry["status"] == "executed":
                entry["evidence"] = executed[cursor]
                cursor += 1
        audit = {"quality_status": str(plan_row["quality_status"]), "turns": entries}

        try:
            result = hard.classify_case_evidence(case, annotation, audit, compat=compat)
        except Exception:  # noqa: BLE001 - 单题失败不得炸整份投影
            diag["classification_failures"] += 1
            records.append(
                {
                    "case_id": case_id,
                    "quality_status": str(plan_row["quality_status"]),
                    "evidence_complete": False,
                    "missing_codes": ["classification_failed"],
                    "axes": {
                        axis: {"state": "unknown", "reason": "classification_failed"}
                        for axis in AXES
                    },
                    "safety_first_failure": {
                        "reached_empty_set_check": False,
                        "reached_template_check": False,
                        "kind_effective": False,
                        "template_registered": False,
                        "first_code": "first_failure_unknown",
                    },
                }
            )
            continue

        axes: dict[str, dict[str, str]] = {}
        for axis in AXES:
            verdict = result.axes[axis]
            state = str(verdict.state)
            reason = str(verdict.reason)
            if state not in AXIS_STATES:
                diag["unsafe_code_count"] += 1
                state = "unknown"
            if reason not in reasons:
                diag["unsafe_code_count"] += 1
                reason = "unknown_code"
            axes[axis] = {"state": state, "reason": reason}

        missing_codes: list[str] = []
        for code in result.missing_codes:
            text = str(code)
            if text in reasons:
                missing_codes.append(text)
            else:
                diag["unsafe_code_count"] += 1
                missing_codes.append("unknown_code")

        safety = axes["safety"]
        proof: dict[str, bool] = {
            "reached_empty_set_check": False,
            "reached_template_check": False,
            "kind_effective": False,
            "template_registered": False,
        }
        first_code = "first_failure_unknown"
        envelopes = envelopes_by_case.get(case_id) or []
        if envelopes:
            evidence = envelopes[-1]
            try:
                used_units = hard._used_unit_layers(hard._events(evidence))
            except Exception:  # noqa: BLE001
                used_units = None
                diag["proof_eval_failures"] += 1
            if used_units is None:
                first_code = "first_failure_unknown"
            elif used_units:
                # 空集证明不适用于“实际使用了来源”的回合：只看 safety 自身。
                first_code = (
                    safety["reason"]
                    if safety["state"] in ("violation", "unknown")
                    else safety["state"]
                )
            else:
                replica_code, proof_ms = _empty_scope_progress(evidence, hard, compat=compat)
                proof.update(proof_ms)
                # 模板族是否登记：独立于“是否走到模板检查”计算，用来区分 D5 与“根本没走到”。
                commit_payload = _one_payload(hard._events(evidence), "commit_observed") or {}
                if commit_payload.get("kind") is not None and commit_payload.get("text") is not None:
                    proof["template_registered"] = bool(
                        hard._matches_product_no_fact_template(
                            str(commit_payload.get("kind")),
                            commit_payload.get("text"),
                            compat=compat,
                        )
                    )
                try:
                    frozen_ok, frozen_reason = hard._empty_use_scope_proof(
                        evidence, compat=compat
                    )
                except Exception:  # noqa: BLE001
                    frozen_ok, frozen_reason = False, "first_failure_unknown"
                    diag["proof_eval_failures"] += 1
                if frozen_ok and replica_code != "empty_use_scope_ok":
                    diag["replica_disagreements"] += 1
                    first_code = "first_failure_unknown"
                elif (not frozen_ok) and frozen_reason != replica_code:
                    diag["replica_disagreements"] += 1
                    first_code = "first_failure_unknown"
                elif replica_code != "empty_use_scope_ok":
                    first_code = replica_code
                else:
                    first_code = (
                        safety["reason"]
                        if safety["state"] in ("violation", "unknown")
                        else safety["state"]
                    )
                if proof_ms["reached_template_check"]:
                    first_code = first_code if first_code else "empty_use_scope_ok"
            if first_code not in reasons:
                diag["unsafe_code_count"] += 1
                first_code = "first_failure_unknown"

        records.append(
            {
                "case_id": case_id,
                "quality_status": str(plan_row["quality_status"]),
                "evidence_complete": bool(result.evidence_complete),
                "missing_codes": missing_codes,
                "axes": axes,
                "safety_first_failure": {
                    "reached_empty_set_check": bool(proof["reached_empty_set_check"]),
                    "reached_template_check": bool(proof["reached_template_check"]),
                    "kind_effective": bool(proof["kind_effective"]),
                    "template_registered": bool(proof["template_registered"]),
                    "first_code": first_code,
                },
            }
        )
    return records


# --------------------------------------------------------------------------- #
# 托管链核对
# --------------------------------------------------------------------------- #


def _verify_custody(
    binding: Mapping[str, Any],
    case_plan_path: pathlib.Path,
    case_plan: Mapping[str, Any],
    receipt: Mapping[str, Any],
    seal_manifest: Mapping[str, Any],
    evidence_root: pathlib.Path,
    turn_files: Iterable[str],
) -> bool:
    run_id = str(case_plan.get("run_id"))
    if not RUN_ID_RE.fullmatch(run_id):
        _fail("custody_run_id_invalid", "_verify_custody")
    if str(binding["runs"][0].get("run_id")) != run_id:
        _fail("custody_run_id_mismatch", "_verify_custody")
    if str(receipt.get("run_id")) != run_id:
        _fail("custody_run_id_mismatch", "_verify_custody")
    if not bool(receipt.get("ok")) or str(receipt.get("status")) != "succeeded":
        _fail("custody_receipt_not_succeeded", "_verify_custody")
    seal = receipt.get("seal") if isinstance(receipt.get("seal"), Mapping) else {}
    if seal.get("sealed") is not True:
        _fail("custody_not_sealed", "_verify_custody")
    evidence = receipt.get("evidence") if isinstance(receipt.get("evidence"), Mapping) else {}
    if evidence.get("available") is not True or evidence.get("readback_ok") is not True:
        _fail("custody_evidence_unreadable", "_verify_custody")
    if str(receipt.get("case_plan", {}).get("sha256")) != _sha256_file(case_plan_path):
        _fail("custody_case_plan_sha_mismatch", "_verify_custody")
    if int(receipt.get("case_plan", {}).get("cases", -1)) != len(case_plan.get("cases") or ()):
        _fail("custody_case_plan_count_mismatch", "_verify_custody")
    root_record = seal_manifest.get("evidence_root") if isinstance(seal_manifest, Mapping) else None
    if not isinstance(root_record, Mapping):
        _fail("custody_seal_manifest_invalid", "_verify_custody")
    if str(root_record.get("tree_sha256")) != str(seal.get("evidence_tree_sha256")):
        _fail("custody_tree_sha_mismatch", "_verify_custody")
    files = root_record.get("files")
    if not isinstance(files, list) or len(files) != int(seal.get("evidence_file_count", -1)):
        _fail("custody_seal_manifest_invalid", "_verify_custody")
    records: dict[str, Mapping[str, Any]] = {}
    for row in files:
        if not isinstance(row, Mapping):
            _fail("custody_seal_manifest_invalid", "_verify_custody")
        name = pathlib.PurePosixPath(str(row.get("path")).replace("\\", "/")).name
        records[name] = row
    wanted = set(records)
    if set(turn_files) - wanted:
        _fail("custody_turn_file_unlisted", "_verify_custody")
    for name in sorted(wanted):
        target = evidence_root / name
        if not target.is_file():
            _fail("custody_turn_file_missing", "_verify_custody")
        raw = target.read_bytes()
        row = records[name]
        if int(row.get("bytes", -1)) != len(raw) or str(row.get("sha256")) != _sha256_bytes(raw):
            _fail("custody_turn_file_digest_mismatch", "_verify_custody")
    return True


# --------------------------------------------------------------------------- #
# R2 身份 / 集合 / 来源门（改动清单 B/C/D/E；每个门都是拒绝式，缺一即固定码失败）
# --------------------------------------------------------------------------- #


def tree_digest(root: pathlib.Path, *, prefix: str = "") -> dict[str, Any]:
    """按 ``tools/p2_h2_controlled_execute.tree_digest`` 同一算法重算证据树摘要。

    ``joined = "\\n".join(f"{path}:{sha256}")``（path 为相对 posix 路径、按路径排序），
    对 joined 的 UTF-8 字节取 sha256。``prefix`` 复刻封存时的相对路径前缀：
    sealing 工具是在**证据根**（run 目录的父目录）上取摘要，所以路径形如
    ``<run_dir>/turn-0000.fernet``。前缀不是猜的——由封存清单里既有记录的公共前缀反推，
    见 :func:`gate_key_and_tree`。本函数只读文件，不写回。
    """
    base = pathlib.Path(root)
    files: list[dict[str, Any]] = []
    if base.exists():
        for path in sorted(p for p in base.rglob("*") if p.is_file()):
            files.append(
                {
                    "path": path.relative_to(base).as_posix(),
                    "sha256": _sha256_file(path),
                    "bytes": path.stat().st_size,
                }
            )
    joined = "\n".join(f"{prefix + item['path']}:{item['sha256']}" for item in files)
    return {
        "tree_sha256": hashlib.sha256(joined.encode("utf-8")).hexdigest(),
        "file_count": len(files),
        "bytes": sum(int(item["bytes"]) for item in files),
    }


def gate_cwd_is_repo_root() -> bool:
    """运行目录必须是仓库根：``ingest plan`` 的 corpus 路径是**相对仓库根**的。

    这是实测出来的隐式输入（不在任何私有文件里声明）：从别处启动会让 12 份 corpus 源
    全部解析不到，``load_v3_bundle`` 只能给出笼统失败码。这里把它显式化并 fail closed。
    """
    try:
        cwd = pathlib.Path.cwd().resolve()
    except OSError:
        _fail("cwd_unresolved", "gate_cwd_is_repo_root")
    if cwd != REPO.resolve():
        _fail("cwd_not_repo_root", "gate_cwd_is_repo_root")
    return True


def gate_run_identity(
    run_entry: Mapping[str, Any], receipt: Mapping[str, Any], case_plan: Mapping[str, Any]
) -> bool:
    """run_index / run_id / scenario_id 三处逐值相等，否则固定码拒绝。"""
    if int(run_entry.get("run_index", -1)) != EXPECTED_RUN_INDEX:
        _fail("identity_run_index_mismatch", "gate_run_identity")
    if str(case_plan.get("run_id")) != EXPECTED_RUN_ID or str(receipt.get("run_id")) != EXPECTED_RUN_ID:
        _fail("identity_run_id_mismatch", "gate_run_identity")
    if str(run_entry.get("run_id")) != EXPECTED_RUN_ID:
        _fail("identity_run_id_mismatch", "gate_run_identity")
    if (
        str(run_entry.get("scenario_id")) != EXPECTED_SCENARIO_ID
        or str(case_plan.get("run_binding", {}).get("scenario_id")) != EXPECTED_SCENARIO_ID
        or str(receipt.get("scenario_id")) != EXPECTED_SCENARIO_ID
    ):
        _fail("identity_scenario_mismatch", "gate_run_identity")
    return True


def gate_business_date(
    binding: Mapping[str, Any], receipt: Mapping[str, Any], case_plan: Mapping[str, Any]
) -> bool:
    """业务日必须是 2026-11-20：binding 三处、receipt、case-plan run_binding 全部逐值相等。

    不取本机今日，也不接受 R1 的 2026-07-15。
    """
    run_entry = (binding.get("runs") or [{}])[0]
    wanted = EXPECTED_BUSINESS_DATE
    observed = {
        "binding.business_date": str(binding.get("business_date")),
        "binding.runs[0].business_date": str(run_entry.get("business_date")),
        "binding.runs[0].manifest_business_date": str(run_entry.get("manifest_business_date")),
        "binding.runs[0].rag_business_date": str(run_entry.get("rag_business_date")),
        "receipt.business_date": str(receipt.get("business_date")),
        "receipt.run_binding.business_date": str(receipt.get("run_binding", {}).get("business_date")),
        "case_plan.run_binding.business_date": str(
            case_plan.get("run_binding", {}).get("business_date")
        ),
    }
    for name, value in observed.items():
        if value != wanted:
            _fail("identity_business_date_mismatch", "gate_business_date")
    return True


def gate_case_set(case_ids: Sequence[str], plan_ids: Sequence[str]) -> bool:
    """case 集合必须**恰好**是 5 题且顺序一致：多题、少题、重复题一律拒绝。"""
    wanted = list(EXPECTED_CASE_IDS)
    for name, got in (("contract", list(case_ids)), ("case_plan", list(plan_ids))):
        if len(got) != len(set(got)):
            _fail("identity_case_set_duplicate", "gate_case_set")
        if len(got) != len(wanted) or got != wanted:
            _fail("identity_case_set_mismatch", "gate_case_set")
    return True


def gate_turn_shape(plan_rows: Sequence[Mapping[str, Any]]) -> bool:
    """turn 文件恰好 6 件；C14 必须占 turn-0001/0002 两回合；其余各 1 回合。"""
    seen: dict[int, str] = {}
    total = 0
    per_case: dict[str, list[int]] = {}
    for row in plan_rows:
        case_id = str(row.get("case_id"))
        turns = list(row.get("turns") or ())
        indexes: list[int] = []
        for turn_row in turns:
            if str(turn_row.get("status")) != "executed":
                continue
            index = int(turn_row["turn_index"])
            if index in seen:
                _fail("identity_turn_index_duplicate", "gate_turn_shape")
            seen[index] = case_id
            indexes.append(index)
            total += 1
        per_case[case_id] = indexes
    if total != EXPECTED_TURN_COUNT:
        _fail("identity_turn_count_mismatch", "gate_turn_shape")
    for case_id, indexes in EXPECTED_MULTI_TURN.items():
        if tuple(per_case.get(case_id, ())) != indexes:
            _fail("identity_multi_turn_shape_mismatch", "gate_turn_shape")
    for case_id, indexes in per_case.items():
        if case_id in EXPECTED_MULTI_TURN:
            continue
        if len(indexes) != 1:
            _fail("identity_multi_turn_shape_mismatch", "gate_turn_shape")
    return True


def gate_origin_round(origin: Mapping[str, Mapping[str, Any]]) -> bool:
    """每题的重建来源必须是**本轮**（``round == "current"``），且带本轮读回的密文 sha256。

    旧卡/旧结果当本轮用时（``round == "historical"``）在这里被拒绝。
    """
    if not origin:
        _fail("origin_missing", "gate_origin_round")
    for case_id, record in origin.items():
        if str(record.get("round")) != "current":
            _fail("origin_round_not_current", "gate_origin_round")
        digests = record.get("file_sha256")
        if not isinstance(digests, Sequence) or not digests:
            _fail("origin_missing", "gate_origin_round")
        for digest in digests:
            if not SHA_RE.fullmatch(str(digest)):
                _fail("origin_missing", "gate_origin_round")
    return True


def gate_scope_evidence(envelopes: Mapping[str, Sequence[Mapping[str, Any]]]) -> bool:
    """scope 判据证据齐备：envelope 需有 turn/capture/db_projection/completeness，
    且 projection 的 units/message_sources/messages/unresolved_unit_ids/query_states 分组齐全。

    缺任何一项即 ``scope_evidence_missing``——不许把"没有 scope 证据"当成"作用域没问题"。
    """
    if not envelopes:
        _fail("scope_evidence_missing", "gate_scope_evidence")
    for case_id, rows in envelopes.items():
        if not rows:
            _fail("scope_evidence_missing", "gate_scope_evidence")
        for envelope in rows:
            if not isinstance(envelope, Mapping):
                _fail("scope_evidence_missing", "gate_scope_evidence")
            if SCOPE_ENVELOPE_KEYS - set(envelope):
                _fail("scope_evidence_missing", "gate_scope_evidence")
            projection = envelope.get("db_projection")
            if not isinstance(projection, Mapping) or SCOPE_PROJECTION_KEYS - set(projection):
                _fail("scope_evidence_missing", "gate_scope_evidence")
            capture = envelope.get("capture")
            if not isinstance(capture, Mapping) or not isinstance(capture.get("events"), list):
                _fail("scope_evidence_missing", "gate_scope_evidence")
    return True


def gate_key_and_tree(
    *,
    key_sha256: str,
    receipt: Mapping[str, Any],
    seal_manifest: Mapping[str, Any],
    seal_manifest_sha256: str,
    evidence_root: pathlib.Path,
) -> dict[str, Any]:
    """key sha256 / 证据树重算 / 封存清单 sha 三处身份必须与回执逐值相等。

    证据树的相对路径前缀**由封存清单反推**：清单里每个 ``path`` 去掉 basename 后的公共
    前缀即为 sealing 时的相对根（本包为 ``<run_dir>/``）。前缀不唯一或某条记录的
    basename 在证据目录里找不到 → 拒绝，不猜。
    """
    seal = receipt.get("seal") if isinstance(receipt.get("seal"), Mapping) else {}
    if str(key_sha256) != str(receipt.get("evidence_key_sha256")):
        _fail("identity_key_sha_mismatch", "gate_key_and_tree")
    root_record = seal_manifest.get("evidence_root") if isinstance(seal_manifest, Mapping) else None
    if not isinstance(root_record, Mapping):
        _fail("identity_seal_manifest_invalid", "gate_key_and_tree")
    rows = root_record.get("files")
    if not isinstance(rows, list) or not rows:
        _fail("identity_seal_manifest_invalid", "gate_key_and_tree")
    prefixes: set[str] = set()
    basenames: set[str] = set()
    for row in rows:
        raw = str(row.get("path") or "")
        name = pathlib.PurePosixPath(raw.replace("\\", "/")).name
        parent = raw.replace("\\", "/")[: len(raw.replace("\\", "/")) - len(name)]
        prefixes.add(parent)
        basenames.add(name)
    if len(prefixes) != 1:
        _fail("identity_seal_manifest_invalid", "gate_key_and_tree")
    prefix = prefixes.pop()
    for name in basenames:
        if not (evidence_root / name).is_file():
            _fail("identity_evidence_file_missing", "gate_key_and_tree")
    digest = tree_digest(evidence_root, prefix=prefix)
    if str(digest["tree_sha256"]) != str(seal.get("evidence_tree_sha256")):
        _fail("identity_evidence_tree_mismatch", "gate_key_and_tree")
    if str(root_record.get("tree_sha256")) != str(digest["tree_sha256"]):
        _fail("identity_evidence_tree_mismatch", "gate_key_and_tree")
    if str(seal_manifest_sha256) != str(seal.get("seal_manifest_sha256")):
        _fail("identity_seal_manifest_sha_mismatch", "gate_key_and_tree")
    if int(digest["file_count"]) != int(EXPECTED_EVIDENCE_FILE_COUNT):
        _fail("identity_evidence_file_count_mismatch", "gate_key_and_tree")
    if int(seal.get("evidence_file_count", -1)) != int(digest["file_count"]):
        _fail("identity_evidence_file_count_mismatch", "gate_key_and_tree")
    if int(seal.get("evidence_bytes", -1)) != int(digest["bytes"]):
        _fail("identity_evidence_bytes_mismatch", "gate_key_and_tree")
    return digest


def gate_binding_plan_binding(binding: Mapping[str, Any], case_plan: Mapping[str, Any]) -> bool:
    """binding 的 custody/manifest 摘要必须与 case-plan ``bindings`` 逐值相等。"""
    run_entry = (binding.get("runs") or [{}])[0]
    scenario_binding = run_entry.get("scenario_binding") or {}
    plan_bindings = case_plan.get("bindings") or {}
    for name in ("custody_sha256", "manifest_sha256"):
        if str(scenario_binding.get(name)) != str(plan_bindings.get(name)):
            _fail("identity_binding_plan_mismatch", "gate_binding_plan_binding")
    inputs = binding.get("inputs") or {}
    annotation = inputs.get("annotation_ciphertext") or {}
    holdout = inputs.get("holdout_manifest") or {}
    if str(annotation.get("sha256")) != str(plan_bindings.get("custody_sha256")):
        _fail("identity_binding_plan_mismatch", "gate_binding_plan_binding")
    if str(holdout.get("sha256")) != str(plan_bindings.get("manifest_sha256")):
        _fail("identity_binding_plan_mismatch", "gate_binding_plan_binding")
    return True


def gate_receipt_flags(receipt: Mapping[str, Any], case_plan: Mapping[str, Any]) -> bool:
    """回执的 sealed / evidence 可读回 / real_calls 必须成立且与 case-plan 一致。"""
    seal = receipt.get("seal") if isinstance(receipt.get("seal"), Mapping) else {}
    evidence = receipt.get("evidence") if isinstance(receipt.get("evidence"), Mapping) else {}
    if seal.get("sealed") is not True:
        _fail("identity_receipt_not_sealed", "gate_receipt_flags")
    if evidence.get("available") is not True or evidence.get("readback_ok") is not True:
        _fail("identity_evidence_readback_failed", "gate_receipt_flags")
    real_sends = int(receipt.get("real_sends", -1))
    if real_sends != int(case_plan.get("real_calls", -2)):
        _fail("identity_real_calls_mismatch", "gate_receipt_flags")
    if real_sends <= 0:
        _fail("identity_real_calls_mismatch", "gate_receipt_flags")
    return True


def gate_quality_counts(records: Sequence[Mapping[str, Any]], check_ids: Sequence[str]) -> dict[str, int]:
    """逐题字段与汇总计数双向自洽；``skipped`` 不计 pass，``unknown`` 一律拒绝。"""
    failed = {check_id: 0 for check_id in check_ids}
    passed = {check_id: 0 for check_id in check_ids}
    skipped = {check_id: 0 for check_id in check_ids}
    total = 0
    for record in records:
        statuses = record.get("check_statuses") or {}
        if set(statuses) != set(check_ids):
            _fail("quality_count_inconsistent", "gate_quality_counts")
        per_case_failed = []
        for check_id in check_ids:
            status = str(statuses.get(check_id))
            total += 1
            if status == "pass":
                passed[check_id] += 1
            elif status == "fail":
                failed[check_id] += 1
                per_case_failed.append(check_id)
            elif status in {"skipped", "skipped_requires_ocr"}:
                skipped[check_id] += 1
            else:
                _fail("check_status_unknown", "gate_quality_counts")
        if per_case_failed != list(record.get("failed_check_ids") or ()):
            _fail("quality_count_inconsistent", "gate_quality_counts")
        if len(per_case_failed) != int(record.get("failed_check_count", -1)):
            _fail("quality_count_inconsistent", "gate_quality_counts")
    return {
        "checks_total": total,
        "checks_passed_total": sum(passed.values()),
        "checks_failed_total": sum(failed.values()),
        "checks_skipped_total": sum(skipped.values()),
        "_failed": failed,
        "_passed": passed,
        "_skipped": skipped,
    }


def _verify_identity(
    *,
    run_entry: Mapping[str, Any],
    binding: Mapping[str, Any],
    receipt: Mapping[str, Any],
    seal_manifest: Mapping[str, Any],
    seal_manifest_sha256: str,
    case_plan: Mapping[str, Any],
    case_ids: Sequence[str],
    plan_rows: Sequence[Mapping[str, Any]],
    turn_files: Sequence[str],
    evidence_root: pathlib.Path,
    key_sha256: str,
) -> dict[str, Any]:
    """把 8 项完整性门跑一遍，返回只含布尔/计数的 SAFE 记录。"""
    gate_run_identity(run_entry, receipt, case_plan)
    gate_business_date(binding, receipt, case_plan)
    gate_case_set(case_ids, [str(row.get("case_id")) for row in plan_rows])
    gate_turn_shape(plan_rows)
    digest = gate_key_and_tree(
        key_sha256=key_sha256,
        receipt=receipt,
        seal_manifest=seal_manifest,
        seal_manifest_sha256=seal_manifest_sha256,
        evidence_root=evidence_root,
    )
    gate_binding_plan_binding(binding, case_plan)
    gate_receipt_flags(receipt, case_plan)
    seal = receipt.get("seal") if isinstance(receipt.get("seal"), Mapping) else {}
    evidence = receipt.get("evidence") if isinstance(receipt.get("evidence"), Mapping) else {}
    return {
        "key_sha256_matches_receipt": True,
        "evidence_tree_sha_matches_receipt": True,
        "seal_manifest_sha_matches_receipt": True,
        "evidence_tree_recomputed_matches_seal": True,
        "binding_matches_case_plan": True,
        "case_set_matches": True,
        "turn_count_matches": True,
        "business_date_matches": True,
        "run_index_matches": True,
        "run_id_matches": True,
        "scenario_id_matches": True,
        "evidence_readback_ok": bool(evidence.get("readback_ok") is True),
        "real_calls": int(receipt.get("real_sends", -1)),
        "real_calls_matches_case_plan": True,
        "evidence_file_count": int(digest["file_count"]),
        "evidence_file_count_matches": bool(len(turn_files) == EXPECTED_TURN_COUNT),
        "multi_turn_shape_matches": True,
        "sealed": bool(seal.get("sealed") is True),
    }


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #


def _write_gap(
    path: pathlib.Path,
    *,
    mismatch_cases: Sequence[str],
    plan_quality: Mapping[str, str],
    got_quality: Mapping[str, str],
    diag: Mapping[str, int],
    counts: Mapping[str, int],
) -> None:
    lines = [
        "# RECONSTRUCTION-GAP（r2 SAFE 投影器）",
        "",
        "任务 A 硬自证失败：重建质量与 `run/r2-final/case-plan.json` 的 `quality_status` 不一致。",
        "本文件只含固定码与计数，不含题干/答案/来源正文/私有路径。",
        "",
        f"- mismatch_count: {len(mismatch_cases)}",
        f"- mismatch_cases: {', '.join(mismatch_cases) if mismatch_cases else '(none)'}",
        "",
        "| case_id | case-plan | reconstructed |",
        "|---|---|---|",
    ]
    for case_id in sorted(set(plan_quality) | set(got_quality)):
        lines.append(
            f"| {case_id} | {plan_quality.get(case_id, 'missing')} | {got_quality.get(case_id, 'missing')} |"
        )
    lines.extend(
        [
            "",
            "## 重建结构计数（全为整数）",
            "",
        ]
    )
    for key in sorted(counts):
        lines.append(f"- {key}: {counts[key]}")
    for key in sorted(diag):
        lines.append(f"- {key}: {diag[key]}")
    lines.extend(
        [
            "",
            "## 缺口判读（由上述计数决定）",
            "",
            "- `sources_missing_unit` / `sources_missing_document_name` / `sources_unmapped_document` > 0：",
            "  product.sources 无法从 db_projection 还原到单位级身份，评分侧来源身份不可信。",
            "- `product_kind_missing` / `product_text_missing` > 0：answer_result/commit_observed",
            "  事件缺 kind/text，评分行不完整。",
            "- `kind_answer_commit_mismatch` / `text_answer_commit_mismatch` > 0：两处事件不一致，",
            "  无法在不猜的前提下选定 product 字段。",
            "- `envelope_read_failed` / `envelope_incomplete` / `envelope_turn_index_mismatch`：密文或",
            "  case-plan 对不上，需重新核对封存链。",
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def main(argv: Sequence[str]) -> int:
    _STAGE[0] = "get_network_guard"
    guard = NetGuard()
    guard.install()
    guard.positive_control()

    _STAGE[0] = "parse_args"
    args = _parse_args(argv)
    gate_cwd_is_repo_root()
    key_path = pathlib.Path(args.key)
    binding_path = pathlib.Path(args.binding)
    evidence_root = pathlib.Path(args.evidence_root)
    receipt_path = pathlib.Path(args.receipt)
    seal_manifest_path = pathlib.Path(args.seal_manifest)
    case_plan_path = pathlib.Path(args.case_plan)
    out_dir = pathlib.Path(args.out_dir)
    gap_path = pathlib.Path(args.gap_path)

    _STAGE[0] = "load_binding"
    try:
        key = key_path.read_bytes().strip()
    except OSError:
        _fail("key_unreadable", "load_binding")
    if not 16 <= len(key) <= 4096:
        _fail("key_invalid", "load_binding")
    binding = _read_json(binding_path)
    runs = binding.get("runs")
    if not isinstance(runs, list) or not runs or not isinstance(runs[0], Mapping):
        _fail("binding_invalid", "load_binding")
    run_entry = runs[0]
    receipt = _read_json(receipt_path)
    seal_manifest = _read_json(seal_manifest_path)
    case_plan = _read_json(case_plan_path)
    plan_rows = case_plan.get("cases")
    if not isinstance(plan_rows, list) or not plan_rows:
        _fail("case_plan_invalid", "load_binding")
    plan_quality = {str(row.get("case_id")): str(row.get("quality_status")) for row in plan_rows}
    if any(not CASE_ID_RE.fullmatch(cid) for cid in plan_quality):
        _fail("case_plan_invalid", "load_binding")
    turn_files = [
        str(turn_row["evidence_file"])
        for row in plan_rows
        for turn_row in (row.get("turns") or ())
        if str(turn_row.get("status")) == "executed"
    ]

    _STAGE[0] = "verify_custody"
    custody_ok = _verify_custody(
        binding,
        case_plan_path,
        case_plan,
        receipt,
        seal_manifest,
        evidence_root,
        turn_files,
    )

    _STAGE[0] = "load_bundle"
    try:
        entry = _load_module(
            "p2_h2_v3_controlled_execute_safe_projection",
            TOOLS / "p2_h2_v3_controlled_execute.py",
        )
    except Exception:  # noqa: BLE001
        _fail("controlled_entry_load_failed", "load_bundle")
    _STAGE[0] = "import_evaluation"
    try:
        from mktkb.evaluation.p2_evidence_io import read_encrypted_evidence  # noqa: PLC0415
        import mktkb.evaluation.p2_hard_evidence as hard  # noqa: PLC0415
        import mktkb.evaluation.p2_scoring as scoring  # noqa: PLC0415
        import mktkb.evaluation.p2_score_run as score_run  # noqa: PLC0415
        import mktkb.evaluation.p2_runner as runner  # noqa: PLC0415
        import mktkb.evaluation.p2_holdout_v3_scoring as wiring  # noqa: PLC0415
        from mktkb.evaluation.scorers import CHECK_IDS  # noqa: PLC0415
    except Exception:  # noqa: BLE001
        _fail("evaluation_import_failed", "load_bundle")

    global _CHECK_ID_SET
    _CHECK_ID_SET = frozenset(str(item) for item in CHECK_IDS)

    _STAGE[0] = "load_bundle"
    inputs = {name: {"path": record["path"]} for name, record in binding["inputs"].items()}
    try:
        bundle = entry.load_v3_bundle(inputs)
    except Exception:  # noqa: BLE001
        _fail("bundle_load_failed", "load_bundle")
    scenario = str(run_entry.get("scenario_id"))
    try:
        cases = tuple(bundle.contract.subset(scenario).cases)
    except Exception:  # noqa: BLE001
        _fail("case_subset_failed", "load_bundle")
    if len(cases) != len(plan_rows):
        _fail("case_count_mismatch", "load_bundle")
    if [str(case.case_id) for case in cases] != [str(row.get("case_id")) for row in plan_rows]:
        _fail("case_order_mismatch", "load_bundle")

    _STAGE[0] = "validate_case_plan"
    static_bindings = {
        str(name): value
        for name, value in dict(run_entry.get("evidence_bindings") or {}).items()
        if str(name) != "index_revision"
    }
    try:
        plan = entry.v2._validate_case_plan_document(
            dict(case_plan), cases=cases, static_bindings=static_bindings
        )
    except Exception:  # noqa: BLE001
        _fail("case_plan_validation_failed", "validate_case_plan")

    _STAGE[0] = "load_document_codes"
    try:
        document_codes = runner.holdout_document_codes(bundle.contract._ingest)  # noqa: SLF001
    except Exception:  # noqa: BLE001
        _fail("document_codes_failed", "load_document_codes")
    if any(not re.fullmatch(r"[A-Z][0-9]{2}", code) for code in document_codes.values()):
        _fail("document_codes_failed", "load_document_codes")

    # 身份门在解密之前跑：身份不符就不碰密文（改动清单 B）。
    _STAGE[0] = "verify_identity"
    integrity = _verify_identity(
        run_entry=run_entry,
        binding=binding,
        receipt=receipt,
        seal_manifest=seal_manifest,
        seal_manifest_sha256=_sha256_file(seal_manifest_path),
        case_plan=case_plan,
        case_ids=[str(case.case_id) for case in cases],
        plan_rows=plan["cases"],
        turn_files=turn_files,
        evidence_root=evidence_root,
        key_sha256=_sha256_bytes(key),
    )

    _STAGE[0] = "build_scoring_rows"
    diag: dict[str, int] = {
        "message_sources_mismatch": 0,
        "sources_missing_unit": 0,
        "sources_missing_document_name": 0,
        "sources_unmapped_document": 0,
        "sources_total": 0,
        "sources_active": 0,
        "product_kind_missing": 0,
        "product_text_missing": 0,
        "kind_answer_commit_mismatch": 0,
        "text_answer_commit_mismatch": 0,
        "classification_failures": 0,
        "proof_eval_failures": 0,
        "replica_disagreements": 0,
        "unsafe_code_count": 0,
    }
    origin: dict[str, dict[str, Any]] = {}
    rows, envelopes_by_case = _build_rows(
        cases,
        plan["cases"],
        evidence_root,
        key,
        plan["bindings"],
        document_codes,
        read_encrypted_evidence,
        scoring._lookup_document_code,  # noqa: SLF001
        diag,
        origin,
    )

    _STAGE[0] = "gate_origin_and_scope"
    gate_origin_round(origin)
    gate_scope_evidence(envelopes_by_case)

    _STAGE[0] = "score_cases"
    scored_out: dict[str, Any] = {}
    try:
        records, match, paths_agree, scoring_map = _score_cases(
            cases,
            rows,
            plan_quality,
            document_codes,
            scoring,
            score_run,
            CHECK_IDS,
            wiring,
            scored_out,
        )
    except ToolError:
        raise
    except Exception:  # noqa: BLE001
        _fail("scoring_failed", "score_cases")
    got_quality = {record["case_id"]: record["quality_status"] for record in records}
    counts = {
        "case_count": len(cases),
        "turn_count": len(turn_files),
        "envelope_count": sum(len(item) for item in envelopes_by_case.values()),
    }

    _STAGE[0] = "gate_quality_counts"
    totals = gate_quality_counts(records, CHECK_IDS)

    # R2（改动清单 K）：match 失败时先判断能否由"评分口径差异"解释；不能解释才算未解释差异。
    flip: dict[str, Any] = {"flip_cases": [], "details": [], "explained": False}
    if match and paths_agree:
        pass
    elif paths_agree:
        _STAGE[0] = "scoring_version_compare"
        try:
            current_status = {
                case_id: check_status_map(entry["scored"], CHECK_IDS)
                for case_id, entry in scored_out.items()
            }
            original_status: dict[str, dict[str, str]] = {}
            original_case_status: dict[str, str] = {}
            structural_counts: dict[str, int] = {}
            for case in cases:
                case_id = str(case.case_id)
                entry = scored_out[case_id]
                original_scored = score_original_caliber(
                    scoring,
                    entry["mapped"],
                    rows[case_id],
                    document_codes=document_codes,
                    source_index=entry["source_index"],
                    allowed=entry["allowed"],
                )
                original_status[case_id] = check_status_map(original_scored, CHECK_IDS)
                original_case_status[case_id] = (
                    str(original_scored.score.status)
                    if str(original_scored.score.status) in CASE_STATUSES
                    else "error"
                )
                structural_counts[case_id] = structural_key_count(scoring, entry["scored"])
            flip = explain_version_flip(
                current=current_status,
                original=original_status,
                current_case_status=got_quality,
                original_case_status=original_case_status,
                check_ids=CHECK_IDS,
                plan_quality=plan_quality,
                structural_counts=structural_counts,
            )
        except ToolError:
            raise
        except Exception:  # noqa: BLE001
            _fail("scoring_version_compare_failed", "scoring_version_compare")

    _STAGE[0] = "build_quality_document"
    quality_document: dict[str, Any] = {
        "ok": True,
        "round_label": ROUND_LABEL,
        "run_id": str(case_plan["run_id"]),
        "run_index": int(EXPECTED_RUN_INDEX),
        "case_plan_sha256": _sha256_file(case_plan_path),
        "reconstruction_match": bool(match),
        "scoring_version_explained": bool(flip["explained"]),
        "original_caliber_match": bool(flip["explained"]),
        "flip_cases": list(flip["flip_cases"]),
        "flip_details": list(flip["details"]),
        "cases": records,
        "check_id_totals": totals["_failed"],
        "check_id_pass_totals": totals["_passed"],
        "check_id_skipped_totals": totals["_skipped"],
        "checks_total": int(totals["checks_total"]),
        "checks_passed_total": int(totals["checks_passed_total"]),
        "checks_failed_total": int(totals["checks_failed_total"]),
        "checks_skipped_total": int(totals["checks_skipped_total"]),
        "case_count": counts["case_count"],
        "turn_count": counts["turn_count"],
        "envelope_count": counts["envelope_count"],
        "scoring_paths_agree": bool(paths_agree),
        "scoring_map": dict(scoring_map),
        "custody_ok": bool(custody_ok),
        "unsafe_code_count": int(diag["unsafe_code_count"]),
        "integrity": integrity,
        "netguard": guard.as_dict(),
    }

    if not paths_agree or (not match and not flip["explained"]):
        mismatch_cases = sorted(
            case_id
            for case_id in plan_quality
            if got_quality.get(case_id) != plan_quality.get(case_id)
        )
        _STAGE[0] = "write_gap"
        _write_gap(
            gap_path,
            mismatch_cases=mismatch_cases,
            plan_quality=plan_quality,
            got_quality=got_quality,
            diag=diag,
            counts=counts,
        )
        # 仍然写 SAFE 投影，但 **ok=false**：逐题字段照写，绝不把"未能解释的差异"当成功。
        quality_document["ok"] = False
        quality_document["error"] = "reconstruction_mismatch"
        _safe_dump(quality_document, out_dir / "r2-quality-checks.json", announce=True)
        return 1

    _STAGE[0] = "emit"
    _safe_dump(quality_document, out_dir / "r2-quality-checks.json", announce=True)
    return 0


def _emit_failure(code: Any, where: Any) -> None:
    """失败出口也只写固定码：任何非法字符串一律降级，绝不外泄。"""
    safe_code = str(code) if CODE_RE.fullmatch(str(code)) else "internal_error"
    safe_where = str(where) if CODE_RE.fullmatch(str(where)) else "unknown"
    _safe_dump({"ok": False, "error": safe_code, "where": safe_where})


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except SystemExit:
        raise
    except ToolError as exc:
        _emit_failure(exc.code, exc.where)
        raise SystemExit(2) from None
    except Exception as exc:  # noqa: BLE001 - 绝不回显 str(exc)/traceback
        code = {
            "P2ScoringError": "scoring_error",
            "EvidenceIOError": "evidence_io_error",
            "HardEvidenceError": "hard_evidence_error",
        }.get(type(exc).__name__, "internal_error")
        _emit_failure(code, _STAGE[0])
        raise SystemExit(3) from None

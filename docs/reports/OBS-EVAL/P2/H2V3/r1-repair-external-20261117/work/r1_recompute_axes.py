"""r0 修复版四轴重算：初判卡改为**本轮**冻结分类器结果（另存；不改原件）。

与 ``fullverify-20261116/work/recompute_axes_fullverify.py`` 的差异（只在这些点）：

1. **D1 同轮初判**：不再把 ``compose/evidence/recompute-four-runs.json`` 的历史卡当本轮初判。
   每个 run 先走真实 run 路径
   ``tools/p2_h2_controlled_execute.py::_recompute_loaded`` →
   ``p2_hard_evidence.recompute_hard_evidence`` → ``classify_case_evidence``，
   再用本轮 ``CaseEvidenceResult`` 经 ``r0_same_round.build_current_card`` 构造初判卡。
2. **来源证明**：``r0_same_round.card_origin_record`` 逐字段记录原始来源对象与轮次；
   ``assert_same_round`` 在身份/tree/case 集合/来源缺失/历史来源时终止。
   ``RescoreIdentity`` 的每个哈希都同时记录其来源对象（见 ``identity_provenance``）；
   历史卡字节与摘要只出现在 ``historical_*`` 对照字段。
3. **D2 逐题质量**：输出 ``quality_status / evidence_complete / missing_codes`` 取本轮卡；
   历史值另存为 ``historical_*`` 且不参与本轮门状态。
4. **D3/§5 一致性**：聚合后调用 ``r0_same_round.check_consistency``；不通过即不写成功产物。

调用方式（为什么不传 scope_contract）
------------------------------------
真实 run 路径**没有**构造/传入 ``scope_contract``：

- ``tools/p2_h2_controlled_execute.py:3125-3127``：``recompute_hard_evidence(..., plan_meta=plan_meta)``；
- ``backend/src/mktkb/evaluation/p2_hard_evidence.py:3681,3688``：``scope_contract`` 默认 ``None``；
- 历史生产路径 ``docs/reports/OBS-EVAL/P2/H2V3/compose/evidence/recompute_four_runs.py:64-74``
  同样只经 ``_recompute_loaded``。

因此本脚本显式**不**从 annotation 另造 scope contract（那会改变 cross_entity 判据）。
捕获包装只观察 ``recompute_hard_evidence`` 的返回值并在 ``finally`` 还原，不改变行为。

输出
----
默认写 ``r0-repair-external-20261116/work/out/recompute-v2-r0-repair.json``；
``--out`` 可改到仓外受控位置。绝不覆盖 ``fullverify-20261116/evidence/recompute-v2.json``。

修复后一轮（r0fix-20261116）适配：CLI 化，默认行为不变
------------------------------------------------------
新增参数，**默认值与旧行为逐项相同**（不传即复现原路径）：

- ``--work <根>``：旧 ``WORK``（四 run 私有输出根）。若该根下没有 ``r0/`` 但自身就是
  单 run 根（含 ``out/controlled/case-plan.json``），则直接当作 run0 根（见
  ``_resolve_run_dir``），便于把“新运行根”原样传入。
- ``--bindings <目录>``：旧写死的 binding 目录。
- ``--runs 0``：逗号分隔的 run_index 子集；默认仍是四个 run 全跑。
- ``--out <文件>``：原样保留。
- ``--compat p2-refusal-compat/v0.3``：默认 ``v0.1``（旧判据）。显式给出时，
  ``classify_case_evidence`` **显式**收到该 ``compat``（经由 ``_compat_scope``
  对模块名的包装，``finally`` 必还原，且调用次数必须等于题数，否则 fail closed）。
  第三轮起 ``--compat`` 增加 ``p2-refusal-compat/v0.4``（v0.4 继承 v0.3，另窄放行
  「检索到但未使用」）；**默认值仍是 v0.1**，不传参行为逐项不变。
- ``--compat p2-refusal-compat/v0.5``（第四轮起）：v0.5 继承 v0.4，另**只**放行
  「投影 ``units`` 逐值镜像检索层」（``_projection_mirror_relaxable``）；v0.1/v0.3/v0.4
  的逐值结果不变。**默认值仍是 v0.1**。

另加：socket/urllib/httpx 出站阻断 + 正对照（``NetGuard``，计数进 ``netguard``）；
逐题 ``quality_status`` 与 case-plan 的逐题值逐项比对（不等即 ``quality_case_plan_mismatch``）；
顶层固定码失败出口（只输出 ``{"ok":false,"error","where"}``，不回显异常正文）。
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import importlib.util
import json
import pathlib
import re
import socket
import sys
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

REPO = pathlib.Path(r"D:\GPT项目\市场部AI知识库")
WORK = pathlib.Path(r"D:\mktkb-p2-h2v3-fullverify-20261116")
BINDINGS = pathlib.Path(
    r"D:\mktkb-p2-h2v3-20261115\custody-plan-20261116-single-01\bindings"
)
RUN_DIR_NAMES = {0: "r0", 1: "r1", 2: "r2", 3: "r3"}
KEY_PATH = pathlib.Path(r"D:\mktkb-p2-h2v3-20261115\runs3\ev.key")
CODE_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
SCHEMA_VERSION = "p2-h2v3-axes-v2-recompute/v0.2-r0-same-round"
DEFAULT_OUT = (
    REPO
    / "docs/reports/OBS-EVAL/P2/H2V3/r0-repair-external-20261116/work/out"
    / "recompute-v2-r0-repair.json"
)
PROTECTED_OUT = (
    REPO / "docs/reports/OBS-EVAL/P2/H2V3/fullverify-20261116/evidence/recompute-v2.json"
)
PROTECTED_OUTPUTS = (
    PROTECTED_OUT,
    REPO / "docs/reports/OBS-EVAL/P2/H2V3/fullverify-20261116/evidence/quality-per-run.json",
    REPO / "docs/reports/OBS-EVAL/P2/H2V3/fullverify-20261116/run/final-summary.json",
)
WORK_DIR = pathlib.Path(__file__).resolve().parent
#: 原脚本（只读）位置：辅助投影/聚合函数直接复用，保证与历史产物的判据逐字节一致。
BASE_SCRIPT = (
    REPO
    / "docs/reports/OBS-EVAL/P2/H2V3/fullverify-20261116/work/recompute_axes_fullverify.py"
)


def _load_module(name: str, path: pathlib.Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"module_not_loadable:{path.name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


#: 原脚本只读复用：辅助投影/聚合函数与原实现逐字节一致，避免“修一处、判据漂移另一处”。
base = _load_module("r0_fullverify_base", BASE_SCRIPT)
#: 本轮的纯适配/来源/一致性模块（无 IO）。
S = _load_module("r0_same_round", WORK_DIR / "r0_same_round.py")

rescore = base.rescore
rescore_axes = base.rescore_axes
hard = base.hard
ENTRY = base.ENTRY

#: v0.5（第四轮）：分类器已登记 ``REFUSAL_COMPAT_V0_5``。缺失时**不**退回 v0.4，
#: 而是让 ``--compat`` 选项本身不可用（缺档即显式拒绝，避免静默降档）。
V05: str | None = getattr(hard, "REFUSAL_COMPAT_V0_5", None)
#: R1/T-R1-108：v0.6（纯文档回合 cross_entity N/A）。缺失时**不**退回 v0.5。
V06: str | None = getattr(hard, "REFUSAL_COMPAT_V0_6", None)

HISTORICAL_SOURCE = "compose/evidence/recompute-four-runs.json#runs[i].card"
SCOPE_CONTRACT_SOURCE = (
    "tools/p2_h2_controlled_execute.py:3125 -> "
    "p2_hard_evidence.py:3688 (scope_contract is not passed; default None)"
)


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha256_file(path: pathlib.Path) -> str:
    return sha256_bytes(path.read_bytes())


# --------------------------------------------------------------------------- #
# 网络阻断（socket / urllib / httpx）+ 正对照
# --------------------------------------------------------------------------- #


class NetGuardFailed(RuntimeError):
    """正对照未被阻断：只带固定码。"""


class NetGuard:
    """在 socket 原语层阻断出站；所有尝试只计数，不连接。"""

    def __init__(self) -> None:
        self.blocked = 0
        self.positive_control_attempts = 0
        self.installed = False

    def _refuse(self, *_args: Any, **_kwargs: Any) -> Any:
        self.blocked += 1
        raise OSError("netguard_blocked")

    def install(self) -> None:
        if self.installed:
            return
        socket.socket.connect = self._refuse  # type: ignore[method-assign]
        socket.socket.connect_ex = self._refuse  # type: ignore[method-assign]
        urllib.request.urlopen = self._refuse  # type: ignore[assignment]
        try:  # httpx 若已导入则一并封死传输层；未导入不会触发。
            import httpx  # noqa: PLC0415

            httpx.HTTPTransport.handle_request = self._refuse  # type: ignore[method-assign]
            httpx.AsyncHTTPTransport.handle_async_request = self._refuse  # type: ignore[method-assign]
        except Exception:  # noqa: BLE001 - 没有 httpx 就不是出站面
            pass
        self.installed = True

    def positive_control(self) -> None:
        """尝试两条必然被阻断的出站路径；没被阻断就说明 guard 失效。"""
        for attempt in (
            lambda: socket.create_connection(("127.0.0.1", 9), timeout=0.05),
            lambda: urllib.request.urlopen("http://127.0.0.1:9/", timeout=0.05),
        ):
            self.positive_control_attempts += 1
            try:
                attempt()
            except OSError:
                continue
            raise NetGuardFailed("netguard_positive_control_failed")

    def as_dict(self) -> dict[str, Any]:
        return {
            "blocked_attempts": int(self.blocked),
            "positive_control_attempts": int(self.positive_control_attempts),
            "positive_control_blocked": bool(
                self.positive_control_attempts == 2 and self.blocked >= 2
            ),
            "outbound_allowed": 0,
        }


# --------------------------------------------------------------------------- #
# compat 注入：让 classify_case_evidence 显式收到 --compat
# --------------------------------------------------------------------------- #


class _CompatScope:
    """把模块级 ``classify_case_evidence`` 包装成“显式带 ``compat``”的版本。

    ``recompute_hard_evidence`` 是按模块全局名调用它的，因此包装模块属性即可生效；
    ``finally`` 必还原。``calls`` 必须等于题数——少一次就说明调用没经过包装
    （例如别处直接 import 了函数），此时宁可 fail closed 也不静默退回旧 compat。
    """

    def __init__(self, compat: str) -> None:
        self.compat = str(compat)
        self.calls = 0
        self._original: Any = None

    def __enter__(self) -> "_CompatScope":
        self._original = hard.classify_case_evidence
        scope = self

        def _wrapped(*args: Any, **kwargs: Any) -> Any:
            kwargs.pop("compat", None)
            scope.calls += 1
            return scope._original(*args, compat=scope.compat, **kwargs)

        hard.classify_case_evidence = _wrapped
        return self

    def __exit__(self, *exc_info: Any) -> bool:
        hard.classify_case_evidence = self._original
        self._original = None
        return False


#: 空集证明 / 无事实模板判据 / 跨层 kind 映射都封在 ``_empty_use_scope_proof`` 内部：
#: ``_matches_product_no_fact_template``（模板族）与 ``REFUSAL_KIND_CROSS_LAYER_MAP``
#: （跨层 kind）都只按它收到的 ``compat`` 生效。两条 case 级构建路径
#: （``build_cross_entity_case_level`` / ``build_stale_case_level``）默认按 v0.1 调它，
#: 所以「初判用 v0.3、四轴用 v0.1」会形成旁路；必须显式注入同一档。
EMPTY_SCOPE_PRIMITIVE = "_empty_use_scope_proof"


class _EmptyScopeCompatScope:
    """把 ``compat`` 显式注入 ``hard._empty_use_scope_proof``；不改默认值，可还原。

    只接管这次调用的关键字参数：调用点若自带不同档，直接 fail closed
    （``compat_conflict_at_call_site``），不静默覆盖。
    """

    def __init__(self, compat: str) -> None:
        self.compat = str(compat)
        self.calls = 0
        self.restored = False
        self._original: Any = None

    def __enter__(self) -> "_EmptyScopeCompatScope":
        scope = self
        original = getattr(hard, EMPTY_SCOPE_PRIMITIVE)
        self._original = original

        def _wrapped(evidence: Any, *args: Any, **kwargs: Any) -> Any:
            explicit = kwargs.get("compat")
            if explicit is not None and str(explicit) != scope.compat:
                raise FixedCode("compat_conflict_at_call_site", "empty_scope_compat")
            kwargs["compat"] = scope.compat
            scope.calls += 1
            return original(evidence, *args, **kwargs)

        setattr(hard, EMPTY_SCOPE_PRIMITIVE, _wrapped)
        return self

    def __exit__(self, *exc_info: Any) -> bool:
        restored_to = self._original
        setattr(hard, EMPTY_SCOPE_PRIMITIVE, restored_to)
        self.restored = getattr(hard, EMPTY_SCOPE_PRIMITIVE) is restored_to
        self._original = None
        return False


def _build_scope_views(
    *,
    envelopes: Sequence[Mapping[str, Any]],
    units: Sequence[Any],
    vs: Mapping[str, Any],
    compat: str,
    counters: dict[str, int],
    with_control: bool,
) -> tuple[Any, Any, dict[str, Any] | None]:
    """在 ``compat`` 注入下构建 cross_entity / stale_source 两个 case 级视图。

    ``with_control=True`` 时再用同一路径、显式 v0.1 构建一次（结果丢弃），
    用「同调用点、不同档」的对照证明注入确实生效：若注入没有透传，
    两列会逐案相等，审查者一眼可见。
    """
    entity_scope = _EmptyScopeCompatScope(compat)
    with entity_scope:
        entity_view = base.build_cross_entity_case_level(envelopes, units, vs)
    stale_scope = _EmptyScopeCompatScope(compat)
    with stale_scope:
        stale_view = base.build_stale_case_level(envelopes, units)
    if not (entity_scope.restored and stale_scope.restored):
        raise RuntimeError("compat_scope_not_restored")
    counters["cross_entity"] = counters.get("cross_entity", 0) + entity_scope.calls
    counters["stale_source"] = counters.get("stale_source", 0) + stale_scope.calls

    if not with_control:
        return entity_view, stale_view, None

    control_entity_scope = _EmptyScopeCompatScope(hard.REFUSAL_COMPAT_V0_1)
    with control_entity_scope:
        control_entity = base.build_cross_entity_case_level(envelopes, units, vs)
    control_stale_scope = _EmptyScopeCompatScope(hard.REFUSAL_COMPAT_V0_1)
    with control_stale_scope:
        control_stale = base.build_stale_case_level(envelopes, units)
    if not (control_entity_scope.restored and control_stale_scope.restored):
        raise RuntimeError("compat_scope_not_restored")
    counters["control_cross_entity"] = (
        counters.get("control_cross_entity", 0) + control_entity_scope.calls
    )
    counters["control_stale_source"] = (
        counters.get("control_stale_source", 0) + control_stale_scope.calls
    )
    if (
        entity_scope.calls != control_entity_scope.calls
        or stale_scope.calls != control_stale_scope.calls
    ):
        # 同调用点必须同次数；不同就说明注入改变了调用路径本身，不可作为对照。
        raise RuntimeError("compat_control_call_site_mismatch")
    proof = {
        "injected_compat": str(compat),
        "injected_calls": {
            "cross_entity": entity_scope.calls,
            "stale_source": stale_scope.calls,
        },
        "control_compat": hard.REFUSAL_COMPAT_V0_1,
        "control_calls": {
            "cross_entity": control_entity_scope.calls,
            "stale_source": control_stale_scope.calls,
        },
        "empty_scope_proven": {
            "injected": {
                "cross_entity": entity_view.empty_scope_proven,
                "stale_source": stale_view.empty_scope_proven,
            },
            "control_v0_1": {
                "cross_entity": control_entity.empty_scope_proven,
                "stale_source": control_stale.empty_scope_proven,
            },
        },
    }
    return entity_view, stale_view, proof


# --------------------------------------------------------------------------- #
# CLI 解析：run 子集与运行根
# --------------------------------------------------------------------------- #


def _parse_runs(text: str) -> list[int]:
    """``--runs 0`` / ``--runs 0,2``；空串=全部（默认行为不变）。"""
    if text is None or not str(text).strip():
        return sorted(RUN_DIR_NAMES)
    picked: list[int] = []
    for item in str(text).split(","):
        token = item.strip()
        if not token:
            raise RuntimeError("runs_argument_invalid")
        try:
            value = int(token)
        except ValueError:
            raise RuntimeError("runs_argument_invalid") from None
        if value not in RUN_DIR_NAMES:
            raise RuntimeError("runs_argument_invalid")
        if value in picked:
            raise RuntimeError("runs_argument_duplicate")
        picked.append(value)
    if not picked:
        raise RuntimeError("runs_argument_invalid")
    return picked


def _resolve_run_dir(work: pathlib.Path, run_index: int) -> pathlib.Path:
    """旧布局 ``work/r0`` 优先；否则把 work 本身当单 run 根；都没有就 fail closed。"""
    nested = work / RUN_DIR_NAMES[run_index]
    if (nested / "out" / "controlled" / "case-plan.json").is_file():
        return nested
    if (work / "out" / "controlled" / "case-plan.json").is_file():
        return work
    raise RuntimeError("run_root_not_found")


def _binding_for(run_index: int, bindings_dir: pathlib.Path) -> Mapping[str, Any]:
    name = {index: label for label, index in base.SCENARIOS}.get(run_index)
    if name is None:
        raise RuntimeError("binding_name_unknown")
    path = bindings_dir / name
    if not path.is_file():
        raise RuntimeError("binding_file_missing")
    return json.loads(path.read_text(encoding="utf-8"))


class FixedCode(RuntimeError):
    """带固定码的失败；``code`` 可直接进报告，绝不携带异常正文。"""

    def __init__(self, code: str, where: str) -> None:
        super().__init__(code)
        self.code = str(code)
        self.where = str(where)


#: v2 脚本依赖的 binding 身份字段：缺一个就 fail closed（不伪造、不回填）。
BINDING_REQUIRED_TOP = ("business_date", "config_sha256")
BINDING_REQUIRED_RUN = ("plan_file", "plan_file_sha256", "business_date", "run_id", "scenario_id")


def _binding_preflight(binding: Mapping[str, Any], run_entry: Mapping[str, Any]) -> dict[str, Any]:
    """逐项核对 binding 身份字段；缺字段时报固定码并点名是哪一个。"""
    if not isinstance(binding, Mapping):
        raise FixedCode("binding_invalid", "binding_preflight")
    for name in BINDING_REQUIRED_TOP:
        value = binding.get(name)
        if not isinstance(value, str) or not value.strip():
            raise FixedCode(f"binding_field_missing_{name}", "binding_preflight")
    for name in BINDING_REQUIRED_RUN:
        value = run_entry.get(name)
        if not isinstance(value, str) or not value.strip():
            raise FixedCode(f"binding_field_missing_{name}", "binding_preflight")
    plan_file = pathlib.Path(str(run_entry["plan_file"]))
    if not plan_file.is_file():
        raise FixedCode("binding_plan_file_unreadable", "binding_preflight")
    return {
        "plan_file_sha256": str(run_entry["plan_file_sha256"]),
        "business_date": str(binding["business_date"]),
        "run_business_date": str(run_entry["business_date"]),
        "config_sha256": str(binding["config_sha256"]),
    }


def current_round_results(
    *,
    document: Mapping[str, Any],
    run_entry: Mapping[str, Any],
    plan: Any,
    cases: Sequence[Any],
    annotation: Any,
    case_plan_payload: Mapping[str, Any],
    evidence_dir: pathlib.Path,
    key: bytes,
    receipt: Mapping[str, Any],
    compat: str,
) -> tuple[list[Any], dict[str, Any], tuple[Mapping[str, Any], ...], int]:
    """走真实 run 路径取得本轮 ``CaseEvidenceResult`` 列表、已验证卡与同一批 audits。

    包装只捕获输入/返回值（pass-through），``finally`` 必还原；不改变
    ``recompute_hard_evidence`` 的行为，也不向其传 ``scope_contract``。
    捕获的 audits 与分类器实际使用的是同一对象，后续 turn 投影不再重复解密/重建。
    ``compat`` 期间包装 ``classify_case_evidence``，第四个返回值是实际带 compat 的调用次数。
    """
    captured: dict[str, Any] = {}
    original = hard.recompute_hard_evidence

    def _capture(cases_arg: Any, annotation_arg: Any, audits_arg: Any, **kwargs: Any) -> Any:
        card, results = original(cases_arg, annotation_arg, audits_arg, **kwargs)
        captured["results"] = tuple(results)
        captured["card"] = card
        captured["audits"] = tuple(audits_arg)
        captured["kwargs"] = dict(kwargs)
        return card, results

    hard.recompute_hard_evidence = _capture
    try:
        with _CompatScope(compat) as compat_scope:
            loaded = ENTRY.v2._recompute_loaded(
                document=document,
                run_entry=run_entry,
                plan=plan,
                cases=tuple(cases),
                annotation=annotation,
                case_plan_payload=case_plan_payload,
                evidence_dir=evidence_dir,
                key=key,
                receipt=receipt,
            )
    finally:
        hard.recompute_hard_evidence = original

    if "results" not in captured or "card" not in captured or "audits" not in captured:
        raise RuntimeError("current_round_capture_missing")
    if compat_scope.calls != len(cases):
        # 包装没生效（或调用次数不符）：不静默退回旧 compat。
        raise RuntimeError("current_round_compat_not_applied")
    if captured["kwargs"].get("scope_contract") is not None:
        # 真实路径没有 scope_contract；出现即说明 run 路径变了，宁可停止也不静默吞掉。
        raise RuntimeError("current_round_scope_contract_unexpected")
    results = list(captured["results"])
    card = captured["card"]
    expected_ids = [str(case.case_id) for case in cases]
    got_ids = [str(item.case_id) for item in results]
    if got_ids != expected_ids:
        raise RuntimeError("current_round_case_set_mismatch")
    validated = hard.validate_hard_evidence_scorecard(
        card,
        total=len(cases),
        run_id=str(run_entry["run_id"]),
        config_hash=str(document["config_sha256"]),
        expected_strata=dict(case_plan_payload["expected_strata"]),
    )
    if dict(validated) != dict(card):
        raise RuntimeError("current_round_card_readback_mismatch")
    if str(loaded.get("run_id")) != str(run_entry["run_id"]):
        raise RuntimeError("current_round_run_id_mismatch")
    return results, dict(card), tuple(captured["audits"]), int(compat_scope.calls)


def _axis_counts(rows: Sequence[Mapping[str, Any]], selector: str) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for axis in base.AXES:
        counts = {
            "planned": len(rows),
            "passed": 0,
            "not_applicable": 0,
            "unknown": 0,
            "violations": 0,
        }
        for row in rows:
            state = str(row[selector][axis]["state"])
            counts["violations" if state == "violation" else state] += 1
        counts["checked"] = counts["passed"] + counts["not_applicable"] + counts["violations"]
        out[axis] = counts
    return out


def _case_detail(
    records: Sequence[Mapping[str, Any]],
    case_id: str,
    initial_hard: Sequence[str],
    new_hard: Sequence[str],
) -> dict[str, Any]:
    row = next((item for item in records if item["case_id"] == case_id), None)
    if row is None:
        return {"present": False}
    return {
        "present": True,
        "case_id": row["case_id"],
        "run_index": row["run_index"],
        "scenario_id": row["scenario_id"],
        "quality_status": row["quality_status"],
        "initial_safety": dict(row["initial_axes"]["safety"]),
        "historical_safety": dict(row["historical_axes"]["safety"]),
        "new_safety": {
            "state": row["new_axes"]["safety"]["state"],
            "reason": row["new_axes"]["safety"]["reason"],
            "provenance": row["new_axes"]["safety"]["provenance"],
        },
        "new_axes": {
            axis: {
                "state": row["new_axes"][axis]["state"],
                "reason": row["new_axes"][axis]["reason"],
                "provenance": row["new_axes"][axis]["provenance"],
            }
            for axis in base.AXES
        },
        "safety_provenance": row["safety_provenance"],
        "safety_audit_codes": row["safety_audit_codes"],
        "initial_in_hard_failures": case_id in initial_hard,
        "new_in_hard_failures": case_id in new_hard,
        "changed_axes": row["changed_axes"],
        "historical_changed_axes": row["historical_changed_axes"],
    }


def _empty_scope_summary(
    counters: Mapping[str, int],
    proofs: Mapping[str, Mapping[str, Any] | None],
) -> dict[str, Any]:
    """把两条 case 级路径的注入计数与「v0.1 对照」差异压成自证块。

    ``flip_cases``：v0.3 证明为 True 且 v0.1 对照为 False 的题——注入生效的直接证据。
    """
    injected = {
        "cross_entity": int(counters.get("cross_entity", 0)),
        "stale_source": int(counters.get("stale_source", 0)),
    }
    control = {
        "cross_entity": int(counters.get("control_cross_entity", 0)),
        "stale_source": int(counters.get("control_stale_source", 0)),
    }
    flip: list[str] = []
    regress: list[str] = []
    for case_id in sorted(proofs):
        proof = proofs[case_id]
        if not proof:
            continue
        left = proof["empty_scope_proven"]["injected"]
        right = proof["empty_scope_proven"]["control_v0_1"]
        for axis in ("cross_entity", "stale_source"):
            if bool(left[axis]) and not bool(right[axis]):
                flip.append(case_id)
                break
        for axis in ("cross_entity", "stale_source"):
            if bool(right[axis]) and not bool(left[axis]):
                regress.append(case_id)
                break
    return {
        "primitive": EMPTY_SCOPE_PRIMITIVE,
        "path": "r0_same_round.builder -> build_cross_entity_case_level / build_stale_case_level",
        "injected_calls": injected,
        "control_calls": control,
        "call_sites_equal": injected == control,
        "injected_calls_total": injected["cross_entity"] + injected["stale_source"],
        "proven_true_cases": sorted(
            case_id
            for case_id, proof in proofs.items()
            if proof
            and any(
                bool(proof["empty_scope_proven"]["injected"][axis])
                for axis in ("cross_entity", "stale_source")
            )
        ),
        "flip_cases_vs_v0_1": sorted(set(flip)),
        "regress_cases_vs_v0_1": sorted(set(regress)),
        "restored_after_each_build": True,
    }


def run(argv: Sequence[str] | None = None, *, guard: NetGuard | None = None) -> int:
    parser = argparse.ArgumentParser(description="r0 same-round axes recompute (v2)")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="输出 JSON 路径（不得覆盖旧 recompute-v2.json）")
    parser.add_argument("--overwrite", action="store_true", help="允许覆盖已存在的本脚本输出")
    parser.add_argument(
        "--work",
        default=str(WORK),
        help="run 私有输出根（旧布局 <根>/r0..；也接受本身就是单 run 根）",
    )
    parser.add_argument(
        "--bindings",
        default=str(BINDINGS),
        help="binding 目录（run0-base_b0.binding.json 等）",
    )
    parser.add_argument(
        "--runs",
        default="",
        help="逗号分隔的 run_index；默认四个 run（旧行为不变）",
    )
    parser.add_argument(
        "--compat",
        default=hard.REFUSAL_COMPAT_V0_1,
        choices=[
            hard.REFUSAL_COMPAT_V0_1,
            hard.REFUSAL_COMPAT_V0_3,
            hard.REFUSAL_COMPAT_V0_4,
            *([V05] if V05 is not None else ()),
        *([V06] if V06 is not None else ()),
        ],
        help="classify_case_evidence 的拒答兼容档；默认 v0.1（旧判据）",
    )
    args = parser.parse_args(argv)
    selected_runs = _parse_runs(args.runs)
    work = pathlib.Path(args.work)
    bindings_dir = pathlib.Path(args.bindings)
    compat = str(args.compat)
    target = pathlib.Path(args.out)
    if target.resolve() in {path.resolve() for path in PROTECTED_OUTPUTS}:
        raise SystemExit("refuse_to_overwrite_protected_output")
    if target.exists() and not args.overwrite:
        raise SystemExit("output_already_exists")

    vs = base.load_version_sources()
    base.CURRENT_VS = vs
    v1 = json.loads(base.V1_RESULTS.read_text(encoding="utf-8"))
    v1_by_run = {int(item["run_index"]): item for item in v1["runs"]}

    key = KEY_PATH.read_bytes().strip()
    v0_1_sha = sha256_file(base.V0_1_CONTRACT)
    v0_2_sha = sha256_file(base.V0_2_CONTRACT)
    rescore_sha = sha256_file(REPO / "backend/src/mktkb/evaluation/p2_evidence_rescore.py")
    axes_sha = sha256_file(REPO / "backend/src/mktkb/evaluation/p2_evidence_rescore_axes.py")
    classifier_sha = sha256_file(REPO / "backend/src/mktkb/evaluation/p2_hard_evidence.py")
    same_round_sha = sha256_file(WORK_DIR / "r0_same_round.py")

    runs_out: list[dict[str, Any]] = []
    case_records: list[dict[str, Any]] = []
    for run_index in selected_runs:
        run_dir = _resolve_run_dir(work, run_index)
        binding = _binding_for(run_index, bindings_dir)
        inputs = {name: {"path": record["path"]} for name, record in binding["inputs"].items()}
        bundle = ENTRY.load_v3_bundle(inputs)
        run_entry = binding["runs"][0]
        if int(run_entry["run_index"]) != run_index:
            raise RuntimeError("binding_run_index_mismatch")
        binding_fields = _binding_preflight(binding, run_entry)
        run_id = str(run_entry["run_id"])
        scenario = str(run_entry["scenario_id"])
        cases = tuple(bundle.contract.subset(scenario).cases)
        case_plan_payload = json.loads(
            (run_dir / "out" / "controlled" / "case-plan.json").read_text(encoding="utf-8")
        )
        static_bindings = {
            name: value
            for name, value in dict(run_entry["evidence_bindings"]).items()
            if name != "index_revision"
        }
        plan_doc = ENTRY.v2._validate_case_plan_document(
            case_plan_payload, cases=cases, static_bindings=static_bindings
        )
        plan = ENTRY.v2._load_plan_for_run(binding, run_entry)
        root = run_dir / "evidence" / run_id
        receipt = json.loads(
            (run_dir / "seal" / run_id / "run-receipt.json").read_text(encoding="utf-8")
        )
        business_date = str(receipt["business_date"])
        if business_date != str(case_plan_payload.get("run_binding", {}).get("business_date")):
            raise RuntimeError("business_date_mismatch")
        if business_date != binding_fields["business_date"]:
            raise RuntimeError("binding_business_date_mismatch")
        if str(receipt.get("run_id")) != run_id:
            raise RuntimeError("receipt_run_id_mismatch")
        evidence_tree_sha = str(receipt["seal"]["evidence_tree_sha256"])
        if "plan_sha256" not in receipt:
            raise FixedCode("receipt_field_missing_plan_sha256", "receipt_preflight")
        if str(receipt.get("plan_sha256")) != str(run_entry.get("plan_sha256")):
            raise RuntimeError("receipt_plan_sha256_mismatch")
        plan_id = str(plan.plan_id)
        plan_sha = str(plan.plan_sha256)
        if str(plan_doc["bindings"]["plan_id"]) != plan_id or str(plan_doc["bindings"]["plan_sha256"]) != plan_sha:
            raise RuntimeError("plan_identity_mismatch")

        results, hard_card, audits, compat_calls = current_round_results(
            document=binding,
            run_entry=run_entry,
            plan=plan,
            cases=cases,
            annotation=bundle.annotation,
            case_plan_payload=case_plan_payload,
            evidence_dir=root,
            key=key,
            receipt=receipt,
            compat=compat,
        )
        if len(audits) != len(cases):
            raise RuntimeError("current_round_audit_coverage_mismatch")
        audits_by_id = {
            str(case.case_id): audit for case, audit in zip(cases, audits)
        }
        cards = [S.build_current_card(item) for item in results]
        if [card.case_id for card in cards] != [case.case_id for case in cases]:
            raise RuntimeError("current_card_case_set_mismatch")
        if int(hard_card["total"]) != len(cards):
            raise RuntimeError("current_card_total_mismatch")

        card_doc = {
            "schema_version": "p2-h2v3-current-round-initial-card/v1",
            "role": "本轮 classify_case_evidence 初判卡（只读投影；不含题面/答案/query）",
            "run_id": run_id,
            "plan_id": plan_id,
            "plan_sha256": plan_sha,
            "evidence_tree_sha256": evidence_tree_sha,
            "business_date": business_date,
            "scenario_id": scenario,
            "code_version": str(plan_doc["bindings"]["code_version"]),
            "analysis_version": f"{rescore.ANALYSIS_ID}+{base.MATCHER_VERSION}",
            "source": "p2_hard_evidence.classify_case_evidence (current round)",
            "classifier_module_sha256": classifier_sha,
            "scope_contract_passed": None,
            "cases": [S.card_payload(card) for card in cards],
        }
        card_bytes = rescore.canonical_json_bytes(card_doc)
        card_sha = sha256_bytes(card_bytes)
        # 先做同轮来源校验，再允许任何卡进入重评分。
        origin = S.card_origin_record(
            identity={
                "run_id": run_id,
                "plan_id": plan_id,
                "plan_sha256": plan_sha,
                "evidence_tree_sha256": evidence_tree_sha,
                "business_date": business_date,
                "scenario_id": scenario,
                "code_version": str(plan_doc["bindings"]["code_version"]),
                "analysis_version": f"{rescore.ANALYSIS_ID}+{base.MATCHER_VERSION}",
            },
            identity_sources={
                "run_id": {"object": "v3-binding.runs[0].run_id", "field": "run_id", "round": "current"},
                "plan_id": {
                    "object": "plan-file(P2RunPlan).plan_id (asserted == v3-binding.runs[0].plan_id)",
                    "field": "plan_id",
                    "round": "current",
                },
                "plan_sha256": {
                    "object": "plan-file(P2RunPlan).plan_sha256 (asserted == v3-binding.runs[0].plan_sha256)",
                    "field": "plan_sha256",
                    "round": "current",
                },
                "evidence_tree_sha256": {
                    "object": "run-receipt.seal.evidence_tree_sha256",
                    "field": "seal.evidence_tree_sha256",
                    "round": "current",
                },
                "business_date": {
                    "object": "run-receipt.business_date (asserted == case-plan.run_binding.business_date)",
                    "field": "business_date",
                    "round": "current",
                },
                "scenario_id": {
                    "object": "v3-binding.runs[0].scenario_id",
                    "field": "scenario_id",
                    "round": "current",
                },
                "code_version": {
                    "object": "case-plan.bindings.code_version (validated vs v3-binding.evidence_bindings)",
                    "field": "code_version",
                    "round": "current",
                },
                "analysis_version": {
                    "object": "p2_evidence_rescore.ANALYSIS_ID + ref-unit-matcher/v2",
                    "field": "analysis_id",
                    "round": "current",
                },
            },
            cards=cards,
            classifier_sha256=classifier_sha,
            classifier_source={
                "object": "backend/src/mktkb/evaluation/p2_hard_evidence.py",
                "round": "current",
            },
        )
        S.assert_same_round(
            {
                "expected": {
                    "run_id": run_id,
                    "plan_id": plan_id,
                    "plan_sha256": plan_sha,
                    "evidence_tree_sha256": evidence_tree_sha,
                    "case_ids": [card.case_id for card in cards],
                    "classifier_sha256": classifier_sha,
                    "card_sha256": {card.case_id: S.card_sha256(card) for card in cards},
                },
                "origin": origin,
            }
        )

        v1_run = v1_by_run[run_index]
        v1_cases = {str(row["case_id"]): row for row in v1_run["cases"]}
        if set(v1_cases) != {card.case_id for card in cards}:
            raise RuntimeError("historical_case_set_mismatch")
        historical_card_bytes = rescore.canonical_json_bytes(dict(v1_run["card"]))
        historical_card_sha = sha256_bytes(historical_card_bytes)

        # 初判卡只用于本轮限定重评分（safety 非 matcher violation 的保留分支仍按原合同生效）。
        safety_views: list[Any] = []
        axes_views: list[Any] = []
        per_turn_axes: dict[str, dict[str, list[tuple[str, str]]]] = {}
        #: 空集证明原语（两条 case 级路径）的 compat 注入计数与逐案对照证明。
        empty_scope_counters: dict[str, int] = {}
        empty_scope_proofs: dict[str, dict[str, Any] | None] = {}
        card_by_id = {card.case_id: card for card in cards}
        for case in cases:
            annotation_map, _basis = hard.annotation_for_case(bundle.annotation, case)
            refs = base.all_refs(case)
            bindings = base.version_bindings_for(refs, vs)
            old = card_by_id[case.case_id]

            audit = audits_by_id[case.case_id]
            turns, _turn_stats = base.build_safety_turns(audit)
            ordered = [
                entry["evidence"] if str(entry["status"]) == "executed" else None
                for entry in audit["turns"]
            ]
            envelopes = [item for item in ordered if item is not None]
            safety_views.append(
                rescore.SafetyCaseView(
                    old=old,
                    safety_applicability=str(annotation_map["safety"]["applicability"]),
                    safety_criterion=str(annotation_map["safety"]["criterion"]),
                    safety_reason=str(annotation_map["safety"]["reason"]),
                    should_refuse=bool(getattr(case, "should_refuse", False)),
                    forbidden_values=tuple(str(value) for value in case.forbidden_values),
                    forbidden_sources=refs["forbidden_sources"],
                    expected_sources=refs["expected_sources"],
                    version_bindings=bindings,
                    turns=turns,
                )
            )
            annotations = {
                axis: base.make_annotation(axis, annotation_map[axis])
                for axis in base.RESCORED_AXES
            }
            per_turn_units = [turn.units for turn in turns if turn.status == "executed"]
            merged_units = base.merge_units(per_turn_units)
            first_envelope = envelopes[0] if envelopes else None
            cross_user_view = (
                base.build_cross_user(first_envelope, merged_units)
                if first_envelope is not None
                else rescore_axes.CrossUserEvidenceView(projection_available=False)
            )
            entity_view, stale_view, empty_scope_proof = _build_scope_views(
                envelopes=envelopes,
                units=merged_units,
                vs=vs,
                compat=compat,
                counters=empty_scope_counters,
                with_control=True,
            )
            empty_scope_proofs[case.case_id] = empty_scope_proof
            axes_views.append(
                base.build_axes_view(
                    old=old,
                    annotations=annotations,
                    cross_user=cross_user_view,
                    cross_entity=entity_view,
                    stale_source=stale_view,
                    refs=refs,
                    version_bindings=bindings,
                    bindings=base.contract_bindings(plan_doc),
                    cross_entity_mode=base.mode_for(annotations["cross_entity"]),
                    targets=annotations["cross_entity"].targets,
                    case_id=case.case_id,
                )
            )
            if len(turns) > 1:
                parts: dict[str, list[tuple[str, str]]] = {axis: [] for axis in base.RESCORED_AXES}
                for turn in turns:
                    if turn.status != "executed":
                        continue
                    single_envelope = ordered[turn.turn_index] if turn.turn_index < len(ordered) else None
                    if single_envelope is None:
                        continue
                    single_entity, single_stale, _ = _build_scope_views(
                        envelopes=[single_envelope],
                        units=turn.units,
                        vs=vs,
                        compat=compat,
                        counters=empty_scope_counters,
                        with_control=False,
                    )
                    single_view = base.build_axes_view(
                        old=old,
                        annotations=annotations,
                        cross_user=base.build_cross_user(single_envelope, turn.units),
                        cross_entity=single_entity,
                        stale_source=single_stale,
                        refs=refs,
                        version_bindings=bindings,
                        bindings=base.contract_bindings(plan_doc),
                        cross_entity_mode=base.mode_for(annotations["cross_entity"]),
                        targets=annotations["cross_entity"].targets,
                        case_id=case.case_id,
                    )
                    single_result = rescore_axes.rescore_axes_case(
                        single_view, allow_synthetic_fixture=False
                    )
                    for axis in base.RESCORED_AXES:
                        parts[axis].append(
                            (
                                str(single_result.new_axes[axis]["state"]),
                                str(single_result.new_axes[axis]["reason"]),
                            )
                        )
                per_turn_axes[case.case_id] = parts

        binding_payload = {str(k): str(v) for k, v in plan_doc["bindings"].items()}
        base_identity = rescore.RescoreIdentity(
            old_run_id=run_id,
            old_binding=binding_payload,
            old_binding_sha256=sha256_bytes(rescore.canonical_json_bytes(binding_payload)),
            old_evidence_tree_sha256=evidence_tree_sha,
            old_card_sha256=card_sha,
            contract_sha256=v0_1_sha,
            evaluator_sha256=rescore_sha,
            old_binding_bytes=rescore.canonical_json_bytes(binding_payload),
            old_card_bytes=card_bytes,
        )
        safety_report = rescore.rescore_run(identity=base_identity, cases=tuple(safety_views))
        axes_identity = rescore_axes.AxesIdentity(
            base=dataclasses.replace(
                base_identity, contract_sha256=v0_2_sha, evaluator_sha256=axes_sha
            ),
            base_contract_sha256=v0_1_sha,
        )
        axes_report = rescore_axes.rescore_axes_run(
            identity=axes_identity,
            cases=tuple(axes_views),
            allow_synthetic_fixture=False,
        )

        run_case_rows: list[dict[str, Any]] = []
        for index, case in enumerate(cases):
            card = card_by_id[case.case_id]
            historical = v1_cases[case.case_id]
            safety_case = rescore.rescore_case(safety_views[index])
            axes_case = rescore_axes.rescore_axes_case(
                axes_views[index], allow_synthetic_fixture=False
            )
            # 四轴统一成 {state, reason, provenance}；缺 provenance 即 fail closed。
            new_axes = {
                "safety": {
                    "state": str(safety_case.new_axes["safety"]["state"]),
                    "reason": str(safety_case.new_axes["safety"]["reason"]),
                    "provenance": str(safety_case.new_axes["safety"]["provenance"]),
                }
            }
            for axis in base.RESCORED_AXES:
                new_axes[axis] = {
                    "state": str(axes_case.new_axes[axis]["state"]),
                    "reason": str(axes_case.new_axes[axis]["reason"]),
                    "provenance": str(axes_case.new_axes[axis]["provenance"]),
                }
            for axis in base.AXES:
                if not str(new_axes[axis].get("provenance") or "").strip():
                    raise RuntimeError("new_axes_provenance_missing")
            initial_axes = {
                axis: {"state": str(card.axes[axis]["state"]), "reason": str(card.axes[axis]["reason"])}
                for axis in base.AXES
            }
            historical_axes = {
                axis: {
                    "state": str(historical["axes"][axis]["state"]),
                    "reason": str(historical["axes"][axis]["reason"]),
                }
                for axis in base.AXES
            }
            changed_axes = [
                axis
                for axis in base.AXES
                if (new_axes[axis]["state"], new_axes[axis]["reason"])
                != (initial_axes[axis]["state"], initial_axes[axis]["reason"])
            ]
            historical_changed_axes = [
                axis
                for axis in base.AXES
                if (new_axes[axis]["state"], new_axes[axis]["reason"])
                != (historical_axes[axis]["state"], historical_axes[axis]["reason"])
            ]
            equivalence: dict[str, Any] = {}
            if case.case_id in per_turn_axes:
                for axis in base.RESCORED_AXES:
                    folded = base.fold_turns(per_turn_axes[case.case_id][axis])
                    merged = (new_axes[axis]["state"], new_axes[axis]["reason"])
                    equivalence[axis] = {
                        "merged_view": {"state": merged[0], "reason": merged[1]},
                        "per_turn_fold": {"state": folded[0], "reason": folded[1]},
                        "equal_state": folded[0] == merged[0],
                        "equal_state_reason": folded == merged,
                    }
            run_case_rows.append(
                {
                    "case_id": case.case_id,
                    "run_index": run_index,
                    "scenario_id": scenario,
                    "stratum": card.stratum,
                    # D2：本轮质量字段（不取历史卡）
                    "quality_status": card.quality_status,
                    "quality_source": "current_round_classify_case_evidence",
                    "evidence_complete": bool(card.evidence_complete),
                    "missing_codes": list(card.missing_codes),
                    # 本轮初判（重评分输入，供审计）
                    "initial_axes": initial_axes,
                    "initial_card_sha256": S.card_sha256(card),
                    # 历史 compose 对照（绝不参与本轮门状态）
                    "historical_axes": historical_axes,
                    "historical_quality_status": str(historical["quality_status"]),
                    "historical_evidence_complete": bool(historical["evidence_complete"]),
                    "historical_missing_codes": [str(code) for code in historical["missing_codes"]],
                    "historical_card_source": HISTORICAL_SOURCE,
                    "historical_card_sha256": historical_card_sha,
                    # 本轮 matcher v2 结果
                    "new_axes": new_axes,
                    "changed_axes": changed_axes,
                    "historical_changed_axes": historical_changed_axes,
                    "safety_audit_codes": sorted({row.code for row in safety_case.safety_audit}),
                    "axes_audit_codes": {
                        axis: sorted({row.code for row in axes_case.axis_audit[axis]})
                        for axis in base.RESCORED_AXES
                    },
                    "axes_basis": {
                        axis: str(axes_case.axis_basis[axis]) for axis in base.RESCORED_AXES
                    },
                    "axes_provenance": {
                        axis: str(axes_case.axis_provenance[axis]) for axis in base.RESCORED_AXES
                    },
                    "safety_provenance": safety_case.safety_provenance,
                    "empty_scope_proof": empty_scope_proofs.get(case.case_id),
                    "multi_turn_equivalence": equivalence,
                }
            )
        case_records.extend(run_case_rows)

        initial_hard = sorted(
            row["case_id"]
            for row in run_case_rows
            if any(row["initial_axes"][axis]["state"] == "violation" for axis in base.AXES)
        )
        new_hard = sorted(
            row["case_id"]
            for row in run_case_rows
            if any(row["new_axes"][axis]["state"] == "violation" for axis in base.AXES)
        )
        historical_hard = sorted(
            row["case_id"]
            for row in run_case_rows
            if any(row["historical_axes"][axis]["state"] == "violation" for axis in base.AXES)
        )
        unknown_cases = sorted(
            row["case_id"]
            for row in run_case_rows
            if any(row["new_axes"][axis]["state"] == "unknown" for axis in base.AXES)
        )
        # §5：逐题 hard_failed flag 必须等于 violation 并集（check_consistency 会复核）。
        for row in run_case_rows:
            row["hard_failed"] = row["case_id"] in set(new_hard)
        # 逐题 quality_status 必须与 case-plan 的逐题值逐项相同（不是只比总数）。
        plan_quality = {
            str(item["case_id"]): str(item["quality_status"])
            for item in case_plan_payload["cases"]
        }
        got_quality = {row["case_id"]: str(row["quality_status"]) for row in run_case_rows}
        if set(plan_quality) != set(got_quality):
            raise RuntimeError("quality_case_set_mismatch")
        mismatch_quality = sorted(
            case_id for case_id in plan_quality if got_quality[case_id] != plan_quality[case_id]
        )
        if mismatch_quality:
            raise FixedCode("quality_case_plan_mismatch", "quality_vs_case_plan")
        quality = Counter(card.quality_status for card in cards)
        historical_quality = Counter(str(row["quality_status"]) for row in v1_cases.values())
        run_reason_counts = {
            axis: {
                reason: sum(
                    1
                    for row in run_case_rows
                    if row["new_axes"][axis]["state"] == "violation"
                    and row["new_axes"][axis]["reason"] == reason
                )
                for reason in sorted(
                    {
                        row["new_axes"][axis]["reason"]
                        for row in run_case_rows
                        if row["new_axes"][axis]["state"] == "violation"
                    }
                )
            }
            for axis in base.AXES
        }
        runs_out.append(
            {
                "run_index": run_index,
                "run_id": run_id,
                "scenario_id": scenario,
                "business_date": business_date,
                "case_count": len(cards),
                "case_ids": [card.case_id for card in cards],
                "quality_source": "current_round_classify_case_evidence",
                "quality_case_plan_match": True,
                "compat": compat,
                "compat_classify_calls": int(compat_calls),
                "compat_empty_scope": _empty_scope_summary(empty_scope_counters, empty_scope_proofs),
                "binding_identity": binding_fields,
                "quality": {status: int(quality.get(status, 0)) for status in S.QUALITY_STATUSES},
                "historical_quality": {
                    status: int(historical_quality.get(status, 0)) for status in S.QUALITY_STATUSES
                },
                "initial_hard_failures": initial_hard,
                "new_hard_failures": new_hard,
                "historical_hard_failures": historical_hard,
                "unknown_cases": unknown_cases,
                "new_axes": _axis_counts(run_case_rows, "new_axes"),
                "initial_axes": _axis_counts(run_case_rows, "initial_axes"),
                "historical_axes": _axis_counts(run_case_rows, "historical_axes"),
                "card_origin": origin,
                "current_card": {
                    "schema_version": card_doc["schema_version"],
                    "sha256": card_sha,
                    "source": card_doc["source"],
                    "classifier_module_sha256": classifier_sha,
                    "scope_contract_passed": None,
                    "cases": card_doc["cases"],
                },
                "historical_card": {
                    "sha256": historical_card_sha,
                    "source": HISTORICAL_SOURCE,
                    "v1_card_sha256": str(v1_run.get("card_sha256") or ""),
                    "role": "comparison_only",
                },
                "identity_provenance": {
                    "old_run_id": {
                        "value": run_id,
                        "source": {"object": "v3-binding.runs[0].run_id", "round": "current"},
                    },
                    "old_binding_sha256": {
                        "value": base_identity.old_binding_sha256,
                        "source": {"object": "case-plan.bindings (canonical JSON)", "round": "current"},
                    },
                    "old_evidence_tree_sha256": {
                        "value": evidence_tree_sha,
                        "source": {
                            "object": "run-receipt.seal.evidence_tree_sha256",
                            "round": "current",
                        },
                    },
                    "old_card_sha256": {
                        "value": card_sha,
                        "source": {
                            "object": "current-round initial card document (classify_case_evidence)",
                            "round": "current",
                        },
                    },
                    "contract_sha256": {
                        "value": v0_1_sha,
                        "source": {"object": "docs/evaluation/p2-evidence-rescore-v0_1.md", "round": "current"},
                    },
                    "evaluator_sha256": {
                        "value": rescore_sha,
                        "source": {
                            "object": "backend/src/mktkb/evaluation/p2_evidence_rescore.py",
                            "round": "current",
                        },
                    },
                    "historical_card_sha256": {
                        "value": historical_card_sha,
                        "source": {"object": HISTORICAL_SOURCE, "round": "historical"},
                    },
                },
                "safety_report": safety_report.as_dict(),
                "axes_report": axes_report.public_summary(),
                "violation_reasons": run_reason_counts,
                "cases": run_case_rows,
            }
        )
        print(
            json.dumps(
                {
                    "run_index": run_index,
                    "scenario_id": scenario,
                    "case_count": len(cases),
                    "quality": {status: int(quality.get(status, 0)) for status in S.QUALITY_STATUSES},
                    "initial_hard_failures": initial_hard,
                    "new_hard_failures": new_hard,
                    "historical_hard_failures": historical_hard,
                    "compat_classify_calls": int(compat_calls),
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            flush=True,
        )

    aggregate = {
        "case_count": len(case_records),
        "new_axes": _axis_counts(case_records, "new_axes"),
        "initial_axes": _axis_counts(case_records, "initial_axes"),
        "historical_axes": _axis_counts(case_records, "historical_axes"),
        "hard_failures": sorted(
            row["case_id"]
            for row in case_records
            if any(row["new_axes"][axis]["state"] == "violation" for axis in base.AXES)
        ),
        "initial_hard_failures": sorted(
            row["case_id"]
            for row in case_records
            if any(row["initial_axes"][axis]["state"] == "violation" for axis in base.AXES)
        ),
        "historical_hard_failures": sorted(
            row["case_id"]
            for row in case_records
            if any(row["historical_axes"][axis]["state"] == "violation" for axis in base.AXES)
        ),
        "unknown_cases": sorted(
            row["case_id"]
            for row in case_records
            if any(row["new_axes"][axis]["state"] == "unknown" for axis in base.AXES)
        ),
        "historical_unknown_cases": sorted(
            row["case_id"]
            for row in case_records
            if any(row["historical_axes"][axis]["state"] == "unknown" for axis in base.AXES)
        ),
        "changed_case_count": sum(1 for row in case_records if row["changed_axes"]),
        "historical_changed_case_count": sum(
            1 for row in case_records if row["historical_changed_axes"]
        ),
        "state_change_cases": sorted(
            {
                row["case_id"]
                for row in case_records
                if any(
                    row["initial_axes"][axis]["state"] != row["new_axes"][axis]["state"]
                    for axis in base.AXES
                )
            }
        ),
        "changed_cases": sorted({row["case_id"] for row in case_records if row["changed_axes"]}),
    }
    # 明确标注 old_* 在本轮的含义，避免读者把它误读成历史 compose 卡。
    aggregate["old_axes"] = aggregate["initial_axes"]
    aggregate["old_hard_failures"] = aggregate["initial_hard_failures"]
    aggregate["old_axes_meaning"] = "same-round initial card (classify_case_evidence)"
    aggregate["historical_axes_meaning"] = "compose historical card; comparison only"
    aggregate["hard_failed_source"] = "validated_per_case_axes.new_axes[*].state==violation"

    # §5 一致性门：任一不成立即抛错，不写成功产物。
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "matcher_version": base.MATCHER_VERSION,
        "analysis_id": rescore.ANALYSIS_ID,
        "evaluator_phase": rescore_axes.EVALUATOR_PHASE,
        "call_path": "tools/p2_h2_controlled_execute.py::_recompute_loaded -> "
        "p2_hard_evidence.recompute_hard_evidence",
        "scope_contract": {
            "passed": None,
            "source": SCOPE_CONTRACT_SOURCE,
            "why": "真实 run 路径不传 scope_contract；从 annotation 另造会改变 cross_entity 判据",
        },
        "source_round": "current",
        "inputs": {
            "v0_1_contract_sha256": v0_1_sha,
            "v0_2_contract_sha256": v0_2_sha,
            "l1_criterion_sha256": vs["l1_criterion_sha256"],
            "lifecycle_sha256": vs["lifecycle_sha256"],
            "source_map_sha256": vs["source_map_sha256"],
            "corpus_manifest_sha256": vs["corpus_manifest_sha256"],
            "rescore_module_sha256": rescore_sha,
            "rescore_axes_module_sha256": axes_sha,
            "classifier_module_sha256": classifier_sha,
            "same_round_module_sha256": same_round_sha,
            "historical_v1_results_sha256": sha256_file(base.V1_RESULTS),
            "historical_v1_results_role": "comparison_only",
            "annotation_schema_sha256": sha256_file(base.ANNOTATION_SCHEMA),
        },
        "version_binding": {
            "declared_codes": vs["code_count"],
            "bijective_pairs": vs["bijective_pairs"],
            "basis": "source_map",
            "refs_bound_by": "p2-holdout-v3.source-map/v0.2 (doc_code -> base_doc_code, version_number)",
            "date_semantics": "L1 p2-stale-source-criterion-v1_1 (sentinel 未声明 => effective_to null / not_asserted)",
            "business_dates": {str(run["run_index"]): run["business_date"] for run in runs_out},
            "inference_used": False,
        },
        "aggregate": aggregate,
        "runs": runs_out,
        "multi_turn_equivalence": [
            {
                "case_id": row["case_id"],
                "run_index": row["run_index"],
                "axes": row["multi_turn_equivalence"],
            }
            for row in case_records
            if row["multi_turn_equivalence"]
        ],
        "c26": _case_detail(
            case_records,
            "H2V3-C26",
            aggregate["initial_hard_failures"],
            aggregate["hard_failures"],
        ),
        "c25": _case_detail(
            case_records,
            "H2V3-C25",
            aggregate["initial_hard_failures"],
            aggregate["hard_failures"],
        ),
        "calls": {"network": 0, "provider": 0, "model": 0, "retrieval": 0, "real": 0},
        "compat": {
            "mode": compat,
            "explicit": True,
            "applied_by": "p2_hard_evidence.classify_case_evidence(compat=...) wrapper",
            "calls_per_run": {str(run["run_index"]): int(run["compat_classify_calls"]) for run in runs_out},
            "empty_scope_injection": {
                "primitive": EMPTY_SCOPE_PRIMITIVE,
                "why": "cross_entity / stale_source 的空集证明默认走 v0.1，必须与初判同档",
                "per_run": {
                    str(run["run_index"]): run["compat_empty_scope"] for run in runs_out
                },
                "applied_by": "adapter-scoped wrapper (restored after each build; defaults untouched)",
            },
            "default_unchanged": compat == hard.REFUSAL_COMPAT_V0_1,
        },
        "netguard": (guard.as_dict() if guard is not None else None),
        "not_claimed": [
            "verified",
            "threshold_met",
            "release_ready",
            "release",
            "T207_pass",
            "all_axes_real_complete",
            "q1a3_complete",
        ],
    }
    S.check_consistency({"runs": runs_out, "aggregate": aggregate})
    derived = S.derive_hard_failed(case_records, aggregate)
    if derived != set(aggregate["hard_failures"]):
        raise RuntimeError("hard_failures_mismatch")
    if guard is not None and not guard.as_dict()["positive_control_blocked"]:
        raise FixedCode("netguard_positive_control_failed", "run")
    for run in runs_out:
        block = run["compat_empty_scope"]
        control_total = sum(block["control_calls"].values())
        injected_total = int(block["injected_calls_total"])
        if not block["call_sites_equal"]:
            raise FixedCode("compat_empty_scope_call_site_mismatch", "compat_self_check")
        # 有空集题时，注入必须真的发生过；否则说明旁路还在。
        if compat != hard.REFUSAL_COMPAT_V0_1 and control_total > 0 and injected_total == 0:
            raise FixedCode("compat_empty_scope_not_applied", "compat_self_check")
    payload["consistency"] = {
        "passed": True,
        "checks": [
            "case_id_unique_exact_coverage",
            "per_case_quality_sum_equals_run_quality",
            "per_case_quality_status_equals_case_plan",
            "hard_failed_flags_equal_violation_union",
            "axis_four_state_counts_equal_case_count",
            "unknown_cases_not_hidden",
            "new_axes_provenance_present_on_all_four_axes",
            "compat_injected_into_cross_entity_and_stale_source_builders",
        ],
        "hard_failed_source": "validated_per_case_axes.new_axes[*].state==violation",
        "quality_source": "case-plan.quality_status (per case, exact)",
        "compat_paths": {
            "classify_case_evidence": "wrapped (explicit compat)",
            "empty_use_scope_proof (cross_entity/stale_source builders)": "wrapped (explicit compat)",
        },
    }

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "wrote": target.name,
                "runs": len(runs_out),
                "case_count": aggregate["case_count"],
                "hard_failures": aggregate["hard_failures"],
                "initial_hard_failures": aggregate["initial_hard_failures"],
                "historical_hard_failures": aggregate["historical_hard_failures"],
                "unknown_cases": aggregate["unknown_cases"],
                "new_axes": aggregate["new_axes"],
                "compat": compat,
                "netguard": payload["netguard"],
                "consistency_passed": True,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


def _emit_failure(code: Any, where: Any) -> None:
    """失败出口只输出固定码与函数名；绝不回显异常正文/traceback。"""
    safe_code = str(code) if CODE_RE.fullmatch(str(code)) else "internal_error"
    safe_where = str(where) if CODE_RE.fullmatch(str(where)) else "unknown"
    print(json.dumps({"ok": False, "error": safe_code, "where": safe_where}, sort_keys=True))


def main(argv: Sequence[str] | None = None) -> int:
    guard = NetGuard()
    guard.install()
    try:
        guard.positive_control()
    except NetGuardFailed as exc:
        _emit_failure(exc.args[0] if exc.args else "netguard_positive_control_failed", "netguard")
        return 2
    try:
        return run(argv, guard=guard)
    except SystemExit:
        raise
    except S.SameRoundError as exc:
        _emit_failure(getattr(exc, "code", None), "same_round")
        return 2
    except FixedCode as exc:
        _emit_failure(exc.code, exc.where)
        return 2
    except RuntimeError as exc:
        # 本脚本的所有内部失败都以固定码字符串抛出；非固定码一律降级。
        _emit_failure(exc.args[0] if exc.args else None, "run")
        return 2
    except Exception as exc:  # noqa: BLE001 - 绝不回显 str(exc)/traceback
        code = {"P2ScoringError": "scoring_error"}.get(type(exc).__name__, "internal_error")
        _emit_failure(code, "run")
        return 3


if __name__ == "__main__":
    raise SystemExit(main())

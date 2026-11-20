"""R0-5 CAP：v3 受控入口的 presend 门序 / run 级单写者 / unlimited 配额口径。

被测契约（只针对 ``tools/p2_h2_v3_controlled_execute.py``）：

1. ``run`` 必须在**真实发送之前**完成 ``plan_dial``（含
   ``plan.max_requests == "unlimited"``）与 ``_recompute_plan``；任一不成立用固定码
   （``plan_dial_failed`` / ``plan_recompute_failed``）拒绝，且不加载私有 v3 材料、
   不进入 ``_execute_loaded``、不产生任何外部连接；
2. ``_recompute_plan`` 额外校验 ``plan_id`` 由 ``{prefix}-r{index}-{scenario}`` 派生；
3. ``run`` 与 ``check-only`` 共用 run 级 O_EXCL 单写者占位：已持有则固定码
   ``run_claim_held`` 拒绝、零发送；死 PID 的陈旧占位可回收，活 PID 的占位不得抢；
4. ``quota`` 块必须真实反映 unlimited（不再恒 False），并写明哪些闸仍然生效。

零真实调用：不读 .env、不读任何 H2 私有材料；binding/inputs 都是 tmp 合成件，
``load_v3_bundle`` 与 ``_execute_loaded`` 被替换成"被调用即失败"的探针。
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from cryptography.fernet import Fernet

_TESTS_DIR = Path(__file__).resolve().parents[1]
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

from acceptance.support.netguard import t09_network_guard  # noqa: E402,F401

pytestmark = pytest.mark.usefixtures("t09_network_guard")

ROOT = Path(__file__).resolve().parents[3]
TOOL_PATH = ROOT / "tools" / "p2_h2_v3_controlled_execute.py"
TOTAL_LIMIT_ENV = "MKTKB_PROJECT_TOTAL_LIMIT_CNY"
NOW = datetime(2026, 11, 19, 3, 0, tzinfo=timezone.utc)
PLAN_ID = "P2-H2V3-20261115-r0-base_b0"
RUN_ID = "p2-h2v3-20261115-r0-base_b0"
SCENARIO = "base_b0"
CREATE_UTC = "2026-11-15T05:00:00+08:00"
BINDING_KEYS = (
    "scenario_id",
    "assignment_sha256",
    "custody_sha256",
    "review_sha256",
    "scenario_contract_sha256",
    "ingest_plan_sha256",
    "scenario_ingest_sha256",
    "subset_sha256",
    "full_cases_sha256",
    "manifest_sha256",
    "schema_sha256",
    "source_map_sha256",
)


@pytest.fixture(scope="module")
def tool() -> Any:
    """按文件路径导入 v3 入口（导入期会把总上限固定为 40；测试后还原环境）。

    ``p2_holdout_plan`` 在导入期读取 ``MKTKB_PROJECT_TOTAL_LIMIT_CNY``；本入口要求它是
    40。如果同会话里别的测试先按 20 导入了它，这里临时改常量只为通过入口自检，
    随后还原，不改变其他测试的可见状态。
    """
    from mktkb.evaluation import p2_holdout_plan as holdout

    original_env = os.environ.get(TOTAL_LIMIT_ENV)
    original_const = holdout.H2_PROJECT_TOTAL_LIMIT_CNY
    os.environ[TOTAL_LIMIT_ENV] = "40.0"
    holdout.H2_PROJECT_TOTAL_LIMIT_CNY = 40.0
    try:
        spec = importlib.util.spec_from_file_location("p2_h2_v3_controlled_entry_under_test", TOOL_PATH)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
    finally:
        holdout.H2_PROJECT_TOTAL_LIMIT_CNY = original_const
        if original_env is None:
            os.environ.pop(TOTAL_LIMIT_ENV, None)
        else:
            os.environ[TOTAL_LIMIT_ENV] = original_env
    return module


# --------------------------------------------------------------------------- #
# 合成 binding / inputs / plan（无私有材料）
# --------------------------------------------------------------------------- #


def _inputs(tool: Any, root: Path) -> dict[str, dict[str, Any]]:
    root.mkdir(parents=True, exist_ok=True)
    records: dict[str, dict[str, Any]] = {}
    names = tuple(tool.V3_INPUT_NAMES)
    assert "holdout_manifest" in names
    for name in names:
        path = root / (name + ".bin")
        path.write_bytes(("synthetic:" + name).encode("utf-8"))
        raw = path.read_bytes()
        records[name] = {
            "path": str(path),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "bytes": len(raw),
        }
    return records


def _scenario_binding(scenario: str, inputs: dict[str, dict[str, Any]]) -> dict[str, str]:
    return {
        "scenario_id": scenario,
        "assignment_sha256": "1" * 64,
        "custody_sha256": "2" * 64,
        "review_sha256": "3" * 64,
        "scenario_contract_sha256": str(inputs["scenario_contract"]["sha256"]),
        "ingest_plan_sha256": str(inputs["ingest_plan"]["sha256"]),
        "scenario_ingest_sha256": "4" * 64,
        "subset_sha256": "5" * 64,
        "full_cases_sha256": "6" * 64,
        "manifest_sha256": str(inputs["holdout_manifest"]["sha256"]),
        "schema_sha256": str(inputs["annotation_schema"]["sha256"]),
        "source_map_sha256": str(inputs["source_map"]["sha256"]),
    }


def _build_plan(
    *,
    plan_id: str = PLAN_ID,
    max_requests: Any = "unlimited",
    scenario_binding: dict[str, str] | None = None,
) -> Any:
    from mktkb.evaluation.p2_holdout_plan import build_holdout_plan

    return build_holdout_plan(
        cases=(("SYN-01", 1),),
        ingest_batches=1,
        plan_id=plan_id,
        plan_version="v0.1",
        created_utc=CREATE_UTC,
        max_requests=max_requests,
        project_total_limit_cny=40.0,
        scenario_binding=scenario_binding,
    )


def _run_entry(plan: Any, *, run_index: int = 0, scenario: str = SCENARIO) -> dict[str, Any]:
    suffix = f"r{run_index}-{scenario}"
    return {
        "run_index": run_index,
        "scenario_id": scenario,
        "run_id": f"p2-h2v3-20261115-{suffix}",
        "total_requests": int(plan.total_requests),
        "case_count": int(plan.case_count) - 1,
        "turn_count": int(plan.turn_count) - 1,
    }


def _document(tool: Any, inputs: dict[str, dict[str, Any]], run_entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "code_version": "c" * 64,
        "business_date": "2026-10-15",
        "inputs": inputs,
        "runs": [run_entry],
    }


def _patch_run_boundary(
    monkeypatch: pytest.MonkeyPatch,
    tool: Any,
    tmp_path: Path,
    *,
    document: dict[str, Any],
    plan: Any,
    sent: list[str],
    bundle_loads: list[str],
) -> None:
    """把私有材料/执行核心换成探针：任何"提前加载/提前发送"都会让测试失败。"""
    monkeypatch.setattr(tool.v2, "code_digest", lambda: document["code_version"])
    monkeypatch.setattr(tool.v2, "load_run_binding", lambda path: document)
    monkeypatch.setattr(tool.v2, "_load_plan_for_run", lambda doc, entry: plan)
    monkeypatch.setattr(tool.v2, "_verify_plan_binding", lambda *args, **kwargs: None)
    # 合成路径在 pytest basetemp（仓内）下：只把 v2 的"仓外"根挪走，闸门逻辑不变。
    monkeypatch.setattr(tool.v2, "PROJECT_ROOT", tmp_path / "workspace")
    monkeypatch.setattr(tool, "RUN_CLAIM_REGISTRY", tmp_path / "claims")

    def _bundle(inputs: Any) -> Any:
        bundle_loads.append("bundle")
        raise AssertionError("plan_dial/plan_recompute 未过就加载了私有 v3 材料")

    async def _execute(**kwargs: Any) -> Any:
        sent.append("execute")
        raise AssertionError("presend 门未过就进入真实执行核心")

    monkeypatch.setattr(tool, "load_v3_bundle", _bundle)
    monkeypatch.setattr(tool.v2, "_execute_loaded", _execute)


def _run_kwargs(tmp_path: Path, binding_path: Path) -> dict[str, Any]:
    key = tmp_path / "evidence.key"
    if not key.exists():
        key.write_bytes(Fernet.generate_key())
    return {
        "binding_path": binding_path,
        "run_index": 0,
        "out_dir": tmp_path / "out",
        "evidence_root": tmp_path / "evidence",
        "seal_root": tmp_path / "seal",
        "evidence_key_file": key,
        "env_file": tmp_path / "env",
        "now": NOW,
    }


# --------------------------------------------------------------------------- #
# 1. presend 门序：dial / recompute / plan_id 派生
# --------------------------------------------------------------------------- #


def test_run_refuses_finite_plan_dial_before_bundle_and_send(
    tool: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, t09_network_guard: Any
) -> None:
    """plan.max_requests=1500（旧有限口径）必须在发送前被 dial 拒掉。"""
    inputs = _inputs(tool, tmp_path / "inputs")
    plan = _build_plan(max_requests=1500)
    run_entry = _run_entry(plan)
    document = _document(tool, inputs, run_entry)
    sent: list[str] = []
    bundle_loads: list[str] = []
    _patch_run_boundary(
        monkeypatch, tool, tmp_path, document=document, plan=plan, sent=sent, bundle_loads=bundle_loads
    )

    with pytest.raises(tool.EntryError) as excinfo:
        tool.run_command(**_run_kwargs(tmp_path, tmp_path / "binding.json"))

    assert excinfo.value.code == "plan_dial_failed"
    assert "max_requests" in excinfo.value.detail
    assert excinfo.value.exit_code == tool.EXIT_REFUSED
    assert sent == [] and bundle_loads == []
    assert t09_network_guard.snapshot()["external"] == []


def test_run_refuses_recompute_mismatch_before_bundle_and_send(
    tool: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, t09_network_guard: Any
) -> None:
    """计划被改写（重算结果不同）必须在发送前以固定码拒绝，而不是花完钱再降 ok。"""
    inputs = _inputs(tool, tmp_path / "inputs")
    binding = _scenario_binding(SCENARIO, inputs)
    plan = _build_plan(scenario_binding=binding)
    other = _build_plan(max_requests=1500, scenario_binding=binding)  # 重算出的"另一份计划"
    run_entry = _run_entry(plan)
    document = _document(tool, inputs, run_entry)
    sent: list[str] = []
    bundle_loads: list[str] = []
    _patch_run_boundary(
        monkeypatch, tool, tmp_path, document=document, plan=plan, sent=sent, bundle_loads=bundle_loads
    )
    real_builder = tool.holdout_plan.build_holdout_plan

    def _builder(**kwargs: Any) -> Any:
        kwargs.setdefault("project_total_limit_cny", tool.V3_PROJECT_TOTAL_LIMIT_CNY)
        if kwargs.get("max_requests") == plan.max_requests:
            return other
        return real_builder(**kwargs)

    monkeypatch.setattr(tool.holdout_plan, "build_holdout_plan", _builder)

    with pytest.raises(tool.EntryError) as excinfo:
        tool.run_command(**_run_kwargs(tmp_path, tmp_path / "binding.json"))

    assert excinfo.value.code == "plan_recompute_failed"
    assert excinfo.value.detail == "scenario_plan_mismatch"
    assert sent == [] and bundle_loads == []
    assert t09_network_guard.snapshot()["external"] == []


def test_run_refuses_plan_id_not_derived(
    tool: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, t09_network_guard: Any
) -> None:
    """plan_id 必须由 {prefix}-r{index}-{scenario} 派生；用 r1 的 id 跑 r0 直接拒绝。"""
    inputs = _inputs(tool, tmp_path / "inputs")
    plan = _build_plan(plan_id="P2-H2V3-20261115-r1-base_b0")
    run_entry = _run_entry(plan)
    document = _document(tool, inputs, run_entry)
    sent: list[str] = []
    bundle_loads: list[str] = []
    _patch_run_boundary(
        monkeypatch, tool, tmp_path, document=document, plan=plan, sent=sent, bundle_loads=bundle_loads
    )
    real_builder = tool.holdout_plan.build_holdout_plan

    def _builder(**kwargs: Any) -> Any:
        kwargs.setdefault("project_total_limit_cny", tool.V3_PROJECT_TOTAL_LIMIT_CNY)
        return real_builder(**kwargs)

    monkeypatch.setattr(tool.holdout_plan, "build_holdout_plan", _builder)

    with pytest.raises(tool.EntryError) as excinfo:
        tool.run_command(**_run_kwargs(tmp_path, tmp_path / "binding.json"))

    assert excinfo.value.code == "plan_recompute_failed"
    assert excinfo.value.detail == "plan_id_not_derived"
    assert sent == [] and bundle_loads == []
    assert t09_network_guard.snapshot()["external"] == []


# --------------------------------------------------------------------------- #
# 2. run 级单写者（O_EXCL claim）
# --------------------------------------------------------------------------- #


def test_run_claim_excludes_concurrent_holder_and_releases(
    tool: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tool, "RUN_CLAIM_REGISTRY", tmp_path / "claims")
    root = tool._claim_registry_root()
    with tool._run_claim(RUN_ID, holder="run", roots=[root]):
        claim = root / f"run-claim-{RUN_ID}.json"
        assert claim.is_file()
        with pytest.raises(tool.EntryError) as excinfo:
            tool._acquire_run_claim(RUN_ID, holder="check-only", root=root)
        assert excinfo.value.code == "run_claim_held"
    assert not claim.exists()


def test_run_claim_reclaims_dead_pid_but_never_a_live_one(
    tool: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tool, "RUN_CLAIM_REGISTRY", tmp_path / "claims")
    root = tool._claim_registry_root()
    root.mkdir(parents=True, exist_ok=True)
    claim = root / f"run-claim-{RUN_ID}.json"

    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    claim.write_text(
        json.dumps({"schema_version": tool.RUN_CLAIM_SCHEMA_VERSION, "pid": dead.pid, "process_start": None}),
        encoding="utf-8",
    )
    held = tool._acquire_run_claim(RUN_ID, holder="run", root=root)
    assert held == claim
    tool._release_run_claim(held)

    from mktkb.proc_identity import process_identity

    alive, marker = process_identity(os.getpid())
    assert alive is True
    claim.write_text(
        json.dumps({"schema_version": tool.RUN_CLAIM_SCHEMA_VERSION, "pid": os.getpid(), "process_start": marker}),
        encoding="utf-8",
    )
    with pytest.raises(tool.EntryError) as excinfo:
        tool._acquire_run_claim(RUN_ID, holder="run", root=root)
    assert excinfo.value.code == "run_claim_held"


def test_run_refuses_when_claim_held_before_bundle_and_send(
    tool: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, t09_network_guard: Any
) -> None:
    inputs = _inputs(tool, tmp_path / "inputs")
    binding = _scenario_binding(SCENARIO, inputs)
    plan = _build_plan(scenario_binding=binding)
    run_entry = _run_entry(plan)
    document = _document(tool, inputs, run_entry)
    sent: list[str] = []
    bundle_loads: list[str] = []
    _patch_run_boundary(
        monkeypatch, tool, tmp_path, document=document, plan=plan, sent=sent, bundle_loads=bundle_loads
    )
    real_builder = tool.holdout_plan.build_holdout_plan

    def _builder(**kwargs: Any) -> Any:
        kwargs.setdefault("project_total_limit_cny", tool.V3_PROJECT_TOTAL_LIMIT_CNY)
        return real_builder(**kwargs)

    monkeypatch.setattr(tool.holdout_plan, "build_holdout_plan", _builder)

    root = tool._claim_registry_root()
    held = tool._acquire_run_claim(RUN_ID, holder="other-run", root=root)
    try:
        with pytest.raises(tool.EntryError) as excinfo:
            tool.run_command(**_run_kwargs(tmp_path, tmp_path / "binding.json"))
    finally:
        tool._release_run_claim(held)

    assert excinfo.value.code == "run_claim_held"
    assert sent == [] and bundle_loads == []
    assert t09_network_guard.snapshot()["external"] == []


def test_run_releases_claim_when_a_later_presend_check_refuses(
    tool: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """claim 之后的失败必须释放租约，不能把下一次重试锁在门外。"""
    inputs = _inputs(tool, tmp_path / "inputs")
    binding = _scenario_binding(SCENARIO, inputs)
    plan = _build_plan(scenario_binding=binding)
    run_entry = _run_entry(plan)
    document = _document(tool, inputs, run_entry)
    sent: list[str] = []
    bundle_loads: list[str] = []
    _patch_run_boundary(
        monkeypatch, tool, tmp_path, document=document, plan=plan, sent=sent, bundle_loads=bundle_loads
    )
    real_builder = tool.holdout_plan.build_holdout_plan

    def _builder(**kwargs: Any) -> Any:
        kwargs.setdefault("project_total_limit_cny", tool.V3_PROJECT_TOTAL_LIMIT_CNY)
        return real_builder(**kwargs)

    monkeypatch.setattr(tool.holdout_plan, "build_holdout_plan", _builder)

    def _bundle(inputs: Any) -> Any:
        bundle_loads.append("bundle")
        raise tool.EntryError("dataset_bundle_invalid")

    monkeypatch.setattr(tool, "load_v3_bundle", _bundle)

    with pytest.raises(tool.EntryError) as excinfo:
        tool.run_command(**_run_kwargs(tmp_path, tmp_path / "binding.json"))
    assert excinfo.value.code == "dataset_bundle_invalid"
    assert sent == [] and len(bundle_loads) == 1
    assert list(tool._claim_registry_root().glob("run-claim-*.json")) == []
    assert list((tmp_path / "seal").glob("run-claim-*.json")) == []


# --------------------------------------------------------------------------- #
# 3. quota：unlimited 不再是"恒 False 的假闸"
# --------------------------------------------------------------------------- #


def test_quota_summary_states_unlimited_has_no_total_request_gate(tool: Any) -> None:
    plan = _build_plan()
    snapshot = SimpleNamespace(reservation_count=7)
    quota = tool._quota_summary(plan, snapshot, 36, go_max_requests="unlimited")

    assert quota["gate_mode"] == "unlimited"
    assert quota["governance_cap"] == "unlimited"
    assert quota["exceeds_gate"] is None
    assert quota["not_enforced_reason"] == "unlimited_no_cumulative_request_gate"
    assert quota["used_before"] == 7
    assert quota["cumulative_after_four_runs"] == 43
    assert quota["requests_this_run"] == int(plan.total_requests)
    assert "plan_dial.max_requests=unlimited" in quota["gate_enforced_by"]


def test_quota_summary_still_computes_a_finite_gate(tool: Any) -> None:
    plan = _build_plan(max_requests=100)
    snapshot = SimpleNamespace(reservation_count=7)

    ok = tool._quota_summary(plan, snapshot, 30, go_max_requests=150)
    assert ok["gate_mode"] == "finite" and ok["governance_cap"] == 100
    assert ok["exceeds_gate"] is False

    over = tool._quota_summary(plan, snapshot, 120, go_max_requests=150)
    assert over["exceeds_gate"] is True
    assert over["cumulative_after_four_runs"] == 127

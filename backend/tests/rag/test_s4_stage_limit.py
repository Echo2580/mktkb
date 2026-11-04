"""S4 工程债 B 回归：阶段额度只来自 GO + 共享预算，不再写死 3.00 元。

背景：``tools/rag_experiment.py live`` 旧实现把阶段额度硬限在 ``(0, 3.00]``，与当前 GO
（``scope.stage_limits_cny['S2-DEV'] = 18.4``）不一致，导致该入口对现行授权**必然**拒绝；
旧实现还会在取不到额度时静默回落 3.00。这里锁定新语义：

- 额度 = min(``--stage-limit``, GO ``scope.stage_limits_cny[stage]``, 共享 ``budget.json``
  的 ``stages[stage]``)；参数只能收窄；
- GO 缺阶段额度 / 预算缺阶段分配 / 参数非有限正数 → 直接拒绝（SystemExit，稳定文案），
  不回落到任何写死值。

全部零请求：只调用纯函数与 ``_check_go_file``，不发 HTTP、不写共享账本/预算（只读真实
budget.json 作为模板，写到自己 tmp_path 的副本上）。
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
REAL_LEDGER = ROOT / "docs" / "evidence" / "LOCAL-R1-20261101" / "budget" / "live-ledger.jsonl"
REAL_BUDGET = ROOT / "docs" / "evidence" / "LOCAL-R1-20261101" / "budget" / "budget.json"


def _tools():
    spec = importlib.util.spec_from_file_location("rag_experiment_s4", ROOT / "tools" / "rag_experiment.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _go_payload(*, stage: str = "S1-DEV", scope: dict | None = None) -> dict:
    payload = {
        "document": "S1-LIVE-GO",
        "stage": stage,
        "authorization": "REAL-STAGE",
        "issued_by": "s4-test",
        "nonce": "s4-test-nonce-0123456789",
        "issued_utc": "2026-11-02T00:00:00+08:00",
        "expires_utc": "2099-01-01T00:00:00+08:00",
        "scope": {
            "max_documents": 2,
            "max_requests": 40,
            "max_questions": 2,
            "stage_limits_cny": {stage: 18.4},
        },
    }
    if scope:
        payload["scope"] = {**payload["scope"], **scope}
    return payload


def _budget_payload(*, stage: str = "S1-DEV", allocation: float | None = 18.4) -> dict:
    payload = {"limit_cny": 20.0, "stages": {stage: allocation} if allocation is not None else {"S1-DEV": 3.0}}
    return payload


# --------------------------------------------------------- 旧行为：>3.00 直接被拒


def test_go_declared_stage_limit_above_three_yuan_is_accepted(tmp_path, monkeypatch):
    """18.4 元（当前 GO 的真实额度）必须被接受；旧实现以 (0, 3.00] 拒绝它。"""
    tools = _tools()
    ledger = tmp_path / "live-ledger.jsonl"
    ledger.write_text(
        json.dumps({"event": "historical_import", "stage": "S1-DEV", "accounted_cny": 0.03}) + "\n",
        encoding="utf-8",
    )
    go = tmp_path / "S1-LIVE-GO.md"
    payload = _go_payload()
    payload["budget_ledger_sha256"] = hashlib.sha256(ledger.read_bytes()).hexdigest()
    go.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(tools, "GO_PATH", go)
    monkeypatch.setattr(tools, "_FIXED_LEDGER", ledger)

    checked = tools._check_go_file()
    assert checked["scope"]["stage_limit_cny"] == pytest.approx(18.4)


# --------------------------------------------------------- 取 min + 只收窄


def test_stage_limit_is_min_of_parameter_go_and_budget():
    tools = _tools()
    go = _go_payload()
    budget = _budget_payload()

    # 不传参数：不额外收窄，取 GO/budget 的较小值
    assert tools._resolve_stage_limit_cny(
        go_payload=go, budget_payload=budget, stage="S1-DEV", requested=None
    ) == pytest.approx(18.4)
    # 参数更小 → 按参数收窄
    assert tools._resolve_stage_limit_cny(
        go_payload=go, budget_payload=budget, stage="S1-DEV", requested=3.0
    ) == pytest.approx(3.0)
    # 参数更大 → 不能放大
    assert tools._resolve_stage_limit_cny(
        go_payload=go, budget_payload=budget, stage="S1-DEV", requested=99.0
    ) == pytest.approx(18.4)
    # budget 阶段分配更小 → 取 budget
    assert tools._resolve_stage_limit_cny(
        go_payload=go,
        budget_payload=_budget_payload(allocation=2.5),
        stage="S1-DEV",
        requested=None,
    ) == pytest.approx(2.5)
    # GO 更小 → 取 GO
    assert tools._resolve_stage_limit_cny(
        go_payload=_go_payload(scope={"stage_limits_cny": {"S1-DEV": 1.5}}),
        budget_payload=budget,
        stage="S1-DEV",
        requested=9.0,
    ) == pytest.approx(1.5)


def test_stage_limit_requires_finite_positive_parameter():
    tools = _tools()
    for bad in (0, -1, math.nan, math.inf, True, "5"):
        with pytest.raises(SystemExit) as excinfo:
            tools._resolve_stage_limit_cny(
                go_payload=_go_payload(), budget_payload=_budget_payload(), stage="S1-DEV", requested=bad
            )
        assert "--stage-limit" in str(excinfo.value)


# --------------------------------------------------------- fail-closed：取不到就拒绝


def test_missing_go_stage_limit_is_rejected_not_defaulted():
    tools = _tools()
    go = _go_payload()
    go["scope"].pop("stage_limits_cny")
    go["scope"].pop("stages", None)
    with pytest.raises(SystemExit) as excinfo:
        tools._resolve_stage_limit_cny(
            go_payload=go, budget_payload=_budget_payload(), stage="S1-DEV", requested=None
        )
    assert "S1-DEV" in str(excinfo.value)
    assert "stage_limits_cny" in str(excinfo.value)


def test_missing_budget_stage_allocation_is_rejected_not_defaulted():
    tools = _tools()
    with pytest.raises(SystemExit) as excinfo:
        tools._resolve_stage_limit_cny(
            go_payload=_go_payload(),
            budget_payload={"limit_cny": 20.0, "stages": {"S2-DEV": 18.4}},
            stage="S1-DEV",
            requested=None,
        )
    assert "共享预算" in str(excinfo.value)


def test_budget_without_stages_object_is_rejected():
    tools = _tools()
    with pytest.raises(SystemExit):
        tools._resolve_stage_limit_cny(
            go_payload=_go_payload(),
            budget_payload={"limit_cny": 20.0},
            stage="S1-DEV",
            requested=None,
        )


def test_legacy_go_stage_limit_field_still_supported():
    """旧 GO 只有 scope.stage_limit_cny 时仍可用（不因为改造而失效）。"""
    tools = _tools()
    go = _go_payload()
    go["scope"].pop("stage_limits_cny")
    go["scope"]["stage_limit_cny"] = 18.4
    assert tools._resolve_stage_limit_cny(
        go_payload=go, budget_payload=_budget_payload(), stage="S1-DEV", requested=None
    ) == pytest.approx(18.4)


def test_current_go_and_budget_are_consistent_and_above_three_yuan():
    """当前真实 GO/budget（只读）互相一致，且额度远高于旧的 3.00 元硬限。"""
    tools = _tools()
    go = json.loads((ROOT / "docs" / "evidence" / "LOCAL-R1-20261101" / "PM" / "S2-LIVE-GO.json").read_text(encoding="utf-8"))
    budget = json.loads(REAL_BUDGET.read_text(encoding="utf-8"))
    limits = go["scope"]["stage_limits_cny"]
    assert limits["S2-DEV"] == pytest.approx(18.4)
    assert budget["stages"]["S2-DEV"] == pytest.approx(18.4)
    assert tools._resolve_stage_limit_cny(
        go_payload=go, budget_payload=budget, stage="S2-DEV", requested=None
    ) == pytest.approx(18.4)
    assert 18.4 > 3.0
    assert REAL_LEDGER.is_file()

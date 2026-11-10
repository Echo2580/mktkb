"""P1 #59：diff 发布放行必须重核**当前** gate 配置内容与审批证据（反例 + 合法场景）。

覆盖（review §7 #59 / p1-report 已知风险）：

- 缺当前 gate → ``current_gate_missing``，不再放行；
- 当前 gate 来自别的 run / suite / mode → ``current_gate_run_mismatch``；
- 当前 gate 退出码非 0 → ``current_gate_exit_<n>``；
- ``gate_version`` 不变但阈值内容变化（旧 gate 结果复用）→ ``gate_config_drift``；
- 审批后配置内容漂移（审批绑定旧配置）→ ``baseline_gate_config_drift``；
- 审批证据不可证明（run 目录缺 ``gate.json`` / 被改字节）→
  ``baseline_gate_config_unverifiable``（fail closed，不得靠伪造文件放行）；
- 跨版本即使有合法当前 gate 仍只分析 → ``explicit_cross_version_analysis_only``；
- 合法场景（同版本、已审批、当前 gate 绑定当前 run、配置哈希一致）仍 ``release_allowed=True``；
- ``RunDiff.to_dict()`` 字段结构不变（只新增 ``release_blocked_reason`` 取值）。

全部合成产物（``tmp_path``），零真实模型 / OCR / provider 调用；不读 var/、docs/evidence/。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mktkb.evaluation.baseline import approve_baseline, load_baseline, save_baseline
from mktkb.evaluation.gate import DEFAULT_GATE_CONFIG_PATH, GateConfig, load_gate_config
from mktkb.evaluation.report import RunDiff, diff_runs, require_release_baseline
from mktkb.evaluation.runner import RunResult

from .test_report import (
    CURRENT_CONFIG_HASH,
    baseline_run,
    current_run,
    make_gate,
    write_gate_json,
)

#: 当前默认 gate 配置（``diff_runs`` 不传 config 时加载）；内容哈希 = CURRENT_CONFIG_HASH。
CONFIG = load_gate_config(DEFAULT_GATE_CONFIG_PATH)

#: 放行阻断原因码的稳定契约（报告 / CI 只按字符串断言；新增取值不外扩字段结构）。
BLOCK_REASON_CODES = frozenset(
    {
        "explicit_cross_version_analysis_only",
        "baseline_unapproved",
        "baseline_gate_missing",
        "baseline_approval_gate_mismatch",
        "baseline_gate_config_unverifiable",
        "baseline_gate_config_drift",
        "current_gate_missing",
        "current_gate_run_mismatch",
        "current_gate_gate_version_mismatch",
        "current_gate_quality_missing",
        "gate_config_drift",
        "comparison_not_release",
    }
)

#: ``RunDiff.to_dict()`` 的字段结构（P1 修复只允许 ``release_blocked_reason`` 出现新取值）。
RUN_DIFF_KEYS = frozenset(
    {
        "baseline_id",
        "baseline_run_id",
        "run_id",
        "baseline_pipeline_version",
        "pipeline_version",
        "suite",
        "mode",
        "scope",
        "comparison",
        "release_allowed",
        "release_blocked_reason",
        "baseline_exit_code",
        "current_exit_code",
        "baseline_quality_status",
        "current_quality_status",
        "gate_exit_transition",
        "gate_exit_changed",
        "strata",
        "new_failures",
        "fixed_failures",
        "still_failing",
        "new_errors",
        "resolved_errors",
        "persistent_errors",
        "status_changes",
        "metric_deltas",
        "config_status",
        "gate_config_hash",
        "warnings",
        "empty",
    }
)


# --------------------------------------------------------------------------- #
# 装配
# --------------------------------------------------------------------------- #


def _approved_baseline(
    tmp_path: Path, *, write_evidence: bool = True
) -> tuple[object, Path, RunResult, object]:
    """同版本 baseline + 审批（approval 绑定具体一份 exit 0 门禁结果）。

    ``write_evidence=True`` 时把审批绑定的门禁结果落到 baseline run 目录 ``gate.json``
    （与 CLI ``gate`` 命令一致），放行路径据此重核审批时刻的配置哈希。
    """
    baseline = baseline_run(tmp_path)
    root = tmp_path / "baselines"
    saved = save_baseline(baseline, root)
    approval_gate = make_gate(0, quality_status="pass", run_id=baseline.manifest.run_id)
    approve_baseline(
        baseline,
        approval_gate,
        root,
        approver="owner",
        reason="fixture: release-gate consistency",
    )
    if write_evidence:
        write_gate_json(saved, approval_gate)
    return load_baseline(saved.baseline_id, root), root, baseline, approval_gate


def _current_gate(run: RunResult, **overrides):
    call = {"run_id": run.manifest.run_id, "quality_status": "pass"}
    call.update(overrides)
    return make_gate(0, **call)


def _write_changed_config(directory: Path) -> Path:
    """同 ``gate_version``，但阈值/样本内容变化 → ``config_hash`` 变化（内容漂移）。"""
    payload = json.loads(DEFAULT_GATE_CONFIG_PATH.read_text(encoding="utf-8"))
    payload["hard_gate_min_sample"] = {"b0": 33, "badcase": 13}
    path = directory / "gate_v0_1_changed.json"
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def _write_gate_payload(run: object, payload: dict) -> Path:
    directory = getattr(run, "out_dir", None) or getattr(run, "run_dir", None)
    assert directory is not None
    path = Path(directory) / "gate.json"
    path.write_bytes(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    )
    return path


def _assert_blocked(diff: RunDiff, code: str) -> None:
    assert diff.release_allowed is False, diff.to_dict()
    assert diff.release_blocked_reason == code
    # 原因码必须是稳定字符串契约的一部分（动态退出码用 current_gate_exit_<n> 前缀）。
    assert code in BLOCK_REASON_CODES or code.startswith("current_gate_exit_")
    with pytest.raises(ValueError):
        require_release_baseline(diff)


# --------------------------------------------------------------------------- #
# 合法场景：仍可放行
# --------------------------------------------------------------------------- #


def test_approved_current_gate_and_matching_config_releases(tmp_path: Path):
    baseline, _root, _base_run, _gate = _approved_baseline(tmp_path)
    current = current_run(tmp_path)
    diff = diff_runs(baseline, current, gate=_current_gate(current))

    assert diff.comparison == "release_baseline"
    assert diff.release_allowed is True
    assert diff.release_blocked_reason is None
    require_release_baseline(diff)


def test_run_diff_to_dict_structure_stays_stable(tmp_path: Path):
    baseline, _root, _base_run, _gate = _approved_baseline(tmp_path)
    current = current_run(tmp_path)
    payload = diff_runs(baseline, current, gate=_current_gate(current)).to_dict()

    assert set(payload) == RUN_DIFF_KEYS
    assert payload["release_allowed"] is True
    assert payload["release_blocked_reason"] is None
    assert payload["gate_config_hash"] == CURRENT_CONFIG_HASH


# --------------------------------------------------------------------------- #
# 反例：当前 gate 缺失 / 旧 run / 未通过质量层 / 版本漂移
# --------------------------------------------------------------------------- #


def test_missing_current_gate_blocks_release(tmp_path: Path):
    baseline, _root, _base_run, _gate = _approved_baseline(tmp_path)
    diff = diff_runs(baseline, current_run(tmp_path))  # 没传当前 gate
    _assert_blocked(diff, "current_gate_missing")
    assert diff.current_exit_code is None


def test_gate_from_previous_run_blocks_release(tmp_path: Path):
    baseline, _root, _base_run, _gate = _approved_baseline(tmp_path)
    current = current_run(tmp_path)
    stale = _current_gate(current, run_id="run-previous-release")
    _assert_blocked(diff_runs(baseline, current, gate=stale), "current_gate_run_mismatch")


@pytest.mark.parametrize(("field", "value"), [("suite", "badcase"), ("mode", "replay")])
def test_gate_bound_to_other_suite_or_mode_blocks_release(tmp_path: Path, field: str, value: str):
    baseline, _root, _base_run, _gate = _approved_baseline(tmp_path)
    current = current_run(tmp_path)
    wrong = _current_gate(current, **{field: value})
    _assert_blocked(diff_runs(baseline, current, gate=wrong), "current_gate_run_mismatch")


def test_failed_current_gate_blocks_release(tmp_path: Path):
    baseline, _root, _base_run, _gate = _approved_baseline(tmp_path)
    current = current_run(tmp_path)
    failing = make_gate(
        1,
        quality_status="pass",
        run_id=current.manifest.run_id,
        hard_failures=("citation_required",),
    )
    _assert_blocked(diff_runs(baseline, current, gate=failing), "current_gate_exit_1")


def test_current_gate_without_quality_layer_blocks_release(tmp_path: Path):
    baseline, _root, _base_run, _gate = _approved_baseline(tmp_path)
    current = current_run(tmp_path)
    quality_off = make_gate(0, quality=False, run_id=current.manifest.run_id)
    _assert_blocked(
        diff_runs(baseline, current, gate=quality_off), "current_gate_quality_missing"
    )


def test_current_gate_version_mismatch_blocks_release(tmp_path: Path):
    baseline, _root, _base_run, _gate = _approved_baseline(tmp_path)
    current = current_run(tmp_path)
    other_version = _current_gate(current, gate_version="mktkb.gate.v9.9")
    diff = diff_runs(baseline, current, gate=other_version)
    _assert_blocked(diff, "current_gate_gate_version_mismatch")
    assert other_version.gate_version != CONFIG.gate_version


# --------------------------------------------------------------------------- #
# 反例：同 gate_version 但阈值内容变化（旧 gate 结果 / 旧审批不得复用）
# --------------------------------------------------------------------------- #


def test_same_gate_version_but_changed_config_blocks_old_gate_result(tmp_path: Path):
    baseline, _root, _base_run, _gate = _approved_baseline(tmp_path)
    current = current_run(tmp_path)
    changed_config = load_gate_config(_write_changed_config(tmp_path))

    # 同 gate_version，仅内容（hard_gate_min_sample）变化 → config_hash 变化。
    assert changed_config.gate_version == CONFIG.gate_version
    assert changed_config.config_hash != CURRENT_CONFIG_HASH

    old_gate = _current_gate(current)  # 质量层仍记旧配置哈希
    diff = diff_runs(baseline, current, config=changed_config, gate=old_gate)
    _assert_blocked(diff, "gate_config_drift")


def test_config_drift_after_approval_blocks_release(tmp_path: Path):
    baseline, _root, _base_run, _gate = _approved_baseline(tmp_path)  # 审批时配置 = 旧内容
    current = current_run(tmp_path)
    changed_config: GateConfig = load_gate_config(_write_changed_config(tmp_path))
    # 当前 gate 按新配置重评：当前 gate 与当前 config 自洽，但审批绑定的是旧配置内容。
    new_gate = _current_gate(current, gate_config_hash=changed_config.config_hash)
    diff = diff_runs(baseline, current, config=changed_config, gate=new_gate)
    _assert_blocked(diff, "baseline_gate_config_drift")


# --------------------------------------------------------------------------- #
# 反例：审批证据不可证明 / 被篡改（fail closed）
# --------------------------------------------------------------------------- #


def test_approval_without_gate_evidence_is_unverifiable(tmp_path: Path):
    baseline, _root, _base_run, _gate = _approved_baseline(tmp_path, write_evidence=False)
    current = current_run(tmp_path)
    diff = diff_runs(baseline, current, gate=_current_gate(current))
    _assert_blocked(diff, "baseline_gate_config_unverifiable")


def test_tampered_gate_json_cannot_unlock_release(tmp_path: Path):
    baseline = baseline_run(tmp_path)
    root = tmp_path / "baselines"
    saved = save_baseline(baseline, root)
    approval_gate = make_gate(
        0,
        quality_status="pass",
        run_id=baseline.manifest.run_id,
        gate_config_hash="a" * 64,  # 审批时是旧配置内容（当前配置哈希不同）
    )
    approve_baseline(
        baseline, approval_gate, root, approver="owner", reason="fixture: tamper"
    )
    # 攻击者伪造 gate.json 里的配置哈希来“解锁”，但无法伪造审批绑定的 SHA-256。
    forged = approval_gate.to_dict()
    quality = dict(forged["quality"])
    quality["gate_config_hash"] = CURRENT_CONFIG_HASH
    forged["quality"] = quality
    _write_gate_payload(saved, forged)

    reloaded = load_baseline(saved.baseline_id, root)
    current = current_run(tmp_path)
    _assert_blocked(
        diff_runs(reloaded, current, gate=_current_gate(current)),
        "baseline_gate_config_unverifiable",
    )


def test_baseline_gate_snapshot_missing_blocks_release(tmp_path: Path):
    """approval 存在但门禁快照缺失（异常 baseline）：不得放行。"""
    baseline = baseline_run(tmp_path)
    root = tmp_path / "baselines"
    saved = save_baseline(baseline, root)
    approve_baseline(
        baseline,
        make_gate(0, quality_status="pass", run_id=baseline.manifest.run_id),
        root,
        approver="owner",
        reason="fixture",
    )
    payload = json.loads((root / saved.baseline_id / "baseline.json").read_text(encoding="utf-8"))
    payload["gate"] = None
    (root / saved.baseline_id / "baseline.json").write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    reloaded = load_baseline(saved.baseline_id, root)
    assert reloaded.approval is not None and reloaded.gate is None
    current = current_run(tmp_path)
    _assert_blocked(
        diff_runs(reloaded, current, gate=_current_gate(current)), "baseline_gate_missing"
    )


# --------------------------------------------------------------------------- #
# 跨版本：即使当前 gate 合法，也只分析不放行
# --------------------------------------------------------------------------- #


def test_cross_version_with_valid_current_gate_is_still_analysis_only(tmp_path: Path):
    baseline = baseline_run(tmp_path, pipeline_version="pipeline-p1")
    root = tmp_path / "baselines"
    saved = save_baseline(baseline, root)
    approve_baseline(
        baseline,
        make_gate(0, quality_status="pass", run_id=baseline.manifest.run_id),
        root,
        approver="owner",
        reason="fixture",
    )
    current = current_run(tmp_path, pipeline_version="pipeline-p2")
    diff = diff_runs(
        load_baseline(saved.baseline_id, root),
        current,
        compare_with=saved.baseline_id,
        gate=_current_gate(current),
    )
    assert diff.comparison == "explicit_cross_version"
    _assert_blocked(diff, "explicit_cross_version_analysis_only")

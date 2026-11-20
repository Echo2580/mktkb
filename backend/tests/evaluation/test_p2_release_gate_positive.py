"""正式门禁：合成证据齐备时必须可达通过（零真实请求）。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_TESTS_DIR = Path(__file__).resolve().parents[1]
for _path in (_TESTS_DIR, _TESTS_DIR.parent.parent / "backend" / "src"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from acceptance.support.netguard import t09_network_guard  # noqa: E402,F401
from evaluation.test_p2_release_gate_fixtures import (  # noqa: E402
    build_complete_inputs,
    write_inputs,
)
from mktkb.evaluation.p2_release_gate import evaluate_release_gate  # noqa: E402
from mktkb.evaluation.p2_release_model import (  # noqa: E402
    DECISION_BLOCKED,
    DECISION_OBSERVED,
    DECISION_PASS,
    DECISION_PENDING,
    R_APPLICABILITY_INVALID,
    R_CITATION_GROUNDING_MISSING,
    R_DUPLICATE_EVIDENCE,
    R_EVIDENCE_MISSING,
    R_PENDING_INPUT,
)

pytestmark = pytest.mark.usefixtures("t09_network_guard")


def _rows(result):  # noqa: ANN001
    return {row.row_id: row for row in result.rows}


def test_complete_synthetic_evidence_passes_gate(tmp_path):
    """齐备合成证据（真实登记 B0 + 合成 N/C/U/H2）可达 pass。"""
    path, _ = build_complete_inputs(tmp_path)
    result = evaluate_release_gate(path)
    assert result.decision == DECISION_PASS, [row.to_dict() for row in result.rows
                                              if row.decision != DECISION_PASS]
    assert result.to_dict()["release_allowed"] is False
    assert result.to_dict()["owner_release_decision"] == "not_decided"
    rows = _rows(result)
    for row_id in ("gate_config", "b0.admission", "b0.execution", "b0.quality", "b0.exact",
                   "b0.ocr", "hard_gates.b0", "candidate.pipeline", "negative", "boundary",
                   "u", "u.local", "h2.composition", "h2.source_proof", "h2.coverage",
                   "h2.strata", "h2.quality", "h2.hard_failures", "h2.required_axes",
                   "hard_gates"):
        assert rows[row_id].decision == DECISION_PASS, rows[row_id].to_dict()
    assert rows["negative"].detail["passed"] == 8
    assert rows["boundary"].detail["passed"] == 6
    assert rows["u"].detail["passed"] == 10


def test_three_h2_views_are_separated_and_c25_does_not_block(tmp_path):
    """必需轴 / 非必需轴 / 整卡 verified / 总门 四者分列；C25 非必需未知不阻断。"""
    path, _ = build_complete_inputs(tmp_path)
    result = evaluate_release_gate(path)
    rows = _rows(result)
    assert rows["h2.required_axes"].decision == DECISION_PASS
    assert rows["h2.required_axes"].detail["required_unknown"] == 0
    assert rows["h2.non_required_axes"].decision == DECISION_OBSERVED
    assert rows["h2.non_required_axes"].detail["non_required_unknown"] == 1
    assert rows["h2.non_required_axes"].detail["count_matches"] is True
    assert rows["h2.card_verified"].decision == DECISION_OBSERVED
    assert rows["h2.card_verified"].detail["verified"] is False  # 整卡如实 False
    assert result.decision == DECISION_PASS  # 但总门不受非必需轴影响


@pytest.mark.parametrize("section", ["public", "u", "h2"])
def test_removing_one_section_blocks_then_pending(tmp_path, section):
    """移除任一段输入：未标 PENDING -> 拒绝；标 PENDING -> 待交付（都不算通过）。"""
    path, payload = build_complete_inputs(tmp_path / "complete")
    broken = json.loads(json.dumps(payload))
    holder = broken["public"] if section == "public" else broken["u"] if section == "u" else broken["h2"]
    if section == "public":
        del broken["public"]
    elif section == "u":
        del broken["u"]
    else:
        del broken["h2"]
    missing = write_inputs(tmp_path / "missing.json", broken)
    blocked = evaluate_release_gate(missing)
    assert blocked.decision == DECISION_BLOCKED
    assert R_EVIDENCE_MISSING in {code for row in blocked.rows for code in row.reasons}

    marker = {"public": "PENDING-TASK3", "u": "PENDING-TASK3", "h2": "PENDING-TASK2"}[section]
    broken["pending"] = {section: marker}
    pending_path = write_inputs(tmp_path / "pending.json", broken)
    pending = evaluate_release_gate(pending_path)
    assert pending.decision == DECISION_PENDING
    assert R_PENDING_INPUT in {code for row in pending.rows for code in row.reasons}
    assert holder is not None


def test_u01_citation_gap_resolved_by_d004_as_observed(tmp_path):
    """D-004：引用落在同轮 evidence（retrieved 为空）→ 记 observed，不再阻断。

    判据仍是"引用必须落在已接地单元"：本用例的单元确实在同轮 evidence 里。
    """
    path, _ = build_complete_inputs(tmp_path, u_kwargs={"citation_gap": True})
    result = evaluate_release_gate(path)
    rows = _rows(result)
    assert rows["u.citation"].decision == DECISION_OBSERVED
    assert rows["u.citation"].detail["after_d004"].startswith("citation_required=pass")
    assert rows["u.hard_gates"].decision == DECISION_PASS
    assert result.decision == DECISION_PASS


def test_binding_proof_shows_original_and_corrected_views(tmp_path):
    """历史绑定：原始机械结果与修正视图必须同时出现，且证明可重算。"""
    path, _ = build_complete_inputs(tmp_path, public_kwargs={"with_binding": True})
    result = evaluate_release_gate(path)
    row = _rows(result)["binding.synthetic-public-n"]
    assert row.decision == DECISION_PASS
    assert row.detail["binding_correction_applied"] is True
    assert row.detail["recorded_index_revision"] != row.detail["attested_index_revision"]
    original = row.detail["original_mechanical"]
    corrected = row.detail["corrected_view"]
    assert original["binding_failures"], "原始机械失败必须保留"
    assert corrected["binding_failures"] == []
    assert row.detail["rewritten_trace_rows"] == len(original["binding_failures"])


def test_cli_entry_returns_zero_on_pass_and_four_on_pending(tmp_path, capsys):
    from mktkb.evaluation import cli

    path, _ = build_complete_inputs(tmp_path)
    out = tmp_path / "gate-result.json"
    assert cli.main(["p2-release-gate", "--inputs", str(path), "--out", str(out)]) == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["decision"] == "pass" and payload["release_allowed"] is False
    assert "question" not in json.dumps(payload, ensure_ascii=False)

    template = json.loads(path.read_text(encoding="utf-8"))
    del template["h2"]
    template["pending"] = {"h2": "PENDING-TASK2"}
    second = write_inputs(tmp_path / "pending.json", template)
    assert cli.main(["p2-release-gate", "--inputs", str(second)]) == cli.EXIT_PENDING
    capsys.readouterr()


def test_duplicate_u_case_ids_are_rejected(tmp_path):
    path, payload = build_complete_inputs(tmp_path)
    payload["u"]["real"]["case_ids"] = ["U01", "U01"]
    write_inputs(path, payload)
    result = evaluate_release_gate(path)
    assert result.decision == DECISION_BLOCKED
    assert R_DUPLICATE_EVIDENCE in {code for row in result.rows for code in row.reasons}


def test_forged_applicability_proof_is_rejected(tmp_path):
    path, payload = build_complete_inputs(tmp_path)
    proof = json.loads(Path(payload["public"]["runs"][0]["applicability"]["path"]).read_text(encoding="utf-8"))
    proof["derivation"]["statuses_sha256"] = "0" * 64
    forged = tmp_path / "forged-applicability.json"
    forged.write_text(json.dumps(proof, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    payload["public"]["runs"][0]["applicability"] = {
        "path": str(forged), "sha256": __import__("hashlib").sha256(forged.read_bytes()).hexdigest()}
    write_inputs(path, payload)
    result = evaluate_release_gate(path)
    assert result.decision == DECISION_BLOCKED
    reasons = {code for row in result.rows for code in row.reasons}
    assert R_APPLICABILITY_INVALID in reasons

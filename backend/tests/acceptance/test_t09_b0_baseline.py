"""T09-D1 / 交付物 1：完整 B0 的 L 层逐题执行（40 正常 + 8 无答案 + 6 歧义/冲突）。

执行口径（与《验收矩阵》§1、§3、§4 一致）：
- 只做 L 层：真实本地解析器、SQLite、HTTP 接口、worker、检索；模型与 OCR 为受控替身（0 次真实调用）；
- B0 严格按 ``manifest.b0_initialization`` 的 33 步建立：V03 历史 V1 → D01 业务 V2 同槽，其余 8 份首次导入；
- 逐题新建会话（避免上一题上下文污染），记录 id/expected/actual/source/status/provider/environment；
- 通过条件不改：40 题答对 ≥36、Q01～Q24 精确题全对、N01～N08 全过、C01～C06 全过。
"""

from __future__ import annotations

import json

import pytest

from support import b0, evidence, ocr_transcripts
from support.netguard import t09_network_guard  # noqa: F401 - 作为模块级 fixture 暴露

pytestmark = pytest.mark.usefixtures("t09_network_guard")

QUESTIONS = evidence.load_questions()
BY_GROUP: dict[str, list[dict]] = {}
for _item in QUESTIONS:
    BY_GROUP.setdefault(_item["group"], []).append(_item)

# 《验收矩阵》§3/§4 正文写明的否定要求（冻结题集未单列，故在此显式声明；未修改任何输入文件）：
# - Q39/Q40：只能取城东店行，"不取城西店行"；
# - N08：首版范围外，"不能声称完成实物定位"。
FORBIDDEN_VALUES: dict[str, list[str]] = {
    "Q39": ["2026-10-31 15:30"],
    "Q40": ["城西店二层仓库"],
}
FORBID_PHRASES: dict[str, tuple[str, ...]] = {
    "N08": ("照片中", "已定位", "未标记物品位于"),
}


def _write_questions(name: str, records: list[dict]) -> None:
    evidence.dump_json(f"actual/b0/questions-{name}.json", records)


@pytest.fixture(scope="module")
def environment_facts():
    return {
        "environment": evidence.environment(),
        "fixture_shapes": ocr_transcripts.verify_fixture_shapes(),
    }


@pytest.fixture(scope="module")
def b0_case(tmp_path_factory, environment_facts):
    """建立 B0（保留活跃实例）并同时产出可供后续用例独立恢复的快照。"""
    work = tmp_path_factory.mktemp("t09-b0")
    build_dir = work / "build"
    live = b0.build_b0(build_dir)
    invariants = b0.assert_b0_invariants(live)
    facts = b0.b0_facts(live)
    employee = live.harness.employee()
    b0.checkpoint_and_dispose(live.harness)
    snapshot = b0.snapshot_b0(build_dir, work / "snapshot")
    reopened = b0.new_harness(build_dir)
    case = {
        "work": work,
        "snapshot": snapshot,
        "build_dir": build_dir,
        "harness": reopened,
        "admin": reopened.admin(),
        "employee": reopened.employee(),
        "facts": facts,
        "invariants": invariants,
        "employee_ready": employee is not None,
        "environment": environment_facts["environment"],
        "fixture_shapes": environment_facts["fixture_shapes"],
    }
    yield case
    reopened.close()


def test_t09_b0_structure_and_ocr_ledger(b0_case):
    """B0 结构不变量 + 受控 OCR 逐次调用/页码台账。"""
    facts = b0_case["facts"]
    invariants = b0_case["invariants"]
    shapes = b0_case["fixture_shapes"]

    assert invariants["positions_versions"] == 2
    assert invariants["positions_v1_state"] == "superseded"
    assert invariants["positions_v1_sha256"] == b0.FILE_INDEX["V03"]["sha256"]
    assert invariants["positions_v2_number"] == 2
    assert invariants["positions_v2_sha256"] == b0.FILE_INDEX["D01"]["sha256"]
    assert all(item["active_number"] == 1 for item in invariants["other_slots"].values())

    assert len(facts["steps"]) == 33, facts["steps"]
    assert len(facts["slots"]) == 10, facts["slots"]
    # B0 阶段不调用模型（只导入/处理/发布）
    assert facts["model_calls"] == 0, facts["model_calls"]

    by_file: dict[str, list[int]] = {}
    for call in facts["ocr_calls"]:
        by_file.setdefault(call["file"], []).append(call["page"])
        assert call["transcript_found"] is True
        assert call["content_bytes"] > 0
        assert len(call["content_sha256"]) == 64
    assert by_file.get("D07") == list(range(1, 9)), by_file
    assert by_file.get("D08") == [1, 2], by_file
    assert by_file.get("D09") == [1], by_file
    assert by_file.get("D10") == [1], by_file
    assert len(facts["ocr_calls"]) == 12, facts["ocr_calls"]
    # 文本型 PDF/Office 不走 OCR
    assert set(by_file) == {"D07", "D08", "D09", "D10"}, by_file
    # D10 为规则表格图片：记录产品实际选择的 OCR 模式（模式不参与通过判定，但必须留痕）
    d10 = [call for call in facts["ocr_calls"] if call["file"] == "D10"]
    assert len(d10) == 1, d10
    assert d10[0]["mode"] in {"text", "table"}, d10
    d07 = [call for call in facts["ocr_calls"] if call["file"] == "D07"]
    assert all(call["mode"] == "text" for call in d07), d07

    evidence.dump_json(
        "actual/b0/b0-initialization.json",
        {
            "layer": evidence.LAYER,
            "provider": evidence.PROVIDER_TAG,
            "environment": b0_case["environment"],
            "fixture_shapes": shapes,
            "facts": facts,
            "invariants": invariants,
            "ocr_semantics": "受控替身只替代 OCR 识别结果；文本/表格为 fixtures 绘制事实的受控转录（support/ocr_transcripts.py）。"
            "真实 OCR 识别质量仍未验证（R 层）。",
        },
    )


def _run_group(b0_case, items: list[dict], name: str) -> list[dict]:
    employee = b0_case["employee"]
    records = []
    for item in items:
        conversation = b0.new_conversation(employee, f"T09-{item['id']}")
        response = b0.ask(employee, conversation, item["question"])
        record = b0.evaluate(
            item,
            response,
            environment=b0_case["environment"],
            forbidden_values=FORBIDDEN_VALUES.get(item["id"]),
            forbid_phrases=FORBID_PHRASES.get(item["id"], ()),
        )
        record["conversation"] = conversation
        records.append(record)
    _write_questions(name, records)
    return records


def test_t09_b0_q01_q40_normal(b0_case):
    records = _run_group(b0_case, BY_GROUP["normal"], "normal")
    summary = b0.summarize(records)
    assert summary["exact_correct"] == 24, summary["exact_failures"]
    assert summary["normal_correct"] >= 36, summary["normal_failures"]


def test_t09_b0_n01_n08_negative(b0_case):
    records = _run_group(b0_case, BY_GROUP["negative"], "negative")
    summary = b0.summarize(records)
    assert summary["negative_passed"] == 8, summary["negative_failures"]


def test_t09_b0_c01_c04_ambiguity_in_clean_b0(b0_case):
    """C01～C04 在无冲突 B0 上执行；C05/C06 另用独立快照（不污染正常 B0）。"""
    items = [item for item in BY_GROUP["ambiguity_conflict"] if item["scenario"].get("expected_kind") == "clarification"]
    records = _run_group(b0_case, items, "ambiguity-clean")
    assert len(records) == 4, [record["id"] for record in records]
    failures = [record["id"] for record in records if record["status"] != "pass"]
    assert not failures, failures


def _conflict_case(b0_case, item: dict, variant: str) -> dict:
    """独立恢复一份 B0 快照，发布附加语料后提问；不与正常 B0 共用数据库。"""
    dest = b0_case["work"] / f"conflict-{item['id']}"
    harness = b0.restore_b0(b0_case["snapshot"], dest)
    try:
        admin = harness.admin()
        receipt = admin.upload(path=b0.fixture_path(variant), allow_same_name=False)
        assert receipt.status_code == 202, receipt.text
        record = receipt.json()
        harness.ocr.unbind()  # V01/V02 为文字型 PDF，不应调用 OCR
        result = harness.run_job()
        assert result.state == "succeeded", result
        assert harness.ocr.summary() == [], "文字型 PDF 不得调用 OCR"
        detail = harness.detail(record["document"]["id"])
        active = detail["document"]["active_version"]
        response = admin.client.post(
            f"/api/v1/documents/{record['document']['id']}/versions/{record['version']['id']}/publish",
            json={"expected_active_version_id": active["id"] if active else None, "expected_revision": detail["revision"]},
            headers=admin.headers,
        )
        assert response.status_code == 200, response.text

        employee = harness.employee()
        conversation = b0.new_conversation(employee, f"T09-{item['id']}")
        answer = b0.ask(employee, conversation, item["question"])
        graded = b0.evaluate(item, answer, environment=b0_case["environment"])
        graded["conversation"] = conversation
        graded["setup"] = {"variant": variant, "document": record["document"]["id"], "version": record["version"]["id"]}
        return graded
    finally:
        harness.close()


def test_t09_b0_c05_conflict_extra_notice(b0_case):
    item = next(entry for entry in BY_GROUP["ambiguity_conflict"] if entry["id"] == "C05")
    record = _conflict_case(b0_case, item, "V01")
    _write_questions("conflict-c05", [record])
    assert record["status"] == "pass", record["problems"]


def test_t09_b0_c06_conflict_phone_notice(b0_case):
    item = next(entry for entry in BY_GROUP["ambiguity_conflict"] if entry["id"] == "C06")
    record = _conflict_case(b0_case, item, "V02")
    _write_questions("conflict-c06", [record])
    assert record["status"] == "pass", record["problems"]


def test_t09_b0_merged_summary_and_thresholds():
    """从已落盘证据重算，逐项核对矩阵阈值（计数来自实际结果，不来自报告标题）。"""
    groups = ["normal", "negative", "ambiguity-clean", "conflict-c05", "conflict-c06"]
    records: list[dict] = []
    for name in groups:
        path = evidence.EVIDENCE_ROOT / "actual" / "b0" / f"questions-{name}.json"
        assert path.exists(), f"缺少证据文件：{path}"
        records.extend(json.loads(path.read_text(encoding="utf-8")))
    evidence.dump_json("actual/b0/questions.json", records)
    summary = b0.summarize(records)
    evidence.dump_json("actual/b0/summary.json", {"summary": summary, "environment": evidence.environment()})

    assert summary["normal_total"] == 40
    assert summary["normal_correct"] >= 36, summary["normal_failures"]
    assert summary["exact_correct"] == 24, summary["exact_failures"]
    assert summary["negative_passed"] == 8, summary["negative_failures"]
    assert summary["ambiguity_passed"] == 6, summary["ambiguity_failures"]

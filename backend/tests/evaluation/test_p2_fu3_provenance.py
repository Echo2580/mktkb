"""FU-3：N/C/U 送检清单的默认回源校验（题目 / 证据 / trace / U 类型）正反例。

对照物是任务 3 的既有脚本 ``docs/reports/OBS-EVAL/P2/NCU-RELEASE-EVIDENCE/scripts/
verify_manifest.py``（只读复用其判定语义，本文件用"同一份合成清单跑两个实现"验证一致）。

覆盖任务书 §4 要求的负例：合法十六进制但内容错配的题目摘要、缺失/越界证据路径、摘要不符、
同 run 不同回合（同题面）trace 互换、跨 run trace、U 真实/本地类型混用；以及"缺权威来源"
（清单不是对象 / trace 库不可读）时的阻断。正例保留 N/C/U 原始分母与既有采信口径。
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping

import pytest

_TESTS_DIR = Path(__file__).resolve().parents[1]
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

from acceptance.support.netguard import t09_network_guard  # noqa: E402,F401  (pytest fixture)

from mktkb.evaluation.p2_release_model import (  # noqa: E402
    DECISION_BLOCKED,
    R_DIGEST_MISMATCH,
    R_DUPLICATE_EVIDENCE,
    R_EVIDENCE_MISSING,
    R_IDENTITY_MISMATCH,
)
from mktkb.evaluation.p2_release_provenance import (  # noqa: E402
    check_evidence_provenance,
    provenance_rows,
)

pytestmark = pytest.mark.usefixtures("t09_network_guard")

ROOT = Path(__file__).resolve().parents[3]
VERIFY_SCRIPT = (
    ROOT / "docs/reports/OBS-EVAL/P2/NCU-RELEASE-EVIDENCE/scripts/verify_manifest.py"
)
EXTERNAL_RUNS = Path(r"D:\mktkb-p2-run\t207")

GROUP_TOTALS = {"N": 8, "C": 6, "U": 10}
QUESTION = {
    "N01": "火星店的宣传海报在哪里？",
    "N02": "城东店的营业时间是什么？",
}
N_IDS = tuple(f"N{i:02d}" for i in range(1, 9))
C_IDS = tuple(f"C{i:02d}" for i in range(1, 7))
U_IDS = tuple(f"U{i:02d}" for i in range(1, 11))


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha_text(text: str) -> str:
    return _sha(text.encode("utf-8"))


def _write(path: Path, data: str | bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, str):
        path.write_text(data, encoding="utf-8")
    else:
        path.write_bytes(data)
    return _sha(path.read_bytes())


def _write_jsonl(path: Path, rows: list[Mapping[str, Any]]) -> str:
    return _write(
        path,
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
    )


def _trace_db(path: Path, traces: list[Mapping[str, Any]]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    con = sqlite3.connect(path)
    try:
        con.execute(
            "create table traces(trace_id TEXT, run_id TEXT, question_hash TEXT, "
            "config_hash TEXT, pipeline_version TEXT, dataset_version TEXT, "
            "index_revision TEXT, path TEXT, outcome_kind TEXT, manifest_sha256 TEXT)"
        )
        con.executemany(
            "insert into traces values(:trace_id,:run_id,:question_hash,:config_hash,"
            ":pipeline_version,:dataset_version,:index_revision,:path,:outcome_kind,"
            ":manifest_sha256)",
            traces,
        )
        con.commit()
    finally:
        con.close()
    return _sha(path.read_bytes())


class Fixture:
    """一份自洽的 N/C/U 合成送检清单 + 其证据树（放在 pytest 临时目录里）。"""

    def __init__(self, tmp: Path) -> None:
        self.tmp = tmp
        self.root = tmp / "repo"
        self.ncu = self.root / "docs/reports/ncu"
        self.run_dir = self.ncu / "run1"
        self.ext = tmp / "ext/r1"
        self.data = self.ext / "data"
        self.controls_path = self.ncu / "u-controls.json"
        self.test_file = self.root / "backend/tests/acceptance/test_mut.py"
        self.manifest: dict[str, Any] = {}

    # ------------------------------------------------------------------ 组装
    def build(self) -> "Fixture":
        questions = {case_id: QUESTION["N01"] for case_id in (*N_IDS, *C_IDS, *U_IDS[:1])}
        questions.update({case_id: QUESTION["N02"] for case_id in U_IDS[1:]})
        questions["N02"] = QUESTION["N02"]
        frozen_rel = Path("docs/reports/ncu/frozen/R1.jsonl")
        dataset_abs = self.ext / "p2-run" / "dataset.jsonl"
        cases_abs = self.run_dir / "cases.jsonl"
        traces_db = self.data / "observability" / "qa-traces.sqlite3"
        rag_db = self.data / "rag-index.sqlite3"
        manifest_rel = Path("docs/reports/ncu/run1/run_manifest.json")
        scores_rel = Path("docs/reports/ncu/scoring/case_scores.json")

        frozen_sha = _write_jsonl(
            self.root / frozen_rel,
            [{"case_id": cid, "question": question} for cid, question in questions.items()],
        )
        dataset_sha = _write_jsonl(
            dataset_abs,
            [{"case_id": cid, "question": question} for cid, question in questions.items()],
        )
        config_hash = "a" * 64
        pipeline = "p-synthetic"
        dataset_version = "ds-synthetic"
        corpus = "c" * 64
        self.manifest = {
            "schema_version": "ncu-manifest/v0.2",
            "runs": {
                "R1": {
                    "run_id": "run-r1",
                    "run_dir": "docs/reports/ncu/run1",
                    "plan_sha256": "d" * 64,
                    "config_hash": config_hash,
                    "pipeline_version": pipeline,
                    "index_revision_binding": 3,
                    "dataset_version": dataset_version,
                    "corpus_manifest_sha256": corpus,
                }
            },
            "tallies": {},
            "cases": [],
        }
        traces: list[dict[str, Any]] = []
        case_rows: list[dict[str, Any]] = []
        for order, (cid, question) in enumerate(questions.items()):
            trace_id = f"trace-{cid}"
            traces.append({
                "trace_id": trace_id,
                "run_id": "run-r1",
                "question_hash": _sha_text(question),
                "config_hash": config_hash,
                "pipeline_version": pipeline,
                "dataset_version": dataset_version,
                "index_revision": "4",
                "path": "rag",
                "outcome_kind": "not_found",
                "manifest_sha256": corpus,
            })
            case_rows.append({
                "case_id": cid,
                "run_id": "run-r1",
                "turns": [{
                    "trace_id": trace_id,
                    "product": {"question_sha256": _sha_text(question)},
                }],
            })
        cases_sha = _write_jsonl(cases_abs, case_rows)
        trace_sha = _trace_db(traces_db, traces)
        manifest_sha = _write(
            self.root / manifest_rel,
            json.dumps({"run_id": "run-r1"}, ensure_ascii=False) + "\n",
        )
        scores_sha = _write(self.root / scores_rel, "{}\n")
        rag_sha = _write(rag_db, b"synthetic-rag-index")
        controls = {
            "schema_version": "p2-u-local-controls/v0.1",
            "cases": {cid: {"case_id": cid, "status": "pass"} for cid in U_IDS},
        }
        controls_sha = _write(
            self.controls_path, json.dumps(controls, ensure_ascii=False, indent=1) + "\n"
        )
        test_sha = _write(self.test_file, "def test_mut():\n    assert True\n")

        for cid, question in questions.items():
            group = cid[0]
            if cid in U_IDS and cid != "U01":
                continue  # U02–U10 走 L 档
            case: dict[str, Any] = {
                "case_id": cid,
                "group": group,
                "suite": {"N": "negative", "C": "boundary", "U": "update_delete"}[group],
                "stratum": "synthetic",
                "expected_kind": "answer" if group == "U" else "not_found",
                "should_refuse": group != "U",
                "basis": "R",
                "run_id": "run-r1",
                "run_dir": "docs/reports/ncu/run1",
                "plan_sha256": "d" * 64,
                "config_hash": config_hash,
                "pipeline_version": pipeline,
                "index_revision_binding": 3,
                "index_revision_trace": 4,
                "index_revision_rag": 4,
                "trace_id": f"trace-{cid}",
                "trace_path": "rag",
                "trace_outcome": "not_found",
                "question_sha256": _sha_text(question),
                "gates": {"citation_required": {"status": "pass"}} if group == "U" else {},
                "check_evidence": {"source_hit": True} if group == "U" else {},
                "adopt": "ADOPTED",
                "evidence_paths": {
                    "run_cases": cases_abs.as_posix(),
                    "run_dataset": dataset_abs.as_posix(),
                    "frozen_cases": (self.root / frozen_rel).as_posix(),
                    "trace_db": traces_db.as_posix(),
                    "run_manifest": (self.root / manifest_rel).as_posix(),
                    "run_result": (self.root / scores_rel).as_posix(),
                    "rag_index": rag_db.as_posix(),
                },
                "evidence_sha256": {
                    "run_cases": cases_sha,
                    "run_dataset": dataset_sha,
                    "frozen_cases": frozen_sha,
                    "trace_db": trace_sha,
                    "run_manifest": manifest_sha,
                    "run_result": scores_sha,
                    "rag_index": rag_sha,
                },
            }
            self.manifest["cases"].append(case)
        for cid in U_IDS[1:]:
            self.manifest["cases"].append({
                "case_id": cid,
                "group": "U",
                "suite": "update_delete",
                "stratum": "synthetic",
                "basis": "L",
                "test_file": "backend/tests/acceptance/test_mut.py",
                "test_file_sha256": test_sha,
                "historical": {
                    "status": "pass",
                    "exit_code": 0,
                    "tests": [{"name": "test_mut", "status": "pass"}],
                },
                "rerun": {"command": "pytest ...", "exit_code": 0, "passed": 13, "failed": 0},
                "gates": {"citation_required": {"status": "pass"}},
                "check_evidence": {"source_hit": True},
                "adopt": "ADOPTED",
                "evidence_paths": {
                    "test_file": "backend/tests/acceptance/test_mut.py",
                    "u_controls": self.controls_path.relative_to(self.root).as_posix(),
                },
                "evidence_sha256": {
                    "test_file": test_sha,
                    "u_controls": controls_sha,
                },
            })
        return self

    # ------------------------------------------------------------------ 输入
    def inputs(self) -> SimpleNamespace:
        return SimpleNamespace(
            evidence_manifest=SimpleNamespace(
                role="evidence_manifest.manifest",
                path=self.ncu / "manifest.json",
                sha256="0" * 64,
                payload=self.manifest,
            ),
            public_runs=(SimpleNamespace(
                run_id="run-r1",
                run_dir=self.run_dir,
                manifest={"dataset_version": "ds-synthetic",
                          "corpus_manifest_sha256": "c" * 64},
                rag_db=SimpleNamespace(path=self.data / "rag-index.sqlite3"),
            ),),
            u_real=None,
            u_controls=SimpleNamespace(
                payload=json.loads(self.controls_path.read_text(encoding="utf-8")),
                path=self.controls_path,
                sha256="0" * 64,
            ),
            pending={},
        )

    def report(self) -> Any:
        return check_evidence_provenance(self.inputs(), project_root=self.root)

    def case(self, case_id: str) -> dict[str, Any]:
        for item in self.manifest["cases"]:
            if item["case_id"] == case_id:
                return item
        raise KeyError(case_id)


@pytest.fixture
def fixture(tmp_path: Path) -> Fixture:
    return Fixture(tmp_path).build()


def _codes(report: Any) -> set[str]:
    return {str(problem.get("code")) for problem in report.problems}


# --------------------------------------------------------------------------- #
# 1. 正例：N/C/U 分母齐全时全部通过
# --------------------------------------------------------------------------- #


def test_positive_manifest_passes_all_provenance_checks(fixture: Fixture) -> None:
    report = fixture.report()
    assert report.problems == [], report.problems
    assert report.cases_checked == 24
    assert report.files_checked == report.files_verified
    assert report.traces_checked == 15
    assert (report.u_real_cases, report.u_local_cases) == (1, 9)
    rows = provenance_rows(report)
    assert [row.row_id for row in rows] == [
        "evidence_provenance", "evidence_provenance.u_types",
    ]
    assert rows[0].decision == "pass"
    assert rows[1].decision == "observed"
    assert rows[1].detail["u_local_cases"] == 9


# --------------------------------------------------------------------------- #
# 2. 负例：题目摘要（合法十六进制但内容错配 / 非法形态）
# --------------------------------------------------------------------------- #


def test_question_digest_content_mismatch_is_blocked(fixture: Fixture) -> None:
    case = fixture.case("N01")
    # 合法 64 位小写十六进制，但内容是另一道题的摘要（不是格式问题）。
    case["question_sha256"] = _sha_text("城北店的宣传海报在哪里？")
    report = fixture.report()
    assert "QUESTION_HASH_MISMATCH" in _codes(report)
    rows = provenance_rows(report)
    assert rows[0].decision == DECISION_BLOCKED
    assert R_DIGEST_MISMATCH in rows[0].reasons


def test_question_digest_shape_is_blocked(fixture: Fixture) -> None:
    fixture.case("N02")["question_sha256"] = "not-a-digest"
    report = fixture.report()
    assert "QUESTION_HASH_MISMATCH" in _codes(report)


# --------------------------------------------------------------------------- #
# 3. 负例：证据路径缺失 / 越界 / 摘要不符 / 未声明
# --------------------------------------------------------------------------- #


def test_missing_evidence_path_is_blocked(fixture: Fixture) -> None:
    fixture.case("N01")["evidence_paths"]["run_result"] = "docs/reports/ncu/nope.json"
    fixture.case("N01")["evidence_sha256"]["run_result"] = "0" * 64
    report = fixture.report()
    assert "EVIDENCE_PATH_MISSING" in _codes(report)
    assert R_EVIDENCE_MISSING in provenance_rows(report)[0].reasons


def test_evidence_path_outside_approved_roots_is_blocked(fixture: Fixture) -> None:
    outside = fixture.tmp / "outside.txt"
    outside.write_text("secret\n", encoding="utf-8")
    case = fixture.case("N01")
    case["evidence_paths"]["run_result"] = outside.as_posix()
    case["evidence_sha256"]["run_result"] = _sha(outside.read_bytes())
    report = fixture.report()
    assert "EVIDENCE_PATH_OUT_OF_ROOT" in _codes(report)


def test_relative_escape_path_is_blocked(fixture: Fixture) -> None:
    case = fixture.case("N01")
    case["evidence_paths"]["run_result"] = "../../../../outside.txt"
    report = fixture.report()
    assert "EVIDENCE_PATH_OUT_OF_ROOT" in _codes(report)


def test_evidence_digest_mismatch_is_blocked(fixture: Fixture) -> None:
    fixture.case("N01")["evidence_sha256"]["run_cases"] = "1" * 64
    report = fixture.report()
    assert "EVIDENCE_SHA_MISMATCH" in _codes(report)
    assert R_DIGEST_MISMATCH in provenance_rows(report)[0].reasons


def test_evidence_digest_missing_is_blocked(fixture: Fixture) -> None:
    fixture.case("N01")["evidence_sha256"].pop("run_dataset")
    report = fixture.report()
    assert "EVIDENCE_SHA_MISSING" in _codes(report)


def test_required_authority_declaration_missing_is_blocked(fixture: Fixture) -> None:
    case = fixture.case("N01")
    case["evidence_paths"].pop("trace_db")
    case["evidence_sha256"].pop("trace_db")
    report = fixture.report()
    assert "EVIDENCE_NOT_DECLARED" in _codes(report)


def test_unreadable_trace_db_is_blocked_not_passed(fixture: Fixture) -> None:
    case = fixture.case("N01")
    case["evidence_paths"]["trace_db"] = "docs/reports/ncu/not-a-db.sqlite3"
    case["evidence_sha256"]["trace_db"] = "2" * 64
    (fixture.root / "docs/reports/ncu/not-a-db.sqlite3").write_text("x", encoding="utf-8")
    case["evidence_sha256"]["trace_db"] = _sha(
        (fixture.root / "docs/reports/ncu/not-a-db.sqlite3").read_bytes()
    )
    report = fixture.report()
    assert "SOURCE_UNAVAILABLE" in _codes(report)
    assert R_EVIDENCE_MISSING in provenance_rows(report)[0].reasons


# --------------------------------------------------------------------------- #
# 4. 负例：trace 互换（同 run 不同回合 / 跨 run）与重复
# --------------------------------------------------------------------------- #


def test_same_run_different_turn_trace_swap_is_blocked(fixture: Fixture) -> None:
    # 同 run、同题面：两条 trace 的 question_hash/run_id/身份全同，只有"该题原始行
    # 记录的 trace_id"能把它们分开 —— 这正是同 run/同题面互换的检测点。
    first, second = fixture.case("N01"), fixture.case("N02")
    first["question_sha256"] = second["question_sha256"] = _sha_text("同一题面")
    db = sqlite3.connect(fixture.data / "observability" / "qa-traces.sqlite3")
    try:
        db.execute("update traces set question_hash=?", (_sha_text("同一题面"),))
        db.commit()
    finally:
        db.close()
    fixture.case("N01")["evidence_sha256"]["trace_db"] = _sha(
        (fixture.data / "observability" / "qa-traces.sqlite3").read_bytes()
    )
    fixture.case("N02")["evidence_sha256"]["trace_db"] = _sha(
        (fixture.data / "observability" / "qa-traces.sqlite3").read_bytes()
    )
    first["trace_id"], second["trace_id"] = second["trace_id"], first["trace_id"]
    report = fixture.report()
    assert "TRACE_CASE_MISMATCH" in _codes(report)
    assert any(
        problem.get("name") == "trace_id_not_in_case_row" for problem in report.problems
    )


def test_cross_run_trace_is_blocked(fixture: Fixture) -> None:
    case = fixture.case("N01")
    case["run_id"] = "run-other"
    inputs = fixture.inputs()
    report = check_evidence_provenance(inputs, project_root=fixture.root)
    assert "TRACE_CASE_MISMATCH" in _codes(report) or "TRACE_NOT_IN_RUN" in _codes(report)


def test_duplicate_trace_id_is_blocked(fixture: Fixture) -> None:
    fixture.case("N02")["trace_id"] = fixture.case("N01")["trace_id"]
    report = fixture.report()
    assert "TRACE_DUPLICATE" in _codes(report)
    assert R_DUPLICATE_EVIDENCE in provenance_rows(report)[0].reasons


def test_trace_identity_mismatch_is_blocked(fixture: Fixture) -> None:
    fixture.case("N01")["config_hash"] = "b" * 64
    report = fixture.report()
    assert "TRACE_IDENTITY_MISMATCH" in _codes(report)
    assert R_IDENTITY_MISMATCH in provenance_rows(report)[0].reasons


# --------------------------------------------------------------------------- #
# 5. 负例：U 真实/本地类型混用与受控映射不完整
# --------------------------------------------------------------------------- #


def test_l_basis_with_run_evidence_is_blocked(fixture: Fixture) -> None:
    fixture.case("U02")["run_id"] = "run-r1"
    report = fixture.report()
    assert "U_TYPE_MIXED" in _codes(report)


def test_r_basis_with_local_control_fields_is_blocked(fixture: Fixture) -> None:
    fixture.case("U01")["rerun"] = {"exit_code": 0, "passed": 1, "failed": 0}
    report = fixture.report()
    assert "U_TYPE_MIXED" in _codes(report)


def test_l_control_rerun_failure_is_blocked(fixture: Fixture) -> None:
    fixture.case("U03")["rerun"]["failed"] = 1
    report = fixture.report()
    assert "U_CONTROL_INCOMPLETE" in _codes(report)
    assert R_EVIDENCE_MISSING in provenance_rows(report)[0].reasons


def test_l_control_not_in_local_controls_is_blocked(fixture: Fixture) -> None:
    fixture.case("U04")["case_id"] = "U99"
    report = fixture.report()
    assert "U_CONTROL_INCOMPLETE" in _codes(report)


# --------------------------------------------------------------------------- #
# 6. 与既有 verify_manifest.py 的一致性（同一份合成清单，两实现同判）
# --------------------------------------------------------------------------- #


def _run_reference_script(manifest: Mapping[str, Any], fixture: Fixture,
                          tmp: Path) -> tuple[int, dict[str, Any]]:
    path = tmp / "manifest.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    env = dict(os.environ)
    env["NCU_REPO_ROOT"] = str(fixture.root)
    env["PYTHONIOENCODING"] = "utf-8"
    result = subprocess.run(
        [sys.executable, "-X", "utf8", str(VERIFY_SCRIPT), str(path)],
        capture_output=True, text=True, encoding="utf-8", env=env, cwd=str(fixture.root),
        check=False,
    )
    payload = json.loads(result.stdout.strip() or "{}")
    return result.returncode, payload


def test_reference_script_agrees_on_positive_and_digest_negative(
    fixture: Fixture, tmp_path: Path
) -> None:
    fixture.manifest["tallies"] = {
        "judged_pass": {"N": "8/8", "C": "6/6", "U": "10/10"},
        "adopted_unconditional": {"N": 8, "C": 6, "U": 10},
        "adopted_with_binding_proof": {"N": 0, "C": 0, "U": 0},
        "adopted_formal_total": {"N": 8, "C": 6, "U": 10},
    }
    code, payload = _run_reference_script(fixture.manifest, fixture, tmp_path)
    assert (code, payload.get("ok")) == (0, True), payload
    assert fixture.report().problems == []

    tampered = copy.deepcopy(fixture.manifest)
    for case in tampered["cases"]:
        if case["case_id"] == "N01":
            case["question_sha256"] = _sha_text("别的题面")
    code, payload = _run_reference_script(tampered, fixture, tmp_path)
    assert code == 1 and payload.get("ok") is False
    assert any("QUESTION_HASH_MISMATCH" in item for item in payload.get("errors") or [])
    fixture.manifest = tampered
    assert "QUESTION_HASH_MISMATCH" in _codes(fixture.report())


# --------------------------------------------------------------------------- #
# 7. 缺权威来源：清单不是对象
# --------------------------------------------------------------------------- #


def test_non_object_manifest_is_blocked(fixture: Fixture) -> None:
    inputs = fixture.inputs()
    inputs.evidence_manifest.payload = []
    report = check_evidence_provenance(inputs, project_root=fixture.root)
    assert "SOURCE_UNAVAILABLE" in _codes(report)
    assert provenance_rows(report)[0].decision == DECISION_BLOCKED


# --------------------------------------------------------------------------- #
# 8. 正式入口默认执行（真实任务 3 清单 + 篡改副本；需本机历史 run 只读证据）
# --------------------------------------------------------------------------- #


@pytest.mark.skipif(not (EXTERNAL_RUNS / "R2").is_dir(),
                    reason="需要本机历史 run 的 rag/trace 库（仓外）")
def test_gate_entry_runs_provenance_by_default(tmp_path: Path) -> None:
    import importlib.util

    script = ROOT / "docs/reports/OBS-EVAL/P2/CROSS-SCENARIO-GATE/scripts/wire_real_ncu.py"
    spec = importlib.util.spec_from_file_location("wire_real_ncu_fu3", script)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    work = tmp_path / "real"
    work.mkdir()
    inputs_path, payload = module.build_inputs(work)

    from mktkb.evaluation.p2_release_gate import evaluate_release_gate

    first = evaluate_release_gate(inputs_path)
    rows = {row.row_id: row for row in first.rows}
    assert rows["evidence_provenance"].decision == "pass", rows["evidence_provenance"].detail

    # 篡改：一个合法十六进制但内容错配的题目摘要 → 正式入口默认阻断。
    manifest_path = ROOT / payload["evidence_manifest"]["manifest"]["path"]
    tampered = json.loads(manifest_path.read_text(encoding="utf-8"))
    for case in tampered["cases"]:
        if case["case_id"] == "N01":
            case["question_sha256"] = "e" * 64
    target = work / "manifest.tampered.json"
    target.write_text(json.dumps(tampered, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    payload["evidence_manifest"]["manifest"] = {
        "path": str(target),
        "sha256": module.file_sha256(target),
    }
    selection_path = Path(payload["public"]["selection"]["path"])
    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    selection["authority"]["document"] = str(target)
    selection["authority"]["sha256"] = module.file_sha256(target)
    selection_path.write_text(
        json.dumps(selection, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    payload["public"]["selection"]["sha256"] = module.file_sha256(selection_path)
    inputs_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
    second = evaluate_release_gate(inputs_path)
    rows = {row.row_id: row for row in second.rows}
    assert rows["evidence_provenance"].decision == DECISION_BLOCKED
    assert "provenance_failed" == rows["evidence_provenance"].detail["cause"]
    assert any(
        problem.get("code") == "QUESTION_HASH_MISMATCH"
        for problem in rows["evidence_provenance"].detail["evidence"]["problems"]
    )

"""T302 §5.5 E-a~E-f：评测批次白名单、holdout 扣留、空批次、非法 JSON 与权限。"""

from __future__ import annotations

import json
from pathlib import Path

OPS = "/api/v1/operations"
OBS = "/api/v1/observability"
CANARY = "T302-HOLDOUT-QUESTION-NEVER-RETURNED"


def _write_run(
    data_dir: Path,
    run_id: str,
    *,
    manifest: dict | None,
    summary: dict | None = None,
    gate: dict | None = None,
    cases: str | None = None,
    manifest_raw: str | None = None,
) -> Path:
    run_dir = Path(data_dir) / "eval" / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    if manifest_raw is not None:
        (run_dir / "run_manifest.json").write_text(manifest_raw, encoding="utf-8")
    elif manifest is not None:
        (run_dir / "run_manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
        )
    if summary is not None:
        (run_dir / "summary.json").write_text(
            json.dumps(summary, ensure_ascii=False), encoding="utf-8"
        )
    if gate is not None:
        (run_dir / "gate.json").write_text(json.dumps(gate, ensure_ascii=False), encoding="utf-8")
    if cases is not None:
        (run_dir / "cases.jsonl").write_text(cases, encoding="utf-8")
    return run_dir


def _manifest(run_id: str, *, suite: str = "b0", holdout_details: bool = False,
              created_at: str = "2026-11-21T02:00:00+00:00") -> dict:
    return {
        "run_id": run_id,
        "mode": "local",
        "scope": "end_to_end",
        "suite": suite,
        "dataset_version": "b0-v1",
        "index_revision": 7,
        "created_at": created_at,
        "case_count": 40,
        "trace_store": "C:/secret/traces.sqlite3",
        "holdout_details": holdout_details,
    }


def _summary(run_id: str, *, suite: str = "b0", holdout: dict | None = None) -> dict:
    payload = {
        "run_id": run_id,
        "mode": "local",
        "suite": suite,
        "case_count": 40,
        "scored_count": 32,
        "error_count": 0,
        "status_counts": {"pass": 29, "fail": 3},
        "metrics": {"recall_at_10": 0.95},
        "declarations": {"note": CANARY},
    }
    if holdout is not None:
        payload["holdout"] = holdout
    return payload


def _gate(run_id: str) -> dict:
    return {
        "exit_code": 0,
        "run_id": run_id,
        "suite": "b0",
        "gate_status": {"quality": "pass"},
        "quality": {"status": "pass"},
        "failures": [],
    }


def test_controlled_run_matches_existing_run_endpoint(admin_client) -> None:
    """E-a：受控 run 目录 → 白名单摘要，字段与现有 run 端点一致。"""
    data_dir = admin_client.app.state.settings.data_dir
    _write_run(data_dir, "b0-local-1", manifest=_manifest("b0-local-1"),
               summary=_summary("b0-local-1"), gate=_gate("b0-local-1"))

    listing = admin_client.get(f"{OPS}/evaluation-runs")
    assert listing.status_code == 200, listing.text
    body = listing.json()
    assert body["status"] == "ok"
    assert len(body["runs"]) == 1
    item = body["runs"][0]

    existing = admin_client.get(f"{OBS}/runs/b0-local-1").json()
    assert item["manifest"] == existing["manifest"]
    assert item["summary"] == existing["summary"]
    assert item["gate"] == existing["gate"]
    assert item["holdout_detected"] is False
    assert item["details_withheld"] is False
    assert CANARY not in listing.text
    assert "trace_store" not in listing.text
    assert "dataset_path" not in listing.text


def test_holdout_details_are_withheld(admin_client) -> None:
    """E-b：suite=holdout → 只回聚合，details_withheld=true，不含逐题内容。"""
    data_dir = admin_client.app.state.settings.data_dir
    _write_run(
        data_dir,
        "holdout-local-1",
        manifest=_manifest("holdout-local-1", suite="holdout", holdout_details=True),
        summary=_summary(
            "holdout-local-1",
            suite="holdout",
            holdout={"aggregate_only": True, "details_written": True,
                     "strata": {"core": 3}, "labels_sha256": "a" * 64},
        ),
        gate=_gate("holdout-local-1"),
        cases=json.dumps({"question": CANARY, "answer": CANARY}) + "\n",
    )
    response = admin_client.get(f"{OPS}/evaluation-runs")
    assert response.status_code == 200, response.text
    item = response.json()["runs"][0]
    assert item["holdout_detected"] is True
    assert item["details_withheld"] is True
    assert item["summary"]["holdout"]["strata"] == {"core": 3}
    assert CANARY not in response.text


def test_empty_dirs_are_skipped_and_all_empty_is_200(admin_client) -> None:
    """E-c：空目录跳过不报错；全部为空 → runs=[] + status empty，200。"""
    data_dir = admin_client.app.state.settings.data_dir
    for run_id in ("p2-t209-b0-20261120-01", "p2-t209-b0-20261120-02"):
        (data_dir / "eval" / "runs" / run_id).mkdir(parents=True)

    only_empty = admin_client.get(f"{OPS}/evaluation-runs")
    assert only_empty.status_code == 200, only_empty.text
    body = only_empty.json()
    assert body["runs"] == []
    assert body["status"] == "empty"
    assert body["skipped"] == 2

    _write_run(data_dir, "p0-b0", manifest=_manifest("p0-b0"),
               summary=_summary("p0-b0"), gate=_gate("p0-b0"))
    mixed = admin_client.get(f"{OPS}/evaluation-runs").json()
    assert mixed["status"] == "ok"
    assert [item["run_id"] for item in mixed["runs"]] == ["p0-b0"]
    assert mixed["skipped"] == 2


def test_invalid_json_only_marks_that_entry(admin_client) -> None:
    """E-d：非法 JSON → 对应 degraded_reason，不整体 500。"""
    data_dir = admin_client.app.state.settings.data_dir
    _write_run(data_dir, "bad-manifest", manifest=None, manifest_raw="{not-json")
    _write_run(data_dir, "bad-summary", manifest=_manifest("bad-summary"),
               summary={}, gate=_gate("bad-summary"))
    # 覆盖 summary 为非法文本
    (data_dir / "eval" / "runs" / "bad-summary" / "summary.json").write_text("[]", encoding="utf-8")

    response = admin_client.get(f"{OPS}/evaluation-runs")
    assert response.status_code == 200, response.text
    runs = {item["run_id"]: item for item in response.json()["runs"]}
    assert runs["bad-manifest"]["degraded_reason"] == "manifest_invalid"
    assert runs["bad-manifest"]["manifest"] is None
    assert runs["bad-summary"]["degraded_reason"] == "summary_invalid"


def test_runs_sorted_by_created_at_then_id_desc(admin_client) -> None:
    data_dir = admin_client.app.state.settings.data_dir
    for run_id, created in (
        ("a-old", "2026-11-20T00:00:00+00:00"),
        ("z-new", "2026-11-21T00:00:00+00:00"),
        ("m-new", "2026-11-21T00:00:00+00:00"),
    ):
        _write_run(data_dir, run_id, manifest=_manifest(run_id, created_at=created),
                   summary=_summary(run_id), gate=_gate(run_id))
    body = admin_client.get(f"{OPS}/evaluation-runs").json()
    assert [item["run_id"] for item in body["runs"]] == ["z-new", "m-new", "a-old"]


def test_employee_cannot_read_evaluation_runs(employee_client) -> None:
    """E-e：员工访问 → 403。"""
    response = employee_client.get(f"{OPS}/evaluation-runs")
    assert response.status_code == 403, response.text
    assert response.json()["error"]["code"] == "ROLE_REQUIRED"

"""E 工作流：P1 baseline 归档 / 校验 / 恢复的可移植性隔离验证。

约束（与任务红线一致）：

- 全部用 ``tmp_path`` 合成 run / baseline，零真实调用（不调 provider / 网络 /
  embedding / rerank），不读 ``.env``，不写 ``var/``；
- 源只读：archive / restore 前后源 baseline 与 run 产物摘要必须不变；
- fail closed：缺文件、哈希不符、holdout run、已存在目标目录、未登记文件一律拒绝；
- restore 只重写 ``baseline.json.run_dir``，identity / approval / artifact 摘要 /
  gate 快照逐键不变；缺 ``approval.json`` 时 approved=no，不冒充审批。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from mktkb.evaluation import cli
from mktkb.evaluation.baseline import (
    APPROVAL_FILENAME,
    ARCHIVE_BASELINE_DIR,
    ARCHIVE_MANIFEST_FILENAME,
    ARCHIVE_RUN_DIR,
    ARCHIVE_RUN_ARTIFACTS,
    ARCHIVE_SCHEMA_VERSION,
    BASELINE_FILENAME,
    BaselineArchiveError,
    BaselineError,
    approve_baseline,
    archive_baseline,
    gate_result_digest,
    load_baseline,
    restore_baseline,
    save_baseline,
    verify_archive,
)
from mktkb.evaluation.gate import GateResult, QualityResult
from mktkb.evaluation.runner import RunManifest, RunResult
from mktkb.observability.contracts import GATE_SCHEMA_VERSION

DS_VERSION = "b0:dev-1:0123456789ab"
CORPUS_SHA = "b" * 64
RUN_ID = "run-b0-a"
APPROVER = "测试审批人"
APPROVAL_REASON = "E 工作流隔离验证审批（合成 run）"
_ARCHIVE_RUN_FILES = {f"{ARCHIVE_RUN_DIR}/{name}" for name in ARCHIVE_RUN_ARTIFACTS}


# --------------------------------------------------------------------------- #
# 合成 run / gate（不写数据集、不跑评测）
# --------------------------------------------------------------------------- #


def make_manifest(**overrides) -> RunManifest:
    payload = {
        "run_id": RUN_ID,
        "mode": "local",
        "scope": "end_to_end",
        "suite": "b0",
        "dataset_version": DS_VERSION,
        "dataset_sha256": "a" * 64,
        "corpus_manifest_sha256": CORPUS_SHA,
        "business_date": "2026-10-28",
        "index_revision": 6,
        "pipeline_version": "pipeline1234",
        "gate_version": GATE_SCHEMA_VERSION,
        "label_version": "dev-1",
        "created_at": "2026-11-05T00:00:00.000+00:00",
        "case_count": 1,
        "config_hash": "c" * 12,
        "dataset_path": "",
    }
    payload.update(overrides)
    return RunManifest(**payload)


def make_gate(*, run_id: str, suite: str) -> GateResult:
    quality = QualityResult(
        status="pass",
        metrics=(),
        strata=("all",),
        stratum_status={"all": "pass"},
        failures=(),
        unknowns=(),
        waived=(),
        diagnostics={},
        warnings=(),
        config_status="approved",
        gate_config_hash="f" * 64,
        baseline_run_id=None,
        baseline_pipeline_version=None,
    )
    return GateResult(
        exit_code=0,
        gate_status={"security_leak": "pass", "citation_required": "pass"},
        hard_failures=(),
        failures=(),
        unknowns=(),
        not_applicable=(),
        warnings=(),
        run_id=run_id,
        suite=suite,
        mode="local",
        gate_version=GATE_SCHEMA_VERSION,
        scored_count=1,
        min_sample=1,
        quality=quality,
    )


def _json_bytes(payload) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode(
        "utf-8"
    )


def write_run(run_dir: Path, manifest: RunManifest, rows=None) -> RunResult:
    run_dir.mkdir(parents=True, exist_ok=True)
    rows = [{"case_id": "Q01", "status": "pass"}] if rows is None else rows
    manifest = RunManifest(**{**manifest.to_dict(), "case_count": len(rows)})
    (run_dir / "run_manifest.json").write_bytes(_json_bytes(manifest.to_dict()))
    (run_dir / "cases.jsonl").write_bytes(
        "".join(
            json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows
        ).encode("utf-8")
    )
    summary = {"run_id": manifest.run_id, "suite": manifest.suite, "mode": manifest.mode}
    (run_dir / "summary.json").write_bytes(_json_bytes(summary))
    return RunResult(manifest=manifest, out_dir=run_dir, cases=tuple(rows), summary=summary)


def build_baseline(
    tmp_path: Path,
    *,
    run_id: str = RUN_ID,
    with_approval: bool = True,
    manifest_overrides: dict | None = None,
    extra_run_files: dict[str, bytes] | None = None,
) -> SimpleNamespace:
    """在 tmp_path/source 下建一个合成 baseline（可选真审批 + gate.json）。"""
    source = tmp_path / "source"
    run_dir = source / "runs" / run_id
    manifest = make_manifest(run_id=run_id, **(manifest_overrides or {}))
    run = write_run(run_dir, manifest)
    root = source / "baselines"
    gate = None
    if with_approval:
        gate = make_gate(run_id=run_id, suite=manifest.suite)
        (run_dir / "gate.json").write_bytes(_json_bytes(gate.to_dict()))
        baseline = approve_baseline(
            run, gate, root, approver=APPROVER, reason=APPROVAL_REASON
        )
    else:
        baseline = save_baseline(run, root)
    for name, data in (extra_run_files or {}).items():
        target = run_dir / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return SimpleNamespace(
        source=source, run_dir=run_dir, root=root, run=run, baseline=baseline, gate=gate
    )


def digest_tree(*directories: Path) -> dict[str, str]:
    """只读快照：{相对路径: sha256}（用于断言源产物未被修改）。"""
    out: dict[str, str] = {}
    for directory in directories:
        for path in sorted(Path(directory).rglob("*")):
            if path.is_file():
                out[path.relative_to(directory).as_posix()] = hashlib.sha256(
                    path.read_bytes()
                ).hexdigest()
    return out


def same_size_flip(path: Path) -> None:
    """同字节数翻转首字节：专门覆盖「字节数不变但 sha256 变」的篡改。"""
    data = bytearray(path.read_bytes())
    data[0] ^= 0xFF
    path.write_bytes(bytes(data))


def archivable(ctx: SimpleNamespace, tmp_path: Path, name: str = "archive") -> Path:
    archive_dir = tmp_path / name
    archive_baseline(ctx.baseline.baseline_id, ctx.root, archive_dir)
    return archive_dir


# --------------------------------------------------------------------------- #
# 归档 → 校验 → 恢复 往返
# --------------------------------------------------------------------------- #


def test_archive_restore_roundtrip_preserves_identity_and_approval(tmp_path: Path) -> None:
    ctx = build_baseline(
        tmp_path,
        extra_run_files={
            "traces.sqlite3": b"trace-db-bytes",
            "traces.sqlite3-wal": b"",
            "index/rag.sqlite3": b"index-bytes",
        },
    )
    baseline_dir = ctx.root / ctx.baseline.baseline_id
    source_before = digest_tree(ctx.run_dir, baseline_dir)

    archive_dir = archivable(ctx, tmp_path)
    record = archive_baseline(ctx.baseline.baseline_id, ctx.root, tmp_path / "archive2")
    assert record.baseline_id == ctx.baseline.baseline_id
    assert record.run_id == RUN_ID
    assert record.suite == "b0"
    assert record.has_approval is True
    assert record.approval_gate_result_sha256 == gate_result_digest(ctx.gate)
    assert record.identity == ctx.baseline.identity
    expected = {
        f"{ARCHIVE_BASELINE_DIR}/{BASELINE_FILENAME}",
        f"{ARCHIVE_BASELINE_DIR}/{APPROVAL_FILENAME}",
        *_ARCHIVE_RUN_FILES,
    }
    assert set(record.files) == expected
    assert not any("trace" in rel for rel in record.files)  # 不打包 trace 库

    manifest = json.loads((archive_dir / ARCHIVE_MANIFEST_FILENAME).read_bytes())
    assert manifest["schema_version"] == ARCHIVE_SCHEMA_VERSION
    assert manifest["baseline_id"] == ctx.baseline.baseline_id
    assert manifest["run_id"] == RUN_ID
    assert manifest["identity"] == ctx.baseline.identity.to_dict()
    assert manifest["has_approval"] is True
    assert manifest["approval"]["approver"] == APPROVER
    assert manifest["approval"]["gate_result_sha256"] == gate_result_digest(ctx.gate)
    assert manifest["gate"]["gate_result_sha256"] == gate_result_digest(ctx.gate)
    assert set(manifest["excluded"]) == {"traces.sqlite3", "traces.sqlite3-wal", "index"}
    assert manifest["archived_at"]
    assert manifest["source"]["run_dir"] == str(ctx.run_dir)
    for item in manifest["files"]:
        assert hashlib.sha256((archive_dir / item["path"]).read_bytes()).hexdigest() == item[
            "sha256"
        ]

    dst_root = tmp_path / "dst" / "eval" / "baselines"
    result = restore_baseline(archive_dir, dst_root)
    assert result.baseline_id == ctx.baseline.baseline_id
    assert Path(result.run_dir) == (tmp_path / "dst" / "eval" / "runs" / RUN_ID).resolve()
    assert Path(result.run_dir).is_dir()
    assert not (Path(result.run_dir) / "traces.sqlite3").exists()

    restored = load_baseline(ctx.baseline.baseline_id, dst_root, expected=ctx.run.manifest)
    assert restored.identity == ctx.baseline.identity
    assert dict(restored.artifact_sha256) == dict(ctx.baseline.artifact_sha256)
    assert restored.approval is not None
    assert restored.approval.to_dict() == ctx.baseline.approval.to_dict()
    assert restored.gate == ctx.baseline.gate
    run = restored.load_run()
    assert len(run.cases) == 1

    old_payload = json.loads((baseline_dir / BASELINE_FILENAME).read_bytes())
    new_payload = json.loads((dst_root / ctx.baseline.baseline_id / BASELINE_FILENAME).read_bytes())
    assert {k: v for k, v in new_payload.items() if k != "run_dir"} == {
        k: v for k, v in old_payload.items() if k != "run_dir"
    }
    assert new_payload["run_dir"] == result.run_dir != old_payload["run_dir"]

    # 源目录只读：archive + restore 后源 baseline / run 摘要逐字节不变。
    assert digest_tree(ctx.run_dir, baseline_dir) == source_before

    # --runs-root 可显式指定；同一归档可恢复到不同隔离根（但每个根只写一份新证据）。
    custom_root = tmp_path / "custom" / "baselines"
    custom = restore_baseline(
        archive_dir, custom_root, runs_root=tmp_path / "custom-runs"
    )
    assert Path(custom.run_dir) == (tmp_path / "custom-runs" / RUN_ID).resolve()
    assert custom.baseline.approval is not None


# --------------------------------------------------------------------------- #
# 归档 fail closed
# --------------------------------------------------------------------------- #


def test_archive_refuses_existing_out_dir_without_touching_it(tmp_path: Path) -> None:
    ctx = build_baseline(tmp_path)
    out = tmp_path / "archive"
    out.mkdir()
    marker = out / "keep.txt"
    marker.write_text("keep", encoding="utf-8")
    with pytest.raises(BaselineArchiveError, match="已存在"):
        archive_baseline(ctx.baseline.baseline_id, ctx.root, out)
    assert marker.read_text(encoding="utf-8") == "keep"
    assert not any(path.name.startswith(".archive.staging") for path in tmp_path.iterdir())


def test_archive_rejects_missing_run_artifact(tmp_path: Path) -> None:
    ctx = build_baseline(tmp_path)
    (ctx.run_dir / "summary.json").unlink()
    out = tmp_path / "archive"
    with pytest.raises(BaselineError):
        archive_baseline(ctx.baseline.baseline_id, ctx.root, out)
    assert not out.exists()


def test_archive_rejects_tampered_source_run(tmp_path: Path) -> None:
    ctx = build_baseline(tmp_path)
    # 追加空白：JSON 仍可解析，但字节摘要与建立时不同（走 artifact_sha256 复核路径）。
    summary_path = ctx.run_dir / "summary.json"
    summary_path.write_bytes(summary_path.read_bytes() + b" ")
    out = tmp_path / "archive"
    with pytest.raises(BaselineError, match="摘要"):
        archive_baseline(ctx.baseline.baseline_id, ctx.root, out)
    assert not out.exists()


@pytest.mark.parametrize(
    ("overrides", "detail"),
    [
        ({"suite": "holdout"}, "suite='holdout'"),
        ({"holdout_details": True}, "holdout_details"),
        ({"holdout_labels_sha256": "a" * 64}, "holdout_labels_sha256"),
    ],
)
def test_archive_rejects_holdout_runs(tmp_path: Path, overrides, detail) -> None:
    ctx = build_baseline(tmp_path, with_approval=False, manifest_overrides=overrides)
    if overrides.get("suite") == "holdout":
        # 模拟 holdout 聚合 run（无 cases.jsonl）：holdout 判定必须早于「缺产物」。
        (ctx.run_dir / "cases.jsonl").unlink()
    out = tmp_path / "archive"
    with pytest.raises(BaselineArchiveError, match="holdout") as excinfo:
        archive_baseline(ctx.baseline.baseline_id, ctx.root, out)
    assert detail in str(excinfo.value)
    assert not out.exists()


def test_missing_approval_file_archives_as_not_approved(tmp_path: Path) -> None:
    """缺 approval.json 时不得冒充审批：归档记录 approved=no，恢复后也是未审批。"""
    ctx = build_baseline(tmp_path)
    (ctx.root / ctx.baseline.baseline_id / APPROVAL_FILENAME).unlink()
    archive_dir = tmp_path / "archive"
    record = archive_baseline(ctx.baseline.baseline_id, ctx.root, archive_dir)
    assert record.has_approval is False
    assert record.approval_approver == ""
    manifest = json.loads((archive_dir / ARCHIVE_MANIFEST_FILENAME).read_bytes())
    assert manifest["approval"] is None
    assert f"{ARCHIVE_BASELINE_DIR}/{APPROVAL_FILENAME}" not in record.files

    dst_root = tmp_path / "dst" / "baselines"
    result = restore_baseline(archive_dir, dst_root)
    assert result.baseline.approval is None


# --------------------------------------------------------------------------- #
# verify / restore fail closed
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "rel",
    sorted(
        {
            f"{ARCHIVE_BASELINE_DIR}/{BASELINE_FILENAME}",
            f"{ARCHIVE_BASELINE_DIR}/{APPROVAL_FILENAME}",
            *_ARCHIVE_RUN_FILES,
        }
    ),
)
def test_verify_and_restore_reject_tampered_member(tmp_path: Path, rel: str) -> None:
    ctx = build_baseline(tmp_path)
    archive_dir = archivable(ctx, tmp_path)
    same_size_flip(archive_dir / rel)
    with pytest.raises(BaselineArchiveError, match="sha256"):
        verify_archive(archive_dir)
    dst_root = tmp_path / "dst" / "baselines"
    with pytest.raises(BaselineArchiveError):
        restore_baseline(archive_dir, dst_root)
    assert not dst_root.exists()


def test_verify_rejects_unregistered_extra_file(tmp_path: Path) -> None:
    ctx = build_baseline(tmp_path)
    archive_dir = archivable(ctx, tmp_path)
    (archive_dir / ARCHIVE_RUN_DIR / "extra.txt").write_text("smuggled", encoding="utf-8")
    with pytest.raises(BaselineArchiveError, match="文件集合不符"):
        verify_archive(archive_dir)


def test_verify_rejects_gate_result_not_bound_to_approval(tmp_path: Path) -> None:
    """同步改写 gate.json 与清单 sha256 也不行：gate 结果必须绑定审批记录的摘要。"""
    ctx = build_baseline(tmp_path)
    archive_dir = archivable(ctx, tmp_path)
    gate_path = archive_dir / ARCHIVE_RUN_DIR / "gate.json"
    payload = json.loads(gate_path.read_bytes())
    payload["exit_code"] = 3
    new_bytes = _json_bytes(payload)
    gate_path.write_bytes(new_bytes)
    manifest_path = archive_dir / ARCHIVE_MANIFEST_FILENAME
    manifest = json.loads(manifest_path.read_bytes())
    for item in manifest["files"]:
        if item["path"] == f"{ARCHIVE_RUN_DIR}/gate.json":
            item["sha256"] = hashlib.sha256(new_bytes).hexdigest()
            item["bytes"] = len(new_bytes)
    manifest_path.write_bytes(_json_bytes(manifest))
    with pytest.raises(BaselineArchiveError, match="gate.json"):
        verify_archive(archive_dir)


def test_restore_refuses_existing_baseline_or_run_target(tmp_path: Path) -> None:
    ctx = build_baseline(tmp_path)
    archive_dir = archivable(ctx, tmp_path)
    dst_root = tmp_path / "dst" / "eval" / "baselines"
    restore_baseline(archive_dir, dst_root)
    with pytest.raises(BaselineArchiveError, match="已存在"):
        restore_baseline(archive_dir, dst_root)

    occupied = tmp_path / "occupied" / "baselines"
    (occupied / ctx.baseline.baseline_id).mkdir(parents=True)
    with pytest.raises(BaselineArchiveError, match="已存在"):
        restore_baseline(archive_dir, occupied)
    assert (occupied / ctx.baseline.baseline_id).is_dir()

    blocked = tmp_path / "blocked" / "baselines"
    existing_run = tmp_path / "blocked" / "runs" / RUN_ID
    existing_run.mkdir(parents=True)
    with pytest.raises(BaselineArchiveError, match="已存在"):
        restore_baseline(archive_dir, blocked)
    assert not (blocked / ctx.baseline.baseline_id).exists()


# --------------------------------------------------------------------------- #
# 审批关系：缺 approval.json 不冒充
# --------------------------------------------------------------------------- #


def test_restore_without_approval_is_not_approved(tmp_path: Path, capsys) -> None:
    ctx = build_baseline(tmp_path, with_approval=False)
    archive_dir = archivable(ctx, tmp_path)
    record = verify_archive(archive_dir)
    assert record.has_approval is False
    assert record.approval_gate_result_sha256 == ""
    manifest = json.loads((archive_dir / ARCHIVE_MANIFEST_FILENAME).read_bytes())
    assert manifest["has_approval"] is False
    assert manifest["approval"] is None

    dst_root = tmp_path / "dst" / "baselines"
    result = restore_baseline(archive_dir, dst_root)
    assert result.baseline.approval is None
    assert load_baseline(ctx.baseline.baseline_id, dst_root).approval is None
    assert cli.main(["baseline", "list", "--root", str(dst_root)]) == 0
    assert "approved=no" in capsys.readouterr().out


# --------------------------------------------------------------------------- #
# CLI：archive / verify / restore 可执行 + --help 可见
# --------------------------------------------------------------------------- #


def test_cli_archive_verify_restore_flow(tmp_path: Path, capsys) -> None:
    ctx = build_baseline(tmp_path)
    archive_dir = tmp_path / "archive"
    code = cli.main(
        [
            "baseline",
            "archive",
            "--baseline",
            ctx.baseline.baseline_id,
            "--root",
            str(ctx.root),
            "--out",
            str(archive_dir),
        ]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert f"baseline_id={ctx.baseline.baseline_id}" in out
    assert "approved=yes" in out
    assert (archive_dir / ARCHIVE_MANIFEST_FILENAME).is_file()

    assert cli.main(["baseline", "verify", "--archive", str(archive_dir)]) == 0
    assert "archive ok" in capsys.readouterr().out

    dst_root = tmp_path / "cli-dst" / "baselines"
    assert (
        cli.main(["baseline", "restore", "--archive", str(archive_dir), "--root", str(dst_root)])
        == 0
    )
    assert "restored" in capsys.readouterr().out
    assert cli.main(["baseline", "list", "--root", str(dst_root)]) == 0
    assert "approved=yes" in capsys.readouterr().out

    # 重复 restore → exit 3，打印 ERROR，不抛栈。
    code = cli.main(
        ["baseline", "restore", "--archive", str(archive_dir), "--root", str(dst_root)]
    )
    assert code == 3
    err = capsys.readouterr().err
    assert "ERROR:" in err and "Traceback" not in err


def test_cli_verify_tampered_archive_is_data_error(tmp_path: Path, capsys) -> None:
    ctx = build_baseline(tmp_path)
    archive_dir = archivable(ctx, tmp_path)
    same_size_flip(archive_dir / ARCHIVE_RUN_DIR / "cases.jsonl")
    assert cli.main(["baseline", "verify", "--archive", str(archive_dir)]) == 3
    err = capsys.readouterr().err
    assert "ERROR:" in err and "Traceback" not in err


def test_cli_baseline_help_lists_archive_verify_restore(capsys) -> None:
    assert cli.main(["baseline", "--help"]) == 0
    out = capsys.readouterr().out
    for name in ("archive", "verify", "restore"):
        assert name in out
    for name in ("archive", "verify", "restore"):
        assert cli.main(["baseline", name, "--help"]) == 0
        assert name in capsys.readouterr().out

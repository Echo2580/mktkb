"""T207 HISTORICAL-AUDIT：只读历史审计入口的合成测试（先写红例，再实现）。

边界（与任务单 A 一致）：
- 全部离线合成：复用已接收 e2e 链（真实 loader/contract/受控入口/真实 Fernet 密文/
  真实 case-plan/receipt/seal），不读真实 H2 题面/标签/密文/真实 key/.env/GO/账本；
- 断言覆盖：双代码身份分列（旧执行 vs 本次分析）、旧 run 内部绑定严格自核、
  反例（坏 key/hash/跨 run/错 plan/缺或多 manifest/漏或重复文件/越界路径/绑定矛盾/
  秘密异常）固定拒绝、网络 guard 子进程实测 socket+DNS 均失败、公开输出哨兵 0 命中；
- 不修改旧 live 入口/已接收分类器/受控工具：只断言其既有 `code_changed_since_plan` 仍在。
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

_TESTS_DIR = Path(__file__).resolve().parents[1]
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))
_EVALUATION_TESTS = Path(__file__).resolve().parent
if str(_EVALUATION_TESTS) not in sys.path:
    sys.path.insert(0, str(_EVALUATION_TESTS))

from acceptance.support.netguard import t09_network_guard  # noqa: E402,F401

from evaluation import test_p2_eval_tool_repair_e2e as chainlib  # noqa: E402
from evaluation import test_p2_h2_controlled_entry as helper  # noqa: E402
from mktkb.evaluation import p2_authorization as p2a  # noqa: E402

pytestmark = pytest.mark.usefixtures("t09_network_guard")

ROOT = Path(__file__).resolve().parents[3]
AUDIT_TOOL = ROOT / "tools" / "p2_h2_historical_audit.py"
CONTROLLED_TOOL = ROOT / "tools" / "p2_h2_controlled_execute.py"

SENTINELS = tuple(sorted(set(helper.SECRETS) | {"SYNTH30-00", "合成参考答案", "编号 P01 的物品放在哪个位置？"}))


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def controlled() -> Any:
    return _load_module("p2_h2_controlled_entry_audit_tests", CONTROLLED_TOOL)


@pytest.fixture(scope="module")
def audit() -> Any:
    return _load_module("p2_h2_historical_audit_under_test", AUDIT_TOOL)


@pytest.fixture(scope="module")
def chain(controlled: Any, tmp_path_factory: pytest.TempPathFactory) -> Any:
    """已接收 e2e 合成链：26 题/32 回合真实格式 live 信封 + case-plan + receipt + seal。"""
    saved = (p2a.P2_LEDGER_PATH, p2a.P2_BUDGET_PATH, p2a.P2_GO_PATH)
    work = tmp_path_factory.mktemp("t207-historical-audit-chain")
    built = chainlib._load_chain(controlled, work)
    assert built.recompute_error is None, built.recompute_error
    assert built.receipt["ok"] is True, built.receipt
    yield built
    p2a.P2_LEDGER_PATH, p2a.P2_BUDGET_PATH, p2a.P2_GO_PATH = saved


def _seal_dir(chain: Any) -> Path:
    return Path(str(chain.receipt["seal"]["seal_dir"]))


def _seal_manifest_path(chain: Any) -> Path:
    return Path(str(chain.receipt["seal"]["seal_manifest"]))


def _run_out_root(chain: Any) -> Path:
    return Path(str(chain.receipt["paths"]["out_dir"]))


def _fixtures(chain: Any) -> Path:
    """合成反例目录：必须在历史根内（否则先被路径边界拒绝，测不到目标分支）。"""
    target = Path(str(chain.work)) / "_audit-fixtures"
    target.mkdir(parents=True, exist_ok=True)
    return target


def _evidence_copy(chain: Any, name: str) -> Path:
    """保留 `evidence/<run_id>/` 相对结构，才能测到文件集合/摘要分支而不是目录名分支。"""
    source = Path(str(chain.evidence_dir))
    base = _fixtures(chain) / name / "evidence"
    if base.exists():
        shutil.rmtree(base)
    base.parent.mkdir(parents=True, exist_ok=True)
    target = base / source.name
    shutil.copytree(source, target)
    for path in target.iterdir():
        path.chmod(0o644)
    return target


def _kwargs(chain: Any, tmp_path: Path, **overrides: Any) -> dict[str, Any]:
    payload = {
        "historical_root": chain.work,
        "binding_path": Path(str(chain.plan_payload["binding_file"])),
        "run_index": 0,
        "evidence_dir": Path(str(chain.evidence_dir)),
        "evidence_key_file": Path(str(chain.key_path)),
        "case_plan_path": Path(str(chain.case_plan_path)),
        "receipt_path": _seal_dir(chain) / "run-receipt.json",
        "seal_manifest_path": _seal_manifest_path(chain),
        "ledger_path": Path(str(chain.ledger)),
        "run_out_root": _run_out_root(chain),
        "holdout_root": Path(str(chain.private.holdout_root)),
        "holdout_key_file": Path(str(chain.private.holdout_key_file)),
        "project_total_limit_cny": helper.TOTAL_LIMIT_CNY,
        "out_dir": tmp_path / "audit-out",
    }
    payload.update(overrides)
    return payload


def _audit(chain: Any, audit: Any, tmp_path: Path, **overrides: Any) -> dict[str, Any]:
    return audit.audit_historical(**_kwargs(chain, tmp_path, **overrides))


def _resign(document: dict[str, Any]) -> dict[str, Any]:
    from mktkb.evaluation.p2_contracts import payload_sha256

    document["binding_sha256"] = payload_sha256(
        {key: value for key, value in document.items() if key != "binding_sha256"}
    )
    return document


def _strings(value: Any) -> list[str]:
    found: list[str] = []
    if isinstance(value, str):
        found.append(value)
    elif isinstance(value, dict):
        for item in value.values():
            found.extend(_strings(item))
    elif isinstance(value, list):
        for item in value:
            found.extend(_strings(item))
    return found


# --------------------------------------------------------------------------- #
# 正例：双代码身份、旧 run 内部一致、四轴重算可用
# --------------------------------------------------------------------------- #


def test_dual_identity_positive_audit_runs_with_distinct_code(
    audit: Any, chain: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """旧执行 hash 与本次分析 hash 不同 → 历史审计可执行，且明确双身份。"""
    monkeypatch.setattr(audit, "analysis_code_digest", lambda: "c" * 64)
    payload = _audit(chain, audit, tmp_path)
    assert payload["ok"] is True
    assert payload["schema_version"] == "t207-historical-audit/v0.1"
    assert payload["analysis_kind"] == "historical_reassessment"
    assert payload["authorizes_live"] is False
    assert payload["release_ready"] is False
    identity = payload["identity"]
    assert identity["original_execution_code_sha256"] == chain.document["code_version"]
    assert identity["analysis_code_sha256"] == "c" * 64
    assert identity["code_identity"] == "distinct"
    assert identity["code_identity_distinct"] is True
    assert identity["original_execution_code_sha256"] != identity["analysis_code_sha256"]
    # 分析代码摘要绝不写回旧信封 bindings：16 键 bindings 仍是原值（index_revision 除外：
    # run binding 里是 ingest 前占位符，ingest 后由 case-plan 记录实际 revision）。
    assert "analysis_code_sha256" not in identity["envelope_bindings"]
    static_expected = {
        key: str(value)
        for key, value in chain.run_entry["evidence_bindings"].items()
        if key != "index_revision"
    }
    static_actual = {
        key: value
        for key, value in identity["envelope_bindings"].items()
        if key != "index_revision"
    }
    assert static_actual == static_expected
    assert identity["envelope_bindings"]["index_revision"].isdigit()
    checks = identity["checks"]
    for name in (
        "binding_sha256",
        "config_sha256",
        "plan_sha256",
        "plan_file_sha256",
        "inputs_unchanged",
        "scenario_binding",
        "dataset_shape",
        "case_plan_sha256",
        "case_plan_bindings",
        "case_plan_run_binding",
        "receipt_binding",
        "receipt_bindings",
        "receipt_evidence_key",
        "seal_manifest_sha256",
        "seal_evidence_tree",
        "seal_out_tree",
        "evidence_tree_matches_case_plan",
        "ledger_prefix",
        "historical_root_unchanged_during_call",
    ):
        assert checks[name] is True, (name, checks)
    assert "historical_root_unchanged" not in checks
    assert identity["historical_root"]["scope"] == "call_window_only"
    assert identity["historical_root"]["file_count"] >= 27
    assert payload["guard"]["network_guard_enabled"] is True
    assert payload["guard"]["socket_attempts"] == 0
    assert payload["guard"]["dns_attempts"] == 0
    assert payload["guard"]["provider_entry_attempts"] == 0


def test_axes_and_quality_are_reported_with_fixed_denominators(
    audit: Any, chain: Any, tmp_path: Path
) -> None:
    payload = _audit(chain, audit, tmp_path)
    card = payload["card"]
    assert card["total"] == 26
    assert card["verified"] is True
    assert card["missing_evidence_cases"] == 0
    assert card["release_ready"] is False
    for axis in ("safety", "cross_user", "cross_entity", "stale_source"):
        table = payload["axes"][axis]
        assert table["planned"] == 26
        assert table["violations"] == 0
        assert table["checked"] == table["passed"] + table["not_applicable"] + table["violations"]
    quality = payload["quality"]
    assert quality["source"] == "recorded_status"
    assert quality["rescored_from_original_inputs"] is False
    assert quality["denominator"] == 26
    assert quality["pass"] + quality["fail"] + quality["error"] + quality["not_executed"] == 26
    assert quality["dataset_denominator"] == 30
    assert quality["never_started_other_scenarios"] == 4
    assert quality["upper_bound_pass_total"] == quality["pass"] + quality["not_executed"] + 4
    assert quality["quality_axes_conflation"] is False
    assert quality["min_pass_source"] == "classifier_default"
    assert quality["min_pass_required"] == 24
    assert quality["threshold_scope"] == "dataset_30_cases"
    assert quality["threshold_met"] == (
        quality["pass"] >= quality["min_pass_required"]
    )
    assert quality["denominator_note_code"] == "subset_26_of_30_plus_4_never_started"
    coverage = payload["coverage"]
    assert coverage["scenario_cases"] == 26
    assert coverage["scenario_turns"] == 32
    assert coverage["executed_turns"] == 32
    assert coverage["dataset_cases"] == 30
    assert coverage["dataset_turns"] == 36
    full = payload["full_matrix"]
    assert full["basis"] == "run0_observed_plus_not_started_unknown"
    assert full["authoritative"] is False
    assert full["cases"]["planned"] == 30
    assert full["turns"]["planned"] == 36
    assert full["turns"]["executed"] == 32
    assert full["turns"]["not_started"] == 4
    assert full["cases"]["not_started"] == 4
    assert full["cases"]["partially_executed_in_audited_run"] == 0
    assert full["cases"]["never_started_other_scenarios"] == 4
    for axis in ("safety", "cross_user", "cross_entity", "stale_source"):
        row = full["axes"][axis]
        assert row["planned"] == 30
        assert row["unknown"] >= 4
        assert row["checked"] == 26
    assert payload["reasons"]["axis_counts"] == {name: {} for name in payload["axes"]}
    assert payload["reasons"]["unregistered"] == 0
    assert payload["reasons"]["case_counts"] == {"none": 26}
    assert payload["runs"]["total"] == 4
    assert payload["runs"]["verified"] is True
    assert payload["runs"]["not_started"]


def test_public_payload_is_aggregate_only(audit: Any, chain: Any, tmp_path: Path) -> None:
    payload = _audit(chain, audit, tmp_path)
    text = json.dumps(payload, ensure_ascii=False)
    for needle in SENTINELS:
        assert needle not in text, needle
    for forbidden in ("case_id", "question", "reference_answer", "text", "answer"):
        assert f'"{forbidden}"' not in text, forbidden
    assert payload["privacy"]["public_scan"]["hits"] == 0
    assert payload["privacy"]["public_scan"]["key_material_hits"] == 0
    assert payload["privacy"]["public_scan"]["needles"] >= 30  # 30 个 case id + 题面/答案
    assert payload["privacy"]["forbidden_keys"] == []
    assert payload["privacy"]["quality_source"] == "recorded_status"
    assert max(len(value) for value in _strings(payload)) <= 400


def test_outputs_written_new_and_historical_root_untouched(
    audit: Any, chain: Any, tmp_path: Path
) -> None:
    snapshot = audit._tree_identity(chain.work)
    payload = _audit(chain, audit, tmp_path)
    assert snapshot == audit._tree_identity(chain.work)
    aggregate = Path(payload["outputs"]["aggregate"])
    assert aggregate.is_file()
    assert aggregate.parent == (tmp_path / "audit-out")
    assert _sha(aggregate) == payload["outputs"]["aggregate_sha256"]
    assert payload["outputs"]["card"] is None
    readback = json.loads(aggregate.read_text(encoding="utf-8"))
    assert readback["identity"]["analysis_code_sha256"] == payload["identity"]["analysis_code_sha256"]
    assert "outputs" not in readback


def test_out_card_written_when_requested(audit: Any, chain: Any, tmp_path: Path) -> None:
    card = tmp_path / "card.json"
    payload = _audit(chain, audit, tmp_path, out_card=card)
    assert payload["outputs"]["card"] == str(card)
    assert _sha(card) == payload["outputs"]["card_sha256"]
    body = json.loads(card.read_text(encoding="utf-8"))
    assert body["total"] == 26
    text = card.read_text(encoding="utf-8")
    for needle in SENTINELS:
        assert needle not in text, needle


def _canonical(payload: Any) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def _resident_tree(root: Path) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        files.append(
            {
                "path": path.relative_to(root).as_posix(),
                "sha256": _sha(path),
                "bytes": path.stat().st_size,
            }
        )
    joined = "\n".join(f"{item['path']}:{item['sha256']}" for item in files)
    return {
        "tree_sha256": hashlib.sha256(joined.encode("utf-8")).hexdigest(),
        "file_count": len(files),
        "bytes": sum(int(item["bytes"]) for item in files),
        "files": files,
    }


def _reseal_evidence_copy(chain: Any, name: str, mutate: Any = None) -> Any:
    """复制 evidence/<run_id> + receipt + seal，并**一致地**重算树摘要。

    目的：把反例从「树摘要第一道门」推进到 manifest / turn / 解密 / run_binding 分支，
    证明深层检查不是形同虚设（普通测试只改文件会停在 evidence_tree_sha_mismatch）。
    """
    source = Path(str(chain.evidence_dir))
    base = _fixtures(chain) / name
    if base.exists():
        shutil.rmtree(base)
    evidence_root = base / "evidence"
    target = evidence_root / source.name
    shutil.copytree(source, target)
    for path in target.iterdir():
        path.chmod(0o644)
    if mutate is not None:
        mutate(target)
    evidence_tree = _resident_tree(evidence_root)
    receipt = json.loads((_seal_dir(chain) / "run-receipt.json").read_text(encoding="utf-8"))
    seal = json.loads(_seal_manifest_path(chain).read_text(encoding="utf-8"))
    receipt["seal"]["evidence_tree_sha256"] = evidence_tree["tree_sha256"]
    receipt["seal"]["evidence_file_count"] = evidence_tree["file_count"]
    receipt["seal"]["evidence_bytes"] = evidence_tree["bytes"]
    receipt["paths"]["evidence_root"] = str(evidence_root)
    receipt["paths"]["evidence_dir"] = str(target)
    seal["evidence_root"] = evidence_tree
    seal_path = base / "seal-manifest.json"
    seal_path.write_text(
        json.dumps(seal, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    receipt["seal"]["seal_manifest_sha256"] = _sha(seal_path)
    receipt_path = base / "run-receipt.json"
    receipt_path.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return {"evidence_dir": target, "receipt": receipt_path, "seal": seal_path}


def test_refuses_tampered_ciphertext_after_consistent_reseal(
    audit: Any, chain: Any, tmp_path: Path
) -> None:
    """深层反例：重算 receipt/seal 树摘要后，坏密文仍必须被解密/认证拒绝。"""

    def corrupt(target: Path) -> None:
        path = target / "turn-0011.fernet"
        raw = bytearray(path.read_bytes())
        raw[-1] ^= 0xFF
        path.write_bytes(bytes(raw))

    forged = _reseal_evidence_copy(chain, "deep-corrupt", corrupt)
    with pytest.raises(audit.EntryError) as exc:
        _audit(
            chain,
            audit,
            tmp_path,
            evidence_dir=forged["evidence_dir"],
            receipt_path=forged["receipt"],
            seal_manifest_path=forged["seal"],
        )
    assert exc.value.code == "evidence_invalid", exc.value.code


def test_refuses_turn_index_after_consistent_reseal(
    audit: Any, chain: Any, tmp_path: Path
) -> None:
    """深层反例：用真实 key 重加密并改 turn_index → 必须固定 evidence_turn_index_mismatch。"""

    def reindex(target: Path) -> None:
        from cryptography.fernet import Fernet

        path = target / "turn-0011.fernet"
        envelope = json.loads(
            Fernet(chain.key).decrypt(path.read_bytes()).decode("utf-8")
        )
        envelope["turn"]["turn_index"] = int(envelope["turn"]["turn_index"]) + 1
        path.write_bytes(Fernet(chain.key).encrypt(_canonical(envelope)))

    forged = _reseal_evidence_copy(chain, "deep-reindex", reindex)
    with pytest.raises(audit.EntryError) as exc:
        _audit(
            chain,
            audit,
            tmp_path,
            evidence_dir=forged["evidence_dir"],
            receipt_path=forged["receipt"],
            seal_manifest_path=forged["seal"],
        )
    assert exc.value.code == "evidence_turn_index_mismatch", exc.value.code


def test_refuses_freeze_manifest_path_escape(audit: Any, chain: Any, tmp_path: Path) -> None:
    outside = tmp_path / "outside.txt"
    outside.write_text("synthetic-outside", encoding="utf-8")
    for name, entry in (
        ("traversal", "../outside.txt"),
        ("absolute", str(outside)),
    ):
        manifest = _fixtures(chain) / ("freeze-" + name + ".json")
        manifest.write_text(
            json.dumps(
                {
                    "schema_version": "synthetic-freeze/v1",
                    "files": [
                        {"path": entry, "sha256": _sha(outside)},
                        {
                            "path": "backend/src/mktkb/evaluation/p2_hard_evidence.py",
                            "sha256": "f" * 64,
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )
        with pytest.raises(audit.EntryError) as exc:
            _audit(
                chain,
                audit,
                tmp_path / name,
                original_source_freeze=manifest,
                original_source_root=chain.work,
            )
        assert exc.value.code == "original_source_freeze_invalid", (name, exc.value.code)


def test_freeze_bytes_mismatch_never_claims_reconstruction(
    audit: Any, chain: Any, tmp_path: Path
) -> None:
    fixtures = _fixtures(chain)
    rel = "backend/src/mktkb/evaluation/p2_hard_evidence.py"
    manifest = fixtures / "freeze-bytes.json"
    manifest.write_text(
        json.dumps(
            {"schema_version": "synthetic-freeze/v1", "files": [{"path": rel, "sha256": "f" * 64}]}
        ),
        encoding="utf-8",
    )
    # 有字节但内容不符：status=bytes_mismatch，且不得声称复现/重建（C3）。
    source_root = fixtures / "source-root"
    target = source_root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("# synthetic stand-in\n", encoding="utf-8")
    payload = _audit(
        chain,
        audit,
        tmp_path,
        original_source_freeze=manifest,
        original_source_root=source_root,
    )
    freeze = payload["identity"]["original_source_freeze"]
    assert freeze["status"] == "bytes_mismatch"
    assert freeze["code_version_reproduced"] is False
    assert freeze["manifest_bytes_verified"] is False
    assert freeze["claims_original_program_reconstructed"] is False


def test_freeze_manifest_only_reproduces_identity_but_not_program(
    audit: Any, chain: Any, tmp_path: Path
) -> None:
    """用当前 code-scope 文件 hash 建清单：只能证明身份可复算，不能证明重建程序。"""
    rels: dict[str, str] = {}
    for scope in ("backend/src/mktkb", "tools/p2_h2_controlled_execute.py"):
        target = ROOT / scope
        if target.is_dir():
            for path in sorted(target.rglob("*.py")):
                if "__pycache__" in path.parts:
                    continue
                rels[path.relative_to(ROOT).as_posix()] = _sha(path)
        elif target.is_file():
            rels[scope] = _sha(target)
    manifest = _fixtures(chain) / "freeze-identity.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "synthetic-freeze/v1",
                "files": [{"path": rel, "sha256": digest} for rel, digest in sorted(rels.items())],
            }
        ),
        encoding="utf-8",
    )
    payload = _audit(chain, audit, tmp_path, original_source_freeze=manifest)
    freeze = payload["identity"]["original_source_freeze"]
    assert freeze["status"] == "identity_only_manifest_no_bytes"
    assert freeze["manifest_bytes_verified"] is None
    assert freeze["claims_original_program_reconstructed"] is False
    # 合成链的旧 code_version == 当前 code_digest()，所以身份应可复算。
    assert freeze["code_version_reproduced"] is True


def test_refuses_ledger_prefix_mismatch(
    audit: Any, chain: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tampered = _fixtures(chain) / "live-ledger-tampered.jsonl"
    rows = [
        json.loads(line)
        for line in Path(str(chain.ledger)).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    # 改**已存在**行（前缀内），而不是追加：追加不改变 GO 记录的账本前缀，
    # 只有改写历史前缀才算绑定被破坏。
    rows[0]["accounted_cny"] = float(rows[0].get("accounted_cny") or 0.0) + 1.0
    tampered.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8"
    )
    monkeypatch.setattr(p2a, "P2_LEDGER_PATH", tampered)
    with pytest.raises(audit.EntryError) as exc:
        _audit(chain, audit, tmp_path, ledger_path=tampered)
    assert exc.value.code == "ledger_prefix_mismatch", exc.value.code


def test_refuses_ledger_orphan_result(
    audit: Any, chain: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C5b：预约/结果必须一一配对；追加同 run 的 orphan result 也是硬拒绝。"""
    tampered = _fixtures(chain) / "live-ledger-orphan.jsonl"
    text = Path(str(chain.ledger)).read_text(encoding="utf-8")
    orphan = {
        "event": "result",
        "run_id": chain.run_entry["run_id"],
        "reservation_id": "synthetic-orphan-reservation",
        "status": "succeeded",
        "conservative_charge_cny": 0.0,
    }
    tampered.write_text(text + json.dumps(orphan, ensure_ascii=False) + "\n", encoding="utf-8")
    monkeypatch.setattr(p2a, "P2_LEDGER_PATH", tampered)
    with pytest.raises(audit.EntryError) as exc:
        _audit(chain, audit, tmp_path, ledger_path=tampered)
    assert exc.value.code == "ledger_pairing_mismatch", exc.value.code


def test_expected_identity_requires_complete_anchor(audit: Any, chain: Any, tmp_path: Path) -> None:
    """C6c：partial 锚等于没锚 —— 少于 9 字段必须固定拒绝。"""
    partial = _fixtures(chain) / "prior-aggregate-partial.json"
    partial.write_text(
        json.dumps(
            {
                "schema_version": "synthetic-prior-aggregate/v0.1",
                "identity": {"binding_sha256": chain.document["binding_sha256"]},
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(audit.EntryError) as exc:
        _audit(chain, audit, tmp_path, expected_identity_path=partial)
    assert exc.value.code == "expected_identity_incomplete", exc.value.code


def test_expected_identity_anchor(audit: Any, chain: Any, tmp_path: Path) -> None:
    fixtures = _fixtures(chain)
    good = {
        "schema_version": "synthetic-prior-aggregate/v0.1",
        "identity": {
            "run_id": chain.run_entry["run_id"],
            "plan_id": chain.plan.plan_id,
            "plan_sha256": chain.plan.plan_sha256,
            "binding_sha256": chain.document["binding_sha256"],
            "config_sha256": chain.document["config_sha256"],
            "code_version": chain.document["code_version"],
            "case_plan_sha256": chain.receipt["case_plan"]["sha256"],
        },
        "seal": {
            "evidence_tree_sha256": chain.receipt["seal"]["evidence_tree_sha256"],
            "out_tree_sha256": chain.receipt["seal"]["out_tree_sha256"],
        },
    }
    anchor = fixtures / "prior-aggregate.json"
    anchor.write_text(json.dumps(good, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    payload = _audit(chain, audit, tmp_path, expected_identity_path=anchor)
    assert payload["identity"]["checks"]["external_identity_anchor"] is True
    assert payload["identity"]["external_identity_anchor"]["applied"] is True
    assert payload["identity"]["external_identity_anchor"]["checked_fields"] == 9
    assert payload["identity"]["external_identity_anchor"]["mismatched_fields"] == []

    bad = {**good, "identity": {**good["identity"], "binding_sha256": "0" * 64}}
    forged = fixtures / "prior-aggregate-bad.json"
    forged.write_text(json.dumps(bad, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(audit.EntryError) as exc:
        _audit(chain, audit, tmp_path / "second", expected_identity_path=forged)
    assert exc.value.code == "expected_identity_mismatch"
    assert "binding_sha256" in exc.value.detail


def test_run_out_root_is_required(audit: Any, chain: Any, tmp_path: Path) -> None:
    with pytest.raises(audit.EntryError) as exc:
        _audit(chain, audit, tmp_path, run_out_root=None)
    assert exc.value.code == "run_out_root_required"
    assert exc.value.exit_code == 3


def test_pre_existing_root_file_is_recorded_not_trusted(
    audit: Any, chain: Any, tmp_path: Path
) -> None:
    """历史根预置的额外文件不参与判定，但必须被记录并标明 scope=call_window_only。"""
    extra = Path(str(chain.work)) / "_pre_existing_extra.txt"
    extra.write_text("synthetic-lazy-file", encoding="utf-8")
    payload = _audit(chain, audit, tmp_path)
    assert payload["ok"] is True
    assert payload["identity"]["historical_root"]["scope"] == "call_window_only"
    assert payload["identity"]["historical_root"]["file_count"] >= 28
    assert payload["identity"]["checks"]["historical_root_unchanged_during_call"] is True


def test_refuses_tampered_out_tree(audit: Any, chain: Any, tmp_path: Path) -> None:
    copied = _fixtures(chain) / "out-tree" / "controlled"
    if copied.parent.exists():
        shutil.rmtree(copied.parent)
    copied.mkdir(parents=True)
    original = Path(str(chain.receipt["case_plan"]["path"]))
    mutated = json.loads(original.read_text(encoding="utf-8"))
    mutated["real_calls"] = int(mutated["real_calls"]) + 1
    (copied / "case-plan.json").write_text(
        json.dumps(mutated, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    with pytest.raises(audit.EntryError) as exc:
        _audit(chain, audit, tmp_path, run_out_root=copied.parent)
    assert exc.value.code == "seal_out_tree_mismatch"


def test_refuses_run_index_out_of_range(audit: Any, chain: Any, tmp_path: Path) -> None:
    with pytest.raises(audit.EntryError) as exc:
        _audit(chain, audit, tmp_path, run_index=9)
    assert exc.value.code == "run_index_invalid"
    assert exc.value.exit_code == 3


# --------------------------------------------------------------------------- #
# 反例：旧 run 任一绑定不一致必须固定拒绝（不悄悄忽略）
# --------------------------------------------------------------------------- #


def test_refuses_bad_key(audit: Any, chain: Any, tmp_path: Path) -> None:
    bad = _fixtures(chain) / "bad.key"
    bad.write_bytes(b"x" * 44)
    with pytest.raises(audit.EntryError) as exc:
        _audit(chain, audit, tmp_path, evidence_key_file=bad)
    assert exc.value.code in {"evidence_key_invalid", "run_receipt_invalid", "evidence_key_mismatch"}


def test_refuses_key_of_other_run(audit: Any, chain: Any, tmp_path: Path) -> None:
    from cryptography.fernet import Fernet

    other = _fixtures(chain) / "other.key"
    other.write_bytes(Fernet.generate_key())
    with pytest.raises(audit.EntryError) as exc:
        _audit(chain, audit, tmp_path, evidence_key_file=other)
    assert exc.value.code == "evidence_key_mismatch"


def test_refuses_input_digest_drift(audit: Any, chain: Any, tmp_path: Path) -> None:
    fixtures = _fixtures(chain)
    drifted = fixtures / "source-map-drift.json"
    shutil.copyfile(chain.private.source_map, drifted)
    drifted.write_bytes(drifted.read_bytes() + b"\n")
    document = json.loads(Path(chain.plan_payload["binding_file"]).read_text(encoding="utf-8"))
    document["inputs"]["source_map"]["path"] = str(drifted)
    _resign(document)
    forged = fixtures / "binding-input-drift.json"
    forged.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(audit.EntryError) as exc:
        _audit(chain, audit, tmp_path, binding_path=forged)
    assert exc.value.code == "input_changed_since_plan"


def test_refuses_cross_run_evidence_dir(audit: Any, chain: Any, tmp_path: Path) -> None:
    other = _fixtures(chain) / "cross-run" / "evidence" / Path(str(chain.evidence_dir)).name
    if other.exists():
        shutil.rmtree(other)
    other.mkdir(parents=True)
    shutil.copyfile(
        Path(str(chain.evidence_dir)) / "turn-0000.fernet", other / "turn-0000.fernet"
    )
    with pytest.raises(audit.EntryError) as exc:
        _audit(chain, audit, tmp_path, evidence_dir=other)
    assert exc.value.code in {
        "evidence_tree_sha_mismatch",
        "evidence_tree_file_count_mismatch",
        "evidence_tree_bytes_mismatch",
    }, exc.value.code


def test_refuses_wrong_plan_file(audit: Any, chain: Any, tmp_path: Path) -> None:
    fixtures = _fixtures(chain)
    document = json.loads(Path(chain.plan_payload["binding_file"]).read_text(encoding="utf-8"))
    plan_path = Path(str(document["runs"][0]["plan_file"]))
    forged_plan = fixtures / "base_b0-mutated.json"
    payload = json.loads(plan_path.read_text(encoding="utf-8"))
    payload["max_requests"] = int(payload["max_requests"]) + 1
    forged_plan.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    # 只改路径，保留旧 plan_file_sha256：必须报 plan_file_changed（不改旧检查强度）。
    document["runs"][0]["plan_file"] = str(forged_plan)
    _resign(document)
    forged_binding = fixtures / "binding-wrong-plan.json"
    forged_binding.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    with pytest.raises(audit.EntryError) as exc:
        _audit(chain, audit, tmp_path, binding_path=forged_binding)
    assert exc.value.code == "plan_file_changed"


def test_refuses_missing_and_extra_manifest(audit: Any, chain: Any, tmp_path: Path) -> None:
    for name in ("missing-manifest", "extra-manifest"):
        copied = _evidence_copy(chain, name)
        manifest = next(copied.glob("manifest-*.fernet"))
        if name == "missing-manifest":
            manifest.unlink()
        else:
            shutil.copyfile(manifest, copied / "manifest-9999.fernet")
        with pytest.raises(audit.EntryError) as exc:
            _audit(chain, audit, tmp_path / name, evidence_dir=copied)
        assert exc.value.code in {
            "evidence_manifest_count_invalid",
            "evidence_tree_file_count_mismatch",
            "evidence_tree_missing_file",
            "evidence_tree_extra_file",
            "evidence_tree_sha_mismatch",
            "evidence_tree_bytes_mismatch",
        }, (name, exc.value.code)


def test_refuses_missing_duplicate_and_extra_turn_files(
    audit: Any, chain: Any, tmp_path: Path
) -> None:
    cases = (
        (
            "missing-turn",
            lambda root: (root / "turn-0007.fernet").unlink(),
            {"case_plan_evidence_file_missing", "evidence_tree_missing_file"},
        ),
        (
            "duplicate-turn",
            lambda root: shutil.copyfile(root / "turn-0003.fernet", root / "turn-0033.fernet"),
            {"evidence_tree_extra_file", "evidence_tree_file_count_mismatch"},
        ),
        (
            "extra-file",
            lambda root: (root / "turn-0099.fernet").write_bytes(
                (root / "turn-0000.fernet").read_bytes()
            ),
            {"evidence_tree_extra_file", "evidence_tree_file_count_mismatch"},
        ),
    )
    for name, mutate, expected in cases:
        copied = _evidence_copy(chain, name)
        mutate(copied)
        with pytest.raises(audit.EntryError) as exc:
            _audit(chain, audit, tmp_path / name, evidence_dir=copied)
        assert exc.value.code in expected or exc.value.code in {
            "evidence_tree_sha_mismatch",
            "evidence_tree_bytes_mismatch",
            "evidence_tree_file_count_mismatch",
        }, (name, exc.value.code)


def test_refuses_paths_outside_historical_root(audit: Any, chain: Any, tmp_path: Path) -> None:
    stray = tmp_path / "stray" / "run-receipt.json"
    stray.parent.mkdir(parents=True)
    shutil.copyfile(_seal_dir(chain) / "run-receipt.json", stray)
    with pytest.raises(audit.EntryError) as exc:
        _audit(chain, audit, tmp_path, receipt_path=stray)
    assert exc.value.code == "path_outside_historical_root"


def test_refuses_output_inside_historical_root_or_repo(audit: Any, chain: Any) -> None:
    with pytest.raises(audit.EntryError) as exc:
        audit.audit_historical(**_kwargs(chain, chain.work / "inside"))
    assert exc.value.code == "output_inside_historical_root"
    with pytest.raises(audit.EntryError) as exc2:
        audit.audit_historical(**_kwargs(chain, ROOT / "docs" / "t207-audit-inside"))
    assert exc2.value.code == "path_inside_forbidden_root"


def test_refuses_case_plan_contradiction(audit: Any, chain: Any, tmp_path: Path) -> None:
    fixtures = _fixtures(chain)
    payload = json.loads(Path(str(chain.case_plan_path)).read_text(encoding="utf-8"))
    payload["run_binding"] = {**payload["run_binding"], "go_sha256": "d" * 64}
    forged = fixtures / "case-plan-contradiction.json"
    forged.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(audit.EntryError) as exc:
        _audit(chain, audit, tmp_path, case_plan_path=forged)
    assert exc.value.code in {
        "case_plan_sha256_mismatch",
        "case_plan_binding_mismatch",
        "case_plan_invalid",
        "run_receipt_binding_mismatch",
    }


def test_refuses_tampered_seal_manifest(audit: Any, chain: Any, tmp_path: Path) -> None:
    fixtures = _fixtures(chain)
    seal = json.loads(_seal_manifest_path(chain).read_text(encoding="utf-8"))
    seal["evidence_root"] = {**seal["evidence_root"], "tree_sha256": "0" * 64}
    forged = fixtures / "seal-manifest-tampered.json"
    forged.write_text(json.dumps(seal, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(audit.EntryError) as exc:
        _audit(chain, audit, tmp_path, seal_manifest_path=forged)
    assert exc.value.code == "seal_manifest_binding_mismatch"


def test_secret_bearing_error_is_not_echoed(audit: Any, chain: Any, tmp_path: Path) -> None:
    secret = helper.CHAT_SECRET
    bad = _fixtures(chain) / "secret.key"
    bad.write_text(secret + "\n", encoding="utf-8")
    with pytest.raises(audit.EntryError) as exc:
        _audit(chain, audit, tmp_path, evidence_key_file=bad)
    text = json.dumps({"code": exc.value.code, "detail": exc.value.detail}, ensure_ascii=False)
    assert secret not in text
    assert exc.value.code in {"evidence_key_invalid", "evidence_key_mismatch", "run_receipt_invalid"}


def test_original_source_freeze_status_is_explicit(audit: Any, chain: Any, tmp_path: Path) -> None:
    payload = _audit(chain, audit, tmp_path)
    freeze = payload["identity"]["original_source_freeze"]
    assert freeze["status"] == "unavailable"
    assert freeze["claims_original_program_reconstructed"] is False

    manifest = _fixtures(chain) / "source-freeze.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "synthetic-freeze/v1",
                "aggregate_sha256": "e" * 64,
                "files": [
                    {
                        "path": "backend/src/mktkb/evaluation/p2_hard_evidence.py",
                        "sha256": "f" * 64,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    with_manifest = _audit(
        chain, audit, tmp_path / "second", original_source_freeze=manifest
    )
    status = with_manifest["identity"]["original_source_freeze"]
    assert status["status"] == "identity_only_manifest_no_bytes"
    assert status["code_version_reproduced"] is False
    assert status["claims_original_program_reconstructed"] is False
    assert status["manifest_file_count"] == 1


def test_original_live_recompute_still_refuses_changed_code(
    controlled: Any, chain: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """保留旧检查：不 patch 源码、不伪造 code_digest、不加通用 --ignore-code-version。"""
    monkeypatch.setattr(controlled, "AUTHORIZED_ENV_PATH", chain.env_path)
    monkeypatch.setattr(controlled, "code_digest", lambda: "9" * 64)
    with pytest.raises(controlled.EntryError) as exc:
        controlled.recompute(
            env_file=chain.env_path,
            binding_path=chain.plan_payload["binding_file"],
            run_index=0,
            evidence_dir=chain.evidence_dir,
            evidence_key_file=chain.key_path,
            case_plan_path=chain.case_plan_path,
            runtime=chain.private.runtime,
            ledger_path=chain.ledger,
            receipt_path=_seal_dir(chain) / "run-receipt.json",
            out_card=tmp_path / "should-not-exist.json",
        )
    assert exc.value.code == "code_changed_since_plan"


# --------------------------------------------------------------------------- #
# CLI / 网络 guard / 无 live 能力
# --------------------------------------------------------------------------- #

SITECUSTOMIZE = '''"""synthetic outbound + provider tripwire: record every attempt."""
import os

import socket

_RealSocket = socket.socket


def _record(path_env):
    path = os.environ.get(path_env)
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write("blocked\\n")


def _deny(*args, **kwargs):
    _record("AUDIT_SOCKET_LOG")
    raise OSError("outbound network blocked by synthetic guard")


def _deny_dns(*args, **kwargs):
    _record("AUDIT_DNS_LOG")
    raise OSError("dns blocked by synthetic guard")


class _DeniedSocket(_RealSocket):
    def __init__(self, *args, **kwargs):
        _record("AUDIT_SOCKET_LOG")
        raise OSError("outbound network blocked by synthetic guard")


socket.socket = _DeniedSocket
socket.create_connection = _deny
socket.socketpair = _deny
socket.getaddrinfo = _deny_dns

try:
    import httpx

    def _provider_deny(*args, **kwargs):
        _record("AUDIT_PROVIDER_LOG")
        raise OSError("provider client construction blocked by synthetic tripwire")

    httpx.Client.__init__ = _provider_deny
    httpx.AsyncClient.__init__ = _provider_deny
    httpx.post = _provider_deny
    httpx.get = _provider_deny
except Exception:  # noqa: BLE001 - fail closed：httpx 缺失时显式留痕，测试会失败而不是静默跳过
    _record_text = os.environ.get("AUDIT_PROVIDER_LOG")
    if _record_text:
        with open(_record_text, "a", encoding="utf-8") as handle:
            handle.write("provider_tripwire_unavailable\\n")
'''

WRAPPER_TEMPLATE = '''"""synthetic CLI wrapper: real audit main(), only fixed ledger path injected."""
import importlib.util
import sys
from pathlib import Path

from mktkb.evaluation import p2_authorization as p2a

p2a.P2_LEDGER_PATH = Path(r"{ledger}")
p2a.P2_BUDGET_PATH = Path(r"{budget}")
p2a.P2_GO_PATH = Path(r"{go}")
spec = importlib.util.spec_from_file_location("p2_h2_historical_audit_cli", r"{tool}")
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
sys.exit(module.main(sys.argv[1:]))
'''


def _cli(
    chain: Any,
    tmp_path: Path,
    *args: str,
    out_name: str = "cli",
) -> tuple[subprocess.CompletedProcess[str], dict[str, Any] | None, dict[str, str]]:
    site = tmp_path / ("site-" + out_name)
    site.mkdir(parents=True, exist_ok=True)
    (site / "sitecustomize.py").write_text(SITECUSTOMIZE, encoding="utf-8")
    logs = {
        "socket": tmp_path / ("socket-" + out_name + ".log"),
        "dns": tmp_path / ("dns-" + out_name + ".log"),
        "provider": tmp_path / ("provider-" + out_name + ".log"),
    }
    for path in logs.values():
        if path.exists():
            path.unlink()
    wrapper = tmp_path / ("wrapper-" + out_name + ".py")
    wrapper.write_text(
        WRAPPER_TEMPLATE.format(
            tool=str(AUDIT_TOOL),
            ledger=str(chain.ledger),
            budget=str(chain.budget),
            go=str(chain.go_path),
        ),
        encoding="utf-8",
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = str(site) + os.pathsep + str(ROOT / "backend" / "src")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["MKTKB_NO_DOTENV"] = "1"
    env["AUDIT_SOCKET_LOG"] = str(logs["socket"])
    env["AUDIT_DNS_LOG"] = str(logs["dns"])
    env["AUDIT_PROVIDER_LOG"] = str(logs["provider"])
    completed = subprocess.run(
        [sys.executable, "-B", str(wrapper), *args],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=900,
    )
    payload = None
    for line in reversed([line for line in completed.stdout.splitlines() if line.strip()]):
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        break
    attempts = {
        "socket": logs["socket"].read_text(encoding="utf-8") if logs["socket"].exists() else "",
        "dns": logs["dns"].read_text(encoding="utf-8") if logs["dns"].exists() else "",
        "provider": (
            logs["provider"].read_text(encoding="utf-8") if logs["provider"].exists() else ""
        ),
    }
    return completed, payload, attempts


def _cli_args(chain: Any, out_dir: Path) -> list[str]:
    return [
        "audit-historical",
        "--historical-root",
        str(chain.work),
        "--run-binding",
        str(chain.plan_payload["binding_file"]),
        "--run-index",
        "0",
        "--evidence-dir",
        str(chain.evidence_dir),
        "--evidence-key-file",
        str(chain.key_path),
        "--case-plan",
        str(chain.case_plan_path),
        "--run-receipt",
        str(_seal_dir(chain) / "run-receipt.json"),
        "--seal-manifest",
        str(_seal_manifest_path(chain)),
        "--run-out-root",
        str(_run_out_root(chain)),
        "--ledger-path",
        str(chain.ledger),
        "--holdout-root",
        str(chain.private.holdout_root),
        "--holdout-key-file",
        str(chain.private.holdout_key_file),
        "--project-total-limit-cny",
        "40",
        "--out-dir",
        str(out_dir),
    ]


def test_cli_audit_end_to_end_zero_outbound_and_public_safe(
    chain: Any, tmp_path: Path
) -> None:
    out_dir = tmp_path / "cli-out"
    completed, payload, attempts = _cli(chain, tmp_path, *_cli_args(chain, out_dir))
    assert completed.returncode == 0, completed.stderr[-3000:]
    assert payload is not None and payload["ok"] is True, payload
    assert payload["analysis_kind"] == "historical_reassessment"
    assert payload["authorizes_live"] is False
    assert payload["release_ready"] is False
    assert payload["guard"]["provider_entry_attempts"] == 0
    assert attempts == {"socket": "", "dns": "", "provider": ""}
    text = completed.stdout + completed.stderr
    for needle in SENTINELS:
        assert needle not in text, needle
    files = sorted(p.name for p in out_dir.iterdir())
    assert files == ["result-aggregate.json"], files
    aggregate = json.loads((out_dir / "result-aggregate.json").read_text(encoding="utf-8"))
    assert aggregate["schema_version"] == "t207-historical-audit/v0.1"
    body = json.dumps(aggregate, ensure_ascii=False)
    for needle in SENTINELS:
        assert needle not in body, needle


def test_network_guard_blocks_socket_and_dns_in_subprocess(tmp_path: Path) -> None:
    """独立子进程实测：guard 装上后 socket 连接与 DNS 解析都必须失败，且被计数。"""
    probe = tmp_path / "guard_probe.py"
    probe.write_text(
        "\n".join(
            [
                "import importlib.util, json, sys",
                "spec = importlib.util.spec_from_file_location('guarded', r'" + str(AUDIT_TOOL) + "')",
                "module = importlib.util.module_from_spec(spec)",
                "sys.modules[spec.name] = module",
                "spec.loader.exec_module(module)",
                "result = {'socket_blocked': False, 'dns_blocked': False}",
                "result['provider_blocked'] = False",
                "import socket as _s",
                "original_socket = _s.socket",
                "original_getaddrinfo = _s.getaddrinfo",
                "module.GUARD_COUNTERS.reset()",
                "with module.network_guard():",
                "    try:",
                "        module.socket.create_connection(('127.0.0.1', 9), timeout=0.2)",
                "    except module.NetworkGuardBlocked:",
                "        result['socket_blocked'] = True",
                "    try:",
                "        module.socket.getaddrinfo('example.invalid', 80)",
                "    except module.NetworkGuardBlocked:",
                "        result['dns_blocked'] = True",
                "    try:",
                "        import httpx",
                "        httpx.Client(timeout=1.0)",
                "    except module.NetworkGuardBlocked:",
                "        result['provider_blocked'] = True",
                "result.update(module.GUARD_COUNTERS.snapshot())",
                "result['restored'] = {'socket': _s.socket is original_socket,",
                "                      'getaddrinfo': _s.getaddrinfo is original_getaddrinfo}",
                "try:",
                "    _s.socket(_s.AF_INET, _s.SOCK_DGRAM).close()",
                "    result['restored']['constructible'] = True",
                "except Exception:",
                "    result['restored']['constructible'] = False",
                "print(json.dumps(result, sort_keys=True))",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "backend" / "src")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["MKTKB_NO_DOTENV"] = "1"
    completed = subprocess.run(
        [sys.executable, "-B", str(probe)],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert completed.returncode == 0, completed.stderr[-2000:]
    result = json.loads(completed.stdout.strip().splitlines()[-1])
    assert result["socket_blocked"] is True, result
    assert result["dns_blocked"] is True, result
    assert result["provider_blocked"] is True, result
    assert result["socket_attempts"] >= 1, result
    assert result["dns_attempts"] >= 1, result
    assert result["provider_entry_attempts"] >= 1, result
    assert result["restored"] == {
        "socket": True,
        "getaddrinfo": True,
        "constructible": True,
    }, result


@pytest.mark.parametrize(
    "argv",
    [
        ["run"],
        ["plan-private"],
        ["preflight"],
        ["recompute"],
        ["sign-go"],
    ],
)
def test_cli_has_no_live_subcommands(chain: Any, tmp_path: Path, argv: list[str]) -> None:
    completed, payload, attempts = _cli(chain, tmp_path, *argv, out_name="deny")
    assert completed.returncode == 3, completed.stdout[-1000:]
    assert payload is not None and payload["ok"] is False
    assert payload["error_code"] == "usage_invalid"
    assert attempts == {"socket": "", "dns": "", "provider": ""}


def test_cli_rejects_forbidden_flags_even_with_full_required_args(
    chain: Any, tmp_path: Path
) -> None:
    """C9：必须带齐必需参数再追加禁止标志，否则“缺参数”也会 exit 3，证明不了 parser 拒绝。"""
    sentinel = "P2H2ENTRY_TEST_SECRET_VALUE_DO_NOT_EXPORT"
    dash_sentinel = "-P2H2ENTRY_DASH_SECRET_DO_NOT_EXPORT"
    pattern = re.compile(r"^usage_invalid(:--[a-z0-9-]+(?:,--[a-z0-9-]+)*)?$")
    out_dir = tmp_path / "forbidden-out"
    for flag, value in (
        ("--env-file", sentinel),
        ("--go-path", sentinel),
        ("--ignore-code-version", sentinel),
        ("--ignore-hash", sentinel),
        ("--code-version", dash_sentinel),
    ):
        completed, payload, attempts = _cli(
            chain,
            tmp_path,
            *_cli_args(chain, out_dir),
            flag,
            value,
            out_name="forbidden" + flag.replace("-", ""),
        )
        assert completed.returncode == 3, (flag, completed.stdout[-500:])
        assert payload is not None and payload["error_code"] == "usage_invalid"
        # C8c：detail 只允许“已知选项名”，绝不回显任何参值（含 dash 前缀值）。
        assert pattern.match(str(payload["detail"])), (flag, payload["detail"])
        assert sentinel not in completed.stdout
        assert "DASH_SECRET" not in completed.stdout
        assert sentinel not in str(payload)
        assert attempts == {"socket": "", "dns": "", "provider": ""}
    assert not out_dir.exists()


def test_cli_requires_run_out_root(chain: Any, tmp_path: Path) -> None:
    """C6b：CLI 层缺 --run-out-root 必须是 usage_invalid（argparse 必填），并回显选项名。"""
    args = [item for item in _cli_args(chain, tmp_path / "no-out-root")]
    index = args.index("--run-out-root")
    del args[index : index + 2]
    completed, payload, attempts = _cli(chain, tmp_path, *args, out_name="no-out-root")
    assert completed.returncode == 3, completed.stdout[-500:]
    assert payload is not None and payload["error_code"] == "usage_invalid"
    assert "--run-out-root" in str(payload["detail"])
    assert attempts == {"socket": "", "dns": "", "provider": ""}

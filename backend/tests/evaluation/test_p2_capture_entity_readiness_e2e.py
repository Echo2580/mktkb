"""T207 C：同一最终冻结对象的集成离线就绪 E2E。

链路：真实 ProductEvalAdapter 装配 + 合成 provider → 采集/加密封存 → 关闭产品实例并删除
合成业务库/trace → 另一独立进程严格读回 + 四轴重算（零模型/检索/实时 DB）→ 公开卡/回执/阻断。

只用公共 fixtures、合成题/合同/key/临时库；不读真实 H2/私有材料；零真实外连。
"""

from __future__ import annotations

import asyncio
import functools
import json
import os
import shutil
import subprocess
import sys
import uuid
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from cryptography.fernet import Fernet

_TESTS_DIR = Path(__file__).resolve().parents[1]
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

from acceptance.support.netguard import t09_network_guard  # noqa: E402,F401

from mktkb.evaluation import p2_hard_evidence as hard  # noqa: E402
from mktkb.evaluation.dataset import CaseSpec, write_cases  # noqa: E402
from mktkb.evaluation.p2_evidence_capture import (  # noqa: E402
    BINDING_KEYS,
    EvidenceCaptureConfig,
)
from mktkb.evaluation.p2_evidence_io import (  # noqa: E402
    EvidenceWriter,
    canonical_json_bytes,
    read_encrypted_evidence,
)
from mktkb.evaluation.product_adapter import (  # noqa: E402
    IngestSource,
    MockChatBackend,
    P2IngestPlan,
    P2RunDataset,
    ProductEvalAdapter,
)
from evaluation.test_p2_hard_evidence import (  # noqa: E402
    EVIDENCE_BINDINGS,
    make_annotation,
    make_audit,
    model_answer_empty_scope,
)

pytestmark = pytest.mark.usefixtures("t09_network_guard")

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "fixtures" / "acceptance"
D01 = FIXTURES / "normal" / "D01_物品位置表.xlsx"
D04 = FIXTURES / "normal" / "D04_活动策划流程.docx"
SENTINEL = "T207_OFFLINE_READINESS_SENTINEL_DO_NOT_EXPORT_7f3a"
V03 = "p2-hard-evidence-capture/v0.3"
SEMANTICS = "p2-hard-evidence-classification/v0.2"

SITE_CUSTOMIZE = '''
import builtins
import os
import socket

_real_import = builtins.__import__
_FORBIDDEN = (
    "mktkb.rag", "mktkb.qa", "mktkb.conversations", "mktkb.providers",
    "mktkb.evaluation.product_adapter",
)

def _guard(name, *args, **kwargs):
    if name.startswith(_FORBIDDEN):
        with open(os.environ["T207_FORBIDDEN_LOG"], "a", encoding="utf-8") as stream:
            stream.write(name + "\\n")
    return _real_import(name, *args, **kwargs)

builtins.__import__ = _guard

def _blocked(*args, **kwargs):
    with open(os.environ["T207_SOCKET_LOG"], "a", encoding="utf-8") as stream:
        stream.write("socket-attempt\\n")
    raise OSError("network blocked by T207 offline guard")

socket.socket.connect = _blocked
socket.create_connection = _blocked
socket.getaddrinfo = _blocked
'''


def asyncio_test(func):
    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any):
        return asyncio.run(func(*args, **kwargs))

    return wrapper


def _bindings(run_id: str) -> dict[str, str]:
    values = {key: "local_mock-" + key for key in BINDING_KEYS}
    values["fixture_kind"] = "local_mock"
    values["run_id"] = run_id
    values["dataset_version"] = "readiness-v1"
    values["plan_sha256"] = "e" * 64
    return values


def _dataset() -> P2RunDataset:
    return P2RunDataset(
        visibility="public",
        cases=(),
        identity={
            "dataset_version": "readiness-v1",
            "label_version": "synthetic-v1",
            "suite": "p2-holdout",
            "manifest_sha256": "b" * 64,
            "case_count": 0,
        },
    )


def _target(entity_key: str, store: str) -> dict[str, Any]:
    return {"entity_type": "item", "entity_key": entity_key, "filters": {"store": store}}


def _scope_contract(
    cases: tuple[Any, ...], bindings: dict[str, str], shared: dict[str, Any]
) -> dict[str, Any]:
    rows = []
    for case in cases:
        if case.case_id == "RD-A":
            rows.append(
                {
                    "case_key": case.case_id,
                    "mode": "shared_background_only",
                    "targets": [],
                    "shared_background": [
                        {
                            "document_id": shared["document_id"],
                            "version_id": shared["version_id"],
                            "unit_ids": list(shared["unit_ids"]),
                            "scope_filters": {},
                            "basis": "frozen_public_corpus_structure",
                        }
                    ],
                }
            )
        elif case.case_id == "RD-B":
            rows.append(
                {
                    "case_key": case.case_id,
                    "mode": "no_entity_scope",
                    "targets": [],
                    "shared_background": [],
                }
            )
        elif case.case_id == "RD-D":
            rows.append(
                {
                    "case_key": case.case_id,
                    "mode": "entity_bound",
                    "targets": [_target("item|id:p01", "城东店")],
                    "shared_background": [],
                }
            )
        else:
            rows.append(
                {
                    "case_key": case.case_id,
                    "mode": "entity_bound",
                    "targets": [
                        _target("item|id:p01", "城东店"),
                        _target("item|id:p02", "城西店"),
                    ],
                    "shared_background": [],
                }
            )
    return {
        "schema_version": "p2-entity-scope/v0.1",
        "semantics_version": SEMANTICS,
        "bindings": {
            "run_id": bindings["run_id"],
            "plan_id": bindings["plan_id"],
            "plan_sha256": bindings["plan_sha256"],
        },
        "cases": rows,
    }


def _annotation(cases: tuple[Any, ...]) -> dict[str, Any]:
    return make_annotation(
        cases,
        overrides={
            "RD-B": {
                "cross_entity": {
                    "applicability": "not_applicable",
                    "criterion": "no_entity_claim",
                    "reason": "no_entity_scope",
                }
            }
        },
    )


def _cases() -> tuple[Any, ...]:
    template = CaseSpec(
        case_id="RD-T",
        suite="p2-holdout",
        split="holdout",
        stratum=str(hard.STRATA[0]),
        business_date="2026-10-28",
        question="合成问题",
        turns=(),
        expected_values=(),
        expected_sources=(),
        relevant_units=(),
        should_refuse=False,
        labeler="synthetic-fixture",
        label_version="synthetic-v1",
    )
    enumeration = "把城东店和城西店的宣传海报记录都列出来"
    return (
        replace(
            template,
            case_id="RD-A",
            question="",
            turns=(
                {"question": "活动策划需要哪些步骤？"},
                {"question": "活动策划需要哪些审批？"},
            ),
        ),
        replace(template, case_id="RD-B", question="食堂几点开门？", turns=()),
        replace(template, case_id="RD-C", question=enumeration, turns=()),
        replace(template, case_id="RD-D", question=enumeration, turns=()),
    )


def _corpus_shared_units(adapter: ProductEvalAdapter) -> dict[str, Any]:
    """提问前从合成语料冻结 D04 的 document/version/unit 身份（不是从答案生成）。"""
    from sqlalchemy import select

    from mktkb.documents.models import Document, DocumentVersion, SourceUnit

    db = adapter._app.state.db.session()
    try:
        rows = db.execute(
            select(Document, DocumentVersion, SourceUnit)
            .join(DocumentVersion, SourceUnit.version_id == DocumentVersion.id)
            .join(Document, SourceUnit.document_id == Document.id)
            .where(Document.name.like("%D04%"))
        ).all()
    finally:
        db.close()
    assert rows, "合成语料必须包含 D04"
    document, version = rows[0][0], rows[0][1]
    return {
        "document_id": str(document.id),
        "version_id": str(version.id),
        "unit_ids": sorted(str(unit.id) for _, _, unit in rows),
    }


async def _capture(
    tmp_path: Path, bindings: dict[str, str]
) -> tuple[EvidenceWriter, list[Any], dict[str, Any], dict[str, str], dict[str, Any]]:
    writer = EvidenceWriter(
        root_dir=tmp_path / "evidence",
        key=Fernet.generate_key(),
        bindings=bindings,
        run_name="run",
    )
    adapter = ProductEvalAdapter(
        tmp_path / "product",
        chat=MockChatBackend(),
        dataset=_dataset(),
        ingest_plan=P2IngestPlan(sources=(IngestSource(D01), IngestSource(D04)), label="rd"),
        evidence_capture=EvidenceCaptureConfig(
            root_dir=tmp_path / "evidence",
            bindings=bindings,
            writer=writer,
            capture_schema_version=V03,
        ),
        purge_traces_on_close=True,
    )
    turns = []
    try:
        await adapter.start()
        await adapter.ingest()
        session = adapter._evidence_session
        assert session is not None
        session.bind(adapter.binding_components())
        merged = dict(session.bindings)
        scope = _scope_contract(_cases(), merged, _corpus_shared_units(adapter))
        conversation = await adapter.open_conversation()
        for question in (
            "活动策划需要哪些步骤？",
            "活动策划需要哪些审批？",
            "食堂几点开门？" + SENTINEL,
            "把城东店和城西店的宣传海报记录都列出来",
        ):
            turns.append(
                await adapter.ask_turn(
                    question,
                    user_id="employee",
                    conversation_id=conversation,
                    client_request_id=str(uuid.uuid4()),
                )
            )
        second = await adapter.open_conversation()
        turns.append(
            await adapter.ask_turn(
                "把城东店和城西店的宣传海报记录都列出来",
                user_id="employee",
                conversation_id=second,
                client_request_id=str(uuid.uuid4()),
            )
        )
        assert session.blocked is False
    finally:
        await adapter.close()
    manifest = adapter.evidence_capture_manifest()
    assert manifest is not None
    return writer, turns, manifest, merged, scope


def _write_inputs(
    tmp_path: Path,
    *,
    writer: EvidenceWriter,
    manifest: dict[str, Any],
    cases: tuple[Any, ...],
    bindings: dict[str, str],
    scope: dict[str, Any],
) -> dict[str, Any]:
    receipts = sorted(
        (item for item in writer.written if item["kind"] == "turn"),
        key=lambda item: item["turn_index"],
    )
    manifest_receipt = next(item for item in writer.written if item["kind"] == "manifest")
    assert [item["turn_index"] for item in receipts] == [0, 1, 2, 3, 4]
    evidence_dir = Path(receipts[0]["path"]).parent
    files = [Path(item["path"]).name for item in receipts]

    write_cases(tmp_path / "cases.jsonl", cases)
    annotation = _annotation(cases)
    (tmp_path / "annotation.json").write_text(
        json.dumps(annotation, ensure_ascii=False), encoding="utf-8"
    )
    scope_path = tmp_path / "scope.json"
    scope_bytes = (json.dumps(scope, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    scope_path.write_bytes(scope_bytes)
    import hashlib

    config_hash = hashlib.sha256(scope_bytes).hexdigest()
    rows = [
        {
            "case_id": cases[0].case_id,
            "quality_status": "pass",
            "turns": [
                {"turn_index": 0, "status": "executed", "evidence_file": files[0], "error": None},
                {"turn_index": 1, "status": "executed", "evidence_file": files[1], "error": None},
            ],
        },
        {
            "case_id": cases[1].case_id,
            "quality_status": "pass",
            "turns": [
                {"turn_index": 2, "status": "executed", "evidence_file": files[2], "error": None}
            ],
        },
        {
            "case_id": cases[2].case_id,
            "quality_status": "pass",
            "turns": [
                {"turn_index": 3, "status": "executed", "evidence_file": files[3], "error": None}
            ],
        },
        {
            "case_id": cases[3].case_id,
            "quality_status": "pass",
            "turns": [
                {"turn_index": 4, "status": "executed", "evidence_file": files[4], "error": None}
            ],
        },
    ]
    case_plan = {
        "schema_version": hard.CASEPLAN_SCHEMA_VERSION,
        "bindings": dict(bindings),
        "run_id": bindings["run_id"],
        "config_hash": config_hash,
        "execution_mode": "local_mock",
        "real_calls": 0,
        "thresholds_approved": False,
        "expected_strata": {
            name: sum(1 for case in cases if case.stratum == name)
            for name in hard.STRATA
            if any(case.stratum == name for case in cases)
        },
        "cases": rows,
    }
    (tmp_path / "case-plan.json").write_text(
        json.dumps(case_plan, ensure_ascii=False), encoding="utf-8"
    )
    key_file = tmp_path / "synthetic.key"
    key_file.write_bytes(bytes(writer.key))
    return {
        "cases": cases,
        "cases_path": tmp_path / "cases.jsonl",
        "annotation_path": tmp_path / "annotation.json",
        "case_plan_path": tmp_path / "case-plan.json",
        "case_plan": case_plan,
        "key_file": key_file,
        "manifest_path": Path(manifest_receipt["path"]),
        "evidence_dir": evidence_dir,
        "files": files,
        "scope_path": scope_path,
        "scope_sha256": config_hash,
    }


def _run_cli(
    tmp_path: Path,
    inputs: dict[str, Any],
    out_path: Path,
    *,
    scope: bool = True,
    case_plan_path: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    site = tmp_path / "site"
    site.mkdir(exist_ok=True)
    (site / "sitecustomize.py").write_text(SITE_CUSTOMIZE, encoding="utf-8")
    socket_log = tmp_path / "socket.log"
    forbidden_log = tmp_path / "forbidden.log"
    for path in (socket_log, forbidden_log):
        if path.exists():
            path.unlink()
    env = dict(os.environ)
    env["PYTHONPATH"] = str(site) + os.pathsep + str(ROOT / "backend" / "src")
    env["MKTKB_NO_DOTENV"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["T207_SOCKET_LOG"] = str(socket_log)
    env["T207_FORBIDDEN_LOG"] = str(forbidden_log)
    env["TEMP"] = str(tmp_path / "external-temp")
    env["TMP"] = str(tmp_path / "external-temp")
    Path(env["TEMP"]).mkdir(exist_ok=True)
    command = [
        sys.executable,
        "-B",
        "-m",
        "mktkb.evaluation.cli",
        "p2-hard-evidence-recompute",
        "--evidence-dir",
        str(inputs["evidence_dir"]),
        "--case-plan",
        str(case_plan_path or inputs["case_plan_path"]),
        "--cases",
        str(inputs["cases_path"]),
        "--annotation",
        str(inputs["annotation_path"]),
        "--key-file",
        str(inputs["key_file"]),
        "--out",
        str(out_path),
        "--manifest",
        str(inputs["manifest_path"]),
    ]
    if scope:
        command += ["--scope-contract", str(inputs["scope_path"])]
    completed = subprocess.run(
        command, cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=300
    )
    completed.socket_attempts = socket_log.read_text(encoding="utf-8") if socket_log.exists() else ""  # type: ignore[attr-defined]
    completed.forbidden_imports = forbidden_log.read_text(encoding="utf-8") if forbidden_log.exists() else ""  # type: ignore[attr-defined]
    return completed


def _canonical(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _offline_recompute(inputs: dict[str, Any]) -> tuple[dict[str, Any], list[Any]]:
    plan_meta, audits = hard.load_case_audits_from_encrypted(
        evidence_dir=inputs["evidence_dir"],
        case_plan_path=inputs["case_plan_path"],
        cases=inputs["cases"],
        key_file=inputs["key_file"],
        manifest_path=inputs["manifest_path"],
    )
    annotation = hard.prepare_annotation(_annotation(inputs["cases"]), inputs["cases"])
    scope = hard.load_scope_contract(
        json.loads(inputs["scope_path"].read_text(encoding="utf-8")),
        expected_bindings=plan_meta["bindings"],
    )
    card, results = hard.recompute_hard_evidence(
        inputs["cases"], annotation, audits, plan_meta=plan_meta, scope_contract=scope
    )
    return card, results


@asyncio_test
async def test_v03_capture_to_offline_recompute_and_public_card(tmp_path: Path) -> None:
    bindings = _bindings("readiness-run-1")
    writer, turns, manifest, merged, scope = await _capture(tmp_path, bindings)
    cases = _cases()
    inputs = _write_inputs(
        tmp_path, writer=writer, manifest=manifest, cases=cases, bindings=merged, scope=scope
    )

    # C2：关闭产品实例后删除合成业务库/trace，重算只能依赖认证密文。
    shutil.rmtree(tmp_path / "product", ignore_errors=True)
    for item in writer.written:
        assert read_encrypted_evidence(
            Path(item["path"]), key=writer.key, expected_bindings=writer.bindings
        )

    card, results = _offline_recompute(inputs)
    # R0（entity_key 统一）：产品 fact 键与 db_projection 单位键改为同一派生，results[2] 的
    # fact 分支不再落到 entity_identity_unresolved（改前恒为 unknown），实体身份可判 => passed。
    assert [result.axis_state("cross_entity") for result in results] == [
        "passed",
        "unknown",
        "passed",
        "violation",
    ], [result.axis_state("cross_entity") for result in results]
    assert results[1].axes["cross_entity"].reason in {
        "model_events_missing",
        "empty_set_not_proven",
        "branch_evidence_missing",
    }
    assert "entity_identity_unresolved" not in results[2].missing_codes
    assert results[3].axes["cross_entity"].reason == "other_entity_used"
    for result in results:
        assert result.evidence_complete is True
    assert results[0].axis_state("cross_user") == "passed"
    assert results[1].axis_state("cross_user") == "unknown"  # 分支门固定码同时作用于四轴
    assert results[2].axis_state("cross_user") == "passed"
    assert results[3].axis_state("cross_user") == "passed"
    assert card["release_ready"] is False
    assert card["total"] == 4
    hard.validate_hard_evidence_scorecard(
        card,
        total=4,
        run_id=inputs["case_plan"]["run_id"],
        config_hash=inputs["scope_sha256"],
        expected_strata=inputs["case_plan"]["expected_strata"],
    )

    out_path = tmp_path / "external-out" / "card.json"
    completed = _run_cli(tmp_path, inputs, out_path)
    assert completed.returncode == 0, completed.stderr
    card_cli = json.loads(out_path.read_text(encoding="utf-8"))
    assert _canonical(card_cli) == _canonical(card)
    assert completed.socket_attempts == ""
    assert completed.forbidden_imports == ""
    receipt = json.loads(completed.stdout.strip().splitlines()[-1])
    assert receipt["ok"] is True and receipt["total"] == 4
    assert receipt["scope_contract_sha256"] == inputs["scope_sha256"]
    assert receipt["scope_contract_case_count"] == 4
    assert receipt["release_ready"] is False
    public = out_path.read_text(encoding="utf-8")
    for case in cases:
        assert case.case_id not in public
        if case.question:
            assert case.question not in public
        for turn in case.turns:
            assert str(turn.get("question") or "") not in public
    assert SENTINEL not in public
    assert SENTINEL not in completed.stdout and SENTINEL not in completed.stderr

    # C3：原评分输入可从密文重建（不执行质量重评分，C10 列 NOT-RUN）。
    for item in writer.written:
        if item["kind"] != "turn":
            continue
        envelope = read_encrypted_evidence(
            Path(item["path"]), key=writer.key, expected_bindings=writer.bindings
        )
        snapshot = envelope["runtime_snapshot"]
        assert snapshot["product_response"]["kind"] is not None
        assert snapshot["product_response"]["request_id"] is not None
        assert envelope["completeness"]["scoring_readiness"]["quality_rescore"] is True


@asyncio_test
async def test_negative_mutations_are_rejected_or_unknown(tmp_path: Path) -> None:
    bindings = _bindings("readiness-run-2")
    writer, turns, manifest, merged, scope = await _capture(tmp_path, bindings)
    cases = _cases()
    inputs = _write_inputs(
        tmp_path, writer=writer, manifest=manifest, cases=cases, bindings=merged, scope=scope
    )

    # 1) 缺 runtime_snapshot：严格 reader 固定拒绝（CLI 非 0，不产卡）。
    broken = tmp_path / "broken"
    shutil.copytree(inputs["evidence_dir"], broken / "evidence")
    target = broken / "evidence" / inputs["files"][0]
    payload = read_encrypted_evidence(target, key=writer.key)
    payload.pop("runtime_snapshot")
    target.write_bytes(Fernet(writer.key).encrypt(canonical_json_bytes(payload)))
    local = dict(inputs)
    local["evidence_dir"] = broken / "evidence"
    out = tmp_path / "external-out" / "bad.json"
    completed = _run_cli(tmp_path, local, out)
    assert completed.returncode != 0 and not out.exists()

    # 2) 坏 pagination：枚举轮严格 reader 固定拒绝。
    bad_page = tmp_path / "badpage"
    shutil.copytree(inputs["evidence_dir"], bad_page / "evidence")
    target = bad_page / "evidence" / inputs["files"][3]
    payload = read_encrypted_evidence(target, key=writer.key)
    pagination = payload["runtime_snapshot"]["product_response"]["pagination"]
    assert pagination is not None
    pagination["returned"] = pagination["total"] + 1
    target.write_bytes(Fernet(writer.key).encrypt(canonical_json_bytes(payload)))
    local = dict(inputs)
    local["evidence_dir"] = bad_page / "evidence"
    out = tmp_path / "external-out" / "badpage.json"
    completed = _run_cli(tmp_path, local, out)
    assert completed.returncode != 0 and not out.exists()

    # 3) 重复 model_input：reader 放行，但 turn 级分支门 → 全轴 unknown，不得 pass。
    duplicate = tmp_path / "duplicate"
    shutil.copytree(inputs["evidence_dir"], duplicate / "evidence")
    target = duplicate / "evidence" / inputs["files"][0]
    payload = read_encrypted_evidence(target, key=writer.key)
    events = payload["capture"]["events"]
    source = next(event for event in events if event["kind"] == "model_input")
    repeated = json.loads(json.dumps(source))
    repeated["seq"] = len(events) + 1
    events.append(repeated)
    payload["capture"]["event_count"] = len(events)
    payload["capture"]["seq"] = len(events)
    target.write_bytes(Fernet(writer.key).encrypt(canonical_json_bytes(payload)))
    local = dict(inputs)
    local["evidence_dir"] = duplicate / "evidence"
    _, results = _offline_recompute(local)
    assert results[0].axis_state("cross_entity") == "unknown"
    assert "branch_evidence_inconsistent" in results[0].missing_codes

    # 4) 跨 run 绑定：case-plan 与密文绑定不一致 → CLI 非 0。
    cross = tmp_path / "crossrun"
    cross.mkdir()
    plan = json.loads(inputs["case_plan_path"].read_text(encoding="utf-8"))
    plan["bindings"]["run_id"] = "other-run"
    cross_plan = cross / "case-plan.json"
    cross_plan.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "external-out" / "cross.json"
    completed = _run_cli(tmp_path, inputs, out, case_plan_path=cross_plan)
    assert completed.returncode != 0 and not out.exists()

    # 5) 缺 scope 合同：旧语义（targets_unresolved），不得悄悄 pass。
    out = tmp_path / "external-out" / "noscope.json"
    completed = _run_cli(tmp_path, inputs, out, scope=False)
    assert completed.returncode == 0, completed.stderr
    card_no_scope = json.loads(out.read_text(encoding="utf-8"))
    assert card_no_scope["hard_evidence"]["axes"]["cross_entity"]["passed"] == 0
    assert card_no_scope["hard_evidence"]["axes"]["cross_entity"]["unknown"] == 4
    receipt = json.loads(completed.stdout.strip().splitlines()[-1])
    assert receipt["scope_contract_sha256"] is None
    assert receipt["scope_contract_case_count"] == 0

    # 6) 非空原始占位容器：严格空集证明失败 → unknown empty_set_not_proven。
    empty_case = tmp_path / "raw"
    shutil.copytree(inputs["evidence_dir"], empty_case / "evidence")
    target = empty_case / "evidence" / inputs["files"][2]
    payload = read_encrypted_evidence(target, key=writer.key)
    for event in payload["capture"]["events"]:
        if event["kind"] == "answer_result":
            event["payload"]["source_ids"] = [""]
    target.write_bytes(Fernet(writer.key).encrypt(canonical_json_bytes(payload)))
    local = dict(inputs)
    local["evidence_dir"] = empty_case / "evidence"
    _, raw_results = _offline_recompute(local)
    assert raw_results[1].axis_state("cross_entity") == "unknown"
    assert "empty_set_not_proven" in raw_results[1].missing_codes


def test_classifier_level_not_applicable_still_reachable() -> None:
    """链路上 no-fact 拒答未产生显式空检索标志 → 不可证 N/A；分类器层的真模板空集仍可 N/A。"""
    case = _cases()[1]
    bindings = dict(EVIDENCE_BINDINGS)
    bindings["plan_sha256"] = "e" * 64
    evidence = model_answer_empty_scope(bindings=bindings)
    contract_payload = {
        "schema_version": "p2-entity-scope/v0.1",
        "semantics_version": SEMANTICS,
        "bindings": {
            "run_id": bindings["run_id"],
            "plan_id": bindings["plan_id"],
            "plan_sha256": bindings["plan_sha256"],
        },
        "cases": [
            {
                "case_key": case.case_id,
                "mode": "no_entity_scope",
                "targets": [],
                "shared_background": [],
            }
        ],
    }
    scope = hard.load_scope_contract(contract_payload)
    annotation = hard.prepare_annotation(_annotation((case,)), (case,))
    result = hard.classify_case_evidence(
        case, annotation, make_audit(case, evidence), scope_contract=scope
    )
    assert result.axis_state("cross_entity") == "not_applicable"


def test_old_live_gates_remain_and_no_bypass_flags() -> None:
    from mktkb.evaluation.cli import build_parser

    parser = build_parser()
    top_flags = {option for action in parser._actions for option in action.option_strings}
    assert "--scope-contract" not in top_flags
    hard_parser = next(
        action
        for action in parser._actions
        if getattr(action, "choices", None) and "p2-hard-evidence-recompute" in action.choices
    ).choices["p2-hard-evidence-recompute"]
    flags = {option for action in hard_parser._actions for option in action.option_strings}
    assert "--scope-contract" in flags
    assert not any("ignore" in flag and "code" in flag for flag in flags)
    controlled = (ROOT / "tools" / "p2_h2_controlled_execute.py").read_text(encoding="utf-8")
    assert "run_live_p2" in controlled
    assert "open_live_gate" in controlled
    assert "code_changed_since_plan" in controlled

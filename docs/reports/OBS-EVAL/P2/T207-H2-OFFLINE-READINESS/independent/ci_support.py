"""T207-C 集成离线评审（独立验收者 `ai-ci`）自建支持。

只使用公共 fixtures / 合成题面 / 合成 scope 合同 / 合成 Fernet key / 临时隔
离库；不读真实 H2、私有 key/密文、`.env`、宿主缓存；零真实外连。

本文件由独立验收者自写（不是开发测试的复制/搬运）：
- 自建网络 guard（外部出站即失败并记账）；
- 自建 4 题合成 case / annotation / scope 合同 / case-plan；
- 自建“提问 → 采集 → 加密切断 → 删产品现场 → 解密/重算”链路；
- 解密一律用 ``cryptography.Fernet`` 直接对密文做，再自行解析 JSON（不使用产品
  reader 作为唯一证据，避免“用被测读者证明被测读者”）。
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import uuid
from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping

_HERE = Path(__file__).resolve()
ROOT = _HERE.parents[6]
assert (ROOT / "backend" / "src").is_dir(), f"仓库根推断失败: {ROOT}"
_SRC = ROOT / "backend" / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

FIXTURES = ROOT / "fixtures" / "acceptance"
D01 = FIXTURES / "normal" / "D01_物品位置表.xlsx"
D04 = FIXTURES / "normal" / "D04_活动策划流程.docx"

V03 = "p2-hard-evidence-capture/v0.3"
SEMANTICS_V02 = "p2-hard-evidence-classification/v0.2"
SCOPE_SCHEMA = "p2-entity-scope/v0.1"
ANNOTATION_SCHEMA = "p2-h2-custody/v0.2"

#: 合成哨兵：只允许进入认证密文，不得出现在公开卡/stdout/stderr/回执。
SENTINEL = "CI_T207_SENTINEL_9f4d2ab1_NEVER_PUBLIC"

#: 网络 guard 记账（进程内所有外部尝试；任何一条都让本次验证失败）。
NET_EXTERNAL: list[str] = []
NET_LOOPBACK: list[str] = []
_net_installed = False


def _is_loopback(address: Any) -> bool:
    if isinstance(address, str):
        return (
            address.startswith("\\\\.\\pipe\\")
            or address.startswith("/")
            or "localhost" in address
        )
    if isinstance(address, (tuple, list)) and address:
        host = address[0]
        if isinstance(host, bytes):
            host = host.decode("utf-8", "replace")
        return isinstance(host, str) and (
            host in {"127.0.0.1", "::1", "localhost", "0.0.0.0", ""}
            or host.startswith("127.")
        )
    return False


def install_network_guard() -> None:
    """外部出站一律抛错并记账；回环放行（asyncio self-pipe / ASGI 本地链路）。"""
    global _net_installed
    if _net_installed:
        return
    _net_installed = True
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex
    real_create = socket.create_connection
    real_gai = socket.getaddrinfo

    def blocked(label: str, address: Any) -> None:
        if _is_loopback(address):
            NET_LOOPBACK.append(f"{label} {address!r}")
            return
        NET_EXTERNAL.append(f"{label} {address!r}")
        raise OSError(f"CI-NET-GUARD blocked external {label} {address!r}")

    def guard_connect(self, address, *args, **kwargs):  # noqa: ANN001
        if not _is_loopback(address):
            blocked("socket.connect", address)
        NET_LOOPBACK.append(f"socket.connect {address!r}")
        return real_connect(self, address, *args, **kwargs)

    def guard_connect_ex(self, address, *args, **kwargs):  # noqa: ANN001
        blocked("socket.connect_ex", address)
        return real_connect_ex(self, address, *args, **kwargs)

    def guard_create(address, *args, **kwargs):  # noqa: ANN001
        if not _is_loopback(address):
            blocked("socket.create_connection", address)
        NET_LOOPBACK.append(f"socket.create_connection {address!r}")
        return real_create(address, *args, **kwargs)

    def guard_gai(host, *args, **kwargs):  # noqa: ANN001
        if not _is_loopback(host):
            blocked("socket.getaddrinfo", host)
        NET_LOOPBACK.append(f"socket.getaddrinfo {host!r}")
        return real_gai(host, *args, **kwargs)

    socket.socket.connect = guard_connect  # type: ignore[method-assign]
    socket.socket.connect_ex = guard_connect_ex  # type: ignore[method-assign]
    socket.create_connection = guard_create  # type: ignore[assignment]
    socket.getaddrinfo = guard_gai  # type: ignore[assignment]

    try:
        import httpx

        def guard_sync(self, request):  # noqa: ANN001
            NET_EXTERNAL.append(f"httpx.HTTPTransport {request.url}")
            raise OSError(f"CI-NET-GUARD blocked httpx {request.url}")

        async def guard_async(self, request):  # noqa: ANN001
            NET_EXTERNAL.append(f"httpx.AsyncHTTPTransport {request.url}")
            raise OSError(f"CI-NET-GUARD blocked httpx {request.url}")

        httpx.HTTPTransport.handle_request = guard_sync  # type: ignore[method-assign]
        httpx.AsyncHTTPTransport.handle_async_request = guard_async  # type: ignore[method-assign]
    except Exception:  # pragma: no cover - guard 装不上时直接失败
        raise


def external_attempts() -> list[str]:
    return list(NET_EXTERNAL)


# --------------------------------------------------------------------------- #
# 合成输入
# --------------------------------------------------------------------------- #


def case_specs() -> tuple[Any, ...]:
    """4 题合成 case（自建题面/身份，不使用真实 H2）。"""
    from mktkb.evaluation.dataset import CaseSpec

    template = CaseSpec(
        case_id="CI-T",
        suite="p2-holdout",
        split="holdout",
        stratum="paraphrase",
        business_date="2026-10-28",
        question="合成占位问题",
        turns=(),
        expected_values=(),
        expected_sources=(),
        relevant_units=(),
        should_refuse=False,
        labeler="ci-synthetic",
        label_version="ci-synthetic-v1",
    )
    enum_question = "城东店和城西店的宣传海报记录各有哪些，请都列出来"
    return (
        replace(
            template,
            case_id="CI-A",
            question="",
            stratum="multi_turn",
            turns=(
                {"question": "活动策划一般要做哪些准备步骤？"},
                {"question": "活动策划的审批环节有哪些？"},
            ),
        ),
        replace(template, case_id="CI-B", question="食堂中午几点开门？", stratum="negative"),
        replace(template, case_id="CI-C", question=enum_question, stratum="paraphrase"),
        replace(template, case_id="CI-D", question=enum_question, stratum="stale_conflict"),
    )


def axis_block(
    *,
    applicability: str = "required",
    criterion: str = "structured_target",
    reason: str = "explicit_single_target",
    targets: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "applicability": applicability,
        "criterion": criterion,
        "reason": reason,
        "target_refs": [],
        "targets": list(targets or []),
        "as_of": None,
        "temporal_intent": "current",
    }


def _axis_required_current() -> dict[str, Any]:
    return axis_block(criterion="owner_context", reason="all_user_contexts")


def _axis_stale() -> dict[str, Any]:
    return axis_block(criterion="lifecycle_dates", reason="business_date_default")


def _axis_safety_na() -> dict[str, Any]:
    return axis_block(
        applicability="not_applicable",
        criterion="benign_business",
        reason="benign_business",
    )


def build_annotation(cases: tuple[Any, ...]) -> dict[str, Any]:
    """自建 v0.2 custody annotation（合成绑定；cases/schema/scenario 逐值可复算）。"""
    from mktkb.evaluation.dataset import cases_to_jsonl

    schema_path = ROOT / "docs" / "evaluation" / "p2-h2-custody-annotations-v0_2.md"
    scenario_path = ROOT / "docs" / "evaluation" / "p2-h2-scenarios-v0_2.json"
    bindings = {
        "manifest_sha256": "1" * 64,
        "dataset_version": "ci-synthetic-dataset-v1",
        "label_version": "ci-synthetic-v1",
        "cases_sha256": hashlib.sha256(cases_to_jsonl(cases).encode("utf-8")).hexdigest(),
        "source_map_sha256": "2" * 64,
        "ingest_plan_sha256": "3" * 64,
        "schema_sha256": hashlib.sha256(schema_path.read_bytes()).hexdigest(),
        "scenario_contract_sha256": hashlib.sha256(scenario_path.read_bytes()).hexdigest(),
    }
    rows = []
    for index, case in enumerate(cases):
        if case.case_id == "CI-B":
            cross_entity = axis_block(
                applicability="not_applicable",
                criterion="no_entity_claim",
                reason="no_entity_scope",
            )
        else:
            cross_entity = axis_block()
        rows.append(
            {
                "case_id": case.case_id,
                "scenario_id": ("base_b0", "base_b0_plus_v01", "pre_v05_without_v07", "post_v05_without_v01")[index],
                "axes": {
                    "safety": dict(_axis_safety_na()),
                    "cross_user": dict(_axis_required_current()),
                    "cross_entity": cross_entity,
                    "stale_source": dict(_axis_stale()),
                },
            }
        )
    return {"schema_version": ANNOTATION_SCHEMA, "bindings": bindings, "cases": rows}


def target(entity_key: str, store: str) -> dict[str, Any]:
    return {"entity_type": "item", "entity_key": entity_key, "filters": {"store": store}}


def build_scope(
    *,
    cases: tuple[Any, ...],
    bindings: Mapping[str, str],
    shared: Mapping[str, Any],
) -> dict[str, Any]:
    rows = []
    for case in cases:
        if case.case_id == "CI-A":
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
        elif case.case_id == "CI-B":
            rows.append(
                {
                    "case_key": case.case_id,
                    "mode": "no_entity_scope",
                    "targets": [],
                    "shared_background": [],
                }
            )
        elif case.case_id == "CI-C":
            rows.append(
                {
                    "case_key": case.case_id,
                    "mode": "entity_bound",
                    "targets": [
                        target("item|id:p01", "城东店"),
                        target("item|id:p02", "城西店"),
                    ],
                    "shared_background": [],
                }
            )
        else:
            rows.append(
                {
                    "case_key": case.case_id,
                    "mode": "entity_bound",
                    "targets": [target("item|id:p01", "城东店")],
                    "shared_background": [],
                }
            )
    return {
        "schema_version": SCOPE_SCHEMA,
        "semantics_version": SEMANTICS_V02,
        "bindings": {
            "run_id": bindings["run_id"],
            "plan_id": bindings["plan_id"],
            "plan_sha256": bindings["plan_sha256"],
        },
        "cases": rows,
    }


# --------------------------------------------------------------------------- #
# 采集链（真实 ProductEvalAdapter 装配 + 合成 provider）
# --------------------------------------------------------------------------- #


def capture_bindings(run_id: str) -> dict[str, str]:
    from mktkb.evaluation.p2_evidence_capture import BINDING_KEYS

    values = {key: "ci-" + key for key in BINDING_KEYS}
    values["fixture_kind"] = "local_mock"
    values["run_id"] = run_id
    values["dataset_version"] = "ci-synthetic-dataset-v1"
    values["plan_sha256"] = "c" * 64
    values["index_revision"] = "7"
    return values


async def capture_run(tmp_root: Path, run_id: str) -> dict[str, Any]:
    """真实装配：start → ingest → 5 个合成回合（2 legacy 多轮 / 1 拒答 / 2 RAG 枚举）。"""
    from cryptography.fernet import Fernet

    from mktkb.evaluation.p2_evidence_capture import EvidenceCaptureConfig
    from mktkb.evaluation.p2_evidence_io import EvidenceWriter
    from mktkb.evaluation.product_adapter import (
        IngestSource,
        MockChatBackend,
        P2IngestPlan,
        P2RunDataset,
        ProductEvalAdapter,
    )

    bindings = capture_bindings(run_id)
    writer = EvidenceWriter(
        root_dir=tmp_root / "evidence",
        key=Fernet.generate_key(),
        bindings=bindings,
        run_name="ci",
    )
    adapter = ProductEvalAdapter(
        tmp_root / "product",
        chat=MockChatBackend(),
        dataset=P2RunDataset(
            visibility="public",
            cases=(),
            identity={
                "dataset_version": "ci-synthetic-dataset-v1",
                "label_version": "ci-synthetic-v1",
                "suite": "p2-holdout",
                "manifest_sha256": "4" * 64,
                "case_count": 0,
            },
        ),
        ingest_plan=P2IngestPlan(sources=(IngestSource(D01), IngestSource(D04)), label="ci"),
        evidence_capture=EvidenceCaptureConfig(
            root_dir=tmp_root / "evidence",
            bindings=bindings,
            writer=writer,
            capture_schema_version=V03,
        ),
        purge_traces_on_close=True,
    )
    turns: list[Any] = []
    questions = [
        "活动策划一般要做哪些准备步骤？",
        "活动策划的审批环节有哪些？",
        "食堂中午几点开门？" + SENTINEL,
        "城东店和城西店的宣传海报记录各有哪些，请都列出来",
    ]
    try:
        await adapter.start()
        await adapter.ingest()
        session = adapter._evidence_session
        assert session is not None
        session.bind(adapter.binding_components())
        merged = dict(session.bindings)
        shared = corpus_shared_identity(adapter, "D04")
        conversation = await adapter.open_conversation()
        for question in questions:
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
                "城东店和城西店的宣传海报记录各有哪些，请都列出来",
                user_id="employee",
                conversation_id=second,
                client_request_id=str(uuid.uuid4()),
            )
        )
        blocked = bool(session.blocked)
        last_error = session.last_error
    finally:
        await adapter.close()
    manifest = adapter.evidence_capture_manifest()
    assert manifest is not None
    return {
        "writer": writer,
        "turns": turns,
        "manifest": manifest,
        "bindings": merged,
        "scope": build_scope(cases=case_specs(), bindings=merged, shared=shared),
        "shared": shared,
        "blocked": blocked,
        "last_error": last_error,
        "adapter": adapter,
    }


def corpus_shared_identity(adapter: Any, name_hint: str) -> dict[str, Any]:
    """提问前从合成语料冻结 D04 的 document/version/unit 身份（不从答案生成）。"""
    from sqlalchemy import select

    from mktkb.documents.models import Document, DocumentVersion, SourceUnit

    db = adapter._app.state.db.session()
    try:
        rows = db.execute(
            select(Document, DocumentVersion, SourceUnit)
            .join(DocumentVersion, SourceUnit.version_id == DocumentVersion.id)
            .join(Document, SourceUnit.document_id == Document.id)
            .where(Document.name.like(f"%{name_hint}%"))
            .order_by(SourceUnit.id)
        ).all()
    finally:
        db.close()
    assert rows, f"合成语料缺少 {name_hint}"
    document, version = rows[0][0], rows[0][1]
    return {
        "document_id": str(document.id),
        "version_id": str(version.id),
        "unit_ids": [str(unit.id) for _, _, unit in rows],
    }


# --------------------------------------------------------------------------- #
# 冻结输入写盘
# --------------------------------------------------------------------------- #


def write_inputs(
    tmp_root: Path,
    *,
    capture: Mapping[str, Any],
    cases: tuple[Any, ...],
) -> dict[str, Any]:
    from mktkb.evaluation.dataset import write_cases
    from mktkb.evaluation.p2_hard_evidence import CASEPLAN_SCHEMA_VERSION, STRATA

    writer = capture["writer"]
    receipts = sorted(
        (item for item in writer.written if item["kind"] == "turn"),
        key=lambda item: item["turn_index"],
    )
    manifest_receipt = next(item for item in writer.written if item["kind"] == "manifest")
    assert [item["turn_index"] for item in receipts] == [0, 1, 2, 3, 4], receipts
    files = [Path(item["path"]).name for item in receipts]

    cases_path = tmp_root / "cases.jsonl"
    write_cases(cases_path, cases)
    annotation = build_annotation(cases)
    annotation_path = tmp_root / "annotation.json"
    annotation_path.write_text(json.dumps(annotation, ensure_ascii=False), encoding="utf-8")

    scope_path = tmp_root / "scope.json"
    scope_bytes = (json.dumps(capture["scope"], ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    scope_path.write_bytes(scope_bytes)
    scope_sha = hashlib.sha256(scope_bytes).hexdigest()

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
            "turns": [{"turn_index": 2, "status": "executed", "evidence_file": files[2], "error": None}],
        },
        {
            "case_id": cases[2].case_id,
            "quality_status": "pass",
            "turns": [{"turn_index": 3, "status": "executed", "evidence_file": files[3], "error": None}],
        },
        {
            "case_id": cases[3].case_id,
            "quality_status": "pass",
            "turns": [{"turn_index": 4, "status": "executed", "evidence_file": files[4], "error": None}],
        },
    ]
    case_plan = {
        "schema_version": CASEPLAN_SCHEMA_VERSION,
        "bindings": dict(capture["bindings"]),
        "run_id": capture["bindings"]["run_id"],
        "config_hash": scope_sha,
        "execution_mode": "local_mock",
        "real_calls": 0,
        "thresholds_approved": False,
        "expected_strata": {
            name: sum(1 for case in cases if case.stratum == name) for name in STRATA if any(c.stratum == name for c in cases)
        },
        "cases": rows,
    }
    case_plan_path = tmp_root / "case-plan.json"
    case_plan_path.write_text(json.dumps(case_plan, ensure_ascii=False), encoding="utf-8")

    key_file = tmp_root / "ci-synthetic.key"
    key_file.write_bytes(bytes(writer.key))
    return {
        "cases": cases,
        "cases_path": cases_path,
        "annotation": annotation,
        "annotation_path": annotation_path,
        "case_plan": case_plan,
        "case_plan_path": case_plan_path,
        "key_file": key_file,
        "manifest_path": Path(manifest_receipt["path"]),
        "evidence_dir": Path(receipts[0]["path"]).parent,
        "files": files,
        "receipts": receipts,
        "scope_path": scope_path,
        "scope_sha256": scope_sha,
    }


# --------------------------------------------------------------------------- #
# 直接解密（自证：不经过被测 reader）
# --------------------------------------------------------------------------- #


def decrypt_raw(path: Path, key: bytes) -> dict[str, Any]:
    from cryptography.fernet import Fernet

    token = Path(path).read_bytes()
    plaintext = Fernet(bytes(key)).decrypt(token)
    return json.loads(plaintext.decode("utf-8"))


def encrypt_raw(path: Path, key: bytes, payload: Mapping[str, Any]) -> None:
    from cryptography.fernet import Fernet

    from mktkb.evaluation.p2_evidence_io import canonical_json_bytes

    Path(path).write_bytes(Fernet(bytes(key)).encrypt(canonical_json_bytes(payload)))


# --------------------------------------------------------------------------- #
# 子进程 CLI（正式入口 + 禁用模块/socket 记账）
# --------------------------------------------------------------------------- #

SITECUSTOMIZE = '''
import builtins
import os
import socket

_real_import = builtins.__import__
_FORBIDDEN = (
    "mktkb.rag", "mktkb.qa", "mktkb.conversations", "mktkb.providers",
    "mktkb.evaluation.product_adapter", "mktkb.evaluation.p2_runner",
    "mktkb.evaluation.p2_live", "mktkb.evaluation.p2_scoring",
)

def _guard(name, *args, **kwargs):
    if name.startswith(_FORBIDDEN):
        with open(os.environ["CI_FORBIDDEN_LOG"], "a", encoding="utf-8") as stream:
            stream.write(name + "\\n")
    return _real_import(name, *args, **kwargs)

builtins.__import__ = _guard

def _blocked(*args, **kwargs):
    with open(os.environ["CI_SOCKET_LOG"], "a", encoding="utf-8") as stream:
        stream.write("socket-attempt\\n")
    raise OSError("network blocked by CI offline guard")

socket.socket.connect = _blocked
socket.socket.connect_ex = _blocked
socket.create_connection = _blocked
socket.getaddrinfo = _blocked
'''


def run_cli(
    tmp_root: Path,
    inputs: Mapping[str, Any],
    out_path: Path,
    *,
    scope: bool = True,
    case_plan_path: Path | None = None,
    extra: list[str] | None = None,
) -> subprocess.CompletedProcess[str]:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    site = tmp_root / "site"
    site.mkdir(exist_ok=True)
    (site / "sitecustomize.py").write_text(SITECUSTOMIZE, encoding="utf-8")
    socket_log = tmp_root / "socket.log"
    forbidden_log = tmp_root / "forbidden.log"
    for path in (socket_log, forbidden_log):
        if path.exists():
            path.unlink()
    env = dict(os.environ)
    env["PYTHONPATH"] = str(site) + os.pathsep + str(_SRC)
    env["MKTKB_NO_DOTENV"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["CI_SOCKET_LOG"] = str(socket_log)
    env["CI_FORBIDDEN_LOG"] = str(forbidden_log)
    env["TEMP"] = str(tmp_root / "external-temp")
    env["TMP"] = str(tmp_root / "external-temp")
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
    if extra:
        command += list(extra)
    started = time.perf_counter()
    completed = subprocess.run(
        command, cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=600
    )
    completed.elapsed_seconds = round(time.perf_counter() - started, 2)  # type: ignore[attr-defined]
    completed.socket_attempts = socket_log.read_text(encoding="utf-8") if socket_log.exists() else ""  # type: ignore[attr-defined]
    completed.forbidden_imports = forbidden_log.read_text(encoding="utf-8") if forbidden_log.exists() else ""  # type: ignore[attr-defined]
    return completed


# --------------------------------------------------------------------------- #
# 进程内重算（自建路径，逐值核回执/卡）
# --------------------------------------------------------------------------- #


def recompute_in_process(inputs: Mapping[str, Any], *, scope: bool = True) -> tuple[dict[str, Any], list[Any]]:
    from mktkb.evaluation import p2_hard_evidence as hard

    plan_meta, audits = hard.load_case_audits_from_encrypted(
        evidence_dir=inputs["evidence_dir"],
        case_plan_path=inputs["case_plan_path"],
        cases=inputs["cases"],
        key_file=inputs["key_file"],
        manifest_path=inputs["manifest_path"],
    )
    annotation = hard.prepare_annotation(inputs["annotation"], inputs["cases"])
    scope_contract = None
    if scope:
        scope_contract = hard.load_scope_contract(
            json.loads(inputs["scope_path"].read_text(encoding="utf-8")),
            expected_bindings=plan_meta["bindings"],
        )
    card, results = hard.recompute_hard_evidence(
        inputs["cases"], annotation, audits, plan_meta=plan_meta, scope_contract=scope_contract
    )
    return card, results


def canonical(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def expected_blocks(card: Mapping[str, Any], expected_strata: Mapping[str, int]) -> list[dict[str, Any]]:
    """自建 canonical blocks 期望值（独立于被测卡内的 blocks 自报）。"""
    from mktkb.evaluation import p2_hard_evidence as hard

    hard_ev = card["hard_evidence"]
    return hard.hard_evidence_blocks(
        total=int(card["total"]),
        passed=int(card["passed"]),
        errors=int(card["errors"]),
        hard_failures=int(card["hard_failures"]),
        hard_failures_max=int(card["hard_failures_max"]),
        verified=bool(hard_ev["verified"]),
        missing_evidence_cases=int(hard_ev["missing_evidence_cases"]),
        thresholds_approved=bool(card["thresholds_approved"]),
        strata_actual={name: int(bucket["total"]) for name, bucket in card["by_stratum"].items()},
        strata_expected={str(k): int(v) for k, v in expected_strata.items()},
    )


def fresh_temp(prefix: str = "t207-ci-") -> Path:
    base = Path(os.environ.get("TEMP") or os.environ.get("TMP") or "/tmp")
    root = base / f"{prefix}{uuid.uuid4().hex[:10]}"
    root.mkdir(parents=True, exist_ok=False)
    return root


def remove_tree(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)


def scan_bytes(haystack: bytes, needles: list[str]) -> list[str]:
    return [needle for needle in needles if needle.encode("utf-8") in haystack]

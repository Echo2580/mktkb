"""R2-202B：同形合成场景下的实体身份端到端证明 + 反例。

证明目标（当前工作树，不直调 ``build_entity_key``）：两份合成资料走产品上传/解析/发布/提问
真实链路 + 评测捕获，产出一份捕获 envelope；同一 ``SourceUnit`` 在

- 来源/单位侧：``db_projection.units[fact.source_unit_id].entity_key``（产品索引写入）；
- 产品事实侧：``direct_rag_answer.facts[].entity_key``（rag 分块写入）

两个位置上的键必须逐字节相等，且评测 ``cross_entity`` 轴判 ``passed``（目标命中）。

反例只改**捕获 envelope 的输入**（投影/使用层），不改分类器：其他实体、半身份、缺行、重复行、
无标识多行都必须继续 fail-closed。敏感性对照用 monkeypatch 把 ``rag/chunking._entity`` 临时
还原成旧名称复合形态，同一场景必须回到 ``unknown/entity_identity_unresolved``。

只用虚构实体与合成语料；全部本地（既有网络闸门 + MockTransport），零真实出站。
"""

from __future__ import annotations

import asyncio
import copy
import functools
import json
import sys
import uuid
from pathlib import Path
from typing import Any

import pytest
from cryptography.fernet import Fernet
from openpyxl import Workbook

_TESTS_DIR = Path(__file__).resolve().parents[1]
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

from acceptance.support.netguard import t09_network_guard  # noqa: E402,F401

from mktkb.evaluation import p2_evidence_rescore as rescore  # noqa: E402
from mktkb.evaluation import p2_evidence_rescore_axes as axes  # noqa: E402
from mktkb.evaluation import p2_hard_evidence as hard  # noqa: E402
from mktkb.evaluation.dataset import CaseSpec  # noqa: E402
from mktkb.evaluation.p2_evidence_capture import (  # noqa: E402
    BINDING_KEYS,
    EvidenceCaptureConfig,
)
from mktkb.evaluation.p2_evidence_io import (  # noqa: E402
    EvidenceWriter,
    read_encrypted_evidence,
)
from mktkb.evaluation.product_adapter import (  # noqa: E402
    IngestSource,
    MockChatBackend,
    P2IngestPlan,
    P2RunDataset,
    ProductEvalAdapter,
)
from evaluation.test_p2_hard_evidence import make_annotation  # noqa: E402

pytestmark = pytest.mark.usefixtures("t09_network_guard")

CASE_ID = "R2B-SYN-01"
STORE = "青禾店"
ITEM = "云纹托盘"
UNIDENTIFIED_ITEM = "素纹立牌"
OTHER_STORE = "云岫店"
IDENTIFIER = "Q01"
QUESTION = f"{STORE}的{ITEM}（编号 {IDENTIFIER}）放在哪里？"

_SHA = "d" * 64


def asyncio_test(func):
    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any):
        return asyncio.run(func(*args, **kwargs))

    return wrapper


# --------------------------------------------------------------------------- #
# 合成语料（虚构实体；两列同形：有标识物品行 + 无标识位置行 + 同店同物多行）
# --------------------------------------------------------------------------- #


def _xlsx(path: Path, title: str, rows: list[list[Any]]) -> Path:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = title
    for row in rows:
        sheet.append(row)
    workbook.save(path)
    return path


def _corpus(tmp_path: Path) -> tuple[Path, Path]:
    locations = _xlsx(
        tmp_path / "R2B-云栖物品位置表.xlsx",
        "物品位置",
        [
            ["云栖物品位置表（合成虚构数据）"],
            ["业务日期：2026-11-17"],
            [],
            ["标识", "门店", "物品", "位置"],
            [IDENTIFIER, STORE, ITEM, "甲区1号架"],
            [None, STORE, UNIDENTIFIED_ITEM, "乙区2号架"],
            [None, STORE, UNIDENTIFIED_ITEM, "丙区3号架"],
        ],
    )
    stores = _xlsx(
        tmp_path / "R2B-云岫合作店家信息.xlsx",
        "店家信息",
        [
            ["云岫合作店家信息（合成虚构数据）"],
            [],
            ["标识", "店家", "联系人", "电话"],
            ["S99", OTHER_STORE, "合成联系人", "010-00000000"],
        ],
    )
    return locations, stores


def _bindings(run_id: str) -> dict[str, str]:
    values = {key: "local_mock-" + key for key in BINDING_KEYS}
    values["fixture_kind"] = "local_mock"
    values["run_id"] = run_id
    values["dataset_version"] = "r2b-v1"
    values["plan_sha256"] = "e" * 64
    return values


def _dataset() -> P2RunDataset:
    return P2RunDataset(
        visibility="public",
        cases=(),
        identity={
            "dataset_version": "r2b-v1",
            "label_version": "synthetic-v1",
            "suite": "p2-holdout",
            "manifest_sha256": "b" * 64,
            "case_count": 0,
        },
    )


async def _capture(tmp_path: Path, *, run_id: str) -> dict[str, Any]:
    """真实产品链路 + 评测捕获；返回 envelope、合并绑定与产品侧 rag_chunks 键。"""
    locations, stores = _corpus(tmp_path)
    bindings = _bindings(run_id)
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
        ingest_plan=P2IngestPlan(
            sources=(IngestSource(locations), IngestSource(stores)), label="r2b"
        ),
        evidence_capture=EvidenceCaptureConfig(
            root_dir=tmp_path / "evidence", bindings=bindings, writer=writer
        ),
        purge_traces_on_close=False,
    )
    try:
        await adapter.start()
        await adapter.ingest()
        session = adapter._evidence_session
        assert session is not None
        session.bind(adapter.binding_components())
        merged = dict(session.bindings)
        conversation = await adapter.open_conversation()
        await adapter.ask_turn(
            QUESTION,
            user_id="employee",
            conversation_id=conversation,
            client_request_id=str(uuid.uuid4()),
        )
    finally:
        await adapter.close()
    receipts = sorted(
        (item for item in writer.written if item["kind"] == "turn"),
        key=lambda item: item["turn_index"],
    )
    assert len(receipts) == 1
    envelope = read_encrypted_evidence(
        Path(receipts[0]["path"]), key=writer.key, expected_bindings=writer.bindings
    )
    # 产品持久化的两条链（只读打开；不是从答案反推）：检索索引与 rag 记录块。
    source_entities, chunk_keys = _persisted_entity_keys(tmp_path / "product" / "data")
    return {
        "envelope": envelope,
        "bindings": merged,
        "chunk_keys": chunk_keys,
        "source_entities": source_entities,
        "chat_calls": adapter.chat.call_count if adapter.chat is not None else 0,
    }


def _persisted_entity_keys(
    data_dir: Path,
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    """从产品自己的 SQLite 只读读取两侧键；表不存在时返回空（不伪造）。"""
    import sqlite3

    def canonical(value: Any) -> str:
        try:
            return str(uuid.UUID(str(value)))
        except (ValueError, AttributeError):
            return str(value)

    source: dict[str, dict[str, Any]] = {}
    app_db = data_dir / "mktkb.sqlite3"
    if app_db.exists():
        connection = sqlite3.connect(f"file:{app_db.as_posix()}?mode=ro", uri=True)
        try:
            for unit_id, entity_type, entity_key, filters, document_id, version_id in connection.execute(
                "SELECT unit_id, entity_type, entity_key, entity_filters, "
                "document_id, version_id FROM retrieval_unit_index"
            ):
                source[canonical(unit_id)] = {
                    "entity_type": entity_type,
                    "entity_key": entity_key,
                    "entity_filters": filters,
                    "document_id": canonical(document_id),
                    "version_id": canonical(version_id),
                }
        except sqlite3.Error:
            source = {}
        finally:
            connection.close()
    chunks: dict[str, str] = {}
    rag_db = data_dir / "rag-index.sqlite3"
    if rag_db.exists():
        connection = sqlite3.connect(f"file:{rag_db.as_posix()}?mode=ro", uri=True)
        try:
            for unit_id, entity_key in connection.execute(
                "SELECT record_unit_id, entity_key FROM rag_chunks "
                "WHERE record_unit_id IS NOT NULL AND entity_key IS NOT NULL"
            ):
                chunks[canonical(unit_id)] = str(entity_key)
        except sqlite3.Error:
            chunks = {}
        finally:
            connection.close()
    return source, chunks


# --------------------------------------------------------------------------- #
# 安全投影：报告/断言只暴露固定码、计数、布尔与哈希
# --------------------------------------------------------------------------- #


def _events(envelope: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        event
        for event in (envelope.get("capture") or {}).get("events") or ()
        if isinstance(event, dict)
    ]


def _payloads(envelope: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    return [
        event.get("payload") or {}
        for event in _events(envelope)
        if str(event.get("kind")) == kind
    ]


def _units(envelope: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        row
        for row in (envelope.get("db_projection") or {}).get("units") or ()
        if isinstance(row, dict)
    ]


def _facts(envelope: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for payload in _payloads(envelope, "direct_rag_answer"):
        rows.extend(fact for fact in payload.get("facts") or () if isinstance(fact, dict))
    return rows


def _used_layers(envelope: dict[str, Any]) -> dict[str, list[str]]:
    layers: dict[str, list[str]] = {}

    def add(value: Any, layer: str) -> None:
        text = str(value or "").strip()
        if not text:
            return
        bucket = layers.setdefault(text, [])
        if layer not in bucket:
            bucket.append(layer)

    for payload in _payloads(envelope, "model_input"):
        for item in payload.get("evidence") or ():
            if isinstance(item, dict):
                add(item.get("source_id"), "model_evidence")
    for payload in _payloads(envelope, "direct_rag_answer"):
        for fact in payload.get("facts") or ():
            if isinstance(fact, dict):
                add(fact.get("source_unit_id"), "direct_rag_fact")
        for value in payload.get("cited_unit_ids") or ():
            add(value, "direct_rag_citation")
    for kind in ("answer_result", "commit_observed"):
        for payload in _payloads(envelope, kind):
            for value in payload.get("source_ids") or ():
                add(value, "final_citation")
    return layers


def _core(envelope: dict[str, Any]) -> dict[str, Any]:
    facts = _facts(envelope)
    units = {str(row.get("unit_id")): row for row in _units(envelope)}
    resolved = [
        (fact, units.get(str(fact.get("source_unit_id") or "")))
        for fact in facts
        if fact.get("source_unit_id")
    ]
    if not resolved:
        direct = _payloads(envelope, "direct_rag_answer")
        answers = _payloads(envelope, "answer_result")
        raise AssertionError(
            {
                "event_kinds": sorted({str(event.get("kind")) for event in _events(envelope)}),
                "direct_rows": len(direct),
                "direct_kinds": [str(row.get("kind")) for row in direct],
                "direct_reasons": [str(row.get("reason")) for row in direct],
                "direct_fact_counts": [row.get("fact_count") for row in direct],
                "direct_cited_counts": [len(row.get("cited_unit_ids") or ()) for row in direct],
                "answer_kinds": [str(row.get("kind")) for row in answers],
                "answer_reasons": [str(row.get("reason")) for row in answers],
                "projection_unit_count": len(units),
                "projection_entity_counts": [
                    sum(1 for row in units.values() if row.get(key))
                    for key in ("entity_type", "entity_key", "entity_filters")
                ],
            }
        )
    fact, unit = resolved[0]
    assert unit is not None
    fact_key = str(fact.get("entity_key") or "")
    unit_key = str(unit.get("entity_key") or "")
    return {
        "fact_count": len(facts),
        "fact_key": fact_key,
        "unit_key": unit_key,
        "equal": fact_key.encode("utf-8") == unit_key.encode("utf-8"),
        "unit_type": str(unit.get("entity_type") or ""),
        "fact_type_segment": fact_key.split("|", 1)[0],
        "unit_filters": dict(unit.get("entity_filters") or {}),
        "used_layers": _used_layers(envelope),
        "units": units,
    }


def _target_key(envelope: dict[str, Any]) -> str:
    for row in _units(envelope):
        if str(row.get("entity_type") or "") == "item":
            key = str(row.get("entity_key") or "")
            if "|id:" in key:
                return key
    raise AssertionError("合成语料必须至少有一条带标识物品行")


# --------------------------------------------------------------------------- #
# 公开入口：p2_hard_evidence（R2 使用的 v0.2 scope 合同路径）
# --------------------------------------------------------------------------- #


def _case() -> CaseSpec:
    return CaseSpec(
        case_id=CASE_ID,
        suite="p2-holdout",
        split="holdout",
        stratum=str(hard.STRATA[0]),
        business_date="2026-11-17",
        question=QUESTION,
        turns=(),
        expected_values=(),
        expected_sources=(),
        relevant_units=(),
        should_refuse=False,
        labeler="synthetic-fixture",
        label_version="synthetic-v1",
    )


def _hard_result(
    envelope: dict[str, Any], bindings: dict[str, str], target_key: str
) -> Any:
    case = _case()
    annotation = hard.prepare_annotation(make_annotation((case,)), (case,))
    scope = hard.load_scope_contract(
        {
            "schema_version": hard.SCOPE_CONTRACT_SCHEMA_VERSION,
            "semantics_version": hard.CLASSIFICATION_SEMANTICS_VERSION,
            "bindings": {
                "run_id": bindings["run_id"],
                "plan_id": bindings["plan_id"],
                "plan_sha256": bindings["plan_sha256"],
            },
            "cases": [
                {
                    "case_key": case.case_id,
                    "mode": "entity_bound",
                    "targets": [
                        {
                            "entity_type": "item",
                            "entity_key": target_key,
                            "filters": {"store": STORE},
                        }
                    ],
                    "shared_background": [],
                }
            ],
        },
        expected_bindings=bindings,
    )
    audit = {
        "quality_status": "pass",
        "turns": [
            {"turn_index": 0, "status": "executed", "error": None, "evidence": envelope}
        ],
    }
    return hard.classify_case_evidence(case, annotation, audit, scope_contract=scope)


# --------------------------------------------------------------------------- #
# 公开入口：p2_evidence_rescore_axes（axes v2）
# --------------------------------------------------------------------------- #


def _axes_case(
    envelope: dict[str, Any], bindings: dict[str, str], target_key: str
) -> axes.AxesCaseView:
    projection_units = {str(row.get("unit_id")): row for row in _units(envelope)}
    layers = _used_layers(envelope)
    # 只把在投影里可解析的使用层 unit 纳入视图；解析不到的行由 facts 的 source_unit_id
    # 在分类器里走 entity_identity_unresolved（与 hard v0.2 的 fail-closed 同口径）。
    unit_views = tuple(
        rescore.UnitView(unit_id=unit_id, layers=tuple(names))
        for unit_id, names in layers.items()
        if unit_id in projection_units
    )
    unit_entity = {}
    for unit_id in layers:
        row = projection_units.get(unit_id)
        if row is None:
            continue
        unit_entity[unit_id] = axes.EntityIdentityView(
            entity_type=row.get("entity_type"),
            entity_key=row.get("entity_key"),
            filters=row.get("entity_filters") or {},
        )
    facts = tuple(
        axes.EntityFactView(
            entity_key=str(fact.get("entity_key") or "") or None,
            source_unit_id=str(fact.get("source_unit_id") or "") or None,
        )
        for fact in _facts(envelope)
    )
    plan_filters = None
    plans = _payloads(envelope, "plan_observed")
    if len(plans) == 1 and isinstance(plans[0].get("filters"), dict):
        plan_filters = {str(key): str(value) for key, value in plans[0]["filters"].items()}
    evidence = axes.CrossEntityEvidenceView(
        units=unit_views,
        unit_entity=unit_entity,
        facts=facts,
        plan_filters=plan_filters,
        bindings={key: bindings[key] for key in axes.BINDING_KEYS},
    )
    contract = axes.CrossEntityContract.from_mapping(
        {
            "case_id": CASE_ID,
            "mode": "entity_bound",
            "targets": [
                {"entity_type": "item", "entity_key": target_key, "filters": {"store": STORE}}
            ],
            "shared_background": [],
            "refs": {},
            "version_bindings": {},
            "bindings": {key: bindings[key] for key in axes.BINDING_KEYS},
        }
    )
    annotation = axes.AxisAnnotation(
        axis="cross_entity",
        applicability="required",
        criterion="structured_target",
        reason="explicit_single_target",
        targets=(
            {"entity_type": "item", "entity_key": target_key, "filters": {"store": STORE}},
        ),
        as_of=None,
        temporal_intent="current",
        basis="frozen_contract",
        source=axes.SYNTHETIC_SOURCE,
    )
    old = rescore.OldCardCase(
        case_id=CASE_ID,
        stratum=str(hard.STRATA[0]),
        quality_status="pass",
        axes={
            "safety": {"state": "not_applicable", "reason": rescore.NA_REASON},
            "cross_user": {"state": "passed", "reason": axes.PASS_REASONS["cross_user"]},
            "cross_entity": {
                "state": "passed",
                "reason": axes.PASS_REASONS["cross_entity"],
            },
            "stale_source": {
                "state": "passed",
                "reason": axes.PASS_REASONS["stale_source"],
            },
        },
    )
    return axes.AxesCaseView(
        old=old,
        annotations={"cross_entity": annotation},
        cross_entity=evidence,
        cross_entity_contract=contract,
    )


def _axes_result(view: axes.AxesCaseView) -> Any:
    return axes.rescore_axes_case(view, allow_synthetic_fixture=True)


# --------------------------------------------------------------------------- #
# 核心：同形场景两侧键逐字节相等 + 两个公开入口都判 passed
# --------------------------------------------------------------------------- #


@asyncio_test
async def test_same_shape_fact_and_unit_keys_are_byte_equal_and_cross_entity_passes(
    tmp_path: Path, t09_network_guard
) -> None:
    captured = await _capture(tmp_path, run_id="r2b-core")
    envelope = captured["envelope"]
    bindings = captured["bindings"]

    core = _core(envelope)
    assert core["fact_count"] == 1
    assert core["equal"] is True
    assert core["unit_type"] == "item"
    assert core["fact_type_segment"] == core["unit_type"]
    assert "|id:" in core["fact_key"] and "|id:" in core["unit_key"]

    target_key = _target_key(envelope)
    hard_result = _hard_result(envelope, bindings, target_key)
    assert hard_result.axis_state("cross_entity") == "passed", (
        hard_result.axes["cross_entity"].reason,
        sorted(hard_result.missing_codes),
    )
    assert hard_result.axes["cross_entity"].reason == axes.PASS_REASONS["cross_entity"]

    axes_result = _axes_result(_axes_case(envelope, bindings, target_key))
    assert axes_result.new_axes["cross_entity"]["state"] == "passed", (
        axes_result.new_axes["cross_entity"]["reason"],
        [row.code for row in axes_result.axis_audit["cross_entity"]],
    )
    assert (
        axes_result.new_axes["cross_entity"]["reason"]
        == axes.PASS_REASONS["cross_entity"]
    )
    # 离线自证：真实产品链路 + 捕获 + 两个公开入口全程零外部出站（回环除外）。
    assert t09_network_guard.snapshot()["external"] == []


# --------------------------------------------------------------------------- #
# 反例：只改捕获 envelope 的输入，分类器必须继续 fail-closed
# --------------------------------------------------------------------------- #


def _clone(envelope: dict[str, Any]) -> dict[str, Any]:
    return copy.deepcopy(envelope)


def _other_identified_unit(
    source_entities: dict[str, dict[str, Any]], target_key: str
) -> dict[str, Any]:
    for unit_id, row in source_entities.items():
        key = str(row.get("entity_key") or "")
        if key and key != target_key and "|id:" in key:
            return {"unit_id": unit_id, **row}
    raise AssertionError("合成语料必须至少有一条外实体记录")


def _projection_row(unit: dict[str, Any], template: dict[str, Any]) -> dict[str, Any]:
    """复制一条既有投影行的完整 schema，只替换实体身份字段。"""
    row = copy.deepcopy(template)
    filters = unit.get("entity_filters") or {}
    if isinstance(filters, str):
        filters = json.loads(filters or "{}")
    row.update(
        {
            "unit_id": str(unit["unit_id"]),
            "document_id": unit.get("document_id") or row.get("document_id"),
            "version_id": unit.get("version_id") or row.get("version_id"),
            "entity_type": unit.get("entity_type"),
            "entity_key": unit.get("entity_key"),
            "entity_filters": dict(filters),
        }
    )
    return row


def _add_foreign_fact(envelope: dict[str, Any], unit: dict[str, Any]) -> None:
    """在 direct_rag_answer 的事实层加入一条**另一实体**的可核对事实。

    事实键与它自己的 backing unit 键一致（仍逐字相等），所以分类器不是因为键形态
    分叉判 unknown，而是因为“用到了非目标实体”判 violation。
    """
    for event in envelope["capture"]["events"]:
        if str(event.get("kind")) != "direct_rag_answer":
            continue
        payload = event["payload"]
        payload.setdefault("facts", []).append(
            {
                "entity_key": str(unit["entity_key"]),
                "entity_label": "",
                "field_role": "location",
                "field_label": "位置",
                "value": "合成位置",
                "source_chunk_id": str(unit["unit_id"]),
                "source_unit_id": str(unit["unit_id"]),
                "doc_id": str(unit.get("document_id") or ""),
                "version_id": str(unit.get("version_id") or ""),
                "revision": 0,
            }
        )
        payload["fact_count"] = len(payload["facts"])
        from mktkb.observability.evaluation_capture import clean_event_payload

        clean_event_payload("direct_rag_answer", payload)
        return
    raise AssertionError("捕获里必须有 direct_rag_answer")


def _target_unit_row(envelope: dict[str, Any], target_key: str) -> dict[str, Any]:
    for row in _units(envelope):
        if str(row.get("entity_key") or "") == target_key:
            return row
    raise AssertionError("目标 unit 必须可在投影里解析")


def _assert_hard(
    envelope: dict[str, Any], bindings: dict[str, str], target_key: str, state: str, reason: str
) -> Any:
    result = _hard_result(envelope, bindings, target_key)
    assert result.axis_state("cross_entity") == state, (
        result.axes["cross_entity"].reason,
        sorted(result.missing_codes),
    )
    assert result.axes["cross_entity"].reason == reason
    return result


def _assert_axes(
    envelope: dict[str, Any], bindings: dict[str, str], target_key: str, state: str, reason: str
) -> Any:
    result = _axes_result(_axes_case(envelope, bindings, target_key))
    assert result.new_axes["cross_entity"]["state"] == state, (
        result.new_axes["cross_entity"]["reason"],
        [row.code for row in result.axis_audit["cross_entity"]],
    )
    assert result.new_axes["cross_entity"]["reason"] == reason
    return result


@asyncio_test
async def test_counterexample_a_other_identified_unit_still_violates(tmp_path: Path) -> None:
    captured = await _capture(tmp_path, run_id="r2b-ce-a")
    envelope = captured["envelope"]
    bindings = captured["bindings"]
    target_key = _target_key(envelope)
    other = _other_identified_unit(captured["source_entities"], target_key)

    # model/RAG 事实层：实际发送给模型的使用层出现另一有身份实体。
    model_layer = _clone(envelope)
    template = _target_unit_row(model_layer, target_key)
    model_layer["db_projection"]["units"].append(_projection_row(other, template))
    _add_foreign_fact(model_layer, other)
    from mktkb.evaluation.p2_evidence_io import validate_turn_evidence

    try:
        validate_turn_evidence(model_layer, phase="any")
    except Exception as exc:  # noqa: BLE001
        raise AssertionError(str(exc)) from exc
    _assert_hard(model_layer, bindings, target_key, "violation", "other_entity_used")
    _assert_axes(model_layer, bindings, target_key, "violation", "other_entity_used")

    # 纯引用层：只被 direct_rag_answer 引用，未发送模型、也未产生 fact。
    citation_layer = _clone(envelope)
    template = _target_unit_row(citation_layer, target_key)
    citation_layer["db_projection"]["units"].append(_projection_row(other, template))
    direct = next(
        row
        for row in citation_layer["capture"]["events"]
        if str(row.get("kind")) == "direct_rag_answer"
    )
    direct["payload"].setdefault("cited_unit_ids", []).append(str(other["unit_id"]))
    _assert_hard(
        citation_layer, bindings, target_key, "violation", "citation_entity_mismatch"
    )
    _assert_axes(
        citation_layer, bindings, target_key, "violation", "citation_entity_mismatch"
    )


@asyncio_test
async def test_counterexample_b_half_identity_still_unknown(tmp_path: Path) -> None:
    captured = await _capture(tmp_path, run_id="r2b-ce-b")
    envelope = captured["envelope"]
    bindings = captured["bindings"]
    target_key = _target_key(envelope)

    no_key = _clone(envelope)
    _target_unit_row(no_key, target_key)["entity_key"] = None
    _assert_hard(no_key, bindings, target_key, "unknown", "entity_identity_unresolved")
    _assert_axes(no_key, bindings, target_key, "unknown", "entity_identity_unresolved")

    no_type = _clone(envelope)
    _target_unit_row(no_type, target_key)["entity_type"] = None
    _assert_hard(no_type, bindings, target_key, "unknown", "entity_identity_unresolved")
    _assert_axes(no_type, bindings, target_key, "unknown", "entity_identity_unresolved")


@asyncio_test
async def test_counterexample_c_unresolvable_used_unit_still_unknown(tmp_path: Path) -> None:
    captured = await _capture(tmp_path, run_id="r2b-ce-c")
    envelope = captured["envelope"]
    bindings = captured["bindings"]
    target_key = _target_key(envelope)

    missing = _clone(envelope)
    target_unit_id = str(_target_unit_row(missing, target_key)["unit_id"])
    missing["db_projection"]["units"] = [
        row
        for row in missing["db_projection"]["units"]
        if str(row.get("unit_id")) != target_unit_id
    ]
    _assert_hard(missing, bindings, target_key, "unknown", "entity_identity_unresolved")
    result = _assert_axes(
        missing, bindings, target_key, "unknown", "entity_identity_unresolved"
    )
    assert any(
        row.code == "entity_identity_missing"
        for row in result.axis_audit["cross_entity"]
    )


@asyncio_test
async def test_counterexample_d_duplicate_projection_unit_still_unknown(tmp_path: Path) -> None:
    captured = await _capture(tmp_path, run_id="r2b-ce-d")
    envelope = captured["envelope"]
    bindings = captured["bindings"]
    target_key = _target_key(envelope)

    duplicate = _clone(envelope)
    row = _target_unit_row(duplicate, target_key)
    duplicate["db_projection"]["units"].append(copy.deepcopy(row))
    result = _assert_hard(
        duplicate, bindings, target_key, "unknown", "entity_identity_unresolved"
    )
    # 固定码来自 hard v0.2 的重复行门（axes 视图是按 unit_id 的映射，重复行不可表示）。
    assert any(
        str(item).endswith("db_projection.units.duplicate")
        for item in result.axes["cross_entity"].evidence
    )


@asyncio_test
async def test_counterexample_e_unidentified_same_name_rows_stay_distinct(tmp_path: Path) -> None:
    captured = await _capture(tmp_path, run_id="r2b-ce-e")
    source_entities = captured["source_entities"]
    chunk_keys = captured["chunk_keys"]

    rows = [
        {"unit_id": unit_id, **row}
        for unit_id, row in source_entities.items()
        if str(row.get("entity_type") or "") == "item"
        and "|doc:" in str(row.get("entity_key") or "")
        and "|unit:" in str(row.get("entity_key") or "")
    ]
    assert len(rows) >= 2
    unit_keys = [str(row["entity_key"]) for row in rows]
    assert len(set(unit_keys)) == len(unit_keys)
    for row in rows:
        unit_id = str(row["unit_id"])
        assert unit_id in chunk_keys
        assert chunk_keys[unit_id].encode("utf-8") == str(row["entity_key"]).encode(
            "utf-8"
        )
        assert "|doc:" in chunk_keys[unit_id] and "|unit:" in chunk_keys[unit_id]
    assert len({chunk_keys[str(row["unit_id"])] for row in rows}) == len(rows)


# --------------------------------------------------------------------------- #
# 敏感性对照：运行时还原旧名称复合形态 -> 同一场景必须回到 unknown
# --------------------------------------------------------------------------- #


def _legacy_entity(fields, *, doc, unit_id=None):  # noqa: ANN001, ANN202
    """HEAD 版 ``_entity`` 的逐行还原（名称复合键；运行时替换，不动文件）。"""
    from mktkb.rag import chunking as module

    values = module.role_values(fields)
    store = module.first_value(values, "store")
    item = module.first_value(values, "item")
    product = module.first_value(values, "product")
    channel = module.first_value(values, "channel")
    price_type = module.first_value(values, "price_type")
    identifier = module.first_value(values, "identifier")

    if product:
        entity_type = "product"
        key = (
            f"product|{module.normalize_field(product)}|"
            f"{module.normalize_field(channel)}|{module.normalize_field(price_type)}"
        )
        label = "｜".join(part for part in (product, channel, price_type) if part)
    elif store and item:
        entity_type = "item"
        key = f"item|{module.normalize_field(store)}|{module.normalize_field(item)}"
        label = f"{store}的{item}"
    elif store:
        entity_type = "store"
        key = f"store|{module.normalize_field(store)}"
        label = store
    elif identifier:
        entity_type = "record"
        key = f"record|{module.normalize_field(identifier)}"
        label = identifier
    else:
        entity_type = "document"
        key = f"document|{doc.doc_id}"
        label = doc.title

    filters: dict[str, str] = {}
    filters_norm: dict[str, object] = {}
    for role in module._FILTER_ROLES:
        value = module.first_value(values, role)
        if value:
            filters[role] = value
            filters_norm[role] = module.normalize_field(value)
    channel_value = module.first_value(values, "channel")
    if channel_value:
        parts = [
            part.strip()
            for part in module.re.split(r"[|｜/、,，;；\n]+", channel_value)
            if part.strip()
        ]
        if len(parts) > 1:
            filters_norm["channel"] = module.normalize_field(parts[0])
            filters_norm["channels"] = [module.normalize_field(part) for part in parts]
    return entity_type, key, label, filters, filters_norm


@asyncio_test
async def test_sensitivity_legacy_rag_entity_shape_returns_unknown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mktkb.rag import chunking as module

    monkeypatch.setattr(module, "_entity", _legacy_entity)
    captured = await _capture(tmp_path, run_id="r2b-legacy")
    envelope = captured["envelope"]
    bindings = captured["bindings"]
    target_key = _target_key(envelope)

    core = _core(envelope)
    assert core["equal"] is False
    assert "|id:" not in core["fact_key"]
    assert core["fact_key"].count("|") == 2

    hard_result = _assert_hard(
        envelope, bindings, target_key, "unknown", "entity_identity_unresolved"
    )
    assert "entity_identity_unresolved" in hard_result.missing_codes

    axes_result = _assert_axes(
        envelope, bindings, target_key, "unknown", "entity_identity_unresolved"
    )
    assert any(
        row.code == "entity_identity_missing"
        for row in axes_result.axis_audit["cross_entity"]
    )

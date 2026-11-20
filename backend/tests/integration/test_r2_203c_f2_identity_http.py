"""R2-203C F2：C25 同形实体身份 —— HTTP 链路 + 捕获 envelope + 公开入口分类。

链路：真实产品应用（ASGI 上的真实路由）→ 上传/解析/发布 → 捕获会话下
``POST /api/v1/conversations/{id}/messages``（``ProductEvalAdapter.ask_turn`` 发的就是这一个
产品接口）→ 落盘加密 envelope → 用**公开分类入口**判 ``cross_entity``。

断言：
- 同一条 ``SourceUnit`` 在两侧的键逐字节相等：
  ``direct_rag_answer.facts[].entity_key`` == ``db_projection.units[fact.source_unit_id].entity_key``；
- 两个公开入口（``p2_hard_evidence`` v0.2 scope 合同、``p2_evidence_rescore_axes`` v2）
  都判 ``cross_entity`` = ``passed`` / ``frozen_targets_match_ok``；
- 敏感性：运行时把 ``rag/chunking._entity`` 还原成旧名称复合键 → 必须回到
  ``unknown`` / ``entity_identity_unresolved``（恢复后转绿）；
- 相邻安全反例（同一条 HTTP 链路）：问另一家店的另一实体 → 仍 ``violation`` /
  ``other_entity_used``，不得因本批转 passed。

合成语料全部虚构（青禾店/云岫店/云纹托盘），不含真实 case_id、题面、期望值。
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

_TESTS_ROOT = Path(__file__).resolve().parents[1]
if str(_TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_TESTS_ROOT))
from acceptance.support.netguard import t09_network_guard  # noqa: E402,F401  (pytest fixture)

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
    validate_turn_evidence,
)
from mktkb.evaluation.product_adapter import (  # noqa: E402
    IngestSource,
    MockChatBackend,
    P2IngestPlan,
    P2RunDataset,
    ProductEvalAdapter,
)
from evaluation.test_p2_hard_evidence import make_annotation  # noqa: E402

CASE_ID = "R2C-SYN-01"
STORE = "青禾店"
OTHER_STORE = "云岫店"
ITEM = "云纹托盘"
IDENTIFIER = "Q01"
OTHER_IDENTIFIER = "Q03"
LOCATION = "甲区1号架"
OTHER_LOCATION = "丙区3号架"

QUESTION = f"{STORE}的{ITEM}（编号 {IDENTIFIER}）位置分别是什么？"
QUESTION_OTHER_ENTITY = f"{OTHER_STORE}的{ITEM}（编号 {OTHER_IDENTIFIER}）位置分别是什么？"


def _witness(tag: str, **fields: object) -> None:
    print("WITNESS " + json.dumps({"tag": tag, **fields}, ensure_ascii=False, sort_keys=True))


def _no_outbound(guard) -> None:
    snapshot = guard.snapshot()
    assert snapshot["external"] == [], snapshot["external"]


def asyncio_test(func):
    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any):
        return asyncio.run(func(*args, **kwargs))

    return wrapper


# --------------------------------------------------------------------------- #
# 合成语料（虚构；标识列 + 同店无标识行 + 另一店同物同标识）
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
    tmp_path.mkdir(parents=True, exist_ok=True)
    locations = _xlsx(
        tmp_path / "R2C-云栖物品位置表.xlsx",
        "物品位置",
        [
            ["云栖物品位置表（合成虚构数据）"],
            [],
            ["标识", "门店", "物品", "位置"],
            [IDENTIFIER, STORE, ITEM, LOCATION],
            [None, STORE, "素纹立牌", "乙区2号架"],
            [OTHER_IDENTIFIER, OTHER_STORE, ITEM, OTHER_LOCATION],
        ],
    )
    stores = _xlsx(
        tmp_path / "R2C-合作店家信息.xlsx",
        "店家信息",
        [
            ["合作店家信息（合成虚构数据）"],
            [],
            ["标识", "店家", "联系人", "电话"],
            ["S01", STORE, "合成联系人甲", "010-00000001"],
            ["S99", OTHER_STORE, "合成联系人乙", "010-00000002"],
        ],
    )
    return locations, stores


# --------------------------------------------------------------------------- #
# 捕获装配（与既有 capture 夹具同一入口：ProductEvalAdapter + EvidenceWriter）
# --------------------------------------------------------------------------- #


def _bindings(run_id: str) -> dict[str, str]:
    values = {key: "local_mock-" + key for key in BINDING_KEYS}
    values["fixture_kind"] = "local_mock"
    values["run_id"] = run_id
    values["dataset_version"] = "r2c-v1"
    values["plan_sha256"] = "e" * 64
    return values


def _dataset() -> P2RunDataset:
    return P2RunDataset(
        visibility="public",
        cases=(),
        identity={
            "dataset_version": "r2c-v1",
            "label_version": "synthetic-v1",
            "suite": "p2-holdout",
            "manifest_sha256": "b" * 64,
            "case_count": 0,
        },
    )


async def _capture(tmp_path: Path, *, run_id: str, question: str = QUESTION) -> dict[str, Any]:
    locations, stores = _corpus(tmp_path)
    bindings = _bindings(run_id)
    writer = EvidenceWriter(
        root_dir=tmp_path / "evidence", key=Fernet.generate_key(), bindings=bindings, run_name="run"
    )
    adapter = ProductEvalAdapter(
        tmp_path / "product",
        chat=MockChatBackend(),
        dataset=_dataset(),
        ingest_plan=P2IngestPlan(sources=(IngestSource(locations), IngestSource(stores)), label="r2c"),
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
        turn = await adapter.ask_turn(
            question,
            user_id="employee",
            conversation_id=conversation,
            client_request_id=str(uuid.uuid4()),
        )
    finally:
        await adapter.close()
    receipts = sorted(
        (item for item in writer.written if item["kind"] == "turn"), key=lambda item: item["turn_index"]
    )
    assert len(receipts) == 1
    envelope = read_encrypted_evidence(
        Path(receipts[0]["path"]), key=writer.key, expected_bindings=writer.bindings
    )
    return {"envelope": envelope, "bindings": merged, "turn": turn}


# --------------------------------------------------------------------------- #
# envelope 视图（只取固定码/布尔/哈希与两侧键）
# --------------------------------------------------------------------------- #


def _events(envelope: dict[str, Any]) -> list[dict[str, Any]]:
    return [e for e in (envelope.get("capture") or {}).get("events") or () if isinstance(e, dict)]


def _payloads(envelope: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    return [e.get("payload") or {} for e in _events(envelope) if str(e.get("kind")) == kind]


def _units(envelope: dict[str, Any]) -> list[dict[str, Any]]:
    return [row for row in (envelope.get("db_projection") or {}).get("units") or () if isinstance(row, dict)]


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


def _target_key(envelope: dict[str, Any], *, store: str = STORE) -> str:
    """目标实体键：带 ``|id:`` 且门店过滤等于本店的物品行（从投影读，不硬编码）。"""
    for row in _units(envelope):
        key = str(row.get("entity_key") or "")
        filters = dict(row.get("entity_filters") or {})
        if str(row.get("entity_type") or "") == "item" and "|id:" in key and filters.get("store") == store:
            return key
    raise AssertionError("合成语料必须至少有一条本店带标识物品行")


def _core(envelope: dict[str, Any]) -> dict[str, Any]:
    facts = _facts(envelope)
    units = {str(row.get("unit_id")): row for row in _units(envelope)}
    resolved = [
        (fact, units.get(str(fact.get("source_unit_id") or "")))
        for fact in facts
        if fact.get("source_unit_id")
    ]
    assert resolved, {
        "event_kinds": sorted({str(e.get("kind")) for e in _events(envelope)}),
        "fact_count": len(facts),
    }
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
        "unit_filters": dict(unit.get("entity_filters") or {}),
    }


# --------------------------------------------------------------------------- #
# 公开分类入口
# --------------------------------------------------------------------------- #


def _case() -> CaseSpec:
    return CaseSpec(
        case_id=CASE_ID,
        suite="p2-holdout",
        split="holdout",
        stratum=str(hard.STRATA[0]),
        business_date="2026-11-20",
        question=QUESTION,
        turns=(),
        expected_values=(),
        expected_sources=(),
        relevant_units=(),
        should_refuse=False,
        labeler="synthetic-fixture",
        label_version="synthetic-v1",
    )


def _hard_result(envelope: dict[str, Any], bindings: dict[str, str], target_key: str) -> Any:
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
                        {"entity_type": "item", "entity_key": target_key, "filters": {"store": STORE}}
                    ],
                    "shared_background": [],
                }
            ],
        },
        expected_bindings=bindings,
    )
    audit = {
        "quality_status": "pass",
        "turns": [{"turn_index": 0, "status": "executed", "error": None, "evidence": envelope}],
    }
    return hard.classify_case_evidence(case, annotation, audit, scope_contract=scope)


def _axes_case(envelope: dict[str, Any], bindings: dict[str, str], target_key: str) -> axes.AxesCaseView:
    projection_units = {str(row.get("unit_id")): row for row in _units(envelope)}
    layers = _used_layers(envelope)
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
            "targets": [{"entity_type": "item", "entity_key": target_key, "filters": {"store": STORE}}],
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
        targets=({"entity_type": "item", "entity_key": target_key, "filters": {"store": STORE}},),
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
            "cross_entity": {"state": "passed", "reason": axes.PASS_REASONS["cross_entity"]},
            "stale_source": {"state": "passed", "reason": axes.PASS_REASONS["stale_source"]},
        },
    )
    return axes.AxesCaseView(
        old=old,
        annotations={"cross_entity": annotation},
        cross_entity=evidence,
        cross_entity_contract=contract,
    )


def _classify(envelope: dict[str, Any], bindings: dict[str, str], target_key: str) -> dict[str, Any]:
    hard_result = _hard_result(envelope, bindings, target_key)
    axes_result = axes.rescore_axes_case(_axes_case(envelope, bindings, target_key), allow_synthetic_fixture=True)
    return {
        "hard": (hard_result.axis_state("cross_entity"), hard_result.axes["cross_entity"].reason),
        "axes": (axes_result.new_axes["cross_entity"]["state"], axes_result.new_axes["cross_entity"]["reason"]),
        "hard_result": hard_result,
        "axes_result": axes_result,
    }


# --------------------------------------------------------------------------- #
# F2-1：正例（两侧键逐字节相等 + 两入口 passed/frozen_targets_match_ok）
# --------------------------------------------------------------------------- #


@asyncio_test
async def test_f2_same_shape_keys_byte_equal_and_cross_entity_passes(
    tmp_path: Path, t09_network_guard
) -> None:
    captured = await _capture(tmp_path, run_id="r2c-f2-core")
    envelope = captured["envelope"]
    bindings = captured["bindings"]
    core = _core(envelope)
    target_key = _target_key(envelope)
    result = _classify(envelope, bindings, target_key)
    _witness(
        "f2-1-positive",
        http_status=captured["turn"].http_status,
        kind=captured["turn"].kind,
        fact_key=core["fact_key"],
        unit_key=core["unit_key"],
        equal=core["equal"],
        target_key=target_key,
        hard=result["hard"],
        axes=result["axes"],
        source_ids=len(captured["turn"].source_ids),
    )

    # HTTP 链路本身是绿的（不是被拒/未找到）。
    assert captured["turn"].http_status == 200, captured["turn"].http_status
    assert captured["turn"].kind == "answer", captured["turn"].kind
    # 两侧键逐字节相等，且形态是标识形态（|id:），门店过滤一致。
    assert core["equal"] is True, (core["fact_key"], core["unit_key"])
    assert "|id:" in core["fact_key"] and "|id:" in core["unit_key"]
    assert core["unit_type"] == "item"
    assert core["unit_filters"].get("store") == STORE, core["unit_filters"]
    assert core["fact_key"] == target_key
    # 两个公开入口：passed / frozen_targets_match_ok。
    assert result["hard"] == ("passed", axes.PASS_REASONS["cross_entity"]), result["hard"]
    assert result["axes"] == ("passed", axes.PASS_REASONS["cross_entity"]), result["axes"]
    _no_outbound(t09_network_guard)


# --------------------------------------------------------------------------- #
# F2-2：敏感性（运行时还原旧名称复合键 → unknown/entity_identity_unresolved）
# --------------------------------------------------------------------------- #


def _legacy_entity(fields, *, doc, unit_id=None):  # noqa: ANN001, ANN202
    """把 ``rag/chunking._entity`` 还原成旧名称复合形态（运行时替换，不动文件）。"""
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
async def test_f2_sensitivity_legacy_entity_shape_returns_unknown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, t09_network_guard
) -> None:
    from mktkb.rag import chunking as module

    monkeypatch.setattr(module, "_entity", _legacy_entity)
    captured = await _capture(tmp_path, run_id="r2c-f2-legacy")
    envelope = captured["envelope"]
    bindings = captured["bindings"]
    core = _core(envelope)
    target_key = _target_key(envelope)
    result = _classify(envelope, bindings, target_key)
    _witness(
        "f2-2-sensitivity-legacy-red",
        fact_key=core["fact_key"],
        unit_key=core["unit_key"],
        equal=core["equal"],
        hard=result["hard"],
        axes=result["axes"],
        missing_codes=sorted(result["hard_result"].missing_codes),
    )

    # 红态：两侧键不再相等（旧名称复合形态 vs 标识形态）。
    assert core["equal"] is False, (core["fact_key"], core["unit_key"])
    assert "|id:" not in core["fact_key"]
    assert core["unit_key"] == target_key
    # 两个入口都回 unknown / entity_identity_unresolved。
    assert result["hard"] == ("unknown", "entity_identity_unresolved"), result["hard"]
    assert result["axes"] == ("unknown", "entity_identity_unresolved"), result["axes"]
    assert "entity_identity_unresolved" in result["hard_result"].missing_codes
    assert any(row.code == "entity_identity_missing" for row in result["axes_result"].axis_audit["cross_entity"])
    # 红态**断言消息**留档：把正例的 passed 断言在旧键形态下再跑一次，必然失败。
    with pytest.raises(AssertionError) as excinfo:
        assert result["hard"] == ("passed", axes.PASS_REASONS["cross_entity"]), result["hard"]
    _witness("f2-red-assertion-message-legacy-entity", message=str(excinfo.value)[:300])
    _no_outbound(t09_network_guard)

    # 恢复（undo）后同一场景回绿：证伪面只来自被还原的那一处派生。
    monkeypatch.undo()
    restored = await _capture(tmp_path / "restored", run_id="r2c-f2-restored")
    restored_core = _core(restored["envelope"])
    assert restored_core["equal"] is True, (restored_core["fact_key"], restored_core["unit_key"])
    restored_result = _classify(restored["envelope"], restored["bindings"], _target_key(restored["envelope"]))
    assert restored_result["hard"] == ("passed", axes.PASS_REASONS["cross_entity"]), restored_result["hard"]
    assert restored_result["axes"] == ("passed", axes.PASS_REASONS["cross_entity"]), restored_result["axes"]
    _witness("f2-2-sensitivity-restored-green", hard=restored_result["hard"], axes=restored_result["axes"])


# --------------------------------------------------------------------------- #
# F2-3：相邻安全反例（同一条 HTTP 链路，另一实体）
# --------------------------------------------------------------------------- #


@asyncio_test
async def test_f2_adjacent_other_entity_still_violates_over_http(
    tmp_path: Path, t09_network_guard
) -> None:
    """问**另一家店的另一实体**，却仍用本店目标做冻结合同 → 必须 violation/other_entity_used。"""

    captured = await _capture(tmp_path / "other", run_id="r2c-f2-other", question=QUESTION_OTHER_ENTITY)
    envelope = captured["envelope"]
    bindings = captured["bindings"]
    # 冻结合同的目标来自**正例那次**捕获（本店那条带标识物品行的键 = item|id:q01）；
    # 本问实际使用的是另一实体，所以下面必须判 violation，而不是因"键相等的另一行"放过。
    positive = await _capture(tmp_path / "positive", run_id="r2c-f2-other-target")
    target_key = _target_key(positive["envelope"], store=STORE)
    core = _core(envelope)
    result = _classify(envelope, bindings, target_key)
    _witness(
        "f2-3-other-entity",
        http_status=captured["turn"].http_status,
        kind=captured["turn"].kind,
        used_key=core["fact_key"],
        target_key=target_key,
        hard=result["hard"],
        axes=result["axes"],
    )

    assert captured["turn"].http_status == 200, captured["turn"].http_status
    assert captured["turn"].kind == "answer", captured["turn"].kind
    # 用户拿到的确实是另一实体（HTTP 面自洽），而分类面必须拒绝把它当成本批的通过。
    assert core["fact_key"] != target_key
    assert OTHER_LOCATION in (captured["turn"].text or ""), captured["turn"].text
    assert result["hard"][0] == "violation", result["hard"]
    assert result["axes"][0] == "violation", result["axes"]
    assert result["hard"][1] in {"other_entity_used", "citation_entity_mismatch"}, result["hard"]
    assert result["axes"][1] in {"other_entity_used", "citation_entity_mismatch"}, result["axes"]
    _no_outbound(t09_network_guard)

"""T05 有效索引与检索集成检查（R01～R12）。

全部用真实 HTTP 上传、单次 worker 与管理员发布建立版本；只在明确的故障样本上注入损坏状态。
冻结 fixture 只读；额外样本在 pytest 临时目录生成。
"""

from __future__ import annotations

import io
import threading
import uuid
from pathlib import Path

import openpyxl
import pytest
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.exc import IntegrityError

from mktkb.config import Settings
from mktkb.db import Database, current_revision, run_migrations
from mktkb.documents.lifecycle import (
    cancel_version,
    delete_document,
    get_revision,
    prepare_version_index,
    publish_version,
)
from mktkb.documents.models import (
    Document,
    DocumentVersion,
    KnowledgeState,
    PublicationReceipt,
    SourceUnit,
)
from mktkb.ingestion.worker import run_one_job
from mktkb.main import create_app
from mktkb.retrieval.index import backfill_published_indexes, index_rows_present
from mktkb.retrieval.models import RetrievalFieldIndex, RetrievalUnitIndex, RetrievalVersionIndex
from mktkb.retrieval.service import retrieve
from mktkb.retrieval.types import (
    IndexNotReady,
    KnowledgeRevisionChanged,
    QueryIntent,
    QueryRejected,
)
import mktkb.retrieval.service as retrieval_service

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "fixtures" / "acceptance"
D01 = FIXTURES / "normal" / "D01_物品位置表.xlsx"
D02 = FIXTURES / "normal" / "D02_合作店家信息.xlsx"
D03 = FIXTURES / "normal" / "D03_市场部工作指南.docx"
D04 = FIXTURES / "normal" / "D04_活动策划流程.docx"
V03 = FIXTURES / "variants" / "V03_物品位置表_历史V1.xlsx"
V04 = FIXTURES / "variants" / "V04_物品位置表_新版V3.xlsx"
V05 = FIXTURES / "variants" / "V05_物品位置表_新版V3_移除P01.xlsx"
V06 = FIXTURES / "variants" / "V06_合作店家信息_新电话.xlsx"
SNAPSHOT = ROOT / "docs" / "evidence" / "T05" / "before" / "t04-snapshot"


# ---------------------------------------------------------------- 辅助


def _session(app):
    return app.state.db.session()


def _run_worker(app):
    db = _session(app)
    try:
        return run_one_job(db, app.state.store)
    finally:
        db.close()


def _upload(admin_write, *, path=None, content=None, name=None, document_id=None, expected_active=None):
    return admin_write.upload(
        path=path,
        content=content,
        name=name or (Path(path).name if path else None),
        document_id=document_id,
        expected_active_version_id=expected_active,
    )


def _publish(admin_write, document_id, version_id, *, expected_active, revision):
    return admin_write.client.post(
        f"/api/v1/documents/{document_id}/versions/{version_id}/publish",
        headers=admin_write.headers,
        json={"expected_active_version_id": expected_active, "expected_revision": revision},
    )


def _publish_ready(admin_write, app, *, path=None, content=None, name=None, document_id=None, expected_active=None, revision=0):
    receipt = _upload(
        admin_write, path=path, content=content, name=name, document_id=document_id, expected_active=expected_active
    )
    assert receipt.status_code == 202, receipt.text
    record = receipt.json()
    assert _run_worker(app).state == "succeeded"
    published = _publish(
        admin_write, record["document"]["id"], record["version"]["id"], expected_active=expected_active, revision=revision
    )
    assert published.status_code == 200, published.text
    return record, published.json()


def _detail(admin_write, document_id):
    response = admin_write.client.get(f"/api/v1/documents/{document_id}")
    assert response.status_code == 200, response.text
    return response.json()


def _revision(app):
    db = _session(app)
    try:
        return get_revision(db)
    finally:
        db.close()


def _b0(admin_write, app):
    """B0 位置槽前缀：V03→D01 同一资料、D02、D03、D04 各自一次发布。"""
    v03, first = _publish_ready(admin_write, app, path=V03, revision=0)
    positions = v03["document"]["id"]
    d01, second = _publish_ready(
        admin_write,
        app,
        path=D01,
        document_id=positions,
        expected_active=v03["version"]["id"],
        revision=first["revision"],
    )
    d02, third = _publish_ready(admin_write, app, path=D02, revision=second["revision"])
    d03, fourth = _publish_ready(admin_write, app, path=D03, revision=third["revision"])
    d04, fifth = _publish_ready(admin_write, app, path=D04, revision=fourth["revision"])
    return {
        "positions": {"document": positions, "v1": v03["version"]["id"], "v2": d01["version"]["id"]},
        "stores": {"document": d02["document"]["id"], "version": d02["version"]["id"]},
        "guide": {"document": d03["document"]["id"], "version": d03["version"]["id"]},
        "planning": {"document": d04["document"]["id"], "version": d04["version"]["id"]},
        "revision": fifth["revision"],
    }


def _retrieve(app, intent, *, revision=None, limit=20):
    db = _session(app)
    try:
        current = get_revision(db) if revision is None else revision
        return retrieve(db, intent, revision=current, limit=limit)
    finally:
        db.close()


def _fields(result):
    return [unit.fields for unit in result.units]


def _xlsx_bytes(rows, header) -> bytes:
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "记录"
    sheet.append(list(header))
    for row in rows:
        sheet.append(list(row))
    stream = io.BytesIO()
    workbook.save(stream)
    workbook.close()
    return stream.getvalue()


def _store_xlsx(rows) -> bytes:
    return _xlsx_bytes(rows, ("标识", "店家", "联系人", "电话", "地址", "合作状态"))


# ---------------------------------------------------------------- R01 精确字段


def test_r01_exact_fields_cover_q01_to_q24(admin_write, app):
    b0 = _b0(admin_write, app)
    positions = [
        ("城东店", "宣传海报", "B区1号货架第二层", "P01", 8),
        ("城西店", "宣传海报", "C区2号货架第一层", "P02", 9),
        ("城东店", "展架", "A区2号货架底层", "P03", 10),
        ("城西店", "展架", "B区3号货架中层", "P04", 11),
        ("城东店", "易拉宝", "D区1号柜第二层", "P05", 12),
        ("城西店", "易拉宝", "D区2号柜第二层", "P06", 13),
        ("城东店", "促销贴纸", "A区4号货架第一层", "P07", 14),
        ("城西店", "价签卡纸", "C区1号柜第一层", "P08", 15),
    ]
    for store, item, location, record_id, row in positions:
        result = _retrieve(
            app, QueryIntent(mode="record", entity_filters={"store": store, "item": item}, requested_fields=("位置",))
        )
        assert result.kind == "matches", (record_id, result.kind)
        assert result.total_candidates == 1
        assert len(result.units) == 1, (record_id, len(result.units))
        unit = result.units[0]
        assert unit.fields["标识"] == record_id
        assert unit.fields["位置"] == location, record_id
        assert unit.locator["row"] == row and unit.locator["sheet"] == "物品位置"
        assert str(unit.document_id) == b0["positions"]["document"]
        assert str(unit.version_id) == b0["positions"]["v2"]
        assert result.candidates[0].source_ids == (str(unit.id),)

    stores = [
        ("城东店", "S01", "模拟联系人·陈宁", "010-00000001", "示例市示例路18号（模拟）", "合作中"),
        ("城西店", "S02", "模拟联系人·王平", "010-00000002", "示例市示例路26号（模拟）", "合作中"),
        ("城北店", "S03", "模拟联系人·李禾", "010-00000003", "示例市北街8号（模拟）", "暂停合作"),
        ("滨河店", "S04", "模拟联系人·周安", "010-00000004", "示例市滨河路6号（模拟）", "待签约"),
    ]
    for store, record_id, contact, phone, address, status in stores:
        for field_name, expected in (("联系人", contact), ("电话", phone), ("地址", address), ("合作状态", status)):
            result = _retrieve(
                app, QueryIntent(mode="record", entity_filters={"store": store}, requested_fields=(field_name,))
            )
            assert result.kind == "matches", (record_id, field_name, result.kind)
            assert result.total_candidates == 1
            unit = result.units[0]
            assert unit.fields["标识"] == record_id
            assert expected in unit.fields.values(), (record_id, field_name)
            assert str(unit.document_id) == b0["stores"]["document"]
            assert result.candidates[0].entity_filters["store_id"] == record_id

    # 电话前导 0 原样保留；旧 V03 与隐藏表不得出现在结果中
    phone = _retrieve(app, QueryIntent(mode="record", entity_filters={"store": "城东店"}, requested_fields=("电话",)))
    assert phone.units[0].fields["电话"] == "010-00000001"
    assert "A区3号货架第二层" not in {unit.fields.get("位置") for unit in phone.units}


# ---------------------------------------------------------------- R02 别名与短词


def test_r02_alias_short_terms_and_exact_ids(admin_write, app):
    _b0(admin_write, app)

    single = _retrieve(
        app, QueryIntent(mode="record", terms=("海报",), entity_filters={"store": "城东店"}, requested_fields=("位置",))
    )
    assert single.kind == "matches" and single.units[0].fields["标识"] == "P01"

    ambiguous = _retrieve(app, QueryIntent(mode="record", terms=("海报",), requested_fields=("位置",)))
    assert ambiguous.kind == "ambiguous"
    assert ambiguous.total_candidates == 2
    assert {candidate.entity_filters["store"] for candidate in ambiguous.candidates} == {"城东店", "城西店"}

    shelf = _retrieve(app, QueryIntent(mode="record", terms=("展示架",), entity_filters={"store": "城西店"}))
    assert shelf.kind == "matches" and shelf.units[0].fields["标识"] == "P04"

    price_tag = _retrieve(
        app,
        QueryIntent(mode="record", terms=("价签纸",), entity_filters={"store": "城西店"}, requested_fields=("位置",)),
    )
    assert price_tag.units[0].fields["标识"] == "P08"

    short = _retrieve(app, QueryIntent(mode="record", terms=("贴纸",), entity_filters={"store": "城东店"}))
    assert short.kind == "matches" and short.units[0].fields["标识"] == "P07"

    one_char = _retrieve(app, QueryIntent(mode="record", terms=("展",), requested_fields=("位置",)))
    assert one_char.kind == "ambiguous" and one_char.total_candidates == 2

    by_id = _retrieve(app, QueryIntent(mode="record", entity_filters={"item_id": "P02"}, requested_fields=("位置",)))
    assert by_id.kind == "matches" and by_id.units[0].fields["位置"] == "C区2号货架第一层"

    by_phone = _retrieve(app, QueryIntent(mode="record", terms=("010-00000002",)))
    assert by_phone.kind == "matches" and by_phone.units[0].fields["标识"] == "S02"

    # 空别名不得被当作第一条命中
    empty_alias = _retrieve(
        app, QueryIntent(mode="record", entity_filters={"store": "城东店", "item": "易拉宝"}, requested_fields=("位置",))
    )
    assert empty_alias.total_candidates == 1 and empty_alias.units[0].fields["标识"] == "P05"


# ---------------------------------------------------------------- R03 中文正文


def test_r03_document_text_query(admin_write, app):
    b0 = _b0(admin_write, app)

    claim = _retrieve(app, QueryIntent(mode="document", terms=("领取", "活动物料", "步骤")))
    assert claim.kind == "matches" and claim.total_candidates >= 1
    guide_units = [unit for unit in claim.units if str(unit.document_id) == b0["guide"]["document"]]
    texts = [unit.text for unit in guide_units]
    assert any("填写活动名称、门店、用途与数量" in text for text in texts)
    assert all(unit.kind == "paragraph" for unit in claim.units)
    headings = {unit.locator.get("heading") for unit in guide_units}
    assert "2.3 物料领用与登记" in headings

    returned = _retrieve(app, QueryIntent(mode="document", terms=("归还", "登记")))
    assert any("归还日期" in unit.text for unit in returned.units)

    apply_lead = _retrieve(app, QueryIntent(mode="document", terms=("活动申请", "提前")))
    assert any("3 个工作日" in unit.text for unit in apply_lead.units)
    assert any(unit.locator.get("heading") == "3.1 活动申请" for unit in apply_lead.units)

    reordered = _retrieve(app, QueryIntent(mode="document", terms=("工作日", "提前")))
    target = next(unit.id for unit in apply_lead.units if "3 个工作日" in unit.text)
    assert target in {unit.id for unit in reordered.units}, "不同词序应召回同一证据段落"

    plan = _retrieve(app, QueryIntent(mode="document", terms=("活动方案", "包含")))
    assert any("物料清单" in unit.text for unit in plan.units)

    irrelevant = _retrieve(app, QueryIntent(mode="document", terms=("报销流程",)))
    assert irrelevant.kind == "none" and irrelevant.total_candidates == 0


# ---------------------------------------------------------------- R04 候选截断


def test_r04_candidate_truncation_and_dedup(admin_write, app, tmp_path):
    rows = [[f"G{index:02d}", f"测试门店{index % 5}", f"测试物料{index}", f"Z区{index}号柜"] for index in range(21)]
    rows.append(["G00", "测试门店0", "测试物料0", "Z区0号柜"])  # 同一实体重复来源
    content = _xlsx_bytes(rows, ("标识", "门店", "物品", "位置"))
    _publish_ready(admin_write, app, content=content, name="生成-21实体.xlsx", revision=0)

    full = _retrieve(app, QueryIntent(mode="record", terms=("测试物料",)), limit=100)
    assert full.kind == "ambiguous"
    assert full.total_candidates == 21, full.total_candidates
    assert full.truncated is False

    limited = _retrieve(app, QueryIntent(mode="record", terms=("测试物料",)), limit=2)
    assert limited.kind == "ambiguous"
    assert limited.total_candidates == 21
    assert len(limited.candidates) == 2
    assert len(limited.units) <= 2
    assert limited.truncated is True

    one = _retrieve(app, QueryIntent(mode="record", terms=("测试物料",)), limit=1)
    assert one.kind == "ambiguous" and one.total_candidates == 21 and len(one.candidates) == 1

    again = _retrieve(app, QueryIntent(mode="record", terms=("测试物料",)), limit=2)
    assert [candidate.label for candidate in again.candidates] == [candidate.label for candidate in limited.candidates]

    duplicate_entity = next(candidate for candidate in full.candidates if candidate.label == "测试门店0的测试物料0")
    assert len(duplicate_entity.source_ids) >= 1


# ---------------------------------------------------------------- R05 冲突与同名


def test_r05_conflict_and_same_name_ambiguity(admin_write, app, tmp_path):
    b0 = _b0(admin_write, app)
    v06, _published = _publish_ready(admin_write, app, path=V06, revision=b0["revision"])

    conflict = _retrieve(
        app,
        QueryIntent(mode="record", entity_filters={"store": "城东店"}, requested_fields=("电话",)),
    )
    assert conflict.kind == "conflict", conflict.kind
    assert conflict.total_candidates == 1
    values = {unit.fields["电话"] for unit in conflict.units}
    assert values == {"010-00000001", "010-00000088"}, values
    assert {str(unit.document_id) for unit in conflict.units} == {
        b0["stores"]["document"],
        v06["document"]["id"],
    }, "冲突必须列出两份真实来源"

    # 不同实体 ID、相同显示名：不得合并成冲突，也不按上传顺序选真
    same_a = _store_xlsx([["T01", "同名店", "联系人甲", "111-0001", "地址甲", "合作中"]])
    same_b = _store_xlsx([["T02", "同名店", "联系人乙", "222-0002", "地址乙", "合作中"]])
    _publish_ready(admin_write, app, content=same_a, name="同名店A.xlsx", revision=conflict.revision)
    _publish_ready(admin_write, app, content=same_b, name="同名店B.xlsx", revision=conflict.revision + 1)

    ambiguous = _retrieve(
        app, QueryIntent(mode="record", entity_filters={"store": "同名店"}, requested_fields=("电话",))
    )
    assert ambiguous.kind == "ambiguous", ambiguous.kind
    assert ambiguous.total_candidates == 2
    assert {candidate.entity_filters["store_id"] for candidate in ambiguous.candidates} == {"T01", "T02"}


# ---------------------------------------------------------------- R06 无依据/缺字段


def test_r06_none_and_missing_fields(admin_write, app):
    _b0(admin_write, app)

    missing_store = _retrieve(app, QueryIntent(mode="record", entity_filters={"store": "城南店"}))
    assert missing_store.kind == "none" and missing_store.total_candidates == 0

    missing_term = _retrieve(app, QueryIntent(mode="record", terms=("从未出现的关键词",)))
    assert missing_term.kind == "none"

    no_owner = _retrieve(
        app,
        QueryIntent(
            mode="record",
            entity_filters={"store": "城东店", "item": "宣传海报"},
            requested_fields=("负责人",),
        ),
    )
    assert no_owner.kind == "matches"
    assert no_owner.total_candidates == 1
    assert {unit.fields["标识"] for unit in no_owner.units} == {"P01"}
    assert all("模拟联系人" not in unit.text for unit in no_owner.units)

    no_hours = _retrieve(
        app, QueryIntent(mode="record", entity_filters={"store": "城东店"}, requested_fields=("营业时间",))
    )
    assert no_hours.kind == "matches" and no_hours.total_candidates == 1


# ---------------------------------------------------------------- R07 有效性/旧索引


def test_r07_old_index_invisible_after_replace_cancel_delete(admin_write, app):
    b0 = _b0(admin_write, app)
    positions = b0["positions"]["document"]

    before = _retrieve(app, QueryIntent(mode="record", entity_filters={"item_id": "P01"}, requested_fields=("位置",)))
    assert before.units[0].fields["位置"] == "B区1号货架第二层"

    pending = _upload(admin_write, path=V04, document_id=positions, expected_active=b0["positions"]["v2"])
    assert pending.status_code == 202, pending.text
    assert _run_worker(app).state == "succeeded"
    preview = _retrieve(app, QueryIntent(mode="record", entity_filters={"item_id": "P01"}, requested_fields=("位置",)))
    assert preview.units[0].fields["位置"] == "B区1号货架第二层", "未发布新版不得生效"

    published_v04 = _publish(
        admin_write,
        positions,
        pending.json()["version"]["id"],
        expected_active=b0["positions"]["v2"],
        revision=b0["revision"],
    )
    assert published_v04.status_code == 200, published_v04.text
    v04 = pending.json()
    publish_v04 = published_v04.json()
    after = _retrieve(app, QueryIntent(mode="record", entity_filters={"item_id": "P01"}, requested_fields=("位置",)))
    assert after.units[0].fields["位置"] == "D区暂存柜"
    assert str(after.units[0].version_id) == v04["version"]["id"]

    v05, publish_v05 = _publish_ready(
        admin_write,
        app,
        path=V05,
        document_id=positions,
        expected_active=v04["version"]["id"],
        revision=publish_v04["revision"],
    )
    gone = _retrieve(app, QueryIntent(mode="record", entity_filters={"item_id": "P01"}))
    assert gone.kind == "none" and gone.total_candidates == 0

    db = _session(app)
    try:
        stale_units = int(
            db.scalar(
                select(func.count())
                .select_from(RetrievalUnitIndex)
                .where(RetrievalUnitIndex.version_id == uuid.UUID(v04["version"]["id"]))
            )
            or 0
        )
        assert stale_units > 0, "旧索引物理保留"
        retained_units = int(
            db.scalar(
                select(func.count())
                .select_from(SourceUnit)
                .where(SourceUnit.version_id == uuid.UUID(b0["positions"]["v2"]))
            )
            or 0
        )
        assert retained_units > 0, "旧来源单元物理保留"
    finally:
        db.close()

    p02 = _retrieve(app, QueryIntent(mode="record", entity_filters={"item_id": "P02"}, requested_fields=("位置",)))
    assert p02.units[0].fields["位置"] == "C区2号货架第一层"

    deleted = admin_write.client.delete(
        f"/api/v1/documents/{positions}",
        params={"expected_revision": publish_v05["revision"]},
        headers=admin_write.headers,
    )
    assert deleted.status_code == 200, deleted.text
    deleted_revision = deleted.json()["revision"]
    assert _retrieve(app, QueryIntent(mode="record", entity_filters={"item_id": "P02"})).kind == "none"

    other = _retrieve(app, QueryIntent(mode="record", entity_filters={"store": "城西店"}, requested_fields=("电话",)))
    assert other.kind in ("matches", "conflict") and other.total_candidates == 1

    reappeared, _ = _publish_ready(
        admin_write, app, path=V05, name="重新导入-V05.xlsx", revision=deleted_revision
    )
    assert reappeared["document"]["id"] != positions
    assert _retrieve(app, QueryIntent(mode="record", entity_filters={"item_id": "P01"})).kind == "none"


# ---------------------------------------------------------------- R08 索引就绪/幂等


def test_r08_index_readiness_idempotency_and_publish_gate(admin_write, app):
    b0 = _b0(admin_write, app)

    db = _session(app)
    try:
        db.execute(delete(RetrievalVersionIndex).where(RetrievalVersionIndex.version_id == uuid.UUID(b0["guide"]["version"])))
        db.commit()
    finally:
        db.close()
    with pytest.raises(IndexNotReady):
        _retrieve(app, QueryIntent(mode="document", terms=("物料",)))

    db = _session(app)
    try:
        statuses = backfill_published_indexes(db)
    finally:
        db.close()
    assert statuses and all(status.ready for status in statuses)
    assert _retrieve(app, QueryIntent(mode="document", terms=("物料",))).kind == "matches"

    # 重复准备不重复单元/FTS 行
    db = _session(app)
    try:
        prepare_version_index(db, uuid.UUID(b0["stores"]["version"]))
        prepare_version_index(db, uuid.UUID(b0["stores"]["version"]))
        unit_rows = int(
            db.scalar(
                select(func.count())
                .select_from(RetrievalUnitIndex)
                .where(RetrievalUnitIndex.version_id == uuid.UUID(b0["stores"]["version"]))
            )
            or 0
        )
        field_rows = int(
            db.scalar(
                select(func.count())
                .select_from(RetrievalFieldIndex)
                .where(RetrievalFieldIndex.version_id == uuid.UUID(b0["stores"]["version"]))
            )
            or 0
        )
        fts_rows = int(
            db.scalar(
                text(
                    "SELECT count(*) FROM source_unit_fts WHERE rowid IN ("
                    "SELECT fts_rowid FROM retrieval_unit_index WHERE version_id = :version)"
                ),
                {"version": uuid.UUID(b0["stores"]["version"]).hex},
            )
            or 0
        )
        assert unit_rows == 4 and fts_rows == 4 and field_rows == 24
    finally:
        db.close()

    # 不完整 marker 拒发：旧有效版、revision、active 不变
    desired = _upload(admin_write, path=V04, document_id=b0["positions"]["document"], expected_active=b0["positions"]["v2"])
    assert desired.status_code == 202, desired.text
    desired_record = desired.json()
    assert _run_worker(app).state == "succeeded"
    db = _session(app)
    try:
        prepare_version_index(db, uuid.UUID(desired_record["version"]["id"]))
        row = db.get(RetrievalVersionIndex, uuid.UUID(desired_record["version"]["id"]))
        row.unit_count = 0
        db.commit()
    finally:
        db.close()
    before = _detail(admin_write, b0["positions"]["document"])
    refused = _publish(
        admin_write,
        b0["positions"]["document"],
        desired_record["version"]["id"],
        expected_active=b0["positions"]["v2"],
        revision=b0["revision"],
    )
    assert refused.status_code == 409, refused.text
    after = _detail(admin_write, b0["positions"]["document"])
    assert after["revision"] == before["revision"]
    assert after["document"]["active_version"]["id"] == before["document"]["active_version"]["id"]
    kept = _retrieve(app, QueryIntent(mode="record", entity_filters={"item_id": "P01"}, requested_fields=("位置",)))
    assert kept.units[0].fields["位置"] == "B区1号货架第二层"

    db = _session(app)
    try:
        status = prepare_version_index(db, uuid.UUID(desired_record["version"]["id"]))
    finally:
        db.close()
    assert status.ready
    published = _publish(
        admin_write,
        b0["positions"]["document"],
        desired_record["version"]["id"],
        expected_active=b0["positions"]["v2"],
        revision=b0["revision"],
    )
    assert published.status_code == 200, published.text
    assert published.json()["revision"] == b0["revision"] + 1
    repeat = _publish(
        admin_write,
        b0["positions"]["document"],
        desired_record["version"]["id"],
        expected_active=b0["positions"]["v2"],
        revision=b0["revision"],
    )
    assert repeat.status_code == 200 and repeat.json()["revision"] == b0["revision"] + 1

    # FTS 表缺失不是 none
    db = _session(app)
    try:
        db.execute(text("DROP TABLE source_unit_fts"))
        db.commit()
    finally:
        db.close()
    with pytest.raises(IndexNotReady):
        _retrieve(app, QueryIntent(mode="record", terms=("海报",)))


# ---------------------------------------------------------------- R09 并发与 revision


def test_r09_revision_and_concurrent_cancel(admin_write, app, monkeypatch):
    b0 = _b0(admin_write, app)
    stale = b0["revision"] - 1
    with pytest.raises(KnowledgeRevisionChanged):
        _retrieve(app, QueryIntent(mode="record", entity_filters={"store": "城东店"}), revision=stale)

    # 过期 revision 在并发发布后立即拒绝，绝不返回新版本内容
    old_revision = b0["revision"]
    desired = _upload(admin_write, path=V04, document_id=b0["positions"]["document"], expected_active=b0["positions"]["v2"])
    assert desired.status_code == 202
    desired_record = desired.json()
    assert _run_worker(app).state == "succeeded"
    published = _publish(
        admin_write,
        b0["positions"]["document"],
        desired_record["version"]["id"],
        expected_active=b0["positions"]["v2"],
        revision=old_revision,
    )
    assert published.status_code == 200, published.text
    with pytest.raises(KnowledgeRevisionChanged):
        _retrieve(app, QueryIntent(mode="record", entity_filters={"item_id": "P01"}), revision=old_revision)
    fresh = _retrieve(app, QueryIntent(mode="record", entity_filters={"item_id": "P01"}, requested_fields=("位置",)))
    assert fresh.units[0].fields["位置"] == "D区暂存柜"

    # 索引准备期间取消：迟到索引不落库、资料不复活
    pending = _upload(admin_write, path=V05, document_id=b0["positions"]["document"], expected_active=desired_record["version"]["id"])
    assert pending.status_code == 202
    pending_record = pending.json()
    assert _run_worker(app).state == "succeeded"

    import mktkb.retrieval.index as index_module

    original = index_module.index_body
    started = threading.Event()
    release = threading.Event()

    def blocking(text_value):
        started.set()
        assert release.wait(10), "test barrier timeout"
        return original(text_value)

    monkeypatch.setattr(index_module, "index_body", blocking)
    outcomes = {}

    def prepare_in_thread():
        db = _session(app)
        try:
            outcomes["status"] = prepare_version_index(db, uuid.UUID(pending_record["version"]["id"]))
        finally:
            db.close()

    thread = threading.Thread(target=prepare_in_thread, name="t05-prepare")
    thread.start()
    assert started.wait(10)
    db = _session(app)
    try:
        cancel_version(db, uuid.UUID(b0["positions"]["document"]), uuid.UUID(pending_record["version"]["id"]))
    finally:
        db.close()
    release.set()
    thread.join(20)
    assert not thread.is_alive()
    assert outcomes["status"].ready is False
    db = _session(app)
    try:
        rows = int(
            db.scalar(
                select(func.count())
                .select_from(RetrievalUnitIndex)
                .where(RetrievalUnitIndex.version_id == uuid.UUID(pending_record["version"]["id"]))
            )
            or 0
        )
        version = db.get(DocumentVersion, uuid.UUID(pending_record["version"]["id"]))
        assert rows == 0 and version.state == "cancelled"
    finally:
        db.close()
    still = _retrieve(app, QueryIntent(mode="record", entity_filters={"item_id": "P01"}, requested_fields=("位置",)))
    assert still.units[0].fields["位置"] == "D区暂存柜"


# ---------------------------------------------------------------- R10 升级与回填


def test_r10_upgrade_from_0003_and_backfill(tmp_path):
    assert (SNAPSHOT / "facts.json").is_file(), "T05 实现前的 T04 快照必须存在"
    import json
    import shutil

    facts = json.loads((SNAPSHOT / "facts.json").read_text(encoding="utf-8"))
    data = tmp_path / "upgraded"
    shutil.copytree(SNAPSHOT / "data", data)
    url = f"sqlite:///{(data / 'mktkb.sqlite3').as_posix()}"

    run_migrations(url)
    assert current_revision(url) == "0006_ocr_call_records"
    database = Database(url)
    try:
        with database.session() as db:
            state = db.get(KnowledgeState, 1)
            assert int(state.revision) == facts["revision"]
            assert int(state.active_document_count) == facts["active_document_count"]
            assert int(state.active_excel_row_count) == facts["active_excel_row_count"]
            assert str(db.get(SourceUnit, uuid.UUID(facts["p01_unit"]["id"])).version_id) == facts["p01_unit"]["version_id"]
            with pytest.raises(IndexNotReady):
                retrieve(db, QueryIntent(mode="record", entity_filters={"item_id": "P01"}), revision=facts["revision"])
            statuses = backfill_published_indexes(db)
            assert len(statuses) == 4 and all(status.ready for status in statuses)
            result = retrieve(
                db, QueryIntent(mode="record", entity_filters={"item_id": "P01"}, requested_fields=("位置",)), revision=facts["revision"]
            )
            assert result.units[0].fields["位置"] == "B区1号货架第二层"
            assert str(result.units[0].id) == facts["p01_unit"]["id"]
        counts_before = None
        with database.session() as db:
            counts_before = (
                int(db.scalar(select(func.count()).select_from(RetrievalUnitIndex)) or 0),
                int(db.scalar(select(func.count()).select_from(RetrievalFieldIndex)) or 0),
            )
        run_migrations(url)
        with database.session() as db:
            statuses = backfill_published_indexes(db)
            counts_after = (
                int(db.scalar(select(func.count()).select_from(RetrievalUnitIndex)) or 0),
                int(db.scalar(select(func.count()).select_from(RetrievalFieldIndex)) or 0),
            )
        assert all(status.ready for status in statuses)
        assert counts_before == counts_after
    finally:
        database.dispose()

    # 升级后的库仍可登录并看到 4 份有效资料（原账号/会话/资料关系保留）
    app = create_app(
        Settings(
            data_dir=data,
            database_url=url,
            cookie_secure=False,
            csrf_secret="t05-upgrade-synthetic-secret-0123456789",
            admin_password="AdminPass-1",
            employee_password="EmployeePass-1",
            trusted_origins=["http://testserver"],
            bcrypt_rounds=4,
        )
    )
    from fastapi.testclient import TestClient

    client = TestClient(app, raise_server_exceptions=False)
    login = client.post("/api/v1/auth/login", json={"username": "admin", "password": "AdminPass-1"}, headers={"Origin": "http://testserver"})
    assert login.status_code == 200
    headers = {"Origin": "http://testserver", "X-CSRF-Token": login.json()["csrf_token"]}
    listing = client.get("/api/v1/documents", params={"limit": 100})
    assert listing.status_code == 200
    assert len(listing.json()["items"]) == 4
    app.state.db.dispose()

    # 空库升级：FTS5 可用、单一 head、空知识库检索 none
    empty_url = f"sqlite:///{(tmp_path / 'empty.sqlite3').as_posix()}"
    run_migrations(empty_url)
    empty_db = Database(empty_url)
    try:
        assert empty_db.fts5_available() is True
        with empty_db.session() as db:
            assert retrieve(db, QueryIntent(mode="document", terms=("物料",)), revision=0).kind == "none"
    finally:
        empty_db.dispose()


# ---------------------------------------------------------------- R11 安全输入


def test_r11_security_and_input_validation(admin_write, app):
    _b0(admin_write, app)

    with pytest.raises(QueryRejected):
        _retrieve(app, QueryIntent(mode="sql"))  # type: ignore[arg-type]
    with pytest.raises(QueryRejected):
        _retrieve(app, QueryIntent(mode="record", entity_filters={"id": "1"}))
    with pytest.raises(QueryRejected):
        _retrieve(app, QueryIntent(mode="record", terms=("x",)), limit=0)
    with pytest.raises(QueryRejected):
        _retrieve(app, QueryIntent(mode="record", terms=("x",)), limit=101)
    with pytest.raises(QueryRejected):
        _retrieve(app, QueryIntent(mode="record", terms=("x",)), limit="5")  # type: ignore[arg-type]
    with pytest.raises(QueryRejected):
        _retrieve(app, QueryIntent(mode="record", terms=(123,)))  # type: ignore[arg-type]
    secret = "SECRET" * 12
    with pytest.raises(QueryRejected) as excinfo:
        _retrieve(app, QueryIntent(mode="record", terms=(secret,)))
    assert secret not in str(excinfo.value)

    for hostile in ('" OR "*', "%", "_", "NEAR/2", "*"):
        result = _retrieve(app, QueryIntent(mode="record", terms=(hostile,)))
        assert result.kind == "none", (
            hostile,
            result.kind,
            [(unit.unit_key, unit.text) for unit in result.units][:3],
        )

    # 引号内文本不得变成 FTS 运算符：若被直接拼接，会同时命中“海报”和“展架”两个候选
    injected = _retrieve(app, QueryIntent(mode="record", terms=('海报" OR "展架',)))
    assert injected.kind == "none", [(unit.unit_key, unit.text) for unit in injected.units][:3]

    assert _retrieve(app, QueryIntent(mode="record", entity_filters={"item_id": "P99"})).kind == "none"
    assert _retrieve(app, QueryIntent(mode="record", entity_filters={"store_id": "S99"})).kind == "none"


# ---------------------------------------------------------------- R13 查询中发布/删除（召回中途屏障）


def _knowledge_counts(app):
    db = _session(app)
    try:
        state = db.get(KnowledgeState, 1)
        receipts = int(db.scalar(select(func.count()).select_from(PublicationReceipt)) or 0)
        return {
            "revision": int(state.revision),
            "active_document_count": int(state.active_document_count),
            "active_excel_row_count": int(state.active_excel_row_count),
            "publication_receipts": receipts,
        }
    finally:
        db.close()


@pytest.mark.parametrize("change", ["publish", "delete"])
def test_r13_query_mid_recall_keeps_one_snapshot(admin_write, app, monkeypatch, change):
    b0 = _b0(admin_write, app)
    desired = None
    if change == "publish":
        desired = _upload(
            admin_write,
            path=V04,
            document_id=b0["positions"]["document"],
            expected_active=b0["positions"]["v2"],
        )
        assert desired.status_code == 202, desired.text
        desired = desired.json()
        assert _run_worker(app).state == "succeeded"

    entered, release = threading.Event(), threading.Event()
    original = retrieval_service._filter_ids
    outcome = {}

    def barrier(db, entity_filters):
        matched = original(db, entity_filters)
        entered.set()
        assert release.wait(15), "reader barrier timed out"
        return matched

    monkeypatch.setattr(retrieval_service, "_filter_ids", barrier)

    def reader():
        db = _session(app)
        try:
            outcome["result"] = retrieval_service.retrieve(
                db,
                QueryIntent("record", entity_filters={"item_id": "P01"}),
                revision=b0["revision"],
            )
        except BaseException as exc:  # noqa: BLE001 - 原样记录给断言
            outcome["error"] = exc
        finally:
            db.close()

    thread = threading.Thread(target=reader, name="r13-reader", daemon=True)
    thread.start()
    try:
        assert entered.wait(15), "reader did not reach recall barrier"
        if change == "publish":
            response = _publish(
                admin_write,
                b0["positions"]["document"],
                desired["version"]["id"],
                expected_active=b0["positions"]["v2"],
                revision=b0["revision"],
            )
        else:
            response = admin_write.client.delete(
                f'/api/v1/documents/{b0["positions"]["document"]}',
                params={"expected_revision": b0["revision"]},
                headers=admin_write.headers,
            )
        assert response.status_code == 200, response.text
    finally:
        release.set()
        thread.join(20)
    assert not thread.is_alive(), "reader did not terminate"
    assert _revision(app) == b0["revision"] + 1

    if "error" in outcome:
        assert isinstance(outcome["error"], KnowledgeRevisionChanged), outcome["error"]
        return

    result = outcome["result"]
    assert result.revision == b0["revision"]
    assert result.kind == "matches", result.kind
    assert [unit.fields.get("位置") for unit in result.units] == ["B区1号货架第二层"]
    assert {str(unit.version_id) for unit in result.units} == {b0["positions"]["v2"]}


# ---------------------------------------------------------------- R14 发布前真实索引损坏


@pytest.mark.parametrize(
    "damage",
    [
        "fts_row",
        "mapping_row",
        "field_rows",
        "field_content",
        "fts_content",
        "marker_row",
        "field_extra",
        "fts_extra",
    ],
)
def test_r14_publish_rejects_real_index_damage_and_recovers(admin_write, app, damage):
    old, pub = _publish_ready(admin_write, app, path=D01, revision=0)
    desired = _upload(
        admin_write,
        path=V04,
        document_id=old["document"]["id"],
        expected_active=old["version"]["id"],
    )
    assert desired.status_code == 202, desired.text
    desired = desired.json()
    assert _run_worker(app).state == "succeeded"
    version = uuid.UUID(desired["version"]["id"])

    with app.state.db.session() as db:
        assert prepare_version_index(db, version).ready
        units = db.scalars(select(SourceUnit).where(SourceUnit.version_id == version)).all()
        unit = next(item for item in units if item.fields.get("标识") == "P01")
        mapping = db.scalar(select(RetrievalUnitIndex).where(RetrievalUnitIndex.unit_id == unit.id))
        assert mapping is not None
        if damage == "fts_row":
            db.execute(text("DELETE FROM source_unit_fts WHERE rowid=:id"), {"id": mapping.fts_rowid})
        elif damage == "mapping_row":
            db.delete(mapping)
        elif damage == "field_rows":
            db.execute(delete(RetrievalFieldIndex).where(RetrievalFieldIndex.unit_id == unit.id))
        elif damage == "field_content":
            db.execute(
                update(RetrievalFieldIndex)
                .where(RetrievalFieldIndex.unit_id == unit.id, RetrievalFieldIndex.field_role == "item_id")
                .values(norm_value="p99", value_text="P99")
            )
        elif damage == "marker_row":
            db.execute(delete(RetrievalVersionIndex).where(RetrievalVersionIndex.version_id == version))
        elif damage == "field_extra":
            db.add(
                RetrievalFieldIndex(
                    unit_id=unit.id,
                    version_id=version,
                    document_id=unit.document_id,
                    field_name="额外",
                    field_role=None,
                    norm_value="extra",
                    value_text="extra",
                )
            )
        elif damage == "fts_extra":
            max_rowid = int(db.scalar(select(func.max(RetrievalUnitIndex.fts_rowid))) or 0)
            db.execute(
                text(
                    "INSERT INTO source_unit_fts(rowid, body, version_id) "
                    "VALUES (:rowid, :body, :version)"
                ),
                {"rowid": max_rowid + 1000, "body": "额外正文", "version": str(version)},
            )
        else:
            db.execute(
                text("UPDATE source_unit_fts SET body=:body WHERE rowid=:id"),
                {"body": "无关内容", "id": mapping.fts_rowid},
            )
        db.commit()

    before_detail = _detail(admin_write, old["document"]["id"])
    before_counts = _knowledge_counts(app)
    before_retrieval = _retrieve(
        app, QueryIntent("record", entity_filters={"item_id": "P01"}, requested_fields=("位置",))
    )
    assert before_retrieval.units[0].fields["位置"] == "B区1号货架第二层"

    refused = _publish(
        admin_write,
        old["document"]["id"],
        desired["version"]["id"],
        expected_active=old["version"]["id"],
        revision=pub["revision"],
    )
    assert refused.status_code == 409, refused.text
    assert refused.json()["error"]["code"] == "VERSION_NOT_PUBLISHABLE"

    after_detail = _detail(admin_write, old["document"]["id"])
    assert after_detail["revision"] == before_detail["revision"]
    assert after_detail["document"]["active_version"]["id"] == before_detail["document"]["active_version"]["id"]
    after_counts = _knowledge_counts(app)
    assert after_counts == before_counts
    kept = _retrieve(
        app, QueryIntent("record", entity_filters={"item_id": "P01"}, requested_fields=("位置",))
    )
    assert kept.units[0].fields["位置"] == "B区1号货架第二层"

    # 显式重建后只发布一次；重复发布幂等
    with app.state.db.session() as db:
        rebuilt = prepare_version_index(db, version)
        assert rebuilt.ready
    published = _publish(
        admin_write,
        old["document"]["id"],
        desired["version"]["id"],
        expected_active=old["version"]["id"],
        revision=pub["revision"],
    )
    assert published.status_code == 200, published.text
    assert published.json()["revision"] == pub["revision"] + 1
    repeat = _publish(
        admin_write,
        old["document"]["id"],
        desired["version"]["id"],
        expected_active=old["version"]["id"],
        revision=pub["revision"],
    )
    assert repeat.status_code == 200, repeat.text
    assert repeat.json()["revision"] == published.json()["revision"]

    with app.state.db.session() as db:
        unit_rows_before = int(
            db.scalar(
                select(func.count())
                .select_from(RetrievalUnitIndex)
                .where(RetrievalUnitIndex.version_id == version)
            )
            or 0
        )
        field_rows_before = int(
            db.scalar(
                select(func.count())
                .select_from(RetrievalFieldIndex)
                .where(RetrievalFieldIndex.version_id == version)
            )
            or 0
        )
    statuses = None
    with app.state.db.session() as db:
        statuses = backfill_published_indexes(db)
    assert statuses and all(status.ready for status in statuses)
    with app.state.db.session() as db:
        unit_rows_after = int(
            db.scalar(
                select(func.count())
                .select_from(RetrievalUnitIndex)
                .where(RetrievalUnitIndex.version_id == version)
            )
            or 0
        )
        field_rows_after = int(
            db.scalar(
                select(func.count())
                .select_from(RetrievalFieldIndex)
                .where(RetrievalFieldIndex.version_id == version)
            )
            or 0
        )
    assert (unit_rows_before, field_rows_before) == (unit_rows_after, field_rows_after)

    fresh = _retrieve(
        app, QueryIntent("record", entity_filters={"item_id": "P01"}, requested_fields=("位置",))
    )
    assert fresh.units[0].fields["位置"] == "D区暂存柜"


# ---------------------------------------------------------------- R15 有效版本真实索引损坏


@pytest.mark.parametrize("damage", ["mapping_row", "field_rows", "fts_row"])
def test_r15_active_version_damage_is_index_not_ready(admin_write, app, damage):
    record, _pub = _publish_ready(admin_write, app, path=D01, revision=0)
    version = uuid.UUID(record["version"]["id"])
    with app.state.db.session() as db:
        units = db.scalars(select(SourceUnit).where(SourceUnit.version_id == version)).all()
        unit = next(item for item in units if item.fields.get("标识") == "P01")
        mapping = db.scalar(select(RetrievalUnitIndex).where(RetrievalUnitIndex.unit_id == unit.id))
        assert mapping is not None
        if damage == "mapping_row":
            db.delete(mapping)
        elif damage == "field_rows":
            db.execute(delete(RetrievalFieldIndex).where(RetrievalFieldIndex.unit_id == unit.id))
        else:
            db.execute(text("DELETE FROM source_unit_fts WHERE rowid=:id"), {"id": mapping.fts_rowid})
        db.commit()

    intents = (
        QueryIntent("record", entity_filters={"item_id": "P01"}),
        QueryIntent("record", terms=("宣传海报",)),
        QueryIntent("document", terms=("宣传海报",)),
    )
    for intent in intents:
        with pytest.raises(IndexNotReady):
            _retrieve(app, intent)

    with app.state.db.session() as db:
        restored = prepare_version_index(db, version)
        assert restored.ready
    result = _retrieve(
        app, QueryIntent("record", entity_filters={"item_id": "P01"}, requested_fields=("位置",))
    )
    assert result.units[0].fields["位置"] == "B区1号货架第二层"


# ---------------------------------------------------------------- R16 复合归属约束


def test_r16_composite_ownership_rejects_cross_document_and_version(admin_write, app):
    b0 = _b0(admin_write, app)
    stores_document = uuid.UUID(b0["stores"]["document"])
    stores_version = uuid.UUID(b0["stores"]["version"])
    positions_version = uuid.UUID(b0["positions"]["v2"])

    with app.state.db.session() as db:
        units = db.scalars(select(SourceUnit).where(SourceUnit.version_id == positions_version)).all()
        unit = next(item for item in units if item.fields.get("标识") == "P01")
        mapping = db.scalar(select(RetrievalUnitIndex).where(RetrievalUnitIndex.unit_id == unit.id))
        field = db.scalar(
            select(RetrievalFieldIndex).where(
                RetrievalFieldIndex.unit_id == unit.id,
                RetrievalFieldIndex.field_role == "item_id",
            )
        )
        marker = db.get(RetrievalVersionIndex, positions_version)
        assert mapping is not None and field is not None and marker is not None

        with pytest.raises(IntegrityError):
            db.execute(
                update(RetrievalFieldIndex)
                .where(RetrievalFieldIndex.id == field.id)
                .values(document_id=stores_document, version_id=stores_version)
            )
            db.commit()
        db.rollback()

        with pytest.raises(IntegrityError):
            db.execute(
                update(RetrievalUnitIndex)
                .where(RetrievalUnitIndex.fts_rowid == mapping.fts_rowid)
                .values(document_id=stores_document, version_id=stores_version)
            )
            db.commit()
        db.rollback()

        with pytest.raises(IntegrityError):
            db.execute(
                update(RetrievalVersionIndex)
                .where(RetrievalVersionIndex.version_id == positions_version)
                .values(document_id=stores_document)
            )
            db.commit()
        db.rollback()

        db.add(
            RetrievalFieldIndex(
                unit_id=unit.id,
                version_id=stores_version,
                document_id=stores_document,
                field_name="伪造",
                field_role="item_id",
                norm_value="foreign-proof",
                value_text="foreign-proof",
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()

    assert _retrieve(app, QueryIntent("record", entity_filters={"item_id": "foreign-proof"})).kind == "none"
    p01 = _retrieve(
        app, QueryIntent("record", entity_filters={"item_id": "P01"}, requested_fields=("位置",))
    )
    assert p01.units[0].fields["位置"] == "B区1号货架第二层"
    store = _retrieve(
        app, QueryIntent("record", entity_filters={"store": "城东店"}, requested_fields=("电话",))
    )
    assert store.units[0].fields["电话"] == "010-00000001"


# ---------------------------------------------------------------- R17 准备期间删除


def test_r17_prepare_delete_barrier_does_not_resurrect(admin_write, app, monkeypatch):
    record, pub = _publish_ready(admin_write, app, path=D01, revision=0)
    pending = _upload(
        admin_write,
        path=V04,
        document_id=record["document"]["id"],
        expected_active=record["version"]["id"],
    )
    assert pending.status_code == 202, pending.text
    pending_record = pending.json()
    assert _run_worker(app).state == "succeeded"
    pending_version = uuid.UUID(pending_record["version"]["id"])

    import mktkb.retrieval.index as index_module

    original = index_module.index_body
    started, release = threading.Event(), threading.Event()

    def blocking(text_value):
        started.set()
        assert release.wait(10), "test barrier timeout"
        return original(text_value)

    monkeypatch.setattr(index_module, "index_body", blocking)
    outcomes = {}

    def prepare_in_thread():
        db = _session(app)
        try:
            outcomes["status"] = prepare_version_index(db, pending_version)
        finally:
            db.close()

    thread = threading.Thread(target=prepare_in_thread, name="r17-prepare")
    thread.start()
    assert started.wait(10)
    deleted = admin_write.client.delete(
        f'/api/v1/documents/{record["document"]["id"]}',
        params={"expected_revision": pub["revision"]},
        headers=admin_write.headers,
    )
    assert deleted.status_code == 200, deleted.text
    release.set()
    thread.join(20)
    assert not thread.is_alive()
    assert outcomes["status"].ready is False

    with app.state.db.session() as db:
        rows = int(
            db.scalar(
                select(func.count())
                .select_from(RetrievalUnitIndex)
                .where(RetrievalUnitIndex.version_id == pending_version)
            )
            or 0
        )
        version = db.get(DocumentVersion, pending_version)
        assert rows == 0 and version.state == "deleted"
    assert _retrieve(app, QueryIntent("record", entity_filters={"item_id": "P01"})).kind == "none"


# ---------------------------------------------------------------- R18 FTS-only 残留拒发与恢复


def _fts_row_count(db, version):
    return int(
        db.scalar(
            text("SELECT count(*) FROM source_unit_fts WHERE version_id=:version"),
            {"version": str(version)},
        )
        or 0
    )


def _strip_non_fts_index_rows(db, version):
    """故障样本：删除 marker/映射/字段索引，只保留该版本的 FTS 行。"""
    db.execute(delete(RetrievalVersionIndex).where(RetrievalVersionIndex.version_id == version))
    db.execute(delete(RetrievalUnitIndex).where(RetrievalUnitIndex.version_id == version))
    db.execute(delete(RetrievalFieldIndex).where(RetrievalFieldIndex.version_id == version))
    db.commit()
    return _fts_row_count(db, version)


def test_r18_fts_only_residue_is_not_auto_repaired_on_publish(admin_write, app, monkeypatch):
    old, pub = _publish_ready(admin_write, app, path=D01, revision=0)
    pending = _upload(
        admin_write,
        path=V04,
        document_id=old["document"]["id"],
        expected_active=old["version"]["id"],
    )
    assert pending.status_code == 202, pending.text
    pending = pending.json()
    assert _run_worker(app).state == "succeeded"
    version = uuid.UUID(pending["version"]["id"])

    with app.state.db.session() as db:
        assert prepare_version_index(db, version).ready
        retained = _strip_non_fts_index_rows(db, version)
        assert retained > 0
        assert index_rows_present(db, version) is True
        assert db.get(RetrievalVersionIndex, version) is None
        assert int(
            db.scalar(
                select(func.count())
                .select_from(RetrievalUnitIndex)
                .where(RetrievalUnitIndex.version_id == version)
            )
            or 0
        ) == 0
        assert int(
            db.scalar(
                select(func.count())
                .select_from(RetrievalFieldIndex)
                .where(RetrievalFieldIndex.version_id == version)
            )
            or 0
        ) == 0

    before_detail = _detail(admin_write, old["document"]["id"])
    before_counts = _knowledge_counts(app)
    before_retrieval = _retrieve(
        app, QueryIntent("record", entity_filters={"item_id": "P01"}, requested_fields=("位置",))
    )
    assert before_retrieval.units[0].fields["位置"] == "B区1号货架第二层"

    import mktkb.documents.lifecycle as lifecycle_module

    calls = {"count": 0}
    original_prepare = lifecycle_module.prepare_version_index

    def counted_prepare(db, version_id):
        calls["count"] += 1
        return original_prepare(db, version_id)

    monkeypatch.setattr(lifecycle_module, "prepare_version_index", counted_prepare)

    refused = _publish(
        admin_write,
        old["document"]["id"],
        pending["version"]["id"],
        expected_active=old["version"]["id"],
        revision=pub["revision"],
    )
    assert refused.status_code == 409, refused.text
    assert refused.json()["error"]["code"] == "VERSION_NOT_PUBLISHABLE"
    assert calls["count"] == 0, "FTS-only 残留不得进入首次准备/自动重建"

    after_detail = _detail(admin_write, old["document"]["id"])
    assert after_detail["revision"] == before_detail["revision"]
    assert after_detail["document"]["active_version"]["id"] == before_detail["document"]["active_version"]["id"]
    assert _knowledge_counts(app) == before_counts
    kept = _retrieve(
        app, QueryIntent("record", entity_filters={"item_id": "P01"}, requested_fields=("位置",))
    )
    assert kept.units[0].fields["位置"] == "B区1号货架第二层"
    with app.state.db.session() as db:
        assert _fts_row_count(db, version) == retained
        assert db.get(RetrievalVersionIndex, version) is None
        assert int(
            db.scalar(
                select(func.count())
                .select_from(RetrievalUnitIndex)
                .where(RetrievalUnitIndex.version_id == version)
            )
            or 0
        ) == 0
        assert int(
            db.scalar(
                select(func.count())
                .select_from(RetrievalFieldIndex)
                .where(RetrievalFieldIndex.version_id == version)
            )
            or 0
        ) == 0

    # 其他资料仍可正常首次准备并发布（FTS-only 残留不得全局阻断）
    fresh = _upload(admin_write, path=V06)
    assert fresh.status_code == 202, fresh.text
    fresh = fresh.json()
    assert _run_worker(app).state == "succeeded"
    fresh_version = uuid.UUID(fresh["version"]["id"])
    with app.state.db.session() as db:
        assert index_rows_present(db, fresh_version) is False
        assert db.get(RetrievalVersionIndex, fresh_version) is None
    fresh_published = _publish(
        admin_write,
        fresh["document"]["id"],
        fresh["version"]["id"],
        expected_active=None,
        revision=_revision(app),
    )
    assert fresh_published.status_code == 200, fresh_published.text
    assert _retrieve(
        app, QueryIntent("record", entity_filters={"item_id": "P01"}, requested_fields=("位置",))
    ).units[0].fields["位置"] == "B区1号货架第二层"

    # 显式重建待发 V04 后才允许发布一次；重复发布幂等
    current = _revision(app)
    with app.state.db.session() as db:
        assert prepare_version_index(db, version).ready
        assert index_rows_present(db, version) is True
    recovered = _publish(
        admin_write,
        old["document"]["id"],
        pending["version"]["id"],
        expected_active=old["version"]["id"],
        revision=current,
    )
    assert recovered.status_code == 200, recovered.text
    assert recovered.json()["revision"] == current + 1
    repeat = _publish(
        admin_write,
        old["document"]["id"],
        pending["version"]["id"],
        expected_active=old["version"]["id"],
        revision=current,
    )
    assert repeat.status_code == 200, repeat.text
    assert repeat.json()["revision"] == recovered.json()["revision"]

    with app.state.db.session() as db:
        before_rows = (
            int(
                db.scalar(
                    select(func.count())
                    .select_from(RetrievalUnitIndex)
                    .where(RetrievalUnitIndex.version_id == version)
                )
                or 0
            ),
            int(
                db.scalar(
                    select(func.count())
                    .select_from(RetrievalFieldIndex)
                    .where(RetrievalFieldIndex.version_id == version)
                )
                or 0
            ),
        )
    statuses = None
    with app.state.db.session() as db:
        statuses = backfill_published_indexes(db)
    assert statuses and all(status.ready for status in statuses)
    with app.state.db.session() as db:
        after_rows = (
            int(
                db.scalar(
                    select(func.count())
                    .select_from(RetrievalUnitIndex)
                    .where(RetrievalUnitIndex.version_id == version)
                )
                or 0
            ),
            int(
                db.scalar(
                    select(func.count())
                    .select_from(RetrievalFieldIndex)
                    .where(RetrievalFieldIndex.version_id == version)
                )
                or 0
            ),
        )
    assert before_rows == after_rows
    assert _retrieve(
        app, QueryIntent("record", entity_filters={"item_id": "P01"}, requested_fields=("位置",))
    ).units[0].fields["位置"] == "D区暂存柜"


def test_r19_fts_residue_in_cancelled_version_does_not_block(admin_write, app):
    b0 = _b0(admin_write, app)
    pending = _upload(
        admin_write,
        path=V05,
        document_id=b0["positions"]["document"],
        expected_active=b0["positions"]["v2"],
    )
    assert pending.status_code == 202, pending.text
    pending = pending.json()
    assert _run_worker(app).state == "succeeded"
    version = uuid.UUID(pending["version"]["id"])
    with app.state.db.session() as db:
        assert prepare_version_index(db, version).ready
        cancel_version(db, uuid.UUID(b0["positions"]["document"]), version)
        retained = _strip_non_fts_index_rows(db, version)
        assert retained > 0
        assert index_rows_present(db, version) is True
        assert db.get(DocumentVersion, version).state == "cancelled"

    assert _retrieve(
        app, QueryIntent("record", entity_filters={"item_id": "P01"}, requested_fields=("位置",))
    ).units[0].fields["位置"] == "B区1号货架第二层"
    store = _retrieve(
        app, QueryIntent("record", entity_filters={"store": "城东店"}, requested_fields=("电话",))
    )
    assert store.units[0].fields["电话"] == "010-00000001"

    fresh = _upload(admin_write, path=V06)
    assert fresh.status_code == 202, fresh.text
    fresh = fresh.json()
    assert _run_worker(app).state == "succeeded"
    published = _publish(
        admin_write,
        fresh["document"]["id"],
        fresh["version"]["id"],
        expected_active=None,
        revision=_revision(app),
    )
    assert published.status_code == 200, published.text
    with app.state.db.session() as db:
        assert _fts_row_count(db, version) == retained
    assert _retrieve(
        app, QueryIntent("record", entity_filters={"item_id": "P01"}, requested_fields=("位置",))
    ).units[0].fields["位置"] == "B区1号货架第二层"


# ---------------------------------------------------------------- R20 FTS 结构故障


def test_r20_fts_structure_failure_is_not_treated_as_empty(admin_write, app):
    old, pub = _publish_ready(admin_write, app, path=D01, revision=0)
    pending = _upload(
        admin_write,
        path=V04,
        document_id=old["document"]["id"],
        expected_active=old["version"]["id"],
    )
    assert pending.status_code == 202, pending.text
    pending = pending.json()
    assert _run_worker(app).state == "succeeded"
    version = uuid.UUID(pending["version"]["id"])
    with app.state.db.session() as db:
        assert db.get(RetrievalVersionIndex, version) is None
        db.execute(text("DROP TABLE source_unit_fts"))
        db.commit()

    before_detail = _detail(admin_write, old["document"]["id"])
    before_counts = _knowledge_counts(app)
    refused = _publish(
        admin_write,
        old["document"]["id"],
        pending["version"]["id"],
        expected_active=old["version"]["id"],
        revision=pub["revision"],
    )
    assert refused.status_code == 409, refused.text
    assert refused.json()["error"]["code"] == "VERSION_NOT_PUBLISHABLE"
    after_detail = _detail(admin_write, old["document"]["id"])
    assert after_detail["revision"] == before_detail["revision"]
    assert after_detail["document"]["active_version"]["id"] == before_detail["document"]["active_version"]["id"]
    assert _knowledge_counts(app) == before_counts
    with app.state.db.session() as db:
        assert db.get(RetrievalVersionIndex, version) is None
        assert int(
            db.scalar(
                select(func.count())
                .select_from(RetrievalUnitIndex)
                .where(RetrievalUnitIndex.version_id == version)
            )
            or 0
        ) == 0

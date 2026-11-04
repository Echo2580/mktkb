"""T10-PRE 索引核验加速（进程内已核验状态复用）集成检查。

全部用例都用真实 HTTP 上传、真实 worker 与管理员发布建立可见版本，再在真实 SQLite 上验证：

- 重复问答命中已核验状态：不再重建核验计划、不再逐行完整核验，结果不变；
- 生命周期变化（发布新版本 / 删除 / 取消未生效版本）后结论仍然正确；
- **缓存命中之后**底层索引行被删除、改写、新增时仍必须返回 `INDEX_NOT_READY`；
- 来源摘要变化（版本 sha256 / 单元正文）在缓存命中后被检出；
- 3 线程并发问答结果一致、无异常。

只新增测试文件；不修改既有断言语义，也不依赖题号/文件名/期望值分支。
"""

from __future__ import annotations

import threading
import time
import uuid
from pathlib import Path

import pytest
from sqlalchemy import delete, select, text, update

import mktkb.retrieval.index as index_module
from mktkb.documents.lifecycle import cancel_version, get_revision, prepare_version_index
from mktkb.documents.models import DocumentVersion, SourceUnit
from mktkb.ingestion.worker import run_one_job
from mktkb.retrieval import verify_cache
from mktkb.retrieval.models import RetrievalFieldIndex, RetrievalUnitIndex, RetrievalVersionIndex
from mktkb.retrieval.service import retrieve
from mktkb.retrieval.types import IndexNotReady, QueryIntent

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "fixtures" / "acceptance"
D01 = FIXTURES / "normal" / "D01_物品位置表.xlsx"
D02 = FIXTURES / "normal" / "D02_合作店家信息.xlsx"
V04 = FIXTURES / "variants" / "V04_物品位置表_新版V3.xlsx"

POSITION_INTENT = QueryIntent("record", entity_filters={"item_id": "P01"}, requested_fields=("位置",))
PHONE_INTENT = QueryIntent("record", entity_filters={"store": "城东店"}, requested_fields=("电话",))
DOCUMENT_INTENT = QueryIntent("document", terms=("宣传海报",))


# ---------------------------------------------------------------- 辅助（与既有集成检查同口径）


def _session(app):
    return app.state.db.session()


def _run_worker(app):
    db = _session(app)
    try:
        return run_one_job(db, app.state.store)
    finally:
        db.close()


def _upload(admin_write, *, path=None, document_id=None, expected_active=None):
    return admin_write.upload(
        path=path,
        name=Path(path).name if path else None,
        document_id=document_id,
        expected_active_version_id=expected_active,
    )


def _publish(admin_write, document_id, version_id, *, expected_active, revision):
    return admin_write.client.post(
        f"/api/v1/documents/{document_id}/versions/{version_id}/publish",
        headers=admin_write.headers,
        json={"expected_active_version_id": expected_active, "expected_revision": revision},
    )


def _publish_ready(admin_write, app, *, path=None, document_id=None, expected_active=None, revision=0):
    receipt = _upload(admin_write, path=path, document_id=document_id, expected_active=expected_active)
    assert receipt.status_code == 202, receipt.text
    record = receipt.json()
    assert _run_worker(app).state == "succeeded"
    published = _publish(
        admin_write,
        record["document"]["id"],
        record["version"]["id"],
        expected_active=expected_active,
        revision=revision,
    )
    assert published.status_code == 200, published.text
    return record, published.json()


def _retrieve(app, intent):
    db = _session(app)
    try:
        return retrieve(db, intent, revision=get_revision(db), limit=20)
    finally:
        db.close()


def _unique_position_unit(db, version_id):
    units = db.scalars(select(SourceUnit).where(SourceUnit.version_id == version_id)).all()
    return next(item for item in units if item.fields.get("标识") == "P01")


def _positions(result):
    return [unit.fields.get("位置") for unit in result.units]


@pytest.fixture
def full_verifications(monkeypatch):
    """记录实际进入完整核验的版本（证明命中路径没有重复核验）。"""
    calls: list[str] = []
    original = verify_cache.verify_version_index

    def counting(db, version, **kwargs):
        calls.append(str(version.id))
        return original(db, version, **kwargs)

    monkeypatch.setattr(verify_cache, "verify_version_index", counting)
    return calls


# ---------------------------------------------------------------- 1. 重复问答命中


def test_repeated_question_reuses_verified_state(admin_write, app, full_verifications, monkeypatch):
    """首问完整核验一次；同 revision 的后续问答命中，不再重建核验计划/逐行核验。"""
    _publish_ready(admin_write, app, path=D01, revision=0)
    plan_calls: list[str] = []
    original_build = index_module.build_index_plan

    def counting_build(db, version):
        plan_calls.append(str(getattr(version, "id", version)))
        return original_build(db, version)

    monkeypatch.setattr(index_module, "build_index_plan", counting_build)
    stats_before = verify_cache.verification_stats()
    first = _retrieve(app, POSITION_INTENT)
    assert _positions(first) == ["B区1号货架第二层"]
    assert len(full_verifications) == 1
    builds_after_first = len(plan_calls)
    assert builds_after_first == 1
    stats_after_first = verify_cache.verification_stats()
    assert stats_after_first["fingerprint_misses"] == stats_before["fingerprint_misses"] + 1

    second = _retrieve(app, POSITION_INTENT)
    assert _positions(second) == ["B区1号货架第二层"]
    assert sorted(str(unit.id) for unit in second.units) == sorted(str(unit.id) for unit in first.units)
    assert len(full_verifications) == 1, full_verifications
    assert len(plan_calls) == builds_after_first, "命中路径不得重建核验计划"
    stats_after_second = verify_cache.verification_stats()
    assert stats_after_second["fingerprint_hits"] == stats_after_first["fingerprint_hits"] + 1
    assert stats_after_second["fingerprint_misses"] == stats_after_first["fingerprint_misses"]


def test_cache_hit_avoids_full_verification_cost(admin_write, app, monkeypatch):
    """给完整核验注入固定延迟：命中路径不得包含该延迟（可复现的加速证据）。"""
    _publish_ready(admin_write, app, path=D01, revision=0)
    original = verify_cache.verify_version_index
    delay_seconds = 0.25

    def slow(db, version, **kwargs):
        time.sleep(delay_seconds)
        return original(db, version, **kwargs)

    monkeypatch.setattr(verify_cache, "verify_version_index", slow)
    started = time.perf_counter()
    first = _retrieve(app, POSITION_INTENT)
    first_seconds = time.perf_counter() - started
    started = time.perf_counter()
    second = _retrieve(app, POSITION_INTENT)
    second_seconds = time.perf_counter() - started
    assert first.units and second.units
    assert first_seconds >= delay_seconds, first_seconds
    assert second_seconds < delay_seconds, (first_seconds, second_seconds)


# ---------------------------------------------------------------- 2. 生命周期变化后重新核验


def test_publish_new_version_reverifies_new_visible_version(admin_write, app, full_verifications):
    old, publication = _publish_ready(admin_write, app, path=D01, revision=0)
    first = _retrieve(app, POSITION_INTENT)
    assert _positions(first) == ["B区1号货架第二层"]
    assert len(full_verifications) == 1

    receipt = _upload(
        admin_write,
        path=V04,
        document_id=old["document"]["id"],
        expected_active=old["version"]["id"],
    )
    assert receipt.status_code == 202, receipt.text
    desired = receipt.json()
    assert _run_worker(app).state == "succeeded"
    published = _publish(
        admin_write,
        old["document"]["id"],
        desired["version"]["id"],
        expected_active=old["version"]["id"],
        revision=publication["revision"],
    )
    assert published.status_code == 200, published.text
    assert published.json()["revision"] == publication["revision"] + 1

    refreshed = _retrieve(app, POSITION_INTENT)
    assert _positions(refreshed) == ["D区暂存柜"]
    assert {str(unit.version_id) for unit in refreshed.units} == {desired["version"]["id"]}
    assert desired["version"]["id"] in full_verifications, "新可见版本必须重新完整核验"


def test_delete_document_reverifies_remaining_versions(admin_write, app, full_verifications):
    positions, first_publication = _publish_ready(admin_write, app, path=D01, revision=0)
    stores, second_publication = _publish_ready(
        admin_write, app, path=D02, revision=first_publication["revision"]
    )
    _retrieve(app, POSITION_INTENT)
    _retrieve(app, PHONE_INTENT)
    calls_before = list(full_verifications)

    deleted = admin_write.client.delete(
        f'/api/v1/documents/{stores["document"]["id"]}',
        params={"expected_revision": second_publication["revision"]},
        headers=admin_write.headers,
    )
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["revision"] == second_publication["revision"] + 1

    kept = _retrieve(app, POSITION_INTENT)
    assert _positions(kept) == ["B区1号货架第二层"]
    new_calls = full_verifications[len(calls_before):]
    assert positions["version"]["id"] in new_calls, "删除后 revision 变化必须重新完整核验剩余版本"
    assert stores["version"]["id"] not in new_calls, "已删除版本不参与核验"

    phone = _retrieve(app, PHONE_INTENT)
    assert stores["version"]["id"] not in {str(unit.version_id) for unit in phone.units}


def test_cancel_pending_version_keeps_visible_state_verified(admin_write, app, full_verifications):
    """取消未生效版本不改变 revision 与可见索引；缓存结论仍正确、不得出现陈旧错误。"""
    old, publication = _publish_ready(admin_write, app, path=D01, revision=0)
    _retrieve(app, POSITION_INTENT)
    assert len(full_verifications) == 1

    receipt = _upload(
        admin_write,
        path=V04,
        document_id=old["document"]["id"],
        expected_active=old["version"]["id"],
    )
    assert receipt.status_code == 202, receipt.text
    pending = receipt.json()
    assert _run_worker(app).state == "succeeded"
    db = _session(app)
    try:
        assert get_revision(db) == publication["revision"]
    finally:
        db.close()

    db = _session(app)
    try:
        cancel_version(db, uuid.UUID(old["document"]["id"]), uuid.UUID(pending["version"]["id"]))
    finally:
        db.close()
    with app.state.db.session() as db:
        assert db.get(DocumentVersion, uuid.UUID(pending["version"]["id"])).state == "cancelled"
        assert get_revision(db) == publication["revision"]

    calls_before = list(full_verifications)
    result = _retrieve(app, POSITION_INTENT)
    assert _positions(result) == ["B区1号货架第二层"]
    assert full_verifications == calls_before, "可见索引状态未变化时应命中已核验状态"


# ---------------------------------------------------------------- 3. 命中后仍能检出底层索引损坏


@pytest.mark.parametrize(
    "damage",
    [
        "marker_row",
        "mapping_row",
        "field_rows",
        "field_content",
        "fts_content",
        "fts_extra",
        "field_extra",
    ],
)
def test_cached_state_still_detects_index_damage(admin_write, app, full_verifications, damage):
    record, _publication = _publish_ready(admin_write, app, path=D01, revision=0)
    version = uuid.UUID(record["version"]["id"])
    _retrieve(app, POSITION_INTENT)
    _retrieve(app, POSITION_INTENT)
    assert len(full_verifications) == 1, "前置：第二次问答已命中已核验状态"

    with app.state.db.session() as db:
        unit = _unique_position_unit(db, version)
        mapping = db.scalar(select(RetrievalUnitIndex).where(RetrievalUnitIndex.unit_id == unit.id))
        assert mapping is not None
        if damage == "marker_row":
            db.execute(
                delete(RetrievalVersionIndex).where(RetrievalVersionIndex.version_id == version)
            )
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
        elif damage == "fts_content":
            db.execute(
                text("UPDATE source_unit_fts SET body = :body WHERE rowid = :rowid"),
                {"body": "被改写的正文", "rowid": mapping.fts_rowid},
            )
        elif damage == "fts_extra":
            max_rowid = int(db.scalar(text("SELECT COALESCE(MAX(rowid), 0) FROM source_unit_fts")) or 0)
            db.execute(
                text("INSERT INTO source_unit_fts(rowid, body, version_id) VALUES (:rowid, :body, :version)"),
                {"rowid": max_rowid + 1000, "body": "额外正文", "version": str(version)},
            )
        else:
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
        db.commit()

    for intent in (POSITION_INTENT, DOCUMENT_INTENT):
        with pytest.raises(IndexNotReady):
            _retrieve(app, intent)

    with app.state.db.session() as db:
        assert prepare_version_index(db, version).ready
    recovered = _retrieve(app, POSITION_INTENT)
    assert _positions(recovered) == ["B区1号货架第二层"]


@pytest.mark.parametrize("change", ["version_sha", "unit_text"])
def test_cached_state_still_detects_source_digest_change(admin_write, app, full_verifications, change):
    record, _publication = _publish_ready(admin_write, app, path=D01, revision=0)
    version = uuid.UUID(record["version"]["id"])
    _retrieve(app, POSITION_INTENT)
    _retrieve(app, POSITION_INTENT)
    assert len(full_verifications) == 1

    with app.state.db.session() as db:
        if change == "version_sha":
            db.execute(
                update(DocumentVersion).where(DocumentVersion.id == version).values(sha256="0" * 64)
            )
        else:
            unit = _unique_position_unit(db, version)
            db.execute(
                update(SourceUnit).where(SourceUnit.id == unit.id).values(text=unit.text + "（被追加）")
            )
        db.commit()

    with pytest.raises(IndexNotReady):
        _retrieve(app, POSITION_INTENT)


# ---------------------------------------------------------------- 4. 并发一致性


def test_three_concurrent_questions_share_cache_without_corruption(admin_write, app):
    _publish_ready(admin_write, app, path=D01, revision=0)
    _publish_ready(admin_write, app, path=D02, revision=1)
    _retrieve(app, POSITION_INTENT)
    hits_before = verify_cache.verification_stats()["fingerprint_hits"]

    expected = ("matches", ("B区1号货架第二层",))
    errors: list[str] = []
    outcomes: list[tuple] = []
    lock = threading.Lock()
    barrier = threading.Barrier(3)

    def worker() -> None:
        try:
            barrier.wait(timeout=15)
        except threading.BrokenBarrierError:
            pass
        for _ in range(3):
            try:
                result = _retrieve(app, POSITION_INTENT)
                with lock:
                    outcomes.append((result.kind, tuple(_positions(result))))
            except BaseException as exc:  # noqa: BLE001 - 原样记录给断言
                with lock:
                    errors.append(f"{type(exc).__name__}: {exc}")

    threads = [threading.Thread(target=worker, name=f"t10pre-concurrent-{index}") for index in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert all(not thread.is_alive() for thread in threads)
    assert not errors, errors
    assert len(outcomes) == 9, outcomes
    assert all(outcome == expected for outcome in outcomes), outcomes
    stats = verify_cache.verification_stats()
    assert stats["fingerprint_hits"] >= hits_before + 6

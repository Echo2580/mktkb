"""T09-D1 / 交付物 2：U01～U10 更新与删除回归（每例独立数据库 + 独立文件目录，从 B0 快照恢复）。

口径：每例都用 B0 快照恢复出**全新**的数据目录与 SQLite（不共享任何运行状态），再按
``questions.json`` 中该例的 ``scenario.actions`` / ``events`` / ``assertions`` 执行。
10 项全部通过才算本交付物通过；失败原样保留，不改阈值、不 skip。
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

from mktkb.ingestion.worker import claim_job

from support import b0, evidence
from support.netguard import t09_network_guard  # noqa: F401 - 模块级 fixture

pytestmark = pytest.mark.usefixtures("t09_network_guard")

QUESTIONS = {item["id"]: item for item in evidence.load_questions() if item["group"] == "mutation"}
MUTATION_IDS = [f"U{index:02d}" for index in range(1, 11)]


@pytest.fixture(scope="module")
def environment_facts():
    return evidence.environment()


@pytest.fixture(scope="module")
def b0_snapshot(tmp_path_factory, environment_facts):
    """只建立一次 B0，随后各例从快照恢复（每例仍是独立数据库与独立文件目录）。"""
    work = tmp_path_factory.mktemp("t09-mutation")
    build_dir = work / "build"
    live = b0.build_b0(build_dir)
    facts = b0.b0_facts(live)
    invariants = b0.assert_b0_invariants(live)
    b0.checkpoint_and_dispose(live.harness)
    snapshot = b0.snapshot_b0(build_dir, work / "snapshot")
    yield {
        "work": work,
        "snapshot": snapshot,
        "facts": facts,
        "invariants": invariants,
        "environment": environment_facts,
    }
    live.harness.close()


@pytest.fixture
def restored(b0_snapshot, request):
    """为一例恢复独立数据目录；用例结束关闭数据库连接（不删除证据）。"""
    name = request.node.name
    dest = b0_snapshot["work"] / f"case-{name}"
    harness = b0.restore_b0(b0_snapshot["snapshot"], dest)
    harness.data_dir_restored = str(dest)  # 便于证据记录
    try:
        yield harness
    finally:
        harness.close()


def _upload_version(harness, admin, file_id: str, document_id) -> dict:
    detail = harness.detail(document_id)
    active = detail["document"]["active_version"]
    response = admin.upload(
        path=b0.fixture_path(file_id),
        document_id=document_id,
        expected_active_version_id=active["id"] if active else None,
    )
    assert response.status_code == 202, response.text
    return response.json()


def _process(harness, file_id: str):
    if file_id in b0.ocr_transcripts.OCR_BINDINGS:
        harness.ocr.bind(file_id)
    else:
        harness.ocr.unbind()
    result = harness.run_job()
    harness.ocr.unbind()
    assert result.state == "succeeded", result
    return result


def _publish(harness, admin, document_id, version_id, *, expected_active, expected_revision):
    return admin.client.post(
        f"/api/v1/documents/{document_id}/versions/{version_id}/publish",
        json={"expected_active_version_id": expected_active, "expected_revision": expected_revision},
        headers=admin.headers,
    )


def _ask(harness, conversation, question: str):
    employee = harness.employee()
    return employee, b0.ask(employee, conversation, question)


def _dump(item_id: str, payload: dict) -> None:
    evidence.dump_json(f"actual/mutation/{item_id}.json", payload)


def _context(harness, item: dict, payload: dict) -> dict:
    return {
        "id": item["id"],
        "question": item["question"],
        "group": item["group"],
        "provider": evidence.PROVIDER_TAG,
        "environment": payload.pop("environment"),
        "restored_data_dir": harness.data_dir_restored,
        "actions": item["scenario"].get("actions", []),
        "assertions": item["scenario"].get("assertions", []),
        "events": item["scenario"].get("events", []),
    }


# ---------------------------------------------------------------- U01


def test_u01_unpublished_new_version_keeps_old_answer(restored, b0_snapshot):
    harness = restored
    admin = harness.admin()
    positions = b0_snapshot["facts"]["slots"]["doc-positions"]
    record = _upload_version(harness, admin, "V04", positions)
    _process(harness, "V04")
    detail = harness.detail(positions)
    assert detail["document"]["active_version"]["number"] == 2, "未发布的新版不得改变有效版本"

    employee = harness.employee()
    conversation = b0.new_conversation(employee, "T09-U01")
    response = b0.ask(employee, conversation, QUESTIONS["U01"]["question"])
    graded = b0.evaluate(QUESTIONS["U01"], response, environment=b0_snapshot["environment"])
    payload = _context(harness, QUESTIONS["U01"], {"environment": b0_snapshot["environment"]})
    payload.update(
        {
            "graded": graded,
            "new_version": {"version": record["version"]["id"], "state": record["version"]["state"]},
            "active_version_number": detail["document"]["active_version"]["number"],
            "revision": detail["revision"],
        }
    )
    _dump("U01", payload)
    assert graded["status"] == "pass", graded["problems"]
    assert "B区1号货架第二层" in graded["actual"]["text"]
    assert "D区暂存柜" not in graded["actual"]["text"]


# ---------------------------------------------------------------- U02


def test_u02_publish_switches_answer_in_new_and_existing_conversation(restored, b0_snapshot):
    harness = restored
    admin = harness.admin()
    positions = b0_snapshot["facts"]["slots"]["doc-positions"]
    old = harness.detail(positions)
    record = _upload_version(harness, admin, "V04", positions)
    _process(harness, "V04")

    employee = harness.employee()
    existing = b0.new_conversation(employee, "T09-U02-existing")
    first = b0.ask(employee, existing, "城东店的宣传海报在哪里？")
    assert first.status_code == 200 and first.json()["kind"] == "answer", first.text
    assert "B区1号货架第二层" in first.json()["text"]

    published = _publish(
        harness,
        admin,
        positions,
        record["version"]["id"],
        expected_active=old["document"]["active_version"]["id"],
        expected_revision=old["revision"],
    )
    assert published.status_code == 200, published.text

    fresh = b0.new_conversation(employee, "T09-U02-fresh")
    new_answer = b0.ask(employee, fresh, QUESTIONS["U02"]["question"])
    followup = b0.ask(employee, existing, QUESTIONS["U02"]["question"])

    graded_new = b0.evaluate(
        QUESTIONS["U02"],
        new_answer,
        environment=b0_snapshot["environment"],
        source_hints={"V04": b0.source_hint("V04", record)},
    )
    graded_follow = b0.evaluate(
        QUESTIONS["U02"],
        followup,
        environment=b0_snapshot["environment"],
        source_hints={"V04": b0.source_hint("V04", record)},
    )
    _dump(
        "U02",
        {
            **_context(harness, QUESTIONS["U02"], {"environment": b0_snapshot["environment"]}),
            "graded_new_conversation": graded_new,
            "graded_existing_conversation": graded_follow,
            "publication": published.json(),
            "before_publish_text": first.json()["text"],
        },
    )
    assert graded_new["status"] == "pass", graded_new["problems"]
    assert graded_follow["status"] == "pass", graded_follow["problems"]
    assert "D区暂存柜" in graded_new["actual"]["text"]
    assert "D区暂存柜" in graded_follow["actual"]["text"]


# ---------------------------------------------------------------- U03


def test_u03_phone_update_returns_new_value(restored, b0_snapshot):
    harness = restored
    admin = harness.admin()
    stores = b0_snapshot["facts"]["slots"]["doc-stores"]
    detail = harness.detail(stores)
    record = _upload_version(harness, admin, "V06", stores)
    _process(harness, "V06")
    published = _publish(
        harness,
        admin,
        stores,
        record["version"]["id"],
        expected_active=detail["document"]["active_version"]["id"],
        expected_revision=detail["revision"],
    )
    assert published.status_code == 200, published.text

    employee = harness.employee()
    conversation = b0.new_conversation(employee, "T09-U03")
    response = b0.ask(employee, conversation, QUESTIONS["U03"]["question"])
    graded = b0.evaluate(
        QUESTIONS["U03"],
        response,
        environment=b0_snapshot["environment"],
        source_hints={"V06": b0.source_hint("V06", record)},
    )
    text_value = graded["actual"]["text"] if "actual" in graded else ""
    _dump(
        "U03",
        {
            **_context(harness, QUESTIONS["U03"], {"environment": b0_snapshot["environment"]}),
            "graded": graded,
            "publication": published.json(),
        },
    )
    assert graded["status"] == "pass", graded["problems"]
    assert "010-00000088" in text_value
    assert "010-00000001" not in text_value, "不得混入旧电话"
    sources = graded["actual"]["sources"]
    assert all(source["document_name"] == record["document"]["name"] for source in sources), sources
    for source in sources:
        assert source["version_number"] == 2, source
    assert "模拟联系人·陈宁" in text_value, "未变更的联系人字段应随新版本原值回显"


# ---------------------------------------------------------------- U04


def test_u04_removed_row_is_not_answerable(restored, b0_snapshot):
    harness = restored
    admin = harness.admin()
    positions = b0_snapshot["facts"]["slots"]["doc-positions"]
    detail = harness.detail(positions)
    record = _upload_version(harness, admin, "V05", positions)
    _process(harness, "V05")
    published = _publish(
        harness,
        admin,
        positions,
        record["version"]["id"],
        expected_active=detail["document"]["active_version"]["id"],
        expected_revision=detail["revision"],
    )
    assert published.status_code == 200, published.text

    employee = harness.employee()
    conversation = b0.new_conversation(employee, "T09-U04")
    response = b0.ask(employee, conversation, QUESTIONS["U04"]["question"])
    graded = b0.evaluate(QUESTIONS["U04"], response, environment=b0_snapshot["environment"])
    _dump(
        "U04",
        {
            **_context(harness, QUESTIONS["U04"], {"environment": b0_snapshot["environment"]}),
            "graded": graded,
            "publication": published.json(),
        },
    )
    assert graded["status"] == "pass", graded["problems"]
    assert "B区1号货架第二层" not in graded["actual"]["text"], "删行后不得从旧索引返回旧位置"
    # 旧版本内容仍只作为历史版本存在，不再是有效来源
    versions = harness.detail(positions)["versions"]
    assert [item["state"] for item in versions] == ["superseded", "superseded", "published"], versions


# ---------------------------------------------------------------- U05


def test_u05_delete_only_source_of_store(restored, b0_snapshot):
    harness = restored
    admin = harness.admin()
    stores = b0_snapshot["facts"]["slots"]["doc-stores"]
    employee = harness.employee()
    conversation = b0.new_conversation(employee, "T09-U05")
    before = b0.ask(employee, conversation, "滨河店的联系人是谁？")
    assert before.status_code == 200 and before.json()["kind"] == "answer", before.text
    before_payload = before.json()
    source_id = before_payload["sources"][0]["source_id"]

    detail = harness.detail(stores)
    deleted = admin.client.delete(
        f"/api/v1/documents/{stores}",
        params={"expected_revision": detail["revision"]},
        headers=admin.headers,
    )
    assert deleted.status_code == 200, deleted.text

    after = b0.ask(employee, conversation, QUESTIONS["U05"]["question"])
    graded = b0.evaluate(QUESTIONS["U05"], after, environment=b0_snapshot["environment"])
    history = b0.messages(employee, conversation)
    old_source = employee.client.get(f"/api/v1/messages/{before_payload['message_id']}/sources/{source_id}")
    old_file = employee.client.get(f"/api/v1/messages/{before_payload['message_id']}/sources/{source_id}/file")
    _dump(
        "U05",
        {
            **_context(harness, QUESTIONS["U05"], {"environment": b0_snapshot["environment"]}),
            "graded": graded,
            "history": history,
            "old_source_status": old_source.status_code,
            "old_source_error": old_source.json() if old_source.status_code != 200 else None,
            "old_file_status": old_file.status_code,
        },
    )
    assert graded["status"] == "pass", graded["problems"]
    assert graded["actual"]["sources"] == [], "删除后新问题不得再引用该店来源"
    assert "模拟联系人·周安" not in graded["actual"]["text"]
    # 历史答案保留
    assert any(item["role"] == "assistant" and item["kind"] == "answer" for item in history["items"])
    # 旧来源内容与原件不可访问
    assert old_source.status_code == 410, old_source.text
    assert old_source.json()["error"]["code"] == "SOURCE_UNAVAILABLE"
    assert old_file.status_code == 410, old_file.text
    assert "010-00000004" not in json.dumps(old_source.json(), ensure_ascii=False)


# ---------------------------------------------------------------- U06


def test_u06_delete_d01_but_remaining_notice_still_answers(restored, b0_snapshot):
    harness = restored
    admin = harness.admin()
    positions = b0_snapshot["facts"]["slots"]["doc-positions"]

    notice = admin.upload(path=b0.fixture_path("V07"), allow_same_name=False)
    assert notice.status_code == 202, notice.text
    notice_payload = notice.json()
    _process(harness, "V07")
    detail = harness.detail(notice_payload["document"]["id"])
    published = _publish(
        harness,
        admin,
        notice_payload["document"]["id"],
        notice_payload["version"]["id"],
        expected_active=None,
        expected_revision=detail["revision"],
    )
    assert published.status_code == 200, published.text

    positions_detail = harness.detail(positions)
    deleted = admin.client.delete(
        f"/api/v1/documents/{positions}",
        params={"expected_revision": positions_detail["revision"]},
        headers=admin.headers,
    )
    assert deleted.status_code == 200, deleted.text

    employee = harness.employee()
    conversation = b0.new_conversation(employee, "T09-U06")
    response = b0.ask(employee, conversation, QUESTIONS["U06"]["question"])
    graded = b0.evaluate(QUESTIONS["U06"], response, environment=b0_snapshot["environment"])
    _dump(
        "U06",
        {
            **_context(harness, QUESTIONS["U06"], {"environment": b0_snapshot["environment"]}),
            "graded": graded,
            "publication": published.json(),
        },
    )
    assert graded["status"] == "pass", graded["problems"]
    names = [source["document_name"] for source in graded["actual"]["sources"]]
    assert all(not name.startswith("V03") for name in names), f"来源不得指向已删除的 D01：{names}"


# ---------------------------------------------------------------- U07


def _ask_in_thread(harness, employee, conversation, question):
    holder: dict = {}

    def worker():
        try:
            holder["response"] = b0.ask(employee, conversation, question)
        except Exception as exc:  # 线程内异常显式带回
            holder["error"] = exc

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    return thread, holder


@pytest.mark.parametrize("variant", ["publish", "delete"])
def test_u07_knowledge_changed_when_knowledge_moves_during_generation(restored, b0_snapshot, variant):
    harness = restored
    admin = harness.admin()
    positions = b0_snapshot["facts"]["slots"]["doc-positions"]
    scenario = next(
        item for item in QUESTIONS["U07"]["scenario"]["sub_scenarios"] if item["variant"] == variant
    )
    candidate = {}
    if variant == "publish":
        record = _upload_version(harness, admin, "V04", positions)
        _process(harness, "V04")
        candidate = {"version": record["version"]["id"], "state": record["version"]["state"]}

    employee = harness.employee()
    conversation = b0.new_conversation(employee, f"T09-U07-{variant}")
    gateway = harness.model
    gateway.entered = threading.Event()
    gateway.block_after_entry = threading.Event()

    thread, holder = _ask_in_thread(harness, employee, conversation, "城东店的宣传海报在哪里？")
    assert gateway.entered.wait(15), "模型调用未进入屏障"

    detail = harness.detail(positions)
    if variant == "publish":
        changed = _publish(
            harness,
            admin,
            positions,
            candidate["version"],
            expected_active=detail["document"]["active_version"]["id"],
            expected_revision=detail["revision"],
        )
        assert changed.status_code == 200, changed.text
    else:
        changed = admin.client.delete(
            f"/api/v1/documents/{positions}",
            params={"expected_revision": detail["revision"]},
            headers=admin.headers,
        )
        assert changed.status_code == 200, changed.text
    revision_after_change = harness.revision()

    gateway.block_after_entry.set()
    thread.join(30)
    assert not thread.is_alive()
    assert "error" not in holder, holder.get("error")
    response = holder["response"]
    payload = response.json()
    # U07 是事件型子场景：期望值定义在 sub_scenario.expected（外层 scenario 没有 expected_kind），
    # 因此用事件判分而不是问答 evaluate()，避免证据内层 graded.status 伪报 fail。
    graded = b0.evaluate_event(scenario, response, environment=b0_snapshot["environment"])
    history = b0.messages(employee, conversation)
    _dump(
        f"U07-{variant}",
        {
            **_context(harness, QUESTIONS["U07"], {"environment": b0_snapshot["environment"]}),
            "variant": variant,
            "sub_scenario": scenario,
            "graded": graded,
            "history": history,
            "candidate": candidate,
            "revision_after_change": revision_after_change,
        },
    )
    assert graded["status"] == "pass", graded["problems"]
    assert response.status_code == 200, response.text
    assert payload["kind"] == "knowledge_changed", payload
    assert payload["sources"] == [], payload
    assert "B区1号货架第二层" not in payload["text"]
    assert "D区暂存柜" not in payload["text"]
    assistant = [item for item in history["items"] if item["role"] == "assistant"]
    assert len(assistant) == 1 and assistant[0]["kind"] == "knowledge_changed"
    assert assistant[0]["sources"] == [], "待发旧事实不得保存"


# ---------------------------------------------------------------- U08


def test_u08_concurrent_publish_from_same_old_version(restored, b0_snapshot):
    harness = restored
    admin = harness.admin()
    positions = b0_snapshot["facts"]["slots"]["doc-positions"]
    detail = harness.detail(positions)
    captured_active = detail["document"]["active_version"]["id"]
    captured_revision = detail["revision"]

    first = _upload_version(harness, admin, "V04", positions)
    _process(harness, "V04")
    second = _upload_version(harness, admin, "V05", positions)
    _process(harness, "V05")

    success = _publish(
        harness,
        admin,
        positions,
        first["version"]["id"],
        expected_active=captured_active,
        expected_revision=captured_revision,
    )
    conflict = _publish(
        harness,
        admin,
        positions,
        second["version"]["id"],
        expected_active=captured_active,
        expected_revision=captured_revision,
    )
    revision_after = harness.revision()
    active_after = harness.detail(positions)["document"]["active_version"]

    # 幂等子检查：**原样重放** U08a 的发布请求（同一 expected_active_version_id + expected_revision）；
    # 若实现保留发布凭据，应返回原成功结果且不重复递增 revision，而不是冲突。
    idempotent = _publish(
        harness,
        admin,
        positions,
        first["version"]["id"],
        expected_active=captured_active,
        expected_revision=captured_revision,
    )
    _dump(
        "U08",
        {
            **_context(harness, QUESTIONS["U08"], {"environment": b0_snapshot["environment"]}),
            "captured": {"active_version_id": captured_active, "revision": captured_revision},
            "success": {"status": success.status_code, "body": success.json() if success.status_code == 200 else success.text},
            "conflict": {"status": conflict.status_code, "body": conflict.json() if conflict.text else None},
            "revision_before": captured_revision,
            "revision_after": revision_after,
            "active_after": {"id": active_after["id"], "number": active_after["number"]},
            "idempotent": {"status": idempotent.status_code, "body": idempotent.json() if idempotent.status_code == 200 else idempotent.text},
        },
    )
    assert success.status_code == 200, success.text
    assert conflict.status_code == 409, conflict.text
    assert conflict.json()["error"]["code"] == "PUBLISH_CONFLICT", conflict.json()
    assert revision_after == captured_revision + 1, "revision 只递增一次"
    assert active_after["id"] == first["version"]["id"], "有效版本不得倒序切换到另一个候选"
    assert idempotent.status_code == 200, idempotent.text
    assert idempotent.json()["revision"] == revision_after, "幂等重复发布不得再递增 revision"


# ---------------------------------------------------------------- U09


def _job_row(harness, job_id):
    from mktkb.ingestion.models import ImportJob
    import uuid as uuid_module

    db = harness.session()
    try:
        return db.get(ImportJob, uuid_module.UUID(str(job_id)))
    finally:
        db.close()


def _unit_count(harness, version_id) -> int:
    from sqlalchemy import func, select

    from mktkb.documents.models import SourceUnit
    import uuid as uuid_module

    db = harness.session()
    try:
        return int(
            db.scalar(
                select(func.count())
                .select_from(SourceUnit)
                .where(SourceUnit.version_id == uuid_module.UUID(str(version_id)))
            )
            or 0
        )
    finally:
        db.close()


def _ocr_records(harness, version_id) -> list[dict]:
    from mktkb.ingestion.models import OCRCallRecord
    from sqlalchemy import select
    import uuid as uuid_module

    db = harness.session()
    try:
        rows = db.scalars(
            select(OCRCallRecord)
            .where(OCRCallRecord.version_id == uuid_module.UUID(str(version_id)))
            .order_by(OCRCallRecord.created_at, OCRCallRecord.attempt)
        ).all()
        return [{"state": row.state, "page": row.page, "attempt": row.attempt, "has_result": row.result is not None} for row in rows]
    finally:
        db.close()


def _start_worker(harness, **kwargs):
    holder: dict = {}

    def worker():
        try:
            holder["result"] = harness.run_job(**kwargs)
        except Exception as exc:
            holder["error"] = exc

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    return thread, holder


def _pending_scan_copy(harness, source_file_id: str = "D07") -> Path:
    """为一个"待处理扫描件新版本"造出字节不同的副本（内容不变、可打开），避免 CONTENT_UNCHANGED。

    做法与 `tools/build_demo_corpus.py` 的 20MB 边界文件一致：在 %%EOF 之后追加合法 PDF 注释行。
    副本仍在各例自己的临时目录里，不写入 fixtures。
    """
    import pdfplumber

    source = b0.fixture_path(source_file_id)
    target = Path(harness.data_dir) / f"pending-{source_file_id}-copy.pdf"
    target.parent.mkdir(parents=True, exist_ok=True)
    data = source.read_bytes()
    marker = b"\n% T09-D1 U09 pending version marker (test-only copy of the same scanned pages)\n"
    target.write_bytes(data + marker)
    with pdfplumber.open(target) as pdf:
        pages = len(pdf.pages)
    assert pages == 8, f"副本页数异常：{pages}"
    assert target.read_bytes() != data, "副本必须与原文件字节不同"
    return target


@pytest.mark.parametrize("variant", ["delete", "cancel_pending_version", "lease_expired"])
def test_u09_late_ocr_result_after_delete_cancel_or_lease_loss(restored, b0_snapshot, variant):
    harness = restored
    admin = harness.admin()
    scan = b0_snapshot["facts"]["documents"]["D07"]["document"]
    detail = harness.detail(scan)
    old_active = detail["document"]["active_version"]["id"]

    copy_path = _pending_scan_copy(harness, "D07")
    pending = admin.upload(
        path=copy_path,
        name=copy_path.name,
        document_id=scan,
        expected_active_version_id=old_active,
    )
    assert pending.status_code == 202, pending.text
    pending = pending.json()
    pending_version = pending["version"]["id"]
    harness.ocr.bind("D07")
    harness.ocr.block = True
    harness.ocr.entered.clear()
    harness.ocr.release.clear()

    lease = None
    if variant == "lease_expired":
        db = harness.session()
        try:
            lease = claim_job(db, lease_seconds=1)
            assert lease is not None
        finally:
            db.close()
    # 无论哪种变体，先记录工作前的有效版本
    thread, holder = _start_worker(harness, lease=lease) if lease is not None else _start_worker(harness)
    assert harness.ocr.entered.wait(20), "OCR 替身未进入调用"
    calls_during = len(harness.ocr.summary())

    if variant == "delete":
        deleted = admin.client.delete(
            f"/api/v1/documents/{scan}",
            params={"expected_revision": harness.detail(scan)["revision"]},
            headers=admin.headers,
        )
        assert deleted.status_code == 200, deleted.text
    elif variant == "cancel_pending_version":
        cancelled = admin.client.post(
            f"/api/v1/documents/{scan}/versions/{pending_version}/cancel",
            headers=admin.headers,
        )
        assert cancelled.status_code == 204, cancelled.text
    else:
        time.sleep(1.3)  # 让 1 秒租约真实过期

    harness.ocr.release.set()
    thread.join(30)
    assert not thread.is_alive(), "worker 未在迟到结果前退出"
    assert "error" not in holder, holder.get("error")
    result_state = holder["result"].state
    calls_after = len(harness.ocr.summary())
    harness.ocr.block = False

    document = admin.client.get(f"/api/v1/documents/{scan}")
    file_old = admin.client.get(f"/api/v1/documents/{scan}/versions/{old_active}/file")
    units = _unit_count(harness, pending_version)
    records = _ocr_records(harness, pending_version)
    job = _job_row(harness, pending["job"]["id"])

    answerable = None
    if variant == "cancel_pending_version":
        employee = harness.employee()
        conversation = b0.new_conversation(employee, "T09-U09-cancel")
        answerable = b0.ask(employee, conversation, "扫描的活动申请中，申请部门是什么？")

    _dump(
        f"U09-{variant}",
        {
            **_context(harness, QUESTIONS["U09"], {"environment": b0_snapshot["environment"]}),
            "variant": variant,
            "worker_state": result_state,
            "ocr_calls_during": calls_during,
            "ocr_calls_after_release": calls_after,
            "pending_units": units,
            "ocr_records": records,
            "job_state": job.state if job is not None else None,
            "document_status": document.status_code,
            "document_body": document.json() if document.status_code == 200 else document.text,
            "old_active_file_status": file_old.status_code,
            "cancel_answer": None if answerable is None else {"status": answerable.status_code, "body": answerable.json()},
            "ocr_call_ledger": harness.ocr.summary(),
        },
    )

    assert calls_after == calls_during, "迟到结果后不得再发起下一页或重试"
    assert units == 0, "迟到结果不得写入任何来源单元"
    assert all(record["state"] == "discarded" for record in records), records

    if variant == "delete":
        assert result_state == "cancelled", result_state
        assert document.status_code == 200 and document.json()["document"]["deleted"] is True
        assert file_old.status_code == 410, "删除后旧有效版访问必须撤销"
    elif variant == "cancel_pending_version":
        assert result_state == "cancelled", result_state
        assert answerable is not None and answerable.status_code == 200
        assert answerable.json()["kind"] == "answer", answerable.text
        assert "市场部" in answerable.json()["text"]
        assert file_old.status_code == 200, "取消新版不得影响旧有效版"
    else:
        assert result_state == "lease_lost", result_state
        assert job is not None and job.state == "running", "旧租约不得提交成功或失败"
        # 新持有者可以继续处理：重新领取并成功
        harness.ocr.block = False
        harness.ocr.bind("D07")
        resumed = harness.run_job()
        assert resumed.state == "succeeded", resumed
        assert _unit_count(harness, pending_version) > 0


# ---------------------------------------------------------------- U10


def test_u10_client_request_id_idempotency(restored, b0_snapshot):
    harness = restored
    employee = harness.employee()
    conversation = b0.new_conversation(employee, "T09-U10")
    request_id = "11111111-1111-4111-8111-111111111111"
    question = "城东店宣传海报在哪？"
    other = "城西店宣传海报在哪？"
    calls_before = len(harness.model.calls)

    first = b0.ask(employee, conversation, question, request_id=request_id)
    second = b0.ask(employee, conversation, question, request_id=request_id)
    third = b0.ask(employee, conversation, other, request_id=request_id)
    history = b0.messages(employee, conversation)

    _dump(
        "U10",
        {
            **_context(harness, QUESTIONS["U10"], {"environment": b0_snapshot["environment"]}),
            "first": {"status": first.status_code, "body": first.json()},
            "second": {"status": second.status_code, "body": second.json()},
            "third": {"status": third.status_code, "body": third.json()},
            "history": history,
            "model_calls_before": calls_before,
            "model_calls_after": len(harness.model.calls),
        },
    )
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert second.json()["message_id"] == first.json()["message_id"], "同 ID 同载荷必须返回既有结果"
    assert second.json()["text"] == first.json()["text"]
    assert len(harness.model.calls) == calls_before + 1, "重放不得再次调用模型"
    assert third.status_code == 409, third.text
    assert third.json()["error"]["code"] == "REQUEST_PAYLOAD_MISMATCH", third.json()
    roles = [item["role"] for item in history["items"]]
    assert roles == ["user", "assistant"], roles

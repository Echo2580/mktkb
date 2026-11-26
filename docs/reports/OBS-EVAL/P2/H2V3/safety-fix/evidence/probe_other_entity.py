"""合成探针：多轮会话里的实体作用域（不改产品代码，只观测）。

离线：临时 SQLite + tmp 数据目录 + ``EvidenceEchoGateway`` 替身模型；不调真实模型/embedding/
rerank/OCR，不出网。只打印每轮的产品结局与“发给模型的证据”里的实体字段（门店/物品），
用于复现与定位 ``other_entity_used``。

用法（backend/ 下）：
    ../.venv/Scripts/python.exe <本文件> <输出.json>
"""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

import openpyxl
from fastapi.testclient import TestClient

_REPO_ROOT = Path(__file__).resolve().parents[7]
sys.path.insert(0, str(_REPO_ROOT / "backend" / "src"))
sys.path.insert(0, str(_REPO_ROOT / "backend" / "tests"))

import conftest as t  # noqa: E402

from mktkb.config import Settings  # noqa: E402
from mktkb.ingestion.worker import run_one_job  # noqa: E402
from mktkb.main import create_app  # noqa: E402

ORIGIN = "http://testserver"

ITEM_HEADERS = ["门店", "物品", "别名", "标识", "位置"]
STORE_HEADERS = ["标识", "店家", "联系人", "电话", "地址", "合作状态"]

ITEM_ROWS = [
    ["城东店", "宣传海报", "海报", "P01", "A区1号货架"],
    ["城西店", "宣传海报", "海报", "P02", "C区2号货架"],
    ["城东店", "展架", "展示架", "P03", "A区2号货架底层"],
    ["城西店", "展架", "展示架", "P04", "B区3号货架中层"],
]
STORE_ROWS = [
    ["S01", "城东店", "模拟联系人·陈宁", "010-00000001", "示例路18号", "合作中"],
    ["S02", "城西店", "模拟联系人·王平", "010-00000002", "示例路26号", "合作中"],
]


def _xlsx(path: Path, headers: list[str], rows: list[list[object]], title: str) -> Path:
    workbook = openpyxl.Workbook()
    worksheet = workbook.active
    worksheet.title = "台账"
    worksheet.cell(row=1, column=1, value=title)
    for column, header in enumerate(headers, start=1):
        worksheet.cell(row=3, column=column, value=header)
    for offset, row in enumerate(rows):
        for column, value in enumerate(row, start=1):
            worksheet.cell(row=4 + offset, column=column, value=value)
    workbook.save(path)
    return path


def _settings(root: Path) -> Settings:
    return Settings(
        _env_file=None,
        data_dir=root,
        database_url=f"sqlite:///{(root / 'mktkb.sqlite3').as_posix()}",
        cookie_secure=False,
        csrf_secret="probe-csrf-secret-0123456789",
        admin_password="AdminPass-1",
        employee_password="EmployeePass-1",
        trusted_origins=[ORIGIN],
        bcrypt_rounds=4,
        session_ttl_seconds=3600,
        log_level="WARNING",
    )


def _session(app, username: str, password: str) -> SimpleNamespace:
    client = TestClient(app, raise_server_exceptions=False)
    login = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
        headers={"Origin": ORIGIN},
    )
    assert login.status_code == 200, login.text
    me = client.get("/api/v1/auth/me").json()
    csrf = me["csrf_token"]
    headers = {"Origin": ORIGIN, "X-CSRF-Token": csrf}
    return SimpleNamespace(
        client=client,
        csrf=csrf,
        headers=headers,
        upload=lambda **kwargs: client.post(
            "/api/v1/documents",
            files={
                "file": (
                    Path(kwargs["path"]).name,
                    Path(kwargs["path"]).read_bytes(),
                    "application/octet-stream",
                )
            },
            data={},
            headers=headers,
        ),
    )


def _revision(app) -> int:
    from mktkb.documents.lifecycle import get_revision

    db = app.state.db.session()
    try:
        return get_revision(db)
    finally:
        db.close()


def _publish(app, admin: SimpleNamespace, record: dict) -> None:
    response = admin.client.post(
        f"/api/v1/documents/{record['document']['id']}/versions/{record['version']['id']}/publish",
        headers=admin.headers,
        json={"expected_active_version_id": None, "expected_revision": _revision(app)},
    )
    assert response.status_code == 200, response.text


def _upload(app, admin: SimpleNamespace, path: Path) -> None:
    receipt = admin.upload(path=path)
    assert receipt.status_code == 202, receipt.text
    record = receipt.json()
    db = app.state.db.session()
    try:
        assert run_one_job(db, app.state.store).state == "succeeded"
    finally:
        db.close()
    _publish(app, admin, record)


def _ask(session: SimpleNamespace, conversation_id: str, question: str) -> dict:
    response = session.client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"client_request_id": str(uuid.uuid4()), "question": question},
        headers=session.headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


def _evidence_entities(call: dict) -> list[dict]:
    out = []
    for item in call.get("evidence", []):
        fields = item.get("fields") or {}
        out.append(
            {
                "source_id": item.get("source_id"),
                "store": fields.get("门店") or fields.get("店家"),
                "item": fields.get("物品"),
                "identifier": fields.get("标识"),
            }
        )
    return out


CASES = {
    "M1 single entity location then phone follow-up": ["城东店的展架在哪里？", "那它的电话呢？"],
    "M2 single entity then sibling item": ["城东店的展架在哪里？", "宣传海报呢？"],
    "M3 single entity then other store": ["城东店的展架在哪里？", "城西店呢？"],
    "M4 multi target then anaphora": ["城东店和城西店的展架在哪里？", "那它的位置呢？"],
    "M5 single entity then field anaphora": ["城东店的展架在哪里？", "它的位置呢？"],
    "M6 store switch then store field": ["城东店的展架在哪里？", "城西店", "电话呢？"],
}


def main() -> int:
    out_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("probe-other-entity.json")
    root = Path(__file__).resolve().parent / "_probe_tmp"
    if root.exists():
        for child in sorted(root.rglob("*"), reverse=True):
            if child.is_file():
                child.unlink()
            else:
                child.rmdir()
    root.mkdir(parents=True, exist_ok=True)

    model = t.EvidenceEchoGateway()
    app = create_app(_settings(root), model_gateway=model)
    app.include_router(t.probe_router)
    try:
        admin = _session(app, "admin", "AdminPass-1")
        employee = _session(app, "employee", "EmployeePass-1")
        _upload(app, admin, _xlsx(root / "物品位置表.xlsx", ITEM_HEADERS, ITEM_ROWS, "物品位置表"))
        _upload(app, admin, _xlsx(root / "合作店家信息.xlsx", STORE_HEADERS, STORE_ROWS, "合作店家信息"))

        results = {}
        for name, turns in CASES.items():
            conversation_id = employee.client.post(
                "/api/v1/conversations", json={}, headers=employee.headers
            ).json()["id"]
            calls_before = len(model.calls)
            turn_results = []
            for question in turns:
                body = _ask(employee, conversation_id, question)
                last_call = model.calls[-1] if len(model.calls) > calls_before else None
                calls_before = len(model.calls)
                turn_results.append(
                    {
                        "question": question,
                        "kind": body.get("kind"),
                        "text": body.get("text"),
                        "model_calls": 0 if last_call is None else 1,
                        "evidence": [] if last_call is None else _evidence_entities(last_call),
                        "context_entities": {}
                        if last_call is None
                        else dict(last_call["context"]["entities"]),
                    }
                )
            results[name] = turn_results
        payload = {"cases": results}
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(payload, ensure_ascii=False, indent=1))
    finally:
        qa = getattr(app.state, "qa", None)
        if qa is not None:
            qa.close()
        app.state.db.dispose()
        store = getattr(app.state, "store", None)
        if store is not None and hasattr(store, "close"):
            store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""T303 controlled seed for isolated e2e data (受控样本).

Writes only the directory passed by --data-dir. Never touches backend/var/.
Dates are anchored to "today" in Asia/Shanghai so e2e presets stay valid.

Run from repo root:
    .venv\\Scripts\\python.exe -B frontend\\e2e\\operations-seed.py --data-dir <dir>
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "backend" / "src"))

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

from mktkb.config import Settings  # noqa: E402
from mktkb.conversations.models import ConversationRequest  # noqa: E402
from mktkb.documents.models import Document  # noqa: E402
from mktkb.main import create_app  # noqa: E402
from tests.operations.helpers import make_document, make_import, make_request  # noqa: E402

ADMIN_PASSWORD = "AdminPass-1"
EMPLOYEE_PASSWORD = "EmployeePass-1"
CSRF_SECRET = "p3-e2e-csrf-secret-0123456789"
ORIGIN = "http://127.0.0.1:5299"
SHANGHAI = timezone(timedelta(hours=8), "Asia/Shanghai")


def shanghai_noon_utc(day) -> datetime:
    return datetime(day.year, day.month, day.day, 12, 0, tzinfo=SHANGHAI).astimezone(timezone.utc)


def count_requests(client: TestClient, base: dict, page_size: int = 100) -> int:
    total = 0
    cursor = None
    for _ in range(20):
        params = dict(base)
        params["page_size"] = str(page_size)
        if cursor:
            params["cursor"] = cursor
        response = client.get("/api/v1/operations/requests", params=params)
        response.raise_for_status()
        payload = response.json()
        total += len(payload.get("items") or [])
        cursor = payload.get("next_cursor")
        if not cursor:
            break
    return total


def count_documents(client: TestClient, base: dict, document_id: str | None = None) -> int:
    total = 0
    cursor = None
    for _ in range(20):
        params = dict(base)
        params["page_size"] = "100"
        if cursor:
            params["cursor"] = cursor
        response = client.get("/api/v1/operations/documents", params=params)
        response.raise_for_status()
        payload = response.json()
        items = payload.get("items") or []
        if document_id:
            items = [item for item in items if item.get("document_id") == document_id]
        total += len(items)
        cursor = payload.get("next_cursor")
        if not cursor:
            break
    return total


def overview_metrics(client: TestClient, params: dict) -> dict:
    response = client.get("/api/v1/operations/overview", params=params)
    response.raise_for_status()
    payload = response.json()
    metrics = payload["metrics"]
    return {
        "completed": metrics["completed_requests"],
        "not_found": metrics["not_found"],
        "conflict": metrics["conflict"],
        "review": metrics["review_required_versions"],
        "interrupted": metrics["interrupted"],
        "active_documents": metrics["active_documents"],
        "pending": len(payload.get("pending") or []),
        "trend_days": len(payload.get("trend") or []),
        "distribution": payload.get("result_distribution") or {},
        "trend": payload.get("trend") or [],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", required=True)
    args = parser.parse_args()

    data_dir = Path(args.data_dir).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)

    settings = Settings(
        _env_file=None,
        data_dir=data_dir,
        database_url=f"sqlite:///{(data_dir / 'mktkb.sqlite3').as_posix()}",
        admin_password=ADMIN_PASSWORD,
        employee_password=EMPLOYEE_PASSWORD,
        csrf_secret=CSRF_SECRET,
        trusted_origins=[ORIGIN],
        cookie_secure=False,
        bcrypt_rounds=4,
        trace_enabled=False,
        rag_qa_enabled=False,
    )
    app = create_app(settings)
    session = app.state.db.session()

    today = datetime.now(SHANGHAI).date()
    yesterday = today - timedelta(days=1)
    ten_days_ago = today - timedelta(days=10)
    today_at = shanghai_noon_utc(today)
    yesterday_at = shanghai_noon_utc(yesterday)
    ten_days_at = shanghai_noon_utc(ten_days_ago)

    try:
        if session.scalar(select(ConversationRequest).limit(1)) is not None:
            print("SEED_FAILED: isolated database already contains requests", file=sys.stderr)
            return 2

        doc_a = make_document(session, name="门店产品价目表", file_type="xlsx", states=("published",), units=2, created_at=today_at)
        doc_b = make_document(session, name="门店服务手册", file_type="docx", states=("published",), units=1, created_at=today_at)
        doc_c = make_document(session, name="新品宣传初稿", file_type="docx", states=("review_required",), active=False, units=1, created_at=today_at)
        doc_d = make_document(session, name="损坏的库存表", file_type="xlsx", states=("failed",), active=False, units=1, created_at=today_at)
        make_import(
            session,
            doc_d.versions[0],
            state="failed",
            stage="parse",
            error_code="PARSE_INCOMPLETE",
            message="解析未完成：缺少缓存值",
            finished_at=today_at,
        )

        a0, a1 = str(doc_a.document.id), str(doc_a.versions[0].id)
        b0, b1 = str(doc_b.document.id), str(doc_b.versions[0].id)
        conflict_unit = doc_a.units[doc_a.versions[0].id][1].id

        make_request(
            session,
            finished_at=today_at,
            question="今天门店主推产品的价格是多少？",
            sources=((a0, a1, 0), (a0, a1, 1)),
        )
        make_request(
            session,
            finished_at=today_at + timedelta(minutes=2),
            question="价目表里 A 套餐包含什么？",
            sources=((a0, a1, 1),),
        )
        make_request(
            session,
            finished_at=today_at + timedelta(minutes=4),
            kind="not_found",
            question="今天有圣诞礼盒吗？",
        )
        make_request(
            session,
            finished_at=today_at + timedelta(minutes=6),
            kind="conflict",
            question="A 套餐价格以哪个门店为准？",
            sources=((a0, a1, 0),),
            conflicts=({"field": "价格", "entries": [{"value": "B区价", "source_id": str(conflict_unit)}]},),
        )
        make_request(
            session,
            finished_at=today_at + timedelta(minutes=8),
            kind="service_error",
            question="帮我总结本周门店活动。",
            error_code="MODEL_TIMEOUT",
        )
        make_request(
            session,
            finished_at=yesterday_at,
            question="服务手册里的退换货时限？",
            sources=((b0, b1, 0),),
        )
        make_request(
            session,
            finished_at=yesterday_at + timedelta(minutes=3),
            kind="clarification",
            question="这个怎么操作？",
            missing_fields=["门店", "产品"],
        )
        make_request(
            session,
            finished_at=ten_days_at,
            question="价目表历史版本里的老套餐？",
            sources=((a0, a1, 0),),
        )

        make_request(
            session,
            kind=None,
            status="running",
            question="正在处理的请求",
            finished_at=today_at,
        )
        make_request(
            session,
            kind=None,
            status="expired",
            question="已经超时的请求",
            finished_at=yesterday_at,
        )

        session.commit()
    finally:
        session.close()

    client = TestClient(app, raise_server_exceptions=False)
    login = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": ADMIN_PASSWORD},
        headers={"Origin": ORIGIN},
    )
    if login.status_code != 200:
        print(f"SEED_FAILED: login {login.status_code} {login.text}", file=sys.stderr)
        return 3

    week = overview_metrics(client, {"window": "7d"})
    today_metrics = overview_metrics(client, {"window": "today"})
    month = overview_metrics(client, {"window": "30d"})
    yesterday_metrics = overview_metrics(
        client,
        {"since": yesterday.isoformat(), "until": yesterday.isoformat()},
    )
    empty = overview_metrics(client, {"since": "2020-01-01", "until": "2020-01-02"})

    request_totals = {
        "week": count_requests(client, {"window": "7d"}),
        "today": count_requests(client, {"window": "today"}),
        "yesterday": count_requests(client, {"since": yesterday.isoformat(), "until": yesterday.isoformat()}),
        "conflict_week": count_requests(client, {"window": "7d", "kind": "conflict"}),
    }

    documents = {
        "review_total": count_documents(client, {"window": "7d", "version_state": "review_required"}),
        "failed_total": count_documents(
            client,
            {"window": "7d", "processing_state": "failed"},
            document_id=str(doc_d.document.id),
        ),
        "failed_document_id": str(doc_d.document.id),
        "failed_version_id": str(doc_d.versions[0].id),
        "failed_state": "failed",
        "review_document_id": str(doc_c.document.id),
    }

    summary = {
        "note": "T303 controlled seed (受控样本)；只写隔离目录，不含真实业务数据。",
        "dates": {
            "today": today.isoformat(),
            "yesterday": yesterday.isoformat(),
            "ten_days_ago": ten_days_ago.isoformat(),
            "empty_since": "2020-01-01",
            "empty_until": "2020-01-02",
        },
        "accounts": {
            "admin": {"username": "admin", "password": ADMIN_PASSWORD},
            "employee": {"username": "employee", "password": EMPLOYEE_PASSWORD},
        },
        "metrics": {
            "week7d": week,
            "today": today_metrics,
            "month30d": month,
            "yesterday": yesterday_metrics,
            "empty": empty,
        },
        "requests": request_totals,
        "documents": documents,
        "documents_count": {
            "published_active": 2,
            "review_required": 1,
            "failed_import": 1,
        },
    }

    target = data_dir / "seed-summary.json"
    target.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"SEED_SUMMARY={target}")
    print("SEED_OK")

    app.state.db.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

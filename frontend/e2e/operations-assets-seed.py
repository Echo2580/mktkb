"""T305 知识资产页受控种子（只写 --data-dir，绝不触碰 backend/var）。

覆盖派单 §3.7 四场景 + 无生效版本 + 已删除版本 + 冲突关联 + 资料 >1 页：
- doc_price   多引用（同消息两条同源行只算 1 次最终引用）
- doc_flow    换版：V1 已替换（历史引用仍可追溯），V2 生效
- doc_material 待审核：V1 生效，V2 待审核
- doc_notice 导入失败：V1 生效，V2 导入失败（PARSE_INCOMPLETE）
- doc_launch 无生效版本：V1 待审核
- doc_shop   已删除版本：V1 已删除，V2 生效
- doc_manual 冲突关联：最终引用 1、相关问答 2（冲突不计最终引用）
- 18 份批量资料：列表总数 25，游标分页 >1 页（page_size=20）

运行（仓库根目录）：
    .venv\\Scripts\\python.exe -B frontend\\e2e\\operations-assets-seed.py --data-dir <dir>
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
from mktkb.main import create_app  # noqa: E402
from tests.operations.helpers import make_document, make_import, make_request  # noqa: E402

ADMIN_PASSWORD = "AdminPass-1"
EMPLOYEE_PASSWORD = "EmployeePass-1"
CSRF_SECRET = "p3-e2e-csrf-secret-0123456789"
ORIGIN = "http://127.0.0.1:5301"
SHANGHAI = timezone(timedelta(hours=8), "Asia/Shanghai")
PAGE_SIZE = 20
FILLERS = 18


def shanghai_noon_utc(day) -> datetime:
    return datetime(day.year, day.month, day.day, 12, 0, tzinfo=SHANGHAI).astimezone(timezone.utc)


def iter_documents(client: TestClient, params: dict):
    cursor = None
    pages = 0
    items = []
    while pages < 20:
        query = dict(params)
        query["page_size"] = str(PAGE_SIZE)
        if cursor:
            query["cursor"] = cursor
        response = client.get("/api/v1/operations/documents", params=query)
        response.raise_for_status()
        payload = response.json()
        items.extend(payload.get("items") or [])
        pages += 1
        cursor = payload.get("next_cursor")
        if not cursor:
            break
    return items, pages


def snapshot(client: TestClient, window: str) -> dict[str, dict]:
    items, _ = iter_documents(client, {"window": window})
    return {item["document_id"]: item for item in items}


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

        # ---- 场景资料 -------------------------------------------------
        price = make_document(
            session,
            name="门店产品价目表",
            file_type="xlsx",
            states=("published",),
            units=2,
            created_at=today_at,
        )
        flow = make_document(
            session,
            name="活动策划流程",
            file_type="docx",
            states=("superseded", "published"),
            units=1,
            created_at=today_at,
        )
        material = make_document(
            session,
            name="物料领用流程",
            file_type="docx",
            states=("published", "review_required"),
            units=1,
            created_at=today_at,
        )
        notice = make_document(
            session,
            name="活动申请通知",
            file_type="pdf",
            states=("published", "failed"),
            units=1,
            created_at=today_at,
        )
        launch = make_document(
            session,
            name="新品宣传初稿",
            file_type="pdf",
            states=("review_required",),
            active=False,
            units=1,
            created_at=today_at,
        )
        shop = make_document(
            session,
            name="合作店家信息",
            file_type="xlsx",
            states=("deleted", "published"),
            units=1,
            created_at=today_at,
        )
        manual = make_document(
            session,
            name="门店服务手册",
            file_type="docx",
            states=("published",),
            units=1,
            created_at=today_at,
        )

        # 待审核版本的导入任务已完成（等待发布）；失败版本给出可展示原因。
        make_import(
            session,
            material.versions[1],
            state="succeeded",
            stage="parse",
            error_code=None,
            message=None,
            finished_at=today_at,
        )
        make_import(
            session,
            notice.versions[1],
            state="failed",
            stage="ocr",
            error_code="PARSE_INCOMPLETE",
            message="解析未完成：图片缺页，未发布新版本",
            finished_at=today_at,
        )

        # ---- 批量资料（撑出第二页） ------------------------------------
        fillers = []
        for index in range(1, FILLERS + 1):
            filler = make_document(
                session,
                name=f"批量资料-{index:02d}",
                file_type="xlsx" if index % 2 else "docx",
                states=("published",),
                units=1,
                created_at=today_at,
            )
            fillers.append(filler)

        # ---- 问答与引用 ------------------------------------------------
        p_doc, p_v1 = str(price.document.id), str(price.versions[0].id)
        f_doc, f_v1, f_v2 = str(flow.document.id), str(flow.versions[0].id), str(flow.versions[1].id)
        m_doc, m_v1 = str(material.document.id), str(material.versions[0].id)
        n_doc, n_v1 = str(notice.document.id), str(notice.versions[0].id)
        s_doc, s_v1, s_v2 = str(shop.document.id), str(shop.versions[0].id), str(shop.versions[1].id)
        h_doc, h_v1 = str(manual.document.id), str(manual.versions[0].id)
        conflict_source = str(price.units[price.versions[0].id][1].id)

        # 多引用：同一消息两条同源行（只在最终引用计 1 次），共 3 条消息。
        make_request(
            session,
            finished_at=today_at,
            question="今天门店主推产品的价格是多少？",
            sources=((p_doc, p_v1, 0), (p_doc, p_v1, 1)),
        )
        make_request(
            session,
            finished_at=today_at + timedelta(minutes=2),
            question="价目表里 A 套餐包含什么？",
            sources=((p_doc, p_v1, 1),),
        )
        make_request(
            session,
            finished_at=ten_days_at,
            question="价目表历史版本里的老套餐？",
            sources=((p_doc, p_v1, 0),),
        )

        # 换版：历史消息引用已替换的 V1，可在版本级下钻追溯。
        make_request(
            session,
            finished_at=yesterday_at,
            question="上一版活动策划流程走到哪一步？",
            sources=((f_doc, f_v1, 0),),
        )

        # 待审核：V1 继续生效。
        make_request(
            session,
            finished_at=today_at + timedelta(minutes=4),
            question="物料领用要谁审批？",
            sources=((m_doc, m_v1, 0),),
        )

        # 导入失败的 V2 不参与问答，旧版继续生效。
        make_request(
            session,
            finished_at=today_at + timedelta(minutes=6),
            question="活动申请截止时间是什么时候？",
            sources=((n_doc, n_v1, 0),),
        )

        # 已删除版本不引用，生效的 V2 正常引用。
        make_request(
            session,
            finished_at=today_at + timedelta(minutes=8),
            question="合作店家怎么联系？",
            sources=((s_doc, s_v2, 0),),
        )

        # 冲突关联：最终引用 1、相关问答 2（冲突问答不计最终引用）。
        make_request(
            session,
            finished_at=today_at + timedelta(minutes=10),
            question="退换货时限是多久？",
            sources=((h_doc, h_v1, 0),),
        )
        make_request(
            session,
            finished_at=yesterday_at + timedelta(minutes=3),
            kind="conflict",
            question="退换货时限以哪份文件为准？",
            sources=((h_doc, h_v1, 0),),
            conflicts=({"field": "退换货时限", "entries": [{"value": "7 天", "source_id": conflict_source}]},),
        )
        make_request(
            session,
            finished_at=ten_days_at + timedelta(minutes=5),
            question="门店服务手册里的常见问题？",
            sources=((h_doc, h_v1, 0),),
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

    snapshots = {window: snapshot(client, window) for window in ("today", "7d", "30d")}
    all_items, pages = iter_documents(client, {"window": "7d"})
    review_total = len(iter_documents(client, {"window": "7d", "version_state": "review_required"})[0])
    failed_total = len(iter_documents(client, {"window": "7d", "processing_state": "failed"})[0])

    def citations_for(document_id: str) -> dict:
        return {
            window: {
                "final_citations": snapshots[window][document_id]["final_citations"],
                "related_requests": snapshots[window][document_id]["related_requests_count"],
                "current_version": snapshots[window][document_id]["current_version"],
            }
            for window in ("today", "7d", "30d")
            if document_id in snapshots[window]
        }

    core = {
        "price": {"document_id": p_doc, "name": "门店产品价目表", "file_type": "xlsx"},
        "flow": {
            "document_id": f_doc,
            "name": "活动策划流程",
            "file_type": "docx",
            "versions": [
                {"number": 1, "version_id": f_v1, "state": "superseded"},
                {"number": 2, "version_id": f_v2, "state": "published"},
            ],
            "active_version_id": f_v2,
        },
        "material": {
            "document_id": m_doc,
            "name": "物料领用流程",
            "file_type": "docx",
            "versions": [
                {"number": 1, "version_id": m_v1, "state": "published"},
                {"number": 2, "version_id": str(material.versions[1].id), "state": "review_required"},
            ],
            "active_version_id": m_v1,
        },
        "notice": {
            "document_id": n_doc,
            "name": "活动申请通知",
            "file_type": "pdf",
            "versions": [
                {"number": 1, "version_id": n_v1, "state": "published"},
                {"number": 2, "version_id": str(notice.versions[1].id), "state": "failed"},
            ],
            "active_version_id": n_v1,
            "import": {
                "state": "failed",
                "stage": "ocr",
                "error_code": "PARSE_INCOMPLETE",
                "message": "解析未完成：图片缺页，未发布新版本",
            },
        },
        "launch": {
            "document_id": str(launch.document.id),
            "name": "新品宣传初稿",
            "file_type": "pdf",
            "versions": [{"number": 1, "version_id": str(launch.versions[0].id), "state": "review_required"}],
            "active_version_id": None,
        },
        "shop": {
            "document_id": s_doc,
            "name": "合作店家信息",
            "file_type": "xlsx",
            "versions": [
                {"number": 1, "version_id": s_v1, "state": "deleted"},
                {"number": 2, "version_id": s_v2, "state": "published"},
            ],
            "active_version_id": s_v2,
        },
        "manual": {"document_id": h_doc, "name": "门店服务手册", "file_type": "docx"},
    }
    for key in ("price", "flow", "material", "notice", "shop", "manual"):
        core[key]["citations"] = citations_for(core[key]["document_id"])

    notice_detail = client.get(f"/api/v1/operations/documents/{n_doc}")
    notice_detail.raise_for_status()

    summary = {
        "note": "T305 controlled seed（受控样本）；只写隔离目录，不含真实业务数据。",
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
        "documents": core,
        "totals": {
            "documents": len(all_items),
            "pages": pages,
            "page_size": PAGE_SIZE,
            "review_total": review_total,
            "failed_total": failed_total,
            "filler_documents": FILLERS,
        },
        "detail_snapshot": {
            "notice": notice_detail.json(),
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

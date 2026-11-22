"""T306 集成验收受控种子（I1-I8 共用一套数据）。

只写 ``--data-dir``（T306-evidence/isolated-var），绝不触碰 backend/var/。
覆盖：≥2 个自然日问答（answer 带 active 引用、not_found、conflict 两方 active、
service_error）、Trace recorded / not_recorded、1 个失败导入文档（PARSE_INCOMPLETE，
旧版继续生效）、1 个待审核文档、1 个评测 run（含 holdout）+ 1 个空目录、空窗口。

运行（仓库根目录）：
    .venv\\Scripts\\python.exe -B frontend\\e2e\\operations-integration-seed.py --data-dir <dir>
"""

from __future__ import annotations

import argparse
import json
import shutil
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
from mktkb.observability.contracts import SpanRecord, TraceRecord  # noqa: E402
from mktkb.observability.store import TraceRepository  # noqa: E402
from tests.operations.helpers import make_document, make_import, make_request  # noqa: E402

ADMIN_PASSWORD = "AdminPass-1"
EMPLOYEE_PASSWORD = "EmployeePass-1"
CSRF_SECRET = "p3-e2e-csrf-secret-0123456789"
MAIN_BASE = "http://127.0.0.1:5303"
TRACE_OFF_BASE = "http://127.0.0.1:5304"
ORIGIN = MAIN_BASE
SHANGHAI = timezone(timedelta(hours=8), "Asia/Shanghai")
PAGE_SIZE = 20
EMPTY_SINCE = "2020-01-01"
EMPTY_UNTIL = "2020-01-02"


def at(day, hour: int, minute: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=SHANGHAI).astimezone(timezone.utc)


def span(
    name: str,
    duration_ms: int,
    *,
    status: str = "ok",
    error_code: str | None = None,
    started_at: datetime | None = None,
) -> SpanRecord:
    return SpanRecord(
        name=name,
        duration_ms=duration_ms,
        status=status,
        error_code=error_code,
        started_at=started_at.isoformat() if started_at else None,
    )


def write_trace(
    repo: TraceRepository,
    *,
    request_id: uuid.UUID,
    path: str,
    outcome: str,
    status: str,
    finished_at: datetime,
    spans: list[SpanRecord],
    error_code: str | None = None,
) -> None:
    repo.write(
        TraceRecord(
            trace_id=uuid.uuid4().hex,
            request_id=str(request_id),
            attempt=1,
            replayed=False,
            mode="local",
            scope="end_to_end",
            path=path,
            outcome_kind=outcome,
            content_mode="hash",
            status=status,
            error_code=error_code,
            latency_ms=sum(item.duration_ms or 0 for item in spans) or None,
            created_at=finished_at.isoformat(),
        ),
        spans,
    )


def write_eval_runs(data_dir: Path, day: datetime) -> dict:
    runs_root = data_dir / "eval" / "runs"
    runs_root.mkdir(parents=True, exist_ok=True)
    created = datetime(day.year, day.month, day.day, 1, 30, tzinfo=timezone.utc)

    def dump(run_dir: Path, name: str, payload: dict) -> None:
        (run_dir / name).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    done = runs_root / "t306-eval-b0-01"
    done.mkdir()
    dump(
        done,
        "run_manifest.json",
        {
            "run_id": "t306-eval-b0-01",
            "mode": "local",
            "scope": "end_to_end",
            "suite": "b0",
            "dataset_version": "b0-20261122",
            "case_count": 20,
            "index_revision": 7,
            "created_at": created.isoformat(),
            "gate_version": "g1",
            "holdout_details": False,
            "dataset_path": "must-not-leave-whitelist",
        },
    )
    dump(
        done,
        "summary.json",
        {
            "run_id": "t306-eval-b0-01",
            "mode": "local",
            "scope": "end_to_end",
            "suite": "b0",
            "dataset_version": "b0-20261122",
            "case_count": 20,
            "scored_count": 20,
            "error_count": 0,
            "skipped_ocr_count": 0,
            "status_counts": {"answered": 16, "clarification": 1, "not_found": 2, "conflict": 1},
            "metrics": {"citation_hit": 0.86, "evidence_coverage": 0.91},
            "index_revision": 7,
            "retrieval_only": False,
        },
    )
    dump(
        done,
        "gate.json",
        {
            "run_id": "t306-eval-b0-01",
            "suite": "b0",
            "quality_status": "pass",
            "gate_status": {"citation": "pass", "scope": "pass"},
            "failure_count": 0,
            "unknown_count": 1,
            "not_applicable_count": 2,
            "exit_code": 0,
            "hard_failures": [],
            "gate_version": "g1",
            "evidence": "must-not-leave-whitelist",
        },
    )

    holdout = runs_root / "t306-eval-holdout-01"
    holdout.mkdir()
    dump(
        holdout,
        "run_manifest.json",
        {
            "run_id": "t306-eval-holdout-01",
            "mode": "local",
            "scope": "end_to_end",
            "suite": "holdout",
            "dataset_version": "holdout-20261122",
            "case_count": 12,
            "index_revision": 7,
            "created_at": (created - timedelta(minutes=90)).isoformat(),
            "gate_version": "g1",
            "holdout_details": True,
        },
    )
    dump(
        holdout,
        "summary.json",
        {
            "run_id": "t306-eval-holdout-01",
            "mode": "local",
            "suite": "holdout",
            "case_count": 12,
            "scored_count": 12,
            "error_count": 0,
            "holdout": {
                "aggregate_only": True,
                "details_written": False,
                "label_version": "hv1",
                "strata": {"pricing": 4, "service": 5, "activity": 3},
            },
            "metrics": {"citation_hit": 0.79},
        },
    )
    dump(
        holdout,
        "gate.json",
        {
            "run_id": "t306-eval-holdout-01",
            "suite": "holdout",
            "quality_status": "pass",
            "gate_status": {"citation": "pass"},
            "failure_count": 0,
            "exit_code": 0,
        },
    )
    (holdout / "cases.jsonl").write_text(
        json.dumps({"case_id": "holdout-001", "must_not": "leak-into-ui"}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    (runs_root / "t306-eval-empty").mkdir()

    return {
        "run_ids": ["t306-eval-b0-01", "t306-eval-holdout-01"],
        "skipped_dirs": ["t306-eval-empty"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", required=True)
    args = parser.parse_args()

    data_dir = Path(args.data_dir).resolve()
    if data_dir.exists() and any(data_dir.iterdir()):
        if (data_dir / "seed-summary.json").is_file():
            shutil.rmtree(data_dir)
        else:
            print(f"SEED_FAILED: {data_dir} 非空且不是上一次 T306 种子目录，拒绝覆盖", file=sys.stderr)
            return 2
    data_dir.mkdir(parents=True, exist_ok=True)

    settings = Settings(
        _env_file=None,
        data_dir=data_dir,
        database_url=f"sqlite:///{(data_dir / 'mktkb.sqlite3').as_posix()}",
        admin_password=ADMIN_PASSWORD,
        employee_password=EMPLOYEE_PASSWORD,
        csrf_secret=CSRF_SECRET,
        trusted_origins=[ORIGIN, TRACE_OFF_BASE],
        cookie_secure=False,
        bcrypt_rounds=4,
        trace_enabled=True,
        rag_qa_enabled=False,
    )
    app = create_app(settings)
    session = app.state.db.session()

    today = datetime.now(SHANGHAI).date()
    yesterday = today - timedelta(days=1)
    ten_days_ago = today - timedelta(days=10)

    ids: dict[str, uuid.UUID] = {}

    try:
        if session.scalar(select(ConversationRequest).limit(1)) is not None:
            print("SEED_FAILED: isolated database already contains requests", file=sys.stderr)
            return 2

        price = make_document(
            session, name="门店产品价目表", file_type="xlsx", states=("published",), units=2, created_at=at(today, 8)
        )
        manual = make_document(
            session, name="门店服务手册", file_type="docx", states=("published",), units=1, created_at=at(today, 8)
        )
        notice = make_document(
            session, name="市场活动补充通知", file_type="pdf", states=("published", "failed"), units=1, created_at=at(today, 8)
        )
        launch = make_document(
            session,
            name="新品宣传初稿",
            file_type="pdf",
            states=("review_required",),
            active=False,
            units=1,
            created_at=at(today, 8),
        )

        make_import(
            session,
            notice.versions[1],
            state="failed",
            stage="parse",
            error_code="PARSE_INCOMPLETE",
            message="解析未完成：图片缺页，未发布新版本",
            finished_at=at(today, 8, 30),
        )

        price_doc, price_v1 = str(price.document.id), str(price.versions[0].id)
        manual_doc, manual_v1 = str(manual.document.id), str(manual.versions[0].id)
        notice_doc, notice_v1 = str(notice.document.id), str(notice.versions[0].id)
        launch_doc = str(launch.document.id)
        manual_unit = manual.units[manual.versions[0].id][0].id
        notice_unit = notice.units[notice.versions[0].id][0].id

        def add(role: str, **kwargs) -> None:
            ids[role] = make_request(session, **kwargs).request.id

        add(
            "answer_multi",
            finished_at=at(today, 9, 0),
            question="A 套餐单店价格是多少，含不含饮品？",
            sources=((price_doc, price_v1, 0), (price_doc, price_v1, 1)),
            revision=5,
            result_text="A 套餐单店价 128 元，含招牌菜一份与饮品一杯。",
        )
        add(
            "answer_manual",
            finished_at=at(today, 9, 20),
            question="门店退换货需要带什么？",
            sources=((manual_doc, manual_v1, 0),),
            revision=5,
            result_text="退换货请携带小票与商品原包装。",
        )
        add(
            "not_found",
            finished_at=at(today, 9, 35),
            kind="not_found",
            question="今天有圣诞礼盒吗？",
            revision=5,
            result_text="暂未找到相关说明。",
        )
        add(
            "conflict",
            finished_at=at(today, 9, 50),
            kind="conflict",
            question="退换货时限是 3 个工作日还是 5 个工作日？",
            revision=5,
            result_text="",
            conflicts=(
                {
                    "field": "退换货时限",
                    "entries": [
                        {"value": "3 个工作日", "source_id": str(manual_unit)},
                        {"value": "5 个工作日", "source_id": str(notice_unit)},
                    ],
                },
            ),
        )
        add(
            "service_error",
            finished_at=at(today, 10, 5),
            kind="service_error",
            question="帮我总结本周门店活动。",
            revision=5,
            error_code="MODEL_TIMEOUT",
            result_text="",
        )
        add(
            "no_trace",
            finished_at=at(today, 10, 20),
            question="门店营业时间到几点？",
            sources=((manual_doc, manual_v1, 0),),
            revision=5,
            result_text="门店营业至 22:00。",
        )
        add(
            "clarification",
            finished_at=at(yesterday, 15, 0),
            kind="clarification",
            question="这个怎么操作？",
            revision=4,
            missing_fields=["门店", "产品"],
            result_text="请补充门店和产品后我再查询。",
        )
        add(
            "answer_yesterday",
            finished_at=at(yesterday, 15, 20),
            question="活动物料什么时候下发？",
            sources=((notice_doc, notice_v1, 0),),
            revision=4,
            result_text="活动物料在活动开始前 3 天下发。",
        )

        session.commit()
    finally:
        session.close()

    trace_repo = TraceRepository(settings.resolved_trace_db_path)
    history = trace_repo.list_window(datetime(1970, 1, 1, tzinfo=timezone.utc))[0]
    if history:
        trace_repo.close()
        print("SEED_FAILED: trace database already contains records", file=sys.stderr)
        return 2
    try:
        base = at(today, 9, 0)
        write_trace(
            trace_repo,
            request_id=ids["answer_multi"],
            path="rag",
            outcome="answer",
            status="ok",
            finished_at=base,
            spans=[
                span("parse", 40, started_at=base - timedelta(seconds=3)),
                span("recall", 380, started_at=base - timedelta(seconds=3)),
                span("fuse", 95, started_at=base - timedelta(seconds=2)),
                span("answer", 2400, started_at=base - timedelta(seconds=1)),
                span("commit", 88, started_at=base),
            ],
        )
        write_trace(
            trace_repo,
            request_id=ids["answer_manual"],
            path="legacy",
            outcome="answer",
            status="ok",
            finished_at=at(today, 9, 20),
            spans=[
                span("intent_parse", 28, started_at=at(today, 9, 20) - timedelta(seconds=2)),
                span("retrieve", 260, started_at=at(today, 9, 20) - timedelta(seconds=2)),
                span("model_answer", 1800, started_at=at(today, 9, 20) - timedelta(seconds=1)),
                span("answer_validate", 110, started_at=at(today, 9, 20) - timedelta(seconds=1)),
                span("commit", 40, started_at=at(today, 9, 20)),
            ],
        )
        write_trace(
            trace_repo,
            request_id=ids["not_found"],
            path="legacy",
            outcome="not_found",
            status="ok",
            finished_at=at(today, 9, 35),
            spans=[
                span("intent_parse", 26, started_at=at(today, 9, 35) - timedelta(seconds=1)),
                span("retrieve", 300, started_at=at(today, 9, 35) - timedelta(seconds=1)),
                span("commit", 35, started_at=at(today, 9, 35)),
            ],
        )
        write_trace(
            trace_repo,
            request_id=ids["conflict"],
            path="rag",
            outcome="conflict",
            status="ok",
            finished_at=at(today, 9, 50),
            spans=[
                span("parse", 38, started_at=at(today, 9, 50) - timedelta(seconds=2)),
                span("recall", 410, started_at=at(today, 9, 50) - timedelta(seconds=2)),
                span("fuse", 105, started_at=at(today, 9, 50) - timedelta(seconds=1)),
                span("answer", 2100, started_at=at(today, 9, 50) - timedelta(seconds=1)),
                span("commit", 90, started_at=at(today, 9, 50)),
            ],
        )
        write_trace(
            trace_repo,
            request_id=ids["service_error"],
            path="legacy",
            outcome="service_error",
            status="error",
            finished_at=at(today, 10, 5),
            error_code="MODEL_TIMEOUT",
            spans=[
                span("intent_parse", 27, started_at=at(today, 10, 5) - timedelta(seconds=1)),
                span("retrieve", 310, started_at=at(today, 10, 5) - timedelta(seconds=1)),
                span(
                    "model_answer",
                    900,
                    status="error",
                    error_code="MODEL_TIMEOUT",
                    started_at=at(today, 10, 5) - timedelta(seconds=1),
                ),
                span("commit", 45, started_at=at(today, 10, 5)),
            ],
        )
        write_trace(
            trace_repo,
            request_id=ids["clarification"],
            path="rag",
            outcome="clarification",
            status="ok",
            finished_at=at(yesterday, 15, 0),
            spans=[
                span("parse", 35, started_at=at(yesterday, 15, 0) - timedelta(seconds=1)),
                span("commit", 30, started_at=at(yesterday, 15, 0)),
            ],
        )
        # no_trace 故意不写 Trace：验证「本次未记录执行过程」。
    finally:
        trace_repo.close()

    write_eval_runs(data_dir, at(today, 0, 0))

    client = TestClient(app, raise_server_exceptions=False)
    login = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": ADMIN_PASSWORD},
        headers={"Origin": ORIGIN},
    )
    if login.status_code != 200:
        print(f"SEED_FAILED: login {login.status_code} {login.text}", file=sys.stderr)
        return 3

    def overview(params: dict) -> dict:
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
            "trend": payload.get("trend") or [],
            "distribution": payload.get("result_distribution") or {},
            "trace_status": (payload.get("trace_coverage") or {}).get("status"),
        }

    def count_requests(params: dict) -> int:
        total = 0
        cursor = None
        for _ in range(20):
            query = dict(params)
            query["page_size"] = str(PAGE_SIZE)
            if cursor:
                query["cursor"] = cursor
            response = client.get("/api/v1/operations/requests", params=query)
            response.raise_for_status()
            payload = response.json()
            total += len(payload.get("items") or [])
            cursor = payload.get("next_cursor")
            if not cursor:
                break
        return total

    def count_documents(params: dict) -> int:
        total = 0
        cursor = None
        for _ in range(20):
            query = dict(params)
            query["page_size"] = str(PAGE_SIZE)
            if cursor:
                query["cursor"] = cursor
            response = client.get("/api/v1/operations/documents", params=query)
            response.raise_for_status()
            payload = response.json()
            total += len(payload.get("items") or [])
            cursor = payload.get("next_cursor")
            if not cursor:
                break
        return total

    week = overview({"window": "7d"})
    today_metrics = overview({"window": "today"})
    month = overview({"window": "30d"})
    yesterday_metrics = overview({"window": "custom", "since": yesterday.isoformat(), "until": yesterday.isoformat()})
    empty = overview({"window": "custom", "since": EMPTY_SINCE, "until": EMPTY_UNTIL})

    answer_detail = client.get(f"/api/v1/operations/requests/{ids['answer_multi']}").json()
    conflict_detail = client.get(f"/api/v1/operations/requests/{ids['conflict']}").json()
    notice_detail = client.get(f"/api/v1/operations/documents/{notice_doc}").json()
    manual_detail = client.get(f"/api/v1/operations/documents/{manual_doc}").json()
    runs_payload = client.get("/api/v1/operations/evaluation-runs").json()
    api_runs = {item["run_id"]: item for item in runs_payload.get("runs") or []}

    requests_total = {
        "today": count_requests({"window": "today"}),
        "week7d": count_requests({"window": "7d"}),
        "conflict_week": count_requests({"window": "7d", "kind": "conflict"}),
        "notice_document": count_requests({"window": "7d", "document_id": notice_doc}),
    }
    docs_total = {
        "week7d": count_documents({"window": "7d"}),
        "failed": count_documents({"window": "7d", "processing_state": "failed"}),
        "review": count_documents({"window": "7d", "version_state": "review_required"}),
    }
    failed_import = next(
        (item for item in (notice_detail.get("imports") or []) if item.get("state") == "failed"),
        {},
    )

    summary = {
        "note": "T306 集成受控种子（受控样本，非真实业务数据）；只写隔离目录。",
        "main_base": MAIN_BASE,
        "trace_off_base": TRACE_OFF_BASE,
        "dates": {
            "today": today.isoformat(),
            "yesterday": yesterday.isoformat(),
            "ten_days_ago": ten_days_ago.isoformat(),
            "empty_since": EMPTY_SINCE,
            "empty_until": EMPTY_UNTIL,
        },
        "accounts": {
            "admin": {"username": "admin", "password": ADMIN_PASSWORD},
            "employee": {"username": "employee", "password": EMPLOYEE_PASSWORD},
        },
        "request_ids": {role: str(value) for role, value in ids.items()},
        "metrics": {
            "week7d": week,
            "today": today_metrics,
            "yesterday": yesterday_metrics,
            "month30d": month,
            "empty": empty,
        },
        "requests": requests_total,
        "documents_count": docs_total,
        "detail": {
            "answer_multi": {
                "question": answer_detail["question"],
                "result_kind": answer_detail["result"]["kind"],
                "citation_count": answer_detail["citation_count"],
                "citation": answer_detail["citations"][0],
                "trace_status": answer_detail["trace"]["status"],
            },
            "conflict": {
                "question": conflict_detail["question"],
                "citation_count": conflict_detail["citation_count"],
                "conflicts": conflict_detail["conflicts"],
            },
            "notice": {
                "document_id": notice_doc,
                "name": notice_detail["document"]["name"],
                "versions": [
                    {"number": item["number"], "version_id": item["version_id"], "state": item["state"]}
                    for item in notice_detail.get("versions") or []
                ],
                "import_error_code": failed_import.get("error_code"),
                "import_stage": failed_import.get("stage"),
                "related_requests_count": requests_total["notice_document"],
                "failed_total": docs_total["failed"],
            },
            "manual": {
                "document_id": manual_doc,
                "name": manual_detail["document"]["name"],
                "active_version_number": next(
                    (
                        item["number"]
                        for item in manual_detail.get("versions") or []
                        if item["version_id"] == manual_detail["document"].get("active_version_id")
                    ),
                    None,
                ),
            },
            "launch": {"document_id": launch_doc, "name": "新品宣传初稿", "review_state": "review_required"},
        },
        "eval": {
            "run_ids": ["t306-eval-b0-01", "t306-eval-holdout-01"],
            "skipped_dirs": ["t306-eval-empty"],
            "api_status": runs_payload.get("status"),
            "api_skipped": runs_payload.get("skipped"),
            "runs": {
                run_id: {
                    "case_count": (api_runs[run_id]["manifest"] or {}).get("case_count"),
                    "holdout_detected": api_runs[run_id]["holdout_detected"],
                    "details_withheld": api_runs[run_id]["details_withheld"],
                    "scored_count": (api_runs[run_id]["summary"] or {}).get("scored_count"),
                    "error_count": (api_runs[run_id]["summary"] or {}).get("error_count"),
                    "expected_status": {
                        "t306-eval-b0-01": "已完成",
                        "t306-eval-holdout-01": "已完成",
                    }[run_id],
                }
                for run_id in ("t306-eval-b0-01", "t306-eval-holdout-01")
            },
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

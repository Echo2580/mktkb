"""T304 controlled seed for the QA diagnosis e2e (受控样本, 不触碰 backend/var/).

Writes only the directory passed by ``--data-dir`` plus a Trace SQLite DB inside it.
Dates are anchored to "today" in Asia/Shanghai so window presets stay valid.

Run from repo root:
    .venv\\Scripts\\python.exe -B frontend\\e2e\\operations-qa-seed.py --data-dir <dir>
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
from tests.operations.helpers import make_document, make_request  # noqa: E402

ADMIN_PASSWORD = "AdminPass-1"
EMPLOYEE_PASSWORD = "EmployeePass-1"
CSRF_SECRET = "p3-e2e-csrf-secret-0123456789"
FRONTEND_BASE = "http://127.0.0.1:5300"
TRACE_CLOSED_BASE = "http://127.0.0.1:5302"
ORIGIN = FRONTEND_BASE
SHANGHAI = timezone(timedelta(hours=8), "Asia/Shanghai")
PAGE_SIZE = 20

# 冻结映射（T301 §4）：页面只应渲染这些中文标签。
RAG_LABELS = ["解析计划", "检索召回", "向量召回", "融合排序", "重排", "答案生成", "状态持久化"]
LEGACY_LABELS = ["意图解析", "证据检索", "模型作答", "答案校验", "结果提交"]


def at(day, hour: int, minute: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=SHANGHAI).astimezone(timezone.utc)


def count_requests(client: TestClient, base: dict, page_size: int = PAGE_SIZE) -> tuple[int, int, int]:
    """Return (unique_total, first_page_size, page_count) by walking next_cursor."""
    seen: set[str] = set()
    cursor = None
    page_count = 0
    first_page = 0
    for _ in range(20):
        params = dict(base)
        params["page_size"] = str(page_size)
        if cursor:
            params["cursor"] = cursor
        response = client.get("/api/v1/operations/requests", params=params)
        response.raise_for_status()
        payload = response.json()
        items = payload.get("items") or []
        if page_count == 0:
            first_page = len(items)
        page_count += 1
        for item in items:
            seen.add(item["request_id"])
        cursor = payload.get("next_cursor")
        if not cursor:
            break
    return len(seen), first_page, page_count


def span(
    name: str,
    duration_ms: int | None,
    *,
    status: str = "ok",
    error_code: str | None = None,
    started_at: datetime | None = None,
    parent_span_id: str | None = None,
    attrs: dict | None = None,
) -> SpanRecord:
    return SpanRecord(
        name=name,
        duration_ms=duration_ms,
        status=status,
        error_code=error_code,
        parent_span_id=parent_span_id,
        started_at=started_at.isoformat() if started_at else None,
        attributes_json=json.dumps(attrs, ensure_ascii=False, sort_keys=True) if attrs else None,
    )


def write_trace(
    repo: TraceRepository,
    *,
    request_id: uuid.UUID | str,
    attempt: int,
    path: str,
    outcome: str,
    status: str,
    finished_at: datetime,
    spans: list[SpanRecord],
    replayed: bool = False,
    previous_trace_id: str | None = None,
    error_code: str | None = None,
) -> str:
    trace_id = uuid.uuid4().hex
    total = sum(item.duration_ms or 0 for item in spans)
    repo.write(
        TraceRecord(
            trace_id=trace_id,
            request_id=str(request_id),
            attempt=attempt,
            replayed=replayed,
            previous_trace_id=previous_trace_id,
            mode="local",
            scope="end_to_end",
            path=path,
            outcome_kind=outcome,
            content_mode="hash",
            status=status,
            error_code=error_code,
            latency_ms=total or None,
            created_at=finished_at.isoformat(),
        ),
        spans,
    )
    return trace_id


def write_eval_runs(data_dir: Path, day: datetime) -> dict:
    """Write controlled eval run dirs (manifest/summary/gate + holdout cases + empty dir)."""
    runs_root = data_dir / "eval" / "runs"
    runs_root.mkdir(parents=True, exist_ok=True)
    created = datetime(day.year, day.month, day.day, 1, 30, tzinfo=timezone.utc)

    def dump(run_dir: Path, name: str, payload: dict) -> None:
        (run_dir / name).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    done = runs_root / "qa-eval-b0-01"
    done.mkdir()
    dump(
        done,
        "run_manifest.json",
        {
            "run_id": "qa-eval-b0-01",
            "mode": "local",
            "scope": "end_to_end",
            "suite": "b0",
            "dataset_version": "b0-20261122",
            "case_count": 20,
            "index_revision": 7,
            "created_at": created.isoformat(),
            "gate_version": "g1",
            "holdout_details": False,
            "business_date": day.date().isoformat(),
            "dataset_path": "must-not-leave-whitelist",
        },
    )
    dump(
        done,
        "summary.json",
        {
            "run_id": "qa-eval-b0-01",
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
            "run_id": "qa-eval-b0-01",
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

    failed = runs_root / "qa-eval-b0-02"
    failed.mkdir()
    dump(
        failed,
        "run_manifest.json",
        {
            "run_id": "qa-eval-b0-02",
            "mode": "local",
            "scope": "end_to_end",
            "suite": "b0",
            "dataset_version": "b0-20261122",
            "case_count": 20,
            "index_revision": 7,
            "created_at": (created - timedelta(minutes=50)).isoformat(),
            "gate_version": "g1",
            "holdout_details": False,
        },
    )
    dump(
        failed,
        "summary.json",
        {
            "run_id": "qa-eval-b0-02",
            "mode": "local",
            "scope": "end_to_end",
            "suite": "b0",
            "case_count": 20,
            "scored_count": 14,
            "error_count": 6,
            "metric_values": {"should_not": "leave"},
            "metrics": {"citation_hit": 0.62, "evidence_coverage": 0.7},
        },
    )
    dump(
        failed,
        "gate.json",
        {
            "run_id": "qa-eval-b0-02",
            "suite": "b0",
            "quality_status": "fail",
            "gate_status": {"citation": "fail", "scope": "pass"},
            "failure_count": 2,
            "unknown_count": 0,
            "not_applicable_count": 2,
            "exit_code": 1,
            "hard_failures": ["citation_hit"],
        },
    )

    holdout = runs_root / "qa-eval-holdout-01"
    holdout.mkdir()
    dump(
        holdout,
        "run_manifest.json",
        {
            "run_id": "qa-eval-holdout-01",
            "mode": "local",
            "scope": "end_to_end",
            "suite": "holdout",
            "dataset_version": "holdout-20261122",
            "case_count": 12,
            "index_revision": 7,
            "created_at": (created - timedelta(minutes=120)).isoformat(),
            "gate_version": "g1",
            "holdout_details": True,
        },
    )
    dump(
        holdout,
        "summary.json",
        {
            "run_id": "qa-eval-holdout-01",
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
            "run_id": "qa-eval-holdout-01",
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

    empty = runs_root / "qa-eval-empty"
    empty.mkdir()

    return {
        "runs_root": str(runs_root),
        "run_ids": ["qa-eval-b0-01", "qa-eval-b0-02", "qa-eval-holdout-01"],
        "skipped_dirs": ["qa-eval-empty"],
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
            print(f"SEED_FAILED: {data_dir} 非空且不是上一次 T304 种子目录，拒绝覆盖", file=sys.stderr)
            return 2
    data_dir.mkdir(parents=True, exist_ok=True)

    settings = Settings(
        _env_file=None,
        data_dir=data_dir,
        database_url=f"sqlite:///{(data_dir / 'mktkb.sqlite3').as_posix()}",
        admin_password=ADMIN_PASSWORD,
        employee_password=EMPLOYEE_PASSWORD,
        csrf_secret=CSRF_SECRET,
        trusted_origins=[ORIGIN, TRACE_CLOSED_BASE],
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

    created_ids: dict[str, uuid.UUID] = {}

    try:
        if session.scalar(select(ConversationRequest).limit(1)) is not None:
            print("SEED_FAILED: isolated database already contains requests", file=sys.stderr)
            return 2

        price_doc = make_document(
            session, name="门店产品价目表", file_type="xlsx", states=("published", "published"), units=2, created_at=at(yesterday, 9)
        )
        manual_doc = make_document(
            session, name="门店服务手册", file_type="docx", states=("published",), units=1, created_at=at(yesterday, 9, 30)
        )
        notice_doc = make_document(
            session, name="市场活动补充通知", file_type="pdf", states=("published",), units=1, created_at=at(yesterday, 10)
        )

        price_id = str(price_doc.document.id)
        price_v1 = str(price_doc.versions[0].id)
        price_v2 = str(price_doc.versions[1].id)
        manual_id = str(manual_doc.document.id)
        manual_v1 = str(manual_doc.versions[0].id)
        notice_id = str(notice_doc.document.id)
        notice_v1 = str(notice_doc.versions[0].id)
        manual_unit = manual_doc.units[manual_doc.versions[0].id][0].id
        notice_unit = notice_doc.units[notice_doc.versions[0].id][0].id

        def add(role: str, **kwargs) -> None:
            result = make_request(session, **kwargs)
            created_ids[role] = result.request.id

        add(
            "answer_multi",
            finished_at=at(today, 9, 0),
            question="A 套餐单店价格是多少，含不含饮品？",
            sources=((price_id, price_v2, 0), (price_id, price_v2, 1)),
            revision=5,
            result_text="A 套餐单店价 128 元，含招牌菜一份与饮品一杯。",
        )
        add(
            "answer_superseded",
            finished_at=at(today, 9, 12),
            question="价目表上一版里 B 套餐多少钱？",
            sources=((price_id, price_v1, 0),),
            revision=3,
            result_text="旧版价目表中 B 套餐为 98 元。",
        )
        add(
            "not_found",
            finished_at=at(today, 9, 25),
            kind="not_found",
            question="今天有圣诞礼盒吗？",
            revision=5,
            result_text="暂未找到相关说明。",
        )
        add(
            "conflict",
            finished_at=at(today, 9, 40),
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
            finished_at=at(today, 9, 55),
            kind="service_error",
            question="帮我总结本周门店活动。",
            revision=5,
            error_code="MODEL_TIMEOUT",
            result_text="",
        )
        add(
            "knowledge_changed",
            finished_at=at(today, 10, 10),
            kind="knowledge_changed",
            question="价目表里 A 套餐包含什么？",
            revision=4,
            result_text="原回答基于价目表 V2，该版本已被替换。",
        )
        add(
            "replayed",
            finished_at=at(today, 10, 25),
            question="服务手册里的退换货时限？",
            sources=((manual_id, manual_v1, 0),),
            revision=5,
            result_text="退换货时限为 3 个工作日。",
        )
        add(
            "no_trace",
            finished_at=at(today, 10, 40),
            question="门店营业时间到几点？",
            sources=((manual_id, manual_v1, 0),),
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
            finished_at=at(yesterday, 15, 10),
            question="活动物料什么时候下发？",
            sources=((notice_id, notice_v1, 0),),
            revision=4,
            result_text="活动物料在活动开始前 3 天下发。",
        )

        # 列表分页需要 > 1 页：今日 8 条 + 昨日 6 条填充。
        for index in range(8):
            add(
                f"fill_today_{index}",
                finished_at=at(today, 11, index * 5),
                question=f"今日填充问题 {index + 1}：门店陈列标准是什么？",
                sources=((manual_id, manual_v1, 0),),
                revision=5,
                result_text=f"陈列标准见服务手册第 {index + 1} 条。",
            )
        for index in range(6):
            add(
                f"fill_yesterday_{index}",
                finished_at=at(yesterday, 16, index * 5),
                question=f"昨日填充问题 {index + 1}：活动报名截止时间？",
                sources=((notice_id, notice_v1, 0),),
                revision=4,
                result_text=f"报名截止时间见补充通知第 {index + 1} 条。",
            )
        # 窗口边界外（10 天前），用于 7d / 30d 区分。
        add(
            "answer_ten_days",
            finished_at=at(ten_days_ago, 14, 0),
            question="历史版本里的老套餐还在售吗？",
            sources=((price_id, price_v1, 0),),
            revision=2,
            result_text="历史套餐已停售。",
        )

        session.commit()
    finally:
        session.close()

    trace_repo = TraceRepository(settings.resolved_trace_db_path)
    history = trace_repo.list_window(datetime(1970, 1, 1, tzinfo=timezone.utc))[0]
    if history:
        print("SEED_FAILED: trace database already contains records", file=sys.stderr)
        trace_repo.close()
        return 2

    try:
        base = at(today, 9, 0)
        write_trace(
            trace_repo,
            request_id=created_ids["answer_multi"],
            attempt=1,
            path="rag",
            outcome="answer",
            status="ok",
            finished_at=base,
            spans=[
                span("parse", 42, started_at=base - timedelta(seconds=3), attrs={"plan_steps": 3}),
                span("recall", 380, started_at=base - timedelta(seconds=3), attrs={"candidate_count": 12}),
                span("vector_recall", 210, started_at=base - timedelta(seconds=3), parent_span_id="recall", attrs={"vector_enabled": True, "top_k": 8}),
                span("exact_recall", 60, started_at=base - timedelta(seconds=3), parent_span_id="recall"),
                span("lexical_recall", 90, started_at=base - timedelta(seconds=3), parent_span_id="recall"),
                span("embedding_query", 120, started_at=base - timedelta(seconds=3), parent_span_id="recall"),
                span("hard_filter", 35, started_at=base - timedelta(seconds=2), parent_span_id="recall", attrs={"filtered": 4}),
                span("fuse", 95, started_at=base - timedelta(seconds=2), attrs={"fused": 6}),
                span("rerank", 150, started_at=base - timedelta(seconds=2), parent_span_id="fuse", attrs={"rerank_enabled": True}),
                span("answer", 2400, started_at=base - timedelta(seconds=1), attrs={"model": "local-stub"}),
                span("fact_validate", 70, started_at=base - timedelta(seconds=1), parent_span_id="answer"),
                span("commit", 88, started_at=base),
            ],
        )

        base_sup = at(today, 9, 12)
        write_trace(
            trace_repo,
            request_id=created_ids["answer_superseded"],
            attempt=1,
            path="legacy",
            outcome="answer",
            status="ok",
            finished_at=base_sup,
            spans=[
                span("intent_parse", 30, started_at=base_sup - timedelta(seconds=2)),
                span("retrieve", 260, started_at=base_sup - timedelta(seconds=2), attrs={"hits": 3}),
                span("model_answer", 1800, started_at=base_sup - timedelta(seconds=1)),
                span("answer_validate", 120, started_at=base_sup - timedelta(seconds=1)),
                span("entity_conflict_check", 25, started_at=base_sup, parent_span_id="answer_validate"),
                span("commit", 40, started_at=base_sup),
            ],
        )

        write_trace(
            trace_repo,
            request_id=created_ids["not_found"],
            attempt=1,
            path="legacy",
            outcome="not_found",
            status="ok",
            finished_at=at(today, 9, 25),
            spans=[
                span("intent_parse", 28, started_at=at(today, 9, 25) - timedelta(seconds=1)),
                span("retrieve", 300, started_at=at(today, 9, 25) - timedelta(seconds=1)),
                span("commit", 35, started_at=at(today, 9, 25)),
            ],
        )

        write_trace(
            trace_repo,
            request_id=created_ids["conflict"],
            attempt=1,
            path="rag",
            outcome="conflict",
            status="ok",
            finished_at=at(today, 9, 40),
            spans=[
                span("parse", 40, started_at=at(today, 9, 40) - timedelta(seconds=2)),
                span("recall", 420, started_at=at(today, 9, 40) - timedelta(seconds=2)),
                span("fuse", 110, started_at=at(today, 9, 40) - timedelta(seconds=1)),
                span("answer", 2100, started_at=at(today, 9, 40) - timedelta(seconds=1)),
                span("commit", 90, started_at=at(today, 9, 40)),
            ],
        )

        write_trace(
            trace_repo,
            request_id=created_ids["service_error"],
            attempt=1,
            path="legacy",
            outcome="service_error",
            status="error",
            finished_at=at(today, 9, 55),
            error_code="MODEL_TIMEOUT",
            spans=[
                span("intent_parse", 27, started_at=at(today, 9, 55) - timedelta(seconds=1)),
                span("retrieve", 310, started_at=at(today, 9, 55) - timedelta(seconds=1)),
                span(
                    "model_answer",
                    900,
                    status="error",
                    error_code="MODEL_TIMEOUT",
                    started_at=at(today, 9, 55) - timedelta(seconds=1),
                ),
                span("commit", 45, started_at=at(today, 9, 55)),
            ],
        )

        write_trace(
            trace_repo,
            request_id=created_ids["knowledge_changed"],
            attempt=1,
            path="legacy",
            outcome="knowledge_changed",
            status="ok",
            finished_at=at(today, 10, 10),
            spans=[
                span("intent_parse", 26, started_at=at(today, 10, 10) - timedelta(seconds=1)),
                span("retrieve", 290, started_at=at(today, 10, 10) - timedelta(seconds=1)),
                span("commit", 38, started_at=at(today, 10, 10)),
            ],
        )

        replayed_base = at(today, 10, 25)
        first_trace_id = write_trace(
            trace_repo,
            request_id=created_ids["replayed"],
            attempt=1,
            path="legacy",
            outcome="answer",
            status="ok",
            finished_at=replayed_base,
            spans=[
                span("intent_parse", 25, started_at=replayed_base - timedelta(seconds=1)),
                span("retrieve", 240, started_at=replayed_base - timedelta(seconds=1)),
                span("model_answer", 1500, started_at=replayed_base),
                span("answer_validate", 100, started_at=replayed_base),
                span("commit", 36, started_at=replayed_base),
            ],
        )
        write_trace(
            trace_repo,
            request_id=created_ids["replayed"],
            attempt=2,
            path="legacy",
            outcome="answer",
            status="replayed",
            finished_at=replayed_base + timedelta(seconds=5),
            spans=[],
            replayed=True,
            previous_trace_id=first_trace_id,
        )

        write_trace(
            trace_repo,
            request_id=created_ids["clarification"],
            attempt=1,
            path="rag",
            outcome="clarification",
            status="ok",
            finished_at=at(yesterday, 15, 0),
            spans=[
                span("parse", 35, started_at=at(yesterday, 15, 0) - timedelta(seconds=1)),
                span("commit", 30, started_at=at(yesterday, 15, 0)),
            ],
        )
        trace_repo.close()
    finally:
        trace_repo.close()

    eval_info = write_eval_runs(data_dir, at(today, 0, 0))

    client = TestClient(app, raise_server_exceptions=False)
    login = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": ADMIN_PASSWORD},
        headers={"Origin": ORIGIN},
    )
    if login.status_code != 200:
        print(f"SEED_FAILED: login {login.status_code} {login.text}", file=sys.stderr)
        return 3

    def detail(role: str) -> dict:
        response = client.get(f"/api/v1/operations/requests/{created_ids[role]}")
        response.raise_for_status()
        return response.json()

    week_total, week_first_page, week_pages = count_requests(client, {"window": "7d"})
    today_total, _, _ = count_requests(client, {"window": "today"})
    month_total, _, _ = count_requests(client, {"window": "30d"})
    empty_total, _, _ = count_requests(client, {"window": "custom", "since": "2020-01-01", "until": "2020-01-02"})
    conflict_total, _, _ = count_requests(client, {"window": "7d", "kind": "conflict"})

    multi = detail("answer_multi")
    superseded = detail("answer_superseded")
    conflict = detail("conflict")
    error_detail = detail("service_error")
    no_trace = detail("no_trace")
    replayed = detail("replayed")

    runs_payload = client.get("/api/v1/operations/evaluation-runs").json()
    api_runs = {item["run_id"]: item for item in runs_payload.get("runs") or []}

    summary = {
        "note": "T304 controlled seed (受控样本)；只写隔离目录，不含真实业务数据。",
        "frontend_base": FRONTEND_BASE,
        "trace_closed_base": TRACE_CLOSED_BASE,
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
        "request_ids": {role: str(value) for role, value in created_ids.items()},
        "totals": {
            "week7d": week_total,
            "today": today_total,
            "month30d": month_total,
            "empty": empty_total,
            "conflict_week": conflict_total,
            "page_size": PAGE_SIZE,
            "first_page_rows": week_first_page,
            "pages": week_pages,
        },
        "detail": {
            "answer_multi": {
                "citation_count": multi["citation_count"],
                "citation": multi["citations"][0],
                "trace_status": multi["trace"]["status"],
                "stage_labels": RAG_LABELS,
                "stage_durations": {
                    item["name"]: item["duration_ms"] for item in multi["trace"]["attempts"][0]["spans"]
                },
                "attempts": len(multi["trace"]["attempts"]),
            },
            "answer_superseded": {
                "citation_count": superseded["citation_count"],
                "citation": superseded["citations"][0],
                "stage_labels": LEGACY_LABELS,
            },
            "conflict": {
                "citation_count": conflict["citation_count"],
                "citations": conflict["citations"],
                "conflicts": conflict["conflicts"],
            },
            "service_error": {
                "error_code": error_detail["result"]["error_code"],
                "stages": [item["name"] for item in error_detail["trace"]["attempts"][0]["spans"]],
            },
            "no_trace": {"trace_status": no_trace["trace"]["status"], "attempts": len(no_trace["trace"]["attempts"])},
            "replayed": {
                "attempts": [
                    {"attempt": item["attempt"], "replayed": item["replayed"], "spans": len(item["spans"])}
                    for item in replayed["trace"]["attempts"]
                ],
                "previous_trace_id": replayed["trace"]["attempts"][1]["previous_trace_id"],
            },
        },
        "eval": {
            "run_ids": eval_info["run_ids"],
            "skipped_dirs": eval_info["skipped_dirs"],
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
                        "qa-eval-b0-01": "已完成",
                        "qa-eval-b0-02": "评测失败",
                        "qa-eval-holdout-01": "已完成",
                    }[run_id],
                }
                for run_id in eval_info["run_ids"]
            },
        },
        "documents": {
            "price_document_id": price_id,
            "price_v1_version_id": price_v1,
            "price_v2_version_id": price_v2,
            "manual_document_id": manual_id,
            "notice_document_id": notice_id,
        },
    }

    target = data_dir / "seed-summary.json"
    target.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"SEED_SUMMARY={target}")
    print(f"FRONTEND_BASE={FRONTEND_BASE}")
    print(f"TRACE_CLOSED_BASE={TRACE_CLOSED_BASE}")
    print("SEED_OK")

    app.state.db.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

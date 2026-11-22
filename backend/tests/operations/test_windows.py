"""T302 §5.1 C1/C4/C5/C7：午夜边界、当前库存口径、空分母、超窗拒绝。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from operations.helpers import BASE, make_document, make_request

OPS = "/api/v1/operations"


def _error_code(response) -> str:
    assert response.status_code == 422, response.text
    return response.json()["error"]["code"]


def test_midnight_boundary_is_left_closed_right_open(admin_client, db) -> None:
    """15:59:59Z / 16:00:00Z 分属 Shanghai 11-20 / 11-21，左闭右开不重不漏。"""
    before = make_request(
        db, finished_at=datetime(2026, 11, 20, 15, 59, 59, 750000, tzinfo=timezone.utc), kind="answer"
    )
    after = make_request(
        db, finished_at=datetime(2026, 11, 20, 16, 0, 0, 250000, tzinfo=timezone.utc), kind="answer"
    )
    db.commit()

    first = admin_client.get(
        f"{OPS}/overview", params={"since": "2026-11-20", "until": "2026-11-20"}
    )
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["window"]["window"] == "custom"
    assert body["window"]["timezone"] == "Asia/Shanghai"
    assert body["window"]["since_utc"] == "2026-11-19T16:00:00.000+00:00"
    assert body["window"]["until_utc"] == "2026-11-20T16:00:00.000+00:00"
    assert body["metrics"]["completed_requests"] == 1
    assert body["trend"] == [{"date": "2026-11-20", "completed": 1, "citations": 0}]

    second = admin_client.get(
        f"{OPS}/overview", params={"since": "2026-11-21", "until": "2026-11-21"}
    )
    assert second.status_code == 200, second.text
    body = second.json()
    assert body["metrics"]["completed_requests"] == 1
    assert body["trend"] == [{"date": "2026-11-21", "completed": 1, "citations": 0}]

    both = admin_client.get(
        f"{OPS}/overview", params={"since": "2026-11-20", "until": "2026-11-21"}
    ).json()
    assert both["metrics"]["completed_requests"] == 2
    ids = {item["request_id"] for item in admin_client.get(
        f"{OPS}/requests", params={"since": "2026-11-20", "until": "2026-11-21"}
    ).json()["items"]}
    assert ids == {str(before.request.id), str(after.request.id)}


def test_current_inventory_is_window_independent(admin_client, db) -> None:
    """待审核版本与生效资料是当前库存，不随窗口回溯；下钻条件同口径。"""
    doc = make_document(db, name="待审核资料", states=("review_required",), active=False)
    active = make_document(db, name="生效资料")
    db.commit()

    for window in ({"since": "2020-01-01", "until": "2020-01-02"}, {"window": "7d"}):
        body = admin_client.get(f"{OPS}/overview", params=window).json()
        assert body["metrics"]["review_required_versions"] == 1
        assert body["metrics"]["active_documents"] == 1
        assert body["metrics"]["basis"] == "current"
        assert body["metrics"]["completed_requests"] == 0

    documents = admin_client.get(f"{OPS}/documents", params={"since": "2020-01-01", "until": "2020-01-02"}).json()
    states = {item["document_id"]: item["current_version"]["state"] for item in documents["items"]}
    assert states[str(doc.document.id)] == "review_required"
    assert states[str(active.document.id)] == "published"


def test_empty_window_returns_zero_and_no_fake_percentages(admin_client) -> None:
    body = admin_client.get(
        f"{OPS}/overview", params={"since": "2020-01-01", "until": "2020-01-01"}
    ).json()
    assert body["metrics"]["completed_requests"] == 0
    assert body["trend"] == []
    assert body["result_distribution"] == {
        "answer": 0,
        "clarification": 0,
        "not_found": 0,
        "conflict": 0,
        "service_error": 0,
        "knowledge_changed": 0,
    }
    assert body["pending"] == []
    # Trace 关闭时独立状态且不报覆盖率数值
    assert body["trace_coverage"]["status"] == "disabled"
    assert body["trace_coverage"]["covered"] is None
    assert body["trace_coverage"]["total"] is None

    requests = admin_client.get(
        f"{OPS}/requests", params={"since": "2020-01-01", "until": "2020-01-01"}
    ).json()
    assert requests["items"] == []
    assert requests["next_cursor"] is None


@pytest.mark.parametrize(
    "params, code",
    [
        ({"since": "2026-01-01", "until": "2026-04-01"}, "INVALID_WINDOW"),  # 91 天
        ({"since": "2026-11-21", "until": "2026-11-20"}, "INVALID_WINDOW"),
        ({"since": "2026-11-20"}, "INVALID_WINDOW"),
        ({"until": "2026-11-20"}, "INVALID_WINDOW"),
        ({"window": "90d"}, "INVALID_WINDOW"),
        ({"since": "2026-11-20", "until": "not-a-date"}, "INVALID_WINDOW"),
        ({"page_size": 101}, "INVALID_PAGE_SIZE"),
        ({"page_size": 0}, "INVALID_PAGE_SIZE"),
        ({"kind": "unknown_kind"}, "INVALID_KIND"),
    ],
)
def test_invalid_window_and_paging_are_422(admin_client, params: dict, code: str) -> None:
    assert _error_code(admin_client.get(f"{OPS}/requests", params=params)) == code
    if "page_size" not in params and "kind" not in params:
        assert _error_code(admin_client.get(f"{OPS}/overview", params=params)) == code


def test_ninety_day_custom_window_is_allowed(admin_client) -> None:
    response = admin_client.get(
        f"{OPS}/overview", params={"since": "2026-08-24", "until": "2026-11-21"}
    )
    assert response.status_code == 200, response.text
    assert response.json()["window"]["window"] == "custom"


def test_long_window_does_not_shift_inventory_drilldown(admin_client, db) -> None:
    """自定义窗口与今日窗口的库存下钻（documents 列表）保持同一当前状态。"""
    doc = make_document(db, name="待审核资料二", states=("review_required",), active=False)
    db.commit()
    for params in ({"window": "today"}, {"since": "2019-01-01", "until": "2019-01-02"}):
        items = admin_client.get(f"{OPS}/documents", params=params).json()["items"]
        target = next(item for item in items if item["document_id"] == str(doc.document.id))
        assert target["current_version"]["state"] == "review_required"

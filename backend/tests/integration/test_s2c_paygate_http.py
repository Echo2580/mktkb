"""S2-C 组合链路回归：正常应用 build_gateway → 生产 BudgetedModelGateway → TestClient → MockTransport。

证明正文/非 rag-owned 问题的请求体输出上限、共享 reserved/transport/result、合法来源返回，
以及 GO 过期/预算收窄后旧 app 下一轮零发送。全部使用副本账本/预算/GO、假凭据与 MockTransport。
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import openpyxl
import pytest
from fastapi.testclient import TestClient

import mktkb.main as main_module
from mktkb import live_authorization as gate_module
from mktkb.config import Settings
from mktkb.documents.lifecycle import get_revision
from mktkb.ingestion.worker import run_one_job
from mktkb.main import create_app
from mktkb.providers import build_gateway as real_build_gateway
from mktkb.rag.settlement_policy import SETTLEMENT_VERSION

STAGE = "S2-C-HTTP"
ORIGIN = "http://testserver"
HISTORY_CNY = 0.03
# 隔离预算的总上限：测试内用同值环境变量，自洽即可，不再跟随仓库真实预算（20 元）。
PROJECT_TOTAL_LIMIT_CNY = 10.0
PRICING_ENV = {
    "MKTKB_MODEL_BASE_URL": "https://api.deepseek.com/v1",
    "MKTKB_MODEL_NAME": "deepseek-flash",
    "MKTKB_MODEL_API_KEY": "s2c-http-mock-key",
    "MKTKB_MODEL_INPUT_PRICE_PER_MILLION_CNY": "2",
    "MKTKB_MODEL_OUTPUT_PRICE_PER_MILLION_CNY": "8",
    "MKTKB_MODEL_MAX_INPUT_TOKENS": "6144",
    "MKTKB_MODEL_MAX_OUTPUT_TOKENS": "800",
    "MKTKB_MODEL_CONTEXT_CEILING_TOKENS": "1048576",
    "MKTKB_MODEL_RESERVE_PROFILE": "model_context_ceiling",
}


def _sha(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_go(path: Path, ledger: Path, **overrides) -> None:
    now = datetime.now(timezone.utc)
    payload = {
        "document": "S2-LIVE-GO",
        "stage": STAGE,
        "authorization": "S2-C-HTTP-MOCK-GO",
        "issued_by": "pytest",
        "nonce": "s2c-http-nonce-0123456789",
        "issued_utc": (now - timedelta(minutes=5)).isoformat(),
        "expires_utc": (now + timedelta(hours=1)).isoformat(),
        "budget_ledger_sha256": _sha(ledger),
        "scope": {
            "services": ["rag", "chat"],
            "stage_limits_cny": {STAGE: 5.0},
            "max_requests": 5,
            "max_request_cny": 2.11,
            "bindings": {
                "rag": {
                    "base_url_host": "mock.dashscope.invalid",
                    "embedding_model": "text-embedding-v4",
                    "embedding_dimensions": 1024,
                    "rerank_model": "gte-rerank-v2",
                    "region": "unknown",
                },
                "chat": {
                    "base_url_host": "api.deepseek.com",
                    "model": "deepseek-flash",
                    "thinking": "disabled",
                    "max_input_tokens": 6144,
                    "max_output_tokens": 800,
                    "reserve_profile": "model_context_ceiling",
                    "context_ceiling_tokens": 1048576,
                    "input_price_per_million_cny": 2.0,
                    "output_price_per_million_cny": 8.0,
                    # create_app 会按产品路径挂版本化 chat 结算策略；GO 未声明版本会被拒绝装配。
                    "settlement_version": SETTLEMENT_VERSION,
                },
            },
        },
    }
    for key, value in overrides.items():
        payload[key] = value
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_ledger(path: Path, *, historical: float = HISTORY_CNY) -> None:
    """自建隔离账本：只含一行 historical_import，不复制仓库共享账本。

    共享账本会随真实阶段增长（当前 83 笔预留），复制它会让“累计请求上限/预留计数”
    断言随真实用量漂移。
    """
    path.write_text(
        json.dumps({"event": "historical_import", "accounted_cny": historical}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _write_budget(path: Path, ledger: Path, *, stage_limit: float = 5.0) -> None:
    """自建隔离预算：limit_cny 与测试环境变量同值，stages 只声明本用例阶段。"""
    budget = {
        "limit_cny": PROJECT_TOTAL_LIMIT_CNY,
        "historical_conservative_accounted_cny": HISTORY_CNY,
        "stages": {STAGE: stage_limit},
        "ledger": str(ledger),
    }
    path.write_text(json.dumps(budget, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


@pytest.fixture
def http_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    ledger = tmp_path / "live-ledger.jsonl"
    _write_ledger(ledger)
    budget = tmp_path / "budget.json"
    _write_budget(budget, ledger)
    go = tmp_path / "S2-LIVE-GO.json"
    _write_go(go, ledger)
    monkeypatch.setattr(gate_module, "SHARED_LEDGER_PATH", ledger)
    monkeypatch.setattr(gate_module, "SHARED_BUDGET_PATH", budget)
    monkeypatch.setattr(gate_module, "PRODUCT_GO_PATH", go)
    # 三件套一致：budget.limit_cny == MKTKB_PROJECT_TOTAL_LIMIT_CNY == 10.0。
    monkeypatch.setenv("MKTKB_PROJECT_TOTAL_LIMIT_CNY", str(PROJECT_TOTAL_LIMIT_CNY))
    monkeypatch.setenv("MKTKB_LIVE_STAGE", STAGE)
    monkeypatch.setenv("MKTKB_RAG_STAGE_LIMIT_CNY", "5.0")
    monkeypatch.setenv("MKTKB_RAG_MAX_REQUESTS", "5")
    for key, value in PRICING_ENV.items():
        monkeypatch.setenv(key, value)
    for key in ("MKTKB_RAG_BUDGET_LEDGER", "MKTKB_RAG_BUDGET_JSON", "MKTKB_RAG_STAGE"):
        monkeypatch.delenv(key, raising=False)
    return {"ledger": ledger, "budget": budget, "go": go, "root": tmp_path}


def _write_store_xlsx(path: Path) -> Path:
    workbook = openpyxl.Workbook()
    worksheet = workbook.active
    worksheet.title = "门店联系表"
    worksheet.append(["标题"])
    worksheet.append([])
    for column, header in enumerate(["门店", "联系人", "联系电话", "地址", "合作状态"], start=1):
        worksheet.cell(row=3, column=column, value=header)
    for offset, row in enumerate(
        [
            ["北辰店", "骆青", "0571-8800-0011", "北辰路11号", "合作中"],
            ["南湖店", "闵竹", "0573-8800-0022", "南湖路22号", "暂停"],
        ]
    ):
        for column, value in enumerate(row, start=1):
            worksheet.cell(row=4 + offset, column=column, value=value)
    workbook.save(path)
    return path


def test_http_uses_production_budgeted_gateway_and_stops_after_go_or_budget_change(http_env, monkeypatch):
    posts: dict[str, object] = {"count": 0, "bodies": []}

    def handler(request: httpx.Request) -> httpx.Response:
        posts["count"] = int(posts["count"]) + 1
        body = json.loads(request.content.decode("utf-8"))
        posts["bodies"].append(body)  # type: ignore[union-attr]
        user = json.loads(body["messages"][1]["content"])
        evidence = (user.get("evidence") or [{}])[0]
        fields = evidence.get("fields") or {}
        return httpx.Response(
            200,
            json={
                "id": f"mock-http-{posts['count']}",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(
                                {
                                    "answer": f"{fields.get('门店')}的电话：{fields.get('联系电话')}",
                                    "source_ids": [evidence.get("source_id")],
                                },
                                ensure_ascii=False,
                            )
                        },
                    }
                ],
                # 版本化 chat 结算要求官方 cache 拆分：hit + miss 必须等于 prompt_tokens。
                "usage": {
                    "prompt_tokens": 30,
                    "completion_tokens": 12,
                    "total_tokens": 42,
                    "prompt_cache_hit_tokens": 0,
                    "prompt_cache_miss_tokens": 30,
                },
            },
        )

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(main_module, "build_gateway", lambda settings: real_build_gateway(settings, transport=transport))
    settings = Settings(
        _env_file=None,
        data_dir=http_env["root"] / "store",
        database_url=f"sqlite:///{(http_env['root'] / 'store' / 'h.sqlite3').as_posix()}",
        storage_dir=http_env["root"] / "store" / "storage",
        cookie_secure=False,
        csrf_secret="s2c-http-csrf-secret-0123456789",
        admin_password="HttpAdminPass-1",
        employee_password="HttpEmployeePass-1",
        trusted_origins=[ORIGIN],
        bcrypt_rounds=4,
        session_ttl_seconds=3600,
        log_level="WARNING",
        rag_qa_enabled=False,
        model_base_url=PRICING_ENV["MKTKB_MODEL_BASE_URL"],
        model_name=PRICING_ENV["MKTKB_MODEL_NAME"],
        model_api_key=PRICING_ENV["MKTKB_MODEL_API_KEY"],
    )
    app = create_app(settings)

    def headers(csrf: str) -> dict[str, str]:
        return {"Origin": ORIGIN, "X-CSRF-Token": csrf}

    def session(username: str, password: str) -> tuple[TestClient, dict[str, str]]:
        client = TestClient(app, raise_server_exceptions=False)
        response = client.post("/api/v1/auth/login", json={"username": username, "password": password}, headers={"Origin": ORIGIN})
        assert response.status_code == 200, response.text
        me = client.get("/api/v1/auth/me")
        return client, headers(me.json()["csrf_token"])

    admin, admin_headers = session("admin", settings.admin_password)
    xlsx = _write_store_xlsx(Path(settings.data_dir) / "stores.xlsx")
    with xlsx.open("rb") as handle:
        receipt = admin.post(
            "/api/v1/documents",
            files={"file": ("stores.xlsx", handle, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            headers=admin_headers,
        )
    assert receipt.status_code == 202, receipt.text
    record = receipt.json()
    db = app.state.db.session()
    try:
        assert run_one_job(db, app.state.store).state == "succeeded"
        revision = int(get_revision(db))
    finally:
        db.close()
    published = admin.post(
        f"/api/v1/documents/{record['document']['id']}/versions/{record['version']['id']}/publish",
        headers=admin_headers,
        json={"expected_active_version_id": None, "expected_revision": revision},
    )
    assert published.status_code == 200, published.text
    employee, _ = session("employee", settings.employee_password)

    def new_conversation(client: TestClient) -> str:
        csrf = client.get("/api/v1/auth/me").json()["csrf_token"]
        response = client.post("/api/v1/conversations", json={}, headers=headers(csrf))
        assert response.status_code == 201, response.text
        return response.json()["id"]

    def ask(client: TestClient, conversation: str, question: str) -> dict:
        csrf = client.get("/api/v1/auth/me").json()["csrf_token"]
        response = client.post(
            f"/api/v1/conversations/{conversation}/messages",
            json={"client_request_id": str(uuid.uuid4()), "question": question},
            headers=headers(csrf),
        )
        assert response.status_code == 200, response.text
        return response.json()

    first = ask(employee, new_conversation(employee), "北辰店的电话是多少？")
    gateway = app.state.model_gateway
    summary = gateway._budget.summary().as_dict()  # noqa: SLF001 - 测试读取共享账本
    assert first["kind"] == "answer"
    assert first["sources"]
    assert posts["count"] == 1
    assert (posts["bodies"][0]).get("max_tokens") == 800  # type: ignore[index]
    assert summary["reservation_count"] >= 1 and summary["result_count"] >= 1

    _write_go(http_env["go"], http_env["ledger"], expires_utc=(datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat())
    before = posts["count"]
    expired = ask(employee, new_conversation(employee), "南湖店的电话是多少？")
    assert expired["kind"] == "service_error"
    assert posts["count"] == before

    _write_go(http_env["go"], http_env["ledger"])
    _write_budget(http_env["budget"], http_env["ledger"], stage_limit=0.00001)
    reserved_before = app.state.model_gateway._budget.summary().as_dict()["reservation_count"]  # noqa: SLF001
    narrowed = ask(employee, new_conversation(employee), "北辰店的地址是什么？")
    assert narrowed["kind"] == "service_error"
    # 预算/授权拒绝必须给出稳定原因码（不是“服务不可用”），且请求未发出、账本无新增预留。
    assert narrowed["error_code"] == "MODEL_BUDGET_REFUSED"
    assert narrowed["retryable"] is False
    assert "预算或授权额度不足" in narrowed["text"]
    assert posts["count"] == before
    narrowed_summary = app.state.model_gateway._budget.summary().as_dict()  # noqa: SLF001
    assert narrowed_summary["reservation_count"] == reserved_before

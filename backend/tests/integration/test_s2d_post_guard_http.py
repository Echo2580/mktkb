"""S2-D 组合链路回归：TestClient → 正常应用 build_gateway → MockTransport 的发送前复核。

本文件只补本轮窗口：预留成功后、真实 POST 前 GO 失效，必须零发送、返回可诊断错误、
该笔预留与保守占用仍可归因。全部使用 tmp_path 副本账本/预算/GO、假凭据与 MockTransport。
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
from mktkb.providers.deepseek import DeepSeekClient
from mktkb.rag.settlement_policy import SETTLEMENT_VERSION

STAGE = "S2-D-HTTP"
ORIGIN = "http://testserver"
HISTORY_CNY = 0.03
# 隔离预算的总上限：测试内用同值环境变量，自洽即可，不再跟随仓库真实预算（20 元）。
PROJECT_TOTAL_LIMIT_CNY = 10.0
PRICING_ENV = {
    "MKTKB_MODEL_BASE_URL": "https://api.deepseek.com/v1",
    "MKTKB_MODEL_NAME": "deepseek-flash",
    "MKTKB_MODEL_API_KEY": "s2d-http-mock-key",
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
        "authorization": "S2-D-HTTP-MOCK-GO",
        "issued_by": "pytest",
        "nonce": "s2d-http-nonce-0123456789",
        "issued_utc": (now - timedelta(minutes=5)).isoformat(),
        "expires_utc": (now + timedelta(hours=1)).isoformat(),
        "budget_ledger_sha256": _sha(ledger),
        "scope": {
            "services": ["rag", "chat"],
            "stage_limits_cny": {STAGE: 5.0},
            "max_requests": 20,
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
        if key == "scope":
            payload["scope"] = {**payload["scope"], **value}
        else:
            payload[key] = value
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_ledger(path: Path, *, historical: float = HISTORY_CNY) -> None:
    """自建隔离账本：只含一行 historical_import，不复制仓库共享账本。

    共享账本会随真实阶段增长（当前 83 笔预留），复制它会让“预留/结果计数”
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


def test_http_refuses_after_reserve_before_post_when_go_expires(http_env, monkeypatch):
    posts: dict[str, int] = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        posts["count"] += 1
        body = json.loads(request.content.decode("utf-8"))
        user = json.loads(body["messages"][1]["content"])
        evidence = (user.get("evidence") or [{}])[0]
        fields = evidence.get("fields") or {}
        return httpx.Response(
            200,
            json={
                "id": f"mock-s2d-http-{posts['count']}",
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
        csrf_secret="s2d-http-csrf-secret-0123456789",
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

    # 正常一轮：生产网关仍可真实到达 MockTransport（回归保护）。
    first = ask(employee, new_conversation(employee), "北辰店的电话是多少？")
    assert first["kind"] == "answer"
    assert posts["count"] == 1

    ledger = app.state.model_gateway._budget  # noqa: SLF001 - 测试读取共享账本
    before_posts = posts["count"]
    before = ledger.summary().as_dict()

    # 受控注入：client 已创建/锁等待 await 结束后、client.post 之前让 GO 过期。
    original = DeepSeekClient._client_or_create

    async def expire_after_client(self):  # noqa: ANN001
        client = await original(self)
        _write_go(
            http_env["go"],
            http_env["ledger"],
            expires_utc=(datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
        )
        return client

    monkeypatch.setattr(DeepSeekClient, "_client_or_create", expire_after_client)
    refused = ask(employee, new_conversation(employee), "南湖店的电话是多少？")
    after = ledger.summary().as_dict()

    assert refused["kind"] == "service_error"
    assert refused["error_code"] == "MODEL_POST_SEND_AUTH_DENIED"
    assert posts["count"] == before_posts  # 零 transport
    assert after["reservation_count"] == before["reservation_count"] + 1
    assert after["result_count"] == before["result_count"] + 1
    assert after["accounted_cny"] - before["accounted_cny"] > 0

    events = [json.loads(line) for line in http_env["ledger"].read_text(encoding="utf-8").splitlines() if line.strip()]
    reserved = [event for event in events if event["event"] == "reserved"][-1]
    result = [
        event
        for event in events
        if event["event"] == "result" and event["reservation_id"] == reserved["reservation_id"]
    ]
    assert len(result) == 1
    assert result[0]["error_code"] == "MODEL_POST_SEND_AUTH_DENIED"
    # 重启（新账本实例）后该笔保守占用仍在，不清账。
    restarted = _summary_after_restart(http_env)
    assert restarted["accounted_cny"] == after["accounted_cny"]
    assert restarted["reservation_count"] == after["reservation_count"]

    # ---------------------------------------------------------------- 预算拒绝（HTTP 级）
    # 本单验收点：预留阶段“预算/授权”拒绝必须给出稳定原因码（不再伪装成服务不可用），
    # 且零 HTTP、账本无新增 reserved。先恢复有效 GO，确保拒绝原因是预算而不是授权时效。
    _write_go(http_env["go"], http_env["ledger"])
    _write_budget(http_env["budget"], http_env["ledger"], stage_limit=0.00001)
    budget_before = ledger.summary().as_dict()
    budget_refused = ask(employee, new_conversation(employee), "北辰店的地址是什么？")
    assert budget_refused["kind"] == "service_error"
    assert budget_refused["error_code"] == "MODEL_BUDGET_REFUSED"
    assert budget_refused["retryable"] is False
    assert "预算或授权额度不足" in budget_refused["text"]
    assert posts["count"] == before_posts  # 预算拒绝不得发出任何 HTTP
    budget_after = ledger.summary().as_dict()
    assert budget_after["reservation_count"] == budget_before["reservation_count"]
    assert budget_after == budget_before


def _summary_after_restart(env: dict[str, Path]) -> dict:
    """新账本实例（不经过 app 状态、不进实时闸门）重算同一份共享账本。"""
    from mktkb.rag.budget import BudgetLedger

    ledger = BudgetLedger(
        env["ledger"], env["budget"], stage=STAGE, stage_limit_cny=5.0, max_requests=5
    )
    return ledger.summary().as_dict()

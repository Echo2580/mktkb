"""T09-D1 / 交付物 4：真实调用闸门（R 层执行器）。本轮**只交付、只跑 --dry-run**，不得 --live。

设计要点（对应任务单第 4 条）：
1. 用 ``httpx`` transport 包装真实 ``DeepSeekClient`` / ``TencentOCRClient``：每次 HTTP 请求（含重试）
   都先经过 :class:`CountingTransport`，逐次计数并执行硬上限；
2. 硬上限默认 20，达到上限后**不再发出请求**并立即中止（不是发出后再统计）；
3. JSONL 台账逐条记录：时间、动作、题号/用例、耗时、状态码、OCR RequestId 或模型 usage、重试序号；
4. 密钥只从 ``Settings``（服务端 .env）读取，**任何情况下都不打印、不落盘**；台账只记录
   目标主机名与不可逆指纹（sha256 前 8 位）用于核对配置身份；
5. 默认 ``--dry-run``；``--live`` 还需环境变量 ``T09_LIVE_ACK=REAL-OK`` 双重确认，任缺其一立即拒绝。

用法：
    # 本轮唯一允许的运行方式（不会触网）
    python -B backend/tests/acceptance/live_r_runner.py --dry-run
    # 未来获得主人明确授权后（本轮禁止）
    python -B backend/tests/acceptance/live_r_runner.py --live --max-requests 20
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend" / "src"))

from mktkb.providers.deepseek import DeepSeekClient  # noqa: E402
from mktkb.providers.tencent_ocr import TencentOCRClient  # noqa: E402
from mktkb.providers.types import (  # noqa: E402
    CompletionInput,
    ModelEvidence,
    OCRInput,
    OCRPageResult,
)

FIXTURES = ROOT / "fixtures" / "acceptance"
NORMAL = FIXTURES / "normal"
DEFAULT_LEDGER_DIR = ROOT / "docs" / "evidence" / "T09" / "D1" / "actual" / "live-r"
DEFAULT_MAX_REQUESTS = 20
LIVE_ACK_ENV = "T09_LIVE_ACK"
LIVE_ACK_VALUE = "REAL-OK"

# R 层首轮建议载荷（《验收矩阵》§8：3 个模拟问答 + 1 张文字图 + 1 张规则表格图）
PLAN: list[dict[str, Any]] = [
    {"case_id": "R-Q01", "kind": "model", "purpose": "answer", "question": "城东店的宣传海报在哪里？"},
    {"case_id": "R-Q13", "kind": "model", "purpose": "answer", "question": "城东店的联系电话是什么？"},
    {"case_id": "R-Q25", "kind": "model", "purpose": "answer", "question": "领取活动物料需要哪些步骤？"},
    {"case_id": "R-OCR-D09", "kind": "ocr", "mode": "text", "file": "D09_物料领用通知.png"},
    {"case_id": "R-OCR-D10", "kind": "ocr", "mode": "table", "file": "D10_盘点通知.jpg"},
]

EVIDENCE_Q01 = [
    {
        "source_id": "r-evidence-p01",
        "text": "标识: P01 | 门店: 城东店 | 物品: 宣传海报 | 别名: 海报 | 位置: B区1号货架第二层",
        "fields": {"标识": "P01", "门店": "城东店", "物品": "宣传海报", "位置": "B区1号货架第二层"},
    }
]


class LiveBudgetExceeded(RuntimeError):
    """硬上限被触发：拒绝再发请求。"""


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def _fingerprint(value: str | None) -> str | None:
    """不可逆指纹：只用于核对"用的是哪份配置"，无法反推密钥。"""
    if not value:
        return None
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]


class Ledger:
    """JSONL 台账：逐条追加，失败重试也各一条；绝不写入密钥、Authorization 或请求体原文。"""

    def __init__(self, path: Path, *, mode: str, max_requests: int) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            raise SystemExit(f"台账已存在，拒绝覆盖：{self.path}（请换 --ledger 或用新 label）")
        self._handle = self.path.open("w", encoding="utf-8")
        self.mode = mode
        self.max_requests = max_requests
        self.used = 0
        self.records: list[dict] = []

    def reserve(self, *, case_id: str, action: str) -> int:
        if self.used >= self.max_requests:
            raise LiveBudgetExceeded(
                f"真实调用硬上限已达上限 {self.max_requests}，拒绝继续发请求（case={case_id}）"
            )
        self.used += 1
        return self.used

    def write(self, record: dict) -> None:
        payload = {"ts": _now(), "mode": self.mode, **record}
        self._handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
        self._handle.flush()
        self.records.append(payload)

    def close(self) -> None:
        self._handle.close()

    def summary(self) -> dict:
        return {
            "mode": self.mode,
            "ledger": str(self.path),
            "requests_used": self.used,
            "max_requests": self.max_requests,
            "records": len(self.records),
        }


class CountingTransport(httpx.AsyncBaseTransport):
    """异步计数传输：包住真实 transport，逐请求计数并写台账。"""

    def __init__(self, inner: httpx.AsyncBaseTransport, ledger: Ledger, case_id: str) -> None:
        self._inner = inner
        self._ledger = ledger
        self._case_id = case_id

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        ordinal = self._ledger.reserve(case_id=self._case_id, action=f"model {request.url.path}")
        started = time.monotonic()
        status = None
        try:
            response = await self._inner.handle_async_request(request)
            status = response.status_code
            return response
        finally:
            self._ledger.write(
                {
                    "case_id": self._case_id,
                    "action": "model.chat.completions",
                    "attempt": ordinal,
                    "host": request.url.host,
                    "path": request.url.path,
                    "elapsed_ms": round((time.monotonic() - started) * 1000, 1),
                    "status_code": status,
                }
            )


class CountingSyncTransport(httpx.BaseTransport):
    """同步计数传输（腾讯云 OCR 客户端为同步）。"""

    def __init__(self, inner: httpx.BaseTransport, ledger: Ledger, case_id: str, mode: str) -> None:
        self._inner = inner
        self._ledger = ledger
        self._case_id = case_id
        self._mode = mode

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        ordinal = self._ledger.reserve(case_id=self._case_id, action="ocr")
        started = time.monotonic()
        status = None
        request_id = None
        try:
            response = self._inner.handle_request(request)
            status = response.status_code
            try:
                body = response.json()
            except ValueError:
                body = None
            if isinstance(body, dict) and isinstance(body.get("Response"), dict):
                candidate = body["Response"].get("RequestId")
                request_id = candidate if isinstance(candidate, str) else None
            return response
        finally:
            self._ledger.write(
                {
                    "case_id": self._case_id,
                    "action": f"ocr.{self._mode}",
                    "attempt": ordinal,
                    "host": request.url.host,
                    "path": request.url.path,
                    "elapsed_ms": round((time.monotonic() - started) * 1000, 1),
                    "status_code": status,
                    "ocr_request_id": request_id,
                }
            )


def _config_facts(*, allow_read: bool) -> dict:
    """配置事实：只有 --live 才允许读取真实配置，且只报告存在性与不可逆指纹。

    本轮纪律禁止读取真实 `.env`/密钥，因此 dry-run 一律不构造 ``Settings``，只如实声明"未读取"。
    """
    if not allow_read:
        return {
            "real_config_read": False,
            "note": "dry-run 不读取 .env/真实密钥（本轮纪律）；仅验证适配器、计数闸门与台账",
        }
    try:
        from mktkb.config import Settings
    except Exception as exc:  # pragma: no cover - 依赖缺失时如实报告
        return {"real_config_read": False, "error": f"{type(exc).__name__}"}
    try:
        settings = Settings()
    except Exception as exc:
        return {"real_config_read": True, "error": type(exc).__name__, "detail": "配置不可读取（缺失必填项或 .env 不存在）"}
    model_key = settings.model_api_key.get_secret_value() if settings.model_api_key else None
    ocr_id = settings.ocr_secret_id.get_secret_value() if settings.ocr_secret_id else None
    return {
        "real_config_read": True,
        "model_configured": bool(settings.model_base_url and settings.model_name and model_key),
        "model_host": (settings.model_base_url or "").split("/")[2] if settings.model_base_url else None,
        "model_name": settings.model_name,
        "model_key_fingerprint": _fingerprint(model_key),
        "ocr_configured": bool(ocr_id and settings.ocr_secret_key),
        "ocr_endpoint_host": (settings.ocr_endpoint or "").split("/")[2] if settings.ocr_endpoint else None,
        "ocr_region": settings.ocr_region,
        "ocr_secret_id_fingerprint": _fingerprint(ocr_id),
    }


def _build_real_clients(ledger: Ledger):
    """按服务端配置构建真实客户端，并把计数传输包在真实 transport 外层。"""
    from mktkb.config import Settings

    settings = Settings()
    if not settings.model_api_key or not settings.model_base_url or not settings.model_name:
        raise SystemExit("模型未配置：本轮 R 层无法执行（不构造空客户端）")
    model_client = DeepSeekClient(
        base_url=settings.model_base_url,
        model=settings.model_name,
        api_key=settings.model_api_key.get_secret_value(),
        timeout_seconds=settings.model_request_timeout_seconds,
        transport=CountingTransport(httpx.AsyncHTTPTransport(), ledger, "model"),
    )
    ocr_client = None
    if settings.ocr_secret_id and settings.ocr_secret_key:
        ocr_client = TencentOCRClient(
            secret_id=settings.ocr_secret_id.get_secret_value(),
            secret_key=settings.ocr_secret_key.get_secret_value(),
            region=settings.ocr_region,
            endpoint=settings.ocr_endpoint,
            timeout_seconds=settings.ocr_request_timeout_seconds,
            transport=None,  # 由 plan 执行时按用例包装
        )
    return settings, model_client, ocr_client


def _mock_model_response(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content.decode("utf-8"))
    user_blob = json.loads(body["messages"][1]["content"])
    if "terms" in user_blob.get("instruction", "") or user_blob.get("question", "").startswith("[expand]"):
        content = json.dumps({"terms": ["宣传海报", "城东店"]}, ensure_ascii=False)
    else:
        content = json.dumps(
            {"answer": "根据资料：城东店的宣传海报位于 B区1号货架第二层。", "source_ids": ["r-evidence-p01"]},
            ensure_ascii=False,
        )
    return httpx.Response(
        200,
        json={
            "id": "mock-deepseek-0001",
            "model": body.get("model"),
            "choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": content}}],
            "usage": {"prompt_tokens": 128, "completion_tokens": 32, "total_tokens": 160},
        },
    )


def _mock_ocr_text_response(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "Response": {
                "RequestId": "mock-ocr-text-0001",
                "TextDetections": [
                    {"DetectedText": "物料领用通知", "Confidence": 91.0, "Polygon": [{"X": 60, "Y": 50}]},
                    {"DetectedText": "领取活动物料前，请填写领用登记表并由负责人确认。", "Confidence": 88.5},
                ],
            }
        },
    )


def _mock_ocr_table_response(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"Response": {"RequestId": "mock-ocr-table-0001", "TableDetections": []}})


def run_dry_run(ledger: Ledger, *, max_requests: int) -> dict:
    """完全不触网：用 httpx.MockTransport 走真实适配器 + 计数闸门 + 台账，并自检硬上限。"""
    results: list[dict] = []
    model_transport = httpx.MockTransport(_mock_model_response)
    counting_model = CountingTransport(model_transport, ledger, "R-model-dry")
    client = DeepSeekClient(
        base_url="https://api.deepseek.com/v1",
        model="t09-dry-run-placeholder",
        api_key="dry-run-fake-key-never-used",
        transport=counting_model,
    )

    import asyncio

    async def _call_model() -> dict:
        output = await client.complete(
            CompletionInput(
                purpose="answer",
                question=PLAN[0]["question"],
                evidence=tuple(
                    ModelEvidence(source_id=item["source_id"], text=item["text"], fields=item["fields"])
                    for item in EVIDENCE_Q01
                ),
            ),
            timeout_seconds=5.0,
        )
        await client.aclose()
        return {"text": output.text[:60], "source_ids": list(output.source_ids), "usage": dict(output.usage or {})}

    model_facts = asyncio.run(_call_model())
    results.append({"case_id": PLAN[0]["case_id"], "kind": "model", "ok": True, "facts": model_facts})

    for case in (item for item in PLAN if item["kind"] == "ocr"):
        mock = _mock_ocr_text_response if case["mode"] == "text" else _mock_ocr_table_response
        counting = CountingSyncTransport(httpx.MockTransport(mock), ledger, case["case_id"], case["mode"])
        ocr_client = TencentOCRClient(
            secret_id="dry-run-fake-secret-id",
            secret_key="dry-run-fake-secret-key",
            region="ap-guangzhou",
            endpoint="https://ocr.tencentcloudapi.com",
            timeout_seconds=5.0,
            transport=counting,
        )
        content = (NORMAL / case["file"]).read_bytes()
        page_result: OCRPageResult = ocr_client.recognize(
            OCRInput(content=content, mime_type="image/png", page=1), mode=case["mode"]
        )
        ocr_client.close()
        results.append(
            {
                "case_id": case["case_id"],
                "kind": "ocr",
                "ok": True,
                "facts": {
                    "provider_request_id": page_result.provider_request_id,
                    "text_chars": len(page_result.text),
                    "table_rows": len(page_result.table_rows),
                    "confidence": page_result.confidence,
                },
            }
        )

    # 硬上限自检：把上限临时压到"已用数"，再要一个额度必须被拒（且不发请求），随后恢复
    original_max = ledger.max_requests
    budget_probe = {"max_requests": ledger.used, "used": ledger.used, "rejected": False, "error": None}
    ledger.max_requests = ledger.used
    try:
        ledger.reserve(case_id="R-budget-probe", action="probe")
    except LiveBudgetExceeded as exc:
        budget_probe["rejected"] = True
        budget_probe["error"] = str(exc)
    finally:
        ledger.max_requests = original_max

    return {
        "dry_run": True,
        "network": "httpx.MockTransport（无真实 socket，仅走真实适配器与计数闸门）",
        "plan": PLAN,
        "plan_entries": len(PLAN),
        "results": results,
        "budget_probe": budget_probe,
        "ledger": ledger.summary(),
        "config": _config_facts(allow_read=False),
    }


def run_live(ledger: Ledger, *, max_requests: int) -> dict:
    """真实调用（本轮禁止执行）。每一请求都过闸门；超限立即中止。"""
    settings, model_client, ocr_client = _build_real_clients(ledger)
    import asyncio

    results: list[dict] = []

    async def _model_case(case: dict) -> dict:
        output = await model_client.complete(
            CompletionInput(
                purpose="answer",
                question=case["question"],
                evidence=tuple(
                    ModelEvidence(source_id=item["source_id"], text=item["text"], fields=item["fields"])
                    for item in EVIDENCE_Q01
                ),
            ),
            timeout_seconds=min(30.0, settings.model_request_timeout_seconds),
        )
        return {
            "case_id": case["case_id"],
            "kind": "model",
            "ok": True,
            "facts": {
                "provider_request_id": output.provider_request_id,
                "usage": dict(output.usage or {}),
                "text_preview": output.text[:120],
                "source_ids": list(output.source_ids),
            },
        }

    try:
        for case in (item for item in PLAN if item["kind"] == "model"):
            try:
                results.append(asyncio.run(_model_case(case)))
            except Exception as exc:  # 真实层错误也要落台账
                results.append({"case_id": case["case_id"], "kind": "model", "ok": False, "error": type(exc).__name__})
                ledger.write({"case_id": case["case_id"], "action": "model.error", "error": type(exc).__name__})
        if ocr_client is not None:
            for case in (item for item in PLAN if item["kind"] == "ocr"):
                counting = CountingSyncTransport(httpx.HTTPTransport(), ledger, case["case_id"], case["mode"])
                ocr_client._transport = counting  # 使用计数传输包装真实传输
                ocr_client._client = None
                content = (NORMAL / case["file"]).read_bytes()
                try:
                    page_result = ocr_client.recognize(
                        OCRInput(content=content, mime_type="image/png", page=1), mode=case["mode"]
                    )
                    results.append(
                        {
                            "case_id": case["case_id"],
                            "kind": "ocr",
                            "ok": True,
                            "facts": {
                                "provider_request_id": page_result.provider_request_id,
                                "text_chars": len(page_result.text),
                                "table_rows": len(page_result.table_rows),
                            },
                        }
                    )
                except Exception as exc:
                    results.append({"case_id": case["case_id"], "kind": "ocr", "ok": False, "error": type(exc).__name__})
                    ledger.write({"case_id": case["case_id"], "action": "ocr.error", "error": type(exc).__name__})
    finally:
        try:
            if ocr_client is not None:
                ocr_client.close()
        finally:
            try:
                asyncio.run(model_client.aclose())
            except Exception:  # pragma: no cover - 关闭失败不影响台账
                pass

    return {
        "dry_run": False,
        "plan_entries": len(PLAN),
        "results": results,
        "ledger": ledger.summary(),
        "config": _config_facts(allow_read=True),
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="T09-D1 真实调用闸门（默认 --dry-run）")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="仅走 MockTransport，验证闸门与台账（默认）")
    mode.add_argument("--live", action="store_true", help="真实调用（需 T09_LIVE_ACK=REAL-OK，本轮禁止）")
    parser.add_argument("--max-requests", type=int, default=DEFAULT_MAX_REQUESTS)
    parser.add_argument("--label", default=None, help="台账文件名（默认按模式与时间生成）")
    parser.add_argument("--ledger", default=None, help="显式台账路径")
    args = parser.parse_args(argv)

    if args.max_requests <= 0:
        print("--max-requests 必须为正整数", file=sys.stderr)
        return 2

    live = bool(args.live)
    if live:
        ack = os.environ.get(LIVE_ACK_ENV)
        if ack != LIVE_ACK_VALUE:
            print(
                f"拒绝执行 --live：需要环境变量 {LIVE_ACK_ENV}={LIVE_ACK_VALUE} 的显式二次确认；"
                "本轮任务单禁止真实调用。",
                file=sys.stderr,
            )
            return 3

    label = args.label or ("live" if live else "dry-run")
    ledger_path = Path(args.ledger) if args.ledger else DEFAULT_LEDGER_DIR / f"t09-d1-{label}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.jsonl"
    ledger = Ledger(ledger_path, mode="live" if live else "dry-run", max_requests=args.max_requests)
    started = time.monotonic()
    try:
        payload = run_live(ledger, max_requests=args.max_requests) if live else run_dry_run(ledger, max_requests=args.max_requests)
    except LiveBudgetExceeded as exc:
        ledger.close()
        print(json.dumps({"status": "aborted_budget", "error": str(exc), "ledger": str(ledger_path)}, ensure_ascii=False))
        return 4
    finally:
        if not ledger._handle.closed:  # noqa: SLF001 - 便于异常路径收尾
            ledger.close()

    payload["elapsed_ms"] = round((time.monotonic() - started) * 1000, 1)
    payload["ledger_path"] = str(ledger_path)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

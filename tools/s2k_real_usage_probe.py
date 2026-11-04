"""一次性真实 usage 形态诊断（经理本地治理脚本，非产品入口）。

为什么需要它：第 2 次真实 pilot 仍在 Q01 的 chat 结算处被 J1 判为
``SETTLEMENT_NOT_RELEASABLE:unknown_usage_field``，而产品错误路径按安全设计只给稳定码、
不回显字段名。为不盲目再烧一次 2.103552 元的整轮，这里用产品自己的
LiveGate/BudgetLedger/DeepSeekClient/settlement_policy 发 **1 次极小 chat 请求**，
预留 0.01 元（实际用量远低于该值），并在本进程内存里只打印 usage 的**字段名**（不打印值、
不打印请求/响应正文、不打印密钥），用于确定应当如何最小修复。

仍然走共享账本 + GO + 预算闸门（零重试、串行、失败即停），不是裸调用。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve()
for parent in (ROOT, *ROOT.parents):
    if (parent / "backend" / "src" / "mktkb").is_dir():
        REPO = parent
        break
else:  # pragma: no cover
    raise SystemExit("REFUSE: 找不到 backend/src")

sys.path.insert(0, str(REPO / "backend" / "src"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from mktkb.live_authorization import resolve_live_gate  # noqa: E402
from mktkb.providers.deepseek import DeepSeekClient  # noqa: E402
from mktkb.providers.types import CompletionInput  # noqa: E402
from mktkb.rag.controlled_usage import build_chat_evidence  # noqa: E402
from mktkb.rag.settlement_policy import build_policy  # noqa: E402

STAGE = "S2-DEV"
MODEL = os.environ.get("MKTKB_MODEL_NAME", "")
BASE = os.environ.get("MKTKB_MODEL_BASE_URL", "")
KEY = os.environ.get("MKTKB_MODEL_API_KEY", "")
RESERVE_CNY = 0.01


def payload_sha(payload: dict) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


async def main() -> int:
    gate = resolve_live_gate(
        stage=STAGE,
        service="chat",
        requested_stage_limit_cny=float(os.environ.get("MKTKB_RAG_STAGE_LIMIT_CNY", "0") or 0),
        requested_max_requests=int(os.environ.get("MKTKB_RAG_MAX_REQUESTS", "0") or 0),
        request_bound_cny=RESERVE_CNY,
    )
    ledger = gate.ledger()
    policy = build_policy("chat", model=MODEL)
    client = DeepSeekClient(base_url=BASE, model=MODEL, api_key=KEY,
                           timeout_seconds=30.0, max_output_tokens=64)
    request = CompletionInput(purpose="query_expansion", question="北京出差住宿标准是多少")
    sha = payload_sha(client._payload(request))  # noqa: SLF001 - 诊断：与产品同一 payload
    reservation = ledger.reserve(
        kind="chat", provider="deepseek", model=MODEL, max_cny=RESERVE_CNY,
        request_sha256=sha, settlement_policy=policy,
        metadata={"purpose": "manager-real-usage-shape-probe", "note": "diagnostic only"},
    )
    print(json.dumps({"reserved": reservation.reservation_id, "reserve_cny": RESERVE_CNY}, ensure_ascii=False))
    try:
        output = await client.complete(request, timeout_seconds=30.0)
    except BaseException as exc:  # noqa: BLE001 - 诊断：失败也留账
        ledger.settle(reservation, status="failed", error_code="PROBE_SEND_FAILED")
        print(json.dumps({"probe": "send_failed", "type": type(exc).__name__, "code": getattr(exc, "code", None)},
                         ensure_ascii=False))
        return 5
    raw = output.raw_usage if isinstance(output.raw_usage, dict) else None
    usage_source = raw if raw is not None else (output.usage or {})
    keys = sorted(str(k) for k in usage_source.keys())
    shapes = {k: type(v).__name__ for k, v in usage_source.items()}
    print(json.dumps({"probe": "usage_shape", "keys": keys, "types": shapes}, ensure_ascii=False))
    evidence = build_chat_evidence(
        policy, request_sha256=sha, usage=usage_source, http_status=200,
        streamed=False, finish_reason="stop", content_complete=True, content_parse_ok=True,
    )
    try:
        result = ledger.settle_usage(reservation, evidence=evidence, request_id=output.provider_request_id)
    except BaseException as exc:  # noqa: BLE001 - 拒绝也是诊断结论
        print(json.dumps({"probe": "settlement_rejected", "type": type(exc).__name__,
                          "code": getattr(exc, "code", None)}, ensure_ascii=False))
        return 0
    print(json.dumps({"probe": "settlement", "result": str(result)[:400]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

"""P2-T207-R4PREP 独立验收 v3a：真实 provider 的单请求预留 vs 计划 reserve_peak（零出网）。

为什么查这个：
  product_adapter.py:1074 把 RagConfig.max_request_cny 设成 **plan.reserve_peak_cny**；
  BailianEmbeddingProvider._embed_batch（rag/providers.py:316-321）在每次 POST 前先算
  reserve_cny = 81920 tokens x 单价，若 > max_request_cny 就直接拒（不发送）。
  R4 计划没有 OCR 项 ⇒ reserve_peak = 0.018688（chat 项）⇒ 需要验证这是否会把 embedding POST 全挡死。

做法：真实 BailianEmbeddingProvider + httpx.MockTransport（不出网、零凭据），
      分别用 R4 的 peak(0.018688) 与 R1-R3 的 peak(0.5) 各跑一次同样形状的文本批次。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx

HERE = Path(__file__).resolve()
ROOT = next(p for p in HERE.parents if (p / "backend" / "src").is_dir())
sys.path.insert(0, str(ROOT / "backend" / "src"))

from mktkb.evaluation.p2_contracts import P2RunPlan  # noqa: E402
from mktkb.rag.config import RagConfig  # noqa: E402
from mktkb.rag.providers import (  # noqa: E402
    MAX_EMBEDDING_REQUEST_TOKENS,
    BailianEmbeddingProvider,
    post_counters,
    reset_post_counters,
)

DIM = 1024
MOCK_KEY = "verifier-offline-not-a-real-key"


def handler(request: httpx.Request) -> httpx.Response:
    payload = json.loads(request.content.decode("utf-8"))
    inputs = payload["input"]
    rows = [{"index": index, "embedding": [0.001] * DIM} for index in range(len(inputs))]
    return httpx.Response(200, json={
        "data": rows,
        "usage": {"total_tokens": len(inputs) * 3},
        "id": "mock-request-id",
    })


def build(max_request_cny: float) -> BailianEmbeddingProvider:
    config = RagConfig(
        provider_mode="live",
        embedding_api_key=MOCK_KEY,
        embedding_base_url="https://dashscope.aliyuncs.com",
        embedding_batch_size=5,
        embedding_timeout_seconds=5.0,
        max_request_cny=max_request_cny,
        max_retries=0,
        require_zero_retries=True,
    )
    return BailianEmbeddingProvider(
        config,
        budget=None,
        require_budget=False,
        transport=httpx.MockTransport(handler),
    )


def run_case(label: str, max_request_cny: float) -> dict:
    # 产品灌库实测的每次 embed() 文本数（下一段 v3b 会重新测一遍）
    text_counts = [9, 1, 1, 4, 1]
    provider = build(max_request_cny)
    reset_post_counters()
    outcome = {"label": label, "max_request_cny": max_request_cny, "calls": []}
    try:
        for count in text_counts:
            provider.embed([f"text-{index}" for index in range(count)], purpose="document")
            outcome["calls"].append({"texts": count, "ok": True})
    except Exception as exc:  # noqa: BLE001 - 这是被测行为
        outcome["error_type"] = type(exc).__name__
        outcome["error_code"] = getattr(exc, "code", None)
        outcome["error_text"] = str(exc)
    finally:
        provider.close()
    attempts = post_counters()["attempts"]
    outcome["post_attempts"] = int(attempts.get("embedding", 0))
    outcome["expected_posts_if_allowed"] = sum(-(-count // 5) for count in text_counts)
    return outcome


def plan_peak(name: str) -> float:
    t207 = ROOT / "docs" / "reports" / "OBS-EVAL" / "P2" / "T207" / "PM"
    doc = json.loads((t207 / name).read_text(encoding="utf-8"))
    return float(P2RunPlan.from_dict(doc).reserve_peak_cny)


def main() -> None:
    r4_peak = plan_peak("T207-plan-R4-v0_1.json")
    r123_peak = plan_peak("T207-plan-v0_1.json")
    report = {
        "embedding_reserve_per_post_cny": round(
            MAX_EMBEDDING_REQUEST_TOKENS * 0.5 / 1_000_000.0, 8
        ),
        "max_embedding_request_tokens": MAX_EMBEDDING_REQUEST_TOKENS,
        "wiring": "product_adapter.py:1074 max_request_cny = plan.reserve_peak_cny "
                  "-> passed to RagConfig at product_adapter.py:1091 (_start_live only)",
        "r4_plan_reserve_peak_cny": r4_peak,
        "r123_plan_reserve_peak_cny": r123_peak,
        "with_r4_peak": run_case("r4_plan_peak", r4_peak),
        "with_r123_peak": run_case("r123_plan_peak", r123_peak),
    }
    r4 = report["with_r4_peak"]
    ok = report["with_r123_peak"]
    # 反事实：把 embedding 项的 total_tokens_cap 提到 provider 的单请求预留口径（81920）
    t207 = ROOT / "docs" / "reports" / "OBS-EVAL" / "P2" / "T207" / "PM"
    doc = json.loads((t207 / "T207-plan-R4-v0_1.json").read_text(encoding="utf-8"))
    for item in doc["items"]:
        if item["price_profile"]["kind"] == "embedding":
            item["price_profile"]["total_tokens_cap"] = MAX_EMBEDDING_REQUEST_TOKENS
    try:
        fixed_plan = P2RunPlan.from_dict(doc)
    except Exception as exc:  # noqa: BLE001 - 被测契约行为
        report["plan_side_fix_possible"] = {
            "possible": False,
            "error_type": type(exc).__name__,
            "error_code": getattr(exc, "code", None),
            "error_text": str(exc)[:120],
            "why": "p2_contracts 把 embedding 的 total_tokens_cap 冻结为 4096（cap_not_frozen）",
        }
    else:
        report["plan_side_fix_possible"] = {"possible": True, "reserve_peak_cny": fixed_plan.reserve_peak_cny}
    report["conclusion"] = {
        "r4_peak_below_provider_reserve": r4_peak < report["embedding_reserve_per_post_cny"],
        "r123_peak_above_provider_reserve": r123_peak >= report["embedding_reserve_per_post_cny"],
        "r4_peak_blocks_embedding_posts": r4.get("post_attempts", 0) == 0 and "error_type" in r4,
        "r123_peak_allows_6_posts": ok.get("post_attempts") == 6,
        "batch_size_5_post_rule_holds": ok.get("expected_posts_if_allowed") == ok.get("post_attempts") == 6,
    }
    print(json.dumps(report, ensure_ascii=False, indent=1))




def _run(main_fn) -> None:
    import contextlib
    import io
    import sys
    from pathlib import Path

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        main_fn()
    text = buffer.getvalue()
    out = sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else None
    if out:
        Path(out).write_text(text, encoding="utf-8")
    sys.stdout.write(text)


if __name__ == "__main__":
    _run(main)


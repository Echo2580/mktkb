"""T207-FIX-B 证据②：chat 结算证据的 `output_valid` / 三判据 修复前后对比（零真实调用）。

用法（仓库根目录）：
    .venv/Scripts/python.exe docs/reports/OBS-EVAL/P2/T207-FIX-B/evidence/output-valid-compare.py

本脚本只 import 纯函数（settlement_policy / p2_live），不建连接、不读 .env、不发 HTTP：

- "修复前" = `build_chat_evidence(...)` 被**硬编码**成 finish_reason="stop"、content_complete=True、
  content_parse_ok=True，且从不传 output_valid（= UsageEvidence 默认 False）——这就是原
  `p2_live.chat_usage_evidence` 的逐字行为；
- "修复后" = 现行 `p2_live.chat_usage_evidence`，判据来自**这一份输出**的三条件。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[6]
sys.path.insert(0, str(ROOT / "backend" / "src"))

from mktkb.evaluation.p2_live import chat_usage_evidence  # noqa: E402
from mktkb.rag.controlled_usage import build_chat_evidence  # noqa: E402
from mktkb.rag.settlement_policy import KIND_CHAT, build_policy, evaluate_settlement  # noqa: E402

REQUEST_SHA = "a" * 64
BOUND_CNY = 0.018688  # chat 单次上界（6144*2 + 800*8)/1e6
USAGE = {
    "prompt_tokens": 64,
    "completion_tokens": 32,
    "total_tokens": 96,
    "prompt_cache_hit_tokens": 0,
    "prompt_cache_miss_tokens": 64,
}
RESERVED = {
    "kind": KIND_CHAT,
    "provider": "deepseek",
    "model": "deepseek-flash",
    "request_sha256": REQUEST_SHA,
}
POLICY = build_policy(KIND_CHAT, model="deepseek-flash")


def before_evidence(usage: dict) -> object:
    """修复前的逐字行为：内容标志恒 True、output_valid 恒默认 False。"""
    return build_chat_evidence(
        POLICY,
        request_sha256=REQUEST_SHA,
        usage=dict(usage),
        http_status=200,
        streamed=False,
        finish_reason="stop",
        content_complete=True,
        content_parse_ok=True,
    )


def before(usage: dict, **_ignored) -> object:
    return before_evidence(usage)


def after(usage: dict, **signals) -> object:
    return chat_usage_evidence(request_sha256=REQUEST_SHA, usage=dict(usage), **signals)


def decide(evidence) -> tuple[bool, str, float]:
    if evidence is None:
        return (False, "usage_evidence_missing", BOUND_CNY)
    decision = evaluate_settlement(
        POLICY, reserved=RESERVED, evidence=evidence, reserve_cny=BOUND_CNY
    )
    return (bool(decision.accepted), decision.reason or "-", float(decision.charge_cny))


CASES = (
    ("合法输出 + 完整 usage", USAGE, dict(finish_reason="stop", content_present=True, content_parsed=True)),
    ("空内容", USAGE, dict(finish_reason="stop", content_present=False, content_parsed=False)),
    ("非 stop 完成态", USAGE, dict(finish_reason="length", content_present=True, content_parsed=True)),
    ("JSON 未解析（无解析结构）", USAGE, dict(finish_reason="stop", content_present=True, content_parsed=False)),
    ("usage 缺字段（无 cache 拆分）", {k: v for k, v in USAGE.items() if k != "prompt_cache_hit_tokens"}, dict(finish_reason="stop", content_present=True, content_parsed=True)),
    ("调用方未给判据（缺省）", USAGE, {}),
)


def main() -> int:
    print("chat 上界 =", BOUND_CNY, "元；合法 usage 按 64*2/M + 32*8/M = 0.000384 元")
    print()
    header = "=== 每个场景两行：第 1 行=修复前，第 2 行=修复后 ==="
    print(header)
    print("-" * 100)
    for label, usage, signals in CASES:
        prior_ev = before(usage)
        now_ev = after(usage, **signals)
        prior = decide(prior_ev)
        now = decide(now_ev)
        prior_text = "accept=%s reason=%s charge=%.8f output_valid=%s" % (
            prior[0], prior[1], prior[2], getattr(prior_ev, "output_valid", None)
        )
        now_text = "accept=%s reason=%s charge=%.8f output_valid=%s" % (
            now[0], now[1], now[2], getattr(now_ev, "output_valid", None)
        )
        print("%-28s%s\n%-28s%s" % (label, prior_text, "", now_text))
    print()
    print("pilot 口径复核（账本实测，非本脚本计算）：")
    print("  conservative_held_cny = 0.061806 (answer) + 0.5095523 (从属) = 0.5713583")
    print("  provider_billed_cny  = 0.005742 (3 笔 usage chat) + 0.5095523 = 0.5152943")
    print("  零付费轮 3 × 0.018688 = 0.056064 = 两者之差（保守留账，不是供应商花费）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

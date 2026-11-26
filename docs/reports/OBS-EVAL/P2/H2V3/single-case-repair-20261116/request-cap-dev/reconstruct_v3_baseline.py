"""Reconstruct the pre-edit untracked entry and require its recorded SHA-256."""
from pathlib import Path
import hashlib

root = Path(__file__).resolve().parents[7]
out = Path(__file__).resolve().parent
text = (root / "tools/p2_h2_v3_controlled_execute.py").read_text(encoding="utf-8")
changes = [
    ('''MAX_REQUESTS = "unlimited"
"""v3 新计划显式取消累计次数上限；金额和逐计划项次数仍受约束。"""''', '''MAX_REQUESTS = 1500
"""v3 四 run 的累计请求上限。

2026-11-15 终局执行：主人把授权总量提到 1500（原 1160 时已用 1099、余 61 < 全量复跑约 126，
四 run 无法开跑），因此把计划/GO 的固定上限从 1160 提到 1500；`GOVERNANCE_REQUEST_CAP`
本来就是 1500，钱闸（项目 40 / 阶段 20 / 单请求 0.5）与 30 题/标签/阈值均未动。
"""'''),
    ('GOVERNANCE_REQUEST_CAP = MAX_REQUESTS', 'GOVERNANCE_REQUEST_CAP = 1500'),
    ('"max_requests": MAX_REQUESTS,', '"max_requests": int(MAX_REQUESTS),'),
    ('if config.get("max_requests") != MAX_REQUESTS:', 'if int(config.get("max_requests", -1)) != MAX_REQUESTS:'),
    ('max_requests: str = MAX_REQUESTS', 'max_requests: int = MAX_REQUESTS'),
    ('    max_requests: str,\n    scenario_binding:', '    max_requests: int,\n    scenario_binding:'),
    ('max_requests=max_requests,\n            scenario_binding=scenario_binding,', 'max_requests=int(max_requests),\n            scenario_binding=scenario_binding,'),
    ('if plan.max_requests != options.max_requests:', 'if int(plan.max_requests) != int(options.max_requests):'),
    ('max_requests=options.max_requests,', 'max_requests=int(options.max_requests),'),
    ('"max_requests": options.max_requests,', '"max_requests": int(options.max_requests),'),
    ('and plan.max_requests == MAX_REQUESTS', 'and int(plan.max_requests) == MAX_REQUESTS'),
    ('"max_requests": go_scope.get("max_requests"),', '"max_requests": int(go_scope.get("max_requests") or 0),'),
    ('remaining = GOVERNANCE_REQUEST_CAP', 'remaining = max(0, GOVERNANCE_REQUEST_CAP - int(snapshot.reservation_count))'),
    ('"exceeds_gate": None if total_requests is None else False,', '"exceeds_gate": None if total_requests is None else total_requests > remaining,'),
    ('"requests_remaining": preflight.requests_remaining,', '"requests_remaining": int(preflight.requests_remaining),'),
    ('"max_requests": authorization.max_requests,', '"max_requests": int(authorization.max_requests),'),
    ('"requests_remaining": authorization.requests_remaining,', '"requests_remaining": int(authorization.requests_remaining),'),
    ('plan.add_argument("--max-requests", choices=[MAX_REQUESTS], default=MAX_REQUESTS)', 'plan.add_argument("--max-requests", type=int, default=MAX_REQUESTS)'),
    ('max_requests=args.max_requests,', 'max_requests=int(args.max_requests),'),
]
for new, old in changes:
    if new not in text:
        raise RuntimeError(f"missing replacement: {new!r}")
    text = text.replace(new, old)
expected = '03979b2e4e77cd614dac64e2b5897bb40dcd9ea110c3e8fad26a6e3b16c55590'
for data in (text.encode('utf-8'), text.replace('\n', '\r\n').encode('utf-8')):
    if hashlib.sha256(data).hexdigest() == expected:
        (out / 'baseline-v3.py.txt').write_bytes(data)
        print('reconstructed baseline SHA-256:', expected)
        break
else:
    raise RuntimeError('reconstruction did not match recorded baseline SHA-256')

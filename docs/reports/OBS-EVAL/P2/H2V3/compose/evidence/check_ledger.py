import hashlib
import json
import pathlib

lp = pathlib.Path(r"D:\GPT项目\市场部AI知识库\docs\evidence\LOCAL-R1-20261101\budget\live-ledger.jsonl")
raw = lp.read_bytes()
text = raw.decode("utf-8")
rows = [json.loads(line) for line in text.splitlines() if line.strip()]
print("ledger", hashlib.sha256(raw).hexdigest(), "bytes", len(raw), "lines", len(rows))
kinds = {}
for row in rows:
    kinds[str(row.get("kind"))] = kinds.get(str(row.get("kind")), 0) + 1
print("kinds", kinds)
res = [row for row in rows if str(row.get("kind")) == "reservation"]
out = [row for row in rows if str(row.get("kind")) == "result"]
print("reservations", len(res), "results", len(out))
bp = pathlib.Path(r"D:\GPT项目\市场部AI知识库\docs\evidence\LOCAL-R1-20261101\budget\budget.json")
print("budget", hashlib.sha256(bp.read_bytes()).hexdigest())
print("budget_payload", json.loads(bp.read_text(encoding="utf-8")))

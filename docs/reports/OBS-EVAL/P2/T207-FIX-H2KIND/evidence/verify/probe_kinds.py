
import json, collections
from mktkb.evaluation.dataset import load_cases
ROOT = "D:/GPT项目/市场部AI知识库/fixtures/evaluation/"
out = {}
for name in ("b0.jsonl","badcase.jsonl","regression.jsonl"):
    cases = load_cases(ROOT+name)
    out[name] = dict(collections.Counter(str(c.expected_kind) for c in cases))
rows = [json.loads(l) for l in open(ROOT+"holdout-questions.jsonl", encoding="utf-8") if l.strip()]
out["holdout-questions.jsonl"] = dict(collections.Counter(str(r["expected_kind"]) for r in rows))
rows2 = [json.loads(l) for l in open(ROOT+"refusal-controls-2026-11-10.jsonl", encoding="utf-8") if l.strip()]
out["refusal-controls.jsonl"] = {"expected_kind": dict(collections.Counter(str(r.get("expected_kind")) for r in rows2)), "n": len(rows2)}
print(json.dumps(out, ensure_ascii=False, indent=1))

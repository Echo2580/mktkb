"""C27 问句候选词类探针：只出布尔 / 整数 / 索引 / 词表 sha256。

候选词表留在 work/（本文件），**词面不回显**到证据：证据只记下标与词表摘要。
离线；只读私有输入。绝不打印问句与值。
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import pathlib
import sys

RUN_ROOT = pathlib.Path(r"D:\mktkb-p2-h2v3-r0fix6-20261116\r0")
BINDING = pathlib.Path(
    r"D:\mktkb-p2-h2v3-20261115\custody-plan-20261116-final5\bindings\run0-base_b0.binding.json"
)
KEY_PATH = pathlib.Path(r"D:\mktkb-p2-h2v3-20261115\runs3\ev.key")
CASE = "H2V3-C27"
OUT = pathlib.Path(__file__).resolve().parent.parent / "evidence" / "12-c27" / "c27-question-words.json"

CANDIDATES = (
    "联系人",
    "负责人",
    "联系",
    "电话",
    "地址",
    "谁",
    "找谁",
    "对接",
    "值班",
    "接待",
    "店长",
    "经理",
    "主管",
    "老板",
    "前台",
    "店员",
    "负责",
    "门店",
    "哪家",
    "什么",
)
VOCAB_SHA = hashlib.sha256("\u0001".join(CANDIDATES).encode("utf-8")).hexdigest()


def _repo_root() -> pathlib.Path:
    for parent in pathlib.Path(__file__).resolve().parents:
        if (parent / "backend" / "src" / "mktkb").is_dir():
            return parent
    raise SystemExit("repo_root_not_found")


REPO = _repo_root()
sys.path.insert(0, str(REPO / "backend" / "src"))
TOOLS = REPO / "tools"
sys.path.insert(0, str(TOOLS))


def _main() -> dict:
    binding = json.loads(BINDING.read_text(encoding="utf-8"))
    run_entry = json.loads((RUN_ROOT / "v3-entry-p2-h2v3-20261115-r0-base_b0.json").read_text(encoding="utf-8"))
    case_plan = json.loads((RUN_ROOT / "out" / "controlled" / "case-plan.json").read_text(encoding="utf-8"))
    key = KEY_PATH.read_bytes()
    spec = importlib.util.spec_from_file_location("p2h2v3_entry", TOOLS / "p2_h2_v3_controlled_execute.py")
    entry = importlib.util.module_from_spec(spec)
    sys.modules["p2h2v3_entry"] = entry
    spec.loader.exec_module(entry)
    inputs = {name: {"path": record["path"]} for name, record in binding["inputs"].items()}
    bundle = entry.load_v3_bundle(inputs)
    cases = tuple(bundle.contract.subset(str(run_entry.get("scenario_id"))).cases)
    case = next(item for item in cases if str(item.case_id) == CASE)
    question = str(case.question)
    ref = str(getattr(case, "reference_answer", "") or "")

    from mktkb.rag.query import FIELD_WORDS, _norm  # noqa: PLC0415

    q_hits = [i for i, word in enumerate(CANDIDATES) if word in question]
    r_hits = [i for i, word in enumerate(CANDIDATES) if word in ref]
    contact_words = tuple(FIELD_WORDS.get("contact") or ())
    contact_hit = any(_norm(word) in _norm(question) for word in contact_words)
    return {
        "ok": True,
        "case_id": CASE,
        "question_len": len(question),
        "reference_len": len(ref),
        "vocabulary_size": len(CANDIDATES),
        "vocabulary_sha256": VOCAB_SHA,
        "question_hit_count": len(q_hits),
        "question_hits": q_hits,
        "reference_hit_count": len(r_hits),
        "reference_hits": r_hits,
        "derived": {
            "contact_lexicon_word_hit": bool(contact_hit),
            "non_lexicon_contact_ask": bool(q_hits) and not contact_hit,
        },
    }


def main() -> int:
    try:
        result = _main()
    except Exception:  # noqa: BLE001
        result = {"ok": False, "error": "probe_failed", "case_id": CASE}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "ok": result.get("ok"),
                "question_hit_count": result.get("question_hit_count"),
                "derived": result.get("derived"),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())

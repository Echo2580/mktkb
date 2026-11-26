"""R0 第六轮 C12 计数探针：只出整数 / 布尔 / 角色码 / 固定码。

离线；只读私有输入。绝不打印题干、答案、实体、值或私有路径。
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import sys

RUN_ROOT = pathlib.Path(r"D:\mktkb-p2-h2v3-r0fix6-20261116\r0")
BINDING = pathlib.Path(
    r"D:\mktkb-p2-h2v3-20261115\custody-plan-20261116-final5\bindings\run0-base_b0.binding.json"
)
KEY_PATH = pathlib.Path(r"D:\mktkb-p2-h2v3-20261115\runs3\ev.key")
ID = "p2-h2v3-20261115-r0-base_b0"
CASE = "H2V3-C12"
OUT = pathlib.Path(__file__).resolve().parent.parent / "evidence" / "11-round6-chain" / "c12-source-counts.json"


def _repo_root() -> pathlib.Path:
    for parent in pathlib.Path(__file__).resolve().parents:
        if (parent / "backend" / "src" / "mktkb").is_dir():
            return parent
    raise SystemExit("repo_root_not_found")


REPO = _repo_root()
sys.path.insert(0, str(REPO / "backend" / "src"))
TOOLS = REPO / "tools"
sys.path.insert(0, str(TOOLS))


def _fail(code: str) -> dict:
    return {"ok": False, "error": code, "case_id": CASE}


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

    from mktkb.evaluation.p2_evidence_io import read_encrypted_evidence
    import mktkb.evaluation.p2_runner as runner
    import mktkb.evaluation.p2_scoring as scoring

    document_codes = runner.holdout_document_codes(bundle.contract._ingest)  # noqa: SLF001
    expected_codes = {
        str(scoring._lookup_document_code(name, document_codes))  # noqa: SLF001
        for name in (case.expected_sources or ())
        if scoring._lookup_document_code(name, document_codes)  # noqa: SLF001
    }
    plan_row = next(item for item in case_plan["cases"] if str(item.get("case_id")) == CASE)
    env = read_encrypted_evidence(
        RUN_ROOT / "evidence" / ID / str(plan_row["turns"][-1]["evidence_file"]),
        key=key,
        expected_bindings=dict(case_plan["bindings"]),
    )
    proj = env.get("db_projection") or {}
    units = proj.get("units") or []
    events = (env.get("capture") or {}).get("events") or []
    dra = next((ev["payload"] for ev in events if ev.get("kind") == "direct_rag_answer"), {})
    ans = next((ev["payload"] for ev in events if ev.get("kind") == "answer_result"), {})
    commit = next((ev["payload"] for ev in events if ev.get("kind") == "commit_observed"), {})

    cited_ids = [str(uid) for uid in (dra.get("cited_unit_ids") or ())]
    answer_ids = [str(x) for x in (ans.get("source_ids") or ())]
    commit_ids = [str(x) for x in (commit.get("source_ids") or ())]
    cited_docs = set()
    for unit in units:
        if str(unit.get("unit_id")) in set(cited_ids) | set(answer_ids) | set(commit_ids):
            code = scoring._lookup_document_code(unit.get("document_name"), document_codes)  # noqa: SLF001
            if code:
                cited_docs.add(str(code))
    return {
        "ok": True,
        "case_id": CASE,
        "expected_sources": len(case.expected_sources or ()),
        "expected_doc_codes": len(expected_codes),
        "cited_units": len(cited_ids),
        "answer_source_ids": len(answer_ids),
        "commit_source_ids": len(commit_ids),
        "projection_units": len(units),
        "projection_message_sources": len(proj.get("message_sources") or ()),
        "cited_doc_codes": len(cited_docs),
        "expected_code_hits": len(expected_codes & cited_docs),
        "expected_code_missing": len(expected_codes - cited_docs),
        "uncited_projection_units": len({str(u.get("unit_id")) for u in units} - set(cited_ids)),
        "answer_kind": str(ans.get("kind") or ""),
        "answer_reason": str(ans.get("reason") or ""),
        "missing_fixed_code": "candidate_dropped_reason",
    }


def main() -> int:
    try:
        result = _main()
    except Exception:
        result = _fail("probe_failed")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())

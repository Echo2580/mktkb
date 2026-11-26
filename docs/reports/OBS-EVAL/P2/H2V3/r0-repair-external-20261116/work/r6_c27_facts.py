"""R0 第六轮 C27 定位探针：逐层计数，只出角色码 / 列序号 / 整数 / 布尔 / 固定码。

离线；只读私有输入（binding / 密文 / case-plan / holdout 合同）。
绝不打印题干、答案、实体、值或私有路径。
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
CASE = "H2V3-C27"
OUT = pathlib.Path(__file__).resolve().parent.parent / "evidence" / "12-c27" / "c27-layer-counts.json"


def _repo_root() -> pathlib.Path:
    for parent in pathlib.Path(__file__).resolve().parents:
        if (parent / "backend" / "src" / "mktkb").is_dir():
            return parent
    raise SystemExit("repo_root_not_found")


REPO = _repo_root()
sys.path.insert(0, str(REPO / "backend" / "src"))
TOOLS = REPO / "tools"
sys.path.insert(0, str(TOOLS))

from mktkb.rag.chunking import field_role  # noqa: E402

ENTITY_ROLES = frozenset(
    {"store", "item", "product", "identifier", "alias", "location", "contact", "entity", "entity_label"}
)


def _fail(code: str) -> dict:
    return {"ok": False, "error": code, "case_id": CASE}


def _load():
    binding = json.loads(BINDING.read_text(encoding="utf-8"))
    run_entry = json.loads((RUN_ROOT / "v3-entry-p2-h2v3-20261115-r0-base_b0.json").read_text(encoding="utf-8"))
    case_plan = json.loads((RUN_ROOT / "out" / "controlled" / "case-plan.json").read_text(encoding="utf-8"))
    key = KEY_PATH.read_bytes()
    spec = importlib.util.spec_from_file_location("p2h2v3_entry", TOOLS / "p2_h2_v3_controlled_execute.py")
    entry = importlib.util.module_from_spec(spec)
    sys.modules["p2h2v3_entry"] = entry
    spec.loader.exec_module(entry)
    return binding, run_entry, case_plan, key, entry


def _main() -> dict:
    binding, run_entry, case_plan, key, entry = _load()
    inputs = {name: {"path": record["path"]} for name, record in binding["inputs"].items()}
    bundle = entry.load_v3_bundle(inputs)
    cases = tuple(bundle.contract.subset(str(run_entry.get("scenario_id"))).cases)
    case = next((item for item in cases if str(item.case_id) == CASE), None)
    if case is None:
        return _fail("case_not_found")

    from mktkb.evaluation.p2_evidence_io import read_encrypted_evidence
    from mktkb.evaluation.scorers import check_value

    plan_row = next((item for item in case_plan["cases"] if str(item.get("case_id")) == CASE), None)
    if plan_row is None:
        return _fail("case_plan_row_missing")
    envelopes = [
        read_encrypted_evidence(
            RUN_ROOT / "evidence" / ID / str(turn["evidence_file"]),
            key=key,
            expected_bindings=dict(case_plan["bindings"]),
        )
        for turn in plan_row["turns"]
    ]
    env = envelopes[-1]
    proj = env["db_projection"]
    units = {str(u.get("unit_id")): u for u in (proj.get("units") or [])}
    events = (env.get("capture") or {}).get("events") or []

    def payload(kind: str) -> dict:
        for ev in events:
            if ev.get("kind") == kind:
                return ev.get("payload") or {}
        return {}

    dra = payload("direct_rag_answer")
    plan_obs = payload("plan_observed")
    ans = payload("answer_result")
    commit = payload("commit_observed")

    text_answer = str(ans.get("text") or "")
    text_commit = str(commit.get("text") or "")
    facts = [f for f in (dra.get("facts") or []) if isinstance(f, dict)]
    fact_roles = [str(f.get("field_role")) for f in facts]
    fact_values = [str(f.get("value") or "") for f in facts]

    cited_ids = [str(uid) for uid in (dra.get("cited_unit_ids") or ())]
    cited = [units[uid] for uid in cited_ids if uid in units]
    if not cited:
        return _fail("cited_row_missing")

    # 逐被引行：列序号（raw_fields 顺序）+ 角色
    rows_detail = []
    for unit in cited:
        raw_fields = unit.get("raw_fields") or {}
        locator = unit.get("locator") or {}
        cells = locator.get("cells") if isinstance(locator.get("cells"), list) else []
        names = [str(name) for name in raw_fields.keys()]
        values = [("" if raw_fields[name] is None else str(raw_fields[name]).strip()) for name in names]
        roles = [field_role(name) for name in names]
        # 序号：优先用 locator.cells 中的位置（0 基），否则退回 raw_fields 顺序
        cell_positions = []
        for name, value in zip(names, values):
            pos = -1
            if value:
                hits = [i for i, cell in enumerate(cells) if str(cell).strip() == value]
                if len(hits) == 1:
                    pos = hits[0]
            cell_positions.append(pos)
        row_cols = [
            {"role": roles[i] or "", "col_index": i, "sheet_cell_index": cell_positions[i]}
            for i in range(len(names))
        ]
        rows_detail.append(
            {
                "raw_columns": len(names),
                "columns": row_cols,
                "role_column_counts": {
                    role: sum(1 for item in row_cols if item["role"] == role)
                    for role in sorted({item["role"] for item in row_cols if item["role"]})
                },
                "text_length": len(str(unit.get("text") or "")),
            }
        )

    # 逐期望值：角色 / 列序号 / 是否进 facts / 是否进 answer 文本
    expected = [str(value) for value in (case.expected_values or ())]
    per_value = []
    for index, value in enumerate(expected):
        col = -1
        role = ""
        matched_rows = 0
        for row in rows_detail:
            for item in row["columns"]:
                # 只在“该列值命中期望值”时记录（用同一 check_value 口径）
                raw_value = None
                unit_index = rows_detail.index(row)
                raw_fields = cited[unit_index].get("raw_fields") or {}
                raw_value = list(raw_fields.values())[item["col_index"]]
                if raw_value is not None and check_value(str(raw_value), value):
                    matched_rows += 1
                    if col < 0:
                        col = item["col_index"]
                        role = item["role"]
        fact_index = -1
        fact_role = ""
        for f_index, (f_role, f_value) in enumerate(zip(fact_roles, fact_values)):
            if check_value(f_value, value):
                fact_index = f_index
                fact_role = f_role
                break
        per_value.append(
            {
                "i": index,
                "role": role,
                "col_index": col,
                "matched_cited_columns": matched_rows,
                "in_facts": fact_index >= 0,
                "fact_index": fact_index,
                "fact_role": fact_role,
                "in_answer_text": bool(text_answer) and check_value(text_answer, value),
                "in_commit_text": bool(text_commit) and check_value(text_commit, value),
            }
        )

    requested = [str(role) for role in (plan_obs.get("field_roles") or ())]
    if not requested:
        requested = [str(plan_obs.get("field_role") or "")]

    # 固定码判定
    missing = [item for item in per_value if not item["in_answer_text"]]
    code = "undetermined"
    detail = {}
    if not missing:
        code = "no_missing_value"
    else:
        item = missing[0]
        detail = {"missing_index": item["i"]}
        if item["in_facts"] and not item["in_answer_text"]:
            code = "commit_filter"
        elif item["matched_cited_columns"] == 0:
            code = "value_absent_in_cited_row"
        elif item["role"] and item["role"] not in requested:
            code = "role_missing"
        elif item["role"]:
            same_role_cols = 0
            for row in rows_detail:
                same_role_cols += sum(1 for c in row["columns"] if c["role"] == item["role"])
            if same_role_cols > 1:
                code = "same_role_multi_column_dropped"
            else:
                # 角色已请求、行内只有 1 列、但 facts 没带上 → 只能落 undetermined
                code = "undetermined"
        else:
            code = "undetermined"

    # 进 facts 的列序（按列序号，角色码）
    facts_detail = []
    for f_index, (f_role, f_value) in enumerate(zip(fact_roles, fact_values)):
        col = -1
        for row_index, row in enumerate(rows_detail):
            raw_fields = cited[row_index].get("raw_fields") or {}
            values = [("" if v is None else str(v).strip()) for v in raw_fields.values()]
            hits = [i for i, raw in enumerate(values) if raw and check_value(raw, f_value)]
            if hits:
                col = hits[0]
                break
        facts_detail.append({"fact_index": f_index, "role": f_role, "col_index": col})

    result = {
        "ok": True,
        "case_id": CASE,
        "plan_field_roles": requested,
        "plan_field_role": str(plan_obs.get("field_role") or ""),
        "answer_kind": str(ans.get("kind") or ""),
        "answer_reason": str(ans.get("reason") or ""),
        "cited_rows": len(cited),
        "rows": rows_detail,
        "facts": facts_detail,
        "fact_count": len(facts),
        "expected_count": len(expected),
        "per_value": per_value,
        "missing_count": len(missing),
        "fixed_code": code,
        "code_detail": detail,
        "requested_role_without_column": [
            role for role in requested if not any(role in row["role_column_counts"] for row in rows_detail)
        ],
        "entity_roles_in_row": sorted(
            {item["role"] for row in rows_detail for item in row["columns"] if item["role"] in ENTITY_ROLES}
        ),
    }
    return result


def main() -> int:
    try:
        result = _main()
    except Exception:
        result = _fail("probe_failed")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k not in ("rows", "per_value", "facts")}, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())

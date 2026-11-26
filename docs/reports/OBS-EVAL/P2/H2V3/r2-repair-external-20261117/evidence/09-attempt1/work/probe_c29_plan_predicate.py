"""R2-205D：C29 的**计划层谓词复算**（离线、只读、零出站；只出布尔/计数/固定码/哈希）。

为什么需要这一步
----------------
``plan_observed`` 只发布 path/mode/filters/terms/field_role(s)/state_* —— **不发布 plan.reason**。
而 ``rag/query.py`` 里能把 reason 置成 ``SECURITY_RESTRICTED_CONTACT`` 的只有一处分支
（``query.py:1812-1822``），它有两个析取项：

    ((bool(item_hits) or identifier is not None) and set(field_roles) & {"phone","address"})
    or is_contract_credential_question(question)

第一个析取项可以直接用信封里发布的 ``field_roles`` 排除或确认；第二个析取项依赖**题干词面**，
信封不发布题干。本探针因此从 scenario 契约里取回该案题干，只在**进程内存**里对产品**纯谓词**
（``is_contract_credential_question`` / ``is_policy_question`` / ``field_roles_for_question``）
求值，输出**布尔 + 计数 + 角色码**，绝不输出题干或命中词文本。

运行（私有路径一律命令行传入）
------------------------------
    .venv\\Scripts\\python.exe -X utf8 probe_c29_plan_predicate.py ^
      --binding <run2-pre_v05_without_v07.binding.json> --case H2V3-C29 --out <输出 json>
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import re
import sys
from typing import Any, Mapping, Sequence

_WORK = pathlib.Path(__file__).resolve().parents[3] / "work"
if str(_WORK) not in sys.path:
    sys.path.insert(0, str(_WORK))

import r2_safe_project as base  # noqa: E402 - 复用出站阻断与模块加载

CODE_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
CASE_ID_RE = re.compile(r"^H2V3-C[0-9]{2}$")


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _assert_safe(node: Any, depth: int = 0) -> None:
    if depth > 6:
        raise base.ToolError("unsafe_output_depth", "assert_safe")
    if node is None or isinstance(node, bool) or isinstance(node, int):
        return
    if isinstance(node, str):
        if CODE_RE.fullmatch(node) or CASE_ID_RE.fullmatch(node) or re.fullmatch(r"[0-9a-f]{8,64}", node):
            return
        raise base.ToolError("unsafe_output_string", "assert_safe")
    if isinstance(node, Mapping):
        for key, value in node.items():
            if not isinstance(key, str) or not CODE_RE.fullmatch(key):
                raise base.ToolError("unsafe_output_key", "assert_safe")
            _assert_safe(value, depth + 1)
        return
    if isinstance(node, (list, tuple)):
        for item in node:
            _assert_safe(item, depth + 1)
        return
    raise base.ToolError("unsafe_output_type", "assert_safe")


def main(argv: Sequence[str]) -> int:
    guard = base.NetGuard()
    guard.install()
    guard.positive_control()

    import argparse  # noqa: PLC0415

    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--binding", required=True)
    parser.add_argument("--case", default="H2V3-C29")
    parser.add_argument("--out", default=None)
    args = parser.parse_args(list(argv))

    binding = base._read_json(pathlib.Path(args.binding))
    runs = binding.get("runs")
    if not isinstance(runs, list) or not runs or not isinstance(runs[0], Mapping):
        raise base.ToolError("binding_invalid", "main")
    run_entry = runs[0]
    inputs = {str(name): {"path": record["path"]} for name, record in binding["inputs"].items()}
    try:
        entry = base._load_module(
            "p2_h2_v3_controlled_execute_predicate",
            base.TOOLS / "p2_h2_v3_controlled_execute.py",
        )
        bundle = entry.load_v3_bundle(inputs)
    except base.ToolError:
        raise
    except Exception:  # noqa: BLE001 - 只回固定码
        raise base.ToolError("bundle_load_failed", "main") from None
    scenario = str(run_entry.get("scenario_id"))
    try:
        cases = tuple(bundle.contract.subset(scenario).cases)
    except Exception:  # noqa: BLE001
        raise base.ToolError("case_subset_failed", "main") from None
    rows = [case for case in cases if str(getattr(case, "case_id", "")) == args.case]
    if len(rows) != 1:
        raise base.ToolError("case_not_in_contract", "main")
    question = str(getattr(rows[0], "question", "") or "")
    if not question:
        raise base.ToolError("case_question_absent", "main")

    import mktkb.rag.query as rag_query  # noqa: PLC0415

    norm_question = rag_query._norm(question)  # noqa: SLF001 - 产品纯函数，只读
    credential_matches = sum(
        1 for word in rag_query.CONTRACT_CREDENTIAL_WORDS if rag_query._norm(word) in norm_question  # noqa: SLF001
    )
    roles_with_entity = tuple(
        str(item) for item in rag_query.field_roles_for_question(question, has_entity=True)
    )
    roles_without_entity = tuple(
        str(item) for item in rag_query.field_roles_for_question(question, has_entity=False)
    )
    refusal_roles = set(rag_query.REFUSAL_CONTACT_ROLES)
    terms = tuple(str(item) for item in rag_query._terms(question))  # noqa: SLF001
    terms_joined = re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", "".join(terms).lower())
    terms_credential_hits = sum(
        1 for word in rag_query.CONTRACT_CREDENTIAL_WORDS if word in terms_joined
    )

    report = {
        "ok": True,
        "case_id": args.case if CASE_ID_RE.fullmatch(str(args.case)) else "unknown_case",
        "question_chars": len(question),
        "question_sha256": _sha(question)[:16],
        "predicate": {
            "is_contract_credential_question": bool(
                rag_query.is_contract_credential_question(question)
            ),
            "credential_word_match_count": int(credential_matches),
            "is_policy_question": bool(rag_query.is_policy_question(question)),
            "is_regulation_question": bool(rag_query.is_regulation_question(question)),
            "field_roles_has_entity": list(roles_with_entity),
            "field_roles_no_entity": list(roles_without_entity),
            "contact_disjunct_has_entity": bool(set(roles_with_entity) & refusal_roles),
            "contact_disjunct_no_entity": bool(set(roles_without_entity) & refusal_roles),
            "terms_count": len(terms),
            "terms_credential_hit_count": int(terms_credential_hits),
        },
        "netguard": guard.as_dict(),
    }
    _assert_safe(report)
    text = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if args.out:
        target = pathlib.Path(args.out)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except SystemExit:
        raise
    except base.ToolError as exc:
        print(json.dumps({"ok": False, "error": exc.code if CODE_RE.fullmatch(str(exc.code)) else "internal_error"}))
        raise SystemExit(2) from None
    except Exception:  # noqa: BLE001 - 绝不回显 str(exc)/traceback
        print(json.dumps({"ok": False, "error": "internal_error"}))
        raise SystemExit(3) from None

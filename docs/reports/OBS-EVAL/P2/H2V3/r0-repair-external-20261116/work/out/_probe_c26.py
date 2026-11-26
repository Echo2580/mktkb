"""C26 分支证据结构探针：只输出事件种类计数、枚举名、布尔、整数；绝不输出正文。

用途：解释本轮 C26 的 cross_entity / stale_source 为何是 unknown
（`branch_evidence_inconsistent`），对齐 `_turn_branch_matrix_violation` 的判定分支。
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import re
import sys

CODE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
HERE = pathlib.Path(__file__).resolve().parent
TARGET = HERE.parent / "recompute_axes_fullverify_v2.py"
TARGET_CASE = "H2V3-C26"


def main() -> int:
    spec = importlib.util.spec_from_file_location("_probe_recompute", TARGET)
    module = importlib.util.module_from_spec(spec)
    sys.modules["_probe_recompute"] = module
    spec.loader.exec_module(module)

    work = pathlib.Path(sys.argv[1])
    bindings = pathlib.Path(sys.argv[2])
    entry_mod = module.ENTRY
    hard = module.hard
    binding = module._binding_for(0, bindings)
    inputs = {name: {"path": record["path"]} for name, record in binding["inputs"].items()}
    bundle = entry_mod.load_v3_bundle(inputs)
    run_entry = binding["runs"][0]
    cases = tuple(bundle.contract.subset(str(run_entry["scenario_id"])).cases)
    case_plan = json.loads(
        (module._resolve_run_dir(work, 0) / "out" / "controlled" / "case-plan.json").read_text(
            encoding="utf-8"
        )
    )
    static_bindings = {
        name: value
        for name, value in dict(run_entry["evidence_bindings"]).items()
        if name != "index_revision"
    }
    plan = entry_mod.v2._load_plan_for_run(binding, run_entry)
    module.ENTRY.v2._validate_case_plan_document(
        case_plan, cases=cases, static_bindings=static_bindings
    )
    root = module._resolve_run_dir(work, 0) / "evidence" / str(run_entry["run_id"])
    receipt = json.loads(
        (module._resolve_run_dir(work, 0) / "seal" / str(run_entry["run_id"]) / "run-receipt.json").read_text(
            encoding="utf-8"
        )
    )
    _, _, audits, _ = module.current_round_results(
        document=binding,
        run_entry=run_entry,
        plan=plan,
        cases=cases,
        annotation=bundle.annotation,
        case_plan_payload=case_plan,
        evidence_dir=root,
        key=module.KEY_PATH.read_bytes().strip(),
        receipt=receipt,
        compat=hard.REFUSAL_COMPAT_V0_3,
    )
    audit = next(
        item for case, item in zip(cases, audits) if str(case.case_id) == TARGET_CASE
    )

    out = {"case_id": TARGET_CASE, "turns": []}
    for turn in audit["turns"]:
        row = {"turn_index": int(turn["turn_index"]), "status": str(turn["status"])}
        evidence = turn.get("evidence")
        if isinstance(evidence, dict):
            events = hard._events(evidence)  # noqa: SLF001 - 只读结构
            counts: dict[str, int] = {}
            for event in events:
                kind = str(event.get("kind"))
                counts[kind] = counts.get(kind, 0) + 1
            row["event_kinds"] = counts
            plan_rows = hard._payloads(events, "plan_observed")  # noqa: SLF001
            row["plan_path"] = (
                str(plan_rows[0].get("path") or "") if plan_rows else ""
            )
            row["plan_path_is_enum"] = row["plan_path"] in ("legacy", "rag")
            row["plan_field_role_present"] = any(
                key in (plan_rows[0] if plan_rows else {})
                for key in ("field_role", "field_roles", "targets")
            )
            inputs_, outputs_ = hard._model_event_rows(events)  # noqa: SLF001
            purposes = sorted(set(inputs_) | set(outputs_))
            row["purposes"] = [name for name in purposes if CODE.fullmatch(name)]
            row["purpose_counts"] = {
                name: [len(inputs_.get(name, [])), len(outputs_.get(name, []))]
                for name in purposes
                if CODE.fullmatch(name)
            }
            row["direct_rows"] = len(hard._payloads(events, "direct_rag_answer"))  # noqa: SLF001
            row["retrieval_rows"] = len(hard._payloads(events, "retrieval_observed"))  # noqa: SLF001
            answer = hard._payloads(events, "answer_result")  # noqa: SLF001
            commit = hard._payloads(events, "commit_observed")  # noqa: SLF001
            row["answer_count"] = len(answer)
            row["commit_count"] = len(commit)
            if answer and commit:
                row["answer_kind_equals_commit_kind"] = str(answer[0].get("kind")) == str(
                    commit[0].get("kind")
                )
                row["answer_kind_is_nofact"] = str(answer[0].get("kind")) in hard.NO_FACT_KINDS
                row["usage_lists_empty"] = not any(
                    (answer[0].get("source_ids"), commit[0].get("source_ids"))
                )
            violation = hard._turn_branch_matrix_violation(evidence)  # noqa: SLF001
            row["branch_matrix_violation"] = (
                None if violation is None else [str(violation[0]), str(violation[1])]
            )
            row["completeness"] = str((evidence.get("completeness") or {}).get("status"))
        out["turns"].append(row)
    print(json.dumps(out, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

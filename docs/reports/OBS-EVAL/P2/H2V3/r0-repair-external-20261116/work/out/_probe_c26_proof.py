"""C26 空用集证明探针：只输出「哪个 return 分支」的行号与固定码，绝不输出正文。

`_empty_use_scope_proof` 是 C26 这类无事实结局的 cross_entity / stale_source 证据面闸门。
本探针用 sys.settrace 记录该函数内最后命中的行号（行号即分支标识），再打印其返回的
固定 reason。不打印任何 payload / 文本 / 实体名。
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
TARGET = HERE.parent / "recompute_axes_fullverify_v2.py"
TARGET_CASE = "H2V3-C26"
FUNC = "_empty_use_scope_proof"


def main() -> int:
    spec = importlib.util.spec_from_file_location("_probe_recompute2", TARGET)
    module = importlib.util.module_from_spec(spec)
    sys.modules["_probe_recompute2"] = module
    spec.loader.exec_module(module)
    hard = module.hard
    entry_mod = module.ENTRY

    work = pathlib.Path(sys.argv[1])
    bindings = pathlib.Path(sys.argv[2])
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
    entry_mod.v2._validate_case_plan_document(
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
    audit = next(item for case, item in zip(cases, audits) if str(case.case_id) == TARGET_CASE)
    evidence = audit["turns"][0]["evidence"]

    target_file = str(pathlib.Path(hard.__file__).resolve())
    state = {"depth": 0, "last_line": None, "in_func": False}

    def _tracer(frame, event, arg):  # noqa: ANN001
        if frame.f_code.co_name != FUNC:
            return _tracer if state["in_func"] else None
        if event == "call":
            state["in_func"] = True
            state["depth"] = 1
            return _tracer
        if event == "line" and state["in_func"]:
            state["last_line"] = frame.f_lineno
        return _tracer

    original = getattr(hard, FUNC)
    sys.settrace(_tracer)
    try:
        proof = original(evidence, compat=hard.REFUSAL_COMPAT_V0_3)
    finally:
        sys.settrace(None)

    fname = str(pathlib.Path(hard.__file__).name)
    print(
        json.dumps(
            {
                "case_id": TARGET_CASE,
                "evidence_file": fname,
                "function": FUNC,
                "ok": bool(proof[0]),
                "reason": str(proof[1]),
                "last_line_hit": state["last_line"],
                "source_path_is_expected": str(pathlib.Path(hard.__file__).resolve()) == target_file,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

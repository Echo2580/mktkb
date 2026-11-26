r"""R2 适配层合成输入自检（T-R2-201 §5.3）：6 类故意错误输入必须**全部拒绝**。

本脚本只做一件事：把 ``r2_safe_project`` 里真实使用的门禁函数拿合成/变异输入打一遍，
证明"错 binding / 错业务日 / 错 case 集合 / 缺 C14 回合 / 旧卡当本轮 / 缺 scope 证据"
都不会被当成成功结论。每个 case 同时跑一次**未变异**的正对照，防止门禁变成"一律拒绝"
而假通过。

纪律
----
- 私有输入只在内存里用；输出只含固定码、布尔、计数、sha256、case_id；
- 出站由 ``r2_safe_project.NetGuard`` 阻断（含子进程面），全程零真实调用；
- 任一条未拒绝即 ``ok:false`` + 固定码 ``selftest_not_refused``，退出码 3。

运行
----
    .venv\Scripts\python.exe -X utf8 r2_selftest.py ^
      --key <ev.key> --binding <run2 binding> --r1-binding <run1 binding> ^
      --evidence-root <...\r2\evidence\...> ^
      --receipt <...\run-receipt.json> --seal-manifest <...\seal-manifest.json> ^
      --case-plan <repo\...\run\r2-final\case-plan.json> ^
      --out-dir <repo\...\r2-repair-external-20261117\evidence\01-safe-projection>
"""
from __future__ import annotations

import argparse
import copy
import json
import pathlib
import sys
from typing import Any, Mapping, Sequence

import r2_safe_project as proj


SELFTEST_ALLOWED = frozenset(
    {
        "ok",
        "error",
        "where",
        "round_label",
        "run_id",
        "run_index",
        "selftest_count",
        "all_refused",
        "positive_controls_total",
        "positive_controls_ok",
        "case",
        "cases",
        "refused",
        "error_code",
        "positive_control_ok",
        "variants",
        "label",
        "note_code",
        "netguard",
        "blocked_attempts",
        "blocked_subprocess_attempts",
        "subprocess_guard_installed",
        "positive_control_attempts",
        "positive_control_blocked",
        "outbound_allowed",
        "case_plan_sha256",
        "r1_binding_run_id_mismatch",
    }
)


def _assert_safe(node: Any, depth: int = 0) -> None:
    """与主投影器同口径的只增不减白名单（字符串仍必须是固定码/枚举/sha256/case_id）。"""
    if depth > 8:
        raise SystemExit("selftest_output_too_deep")
    if type(node) is bool:
        return
    if type(node) is int:
        if node < 0 or node > 10**9:
            raise SystemExit("selftest_int_out_of_range")
        return
    if type(node) is str:
        if not proj._safe_string(node):
            raise SystemExit("selftest_unsafe_string")
        return
    if isinstance(node, list):
        for item in node:
            _assert_safe(item, depth + 1)
        return
    if isinstance(node, dict):
        for key, value in node.items():
            if type(key) is not str or key not in SELFTEST_ALLOWED:
                raise SystemExit("selftest_unsafe_key")
            _assert_safe(value, depth + 1)
        return
    raise SystemExit("selftest_unsafe_type")


def _dump(payload: Mapping[str, Any], path: pathlib.Path, *, announce: bool = True) -> None:
    _assert_safe(dict(payload))
    text = json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text + "\n", encoding="utf-8")
    if announce:
        print(text)


def _expect_refused(call, *args: Any, **kwargs: Any) -> tuple[bool, str]:
    """跑一次门禁；被拒返回 (True, 固定码)，未被拒返回 (False, 'not_refused')。"""
    try:
        call(*args, **kwargs)
    except proj.ToolError as exc:
        code = str(exc.code)
        if not proj.CODE_RE.fullmatch(code):
            return True, "unclassified_refusal"
        return True, code
    return False, "not_refused"


def _expect_ok(call, *args: Any, **kwargs: Any) -> bool:
    try:
        call(*args, **kwargs)
    except proj.ToolError:
        return False
    return True


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--key", default=None)
    parser.add_argument("--binding", default=None)
    parser.add_argument("--r1-binding", default=None)
    parser.add_argument("--evidence-root", default=None)
    parser.add_argument("--receipt", default=None)
    parser.add_argument("--seal-manifest", default=None)
    parser.add_argument(
        "--case-plan",
        default=str(proj.REPO / "docs/reports/OBS-EVAL/P2/H2V3/fullverify-20261116/run/r2-final/case-plan.json"),
    )
    parser.add_argument(
        "--out-dir",
        default=str(
            proj.REPO
            / "docs/reports/OBS-EVAL/P2/H2V3/r2-repair-external-20261117/evidence/01-safe-projection"
        ),
    )
    args = parser.parse_args(list(argv))
    for name in ("key", "binding", "r1_binding", "evidence_root", "receipt", "seal_manifest"):
        if not getattr(args, name):
            raise SystemExit("argument_missing")
    return args


def main(argv: Sequence[str]) -> int:
    guard = proj.NetGuard()
    guard.install()
    guard.positive_control()
    args = _parse_args(argv)
    proj.gate_cwd_is_repo_root()

    case_plan = proj._read_json(pathlib.Path(args.case_plan))
    receipt = proj._read_json(pathlib.Path(args.receipt))
    seal_manifest = proj._read_json(pathlib.Path(args.seal_manifest))
    binding = proj._read_json(pathlib.Path(args.binding))
    r1_binding = proj._read_json(pathlib.Path(args.r1_binding))
    key = pathlib.Path(args.key).read_bytes().strip()
    evidence_root = pathlib.Path(args.evidence_root)

    plan_rows = [row for row in (case_plan.get("cases") or []) if isinstance(row, Mapping)]
    plan_ids = [str(row.get("case_id")) for row in plan_rows]
    run_entry = (binding.get("runs") or [{}])[0]
    r1_run_entry = (r1_binding.get("runs") or [{}])[0]

    rows: list[dict[str, Any]] = []
    positives_ok = 0

    # (a) 混入 R1 的 binding -------------------------------------------------
    refused, code = _expect_refused(
        proj.gate_run_identity, r1_run_entry, receipt, case_plan
    )
    positive_ok = _expect_ok(proj.gate_run_identity, run_entry, receipt, case_plan)
    positives_ok += int(positive_ok)
    rows.append(
        {
            "case": "r1_binding_mixed",
            "refused": bool(refused),
            "error_code": code,
            "positive_control_ok": bool(positive_ok),
        }
    )

    # (b) 错业务日 -----------------------------------------------------------
    bad_receipt = copy.deepcopy(receipt)
    bad_receipt["business_date"] = "2026-07-15"
    if isinstance(bad_receipt.get("run_binding"), dict):
        bad_receipt["run_binding"]["business_date"] = "2026-07-15"
    refused, code = _expect_refused(proj.gate_business_date, binding, bad_receipt, case_plan)
    positive_ok = _expect_ok(proj.gate_business_date, binding, receipt, case_plan)
    positives_ok += int(positive_ok)
    rows.append(
        {
            "case": "wrong_business_date",
            "refused": bool(refused),
            "error_code": code,
            "positive_control_ok": bool(positive_ok),
        }
    )

    # (c) 错 case 集合：少题 / 多题 / 重复 / 同数换题 --------------------------
    variants: list[dict[str, Any]] = []
    bad_sets = {
        "case_set_missing": list(plan_ids[:-1]),
        "case_set_extra": list(plan_ids) + ["H2V3-C30"],
        "case_set_duplicate": [plan_ids[0]] + list(plan_ids),
        "case_set_swapped": list(plan_ids[:-1]) + ["H2V3-C30"],
    }
    for label, bad_ids in bad_sets.items():
        refused_v, code_v = _expect_refused(proj.gate_case_set, bad_ids, plan_ids)
        variants.append({"label": label, "refused": bool(refused_v), "error_code": code_v})
    refused = all(bool(item["refused"]) for item in variants)
    codes = {str(item["error_code"]) for item in variants}
    code = codes.pop() if len(codes) == 1 else "identity_case_set_mismatch"
    positive_ok = _expect_ok(proj.gate_case_set, plan_ids, plan_ids)
    positives_ok += int(positive_ok)
    rows.append(
        {
            "case": "wrong_case_set",
            "refused": bool(refused),
            "error_code": code,
            "positive_control_ok": bool(positive_ok),
            "variants": variants,
        }
    )

    # (d) 缺 C14 回合 / 把两回合挪到别的题 ------------------------------------
    variants = []
    missing = []
    for row in plan_rows:
        row_copy = {**row, "turns": [dict(turn) for turn in (row.get("turns") or [])]}
        if str(row_copy.get("case_id")) == "H2V3-C14":
            row_copy["turns"] = row_copy["turns"][:1]
        missing.append(row_copy)
    refused_v, code_v = _expect_refused(proj.gate_turn_shape, missing)
    variants.append({"label": "c14_turn_missing", "refused": bool(refused_v), "error_code": code_v})
    moved = []
    for row in plan_rows:
        row_copy = {**row, "turns": [dict(turn) for turn in (row.get("turns") or [])]}
        row_copy["turns"] = list(row_copy["turns"])
        moved.append(row_copy)
    moved[0]["turns"] = [
        {"turn_index": 0, "status": "executed", "evidence_file": "turn-0000.fernet", "error": None},
        {"turn_index": 1, "status": "executed", "evidence_file": "turn-0001.fernet", "error": None},
    ]
    for row in moved:
        if str(row.get("case_id")) == "H2V3-C14":
            row["turns"] = [
                {"turn_index": 2, "status": "executed", "evidence_file": "turn-0002.fernet", "error": None}
            ]
    refused_v, code_v = _expect_refused(proj.gate_turn_shape, moved)
    variants.append({"label": "multi_turn_moved", "refused": bool(refused_v), "error_code": code_v})
    refused = all(bool(item["refused"]) for item in variants)
    codes = {str(item["error_code"]) for item in variants}
    code = codes.pop() if len(codes) == 1 else "identity_turn_count_mismatch"
    positive_ok = _expect_ok(proj.gate_turn_shape, plan_rows)
    positives_ok += int(positive_ok)
    rows.append(
        {
            "case": "wrong_turn_shape",
            "refused": bool(refused),
            "error_code": code,
            "positive_control_ok": bool(positive_ok),
            "variants": variants,
        }
    )

    # (e) 旧卡来源当本轮 -----------------------------------------------------
    turn_file = str((plan_rows[-1]["turns"] or [{}])[-1].get("evidence_file") or "turn-0005.fernet")
    real_sha = proj._sha256_file(evidence_root / turn_file)
    current_origin = {case_id: {"round": "current", "file_count": 1, "file_sha256": [real_sha]} for case_id in plan_ids}
    stale_origin = copy.deepcopy(current_origin)
    stale_origin[plan_ids[-1]]["round"] = "historical"
    refused, code = _expect_refused(proj.gate_origin_round, stale_origin)
    positive_ok = _expect_ok(proj.gate_origin_round, current_origin)
    positives_ok += int(positive_ok)
    rows.append(
        {
            "case": "stale_card_as_current",
            "refused": bool(refused),
            "error_code": code,
            "positive_control_ok": bool(positive_ok),
        }
    )

    # (f) 缺 scope 证据 ------------------------------------------------------
    from mktkb.evaluation.p2_evidence_io import read_encrypted_evidence  # noqa: PLC0415

    envelope = read_encrypted_evidence(
        evidence_root / turn_file, key=key, expected_bindings=dict(case_plan.get("bindings") or {})
    )
    real_scope = {plan_ids[-1]: [envelope]}
    variants = []
    no_projection = copy.deepcopy(envelope)
    no_projection.pop("db_projection", None)
    variants.append(
        {
            "label": "projection_missing",
            **_dict_pair(_expect_refused(proj.gate_scope_evidence, {plan_ids[-1]: [no_projection]})),
        }
    )
    no_capture = copy.deepcopy(envelope)
    no_capture.pop("capture", None)
    variants.append(
        {
            "label": "capture_missing",
            **_dict_pair(_expect_refused(proj.gate_scope_evidence, {plan_ids[-1]: [no_capture]})),
        }
    )
    no_units = copy.deepcopy(envelope)
    if isinstance(no_units.get("db_projection"), dict):
        no_units["db_projection"].pop("units", None)
    variants.append(
        {
            "label": "projection_units_missing",
            **_dict_pair(_expect_refused(proj.gate_scope_evidence, {plan_ids[-1]: [no_units]})),
        }
    )
    refused = all(bool(item["refused"]) for item in variants)
    codes = {str(item["error_code"]) for item in variants}
    code = codes.pop() if len(codes) == 1 else "scope_evidence_missing"
    positive_ok = _expect_ok(proj.gate_scope_evidence, real_scope)
    positives_ok += int(positive_ok)
    rows.append(
        {
            "case": "missing_scope_evidence",
            "refused": bool(refused),
            "error_code": code,
            "positive_control_ok": bool(positive_ok),
            "variants": variants,
        }
    )

    all_refused = all(bool(row["refused"]) and bool(row["positive_control_ok"]) for row in rows)
    payload: dict[str, Any] = {
        "ok": bool(all_refused),
        "round_label": proj.ROUND_LABEL,
        "run_id": str(case_plan.get("run_id")),
        "run_index": int(proj.EXPECTED_RUN_INDEX),
        "case_plan_sha256": proj._sha256_file(pathlib.Path(args.case_plan)),
        "selftest_count": len(rows),
        "all_refused": bool(all_refused),
        "positive_controls_total": len(rows),
        "positive_controls_ok": int(positives_ok),
        "cases": rows,
        "netguard": guard.as_dict(),
    }
    if not all_refused:
        payload["ok"] = False
        payload["error"] = "selftest_not_refused"
        payload["where"] = "main"
    _dump(payload, pathlib.Path(args.out_dir) / "r2-adaptation-selftest.json")
    return 0 if all_refused else 3


def _dict_pair(result: tuple[bool, str]) -> dict[str, Any]:
    refused, code = result
    return {"refused": bool(refused), "error_code": code}


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except SystemExit:
        raise
    except proj.ToolError as exc:  # 只写固定码，绝不回显 str(exc)/traceback
        code = str(exc.code) if proj.CODE_RE.fullmatch(str(exc.code)) else "internal_error"
        print(json.dumps({"ok": False, "error": code, "where": "main"}, ensure_ascii=False))
        raise SystemExit(2) from None
    except Exception:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": "internal_error", "where": "main"}, ensure_ascii=False))
        raise SystemExit(3) from None

"""生成 ``r2_recompute_axes.py``：从 R1 基座逐处定点替换，替换失败即停。

只做字符串替换，不做语义改写；每个替换点都断言“恰好命中 1 次”，
任何一处不匹配就抛固定码退出，避免“文件被改过却静默生成”。

输出：``work/r2_recompute_axes.py``（UTF-8 无 BOM，LF）。
本脚本只读 R1 基座，不写任何受保护文件。
"""

from __future__ import annotations

import hashlib
import pathlib

WORK = pathlib.Path(__file__).resolve().parent
HERE = WORK.parent
R1 = (
    HERE.parent
    / "r1-repair-external-20261117"
    / "work"
    / "r1_recompute_axes.py"
)
DST = WORK / "r2_recompute_axes.py"

HEADER = '''# T-R2-201B：R2（run_index=2）单轮四轴重算副本（从 R1 基座复制后定点改动）。
#
# 基座：r1-repair-external-20261117/work/r1_recompute_axes.py
#       基座与产物的 sha256 由 build_r2_script.py 实算输出，登记在 evidence/03-final-chain/NOTES.md。
# 改动清单（仅以下 5 项；判定逻辑 / matcher 调用 / 聚合 / 一致性门 / NetGuard / SAFE 出口一字未改）：
#   1) 默认 run 集合：``--runs`` 默认值改为 ``2``；非 ``[2]`` 的取值一律以固定码
#      ``single_run_isolation_violation`` 退出（绝不处理 r0/r1/r3）。
#   2) run 目录解析：沿用 ``<work>/r2`` 优先、其次单 run 根；解析后追加 receipt
#      ``run_index`` 必须等于 2 的断言。
#   3) 输出默认名：``work/out/recompute-v2-r2-repair.json``（R2 交付目录内）。
#   4) 轮次标签：``SCHEMA_VERSION`` 的 ``r2-same-round`` 与 argparse 描述/R2 注释。
#   5) 单 run 隔离：四 run 历史对照文件只物化 ``run_index=2`` 那一条（``_historical_run_entry``），
#      其余条目**不进内存**；收尾处再断言 runs_out / case_records 的 run_index 全为 2。
#      （``--compat`` 已原生支持 v0.6，无需改注入点。）
'''

REPLACEMENTS: list[tuple[str, str, str]] = [
    (
        "default_out",
        'DEFAULT_OUT = (\n'
        '    REPO\n'
        '    / "docs/reports/OBS-EVAL/P2/H2V3/r0-repair-external-20261116/work/out"\n'
        '    / "recompute-v2-r0-repair.json"\n'
        ')',
        'DEFAULT_OUT = (\n'
        '    REPO\n'
        '    / "docs/reports/OBS-EVAL/P2/H2V3/r2-repair-external-20261117/work/out"\n'
        '    / "recompute-v2-r2-repair.json"\n'
        ')',
    ),
    (
        "schema_version",
        'SCHEMA_VERSION = "p2-h2v3-axes-v2-recompute/v0.2-r0-same-round"',
        'SCHEMA_VERSION = "p2-h2v3-axes-v2-recompute/v0.2-r2-same-round"',
    ),
    (
        "single_run_const",
        'RUN_DIR_NAMES = {0: "r0", 1: "r1", 2: "r2", 3: "r3"}',
        'RUN_DIR_NAMES = {0: "r0", 1: "r1", 2: "r2", 3: "r3"}\n'
        '#: R2 单 run 隔离：本副本只允许处理这一个 run。\n'
        'SINGLE_RUN = 2',
    ),
    (
        "parse_runs_default",
        '    """``--runs 0`` / ``--runs 0,2``；空串=全部（默认行为不变）。"""\n'
        '    if text is None or not str(text).strip():\n'
        '        return sorted(RUN_DIR_NAMES)',
        '    """R2：空串=仅 run 2；任何非 ``[2]`` 的取值都在末尾被拒绝。"""\n'
        '    if text is None or not str(text).strip():\n'
        '        return [SINGLE_RUN]',
    ),
    (
        "parse_runs_guard",
        '    if not picked:\n'
        '        raise RuntimeError("runs_argument_invalid")\n'
        '    return picked',
        '    if not picked:\n'
        '        raise RuntimeError("runs_argument_invalid")\n'
        '    if picked != [SINGLE_RUN]:\n'
        '        # 单 run 隔离：r0/r1/r3 一律不进入本进程的分析路径。\n'
        '        raise RuntimeError("single_run_isolation_violation")\n'
        '    return picked',
    ),
    (
        "historical_picker",
        '    v1 = json.loads(base.V1_RESULTS.read_text(encoding="utf-8"))\n'
        '    v1_by_run = {int(item["run_index"]): item for item in v1["runs"]}',
        '    v1 = json.loads(base.V1_RESULTS.read_text(encoding="utf-8"))\n'
        '    # 单 run 隔离：四 run 历史对照件只物化 run_index=2 的条目，其余条目不进内存。\n'
        '    v1_run = _historical_run_entry(v1)',
    ),
    (
        "historical_use",
        '        v1_run = v1_by_run[run_index]\n'
        '        v1_cases = {str(row["case_id"]): row for row in v1_run["cases"]}',
        '        v1_cases = {str(row["case_id"]): row for row in v1_run["cases"]}',
    ),
    (
        "argparse_description",
        '    parser = argparse.ArgumentParser(description="r0 same-round axes recompute (v2)")',
        '    parser = argparse.ArgumentParser(description="r2 (run_index=2) same-round axes recompute (v2)")',
    ),
    (
        "runs_help",
        '        help="逗号分隔的 run_index；默认四个 run（旧行为不变）",',
        '        help="仅接受 2（R2 单 run 隔离）；默认即 2",',
    ),
    (
        "historical_helper",
        'def _binding_for(run_index: int, bindings_dir: pathlib.Path) -> Mapping[str, Any]:',
        'def _historical_run_entry(v1: Mapping[str, Any]) -> Mapping[str, Any]:\n'
        '    """只从四 run 历史对照件里取出 run_index=2 的唯一一条；其余条目不物化。\n'
        '\n'
        '    0 条（缺失）或 >1 条（重复）都 fail closed：不猜、不回填。\n'
        '    """\n'
        '    matches = [item for item in v1["runs"] if int(item.get("run_index", -1)) == SINGLE_RUN]\n'
        '    if len(matches) != 1:\n'
        '        raise FixedCode("single_run_historical_entry_invalid", "historical_v1")\n'
        '    return matches[0]\n'
        '\n'
        '\n'
        'def _binding_for(run_index: int, bindings_dir: pathlib.Path) -> Mapping[str, Any]:',
    ),
    (
        "loop_run_index_guard",
        '        if int(run_entry["run_index"]) != run_index:\n'
        '            raise RuntimeError("binding_run_index_mismatch")',
        '        if int(run_entry["run_index"]) != run_index:\n'
        '            raise RuntimeError("binding_run_index_mismatch")\n'
        '        if int(run_index) != SINGLE_RUN:\n'
        '            raise FixedCode("single_run_isolation_violation", "run_loop")',
    ),
    (
        "receipt_run_index_guard",
        '        business_date = str(receipt["business_date"])',
        '        if int(receipt.get("run_index", -1)) != SINGLE_RUN:\n'
        '            raise FixedCode("single_run_isolation_violation", "receipt_run_index")\n'
        '        business_date = str(receipt["business_date"])',
    ),
    (
        "payload_isolation_block",
        '        "netguard": (guard.as_dict() if guard is not None else None),',
        '        "single_run_isolation": {\n'
        '            "expected_run_index": SINGLE_RUN,\n'
        '            "selected_runs": [int(item) for item in selected_runs],\n'
        '            "runs_out": [int(run["run_index"]) for run in runs_out],\n'
        '            "case_records_total": len(case_records),\n'
        '            "case_records_run_index_set": sorted({int(row["run_index"]) for row in case_records}),\n'
        '            "historical_four_run_file": {\n'
        '                "role": "comparison_only",\n'
        '                "materialized_run_index": SINGLE_RUN,\n'
        '                "other_run_entries_materialized": 0,\n'
        '            },\n'
        '            "asserted": True,\n'
        '        },\n'
        '        "netguard": (guard.as_dict() if guard is not None else None),',
    ),
    (
        "final_isolation_assert",
        '    S.check_consistency({"runs": runs_out, "aggregate": aggregate})',
        '    _assert_single_run_output(runs_out, case_records)\n'
        '    S.check_consistency({"runs": runs_out, "aggregate": aggregate})',
    ),
    (
        "isolation_assert_def",
        'def _emit_failure(code: Any, where: Any) -> None:',
        'def _assert_single_run_output(\n'
        '    runs_out: Sequence[Mapping[str, Any]], case_records: Sequence[Mapping[str, Any]]\n'
        ') -> None:\n'
        '    """收尾断言：输出里出现任何非 2 的 run_index 即 fail closed。"""\n'
        '    if [int(run["run_index"]) for run in runs_out] != [SINGLE_RUN]:\n'
        '        raise FixedCode("single_run_isolation_violation", "runs_out")\n'
        '    if {int(row["run_index"]) for row in case_records} - {SINGLE_RUN}:\n'
        '        raise FixedCode("single_run_isolation_violation", "case_records")\n'
        '\n'
        '\n'
        'def _emit_failure(code: Any, where: Any) -> None:',
    ),
]


def main() -> int:
    raw = R1.read_bytes()
    src_sha = hashlib.sha256(raw).hexdigest()
    text = raw.decode("utf-8")
    for label, old, new in REPLACEMENTS:
        count = text.count(old)
        if count != 1:
            print(f"replacement_miss:{label}:{count}", flush=True)
            return 2
        text = text.replace(old, new)
    text = HEADER + text
    DST.write_bytes(text.encode("utf-8"))
    out_sha = hashlib.sha256(DST.read_bytes()).hexdigest()
    print(
        f"built={DST.name} source_sha256={src_sha} out_sha256={out_sha} "
        f"replacements={len(REPLACEMENTS)} header_lines={HEADER.count(chr(10))}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""v3 语料返工 R1：一致性自检（L1 计数、规格计数、manifest 计数三者对账）。

为什么单独一个脚本：上一轮交付里有两处**同类的「计数与数组不符」**——
① L1 ``coverage_selfcheck.totals.records_rows`` 写 2，而 ``records[]`` 实为 4 行；
② 规格 §7 写「不动的工作表 6 张（4 + 2）」，实测 8 张（4 + 4）。
只改这两处是不够的：必须**穷举复算**同一份文件里所有可复算的计数，才能回答「还有没有第三处」。

做法：把 L1 里每个可复算的计数声明逐条与「从数组重算」的结果对照；把规格 §7 的表数声明与
「真的打开 6 个 xlsx 数一遍」对照；把 manifest 的 ``lifecycle.totals`` 与实测对照。
每条都留 ``claim / expected / actual / ok``，不做「抽查」。

零真实调用。
用法：``.venv\\Scripts\\python.exe 08r1-consistency-selfcheck.py``
"""

from __future__ import annotations

import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path

import openpyxl

HERE = Path(__file__).resolve().parent
ROOT = Path(__file__).resolve().parents[7]
L1_PATH = ROOT / "docs/evaluation/p2-source-lifecycle-v1.json"
SPEC_PATH = ROOT / "docs/superpowers/plans/2026-11-15-h2-v3-corpus-modification-spec.md"
V3_ROOT = ROOT / "fixtures/acceptance-h2v3"
OUT = HERE / "08r1-consistency-selfcheck.json"

TARGET_SHEETS = {
    "variants/V03_物品位置表_历史V1.xlsx": "物品位置",
    "normal/D01_物品位置表.xlsx": "物品位置",
    "variants/V04_物品位置表_新版V3.xlsx": "物品位置",
    "variants/V05_物品位置表_新版V3_移除P01.xlsx": "物品位置",
    "normal/D02_合作店家信息.xlsx": "店家信息",
    "variants/V06_合作店家信息_新电话.xlsx": "店家信息",
}


def _d(value: str) -> date:
    return date.fromisoformat(value)


def covers(start: str, end: str | None, day: str) -> bool:
    if _d(day) < _d(start):
        return False
    return end is None or _d(day) <= _d(end)


def add(rows: list, ident: str, claim: str, expected, actual) -> None:
    rows.append({"id": ident, "claim": claim, "expected": expected, "actual": actual, "ok": expected == actual})


def main() -> int:
    l1 = json.loads(L1_PATH.read_text(encoding="utf-8"))
    sources = l1["sources"]
    records = l1["records"]
    totals = l1["coverage_selfcheck"]["totals"]
    per_run = l1["coverage_selfcheck"]["per_run_dates"]
    checks: list[dict] = []

    # ---------- L1：coverage_selfcheck.totals ----------
    add(checks, "l1.sources_rows", "sources_rows == len(sources[])", len(sources), totals["sources_rows"])
    add(checks, "l1.records_rows", "records_rows == len(records[])（R1 由 2 修为 4）", len(records), totals["records_rows"])
    windows = [(row["effective_from"], row["effective_to"]) for row in sources]
    add(checks, "l1.distinct_version_windows", "distinct_version_windows == 去重后的版本窗口数", len(set(windows)), totals["distinct_version_windows"])
    add(
        checks,
        "l1.three_fields_complete",
        "three_fields_complete == 同时具备 published_at/effective_from/effective_to 三键的版本行数",
        len(sources),
        totals["three_fields_complete"],
    )
    add(
        checks,
        "l1.published_at_gt_effective_from_violations",
        "published_at <= effective_from 违例数",
        sum(1 for row in sources if row["published_at"] and row["published_at"] > row["effective_from"]),
        totals["published_at_gt_effective_from_violations"],
    )
    built_at = totals["built_at_value"]
    add(
        checks,
        "l1.built_at_collisions",
        "任一 effective_from/effective_to 等于 built_at 的处数",
        sum(1 for row in sources if built_at in (row["effective_from"], row["effective_to"]))
        + sum(1 for row in records if built_at in (row["effective_from"], row["effective_to"])),
        totals["built_at_collisions"],
    )
    add(checks, "l1.all_same_window_detected", "all_same_window_detected == (窗口去重数 == 1)", len(set(windows)) == 1, totals["all_same_window_detected"])

    # 同槽位连续性 / 终端 null
    by_slot: dict[str, list] = {}
    for row in sources:
        by_slot.setdefault(row["doc_code"], []).append(row)
    contiguity_bad = 0
    terminal_bad = 0
    for _slot, rows in by_slot.items():
        rows = sorted(rows, key=lambda item: int(item["version_number"]))
        for prev, nxt in zip(rows, rows[1:]):
            if prev["effective_to"] is None or _d(nxt["effective_from"]) != _d(prev["effective_to"]) + timedelta(days=1):
                contiguity_bad += 1
        if rows[-1]["effective_to"] is not None:
            terminal_bad += 1
    add(checks, "l1.contiguity_violations", "同槽位后继 effective_from == 前驱 effective_to + 1 天的违例数", contiguity_bad, totals["contiguity_violations"])
    add(checks, "l1.terminal_not_open_violations", "同槽位最大版本 effective_to 必须为 null 的违例数", terminal_bad, totals["terminal_not_open_violations"])

    # records ⊆ 版本窗口 + 键唯一
    version_by_key = {(row["doc_code"], int(row["version_number"])): row for row in sources}
    out_of_window = 0
    for row in records:
        window = version_by_key[(row["doc_code"], int(row["version_number"]))]
        if window["effective_from"] > row["effective_from"]:
            out_of_window += 1
        if window["effective_to"] is not None and (row["effective_to"] is None or row["effective_to"] > window["effective_to"]):
            out_of_window += 1
    add(checks, "l1.records_out_of_version_window_violations", "records[] 窗口 ⊆ 同版本 sources[] 窗口的违例数", out_of_window, totals["records_out_of_version_window_violations"])
    keys = [(row["doc_code"], int(row["version_number"]), row["record_code"]) for row in records]
    add(checks, "l1.records_keys_unique", "records[] 的 (doc_code, version_number, record_code) 无重复", len(keys), len(set(keys)))

    # ---------- L1：per_run_dates ----------
    runs = per_run["runs"]
    rt = per_run["totals"]
    add(checks, "l1.per_run.cases", "per_run.total.cases == Σ runs[].cases", sum(row["cases"] for row in runs), rt["cases"])
    add(checks, "l1.per_run.turns", "per_run.total.turns == Σ runs[].turns", sum(row["turns"] for row in runs), rt["turns"])
    add(checks, "l1.per_run.slot_checks", "per_run.total.slot_checks == Σ runs[].uploaded_slots", sum(row["uploaded_slots"] for row in runs), rt["slot_checks"])
    add(
        checks,
        "l1.per_run.slot_cardinality_one",
        "per_run.total.slot_cardinality_one == 每 run 每槽位覆盖基数确为 1 的槽位数",
        sum(
            sum(1 for value in row["per_doc_code_cardinality"].values() if value == 1)
            for row in runs
        ),
        rt["slot_cardinality_one"],
    )
    add(
        checks,
        "l1.per_run.stale_decidable_cases",
        "per_run.total.stale_decidable_cases == Σ runs[].stale_decidable_cases",
        sum(row["stale_decidable_cases"] for row in runs),
        rt["stale_decidable_cases"],
    )
    add(
        checks,
        "l1.per_run.window_equals_position",
        "每个 run 的 window_active_equals_position_active 都必须为 true",
        True,
        all(row["window_active_equals_position_active"] for row in runs),
    )

    # ---------- anchor 基数 ----------
    anchor = l1["business_date_anchor"]
    anchor_expected = {}
    for slot in sorted(by_slot):
        count = sum(1 for row in by_slot[slot] if covers(row["effective_from"], row["effective_to"], anchor))
        anchor_expected[slot] = count
    declared_anchor = {slot: item["covering_count"] for slot, item in l1["coverage_selfcheck"]["anchor_2026_10_28"]["per_doc_code"].items()}
    add(checks, "l1.anchor_cardinality_one", "anchor 日每槽位覆盖集合基数恰为 1", {slot: 1 for slot in anchor_expected}, anchor_expected)
    add(checks, "l1.anchor_declared_matches", "anchor 声明值与重算值逐槽相等", anchor_expected, declared_anchor)

    # ---------- pre_freeze_revision.invariants_preserved 逐条 ----------
    add(checks, "l1.inv.published_le_from", "published_at <= effective_from：12/12", 12, sum(1 for row in sources if row["published_at"] <= row["effective_from"]))
    add(checks, "l1.inv.windows_distinct", "12 个版本窗口互不相同", 12, len(set(windows)))
    add(checks, "l1.inv.records_subset", "4 条 records[] 窗口全部 ⊆ 同版本窗口", 0, out_of_window)
    add(checks, "l1.inv.records_unique", "records[] 主键无重复", 0, len(keys) - len(set(keys)))

    # ---------- version_number_bijection ----------
    bijection = l1["coverage_selfcheck"]["version_number_bijection"]["with_source_map_v0_1_declared"]
    add(
        checks,
        "l1.bijection_mismatch",
        "v0.1 已声明的四个码与 L1 设计值冲突数（应与 mismatch_count 一致）",
        l1["coverage_selfcheck"]["version_number_bijection"]["mismatch_count"],
        sum(1 for item in bijection.values() if item["design"] != item["declared"]),
    )

    # ---------- 规格 §7 的表数 ----------
    measured_total_sheets = 0
    measured_target_sheets = 0
    measured_non_target_sheets = 0
    per_file = {}
    for rel, target in TARGET_SHEETS.items():
        wb = openpyxl.load_workbook(V3_ROOT / rel)
        non_target = [name for name in wb.sheetnames if name != target]
        per_file[rel] = {"sheets": list(wb.sheetnames), "target": target, "non_target": non_target}
        measured_total_sheets += len(wb.sheetnames)
        measured_target_sheets += 1
        measured_non_target_sheets += len(non_target)
    spare = sum(1 for item in per_file.values() for name in item["non_target"] if name.startswith("备用物料表"))
    draft = sum(1 for item in per_file.values() for name in item["non_target"] if name.startswith("旧草稿"))
    add(checks, "spec.non_target_sheets", "规格 §7『不动的工作表』== 实测非目标表数", measured_non_target_sheets, 8)
    add(checks, "spec.spare_sheets", "实测 备用物料表 张数", spare, 4)
    add(checks, "spec.draft_sheets", "实测 旧草稿 张数", draft, 4)
    add(checks, "spec.total_sheets", "6 个 xlsx 的表总数（目标 6 + 非目标 8）", measured_total_sheets, measured_target_sheets + measured_non_target_sheets)

    spec_text = SPEC_PATH.read_text(encoding="utf-8")
    add(checks, "spec.text_says_8", "规格 §7 现在写 8 张（4 + 4）", True, "**8 张**（4 个 `备用物料表` + 4 个 `旧草稿`）" in spec_text)
    add(checks, "spec.text_no_longer_6", "规格里旧的『6 张（4 个 备用物料表 + 2 个 旧草稿）』已不存在", False, "6 张（4 个 `备用物料表` + 2 个 `旧草稿`）" in spec_text)
    add(checks, "spec.text_has_sentinel_section", "规格含 §1.5 哨兵小节", True, "## 1.5 R1 修订" in spec_text)
    add(checks, "spec.text_sentinel_literal", "规格写死哨兵字面值 未声明", True, "未声明" in spec_text)
    add(checks, "spec.text_1_4_points_to_1_5", "规格 §1.4 的 null 分支指向 §1.5（不再写『留空单元格』）", True, "**写显式哨兵 `未声明`**（R1 修订，见 §1.5）" in spec_text)

    # ---------- manifest 计数对账 ----------
    manifest = json.loads((V3_ROOT / "manifest.json").read_text(encoding="utf-8"))
    lt = manifest["lifecycle"]["totals"]
    files = manifest["normal_files"] + manifest["variants"]
    add(checks, "manifest.corpus_files", "corpus_files == 实际清单条数", len(files), lt["corpus_files"])
    add(checks, "manifest.files_count", "清单 12 条（normal 6 + variants 6；V 前缀 6 个 + D 前缀 6 个）", (6, 6), (len(manifest["normal_files"]), len(manifest["variants"])))
    add(
        checks,
        "manifest.physical_files",
        "语料根物理文件数 = 12 源 + manifest.json",
        13,
        sum(1 for path in V3_ROOT.rglob("*") if path.is_file()),
    )
    add(checks, "manifest.unchanged_sheets", "unchanged_sheets == 实测非目标表数", measured_non_target_sheets, lt["unchanged_sheets"])
    add(checks, "manifest.applied_sheets", "applied_sheets == 6", measured_target_sheets, lt["applied_sheets"])
    add(checks, "manifest.data_cells_written", "data_cells_written == 数据行 39 × 2 列", 78, lt["data_cells_written"])
    add(checks, "manifest.sentinel", "data_cells_sentinel_not_asserted == 11", 11, lt["data_cells_sentinel_not_asserted"])
    add(checks, "manifest.blank", "data_cells_left_blank == 0", 0, lt["data_cells_left_blank"])
    add(checks, "manifest.existing_modified", "existing_cells_modified == 0", 0, lt["existing_cells_modified"])
    add(checks, "manifest.header_cells", "header_cells_added == 12", 12, lt["header_cells_added"])
    add(checks, "manifest.record_overrides", "record_override_rows == 4", 4, lt["record_override_rows"])
    add(
        checks,
        "manifest.sentinel_rows_per_file",
        "哨兵格数按文件：V05=7 / V06=4 / 其余 0",
        {"V05": 7, "V06": 4},
        {item["source_id"]: item["cells_sentinel_not_asserted"] for item in manifest["lifecycle"]["applied_sheets"] if item["cells_sentinel_not_asserted"]},
    )
    add(checks, "manifest.lifecycle_ref_sha", "manifest.lifecycle_ref.sha256 == L1 实际 SHA", True, manifest["lifecycle_ref"]["sha256"] == sha256_of(L1_PATH))
    add(
        checks,
        "manifest.file_shas",
        "manifest 逐文件 sha256 == 实际文件 sha256",
        0,
        sum(1 for item in files if item["sha256"] != sha256_of(V3_ROOT / item["path"])),
    )
    add(checks, "manifest.built_at", "built_at 仍为 2026-10-27", "2026-10-27", manifest["built_at"])
    add(checks, "manifest.sentinel_declared", "manifest 写死哨兵字面值", "未声明", manifest["lifecycle"]["effective_to_sentinel"]["literal"])

    mismatches = [row for row in checks if not row["ok"]]
    payload = {
        "schema_version": "p2h2v3-consistency-selfcheck/v0.1",
        "phase": "consistency-selfcheck-r1",
        "why": "上一轮有两处同类不一致（L1 records_rows 2≠4；规格 §7 表数 6≠8）。只修两处不够，必须穷举复算同文件里所有可复算的计数，才能回答『还有没有第三处』。",
        "convention": "每行 {id, claim, expected, actual, ok}：expected = 从数组/文件重算出的参考值，actual = 文件里的声明值（少数几行方向相反，但判定是对称的 expected == actual，不影响结论）。",
        "inputs": {
            "l1": {"path": "docs/evaluation/p2-source-lifecycle-v1.json", "sha256": sha256_of(L1_PATH)},
            "spec": {"path": "docs/superpowers/plans/2026-11-15-h2-v3-corpus-modification-spec.md", "sha256": sha256_of(SPEC_PATH)},
            "manifest": {"path": "fixtures/acceptance-h2v3/manifest.json", "sha256": sha256_of(V3_ROOT / "manifest.json")},
        },
        "sheet_measurement": {
            "per_file": per_file,
            "total_sheets": measured_total_sheets,
            "target_sheets": measured_target_sheets,
            "non_target_sheets": measured_non_target_sheets,
            "spare_sheets": spare,
            "draft_sheets": draft,
        },
        "checks": checks,
        "summary": {
            "checks": len(checks),
            "ok": len(checks) - len(mismatches),
            "mismatched": len(mismatches),
            "mismatched_ids": [row["id"] for row in mismatches],
        },
        "result": "CONSISTENT" if not mismatches else "INCONSISTENT",
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"summary": payload["summary"], "sheet_measurement": {k: v for k, v in payload["sheet_measurement"].items() if k != "per_file"}, "result": payload["result"]}, ensure_ascii=False, indent=1))
    for row in mismatches:
        print("MISMATCH:", row["id"], row["claim"], "expected", row["expected"], "actual", row["actual"], file=sys.stderr)
    return 0 if not mismatches else 1


def sha256_of(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    sys.exit(main())

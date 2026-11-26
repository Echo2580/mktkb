#!/usr/bin/env python
"""探针 16：契约 v0.2 ↔ 实现 ↔ C 冻结词表逐值一致；R-06/R-07；声明如实性。

C 冻结评测器只按源码文本 AST 读取常量（不 import、不执行、不改）。
输出：16-contract-consistency.out.json
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import Any

from _common import HERE, ROOT, axes, dump, rescore, unit

C_PATH = ROOT / "backend" / "src" / "mktkb" / "evaluation" / "p2_hard_evidence.py"
V02 = ROOT / "docs" / "evaluation" / "p2-evidence-rescore-v0_2.md"
V01 = ROOT / "docs" / "evaluation" / "p2-evidence-rescore-v0_1.md"
Q1A2 = ROOT / "docs" / "evaluation" / "q1a-scope-targets-contract-v1.md"
DEV_REPORT = ROOT / "docs" / "reports" / "OBS-EVAL" / "P2" / "Q1A-EVAL-REPAIR" / "axes" / "dev-report.md"

RESULTS: list[dict[str, Any]] = []


def check(label: str, ok: bool, detail: Any = None) -> None:
    RESULTS.append({"label": label, "ok": bool(ok), "detail": detail})


# --------------------------------------------------------------------------- #
# C 冻结词表：AST literal 提取（不 import）
# --------------------------------------------------------------------------- #
def literal(node: ast.AST) -> Any:
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, (ast.Tuple, ast.List)):
        return tuple(literal(item) for item in node.elts)
    if isinstance(node, ast.Set):
        return frozenset(literal(item) for item in node.elts)
    if isinstance(node, ast.Dict):
        return {literal(key): literal(value) for key, value in zip(node.keys, node.values)}
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Name) and func.id == "frozenset":
            return frozenset(literal(node.args[0]))
        if isinstance(func, ast.Attribute) and func.attr == "split":
            return tuple(str(literal(func.value)).split())
        if isinstance(func, ast.Name) and func.id == "tuple":
            return tuple(literal(node.args[0]))
    raise ValueError(f"unsupported literal node: {ast.dump(node)[:120]}")


def c_constants() -> dict[str, Any]:
    tree = ast.parse(C_PATH.read_text(encoding="utf-8"))
    wanted = {
        "AXES",
        "AXIS_STATES",
        "QUALITY_STATUSES",
        "AXIS_CRITERIA",
        "REASONS",
        "AXIS_KEYS",
        "TEMPORAL_INTENTS",
        "TARGET_REF_COLLECTIONS",
        "PASS_REASONS",
        "NA_REASONS",
        "UNKNOWN_REASONS_BY_AXIS",
        "VIOLATION_REASONS_BY_AXIS",
        "SCOPE_MODES",
        "SHARED_BACKGROUND_BASES",
        "SCOPE_BINDING_KEYS",
    }
    found: dict[str, Any] = {}
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id in wanted and node.value is not None:
                found[node.target.id] = literal(node.value)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in wanted:
                    found[target.id] = literal(node.value)
    return found


def doc_section(text: str, heading: str, stop: str) -> str:
    start = text.index(heading)
    end = text.index(stop, start + len(heading))
    return text[start:end]


def backticked(block: str) -> list[str]:
    return re.findall(r"`([^`]+)`", block)


def axis_bullets(block: str) -> dict[str, set[str]]:
    """解析 `- cross_user：`a`、`b`… 的多行 bullet。"""
    result: dict[str, set[str]] = {}
    current: str | None = None
    for line in block.splitlines():
        match = re.match(r"^- (cross_user|cross_entity|stale_source)：", line.strip())
        if match:
            current = match.group(1)
            result[current] = set(backticked(line))
            continue
        if current is not None and line.startswith("  "):
            result[current].update(backticked(line))
        elif line.strip() == "" or not line.startswith("  "):
            current = None
    return result


def main() -> int:
    c = c_constants()
    v02 = V02.read_text(encoding="utf-8")
    v01 = V01.read_text(encoding="utf-8")
    q1a2 = Q1A2.read_text(encoding="utf-8")
    dev = DEV_REPORT.read_text(encoding="utf-8")

    # ---- C 冻结词表 vs 实现 ----
    check("C REASONS has 18 codes", len(c["REASONS"]) == 18, len(c["REASONS"]))
    check("implementation ANNOTATION_REASONS == C REASONS", axes.ANNOTATION_REASONS == c["REASONS"], sorted(c["REASONS"] ^ axes.ANNOTATION_REASONS))
    check("AXIS_KEYS(7) + basis/source == ANNOTATION_KEYS", axes.ANNOTATION_KEYS == c["AXIS_KEYS"] | {"basis", "source"}, sorted(axes.ANNOTATION_KEYS ^ (c["AXIS_KEYS"] | {"basis", "source"})))
    check("UNKNOWN_REASONS == C UNKNOWN_REASONS_BY_AXIS (3 axes)", all(axes.UNKNOWN_REASONS[a] == c["UNKNOWN_REASONS_BY_AXIS"][a] for a in axes.RESCORED_AXES), {a: sorted(axes.UNKNOWN_REASONS[a] ^ c["UNKNOWN_REASONS_BY_AXIS"][a]) for a in axes.RESCORED_AXES})
    check("VIOLATION_REASONS == C VIOLATION_REASONS_BY_AXIS", all(axes.VIOLATION_REASONS[a] == c["VIOLATION_REASONS_BY_AXIS"][a] for a in axes.RESCORED_AXES), {a: sorted(axes.VIOLATION_REASONS[a] ^ c["VIOLATION_REASONS_BY_AXIS"][a]) for a in axes.RESCORED_AXES})
    check("PASS_REASONS == C", all(axes.PASS_REASONS[a] == c["PASS_REASONS"][a] for a in axes.RESCORED_AXES), {a: (axes.PASS_REASONS[a], c["PASS_REASONS"][a]) for a in axes.RESCORED_AXES})
    check("NA_REASONS == C", all(axes.NA_REASONS[a] == c["NA_REASONS"][a] for a in axes.RESCORED_AXES))
    check("AXIS_CRITERIA == C (3 axes)", all(axes.AXIS_CRITERIA[a] == c["AXIS_CRITERIA"][a] for a in axes.RESCORED_AXES), {a: sorted(axes.AXIS_CRITERIA[a] ^ c["AXIS_CRITERIA"][a]) for a in axes.RESCORED_AXES})
    check("TEMPORAL_INTENTS == C", tuple(axes.TEMPORAL_INTENTS) == tuple(c["TEMPORAL_INTENTS"]), (axes.TEMPORAL_INTENTS, c["TEMPORAL_INTENTS"]))
    check("TARGET_REF_COLLECTIONS == C", tuple(axes.TARGET_REF_COLLECTIONS) == tuple(c["TARGET_REF_COLLECTIONS"]))
    check("SCOPE_MODES == C", tuple(axes.SCOPE_MODES) == tuple(c["SCOPE_MODES"]))
    check("SHARED_BACKGROUND_BASES == C", tuple(axes.SHARED_BACKGROUND_BASES) == tuple(c["SHARED_BACKGROUND_BASES"]))
    check("BINDING_KEYS == C SCOPE_BINDING_KEYS", tuple(axes.BINDING_KEYS) == tuple(c["SCOPE_BINDING_KEYS"]))
    check("QUALITY_STATUSES == C", tuple(axes.QUALITY_STATUSES) == tuple(c["QUALITY_STATUSES"]))
    check("AXIS_STATES == C", tuple(axes.AXIS_STATES) == tuple(c["AXIS_STATES"]))
    check("AXES order == C", tuple(axes.AXES) == tuple(c["AXES"]))

    # ---- v0.2 §7 码表 vs 实现 ----
    unknown_block = doc_section(v02, "### 7.2 unknown reason", "### 7.3 violation reason")
    violation_block = doc_section(v02, "### 7.3 violation reason", "### 7.4 审计码")
    audit_block = doc_section(v02, "### 7.4 审计码", "### 7.5 matcher")
    doc_unknown = axis_bullets(unknown_block)
    doc_violation = axis_bullets(violation_block)
    check("v0.2 §7.2 parsed 3 axes", set(doc_unknown) == set(axes.RESCORED_AXES), sorted(doc_unknown))
    check("v0.2 §7.2 unknown lists == implementation", all(doc_unknown[a] == set(axes.UNKNOWN_REASONS[a]) for a in axes.RESCORED_AXES), {a: {"doc_only": sorted(doc_unknown[a] - set(axes.UNKNOWN_REASONS[a])), "impl_only": sorted(set(axes.UNKNOWN_REASONS[a]) - doc_unknown[a])} for a in axes.RESCORED_AXES})
    check("v0.2 §7.3 violation lists == implementation", all(doc_violation[a] == set(axes.VIOLATION_REASONS[a]) for a in axes.RESCORED_AXES), {a: {"doc_only": sorted(doc_violation[a] - set(axes.VIOLATION_REASONS[a])), "impl_only": sorted(set(axes.VIOLATION_REASONS[a]) - doc_violation[a])} for a in axes.RESCORED_AXES})
    doc_audit = set(backticked(audit_block))
    check("v0.2 §7.4 audit codes == AXES_AUDIT_CODES", doc_audit == set(axes.AXES_AUDIT_CODES), {"doc_only": sorted(doc_audit - set(axes.AXES_AUDIT_CODES)), "impl_only": sorted(set(axes.AXES_AUDIT_CODES) - doc_audit)})

    # ---- v0.2 §4.2 basis / source 枚举 ----
    basis_para = v02[v02.index("固定 `basis` 枚举：") : v02.index("\n\n", v02.index("固定 `basis` 枚举："))].split("。")[0].split("枚举：", 1)[1]
    doc_bases = set(backticked(basis_para))
    check("v0.2 basis enum == AXES_BASES", doc_bases == set(axes.AXES_BASES), sorted(doc_bases ^ set(axes.AXES_BASES)))
    source_para = v02[v02.index("固定来源标记枚举：") : v02.index("\n\n", v02.index("固定来源标记枚举："))].split("。")[0]
    doc_sources = set(backticked(source_para))
    check("v0.2 source enum == AXES_SOURCES", doc_sources == set(axes.AXES_SOURCES), sorted(doc_sources ^ set(axes.AXES_SOURCES)))
    check("TRUSTED_SOURCES excludes synthetic+unresolved", axes.TRUSTED_SOURCES == set(axes.AXES_SOURCES) - {"synthetic_fixture", "unresolved"})
    check("Q1a-2 basis 5 codes ⊆ AXES_BASES", set(axes.Q1A2_BASIS_CODES) <= set(axes.AXES_BASES) and len(axes.Q1A2_BASIS_CODES) == 5, sorted(axes.Q1A2_BASIS_CODES))

    # ---- Q1a-2 公开 schema 的 reason 码：权威 18，文档“19 码”是笔误 ----
    schema_start = q1a2.index("### 3.2")
    schema_body = q1a2[q1a2.index("\n", schema_start) + 1 :].lstrip("\n")
    schema_para = schema_body[: schema_body.index("\n\n")]
    schema_reasons = set(backticked(schema_para))
    check("Q1a-2 schema lists 18 reason codes despite '19 码' label", len(schema_reasons) == 18, sorted(schema_reasons))
    check("Q1a-2 schema reasons == C REASONS (18)", schema_reasons == set(c["REASONS"]), sorted(schema_reasons ^ set(c["REASONS"])))
    check("Q1a-2 schema reasons == implementation", schema_reasons == set(axes.ANNOTATION_REASONS))

    # ---- R-06 / R-07 ----
    check("v0.2 §6.1 states first-unknown-reason order", "首个固定码" in v02 and "1. 轴对象缺失" in v02)
    check("v0.2 §10 R-06 present", "R-06" in v02 and "annotation_unknown` 只在注解本身是首个/唯一 unknown 时出现" in v02)
    check("v0.2 §10 R-07 present", "R-07" in v02 and "防御性保留码" in v02 and "不可达" in v02)
    check("ref_doc_missing is in MATCH_CODES but unreachable via public API", "ref_doc_missing" in rescore.MATCH_CODES)
    try:
        rescore.match_ref_to_unit({"locator": {"row": 1}}, unit("u1"))
    except rescore.RescoreError as exc:
        check("ref without doc_code raises ref_invalid (not ref_doc_missing)", str(exc) == "ref_invalid", str(exc))
    else:
        check("ref without doc_code raises ref_invalid (not ref_doc_missing)", False, "accepted")

    # ---- 文档内部不一致（记录为残余，不掩盖） ----
    cross_user_doc = unknown_block[: unknown_block.index("- cross_entity")]
    contradiction = "`annotation_unknown`" in v02.split("### 5.1")[1].split("### 5.2")[0] and "annotation_unknown" not in cross_user_doc
    check("v0.2 §5.1 says cross_user N/A -> annotation_unknown, but §7.2 table lacks it (doc defect)", contradiction, {"doc_5_1_claims_annotation_unknown": True, "doc_7_2_has_it": "annotation_unknown" in cross_user_doc})
    check("implementation uses frozen cross_user reason instead (evidence_incomplete)", "evidence_incomplete" in axes.UNKNOWN_REASONS["cross_user"])

    # ---- 声明如实性（不覆盖全轴 / Q1a-3 未执行） ----
    check("v0.2 declares scope excludes full-axis completion", "不在本契约范围" in v02 and "不构成 Q1A 通过" in v02 and "Q1a-3 仍须" in v02)
    check("v0.2 §2 states safety stays recorded_old in this module", "本模块仍 `recorded_old`" in v02 or "safety 轴 | `rescored` | 本模块仍 `recorded_old`" in v02)
    check("v0.2 §9 requires merging before claiming four axes", "不得用单侧报告冒充四轴完成" in v02 or "任一侧单独都不能声称“四轴重评分完成”" in v02)
    check("dev report marks itself as awaiting independent review", "待全新独立验收" in dev)
    positive_claims = [
        line.strip()
        for line in dev.splitlines()
        if ("T207 通过。" in line or "整体重评分完成。" in line or "release_ready\": true" in line or "已发布" in line)
    ]
    check("dev report has no positive pass/release sentence", positive_claims == [], positive_claims)
    v02_positive = [
        line.strip()
        for line in v02.splitlines()
        if ("T207 通过" in line or "整体重评分完成" in line or "已发布" in line)
        and not any(neg in line for neg in ("不", "未", "非"))
    ]
    check("v0.2 has no positive pass/release claim", v02_positive == [], v02_positive)

    # ---- 冻结文件未改 ----
    check("v0.1 contract unchanged hash prefix", rescore.file_sha256(V01).startswith("e0487f25"), rescore.file_sha256(V01))
    check("p2_evidence_rescore.py unchanged hash prefix", rescore.file_sha256(ROOT / "backend" / "src" / "mktkb" / "evaluation" / "p2_evidence_rescore.py").startswith("d8260256"))

    failures = [item for item in RESULTS if not item["ok"]]
    payload = {
        "probe": "16-contract-consistency",
        "assertions_total": len(RESULTS),
        "assertions_failed": len(failures),
        "failures": failures,
        "results": RESULTS,
        "c_frozen_summary": {
            "reasons": len(c["REASONS"]),
            "axis_keys": sorted(c["AXIS_KEYS"]),
            "unknown_counts": {axis: len(c["UNKNOWN_REASONS_BY_AXIS"][axis]) for axis in axes.RESCORED_AXES},
        },
        "verdict": "PASS" if not failures else "FAIL",
    }
    dump(HERE / "16-contract-consistency.out.json", payload)
    print(json.dumps({"assertions": len(RESULTS), "failed": len(failures), "verdict": payload["verdict"]}, ensure_ascii=False))
    if failures:
        print(json.dumps(failures, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())




"""H2 缺口 A/B 修前/修后对照（只读、合成数据、零请求、不写仓库）。

用法（仓库根目录）：

    .\\.venv\\Scripts\\python.exe docs\\reports\\OBS-EVAL\\P2\\H2-DOC-REBUILD\\repro_gap.py

说明（为什么是“语义回放”而不是 `git show HEAD:`）
---------------------------------------------------
``backend/src/mktkb/evaluation/p2_hard_evidence.py``、``p2_evidence_rescore.py``、
``tools/p2_h2_controlled_execute.py``、``tools/p2_h2_v3_controlled_execute.py`` 在本工作树里
是**未跟踪文件**（``git ls-files`` 不含它们，``git show HEAD:<path>`` 报 "exists on disk, but
not in HEAD"）。所以接手锚点没有这四份文件的 git 基线，无法用 ``git show`` 取回修前字节。

本脚本因此**逐字回放**修前分支的判定门（接手任务书 §2 记录的缺口 A 语义）：修前
``ForbiddenSourceIdentity.matches`` 的第一句就是 ``located = _ref_matches_unit(ref, unit);
if located is not True: return located``，而 ``_ref_matches_unit`` 在 ref 只有 ``doc_code`` 时
返回 ``None``。该函数在工作树里**未被修改**，因此回放用的是同一个函数、同一份合成输入，
只把“先要求定位”的那道门恢复回去；定位命中的引用随后仍走同样逐值身份比较。修后列则是
工作树当前实现。两列都由本脚本真实执行得到。

脚本不读真实题面/标签/密文/密钥，不发起任何网络或供应商调用。
"""
from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
for extra in (
    ROOT / "backend" / "src",
    ROOT / "backend" / "tests",
    ROOT / "backend" / "tests" / "evaluation",
):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from mktkb.evaluation import p2_hard_evidence as hard_fixed  # noqa: E402
from test_p2_hard_evidence import build_evidence, make_annotation, _one_case  # noqa: E402

TARGET = ROOT / "backend/src/mktkb/evaluation/p2_hard_evidence.py"
SOURCE_MAP = {
    "D01": {"base_doc_code": "D01", "version_number": 2},
    "V03": {"base_doc_code": "D01", "version_number": 1},
    "V04": {"base_doc_code": "D01", "version_number": 3},
    "D02": {"base_doc_code": "D02", "version_number": 1},
}
DOCUMENT_CODES = {
    "synthetic-old.xlsx": "D01",
    "synthetic-old": "D01",
    "synthetic-current.xlsx": "V04",
    "synthetic-other.xlsx": "D02",
}


class PreFixForbiddenSourceIdentity(hard_fixed.ForbiddenSourceIdentity):
    """接手锚点版本的 matches：定位层不返回 True 就直接把 None/False 交出去。

    只有“先要求定位”的那一句是修前的；定位命中后的文档 + 版本逐值比较沿用同一实现
    （它与修前逐值语义一致，见 p2_evidence_rescore.match_document_identity）。
    """

    def matches(self, ref, unit):  # type: ignore[override]
        located = hard_fixed._ref_matches_unit(ref, unit)
        if located is not True:
            return located
        return super().matches(ref, unit)


def identity(module, *, pre_fix: bool):
    mapping = SOURCE_MAP
    codes = DOCUMENT_CODES
    factory = PreFixForbiddenSourceIdentity if pre_fix else module.ForbiddenSourceIdentity
    return factory(mapping, codes)


def verdict(module, case, evidence, *, with_identity: bool, v3: bool, pre_fix: bool) -> str:
    payload = make_annotation((case,))
    if v3:
        payload = dict(payload)
        payload["bindings"] = dict(payload["bindings"])
        payload["bindings"]["dataset_version"] = "P2-HOLDOUT-v3.3"
    annotation = module.prepare_annotation(payload, (case,))
    audit = {
        "quality_status": "pass",
        "turns": [{"turn_index": 0, "status": "executed", "error": None, "evidence": evidence}],
    }
    kwargs = {"source_identity": identity(module, pre_fix=pre_fix)} if with_identity else {}
    result = module.classify_case_evidence(case, annotation, audit, **kwargs)
    axis = result.axis("safety")
    return axis.state + "/" + (axis.reason or "-")


def main() -> int:
    lines: list[str] = []

    def emit(text: str = "") -> None:
        lines.append(text)
        print(text)

    emit("HEAD               : " + _git("rev-parse", "HEAD"))
    emit("target tracked?    : no（git ls-files 不含，无 git 基线）")
    emit("worktree sha256    : " + hashlib.sha256(TARGET.read_bytes()).hexdigest())
    emit("pre-fix replay     : " + PreFixForbiddenSourceIdentity.__doc__.splitlines()[0].strip())

    doc_case = _one_case(forbidden_sources=({"doc_code": "D01"},))
    same = build_evidence(units=[{"document_name": "synthetic-old.xlsx", "version_number": 2}])
    cross = build_evidence(units=[{"document_name": "synthetic-current.xlsx", "version_number": 3}])
    other = build_evidence(units=[{"document_name": "synthetic-other.xlsx", "version_number": 1}])
    unmapped = build_evidence(
        units=[{"document_name": "synthetic-unknown.xlsx", "version_number": 2}]
    )
    bad_version = build_evidence(
        units=[{"document_name": "synthetic-old.xlsx", "version_number": 0}]
    )
    rows = [
        ("A 同文档同版本（应 violation）", same, True, False),
        ("A 同 base 跨版本（应排除）", cross, True, False),
        ("A 其他文档（应排除）", other, True, False),
        ("A 文档名无映射（应 unknown）", unmapped, True, False),
        ("A 版本不合法（应 unknown）", bad_version, True, False),
        ("A 纯文档引用但没给身份（应 unknown）", same, False, False),
        ("B v3 未传身份（应 unknown）", same, False, True),
        ("B v3 传入冻结身份（应 violation）", same, True, True),
    ]
    emit(f"\n{'场景':44s} {'修前（回放）':46s} 修后（工作树）")
    for label, evidence, with_identity, v3 in rows:
        before = verdict(
            hard_fixed, doc_case, evidence, with_identity=with_identity, v3=v3, pre_fix=True
        )
        after = verdict(
            hard_fixed, doc_case, evidence, with_identity=with_identity, v3=v3, pre_fix=False
        )
        emit(f"{label:44s} {before:46s} {after}")
    emit()
    emit(
        json.dumps(
            {"worktree_sha256": hashlib.sha256(TARGET.read_bytes()).hexdigest()},
            ensure_ascii=False,
        )
    )
    out = Path(__file__).resolve().parent / "repro-output.txt"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0


def _git(*args: str) -> str:
    import subprocess

    completed = subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=False
    )
    return completed.stdout.strip() or completed.stderr.strip()


if __name__ == "__main__":
    raise SystemExit(main())

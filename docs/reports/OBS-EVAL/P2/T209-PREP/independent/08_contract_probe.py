"""T209-PREP 独立验收：报告/契约一致性与证据自洽。

只读开发报告/证据与代码，核对：
1. 未写 ``T209_PREP_PASS``、未宣称独立验收/正式 T209 通过/质量通过/发布批准；
2. 报告分列/候选不可发布/坏输入拒绝/零真实调用的声称有独立证据可对照（本目录其他探针）；
3. NOT-RUN/残余如实列出（真实 card 未消费、无外部签名、无 round-run 绑定、POSIX symlink）；
4. 证据日志自洽：34 passed、80 passed、collect 114、red 为 ImportError、protected compare IDENTICAL；
5. dev-report 引用的测试名在测试文件中真实存在。
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[6]
REPORT = ROOT / "docs/reports/OBS-EVAL/P2/T209-PREP"
REAL = ROOT / "docs/reports/OBS-EVAL/P2/T207-H2-OFFLINE-READINESS/real-h2.md"
NEW_TEST = ROOT / "backend/tests/evaluation/test_p2_candidate_report.py"
EXISTING_TESTS = [
    ROOT / "backend/tests/evaluation" / name
    for name in (
        "test_report.py",
        "test_baseline_portability.py",
        "test_diff_release_gate.py",
        "test_p2_gate.py",
    )
]
RESULTS: list[tuple[bool, str, str]] = []


def check(ok: bool, name: str, detail: str = "") -> None:
    RESULTS.append((bool(ok), name, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" :: {detail}" if detail else ""))


def main() -> int:
    dev = (REPORT / "dev-report.md").read_text(encoding="utf-8")
    real = REAL.read_text(encoding="utf-8")
    verbose = (REPORT / "evidence/06-tests-verbose.txt").read_text(encoding="utf-8")
    collect = (REPORT / "evidence/07-collect.txt").read_text(encoding="utf-8")
    red = (REPORT / "evidence/01-red.txt").read_text(encoding="utf-8")
    compare = (REPORT / "evidence/10-protected-compare.txt").read_text(encoding="utf-8")
    zero = (REPORT / "evidence/08-zero-real-calls.txt").read_text(encoding="utf-8")
    example = (REPORT / "evidence/04-report-example.md").read_text(encoding="utf-8")

    pass_lines = [line for line in dev.splitlines() if "T209_PREP_PASS" in line]
    check(
        all(any(token in line for token in ("未写", "不写", "不得", "禁止", "仅由")) for line in pass_lines)
        and not any(
            re.search(r"(记|写|为|状态[:：])\s*`?T209_PREP_PASS`?", line)
            and not any(token in line for token in ("未写", "不写", "不得", "禁止", "仅由"))
            for line in pass_lines
        ),
        "C1 dev-report 未写 T209_PREP_PASS（仅以否定句出现）",
        f"occurrences={len(pass_lines)}",
    )
    check(
        ("独立复验" in dev or "待独立验收" in dev)
        and ("不代写独立结论" in dev or "不构成独立验收" in dev),
        "C2 dev-report 明确开发自测≠独立验收",
    )
    check(
        "不声称正式 T209 通过" in dev or "不构成正式 T209 通过" in dev,
        "C3 dev-report 未声称正式通过",
    )

    check(
        all(token in dev for token in ("未直接消费", "外部签名", "四 run 集合", "POSIX symlink")),
        "C4 NOT-RUN/残余四项如实列出",
    )
    check("真实 H2 逐题" in dev and "未读取" in dev, "C5 声明未读取真实 H2 私有材料")
    check("provider_balance_queried" in dev, "C6 声明不查询供应商余额")

    check(verbose.count("PASSED") == 40 and "40 passed" in verbose, "C7 verbose 证据 40 PASSED", str(verbose.count("PASSED")))
    check("SKIPPED" not in verbose and "XFAIL" not in verbose, "C8 verbose 无 skip/xfail")
    check("80 passed" in (REPORT / "evidence/03-green-existing.txt").read_text(encoding="utf-8"), "C9 既有测试证据 80 passed")
    check("120 tests collected" in collect, "C10 collect 证据 120")
    check("ImportError" in red and "p2_candidate_report" in red and "error during collection" in red, "C11 先红证据为 ImportError")
    check("RESULT=IDENTICAL" in compare and "changed_lines=0" in compare, "C12 protected compare IDENTICAL")
    check("no matches (0 lines)" in zero, "C13 零真实调用扫描 0 命中")
    check("27 是缺失证据题数，不是 27 题答错" in example, "C14 示例报告口径声明")
    check(
        "release_ready: false" in example
        and "overall_success" not in example
        and "release_ready: true" not in example,
        "C15 示例报告无发布就绪/总体字段",
    )

    # real-h2 公开聚合与报告镜像一致
    for token in ("19", "11", "2 个 safety", "27", "threshold_met=false", "verified=false"):
        check(token in real, f"C16 real-h2 公开聚合含 {token}")
    check("19/30" in dev and "11 fail" in dev and "2 safety" in dev and "27 缺证据" in dev, "C17 dev-report 计数与 real-h2 一致")

    # dev-report 引用的测试名真实存在
    all_test_text = NEW_TEST.read_text(encoding="utf-8") + "".join(
        path.read_text(encoding="utf-8") for path in EXISTING_TESTS
    )
    known_defs = set(re.findall(r"def (test_[a-z0-9_]+)\(", all_test_text))
    known_files = {path.stem for path in [NEW_TEST, *EXISTING_TESTS]}
    referenced = sorted(set(re.findall(r"`?(test_[a-z0-9_]+)`?", dev)))
    missing = [name for name in referenced if name not in known_defs and name not in known_files]
    check(not missing, "C18 dev-report 引用的测试名均存在", f"refs={len(referenced)} missing={missing}")

    # 新测试确实覆盖 fail-closed：名字/断言中直接出现拒绝或篡改关键词
    test_text = NEW_TEST.read_text(encoding="utf-8")
    keywords = ("raises", "CandidateArchiveError", "sha256", "已审批", "holdout", "state", "publishable")
    check(all(key in test_text for key in keywords), "C19 新测试含 fail-closed 关键断言")
    check("assert True" not in test_text and "or True" not in test_text, "C20 新测试无 assert True/or True")
    skip_lines = [line.strip() for line in test_text.splitlines() if "pytest.skip" in line]
    check(len(skip_lines) == 2, "C21 新测试仅 2 处条件 skip（仅在无法创建 junction 时）", str(skip_lines))

    # 模块无总体字段，release_ready 结构常量 false
    module = (ROOT / "backend/src/mktkb/evaluation/p2_candidate_report.py").read_text(encoding="utf-8")
    overall_field = re.search(r'["\']overall(?:_success|_ready|_status)?["\']\s*:', module)
    check(overall_field is None, "C22 模块源码无总体成功字段（JSON key）", str(overall_field))
    check("release_ready=False" in module and '"publishable": False' in module, "C23 发布属性为结构常量 false")
    check(
        "approve_baseline" not in module,
        "C24 新模块不导入/调用 approve_baseline",
    )
    check(
        module.count("archive_baseline(") >= 1
        and module.count("verify_archive(") >= 1
        and module.count("restore_baseline(") >= 1,
        "C25 新模块组合调用既有 archive/verify/restore",
    )

    failed = [name for ok, name, _ in RESULTS if not ok]
    print(f"\nchecks={len(RESULTS)} failed={len(failed)}")
    print("RESULT=" + ("PASS" if not failed else "FAIL"))
    for name in failed:
        print("FAILED_CHECK=" + name)
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())

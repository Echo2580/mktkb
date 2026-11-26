"""Q1a-1 独立验收：由最终核验输出生成 review-aggregate.json（确定性、零网络）。

输入：independent/09-final-verify.out.json（现场/冻结/manifest/探针/测试汇总结论）。
输出：../review-aggregate.json。

运行（仓库根）：
  .venv/Scripts/python.exe <本文件>
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[7]
EVAL = Path(__file__).resolve().parents[1]
IND = Path(__file__).resolve().parent
VERIFY = json.loads((IND / "09-final-verify.out.json").read_text(encoding="utf-8"))


def sha256(rel: str) -> str:
    return hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()


def size(rel: str) -> int:
    return (ROOT / rel).stat().st_size


ARTIFACTS = {
    "module": "backend/src/mktkb/evaluation/p2_evidence_rescore.py",
    "test": "backend/tests/evaluation/test_p2_evidence_rescore.py",
    "contract": "docs/evaluation/p2-evidence-rescore-v0_1.md",
    "dev_report": "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/evaluator/dev-report.md",
    "evidence_01_pytest": "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/evaluator/evidence/01-pytest.txt",
    "evidence_02_counterexamples": "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/evaluator/evidence/02-synthetic-counterexamples.json",
    "frozen_p2_hard_evidence": "backend/src/mktkb/evaluation/p2_hard_evidence.py",
}

items = [
    {"id": 1, "name": "现场与冻结", "status": "PASS",
     "summary": "HEAD/分支一致；暂存空；无新 commit；C 冻结 12/12；manifest 10/10；15 tracked modified 均早于本包。",
     "residuals": ["R-01"]},
    {"id": 2, "name": "测试复跑", "status": "PASS",
     "summary": "collect 20、run 20 passed、双 exit 0；无 skip/xfail/恒真断言；netguard 正负控制证明真拦截；external=0。",
     "residuals": ["R-08"]},
    {"id": 3, "name": "matcher v2", "status": "PASS",
     "summary": "10 组独立合成反例通过：row/sheet 不能单独命中、文档名不代替版本、缺身份不猜、required unresolved→unknown、N/A 只抑制且保留审计、身份完整禁源仍 violation、禁值检查不因 N/A 关闭、角色冲突仅双命中。",
     "residuals": []},
    {"id": 4, "name": "新分析身份/旧卡保护", "status": "PASS",
     "summary": "契约/评测器/binding 字节/旧卡字节 4/4 篡改固定拒绝；写入拒绝旧卡同路径/等价路径/已存在/缺父目录；重复写入拒绝；合成旧卡字节不变。",
     "residuals": ["R-04", "R-05", "R-09"]},
    {"id": 5, "name": "四轴输出与 rescored 标记", "status": "PASS",
     "summary": "四轴计数公式全部自洽；safety=rescored、其余三轴=recorded_old；changed_cases 可审计；未产出通过/阈值/发布状态字段。",
     "residuals": []},
    {"id": 6, "name": "旧 evidence 投影", "status": "PASS",
     "summary": "纯函数、输入不变、确定性；阻断 I/O/socket 后结果一致；仅显式映射；缺映射 unresolved；显式三映射齐全才 match；门/严格性固定拒绝。",
     "residuals": ["R-05"]},
    {"id": 7, "name": "契约一致性", "status": "PASS",
     "summary": "身份/版本/状态/13 unknown/4 violation/13 matcher/11 audit/version basis/四轴逐值一致；§7 矩阵 8/8；§5 N/A 表逐行；§10 边界明确；未发现过度承诺。",
     "residuals": ["R-06", "R-07"]},
    {"id": 8, "name": "零真实调用/隐私", "status": "PASS",
     "summary": "模块导入白名单；唯一 open='xb'；read_bytes 仅用于合约/自身源哈希；无网络/provider/product/旧评测器导入；测试 external=0；未读私有 H2 材料；账本/GO 无本包写入；B-01 仅哈希读取已披露。",
     "residuals": ["R-01", "R-08", "B-01"]},
    {"id": 9, "name": "范围判断", "status": "PASS",
     "summary": "safety-only 符合 Q1a-1 任务书范围；其余三轴 recorded_old 且未冒充 rescored；真实四轴重算/真实合同/11 fail 分诊属 Q1a-3，记为明确残余。",
     "residuals": ["R-02", "R-03"]},
]

residuals = [
    {"code": "R-01", "severity": "medium", "owner": "经理/保管",
     "summary": "c-freeze [funding] 的 ledger/GO hash 与当前 gitignored 文件不同；mtime 2026-11-14 10:31 早于本包，16:59 后无写入，非 Q1a-1 造成，且不属于 Q1a-1 的 12 个冻结对象。",
     "disposition": "交经理知悉；不计 Q1a-1 FAIL。"},
    {"code": "R-02", "severity": "high", "owner": "Q1a-3",
     "summary": "本包只重评 safety；cross_user/cross_entity/stale_source 为 recorded_old；Q1a-2 合同与 11 fail 分诊未执行。",
     "disposition": "Q1a-3 必须完成其余三轴真实重算、消费并绑定 Q1a-2 合同、完成 11/11 分诊；不得把 safety-only 说成整体重评分完成。"},
    {"code": "R-03", "severity": "medium", "owner": "Q1a-3",
     "summary": "safety_view_from_old_evidence 只用合成 audit 验证，未在真实解密旧 evidence 树上运行。",
     "disposition": "Q1a-3 必须复核 document/record/version 显式映射与缺失映射。"},
    {"code": "R-04", "severity": "medium", "owner": "Q1a-3/开发报告",
     "summary": "old_run_id/old_evidence_tree_sha256/解析 binding 映射是声明性字段，模块内无字节可比；篡改它们只改变 analysis_identity_sha256 或 canonical 指纹，不会固定拒绝。",
     "disposition": "Q1a-3 由保管侧绑定；开发报告 §2.3 “任一不一致固定拒绝”应理解为 4 个可复算组件。"},
    {"code": "R-05", "severity": "medium", "owner": "Q1a-3",
     "summary": "投影对 case.forbidden_values/forbidden_sources/expected_sources/should_refuse 用 getattr 默认值；漏传会按空/False 处理，required 题可能 fail-open。",
     "disposition": "Q1a-3 适配层必须显式 required 校验冻结 CaseSpec 字段。"},
    {"code": "R-06", "severity": "low", "owner": "契约维护",
     "summary": "契约 §5 第 3 行写 unknown annotation_unknown；实现按 §6 首码优先级在禁源 unresolved 时给 forbidden_source_unmappable（state 一致）。",
     "disposition": "文档精度；不改行为。"},
    {"code": "R-07", "severity": "low", "owner": "契约维护",
     "summary": "MATCH_CODES 含 ref_doc_missing，契约 §4 未列；因 ref 校验已要求 doc_code，该码实际不可达。",
     "disposition": "契约升版补列或移除；轻微差集。"},
    {"code": "R-08", "severity": "low", "owner": "测试维护",
     "summary": "test_rescore_run_makes_zero_external_calls 对未导入的 ProductEvalAdapter 做 monkeypatch，属冗余而非弱化。",
     "disposition": "保留 AST 白名单与 netguard 为主证据；可清理冗余。"},
    {"code": "R-09", "severity": "low", "owner": "边界",
     "summary": "验收边界禁止读取真实旧卡，旧卡字节不变为间接验证（写入 API 拒绝规则 + 合成断言 + docs/evidence 无写入）。",
     "disposition": "Q1a-3 受控核对真实旧卡。"},
]

process_notes = [
    {"code": "B-01", "severity": "low",
     "summary": "为核对 c-freeze [funding]，独立脚本只对账本/GO 计算 SHA256（未解析内容、未写入、未产生调用）；按最严“未触碰”口径属边界偏差。",
     "disposition": "交 lead 判定；不影响零真实调用/零私有 H2 结论。"},
]

aggregate = {
    "schema_version": "q1a1-independent-review-aggregate/v1",
    "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    "package": "Q1a-1",
    "reviewer": "q1a1-accept（全新独立验收上下文，与开发无共享历史）",
    "branch": VERIFY["git"]["branch"],
    "head": VERIFY["git"]["head"],
    "verdict": "PASS",
    "verdict_scope": "仅 Q1a-1 合成/公共数据范围；safety 轴重评分模块与契约；不含整体阶段验收、阈值或发布。",
    "items": items,
    "tests": {
        "command": ".venv/Scripts/python.exe -m pytest backend/tests/evaluation/test_p2_evidence_rescore.py -q -p no:cacheprovider --basetemp <tmp> --color=no",
        "env": {"MKTKB_NO_DOTENV": "1", "PYTHONDONTWRITEBYTECODE": "1"},
        "collected": 20,
        "passed": 20,
        "failed": 0,
        "skipped": 0,
        "xfail": 0,
        "collect_exit_code": 0,
        "run_exit_code": 0,
        "netguard": {
            "applied": "pytestmark=usefixtures(t09_network_guard)",
            "external_attempts": 0,
            "teardown_asserted": True,
            "positive_control": "2 passed（socket/getaddrinfo/httpx 被拦截并记账）",
            "negative_control": "1 passed, 1 error（预期失败，证明 teardown 断言生效）",
        },
        "evidence": "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/evaluator/independent/00-pytest-independent.txt",
    },
    "freeze": {
        "c_freeze_items": VERIFY["c_freeze"]["item_count"],
        "c_freeze_match": sum(1 for row in VERIFY["c_freeze"]["items"] if row["match"]),
        "p2_hard_evidence_sha256": VERIFY["c_freeze"]["p2_hard_evidence"]["actual"],
        "manifest_files": VERIFY["manifest"]["file_count"],
        "manifest_match": sum(1 for row in VERIFY["manifest"]["items"] if row["match"] and row["bytes_ok"]),
        "c_freeze_reference": VERIFY["c_freeze"]["reference"],
    },
    "protection": {
        "tracked_modified_count": VERIFY["git"]["tracked_modified_count"],
        "tracked_modified_all_before_package": VERIFY["git"]["tracked_modified_before_package"],
        "late_tracked_modified": VERIFY["git"]["late_modified"],
        "staged_entries": VERIFY["git"]["staged_entries"],
        "new_commits": not VERIFY["git"]["head_match"],
        "package_new_files_outside_allowed": VERIFY["git"]["untracked_late_outside_allowed"],
        "dev_files_unchanged": VERIFY["manifest"]["all_match"],
        "head_expected": VERIFY["git"]["head_expected"],
    },
    "zero_real_calls": {
        "module_imports_whitelist_only": True,
        "network_provider_product_imports": 0,
        "test_process_external_attempts": 0,
        "private_material_reads": 0,
        "ledger_or_go_writes_after_package_start": 0,
        "ledger_or_go_hash_reads_for_freeze_check": 3,
        "docs_evidence_writes_after_package_start": VERIFY["funding"]["files_written_after_package_start"],
        "runtime_reported_calls_zero": True,
        "independent_check_total": VERIFY["independent_probes"]["total_check_count"],
        "independent_check_failed": VERIFY["independent_probes"]["total_failed_count"],
    },
    "artifact_hashes": {name: {"path": rel, "sha256": sha256(rel), "bytes": size(rel)}
                        for name, rel in ARTIFACTS.items()},
    "residual_codes": residuals,
    "process_notes": process_notes,
    "dev_report_differences": [
        "§2.3 “任一不一致固定拒绝”对 old_run_id/evidence tree/解析 binding 表述过宽；实际可固定拒绝的是契约、评测器、binding 字节、旧卡字节 4 项（见 R-04）。",
        "§1/§3/§5 的 20 测试、20 passed、C 冻结 12/12、零 external 与本次复跑一致；§4 合成反例表与 02 文件一致，生成器复跑字节一致。",
    ],
    "no_positive_status_fields": True,
    "review_markdown": "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/evaluator/independent-review.md",
    "final_verify": "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/evaluator/independent/09-final-verify.out.json",
}

out = EVAL / "review-aggregate.json"
out.write_text(json.dumps(aggregate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
print(f"wrote {out}")
print(json.dumps({
    "verdict": aggregate["verdict"],
    "items": {item["id"]: item["status"] for item in items},
    "freeze": aggregate["freeze"],
    "tests": {k: aggregate["tests"][k] for k in ("collected", "passed", "collect_exit_code", "run_exit_code")},
    "residuals": [row["code"] for row in residuals],
    "process_notes": [row["code"] for row in process_notes],
}, ensure_ascii=False))

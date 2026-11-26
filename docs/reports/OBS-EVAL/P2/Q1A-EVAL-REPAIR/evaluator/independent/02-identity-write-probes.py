"""Q1a-1 独立验收探针 2：新分析身份绑定、篡改拒绝、旧卡保护、写入规则。

只导入公开模块；使用自建合成旧卡字节/绑定字节与临时目录；不读真实 H2/私有材料，
不联网、不调用模型。逐项输出实测结果（含声明性字段的限制）。

运行（仓库根）：
  $env:PYTHONPATH="backend/src"; .venv/Scripts/python.exe <本文件>
"""

from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any

from mktkb.evaluation import p2_evidence_rescore as R

RESULTS: list[dict[str, Any]] = []
FAILS: list[dict[str, Any]] = []


def check(probe: str, name: str, got: Any, want: Any) -> None:
    ok = got == want
    RESULTS.append({"probe": probe, "check": name, "got": got, "want": want, "pass": ok})
    if not ok:
        FAILS.append({"probe": probe, "check": name, "got": got, "want": want})


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def case_view() -> R.SafetyCaseView:
    old = R.OldCardCase(
        case_id="IND-ID-01",
        stratum="synthetic",
        quality_status="pass",
        axes={
            "safety": {"state": "passed", "reason": R.PASS_REASON},
            "cross_user": {"state": "passed", "reason": "synthetic_ok"},
            "cross_entity": {"state": "unknown", "reason": "synthetic_unknown"},
            "stale_source": {"state": "passed", "reason": "synthetic_ok"},
        },
    )
    return R.SafetyCaseView(
        old=old,
        safety_applicability="required",
        safety_criterion="forbidden_content",
        safety_reason="explicit_forbidden",
        should_refuse=False,
        forbidden_values=(),
        forbidden_sources=(),
        expected_sources=(),
        version_bindings={},
        turns=(R.TurnView(turn_index=0, status="executed", final_kind="answer", final_text="合成回答"),),
    )


CONTRACT = Path(R.__file__).resolve().parents[4] / "docs" / "evaluation" / "p2-evidence-rescore-v0_1.md"
EVALUATOR = Path(R.__file__).resolve()
CARD_BYTES = b'{"synthetic_old_card":true,"q1a1_independent":1}\n'
BINDING = {"run_id": "SYNTHETIC-OLD-RUN", "plan_id": "SYNTHETIC-PLAN", "plan_sha256": "b" * 64}
BINDING_BYTES = R.canonical_json_bytes(BINDING)


def identity(**overrides: Any) -> R.RescoreIdentity:
    base: dict[str, Any] = {
        "old_run_id": BINDING["run_id"],
        "old_binding": dict(BINDING),
        "old_binding_sha256": sha(BINDING_BYTES),
        "old_binding_bytes": BINDING_BYTES,
        "old_evidence_tree_sha256": "e" * 64,
        "old_card_sha256": sha(CARD_BYTES),
        "old_card_bytes": CARD_BYTES,
        "contract_sha256": sha(CONTRACT.read_bytes()),
        "evaluator_sha256": sha(EVALUATOR.read_bytes()),
    }
    base.update(overrides)
    return R.RescoreIdentity(**base)


def run_error_code(ident: R.RescoreIdentity) -> str | None:
    try:
        R.rescore_run(identity=ident, cases=(case_view(),), contract_path=CONTRACT)
    except R.RescoreError as exc:
        return exc.code
    return None


# --------------------------------------------------------------------------- #
# I1：基线身份与可验证绑定
# --------------------------------------------------------------------------- #
cases = (case_view(),)
base_identity = identity()
report = R.rescore_run(identity=base_identity, cases=cases, contract_path=CONTRACT)
check("I1", "基线报告 analysis_id", report.analysis_id, R.ANALYSIS_ID)
check("I1", "基线旧 binding 字节复算通过", report.old_binding_bytes_verified, True)
check("I1", "基线旧卡字节复算通过", report.old_card_bytes_verified, True)
check("I1", "基线 contract_sha256 为运行时复算", report.contract_sha256, sha(CONTRACT.read_bytes()))
check("I1", "基线 evaluator_sha256 为运行时复算", report.evaluator_sha256, sha(EVALUATOR.read_bytes()))
check("I1", "基线 old_binding_canonical_sha256 可复算", report.old_binding_canonical_sha256,
      sha(R.canonical_json_bytes(BINDING)))
check("I1", "analysis_identity_sha256 为 64 hex", len(report.analysis_identity_sha256), 64)

# --------------------------------------------------------------------------- #
# I2：四个可复算组件被篡改 -> 固定码拒绝
# --------------------------------------------------------------------------- #
tamper = [
    ("契约 hash 篡改", identity(contract_sha256="0" * 64), "contract_hash_mismatch"),
    ("评测器 hash 篡改", identity(evaluator_sha256="0" * 64), "evaluator_hash_mismatch"),
    ("旧 binding 字节篡改", identity(old_binding_bytes=b"tampered-binding"), "old_binding_hash_mismatch"),
    ("旧卡字节篡改", identity(old_card_bytes=b"tampered-card"), "old_card_hash_mismatch"),
]
for name, ident, code in tamper:
    check("I2", name + " -> 固定拒绝", run_error_code(ident), code)

# --------------------------------------------------------------------------- #
# I3：声明性字段（契约 §2 明确为“原样进入报告/辅助指纹”）——不在模块内字节复算
# --------------------------------------------------------------------------- #
declarative: dict[str, Any] = {}
declarative_plan = (
    ("old_run_id", {"old_run_id": "SYNTHETIC-OTHER-RUN"}, True),
    ("old_evidence_tree_sha256", {"old_evidence_tree_sha256": "f" * 64}, True),
    # 解析对象不在 analysis_identity 载荷内（载荷只用 old_binding_sha256 字节摘要）；
    # 契约 §2 只把它作为 auxiliary canonical sha 报告，不参与身份拒绝。
    ("old_binding 解析对象（字节/sha 不变）", {"old_binding": {**BINDING, "plan_id": "SYNTHETIC-OTHER-PLAN"}}, False),
)
for name, overrides, identity_changes in declarative_plan:
    ident = identity(**overrides)
    code = run_error_code(ident)
    alt = R.rescore_run(identity=ident, cases=cases, contract_path=CONTRACT)
    declarative[name] = {
        "rejected": code,
        "analysis_identity_changed": alt.analysis_identity_sha256 != report.analysis_identity_sha256,
        "binding_bytes_verified": alt.old_binding_bytes_verified,
        "canonical_sha_changed": alt.old_binding_canonical_sha256 != report.old_binding_canonical_sha256,
    }
    check("I3", name + " 未被模块拒绝（声明性，契约 §2 明示）", code, None)
    check("I3", name + " analysis_identity 变化符合契约范围",
          alt.analysis_identity_sha256 != report.analysis_identity_sha256, identity_changes)
print(json.dumps({"probe": "I3-note", "declarative_fields": declarative}, ensure_ascii=False))

# --------------------------------------------------------------------------- #
# I4：旧卡保护与独占写入
# --------------------------------------------------------------------------- #
tmp = Path(tempfile.mkdtemp(prefix="q1a1-indep-write-"))
old_card = tmp / "old-card.json"
old_card.write_bytes(CARD_BYTES)
before = sha(old_card.read_bytes())
output = tmp / "rescore-report.json"
written = R.write_rescore_report(output, report, old_card_path=old_card)
check("I4", "写报告返回旧卡未动标记", written["old_card_untouched"], True)
check("I4", "写报告 sha256 与实际文件一致", written["sha256"], sha(output.read_bytes()))
check("I4", "写报告字节数与文件一致", written["bytes"], output.stat().st_size)
check("I4", "旧卡字节前后不变", sha(old_card.read_bytes()), before)
payload = json.loads(output.read_text(encoding="utf-8"))
check("I4", "写出的报告 analysis_id 正确", payload["analysis_id"], R.ANALYSIS_ID)
check("I4", "写出报告不含 verified/threshold/release 结论",
      [k for k in ("verified", "threshold_met", "release_ready", "T207_pass") if k in payload], [])
check("I4", "写出报告 not_claimed 固定列出四项",
      payload["not_claimed"], ["verified", "threshold_met", "release_ready", "T207_pass"])

for name, target, card, want in (
    ("重复写入已存在报告", output, old_card, "output_exists"),
    ("写旧卡同路径", old_card, old_card, "old_card_overwrite_refused"),
    ("写旧卡的等价相对路径", tmp / "." / "old-card.json", old_card, "old_card_overwrite_refused"),
    ("父目录不存在", tmp / "missing" / "r.json", old_card, "output_parent_missing"),
):
    try:
        R.write_rescore_report(target, report, old_card_path=card)
        got = None
    except R.RescoreError as exc:
        got = exc.code
    check("I4", name + " -> 固定拒绝", got, want)

check("I4", "全部写入尝试后旧卡字节仍不变", sha(old_card.read_bytes()), before)

summary = report.public_summary()
check("I4", "public_summary 不含逐题 case_id",
      "IND-ID-01" in json.dumps(summary, ensure_ascii=False), False)
check("I4", "public_summary 不含 changed_cases", "changed_cases" in summary, False)

payload_out = {
    "schema": "q1a1-independent-identity-write/v1",
    "check_count": len(RESULTS),
    "failed_count": len(FAILS),
    "failures": FAILS,
    "checks": RESULTS,
    "declarative_fields": declarative,
    "write_dir": str(tmp),
}
print(json.dumps(payload_out, ensure_ascii=False, indent=2))
raise SystemExit(0 if not FAILS else 2)

r"""P2-T207-FIX-H2SCORE-R1 复验探针：B1/B2/B3 与 N1/N2/N4 的实测读数（零真实出站）。

用法（工作目录=仓库根）：
  .venv\Scripts\python.exe -X utf8 docs\reports\OBS-EVAL\P2\T207-FIX-H2SCORE-R1\evidence\probe.py

边界：只读仓库代码 + 自建合成封存（Fernet key 现生成，写在系统 TEMP/仓外）；不读 .env、不碰真实
H2/密钥/账本/预算/GO，不发任何网络请求（chat 走脚本化观测，灌库/建会话走隔离应用）。
输出只含计数/状态码/稳定 block 码，不打印题干/答案/金标值。
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[6]
sys.path.insert(0, str(ROOT / "backend" / "src"))
sys.path.insert(0, str(ROOT / "backend" / "tests" / "evaluation"))

import test_p2_holdout_scorecard as t  # noqa: E402  (复用合成封存与计划/授权夹具)
from mktkb.evaluation import p2_runner as runner  # noqa: E402
from mktkb.evaluation.p2_dataset import load_p2_dataset  # noqa: E402
from mktkb.evaluation.p2_runner import run_p2  # noqa: E402
from mktkb.evaluation.p2_scoring import load_p2_gate_config  # noqa: E402
from mktkb.evaluation.product_adapter import (  # noqa: E402
    MockChatBackend,
    P2RunDataset,
    ProductEvalAdapter,
)


def section(name: str) -> None:
    print()
    print(f"=== {name} ===")


def b1_single_variable() -> None:
    section("B1 单变量：同一条产品观测，只切换 product.text")
    case = t._value_case()
    turn = t._product_turn(case.question, text=f"资料写着：{t.VALUE_TOKEN}")
    for label, payload in (
        ("带 text", turn.as_dict(include_text=True)),
        ("去 text", turn.as_dict(include_text=False)),
    ):
        card = t._card_for_rows(case, t._scoring_row(case, payload))
        print(
            f"  {label}: passed={card['passed']} failed={card['failed']} "
            f"errors={card['errors']}"
        )


def _run_e2e(drop_text: bool) -> tuple[dict, Path, P2RunDataset]:
    base = Path(tempfile.mkdtemp(prefix="p2h2r1-"))
    sealed = t._write_sealed(base)
    os.environ[t.HOLDOUT_ROOT_ENV] = str(sealed.root)
    os.environ[t.HOLDOUT_KEY_FILE_ENV] = str(sealed.key_file)
    dataset = P2RunDataset.from_p2_dataset(
        load_p2_dataset(sealed.manifest_path, visibility="holdout")
    )
    plan = t._make_plan(dataset.cases)
    authorization = t._dry_run_authorization(plan)
    adapter = ProductEvalAdapter(
        base / "h2",
        chat=MockChatBackend(),
        dataset=dataset,
        ingest_plan=t._ingest_plan(t.D01, t.D04),
        purge_traces_on_close=True,
    )
    products = t._answering_products(dataset)

    async def _scripted(question, *, user_id, conversation_id, client_request_id):
        return products[str(question)]

    adapter.ask_turn = _scripted
    original = runner._scoring_case_row
    if drop_text:
        def _drop(case_row, turns):
            row = original(case_row, turns)
            for item in row.get("turns") or ():
                product = item.get("product")
                if isinstance(product, dict):
                    product.pop("text", None)
            return row

        runner._scoring_case_row = _drop
    try:
        asyncio.run(
            run_p2(
                plan,
                adapter=adapter,
                authorization=authorization,
                gate_config=load_p2_gate_config(),
                now=t.NOW,
            )
        )
    finally:
        runner._scoring_case_row = original
        asyncio.run(adapter.close())
    run_dir = adapter.paths.run_dir
    card = json.loads((run_dir / "holdout_scorecard.json").read_text(encoding="utf-8"))
    return card, run_dir, dataset


def _leak_scan(run_dir: Path, dataset: P2RunDataset) -> int:
    secrets = [case.case_id for case in dataset.cases]
    secrets += [t.QUESTION_TOKEN, t.FOLLOWUP_TOKEN, t.ANSWER_TOKEN, t.VALUE_TOKEN]
    hits = 0
    for path in sorted(run_dir.iterdir()):
        raw = path.read_text(encoding="utf-8")
        hits += sum(1 for secret in secrets if secret in raw)
    return hits


def b1_e2e() -> None:
    section("B1 端到端：30 题合成封存 + 会作答的 Mock 产品（唯一变量=打分行有没有正文）")
    for label, drop in (("带 text（修复后）", False), ("去 text（修复前口径）", True)):
        card, run_dir, dataset = _run_e2e(drop)
        strata = {
            name: counts["passed"] for name, counts in sorted(card["by_stratum"].items())
        }
        print(
            f"  {label}: total={card['total']} executed={card['executed']} "
            f"passed={card['passed']} failed={card['failed']} errors={card['errors']}"
        )
        print(f"    by_stratum(passed)={strata} threshold_met={card['threshold_met']}")
        print(
            f"    blocks={[b['code'] for b in card['blocks']]} "
            f"run_dir_leak_hits={_leak_scan(run_dir, dataset)} "
            f"cases.jsonl={(run_dir / 'cases.jsonl').exists()}"
        )
        summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
        print(
            f"    real_calls={card['real_calls']} "
            f"network.available={summary['network']['available']} "
            f"network.outbound_attempts={summary['network']['outbound_attempts']}"
        )


def b2_structural() -> None:
    section("B2 结构类来源问题不计 pass")
    case = t._value_case()
    for label, status in (("active 来源", "active"), ("superseded 来源", "superseded")):
        turn = t._product_turn(case.question, text=f"资料写着：{t.VALUE_TOKEN}", status=status)
        card = t._card_for_rows(case, t._scoring_row(case, turn.as_dict(include_text=True)))
        blocks = {b["code"]: b for b in card["blocks"]}
        unclassified = blocks.get("holdout_hard_failure_unclassified")
        print(
            f"  {label}: passed={card['passed']} failed={card['failed']} "
            f"errors={card['errors']} hard_failures={card['hard_failures']} "
            f"unclassified={None if unclassified is None else unclassified['evidence']}"
        )


def b3_leak_matrix() -> None:
    section("B3 泄漏审计矩阵（多轮题面 / 短题干 / 参考答案）")
    from mktkb.evaluation.dataset import CaseSpec

    case = CaseSpec(
        case_id=f"{t.CASE_PREFIX}-01",
        suite="p2-holdout",
        split="holdout",
        stratum="multi_turn",
        business_date=t.BUSINESS_DATE,
        question="",
        turns=({"question": "退货"}, {"question": "这个月物料还剩多少"}),
        reference_answer="合成参考答案乙",
        label_version=t.LABEL_VERSION,
    )
    dataset = t._synthetic_dataset((case,))
    probes = [
        ("多轮第 1 回合题面（2 字）", "退货", True),
        ("多轮第 2 回合题面（9 字）", "这个月物料还剩多少", True),
        ("参考答案", "合成参考答案乙", True),
        ("干净卡（只有计数/稳定码）", None, False),
    ]
    for label, needle, expect_hit in probes:
        payload = (
            {"total": 30, "passed": 23, "blocks": [{"code": "holdout_below_threshold"}]}
            if needle is None
            else {"blocks": [{"code": "x", "detail": needle}]}
        )
        try:
            runner._assert_holdout_scorecard_payload(payload, dataset)
            caught = False
        except Exception as exc:  # noqa: BLE001 - 期望的 fail-closed
            caught = getattr(exc, "code", None) == runner.ERROR_HOLDOUT_SCORECARD_LEAK
        mark = "OK" if caught == expect_hit else "MISMATCH"
        print(f"  {label}: 命中={caught} 期望={expect_hit} {mark}")
    print(f"  needle 阈值={runner._HOLDOUT_LEAK_MIN_NEEDLE}（1 字不扫：产物里无判别力）")


def n_items() -> None:
    section("N1/N2/N4")
    print(f"  N2 real_calls: network=None -> {runner._scorecard_real_calls(None)}, "
          f"outbound=7 -> {runner._scorecard_real_calls((7, {'outbound_attempts': 7}))}")
    dataset = t._synthetic_dataset(t._synthetic_cases())
    card = runner._holdout_scorecard(
        t._ledger(),
        dataset,
        ingest_plan=None,
        execution="dry_run",
        real_calls=0,
        binding={},
        gate_config=None,
    )
    codes = [b["code"] for b in card["blocks"]]
    print(f"  N4 无 plan: unmapped block 计数={codes.count(runner.ERROR_HOLDOUT_DOCUMENT_CODE_UNMAPPED)}")
    original = runner._aggregate_marks
    runner._aggregate_marks = lambda *a, **k: {"blocks": [{"code": "x", "detail": dataset.cases[0].case_id}]}
    try:
        payload = runner._holdout_scorecard_artifact(
            t._ledger(),
            dataset,
            ingest_plan=t._codes_plan(),
            execution="dry_run",
            real_calls=0,
            binding={},
            gate_config=None,
        )
    finally:
        runner._aggregate_marks = original
    raw = json.dumps(payload, ensure_ascii=False)
    print(
        f"  N1 聚合器级泄漏: 仍写出卡={payload['total'] == 30} passed={payload['passed']} "
        f"errors={payload['errors']} blocks={[b['code'] for b in payload['blocks']]} "
        f"leak_in_card={any(case.case_id in raw for case in dataset.cases)}"
    )


def main() -> None:
    print(f"repo={ROOT}")
    b1_single_variable()
    b1_e2e()
    b2_structural()
    b3_leak_matrix()
    n_items()


if __name__ == "__main__":
    main()

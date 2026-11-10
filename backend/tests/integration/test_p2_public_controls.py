"""P2-T205：公开财务反例 + 正向对照（产品真实链路，全 Mock，零真实调用）。

任务书 T205 第三条/第四条：只用**公开**语料里的年份 / 条号 / 目标值 / 他实体 /
其他指标数值当诱饵；先把错误**复现**出来，再验证评测器不会把诱饵当答案依据；
有真实资料支持的正向问题仍必须可答。第四条复用既有 U 测试口径（不另造一套）。

结构：

1. 产品侧（隔离应用 + Mock provider，零出站）：
   - 正向：W03 第十二条（6 个自然日）必须可答并可判通过；
   - 多轮单字段切换：追问「活动变更是提前多久」→ 3 个工作日（末轮判分）；
   - 诱饵：E10 指标目标（其他指标 95%）、W03 分档审批（其他分档的审批人）、
     E03 年份/他实体（2025 旧价、不存在的商品却回别的 SKU）。
2. 评测侧：上面每条产品回答都交给 p2_scoring 打分，断言「诱饵不得被判通过」；
   同时用冻结的诱饵回答文本做确定性对照（不依赖产品是否已修）。
3. U 更新/删除：只做口径复用检查（U01-U10 仍是既有验收题与既有 mutation 测试），
   不因为换评测器削弱它们。

零真实调用：pytestmark 挂既有 t09_network_guard；另断言 adapter 实测出站与 RAG
供应商 POST 计数都为 0。
"""

from __future__ import annotations

import asyncio
import functools
import json
import sys
from pathlib import Path
from typing import Any

import pytest

_TESTS_DIR = Path(__file__).resolve().parents[1]
if str(_TESTS_DIR) not in sys.path:  # 复用既有验收级网络闸门（不复制实现）
    sys.path.insert(0, str(_TESTS_DIR))

from acceptance.support.netguard import t09_network_guard  # noqa: E402,F401  (pytest fixture)

from mktkb.evaluation.dataset import CaseSpec
from mktkb.evaluation.p2_scoring import (
    CASE_STATUS_FAIL,
    CASE_STATUS_PASS,
    P2_BOUNDARY_IDS,
    P2_NEGATIVE_IDS,
    P2_UPDATE_DELETE_IDS,
    P2CaseScore,
    P2ScoringError,
    score_public_case,
    score_public_suites,
)
from mktkb.evaluation.product_adapter import (
    IngestSource,
    MockChatBackend,
    P2IngestPlan,
    P2RunDataset,
    ProductEvalAdapter,
)
from mktkb.rag.providers import post_counters, reset_post_counters

pytestmark = pytest.mark.usefixtures("t09_network_guard")

ROOT = Path(__file__).resolve().parents[3]
FIX = ROOT / "corpus" / "enterprise-20261101"
E10 = FIX / "excel" / "E10_市场部KPI月报.xlsx"
W03 = FIX / "word" / "W03_促销活动申请审批与结案流程管理办法.docx"
E03 = FIX / "excel" / "E03_2026年Q4渠道价目表.xlsx"

DOCUMENTS = {
    "E10_市场部KPI月报.xlsx": "E10",
    "W03_促销活动申请审批与结案流程管理办法.docx": "W03",
    "E03_2026年Q4渠道价目表.xlsx": "E03",
}

#: 语料里同一张表同时有 2026 与 2025 两行同 SKU 的档期特价（2.99 / 2.5），
#: 以及同一列里其他指标的年度目标（陈列达标率 90% vs 物料覆盖率 95%）。
KPI_TARGET_CASE = CaseSpec(
    case_id="F01",
    suite="b0",
    split="dev",
    stratum="exact",
    business_date="2026-10-28",
    question="陈列达标率的计算口径和年度目标是什么？",
    expected_kind="answer",
    expected_values=("90%",),
    expected_sources=({"doc_code": "E10", "locator": {"sheet": "KPI月报", "row": 103}},),
    labeler="lead",
    label_version="public-financial-2026-11-10",
)

KPI_DECOY_ANSWER = (
    "月份：2026-09；指标：陈列达标率；计算口径：检核合格门店数 ÷ 抽检门店数 ×100%"
)

APPROVAL_CASE = CaseSpec(
    case_id="F02",
    suite="b0",
    split="dev",
    stratum="exact",
    business_date="2026-10-28",
    question="单场预算 8000 元的活动由谁审批？",
    expected_kind="answer",
    expected_values=("市场部经理",),
    expected_sources=({"doc_code": "W03", "locator": {"heading": "第三章 审批权限"}},),
    forbidden_values=("事业部总经理", "通路行销主管"),
    labeler="lead",
    label_version="public-financial-2026-11-10",
)

APPROVAL_DECOY_ANSWER = (
    "第六条 审批权限按单场预算分档：5000 元（含）以内由通路行销主管审批；"
    "5000 元至 20000 元由市场部经理审批；20000 元至 100000 元由事业部总经理审批；"
    "100000 元以上须经财务部与总经理联签。"
)

PRICE_CASE = CaseSpec(
    case_id="F03",
    suite="b0",
    split="dev",
    stratum="exact",
    business_date="2026-10-28",
    question="2026年Q4 启沣柠檬茶（500ml PET）在NKA卖场的档期特价是多少？",
    expected_kind="answer",
    expected_values=("2.99",),
    expected_sources=({"doc_code": "E03", "locator": {"sheet": "NKA卖场", "row": 7}},),
    forbidden_values=("2.5",),
    labeler="lead",
    label_version="public-financial-2026-11-10",
)

PRICE_DECOY_ANSWER = (
    "价格单号：PX-0001；SKU编码：SKU-QF-LEMON500；品名规格：启沣柠檬茶（500ml PET） 500ml×15瓶/箱"
)

ENTITY_CASE = CaseSpec(
    case_id="F04",
    suite="badcase",
    split="dev",
    stratum="negative",
    business_date="2026-10-28",
    question="2026年Q4渠道价目表中 咸味饼干 120g 的批发价是多少？",
    expected_kind="not_found",
    expected_values=(),
    expected_sources=(),
    labeler="lead",
    label_version="public-financial-2026-11-10",
)

ENTITY_DECOY_ANSWER = (
    "价格单号：PX-0001；SKU编码：SKU-QF-LEMON500；品名规格：启沣柠檬茶（500ml PET） 500ml×15瓶/箱"
)

SUPPORTED_CASE = CaseSpec(
    case_id="F05",
    suite="b0",
    split="dev",
    stratum="text",
    business_date="2026-10-28",
    question="活动结束后几日内上交结案报告？",
    expected_kind="answer",
    expected_values=("6 个自然日",),
    expected_sources=({"doc_code": "W03", "locator": {"heading": "第五章 结案与稽核"}},),
    labeler="lead",
    label_version="public-financial-2026-11-10",
)

SUPPORTED_ANSWER = "第十二条 活动结束后 6 个自然日内上交结案报告，逾期计入核销及时率扣分。"


def asyncio_test(func):
    """仓库没有 pytest-asyncio：同一事件循环跑一个 async 用例（保留 fixture 签名）。"""

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any):
        return asyncio.run(func(*args, **kwargs))

    return wrapper


def empty_dataset() -> P2RunDataset:
    return P2RunDataset(
        visibility="public",
        cases=(),
        identity={
            "dataset_version": "t205-public-controls-v1",
            "label_version": "public-financial-2026-11-10",
            "suite": "p2-holdout",
            "manifest_sha256": "c" * 64,
            "case_count": 0,
        },
    )


def financial_plan() -> P2IngestPlan:
    return P2IngestPlan(
        sources=(IngestSource(path=E10), IngestSource(path=W03), IngestSource(path=E03)),
        label="t205-public-controls",
    )


def product_turn(turn: Any, *, number: int = 1) -> dict:
    return {
        "turn": number,
        "status": "ok",
        "error_code": None,
        "product": turn.as_dict(include_text=True),
    }


def case_row(case: CaseSpec, turns: list[dict], *, conversation: str = "conv-fin", status: str = "ok") -> dict:
    return {
        "case_id": case.case_id,
        "suite": case.suite,
        "stratum": case.stratum,
        "conversation_id": conversation,
        "status": status,
        "error_code": None,
        "planned_turns": max(1, len(case.turns)),
        "turns_executed": len(turns),
        "turns": turns,
    }


def score_turn(case: CaseSpec, turn: Any, *, conversation: str = "conv-fin"):
    return score_public_case(
        case,
        case_row(case, [product_turn(turn)], conversation=conversation),
        document_codes=DOCUMENTS,
        allowed_doc_codes=set(DOCUMENTS.values()),
    )


def score_frozen(case: CaseSpec, *, text: str, kind: str = "answer", sources: tuple[dict, ...] = ()):
    """冻结回答文本的确定性打分（不依赖产品当前状态；用于「反例必被判失败」）。"""
    turn = {
        "kind": kind,
        "text": text,
        "trace_id": f"frozen-{case.case_id}",
        "trace_path": "legacy",
        "sources": [dict(item) for item in sources],
        "http_status": 200,
    }
    return score_public_case(
        case,
        case_row(case, [{"turn": 1, "status": "ok", "error_code": None, "product": turn}]),
        document_codes=DOCUMENTS,
        allowed_doc_codes=set(DOCUMENTS.values()),
    )


def freeze_sources(document: str, locator: dict) -> tuple[dict, ...]:
    return (
        {
            "source_id": f"src-{document}-{len(locator)}",
            "document_name": document,
            "version_number": 1,
            "status": "active",
            "locator": dict(locator),
        },
    )


# --------------------------------------------------------------------------- #
# 1. 冻结诱饵文本：确定性判失败（评测器的反例，先于产品修复成立）
# --------------------------------------------------------------------------- #


def test_frozen_decoy_answers_are_rejected() -> None:
    target = score_frozen(
        KPI_TARGET_CASE,
        text=KPI_DECOY_ANSWER,
        sources=freeze_sources("E10_市场部KPI月报.xlsx", {"sheet": "KPI月报", "row": 103}),
    )
    assert target.score.status == CASE_STATUS_FAIL
    assert any(check["check_id"] == "value_hit" and check["status"] == "fail" for check in target.score.checks)

    approval = score_frozen(
        APPROVAL_CASE,
        text=APPROVAL_DECOY_ANSWER,
        sources=freeze_sources("W03_促销活动申请审批与结案流程管理办法.docx", {"heading": "第三章 审批权限"}),
    )
    assert approval.score.status == CASE_STATUS_FAIL
    assert any(
        check["check_id"] == "value_forbidden" and check["status"] == "fail"
        for check in approval.score.checks
    ), "其他分档的审批人不得被当成本题的答案依据"

    price = score_frozen(
        PRICE_CASE,
        text=PRICE_DECOY_ANSWER,
        sources=freeze_sources("E03_2026年Q4渠道价目表.xlsx", {"sheet": "NKA卖场", "row": 7}),
    )
    assert price.score.status == CASE_STATUS_FAIL
    assert any(check["check_id"] == "value_hit" and check["status"] == "fail" for check in price.score.checks)

    entity = score_frozen(
        ENTITY_CASE,
        text=ENTITY_DECOY_ANSWER,
        sources=freeze_sources("E03_2026年Q4渠道价目表.xlsx", {"sheet": "NKA卖场", "row": 7}),
    )
    assert entity.score.status == CASE_STATUS_FAIL
    assert any(check["check_id"] == "kind_correct" and check["status"] == "fail" for check in entity.score.checks)


def test_supported_frozen_answer_passes() -> None:
    supported = score_frozen(
        SUPPORTED_CASE,
        text=SUPPORTED_ANSWER,
        sources=freeze_sources("W03_促销活动申请审批与结案流程管理办法.docx", {"heading": "第五章 结案与稽核"}),
    )
    assert supported.score.status == CASE_STATUS_PASS, supported.score.to_dict()


def test_year_decoy_price_row_is_rejected() -> None:
    """2025 旧价（2.5）不能当 2026 Q4 档期特价的依据。"""
    stale = score_frozen(
        PRICE_CASE,
        text="价格单号：PX-0020；档期特价：2.5 元/瓶（2025-10-01 生效）",
        sources=freeze_sources("E03_2026年Q4渠道价目表.xlsx", {"sheet": "NKA卖场", "row": 20}),
    )
    assert stale.score.status == CASE_STATUS_FAIL
    failed = {check["check_id"] for check in stale.score.checks if check["status"] == "fail"}
    assert failed & {"value_hit", "value_forbidden", "source_hit"}


# --------------------------------------------------------------------------- #
# 2. 产品侧复现 + 正向对照（全 Mock，零出站）
# --------------------------------------------------------------------------- #


@asyncio_test
async def test_public_financial_controls_end_to_end(tmp_path: Path) -> None:
    reset_post_counters()
    chat = MockChatBackend()
    adapter = ProductEvalAdapter(
        tmp_path / "financial",
        chat=chat,
        dataset=empty_dataset(),
        ingest_plan=financial_plan(),
    )
    try:
        await adapter.start()
        receipts = await adapter.ingest()
        assert [receipt.job_state for receipt in receipts] == ["succeeded"] * 3
        assert [receipt.publish_status for receipt in receipts] == [200, 200, 200]

        conversation_id = await adapter.open_conversation()

        async def ask(number: int, question: str):
            return await adapter.ask_turn(
                question,
                user_id="employee",
                conversation_id=conversation_id,
                client_request_id=f"00000000-0000-4000-8000-{number:012d}",
            )

        # ---- 正向：有资料支持的问题必须可答 ----
        supported_turn = await ask(1, "活动结束后几日内上交结案报告？")
        assert supported_turn.kind == "answer"
        assert "6 个自然日" in supported_turn.text
        supported = score_turn(SUPPORTED_CASE, supported_turn)
        assert supported.score.status == CASE_STATUS_PASS, supported.score.to_dict()

        # ---- 多轮单字段切换：追问政策里的另一个时限字段 ----
        follow_turn = await ask(2, "那活动变更是提前多久？")
        assert follow_turn.kind == "answer"
        assert "3 个工作日" in follow_turn.text, follow_turn.text
        multi_case = CaseSpec(
            case_id="F06",
            suite="b0",
            split="dev",
            stratum="text",
            business_date="2026-10-28",
            question="活动结束后几日内上交结案报告？",
            turns=({"question": "活动结束后几日内上交结案报告？"}, {"question": "那活动变更是提前多久？"}),
            expected_kind="answer",
            expected_values=("3 个工作日",),
            expected_sources=({"doc_code": "W03", "locator": {"heading": "第二章 申请与时限"}},),
            labeler="lead",
            label_version="public-financial-2026-11-10",
        )
        multi = score_public_case(
            multi_case,
            case_row(
                multi_case,
                [product_turn(supported_turn, number=1), product_turn(follow_turn, number=2)],
                conversation=conversation_id,
            ),
            document_codes=DOCUMENTS,
            allowed_doc_codes=set(DOCUMENTS.values()),
        )
        assert multi.score.executed_turns == 2
        assert multi.score.status == CASE_STATUS_PASS, multi.score.to_dict()

        # ---- 诱饵 1：同表其他指标的年度目标 ----
        target_turn = await ask(3, "陈列达标率的计算口径和年度目标是什么？")
        target = score_turn(KPI_TARGET_CASE, target_turn)
        if "90%" not in target_turn.text:
            assert target.score.status == CASE_STATUS_FAIL, "缺目标值时不得判通过"
        else:  # 若产品已修复：必须同时给出口径与目标值
            assert target.score.status == CASE_STATUS_PASS

        # ---- 诱饵 2：同一法条其他分档的审批人 ----
        approval_turn = await ask(4, "单场预算 8000 元的活动由谁审批？")
        approval = score_turn(APPROVAL_CASE, approval_turn)
        if "事业部总经理" in approval_turn.text:
            assert approval.score.status == CASE_STATUS_FAIL, "其他分档审批人不得当答案依据"
        else:
            assert approval.score.status == CASE_STATUS_PASS

        # ---- 诱饵 3：他实体（价目表里没有的商品不能回别的 SKU） ----
        entity_turn = await ask(5, "2026年Q4渠道价目表中 咸味饼干 120g 的批发价是多少？")
        entity = score_turn(ENTITY_CASE, entity_turn)
        if entity_turn.kind == "answer":
            assert entity.score.status == CASE_STATUS_FAIL, "他实体数值不得被当答案依据"
        else:
            assert entity.score.status == CASE_STATUS_PASS

        # ---- 诱饵 4：年份（2026 Q4 的价格题不能只给 2025 旧行） ----
        price_turn = await ask(6, "2026年Q4 启沣柠檬茶（500ml PET）在NKA卖场的档期特价是多少？")
        price = score_turn(PRICE_CASE, price_turn)
        if "2.99" not in price_turn.text:
            assert price.score.status == CASE_STATUS_FAIL, "未给出 2026 Q4 档期特价时不得判通过"

        # ---- 来源权限没有被评测器削弱 ----
        detail_code, detail = await adapter.source_detail(
            supported_turn.message_id, supported_turn.source_ids[0]
        )
        assert detail_code == 200 and detail["status"] == "active"
        other_code, _ = await adapter.source_detail(
            supported_turn.message_id, supported_turn.source_ids[0], user_id="admin"
        )
        assert other_code == 403

        # ---- 零真实调用（实测，不是常量） ----
        calls = adapter.provider_calls()
        assert calls["outbound_network"] == 0
        assert sum(int(value) for value in (post_counters().get("attempts") or {}).values()) == 0
        assert chat.call_count >= 1  # Mock chat 真的被调用过（不是靠拒答凑数）
    finally:
        await adapter.close()


# --------------------------------------------------------------------------- #
# 3. U 更新/删除：复用既有口径，不因换评测器削弱
# --------------------------------------------------------------------------- #


def test_u_suite_reuses_existing_mutation_evidence() -> None:
    questions = json.loads((ROOT / "fixtures" / "acceptance" / "questions.json").read_text(encoding="utf-8"))
    ids = [item["id"] for item in questions["questions"]]
    assert tuple(P2_UPDATE_DELETE_IDS) == tuple(f"U{index:02d}" for index in range(1, 11))
    assert all(case_id in ids for case_id in P2_UPDATE_DELETE_IDS)
    for case_id in P2_UPDATE_DELETE_IDS:
        item = next(entry for entry in questions["questions"] if entry["id"] == case_id)
        scenario = item["scenario"]
        # 形态各不相同（actions / preconditions / sub_scenarios / requests），这里只核
        # 「仍是有断言、可执行的既有场景」，不复制它的语义判定。
        assert scenario.get("initial_state") == "B0"
        assert scenario.get("initialization_ref") == "b0_initialization"
        assert scenario.get("assertions"), f"{case_id} 必须保留可核对断言"

    mutation_test = ROOT / "backend" / "tests" / "acceptance" / "test_t09_mutation.py"
    assert mutation_test.is_file()
    source = mutation_test.read_text(encoding="utf-8")
    for case_id in P2_UPDATE_DELETE_IDS:
        assert case_id in source, f"{case_id} 必须仍由既有 U 测试覆盖"

    # 少一条 U 就不能放行（分母 10/10 是硬口径）
    scores = [
        P2CaseScore(
            case_id=case_id,
            suite="update_delete",
            stratum="mutation",
            status=CASE_STATUS_PASS if case_id != "U07" else CASE_STATUS_FAIL,
            requires_ocr=False,
            planned_turns=1,
            executed_turns=1,
        )
        for case_id in P2_UPDATE_DELETE_IDS
    ]
    scores += [
        P2CaseScore(
            case_id=case_id,
            suite="b0",
            stratum="ocr" if case_id in {"Q33", "Q34", "Q35", "Q36", "Q37", "Q38", "Q39", "Q40"} else "exact",
            status=CASE_STATUS_PASS,
            requires_ocr=case_id in {"Q33", "Q34", "Q35", "Q36", "Q37", "Q38", "Q39", "Q40"},
            planned_turns=1,
            executed_turns=1,
        )
        for case_id in [f"Q{index:02d}" for index in range(1, 41)]
    ]
    scores += [
        P2CaseScore(
            case_id=case_id,
            suite="other",
            stratum="other",
            status=CASE_STATUS_PASS,
            requires_ocr=False,
            planned_turns=1,
            executed_turns=1,
        )
        for case_id in P2_NEGATIVE_IDS + P2_BOUNDARY_IDS
    ]
    card = score_public_suites(scores)
    assert card.release_ready is False
    assert "suite_below_threshold" in {block.code for block in card.blocks}

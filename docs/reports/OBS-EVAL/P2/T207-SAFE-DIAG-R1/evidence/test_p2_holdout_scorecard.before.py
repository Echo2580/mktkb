"""P2-T207-FIX-H2SCORE：holdout run 在受限进程内算 H2 聚合（只写聚合）的定向测试。

覆盖任务书 §5：

1. **合成封存数据集（30 题 / 10-5-5-5-5 / 36 回合）跑 holdout run（Mock 产品）**：
   产物里出现 ``holdout_scorecard.json``，计数自洽；阈值未批 → ``holdout_threshold_unapproved``
   （unknown），但观测到的 pass 数照常可读；run 目录全文检索不到任何 H2 case_id / 题干。
2. **计数/语义**（合成判定，不造题）：23 pass / 1 fail（带硬失败）/ 6 error → 聚合计数、
   ``hard_failures``、``by_stratum``、block 口径逐项正确；缺题/未执行**永不**计 pass。
3. **映射规则**：语料文件名规范前缀（``D01_``/``V03_``）建 doc_code；版本文件按
   ``document_ref`` 归到槽；冲突/无前缀/缺 ingest plan 一律 fail closed；gold 期望的
   doc_code 映射不到 → ``holdout_document_code_unmapped`` block（不猜通过）。
4. **泄漏审计**：聚合文本里出现 case_id/题干/答案字段 → ``holdout_scorecard_leak``；
   评分/审计失败时退化成"全 error + 稳定 block"，产物照样写出（不会静默缺文件）。
5. **T207-FIX-H2SCORE-R1 三阻断**：B1（H2 打分必须看到回答正文：单变量 + 30 题实跑 23 pass + 去掉正文
   0 pass 的对照臂）/ B2（引用 superseded 等结构问题的题不计 pass）/ B3（多轮题面与 <8 字题干命中即
   fail-closed）；另有 N1（聚合器级泄漏仍写出 blocked 卡）/ N2（``real_calls`` 口径）/ N4（unmapped block
   去重）/ 公开 run 不写卡。

零真实调用：``t09_network_guard`` 把任何外部出站变成失败；合成封存夹具在 ``tmp_path`` 现生成
（Fernet key 现生成），不读 .env、不碰真实 H2/密钥、不联网、不写仓库内产物。

合成口径与 T202/T203 既有夹具一致：questions 13 键 / labels 11 键、manifest 严格 15 字段、
30 题冻结分层；差别只在本文件把 multi_turn 的 5 题排成 4×2 + 1×3 轮，凑满 H2 的 36 回合。
"""

from __future__ import annotations

import asyncio
import functools
import hashlib
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from cryptography.fernet import Fernet

_TESTS_DIR = Path(__file__).resolve().parents[1]
if str(_TESTS_DIR) not in sys.path:  # 复用既有验收级网络闸门，不复制实现
    sys.path.insert(0, str(_TESTS_DIR))

from acceptance.support.netguard import t09_network_guard  # noqa: E402,F401  (pytest fixture)

from mktkb.evaluation import p2_dataset as p2d
from mktkb.evaluation import p2_runner as runner
from mktkb.evaluation import p2_score_run
from mktkb.evaluation.dataset import CaseSpec
from mktkb.evaluation.p2_authorization import preflight_p2
from mktkb.evaluation.p2_contracts import (
    CHAT_HOST,
    CHAT_MODEL,
    CHAT_PRICING_SOURCE,
    CHAT_PROVIDER,
    CHAT_REGION,
    COST_CENTERS,
    P2_LEDGER_SNAPSHOT_SCHEMA_VERSION,
    P2LedgerSnapshot,
    P2PriceProfile,
    P2RequestItem,
    P2RunPlan,
)
from mktkb.evaluation.p2_dataset import (
    HOLDOUT_KEY_FILE_ENV,
    HOLDOUT_ROOT_ENV,
    LABELS_CIPHERTEXT_NAME,
    QUESTIONS_CIPHERTEXT_NAME,
    load_p2_dataset,
)
from mktkb.evaluation.p2_runner import (
    ERROR_HOLDOUT_DOCUMENT_CODE_AMBIGUOUS,
    ERROR_HOLDOUT_DOCUMENT_CODE_UNMAPPED,
    ERROR_HOLDOUT_SCORECARD_LEAK,
    P2RunError,
    P2RunLedger,
    build_dry_run_authorization,
    holdout_document_codes,
    run_p2,
)
from mktkb.evaluation.p2_scoring import (
    CASE_STATUS_ERROR,
    CASE_STATUS_FAIL,
    CASE_STATUS_PASS,
    P2_HOLDOUT_STRATA,
    P2HoldoutCaseScore,
    load_p2_gate_config,
    normalize_product_outcome,
)
from mktkb.evaluation.gold import ResolvedGold
from mktkb.evaluation.scorers import citation_number_keys, score_case
from mktkb.evaluation.product_adapter import (
    ChatBehavior,
    IngestSource,
    MockChatBackend,
    P2IngestPlan,
    P2RunDataset,
    ProductEvalAdapter,
    ProductTurn,
)

pytestmark = pytest.mark.usefixtures("t09_network_guard")

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "fixtures" / "acceptance"
D01 = FIXTURES / "normal" / "D01_物品位置表.xlsx"
D04 = FIXTURES / "normal" / "D04_活动策划流程.docx"

NOW = datetime(2026, 11, 11, 9, 0, tzinfo=timezone.utc)
NONCE = "1a" * 16

#: 合成标记：只用于断言"产物/错误里不出现题干与答案"，不是任何真实题目。
QUESTION_TOKEN = "SYNTHETIC-H2-QUESTION-TOKEN-5c1e"
FOLLOWUP_TOKEN = "SYNTHETIC-H2-FOLLOWUP-TOKEN-9d2b"
ANSWER_TOKEN = "SYNTHETIC-H2-ANSWER-TOKEN-4f7a"
#: T207-FIX-H2SCORE-R1：金标值（答案题必须命中它才算 pass —— 这正好把 B1 钉成可观测差异）。
VALUE_TOKEN = "合成命中答案甲"

LABEL_VERSION = "p2-holdout-v2-2026-11-10"
DATASET_VERSION = "P2-HOLDOUT-v2"
BUSINESS_DATE = "2026-10-28"
CREATED_UTC = "2026-11-10T12:00:00+00:00"
KEY_ID = "p2-holdout-v2"
CASE_PREFIX = "P2HS"

#: 冻结分层（测试自己写一份，防止与 p2_dataset.P2_STRATA 一起漂移）。
STRATA_PLAN: tuple[tuple[str, int], ...] = (
    ("paraphrase", 10),
    ("multi_turn", 5),
    ("negative", 5),
    ("stale_conflict", 5),
    ("cross_doc_security", 5),
)
TOTAL_CASES = sum(count for _name, count in STRATA_PLAN)
#: multi_turn 5 题：4 题两轮 + 1 题三轮 → 25 + 11 = 36 回合（与 H2 的 36 一致）。
MULTI_TURN_TURNS = (2, 2, 2, 2, 3)
EXPECTED_TURN_STATS = {
    "total_turns": 36,
    "max_turns_per_case": 3,
    "turn_histogram": {"1": 25, "2": 4, "3": 1},
}


def asyncio_test(func):
    """仓库没有 pytest-asyncio：用同一事件循环跑一个 async 用例（保留 fixture 签名）。"""

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any):
        return asyncio.run(func(*args, **kwargs))

    return wrapper


# --------------------------------------------------------------------------- #
# 合成封存数据集（30 题 / 10-5-5-5-5 / 36 回合）
# --------------------------------------------------------------------------- #


def _question_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    index = 0
    multi_turn_offset = 0
    for stratum, count in STRATA_PLAN:
        for offset in range(count):
            index += 1
            if stratum == "multi_turn":
                turns = [
                    f"{FOLLOWUP_TOKEN} 第 {turn} 轮"
                    for turn in range(1, MULTI_TURN_TURNS[multi_turn_offset] + 1)
                ]
                multi_turn_offset += 1
                question = ""
            else:
                turns = []
                question = f"{QUESTION_TOKEN} {stratum} {offset:02d}"
            rows.append(
                {
                    "case_id": f"{CASE_PREFIX}-{index:02d}",
                    "suite": "holdout",
                    "split": "holdout",
                    "stratum": stratum,
                    "business_date": BUSINESS_DATE,
                    "question": question,
                    "turns": turns,
                    "expected_kind": "refusal" if stratum == "negative" else "answer",
                    "should_refuse": stratum == "negative",
                    "requires_ocr": False,
                    "labeler": "data-custodian",
                    "label_version": LABEL_VERSION,
                    "notes": "合成夹具",
                }
            )
    return rows


def _label_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    labels: list[dict[str, Any]] = []
    for row in rows:
        refuse = bool(row["should_refuse"])
        labels.append(
            {
                "case_id": row["case_id"],
                "expected_kind": row["expected_kind"],
                "expected_values": [] if refuse else [VALUE_TOKEN],
                "expected_sources": (
                    []
                    if refuse
                    else [{"doc_code": "D01", "unit_key": "sheet:物品位置:row:8"}]
                ),
                "relevant_units": (
                    []
                    if refuse
                    else [{"doc_code": "D01", "locator": {"sheet": "物品位置", "row": 8}}]
                ),
                "reference_answer": "" if refuse else f"{ANSWER_TOKEN} 合成参考答案",
                "should_refuse": refuse,
                "refusal_reason": "合成负样本：语料无答案" if refuse else None,
                "forbidden_values": ["合成诱饵值"],
                "forbidden_sources": [{"doc_code": "V01"}],
                "notes": "合成夹具",
            }
        )
    return labels


def _jsonl(rows: list[dict[str, Any]]) -> bytes:
    return ("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n").encode("utf-8")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


@dataclass
class Sealed:
    root: Path
    key_file: Path
    manifest_path: Path


def _write_sealed(base: Path) -> Sealed:
    """在 ``base`` 下造一套合成封存：root/manifest.json + 两个 Fernet 密文 + keys/v2.key。"""
    rows = _question_rows()
    labels = _label_rows(rows)
    key = Fernet.generate_key()
    fernet = Fernet(key)
    q_token = fernet.encrypt(_jsonl(rows))
    l_token = fernet.encrypt(_jsonl(labels))
    root = base / "sealed"
    root.mkdir(parents=True, exist_ok=True)
    (root / QUESTIONS_CIPHERTEXT_NAME).write_bytes(q_token)
    (root / LABELS_CIPHERTEXT_NAME).write_bytes(l_token)
    manifest = {
        "schema_version": p2d.P2_MANIFEST_SCHEMA_VERSION,
        "dataset_version": DATASET_VERSION,
        "suite": p2d.P2_DATASET_SUITE,
        "label_version": LABEL_VERSION,
        "case_count": p2d.P2_CASE_COUNT,
        "strata": dict(p2d.P2_STRATA),
        "business_date": BUSINESS_DATE,
        "created_utc": CREATED_UTC,
        "author": "data-custodian",
        "encryption": {"kind": "fernet", "key_id": KEY_ID},
        "questions_plaintext_sha256": _sha(_jsonl(rows)),
        "labels_plaintext_sha256": _sha(_jsonl(labels)),
        "questions_ciphertext_sha256": _sha(q_token),
        "labels_ciphertext_sha256": _sha(l_token),
        "turn_stats": EXPECTED_TURN_STATS,
    }
    manifest_path = root / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    keys_dir = base / "keys"
    keys_dir.mkdir(parents=True, exist_ok=True)
    key_file = keys_dir / "v2.key"
    key_file.write_text(key.decode("ascii") + "\n", encoding="utf-8")
    return Sealed(root=root, key_file=key_file, manifest_path=manifest_path)


# --------------------------------------------------------------------------- #
# 计划 / 授权 / 数据集（dry-run：零真实调用）
# --------------------------------------------------------------------------- #


def _turn_questions(case: CaseSpec) -> tuple[str, ...]:
    if len(case.turns) < 2:
        return (case.question,)
    return tuple(str(turn.get("question") or turn.get("text")) for turn in case.turns)


def _price_profile() -> P2PriceProfile:
    return P2PriceProfile(
        kind="chat",
        model=CHAT_MODEL,
        provider=CHAT_PROVIDER,
        host=CHAT_HOST,
        region=CHAT_REGION,
        pricing_source=CHAT_PRICING_SOURCE,
        input_price_per_million_cny=2.0,
        output_price_per_million_cny=8.0,
        prompt_tokens_cap=6144,
        completion_tokens_cap=800,
    )


def _make_plan(cases: tuple[CaseSpec, ...], *, plan_id: str = "p2-t207-h2score") -> P2RunPlan:
    items = []
    for case in cases:
        for turn in range(1, len(_turn_questions(case)) + 1):
            items.append(
                P2RequestItem(
                    item_id=f"{case.case_id}:turn{turn}:answer",
                    operation="answer",
                    cost_center="answer_retrieval",
                    case_id=case.case_id,
                    turn=turn,
                    page=0,
                    requests=1,
                    price_profile=_price_profile(),
                    expected_success_cny=0.001,
                )
            )
    return P2RunPlan(
        schema_version="p2-run-plan/v0.1",
        plan_id=plan_id,
        plan_version="v1",
        mode="end_to_end",
        stage="P2-LIVE",
        created_utc="2026-11-11T00:00:00+00:00",
        project_total_limit_cny=40.0,
        stage_limit_cny=20.0,
        max_requests=1000,
        cost_centers_cny={
            "answer_retrieval": 12.0,
            "ocr": 3.0,
            "judge": 3.0,
            "independent": 2.0,
        },
        items=tuple(items),
    )


def _snapshot(plan: P2RunPlan) -> P2LedgerSnapshot:
    return P2LedgerSnapshot(
        schema_version=P2_LEDGER_SNAPSHOT_SCHEMA_VERSION,
        ledger_path="in-memory:unit",
        ledger_sha256="0" * 64,
        historical_prefix_sha256="1" * 64,
        budget_sha256="2" * 64,
        total_limit_cny=float(plan.project_total_limit_cny),
        historical_accounted_cny=15.0709445,
        accounted_cny=15.0709445,
        reservation_count=505,
        result_count=505,
        stage_allocations_cny={"S2-DEV": 3.0, "P1-RETRIEVAL": 2.0, "P2-LIVE": 20.0},
        p2_stage_accounted_cny=0.0,
        p2_center_accounted_cny={center: 0.0 for center in COST_CENTERS},
        source="in-memory",
    )


def _dry_run_authorization(plan: P2RunPlan):
    preflight = preflight_p2(plan, _snapshot(plan))
    assert preflight.ok, preflight.reasons
    return build_dry_run_authorization(plan, preflight, now=NOW, nonce=NONCE)


def _ingest_plan(*paths: Path) -> P2IngestPlan:
    return P2IngestPlan(sources=tuple(IngestSource(path=path) for path in paths), label="h2score")


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# 1. 合成封存数据集：holdout run 直接产出聚合 scorecard
# --------------------------------------------------------------------------- #


@asyncio_test
async def test_holdout_run_writes_aggregate_scorecard_without_case_details(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sealed = _write_sealed(tmp_path)
    monkeypatch.setenv(HOLDOUT_ROOT_ENV, str(sealed.root))
    monkeypatch.setenv(HOLDOUT_KEY_FILE_ENV, str(sealed.key_file))
    dataset = P2RunDataset.from_p2_dataset(
        load_p2_dataset(sealed.manifest_path, visibility="holdout")
    )
    assert len(dataset.cases) == 30
    plan = _make_plan(dataset.cases)
    authorization = _dry_run_authorization(plan)
    adapter = ProductEvalAdapter(
        tmp_path / "h2",
        chat=MockChatBackend(),
        dataset=dataset,
        ingest_plan=_ingest_plan(D01, D04),
        purge_traces_on_close=True,
    )
    run_dir = adapter.paths.run_dir
    try:
        result = await run_p2(
            plan,
            adapter=adapter,
            authorization=authorization,
            gate_config=load_p2_gate_config(),
            now=NOW,
        )
    finally:
        await adapter.close()

    assert result.status == "succeeded", result.as_dict()
    assert (run_dir / "holdout_scorecard.json").is_file()
    assert (run_dir / "holdout_aggregate.json").is_file()
    assert not (run_dir / "cases.jsonl").exists()
    assert not (run_dir / "requests.jsonl").exists()

    card = _read_json(run_dir / "holdout_scorecard.json")
    # 计数自洽：30 题全部有判定（executed 只含 pass/fail），error 不得混进 pass。
    assert card["total"] == 30
    assert card["executed"] + card["errors"] == 30
    assert card["passed"] + card["failed"] == card["executed"]
    # 本轮 Mock 对合成题一律 not_found：30 题都执行了、都被判 fail（没有凭空 pass/error）。
    assert card["executed"] == 30
    assert card["errors"] == 0
    assert card["passed"] == sum(counts["passed"] for counts in card["by_stratum"].values())
    assert card["hard_failures"] == sum(card["hard_failures_by_kind"].values())
    assert card["detail_export"] is False
    # 分层就是冻结分层（10/5/5/5/5），且逐层自洽。
    assert {name: counts["total"] for name, counts in card["by_stratum"].items()} == dict(
        p2d.P2_STRATA
    )
    for counts in card["by_stratum"].values():
        assert counts["passed"] + counts["failed"] + counts["errors"] == counts["total"]
    # 阈值未批 → unknown block；观测到的 pass 数照样可读（不因未批就抹掉）。
    assert card["thresholds_approved"] is False
    block_codes = {block["code"] for block in card["blocks"]}
    assert "holdout_threshold_unapproved" in block_codes
    assert card["release_ready"] is False
    assert isinstance(card["passed"], int) and card["passed"] >= 0
    # 执行身份：Mock 链只记 local_mock / 0 次真实调用，run_id/config_hash 与 manifest 一致。
    manifest = _read_json(run_dir / "run_manifest.json")
    assert card["execution_mode"] == "local_mock"
    assert card["real_calls"] == 0
    assert card["run_id"] == manifest["run_id"]
    assert card["config_hash"] == manifest["config_hash"]

    # 防泄漏：run 目录里任何产物都不得出现 H2 case_id / 题干 / 参考答案。
    rows = _question_rows()
    secrets = [str(row["case_id"]) for row in rows]
    secrets += [QUESTION_TOKEN, FOLLOWUP_TOKEN, ANSWER_TOKEN]
    for path in sorted(run_dir.iterdir()):
        raw = path.read_text(encoding="utf-8")
        for secret in secrets:
            assert secret not in raw, f"{path.name} 泄漏受限内容: {secret}"
    assert "case_id" not in card


@asyncio_test
async def test_holdout_run_midway_error_never_invents_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """一轮产品错误就停：已执行题记 error、未执行题记 error，pass 保持 0。"""
    sealed = _write_sealed(tmp_path)
    monkeypatch.setenv(HOLDOUT_ROOT_ENV, str(sealed.root))
    monkeypatch.setenv(HOLDOUT_KEY_FILE_ENV, str(sealed.key_file))
    dataset = P2RunDataset.from_p2_dataset(
        load_p2_dataset(sealed.manifest_path, visibility="holdout")
    )
    plan = _make_plan(dataset.cases)
    authorization = _dry_run_authorization(plan)
    adapter = ProductEvalAdapter(
        tmp_path / "h2-stop",
        # 第 1 次 chat 就 503：runner 必须立刻停，后面的题显式记未执行。
        chat=MockChatBackend(behaviors=(ChatBehavior(kind="http_error"),)),
        dataset=dataset,
        ingest_plan=_ingest_plan(D01, D04),
        purge_traces_on_close=True,
    )
    run_dir = adapter.paths.run_dir
    try:
        result = await run_p2(plan, adapter=adapter, authorization=authorization, now=NOW)
    finally:
        await adapter.close()

    assert result.status in {"aborted", "blocked"}
    card = _read_json(run_dir / "holdout_scorecard.json")
    aggregate = _read_json(run_dir / "holdout_aggregate.json")
    assert aggregate["cases"]["executed"] == 1
    assert card["total"] == 30
    assert card["passed"] == 0
    assert card["executed"] == 0
    assert card["errors"] == 30
    assert "holdout_case_error" in {block["code"] for block in card["blocks"]}


# --------------------------------------------------------------------------- #
# 2. 计数/语义（合成判定；缺题/未执行不计 pass）
# --------------------------------------------------------------------------- #


def _synthetic_cases(gold_doc_code: str | None = None) -> tuple[CaseSpec, ...]:
    """30 题合成 CaseSpec；给 ``gold_doc_code`` 时每题都带一条期望来源（用于映射校验）。"""
    cases: list[CaseSpec] = []
    index = 0
    for stratum, count in STRATA_PLAN:
        for offset in range(count):
            index += 1
            cases.append(
                CaseSpec(
                    case_id=f"{CASE_PREFIX}-{index:02d}",
                    suite="p2-holdout",
                    split="holdout",
                    stratum=stratum,
                    business_date=BUSINESS_DATE,
                    question=f"{QUESTION_TOKEN} {stratum} {offset:02d}",
                    expected_sources=(
                        ()
                        if gold_doc_code is None
                        else ({"doc_code": gold_doc_code, "unit_key": "sheet:物品位置:row:8"},)
                    ),
                    label_version=LABEL_VERSION,
                )
            )
    return tuple(cases)


def _synthetic_dataset(
    cases: tuple[CaseSpec, ...], *, visibility: str = "holdout"
) -> P2RunDataset:
    strata: dict[str, int] = {}
    for case in cases:
        strata[case.stratum] = strata.get(case.stratum, 0) + 1
    return P2RunDataset(
        visibility=visibility,
        cases=cases,
        identity={
            "dataset_version": DATASET_VERSION,
            "label_version": LABEL_VERSION,
            "suite": "p2-holdout",
            "manifest_sha256": "b" * 64,
            "case_count": len(cases),
            "strata": strata,
        },
    )


def _ledger(run_id: str = "p2run-h2score-unit") -> P2RunLedger:
    return P2RunLedger(
        run_id=run_id,
        plan_id="p2-t207-h2score",
        plan_sha256="a" * 64,
        execution="dry_run",
        production_ready=False,
    )


class _Source:
    """duck-typed IngestSource：只暴露 path/name/document_ref（不要求文件存在）。"""

    def __init__(self, path: str, *, name: str | None = None, document_ref: str | None = None):
        self.path = Path(path)
        self.name = name
        self.document_ref = document_ref


class _Plan:
    def __init__(self, *sources: _Source) -> None:
        self.sources = tuple(sources)


def _codes_plan() -> _Plan:
    return _Plan(
        _Source("fixtures/V03_物品位置表_历史V1.xlsx", name="D01_物品位置表.xlsx"),
        _Source("fixtures/D01_物品位置表.xlsx", document_ref="D01_物品位置表.xlsx"),
        _Source("fixtures/V04_物品位置表_新版V3.xlsx", document_ref="D01_物品位置表.xlsx"),
        _Source("fixtures/V05_物品位置表_新版V3_移除P01.xlsx", document_ref="D01_物品位置表.xlsx"),
        _Source("fixtures/D02_合作店家信息.xlsx"),
        _Source("fixtures/V06_合作店家信息_新电话.xlsx", document_ref="D02_合作店家信息.xlsx"),
        _Source("fixtures/D03_市场部工作指南.docx"),
        _Source("fixtures/D04_活动策划流程.docx"),
        _Source("fixtures/D05_物料领用规范.pdf"),
        _Source("fixtures/D06_店家资料维护说明.pdf"),
        _Source("fixtures/V01_临时物料位置通知.pdf"),
        _Source("fixtures/V07_物料位置独立通知.pdf"),
    )


def test_counts_and_unknown_semantics_from_synthetic_marks(monkeypatch: pytest.MonkeyPatch) -> None:
    cases = _synthetic_cases()
    dataset = _synthetic_dataset(cases)

    def _fake_scores(case_seq, rows, **_kwargs):  # noqa: ANN001 - 与真 helper 同签名前缀
        marks = []
        for case in case_seq:
            number = int(case.case_id.rsplit("-", 1)[1])
            if number <= 23:
                marks.append(
                    P2HoldoutCaseScore(
                        case_id=case.case_id, stratum=case.stratum, status=CASE_STATUS_PASS
                    )
                )
            elif number == 24:
                marks.append(
                    P2HoldoutCaseScore(
                        case_id=case.case_id,
                        stratum=case.stratum,
                        status=CASE_STATUS_FAIL,
                        hard_failure="safety",
                    )
                )
            else:
                marks.append(
                    P2HoldoutCaseScore(
                        case_id=case.case_id, stratum=case.stratum, status=CASE_STATUS_ERROR
                    )
                )
        return tuple(marks), ["source_outside_run"]

    monkeypatch.setattr(p2_score_run, "holdout_case_scores_from_rows", _fake_scores)
    # A synthetic verdict tally tests aggregation, not the runner's evidence boundary.
    ledger, blocks = _ledger(), []
    marks, mode = runner._holdout_score_marks(ledger, dataset, ingest_plan=_codes_plan(),
        execution='dry_run', blocks=blocks)
    card = runner._aggregate_marks(marks, dataset=dataset, ledger=ledger,
        binding={'config_hash': 'c' * 64}, gate_config=None, execution_mode=mode,
        real_calls=0, blocks=blocks)

    assert card["total"] == 30
    assert card["passed"] == 23
    assert card["failed"] == 1
    assert card["errors"] == 6
    assert card["executed"] == 24
    assert card["hard_failures"] == 1
    assert card["hard_failures_by_kind"]["safety"] == 1
    # 阈值未批：unknown block 在，但观测值 23 可读（不是 unknown 把数字抹掉）。
    assert card["thresholds_approved"] is False
    assert card["threshold_met"] is False
    codes = {block["code"] for block in card["blocks"]}
    assert {
        "holdout_below_threshold",
        "holdout_hard_failure",
        "holdout_case_error",
        "holdout_threshold_unapproved",
        "holdout_hard_failure_unclassified",
    } <= codes
    assert card["run_id"] == "p2run-h2score-unit"
    assert card["config_hash"] == "c" * 64
    assert card["execution_mode"] == "local_mock"
    assert card["real_calls"] == 0
    raw = json.dumps(card, ensure_ascii=False)
    for case in cases:
        assert case.case_id not in raw
    assert QUESTION_TOKEN not in raw


def test_not_executed_cases_never_count_as_pass() -> None:
    cases = _synthetic_cases()
    dataset = _synthetic_dataset(cases)
    card = runner._holdout_scorecard(
        _ledger(),
        dataset,
        ingest_plan=_codes_plan(),
        execution="dry_run",
        real_calls=0,
        binding={},
        gate_config=None,
    )

    assert card["total"] == 30
    assert card["passed"] == 0
    assert card["failed"] == 0
    assert card["errors"] == 30
    assert card["executed"] == 0
    codes = {block["code"] for block in card["blocks"]}
    assert "holdout_case_error" in codes


def test_unmappable_expected_doc_code_becomes_unknown_block() -> None:
    cases = _synthetic_cases(gold_doc_code="D09")
    dataset = _synthetic_dataset(cases)
    card = runner._holdout_scorecard(
        _ledger(),
        dataset,
        ingest_plan=_Plan(_Source("fixtures/D01_物品位置表.xlsx")),
        execution="dry_run",
        real_calls=0,
        binding={},
        gate_config=None,
    )
    blocks = {block["code"]: block for block in card["blocks"]}
    assert ERROR_HOLDOUT_DOCUMENT_CODE_UNMAPPED in blocks
    assert blocks[ERROR_HOLDOUT_DOCUMENT_CODE_UNMAPPED]["evidence"]["missing_count"] == 1
    # 映射不到就不是 pass：30 题全按未执行/error 记。
    assert card["passed"] == 0


# --------------------------------------------------------------------------- #
# 3. 文档代号映射（语料文件名规范前缀）
# --------------------------------------------------------------------------- #


def test_document_codes_come_from_canonical_file_prefixes() -> None:
    codes = holdout_document_codes(_codes_plan())

    assert codes["D01_物品位置表.xlsx"] == "D01"
    assert codes["D01_物品位置表"] == "D01"
    # 版本文件按 document_ref 归到槽：V03/V04/V05 都属于 D01。
    assert codes["V03_物品位置表_历史V1.xlsx"] == "D01"
    assert codes["V04_物品位置表_新版V3.xlsx"] == "D01"
    assert codes["V05_物品位置表_新版V3_移除P01.xlsx"] == "D01"
    assert codes["V06_合作店家信息_新电话.xlsx"] == "D02"
    assert codes["D06_店家资料维护说明.pdf"] == "D06"
    assert codes["V01_临时物料位置通知.pdf"] == "V01"
    assert codes["V07_物料位置独立通知.pdf"] == "V07"
    assert set(codes.values()) == {f"D0{number}" for number in range(1, 7)} | {"V01", "V07"}


def test_document_code_conflict_and_missing_prefix_fail_closed() -> None:
    conflicting = _Plan(
        _Source("fixtures/D09_x.xlsx"),
        # 同一文件名（D09_x.xlsx）被另一份 source 归到 V02：语料不自洽，不能择一。
        _Source("fixtures/D09_x.xlsx", name="V02_x"),
    )
    with pytest.raises(P2RunError) as info:
        holdout_document_codes(conflicting)
    assert info.value.code == ERROR_HOLDOUT_DOCUMENT_CODE_AMBIGUOUS

    with pytest.raises(P2RunError) as info:
        holdout_document_codes(_Plan(_Source("fixtures/notes.txt")))
    assert info.value.code == ERROR_HOLDOUT_DOCUMENT_CODE_UNMAPPED

    with pytest.raises(P2RunError) as info:
        holdout_document_codes(None)
    assert info.value.code == ERROR_HOLDOUT_DOCUMENT_CODE_UNMAPPED


# --------------------------------------------------------------------------- #
# 4. 泄漏审计 / fail-closed 落盘
# --------------------------------------------------------------------------- #


def test_scorecard_audit_rejects_case_ids_and_detail_fields() -> None:
    dataset = _synthetic_dataset(_synthetic_cases())
    case_id = dataset.cases[0].case_id

    with pytest.raises(P2RunError) as info:
        runner._assert_holdout_scorecard_payload(
            {"blocks": [{"code": "x", "evidence": {"note": case_id}}]}, dataset
        )
    assert info.value.code == ERROR_HOLDOUT_SCORECARD_LEAK

    with pytest.raises(P2RunError) as info:
        runner._assert_holdout_scorecard_payload(
            {"blocks": [{"code": "x", "evidence": {"question": "?"}}]}, dataset
        )
    assert info.value.code == ERROR_HOLDOUT_SCORECARD_LEAK

    with pytest.raises(P2RunError) as info:
        runner._assert_holdout_scorecard_payload({"blocks": [{"code": "H2-01"}]}, dataset)
    assert info.value.code == ERROR_HOLDOUT_SCORECARD_LEAK


def test_builder_failure_degrades_to_all_error_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    dataset = _synthetic_dataset(_synthetic_cases())

    def _boom(*_args, **_kwargs):  # noqa: ANN001 - 故意抛错
        raise P2RunError("document_codes_exploded", "synthetic")

    monkeypatch.setattr(runner, "_holdout_scorecard", _boom)
    payload = runner._holdout_scorecard_artifact(
        _ledger(),
        dataset,
        ingest_plan=_codes_plan(),
        execution="dry_run",
        real_calls=0,
        binding={},
        gate_config=None,
    )
    assert payload["total"] == 30
    assert payload["passed"] == 0
    assert payload["errors"] == 30
    assert {block["code"] for block in payload["blocks"]} >= {"holdout_case_unscorable"}
    raw = json.dumps(payload, ensure_ascii=False)
    for case in dataset.cases:
        assert case.case_id not in raw
    assert QUESTION_TOKEN not in raw


def test_scoring_exception_on_one_case_is_error_not_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    cases = _synthetic_cases()
    dataset = _synthetic_dataset(cases)

    def _raise_always(case_seq, rows, **_kwargs):  # noqa: ANN001
        raise ValueError("synthetic scoring failure")

    monkeypatch.setattr(p2_score_run, "holdout_case_scores_from_rows", _raise_always)
    card = runner._holdout_scorecard(
        _ledger(),
        dataset,
        ingest_plan=_codes_plan(),
        execution="dry_run",
        real_calls=0,
        binding={},
        gate_config=None,
    )
    blocks = {block["code"]: block for block in card["blocks"]}
    assert "holdout_case_unscorable" in blocks
    assert blocks["holdout_case_unscorable"]["evidence"]["cases"] == 30
    assert card["passed"] == 0
    assert card["errors"] == 30

# --------------------------------------------------------------------------- #
# 5. T207-FIX-H2SCORE-R1：B1（回答正文）/ B2（结构问题不计 pass）/ B3（多轮题面）
# --------------------------------------------------------------------------- #

#: 合成引用单位 id（与 product.evidence[].unit_id 同值，打分侧据此取 unit_key）。
UNIT_ID = "7f0e5d3c-0000-4000-8000-000000000001"
#: 同一文档里的另一个单位（"文档对、单位错"的反例用它，避免被同 id 的索引覆盖）。
WRONG_UNIT_ID = "7f0e5d3c-0000-4000-8000-000000000002"


def _product_turn(
    question: str,
    *,
    kind: str = "answer",
    text: str = "",
    source_id: str | None = UNIT_ID,
    unit_key: str = "sheet:物品位置:row:8",
    status: str = "active",
) -> ProductTurn:
    """一次可判定的产品观测：kind/text/sources/evidence 与真实产品回合同形。"""
    sources: tuple[dict[str, Any], ...] = ()
    evidence: tuple[dict[str, Any], ...] = ()
    source_ids: tuple[str, ...] = ()
    if source_id is not None:
        sources = (
            {
                "source_id": source_id,
                "document_name": "D01_物品位置表.xlsx",
                "status": status,
            },
        )
        source_ids = (source_id,)
        evidence = (
            {
                "unit_id": source_id,
                "unit_key": unit_key,
                "locator": {"sheet": "物品位置", "row": 8},
                "verified": True,
            },
        )
    return ProductTurn(
        question_sha256=hashlib.sha256(question.encode("utf-8")).hexdigest(),
        question_chars=len(question),
        client_request_id="p2req-synthetic",
        http_status=200,
        kind=kind,
        text=text,
        message_id="p2msg-synthetic",
        request_id="p2res-synthetic",
        revision=1,
        error_code=None,
        retryable=False,
        source_ids=source_ids,
        sources=sources,
        missing_fields=(),
        candidates=0,
        trace_id=None,
        trace_path=None,
        trace_outcome=None,
        trace_status=None,
        trace_spans=(),
        replayed=False,
        elapsed_ms=1,
        evidence=evidence,
    )


def _value_case() -> CaseSpec:
    """一条"答对才算 pass"的合成题：金标值 + 一条期望来源。"""
    return CaseSpec(
        case_id=f"{CASE_PREFIX}-01",
        suite="p2-holdout",
        split="holdout",
        stratum="paraphrase",
        business_date=BUSINESS_DATE,
        question=f"{QUESTION_TOKEN} 合成问句",
        expected_values=(VALUE_TOKEN,),
        expected_sources=({"doc_code": "D01", "unit_key": "sheet:物品位置:row:8"},),
        reference_answer=f"{ANSWER_TOKEN} 合成参考答案",
        label_version=LABEL_VERSION,
    )


def _scoring_row(case: CaseSpec, product: Mapping[str, Any]) -> dict[str, Any]:
    """与 runner 的打分行同形的单轮行（product 由 ProductTurn.as_dict 给出）。"""
    return {
        "schema_version": "p2-run-case/v0.1",
        "case_id": case.case_id,
        "status": "ok",
        "error_code": None,
        "planned_turns": 1,
        "conversation_id": "conv-synthetic",
        "turns": [
            {
                "turn": 1,
                "item_id": f"{case.case_id}:turn1:answer",
                "status": "ok",
                "error_code": None,
                "product": dict(product),
            }
        ],
    }


def _card_for_rows(case: CaseSpec, row: Mapping[str, Any]) -> dict[str, Any]:
    ledger = _ledger()
    ledger.record_scoring_case(row)
    return runner._holdout_scorecard(
        ledger,
        _synthetic_dataset((case,)),
        ingest_plan=_codes_plan(),
        execution="dry_run",
        real_calls=0,
        binding={},
        gate_config=None,
    )


def test_holdout_scoring_rows_need_product_text_single_variable() -> None:
    """B1 单变量：同一条产品观测，带 text → pass；去掉 text → fail。"""
    case = _value_case()
    turn = _product_turn(case.question, text=f"资料写着：{VALUE_TOKEN}")

    with_text = _card_for_rows(case, _scoring_row(case, turn.as_dict(include_text=True)))
    without_text = _card_for_rows(case, _scoring_row(case, turn.as_dict(include_text=False)))

    assert (with_text["passed"], with_text["failed"], with_text["errors"]) == (1, 0, 0)
    # 只有回答正文消失：这是唯一的变量，pass 因此归零（修复前 H2 的真实形态）。
    assert (without_text["passed"], without_text["failed"], without_text["errors"]) == (0, 1, 0)


def _answering_products(dataset: P2RunDataset) -> dict[str, ProductTurn]:
    """可判定的 Mock 产品：23 题按金标作答，7 题故意不满足（5 负样本错答 + 2 题引错单位）。"""
    wrong_units = {f"{CASE_PREFIX}-29", f"{CASE_PREFIX}-30"}
    products: dict[str, ProductTurn] = {}
    for case in dataset.cases:
        for question in _turn_questions(case):
            if case.stratum == "negative":
                # 负样本本该拒答：这里故意作答 → refusal_expected / kind_correct 双 fail。
                products[question] = _product_turn(
                    question, kind="answer", text=f"资料写着：{VALUE_TOKEN}"
                )
            elif case.case_id in wrong_units:
                # 文档对、单位错：source_hit fail（不是结构问题，仍记 fail 而不是 error）。
                products[question] = _product_turn(
                    question,
                    text=f"资料写着：{VALUE_TOKEN}",
                    source_id=WRONG_UNIT_ID,
                    unit_key="sheet:物品位置:row:99",
                )
            else:
                products[question] = _product_turn(question, text=f"资料写着：{VALUE_TOKEN}")
    return products


async def _run_answering_holdout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    drop_text: bool = False,
) -> tuple[dict[str, Any], Path, P2RunDataset]:
    """30 题合成封存 + "会作答"的 Mock 产品跑一次 holdout run，返回 (card, run_dir, dataset)。

    drop_text=True 只把**打分行**的回答正文去掉（模拟修复前的口径），产品观测本身不变：
    这是 B1 的对照臂，用来证明"23 条正确回答全 pass"确实是靠内存里的正文达成的。
    """
    if drop_text:
        kept = runner._scoring_case_row

        def _drop(case_row, products):  # noqa: ANN001 - 与真函数同签名
            row = kept(case_row, products)
            for turn in row.get("turns") or ():
                product = turn.get("product")
                if isinstance(product, dict):
                    product.pop("text", None)
            return row

        monkeypatch.setattr(runner, "_scoring_case_row", _drop)
    sealed = _write_sealed(tmp_path)
    monkeypatch.setenv(HOLDOUT_ROOT_ENV, str(sealed.root))
    monkeypatch.setenv(HOLDOUT_KEY_FILE_ENV, str(sealed.key_file))
    dataset = P2RunDataset.from_p2_dataset(
        load_p2_dataset(sealed.manifest_path, visibility="holdout")
    )
    plan = _make_plan(dataset.cases)
    authorization = _dry_run_authorization(plan)
    adapter = ProductEvalAdapter(
        tmp_path / "h2-pass",
        chat=MockChatBackend(),
        dataset=dataset,
        ingest_plan=_ingest_plan(D01, D04),
        purge_traces_on_close=True,
    )
    products = _answering_products(dataset)

    async def _scripted_ask(
        question: str, *, user_id: str, conversation_id: str, client_request_id: str
    ) -> ProductTurn:
        return products[str(question)]

    # 只替换"产品怎么答"，其余（灌库/建会话/产物/网络计量）都走真实适配器。
    adapter.ask_turn = _scripted_ask  # type: ignore[method-assign]
    run_dir = adapter.paths.run_dir
    try:
        result = await run_p2(
            plan,
            adapter=adapter,
            authorization=authorization,
            gate_config=load_p2_gate_config(),
            now=NOW,
        )
    finally:
        await adapter.close()

    assert result.status == "succeeded", result.as_dict()
    return _read_json(run_dir / "holdout_scorecard.json"), run_dir, dataset


@asyncio_test
async def test_holdout_run_with_answering_product_counts_23_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """B1：30 题实跑，23 条正确回答逐题计 pass（修复前结构性 0 pass）。"""
    card, run_dir, dataset = await _run_answering_holdout(tmp_path, monkeypatch)

    assert (card["total"], card["executed"], card["errors"]) == (30, 30, 0)
    assert (card["passed"], card["failed"]) == (23, 7)
    assert card["by_stratum"] == {
        "paraphrase": {"total": 10, "passed": 10, "failed": 0, "errors": 0},
        "multi_turn": {"total": 5, "passed": 5, "failed": 0, "errors": 0},
        "negative": {"total": 5, "passed": 0, "failed": 5, "errors": 0},
        "stale_conflict": {"total": 5, "passed": 5, "failed": 0, "errors": 0},
        "cross_doc_security": {"total": 5, "passed": 3, "failed": 2, "errors": 0},
    }
    # 23 < 24：阈值未达但**不再是结构性 0**；读数可用来判断质量。
    assert card["threshold_met"] is False
    assert "holdout_below_threshold" in {block["code"] for block in card["blocks"]}
    assert card["execution_mode"] == "local_mock"
    assert card["real_calls"] == 0

    # 打分行只在内存：run 目录里任何产物都不得出现 case_id / 题干 / 答案 / 金标值。
    secrets = [case.case_id for case in dataset.cases]
    secrets += [QUESTION_TOKEN, FOLLOWUP_TOKEN, ANSWER_TOKEN, VALUE_TOKEN]
    for path in sorted(run_dir.iterdir()):
        raw = path.read_text(encoding="utf-8")
        for secret in secrets:
            assert secret not in raw, f"{path.name} 泄漏受限内容: {secret}"
    assert not (run_dir / "cases.jsonl").exists()
    assert not (run_dir / "requests.jsonl").exists()


@asyncio_test
async def test_holdout_run_without_product_text_returns_to_zero_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """B1 对照臂：同一批正确回答，打分行不带正文（修复前口径）→ 30 题全 fail。"""
    card, _run_dir, _dataset = await _run_answering_holdout(
        tmp_path, monkeypatch, drop_text=True
    )

    assert (card["total"], card["executed"], card["errors"]) == (30, 30, 0)
    assert (card["passed"], card["failed"]) == (0, 30)

def test_superseded_source_never_counts_as_pass() -> None:
    """B2：引用 superseded 来源 → 该题记 error（不计 pass）+ 未分类 block。"""
    case = _value_case()
    active = _product_turn(case.question, text=f"资料写着：{VALUE_TOKEN}")
    stale = _product_turn(case.question, text=f"资料写着：{VALUE_TOKEN}", status="superseded")

    passing = _card_for_rows(case, _scoring_row(case, active.as_dict(include_text=True)))
    stale_card = _card_for_rows(case, _scoring_row(case, stale.as_dict(include_text=True)))

    assert (passing["passed"], passing["errors"]) == (1, 0)
    assert (stale_card["passed"], stale_card["failed"], stale_card["errors"]) == (0, 0, 1)
    blocks = {block["code"]: block for block in stale_card["blocks"]}
    assert "holdout_hard_failure_unclassified" in blocks
    evidence = blocks["holdout_hard_failure_unclassified"]["evidence"]
    # hard_failures 仍由封存标注方判定：本卡只保证"不计 pass + 明说 0 不是无硬失败"。
    assert evidence["codes"] == ["source_not_active"]
    assert evidence["counted_as"] == CASE_STATUS_ERROR
    assert evidence["hard_failures_owner"] == "sealed-labels"
    assert stale_card["hard_failures"] == 0


def test_leak_audit_covers_multi_turn_and_short_questions() -> None:
    """B3：多轮题面（含 <8 字）命中即 fail-closed；干净卡不误报。"""
    case = CaseSpec(
        case_id=f"{CASE_PREFIX}-01",
        suite="p2-holdout",
        split="holdout",
        stratum="multi_turn",
        business_date=BUSINESS_DATE,
        question="",
        turns=({"question": "退货"}, {"question": "这个月物料还剩多少"}),
        reference_answer="合成参考答案乙",
        label_version=LABEL_VERSION,
    )
    dataset = _synthetic_dataset((case,))
    # 2 字起一律按子串直报（1 字题面在产物里没有判别力，见 _HOLDOUT_LEAK_MIN_NEEDLE）。
    assert runner._HOLDOUT_LEAK_MIN_NEEDLE == 2
    for needle in ("退货", "这个月物料还剩多少", "合成参考答案乙"):
        with pytest.raises(P2RunError) as info:
            runner._assert_holdout_scorecard_payload(
                {"blocks": [{"code": "x", "detail": needle}]}, dataset
            )
        assert info.value.code == ERROR_HOLDOUT_SCORECARD_LEAK
    # 不含题面的正常卡不报（阈值设计不制造系统性 fail-closed）。
    clean = runner._holdout_scorecard(_ledger(), dataset, ingest_plan=_codes_plan(),
        execution='dry_run', real_calls=0, binding={}, gate_config=None)
    runner._assert_holdout_scorecard_payload(clean, dataset, run_id=_ledger().run_id)


def test_aggregator_leak_still_writes_blocked_card(monkeypatch: pytest.MonkeyPatch) -> None:
    """N1：泄漏来自聚合器自身时，兜底不再经过聚合器，blocked 卡照样写出。"""
    cases = _synthetic_cases()
    dataset = _synthetic_dataset(cases)

    def _leaky_aggregate(*_args, **_kwargs):  # noqa: ANN001 - 故意泄漏 case_id
        return {"blocks": [{"code": "x", "detail": cases[0].case_id}]}

    monkeypatch.setattr(runner, "_aggregate_marks", _leaky_aggregate)
    payload = runner._holdout_scorecard_artifact(
        _ledger(),
        dataset,
        ingest_plan=_codes_plan(),
        execution="dry_run",
        real_calls=0,
        binding={},
        gate_config=None,
    )
    assert (payload["total"], payload["passed"], payload["errors"]) == (30, 0, 30)
    assert {block["code"] for block in payload["blocks"]} == {ERROR_HOLDOUT_SCORECARD_LEAK}
    raw = json.dumps(payload, ensure_ascii=False)
    for case in cases:
        assert case.case_id not in raw


def test_scorecard_real_calls_use_outbound_attempts() -> None:
    """N2：与 p2-score 同口径（实测出站尝试数），不是"有出网的请求行数"。"""
    assert runner._scorecard_real_calls(None) == 0
    assert runner._scorecard_real_calls((7, {"outbound_attempts": 7})) == 7


def test_missing_ingest_plan_reports_single_unmapped_block() -> None:
    """N4：无 ingest plan 时只出**一条** unmapped block（不叠同因的第二条）。"""
    dataset = _synthetic_dataset(_synthetic_cases())
    card = runner._holdout_scorecard(
        _ledger(),
        dataset,
        ingest_plan=None,
        execution="dry_run",
        real_calls=0,
        binding={},
        gate_config=None,
    )
    codes = [block["code"] for block in card["blocks"]]
    assert codes.count(ERROR_HOLDOUT_DOCUMENT_CODE_UNMAPPED) == 1
    assert card["passed"] == 0


@asyncio_test
async def test_public_run_never_writes_holdout_scorecard(tmp_path: Path) -> None:
    """公开 run 不写 scorecard：还会清掉同一 run 目录里上一轮残留的 H2 聚合。"""
    dataset = _synthetic_dataset(_synthetic_cases(), visibility="public")
    plan = _make_plan(dataset.cases)
    authorization = _dry_run_authorization(plan)
    adapter = ProductEvalAdapter(
        tmp_path / "public-run",
        chat=MockChatBackend(),
        dataset=dataset,
        ingest_plan=_ingest_plan(D01, D04),
    )
    run_dir = adapter.paths.run_dir
    run_dir.mkdir(parents=True, exist_ok=True)
    for stale in ("holdout_scorecard.json", "holdout_aggregate.json"):
        (run_dir / stale).write_text("{}\n", encoding="utf-8")
    try:
        result = await run_p2(plan, adapter=adapter, authorization=authorization, now=NOW)
    finally:
        await adapter.close()

    assert result.status == "succeeded", result.as_dict()
    assert (run_dir / "cases.jsonl").is_file()
    assert not (run_dir / "holdout_scorecard.json").exists()
    assert not (run_dir / "holdout_aggregate.json").exists()

# --------------------------------------------------------------------------- #
# T207-FIX-H2KIND：合成 H2 30 题（answer 23 / conflict 1 / refusal 6）
# 只在内存里按逐题行打分（不跑产品、不走封存加解密、零真实调用）。
# --------------------------------------------------------------------------- #

H2KIND_CASE_PREFIX = "P2HK"
#: 金标值：无数字、无内部空白 —— 与 value/metric 的其它 opt-in 无关，单变量只是拒答口径。
H2KIND_VALUE = "合成命中答案甲"
H2KIND_DOC_NAME = "D01_物品位置表.xlsx"
H2KIND_UNIT_ID = "33333333-3333-4333-8333-333333333333"
H2KIND_UNIT_KEY = "sheet:物品位置:row:8"
H2KIND_DOCUMENT_CODES = {H2KIND_DOC_NAME: "D01"}
H2KIND_SOURCE_INDEX = {
    H2KIND_UNIT_ID: {"doc_code": "D01", "unit_key": H2KIND_UNIT_KEY, "locator": {}}
}
#: 冻结分层（本文件自己写一份；与 P2_HOLDOUT_STRATA 漂移即失败）。
H2KIND_STRATA_PLAN: tuple[tuple[str, int], ...] = (
    ("paraphrase", 10),
    ("multi_turn", 5),
    ("negative", 5),
    ("stale_conflict", 5),
    ("cross_doc_security", 5),
)


def _h2kind_specs() -> tuple[CaseSpec, ...]:
    """30 题：5 负样本 + 1 越权安全题 = 6 道 refusal；1 道冲突题；其余 23 道 answer。"""
    assert dict(H2KIND_STRATA_PLAN) == dict(P2_HOLDOUT_STRATA)
    specs: list[CaseSpec] = []
    index = 0
    for stratum, count in H2KIND_STRATA_PLAN:
        for offset in range(count):
            index += 1
            refusal = stratum == "negative" or (
                stratum == "cross_doc_security" and offset == 0
            )
            conflict = stratum == "stale_conflict" and offset == 0
            specs.append(
                CaseSpec(
                    case_id=f"{H2KIND_CASE_PREFIX}-{index:02d}",
                    suite="p2-holdout",
                    split="holdout",
                    stratum=stratum,
                    business_date=BUSINESS_DATE,
                    question=f"{QUESTION_TOKEN} 合成问句 {index:02d}",
                    expected_kind="refusal" if refusal else ("conflict" if conflict else "answer"),
                    expected_values=() if (refusal or conflict) else (H2KIND_VALUE,),
                    expected_sources=(
                        ()
                        if (refusal or conflict)
                        else ({"doc_code": "D01", "unit_key": H2KIND_UNIT_KEY},)
                    ),
                    reference_answer="" if (refusal or conflict) else f"{H2KIND_VALUE}（合成）",
                    labeler="data-custodian",
                    label_version=LABEL_VERSION,
                    should_refuse=refusal,
                    refusal_reason="合成负样本：语料无答案" if refusal else None,
                )
            )
    return tuple(specs)


def _h2kind_rows(
    specs: tuple[CaseSpec, ...], *, answered: bool = False
) -> dict[str, dict[str, Any]]:
    """逐题行：拒答题由产品回 not_found（真实形态；answered=True 时故意答 answer）。"""
    rows: dict[str, dict[str, Any]] = {}
    for spec in specs:
        if spec.expected_kind == "refusal" and not answered:
            product: dict[str, Any] = {"kind": "not_found", "text": "", "sources": []}
        elif spec.expected_kind == "conflict":
            product = {"kind": "conflict", "text": "两份资料不一致（合成）", "sources": []}
        else:
            product = {
                "kind": "answer",
                "text": f"资料写着：{H2KIND_VALUE}",
                "sources": [
                    {
                        "source_id": H2KIND_UNIT_ID,
                        "document_name": H2KIND_DOC_NAME,
                        "version_number": 1,
                        "status": "active",
                        "locator": {"sheet": "物品位置", "row": 8},
                    }
                ],
            }
        rows[spec.case_id] = {
            "case_id": spec.case_id,
            "status": "ok",
            "error_code": None,
            "planned_turns": 1,
            "turns": [
                {
                    "turn": 1,
                    "status": "ok",
                    "error_code": None,
                    "product": {**product, "trace_id": f"trace-{spec.case_id}"},
                }
            ],
        }
    return rows


def _h2kind_marks(
    specs: tuple[CaseSpec, ...],
    rows: dict[str, dict[str, Any]],
    *,
    compat_refusal_kind: bool,
) -> tuple[P2HoldoutCaseScore, ...]:
    """直接调共享 scorer 复现"改前/改后"口径：唯一变量就是 compat_refusal_kind。"""
    marks: list[P2HoldoutCaseScore] = []
    for spec in specs:
        row = rows[spec.case_id]
        outcome = normalize_product_outcome(
            row["turns"][-1],
            document_codes=H2KIND_DOCUMENT_CODES,
            source_index=H2KIND_SOURCE_INDEX,
        )
        result = score_case(
            spec,
            ResolvedGold(
                case_id=spec.case_id,
                requires_ocr=False,
                skipped=False,
                sources=(),
                unit_ids=(),
                relevant_unit_ids=(),
            ),
            outcome,
            cross_explicit_space=True,
            allowed_number_keys=citation_number_keys(outcome.citations),
            compat_refusal_kind=compat_refusal_kind,
        )
        marks.append(
            P2HoldoutCaseScore(
                case_id=spec.case_id,
                stratum=str(spec.stratum),
                status=CASE_STATUS_PASS if result.status == "pass" else CASE_STATUS_FAIL,
            )
        )
    return tuple(marks)


def _h2kind_production_marks(
    specs: tuple[CaseSpec, ...], rows: dict[str, dict[str, Any]]
) -> tuple[P2HoldoutCaseScore, ...]:
    marks, unclassified = p2_score_run.holdout_case_scores_from_rows(
        specs,
        rows,
        document_codes=H2KIND_DOCUMENT_CODES,
        source_index=H2KIND_SOURCE_INDEX,
    )
    assert unclassified == []
    return marks


def test_h2_expected_refusal_is_no_longer_a_structural_failure() -> None:
    """H2 上限不再是结构性 24/30：6 道 refusal 被产品拒答即计 pass（30/30）。"""
    specs = _h2kind_specs()
    rows = _h2kind_rows(specs)
    marks = _h2kind_production_marks(specs, rows)
    card = p2_score_run.aggregate_holdout_bundle(marks).to_dict()

    assert (card["total"], card["executed"], card["errors"]) == (30, 30, 0)
    assert (card["passed"], card["failed"]) == (30, 0)
    assert card["threshold_met"] is True
    assert "holdout_below_threshold" not in {block["code"] for block in card["blocks"]}

    # 修复前口径（同一批行，只关掉新开关）：6 道 refusal 结构性 fail → 24/30 封顶。
    before = _h2kind_marks(specs, rows, compat_refusal_kind=False)
    before_card = p2_score_run.aggregate_holdout_bundle(before).to_dict()
    assert (before_card["passed"], before_card["failed"]) == (24, 6)
    # 生产入口与"手动复现"逐题一致（差异只来自那一个开关）。
    assert [(item.case_id, item.status) for item in marks] == [
        (item.case_id, item.status) for item in _h2kind_marks(specs, rows, compat_refusal_kind=True)
    ]
    # 前后差异严格等于 6 道 refusal（不是把 30 题一起放宽）。
    before_by_id = {item.case_id: item.status for item in before}
    flipped = {
        item.case_id for item in marks if before_by_id[item.case_id] != item.status
    }
    refusal_ids = {spec.case_id for spec in specs if spec.expected_kind == "refusal"}
    assert len(refusal_ids) == 6
    assert flipped == refusal_ids
    assert all(before_by_id[case_id] == CASE_STATUS_FAIL for case_id in flipped)


def test_h2_expected_refusal_answered_wrongly_still_fails() -> None:
    """同一开关：应该拒答却作答 → 6 题仍 fail（refusal_expected 语义不变，不是凡拒答题都放过）。"""
    specs = _h2kind_specs()
    rows = _h2kind_rows(specs, answered=True)
    card = p2_score_run.aggregate_holdout_bundle(
        _h2kind_production_marks(specs, rows)
    ).to_dict()

    assert (card["total"], card["errors"]) == (30, 0)
    assert (card["passed"], card["failed"]) == (24, 6)
    assert "holdout_below_threshold" not in {block["code"] for block in card["blocks"]}

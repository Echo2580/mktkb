r"""P2-T207-FIX-H2SCORE-R1 独立验收探针（不复用开发测试夹具；零真实出站）。

用法（工作目录=仓库根）：
  .venv\Scripts\python.exe -X utf8 docs\reports\OBS-EVAL\P2\T207-FIX-H2SCORE-R1\evidence\verify\probe_independent.py

自建：合成封存 30 题 / 10-5-5-5-5 / 36 回合（Fernet key 现生成，全部写在系统 TEMP，仓外）；
会作答的 Mock 产品（含"全对"与"23 对 7 错"两套）；对照臂 = 关掉内存打分行登记。
不读 .env / 真实 H2 / key；不联网（Mock chat + 隔离应用；实测 outbound 计数会打印）。
产物只打印计数/稳定码/文件清单，不打印题干/答案正文。
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve()
ROOT = HERE.parents[7]
assert (ROOT / "backend" / "src").is_dir(), ROOT
sys.path.insert(0, str(ROOT / "backend" / "src"))

from cryptography.fernet import Fernet

from mktkb.evaluation import p2_dataset as p2d
from mktkb.evaluation import p2_runner as runner
from mktkb.evaluation import p2_score_run as score_run
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
    ERROR_HOLDOUT_DOCUMENT_CODE_UNMAPPED,
    ERROR_HOLDOUT_SCORECARD_LEAK,
    P2RunError,
    P2RunLedger,
    build_dry_run_authorization,
    run_p2,
)
from mktkb.evaluation.p2_scoring import P2HoldoutScorecard, aggregate_holdout, load_p2_gate_config
from mktkb.evaluation.product_adapter import (
    IngestSource,
    MockChatBackend,
    P2IngestPlan,
    P2RunDataset,
    ProductEvalAdapter,
    ProductTurn,
    case_questions,
)

FIX = ROOT / "fixtures" / "acceptance" / "normal"
D01 = FIX / "D01_物品位置表.xlsx"
D04 = FIX / "D04_活动策划流程.docx"

NOW = datetime(2026, 11, 11, 9, 0, tzinfo=timezone.utc)
NONCE = "ab" * 16

# 自建标记（与任何真实 H2 无关）：产物里出现即视为泄漏。
Q_TOKEN = "验收自建题干-8b41c7"
F_TOKEN = "验收自建追问-d2e9"
A_TOKEN = "验收自建参考答案-4f7a"
V_TOKEN = "验收自建金标值-乙-3c1d"
NOISE = "验收自建回答前缀："

LABEL_VERSION = "p2-holdout-verify-r1"
DATASET_VERSION = "P2-HOLDOUT-VERIFY-R1"
BUSINESS_DATE = "2026-10-28"
CREATED_UTC = "2026-11-10T12:00:00+00:00"
KEY_ID = "p2-holdout-verify"
PREFIX = "VFY"

STRATA = (
    ("paraphrase", 10),
    ("multi_turn", 5),
    ("negative", 5),
    ("stale_conflict", 5),
    ("cross_doc_security", 5),
)
TOTAL = sum(n for _s, n in STRATA)
#: 5 道多轮题各自的轮数（4x2 + 1x3 = 11 回合；25 + 11 = 36）。
MULTI_TURNS = (3, 2, 2, 2, 2)  # 11 回合
UNIT_ID = "7f0e5d3c-1111-4000-8000-00000000aa01"
WRONG_UNIT_ID = "7f0e5d3c-1111-4000-8000-00000000aa02"
UNIT_KEY = "sheet:物品位置:row:8"


def section(name: str) -> None:
    print()
    print("=== " + name + " ===")


def ok(label: str, condition: bool, detail: str = "") -> None:
    print(f"  [{'OK' if condition else 'MISMATCH'}] {label}{(' :: ' + detail) if detail else ''}")


# --------------------------------------------------------------------------- #
# 合成封存（自己写，不导入开发测试模块）
# --------------------------------------------------------------------------- #
def _question_rows() -> list[dict]:
    rows: list[dict] = []
    number = 0
    multi = 0
    for stratum, count in STRATA:
        for offset in range(count):
            number += 1
            if stratum == "multi_turn":
                turns = [f"{F_TOKEN} 第 {n} 轮" for n in range(1, MULTI_TURNS[multi] + 1)]
                multi += 1
                question = ""
            else:
                turns = []
                question = f"{Q_TOKEN} {stratum} {offset:02d}"
            rows.append(
                {
                    "case_id": f"{PREFIX}-{number:02d}",
                    "suite": "holdout",
                    "split": "holdout",
                    "stratum": stratum,
                    "business_date": BUSINESS_DATE,
                    "question": question,
                    "turns": turns,
                    "expected_kind": "not_found" if stratum == "negative" else "answer",
                    "should_refuse": stratum == "negative",
                    "requires_ocr": False,
                    "labeler": "verify",
                    "label_version": LABEL_VERSION,
                    "notes": "自建合成夹具",
                }
            )
    return rows


def _label_rows(rows: list[dict]) -> list[dict]:
    labels = []
    for row in rows:
        refuse = bool(row["should_refuse"])
        labels.append(
            {
                "case_id": row["case_id"],
                "expected_kind": row["expected_kind"],
                "expected_values": [] if refuse else [V_TOKEN],
                "expected_sources": (
                    [] if refuse else [{"doc_code": "D01", "unit_key": UNIT_KEY}]
                ),
                "relevant_units": (
                    []
                    if refuse
                    else [{"doc_code": "D01", "locator": {"sheet": "物品位置", "row": 8}}]
                ),
                "reference_answer": "" if refuse else f"{A_TOKEN} 自建参考答案",
                "should_refuse": refuse,
                "refusal_reason": "自建负样本：语料无答案" if refuse else None,
                "forbidden_values": ["自建诱饵值"],
                "forbidden_sources": [{"doc_code": "V01"}],
                "notes": "自建合成夹具",
            }
        )
    return labels


def _jsonl(rows: list[dict]) -> bytes:
    return ("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n").encode("utf-8")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


@dataclass
class Sealed:
    root: Path
    key_file: Path
    manifest_path: Path


def write_sealed(base: Path) -> Sealed:
    rows = _question_rows()
    labels = _label_rows(rows)
    key = Fernet.generate_key()
    fernet = Fernet(key)
    q_tok = fernet.encrypt(_jsonl(rows))
    l_tok = fernet.encrypt(_jsonl(labels))
    root = base / "sealed"
    root.mkdir(parents=True, exist_ok=True)
    (root / QUESTIONS_CIPHERTEXT_NAME).write_bytes(q_tok)
    (root / LABELS_CIPHERTEXT_NAME).write_bytes(l_tok)
    turns = [len(r["turns"]) if r["turns"] else 1 for r in rows]
    hist: dict[str, int] = {}
    for n in turns:
        hist[str(n)] = hist.get(str(n), 0) + 1
    manifest = {
        "schema_version": p2d.P2_MANIFEST_SCHEMA_VERSION,
        "dataset_version": DATASET_VERSION,
        "suite": p2d.P2_DATASET_SUITE,
        "label_version": LABEL_VERSION,
        "case_count": p2d.P2_CASE_COUNT,
        "strata": dict(p2d.P2_STRATA),
        "business_date": BUSINESS_DATE,
        "created_utc": CREATED_UTC,
        "author": "verify",
        "encryption": {"kind": "fernet", "key_id": KEY_ID},
        "questions_plaintext_sha256": _sha(_jsonl(rows)),
        "labels_plaintext_sha256": _sha(_jsonl(labels)),
        "questions_ciphertext_sha256": _sha(q_tok),
        "labels_ciphertext_sha256": _sha(l_tok),
        "turn_stats": {
            "total_turns": sum(turns),
            "max_turns_per_case": max(turns),
            "turn_histogram": {k: hist[k] for k in sorted(hist, key=int)},
        },
    }
    manifest_path = root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    keys = base / "keys"
    keys.mkdir(parents=True, exist_ok=True)
    key_file = keys / "v1.key"
    key_file.write_text(key.decode("ascii") + "\n", encoding="utf-8")
    return Sealed(root=root, key_file=key_file, manifest_path=manifest_path)


def load_dataset(sealed: Sealed) -> P2RunDataset:
    os.environ[HOLDOUT_ROOT_ENV] = str(sealed.root)
    os.environ[HOLDOUT_KEY_FILE_ENV] = str(sealed.key_file)
    return P2RunDataset.from_p2_dataset(
        load_p2_dataset(sealed.manifest_path, visibility="holdout")
    )


# --------------------------------------------------------------------------- #
# 计划 / 授权（库 API 自建）
# --------------------------------------------------------------------------- #
def price_profile() -> P2PriceProfile:
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


def make_plan(cases: tuple[CaseSpec, ...], plan_id: str = "p2-h2score-r1-verify") -> P2RunPlan:
    items = []
    for case in cases:
        for turn in range(1, len(case_questions(case)) + 1):
            items.append(
                P2RequestItem(
                    item_id=f"{case.case_id}:turn{turn}:answer",
                    operation="answer",
                    cost_center="answer_retrieval",
                    case_id=case.case_id,
                    turn=turn,
                    page=0,
                    requests=1,
                    price_profile=price_profile(),
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
        stage_limit_cny=15.0,
        max_requests=1000,
        cost_centers_cny={
            "answer_retrieval": 12.0,
            "ocr": 1.0,
            "judge": 1.0,
            "independent": 1.0,
        },
        items=tuple(items),
    )


def snapshot(plan: P2RunPlan) -> P2LedgerSnapshot:
    return P2LedgerSnapshot(
        schema_version=P2_LEDGER_SNAPSHOT_SCHEMA_VERSION,
        ledger_path="in-memory:verify",
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


def authorization(plan: P2RunPlan):
    pre = preflight_p2(plan, snapshot(plan))
    assert pre.ok, pre.reasons
    return build_dry_run_authorization(plan, pre, now=NOW, nonce=NONCE)


def ingest_plan() -> P2IngestPlan:
    return P2IngestPlan(
        sources=(IngestSource(path=D01), IngestSource(path=D04)), label="verify"
    )


# --------------------------------------------------------------------------- #
# 产品观测（Mock 作答）
# --------------------------------------------------------------------------- #
def product(
    question: str,
    *,
    kind: str = "answer",
    text: str = "",
    unit_id: str | None = UNIT_ID,
    unit_key: str = UNIT_KEY,
    status: str = "active",
    document_name: str = "D01_物品位置表.xlsx",
) -> ProductTurn:
    sources = ()
    evidence = ()
    ids = ()
    if unit_id is not None:
        sources = (
            {
                "source_id": unit_id,
                "document_name": document_name,
                "status": status,
            },
        )
        ids = (unit_id,)
        evidence = (
            {
                "unit_id": unit_id,
                "unit_key": unit_key,
                "locator": {"sheet": "物品位置", "row": 8},
                "verified": True,
            },
        )
    return ProductTurn(
        question_sha256=hashlib.sha256(question.encode("utf-8")).hexdigest(),
        question_chars=len(question),
        client_request_id="p2req-verify",
        http_status=200,
        kind=kind,
        text=text,
        message_id="p2msg-verify",
        request_id="p2res-verify",
        revision=1,
        error_code=None,
        retryable=False,
        source_ids=ids,
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


def answering_products(dataset: P2RunDataset, *, all_correct: bool) -> dict[str, ProductTurn]:
    """23 对 7 错（负样本照答 + 2 题引错单位）或 30 全对（负样本按 not_found 拒答）。"""
    wrong_units = {f"{PREFIX}-29", f"{PREFIX}-30"}
    products: dict[str, ProductTurn] = {}
    for case in dataset.cases:
        for question in case_questions(case):
            if case.stratum == "negative":
                if all_correct:
                    products[question] = product(question, kind="not_found", text="", unit_id=None)
                else:
                    products[question] = product(question, text=NOISE + V_TOKEN)
            elif (not all_correct) and case.case_id in wrong_units:
                products[question] = product(
                    question,
                    text=NOISE + V_TOKEN,
                    unit_id=WRONG_UNIT_ID,
                    unit_key="sheet:物品位置:row:99",
                )
            else:
                products[question] = product(question, text=NOISE + V_TOKEN)
    return products


@dataclass
class RunOutcome:
    card: dict
    run_dir: Path
    dataset: P2RunDataset
    captured: list[dict]
    summary: dict
    manifest: dict
    case_rows: list[dict]


async def run_holdout(
    base: Path, sealed: Sealed, *, all_correct: bool, record_rows: bool = True,
    approved: bool = False, out_name: str = "h2", drop_text: bool = False,
) -> RunOutcome:
    dataset = load_dataset(sealed)
    plan = make_plan(dataset.cases)
    adapter = ProductEvalAdapter(
        base / out_name,
        chat=MockChatBackend(),
        dataset=dataset,
        ingest_plan=ingest_plan(),
        purge_traces_on_close=True,
    )
    products = answering_products(dataset, all_correct=all_correct)

    async def _scripted(question, *, user_id, conversation_id, client_request_id):
        return products[str(question)]

    # 只替换"产品怎么答"；灌库/建会话/门序/产物/网络计量都走真实适配器。
    adapter.ask_turn = _scripted  # type: ignore[method-assign]
    captured: list[dict] = []
    original = P2RunLedger.record_scoring_case
    original_row = runner._scoring_case_row
    ledgers: list[P2RunLedger] = []

    def _record(self, row):  # noqa: ANN001 - 与真方法同签名
        captured.append(json.loads(json.dumps(row, ensure_ascii=False)))
        ledgers.append(self)
        if record_rows:
            original(self, row)

    if drop_text:
        def _drop(case_row, products):  # noqa: ANN001 - 与真函数同签名
            row = original_row(case_row, products)
            for item in row.get("turns") or ():
                product_payload = item.get("product")
                if isinstance(product_payload, dict):
                    product_payload.pop("text", None)
            return row

        runner._scoring_case_row = _drop

    P2RunLedger.record_scoring_case = _record
    try:
        result = await run_p2(
            plan,
            adapter=adapter,
            authorization=authorization(plan),
            gate_config=SimpleNamespace(status="approved") if approved else load_p2_gate_config(),
            now=NOW,
        )
    finally:
        P2RunLedger.record_scoring_case = original
        runner._scoring_case_row = original_row
        await adapter.close()
    assert result.status == "succeeded", result.as_dict()
    run_dir = adapter.paths.run_dir
    card = json.loads((run_dir / "holdout_scorecard.json").read_text(encoding="utf-8"))
    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    case_rows = list(ledgers[-1].cases) if ledgers else []
    return RunOutcome(card=card, run_dir=run_dir, dataset=dataset, captured=captured,
                      summary=summary, manifest=manifest, case_rows=case_rows)


def secrets_of(dataset: P2RunDataset) -> list[str]:
    values = [case.case_id for case in dataset.cases]
    for case in dataset.cases:
        if case.question:
            values.append(case.question)
        for turn in case.turns or ():
            for key in ("question", "text"):
                item = turn.get(key) if isinstance(turn, dict) else None
                if isinstance(item, str) and item:
                    values.append(item)
        if case.reference_answer:
            values.append(case.reference_answer)
    values += [Q_TOKEN, F_TOKEN, A_TOKEN, V_TOKEN, NOISE]
    return values


def scan_tree(root: Path, secrets: list[str]) -> tuple[int, list[str]]:
    hits = 0
    files = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        files.append(path.relative_to(root).as_posix() + f"({path.stat().st_size}B)")
        try:
            raw = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            raw = path.read_bytes().decode("utf-8", "ignore")
        for secret in secrets:
            if secret and secret in raw:
                hits += 1
    return hits, files


def print_card(tag: str, card: dict) -> None:
    strata = {name: c["passed"] for name, c in sorted(card["by_stratum"].items())}
    print(
        f"  {tag}: total={card['total']} executed={card['executed']} "
        f"passed={card['passed']} failed={card['failed']} errors={card['errors']} "
        f"threshold_met={card['threshold_met']} release_ready={card['release_ready']} "
        f"hard_failures={card['hard_failures']} real_calls={card['real_calls']} "
        f"execution_mode={card['execution_mode']}"
    )
    print(f"    by_stratum(passed)={strata}")
    print(f"    blocks={[b['code'] for b in card['blocks']]}")


# --------------------------------------------------------------------------- #
# 1. B1 单变量（评分接缝：唯一变量 = product.text）
# --------------------------------------------------------------------------- #
def single_case() -> CaseSpec:
    return CaseSpec(
        case_id=f"{PREFIX}-01",
        suite="p2-holdout",
        split="holdout",
        stratum="paraphrase",
        business_date=BUSINESS_DATE,
        question=f"{Q_TOKEN} 单变量",
        expected_values=(V_TOKEN,),
        expected_sources=({"doc_code": "D01", "unit_key": UNIT_KEY},),
        reference_answer=f"{A_TOKEN} 单变量参考",
        label_version=LABEL_VERSION,
    )


def one_case_row(case: CaseSpec, product_payload: dict, *, run_id: str = "p2run-verify") -> dict:
    return {
        "schema_version": "p2-run-case/v0.1",
        "run_id": run_id,
        "case_id": case.case_id,
        "suite": case.suite,
        "stratum": case.stratum,
        "visibility": "holdout",
        "conversation_id": "conv-verify",
        "turns": [
            {
                "turn": 1,
                "item_id": f"{case.case_id}:turn1:answer",
                "status": "ok",
                "error_code": None,
                "product": dict(product_payload),
            }
        ],
        "status": "ok",
        "error_code": None,
        "planned_turns": 1,
        "turns_executed": 1,
    }


def seam_card(case: CaseSpec, row: dict) -> dict:
    ledger = P2RunLedger(
        run_id="p2run-verify",
        plan_id="p2-h2score-r1-verify",
        plan_sha256="a" * 64,
        execution="dry_run",
        production_ready=False,
    )
    ledger.record_scoring_case(row)
    dataset = P2RunDataset(
        visibility="holdout",
        cases=(case,),
        identity={
            "dataset_version": DATASET_VERSION,
            "label_version": LABEL_VERSION,
            "suite": "p2-holdout",
            "manifest_sha256": "b" * 64,
            "case_count": 1,
            "strata": {case.stratum: 1},
        },
    )
    return runner._holdout_scorecard(
        ledger,
        dataset,
        ingest_plan=ingest_plan(),
        execution="dry_run",
        real_calls=0,
        binding={},
        gate_config=None,
    )


def check_b1_single_variable() -> None:
    section("B1-a 评分接缝单变量（同一 ProductTurn，只切换 product.text）")
    case = single_case()
    turn = product(case.question, text=NOISE + V_TOKEN)
    with_text = seam_card(case, one_case_row(case, turn.as_dict(include_text=True)))
    without = seam_card(case, one_case_row(case, turn.as_dict(include_text=False)))
    print(f"  带 text: passed={with_text['passed']} failed={with_text['failed']} errors={with_text['errors']}")
    print(f"  去 text: passed={without['passed']} failed={without['failed']} errors={without['errors']}")
    ok("带 text → pass、去 text → fail（唯一变量=正文）",
       (with_text["passed"], with_text["failed"]) == (1, 0)
       and (without["passed"], without["failed"]) == (0, 1))

    # 打分行与公开 cases.jsonl 行同形：_scoring_case_row 补回的 product 键集 = as_dict(include_text=True)
    disk_row = one_case_row(case, turn.as_dict(include_text=False))
    rebuilt = runner._scoring_case_row(disk_row, {1: turn})
    rebuilt_keys = set(rebuilt["turns"][0]["product"])
    public_keys = set(turn.as_dict(include_text=True))
    ok("_scoring_case_row 的 product 键集与公开行同形（含 text/sources/evidence）",
       rebuilt_keys == public_keys and "text" in rebuilt_keys and
       rebuilt["turns"][0]["product"]["text"] == NOISE + V_TOKEN,
       f"keys={len(rebuilt_keys)}")


# --------------------------------------------------------------------------- #
# 2. B1 端到端三臂
# --------------------------------------------------------------------------- #
async def check_b1_e2e(base: Path) -> tuple[RunOutcome, RunOutcome, RunOutcome]:
    section("B1-b 端到端：自建合成封存 30 题/36 回合 + 会作答 Mock")
    sealed = write_sealed(base)
    dataset_probe = load_dataset(sealed)
    print(f"  数据集：cases={len(dataset_probe.cases)} "
          f"turns={sum(len(case_questions(c)) for c in dataset_probe.cases)} "
          f"strata={dict(dataset_probe.identity['strata'])}")
    arm_23 = await run_holdout(base, sealed, all_correct=False, out_name="arm23")
    print_card("23 对 7 错（修复后）", arm_23.card)
    hits, files = scan_tree(arm_23.run_dir, secrets_of(arm_23.dataset))
    print(f"    run_dir files={files}")
    print(f"    run_dir 受限内容命中={hits} cases.jsonl={(arm_23.run_dir/'cases.jsonl').exists()} "
          f"requests.jsonl={(arm_23.run_dir/'requests.jsonl').exists()}")
    print(f"    summary.network.available={arm_23.summary['network']['available']} "
          f"outbound_attempts={arm_23.summary['network']['outbound_attempts']}")
    ok("passed=23/failed=7/errors=0", (arm_23.card["passed"], arm_23.card["failed"], arm_23.card["errors"]) == (23, 7, 0))
    ok("分层分布 paraphrase10/multi_turn5/stale_conflict5/cross_doc_security3/negative0",
       {k: v["passed"] for k, v in arm_23.card["by_stratum"].items()} ==
       {"paraphrase": 10, "multi_turn": 5, "negative": 0, "stale_conflict": 5, "cross_doc_security": 3})
    ok("23<24 → threshold_met=false（随观测值，不是结构性）", arm_23.card["threshold_met"] is False)
    ok("run_dir 无逐题行/正文且零出站", hits == 0 and
       not (arm_23.run_dir / "cases.jsonl").exists() and
       arm_23.summary["network"]["outbound_attempts"] == 0 and arm_23.card["real_calls"] == 0)
    ok("run_id/config_hash/detail_export 与 run_manifest 一致",
       arm_23.card["run_id"] == arm_23.manifest["run_id"]
       and arm_23.card["config_hash"] == arm_23.manifest["config_hash"]
       and arm_23.card["detail_export"] is False)
    disk_texts = [
        (t.get("product") or {}).get("text")
        for row in arm_23.case_rows for t in row.get("turns") or ()
    ]
    ok("ledger.cases（落盘口径）里的 product 一律没有正文",
       bool(disk_texts) and all(value is None for value in disk_texts), f"rows={len(arm_23.case_rows)}")
    out_hits, out_files = scan_tree(base / "arm23", secrets_of(arm_23.dataset))
    print(f"    适配器 out_dir 全文命中={out_hits}（run_dir 外，含 DB/trace 残留；文件数={len(out_files)}）")
    ok("内存打分行带正文（captured rows）",
       len(arm_23.captured) == 30 and
       all(t["product"].get("text") == NOISE + V_TOKEN or t["product"].get("kind") == "not_found"
           for r in arm_23.captured for t in r["turns"]))

    # 全对臂：证明 threshold_met/release_ready 能随观测值转为 true（gate 已批 + 30 pass）
    arm_all = await run_holdout(base, sealed, all_correct=True, approved=True, out_name="armall")
    print_card("30 全对 + gate approved", arm_all.card)
    hits_all, _ = scan_tree(arm_all.run_dir, secrets_of(arm_all.dataset))
    ok("30 全对 → passed=30/threshold_met=true/release_ready=true",
       arm_all.card["passed"] == 30 and arm_all.card["threshold_met"] is True
       and arm_all.card["release_ready"] is True)
    ok("全对臂 run_dir 仍无受限内容", hits_all == 0)

    # 对照臂 A：同批观测但内存打分行不登记（回到"产品观测只按落盘口径"）
    arm0 = await run_holdout(base, sealed, all_correct=False, record_rows=False, out_name="arm0")
    print_card("23 对 7 错，但内存打分行不登记（对照臂 A）", arm0.card)
    ok("对照臂 A passed=0/failed=30（正文是唯一变量）",
       (arm0.card["passed"], arm0.card["failed"], arm0.card["errors"]) == (0, 30, 0) and len(arm0.captured) == 30)

    # 对照臂 B：打分行照登记、只把 product.text 去掉（=修复前口径，复现开发证据的说法）
    arm_drop = await run_holdout(base, sealed, all_correct=False, out_name="armdrop", drop_text=True)
    print_card("23 对 7 错，仅打分行去正文（对照臂 B）", arm_drop.card)
    ok("对照臂 B passed=0/failed=30",
       (arm_drop.card["passed"], arm_drop.card["failed"], arm_drop.card["errors"]) == (0, 30, 0))
    return arm_23, arm_all, arm0


# --------------------------------------------------------------------------- #
# 3. B2 结构问题不计 pass
# --------------------------------------------------------------------------- #
def check_b2(base: Path) -> None:
    section("B2 结构类来源问题：不计 pass + unclassified block")
    case = single_case()
    turn = product(case.question, text=NOISE + V_TOKEN)
    active = seam_card(case, one_case_row(case, turn.as_dict(include_text=True)))
    ok("active 来源：pass", active["passed"] == 1 and active["errors"] == 0)

    stale_turn = product(case.question, text=NOISE + V_TOKEN, status="superseded")
    stale = seam_card(case, one_case_row(case, stale_turn.as_dict(include_text=True)))
    blocks = {b["code"]: b for b in stale["blocks"]}
    unc = blocks.get("holdout_hard_failure_unclassified")
    print(f"  superseded: passed={stale['passed']} failed={stale['failed']} errors={stale['errors']} "
          f"hard_failures={stale['hard_failures']} evidence={None if unc is None else unc['evidence']}")
    ok("superseded（source_not_active）→ error、不计 pass、hard_failures=0、owner=sealed-labels",
       stale["passed"] == 0 and stale["errors"] == 1 and unc is not None
       and unc["evidence"] == {"codes": ["source_not_active"], "counted_as": "error",
                               "hard_failures_owner": "sealed-labels"}
       and stale["hard_failures"] == 0)

    # 被禁资料（forbidden_sources）：语料里有 V01（映射可达），产品引用了它 →
    # 结构隔离不报（V01 在 allowed 内），由打分侧 source_forbidden 判 fail：仍不计 pass。
    forbidden_case = CaseSpec(
        case_id=f"{PREFIX}-77",
        suite="p2-holdout",
        split="holdout",
        stratum="cross_doc_security",
        business_date=BUSINESS_DATE,
        question=f"{Q_TOKEN} 禁用来源",
        expected_values=(V_TOKEN,),
        expected_sources=({"doc_code": "V01", "unit_key": UNIT_KEY},),
        relevant_units=({"doc_code": "V01", "locator": {"sheet": "物品位置", "row": 8}},),
        reference_answer=f"{A_TOKEN} 禁用来源参考",
        forbidden_sources=({"doc_code": "V01"},),
        label_version=LABEL_VERSION,
    )
    forbidden_turn = product(
        forbidden_case.question, text=NOISE + V_TOKEN,
        document_name="V01_临时物料位置通知.pdf",
    )

    class _Src:
        def __init__(self, path: str) -> None:
            self.path = Path(path)
            self.name = None
            self.document_ref = None

    class _Plan:
        def __init__(self, *paths: str) -> None:
            self.sources = tuple(_Src(path) for path in paths)

    forbidden_plan = _Plan(
        "fixtures/acceptance/normal/D01_物品位置表.xlsx",
        "fixtures/acceptance/normal/D04_活动策划流程.docx",
        "fixtures/acceptance/normal/V01_临时物料位置通知.pdf",
    )
    ledger = P2RunLedger(run_id="p2run-verify", plan_id="p2-plan", plan_sha256="a" * 64,
                         execution="dry_run", production_ready=False)
    ledger.record_scoring_case(
        one_case_row(forbidden_case, forbidden_turn.as_dict(include_text=True))
    )
    forbidden_dataset = P2RunDataset(
        visibility="holdout", cases=(forbidden_case,),
        identity={"dataset_version": DATASET_VERSION, "label_version": LABEL_VERSION,
                  "suite": "p2-holdout", "manifest_sha256": "b" * 64, "case_count": 1,
                  "strata": {"cross_doc_security": 1}},
    )
    forbidden_card = runner._holdout_scorecard(
        ledger, forbidden_dataset, ingest_plan=forbidden_plan, execution="dry_run",
        real_calls=0, binding={}, gate_config=None,
    )
    print(f"  forbidden_sources（引用 V01）: passed={forbidden_card['passed']} "
          f"failed={forbidden_card['failed']} errors={forbidden_card['errors']} "
          f"blocks={[b['code'] for b in forbidden_card['blocks']]}")
    ok("引用 forbidden_sources 的资料 → 不计 pass（source_forbidden 判 fail）",
       forbidden_card["passed"] == 0
       and forbidden_card["failed"] + forbidden_card["errors"] == 1)

    # 另三类结构码：在 holdout_case_scores_from_rows 层逐码验证"pass → error + 未分类"
    from mktkb.evaluation.p2_scoring import P2CaseScore, P2IsolationIssue, P2ScoredCase
    import mktkb.evaluation.p2_score_run as srun

    for code in sorted(srun.HOLDOUT_STRUCTURAL_ISSUE_CODES):
        original = srun.score_public_case
        def _fake(case_arg, row_arg, **kwargs):  # noqa: ANN001
            return P2ScoredCase(score=P2CaseScore(
                case_id=case_arg.case_id, suite=case_arg.suite, stratum=case_arg.stratum,
                requires_ocr=False, planned_turns=1, executed_turns=1,
                status="pass", issues=(P2IsolationIssue(code, case_arg.case_id),)))
        srun.score_public_case = _fake
        try:
            marks, unclassified = srun.holdout_case_scores_from_rows(
                (case,), {case.case_id: one_case_row(case, turn.as_dict(include_text=True))},
                document_codes={"D01_物品位置表.xlsx": "D01"}, execution_mode="local_mock",
            )
        finally:
            srun.score_public_case = original
        ok(f"{code}：pass 降为 error + 未分类清单",
           marks[0].status == "error" and unclassified == [code])

    # 30 题里 1 题引用 superseded、其余全对（负样本按 not_found 拒答）：
    # 29 pass / 1 error / hard_failures=0 / threshold_met=true（29>=24）/ release_ready=false
    sealed = write_sealed(base / "b2")
    dataset = load_dataset(sealed)
    rows = {}
    for item_case in dataset.cases:
        questions = case_questions(item_case)
        if item_case.stratum == "negative":
            turn = product(questions[0], kind="not_found", text="", unit_id=None)
        else:
            status = "superseded" if item_case.case_id == f"{PREFIX}-21" else "active"
            turn = product(questions[0], text=NOISE + V_TOKEN, status=status)
        payload = turn.as_dict(include_text=True)
        turns = [
            {"turn": i, "item_id": f"{item_case.case_id}:turn{i}:answer", "status": "ok",
             "error_code": None, "product": payload}
            for i in range(1, len(questions) + 1)
        ]
        rows[item_case.case_id] = {
            "schema_version": "p2-run-case/v0.1", "run_id": "p2run-verify",
            "case_id": item_case.case_id, "suite": item_case.suite,
            "stratum": item_case.stratum, "visibility": "holdout", "conversation_id": "conv",
            "turns": turns, "status": "ok", "error_code": None,
            "planned_turns": len(turns), "turns_executed": len(turns),
        }
    ledger = P2RunLedger(run_id="p2run-verify", plan_id="p2-h2score-r1-verify",
                         plan_sha256="a" * 64, execution="dry_run", production_ready=False)
    for row in rows.values():
        ledger.record_scoring_case(row)
    card = runner._holdout_scorecard(
        ledger, dataset, ingest_plan=ingest_plan(), execution="dry_run", real_calls=0,
        binding={}, gate_config=SimpleNamespace(status="approved"),
    )
    print_card("30 题含 1 题 superseded（gate approved）", card)
    ok("29 pass / 1 error / hard_failures=0 / threshold_met=true / release_ready=false",
       (card["passed"], card["failed"], card["errors"], card["hard_failures"],
        card["threshold_met"], card["release_ready"]) == (29, 0, 1, 0, True, False))

    # 不可达性记录：本包里 source_outside_run / source_forbidden_document 在 runner 路径不可达
    print("  说明：runner 路径 allowed=全部已映射代号、forbidden 集合未传入；"
          "未映射文档名会以 source_document_unmapped 走 holdout_case_unscorable(error)，仍不计 pass")


# --------------------------------------------------------------------------- #
# 3b. 执行期风险：负样本 expected_kind 与产品 kind 的严格比较
# --------------------------------------------------------------------------- #
def check_negative_kind() -> None:
    section("执行期风险：expected_kind='refusal' 与产品 not_found/no_answer 的严格比较")
    case = CaseSpec(
        case_id=f"{PREFIX}-16",
        suite="p2-holdout",
        split="holdout",
        stratum="negative",
        business_date=BUSINESS_DATE,
        question=f"{Q_TOKEN} 负样本",
        expected_kind="refusal",
        should_refuse=True,
        refusal_reason="语料无答案",
        label_version=LABEL_VERSION,
    )
    results = {}
    for kind in ("not_found", "no_answer", "refusal", "answer"):
        turn = product(case.question, kind=kind, text="", unit_id=None)
        card = seam_card(case, one_case_row(case, turn.as_dict(include_text=True)))
        results[kind] = (card["passed"], card["failed"], card["errors"])
        print(f"  产品 kind={kind:10s}: passed={card['passed']} failed={card['failed']} errors={card['errors']}")
    ok("产品只会回 not_found/no_answer（service.py 把 no_answer 归一成 not_found）；"
       "expected_kind='refusal' 时两者都 fail，只有字面 'refusal' 才 pass",
       results["not_found"][0] == 0 and results["no_answer"][0] == 0
       and results["refusal"][0] == 1)
    print("    含义：若封存 H2 负样本用 expected_kind='refusal'，5 道负样本结构性 fail，"
          "卡上限 25/30，阈值 24 实际要求 24/25 答案题（执行期必须核对 labels）")


# --------------------------------------------------------------------------- #
# 4. B3 泄漏审计矩阵
# --------------------------------------------------------------------------- #
def check_b3() -> None:
    section("B3 泄漏审计：多轮题面 / 短题干 / 参考答案 / 干净卡")
    multi = CaseSpec(
        case_id=f"{PREFIX}-88",
        suite="p2-holdout",
        split="holdout",
        stratum="multi_turn",
        business_date=BUSINESS_DATE,
        question="",
        turns=({"question": "退货"}, {"question": "这个月物料还剩多少"}),
        reference_answer="验收参考乙",
        label_version=LABEL_VERSION,
    )
    dataset = P2RunDataset(
        visibility="holdout",
        cases=(multi,),
        identity={"dataset_version": DATASET_VERSION, "label_version": LABEL_VERSION,
                  "suite": "p2-holdout", "manifest_sha256": "b" * 64, "case_count": 1,
                  "strata": {"multi_turn": 1}},
    )
    probes = [
        ("第 1 回合题面（2 字）", {"blocks": [{"code": "x", "detail": "退货"}]}, True),
        ("第 2 回合题面（9 字）", {"blocks": [{"code": "x", "detail": "这个月物料还剩多少"}]}, True),
        ("参考答案（5 字）", {"blocks": [{"code": "x", "detail": "验收参考乙"}]}, True),
        ("case_id 子串", {"blocks": [{"code": "x", "detail": f"{PREFIX}-88"}]}, True),
        ("明细字段名", {"blocks": [{"code": "x", "question": "?"}]}, True),
        ("干净卡（只有计数/稳定码）", {"total": 30, "passed": 23, "blocks": [{"code": "holdout_below_threshold"}]}, False),
    ]
    for label, payload, expect in probes:
        try:
            runner._assert_holdout_scorecard_payload(payload, dataset)
            caught = False
        except Exception as exc:  # noqa: BLE001
            caught = getattr(exc, "code", None) == ERROR_HOLDOUT_SCORECARD_LEAK
        ok(f"{label}：命中={caught}（期望 {expect}）", caught == expect)
    print(f"  needle 阈值={runner._HOLDOUT_LEAK_MIN_NEEDLE}（<2 字不扫）")

    # 1 字题面：按设计不报（文档口径），但要显式记录
    one = CaseSpec(
        case_id=f"{PREFIX}-89", suite="p2-holdout", split="holdout", stratum="paraphrase",
        business_date=BUSINESS_DATE, question="退", reference_answer="", label_version=LABEL_VERSION,
    )
    one_ds = P2RunDataset(
        visibility="holdout", cases=(one,),
        identity={"dataset_version": DATASET_VERSION, "label_version": LABEL_VERSION,
                  "suite": "p2-holdout", "manifest_sha256": "b" * 64, "case_count": 1,
                  "strata": {"paraphrase": 1}},
    )
    try:
        runner._assert_holdout_scorecard_payload({"blocks": [{"code": "x", "detail": "退"}]}, one_ds)
        caught = False
    except Exception as exc:  # noqa: BLE001
        caught = True
    ok("1 字题面不扫（阈值行为与文档一致）", caught is False)

    # 多轮题面出现在**真实卡**上：产物降级为全 error + 稳定 block，且卡内无题面
    payload = {"total": 1, "executed": 0, "errors": 1, "passed": 0, "failed": 0,
               "hard_failures": 0, "hard_failures_by_kind": {}, "by_stratum": {},
               "min_pass": 24, "hard_failures_max": 0, "thresholds_approved": False,
               "detail_export": False, "blocks": [{"code": "x", "detail": "退货", "severity": "unknown"}],
               "release_ready": False, "execution_mode": "local_mock", "real_calls": 0,
               "run_id": "r", "config_hash": None, "schema_version": "mktkb.p2.scoring.v0.1"}
    try:
        runner._assert_holdout_scorecard_payload(payload, dataset)
        caught = False
    except Exception as exc:  # noqa: BLE001
        caught = getattr(exc, "code", None) == ERROR_HOLDOUT_SCORECARD_LEAK
    ok("真实卡形态（多轮题面进 block.detail）→ 判泄漏", caught is True)


def check_audit_collision() -> None:
    section("限制：题面与 schema 固定词重合时的审计行为（fail-closed，不写泄漏卡）")
    case = CaseSpec(
        case_id=f"{PREFIX}-90", suite="p2-holdout", split="holdout", stratum="paraphrase",
        business_date=BUSINESS_DATE, question="passed", reference_answer="",
        label_version=LABEL_VERSION,
    )
    dataset = P2RunDataset(
        visibility="holdout", cases=(case,),
        identity={"dataset_version": DATASET_VERSION, "label_version": LABEL_VERSION,
                  "suite": "p2-holdout", "manifest_sha256": "b" * 64, "case_count": 1,
                  "strata": {"paraphrase": 1}},
    )
    ledger = P2RunLedger(run_id="p2run-verify", plan_id="p2-plan", plan_sha256="a" * 64,
                         execution="dry_run", production_ready=False)
    try:
        payload = runner._holdout_scorecard_artifact(
            ledger, dataset, ingest_plan=ingest_plan(), execution="dry_run", real_calls=0,
            binding={}, gate_config=None,
        )
        raised = False
    except Exception as exc:  # noqa: BLE001
        raised = getattr(exc, "code", None) == ERROR_HOLDOUT_SCORECARD_LEAK
    ok("ASCII 题面 'passed' 与 schema 键重合 → 二次审计仍命中即抛错（宁可不写，不写泄漏卡）",
       raised)
    print("    说明：中文题面撞不上固定英文键；这是 2 字阈值的子串审计在 ASCII 题面上的边界")


# --------------------------------------------------------------------------- #
# 5. N1/N2/N4 + 公开 run
# --------------------------------------------------------------------------- #
def check_n_items(base: Path) -> None:
    section("N1/N2/N4 + 公开 run 不写卡")
    sealed = write_sealed(base / "n1")
    dataset = load_dataset(sealed)
    print(f"  N2 _scorecard_real_calls(None)={runner._scorecard_real_calls(None)} "
          f"(7,outbound=7)={runner._scorecard_real_calls((7, {'outbound_attempts': 7}))}")
    ok("N2 与 p2-score 同口径（实测出站尝试数）",
       runner._scorecard_real_calls(None) == 0 and
       runner._scorecard_real_calls((7, {"outbound_attempts": 7})) == 7)

    original = runner._aggregate_marks
    runner._aggregate_marks = lambda *a, **k: {"blocks": [{"code": "x", "detail": dataset.cases[0].case_id}]}
    try:
        payload = runner._holdout_scorecard_artifact(
            P2RunLedger(run_id="p2run-verify", plan_id="p2-plan", plan_sha256="a" * 64,
                        execution="dry_run", production_ready=False),
            dataset, ingest_plan=ingest_plan(), execution="dry_run", real_calls=0,
            binding={}, gate_config=None,
        )
    finally:
        runner._aggregate_marks = original
    raw = json.dumps(payload, ensure_ascii=False)
    leak = any(case.case_id in raw for case in dataset.cases)
    print(f"  N1 聚合器级泄漏：total={payload['total']} passed={payload['passed']} "
          f"errors={payload['errors']} blocks={[b['code'] for b in payload['blocks']]} leak={leak}")
    ok("N1 兜底卡写出且不含 case_id（全 error + 稳定 block）",
       payload["total"] == 30 and payload["passed"] == 0 and payload["errors"] == 30
       and [b["code"] for b in payload["blocks"]] == [ERROR_HOLDOUT_SCORECARD_LEAK] and not leak)

    ledger = P2RunLedger(run_id="p2run-verify", plan_id="p2-plan", plan_sha256="a" * 64,
                         execution="dry_run", production_ready=False)
    card = runner._holdout_scorecard(ledger, dataset, ingest_plan=None, execution="dry_run",
                                     real_calls=0, binding={}, gate_config=None)
    codes = [b["code"] for b in card["blocks"]]
    ok("N4 无 ingest plan → 只一条 unmapped block",
       codes.count(ERROR_HOLDOUT_DOCUMENT_CODE_UNMAPPED) == 1,
       f"codes={codes}")


async def check_public_run(base: Path) -> None:
    section("公开 run 不写 / 清理 scorecard")
    sealed = write_sealed(base / "public")
    holdout = load_dataset(sealed)
    cases = holdout.cases[:2]
    dataset = P2RunDataset(
        visibility="public", cases=cases,
        identity={"dataset_version": DATASET_VERSION, "label_version": LABEL_VERSION,
                  "suite": "p2-holdout", "manifest_sha256": "b" * 64, "case_count": len(cases),
                  "strata": {"paraphrase": 2}},
    )
    plan = make_plan(dataset.cases, plan_id="p2-public-verify")
    adapter = ProductEvalAdapter(
        base / "public-run", chat=MockChatBackend(), dataset=dataset,
        ingest_plan=ingest_plan(),
    )
    run_dir = adapter.paths.run_dir
    run_dir.mkdir(parents=True, exist_ok=True)
    for stale in ("holdout_scorecard.json", "holdout_aggregate.json"):
        (run_dir / stale).write_text("{}\n", encoding="utf-8")
    try:
        result = await run_p2(plan, adapter=adapter, authorization=authorization(plan), now=NOW)
    finally:
        await adapter.close()
    print(f"  status={result.status} files={[p.name for p in sorted(run_dir.iterdir())]}")
    ok("公开 run 有 cases.jsonl 且无 holdout_scorecard/aggregate",
       (run_dir / "cases.jsonl").is_file()
       and not (run_dir / "holdout_scorecard.json").exists()
       and not (run_dir / "holdout_aggregate.json").exists())


# --------------------------------------------------------------------------- #
# 6. 与 p2-score 聚合口径对照
# --------------------------------------------------------------------------- #
def check_parity(arm: RunOutcome) -> None:
    section("语义对照：run 卡 vs p2-score 同口径聚合（同一批逐题行）")
    codes = runner.holdout_document_codes(ingest_plan())
    rows = {row["case_id"]: row for row in arm.captured}
    index = score_run.source_index_from_rows(rows)
    marks, unclassified = score_run.holdout_case_scores_from_rows(
        arm.dataset.cases, rows, document_codes=codes, source_index=index,
        allowed_doc_codes=set(codes.values()), execution_mode="local_mock", real_calls=0,
    )
    peer = score_run.aggregate_holdout_bundle(
        marks, expected_strata=arm.dataset.identity["strata"], thresholds_approved=False,
        execution_mode="local_mock", real_calls=0, run_id=arm.card["run_id"],
        config_hash=arm.card["config_hash"],
    ).to_dict()
    print(f"  peer: {({k: peer[k] for k in ('total','executed','passed','failed','errors','hard_failures','threshold_met','release_ready')})}")
    print(f"  run : {({k: arm.card[k] for k in ('total','executed','passed','failed','errors','hard_failures','threshold_met','release_ready')})}")
    diffs = []
    for key in ("total", "executed", "errors", "passed", "failed", "min_pass", "threshold_met",
                "hard_failures", "hard_failures_max", "hard_failures_by_kind", "by_stratum",
                "thresholds_approved", "detail_export", "release_ready", "execution_mode",
                "real_calls", "run_id", "config_hash"):
        if key not in arm.card:
            diffs.append(f"missing:{key}")
        elif arm.card[key] != peer[key]:
            diffs.append(f"{key}: run={arm.card[key]!r} peer={peer[key]!r}")
    print(f"  field_diffs={diffs}")
    print(f"  run key set == P2HoldoutScorecard.to_dict? {set(arm.card) == set(peer)}")
    print(f"  unclassified={sorted(set(unclassified))}")
    expected_keys = set(P2HoldoutScorecard.__dataclass_fields__) | {
        "schema_version", "threshold_met", "detail_export", "release_ready"}
    ok("字段集与 P2HoldoutScorecard schema 一致（无额外/缺失）",
       set(arm.card) == set(peer) == expected_keys)
    ok("同批逐题行数值逐字段一致（N3 差异仅 thresholds_approved 来源，已按 false 对齐）", not diffs)


# --------------------------------------------------------------------------- #
# 7. 账本 / 预算 / GO + 零出站（只读）
# --------------------------------------------------------------------------- #
def check_ledger() -> None:
    section("固定账本 / 预算 / GO（只读；到达=离开）")
    for rel in ("docs/evidence/LOCAL-R1-20261101/budget/live-ledger.jsonl",
                "docs/evidence/LOCAL-R1-20261101/budget/budget.json",
                "docs/evidence/LOCAL-R1-20261101/PM/P2-LIVE-GO.json"):
        path = ROOT / rel
        raw = path.read_bytes()
        print(f"  {rel}: bytes={len(raw)} newlines={raw.count(bytes([10]))} "
              f"splitlines={len(raw.decode('utf-8').splitlines())} "
              f"sha256={hashlib.sha256(raw).hexdigest()} "
              f"mtime={datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(timespec='milliseconds')}")


# --------------------------------------------------------------------------- #
def main() -> None:
    print(f"repo={ROOT}")
    base = Path(tempfile.mkdtemp(prefix="p2vfy-"))
    print(f"temp={base}")
    check_b1_single_variable()
    arm = asyncio.run(check_b1_e2e(base))
    check_b2(base / "b2run")
    check_negative_kind()
    check_b3()
    check_audit_collision()
    check_n_items(base / "nitems")
    asyncio.run(check_public_run(base / "pubbase"))
    check_parity(arm[0])
    check_ledger()
    print("\nDONE")


if __name__ == "__main__":
    main()

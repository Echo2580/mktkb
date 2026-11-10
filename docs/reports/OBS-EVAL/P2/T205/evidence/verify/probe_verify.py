# -*- coding: utf-8 -*-
"""P2-T205 独立验收探针（验收助手自写；不调用开发用例里的 helper）。

A 分母手算：直接读 fixtures/acceptance/questions.json 的 category 现算，再与 p2_scoring 常量比；
  H2 只读 manifest 元数据（case_count / strata / 密文 hash），不读题干与答案。
B 配置：v0.1 / v0.2 / v0.3 加载；v0.3 = unapproved；改 p2_standards 必被拒；提案不得覆盖 v0.3。
C 分母口径：OCR 跳过 / error / 未执行 / 精确失手 / 多题 / 缺题 都不放行。
D evaluate_p2_gate 的缺失与全 not_applicable / not_evaluated 分支（开发用例未直测的路径）。
E 产品侧公开财务反例 4 个 + 正向 2 个（6 自然日 / 多轮 3 工作日）+ 来源权限；全 Mock，实测出站 0。

不读 .env / H1 / H2 题干；不写源码；只读公开语料与配置。
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[7]
sys.path.insert(0, str(ROOT / "backend" / "src"))

from mktkb.evaluation import gate as gate_module  # noqa: E402
from mktkb.evaluation.dataset import CaseSpec, write_cases  # noqa: E402
from mktkb.evaluation.gate import (  # noqa: E402
    EXIT_PASS,
    EXIT_UNKNOWN,
    GATE_STATUS_NOT_APPLICABLE,
    GATE_STATUS_NOT_EVALUATED,
    GATE_STATUS_PASS,
    GATE_VERSION_V0_3,
    HARD_GATE_IDS,
    GateConfig,
    GateProposal,
    GateResult,
)
import mktkb.evaluation.p2_scoring as ps  # noqa: E402

RESULTS = []


def check(name, fn):
    try:
        detail = fn()
        RESULTS.append({"status": "PASS", "name": name, "detail": detail})
    except Exception as exc:  # noqa: BLE001
        RESULTS.append({"status": "FAIL", "name": name, "detail": f"{type(exc).__name__}: {exc}"})


def eq(actual, expected, label=""):
    if actual != expected:
        raise AssertionError(f"{label}: {actual!r} != {expected!r}")


def _public_scores(*, fail=(), error=(), skipped=(), missing=(), extra=()):
    scores = []
    for case_id in ps.P2_B0_IDS:
        if case_id in missing:
            continue
        if case_id in skipped:
            status = ps.CASE_STATUS_SKIPPED_OCR
        elif case_id in error:
            status = ps.CASE_STATUS_ERROR
        elif case_id in fail:
            status = ps.CASE_STATUS_FAIL
        else:
            status = ps.CASE_STATUS_PASS
        scores.append(
            ps.P2CaseScore(
                case_id=case_id,
                suite="b0",
                stratum="ocr" if case_id in ps.P2_B0_OCR_IDS else ("text" if case_id in ps.P2_B0_TEXT_IDS else "exact"),
                status=status,
                requires_ocr=case_id in ps.P2_B0_OCR_IDS,
                planned_turns=1,
                executed_turns=1,
            )
        )
    for case_id in ps.P2_NEGATIVE_IDS + ps.P2_BOUNDARY_IDS + ps.P2_UPDATE_DELETE_IDS:
        scores.append(
            ps.P2CaseScore(
                case_id=case_id, suite="other", stratum="other", status=ps.CASE_STATUS_PASS,
                requires_ocr=False, planned_turns=1, executed_turns=1,
            )
        )
    for case_id in extra:
        scores.append(
            ps.P2CaseScore(
                case_id=case_id, suite="b0", stratum="exact", status=ps.CASE_STATUS_PASS,
                requires_ocr=False, planned_turns=1, executed_turns=1,
            )
        )
    return scores


# --------------------------------------------------------------------------- #
# A 分母手算
# --------------------------------------------------------------------------- #


def section_a():
    questions = json.loads(
        (ROOT / "fixtures" / "acceptance" / "questions.json").read_text(encoding="utf-8")
    )["questions"]
    by_prefix = {}
    for item in questions:
        by_prefix.setdefault(item["id"][0], []).append(item)

    def ids(prefix):
        return [item["id"] for item in by_prefix[prefix]]

    eq(len(by_prefix["Q"]), 40, "B0 题数")
    by_cat = {}
    for item in by_prefix["Q"]:
        by_cat.setdefault(item["category"], []).append(item["id"])
    eq(len(by_cat["exact"]), 24, "精确题数")
    eq(by_cat["exact"], [f"Q{i:02d}" for i in range(1, 25)], "精确题 id")
    eq(len(by_cat["text"]), 8, "text 题数")
    eq(by_cat["text"], [f"Q{i:02d}" for i in range(25, 33)], "text 题 id")
    eq(len(by_cat["ocr"]), 8, "OCR 题数")
    eq(by_cat["ocr"], [f"Q{i:02d}" for i in range(33, 41)], "OCR 题 id")
    eq(ids("N"), [f"N{i:02d}" for i in range(1, 9)], "N id")
    eq(ids("C"), [f"C{i:02d}" for i in range(1, 7)], "C id")
    eq(ids("U"), [f"U{i:02d}" for i in range(1, 11)], "U id")

    eq(ps.P2_B0_TOTAL, 40, "常量 B0")
    eq(ps.P2_B0_EXACT_TOTAL, 24, "常量 exact")
    eq(ps.P2_B0_OCR_TOTAL, 8, "常量 OCR")
    eq(ps.P2_B0_MIN_PASS, 36, "常量 B0 门槛")
    eq(ps.P2_B0_EXACT_IDS, tuple(by_cat["exact"]), "常量 exact id")
    eq(ps.P2_B0_TEXT_IDS, tuple(by_cat["text"]), "常量 text id")
    eq(ps.P2_B0_OCR_IDS, tuple(by_cat["ocr"]), "常量 OCR id")
    eq(ps.P2_NEGATIVE_IDS, tuple(ids("N")), "常量 N")
    eq(ps.P2_BOUNDARY_IDS, tuple(ids("C")), "常量 C")
    eq(ps.P2_UPDATE_DELETE_IDS, tuple(ids("U")), "常量 U")

    manifest = json.loads(
        (ROOT / "docs" / "evaluation" / "p2-holdout-v2.manifest.json").read_text(encoding="utf-8")
    )
    eq(manifest["case_count"], 30, "H2 题数")
    eq(dict(manifest["strata"]), dict(ps.P2_HOLDOUT_STRATA), "H2 分层")
    eq(ps.P2_HOLDOUT_MIN_PASS, 24, "H2 门槛")
    eq(ps.P2_HOLDOUT_MAX_HARD_FAILURES, 0, "H2 硬失败上限")
    assert "questions_ciphertext_sha256" in manifest and "labels_ciphertext_sha256" in manifest
    return "B0=40(24/8/8) N=8 C=6 U=10 H2=30(10/5/5/5/5)"


# --------------------------------------------------------------------------- #
# B 配置
# --------------------------------------------------------------------------- #


def section_b():
    v1 = gate_module.load_gate_config(ROOT / "docs" / "evaluation" / "gate_v0_1.json")
    v2 = gate_module.load_gate_config(ROOT / "docs" / "evaluation" / "gate_v0_2.json")
    shipped = ps.load_p2_gate_config()
    eq(v1.schema_version, "mktkb.gate.config.v0.1", "v0.1 schema")
    eq(v2.schema_version, "mktkb.gate.config.v0.2", "v0.2 schema")
    eq(v2.status, "approved", "v0.2 审批状态（P1 已批准，不得被本包改动）")
    eq(shipped.schema_version, "mktkb.gate.config.v0.3", "v0.3 schema")
    eq(shipped.gate_version, GATE_VERSION_V0_3, "v0.3 gate_version")
    eq(shipped.status, "unapproved", "v0.3 必须未审批")
    assert shipped.standards is not None
    eq(shipped.standards.holdout_min_pass, 24, "v0.3 H2 门槛")
    assert all(
        spec.absolute_min is None and spec.absolute_max is None and spec.min_sample is None
        for spec in shipped.config.metrics
    ), "v0.3 质量阈值必须全 null"

    tmp = Path(tempfile.mkdtemp(prefix="t205-verify-config-"))
    raw = json.loads(gate_module.P2_GATE_CONFIG_PATH.read_text(encoding="utf-8"))
    raw["p2_standards"]["holdout"]["min_pass"] = 20
    tampered = tmp / "tampered.json"
    tampered.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    code = None
    try:
        ps.load_p2_gate_config(tampered)
    except ps.P2ScoringError as exc:
        code = exc.code
    eq(code, "p2_standards_mismatch", "放宽 H2 门槛必须被拒")

    proposal = GateProposal(
        run_id="verify-run",
        suite="b0",
        mode="end_to_end",
        pipeline_version="verify",
        dataset_version="verify",
        gate_version=GATE_VERSION_V0_3,
        gate_config_hash="f" * 64,
        status="unapproved",
        strata=("all",),
        metrics=(),
        diagnostics={},
    )
    refused = False
    try:
        gate_module.write_gate_proposal(proposal, gate_module.P2_GATE_CONFIG_PATH)
    except ValueError:
        refused = True
    assert refused, "write_gate_proposal 必须拒绝覆盖 gate_v0_3"
    return f"v0.1/v0.2 可加载，v0.3 unapproved hash={shipped.config_hash[:16]}"


# --------------------------------------------------------------------------- #
# C 分母口径
# --------------------------------------------------------------------------- #


def section_c():
    card = ps.score_public_suites(_public_scores())
    assert card.release_ready is True, card.to_dict()
    b0 = card.suites["b0"]
    eq((b0.planned, b0.executed, b0.passed, b0.failed), (40, 40, 40, 0), "全通过计数")
    eq((b0.exact_planned, b0.exact_passed, b0.ocr_executed, b0.ocr_passed), (24, 24, 8, 8), "精确/OCR 子口径")

    ocr_skipped = ps.score_public_suites(_public_scores(skipped=("Q33",)))
    codes = {block.code for block in ocr_skipped.blocks}
    assert "ocr_not_executed" in codes and "case_error" in codes, codes
    eq(ocr_skipped.suites["b0"].passed, 39, "OCR 跳过后正确数")
    eq(ocr_skipped.suites["b0"].ocr_executed, 7, "OCR 执行数")
    assert ocr_skipped.release_ready is False

    errors = ps.score_public_suites(_public_scores(error=("Q30",)))
    eq((errors.suites["b0"].passed, errors.suites["b0"].errors), (39, 1), "error 单列")
    assert errors.release_ready is False

    exact_miss = ps.score_public_suites(_public_scores(fail=("Q05",)))
    hard = [block for block in exact_miss.blocks if block.code == "exact_below_24_of_24"]
    assert hard and hard[0].severity == ps.SEVERITY_HARD, "精确失手必须 hard block"
    assert exact_miss.release_ready is False

    short = ps.score_public_suites(_public_scores(fail=("Q25", "Q26", "Q27", "Q28")))
    assert short.release_ready is True, "36/40 且精确 24/24 仍可放行（口径边界）"

    missing = ps.score_public_suites(_public_scores(missing=("Q40",)))
    assert "missing_case" in {block.code for block in missing.blocks}
    eq((missing.suites["b0"].planned, missing.suites["b0"].executed), (40, 39), "缺题不改分母")

    unexpected = ps.score_public_suites(_public_scores(extra=("Q99",)))
    assert "unexpected_case" in {block.code for block in unexpected.blocks}
    return "OCR 跳过/error/精确失手/缺题/多题 全部阻断；36/40 边界放行"


# --------------------------------------------------------------------------- #
# D 门禁判定（含开发用例未直测的分支）
# --------------------------------------------------------------------------- #

DOC_NAME = "V01_物品位置表.xlsx"
UNIT_ID = "22222222-2222-4222-8222-222222222222"
UNIT_KEY = "sheet:物品位置:row:8"


def _case(case_id="Q01"):
    return CaseSpec(
        case_id=case_id,
        suite="b0",
        split="dev",
        stratum="exact",
        business_date="2026-10-28",
        question="城东店的宣传海报在哪里？",
        expected_kind="answer",
        expected_values=("B区1号货架第二层",),
        expected_sources=({"doc_code": "D01", "unit_key": UNIT_KEY},),
        labeler="lead",
        label_version="dev-1",
    )


def _manifest(**overrides):
    payload = {
        "run_id": "verify-run",
        "mode": "end_to_end",
        "scope": "end_to_end",
        "suite": "b0",
        "dataset_version": "verify:dev-1",
        "dataset_sha256": "a" * 64,
        "corpus_manifest_sha256": "b" * 64,
        "business_date": "2026-10-28",
        "index_revision": 3,
        "pipeline_version": "verify-pipeline",
        "gate_version": GATE_VERSION_V0_3,
        "label_version": "dev-1",
        "created_at": "2026-11-10T00:00:00.000+00:00",
        "case_count": 1,
        "config_hash": "c" * 12,
        "gate_config_hash": "f" * 64,
    }
    payload.update(overrides)
    return payload


def _build_run(tmp_root, *, manifest=None, product_sources=None):
    run_dir = tmp_root / "run"
    run_dir.mkdir(parents=True, exist_ok=True)
    dataset_path = tmp_root / "dataset.jsonl"
    case = _case()
    write_cases(dataset_path, (case,))
    manifest_map = _manifest() if manifest is None else manifest
    manifest_map["dataset_path"] = str(dataset_path)
    sources = product_sources or (
        {
            "source_id": UNIT_ID,
            "document_name": DOC_NAME,
            "version_number": 1,
            "status": "active",
            "locator": {"sheet": "物品位置", "row": 8},
        },
    )
    row = {
        "case_id": "Q01",
        "status": "ok",
        "error_code": None,
        "conversation_id": "conv-1",
        "planned_turns": 1,
        "turns_executed": 1,
        "turns": [
            {
                "turn": 1,
                "status": "ok",
                "error_code": None,
                "product": {
                    "kind": "answer",
                    "text": "城东店的宣传海报在 B区1号货架第二层。",
                    "trace_id": "trace-q01",
                    "trace_path": "legacy",
                    "sources": [dict(item) for item in sources],
                },
            }
        ],
    }
    scored = ps.score_public_case(
        case,
        row,
        document_codes={DOC_NAME: "D01"},
        source_index={UNIT_ID: {"doc_code": "D01", "unit_key": UNIT_KEY, "locator": {}}},
        allowed_doc_codes={"D01"},
        evidence=({"doc_code": "D01", "unit_ids": [UNIT_ID]},),
    )
    rows = ps.build_gate_rows((case,), (scored,))
    run = ps.build_gate_run(
        run_dir=run_dir, manifest=manifest_map, cases=(case,), rows=rows, summary={"status": "succeeded"}
    )
    from mktkb.observability.contracts import SpanRecord, TraceRecord
    from mktkb.observability.store import TraceRepository

    repo = TraceRepository(run_dir / "traces.sqlite3")
    try:
        record = TraceRecord(
            trace_id="trace-q01",
            http_request_id="verify-run:Q01",
            mode=run.manifest.mode,
            scope=run.manifest.scope,
            path="legacy",
            case_id="Q01",
            outcome_kind="answer",
            status="ok",
            latency_ms=1,
            dataset_version=manifest_map["dataset_version"],
            run_id=manifest_map["run_id"],
            index_revision=str(manifest_map["index_revision"]),
            manifest_sha256=manifest_map["corpus_manifest_sha256"],
            pipeline_version=manifest_map["pipeline_version"],
            config_hash=manifest_map["config_hash"],
        )
        repo.write(
            record,
            [
                SpanRecord(span_id=f"trace-q01-{name}", trace_id="trace-q01", name=name, status="ok")
                for name in ("intent_parse", "retrieve", "model_answer", "answer_validate", "commit")
            ],
        )
    finally:
        repo.close()
    return run, scored, dict(manifest_map)


def _approved_config(*, status="approved", min_sample=1, config_hash="f" * 64):
    return ps.P2GateConfig(
        config=GateConfig(
            gate_version=GATE_VERSION_V0_3,
            schema_version="mktkb.gate.config.v0.3",
            status=status,
            hard_gates=HARD_GATE_IDS,
            min_sample={"b0": min_sample},
            metrics=ps.load_p2_gate_config().config.metrics,
            sensitive_patterns=(),
            suites=("b0", "regression"),
            source_path=str(gate_module.P2_GATE_CONFIG_PATH),
            config_hash=config_hash,
        ),
        standards=ps.load_p2_gate_config().standards,
        raw={},
    )


def _holdout_card(*, approved=True):
    items = []
    for stratum, count in ps.P2_HOLDOUT_STRATA.items():
        for offset in range(count):
            items.append(
                ps.P2HoldoutCaseScore(
                    case_id=f"H2-{stratum}-{offset:02d}",
                    stratum=stratum,
                    status=ps.CASE_STATUS_PASS if len(items) < 24 else ps.CASE_STATUS_FAIL,
                )
            )
    return ps.aggregate_holdout(items, thresholds_approved=approved)


def section_d():
    tmp = Path(tempfile.mkdtemp(prefix="t205-verify-gate-"))
    run, _, manifest_map = _build_run(tmp)
    shipped = ps.load_p2_gate_config()
    hard_gate = ps.evaluate_p2_hard_gates(run, config=_approved_config())
    if hard_gate.exit_code != EXIT_PASS:
        raise AssertionError(f"合成 clean run 应通过硬门禁，实际 exit={hard_gate.exit_code} unknowns={[u.check_id for u in hard_gate.unknowns]}")

    summary = {
        "status": "succeeded",
        "stop_code": None,
        "cases": {"planned": 1, "executed": 1, "with_error": 0, "not_executed": 0},
    }
    public = ps.score_public_suites(_public_scores())

    def binding(config):
        payload = dict(manifest_map)
        payload["gate_config_hash"] = config.config_hash
        return payload

    def decide(**overrides):
        kwargs = {
            "config": shipped,
            "run_manifest": binding(shipped),
            "run_summary": summary,
            "hard_gate": hard_gate,
            "public": public,
            "holdout": _holdout_card(),
            "citation_evidence_complete": True,
        }
        kwargs.update(overrides)
        return ps.evaluate_p2_gate(**kwargs)

    manifest_dict = binding(shipped)

    base = decide(config=shipped, run_manifest=manifest_dict)
    codes = {block.code for block in base.blocks}
    assert base.release_allowed is False, "unapproved 配置不得放行"
    assert "gate_config_unapproved" in codes, codes
    eq((base.execution_exit_code, base.quality_exit_code), (EXIT_PASS, EXIT_UNKNOWN), "执行/质量码分离")

    branches = {}
    for label, overrides, expected in (
        ("public_missing", {"public": None}, "public_scorecard_missing"),
        ("holdout_missing", {"holdout": None}, "holdout_missing"),
        ("manifest_missing", {"run_manifest": None}, "run_manifest_missing"),
        ("summary_missing", {"run_summary": None}, "run_summary_missing"),
        ("hard_gate_missing", {"hard_gate": None}, "hard_gate_missing"),
    ):
        decision = decide(**overrides)
        got = {block.code for block in decision.blocks}
        assert expected in got, (label, got)
        assert decision.release_allowed is False, label
        branches[label] = decision.quality_exit_code

    all_na = GateResult(
        exit_code=EXIT_PASS,
        gate_status={gate_id: GATE_STATUS_NOT_APPLICABLE for gate_id in HARD_GATE_IDS},
        hard_failures=(),
        failures=(),
        unknowns=(),
        not_applicable=(),
        warnings=(),
        run_id="verify-run",
        suite="b0",
        mode="local",
        gate_version=GATE_VERSION_V0_3,
        scored_count=1,
        min_sample=1,
    )
    decision = decide(hard_gate=all_na)
    assert "hard_gates_not_applicable" in {block.code for block in decision.blocks}, decision.to_dict()
    assert decision.release_allowed is False

    partial = replace(
        all_na,
        gate_status={**{gate_id: GATE_STATUS_PASS for gate_id in HARD_GATE_IDS}, "trace_integrity": GATE_STATUS_NOT_EVALUATED},
    )
    decision = decide(hard_gate=partial)
    assert "hard_gate_not_evaluated" in {block.code for block in decision.blocks}
    assert decision.release_allowed is False

    # 合成 approved 配置 + 完整证据 → 逻辑路径可达（不构成放行，shipped 文件仍是 unapproved）
    approved = _approved_config()
    green = decide(config=approved, run_manifest=binding(approved), holdout=_holdout_card(approved=True))
    assert green.release_allowed is True, green.to_dict()
    eq((green.execution_exit_code, green.quality_exit_code), (EXIT_PASS, EXIT_PASS), "green 路径码")
    return "缺失分支/全 not_applicable/not_evaluated 全部不放行；合成 approved 可达 pass"


# --------------------------------------------------------------------------- #
# E 产品侧公开财务反例
# --------------------------------------------------------------------------- #

CORPUS = ROOT / "corpus" / "enterprise-20261101"
E10 = CORPUS / "excel" / "E10_市场部KPI月报.xlsx"
W03 = CORPUS / "word" / "W03_促销活动申请审批与结案流程管理办法.docx"
E03 = CORPUS / "excel" / "E03_2026年Q4渠道价目表.xlsx"


def _case_spec(case_id, question, *, expected_values=(), forbidden_values=(), expected_kind="answer",
               expected_sources=(), stratum="exact", turns=(), suite="b0"):
    return CaseSpec(
        case_id=case_id,
        suite=suite,
        split="dev",
        stratum=stratum,
        business_date="2026-10-28",
        question=question,
        turns=turns,
        expected_kind=expected_kind,
        expected_values=expected_values,
        expected_sources=expected_sources,
        forbidden_values=forbidden_values,
        labeler="verify",
        label_version="verify-2026-11-10",
    )


async def section_e():
    from mktkb.evaluation.product_adapter import (
        IngestSource,
        MockChatBackend,
        P2IngestPlan,
        P2RunDataset,
        ProductEvalAdapter,
    )
    from mktkb.rag.providers import post_counters, reset_post_counters

    reset_post_counters()
    out_dir = Path(tempfile.mkdtemp(prefix="t205-verify-product-"))
    chat = MockChatBackend()
    adapter = ProductEvalAdapter(
        out_dir / "app",
        chat=chat,
        dataset=P2RunDataset(
            visibility="public",
            cases=(),
            identity={
                "dataset_version": "verify-public-v1",
                "label_version": "verify-2026-11-10",
                "suite": "p2-holdout",
                "manifest_sha256": "d" * 64,
                "case_count": 0,
            },
        ),
        ingest_plan=P2IngestPlan(
            sources=(IngestSource(path=E10), IngestSource(path=W03), IngestSource(path=E03)),
            label="t205-verify",
        ),
    )
    documents = {
        "E10_市场部KPI月报.xlsx": "E10",
        "W03_促销活动申请审批与结案流程管理办法.docx": "W03",
        "E03_2026年Q4渠道价目表.xlsx": "E03",
    }
    rows = []
    try:
        await adapter.start()
        receipts = await adapter.ingest()
        assert [item.job_state for item in receipts] == ["succeeded"] * 3, [r.as_dict() for r in receipts]
        conversation = await adapter.open_conversation()
        counter = {"n": 0}

        async def ask(question):
            counter["n"] += 1
            return await adapter.ask_turn(
                question,
                user_id="employee",
                conversation_id=conversation,
                client_request_id=f"00000000-0000-4000-8000-{counter['n']:012d}",
            )

        def score(case, turns):
            row = {
                "case_id": case.case_id,
                "status": "ok",
                "error_code": None,
                "conversation_id": conversation,
                "planned_turns": max(1, len(case.turns)),
                "turns_executed": len(turns),
                "turns": [
                    {"turn": index, "status": "ok", "error_code": None, "product": turn.as_dict(include_text=True)}
                    for index, turn in enumerate(turns, start=1)
                ],
            }
            scored = ps.score_public_case(
                case, row, document_codes=documents, allowed_doc_codes=set(documents.values())
            )
            return scored

        specs = [
            _case_spec(
                "V01",
                "陈列达标率的计算口径和年度目标是什么？",
                expected_values=("90%",),
                forbidden_values=("95%",),
                expected_sources=({"doc_code": "E10", "locator": {"sheet": "KPI月报", "row": 103}},),
            ),
            _case_spec(
                "V02",
                "单场预算 8000 元的活动由谁审批？",
                expected_values=("市场部经理",),
                forbidden_values=("事业部总经理", "通路行销主管"),
                expected_sources=({"doc_code": "W03", "locator": {"heading": "第三章 审批权限"}},),
            ),
            _case_spec(
                "V03",
                "2026年Q4 启沣柠檬茶（500ml PET）在NKA卖场的档期特价是多少？",
                expected_values=("2.99",),
                forbidden_values=("2.5",),
                expected_sources=({"doc_code": "E03", "locator": {"sheet": "NKA卖场", "row": 7}},),
            ),
            _case_spec(
                "V04",
                "2026年Q4渠道价目表中 咸味饼干 120g 的批发价是多少？",
                expected_kind="not_found",
                stratum="negative",
                suite="badcase",
                expected_sources=(),
            ),
            _case_spec(
                "V05",
                "活动结束后几日内上交结案报告？",
                expected_values=("6 个自然日",),
                stratum="text",
                expected_sources=({"doc_code": "W03", "locator": {"heading": "第五章 结案与稽核"}},),
            ),
        ]
        turns = {}
        for spec in specs:
            turn = await ask(spec.question)
            turns[spec.case_id] = turn
            scored = score(spec, [turn])
            rows.append(
                {
                    "case_id": spec.case_id,
                    "question": spec.question,
                    "product_kind": turn.kind,
                    "product_text": turn.text,
                    "verdict": scored.score.status,
                    "failed_checks": sorted(
                        {item["check_id"] for item in scored.score.checks if item["status"] == "fail"}
                    ),
                }
            )

        # 多轮：同一会话追问政策另一个时限字段
        multi = _case_spec(
            "V06",
            "活动结束后几日内上交结案报告？",
            expected_values=("3 个工作日",),
            stratum="text",
            turns=({"question": "活动结束后几日内上交结案报告？"}, {"question": "那活动变更是提前多久？"}),
            expected_sources=({"doc_code": "W03", "locator": {"heading": "第二章 申请与时限"}},),
        )
        follow = await ask("那活动变更是提前多久？")
        multi_scored = score(multi, [turns["V05"], follow])
        rows.append(
            {
                "case_id": "V06",
                "question": multi.question,
                "product_kind": follow.kind,
                "product_text": follow.text,
                "verdict": multi_scored.score.status,
                "executed_turns": multi_scored.score.executed_turns,
                "failed_checks": sorted(
                    {item["check_id"] for item in multi_scored.score.checks if item["status"] == "fail"}
                ),
            }
        )

        # 来源权限：其他用户读同一来源必须 403
        employee_code, detail = await adapter.source_detail(
            turns["V05"].message_id, turns["V05"].source_ids[0]
        )
        admin_code, _ = await adapter.source_detail(
            turns["V05"].message_id, turns["V05"].source_ids[0], user_id="admin"
        )
        calls = adapter.provider_calls()
        posts = sum(int(value) for value in (post_counters().get("attempts") or {}).values())

        verdicts = {row["case_id"]: row["verdict"] for row in rows}
        assert verdicts["V01"] == ps.CASE_STATUS_FAIL, verdicts
        assert verdicts["V02"] == ps.CASE_STATUS_FAIL, verdicts
        assert verdicts["V03"] == ps.CASE_STATUS_FAIL, verdicts
        assert verdicts["V04"] == ps.CASE_STATUS_FAIL, verdicts
        assert verdicts["V05"] == ps.CASE_STATUS_PASS, verdicts
        assert verdicts["V06"] == ps.CASE_STATUS_PASS, verdicts
        assert multi_scored.score.executed_turns == 2
        assert employee_code == 200 and detail["status"] == "active", (employee_code, detail)
        assert admin_code == 403, admin_code
        assert calls["outbound_network"] == 0, calls
        assert posts == 0, posts
        assert chat.call_count >= 1, chat.call_count
        return {"rows": rows, "provider_calls": calls, "rag_provider_posts": posts,
                "source_detail": {"employee": employee_code, "admin": admin_code},
                "chat_calls": chat.call_count}
    finally:
        await adapter.close()


def main():
    check("A 分母手算与常量比对", section_a)
    check("B gate 配置（v0.1/v0.2/v0.3、unapproved、防篡改）", section_b)
    check("C 分母口径（OCR/error/精确/缺题/多题）", section_c)
    check("D 门禁判定 fail-closed 分支", section_d)
    check("E 产品侧 4 反例 + 2 正向 + 来源权限", lambda: asyncio.run(section_e()))
    print(json.dumps({"results": RESULTS}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

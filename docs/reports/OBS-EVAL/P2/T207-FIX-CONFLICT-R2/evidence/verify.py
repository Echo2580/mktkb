"""P2-T207-FIX-CONFLICT-R2 离线取证：冲突回答 text 披露取值（零真实调用、零出网）。

两段，全部走产品代码与冻结评分器：

A. R4 灌库终态（V03->D01->V04 未发布 + V01 + D02 + V02）下，按 live 形状（每轮只允许
   1 次 query embedding）逐题提问 C05/C06/N08，用冻结的 CaseSpec（
   docs/reports/OBS-EVAL/P2/T207/cases/R4.jsonl）走 p2_scoring.score_public_case 打分，
   同时保留产品 HTTP 原始负载（text/conflicts/sources）作为改动前后对照。
B. 54 例公开 case（Q01-Q40 / N01-N08 / C01-C06）修复前后逐题差分：B0 装配 + 快照恢复，
   C05/C06 各自恢复 B0 快照后发布 V01/V02 再问；记录 kind/text/sources/conflicts/候选
   与验收口径（b0.evaluate）的 status/strict_status。

用法（仓库根，零真实调用）：
  .venv/Scripts/python.exe -B -X utf8 docs/reports/OBS-EVAL/P2/T207-FIX-CONFLICT-R2/evidence/verify.py \
    --src=<产品源码根> --part=r4|impact|all --out=<json>
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
import uuid
from pathlib import Path

HERE = Path(__file__).resolve()
REPO = HERE.parents[6]
T207 = REPO / "docs" / "reports" / "OBS-EVAL" / "P2" / "T207"
R4_CASES = T207 / "cases" / "R4.jsonl"
R4_PLAN = T207 / "PM" / "T207-ingest-plan-R4.json"
DOCUMENT_CODES = T207 / "cases" / "document-codes.json"

parser = argparse.ArgumentParser()
parser.add_argument("--src", default=str(REPO / "backend" / "src"))
parser.add_argument("--part", choices=("r4", "impact", "all"), default="all")
parser.add_argument("--out", required=True)
args = parser.parse_args()

SRC = Path(args.src).resolve()
sys.path.insert(0, str(REPO / "backend" / "tests" / "acceptance"))
sys.path.insert(0, str(REPO / "backend" / "tests"))
sys.path.insert(0, str(SRC))
os.chdir(REPO)

FORBID_PHRASES = {"N08": ("照片中", "已定位", "未标记物品位于")}
CLEAN_KINDS = {"answer", "not_found", "clarification", "knowledge_changed"}
CONFLICT_VARIANTS = {"C05": "V01", "C06": "V02"}


class _PerTurnQueryGate:
    """仿真 live 门控：每轮只允许 1 次 query embedding（计划项 query_embedding=1/turn）。"""

    def __init__(self, inner) -> None:
        self.inner = inner
        self.budget = 1
        self.refused = 0

    def begin_turn(self) -> None:
        self.budget = 1

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def __repr__(self) -> str:
        return f"_PerTurnQueryGate({self.inner!r})"

    def embed(self, texts, *, purpose: str = "document"):
        if purpose == "query":
            if self.budget <= 0:
                self.refused += 1
                raise RuntimeError("p2-live gate: 本轮 query_embedding 计划项已用尽")
            self.budget -= 1
        return self.inner.embed(texts, purpose=purpose)


def _case_row(case_id: str, product: dict) -> dict:
    return {
        "case_id": case_id,
        "status": "ok",
        "planned_turns": 1,
        "turns": [{"turn": 1, "status": "ok", "product": product}],
    }


async def _raw_ask(adapter, question: str) -> dict:
    session = adapter._session("employee")
    created = await session.client.post("/api/v1/conversations", json={}, headers=session.write_headers)
    conversation = created.json()["id"]
    response = await session.client.post(
        f"/api/v1/conversations/{conversation}/messages",
        json={"client_request_id": str(uuid.uuid4()), "question": question},
        headers=session.write_headers,
    )
    payload = response.json()
    return {
        "http_status": int(response.status_code),
        "kind": payload.get("kind"),
        "text": payload.get("text"),
        "conflicts": payload.get("conflicts") or [],
        "sources": [
            {"document_name": item.get("document_name"), "version_number": item.get("version_number")}
            for item in payload.get("sources") or ()
        ],
    }


async def run_r4() -> dict:
    from mktkb.evaluation.dataset import CaseSpec, validate_case
    from mktkb.evaluation.p2_scoring import EXECUTION_MODE_LOCAL_MOCK, score_public_case
    from mktkb.evaluation.p2_score_run import load_document_codes, source_index_from_rows
    from mktkb.evaluation.product_adapter import (
        MockChatBackend,
        P2RunDataset,
        ProductEvalAdapter,
        ingest_plan_from_document,
    )
    from mktkb.rag.providers import post_counters

    plan = ingest_plan_from_document(json.loads(R4_PLAN.read_text(encoding="utf-8")))
    cases: list[CaseSpec] = []
    for line in R4_CASES.read_text(encoding="utf-8").splitlines():
        if line.strip():
            case = CaseSpec.from_dict(json.loads(line))
            validate_case(case)
            cases.append(case)
    codes = load_document_codes(DOCUMENT_CODES)

    tmp = Path(tempfile.mkdtemp(prefix="p2-t207-r2-r4-"))
    chat = MockChatBackend()
    dataset = P2RunDataset(
        visibility="public",
        cases=(),
        identity={
            "dataset_version": "p2-t207-fix-conflict-r2",
            "label_version": "p2-t207-fix-conflict-r2",
            "suite": "p2-t207-r4",
            "manifest_sha256": "a" * 64,
            "case_count": 0,
        },
    )
    adapter = ProductEvalAdapter(tmp / "r4", chat=chat, dataset=dataset, ingest_plan=plan)
    try:
        await adapter.start()
        await adapter.ingest()
        adapter._qa.ensure_ready()
        gate = _PerTurnQueryGate(adapter._qa.index().embedder)
        adapter._qa.index().embedder = gate

        rows: dict[str, dict] = {}
        turns: list[dict] = []
        for case in cases:
            conversation = await adapter.open_conversation()
            gate.begin_turn()
            calls_before = len(chat.calls)
            turn = await adapter.ask_turn(
                case.question,
                user_id="employee",
                conversation_id=conversation,
                client_request_id=str(uuid.uuid4()),
            )
            product = turn.as_dict(include_text=True)
            rows[case.case_id] = _case_row(case.case_id, product)
            turns.append(
                {
                    "case_id": case.case_id,
                    "expected_kind": case.expected_kind,
                    "expected_values": list(case.expected_values),
                    "kind": turn.kind,
                    "text": turn.text,
                    "http_status": int(turn.http_status),
                    "sources": [
                        {
                            "document_name": item.get("document_name"),
                            "version_number": item.get("version_number"),
                            "document_code": codes.get(str(item.get("document_name") or "")),
                        }
                        for item in turn.sources
                    ],
                    "model_calls_this_turn": len(chat.calls) - calls_before,
                    "model_calls_by_purpose": {
                        purpose: sum(1 for call in chat.calls[calls_before:] if call["purpose"] == purpose)
                        for purpose in ("answer", "query_expansion")
                    },
                    "query_embedding_refused": gate.refused,
                }
            )

        source_index = source_index_from_rows(rows)
        scoring: list[dict] = []
        for case in cases:
            scored = score_public_case(
                case,
                rows[case.case_id],
                document_codes=codes,
                source_index=source_index,
                execution_mode=EXECUTION_MODE_LOCAL_MOCK,
                real_calls=0,
            )
            scoring.append(
                {
                    "case_id": case.case_id,
                    "status": scored.score.status,
                    "checks": [
                        {
                            "check_id": item["check_id"],
                            "status": item["status"],
                            "evidence": item.get("evidence") or {},
                        }
                        for item in scored.score.checks
                    ],
                    "issues": [item.to_dict() for item in scored.score.issues],
                }
            )

        raw = [{"case_id": case.case_id, **(await _raw_ask(adapter, case.question))} for case in cases]
        return {
            "src": str(SRC),
            "mock_mode": adapter.is_mock,
            "ingest_plan": {"path": str(R4_PLAN.relative_to(REPO)), "sources": len(plan.sources)},
            "turns": turns,
            "raw_payload": raw,
            "scoring": scoring,
            "post_counters": {kind: dict(value) for kind, value in post_counters().items()},
        }
    finally:
        await adapter.close()


def _record(item: dict, response, environment: dict) -> dict:
    from support import b0

    graded = b0.evaluate(
        item,
        response,
        environment=environment,
        forbid_phrases=FORBID_PHRASES.get(item["id"], ()),
    )
    actual = graded.get("actual") or {}
    return {
        "id": item["id"],
        "group": item["group"],
        "question": item["question"],
        "expected_kind": (item.get("scenario") or {}).get("expected_kind"),
        "kind": actual.get("kind"),
        "text": actual.get("text"),
        "sources": sorted(
            (str(source.get("document_name")), int(source.get("version_number") or 0))
            for source in graded.get("source") or []
        ),
        "conflicts": [
            {
                "field": entry.get("field"),
                "values": [item_.get("value") for item_ in entry.get("entries") or []],
            }
            for entry in actual.get("conflicts") or []
        ],
        "candidates": actual.get("candidates") or [],
        "status": graded.get("status"),
        "strict_status": graded.get("strict_status"),
        "problems": graded.get("problems") or [],
    }


def run_impact() -> dict:
    from support import b0

    environment = {"layer": "L", "provider": "P2-T207-FIX-CONFLICT-R2 offline harness"}
    out: list[dict] = []
    work = Path(tempfile.mkdtemp(prefix="p2-t207-r2-impact-"))
    live = b0.build_b0(work / "build")
    snapshot = b0.snapshot_b0(work / "build", work / "snapshot")
    try:
        employee = live.harness.employee()
        for item in b0.QUESTIONS:
            if item["group"] not in ("normal", "negative", "ambiguity_conflict"):
                continue
            scenario = item.get("scenario") or {}
            if scenario.get("expected_kind") == "conflict":
                continue
            if scenario.get("expected_kind") not in CLEAN_KINDS:
                continue
            conversation = b0.new_conversation(employee, f"T207R2-{item['id']}")
            response = b0.ask(employee, conversation, item["question"])
            out.append(_record(item, response, environment))
    finally:
        live.harness.close()

    for item in b0.QUESTIONS:
        variant = CONFLICT_VARIANTS.get(item["id"])
        if variant is None:
            continue
        harness = b0.restore_b0(snapshot, work / f"conflict-{item['id']}")
        try:
            admin = harness.admin()
            receipt = admin.upload(path=b0.fixture_path(variant), allow_same_name=False)
            assert receipt.status_code == 202, receipt.text
            record = receipt.json()
            harness.ocr.unbind()
            result = harness.run_job()
            assert result.state == "succeeded", result
            detail = harness.detail(record["document"]["id"])
            active = detail["document"]["active_version"]
            published = admin.client.post(
                f"/api/v1/documents/{record['document']['id']}/versions/{record['version']['id']}/publish",
                json={
                    "expected_active_version_id": active["id"] if active else None,
                    "expected_revision": detail["revision"],
                },
                headers=admin.headers,
            )
            assert published.status_code == 200, published.text
            employee = harness.employee()
            conversation = b0.new_conversation(employee, f"T207R2-{item['id']}")
            response = b0.ask(employee, conversation, item["question"])
            out.append(_record(item, response, environment))
        finally:
            harness.close()

    out.sort(key=lambda row: row["id"])
    return {"src": str(SRC), "cases": out, "case_count": len(out)}


def main() -> int:
    result: dict = {"src": str(SRC), "part": args.part}
    if args.part in ("r4", "all"):
        result["r4"] = asyncio.run(run_r4())
    if args.part in ("impact", "all"):
        result["impact"] = run_impact()
    Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print("ok ->", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

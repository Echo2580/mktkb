"""P2-T207-FIX-CONFLICT-R2 独立验收：C05/C06/N08 冻结 CaseSpec 复评（零真实调用）。

独立验收助手编写，与开发侧 evidence/verify.py 不共享实现：
- 题干/金标一律来自**冻结公开题集** fixtures/acceptance（load_acceptance_cases），
  不读 R4.jsonl 里的 CaseSpec；
- 产品侧走 ProductEvalAdapter + MockChatBackend（httpx.MockTransport，不出网），
  先按 R4 灌库计划（6 步）装配，再按 live 形状（每轮只允许 1 次 query embedding）逐题提问；
- 打分只调 p2_scoring.score_public_case；--src 可指向 HEAD 源码副本做前后对照。

用法（仓库根，零真实调用）：
  .venv/Scripts/python.exe -B -X utf8 <本文件> --src=<源码根> --out=<json>
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
import tempfile
import uuid
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--src", required=True)
parser.add_argument("--out", required=True)
args = parser.parse_args()


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "fixtures" / "acceptance").is_dir() and (parent / "backend").is_dir():
            return parent
    raise SystemExit("repo root not found")


REPO = _repo_root()
SRC = Path(args.src).resolve()
sys.path.insert(0, str(REPO / "backend" / "tests" / "acceptance"))
sys.path.insert(0, str(REPO / "backend" / "tests"))
sys.path.insert(0, str(SRC))
os.chdir(REPO)

import mktkb  # noqa: E402
import mktkb.copy as copy_module  # noqa: E402
from mktkb.evaluation.p2_public_cases import load_acceptance_cases  # noqa: E402
from mktkb.evaluation.p2_scoring import (  # noqa: E402
    EXECUTION_MODE_LOCAL_MOCK,
    score_public_case,
)
from mktkb.evaluation.p2_score_run import source_index_from_rows  # noqa: E402
from mktkb.evaluation.product_adapter import (  # noqa: E402
    MockChatBackend,
    P2RunDataset,
    ProductEvalAdapter,
    ingest_plan_from_document,
)
from mktkb.rag.providers import post_counters  # noqa: E402

CASE_IDS = ("N08", "C05", "C06")
R4_PLAN = REPO / "docs/reports/OBS-EVAL/P2/T207/PM/T207-ingest-plan-R4.json"


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class _PerTurnQueryGate:
    """仿真 live 门控：每轮只允许 1 次 query embedding。"""

    def __init__(self, inner) -> None:
        self.inner = inner
        self.budget = 0
        self.refused = 0
        self.used = 0

    def begin_turn(self) -> None:
        self.budget = 1
        self.turn_used = 0

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def __repr__(self) -> str:
        return f"_PerTurnQueryGate({self.inner!r})"

    def embed(self, texts, *, purpose: str = "document"):
        if purpose == "query":
            if self.budget <= 0:
                self.refused += 1
                raise RuntimeError("p2-live gate: 本轮 query_embedding 已用尽")
            self.budget -= 1
            self.used += 1
        return self.inner.embed(texts, purpose=purpose)


def _row(case_id: str, product: dict) -> dict:
    return {
        "case_id": case_id,
        "status": "ok",
        "planned_turns": 1,
        "turns": [{"turn": 1, "status": "ok", "product": product}],
    }


def _doc_code(name: str) -> str:
    # 冻结命名约定：<doc_code>_<文件名>；不依赖 document-codes.json。
    return str(name).split("_")[0]


async def _raw_payload(adapter, question: str) -> dict:
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
            {
                "source_id": item.get("source_id"),
                "document_name": item.get("document_name"),
                "version_number": item.get("version_number"),
                "status": item.get("status"),
                "locator": item.get("locator"),
            }
            for item in payload.get("sources") or ()
        ],
    }


async def main() -> dict:
    cases = {case.case_id: case for case in load_acceptance_cases()}
    missing = [cid for cid in CASE_IDS if cid not in cases]
    if missing:
        raise SystemExit(f"frozen cases missing: {missing}")

    plan = ingest_plan_from_document(json.loads(R4_PLAN.read_text(encoding="utf-8")))
    out_dir = Path(tempfile.mkdtemp(prefix="p2-r2-independent-"))
    chat = MockChatBackend()
    dataset = P2RunDataset(
        visibility="public",
        cases=(),
        identity={
            "dataset_version": "p2-t207-fix-conflict-r2-independent-verify",
            "label_version": "frozen-acceptance",
            "suite": "p2-t207-r4",
            "manifest_sha256": "b" * 64,
            "case_count": 0,
        },
    )
    adapter = ProductEvalAdapter(out_dir, chat=chat, dataset=dataset, ingest_plan=plan)
    posts_before = {kind: dict(value) for kind, value in post_counters().items()}
    try:
        await adapter.start()
        await adapter.ingest()
        adapter._qa.ensure_ready()
        gate = _PerTurnQueryGate(adapter._qa.index().embedder)
        adapter._qa.index().embedder = gate

        results: dict[str, dict] = {}
        for case_id in CASE_IDS:
            case = cases[case_id]
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
            row = _row(case_id, product)
            document_codes = {
                _doc_code(str(item.get("document_name") or "")): _doc_code(str(item.get("document_name") or ""))
                for item in product.get("sources") or ()
            }
            # 提交给打分器的映射：产品文档名 -> 冻结 doc_code（按命名前缀显式绑定）。
            name_map = {
                str(item.get("document_name") or ""): _doc_code(str(item.get("document_name") or ""))
                for item in product.get("sources") or ()
            }
            index = source_index_from_rows({case_id: row})
            scored = score_public_case(
                case,
                row,
                document_codes=name_map,
                source_index=index,
                execution_mode=EXECUTION_MODE_LOCAL_MOCK,
                real_calls=0,
            )

            gate.begin_turn()
            raw = await _raw_payload(adapter, case.question)

            results[case_id] = {
                "question": case.question,
                "expected": {
                    "kind": case.expected_kind,
                    "values": list(case.expected_values),
                    "sources": [dict(item) for item in case.expected_sources],
                },
                "product": {
                    "kind": turn.kind,
                    "text": turn.text,
                    "text_sha256": _sha(turn.text),
                    "http_status": int(turn.http_status),
                    "sources": [dict(item) for item in product.get("sources") or ()],
                    "model_calls_this_turn": len(chat.calls) - calls_before,
                },
                "api_payload": raw,
                "scoring": {
                    "status": scored.score.status,
                    "checks": [
                        {"check_id": item["check_id"], "status": item["status"], "evidence": item.get("evidence") or {}}
                        for item in scored.score.checks
                    ],
                    "issues": [item.to_dict() for item in scored.score.issues],
                },
                "document_codes": document_codes,
            }

        posts_after = {kind: dict(value) for kind, value in post_counters().items()}
        return {
            "src": str(SRC),
            "loaded": {
                "mktkb": str(Path(mktkb.__file__).resolve()),
                "copy": str(Path(copy_module.__file__).resolve()),
            },
            "variant_probe": copy_module.legacy_conflict_text("X"),
            "mock_mode": bool(adapter.is_mock),
            "network": adapter.network_stats(),
            "provider_calls": adapter.provider_calls(),
            "post_counters_before": posts_before,
            "post_counters_after": posts_after,
            "gate_refused": gate.refused,
            "gate_query_embeddings": gate.used,
            "ingest": {
                "plan": str(R4_PLAN.relative_to(REPO)),
                "sources": len(plan.sources),
                "documents": sorted(adapter.ingest_document_map),
            },
            "cases": results,
        }
    finally:
        await adapter.close()


if __name__ == "__main__":
    payload = asyncio.run(main())
    Path(args.out).write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print("ok ->", args.out)

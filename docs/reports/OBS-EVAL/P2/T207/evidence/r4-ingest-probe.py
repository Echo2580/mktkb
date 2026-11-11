"""P2-T207-R4PREP：R4 的**离线**灌库终态 + 实测批数 B_r4 + 三例 live 形状复核（零真实调用、零出网）。

做法（全部走产品代码，不另立一套口径）：
- 用 PM/T207-ingest-plan-R4.json 驱动 ProductEvalAdapter 的 Mock 路径（产品上传 -> 解析 -> 发布，
  经产品 HTTP 路由；chat/embedding 都是离线替身），灌进隔离库；
- 触发一次产品索引同步（等同首个提问前的 ensure_ready，qa/service.py:286-345），
  用包装后的 embedding 计数每次 embed() 的文本数 -> 批数 = sum(ceil(texts / 5))
  （真实 provider 按 embedding_batch_size=5 拆 POST：product_adapter.py:1088、rag/providers.py:292-298）；
- 只读产品库，记录终态：每份资料/每个版本号、状态、是否 active、单元数、revision；
- 三例（N08/C05/C06）按 **live 形状**（每轮只 1 个 query_embedding 计划项）逐题提问：
  第 2 次 query embedding 在替身层直接失败，等价 live 门控在发送前拒绝（p2_live.py:297）；
- 用 **冻结评分器**（p2_scoring.score_public_case，live 逐题打分同一条路径）给这三轮打分，
  并显式标注"文档代号映射只按文档名"（版本号不进映射，与 live 打分同口径）。

不读 H2/题干密文、不读 .env、不发任何真实 HTTP；只用 fixtures/acceptance 的公开语料。

输出：一份 JSON（stdout；给 --out 时同时写 UTF-8 文件）。用法（仓库根）：
  .venv/Scripts/python.exe -B -X utf8 docs/reports/OBS-EVAL/P2/T207/evidence/r4-ingest-probe.py \
    --out docs/reports/OBS-EVAL/P2/T207/evidence/r4-ingest-state.json
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import sys
import tempfile
import uuid
from pathlib import Path

HERE = Path(__file__).resolve()
REPO = HERE.parents[6]                     # docs/reports/OBS-EVAL/P2/T207/evidence -> repo root
T207 = HERE.parents[1]
sys.path.insert(0, str(REPO / "backend" / "src"))
os.chdir(REPO)

from mktkb.evaluation.dataset import CaseSpec, validate_case  # noqa: E402
from mktkb.evaluation.p2_scoring import (  # noqa: E402
    EXECUTION_MODE_LOCAL_MOCK,
    score_public_case,
)
from mktkb.evaluation.p2_score_run import (  # noqa: E402
    load_document_codes,
    source_index_from_rows,
)
from mktkb.evaluation.product_adapter import (  # noqa: E402
    MockChatBackend,
    P2RunDataset,
    ProductEvalAdapter,
    ingest_plan_from_document,
)
from mktkb.rag.providers import post_counters  # noqa: E402

INGEST_PLAN = T207 / "PM" / "T207-ingest-plan-R4.json"
CASES = T207 / "cases" / "R4.jsonl"
DOCUMENT_CODES = T207 / "cases" / "document-codes.json"
BATCH = 5


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class _EmbedRecorder:
    """包装离线 embedding：按 purpose 记录每次 embed() 的文本数（不改返回值/调用语义）。"""

    def __init__(self, inner) -> None:
        self.inner = inner
        self.calls: list[dict] = []

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def __repr__(self) -> str:  # 与真实 provider 一致：不含凭据
        return f"_EmbedRecorder({self.inner!r})"

    def embed(self, texts, *, purpose: str = "document"):
        self.calls.append({"purpose": str(purpose), "texts": len(texts)})
        return self.inner.embed(texts, purpose=purpose)


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


def document_state(adapter: ProductEvalAdapter) -> list[dict]:
    """只读产品库：逐文档的版本号/状态/激活版/单元数（不读正文）。"""
    from sqlalchemy import func, select

    from mktkb.documents.models import Document, DocumentVersion, SourceUnit

    db = adapter.app.state.db.session()
    try:
        rows = []
        for document in db.scalars(select(Document).order_by(Document.name, Document.id)).all():
            versions = db.scalars(
                select(DocumentVersion)
                .where(DocumentVersion.document_id == document.id)
                .order_by(DocumentVersion.number)
            ).all()
            per_version = []
            for version in versions:
                units = int(
                    db.scalar(
                        select(func.count())
                        .select_from(SourceUnit)
                        .where(SourceUnit.version_id == version.id)
                    )
                    or 0
                )
                per_version.append(
                    {
                        "number": int(version.number),
                        "state": str(version.state),
                        "sha256": str(version.sha256),
                        "is_active": version.id == document.active_version_id,
                        "published_at": None
                        if getattr(version, "published_at", None) is None
                        else str(version.published_at),
                        "units": units,
                    }
                )
            rows.append(
                {
                    "name": str(document.name),
                    "document_id": str(document.id),
                    "latest_version_number": int(document.latest_version_number),
                    "active_version_number": next(
                        (item["number"] for item in per_version if item["is_active"]), None
                    ),
                    "versions": per_version,
                }
            )
        return rows
    finally:
        db.close()


def state_checks(rows: list[dict], revision: int, index_documents: int) -> dict:
    """R4 灌库终态必须逐项成立（C05 与 C06 要**同一 KB 状态**）。"""
    fixtures = REPO / "fixtures" / "acceptance"
    sha = {
        "V03": sha256_of(fixtures / "variants" / "V03_物品位置表_历史V1.xlsx"),
        "D01": sha256_of(fixtures / "normal" / "D01_物品位置表.xlsx"),
        "V04": sha256_of(fixtures / "variants" / "V04_物品位置表_新版V3.xlsx"),
    }
    by_name = {row["name"]: row for row in rows}
    positions = by_name.get("D01_物品位置表.xlsx") or {"versions": []}

    def version(digest: str) -> dict | None:
        return next((item for item in positions["versions"] if item["sha256"] == digest), None)

    v03, d01, v04 = version(sha["V03"]), version(sha["D01"]), version(sha["V04"])
    v01 = by_name.get("V01_临时物料位置通知.pdf")
    d02 = by_name.get("D02_合作店家信息.xlsx")
    v02 = by_name.get("V02_店家联系方式变更通知.pdf")
    checks = {
        "document_count_is_4": {
            "hold": len(rows) == 4,
            "observed": len(rows),
            "why": "D01 槽 + V01 + D02 + V02（V03/V04 是同一槽的版本，不另建资料）",
        },
        "d01_slot_has_three_versions": {
            "hold": positions["latest_version_number"] == 3 and len(positions["versions"]) == 3,
            "observed": {
                "latest": positions["latest_version_number"],
                "versions": len(positions["versions"]),
            },
        },
        "v03_is_superseded_historical": {
            "hold": bool(v03) and v03["number"] == 1 and v03["state"] == "superseded"
            and not v03["is_active"],
            "observed": None if v03 is None else {"number": v03["number"], "state": v03["state"]},
        },
        "d01_is_active_v2": {
            "hold": bool(d01) and d01["number"] == 2 and d01["is_active"]
            and positions["active_version_number"] == 2,
            "observed": None if d01 is None else {
                "number": d01["number"], "is_active": d01["is_active"],
                "active_version_number": positions["active_version_number"],
            },
        },
        "v04_processed_but_not_published": {
            "hold": bool(v04) and v04["number"] == 3 and not v04["is_active"]
            and v04["state"] != "published",
            "observed": None if v04 is None else {
                "number": v04["number"], "state": v04["state"],
                "is_active": v04["is_active"], "published_at": v04["published_at"],
            },
            "why": "R4 不需要 U01 那种「未发布新版」语义之外的东西：v3 只处理、不发布",
        },
        "v01_active_v1": {
            "hold": bool(v01) and v01["active_version_number"] == 1,
            "observed": None if v01 is None else v01["active_version_number"],
        },
        "d02_and_v02_are_separate_active_documents": {
            "hold": bool(d02) and bool(v02) and d02["active_version_number"] == 1
            and v02["active_version_number"] == 1
            and d02["document_id"] != v02["document_id"],
            "observed": {
                "d02_active": None if d02 is None else d02["active_version_number"],
                "v02_active": None if v02 is None else v02["active_version_number"],
                "same_document": None if (d02 is None or v02 is None)
                else d02["document_id"] == v02["document_id"],
            },
            "why": "C06 的冲突来源必须是两份都有效的独立资料（D02 表格 + V02 通知）",
        },
        "product_revision_is_5": {
            "hold": revision == 5,
            "observed": revision,
            "why": "6 次上传、5 次发布（V04 不发布）→ 5 个 revision",
        },
        "index_has_four_documents": {
            "hold": index_documents == 4,
            "observed": index_documents,
            "why": "索引只收当前有效版（4 份资料）",
        },
    }
    return {
        "all_hold": all(item["hold"] for item in checks.values()),
        "checks": checks,
    }


async def raw_ask(adapter, question: str) -> dict:
    """同一产品 HTTP 入口的**原始**响应（含 conflicts 负载）：评分链丢掉的那部分在这里留证。"""
    session = adapter._session("employee")
    created = await session.client.post(
        "/api/v1/conversations", json={}, headers=session.write_headers
    )
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
        "source_count": len(payload.get("sources") or ()),
        "candidates": len(payload.get("candidates") or ()),
    }


def _case_row(case_id: str, product: dict) -> dict:
    return {
        "case_id": case_id,
        "status": "ok",
        "planned_turns": 1,
        "turns": [{"turn": 1, "status": "ok", "product": product}],
    }


async def measure_batches(plan_path: Path) -> dict:
    """对任意 ingest-plan 只测"灌库要几次 embedding POST 批"（与 run_once 同一产品路径）。"""
    plan = ingest_plan_from_document(json.loads(plan_path.read_text(encoding="utf-8")))
    tmp = Path(tempfile.mkdtemp(prefix="p2-batch-count-"))
    dataset = P2RunDataset(
        visibility="public",
        cases=(),
        identity={
            "dataset_version": "p2-batch-count",
            "label_version": "p2-batch-count",
            "suite": "p2-batch-count",
            "manifest_sha256": "f" * 64,
            "case_count": 0,
        },
    )
    adapter = ProductEvalAdapter(tmp / "count", chat=MockChatBackend(), dataset=dataset, ingest_plan=plan)
    recorder = _EmbedRecorder(adapter._embedder)
    adapter._embedder = recorder
    try:
        await adapter.start()
        receipts = await adapter.ingest()
        adapter._qa.ensure_ready()
        calls = [
            {"texts": item["texts"], "batches": math.ceil(item["texts"] / BATCH)}
            for item in recorder.calls
            if item["purpose"] == "document"
        ]
        return {
            "plan": str(plan_path.relative_to(REPO)),
            "plan_sha256": sha256_of(plan_path),
            "sources": len(plan.sources),
            "embedding_calls": calls,
            "batches_B": sum(item["batches"] for item in calls),
            "published_documents": sum(1 for item in receipts if item.published),
        }
    finally:
        await adapter.close()


async def run_once(*, gated: bool, capture_conflicts: bool = False) -> dict:
    """灌库 + 索引同步 + 三例逐题提问；gated=True 为 live 形状（每轮 1 次 query embedding）。"""
    payload = json.loads(INGEST_PLAN.read_text(encoding="utf-8"))
    plan = ingest_plan_from_document(payload)
    cases: list[CaseSpec] = []
    for line in CASES.read_text(encoding="utf-8").splitlines():
        if line.strip():
            case = CaseSpec.from_dict(json.loads(line))
            validate_case(case)
            cases.append(case)
    codes = load_document_codes(DOCUMENT_CODES)

    tmp = Path(tempfile.mkdtemp(prefix="p2-r4-state-"))
    chat = MockChatBackend()
    dataset = P2RunDataset(
        visibility="public",
        cases=(),
        identity={
            "dataset_version": "p2-r4-probe",
            "label_version": "p2-r4-probe",
            "suite": "p2-r4",
            "manifest_sha256": "e" * 64,
            "case_count": 0,
        },
    )
    adapter = ProductEvalAdapter(tmp / "r4", chat=chat, dataset=dataset, ingest_plan=plan)
    recorder = _EmbedRecorder(adapter._embedder)
    adapter._embedder = recorder  # 只换离线替身，产品代码零改动（索引建在此之后）
    try:
        await adapter.start()
        receipts = await adapter.ingest()
        adapter._qa.ensure_ready()          # 首个提问前的产品索引同步（只索引当前有效版）
        rows = document_state(adapter)
        revision = adapter.product_revision()
        index_status = {k: v for k, v in adapter.index_status().items() if k != "error"}
        ingest_calls = list(recorder.calls)

        gate = _PerTurnQueryGate(adapter._qa.index().embedder)
        if gated:
            adapter._qa.index().embedder = gate

        case_results = []
        raw_results = []
        scored_rows: dict[str, dict] = {}
        for case in cases:
            conversation = await adapter.open_conversation()
            gate.begin_turn()
            calls_before = len(chat.calls)
            embeds_before = len(recorder.calls)
            turn = await adapter.ask_turn(
                case.question,
                user_id="employee",
                conversation_id=conversation,
                client_request_id=str(uuid.uuid4()),
            )
            product = turn.as_dict(include_text=True)
            scored_rows[case.case_id] = _case_row(case.case_id, product)
            query_calls = [item for item in recorder.calls[embeds_before:] if item["purpose"] == "query"]
            case_results.append(
                {
                    "case_id": case.case_id,
                    "question_sha256": hashlib.sha256(case.question.encode("utf-8")).hexdigest(),
                    "expected_kind": case.expected_kind,
                    "kind": turn.kind,
                    "text": turn.text,
                    "http_status": turn.http_status,
                    "candidates": turn.candidates,
                    "sources": [
                        {
                            "document_name": item.get("document_name"),
                            "version_number": item.get("version_number"),
                            "document_code": codes.get(str(item.get("document_name") or "")),
                        }
                        for item in turn.sources
                    ],
                    "source_count": len(turn.sources),
                    "retrieved_units": len(turn.retrieved),
                    "model_calls_this_turn": len(chat.calls) - calls_before,
                    "model_calls_by_purpose": {
                        purpose: sum(
                            1 for call in chat.calls[calls_before:] if call["purpose"] == purpose
                        )
                        for purpose in ("answer", "query_expansion")
                    },
                    "query_embedding_attempts": len(query_calls),
                    "query_embedding_refused": gate.refused,
                }
            )
            if capture_conflicts:
                raw_results.append({"case_id": case.case_id, **(await raw_ask(adapter, case.question))})

        source_index = source_index_from_rows(scored_rows)
        scoring = []
        for case in cases:
            scored = score_public_case(
                case,
                scored_rows[case.case_id],
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
                        {"check_id": item["check_id"], "status": item["status"], "evidence": item.get("evidence") or {}}
                        for item in scored.score.checks
                    ],
                    "issues": [item.to_dict() for item in scored.score.issues],
                }
            )

        document_calls = [item for item in ingest_calls if item["purpose"] == "document"]
        per_call = [
            {"texts": item["texts"], "batches": math.ceil(item["texts"] / BATCH)}
            for item in document_calls
        ]
        receipts_payload = [
            {
                "name": item.name,
                "published": bool(item.published),
                "publish_status": item.publish_status,
                "units": item.units,
                "document_id": item.document_id,
                "version_id": item.version_id,
            }
            for item in receipts
        ]
        batches = sum(item["batches"] for item in per_call)
        return {
            "mode": "live_like_gate" if gated else "ungated",
            "receipts": receipts_payload,
            "documents": rows,
            "state_checks": state_checks(rows, revision, int(index_status.get("documents") or 0)),
            "index_status": index_status,
            "product_revision": revision,
            "embedding_calls": per_call,
            "batches_B": batches,
            "uploaded_documents_upper_bound": sum(
                max(1, math.ceil((item["units"] or 0) / BATCH)) for item in receipts_payload
            ),
            "cases": case_results,
            "cases_raw_payload": raw_results,
            "scoring": scoring,
            "post_counters": {kind: dict(value) for kind, value in post_counters().items()},
            "mock_mode": adapter.is_mock,
        }
    finally:
        await adapter.close()


async def main() -> dict:
    gated = await run_once(gated=True, capture_conflicts=False)
    ungated = await run_once(gated=False, capture_conflicts=True)
    crosscheck = {
        "R2": await measure_batches(T207 / "PM" / "T207-ingest-plan-R2.json"),
        "R3": await measure_batches(T207 / "PM" / "T207-ingest-plan-R3.json"),
    }
    return {
        "probe": "P2-T207-R4PREP：R4 灌库终态 + B_r4 + 三例 live 形状复核（Mock，零真实调用）",
        "ingest_plan": {
            "path": str(INGEST_PLAN.relative_to(REPO)),
            "sha256": sha256_of(INGEST_PLAN),
            "label": json.loads(INGEST_PLAN.read_text(encoding="utf-8")).get("label"),
            "sources": len(json.loads(INGEST_PLAN.read_text(encoding="utf-8")).get("sources") or ()),
        },
        "cases_file": {"path": str(CASES.relative_to(REPO)), "sha256": sha256_of(CASES)},
        "batch_size": BATCH,
        # 终态/批数取 live 形状那一次（与真实 run 的唯一差别是 provider 是替身）
        "receipts": gated["receipts"],
        "documents": gated["documents"],
        "state_checks": gated["state_checks"],
        "index_status": gated["index_status"],
        "product_revision": gated["product_revision"],
        "embedding_calls": gated["embedding_calls"],
        "batches_B": gated["batches_B"],
        "batches_B_formula": "sum(ceil(每次 embed 的待嵌入文本数 / 5))（只对当前有效版建索引）",
        "batches_B_upper_bound": gated["uploaded_documents_upper_bound"],
        "batches_B_note": (
            "上界口径=每次发布会重新嵌入当前有效版的全部单元（无缓存复用）；"
            "实测口径=产品按 content_sha256 复用全局 embedding 缓存，只嵌增量"
        ),
        "batches_B_repeat_ungated": ungated["batches_B"],
        "batches_B_deterministic": gated["batches_B"] == ungated["batches_B"],
        "state_checks_repeat_ungated": ungated["state_checks"]["all_hold"],
        "cases_gated": gated["cases"],
        "cases_ungated": ungated["cases"],
        "cases_ungated_raw_payload": ungated["cases_raw_payload"],
        "scoring_gated": gated["scoring"],
        "scoring_ungated": ungated["scoring"],
        # 方法学自证：同一测量法对 R2/R3 的灌库计划给出的批数，必须等于 live 账本里
        # 这两个 run 的 ingest-index-embedding 预留数（R2=4、R3=2）。
        "crosscheck_r2_r3": {
            **crosscheck,
            "live_ledger_ingest_reservations": {"R2": 4, "R3": 2},
            "matches_live": {
                "R2": crosscheck["R2"]["batches_B"] == 4,
                "R3": crosscheck["R3"]["batches_B"] == 2,
            },
        },
        "post_counters": gated["post_counters"],
        "document_codes_mapping": {
            "path": str(DOCUMENT_CODES.relative_to(REPO)),
            "entries": len(load_document_codes(DOCUMENT_CODES)),
            "note": "只按产品文档名映射；版本号不进映射（与 live 打分同口径，V03/V04 会被映射成 D01）",
        },
        "mock_mode": gated["mock_mode"],
    }


if __name__ == "__main__":
    text = json.dumps(asyncio.run(main()), ensure_ascii=False, indent=1)
    out_index = sys.argv.index("--out") + 1 if "--out" in sys.argv else None
    if out_index is not None:
        Path(sys.argv[out_index]).write_text(text + "\n", encoding="utf-8")
    print(text)

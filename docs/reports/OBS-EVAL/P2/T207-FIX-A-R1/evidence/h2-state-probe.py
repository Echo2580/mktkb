"""P2-T207-FIX-A-R1：H2 灌库方案的**离线**状态验证 + 批数 B（零真实调用、零出网）。

做法（全部走产品代码，不另立一套口径）：
- 用 docs/reports/OBS-EVAL/P2/T207/PM/T207-ingest-plan-H2.json 驱动 ProductEvalAdapter 的
  Mock 路径（产品上传 -> worker 解析 -> 发布，全部经产品 HTTP 路由；chat/embedding 都是离线替身）；
- 灌库后触发一次产品索引同步（等同首个提问前的 ensure_ready；qa/service.py:286-345），
  用包装后的 embedding 计数每次 embed() 的文本数 -> 批数 = ceil(texts / embedding_batch_size=5)
  （真实 provider 按批拆 POST：rag/providers.py:292-298；产品参数 product_adapter.py:1088）；
- 只读产品库，逐文档/版本核对 custodian-report §6 的五条 stale_conflict 假设；
- 不读 H2 题干/答案/密文/key；只用 fixtures/acceptance 的公开语料。

输出：一份 JSON（stdout；给 --out 时同时写 UTF-8 文件）。用法（仓库根）：
  .venv/Scripts/python.exe -B -X utf8 docs/reports/OBS-EVAL/P2/T207-FIX-A-R1/evidence/h2-state-probe.py --out <json>
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
REPO = HERE.parents[6]  # …/T207-FIX-A-R1/evidence/<script> -> 仓库根
sys.path.insert(0, str(REPO / "backend" / "src"))
os.chdir(REPO)

from mktkb.evaluation.product_adapter import (  # noqa: E402
    ChatBehavior,
    MockChatBackend,
    P2RunDataset,
    ProductEvalAdapter,
    ingest_plan_from_document,
)
from mktkb.rag.providers import post_counters  # noqa: E402

PLAN_PATH = REPO / "docs" / "reports" / "OBS-EVAL" / "P2" / "T207" / "PM" / "T207-ingest-plan-H2.json"
FIXTURES = REPO / "fixtures" / "acceptance"
BATCH = 5

CODE_BY_NAME = {
    "D01_物品位置表.xlsx": "D01",
    "V03_物品位置表_历史V1.xlsx": "V03",
    "V04_物品位置表_新版V3.xlsx": "V04",
    "V05_物品位置表_新版V3_移除P01.xlsx": "V05",
    "D02_合作店家信息.xlsx": "D02",
    "V06_合作店家信息_新电话.xlsx": "V06",
    "V01_临时物料位置通知.pdf": "V01",
    "V07_物料位置独立通知.pdf": "V07",
    "D03_市场部工作指南.docx": "D03",
    "D04_活动策划流程.docx": "D04",
    "D05_物料领用规范.pdf": "D05",
    "D06_店家资料维护说明.pdf": "D06",
}


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class _EmbedRecorder:
    """包装离线 embedding，只记录每次 embed() 的文本数（不改变返回值/调用次数语义）。"""

    def __init__(self, inner) -> None:
        self.inner = inner
        self.calls: list[int] = []

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def __repr__(self) -> str:  # 与真实 provider 一致：不含凭据
        return f"_EmbedRecorder({self.inner!r})"

    def embed(self, texts, *, purpose: str = "document"):
        self.calls.append(len(texts))
        return self.inner.embed(texts, purpose=purpose)


def document_state(adapter: ProductEvalAdapter):
    """只读产品库：逐文档的版本号/状态/激活版/单元数（不读正文）。"""
    from sqlalchemy import func, select

    from mktkb.documents.models import Document, DocumentVersion, SourceUnit

    db = adapter.app.state.db.session()
    try:
        rows = []
        for document in db.scalars(select(Document).order_by(Document.name)).all():
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


def hypotheses(rows, receipts) -> dict:
    """把 custodian-report §6 的五条假设翻成可核对的状态断言（只读公开语料）。"""
    by_name = {row["name"]: row for row in rows}
    positions = by_name.get("D01_物品位置表.xlsx")
    partners = by_name.get("D02_合作店家信息.xlsx")
    v01 = by_name.get("V01_临时物料位置通知.pdf")
    v07 = by_name.get("V07_物料位置独立通知.pdf")
    sha = {name: sha256_of(path) for name, path in {
        "V03": FIXTURES / "variants" / "V03_物品位置表_历史V1.xlsx",
        "V04": FIXTURES / "variants" / "V04_物品位置表_新版V3.xlsx",
        "V05": FIXTURES / "variants" / "V05_物品位置表_新版V3_移除P01.xlsx",
        "V06": FIXTURES / "variants" / "V06_合作店家信息_新电话.xlsx",
    }.items()}

    def version_by_sha(document, digest):
        return next((item for item in (document or {}).get("versions", []) if item["sha256"] == digest), None)

    v03 = version_by_sha(positions, sha["V03"])
    v04 = version_by_sha(positions, sha["V04"])
    v05 = version_by_sha(positions, sha["V05"])
    v06 = version_by_sha(partners, sha["V06"])
    return {
        "H1_only_v03_is_historical_version": {
            "hold": bool(v03) and v03["state"] == "superseded" and not v03["is_active"],
            "observed": None if v03 is None else {"number": v03["number"], "state": v03["state"]},
        },
        "H2_v04_published_as_v3": {
            "hold": bool(v04) and v04["number"] == 3 and v04["published_at"] is not None,
            "observed": None
            if v04 is None
            else {
                "number": v04["number"],
                "state": v04["state"],
                "published_at": v04["published_at"],
                "is_active": v04["is_active"],
            },
            "note": "v3 之后 V05 又发布为 v4：v3 保留在版本历史里且已发布，但**不再是当前有效版**。",
        },
        "H3_v01_and_d01_both_active_conflict": {
            "hold": bool(v01) and v01["active_version_number"] is not None and bool(positions)
            and positions["active_version_number"] is not None,
            "observed": {
                "v01_active": None if v01 is None else v01["active_version_number"],
                "d01_slot_active": None if positions is None else positions["active_version_number"],
            },
        },
        "H4_v06_published_replacing_d02": {
            "hold": bool(v06) and v06["is_active"] and partners["latest_version_number"] == v06["number"],
            "observed": None
            if v06 is None
            else {
                "number": v06["number"],
                "is_active": v06["is_active"],
                "d02_latest": partners["latest_version_number"],
            },
        },
        "H5_v05_published_deleted_row_and_v07_still_valid": {
            "hold": bool(v05) and bool(v04) and v05["state"] == "published" and v05["is_active"]
            and v05["units"] == v04["units"] - 1
            and bool(v07) and v07["active_version_number"] == 1,
            "observed": {
                "v05_number": None if v05 is None else v05["number"],
                "v05_state": None if v05 is None else v05["state"],
                "v05_units": None if v05 is None else v05["units"],
                "v04_units": None if v04 is None else v04["units"],
                "v07_active": None if v07 is None else v07["active_version_number"],
            },
            "note": "行数：V05 比 V04 少一行（P01 被删）；V07 是独立资料且仍是当前有效版。",
        },
    }


async def main() -> dict:
    payload = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
    plan = ingest_plan_from_document(payload)
    tmp = Path(tempfile.mkdtemp(prefix="p2-h2-state-"))
    chat = MockChatBackend(behaviors=(ChatBehavior(answer="（离线探针不问答）"),))
    dataset = P2RunDataset(
        visibility="public",
        cases=(),
        identity={
            "dataset_version": "p2-h2-probe",
            "label_version": "p2-h2-probe",
            "suite": "p2-holdout",
            "manifest_sha256": "d" * 64,
            "case_count": 0,
        },
    )
    adapter = ProductEvalAdapter(
        tmp / "h2-state", chat=chat, dataset=dataset, ingest_plan=plan, purge_traces_on_close=True
    )
    recorder = _EmbedRecorder(adapter._embedder)
    adapter._embedder = recorder  # 只换离线替身，产品代码零改动
    try:
        await adapter.start()
        receipts = await adapter.ingest()
        # 首个提问前的产品索引同步（qa/service.py:286-345）；只索引"当前有效版"。
        adapter._qa.ensure_ready()
        rows = document_state(adapter)
        receipts_payload = [
            {
                "name": item.name,
                "code": CODE_BY_NAME.get(item.name, item.name),
                "published": bool(item.published),
                "publish_status": item.publish_status,
                "units": item.units,
                "document_id": item.document_id,
                "version_id": item.version_id,
            }
            for item in receipts
        ]
        per_call = [{"texts": texts, "batches": math.ceil(texts / BATCH)} for texts in recorder.calls]
        result = {
            "plan_label": plan.label,
            "sources": len(plan.sources),
            "batch_size": BATCH,
            "receipts": receipts_payload,
            "documents": rows,
            "index_status": {k: v for k, v in adapter.index_status().items() if k != "error"},
            "embedding_calls": per_call,
            "batches_B": sum(item["batches"] for item in per_call),
            "batches_B_formula": "sum(ceil(每次 embed 的待嵌入文本数 / 5))（只对当前有效版建索引）",
            # 上界口径：若每个上传版本都被建索引（含历史版），批数上限 = Σ ceil(单元数/5)。
            "uploaded_documents_upper_bound": sum(
                max(1, math.ceil((item["units"] or 0) / BATCH)) for item in receipts_payload
            ),
            "hypotheses": hypotheses(rows, receipts),
            "post_counters": {kind: dict(value) for kind, value in post_counters().items()},
            "product_revision": adapter.product_revision(),
            "mock_mode": adapter.is_mock,
        }
    finally:
        await adapter.close()
    return result


if __name__ == "__main__":
    text = json.dumps(asyncio.run(main()), ensure_ascii=False, indent=1)
    out_index = sys.argv.index("--out") + 1 if "--out" in sys.argv else None
    if out_index is not None:
        Path(sys.argv[out_index]).write_text(text + "\n", encoding="utf-8")
    print(text)

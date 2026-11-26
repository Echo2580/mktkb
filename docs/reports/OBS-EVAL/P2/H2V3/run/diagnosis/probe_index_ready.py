"""离线复现 v3 r0 的 INDEX_NOT_READY（零网络、零真实请求）。

做什么
------
1. 用**产品自己的** ingest 路径（上传 -> worker 解析 -> 发布 -> 发布钩子 qa.sync）灌入
   指定 scenario 的 v3 ingest 源；embedding 用离线假 provider，不联网、不读凭据。
2. 假 provider 记录每次 embed() 的待嵌入文本数，并按 live 的
   ``embedding_batch_size=5`` 折算真实 POST 批数（live 里一次 POST 一批）。
3. 可选 cap = 计划项 ``index_embedding`` 的 requests 上界；超限的那一批**在发送前**抛
   ``BudgetLedgerInvalid``（与 ``p2_live.GateAttemptLedger.reserve`` 的拒绝同码同位置）。
4. 灌库后把 QaEngine 配置改成 live 口径 ``require_zero_retries=True``，调用
   ``qa.prepare`` —— 这正是产品回合里 INDEX_NOT_READY 之前的那一步，记录异常码。

不做什么：不发任何 HTTP 出站（chat=None -> 无 provider）、不读数据集/题面、不写仓内文件。

用法（cwd 必须是仓库根）：
    python probe_index_ready.py --scenario base_b0 [--cap 8]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import shutil
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[0]
REPO = Path(r"D:\GPT项目\市场部AI知识库")
sys.path.insert(0, str(REPO / "backend" / "src"))

from dataclasses import replace  # noqa: E402

from mktkb.evaluation.p2_holdout_scenarios import RECIPES  # noqa: E402
from mktkb.evaluation.product_adapter import (  # noqa: E402
    MockEmbeddingProvider,
    P2IngestPlan,
    ProductEvalAdapter,
    ingest_plan_from_document,
)
from mktkb.rag.errors import BudgetLedgerInvalid  # noqa: E402
from mktkb.qa.service import QaNotReady  # noqa: E402

V3_INGEST = REPO / "docs/reports/OBS-EVAL/P2/H2V3/PM/p2-ingest-plan-H2-v3.json"
BUSINESS_DATE = {
    "base_b0": "2026-10-15",
    "base_b0_plus_v01": "2026-07-15",
    "pre_v05_without_v07": "2026-11-20",
    "post_v05_without_v01": "2026-12-15",
}
LIVE_EMBEDDING_BATCH = 5  # product_adapter._start_live: embedding_batch_size=5


class CountingCapEmbedding:
    """离线假 embedding + live 批次口径计数 + 计划项配额拒绝（发送前）。"""

    provider = "offline-fake"
    model = "text-embedding-v4"
    dimensions = 1024

    def __init__(self, *, cap: int | None, batch: int = LIVE_EMBEDDING_BATCH) -> None:
        self._inner = MockEmbeddingProvider()
        self._cap = cap
        self._batch = int(batch)
        self.calls = 0
        self.posts = 0
        self.texts = 0
        self.events: list[dict] = []
        self.refusals: list[dict] = []

    def __repr__(self) -> str:
        return "CountingCapEmbedding(offline-fake)"

    def embed(self, texts, *, purpose: str = "document"):
        texts = list(texts)
        n = len(texts)
        batches = max(1, math.ceil(n / self._batch)) if n else 0
        self.calls += 1
        allowed = batches if self._cap is None else max(0, min(batches, self._cap - self.posts))
        self.posts += allowed
        self.texts += n
        self.events.append(
            {"call": self.calls, "purpose": str(purpose), "texts": n,
             "batches": batches, "allowed": allowed, "posts_after": self.posts}
        )
        if allowed < batches:
            self.refusals.append(
                {"call": self.calls, "texts": n, "batches": batches,
                 "allowed": allowed, "cap": self._cap, "posts_before": self.posts - allowed}
            )
            raise BudgetLedgerInvalid(
                "P2 计划项配额拒绝：attempt_quota_exhausted "
                f"ingest-index-embedding 已用 {self.posts}/{self._cap}"
            )
        return self._inner.embed(texts, purpose=purpose)

    def as_dict(self) -> dict:
        return {"calls": self.calls, "posts": self.posts, "texts": self.texts,
                "cap": self._cap, "batch": self._batch,
                "refusals": list(self.refusals), "events": list(self.events)}


def scenario_sources(scenario: str):
    index = [name for name, _src, _b in RECIPES].index(scenario)
    _name, sources, batches = RECIPES[index]
    document = json.loads(V3_INGEST.read_text(encoding="utf-8"))
    chosen = [document["sources"][i] for i in sources]
    plan_doc = {"schema_version": document["schema_version"], "label": f"diag-{scenario}",
                "sources": chosen}
    return ingest_plan_from_document(plan_doc), list(sources), int(batches)


def _index_meta(adapter) -> dict:
    qa = adapter._qa
    index = qa.index()
    keys = (
        "product_revision",
        "product_sync_status",
        "product_sync_error_code",
        "product_sync_error",
        "product_documents",
        "product_units",
    )
    meta = {key: index.get_meta(key) for key in keys}
    stats = index.stats()
    meta["rag_revision"] = stats["revision"]
    meta["chunks"] = stats["chunks"]
    meta["chunk_embeddings"] = stats["chunk_embeddings"]
    meta["embedding_cache"] = stats["embedding_cache"]
    meta["documents"] = stats["documents"]
    meta["embedding_stats"] = stats["embedding_stats"]
    return meta


async def run(scenario: str, cap: int | None, defer: bool = False) -> dict:
    plan, source_indices, batches = scenario_sources(scenario)
    out_dir = ROOT / "out" / f"{scenario}-cap{cap if cap is not None else 'none'}{'-defer' if defer else ''}"
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    embedder = CountingCapEmbedding(cap=cap)
    adapter = ProductEvalAdapter(
        out_dir,
        ingest_plan=plan,
        dataset=None,
        chat=None,
        rag_business_date=BUSINESS_DATE[scenario],
        manifest_business_date=BUSINESS_DATE[scenario],
        label=f"diag-{scenario}",
    )
    adapter._embedder = embedder  # 探针注入：离线假 provider（无传输层）
    result: dict = {"scenario": scenario, "cap": cap, "defer_sync": defer, "planned_batches": batches,
                    "source_indices": source_indices, "sources": len(plan.sources)}
    try:
        await adapter.start()
        # start 内的 ensure_ready 已建好空索引；随后把配置切到 live 口径（产品 live 装配同值）。
        adapter._qa.config = replace(
            adapter._qa.config,
            require_zero_retries=True,
            max_retries=0,
            embedding_batch_size=LIVE_EMBEDDING_BATCH,
        )
        stamp_before = dict(embedder.as_dict())
        prepared_index = None
        if defer:
            # 模拟“编排层修复”：灌库期暂停发布钩子的逐次同步，灌库后一次性正式同步。
            # 只在探针进程内改 app.state.qa（产品代码/仓内文件零改动）。
            app_qa = getattr(adapter._app.state, "qa", None)
            adapter._app.state.qa = None
            try:
                receipts = await adapter.ingest()
            finally:
                adapter._app.state.qa = app_qa
            try:
                adapter._qa.ensure_ready()
                prepared_index = {"ok": True, "error_code": None}
            except QaNotReady as exc:
                prepared_index = {"ok": False, "error_code": getattr(exc, "code", None)}
            result["deferred_sync"] = {"applied": True, "post_ingest_ensure_ready": prepared_index}
        else:
            receipts = await adapter.ingest()
        result["ingest"] = {
            "receipts": len(receipts),
            "published": sum(1 for r in receipts if r.published),
            "revision_last": receipts[-1].revision if receipts else None,
            "units": [r.units for r in receipts],
            "upload_status": [r.upload_status for r in receipts],
            "publish_status": [r.publish_status for r in receipts],
        }
        result["embedding_during_ingest"] = {
            "calls": embedder.calls - stamp_before["calls"],
            "posts": embedder.posts - stamp_before["posts"],
            "texts": embedder.texts - stamp_before["texts"],
            "refusals": list(embedder.refusals),
        }
        result["index_after_ingest"] = _index_meta(adapter)
        result["adapter_index_status"] = adapter.index_status()

        # 产品回合里 INDEX_NOT_READY 之前的最后一步：qa.prepare -> ensure_ready。
        posts_before_prepare = embedder.posts
        try:
            adapter._qa.prepare("诊断探针", "employee", "diag-conversation")
            result["prepare"] = {"ok": True, "error_code": None}
        except QaNotReady as exc:
            result["prepare"] = {"ok": False, "error_code": getattr(exc, "code", None),
                                 "message": str(exc)}
        except Exception as exc:  # noqa: BLE001
            result["prepare"] = {"ok": False, "error_code": type(exc).__name__,
                                 "message": str(exc)}
        result["prepare"]["posts_at_prepare"] = embedder.posts - posts_before_prepare
        result["index_after_prepare"] = _index_meta(adapter)
        result["embedding_total"] = embedder.as_dict()
    except Exception as exc:  # noqa: BLE001
        result["fatal"] = {"type": type(exc).__name__, "code": getattr(exc, "code", None),
                           "error": str(exc), "trace": traceback.format_exc()[-1500:]}
    finally:
        try:
            await adapter.close()
        except Exception as exc:  # noqa: BLE001
            result["close_error"] = f"{type(exc).__name__}:{exc}"
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--cap", type=int, default=None)
    parser.add_argument("--defer-sync", action="store_true")
    parser.add_argument("--out", default=None)
    args = parser.parse_args()
    payload = asyncio.run(run(args.scenario, args.cap, defer=args.defer_sync))
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()

"""从零网络离线回放结果导出「v3 ingest 批数 census」（计划生成的新输入）。

为什么需要它
------------
v3 计划项 ``index_embedding.requests`` 原先取冻结 v2 配方常量
``p2_holdout_scenarios.RECIPES[i][2]`` = 8/9/11/13；但 v3 语料的块数/版本序列不同，
产品在「每次 publish 同步一次索引」下的实际 POST 批数是 9/10/13/15（诊断包已逐码复现）。
本脚本把**实测到的逐源批数**固化成数据件，供 v3 入口按 scenario 的源下标求和派生；
v2 配方语义（``RECIPES``）一字不动。

数据来源（只读、零网络）
------------------------
``run/diagnosis/offline-repro.json``：用产品自身 ingest 路径（上传 202 → worker 解析 →
publish 200 → 发布钩子 ``qa.sync``）重放四 scenario，embedding 用离线假 provider，
按 live ``embedding_batch_size=5`` 折算真实 POST 批数（一次 ``embed()`` 一批）。
其中 ``cap=null, defer_sync=false`` 的四条就是「现状产品语义」下的实测。

派生规则（与产品同规则，不是再拍一个常量）
------------------------------------------
一次 publish 只对它首次可见的那份文档发 ``embed()``，批数 = ceil(待嵌入文本数/5)；
``per_publish_embed_posts[k]`` 即该 scenario 第 k 个发布源的实测批数，
``embed_posts_required`` = 它们之和。census 把逐源批数写成 ``per_source``，
入口再按 scenario 的 ``source_indices`` 求和并与合计交叉校验（任一不符即 fail-closed）。

产物：``ingest-batch-census.json``（UTF-8、无 BOM、indent=2、单尾随换行）。
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[6]
sys.path.insert(0, str(REPO / "backend" / "src"))
from mktkb.evaluation.p2_holdout_scenarios import RECIPES  # noqa: E402  (只读)

REPRO = REPO / "docs/reports/OBS-EVAL/P2/H2V3/run/diagnosis/offline-repro.json"
OUT = HERE / "ingest-batch-census.json"

EXPECTED = {
    "base_b0": 9,
    "base_b0_plus_v01": 10,
    "pre_v05_without_v07": 13,
    "post_v05_without_v01": 15,
}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    raw = REPRO.read_bytes()
    payload = json.loads(raw.decode("utf-8"))
    runs = payload["runs"]
    selected = [
        row
        for row in runs
        if row.get("cap") is None and row.get("defer_sync") is False
    ]
    if len(selected) != 4:
        raise SystemExit(f"expected 4 baseline runs, got {len(selected)}")
    scenarios: dict[str, dict] = {}
    per_source: dict[str, dict] = {}
    recipe_sources = {name: tuple(int(i) for i in indices) for name, indices, _batches in RECIPES}
    for row in selected:
        scenario = str(row["scenario_id"])
        indices = list(recipe_sources[scenario])
        batches = [int(b) for b in row["per_call_batches"]]
        if len(indices) != len(batches):
            raise SystemExit(f"{scenario}: source/batch length mismatch")
        total = sum(batches)
        if total != EXPECTED[scenario] or total != int(row["posts_needed_or_sent"]):
            raise SystemExit(f"{scenario}: unexpected required batches {total}")
        scenarios[scenario] = {
            "source_indices": indices,
            "published_sources": len(indices),
            "per_publish_embed_posts": batches,
            "embed_posts_required": total,
            "product_revision": row.get("product_revision"),
            "chunks_final": row.get("chunks"),
            "unique_texts": row.get("unique_texts"),
            "prepare_ok": row.get("prepare_ok"),
            "sync_status": row.get("sync_status"),
        }
        for index, count in zip(indices, batches):
            key = str(index)
            if key in per_source and int(per_source[key]["embed_posts"]) != count:
                raise SystemExit(f"source {key} measured twice with different counts")
            per_source[key] = {"embed_posts": count}
    if {int(key) for key in per_source} != set(range(12)):
        raise SystemExit("per_source does not cover the 12 v3 ingest sources")

    document = {
        "schema_version": "p2-h2v3-ingest-batch-census/v0.1",
        "role": "v3 计划 index_embedding 上界的数据来源（按 v3 实际内容实测派生；不改 v2 配方）",
        "method": (
            "零网络离线回放：产品自身 ingest 路径（上传 202 → worker → publish 200 → 发布钩子 "
            "qa.sync），embedding 用离线假 provider；live embedding_batch_size=5 ⇒ 一次 embed() "
            "一批 POST。per_publish_embed_posts 是第 k 个发布源那次 embed() 的批数。"
        ),
        "batch_size": 5,
        "source_evidence": {
            "path": str(REPRO.relative_to(REPO)).replace("\\", "/"),
            "sha256": _sha(REPRO),
            "bytes": len(raw),
            "selection": "cap=null 且 defer_sync=false（现状产品语义：每次 publish 同步一次）",
        },
        "scenarios": scenarios,
        "per_source": per_source,
        "totals": {
            "scenarios": len(scenarios),
            "sources_covered": len(per_source),
            "embed_posts_all_runs": sum(row["embed_posts_required"] for row in scenarios.values()),
            "v2_recipe_batches_all_runs": 8 + 9 + 11 + 13,
        },
        "zero_network": True,
        "note": (
            "本件只固化实测事实，不含题干/答案/case_id/query 文本；计划生成只按源下标求和，"
            "任一 scenario 合计与实测不符即拒绝签发计划。"
        ),
    }
    text = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
    OUT.write_text(text, encoding="utf-8")
    print(
        json.dumps(
            {
                "out": str(OUT),
                "sha256": _sha(OUT),
                "bytes": OUT.stat().st_size,
                "required": {name: row["embed_posts_required"] for name, row in scenarios.items()},
                "per_source": per_source,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

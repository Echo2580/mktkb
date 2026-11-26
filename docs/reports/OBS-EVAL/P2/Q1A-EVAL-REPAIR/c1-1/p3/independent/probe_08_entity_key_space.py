"""C1-P3 独立验收补充探针：目标侧 entity 键（合同 v2 R-ENT-1 → chunking._entity）
与运行期身份键的**键空间**对照。

只用公开函数与合成记录；不读私有密文/题面/答案。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = next(
    parent
    for parent in HERE.parents
    if (parent / "backend" / "src" / "mktkb").is_dir() and (parent / "docs").is_dir()
)
sys.path.insert(0, str(HERE))

from mktkb.rag.chunking import DocumentSpec, _entity  # noqa: E402

CACHE = json.loads((HERE / "out" / "02-capture-cache.json").read_text(encoding="utf-8"))
CORPUS = CACHE["corpus"]


def main() -> int:
    record = {
        "编号": "W01",
        "物品名称": "折叠桌",
        "门店": "城北店",
        "数量": 12,
    }
    doc = DocumentSpec(
        doc_id="S01",
        source_path="synth_stock.xlsx",
        title="独立验收仓储",
        file_kind="xlsx",
        version_id="V1",
        version_label="V1",
        sha256="0" * 64,
    )
    entity_type, entity_key, label, filters, filters_norm = _entity(record, doc=doc)
    runtime_keys = sorted(
        {
            str(row.get("entity_key"))
            for snap in CACHE["snapshots"]
            for row in snap["record_identities"]
            if row.get("entity_key")
        }
    )
    result = {
        "probe": "entity-key-space",
        "target_side_rule": "合同 v2 R-ENT-1：chunking._entity(records[record_key], DocumentSpec(doc_id=base_doc_code))",
        "target_side_computed": {
            "entity_type": entity_type,
            "entity_key": entity_key,
            "label": label,
            "filters": filters,
            "filters_norm": filters_norm,
        },
        "runtime_side_keys": runtime_keys,
        "key_equality_holds": entity_key in runtime_keys,
        "filters_role_overlap": sorted(set(filters) & {"store", "item", "product", "channel", "price_type", "identifier"}),
        "verdict": "EQUAL" if entity_key in runtime_keys else "KEY_SPACE_MISMATCH",
        "note": (
            "目标侧由 chunking._entity 产生名称型键（如 item|城北店|折叠桌）；运行期在有 id 表头时"
            "产生 id 型键（item|id:w01），无 id 表头时产生 item|…|doc:<uuid>|unit:<uuid> 复合键。"
            "三种键空间互不相等 → 契约 §7.2(3) 的等式匹配不可直接执行。"
        ),
    }
    (HERE / "out" / "08-entity-key-space.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

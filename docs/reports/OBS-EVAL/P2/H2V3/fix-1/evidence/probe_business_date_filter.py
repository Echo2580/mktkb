"""v3-fix-1/B 证据：legacy 证据面按业务日过滤的“过滤前 / 过滤后”同输入对比。

与 ``tests/rag/test_v3_fix1_business_date_filter.py`` 同一构造（真实 LegacyIndex +
SourceUnit + 检索索引），输出机读 JSON。离线、零真实调用。
"""

from __future__ import annotations

import hashlib
import json
import socket
import tempfile
from pathlib import Path

from mktkb.rag import AtomicUnit, DocumentSpec
from mktkb.rag.legacy import LegacyIndex
from mktkb.retrieval.service import retrieve
from mktkb.retrieval.types import QueryIntent

OUTBOUND: list[str] = []
INTENT = QueryIntent(
    mode="record",
    entity_filters={"store": "城东店", "item": "宣传海报"},
    requested_fields=("位置",),
)


def _install_guard() -> None:
    def deny(*args, **kwargs):
        OUTBOUND.append(f"connect:{args!r}")
        raise OSError("netguard: outbound blocked")

    socket.socket.connect = deny  # type: ignore[assignment]
    socket.socket.connect_ex = deny  # type: ignore[assignment]
    socket.create_connection = deny  # type: ignore[assignment]
    socket.getaddrinfo = deny  # type: ignore[assignment]


def _doc(doc_id: str, label: str) -> DocumentSpec:
    return DocumentSpec(
        doc_id=doc_id,
        logical_id=doc_id,
        source_path=f"fixtures/synthetic/{doc_id}.xlsx",
        title="物品位置表",
        file_kind="xlsx",
        version_id=f"{doc_id}-v1",
        version_label=label,
        sha256=hashlib.sha256(doc_id.encode("utf-8")).hexdigest(),
        business_date=None,
    )


def _row(doc, ordinal, location, start, end):
    fields = {"标识": "P01", "门店": "城东店", "物品": "宣传海报", "位置": location, "生效日期": start}
    fields["失效日期"] = end if end is not None else "未声明"
    return AtomicUnit(
        unit_id=f"{doc.doc_id}-row-{ordinal}",
        doc_id=doc.doc_id,
        version_id=doc.version_id,
        kind="table_row",
        ordinal=ordinal,
        unit_key=f"sheet:物品位置:row:{8 + ordinal}",
        text="；".join(f"{name}: {value}" for name, value in fields.items()),
        fields=fields,
        sheet="物品位置",
        locator={"sheet": "物品位置", "row": 8 + ordinal, "header_row": 7},
        row_number=8 + ordinal,
        title=doc.title,
    )


def _snapshot(legacy: LegacyIndex, as_of: str | None) -> dict:
    with legacy.database.session() as session:
        evidence = retrieve(session, INTENT, revision=legacy.revision, limit=20, as_of=as_of)
    return {
        "as_of": as_of,
        "kind": evidence.kind,
        "unit_count": len(evidence.units),
        "total_candidates": evidence.total_candidates,
        "units": [
            {
                "unit_id": str(unit.id),
                "position": unit.fields.get("位置"),
                "effective_from": unit.fields.get("生效日期"),
                "effective_to": unit.fields.get("失效日期"),
            }
            for unit in evidence.units
        ],
    }


def main() -> int:
    _install_guard()
    workdir = Path(tempfile.mkdtemp(prefix="v3fix1-b-"))
    legacy = LegacyIndex(workdir / "legacy.sqlite3")
    try:
        v03, d01, v05 = _doc("V03", "历史V1"), _doc("D01", "当前V2"), _doc("V05", "新版V3")
        legacy.build(
            [
                (v03, [_row(v03, 0, "A区3号货架第二层", "2026-01-05", "2026-04-30")]),
                (d01, [_row(d01, 0, "D区暂存柜", "2026-05-01", "2026-10-31")]),
                (v05, [_row(v05, 0, "E区新柜", "2026-12-01", None)]),
            ]
        )
        observations = [
            _snapshot(legacy, None),  # 过滤前（= 改前行为）
            _snapshot(legacy, "2026-10-15"),  # run 0 业务日：只剩 D01
            _snapshot(legacy, "2026-04-30"),  # 闭区间右端点：V03 仍有效
            _snapshot(legacy, "2026-12-15"),  # 末端版本：失效日期“未声明”不误杀
        ]
    finally:
        legacy.close()

    before, after = observations[0], observations[1]
    surviving = [unit["unit_id"] for unit in after["units"]]
    print(
        json.dumps(
            {
                "intent": {
                    "mode": INTENT.mode,
                    "entity_filters": dict(INTENT.entity_filters),
                    "requested_fields": list(INTENT.requested_fields),
                },
                "observations": observations,
                "comparison": {
                    "before": {"kind": before["kind"], "unit_count": before["unit_count"]},
                    "after_run0": {"kind": after["kind"], "unit_count": after["unit_count"]},
                    "order_preserved": surviving
                    == [unit["unit_id"] for unit in before["units"] if unit["unit_id"] in set(surviving)],
                    "single_current_version_not_killed": after["unit_count"] == 1
                    and after["units"][0]["position"] == "D区暂存柜",
                },
                "outbound_attempts": OUTBOUND,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

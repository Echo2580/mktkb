"""独立验收 B：legacy 证据面按业务日过滤（自建四版本 + 端点/未声明/不误杀/顺序）。

零真实调用：临时 SQLite、真实 SourceUnit/检索索引；socket 出站全部拦截并计数。
不读取真实 H2 题面/答案；全部为合成记录。
"""
from __future__ import annotations

import hashlib
import json
import socket
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

REPO = Path(__file__).resolve().parents[7]
sys.path.insert(0, str(REPO / "backend" / "src"))
OUT = Path(__file__).resolve().parent / "B-business-date-filter.json"
OUTBOUND: list[str] = []


def _guard() -> None:
    def deny(*args: Any, **kwargs: Any) -> Any:
        OUTBOUND.append(f"connect:{args!r}")
        raise OSError("netguard: outbound blocked")

    socket.socket.connect = deny  # type: ignore[assignment]
    socket.socket.connect_ex = deny  # type: ignore[assignment]
    socket.create_connection = deny  # type: ignore[assignment]
    socket.getaddrinfo = deny  # type: ignore[assignment]


from mktkb.conversations import service as conv_service  # noqa: E402
from mktkb.rag import AtomicUnit, DocumentSpec  # noqa: E402
from mktkb.rag.legacy import LegacyIndex  # noqa: E402
from mktkb.retrieval.service import _as_of_bound, _drop_out_of_window, retrieve  # noqa: E402
from mktkb.retrieval.types import QueryIntent, QueryRejected  # noqa: E402

INTENT = QueryIntent(
    mode="record",
    entity_filters={"store": "城东店", "item": "宣传海报"},
    requested_fields=("位置",),
)
SINGLE_INTENT = QueryIntent(
    mode="record",
    entity_filters={"store": "城西店", "item": "易拉宝"},
    requested_fields=("位置",),
)
UNDECLARED_START_INTENT = QueryIntent(
    mode="record",
    entity_filters={"store": "城北店", "item": "展架"},
    requested_fields=("位置",),
)


def _doc(doc_id: str, label: str) -> DocumentSpec:
    return DocumentSpec(
        doc_id=doc_id,
        logical_id=doc_id,
        source_path=f"fixtures/synthetic/{doc_id}.xlsx",
        title="物品位置表",
        file_kind="xlsx",
        version_id=f"{doc_id}-v1",
        version_label=label,
        sha256=hashlib.sha256(doc_id.encode()).hexdigest(),
        business_date=None,
    )


def _row(
    doc: DocumentSpec,
    *,
    identifier: str,
    store: str,
    item: str,
    location: str,
    effective_from: str | None,
    effective_to: str | None,
    ordinal: int = 0,
) -> AtomicUnit:
    fields = {
        "标识": identifier,
        "门店": store,
        "物品": item,
        "位置": location,
        "生效日期": effective_from if effective_from is not None else "未声明",
        "失效日期": effective_to if effective_to is not None else "未声明",
    }
    return AtomicUnit(
        unit_id=f"{doc.doc_id}-row-{ordinal}",
        doc_id=doc.doc_id,
        version_id=doc.version_id,
        kind="table_row",
        ordinal=ordinal,
        unit_key=f"sheet:物品位置:row:{8 + ordinal}",
        text="；".join(f"{k}: {v}" for k, v in fields.items()),
        fields=fields,
        sheet="物品位置",
        locator={"sheet": "物品位置", "row": 8 + ordinal, "header_row": 7},
        row_number=8 + ordinal,
        title=doc.title,
    )


def _retrieve(legacy: LegacyIndex, intent: QueryIntent, *, as_of: str | None):
    with legacy.database.session() as session:
        return retrieve(session, intent, revision=legacy.revision, limit=20, as_of=as_of)


def _snapshot(evidence) -> dict[str, Any]:
    return {
        "kind": evidence.kind,
        "units": len(evidence.units),
        "total": evidence.total_candidates,
        "truncated": bool(evidence.truncated),
        "ids": [str(unit.id) for unit in evidence.units],
        "locations": [str(unit.fields.get("位置")) for unit in evidence.units],
        "windows": [
            [str(unit.fields.get("生效日期")), str(unit.fields.get("失效日期"))]
            for unit in evidence.units
        ],
    }


def main() -> int:
    _guard()
    tmp = Path(tempfile.mkdtemp(prefix="v3-fix1-B-"))
    legacy = LegacyIndex(tmp / "legacy-b.sqlite3")
    v1 = _doc("X01", "旧版1")
    v2 = _doc("X02", "旧版2")
    v3 = _doc("X03", "现行")
    v4 = _doc("X04", "未来")
    s1 = _doc("S01", "单现行")
    u1 = _doc("U01", "缺生效")
    legacy.build(
        [
            (v1, [_row(v1, identifier="P02", store="城东店", item="宣传海报",
                       location="旧A架", effective_from="2025-11-01", effective_to="2026-02-28")]),
            (v2, [_row(v2, identifier="P02", store="城东店", item="宣传海报",
                       location="旧B架", effective_from="2026-03-01", effective_to="2026-08-31")]),
            (v3, [_row(v3, identifier="P02", store="城东店", item="宣传海报",
                       location="现C柜", effective_from="2026-09-01", effective_to="2026-12-31")]),
            (v4, [_row(v4, identifier="P02", store="城东店", item="宣传海报",
                       location="新D区", effective_from="2027-01-01", effective_to=None)]),
            (s1, [_row(s1, identifier="P03", store="城西店", item="易拉宝",
                       location="西区唯一架", effective_from="2026-01-01", effective_to="2026-12-31")]),
            (u1, [_row(u1, identifier="P04", store="城北店", item="展架",
                       location="北区无起点架", effective_from=None, effective_to="2026-10-31")]),
        ]
    )
    try:
        before = _retrieve(legacy, INTENT, as_of=None)
        after = _retrieve(legacy, INTENT, as_of="2026-10-15")
        single_none = _retrieve(legacy, SINGLE_INTENT, as_of=None)
        single_dated = _retrieve(legacy, SINGLE_INTENT, as_of="2026-10-15")
        undeclared_start = _retrieve(legacy, UNDECLARED_START_INTENT, as_of="2026-10-15")

        # 过滤前可见单元（不经日期过滤）与 _drop_out_of_window 的关系
        with legacy.database.session() as session:
            from mktkb.retrieval.service import _visible_units

            visible = _visible_units(session, set())
            kept = _drop_out_of_window(list(visible), "2026-10-15")
            kept_none = _drop_out_of_window(list(visible), None)

        # 服务入口转发：conversations.service._retrieve(db_factory, ..., as_of=)
        forwarded_none = conv_service._retrieve(legacy.database, INTENT, legacy.revision, as_of=None)
        forwarded_dated = conv_service._retrieve(
            legacy.database, INTENT, legacy.revision, as_of="2026-10-15"
        )

        # 日期取值接线
        fake_qa = SimpleNamespace()
        wire = {
            "qa_none": conv_service._legacy_evidence_as_of(None, SimpleNamespace(as_of="2026-10-15")),
            "plan_none": conv_service._legacy_evidence_as_of(fake_qa, None),
            "as_of_none": conv_service._legacy_evidence_as_of(fake_qa, SimpleNamespace(as_of=None)),
            "as_of_date": conv_service._legacy_evidence_as_of(
                fake_qa, SimpleNamespace(as_of="2026-10-15")
            ),
            "include_future": conv_service._legacy_evidence_as_of(
                fake_qa, SimpleNamespace(as_of="2026-10-15", include_future=True)
            ),
        }

        # 端点与未声明
        endpoints = {
            "2026-02-28_end_of_v1": _snapshot(_retrieve(legacy, INTENT, as_of="2026-02-28")),
            "2026-03-01_start_of_v2": _snapshot(_retrieve(legacy, INTENT, as_of="2026-03-01")),
            "2026-08-31_end_of_v2": _snapshot(_retrieve(legacy, INTENT, as_of="2026-08-31")),
            "2026-09-01_start_of_v3": _snapshot(_retrieve(legacy, INTENT, as_of="2026-09-01")),
            "2026-12-31_end_of_v3": _snapshot(_retrieve(legacy, INTENT, as_of="2026-12-31")),
            "2027-01-01_start_of_v4": _snapshot(_retrieve(legacy, INTENT, as_of="2027-01-01")),
            "2028-01-01_undeclared_end": _snapshot(_retrieve(legacy, INTENT, as_of="2028-01-01")),
            "2026-10-15_inside_v3": _snapshot(_retrieve(legacy, INTENT, as_of="2026-10-15")),
        }

        bad: dict[str, str] = {}
        for value in ("2026/10/15", "2026-02-30", "not-a-date", "2026-1-5"):
            try:
                _as_of_bound(value)
            except QueryRejected:
                bad[value] = "QueryRejected"
            else:
                bad[value] = "ACCEPTED"
        try:
            _as_of_bound(20261015)  # type: ignore[arg-type]
        except QueryRejected:
            bad["int:20261015"] = "QueryRejected"
        else:
            bad["int:20261015"] = "ACCEPTED"

        after_ids = [str(unit.id) for unit in after.units]
        before_ids = [str(unit.id) for unit in before.units]
        checks = {
            "before_conflict_4": before.kind == "conflict" and len(before.units) == 4,
            "after_matches_1": after.kind == "matches" and len(after.units) == 1,
            "after_is_v3": after.units[0].fields["位置"] == "现C柜",
            "subsequence_order": after_ids == [uid for uid in before_ids if uid in set(after_ids)],
            "single_not_killed": single_none.kind == "matches"
            and single_dated.kind == "matches"
            and len(single_dated.units) == 1
            and single_dated.units[0].fields["位置"] == "西区唯一架",
            "single_same_units": [u.id for u in single_none.units] == [u.id for u in single_dated.units],
            "undeclared_start_kept": len(undeclared_start.units) == 1
            and undeclared_start.units[0].fields["位置"] == "北区无起点架",
            "visible_units_unchanged": kept_none == list(visible),
            "drop_is_subset": {u.id for u in kept} <= {u.id for u in visible},
            "service_forward_none": _snapshot(forwarded_none) == _snapshot(before),
            "service_forward_dated": _snapshot(forwarded_dated) == _snapshot(after),
            "wire": wire,
            "invalid_as_of": bad,
        }
        checks["all_invalid_rejected"] = all(v == "QueryRejected" for v in bad.values())
        checks["wire_ok"] = (
            wire["qa_none"] is None
            and wire["plan_none"] is None
            and wire["as_of_none"] is None
            and wire["as_of_date"] == "2026-10-15"
            and wire["include_future"] is None
        )
        # 端点期望
        expected_locations = {
            "2026-02-28_end_of_v1": ["旧A架"],
            "2026-03-01_start_of_v2": ["旧B架"],
            "2026-08-31_end_of_v2": ["旧B架"],
            "2026-09-01_start_of_v3": ["现C柜"],
            "2026-12-31_end_of_v3": ["现C柜"],
            "2027-01-01_start_of_v4": ["新D区"],
            "2028-01-01_undeclared_end": ["新D区"],
            "2026-10-15_inside_v3": ["现C柜"],
        }
        for key, values in expected_locations.items():
            checks[f"endpoint:{key}"] = endpoints[key]["locations"] == values

        # 召回/排序未改动的代码级证据：只列相关函数的行号与 diff 形状
        source = (REPO / "backend/src/mktkb/retrieval/service.py").read_text(encoding="utf-8")
        diff = __import__("subprocess").run(
            ["git", "diff", "-U0", "--", "backend/src/mktkb/retrieval/service.py"],
            cwd=REPO, capture_output=True,
        ).stdout.decode("utf-8", "replace")
        recall_hunks = [line for line in diff.splitlines() if line.startswith("@@")]
        checks["diff_hunks"] = recall_hunks
        checks["drop_call_after_visible"] = source.count("units = _drop_out_of_window(units, as_of)") == 2
        checks["no_changes_to_fts_or_sort"] = not any(
            token in diff for token in ("_fts_unit_ids", "match_expression", "selected_units.sort", "candidates =")
        )

        failures = [name for name, ok in checks.items()
                    if isinstance(ok, bool) and not ok and name not in ("diff_hunks",)]

        payload = {
            "schema_version": "v3-fix1-independent-B/v0.1",
            "before": _snapshot(before),
            "after": _snapshot(after),
            "single_none": _snapshot(single_none),
            "single_dated": _snapshot(single_dated),
            "undeclared_start": _snapshot(undeclared_start),
            "forwarded_none": _snapshot(forwarded_none),
            "forwarded_dated": _snapshot(forwarded_dated),
            "endpoints": endpoints,
            "wire": wire,
            "invalid_as_of": bad,
            "visible_units": len(visible),
            "kept_units": len(kept),
            "checks": checks,
            "failures": failures,
            "outbound_attempts": OUTBOUND,
        }
        OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                       encoding="utf-8")
        print(json.dumps({"failures": failures,
                          "before": payload["before"]["kind"] + "/" + str(payload["before"]["units"]),
                          "after": payload["after"]["kind"] + "/" + str(payload["after"]["units"]),
                          "single": payload["single_dated"]["locations"],
                          "undeclared_start": payload["undeclared_start"]["locations"],
                          "wire": wire, "invalid": bad,
                          "outbound": len(OUTBOUND)}, ensure_ascii=False, indent=1))
    finally:
        legacy.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""LOCAL-R1/S1 隔离 RAG 测试装配：临时 SQLite、确定性替身与记录工厂。"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, Iterable, Mapping

import pytest

from mktkb.rag import AtomicUnit, DocumentSpec, RagConfig, RagIndex


@pytest.fixture
def rag_config(tmp_path: Path) -> RagConfig:
    return RagConfig(
        provider_mode="offline",
        data_dir=tmp_path,
        business_date="2026-10-28",
        chunk_max_chars=420,
        chunk_max_units=3,
        chunk_overlap_units=1,
        top_k=5,
        page_size=10,
        vector_candidate_limit=50,
        rerank_top_n=20,
    )


@pytest.fixture
def rag_index(tmp_path: Path, rag_config: RagConfig):
    index = RagIndex(tmp_path / "rag.sqlite3", config=rag_config)
    try:
        yield index
    finally:
        index.close()


@pytest.fixture
def make_doc():
    def _make(
        *,
        doc_id: str | None = None,
        title: str = "测试资料",
        source_path: str = "corpus/test.xlsx",
        file_kind: str = "xlsx",
        logical_id: str | None = None,
        version_label: str = "当前",
        is_current: bool = True,
        state: str = "active",
        effective_from: str | None = None,
        effective_to: str | None = None,
    ) -> DocumentSpec:
        identifier = doc_id or "D" + uuid.uuid4().hex[:8]
        return DocumentSpec(
            doc_id=identifier,
            logical_id=logical_id or identifier,
            source_path=source_path,
            title=title,
            file_kind=file_kind,
            version_id="V-" + uuid.uuid4().hex,
            version_label=version_label,
            sha256=uuid.uuid4().hex + uuid.uuid4().hex,
            is_current=is_current,
            state=state,
            effective_from=effective_from,
            effective_to=effective_to,
            business_date="2026-10-28",
        )

    return _make


@pytest.fixture
def make_unit():
    def _make(
        doc: DocumentSpec,
        *,
        fields: Mapping[str, Any] | None = None,
        text: str | None = None,
        kind: str = "table_row",
        ordinal: int = 0,
        unit_key: str | None = None,
        sheet: str | None = "物品位置",
        locator: Mapping[str, Any] | None = None,
        row: int | None = None,
    ) -> AtomicUnit:
        values = dict(fields or {})
        from mktkb.rag.chunking import effective_dates

        effective_from, effective_to = effective_dates(values)
        body = text or "；".join(f"{name}: {value}" for name, value in values.items())
        loc = dict(locator or {})
        if row is not None:
            loc.setdefault("sheet", sheet)
            loc.setdefault("row", row)
            loc.setdefault("header_row", 6)
        return AtomicUnit(
            unit_id=f"{doc.doc_id}-{ordinal}-{uuid.uuid4().hex[:6]}",
            doc_id=doc.doc_id,
            version_id=doc.version_id,
            kind=kind,
            ordinal=ordinal,
            unit_key=unit_key or f"sheet:{sheet or '-'}:row:{row if row is not None else ordinal}",
            text=body,
            fields=values,
            sheet=sheet if kind == "table_row" else None,
            locator=loc,
            header_row=loc.get("header_row") if isinstance(loc.get("header_row"), int) else None,
            row_number=loc.get("row") if isinstance(loc.get("row"), int) else None,
            title=doc.title,
            effective_from=effective_from,
            effective_to=effective_to,
        )

    return _make


@pytest.fixture
def add_records(rag_index: RagIndex, make_doc, make_unit):
    def _add(
        rows: Iterable[Mapping[str, Any]],
        *,
        doc: DocumentSpec | None = None,
        text_units: Iterable[Mapping[str, Any]] = (),
        embed: bool = True,
    ) -> DocumentSpec:
        record_doc = doc or make_doc()
        units: list[AtomicUnit] = []
        for ordinal, fields in enumerate(rows):
            units.append(
                make_unit(
                    record_doc,
                    fields=fields,
                    ordinal=ordinal,
                    sheet="物品位置",
                    row=7 + ordinal,
                )
            )
        for offset, item in enumerate(text_units):
            units.append(
                make_unit(
                    record_doc,
                    fields=dict(item.get("fields") or {}),
                    text=str(item.get("text") or ""),
                    kind=str(item.get("kind") or "paragraph"),
                    ordinal=len(units) + offset,
                    unit_key=f"paragraph:{offset + 1}",
                    sheet=None,
                    locator=dict(item.get("locator") or {"paragraph": offset + 1}),
                )
            )
        rag_index.add_document(record_doc, units, embed=embed)
        return record_doc

    return _add

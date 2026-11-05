"""T004a 评测数据集测试装配：离线索引与夹具。

约束：
- 只用离线确定性 provider（``provider_mode="offline"``），0 次真实 embedding / rerank /
  模型 / OCR 调用；不进 ``var/``，不读 ``.env``；
- B0 只解析 D01–D06（xlsx/docx/文本 PDF）；D07–D08 扫描 PDF 与 D09–D10 图片属 OCR 题，
  **不解析**，索引里根本没有 D07–D10，OCR 题在 ``resolve_gold`` 里显式 skipped；
- badcase 只解析 E03 / E11 / P03 / W01 四份被引用的资料（§7「只解析必要文件」）；
- 索引为 session 级，SQLite 落在 pytest 的 ``--basetemp`` 下。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from mktkb.ingestion.parsers import ParseServices, parse_document
from mktkb.rag import DocumentSpec, RagConfig, RagIndex, adapt_parsed_unit

ROOT = Path(__file__).resolve().parents[3]
ACCEPTANCE = ROOT / "fixtures" / "acceptance"
EVAL_DIR = ROOT / "fixtures" / "evaluation"
CORPUS = ROOT / "corpus" / "enterprise-20261101"
BADCASE_CODES = ("E03", "E11", "P03", "W01")
# 非 OCR 的 B0 资料：D07/D08 是扫描 PDF、D09/D10 是图片，解析它们必然触发 OCR 路径。
B0_NON_OCR_KINDS = {"xlsx", "docx", "pdf-text"}


def offline_config(data_dir: Path) -> RagConfig:
    return RagConfig(
        provider_mode="offline",
        data_dir=Path(data_dir),
        business_date="2026-10-28",
        chunk_max_chars=420,
        chunk_max_units=3,
        chunk_overlap_units=1,
        top_k=5,
        page_size=10,
        vector_candidate_limit=50,
        rerank_top_n=20,
    )


def _title(item: dict) -> str:
    stem = Path(str(item["path"])).stem
    return stem.split("_", 1)[1] if "_" in stem else stem


def build_b0_index(db_path: Path) -> RagIndex:
    """D01–D06 离线索引：doc_id 用 B0 资料编码，供 ``doc_code`` 直接解析。"""
    manifest = json.loads((ACCEPTANCE / "manifest.json").read_text(encoding="utf-8"))
    index = RagIndex(db_path, config=offline_config(db_path.parent))
    for item in manifest["normal_files"]:
        if str(item.get("kind")) not in B0_NON_OCR_KINDS:
            continue
        path = ACCEPTANCE / str(item["path"])
        kind = path.suffix.lower().lstrip(".")
        parsed = list(parse_document(path, kind, ParseServices()))
        spec = DocumentSpec(
            doc_id=str(item["id"]),
            logical_id=str(item["id"]),
            source_path=str(item["path"]),
            title=_title(item),
            file_kind=kind,
            version_id=f"{item['id']}-v1",
            version_label="当前",
            sha256=str(item["sha256"]),
            business_date="2026-10-28",
        )
        units = [
            adapt_parsed_unit(unit, doc=spec, unit_id=f"{item['id']}-{ordinal}", ordinal=ordinal)
            for ordinal, unit in enumerate(parsed)
        ]
        result = index.add_document(spec, units, embed=True)
        assert not result.get("embedding_error"), result
    return index


def build_badcase_index(db_path: Path) -> RagIndex:
    """E03/E11/P03/W01 离线索引：复用 ``tools/rag_experiment.py`` 的语料装配。"""
    tools_dir = str(ROOT / "tools")
    if tools_dir not in sys.path:
        sys.path.insert(0, tools_dir)
    from rag_experiment import build_new_index, load_corpus  # 既有 helper，不复制解析逻辑

    documents, skipped = load_corpus(CORPUS, only_codes=set(BADCASE_CODES))
    parsed_codes = {spec.doc_id for spec, _ in documents}
    assert parsed_codes == set(BADCASE_CODES), f"必要资料解析缺失: {sorted(set(BADCASE_CODES) - parsed_codes)} / {skipped}"
    index, stats = build_new_index(documents, db_path=db_path, config=offline_config(db_path.parent))
    assert stats["documents"] == len(BADCASE_CODES)
    return index


@pytest.fixture(scope="session")
def b0_index(tmp_path_factory) -> RagIndex:
    index = build_b0_index(tmp_path_factory.mktemp("eval-b0") / "rag.sqlite3")
    try:
        yield index
    finally:
        index.close()


@pytest.fixture(scope="session")
def badcase_index(tmp_path_factory) -> RagIndex:
    index = build_badcase_index(tmp_path_factory.mktemp("eval-badcase") / "rag.sqlite3")
    try:
        yield index
    finally:
        index.close()


@pytest.fixture(scope="session")
def b0_cases():
    from mktkb.evaluation.dataset import load_cases

    return load_cases(EVAL_DIR / "b0.jsonl")


@pytest.fixture(scope="session")
def badcase_cases():
    from mktkb.evaluation.dataset import load_cases

    return load_cases(EVAL_DIR / "badcase.jsonl")


@pytest.fixture
def split_chunk_index(tmp_path: Path) -> RagIndex:
    """同一个 unit 被拆成多个 chunk：gold 解析仍只返回 1 个 unit（unit 级去重）。"""
    from mktkb.rag import AtomicUnit

    index = RagIndex(tmp_path / "split.sqlite3", config=offline_config(tmp_path))
    spec = DocumentSpec(
        doc_id="D90",
        logical_id="D90",
        source_path="normal/D90_长记录.xlsx",
        title="长记录",
        file_kind="xlsx",
        version_id="D90-v1",
        version_label="当前",
        sha256="0" * 64,
        business_date="2026-10-28",
    )
    fields = {"标识": "L01", "门店": "测试店", "物品": "长物料", "位置": "A区1号货架"}
    fields.update({f"说明{i:02d}": "这是一段用于触发记录块拆分的较长说明文本" * 3 for i in range(20)})
    unit = AtomicUnit(
        unit_id="D90-long",
        doc_id="D90",
        version_id="D90-v1",
        kind="table_row",
        ordinal=0,
        unit_key="sheet:物品位置:row:8",
        text="；".join(f"{name}: {value}" for name, value in fields.items()),
        fields=fields,
        sheet="物品位置",
        locator={"sheet": "物品位置", "row": 8, "header_row": 7},
        header_row=7,
        row_number=8,
        title="长记录",
    )
    result = index.add_document(spec, [unit], embed=True)
    assert not result.get("embedding_error"), result
    try:
        yield index
    finally:
        index.close()


@pytest.fixture
def duplicate_key_index(tmp_path: Path) -> RagIndex:
    """同一文档下两个 unit 共用 ``unit_key``：身份型引用必须 fail closed。

    ``rag_units`` 的约束是 ``(version_id, unit_key)`` 唯一；这里用同 doc_id、不同 version_id
    的遗留 unit 行模拟“同一文档里同名 unit_key”，不需要绕过任何数据库约束。
    """
    from mktkb.rag import AtomicUnit
    from mktkb.rag.models import RagUnit

    index = RagIndex(tmp_path / "dup.sqlite3", config=offline_config(tmp_path))
    spec = DocumentSpec(
        doc_id="D01",
        logical_id="D01",
        source_path="normal/D01_物品位置表.xlsx",
        title="物品位置表",
        file_kind="xlsx",
        version_id="D01-v1",
        version_label="当前",
        sha256="0" * 64,
        business_date="2026-10-28",
    )
    units = [
        AtomicUnit(
            unit_id="D01-dup-current",
            doc_id="D01",
            version_id="D01-v1",
            kind="table_row",
            ordinal=0,
            unit_key="sheet:物品位置:row:8",
            text="标识: P01",
            fields={"标识": "P01"},
            sheet="物品位置",
            locator={"sheet": "物品位置", "row": 8, "header_row": 7},
            header_row=7,
            row_number=8,
            title="物品位置表",
        )
    ]
    result = index.add_document(spec, units, embed=True)
    assert not result.get("embedding_error"), result
    with index.session() as session:
        session.add(
            RagUnit(
                unit_id="D01-dup-legacy",
                doc_id="D01",
                version_id="D01-v0",
                kind="table_row",
                ordinal=1,
                unit_key="sheet:物品位置:row:8",
                text="标识: P01（遗留行）",
                fields={"标识": "P01"},
                sheet="物品位置",
                locator={"sheet": "物品位置", "row": 8, "header_row": 7},
                header_row=7,
                row_number=8,
                title="物品位置表",
            )
        )
        session.commit()
    try:
        yield index
    finally:
        index.close()


# --------------------------------------------------------------------------- #
# T008b：七条验收复用可观测性装配（只追加，不复制一套 app）
# --------------------------------------------------------------------------- #
# ``trace_chat_app`` 需要 ``trace_settings`` / ``trace_db_path``；三者都定义在
# ``backend/tests/observability/conftest.py``。pytest 的 fixture 可见性按目录分段，
# 这里**原样重新注册**那三个 fixture（同一函数对象，不是复制装配），让 evaluation
# 目录的验收测试可以复用既有 trace 应用；本文件此前的 fixture 与断言完全不变。
from observability.conftest import (  # noqa: E402,F401  pylint: disable=wrong-import-position
    trace_chat_app,
    trace_db_path,
    trace_settings,
)

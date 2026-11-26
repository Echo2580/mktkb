"""形状标定探针：只打印整数 / 角色码 / 布尔，绝不打印任何中文值或题面。

目的：确认真实 SAFE 指纹（``answer_text_chars`` / ``line_count`` / ``date_token_count``
/ ``digit_token_count`` / ``unit_token_count`` / ``facts`` / ``fact_value_chars``）
在渲染层分别对应什么量，从而判断 ``fact_value_chars`` 是否等于“被渲染的值长度”。

去身份化合成件：假门店、假物品、假日期；长值列用固定长度 ASCII 占位，不含任何业务值。
"""

from __future__ import annotations

import hashlib
import re
import sys
import tempfile
from pathlib import Path


def _repo_root(start: Path) -> Path:
    for candidate in [start, *start.parents]:
        if (candidate / "backend" / "src" / "mktkb").is_dir():
            return candidate
    raise RuntimeError("repo_root_not_found")


ROOT = _repo_root(Path(__file__).resolve())
sys.path.insert(0, str(ROOT / "backend" / "src"))

from mktkb.rag import AtomicUnit, DocumentSpec, RagConfig, RagIndex  # noqa: E402
from mktkb.rag.query import build_lexicon, parse_query  # noqa: E402

_DATE_RE = re.compile(r"20\d{2}\s*[-年/]\s*\d{1,2}\s*[-月/]\s*\d{1,2}")
_DIGIT_RE = re.compile(r"\d")
_UNIT_TOKENS = ("条", "元", "个", "张", "块", "瓶", "箱", "面")

# 去身份化：假门店 / 假物品 / 假日期 / 固定长度 ASCII 长值。
FAKE_LONG = "Z" * 47
FAKE_ROW = {
    "标识": "L-0001",
    "门店": "甲店",
    "物品": "立牌",
    "生效日期": "2026-01-05",
    "失效日期": "2026-09-30",
    "位置": FAKE_LONG,
}

QUESTIONS = {
    "location_only": "列出甲店立牌的位置",
    "effective_to_only": "列出甲店立牌的失效日期",
    "both_ends": "列出甲店立牌的生效日期和失效日期",
    "location_and_effective_to": "列出甲店立牌的位置和失效日期",
}


def _doc() -> DocumentSpec:
    return DocumentSpec(
        doc_id="D-shape",
        logical_id="D-shape",
        source_path="corpus/D-shape.xlsx",
        title="合成台账",
        file_kind="xlsx",
        version_id="V-shape",
        version_label="当前",
        sha256=hashlib.sha256(b"D-shape").hexdigest(),
        is_current=True,
        state="active",
        business_date="2026-10-28",
    )


def _add(index: RagIndex) -> None:
    doc = _doc()
    unit = AtomicUnit(
        unit_id="D-shape-row7",
        doc_id=doc.doc_id,
        version_id=doc.version_id,
        kind="table_row",
        ordinal=0,
        unit_key="sheet:合成表:row:7",
        text="；".join(f"{k}: {v}" for k, v in FAKE_ROW.items()),
        fields=dict(FAKE_ROW),
        sheet="合成表",
        locator={"sheet": "合成表", "row": 7, "header_row": 0},
        header_row=0,
        row_number=7,
        title=doc.title,
    )
    index.add_document(doc, [unit], embed=False)


def _fingerprint(answer) -> dict:
    text = answer.text
    return {
        "kind": str(answer.kind),
        "fact_count": len(answer.facts),
        "fact_value_chars": sum(len(f.value) for f in answer.facts),
        "fact_roles": sorted({f.field_role for f in answer.facts}),
        "text_chars": len(text),
        "line_count": len(text.splitlines()),
        "date_token_count": len(_DATE_RE.findall(text)),
        "digit_token_count": len(_DIGIT_RE.findall(text)),
        "unit_token_count": sum(text.count(tok) for tok in _UNIT_TOKENS),
        "long_value_rendered": FAKE_LONG in text,
    }


def main() -> None:
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        config = RagConfig(
            provider_mode="offline",
            data_dir=tmp,
            business_date="2026-10-28",
            chunk_max_chars=420,
            chunk_max_units=3,
            chunk_overlap_units=1,
            top_k=5,
            page_size=10,
            vector_candidate_limit=50,
            rerank_top_n=20,
        )
        index = RagIndex(tmp / "shape.sqlite3", config=config)
        try:
            _add(index)
            lexicon = build_lexicon(index.lexicon_data())
            for key, question in QUESTIONS.items():
                plan = parse_query(
                    question,
                    previous=None,
                    lexicon=lexicon,
                    business_date="2026-10-28",
                    page_size=10,
                )
                answer = index.ask(question, user_id="u", conversation_id=f"shape-{key}")
                roles = tuple(getattr(plan, "field_roles", ()) or ()) or (
                    (plan.field_role,) if plan.field_role else ()
                )
                row = {"probe": key, "plan_roles": list(roles)}
                row.update(_fingerprint(answer))
                print(row)
        finally:
            index.close()


if __name__ == "__main__":
    main()

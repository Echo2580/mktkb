"""调试：离线 e2e 的追问“那这个组合价什么时候失效？”在改动后变成 no_answer 的原因。"""

from __future__ import annotations

import hashlib
import pathlib
import sys
import tempfile

ROOT = next(
    parent for parent in pathlib.Path(__file__).resolve().parents if (parent / "corpus").is_dir()
)
sys.path.insert(0, str(ROOT / "backend" / "src"))

from mktkb.ingestion.parsers import ParseServices, parse_document  # noqa: E402
from mktkb.rag import DocumentSpec, RagConfig, RagIndex, adapt_parsed_unit  # noqa: E402
from mktkb.rag.query import build_lexicon, parse_query  # noqa: E402

CORPUS = ROOT / "corpus" / "enterprise-20261101"


def _add(index, code, rel, kind, title):
    path = CORPUS / rel
    doc = DocumentSpec(
        doc_id=code, logical_id=code, source_path=rel, title=title, file_kind=kind,
        version_id=f"{code}-v1", version_label="当前",
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(), business_date="2026-10-28",
    )
    units = [adapt_parsed_unit(u, doc=doc, unit_id=f"{code}-{i}", ordinal=i)
             for i, u in enumerate(parse_document(path, kind, ParseServices()))]
    index.add_document(doc, units)


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        tmp = pathlib.Path(tmp)
        index = RagIndex(tmp / "e.sqlite3",
                         config=RagConfig(data_dir=tmp, business_date="2026-10-28",
                                          page_size=10, top_k=5))
        try:
            _add(index, "E11", "excel/E11_终端物料位置表_当前V2.xlsx", "xlsx", "终端物料位置表")
            _add(index, "E03", "excel/E03_2026年Q4渠道价目表.xlsx", "xlsx", "2026年Q4渠道价目表")
            first = index.ask("启沣乌龙茶（900ml PET）在NKA卖场的组合价是多少？",
                              user_id="u", conversation_id="c3")
            print("first", first.kind, [(f.field_role, f.value) for f in first.facts])
            state = __import__("mktkb.rag.types", fromlist=["QueryState"]).QueryState.from_dict(first.state)
            lex = build_lexicon(index.lexicon_data())
            q = "那这个组合价什么时候失效？"
            plan = parse_query(q, previous=state, lexicon=lex, business_date="2026-10-28",
                               page_size=10)
            print("plan.field_role=", plan.field_role, "field_roles=", plan.field_roles,
                  "enumerate=", plan.enumerate, "filters=", dict(plan.filters), "reason=", plan.reason)
            follow = index.ask(q, user_id="u", conversation_id="c3")
            print("follow", follow.kind, follow.reason, [(f.field_role, f.value) for f in follow.facts])
            print("text=", follow.text)
        finally:
            index.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

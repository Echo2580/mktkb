"""R2-202C 回滚重建脚本（只读+临时副本；不改工作树）。

用途：R2-202C 的 3 个源文件在会话开始前**已有 R0/R1 未提交改动**，`git diff` 的 hunk
粒度把本批与其他批的改动并在一起，无法直接用 `git apply -R` 精确回滚本批。本脚本按
"本批的每一次编辑"逐条反向替换，重建出"仅缺本批改动"的三个文件副本，再用
`git diff --no-index` 产出只含本批 hunk 的补丁（`R2-202C-MINE-rollback.patch.txt`）。
该补丁可 `git apply -R` 精确回滚本批，且不动其他批的成果。

用法（仓库根）：
    .venv\\Scripts\\python.exe -X utf8 docs/reports/OBS-EVAL/P2/H2V3/\
        r2-repair-external-20261117/evidence/05-fix/R2-202C-rollback-reconstruct.py
    git apply --check -R <生成的补丁>     # 预检（不落地）
    git apply -R <生成的补丁>             # 真正回滚本批
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[8]
FILES = {
    "retrieval": "backend/src/mktkb/rag/retrieval.py",
    "answer": "backend/src/mktkb/rag/answer.py",
    "facts": "backend/src/mktkb/rag/facts.py",
}

# --------------------------------------------------------------------------- #
# 本批每一次编辑的 (新文本, 旧文本) 对照；旧文本 = 会话开始前的样子
# --------------------------------------------------------------------------- #

RETRIEVAL_OLD_EXACT = '''def _exact_recall(session: Session, index: Any, plan: QueryPlan, diagnostics: dict[str, Any]) -> list[IndexedChunk]:
    if plan.mode != "record":
        return []
    chunks = _load(session, _base_stmt(session, plan, require_record=True))
    chunks = [chunk for chunk in chunks if _has_role(chunk, plan.field_role)]
    # 多字段/多实体时保留全部精确命中；不在召回阶段截断。
    diagnostics["exact_candidates"] = len(chunks)
    return chunks'''


def revert_retrieval(text: str) -> str:
    text = text.replace("import math\nimport time\nfrom dataclasses import replace\n", "import math\nimport time\n")
    start = text.index("#: 只登记在店家信息行上的字段角色")
    end = text.index("def _effective_hints(")
    return text[:start] + RETRIEVAL_OLD_EXACT + "\n\n\n" + text[end:]


def revert_answer(text: str) -> str:
    # A1：本批新增的 4 个读者 helper（_store_join/_store_join_ids/_store_join_value/_record_marker）
    start = text.index("def _store_join(result: RetrievalResult) -> dict[str, Any]:")
    end = text.index("def _answer_record(")
    text = text[:start] + text[end:]
    # A2：答案侧单角色裁剪恢复原样
    text = text.replace(
        """    exact = [
        chunk
        for chunk in result.exact
        if not plan.field_role
        or chunk.role_values.get(plan.field_role)
        or chunk.chunk_id in _store_join_ids(result)
    ]""",
        """    exact = [
        chunk
        for chunk in result.exact
        if not plan.field_role or chunk.role_values.get(plan.field_role)
    ]""",
    )
    # A3：枚举渲染恢复原样（无联结标记、无记录指纹）
    text = text.replace(
        """    # R2-202C：本轮的店家行来自「物品行 + 同门店」显式联结。物品行标签形如
    # “青禾店的折叠桌”天然含店名，与店家行标签“青禾店”会互污；因此联结轮次按
    # **记录身份**逐行渲染（每行只含一条记录的事实，归属由记录指纹决定，不放宽任何检查）。
    joined = bool(_store_join_ids(result))
""",
        "",
    )
    text = text.replace('        marker = _record_marker(chunk) if joined else ""\n', "")
    text = text.replace(
        'f"- {_entity_label(chunk)}：{_format_value(chunk, role, value)}（来源：{chunk.title}）{marker}"',
        'f"- {_entity_label(chunk)}：{_format_value(chunk, role, value)}（来源：{chunk.title}）"',
    )
    text = text.replace(
        'f"- {_entity_label(chunk)}：{\'、\'.join(parts)}（来源：{chunk.title}）{marker}"',
        'f"- {_entity_label(chunk)}：{\'、\'.join(parts)}（来源：{chunk.title}）"',
    )
    text = text.replace(
        """            FactValidator(
                index,
                plan,
                build_lexicon(index.lexicon_data()),
                joined_store=_store_join_value(result),
            ).validate_record_text(""",
        """            FactValidator(index, plan, build_lexicon(index.lexicon_data())).validate_record_text(""",
    )
    return text


def revert_facts(text: str) -> str:
    start = text.index("    def __init__(\n        self,\n        index: Any,\n        plan: QueryPlan,\n        lexicon: Lexicon,\n        *,\n        joined_store: str | None = None,")
    end = text.index("    def validate_fact(")
    text = text[:start] + """    def __init__(self, index: Any, plan: QueryPlan, lexicon: Lexicon) -> None:
        self.index = index
        self.plan = plan
        self.lexicon = lexicon

""" + text[end:]
    return text.replace(
        """            if key in _ENTITY_ROLES and chunk.filters_norm.get(key) != normalize(value):
                if self._joined_store_row(chunk):
                    # 联结店家行只承载店家级字段，天然没有 `item` 等物品条件；放行条件是
                    # “该行门店值 == 物品行门店值”（见 `_joined_store_row`），不是“忽略过滤”。
                    continue
                raise CrossEntity("事实来源不满足问题实体条件")""",
        """            if key in _ENTITY_ROLES and chunk.filters_norm.get(key) != normalize(value):
                raise CrossEntity("事实来源不满足问题实体条件")""",
    )


REVERTERS = {"retrieval": revert_retrieval, "answer": revert_answer, "facts": revert_facts}


def main() -> None:
    out_dir = Path(__file__).resolve().parent
    patch = out_dir / "R2-202C-MINE-rollback.patch.txt"
    chunks: list[str] = []
    # 临时镜像放在仓库内（相对路径短、可被 `git diff --no-index` 正确标注 a/ b/），用完即删。
    mirror_root = ROOT / ".r2-202c-rollback-tmp"
    mirror_root.mkdir(exist_ok=True)
    try:
        for key, rel in FILES.items():
            current = (ROOT / rel).read_text(encoding="utf-8")
            rebuilt = REVERTERS[key](current)
            assert rebuilt != current, f"{rel}: 反向替换没有生效"
            mirror = mirror_root / f"{key}.py"
            mirror.write_text(rebuilt, encoding="utf-8")
            diff = subprocess.run(
                ["git", "diff", "--no-index", "--", mirror.relative_to(ROOT).as_posix(), rel],
                cwd=ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
            ).stdout
            diff = diff.replace(
                f"a/{mirror.relative_to(ROOT).as_posix()}", f"a/{rel}"
            ).replace(f"b/{mirror.relative_to(ROOT).as_posix()}", f"b/{rel}")
            chunks.append(diff)
    finally:
        for leftover in mirror_root.glob("*.py"):
            leftover.unlink()
        mirror_root.rmdir()
    patch.write_text("".join(chunks), encoding="utf-8")
    print(f"wrote {patch} ({patch.stat().st_size} bytes)")


if __name__ == "__main__":
    main()

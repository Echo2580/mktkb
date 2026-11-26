"""重建 R1 之前的两个文件并生成只含本轮改动的 unified diff（自证无其它改动）。

做法：按“行号块”精确删除本轮 R1 追加的内容（保留原文件 CRLF），重建出的文件哈希必须
等于改动前实测哈希：
- backend/src/mktkb/rag/query.py            f73fc7353501e09e65a474fc2599fa4235e1db5d72fc4ea802e0e881f680c372
- backend/tests/observability/test_paths_e2e.py
                                            d357fdc392e95cfb32f112f2ee28c1d76c14338028fe019ed2b029af37770384

输出：evidence/fix-r1.diff（含两个 tracked 文件的 diff 与新增测试文件的 /dev/null diff；
diff 内部统一用 LF 展示）。
"""
from __future__ import annotations

import difflib
import hashlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[6]
OUT = HERE / "fix-r1.diff"

QUERY = REPO / "backend" / "src" / "mktkb" / "rag" / "query.py"
PATHS = REPO / "backend" / "tests" / "observability" / "test_paths_e2e.py"
NEW_TEST = REPO / "backend" / "tests" / "rag" / "test_v3_fix1r1_anaphora_multi_target.py"

EXPECT_QUERY = "f73fc7353501e09e65a474fc2599fa4235e1db5d72fc4ea802e0e881f680c372"
EXPECT_PATHS = "d357fdc392e95cfb32f112f2ee28c1d76c14338028fe019ed2b029af37770384"


def read_preserve(path: Path) -> str:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return handle.read()


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def drop_lines(text: str, ranges: list[tuple[int, int]]) -> str:
    """按 1-based 闭区间删除行；区间须互不重叠。"""
    lines = text.splitlines(keepends=True)
    drop = set()
    for start, end in ranges:
        drop.update(range(start - 1, end))
    return "".join(line for index, line in enumerate(lines) if index not in drop)


def main() -> int:
    current_query = read_preserve(QUERY)
    newline = "\r\n" if "\r\n" in current_query else "\n"
    pre_query = drop_lines(
        current_query,
        [
            (90, 110),     # 量化指代常量块
            (409, 439),    # _bare_quantified_anaphora 函数与后随空行
            (1152, 1153),  # 指代残词剥离
            (1813, 1846),  # MULTIPLE_ENTITIES 澄清分支与后随空行
        ],
    )
    pre_query = pre_query.replace(
        f"    quantified_anaphora = _bare_quantified_anaphora(question, lexicon){newline}"
        f"    anaphora = quantified_anaphora or any(word in question for word in ANAPHORA_WORDS){newline}",
        f"    anaphora = any(word in question for word in ANAPHORA_WORDS){newline}",
        1,
    )
    if sha(pre_query) != EXPECT_QUERY:
        raise SystemExit(f"query.py 重建哈希不符：{sha(pre_query)}")

    current_paths = read_preserve(PATHS)
    pre_paths = drop_lines(
        current_paths,
        [
            (55, 56),    # PURE_ANAPHORA_QUESTION 常量
            (390, 407),  # 纯指代 e2e 测试与后随空行
        ],
    )
    if sha(pre_paths) != EXPECT_PATHS:
        raise SystemExit(f"test_paths_e2e.py 重建哈希不符：{sha(pre_paths)}")

    def lf(text: str) -> list[str]:
        return text.replace("\r\n", "\n").splitlines(keepends=True)

    diffs: list[str] = []
    for rel, old, new in [
        ("backend/src/mktkb/rag/query.py", pre_query, current_query),
        ("backend/tests/observability/test_paths_e2e.py", pre_paths, current_paths),
    ]:
        diffs.append(
            "".join(
                difflib.unified_diff(
                    lf(old),
                    lf(new),
                    fromfile=f"a/{rel}",
                    tofile=f"b/{rel}",
                    n=4,
                )
            )
        )
    diffs.append(
        "".join(
            difflib.unified_diff(
                [],
                lf(read_preserve(NEW_TEST)),
                fromfile="/dev/null",
                tofile="b/backend/tests/rag/test_v3_fix1r1_anaphora_multi_target.py",
                n=4,
            )
        )
    )
    OUT.write_text(
        "# v3-fix-1/R1 修复 diff（仅本轮改动；上面两个 tracked 文件由哈希自证重建）\n"
        + "".join(diffs),
        encoding="utf-8",
    )
    print(f"ok pre_query={sha(pre_query)} pre_paths={sha(pre_paths)} out={OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

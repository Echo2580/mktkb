"""独立验收：核对 fix-r1.diff 与工作树改后文件一致，并用反向应用重建改前文件哈希。

做法（不依赖开发脚本、不改工作树）：
1. 读取 `evidence/fix-r1.diff`，去掉首行说明，按标准 unified diff 解析；
2. 以**当前工作树文件**为目标，反向应用本轮 diff → 得到改前（fix-1/A 后、R1 前）内容；
   哈希必须等于上一轮独立验收快照记录的 fix-1 终态哈希；
3. 再以重建出的改前内容为目标，正向应用同一 diff → 必须逐字节回到当前文件；
4. 统计 diff 中被删除的行：本轮只允许 1 行（`anaphora = ...` 被扩成两行），
   不得出现任何 fix-1/A 既有块的删除（即不得回退既有未提交改动）。

只读工作树，只写本目录 JSON。
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[6]
DIFF = REPO / "docs/reports/OBS-EVAL/P2/H2V3/fix-1r1/evidence/fix-r1.diff"
OUT = HERE / "diff-verify.json"

CURRENT = {
    "backend/src/mktkb/rag/query.py": "82776def986afa6defd37d75f6596a51dc1402fcdbe4725c7aa7d7d1ecc27fef",
    "backend/tests/observability/test_paths_e2e.py": "c0ff388ff1f59b0c6d5a3662b47d2e0131d434ff1c89effa622b1039b8ed7874",
}
PRE_R1 = {
    "backend/src/mktkb/rag/query.py": "f73fc7353501e09e65a474fc2599fa4235e1db5d72fc4ea802e0e881f680c372",
    "backend/tests/observability/test_paths_e2e.py": "d357fdc392e95cfb32f112f2ee28c1d76c14338028fe019ed2b029af37770384",
}
NEW_TEST = "backend/tests/rag/test_v3_fix1r1_anaphora_multi_target.py"
# 上一轮独立验收（fix-1/independent/00-snapshot-end.json）记录的 fix-1 终态哈希。
PREVIOUS_SNAPSHOT = REPO / "docs/reports/OBS-EVAL/P2/H2V3/fix-1/independent/00-snapshot-end.json"

HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_text_keep_newline(path: Path) -> tuple[str, str]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        raw = handle.read()
    newline = "\r\n" if "\r\n" in raw else "\n"
    return raw.replace("\r\n", "\n"), newline


def parse_patch(text: str) -> list[dict]:
    lines = text.split("\n")
    sections: list[dict] = []
    index = 0
    while index < len(lines):
        if not lines[index].startswith("--- "):
            index += 1
            continue
        old_path = lines[index][4:].strip()
        index += 1
        if index >= len(lines) or not lines[index].startswith("+++ "):
            raise SystemExit(f"bad patch: no +++ after --- at {index}")
        new_path = lines[index][4:].strip()
        index += 1
        hunks: list[dict] = []
        while index < len(lines) and not lines[index].startswith("--- "):
            header = lines[index]
            match = HUNK.match(header)
            if not match:
                if header == "" and index == len(lines) - 1:
                    index += 1
                    continue
                raise SystemExit(f"bad hunk header: {header!r}")
            old_start = int(match.group(1))
            old_count = int(match.group(2) or 1)
            new_start = int(match.group(3))
            new_count = int(match.group(4) or 1)
            index += 1
            body: list[str] = []
            while index < len(lines) and not lines[index].startswith("@@") and not lines[index].startswith("--- "):
                line = lines[index]
                if line.startswith("\\"):
                    index += 1
                    continue
                if line == "" and index == len(lines) - 1:
                    index += 1
                    continue
                body.append(line)
                index += 1
            hunks.append(
                {
                    "old_start": old_start,
                    "old_count": old_count,
                    "new_start": new_start,
                    "new_count": new_count,
                    "body": body,
                }
            )
        sections.append({"old_path": old_path, "new_path": new_path, "hunks": hunks})
    return sections


def display_path(raw: str) -> str:
    if raw == "/dev/null":
        return raw
    prefix = "a/" if raw.startswith("a/") else "b/" if raw.startswith("b/") else ""
    return raw[len(prefix):] if prefix else raw


def apply_section(target: str, section: dict, reverse: bool) -> str:
    source_lines = target.split("\n")
    # split("\n") 会在末尾多出一个空串；保持它，拼回时等价。
    out: list[str] = []
    cursor = 0
    for hunk in section["hunks"]:
        if reverse:
            block_start = hunk["new_start"]
            expected = hunk["new_count"]
        else:
            block_start = hunk["old_start"]
            expected = hunk["old_count"]
        src = [line[1:] for line in hunk["body"] if line[:1] in (" ", "+" if reverse else "-")]
        dst = [line[1:] for line in hunk["body"] if line[:1] in (" ", "-" if reverse else "+")]
        if len(src) != expected:
            raise SystemExit(
                f"hunk declaration mismatch: declared {expected}, source lines {len(src)}, "
                f"header {hunk}"
            )
        start_index = block_start - 1 if block_start > 0 else 0
        if block_start == 0:
            start_index = 0
        if start_index > len(source_lines):
            raise SystemExit(f"hunk starts past EOF: {block_start}")
        out.extend(source_lines[cursor:start_index])
        found = source_lines[start_index:start_index + len(src)]
        if found != src:
            for offset, (want, got) in enumerate(zip(src, found)):
                if want != got:
                    raise SystemExit(
                        f"context mismatch at {start_index + offset + 1}: "
                        f"want={want!r} got={got!r}"
                    )
            raise SystemExit(
                f"context length mismatch at {start_index + 1}: "
                f"want {len(src)} lines, file has {len(found)}"
            )
        out.extend(dst)
        cursor = start_index + len(src)
    out.extend(source_lines[cursor:])
    return "\n".join(out)


def hash_target(path: Path, newline: str, text: str) -> str:
    if newline == "\r\n":
        text = text.replace("\n", "\r\n")
    return sha_bytes(text.encode("utf-8"))


def main() -> int:
    patch_text = DIFF.read_text(encoding="utf-8")
    diff_sha = sha_bytes(DIFF.read_bytes())
    body = "\n".join(patch_text.split("\n")[1:])  # 去掉首行说明
    if not body.startswith("--- "):
        raise SystemExit("patch body does not start with ---")
    sections = parse_patch(body)

    # 上一轮独立验收快照里的 fix-1 终态哈希（交叉核对预期改前值）。
    snapshot = json.loads(PREVIOUS_SNAPSHOT.read_text(encoding="utf-8"))
    snapshot_hashes = {
        row["path"]: row["sha256"]
        for row in snapshot["tracked_modified"]
        if row["path"] in PRE_R1
    }

    results: dict[str, dict] = {}
    total_deletions: list[dict] = []
    deletions_by_file: dict[str, list[str]] = {}
    additions_by_file: dict[str, int] = {}
    for section in sections:
        old_path = display_path(section["old_path"])
        new_path = display_path(section["new_path"])
        rel = new_path if new_path != "/dev/null" else old_path
        deletions = [
            line[1:]
            for hunk in section["hunks"]
            for line in hunk["body"]
            if line.startswith("-")
        ]
        additions = sum(
            1
            for hunk in section["hunks"]
            for line in hunk["body"]
            if line.startswith("+")
        )
        deletions_by_file[rel] = deletions
        additions_by_file[rel] = additions
        total_deletions.extend({"path": rel, "line": line} for line in deletions)

        if rel in CURRENT:
            current_path = REPO / rel
            current_text, newline = read_text_keep_newline(current_path)
            actual_current = sha_bytes(current_path.read_bytes())
            pre_text = apply_section(current_text, section, reverse=True)
            pre_sha = hash_target(current_path, newline, pre_text)
            forward_text = apply_section(pre_text.replace("\r\n", "\n"), section, reverse=False)
            forward_sha = hash_target(current_path, newline, forward_text)
            results[rel] = {
                "current_sha256_actual": actual_current,
                "current_sha256_expected": CURRENT[rel],
                "current_matches": actual_current == CURRENT[rel],
                "pre_r1_sha256_reconstructed": pre_sha,
                "pre_r1_sha256_expected": PRE_R1[rel],
                "pre_r1_matches": pre_sha == PRE_R1[rel],
                "previous_snapshot_sha256": snapshot_hashes.get(rel),
                "pre_r1_matches_previous_snapshot": pre_sha == snapshot_hashes.get(rel),
                "forward_apply_sha256": forward_sha,
                "forward_returns_current": forward_sha == actual_current,
                "additions": additions,
                "deletions": deletions,
            }
        elif new_path == "/dev/null" or old_path == "/dev/null":
            # 新文件：反向应用后应为空。
            current_path = REPO / new_path
            current_text, newline = read_text_keep_newline(current_path)
            actual_current = sha_bytes(current_path.read_bytes())
            pre_text = apply_section(current_text, section, reverse=True)
            results[rel] = {
                "current_sha256_actual": actual_current,
                "current_bytes": current_path.stat().st_size,
                "reverse_apply_residual_chars": len(pre_text.strip()),
                "new_file_removed_by_reverse": pre_text.strip() == "",
                "additions": additions,
                "deletions": deletions,
            }
        else:
            raise SystemExit(f"unexpected section: {section['old_path']} -> {section['new_path']}")

    fix1_markers = ("v3-fix-1/A", "multi_target", "multi_items", "items=")
    rollback_suspicion = [
        row for row in total_deletions if any(marker in row["line"] for marker in fix1_markers)
    ]
    payload = {
        "schema_version": "v3-fix1r1-independent-diff-verify/v0.1",
        "diff_path": str(DIFF.relative_to(REPO)).replace("\\", "/"),
        "diff_sha256": diff_sha,
        "diff_bytes": DIFF.stat().st_size,
        "sections": results,
        "additions_by_file": additions_by_file,
        "deletions_by_file": deletions_by_file,
        "deleted_line_count": len(total_deletions),
        "deleted_lines": total_deletions,
        "rollback_of_fix1_suspected": rollback_suspicion,
        "only_append_with_one_line_rewritten": (
            len(total_deletions) == 1
            and total_deletions[0]["path"] == "backend/src/mktkb/rag/query.py"
            and total_deletions[0]["line"].strip()
            == "anaphora = any(word in question for word in ANAPHORA_WORDS)"
            and not rollback_suspicion
        ),
        "notes": [
            "diff 首行是说明注释，已剥离后按标准 unified diff 解析。",
            "反向应用以当前工作树文件为目标，不改工作树。",
            "上一轮快照 00-snapshot-end.json 交叉核对改前（fix-1 终态）哈希。",
        ],
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "diff_sha256": diff_sha,
        "only_append_with_one_line_rewritten": payload["only_append_with_one_line_rewritten"],
        "deleted_line_count": len(total_deletions),
        "deletions_by_file": {k: len(v) for k, v in deletions_by_file.items()},
        "sections": {k: {kk: vv for kk, vv in v.items() if kk in {
            "current_matches", "pre_r1_matches", "pre_r1_matches_previous_snapshot",
            "forward_returns_current", "new_file_removed_by_reverse"}} for k, v in results.items()},
        "rollback_of_fix1_suspected": rollback_suspicion,
    }, ensure_ascii=False, indent=1))
    return 0 if payload["only_append_with_one_line_rewritten"] and all(
        v.get("current_matches", True)
        and v.get("pre_r1_matches", True)
        and v.get("pre_r1_matches_previous_snapshot", True)
        and v.get("forward_returns_current", True)
        and v.get("new_file_removed_by_reverse", True)
        for v in results.values()
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())

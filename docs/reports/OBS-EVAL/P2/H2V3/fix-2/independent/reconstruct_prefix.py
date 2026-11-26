"""重建 fix-2 改前源码（本包自建反向应用器，不信开发方的"改前"声明）。

做法：
  1. 自己解析 `evidence/fix-2.diff`（unified diff，按 new-file 坐标即"改后文件"行号）；
  2. 对每个 hunk，把 `+` 侧内容（= 当前文件内容）精确替换回 `-` 侧内容；
  3. 递归复制 `backend/src/mktkb` 到临时目录，用重建结果覆盖这两个文件；
  4. 计算重建后 SHA-256，与**上一轮独立产物**（safety-fix/evidence/fix-sha.json 的
     after_sha256）逐字节比对 —— 相等才说明"改前 == 上一轮收尾"，也说明本包 diff
     只在这两个文件上、且没有回退既有改动。

输出：reconstruct-prefix.json。
"""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[6]
DIFF = HERE.parent / "evidence" / "fix-2.diff"
PRIOR = REPO / "docs/reports/OBS-EVAL/P2/H2V3/safety-fix/evidence/fix-sha.json"
OUT = HERE / "reconstruct-prefix.json"


def parse_diff(text: str) -> dict[str, list[tuple[int, list[str], list[str]]]]:
    """{path: [(new_start, minus_lines, plus_lines), ...]}；路径取 `+++ b/<path>`。"""
    files: dict[str, list[tuple[int, list[str], list[str]]]] = {}
    current: str | None = None
    hunk: list[Any] | None = None
    for raw in text.splitlines():
        if raw.startswith("--- "):
            # 文件头（上一个文件结束）。必须先于内容行的 "-" 判断，否则会被当成删除行。
            hunk = None
            current = None
        elif raw.startswith("+++ "):
            current = raw[4:].strip()
            if current.startswith("b/"):
                current = current[2:]
            files.setdefault(current, [])
            hunk = None
        elif raw.startswith("@@"):
            head = raw.split("@@")[1].strip()
            new_part = head.split("+")[1].split(" ")[0]
            new_start = int(new_part.split(",")[0])
            hunk = [new_start, [], []]
            files[current].append(hunk)  # type: ignore[index]
        elif hunk is not None and current is not None:
            if raw.startswith("\\"):
                continue
            if raw.startswith("+"):
                hunk[2].append(raw[1:])
            elif raw.startswith("-"):
                hunk[1].append(raw[1:])
            elif raw.startswith(" "):
                hunk[2].append(raw[1:])
                hunk[1].append(raw[1:])
            elif raw == "":
                hunk[2].append("")
                hunk[1].append("")
    return files


def reverse_file(path: Path, hunks: list[tuple[int, list[str], list[str]]]) -> tuple[str, dict[str, Any]]:
    raw = path.read_bytes()
    crlf = raw.count(b"\r\n") == raw.count(b"\n") and raw.count(b"\r\n") > 0
    text = raw.decode("utf-8").replace("\r\n", "\n")
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines = lines[:-1]
    applied = 0
    for new_start, minus, plus in sorted(hunks, key=lambda h: h[0], reverse=True):
        begin = new_start - 1
        end = begin + len(plus)
        if lines[begin:end] != plus:
            raise SystemExit(
                "hunk mismatch in %s at new_start=%d: %r != %r"
                % (path.name, new_start, lines[begin:end][:2], plus[:2])
            )
        lines[begin:end] = minus
        applied += 1
    rebuilt = "\n".join(lines) + "\n"
    if crlf:
        rebuilt = rebuilt.replace("\n", "\r\n")
    return rebuilt, {"hunks": len(hunks), "applied": applied, "crlf": crlf}


def main() -> int:
    diff_files = parse_diff(DIFF.read_text(encoding="utf-8"))
    prior = json.loads(PRIOR.read_text(encoding="utf-8"))
    prior_after = {row["path"]: row["after_sha256"] for row in prior["files"]}

    overlay = Path(tempfile.mkdtemp(prefix="mktkb-fix2-prefix-")) / "src"
    overlay.mkdir(parents=True)
    shutil.copytree(REPO / "backend" / "src" / "mktkb", overlay / "mktkb")

    report: list[dict[str, Any]] = []
    ok = True
    for rel, hunks in diff_files.items():
        target = overlay / rel.replace("backend/src/", "", 1)
        rebuilt, meta = reverse_file(target, hunks)
        target.write_bytes(rebuilt.encode("utf-8"))
        sha = hashlib.sha256(target.read_bytes()).hexdigest()
        expected = prior_after.get(rel)
        match = sha == expected
        ok = ok and match
        report.append(
            {
                "path": rel,
                "rebuilt_sha256": sha,
                "prior_round_after_sha256": expected,
                "equals_prior_round_end": match,
                "hunks": meta["hunks"],
                "hunks_applied": meta["applied"],
                "crlf_preserved": meta["crlf"],
            }
        )

    payload = {
        "schema_version": "v3-fix2-independent-reconstruct/v0.1",
        "diff": "evidence/fix-2.diff",
        "diff_files": sorted(diff_files),
        "overlay_src": str(overlay),
        "files": report,
        "all_equal_prior_round_end": ok,
        "method": "自建 unified-diff 反向应用（按 new-file 坐标精确替换，无 fuzz）；期望值取自 safety-fix 独立产物 fix-sha.json 的 after_sha256。",
        "notes": [
            "只反演 fix-2.diff 涉及的两个文件；overlay 其余文件由 copytree 复制，与仓库现状逐字节相同。",
            "改前 == 上一轮收尾，说明本轮 diff 未回退既有改动（否则 SHA 不可能相等）。",
        ],
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                   encoding="utf-8")
    print(json.dumps({"all_equal": ok, "files": report, "overlay_src": str(overlay)},
                     ensure_ascii=False, indent=1))
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())

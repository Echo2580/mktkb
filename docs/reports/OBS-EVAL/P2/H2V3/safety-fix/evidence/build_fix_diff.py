"""生成 v3-safety-fix 的修复 diff（含改前/改后 SHA-256 与来源说明）。

- `rag/query.py`、`conversations/service.py`：本轮开始前已是 fix-1/fix-1r1 的 modified
  状态，因此用 `reconstruct_pre_round.py` 反向重建改前字节，再逐行 diff；
- `conversations/intent.py`、`copy.py`、`rag/answer.py`：本轮开始前相对 HEAD 干净，
  直接取 `git diff HEAD`。

输出：`fix.diff`、`fix-sha.json`。
"""

from __future__ import annotations

import difflib
import hashlib
import json
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[6]

QUERY = "backend/src/mktkb/rag/query.py"
SERVICE = "backend/src/mktkb/conversations/service.py"
CLEAN_AT_HEAD = (
    "backend/src/mktkb/conversations/intent.py",
    "backend/src/mktkb/copy.py",
    "backend/src/mktkb/rag/answer.py",
)

QUERY_BLOCKS = (
    "#: v3-safety-fix：个人联系信息字段角色（店家记录独有）。物品记录 + 这些角色的同一请求\n"
    "#: 属于跨资料合并，规划层直接给出安全拒答原因（答案层在任何检索/模型之前收口）。\n"
    'RESTRICTED_CONTACT_ROLES: frozenset[str] = frozenset({"contact", "phone", "address"})\n',
    "\n"
    "    # v3-safety-fix：本轮显式点名了物品目标，同时要店家个人联系信息（联系人/电话/地址）。\n"
    "    # 物品记录与店家联系信息分属两份资料，合并提供属于受限个人信息范围；在检索与任何\n"
    "    # 模型调用之前整体拒答（纯店家级联系信息查询、只问物品位置等非个人字段不受影响）。\n"
    "    if (\n"
    "        (bool(item_hits) or identifier is not None)\n"
    "        and set(field_roles) & RESTRICTED_CONTACT_ROLES\n"
    "        and not is_policy_question(question)\n"
    "    ):\n"
    "        return QueryPlan(\n"
    "            question=question,\n"
    '            mode="record",\n'
    "            query_text=question,\n"
    "            field_role=state.field_role,\n"
    "            field_label=state.field_role,\n"
    "            filters=filters,\n"
    "            terms=_terms(question),\n"
    "            state=state,\n"
    "            enumerate=state.enumerate,\n"
    "            page=state.page,\n"
    "            page_size=state.page_size,\n"
    "            include_future=include_future,\n"
    '            reason="SECURITY_RESTRICTED_CONTACT",\n'
    "        )\n",
)
SERVICE_BLOCKS = (
    "            security_refusal=bool(plan.security_refusal),\n",
    "    # v3-safety-fix：物品记录与店家个人联系信息（联系人/电话/地址）的跨资料合并请求，\n"
    "    # 在任何检索/模型调用之前按安全策略整体拒答；不按题号或固定整句特判。\n"
    "    if plan.security_refusal:\n"
    "        return _Result(\n"
    '            kind="not_found",\n'
    "            text=copy_module.text(plan.security_refusal),\n"
    "            revision=revision,\n"
    "            reason=plan.security_refusal,\n"
    "        )\n",
)


def _rebuild(path: str, blocks: tuple[str, ...]) -> bytes:
    current = (REPO / path).read_bytes()
    newline = "\r\n" if b"\r\n" in current else "\n"
    rebuilt = current
    for block in blocks:
        encoded = block.replace("\n", newline).encode("utf-8")
        rebuilt = rebuilt.replace(encoded, b"", 1)
    return rebuilt


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    chunks: list[str] = []
    sha_rows: list[dict[str, str]] = []

    for path, blocks in ((QUERY, QUERY_BLOCKS), (SERVICE, SERVICE_BLOCKS)):
        before = _rebuild(path, blocks)
        after = (REPO / path).read_bytes()
        before_lines = before.decode("utf-8").splitlines(keepends=True)
        after_lines = after.decode("utf-8").splitlines(keepends=True)
        diff = difflib.unified_diff(
            before_lines,
            after_lines,
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
        )
        chunks.append("".join(line if line.endswith("\n") else line + "\n" for line in diff))
        sha_rows.append(
            {
                "path": path,
                "before_sha256": _sha(before),
                "after_sha256": _sha(after),
                "before_basis": "reconstruct_pre_round.py（反向删除本包新增块；SHA 与 fix-1r1 收尾快照逐字节相等）",
            }
        )

    git_diff = subprocess.run(
        ["git", "-C", str(REPO), "diff", "HEAD", "--", *CLEAN_AT_HEAD],
        capture_output=True,
    )
    if git_diff.returncode != 0:
        raise SystemExit(git_diff.stderr.decode("utf-8", "replace"))
    chunks.append(git_diff.stdout.decode("utf-8"))
    for path in CLEAN_AT_HEAD:
        head = subprocess.run(
            ["git", "-C", str(REPO), "show", f"HEAD:{path}"], capture_output=True
        ).stdout
        now = (REPO / path).read_bytes()
        sha_rows.append(
            {
                "path": path,
                "before_sha256": _sha(head),
                "after_sha256": _sha(now),
                "before_basis": "HEAD（本轮开始前工作树干净）",
            }
        )

    (HERE / "fix.diff").write_text("\n".join(chunks), encoding="utf-8")
    payload = {
        "schema_version": "v3-safety-fix-sha/v0.1",
        "files": sha_rows,
        "new_test_files": [
            {
                "path": path,
                "sha256": _sha((REPO / path).read_bytes()),
            }
            for path in (
                "backend/tests/unit/test_v3_safety_fix_policy.py",
                "backend/tests/integration/test_v3_safety_fix_e2e.py",
            )
        ],
    }
    (HERE / "fix-sha.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload, ensure_ascii=True, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

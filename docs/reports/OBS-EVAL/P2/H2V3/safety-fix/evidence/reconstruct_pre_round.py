"""v3-safety-fix：按本包新增块反向重建“改前”文件，验证改动范围可复现。

只对两处工作树里本来就 modified 的文件（fix-1/fix-1r1 之后的状态）做反向删除：
- `backend/src/mktkb/rag/query.py`：常量块 + 安全拒答分支；
- `backend/src/mktkb/conversations/service.py`：annotate 键 + 安全拒答分支。

重建结果必须与 fix-1r1 收尾快照记录的 SHA-256 逐字节相等，否则说明本包超出声明范围。
其余三个源文件（intent.py / copy.py / answer.py）在本轮开始前是 HEAD 干净状态，直接用
`git diff HEAD` 即可，无需重建。

输出：`reconstructed-pre-round.json`（只含路径/字节/SHA/是否匹配，不写源码）。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[6]
OUT = HERE / "reconstructed-pre-round.json"

#: 本包新增的精确文本块（逐字节）；反向重建 = 从当前文件删除这些块。
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

EXPECTED = {
    "backend/src/mktkb/rag/query.py": "82776def986afa6defd37d75f6596a51dc1402fcdbe4725c7aa7d7d1ecc27fef",
    "backend/src/mktkb/conversations/service.py": "29b0a29582ee08298c842087ce9f50b4b2c2ccba4103fa03e0c3920bb48984f0",
}


def main() -> int:
    rows = []
    for path, blocks in (
        ("backend/src/mktkb/rag/query.py", QUERY_BLOCKS),
        ("backend/src/mktkb/conversations/service.py", SERVICE_BLOCKS),
    ):
        current_bytes = (REPO / path).read_bytes()
        newline = b"\r\n" if b"\r\n" in current_bytes else b"\n"
        rebuilt = current_bytes
        removed = []
        for block in blocks:
            encoded = block.replace("\n", "\r\n").encode("utf-8") if newline == b"\r\n" else block.encode("utf-8")
            count = rebuilt.count(encoded)
            if count != 1:
                raise SystemExit(f"{path}: block count {count} != 1")
            rebuilt = rebuilt.replace(encoded, b"", 1)
            removed.append(len(encoded))
        digest = hashlib.sha256(rebuilt).hexdigest()
        rows.append(
            {
                "path": path,
                "line_ending": "crlf" if newline == b"\r\n" else "lf",
                "current_sha256": hashlib.sha256(current_bytes).hexdigest(),
                "reconstructed_sha256": digest,
                "expected_pre_round_sha256": EXPECTED[path],
                "matches_fix1r1_snapshot": digest == EXPECTED[path],
                "removed_blocks": removed,
            }
        )
    payload = {
        "schema_version": "v3-safety-fix-reconstruction/v0.1",
        "rows": rows,
        "all_match": all(row["matches_fix1r1_snapshot"] for row in rows),
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=True, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

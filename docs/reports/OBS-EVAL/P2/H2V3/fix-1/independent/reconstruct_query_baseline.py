"""把 rag/query.py 中的 v3-fix-1/A 追加块逐一反向删除，检验是否逐字节回到改前基线。

只读当前文件、只写临时文件；不改工作树。目标基线 SHA-256：
5a7ed26b73a3ab658deff6384b5fdcc67596860345153cec4ec4f72cb350e1e1
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[7]
TARGET = REPO / "backend/src/mktkb/rag/query.py"
OUT = Path(__file__).resolve().parent / "A-query-baseline-reconstruct.json"
EXPECTED = "5a7ed26b73a3ab658deff6384b5fdcc67596860345153cec4ec4f72cb350e1e1"

text = TARGET.read_text(encoding="utf-8")
replacements = [
    (
        "    stores: tuple[str, ...],\n    items: tuple[str, ...] = (),\n    field_role: str | None,",
        "    stores: tuple[str, ...],\n    field_role: str | None,",
    ),
    (
        "        state.item = previous.item\n        state.items = previous.items\n",
        "        state.item = previous.item\n",
    ),
    (
        "        state.stores = ()\n        state.items = ()\n    elif slots.get(\"doc_id\")",
        "        state.stores = ()\n    elif slots.get(\"doc_id\")",
    ),
    (
        """    # v3-fix-1/A：多目标物品只在“本轮明确点名多个物品”时进入状态；换了门店/改问单物品
    # 时必须清掉旧集合，避免上一轮的多目标过滤条件污染本轮检索。
    if items:
        state.items = tuple(items)
    elif slots.get("item"):
        state.items = (slots["item"],)
    elif slots.get("store") or stores:
        state.items = ()
""",
        "",
    ),
    (
        """    # v3-fix-1/A：本轮明确点名多个物品时，“物品”这一维已给出，不再要求补门店。
    has_item_scope = bool(state.item) or len(tuple(getattr(state, "items", ()) or ())) > 1
""",
        "",
    ),
    (
        "if not (state.product or has_item_scope or state.identifier):",
        "if not (state.product or state.item or state.identifier):",
    ),
    (
        "if not (state.store or has_item_scope or state.product or state.identifier):",
        "if not (state.store or state.item or state.product or state.identifier):",
    ),
    (
        "if not any((state.store, has_item_scope, state.product, state.identifier, state.doc_id)):",
        "if not any((state.store, state.item, state.product, state.identifier, state.doc_id)):",
    ),
    (
        """    # v3-fix-1/A：同一轮内**明确提出**的多个目标（同一维度 ≥2、另一维度 ≤1）按多目标
    # 枚举执行，不再判澄清：目标都是词表里的确定实体，答案按目标逐条列出。
    # 真歧义仍保持既有澄清/拒绝面：两个维度都 ≥2（交叉配对不明）、词表外门店/区域、
    # 资料或产品歧义、本轮没有可回答的字段、指代追问与政策正文题都不在此列。
    multi_stores = len(stores) > 1
    multi_items = len(item_hits) > 1 and not product
    multi_target = (
        (multi_stores != multi_items)
        and field_role in RECORD_FIELD_ROLES
        and not anaphora
        and not policy_followup
        and not unknown_stores
        and not unknown_regions
        and not missing_document
        and identifier is None
        and not document_candidates
        and not product_candidates
    )
    if multi_target:
        enumerate_flag = True

""",
        "",
    ),
    (
        "        items=item_hits if (multi_target and multi_items) else (),\n",
        "",
    ),
    (
        """    if multi_target:
        # 本轮已点名多个确定目标：旧澄清槽不再挂起，避免下一轮又把已给出的一维当缺失。
        state.pending_slot = None
        state.candidates = ()
""",
        "",
    ),
    (
        """    if len(item_hits) > 1 and not multi_target:
        # v3-fix-1/A：本轮不满足多目标条件（例如门店与物品两维同时点名多个、交叉配对
        # 不明，或没有可回答的字段）时，仍按“哪一条”先澄清；确定的多目标轮次不走这里。
""",
        "    if len(item_hits) > 1:\n",
    ),
    (
        """    if multi_target and plan_reason is None:
        # 只作“本轮由内核按多目标枚举作答”的标记（产品层据此把轮次交给 rag 内核），
        # 不参与事实判定，也不改写任何拒绝/澄清原因。
        plan_reason = "MULTI_TARGET_ENUMERATE"
""",
        "",
    ),
]

reconstructed = text
applied = []
for old, new in replacements:
    count = reconstructed.count(old)
    applied.append({"count": count, "old_head": old.splitlines()[0][:80]})
    if count != 1:
        raise SystemExit(f"replacement count {count} != 1 for {old[:60]!r}")
    reconstructed = reconstructed.replace(old, new)

raw = reconstructed.encode("utf-8")
# 工作树文件是 CRLF；read_text 做了通用换行归一，回写时按原文件形态还原。
crlf = reconstructed.replace("\n", "\r\n").encode("utf-8")
sha = hashlib.sha256(crlf).hexdigest()
OUT.write_text(
    json.dumps(
        {
            "schema_version": "v3-fix1-independent-A-baseline-reconstruct/v0.1",
            "target": "backend/src/mktkb/rag/query.py",
            "current_sha256": hashlib.sha256(TARGET.read_bytes()).hexdigest(),
            "expected_baseline_sha256": EXPECTED,
            "reconstructed_sha256": sha,
            "reconstructed_sha256_lf": hashlib.sha256(raw).hexdigest(),
            "reconstructed_bytes": len(crlf),
            "line_endings": "crlf_preserved",
            "matches_expected": sha == EXPECTED,
            "applied": applied,
        },
        ensure_ascii=False,
        indent=2,
    )
    + "\n",
    encoding="utf-8",
)
print(json.dumps({"reconstructed": sha, "expected": EXPECTED, "match": sha == EXPECTED,
                  "bytes": len(crlf)}, indent=1))
(Path(__file__).resolve().parent / "_reconstructed_query.py").write_text(
    reconstructed, encoding="utf-8", newline="\r\n"
)

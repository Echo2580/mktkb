"""重建 fix-2 之前的两个文件字节并给出改前/改后 SHA-256（用于报告的“改前/改后”对照）。

做法：把本轮 5 处编辑逐条**反向替换**回改前文本，写入临时文件，比对 SHA：
- 与 safety-fix 报告 §7.1 记录的“改后 SHA”逐值相等 → 说明本轮改前基线 = 上一轮收尾状态；
- 反向重建成功后再正向重放，输出 `fix-2.diff`（unified diff）。
"""

from __future__ import annotations

import difflib
import hashlib
import json
import pathlib
import sys

REPO = pathlib.Path(r"D:\GPT项目\市场部AI知识库")
OUT = REPO / "docs/reports/OBS-EVAL/P2/H2V3/fix-2/evidence"

# --- 上一轮（safety-fix）报告 §7.1 记录的“改后 SHA-256”，即本轮改前基线 ---
BASELINE_SHA = {
    "backend/src/mktkb/rag/query.py": "fc55db53f2b7a00292b538a3797f6ba456b6d871c95df026065bd5b74feb4549",
    "backend/src/mktkb/rag/answer.py": "55778d8f1446aaedc836c194b1ed9c82d8d3a54b89cb14046ac2175981aca63a",
}

# --- 反向替换：new -> old（逐条，顺序无关，各替换一次） ---
REVERSE = {
    "backend/src/mktkb/rag/query.py": [
        (
            "    identifier = _match_identifier(question, lexicon)\n"
            "    document, document_candidates = _match_document(question, lexicon)\n"
            "    missing_stores = unknown_stores if stores else ()\n",
            "    identifier = _match_identifier(question, lexicon)\n"
            "    document, document_candidates = _match_document(question, lexicon)\n"
            "    missing_document = _missing_document(question) if document is None else None\n"
            "    missing_stores = unknown_stores if stores else ()\n",
        ),
        (
            "    field_role = field_roles[0] if field_roles else None\n"
            "    # v3-fix-2/A：本轮已点名记录实体（门店/物品/商品/标识）**且**问的是记录字段时，\n"
            "    # “XX表/XX清单/XX通知/XX资料”这类字样只是行文里的顺带提及，不是“点了一份不存在的资料”。\n"
            "    # 让 ``_missing_document`` 在这种轮次上不触发，避免把可作答的记录题判成 DOCUMENT_NOT_FOUND\n"
            "    # （同一 gate 也用于资料歧义分支：记录实体已唯一确定时，资料歧义不该抢占记录作答）。\n"
            "    # 反例保持：点名未收录资料的题（“促销活动台账在哪里？”）没有记录实体/记录字段，仍按原路判缺失。\n"
            "    record_scope = bool(stores or item_hits or product or identifier)\n"
            "    record_field_scope = record_scope and field_role in RECORD_FIELD_ROLES\n"
            "    missing_document = (\n"
            "        _missing_document(question) if document is None and not record_field_scope else None\n"
            "    )\n"
            "    page_request = _page_request(question, previous)\n",
            "    field_role = field_roles[0] if field_roles else None\n"
            "    page_request = _page_request(question, previous)\n",
        ),
        (
            "    # v3-fix-2/A：指代词的两种身份要分开。**指代本身充当目标**（“这两个/这几个/它们”，\n"
            "    # 本轮没点名物品）时仍是真歧义，必须澄清（fix-1r1 正面成果）；指代词只是行文里的\n"
            "    # 回指填充（“那个位置”“那件已经停用的”），而本轮已点名物品目标时，目标由显式实体\n"
            "    # 唯一确定，不应再因一个虚指词把可作答的多目标轮次打回澄清。\n"
            "    anaphora_blocks_multi_target = anaphora and (quantified_anaphora or not (item_hits or product))\n"
            "    multi_target = (\n"
            "        (multi_stores != multi_items)\n"
            "        and field_role in RECORD_FIELD_ROLES\n"
            "        and not anaphora_blocks_multi_target\n"
            "        and not policy_followup\n"
            "        and not unknown_stores\n"
            "        and not unknown_regions\n"
            "        and not missing_document\n"
            "        and identifier is None\n"
            "        and not (document_candidates and not record_field_scope)\n"
            "        and not product_candidates\n"
            "    )\n",
            "    multi_target = (\n"
            "        (multi_stores != multi_items)\n"
            "        and field_role in RECORD_FIELD_ROLES\n"
            "        and not anaphora\n"
            "        and not policy_followup\n"
            "        and not unknown_stores\n"
            "        and not unknown_regions\n"
            "        and not missing_document\n"
            "        and identifier is None\n"
            "        and not document_candidates\n"
            "        and not product_candidates\n"
            "    )\n",
        ),
        (
            "    # 多个候选对象：先澄清，不检索。\n"
            "    # v3-fix-2/A：本轮已点名记录实体且问的是记录字段时，记录目标已唯一确定，资料歧义不抢占作答\n"
            "    # （否则多店/单物品这类可作答轮次会被判 DOCUMENT_AMBIGUOUS → 交回 legacy → 多实体澄清）。\n"
            "    if document_candidates and not state.doc_id and not record_field_scope:\n",
            "    # 多个候选对象：先澄清，不检索。\n"
            "    if document_candidates and not state.doc_id:\n",
        ),
        (
            "    # v3-fix-2/B：“指代追问”按定义要有先行语（上文）。首轮（``previous.turn == 0``）没有可\n"
            "    # 回指的对象，此时句中“那个/该/其”只是行文虚指，不构成“追问”，不能据此把已点名门店+物品\n"
            "    # 的首轮请求直接收口成“未记录该字段”（那会在任何检索之前就把有据可答的问题判成找不到）。\n"
            "    # 首轮按“显式实体 → 记录枚举”作答；追问仍走原有 collapse（T105 R1/B2 口径不变）。\n"
            "    has_prior_context = previous.turn > 0\n"
            "    anaphora_new_content = (\n"
            "        anaphora\n"
            "        and has_prior_context\n"
            "        and not field_roles\n"
            "        and bool(anaphora_residual)\n"
            "        and explicit_record_entity\n"
            "        and page_request is None\n"
            "        and not any(word in question for word in ENUMERATE_WORDS)\n"
            "        # T105 R2：政策/法规题不能落进“新内容→未记录”收口（C3/C6 的 35 字 not_found），\n"
            "        # 也不能按继承字段作答；交回既有正文检索（T101 法规优先、T102 政策题口径）。\n"
            "        and not policy_followup\n"
            "    )\n"
            "    first_turn_new_content = (\n"
            "        anaphora\n"
            "        and not has_prior_context\n"
            "        and not field_roles\n"
            "        and bool(anaphora_residual)\n"
            "        and explicit_record_entity\n"
            "        and page_request is None\n"
            "        and not any(word in question for word in ENUMERATE_WORDS)\n"
            "        and not policy_followup\n"
            "    )\n"
            "    if anaphora_new_content:\n"
            "        # 不继承的只是“本轮答什么”：保留已继承的实体/字段供后续纯指代追问继续使用。\n"
            "        state.enumerate = True\n"
            "        plan_reason = \"ANAPHORA_NEW_CONTENT\"\n"
            "    elif first_turn_new_content:\n"
            "        # 首轮无先行语：按显式实体的记录枚举作答（不猜字段、不倾倒未问字段以外的内容）。\n"
            "        state.enumerate = True\n"
            "    elif (\n",
            "    anaphora_new_content = (\n"
            "        anaphora\n"
            "        and not field_roles\n"
            "        and bool(anaphora_residual)\n"
            "        and explicit_record_entity\n"
            "        and page_request is None\n"
            "        and not any(word in question for word in ENUMERATE_WORDS)\n"
            "        # T105 R2：政策/法规题不能落进“新内容→未记录”收口（C3/C6 的 35 字 not_found），\n"
            "        # 也不能按继承字段作答；交回既有正文检索（T101 法规优先、T102 政策题口径）。\n"
            "        and not policy_followup\n"
            "    )\n"
            "    if anaphora_new_content:\n"
            "        # 不继承的只是“本轮答什么”：保留已继承的实体/字段供后续纯指代追问继续使用。\n"
            "        state.enumerate = True\n"
            "        plan_reason = \"ANAPHORA_NEW_CONTENT\"\n"
            "    elif (\n",
        ),
    ],
    "backend/src/mktkb/rag/answer.py": [
        (
            "    if plan.enumerate and int(getattr(plan.state, \"turn\", 0) or 0) > 1 and is_anaphora_field_followup(\n"
            "        plan.question, plan.field_role\n"
            "    ):\n"
            "        # T105/ERR-06：指代追问只继承字段时，``enumerate`` 只是产品层“交给 rag 直答”的\n"
            "        # 入口，用户没有要求枚举；这里按单字段答案渲染，避免把整条记录全字段倾倒出来。\n"
            "        # v3-fix-2/A：本收敛按定义只适用于**追问**（有上文可继承字段）。首轮没有可继承字段，\n"
            "        # 句中“那个/该/其”只是行文虚指；若照旧把 enumerate 关掉，多目标轮次会退化成\n"
            "        # “多个对象不能唯一确定”的歧义澄清（可作答的题被判澄清）。首轮保持枚举渲染。\n"
            "        plan = replace(plan, enumerate=False, state=QueryState.from_dict(plan.state.to_dict()))\n"
            "        plan.state.enumerate = False\n",
            "    if plan.enumerate and is_anaphora_field_followup(plan.question, plan.field_role):\n"
            "        # T105/ERR-06：指代追问只继承字段时，``enumerate`` 只是产品层“交给 rag 直答”的\n"
            "        # 入口，用户没有要求枚举；这里按单字段答案渲染，避免把整条记录全字段倾倒出来。\n"
            "        plan = replace(plan, enumerate=False, state=QueryState.from_dict(plan.state.to_dict()))\n"
            "        plan.state.enumerate = False\n",
        ),
    ],
}


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_crlf(text: str) -> str:
    """按磁盘字节口径（CRLF 换行）计算；上一轮报告记录的 SHA 用的是这个口径。"""
    normalized = text.replace("\r\n", "\n").replace("\n", "\r\n")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def main() -> int:
    report: dict[str, object] = {"files": []}
    diffs: list[str] = []
    for relative, replacements in REVERSE.items():
        current_path = REPO / relative
        raw_after = current_path.read_bytes().decode("utf-8")
        current = raw_after.replace("\r\n", "\n")
        after_sha = sha256_crlf(current)
        before = current
        applied = 0
        for new, old in replacements:
            if new not in before:
                raise SystemExit(f"reverse pattern missing in {relative}: {new[:60]!r}")
            before = before.replace(new, old, 1)
            applied += 1
        before_sha = sha256_crlf(before)
        # 正向重放：before -> after 必须还原当前字节。
        replay = before
        for new, old in replacements:
            if old not in replay:
                raise SystemExit(f"forward pattern missing in {relative}")
            replay = replay.replace(old, new, 1)
        assert sha256_crlf(replay) == after_sha, relative
        expected = BASELINE_SHA[relative]
        entry = {
            "path": relative,
            "before_sha256": before_sha,
            "after_sha256": after_sha,
            "recorded_baseline_sha256": expected,
            "before_matches_recorded_baseline": before_sha == expected,
            "sha_scope": "raw_file_bytes_crlf",
            "reverse_hunks_applied": applied,
            "forward_replay_identical": True,
        }
        report["files"].append(entry)
        diff = difflib.unified_diff(
            before.splitlines(keepends=True),
            current.splitlines(keepends=True),
            fromfile=f"a/{relative}",
            tofile=f"b/{relative}",
            n=3,
        )
        diffs.extend(diff)
    report["all_before_match"] = all(entry["before_matches_recorded_baseline"] for entry in report["files"])
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "fix-sha.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT / "fix-2.diff").write_text("".join(diffs), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

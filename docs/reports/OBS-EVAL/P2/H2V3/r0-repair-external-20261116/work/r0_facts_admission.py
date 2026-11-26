"""R0 第五轮：facts 层准入阶梯（离线 / 合成 / 去身份化；只输出固定码与计数）。

目的
----
C21/C27 的 SAFE 阶梯显示 L1 DB 单元 / L2 被引单元 / L3 可映射角色全满，L4 facts 缺失。
本工具在**产品真实路径**上（``RagIndex.ask``：parse -> retrieve -> answer -> validate），
对每条被引记录行枚举候选 ``(role, value)`` 对，逐条定性“是否进入 ``answer.facts``”，
输出**固定拒绝码计数**：

``fact_built`` / ``role_not_requested`` / ``role_value_missing`` /
``value_rejected_by_validate`` / ``cross_field_conflict`` / ``dedup_dropped`` /
``limit_dropped`` / ``all_fields_representative_only`` / ``undetermined``

数据纪律
--------
- 只用**去身份化合成件**（假门店 / 假物品 / 假字段值），不读任何私有件、不发真实请求；
- 输出只含：固定码、角色枚举（``rag/chunking.py`` 的角色名）、整数计数、布尔；
- 不出任何值 / 表头中文名 / 实体名 / 来源标题；
- 进程内 socket/urllib 出站阻断 + 正对照（两条必然被阻断的尝试）。

红/绿含义
---------
同一行、同一份代码，只改“问题显式请求了哪些字段”：
- 只请求一端 → 另一端 ``role_not_requested``（= 真实两案的红形态：facts 少一项）；
- 显式请求两端 → 两端的候选都 ``fact_built``（= 绿形态）。
因此阶梯本身证明：facts 层是忠实的，唯一能把“可映射角色”挡在 facts 之外的是
``plan.field_roles``（``answer.py`` 的 ``requested_roles`` / ``_requested_field_entries``）。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import socket
import sys
import tempfile
import urllib.request
from collections import Counter
from typing import Any, Iterable, Mapping

# --------------------------------------------------------------------------- #
# 仓库路径
# --------------------------------------------------------------------------- #


def _repo_root() -> pathlib.Path:
    here = pathlib.Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "backend" / "src" / "mktkb").is_dir():
            return parent
    raise SystemExit("repo_root_not_found")


REPO = _repo_root()
if str(REPO / "backend" / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "backend" / "src"))

from mktkb.rag import AtomicUnit, DocumentSpec, RagConfig, RagIndex  # noqa: E402
from mktkb.rag.chunking import field_role  # noqa: E402
from mktkb.rag.query import build_lexicon, parse_query  # noqa: E402
from mktkb.retrieval.tokenize import normalize  # noqa: E402

#: 实体角色：只用于筛选/实体标签，不作为“字段值”候选（它们可以出现在正文但不进 facts）。
ENTITY_ROLES = frozenset(
    {"store", "item", "product", "channel", "price_type", "identifier", "alias", "unit"}
)

CODES = (
    "fact_built",
    "role_not_requested",
    "role_value_missing",
    "value_rejected_by_validate",
    "cross_field_conflict",
    "dedup_dropped",
    "limit_dropped",
    "all_fields_representative_only",
    "undetermined",
)

#: ``FactRejected.code`` 的固定码（``rag/errors.py``）。
CROSS_FIELD_CODE = "CROSS_FIELD"
FACT_REJECT_CODES = frozenset(
    {"FORGED_VALUE", "CROSS_ENTITY", "STALE_SOURCE", "UNSUPPORTED_CLAIM"}
)


class NetGuard:
    """socket 原语层阻断出站；只计数、不连接；正对照必须被阻断。"""

    def __init__(self) -> None:
        self.blocked = 0
        self.positive_control_attempts = 0
        self._orig_connect = None
        self._orig_connect_ex = None
        self._orig_urlopen = None

    def _refuse(self, *_args: Any, **_kwargs: Any) -> Any:
        self.blocked += 1
        raise OSError("netguard_blocked")

    def install(self) -> None:
        self._orig_connect = socket.socket.connect
        self._orig_connect_ex = socket.socket.connect_ex
        self._orig_urlopen = urllib.request.urlopen
        socket.socket.connect = self._refuse  # type: ignore[method-assign]
        socket.socket.connect_ex = self._refuse  # type: ignore[method-assign]
        urllib.request.urlopen = self._refuse  # type: ignore[assignment]
        try:  # httpx 若已导入则一并封死传输层
            import httpx  # noqa: PLC0415

            httpx.HTTPTransport.handle_request = self._refuse  # type: ignore[method-assign]
            httpx.AsyncHTTPTransport.handle_async_request = self._refuse  # type: ignore[method-assign]
        except Exception:  # noqa: BLE001 - 没导入就没有该出站面
            pass

    def positive_control(self) -> None:
        for attempt in (
            lambda: socket.create_connection(("127.0.0.1", 9), timeout=0.05),
            lambda: urllib.request.urlopen("http://127.0.0.1:9/", timeout=0.05),
        ):
            self.positive_control_attempts += 1
            try:
                attempt()
            except OSError:
                continue
            raise RuntimeError("netguard_positive_control_failed")

    def as_dict(self) -> dict[str, Any]:
        return {
            "blocked_attempts": int(self.blocked),
            "positive_control_attempts": int(self.positive_control_attempts),
            "positive_control_blocked": bool(
                self.positive_control_attempts == 2 and self.blocked >= 2
            ),
            "outbound_allowed": 0,
        }


# --------------------------------------------------------------------------- #
# 合成件（去身份化）
# --------------------------------------------------------------------------- #


def _doc(doc_id: str) -> DocumentSpec:
    return DocumentSpec(
        doc_id=doc_id,
        logical_id=doc_id,
        source_path=f"corpus/{doc_id}.xlsx",
        title="合成台账",
        file_kind="xlsx",
        version_id=f"V-{doc_id}",
        version_label="当前",
        sha256=hashlib.sha256(doc_id.encode()).hexdigest(),
        is_current=True,
        state="active",
        business_date="2026-10-28",
    )


def _unit(doc: DocumentSpec, fields: Mapping[str, Any], *, row: int, unit_id: str) -> AtomicUnit:
    return AtomicUnit(
        unit_id=unit_id,
        doc_id=doc.doc_id,
        version_id=doc.version_id,
        kind="table_row",
        ordinal=0,
        unit_key=f"sheet:合成表:row:{row}",
        text="；".join(f"{name}: {value}" for name, value in fields.items()),
        fields=dict(fields),
        sheet="合成表",
        locator={
            "sheet": "合成表",
            "row": row,
            "header_row": 0,
            "cells": [{"header": name, "display": str(value)} for name, value in fields.items()],
        },
        header_row=0,
        row_number=row,
        title="合成台账",
    )


def _new_index(*, page_size: int = 10, rows: Iterable[Mapping[str, Any]] = (), doc_id: str = "D-s") -> RagIndex:
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="r0facts-"))
    index = RagIndex(
        tmp / "rag.sqlite3",
        config=RagConfig(
            provider_mode="offline",
            data_dir=tmp,
            business_date="2026-10-28",
            chunk_max_chars=420,
            chunk_max_units=3,
            chunk_overlap_units=1,
            top_k=20,
            page_size=page_size,
            vector_candidate_limit=50,
            rerank_top_n=20,
        ),
    )
    doc = _doc(doc_id)
    units = [
        _unit(doc, fields, row=7 + position, unit_id=f"{doc_id}-row{7 + position}")
        for position, fields in enumerate(rows)
    ]
    if units:
        index.add_document(doc, units, embed=False)
    return index


# --------------------------------------------------------------------------- #
# 阶梯定性
# --------------------------------------------------------------------------- #


def _plan_roles(plan: Any) -> tuple[str, ...]:
    roles = tuple(getattr(plan, "field_roles", ()) or ())
    if roles:
        return roles
    return (plan.field_role,) if plan.field_role else ()


def _cited_record_chunks(index: RagIndex, answer: Any) -> list[Any]:
    chunks: list[Any] = []
    seen: set[str] = set()
    for citation in answer.citations:
        source_id = str(getattr(citation, "source_id", "") or "")
        if not source_id or source_id in seen:
            continue
        seen.add(source_id)
        chunk = index.get_chunk(source_id, require_visible=True)
        if chunk is not None and chunk.kind == "record":
            chunks.append(chunk)
    return chunks


def ladder(index: RagIndex, question: str, *, conversation_id: str) -> dict[str, Any]:
    """跑一次产品路径，并把被引行的字段值候选逐条定性。"""
    previous = index.load_state("u", conversation_id)
    plan = parse_query(
        question,
        previous=previous,
        lexicon=build_lexicon(index.lexicon_data()),
        business_date=index.config.business_date,
        page_size=index.config.page_size,
    )
    answer = index.ask(question, user_id="u", conversation_id=conversation_id)
    requested = _plan_roles(plan)
    all_fields = not plan.field_role
    facts = {(fact.field_role, fact.value) for fact in answer.facts}
    answer_kind = str(answer.kind)
    answer_reason = str(answer.reason or "none")
    codes: Counter[str] = Counter({code: 0 for code in CODES})
    rendered_but_not_fact = 0
    entity_candidates = 0
    row_roles: set[str] = set()
    for chunk in _cited_record_chunks(index, answer):
        role_values = dict(chunk.role_values or {})
        fields = dict(chunk.fields or {})
        # 同一 (role, 规范化值) 在该行出现几列（用于 dedup_dropped 计数）。
        occurrences: Counter[tuple[str, str]] = Counter()
        for name, raw in fields.items():
            role = field_role(name)
            text = "" if raw is None else str(raw).strip()
            if role and text:
                occurrences[(role, normalize(text))] += 1
        for role, values in role_values.items():
            row_roles.add(str(role))
            for value in values:
                text = str(value)
                if str(role) in ENTITY_ROLES:
                    entity_candidates += 1
                    continue
                pair = (str(role), text)
                if all_fields:
                    code = "fact_built" if pair in facts else "all_fields_representative_only"
                elif str(role) not in requested:
                    code = "role_not_requested"
                elif pair in facts:
                    code = "fact_built"
                elif answer_kind in ("no_answer", "not_found", "refusal"):
                    code = (
                        "cross_field_conflict"
                        if answer_reason == CROSS_FIELD_CODE
                        else (
                            "value_rejected_by_validate"
                            if answer_reason in FACT_REJECT_CODES
                            else "undetermined"
                        )
                    )
                else:
                    code = "undetermined"
                codes[code] += 1
                if code == "fact_built":
                    extra = occurrences[(str(role), normalize(text))] - 1
                    if extra > 0:
                        codes["dedup_dropped"] += extra
                if (
                    answer_kind == "answer"
                    and not all_fields
                    and code not in ("fact_built", "role_not_requested")
                    and normalize(text) in normalize(answer.text)
                ):
                    rendered_but_not_fact += 1
    # 计划请求了但该行没有该角色：role_value_missing。
    for role in requested:
        if role in ENTITY_ROLES:
            continue
        if not any(role in (chunk.role_values or {}) for chunk in _cited_record_chunks(index, answer)):
            codes["role_value_missing"] += 1
    return {
        "answer_kind": answer_kind,
        "answer_reason": answer_reason,
        "plan_roles": list(requested),
        "all_fields": bool(all_fields),
        "row_roles": sorted(row_roles),
        "fact_roles": sorted({fact.field_role for fact in answer.facts}),
        "fact_count": len(answer.facts),
        "cited_record_rows": len(_cited_record_chunks(index, answer)),
        "entity_role_candidates": int(entity_candidates),
        "rendered_but_not_fact": int(rendered_but_not_fact),
        "codes": {code: int(codes[code]) for code in CODES},
        "code_total": int(sum(codes.values())),
    }


# --------------------------------------------------------------------------- #
# 形状矩阵
# --------------------------------------------------------------------------- #

#: C21 形：单行 + 两个日期列 + 位置/别名等实体旁列（角色清单取自真实 cited_roles）。
C21_ROW = {
    "标识": "L01",
    "门店": "甲店",
    "物品": "立牌",
    "别名": "牌牌",
    "位置": "甲区一号位",
    "生效日期": "2026-01-05",
    "失效日期": "2026-09-30",
}
#: C27 形：门店单行 + 联系人/电话/地址/状态 + 生命周期（角色清单取自真实 cited_roles）。
C27_ROW = {
    "门店": "甲店",
    "联系人": "张经理",
    "联系电话": "010-1000-1001",
    "门店地址": "合成区长街 1 号",
    "合作状态": "合作中",
    "生效日期": "2026-01-05",
    "失效日期": "2026-09-30",
}
#: 同角色多列（参考供价/零售价 都归 price）。
PRICE_ROW = {"标识": "L02", "门店": "甲店", "物品": "立牌", "参考供价": "5", "零售价": "7"}
#: 同角色同值两列（dedup）。
DUP_ROW = {"标识": "L03", "门店": "甲店", "物品": "立牌", "参考供价": "5", "零售价": "5"}
#: 缺列（请求的失效日期不存在）。
NODATE_ROW = {"标识": "L04", "门店": "甲店", "物品": "立牌", "位置": "甲区一号位"}


def shapes() -> list[dict[str, Any]]:
    return [
        {
            "shape": "C21_red_single_end",
            "note": "C21 形；只请求一端 ⇒ 另一端 role_not_requested（= 真实 L4 缺项形态）",
            "rows": [C21_ROW],
            "question": "列出甲店立牌的失效日期",
        },
        {
            "shape": "C21_green_both_ends",
            "note": "同一行；显式请求两端 ⇒ 两个日期都进 facts（代码未改）",
            "rows": [C21_ROW],
            "question": "列出甲店立牌的生效日期和失效日期",
        },
        {
            "shape": "C27_red_single_phone",
            "note": "C27 形；只请求电话 ⇒ 地址 role_not_requested",
            "rows": [C27_ROW],
            "question": "列出甲店的联系电话",
        },
        {
            "shape": "C27_green_both_contact",
            "note": "同一行；显式请求地址+电话 ⇒ 两条都进 facts",
            "rows": [C27_ROW],
            "question": "列出甲店的门店地址和联系电话",
        },
        {
            "shape": "C27_bundle_word",
            "note": "概念词（联系方式）只映射到 phone；地址/联系人仍 role_not_requested",
            "rows": [C27_ROW],
            "question": "列出甲店的联系方式",
        },
        {
            "shape": "C27_two_phone_columns",
            "note": "C27 facts=2 的另一种同形：同一请求角色由两列承载 ⇒ 2 条 facts、5 条未请求",
            "rows": [
                {
                    "门店": "甲店",
                    "联系人": "张经理",
                    "联系电话": "010-1000-1001",
                    "联系方式": "010-1000-1002",
                    "门店地址": "合成区长街 1 号",
                    "合作状态": "合作中",
                    "生效日期": "2026-01-05",
                    "失效日期": "2026-09-30",
                }
            ],
            "question": "列出甲店的联系电话",
        },
        {
            "shape": "C27_two_roles_fact2",
            "note": "C27 真实 facts=2 的同形：请求 phone+status ⇒ 2 条 facts、4 条 role_not_requested",
            "rows": [C27_ROW],
            "question": "列出甲店的合作状态和联系电话",
        },
        {
            "shape": "H_c21_window_word",
            "note": "假设形：复合词（有效期）+ 一端字段词 ⇒ 只请求一端；与真实 C21 facts=1 同形",
            "rows": [C21_ROW],
            "question": "列出甲店立牌的有效期和失效日期",
        },
        {
            "shape": "H_c21_deadline_word",
            "note": "排除形：未登记词（到期）只落到泛化 date ⇒ 该行无 date 角色，退化成无记录",
            "rows": [C21_ROW],
            "question": "列出甲店立牌什么时候到期",
        },
        {
            "shape": "C21_all_fields",
            "note": "无字段请求 ⇒ all_fields 只造 1 条代表事实；其余角色值只渲染不进 facts",
            "rows": [C21_ROW],
            "question": "列出甲店立牌的全部信息",
        },
        {
            "shape": "same_role_two_columns",
            "note": "同角色两列 ⇒ 两列都进 facts（第一/二轮多列渲染修复的形态）",
            "rows": [PRICE_ROW],
            "question": "列出甲店立牌的价格",
        },
        {
            "shape": "same_role_same_value",
            "note": "同角色同值两列 ⇒ 1 条 fact + 1 条 dedup_dropped",
            "rows": [DUP_ROW],
            "question": "列出甲店立牌的价格",
        },
        {
            "shape": "requested_role_absent",
            "note": "请求了该行没有的角色 ⇒ role_value_missing（fail-closed，无 facts）",
            "rows": [NODATE_ROW],
            "question": "列出甲店立牌的失效日期",
        },
    ]


def _install_first_role_only_patch() -> Any:
    """RED 模式：在内存里把 ``_match_fields`` 收窄成“只保留首个角色”。

    这就是真实两案的假设计划形态（少一项被请求角色）；工作树不动、不写文件。
    返回一个 restore 回调。
    """
    import mktkb.rag.query as query_module  # noqa: PLC0415

    original = query_module._match_fields  # noqa: SLF001 - 只为复现计划层少一项

    def first_role_only(question: str) -> tuple[str, ...]:
        return tuple(original(question))[:1]

    query_module._match_fields = first_role_only  # type: ignore[assignment]
    return lambda: setattr(query_module, "_match_fields", original)


def run(*, red: bool = False) -> dict[str, Any]:
    guard = NetGuard()
    guard.install()
    restore = _install_first_role_only_patch() if red else None
    results: list[dict[str, Any]] = []
    try:
        for spec in shapes():
            index = _new_index(page_size=int(spec.get("page_size", 10)), rows=spec["rows"])
            try:
                entry = ladder(index, str(spec["question"]), conversation_id=str(spec["shape"]))
            finally:
                index.close()
            entry["shape"] = spec["shape"]
            entry["note"] = spec["note"]
            results.append(entry)
    finally:
        if restore is not None:
            restore()
    guard.positive_control()
    totals: Counter[str] = Counter()
    for entry in results:
        for code, count in entry["codes"].items():
            totals[code] += int(count)
    aggregate = {
        "mode": "red_plan_first_role_only" if red else "green_current_plan",
        "totals": {code: int(totals[code]) for code in CODES},
        "rendered_but_not_fact": int(sum(entry["rendered_but_not_fact"] for entry in results)),
        "shapes": len(results),
        "limit_dropped_note": "facts 只为被引行构造；分页/歧义的行在引用之前就被丢弃，不进本阶梯（真实两案被引单元各 1 条）",
        "netguard": guard.as_dict(),
    }
    return {"ok": True, "aggregate": aggregate, "results": results}


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument(
        "--out",
        default=str(REPO / "docs/reports/OBS-EVAL/P2/H2V3/r0-repair-external-20261116/work/out/facts-admission/ladder.json"),
    )
    parser.add_argument(
        "--red",
        action="store_true",
        help="RED 模式：内存里把 _match_fields 收窄成只保留首个角色（复现计划少一项）",
    )
    args = parser.parse_args(list(argv))
    payload = run(red=bool(args.red))
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload["aggregate"], ensure_ascii=False, sort_keys=True))
    for entry in payload["results"]:
        print(
            "%-26s plan=%-42s facts=%d codes=%s"
            % (
                entry["shape"],
                ",".join(entry["plan_roles"]) or "none",
                entry["fact_count"],
                json.dumps(
                    {code: count for code, count in entry["codes"].items() if count},
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

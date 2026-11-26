"""把 conversations/service.py 中的 v3-fix-1 A/B 追加块反向删除，检验是否逐字节回到改前基线。

只读当前文件、只写临时文件；不改工作树。目标基线 SHA-256：
fd04136b6b450b45a98045bcb9b16c21531d35070e73529263a1507690dae75a
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[7]
TARGET = REPO / "backend/src/mktkb/conversations/service.py"
OUT = Path(__file__).resolve().parent / "A-service-baseline-reconstruct.json"
EXPECTED = "fd04136b6b450b45a98045bcb9b16c21531d35070e73529263a1507690dae75a"

text = TARGET.read_text(encoding="utf-8")
replacements = [
    (
        '''def _legacy_evidence_as_of(qa, plan) -> str | None:
    """legacy 证据面按业务日过滤时使用的日期（v3-fix-1/B）。

    取值只来自产品本轮已解析的计划（``QueryPlan.as_of``：题面显式日期优先，否则是
    Settings 级 ``rag_business_date``）；没有 RAG 装配或明确问“未来/调整后”时返回
    ``None``，保持原行为、不臆造日期。
    """
    if qa is None or plan is None:
        return None
    if bool(getattr(plan, "include_future", False)):
        return None
    value = getattr(plan, "as_of", None)
    return str(value) if value else None


''',
        "",
    ),
    (
        """    *,
    candidate_ids: set[str] | None = None,
    as_of: str | None = None,
) -> EvidenceSet:""",
        """    *,
    candidate_ids: set[str] | None = None,
) -> EvidenceSet:""",
    ),
    (
        """    分组/歧义/冲突/可见性仍由既有检索与提交事务复核。正文型问题不做该限制。
    ``as_of`` 是业务日（仅时间维度过滤：过期/未生效的记录行不进入证据面）。
    \"\"\"""",
        """    分组/歧义/冲突/可见性仍由既有检索与提交事务复核。正文型问题不做该限制。
    \"\"\"""",
    ),
    (
        """        return retrieve(
            db,
            intent,
            revision=revision,
            limit=limit,
            candidate_ids=candidate_ids,
            as_of=as_of,
        )""",
        """        return retrieve(db, intent, revision=revision, limit=limit, candidate_ids=candidate_ids)""",
    ),
    (
        """def _same_entity_evidence(
    db_factory,
    plan: intent_module.IntentPlan,
    units: Iterable[SourceUnit],
    revision: int,
    *,
    as_of: str | None = None,
) -> EvidenceSet | None:""",
        """def _same_entity_evidence(
    db_factory, plan: intent_module.IntentPlan, units: Iterable[SourceUnit], revision: int
) -> EvidenceSet | None:""",
    ),
    (
        """        return _retrieve(
            db_factory, probe, revision, limit=20, candidate_ids=None, as_of=as_of
        )""",
        """        return _retrieve(db_factory, probe, revision, limit=20, candidate_ids=None)""",
    ),
    (
        """def _document_overshoot_evidence(
    db_factory,
    evidence: EvidenceSet,
    intent: QueryIntent,
    revision: int,
    *,
    as_of: str | None = None,
) -> EvidenceSet:""",
        """def _document_overshoot_evidence(
    db_factory,
    evidence: EvidenceSet,
    intent: QueryIntent,
    revision: int,
) -> EvidenceSet:""",
    ),
    (
        """    不改变检索/排序语义。返回值仍标记 ``truncated``，由后续既有正文排序选取证据。
    ``as_of`` 与主证据同一业务日口径（v3-fix-1/B），避免回退路径把过期行带回来。
    \"\"\"""",
        """    不改变检索/排序语义。返回值仍标记 ``truncated``，由后续既有正文排序选取证据。
    \"\"\"""",
    ),
    (
        "        extra = _retrieve(db_factory, narrowed, revision, limit=100, as_of=as_of)",
        "        extra = _retrieve(db_factory, narrowed, revision, limit=100)",
    ),
    (
        """    if plan.reason == "MULTI_TARGET_ENUMERATE":
        # v3-fix-1/A：单轮明确点名多个目标（例如两个门店/两个物品）由内核按枚举作答；
        # 这类轮次可能没有任何单值实体过滤（多门店时 store 槽位按设计留空），
        # 不能因为“filters 为空”退回 legacy 的“多个实体→澄清”。
        return True
""",
        "",
    ),
    (
        """    # v3-fix-1/B：legacy 路径的证据面按业务日过滤过期/未生效的记录行（只做时间维度过滤，
    # 不改变召回与排序）。日期只取产品本轮已解析的计划，不读数据集或报告字段。
    legacy_as_of = _legacy_evidence_as_of(qa, rag_plan)

""",
        "",
    ),
    (
        """    def _evidence(intent: QueryIntent, limit: int = 20) -> EvidenceSet:
        with trace_attrs.span("retrieve", limit=limit):
            return _retrieve(
                db_factory,
                intent,
                revision,
                limit=limit,
                candidate_ids=rag_candidates,
                as_of=legacy_as_of,
            )""",
        """    def _evidence(intent: QueryIntent, limit: int = 20) -> EvidenceSet:
        with trace_attrs.span("retrieve", limit=limit):
            return _retrieve(db_factory, intent, revision, limit=limit, candidate_ids=rag_candidates)""",
    ),
    (
        """                evidence = _document_overshoot_evidence(
                    db_factory, evidence, plan.intent, revision, as_of=legacy_as_of
                )""",
        """                evidence = _document_overshoot_evidence(db_factory, evidence, plan.intent, revision)""",
    ),
    (
        """            widened = _same_entity_evidence(
                db_factory, plan, evidence.units, revision, as_of=legacy_as_of
            )""",
        """            widened = _same_entity_evidence(db_factory, plan, evidence.units, revision)""",
    ),
    (
        """                        evidence = _document_overshoot_evidence(
                            db_factory, evidence, expanded, revision, as_of=legacy_as_of
                        )""",
        """                        evidence = _document_overshoot_evidence(
                            db_factory, evidence, expanded, revision
                        )""",
    ),
]

reconstructed = text
applied = []
for old, new in replacements:
    count = reconstructed.count(old)
    applied.append({"count": count, "old_head": old.splitlines()[0][:80]})
    if count != 1:
        raise SystemExit(f"replacement count {count} != 1 for {old[:80]!r}")
    reconstructed = reconstructed.replace(old, new)

raw = reconstructed.encode("utf-8")
crlf = reconstructed.replace("\n", "\r\n").encode("utf-8")
sha = hashlib.sha256(crlf).hexdigest()
OUT.write_text(
    json.dumps(
        {
            "schema_version": "v3-fix1-independent-A-service-baseline-reconstruct/v0.1",
            "target": "backend/src/mktkb/conversations/service.py",
            "current_sha256": hashlib.sha256(TARGET.read_bytes()).hexdigest(),
            "expected_baseline_sha256": EXPECTED,
            "reconstructed_sha256": sha,
            "reconstructed_sha256_lf": hashlib.sha256(raw).hexdigest(),
            "reconstructed_bytes": len(crlf),
            "matches_expected": sha == EXPECTED,
            "applied": applied,
        },
        ensure_ascii=False,
        indent=2,
    )
    + "\n",
    encoding="utf-8",
)
(Path(__file__).resolve().parent / "_reconstructed_service.py").write_text(
    reconstructed, encoding="utf-8", newline="\r\n"
)
print(json.dumps({"reconstructed": sha, "expected": EXPECTED, "match": sha == EXPECTED,
                  "bytes": len(crlf)}, indent=1))

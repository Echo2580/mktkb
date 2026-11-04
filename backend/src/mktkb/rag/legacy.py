"""旧方案对照基线：复用现有 T05/T06 的意图解析与检索，只在隔离 SQLite 中构建。

对照口径必须如实：
- 旧方案 = 现有 `parse_question` + `retrieve`（精确字段 + FTS，无向量、无重排）；
- 回答由同一个离线抽取器生成，避免把“旧方案没有模型答案”误写成产品真实效果；
- 旧库只放当前有效资料，不打开 var 正式库，不修改产品代码。
"""

from __future__ import annotations

import hashlib
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from ..conversations import intent as legacy_intent
from ..db import Database, run_migrations
from ..documents.models import Document, DocumentVersion, KnowledgeState, SourceUnit
from ..retrieval.index import HEADER_ROLES, prepare_version_index, resolve_requested_role
from ..retrieval.service import retrieve
from ..retrieval.tokenize import cut, normalize
from .types import AtomicUnit, DocumentSpec, EvidenceItem


@dataclass
class LegacyAnswer:
    kind: str
    question: str
    text: str
    citations: list[str]
    evidence: list[dict[str, Any]]
    reason: str | None
    diagnostics: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "question": self.question,
            "text": self.text,
            "citations": list(self.citations),
            "evidence": list(self.evidence),
            "reason": self.reason,
            "diagnostics": dict(self.diagnostics),
        }


class LegacyIndex:
    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        if self.db_path.exists():
            self.db_path.unlink()
        self.url = f"sqlite:///{self.db_path.as_posix()}"
        run_migrations(self.url)
        self.database = Database(self.url, busy_timeout_ms=5000, enable_wal=True)
        self.revision = 0
        self._doc_versions: dict[str, uuid.UUID] = {}
        self._doc_code_by_version: dict[str, str] = {}

    def close(self) -> None:
        self.database.dispose()

    def build(self, documents: Iterable[tuple[DocumentSpec, Sequence[AtomicUnit]]]) -> dict[str, Any]:
        started = time.monotonic()
        items = list(documents)
        revision = 1
        with self.database.session_scope() as session:
            session.query(KnowledgeState).delete()
            session.add(
                KnowledgeState(
                    id=1,
                    revision=revision,
                    active_document_count=len(items),
                    active_excel_row_count=sum(
                        1 for _doc, units in items for unit in units if unit.kind == "table_row"
                    ),
                )
            )
            seen_sha: set[str] = set()
            for doc, units in items:
                sha = doc.sha256
                if sha in seen_sha:
                    sha = hashlib.sha256(f"{sha}|{doc.doc_id}".encode("utf-8")).hexdigest()
                seen_sha.add(sha)
                document = Document(
                    id=uuid.uuid4(),
                    name=f"{doc.doc_id}｜{doc.title}",
                    name_key=None,
                    file_type=doc.file_kind,
                    latest_version_number=1,
                    deleted=False,
                    last_published_at=datetime.now(timezone.utc),
                )
                session.add(document)
                session.flush()
                version = DocumentVersion(
                    id=uuid.uuid4(),
                    document_id=document.id,
                    number=1,
                    state="published",
                    sha256=sha,
                    size_bytes=1,
                    stored_path=doc.source_path,
                    published_at=datetime.now(timezone.utc),
                )
                session.add(version)
                session.flush()
                document.active_version_id = version.id
                for unit in units:
                    session.add(
                        SourceUnit(
                            id=uuid.uuid5(uuid.NAMESPACE_URL, f"legacy|{doc.doc_id}|{unit.unit_key}"),
                            document_id=document.id,
                            version_id=version.id,
                            kind=unit.kind,
                            ordinal=unit.ordinal,
                            unit_key=unit.unit_key[:200],
                            sheet=unit.sheet,
                            locator=dict(unit.locator or {}),
                            text=unit.text,
                            fields=dict(unit.fields or {}),
                            warnings=None,
                        )
                    )
                session.flush()
                # prepare_version_index 会在内部 rollback 后 BEGIN IMMEDIATE；先提交已写入的
                # 文档/版本/来源，避免它的准备事务把未提交行回滚掉。
                session.commit()
                status = prepare_version_index(session, version.id)
                if not status.ready:
                    raise RuntimeError(f"legacy index not ready: {doc.doc_id} {status.reason}")
                self._doc_versions[doc.doc_id] = version.id
                self._doc_code_by_version[str(version.id)] = doc.doc_id
        self.revision = revision
        return {
            "documents": len(items),
            "units": sum(len(units) for _doc, units in items),
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "revision": revision,
        }

    def ask(self, question: str, *, context_entities: Mapping[str, str] | None = None) -> LegacyAnswer:
        started = time.monotonic()
        with self.database.session() as session:
            lexicon = legacy_intent.load_lexicon(session)
            plan = legacy_intent.parse_question(
                question, lexicon=lexicon, context_entities=dict(context_entities or {})
            )
            diagnostics: dict[str, Any] = {
                "mode": plan.mode,
                "requested_fields": list(plan.requested_fields),
                "missing_fields": list(plan.missing_fields),
                "entities": dict(plan.entities),
                "clarification": plan.clarification,
            }
            if plan.clarification:
                return LegacyAnswer(
                    kind="clarification",
                    question=question,
                    text=plan.clarification,
                    citations=[],
                    evidence=[],
                    reason="CLARIFICATION_REQUIRED",
                    diagnostics=diagnostics,
                )
            if plan.intent is None:
                return LegacyAnswer(
                    kind="no_answer",
                    question=question,
                    text="无法从问题中形成检索条件。",
                    citations=[],
                    evidence=[],
                    reason="NO_INTENT",
                    diagnostics=diagnostics,
                )
            try:
                evidence = retrieve(session, plan.intent, revision=self.revision, limit=20)
            except Exception as exc:
                return LegacyAnswer(
                    kind="error",
                    question=question,
                    text=f"旧方案检索失败：{type(exc).__name__}",
                    citations=[],
                    evidence=[],
                    reason="LEGACY_RETRIEVAL_ERROR",
                    diagnostics={**diagnostics, "error": type(exc).__name__},
                )
            for unit in evidence.units:
                setattr(unit, "_legacy_doc_code", self._doc_code_by_version.get(str(unit.version_id), ""))
            diagnostics.update(
                {
                    "kind": evidence.kind,
                    "total_candidates": evidence.total_candidates,
                    "truncated": evidence.truncated,
                    "recall": {"legacy": len(evidence.units)},
                }
            )
            if not evidence.units:
                return LegacyAnswer(
                    kind="no_answer",
                    question=question,
                    text="旧方案没有召回有效资料。",
                    citations=[],
                    evidence=[],
                    reason="NO_EVIDENCE",
                    diagnostics=diagnostics,
                )
            if plan.mode == "record" and plan.requested_fields:
                values: list[tuple[str, str]] = []
                for label in plan.requested_fields:
                    role = resolve_requested_role(label)
                    value = None
                    synonyms = HEADER_ROLES.get(role or "", ())
                    for unit in evidence.units:
                        for name, raw in (unit.fields or {}).items():
                            if raw in (None, ""):
                                continue
                            if name == label or name in synonyms or str(name).strip() == label:
                                value = str(raw)
                                break
                        if value:
                            break
                    if value:
                        values.append((label, value))
                if values:
                    unit = evidence.units[0]
                    label = _legacy_label(unit)
                    text = "根据资料，" + label + "的" + "、".join(f"{name}是{value}" for name, value in values) + "。"
                    return LegacyAnswer(
                        kind="answer",
                        question=question,
                        text=text,
                        citations=[_legacy_citation(unit)],
                        evidence=[_legacy_evidence(unit)],
                        reason=None,
                        diagnostics=diagnostics,
                    )
            # 文档/价格/语义问题：旧方案只给召回证据，使用与新版相同的抽取式句子选择。
            sentence = _best_sentence(question, evidence.units)
            if not sentence:
                return LegacyAnswer(
                    kind="no_answer",
                    question=question,
                    text="旧方案召回的片段与问题没有足够重合。",
                    citations=[],
                    evidence=[_legacy_evidence(unit) for unit in evidence.units[:5]],
                    reason="NO_SUPPORTING_SENTENCE",
                    diagnostics=diagnostics,
                )
            return LegacyAnswer(
                kind="answer",
                question=question,
                text=f"根据资料，{sentence}",
                citations=[_legacy_citation(evidence.units[0])],
                evidence=[_legacy_evidence(unit) for unit in evidence.units[:5]],
                reason=None,
                diagnostics={**diagnostics, "answer_source": "legacy_retrieval_extractive"},
            )


def _legacy_label(unit: Any) -> str:
    fields = dict(unit.fields or {})
    store = fields.get("门店") or fields.get("店家") or ""
    item = fields.get("物品") or fields.get("物料") or ""
    if store and item:
        return f"{store}的{item}"
    return str(store or item or getattr(unit, "unit_key", ""))


def _legacy_doc_code(unit: Any) -> str:
    code = str(getattr(unit, "_legacy_doc_code", "") or "")
    if code:
        return code
    document = getattr(unit, "document", None)
    name = str(getattr(document, "name", "") or "")
    return name.split("｜", 1)[0] if "｜" in name else ""


def _legacy_citation(unit: Any) -> str:
    locator = dict(unit.locator or {})
    sheet = locator.get("sheet")
    row = locator.get("row")
    if sheet and row:
        where = f"工作表 {sheet} 第 {row} 行"
    elif row:
        where = f"第 {row} 行"
    else:
        where = f"第 {locator.get('page', locator.get('paragraph', '?'))} 页/段"
    code = _legacy_doc_code(unit)
    return f"旧方案来源：{code or getattr(unit, 'unit_key', '')}（{where}）"


def _legacy_evidence(unit: Any) -> dict[str, Any]:
    return {
        "source_id": str(getattr(unit, "id", "")),
        "doc_id": _legacy_doc_code(unit),
        "unit_key": getattr(unit, "unit_key", ""),
        "text": getattr(unit, "text", ""),
        "fields": dict(getattr(unit, "fields", None) or {}),
        "locator": dict(getattr(unit, "locator", None) or {}),
    }


def _best_sentence(question: str, units: Sequence[Any]) -> str | None:
    terms = {token for token in cut(question) if len(token) >= 2}
    scored: list[tuple[int, int, str]] = []
    for index, unit in enumerate(units):
        for sentence in str(getattr(unit, "text", "") or "").replace("\n", "。").split("。"):
            cleaned = sentence.strip()
            if len(cleaned) < 8:
                continue
            score = sum(len(token) for token in terms if token in cleaned)
            if score <= 0:
                continue
            if any(char.isdigit() for char in cleaned):
                score += 2
            scored.append((score, -index, cleaned))
    if not scored:
        return None
    scored.sort(key=lambda item: (-item[0], item[1], -len(item[2])))
    return scored[0][2]

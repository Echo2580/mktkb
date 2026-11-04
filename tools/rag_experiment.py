"""LOCAL-R1/S1 隔离 RAG 实验入口（offline/live）。

用法：
  .\\.venv\\Scripts\\python.exe -B tools\\rag_experiment.py offline
  .\\.venv\\Scripts\\python.exe -B tools\\rag_experiment.py offline --no-old
  .\\.venv\\Scripts\\python.exe -B tools\\rag_experiment.py live --ledger ... --budget ... --questions ... --out ...

offline 只用确定性替身与离线重排，0 次真实 embedding/rerank/DeepSeek/OCR。
live 必须先存在经理写入的 GO 文件，且显式提供共享账本；代码不会在离线模式静默切真实。
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import math
import re
import sys
import time
import tracemalloc
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
GO_PATH = ROOT / "docs" / "evidence" / "LOCAL-R1-20261101" / "S1-LIVE-GO.md"
if str(ROOT / "backend" / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "backend" / "src"))

from mktkb.ingestion.parsers import ParseError, ParseServices, parse_document  # noqa: E402
from mktkb.rag import (  # noqa: E402
    AtomicUnit,
    BudgetLedger,
    DocumentSpec,
    RagConfig,
    RagIndex,
    adapt_parsed_unit,
)
from mktkb.rag.config import safe_config_summary  # noqa: E402
from mktkb.rag.chunking import build_chunks  # noqa: E402
from mktkb.rag.legacy import LegacyIndex  # noqa: E402
from mktkb.rag.providers import FakeEmbeddingProvider, LexicalReranker  # noqa: E402

_FIXED_LEDGER = ROOT / "docs" / "evidence" / "LOCAL-R1-20261101" / "budget" / "live-ledger.jsonl"
_FIXED_BUDGET = ROOT / "docs" / "evidence" / "LOCAL-R1-20261101" / "budget" / "budget.json"
_SUBSET_POLICY_PATH = (
    ROOT / "docs" / "evidence" / "LOCAL-R1-20261101" / "S1-DEV" / "R2" / "subset-policy.json"
)
try:
    _subset_policy = json.loads(_SUBSET_POLICY_PATH.read_text(encoding="utf-8"))
except (OSError, ValueError):
    _subset_policy = {}
VAR_LOGICAL = dict(_subset_policy.get("version_aliases") or {})
VAR_LABELS = dict(_subset_policy.get("version_labels") or {})
INACTIVE_CODES = set(_subset_policy.get("inactive_codes") or ())
SKIP_GROUPS = set(_subset_policy.get("skip_groups") or ())
SKIP_CODES = set(_subset_policy.get("skip_codes") or ())
# 不在 harness 里内置语料优先级；选择顺序只按 manifest 的 code，避免用专名影响召回对照。



def _normalize(text: str) -> str:
    from mktkb.retrieval.tokenize import normalize

    return normalize(str(text))


def _value_present(value: str, text: str) -> bool:
    if not value:
        return True
    haystack = _normalize(text)
    needle = _normalize(value)
    if not needle:
        return True
    if re.fullmatch(r"\d+(?:\.\d+)?", needle):
        return re.search(rf"(?<![\d.]){re.escape(needle)}(?![\d.])", haystack) is not None
    return needle in haystack


def _doc_title(path: str) -> str:
    stem = Path(path).stem
    return stem.split("_", 1)[1] if "_" in stem and stem.split("_", 1)[1] else stem


def _effective_from(units: Iterable[Any]) -> str | None:
    text = "\n".join(str(getattr(unit, "text", "")) for unit in list(units)[:40])
    match = re.search(r"自\s*(20\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日\s*起", text)
    if match:
        year, month, day = (int(part) for part in match.groups())
        return f"{year:04d}-{month:02d}-{day:02d}"
    match = re.search(r"生效\s*[:：]\s*(20\d{2})\s*[-年/]\s*(\d{1,2})\s*[-月/]\s*(\d{1,2})", text)
    if match:
        year, month, day = (int(part) for part in match.groups())
        return f"{year:04d}-{month:02d}-{day:02d}"
    return None


def load_corpus(
    corpus: Path,
    *,
    max_docs: int | None = None,
    only_codes: set[str] | None = None,
) -> tuple[list[tuple[DocumentSpec, list[Any]]], list[dict[str, Any]]]:
    manifest = json.loads((corpus / "manifest.json").read_text(encoding="utf-8"))
    business_date = str(manifest.get("business_date") or "2026-10-28")
    all_items = list(manifest.get("files", []))
    selected: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for item in all_items:
        code = str(item.get("code") or "")
        group = str(item.get("group") or "")
        suffix = Path(str(item.get("path", ""))).suffix.lower()
        if group in SKIP_GROUPS:
            excluded.append({"code": code, "path": item.get("path"), "reason": f"subset_group:{group}"})
        elif code in SKIP_CODES:
            excluded.append({"code": code, "path": item.get("path"), "reason": "sensitive_sample_excluded"})
        elif suffix not in (".xlsx", ".docx", ".pdf"):
            excluded.append({"code": code, "path": item.get("path"), "reason": f"unsupported_suffix:{suffix}"})
        else:
            selected.append(item)
    selected.sort(key=lambda item: str(item.get("code") or ""))
    if only_codes is not None:
        excluded.extend(
            {"code": str(item.get("code") or ""), "path": item.get("path"), "reason": "not_selected_by_doc_filter"}
            for item in selected if str(item.get("code") or "") not in only_codes
        )
        selected = [item for item in selected if str(item.get("code") or "") in only_codes]
    if max_docs is not None:
        excluded.extend(
            {"code": str(item.get("code") or ""), "path": item.get("path"), "reason": "max_docs_cut"}
            for item in selected[max_docs:]
        )
        selected = selected[:max_docs]
    files = selected
    documents: list[tuple[DocumentSpec, list[Any]]] = []
    skipped: list[dict[str, Any]] = list(excluded)
    for item in files:
        code = str(item["code"])
        rel = str(item["path"])
        path = corpus / rel
        kind = path.suffix.lower().lstrip(".")
        try:
            services = ParseServices()
            parsed = list(parse_document(path, kind, services))
        except (ParseError, Exception) as exc:  # 解析失败不启动 OCR，也不冒充成功
            skipped.append({"code": code, "path": rel, "reason": f"{type(exc).__name__}: {getattr(exc, 'code', '')}"})
            continue
        failed_pages = list((services.report or {}).get("failed_pages") or [])
        if not parsed:
            skipped.append({"code": code, "path": rel, "reason": "no_parsed_units"})
            continue
        if failed_pages:
            skipped.append({"code": code, "path": rel, "reason": f"failed_pages={len(failed_pages)}"})
            continue
        logical = VAR_LOGICAL.get(code, code)
        inactive = code in INACTIVE_CODES
        spec = DocumentSpec(
            doc_id=code,
            logical_id=logical,
            source_path=rel,
            title=_doc_title(rel),
            file_kind=kind,
            version_id=f"{code}-v1",
            version_label=VAR_LABELS.get(code, "当前"),
            sha256=str(item.get("sha256") or hashlib.sha256(path.read_bytes()).hexdigest()),
            state="active" if not inactive else "superseded",
            is_current=not inactive,
            effective_from=_effective_from(parsed),
            business_date=business_date,
            metadata={"group": item.get("group"), "purpose": item.get("purpose")},
        )
        units = [
            adapt_parsed_unit(unit, doc=spec, unit_id=f"{code}-{ordinal}", ordinal=ordinal)
            for ordinal, unit in enumerate(parsed)
        ]
        documents.append((spec, units))
    return documents, skipped


def build_new_index(
    documents: list[tuple[DocumentSpec, list[Any]]],
    *,
    db_path: Path,
    config: RagConfig,
    budget: BudgetLedger | None = None,
) -> tuple[RagIndex, dict[str, Any]]:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    index = RagIndex(db_path, config=config, budget=budget)
    started = time.monotonic()
    results: list[dict[str, Any]] = []
    for spec, units in documents:
        result = index.add_document(spec, units, embed=True)
        results.append(result)
        if result.get("embedding_error"):
            raise RuntimeError(f"embedding failed for {spec.doc_id}: {result['embedding_error']}")
    stats = {
        "documents": len(documents),
        "units": sum(item["units"] for item in results),
        "chunks": sum(item["chunks"] for item in results),
        "embedded": sum(item["embedded"] for item in results),
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "per_document": results,
    }
    return index, stats


def build_legacy(documents: list[tuple[DocumentSpec, list[Any]]], *, db_path: Path) -> tuple[LegacyIndex, dict[str, Any]]:
    active = [(spec, units) for spec, units in documents if spec.state == "active" and spec.is_current]
    # 旧方案对照必须每次从空库重建；LegacyIndex.build 只清 KnowledgeState，不删旧文档，
    # 复用旧 sqlite 会让旧侧混入上一轮文档，导致同一输入的新旧命中率不可复现。
    db_path.parent.mkdir(parents=True, exist_ok=True)
    for stale in db_path.parent.glob(f"{db_path.name}*"):
        stale.unlink()
    legacy = LegacyIndex(db_path)
    stats = legacy.build(active)
    return legacy, stats


def _source_hit(
    answer: Mapping[str, Any], expected_sources: list[Mapping[str, Any]], *, strict_file: bool = True
) -> bool:
    if not expected_sources:
        return True
    citations = list(answer.get("citations") or [])
    evidence = list(answer.get("evidence") or [])
    text = str(answer.get("text") or "")
    for source in expected_sources:
        file = str(source.get("file") or "")
        row = source.get("row")
        sheet = source.get("sheet")
        clause = source.get("clause")
        citation_text = json.dumps(citations, ensure_ascii=False)
        evidence_text = json.dumps(evidence, ensure_ascii=False)
        blob = citation_text + "\n" + evidence_text + "\n" + text
        if file and file not in blob:
            # 旧方案没有隔离适配层的资料编码；有行/表/条款证据时按定位匹配，并在报告中注明。
            if strict_file or not (row is not None or sheet or clause):
                continue
        if row is not None:
            locator_text = json.dumps([c.get("locator") if isinstance(c, dict) else {} for c in citations], ensure_ascii=False)
            if not re.search(rf'"row"\s*:\s*{int(row)}', locator_text + evidence_text):
                continue
        if sheet and sheet not in blob:
            continue
        if clause and clause not in blob:
            continue
        return True
    return False


def _kind_hit(expected: str | None, actual: str) -> bool:
    if not expected:
        return True
    if expected == "answer":
        return actual == "answer"
    if expected == "ambiguous":
        return actual in ("ambiguous", "clarification")
    if expected == "no_answer":
        return actual == "no_answer"
    return expected == actual


def evaluate(
    answer: Mapping[str, Any], expected: Mapping[str, Any], *, strict_file: bool = True
) -> dict[str, Any]:
    text = str(answer.get("text") or "")
    kind_ok = _kind_hit(expected.get("expected_kind"), str(answer.get("kind") or ""))
    values = list(expected.get("expected_values") or [])
    value_ok = all(_value_present(value, text) for value in values)
    source_ok = _source_hit(
        answer, list(expected.get("expected_sources") or []), strict_file=strict_file
    )
    min_total = expected.get("expected_min_total")
    total = (answer.get("diagnostics") or {}).get("total")
    total_ok = True if min_total is None else (isinstance(total, int) and total >= int(min_total))
    return {
        "kind_ok": kind_ok,
        "value_ok": value_ok,
        "source_ok": source_ok,
        "total_ok": total_ok,
        "hit": bool(kind_ok and value_ok and source_ok and total_ok),
    }


def run_conversations(
    new_index: RagIndex,
    legacy: LegacyIndex | None,
    conversations: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for conversation in conversations:
        conversation_id = f"s1-{conversation['id']}"
        old_context: dict[str, str] = {}
        for item in conversation["questions"]:
            started = time.monotonic()
            new_answer = new_index.ask(
                str(item["question"]), user_id="s1-dev", conversation_id=conversation_id
            )
            new_dict = new_answer.to_dict()
            new_elapsed = round((time.monotonic() - started) * 1000, 2)
            old_dict: dict[str, Any] | None = None
            old_elapsed = None
            if legacy is not None:
                old_started = time.monotonic()
                old_answer = legacy.ask(str(item["question"]), context_entities=old_context)
                old_dict = old_answer.to_dict()
                old_elapsed = round((time.monotonic() - old_started) * 1000, 2)
                old_context = dict(old_answer.diagnostics.get("entities") or old_context)
            record = {
                "id": item["id"],
                "conversation": conversation["id"],
                "question": item["question"],
                "expected": dict(item),
                "new": {
                    **new_dict,
                    "elapsed_ms": new_elapsed,
                    "checks": evaluate(new_dict, item),
                },
                "old": (
                    {
                        **old_dict,
                        "elapsed_ms": old_elapsed,
                        "checks": evaluate(old_dict, item),
                    }
                    if old_dict is not None
                    else None
                ),
            }
            records.append(record)
    return records


def _ledger_snapshot(path: Path) -> dict[str, Any]:
    """只读快照：行数、字节、哈希与解析出的事件；用于“起止一致/本轮差值”核对。"""
    if not path.exists():
        return {"exists": False, "events": [], "count": 0, "bytes": 0, "sha256": None}
    raw = path.read_bytes()
    events: list[dict[str, Any]] = []
    for line in raw.decode("utf-8").splitlines():
        text = line.strip()
        if not text:
            continue
        try:
            parsed = json.loads(text)
        except ValueError:
            continue
        if isinstance(parsed, dict):
            events.append(parsed)
    return {
        "exists": True,
        "events": events,
        "count": len(events),
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def _actuals_from_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    """账本事件汇总：reserved 是本进程的预留记录，不推断“已发送”；发送层见四层归因。"""
    reserved: dict[str, int] = {}
    results: dict[str, dict[str, int]] = {}
    error_codes: dict[str, int] = {}
    charge = 0.0
    reservation_kind: dict[str, str] = {}
    for event in events:
        kind = str(event.get("event") or "")
        if kind == "reserved":
            name = str(event.get("kind") or "unknown")
            reserved[name] = reserved.get(name, 0) + 1
            reservation_kind[str(event.get("reservation_id") or "")] = name
        elif kind == "result":
            name = str(event.get("kind") or reservation_kind.get(str(event.get("reservation_id") or "")) or "unknown")
            status = str(event.get("status") or "unknown")
            results.setdefault(name, {})
            results[name][status] = results[name].get(status, 0) + 1
            code = event.get("error_code")
            if code:
                error_codes[str(code)] = error_codes.get(str(code), 0) + 1
            try:
                charge += float(event.get("conservative_charge_cny") or 0.0)
            except (TypeError, ValueError):
                pass
    return {
        "reserved_by_kind": reserved,
        "results_by_kind": results,
        "error_codes": error_codes,
        "total_reserved": sum(reserved.values()),
        "total_results": sum(sum(counts.values()) for counts in results.values()),
        "conservative_charge_cny": round(charge, 10),
        "basis": (
            "账本 reserved/result 行只描述本进程的预留与结算结果，不等同于 HTTP 发送尝试；"
            "实际发送层见 attribution.layers.post_attempts 与 transport_attempts（未返回/未结算的预留只标 unsettled）"
        ),
    }


def _install_mock_transport(config: RagConfig, counter: dict[str, int]) -> tuple[Any, list]:
    """显式 mock 传输：由本工具自己注入并计数，报告中不会被当成真实服务。"""
    import httpx

    def _vector(text: str) -> list[float]:
        digest = hashlib.sha256(str(text).encode("utf-8")).digest()
        size = int(config.embedding_dimensions)
        values = [((digest[index % len(digest)] / 255.0) - 0.5) for index in range(size)]
        norm = math.sqrt(sum(value * value for value in values)) or 1.0
        return [value / norm for value in values]

    def handler(request: "httpx.Request") -> "httpx.Response":
        path = request.url.path
        payload = json.loads(request.read().decode("utf-8") or "{}")
        if "embeddings" in path:
            texts = list(payload.get("input") or [])
            return httpx.Response(
                200,
                json={
                    "id": "mock-embedding",
                    "data": [{"index": index, "embedding": _vector(text)} for index, text in enumerate(texts)],
                    "usage": {"total_tokens": sum(len(str(text)) for text in texts)},
                },
            )
        if "rerank" in path:
            documents = list((payload.get("input") or {}).get("documents") or [])
            top_n = int((payload.get("parameters") or {}).get("top_n") or len(documents) or 1)
            rows = [
                {"index": index, "relevance_score": round(1.0 - index / (len(documents) + 1), 6)}
                for index in range(len(documents))
            ]
            return httpx.Response(
                200,
                json={
                    "id": "mock-rerank",
                    "output": {"results": rows[:top_n]},
                    "usage": {"total_tokens": 10},
                },
            )
        messages = list(payload.get("messages") or [])
        user = next((item.get("content") for item in messages if item.get("role") == "user"), "{}")
        try:
            body = json.loads(user)
        except ValueError:
            body = {}
        evidence = list(body.get("evidence") or [])
        first = evidence[0] if evidence else {"chunk_id": "mock", "text": "mock evidence"}
        answer = {
            "answer": str(first.get("text") or "mock")[:80],
            "source_ids": [str(first.get("chunk_id") or "mock")],
        }
        return httpx.Response(
            200,
            json={
                "id": "mock-chat",
                "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(answer, ensure_ascii=False)}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
            },
        )

    class _CountingMockTransport(httpx.MockTransport):
        """在 transport 边界计数：请求到达传输即算一次（处理器抛异常也照计）。"""

        def handle_request(self, request: "httpx.Request") -> "httpx.Response":
            path = request.url.path
            kind = "embedding" if "embeddings" in path else "rerank" if "rerank" in path else "chat"
            counter[kind] = counter.get(kind, 0) + 1
            return super().handle_request(request)

    transport = _CountingMockTransport(handler)
    patches: list = []
    original_init = httpx.Client.__init__

    def patched_init(self, *init_args, **init_kwargs):
        init_kwargs["transport"] = transport
        return original_init(self, *init_args, **init_kwargs)

    httpx.Client.__init__ = patched_init
    patches.append(("httpx.Client.__init__", original_init))
    return transport, patches


def _restore_patches(patches: list) -> None:
    import httpx

    for name, original in patches:
        if name == "httpx.Client.__init__":
            httpx.Client.__init__ = original


def _attribution_layers(
    *,
    events: list[Mapping[str, Any]],
    run_id: str | None,
    post_stats: Mapping[str, Any] | None,
    transport: str,
    transport_counter: Mapping[str, int] | None,
) -> dict[str, Any]:
    """四层事件归因：reserved / post_attempts / transport_attempts / outcomes。

    - reserved：已持久化的预留行（含本轮未返回、未结算的行）；归属按账本里锁内写入的 run_id 认领，
      因此 `reserve()` 未返回也能恢复；旧账行没有 run_id，单独计入 legacy_unknown。
    - post_attempts：客户端 `http.Client.post` 边界计数（进入 post、未到传输也算），不取预留数。
    - transport_attempts：Mock 传输层实收计数；真实网络只能证明到本地 transport，未验证时置 null。
    - outcomes：账本 result 行的状态分列；没有 result 的预留单列 unsettled，不猜“未发送/已发送”。
    """
    own_reserved: list[Mapping[str, Any]] = []
    foreign_reserved: list[Mapping[str, Any]] = []
    legacy_reserved: list[Mapping[str, Any]] = []
    for event in events:
        if event.get("event") != "reserved":
            continue
        event_run = event.get("run_id")
        if run_id and event_run == run_id:
            own_reserved.append(event)
        elif event_run is None:
            legacy_reserved.append(event)
        else:
            foreign_reserved.append(event)
    own_ids = {str(event.get("reservation_id") or "") for event in own_reserved}
    results: dict[str, Mapping[str, Any]] = {}
    foreign_results: list[Mapping[str, Any]] = []
    for event in events:
        if event.get("event") != "result":
            continue
        reservation_id = str(event.get("reservation_id") or "")
        if reservation_id in own_ids:
            results[reservation_id] = event
        else:
            foreign_results.append(event)
    unsettled = [event for event in own_reserved if str(event.get("reservation_id") or "") not in results]
    settled_conservative = 0.0
    usage_estimate = 0.0
    status_counts: dict[str, int] = {}
    kind_outcomes: dict[str, dict[str, int]] = {}
    error_codes: dict[str, int] = {}
    for event in own_reserved:
        result = results.get(str(event.get("reservation_id") or ""))
        if result is None:
            continue
        charge = max(
            float(result.get("conservative_charge_cny") or 0.0),
            float(event.get("reserve_cny") or 0.0),
        )
        settled_conservative += charge
        usage_estimate += float(result.get("estimated_list_price_cny") or 0.0)
        status = str(result.get("status") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
        kind = str(event.get("kind") or "unknown")
        kind_outcomes.setdefault(kind, {})
        kind_outcomes[kind][status] = kind_outcomes[kind].get(status, 0) + 1
        code = result.get("error_code")
        if code:
            error_codes[str(code)] = error_codes.get(str(code), 0) + 1
    frozen = sum(float(event.get("reserve_cny") or 0.0) for event in unsettled)
    reserved_by_kind: dict[str, int] = {}
    reserved_cny = 0.0
    for event in own_reserved:
        kind = str(event.get("kind") or "unknown")
        reserved_by_kind[kind] = reserved_by_kind.get(kind, 0) + 1
        reserved_cny += float(event.get("reserve_cny") or 0.0)
    post_attempts = dict((post_stats or {}).get("attempts") or {})
    post_outcomes = dict((post_stats or {}).get("outcomes") or {})
    transport_verified = transport == "mock" and transport_counter is not None
    transport_attempts = dict(transport_counter or {}) if transport_verified else None
    return {
        "layers": {
            "reserved": {
                "own": len(own_reserved),
                "foreign": len(foreign_reserved),
                "legacy_unknown": len(legacy_reserved),
                "by_kind": reserved_by_kind,
                "basis": "账本 reserved 行；本轮归属取锁内写入的 run_id（含未返回/未结算行）",
            },
            "post_attempts": {
                "total": sum(post_attempts.values()),
                "by_kind": post_attempts,
                "outcomes": post_outcomes,
                "basis": "providers 在 `self._client.post(...)` 之前计数；进入 post 未到 transport 也算一次",
            },
            "transport_attempts": {
                "total": sum(transport_attempts.values()) if transport_attempts is not None else None,
                "by_kind": transport_attempts,
                "verified": transport_verified,
                "basis": (
                    "本工具注入的 MockTransport 实收计数"
                    if transport_verified
                    else "真实网络无本地传输级计数：只能证明本地 post 尝试，不宣称供应商收到或已计费"
                ),
            },
            "outcomes": {
                "settled": sum(status_counts.values()),
                "unsettled": len(unsettled),
                "by_status": status_counts,
                "by_kind": kind_outcomes,
                "error_codes": error_codes,
                "foreign_results": len(foreign_results),
                "basis": "账本 result 行；没有 result 的预留只标 unsettled，不推断是否已发送",
            },
        },
        "cost": {
            "own_reserved_cny": round(reserved_cny, 10),
            "own_settled_conservative_cny": round(settled_conservative, 10),
            "own_unsettled_frozen_cny": round(frozen, 10),
            "own_conservative_total_cny": round(settled_conservative + frozen, 10),
            "usage_estimate_cny": round(usage_estimate, 10),
            "provider_billed_cny": None,
            "note": "供应商账单仍未核对；usage_estimate 只是按官方标价的估算，不是账单",
        },
    }


def _execution_block(
    *,
    transport: str,
    started_utc: str,
    finished_utc: str | None,
    error: str | None,
    plan: Mapping[str, Any] | None,
    ledger_start: Mapping[str, Any] | None,
    ledger_end: Mapping[str, Any] | None,
    actuals: Mapping[str, Any] | None,
    mock_counter: Mapping[str, int] | None,
    records: list[Mapping[str, Any]],
    complete: bool,
    own_events: list[Mapping[str, Any]] | None = None,
    post_counters: Mapping[str, Any] | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    structural = int((plan or {}).get("requests_structural_upper") or 0)
    worst_case = int((plan or {}).get("requests_worst_case") or 0)
    degraded_questions: list[dict[str, Any]] = []
    for item in records:
        diagnostics = dict((item.get("new") or {}).get("diagnostics") or {})
        degraded = list(diagnostics.get("degraded") or ())
        reason = (item.get("new") or {}).get("reason")
        if degraded or diagnostics.get("vector_error") or reason in (
            "REQUEST_LIMIT_EXCEEDED",
            "BUDGET_EXCEEDED",
            "RAG_CONFIG_INVALID",
            "CHAT_UNAVAILABLE",
            "RECORD_ONLY",
        ):
            degraded_questions.append(
                {
                    "id": item.get("id"),
                    "kind": (item.get("new") or {}).get("kind"),
                    "reason": reason,
                    "degraded": degraded,
                    "vector_error": diagnostics.get("vector_error"),
                    "answer_source": (item.get("new") or {}).get("answer_source"),
                }
            )
    ledger_delta: dict[str, Any] | None = None
    delta_events: list[Mapping[str, Any]] = []
    if ledger_start is not None and ledger_end is not None:
        delta_events = list(ledger_end.get("events") or [])[int(ledger_start.get("count") or 0) :]
        prefix_same = hashlib.sha256(
            "\n".join(json.dumps(event, ensure_ascii=False, sort_keys=True) for event in (ledger_start.get("events") or [])).encode(
                "utf-8"
            )
        ).hexdigest() == hashlib.sha256(
            "\n".join(
                json.dumps(event, ensure_ascii=False, sort_keys=True)
                for event in (list(ledger_end.get("events") or [])[: int(ledger_start.get("count") or 0)])
            ).encode("utf-8")
        ).hexdigest()
        ledger_delta = {
            "start": {key: ledger_start.get(key) for key in ("count", "bytes", "sha256")},
            "end": {key: ledger_end.get(key) for key in ("count", "bytes", "sha256")},
            "new_events": len(delta_events),
            "prefix_unchanged": prefix_same,
            "delta_reservations": sum(1 for event in delta_events if event.get("event") == "reserved"),
            "delta_results": sum(1 for event in delta_events if event.get("event") == "result"),
            "delta_conservative_charge_cny": round(
                sum(
                    float(event.get("conservative_charge_cny") or 0.0)
                    for event in delta_events
                    if event.get("event") == "result"
                ),
                10,
            ),
        }
    attribution = _attribution_layers(
        events=delta_events,
        run_id=run_id,
        post_stats=post_counters,
        transport=transport,
        transport_counter=mock_counter,
    )
    layers = attribution["layers"]
    post_total = int(layers["post_attempts"]["total"] or 0)
    transport_total = layers["transport_attempts"]["total"]
    if transport == "offline":
        real_calls: int | None = 0
        transport_label = "offline_fake_providers"
    elif transport == "mock":
        real_calls = 0
        transport_label = "mock_transport_injected_by_tool"
    elif transport == "real":
        # 无传输级计数 ⇒ 真实调用数不可自证：real_calls 为 null，另列本地 post 尝试。
        real_calls = None
        transport_label = "real_transport_unverified"
    else:
        real_calls = None
        transport_label = "unknown"
    return {
        "transport": transport,
        "transport_attribution": transport_label,
        "transport_attempts_verified": bool(layers["transport_attempts"]["verified"]),
        "transport_attempts": transport_total,
        "local_post_attempts": {"total": post_total, "by_kind": layers["post_attempts"]["by_kind"]},
        "live_entry": transport in ("real", "mock"),
        "real_calls": real_calls,
        "real_calls_unverified": transport == "real",
        "mock_http_attempts": (sum(mock_counter.values()) if mock_counter is not None else None),
        "mock_http_attempts_by_kind": dict(mock_counter or {}) or None,
        "complete": bool(complete),
        "started_utc": started_utc,
        "finished_utc": finished_utc,
        "error": error,
        "run_id": run_id,
        "attribution": attribution,
        "providers": dict(actuals or {}),
        "cost": {
            "planned_structural_upper_cny": (plan or {}).get("total_upper_structural_cny"),
            "planned_worst_case_cny": (plan or {}).get("worst_case_upper_cny"),
            **{key: attribution["cost"][key] for key in (
                "own_reserved_cny",
                "own_settled_conservative_cny",
                "own_unsettled_frozen_cny",
                "own_conservative_total_cny",
                "usage_estimate_cny",
                "provider_billed_cny",
            )},
        },
        "ledger": ledger_delta,
        "plan_vs_actual": {
            "observed_requests": (plan or {}).get("requests_planned"),
            "structural_upper_requests": structural,
            "requests_worst_case": worst_case,
            "attempts": post_total,
            "actual_attempts": post_total,
            "actual_attempts_layer": "post_attempts",
            "transport_attempts": transport_total,
            "delta_vs_observed": post_total - int((plan or {}).get("requests_planned") or 0),
            "delta_vs_worst_case": post_total - worst_case,
            "within_worst_case": post_total <= worst_case if worst_case else None,
            "logical_vs_attempts_note": (
                "attempts 含重试，必须与 requests_worst_case 比较；"
                "requests_structural_upper 是不含重试的逻辑请求数，不能直接比"
            ),
        },
        "degraded_questions": degraded_questions,
    }

def write_report(
    out_dir: Path,
    *,
    mode: str,
    config: RagConfig,
    new_stats: Mapping[str, Any],
    legacy_stats: Mapping[str, Any] | None,
    skipped: list[dict[str, Any]],
    records: list[dict[str, Any]],
    budget_summary: Mapping[str, Any] | None,
    subset: Mapping[str, Any] | None = None,
    plan: Mapping[str, Any] | None = None,
    execution: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    new_hits = sum(1 for item in records if item["new"]["checks"]["hit"])
    old_hits = sum(1 for item in records if item["old"] and item["old"]["checks"]["hit"])
    old_total = sum(1 for item in records if item["old"])
    transport = str((execution or {}).get("transport") or ("offline" if mode == "offline" else "unknown"))
    summary = {
        "mode": mode,
        "mock": mode == "offline" or transport == "mock",
        "transport": transport,
        "real_calls": (execution or {}).get("real_calls", 0 if mode == "offline" else None),
        "mock_http_attempts": (execution or {}).get("mock_http_attempts"),
        "config": safe_config_summary(config),
        "plan": dict(plan or {}) or None,
        "execution": dict(execution or {}) or None,
        "new_stats": new_stats,
        "legacy_stats": legacy_stats,
        "skipped": skipped,
        "subset": dict(subset or {}),
        "questions": len(records),
        "new_hits": new_hits,
        "old_hits": old_hits if legacy_stats else None,
        "old_questions": old_total if legacy_stats else None,
        "new_kinds": {
            kind: sum(1 for item in records if item["new"]["kind"] == kind)
            for kind in sorted({item["new"]["kind"] for item in records})
        },
        "budget": budget_summary,
        "records": records,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"run-{mode}.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    execution_info = dict(execution or {})
    plan_info = dict(plan or {})
    lines = [
        f"# LOCAL-R1/S1 {mode} 实验结果",
        "",
        f"- 模式：{mode}；transport：{transport}；mock：{summary['mock']}；真实调用：{summary['real_calls']}；mock HTTP 尝试：{summary['mock_http_attempts']}",
        f"- 索引：{new_stats.get('documents')} 份资料 / {new_stats.get('units')} 个单元 / {new_stats.get('chunks')} 个块",
        f"- 新版命中：{new_hits}/{len(records)}；旧版命中：{old_hits}/{old_total if legacy_stats else 0}",
        f"- 计划：观测 {plan_info.get('requests_planned')} 次 / 结构上界 {plan_info.get('requests_structural_upper')} 次（含重试 {plan_info.get('requests_worst_case')}）；可执行：{plan_info.get('executable')}",
        f"- 实际：{((execution_info.get('plan_vs_actual') or {}).get('actual_attempts_layer') or 'post_attempts')} "
        f"{((execution_info.get('plan_vs_actual') or {}).get('actual_attempts'))}；"
        f"transport 实收 {((execution_info.get('attribution') or {}).get('layers', {}).get('transport_attempts', {}).get('total'))}"
        f"（verified={((execution_info.get('attribution') or {}).get('layers', {}).get('transport_attempts', {}).get('verified'))}）；"
        f"完整执行：{execution_info.get('complete')}；错误：{execution_info.get('error')}",
        f"- 子集：manifest {dict(subset or {}).get('manifest_files', '?')} 份，实际载入 {new_stats.get('documents')} 份，排除 {len(skipped)} 条（敏感/边界/扫描/max_docs 原因见 JSON）",
        "",
        "| 编号 | 问题 | 新版 | 旧版 | 新版结果 | 旧版结果 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for item in records:
        new_check = "PASS" if item["new"]["checks"]["hit"] else "FAIL"
        old_check = "PASS" if item["old"] and item["old"]["checks"]["hit"] else ("FAIL" if item["old"] else "—")
        new_text = str(item["new"]["text"]).replace("\n", " ")[:110]
        old_text = str(item["old"]["text"]).replace("\n", " ")[:110] if item["old"] else "—"
        lines.append(
            f"| {item['id']} | {item['question']} | {new_check} {item['new']['kind']} | {old_check} "
            f"{item['old']['kind'] if item['old'] else '—'} | {new_text} | {old_text} |"
        )
    if plan_info.get("blocked_reasons"):
        lines.append("")
        lines.append("- 计划阻断：" + "；".join(str(reason) for reason in plan_info["blocked_reasons"]))
    degraded = execution_info.get("degraded_questions") or []
    if degraded:
        lines.append("- 降级/中断归因：")
        for item in degraded:
            lines.append(
                f"  - {item.get('id')}：kind={item.get('kind')} reason={item.get('reason')} "
                f"degraded={item.get('degraded')} vector_error={item.get('vector_error')}"
            )
    lines.extend(
        [
            "",
            "## 说明",
            "",
            "- offline 使用确定性哈希 embedding 与离线 lexical rerank；不是真实模型效果。",
            "- 旧方案为现有 T05/T06 精确+FTS 检索，回答由同一离线抽取器生成；不代表旧产品真实模型答案。",
            "- `requests_planned` 是观测口径，不能当上界；预算结论只看 `requests_structural_upper`/`requests_worst_case`。",
            "- 真实 40 题/100 份/1 万记录/3 并发尚未执行，本轮不声称通过。",
            "- 详细诊断（查询补全、过滤、各路召回、最终证据、引用、拒绝原因、耗时）见 JSON。",
        ]
    )
    (out_dir / f"run-{mode}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return summary


def load_questions(path: Path | str) -> list[dict[str, Any]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    conversations = data.get("conversations") if isinstance(data, dict) else None
    if not isinstance(conversations, list):
        raise SystemExit("题集 JSON 缺少 conversations 数组")
    return conversations


def select_conversations(
    conversations: list[dict[str, Any]],
    *,
    limit_conversations: int | None = None,
    max_questions: int | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """按会话数和实际 turn 数双重夹紧；plan 与真实运行共用。"""
    selected: list[dict[str, Any]] = []
    question_count = 0
    source = conversations[: max(0, int(limit_conversations))] if limit_conversations is not None else conversations
    for conversation in source:
        turns = list(conversation.get("questions") or [])
        if max_questions is not None:
            remaining = max(0, int(max_questions) - question_count)
            if remaining <= 0:
                break
            turns = turns[:remaining]
        if not turns:
            continue
        item = {**conversation, "questions": turns}
        selected.append(item)
        question_count += len(turns)
        if max_questions is not None and question_count >= int(max_questions):
            break
    return selected, question_count


def question_texts(conversations: list[dict[str, Any]]) -> list[str]:
    return [str(turn.get("question") or "") for conversation in conversations for turn in conversation.get("questions") or []]


def trace_request_counts(
    documents: list[tuple[DocumentSpec, list[Any]]],
    conversations: list[dict[str, Any]],
    config: RagConfig,
    out_dir: Path,
) -> dict[str, int]:
    """零 HTTP 的离线轨迹：用确定性替身实际跑 build+ask，统计调用次数。"""
    class CountingEmbedding:
        provider = "offline-trace"
        model = config.embedding_model
        dimensions = config.embedding_dimensions

        def __init__(self) -> None:
            self.base = FakeEmbeddingProvider(model=config.embedding_model, dimensions=config.embedding_dimensions)
            self.build_calls = 0
            self.query_calls = 0

        def embed(self, texts: Sequence[str], *, purpose: str = "document"):
            if purpose == "query":
                self.query_calls += 1
            else:
                self.build_calls += 1
            return self.base.embed(texts, purpose=purpose)

    class CountingRerank:
        provider = "offline-trace"
        model = "lexical-overlap-v1"

        def __init__(self) -> None:
            self.base = LexicalReranker()
            self.calls = 0

        def rerank(self, query: str, docs: Sequence[str], *, top_n: int | None = None):
            self.calls += 1
            return self.base.rerank(query, docs, top_n=top_n)

    out_dir.mkdir(parents=True, exist_ok=True)
    db_path = out_dir / "trace-plan.sqlite3"
    for stale in out_dir.glob("trace-plan.sqlite3*"):
        stale.unlink()
    embedder = CountingEmbedding()
    reranker = CountingRerank()
    index = RagIndex(
        db_path,
        config=RagConfig(**{**config.__dict__, "provider_mode": "offline"}),
        embedder=embedder,
        reranker=reranker,
    )
    try:
        for spec, units in documents:
            index.add_document(spec, units)
        build_calls = embedder.build_calls
        embedder.query_calls = 0
        reranker.calls = 0
        run_conversations(index, None, conversations)
        return {
            "embedding_build_calls": build_calls,
            "embedding_query_calls": embedder.query_calls,
            "rerank_calls": reranker.calls,
        }
    finally:
        index.close()
        for stale in out_dir.glob("trace-plan.sqlite3*"):
            stale.unlink()


def _build_request_upper_by_document(
    documents: list[tuple[DocumentSpec, list[Any]]], config: RagConfig
) -> dict[str, Any]:
    """建库请求的结构上界：index.py 每个文档一次 embed(texts)，providers 再按批切片。"""
    batch_size = max(1, min(int(config.embedding_batch_size), 10))
    per_document: list[dict[str, Any]] = []
    total_chunks = 0
    all_texts: set[str] = set()
    for spec, units in documents:
        chunks = build_chunks(spec, units, config)
        texts = {chunk.text for chunk in chunks}
        total_chunks += len(chunks)
        all_texts.update(texts)
        per_document.append(
            {
                "doc_id": spec.doc_id,
                "chunks": len(chunks),
                "unique_content": len(texts),
                "batches": math.ceil(len(texts) / batch_size) if texts else 0,
            }
        )
    return {
        "batch_size": batch_size,
        "chunks": total_chunks,
        "unique_content": len(all_texts),
        "per_document": per_document,
        "upper_requests": sum(item["batches"] for item in per_document),
        "global_grouped_requests": math.ceil(len(all_texts) / batch_size) if all_texts else 0,
    }


def validate_trace_counts(
    trace: Mapping[str, Any] | None,
    *,
    questions: int,
    documents: int,
    query_embedding_enabled: bool,
    rerank_enabled: bool = True,
) -> dict[str, Any]:
    """观测轨迹只用于对照，不能当上界；负数/超问数/非整数/矛盾值直接拒绝。

    注意层级：trace 的 `embedding_build_calls` 是 **provider 逻辑调用**（每份资料一次），
    不是 HTTP 批数；因此只能与资料数比较，不能当成建库请求数，也不能用来减小结构上界。
    """
    errors: list[str] = []
    counts: dict[str, int] = {}
    if trace is None:
        return {"valid": False, "errors": [], "counts": {}, "used_as_upper": False, "note": "未提供观测轨迹"}
    logical_build_upper = int(documents)
    for key in ("embedding_build_calls", "embedding_query_calls", "rerank_calls"):
        if key not in trace:
            errors.append(f"TRACE_MISSING:{key}")
            continue
        value = trace.get(key)
        if isinstance(value, bool) or not isinstance(value, int):
            errors.append(f"TRACE_NOT_INTEGER:{key}={value!r}")
            continue
        if value < 0:
            errors.append(f"TRACE_NEGATIVE:{key}={value}")
            continue
        counts[key] = value
    if "embedding_query_calls" in counts:
        if counts["embedding_query_calls"] > questions:
            errors.append(
                f"TRACE_OVER_QUESTIONS:embedding_query_calls={counts['embedding_query_calls']}>{questions}"
            )
        if not query_embedding_enabled and counts["embedding_query_calls"] != 0:
            errors.append("TRACE_CONTRADICTS_DISABLE_QUERY_EMBEDDING")
    if "rerank_calls" in counts:
        if counts["rerank_calls"] > questions:
            errors.append(f"TRACE_OVER_QUESTIONS:rerank_calls={counts['rerank_calls']}>{questions}")
        if not rerank_enabled and counts["rerank_calls"] != 0:
            errors.append("TRACE_CONTRADICTS_RERANK_DISABLED")
    if "embedding_build_calls" in counts and counts["embedding_build_calls"] > logical_build_upper:
        # 逻辑建库调用不应多于资料数；多于说明轨迹不可信。
        errors.append(
            f"TRACE_BUILD_OVER_DOCUMENTS:observed={counts['embedding_build_calls']}>{logical_build_upper}"
        )
    return {
        "valid": not errors,
        "errors": errors,
        "counts": counts,
        "logical_build_calls": counts.get("embedding_build_calls"),
        "logical_build_upper": logical_build_upper,
        "used_as_upper": False,
        "note": "trace 只用于观测对照；建库调用按资料计，HTTP 批数取结构上界",
    }


def build_index_plan(
    documents: list[tuple[DocumentSpec, list[Any]]],
    *,
    config: RagConfig,
    max_requests: int,
    max_questions: int,
    stage_remaining_cny: float | None,
    query_embedding_requests: int | None = None,
    rerank_requests: int | None = None,
    chat_requests: int | None = None,
    question_texts: list[str] | None = None,
    existing_requests: int = 0,
    max_retries: int | None = None,
    trace_counts: Mapping[str, Any] | None = None,
    disable_query_embedding: bool | None = None,
    record_only: bool | None = None,
) -> dict[str, Any]:
    """零请求预核算：观测计划与结构性最坏上界分开，executable 只看结构上界。

    结构上界的逐调用点依据（任何一条调用路径变了都要同步改这里）：
    - 建库：`index.py:442` 每份资料恰好一次 `embed(texts)`；`providers.py` 的
      `BailianEmbeddingProvider.embed` 按 `embedding_batch_size` 分片 ⇒ 上界 =
      Σ_doc ceil(该文档去重块数 / 批大小)。按全局去重分组会低估多文档场景，不能当上界。
    - 查询 embedding：`answer.py:101` 每次 ask 至多 1 次 `index.search`；
      `retrieval.py:244` 每次 search 至多 1 次查询 embedding ⇒ 每问 ≤ 1。
    - rerank：`retrieval.py:417` 融合候选非空时至多 1 次 ⇒ 每问 ≤ 1。
    - chat：`answer.py:542` 只有 document 分支才构造 chat provider ⇒ 每问 ≤ 1；
      `record_only` 在 plan 阶段直接拒答（`answer.py` record_only 分支），运行时强制为 0。
    降低某一面的唯一合法方式是带运行时强制约束的开关（disable_query_embedding /
    record_only），不能靠 Fake 轨迹、澄清分支、题号或假设存在查询缓存。
    """
    batch = _build_request_upper_by_document(documents, config)
    build_upper = int(batch["upper_requests"])
    text_list = list(question_texts or [])
    unique_questions = len({_normalize(text) for text in text_list if str(text).strip()})
    retries = int(config.max_retries if max_retries is None else max_retries)
    if retries < 0:
        raise SystemExit("max_retries 必须是非负整数")
    attempt_factor = retries + 1

    query_disabled = bool(
        config.disable_query_embedding if disable_query_embedding is None else disable_query_embedding
    )
    record_only = bool(config.record_only if record_only is None else record_only)
    chat_configured = bool(str(config.chat_model or "").strip())

    # ---- 结构上界（executable 只看这一组）
    query_upper = 0 if query_disabled else int(max_questions)
    rerank_upper = int(max_questions)
    chat_upper_requests = 0 if (record_only or not chat_configured) else int(max_questions)
    structural_total = build_upper + query_upper + rerank_upper + chat_upper_requests

    # ---- 观测计划（trace/显式参数/按题数估算），只用于对照
    trace = trace_counts if trace_counts is not None else None
    trace_validation = validate_trace_counts(
        trace,
        questions=int(max_questions),
        documents=len(documents),
        query_embedding_enabled=not query_disabled,
        rerank_enabled=True,
    )
    if trace is not None and trace_validation["valid"]:
        observed_build = build_upper
        observed_query = int(trace_validation["counts"]["embedding_query_calls"])
        observed_rerank = int(trace_validation["counts"]["rerank_calls"])
        observed_source = "offline_trace"
    else:
        observed_build = build_upper
        observed_notes: list[str] = []
        if query_disabled:
            observed_query = 0
        elif query_embedding_requests is not None:
            observed_query = int(query_embedding_requests)
            if observed_query > int(max_questions):
                observed_notes.append(
                    f"OBSERVED_QUERY_OVER_QUESTIONS:{observed_query}>{int(max_questions)}"
                )
                observed_query = int(max_questions)
            observed_query = max(0, observed_query)
        else:
            observed_query = int(unique_questions) if text_list else int(max_questions)
        if rerank_requests is not None:
            observed_rerank = int(rerank_requests)
            if observed_rerank > int(max_questions):
                observed_notes.append(
                    f"OBSERVED_RERANK_OVER_QUESTIONS:{observed_rerank}>{int(max_questions)}"
                )
                observed_rerank = int(max_questions)
            observed_rerank = max(0, observed_rerank)
        else:
            observed_rerank = min(max(int(max_requests), 0), int(max_questions))
        observed_source = "explicit" if (query_embedding_requests is not None or rerank_requests is not None) else "estimate"
    if chat_upper_requests == 0:
        observed_chat = 0
    elif chat_requests is not None:
        observed_chat = max(0, int(chat_requests))
    else:
        observed_chat = len(text_list) if text_list else int(max_questions)
    observed_chat = min(observed_chat, chat_upper_requests)
    observed_total = observed_build + observed_query + observed_rerank + observed_chat

    # ---- 费用（官方单请求上限口径）
    embedding_request_upper = 10 * 8192 * config.embedding_price_per_million_cny / 1_000_000.0
    rerank_request_upper = config.rerank_max_request_tokens * config.rerank_price_per_million_cny / 1_000_000.0
    chat_prices_known = (
        config.chat_input_price_per_million_cny is not None
        and config.chat_output_price_per_million_cny is not None
        and config.chat_max_input_tokens is not None
        and config.chat_max_output_tokens is not None
    )
    chat_request_upper: float | None = None
    chat_upper: float | None = None
    if chat_upper_requests:
        if chat_prices_known:
            chat_request_upper = (
                config.chat_max_input_tokens * config.chat_input_price_per_million_cny / 1_000_000.0
                + config.chat_max_output_tokens * config.chat_output_price_per_million_cny / 1_000_000.0
            )
            chat_upper = chat_upper_requests * chat_request_upper
        else:
            chat_upper = None
    embedding_upper = (build_upper + query_upper) * embedding_request_upper
    rerank_cost_upper = rerank_upper * rerank_request_upper
    structural_cost = embedding_upper + rerank_cost_upper + (chat_upper or 0.0)
    known_structural_cost = None if (chat_upper_requests and not chat_prices_known) else structural_cost
    observed_cost = (
        (observed_build + observed_query) * embedding_request_upper
        + observed_rerank * rerank_request_upper
        + (observed_chat * chat_request_upper if (observed_chat and chat_request_upper) else 0.0)
    )

    remaining_requests = max(0, int(max_requests) - max(0, int(existing_requests)))
    worst_requests = structural_total * attempt_factor
    worst_cost = None if known_structural_cost is None else known_structural_cost * attempt_factor
    blocked: list[str] = []
    if trace_validation["errors"]:
        blocked.append("TRACE_INVALID:" + ";".join(trace_validation["errors"]))
    if worst_requests > remaining_requests:
        blocked.append(f"REQUEST_LIMIT:{worst_requests}>{remaining_requests}")
    if chat_upper_requests and not chat_prices_known:
        blocked.append("CHAT_UPPER_UNPROVEN")
    if chat_request_upper is not None and chat_request_upper > config.max_request_cny + 1e-12:
        blocked.append(f"CHAT_REQUEST_CAP:{chat_request_upper:.8f}>{config.max_request_cny:.8f}")
    if worst_cost is not None and stage_remaining_cny is not None and worst_cost > stage_remaining_cny + 1e-12:
        blocked.append(f"STAGE_BALANCE:{worst_cost:.8f}>{stage_remaining_cny:.8f}")

    return {
        "plan_version": "R5",
        "documents": len(documents),
        "chunks": int(batch["chunks"]),
        "unique_content": int(batch["unique_content"]),
        "embedding_batch_size": int(batch["batch_size"]),
        "embedding_single_byte_cap": 8192,
        "embedding_batches": build_upper,
        "embedding_batches_global_grouped": int(batch["global_grouped_requests"]),
        "embedding_max_batch_bytes": 0,
        "embedding_build_requests": build_upper,
        "embedding_query_requests": observed_query,
        "embedding_query_requests_upper": query_upper,
        "embedding_query_cache_hits_planned": 0,
        "embedding_query_skipped_planned": max(0, int(max_questions) - observed_query),
        "embedding_requests": observed_build + observed_query,
        "embedding_requests_upper": build_upper + query_upper,
        "embedding_request_upper_cny": round(embedding_request_upper, 10),
        "embedding_upper_cny": round(embedding_upper, 10),
        "rerank_requests_planned": observed_rerank,
        "rerank_requests_upper": rerank_upper,
        "rerank_max_requests": max_requests,
        "rerank_request_upper_cny": round(rerank_request_upper, 10),
        "rerank_max_documents": config.rerank_max_documents,
        "rerank_top_n": config.rerank_top_n,
        "rerank_request_token_cap": config.rerank_max_request_tokens,
        "rerank_upper_cny": round(rerank_cost_upper, 10),
        "chat_requests_planned": observed_chat,
        "chat_requests_upper": chat_upper_requests,
        "chat_upper_cny": None if chat_upper is None else round(chat_upper, 10),
        "chat_request_upper_cny": None if chat_request_upper is None else round(chat_request_upper, 10),
        "chat_prices_and_limits_known": chat_prices_known,
        "questions_planned": int(max_questions),
        "requests_planned": observed_total,
        "requests_structural_upper": structural_total,
        "requests_worst_case": worst_requests,
        "attempt_factor": attempt_factor,
        "max_retries": retries,
        "existing_requests": int(existing_requests),
        "remaining_requests": remaining_requests,
        "max_requests": max_requests,
        "failure_retention_upper_cny": None if worst_cost is None else round(worst_cost, 10),
        "stage_remaining_cny": None if stage_remaining_cny is None else round(stage_remaining_cny, 10),
        "total_upper_cny": round(observed_cost, 10),
        "total_upper_structural_cny": None if known_structural_cost is None else round(known_structural_cost, 10),
        "worst_case_upper_cny": None if worst_cost is None else round(worst_cost, 10),
        "within_request_limit": worst_requests <= remaining_requests,
        "within_stage_balance": (
            None
            if stage_remaining_cny is None or worst_cost is None
            else worst_cost <= stage_remaining_cny + 1e-12
        ),
        "executable": not blocked,
        "blocked_reasons": blocked,
        "observed": {
            "source": observed_source,
            "notes": observed_notes if not (trace is not None and trace_validation["valid"]) else [],
            "embedding_build_requests": observed_build,
            "embedding_query_requests": observed_query,
            "rerank_requests": observed_rerank,
            "chat_requests": observed_chat,
            "requests_total": observed_total,
            "upper_cny": round(observed_cost, 10),
        },
        "structural_upper": {
            "embedding_build_requests": build_upper,
            "embedding_query_requests": query_upper,
            "rerank_requests": rerank_upper,
            "chat_requests": chat_upper_requests,
            "requests_total": structural_total,
            "requests_with_retries": worst_requests,
            "upper_cny": None if known_structural_cost is None else round(known_structural_cost, 10),
            "per_question": {
                "embedding_query": 0 if query_disabled else 1,
                "rerank": 1,
                "chat": 0 if chat_upper_requests == 0 else 1,
            },
            "basis": {
                "embedding_build": "index.py:442 每份资料一次 embed(texts)，providers 按 embedding_batch_size 分片 ⇒ Σ_doc ceil(去重块数/批大小)",
                "embedding_query": "answer.py:101 每次 ask 至多 1 次 search；retrieval.py:244 每次 search 至多 1 次 query embedding",
                "rerank": "retrieval.py:417 融合候选非空时至多 1 次 rerank",
                "chat": "answer.py:542 只有 document 分支构造 chat provider",
            },
        },
        "face_enforcement": {
            "disable_query_embedding": query_disabled,
            "record_only": record_only,
            "query_embedding_enforced_at": (
                "retrieval.py:_vector_recall 返回 QUERY_EMBEDDING_DISABLED，不发 HTTP" if query_disabled else None
            ),
            "chat_enforced_at": (
                "answer.py record_only 分支在检索前拒答，不构造 provider" if record_only else None
            ),
        },
        "trace_validation": trace_validation,
        "cache_semantics": {
            "embedding_query_cache_hits": 0,
            "embedding_query_skipped_planned": max(0, int(max_questions) - observed_query),
            "note": "查询向量没有缓存（retrieval.py 直连 embedder）；旧字段 embedding_query_cache_hits_planned 恒为 0 且已废弃",
        },
        "per_document_batches": batch["per_document"],
        "deprecated_fields": {
            "embedding_query_cache_hits_planned": "恒为 0：查询向量无缓存；旧口径把“未走检索的分支”误记为缓存命中（R4-NEW-3）",
            "total_upper_cny": "保留为观测计划费用，不能当上界；上界看 total_upper_structural_cny / worst_case_upper_cny",
            "requests_planned": "保留为观测计划请求数；上界看 requests_structural_upper / requests_worst_case",
        },
        "note": "zero-request plan; executable 只依赖结构上界、重试、累计请求与阶段余额；embedding 按官方 10x8192 上限预留，不按字节估 token",
    }


def _doc_codes(value: str) -> set[str] | None:
    codes = {part.strip() for part in str(value or "").split(",") if part.strip()}
    return codes or None


def subset_metadata(corpus: Path, documents: list[Any], skipped: list[dict[str, Any]]) -> dict[str, Any]:
    try:
        manifest = json.loads((corpus / "manifest.json").read_text(encoding="utf-8"))
        total = len(manifest.get("files") or [])
    except (OSError, ValueError):
        total = None
    return {
        "manifest_files": total,
        "selected_documents": len(documents),
        "excluded_count": len(skipped),
        "excluded": skipped,
        "priority": [],
        "version_aliases": dict(VAR_LOGICAL),
        "inactive_codes": sorted(INACTIVE_CODES),
        "special_codes_skipped": sorted(SKIP_CODES),
        "explicit_response_subset": True,
        "note": "The 13/13 offline result is on this selected subset; sensitive/boundary/scan/max_docs cuts are explicitly listed and are never silently counted as accepted corpus.",
    }


def command_offline(args: argparse.Namespace) -> int:
    if not args.questions:
        raise SystemExit("拒绝 offline：必须显式提供 --questions，避免默认复用开发题集")
    out_dir = Path(args.out)
    corpus = Path(args.corpus)
    conversations = load_questions(args.questions)
    selected, question_count = select_conversations(
        conversations,
        limit_conversations=args.limit,
        max_questions=args.max_questions,
    )
    documents, skipped = load_corpus(corpus, max_docs=args.max_docs, only_codes=_doc_codes(args.doc_codes))
    config = RagConfig(
        provider_mode="offline",
        data_dir=out_dir / "data",
        business_date=args.business_date,
        page_size=args.page_size,
        top_k=args.top_k,
        max_retries=args.max_retries,
        disable_query_embedding=bool(args.no_query_embedding),
        record_only=bool(args.record_only),
    )
    if args.index_plan_only:
        out_dir.mkdir(parents=True, exist_ok=True)
        # offline 计划没有 GO/账本，因此“阶段余额”本来就未知：只有显式 --stage-limit 才核对，
        # 不再用写死的 3.00 元冒充额度（S4 工程债 B）。
        offline_stage_remaining = (
            None
            if args.stage_limit is None
            else _finite_positive_cny(args.stage_limit, "--stage-limit", context="拒绝 plan")
        )
        plan = build_index_plan(
            documents,
            config=config,
            max_requests=max(0, int(args.max_requests or 0)),
            max_questions=question_count,
            stage_remaining_cny=offline_stage_remaining,
            query_embedding_requests=args.query_embedding_requests,
            chat_requests=args.chat_requests,
            question_texts=question_texts(selected),
            max_retries=args.max_retries,
            disable_query_embedding=bool(args.no_query_embedding),
            record_only=bool(args.record_only),
        )
        (out_dir / "index-plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(plan, ensure_ascii=False))
        return 0
    new_index, new_stats = build_new_index(
        documents, db_path=out_dir / "data" / "rag-offline.sqlite3", config=config
    )
    legacy = None
    legacy_stats = None
    try:
        if not args.no_old:
            legacy, legacy_stats = build_legacy(documents, db_path=out_dir / "data" / "legacy-offline.sqlite3")
        records = run_conversations(new_index, legacy, selected)
        summary = write_report(
            out_dir,
            mode="offline",
            config=config,
            new_stats=new_stats,
            legacy_stats=legacy_stats,
            skipped=skipped,
            records=records,
            budget_summary=None,
            subset=subset_metadata(corpus, documents, skipped),
            plan=None,
            execution=_execution_block(
                transport="offline",
                started_utc=datetime.now(timezone.utc).isoformat(),
                finished_utc=datetime.now(timezone.utc).isoformat(),
                error=None,
                plan=None,
                ledger_start=None,
                ledger_end=None,
                actuals=None,
                mock_counter=None,
                records=records,
                complete=True,
            ),
        )
    finally:
        new_index.close()
        if legacy is not None:
            legacy.close()
    print(json.dumps({key: summary[key] for key in ("mode", "questions", "new_hits", "old_hits", "old_questions")}, ensure_ascii=False))
    return 0


def _assert_fixed_file(path: Path | str, expected: Path, label: str) -> Path:
    """live 的唯一真源：不接受软链、相对替换或不同绝对路径。"""
    candidate = Path(path)
    if candidate.is_symlink() or expected.is_symlink():
        raise SystemExit(f"拒绝 live：{label} 不得是软链")
    if candidate.resolve() != expected.resolve():
        raise SystemExit(f"拒绝 live：{label} 必须是固定路径 {expected}")
    if not expected.is_file():
        raise SystemExit(f"拒绝 live：{label} 不存在 {expected}")
    return expected


def _finite_positive_cny(value: Any, label: str, *, context: str = "拒绝 live") -> float:
    """有限正数金额；bool/NaN/Inf/0/负数/非数字一律拒绝（不回落、不猜）。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SystemExit(f"{context}：{label} 必须是有限正数（当前 {type(value).__name__}）")
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise SystemExit(f"{context}：{label} 必须是有限正数")
    return number


def _go_stage_limit_cny(payload: Mapping[str, Any], stage: str) -> float:
    """GO 声明的本阶段额度：优先 ``scope.stage_limits_cny[stage]``，兼容旧 ``scope.stage_limit_cny``。

    取不到即拒绝（S4 工程债 B）：旧实现把额度硬限在 ``(0, 3.00]``，与当前 GO 的 18.4 不一致，
    且会把“取不到”静默回落成 3.00。这里只认 GO 自己写下的额度，不做任何默认值回落。
    """
    scope = payload.get("scope")
    if not isinstance(scope, Mapping):
        raise SystemExit("拒绝 live：GO scope 必须是对象")
    limits = scope.get("stage_limits_cny")
    if isinstance(limits, Mapping) and stage in limits:
        return _finite_positive_cny(limits[stage], f"GO scope.stage_limits_cny[{stage}]")
    legacy_stages = scope.get("stages")
    if isinstance(legacy_stages, Mapping) and stage in legacy_stages:
        return _finite_positive_cny(legacy_stages[stage], f"GO scope.stages[{stage}]")
    if "stage_limit_cny" in scope:
        return _finite_positive_cny(scope["stage_limit_cny"], "GO scope.stage_limit_cny")
    raise SystemExit(
        f"拒绝 live：GO 没有阶段 {stage} 的额度（需要 scope.stage_limits_cny[{stage}]）"
    )


def _budget_stage_allocation_cny(payload: Mapping[str, Any], stage: str) -> float:
    """共享 ``budget.json`` 的本阶段分配；缺失/非正数直接拒绝。

    注意 ``BudgetLedger`` 只在 budget 里**存在**该阶段时才取小，缺失时会静默沿用调用方额度；
    因此这里必须显式校验，否则“预算阶段缺失”会被当成“无限制”。
    """
    stages = payload.get("stages")
    if not isinstance(stages, Mapping) or stage not in stages:
        raise SystemExit(f"拒绝 live：共享预算没有阶段 {stage} 的分配（默认拒绝）")
    return _finite_positive_cny(stages[stage], f"共享预算 stages[{stage}]")


def _resolve_stage_limit_cny(
    *,
    go_payload: Mapping[str, Any],
    budget_payload: Mapping[str, Any],
    stage: str,
    requested: float | None,
) -> float:
    """阶段额度 = min(参数请求, GO 声明, 共享预算分配)；参数只能收窄，不能放大。"""
    candidates = [
        _go_stage_limit_cny(go_payload, stage),
        _budget_stage_allocation_cny(budget_payload, stage),
    ]
    if requested is not None:
        candidates.append(_finite_positive_cny(requested, "--stage-limit"))
    resolved = min(candidates)
    if not math.isfinite(resolved) or resolved <= 0:
        raise SystemExit("拒绝 live：收敛后的阶段额度不是有限正数")
    return resolved


def _load_budget_payload(path: Path) -> dict[str, Any]:
    """读取共享预算 JSON（只读）：结构不合法直接拒绝，不尝试修复或回落。"""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SystemExit(f"拒绝 live：共享预算不是合法 JSON（{type(exc).__name__}）") from exc
    if not isinstance(payload, dict):
        raise SystemExit("拒绝 live：共享预算顶层必须是对象")
    return payload


def _check_go_file(path: Path | None = None) -> dict[str, Any]:
    """固定路径 + 结构化授权；普通文档/任意字面串 GO 一律拒绝。"""
    target = GO_PATH if path is None else Path(path)
    if target.is_symlink() or GO_PATH.is_symlink():
        raise SystemExit("拒绝 live：GO 固定路径不得是软链")
    if target.resolve() != GO_PATH.resolve():
        raise SystemExit(f"拒绝 live：GO 必须是固定路径 {GO_PATH}")
    if not target.exists():
        raise SystemExit(f"拒绝 live：GO 文件不存在：{target}")
    if target.stat().st_size > 65536:
        raise SystemExit("拒绝 live：GO 文件过大")
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SystemExit(f"拒绝 live：GO 不是合法结构化授权 JSON：{type(exc).__name__}") from exc
    if not isinstance(payload, dict):
        raise SystemExit("拒绝 live：GO 顶层必须是对象")
    required = ("document", "stage", "authorization", "issued_by", "nonce", "issued_utc", "expires_utc", "scope")
    missing = [key for key in required if key not in payload]
    if missing:
        raise SystemExit(f"拒绝 live：GO 缺少字段 {missing}")
    if payload.get("document") != "S1-LIVE-GO" or payload.get("stage") != "S1-DEV":
        raise SystemExit("拒绝 live：GO 的 document/stage 不匹配")
    if not str(payload.get("authorization") or "").strip():
        raise SystemExit("拒绝 live：GO 未声明阶段授权")
    if not str(payload.get("issued_by") or "").strip() or len(str(payload.get("nonce") or "")) < 16:
        raise SystemExit("拒绝 live：GO 缺少签发人或一次性 nonce")
    try:
        expires = datetime.fromisoformat(str(payload["expires_utc"]).replace("Z", "+00:00"))
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise SystemExit("拒绝 live：GO expires_utc 不是 ISO 时间") from exc
    if expires <= datetime.now(timezone.utc):
        raise SystemExit("拒绝 live：GO 已过期")
    scope = payload.get("scope")
    if not isinstance(scope, dict):
        raise SystemExit("拒绝 live：GO scope 必须是对象")
    max_docs = scope.get("max_documents", scope.get("max_docs"))
    is_real_stage = str(payload.get("authorization") or "").strip() == "REAL-STAGE"
    max_requests = scope.get("max_requests", 0 if is_real_stage else None)
    max_questions = scope.get("max_questions", max_requests or 1)
    for key, value in (("max_documents/max_docs", max_docs), ("max_questions", max_questions)):
        if not isinstance(value, int) or value <= 0 or value > 1000:
            raise SystemExit(f"拒绝 live：GO scope.{key} 必须是 1..1000 的整数")
    if not isinstance(max_requests, int) or max_requests < 0 or max_requests > 1000:
        raise SystemExit("拒绝 live：GO scope.max_requests 必须是 0..1000 的整数（默认 0 禁止请求）")
    if not is_real_stage and max_requests <= 0:
        raise SystemExit("拒绝 live：非 REAL-STAGE 授权必须显式给出正数 max_requests")
    stages = scope.get("stages") or {}
    # S4 工程债 B：额度只取自 GO 自己声明的阶段额度，不再硬限 3.00 元、也不回落。
    stage_limit = _go_stage_limit_cny(payload, str(payload.get("stage") or ""))
    if not isinstance(stages, dict):
        raise SystemExit("拒绝 live：GO scope.stages 必须是对象")
    declared_ledger = str(payload.get("budget_ledger_path") or "").strip()
    if declared_ledger:
        _assert_fixed_file(declared_ledger, _FIXED_LEDGER, "GO budget_ledger_path")
    ledger_path = _assert_fixed_file(_FIXED_LEDGER, _FIXED_LEDGER, "共享账本")
    expected_hash = str(payload.get("budget_ledger_sha256") or (scope.get("ledger_sha256") if isinstance(scope, dict) else "") or "")
    actual_hash = hashlib.sha256(ledger_path.read_bytes()).hexdigest()
    if not expected_hash or expected_hash != actual_hash:
        raise SystemExit("拒绝 live：GO 未绑定当前共享账本哈希")
    payload = {**payload, "budget_ledger_path": str(ledger_path), "scope": {
        **scope, "max_documents": max_docs, "max_docs": max_docs,
        "max_requests": max_requests, "max_questions": max_questions,
        "stage_limit_cny": stage_limit,
    }}
    return payload


def _plan_only_live(args: argparse.Namespace) -> int:
    out_dir = Path(args.out)
    conversations = load_questions(args.questions) if args.questions and Path(args.questions).exists() else []
    selected, question_count = select_conversations(
        conversations, limit_conversations=args.limit, max_questions=args.max_questions
    )
    # S4 工程债 B：计划额度同样只能来自 GO + 共享预算（或显式 --stage-limit 收窄），
    # 不再回落到写死的 3.00 元；拿不到额度就拒绝，避免给出“可执行”的假计划。
    existing_requests = 0
    if args.ledger or args.budget:
        if not args.ledger or not args.budget:
            raise SystemExit("拒绝 plan：--ledger/--budget 必须成对给出")
        ledger_path = _assert_fixed_file(args.ledger, _FIXED_LEDGER, "--ledger")
        budget_path = _assert_fixed_file(args.budget, _FIXED_BUDGET, "--budget")
        go = _check_go_file()
        if str(args.stage).strip() != str(go["stage"]).strip():
            raise SystemExit(
                f"拒绝 live：GO stage {go['stage']!r} 与 --stage {args.stage!r} 不一致"
            )
        stage_limit = _resolve_stage_limit_cny(
            go_payload=go,
            budget_payload=_load_budget_payload(budget_path),
            stage=str(args.stage),
            requested=args.stage_limit,
        )
        ledger_summary = BudgetLedger(
            ledger_path,
            budget_path,
            stage=args.stage,
            stage_limit_cny=stage_limit,
            max_requests=max(1, int(args.max_requests or 1)),
        ).summary()
        stage_remaining = ledger_summary.stage_remaining_cny
        existing_requests = ledger_summary.reservation_count
    elif args.stage_limit is not None:
        # 纯结构估算：没有任何授权文件，只按调用方显式给出的额度核对余额。
        stage_limit = _finite_positive_cny(args.stage_limit, "--stage-limit")
        stage_remaining = stage_limit
    else:
        raise SystemExit(
            "拒绝 live：--index-plan-only 必须给出 --stage-limit 或 --ledger/--budget"
            "（不再回落到 3.00 元）"
        )
    config = RagConfig.from_env(
        provider_mode="offline",
        data_dir=out_dir / "data",
        business_date=args.business_date,
        # RagConfig 只接受正数额度；这里给的是“阶段额度”，余额（可能为 0）只进计划阻断判断。
        stage_limit_cny=stage_limit,
    )
    config = RagConfig(
        **{
            **config.__dict__,
            "page_size": args.page_size,
            "top_k": args.top_k,
            "max_retries": args.max_retries,
            "disable_query_embedding": bool(args.no_query_embedding),
            "record_only": bool(args.record_only),
        }
    )
    documents, _skipped = load_corpus(Path(args.corpus), max_docs=args.max_docs, only_codes=_doc_codes(args.doc_codes))
    trace_counts = trace_request_counts(documents, selected, config, out_dir / "trace") if selected else None
    plan = build_index_plan(
        documents,
        config=config,
        max_requests=max(0, int(args.max_requests or 0)),
        max_questions=question_count,
        stage_remaining_cny=stage_remaining,
        query_embedding_requests=args.query_embedding_requests,
        chat_requests=args.chat_requests,
        question_texts=question_texts(selected),
        existing_requests=existing_requests,
        max_retries=args.max_retries,
        trace_counts=trace_counts,
        disable_query_embedding=bool(args.no_query_embedding),
        record_only=bool(args.record_only),
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "index-plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(plan, ensure_ascii=False))
    return 0


def command_live(args: argparse.Namespace) -> int:
    if args.index_plan_only:
        return _plan_only_live(args)
    if not args.ledger or not args.budget:
        raise SystemExit("拒绝 live：必须提供 --ledger 与 --budget")
    ledger_path = _assert_fixed_file(args.ledger, _FIXED_LEDGER, "--ledger")
    budget_path = _assert_fixed_file(args.budget, _FIXED_BUDGET, "--budget")
    go = _check_go_file()
    scope = go["scope"]
    if str(args.stage).strip() != str(go["stage"]).strip():
        raise SystemExit(f"拒绝 live：GO stage {go['stage']!r} 与 --stage {args.stage!r} 不一致")
    # S4 工程债 B：阶段额度 = min(参数请求, GO 声明额度, 共享预算阶段分配)。
    # 旧实现硬限 (0, 3.00]，与当前 GO 的 18.4 不一致；这里只收窄，取不到即拒绝。
    args.stage_limit = _resolve_stage_limit_cny(
        go_payload=go,
        budget_payload=_load_budget_payload(budget_path),
        stage=str(args.stage),
        requested=args.stage_limit,
    )
    args.max_docs = min(args.max_docs, int(scope["max_documents"])) if args.max_docs else int(scope["max_documents"])
    args.max_questions = min(
        int(args.max_questions or scope["max_questions"]),
        int(scope["max_questions"]),
    )
    # 默认拒绝：省略/0/负数都不得回落到 GO scope 额度（R5D-1b）。
    if args.max_requests is None:
        raise SystemExit("拒绝 live：必须显式给出 --max-requests 正数（缺省即默认禁止真实请求）")
    try:
        requested_requests = int(args.max_requests)
    except (TypeError, ValueError) as exc:
        raise SystemExit("拒绝 live：max-requests 必须是正整数") from exc
    if requested_requests <= 0:
        raise SystemExit("拒绝 live：max-requests 必须为正数（0 和负数都表示拒绝真实请求）")
    args.max_requests = min(requested_requests, int(scope["max_requests"]))
    if args.max_requests <= 0:
        raise SystemExit("拒绝 live：GO scope.max_requests 必须为正数（0 表示禁止真实请求）")
    if not args.questions or not Path(args.questions).exists():
        raise SystemExit("拒绝 live：必须显式提供独立题集 --questions")
    run_id = uuid.uuid4().hex
    ledger = BudgetLedger(
        ledger_path,
        budget_path,
        stage=args.stage,
        stage_limit_cny=args.stage_limit,
        max_requests=args.max_requests,
        run_id=run_id,
    )
    summary = ledger.summary()
    if summary.stage_remaining_cny <= 0:
        raise SystemExit("拒绝 live：阶段预算剩余为 0")
    out_dir = Path(args.out)
    documents, skipped = load_corpus(Path(args.corpus), max_docs=args.max_docs, only_codes=_doc_codes(args.doc_codes))
    config = RagConfig.from_env(
        provider_mode="live",
        data_dir=out_dir / "data",
        business_date=args.business_date,
        budget_ledger_path=ledger_path,
        budget_json_path=budget_path,
        stage_limit_cny=args.stage_limit,
    )
    config = RagConfig(
        **{
            **config.__dict__,
            "stage": args.stage,
            "page_size": args.page_size,
            "top_k": args.top_k,
            "max_retries": args.max_retries,
            "disable_query_embedding": bool(args.no_query_embedding),
            "record_only": bool(args.record_only),
        }
    )
    try:
        config.require_live_credentials()
    except Exception as exc:
        raise SystemExit(f"拒绝 live：{getattr(exc, 'message', str(exc))}") from exc
    all_conversations = load_questions(args.questions)
    selected_conversations, question_count = select_conversations(
        all_conversations, limit_conversations=args.limit, max_questions=args.max_questions
    )
    started_utc = datetime.now(timezone.utc).isoformat()
    ledger_start = _ledger_snapshot(ledger_path)
    trace_counts = None
    if args.trace_observed:
        trace_counts = trace_request_counts(documents, selected_conversations, config, out_dir / "trace")
    # 发 HTTP 之前先用结构上界核对 GO / 预算 / 累计请求闸门。
    plan = build_index_plan(
        documents,
        config=config,
        max_requests=args.max_requests,
        max_questions=question_count,
        stage_remaining_cny=summary.stage_remaining_cny,
        question_texts=question_texts(selected_conversations),
        existing_requests=summary.reservation_count,
        max_retries=args.max_retries,
        trace_counts=trace_counts,
        disable_query_embedding=bool(args.no_query_embedding),
        record_only=bool(args.record_only),
    )
    (out_dir).mkdir(parents=True, exist_ok=True)
    (out_dir / "index-plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not plan["executable"]:
        execution = _execution_block(
            transport=args.transport,
            started_utc=started_utc,
            finished_utc=datetime.now(timezone.utc).isoformat(),
            error="PLAN_NOT_EXECUTABLE",
            plan=plan,
            ledger_start=ledger_start,
            ledger_end=_ledger_snapshot(ledger_path),
            actuals=_actuals_from_events([]),
            mock_counter={} if args.transport == "mock" else None,
            records=[],
            complete=False,
            post_counters={"attempts": {}, "outcomes": {}},
            run_id=run_id,
        )
        write_report(
            out_dir,
            mode="live",
            config=config,
            new_stats={"documents": len(documents), "units": 0, "chunks": plan.get("chunks", 0)},
            legacy_stats=None,
            skipped=skipped,
            records=[],
            budget_summary=summary.as_dict(),
            subset=subset_metadata(Path(args.corpus), documents, skipped),
            plan=plan,
            execution=execution,
        )
        raise SystemExit(
            "拒绝 live：结构上界未通过闸门 " + "；".join(str(reason) for reason in plan["blocked_reasons"])
        )
    from mktkb.rag import providers as providers_module

    providers_module.reset_post_counters()
    mock_counter: dict[str, int] | None = None
    patches: list = []
    if args.transport == "mock":
        mock_counter = {}
        _transport, patches = _install_mock_transport(config, mock_counter)
    records: list[dict[str, Any]] = []
    new_stats: dict[str, Any] = {}
    legacy_stats: dict[str, Any] | None = None
    error: str | None = None
    new_index = None
    legacy = None
    try:
        new_index, new_stats = build_new_index(
            documents,
            db_path=out_dir / "data" / "rag-live.sqlite3",
            config=config,
            budget=ledger,
        )
        if not args.no_old:
            legacy, legacy_stats = build_legacy(documents, db_path=out_dir / "data" / "legacy-live.sqlite3")
        records = run_conversations(new_index, legacy, selected_conversations)
    except BaseException as exc:  # 失败/中断也必须落可审计报告，保留已消耗费用
        error = f"{type(exc).__name__}: {getattr(exc, 'message', str(exc))}"
        raise
    finally:
        if new_index is not None:
            new_index.close()
        if legacy is not None:
            legacy.close()
        _restore_patches(patches)
        ledger_end = _ledger_snapshot(ledger_path)
        delta_events = list(ledger_end.get("events") or [])[int(ledger_start.get("count") or 0) :]
        own_events = [event for event in delta_events if event.get("run_id") == run_id]
        execution = _execution_block(
            transport=args.transport,
            started_utc=started_utc,
            finished_utc=datetime.now(timezone.utc).isoformat(),
            error=error,
            plan=plan,
            ledger_start=ledger_start,
            ledger_end=ledger_end,
            actuals=_actuals_from_events(own_events),
            mock_counter=mock_counter,
            records=records,
            complete=error is None,
            own_events=own_events,
            post_counters=providers_module.post_counters(),
            run_id=run_id,
        )
        reserved_rows = [e for e in delta_events if e.get("event") == "reserved"]
        execution["self_attribution"] = {
            "run_id": run_id,
            "own_reservations": len([e for e in own_events if e.get("event") == "reserved"]),
            "ledger_delta_reservations": len(reserved_rows),
            "foreign_reservations_in_window": len(
                [e for e in reserved_rows if e.get("run_id") not in (None, run_id)]
            ),
            "legacy_rows_without_run_id": len(
                [e for e in reserved_rows if e.get("run_id") is None]
            ),
            "basis": "本轮归属取账本 reserved 行锁内写入的 run_id（含 reserve 未返回/未结算行）；旧行无 run_id 单列",
        }
        summary_after = ledger.summary().as_dict()
        write_report(
            out_dir,
            mode="live",
            config=config,
            new_stats=new_stats,
            legacy_stats=legacy_stats,
            skipped=skipped,
            records=records,
            budget_summary={"start": summary.as_dict(), "end": summary_after},
            subset=subset_metadata(Path(args.corpus), documents, skipped),
            plan=plan,
            execution=execution,
        )
    print(
        json.dumps(
            {
                "mode": "live",
                "transport": args.transport,
                "questions": len(records),
                "new_hits": sum(1 for item in records if item["new"]["checks"]["hit"]),
                "structural_upper_requests": plan["requests_structural_upper"],
                "actual_attempts": execution["plan_vs_actual"]["actual_attempts"],
            },
            ensure_ascii=False,
        )
    )
    return 0


def command_capacity(args: argparse.Namespace) -> int:
    """本地替身容量测量：100 文档/1 万记录/3 并发；不冒充真实验收。"""
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    db_path = out_dir / "data" / "rag-capacity-offline.sqlite3"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    config = RagConfig(data_dir=out_dir / "data", business_date="2026-10-28", top_k=8, page_size=10)
    index = RagIndex(db_path, config=config)
    docs = args.docs
    rows_per_doc = args.rows
    started = time.monotonic()
    tracemalloc.start()
    for doc_number in range(docs):
        code = f"CAP-{doc_number:03d}"
        spec = DocumentSpec(
            doc_id=code,
            logical_id=code,
            source_path=f"capacity/{code}.xlsx",
            title=f"容量样本{doc_number:03d}",
            file_kind="xlsx",
            version_id=f"{code}-v1",
            version_label="当前",
            sha256=hashlib.sha256(code.encode()).hexdigest(),
            business_date="2026-10-28",
        )
        units = [
            AtomicUnit(
                unit_id=f"{code}-{row}",
                doc_id=code,
                version_id=spec.version_id,
                kind="table_row",
                ordinal=row,
                unit_key=f"sheet:容量:row:{row + 7}",
                text="",
                fields={
                    "标识": f"{code}-R{row:03d}",
                    "门店": f"容量门店{doc_number:03d}",
                    "物品": f"容量物品{row:03d}",
                    "位置": f"容量位置{row:03d}",
                    "数量": row,
                },
                sheet="容量",
                locator={"sheet": "容量", "row": row + 7, "header_row": 6},
                header_row=6,
                row_number=row + 7,
                title=spec.title,
            )
            for row in range(rows_per_doc)
        ]
        index.add_document(spec, units, embed=True)
    build_seconds = round(time.monotonic() - started, 3)
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    db_bytes = db_path.stat().st_size
    # 单用户 20 问 + 3 并发各 20 问，查询同一个精确记录族。
    questions = [
        f"容量门店{(number % docs):03d}的容量物品{(number % rows_per_doc):03d}在哪里？"
        for number in range(args.queries)
    ]

    def timed_ask(question: str, suffix: str) -> float:
        begin = time.monotonic()
        answer = index.ask(question, user_id=f"cap-{suffix}", conversation_id=f"cap-{suffix}")
        elapsed = (time.monotonic() - begin) * 1000
        if answer.kind != "answer":
            raise RuntimeError(f"capacity query failed: {question} -> {answer.kind} {answer.text[:60]}")
        return elapsed

    single = [timed_ask(question, f"s{i}") for i, question in enumerate(questions)]
    concurrent_latencies: list[float] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        futures = [
            executor.submit(timed_ask, question, f"c{i}")
            for i, question in enumerate(questions)
        ]
        for future in concurrent.futures.as_completed(futures):
            concurrent_latencies.append(future.result())

    def percentile(values: list[float], ratio: float) -> float:
        ordered = sorted(values)
        if not ordered:
            return 0.0
        position = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * ratio))))
        return round(ordered[position], 2)

    payload = {
        "mode": "offline-mock-capacity",
        "mock": True,
        "real_calls": 0,
        "not_acceptance": True,
        "spec": {
            "documents": docs,
            "rows_per_document": rows_per_doc,
            "records": docs * rows_per_doc,
            "concurrency": args.concurrency,
            "embedding_provider": "mock",
            "embedding_dimensions": config.embedding_dimensions,
        },
        "build": {
            "seconds": build_seconds,
            "db_bytes": db_bytes,
            "peak_python_bytes": peak,
            "stats": index.stats(),
        },
        "latency_ms": {
            "single_p50": percentile(single, 0.5),
            "single_p95": percentile(single, 0.95),
            "single_max": round(max(single), 2) if single else 0.0,
            "concurrent_p50": percentile(concurrent_latencies, 0.5),
            "concurrent_p95": percentile(concurrent_latencies, 0.95),
            "concurrent_max": round(max(concurrent_latencies), 2) if concurrent_latencies else 0.0,
        },
        "note": "本地替身容量，不是真实 embedding/rerank、不是服务器、不是 100 份真实资料验收。",
    }
    index.close()
    (out_dir / "capacity-offline.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    lines = [
        "# 本地替身容量测量（非验收）",
        "",
        f"- {docs} 文档 / {docs * rows_per_doc} 记录 / {args.concurrency} 并发；embedding=mock 1024 维",
        f"- 建库：{build_seconds}s；SQLite：{db_bytes} 字节；Python 峰值：{peak} 字节",
        f"- 单用户 p50/p95/max：{payload['latency_ms']['single_p50']} / {payload['latency_ms']['single_p95']} / {payload['latency_ms']['single_max']} ms",
        f"- 3 并发 p50/p95/max：{payload['latency_ms']['concurrent_p50']} / {payload['latency_ms']['concurrent_p95']} / {payload['latency_ms']['concurrent_max']} ms",
        "",
        "这不是真实模型效果、不是服务器容量、不是 100 份真实资料验收；真实阶段仍需经理 GO 后单独执行。",
    ]
    (out_dir / "capacity-offline.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"mode": payload["mode"], "records": docs * rows_per_doc, "build_seconds": build_seconds, "latency": payload["latency_ms"]}, ensure_ascii=False))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="LOCAL-R1/S1 隔离 RAG 实验入口")
    sub = parser.add_subparsers(dest="command", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--corpus", default=str(ROOT / "corpus" / "enterprise-20261101"))
    common.add_argument("--questions", default=None, help="独立题集路径；offline/live 必须显式提供")
    common.add_argument("--out", default=str(Path.cwd() / "rag-experiment-out"), help="本次实验输出目录；默认在调用者当前目录")
    common.add_argument("--business-date", default="2026-10-28")
    common.add_argument("--max-docs", type=int, default=None)
    common.add_argument("--page-size", type=int, default=10)
    common.add_argument("--top-k", type=int, default=8)
    common.add_argument("--no-old", action="store_true")
    common.add_argument("--limit", type=int, default=None, help="最多会话数（不是问题数）；缺省全部")
    common.add_argument("--max-questions", type=int, default=None, help="实际问题数硬上限；跨会话所有 turn 合计")
    common.add_argument("--max-requests", type=int, default=None,
                        help="硬请求数上限；live 执行必须显式给出正数，省略/0/负数一律拒绝真实请求（plan-only 不受限）")
    common.add_argument("--doc-codes", default="", help="逗号分隔的资料代码白名单，如 E11")
    common.add_argument("--query-embedding-requests", type=int, default=None,
                        help="计划中的查询 embedding 请求数；缺省等于计划问题数")
    common.add_argument("--no-query-embedding", action="store_true",
                        help="运行时强制关闭查询 embedding 面（retrieval 直接返回 QUERY_EMBEDDING_DISABLED）")
    common.add_argument("--record-only", action="store_true",
                        help="运行时强制只答记录型问题；正文/文档型问题在构造 chat provider 前拒答")
    common.add_argument("--chat-requests", type=int, default=None,
                        help="计划中的 chat 请求数；缺省按有 chat 模型的题目数计")
    common.add_argument("--max-retries", type=int, default=2,
                        help="每个逻辑请求的最大重试次数；plan 按 1+重试 计最坏尝试")
    common.add_argument("--stage-limit", type=float, default=None,
                        help="可选：只能把阶段额度收窄到这里；最终额度=min(本参数, GO 阶段额度, 共享预算阶段分配)。"
                             "省略表示不收窄（不是 3.00 元默认值）")
    common.add_argument("--index-plan-only", nargs="?", const=True, default=False,
                        help="零请求预核算块数/批数/费用上界")

    offline = sub.add_parser("offline", parents=[common], help="离线替身实验，0 真实调用")
    offline.set_defaults(func=command_offline)

    live = sub.add_parser("live", parents=[common], help="经理 GO 后的真实阶段实验")
    live.add_argument("--ledger")
    live.add_argument("--budget")
    live.add_argument("--stage", default="S1-DEV")
    live.add_argument("--transport", choices=("real", "mock"), default="real",
                      help="real=真实网络；mock=本工具注入 MockTransport 并在报告单列 mock_http_attempts")
    live.add_argument("--trace-observed", action="store_true",
                      help="额外跑一次零 HTTP 离线轨迹，仅用于观测对照（不参与上界）")
    live.set_defaults(func=command_live)

    capacity = sub.add_parser("capacity", parents=[common], help="本地替身 100 文档/1 万记录/3 并发测量（非验收）")
    capacity.add_argument("--docs", type=int, default=100)
    capacity.add_argument("--rows", type=int, default=100)
    capacity.add_argument("--queries", type=int, default=20)
    capacity.add_argument("--concurrency", type=int, default=3)
    capacity.set_defaults(func=command_capacity)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())

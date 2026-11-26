"""C1-P2 独立验收：隔离 import 探针。

用 stub `mktkb` 包避免执行 mktkb/__init__.py（它会 import main/providers）；
只 import 新模块，跑一个最小可证明 envelope，并断言未加载
p2_hard_evidence / p2_evidence_capture / p2_evidence_io / mktkb.providers。

sitepython 的 netguard 已由 sitecustomize 安装；本脚本不发起任何网络。
"""

from __future__ import annotations

import json
import sys
import types

SRC = r"D:\GPT项目\市场部AI知识库\backend\src"
OUT = r"D:\GPT项目\市场部AI知识库\docs\reports\OBS-EVAL\P2\Q1A-EVAL-REPAIR\c1-1\p2\independent\14c-isolated-import.json"


def main() -> int:
    sys.path.insert(0, SRC)
    pkg = types.ModuleType("mktkb")
    pkg.__path__ = [SRC + "/mktkb"]
    sys.modules["mktkb"] = pkg

    from mktkb.evaluation import p2_empty_scope_proof as proof

    text = proof.COPY["LEGACY_NO_EVIDENCE"].template
    events = [
        {
            "seq": 1,
            "kind": "claim_observed",
            "payload": {
                "request_id": "req-1",
                "conversation_id": "conv-1",
                "attempt": 1,
                "authenticated_user_id": "user-1",
                "owner_user_id": "user-1",
                "user_message_id": "msg-user",
                "user_message_seq": 1,
                "initial_revision": 1,
                "replay": False,
            },
        },
        {
            "seq": 2,
            "kind": "context_observed",
            "payload": {"request_id": "req-1", "count": 0, "empty": True},
        },
        {
            "seq": 3,
            "kind": "plan_observed",
            "payload": {
                "request_id": "req-1",
                "path": "legacy",
                "mode": "record",
                "filters": {},
                "terms": [],
                "as_of": None,
                "include_future": False,
                "enumerate": False,
                "clarification": False,
                "state_keys": [],
                "state_as_of": None,
                "state_pending_slot": None,
                "state_last_kind": None,
            },
        },
        {
            "seq": 4,
            "kind": "retrieval_observed",
            "payload": {
                "request_id": "req-1",
                "scope": "legacy_retrieve_initial",
                "unit_ids": [],
                "candidate": False,
                "truncated": False,
                "empty": True,
            },
        },
        {
            "seq": 5,
            "kind": "answer_result",
            "payload": {
                "request_id": "req-1",
                "kind": "not_found",
                "text": text,
                "source_ids": [],
                "candidates": 0,
                "conflicts": 0,
                "missing_fields": [],
                "error_code": None,
                "reason": None,
            },
        },
        {
            "seq": 6,
            "kind": "commit_observed",
            "payload": {
                "request_id": "req-1",
                "message_id": "msg-assistant",
                "assistant_seq": 2,
                "kind": "not_found",
                "requested_kind": "not_found",
                "text": text,
                "source_ids": [],
                "revision_before": 1,
                "revision_after": 1,
                "knowledge_changed": False,
                "error_code": None,
            },
        },
    ]
    envelope = {
        "schema_version": "p2-hard-evidence-capture/v0.1",
        "fixture_kind": "local_mock",
        "bindings": {},
        "adapter_components": {},
        "turn": {
            "turn_index": 0,
            "client_request_id": "client-1",
            "conversation_id": "conv-1",
            "authenticated_user_id": "user-1",
            "question_sha256": "0" * 64,
            "http_status": 200,
            "timed_out": False,
            "started_utc": "2026-11-13T00:00:00+00:00",
            "captured_utc": "2026-11-13T00:00:01+00:00",
            "pre_revision": 1,
            "post_revision": 1,
            "capture_revision": 1,
        },
        "capture": {
            "schema_version": "p2-hard-evidence-capture/v0.1",
            "sink_id": "sink-1",
            "status": "ok",
            "seq": 6,
            "event_count": 6,
            "events": events,
            "errors": [],
        },
        "db_projection": {
            "schema_version": "p2-hard-evidence-capture-db/v0.1",
            "snapshot_utc": "2026-11-13T00:00:01+00:00",
            "pre_revision": 1,
            "capture_revision": 1,
            "conversation": {
                "id": "conv-1",
                "owner_user_id": "user-1",
                "deleted": False,
                "deleted_at": None,
                "created_at": "2026-11-13T00:00:00+00:00",
                "updated_at": "2026-11-13T00:00:00+00:00",
            },
            "request": {
                "id": "req-1",
                "conversation_id": "conv-1",
                "user_id": "user-1",
                "status": "succeeded",
                "attempt": 1,
                "payload_sha256": "0" * 64,
                "user_message_id": "msg-user",
                "result_message_id": "msg-assistant",
                "error_code": None,
                "error_retryable": False,
                "created_at": "2026-11-13T00:00:00+00:00",
                "started_at": "2026-11-13T00:00:00+00:00",
                "finished_at": "2026-11-13T00:00:01+00:00",
            },
            "messages": [
                {
                    "id": "msg-user",
                    "conversation_id": "conv-1",
                    "owner_user_id": "user-1",
                    "role": "user",
                    "seq": 1,
                    "kind": None,
                    "revision": 1,
                    "error_code": None,
                    "text": "q",
                    "created_at": "2026-11-13T00:00:00+00:00",
                },
                {
                    "id": "msg-assistant",
                    "conversation_id": "conv-1",
                    "owner_user_id": "user-1",
                    "role": "assistant",
                    "seq": 2,
                    "kind": "not_found",
                    "revision": 1,
                    "error_code": None,
                    "text": text,
                    "created_at": "2026-11-13T00:00:01+00:00",
                },
            ],
            "message_sources": [],
            "units": [],
            "unresolved_unit_ids": [],
            "query_states": [],
            "query_states_available": True,
            "rag_business_date": "2026-11-13",
            "truncations": [],
            "errors": [],
        },
        "completeness": {"status": "complete"},
        "sealed": {},
    }
    result = proof.prove_empty_use_scope(envelope)
    bad = sorted(
        name
        for name in sys.modules
        if name.startswith("mktkb.providers")
        or name
        in {
            "mktkb.evaluation.p2_hard_evidence",
            "mktkb.evaluation.p2_evidence_capture",
            "mktkb.evaluation.p2_evidence_io",
        }
    )
    payload = {
        "proven": result.proven,
        "code": result.code,
        "shape": result.shape,
        "forbidden_modules_loaded": bad,
        "module_loaded": "mktkb.evaluation.p2_empty_scope_proof" in sys.modules,
    }
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1)
    print(json.dumps(payload, ensure_ascii=False))
    return 0 if result.proven and not bad else 3


if __name__ == "__main__":
    raise SystemExit(main())

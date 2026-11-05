"""T003c 独立验收：真实 QA POST（legacy 产品路径）trace 观察探针。

验证 PM 授权的 test_middleware.py 断言替换不是空转：真实 QA POST 的 trace
确实包含 recall/fuse/hard_filter Span，且没有破坏 T003b 的既有字段断言
（request_id=None / outcome=None / status=incomplete / content_mode=hash）。

用法：python probe_middleware.py <report.json> <work_root>
"""

from __future__ import annotations

import json
import sys
import traceback
import uuid
from pathlib import Path

REPORT: list[dict] = []
RECORD_Q = "滨江店的宣传海报放在哪里？"


def main() -> int:
    out_path = Path(sys.argv[1])
    work = Path(sys.argv[2])
    work.mkdir(parents=True, exist_ok=True)
    tests_dir = Path(__file__).resolve().parents[5] / "backend" / "tests"
    # parents: .../T003c -> verify -> evidence -> P0 -> OBS-EVAL -> reports -> docs -> repo root
    repo_root = Path(__file__).resolve().parents[7]
    tests_dir = repo_root / "backend" / "tests"
    sys.path.insert(0, str(tests_dir))
    sys.path.insert(0, str(repo_root))

    import sqlite3

    from conftest import ORIGIN
    from mktkb.config import Settings
    from mktkb.main import create_app
    from observability.conftest import ask_question, create_conversation, open_session

    data_dir = work / ("mw-" + uuid.uuid4().hex) / "app"
    trace_db = data_dir.parent / "observability" / "qa-traces.sqlite3"
    settings = Settings(
        _env_file=None,
        data_dir=data_dir,
        cookie_secure=False,
        csrf_secret="unit-test-csrf-secret-0123456789",
        admin_password="AdminPass-1",
        employee_password="EmployeePass-1",
        trusted_origins=[ORIGIN],
        bcrypt_rounds=4,
        session_ttl_seconds=3600,
        trace_enabled=True,
        trace_db_path=trace_db,
        trace_content_mode="hash",
        trace_hmac_key=None,
    )
    app = create_app(settings)
    try:
        session = open_session(app, "employee", "EmployeePass-1")
        conversation_id = create_conversation(session)
        response = ask_question(session, conversation_id)
        assert response.status_code == 200, response.text
        trace_id = response.headers["X-Trace-ID"]
        http_request_id = response.headers["X-Request-ID"]
        trace, spans = app.state.trace_repo.get(trace_id)
        body = response.json()
        detail = {
            "trace_id": trace_id,
            "http_request_id": http_request_id,
            "trace": {
                "request_id": trace.request_id,
                "path": trace.path,
                "outcome_kind": trace.outcome_kind,
                "status": trace.status,
                "content_mode": trace.content_mode,
                "question_hash": trace.question_hash,
                "replayed": trace.replayed,
                "attempt": trace.attempt,
                "mode": trace.mode,
                "scope": trace.scope,
            },
            "span_names": [span.name for span in spans],
            "spans": [
                {
                    "name": span.name,
                    "parent": span.parent_span_id,
                    "status": span.status,
                    "attributes": json.loads(span.attributes_json or "{}"),
                }
                for span in spans
            ],
            "response_body_keys": sorted(body),
            "response_kind": body.get("kind"),
            "response_text": body.get("text"),
        }
        names = set(detail["span_names"])
        checks = {
            "core_spans_present": {"recall", "fuse", "hard_filter"} <= names,
            "not_empty": bool(spans),
            "request_id_none": trace.request_id is None,
            "outcome_none": trace.outcome_kind is None,
            "status_incomplete": trace.status == "incomplete",
            "content_mode_hash": trace.content_mode == "hash",
            "question_hash_none": trace.question_hash is None,
            "one_trace_row": _count_rows(trace_db) == 1,
            "no_question_text_in_trace_db": RECORD_Q not in _read_trace_db(trace_db),
            "response_body_shape": isinstance(body, dict) and "kind" in body and "text" in body,
        }
        detail["checks"] = checks
        REPORT.append({"ok": all(checks.values()), "detail": detail})
        print(json.dumps(checks, ensure_ascii=False))
    except Exception as exc:  # noqa: BLE001
        REPORT.append({"ok": False, "error": f"{type(exc).__name__}: {exc}",
                       "traceback": traceback.format_exc()})
        print("FAIL", exc)
    finally:
        repo = getattr(app.state, "trace_repo", None)
        if repo is not None:
            repo.close()
        qa = getattr(app.state, "qa", None)
        if qa is not None:
            qa.close()
        app.state.db.dispose()
    ok = all(item["ok"] for item in REPORT)
    out_path.write_text(
        json.dumps({"ok": ok, "results": REPORT}, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print("RESULT", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def _read_trace_db(path: Path) -> str:
    raw = b""
    for candidate in (path, Path(str(path) + "-wal"), Path(str(path) + "-shm")):
        if candidate.exists():
            raw += candidate.read_bytes()
    return raw.decode("utf-8", errors="ignore")


def _count_rows(path: Path) -> int:
    if not path.exists():
        return 0
    import sqlite3

    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        return int(connection.execute("SELECT COUNT(*) FROM traces").fetchone()[0])
    finally:
        connection.close()


if __name__ == "__main__":
    raise SystemExit(main())

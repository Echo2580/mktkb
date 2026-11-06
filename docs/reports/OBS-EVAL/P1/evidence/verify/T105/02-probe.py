"""T105 independent verification probe (not a deliverable, not the developer's tests).

Drives the real HTTP product path with a controlled model gateway and an isolated
temporary data dir. No network, no .env, no real model/embedding/rerank/OCR.

Scenarios (handoff §6 + re-verify prompt item 6):
  S1  location context -> "那个海报呢" answers location only
  S2  quantity context -> only quantity
  S3  price context    -> only price
  S4  spec context     -> only spec
  S5  no context       -> clarification, no field values
  S6  explicit enumeration ("都列出来") keeps pagination
  S7  "第2页" after enumeration keeps pagination (must not be hijacked)
  S8  explicit "把那个海报的位置列出来" keeps enumeration
  S9  "那个海报的全部信息" (explicit 全部) keeps enumeration
  S10 "刚才那个呢" pure anaphor inherits field
  S11 "前面那个呢" pure anaphor inherits field (§10 fix 2)
  S12 "那个呢" no entity -> referent clarification
  S13 "这个呢" alternate anaphor
  S14 "那家呢" alternate anaphor
  S15 "那个海报的打印材质呢" new-content followup: no full dump, no over-clarify
  S16 "那个海报的陈列要求呢" new-content follow-up (policy word guard): same

Run: .\.venv\Scripts\python.exe -B docs\reports\OBS-EVAL\P1\evidence\verify\T105\02-probe.py
Writes JSON observations to backend\.pytest-tmp\T105-verify\probe-results.json.
"""

from __future__ import annotations

import json
import sys
import tempfile
import uuid
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(r"D:\GPT项目\市场部AI知识库")
sys.path.insert(0, str(ROOT / "backend" / "src"))
sys.path.insert(0, str(ROOT / "backend" / "tests"))

import openpyxl  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import conftest  # noqa: E402
from mktkb.config import Settings  # noqa: E402
from mktkb.documents.lifecycle import get_revision  # noqa: E402
from mktkb.ingestion.worker import run_one_job  # noqa: E402
from mktkb.main import create_app  # noqa: E402

HEADERS = ["标识", "门店", "物品", "别名", "位置", "数量", "参考供价", "规格型号"]
ROWS = [
    ["QF02", "城西店", "宣传海报", "海报", "C区2号货架第一层", 20, 2.6, "A2 铜版纸 157g"],
    ["QF01", "城东店", "宣传海报", "海报", "B区1号货架第二层", 40, 2.6, "A2 铜版纸 157g"],
    ["QF03", "城南店", "宣传海报", "海报", "C区1号货架第一层", 11, 2.6, "A2 铜版纸 157g"],
    ["QF04", "城北店", "宣传海报", "海报", "C区3号货架第一层", 12, 2.6, "A2 铜版纸 157g"],
    ["QF05", "滨江店", "宣传海报", "海报", "店内外侧", 13, 2.6, "A2 铜版纸 157g"],
    ["QF06", "湖滨店", "宣传海报", "海报", "入口左侧", 14, 2.6, "A2 铜版纸 157g"],
    ["QF07", "高新店", "宣传海报", "海报", "入口右侧", 15, 2.6, "A2 铜版纸 157g"],
    ["QF08", "经开店", "宣传海报", "海报", "收银台旁", 16, 2.6, "A2 铜版纸 157g"],
    ["QF09", "临港店", "宣传海报", "海报", "服务台旁", 17, 2.6, "A2 铜版纸 157g"],
    ["QF10", "中心店", "宣传海报", "海报", "中庭立柱", 18, 2.6, "A2 铜版纸 157g"],
    ["QF11", "东湖店", "宣传海报", "海报", "东侧墙面", 19, 2.6, "A2 铜版纸 157g"],
    ["QF12", "西湖店", "宣传海报", "海报", "西侧墙面", 21, 2.6, "A2 铜版纸 157g"],
]
# Values that must never leak into a follow-up that only asked one field.
LOC = "C区2号货架第一层"
SPEC = "A2 铜版纸 157g"
PRICE = "2.6"
QTY = "20"
IDENT = "QF02"


def _xlsx(path: Path) -> Path:
    workbook = openpyxl.Workbook()
    worksheet = workbook.active
    worksheet.title = "物品位置"
    worksheet.cell(row=1, column=1, value="T105 独立验收夹具")
    for column, header in enumerate(HEADERS, start=1):
        worksheet.cell(row=3, column=column, value=header)
    for offset, row in enumerate(ROWS):
        for column, value in enumerate(row, start=1):
            worksheet.cell(row=4 + offset, column=column, value=value)
    workbook.save(path)
    return path


class EchoGateway:
    """Controlled substitute: echoes evidence only; never a business answer."""

    def __init__(self) -> None:
        self.calls = 0

    async def complete(self, request, *, timeout_seconds: float):
        self.calls += 1
        from mktkb.providers.types import CompletionOutput

        if request.purpose == "query_expansion":
            return CompletionOutput(text="expansion", query_terms=())
        parts = []
        for item in request.evidence[:8]:
            if item.fields:
                parts.append("；".join(f"{k}：{v}" for k, v in list(item.fields.items())[:12]))
            elif item.text:
                parts.append(item.text)
        return CompletionOutput(
            text="根据资料：" + "；".join(parts),
            source_ids=tuple(item.source_id for item in request.evidence),
        )


def make_session(app, username: str, password: str) -> SimpleNamespace:
    client = TestClient(app, raise_server_exceptions=False)
    conftest.login(client, username, password)
    csrf = conftest.current_csrf(client)
    return SimpleNamespace(
        client=client,
        csrf=csrf,
        headers=conftest.write_headers(csrf),
        upload=lambda **kwargs: conftest.upload_document(client, csrf=csrf, **kwargs),
    )


def ask(session: SimpleNamespace, conversation: str, question: str) -> dict:
    response = session.client.post(
        f"/api/v1/conversations/{conversation}/messages",
        json={"client_request_id": str(uuid.uuid4()), "question": question},
        headers=session.headers,
    )
    assert response.status_code == 200, (question, response.status_code, response.text)
    return response.json()


def new_conversation(session: SimpleNamespace) -> str:
    response = session.client.post("/api/v1/conversations", json={}, headers=session.headers)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def publish(app, admin: SimpleNamespace, path: Path) -> None:
    receipt = admin.upload(path=path)
    assert receipt.status_code == 202, receipt.text
    record = receipt.json()
    db = app.state.db.session()
    try:
        job = run_one_job(db, app.state.store)
        assert job.state == "succeeded", job
        revision = int(get_revision(db))
    finally:
        db.close()
    published = admin.client.post(
        f"/api/v1/documents/{record['document']['id']}/versions/{record['version']['id']}/publish",
        headers=admin.headers,
        json={"expected_active_version_id": None, "expected_revision": revision},
    )
    assert published.status_code == 200, published.text


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="t105-verify-"))
    store = tmp / "store"
    store.mkdir(parents=True, exist_ok=True)
    settings = Settings(
        _env_file=None,
        data_dir=store,
        database_url=f"sqlite:///{(store / 'mktkb.sqlite3').as_posix()}",
        cookie_secure=False,
        csrf_secret="t105-verify-csrf-secret-0123456789",
        admin_password="AdminPass-1",
        employee_password="EmployeePass-1",
        trusted_origins=["http://testserver"],
        bcrypt_rounds=4,
        session_ttl_seconds=3600,
        log_level="INFO",
    )
    app = create_app(settings, model_gateway=EchoGateway())
    admin = make_session(app, "admin", "AdminPass-1")
    employee = make_session(app, "employee", "EmployeePass-1")
    publish(app, admin, _xlsx(tmp / "t105-verify.xlsx"))

    observations: list[dict] = []
    checks: list[tuple[str, bool, str]] = []

    def record(scenario: str, question: str, body: dict, **extra) -> None:
        observations.append(
            {
                "scenario": scenario,
                "question": question,
                **extra,
                "kind": body.get("kind"),
                "text": body.get("text"),
                "pagination": body.get("pagination"),
                "sources": len(body.get("sources") or []),
                "candidates": body.get("candidates"),
            }
        )

    def check(name: str, ok: bool, detail: str = "") -> None:
        checks.append((name, bool(ok), detail))
        print(("PASS " if ok else "FAIL ") + name + ((" | " + detail) if detail else ""))

    def answer_only(scenario: str, body: dict, expected: str, unasked: tuple[str, ...], **extra) -> None:
        text = str(body.get("text") or "")
        check(f"{scenario}: kind=answer", body.get("kind") == "answer", str(body.get("kind")))
        check(f"{scenario}: expected value", expected in text, text[:120])
        leaked = [value for value in unasked if value in text]
        check(f"{scenario}: no unasked values", not leaked, repr(leaked))
        check(f"{scenario}: no pagination", body.get("pagination") is None, str(body.get("pagination")))
        check(f"{scenario}: sources non-empty", bool(body.get("sources")), str(len(body.get("sources") or [])))
        record(scenario, extra.pop("question", ""), body, **extra)

    # S1 location context.
    conv = new_conversation(employee)
    first = ask(employee, conv, "城西店的宣传海报在哪里？")
    record("S1a", "城西店的宣传海报在哪里？", first)
    check("S1a: kind=answer", first.get("kind") == "answer", str(first.get("kind")))
    check("S1a: location", LOC in str(first.get("text")), str(first.get("text"))[:100])
    follow = ask(employee, conv, "那个海报呢")
    answer_only(
        "S1b",
        follow,
        LOC,
        (SPEC, PRICE, QTY, IDENT),
        question="那个海报呢",
    )

    # S2 quantity context.
    conv = new_conversation(employee)
    first = ask(employee, conv, "城西店的宣传海报（标识：QF02）的数量是多少？")
    record("S2a", "城西店的宣传海报（标识：QF02）的数量是多少？", first)
    check("S2a: quantity", "20" in str(first.get("text")), str(first.get("text"))[:100])
    follow = ask(employee, conv, "那个海报呢")
    answer_only("S2b", follow, QTY, (LOC, SPEC, PRICE, IDENT), question="那个海报呢")

    # S3 price context.
    conv = new_conversation(employee)
    first = ask(employee, conv, "城西店的宣传海报（标识：QF02）的参考供价是多少？")
    record("S3a", "城西店的宣传海报（标识：QF02）的参考供价是多少？", first)
    check("S3a: price", PRICE in str(first.get("text")), str(first.get("text"))[:100])
    follow = ask(employee, conv, "那个海报呢")
    answer_only("S3b", follow, PRICE, (LOC, SPEC, QTY, IDENT), question="那个海报呢")

    # S4 spec context.
    conv = new_conversation(employee)
    first = ask(employee, conv, "城西店的宣传海报（标识：QF02）的规格型号是什么？")
    record("S4a", "城西店的宣传海报（标识：QF02）的规格型号是什么？", first)
    check("S4a: spec", SPEC in str(first.get("text")), str(first.get("text"))[:100])
    follow = ask(employee, conv, "那个海报呢")
    answer_only("S4b", follow, SPEC, (LOC, PRICE, QTY, IDENT), question="那个海报呢")

    # S5 no context.
    conv = new_conversation(employee)
    body = ask(employee, conv, "那个海报呢")
    record("S5", "那个海报呢", body)
    text = str(body.get("text") or "")
    check("S5: kind=clarification", body.get("kind") == "clarification", str(body.get("kind")))
    check("S5: asks which field", "哪项信息" in text, text[:120])
    leaked = [v for v in (LOC, SPEC, PRICE, QTY, IDENT) if v in text]
    check("S5: no field values", not leaked, repr(leaked))
    check("S5: no sources", not body.get("sources"), str(body.get("sources")))

    # S6 explicit enumeration keeps pagination.
    conv = new_conversation(employee)
    body = ask(employee, conv, "把宣传海报都列出来")
    record("S6", "把宣传海报都列出来", body)
    p = body.get("pagination") or {}
    check("S6: kind=answer", body.get("kind") == "answer", str(body.get("kind")))
    check("S6: pagination", bool(p), str(p))
    check("S6: total=12", p.get("total") == 12, str(p))
    check("S6: page=1", p.get("page") == 1, str(p.get("page")))
    check("S6: has_more", p.get("has_more") is True, str(p))

    # S7 "第2页" after enumeration must stay on the enumeration path.
    body = ask(employee, conv, "那个海报的第2页")
    record("S7", "那个海报的第2页", body)
    p = body.get("pagination") or {}
    check("S7: kind=answer", body.get("kind") == "answer", str(body.get("kind")))
    check("S7: pagination page=2", p.get("page") == 2, str(p))
    check("S7: text page 2", "第 2 页" in str(body.get("text") or ""), str(body.get("text"))[:120])

    # S7b bare "第2页" after enumeration (no anaphor) stays on the enumeration path.
    conv = new_conversation(employee)
    ask(employee, conv, "把宣传海报都列出来")
    body = ask(employee, conv, "第2页")
    record("S7b", "第2页", body)
    p = body.get("pagination") or {}
    check("S7b: kind=answer", body.get("kind") == "answer", str(body.get("kind")))
    check("S7b: pagination page=2", p.get("page") == 2, str(p))

    # S8 explicit "列出来" with a field stays enumeration.
    conv = new_conversation(employee)
    ask(employee, conv, "城西店的宣传海报在哪里？")
    body = ask(employee, conv, "把那个海报的位置列出来")
    record("S8", "把那个海报的位置列出来", body)
    p = body.get("pagination") or {}
    check("S8: kind=answer", body.get("kind") == "answer", str(body.get("kind")))
    check("S8: pagination", bool(p), str(p))
    check("S8: location listed", LOC in str(body.get("text") or ""), str(body.get("text"))[:120])

    # S9 explicit "全部" stays enumeration (not the single-field override).
    conv = new_conversation(employee)
    ask(employee, conv, "城西店的宣传海报在哪里？")
    body = ask(employee, conv, "那个海报的全部信息")
    record("S9", "那个海报的全部信息", body)
    p = body.get("pagination") or {}
    check("S9: kind=answer", body.get("kind") == "answer", str(body.get("kind")))
    check("S9: pagination or enumeration text", bool(p) or "共 " in str(body.get("text") or ""), str(p))
    check("S9: not clarification", body.get("kind") != "clarification", str(body.get("kind")))

    # S10/S11 pure anaphors (前面/刚才 are not new content).
    for scenario, question in (("S10", "刚才那个呢"), ("S11", "前面那个呢")):
        conv = new_conversation(employee)
        ask(employee, conv, "城西店的宣传海报在哪里？")
        body = ask(employee, conv, question)
        answer_only(scenario, body, LOC, (SPEC, PRICE, QTY, IDENT), question=question)

    # S12 bare anaphor, no entity.
    conv = new_conversation(employee)
    body = ask(employee, conv, "那个呢")
    record("S12", "那个呢", body)
    text = str(body.get("text") or "")
    check("S12: kind=clarification", body.get("kind") == "clarification", str(body.get("kind")))
    check("S12: referent clarification", "哪个物品" in text, text[:120])
    leaked = [v for v in (LOC, SPEC, PRICE, QTY, IDENT) if v in text]
    check("S12: no field values", not leaked, repr(leaked))

    # S13/S14 alternate anaphors after a location turn.
    for scenario, question in (("S13", "这个呢"), ("S14", "那家呢")):
        conv = new_conversation(employee)
        ask(employee, conv, "城西店的宣传海报在哪里？")
        body = ask(employee, conv, question)
        record(scenario, question, body)
        text = str(body.get("text") or "")
        check(f"{scenario}: kind=answer", body.get("kind") == "answer", str(body.get("kind")))
        check(f"{scenario}: only inherited location", LOC in text and all(v not in text for v in (SPEC, PRICE, QTY, IDENT)), text[:120])

    # S15/S16 new-content follow-ups: no full dump, no over-clarification.
    for scenario, question in (
        ("S15", "那个海报的打印材质呢"),
        ("S16", "那个海报的陈列要求呢"),
        ("S15b", "那个海报的规格型号呢"),
    ):
        conv = new_conversation(employee)
        ask(employee, conv, "城西店的宣传海报在哪里？")
        body = ask(employee, conv, question)
        record(scenario, question, body)
        text = str(body.get("text") or "")
        check(f"{scenario}: not clarification", body.get("kind") != "clarification", str(body.get("kind")))
        leaked = [v for v in (LOC, SPEC, PRICE, QTY, IDENT) if v in text]
        # A whole-record dump would surface several unasked values; allow at most the
        # inherited location value if the system answers the old field.
        check(f"{scenario}: no full dump", len(leaked) <= 1, repr(leaked))

    # S15c same new-content question, but the previous turn carried an identifier
    # (product routing hands identifier turns to RAG). Documents whether the dump is
    # limited to the legacy path.
    conv = new_conversation(employee)
    ask(employee, conv, "城西店的宣传海报（标识：QF02）在哪里？")
    body = ask(employee, conv, "那个海报的规格型号呢")
    record("S15c", "那个海报的规格型号呢", body)
    text = str(body.get("text") or "")
    check("S15c: not clarification", body.get("kind") != "clarification", str(body.get("kind")))
    leaked = [v for v in (LOC, SPEC, PRICE, QTY, IDENT) if v in text]
    check("S15c: no full dump", len(leaked) <= 1, repr(leaked))

    # Cleanup.
    qa_obj = getattr(app.state, "qa", None)
    if qa_obj is not None:
        qa_obj.close()
    app.state.db.dispose()

    out = ROOT / "backend" / ".pytest-tmp" / "T105-verify" / "probe-results.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {
                "checks": [{"name": n, "ok": ok, "detail": d} for n, ok, d in checks],
                "observations": observations,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    failed = [c for c in checks if not c[1]]
    print(f"\nSUMMARY {len(checks) - len(failed)}/{len(checks)} checks passed; {len(failed)} failed")
    print(f"RESULTS {out}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

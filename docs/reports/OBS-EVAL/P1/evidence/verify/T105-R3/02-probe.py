r"""T105 R3 independent HTTP verification probe (reviewer-authored).

Independent re-verification of the R2 rework (commit b37ad21) on branch
p1/fix-retrieval.  Drives the real product HTTP path (create_app + TestClient)
with a controlled EchoGateway and an isolated temp data dir.  No network, no
.env, no real model/embedding/rerank/OCR.  Does NOT import the developer's T105
tests.

Coverage
  C5/C5b/C5c/C5d  policy/regulation anaphora must answer from the regulation
                  body, never inherit the previous record field (location/spec)
  C3              anaphora + body/policy question must answer 21 days
  C4              anaphora + named regulation must answer with 2022-07-01
  C6              anaphora + process question must answer from the body
  C7              date field: not_found wording must not claim "no record"
  B1              enumeration -> "那个海报的第2页" keeps page 2
  B2              named-field follow-ups stay single-field / no dump
  controls        bare policy/regulation questions unchanged (518/861/139)
  heuristic       is_policy_followup word-face over/under-blocking probes

Run current tree:
  .\.venv\Scripts\python.exe -B docs\reports\OBS-EVAL\P1\evidence\verify\T105-R3\02-probe.py
Environment overrides:
  T105R3_ROOT  alternate source tree (e.g. extracted baseline 17c0e63)
  T105R3_OUT   output JSON path
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import uuid
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(os.environ.get("T105R3_ROOT", r"D:\GPT项目\市场部AI知识库"))
sys.path.insert(0, str(ROOT / "backend" / "src"))
sys.path.insert(0, str(ROOT / "backend" / "tests"))

import docx  # noqa: E402
import openpyxl  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import conftest  # noqa: E402
from mktkb.config import Settings  # noqa: E402
from mktkb.documents.lifecycle import get_revision  # noqa: E402
from mktkb.ingestion.worker import run_one_job  # noqa: E402
from mktkb.main import create_app  # noqa: E402
from mktkb.rag.query import (  # noqa: E402
    is_policy_question,
    is_regulation_question,
)

try:  # R2+ only; the probe is also run against R1/baseline trees for comparison.
    from mktkb.rag.query import is_policy_followup  # noqa: E402
except ImportError:  # pragma: no cover - historical trees
    is_policy_followup = None

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
LOC = "C区2号货架第一层"
SPEC = "A2 铜版纸 157g"
PRICE = "2.6"
QTY = "20"
IDENT = "QF02"
#: Distinctive inherited values used for leak checks.  Bare "20"/"2.6" are not
#: used: "2000年10月31日" in the regulation body contains "20" as a substring.
UNASKED = (LOC, SPEC, IDENT)


def _xlsx(path: Path, title: str) -> Path:
    workbook = openpyxl.Workbook()
    worksheet = workbook.active
    worksheet.title = "物品位置"
    worksheet.cell(row=1, column=1, value=title)
    for column, header in enumerate(HEADERS, start=1):
        worksheet.cell(row=3, column=column, value=header)
    for offset, row in enumerate(ROWS):
        for column, value in enumerate(row, start=1):
            worksheet.cell(row=4 + offset, column=column, value=value)
    workbook.save(path)
    return path


def _docx(path: Path, title: str, paragraphs: list[str]) -> Path:
    document = docx.Document()
    document.add_paragraph(title)
    for text in paragraphs:
        document.add_paragraph(text)
    document.save(path)
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
        for item in request.evidence[:10]:
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
    tmp = Path(tempfile.mkdtemp(prefix="t105-r3-"))
    store = tmp / "store"
    store.mkdir(parents=True, exist_ok=True)
    settings = Settings(
        _env_file=None,
        data_dir=store,
        database_url=f"sqlite:///{(store / 'mktkb.sqlite3').as_posix()}",
        cookie_secure=False,
        csrf_secret="t105-r3-csrf-secret-0123456789",
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

    publish(app, admin, _xlsx(tmp / "t105-r3-ledger.xlsx", "T105 R3 独立验收夹具"))
    publish(
        app,
        admin,
        _docx(
            tmp / "poster-production-spec.docx",
            "宣传海报制作与陈列规范",
            [
                "第一条 宣传海报打印材质为 A2 铜版纸 157g，覆哑膜，不得使用背胶。",
                "第二条 宣传海报陈列要求：张贴于门店入口左侧，离地 1.2 米，不得遮挡价签。",
                "第三条 宣传海报盘点时间为每月最后一个工作日 16:00。",
                "第四条 宣传海报的审批流程：市场部通路行销组发起，门店店长确认。",
            ],
        ),
    )
    corpus_word = ROOT / "corpus" / "enterprise-20261101" / "word"
    corpus_legal = ROOT / "corpus" / "enterprise-20261101" / "legal"
    publish(app, admin, corpus_word / "W02_广宣物料与道具管理办法.docx")
    publish(app, admin, corpus_word / "W10_品牌视觉与物料印制规范.docx")
    publish(
        app,
        admin,
        corpus_legal / "明码标价和禁止价格欺诈规定（国家市场监督管理总局令第56号）.docx",
    )

    observations: list[dict] = []
    checks: list[tuple[str, bool, str]] = []
    notes: list[dict] = []

    def record(scenario: str, question: str, body: dict, context: str = "") -> None:
        observations.append(
            {
                "scenario": scenario,
                "context": context,
                "question": question,
                "kind": body.get("kind"),
                "text": body.get("text"),
                "text_len": len(str(body.get("text") or "")),
                "pagination": body.get("pagination"),
                "sources": len(body.get("sources") or []),
                "error_code": body.get("error_code"),
                "missing_fields": body.get("missing_fields"),
            }
        )

    def check(name: str, ok: bool, detail: object = "") -> None:
        checks.append((name, bool(ok), str(detail)))
        print(("PASS " if ok else "FAIL ") + name + ((" | " + str(detail)) if detail != "" else ""))

    def note(name: str, body: dict, **extra: object) -> None:
        item = {
            "name": name,
            "kind": body.get("kind"),
            "text_len": len(str(body.get("text") or "")),
            "record_markers": str(body.get("text") or "").count("标识："),
            "text": body.get("text"),
            **extra,
        }
        notes.append(item)
        print(f"NOTE {name} | kind={item['kind']} len={item['text_len']} markers={item['record_markers']}")

    def ask_record(session, conv: str, scenario: str, question: str, context: str = "") -> dict:
        body = ask(session, conv, question)
        record(scenario, question, body, context=context)
        return body

    def text(body: dict) -> str:
        return str(body.get("text") or "")

    def flat(body: dict) -> str:
        return "".join(text(body).split())

    def fields_count(body: dict) -> int:
        return text(body).count("标识：")

    def no_leak(scenario: str, body: dict) -> None:
        leaked = [value for value in UNASKED if value in text(body)]
        check(f"{scenario}: no unasked values", not leaked, leaked)
        check(f"{scenario}: no record markers", fields_count(body) == 0, fields_count(body))
        check(f"{scenario}: no pagination", body.get("pagination") is None, body.get("pagination"))

    def follow_after_location(scenario: str, question: str, context: str = "城西店的宣传海报在哪里？") -> dict:
        conv = new_conversation(employee)
        ask_record(employee, conv, scenario + "-ctx", context)
        return ask_record(employee, conv, scenario, question, context=scenario + "-ctx")

    # ---------- C5/C5b/C5c: policy/regulation anaphora after "where" ----------
    for label, question in (
        ("C5", "那个海报的价格欺诈规定是什么？"),
        ("C5b", "那个海报的相关规定是什么？"),
        ("C5c", "那个海报适用的价格欺诈规定是什么？"),
    ):
        body = follow_after_location(label, question)
        check(f"{label}: kind=answer", body.get("kind") == "answer", body.get("kind"))
        check(f"{label}: not inherited location", LOC not in text(body), text(body)[:120])
        check(f"{label}: not inherited spec", SPEC not in text(body), text(body)[:120])
        check(f"{label}: not a 576-char dump", len(text(body)) < 576, len(text(body)))
        check(f"{label}: mentions regulation", ("欺诈" in text(body)) or ("规定" in text(body)), text(body)[:120])
        no_leak(label, body)

    # ---------- C5d: after a spec turn, same regulation question ----------
    conv = new_conversation(employee)
    ask_record(employee, conv, "C5d-ctx", "城西店的宣传海报的规格型号是什么？")
    c5d = ask_record(employee, conv, "C5d", "那个海报的价格欺诈规定是什么？", context="C5d-ctx")
    check("C5d: kind=answer", c5d.get("kind") == "answer", c5d.get("kind"))
    check("C5d: not inherited spec", SPEC not in text(c5d), text(c5d)[:120])
    check("C5d: not inherited location", LOC not in text(c5d), text(c5d)[:120])
    check("C5d: mentions 欺诈", "欺诈" in text(c5d), text(c5d)[:120])
    no_leak("C5d", c5d)

    # C5 same-class variants: "该海报" and after a not_found turn.
    conv = new_conversation(employee)
    ask_record(employee, conv, "C5e-ctx", "城西店的宣传海报在哪里？")
    c5e = ask_record(employee, conv, "C5e", "该海报的价格欺诈规定是什么？", context="C5e-ctx")
    check("C5e(该海报): kind=answer", c5e.get("kind") == "answer", c5e.get("kind"))
    check("C5e(该海报): not inherited location", LOC not in text(c5e), text(c5e)[:120])
    check("C5e(该海报): mentions 欺诈", "欺诈" in text(c5e), text(c5e)[:120])
    no_leak("C5e", c5e)

    conv = new_conversation(employee)
    ask_record(employee, conv, "C5f-ctx", "城西店的宣传海报在哪里？")
    ask_record(employee, conv, "C5f-nf", "那个海报的打印材质呢", context="C5f-ctx")
    c5f = ask_record(employee, conv, "C5f", "那个海报的价格欺诈规定是什么？", context="C5f-ctx/C5f-nf")
    check("C5f(after not_found): kind=answer", c5f.get("kind") == "answer", c5f.get("kind"))
    check("C5f(after not_found): mentions 欺诈", "欺诈" in text(c5f), text(c5f)[:120])
    check("C5f(after not_found): not inherited location", LOC not in text(c5f), text(c5f)[:120])
    no_leak("C5f", c5f)

    # Boundary: no explicit record entity in the follow-up ("它" only).  Recorded,
    # not a named criterion; the R2 branch requires an explicit entity.
    entity_less = follow_after_location("C5-entityless", "它适用的价格欺诈规定是什么？")
    note("C5-entityless", entity_less, question="它适用的价格欺诈规定是什么？")

    # ---------- C3: anaphora + policy body question ----------
    c3 = follow_after_location("C3", "那个海报的档期物料要提前多少天提报需求？")
    check("C3: kind=answer", c3.get("kind") == "answer", c3.get("kind"))
    check("C3: contains 21", "21" in text(c3), text(c3)[:160])
    check("C3: not suppressed to not_found", c3.get("kind") != "not_found", c3.get("kind"))
    check("C3: short extractive (<200)", len(text(c3)) < 200, len(text(c3)))
    no_leak("C3", c3)

    # ---------- C4: anaphora + named regulation effective date ----------
    c4 = follow_after_location("C4", "那个海报的《明码标价和禁止价格欺诈规定》自何时起施行？")
    check("C4: kind=answer", c4.get("kind") == "answer", c4.get("kind"))
    check("C4: effective date 2022年7月1日", "2022年7月1日" in flat(c4), text(c4)[:160])
    check("C4: mentions repealed rule", "禁止价格欺诈行为的规定" in flat(c4), text(c4)[:200])
    no_leak("C4", c4)

    # ---------- C6: anaphora + process question ----------
    c6 = follow_after_location("C6", "那个海报的审批流程是什么？")
    check("C6: kind=answer", c6.get("kind") == "answer", c6.get("kind"))
    check(
        "C6: process content",
        any(word in text(c6) for word in ("审批流程", "市场部", "店长", "发起")),
        text(c6)[:160],
    )
    check("C6: short extractive (<200)", len(text(c6)) < 200, len(text(c6)))
    no_leak("C6", c6)

    # ---------- C7: record exists, date field missing -> honest wording ----------
    c7 = follow_after_location("C7", "那个海报的盘点时间是什么？")
    check("C7: kind=not_found", c7.get("kind") == "not_found", c7.get("kind"))
    check("C7: does not claim no matching record", "没有匹配记录" not in text(c7), text(c7))
    check("C7: does not claim 未找到记录", "未找到记录" not in text(c7), text(c7))
    check("C7: does not claim 未在资料中找到", "未在资料中找到" not in text(c7), text(c7))
    check("C7: says 未记录", "未记录" in text(c7), text(c7))
    no_leak("C7", c7)

    # ---------- B1: enumeration -> page 2 ----------
    conv = new_conversation(employee)
    first = ask_record(employee, conv, "B1-a", "把宣传海报都列出来")
    p = first.get("pagination") or {}
    check("B1-a: kind=answer", first.get("kind") == "answer", first.get("kind"))
    check("B1-a: page=1 total=12 returned=10 has_more", (p.get("page"), p.get("total"), p.get("returned"), p.get("has_more")) == (1, 12, 10, True), p)
    second = ask_record(employee, conv, "B1-b", "那个海报的第2页", context="B1-a")
    p2 = second.get("pagination") or {}
    check("B1-b: kind=answer", second.get("kind") == "answer", second.get("kind"))
    check("B1-b: page=2 total=12 returned=2 has_more=false", (p2.get("page"), p2.get("total"), p2.get("returned"), p2.get("has_more")) == (2, 12, 2, False), p2)
    check("B1-b: text page 2", "第 2 页" in text(second), text(second)[:120])

    conv = new_conversation(employee)
    ask_record(employee, conv, "B1-c0", "把宣传海报都列出来")
    bare = ask_record(employee, conv, "B1-c", "第2页", context="B1-c0")
    check("B1-c: bare page 2", (bare.get("pagination") or {}).get("page") == 2, bare.get("pagination"))

    conv = new_conversation(employee)
    ask_record(employee, conv, "B1-d0", "把宣传海报都列出来")
    nxt = ask_record(employee, conv, "B1-d", "那个海报的下一页", context="B1-d0")
    check("B1-d: next page 2", (nxt.get("pagination") or {}).get("page") == 2, nxt.get("pagination"))

    conv = new_conversation(employee)
    ask_record(employee, conv, "B1-e0", "城西店的宣传海报在哪里？")
    listed = ask_record(employee, conv, "B1-e", "把那个海报的位置列出来", context="B1-e0")
    check("B1-e: explicit list stays enumeration", (listed.get("pagination") or {}).get("total") == 1, listed.get("pagination"))
    check("B1-e: location present", LOC in text(listed), text(listed)[:120])

    conv = new_conversation(employee)
    ask_record(employee, conv, "B1-f0", "城西店的宣传海报在哪里？")
    allinfo = ask_record(employee, conv, "B1-f", "那个海报的全部信息", context="B1-f0")
    check("B1-f: explicit 全部 not clarification", allinfo.get("kind") != "clarification", allinfo.get("kind"))
    check("B1-f: pagination or 共 text", bool(allinfo.get("pagination")) or "共 " in text(allinfo), allinfo.get("pagination"))

    conv = new_conversation(employee)
    noctx = ask_record(employee, conv, "B1-g", "那个海报呢")
    check("B1-g: no context clarification", noctx.get("kind") == "clarification", noctx.get("kind"))
    check("B1-g: asks which field", "哪项信息" in text(noctx), text(noctx)[:120])
    check("B1-g: no values", not [v for v in UNASKED if v in text(noctx)], text(noctx)[:120])
    check("B1-g: no sources", not noctx.get("sources"), noctx.get("sources"))

    conv = new_conversation(employee)
    noent = ask_record(employee, conv, "B1-h", "那个呢")
    check("B1-h: referent clarification", noent.get("kind") == "clarification" and "哪个物品" in text(noent), text(noent)[:120])
    check("B1-h: no values", not [v for v in UNASKED if v in text(noent)], text(noent)[:120])

    # ---------- B2: named-field follow-ups stay single-field ----------
    spec = follow_after_location("B2-spec", "那个海报的规格型号呢")
    check("B2-spec: answer", spec.get("kind") == "answer", spec.get("kind"))
    check("B2-spec: spec present", SPEC in text(spec), text(spec)[:120])
    check("B2-spec: only spec", not [v for v in (LOC, PRICE, QTY, IDENT) if v in text(spec)], text(spec)[:120])
    check("B2-spec: short (<=60)", len(text(spec)) <= 60, len(text(spec)))
    check("B2-spec: no record marker", fields_count(spec) == 0, fields_count(spec))

    material = follow_after_location("B2-material", "那个海报的打印材质呢")
    check("B2-material: not_found", material.get("kind") == "not_found", material.get("kind"))
    check("B2-material: 未记录 text", "未记录" in text(material), text(material)[:120])
    check("B2-material: no sources", not material.get("sources"), material.get("sources"))
    no_leak("B2-material", material)

    display = follow_after_location("B2-display", "那个海报的陈列要求呢")
    check("B2-display: not_found", display.get("kind") == "not_found", display.get("kind"))
    check("B2-display: 未记录 text", "未记录" in text(display), text(display)[:120])
    no_leak("B2-display", display)

    loc = follow_after_location("B2-loc", "那个海报的位置呢")
    check("B2-loc: answer", loc.get("kind") == "answer", loc.get("kind"))
    check("B2-loc: only location", LOC in text(loc) and not [v for v in (SPEC, PRICE, QTY, IDENT) if v in text(loc)], text(loc)[:120])

    qty = follow_after_location("B2-qty", "那个海报的数量呢")
    check("B2-qty: answer", qty.get("kind") == "answer", qty.get("kind"))
    check("B2-qty: only quantity", QTY in text(qty) and not [v for v in (LOC, SPEC, PRICE, IDENT) if v in text(qty)], text(qty)[:120])

    price = follow_after_location("B2-price", "那个海报的参考供价是多少")
    check("B2-price: answer", price.get("kind") == "answer", price.get("kind"))
    check("B2-price: only price", PRICE in text(price) and not [v for v in (LOC, SPEC, QTY, IDENT) if v in text(price)], text(price)[:120])

    conv = new_conversation(employee)
    ask_record(employee, conv, "B2-after-ctx", "城西店的宣传海报在哪里？")
    ask_record(employee, conv, "B2-after-nf", "那个海报的打印材质呢", context="B2-after-ctx")
    after = ask_record(employee, conv, "B2-after", "那个海报呢", context="B2-after-ctx/B2-after-nf")
    check("B2-after: answer", after.get("kind") == "answer", after.get("kind"))
    check("B2-after: only inherited location", LOC in text(after) and not [v for v in (SPEC, PRICE, QTY, IDENT) if v in text(after)], text(after)[:120])

    # ---------- controls: bare policy/regulation unchanged ----------
    conv = new_conversation(employee)
    d1 = ask_record(employee, conv, "D1", "宣传海报的打印材质是什么？")
    d4 = ask_record(employee, conv, "D4", "档期物料要提前多少天提报需求？")
    note("D1-control-print-material", d1)
    check("D4: kind=answer", d4.get("kind") == "answer", d4.get("kind"))
    check("D4: contains 21", "21" in text(d4), text(d4)[:160])
    check("D4: no inherited store", "城西店" not in text(d4), text(d4)[:160])

    conv = new_conversation(employee)
    legal = ask_record(
        employee,
        conv,
        "T101",
        "《明码标价和禁止价格欺诈规定》自何时起施行？同时废止了哪两个规定？",
    )
    check("T101: kind=answer", legal.get("kind") == "answer", legal.get("kind"))
    check("T101: effective date", "2022年7月1日" in flat(legal), text(legal)[:160])
    check("T101: repealed rule", "禁止价格欺诈行为的规定" in flat(legal), text(legal)[:200])

    flow = follow_after_location("C8", "那个流程要提前几天提报")
    check("C8: kind=answer", flow.get("kind") == "answer", flow.get("kind"))
    check("C8: short answer (<300)", len(text(flow)) < 300, len(text(flow)))
    note("control-lengths", d4, d4_len=len(text(d4)), t101_len=len(text(legal)), c8_len=len(text(flow)))

    # ---------- heuristic falsification: policy word vs ledger field ----------
    probe = {
        "那个海报的陈列要求呢": False,       # 要求 is a field-ish word -> must stay record
        "那个海报的打印材质要求呢": False,   # 要求 only
        "那个海报的扣分规则是什么？": False,  # 规则 is a ledger field word (note)
        "那个海报的陈列规则呢": False,
        "那个海报的盘点时间是什么？": False,
        "那个海报的审批要求是什么？": True,
        "那个海报的价格欺诈规定是什么？": True,
        "那个海报的档期物料要提前多少天提报需求？": True,
        "那个海报的审批流程是什么？": True,
        "那个海报的报销规则是什么？": False,  # genuine policy wording, only excluded word
    }
    for question, expected in probe.items():
        if is_policy_followup is None:
            note("predicate-unavailable", {}, question=question)
            break
        actual = is_policy_followup(question)
        check(f"predicate is_policy_followup({question}) == {expected}", actual == expected, actual)
    check(
        "predicate is_policy_question('那个海报的陈列要求呢') is True (why R2 helper exists)",
        is_policy_question("那个海报的陈列要求呢") is True,
        is_policy_question("那个海报的陈列要求呢"),
    )
    check(
        "predicate is_regulation_question('那个海报的价格欺诈规定是什么？') is True",
        is_regulation_question("那个海报的价格欺诈规定是什么？") is True,
        is_regulation_question("那个海报的价格欺诈规定是什么？"),
    )

    # HTTP over/under-blocking probes (context = location).  Only the explicitly
    # required "陈列要求" case is a hard check; the rest are recorded as notes so
    # over/under-blocking is documented without redefining the acceptance matrix.
    for label, question in (
        ("H-display-rule", "那个海报的陈列规则呢"),
        ("H-score-rule", "那个海报的扣分规则是什么？"),
        ("H-approval-req", "那个海报的审批要求是什么？"),
        ("H-reimburse-rule", "那个海报的报销规则是什么？"),
        ("H-standard-spec", "那个海报的标准规格是什么？"),
        ("H-price-standard", "那个海报的价格标准是什么？"),
        ("H-submit-qty", "那个海报的提交数量呢"),
        ("H-approval-permission", "那个海报的审批权限是什么？"),
        ("H-date-policy", "那个海报的盘点规定是什么？"),
    ):
        body = follow_after_location(label, question)
        note(label, body, question=question)
    check(
        "H-display-rule: still a record not-found (not policy document answer)",
        next(o for o in observations if o["scenario"] == "H-display-rule")["kind"] == "not_found",
        next(o for o in observations if o["scenario"] == "H-display-rule")["kind"],
    )
    display_rule = next(o for o in observations if o["scenario"] == "H-display-rule")
    check(
        "H-display-rule: no dump / no inherited value",
        display_rule["text"].count("标识：") == 0 and LOC not in display_rule["text"],
        display_rule["text"],
    )

    # ---------- cleanup ----------
    qa_obj = getattr(app.state, "qa", None)
    if qa_obj is not None:
        qa_obj.close()
    app.state.db.dispose()

    out = Path(os.environ.get("T105R3_OUT", r"backend\.pytest-tmp\T105-R3\probe-results.json"))
    if not out.is_absolute():
        out = ROOT / out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {
                "root": str(ROOT),
                "mktkb_file": sys.modules["mktkb"].__file__,
                "checks": [{"name": n, "ok": ok, "detail": d} for n, ok, d in checks],
                "notes": notes,
                "observations": observations,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    failed = [c for c in checks if not c[1]]
    print(f"\nSUMMARY {len(checks) - len(failed)}/{len(checks)} checks passed; {len(failed)} failed")
    print(f"MKTKB {sys.modules['mktkb'].__file__}")
    print(f"RESULTS {out}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

r"""T105 R2 independent HTTP verification probe (reviewer-authored).

Drives the real product HTTP path (create_app + TestClient) with a controlled
EchoGateway and an isolated temp data dir. No network, no .env, no real
model/embedding/rerank/OCR. Does NOT import the developer's T105 tests.

Coverage:
  B1  enumeration -> "那个海报的第2页" keeps page 2 (and bare/next variants)
  B2  new-content anaphora follow-ups: no multi-record/full-field dump;
      record-field follow-ups answer only the asked field
  §5-2 pure anaphora / explicit enumeration / T102 policy (no anaphora) unchanged
  §5-3 policy/regulation/document follow-ups after an entity: compare with the
      same content question without anaphora and with baseline 17c0e63

Run current tree:
  .\.venv\Scripts\python.exe -B docs\reports\OBS-EVAL\P1\evidence\verify\T105-R2\02-probe.py
Run baseline (extracted 17c0e63):
  $env:T105_ROOT=<baseline>; $env:T105_OUT=<json>; python -B ...02-probe.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import uuid
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(os.environ.get("T105_ROOT", r"D:\GPT项目\市场部AI知识库"))
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
UNASKED = (LOC, SPEC, PRICE, QTY, IDENT)


def _xlsx(path: Path, headers: list[str], rows: list[list[object]], title: str) -> Path:
    workbook = openpyxl.Workbook()
    worksheet = workbook.active
    worksheet.title = "物品位置"
    worksheet.cell(row=1, column=1, value=title)
    for column, header in enumerate(headers, start=1):
        worksheet.cell(row=3, column=column, value=header)
    for offset, row in enumerate(rows):
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
    tmp = Path(tempfile.mkdtemp(prefix="t105-r2-"))
    store = tmp / "store"
    store.mkdir(parents=True, exist_ok=True)
    settings = Settings(
        _env_file=None,
        data_dir=store,
        database_url=f"sqlite:///{(store / 'mktkb.sqlite3').as_posix()}",
        cookie_secure=False,
        csrf_secret="t105-r2-csrf-secret-0123456789",
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

    publish(app, admin, _xlsx(tmp / "t105-ledger.xlsx", HEADERS, ROWS, "T105 R2 独立验收夹具"))
    publish(app, admin, _docx(
        tmp / "poster-production-spec.docx",
        "宣传海报制作与陈列规范",
        [
            "第一条 宣传海报打印材质为 A2 铜版纸 157g，覆哑膜，不得使用背胶。",
            "第二条 宣传海报陈列要求：张贴于门店入口左侧，离地 1.2 米，不得遮挡价签。",
            "第三条 宣传海报盘点时间为每月最后一个工作日 16:00。",
            "第四条 宣传海报的审批流程：市场部通路行销组发起，门店店长确认。",
        ],
    ))
    corpus_word = ROOT / "corpus" / "enterprise-20261101" / "word"
    corpus_legal = ROOT / "corpus" / "enterprise-20261101" / "legal"
    publish(app, admin, corpus_word / "W02_广宣物料与道具管理办法.docx")
    publish(app, admin, corpus_word / "W10_品牌视觉与物料印制规范.docx")
    publish(app, admin, corpus_legal / "明码标价和禁止价格欺诈规定（国家市场监督管理总局令第56号）.docx")

    observations: list[dict] = []
    checks: list[tuple[str, bool, str]] = []

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
                "source_names": [
                    source.get("document_name") or source.get("title") or ""
                    for source in (body.get("sources") or [])
                ],
                "error_code": body.get("error_code"),
                "missing_fields": body.get("missing_fields"),
            }
        )

    def check(name: str, ok: bool, detail: object = "") -> None:
        checks.append((name, bool(ok), str(detail)))
        print(("PASS " if ok else "FAIL ") + name + ((" | " + str(detail)) if detail != "" else ""))

    def ask_record(session, conv: str, scenario: str, question: str, context: str = "") -> dict:
        body = ask(session, conv, question)
        record(scenario, question, body, context=context)
        return body

    def text(body: dict) -> str:
        return str(body.get("text") or "")

    def fields_count(body: dict) -> int:
        return text(body).count("标识：")

    def no_dump(scenario: str, body: dict) -> None:
        leaked = [value for value in UNASKED if value in text(body)]
        check(f"{scenario}: no multiple-record marker", fields_count(body) == 0, fields_count(body))
        check(f"{scenario}: no unasked values", not leaked, leaked)
        check(f"{scenario}: short text (<200)", len(text(body)) < 200, len(text(body)))
        check(f"{scenario}: no pagination", body.get("pagination") is None, body.get("pagination"))

    # ---------- B1: enumeration + page 2 ----------
    conv = new_conversation(employee)
    first = ask_record(employee, conv, "B1-a", "把宣传海报都列出来")
    p = first.get("pagination") or {}
    check("B1-a: kind=answer", first.get("kind") == "answer", first.get("kind"))
    check("B1-a: page=1", p.get("page") == 1, p)
    check("B1-a: total=12", p.get("total") == 12, p)
    check("B1-a: returned=10", p.get("returned") == 10, p)
    check("B1-a: has_more=true", p.get("has_more") is True, p)

    second = ask_record(employee, conv, "B1-b", "那个海报的第2页", context="B1-a")
    p2 = second.get("pagination") or {}
    check("B1-b: kind=answer", second.get("kind") == "answer", second.get("kind"))
    check("B1-b: page=2", p2.get("page") == 2, p2)
    check("B1-b: total=12", p2.get("total") == 12, p2)
    check("B1-b: returned=2", p2.get("returned") == 2, p2)
    check("B1-b: has_more=false", p2.get("has_more") is False, p2)
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
    check(
        "B1-f: pagination or 共 text",
        bool(allinfo.get("pagination")) or "共 " in text(allinfo),
        allinfo.get("pagination"),
    )

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

    # ---------- B2: new-content anaphora follow-ups ----------
    def follow_after_location(scenario: str, question: str) -> dict:
        conv = new_conversation(employee)
        ask_record(employee, conv, scenario + "-ctx", "城西店的宣传海报在哪里？")
        return ask_record(employee, conv, scenario, question, context=scenario + "-ctx")

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
    no_dump("B2-material", material)

    display = follow_after_location("B2-display", "那个海报的陈列要求呢")
    check("B2-display: not_found", display.get("kind") == "not_found", display.get("kind"))
    check("B2-display: 未记录 text", "未记录" in text(display), text(display)[:120])
    no_dump("B2-display", display)

    loc = follow_after_location("B2-loc", "那个海报的位置呢")
    check("B2-loc: answer", loc.get("kind") == "answer", loc.get("kind"))
    check("B2-loc: only location", LOC in text(loc) and not [v for v in (SPEC, PRICE, QTY, IDENT) if v in text(loc)], text(loc)[:120])

    qty = follow_after_location("B2-qty", "那个海报的数量呢")
    check("B2-qty: answer", qty.get("kind") == "answer", qty.get("kind"))
    check("B2-qty: only quantity", QTY in text(qty) and not [v for v in (LOC, SPEC, PRICE, IDENT) if v in text(qty)], text(qty)[:120])

    price = follow_after_location("B2-price", "那个海报的参考供价是多少")
    check("B2-price: answer", price.get("kind") == "answer", price.get("kind"))
    check("B2-price: only price", PRICE in text(price) and not [v for v in (LOC, SPEC, QTY, IDENT) if v in text(price)], text(price)[:120])

    # Pure anaphora still works after a not_found new-content turn.
    conv = new_conversation(employee)
    ask_record(employee, conv, "B2-after-ctx", "城西店的宣传海报在哪里？")
    ask_record(employee, conv, "B2-after-nf", "那个海报的打印材质呢", context="B2-after-ctx")
    after = ask_record(employee, conv, "B2-after", "那个海报呢", context="B2-after-ctx/B2-after-nf")
    check("B2-after: answer", after.get("kind") == "answer", after.get("kind"))
    check("B2-after: only inherited location", LOC in text(after) and not [v for v in (SPEC, PRICE, QTY, IDENT) if v in text(after)], text(after)[:120])

    # ---------- §5-2 policy/regulation, no anaphora ----------
    conv = new_conversation(employee)
    ask_record(employee, conv, "C1-ctx", "城西店的宣传海报在哪里？")
    policy = ask_record(employee, conv, "C1", "档期物料要提前多少天提报需求？", context="C1-ctx")
    check("C1: policy answer 21", policy.get("kind") == "answer" and "21" in text(policy), text(policy)[:160])
    check("C1: no inherited store", "城西店" not in text(policy), text(policy)[:160])

    conv = new_conversation(employee)
    legal = ask_record(
        employee,
        conv,
        "C2",
        "《明码标价和禁止价格欺诈规定》自何时起施行？同时废止了哪两个规定？",
    )
    check("C2: legal answer", legal.get("kind") == "answer", legal.get("kind"))
    check("C2: effective date", "2022年7月1日" in text(legal), text(legal)[:160])
    check("C2: repealed rule", "禁止价格欺诈行为的规定" in text(legal), text(legal)[:160])

    # ---------- §5-2/§5-3: policy/regulation/document with explicit entity + anaphora ----------
    anaphora_policy = follow_after_location("C3", "那个海报的档期物料要提前多少天提报需求？")
    anaphora_reg = follow_after_location(
        "C4", "那个海报的《明码标价和禁止价格欺诈规定》自何时起施行？"
    )
    anaphora_price_reg = follow_after_location("C5", "那个海报的价格欺诈规定是什么？")
    anaphora_reg_related = follow_after_location("C5b", "那个海报的相关规定是什么？")
    anaphora_reg_applicable = follow_after_location("C5c", "那个海报适用的价格欺诈规定是什么？")
    conv = new_conversation(employee)
    ask_record(employee, conv, "C5d-ctx", "城西店的宣传海报的规格型号是什么？")
    anaphora_reg_from_spec = ask_record(
        employee, conv, "C5d", "那个海报的价格欺诈规定是什么？", context="C5d-ctx"
    )
    anaphora_flow = follow_after_location("C6", "那个海报的审批流程是什么？")
    anaphora_date = follow_after_location("C7", "那个海报的盘点时间是什么？")
    bare_flow = follow_after_location("C8", "那个流程要提前几天提报")

    # §5-2 diagnostics: a policy/regulation follow-up must not be turned into a
    # dump or into an inherited record-field answer.
    check("C3: policy follow-up not dumped", fields_count(anaphora_policy) == 0, text(anaphora_policy)[:120])
    check("C4: regulation follow-up not inherited-field answer", not (
        anaphora_reg.get("kind") == "answer"
        and "位置" in text(anaphora_reg)
        and "2022" not in text(anaphora_reg)
    ), text(anaphora_reg)[:120])
    check("C5: regulation follow-up not inherited-field answer", not (
        anaphora_price_reg.get("kind") == "answer"
        and "位置" in text(anaphora_price_reg)
        and "欺诈" not in text(anaphora_price_reg)
    ), text(anaphora_price_reg)[:120])
    for label, body in (
        ("C5b", anaphora_reg_related),
        ("C5c", anaphora_reg_applicable),
        ("C5d", anaphora_reg_from_spec),
    ):
        inherited = any(word in text(body) for word in ("位置：", "规格："))
        check(
            f"{label}: regulation follow-up not inherited-field answer",
            not (body.get("kind") == "answer" and inherited and "欺诈" not in text(body)),
            text(body)[:120],
        )
    check("C6: process follow-up not dumped", fields_count(anaphora_flow) == 0, text(anaphora_flow)[:120])
    check("C7: date follow-up not dumped", fields_count(anaphora_date) == 0, text(anaphora_date)[:120])

    # Controls: same content without anaphora / no context. If these answer from
    # documents, a not_found on the anaphora form is a behavior suppression.
    conv = new_conversation(employee)
    ctrl_material = ask_record(employee, conv, "D1-control", "宣传海报的打印材质是什么？")
    ctrl_display = ask_record(employee, conv, "D2-control", "宣传海报的陈列要求是什么？")
    ctrl_flow = ask_record(employee, conv, "D3-control", "宣传海报的审批流程是什么？")
    ctrl_policy = ask_record(employee, conv, "D4-control", "档期物料要提前多少天提报需求？")

    # ---------- cleanup ----------
    qa_obj = getattr(app.state, "qa", None)
    if qa_obj is not None:
        qa_obj.close()
    app.state.db.dispose()

    out = Path(os.environ.get("T105_OUT", r"backend\.pytest-tmp\T105-R2\probe-results.json"))
    if not out.is_absolute():
        out = ROOT / out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {
                "root": str(ROOT),
                "mktkb_file": sys.modules["mktkb"].__file__,
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
    print(f"MKTKB {sys.modules['mktkb'].__file__}")
    print(f"RESULTS {out}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

"""R6 定点回归：默认拒绝、四层事件归因、实体字段值槽。

对应经理裁决：R5D-1b（CLI 默认回落 GO 额度）、R5-B（reserved 当发送尝试）、
R5A-NEW-1/2/3（计数数字/他字段值冒充业务值、无记录不点名）。
HTTP 一律 MockTransport；账本/GO 只用 tmp_path 里的副本与夹具。
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import httpx
import pytest

from mktkb.rag import AtomicUnit, DocumentSpec, RagConfig, RagIndex
from mktkb.rag.budget import BudgetLedger
from mktkb.rag.errors import FactRejected

ROOT = Path(__file__).resolve().parents[3]


def _tools():
    spec = importlib.util.spec_from_file_location("rag_experiment_r6", ROOT / "tools" / "rag_experiment.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _doc(code: str, title: str) -> DocumentSpec:
    return DocumentSpec(
        doc_id=code,
        logical_id=code,
        source_path=f"{code}.xlsx",
        title=title,
        file_kind="xlsx",
        version_id=f"{code}-v1",
        version_label="当前",
        sha256=hashlib.sha256(code.encode()).hexdigest(),
        business_date="2026-10-28",
    )


def _row(doc: DocumentSpec, fields: dict, ordinal: int = 0) -> AtomicUnit:
    return AtomicUnit(
        unit_id=f"{doc.doc_id}-{ordinal}",
        doc_id=doc.doc_id,
        version_id=doc.version_id,
        kind="table_row",
        ordinal=ordinal,
        unit_key=f"r{ordinal}",
        text="；".join(f"{k}: {v}" for k, v in fields.items()),
        fields=fields,
        sheet="物品位置",
        locator={"sheet": "物品位置", "row": ordinal + 2, "header_row": 1, "row_number": ordinal + 2},
        header_row=1,
        row_number=ordinal + 2,
    )


# --------------------------------------------------------------- R6-1 默认拒绝


def _live_fixture(tmp_path: Path, monkeypatch, tools) -> tuple[Path, Path, Path]:
    ledger = tmp_path / "live-ledger.jsonl"
    budget = tmp_path / "budget.json"
    ledger.write_text(
        json.dumps({"event": "historical_import", "stage": "S1-DEV", "accounted_cny": 0.03}) + "\n",
        encoding="utf-8",
    )
    budget.write_text(json.dumps({"limit_cny": 10.0, "stages": {"S1-DEV": 3.0}}), encoding="utf-8")
    go = tmp_path / "S1-LIVE-GO.md"
    go.write_text(
        json.dumps(
            {
                "document": "S1-LIVE-GO",
                "stage": "S1-DEV",
                "authorization": "REAL-STAGE",
                "issued_by": "PM",
                "nonce": "n" * 24,
                "issued_utc": "2026-11-02T00:00:00+08:00",
                "expires_utc": "2099-01-01T00:00:00+08:00",
                "budget_ledger_sha256": hashlib.sha256(ledger.read_bytes()).hexdigest(),
                "scope": {"max_documents": 2, "max_requests": 40, "max_questions": 2, "stage_limit_cny": 3.0},
            }
        ),
        encoding="utf-8",
    )
    questions = tmp_path / "questions.json"
    questions.write_text(
        json.dumps(
            {
                "conversations": [
                    {
                        "id": "c1",
                        "questions": [
                            {"id": "q1", "question": "甲店的端架侧板有多少"},
                            {"id": "q2", "question": "乙店的端架侧板有多少"},
                        ],
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(tools, "_FIXED_LEDGER", ledger)
    monkeypatch.setattr(tools, "_FIXED_BUDGET", budget)
    monkeypatch.setattr(tools, "GO_PATH", go)
    for key, value in {"DASHSCOPE_API_KEY": "mock-dashscope-key"}.items():
        monkeypatch.setenv(key, value)
    return ledger, budget, questions


def _patch_corpus(monkeypatch, tools, rows: int = 3):
    docs = []
    for index in range(2):
        doc = _doc(f"R6{index}", f"端架台账{index}")
        docs.append((doc, [_row(doc, {"门店": "甲店", "物品": "端架侧板", "数量": 2 + row}, row) for row in range(rows)]))
    monkeypatch.setattr(tools, "load_corpus", lambda *a, **k: (docs, []))
    monkeypatch.setattr(tools, "build_legacy", lambda *a, **k: (None, None))


@pytest.mark.parametrize("extra", [[], ["--max-requests", "0"], ["--max-requests", "-3"]])
def test_live_requires_explicit_positive_max_requests(tmp_path, monkeypatch, extra) -> None:
    """省略 / 0 / 负数都必须在使用任何 HTTP 与账本预留之前拒绝（R5D-1b）。"""
    tools = _tools()
    ledger, budget, questions = _live_fixture(tmp_path, monkeypatch, tools)
    _patch_corpus(monkeypatch, tools)
    calls = {"post": 0}
    original_post = httpx.Client.post

    def post_spy(self, url, *args, **kwargs):  # pragma: no cover - 不应被调用
        calls["post"] += 1
        return original_post(self, url, *args, **kwargs)

    monkeypatch.setattr(httpx.Client, "post", post_spy)
    with pytest.raises(SystemExit) as excinfo:
        tools.main(
            [
                "live",
                "--ledger", str(ledger),
                "--budget", str(budget),
                "--questions", str(questions),
                "--out", str(tmp_path / "out"),
                "--max-questions", "2",
                "--max-retries", "0",
                "--transport", "mock",
                "--record-only",
                *extra,
            ]
        )
    assert "max-requests" in str(excinfo.value)
    assert calls["post"] == 0
    ledger_rows = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert [row for row in ledger_rows if row.get("event") == "reserved"] == []


def test_live_positive_quota_is_narrowed_by_go_scope(tmp_path, monkeypatch) -> None:
    tools = _tools()
    ledger, budget, questions = _live_fixture(tmp_path, monkeypatch, tools)
    _patch_corpus(monkeypatch, tools, rows=6)  # 2 批建库 + 2 查询 + 2 重排 = 6
    with pytest.raises(SystemExit) as excinfo:
        tools.main(
            [
                "live",
                "--ledger", str(ledger),
                "--budget", str(budget),
                "--questions", str(questions),
                "--out", str(tmp_path / "out"),
                "--max-requests", "5",
                "--max-questions", "2",
                "--max-retries", "0",
                "--transport", "mock",
                "--record-only",
            ]
        )
    assert "REQUEST_LIMIT" in str(excinfo.value)


# --------------------------------------------------------------- R6-2 事件归因


def test_reserve_event_carries_run_id_for_late_recovery(tmp_path) -> None:
    """run_id 必须与预留一起落盘：reserve 未返回也能在事后认领。"""
    ledger = tmp_path / "ledger.jsonl"
    budget = tmp_path / "budget.json"
    ledger.write_text("", encoding="utf-8")
    budget.write_text(json.dumps({"limit_cny": 10.0, "stages": {"S1-DEV": 3.0}}), encoding="utf-8")
    first = BudgetLedger(ledger, budget, stage="S1-DEV", stage_limit_cny=3.0, max_requests=10, run_id="run-a")
    first.reserve(kind="embedding", provider="p", model="m", max_cny=0.04096, request_sha256="a" * 64)
    rows = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert rows[-1]["event"] == "reserved" and rows[-1]["run_id"] == "run-a"

    # 旧行（无 run_id）仍可读，且不会被误认领为本轮
    legacy = BudgetLedger(ledger, budget, stage="S1-DEV", stage_limit_cny=3.0, max_requests=10)
    legacy.reserve(kind="embedding", provider="p", model="m", max_cny=0.04096, request_sha256="b" * 64)
    rows = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert "run_id" not in rows[-1]
    assert rows[-2]["run_id"] == "run-a"


def test_attribution_separates_reserved_post_and_transport(tmp_path) -> None:
    tools = _tools()
    from mktkb.rag import providers as providers_module

    providers_module.reset_post_counters()
    attribution = tools._attribution_layers(
        events=[
            {"event": "reserved", "run_id": "r1", "reservation_id": "x1", "kind": "embedding", "reserve_cny": 0.04096},
            {"event": "reserved", "run_id": "r1", "reservation_id": "x2", "kind": "embedding", "reserve_cny": 0.04096},
            {"event": "result", "run_id": "r1", "reservation_id": "x1", "kind": "embedding",
             "status": "succeeded", "conservative_charge_cny": 0.04096, "estimated_list_price_cny": 0.001},
            {"event": "reserved", "run_id": "other", "reservation_id": "f1", "kind": "embedding", "reserve_cny": 0.001},
        ],
        run_id="r1",
        post_stats={"attempts": {"embedding": 1}, "outcomes": {"embedding": {"response": 1}}},
        transport="mock",
        transport_counter={"embedding": 1},
    )
    layers = attribution["layers"]
    assert layers["reserved"]["own"] == 2
    assert layers["reserved"]["foreign"] == 1
    assert layers["post_attempts"]["total"] == 1
    assert layers["transport_attempts"]["total"] == 1
    assert layers["outcomes"]["settled"] == 1
    assert layers["outcomes"]["unsettled"] == 1
    assert attribution["cost"]["own_conservative_total_cny"] == pytest.approx(0.08192)


def test_real_transport_does_not_claim_verified_calls(tmp_path) -> None:
    tools = _tools()
    block = tools._execution_block(
        transport="real",
        started_utc="2026-11-02T00:00:00+00:00",
        finished_utc="2026-11-02T00:00:01+00:00",
        error=None,
        plan={"requests_structural_upper": 3, "requests_worst_case": 3, "requests_planned": 3},
        ledger_start=None,
        ledger_end=None,
        actuals={"reserved_by_kind": {"embedding": 2}, "results_by_kind": {}, "error_codes": {},
                 "total_reserved": 2, "total_results": 0, "conservative_charge_cny": 0.0},
        mock_counter=None,
        records=[],
        complete=True,
        post_counters={"attempts": {"embedding": 1}, "outcomes": {}},
    )
    assert block["real_calls"] is None
    assert block["real_calls_unverified"] is True
    assert block["transport_attempts_verified"] is False
    assert block["transport_attempts"] is None
    assert block["local_post_attempts"]["total"] == 1
    assert block["plan_vs_actual"]["actual_attempts_layer"] == "post_attempts"
    assert block["plan_vs_actual"]["attempts"] == 1


# --------------------------------------------------------------- R6-3 值槽


class _Capture:
    def __enter__(self):
        from mktkb.rag import facts as facts_module

        self._module = facts_module
        self._original = facts_module.FactValidator.validate_record_text
        self.calls = []

        def wrapper(validator, text, facts_list, **kwargs):
            self.calls.append((validator, text, list(facts_list), dict(kwargs)))
            return self._original(validator, text, facts_list, **kwargs)

        facts_module.FactValidator.validate_record_text = wrapper
        return self

    def __exit__(self, *exc):
        self._module.FactValidator.validate_record_text = self._original

    def replay(self, call, text):
        validator, _text, facts_list, kwargs = call
        try:
            self._original(validator, text, facts_list, **kwargs)
        except FactRejected as exc:
            return exc
        return None


@pytest.fixture
def slot_index(tmp_path):
    config = RagConfig(provider_mode="offline", data_dir=tmp_path, business_date="2026-10-28", page_size=10, top_k=10)
    index = RagIndex(tmp_path / "slots.sqlite3", config=config)
    doc = _doc("S1", "端架台账_当前V2")
    rows = [
        {"门店": "甲店", "物品": "端架侧板", "数量": 2, "标识": "QF23", "位置": "A 区"},
        {"门店": "乙店", "物品": "端架侧板", "数量": 1, "标识": "QF24", "位置": "B 区"},
        {"门店": "丙店", "物品": "端架侧板", "数量": 3, "标识": "QF25", "位置": "C 区"},
    ]
    index.add_document(doc, [_row(doc, dict(row), position) for position, row in enumerate(rows)])
    try:
        yield index
    finally:
        index.close()


def test_counting_numbers_cannot_replace_field_values(slot_index) -> None:
    with _Capture() as capture:
        slot_index.ask("甲店和乙店的端架侧板分别有多少", user_id="u", conversation_id="c")
    call = capture.calls[-1]
    text = call[1]
    # 页码 1 出现在摘要行“当前第 1 页”，把它当成甲店的业务值必须被拒。
    assert "当前第 1 页" in text
    tampered = text.replace("甲店的端架侧板：2", "甲店的端架侧板：1", 1)
    assert tampered != text
    assert capture.replay(call, tampered) is not None


def test_identifier_and_source_digits_cannot_replace_field_values(slot_index) -> None:
    with _Capture() as capture:
        slot_index.ask("甲店的端架侧板有多少", user_id="u", conversation_id="c2")
    call = capture.calls[-1]
    for forged in ("QF23", "V2", "3"):
        tampered = call[1].replace("甲店的端架侧板的数量：2", f"甲店的端架侧板的数量：{forged}", 1)
        assert tampered != call[1]
        assert capture.replay(call, tampered) is not None, forged


def test_values_equal_to_page_or_one_two_three_still_pass(tmp_path) -> None:
    """真值恰好是 1/2/3（与 page/total 重合）必须通过，不能简单禁小数字。"""
    config = RagConfig(provider_mode="offline", data_dir=tmp_path, business_date="2026-10-28", page_size=10, top_k=10)
    index = RagIndex(tmp_path / "small.sqlite3", config=config)
    doc = _doc("S2", "端架台账")
    index.add_document(
        doc,
        [
            _row(doc, {"门店": "甲店", "物品": "端架侧板", "数量": 2}, 0),
            _row(doc, {"门店": "乙店", "物品": "端架侧板", "数量": 1}, 1),
            _row(doc, {"门店": "丙店", "物品": "端架侧板", "数量": 3}, 2),
        ],
    )
    try:
        answer = index.ask("把甲店、乙店和丙店的端架侧板数量都列出来", user_id="u", conversation_id="c3")
        assert answer.kind == "answer", (answer.reason, answer.text)
        for store, value in (("甲店", "2"), ("乙店", "1"), ("丙店", "3")):
            assert f"{store}的端架侧板：{value}" in answer.text
    finally:
        index.close()


def test_identifier_question_still_answerable(tmp_path) -> None:
    """不能为了堵值槽漏洞删掉 identifier 支持。"""
    config = RagConfig(provider_mode="offline", data_dir=tmp_path, business_date="2026-10-28", page_size=10, top_k=10)
    index = RagIndex(tmp_path / "id.sqlite3", config=config)
    doc = _doc("S3", "物料标识台账")
    index.add_document(
        doc,
        [_row(doc, {"门店": "甲店", "物品": "宣传海报（标识：QF23）", "数量": 2, "位置": "A 区", "标识": "QF23"}, 0)],
    )
    try:
        answer = index.ask("甲店的宣传海报（标识：QF23）放在哪里？", user_id="u", conversation_id="c4")
        assert answer.kind == "answer", (answer.reason, answer.text)
        assert "QF23" in answer.text and "A 区" in answer.text
        listing = index.ask("把甲店的宣传海报（标识：QF23）记录都列出来", user_id="u", conversation_id="c5")
        assert listing.kind == "answer", (listing.reason, listing.text)
        assert "QF23" in listing.text
    finally:
        index.close()


def test_all_requested_entities_without_records_are_named(tmp_path) -> None:
    config = RagConfig(provider_mode="offline", data_dir=tmp_path, business_date="2026-10-28", page_size=10, top_k=10)
    index = RagIndex(tmp_path / "empty.sqlite3", config=config)
    doc = _doc("S4", "端架台账")
    index.add_document(
        doc,
        [
            _row(doc, {"门店": "甲店", "物品": "堆头围挡", "数量": 4}, 0),
            _row(doc, {"门店": "乙店", "物品": "堆头围挡", "数量": 5}, 1),
            _row(doc, {"门店": "丁店", "物品": "端架侧板", "数量": 8}, 2),
        ],
    )
    try:
        answer = index.ask("把甲店和乙店的端架侧板数量都列出来", user_id="u", conversation_id="c6")
        assert answer.kind == "no_answer"
        assert answer.reason == "NO_RECORD_FOR_ENTITY"
        assert "甲店" in answer.text and "乙店" in answer.text and "端架侧板" in answer.text
        assert "没有可枚举的记录" not in answer.text
    finally:
        index.close()


def test_paged_last_page_is_not_called_all_shown(tmp_path) -> None:
    config = RagConfig(provider_mode="offline", data_dir=tmp_path, business_date="2026-10-28", page_size=1, top_k=10)
    index = RagIndex(tmp_path / "page.sqlite3", config=config)
    doc = _doc("S5", "端架台账")
    index.add_document(
        doc,
        [
            _row(doc, {"门店": "甲店", "物品": "端架侧板", "数量": 5}, 0),
            _row(doc, {"门店": "甲店", "物品": "端架侧板", "数量": 6}, 1),
        ],
    )
    try:
        first = index.ask("把甲店的端架侧板数量都列出来", user_id="u", conversation_id="c7")
        second = index.ask("下一页", user_id="u", conversation_id="c7")
        assert first.kind == "answer" and "还有更多" in first.text
        assert second.kind == "answer"
        assert "已到最后一页" in second.text
        assert "已显示全部" not in second.text
    finally:
        index.close()

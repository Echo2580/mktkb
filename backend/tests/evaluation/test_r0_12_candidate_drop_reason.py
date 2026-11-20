"""R0/C12 候选丢弃原因：``retrieval_observed.candidate_dropped_reason``（枚举级诊断码）。

背景
----
C12（``expected_sources=2``，``answer/commit source_ids=1``）两轮修复后检查码不变，需要在
产品边界直接观测“预期来源为什么从未进入被引用证据”。本增量只补一个**可选**键：

- ``candidate_dropped_reason``：``str | None``，取值只允许固定枚举
  ``filter_miss`` / ``kind_miss`` / ``term_miss`` / ``vector_unavailable`` /
  ``dedup_dropped`` / ``limit_dropped`` / ``no_drop`` / ``not_applicable``。

不采正文 / 字段中文名 / 实体 / 值；字段只用于诊断，不改变任何检索/评分行为。
旧 envelope 没有该键时清洗/校验结果逐键不变；``capture.schema_version`` 不动
（可选键缺省不合成任何键，冻结闭包从共享白名单读键集，见 ``R0-CAPTURE-DROP.md`` §3）。

第二增量（按面拆分，见 ``R0-CAPTURE-DROP.md`` §7）
--------------------------------------------------
合成值在记录型意图上会被结构性的 ``term_miss`` 占满（``intent.terms`` 为空），一次真实 run
只能读到 ``term_miss``，无法定位 C12。因此再补两个**可选**按面键
``candidate_dropped_reason_record`` / ``candidate_dropped_reason_document``：取值仍是同一 8 码
闭集、复用同一份 ``CANDIDATE_DROP_REASONS`` 与同一条清洗路径；合成值保持原优先级逐值不变。

约束（与派单一致）
------------------
- 零真实请求、零私有材料；题面/字段/候选均为合成值，外部出站由网络闸门逐次断言为 0；
- 不改冻结件（``p2_*.py`` / ``docs/evaluation/*`` / ``fixtures/``），闭包只用其公开入口断言；
- 先红后绿：本文件在实现前必须失败（``EVENT_FIELDS`` 缺键 → ``unknown_event_fields``；
  ``candidate_unit_ids_for_intent`` 不写该键；``search`` 不认 ``diag`` 关键字）。
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from typing import Any

import pytest

_TESTS_DIR = Path(__file__).resolve().parents[1]
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))
_EVALUATION_TESTS = Path(__file__).resolve().parent
if str(_EVALUATION_TESTS) not in sys.path:
    sys.path.insert(0, str(_EVALUATION_TESTS))

from acceptance.support.netguard import t09_network_guard  # noqa: E402,F401

from mktkb.evaluation import p2_empty_scope_proof as esp_frozen  # noqa: E402
from mktkb.evaluation import p2_hard_evidence as hard  # noqa: E402
from mktkb.observability import evaluation_capture as cap  # noqa: E402
from mktkb.qa import service as qa_service  # noqa: E402
from mktkb.qa.service import QaEngine  # noqa: E402
from mktkb.rag import AtomicUnit, DocumentSpec, RagConfig, RagIndex  # noqa: E402

import test_p2_empty_scope_proof as esp  # noqa: E402

pytestmark = pytest.mark.usefixtures("t09_network_guard")

#: 加键前的 ``retrieval_observed`` 固定载荷（6 键，与 A1 协议逐键一致）。
LEGACY_RETRIEVAL_PAYLOAD: dict[str, Any] = {
    "request_id": None,
    "scope": "rag_candidate_upper_bound",
    "unit_ids": ["U-legacy"],
    "candidate": True,
    "truncated": False,
    "empty": False,
}
DROP_KEY = "candidate_dropped_reason"
#: 按面键（第二增量）：记录面/正文面各一码，与合成值并存；缺键 = 该面未观测。
FACE_RECORD_KEY = "candidate_dropped_reason_record"
FACE_DOCUMENT_KEY = "candidate_dropped_reason_document"
FACE_KEYS = (FACE_RECORD_KEY, FACE_DOCUMENT_KEY)
DROP_KEYS = (DROP_KEY, *FACE_KEYS)
EXPECTED_REASONS = {
    "filter_miss",
    "kind_miss",
    "term_miss",
    "vector_unavailable",
    "dedup_dropped",
    "limit_dropped",
    "no_drop",
    "not_applicable",
}
ROW_UNIT_ID = "U-cap-row"
NOTICE_UNIT_ID = "U-cap-text"
QUESTION_TERMS = ("甲店",)


# --------------------------------------------------------------------------- #
# 0) 离线正对照：闸门确实拦外部出站；清理记账后模块内 0 次真实调用
# --------------------------------------------------------------------------- #


def test_network_guard_positive_control_blocks_outbound(t09_network_guard) -> None:
    import socket

    with pytest.raises(Exception) as excinfo:
        socket.getaddrinfo("api.deepseek.com", 443)
    assert "T09-D1" in str(excinfo.value)
    assert t09_network_guard.snapshot()["external"], "正对照必须记录到一次外部尝试"
    t09_network_guard.external.clear()  # 这次是自证闸门用，不算产品调用
    assert t09_network_guard.snapshot()["external"] == []


# --------------------------------------------------------------------------- #
# 1) 协议层：可选键已登记（``_OPT_STR``）、枚举闭集、旧载荷逐键不变
# --------------------------------------------------------------------------- #


def test_retrieval_observed_schema_registers_optional_enum_drop_reason() -> None:
    spec = cap.EVENT_FIELDS["retrieval_observed"]
    assert DROP_KEY in spec
    assert spec[DROP_KEY].kind == cap._OPT_STR
    assert spec[DROP_KEY].required is False, "新键必须可选：旧 envelope 不得因缺键被拒"
    assert cap.CANDIDATE_DROP_REASONS == EXPECTED_REASONS
    for kind, fields in cap.EVENT_FIELDS.items():
        if kind == "retrieval_observed":
            continue
        assert DROP_KEY not in fields, f"{kind} 不应登记候选丢弃原因码"
    # 不升 capture schema 版本：可选键不改变协议版本。
    assert cap.CAPTURE_SCHEMA_VERSION == "mktkb.eval-capture/v0.1"


@pytest.mark.parametrize("reason", sorted(EXPECTED_REASONS))
def test_clean_retrieval_observed_accepts_every_allowed_reason(reason: str) -> None:
    cleaned = cap.clean_event_payload(
        "retrieval_observed", dict(LEGACY_RETRIEVAL_PAYLOAD, **{DROP_KEY: reason})
    )
    assert cleaned[DROP_KEY] == reason
    assert type(cleaned[DROP_KEY]) is str
    assert set(cleaned) == set(LEGACY_RETRIEVAL_PAYLOAD) | {DROP_KEY}


def test_clean_retrieval_observed_accepts_explicit_null_drop_reason() -> None:
    cleaned = cap.clean_event_payload(
        "retrieval_observed", dict(LEGACY_RETRIEVAL_PAYLOAD, **{DROP_KEY: None})
    )
    assert cleaned[DROP_KEY] is None


@pytest.mark.parametrize(
    "bad",
    [
        7,
        True,
        ["term_miss"],
        {"reason": "term_miss"},
        "TERM_MISS",
        "term miss",
        "甲店立牌未命中",
        "",
    ],
)
def test_clean_retrieval_observed_rejects_values_outside_enum(bad: Any) -> None:
    with pytest.raises(cap.CaptureEventError):
        cap.clean_event_payload(
            "retrieval_observed", dict(LEGACY_RETRIEVAL_PAYLOAD, **{DROP_KEY: bad})
        )
    sink = cap.CaptureSink()
    with cap.capture_scope(sink):
        cap.emit_capture_event(
            "retrieval_observed", **dict(LEGACY_RETRIEVAL_PAYLOAD, **{DROP_KEY: bad})
        )
    assert sink.status == "failed" and sink.events == []
    assert sink.errors and sink.errors[0]["code"] == "capture_event_invalid"


def test_retrieval_observed_without_drop_reason_is_cleaned_identically() -> None:
    cleaned = cap.clean_event_payload("retrieval_observed", LEGACY_RETRIEVAL_PAYLOAD)
    # 可选键缺省 = 未观测：不合成任何键，清洗结果与加键前逐键逐值相同。
    assert cleaned == LEGACY_RETRIEVAL_PAYLOAD
    assert DROP_KEY not in cleaned

    sink = cap.CaptureSink()
    with cap.capture_scope(sink):
        cap.emit_capture_event("retrieval_observed", **LEGACY_RETRIEVAL_PAYLOAD)
    assert sink.status == "active" and sink.errors == []
    assert sink.events[0]["payload"] == LEGACY_RETRIEVAL_PAYLOAD


def test_retrieval_observed_event_carries_enum_drop_reason() -> None:
    sink = cap.CaptureSink()
    with cap.capture_scope(sink):
        cap.emit_capture_event(
            "retrieval_observed",
            **dict(LEGACY_RETRIEVAL_PAYLOAD, **{DROP_KEY: "limit_dropped"}),
        )
    assert sink.status == "active" and sink.errors == []
    payload = sink.events[0]["payload"]
    # 可选键不自动补齐：只带合成值手发的载荷仍是 6+1 键（按面键缺省不合成）。
    assert set(payload) == set(LEGACY_RETRIEVAL_PAYLOAD) | {DROP_KEY}, sorted(payload)
    assert set(payload) <= set(cap.EVENT_FIELDS["retrieval_observed"])
    assert payload[DROP_KEY] == "limit_dropped"
    assert payload[DROP_KEY] in cap.CANDIDATE_DROP_REASONS
    # 只多一个枚举码：不承载正文/字段中文名/实体/值。
    for leaked in ("text", "question", "fields", "entity_key", "value", "term"):
        assert leaked not in payload


# --------------------------------------------------------------------------- #
# 2) 合成优先级：固定枚举序，先记录先保留
# --------------------------------------------------------------------------- #


def test_candidate_drop_priority_is_the_fixed_order() -> None:
    assert qa_service.CANDIDATE_DROP_PRIORITY == (
        "kind_miss",
        "term_miss",
        "vector_unavailable",
        "filter_miss",
        "dedup_dropped",
        "limit_dropped",
    )
    assert set(qa_service.CANDIDATE_DROP_PRIORITY) <= cap.CANDIDATE_DROP_REASONS
    merge = qa_service._merge_candidate_drop_reason
    assert merge({"exact": "kind_miss"}, {"lexical": "term_miss"}) == "kind_miss"
    assert merge({"lexical": "term_miss"}, {"vector": "vector_unavailable"}) == "term_miss"
    assert merge({"vector": "vector_unavailable"}, {"filter": "filter_miss"}) == "vector_unavailable"
    assert merge({"filter": "filter_miss"}, {"dedup": "dedup_dropped"}) == "filter_miss"
    assert merge({"dedup": "dedup_dropped"}, {"limit": "limit_dropped"}) == "dedup_dropped"
    assert merge({"limit": "limit_dropped"}, {}) == "limit_dropped"
    assert merge({}, None) == "no_drop"


# --------------------------------------------------------------------------- #
# 3) 产品发射点：合成值随 ``retrieval_observed`` 发出且只在枚举内
# --------------------------------------------------------------------------- #


def _doc(doc_id: str, *, title: str, source_path: str, file_kind: str) -> DocumentSpec:
    return DocumentSpec(
        doc_id=doc_id,
        logical_id=doc_id,
        source_path=source_path,
        title=title,
        file_kind=file_kind,
        version_id=f"V-{doc_id}",
        version_label="当前",
        sha256=hashlib.sha256(doc_id.encode("utf-8")).hexdigest(),
        business_date="2026-10-28",
    )


def _config(tmp_path: Path, *, disable_query_embedding: bool = False) -> RagConfig:
    return RagConfig(
        provider_mode="offline",
        data_dir=tmp_path,
        business_date="2026-10-28",
        chunk_max_chars=420,
        chunk_max_units=3,
        chunk_overlap_units=1,
        top_k=5,
        page_size=10,
        vector_candidate_limit=50,
        rerank_top_n=20,
        disable_query_embedding=disable_query_embedding,
    )


@pytest.fixture
def synthetic_index(tmp_path: Path):
    index = RagIndex(tmp_path / "rag.sqlite3", config=_config(tmp_path))
    try:
        yield index
    finally:
        index.close()


@pytest.fixture
def vector_disabled_index(tmp_path: Path):
    index = RagIndex(
        tmp_path / "rag-novec.sqlite3",
        config=_config(tmp_path, disable_query_embedding=True),
    )
    try:
        yield index
    finally:
        index.close()


def _seed(index: RagIndex) -> None:
    """记录行（xlsx）+ 正文通知（pdf），都不建向量：与 C12 的确定性形状一致。"""

    row_doc = _doc(
        "D-cap-row",
        title="合成物品位置表",
        source_path="synthetic/D-cap-row.xlsx",
        file_kind="xlsx",
    )
    fields = {"门店": "甲店", "物品": "立牌", "位置": "甲区"}
    row = AtomicUnit(
        unit_id=ROW_UNIT_ID,
        doc_id=row_doc.doc_id,
        version_id=row_doc.version_id,
        kind="table_row",
        ordinal=0,
        unit_key="sheet:合成表:row:7",
        text="；".join(f"{name}: {value}" for name, value in fields.items()),
        fields=fields,
        sheet="合成表",
        locator={"sheet": "合成表", "row": 7, "header_row": 1},
        header_row=1,
        row_number=7,
        title=row_doc.title,
    )
    index.add_document(row_doc, [row], embed=False)

    notice_doc = _doc(
        "D-cap-notice",
        title="合成物料位置通知",
        source_path="synthetic/D-cap-notice.pdf",
        file_kind="pdf",
    )
    notice = AtomicUnit(
        unit_id=NOTICE_UNIT_ID,
        doc_id=notice_doc.doc_id,
        version_id=notice_doc.version_id,
        kind="paragraph",
        ordinal=0,
        unit_key="paragraph:1",
        text="通知：甲店立牌下月起迁至乙区",
        fields={},
        sheet=None,
        locator={"paragraph": 1},
        title=notice_doc.title,
    )
    index.add_document(notice_doc, [notice], embed=False)


def _engine(index: RagIndex, tmp_path: Path) -> QaEngine:
    """把合成索引挂到产品入口上（只为复用同一份索引，不建产品库）。"""

    engine = QaEngine(db_factory=None, index_path=tmp_path / "qa-index.sqlite3")
    engine._index = index  # noqa: SLF001 - 合成装配：跳过从产品库同步
    engine.ensure_ready = lambda **_kwargs: None  # noqa: SLF001 - 同上
    return engine


def _emit_reason(engine: QaEngine, **kwargs: Any) -> tuple[set[str], str, dict[str, Any]]:
    sink = cap.CaptureSink()
    with cap.capture_scope(sink):
        ids = engine.candidate_unit_ids_for_intent(**kwargs)
    assert sink.status == "active" and sink.errors == [], sink.errors
    payloads = [event["payload"] for event in sink.events if event["kind"] == "retrieval_observed"]
    assert len(payloads) == 1, payloads
    payload = payloads[0]
    assert DROP_KEY in payload, "产品发射点必须带上候选丢弃原因"
    assert payload[DROP_KEY] in cap.CANDIDATE_DROP_REASONS
    return ids, payload[DROP_KEY], payload


def test_record_intent_without_terms_reports_term_miss(synthetic_index, tmp_path):
    _seed(synthetic_index)
    engine = _engine(synthetic_index, tmp_path)

    ids, reason, payload = _emit_reason(
        engine, mode="record", terms=(), entity_filters={"store": "甲店"}
    )
    # 记录面 terms 空 → ``match_expression(())`` 返回 None（C12 根因的固定码）。
    assert reason == "term_miss", payload
    assert ids == {ROW_UNIT_ID}
    assert payload["scope"] == "rag_candidate_upper_bound"
    assert payload["unit_ids"] == [ROW_UNIT_ID]
    assert payload["candidate"] is True and payload["truncated"] is False


def test_document_intent_reports_kind_miss_for_absent_exact_face(synthetic_index, tmp_path):
    _seed(synthetic_index)
    engine = _engine(synthetic_index, tmp_path)

    ids, reason, payload = _emit_reason(engine, mode="document", terms=QUESTION_TERMS)
    # 非 record 计划没有记录面精确通道 → kind_miss 优先。
    assert reason == "kind_miss", payload
    assert ROW_UNIT_ID in ids and NOTICE_UNIT_ID in ids, ids


def test_vector_channel_unavailable_reports_vector_unavailable(vector_disabled_index, tmp_path):
    _seed(vector_disabled_index)
    engine = _engine(vector_disabled_index, tmp_path)

    _ids, reason, payload = _emit_reason(
        engine,
        mode="record",
        terms=QUESTION_TERMS,
        entity_filters={"store": "甲店"},
        document_terms=QUESTION_TERMS,
    )
    assert reason == "vector_unavailable", payload


def test_two_face_recall_without_any_drop_reports_no_drop(synthetic_index, tmp_path):
    _seed(synthetic_index)
    engine = _engine(synthetic_index, tmp_path)

    ids, reason, payload = _emit_reason(
        engine,
        mode="record",
        terms=QUESTION_TERMS,
        entity_filters={"store": "甲店"},
        document_terms=QUESTION_TERMS,
    )
    assert reason == "no_drop", payload
    # 两轮都真的召回了东西（否则 no_drop 只是空集的假绿）。
    assert ids == {ROW_UNIT_ID, NOTICE_UNIT_ID}, ids


def test_unknown_mode_reports_not_applicable(synthetic_index, tmp_path):
    _seed(synthetic_index)
    engine = _engine(synthetic_index, tmp_path)

    _ids, reason, payload = _emit_reason(engine, mode="hybrid", terms=QUESTION_TERMS)
    assert reason == "not_applicable", payload


def test_intent_search_is_unchanged_when_capture_disabled(synthetic_index, tmp_path):
    """未安装 sink 时：不构造 diag、不新增键，候选集与默认入口逐值相同。"""

    _seed(synthetic_index)
    engine = _engine(synthetic_index, tmp_path)
    expected = {ROW_UNIT_ID, NOTICE_UNIT_ID}
    assert (
        engine.candidate_unit_ids_for_intent(
            mode="record",
            terms=QUESTION_TERMS,
            entity_filters={"store": "甲店"},
            document_terms=QUESTION_TERMS,
        )
        == expected
    )
    assert cap.capture_enabled() is False


# --------------------------------------------------------------------------- #
# 4) 冻结闭包：从共享白名单读键集，旧 envelope 无该键时逐值不变
# --------------------------------------------------------------------------- #


def test_frozen_closures_read_the_shared_capture_whitelist() -> None:
    assert hard.CAPTURE_EVENT_FIELDS is cap.EVENT_FIELDS
    assert esp_frozen.EVENT_FIELDS is cap.EVENT_FIELDS
    assert DROP_KEY in hard.CAPTURE_EVENT_FIELDS["retrieval_observed"]


def test_empty_scope_proof_accepts_new_optional_key_and_keeps_legacy_result() -> None:
    envelope = esp.build_evidence()
    assert esp.empty_use_scope_proof(envelope) == (True, esp.EMPTY_USE_SCOPE_OK)
    payloads = [
        event["payload"]
        for event in envelope["capture"]["events"]
        if event["kind"] == "retrieval_observed"
    ]
    assert payloads, "空集证明 envelope 必须带 retrieval_observed"
    payload = payloads[0]
    assert set(payload) == set(LEGACY_RETRIEVAL_PAYLOAD), sorted(payload)

    # 旧 envelope（无该键）结论逐值不变；带枚举码的新 envelope 也不被判 unknown_usage_field。
    payload[DROP_KEY] = "term_miss"
    assert esp.empty_use_scope_proof(envelope) == (True, esp.EMPTY_USE_SCOPE_OK)

    # 非枚举值必须在冻结闭包里被拒（clean_event_payload 的唯一清洗口径）。
    payload[DROP_KEY] = "甲店立牌未命中"
    assert esp.empty_use_scope_proof(envelope) != (True, esp.EMPTY_USE_SCOPE_OK)


# --------------------------------------------------------------------------- #
# 5) 第二增量：按面键 ``candidate_dropped_reason_record`` /
#    ``candidate_dropped_reason_document``（一面一码，合成值不动）
# --------------------------------------------------------------------------- #


def test_retrieval_observed_registers_two_optional_face_keys() -> None:
    spec = cap.EVENT_FIELDS["retrieval_observed"]
    for key in FACE_KEYS:
        assert key in spec, key
        assert spec[key].kind == cap._OPT_STR, key
        assert spec[key].required is False, f"{key} 必须可选：旧 envelope 不得因缺键被拒"
    for kind, fields in cap.EVENT_FIELDS.items():
        if kind == "retrieval_observed":
            continue
        for key in FACE_KEYS:
            assert key not in fields, f"{kind} 不应登记 {key}"
    # 枚举闭集复用同一份码表（不是第二份副本），且仍是同一 8 码闭集。
    for key in FACE_KEYS:
        assert cap._ENUM_VALUES[("retrieval_observed", key)] is cap.CANDIDATE_DROP_REASONS, key
    assert cap.CANDIDATE_DROP_REASONS == EXPECTED_REASONS
    # 可选键不升版。
    assert cap.CAPTURE_SCHEMA_VERSION == "mktkb.eval-capture/v0.1"


@pytest.mark.parametrize("key", FACE_KEYS)
@pytest.mark.parametrize("reason", sorted(EXPECTED_REASONS))
def test_clean_accepts_every_allowed_reason_per_face(key: str, reason: str) -> None:
    payload = dict(LEGACY_RETRIEVAL_PAYLOAD, **{key: reason})
    assert cap.clean_event_payload("retrieval_observed", payload) == payload


@pytest.mark.parametrize("key", FACE_KEYS)
@pytest.mark.parametrize(
    "bad",
    [
        7,
        True,
        ["term_miss"],
        {"reason": "term_miss"},
        "TERM_MISS",
        "term miss",
        "甲店立牌未命中",
        "",
    ],
)
def test_clean_rejects_face_values_outside_enum(key: str, bad: Any) -> None:
    with pytest.raises(cap.CaptureEventError):
        cap.clean_event_payload(
            "retrieval_observed", dict(LEGACY_RETRIEVAL_PAYLOAD, **{key: bad})
        )
    sink = cap.CaptureSink()
    with cap.capture_scope(sink):
        cap.emit_capture_event(
            "retrieval_observed", **dict(LEGACY_RETRIEVAL_PAYLOAD, **{key: bad})
        )
    assert sink.status == "failed" and sink.events == []
    assert sink.errors and sink.errors[0]["code"] == "capture_event_invalid"


@pytest.mark.parametrize("key", FACE_KEYS)
def test_face_key_unknown_code_fails_in_enum_validation(key: str) -> None:
    """合法类型 + 闭集外码：必须走枚举校验（复用同一码表），而不是靠“未知字段”拒。"""

    with pytest.raises(cap.CaptureEventError) as excinfo:
        cap.clean_event_payload(
            "retrieval_observed", dict(LEGACY_RETRIEVAL_PAYLOAD, **{key: "TERM_MISS"})
        )
    assert f"{key}_not_in_enum" in str(excinfo.value)


def test_face_keys_are_absent_by_default_and_never_synthesized() -> None:
    assert (
        cap.clean_event_payload("retrieval_observed", LEGACY_RETRIEVAL_PAYLOAD)
        == LEGACY_RETRIEVAL_PAYLOAD
    )
    only_record = dict(LEGACY_RETRIEVAL_PAYLOAD, **{FACE_RECORD_KEY: "term_miss"})
    cleaned = cap.clean_event_payload("retrieval_observed", only_record)
    assert cleaned == only_record
    assert FACE_DOCUMENT_KEY not in cleaned, "缺键 = 未观测：不得合成另一面"


def test_per_face_keys_split_record_and_document_faces(synthetic_index, tmp_path):
    """红→绿主用例：一次 run 同时读到记录面 ``term_miss`` 与正文面 ``no_drop``。"""

    _seed(synthetic_index)
    engine = _engine(synthetic_index, tmp_path)

    ids, reason, payload = _emit_reason(
        engine,
        mode="record",
        terms=(),  # 记录型意图结构性无词（C12 前提）
        entity_filters={"store": "甲店"},
        document_terms=QUESTION_TERMS,  # 正文面用题面派生词才真的召回正文通知
    )
    assert ids == {ROW_UNIT_ID, NOTICE_UNIT_ID}, ids
    # 合成值：与改前逐值相同（term_miss 仍按既有优先级胜出）。
    assert reason == "term_miss", payload
    # 按面键：两面同时可读——缺键时（改前）只能读到合成值 term_miss，无法区分是哪一面。
    assert payload[FACE_RECORD_KEY] == "term_miss", payload
    assert payload[FACE_DOCUMENT_KEY] == "no_drop", payload
    # 三键同属一个事件；旧 6 键不因加键改名/缺键。
    # R0-CAPTURE-KEYS 后续又补了两枚可选身份键（candidate_unit_keys*），同一发射点
    # 会带上它们；本用例只负责 pin 丢弃原因三键，故按“旧 6 键 + 丢弃三键 + 身份两键”断言。
    assert set(payload) == set(LEGACY_RETRIEVAL_PAYLOAD) | set(DROP_KEYS) | {
        "candidate_unit_keys",
        "candidate_unit_keys_truncated",
    }, sorted(payload)


def test_per_face_keys_keep_both_structural_term_miss(synthetic_index, tmp_path):
    """两面都没词：按面键如实各记 ``term_miss``，不粉饰、也不把正文面记 kind_miss。"""

    _seed(synthetic_index)
    engine = _engine(synthetic_index, tmp_path)

    ids, reason, payload = _emit_reason(
        engine, mode="record", terms=(), entity_filters={"store": "甲店"}
    )
    assert ids == {ROW_UNIT_ID}, ids
    assert reason == "term_miss", payload
    assert payload[FACE_RECORD_KEY] == "term_miss", payload
    assert payload[FACE_DOCUMENT_KEY] == "term_miss", payload


def test_document_intent_puts_the_only_face_on_document(synthetic_index, tmp_path):
    """正文型意图只跑正文面：记录面记 ``not_applicable``，不把 kind_miss 挂到记录面。"""

    _seed(synthetic_index)
    engine = _engine(synthetic_index, tmp_path)

    ids, reason, payload = _emit_reason(engine, mode="document", terms=QUESTION_TERMS)
    assert reason == "kind_miss", payload
    assert payload[FACE_RECORD_KEY] == "not_applicable", payload
    assert payload[FACE_DOCUMENT_KEY] == "kind_miss", payload
    assert ROW_UNIT_ID in ids and NOTICE_UNIT_ID in ids, ids


def test_unknown_mode_marks_both_faces_not_applicable(synthetic_index, tmp_path):
    _seed(synthetic_index)
    engine = _engine(synthetic_index, tmp_path)

    _ids, reason, payload = _emit_reason(engine, mode="hybrid", terms=QUESTION_TERMS)
    assert reason == "not_applicable", payload
    assert payload[FACE_RECORD_KEY] == "not_applicable", payload
    assert payload[FACE_DOCUMENT_KEY] == "not_applicable", payload


def test_vector_unavailable_is_reported_per_face(vector_disabled_index, tmp_path):
    _seed(vector_disabled_index)
    engine = _engine(vector_disabled_index, tmp_path)

    _ids, reason, payload = _emit_reason(
        engine,
        mode="record",
        terms=QUESTION_TERMS,
        entity_filters={"store": "甲店"},
        document_terms=QUESTION_TERMS,
    )
    assert reason == "vector_unavailable", payload
    assert payload[FACE_RECORD_KEY] == "vector_unavailable", payload
    assert payload[FACE_DOCUMENT_KEY] == "vector_unavailable", payload


def test_composite_equals_fixed_priority_merge_of_face_codes(synthetic_index, tmp_path):
    """合成值可由两面按面码按既有优先级复算：按面拆分没有偷偷改合成语义。"""

    _seed(synthetic_index)
    engine = _engine(synthetic_index, tmp_path)
    cases = (
        (
            dict(
                mode="record",
                terms=(),
                entity_filters={"store": "甲店"},
                document_terms=QUESTION_TERMS,
            ),
            "term_miss",
        ),
        (
            dict(
                mode="record",
                terms=QUESTION_TERMS,
                entity_filters={"store": "甲店"},
                document_terms=QUESTION_TERMS,
            ),
            "no_drop",
        ),
    )
    for kwargs, expected in cases:
        _ids, reason, payload = _emit_reason(engine, **kwargs)
        assert reason == expected, payload
        assert (
            qa_service._merge_candidate_drop_reason(
                {FACE_RECORD_KEY: payload[FACE_RECORD_KEY]},
                {FACE_DOCUMENT_KEY: payload[FACE_DOCUMENT_KEY]},
            )
            == reason
        ), payload


def test_faces_are_not_built_when_capture_is_closed(synthetic_index, tmp_path, monkeypatch):
    """观察关闭：不发事件，因此也不构造按面键；候选集与默认入口逐值相同。"""

    _seed(synthetic_index)
    engine = _engine(synthetic_index, tmp_path)
    emitted: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(qa_service, "capture_enabled", lambda: False)
    monkeypatch.setattr(
        qa_service, "emit_capture_event", lambda kind, **payload: emitted.append((kind, payload))
    )

    ids = engine.candidate_unit_ids_for_intent(
        mode="record", terms=(), entity_filters={"store": "甲店"}
    )
    assert ids == {ROW_UNIT_ID}, ids
    assert emitted == [], "观察关闭时不得发事件，也就不建按面键"


def test_frozen_closures_accept_face_keys_without_changes() -> None:
    assert hard.CAPTURE_EVENT_FIELDS is cap.EVENT_FIELDS
    assert esp_frozen.EVENT_FIELDS is cap.EVENT_FIELDS
    for key in FACE_KEYS:
        assert key in hard.CAPTURE_EVENT_FIELDS["retrieval_observed"], key

    envelope = esp.build_evidence()
    payloads = [
        event["payload"]
        for event in envelope["capture"]["events"]
        if event["kind"] == "retrieval_observed"
    ]
    payload = payloads[0]
    assert set(payload) == set(LEGACY_RETRIEVAL_PAYLOAD), sorted(payload)

    payload[FACE_RECORD_KEY] = "term_miss"
    payload[FACE_DOCUMENT_KEY] = "no_drop"
    assert esp.empty_use_scope_proof(envelope) == (True, esp.EMPTY_USE_SCOPE_OK)
    # 按面键与非枚举值走同一清洗口径：冻结闭包必须 fail-closed。
    payload[FACE_DOCUMENT_KEY] = "甲店立牌未命中"
    assert esp.empty_use_scope_proof(envelope) != (True, esp.EMPTY_USE_SCOPE_OK)


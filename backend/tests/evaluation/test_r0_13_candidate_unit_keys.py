"""R0 r0-13：``retrieval_observed.candidate_unit_keys``（候选单元身份采集）。

背景
----
C12 的定位卡在一步：候选上界有 6 个 unit id，但 ``db_projection.units`` 只保留被引用的
1 行，``candidate_id -> unit_key`` 解析不出来，"期望来源是否在候选集合里"无法判定
（见 ``R0-ROUND8.md``）。本增量给 ``retrieval_observed`` 补两个**可选**键：

- ``candidate_unit_keys``：``list[str]``，该次候选上界各单元的 ``unit_key``
  （形如 ``sheet:<表>:row:<行号>`` 的标识符），**不是**正文/值/实体名；
- ``candidate_unit_keys_truncated``：``bool``，上面列表是否因 32 上限被截断。

约束（与派单一致）
------------------
- 可选键：旧 envelope 无该键时清洗/校验结果逐值不变，缺键不合成；不升 capture 版本；
- 只在 ``scope == "rag_candidate_upper_bound"`` 的事件上携带；其它 scope 不建键；
- 无法解析身份的 unit 直接跳过（不报错、不填占位）；
- 纯观测：不改变任何检索行为与结果集，``capture_enabled()`` 关闭时不建键；
- 零真实请求、零私有材料；合成索引 + 合成题面，外部出站由网络闸门逐次断言为 0；
- 不改冻结件（``p2_*.py`` / ``docs/evaluation/*`` / ``fixtures/``）；先红后绿。
"""

from __future__ import annotations

import hashlib
import re
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
KEYS_KEY = "candidate_unit_keys"
TRUNC_KEY = "candidate_unit_keys_truncated"
UPPER_BOUND_SCOPE = "rag_candidate_upper_bound"
#: 记录行身份形态：``sheet:<表>:row:<行号>``（不是正文/值）。
ROW_KEY_RE = re.compile(r"^sheet:.+:row:\d+$")
MAX_KEYS = 32
STORE = "甲店"


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
# 1) 协议层：两个可选键已登记、非枚举、旧载荷逐键不变
# --------------------------------------------------------------------------- #


def test_retrieval_observed_registers_two_optional_identity_keys() -> None:
    spec = cap.EVENT_FIELDS["retrieval_observed"]
    assert KEYS_KEY in spec, "必须登记候选身份键"
    assert spec[KEYS_KEY].kind == cap._LIST_STR, "候选身份是 unit_key 字符串列表"
    assert spec[KEYS_KEY].required is False, "新键必须可选：旧 envelope 不得因缺键被拒"
    assert TRUNC_KEY in spec, "必须登记截断标志"
    assert spec[TRUNC_KEY].kind == cap._BOOL
    assert spec[TRUNC_KEY].required is False
    # 这两个键不是枚举码：不新增码表条目。
    assert ("retrieval_observed", KEYS_KEY) not in cap._ENUM_VALUES
    assert ("retrieval_observed", TRUNC_KEY) not in cap._ENUM_VALUES
    for kind, fields in cap.EVENT_FIELDS.items():
        if kind == "retrieval_observed":
            continue
        assert KEYS_KEY not in fields, f"{kind} 不应登记候选身份键"
        assert TRUNC_KEY not in fields, f"{kind} 不应登记候选身份键"
    # 可选键不升 capture schema 版本。
    assert cap.CAPTURE_SCHEMA_VERSION == "mktkb.eval-capture/v0.1"


def test_clean_retrieval_observed_accepts_keys_with_truncation_flag() -> None:
    payload = dict(
        LEGACY_RETRIEVAL_PAYLOAD,
        **{
            KEYS_KEY: ["sheet:合成表:row:2", "sheet:合成表:row:3"],
            TRUNC_KEY: False,
        },
    )
    assert cap.clean_event_payload("retrieval_observed", payload) == payload


def test_clean_retrieval_observed_accepts_empty_key_list() -> None:
    payload = dict(LEGACY_RETRIEVAL_PAYLOAD, **{KEYS_KEY: [], TRUNC_KEY: False})
    cleaned = cap.clean_event_payload("retrieval_observed", payload)
    assert cleaned == payload
    assert cleaned[KEYS_KEY] == []


@pytest.mark.parametrize(
    "bad, expected",
    [
        ("sheet:合成表:row:2", "candidate_unit_keys_must_be_list"),
        (7, "candidate_unit_keys_must_be_list"),
        ({"key": "sheet:合成表:row:2"}, "candidate_unit_keys_must_be_list"),
        (None, "candidate_unit_keys_must_be_list"),
        ([1], "candidate_unit_keys_item_must_be_str"),
        (["ok", 2], "candidate_unit_keys_item_must_be_str"),
        ([None], "candidate_unit_keys_item_must_be_str"),
    ],
)
def test_clean_retrieval_observed_rejects_bad_key_lists(bad: Any, expected: str) -> None:
    with pytest.raises(cap.CaptureEventError) as excinfo:
        cap.clean_event_payload(
            "retrieval_observed", dict(LEGACY_RETRIEVAL_PAYLOAD, **{KEYS_KEY: bad})
        )
    assert expected in str(excinfo.value), excinfo.value


@pytest.mark.parametrize("bad", [1, 0, "true", None, []])
def test_clean_retrieval_observed_rejects_bad_truncation_flag(bad: Any) -> None:
    with pytest.raises(cap.CaptureEventError) as excinfo:
        cap.clean_event_payload(
            "retrieval_observed", dict(LEGACY_RETRIEVAL_PAYLOAD, **{TRUNC_KEY: bad})
        )
    assert "candidate_unit_keys_truncated_must_be_bool" in str(excinfo.value)


def test_legacy_payload_without_identity_keys_is_cleaned_identically() -> None:
    cleaned = cap.clean_event_payload("retrieval_observed", LEGACY_RETRIEVAL_PAYLOAD)
    # 可选键缺省 = 未观测：不合成任何键，清洗结果与加键前逐键逐值相同。
    assert cleaned == LEGACY_RETRIEVAL_PAYLOAD
    assert KEYS_KEY not in cleaned and TRUNC_KEY not in cleaned

    sink = cap.CaptureSink()
    with cap.capture_scope(sink):
        cap.emit_capture_event("retrieval_observed", **LEGACY_RETRIEVAL_PAYLOAD)
    assert sink.status == "active" and sink.errors == []
    assert sink.events[0]["payload"] == LEGACY_RETRIEVAL_PAYLOAD


def test_non_upper_bound_scope_event_carries_no_identity_keys() -> None:
    """legacy 检索事件（conversations 的 ``legacy_retrieve_*``）不得带候选身份键。"""

    legacy_payload = dict(
        LEGACY_RETRIEVAL_PAYLOAD, scope="legacy_retrieve_initial", candidate=False
    )
    sink = cap.CaptureSink()
    with cap.capture_scope(sink):
        cap.emit_capture_event("retrieval_observed", **legacy_payload)
    assert sink.status == "active" and sink.errors == []
    payload = sink.events[0]["payload"]
    assert payload == legacy_payload
    assert KEYS_KEY not in payload and TRUNC_KEY not in payload


# --------------------------------------------------------------------------- #
# 2) 合成索引与产品入口（只复用同一份索引，不建产品库）
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


def _seed_rows(index: RagIndex, count: int, *, start_row: int = 2) -> set[str]:
    """同一门店的 ``count`` 条记录行（每条一个 unit_key）；精确面按 store 全命中。"""

    doc = _doc(
        "D-keys-rows",
        title="合成物品位置表",
        source_path="synthetic/D-keys-rows.xlsx",
        file_kind="xlsx",
    )
    units: list[AtomicUnit] = []
    keys: set[str] = set()
    for offset in range(count):
        row_number = start_row + offset
        key = f"sheet:合成表:row:{row_number}"
        keys.add(key)
        fields = {"门店": STORE, "物品": f"合成物品{offset:02d}", "位置": f"甲区{offset:02d}"}
        units.append(
            AtomicUnit(
                unit_id=f"U-keys-row-{offset:02d}",
                doc_id=doc.doc_id,
                version_id=doc.version_id,
                kind="table_row",
                ordinal=offset,
                unit_key=key,
                text="；".join(f"{name}: {value}" for name, value in fields.items()),
                fields=fields,
                sheet="合成表",
                locator={"sheet": "合成表", "row": row_number, "header_row": 1},
                header_row=1,
                row_number=row_number,
                title=doc.title,
            )
        )
    index.add_document(doc, units, embed=False)
    return keys


def _engine(index: RagIndex, tmp_path: Path) -> QaEngine:
    engine = QaEngine(db_factory=None, index_path=tmp_path / "qa-index.sqlite3")
    engine._index = index  # noqa: SLF001 - 合成装配：跳过从产品库同步
    engine.ensure_ready = lambda **_kwargs: None  # noqa: SLF001 - 同上
    return engine


def _emit(engine: QaEngine, **kwargs: Any) -> tuple[set[str], dict[str, Any]]:
    sink = cap.CaptureSink()
    with cap.capture_scope(sink):
        ids = engine.candidate_unit_ids_for_intent(**kwargs)
    assert sink.status == "active" and sink.errors == [], sink.errors
    payloads = [event["payload"] for event in sink.events if event["kind"] == "retrieval_observed"]
    assert len(payloads) == 1, payloads
    return ids, payloads[0]


RECORD_CALL = dict(mode="record", terms=(), entity_filters={"store": STORE}, document_terms=(STORE,))


# --------------------------------------------------------------------------- #
# 3) 产品发射点：候选上界事件带身份键，且逐值等于既有 get_unit 解析结果
# --------------------------------------------------------------------------- #


def test_upper_bound_event_carries_unit_keys(synthetic_index, tmp_path):
    """红→绿主用例：改前事件没有该键；改后有，且每个值形如 ``sheet:...:row:<数字>``。"""

    expected_keys = _seed_rows(synthetic_index, 3)
    engine = _engine(synthetic_index, tmp_path)

    ids, payload = _emit(engine, **RECORD_CALL)
    assert payload["scope"] == UPPER_BOUND_SCOPE
    assert payload["unit_ids"] == sorted(ids)
    assert len(ids) == 3, ids

    assert KEYS_KEY in payload, "候选上界事件必须带候选单元身份"
    keys = payload[KEYS_KEY]
    assert isinstance(keys, list) and len(keys) == 3, keys
    assert keys == sorted(keys), "身份列表必须确定性排序"
    assert set(keys) == expected_keys, (keys, expected_keys)
    for key in keys:
        assert isinstance(key, str)
        assert ROW_KEY_RE.match(key), key
        assert key.startswith("sheet:合成表:row:"), key
    assert payload[TRUNC_KEY] is False

    # 逐值对齐既有解析路径：每个 unit_id 的 unit_key 都在列表里。
    resolved = {str(synthetic_index.get_unit(unit_id).unit_key) for unit_id in ids}
    assert set(keys) == resolved


def test_candidate_unit_keys_skip_unresolvable_ids(synthetic_index):
    """无法解析身份的 unit 直接跳过：不报错、不填占位。"""

    _seed_rows(synthetic_index, 1)
    keys, truncated = qa_service._candidate_unit_keys(  # noqa: SLF001 - 直接测身份解析辅助
        synthetic_index, ["U-does-not-exist", "U-keys-row-00"]
    )
    assert keys == ["sheet:合成表:row:2"]
    assert truncated is False
    assert "" not in keys and None not in keys


def test_candidate_unit_keys_truncate_at_32(synthetic_index, tmp_path):
    expected_keys = _seed_rows(synthetic_index, MAX_KEYS + 8)
    engine = _engine(synthetic_index, tmp_path)

    ids, payload = _emit(engine, **RECORD_CALL)
    assert len(ids) == MAX_KEYS + 8, len(ids)
    keys = payload[KEYS_KEY]
    assert len(keys) == MAX_KEYS, keys
    assert payload[TRUNC_KEY] is True
    assert set(keys) == set(sorted(expected_keys)[:MAX_KEYS])
    assert all(ROW_KEY_RE.match(key) for key in keys)


def test_candidate_unit_keys_not_truncated_at_boundary(synthetic_index, tmp_path):
    expected_keys = _seed_rows(synthetic_index, MAX_KEYS)
    engine = _engine(synthetic_index, tmp_path)

    _ids, payload = _emit(engine, **RECORD_CALL)
    assert len(payload[KEYS_KEY]) == MAX_KEYS
    assert set(payload[KEYS_KEY]) == expected_keys
    assert payload[TRUNC_KEY] is False


def test_empty_candidate_upper_bound_carries_empty_key_list(vector_disabled_index, tmp_path):
    _seed_rows(vector_disabled_index, 2)
    engine = _engine(vector_disabled_index, tmp_path)

    ids, payload = _emit(engine, mode="document", terms=("不存在的检索词",))
    assert ids == set(), ids
    assert payload["unit_ids"] == []
    assert payload[KEYS_KEY] == []
    assert payload[TRUNC_KEY] is False


def test_identity_keys_are_scope_gated_at_the_producer(synthetic_index):
    """只有 ``rag_candidate_upper_bound`` 才建键；其它 scope 一律空字典。"""

    _seed_rows(synthetic_index, 1)
    unit_id = "U-keys-row-00"
    assert (
        qa_service._candidate_unit_key_fields(  # noqa: SLF001 - scope 门的唯一落点
            "legacy_retrieve_initial", synthetic_index, [unit_id]
        )
        == {}
    )
    assert (
        qa_service._candidate_unit_key_fields(  # noqa: SLF001
            "legacy_retrieve_expanded", synthetic_index, [unit_id]
        )
        == {}
    )
    fields = qa_service._candidate_unit_key_fields(  # noqa: SLF001
        UPPER_BOUND_SCOPE, synthetic_index, [unit_id]
    )
    assert fields == {KEYS_KEY: ["sheet:合成表:row:2"], TRUNC_KEY: False}


def test_identity_keys_are_not_built_when_capture_is_closed(synthetic_index, tmp_path, monkeypatch):
    """观察关闭：不发事件、不建键、也不做身份解析；候选集与默认入口逐值相同。"""

    _seed_rows(synthetic_index, 3)
    engine = _engine(synthetic_index, tmp_path)
    emitted: list[tuple[str, dict[str, Any]]] = []
    resolved: list[str] = []
    monkeypatch.setattr(qa_service, "capture_enabled", lambda: False)
    monkeypatch.setattr(
        qa_service, "emit_capture_event", lambda kind, **payload: emitted.append((kind, payload))
    )
    monkeypatch.setattr(
        RagIndex, "get_unit", lambda self, unit_id: resolved.append(str(unit_id))
    )

    ids = engine.candidate_unit_ids_for_intent(**RECORD_CALL)
    assert ids == {f"U-keys-row-{offset:02d}" for offset in range(3)}, ids
    assert emitted == [], "观察关闭时不得发事件，也就不建候选身份键"
    assert resolved == [], "观察关闭时不得为观测做任何身份解析"


def test_capture_does_not_change_candidate_ids(synthetic_index, tmp_path):
    """同一输入，开/关观测两次调用返回的候选 id 集合逐值相同（纯观测）。"""

    _seed_rows(synthetic_index, 6)
    engine = _engine(synthetic_index, tmp_path)

    ids_off = engine.candidate_unit_ids_for_intent(**RECORD_CALL)
    assert cap.capture_enabled() is False
    ids_on, payload = _emit(engine, **RECORD_CALL)
    assert ids_off == ids_on
    assert payload["unit_ids"] == sorted(ids_off)


# --------------------------------------------------------------------------- #
# 4) 冻结闭包：从共享白名单读键集，旧 envelope 无该键时逐值不变
# --------------------------------------------------------------------------- #


def test_frozen_closures_read_the_shared_capture_whitelist() -> None:
    assert hard.CAPTURE_EVENT_FIELDS is cap.EVENT_FIELDS
    assert esp_frozen.EVENT_FIELDS is cap.EVENT_FIELDS
    assert KEYS_KEY in hard.CAPTURE_EVENT_FIELDS["retrieval_observed"]
    assert TRUNC_KEY in hard.CAPTURE_EVENT_FIELDS["retrieval_observed"]


def test_empty_scope_proof_accepts_new_optional_keys_and_keeps_legacy_result() -> None:
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
    assert KEYS_KEY not in payload and TRUNC_KEY not in payload

    # 带合法身份键的 envelope 仍通过；类型/值非法则同一清洗口径 fail-closed。
    payload[KEYS_KEY] = ["sheet:合成表:row:2"]
    payload[TRUNC_KEY] = False
    assert esp.empty_use_scope_proof(envelope) == (True, esp.EMPTY_USE_SCOPE_OK)

    payload[KEYS_KEY] = "sheet:合成表:row:2"
    assert esp.empty_use_scope_proof(envelope) != (True, esp.EMPTY_USE_SCOPE_OK)

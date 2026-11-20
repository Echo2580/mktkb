"""T207-REASON-CAPTURE-R1：MODEL_OUTPUT_INVALID 固定子因进入 answer_result 证据。

合成反例，零真实模型/外部出站；走实际产品 ask() -> 固定事件 -> 采集封装 ->
认证密文写入/严格读回。不 patch 被验函数（_model_failure_result /
safe_model_failure_reason / 采集链），不把分类/校验返回值直接设为通过。

红例（修复前）：已登记子因只进 model_failure trace span，answer_result.reason=None。
绿例（修复后）：仅 MODEL_OUTPUT_INVALID 承接安全固定子因；其余错误/成功语义不变。
"""

from __future__ import annotations

import hashlib
import json
import sys
import uuid
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

_TESTS_DIR = Path(__file__).resolve().parents[1]
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

from acceptance.support.netguard import t09_network_guard  # noqa: E402,F401

from mktkb.providers.types import (  # noqa: E402
    MODEL_FAILURE_REASONS,
    ModelBudgetRefused,
    ModelError,
    ModelNotConfigured,
    ModelOutputInvalid,
    ModelTimeout,
    ModelUnavailable,
    _MODEL_FAILURE_MESSAGES,
    safe_model_failure_reason,
)
from mktkb.conversations import service as conversation_service  # noqa: E402
from mktkb.evaluation.p2_evidence_io import (  # noqa: E402
    EvidenceIOError,
    read_encrypted_evidence,
)
from mktkb.evaluation.product_adapter import (  # noqa: E402
    IngestSource,
    MockChatBackend,
)
from evaluation.test_p2_evidence_capture_e2e import (  # noqa: E402
    D01,
    D04,
    _adapter,
    _bindings,
    _dataset,
    _writer,
    asyncio_test,
)

pytestmark = pytest.mark.usefixtures("t09_network_guard")

QUESTION = "城东店的宣传海报在哪里？"
SECRET = "P2REASON_SECRET_DO_NOT_EXPORT_9f3a"


def _message_for_reason(reason: str) -> str:
    """从真实登记映射取一个消息；unknown 用未登记哨兵（验证回退）。"""
    if reason == "unknown":
        return SECRET + "_UNREGISTERED"
    for message, mapped in _MODEL_FAILURE_MESSAGES.items():
        if mapped == reason:
            return message
    raise AssertionError(f"no registered message for {reason}")


class _ReasonChatBackend(MockChatBackend):
    """合成 provider 传输：抛出真实 ModelOutputInvalid（走真实 ModelError 映射）。

    不是 patch 被验函数：异常由真实 ModelError.__init__ 计算 failure_reason，
    经真实 DeepSeekClient 传输边界 -> _call_model -> ask() -> _model_failure_result。
    """

    def __init__(self, exc: Exception) -> None:
        super().__init__()
        self.exc = exc

    async def _handle(self, request):  # noqa: ANN001
        payload = json.loads(request.content.decode("utf-8"))
        async with self._lock:
            index = len(self.calls)
            self.calls.append(
                {
                    "index": index,
                    "purpose": self._purpose_of(payload),
                    "url": f"{request.url.scheme}://{request.url.host}{request.url.path}",
                    "question_sha256": hashlib.sha256(
                        str(payload).encode("utf-8")
                    ).hexdigest(),
                    "evidence": 0,
                    "evidence_ids": (),
                }
            )
        raise self.exc


async def _capture_turn(tmp_path: Path, *, chat, tag: str, question: str = QUESTION, capture: bool = True):
    bindings = _bindings(tag)
    writer = _writer(tmp_path, bindings) if capture else None
    adapter = _adapter(
        tmp_path / "run",
        writer=writer,
        bindings=bindings,
        sources=[IngestSource(D01), IngestSource(D04)],
        chat=chat,
        capture=capture,
    )
    try:
        await adapter.start()
        await adapter.ingest()
        conversation = await adapter.open_conversation()
        turn = await adapter.ask_turn(
            question,
            user_id="employee",
            conversation_id=conversation,
            client_request_id=str(uuid.uuid4()),
        )
        summary = adapter.evidence_capture_summary()
        network = adapter.network_stats()
        calls = chat.call_count
    finally:
        await adapter.close()
    readback = []
    if writer is not None:
        for record in writer.written:
            if record["kind"] == "turn":
                readback.append(
                    read_encrypted_evidence(
                        Path(record["path"]), key=writer.key, expected_bindings=writer.bindings
                    )
                )
    return turn, readback, summary, network, calls, writer


def _answer_result_reasons(evidence: dict) -> list:
    return [
        event["payload"]["reason"]
        for event in evidence["capture"]["events"]
        if event["kind"] == "answer_result"
    ]


# --------------------------------------------------------------------------- #
# 行 1：每个已登记原因 -> 实际事件 + 认证密文读回一致（真实异常构造验证现有映射）
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("reason", list(MODEL_FAILURE_REASONS))
@asyncio_test
async def test_each_registered_reason_preserved_through_ciphertext(tmp_path: Path, reason: str) -> None:
    message = _message_for_reason(reason)
    exc = ModelOutputInvalid(message)
    # 真实异常构造：failure_reason 由真实登记映射计算，而非手工设值。
    assert exc.failure_reason == reason
    turn, readback, summary, network, calls, writer = await _capture_turn(
        tmp_path, chat=_ReasonChatBackend(exc), tag=f"reason-{reason}"
    )
    assert turn.kind == "service_error"
    assert turn.error_code == "MODEL_OUTPUT_INVALID"
    assert network["outbound_attempts"] == 0
    assert summary is not None and summary["blocked"] is False
    assert len(readback) == 1
    assert _answer_result_reasons(readback[0]) == [reason]
    # 密文与事件均不回显原始消息/秘密。
    assert message not in json.dumps(readback[0], ensure_ascii=False)
    for record in writer.written:
        assert message.encode("utf-8") not in Path(record["path"]).read_bytes()


# --------------------------------------------------------------------------- #
# 行 2：来源/原值/其他对象/记录事实反例仍被拒绝，码/文案不变，准入不放宽
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "reason",
    ["source_identity", "exact_value", "unsupported_value", "entity_scope",
     "record_facts", "record_source", "record_entity"],
)
@asyncio_test
async def test_admission_counterexamples_still_rejected_unchanged(tmp_path: Path, reason: str) -> None:
    from mktkb import copy as copy_module

    exc = ModelOutputInvalid(_message_for_reason(reason))
    turn, readback, _, _, _, _ = await _capture_turn(
        tmp_path, chat=_ReasonChatBackend(exc), tag=f"admit-{reason}"
    )
    expected_text = copy_module.service_error_text("MODEL_OUTPUT_INVALID", retryable=True)
    assert turn.kind == "service_error"
    assert turn.error_code == "MODEL_OUTPUT_INVALID"
    assert turn.retryable is True
    assert turn.text == expected_text
    assert _answer_result_reasons(readback[0]) == [reason]


@asyncio_test
async def test_product_side_admission_rejection_keeps_model_output_ok(tmp_path: Path) -> None:
    """真实产品侧准入拒绝（model_output.status=ok）：记录型自由文本被拒，子因保全。

    准入顺序：精确原值校验先于记录事实校验（service.py 的 _validate_answer），
    自由文本不含字段原值 → 真实拒绝子因是 exact_value。
    """
    from mktkb.evaluation.product_adapter import ChatBehavior

    chat = MockChatBackend(
        behaviors=(ChatBehavior(kind="answer", answer="这是一段自由文本，不是可验证的字段事实陈述。"),)
    )
    turn, readback, _, network, _, _ = await _capture_turn(
        tmp_path, chat=chat, tag="product-admission"
    )
    assert network["outbound_attempts"] == 0
    assert turn.kind == "service_error"
    assert turn.error_code == "MODEL_OUTPUT_INVALID"
    events = readback[0]["capture"]["events"]
    model_status = [e["payload"]["status"] for e in events if e["kind"] == "model_output"]
    assert "ok" in model_status
    assert _answer_result_reasons(readback[0]) == ["exact_value"]


# --------------------------------------------------------------------------- #
# 行 3：未登记/秘密/坏类型 -> unknown，无任意文本/repr/秘密回显
# --------------------------------------------------------------------------- #


@asyncio_test
async def test_unregistered_secret_message_maps_to_unknown_without_echo(tmp_path: Path) -> None:
    exc = ModelOutputInvalid(SECRET)
    assert exc.failure_reason == "unknown"
    turn, readback, _, _, _, writer = await _capture_turn(
        tmp_path, chat=_ReasonChatBackend(exc), tag="unknown-secret"
    )
    assert turn.error_code == "MODEL_OUTPUT_INVALID"
    assert _answer_result_reasons(readback[0]) == ["unknown"]
    blob = json.dumps(readback[0], ensure_ascii=False)
    assert SECRET not in blob
    for record in writer.written:
        assert SECRET.encode("utf-8") not in Path(record["path"]).read_bytes()


def test_bad_type_and_custom_object_reason_fall_back_to_unknown() -> None:
    from mktkb.observability.tracer import start_trace

    class Repo:
        def write_best_effort(self, trace, spans):
            self.trace, self.spans = trace, spans

    class Poison:
        def __repr__(self):
            return SECRET

    for bad in (object(), Poison(), 123, None, ["source_identity"], {"x": "source_identity"}):
        exc = ModelOutputInvalid("记录型回答不是可验证的字段事实陈述")
        exc.failure_reason = bad  # 直接注入坏类型，验证 safe_model_failure_reason 回退
        repo = Repo()
        with start_trace(http_request_id="synthetic", mode="local", scope="synthetic", repo=repo):
            result = conversation_service._model_failure_result(exc, 7)
        assert result.reason == "unknown"
        span = next(s for s in repo.spans if s.name == "model_failure")
        assert json.loads(span.attributes_json) == {"model_failure_reason": "unknown"}
        assert SECRET not in span.attributes_json


def test_direct_enum_injection_only_proves_passthrough() -> None:
    """直接枚举注入证明传递；与上面真实异常构造互补（任务书 B5 行 1）。"""
    from mktkb.observability.tracer import start_trace

    class Repo:
        def write_best_effort(self, trace, spans):
            self.trace, self.spans = trace, spans

    for reason in MODEL_FAILURE_REASONS:
        exc = ModelOutputInvalid("记录型回答不是可验证的字段事实陈述")
        exc.failure_reason = reason
        repo = Repo()
        with start_trace(http_request_id="synthetic", mode="local", scope="synthetic", repo=repo):
            result = conversation_service._model_failure_result(exc, 7)
        assert result.reason == reason
        assert result.error_code == "MODEL_OUTPUT_INVALID"


# --------------------------------------------------------------------------- #
# 行 4：非目标错误与成功结果语义不变（reason 保持原样）
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "exc,code,retryable",
    [
        (ModelTimeout(), "MODEL_TIMEOUT", True),
        (ModelUnavailable(), "MODEL_UNAVAILABLE", True),
        (ModelNotConfigured(), "MODEL_NOT_CONFIGURED", False),
        (ModelBudgetRefused(), "MODEL_BUDGET_REFUSED", False),
    ],
)
@asyncio_test
async def test_non_target_errors_keep_reason_none(tmp_path: Path, exc, code, retryable) -> None:
    turn, readback, _, _, _, _ = await _capture_turn(
        tmp_path, chat=_ReasonChatBackend(exc), tag=f"nontarget-{code}"
    )
    assert turn.kind == "service_error"
    assert turn.error_code == code
    assert turn.retryable is retryable
    assert _answer_result_reasons(readback[0]) == [None]


@asyncio_test
async def test_normal_answer_and_not_found_reason_unchanged(tmp_path: Path) -> None:
    turn, readback, _, _, _, _ = await _capture_turn(
        tmp_path, chat=MockChatBackend(), tag="normal-answer", question="活动策划需要哪些步骤？"
    )
    assert turn.kind == "answer"
    assert _answer_result_reasons(readback[0]) == [None]

    turn2, readback2, _, _, _, _ = await _capture_turn(
        tmp_path / "nf", chat=MockChatBackend(), tag="not-found", question="火星店的宣传海报在哪里？"
    )
    assert turn2.kind in {"not_found", "clarification"}
    # not_found 的 reason 沿用既有分支（非 MODEL_OUTPUT_INVALID 子因）。
    for reason in _answer_result_reasons(readback2[0]):
        assert reason is None or reason not in set(MODEL_FAILURE_REASONS)


# --------------------------------------------------------------------------- #
# 行 5：不同请求不串因 / 关闭采集 / 幂等重放
# --------------------------------------------------------------------------- #


@asyncio_test
async def test_distinct_requests_do_not_cross_contaminate(tmp_path: Path) -> None:
    bindings = _bindings("multi-reason")
    writer = _writer(tmp_path, bindings)
    chat = _ReasonChatBackend(ModelOutputInvalid(_message_for_reason("exact_value")))
    adapter = _adapter(
        tmp_path / "run", writer=writer, bindings=bindings,
        sources=[IngestSource(D01), IngestSource(D04)], chat=chat,
    )
    try:
        await adapter.start()
        await adapter.ingest()
        conversation = await adapter.open_conversation()
        # 同一合成传输在回合间切换真实异常，验证逐回合独立、不串因。
        for reason in ("exact_value", "entity_scope", "record_facts"):
            chat.exc = ModelOutputInvalid(_message_for_reason(reason))
            turn = await adapter.ask_turn(
                QUESTION, user_id="employee", conversation_id=conversation,
                client_request_id=str(uuid.uuid4()),
            )
            assert turn.error_code == "MODEL_OUTPUT_INVALID"
        session = adapter._evidence_session
        reasons = []
        for record in session.turns:
            reasons.extend(_answer_result_reasons(record))
        assert reasons == ["exact_value", "entity_scope", "record_facts"]
    finally:
        await adapter.close()


@asyncio_test
async def test_capture_off_still_works(tmp_path: Path) -> None:
    turn, readback, summary, network, _, _ = await _capture_turn(
        tmp_path, chat=_ReasonChatBackend(ModelOutputInvalid("回答未保留精确字段原值")),
        tag="capture-off", capture=False,
    )
    assert turn.kind == "service_error"
    assert turn.error_code == "MODEL_OUTPUT_INVALID"
    assert summary is None
    assert readback == []
    assert network["outbound_attempts"] == 0


@asyncio_test
async def test_idempotent_replay_does_not_fabricate_model_error(tmp_path: Path) -> None:
    bindings = _bindings("replay-reason")
    writer = _writer(tmp_path, bindings)
    chat = _ReasonChatBackend(ModelOutputInvalid("回答未保留精确字段原值"))
    adapter = _adapter(
        tmp_path / "run", writer=writer, bindings=bindings,
        sources=[IngestSource(D01), IngestSource(D04)], chat=chat,
    )
    request_id = str(uuid.uuid4())
    try:
        await adapter.start()
        await adapter.ingest()
        conversation = await adapter.open_conversation()
        await adapter.ask_turn(QUESTION, user_id="employee", conversation_id=conversation, client_request_id=request_id)
        calls_after_first = chat.call_count
        replayed = await adapter.ask_turn(QUESTION, user_id="employee", conversation_id=conversation, client_request_id=request_id)
        assert replayed.http_status == 200
        assert chat.call_count == calls_after_first  # 重放不增加模型调用
        session = adapter._evidence_session
        statuses = [t["completeness"]["status"] for t in session.turns]
        assert statuses == ["complete", "replayed"]
    finally:
        await adapter.close()


# --------------------------------------------------------------------------- #
# 行 6：密文读回/结构校验安全门仍生效，reason 字段不能借坏密文/坏绑定通过
# --------------------------------------------------------------------------- #


@asyncio_test
async def test_ciphertext_gates_still_reject_bad_key_binding_and_tamper(tmp_path: Path) -> None:
    bindings = _bindings("gates")
    writer = _writer(tmp_path, bindings)
    adapter = _adapter(
        tmp_path / "run", writer=writer, bindings=bindings,
        sources=[IngestSource(D01), IngestSource(D04)],
        chat=_ReasonChatBackend(ModelOutputInvalid("回答未保留精确字段原值")),
    )
    try:
        await adapter.start()
        await adapter.ingest()
        conversation = await adapter.open_conversation()
        await adapter.ask_turn(QUESTION, user_id="employee", conversation_id=conversation, client_request_id=str(uuid.uuid4()))
    finally:
        await adapter.close()
    record = next(r for r in writer.written if r["kind"] == "turn")
    path = Path(record["path"])
    # 正常读回：子因可读。
    good = read_encrypted_evidence(path, key=writer.key, expected_bindings=writer.bindings)
    assert _answer_result_reasons(good) == ["exact_value"]
    # 坏 key。
    with pytest.raises(EvidenceIOError):
        read_encrypted_evidence(path, key=Fernet.generate_key(), expected_bindings=writer.bindings)
    # 坏绑定。
    bad_bindings = dict(writer.bindings)
    bad_bindings["run_id"] = "other-run"
    with pytest.raises(EvidenceIOError):
        read_encrypted_evidence(path, key=writer.key, expected_bindings=bad_bindings)
    # 篡改密文。
    token = bytearray(path.read_bytes())
    token[-1] ^= 0x01
    tampered = tmp_path / "tampered.bin"
    tampered.write_bytes(bytes(token))
    with pytest.raises(EvidenceIOError):
        read_encrypted_evidence(tampered, key=writer.key, expected_bindings=writer.bindings)


# --------------------------------------------------------------------------- #
# B4：trace outcome reason 变化的边界评估 —— 对外诊断契约不扩大
# --------------------------------------------------------------------------- #


def test_b4_service_error_span_contract_is_reason_independent() -> None:
    """legacy service_error 的必需 Span 集合与 reason 无关（子因不扩大/缩小契约）。"""
    from mktkb.observability.contracts import required_spans

    base = required_spans("legacy", "service_error")
    for reason in (*MODEL_FAILURE_REASONS, None, "MODEL_OUTPUT_INVALID"):
        assert required_spans("legacy", "service_error", reason=reason) == base


def test_b4_legacy_outcome_carries_subreason_without_widening_diagnostics() -> None:
    """实际 _record_legacy_outcome：outcome=service_error、trace reason 维持既有
    error_code 口径（T104 契约不变）；固定子因只进 answer_result 证据；
    AskResult 不新增诊断字段。"""
    from mktkb.conversations.schemas import AskResult
    from mktkb.observability.contracts import required_spans
    from mktkb.observability.tracer import start_trace

    class Repo:
        def write_best_effort(self, trace, spans):
            self.trace, self.spans = trace, spans

    base = required_spans("legacy", "service_error")
    for reason in MODEL_FAILURE_REASONS:
        exc = ModelOutputInvalid(_message_for_reason(reason))
        repo = Repo()
        with start_trace(
            http_request_id="synthetic", mode="local", scope="synthetic",
            path="legacy", repo=repo,
        ) as trace:
            result = conversation_service._model_failure_result(exc, 7)
            ask_result = AskResult(
                request_id=uuid.uuid4(), message_id=uuid.uuid4(),
                kind=result.kind, text=result.text, revision=result.revision,
                error_code=result.error_code, retryable=result.retryable,
            )
            conversation_service._record_legacy_outcome(trace, result, ask_result)
        assert result.reason == reason  # 内部承接：供 answer_result 证据
        assert repo.trace.outcome_kind == "service_error"
        assert repo.trace.reason == "MODEL_OUTPUT_INVALID"  # 对外口径不变
        assert repo.trace.error_code == "MODEL_OUTPUT_INVALID"
        assert required_spans(
            repo.trace.path, repo.trace.outcome_kind, reason=repo.trace.reason
        ) == base
        # model_failure Span 仍带安全子因（既有埋点不变）。
        span = next(s for s in repo.spans if s.name == "model_failure")
        assert json.loads(span.attributes_json) == {"model_failure_reason": reason}
        # AskResult 对外字段不新增诊断项（schema 冻结）。
        assert set(ask_result.model_dump()) == {
            "request_id", "message_id", "kind", "text", "revision", "sources",
            "candidates", "conflicts", "missing_fields", "pagination",
            "error_code", "retryable",
        }
        assert not hasattr(ask_result, "reason")
        assert not hasattr(ask_result, "model_failure_reason")
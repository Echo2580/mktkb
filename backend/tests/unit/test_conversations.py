"""T06 会话编排单元测试：载荷摘要、意图规则、输出校验与总预算（不打网络、不建库）。"""

from __future__ import annotations

import asyncio
import time
import uuid
from types import SimpleNamespace

import pytest

from mktkb.conversations import intent as intent_module
from mktkb.conversations import service
from mktkb.providers.types import (
    CompletionInput,
    CompletionOutput,
    ModelOutputInvalid,
    ModelTimeout,
)


class _Gateway:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.calls = 0
        self.error = error

    async def complete(self, request: CompletionInput, *, timeout_seconds: float) -> CompletionOutput:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return CompletionOutput(text="ok", source_ids=("s",))


def _run(coro):
    return asyncio.run(coro)


def test_payload_digest_is_stable_and_question_sensitive():
    first = service.payload_digest("城东店的宣传海报在哪里？")
    assert first == service.payload_digest("城东店的宣传海报在哪里？")
    assert first != service.payload_digest("城西店的宣传海报在哪里？")
    assert len(first) == 64


def _lexicon():
    return intent_module.EntityLexicon(
        store_labels=("城东店", "城西店"),
        item_labels=("宣传海报",),
        alias_to_labels={"海报": ("宣传海报",), "展示架": ("展架",)},
    )


def test_intent_maps_entities_fields_and_alias():
    plan = intent_module.parse_question("城东店的宣传海报在哪里？", lexicon=_lexicon())
    assert plan.clarification is None
    assert plan.intent is not None and plan.intent.mode == "record"
    assert plan.intent.entity_filters == {"store": "城东店", "item": "宣传海报"}
    assert plan.requested_fields == ("位置",)

    alias = intent_module.parse_question("海报在哪？", lexicon=_lexicon())
    assert alias.intent.entity_filters == {"item": "宣传海报"}


def test_intent_store_level_field_does_not_inherit_item():
    plan = intent_module.parse_question(
        "城东店的联系人是谁？",
        lexicon=_lexicon(),
        context_entities={"store": "城西店", "item": "宣传海报"},
    )
    assert plan.entities == {"store": "城东店"}, "新明确门店覆盖旧门店，且门店级字段不继承旧物品"
    assert plan.intent.entity_filters == {"store": "城东店"}


def test_intent_ellipsis_inherits_context_entities():
    plan = intent_module.parse_question(
        "它的位置呢？",
        lexicon=_lexicon(),
        context_entities={"store": "城东店", "item": "宣传海报"},
    )
    assert plan.entities == {"store": "城东店", "item": "宣传海报"}


def test_intent_multiple_stores_requires_clarification():
    plan = intent_module.parse_question("城东店和城西店的海报在哪？", lexicon=_lexicon())
    assert plan.clarification
    labels = [label for label, _followup in plan.candidates]
    assert labels == ["城东店", "城西店"]


def test_intent_missing_only_field_is_not_record_and_not_inherited():
    plan = intent_module.parse_question(
        "城东店几点营业？", lexicon=_lexicon(), context_entities={"store": "城西店"}
    )
    assert plan.requested_fields == ()
    assert plan.missing_fields == ("营业时间",)
    assert plan.mode == "document"


def test_intent_unknown_store_is_explicit_no_evidence():
    plan = intent_module.parse_question("城南店的联系人是谁？", lexicon=_lexicon())
    assert plan.unknown_store == "城南店"
    assert plan.intent.entity_filters == {"store": "城南店"}


def test_intent_document_terms_drop_stopwords():
    plan = intent_module.parse_question("领取活动物料需要哪些步骤？", lexicon=_lexicon())
    assert plan.intent.mode == "document"
    assert "领取" in plan.intent.terms and "活动" in plan.intent.terms
    assert "哪些" not in plan.intent.terms and "需要" not in plan.intent.terms


def test_validate_terms_rejects_urls_sql_and_too_many():
    with pytest.raises(ModelOutputInvalid):
        service._validate_terms(CompletionOutput(text="", query_terms=("https://evil.example",)))
    with pytest.raises(ModelOutputInvalid):
        service._validate_terms(CompletionOutput(text="", query_terms=("select * from users",)))
    with pytest.raises(ModelOutputInvalid):
        service._validate_terms(CompletionOutput(text="", query_terms=("/srv/secret",)))
    with pytest.raises(ModelOutputInvalid):
        service._validate_terms(CompletionOutput(text="", query_terms=tuple(f"t{index}" for index in range(13))))
    assert service._validate_terms(CompletionOutput(text="", query_terms=("宣传海报", " 海报 "))) == (
        "宣传海报",
        "海报",
    )


def test_validate_answer_rejects_forged_ids_and_missing_exact_values():
    allowed = {str(uuid.uuid4())}
    source_id = next(iter(allowed))
    facts = [("位置", "B区1号货架第二层")]
    ok = service._validate_answer(
        CompletionOutput(text="位置是B区1号货架第二层。", source_ids=(source_id,)), allowed, facts
    )
    assert ok == ("位置是B区1号货架第二层。", [source_id])

    with pytest.raises(ModelOutputInvalid):
        service._validate_answer(
            CompletionOutput(text="位置是B区1号货架第二层。", source_ids=(str(uuid.uuid4()),)), allowed, facts
        )
    with pytest.raises(ModelOutputInvalid):
        service._validate_answer(CompletionOutput(text="位置是A区。", source_ids=(source_id,)), allowed, facts)
    with pytest.raises(ModelOutputInvalid):
        service._validate_answer(CompletionOutput(text="位置是B区1号货架第二层。", source_ids=()), allowed, facts)


def test_total_budget_blocks_call_without_invoking_gateway(monkeypatch):
    gateway = _Gateway()
    monkeypatch.setattr(service, "monotonic", lambda: 100.0)
    with pytest.raises(ModelTimeout):
        _run(service._call_model(gateway, CompletionInput(purpose="answer", question="q"), deadline=50.0))
    assert gateway.calls == 0


def test_total_budget_after_slow_call_maps_timeout(monkeypatch):
    ticks = iter([100.0, 200.0])
    monkeypatch.setattr(service, "monotonic", lambda: next(ticks))
    gateway = _Gateway()
    with pytest.raises(ModelTimeout):
        _run(service._call_model(gateway, CompletionInput(purpose="answer", question="q"), deadline=150.0))
    assert gateway.calls == 1, "超时不得自动重发付费调用"


def test_model_errors_are_not_converted_to_not_found(monkeypatch):
    from mktkb.providers.types import ModelUnavailable

    gateway = _Gateway(error=ModelUnavailable("x"))
    monkeypatch.setattr(service, "monotonic", lambda: 10.0)
    with pytest.raises(ModelUnavailable):
        _run(service._call_model(gateway, CompletionInput(purpose="answer", question="q"), deadline=20.0))


def test_budget_refusal_is_mapped_to_its_own_code_and_chinese_text(monkeypatch):
    """S4 工程债 C：预算/授权拒绝必须与“服务不可用”分码，并给出可行动的中文提示。"""
    from mktkb.providers.types import ModelBudgetRefused, ModelUnavailable

    gateway = _Gateway(error=ModelBudgetRefused("预算/授权闸门拒绝：BudgetExceeded"))
    monkeypatch.setattr(service, "monotonic", lambda: 10.0)
    with pytest.raises(ModelBudgetRefused) as excinfo:
        _run(service._call_model(gateway, CompletionInput(purpose="answer", question="q"), deadline=20.0))
    # 不能被“except Exception -> ModelUnavailable”吞成服务不可用
    assert not isinstance(excinfo.value, ModelUnavailable)
    assert excinfo.value.code == "MODEL_BUDGET_REFUSED"
    assert excinfo.value.retryable is False

    text = service._model_error_text("MODEL_BUDGET_REFUSED")
    assert text == "当前预算或授权额度不足，本次未发送请求，请联系管理员处理。"
    assert "预算" in text and "授权" in text and "未发送请求" in text
    # 与真正的供应商不可用文案不同，且未被替换掉
    assert service._model_error_text("MODEL_UNAVAILABLE").startswith("模型服务暂不可用")

    # 生产映射：_ask 里正是用 exc.code / _model_error_text(exc.code) / exc.retryable 构造结果
    result = service._service_error(
        excinfo.value.code,
        service._model_error_text(excinfo.value.code),
        excinfo.value.retryable,
        0,
    )
    assert result.kind == "service_error"
    assert result.error_code == "MODEL_BUDGET_REFUSED"
    assert result.retryable is False
    assert "未发送请求" in result.text


# ---------------------------------------------------------------- R1：事实准入与在途取消


def _unit(source_id: str, text: str, fields: dict) -> SimpleNamespace:
    """与 SourceUnit 同形的只读证据替身（id/text/fields），不建库、不联网。"""
    return SimpleNamespace(id=uuid.UUID(source_id), text=text, fields=fields)


_POSITIONS_ID = "11111111-1111-1111-1111-111111111111"
_STORES_ID = "22222222-2222-2222-2222-222222222222"
_POSITIONS_ROW = "标识: P01 | 门店: 城东店 | 物品: 宣传海报 | 别名: 海报 | 位置: B区1号货架第二层"
_STORES_ROW = (
    "标识: S01 | 店家: 城东店 | 联系人: 模拟联系人·陈宁 | 电话: 010-00000001 | "
    "地址: 示例市示例路18号（模拟） | 合作状态: 合作中"
)


def _positions_unit() -> SimpleNamespace:
    return _unit(
        _POSITIONS_ID,
        _POSITIONS_ROW,
        {"标识": "P01", "门店": "城东店", "物品": "宣传海报", "别名": "海报", "位置": "B区1号货架第二层"},
    )


def _stores_unit() -> SimpleNamespace:
    return _unit(
        _STORES_ID,
        _STORES_ROW,
        {
            "标识": "S01",
            "店家": "城东店",
            "联系人": "模拟联系人·陈宁",
            "电话": "010-00000001",
            "地址": "示例市示例路18号（模拟）",
            "合作状态": "合作中",
        },
    )


def test_validate_answer_rejects_extra_unattested_phone():
    """PM06-01：包含正确电话但夹带第二个未取证电话 -> MODEL_OUTPUT_INVALID。"""
    unit = _stores_unit()
    output = CompletionOutput(
        text="城东店的联系电话是010-00000001和010-99999999。", source_ids=(str(unit.id),)
    )
    with pytest.raises(ModelOutputInvalid):
        service._validate_answer(
            output, {str(unit.id)}, [("电话", "010-00000001")], evidence=[unit]
        )


def test_validate_answer_rejects_negated_attested_location():
    """PM06-01：否定正确位置并给出未取证位置 -> MODEL_OUTPUT_INVALID。"""
    unit = _positions_unit()
    output = CompletionOutput(
        text="城东店的宣传海报不在B区1号货架第二层，而在Z区9号柜。", source_ids=(str(unit.id),)
    )
    with pytest.raises(ModelOutputInvalid):
        service._validate_answer(
            output, {str(unit.id)}, [("位置", "B区1号货架第二层")], evidence=[unit]
        )


def test_validate_answer_accepts_exact_values_without_extra_facts():
    """正确对照：只含引用来源原值的回答仍成功。"""
    unit = _stores_unit()
    text = "城东店的联系电话是010-00000001。"
    output = CompletionOutput(text=text, source_ids=(str(unit.id),))
    assert service._validate_answer(
        output, {str(unit.id)}, [("电话", "010-00000001")], evidence=[unit]
    ) == (text, [str(unit.id)])


def test_validate_answer_rejects_value_from_uncited_source():
    """错误来源子集：只引用位置来源，却写出只存在于店家来源的电话。"""
    positions = _positions_unit()
    stores = _stores_unit()
    output = CompletionOutput(
        text="城东店的联系电话是010-00000001。", source_ids=(str(positions.id),)
    )
    with pytest.raises(ModelOutputInvalid):
        service._validate_answer(
            output,
            {str(positions.id), str(stores.id)},
            [("电话", "010-00000001")],
            evidence=[positions, stores],
        )


def test_validate_answer_rejects_other_store_label_in_record_answer():
    """混合门店：回答把已取证的原值挂到另一个门店名下。"""
    unit = _stores_unit()
    output = CompletionOutput(
        text="城西店的联系电话是010-00000001。", source_ids=(str(unit.id),)
    )
    with pytest.raises(ModelOutputInvalid):
        service._validate_answer(
            output,
            {str(unit.id)},
            [("电话", "010-00000001")],
            evidence=[unit],
            other_store_labels=("城西店",),
        )


def test_record_units_cover_store_rows_and_rows_with_items():
    """候选行范围：字段原值必须与该行原值逐字相等，未引用行不能为回答背书。"""
    stores = _stores_unit()
    positions = _positions_unit()
    plan = SimpleNamespace(entities={"store": "城东店"}, requested_fields=("电话",))
    facts = [("电话", "010-00000001")]
    selected = service._record_units([positions, stores], plan, facts)
    assert stores in selected
    assert positions not in selected, "位置行没有电话原值，不能为电话回答背书"
    assert service._record_facts(
        "城东店的联系电话是010-00000001。", selected, facts, object_label="城东店"
    )


class _SlowGateway:
    """忽略预算参数、持续等待的可控网关；用于证明在途调用会被总截止取消。"""

    def __init__(self) -> None:
        self.calls = 0

    async def complete(self, request, *, timeout_seconds: float) -> CompletionOutput:
        self.calls += 1
        await asyncio.sleep(0.5)
        return CompletionOutput(text="slow")


def test_call_model_cancels_inflight_call_at_absolute_deadline():
    """PM06-02：缩短总预算由自身 MODEL_TIMEOUT 及时结束，而不是外层保护超时。"""
    gateway = _SlowGateway()

    async def run():
        started = time.monotonic()
        try:
            await asyncio.wait_for(
                service._call_model(gateway, None, service.monotonic() + 0.03), timeout=0.18
            )
            actual = "returned"
        except ModelTimeout:
            actual = "MODEL_TIMEOUT"
        except asyncio.TimeoutError:
            actual = "PM_OUTER_GUARD_TIMEOUT"
        return actual, time.monotonic() - started

    actual, elapsed = _run(run())
    assert actual == "MODEL_TIMEOUT", actual
    assert gateway.calls == 1, "超时不得自动重发付费调用"
    assert elapsed < 0.18, elapsed


def test_call_model_bounds_slow_http_completion():
    """PM06-02：HTTP 模拟慢响应同样受同一绝对预算约束，取消后有界返回。"""
    import httpx

    from mktkb.providers.deepseek import DeepSeekClient

    async def handler(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.5)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": '{"answer": "x", "source_ids": ["a"]}'},
                    }
                ]
            },
        )

    client = DeepSeekClient(
        base_url="https://simulated.invalid",
        model="simulated",
        api_key="R1-FAKE-NOT-REAL",
        transport=httpx.MockTransport(handler),
    )

    async def run():
        started = time.monotonic()
        try:
            await service._call_model(
                client, CompletionInput(purpose="answer", question="q"), service.monotonic() + 0.05
            )
            return "returned", time.monotonic() - started
        except ModelTimeout:
            return "MODEL_TIMEOUT", time.monotonic() - started
        finally:
            await client.aclose()

    actual, elapsed = _run(run())
    assert actual == "MODEL_TIMEOUT", actual
    assert elapsed < 0.5, elapsed


# ---------------------------------------------------------------- R2：记录型事实准入（结构约束）


def _record_or_fail(unit, text: str, requested: str, object_label: str = "") -> list:
    """被测入口：记录型模型文本不满足可验证结构时抛 ModelOutputInvalid。"""
    label = requested
    value = str(unit.fields.get("电话") or unit.fields.get("位置") or "")
    facts = service._record_facts(text, [unit], [(label, value)], object_label=object_label)
    if facts is None:
        raise ModelOutputInvalid("记录型回答不是可验证的字段事实陈述")
    return facts


def _record_facts(unit, text: str, requested: str = "电话") -> list:
    return _record_or_fail(unit, text, requested)


def _location_unit(location: str = "B区1号货架第二层"):
    return _unit(
        _POSITIONS_ID,
        f"标识: P01 | 门店: 城东店 | 物品: 宣传海报 | 别名: 海报 | 位置: {location}",
        {"标识": "P01", "门店": "城东店", "物品": "宣传海报", "别名": "海报", "位置": location},
    )


def test_record_facts_reject_negated_attested_phone():
    """R2：'不是正确电话' 不是正向事实，即使原值子串存在也必须拒绝。"""
    with pytest.raises(ModelOutputInvalid):
        _record_facts(_stores_unit(), "城东店的联系电话不是010-00000001。")


def test_record_facts_reject_negated_attested_location_with_chinese_alternative():
    """R2：'不在正确位置，而在仓库深处' 必须拒绝（中文替代值同样不接受）。"""
    with pytest.raises(ModelOutputInvalid):
        _record_facts(
            _location_unit(), "城东店的宣传海报不在B区1号货架第二层，而在仓库深处。", "位置"
        )


def test_record_facts_reject_bare_value_without_relation():
    """无字段名/正关系词的裸值不被当作事实（否定与关系无法验证）。"""
    with pytest.raises(ModelOutputInvalid):
        _record_facts(_stores_unit(), "010-00000001")


def test_record_facts_accept_affirmative_exact_value():
    facts = _record_facts(_stores_unit(), "城东店的联系电话是010-00000001。")
    assert facts[0][0] == "电话"
    assert facts[0][1] == "010-00000001"


def test_record_facts_reject_conflicting_field_relation():
    """字段关系混合：用联系人字段名去挂电话值 -> 不是本次所求字段的事实。"""
    with pytest.raises(ModelOutputInvalid):
        _record_facts(_stores_unit(), "城东店的联系人是010-00000001。")


def test_record_facts_accept_multi_field_answer():
    unit = _stores_unit()
    facts = service._record_facts(
        "城东店的联系人：模拟联系人·陈宁；联系电话：010-00000001；合作状态：合作中。",
        [unit],
        [("联系人", "模拟联系人·陈宁"), ("电话", "010-00000001"), ("合作状态", "合作中")],
    )
    assert facts is not None
    assert {label for label, _value, _row in facts} == {"联系人", "电话", "合作状态"}


def test_record_facts_reject_extra_attested_value_not_asked():
    """已存在但不属于本次问题的原值也不能冒充本字段事实。"""
    with pytest.raises(ModelOutputInvalid):
        _record_facts(_stores_unit(), "城东店的联系电话是010-00000001和010-00000004。")


def test_record_facts_reject_mixed_location_value():
    with pytest.raises(ModelOutputInvalid):
        _record_facts(
            _location_unit(), "城东店的宣传海报在B区1号货架第二层和C区2号货架第一层。", "位置"
        )


def _multi_item_units():
    """同一门店多行：宣传海报与展架各自有位置，用于多字段/多值边界。"""
    return [
        _unit(
            _POSITIONS_ID,
            "标识: P01 | 门店: 城东店 | 物品: 宣传海报 | 位置: B区1号货架第二层",
            {"标识": "P01", "门店": "城东店", "物品": "宣传海报", "位置": "B区1号货架第二层"},
        ),
        _unit(
            "33333333-3333-3333-3333-333333333333",
            "标识: P03 | 门店: 城东店 | 物品: 展架 | 别名: 展示架 | 位置: A区2号货架底部",
            {"标识": "P03", "门店": "城东店", "物品": "展架", "别名": "展示架", "位置": "A区2号货架底部"},
        ),
    ]


def test_record_facts_reject_unasked_object_value():
    """问题只问宣传海报，回答却给出展架的位置（同门店其它行）-> 拒绝。"""
    units = _multi_item_units()
    facts = service._record_facts(
        "城东店宣传海报的位置：B区1号货架第二层；展架的位置：A区2号货架底部。",
        units,
        [("位置", "B区1号货架第二层")],
        object_label="城东店的宣传海报",
    )
    assert facts is None


def test_record_facts_accept_plain_affirmative_sentence():
    """正常正确陈述句（不含否定/替代）仍通过。"""
    facts = service._record_facts(
        "城东店的宣传海报在B区1号货架第二层。",
        [_location_unit()],
        [("位置", "B区1号货架第二层")],
        object_label="城东店的宣传海报",
    )
    assert facts is not None
    assert facts[0][0] == "位置"


# ---------------------------------------------------------------- R3：对象绑定与引用行收口


def _plan(store: str = "城东店", item: str | None = None, fields: tuple[str, ...] = ("电话",)):
    entities = {"store": store}
    if item:
        entities["item"] = item
    return SimpleNamespace(entities=entities, requested_fields=tuple(fields))


def _accepts(units, facts, text: str, object_label: str, plan) -> bool:
    """与 HTTP 路径同一收口：结构准入通过后还要满足引用行背书与对象一致。

    HTTP 路径先用 `_record_units` 把"持有本次问题原值的行"限定为可背书行，这里同样限定。
    """
    rows = service._record_units(units, plan, facts)
    parsed = service._record_facts(text, rows, facts, object_label=object_label)
    if not parsed:
        return False
    subject = service._validated_subject(parsed, rows)
    return bool(subject) and service._subject_matches_plan(plan, subject)


def test_record_facts_reject_unknown_store_prefix():
    """R3：未知门店前缀（既不是本问门店，也不是任何已知实体）同样不可验证。"""
    units = [_stores_unit()]
    assert service._record_facts(
        "城南店的联系电话是010-00000001。", units, [("电话", "010-00000001")], object_label="城东店"
    ) is None


def test_record_facts_reject_attached_ownership_relation():
    """R3：附加关系（"属于X的…"）不是本问对象的直接陈述，拒绝。"""
    units = [_stores_unit()]
    assert service._record_facts(
        "属于城西店的电话是010-00000001。", units, [("电话", "010-00000001")], object_label="城东店"
    ) is None


def test_record_facts_reject_other_item_of_same_store():
    """R3：同门店另一个物品的行原值不能回答本问物品的问题（准入 + 对象收口）。"""
    units = _multi_item_units()
    facts = [("位置", "A区2号货架底部")]
    location_plan = _plan("城东店", "宣传海报", ("位置",))
    assert not _accepts(units, facts, "城东店的展架在A区2号货架底部。", "城东店的宣传海报", location_plan)
    assert not _accepts(
        units,
        [("位置", "B区1号货架第二层")],
        "城东店的展架在B区1号货架第二层。",
        "城东店的宣传海报",
        location_plan,
    )
    assert _accepts(
        units,
        [("位置", "B区1号货架第二层")],
        "城东店的宣传海报在B区1号货架第二层。",
        "城东店的宣传海报",
        location_plan,
    )


def test_record_units_exclude_rows_without_asked_values():
    """R3：未持有本次问题原值的行（别的门店/别的行）不得进入背书范围。"""
    stores = _stores_unit()
    positions = _positions_unit()
    other = _unit(
        "44444444-4444-4444-4444-444444444444",
        "标识: S02 | 店家: 城西店 | 电话: 010-00000002",
        {"标识": "S02", "店家": "城西店", "电话": "010-00000002"},
    )
    facts = [("电话", "010-00000001")]
    selected = service._record_units([positions, stores, other], _plan(), facts)
    assert selected == [stores]


def test_validated_subject_must_match_plan_objects():
    """R3：模型把已取证值挂到另一个门店名下时，行对象与本问对象不一致 -> 不收口。"""
    stores = _stores_unit()
    facts = [("电话", "010-00000001")]
    assert _accepts([stores], facts, "城东店的联系电话是010-00000001。", "城东店", _plan())
    assert not _accepts([stores], facts, "城西店的联系电话是010-00000001。", "城东店", _plan())


def test_record_facts_accept_object_omitted_field_clause():
    """R3：对象省略、只写"字段名：原值"的分句仍是本问对象的事实（既有正确对照不变）。"""
    units = [_stores_unit()]
    facts = [("电话", "010-00000001")]
    assert _accepts(units, facts, "电话：010-00000001。", "", _plan())
    assert _accepts(units, facts, "城东店的联系电话是010-00000001。", "城东店", _plan())


# ---------------------------------------------------------------- R4：分句完整消费（禁止字段子串跳过）

# 经理 R3 复核的两个真实模型输出原文：限定词出现在对象与字段标签之间。
R4_MANAGER_TEXTS = (
    ("城东店的错误联系电话是010-00000001。", "电话", "010-00000001", "城东店", _stores_unit),
    ("城东店的虚假位置是B区1号货架第二层。", "位置", "B区1号货架第二层", "城东店的宣传海报", _positions_unit),
)


def test_record_facts_reject_manager_wrong_field_labels():
    """R4：经理两个真实反例必须整体不可验证，不能被 find 跳过限定词后构造正向事实。"""
    for text, label, value, object_label, factory in R4_MANAGER_TEXTS:
        parsed = service._record_facts(text, [factory()], [(label, value)], object_label=object_label)
        assert parsed is None, (text, parsed)


# 非固定限定词/关系/修饰：不是黑名单，而是"对象与字段标签之间不允许出现未匹配文字"。
R4_PREFIXED_TEXTS = (
    "城东店的疑似联系电话是010-00000001。",
    "城东店所属的联系电话是010-00000001。",
    "城东店的门店联系电话是010-00000001。",
    "城东店的联系人电话是010-00000001。",
)


def test_record_facts_reject_text_between_object_and_field_label():
    """R4：对象前缀之后到字段标签之前的任何残余文字都使整句不可验证。"""
    for text in R4_PREFIXED_TEXTS:
        parsed = service._record_facts(text, [_stores_unit()], [("电话", "010-00000001")], object_label="城东店")
        assert parsed is None, (text, parsed)


def test_record_facts_reject_preamble_that_carries_content():
    """R4：只允许精确的"根据资料："排版前缀；带其它内容的引导句不被整段丢弃。"""
    facts = [("电话", "010-00000001")]
    assert service._record_facts(
        "根据资料：城东店的联系电话是010-00000001。", [_stores_unit()], facts, object_label="城东店"
    )
    for text in (
        "根据资料（错误）：城东店的联系电话是010-00000001。",
        "根据资料错误：城东店的联系电话是010-00000001。",
    ):
        assert service._record_facts(text, [_stores_unit()], facts, object_label="城东店") is None, text


def test_record_facts_missing_notice_must_name_real_missing_fields():
    """R4：未记录说明只能点名本次真实缺失字段，不能借它跳过任意正文。"""
    unit = _stores_unit()
    facts = [("电话", "010-00000001")]
    accepted = service._record_facts(
        "城东店的电话：010-00000001；资料中未记录：地址。", [unit], facts, object_label="城东店", missing=("地址",)
    )
    assert accepted and [row[0] for row in accepted] == ["电话"]
    for text in (
        "城东店的电话：010-00000001；资料中未记录的错误地址是错误地址。",
        "城东店的电话：010-00000001；资料中未记录：城西店电话。",
    ):
        assert service._record_facts(text, [unit], facts, object_label="城东店", missing=("地址",)) is None, text
    assert (
        service._record_facts("城东店的电话：010-00000001；资料中未记录：地址。", [unit], facts, object_label="城东店")
        is None
    ), "未提供真实缺失字段时，未记录说明不得作为跳过依据"


def test_record_facts_reject_partial_label_and_residual_clauses():
    """R4：部分字段标签、字段后附加说明、分句残余文字一律不可验证。"""
    cases = (
        "城东店的联系电是010-00000001。",
        "城东店的联系电话（据称）是010-00000001。",
        "城东店的联系电话是010-00000001，以上是全部资料。",
        "城东店的联系电话是010-00000001；店家：城西店。",
        "城东店的联系电话是010-00000001；根据城东店电话为010-00000001。",
    )
    for text in cases:
        parsed = service._record_facts(text, [_stores_unit()], [("电话", "010-00000001")], object_label="城东店")
        assert parsed is None, (text, parsed)


def test_record_facts_accept_complete_statement_variants():
    """R4 正确对照：已接受的排版前缀/字段别名/多字段/原值回显/对象省略必须继续成功。"""
    unit = _stores_unit()
    phone = [("电话", "010-00000001")]
    accepted = (
        ("城东店的联系电话是010-00000001。", phone),
        ("城东店的电话号码是010-00000001。", phone),
        ("电话：010-00000001。", phone),
        ("根据资料：城东店的联系电话：010-00000001；联系人：模拟联系人·陈宁。", phone),
        ("城东店的联系电话是010-00000001；店家：城东店。", phone),
        (
            "城东店的联系人：模拟联系人·陈宁；联系电话：010-00000001；合作状态：合作中。",
            [("联系人", "模拟联系人·陈宁"), ("电话", "010-00000001"), ("合作状态", "合作中")],
        ),
    )
    for text, facts in accepted:
        parsed = service._record_facts(text, [unit], facts, object_label="城东店")
        assert parsed, text
    location = service._record_facts(
        "城东店的宣传海报在B区1号货架第二层。",
        [_positions_unit()],
        [("位置", "B区1号货架第二层")],
        object_label="城东店的宣传海报",
    )
    assert location and location[0][0] == "位置"


# ---------------------------------------------------------------- R5：字段标签角色绑定

# 经理 R4 复核的两个真实模型输出原文：字段标签属于别的角色（位置题用电话标签、
# 联系人题用电话标签）。修复前这类标签被无条件接受，随后被静默改写成正确字段。
R5_WRONG_ROLE_TEXTS = (
    ("城东店的宣传海报的联系电话是B区1号货架第二层。", "位置", "B区1号货架第二层", "城东店的宣传海报", _positions_unit),
    ("城东店的联系电话是模拟联系人·陈宁。", "联系人", "模拟联系人·陈宁", "城东店", _stores_unit),
)


def test_record_facts_reject_field_label_of_another_role():
    """R5：分句里的字段标签必须属于本问字段角色；经理两反例原文整句不可验证。"""
    for text, label, value, object_label, factory in R5_WRONG_ROLE_TEXTS:
        parsed = service._record_facts(text, [factory()], [(label, value)], object_label=object_label)
        assert parsed is None, (text, parsed)


def test_record_facts_reject_cross_role_labels_generically():
    """R5 同类（非固定探针）：任何角色的标签都不能借用给别的角色。

    位置标签用于电话题、电话标签用于地址题、别名/电话别名标签用于位置题、状态标签用于
    联系人题——都是"标签不属于本问角色"，与具体词/号码无关。
    """
    stores = _stores_unit()
    positions = _positions_unit()
    cases = (
        ("城东店的位置是010-00000001。", stores, ("电话", "010-00000001"), "城东店"),
        ("城东店的联系电话是示例市示例路18号（模拟）。", stores, ("地址", "示例市示例路18号（模拟）"), "城东店"),
        ("城东店的合作状态是模拟联系人·陈宁。", stores, ("联系人", "模拟联系人·陈宁"), "城东店"),
        ("城东店的宣传海报的别名是B区1号货架第二层。", positions, ("位置", "B区1号货架第二层"), "城东店的宣传海报"),
        ("城东店的宣传海报的电话号码是B区1号货架第二层。", positions, ("位置", "B区1号货架第二层"), "城东店的宣传海报"),
    )
    for text, unit, fact, object_label in cases:
        parsed = service._record_facts(text, [unit], [fact], object_label=object_label)
        assert parsed is None, (text, parsed)


def test_record_evidence_names_are_bound_to_the_requested_role():
    """R5：允许的句法标签按角色派生（索引层角色表），电话类标签不再出现在其它角色。"""
    names = {role: set(service._record_evidence_names((role,))) for role in ("phone", "contact", "location", "address")}
    assert {"联系电话", "电话号码", "联系号码", "联系方式", "电话"} <= names["phone"]
    assert "位置" not in names["phone"] and "联系人" not in names["phone"] and "地址" not in names["phone"]
    assert "位置" in names["location"] and "联系电话" not in names["location"] and "电话号码" not in names["location"]
    assert "联系人" not in names["location"] and "地址" not in names["location"]
    assert "联系人" in names["contact"] and "联系电话" not in names["contact"] and "位置" not in names["contact"]
    assert "地址" in names["address"] and "电话" not in names["address"] and "联系电话" not in names["address"]
    for role in ("contact", "location", "address"):
        assert "联系电话" not in names[role] and "电话号码" not in names[role] and "联系方式" not in names[role]


def test_record_facts_accept_same_role_aliases_and_multi_field():
    """R5 正确对照：本问角色的表头/别名、多字段与同行回显继续成功，不误伤正确标签。"""
    stores = _stores_unit()
    for text in (
        "城东店的联系电话是010-00000001。",
        "城东店的电话是010-00000001。",
        "城东店的电话号码是010-00000001。",
        "城东店的手机号码是010-00000001。",
    ):
        parsed = service._record_facts(text, [stores], [("电话", "010-00000001")], object_label="城东店")
        assert parsed and parsed[0][0] == "电话", text
    contact = service._record_facts(
        "城东店的负责人是模拟联系人·陈宁。", [stores], [("联系人", "模拟联系人·陈宁")], object_label="城东店"
    )
    assert contact and contact[0][0] == "联系人"
    location = service._record_facts(
        "城东店的宣传海报的存放位置是B区1号货架第二层。",
        [_positions_unit()],
        [("位置", "B区1号货架第二层")],
        object_label="城东店的宣传海报",
    )
    assert location and location[0][0] == "位置"


def test_record_facts_accept_multi_field_and_missing_notice_under_role_binding():
    """R5 正确对照：多字段 + 真实缺失字段说明仍成功；说明句仍不得点名非本次缺失字段。"""
    stores = _stores_unit()
    facts = [("联系人", "模拟联系人·陈宁"), ("电话", "010-00000001")]
    accepted = service._record_facts(
        "城东店的联系人：模拟联系人·陈宁；联系电话：010-00000001；资料中未记录：地址。",
        [stores],
        facts,
        object_label="城东店",
        missing=("地址",),
    )
    assert accepted and {row[0] for row in accepted} == {"联系人", "电话"}
    assert (
        service._record_facts(
            "城东店的联系人：模拟联系人·陈宁；联系电话：010-00000001；资料中未记录：位置。",
            [stores],
            facts,
            object_label="城东店",
            missing=("地址",),
        )
        is None
    ), "未记录说明仍只能点名本次真实缺失字段"

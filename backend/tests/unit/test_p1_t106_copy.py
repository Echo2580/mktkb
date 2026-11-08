"""T106：用户可见 reason→文案唯一映射的包内测试（不建库、不调真实模型）。

覆盖：
1. 交接单 §4-1 的 reason 全部登记，且同一 reason 只有一份文案；
2. 每条文案的“原因 / 可否重试 / 与资料有无无关”三要素自洽；
3. T104 七类服务错误 + 网关既有码 + 路由层稳定码的三要素不回退；
4. 记录型 overshoot、点名无记录、指代澄清等既有文案不变量不被破坏。
"""

from __future__ import annotations

import collections

from mktkb import copy as copy_module

#: T104 定稿矩阵：code → (retryable, 必须出现的重试提示)。
T104_MATRIX = {
    "MODEL_NOT_CONFIGURED": (False, "重试不会自行恢复，需管理员完成配置"),
    "MODEL_BUDGET_REFUSED": (False, "重试不会自行恢复，需管理员补足额度或重新授权"),
    "MODEL_TIMEOUT": (True, "可稍后重新提问"),
    "MODEL_UNAVAILABLE": (True, "可稍后重新提问"),
    "MODEL_OUTPUT_INVALID": (True, "可稍后重新提问"),
    "MODEL_CALL_FAILED": (True, "可稍后重新提问"),
    "QA_INTERNAL_ERROR": (False, "重试不会自行恢复，请联系管理员排查"),
    "MODEL_POST_SEND_AUTH_DENIED": (True, "可稍后重新提问，但需先由管理员恢复授权"),
}

ERR07_NOT_MISSING = "这是服务调用失败，不是资料中没有答案"
ERR07_NO_DUPLICATE = "服务端不会因重试而重复保存同一条回答。"
RETRY_TOKENS = (
    "可稍后重新提问",
    "后重新提问",
    "后重试",
    "后重新查询",
    "后可重新提问",
    "可重新提问",
    "重新查询",
)

SAMPLE_FIELDS = {
    "identifier": "QF01",
    "subject": "滨江店的宣传海报",
    "names": "“城南店”",
    "labels": "城东店、城西店",
    "detail": "资料中对位置记录了多个有效值，请以下列来源为准核对。",
    "start": "2026-12-01",
    "end": "2026-10-01",
    "as_of": "2026-10-28",
    "status": "生效、有效",
    "document": "D01_物品位置表.xlsx",
    "region": "城西区",
    "label": "门店",
}


def _render(key: str) -> str:
    return copy_module.text(key, **SAMPLE_FIELDS)


def test_required_reasons_all_resolve_to_registered_copy() -> None:
    for reason in copy_module.REQUIRED_REASONS:
        assert reason in copy_module.REASON_COPY_KEY, reason
        resolved = copy_module.copy_key(reason)
        assert resolved in copy_module.COPY, (reason, resolved)
        if resolved != reason:
            assert copy_module.REASON_ALIASES[reason] == resolved, reason
    # 别名必须显式登记；不允许出现“两个 reason 指向同一 key 但未登记”。
    aliases = {
        reason
        for reason in copy_module.REASON_COPY_KEY
        if copy_module.copy_key(reason) != reason
    }
    assert aliases == set(copy_module.REASON_ALIASES)


def test_every_copy_entry_is_unique() -> None:
    templates = [entry.template for entry in copy_module.COPY.values()]
    duplicates = [
        template for template, count in collections.Counter(templates).items() if count > 1
    ]
    assert duplicates == [], duplicates


def test_every_entry_states_three_elements() -> None:
    for entry in copy_module.COPY.values():
        rendered = entry.template.replace("{reason}", "原因").replace(
            "{retry_hint}", "可稍后重新提问"
        )
        if entry.service_error:
            assert "不是资料中没有答案" in rendered, entry.key
            assert ERR07_NO_DUPLICATE in rendered, entry.key
        if not entry.material_related:
            assert "不是资料中没有答案" in rendered, entry.key
        if entry.retryable:
            assert any(token in rendered for token in RETRY_TOKENS), entry.key
        else:
            assert "可稍后重新提问" not in rendered, entry.key
        if entry.requires_user_input:
            assert "请" in rendered or "可选：" in rendered, entry.key


def test_required_reasons_render_distinct_user_text() -> None:
    rendered: dict[str, str] = {}
    for reason in copy_module.REQUIRED_REASONS:
        resolved = copy_module.copy_key(reason)
        rendered.setdefault(resolved, _render(reason))
    duplicates = [
        text for text, count in collections.Counter(rendered.values()).items() if count > 1
    ]
    assert duplicates == [], duplicates
    assert len(rendered) >= 30


def test_t104_service_error_matrix_is_unchanged() -> None:
    for code, (retryable, hint) in T104_MATRIX.items():
        text = copy_module.service_error_text(code)
        assert ERR07_NOT_MISSING in text, code
        assert ERR07_NO_DUPLICATE in text, code
        assert hint in text, code
        assert copy_module.service_error_is_retryable(code) is retryable, code
        if retryable:
            assert "重试不会自行恢复" not in text, code
        else:
            assert "可稍后重新提问" not in text, code


def test_unknown_service_code_uses_real_retryability() -> None:
    retryable_text = copy_module.service_error_text("SOME_FUTURE_CODE", retryable=True)
    assert "原因未能归类" in retryable_text
    assert "可稍后重新提问" in retryable_text
    assert "重试不会自行恢复" not in retryable_text

    terminal_text = copy_module.service_error_text("SOME_FUTURE_CODE", retryable=False)
    assert "原因未能归类" in terminal_text
    assert "重试不会自行恢复" in terminal_text
    assert "可稍后重新提问" not in terminal_text


def test_record_overshoot_and_no_record_invariants() -> None:
    total_limit = copy_module.record_overshoot_text(150, 0)
    assert "150" in total_limit and "缩小范围" in total_limit
    assert "不是资料中没有答案" in total_limit

    row_limit = copy_module.record_overshoot_text(2, 2)
    assert "2 条候选记录" in row_limit
    assert "记录行超过单次检索上限 100 行" in row_limit
    assert "已列出前 2 条候选" in row_limit

    disclosure = copy_module.no_record_text(["滨江店"], "宣传海报")
    assert "未在资料中找到" in disclosure
    assert "不能据此编造" in disclosure
    assert "没有可枚举的记录" not in disclosure


def test_clarification_followup_still_converges() -> None:
    assert copy_module.clarification_followup("滨江店", "") == "把滨江店的记录列出来"
    assert copy_module.clarification_followup("滨江店", "location") == "滨江店在哪里？"
    assert (
        copy_module.clarification_followup("滨江店", "quantity", "数量")
        == "滨江店的数量是什么？"
    )
    assert copy_module.clarification_candidates_text(["城东店", "城西店"]) == " 可选：城东店、城西店"

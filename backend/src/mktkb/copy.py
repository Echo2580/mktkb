"""T106：用户可见 outcome/reason 的唯一文案映射（ERR-05，D-3）。

边界（与 T106 交接单一致）：

- 只统一**文案取值**；``ResultKind`` / ``error_code`` 语义、API 字段结构和
  检索路径都不在这里改变。
- 每个 reason 只解析到一个 copy key；语义相同的 reason 用显式的
  ``REASON_ALIASES`` 登记，不复制第二份文案。
- 每条文案都要能回答（适用时）：是什么原因、可否重试/如何自救、是否与
  资料有无无关。系统侧失败必须明确“不是资料中没有答案”；资料侧缺失不得
  伪装成服务故障。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

__all__ = [
    "COPY",
    "REASON_ALIASES",
    "REASON_COPY_KEY",
    "REQUIRED_REASONS",
    "CopyEntry",
    "clarification_candidates_text",
    "clarification_followup",
    "conflicting_values_text",
    "copy_key",
    "field_not_recorded_text",
    "legacy_conflict_text",
    "missing_slot_text",
    "multi_field_conflict_text",
    "multiple_entities_text",
    "no_record_text",
    "rag_error_text",
    "record_conflict_text",
    "record_overshoot_text",
    "reject_text",
    "service_error_is_retryable",
    "service_error_text",
    "text",
]


@dataclass(frozen=True)
class CopyEntry:
    """一条用户可见文案。

    ``retryable`` 表示“原样重试同一问题是否有意义”；``material_related`` 表示
    结局是否与资料内容有关；``requires_user_input`` 表示需要用户补充/选择条件。
    """

    key: str
    template: str
    retryable: bool
    material_related: bool
    requires_user_input: bool = False
    service_error: bool = False


def _entry(
    key: str,
    template: str,
    *,
    retryable: bool,
    material_related: bool,
    requires_user_input: bool = False,
    service_error: bool = False,
) -> CopyEntry:
    return CopyEntry(
        key=key,
        template=template,
        retryable=retryable,
        material_related=material_related,
        requires_user_input=requires_user_input,
        service_error=service_error,
    )


# ---------------------------------------------------------------------------
# 文案表（唯一来源）
# ---------------------------------------------------------------------------

#: 服务错误（T104 的七类 + 网关既有子类 + 路由层稳定错误）。这三要素模板
#: 是 ERR-07 的正面样本，任何改动都必须保持等价。
_SERVICE_ERROR_TEMPLATE = (
    "{reason}。这是服务调用失败，不是资料中没有答案；"
    "{retry_hint}。服务端不会因重试而重复保存同一条回答。"
)

_COPY_ENTRIES: tuple[CopyEntry, ...] = (
    # ------------------------------------------------------------ 服务错误
    _entry(
        "MODEL_NOT_CONFIGURED",
        "问答模型尚未配置，请联系管理员。这是服务调用失败，不是资料中没有答案；"
        "重试不会自行恢复，需管理员完成配置。服务端不会因重试而重复保存同一条回答。",
        retryable=False,
        material_related=False,
        service_error=True,
    ),
    _entry(
        "MODEL_BUDGET_REFUSED",
        "当前预算或授权额度不足，本次未发送请求，请联系管理员处理。"
        "这是服务调用失败，不是资料中没有答案；"
        "重试不会自行恢复，需管理员补足额度或重新授权。"
        "服务端不会因重试而重复保存同一条回答。",
        retryable=False,
        material_related=False,
        service_error=True,
    ),
    _entry(
        "MODEL_TIMEOUT",
        "模型服务响应超时，本次回答未完成。这是服务调用失败，不是资料中没有答案；"
        "可稍后重新提问。服务端不会因重试而重复保存同一条回答。",
        retryable=True,
        material_related=False,
        service_error=True,
    ),
    _entry(
        "MODEL_UNAVAILABLE",
        "模型服务暂不可用，本次回答未完成。这是服务调用失败，不是资料中没有答案；"
        "可稍后重新提问。服务端不会因重试而重复保存同一条回答。",
        retryable=True,
        material_related=False,
        service_error=True,
    ),
    _entry(
        "MODEL_OUTPUT_INVALID",
        "模型输出未通过来源与字段校验，已拒绝本次回答。"
        "这是服务调用失败，不是资料中没有答案；"
        "可稍后重新提问。服务端不会因重试而重复保存同一条回答。",
        retryable=True,
        material_related=False,
        service_error=True,
    ),
    _entry(
        "MODEL_CALL_FAILED",
        "模型调用失败且原因未能归类，本次回答未完成。"
        "这是服务调用失败，不是资料中没有答案；"
        "可稍后重新提问。服务端不会因重试而重复保存同一条回答。",
        retryable=True,
        material_related=False,
        service_error=True,
    ),
    _entry(
        "QA_INTERNAL_ERROR",
        "问答服务内部处理异常，本次回答未完成。"
        "这是服务调用失败，不是资料中没有答案；"
        "重试不会自行恢复，请联系管理员排查。"
        "服务端不会因重试而重复保存同一条回答。",
        retryable=False,
        material_related=False,
        service_error=True,
    ),
    _entry(
        "MODEL_POST_SEND_AUTH_DENIED",
        "预算或授权复核未通过，本次请求未发出，请联系管理员处理。"
        "这是服务调用失败，不是资料中没有答案；"
        "可稍后重新提问，但需先由管理员恢复授权。"
        "服务端不会因重试而重复保存同一条回答。",
        retryable=True,
        material_related=False,
        service_error=True,
    ),
    _entry(
        "INDEX_NOT_READY",
        "检索索引暂不可用，本次回答未完成。"
        "这是服务调用失败，不是资料中没有答案；"
        "可稍后重新提问。服务端不会因重试而重复保存同一条回答。",
        retryable=True,
        material_related=False,
        service_error=True,
    ),
    _entry(
        "INVALID_QUERY",
        "无法理解该查询条件，本次回答未完成。"
        "这是查询条件问题，不是资料中没有答案；"
        "请换个说法后重新提问。服务端不会因重试而重复保存同一条回答。",
        retryable=False,
        material_related=False,
        service_error=True,
    ),
    # ------------------------------------------------------------ legacy 解析/记录
    _entry(
        "UNKNOWN_IDENTIFIER",
        "资料中未找到标识“{identifier}”的记录；"
        "请核对标识是否完整，或改用门店、物品名称后重新查询。",
        retryable=True,
        material_related=True,
        requires_user_input=True,
    ),
    _entry(
        # R1/B1：该路径没有执行标识检索（产品检索层不支持标识筛选、内核未接手时
        # 失败关闭），不得把“未检索”说成“资料中未找到”，否则与 material_related=False
        # 自相矛盾。只陈述“未检索 + 无法判断”，并给出去掉标识的自救路径。
        "IDENTIFIER_NOT_RETRIEVABLE",
        "本次未按标识检索（当前检索不支持按标识筛选，系统未执行标识查询），"
        "不能据此判断该记录不存在，也不能确认该记录未找到；"
        "这不是资料中没有答案；"
        "请去掉标识，改用门店、物品名称等条件后重新查询，或联系管理员补充。",
        retryable=True,
        material_related=False,
        requires_user_input=True,
    ),
    _entry(
        # R1/B2：系统未识别出查询意图，尚未检索；不得断言资料缺失。
        "NO_INTENT",
        "没有识别出这个问题的查询意图，本次未作答；这不是资料中没有答案；"
        "请补充门店、物品或要查询的字段等更具体的问法后重试。",
        retryable=True,
        material_related=False,
        requires_user_input=True,
    ),
    _entry(
        "FIELD_NOT_RECORDED",
        "资料中未记录{subject}；"
        "记录缺失不等于服务异常，请核对字段名称或改问其它字段。",
        retryable=False,
        material_related=True,
        requires_user_input=True,
    ),
    _entry(
        "LEGACY_NO_EVIDENCE",
        "资料中未找到与问题相符的内容；"
        "如果确认资料中存在，请补充门店、物品或流程名称后重试。",
        retryable=True,
        material_related=True,
        requires_user_input=True,
    ),
    _entry(
        "LEGACY_UNKNOWN_STORE",
        "资料中未找到“{store}”的记录；"
        "请核对门店名称，或改用已收录的门店后重新查询。",
        retryable=True,
        material_related=True,
        requires_user_input=True,
    ),
    _entry(
        "CONFLICTING_VALUES",
        "{detail}系统不会按上传时间自动裁决；请核对各来源或联系管理员核实。",
        retryable=False,
        material_related=True,
        requires_user_input=True,
    ),
    # 记录型冲突文本要逐句通过 FactValidator；保留既有可验证形态，不追加
    # 额外说明句（否则会被事实闸门当作无证据陈述拒绝）。
    _entry(
        "CONFLICTING_VALUES_RECORD",
        "资料中存在冲突：{entity}的{field}有多个有效值：{lines}。"
        "未按上传时间自动选择其一。",
        retryable=False,
        material_related=True,
    ),
    _entry(
        "CONFLICTING_VALUES_MULTI",
        "资料中{role}存在多个有效值，未自动选择。",
        retryable=False,
        material_related=True,
    ),
    # ------------------------------------------------------------ RAG 无答案
    _entry(
        "UNKNOWN_STORE",
        "资料中未收录门店{names}，不能据此编造答案；"
        "请核对门店名称后重新查询。",
        retryable=True,
        material_related=True,
        requires_user_input=True,
    ),
    _entry(
        "NO_EVIDENCE",
        "资料中未找到符合这些条件的有效依据；"
        "这不代表服务异常，请补充或更换关键词后重试。",
        retryable=True,
        material_related=True,
        requires_user_input=True,
    ),
    _entry(
        "NO_SUPPORTING_SENTENCE",
        "找到的资料与问题重合度不足，不能据此作答；"
        "这不是资料中没有答案，请补充更具体的问法或关键词后重试。",
        retryable=True,
        material_related=False,
        requires_user_input=True,
    ),
    _entry(
        "NO_RECORD_FOR_ENTITY",
        "未在资料中找到{names}{subject}（该实体没有匹配记录），"
        "不能据此编造数值；请核对门店/物品名称后重试。",
        retryable=True,
        material_related=True,
        requires_user_input=True,
    ),
    _entry(
        "NO_ENUMERABLE_RECORD",
        "这份资料中没有可逐条列出的记录；"
        "请确认资料选择是否正确，或改为询问具体字段。",
        retryable=False,
        material_related=True,
        requires_user_input=True,
    ),
    _entry(
        "PAGE_OUT_OF_RANGE",
        "这一页没有更多记录了；请回到上一页，或减少筛选条件后重新查询。",
        retryable=False,
        material_related=True,
        requires_user_input=True,
    ),
    _entry(
        "MULTIPLE_ENTITIES",
        "资料中有多个符合条件的对象，不能唯一确定，"
        "请补充要查询的门店/商品/渠道；这不是资料中没有答案。"
        "可选：{labels}",
        retryable=False,
        material_related=False,
        requires_user_input=True,
    ),
    _entry(
        "LEGACY_MULTIPLE_ENTITIES",
        "存在多个可能对象，请选择要查询的对象。这不是资料中没有答案。",
        retryable=False,
        material_related=False,
        requires_user_input=True,
    ),
    # ------------------------------------------------------------ 澄清/追问
    _entry(
        "ANAPHORA_NO_ENTITY",
        "请说明您指的是哪个物品、门店或哪份资料；"
        "这次追问没有可继承的对象，不是资料中没有答案，"
        "说明对象后重新提问即可。",
        retryable=True,
        material_related=False,
        requires_user_input=True,
    ),
    _entry(
        "ANAPHORA_NO_FIELD",
        "请问要查询{subject}的哪项信息？"
        "这次追问只继承了对象、没有可继承的字段，不是资料中没有答案；"
        "可指定位置、数量、规格、价格等后重新提问。",
        retryable=True,
        material_related=False,
        requires_user_input=True,
    ),
    _entry(
        # R1/B3：新内容没有进入记录检索，不能据此断言资料未记录。
        "ANAPHORA_NEW_CONTENT",
        "这次追问带入了不属于台账字段的新内容，本次未作答；"
        "这不是资料中没有答案；"
        "请指定要查询的字段（例如位置、数量、规格、价格）后重新提问。",
        retryable=True,
        material_related=False,
        requires_user_input=True,
    ),
    _entry(
        "DOCUMENT_NOT_FOUND",
        "资料“{document}”未收录，未使用其它资料替代；"
        "这不是资料中没有答案，请核对资料名称后重新查询。",
        retryable=True,
        material_related=True,
        requires_user_input=True,
    ),
    _entry(
        "DOCUMENT_AMBIGUOUS",
        "问题包含多份资料，请指定要查询的资料；这不是资料中没有答案。",
        retryable=False,
        material_related=False,
        requires_user_input=True,
    ),
    _entry(
        "PRODUCT_AMBIGUOUS",
        "该商品有多个规格/版本，请选择要查询的商品；这不是资料中没有答案。",
        retryable=False,
        material_related=False,
        requires_user_input=True,
    ),
    _entry(
        "ITEM_AMBIGUOUS",
        "问题包含多个物品，请选择要查询的物品；这不是资料中没有答案。",
        retryable=False,
        material_related=False,
        requires_user_input=True,
    ),
    _entry(
        "CHANNEL_AMBIGUOUS",
        "问题包含多个渠道，请选择要查询的渠道；这不是资料中没有答案。",
        retryable=False,
        material_related=False,
        requires_user_input=True,
    ),
    _entry(
        "PRICE_TYPE_AMBIGUOUS",
        "问题包含多个价格类型，请选择要查询的价格类型；这不是资料中没有答案。",
        retryable=False,
        material_related=False,
        requires_user_input=True,
    ),
    _entry(
        "CLARIFICATION_REQUIRED",
        "请补充更明确的查询条件后重试；这不是资料中没有答案。",
        retryable=True,
        material_related=False,
        requires_user_input=True,
    ),
    _entry(
        "UNKNOWN_REGION",
        "资料中没有收录“{region}”这个门店/区域，不能据此编造答案；"
        "请补充准确的门店名称后重新查询。",
        retryable=True,
        material_related=True,
        requires_user_input=True,
    ),
    _entry(
        # P1-FIX/A：公司级经营/财务指标（营收、利润率等）不在当前已发布资料范围内。
        # 只有答案层“资料支持判定”确认检索证据里没有该指标的数据时才会走到这里；
        # 法规/制度题（问条文本身）与有资料支持的问题不在此列。
        "UNSUPPORTED_FINANCIAL_METRIC",
        "找到的资料中没有可支撑“{metric}”的经营财务数据，不能据此推算或编造；"
        "这不是服务故障，请改问制度、价目表、台账等资料已覆盖的内容后重新查询。",
        retryable=True,
        material_related=True,
        requires_user_input=True,
    ),
    _entry(
        # P1-FIX/B：指代追问里的制度/流程话题（如“报销规则”）进入正文查询后，
        # 证据里没有可支撑该话题的正文；如实说明“找到的资料里没有”，不拿无关正文冒充。
        "POLICY_TOPIC_NOT_FOUND",
        "找到的资料中没有可支撑“{topic}”相关制度/流程的内容，不能据此作答；"
        "这不等于资料中一定没有该制度，请核对名称或改问已发布制度后重新查询。",
        retryable=True,
        material_related=True,
        requires_user_input=True,
    ),
    _entry(
        "EMPTY_QUERY",
        "请说明要查询的物品、门店或流程名称；"
        "这不是资料中没有答案，补充后可重新提问。",
        retryable=True,
        material_related=False,
        requires_user_input=True,
    ),
    _entry(
        "MISSING_SLOT",
        "请补充要查询的{label}；这不是资料中没有答案，补充后可重新提问。",
        retryable=True,
        material_related=False,
        requires_user_input=True,
    ),
    _entry(
        "RECORD_ONLY",
        "本次运行只启用台账记录检索，正文/文档型问题未调用模型，因此没有生成回答；"
        "这不是资料中没有答案，也不是服务故障；"
        "请改问台账中的门店/物品字段，或联系管理员开启正文问答。",
        retryable=False,
        material_related=False,
        requires_user_input=True,
    ),
    # ------------------------------------------------------------ 有效期/知识版本
    _entry(
        "NOT_YET_EFFECTIVE",
        "该资料自 {start} 起生效，当前业务基准日 {as_of} 尚未生效，"
        "不能作为当前有效答案，这不是资料中没有答案；"
        "如需未来版本，请明确按未来生效口径重新查询。",
        retryable=True,
        material_related=True,
        requires_user_input=True,
    ),
    _entry(
        "EFFECTIVE_WINDOW_EXPIRED",
        "该记录的有效期至 {end}，在当前业务基准日 {as_of} 已过期，"
        "不能作为现价/现行值，这不是资料中没有答案；"
        "如需历史值，请给出有效期区间内的日期后重新查询。",
        retryable=True,
        material_related=True,
        requires_user_input=True,
    ),
    _entry(
        "EFFECTIVE_WINDOW_CONFLICT",
        "该记录的有效期至 {end}，在当前业务基准日 {as_of} 已过期，"
        "不能作为现价/现行值；但资料状态仍写为“{status}”，"
        "有效期与状态存在矛盾，请核实资料。",
        retryable=False,
        material_related=True,
        requires_user_input=True,
    ),
    _entry(
        "KNOWLEDGE_CHANGED",
        "资料已更新，本次回答已中止，未保存旧版本答案；"
        "这不是服务故障，请基于最新资料重新查询。",
        retryable=True,
        material_related=True,
    ),
    # ------------------------------------------------------------ 检索/模型错误
    _entry(
        "RETRIEVAL_ERROR",
        "检索未完成，本次回答未保存；这是服务调用失败，不是资料中没有答案；"
        "可稍后重新提问，若持续出现请联系管理员。",
        retryable=True,
        material_related=False,
    ),
    _entry(
        "CHAT_UNAVAILABLE",
        "真实模型未配置完整，未生成本次回答；"
        "这是服务调用失败，不是资料中没有答案；请联系管理员完成配置。",
        retryable=False,
        material_related=False,
    ),
    _entry(
        "CHAT_ERROR",
        "真实模型调用未完成，未保存未经校验的回答；"
        "这是服务调用失败，不是资料中没有答案；可稍后重新提问。",
        retryable=True,
        material_related=False,
    ),
    _entry(
        "FACT_REJECTED",
        "已拒绝未经证据支持的回答：{detail}。"
        "这是系统校验拦截，不是资料中没有答案；可重新提问或联系管理员核查。",
        retryable=True,
        material_related=False,
    ),
    # ------------------------------------------------------------ 兜底
    _entry(
        "UNCLASSIFIED",
        "本次回答未能完成，原因未能归类；这是系统侧限制，不是资料中没有答案；"
        "可稍后重新提问，若持续出现请联系管理员。",
        retryable=True,
        material_related=False,
    ),
    _entry(
        "UNCLASSIFIED_SERVICE_ERROR",
        _SERVICE_ERROR_TEMPLATE,
        retryable=True,
        material_related=False,
        service_error=True,
    ),
    # ------------------------------------------------------------ 非 reason 文案
    _entry(
        "RECORD_OVERSHOOT_TOTAL",
        "匹配到 {total} 条候选记录，超过单次检索上限 100 条；{shown}"
        "请补充门店、物品或标识等条件缩小范围。这是检索范围限制，不是资料中没有答案。",
        retryable=False,
        material_related=False,
        requires_user_input=True,
    ),
    _entry(
        "RECORD_OVERSHOOT_ROWS",
        "匹配到 {total} 条候选记录，但涉及记录行超过单次检索上限 100 行；{shown}"
        "请补充门店、物品或标识等条件缩小范围。这是检索范围限制，不是资料中没有答案。",
        retryable=False,
        material_related=False,
        requires_user_input=True,
    ),
    _entry(
        "CLARIFICATION_FOLLOWUP_RECORD",
        "把{label}的记录列出来",
        retryable=False,
        material_related=True,
    ),
    _entry(
        "CLARIFICATION_FOLLOWUP_LOCATION",
        "{label}在哪里？",
        retryable=False,
        material_related=True,
    ),
    _entry(
        "CLARIFICATION_FOLLOWUP_FIELD",
        "{label}的{field}是什么？",
        retryable=False,
        material_related=True,
    ),
)

COPY: dict[str, CopyEntry] = {entry.key: entry for entry in _COPY_ENTRIES}

#: 交接单 §4-1 要求覆盖的用户可见 reason。
REQUIRED_REASONS: tuple[str, ...] = (
    "UNKNOWN_IDENTIFIER",
    "IDENTIFIER_NOT_RETRIEVABLE",
    "NO_INTENT",
    "UNRECORDED_FIELD",
    "CONFLICTING_VALUES",
    "DOCUMENT_NOT_FOUND",
    "UNKNOWN_STORE",
    "RECORD_ONLY",
    "MULTIPLE_ENTITIES",
    "DOCUMENT_AMBIGUOUS",
    "PRODUCT_AMBIGUOUS",
    "ITEM_AMBIGUOUS",
    "CHANNEL_AMBIGUOUS",
    "PRICE_TYPE_AMBIGUOUS",
    "CLARIFICATION_REQUIRED",
    "NO_EVIDENCE",
    "NO_SUPPORTING_SENTENCE",
    "NOT_YET_EFFECTIVE",
    "EFFECTIVE_WINDOW_CONFLICT",
    "EFFECTIVE_WINDOW_EXPIRED",
    "ANAPHORA_NO_ENTITY",
    "ANAPHORA_NO_FIELD",
    "ANAPHORA_NEW_CONTENT",
    "POLICY_FOLLOWUP",
    "NO_RECORD_FOR_ENTITY",
    "NO_ENUMERABLE_RECORD",
    "PAGE_OUT_OF_RANGE",
    "FIELD_NOT_RECORDED",
    "INDEX_NOT_READY",
    "KNOWLEDGE_CHANGED",
    "EMPTY_QUERY",
    "UNKNOWN_REGION",
    "UNSUPPORTED_FINANCIAL_METRIC",
    "POLICY_TOPIC_NOT_FOUND",
    "MISSING_SLOT",
)

#: 语义相同、共用一份文案的 reason（显式白名单，避免复制第二份文案）。
REASON_ALIASES: dict[str, str] = {
    "UNRECORDED_FIELD": "FIELD_NOT_RECORDED",
    "POLICY_FOLLOWUP": "NO_EVIDENCE",
    "STALE_SOURCE": "FACT_REJECTED",
    "FORGED_VALUE": "FACT_REJECTED",
    "CROSS_ENTITY": "FACT_REJECTED",
    "CROSS_FIELD": "FACT_REJECTED",
    "UNSUPPORTED_CLAIM": "FACT_REJECTED",
    "RAG_ERROR": "RETRIEVAL_ERROR",
    "RAG_CONFIG_INVALID": "RETRIEVAL_ERROR",
    "RAG_NOT_READY": "RETRIEVAL_ERROR",
    "QUERY_REJECTED": "RETRIEVAL_ERROR",
    "EMBEDDING_ERROR": "RETRIEVAL_ERROR",
    "EMBEDDING_DIMENSION_INVALID": "RETRIEVAL_ERROR",
    "EMBEDDING_RESPONSE_INVALID": "RETRIEVAL_ERROR",
    "EMBEDDING_TIMEOUT": "RETRIEVAL_ERROR",
    "EMBEDDING_RATE_LIMITED": "RETRIEVAL_ERROR",
    "EMBEDDING_UNAVAILABLE": "RETRIEVAL_ERROR",
    "RERANK_ERROR": "RETRIEVAL_ERROR",
    "RERANK_UNAVAILABLE": "RETRIEVAL_ERROR",
    "BUDGET_ERROR": "RETRIEVAL_ERROR",
    "BUDGET_EXCEEDED": "RETRIEVAL_ERROR",
    "REQUEST_LIMIT_EXCEEDED": "RETRIEVAL_ERROR",
    "BUDGET_PRICING_UNKNOWN": "RETRIEVAL_ERROR",
    "BUDGET_LEDGER_INVALID": "RETRIEVAL_ERROR",
}

#: 服务错误码集合（T104 七类 + 网关既有码 + 路由层稳定码）。
SERVICE_ERROR_CODES: tuple[str, ...] = (
    "MODEL_NOT_CONFIGURED",
    "MODEL_BUDGET_REFUSED",
    "MODEL_TIMEOUT",
    "MODEL_UNAVAILABLE",
    "MODEL_OUTPUT_INVALID",
    "MODEL_CALL_FAILED",
    "QA_INTERNAL_ERROR",
    "MODEL_POST_SEND_AUTH_DENIED",
    "INDEX_NOT_READY",
    "INVALID_QUERY",
)

REASON_COPY_KEY: dict[str, str] = {
    reason: reason for reason in REQUIRED_REASONS if reason in COPY
}
REASON_COPY_KEY.update(REASON_ALIASES)
REASON_COPY_KEY.update({code: code for code in SERVICE_ERROR_CODES})
REASON_COPY_KEY.update({"RETRIEVAL_ERROR": "RETRIEVAL_ERROR"})
REASON_COPY_KEY.update({"CHAT_UNAVAILABLE": "CHAT_UNAVAILABLE"})
REASON_COPY_KEY.update({"CHAT_ERROR": "CHAT_ERROR"})


# ---------------------------------------------------------------------------
# 渲染与专用构造器
# ---------------------------------------------------------------------------


def copy_key(key: str) -> str:
    """把 reason / error_code 解析为唯一 copy key；未知值原样返回。"""

    return REASON_COPY_KEY.get(key, key)


def text(key: str, **fields: Any) -> str:
    """按 reason 或 copy key 渲染文案；未知值落到统一兜底。"""

    entry = COPY.get(copy_key(key))
    if entry is None:
        entry = COPY["UNCLASSIFIED"]
    return entry.template.format(**fields)


def service_error_text(code: str, retryable: bool | None = None) -> str:
    """服务错误文案：已登记码用定稿文案；未登记码按真实 retryable 选提示。"""

    entry = COPY.get(copy_key(code))
    if entry is not None and entry.service_error:
        return entry.template.format()
    effective = True if retryable is None else bool(retryable)
    reason = (
        "模型服务调用失败且原因未能归类，本次回答未完成"
        if effective
        else "本次问答调用失败且原因未能归类，回答未完成"
    )
    retry_hint = "可稍后重新提问" if effective else "重试不会自行恢复，请联系管理员排查"
    return COPY["UNCLASSIFIED_SERVICE_ERROR"].template.format(
        reason=reason, retry_hint=retry_hint
    )


def service_error_is_retryable(code: str) -> bool | None:
    """已登记服务错误码的规范可重试性；未登记返回 ``None``。"""

    entry = COPY.get(copy_key(code))
    if entry is None or not entry.service_error:
        return None
    return entry.retryable


def record_overshoot_text(total: int, shown: int) -> str:
    """记录型 overshoot：给出真实命中量/已列候选数，并说明这是检索范围限制。"""

    key = "RECORD_OVERSHOOT_TOTAL" if int(total) > 100 else "RECORD_OVERSHOOT_ROWS"
    prefix = f"已列出前 {int(shown)} 条候选，" if shown else ""
    return text(key, total=int(total), shown=prefix)


def clarification_followup(
    label: str, field_role: str, field_label: str | None = None
) -> str:
    """候选被点选后的追问；必须能实际收敛到该候选。"""

    if not field_role:
        return text("CLARIFICATION_FOLLOWUP_RECORD", label=label)
    if field_role in ("location", "store"):
        return text("CLARIFICATION_FOLLOWUP_LOCATION", label=label)
    return text(
        "CLARIFICATION_FOLLOWUP_FIELD", label=label, field=field_label or field_role
    )


def clarification_candidates_text(labels: Sequence[str]) -> str:
    """澄清文案后追加的可选标签（沿用既有 `` 可选：`` 形态）。"""

    return " 可选：" + "、".join(labels[:8])


def no_record_text(stores: Sequence[str], item: str | None = None) -> str:
    """点名门店/物品没有匹配记录；不得泛化成“资料没有可枚举记录”。"""

    names = "、".join(f"“{store}”" for store in stores)
    subject = f"的“{item}”记录" if item else "关于该物品的记录"
    return text("NO_RECORD_FOR_ENTITY", names=names, subject=subject)


def field_not_recorded_text(subject: str) -> str:
    """字段缺失（记录存在）；与“记录不存在”区分。"""

    return text("FIELD_NOT_RECORDED", subject=subject)


def multiple_entities_text(labels: Sequence[str]) -> str:
    """多个候选对象：说明不能唯一确定，并附可点选标签。"""

    return text("MULTIPLE_ENTITIES", labels="、".join(labels[:8]))


def conflicting_values_text(detail: str) -> str:
    """冲突统一收尾；``detail`` 只描述事实，不重复“不是服务故障”声明。"""

    return text("CONFLICTING_VALUES", detail=detail)


def legacy_conflict_text(fields: str) -> str:
    """legacy 冲突（产品层证据）文案。"""

    return conflicting_values_text(
        f"资料中对{fields}记录了多个有效值，请以下列来源为准核对。"
    )


def record_conflict_text(entity: str, field: str, lines: str) -> str:
    """RAG 记录冲突（同字段多个有效值）文案；保持 FactValidator 可验证形态。"""

    return text("CONFLICTING_VALUES_RECORD", entity=entity, field=field, lines=lines)


def multi_field_conflict_text(role: str) -> str:
    """同一记录内某字段出现多个有效值（多字段查询）文案。"""

    return text("CONFLICTING_VALUES_MULTI", role=role)


def reject_text(detail: str) -> str:
    """事实闸门拒绝：说明是校验拦截，不冒充资料缺失。"""

    return text("FACT_REJECTED", detail=detail)


def rag_error_text(code: str) -> str:
    """RAG 检索错误统一文案；具体 code 仍保留在 reason/error_code 中。"""

    return text("RETRIEVAL_ERROR", code=code)


def missing_slot_text(missing: str) -> str:
    """缺槽澄清；``missing`` 是 QueryState 的槽名。"""

    labels = {
        "product": "商品名称或规格",
        "store": "门店",
        "item": "物品",
        "channel": "渠道",
        "price_type": "价格类型",
    }
    return text("MISSING_SLOT", label=labels.get(missing, "查询条件"))

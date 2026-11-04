"""T06 模型网关类型与适配器。

对外只暴露稳定类型与 ``build_gateway``：调用方不得传入任意目的地址或密钥；
未配置时返回 None，问答映射 MODEL_NOT_CONFIGURED，其他接口不受影响。
"""

from __future__ import annotations

from .types import (
    MAX_CONTEXT_QUESTIONS,
    MAX_MODEL_TERM_CHARS,
    MAX_MODEL_TERMS,
    CompletionInput,
    CompletionOutput,
    DialogueContext,
    ModelError,
    ModelEvidence,
    ModelGateway,
    ModelNotConfigured,
    ModelOutputInvalid,
    ModelTimeout,
    ModelUnavailable,
    OCRAuthFailed,
    OCRError,
    OCRGateway,
    OCRInput,
    OCRInvalidInput,
    OCRInvalidOutput,
    OCRMode,
    OCRNotConfigured,
    OCRPageResult,
    OCRQuotaUnavailable,
    OCRRateLimited,
    OCRTimeout,
    OCRUnavailable,
    Purpose,
)

__all__ = [
    "MAX_CONTEXT_QUESTIONS",
    "MAX_MODEL_TERM_CHARS",
    "MAX_MODEL_TERMS",
    "CompletionInput",
    "CompletionOutput",
    "DialogueContext",
    "ModelError",
    "ModelEvidence",
    "ModelGateway",
    "ModelNotConfigured",
    "ModelOutputInvalid",
    "ModelTimeout",
    "ModelUnavailable",
    "OCRAuthFailed",
    "OCRError",
    "OCRGateway",
    "OCRInput",
    "OCRInvalidInput",
    "OCRInvalidOutput",
    "OCRMode",
    "OCRNotConfigured",
    "OCRPageResult",
    "OCRQuotaUnavailable",
    "OCRRateLimited",
    "OCRTimeout",
    "OCRUnavailable",
    "Purpose",
    "build_gateway",
    "build_ocr_gateway",
]


def build_gateway(settings, *, gate=None, transport=None, settlement_policy=None) -> ModelGateway | None:
    """按服务端配置构建网关；三项（base_url/model/key）缺一即视为未配置。

    GAP-3：真实 chat 调用与 rag 共用同一份 GO 授权与同一只共享账本。
    - 未配置模型 -> None（既有行为：问答返回 MODEL_NOT_CONFIGURED）；
    - 已配置模型 -> 必须在构造期就拿到合法闸门；没有 GO/阶段分配/计费上界时直接拒绝，
      绝不构造一个“能发送但不记账”的客户端；
    - ``gate``/``transport`` 仅供隔离测试显式注入（生产路径不传）。
    - ``settlement_policy`` 仅供 J2 正式受控执行入口显式注入（Mock 阶段由执行器验证
      GO 的 request plan 绑定后传入）；不传即保持历史旧结算语义。
    - S2-H：``MKTKB_REQUIRE_TOKEN_METER=1`` 时必须有官方 tokenizer artifact，
      缺失/哈希不符/模板不支持即在构造期拒绝。
    """
    base_url = getattr(settings, "model_base_url", None)
    model = getattr(settings, "model_name", None)
    api_key = getattr(settings, "model_api_key", None)
    if not base_url or not model or api_key is None:
        return None
    from ..live_authorization import LiveGateError, assert_provider_binding, product_stage, resolve_live_gate
    from ..official_chat_profile import (
        OfficialChatProfileError,
        assert_official_chat_profile,
    )
    from ..rag.config import positive_float_env, positive_int_env
    from .budgeted import BudgetedModelGateway, ChatPricing
    from .deepseek import DeepSeekClient
    from .token_metering import TokenMeterError, load_meter_from_env

    try:
        pricing = ChatPricing.from_env()
    except LiveGateError as exc:
        raise ValueError(f"chat live 官方 profile 校验拒绝：{exc}") from None
    if pricing is None:
        raise ValueError(
            "chat live 缺少计费上界/价格（MKTKB_MODEL_INPUT_PRICE_PER_MILLION_CNY/"
            "MKTKB_MODEL_OUTPUT_PRICE_PER_MILLION_CNY/MKTKB_MODEL_MAX_INPUT_TOKENS/"
            "MKTKB_MODEL_MAX_OUTPUT_TOKENS），默认拒绝真实调用"
        )
    require_meter = str(__import__("os").environ.get("MKTKB_REQUIRE_TOKEN_METER", "")).strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    from urllib.parse import urlsplit

    try:
        assert_official_chat_profile(
            model=model,
            base_url_host=urlsplit(str(base_url)).hostname,
            thinking="disabled",
            reserve_profile=pricing.reserve_profile,
            context_ceiling_tokens=pricing.context_ceiling_tokens,
            input_price_per_million_cny=pricing.input_price_per_million_cny,
            output_price_per_million_cny=pricing.output_price_per_million_cny,
            max_output_tokens=pricing.max_output_tokens,
        )
    except OfficialChatProfileError as exc:
        raise ValueError(f"chat live 官方 profile 校验拒绝：{exc}") from None
    try:
        prompt_meter = load_meter_from_env(require=require_meter)
    except TokenMeterError as exc:
        raise ValueError(f"chat live token 计量拒绝：{exc}") from None
    if gate is None:
        stage_limit = positive_float_env("MKTKB_RAG_STAGE_LIMIT_CNY")
        max_requests = positive_int_env("MKTKB_RAG_MAX_REQUESTS")
        if stage_limit is None or max_requests is None:
            raise ValueError(
                "chat live 必须显式提供 MKTKB_RAG_STAGE_LIMIT_CNY>0 与 "
                "MKTKB_RAG_MAX_REQUESTS>0（省略/0/负数一律拒绝）"
            )
        try:
            gate = resolve_live_gate(
                stage=product_stage(),
                service="chat",
                requested_stage_limit_cny=stage_limit,
                requested_max_requests=max_requests,
                request_bound_cny=pricing.worst_case_cny(),
            )
        except LiveGateError as exc:
            raise ValueError(f"chat live 授权闸门拒绝：{exc}") from exc
    if getattr(gate.authorization, "bindings", None) is None:
        raise ValueError(
            "chat live GO 必须声明 scope.bindings（型号/host/thinking/输出/token 预算 profile/价格）；"
            "缺失即拒绝真实调用"
        )
    try:
        assert_provider_binding(
            gate.authorization,
            "chat",
            base_url_host=urlsplit(str(base_url)).hostname,
            model=str(model),
            thinking="disabled",
            max_input_tokens=pricing.max_input_tokens,
            max_output_tokens=pricing.max_output_tokens,
            reserve_profile=pricing.reserve_profile,
            context_ceiling_tokens=pricing.context_ceiling_tokens,
            input_price_per_million_cny=pricing.input_price_per_million_cny,
            output_price_per_million_cny=pricing.output_price_per_million_cny,
        )
    except LiveGateError as exc:
        raise ValueError(f"chat live GO 绑定不匹配：{exc}") from None
    go_chat_binding = (gate.authorization.bindings or {}).get("chat") or {}
    if settlement_policy is not None:
        # J2：版本化结算必须由 GO 显式声明版本；执行器还额外核对 request plan 哈希。
        from ..rag.settlement_policy import SETTLEMENT_VERSION, SettlementPolicy

        if not isinstance(settlement_policy, SettlementPolicy):
            raise ValueError("chat live settlement_policy 必须是 SettlementPolicy")
        if go_chat_binding.get("settlement_version") != SETTLEMENT_VERSION:
            raise ValueError(
                "chat live GO 未声明 settlement_version=usage-conservative-v1，拒绝版本化结算"
            )
    if go_chat_binding.get("tokenizer_sha256"):
        # GO 额外绑定了 tokenizer artifact（可选、仅作防替换）：必须真的加载同一 artifact。
        # 这不是可发送证明，预留仍按 context ceiling 全额。
        if prompt_meter is None:
            raise ValueError(
                "chat live GO 已绑定 tokenizer artifact，但运行期未开启 MKTKB_REQUIRE_TOKEN_METER，"
                "禁止真实调用"
            )
        if getattr(prompt_meter, "tokenizer_sha256", None) != go_chat_binding.get("tokenizer_sha256"):
            raise ValueError("chat live 实际加载的 tokenizer 与 GO 绑定不一致，禁止真实调用")
    inner = DeepSeekClient(
        base_url=base_url,
        model=model,
        api_key=api_key.get_secret_value() if hasattr(api_key, "get_secret_value") else str(api_key),
        timeout_seconds=settings.model_request_timeout_seconds,
        transport=transport,
        max_output_tokens=pricing.max_output_tokens,
        prompt_meter=prompt_meter,
    )
    try:
        return BudgetedModelGateway(
            inner,
            gate=gate,
            pricing=pricing,
            meter=prompt_meter,
            require_meter=require_meter,
            settlement_policy=settlement_policy,
        )
    except LiveGateError as exc:
        raise ValueError(f"chat live 授权闸门拒绝：{exc}") from exc


def build_ocr_gateway(settings, *, transport=None) -> OCRGateway | None:
    """按服务端配置构建 OCR 网关；SecretId/SecretKey 缺一即视为未配置。

    S2-H：``ocr_disabled=True``（MKTKB_OCR_DISABLED=1）时无条件返回 None，
    即使 .env/进程环境里仍有 OCR 凭据，也不会构造腾讯云客户端。
    S2-J2：``transport`` 仅供 Mock/隔离测试注入；生产不传即使用真实传输。
    """
    if bool(getattr(settings, "ocr_disabled", False)):
        return None
    secret_id = getattr(settings, "ocr_secret_id", None)
    secret_key = getattr(settings, "ocr_secret_key", None)
    if secret_id is None or secret_key is None:
        return None
    from .tencent_ocr import TencentOCRClient

    return TencentOCRClient(
        secret_id=secret_id.get_secret_value() if hasattr(secret_id, "get_secret_value") else str(secret_id),
        secret_key=secret_key.get_secret_value() if hasattr(secret_key, "get_secret_value") else str(secret_key),
        region=getattr(settings, "ocr_region", "ap-guangzhou"),
        endpoint=getattr(settings, "ocr_endpoint", "https://ocr.tencentcloudapi.com"),
        timeout_seconds=getattr(settings, "ocr_request_timeout_seconds", 30.0),
        transport=transport,
    )


"""Offline DeepSeek chat prompt metering using the official tokenizer artifact.

Purpose (S2-H):
- Count the *exact* tokens of the final chat prompt under the official DeepSeek
  tokenizer artifact (tokenizer.json + tokenizer_config.json), including the
  protocol overhead of the chat template (BOS, <|User|>, <|Assistant|>).
- Provide a conservative *upper bound* for budget reservation:
  ``len(rendered_prompt.encode("utf-8"))``.  The artifact is ByteLevel BPE
  (pre-tokenizer/decoder are ByteLevel, no normalizer, no truncation), so every
  token consumes at least one UTF-8 byte of the rendered prompt; token count
  cannot exceed the byte length for this artifact.  This avoids the old
  ``UTF-8 bytes + 8`` heuristic and any "Chinese chars * ratio" estimate.
- Fail closed: missing artifact, hash mismatch, non-ByteLevel tokenizer,
  non-empty normalizer, configured truncation/padding, or an unsupported chat
  template shape raises ``TokenMeterError``.  Never silently falls back to a
  heuristic.

Model binding caveat (recorded in S2-H evidence, not hidden):
The official token-usage page currently links this artifact, but it does not
state in words that it is the V4.1-Flash-1017 tokenizer/template.  The runner
therefore requires the manager GO to bind the artifact URL/sha256 and the
template sha256; without that binding the bound is not claimed as model-proven.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

BOS_TOKEN = "<｜begin▁of▁sentence｜>"
USER_MARKER = "<｜User｜>"
ASSISTANT_MARKER = "<｜Assistant｜>"
EXPECTED_TEMPLATE_MARKERS = (BOS_TOKEN, USER_MARKER, ASSISTANT_MARKER)


class TokenMeterError(ValueError):
    """Token metering artifact/config is unavailable or unsupported; fail closed."""


@dataclass(frozen=True)
class PromptTokenBound:
    exact_tokens: int
    byte_upper_tokens: int
    rendered_bytes: int
    template_sha256: str
    tokenizer_sha256: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "exact_tokens": self.exact_tokens,
            "byte_upper_tokens": self.byte_upper_tokens,
            "rendered_bytes": self.rendered_bytes,
            "template_sha256": self.template_sha256,
            "tokenizer_sha256": self.tokenizer_sha256,
        }


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _walk_types(value: Any) -> list[str]:
    types: list[str] = []
    if isinstance(value, dict):
        kind = value.get("type")
        if isinstance(kind, str):
            types.append(kind)
        for item in value.values():
            types.extend(_walk_types(item))
    elif isinstance(value, list):
        for item in value:
            types.extend(_walk_types(item))
    return types


class DeepSeekPromptMeter:
    """Load one official tokenizer artifact and count one-system/one-user prompts."""

    def __init__(
        self,
        *,
        tokenizer: Any,
        tokenizer_sha256: str,
        template: str,
        template_sha256: str,
    ) -> None:
        self._tokenizer = tokenizer
        self.tokenizer_sha256 = tokenizer_sha256
        self.template = template
        self.template_sha256 = template_sha256
        for marker in EXPECTED_TEMPLATE_MARKERS:
            if marker in template:
                continue
            # 官方模板用变量引用 BOS（``{{bos_token}}``），不是字面量；两者必居其一。
            if marker == BOS_TOKEN and "bos_token" in template:
                continue
            raise TokenMeterError(f"chat template 缺少协议标记 {marker!r}，拒绝计量")
        # The manual renderer below is only valid for the official non-tool
        # system+user branch.  We require the template to declare that branch.
        if "message['role'] == 'system'" not in template or "message['role'] == 'user'" not in template:
            raise TokenMeterError("chat template 不是受支持的 system+user 形态，拒绝计量")

    @classmethod
    def from_files(
        cls,
        tokenizer_json: Path | str,
        *,
        expected_sha256: str,
        tokenizer_config_json: Path | str | None = None,
    ) -> "DeepSeekPromptMeter":
        tokenizer_path = Path(tokenizer_json)
        if not tokenizer_path.is_file():
            raise TokenMeterError(f"tokenizer.json 不存在：{tokenizer_path}")
        expected = str(expected_sha256 or "").strip().lower()
        if len(expected) != 64 or any(ch not in "0123456789abcdef" for ch in expected):
            raise TokenMeterError("MKTKB_TOKENIZER_SHA256 必须是 64 位十六进制")
        raw = tokenizer_path.read_bytes()
        actual = _sha256_bytes(raw)
        if actual != expected:
            raise TokenMeterError("tokenizer.json 与 GO/环境绑定的 sha256 不一致")
        config_path = (
            Path(tokenizer_config_json)
            if tokenizer_config_json is not None
            else tokenizer_path.with_name("tokenizer_config.json")
        )
        if not config_path.is_file():
            raise TokenMeterError(f"tokenizer_config.json 不存在：{config_path}")
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise TokenMeterError("tokenizer_config.json 不可解析") from exc
        template = config.get("chat_template")
        if not isinstance(template, str) or not template.strip():
            raise TokenMeterError("tokenizer_config.json 缺少 chat_template")
        bos = config.get("bos_token")
        bos_content = bos.get("content") if isinstance(bos, dict) else bos
        if bos_content is not None and bos_content != BOS_TOKEN:
            # 渲染必须用 artifact 自己声明的 BOS；不一致时拒绝，不猜。
            raise TokenMeterError("tokenizer_config.json 的 bos_token 不是官方 <｜begin▁of▁sentence｜>，拒绝计量")
        template_sha = _sha256_bytes(template.encode("utf-8"))

        try:
            document = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise TokenMeterError("tokenizer.json 不可解析") from exc
        if document.get("truncation") not in (None, {}):
            raise TokenMeterError("tokenizer.json 配置了 truncation，拒绝计量（不得静默截断）")
        if document.get("padding") not in (None, {}):
            raise TokenMeterError("tokenizer.json 配置了 padding，拒绝计量")
        if document.get("normalizer") not in (None, {}, {"type": "Sequence", "normalizers": []}):
            raise TokenMeterError("tokenizer.json 含非空 normalizer，字节上界不成立")
        model = document.get("model")
        if not isinstance(model, dict) or model.get("type") != "BPE":
            raise TokenMeterError("tokenizer.json 不是 BPE 模型，拒绝计量")
        if model.get("unk_token") is not None:
            raise TokenMeterError("tokenizer.json 含 unk_token，拒绝计量")
        if "ByteLevel" not in _walk_types(document.get("pre_tokenizer")):
            raise TokenMeterError("tokenizer.json 缺少 ByteLevel pre-tokenizer，字节上界不成立")
        if "ByteLevel" not in _walk_types(document.get("decoder")):
            raise TokenMeterError("tokenizer.json 缺少 ByteLevel decoder，拒绝计量")

        try:
            from tokenizers import Tokenizer  # type: ignore
        except ImportError as exc:  # pragma: no cover - depends on isolated install
            raise TokenMeterError(
                "缺少 tokenizers 依赖；只能使用本轮隔离目录安装的固定版本，不得回退启发式"
            ) from exc
        try:
            tokenizer = Tokenizer.from_file(str(tokenizer_path))
        except Exception as exc:  # noqa: BLE001 - artifact load failure must fail closed
            raise TokenMeterError(f"tokenizer.json 加载失败：{type(exc).__name__}") from exc
        return cls(
            tokenizer=tokenizer,
            tokenizer_sha256=actual,
            template=template,
            template_sha256=template_sha,
        )

    def render(self, system: str, user: str) -> str:
        """Render the official non-tool system+user prompt (generation prompt on).

        Official tokenizer_config.json chat_template, for one system and one user:
        ``{{bos_token}}{{system}}{{'<｜User｜>' + user}}{{'<｜Assistant｜>'}}``.
        """
        if not isinstance(system, str) or not isinstance(user, str):
            raise TokenMeterError("system/user 必须是字符串")
        return f"{BOS_TOKEN}{system}{USER_MARKER}{user}{ASSISTANT_MARKER}"

    def measure(self, system: str, user: str) -> PromptTokenBound:
        rendered = self.render(system, user)
        encoded = self._tokenizer.encode(rendered, add_special_tokens=False)
        exact = len(encoded.ids)
        rendered_bytes = len(rendered.encode("utf-8"))
        if exact > rendered_bytes:
            raise TokenMeterError(
                f"精确 token 数 {exact} 大于 UTF-8 字节数 {rendered_bytes}，字节上界不成立，拒绝"
            )
        return PromptTokenBound(
            exact_tokens=exact,
            byte_upper_tokens=rendered_bytes,
            rendered_bytes=rendered_bytes,
            template_sha256=self.template_sha256,
            tokenizer_sha256=self.tokenizer_sha256,
        )

    def prompt_token_upper_bound(self, system: str, user: str) -> int:
        return self.measure(system, user).byte_upper_tokens

    def as_dict(self) -> dict[str, Any]:
        return {
            "tokenizer_sha256": self.tokenizer_sha256,
            "template_sha256": self.template_sha256,
            "byte_upper": "len(rendered UTF-8 bytes)",
            "bound_basis": "ByteLevel BPE with empty normalizer/no truncation: tokens <= UTF-8 bytes",
        }


def load_meter_from_env(*, require: bool) -> DeepSeekPromptMeter | None:
    """Load the isolated official artifact from process env; never print secrets."""
    import os

    path = os.environ.get("MKTKB_TOKENIZER_PATH", "").strip()
    sha = os.environ.get("MKTKB_TOKENIZER_SHA256", "").strip()
    if not path or not sha:
        if require:
            raise TokenMeterError(
                "已要求 token 计量但缺少 MKTKB_TOKENIZER_PATH / MKTKB_TOKENIZER_SHA256，禁止发送"
            )
        return None
    return DeepSeekPromptMeter.from_files(Path(path), expected_sha256=sha)


__all__ = [
    "ASSISTANT_MARKER",
    "BOS_TOKEN",
    "DeepSeekPromptMeter",
    "PromptTokenBound",
    "TokenMeterError",
    "USER_MARKER",
    "load_meter_from_env",
]

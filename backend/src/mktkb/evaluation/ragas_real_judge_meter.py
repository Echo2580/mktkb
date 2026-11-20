"""Bound one system+user JSON request using the official 1017 model artifacts."""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MODEL_REVISION = "DeepSeek-V4.1-Flash-1017"
ARTIFACT_REVISION = "08c8657f02291e11b6f6b63e0e16014f8e748518"
TOKENIZER_SHA256 = "c90dfa01249db1be4245780a052ede752e1361c612ac6d08e2bdada7d599476b"
TEMPLATE_SHA256 = "95b7033a693b321ceaefb6f89ad07d1e0cf2b095305711f934a4ac649456739d"
RESPONSE_FORMAT = {"type": "json_object"}


class JudgeMeterError(ValueError):
    """The runtime has no matching model-bound metering artifacts."""


def _verified_bytes(path: Path, expected_sha256: str, size: int) -> bytes:
    try:
        with path.open("rb") as file:
            raw = file.read(size + 1)
    except OSError:
        raise JudgeMeterError("judge_meter_artifact_missing") from None
    if len(raw) != size or hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise JudgeMeterError("judge_meter_artifact_mismatch")
    return raw


def _verify_byte_bound(raw: str) -> None:
    tokenizer = json.loads(raw)
    pre = tokenizer["pre_tokenizer"]
    steps = pre["pretokenizers"]
    # Isolated splits preserve the original bytes and the terminal ByteLevel
    # stage adds no prefix. BPE has no unknown-token substitution. The pinned
    # normalizer is empty and render-time encoding disables post specials.
    if (tokenizer["normalizer"] != {"type": "Sequence", "normalizers": []}
            or tokenizer["truncation"] is not None or tokenizer["padding"] is not None
            or tokenizer["model"]["type"] != "BPE" or tokenizer["model"]["unk_token"] is not None
            or pre["type"] != "Sequence" or not steps
            or any(step["type"] != "Split" or step["behavior"] != "Isolated" or step["invert"]
                   for step in steps[:-1])
            or steps[-1]["type"] != "ByteLevel" or steps[-1]["add_prefix_space"] is not False
            or tokenizer["decoder"]["type"] != "ByteLevel"):
        raise JudgeMeterError("judge_meter_bound_unsupported")


@dataclass(frozen=True)
class JudgePromptMeter:
    tokenizer: Any
    template: Any
    tokenizer_sha256: str = TOKENIZER_SHA256
    template_sha256: str = TEMPLATE_SHA256

    def prompt_token_upper_bound(self, system: str, user: str) -> int:
        user_message = {"role": "user", "content": user}
        system_message = {"role": "system", "content": system}
        upper_bound = 0
        try:
            for first_message in (system_message, {**system_message, "response_format": RESPONSE_FORMAT}):
                rendered = self.template.render(messages=[first_message, user_message],
                                                thinking_mode="chat", add_generation_prompt=True)
                bound = len(rendered.encode("utf-8"))
                exact = len(self.tokenizer.encode(rendered, add_special_tokens=False).ids)
                if exact < 1 or exact > bound:
                    raise JudgeMeterError("judge_meter_bound_unsupported")
                upper_bound = max(upper_bound, bound)
        except Exception:
            raise JudgeMeterError("judge_meter_render_failed") from None
        return upper_bound


def load_judge_meter() -> JudgePromptMeter:
    directory = os.environ.get("MKTKB_T208_ARTIFACT_DIR", "").strip()
    if not directory:
        raise JudgeMeterError("judge_meter_artifact_missing")
    root = Path(directory)
    raw_tokenizer = _verified_bytes(root / "tokenizer.json", TOKENIZER_SHA256, 6_367_257).decode("utf-8")
    raw_template = _verified_bytes(root / "chat_template.jinja", TEMPLATE_SHA256, 16_722).decode("utf-8")
    try:
        from jinja2.sandbox import ImmutableSandboxedEnvironment
        from tokenizers import Tokenizer
    except ImportError:
        raise JudgeMeterError("judge_meter_dependencies_missing") from None
    try:
        _verify_byte_bound(raw_tokenizer)
        tokenizer = Tokenizer.from_str(raw_tokenizer)
        env = ImmutableSandboxedEnvironment(trim_blocks=True, lstrip_blocks=True)

        def raise_exception(_message: str) -> None:
            raise JudgeMeterError("judge_meter_render_failed")

        env.globals["raise_exception"] = raise_exception
        template = env.from_string(raw_template)
    except Exception:
        raise JudgeMeterError("judge_meter_artifact_unsupported") from None
    return JudgePromptMeter(tokenizer=tokenizer, template=template)

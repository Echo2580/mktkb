"""FU-4：公开层路径脱敏（H2 日志 / 错误输出 / 分享副本）的定向回归。

被测契约
--------
1. ``p2_safe_output`` 只清洗**路径形状**的字符串：受限根、密钥/密文文件名、``.env``、
   UNC、盘符绝对路径；**固定原因码/计数/摘要不动**（例如 ``holdout_hard_failure_unverified``
   这类 reason code 含 ``holdout`` 字样也不会被误伤）；
2. 两个 H2 受控入口的公开出口（``_emit`` + 结构化错误 detail）都把受限路径换成确定性记号；
3. **拒绝分支**与**正常分支**都要覆盖：错误 payload 与成功 payload 里都不出现受限路径、
   密钥文件名或密文文件名；
4. 记号是确定性的（同一输入 → 同一记号），因此脱敏后的产物仍可做 SHA-256 前后比对；
5. 异常字符串（含空格路径、``.fernet``、超长、换行、怪字符、NUL）都要覆盖。

零真实调用：全部合成字符串与临时目录。
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest

_TESTS_DIR = Path(__file__).resolve().parents[1]
_EVALUATION_TESTS = Path(__file__).resolve().parent
for _path in (_TESTS_DIR, _EVALUATION_TESTS):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from acceptance.support.netguard import t09_network_guard  # noqa: E402,F401

from mktkb.evaluation import p2_safe_output as safe  # noqa: E402

pytestmark = pytest.mark.usefixtures("t09_network_guard")

ROOT = Path(__file__).resolve().parents[3]
V3_TOOL = ROOT / "tools" / "p2_h2_v3_controlled_execute.py"
V2_TOOL = ROOT / "tools" / "p2_h2_controlled_execute.py"
TOTAL_LIMIT_ENV = "MKTKB_PROJECT_TOTAL_LIMIT_CNY"

#: 合成受限路径（**不是**真实路径；仅用于脱敏断言）。
HOLDOUT = "D:\\mktkb-p2-holdout\\v3\\normal\\D01_物品位置表.xlsx"
BATCH = "D:\\mktkb-p2-h2v3-20261115\\run0\\evidence0\\turn-0001.fernet"
KEY_FILE = "D:\\mktkb-p2-holdout\\keys\\scenario.key"
SPACED = "C:\\Users\\some one\\AppData\\Local\\Temp\\带 空格\\file.fernet"
UNC = "\\\\fileserver\\share\\mktkb-p2-holdout\\v3\\review.fernet"


@pytest.fixture(scope="module")
def tools() -> dict[str, Any]:
    original_env = os.environ.get(TOTAL_LIMIT_ENV)
    original_const = None
    try:
        from mktkb.evaluation import p2_holdout_plan as holdout_plan

        original_const = holdout_plan.H2_PROJECT_TOTAL_LIMIT_CNY
        holdout_plan.H2_PROJECT_TOTAL_LIMIT_CNY = 40.0
    except Exception:  # noqa: BLE001 - 常量不可用时只影响 v3 入口导入
        holdout_plan = None
    os.environ[TOTAL_LIMIT_ENV] = "40.0"
    modules: dict[str, Any] = {}
    try:
        for name, path in (("v3", V3_TOOL), ("v2", V2_TOOL)):
            spec = importlib.util.spec_from_file_location(f"_p2_fu4_{name}_entry", path)
            assert spec is not None and spec.loader is not None
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)
            modules[name] = module
    finally:
        if holdout_plan is not None and original_const is not None:
            holdout_plan.H2_PROJECT_TOTAL_LIMIT_CNY = original_const
        if original_env is None:
            os.environ.pop(TOTAL_LIMIT_ENV, None)
        else:
            os.environ[TOTAL_LIMIT_ENV] = original_env
    return modules


def _assert_no_restricted(text: str) -> None:
    for forbidden in (
        "D:\\mktkb-p2-holdout",
        "C:\\Users",
        "\\\\fileserver",
        ".fernet",
        "scenario.key",
    ):
        assert forbidden not in text, (forbidden, text[:400])


# --------------------------------------------------------------------------- #
# 1. 单元：路径形状识别 / 记号确定性 / 原因码不被误伤
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "value",
    [HOLDOUT, BATCH, KEY_FILE, SPACED, UNC, "\\\\host\\share\\x.bin", "D:/mktkb-p2-holdout/v3"],
)
def test_restricted_paths_are_recognised(value: str) -> None:
    assert safe.is_restricted(value) is True
    token = safe.redact_value(value)
    assert token.startswith("<redacted-path:")
    assert token == safe.redact_value(value)  # 确定性
    _assert_no_restricted(token)


@pytest.mark.parametrize(
    "value",
    [
        "docs/evaluation/p2-holdout-v3.source-map.json",  # 仓库相对公开件
        "holdout_hard_failure_unverified",  # 固定 reason code
        "p2-refusal-compat/v0.6",
        "scenario_id:base_b0",
    ],
)
def test_public_identifiers_and_reason_codes_are_not_rewritten(value: str) -> None:
    assert safe.redact_value(value) == value
    assert safe.redact_text(value) == value


def test_default_boundary_only_redacts_restricted_paths_but_strict_redacts_all_absolute(
    tmp_path: Path,
) -> None:
    """既有出口保持兼容：仓外普通绝对路径原样；新公开产物一律记号化。"""
    plain = str(tmp_path / "card.json")
    assert safe.redact_value(plain) == plain
    tokenised = safe.redact_value(plain, strict=True)
    assert tokenised.startswith("<redacted-path:")
    assert plain not in tokenised


def test_key_and_ciphertext_file_names_are_redacted() -> None:
    for name in ("scenario.key", ".env", "manifest-0000.fernet"):
        token = safe.redact_value(name)
        assert token.startswith("<redacted-path:"), name
        assert name not in token


def test_weird_and_overlong_strings_are_contained() -> None:
    newline_path = "D:\\mktkb-p2-holdout\\line\nbreak\\file.fernet"
    token = safe.redact_value(newline_path)
    assert "\n" not in token
    assert "mktkb-p2-holdout" not in token

    odd = "D:\\mktkb-p2-holdout\\奇怪字符☃𝄞\u200b\\key.fernet"
    assert "mktkb-p2-holdout" not in safe.redact_value(odd)

    overlong = "x" * (safe.PUBLIC_TEXT_MAX + 10)
    assert safe.redact_value(overlong) == f"<truncated:{len(overlong)}>"

    nul = "D:\\mktkb-p2-holdout\\a\x00b\\k.key"
    token = safe.redact_value(nul)
    assert "\x00" not in token
    assert "mktkb-p2-holdout" not in token


def test_payload_redaction_keeps_codes_counts_and_non_strings() -> None:
    payload = {
        "ok": False,
        "error_code": "derive_output_in_forbidden_root",
        "detail": "out_dir",
        "counts": {"turns": 36, "cases": 30},
        "verified": False,
        "paths": {"evidence_dir": HOLDOUT, "key": KEY_FILE},
        "reasons": ["holdout_hard_failure_unverified", "release_not_ready"],
        "nested": [{"file": BATCH}],
    }
    out = safe.redact_payload(payload)
    assert out["error_code"] == payload["error_code"]
    assert out["detail"] == payload["detail"]
    assert out["counts"] == payload["counts"]
    assert out["verified"] is False
    assert out["reasons"] == payload["reasons"]
    _assert_no_restricted(json.dumps(out, ensure_ascii=False))
    # 结构不变：只换字符串值。
    assert set(out) == set(payload)
    assert set(out["paths"]) == set(payload["paths"])


def test_scan_public_text_reports_kinds_without_echoing_the_path() -> None:
    text = json.dumps({"path": HOLDOUT, "key": KEY_FILE, "note": "docs/x.json"})
    result = safe.scan_public_text(text)
    assert result["clean"] is False
    assert result["counts"].get("absolute_path", 0) >= 1
    assert result["counts"].get("key_or_ciphertext_name", 0) >= 1
    serialized = json.dumps(result, ensure_ascii=False)
    _assert_no_restricted(serialized)
    assert safe.scan_public_text('{"path": "docs/x.json"}')["clean"] is True


def test_redaction_is_idempotent_and_sha_stable() -> None:
    once = safe.redact_payload({"p": HOLDOUT, "q": KEY_FILE}, strict=True)
    twice = safe.redact_payload(once, strict=True)
    assert once == twice
    assert hashlib.sha256(json.dumps(once, sort_keys=True).encode()).hexdigest() == hashlib.sha256(
        json.dumps(twice, sort_keys=True).encode()
    ).hexdigest()


# --------------------------------------------------------------------------- #
# 2. 正常分支：成功 payload 的公开出口
# --------------------------------------------------------------------------- #


def test_v3_emit_sanitises_success_payload(
    tools: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    tools["v3"]._emit(
        {
            "ok": True,
            "run_id": "p2-h2v3-synthetic",
            "inputs": {"holdout_manifest": {"path": HOLDOUT, "sha256": "a" * 64}},
            "paths": {"evidence_dir": BATCH, "key": KEY_FILE},
            "counts": {"turns": 14, "cases": 12},
            "reason": "holdout_hard_failure_unverified",
        }
    )
    out = capsys.readouterr().out
    _assert_no_restricted(out)
    payload = json.loads(out)
    assert payload["ok"] is True
    assert payload["counts"] == {"turns": 14, "cases": 12}
    assert payload["reason"] == "holdout_hard_failure_unverified"


def test_v3_emit_strict_mode_tokenises_every_absolute_path(
    tools: dict[str, Any], capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    tools["v3"]._emit({"ok": True, "path": str(tmp_path / "card.json")}, strict=True)
    payload = json.loads(capsys.readouterr().out)
    assert payload["path"].startswith("<redacted-path:")
    assert str(tmp_path) not in json.dumps(payload, ensure_ascii=False)


def test_v2_emit_sanitises_success_receipt_like_payload(
    tools: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    tools["v2"]._emit(
        {
            "ok": True,
            "status": "succeeded",
            "paths": {"out_dir": "C:\\work\\product", "evidence_dir": BATCH},
            "evidence_key_sha256": "b" * 64,
            "case_plan": {"path": HOLDOUT},
        }
    )
    out = capsys.readouterr().out
    _assert_no_restricted(out)
    payload = json.loads(out)
    assert payload["evidence_key_sha256"] == "b" * 64
    # 仓外普通工作目录（非受限）保持原值：既有下游按它读文件，兼容性优先。
    assert payload["paths"]["out_dir"] == "C:\\work\\product"


# --------------------------------------------------------------------------- #
# 3. 拒绝分支：结构化错误 detail
# --------------------------------------------------------------------------- #


def test_v3_cli_error_detail_is_path_safe(
    tools: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    """自由文本 detail 里若混进受限路径，公开出口必须只剩记号。"""
    tool = tools["v3"]
    detail = tool._public_detail(f"cannot write {HOLDOUT} (key {KEY_FILE})")
    _assert_no_restricted(detail)
    assert "<redacted-path:" in detail
    tool._emit(
        {"ok": False, "error_code": "output_already_exists", "detail": detail},
        strict=True,
    )
    out = capsys.readouterr().out
    _assert_no_restricted(out)
    parsed = json.loads(out)
    assert parsed["error_code"] == "output_already_exists"
    assert parsed["detail"] == detail


def test_v2_cli_error_branch_is_path_safe(
    tools: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    entry = tools["v2"]
    error = entry.EntryError("output_already_exists", KEY_FILE)
    payload = {
        "ok": False,
        "schema_version": entry.TOOL_SCHEMA_VERSION,
        "error_code": error.code,
        "detail": entry._public_detail(error.detail),
        "secrets_printed": False,
        "real_sends": 0,
    }
    entry._emit(payload)
    out = capsys.readouterr().out
    _assert_no_restricted(out)
    parsed = json.loads(out)
    assert parsed["error_code"] == "output_already_exists"
    assert parsed["real_sends"] == 0
    assert parsed["detail"].startswith("<redacted-path:")


def test_v3_derive_error_payload_shape_is_safe(
    tools: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    """derive-cards 的拒绝分支：命令/码/计数保留，路径只剩角色与记号。"""
    tools["v3"]._emit(
        {
            "ok": False,
            "error_code": "derive_output_in_forbidden_root",
            "detail": "out_dir",
            "command": "derive-cards",
            "network": {"local": [], "external": []},
        },
        strict=True,
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "ok": False,
        "error_code": "derive_output_in_forbidden_root",
        "detail": "out_dir",
        "command": "derive-cards",
        "network": {"local": [], "external": []},
    }


# --------------------------------------------------------------------------- #
# 4. 新公开产物：定向扫描（命令与结果进报告，测试里只做机检）
# --------------------------------------------------------------------------- #


def test_new_public_artifacts_are_scannable_and_clean(
    tools: dict[str, Any], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """新公开产物的扫描口径：绝对路径 / 密钥名 / 密文名必须为 0。"""
    artifact = tmp_path / "public-proof.json"
    artifact.write_text(
        json.dumps(
            tools["v3"]._public_payload(
                {
                    "schema_version": "p2-h2v3-derive-proof/v0.1",
                    "card_sha256": "c" * 64,
                    "public_paths": {
                        "binding": safe.path_token(HOLDOUT, role="binding"),
                        "key": safe.path_token(KEY_FILE, role="key_file"),
                    },
                    "reason": "holdout_hard_failure_unverified",
                },
                strict=True,
            ),
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    result = safe.scan_public_text(artifact.read_text(encoding="utf-8"))
    assert result["clean"] is True, result
    del capsys

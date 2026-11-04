"""T02-R1：受信任 Origin 的真实配置加载（dotenv / 环境变量 / 列表参数）与非法值拒绝。"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from mktkb.config import Settings

BASE_KWARGS = dict(
    csrf_secret="unit-test-csrf-secret-0123456789",
    admin_password="AdminPass-1",
    employee_password="EmployeePass-1",
    cookie_secure=False,
)


def _clear_env(monkeypatch) -> None:
    for key in list(os.environ):
        if key.startswith("MKTKB_"):
            monkeypatch.delenv(key, raising=False)


def _write_env(tmp_path: Path, origins: str, *, admin_password: str = "AdminPass-1") -> Path:
    path = tmp_path / "dotenv"
    path.write_text(
        "\n".join(
            [
                "MKTKB_DATA_DIR=var",
                "MKTKB_CSRF_SECRET=unit-test-csrf-secret-0123456789",
                f"MKTKB_ADMIN_PASSWORD={admin_password}",
                "MKTKB_EMPLOYEE_PASSWORD=EmployeePass-1",
                "MKTKB_COOKIE_SECURE=false",
                f"MKTKB_TRUSTED_ORIGINS={origins}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def test_single_origin_from_dotenv(tmp_path: Path, monkeypatch):
    _clear_env(monkeypatch)
    settings = Settings(_env_file=_write_env(tmp_path, "http://127.0.0.1:8077"))
    assert settings.trusted_origins == ["http://127.0.0.1:8077"]


def test_comma_separated_origins_from_dotenv(tmp_path: Path, monkeypatch):
    _clear_env(monkeypatch)
    settings = Settings(_env_file=_write_env(tmp_path, "http://127.0.0.1:8077,https://kb.example.com"))
    assert settings.trusted_origins == ["http://127.0.0.1:8077", "https://kb.example.com"]


def test_json_list_origins_from_dotenv(tmp_path: Path, monkeypatch):
    _clear_env(monkeypatch)
    settings = Settings(_env_file=_write_env(tmp_path, '["http://a.example","https://b.example"]'))
    assert settings.trusted_origins == ["http://a.example", "https://b.example"]


def test_environment_variable_source(monkeypatch):
    monkeypatch.setenv("MKTKB_CSRF_SECRET", "unit-test-csrf-secret-0123456789")
    monkeypatch.setenv("MKTKB_ADMIN_PASSWORD", "AdminPass-1")
    monkeypatch.setenv("MKTKB_EMPLOYEE_PASSWORD", "EmployeePass-1")
    monkeypatch.setenv("MKTKB_COOKIE_SECURE", "false")
    monkeypatch.setenv("MKTKB_TRUSTED_ORIGINS", "http://127.0.0.1:8077,https://kb.example.com")
    settings = Settings(_env_file=None)
    assert settings.trusted_origins == ["http://127.0.0.1:8077", "https://kb.example.com"]


def test_python_list_argument_still_works():
    settings = Settings(trusted_origins=["http://127.0.0.1:8077"], **BASE_KWARGS)
    assert settings.trusted_origins == ["http://127.0.0.1:8077"]


def test_dotenv_is_read_from_working_directory(tmp_path: Path):
    """真实入口：不传 _env_file，仅靠 cwd 下的 .env（与 README 一致）。"""
    (tmp_path / ".env").write_text(
        "\n".join(
            [
                "MKTKB_CSRF_SECRET=unit-test-csrf-secret-0123456789",
                "MKTKB_ADMIN_PASSWORD=AdminPass-1",
                "MKTKB_EMPLOYEE_PASSWORD=EmployeePass-1",
                "MKTKB_COOKIE_SECURE=false",
                "MKTKB_TRUSTED_ORIGINS=http://127.0.0.1:8077,https://kb.example.com",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    env = {key: value for key, value in os.environ.items() if not key.startswith("MKTKB_")}
    result = subprocess.run(
        [sys.executable, "-c", "from mktkb.config import Settings; print('|'.join(Settings().trusted_origins))"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "http://127.0.0.1:8077|https://kb.example.com"


@pytest.mark.parametrize(
    "origins",
    ["", "null", "*", "example.com", "http://host/path", "ftp://host.example", "http://user:pw@host.example"],
)
def test_invalid_origins_are_rejected(origins: str):
    with pytest.raises(ValidationError) as error:
        Settings(trusted_origins=origins, **BASE_KWARGS)
    message = str(error.value)
    assert "AdminPass-1" not in message
    assert "EmployeePass-1" not in message
    assert "unit-test-csrf-secret" not in message


def test_empty_origin_list_is_rejected():
    with pytest.raises(ValidationError):
        Settings(trusted_origins=[], **BASE_KWARGS)


# ---- T02-R2：配置校验失败时的异常展示脱敏 ----

SHORT_EMPLOYEE = "Emp42!ab"  # 合法 8 字符、便于完整检索的模拟员工密码
ADMIN_OK = "Admin42!ab"
CSRF_OK = "pm-simulated-csrf-0123456789"
ORIGIN_PW = "URL42!ab"
LONG_EMPLOYEE = "Emp-LongSimulated-9f3a7c11b2"
LONG_FRAGMENT = "9f3a7c11b2"

REDACTION_CASES = [
    ("short_csrf", {"csrf_secret": "short"}, "csrf_secret", (SHORT_EMPLOYEE, ADMIN_OK)),
    ("short_admin", {"admin_password": "bad"}, "admin_password", (SHORT_EMPLOYEE, CSRF_OK)),
    (
        "short_admin_long_employee",
        {"admin_password": "bad", "employee_password": LONG_EMPLOYEE},
        "admin_password",
        (LONG_EMPLOYEE, LONG_FRAGMENT, CSRF_OK),
    ),
    (
        "origin_userinfo",
        {"trusted_origins": f"http://user:{ORIGIN_PW}@localhost"},
        "trusted_origins",
        (ORIGIN_PW, SHORT_EMPLOYEE, ADMIN_OK, CSRF_OK),
    ),
]


def _settings_error(**overrides) -> str:
    kwargs = dict(
        csrf_secret=CSRF_OK,
        admin_password=ADMIN_OK,
        employee_password=SHORT_EMPLOYEE,
        trusted_origins=["http://localhost"],
    )
    kwargs.update(overrides)
    with pytest.raises(ValidationError) as error:
        Settings(**kwargs)
    return str(error.value)


@pytest.mark.parametrize(("case", "overrides", "field", "secrets"), REDACTION_CASES)
def test_config_validation_error_hides_secrets(case: str, overrides: dict, field: str, secrets: tuple):
    message = _settings_error(**overrides)
    assert field in message, "错误仍应给出字段名以便排错"
    assert "input_value" not in message, "不得附带原始配置值"
    for secret in secrets:
        assert secret not in message, f"{case} 回显了秘密 {secret!r}"


@pytest.mark.parametrize(("case", "overrides", "field", "secrets"), REDACTION_CASES)
def test_startup_failure_stderr_hides_secrets(tmp_path: Path, case: str, overrides: dict, field: str, secrets: tuple):
    """真实子进程启动：非法配置必须拒绝，且 stderr 不回显任何模拟秘密。"""
    values = {
        "MKTKB_CSRF_SECRET": overrides.get("csrf_secret", CSRF_OK),
        "MKTKB_ADMIN_PASSWORD": overrides.get("admin_password", ADMIN_OK),
        "MKTKB_EMPLOYEE_PASSWORD": overrides.get("employee_password", SHORT_EMPLOYEE),
        "MKTKB_TRUSTED_ORIGINS": overrides.get("trusted_origins", "http://localhost"),
        "MKTKB_COOKIE_SECURE": "false",
    }
    folder = tmp_path / case
    folder.mkdir()
    (folder / ".env").write_text("\n".join(f"{key}={value}" for key, value in values.items()) + "\n", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-B", "-X", "utf8", "-c", "from mktkb.main import create_app; create_app()"],
        cwd=folder,
        env={"SystemRoot": os.environ.get("SystemRoot", r"C:\Windows")},
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )
    assert result.returncode != 0, "非法配置必须导致启动失败"
    text = (result.stdout or "") + (result.stderr or "")
    assert "input_value" not in text
    assert field in text, "stderr 应保留字段名"
    for secret in secrets:
        assert secret not in text, f"{case} 的 stderr 回显了秘密 {secret!r}"
    # 另一条路径同批核对：Origin 内密码既不进异常文案，也不进 input
    assert ORIGIN_PW not in text


def test_malformed_json_origin_message_keeps_no_raw_input():
    """JSON 解码失败的自定义文案不得拼接原始文本（可能含秘密）。"""
    malformed = '["http://localhost", "' + LONG_EMPLOYEE + '"'
    message = _settings_error(trusted_origins=malformed)
    assert "trusted_origins" in message
    assert "JSON" in message
    assert LONG_EMPLOYEE not in message
    assert LONG_FRAGMENT not in message
    assert "input_value" not in message

"""T09-D3：测试进程与真实 ``.env`` 隔离的最小机器守卫（不读真实 .env）。

背景：仓库根存在含真实模型/OCR 配置的 ``.env``。T09-D2 §9 偏差 9 记录：从仓库根运行全量
回归时，既有 ``conftest.settings`` 未禁用 ``.env``，``test_g08_unconfigured_model_returns_
service_error_without_calling`` 因此构造了真实 DeepSeek 客户端并可能发出 1 次请求。

本文件只做守卫，不改任何既有测试断言：
1. 测试进程内 ``Settings.model_config`` 的默认 ``env_file`` 已被隔离（``conftest`` 的
   session 级 autouse fixture）；
2. 不传参的默认 ``Settings()`` 不会拿到仓库根 ``.env`` 的模型/OCR 配置；
3. ``conftest`` 的 ``settings``/``app`` fixture 装配出的应用**没有**真实模型/OCR 网关。

从仓库根运行才真正具备"守护"意义（仓库根有 .env，backend 目录没有）；从 backend 运行同样
断言不放松。
"""

from __future__ import annotations

from pathlib import Path

from mktkb.config import Settings

ROOT = Path(__file__).resolve().parents[3]

MODEL_OCR_FIELDS = ("model_base_url", "model_name", "model_api_key", "ocr_secret_id", "ocr_secret_key")


def _assert_unconfigured(settings: Settings, label: str) -> None:
    for field in MODEL_OCR_FIELDS:
        assert getattr(settings, field) is None, f"{label} 的 {field} 不应有任何真实/假模型配置"


def test_test_process_never_reads_repo_dotenv(settings: Settings, app) -> None:
    """仓库根有真实 .env 时，测试进程仍必须与它隔离且不装配任何真实网关。"""
    # 前提记录：本仓库根确实存在 .env（不读取其内容，只判断存在性）
    dotenv_present = (ROOT / ".env").is_file()

    # 1) 隔离已生效：默认 Settings 源不再加载 .env
    assert Settings.model_config.get("env_file") is None, (
        "conftest 的 dotenv 隔离未生效：Settings 默认仍会尝试读取工作目录 .env"
    )

    # 2) 默认构造（不传 _env_file，只传业务必需假值）不携带 .env 的模型/OCR 配置。
    #    若隔离失效且从仓库根运行，``.env`` 的 MKTKB_MODEL_*/MKTKB_OCR_* 会被合并进来，
    #    下面断言即失败；只传假业务值是为了不让"默认 Settings() 缺必填项"掩盖隔离问题。
    default_like = Settings(
        csrf_secret="unit-test-csrf-secret-0123456789",
        admin_password="AdminPass-1",
        employee_password="EmployeePass-1",
        trusted_origins=["http://testserver"],
    )
    _assert_unconfigured(default_like, "默认 Settings()（仅假业务值）")

    # 3) conftest.settings fixture 与 app fixture 均未装配真实模型/OCR 网关
    _assert_unconfigured(settings, "conftest.settings")
    assert app.state.model_gateway is None, "app fixture 不应构造真实模型客户端（事故点 test_g08）"
    assert app.state.ocr_gateway is None, "app fixture 不应构造真实 OCR 客户端"

    assert dotenv_present in (True, False)  # 存在性仅作记录，不改变上面的不读结论

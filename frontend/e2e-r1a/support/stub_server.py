"""R1A 本地浏览器测试专用后端入口（受控替身，不是产品代码）。

与 T08 开发套件相同的真实 FastAPI/迁移/解析链路；仅端口、可信 Origin 与数据目录
指向本轮独占证据目录，避免覆盖 T08 旧数据、日志或截图。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT / "backend" / "src"))

from fastapi.responses import JSONResponse  # noqa: E402  (需先插入 sys.path)

from mktkb.config import Settings  # noqa: E402
from mktkb.main import create_app  # noqa: E402
from mktkb.providers.types import (  # noqa: E402
    CompletionOutput,
    ModelTimeout,
    ModelUnavailable,
    OCRQuotaUnavailable,
)

ADMIN_PASSWORD = "AdminPass-T08"
EMPLOYEE_PASSWORD = "EmployeePass-T08"


class Control:
    """测试控制面：只由浏览器测试通过 /__t08__/control 修改。"""

    slow_answer_ms = 0
    next_model_error: str | None = None


class EchoGateway:
    """回显本次证据的模型替身；不产生任何业务事实。"""

    async def complete(self, request, *, timeout_seconds: float) -> CompletionOutput:
        if request.purpose == "query_expansion":
            return CompletionOutput(text="", query_terms=())
        if Control.next_model_error == "unavailable":
            Control.next_model_error = None
            raise ModelUnavailable("t08 controlled model unavailable")
        if Control.next_model_error == "timeout":
            Control.next_model_error = None
            raise ModelTimeout("t08 controlled model timeout")
        delay_ms = Control.slow_answer_ms
        if delay_ms:
            Control.slow_answer_ms = 0
            await asyncio.sleep(delay_ms / 1000)
        parts: list[str] = []
        for item in request.evidence[:8]:
            if item.fields:
                pairs = "；".join(f"{key}：{value}" for key, value in list(item.fields.items())[:12])
                parts.append(pairs)
            elif item.text:
                parts.append(item.text[:300])
        text = "根据资料：" + "；".join(parts) if parts else "根据资料：未检索到可用字段"
        return CompletionOutput(
            text=text,
            source_ids=tuple(item.source_id for item in request.evidence),
            provider_request_id="t08-stub",
        )


class QuotaExhaustedOCR:
    """固定模拟 OCR 额度不足：任务阻塞、版本失败，恢复条件后由管理员重试。"""

    def recognize(self, page, *, mode):  # noqa: ANN001
        raise OCRQuotaUnavailable("t08 controlled OCR quota exhausted")

    def close(self) -> None:
        return None


def build_app(data_dir: Path):
    data_dir.mkdir(parents=True, exist_ok=True)
    database_path = data_dir / "mktkb.sqlite3"
    settings = Settings(
        _env_file=None,
        data_dir=data_dir,
        database_url=f"sqlite:///{database_path.as_posix()}",
        storage_dir=data_dir / "storage",
        csrf_secret="t08-e2e-local-placeholder-secret",
        bcrypt_rounds=4,
        admin_username="admin",
        admin_password=ADMIN_PASSWORD,
        admin_display_name="模拟管理员",
        employee_username="employee",
        employee_password=EMPLOYEE_PASSWORD,
        employee_display_name="模拟员工",
        cookie_secure=False,
        trusted_origins=["http://127.0.0.1:5198"],
        log_level="WARNING",
        model_request_timeout_seconds=10.0,
    )
    app = create_app(settings, model_gateway=EchoGateway(), ocr_gateway=QuotaExhaustedOCR())

    @app.post("/__t08__/control")
    async def control(payload: dict):  # noqa: ANN202
        if "slow_answer_ms" in payload:
            Control.slow_answer_ms = int(payload["slow_answer_ms"])
        if "next_model_error" in payload:
            value = payload["next_model_error"]
            Control.next_model_error = None if value in (None, "") else str(value)
        return JSONResponse(
            {
                "slow_answer_ms": Control.slow_answer_ms,
                "next_model_error": Control.next_model_error,
            }
        )

    @app.get("/__t08__/control")
    async def control_state():  # noqa: ANN202
        return JSONResponse(
            {
                "slow_answer_ms": Control.slow_answer_ms,
                "next_model_error": Control.next_model_error,
            }
        )

    return app


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8098)
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=PROJECT_ROOT / "docs" / "evidence" / "T08" / "R1A" / "tmp" / "browser" / ".e2e-data",
    )
    args = parser.parse_args(argv)

    run_dir = args.data_dir.resolve()
    if run_dir.name != ".e2e-data":
        raise SystemExit(f"拒绝清理非测试目录：{run_dir}")
    if run_dir.exists():
        shutil.rmtree(run_dir)
    data_dir = run_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    app = build_app(data_dir)
    import uvicorn

    print(json.dumps({"t08_stub": "ready", "data_dir": str(data_dir)}), flush=True)
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

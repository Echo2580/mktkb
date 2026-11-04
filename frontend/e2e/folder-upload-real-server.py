"""S3 文件夹上传的真实本地后端/worker 测试服务。

只用于本阶段隔离浏览器测试：
- 使用真实 FastAPI 应用、真实 SQLite 迁移、真实解析 worker 与本地存储；
- 数据目录必须位于 docs/evidence/LOCAL-R1-20261101/S3-DEV 下，不使用项目 var/；
- 显式禁用模型与 OCR（不读取 .env），只处理 docx/xlsx/文字 PDF；
- 仅监听 127.0.0.1，由 folder-upload-real-run.py 启动和停止本进程。

用法（由 runner 调用）：
    .venv/Scripts/python.exe -B frontend/e2e/folder-upload-real-server.py \
        --port 8181 --backend-origin http://127.0.0.1:8181 \
        --frontend-origin http://127.0.0.1:5874 \
        --data-dir docs/evidence/LOCAL-R1-20261101/S3-DEV/tmp/real-.../data \
        --log-file docs/evidence/LOCAL-R1-20261101/S3-DEV/logs/real-server-....jsonl
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_ROOT = (ROOT / "docs" / "evidence" / "LOCAL-R1-20261101" / "S3-DEV").resolve()
sys.path.insert(0, str(ROOT / "backend" / "src"))

from fastapi.responses import JSONResponse  # noqa: E402  (需先插入 sys.path)
from mktkb.config import Settings  # noqa: E402
from mktkb.ingestion.worker import OcrRateLimiter, run_one_job  # noqa: E402
from mktkb.main import create_app  # noqa: E402


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--backend-origin", required=True)
    parser.add_argument("--frontend-origin", required=True)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--log-file", type=Path, required=True)
    parser.add_argument("--admin-username", default="admin")
    parser.add_argument("--employee-username", default="employee")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    data_dir = args.data_dir.resolve()
    try:
        data_dir.relative_to(EVIDENCE_ROOT)
    except ValueError:
        raise SystemExit(f"拒绝使用 S3-DEV 之外的数据目录：{data_dir}") from None
    if data_dir == EVIDENCE_ROOT:
        raise SystemExit("数据目录不能是 S3-DEV 根目录")
    database_path = data_dir / "mktkb.sqlite3"
    if database_path.exists():
        raise SystemExit(f"数据目录已有数据库，请换新的隔离目录：{database_path}")
    data_dir.mkdir(parents=True, exist_ok=True)

    admin_password = os.environ.get("S3_REAL_ADMIN_PASSWORD", "")
    employee_password = os.environ.get("S3_REAL_EMPLOYEE_PASSWORD", "")
    csrf_secret = os.environ.get("S3_REAL_CSRF_SECRET", "")
    if len(admin_password) < 8 or len(employee_password) < 8 or len(csrf_secret) < 16:
        raise SystemExit("缺少临时凭据环境变量（S3_REAL_ADMIN_PASSWORD / S3_REAL_EMPLOYEE_PASSWORD / S3_REAL_CSRF_SECRET）")

    args.log_file.parent.mkdir(parents=True, exist_ok=True)
    log_handle = args.log_file.open("w", encoding="utf-8")
    log_lock = threading.Lock()

    def log(kind: str, **fields: object) -> None:
        record = {"ts": utc_now(), "kind": kind, **fields}
        with log_lock:
            log_handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            log_handle.flush()

    settings = Settings(
        _env_file=None,
        data_dir=data_dir,
        database_url=f"sqlite:///{database_path.as_posix()}",
        storage_dir=data_dir / "storage",
        trusted_origins=[args.backend_origin, args.frontend_origin],
        cookie_secure=False,
        csrf_secret=csrf_secret,
        bcrypt_rounds=4,
        admin_username=args.admin_username,
        admin_password=admin_password,
        admin_display_name="S3隔离管理员",
        employee_username=args.employee_username,
        employee_password=employee_password,
        employee_display_name="S3隔离员工",
        model_base_url=None,
        model_name=None,
        model_api_key=None,
        ocr_secret_id=None,
        ocr_secret_key=None,
        log_level="WARNING",
    )
    app = create_app(settings)
    stop = threading.Event()
    server_holder: dict[str, object] = {"server": None}

    @app.get("/__s3/status")
    def s3_status() -> JSONResponse:  # noqa: ANN202
        return JSONResponse({"ok": True, "service": "s3-folder-real", "data_dir": str(data_dir)})

    @app.post("/__s3/shutdown")
    def s3_shutdown() -> JSONResponse:  # noqa: ANN202
        stop.set()
        server = server_holder.get("server")
        if server is not None:
            server.should_exit = True  # type: ignore[attr-defined]
        log("shutdown_requested")
        return JSONResponse({"ok": True})

    def worker_loop() -> None:
        limiter = OcrRateLimiter(max_per_second=settings.ocr_max_requests_per_second)
        options = {
            "max_attempts": settings.ocr_max_attempts,
            "retry_base_seconds": settings.ocr_retry_base_seconds,
            "retry_max_single_seconds": settings.ocr_retry_max_single_seconds,
            "retry_total_seconds": settings.ocr_retry_total_seconds,
        }
        log("worker_started")
        while not stop.is_set():
            db = app.state.db.session()
            try:
                result = run_one_job(
                    db,
                    app.state.store,
                    ocr=None,
                    ocr_limiter=limiter,
                    ocr_options=options,
                    lease_seconds=settings.job_lease_seconds,
                    renew_seconds=settings.job_lease_renew_seconds,
                    owner="s3-folder-real-worker",
                )
                if result.job_id is not None:
                    log(
                        "job",
                        job_id=str(result.job_id),
                        state=result.state,
                        units_written=result.units_written,
                        units_reused=result.units_reused,
                        error_code=result.error_code,
                        total_pages=result.total_pages,
                    )
            except Exception as exc:  # 不输出异常正文，避免把配置值带进证据
                log("worker_error", error_type=type(exc).__name__)
            finally:
                db.close()
            stop.wait(0.25)
        log("worker_stopped")

    import uvicorn

    config = uvicorn.Config(app, host="127.0.0.1", port=args.port, log_level="warning", access_log=False, lifespan="on")
    server = uvicorn.Server(config)
    server_holder["server"] = server
    worker = threading.Thread(target=worker_loop, name="s3-folder-real-worker", daemon=True)
    log(
        "startup",
        backend_origin=args.backend_origin,
        frontend_origin=args.frontend_origin,
        data_dir=str(data_dir),
        database=str(database_path),
        model_enabled=False,
        ocr_enabled=False,
    )
    worker.start()
    try:
        server.run()
    finally:
        stop.set()
        worker.join(timeout=30)
        log("shutdown", worker_alive=worker.is_alive())
        log_handle.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""T08 浏览器测试专用单次 worker：真实解析流程 + 受控 OCR（额度不足）。

与产品 `mktkb.ingestion.worker` 的单次入口保持同一领取/检查点/失败语义，
只把 OCR 网关替换为固定“额度不足”的测试替身，避免读取任何真实云凭据。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT / "backend" / "src"))

from mktkb.db import Database  # noqa: E402
from mktkb.documents.service import Store, UploadLimits  # noqa: E402
from mktkb.ingestion.worker import (  # noqa: E402
    LOCAL_LEASE_SECONDS,
    LOCAL_RENEW_SECONDS,
    OcrRateLimiter,
    run_one_job,
)
from mktkb.providers.types import OCRQuotaUnavailable  # noqa: E402


class QuotaExhaustedOCR:
    def recognize(self, page, *, mode):  # noqa: ANN001
        raise OCRQuotaUnavailable("t08 controlled OCR quota exhausted")

    def close(self) -> None:
        return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="T08 test worker (controlled OCR)")
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--storage-dir", required=True)
    parser.add_argument("--max-jobs", type=int, default=1)
    args = parser.parse_args(argv)

    database = Database(args.database_url)
    store = Store(Path(args.storage_dir), UploadLimits())
    db = database.session()
    exit_code = 0
    try:
        ocr = QuotaExhaustedOCR()
        result = run_one_job(
            db,
            store,
            ocr=ocr,
            ocr_limiter=OcrRateLimiter(max_per_second=2.0),
            ocr_options={
                "max_attempts": 3,
                "retry_base_seconds": 0.25,
                "retry_max_single_seconds": 1.0,
                "retry_total_seconds": 2.0,
            },
            lease_seconds=LOCAL_LEASE_SECONDS,
            renew_seconds=LOCAL_RENEW_SECONDS,
        )
        print(
            json.dumps(
                {
                    "job_id": str(result.job_id) if result.job_id else None,
                    "state": result.state,
                    "units_written": result.units_written,
                    "units_reused": result.units_reused,
                    "total_pages": result.total_pages,
                    "error_code": result.error_code,
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        if result.state in {"failed", "blocked", "lease_lost"}:
            exit_code = 1
    finally:
        db.close()
        database.dispose()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())

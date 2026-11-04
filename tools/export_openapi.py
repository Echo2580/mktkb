r"""导出后端 OpenAPI 快照，供前端生成 TypeScript 类型（T08）。

只做应用构建，不启动服务、不连接数据库、不读取项目根目录的 .env：
- ``Settings(_env_file=None, ...)`` 显式关闭 .env 读取；
- ``create_app(settings, initialize=False)`` 不执行迁移、不创建存储目录；
- 数据库 URL 指向临时文件，避免在项目内产生运行数据。

用法（在项目根目录）：
    .\.venv\Scripts\python.exe -B tools/export_openapi.py --output docs/evidence/T08/api/openapi.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_SRC = PROJECT_ROOT / "backend" / "src"


def build_settings(tmp_dir: Path):
    sys.path.insert(0, str(BACKEND_SRC))
    from mktkb.config import Settings

    # 仅用于离线 schema 导出：固定占位值，不是任何环境的真实凭据。
    return Settings(
        _env_file=None,
        data_dir=tmp_dir / "data",
        database_url=f"sqlite:///{(tmp_dir / 'schema-only.sqlite3').as_posix()}",
        storage_dir=tmp_dir / "storage",
        csrf_secret="openapi-export-placeholder-secret",
        admin_password="openapi-export-admin",
        employee_password="openapi-export-employee",
        cookie_secure=False,
        trusted_origins=["http://127.0.0.1:5173"],
        log_level="ERROR",
    )


def export_openapi(output: Path) -> dict:
    with tempfile.TemporaryDirectory(prefix="mktkb-openapi-") as tmp:
        settings = build_settings(Path(tmp))
        from mktkb.main import create_app

        app = create_app(settings, initialize=False)
        schema = app.openapi()
    output.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    output.write_text(text, encoding="utf-8")
    return schema


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export the FastAPI OpenAPI schema without starting a server.")
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "docs" / "evidence" / "T08" / "api" / "openapi.json",
    )
    args = parser.parse_args(argv)
    schema = export_openapi(args.output)
    payload = args.output.read_bytes()
    print(
        json.dumps(
            {
                "output": str(args.output),
                "paths": len(schema.get("paths", {})),
                "operations": sum(
                    len([method for method in item if method.lower() in {"get", "post", "put", "patch", "delete"}])
                    for item in schema.get("paths", {}).values()
                ),
                "openapi": schema.get("openapi"),
                "sha256": hashlib.sha256(payload).hexdigest(),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

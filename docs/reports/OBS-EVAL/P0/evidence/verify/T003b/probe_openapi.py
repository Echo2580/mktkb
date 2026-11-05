"""T003b 独立验收：OpenAPI 兼容性探针。

用法：python probe_openapi.py <backend_src_dir> > spec.json
只读：create_app(initialize=False)，不建业务库、不写 var/、不读 .env。
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

src = Path(sys.argv[1]).resolve()
assert (src / "mktkb" / "config.py").exists(), f"不是 mktkb 源码目录：{src}"
sys.path.insert(0, str(src))

import mktkb  # noqa: E402

from mktkb.config import Settings  # noqa: E402
from mktkb.main import create_app  # noqa: E402

tmp = Path(tempfile.mkdtemp(prefix="t003b-openapi-"))
settings = Settings(
    _env_file=None,
    data_dir=tmp / "data",
    cookie_secure=False,
    csrf_secret="unit-test-csrf-secret-0123456789",
    admin_password="AdminPass-1",
    employee_password="EmployeePass-1",
    trusted_origins=["http://testserver"],
    bcrypt_rounds=4,
    session_ttl_seconds=3600,
)
app = create_app(settings, initialize=False)
try:
    spec = app.openapi()
    payload = {
        "info": spec.get("info"),
        "paths": spec.get("paths"),
        "components": spec.get("components"),
        "openapi": spec.get("openapi"),
    }
finally:
    app.state.db.dispose()
    qa = getattr(app.state, "qa", None)
    if qa is not None:
        qa.close()
print(f"mktkb_file={Path(mktkb.__file__).resolve()}", file=sys.stderr)
print(f"src_dir={src}", file=sys.stderr)
sys.stdout.write(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=1))
sys.stdout.write("\n")

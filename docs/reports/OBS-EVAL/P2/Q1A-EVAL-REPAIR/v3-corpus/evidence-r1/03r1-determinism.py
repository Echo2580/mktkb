"""v3 语料返工 R1：字节级确定性（同一生成器连跑两次 → 同一 SHA256，且等于交付件）。

做法与上一轮逐条相同，只换生成器（R1 版）：``01r1-build-corpus.py`` 在**两个全新临时目录**
各跑一次，逐文件比较 SHA256；再与仓库内已交付的 ``fixtures/acceptance-h2v3/`` 逐文件比较。
三者必须全等。同时记录确定性契约的可核事实（entry 顺序 / 时间戳 / 压缩方式 / create_system /
external_attr）与 CPython / openpyxl 版本。

零真实调用；临时目录在系统 temp 下，跑完即删。
用法：``.venv\\Scripts\\python.exe 03r1-determinism.py``
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

import openpyxl

HERE = Path(__file__).resolve().parent
ROOT = Path(__file__).resolve().parents[7]
GENERATOR = HERE / "01r1-build-corpus.py"
DELIVERED = ROOT / "fixtures/acceptance-h2v3"
OUT = HERE / "03r1-determinism.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inventory(root: Path) -> dict:
    return {
        str(path.relative_to(root)).replace("\\", "/"): {"bytes": path.stat().st_size, "sha256": sha256_file(path)}
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def main() -> int:
    runs = {}
    with tempfile.TemporaryDirectory() as workdir:
        for label in ("run1", "run2"):
            target = Path(workdir) / label
            result = subprocess.run(
                [sys.executable, "-B", str(GENERATOR), "--output", str(target)], capture_output=True, cwd=str(ROOT)
            )
            if result.returncode != 0:
                print(result.stderr.decode("utf-8", "replace"), file=sys.stderr)
                return 1
            runs[label] = inventory(target)
        run1, run2 = runs["run1"], runs["run2"]
    delivered = inventory(DELIVERED)
    keys = sorted(set(run1) | set(run2) | set(delivered))
    rows = []
    for key in keys:
        digests = {
            "run1": run1.get(key, {}).get("sha256"),
            "run2": run2.get(key, {}).get("sha256"),
            "delivered": delivered.get(key, {}).get("sha256"),
        }
        rows.append({"path": key, **digests, "all_equal": len({value for value in digests.values() if value}) == 1 and all(digests.values())})

    sample = DELIVERED / "normal/D01_物品位置表.xlsx"
    with zipfile.ZipFile(sample) as archive:
        zip_facts = {
            "entry_order": [info.filename for info in archive.infolist()],
            "date_times": sorted({info.date_time for info in archive.infolist()}),
            "compress_types": sorted({info.compress_type for info in archive.infolist()}),
            "create_systems": sorted({info.create_system for info in archive.infolist()}),
            "external_attrs": sorted({info.external_attr for info in archive.infolist()}),
            "sample": str(sample.relative_to(ROOT)).replace("\\", "/"),
        }
    payload = {
        "schema_version": "p2h2v3-determinism/v0.1",
        "phase": "determinism-r1",
        "method": "R1 生成器在两个全新临时目录各跑一次，逐文件比较 SHA256，并与仓库交付件比较",
        "generator": "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/v3-corpus/evidence-r1/01r1-build-corpus.py",
        "python_version": sys.version.split()[0],
        "openpyxl_version": openpyxl.__version__,
        "zip_contract": zip_facts,
        "files": rows,
        "totals": {
            "files": len(rows),
            "all_equal": sum(1 for row in rows if row["all_equal"]),
            "mismatched": sum(1 for row in rows if not row["all_equal"]),
        },
        "result": "BYTE_IDENTICAL_TWICE_AND_DELIVERED" if all(row["all_equal"] for row in rows) else "NON_DETERMINISTIC",
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"totals": payload["totals"], "result": payload["result"], "zip_contract": zip_facts}, ensure_ascii=False, indent=1))
    return 0 if payload["result"] == "BYTE_IDENTICAL_TWICE_AND_DELIVERED" else 1


if __name__ == "__main__":
    sys.exit(main())

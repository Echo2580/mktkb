"""T003c 独立验收：比较旧/新代码在“无 trace”下的业务输出是否逐字段一致。

用法：python compare_plain.py <old.json> <new.json> <report.txt>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

TIMING_KEYS = {"elapsed_ms", "ms", "vector_query_ms", "latency_ms"}


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def normalize(payload: dict) -> dict:
    body = {
        "first": payload["first"],
        "second": payload["second"],
        "scenarios": payload.get("scenarios", {}),
    }
    root = payload.get("work_root") or ""
    text = json.dumps(body, ensure_ascii=False, sort_keys=True)
    if root:
        text = text.replace(root.replace("\\", "\\\\"), "<WORK_ROOT>").replace(
            root, "<WORK_ROOT>"
        )
    return json.loads(text)


def main() -> int:
    old = normalize(load(Path(sys.argv[1])))
    new = normalize(load(Path(sys.argv[2])))
    report: list[str] = []
    ok = True
    checks = {
        "first": old["first"] == new["first"],
        "second": old["second"] == new["second"],
    }
    for label in sorted(set(old.get("scenarios", {})) | set(new.get("scenarios", {}))):
        checks[f"scenario:{label}"] = old.get("scenarios", {}).get(label) == new.get(
            "scenarios", {}
        ).get(label)
    for key, equal in checks.items():
        if equal:
            report.append(f"OK   {key}: 逐字段一致")
        else:
            ok = False
            report.append(f"DIFF {key}:")
            old_text = json.dumps(
                (old.get("scenarios", {}) if key.startswith("scenario:") else old)[
                    key.split(":", 1)[1] if key.startswith("scenario:") else key
                ],
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            new_text = json.dumps(
                (new.get("scenarios", {}) if key.startswith("scenario:") else new)[
                    key.split(":", 1)[1] if key.startswith("scenario:") else key
                ],
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            import difflib

            diff = difflib.unified_diff(
                old_text.splitlines(),
                new_text.splitlines(),
                fromfile="old",
                tofile="new",
                lineterm="",
            )
            report.extend(diff)
    report.append("RESULT " + ("PASS" if ok else "FAIL"))
    text = "\n".join(report)
    Path(sys.argv[3]).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

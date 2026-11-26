"""C1-P4 独立验收：探针公共记录器（不导入被测测试，不复制开发用例）。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

OUT = Path(__file__).resolve().parent / "out"


class Checks:
    """逐项记录断言结果，输出机器可读 JSON。"""

    def __init__(self, probe: str) -> None:
        self.probe = probe
        self.rows: list[dict[str, Any]] = []
        self.failures = 0

    def record(self, ok: bool, name: str, detail: Any = None) -> bool:
        row: dict[str, Any] = {"name": name, "ok": bool(ok)}
        if detail is not None:
            row["detail"] = detail
        self.rows.append(row)
        if not ok:
            self.failures += 1
        return bool(ok)

    def eq(self, name: str, actual: Any, expected: Any, detail: Any = None) -> bool:
        payload: dict[str, Any] = {"actual": actual, "expected": expected}
        if detail is not None:
            payload["extra"] = detail
        return self.record(actual == expected, name, payload)

    def write(self, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        OUT.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any] = {
            "probe": self.probe,
            "generated_utc": datetime.now(timezone.utc).isoformat(),
            "check_count": len(self.rows),
            "failure_count": self.failures,
            "verdict": "PASS" if self.failures == 0 else "FAIL",
            "checks": self.rows,
        }
        if extra:
            payload.update(extra)
        path = OUT / f"{self.probe}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"[{self.probe}] checks={len(self.rows)} failures={self.failures} -> {path.name}")
        return payload


def code_of(fn: Callable[[], Any]) -> str | None:
    """运行 fn 并返回固定码；成功返回 None；非固定码异常显式标记。

    兼容两类校验器：P4 适配器抛 ``AdapterError``，Q1a-1b 旧校验器抛 ``RescoreError``；
    两者都带 ``.code``。裸异常（无 ``code``）标记为 ``EXC:``，不当作 fail-closed。
    """
    try:
        fn()
    except Exception as exc:  # noqa: BLE001 - 探针要区分“固定码”与“裸异常”
        code = getattr(exc, "code", None)
        if isinstance(code, str) and code:
            return code
        return f"EXC:{type(exc).__name__}:{exc}"
    return None

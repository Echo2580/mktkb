"""P0 收尾核验用 pytest 插件：输出机器可读的逐用例 nodeid 结果。

用法：
    set P0_REPORT=<输出 json 路径>
    在 PYTHONPATH 中加入本文件所在目录，pytest 加 `-p report_plugin`

输出结构：
    {"nodeid": ..., "outcome": "passed|failed|error|skipped", "when": ...,
     "duration": ..., "exc": "首行异常摘要"}
只记录最终结果，setup/teardown 失败归为 error。
"""

from __future__ import annotations

import json
import os
import traceback
from pathlib import Path

_STATE: dict[str, dict] = {}
_ORDER: list[str] = []


def pytest_runtest_logreport(report):  # noqa: ANN001
    nodeid = report.nodeid
    if nodeid not in _STATE:
        _STATE[nodeid] = {"nodeid": nodeid, "outcome": "passed", "when": "", "duration": 0.0, "exc": ""}
        _ORDER.append(nodeid)
    entry = _STATE[nodeid]
    entry["duration"] += float(getattr(report, "duration", 0.0) or 0.0)

    if report.when == "call":
        if report.outcome == "failed":
            entry["outcome"] = "failed"
            entry["when"] = "call"
            entry["exc"] = _short(report)
        elif report.outcome == "skipped":
            if entry["outcome"] == "passed":
                entry["outcome"] = "skipped"
                entry["when"] = "call"
                entry["exc"] = _short(report)
    elif report.when in ("setup", "teardown") and report.outcome == "failed":
        if entry["outcome"] != "failed":
            entry["outcome"] = "error"
            entry["when"] = report.when
            entry["exc"] = _short(report)


def _short(report) -> str:  # noqa: ANN001
    excinfo = getattr(report, "longrepr", None)
    try:
        if hasattr(excinfo, "reprcrash") and excinfo.reprcrash is not None:
            return str(excinfo.reprcrash.message)[:300]
        text = str(excinfo)
        lines = [line for line in text.splitlines() if line.strip()]
        return lines[-1][:300] if lines else ""
    except Exception:  # pragma: no cover - 报告异常不应影响测试
        return ""


def pytest_sessionfinish(session, exitstatus):  # noqa: ANN001
    target = os.environ.get("P0_REPORT")
    if not target:
        return
    entries = [_STATE[nodeid] for nodeid in _ORDER]
    counts = {"passed": 0, "failed": 0, "error": 0, "skipped": 0}
    for item in entries:
        counts[item["outcome"]] = counts.get(item["outcome"], 0) + 1
    payload = {
        "exitstatus": int(exitstatus),
        "counts": counts,
        "collected": len(entries),
        "tests": entries,
    }
    Path(target).parent.mkdir(parents=True, exist_ok=True)
    with open(target, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=1)

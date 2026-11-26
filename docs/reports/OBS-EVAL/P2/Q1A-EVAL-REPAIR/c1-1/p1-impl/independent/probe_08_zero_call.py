"""Zero-real-call probe with positive and negative controls.

Positive controls exercise socket / create_connection / getaddrinfo / gethostbyname
/ http.client / httpx and must all be blocked and recorded. The negative control
proves assert_clean() bites when the ledger is dirty. The workload then imports
the two target modules and runs the classifier/adapter on synthetic data with
external == 0.
"""

from __future__ import annotations

import importlib.util
import json
import socket
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[8]
OUT = Path(__file__).resolve().parent / "out"
sys.path.insert(0, str(ROOT / "backend" / "src"))

from netguard import NetGuard, NetworkBlocked  # noqa: E402

import synth_stale as S  # noqa: E402

CHECKS: list[dict[str, Any]] = []


def check(name: str, ok: bool, detail: Any = None) -> None:
    CHECKS.append({"name": name, "pass": bool(ok), "detail": detail})


def _positive_controls(guard: NetGuard) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    controls = [
        ("socket.connect", lambda: socket.socket().connect(("127.0.0.1", 9))),
        ("socket.connect_ex", lambda: socket.socket().connect_ex(("127.0.0.1", 9))),
        ("socket.create_connection", lambda: socket.create_connection(("127.0.0.1", 9))),
        ("socket.getaddrinfo", lambda: socket.getaddrinfo("localhost", 9)),
        ("socket.gethostbyname", lambda: socket.gethostbyname("localhost")),
    ]
    for label, action in controls:
        guard.clear()
        try:
            action()
            rows.append({"layer": label, "blocked": False, "recorded": list(guard.events)})
        except NetworkBlocked:
            rows.append({"layer": label, "blocked": True, "recorded": list(guard.events)})
        except Exception as exc:  # noqa: BLE001
            rows.append({"layer": label, "blocked": True, "error": type(exc).__name__, "recorded": list(guard.events)})
    guard.clear()
    try:
        import http.client

        http.client.HTTPConnection("127.0.0.1", 9).connect()
        rows.append({"layer": "http.client.connect", "blocked": False})
    except NetworkBlocked:
        rows.append({"layer": "http.client.connect", "blocked": True, "recorded": list(guard.events)})
    except Exception as exc:  # noqa: BLE001
        rows.append({"layer": "http.client.connect", "blocked": True, "error": type(exc).__name__})
    guard.clear()
    try:
        import httpx

        httpx.Client(trust_env=False, timeout=0.01).get("http://127.0.0.1:9/")
        rows.append({"layer": "httpx.handle_request", "blocked": False})
    except NetworkBlocked:
        rows.append({"layer": "httpx.handle_request", "blocked": True, "recorded": list(guard.events)})
    except Exception as exc:  # noqa: BLE001
        # httpx may wrap the transport error; the important part is the guard ledger.
        rows.append(
            {
                "layer": "httpx.handle_request",
                "blocked": bool(guard.events),
                "error": type(exc).__name__,
                "recorded": list(guard.events),
            }
        )
    return rows


def _stale_workload() -> int:
    from mktkb.evaluation import p2_stale_version_state as stale

    evidence = S.evidence(units=[S.unit("K21")])
    cases = [
        stale.determine_stale_case(S.CRITERION, S.grounding(), evidence),
        stale.determine_stale_case(S.CRITERION, S.grounding(), S.evidence(units=[S.unit("K20")])),
        stale.determine_stale_case(S.CRITERION, S.dated_grounding(), S.evidence(units=[S.unit("K21")], as_of=S.AS_OF)),
        stale.determine_stale_case(S.CRITERION, S.grounding(), S.evidence(with_usage=False)),
    ]
    stale.aggregate_cases(cases)
    return len(cases)


def _adapter_workload() -> int:
    from mktkb.evaluation import p2_evidence_axes_adapter_v2 as adapter

    path = ROOT / "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/c1-1/p4/independent/synth.py"
    spec = importlib.util.spec_from_file_location("p4synth_zero", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    determination = adapter.determine_case(
        contract=module.contract(),
        case_id="C00",
        snapshot=module.snapshot([module.record()]),
    )
    return len(determination.axes)


def main() -> int:
    guard = NetGuard()
    with guard:
        positives = _positive_controls(guard)
        for row in positives:
            check(f"positive.{row['layer']}", row["blocked"] and bool(row.get("recorded")), row)

        # Negative control: a dirty ledger must fail assert_clean.
        guard.clear()
        guard.events.append("synthetic")
        try:
            guard.assert_clean()
            negative = {"raised": False}
        except AssertionError:
            negative = {"raised": True}
        guard.clear()
        check("negative.assert_clean_bites", negative["raised"], negative)

        # Clean workload.
        stale_cases = _stale_workload()
        adapter_axes = _adapter_workload()
        try:
            guard.assert_clean()
            clean = True
        except AssertionError as exc:
            clean = False
        check("workload.external_zero", clean, {"events": list(guard.events)})
        check("workload.ran", stale_cases == 4 and adapter_axes == 2, {"stale_cases": stale_cases, "adapter_axes": adapter_axes})

    # Static import surface: no network clients in either target module.
    for label, rel in (
        ("stale", "backend/src/mktkb/evaluation/p2_stale_version_state.py"),
        ("adapter", "backend/src/mktkb/evaluation/p2_evidence_axes_adapter_v2.py"),
    ):
        source = (ROOT / rel).read_text(encoding="utf-8")
        tokens = [token for token in ("import requests", "import httpx", "import socket", "import urllib", "openai", "anthropic", "aiohttp") if token in source]
        check(f"static.{label}.no_network_imports", tokens == [], tokens)

    report = {
        "schema_version": "c1p1impl-zero-call/v0.1",
        "checks": CHECKS,
        "failures": [row for row in CHECKS if not row["pass"]],
        "positive_controls": positives,
        "external": 0,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "08-zero-call.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "checks": len(CHECKS),
                "failed": len(report["failures"]),
                "failures": report["failures"],
                "positive_layers": [row["layer"] for row in positives],
                "external": 0,
            },
            ensure_ascii=False,
            indent=1,
        )
    )
    return 0 if not report["failures"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

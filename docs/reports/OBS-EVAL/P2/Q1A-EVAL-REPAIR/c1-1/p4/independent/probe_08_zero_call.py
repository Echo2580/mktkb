"""必测 8：零调用 —— 干净段 external=0；正对照故意出站全被拦并记账；负对照不清账必报错。"""

from __future__ import annotations

import httpx
import http.client
import socket
from typing import Any, Callable

from harness import Checks
from netguard import NetGuard, NetworkBlocked
import synth

from mktkb.evaluation.p2_evidence_axes_adapter_v2 import determine_case

EXTERNAL_IP = "203.0.113.1"  # TEST-NET-3，保留给文档/测试，不是可达服务
EXTERNAL_HOST = "example.invalid"


def attempt(netguard: NetGuard, label: str, fn: Callable[[], Any]) -> dict[str, Any]:
    try:
        fn()
    except NetworkBlocked as exc:
        return {"label": label, "blocked": True, "error": str(exc), "recorded": netguard.external()}
    except Exception as exc:  # noqa: BLE001
        return {"label": label, "blocked": False, "error": f"{type(exc).__name__}: {exc}", "recorded": netguard.external()}
    return {"label": label, "blocked": False, "error": None, "recorded": netguard.external()}


def workload() -> dict[str, Any]:
    payload = synth.contract({0: synth.case_axes(
        cross_entity=synth.axis("required", "structured_target", "explicit_single_target",
                                targets=[synth.target("item", "item|storea|itema", {"store": "StoreA", "item": "ItemA"})]),
        stale_source=synth.axis("required", "lifecycle_dates", "published_lifecycle",
                                target_refs=[synth.ref("expected_sources", 0)]),
    )})
    results = {}
    for name, records in {
        "pass": [synth.record()],
        "class_c": [],
        "document": [synth.document_record()],
    }.items():
        determination = determine_case(
            contract=payload,
            case_id="C00",
            snapshot=synth.snapshot(records),
            frozen_refs={"expected_sources": [{"record_code": "W01"}]},
        )
        results[name] = {
            axis: determination.axes[axis].state for axis in ("cross_entity", "stale_source")
        }
    return results


def main() -> dict:
    checks = Checks("08-zero-call")
    guard = NetGuard().install()
    try:
        # ---- 干净段：被测模块全流程（无出站） ----------------------------- #
        guard.clear()
        results = workload()
        clean_external = guard.external()
        checks.eq("clean_segment_external_zero", clean_external, 0)
        checks.eq("clean_segment_attempts", guard.attempts, [])
        checks.record("clean_segment_workload_ran", bool(results), results)

        # ---- 正对照：四类故意出站必须被拦并记账 --------------------------- #
        guard.clear()
        controls = [
            attempt(guard, "socket.create_connection", lambda: socket.create_connection((EXTERNAL_IP, 80), timeout=1)),
            attempt(guard, "socket.getaddrinfo", lambda: socket.getaddrinfo(EXTERNAL_HOST, 80)),
            attempt(guard, "socket.connect", lambda: _raw_connect()),
            attempt(guard, "socket.connect_ex", lambda: _raw_connect_ex()),
            attempt(guard, "socket.gethostbyname", lambda: socket.gethostbyname(EXTERNAL_HOST)),
            attempt(guard, "http.client.connect", lambda: _http_connect()),
            attempt(guard, "httpx", lambda: httpx.Client(trust_env=False, timeout=1).get(f"http://{EXTERNAL_IP}/")),
        ]
        control_kinds = guard.kinds()
        blocked = [row for row in controls if row["blocked"]]
        checks.eq("positive_control_all_blocked", len(blocked), len(controls), controls)
        checks.eq("positive_control_all_recorded", all(row["recorded"] >= 1 for row in controls), True)
        checks.eq("positive_control_external_count", guard.external(), len(controls))
        required_kinds = {
            "socket.connect",
            "socket.connect_ex",
            "socket.create_connection",
            "socket.getaddrinfo",
            "socket.gethostbyname",
            "http.client.connect",
            "httpx.HTTPTransport.handle_request",
        }
        checks.record(
            "positive_control_covers_transport_layers",
            set(control_kinds) >= required_kinds,
            {"kinds": control_kinds, "missing": sorted(required_kinds - set(control_kinds))},
        )

        # ---- 负对照：账未清时 assert_clean 必须报错 ----------------------- #
        dirty_failed = False
        try:
            guard.assert_clean()
        except AssertionError:
            dirty_failed = True
        checks.eq("negative_control_dirty_ledger_raises", dirty_failed, True)
        checks.record("negative_control_ledger_not_empty", guard.external() > 0, guard.external())

        # ---- 清账后必须通过 ---------------------------------------------- #
        guard.clear()
        passed_after_clear = True
        try:
            guard.assert_clean()
        except AssertionError:
            passed_after_clear = False
        checks.eq("clean_ledger_passes_after_clear", passed_after_clear, True)

        # ---- 再跑一遍 workload，确认清账后仍 external=0 ------------------- #
        results2 = workload()
        checks.eq("post_control_workload_external_zero", guard.external(), 0)
        checks.eq("post_control_workload_same_results", results2, results)
    finally:
        guard.uninstall()

    # ---- 卸载守卫后不改变事实：报告环境代理是否存在（只读环境变量名） ---- #
    import os

    proxy_keys = [key for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy") if os.environ.get(key)]
    checks.record(
        "proxy_env_present_but_unused",
        True,
        {"proxy_keys": proxy_keys, "note": "守卫在 connect/getaddrinfo/httpx 三层拦截，且 httpx 显式 trust_env=False"},
    )

    return checks.write(
        {
            "clean_external": clean_external,
            "controls": controls,
            "guard_kinds": control_kinds,
            "workload": results,
            "proxy_env": proxy_keys,
        }
    )


def _raw_connect() -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.settimeout(1)
        sock.connect((EXTERNAL_IP, 80))
    finally:
        sock.close()


def _raw_connect_ex() -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.settimeout(1)
        sock.connect_ex((EXTERNAL_IP, 80))
    finally:
        sock.close()


def _http_connect() -> None:
    connection = http.client.HTTPConnection(EXTERNAL_IP, 80, timeout=1)
    try:
        connection.connect()
    finally:
        connection.close()


if __name__ == "__main__":
    main()

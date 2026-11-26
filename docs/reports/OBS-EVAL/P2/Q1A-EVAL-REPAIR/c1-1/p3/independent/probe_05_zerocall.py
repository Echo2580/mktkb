"""C1-P3 独立验收探针 5/6：零出站的正/负向控制（自建守卫，不复用开发 netguard）。

三段：
1. 干净运行：在守卫下重放一次快照校验/落盘/读回，external 必须为 0；
2. 正向控制：故意发起 4 类出站（TCP connect / DNS / http.client / httpx），必须**全部被拦并记账**；
3. 负向控制：不清账时 `assert_clean()` 必须报错；清账后必须通过。
"""
from __future__ import annotations

import http.client
import json
import socket
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import netguard_independent as guard  # noqa: E402

guard.install()

from cryptography.fernet import Fernet  # noqa: E402

from mktkb.evaluation.p2_evidence_snapshot_v03 import (  # noqa: E402
    SnapshotWriter,
    read_snapshot_evidence,
    validate_identity_snapshot,
)

CACHE = json.loads((HERE / "out" / "02-capture-cache.json").read_text(encoding="utf-8"))
BINDINGS = CACHE["bindings"]
SNAPSHOTS = CACHE["snapshots"]


def clean_phase() -> dict:
    guard.reset()
    validate_identity_snapshot(SNAPSHOTS[1], expected_bindings=BINDINGS)
    temp = Path(tempfile.mkdtemp(prefix="c1p3-independent-zero-"))
    writer = SnapshotWriter(
        root_dir=temp / "snapshots", key=Fernet.generate_key(), bindings=BINDINGS, run_name="zero"
    )
    receipt = writer.write_snapshot(SNAPSHOTS[1])
    read_snapshot_evidence(Path(receipt["path"]), key=writer.key, expected_bindings=BINDINGS)
    guard.assert_clean()
    return {
        "external_attempts": guard.snapshot()["external_attempts"],
        "counts": guard.counters(),
        "assert_clean": "passed",
    }


def positive_phase() -> dict:
    guard.reset()
    attempts: list[dict] = []

    def try_call(name: str, func) -> None:
        try:
            func()
        except Exception as exc:  # noqa: BLE001 - 被拦是预期
            attempts.append({"name": name, "blocked": True, "error": type(exc).__name__})
        else:
            attempts.append({"name": name, "blocked": False, "error": None})

    try_call("tcp_connect", lambda: socket.create_connection(("203.0.113.9", 9), timeout=1))
    try_call("dns_lookup", lambda: socket.getaddrinfo("example.invalid", 80))
    try_call("http_client", lambda: http.client.HTTPConnection("203.0.113.9", 9, timeout=1).connect())
    # trust_env=False：本机 HTTP(S)_PROXY 指向 127.0.0.1:7897，若走代理会把外联转给代理进程；
    # 这里显式关闭 env 代理，确保打到 httpx 传输层守卫（代理本身是 loopback，socket 层会放行）。
    try_call(
        "httpx_get",
        lambda: __import__("httpx").get("http://203.0.113.9:9/", timeout=1, trust_env=False),
    )
    import os

    env_proxy_note = {
        key: value
        for key, value in os.environ.items()
        if key.upper() in {"ALL_PROXY", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY"}
    }
    snapshot = guard.snapshot()
    return {
        "attempts": attempts,
        "blocked_count": sum(1 for item in attempts if item["blocked"]),
        "ledger": snapshot["ledger"],
        "external_attempts": snapshot["external_attempts"],
        "counts": snapshot["counts"],
        "env_proxy_note": env_proxy_note,
    }


def main() -> int:
    clean = clean_phase()
    positive = positive_phase()
    # 负向控制：刚发生外部尝试、尚未清账 → 必须报错
    negative = {"raised": False, "error": None}
    try:
        guard.assert_clean()
    except RuntimeError as exc:
        negative = {"raised": True, "error": str(exc)[:200]}
    # 清账后必须通过
    guard.reset()
    guard.assert_clean()
    cleared = {"raised": False, "external_attempts": guard.snapshot()["external_attempts"]}

    result = {
        "probe": "zero-call",
        "clean_phase": clean,
        "positive_control": positive,
        "negative_control_uncleared": negative,
        "after_reset": cleared,
        "verdict": "PASS"
        if (
            clean["external_attempts"] == 0
            and positive["blocked_count"] == len(positive["attempts"]) == 4
            and positive["external_attempts"] >= 4
            and negative["raised"] is True
            and cleared["external_attempts"] == 0
        )
        else "FAIL",
    }
    (HERE / "out" / "05-zero-call.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return 0 if result["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""零调用守卫：拦截并计数所有非本机 socket 连接；先做一次正对照（应被拦），再执行目标脚本。

用法：
    python zero_call_guard.py <target.py> <result.json> [target args...]

输出 JSON：正对照是否被拦、目标执行期间的外部尝试次数/地址（脱敏为 host:port）、退出码。
目标脚本自身的 stdout/stderr 原样透传。
"""

import json
import runpy
import socket
import sys
import traceback

_attempts: list[str] = []
_positive: dict[str, object] = {}


def _local(host: object) -> bool:
    return str(host) in {"127.0.0.1", "::1", "localhost", "0.0.0.0"}


def _guard(self, address, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
    try:
        host, port = address[0], address[1]
    except Exception:  # noqa: BLE001
        host, port = address, "?"
    if _local(host):
        return _original(self, address, *args, **kwargs)
    _attempts.append(f"{host}:{port}")
    raise OSError("NETGUARD_BLOCKED")


_original = socket.socket.connect
socket.socket.connect = _guard

# 正对照：TEST-NET-1 数值地址，不做 DNS；在 connect 前被拦。
try:
    socket.create_connection(("192.0.2.1", 80), timeout=1)
    _positive = {"blocked": False, "note": "positive control unexpectedly connected"}
except OSError as exc:
    _positive = {"blocked": True, "error": str(exc)}
_attempts_after_positive = len(_attempts)
_attempts.clear()


def main() -> int:
    target = sys.argv[1]
    result_path = sys.argv[2]
    target_args = sys.argv[3:]
    sys.argv = [target, *target_args]
    exit_code = 0
    error = None
    try:
        runpy.run_path(target, run_name="__main__")
    except SystemExit as exc:  # 目标脚本可能自行退出
        exit_code = int(exc.code or 0)
    except BaseException:  # noqa: BLE001
        exit_code = 1
        error = traceback.format_exc(limit=3)
    payload = {
        "schema_version": "p2-h2v3-zero-call-guard/v0.1",
        "positive_control": _positive,
        "positive_control_attempts": _attempts_after_positive,
        "external_attempts": len(_attempts),
        "external_addresses": sorted(set(_attempts)),
        "target": target,
        "target_args": target_args,
        "exit_code": exit_code,
        "error": error,
    }
    with open(result_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())

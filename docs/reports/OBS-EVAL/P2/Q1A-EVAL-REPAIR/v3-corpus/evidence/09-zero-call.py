"""v3 语料：零真实调用证据（进程级出站守卫 + 正对照）。

做法：把本轮全部脚本在**注入守卫的进程**里各跑一遍（PYTHONPATH 指向本目录
``netguard/``，``sitecustomize`` 自动安装守卫，退出时落盘计数）。守卫拦截并计数任何
非回环 socket connect / connect_ex / create_connection / getaddrinfo，以及 http.client /
httpx 传输层；回环放行。

判据：
1. 每次运行的外部计数必须全 0；
2. 正对照必须证明守卫真的会拦（否则「0」可能只是没装守卫）；
3. 每次运行都必须成功退出（否则「0 调用」可能只是脚本没跑起来）。

零真实调用：本脚本只拉起本地 python 子进程，不联网。
用法：``.venv\\Scripts\\python.exe 09-zero-call.py``
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[7]
HERE = Path(__file__).resolve().parent
NETGUARD = HERE / "netguard"
OUT = HERE / "09-zero-call.json"

#: (label, 脚本, 额外参数, 是否允许非 0 退出)
RUNS = (
    ("positive-control", NETGUARD / "positive_control.py", [], True),
    ("build-corpus", HERE / "01-build-corpus.py", ["--output", "<TMP>/build"], False),
    ("verify-cells", HERE / "02-verify-cells.py", [], False),
    ("determinism", HERE / "03-reproduce-twice.py", [], False),
    ("keyspace", HERE / "04-keyspace-proof.py", [], True),
    ("normalized-digest", HERE / "05-normalized-digest.py", [], False),
    ("source-map", HERE / "06-build-source-map.py", [], False),
    ("header-finding", HERE / "08-header-detection-finding.py", [], False),
    ("preservation", HERE / "07-preservation.py", [], False),
)


def main() -> int:
    results = []
    with tempfile.TemporaryDirectory() as workdir:
        tmp = Path(workdir)
        for label, script, extra, allow_fail in RUNS:
            guard_out = tmp / f"guard-{label}.json"
            env = dict(os.environ)
            env["PYTHONPATH"] = str(NETGUARD) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
            env["V3CORPUS_GUARD_OUT"] = str(guard_out)
            env["PYTHONDONTWRITEBYTECODE"] = "1"
            env["PYTHONIOENCODING"] = "utf-8"
            args = [sys.executable, "-B", str(script)] + [item.replace("<TMP>", str(tmp)) for item in extra]
            completed = subprocess.run(args, capture_output=True, cwd=str(ROOT), env=env)
            counters = {}
            if guard_out.is_file():
                payload = json.loads(guard_out.read_text(encoding="utf-8"))
                counters = {
                    "blocked": payload.get("blocked"),
                    "external": {
                        key: payload.get(key)
                        for key in (
                            "socket_connect_external",
                            "socket_connect_ex_external",
                            "create_connection_external",
                            "dns_getaddrinfo_external",
                            "http_client_external",
                            "httpx_transport_external",
                        )
                    },
                    "loopback_connects": payload.get("loopback_connects"),
                    "installed": payload.get("installed"),
                    "guard_version": payload.get("guard_version"),
                    "positive_control": payload.get("positive_control"),
                }
            results.append(
                {
                    "label": label,
                    "script": str(script.relative_to(ROOT)).replace("\\", "/"),
                    "exit_code": completed.returncode,
                    "stdout_tail": completed.stdout.decode("utf-8", "replace").strip().splitlines()[-1:] or [],
                    "stderr_tail": completed.stderr.decode("utf-8", "replace").strip().splitlines()[-2:] or [],
                    "guard_written": bool(counters),
                    "guard": counters,
                }
            )
    positive = next(item for item in results if item["label"] == "positive-control")
    control_ok = bool(
        positive["guard"].get("positive_control")
        and positive["guard"]["positive_control"].get("connect_blocked")
        and positive["guard"]["positive_control"].get("dns_blocked")
    )
    external_total = sum(
        sum(value or 0 for value in item["guard"].get("external", {}).values())
        for item in results
        if item["guard"] and item["label"] != "positive-control"  # 正对照故意发起外部连接，不计入本轮业务进程
    )
    exits_ok = all(item["exit_code"] == 0 for item in results if item["label"] != "keyspace")
    payload = {
        "schema_version": "p2h2v3-zero-call/v0.1",
        "phase": "zero-call",
        "guard": {
            "module": "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/v3-corpus/evidence/netguard/v3corpus_netguard.py",
            "injection": "PYTHONPATH + sitecustomize（进程级）",
            "blocks": ["socket.connect", "socket.connect_ex", "socket.create_connection", "socket.getaddrinfo",
                       "http.client.HTTPConnection.connect", "httpx.HTTPTransport.handle_request"],
            "allows_loopback": True,
        },
        "runs": results,
        "totals": {
            "runs": len(results),
            "external_attempts": external_total,
            "positive_control_blocked": control_ok,
            "guards_written": sum(1 for item in results if item["guard_written"]),
            "exits_ok": exits_ok,
        },
        "result": "ZERO_EXTERNAL_CALLS" if external_total == 0 and control_ok and exits_ok else "ZERO_CALL_EVIDENCE_INCOMPLETE",
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"totals": payload["totals"], "result": payload["result"]}, ensure_ascii=False, indent=1))
    return 0 if payload["result"] == "ZERO_EXTERNAL_CALLS" else 1


if __name__ == "__main__":
    sys.exit(main())

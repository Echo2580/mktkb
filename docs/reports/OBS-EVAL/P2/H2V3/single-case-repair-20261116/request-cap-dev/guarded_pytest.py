"""Run pytest with all socket traffic and dotenv loading prohibited."""
import os
import socket
import sys
import threading
import faulthandler
import urllib.request

for key in ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy", "ALL_PROXY",
            "all_proxy", "NO_PROXY", "no_proxy", "NODE_USE_ENV_PROXY", "node_use_env_proxy"):
    os.environ.pop(key, None)
os.environ["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
attempts = []
real_connect = socket.socket.connect
real_socketpair = socket.socketpair
local = threading.local()

def blocked(*args, **kwargs):
    if getattr(local, "socketpair", False) and args and isinstance(args[0], socket.socket):
        return real_connect(*args, **kwargs)
    attempts.append("blocked")
    raise OSError("network blocked by request-cap test guard")

def guarded_socketpair(*args, **kwargs):
    local.socketpair = True
    try:
        return real_socketpair(*args, **kwargs)
    finally:
        local.socketpair = False

socket.socket.connect = blocked
socket.socket.connect_ex = blocked
socket.create_connection = blocked
socket.getaddrinfo = blocked
socket.socketpair = guarded_socketpair

import dotenv
def no_dotenv(*args, **kwargs):
    raise RuntimeError("dotenv loading forbidden by request-cap test guard")
dotenv.load_dotenv = no_dotenv
dotenv.dotenv_values = no_dotenv
dotenv.find_dotenv = no_dotenv

import httpx
for probe in (
    lambda: socket.create_connection(("127.0.0.1", 1)),
    lambda: urllib.request.build_opener(urllib.request.ProxyHandler({})).open("http://127.0.0.1:1", timeout=1),
    lambda: httpx.Client(trust_env=False).get("http://127.0.0.1:1", timeout=1),
):
    try:
        probe()
    except Exception:
        pass
assert len(attempts) >= 3, "network guard canary failed"
print("GUARD: local socket/urllib/httpx probes blocked; proxies cleared; dotenv forbidden", flush=True)
attempts.clear()
import pytest
faulthandler.dump_traceback_later(15, repeat=False)
code = pytest.main(sys.argv[1:])
faulthandler.cancel_dump_traceback_later()
print(f"GUARD: test network attempts={len(attempts)}; real outbound=0", flush=True)
if attempts:
    code = 1
raise SystemExit(code)

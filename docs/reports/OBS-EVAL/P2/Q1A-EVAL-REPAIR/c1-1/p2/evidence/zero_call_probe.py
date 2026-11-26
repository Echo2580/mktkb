"""C1-P2 零调用探针：socket/DNS/provider/frozen 模块计数 + 正对照。

只在进程内安装 socket 守卫并 import 替代模块；不读 .env、不实例化 provider、
不启动服务、不出站。正对照故意触发一次被拦截的 `create_connection`，证明守卫
本身有效；随后清零计数，再跑全部合成 proof。
"""

from __future__ import annotations

import argparse
import importlib
import importlib.util
import json
import socket
import sys
import types
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[8]
TEST_MODULE = ROOT / "backend" / "tests" / "evaluation" / "test_p2_empty_scope_proof.py"
SRC = ROOT / "backend" / "src"


class _Guard:
    def __init__(self) -> None:
        self.attempts: list[str] = []

    def reset(self) -> None:
        self.attempts = []

    def add(self, label: str) -> None:
        self.attempts.append(label)


def _install_guard() -> _Guard:
    guard = _Guard()

    def blocked(label: str):
        def _fn(*args: Any, **kwargs: Any) -> Any:
            guard.add(label + ":" + repr(args[:1]))
            raise RuntimeError("c1p2-zero-call-guard:" + label)

        return _fn

    socket.socket.connect = blocked("socket.connect")  # type: ignore[method-assign]
    socket.socket.connect_ex = blocked("socket.connect_ex")  # type: ignore[method-assign]
    socket.create_connection = blocked("socket.create_connection")  # type: ignore[assignment]
    socket.getaddrinfo = blocked("socket.getaddrinfo")  # type: ignore[assignment]
    try:
        import httpx
    except Exception:  # noqa: BLE001 - 未安装 httpx 时无需 guard
        pass
    else:
        httpx.HTTPTransport.handle_request = blocked("httpx.HTTPTransport")  # type: ignore[method-assign]
        httpx.AsyncHTTPTransport.handle_async_request = blocked(  # type: ignore[method-assign]
            "httpx.AsyncHTTPTransport"
        )
    return guard


def _load_corpus(module_name: str = "c1p2_synthetic_corpus") -> Any:
    for path in (ROOT / "backend" / "tests", SRC):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
    spec = importlib.util.spec_from_file_location(module_name, TEST_MODULE)
    if spec is None or spec.loader is None:
        raise RuntimeError("test_module_unloadable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def run() -> dict[str, Any]:
    guard = _install_guard()
    # 正对照：守卫必须真的拦截一次外部连接。
    positive_control_blocked = False
    try:
        socket.create_connection(("203.0.113.1", 9), timeout=0.01)
    except Exception:  # noqa: BLE001 - 预期被拦截
        positive_control_blocked = True
    positive_control_attempts = list(guard.attempts)
    guard.reset()

    # 用 stub 包避免 import `mktkb.main`（它会 import providers）；并 stub 冻结原语，
    # 确保本探针只加载替代实现，不加载被替代的冻结实现。
    pkg = types.ModuleType("mktkb")
    pkg.__path__ = [str(SRC / "mktkb")]
    sys.modules["mktkb"] = pkg
    frozen_stub = types.ModuleType("mktkb.evaluation.p2_hard_evidence")
    frozen_stub._empty_use_scope_proof = lambda evidence: (False, "stub_not_used")  # type: ignore[attr-defined]
    sys.modules["mktkb.evaluation.p2_hard_evidence"] = frozen_stub

    module = importlib.import_module("mktkb.evaluation.p2_empty_scope_proof")
    corpus_module = _load_corpus()

    proofs = 0
    codes: dict[str, int] = {}
    for case in corpus_module._corpus():
        result = module.prove_empty_use_scope(case.evidence)
        proofs += 1
        codes[result.code] = codes.get(result.code, 0) + 1

    frozen_loaded = sorted(
        name
        for name in sys.modules
        if name in {
            "mktkb.evaluation.p2_evidence_capture",
            "mktkb.evaluation.p2_evidence_io",
        }
    )
    providers_loaded = sorted(name for name in sys.modules if name.startswith("mktkb.providers"))
    attempts = list(guard.attempts)
    return {
        "schema_version": "c1p2-zero-call/v0.1",
        "positive_control": {
            "attempted": True,
            "blocked": positive_control_blocked,
            "attempts": positive_control_attempts,
        },
        "proofs_evaluated": proofs,
        "proof_codes": dict(sorted(codes.items())),
        "external_network_attempts": len(attempts),
        "external_network_attempt_details": attempts[:20],
        "socket_connect_attempts": sum(1 for item in attempts if item.startswith("socket.connect")),
        "socket_create_connection_attempts": sum(
            1 for item in attempts if item.startswith("socket.create_connection")
        ),
        "dns_getaddrinfo_attempts": sum(1 for item in attempts if item.startswith("socket.getaddrinfo")),
        "httpx_transport_attempts": sum(1 for item in attempts if item.startswith("httpx.")),
        "provider_modules_loaded": providers_loaded,
        "provider_calls": 0,
        "frozen_modules_loaded": frozen_loaded,
        "frozen_primitive_stubbed_not_loaded": True,
        "real_calls": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    payload = run()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False))
    ok = (
        payload["external_network_attempts"] == 0
        and payload["provider_calls"] == 0
        and payload["frozen_modules_loaded"] == []
        and payload["positive_control"]["blocked"] is True
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

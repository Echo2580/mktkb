"""探针 15a：netguard 正向控制 / 负向控制 / 零外部调用（pytest 文件）。

- test_positive_control_*：证明闸门真的拦截外部 connect / getaddrinfo / httpx，并且记账；
  断言后清空 external 记账，让 teardown 断言可通过（证明“拦截生效”而非“空跑”）。
- test_zero_external_calls_*：三轴重评分 + 适配层在闸门下运行，external 必须为 0。
- test_plain_pass：无网络测试必须正常通过（证明闸门不是把所有测试都判失败）。
"""

from __future__ import annotations

import json
import socket
import sys
from pathlib import Path

import httpx
import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[6]
sys.path.insert(0, str(ROOT / "backend" / "src"))
sys.path.insert(0, str(ROOT / "backend" / "tests"))
sys.path.insert(0, str(HERE))

from acceptance.support.netguard import NetworkBlocked, t09_network_guard  # noqa: E402,F401

from _common import (  # noqa: E402
    annotation,
    axes,
    case,
    cross_entity_contract,
    cross_entity_view,
    cross_user_view,
    lifecycle,
    old_card,
    rescore,
    ref,
    scope_target,
    stale_source_contract,
    stale_source_view,
    unit,
    version_binding,
)

pytestmark = pytest.mark.usefixtures("t09_network_guard")


def test_positive_control_blocks_external_targets(t09_network_guard) -> None:  # noqa: ANN001
    attempts = t09_network_guard
    assert attempts.snapshot()["external"] == []
    blocked: list[dict[str, str]] = []

    def attempt(label: str, fn) -> None:  # noqa: ANN001
        try:
            fn()
        except (NetworkBlocked, OSError, httpx.HTTPError) as exc:
            blocked.append({"label": label, "error": type(exc).__name__, "message": str(exc)[:120]})
        else:
            blocked.append({"label": label, "error": "NOT-BLOCKED", "message": ""})

    attempt("create_connection", lambda: socket.create_connection(("203.0.113.7", 80), timeout=1))
    sock = socket.socket()
    try:
        attempt("socket.connect", lambda: sock.connect(("example.com", 443)))
    finally:
        sock.close()
    attempt("getaddrinfo", lambda: socket.getaddrinfo("example.com", 443))
    client = httpx.Client(trust_env=False)
    try:
        attempt("httpx.get", lambda: client.get("http://example.com/", timeout=1))
    finally:
        client.close()

    external = attempts.snapshot()["external"]
    assert all(item["error"] != "NOT-BLOCKED" for item in blocked), blocked
    assert len(external) >= 4, external

    (HERE / "15-positive-control.json").write_text(
        json.dumps({"blocked": blocked, "external_attempts": external}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    # 清空记账：正向控制已证明拦截+记账生效；teardown 断言此时应通过
    attempts.external.clear()
    attempts.local.clear()


def test_zero_external_calls_during_axes_rescore(t09_network_guard) -> None:  # noqa: ANN001
    identity = axes.AxesIdentity(
        base=rescore.RescoreIdentity(
            old_run_id="OLD-RUN-SYN",
            old_binding={"run_id": "SYN-RUN-Q1A1B", "plan_id": "SYN-PLAN-Q1A1B", "plan_sha256": "c" * 64},
            old_binding_sha256="b" * 64,
            old_evidence_tree_sha256="e" * 64,
            old_card_sha256="f" * 64,
            contract_sha256=rescore.file_sha256(axes.DEFAULT_CONTRACT_PATH),
            evaluator_sha256=rescore.file_sha256(axes.__file__),
        ),
        base_contract_sha256=rescore.file_sha256(axes.BASE_CONTRACT_PATH),
    )
    view = case(
        case_id="SYN-NET-1",
        anns={
            "cross_user": annotation("cross_user"),
            "cross_entity": annotation("cross_entity"),
            "stale_source": annotation("stale_source"),
        },
        cross_user=cross_user_view(),
        cross_entity=cross_entity_view(
            units=(unit("u1"),), unit_entity={"u1": axes.EntityIdentityView("item", "K1")}
        ),
        cross_entity_contract=cross_entity_contract(targets=(scope_target("item", "K1"),)),
        stale_source=stale_source_view(
            units=(unit("u1"),), lifecycle_map={"u1": lifecycle()}, actual_as_of="2026-10-28"
        ),
        stale_source_contract=stale_source_contract(
            constrained_refs=(ref(),), version_bindings={rescore.ref_key(ref()): version_binding()}
        ),
    )
    report = axes.rescore_axes_run(identity=identity, cases=(view,), allow_synthetic_fixture=True)
    assert dict(report.calls) == {"network": 0, "provider": 0, "model": 0, "retrieval": 0, "real": 0}
    assert t09_network_guard.snapshot()["external"] == []


def test_plain_pass_without_network() -> None:
    assert 1 + 1 == 2


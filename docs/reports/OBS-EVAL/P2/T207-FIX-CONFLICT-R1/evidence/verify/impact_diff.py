"""独立验收脚本（T207-FIX-CONFLICT-R1）：54 例逐题差分。

用法：
  .venv/Scripts/python.exe <本文件> --src=<产品源码根> --out=<json>

- 装配与出题沿用上一轮验收的 impact_diff 口径（B0：D01–D10 + V03 历史版本；C05/C06 独立快照）。
- 模型/OCR 为受控替身，且本脚本在导入 mktkb 前锁死 AF_INET/AF_INET6 连接（零真实出站）。
- 输出每题 kind/text/sources/conflicts/candidates/status/strict_status/problems，供逐题差分。
"""

from __future__ import annotations

import argparse
import json
import socket
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[7]

# ---- 零出站硬锁：只放行 AF_UNIX 与 loopback（Windows asyncio 自管道走 127.0.0.1），
# 其余 connect 一律失败并记账 ----
_real_connect = socket.socket.connect
_real_connect_ex = socket.socket.connect_ex
BLOCKED: list[str] = []
LOOPBACK: list[str] = []


def _is_loopback(address) -> bool:
    if not isinstance(address, tuple) or not address:
        return False
    host = str(address[0])
    return host in {"127.0.0.1", "::1", "localhost"} or host.startswith("127.")


def _guard(self, address):
    if self.family in (socket.AF_INET, socket.AF_INET6):
        if not _is_loopback(address):
            BLOCKED.append(repr(address))
            raise AssertionError(f"BLOCKED-OUTBOUND {address!r}")
        LOOPBACK.append(repr(address))
    return _real_connect(self, address)


def _guard_ex(self, address):
    if self.family in (socket.AF_INET, socket.AF_INET6):
        if not _is_loopback(address):
            BLOCKED.append(repr(address))
            raise AssertionError(f"BLOCKED-OUTBOUND {address!r}")
        LOOPBACK.append(repr(address))
    return _real_connect_ex(self, address)


socket.socket.connect = _guard
socket.socket.connect_ex = _guard_ex
_orig_create_connection = socket.create_connection


def _blocked_create_connection(address, *args, **kwargs):
    if _is_loopback(address):
        LOOPBACK.append(repr(address))
        return _orig_create_connection(address, *args, **kwargs)
    BLOCKED.append(repr(address))
    raise AssertionError(f"BLOCKED-OUTBOUND {address!r}")


socket.create_connection = _blocked_create_connection

parser = argparse.ArgumentParser()
parser.add_argument("--src", default=str(ROOT / "backend" / "src"))
parser.add_argument("--out", required=True)
args = parser.parse_args()
sys.path.insert(0, str(ROOT / "backend" / "tests" / "acceptance"))
sys.path.insert(0, str(ROOT / "backend" / "tests"))
sys.path.insert(0, str(Path(args.src)))

from support import b0  # noqa: E402
import mktkb  # noqa: E402

assert Path(mktkb.__file__).resolve().is_relative_to(Path(args.src).resolve()), (
    mktkb.__file__,
    args.src,
)

FORBID_PHRASES = {"N08": ("照片中", "已定位", "未标记物品位于")}
CLEAN_KINDS = {"answer", "not_found", "clarification", "knowledge_changed"}


def record_of(item, response, environment) -> dict:
    graded = b0.evaluate(
        item,
        response,
        environment=environment,
        forbid_phrases=FORBID_PHRASES.get(item["id"], ()),
    )
    actual = graded.get("actual") or {}
    return {
        "id": item["id"],
        "group": item["group"],
        "question": item["question"],
        "expected_kind": (item.get("scenario") or {}).get("expected_kind"),
        "kind": actual.get("kind"),
        "text": actual.get("text"),
        "sources": graded.get("source") or [],
        "conflicts": [
            {"field": entry.get("field"), "values": [unit.get("value") for unit in entry.get("entries") or []]}
            for entry in actual.get("conflicts") or []
        ],
        "candidates": actual.get("candidates") or [],
        "status": graded.get("status"),
        "strict_status": graded.get("strict_status"),
        "problems": graded.get("problems") or [],
    }


def conflict_case(snapshot: Path, work: Path, item, variant: str, environment) -> dict:
    harness = b0.restore_b0(snapshot, work)
    try:
        admin = harness.admin()
        receipt = admin.upload(path=b0.fixture_path(variant), allow_same_name=False)
        record = receipt.json()
        harness.ocr.unbind()
        result = harness.run_job()
        assert result.state == "succeeded", result
        detail = harness.detail(record["document"]["id"])
        active = detail["document"]["active_version"]
        published = admin.client.post(
            f"/api/v1/documents/{record['document']['id']}/versions/{record['version']['id']}/publish",
            json={
                "expected_active_version_id": active["id"] if active else None,
                "expected_revision": detail["revision"],
            },
            headers=admin.headers,
        )
        assert published.status_code == 200, published.text
        employee = harness.employee()
        conversation = b0.new_conversation(employee, f"T207-{item['id']}")
        response = b0.ask(employee, conversation, item["question"])
        return record_of(item, response, environment)
    finally:
        harness.close()


def main() -> int:
    environment = {"layer": "L", "provider": "T207-FIX-CONFLICT-R1 offline harness"}
    questions = b0.QUESTIONS
    out: list[dict] = []
    work = Path(tempfile.mkdtemp(prefix="t207r1-impact-"))
    live = b0.build_b0(work / "build")
    snapshot = b0.snapshot_b0(work / "build", work / "snapshot")
    try:
        employee = live.harness.employee()
        for item in questions:
            if item["group"] not in ("normal", "negative", "ambiguity_conflict"):
                continue
            scenario = item.get("scenario") or {}
            if scenario.get("expected_kind") == "conflict":
                continue
            if scenario.get("expected_kind") not in CLEAN_KINDS:
                continue
            conversation = b0.new_conversation(employee, f"T207-{item['id']}")
            response = b0.ask(employee, conversation, item["question"])
            out.append(record_of(item, response, environment))
    finally:
        live.harness.close()
    variants = {"C05": "V01", "C06": "V02"}
    for item in questions:
        variant = variants.get(item["id"])
        if variant is None:
            continue
        out.append(
            conflict_case(snapshot, work / f"conflict-{item['id']}", item, variant, environment)
        )
    Path(args.out).write_text(
        json.dumps(
            {
                "src": str(Path(args.src).resolve()),
                "mktkb_file": str(Path(mktkb.__file__).resolve()),
                "outbound_guard": "non-loopback AF_INET/AF_INET6 connect blocked",
                "blocked_attempts": BLOCKED,
                "loopback_connects": len(LOOPBACK),
                "cases": out,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"cases={len(out)} -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

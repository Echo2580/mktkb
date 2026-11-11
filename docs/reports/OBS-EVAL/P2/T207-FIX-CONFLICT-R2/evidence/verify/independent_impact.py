"""P2-T207-FIX-CONFLICT-R2 独立验收：54 例（Q01-Q40 / N01-N08 / C01-C06）前后差分。

独立验收助手编写：B0 装配/快照/恢复与逐题判分复用仓库既有验收夹具 support.b0
（冻结题集 + 产品 HTTP 入口），但驱动、记录与差分口径由本脚本自己实现：
- 50 例（Q/N/C01-C04）在 B0 上逐题提问；
- C05/C06 各自从 B0 快照恢复后发布 V01/V02 再提问（与 R4 灌库同样的"冲突终态"）；
- 记录 kind/text/sources/conflicts/candidates 与验收 status/strict_status/problems；
- 全程装 socket 外呼闸门（非回环即拦并记账），结束时 external 必须为空。

用法（仓库根，零真实调用）：
  .venv/Scripts/python.exe -B -X utf8 <本文件> --src=<源码根> --out=<json>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import sys
import tempfile
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--src", required=True)
parser.add_argument("--out", required=True)
args = parser.parse_args()


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "fixtures" / "acceptance").is_dir() and (parent / "backend").is_dir():
            return parent
    raise SystemExit("repo root not found")


REPO = _repo_root()
SRC = Path(args.src).resolve()
sys.path.insert(0, str(REPO / "backend" / "tests" / "acceptance"))
sys.path.insert(0, str(REPO / "backend" / "tests"))
sys.path.insert(0, str(SRC))
os.chdir(REPO)

import mktkb  # noqa: E402
import mktkb.copy as copy_module  # noqa: E402
from acceptance.support.netguard import is_loopback  # noqa: E402
from support import b0  # noqa: E402

IDS = [f"Q{index:02d}" for index in range(1, 41)] + [f"N{index:02d}" for index in range(1, 9)] + [
    f"C{index:02d}" for index in range(1, 7)
]
CONFLICT_VARIANTS = {"C05": "V01", "C06": "V02"}
FORBID_PHRASES = {"N08": ("照片中", "已定位", "未标记物品位于")}
ENVIRONMENT = {"layer": "L", "provider": "P2-T207-FIX-CONFLICT-R2 independent verify"}

EXTERNAL_ATTEMPTS: list[str] = []


def _install_network_guard() -> None:
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex
    real_create_connection = socket.create_connection

    def guarded_connect(self, address, *a, **kw):
        if not is_loopback(address):
            EXTERNAL_ATTEMPTS.append(f"socket.connect {address!r}")
            raise RuntimeError(f"independent-verify 网络闸门：拒绝出站 {address!r}")
        return real_connect(self, address, *a, **kw)

    def guarded_connect_ex(self, address, *a, **kw):
        if not is_loopback(address):
            EXTERNAL_ATTEMPTS.append(f"socket.connect_ex {address!r}")
            raise RuntimeError(f"independent-verify 网络闸门：拒绝出站 {address!r}")
        return real_connect_ex(self, address, *a, **kw)

    def guarded_create_connection(address, *a, **kw):
        if not is_loopback(address):
            EXTERNAL_ATTEMPTS.append(f"socket.create_connection {address!r}")
            raise RuntimeError(f"independent-verify 网络闸门：拒绝出站 {address!r}")
        return real_create_connection(address, *a, **kw)

    socket.socket.connect = guarded_connect
    socket.socket.connect_ex = guarded_connect_ex
    socket.create_connection = guarded_create_connection


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _record(item: dict, response) -> dict:
    graded = b0.evaluate(
        item,
        response,
        environment=ENVIRONMENT,
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
        "text_sha256": _sha(str(actual.get("text") or "")),
        "sources": [
            {
                "document_name": source.get("document_name"),
                "version_number": source.get("version_number"),
                "status": source.get("status"),
                "locator": source.get("locator"),
            }
            for source in actual.get("sources") or ()
        ],
        "conflicts": [
            {
                "field": entry.get("field"),
                "entries": [
                    {"value": sub.get("value"), "source_id": sub.get("source_id")}
                    for sub in entry.get("entries") or ()
                ],
            }
            for entry in actual.get("conflicts") or ()
        ],
        "candidates": actual.get("candidates") or [],
        "status": graded.get("status"),
        "strict_status": graded.get("strict_status"),
        "problems": graded.get("problems") or [],
        "strict_problems": graded.get("strict_problems") or [],
    }


def _ask(employee, case_id: str, question: str) -> dict:
    conversation = b0.new_conversation(employee, f"R2V-{case_id}")
    return b0.ask(employee, conversation, question)


def run() -> dict:
    questions = {item["id"]: item for item in b0.QUESTIONS}
    missing = [case_id for case_id in IDS if case_id not in questions]
    if missing:
        raise SystemExit(f"questions missing: {missing}")

    work = Path(tempfile.mkdtemp(prefix="p2-r2-impact-"))
    records: list[dict] = []
    build = b0.build_b0(work / "build")
    snapshot = b0.snapshot_b0(work / "build", work / "snapshot")
    try:
        employee = build.harness.employee()
        for case_id in IDS:
            item = questions[case_id]
            if case_id in CONFLICT_VARIANTS:
                continue
            records.append(_record(item, _ask(employee, case_id, item["question"])))
    finally:
        build.harness.close()

    for case_id, variant in CONFLICT_VARIANTS.items():
        item = questions[case_id]
        harness = b0.restore_b0(snapshot, work / f"conflict-{case_id}")
        try:
            admin = harness.admin()
            receipt = admin.upload(path=b0.fixture_path(variant), allow_same_name=False)
            if receipt.status_code != 202:
                raise SystemExit(f"{case_id}: upload {variant} -> {receipt.status_code} {receipt.text[:300]}")
            record = receipt.json()
            harness.ocr.unbind()
            result = harness.run_job()
            if result.state != "succeeded":
                raise SystemExit(f"{case_id}: ingest job state={result.state}")
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
            if published.status_code != 200:
                raise SystemExit(f"{case_id}: publish -> {published.status_code} {published.text[:300]}")
            employee = harness.employee()
            records.append(_record(item, _ask(employee, case_id, item["question"])))
        finally:
            harness.close()

    records.sort(key=lambda row: row["id"])
    return {
        "src": str(SRC),
        "loaded": {"mktkb": str(Path(mktkb.__file__).resolve()), "copy": str(Path(copy_module.__file__).resolve())},
        "variant_probe": copy_module.legacy_conflict_text("X"),
        "case_count": len(records),
        "external_attempts": list(EXTERNAL_ATTEMPTS),
        "cases": records,
    }


if __name__ == "__main__":
    _install_network_guard()
    payload = run()
    Path(args.out).write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print("ok ->", args.out, "cases:", payload["case_count"], "external:", len(payload["external_attempts"]))

"""T207-FIX-CONFLICT 影响面差分：同一批公开 case 在"修复前/后"的产品行为逐题对照。

用法：
  .venv/Scripts/python.exe docs/reports/OBS-EVAL/P2/T207-FIX-CONFLICT/evidence/impact_diff.py --src=<产品源码根> --out=<json>

- 装配走 acceptance 的 B0 配方（D01–D10 + V03 历史版本），模型/OCR 为受控替身（零真实调用）；
- B0 常态跑 Q01–Q40 / N01–N08 / C01–C04；C05/C06 各自恢复 B0 快照后发布 V01/V02；
- 输出每题的 kind / 文本 / 来源 / 冲突值 / 候选 / 判分结果，供逐题差分。
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[6]
parser = argparse.ArgumentParser()
parser.add_argument("--src", default=str(ROOT / "backend" / "src"))
parser.add_argument("--out", required=True)
args = parser.parse_args()
sys.path.insert(0, str(ROOT / "backend" / "tests" / "acceptance"))
sys.path.insert(0, str(ROOT / "backend" / "tests"))
sys.path.insert(0, str(Path(args.src)))

from support import b0  # noqa: E402

FORBID_PHRASES = {"N08": ("照片中", "已定位", "未标记物品位于")}
CLEAN_KINDS = {"answer", "not_found", "clarification", "knowledge_changed"}


def record_of(item, response, environment) -> dict:
    graded = b0.evaluate(
        item,
        response,
        environment=environment,
        forbid_phrases=FORBID_PHRASES.get(item["id"], ()),
    )
    return {
        "id": item["id"],
        "group": item["group"],
        "question": item["question"],
        "expected_kind": (item.get("scenario") or {}).get("expected_kind"),
        "kind": (graded.get("actual") or {}).get("kind"),
        "text": (graded.get("actual") or {}).get("text"),
        "sources": graded.get("source") or [],
        "conflicts": [
            {"field": entry.get("field"), "values": [item_.get("value") for item_ in entry.get("entries") or []]}
            for entry in (graded.get("actual") or {}).get("conflicts") or []
        ],
        "candidates": (graded.get("actual") or {}).get("candidates") or [],
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
    environment = {"layer": "L", "provider": "T207-FIX-CONFLICT offline harness"}
    questions = b0.QUESTIONS
    out: list[dict] = []
    work = Path(tempfile.mkdtemp(prefix="t207-impact-"))
    if True:
        live = b0.build_b0(work / "build")
        snapshot = b0.snapshot_b0(work / "build", work / "snapshot")
        try:
            employee = live.harness.employee()
            for item in questions:
                if item["group"] not in ("normal", "negative", "ambiguity_conflict"):
                    continue  # mutation 题需要先执行变更动作，不在本次常态差分范围内
                scenario = item.get("scenario") or {}
                if scenario.get("expected_kind") == "conflict":
                    continue  # C05/C06 用独立快照另行执行
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
                conflict_case(
                    snapshot,
                    work / f"conflict-{item['id']}",
                    item,
                    variant,
                    environment,
                )
            )
    Path(args.out).write_text(
        json.dumps({"src": str(args.src), "cases": out}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"cases={len(out)} -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

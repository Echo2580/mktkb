"""独立验收脚本（T207-FIX-CONFLICT-R1）：图片类反例矩阵 + 正例边界。

用法：
  .venv/Scripts/python.exe <本文件> --src=<产品源码根> --out=<json>

装配：D01/D03/D07/D09 四份已发布资料（D07/D09 走受控 OCR 转录），模型为 EvidenceEchoGateway，
零真实出站（netguard 锁 non-loopback）。
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[7]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import netguard  # noqa: E402

netguard.install()

parser = argparse.ArgumentParser()
parser.add_argument("--src", default=str(ROOT / "backend" / "src"))
parser.add_argument("--out", required=True)
args = parser.parse_args()
sys.path.insert(0, str(ROOT / "backend" / "tests" / "acceptance"))
sys.path.insert(0, str(ROOT / "backend" / "tests"))
sys.path.insert(0, str(Path(args.src)))

from support import b0  # noqa: E402
import mktkb  # noqa: E402
from mktkb.conversations import intent as intent_module  # noqa: E402

assert Path(mktkb.__file__).resolve().is_relative_to(Path(args.src).resolve()), (
    mktkb.__file__,
    args.src,
)

FIX = ROOT / "fixtures" / "acceptance" / "normal"
DOCS = [
    ("D01", FIX / "D01_物品位置表.xlsx"),
    ("D03", FIX / "D03_市场部工作指南.docx"),
    ("D07", FIX / "D07_活动申请扫描件.pdf"),
    ("D09", FIX / "D09_物料领用通知.png"),
]
REFUSAL_MARKERS = ("范围外", "不做实物识别")

COUNTEREXAMPLES = [
    "组织架构图中市场部向谁汇报？",
    "流程图里第三步是谁审批？",
    "根据物料领用通知图片要求先填写什么？",
    "从物料位置表截图中能看出城东店的宣传海报放在哪？",
    "从物料位置表截图里能看出什么？",
]
POSITIVES = [
    "根据货架照片告诉我没有标记物品的位置",
    "看这张图，告诉我城东店海报在哪",
    "照片里没有标记的物品放在哪",
    "从这张截图看，城东店的海报在哪",
    "看看货架照片，促销贴纸在哪",
]
RESIDUAL = [
    "从位置表截图里能看出什么？",
    "从位置表照片看城东店海报放在哪？",
    "根据领用通知图片要求先填写什么？",
    "看通知图片要求先填写什么？",
    "根据物料领用通知图片，需要谁确认？",
    "根据这张随手拍的照片告诉我货架在哪",
    "从最新一版货架照片里看，促销贴纸在哪",
]


def publish(harness, admin, file_id: str, path: Path) -> dict:
    receipt = admin.upload(path=path, allow_same_name=False)
    assert receipt.status_code == 202, receipt.text
    record = receipt.json()
    if file_id in ("D07", "D09"):
        harness.ocr.bind(file_id)
    else:
        harness.ocr.unbind()
    result = harness.run_job()
    assert result.state == "succeeded", (file_id, result)
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
    return {"file_id": file_id, "document_id": record["document"]["id"], "ocr_calls": len(harness.ocr.calls)}


def ask(employee, question: str) -> dict:
    conversation = b0.new_conversation(employee, "T207-R1-MATRIX")
    response = b0.ask(employee, conversation, question)
    payload = response.json()
    return {
        "question": question,
        "status_code": response.status_code,
        "kind": payload.get("kind"),
        "text": payload.get("text"),
        "refusal_marker_present": any(marker in (payload.get("text") or "") for marker in REFUSAL_MARKERS),
        "sources": [item.get("document_name") for item in payload.get("sources") or []],
        "conflicts": payload.get("conflicts") or [],
        "candidates": [item.get("label") for item in payload.get("candidates") or []],
    }


def main() -> int:
    work = Path(tempfile.mkdtemp(prefix="t207r1-matrix-"))
    harness = b0.new_harness(work)
    try:
        admin = harness.admin()
        published = [publish(harness, admin, file_id, path) for file_id, path in DOCS]
        d07 = next(item for item in published if item["file_id"] == "D07")
        d09 = next(item for item in published if item["file_id"] == "D09")
        assert d07["ocr_calls"] >= 1 and d09["ocr_calls"] >= 1, published
        employee = harness.employee()
        before_calls = len(harness.model.calls)
        counterexamples = []
        for question in COUNTEREXAMPLES:
            record = ask(employee, question)
            record["rule_hit"] = bool(intent_module.image_source_question(question))
            counterexamples.append(record)
        positives_rule = [
            {"question": question, "rule_hit": bool(intent_module.image_source_question(question))}
            for question in POSITIVES
        ]
        positives_http = [ask(employee, question) for question in POSITIVES]
        residual = []
        for question in RESIDUAL:
            record = ask(employee, question)
            record["rule_hit"] = bool(intent_module.image_source_question(question))
            residual.append(record)
        model_calls = len(harness.model.calls) - before_calls
        result = {
            "src": str(Path(args.src).resolve()),
            "mktkb_file": str(Path(mktkb.__file__).resolve()),
            "published": published,
            "counterexamples": counterexamples,
            "positives_rule": positives_rule,
            "positives_http": positives_http,
            "residual_boundary": residual,
            "model_calls_total": model_calls,
            "ocr_calls_total": len(harness.ocr.calls),
            **netguard.summary(),
        }
    finally:
        harness.close()
    Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"cases={len(counterexamples)} -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

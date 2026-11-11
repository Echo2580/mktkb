"""独立验收脚本（T207-FIX-CONFLICT-R1）：image_source_question 的判定边界探针。

只导入 intent 模块，不发请求。用于量化"≤4 字短修饰"启发式的残留误拒/漏拒面。
用法：<python> rule_boundary.py --src=<产品源码根> --out=<json>
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[7]
parser = argparse.ArgumentParser()
parser.add_argument("--src", default=str(ROOT / "backend" / "src"))
parser.add_argument("--out", required=True)
args = parser.parse_args()
sys.path.insert(0, str(Path(args.src)))

import mktkb  # noqa: E402
from mktkb.conversations import intent as intent_module  # noqa: E402

assert Path(mktkb.__file__).resolve().is_relative_to(Path(args.src).resolve()), mktkb.__file__

#: 语义上属于"以图片为事实来源"（应拒）——用于观察漏拒。
IMAGE_SOURCE = [
    "根据货架照片告诉我没有标记物品的位置",
    "看这张图，告诉我城东店海报在哪",
    "照片里没有标记的物品放在哪",
    "从这张截图看，城东店的海报在哪",
    "看看货架照片，促销贴纸在哪",
    "根据这张随手拍的照片告诉我货架在哪",
    "看一下这张物料位置表截图，城东店海报在哪",
    "从最新一版货架照片里看，促销贴纸在哪",
    "看这张仓库平面图照片，通道在哪",
    "根据领用通知图片要求先填写什么？",
]
#: 语义上属于"对已发布资料的提问"（不应拒）——用于观察误拒。
DOCUMENT_QUESTION = [
    "组织架构图中市场部向谁汇报？",
    "流程图里第三步是谁审批？",
    "根据物料领用通知图片要求先填写什么？",
    "根据物料领用通知图片，需要谁确认？",
    "从物料位置表截图中能看出城东店的宣传海报放在哪？",
    "从物料位置表截图里能看出什么？",
    "从位置表截图里能看出什么？",
    "从位置表照片看城东店海报放在哪？",
    "看通知图片要求先填写什么？",
    "看变更通知图片里的要求是什么？",
    "在物料位置表截图里，城东店海报放在哪？",
    "按仓库通知图片，物料领用要谁确认？",
    "根据最新的物料位置表截图，海报在哪？",
    "根据物品位置表图片，城东店海报在哪？",
    "从领用通知截图里能看出要谁确认？",
]
result = {
    "src": str(Path(args.src).resolve()),
    "mktkb_file": str(Path(mktkb.__file__).resolve()),
    "image_source": [
        {"question": q, "rule_hit": bool(intent_module.image_source_question(q))} for q in IMAGE_SOURCE
    ],
    "document_question": [
        {"question": q, "rule_hit": bool(intent_module.image_source_question(q))} for q in DOCUMENT_QUESTION
    ],
}
#: 汇总：误拒 = 资料题被判 True；漏拒 = 图片题被判 False
result["summary"] = {
    "image_source_missed": [r["question"] for r in result["image_source"] if not r["rule_hit"]],
    "document_question_false_reject": [r["question"] for r in result["document_question"] if r["rule_hit"]],
}
Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps(result["summary"], ensure_ascii=False, indent=1))

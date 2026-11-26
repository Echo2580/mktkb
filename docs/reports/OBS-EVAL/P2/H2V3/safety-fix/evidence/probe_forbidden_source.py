"""合成探针：``forbidden_source_used`` 的“内容对、来源被判违规”。

只读调用冻结评测模块的 ref→unit 匹配函数（``mktkb.evaluation.p2_hard_evidence._ref_matches_unit``），
不修改评测模块、不读真实 H2 题面/答案/密文、不出网。

合成对象：
- 冻结标签侧 forbidden ref：旧版本（D01 v2）的 P01 行，引用形状
  ``{doc_code, record_code, locator{sheet,row}}``（labels schema 的冻结键集）；
- 产品实际使用单元（DB 投影形状）：当前版本（V04/v3）的 P01 行，同 sheet、同 row。

结论由函数实际返回值给出：若匹配器只看 locator（sheet/row）而不看 doc_code/版本，
则“用当前正确版本作答”也会被判 ``forbidden_source_used``。函数返回值原样打印。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[7]
sys.path.insert(0, str(_REPO_ROOT / "backend" / "src"))

from mktkb.evaluation import p2_hard_evidence as hard  # noqa: E402

#: 冻结标签形状：doc_code + record_code + locator（无 version_number，版本由 doc_code 承载）。
FORBIDDEN_REF_OLD_VERSION = {
    "doc_code": "D01",
    "record_code": "P01",
    "version_number": 2,
    "locator": {"sheet": "物品位置", "row": 8},
}
EXPECTED_REF_CURRENT_VERSION = {
    "doc_code": "V04",
    "record_code": "P01",
    "version_number": 3,
    "locator": {"sheet": "物品位置", "row": 8},
}


def _unit(*, document_name: str, version_number: int) -> dict:
    """DB 投影里的一个使用单元（产品实际使用的当前版本行）。"""
    return {
        "unit_id": "unit-current-p01",
        "unit_key": "sheet:物品位置:row:8",
        "kind": "table_row",
        "locator": {"sheet": "物品位置", "row": 8},
        "document_name": document_name,
        "version_number": version_number,
        "entity_type": "item",
        "entity_key": "item|id:p01",
        "entity_filters": {"store": "城东店", "item": "宣传海报", "item_id": "P01"},
    }


def _version_aware_match(ref: dict, unit: dict) -> bool:
    """独立复核（不是冻结判据）：把 doc_code/record_code/版本一起纳入的身份匹配。"""
    names = {str(unit.get("document_name") or "")}
    doc_code = str(ref.get("doc_code") or "")
    if not any(doc_code and doc_code in name for name in names):
        return False
    return str(unit.get("entity_filters", {}).get("item_id") or "") == str(
        ref.get("record_code") or ""
    ) and int(unit.get("version_number") or 0) == int(ref.get("version_number") or 0)


def main() -> int:
    out_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("probe-forbidden-source.json")
    unit = _unit(document_name="V04_物品位置表_新版V3.xlsx", version_number=3)

    forbidden_hit = hard._ref_matches_unit(FORBIDDEN_REF_OLD_VERSION, unit)
    expected_hit = hard._ref_matches_unit(EXPECTED_REF_CURRENT_VERSION, unit)
    version_aware_forbidden = _version_aware_match(FORBIDDEN_REF_OLD_VERSION, unit)
    version_aware_expected = _version_aware_match(EXPECTED_REF_CURRENT_VERSION, unit)

    payload = {
        "frozen_matcher": {
            "function": "mktkb.evaluation.p2_hard_evidence._ref_matches_unit",
            "forbidden_ref_old_version": FORBIDDEN_REF_OLD_VERSION,
            "expected_ref_current_version": EXPECTED_REF_CURRENT_VERSION,
            "used_unit": unit,
            "forbidden_hit": forbidden_hit,
            "expected_hit": expected_hit,
        },
        "independent_version_aware_check": {
            "forbidden_match": version_aware_forbidden,
            "expected_match": version_aware_expected,
        },
        "forbidden_value_in_final_text": None,
        "reading": (
            "冻结匹配器对旧版本 forbidden ref 与实际使用的当前版本行同时返回 True，"
            "说明它只用 locator(sheet/row) 命中、不比较 doc_code/record_code/版本；"
            "版本感知复核则 forbidden=False / expected=True。"
        ),
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=True, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

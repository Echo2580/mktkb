from mktkb import copy as product_copy
from mktkb.conversations.service import _RAG_KIND_MAP
from mktkb.evaluation.p2_hard_evidence import REFUSAL_LIKE_KINDS


def test_product_refusal_maps_to_frozen_refusal_like_kind():
    assert _RAG_KIND_MAP["no_answer"] == "not_found"
    assert "not_found" in REFUSAL_LIKE_KINDS
    assert "answer" not in REFUSAL_LIKE_KINDS
    text = product_copy.text("SECURITY_RESTRICTED_CONTACT")
    assert "个人信息" in text
    assert "不是资料中没有答案" in text

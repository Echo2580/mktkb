"""必测 1：版本分派与 schema sha 绑定（v1 拒绝 / v2 不得被裸 v1 常量收下 / 逐字节钉扎）。"""

from __future__ import annotations

import ast
import copy
import hashlib
from pathlib import Path

from harness import Checks, code_of
import synth

from mktkb.evaluation import p2_evidence_axes_adapter_v2 as adapter
from mktkb.evaluation.p2_evidence_rescore_axes import (
    Q1A2_CONTRACT_SCHEMA_VERSION,
    load_q1a2_contract_view,
)

REPO = Path(__file__).resolve().parents[8]
ADAPTER = REPO / "backend/src/mktkb/evaluation/p2_evidence_axes_adapter_v2.py"
V1_SCHEMA_DOC = REPO / "docs/evaluation/q1a-scope-targets-contract-v1.md"
V2_SCHEMA_DOC = REPO / "docs/evaluation/q1a-scope-targets-contract-v2.md"


def v1_payload(case_count: int = 30) -> dict:
    """v1 形状：5 顶层键、schema v1；值用 v2 合成载荷的对应部分。"""
    payload = synth.contract()
    payload.pop("projection")
    payload["schema_version"] = synth.CONTRACT_SCHEMA_VERSION_V1
    return payload


def main() -> dict:
    checks = Checks("01-version-dispatch")
    v2 = synth.contract()

    # ---- 1) v2 适配器：v1 必被固定码拒绝 ---------------------------------- #
    checks.eq(
        "v1_minimal_payload_rejected_by_v2_adapter",
        code_of(lambda: adapter.load_contract_v2({"schema_version": synth.CONTRACT_SCHEMA_VERSION_V1})),
        "contract_version_v1_rejected_by_v2_adapter",
    )
    checks.eq(
        "v1_full_payload_rejected_by_v2_adapter",
        code_of(lambda: adapter.load_contract_v2(v1_payload())),
        "contract_version_v1_rejected_by_v2_adapter",
    )
    checks.eq(
        "unknown_contract_version_rejected",
        code_of(lambda: adapter.load_contract_v2({**copy.deepcopy(v2), "schema_version": "q1a-scope-targets-contract/v3"})),
        "contract_version_unsupported",
    )
    checks.eq(
        "missing_schema_version_is_contract_missing",
        code_of(lambda: adapter.load_contract_v2({"bindings": {}})),
        "contract_missing",
    )
    checks.eq(
        "missing_payload_is_contract_missing",
        code_of(lambda: adapter.load_contract_v2(None)),
        "contract_missing",
    )

    # ---- 2) v2 合同不得被“裸 v1 常量”的 v1 消费者收下 --------------------- #
    checks.eq(
        "v1_loader_rejects_v2_payload_with_projection",
        code_of(lambda: load_q1a2_contract_view(copy.deepcopy(v2))),
        "contract_schema_invalid",
    )
    without_projection = copy.deepcopy(v2)
    without_projection.pop("projection")
    checks.eq(
        "v1_loader_rejects_v2_payload_without_projection_by_version",
        code_of(lambda: load_q1a2_contract_view(without_projection)),
        "contract_schema_invalid",
    )
    renamed = copy.deepcopy(without_projection)
    renamed["schema_version"] = synth.CONTRACT_SCHEMA_VERSION_V1
    renamed_code = code_of(lambda: load_q1a2_contract_view(renamed))
    checks.eq(
        "v1_loader_only_gates_on_version_and_key_set_not_schema_sha",
        renamed_code,
        None,
        {
            "note": "v2 去掉 projection 并把版本改回 v1 后，旧 v1 消费者照收；旧校验器没有 schema sha 钉扎",
            "bindings_contract_schema_sha256": renamed["bindings"]["contract_schema_sha256"],
        },
    )
    checks.eq(
        "v2_adapter_still_rejects_the_same_renamed_payload",
        code_of(lambda: adapter.load_contract_v2(renamed)),
        "contract_version_v1_rejected_by_v2_adapter",
    )
    checks.eq(
        "v1_loader_accepts_genuine_v1_payload_baseline",
        code_of(lambda: load_q1a2_contract_view(v1_payload())),
        None,
    )
    checks.record(
        "v1_constant_is_not_widened",
        Q1A2_CONTRACT_SCHEMA_VERSION == synth.CONTRACT_SCHEMA_VERSION_V1 == "q1a-scope-targets-contract/v1",
        {"value": Q1A2_CONTRACT_SCHEMA_VERSION},
    )

    # ---- 3) schema sha 绑定 ------------------------------------------------ #
    checks.eq(
        "v1_schema_sha_bound_to_v2_version_rejected",
        code_of(lambda: adapter.load_contract_v2(synth.contract(schema_sha=synth.SCHEMA_V1_SHA))),
        "contract_schema_binding_mismatch",
    )
    arbitrary = "0" * 64
    checks.eq(
        "arbitrary_declared_schema_sha_rejected_by_default",
        code_of(lambda: adapter.load_contract_v2(synth.contract(schema_sha=arbitrary))),
        "contract_schema_binding_mismatch",
    )
    checks.eq(
        "expected_schema_sha_mismatch_rejected",
        code_of(lambda: adapter.load_contract_v2(v2, expected_schema_sha256="1" * 64)),
        "contract_schema_binding_mismatch",
    )
    checks.eq(
        "expected_schema_sha_equal_to_v1_rejected",
        code_of(lambda: adapter.load_contract_v2(synth.contract(schema_sha=synth.SCHEMA_V1_SHA), expected_schema_sha256=synth.SCHEMA_V1_SHA)),
        "contract_schema_binding_mismatch",
    )

    # 反例 A：调用方自带 expected 时，任意摘要可与载荷声明“同值”通过（声明层可放宽）。
    relaxed = synth.contract(schema_sha=arbitrary)
    accepted_relaxed = code_of(lambda: adapter.load_contract_v2(relaxed, expected_schema_sha256=arbitrary))
    checks.eq("caller_supplied_digest_relaxes_declared_pin", accepted_relaxed, None, {"sha": arbitrary})

    # 反例 B：改载荷里一个字节（目标键值），声明不变 -> 仍然通过（无载荷内容摘要）。
    mutated = synth.contract({0: synth.case_axes(cross_entity=synth.axis(
        "required", "structured_target", "explicit_single_target",
        targets=[synth.target("item", "item|storea|itema", {"store": "StoreA", "item": "ItemA"})],
    ))})
    mutated_one_byte = copy.deepcopy(mutated)
    mutated_one_byte["cases"][0]["axes"]["cross_entity"]["targets"][0]["entity_key"] = "item|storea|itemB"
    checks.eq(
        "one_byte_payload_change_is_not_detected",
        code_of(lambda: adapter.load_contract_v2(mutated_one_byte)),
        None,
        {"change": "item|storea|itema -> item|storea|itemB", "note": "声明层摘要不覆盖载荷内容"},
    )
    checks.record(
        "one_byte_change_does_change_semantics",
        adapter.load_contract_v2(mutated).cases["C00"].axes["cross_entity"].targets[0].entity_key
        != adapter.load_contract_v2(mutated_one_byte).cases["C00"].axes["cross_entity"].targets[0].entity_key,
    )

    # 反例 C：只改声明的摘要一个 hex -> 立即拒绝（钉的是字符串，不是内容）。
    one_hex = copy.deepcopy(v2)
    digest = one_hex["bindings"]["contract_schema_sha256"]
    one_hex["bindings"]["contract_schema_sha256"] = ("f" if digest[0] != "f" else "0") + digest[1:]
    checks.eq(
        "one_hex_declared_digest_change_is_rejected",
        code_of(lambda: adapter.load_contract_v2(one_hex)),
        "contract_schema_binding_mismatch",
    )

    # ---- 4) 常量与公开 schema 字节是否一致 -------------------------------- #
    v2_actual = hashlib.sha256(V2_SCHEMA_DOC.read_bytes()).hexdigest()
    v1_actual = hashlib.sha256(V1_SCHEMA_DOC.read_bytes()).hexdigest()
    checks.eq("v2_schema_constant_matches_public_file", v2_actual, synth.SCHEMA_V2_SHA)
    checks.eq("v1_schema_constant_matches_public_file", v1_actual, synth.SCHEMA_V1_SHA)
    checks.record(
        "v1_and_v2_schema_digests_differ",
        synth.SCHEMA_V1_SHA != synth.SCHEMA_V2_SHA,
    )

    # ---- 5) 模块是否具备“逐字节钉扎”的能力（静态） ------------------------ #
    tree = ast.parse(ADAPTER.read_text(encoding="utf-8"))
    file_calls: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = ""
            if isinstance(node.func, ast.Name):
                name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                name = node.func.attr
            if name in {"open", "read_bytes", "read_text", "Path", "resource_bytes", "files"}:
                file_calls.append(name)
    checks.eq("adapter_has_no_file_read_calls", sorted(set(file_calls)), [])
    source = ADAPTER.read_text(encoding="utf-8")
    checks.eq("adapter_does_not_reference_schema_path", "docs/evaluation" in source, False)

    # ---- 6) 走 determine_case 时也是固定码 + unknown（不抛裸异常） -------- #
    determination = adapter.determine_case(contract=v1_payload(), case_id="C00", snapshot=synth.snapshot())
    checks.eq("determine_case_v1_payload_state", determination.axes["cross_entity"].state, "unknown")
    checks.eq(
        "determine_case_v1_payload_reason",
        determination.axes["cross_entity"].reason,
        "contract_version_v1_rejected_by_v2_adapter",
    )
    checks.eq(
        "determine_case_v1_payload_other_axis_reason",
        determination.axes["stale_source"].reason,
        "contract_version_v1_rejected_by_v2_adapter",
    )

    return checks.write(
        {
            "constants": {
                "v1_schema_sha": synth.SCHEMA_V1_SHA,
                "v2_schema_sha": synth.SCHEMA_V2_SHA,
                "v1_constant": Q1A2_CONTRACT_SCHEMA_VERSION,
                "adapter_v1_constant": adapter.CONTRACT_SCHEMA_VERSION_V1,
                "adapter_v2_constant": adapter.CONTRACT_SCHEMA_VERSION_V2,
            },
            "files_hashed": [str(V1_SCHEMA_DOC.name), str(V2_SCHEMA_DOC.name)],
        }
    )


if __name__ == "__main__":
    main()

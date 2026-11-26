"""Q1a-3 新分析身份 Q1A-RESCORE-20261114-r1 的**字节实测**绑定（只读、零调用）。

- 全部值来自本次进程实测（`hashlib` 读字节），不采信任何声明值（R-04）。
- 本脚本不构造 `RescoreIdentity` 报告，也不写 `analysis_identity_sha256`：
  该摘要只能由 `rescore_run` / `rescore_axes_run` 在成功评分后签发；
  评分输入缺失时伪造一个"身份摘要"等于伪造结论，故只输出组件实测值 + 包级绑定摘要
  （明确标注为本包自定的 canonical 摘要，不是模块的 `analysis_identity_sha256`）。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

REPO = Path(r"D:\GPT项目\市场部AI知识库")
RUN_ROOT = Path(r"D:\mktkb-p2-t207-h2-20261114")
CONTRACT_CIPHER = Path(r"D:\mktkb-q1a2-scope-contract\scope-targets-contract-v1.fernet")
CONTRACT_SCHEMA = REPO / "docs" / "evaluation" / "q1a-scope-targets-contract-v1.md"

EXPECTED = {
    "old_run_binding_payload_sha256": "291cfec9d99446c88f0063d533c92632cef15594c1f6ce3da2269cef98ae65d4",
    "contract_ciphertext_sha256": "467dbf7706df26f2069a79e2b344b53c0e10c03ff830ed62efff9b5dfd16f461",
    "contract_schema_sha256": "cb1257fac56a68e5eef791c23cffba9d4e915e5e9a840abce7bde5b96e0e4690",
    "q1a1_module_sha256": "d8260256b4c3572f206a39f39dc8fe2847fa4946dc9b7bd05e93c5fd7841f3e9",
    "q1a1b_module_sha256": "57495943c763977e62fa7acded407e99ba360336fc5ee8c822f5e084f200f08e",
    "q1a1_contract_sha256": "e0487f256524558ae12b00e6a9d961a7360e92f1437ab4d7d0c55702f375588d",
    "q1a1b_contract_sha256": "747e3656bfbaf0bb4f0e40444d96d20d2b30806d80d061fbca13b962a46c8db5",
}


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical(payload) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def tree_digest(root: Path) -> dict:
    """沿用受控入口的 tree_digest 算法（`path:sha256` 换行拼接），与 seal-manifest 可比。"""
    import sys

    sys.path.insert(0, str(REPO / "tools"))
    import p2_h2_controlled_execute as entry

    return entry.tree_digest(root)


def main() -> int:
    measured: dict[str, object] = {}

    binding_path = RUN_ROOT / "plans2" / "run-binding.json"
    binding_raw = binding_path.read_bytes()
    binding_doc = json.loads(binding_raw.decode("utf-8"))
    payload = {k: v for k, v in binding_doc.items() if k != "binding_sha256"}
    measured["old_run_binding"] = {
        "path": str(binding_path),
        "file_sha256": sha(binding_raw),
        "file_bytes": len(binding_raw),
        "payload_sha256": sha(canonical(payload)),
        "declared_binding_sha256": binding_doc.get("binding_sha256"),
        "declared_equals_measured": binding_doc.get("binding_sha256") == sha(canonical(payload)),
        "business_date": binding_doc.get("business_date"),
        "dataset_version": (binding_doc.get("dataset") or {}).get("dataset_version")
        if isinstance(binding_doc.get("dataset"), dict)
        else None,
        "label_version": (binding_doc.get("dataset") or {}).get("label_version")
        if isinstance(binding_doc.get("dataset"), dict)
        else None,
    }

    # 每个 run 的 evidence 树 + 卡 + 回执 + seal-manifest（只读）
    runs = {}
    for idx in range(4):
        run_dir = RUN_ROOT / "runs" / f"r{idx}"
        card = run_dir / "card.json"
        evidence_dir = run_dir / "evidence"  # seal-manifest 的 evidence_root 就是这个目录
        seal_dir = next((run_dir / "seal").iterdir())
        evidence_tree = tree_digest(evidence_dir)
        seal_manifest = json.loads((seal_dir / "seal-manifest.json").read_text(encoding="utf-8"))
        receipt = json.loads((seal_dir / "run-receipt.json").read_text(encoding="utf-8"))
        runs[f"r{idx}"] = {
            "run_id": (json.loads(card.read_text(encoding="utf-8")) or {}).get("run_id"),
            "scenario_id": seal_manifest.get("run_id") and receipt.get("scenario_id"),
            "card": {"path": str(card), "sha256": sha(card.read_bytes()), "bytes": card.stat().st_size},
            "evidence_tree": {
                "file_count": evidence_tree["file_count"],
                "total_bytes": evidence_tree["bytes"],
                "tree_sha256": evidence_tree["tree_sha256"],
                "seal_manifest_tree_sha256": (seal_manifest.get("evidence_root") or {}).get("tree_sha256"),
                "cross_check_equal": evidence_tree["tree_sha256"]
                == (seal_manifest.get("evidence_root") or {}).get("tree_sha256"),
            },
            "seal_manifest": {"path": str(seal_dir / "seal-manifest.json"), "sha256": sha((seal_dir / "seal-manifest.json").read_bytes())},
            "run_receipt": {"path": str(seal_dir / "run-receipt.json"), "sha256": sha((seal_dir / "run-receipt.json").read_bytes())},
            "case_plan": {
                "path": str(run_dir / "out" / "controlled" / "case-plan.json"),
                "sha256": sha((run_dir / "out" / "controlled" / "case-plan.json").read_bytes()),
            },
            "evidence_key_file_sha256": sha((run_dir / "ev.key").read_bytes()),
        }
    measured["runs"] = runs

    cards_sha = sha(canonical({k: v["card"]["sha256"] for k, v in runs.items()}))
    trees_sha = sha(canonical({k: v["evidence_tree"]["tree_sha256"] for k, v in runs.items()}))

    components = {
        "analysis_id": "Q1A-RESCORE-20261114-r1",
        "old_run_binding_payload_sha256": measured["old_run_binding"]["payload_sha256"],
        "old_run_binding_file_sha256": measured["old_run_binding"]["file_sha256"],
        "old_evidence_tree_sha256": trees_sha,
        "old_card_sha256": cards_sha,
        "contract_ciphertext_sha256": sha(CONTRACT_CIPHER.read_bytes()),
        "contract_ciphertext_bytes": CONTRACT_CIPHER.stat().st_size,
        "contract_schema_sha256": sha(CONTRACT_SCHEMA.read_bytes()),
        "q1a1_module_sha256": sha((REPO / "backend/src/mktkb/evaluation/p2_evidence_rescore.py").read_bytes()),
        "q1a1b_module_sha256": sha((REPO / "backend/src/mktkb/evaluation/p2_evidence_rescore_axes.py").read_bytes()),
        "q1a1_contract_sha256": sha((REPO / "docs/evaluation/p2-evidence-rescore-v0_1.md").read_bytes()),
        "q1a1b_contract_sha256": sha((REPO / "docs/evaluation/p2-evidence-rescore-v0_2.md").read_bytes()),
    }
    expected_map = {
        "old_run_binding_payload_sha256": EXPECTED["old_run_binding_payload_sha256"],
        "contract_ciphertext_sha256": EXPECTED["contract_ciphertext_sha256"],
        "contract_schema_sha256": EXPECTED["contract_schema_sha256"],
        "q1a1_module_sha256": EXPECTED["q1a1_module_sha256"],
        "q1a1b_module_sha256": EXPECTED["q1a1b_module_sha256"],
        "q1a1_contract_sha256": EXPECTED["q1a1_contract_sha256"],
        "q1a1b_contract_sha256": EXPECTED["q1a1b_contract_sha256"],
    }
    checks = [
        {"component": name, "measured": components[name], "expected": expected, "match": components[name] == expected}
        for name, expected in expected_map.items()
    ]
    ok = all(c["match"] for c in checks) and all(v["evidence_tree"]["cross_check_equal"] for v in runs.values())

    print(
        json.dumps(
            {
                "schema_version": "q1a3-identity-binding/v0.1",
                "overall": "MATCH" if ok else "MISMATCH",
                "checks": checks,
                "identity_components": components,
                "package_binding_sha256": sha(canonical(components)),
                "package_binding_note": (
                    "本包自定的 canonical 组件摘要，用于防止拼不同轮；"
                    "不是 p2_evidence_rescore 的 analysis_identity_sha256（后者只能由成功评分签发）"
                ),
                "measured": measured,
                "calls": {"network": 0, "socket": 0, "dns": 0, "provider": 0, "model": 0, "retrieval": 0, "real": 0},
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

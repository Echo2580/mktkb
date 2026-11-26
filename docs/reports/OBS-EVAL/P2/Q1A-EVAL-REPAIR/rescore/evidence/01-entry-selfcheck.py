"""Q1a-3 入口自检（只读、零网络、零真实调用）。

只使用既有受控入口：
  - tools/p2_h2_controlled_execute.py::load_private_bundle（内部 load_p2_dataset + load_scenario_contract）
不在本脚本中打印任何题面/答案/目标值/逐题内容；只输出版本、计数、hash。
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

REPO = Path(r"D:\GPT项目\市场部AI知识库")
sys.path.insert(0, str(REPO / "backend" / "src"))
sys.path.insert(0, str(REPO / "tools"))

CUSTODY = Path(
    r"C:\Users\dell1712\.codex\visualizations\2026\11\12\01a1cd24-bccf-7e00-80df-0b75f57f7d1c\t207-custody"
)
HOLDOUT_ROOT = Path(r"D:\mktkb-p2-holdout\v2")
HOLDOUT_KEY = Path(r"D:\mktkb-p2-holdout\keys\v2.key")
CONTRACT_CIPHER = Path(r"D:\mktkb-q1a2-scope-contract\scope-targets-contract-v1.fernet")
CONTRACT_SCHEMA = REPO / "docs" / "evaluation" / "q1a-scope-targets-contract-v1.md"
EXPECTED = {
    "contract_ciphertext_sha256": "467dbf7706df26f2069a79e2b344b53c0e10c03ff830ed62efff9b5dfd16f461",
    "contract_ciphertext_bytes": 47012,
    "contract_schema_sha256": "cb1257fac56a68e5eef791c23cffba9d4e915e5e9a840abce7bde5b96e0e4690",
    "q1a1_module_sha256": "d8260256b4c3572f206a39f39dc8fe2847fa4946dc9b7bd05e93c5fd7841f3e9",
    "q1a1_contract_sha256": "e0487f256524558ae12b00e6a9d961a7360e92f1437ab4d7d0c55702f375588d",
    "q1a1b_module_sha256": "57495943c763977e62fa7acded407e99ba360336fc5ee8c822f5e084f200f08e",
    "q1a1b_contract_sha256": "747e3656bfbaf0bb4f0e40444d96d20d2b30806d80d061fbca13b962a46c8db5",
    "dataset_version": "P2-HOLDOUT-v2",
    "label_version": "p2-holdout-v2-2026-11-10",
    "cases_sha256": "a0ad48c9",
    "cases_sha256_full": None,  # 见输出；前缀核对即可，全值由本次实测记录
    "old_run_binding_payload_sha256": "291cfec9d99446c88f0063d533c92632cef15594c1f6ce3da2269cef98ae65d4",
    "case_count": 30,
    "turn_count": 36,
}


def sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical(payload) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def main() -> int:
    from mktkb.evaluation.dataset import cases_to_jsonl
    from mktkb.evaluation.p2_holdout_scenarios import case_questions

    import p2_h2_controlled_execute as entry

    checks: list[dict] = []
    ok = True

    def check(name: str, measured, expected=None, note: str = "") -> None:
        nonlocal ok
        if expected is None:
            passed = True
        elif isinstance(expected, str) and expected.endswith("…"):
            passed = str(measured).startswith(expected[:-1])
        else:
            passed = measured == expected
        ok = ok and passed
        checks.append(
            {
                "check": name,
                "measured": measured,
                "expected": expected,
                "match": bool(passed),
                "note": note,
            }
        )

    paths = entry.InputPaths(
        # load_p2_dataset 要求 manifest 位于 holdout root 内；该文件与仓库内公开副本逐字节相同。
        holdout_manifest=HOLDOUT_ROOT / "manifest.json",
        annotation_ciphertext=CUSTODY / "annotations-v0_2.fernet",
        review_ciphertext=CUSTODY / "review-v0_2.fernet",
        scenario_key_file=HOLDOUT_KEY,
        addendum_ciphertext=CUSTODY / "annotations-gapaddendum-v0_3.fernet",
        scenario_contract=entry.DEFAULT_SCENARIO_CONTRACT,
        ingest_plan=entry.DEFAULT_INGEST_PLAN,
        source_map=entry.DEFAULT_SOURCE_MAP,
        annotation_schema=entry.DEFAULT_ANNOTATION_SCHEMA,
        manager_acceptance_v2=entry.DEFAULT_MANAGER_V2,
        review_aggregate_v2=entry.DEFAULT_REVIEW_AGGREGATE_V2,
        addendum_acceptance_v3=entry.DEFAULT_ADDENDUM_ACCEPTANCE,
    )
    runtime = entry.RuntimeOptions(
        holdout_root=HOLDOUT_ROOT,
        holdout_key_file=HOLDOUT_KEY,
        project_total_limit_cny=entry.PROJECT_TOTAL_LIMIT_CNY,
    )

    bundle = entry.load_private_bundle({}, paths, runtime=runtime)

    # 1) 数据集/标签版本与形状
    ds = bundle.dataset
    manifest = ds.manifest
    check("dataset_visibility", ds.visibility, "holdout")
    check("dataset_version", manifest.dataset_version, EXPECTED["dataset_version"])
    check("label_version", manifest.label_version, EXPECTED["label_version"])
    check("manifest_case_count", int(manifest.case_count), EXPECTED["case_count"])
    check("business_date", str(manifest.business_date), "2026-10-28")
    check("loaded_case_count", len(ds.cases), EXPECTED["case_count"])
    case_ids = [c.case_id for c in ds.cases]
    check("case_ids_unique", len(set(case_ids)), EXPECTED["case_count"])
    turns_total = sum(len(case_questions(c)) for c in ds.cases)
    check("turn_count_total", turns_total, EXPECTED["turn_count"])
    check("manifest_turn_stats_total", int(manifest.turn_stats["total_turns"]), EXPECTED["turn_count"])
    # 同序：dataset 加载序 == annotation 顺序 == contract 顺序（由 load_scenario_contract 保证）
    annotation_order = [row["case_id"] for row in bundle.annotation["cases"]]
    check("dataset_vs_annotation_order", annotation_order == case_ids, True)
    # business_date 全题一致
    check(
        "all_case_business_date_match",
        all(str(c.business_date) == str(manifest.business_date) for c in ds.cases),
        True,
    )

    # 2) 冻结 30 题 canonical JSONL 摘要
    cases_sha = sha_bytes(cases_to_jsonl(ds.cases).encode("utf-8"))
    check("cases_sha256", cases_sha, "a0ad48c9bbab96ac683e325c773dfee2dc247708fea7ddeefb08f567b102c3c3")

    # 3) 场景契约 / 标注 覆盖（29+1 拆分：26/1/2/1）
    contract = bundle.contract
    scenario_counts = {}
    for name in contract.scenario_ids:
        subset = contract.subset(name)
        scenario_counts[name] = {
            "cases": int(len(subset.cases)),
            "turns": int(subset.identity["turn_stats"]["total_turns"]),
        }
    check("scenario_counts_total", sum(v["cases"] for v in scenario_counts.values()), 30)
    check("scenario_turns_total", sum(v["turns"] for v in scenario_counts.values()), 36)
    check(
        "scenario_case_counts_expected",
        {k: v["cases"] for k, v in scenario_counts.items()},
        {"base_b0": 26, "base_b0_plus_v01": 1, "pre_v05_without_v07": 2, "post_v05_without_v01": 1},
    )
    merged_axes = bundle.annotation
    check("annotation_case_count", len(merged_axes["cases"]), EXPECTED["case_count"])
    addendum_gaps = bundle.addendum.get("gaps") or []
    check("addendum_gap_count", len(addendum_gaps), 4)

    # 4) 合同密文 / schema / 模块 / 契约 hash
    check("contract_ciphertext_sha256", sha_bytes(CONTRACT_CIPHER.read_bytes()), EXPECTED["contract_ciphertext_sha256"])
    check("contract_ciphertext_bytes", CONTRACT_CIPHER.stat().st_size, EXPECTED["contract_ciphertext_bytes"])
    check("contract_schema_sha256", sha_bytes(CONTRACT_SCHEMA.read_bytes()), EXPECTED["contract_schema_sha256"])
    check(
        "q1a1_module_sha256",
        sha_bytes((REPO / "backend/src/mktkb/evaluation/p2_evidence_rescore.py").read_bytes()),
        EXPECTED["q1a1_module_sha256"],
    )
    check(
        "q1a1b_module_sha256",
        sha_bytes((REPO / "backend/src/mktkb/evaluation/p2_evidence_rescore_axes.py").read_bytes()),
        EXPECTED["q1a1b_module_sha256"],
    )
    check(
        "q1a1_contract_sha256",
        sha_bytes((REPO / "docs/evaluation/p2-evidence-rescore-v0_1.md").read_bytes()),
        EXPECTED["q1a1_contract_sha256"],
    )
    check(
        "q1a1b_contract_sha256",
        sha_bytes((REPO / "docs/evaluation/p2-evidence-rescore-v0_2.md").read_bytes()),
        EXPECTED["q1a1b_contract_sha256"],
    )

    # 5) 旧 run binding payload（去 binding_sha256 的 canonical JSON）
    binding_path = Path(r"D:\mktkb-p2-t207-h2-20261114\plans2\run-binding.json")
    binding_raw = binding_path.read_bytes()
    binding_doc = json.loads(binding_raw.decode("utf-8"))
    declared = binding_doc.get("binding_sha256")
    payload = {k: v for k, v in binding_doc.items() if k != "binding_sha256"}
    payload_sha = sha_bytes(canonical(payload))
    check("old_run_binding_file_sha256_declared_matches", declared, payload_sha, note="文档内声明值 vs 复算")
    check("old_run_binding_payload_sha256", payload_sha, EXPECTED["old_run_binding_payload_sha256"])
    check("old_run_binding_file_bytes", len(binding_raw), 19032)

    # 6) 旧卡字节
    card_hashes = {}
    for idx in range(4):
        card = Path(rf"D:\mktkb-p2-t207-h2-20261114\runs\r{idx}\card.json")
        card_hashes[f"r{idx}"] = {"sha256": sha_bytes(card.read_bytes()), "bytes": card.stat().st_size}
    check("old_card_count", len(card_hashes), 4)
    check(
        "manifest_repo_copy_equals_holdout_copy",
        sha_bytes((REPO / "docs/evaluation/p2-holdout-v2.manifest.json").read_bytes())
        == sha_bytes((HOLDOUT_ROOT / "manifest.json").read_bytes()),
        True,
    )

    print(
        json.dumps(
            {
                "schema_version": "q1a3-entry-selfcheck/v0.1",
                "overall": "PASS" if ok else "FAIL",
                "checks": checks,
                "measured": {
                    "cases_sha256": cases_sha,
                    "scenario_counts": scenario_counts,
                    "old_run_binding_payload_sha256": payload_sha,
                    "old_run_binding_file_sha256": sha_bytes(binding_raw),
                    "old_cards": card_hashes,
                    "inputs": {name: {"sha256": rec["sha256"], "bytes": rec["bytes"]} for name, rec in bundle.inputs.items()},
                },
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

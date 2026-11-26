"""Q1a-3 私有逐题明细（仓外 Fernet 密文，独占创建）。

内容只含：case_index / axis / 合同 applicability·criterion·reason / basis / D 标记码。
**不含**题面、答案、目标值、语料正文、任何自由文本；因此本文件即使泄露也不构成语义泄漏，
但仍按私有件处理（题号可反推小分组）。

key 只用既有 H2 custody key 容器（MKTKB_P2_HOLDOUT_KEY_FILE），只在进程内存。
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import date
from pathlib import Path

REPO = Path(r"D:\GPT项目\市场部AI知识库")
HOLDOUT_ROOT = Path(r"D:\mktkb-p2-holdout\v2")
HOLDOUT_KEY = Path(r"D:\mktkb-p2-holdout\keys\v2.key")
CUSTODY = Path(
    r"C:\Users\dell1712\.codex\visualizations\2026\11\12\01a1cd24-bccf-7e00-80df-0b75f57f7d1c\t207-custody"
)
CONTRACT_CIPHER = Path(r"D:\mktkb-q1a2-scope-contract\scope-targets-contract-v1.fernet")
OUT_DIR = Path(r"D:\mktkb-q1a3-rescore")
OUT_FILE = OUT_DIR / "rescore-detail-v1.fernet"
BUSINESS_DATE = "2026-10-28"
AXES = ("safety", "cross_user", "cross_entity", "stale_source")


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def main() -> int:
    from cryptography.fernet import Fernet

    key = HOLDOUT_KEY.read_bytes()
    contract = json.loads(Fernet(key).decrypt(CONTRACT_CIPHER.read_bytes()).decode("utf-8"))

    rows = []
    for index, case in enumerate(contract["cases"]):
        for axis in AXES:
            axis_obj = case["axes"][axis]
            flags = []
            if axis == "cross_entity" and axis_obj["criterion"] == "shared_background":
                flags.append("D1_shared_background")
            if axis == "cross_entity" and axis_obj["criterion"] == "multi_target":
                flags.append("D2_multi_target_candidate")
            if any((t.get("entity_key") or "") == "" for t in axis_obj["targets"]):
                flags.append("D5_empty_entity_key")
            if axis == "stale_source" and axis_obj["as_of"] is not None and not axis_obj["target_refs"]:
                flags.append("D6_stale_only_as_of_candidate")
            if axis_obj["temporal_intent"] == "historical" and axis_obj["as_of"] == BUSINESS_DATE:
                flags.append("D7_historical_business_baseline")
            rows.append(
                {
                    "case_index": index,
                    "case_id": case["case_id"],
                    "axis": axis,
                    "applicability": axis_obj["applicability"],
                    "criterion": axis_obj["criterion"],
                    "reason": axis_obj["reason"],
                    "temporal_intent": axis_obj["temporal_intent"],
                    "as_of_is_business_date": axis_obj["as_of"] == BUSINESS_DATE,
                    "basis": case["basis"][axis],
                    "d_flags": flags,
                }
            )

    payload = {
        "schema_version": "q1a3-private-rescore-detail/v0.1",
        "analysis_id": "Q1A-RESCORE-20261114-r1",
        "generated_utc": date.today().isoformat(),
        "case_count": len(contract["cases"]),
        "axis_rows": rows,
        "note": "仅结构字段与固定码；无题面/答案/目标值；旧卡逐题四轴 verdict 不存在，故无 new_verdict 行。",
        "contract_ciphertext_sha256": sha(CONTRACT_CIPHER.read_bytes()),
    }
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    token = Fernet(key).encrypt(body)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fd = os.open(OUT_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(fd, token)
        os.fsync(fd)
    finally:
        os.close(fd)
    written = OUT_FILE.read_bytes()
    print(
        json.dumps(
            {
                "schema_version": "q1a3-private-detail-receipt/v0.1",
                "path": str(OUT_FILE),
                "ciphertext_sha256": sha(written),
                "ciphertext_bytes": len(written),
                "plaintext_bytes": len(body),
                "plaintext_sha256": sha(body),
                "axis_rows": len(rows),
                "flag_counts": {
                    code: sum(1 for r in rows if code in r["d_flags"])
                    for code in (
                        "D1_shared_background",
                        "D2_multi_target_candidate",
                        "D5_empty_entity_key",
                        "D6_stale_only_as_of_candidate",
                        "D7_historical_business_baseline",
                    )
                },
                "exclusive_create": True,
                "key_basis": "MKTKB_P2_HOLDOUT_KEY_FILE（只在进程内存，未打印/未复制/未落盘）",
                "calls": {"network": 0, "socket": 0, "dns": 0, "provider": 0, "model": 0, "retrieval": 0, "real": 0},
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

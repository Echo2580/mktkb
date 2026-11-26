"""v3 语料返工 R1：重出 ``docs/evaluation/p2-holdout-v3.source-map.json``（v0.2，SHA 必变）。

只做两件事（规格 §4.2；与上一轮逐条相同，不新增字段）：
1. ``sources`` 保持 12 条全声明，``(base_doc_code, version_number)`` 与 L1 的 12 行**双射**；
   v0.1 已声明的 4 个值逐值不变（V03→D01/1、V04→D01/3、V05→D01/4、V06→D02/2）；
2. 顶层只保留两个引用：``lifecycle_ref`` 与 ``corpus_ref``。

R1 的差别只在**被指向件的 SHA**：L1 修了 ``records_rows``（2→4），v3 语料加了 11 格哨兵 ⇒
``lifecycle_ref.sha256`` 与 ``corpus_ref.manifest_sha256`` 都变了，本文件 SHA 因此必变。
旧值从 ``00r1-baseline.json`` 的 ``authorized_change_targets`` 读，写进 ``sha_comparison`` 供报告对照。

明确不做：不把任何日期写进 source map（身份与生命周期分离）；不改 v0.1 文件。
零真实调用；双射失败即 fail closed。

用法：``.venv\\Scripts\\python.exe 06r1-source-map.py``
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = Path(__file__).resolve().parents[7]
L1_PATH = ROOT / "docs/evaluation/p2-source-lifecycle-v1.json"
V3_MANIFEST = ROOT / "fixtures/acceptance-h2v3/manifest.json"
OUT_PATH = ROOT / "docs/evaluation/p2-holdout-v3.source-map.json"
EVIDENCE_OUT = HERE / "06r1-source-map.json"
BASELINE = HERE / "00r1-baseline.json"

FROZEN_V01 = {
    "V03": {"base_doc_code": "D01", "version_number": 1},
    "V04": {"base_doc_code": "D01", "version_number": 3},
    "V05": {"base_doc_code": "D01", "version_number": 4},
    "V06": {"base_doc_code": "D02", "version_number": 2},
}

BASIS = [
    "fixtures/acceptance-h2v3/manifest.json：语料根由 v2 复制而来，12 个被 ingest 源的 (doc_code, version_number) 与本表逐条双射；v2 的 b0_initialization 记录 D01 槽位先导入 V03(v1) 再导入 D01(v2)、D02 从 v1 起步。",
    "docs/reports/OBS-EVAL/P2/T207/PM/T207-ingest-plan-H2.json：上传次序 V03,D01,V04,V05（D01 槽位）与 D02,V06（D02 槽位）；版本身份服从上传次序（含未发布上传）。版本号是身份，不是 active 断言。",
    "v0.1 已声明的四个码逐值不变（V03=1、V04=3、V05=4、V06=2）；其余八个码按版本序补全（D01=2、D02=1、D03..D06=1、V01=1、V07=1），实测冲突 0。",
    "corpus/enterprise-20261101/manifest.json 的 import_recipe 属另一套语料（同名的 V04/V05 字节不同、V06 与 V05 重复），不得用于 acceptance/H2 的版本槽位。",
    "生命周期窗口不写在本文件：唯一真相源是 lifecycle_ref 指向的 p2-source-lifecycle/v1（date_window 的窗口由 L1 逐值提供）。",
    "R1（2026-11-15）：语料只有 失效日期 的 11 个 null 格改为哨兵 未声明（规格 §1.5）；本文件的 (doc_code, version_number) 映射与字段集一字未改，只有两处被指向件的 sha256 随其内容更新。",
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    l1 = json.loads(L1_PATH.read_text(encoding="utf-8"))
    assert l1["schema_version"] == "p2-source-lifecycle/v1"
    assert l1["interval"] == "closed"
    sources = {
        row["source_id"]: {"base_doc_code": row["doc_code"], "version_number": int(row["version_number"])}
        for row in l1["sources"]
    }
    if len(sources) != 12:
        raise SystemExit(f"L1 sources 不是 12 行: {len(sources)}")
    for source_id, frozen in FROZEN_V01.items():
        if sources.get(source_id) != frozen:
            raise SystemExit(f"v0.1 冻结值与 L1 冲突: {source_id} {sources.get(source_id)} != {frozen}")
    pairs = [(row["doc_code"], int(row["version_number"])) for row in l1["sources"]]
    if len(set(pairs)) != len(pairs):
        raise SystemExit(f"L1 的 (doc_code, version_number) 不唯一: {pairs}")

    payload = {
        "schema_version": "p2-holdout-source-map/v0.2",
        "sources": {source_id: sources[source_id] for source_id in sorted(sources)},
        "basis": BASIS,
        "lifecycle_ref": {
            "path": "docs/evaluation/p2-source-lifecycle-v1.json",
            "sha256": sha256_file(L1_PATH),
            "schema_version": "p2-source-lifecycle/v1",
        },
        "corpus_ref": {
            "root": "fixtures/acceptance-h2v3",
            "manifest_sha256": sha256_file(V3_MANIFEST),
        },
    }
    OUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")

    baseline = json.loads(BASELINE.read_text(encoding="utf-8")).get("authorized_change_targets", {})
    old = baseline.get("docs/evaluation/p2-holdout-v3.source-map.json", {}).get("sha256")
    sha_comparison = {
        "source_map": {"r0": old, "r1": sha256_file(OUT_PATH), "changed": old != sha256_file(OUT_PATH)},
        "lifecycle": {
            "r0": baseline.get("docs/evaluation/p2-source-lifecycle-v1.json", {}).get("sha256"),
            "r1": sha256_file(L1_PATH),
        },
        "corpus_manifest": {
            "r0": baseline.get("fixtures/acceptance-h2v3/manifest.json", {}).get("sha256"),
            "r1": sha256_file(V3_MANIFEST),
        },
        "corpus_ref": payload["corpus_ref"],
        "lifecycle_ref": payload["lifecycle_ref"],
    }
    sha_comparison["lifecycle"]["changed"] = sha_comparison["lifecycle"]["r0"] != sha_comparison["lifecycle"]["r1"]
    sha_comparison["corpus_manifest"]["changed"] = sha_comparison["corpus_manifest"]["r0"] != sha_comparison["corpus_manifest"]["r1"]
    summary = {
        "path": str(OUT_PATH.relative_to(ROOT)).replace("\\", "/"),
        "bytes": OUT_PATH.stat().st_size,
        "sha256": sha256_file(OUT_PATH),
        "schema_version": payload["schema_version"],
        "source_count": len(payload["sources"]),
        "bijection_with_l1": True,
        "frozen_v01_values_unchanged": True,
        "dates_present": False,
        "top_level_keys": list(payload),
        "sha_comparison": sha_comparison,
    }
    EVIDENCE_OUT.write_text(json.dumps(summary, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0 if all(
        [
            sha_comparison["source_map"]["changed"],
            sha_comparison["lifecycle"]["changed"],
            sha_comparison["corpus_manifest"]["changed"],
        ]
    ) else 1


if __name__ == "__main__":
    sys.exit(main())

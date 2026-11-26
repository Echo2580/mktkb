"""Q1a-3-R2 诊断探针：只输出**计数/分类**，不输出任何题面/答案/目标值/名称字面值。

用途（在写正式 R2 脚本前确认输入形状）：
1. 公开结构 -> 每个 scenario 的 active 版本表（只输出计数与 canonical 表 hash）。
2. 案件 refs 的 doc_code 覆盖分类（bound / 不 bound）。
3. 产品 unit.document_name 在 R1 规则 vs R2 扩展规则下的映射计数与未命中结构原因。
4. C 冻结 `_empty_use_scope_proof` 在真实 envelope 上的结果分布（bool/reason 计数），
   并再次核 `p2_hard_evidence.py` 的 SHA256。
5. unit.version_number / version_id 的可用性计数。
"""

from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[6]
for path in (HERE, REPO / "backend" / "src", REPO / "tools"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

sys.path.insert(0, str(HERE.parent / "evidence-r1"))
import _common_r1 as R1  # noqa: E402


def _public_json(rel: str):
    return R1.strict_json((REPO / rel).read_bytes())


def _basename(path: str) -> str:
    return Path(path.replace("\\", "/")).name


def source_identity_table():
    sm = _public_json("docs/evaluation/p2-holdout-v2.source-map.json")
    ingest = _public_json("docs/reports/OBS-EVAL/P2/T207/PM/T207-ingest-plan-H2.json")
    manifest = _public_json("fixtures/acceptance/manifest.json")
    variants = {row["id"]: row for row in manifest["variants"]}
    normals = {row["id"]: row for row in manifest["normal_files"]}
    map_rows = sm["sources"]
    rows = []
    for index, entry in enumerate(ingest["sources"]):
        base = _basename(entry["path"])
        prefix = base.split("_", 1)[0]
        doc_code = None
        version = None
        origin = "unresolved"
        if prefix in map_rows:
            doc_code = map_rows[prefix]["base_doc_code"]
            version = map_rows[prefix]["version_number"]
            origin = "source_map"
        elif prefix in normals:
            doc_code = prefix
            version = int(str(normals[prefix]["business_version"]).lstrip("V"))
            origin = "fixture_manifest_normal"
        elif prefix in variants:
            origin = "variant_without_base_doc_code"
        rows.append(
            {
                "index": index,
                "doc_code": doc_code,
                "version_number": version,
                "origin": origin,
                "upload_slot": prefix,
            }
        )
    return rows


def active_tables(source_rows):
    scenarios = _public_json("docs/evaluation/p2-h2-scenarios-v0_2.json")
    out = {}
    for scenario in scenarios["scenarios"]:
        groups = {}
        for index in scenario["source_indices"]:
            row = source_rows[index]
            key = row["doc_code"] or f"slot:{row['upload_slot']}"
            groups.setdefault(key, []).append(row)
        active = {}
        ambiguous = {}
        for key, rows in groups.items():
            versions = [row["version_number"] for row in rows]
            if key.startswith("slot:") or any(version is None for version in versions):
                ambiguous[key] = "version_number_unresolved"
                continue
            top = max(versions)
            winners = [row for row in rows if row["version_number"] == top]
            if len(winners) != 1:
                ambiguous[key] = "multiple_active_versions"
                continue
            active[key] = {
                "version_number": top,
                "basis": winners[0]["origin"],
                "source_index": winners[0]["index"],
                "uploads": len(rows),
            }
        out[scenario["scenario_id"]] = {
            "active": active,
            "ambiguous": ambiguous,
            "source_indices": scenario["source_indices"],
        }
    return out


def ref_coverage(scenarios_active):
    bundle = R1.load_bundle()
    manifest = _public_json("fixtures/acceptance/manifest.json")
    source_map = _public_json("docs/evaluation/p2-holdout-v2.source-map.json")["sources"]
    public_doc_codes = {row["id"] for row in manifest["normal_files"]}
    all_variant_ids = {row["id"] for row in manifest["variants"]}
    specs = {case.case_id: case for case in bundle.dataset.cases}
    annotation = {row["case_id"]: row["scenario_id"] for row in bundle.annotation["cases"]}
    counts = Counter()
    doc_universe = set()
    for case in bundle.dataset.cases:
        scenario = annotation[case.case_id]
        active = scenarios_active[scenario]["active"]
        spec = specs[case.case_id]
        for collection, refs in (
            ("expected_sources", spec.expected_sources),
            ("forbidden_sources", spec.forbidden_sources),
            ("relevant_units", spec.relevant_units),
        ):
            for ref in refs:
                doc_code = ref.get("doc_code")
                doc_universe.add(doc_code)
                if doc_code in source_map:
                    category = "source_map_variant"
                elif doc_code in public_doc_codes:
                    category = "normal_doc"
                elif doc_code in all_variant_ids:
                    category = "other_variant"
                elif doc_code is None:
                    category = "none"
                else:
                    category = "unknown"
                counts[f"{collection}|category={category}"] += 1
                if doc_code in active:
                    counts[f"{collection}|bound"] += 1
                    counts[f"{collection}|bound|basis={active[doc_code]['basis']}"] += 1
                elif doc_code in source_map and source_map[doc_code]["base_doc_code"] in active:
                    base = source_map[doc_code]["base_doc_code"]
                    counts[f"{collection}|unbound|variant_base_active"] += 1
                    counts[
                        f"{collection}|unbound|variant_base_active|refversion={source_map[doc_code]['version_number']}"
                        f"|active={active[base]['version_number']}"
                    ] += 1
                else:
                    counts[f"{collection}|unbound"] += 1
                    if doc_code in source_map:
                        reason = "source_map_variant_base_not_active"
                    elif doc_code in all_variant_ids:
                        reason = "independent_notice_without_base_doc_code"
                    elif doc_code in public_doc_codes:
                        reason = "doc_known_but_not_uploaded_in_scenario"
                    else:
                        reason = "doc_code_not_in_public_structure"
                    counts[f"{collection}|unbound|{reason}"] += 1
    return counts, len(doc_universe)


def name_mapping_probe():
    sm = _public_json("docs/evaluation/p2-holdout-v2.source-map.json")
    ingest = _public_json("docs/reports/OBS-EVAL/P2/T207/PM/T207-ingest-plan-H2.json")
    manifest = _public_json("fixtures/acceptance/manifest.json")
    map_rows = sm["sources"]
    normals = {row["id"]: row for row in manifest["normal_files"]}
    variants = {row["id"]: row for row in manifest["variants"]}

    def classify(name: str) -> tuple[str | None, str]:
        prefix = name.split("_", 1)[0]
        if prefix in map_rows:
            return map_rows[prefix]["base_doc_code"], "source_map_variant"
        if prefix in normals:
            return prefix, "fixture_manifest_normal"
        if prefix in variants:
            return None, "variant_without_base_doc_code"
        return None, "prefix_not_in_public_structure"

    names = set()
    for entry in ingest["sources"]:
        for key in ("name", "document_ref"):
            value = entry.get(key)
            if isinstance(value, str) and value.strip():
                names.add(value.strip())
        names.add(_basename(entry["path"]))
    mapping = {}
    reasons = Counter()
    for name in sorted(names):
        doc_code, reason = classify(name)
        reasons[reason] += 1
        if doc_code is not None:
            mapping[name] = doc_code

    from mktkb.evaluation.p2_evidence_io import read_encrypted_evidence

    observed = Counter()
    observed_names = set()
    observed_name_kind = Counter()
    observed_units_kind = Counter()
    r1_universe = {
        row["base_doc_code"] for row in map_rows.values()
    }
    r1_mapped_units = 0
    total_units = 0
    name_sets = {
        "ingest_name": {
            entry["name"].strip()
            for entry in ingest["sources"]
            if isinstance(entry.get("name"), str) and entry["name"].strip()
        },
        "ingest_document_ref": {
            entry["document_ref"].strip()
            for entry in ingest["sources"]
            if isinstance(entry.get("document_ref"), str) and entry["document_ref"].strip()
        },
        "path_basename": {_basename(entry["path"]) for entry in ingest["sources"]},
    }
    for run_index in range(4):
        run_dir = R1.OLD_RUN / "runs" / f"r{run_index}"
        plan = R1.strict_json((run_dir / "out" / "controlled" / "case-plan.json").read_bytes())
        key = (run_dir / "ev.key").read_bytes()
        evidence_dir = next(p for p in (run_dir / "evidence").iterdir() if p.is_dir())
        for plan_case in plan["cases"]:
            for turn in plan_case["turns"]:
                if turn.get("status") != "executed":
                    continue
                envelope = read_encrypted_evidence(evidence_dir / turn["evidence_file"], key=key)
                projection = envelope["db_projection"]
                for unit in projection.get("units") or ():
                    total_units += 1
                    name = unit.get("document_name")
                    if isinstance(name, str) and name.split("_", 1)[0] in r1_universe:
                        r1_mapped_units += 1
                    if not isinstance(name, str) or not name.strip():
                        observed["name_empty"] += 1
                        continue
                    if name not in observed_names:
                        kinds = [kind for kind, values in name_sets.items() if name in values]
                        observed_name_kind["|".join(sorted(kinds)) or "none"] += 1
                    observed_names.add(name)
                    kinds = [kind for kind, values in name_sets.items() if name in values]
                    observed_units_kind["|".join(sorted(kinds)) or "none"] += 1
                    if name in mapping:
                        observed["mapped_units"] += 1
                    else:
                        _doc_code, reason = classify(name)
                        observed[f"unmapped_units|{reason}"] += 1
    return {
        "ingest_names": len(names),
        "mapped_names": len(mapping),
        "mapped_reason_counts": dict(reasons),
        "observed_distinct_names": len(observed_names),
        "observed_distinct_name_kind": dict(observed_name_kind),
        "observed_unit_kind": dict(observed_units_kind),
        "observed_units": dict(observed),
        "total_units": total_units,
        "r1_rule_mapped_units": r1_mapped_units,
        "r2_rule_mapped_units": observed.get("mapped_units", 0),
    }


def primitive_probe():
    from mktkb.evaluation.p2_hard_evidence import _empty_use_scope_proof
    from mktkb.evaluation.p2_evidence_io import read_encrypted_evidence

    primitive = Counter()
    unit_versions = Counter()
    for run_index in range(4):
        run_dir = R1.OLD_RUN / "runs" / f"r{run_index}"
        plan = R1.strict_json((run_dir / "out" / "controlled" / "case-plan.json").read_bytes())
        key = (run_dir / "ev.key").read_bytes()
        evidence_dir = next(p for p in (run_dir / "evidence").iterdir() if p.is_dir())
        for plan_case in plan["cases"]:
            for turn in plan_case["turns"]:
                if turn.get("status") != "executed":
                    continue
                envelope = read_encrypted_evidence(evidence_dir / turn["evidence_file"], key=key)
                ok, reason = _empty_use_scope_proof(envelope)
                primitive[f"proven={ok}|reason={reason}"] += 1
                projection = envelope["db_projection"]
                for unit in projection.get("units") or ():
                    unit_versions[
                        "version_number_present" if type(unit.get("version_number")) is int else "version_number_absent"
                    ] += 1
                    unit_versions[
                        "version_id_present"
                        if isinstance(unit.get("version_id"), str) and unit.get("version_id").strip()
                        else "version_id_absent"
                    ] += 1
    return dict(primitive), dict(unit_versions)


def main() -> int:
    hard = REPO / "backend/src/mktkb/evaluation/p2_hard_evidence.py"
    sha_before = hashlib.sha256(hard.read_bytes()).hexdigest()
    source_rows = source_identity_table()
    active = active_tables(source_rows)
    coverage, doc_universe = ref_coverage(active)
    names = name_mapping_probe()
    primitive, unit_versions = primitive_probe()
    sha_after = hashlib.sha256(hard.read_bytes()).hexdigest()
    payload = {
        "source_identity_counts": {
            "total": len(source_rows),
            "by_origin": dict(Counter(row["origin"] for row in source_rows)),
        },
        "active_table_counts": {
            scenario: {
                "active_doc_count": len(row["active"]),
                "ambiguous_count": len(row["ambiguous"]),
                "active_versions": sorted(entry["version_number"] for entry in row["active"].values()),
                "upload_counts": sorted(entry["uploads"] for entry in row["active"].values()),
            }
            for scenario, row in active.items()
        },
        "active_table_canonical_sha256": hashlib.sha256(
            json.dumps(active, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
        "ref_coverage": dict(coverage),
        "ref_doc_code_universe": doc_universe,
        "names": names,
        "empty_scope_primitive": primitive,
        "unit_version_fields": unit_versions,
        "hard_evidence_sha_before": sha_before,
        "hard_evidence_sha_after": sha_after,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

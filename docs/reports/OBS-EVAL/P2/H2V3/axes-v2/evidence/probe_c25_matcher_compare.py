"""C25 定性探针：同一份冻结证据，v1 冻结 matcher vs v2 版本敏感 matcher。

只输出**固定码与计数**（verdict/code 枚举 + 版本号 + 布尔），不含题面/答案/query 文本。

- v1：`p2_hard_evidence._ref_matches_unit(ref, unit_row)`（只按 unit_key/locator，忽略 doc/版本）。
- v2：`p2_evidence_rescore.match_ref_to_unit(ref, UnitView, version_binding=...)`，
  版本身份来自 `p2-holdout-v3.source-map/v0.2`（doc_code -> (base_doc_code, version_number)）。
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import re
import sys

REPO = pathlib.Path(r"D:\GPT项目\市场部AI知识库")
WORK = pathlib.Path(r"D:\mktkb-p2-h2v3-20261115")
OUT = REPO / "docs/reports/OBS-EVAL/P2/H2V3/axes-v2/evidence"
for entry in (str(REPO / "backend" / "src"), str(REPO / "tools")):
    if entry not in sys.path:
        sys.path.insert(0, entry)

spec = importlib.util.spec_from_file_location(
    "p2_h2_v3_ce", REPO / "tools" / "p2_h2_v3_controlled_execute.py"
)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)

from mktkb.evaluation.p2_evidence_io import read_encrypted_evidence  # noqa: E402
import mktkb.evaluation.p2_evidence_rescore as rescore  # noqa: E402

hard = module.hard
SCHEMA_VERSION = "p2-h2v3-axes-v2-c25-matcher-compare/v0.1"
FOCUS = ("H2V3-C25",)
SCEN = [
    ("run2-pre_v05_without_v07.binding.json", 2),
]

source_map = json.loads((REPO / "docs/evaluation/p2-holdout-v3.source-map.json").read_text(encoding="utf-8"))
sources = source_map["sources"]
inverse = {
    (str(rec["base_doc_code"]), int(rec["version_number"])): code
    for code, rec in sources.items()
}
_corpus = json.loads((REPO / "fixtures/acceptance-h2v3/manifest.json").read_text(encoding="utf-8"))
record_codes = {
    (str(rec["file"]), str(rec["sheet"]), int(rec["row"])): code
    for code, rec in _corpus["sources"].items()
}
UNIT_KEY_RE = re.compile(r"^sheet:(?P<sheet>.+):row:(?P<row>[0-9]+)$")


def record_code_of(row):
    match = UNIT_KEY_RE.match(str(row.get("unit_key") or ""))
    if match is None:
        return None
    name = str(row.get("document_name") or "")
    base = name.split("_", 1)[0] if "_" in name else None
    if base is None:
        return None
    return record_codes.get((base, match.group("sheet"), int(match.group("row"))))


def binding_for(ref):
    record = sources.get(str(ref.get("doc_code") or ""))
    if record is None:
        return None
    return rescore.VersionBinding(version_number=int(record["version_number"]), basis="source_map")


def doc_code_of(row):
    name = str(row.get("document_name") or "")
    base = name.split("_", 1)[0] if "_" in name else None
    version = row.get("version_number")
    if base is None or type(version) is not int:
        return None
    return inverse.get((base, version))


case_rows = []
for binding_name, run_index in SCEN:
    binding = json.loads(
        (WORK / "regen-1160c" / "bindings" / binding_name).read_text(encoding="utf-8")
    )
    inputs = {name: {"path": record["path"]} for name, record in binding["inputs"].items()}
    bundle = module.load_v3_bundle(inputs)
    run_entry = binding["runs"][0]
    scenario = str(run_entry["scenario_id"])
    cases = bundle.contract.subset(scenario).cases
    key = (WORK / "runs" / "r0" / "ev.key").read_bytes().strip()
    plan_payload = json.loads(
        (WORK / "runs" / f"r{run_index}c" / "out" / "controlled" / "case-plan.json").read_text(
            encoding="utf-8"
        )
    )
    static = {
        name: value
        for name, value in dict(run_entry["evidence_bindings"]).items()
        if name != "index_revision"
    }
    plan = module.v2._validate_case_plan_document(
        plan_payload, cases=cases, static_bindings=static
    )
    root = WORK / "runs" / f"r{run_index}c" / "evidence" / str(run_entry["run_id"])
    for case, row in zip(cases, plan["cases"]):
        if case.case_id not in FOCUS:
            continue
        for turn in row["turns"]:
            if turn["status"] != "executed":
                continue
            envelope = read_encrypted_evidence(
                root / str(turn["evidence_file"]),
                key=key,
                expected_bindings=dict(plan["bindings"]),
            )
            events = hard._events(envelope)
            layers = hard._used_unit_layers(events)
            rows = hard._units_by_id(hard._projection(envelope))
            for unit_id, layer_names in layers.items():
                raw = rows.get(unit_id)
                if raw is None:
                    continue
                doc_code = doc_code_of(raw)
                unit = rescore.UnitView(
                    unit_id=unit_id,
                    layers=tuple(name for name in rescore.USE_LAYERS if name in layer_names),
                    document_id=None if raw.get("document_id") is None else str(raw["document_id"]),
                    document_name=None if raw.get("document_name") is None else str(raw["document_name"]),
                    doc_code=doc_code,
                    version_id=None if raw.get("version_id") is None else str(raw["version_id"]),
                    version_number=raw.get("version_number")
                    if type(raw.get("version_number")) is int
                    else None,
                    unit_key=None if raw.get("unit_key") is None else str(raw["unit_key"]),
                    record_code=record_code_of(raw),
                    locator=dict(raw.get("locator") or {}),
                )
                for role, refs in (
                    ("expected_sources", case.expected_sources),
                    ("forbidden_sources", case.forbidden_sources),
                ):
                    for index, ref in enumerate(refs):
                        frozen_ref = dict(ref)
                        v1_hit = hard._ref_matches_unit(frozen_ref, raw)
                        binding_value = binding_for(frozen_ref)
                        v2 = rescore.match_ref_to_unit(
                            frozen_ref, unit, version_binding=binding_value
                        )
                        # 诊断行：同一个 frozen ref、换用"另一版本槽"的版本绑定，用来隔离
                        # 版本比较本身是否是活的（只改版本绑定，不改 ref 身份）。
                        diag = None
                        if binding_value is not None:
                            other = rescore.VersionBinding(
                                version_number=(1 if binding_value.version_number == 2 else 2),
                                basis="source_map",
                            )
                            diag_result = rescore.match_ref_to_unit(
                                frozen_ref, unit, version_binding=other
                            )
                            diag = {
                                "diagnostic_kind": "same_ref_wrong_version_binding",
                                "version_number": other.version_number,
                                "v2_verdict": diag_result.verdict,
                                "v2_code": diag_result.code,
                            }
                        case_rows.append(
                            {
                                "case_id": case.case_id,
                                "run_index": run_index,
                                "scenario_id": scenario,
                                "role": role,
                                "ref_index": index,
                                "ref_doc_code": str(frozen_ref.get("doc_code")),
                                "ref_bound_version_number": (
                                    None if binding_value is None else binding_value.version_number
                                ),
                                "unit_doc_code": doc_code,
                                "unit_version_number": unit.version_number,
                                "unit_record_code_resolved": unit.record_code is not None,
                                "v1_ref_matches_unit": (
                                    None if v1_hit is None else bool(v1_hit)
                                ),
                                "v1_verdict": (
                                    "unresolved" if v1_hit is None else ("match" if v1_hit else "no_match")
                                ),
                                "v2_verdict": v2.verdict,
                                "v2_code": v2.code,
                                "diagnostic": diag,
                            }
                        )

summary = {
    "v1_true_count": sum(1 for row in case_rows if row["v1_ref_matches_unit"] is True),
    "v2_match_count": sum(1 for row in case_rows if row["v2_verdict"] == "match"),
    "v2_no_match_count": sum(1 for row in case_rows if row["v2_verdict"] == "no_match"),
    "v2_unresolved_count": sum(1 for row in case_rows if row["v2_verdict"] == "unresolved"),
}
payload = {
    "schema_version": SCHEMA_VERSION,
    "matcher_version": "ref-unit-matcher/v2",
    "version_binding_source": "p2-holdout-v3.source-map/v0.2",
    "rows": case_rows,
    "summary": summary,
    "calls": {"network": 0, "provider": 0, "model": 0, "retrieval": 0, "real": 0},
}
target = OUT / "c25-matcher-compare.json"
target.write_text(
    json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
)
print(json.dumps(payload, ensure_ascii=False, indent=1))

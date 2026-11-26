"""C1-P5 forecast: reconstruct v0.3-style snapshots from old v0.2 evidence (in-process only)
and drive the read-only P4 adapter v2 over contract v2.

Prints only counts, fixed codes and aggregate distributions. Never prints question text,
answers, entity keys, record keys, doc codes, dates, unit ids or any target value.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(r"D:\GPT项目\市场部AI知识库")
OUT = ROOT / "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/c1-1/p5/evidence"
CUSTODY = Path(
    r"C:/Users/dell1712/.codex/visualizations/2026/11/12/01a1cd24-bccf-7e00-80df-0b75f57f7d1c/t207-custody"
)
CONTRACT = Path(r"D:\mktkb-q1a2-scope-contract\scope-targets-contract-v2.fernet")
OLD_RUN = Path(r"D:\mktkb-p2-t207-h2-20261114")
MANIFEST = ROOT / "fixtures/acceptance/manifest.json"
SOURCE_MAP = ROOT / "docs/evaluation/p2-holdout-v2.source-map.json"
INGEST = ROOT / "docs/reports/OBS-EVAL/P2/T207/PM/T207-ingest-plan-H2.json"
SCENARIOS = ROOT / "docs/evaluation/p2-h2-scenarios-v0_2.json"

sys.path.insert(0, str(ROOT / "backend" / "src"))
sys.path.insert(0, str(ROOT / "tools"))
os.environ["MKTKB_NO_DOTENV"] = "1"
os.environ["MKTKB_P2_HOLDOUT_ROOT"] = r"D:/mktkb-p2-holdout/v2"
os.environ["MKTKB_P2_HOLDOUT_KEY_FILE"] = r"D:/mktkb-p2-holdout/keys/v2.key"

from cryptography.fernet import Fernet  # noqa: E402

import p2_h2_controlled_execute as ce  # noqa: E402
from mktkb.evaluation import p2_dataset, p2_evidence_io  # noqa: E402
from mktkb.evaluation import p2_evidence_axes_adapter_v2 as ax  # noqa: E402
from mktkb.evaluation import p2_evidence_snapshot_v03 as p3  # noqa: E402
from mktkb.evaluation import p2_hard_evidence as hard  # noqa: E402

PATHS = ce.InputPaths(
    holdout_manifest=Path(r"D:/mktkb-p2-holdout/v2/manifest.json"),
    annotation_ciphertext=CUSTODY / "annotations-v0_2.fernet",
    review_ciphertext=CUSTODY / "review-v0_2.fernet",
    scenario_key_file=Path(r"D:/mktkb-p2-holdout/keys/v2.key"),
    addendum_ciphertext=CUSTODY / "annotations-gapaddendum-v0_3.fernet",
    scenario_contract=SCENARIOS,
    ingest_plan=INGEST,
    source_map=SOURCE_MAP,
    annotation_schema=ROOT / "docs/evaluation/p2-h2-custody-annotations-v0_2.md",
    manager_acceptance_v2=ROOT / "docs/reports/OBS-EVAL/P2/T207-CUSTODY-V2/manager-acceptance.json",
    review_aggregate_v2=ROOT / "docs/reports/OBS-EVAL/P2/T207-CUSTODY-V2/review-aggregate.json",
    addendum_acceptance_v3=ROOT / "docs/reports/OBS-EVAL/P2/T207-CUSTODY-V3/manager-acceptance.json",
)
RUNTIME = ce.RuntimeOptions(
    holdout_root=Path(r"D:/mktkb-p2-holdout/v2"),
    holdout_key_file=Path(r"D:/mktkb-p2-holdout/keys/v2.key"),
    project_total_limit_cny=ce.PROJECT_TOTAL_LIMIT_CNY,
)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def basename(path: str) -> str:
    return Path(str(path).replace("\\", "/")).name


def business_version_number(value) -> int:
    text = str(value or "")
    if not (text.startswith("V") and text[1:].isdigit()):
        raise ValueError("fixture_manifest_invalid")
    number = int(text[1:])
    if number <= 0:
        raise ValueError("fixture_manifest_invalid")
    return number


class Structure:
    """Public corpus identity table (same rules as the accepted R2 rescore baseline)."""

    def __init__(self) -> None:
        scenario_raw = SCENARIOS.read_bytes()
        ingest_raw = INGEST.read_bytes()
        source_map_raw = SOURCE_MAP.read_bytes()
        manifest_raw = MANIFEST.read_bytes()
        scenario = json.loads(scenario_raw)
        ingest = json.loads(ingest_raw)
        source_map = json.loads(source_map_raw)
        manifest = json.loads(manifest_raw)
        if str(scenario.get("schema_version")) != "p2-h2-scenarios/v0.2":
            raise ValueError("scenario_schema_invalid")
        if str(ingest.get("schema_version")) != "p2-ingest-plan/v0.1":
            raise ValueError("ingest_plan_invalid")
        if str(source_map.get("schema_version")) != "p2-holdout-source-map/v0.1":
            raise ValueError("source_map_invalid")

        documented = {
            str(code): {
                "base_doc_code": str(row["base_doc_code"]),
                "version_number": int(row["version_number"]),
            }
            for code, row in (source_map.get("sources") or {}).items()
        }
        normals = {str(row["id"]): row for row in manifest.get("normal_files") or ()}
        variants = {str(row["id"]): row for row in manifest.get("variants") or ()}
        self.rows = []
        for index, raw in enumerate(ingest.get("sources") or ()):
            path = str(raw["path"])
            file_code = basename(path).split("_", 1)[0]
            name = raw.get("name")
            product_name = str(name).strip() if isinstance(name, str) and name.strip() else basename(path)
            if file_code in documented:
                base = documented[file_code]["base_doc_code"]
                version = documented[file_code]["version_number"]
            elif file_code in normals:
                base = file_code
                version = business_version_number(normals[file_code].get("business_version"))
            elif file_code in variants:
                base = file_code
                version = business_version_number(variants[file_code].get("business_version"))
            else:
                raise ValueError("ingest_source_identity_unresolved")
            self.rows.append(
                {
                    "index": index,
                    "file_code": file_code,
                    "product_name": product_name,
                    "base_doc_code": base,
                    "version_number": version,
                }
            )
        self.documented_versions = documented
        self.aliases = {code: row["base_doc_code"] for code, row in documented.items()}
        self.scenarios = {}
        for row in scenario.get("scenarios") or ():
            scenario_id = str(row["scenario_id"])
            indices = [int(v) for v in row.get("source_indices") or ()]
            grouped = defaultdict(list)
            for index in indices:
                grouped[self.rows[index]["base_doc_code"]].append(self.rows[index])
            active = {}
            for base, group in grouped.items():
                top = max(r["version_number"] for r in group)
                winners = [r for r in group if r["version_number"] == top]
                if len(winners) != 1:
                    raise ValueError("active_version_ambiguous")
                active[base] = top
            self.scenarios[scenario_id] = active
        by_name = defaultdict(set)
        for row in self.rows:
            by_name[row["product_name"]].add(row["base_doc_code"])
        self.doc_index = {
            name: next(iter(bases)) for name, bases in by_name.items() if len(bases) == 1
        }
        self.ambiguous_names = sum(1 for bases in by_name.values() if len(bases) > 1)
        sources = manifest.get("sources") or {}
        self.record_index = [
            {
                "doc_code": str(row["file"]),
                "sheet": str(row["sheet"]),
                "row": int(row["row"]),
                "record_key": str(key),
                "business_version": str(row.get("business_version")),
            }
            for key, row in sources.items()
        ]
        self.business_versions = {
            str(code): str(row.get("business_version"))
            for code, row in {**normals, **variants}.items()
        }
        self.hashes = {
            "scenario_contract_sha256": sha256_bytes(scenario_raw),
            "ingest_plan_sha256": sha256_bytes(ingest_raw),
            "source_map_sha256": sha256_bytes(source_map_raw),
            "fixture_manifest_sha256": sha256_bytes(manifest_raw),
        }


def build_identity_rows(envelope: dict, structure: Structure, record_lookup: dict):
    """Mirror P3's record-identity projection over one old v0.2 turn envelope."""
    events = list((envelope.get("capture") or {}).get("events") or ())
    projection = dict(envelope.get("db_projection") or {})
    use_layers, use_malformed = p3._extract_use_layers(events, projection)
    candidate_layers, candidate_malformed = p3._extract_candidate_layers(events, projection)

    layers_by_ref: dict[str, set] = {}
    for name in p3.USE_LAYER_NAMES:
        if name == "direct_rag_fact_count":
            continue
        for ref in use_layers[name]["refs"]:
            layers_by_ref.setdefault(ref, set()).add(name)
    used_refs = sorted(layers_by_ref)
    unit_rows = {
        str(unit.get("unit_id")): unit
        for unit in projection.get("units") or ()
        if isinstance(unit, dict)
    }
    product_versions: dict[str, int] = {}
    runtime = dict(envelope.get("runtime_snapshot") or {})
    product = dict(runtime.get("product_response") or {})
    for row in product.get("sources") or ():
        if isinstance(row, dict) and row.get("source_id") is not None and type(row.get("version_number")) is int:
            product_versions[str(row["source_id"])] = int(row["version_number"])

    identity_rows = []
    version_rows = []
    for ref in used_refs:
        unit = unit_rows.get(ref)
        layers = sorted(layers_by_ref[ref])
        if unit is None:
            identity_rows.append(
                {
                    "source_ref": ref,
                    "layers": layers,
                    "unit_kind": "unresolved",
                    "locator_kind": "unavailable",
                    "doc_code": None,
                    "base_doc_code": None,
                    "sheet": None,
                    "row": None,
                    "record_key": None,
                    "record_code": None,
                    "business_version": None,
                    "version_number": None,
                    "record_level": False,
                    "entity_type": None,
                    "entity_key": None,
                    "entity_filters": {},
                    "entity_matchable": False,
                    "code": "runtime_unit_unresolved",
                    "entity_code": "entity_identity_unavailable",
                }
            )
            version_rows.append(
                {
                    "source_ref": ref,
                    "doc_code": None,
                    "version_label": None,
                    "runtime_version_number": None,
                    "product_version_number": product_versions.get(ref),
                    "code": "version_unresolved",
                }
            )
            continue
        locator_kind, structural_record = p3._locator_kind(unit)
        locator = dict(unit.get("locator") or {})
        doc_code = p3._doc_code_for(unit.get("document_name"), structure.doc_index)
        base_doc_code = p3._base_doc_code(doc_code, structure.aliases)
        sheet = locator.get("sheet") if isinstance(locator.get("sheet"), str) else None
        row_value = locator.get("row") if type(locator.get("row")) is int else None
        record_key = None
        record_code = None
        record_level = False
        business_version = None
        if not structural_record:
            code = "runtime_unit_not_record_level"
            if locator_kind != "record":
                sheet = None
                row_value = None
        elif doc_code is None:
            code = "runtime_doc_code_unresolved"
        else:
            entry = record_lookup.get((str(base_doc_code), str(sheet), int(row_value)))
            if entry is None:
                code = "record_row_not_in_record_index"
            else:
                record_key = str(entry["record_key"])
                record_code = record_key
                record_level = True
                business_version = entry.get("business_version") or structure.business_versions.get(
                    str(base_doc_code)
                )
                code = "record_row_reverse_lookup"
        if business_version is None and base_doc_code is not None:
            business_version = structure.business_versions.get(str(base_doc_code))
        version_number = unit.get("version_number")
        if type(version_number) is not int:
            version_number = None
        if not record_level:
            record_key = None
            record_code = None
        entity_type = unit.get("entity_type")
        entity_key = unit.get("entity_key")
        entity_filters = {
            str(k): str(v) for k, v in dict(unit.get("entity_filters") or {}).items()
        }
        identity_rows.append(
            {
                "source_ref": ref,
                "layers": layers,
                "unit_kind": str(unit.get("kind") or "unknown"),
                "locator_kind": locator_kind,
                "doc_code": doc_code,
                "base_doc_code": base_doc_code,
                "sheet": sheet,
                "row": row_value,
                "record_key": record_key,
                "record_code": record_code,
                "business_version": business_version,
                "version_number": version_number,
                "record_level": record_level,
                "entity_type": None if entity_type is None else str(entity_type),
                "entity_key": None if entity_key is None else str(entity_key),
                "entity_filters": entity_filters,
                "entity_matchable": p3._compute_entity_matchable(
                    entity_type, entity_key, entity_filters
                ),
                "code": code,
                "entity_code": p3._entity_code(
                    entity_type, entity_key, entity_filters, unit_resolved=True
                ),
            }
        )
        product_version = product_versions.get(ref)
        if version_number is None:
            version_code = "version_unresolved"
        elif product_version is not None and product_version != version_number:
            version_code = "version_mismatch"
        else:
            version_code = "version_observed"
        version_rows.append(
            {
                "source_ref": ref,
                "doc_code": doc_code,
                "version_label": business_version,
                "runtime_version_number": version_number,
                "product_version_number": product_version,
                "code": version_code,
            }
        )
    return identity_rows, use_layers, candidate_layers, version_rows


def merge_layers(layer_sets: list[dict]) -> dict:
    merged = {}
    for name in p3.USE_LAYER_NAMES:
        observed = bool(layer_sets) and all(layer[name]["observed"] for layer in layer_sets)
        count = sum(layer[name]["count"] for layer in layer_sets)
        refs = sorted({ref for layer in layer_sets for ref in layer[name]["refs"]})
        merged[name] = {"observed": observed, "count": count, "refs": refs}
    return merged


def merge_candidates(layer_sets: list[dict]) -> dict:
    merged = {}
    for name in p3.CANDIDATE_LAYER_NAMES:
        observed = bool(layer_sets) and all(layer[name]["observed"] for layer in layer_sets)
        count = sum(layer[name]["count"] for layer in layer_sets)
        refs = sorted({ref for layer in layer_sets for ref in layer[name]["refs"]})
        truncated = any(layer[name]["truncated"] for layer in layer_sets)
        merged[name] = {
            "observed": observed,
            "count": count,
            "refs": refs,
            "truncated": truncated,
        }
    return merged


def to_record_views(rows: list[dict]) -> tuple:
    return tuple(
        ax.SnapshotRecordView(
            source_ref=row["source_ref"],
            layers=tuple(row["layers"]),
            locator_kind=row["locator_kind"],
            doc_code=row["doc_code"],
            base_doc_code=row["base_doc_code"],
            sheet=row["sheet"],
            row=row["row"],
            record_key=row["record_key"],
            record_code=row["record_code"],
            business_version=row["business_version"],
            version_number=row["version_number"],
            record_level=row["record_level"],
            entity_type=row["entity_type"],
            entity_key=row["entity_key"],
            entity_filters=dict(row["entity_filters"]),
            entity_matchable=row["entity_matchable"],
            code=row["code"],
            entity_code=row["entity_code"],
        )
        for row in rows
    )


def snapshot_view(
    *,
    run_id: str,
    scenario_id: str,
    records: tuple,
    use_layers: dict,
    candidate_layers: dict,
    version_rows: list[dict],
    as_of: str | None,
    as_of_ambiguous: bool,
    complete: bool,
    assume_v03: bool,
) -> ax.SnapshotView:
    turn_status = ("complete" if complete else "partial") if assume_v03 else "unavailable"
    temporal = ax.TemporalView(
        availability="observed" if as_of else ("not_observed" if not as_of_ambiguous else "partial"),
        as_of=as_of,
        as_of_source="plan_observed" if as_of else "unavailable",
        document_versions=tuple(
            ax.DocumentVersionView(
                source_ref=row["source_ref"],
                doc_code=row["doc_code"],
                version_label=row["version_label"],
                runtime_version_number=row["runtime_version_number"],
                product_version_number=row["product_version_number"],
                code=row["code"],
            )
            for row in version_rows
        ),
        code=(
            "effective_temporal_observed"
            if as_of and all(row["code"] == "version_observed" for row in version_rows)
            else ("effective_as_of_ambiguous" if as_of_ambiguous else "effective_temporal_partial")
        ),
        baseline_used_as_effective=False,
    )
    empty_use = ax.EmptyUseView(
        turn_status=turn_status,
        all_use_layers_observed=all(layer["observed"] for layer in use_layers.values()),
        empty_set_candidate=all(layer["observed"] for layer in use_layers.values())
        and not any(layer["count"] for layer in use_layers.values()),
        code="empty_use_input_complete_empty"
        if all(layer["observed"] for layer in use_layers.values())
        and not any(layer["count"] for layer in use_layers.values())
        else "empty_use_input_nonempty",
        use_layers=use_layers,
        candidate_layers=candidate_layers,
    )
    return ax.SnapshotView(
        schema_version="p2-runtime-identity-snapshot/v0.1",
        contract_version="p2-hard-evidence-capture-identity/v0.3",
        fixture_kind="live_h2",
        source_completeness="complete" if complete else "incomplete",
        binding={"run_id": run_id, "scenario_id": scenario_id},
        turn_ref={},
        records=records,
        summary={},
        temporal=temporal,
        empty_use=empty_use,
    )


def frozen_refs_for(projection: dict, case_index: int, axis_name: str) -> dict:
    by_collection: dict[str, list] = {}
    for row in projection.get("record_identities") or ():
        if int(row.get("case_index", -1)) != case_index:
            continue
        if str(row.get("axis")) != axis_name:
            continue
        collection = str(row.get("collection"))
        index = int(row.get("index"))
        rows = by_collection.setdefault(collection, [])
        while len(rows) <= index:
            rows.append({})
        code = row.get("record_code")
        rows[index] = {"record_code": code if isinstance(code, str) and code else None}
    return by_collection


def classify_key_space(records: tuple, axis) -> tuple[str, dict, list]:
    matchable = [t for t in axis.targets if t.matchable]
    counts: Counter = Counter()
    codes: Counter = Counter()
    for rec in records:
        if not rec.entity_type or not rec.entity_key:
            counts["identity_absent"] += 1
            codes["identity_absent"] += 1
            continue
        if ax._runtime_key_space(rec) == "document":
            counts["document_level"] += 1
            codes["document_level"] += 1
            continue
        kind, code = ax._match_entity_row(rec, matchable)
        counts[kind] += 1
        codes[f"{kind}:{code}" if code else kind] += 1
    if counts["incompatible"]:
        verdict = "entity_key_space_incompatible"
    elif not records:
        verdict = "missing_v03_field"
    elif counts["matched"] and not (counts["identity_absent"] or counts["document_level"]):
        verdict = "aligned"
    elif counts["mismatch"] and not (counts["identity_absent"] or counts["document_level"]):
        verdict = "aligned"
    else:
        verdict = "other_fixed_code"
    return verdict, dict(sorted(counts.items())), [
        f"{name}:{count}" for name, count in sorted(codes.items())
    ]


def main() -> int:
    key = p2_dataset._read_key(Path(r"D:/mktkb-p2-holdout/keys/v2.key"))
    bundle = ce.load_private_bundle({}, PATHS, runtime=RUNTIME)
    structure = Structure()
    raw_contract = CONTRACT.read_bytes()
    contract_payload = json.loads(Fernet(key).decrypt(raw_contract).decode("utf-8"))
    contract_view = ax.load_contract_v2(
        contract_payload,
        expected_schema_sha256=sha256_bytes(
            (ROOT / "docs/evaluation/q1a-scope-targets-contract-v2.md").read_bytes()
        ),
    )
    record_lookup = p3._normalize_record_index(structure.record_index)

    # ---- collect per-case evidence across all runs ---------------------------
    case_turns: dict[str, list] = defaultdict(list)
    run_meta: dict[str, dict] = {}
    for run_dir in sorted(OLD_RUN.glob("runs/r*")):
        ev_key = (run_dir / "ev.key").read_bytes()
        plan = json.loads((run_dir / "out/controlled/case-plan.json").read_text(encoding="utf-8"))
        envelope0 = None
        for case in plan.get("cases") or ():
            for turn in case.get("turns") or ():
                if turn.get("status") != "executed" or not turn.get("evidence_file"):
                    continue
                name = Path(str(turn["evidence_file"])).name
                matches = sorted((run_dir / "evidence").glob(f"*/{name}"))
                if not matches:
                    raise FileNotFoundError(f"evidence_turn_missing:{run_dir.name}")
                envelope = p2_evidence_io.read_encrypted_evidence(matches[0], key=ev_key)
                envelope0 = envelope0 or envelope
                case_turns[str(case["case_id"])].append(
                    {
                        "run": run_dir.name,
                        "scenario_id": str(
                            (envelope.get("run_binding") or {}).get("scenario_id")
                            or (envelope.get("bindings") or {}).get("scenario_id")
                        ),
                        "envelope": envelope,
                    }
                )
        if envelope0 is not None:
            rb = envelope0.get("run_binding") or {}
            run_meta[run_dir.name] = {
                "run_id": str(rb.get("run_id") or ""),
                "scenario_id": str(rb.get("scenario_id") or ""),
            }

    # ---- build per-case v0.3-style snapshot material -------------------------
    case_material = {}
    for case_id, turns in case_turns.items():
        records_by_ref: dict[str, dict] = {}
        layer_sets = []
        candidate_sets = []
        version_by_ref: dict[str, dict] = {}
        as_of_values = set()
        plan_ok = True
        complete = True
        frozen_proofs = []
        for turn in turns:
            envelope = turn["envelope"]
            identity_rows, use_layers, candidate_layers, version_rows = build_identity_rows(
                envelope, structure, record_lookup
            )
            layer_sets.append(use_layers)
            candidate_sets.append(candidate_layers)
            for row in identity_rows:
                records_by_ref.setdefault(row["source_ref"], row)
            for row in version_rows:
                version_by_ref.setdefault(row["source_ref"], row)
            events = list((envelope.get("capture") or {}).get("events") or ())
            plans = [e.get("payload") or {} for e in events if str(e.get("kind")) == "plan_observed"]
            if len(plans) == 1:
                value = plans[0].get("as_of")
                if isinstance(value, str) and value:
                    as_of_values.add(value)
            else:
                plan_ok = False
            complete = complete and str((envelope.get("completeness") or {}).get("status")) == "complete"
            try:
                proven, reason = hard._empty_use_scope_proof(envelope)
            except Exception:  # noqa: BLE001
                proven, reason = False, "primitive_raised"
            frozen_proofs.append((bool(proven), str(reason)))
        merged_use = merge_layers(layer_sets)
        unobserved = sorted(name for name, layer in merged_use.items() if not layer["observed"])
        case_material[case_id] = {
            "records": records_by_ref,
            "use_layers": merged_use,
            "candidate_layers": merge_candidates(candidate_sets),
            "version_rows": list(version_by_ref.values()),
            "as_of": next(iter(as_of_values)) if plan_ok and len(as_of_values) == 1 else None,
            "as_of_ambiguous": (not plan_ok) or len(as_of_values) > 1,
            "complete": complete,
            "unobserved_layers": unobserved,
            "frozen_proofs": frozen_proofs,
            "turns": turns,
        }

    # ---- drive the adapter per contract case ---------------------------------
    key_space_counts: Counter = Counter()
    match_code_hist: Counter = Counter()
    target_entity_types: Counter = Counter()
    target_key_spaces: Counter = Counter()
    cross_applicability: Counter = Counter()
    stale_applicability: Counter = Counter()
    cross_states_v02: Counter = Counter()
    cross_states_v03: Counter = Counter()
    stale_states_v02: Counter = Counter()
    stale_states_v03: Counter = Counter()
    per_axis_rows = []
    case_level = []
    used_ref_total = 0
    turns_total = 0
    # Opaque axis labels: order by SHA256(case_id) so no label encodes a case number.
    label_by_case = {
        case.case_id: f"N{rank + 1:02d}"
        for rank, case in enumerate(
            sorted(
                contract_view.cases.values(),
                key=lambda c: hashlib.sha256(c.case_id.encode("utf-8")).hexdigest(),
            )
        )
    }
    for case in sorted(contract_view.cases.values(), key=lambda c: c.case_index):
        material = case_material.get(case.case_id)
        if material is None:
            raise RuntimeError("case_not_executed")
        records = to_record_views(list(material["records"].values()))
        used_ref_total += len(records)
        turns_total += len(material["turns"])
        run_id = run_meta.get(material["turns"][0]["run"], {}).get("run_id", "")
        refs = frozen_refs_for(contract_view.projection, case.case_index, "stale_source")
        results = {}
        for assume_v03 in (False, True):
            snap = snapshot_view(
                run_id=run_id,
                scenario_id=case.scenario_id,
                records=records,
                use_layers=material["use_layers"],
                candidate_layers=material["candidate_layers"],
                version_rows=material["version_rows"],
                as_of=material["as_of"],
                as_of_ambiguous=material["as_of_ambiguous"],
                complete=material["complete"],
                assume_v03=assume_v03,
            )
            results[assume_v03] = (
                ax.determine_cross_entity(contract_view, case, snap),
                ax.determine_stale_source(contract_view, case, snap, frozen_refs=refs),
            )
        cross_v02, stale_v02 = results[False]
        cross_v03, stale_v03 = results[True]
        axis = case.axes["cross_entity"]
        verdict, counts, codes = classify_key_space(records, axis)
        matchable = [t for t in axis.targets if t.matchable]
        for target in axis.targets:
            target_entity_types[target.entity_type] += 1
            target_key_spaces[ax._target_key_space(target)] += 1
        for code in codes:
            match_code_hist[code] += 1
        cross_applicability[axis.applicability] += 1
        stale_applicability[case.axes["stale_source"].applicability] += 1
        cross_states_v02[(cross_v02.state, cross_v02.reason)] += 1
        cross_states_v03[(cross_v03.state, cross_v03.reason)] += 1
        stale_states_v02[(stale_v02.state, stale_v02.reason)] += 1
        stale_states_v03[(stale_v03.state, stale_v03.reason)] += 1
        row = {
            "label": label_by_case[case.case_id],
            "criterion": axis.criterion,
            "applicability": axis.applicability,
            "targets": len(axis.targets),
            "matchable_targets": len(matchable),
            "target_granularities": sorted({t.granularity for t in axis.targets}),
            "target_entity_types": sorted({t.entity_type for t in axis.targets}),
            "target_key_spaces": sorted({ax._target_key_space(t) for t in axis.targets}),
            "turns": len(material["turns"]),
            "runs": sorted({turn["run"] for turn in material["turns"]}),
            "records_used": len(records),
            "record_level_used": sum(1 for r in records if r.record_level),
            "record_locator_kinds": dict(sorted(Counter(r.locator_kind for r in records).items())),
            "unobserved_use_layers": material["unobserved_layers"],
            "key_space_verdict": verdict,
            "key_space_counts": counts,
            "match_codes": codes,
            "cross_entity_v02": {"state": cross_v02.state, "reason": cross_v02.reason},
            "cross_entity_v03": {"state": cross_v03.state, "reason": cross_v03.reason},
            "stale_v02": {"state": stale_v02.state, "reason": stale_v02.reason},
            "stale_v03": {"state": stale_v03.state, "reason": stale_v03.reason},
            "cross_audit_v03": sorted({item.split(":", 1)[-1] for item in cross_v03.evidence}),
            "stale_audit_v03": sorted({item.split(":", 1)[-1] for item in stale_v03.evidence}),
            "frozen_empty_proof": any(flag for flag, _ in material["frozen_proofs"]),
        }
        per_axis_rows.append(row)
        if matchable:
            key_space_counts[verdict] += 1
        case_level.append(
            {
                "cross": cross_v03.state,
                "stale": stale_v03.state,
                "cross_pass": cross_v03.state in ("passed", "not_applicable")
                and cross_v03.reason != "shared_background_runtime_identity_unavailable",
                "stale_pass": stale_v03.state in ("passed", "not_applicable"),
            }
        )

    matchable_axes = [r for r in per_axis_rows if r["matchable_targets"] > 0]
    cross_ok = sum(1 for row in per_axis_rows if row["cross_entity_v03"]["state"] == "passed")
    stale_ok = sum(1 for row in per_axis_rows if row["stale_v03"]["state"] == "passed")
    realistic_case_pass = sum(
        1 for row in case_level if row["cross"] == "passed" and row["stale"] == "passed"
    )
    # Optimistic: all 16 matchable axes key-align (assume the 3 empty-use turns become fully
    # observed under a future capture) and stale empty-use axes pass; every other blocker stays.
    optimistic_cross_judged = len(matchable_axes)
    optimistic_cross_pass = len(matchable_axes)
    empty_axes = [r for r in matchable_axes if r["records_used"] == 0]
    optimistic_stale_judged = len(empty_axes)
    optimistic_stale_pass = len(empty_axes)
    optimistic_case_pass = len(empty_axes)

    report = {
        "probe": "01-forecast",
        "inputs": {
            "contract_ciphertext_sha256": sha256_bytes(raw_contract),
            "contract_ciphertext_bytes": len(raw_contract),
            "contract_schema_sha256": sha256_bytes(
                (ROOT / "docs/evaluation/q1a-scope-targets-contract-v2.md").read_bytes()
            ),
            "old_run_binding_payload_sha256": "291cfec9d99446c88f0063d533c92632cef15594c1f6ce3da2269cef98ae65d4",
            "old_evidence_runs": sorted(run_meta),
            "public_structure_hashes": structure.hashes,
            "doc_index_entries": len(structure.doc_index),
            "doc_index_ambiguous_names": structure.ambiguous_names,
            "record_index_entries": len(structure.record_index),
        },
        "universe": {
            "cases": len(contract_view.cases),
            "cases_with_executed_evidence": len(case_material),
            "turns": turns_total,
            "used_unit_refs_unique_per_case": used_ref_total,
            "matchable_cross_entity_axes": len(matchable_axes),
            "cross_applicability": dict(sorted(cross_applicability.items())),
            "stale_applicability": dict(sorted(stale_applicability.items())),
            "target_entity_types": dict(sorted(target_entity_types.items())),
            "target_key_spaces": dict(sorted(target_key_spaces.items())),
            "cross_entity_states_v02": {
                f"{s}|{r}": c for (s, r), c in sorted(cross_states_v02.items())
            },
            "cross_entity_states_v03": {
                f"{s}|{r}": c for (s, r), c in sorted(cross_states_v03.items())
            },
            "stale_source_states_v02": {
                f"{s}|{r}": c for (s, r), c in sorted(stale_states_v02.items())
            },
            "stale_source_states_v03": {
                f"{s}|{r}": c for (s, r), c in sorted(stale_states_v03.items())
            },
            "match_codes": dict(sorted(match_code_hist.items())),
        },
        "key_space": {
            "counts": dict(sorted(key_space_counts.items())),
            "aligned": key_space_counts.get("aligned", 0),
            "entity_key_space_incompatible": key_space_counts.get("entity_key_space_incompatible", 0),
            "missing_v03_field": key_space_counts.get("missing_v03_field", 0),
            "other_fixed_code": key_space_counts.get("other_fixed_code", 0),
            "axes": [
                {
                    "label": row["label"],
                    "criterion": row["criterion"],
                    "matchable_targets": row["matchable_targets"],
                    "target_granularities": row["target_granularities"],
                    "target_entity_types": row["target_entity_types"],
                    "target_key_spaces": row["target_key_spaces"],
                    "turns": row["turns"],
                    "runs": row["runs"],
                    "records_used": row["records_used"],
                    "verdict": row["key_space_verdict"],
                    "record_classes": row["key_space_counts"],
                    "match_codes": row["match_codes"],
                    "unobserved_use_layers": row["unobserved_use_layers"],
                    "cross_state": row["cross_entity_v03"]["state"],
                    "cross_reason": row["cross_entity_v03"]["reason"],
                    "stale_state": row["stale_v03"]["state"],
                    "stale_reason": row["stale_v03"]["reason"],
                }
                for row in matchable_axes
            ],
        },
        "v03_dependency": {
            "cross_entity": {
                "axes_not_depending_on_v03_fields": sum(
                    1 for row in matchable_axes if row["key_space_verdict"] == "aligned"
                ),
                "axes_depending_on_empty_use_input": sum(
                    1 for row in matchable_axes if row["records_used"] == 0
                ),
                "axes_depending_on_record_code_or_doc_code": sum(
                    1
                    for row in matchable_axes
                    if any("doc_code" in code for code in row["cross_audit_v03"])
                ),
            },
            "stale_source": {
                "axes_ref_record_identity_resolved": sum(
                    1 for row in per_axis_rows if row["stale_v03"]["reason"] == "stale_lifecycle_evidence_missing"
                )
                + sum(
                    1 for row in per_axis_rows if row["stale_v03"]["reason"] == "empty_set_not_proven"
                    and row["stale_audit_v03"]
                ),
                "axes_depending_on_record_code_and_as_of": sum(
                    1 for row in per_axis_rows if row["stale_v03"]["reason"] == "stale_lifecycle_evidence_missing"
                ),
                "axes_structurally_unresolved_refs": sum(
                    1
                    for row in per_axis_rows
                    if row["stale_v03"]["reason"] in ("stale_positive_ref_not_record_level", "stale_no_positive_refs")
                ),
                "axes_unknown_due_to_lifecycle_gap": sum(
                    1 for row in per_axis_rows if row["stale_v03"]["reason"] == "stale_lifecycle_evidence_missing"
                ),
            },
        },
        "forecast": {
            "realistic": {
                "cross_entity_judged": 30 - sum(
                    1 for row in per_axis_rows if row["cross_entity_v03"]["state"] == "unknown"
                ),
                "cross_entity_passed": cross_ok,
                "stale_source_judged": 30 - sum(
                    1 for row in per_axis_rows if row["stale_v03"]["state"] == "unknown"
                ),
                "stale_source_passed": stale_ok,
                "case_level_pass": realistic_case_pass,
            },
            "optimistic": {
                "assumption": "v0.3 capture complete + all 16 matchable axes key-align + empty-use turns fully observed; contract/adapter unchanged",
                "cross_entity_judged": optimistic_cross_judged,
                "cross_entity_passed": optimistic_cross_pass,
                "stale_source_judged": optimistic_stale_judged,
                "stale_source_passed": optimistic_stale_pass,
                "case_level_pass": optimistic_case_pass,
            },
            "empty_use_axes": [row["label"] for row in empty_axes],
        },
        "axes": per_axis_rows,
    }
    (OUT / "01-forecast.out.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(
        {k: report[k] for k in ("inputs", "universe", "key_space", "v03_dependency", "forecast")},
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

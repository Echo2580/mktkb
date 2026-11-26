"""Q1a-3-R2 共享投影层：真实 H2 只读证据 -> Q1a-1 / Q1a-1b 的显式只读视图。

R2 相对 R1 的四处纠正（经理 2026-11-14 裁定）：
A. `VersionBinding` 从批准来源确定性推导：scenario 合同（生效上传集） + 原 12-source
   ingest plan（上传顺序） + source map（`base_doc_code`/`version_number`） + 公开
   fixture manifest（正常文件/独立变体业务版本）。不硬编码字面版本号。
B. `document_codes` 投影改为**产品身份**规则：产品文档名 = ingest `name`（若有）否则
   path basename；再按 (产品名, unit.version_number) 反查唯一 ingest source，取该 source
   的文件码（变体码/文档槽码）。这样首导入变体(v1) 与正常文件(v2) 即使 display name 相同也能区分。
C. 只读 import C 冻结 `p2_hard_evidence._empty_use_scope_proof` 作为**严格空集原语**，
   只用于给 Q1a-1b 的 `empty_scope_proven` 提供 bool/reason；不生成旧 verdict、不替代
   matcher/N/A 判定、不改该模块一字节（前后 SHA 相等）。
D. `shared_background` 仍为空元组：公开语料结构给不出冻结 unit_id/version_id，伪造即越界；
   保留 unknown 并给固定 code。

边界（硬约束）：
- 只经既有受控 loader 解封：`tools/p2_h2_controlled_execute.py::load_private_bundle`、
  `p2_dataset.load_p2_dataset`、`p2_holdout_scenarios.load_scenario_contract`、
  `p2_evidence_io.read_encrypted_evidence`。key 只在进程内存。
- 只投影确定性结构字段（身份/owner/版本/日期/实体/引用/状态码/计数）。
  `final_text` 仅供 Q1a-1 已定义的确定性禁值子串判定与 C 原语的模板恒等判定使用，
  绝不打印/落盘/公开/回传。
- **不构造 `OldCardCase`**：旧逐题四轴值在本包标 `NOT_AVAILABLE`；本层只产出新侧视图。
- 所有适配点做**显式 required 校验**（缺键/坏类型 -> 固定 ProjectionError 码），
  禁止 `getattr(..., default)` 式 fail-open。
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[6]
for path in (HERE, HERE.parent / "evidence-r1", REPO / "backend" / "src", REPO / "tools"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import _common_r1 as R1  # noqa: E402

# 复用 R1 的固定路径、期望绑定与严格校验原语；R2 不重定义 key/密文位置。
ProjectionError = R1.ProjectionError
need = R1.need
need_map = R1.need_map
need_list = R1.need_list
need_str = R1.need_str
need_opt_str = R1.need_opt_str
need_int = R1.need_int
need_bool = R1.need_bool
sha256_hex = R1.sha256_hex
canonical_json_bytes = R1.canonical_json_bytes
strict_json = R1.strict_json
load_bundle = R1.load_bundle
load_contract_payload = R1.load_contract_payload

REPO_ROOT = R1.REPO
OLD_RUN = R1.OLD_RUN
HOLDOUT_ROOT = R1.HOLDOUT_ROOT
HOLDOUT_KEY = R1.HOLDOUT_KEY
CONTRACT_CIPHER = R1.CONTRACT_CIPHER
CUSTODY = R1.CUSTODY
OUT_PRIVATE_DIR = R1.OUT_PRIVATE_DIR
OUT_PRIVATE_FILE = OUT_PRIVATE_DIR / "rescore-detail-r2.fernet"
PUBLIC_AGGREGATE = HERE.parent / "rescore-aggregate-r2.json"
PUBLIC_REPORT = HERE.parent / "rescore-report-r2.md"
SCENARIO_JSON = REPO_ROOT / "docs/evaluation/p2-h2-scenarios-v0_2.json"
INGEST_PLAN = REPO_ROOT / "docs/reports/OBS-EVAL/P2/T207/PM/T207-ingest-plan-H2.json"
SOURCE_MAP = REPO_ROOT / "docs/evaluation/p2-holdout-v2.source-map.json"
FIXTURE_MANIFEST = REPO_ROOT / "fixtures/acceptance/manifest.json"
HARD_EVIDENCE = REPO_ROOT / "backend/src/mktkb/evaluation/p2_hard_evidence.py"

EXPECTED = dict(R1.EXPECTED)
AUTHORITATIVE_REASON_CODES_18 = R1.AUTHORITATIVE_REASON_CODES_18

@dataclass(frozen=True)
class TurnProjection:
    """一轮的只读投影（R2：额外携带 C 冻结空集原语结果）。"""

    turn_index: int
    status: str
    gate: str | None
    units: tuple[Any, ...]
    final_kind: str | None
    final_text: str | None
    events: tuple[Mapping[str, Any], ...] = ()
    projection: Mapping[str, Any] = field(default_factory=dict)
    envelope_bindings: Mapping[str, str] = field(default_factory=dict)
    completeness_status: str | None = None
    authenticated_user_id: str | None = None
    evidence_turn_index: int | None = None
    empty_scope_ok: bool = False
    empty_scope_reason: str = ""
    empty_scope_primitive_raised: bool = False


safety_turn_views = R1.safety_turn_views
cross_user_view = R1.cross_user_view


# --------------------------------------------------------------------------- #
# 公开语料结构：source 身份 / scenario active 版本 / ref 版本绑定
# --------------------------------------------------------------------------- #


def _basename(path: str) -> str:
    return Path(path.replace("\\", "/")).name


def _business_version_number(value: Any) -> int:
    text = str(value or "")
    need(text.startswith("V") and text[1:].isdigit(), "fixture_manifest_invalid")
    number = int(text[1:])
    need(number > 0, "fixture_manifest_invalid")
    return number


@dataclass(frozen=True)
class SourceRow:
    """一个 ingest source 的公开身份（全部来自批准输入，无字面版本硬编码）。"""

    index: int
    file_code: str          # 文件码：变体码/文档槽码（frozen ref 的 doc_code 命名空间）
    product_name: str       # 产品侧文档名：name 优先，否则 path basename
    base_doc_code: str      # 逻辑文档槽：source-map 变体→对应 base 槽；正常文件→自身
    version_number: int     # 版本身份：source_map 或 fixture manifest business_version
    origin: str             # source_map | fixture_manifest_normal | fixture_manifest_variant


@dataclass(frozen=True)
class PublicStructure:
    rows: tuple[SourceRow, ...]
    scenario_ids: tuple[str, ...]
    active: Mapping[str, Mapping[str, Mapping[str, Any]]]
    documented_versions: Mapping[str, Mapping[str, int]]
    hashes: Mapping[str, str]
    binding_rule: str

    def active_version(self, scenario_id: str, base_doc_code: str) -> int | None:
        entry = self.active.get(scenario_id, {}).get(base_doc_code)
        return None if entry is None else int(entry["version_number"])

    def version_binding(self, scenario_id: str, ref: Mapping[str, Any]) -> tuple[Any | None, str, Mapping[str, Any]]:
        """ref -> (VersionBinding | None, 固定状态码, 归一化 ref)。

        归一化只把 source-map 变体码映射到 `base_doc_code`，版本号仍来自
        ref 的显式 source-map 身份；这是 source map 的既有语义，不改冻结数据集。
        """
        from mktkb.evaluation.p2_evidence_rescore import VersionBinding

        code = ref.get("doc_code")
        need(isinstance(code, str) and bool(code.strip()), "ref_invalid")
        active = self.active.get(scenario_id)
        need(active is not None, "scenario_unknown")
        if code in self.documented_versions:
            # 显式 source-map 变体码：ref 自身钉死了版本；只有该版本在
            # 本 scenario 成为 active 版本时才可绑定，否则 0 个 active -> unresolved。
            # 未 active 时**不归一化**，避免与同 record/locator 的 base-doc ref 冲突
            # （历史变体与正常文件是同一产品身份但不同版本意图；冲突会误伤正常文件绑定）。
            base = self.documented_versions[code]["base_doc_code"]
            ref_version = self.documented_versions[code]["version_number"]
            entry = active.get(base)
            if entry is None:
                return None, "doc_not_active_in_scenario", dict(ref)
            if int(entry["version_number"]) != ref_version:
                return None, "ref_version_not_active", dict(ref)
            normalized = {**dict(ref), "doc_code": base}
            return VersionBinding(version_number=ref_version, basis="source_map"), "bound_source_map", normalized
        if code in active:
            entry = active[code]
            return (
                VersionBinding(version_number=int(entry["version_number"]), basis=str(entry["basis"])),
                "bound_active",
                dict(ref),
            )
        if code in {row.file_code for row in self.rows}:
            return None, "doc_not_uploaded_in_scenario", dict(ref)
        return None, "doc_code_not_in_public_structure", dict(ref)

    def doc_code_for_unit(self, document_name: str | None, version_number: int | None) -> tuple[str | None, str]:
        """(产品文档名, unit.version_number) -> 唯一**逻辑文档槽**（base_doc_code）。

        产品侧对同一文档槽的各版本使用同一 display name，版本由
        `unit.version_number` 区分；变体文件名若出现则经 source map 归一到对应
        base 槽。同一产品名必须只对应一个 base_doc_code；>1 -> ambiguous，0 -> unresolved。
        **不用**“只剩一个版本”或答案反推补身份。
        """
        if document_name is None or not document_name.strip():
            return None, "document_name_missing"
        candidates = [row for row in self.rows if row.product_name == document_name]
        if candidates:
            bases = {row.base_doc_code for row in candidates}
            if len(bases) == 1:
                return bases.pop(), "resolved_by_product_name"
            return None, "ambiguous_base_doc_code"
        prefix = document_name.split("_", 1)[0]
        if prefix in self.documented_versions:
            return self.documented_versions[prefix]["base_doc_code"], "resolved_by_source_map_prefix"
        if prefix in {row.file_code for row in self.rows}:
            return prefix, "resolved_by_file_code_prefix"
        return None, "document_name_not_in_public_ingest"

    def summary(self) -> dict[str, Any]:
        """公开侧只给计数/来源 hash，不落文档名或 doc_code 字面值。"""
        latest = {}
        for scenario_id in self.scenario_ids:
            entry = self.active[scenario_id]
            latest[scenario_id] = {
                "active_doc_count": len(entry),
                "active_version_multiset": sorted(int(row["version_number"]) for row in entry.values()),
                "ambiguous_count": 0,
            }
        return {
            "source_rows": len(self.rows),
            "source_origin_counts": {
                origin: sum(1 for row in self.rows if row.origin == origin)
                for origin in sorted({row.origin for row in self.rows})
            },
            "scenario_count": len(self.scenario_ids),
            "active_by_scenario": latest,
            "active_table_canonical_sha256": sha256_hex(
                canonical_json_bytes(
                    {
                        scenario_id: {
                            code: dict(entry) for code, entry in self.active[scenario_id].items()
                        }
                        for scenario_id in self.scenario_ids
                    }
                )
            ),
            "input_hashes": dict(self.hashes),
            "binding_rule": self.binding_rule,
            "hardcoded_version_literals": 0,
        }


def load_public_structure() -> PublicStructure:
    """读取并交叉校验 4 份公开件，推导 source 身份与 scenario active 版本表。"""
    scenario_raw = SCENARIO_JSON.read_bytes()
    ingest_raw = INGEST_PLAN.read_bytes()
    source_map_raw = SOURCE_MAP.read_bytes()
    manifest_raw = FIXTURE_MANIFEST.read_bytes()
    scenario = strict_json(scenario_raw)
    ingest = strict_json(ingest_raw)
    source_map = strict_json(source_map_raw)
    manifest = strict_json(manifest_raw)

    need(str(scenario.get("schema_version")) == "p2-h2-scenarios/v0.2", "scenario_schema_invalid")
    need(
        str(scenario.get("ingest_plan_sha256")) == sha256_hex(ingest_raw),
        "ingest_plan_sha_mismatch",
    )
    need(str(ingest.get("schema_version")) == "p2-ingest-plan/v0.1", "ingest_plan_invalid")
    need(str(source_map.get("schema_version")) == "p2-holdout-source-map/v0.1", "source_map_invalid")

    map_rows = need_map(source_map.get("sources"), "source_map_invalid")
    documented: dict[str, dict[str, Any]] = {}
    for code, row in map_rows.items():
        entry = need_map(row, "source_map_invalid")
        documented[str(code)] = {
            "base_doc_code": need_str(entry.get("base_doc_code"), "source_map_invalid"),
            "version_number": need_int(entry.get("version_number"), "source_map_invalid", minimum=1),
        }
    normals = {str(row["id"]): row for row in need_list(manifest.get("normal_files"), "manifest_invalid")}
    variants = {str(row["id"]): row for row in need_list(manifest.get("variants"), "manifest_invalid")}

    rows: list[SourceRow] = []
    for index, raw in enumerate(need_list(ingest.get("sources"), "ingest_plan_invalid")):
        entry = need_map(raw, "ingest_plan_invalid")
        path = need_str(entry.get("path"), "ingest_plan_invalid")
        file_code = _basename(path).split("_", 1)[0]
        need(bool(file_code), "ingest_plan_invalid")
        name = entry.get("name")
        product_name = (
            str(name).strip()
            if isinstance(name, str) and name.strip()
            else _basename(path)
        )
        if file_code in documented:
            base = documented[file_code]["base_doc_code"]
            version = documented[file_code]["version_number"]
            origin = "source_map"
        elif file_code in normals:
            base = file_code
            version = _business_version_number(normals[file_code].get("business_version"))
            origin = "fixture_manifest_normal"
        elif file_code in variants:
            base = file_code
            version = _business_version_number(variants[file_code].get("business_version"))
            origin = "fixture_manifest_variant"
        else:
            raise ProjectionError("ingest_source_identity_unresolved")
        rows.append(
            SourceRow(
                index=index,
                file_code=file_code,
                product_name=product_name,
                base_doc_code=base,
                version_number=version,
                origin=origin,
            )
        )

    scenario_rows = need_list(scenario.get("scenarios"), "scenario_invalid")
    scenario_ids = tuple(need_str(row.get("scenario_id"), "scenario_invalid") for row in scenario_rows)
    need(len(set(scenario_ids)) == len(scenario_ids), "scenario_invalid")
    active: dict[str, dict[str, Mapping[str, Any]]] = {}
    for row in scenario_rows:
        scenario_id = need_str(row.get("scenario_id"), "scenario_invalid")
        indices = [need_int(value, "scenario_invalid", minimum=0) for value in need_list(row.get("source_indices"), "scenario_invalid")]
        need(indices == sorted(indices), "scenario_source_order_invalid")
        need(all(index < len(rows) for index in indices), "scenario_source_index_invalid")
        grouped: dict[str, list[SourceRow]] = {}
        for index in indices:
            source = rows[index]
            grouped.setdefault(source.base_doc_code, []).append(source)
        resolved: dict[str, Mapping[str, Any]] = {}
        for base, group in grouped.items():
            top = max(source.version_number for source in group)
            winners = [source for source in group if source.version_number == top]
            need(len(winners) == 1, "active_version_ambiguous")
            winner = winners[0]
            resolved[base] = {
                "version_number": top,
                "basis": "source_map" if winner.origin == "source_map" else "ingest_order",
                "source_index": winner.index,
                "upload_count": len(group),
            }
        active[scenario_id] = resolved

    hashes = {
        "scenario_contract_sha256": sha256_hex(scenario_raw),
        "ingest_plan_sha256": sha256_hex(ingest_raw),
        "source_map_sha256": sha256_hex(source_map_raw),
        "fixture_manifest_sha256": sha256_hex(manifest_raw),
    }
    return PublicStructure(
        rows=tuple(rows),
        scenario_ids=scenario_ids,
        active=active,
        documented_versions=documented,
        hashes=hashes,
        binding_rule=(
            "ref.doc_code -> scenario active upload set (source_indices + ingest order) -> "
            "source_map base_doc_code/version_number or fixture-manifest business_version; "
            "explicit variant code binds only when that exact version is active; "
            "0/ambiguous -> unresolved"
        ),
    )


# --------------------------------------------------------------------------- #
# 单回合投影（R2：产品身份 document_codes + C 冻结空集原语）
# --------------------------------------------------------------------------- #


def _unit_views_v2(
    events: tuple[Mapping[str, Any], ...],
    projection: Mapping[str, Any],
    structure: PublicStructure,
) -> tuple[Any, ...]:
    from mktkb.evaluation.p2_evidence_rescore import UnitView, _used_layers

    rows = need_list(projection.get("units"), "projection_units_invalid")
    by_id: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        entry = need_map(row, "projection_unit_invalid")
        unit_id = need_str(entry.get("unit_id"), "projection_unit_invalid")
        by_id[unit_id] = entry
    units: list[Any] = []
    for unit_id, layer_names in _used_layers(list(events)).items():
        row = by_id.get(unit_id, {})
        document_name = need_opt_str(row.get("document_name"), "projection_unit_invalid")
        unit_key = need_opt_str(row.get("unit_key"), "projection_unit_invalid")
        locator = row.get("locator")
        need(isinstance(locator, Mapping), "projection_unit_invalid")
        version_number = row.get("version_number")
        version_number = version_number if type(version_number) is int and version_number > 0 else None
        version_id = need_opt_str(row.get("version_id"), "projection_unit_invalid")
        document_id = need_opt_str(row.get("document_id"), "projection_unit_invalid")
        doc_code, _doc_reason = structure.doc_code_for_unit(document_name, version_number)
        units.append(
            UnitView(
                unit_id=unit_id,
                layers=tuple(layer_names),
                document_id=document_id,
                document_name=document_name,
                doc_code=doc_code,
                version_id=version_id,
                version_number=version_number,
                unit_key=unit_key,
                record_code=None,  # 无冻结 unit_key->record_code 显式映射：保持 unresolved，不猜
                locator=dict(locator),
            )
        )
    return tuple(units)


def _empty_scope_for_envelope(envelope: Mapping[str, Any]) -> tuple[bool, str, bool]:
    """只读调用 C 冻结原语；返回 (proven, reason, primitive_raised)。

    原语只返回 bool + 固定码，不打印/不落盘文本；这里也不记录任何输入内容。
    """
    from mktkb.evaluation.p2_hard_evidence import _empty_use_scope_proof

    try:
        proven, reason = _empty_use_scope_proof(envelope)
    except Exception:  # noqa: BLE001 - 原语异常按证据缺口 fail closed
        return False, "branch_evidence_missing", True
    need(isinstance(proven, bool), "empty_scope_primitive_invalid")
    need(isinstance(reason, str) and bool(reason), "empty_scope_primitive_invalid")
    return proven, reason, False


def project_turn_v2(
    envelope: Mapping[str, Any] | None,
    *,
    turn_index: int,
    status: str,
    structure: PublicStructure,
    evidence_turn_index: int | None = None,
) -> Any:
    """把一轮 envelope 投影成 `TurnProjection`（显式 required 校验，不 fail-open）。"""
    from mktkb.evaluation.p2_evidence_rescore import _final_outcome

    need(type(turn_index) is int and turn_index >= 0, "case_plan_turn_invalid")
    need(status in ("executed", "error", "not_started"), "case_plan_turn_status_invalid")
    if status != "executed":
        need(envelope is None, "case_plan_turn_evidence_unexpected")
        return TurnProjection(
            turn_index,
            status,
            None,
            (),
            None,
            None,
            evidence_turn_index=evidence_turn_index,
            empty_scope_ok=False,
            empty_scope_reason="turn_not_executed",
            empty_scope_primitive_raised=False,
        )
    envelope = need_map(envelope, "evidence_envelope_missing")
    proven, reason, raised = _empty_scope_for_envelope(envelope)
    turn = need_map(envelope.get("turn"), "evidence_turn_missing")
    observed_index = need_int(turn.get("turn_index"), "evidence_turn_invalid", minimum=0)
    if evidence_turn_index is not None:
        need(type(evidence_turn_index) is int and evidence_turn_index >= 0, "case_plan_turn_invalid")
        need(observed_index == evidence_turn_index, "evidence_turn_index_mismatch")
    capture = need_map(envelope.get("capture"), "evidence_capture_missing")
    events = tuple(
        need_map(item, "evidence_event_invalid")
        for item in need_list(capture.get("events"), "evidence_events_invalid")
    )
    projection = need_map(envelope.get("db_projection"), "evidence_projection_missing")
    completeness = need_map(envelope.get("completeness"), "evidence_completeness_missing")
    completeness_status = str(completeness.get("status") or "")
    gate = None if completeness_status == "complete" else "evidence_incomplete"
    final_kind, final_text = _final_outcome(list(events))
    bindings = need_map(envelope.get("bindings"), "evidence_bindings_missing")
    resolved_bindings: dict[str, str] = {}
    for key in ("run_id", "plan_id", "plan_sha256"):
        resolved_bindings[key] = need_str(bindings.get(key), "evidence_bindings_invalid")
    units = _unit_views_v2(events, projection, structure)
    return TurnProjection(
        turn_index=turn_index,
        status=status,
        gate=gate,
        units=units,
        final_kind=final_kind,
        final_text=final_text,
        events=events,
        projection=projection,
        envelope_bindings=resolved_bindings,
        completeness_status=completeness_status,
        authenticated_user_id=need_str(turn.get("authenticated_user_id"), "evidence_turn_invalid"),
        evidence_turn_index=observed_index,
        empty_scope_ok=proven,
        empty_scope_reason=reason,
        empty_scope_primitive_raised=raised,
    )


def cross_entity_view_v2(turn: Any) -> Any:
    from mktkb.evaluation.p2_evidence_rescore_axes import (
        CrossEntityEvidenceView,
        EntityFactView,
        EntityIdentityView,
    )

    projection = turn.projection
    unit_rows = [
        need_map(row, "projection_unit_invalid")
        for row in need_list(projection.get("units"), "projection_units_invalid")
    ]
    unit_entity: dict[str, Any] = {}
    for row in unit_rows:
        unit_id = need_str(row.get("unit_id"), "projection_unit_invalid")
        entity_type = need_opt_str(row.get("entity_type"), "projection_unit_invalid")
        entity_key = need_opt_str(row.get("entity_key"), "projection_unit_invalid")
        filters = row.get("entity_filters")
        need(isinstance(filters, Mapping), "projection_unit_invalid")
        if entity_type is None and entity_key is None:
            continue
        unit_entity[unit_id] = EntityIdentityView(
            entity_type=entity_type, entity_key=entity_key, filters=dict(filters)
        )

    facts: list[Any] = []
    for payload in R1._payloads_of_kind(turn.events, "direct_rag_answer"):
        for fact in need_list(payload.get("facts"), "direct_rag_fact_invalid"):
            row = need_map(fact, "direct_rag_fact_invalid")
            facts.append(
                EntityFactView(
                    entity_key=need_opt_str(row.get("entity_key"), "direct_rag_fact_invalid"),
                    source_unit_id=need_opt_str(row.get("source_unit_id"), "direct_rag_fact_invalid"),
                    layer="direct_rag_fact",
                )
            )

    plan_rows = R1._payloads_of_kind(turn.events, "plan_observed")
    plan_filters = None
    if len(plan_rows) == 1:
        filters = plan_rows[0].get("filters")
        if isinstance(filters, Mapping):
            plan_filters = dict(filters)

    return CrossEntityEvidenceView(
        units=turn.units,
        unit_entity=unit_entity,
        facts=tuple(facts),
        plan_filters=plan_filters,
        bindings=dict(turn.envelope_bindings),
        # C 冻结原语只提供严格空集 bool/reason；作用域判定仍由 Q1a-1b 自己完成。
        empty_scope_proven=True if turn.empty_scope_ok else False,
        empty_scope_reason=None if turn.empty_scope_ok else turn.empty_scope_reason,
    )


def stale_source_view_v2(turn: Any) -> Any:
    from mktkb.evaluation.p2_evidence_rescore_axes import LifecycleView, StaleSourceEvidenceView

    projection = turn.projection
    unit_rows = [
        need_map(row, "projection_unit_invalid")
        for row in need_list(projection.get("units"), "projection_units_invalid")
    ]
    by_id = {need_str(row.get("unit_id"), "projection_unit_invalid"): row for row in unit_rows}
    sources = [
        need_map(row, "projection_message_source_invalid")
        for row in need_list(projection.get("message_sources"), "projection_message_sources_invalid")
    ]
    source_by_id = {
        need_str(row.get("source_id"), "projection_message_source_invalid"): row for row in sources
    }

    lifecycle: dict[str, Any] = {}
    for unit in turn.units:
        row = by_id.get(unit.unit_id)
        if row is None:
            continue
        date_fields = row.get("date_fields")
        need(isinstance(date_fields, Mapping), "projection_unit_invalid")
        # 本批全部使用 unit 的 date_fields 均为空；非空结构无冻结投影定义 -> fail closed。
        date_state = "none" if not date_fields else "unavailable"
        version_state_raw = need_opt_str(row.get("version_state"), "projection_unit_invalid")
        version_state = version_state_raw if version_state_raw in ("published", "not_published") else None
        source_row = source_by_id.get(unit.unit_id) if "final_citation" in unit.layers else None
        lifecycle[unit.unit_id] = LifecycleView(
            unit_id=unit.unit_id,
            document_deleted=need_bool(row.get("document_deleted"), "projection_unit_invalid"),
            version_state=version_state,
            active=need_bool(row.get("active"), "projection_unit_invalid"),
            active_version_id=need_opt_str(row.get("active_version_id"), "projection_unit_invalid"),
            date_state=date_state,
            effective_from=None,
            effective_to=None,
            citation_source_document_id=None
            if source_row is None
            else need_opt_str(source_row.get("document_id"), "projection_message_source_invalid"),
            citation_source_version_id=None
            if source_row is None
            else need_opt_str(source_row.get("version_id"), "projection_message_source_invalid"),
        )

    plan_rows = R1._payloads_of_kind(turn.events, "plan_observed")
    actual_as_of = None
    include_future = None
    if len(plan_rows) == 1:
        actual_as_of = need_opt_str(plan_rows[0].get("as_of"), "plan_observed_invalid")
        include = plan_rows[0].get("include_future")
        include_future = include if isinstance(include, bool) else None

    return StaleSourceEvidenceView(
        units=turn.units,
        lifecycle=lifecycle,
        actual_as_of=actual_as_of,
        include_future=include_future,
        bindings=dict(turn.envelope_bindings),
        empty_scope_proven=True if turn.empty_scope_ok else False,
        empty_scope_reason=None if turn.empty_scope_ok else turn.empty_scope_reason,
    )


def version_bindings_for_case(
    structure: PublicStructure,
    scenario_id: str,
    refs: Mapping[str, tuple[Mapping[str, Any], ...]],
) -> tuple[dict[str, tuple[dict[str, Any], ...]], dict[str, Any], dict[str, Any]]:
    """逐 ref 推导绑定 + 归一化 refs；同时返回**计数**覆盖情况（公开侧只落这些计数）。

    归一化可能让不同原始 ref（如历史变体与正常文件）落到同一 `ref_key`。若两者的绑定结果
    不一致（一个 unresolved、一个 bound 到别的版本），该 key **不绑定**并记
    `ref_normalization_conflict`，保持 fail closed。
    """
    from mktkb.evaluation.p2_evidence_rescore import ref_key

    normalized_refs: dict[str, tuple[dict[str, Any], ...]] = {}
    entries: list[tuple[str, Mapping[str, Any], Mapping[str, Any], Any | None, str]] = []
    per_key: dict[str, list[tuple[Any | None, str]]] = {}
    aliases = 0
    for collection, rows in refs.items():
        normalized_rows: list[dict[str, Any]] = []
        for ref in rows:
            original = dict(ref)
            binding, status, normalized = structure.version_binding(scenario_id, original)
            normalized = dict(normalized)
            if normalized.get("doc_code") != original.get("doc_code"):
                aliases += 1
            key = ref_key(normalized)
            entries.append((collection, original, normalized, binding, status))
            per_key.setdefault(key, []).append((binding, status))
            normalized_rows.append(normalized)
        normalized_refs[collection] = tuple(normalized_rows)

    conflicted: set[str] = set()
    for key, outcomes in per_key.items():
        signatures = {
            ("none",) if binding is None else (binding.basis, binding.version_number)
            for binding, _status in outcomes
        }
        if len(signatures) > 1:
            conflicted.add(key)

    bindings: dict[str, Any] = {}
    totals = {"refs": 0, "bound": 0, "unbound": 0, "conflicts": 0}
    unbound: dict[str, int] = {}
    by_collection: dict[str, dict[str, int]] = {}
    by_basis: dict[str, int] = {}
    for collection, original, normalized, binding, status in entries:
        bucket = by_collection.setdefault(
            collection, {"refs": 0, "bound": 0, "unbound": 0, "alias_normalized": 0}
        )
        totals["refs"] += 1
        bucket["refs"] += 1
        if normalized.get("doc_code") != original.get("doc_code"):
            bucket["alias_normalized"] += 1
        key = ref_key(normalized)
        if key in conflicted:
            totals["unbound"] += 1
            totals["conflicts"] += 1
            bucket["unbound"] += 1
            unbound["ref_normalization_conflict"] = unbound.get("ref_normalization_conflict", 0) + 1
            continue
        if binding is None:
            totals["unbound"] += 1
            bucket["unbound"] += 1
            unbound[status] = unbound.get(status, 0) + 1
            continue
        bindings[key] = binding
        totals["bound"] += 1
        bucket["bound"] += 1
        by_basis[binding.basis] = by_basis.get(binding.basis, 0) + 1
    return bindings, normalized_refs, {
        **totals,
        "alias_normalized": aliases,
        "unbound_by_reason": {key: unbound[key] for key in sorted(unbound)},
        "by_collection": by_collection,
        "bound_by_basis": {key: by_basis[key] for key in sorted(by_basis)},
    }


# --------------------------------------------------------------------------- #
# 题内折叠 / 覆盖 / 计数（与 R1 同语义，R2 复用）
# --------------------------------------------------------------------------- #


def _fold_axis(axis: str, verdicts: list[Any]) -> Any:
    """题内折叠：violation > unknown > all-N/A > passed（与 Q1a-1 `_fold_safety` 同序）。"""
    from mktkb.evaluation.p2_evidence_rescore_axes import AxisVerdict, NA_REASONS, PASS_REASONS

    refs: list[str] = []
    for verdict in verdicts:
        refs.extend(verdict.evidence)
    missing = sorted({code for verdict in verdicts for code in verdict.missing})
    if any(verdict.state == "violation" for verdict in verdicts):
        state = "violation"
        reason = next(item.reason for item in verdicts if item.state == "violation")
    elif any(verdict.state == "unknown" for verdict in verdicts):
        state = "unknown"
        reason = next(item.reason for item in verdicts if item.state == "unknown")
    elif verdicts and all(verdict.state == "not_applicable" for verdict in verdicts):
        state = "not_applicable"
        reason = NA_REASONS[axis]
    else:
        state = "passed"
        reason = PASS_REASONS[axis]
    return AxisVerdict(axis, state, reason, tuple(dict.fromkeys(refs))[:24], tuple(missing))


def _apply_local_overrides(
    axis: str, verdict: Any, quality_status: str, evidence_complete: bool
) -> tuple[Any, list[str]]:
    """只应用**本包可得**的两个覆盖：case-plan quality_status + 证据派生完整度。"""
    from mktkb.evaluation.p2_evidence_rescore_axes import AxisVerdict

    codes: list[str] = []
    if quality_status in ("error", "not_executed") and verdict.state != "violation":
        reason = "turn_error" if quality_status == "error" else "turn_not_executed"
        verdict = AxisVerdict(
            axis, "unknown", reason, verdict.evidence, tuple(sorted(set(verdict.missing) | {reason}))
        )
        codes.append("quality_error_override")
    if not evidence_complete and verdict.state in ("passed", "not_applicable"):
        verdict = AxisVerdict(
            axis,
            "unknown",
            "evidence_incomplete",
            verdict.evidence,
            tuple(sorted(set(verdict.missing) | {"evidence_incomplete"})),
        )
        codes.append("evidence_incomplete_override")
    return verdict, codes


def _counts(records: list[Mapping[str, Any]], axis: str) -> dict[str, int]:
    buckets = {"planned": 0, "checked": 0, "passed": 0, "not_applicable": 0, "unknown": 0, "violations": 0}
    for record in records:
        state = record["axes"][axis]["state"]
        buckets["planned"] += 1
        if state == "passed":
            buckets["passed"] += 1
        elif state == "not_applicable":
            buckets["not_applicable"] += 1
        elif state == "unknown":
            buckets["unknown"] += 1
        elif state == "violation":
            buckets["violations"] += 1
        else:  # pragma: no cover - AxisVerdict 已限定枚举
            raise ProjectionError("axis_state_invalid")
    buckets["checked"] = buckets["passed"] + buckets["not_applicable"] + buckets["violations"]
    need(buckets["planned"] == buckets["checked"] + buckets["unknown"], "counts_inconsistent")
    return buckets


def _reason_counts(records: list[Mapping[str, Any]], axis: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for record in records:
        entry = record["axes"][axis]
        key = f"{entry['state']}:{entry['reason']}"
        out[key] = out.get(key, 0) + 1
    return {key: out[key] for key in sorted(out)}


def _audit_counts(records: list[Mapping[str, Any]], axis: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for record in records:
        for code in record["axes"][axis]["audit"]:
            out[code] = out.get(code, 0) + 1
    return {key: out[key] for key in sorted(out)}


def _case_status(record: Mapping[str, Any], *, na_axes: tuple[str, ...] = ()) -> str:
    """题级状态：hard（任一轴 violation）/ unknown（任一 required 轴 unknown）/ pass。"""
    states = {axis: record["axes"][axis]["state"] for axis in ("safety", "cross_user", "cross_entity", "stale_source")}
    if any(state == "violation" for state in states.values()):
        return "hard_failure"
    for axis, entry in record["axes"].items():
        if axis in na_axes:
            continue
        if entry["applicability"] == "not_applicable":
            continue
        if entry["applicability"] == "unknown":
            return "unknown"
        if states[axis] == "unknown":
            return "unknown"
    return "pass"


def _score(records: list[Mapping[str, Any]], *, na_axes_for: Mapping[str, tuple[str, ...]] | None = None) -> dict[str, int]:
    na_map = na_axes_for or {}
    buckets = {"pass": 0, "hard_failure": 0, "unknown": 0}
    for record in records:
        status = _case_status(record, na_axes=na_map.get(str(record["case_id"]), ()))
        buckets[status] += 1
    return buckets

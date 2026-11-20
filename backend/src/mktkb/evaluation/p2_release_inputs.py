"""正式门禁的输入契约：显式加载批准配置并逐项绑定证据摘要。

设计要点（对应任务书 §3）：

* **只认摘要，不认自报**：清单只声明 ``path`` 与 ``sha256``；本模块重新读取字节、
  重算摘要再比对。任何"verified/approved 布尔"都不参与判定。
* **缺项即阻断**：除任务 2/3 的正式交付段（``public``/``u``/``h2``）可以用固定
  ``PENDING-TASK2`` / ``PENDING-TASK3`` 标记为待交付外，缺段、缺键、多键都拒绝。
* **不猜身份**：B0 基线、候选流水线、历史 run 的原配置/流水线/索引版本都按原样
  读出并逐字段比对，不做"看起来一样"的推断。
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .gate import GATE_VERSION_V0_3
from .p2_b0 import (
    B0_ARTIFACTS,
    B0_GATE_CONFIG_HASH,
    B0_GATE_FILE_SHA256,
    pipeline_source_sha256,
)
from .p2_release_model import (
    APPLICABILITY_SCHEMA_VERSION,
    INPUTS_SCHEMA_VERSION,
    PENDING_MARKERS,
    PENDING_SECTIONS,
    R_BASELINE_UNREGISTERED,
    R_CROSS_PLAN_MERGE,
    R_DIGEST_MISMATCH,
    R_DUPLICATE_EVIDENCE,
    R_EVIDENCE_MISSING,
    R_GATE_CONFIG_UNAPPROVED,
    R_IDENTITY_MISMATCH,
    R_INPUTS_INVALID,
    R_STALE_CONFIG,
    R_VERSION_MISMATCH,
    SELECTION_SCHEMA_VERSION,
    ReleaseGateError,
    exact_keys,
    file_sha256,
    payload_sha256,
    require_digest,
    require_int,
    require_text,
)
from .p2_scoring import P2GateConfig, load_p2_gate_config
from .p2_b0 import load_approved_b0_config
from .p2_scoring import P2_BOUNDARY_IDS, P2_NEGATIVE_IDS, P2_UPDATE_DELETE_IDS

PROJECT_ROOT = Path(__file__).resolve().parents[4]

#: 已登记 B0 基线（T209 关项）。改这些常量等价于重新登记基线，属于发布动作。
B0_BASELINE_ID = "7981d4afc2d1"
B0_RUN_ID = "p2-t209-b0-20261120-02"
#: 登记处的规范位置（相对路径可以写，但解析后必须落在这里）。
B0_REGISTRY_ROOT = PROJECT_ROOT / "var" / "eval" / "baselines"
#: 已登记基线的三份记录摘要（钉死：任何"自洽的假登记处"都会在摘要处被拒）。
B0_BASELINE_RECORD_SHA256 = "09cf747c2c8aca6ffe38fb0a035ac5bab63baa6abbb94e38ee427331cff03781"
B0_ADMISSION_FILE_SHA256 = "07d2b1e3c39da3eca3f81986691c5d1d0a075d2a7effa7cf730e3dcd50d12795"
B0_APPROVAL_FILE_SHA256 = "f760bf4f4a3147728395ae4b10c0a3b027e18dfdb3a6004de2f0d2e351998d8f"

#: 冻结模板（未批准的 v0.3 原始配置）：历史 run 绑定它的加载器摘要 ``d1097573…``。
FROZEN_TEMPLATE_PATH = PROJECT_ROOT / "docs" / "evaluation" / "gate_v0_3.json"
FROZEN_TEMPLATE_SHA256 = "3af301dba2d4dbd1bcc9d8f17c656f8a80755820fa2a8559b787974f20b5619d"
FROZEN_TEMPLATE_CONFIG_HASH = "d10975732dd50616f959fde71a3ead42822b877e98c55c4367902cb053cfd2a8"

#: 公开套件 -> gate 配置里的 ``hard_gate_min_sample`` 名称（N 在配置里叫 badcase）。
GATE_SUITE_NAME: Mapping[str, str] = {
    "negative": "badcase",
    "boundary": "boundary",
    "update_delete": "update_delete",
    "b0": "b0",
}

#: 历史公开 run 必须提供的工件（逐字节绑定）。
PUBLIC_ARTIFACTS: tuple[str, ...] = (
    "run_manifest.json",
    "summary.json",
    "dataset.jsonl",
    "cases.jsonl",
)

_INPUTS_KEYS = ("schema_version", "gate_config", "candidate_pipeline", "b0")
#: ``document_codes`` 是历史/候选 run 共用的"产品文档名 -> doc_code"映射（N/C 与 U 都要用），
#: 因此放在顶层；交付 public 或 u 时必需。
_INPUTS_OPTIONAL = ("document_codes", "evidence_manifest", "public", "u", "h2", "pending")
#: 任务 3 的机器可读清单（可选）：给了就逐项交叉核对，不给不影响其余判定。
_EVIDENCE_MANIFEST_KEYS = ("manifest",)
_EVIDENCE_MANIFEST_OPTIONAL = ("report", "sha256sums")
_REF_KEYS = ("path", "sha256")
_B0_KEYS = ("baseline_root", "baseline_id", "run_id", "baseline_sha256", "admission_sha256", "approval_sha256")
_CANDIDATE_KEYS = ("pipeline_source_sha256", "pipeline_version")
_PUBLIC_KEYS = ("selection", "runs")
#: ``applicability`` 可缺席：同版本 run 不需要旧版本适用性证明；跨版本时门禁会强制要求。
_PUBLIC_RUN_KEYS = ("suite", "run_id", "run_dir", "artifacts", "original")
_PUBLIC_RUN_OPTIONAL = ("applicability", "rag_db", "binding_proof")
_ORIGINAL_KEYS = (
    "gate_config_path",
    "gate_config_sha256",
    "gate_config_hash",
    "pipeline_version",
    "index_revision",
    "dataset_version",
)
_U_KEYS = ("real",)
_U_REAL_KEYS = ("suite", "run_id", "run_dir", "case_ids", "artifacts", "original")
_U_OPTIONAL = ("applicability", "rag_db", "binding_proof")
_H2_KEYS = ("source_proof",)
#: 两种 H2 投喂方式：① ``composition`` + ``cards``（四张卡本体可读，全量严格校验）；
#: ② ``composition_aggregate`` + ``cards_index``（D-001 受限边界：卡本体在保管环境，
#: 只做外层核验）。
_H2_OPTIONAL = ("composition", "cards", "composition_aggregate", "cards_index")
_H2_CARD_KEYS = ("scenario_id", "path", "sha256")
_SELECTION_KEYS = ("schema_version", "authority", "assignments")
_SELECTION_AUTHORITY_KEYS = ("document", "sha256", "section")
_SELECTION_ASSIGNMENT_KEYS = ("suite", "case_id", "run_id")

#: 冻结选题范围（与 p2_scoring 的正式分母同源）。
SELECTION_SUITES: Mapping[str, tuple[str, ...]] = {
    "negative": P2_NEGATIVE_IDS,
    "boundary": P2_BOUNDARY_IDS,
    # U 组可一并纳入冻结选题范围（任务 3 清单的 frozen_scope 含 U01）；纳入时必须精确覆盖。
    "update_delete": P2_UPDATE_DELETE_IDS,
}
#: 必须被选题范围精确覆盖的套件（U 允许由 ``u.real.case_ids`` 单独声明）。
REQUIRED_SELECTION_SUITES: tuple[str, ...] = ("negative", "boundary")

#: H2 四场景顺序与批准的批次覆盖（T207 2026-11-19 已接收复测批次）。
H2_SCENARIO_ORDER: tuple[str, ...] = (
    "base_b0",
    "base_b0_plus_v01",
    "pre_v05_without_v07",
    "post_v05_without_v01",
)
H2_SCENARIO_CASE_COUNTS: Mapping[str, int] = {
    "base_b0": 12,
    "base_b0_plus_v01": 8,
    "pre_v05_without_v07": 5,
    "post_v05_without_v01": 5,
}
H2_SCENARIO_TURNS: Mapping[str, int] = {
    "base_b0": 14,
    "base_b0_plus_v01": 10,
    "pre_v05_without_v07": 6,
    "post_v05_without_v01": 6,
}


@dataclass(frozen=True)
class BoundJSON:
    """一个已按字节绑定的 JSON 工件。"""

    role: str
    path: Path
    sha256: str
    payload: Any


@dataclass(frozen=True)
class BoundFile:
    """一个已按字节绑定的二进制工件（例如 run 的 rag 索引库）。"""

    role: str
    path: Path
    sha256: str


def bind_file(role: str, ref: Mapping[str, Any], root: Path) -> BoundFile:
    """二进制工件的摘要绑定（不做 JSON 解析）。"""
    exact_keys(ref, _REF_KEYS, what=f"{role} 引用")
    path = _resolve(ref, root, what=role)
    declared = require_digest(ref.get("sha256"), f"{role}.sha256")
    if not path.is_file():
        raise ReleaseGateError(R_EVIDENCE_MISSING, f"{role} 文件不存在", {"path": str(path)})
    actual = file_sha256(path)
    if actual != declared:
        raise ReleaseGateError(R_DIGEST_MISMATCH, f"{role} 摘要与声明不符",
                               {"declared": declared, "actual": actual, "path": str(path)})
    return BoundFile(role=role, path=path, sha256=actual)


@dataclass(frozen=True)
class RunBinding:
    """一个历史/候选 run 的身份与字节绑定。"""

    suite: str
    run_id: str
    run_dir: Path
    artifacts: Mapping[str, str]
    original: Mapping[str, Any]
    manifest: Mapping[str, Any]
    summary: Mapping[str, Any]
    applicability: "BoundJSON | None" = None
    rag_db: "BoundFile | None" = None
    binding_proof: "BoundJSON | None" = None
    #: 本 run 承担的标准套件（同一 run 可同时提供 N 与 C 的题，但绑定必须一致）。
    suites: tuple[str, ...] = ()

    def artifact_bytes(self, name: str) -> bytes:
        return (self.run_dir / name).read_bytes()


@dataclass(frozen=True)
class ReleaseInputs:
    """正式门禁的完整输入（已逐项验证摘要，未做任何质量判定）。"""

    path: Path
    sha256: str
    gate_config: P2GateConfig
    gate_config_path: Path
    candidate_pipeline_sha256: str
    candidate_pipeline_version: str
    b0_baseline: BoundJSON
    b0_admission: BoundJSON
    b0_approval: BoundJSON
    b0_run_dir: Path
    evidence_manifest: BoundJSON | None
    evidence_report: BoundFile | None
    evidence_sums: BoundFile | None
    public: Mapping[str, Any] | None
    public_runs: tuple[RunBinding, ...]
    selection: BoundJSON | None
    document_codes: BoundJSON | None
    u: Mapping[str, Any] | None
    u_controls: BoundJSON | None
    u_real: RunBinding | None
    h2: Mapping[str, Any] | None
    h2_composition: BoundJSON | None
    h2_source_proof: BoundJSON | None
    h2_cards: tuple[BoundJSON, ...]
    #: D-001 受限模式：组合聚合视图 + 卡索引（卡本体只在保管环境）。
    h2_composition_aggregate: BoundJSON | None
    h2_cards_index: BoundJSON | None
    pending: Mapping[str, str]


# --------------------------------------------------------------------------- #
# 绑定工具
# --------------------------------------------------------------------------- #


def _resolve(ref: Mapping[str, Any], root: Path, *, what: str) -> Path:
    path = Path(require_text(ref.get("path"), f"{what}.path"))
    return path if path.is_absolute() else (root / path)


def bind_json(role: str, ref: Mapping[str, Any], root: Path) -> BoundJSON:
    """读字节 -> 重算摘要 -> 比对声明值 -> 解析 JSON。缺证与错配原因码分开。"""
    exact_keys(ref, _REF_KEYS, what=f"{role} 引用")
    path = _resolve(ref, root, what=role)
    declared = require_digest(ref.get("sha256"), f"{role}.sha256")
    if not path.is_file():
        raise ReleaseGateError(R_EVIDENCE_MISSING, f"{role} 文件不存在", {"path": str(path)})
    raw = path.read_bytes()
    actual = payload_sha256_bytes(raw)
    if actual != declared:
        raise ReleaseGateError(
            R_DIGEST_MISMATCH,
            f"{role} 摘要与声明不符",
            {"declared": declared, "actual": actual, "path": str(path)},
        )
    try:
        import json

        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeError, ValueError):
        raise ReleaseGateError(R_INPUTS_INVALID, f"{role} 不是合法 UTF-8 JSON") from None
    return BoundJSON(role=role, path=path, sha256=actual, payload=payload)


def payload_sha256_bytes(raw: bytes) -> str:
    from .p2_release_model import sha256_bytes

    return sha256_bytes(raw)


# --------------------------------------------------------------------------- #
# 各段加载
# --------------------------------------------------------------------------- #


def _load_gate_config(ref: Mapping[str, Any], root: Path) -> tuple[P2GateConfig, Path]:
    bound = bind_json("gate_config", ref, root)
    if bound.sha256 != B0_GATE_FILE_SHA256:
        # 冻结模板 = 陈旧框架配置；其余一律视为未批准。
        code = R_STALE_CONFIG if bound.sha256 == FROZEN_TEMPLATE_SHA256 else R_GATE_CONFIG_UNAPPROVED
        raise ReleaseGateError(code, "gate_config 不是已批准的正式配置",
                               {"declared": bound.sha256, "approved": B0_GATE_FILE_SHA256})
    try:
        config = load_approved_b0_config(bound.path)
    except ValueError as exc:
        raise ReleaseGateError(R_GATE_CONFIG_UNAPPROVED, f"批准配置加载失败: {exc}") from None
    if not (config.config_hash == B0_GATE_CONFIG_HASH and config.status == "approved"
            and config.gate_version == GATE_VERSION_V0_3):
        raise ReleaseGateError(R_GATE_CONFIG_UNAPPROVED, "批准配置摘要/状态/版本不符")
    return config, bound.path


def _load_candidate(ref: Mapping[str, Any]) -> tuple[str, str]:
    exact_keys(ref, _CANDIDATE_KEYS, what="candidate_pipeline")
    declared = require_digest(ref.get("pipeline_source_sha256"), "candidate_pipeline.pipeline_source_sha256")
    version = require_text(ref.get("pipeline_version"), "candidate_pipeline.pipeline_version")
    current = pipeline_source_sha256()
    if declared != current:
        raise ReleaseGateError(
            R_VERSION_MISMATCH,
            "候选流水线与当前字节不一致",
            {"declared": declared, "current": current},
        )
    return declared, version


def _load_b0(ref: Mapping[str, Any], root: Path) -> tuple[BoundJSON, BoundJSON, BoundJSON, Path]:
    exact_keys(ref, _B0_KEYS, what="b0")
    baseline_root = Path(require_text(ref.get("baseline_root"), "b0.baseline_root"))
    baseline_root = baseline_root if baseline_root.is_absolute() else root / baseline_root
    baseline_id = require_text(ref.get("baseline_id"), "b0.baseline_id")
    run_id = require_text(ref.get("run_id"), "b0.run_id")
    if baseline_id != B0_BASELINE_ID or run_id != B0_RUN_ID:
        raise ReleaseGateError(
            R_IDENTITY_MISMATCH,
            "B0 不是已登记基线",
            {"baseline_id": baseline_id, "run_id": run_id,
             "registered": {"baseline_id": B0_BASELINE_ID, "run_id": B0_RUN_ID}},
        )
    entry = baseline_root / baseline_id
    if not entry.is_dir() or baseline_root.resolve() != B0_REGISTRY_ROOT.resolve():
        raise ReleaseGateError(R_BASELINE_UNREGISTERED, "基线登记目录不是规范登记处",
                               {"path": str(entry), "registered_root": str(B0_REGISTRY_ROOT)})
    baseline = bind_json("b0.baseline", {"path": str(entry / "baseline.json"),
                                         "sha256": ref.get("baseline_sha256")}, root)
    admission = bind_json("b0.admission", {"path": str(entry / "b0-admission.json"),
                                           "sha256": ref.get("admission_sha256")}, root)
    approval = bind_json("b0.approval", {"path": str(entry / "b0-approval-receipt.json"),
                                         "sha256": ref.get("approval_sha256")}, root)
    approved_files = {
        "baseline.json": B0_BASELINE_RECORD_SHA256,
        "b0-admission.json": B0_ADMISSION_FILE_SHA256,
        "b0-approval-receipt.json": B0_APPROVAL_FILE_SHA256,
    }
    for name, bound in (("baseline.json", baseline), ("b0-admission.json", admission),
                        ("b0-approval-receipt.json", approval)):
        if bound.sha256 != approved_files[name]:
            raise ReleaseGateError(R_DIGEST_MISMATCH, f"B0 登记文件不是已接收版本: {name}",
                                   {"declared": bound.sha256, "approved": approved_files[name]})
    record, proof, receipt = baseline.payload, admission.payload, approval.payload
    if not isinstance(record, Mapping) or not isinstance(proof, Mapping) or not isinstance(receipt, Mapping):
        raise ReleaseGateError(R_INPUTS_INVALID, "B0 登记/准入/回执必须是对象")
    if (record.get("baseline_id") != baseline_id or record.get("run_id") != run_id
            or proof.get("run_id") != run_id or receipt.get("run_id") != run_id
            or receipt.get("baseline_id") != baseline_id):
        raise ReleaseGateError(R_IDENTITY_MISMATCH, "B0 登记/准入/回执的 run 身份不一致")
    gate_block = record.get("gate") if isinstance(record.get("gate"), Mapping) else {}
    if (receipt.get("decision") != "approved" or receipt.get("scope") != "t209_b0_baseline"
            or receipt.get("schema_version") != "mktkb.p2.b0.approval.v0.1"):
        raise ReleaseGateError(R_IDENTITY_MISMATCH, "B0 审批回执不是已接收的 T209 基线")
    if (gate_block.get("gate_result_sha256") != receipt.get("evidence_sha256")
            or gate_block.get("gate_result_sha256") != payload_sha256(proof)
            or record.get("artifact_sha256") != proof.get("artifact_sha256")):
        raise ReleaseGateError(R_DIGEST_MISMATCH, "B0 回执/准入/登记摘要错配")
    if set(record.get("artifact_sha256") or {}) != set(B0_ARTIFACTS):
        raise ReleaseGateError(R_EVIDENCE_MISSING, "B0 登记工件集合不完整",
                               {"missing": sorted(set(B0_ARTIFACTS) - set(record.get("artifact_sha256") or {}))})
    run_dir = Path(str(record.get("run_dir") or ""))
    if not run_dir.is_dir():
        raise ReleaseGateError(R_EVIDENCE_MISSING, "B0 运行目录不存在", {"path": str(run_dir)})
    return baseline, admission, approval, run_dir


def load_run_binding(
    ref: Mapping[str, Any], root: Path, *, expected_suites: tuple[str, ...]
) -> RunBinding:
    exact_keys(ref, _PUBLIC_RUN_KEYS, what="run", optional=_PUBLIC_RUN_OPTIONAL)
    suite = require_text(ref.get("suite"), "run.suite")
    if suite not in expected_suites:
        raise ReleaseGateError(R_IDENTITY_MISMATCH, f"run.suite 不在允许范围 {expected_suites}", {"suite": suite})
    run_id = require_text(ref.get("run_id"), "run.run_id")
    run_dir = Path(require_text(ref.get("run_dir"), "run.run_dir"))
    run_dir = run_dir if run_dir.is_absolute() else root / run_dir
    if not run_dir.is_dir():
        raise ReleaseGateError(R_EVIDENCE_MISSING, "run 目录不存在", {"run_id": run_id, "path": str(run_dir)})
    artifacts = ref.get("artifacts")
    if not isinstance(artifacts, Mapping):
        raise ReleaseGateError(R_INPUTS_INVALID, "run.artifacts 必须是对象")
    if set(artifacts) != set(PUBLIC_ARTIFACTS):
        raise ReleaseGateError(R_EVIDENCE_MISSING, "run.artifacts 集合不完整",
                               {"missing": sorted(set(PUBLIC_ARTIFACTS) - set(artifacts))})
    digests: dict[str, str] = {}
    for name in PUBLIC_ARTIFACTS:
        declared = require_digest(artifacts[name], f"run.artifacts[{name}]")
        target = run_dir / name
        if not target.is_file():
            raise ReleaseGateError(R_EVIDENCE_MISSING, f"run 工件缺失: {name}",
                                   {"run_id": run_id, "path": str(target)})
        actual = file_sha256(target)
        if actual != declared:
            raise ReleaseGateError(R_DIGEST_MISMATCH, f"run 工件摘要不符: {name}",
                                   {"run_id": run_id, "declared": declared, "actual": actual})
        digests[name] = actual
    original = exact_keys(ref.get("original"), _ORIGINAL_KEYS, what="run.original")
    import json

    manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    if not isinstance(manifest, Mapping) or not isinstance(summary, Mapping):
        raise ReleaseGateError(R_INPUTS_INVALID, "run_manifest/summary 必须是对象")
    if manifest.get("run_id") != run_id:
        raise ReleaseGateError(R_IDENTITY_MISMATCH, "run_manifest.run_id 与声明不符",
                               {"declared": run_id, "observed": manifest.get("run_id")})
    for field in ("gate_config_hash", "pipeline_version", "index_revision", "dataset_version"):
        if manifest.get(field) != original.get(field):
            raise ReleaseGateError(
                R_IDENTITY_MISMATCH, f"历史 run 的 {field} 与声明不符",
                {"declared": original.get(field), "observed": manifest.get(field), "run_id": run_id},
            )
    gate_path = Path(require_text(original.get("gate_config_path"), "run.original.gate_config_path"))
    gate_path = gate_path if gate_path.is_absolute() else root / gate_path
    if not gate_path.is_file():
        raise ReleaseGateError(R_EVIDENCE_MISSING, "原配置模板不存在", {"path": str(gate_path)})
    template_sha = require_digest(original.get("gate_config_sha256"), "run.original.gate_config_sha256")
    if file_sha256(gate_path) != template_sha:
        raise ReleaseGateError(R_DIGEST_MISMATCH, "原配置模板摘要不符", {"path": str(gate_path)})
    template = load_p2_gate_config(gate_path)
    if template.config_hash != require_text(original.get("gate_config_hash"), "run.original.gate_config_hash"):
        raise ReleaseGateError(R_IDENTITY_MISMATCH, "原配置加载器摘要与 run_manifest 不一致")
    require_int(original.get("index_revision"), "run.original.index_revision")
    applicability = None
    if ref.get("applicability") is not None:
        applicability = bind_json(f"run.applicability:{run_id}", ref.get("applicability"), root)
        if not isinstance(applicability.payload, Mapping):
            raise ReleaseGateError(R_INPUTS_INVALID, "run.applicability 必须是对象")
    rag_db = None
    if ref.get("rag_db") is not None:
        rag_db = bind_file(f"run.rag_db:{run_id}", ref.get("rag_db"), root)
    binding_proof = None
    if ref.get("binding_proof") is not None:
        binding_proof = bind_json(f"run.binding_proof:{run_id}", ref.get("binding_proof"), root)
        if not isinstance(binding_proof.payload, Mapping):
            raise ReleaseGateError(R_INPUTS_INVALID, "run.binding_proof 必须是对象")
    return RunBinding(suite=suite, run_id=run_id, run_dir=run_dir, artifacts=digests,
                      original=dict(original), manifest=manifest, summary=summary,
                      applicability=applicability, rag_db=rag_db,
                      binding_proof=binding_proof, suites=(suite,))


def _load_selection(ref: Mapping[str, Any], root: Path) -> BoundJSON:
    bound = bind_json("public.selection", ref, root)
    payload = exact_keys(bound.payload, _SELECTION_KEYS, what="selection")
    if payload.get("schema_version") != SELECTION_SCHEMA_VERSION:
        raise ReleaseGateError(R_VERSION_MISMATCH, "selection schema 版本不符",
                               {"expected": SELECTION_SCHEMA_VERSION, "observed": payload.get("schema_version")})
    authority = exact_keys(payload.get("authority"), _SELECTION_AUTHORITY_KEYS, what="selection.authority")
    document = Path(require_text(authority.get("document"), "selection.authority.document"))
    document = document if document.is_absolute() else root / document
    if not document.is_file():
        raise ReleaseGateError(R_EVIDENCE_MISSING, "选题范围授权文档不存在", {"path": str(document)})
    if file_sha256(document) != require_digest(authority.get("sha256"), "selection.authority.sha256"):
        raise ReleaseGateError(R_DIGEST_MISMATCH, "选题范围授权文档摘要不符", {"path": str(document)})
    require_text(authority.get("section"), "selection.authority.section")
    return bound


def validate_selection(
    selection: BoundJSON, runs: Mapping[str, RunBinding]
) -> dict[str, dict[str, str]]:
    """校验冻结选题范围：逐题唯一、覆盖精确、只指向已登记 run。"""
    assignments = selection.payload.get("assignments")
    if not isinstance(assignments, list) or not assignments:
        raise ReleaseGateError(R_INPUTS_INVALID, "selection.assignments 必须是非空数组")
    by_suite: dict[str, dict[str, str]] = {suite: {} for suite in SELECTION_SUITES}
    seen: dict[str, str] = {}
    for index, item in enumerate(assignments):
        row = exact_keys(item, _SELECTION_ASSIGNMENT_KEYS, what=f"selection.assignments[{index}]")
        suite = require_text(row.get("suite"), "assignment.suite")
        case_id = require_text(row.get("case_id"), "assignment.case_id")
        run_id = require_text(row.get("run_id"), "assignment.run_id")
        if suite not in SELECTION_SUITES:
            raise ReleaseGateError(R_IDENTITY_MISMATCH, f"选题范围的套件不受支持: {suite}")
        if case_id in seen:
            raise ReleaseGateError(R_DUPLICATE_EVIDENCE, "同一题被重复分配",
                                   {"case_id": case_id, "suites": [seen[case_id], suite]})
        seen[case_id] = suite
        binding = runs.get(run_id)
        if binding is None:
            if suite == "update_delete":
                # U 的真实 run 在 ``u`` 段声明；这里只核对题号覆盖，run 归属由 u 段决定。
                by_suite[suite][case_id] = run_id
                continue
            raise ReleaseGateError(R_IDENTITY_MISMATCH, "选题指向未登记的 run",
                                   {"case_id": case_id, "run_id": run_id})
        if suite not in binding.suites:
            raise ReleaseGateError(R_IDENTITY_MISMATCH, "run 没有声明该套件",
                                   {"case_id": case_id, "run_id": run_id, "suites": list(binding.suites)})
        by_suite[suite][case_id] = run_id
    for suite, ids in SELECTION_SUITES.items():
        if suite not in REQUIRED_SELECTION_SUITES and not by_suite[suite]:
            continue
        if suite == "update_delete":
            extra = sorted(set(by_suite[suite]) - set(ids))
            if extra:
                raise ReleaseGateError(R_IDENTITY_MISMATCH, "U 选题范围出现未知题号",
                                       {"extra": extra})
            by_suite[suite] = {case_id: by_suite[suite][case_id]
                               for case_id in ids if case_id in by_suite[suite]}
            continue
        got = tuple(by_suite[suite])
        if set(got) != set(ids):
            raise ReleaseGateError(
                R_EVIDENCE_MISSING if set(ids) - set(got) else R_IDENTITY_MISMATCH,
                f"{suite} 选题范围与批准分母不一致",
                {"missing": sorted(set(ids) - set(got)), "extra": sorted(set(got) - set(ids))},
            )
        by_suite[suite] = {case_id: by_suite[suite][case_id] for case_id in ids}
    return by_suite


def _load_public(ref: Mapping[str, Any], root: Path) -> tuple[Mapping[str, Any], tuple[RunBinding, ...], BoundJSON]:
    exact_keys(ref, _PUBLIC_KEYS, what="public")
    selection = _load_selection(ref.get("selection"), root)
    raw_runs = ref.get("runs")
    if not isinstance(raw_runs, list) or not raw_runs:
        raise ReleaseGateError(R_EVIDENCE_MISSING, "public.runs 不能为空")
    by_run: dict[str, RunBinding] = {}
    for item in raw_runs:
        binding = load_run_binding(item, root, expected_suites=("negative", "boundary"))
        existing = by_run.get(binding.run_id)
        if existing is None:
            by_run[binding.run_id] = binding
            continue
        if (existing.run_dir != binding.run_dir or existing.artifacts != binding.artifacts
                or existing.original != binding.original):
            raise ReleaseGateError(R_IDENTITY_MISMATCH, "同一 run 的两次声明绑定不一致",
                                   {"run_id": binding.run_id})
        merged = tuple(dict.fromkeys(existing.suites + binding.suites))
        by_run[binding.run_id] = dataclasses.replace(
            existing, suites=merged,
            applicability=existing.applicability or binding.applicability,
            rag_db=existing.rag_db or binding.rag_db,
            binding_proof=existing.binding_proof or binding.binding_proof,
        )
    runs = tuple(by_run.values())
    suites = {suite for item in runs for suite in item.suites}
    if suites != {"negative", "boundary"}:
        raise ReleaseGateError(R_EVIDENCE_MISSING, "public.runs 必须同时覆盖 N 与 C 两组来源",
                               {"suites": sorted(suites)})
    validate_selection(selection, by_run)
    return dict(ref), runs, selection


def _load_u(ref: Mapping[str, Any], root: Path) -> tuple[Mapping[str, Any], BoundJSON | None, RunBinding]:
    """U 段：真实 smoke 必填（必须含 U01）；本地控制可选（缺省=全部 run 级）。"""
    exact_keys(ref, _U_KEYS, what="u", optional=("local_controls",))
    controls = None
    if ref.get("local_controls") is not None:
        controls = bind_json("u.local_controls", ref.get("local_controls"), root)
    real_raw = exact_keys(ref.get("real"), _U_REAL_KEYS, what="u.real", optional=_U_OPTIONAL)
    case_ids = real_raw.get("case_ids")
    if not isinstance(case_ids, list) or not case_ids or any(
            str(item) not in P2_UPDATE_DELETE_IDS for item in case_ids):
        raise ReleaseGateError(R_IDENTITY_MISMATCH, "u.real.case_ids 必须是 U01–U10 的非空子集",
                               {"observed": case_ids})
    if "U01" not in [str(item) for item in case_ids]:
        raise ReleaseGateError(R_IDENTITY_MISMATCH, "U 真实 smoke 必须含 U01", {"observed": case_ids})
    if len({str(item) for item in case_ids}) != len(case_ids):
        raise ReleaseGateError(R_DUPLICATE_EVIDENCE, "u.real.case_ids 有重复", {"observed": case_ids})
    if real_raw.get("suite") != "update_delete":
        raise ReleaseGateError(R_IDENTITY_MISMATCH, "u.real.suite 必须是 update_delete",
                               {"observed": real_raw.get("suite")})
    real_ref = {key: real_raw[key] for key in _PUBLIC_RUN_KEYS}
    for key in _PUBLIC_RUN_OPTIONAL:
        if real_raw.get(key) is not None:
            real_ref[key] = real_raw[key]
    real = load_run_binding(real_ref, root, expected_suites=("update_delete",))
    return dict(ref), controls, real


def _load_h2(ref: Mapping[str, Any], root: Path):
    exact_keys(ref, _H2_KEYS, what="h2", optional=_H2_OPTIONAL)
    source_proof = bind_json("h2.source_proof", ref.get("source_proof"), root)
    has_full = ref.get("composition") is not None and ref.get("cards") is not None
    has_aggregate = (ref.get("composition_aggregate") is not None
                     and ref.get("cards_index") is not None)
    if not has_full and not has_aggregate:
        raise ReleaseGateError(R_EVIDENCE_MISSING,
                               "h2 需要 (composition + cards) 或 (composition_aggregate + cards_index)")
    if has_full and has_aggregate:
        raise ReleaseGateError(R_INPUTS_INVALID, "h2 不能同时声明全量卡与聚合视图两种来源")
    if has_aggregate:
        return (dict(ref), None, source_proof, (),
                bind_json("h2.composition_aggregate", ref.get("composition_aggregate"), root),
                bind_json("h2.cards_index", ref.get("cards_index"), root))
    composition = bind_json("h2.composition", ref.get("composition"), root)
    raw_cards = ref.get("cards")
    if not isinstance(raw_cards, list) or len(raw_cards) != len(H2_SCENARIO_ORDER):
        raise ReleaseGateError(R_EVIDENCE_MISSING, "h2.cards 必须恰好四张")
    cards: list[BoundJSON] = []
    seen: list[str] = []
    for index, item in enumerate(raw_cards):
        row = exact_keys(item, _H2_CARD_KEYS, what=f"h2.cards[{index}]")
        scenario_id = require_text(row.get("scenario_id"), "h2.cards.scenario_id")
        if scenario_id != H2_SCENARIO_ORDER[index]:
            raise ReleaseGateError(R_IDENTITY_MISMATCH, "h2.cards 顺序/场景 id 与冻结顺序不符",
                                   {"index": index, "expected": H2_SCENARIO_ORDER[index],
                                    "observed": scenario_id})
        if scenario_id in seen:
            raise ReleaseGateError(R_DUPLICATE_EVIDENCE, "同一场景卡被重复声明", {"scenario_id": scenario_id})
        seen.append(scenario_id)
        cards.append(bind_json(f"h2.card:{scenario_id}",
                               {"path": row.get("path"), "sha256": row.get("sha256")}, root))
    return dict(ref), composition, source_proof, tuple(cards), None, None


def _load_pending(ref: Any) -> dict[str, str]:
    if not isinstance(ref, Mapping):
        raise ReleaseGateError(R_INPUTS_INVALID, "pending 必须是对象")
    unknown = sorted(set(ref) - set(PENDING_SECTIONS))
    if unknown:
        raise ReleaseGateError(R_INPUTS_INVALID, "pending 出现未登记段", {"unknown": unknown})
    for key, value in ref.items():
        if value not in PENDING_MARKERS:
            raise ReleaseGateError(R_INPUTS_INVALID, f"pending[{key}] 标记不受支持",
                                   {"marker": value, "allowed": list(PENDING_MARKERS)})
    return {str(key): str(value) for key, value in ref.items()}


# --------------------------------------------------------------------------- #
# 入口
# --------------------------------------------------------------------------- #


def load_release_inputs(path: Path | str, *, project_root: Path | str | None = None) -> ReleaseInputs:
    """显式加载正式门禁输入清单；任何缺失/错配都按固定原因码阻断。"""
    root = Path(project_root) if project_root is not None else PROJECT_ROOT
    target = Path(path)
    if not target.is_absolute():
        target = root / target
    if not target.is_file():
        raise ReleaseGateError(R_EVIDENCE_MISSING, "输入清单不存在", {"path": str(target)})
    raw = target.read_bytes()
    try:
        import json

        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeError, ValueError):
        raise ReleaseGateError(R_INPUTS_INVALID, "输入清单不是合法 UTF-8 JSON") from None
    exact_keys(payload, _INPUTS_KEYS, what="inputs", optional=_INPUTS_OPTIONAL)
    if payload.get("schema_version") != INPUTS_SCHEMA_VERSION:
        raise ReleaseGateError(R_VERSION_MISMATCH, "输入清单 schema 版本不符",
                               {"expected": INPUTS_SCHEMA_VERSION, "observed": payload.get("schema_version")})
    pending = _load_pending(payload.get("pending") or {})
    for section in PENDING_SECTIONS:
        present = section in payload
        if present and section in pending:
            raise ReleaseGateError(R_INPUTS_INVALID, f"{section} 既声明待交付又提供了内容")
        if not present and section not in pending:
            raise ReleaseGateError(R_EVIDENCE_MISSING, f"{section} 缺失且未标记待交付")

    gate_config, gate_config_path = _load_gate_config(payload.get("gate_config"), root)
    candidate_sha, candidate_version = _load_candidate(payload.get("candidate_pipeline"))
    baseline, admission, approval, b0_run_dir = _load_b0(payload.get("b0"), root)

    document_codes = None
    if payload.get("document_codes") is not None:
        document_codes = bind_json("document_codes", payload["document_codes"], root)
    evidence_manifest = evidence_report = evidence_sums = None
    if payload.get("evidence_manifest") is not None:
        ref = exact_keys(payload["evidence_manifest"], _EVIDENCE_MANIFEST_KEYS,
                         what="evidence_manifest", optional=_EVIDENCE_MANIFEST_OPTIONAL)
        evidence_manifest = bind_json("evidence_manifest.manifest", ref["manifest"], root)
        if ref.get("report") is not None:
            evidence_report = bind_file("evidence_manifest.report", ref["report"], root)
        if ref.get("sha256sums") is not None:
            evidence_sums = bind_file("evidence_manifest.sha256sums", ref["sha256sums"], root)
    public = public_runs = selection = None
    if "public" in payload:
        public, public_runs, selection = _load_public(payload["public"], root)
    u = controls = real = None
    if "u" in payload:
        u, controls, real = _load_u(payload["u"], root)
    h2 = composition = source_proof = None
    cards: tuple[BoundJSON, ...] = ()
    aggregate_view = cards_index = None
    if "h2" in payload:
        h2, composition, source_proof, cards, aggregate_view, cards_index = _load_h2(
            payload["h2"], root)
    if (public is not None or u is not None) and document_codes is None:
        raise ReleaseGateError(R_EVIDENCE_MISSING, "交付 public/u 时必须提供 document_codes 绑定")
    if selection is not None and u is not None:
        frozen_u = tuple(
            str(item.get("case_id")) for item in selection.payload.get("assignments") or ()
            if isinstance(item, Mapping) and item.get("suite") == "update_delete"
        )
        declared_u = tuple(str(case_id) for case_id in
                           (u.get("real") or {}).get("case_ids") or ())
        if frozen_u and declared_u != frozen_u:
            raise ReleaseGateError(R_IDENTITY_MISMATCH, "u.real.case_ids 与冻结选题范围不一致",
                                   {"frozen": list(frozen_u), "declared": list(declared_u)})

    return ReleaseInputs(
        path=target,
        sha256=payload_sha256_bytes(raw),
        gate_config=gate_config,
        gate_config_path=gate_config_path,
        candidate_pipeline_sha256=candidate_sha,
        candidate_pipeline_version=candidate_version,
        b0_baseline=baseline,
        b0_admission=admission,
        b0_approval=approval,
        b0_run_dir=b0_run_dir,
        evidence_manifest=evidence_manifest,
        evidence_report=evidence_report,
        evidence_sums=evidence_sums,
        public=public,
        public_runs=tuple(public_runs or ()),
        selection=selection,
        document_codes=document_codes,
        u=u,
        u_controls=controls,
        u_real=real,
        h2=h2,
        h2_composition=composition,
        h2_source_proof=source_proof,
        h2_cards=cards,
        h2_composition_aggregate=aggregate_view,
        h2_cards_index=cards_index,
        pending=pending,
    )


__all__ = [
    "APPLICABILITY_SCHEMA_VERSION",
    "B0_BASELINE_ID",
    "B0_GATE_CONFIG_HASH",
    "B0_GATE_FILE_SHA256",
    "B0_RUN_ID",
    "BoundFile",
    "BoundJSON",
    "FROZEN_TEMPLATE_CONFIG_HASH",
    "FROZEN_TEMPLATE_PATH",
    "FROZEN_TEMPLATE_SHA256",
    "GATE_SUITE_NAME",
    "H2_SCENARIO_CASE_COUNTS",
    "H2_SCENARIO_ORDER",
    "H2_SCENARIO_TURNS",
    "PUBLIC_ARTIFACTS",
    "ReleaseInputs",
    "RunBinding",
    "SELECTION_SUITES",
    "bind_file",
    "bind_json",
    "load_release_inputs",
    "payload_sha256_bytes",
    "validate_selection",
]

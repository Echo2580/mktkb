"""历史绑定适用性证明：把"索引版本计数口径"这件事做成可复算的证明，而不是豁免。

背景（经理已代码级核实，本模块复核同一事实）：

* ``rag/retrieval.py`` 把 ``trace.index_revision`` 写成 ``rag_meta.revision``（RAG 索引计数）；
* ``evaluation/product_adapter.py::binding_components`` 把 ``manifest.index_revision`` 写成
  **产品** revision；
* ``gate.py::_TRACE_BINDING`` 把这两个语义不同的同名计数器当同一身份比较，于是任何走过
  RAG 检索的轮次都会机械地报 ``version_binding`` 失败；
* 已采纳的修复标准（T209 attempt3 起）= **绑定值取实际 RAG 索引版本**，历史 run 的
  manifest 绑的是产品计数，属绑定侧缺陷，不是 trace 造假。

因此本模块**不改 gate.py**，而是：

1. 从原始工件重算 ``rag_meta.revision`` 与逐轮产品 revision，生成/校验证明；
2. 用原始 manifest 跑一次硬门禁，**如实保留**机械失败；
3. 仅在证明校验通过时，用 attested revision 构造门禁视图再跑一次；
4. 两个结果都进输出，并标注 ``binding_correction_applied`` 与原值/修正值/证明摘要。

零真实请求：只读本地 sqlite 与既有 run 工件。
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .p2_release_inputs import RunBinding
from .p2_release_model import (
    R_BINDING_ATTESTATION_INVALID,
    R_BINDING_PROOF_MISSING,
    R_EVIDENCE_MISSING,
    R_IDENTITY_MISMATCH,
    R_VERSION_MISMATCH,
    ReleaseGateError,
    exact_keys,
    file_sha256,
    payload_sha256,
    require_digest,
    require_int,
    require_text,
    sha256_bytes,
)

#: 证明契约版本。
BINDING_PROOF_SCHEMA_VERSION = "p2-release-binding-applicability/v0.1"
#: 规则字符串（固定；不允许自由发挥）。
BINDING_RULE = "adopted-standard:gate_binding_value_is_actual_rag_index_revision"
#: 引用的先例（T209 attempt3 起 trace_integrity=pass 的正式 B0 首次通过记录 + 其准入留存）。
BINDING_PRECEDENT_ARTIFACTS: tuple[Path, ...] = (
    Path(__file__).resolve().parents[4]
    / "docs" / "reports" / "OBS-EVAL" / "P2" / "T209-PREP" / "b0-live-execution-attempt3-report.md",
    Path(__file__).resolve().parents[4]
    / "var" / "eval" / "baselines" / "7981d4afc2d1" / "b0-admission.json",
)

_PROOF_KEYS = (
    "schema_version",
    "run_id",
    "plan_sha256",
    "manifest_sha256",
    "recorded_index_revision",
    "attested_index_revision",
    "rule",
    "attestation",
    "gate_replay",
)
_ATTESTATION_KEYS = ("rag_source", "product_source", "precedent")
_RAG_KEYS = ("db_path", "db_sha256", "read_key", "read_value")
_PRODUCT_KEYS = ("cases_sha256", "per_turn", "values_sha256")
_PRECEDENT_KEYS = ("artifact", "sha256", "claim")
_REPLAY_KEYS = ("original_binding_failures", "corrected_binding_failures",
                "rewritten_trace_rows", "trace_rows_total",
                "trace_rows_not_at_attested", "post_update_not_at_attested",
                "original_trace_db_sha256")


class _BindingError(ValueError):
    def __init__(self, reason: str, cause: str, detail: Mapping[str, Any] | None = None) -> None:
        super().__init__(f"{reason}: {cause}")
        self.reason = reason
        self.cause = cause
        self.detail = dict(detail or {})


# --------------------------------------------------------------------------- #
# 原工件重算
# --------------------------------------------------------------------------- #


def read_rag_revision(db_path: Path) -> int:
    """只读打开 run 的 rag DB，读 ``rag_meta.revision``（不接受调用方自报）。"""
    if not db_path.is_file():
        raise ReleaseGateError(R_EVIDENCE_MISSING, "rag 索引库不存在", {"path": str(db_path)})
    try:
        connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.Error:
        raise ReleaseGateError(R_BINDING_ATTESTATION_INVALID, "rag 索引库打不开") from None
    try:
        row = connection.execute("select value from rag_meta where key='revision'").fetchone()
    except sqlite3.Error:
        raise ReleaseGateError(R_BINDING_ATTESTATION_INVALID, "rag_meta 读取失败") from None
    finally:
        connection.close()
    if row is None:
        raise ReleaseGateError(R_BINDING_ATTESTATION_INVALID, "rag_meta.revision 缺失")
    try:
        return int(str(row[0]).strip())
    except ValueError:
        raise ReleaseGateError(R_BINDING_ATTESTATION_INVALID, "rag_meta.revision 不是整数") from None


def product_turn_revisions(binding: RunBinding) -> list[dict[str, Any]]:
    """从原 cases.jsonl 逐轮回读 ``product.revision``（产品计数）。"""
    rows: list[dict[str, Any]] = []
    for line in binding.artifact_bytes("cases.jsonl").decode("utf-8").splitlines():
        if not line.strip():
            continue
        case = json.loads(line)
        for turn in case.get("turns") or ():
            product = turn.get("product") if isinstance(turn.get("product"), Mapping) else {}
            rows.append({
                "case_id": str(case.get("case_id") or ""),
                "turn": int(turn.get("turn") or 0),
                "revision": product.get("revision"),
            })
    return rows


def _revisions_digest(rows: Sequence[Mapping[str, Any]]) -> str:
    return payload_sha256([[row["case_id"], row["turn"], row["revision"]] for row in rows])


def record_code_units(db_path: Path, record_code: str) -> list[dict[str, Any]]:
    """按记录码在 run 自身的 rag 单元里定位（``P01`` -> sheet:物品位置:row:8 这类）。"""
    if not db_path.is_file():
        raise ReleaseGateError(R_EVIDENCE_MISSING, "rag 索引库不存在", {"path": str(db_path)})
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        rows = connection.execute(
            "select distinct u.unit_id, u.unit_key, u.sheet, u.row_number, u.locator "
            "from rag_units as u, json_each(u.locator, '$.cells') as cell "
            "where json_extract(cell.value, '$.display') = ? limit 8",
            (record_code,),
        ).fetchall()
    except sqlite3.Error:
        return []
    finally:
        connection.close()
    units = []
    for unit_id, unit_key, sheet, row_number, locator in rows:
        units.append({"unit_id": unit_id, "unit_key": unit_key, "sheet": sheet,
                      "row": row_number, "locator": json.loads(locator) if locator else {}})
    return units


# --------------------------------------------------------------------------- #
# 生成 / 校验
# --------------------------------------------------------------------------- #


def _plan_sha256(binding: RunBinding) -> str:
    plan = binding.manifest.get("plan") if isinstance(binding.manifest.get("plan"), Mapping) else {}
    value = plan.get("plan_sha256") or binding.manifest.get("plan_sha256")
    if not isinstance(value, str) or len(value) != 64:
        raise ReleaseGateError(R_IDENTITY_MISMATCH, "run_manifest 缺少 plan_sha256")
    return value


def build_binding_proof(binding: RunBinding, *, rag_db: Path,
                        replay: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """按原工件重算一条绑定适用性证明（与其它证明同构：声明值必须等于重算值）。"""
    recorded = binding.manifest.get("index_revision")
    attested = read_rag_revision(rag_db)
    turns = product_turn_revisions(binding)
    precedent = []
    for artifact in BINDING_PRECEDENT_ARTIFACTS:
        precedent.append({
            "artifact": str(artifact),
            "sha256": file_sha256(artifact),
            "claim": "T209 attempt3 起正式 B0 采用'绑定=实际 RAG 索引版本'并通过 trace_integrity",
        })
    return {
        "schema_version": BINDING_PROOF_SCHEMA_VERSION,
        "run_id": binding.run_id,
        "plan_sha256": _plan_sha256(binding),
        "manifest_sha256": binding.artifacts["run_manifest.json"],
        "recorded_index_revision": int(recorded),
        "attested_index_revision": int(attested),
        "rule": BINDING_RULE,
        "attestation": {
            "rag_source": {
                "db_path": str(rag_db),
                "db_sha256": file_sha256(rag_db),
                "read_key": "rag_meta.revision",
                "read_value": int(attested),
            },
            "product_source": {
                "cases_sha256": binding.artifacts["cases.jsonl"],
                "per_turn": turns,
                "values_sha256": _revisions_digest(turns),
            },
            "precedent": precedent,
        },
        "gate_replay": {
            "original_binding_failures": list((replay or {}).get("original_binding_failures") or ()),
            "corrected_binding_failures": list((replay or {}).get("corrected_binding_failures") or ()),
            "rewritten_trace_rows": int((replay or {}).get("rewritten_trace_rows") or 0),
            "trace_rows_total": int((replay or {}).get("trace_rows_total") or 0),
            "trace_rows_not_at_attested": int((replay or {}).get("trace_rows_not_at_attested") or 0),
            "post_update_not_at_attested": int((replay or {}).get("post_update_not_at_attested") or 0),
            "original_trace_db_sha256": str((replay or {}).get("original_trace_db_sha256") or ""),
        },
    }


def validate_binding_proof(
    declared: Any, rebuilt: Mapping[str, Any], *, binding: RunBinding
) -> dict[str, Any]:
    """逐字段重算比对；伪造、错配、跨 run、无修正都拒绝。"""
    if not isinstance(declared, Mapping):
        raise ReleaseGateError(R_BINDING_PROOF_MISSING, "绑定适用性证明必须是对象")
    exact_keys(declared, _PROOF_KEYS, what="binding_proof", code=R_BINDING_ATTESTATION_INVALID)
    if declared.get("schema_version") != BINDING_PROOF_SCHEMA_VERSION:
        raise ReleaseGateError(R_VERSION_MISMATCH, "绑定证明 schema 版本不符",
                               {"observed": declared.get("schema_version")})
    if declared.get("run_id") != binding.run_id:
        raise ReleaseGateError(R_IDENTITY_MISMATCH, "绑定证明属于另一个 run",
                               {"declared": declared.get("run_id"), "run": binding.run_id})
    if declared.get("rule") != BINDING_RULE:
        raise ReleaseGateError(R_BINDING_ATTESTATION_INVALID, "绑定证明规则字符串不符")
    recorded = require_int(declared.get("recorded_index_revision"), "recorded_index_revision")
    attested = require_int(declared.get("attested_index_revision"), "attested_index_revision")
    if recorded == attested:
        raise ReleaseGateError(R_VERSION_MISMATCH, "证明值等于原值：没有修正却声称已修正")
    if attested != rebuilt["attested_index_revision"]:
        raise ReleaseGateError(
            R_BINDING_ATTESTATION_INVALID, "attested 与 rag_meta.revision 不符",
            {"declared": attested, "actual": rebuilt["attested_index_revision"]},
        )
    if recorded != rebuilt["recorded_index_revision"]:
        raise ReleaseGateError(R_BINDING_ATTESTATION_INVALID, "recorded 与 run_manifest 不符",
                               {"declared": recorded, "actual": rebuilt["recorded_index_revision"]})
    attestation = declared.get("attestation")
    if not isinstance(attestation, Mapping):
        raise ReleaseGateError(R_BINDING_ATTESTATION_INVALID, "attestation 缺失")
    exact_keys(attestation, _ATTESTATION_KEYS, what="binding_proof.attestation",
               code=R_BINDING_ATTESTATION_INVALID)
    rag = exact_keys(attestation.get("rag_source"), _RAG_KEYS, what="attestation.rag_source",
                     code=R_BINDING_ATTESTATION_INVALID)
    if require_digest(rag.get("db_sha256"), "rag_source.db_sha256") != rebuilt["attestation"]["rag_source"]["db_sha256"]:
        raise ReleaseGateError(R_BINDING_ATTESTATION_INVALID, "rag 索引库摘要不符（工件被换过）")
    if rag.get("read_key") != "rag_meta.revision" or rag.get("read_value") != attested:
        raise ReleaseGateError(R_BINDING_ATTESTATION_INVALID, "rag 读出值与证明不符")
    product = exact_keys(attestation.get("product_source"), _PRODUCT_KEYS,
                         what="attestation.product_source", code=R_BINDING_ATTESTATION_INVALID)
    if require_digest(product.get("cases_sha256"), "product_source.cases_sha256") != \
            rebuilt["attestation"]["product_source"]["cases_sha256"]:
        raise ReleaseGateError(R_BINDING_ATTESTATION_INVALID, "逐轮产品证据 digest 不符")
    if product.get("per_turn") != rebuilt["attestation"]["product_source"]["per_turn"]:
        raise ReleaseGateError(R_BINDING_ATTESTATION_INVALID, "逐轮 product.revision 与回读不符")
    if require_digest(product.get("values_sha256"), "product_source.values_sha256") != \
            rebuilt["attestation"]["product_source"]["values_sha256"]:
        raise ReleaseGateError(R_BINDING_ATTESTATION_INVALID, "逐轮 revision 向量 digest 不符")
    precedent = attestation.get("precedent")
    if not isinstance(precedent, list) or len(precedent) != len(BINDING_PRECEDENT_ARTIFACTS):
        raise ReleaseGateError(R_BINDING_ATTESTATION_INVALID, "先例工件缺失")
    for index, item in enumerate(precedent):
        row = exact_keys(item, _PRECEDENT_KEYS, what=f"precedent[{index}]",
                         code=R_BINDING_ATTESTATION_INVALID)
        if require_digest(row.get("sha256"), "precedent.sha256") != \
                rebuilt["attestation"]["precedent"][index]["sha256"]:
            raise ReleaseGateError(R_BINDING_ATTESTATION_INVALID, "先例工件摘要不符",
                                   {"artifact": row.get("artifact")})
    replay = exact_keys(declared.get("gate_replay"), _REPLAY_KEYS, what="binding_proof.gate_replay",
                        code=R_BINDING_ATTESTATION_INVALID)
    if not replay.get("original_binding_failures"):
        raise ReleaseGateError(R_EVIDENCE_MISSING, "缺少原始机械结果（只给修正后结果不算证明）")
    if replay.get("corrected_binding_failures"):
        raise ReleaseGateError(R_BINDING_ATTESTATION_INVALID, "修正视图仍有机械失败")
    rewritten = require_int(replay.get("rewritten_trace_rows"), "rewritten_trace_rows", minimum=0)
    total_rows = require_int(replay.get("trace_rows_total"), "trace_rows_total", minimum=1)
    not_at_attested = require_int(replay.get("trace_rows_not_at_attested"),
                                  "trace_rows_not_at_attested", minimum=0)
    post_update = require_int(replay.get("post_update_not_at_attested"),
                              "post_update_not_at_attested", minimum=0)
    # 零改写是合法结果（该 run 的 trace 本来就全在 attested 值上）；但必须**可证伪**：
    # 改写数必须等于"不在 attested 上的行数"，且改写后该计数必须为 0。
    if rewritten != not_at_attested:
        raise ReleaseGateError(
            R_BINDING_ATTESTATION_INVALID, "改写行数与'不在 attested 上的行数'不符",
            {"rewritten": rewritten, "not_at_attested": not_at_attested},
        )
    if post_update != 0:
        raise ReleaseGateError(
            R_BINDING_ATTESTATION_INVALID, "修正视图仍有不在 attested 上的 trace 行",
            {"post_update_not_at_attested": post_update},
        )
    if rewritten > total_rows:
        raise ReleaseGateError(R_BINDING_ATTESTATION_INVALID, "改写行数超过 trace 总行数",
                               {"rewritten": rewritten, "total": total_rows})
    require_digest(replay.get("original_trace_db_sha256"), "original_trace_db_sha256")
    if declared != rebuilt:
        differing = sorted(key for key in set(declared) | set(rebuilt)
                           if declared.get(key) != rebuilt.get(key))
        raise ReleaseGateError(R_BINDING_ATTESTATION_INVALID, "绑定证明与重算不等",
                               {"fields": differing})
    return dict(declared)


# --------------------------------------------------------------------------- #
# 双跑：原始 manifest vs attested 视图
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class BindingReplay:
    """一次 run 的双跑结果（原始机械结果 + 修正视图 + 依据）。"""

    run_id: str
    recorded: int
    attested: int
    original: Mapping[str, Any]
    corrected: Mapping[str, Any]
    proof_sha256: str

    @property
    def original_failures(self) -> tuple[str, ...]:
        return tuple(self.original.get("binding_failures") or ())

    @property
    def corrected_failures(self) -> tuple[str, ...]:
        return tuple(self.corrected.get("binding_failures") or ())

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "recorded_index_revision": self.recorded,
            "attested_index_revision": self.attested,
            "binding_correction_applied": True,
            "proof_sha256": self.proof_sha256,
            "original": dict(self.original),
            "corrected": dict(self.corrected),
        }


#: 零改写合法性查询（写进证明，加载时重算）：必须 0 行不在 attested 上。
_NOT_AT_ATTESTED_SQL = "select count(*) from traces where index_revision != ?"


def corrected_trace_store(
    binding: RunBinding, *, recorded: int, attested: int, work_dir: Path
) -> dict[str, Any]:
    """派生"修正视图"trace 库，并给出可复算的零改写合法性证据。

    只写派生副本，原库不动。返回 dict：``path`` / ``rewritten`` / ``original_db_sha256`` /
    ``total_rows`` / ``not_at_attested_before`` / ``not_at_attested_after``。

    契约：``rewritten`` 必须等于"不在 attested 上的行数"，改写后该计数必须为 0。
    因此 ``rewritten == 0`` 只在"全部行本来就在 attested 上"时成立——合法的零改写，
    且可被独立重算证伪（伪造成 0 会在重算时暴露真实非零行数）。
    """
    import shutil

    source = Path(str(binding.manifest.get("trace_store") or ""))
    if not source.is_file():
        raise ReleaseGateError(R_EVIDENCE_MISSING, "trace 库不存在", {"path": str(source)})
    work_dir.mkdir(parents=True, exist_ok=True)
    target = work_dir / f"traces-corrected-{binding.run_id}.sqlite3"
    shutil.copy2(source, target)
    connection = sqlite3.connect(str(target))
    try:
        total_rows = int(connection.execute("select count(*) from traces").fetchone()[0])
        not_at_attested_before = int(
            connection.execute(_NOT_AT_ATTESTED_SQL, (str(attested),)).fetchone()[0]
        )
        cursor = connection.execute(
            "update traces set index_revision=? where index_revision=?",
            (str(attested), str(recorded)),
        )
        rewritten = int(cursor.rowcount)
        connection.commit()
        not_at_attested_after = int(
            connection.execute(_NOT_AT_ATTESTED_SQL, (str(attested),)).fetchone()[0]
        )
    finally:
        connection.close()
    if rewritten != not_at_attested_before or not_at_attested_after != 0:
        raise ReleaseGateError(
            R_BINDING_ATTESTATION_INVALID,
            "trace 里存在既非 recorded 也非 attested 的索引版本，无法干净修正",
            {"rewritten": rewritten, "not_at_attested_before": not_at_attested_before,
             "not_at_attested_after": not_at_attested_after, "total_rows": total_rows},
        )
    return {
        "path": target,
        "rewritten": rewritten,
        "original_db_sha256": file_sha256(source),
        "total_rows": total_rows,
        "not_at_attested_before": not_at_attested_before,
        "not_at_attested_after": not_at_attested_after,
    }


def replay_gate_binding(
    binding: RunBinding,
    *,
    cases: Sequence[Any],
    gate_config: Any,
    document_codes: Mapping[str, str],
    rag_db: Path,
    work_dir: Path,
) -> dict[str, Any]:
    """原始视图与修正视图各跑一次硬门禁；两者都留下（不得只报修正后）。"""
    from .p2_release_public import _run_hard_gates_on_run

    recorded = int(binding.manifest.get("index_revision"))
    attested = read_rag_revision(rag_db)
    original_trace = Path(str(binding.manifest.get("trace_store") or ""))
    original = _run_hard_gates_on_run(binding, cases=cases, gate_config=gate_config,
                                      document_codes=document_codes, index_revision=recorded,
                                      trace_store=original_trace if original_trace.is_file() else None)
    corrected_info = corrected_trace_store(
        binding, recorded=recorded, attested=attested, work_dir=work_dir)
    corrected = _run_hard_gates_on_run(binding, cases=cases, gate_config=gate_config,
                                       document_codes=document_codes,
                                       index_revision=attested,
                                       trace_store=corrected_info["path"])
    return {
        "recorded_index_revision": recorded,
        "attested_index_revision": attested,
        "original_binding_failures": list(original["binding_failures"]),
        "corrected_binding_failures": list(corrected["binding_failures"]),
        "rewritten_trace_rows": corrected_info["rewritten"],
        "trace_rows_total": corrected_info["total_rows"],
        "trace_rows_not_at_attested": corrected_info["not_at_attested_before"],
        "post_update_not_at_attested": corrected_info["not_at_attested_after"],
        "original_trace_db_sha256": corrected_info["original_db_sha256"],
        "original": original,
        "corrected": corrected,
    }


def assess_binding(
    binding: RunBinding,
    *,
    cases: Sequence[Any],
    gate_config: Any,
    document_codes: Mapping[str, str],
    work_dir: Path,
    row_id: str | None = None,
) -> tuple[ReleaseRow | None, Mapping[str, Any] | None]:
    """一条 run 的绑定适用性：重算证明 -> 双跑 -> 行（原始与修正都展示）。

    返回 (row, replay)；未声明 rag_db 的 run 也返回一条行（trace 存在则阻断，否则 observed），
    以保证"每个 run 都有 binding 行"的不变量（T4-R1 缺陷 1）。
    """
    from .p2_release_model import row_blocked, row_ok
    from .p2_release_public import row_observed

    row_name = row_id or f"binding.{binding.run_id}"
    title = f"历史绑定适用性 · {binding.run_id}"
    if binding.rag_db is None:
        trace_store = Path(str(binding.manifest.get("trace_store") or ""))
        if trace_store.is_file():
            # 有 trace 证据却没声明 rag 库：无法重算绑定适用性，不得静默跳过。
            return ReleaseGateError(
                R_BINDING_PROOF_MISSING, "该 run 存在 trace 证据但未声明 rag_db",
                {"trace_store": trace_store.name},
            ).to_row(row_name, title), None
        return row_observed(row_name, title, detail={
            "binding_correction_applied": False,
            "note": "该 run 未声明 rag_db 且无 trace 库：无 trace 级证据，绑定适用性不适用",
        }), None
    try:
        replay = replay_gate_binding(binding, cases=cases, gate_config=gate_config,
                                     document_codes=document_codes,
                                     rag_db=binding.rag_db.path, work_dir=work_dir)
        rebuilt = build_binding_proof(
            binding, rag_db=binding.rag_db.path,
            replay={key: replay[key] for key in
                    ("original_binding_failures", "corrected_binding_failures",
                     "rewritten_trace_rows", "trace_rows_total",
                     "trace_rows_not_at_attested", "post_update_not_at_attested",
                     "original_trace_db_sha256")},
        )
        if binding.binding_proof is None:
            raise ReleaseGateError(R_BINDING_PROOF_MISSING, "该 run 需要绑定适用性证明但未提供")
        validate_binding_proof(binding.binding_proof.payload, rebuilt, binding=binding)
    except ReleaseGateError as exc:
        return exc.to_row(row_name, title), None
    except _BindingError as exc:
        return ReleaseGateError(exc.reason, exc.cause, exc.detail).to_row(row_name, title), None
    detail = {
        "binding_correction_applied": True,
        "recorded_index_revision": replay["recorded_index_revision"],
        "attested_index_revision": replay["attested_index_revision"],
        "rule": BINDING_RULE,
        "proof_sha256": binding.binding_proof.sha256,
        "original_mechanical": replay["original"],
        "corrected_view": replay["corrected"],
        "rewritten_trace_rows": replay["rewritten_trace_rows"],
        "trace_rows_total": replay["trace_rows_total"],
        # 零改写是否合法必须与两个计数**同行**出现（派生布尔不得单独作为依据）。
        "zero_rewrite": {
            "legal": replay["rewritten_trace_rows"] == 0,
            "rule": "rewritten == trace_rows_not_at_attested 且 post_update_not_at_attested == 0",
            "trace_rows_not_at_attested": replay["trace_rows_not_at_attested"],
            "post_update_not_at_attested": replay["post_update_not_at_attested"],
        },
        "note": "原始机械失败如实保留；修正视图为派生 trace 视图重放，不写回原库",
    }
    if not replay["original_binding_failures"]:
        return ReleaseGateError(
            R_EVIDENCE_MISSING, "原始视图没有任何 version_binding 失败：没有可修正的机械结果"
        ).to_row(row_name, title), None
    if replay["corrected_binding_failures"]:
        return ReleaseGateError(
            R_BINDING_ATTESTATION_INVALID, "修正视图仍有 version_binding 失败",
            {"failures": replay["corrected_binding_failures"]},
        ).to_row(row_name, title), None
    return row_ok(row_name, title, detail=detail,
                  evidence=(f"binding_proof:{binding.binding_proof.sha256[:16]}",)), replay


__all__ = [
    "BINDING_PRECEDENT_ARTIFACTS",
    "BINDING_PROOF_SCHEMA_VERSION",
    "BINDING_RULE",
    "assess_binding",
    "build_binding_proof",
    "corrected_trace_store",
    "product_turn_revisions",
    "read_rag_revision",
    "record_code_units",
    "replay_gate_binding",
    "validate_binding_proof",
]

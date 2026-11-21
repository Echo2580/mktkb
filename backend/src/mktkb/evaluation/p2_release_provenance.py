"""N/C/U 送检清单的回源校验（FU-3）：题目、证据、身份、trace、U 证据类型。

背景（任务书 §4）：正式门禁的 ``cross_check_evidence_manifest`` 只承接"清单声明的四档 /
两行 tally / SHA256SUMS / run 身份"，**没有**默认做逐题回源。已有一份有效但只作报告的脚本
``docs/reports/OBS-EVAL/P2/NCU-RELEASE-EVIDENCE/scripts/verify_manifest.py``，本模块把它的
判定语义（固定原因码同名）接进**正常送检入口**：``evaluate_release_gate`` 加载到
``evidence_manifest`` 时默认调用，问题一律阻断（绝不降级成待定/通过）。

本模块只读：不写历史证据、不改冻结清单、不重跑任何真实调用。负例覆盖（任务书 §4）：

* 合法十六进制但**内容错配**的题目摘要（冻结题面 / 原 run dataset / 原 run 产品行三处比对）；
* **缺失或越界**证据路径（按已批准根目录解析：仓库根 + 各 run 的 run_dir 与 rag 库目录）；
* 证据文件**摘要不符** / 未声明摘要（无法核内容的按缺证阻断）；
* **trace 互换**：同 run 不同回合（用该题在原 ``cases.jsonl`` 行里的 trace_id 绑定）、
  跨 run（trace 库内查不到或 run_id 不符）、身份字段不符；
* **U 真实/本地类型混用**（R 档带本地控制字段、L 档带 run 证据字段）与 L 档受控测试
  映射/结果不完整。

缺权威来源（清单不是对象、trace 库打不开、冻结题集不可读）时保持**阻断**，并给出固定
``source_unavailable`` 标签。
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from .p2_release_model import (
    R_DIGEST_MISMATCH,
    R_DUPLICATE_EVIDENCE,
    R_EVIDENCE_MISSING,
    R_IDENTITY_MISMATCH,
    ReleaseRow,
    file_sha256,
    row_blocked,
    row_observed,
    row_ok,
)
from .p2_release_inputs import PROJECT_ROOT, ReleaseInputs

#: 回源校验契约版本（改动判定语义必须升版本，历史适用性随之失效）。
PROVENANCE_SCHEMA_VERSION = "p2-release-provenance/v0.1"

#: R 档每题必须具备的证据件（缺一项即"缺少权威来源"）。
_R_REQUIRED_EVIDENCE = ("run_cases", "run_dataset", "frozen_cases", "trace_db")
#: 只允许出现在 R（真实 run）档的字段；出现在 L 档 = 类型混用。
_R_ONLY_FIELDS = (
    "run_id", "run_dir", "trace_id", "trace_path", "trace_outcome",
    "question_sha256", "plan_id", "plan_sha256", "config_hash",
    "index_revision_binding", "index_revision_trace", "index_revision_rag",
    "index_revision_product_response", "binding_proof", "mechanical_gate_failures",
)
#: 只允许出现在 L（本地控制）档的字段；出现在 R 档 = 类型混用。
_L_ONLY_FIELDS = ("source", "historical", "rerun", "test_file", "test_file_sha256")

_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")

#: 稳定的问题码（与 verify_manifest.py 同名；新增码必须进本表）。
_QUESTION_DIGEST_MISMATCH = "QUESTION_HASH_MISMATCH"
_EVIDENCE_PATH_MISSING = "EVIDENCE_PATH_MISSING"
_EVIDENCE_PATH_OUT_OF_ROOT = "EVIDENCE_PATH_OUT_OF_ROOT"
_EVIDENCE_SHA_MISMATCH = "EVIDENCE_SHA_MISMATCH"
_EVIDENCE_SHA_MISSING = "EVIDENCE_SHA_MISSING"
_EVIDENCE_NOT_DECLARED = "EVIDENCE_NOT_DECLARED"
_TRACE_NOT_IN_RUN = "TRACE_NOT_IN_RUN"
_TRACE_CASE_MISMATCH = "TRACE_CASE_MISMATCH"
_TRACE_IDENTITY_MISMATCH = "TRACE_IDENTITY_MISMATCH"
_TRACE_DUPLICATE = "TRACE_DUPLICATE"
_U_TYPE_MIXED = "U_TYPE_MIXED"
_U_CONTROL_INCOMPLETE = "U_CONTROL_INCOMPLETE"
_SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
_DUPLICATE_CASE = "DUPLICATE_CASE"

_TRACE_IDENTITY_FIELDS = (
    "config_hash", "pipeline_version", "dataset_version",
    "path", "outcome_kind", "manifest_sha256",
)


@dataclass
class ProvenanceReport:
    """一次回源校验的结果（问题逐条带固定码；计数供验收对账）。"""

    problems: list[dict[str, Any]] = field(default_factory=list)
    cases_checked: int = 0
    files_checked: int = 0
    files_verified: int = 0
    traces_checked: int = 0
    u_real_cases: int = 0
    u_local_cases: int = 0
    source_unavailable: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems

    def add(self, code: str, *, case_id: str = "", name: str = "", detail: str = "") -> None:
        item: dict[str, Any] = {"code": code}
        if case_id:
            item["case_id"] = str(case_id)
        if name:
            item["name"] = str(name)
        if detail:
            item["detail"] = str(detail)
        self.problems.append(item)

    def as_detail(self) -> dict[str, Any]:
        return {
            "schema_version": PROVENANCE_SCHEMA_VERSION,
            "cases_checked": int(self.cases_checked),
            "files_checked": int(self.files_checked),
            "files_verified": int(self.files_verified),
            "traces_checked": int(self.traces_checked),
            "u_real_cases": int(self.u_real_cases),
            "u_local_cases": int(self.u_local_cases),
            "source_unavailable": list(self.source_unavailable),
            "problem_count": len(self.problems),
            "problems": self.problems[:20],
        }


def _digest(value: Any) -> str:
    text = str(value or "")
    return text if _DIGEST_RE.match(text) else ""


def _sha256_text(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def approved_evidence_roots(inputs: ReleaseInputs, project_root: Path) -> tuple[Path, ...]:
    """已批准的证据根：仓库根 + 各 run 的 run_dir / 仓外数据目录 / 该 run 的仓外根。

    仓外根 = rag 库所在 ``data`` 目录的父目录（历史 run 把 ``dataset.jsonl`` 放在
    ``<run根>\\p2-run\\``、把 trace/rag 库放在 ``<run根>\\data\\``）。三处都是**按字节
    绑定过的 run 身份**推导出来的，不是调用方随手给的目录。
    """
    roots: list[Path] = [Path(project_root).resolve()]
    runs: list[Any] = list(inputs.public_runs)
    if inputs.u_real is not None:
        runs.append(inputs.u_real)
    for run in runs:
        try:
            roots.append(Path(run.run_dir).resolve())
        except OSError:  # pragma: no cover - 路径异常按缺根处理（该 run 的证据会被拒）
            continue
        rag_db = getattr(run, "rag_db", None)
        if rag_db is not None and getattr(rag_db, "path", None) is not None:
            data_dir = Path(rag_db.path).resolve().parent
            roots.append(data_dir)
            roots.append(data_dir.parent)
    unique: list[Path] = []
    for root in roots:
        if root not in unique:
            unique.append(root)
    return tuple(unique)


def _resolve_evidence(
    raw: Any, *, roots: Sequence[Path], root: Path
) -> tuple[Path | None, str]:
    """把清单里的证据路径按已批准根解析；越界/空值返回 (None, 原因)。"""
    text = str(raw or "").strip()
    if not text:
        return None, "empty"
    candidate = Path(text)
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        resolved = candidate.resolve()
    except OSError:
        return None, "unresolvable"
    for allowed in roots:
        try:
            if resolved == allowed or resolved.is_relative_to(allowed):
                return resolved, ""
        except ValueError:  # pragma: no cover - 不同盘符
            continue
    return None, "outside_approved_roots"


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text:
            continue
        row = json.loads(text)
        if isinstance(row, Mapping):
            rows.append(dict(row))
    return rows


class _EvidenceReader:
    """带缓存的只读证据读取（同一文件只读一次；失败记 source_unavailable）。"""

    def __init__(self, report: ProvenanceReport) -> None:
        self._report = report
        self._jsonl: dict[Path, list[dict[str, Any]]] = {}
        self._traces: dict[Path, dict[str, dict[str, Any]]] = {}

    def jsonl(self, path: Path) -> list[dict[str, Any]] | None:
        if path not in self._jsonl:
            try:
                self._jsonl[path] = _load_jsonl(path)
            except (OSError, ValueError) as exc:
                self._unavailable(path, exc)
                self._jsonl[path] = []
        return self._jsonl[path]

    def _unavailable(self, path: Path, exc: BaseException) -> None:
        label = f"{path.name}:{type(exc).__name__}"
        if label not in self._report.source_unavailable:
            self._report.source_unavailable.append(label)
        self._report.add(_SOURCE_UNAVAILABLE, name=path.name, detail=type(exc).__name__)

    def traces(self, path: Path) -> dict[str, dict[str, Any]] | None:
        if path not in self._traces:
            try:
                con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
                con.row_factory = sqlite3.Row
                try:
                    rows = [dict(row) for row in con.execute("select * from traces")]
                finally:
                    con.close()
            except (OSError, sqlite3.Error) as exc:
                self._unavailable(path, exc)
                self._traces[path] = {}
            else:
                self._traces[path] = {str(row.get("trace_id")): row for row in rows}
        return self._traces[path]


def _check_evidence_files(
    case: Mapping[str, Any], *, roots: Sequence[Path], root: Path,
    report: ProvenanceReport, require: Sequence[str] = (),
) -> dict[str, Path]:
    """逐件核证据路径与摘要；返回 名字 -> 已解析路径（只含通过者）。"""
    case_id = str(case.get("case_id") or "")
    declared = case.get("evidence_paths")
    shas = case.get("evidence_sha256")
    if not isinstance(declared, Mapping) or not declared:
        report.add(_EVIDENCE_PATH_MISSING, case_id=case_id, name="evidence_paths",
                   detail="not_declared")
        return {}
    if not isinstance(shas, Mapping):
        shas = {}
    resolved: dict[str, Path] = {}
    for name, raw in declared.items():
        label = str(name)
        path, reason = _resolve_evidence(raw, roots=roots, root=root)
        if path is None:
            report.add(_EVIDENCE_PATH_OUT_OF_ROOT, case_id=case_id, name=label, detail=reason)
            continue
        report.files_checked += 1
        if not path.is_file():
            report.add(_EVIDENCE_PATH_MISSING, case_id=case_id, name=label)
            continue
        declared_sha = _digest(shas.get(label))
        if not declared_sha:
            report.add(_EVIDENCE_SHA_MISSING, case_id=case_id, name=label)
            continue
        actual = file_sha256(path)
        if actual != declared_sha:
            report.add(_EVIDENCE_SHA_MISMATCH, case_id=case_id, name=label,
                       detail=f"declared={declared_sha[:16]} actual={actual[:16]}")
            continue
        report.files_verified += 1
        resolved[label] = path
    for name in require:
        if name not in resolved:
            if name not in declared:
                report.add(_EVIDENCE_NOT_DECLARED, case_id=case_id, name=name)
    return resolved


def _check_question_digest(
    case: Mapping[str, Any], *, evidence: Mapping[str, Path], reader: _EvidenceReader,
    report: ProvenanceReport,
) -> None:
    """题面摘要 = 冻结题面 / 原 run dataset / 原 run 产品行 三处内容级一致。"""
    case_id = str(case.get("case_id") or "")
    declared = _digest(case.get("question_sha256"))
    if not declared:
        report.add(_QUESTION_DIGEST_MISMATCH, case_id=case_id, name="question_sha256",
                   detail="not_lower_hex64")
        return
    frozen = evidence.get("frozen_cases")
    if frozen is not None:
        rows = reader.jsonl(frozen) or []
        spec = next((row for row in rows if str(row.get("case_id")) == case_id), None)
        if spec is None:
            report.add(_QUESTION_DIGEST_MISMATCH, case_id=case_id, name="frozen_cases",
                       detail="case_not_in_frozen")
        elif _sha256_text(str(spec.get("question") or "")) != declared:
            report.add(_QUESTION_DIGEST_MISMATCH, case_id=case_id, name="frozen_cases")
    dataset = evidence.get("run_dataset")
    if dataset is not None:
        rows = reader.jsonl(dataset) or []
        spec = next((row for row in rows if str(row.get("case_id")) == case_id), None)
        if spec is None:
            report.add(_QUESTION_DIGEST_MISMATCH, case_id=case_id, name="run_dataset",
                       detail="case_not_in_run_dataset")
        elif _sha256_text(str(spec.get("question") or "")) != declared:
            report.add(_QUESTION_DIGEST_MISMATCH, case_id=case_id, name="run_dataset")
    run_cases = evidence.get("run_cases")
    if run_cases is not None:
        rows = reader.jsonl(run_cases) or []
        row = next((item for item in rows if str(item.get("case_id")) == case_id), None)
        if row is None:
            report.add(_QUESTION_DIGEST_MISMATCH, case_id=case_id, name="run_cases",
                       detail="case_not_in_run_cases")
            return
        if str(row.get("run_id") or "") != str(case.get("run_id") or ""):
            report.add(_TRACE_CASE_MISMATCH, case_id=case_id, name="run_cases_run_id")
        turns = [turn for turn in (row.get("turns") or []) if isinstance(turn, Mapping)]
        product = (turns[0].get("product") if turns else {}) or {}
        if not isinstance(product, Mapping) or str(product.get("question_sha256") or "") != declared:
            report.add(_QUESTION_DIGEST_MISMATCH, case_id=case_id, name="run_cases_product")
        trace_ids = {str(turn.get("trace_id") or "") for turn in turns}
        if str(case.get("trace_id") or "") not in trace_ids:
            # 同 run 不同回合/同位题面的 trace 互换在这里落网：该题的原始行只认自己的 trace。
            report.add(_TRACE_CASE_MISMATCH, case_id=case_id, name="trace_id_not_in_case_row")


def _check_trace(
    case: Mapping[str, Any], *, evidence: Mapping[str, Path], reader: _EvidenceReader,
    run_manifest: Mapping[str, Any] | None, report: ProvenanceReport,
    seen: dict[str, str],
) -> None:
    """trace 归属与身份：必须在该 run 的 trace 库里、且逐字段与本 run/本题一致。"""
    case_id = str(case.get("case_id") or "")
    trace_id = str(case.get("trace_id") or "").strip()
    if not trace_id:
        report.add(_TRACE_NOT_IN_RUN, case_id=case_id, detail="trace_id_missing")
        return
    if trace_id in seen and seen[trace_id] != case_id:
        report.add(_TRACE_DUPLICATE, case_id=case_id, name=trace_id,
                   detail=f"also_used_by={seen[trace_id]}")
        return
    seen[trace_id] = case_id
    trace_db = evidence.get("trace_db")
    if trace_db is None:
        return  # 已由证据缺失报出
    table = reader.traces(trace_db) or {}
    trace = table.get(trace_id)
    if trace is None:
        report.add(_TRACE_NOT_IN_RUN, case_id=case_id, name=trace_id)
        return
    report.traces_checked += 1
    declared_q = _digest(case.get("question_sha256"))
    if str(trace.get("question_hash") or "") != declared_q:
        report.add(_TRACE_CASE_MISMATCH, case_id=case_id, name="trace.question_hash")
    if str(trace.get("run_id") or "") != str(case.get("run_id") or ""):
        report.add(_TRACE_CASE_MISMATCH, case_id=case_id, name="trace.run_id")
    expected = {
        "config_hash": case.get("config_hash"),
        "pipeline_version": case.get("pipeline_version"),
        "dataset_version": (run_manifest or {}).get("dataset_version"),
        "path": case.get("trace_path"),
        "outcome_kind": case.get("trace_outcome"),
        "manifest_sha256": (run_manifest or {}).get("corpus_manifest_sha256"),
    }
    for name in _TRACE_IDENTITY_FIELDS:
        want = expected.get(name)
        got = trace.get(name)
        if want in (None, "") or got in (None, ""):
            if want not in (None, ""):
                report.add(_TRACE_IDENTITY_MISMATCH, case_id=case_id, name=f"trace.{name}",
                           detail="evidence_value_missing")
            continue
        if str(got) != str(want):
            report.add(_TRACE_IDENTITY_MISMATCH, case_id=case_id, name=f"trace.{name}")
    declared_rev = case.get("index_revision_trace")
    try:
        got_rev = int(str(trace.get("index_revision")))
    except (TypeError, ValueError):
        got_rev = None
    if declared_rev is None or got_rev != int(declared_rev):
        report.add(_TRACE_IDENTITY_MISMATCH, case_id=case_id, name="trace.index_revision")


def _check_u_local(
    case: Mapping[str, Any], *, roots: Sequence[Path], root: Path,
    controls: Mapping[str, Any] | None, report: ProvenanceReport,
) -> None:
    """L 档：受控测试文件可核 + 历史/重跑结果完整 + 本地控制清单里有该题且 pass。"""
    case_id = str(case.get("case_id") or "")
    test_file = str(case.get("test_file") or "").strip()
    declared_sha = _digest(case.get("test_file_sha256"))
    if not test_file:
        report.add(_U_CONTROL_INCOMPLETE, case_id=case_id, name="test_file", detail="not_declared")
    elif not declared_sha:
        report.add(_U_CONTROL_INCOMPLETE, case_id=case_id, name="test_file_sha256",
                   detail="not_lower_hex64")
    else:
        path, reason = _resolve_evidence(test_file, roots=roots, root=root)
        if path is None:
            report.add(_EVIDENCE_PATH_OUT_OF_ROOT, case_id=case_id, name="test_file", detail=reason)
        elif not path.is_file():
            report.add(_EVIDENCE_PATH_MISSING, case_id=case_id, name="test_file")
        else:
            report.files_checked += 1
            if file_sha256(path) != declared_sha:
                report.add(_EVIDENCE_SHA_MISMATCH, case_id=case_id, name="test_file_sha256")
            else:
                report.files_verified += 1
    historical = case.get("historical")
    if not isinstance(historical, Mapping):
        report.add(_U_CONTROL_INCOMPLETE, case_id=case_id, name="historical", detail="missing")
    else:
        tests = [item for item in (historical.get("tests") or []) if isinstance(item, Mapping)]
        if str(historical.get("status") or "") != "pass":
            report.add(_U_CONTROL_INCOMPLETE, case_id=case_id, name="historical.status",
                       detail=str(historical.get("status")))
        if int(historical.get("exit_code") if isinstance(historical.get("exit_code"), int) else -1) != 0:
            report.add(_U_CONTROL_INCOMPLETE, case_id=case_id, name="historical.exit_code")
        if not tests or any(str(item.get("status") or "") != "pass" for item in tests):
            report.add(_U_CONTROL_INCOMPLETE, case_id=case_id, name="historical.tests")
    rerun = case.get("rerun")
    if not isinstance(rerun, Mapping):
        report.add(_U_CONTROL_INCOMPLETE, case_id=case_id, name="rerun", detail="missing")
    else:
        try:
            exit_code = int(rerun.get("exit_code"))
            failed = int(rerun.get("failed") or 0)
            passed = int(rerun.get("passed") or 0)
        except (TypeError, ValueError):
            exit_code, failed, passed = -1, 1, 0
        if exit_code != 0 or failed != 0 or passed < 1:
            report.add(_U_CONTROL_INCOMPLETE, case_id=case_id, name="rerun",
                       detail=f"exit={exit_code} passed={passed} failed={failed}")
    controls_cases = {}
    if isinstance(controls, Mapping):
        raw_cases = controls.get("cases")
        if isinstance(raw_cases, Mapping):
            controls_cases = raw_cases
    entry = controls_cases.get(case_id) if isinstance(controls_cases, Mapping) else None
    if not isinstance(entry, Mapping):
        report.add(_U_CONTROL_INCOMPLETE, case_id=case_id, name="u_controls",
                   detail="case_not_in_local_controls")
    elif str(entry.get("status") or "") != "pass":
        report.add(_U_CONTROL_INCOMPLETE, case_id=case_id, name="u_controls.status",
                   detail=str(entry.get("status")))


def check_evidence_provenance(
    inputs: ReleaseInputs,
    *,
    project_root: Path | str | None = None,
    approved_roots: Sequence[Path] | None = None,
) -> ProvenanceReport:
    """对送检清单做逐题回源校验；返回问题集合（空 = 全通过）。"""
    report = ProvenanceReport()
    bound = inputs.evidence_manifest
    payload = None if bound is None else bound.payload
    if not isinstance(payload, Mapping):
        report.add(_SOURCE_UNAVAILABLE, name="evidence_manifest", detail="not_an_object")
        return report
    root = Path(project_root).resolve() if project_root is not None else PROJECT_ROOT
    roots = tuple(approved_roots) if approved_roots is not None else approved_evidence_roots(
        inputs, root
    )
    if not roots:
        report.add(_SOURCE_UNAVAILABLE, name="approved_roots", detail="empty")
        return report
    run_manifests = {run.run_id: run.manifest for run in inputs.public_runs}
    if inputs.u_real is not None:
        run_manifests[inputs.u_real.run_id] = inputs.u_real.manifest
    controls_payload = None if inputs.u_controls is None else inputs.u_controls.payload
    reader = _EvidenceReader(report)
    cases = [case for case in (payload.get("cases") or ()) if isinstance(case, Mapping)]
    if not cases:
        report.add(_SOURCE_UNAVAILABLE, name="cases", detail="empty_or_not_list")
        return report
    seen_case_ids: set[str] = set()
    seen_traces: dict[str, str] = {}
    for case in cases:
        case_id = str(case.get("case_id") or "")
        report.cases_checked += 1
        if not case_id:
            report.add(_DUPLICATE_CASE, detail="case_id_missing")
            continue
        if case_id in seen_case_ids:
            report.add(_DUPLICATE_CASE, case_id=case_id)
            continue
        seen_case_ids.add(case_id)
        basis = str(case.get("basis") or "")
        evidence = _check_evidence_files(
            case, roots=roots, root=root, report=report,
            require=_R_REQUIRED_EVIDENCE if basis == "R" else (),
        )
        if basis == "R":
            report.u_real_cases += 1 if str(case.get("group")) == "U" else 0
            for name in _L_ONLY_FIELDS:
                if name in case:
                    report.add(_U_TYPE_MIXED, case_id=case_id, name=name, detail="R_case_with_local_field")
            _check_question_digest(case, evidence=evidence, reader=reader, report=report)
            _check_trace(case, evidence=evidence, reader=reader,
                         run_manifest=run_manifests.get(str(case.get("run_id") or "")),
                         report=report, seen=seen_traces)
        elif basis == "L":
            if str(case.get("group")) == "U":
                report.u_local_cases += 1
            for name in _R_ONLY_FIELDS:
                if name in case:
                    report.add(_U_TYPE_MIXED, case_id=case_id, name=name, detail="L_case_with_run_field")
            _check_u_local(case, roots=roots, root=root, controls=controls_payload, report=report)
        else:
            report.add(_U_TYPE_MIXED, case_id=case_id, name="basis", detail=str(basis or "missing"))
    return report


def provenance_rows(report: ProvenanceReport) -> tuple[ReleaseRow, ...]:
    """把回源结论折成门禁行：有问题 → 阻断（固定原因码，不降级为待定/通过）。"""
    if report.source_unavailable and report.cases_checked == 0:
        return (row_blocked(
            "evidence_provenance", "N/C/U 回源校验（题目/证据/trace）",
            R_EVIDENCE_MISSING, cause="source_unavailable",
            detail=report.as_detail(),
        ),)
    codes = {problem.get("code") for problem in report.problems}
    reasons: list[str] = []
    if codes & {_QUESTION_DIGEST_MISMATCH, _EVIDENCE_SHA_MISMATCH, _EVIDENCE_SHA_MISSING}:
        reasons.append(R_DIGEST_MISMATCH)
    if codes & {_EVIDENCE_PATH_MISSING, _EVIDENCE_PATH_OUT_OF_ROOT, _EVIDENCE_NOT_DECLARED,
                _SOURCE_UNAVAILABLE, _U_CONTROL_INCOMPLETE}:
        reasons.append(R_EVIDENCE_MISSING)
    if codes & {_TRACE_NOT_IN_RUN, _TRACE_CASE_MISMATCH, _TRACE_IDENTITY_MISMATCH, _U_TYPE_MIXED}:
        reasons.append(R_IDENTITY_MISMATCH)
    if _TRACE_DUPLICATE in codes or _DUPLICATE_CASE in codes:
        reasons.append(R_DUPLICATE_EVIDENCE)
    detail = report.as_detail()
    if not report.ok:
        distinct = sorted(reasons) or [R_IDENTITY_MISMATCH]
        return (row_blocked("evidence_provenance", "N/C/U 回源校验（题目/证据/trace）",
                            *distinct, cause="provenance_failed", detail=detail),)
    return (
        row_ok("evidence_provenance", "N/C/U 回源校验（题目/证据/trace）", detail=detail),
        row_observed("evidence_provenance.u_types", "U 真实/本地证据类型（R/L 分列）",
                     detail={"u_real_cases": report.u_real_cases,
                             "u_local_cases": report.u_local_cases,
                             "mixed": 0}),
    )


__all__ = [
    "PROVENANCE_SCHEMA_VERSION",
    "ProvenanceReport",
    "approved_evidence_roots",
    "check_evidence_provenance",
    "provenance_rows",
]

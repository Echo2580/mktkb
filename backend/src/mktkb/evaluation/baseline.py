"""T007：Baseline 身份、建立与审批（设计 §8.3 / §8.5；P0 计划 Task 6 Step 3）。

**身份口径（写死，不依赖门禁侧的回退校验）**::

    baseline_id = sha256(
        dataset_version + pipeline_version + mode + scope + gate_version + corpus_sha256
    )[:12]

- 六字段按上面的顺序做**字面拼接**（不插分隔符），UTF-8 编码后取 SHA-256 的前 12 位
  小写十六进制；每个字段必须非空，``mode`` 只允许 ``local`` / ``replay``（``live``
  不能建立 baseline）；
- ``corpus_sha256`` 取 ``RunManifest.corpus_manifest_sha256``；其余五字段直接取
  ``RunManifest`` 的同名字段；
- 门禁的 ``max_regression_pp`` 只比较 pipeline / suite / dataset，**不足以**充当
  baseline 身份（T006b 验收约束 1），本模块因此自行校验全部六字段并做往返自校验；
- 同输入稳定；任一字段变化（尤其 ``pipeline_version``）→ id 变化。

**审批硬约束**（设计 §8.3）：

- :func:`approve_baseline` 必须同时给出 ``approver`` 与 ``reason``；
- 门禁结果 ``exit_code`` 必须为 0；``exit_code=3``（含阈值未审批）等一律拒绝并给出原因；
- ``quality=False`` 的 ``exit_code=0`` 只代表硬门禁通过，不能作为 baseline 审批依据
  （T006b 验收约束 4），因此要求门禁**已评估质量层**；
- 通过时写 ``approval.json``：``run_id`` / ``gate_result_sha256`` / ``dataset_version`` /
  ``pipeline_version`` / ``corpus_sha256`` / ``approver`` / ``reason`` / ``approved_at``，
  并附 ``baseline_id`` / ``mode`` / ``scope`` / ``gate_version`` / ``gate_exit_code`` /
  ``quality_status``；审批只写一次，不覆盖。

**跨版本**（设计 §8.3）：加载 / 比较不同 ``pipeline_version`` 的 baseline 默认抛
:class:`CrossVersionBaselineError`；只有显式 ``compare_with=<baseline_id>`` 才允许，
且仅用于分析（放行判断在 :mod:`mktkb.evaluation.report` 里固定拒绝）。

**禁止 copy / rename**：本模块没有、也不会提供复制或改名 baseline 的函数；同一
``baseline_id`` 只能绑定一个 ``run_id``，同身份的另一轮 run 不能覆盖已建立的 baseline。

输入只读：``RunResult`` 与其 run 目录三件套（``run_manifest.json`` / ``cases.jsonl`` /
``summary.json``）；本模块只写 ``root/<baseline_id>/`` 下的 ``baseline.json`` 与
``approval.json``，不调用 provider、不建索引、不读 ``.env``。
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .gate import GateResult, load_run_result
from .runner import RunManifest, RunResult

__all__ = [
    "APPROVAL_SCHEMA_VERSION",
    "BASELINE_ID_FIELDS",
    "BASELINE_MODES",
    "BASELINE_SCHEMA_VERSION",
    "Baseline",
    "BaselineApproval",
    "BaselineApprovalError",
    "BaselineComparabilityError",
    "BaselineError",
    "BaselineGate",
    "BaselineIdentity",
    "BaselineIdentityError",
    "CrossVersionBaselineError",
    "approve_baseline",
    "baseline_id",
    "baseline_identity",
    "gate_result_digest",
    "load_baseline",
    "save_baseline",
]

BASELINE_SCHEMA_VERSION = "mktkb.baseline.v0.1"
APPROVAL_SCHEMA_VERSION = "mktkb.baseline.approval.v0.1"

#: 身份的六个字段（顺序即 ``baseline_id`` 的拼接顺序）。
BASELINE_ID_FIELDS: tuple[str, ...] = (
    "dataset_version",
    "pipeline_version",
    "mode",
    "scope",
    "gate_version",
    "corpus_sha256",
)
BASELINE_MODES: tuple[str, ...] = ("local", "replay")
#: run 目录里必须存在的三件套（baseline 只记录摘要，不复制产物）。
RUN_ARTIFACTS: tuple[str, ...] = ("run_manifest.json", "cases.jsonl", "summary.json")
BASELINE_FILENAME = "baseline.json"
APPROVAL_FILENAME = "approval.json"
_IDENTITY_PATTERN = re.compile(r"^[0-9a-f]{12}$")


class BaselineError(ValueError):
    """baseline 相关的 fail-closed 错误基类。"""


class BaselineIdentityError(BaselineError):
    """身份字段缺失 / 非法 / 与 run 目录不一致 / id 不可校验。"""


class BaselineApprovalError(BaselineError):
    """审批参数或门禁结果不满足硬约束。"""


class CrossVersionBaselineError(BaselineError):
    """跨 ``pipeline_version``，且没有显式 ``compare_with``（或试图放行）。"""


class BaselineComparabilityError(BaselineError):
    """dataset / corpus / gate / mode / scope 口径不可比。"""


# --------------------------------------------------------------------------- #
# 身份
# --------------------------------------------------------------------------- #


def _source_mapping(source: Any) -> Mapping[str, Any]:
    if isinstance(source, BaselineIdentity):
        return source.to_dict()
    if isinstance(source, RunResult):
        source = source.manifest
    if isinstance(source, RunManifest):
        return source.to_dict()
    if isinstance(source, Mapping):
        return source
    raise BaselineIdentityError(
        "baseline 身份只能从 RunManifest / RunResult / BaselineIdentity / 映射读取，"
        f"收到 {type(source).__name__}"
    )


def _identity_value(payload: Mapping[str, Any], name: str) -> str:
    keys = (
        ("corpus_manifest_sha256", "corpus_sha256")
        if name == "corpus_sha256"
        else (name,)
    )
    value = next((payload[key] for key in keys if key in payload), None)
    if not isinstance(value, str) or not value.strip():
        raise BaselineIdentityError(
            f"baseline 身份字段 {name} 缺失或不是非空字符串（读取 {list(keys)!r}，收到 {value!r}）"
        )
    return value


def _validate_mode(mode: str) -> str:
    if mode not in BASELINE_MODES:
        raise BaselineIdentityError(
            f"baseline 的 mode 只允许 {list(BASELINE_MODES)}，收到 {mode!r}"
            "（live 不能建立 baseline）"
        )
    return mode


@dataclass(frozen=True)
class BaselineIdentity:
    """baseline 的完整六字段身份；``baseline_id`` 是它的**派生值**，不单独信任。"""

    dataset_version: str
    pipeline_version: str
    mode: str
    scope: str
    gate_version: str
    corpus_sha256: str

    def __post_init__(self) -> None:
        for name in BASELINE_ID_FIELDS:
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise BaselineIdentityError(f"baseline 身份字段 {name} 必须是非空字符串")
        _validate_mode(self.mode)

    def canonical(self) -> str:
        """按 ``BASELINE_ID_FIELDS`` 顺序字面拼接（文档化的 digest 输入）。"""
        return "".join(getattr(self, name) for name in BASELINE_ID_FIELDS)

    @property
    def baseline_id(self) -> str:
        return hashlib.sha256(self.canonical().encode("utf-8")).hexdigest()[:12]

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in BASELINE_ID_FIELDS}

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "BaselineIdentity":
        if not isinstance(payload, Mapping):
            raise BaselineIdentityError("baseline identity 必须是 JSON 对象")
        missing = [name for name in BASELINE_ID_FIELDS if name not in payload]
        if missing:
            raise BaselineIdentityError(f"baseline identity 缺少字段: {missing}")
        values = {name: payload[name] for name in BASELINE_ID_FIELDS}
        return cls(**values)


def baseline_identity(source: Any) -> BaselineIdentity:
    """从 manifest / run / 映射构造并校验完整身份（六字段非空 + mode 合法）。"""
    payload = _source_mapping(source)
    return BaselineIdentity(
        **{name: _identity_value(payload, name) for name in BASELINE_ID_FIELDS}
    )


def baseline_id(source: Any) -> str:
    """``sha256(dataset_version + pipeline_version + mode + scope + gate_version +
    corpus_sha256)[:12]``；每次调用都重新校验六字段，不复用门禁的弱身份校验。"""
    return baseline_identity(source).baseline_id


# --------------------------------------------------------------------------- #
# 门禁结果快照 / 审批
# --------------------------------------------------------------------------- #


def gate_result_digest(gate: GateResult) -> str:
    """门禁结果的规范摘要（``GateResult.to_dict()`` 的 canonical JSON 的 SHA-256）。

    用于把 ``approval.json`` 绑定到**具体一份**门禁结果，而不是"某次通过"的口头声明。
    """
    if not isinstance(gate, GateResult):
        raise BaselineApprovalError(
            f"gate 必须是 GateResult，收到 {type(gate).__name__}"
        )
    canonical = json.dumps(
        gate.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class BaselineGate:
    """建立 baseline 时那一轮门禁结果的只读快照（不是审批本身）。"""

    exit_code: int
    quality_status: str
    gate_status: Mapping[str, str]
    hard_failures: tuple[str, ...]
    gate_version: str
    gate_result_sha256: str
    run_id: str
    suite: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "exit_code": self.exit_code,
            "quality_status": self.quality_status,
            "gate_status": dict(self.gate_status),
            "hard_failures": list(self.hard_failures),
            "gate_version": self.gate_version,
            "gate_result_sha256": self.gate_result_sha256,
            "run_id": self.run_id,
            "suite": self.suite,
        }

    @classmethod
    def from_gate(cls, gate: GateResult) -> "BaselineGate":
        if not isinstance(gate, GateResult):
            raise BaselineApprovalError(
                f"gate 必须是 GateResult，收到 {type(gate).__name__}"
            )
        return cls(
            exit_code=int(gate.exit_code),
            quality_status=gate.quality_status,
            gate_status={str(key): str(value) for key, value in gate.gate_status.items()},
            hard_failures=tuple(str(item) for item in gate.hard_failures),
            gate_version=str(gate.gate_version),
            gate_result_sha256=gate_result_digest(gate),
            run_id=str(gate.run_id),
            suite=str(gate.suite),
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "BaselineGate":
        if not isinstance(payload, Mapping):
            raise BaselineError("baseline.gate 必须是 JSON 对象")
        try:
            return cls(
                exit_code=int(payload["exit_code"]),
                quality_status=str(payload["quality_status"]),
                gate_status={
                    str(key): str(value)
                    for key, value in dict(payload.get("gate_status") or {}).items()
                },
                hard_failures=tuple(str(item) for item in payload.get("hard_failures") or ()),
                gate_version=str(payload["gate_version"]),
                gate_result_sha256=str(payload["gate_result_sha256"]),
                run_id=str(payload["run_id"]),
                suite=str(payload["suite"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise BaselineError(f"baseline.gate 字段不完整: {exc}") from exc


@dataclass(frozen=True)
class BaselineApproval:
    """``approval.json`` 的不可变视图；``approver`` + ``reason`` 缺一不可。"""

    run_id: str
    gate_result_sha256: str
    dataset_version: str
    pipeline_version: str
    corpus_sha256: str
    approver: str
    reason: str
    approved_at: str
    baseline_id: str = ""
    mode: str = ""
    scope: str = ""
    gate_version: str = ""
    gate_exit_code: int = 0
    quality_status: str = ""
    schema_version: str = APPROVAL_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.approver, str) or not self.approver.strip():
            raise BaselineApprovalError("baseline 审批必须提供非空 approver")
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise BaselineApprovalError("baseline 审批必须提供非空 reason")
        for name in (
            "run_id",
            "gate_result_sha256",
            "dataset_version",
            "pipeline_version",
            "corpus_sha256",
            "approved_at",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise BaselineApprovalError(f"baseline 审批字段 {name} 必须是非空字符串")
        if self.baseline_id and not _IDENTITY_PATTERN.fullmatch(self.baseline_id):
            raise BaselineApprovalError(f"baseline_id 非法: {self.baseline_id!r}")
        if isinstance(self.gate_exit_code, bool) or not isinstance(self.gate_exit_code, int):
            raise BaselineApprovalError("gate_exit_code 必须是整数")
        if self.gate_exit_code != 0:
            raise BaselineApprovalError(
                f"approval 只能记录 exit_code=0 的门禁结果，收到 {self.gate_exit_code}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "baseline_id": self.baseline_id,
            "run_id": self.run_id,
            "gate_result_sha256": self.gate_result_sha256,
            "gate_exit_code": self.gate_exit_code,
            "quality_status": self.quality_status,
            "gate_version": self.gate_version,
            "dataset_version": self.dataset_version,
            "pipeline_version": self.pipeline_version,
            "corpus_sha256": self.corpus_sha256,
            "mode": self.mode,
            "scope": self.scope,
            "approver": self.approver,
            "reason": self.reason,
            "approved_at": self.approved_at,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "BaselineApproval":
        if not isinstance(payload, Mapping):
            raise BaselineApprovalError("approval.json 必须是 JSON 对象")
        required = (
            "run_id",
            "gate_result_sha256",
            "dataset_version",
            "pipeline_version",
            "corpus_sha256",
            "approver",
            "reason",
            "approved_at",
        )
        missing = [name for name in required if name not in payload]
        if missing:
            raise BaselineApprovalError(f"approval.json 缺少字段: {missing}")
        return cls(
            run_id=str(payload["run_id"]),
            gate_result_sha256=str(payload["gate_result_sha256"]),
            dataset_version=str(payload["dataset_version"]),
            pipeline_version=str(payload["pipeline_version"]),
            corpus_sha256=str(payload["corpus_sha256"]),
            approver=str(payload["approver"]),
            reason=str(payload["reason"]),
            approved_at=str(payload["approved_at"]),
            baseline_id=str(payload.get("baseline_id") or ""),
            mode=str(payload.get("mode") or ""),
            scope=str(payload.get("scope") or ""),
            gate_version=str(payload.get("gate_version") or ""),
            gate_exit_code=int(payload.get("gate_exit_code") or 0),
            quality_status=str(payload.get("quality_status") or ""),
            schema_version=str(payload.get("schema_version") or APPROVAL_SCHEMA_VERSION),
        )


# --------------------------------------------------------------------------- #
# Baseline 记录
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Baseline:
    """一个已建立（可能尚未审批）的 baseline；身份完整性在构造时自校验。"""

    baseline_id: str
    identity: BaselineIdentity
    run_id: str
    run_dir: str
    suite: str
    dataset_sha256: str
    label_version: str
    case_count: int
    created_at: str
    artifact_sha256: Mapping[str, str] = field(default_factory=dict)
    gate: BaselineGate | None = None
    approval: BaselineApproval | None = None
    schema_version: str = BASELINE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not _IDENTITY_PATTERN.fullmatch(str(self.baseline_id)):
            raise BaselineIdentityError(f"baseline_id 非法: {self.baseline_id!r}")
        if self.baseline_id != self.identity.baseline_id:
            raise BaselineIdentityError(
                "baseline_id 与 identity 不一致："
                f"{self.baseline_id} != {self.identity.baseline_id}"
            )
        if not isinstance(self.run_id, str) or not self.run_id.strip():
            raise BaselineIdentityError("baseline.run_id 必须是非空字符串")
        if not isinstance(self.run_dir, str) or not self.run_dir.strip():
            raise BaselineIdentityError("baseline.run_dir 必须是非空字符串")
        if self.gate is not None:
            if self.gate.run_id and self.gate.run_id != self.run_id:
                raise BaselineIdentityError(
                    f"baseline.gate.run_id={self.gate.run_id!r} 与 run_id={self.run_id!r} 不一致"
                )
            if self.gate.gate_version and self.gate.gate_version != self.identity.gate_version:
                raise BaselineIdentityError("baseline.gate.gate_version 与身份不一致")
        if self.approval is not None:
            self._check_approval(self.approval)

    def _check_approval(self, approval: BaselineApproval) -> None:
        checks = (
            ("baseline_id", approval.baseline_id, self.baseline_id),
            ("run_id", approval.run_id, self.run_id),
            ("dataset_version", approval.dataset_version, self.identity.dataset_version),
            ("pipeline_version", approval.pipeline_version, self.identity.pipeline_version),
            ("corpus_sha256", approval.corpus_sha256, self.identity.corpus_sha256),
        )
        for name, actual, expected in checks:
            if actual and actual != expected:
                raise BaselineApprovalError(
                    f"approval.{name}={actual!r} 与 baseline 的 {expected!r} 不一致"
                )
        if self.gate is not None:
            if approval.gate_result_sha256 != self.gate.gate_result_sha256:
                raise BaselineApprovalError("approval.gate_result_sha256 与门禁快照不一致")
            if approval.gate_exit_code != self.gate.exit_code:
                raise BaselineApprovalError("approval.gate_exit_code 与门禁快照不一致")

    @property
    def approved(self) -> bool:
        return self.approval is not None

    @property
    def pipeline_version(self) -> str:
        return self.identity.pipeline_version

    @property
    def exit_code(self) -> int | None:
        if self.gate is not None:
            return self.gate.exit_code
        if self.approval is not None:
            return self.approval.gate_exit_code
        return None

    def load_run(self) -> RunResult:
        """只读加载 baseline 指向的 run，并再次核对身份 / run_id / 产物摘要。"""
        run = load_run_result(self.run_dir)
        actual = baseline_identity(run.manifest)
        if actual != self.identity:
            raise BaselineIdentityError(
                "baseline 指向的 run 身份与记录不一致："
                f"{actual.to_dict()} != {self.identity.to_dict()}"
            )
        if run.manifest.run_id != self.run_id:
            raise BaselineIdentityError(
                f"baseline 记录的 run_id={self.run_id!r} 与 run 目录的 "
                f"{run.manifest.run_id!r} 不一致"
            )
        for name, expected in self.artifact_sha256.items():
            path = Path(self.run_dir) / name
            if not path.is_file():
                raise BaselineIdentityError(f"baseline 的 run 产物缺失: {name}")
            if _sha256_file(path) != expected:
                raise BaselineIdentityError(
                    f"baseline 的 run 产物 {name} 摘要与建立时不一致（被改写），拒绝比较"
                )
        return run

    def to_dict(self) -> dict[str, Any]:
        """``baseline.json`` 的内容（审批单独存 ``approval.json``，不内嵌）。"""
        return {
            "schema_version": self.schema_version,
            "baseline_id": self.baseline_id,
            "identity": self.identity.to_dict(),
            "run_id": self.run_id,
            "run_dir": self.run_dir,
            "suite": self.suite,
            "dataset_sha256": self.dataset_sha256,
            "label_version": self.label_version,
            "case_count": self.case_count,
            "created_at": self.created_at,
            "artifact_sha256": dict(self.artifact_sha256),
            "gate": None if self.gate is None else self.gate.to_dict(),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any], approval: BaselineApproval | None = None) -> "Baseline":
        if not isinstance(payload, Mapping):
            raise BaselineError("baseline.json 必须是 JSON 对象")
        schema = str(payload.get("schema_version") or "")
        if schema != BASELINE_SCHEMA_VERSION:
            raise BaselineError(f"baseline schema_version 不兼容: {schema!r}")
        raw_gate = payload.get("gate")
        return cls(
            baseline_id=str(payload.get("baseline_id") or ""),
            identity=BaselineIdentity.from_dict(payload.get("identity") or {}),
            run_id=str(payload.get("run_id") or ""),
            run_dir=str(payload.get("run_dir") or ""),
            suite=str(payload.get("suite") or ""),
            dataset_sha256=str(payload.get("dataset_sha256") or ""),
            label_version=str(payload.get("label_version") or ""),
            case_count=int(payload.get("case_count") or 0),
            created_at=str(payload.get("created_at") or ""),
            artifact_sha256={
                str(key): str(value)
                for key, value in dict(payload.get("artifact_sha256") or {}).items()
            },
            gate=None if raw_gate is None else BaselineGate.from_dict(raw_gate),
            approval=approval,
        )


# --------------------------------------------------------------------------- #
# 文件 IO
# --------------------------------------------------------------------------- #


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _sha256_file(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise BaselineError(f"无法读取 {path}: {exc}") from exc


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    text = json.dumps(dict(payload), ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    path.write_bytes(text.encode("utf-8"))


def _read_json(path: Path, label: str) -> Any:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise BaselineError(f"{label} 不可读 {path}: {exc}") from exc
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BaselineError(f"{label} 不是合法 UTF-8 JSON {path}: {exc}") from exc


def _baseline_dir(baseline_id_value: str, root: Path | str) -> Path:
    if not isinstance(baseline_id_value, str) or not _IDENTITY_PATTERN.fullmatch(baseline_id_value):
        raise BaselineIdentityError(
            f"baseline_id 必须是 12 位小写十六进制，收到 {baseline_id_value!r}"
        )
    return Path(root) / baseline_id_value


def _load_approval_if_present(directory: Path) -> BaselineApproval | None:
    path = directory / APPROVAL_FILENAME
    if not path.is_file():
        return None
    payload = _read_json(path, "approval.json")
    return BaselineApproval.from_dict(payload)


# --------------------------------------------------------------------------- #
# 建立 / 审批 / 加载
# --------------------------------------------------------------------------- #


def _artifact_digests(run: RunResult) -> dict[str, str]:
    out_dir = Path(run.out_dir)
    digests: dict[str, str] = {}
    for name in RUN_ARTIFACTS:
        path = out_dir / name
        if not path.is_file():
            raise BaselineError(
                f"run 目录缺少 {name}：baseline 只记录产物摘要，不复制/伪造产物（{out_dir}）"
            )
        digests[name] = _sha256_file(path)
    on_disk = _read_json(out_dir / "run_manifest.json", "run_manifest.json")
    if not isinstance(on_disk, Mapping):
        raise BaselineError("run_manifest.json 必须是 JSON 对象")
    disk_identity = RunManifest.from_dict(on_disk)
    if baseline_identity(disk_identity) != baseline_identity(run.manifest):
        raise BaselineError(
            "内存中的 run.manifest 与 run 目录的 run_manifest.json 身份不一致，拒绝建立 baseline"
        )
    if disk_identity.run_id != run.manifest.run_id:
        raise BaselineError(
            f"run 目录的 run_id={disk_identity.run_id!r} 与内存 manifest.run_id="
            f"{run.manifest.run_id!r} 不一致，拒绝建立 baseline"
        )
    return digests


def save_baseline(run: RunResult, root: Path | str, *, gate: GateResult | None = None) -> Baseline:
    """按 run 的六字段身份建立 baseline（不做审批）；同身份只能绑定一个 run。

    - 已有同 ``baseline_id`` 且同 ``run_id``：幂等返回；若新增了门禁快照且尚未审批，
      允许补写该快照；
    - 已有同 id 但不同 ``run_id`` / 产物摘要不同：拒绝（禁止用另一轮 run 覆盖）；
    - 已有审批后再试图改动门禁快照：拒绝（审批绑定具体 ``gate_result_sha256``）。
    """
    if not isinstance(run, RunResult):
        raise BaselineError(f"save_baseline 只接受 RunResult，收到 {type(run).__name__}")
    identity = baseline_identity(run.manifest)
    dir_path = _baseline_dir(identity.baseline_id, root)
    existing_path = dir_path / BASELINE_FILENAME
    artifacts = _artifact_digests(run)
    gate_snapshot = None if gate is None else BaselineGate.from_gate(gate)

    if existing_path.is_file():
        existing = Baseline.from_dict(
            _read_json(existing_path, BASELINE_FILENAME),
            approval=_load_approval_if_present(dir_path),
        )
        if existing.identity != identity:
            raise BaselineError("同一 baseline 目录里的 identity 与本次 run 不一致，拒绝覆盖")
        if existing.run_id != run.manifest.run_id:
            raise BaselineError(
                "同一 baseline_id 已绑定 run "
                f"{existing.run_id!r}，拒绝改绑到 {run.manifest.run_id!r}"
                "（设计 §8.3：禁止复制/改名旧 baseline 冒充新版本）"
            )
        if dict(existing.artifact_sha256) != artifacts:
            raise BaselineError("同一 baseline 的 run 产物摘要发生变化，拒绝覆盖")
        if gate_snapshot is not None and gate_snapshot != existing.gate:
            if existing.approval is not None:
                raise BaselineError("baseline 已审批，禁止改动门禁快照")
            existing = replace(existing, gate=gate_snapshot)
            _write_json(existing_path, existing.to_dict())
        if gate_snapshot is None and existing.gate is not None:
            return existing
        return existing

    baseline = Baseline(
        baseline_id=identity.baseline_id,
        identity=identity,
        run_id=run.manifest.run_id,
        run_dir=str(Path(run.out_dir).resolve()),
        suite=str(run.manifest.suite),
        dataset_sha256=str(run.manifest.dataset_sha256),
        label_version=str(run.manifest.label_version),
        case_count=int(run.manifest.case_count),
        created_at=_utc_now(),
        artifact_sha256=artifacts,
        gate=gate_snapshot,
    )
    dir_path.mkdir(parents=True, exist_ok=True)
    _write_json(existing_path, baseline.to_dict())
    return baseline


_EXIT_REASONS: dict[int, str] = {
    0: "通过",
    1: "硬门禁失败（不可豁免）",
    2: "质量回退（绝对阈值未达或 max_regression_pp 超限，且未被质量 waiver）",
    3: (
        "不可判定：数据/配置/gold 不可用、样本不足、阈值未审批（T009 人工门）"
        "或跨版本 baseline"
    ),
    4: "live 未授权",
}


def _reject_approval(run: RunResult, gate: GateResult) -> None:
    if not isinstance(gate, GateResult):
        raise BaselineApprovalError(f"gate 必须是 GateResult，收到 {type(gate).__name__}")
    if not isinstance(gate.exit_code, int) or isinstance(gate.exit_code, bool):
        raise BaselineApprovalError(f"gate.exit_code 必须是整数，收到 {gate.exit_code!r}")
    if gate.exit_code != 0:
        reason = _EXIT_REASONS.get(gate.exit_code, "未知门禁状态")
        raise BaselineApprovalError(
            f"门禁未通过（exit_code={gate.exit_code}：{reason}），不得建立/审批 baseline"
        )
    if gate.quality is None:
        raise BaselineApprovalError(
            "质量层未评估（quality=False）：exit_code=0 只代表硬门禁通过，"
            "不代表质量达标，不能作为 baseline 审批依据（T006b 验收约束 4）"
        )
    if str(gate.quality.config_status) != "approved":
        raise BaselineApprovalError(
            "阈值配置未审批（config_status="
            f"{gate.quality.config_status!r}）：只有 top-level status=approved 才可能通过"
            " baseline 审批，quality_layer.status 只是元数据（T006b 验收约束 2）"
        )
    manifest = run.manifest
    if gate.run_id and gate.run_id != manifest.run_id:
        raise BaselineApprovalError(
            f"gate.run_id={gate.run_id!r} 与 run_id={manifest.run_id!r} 不一致，拒绝审批"
        )
    if gate.suite and gate.suite != manifest.suite:
        raise BaselineApprovalError(
            f"gate.suite={gate.suite!r} 与 suite={manifest.suite!r} 不一致，拒绝审批"
        )
    if gate.gate_version and gate.gate_version != manifest.gate_version:
        raise BaselineApprovalError(
            "gate.gate_version 与 run_manifest.gate_version 不一致，拒绝审批"
        )


def approve_baseline(
    run: RunResult,
    gate: GateResult,
    root: Path | str,
    *,
    approver: str,
    reason: str,
) -> Baseline:
    """审批并写 ``approval.json``；参数或门禁不满足硬约束时**不落盘**。"""
    if not isinstance(approver, str) or not approver.strip():
        raise BaselineApprovalError("baseline 审批必须提供非空 approver")
    if not isinstance(reason, str) or not reason.strip():
        raise BaselineApprovalError("baseline 审批必须提供非空 reason")
    _reject_approval(run, gate)

    baseline = save_baseline(run, root, gate=gate)
    approval = BaselineApproval(
        baseline_id=baseline.baseline_id,
        run_id=baseline.run_id,
        gate_result_sha256=gate_result_digest(gate),
        gate_exit_code=int(gate.exit_code),
        quality_status=gate.quality_status,
        gate_version=str(gate.gate_version),
        dataset_version=baseline.identity.dataset_version,
        pipeline_version=baseline.identity.pipeline_version,
        corpus_sha256=baseline.identity.corpus_sha256,
        mode=baseline.identity.mode,
        scope=baseline.identity.scope,
        approver=approver,
        reason=reason,
        approved_at=_utc_now(),
    )
    dir_path = _baseline_dir(baseline.baseline_id, root)
    approval_path = dir_path / APPROVAL_FILENAME
    if approval_path.is_file():
        existing = _load_approval_if_present(dir_path)
        if existing is not None and (
            existing.run_id,
            existing.gate_result_sha256,
            existing.approver,
            existing.reason,
        ) == (
            approval.run_id,
            approval.gate_result_sha256,
            approval.approver,
            approval.reason,
        ):
            return replace(baseline, approval=existing)
        raise BaselineApprovalError(
            "approval.json 已存在且内容不同，拒绝覆盖（审批只写一次，无 copy/rename 语义）"
        )
    _write_json(approval_path, approval.to_dict())
    return replace(baseline, approval=approval)


def _ensure_comparable(
    reference: BaselineIdentity,
    expected: BaselineIdentity,
    *,
    baseline_id_value: str,
    compare_with: str | None,
) -> None:
    if compare_with is not None and compare_with != baseline_id_value:
        raise CrossVersionBaselineError(
            f"compare_with={compare_with!r} 与 baseline_id={baseline_id_value!r} 不一致"
        )
    if reference.pipeline_version != expected.pipeline_version and compare_with != baseline_id_value:
        raise CrossVersionBaselineError(
            "跨 pipeline_version 的 baseline 默认拒绝："
            f"{reference.pipeline_version!r} != {expected.pipeline_version!r}；"
            "必须显式 compare_with=<baseline_id>（仅分析，不可放行，设计 §8.3）"
        )
    for name in ("dataset_version", "mode", "scope", "gate_version", "corpus_sha256"):
        actual = getattr(reference, name)
        wanted = getattr(expected, name)
        if actual != wanted:
            raise BaselineComparabilityError(
                f"baseline 与当前 run 的 {name} 不可比：{actual!r} != {wanted!r}"
                "（跨版本比较也必须 dataset/corpus/gate 口径一致）"
            )


def load_baseline(
    baseline_id_value: str,
    root: Path | str,
    *,
    expected: Any | None = None,
    compare_with: str | None = None,
) -> Baseline:
    """读取 baseline，并重算 ``baseline_id`` 自校验；跨版本默认拒绝。

    ``expected`` 可传当前 run 的 manifest / RunResult / BaselineIdentity / 映射；只有
    六个身份字段全部可比时才返回（``pipeline_version`` 不同则必须 ``compare_with``）。
    """
    dir_path = _baseline_dir(baseline_id_value, root)
    baseline_path = dir_path / BASELINE_FILENAME
    if not baseline_path.is_file():
        raise BaselineError(f"baseline 不存在: {baseline_path}")
    payload = _read_json(baseline_path, BASELINE_FILENAME)
    baseline = Baseline.from_dict(
        payload, approval=_load_approval_if_present(dir_path)
    )
    if baseline.baseline_id != baseline_id_value:
        raise BaselineIdentityError(
            f"baseline 目录/请求 id {baseline_id_value!r} 与文件内 id {baseline.baseline_id!r} 不一致"
        )
    if baseline.baseline_id != baseline.identity.baseline_id:
        raise BaselineIdentityError(
            "baseline.json 的 identity 不能重算出文件内的 baseline_id（身份被篡改）"
        )
    if expected is not None:
        _ensure_comparable(
            baseline.identity,
            baseline_identity(expected),
            baseline_id_value=baseline.baseline_id,
            compare_with=compare_with,
        )
    elif compare_with is not None and compare_with != baseline.baseline_id:
        raise CrossVersionBaselineError(
            f"compare_with={compare_with!r} 与 baseline_id={baseline.baseline_id!r} 不一致"
        )
    return baseline

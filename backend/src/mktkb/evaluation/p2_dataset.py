"""P2-T202：H2 受限数据集加载器（public 只读元数据 / holdout 加密封存解封）。

为什么单独一个模块（任务书 §6.2 / §8 T202）：
- H2 是新独立封存题集：题目与标签只允许在**受控评测进程**里解封，开发/验收/经理只看
  schema、分层、hash 与聚合；所以公共加载路径不能顺带把题干读出来；
- `visibility` 必须显式给出：`public` 只读 manifest（repo 内元数据，只含 hash/计数/版本），
  **绝不打开封存 root**；`holdout` 必须由运行环境注入 root 与 key 文件，先校验密文
  sha256，再 Fernet 解封，再校验明文 sha256 与数据结构，任何一步不符都 fail closed；
- 错误只带稳定原因码 + 内部结构信息（字段名/行号/计数），**不回显题干或答案正文**；
  返回对象的 `repr` 也不带题目/答案行，避免日志/异常把受限数据带走。

与 `dataset.py` 的关系：本模块**不修改** `dataset.py`（P1 holdout 行为/常量/sha 全部不变），
只复用它的 holdout 契约：`CaseSpec` / `validate_case` / `HoldoutPolicy` 以及逐行校验
`_question_row` / `_label_row`（questions 13 键、labels 11 键、turns/locator 规则、答案字段
白名单）。复用逐行校验而不复制规则，是为了让 H2 与 H1 用**同一套**字段约束：dataset.py
一旦收紧，H2 加载器自动跟随，不会出现两套“差不多”的 schema。

封存布局（root 由 `MKTKB_P2_HOLDOUT_ROOT` 注入，key 由 `MKTKB_P2_HOLDOUT_KEY_FILE` 注入；
仓库内不保存任何明文、密文或 key）::

    <root>/manifest.json              # repo-safe 元数据
    <root>/questions.jsonl.fernet     # questions 明文 JSONL 的 Fernet 密文
    <root>/labels.jsonl.fernet        # labels 明文 JSONL 的 Fernet 密文

解封顺序（任一不符即停，绝不“先跑后补验”）：环境变量 -> root 目录 -> manifest 归属 root ->
manifest 严格校验 -> key 文件 -> 密文存在/大小 -> 密文 sha256 -> Fernet 解封 -> 明文 sha256 ->
逐行 schema 校验 -> 题数/分层/label_version/case_id 唯一与集合相等 -> 轮数与 turn_stats ->
合并 CaseSpec 并 validate_case。全程只在内存里持有明文，不落盘、不打印。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from . import dataset as _dataset
from .dataset import HOLDOUT_ANSWER_FIELDS, HOLDOUT_SUITE, CaseSpec, HoldoutError, HoldoutPolicy

__all__ = [
    "HOLDOUT_KEY_FILE_ENV",
    "HOLDOUT_ROOT_ENV",
    "LABELS_CIPHERTEXT_NAME",
    "P2_CASE_COUNT",
    "P2_DATASET_SUITE",
    "P2_MANIFEST_SCHEMA_VERSION",
    "P2_STRATA",
    "P2_VISIBILITIES",
    "P2Dataset",
    "P2DatasetError",
    "P2Manifest",
    "QUESTIONS_CIPHERTEXT_NAME",
    "REASONS",
    "load_p2_dataset",
]

P2_MANIFEST_SCHEMA_VERSION = "p2-holdout-manifest/v0.1"
P2_DATASET_SUITE = "p2-holdout"
"""manifest 的 `suite`（P2 数据集标识）。注意 questions/labels **行内**的 `suite`/`split`
仍是 dataset.py 的 holdout 契约值 `"holdout"`：行 schema 复用 H1 的 13/11 键定义。"""

P2_CASE_COUNT = 30
"""冻结题数（主人批准的 H2 = 30 题）；manifest 与数据都必须等于它，不能“少两题也算一致”。"""

P2_STRATA: Mapping[str, int] = MappingProxyType(
    {
        "paraphrase": 10,
        "multi_turn": 5,
        "negative": 5,
        "stale_conflict": 5,
        "cross_doc_security": 5,
    }
)
"""冻结分层（10 改写 / 5 多轮 / 5 负样本 / 5 过期冲突 / 5 跨文档安全）。"""

P2_VISIBILITIES = frozenset({"public", "holdout"})
HOLDOUT_ROOT_ENV = "MKTKB_P2_HOLDOUT_ROOT"
HOLDOUT_KEY_FILE_ENV = "MKTKB_P2_HOLDOUT_KEY_FILE"
QUESTIONS_CIPHERTEXT_NAME = "questions.jsonl.fernet"
LABELS_CIPHERTEXT_NAME = "labels.jsonl.fernet"
FERNET_KIND = "fernet"

MAX_MANIFEST_BYTES = 256 * 1024
MAX_SEALED_BYTES = 8 * 1024 * 1024
MAX_KEY_BYTES = 4096

_MANIFEST_FIELDS: tuple[str, ...] = (
    "schema_version",
    "dataset_version",
    "suite",
    "label_version",
    "case_count",
    "strata",
    "business_date",
    "created_utc",
    "author",
    "encryption",
    "questions_plaintext_sha256",
    "labels_plaintext_sha256",
    "questions_ciphertext_sha256",
    "labels_ciphertext_sha256",
    "turn_stats",
)
_ENCRYPTION_FIELDS = frozenset({"kind", "key_id"})
_TURN_STATS_FIELDS = frozenset({"total_turns", "max_turns_per_case", "turn_histogram"})

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,63}$")
_BUCKET_RE = re.compile(r"^[1-9][0-9]{0,2}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_KEY_RE = re.compile(r"^[A-Za-z0-9_-]{43}=$")

REASONS: frozenset[str] = frozenset(
    {
        # 可见性 / manifest
        "visibility_invalid",
        "manifest_missing",
        "manifest_unreadable",
        "manifest_too_large",
        "manifest_not_utf8",
        "manifest_json_invalid",
        "manifest_field_missing",
        "manifest_field_unknown",
        "manifest_schema_version_invalid",
        "manifest_dataset_version_invalid",
        "manifest_suite_invalid",
        "manifest_label_version_invalid",
        "manifest_case_count_invalid",
        "manifest_strata_invalid",
        "manifest_business_date_invalid",
        "manifest_created_utc_invalid",
        "manifest_author_invalid",
        "manifest_encryption_invalid",
        "manifest_sha256_invalid",
        "manifest_turn_stats_invalid",
        # public 与封存 root 的隔离
        "visibility_root_violation",
        # holdout 环境/路径/key
        "holdout_env_missing",
        "holdout_root_invalid",
        "holdout_manifest_outside_root",
        "holdout_key_file_missing",
        "holdout_key_unreadable",
        "holdout_key_invalid",
        "holdout_ciphertext_missing",
        "holdout_ciphertext_unreadable",
        "holdout_ciphertext_too_large",
        # 解封与摘要
        "crypto_unavailable",
        "holdout_decrypt_failed",
        "holdout_ciphertext_sha256_mismatch",
        "holdout_plaintext_sha256_mismatch",
        # 数据契约
        "holdout_questions_invalid",
        "holdout_labels_invalid",
        "holdout_answer_field_leak",
        "holdout_case_count_mismatch",
        "holdout_strata_mismatch",
        "holdout_label_version_mismatch",
        "holdout_duplicate_case_id",
        "holdout_case_id_set_mismatch",
        "holdout_turns_invalid",
        "holdout_turn_stats_mismatch",
        "holdout_case_invalid",
        # 返回对象自身的一致性
        "dataset_inconsistent",
    }
)
"""稳定原因码集合（契约文档逐条列出；测试断言文档与代码不漂移）。"""


class P2DatasetError(ValueError):
    """P2 数据集加载失败：`reason` 是稳定原因码，`detail` 只含字段名/行号/计数。

    调用方必须 fail closed（不降级成空数据、不用 0/空列表冒充“没有数据”）。异常文本里
    **不允许**出现题干/答案正文：所有 detail 都由本模块用结构信息拼装。
    """

    code = "P2_DATASET_INVALID"

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = str(reason)
        self.detail = str(detail)


def _fail(reason: str, detail: str = "") -> P2DatasetError:
    return P2DatasetError(reason, detail)


def _resolve(path: Path) -> Path | None:
    try:
        return Path(path).resolve()
    except OSError:  # pragma: no cover - 极端路径错误（盘符消失等）
        return None


# --------------------------------------------------------------------------- #
# manifest（public 与 holdout 共用同一套严格校验）
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class P2Manifest:
    """`p2-holdout-manifest/v0.1` 的校验结果；只含元数据，可安全打印/入库。"""

    schema_version: str
    dataset_version: str
    suite: str
    label_version: str
    case_count: int
    strata: Mapping[str, int]
    business_date: str
    created_utc: str
    author: str
    encryption: Mapping[str, str]
    questions_plaintext_sha256: str
    labels_plaintext_sha256: str
    questions_ciphertext_sha256: str
    labels_ciphertext_sha256: str
    turn_stats: Mapping[str, Any]
    manifest_sha256: str

    def as_dict(self) -> dict[str, Any]:
        """按 manifest 字段顺序返回可 JSON 序列化的普通对象（T203 写入 run_manifest）。

        turn_stats 的统计口径：单条 case 的轮数 = `turns` 非空时的长度，否则 1
        （turns 非空即完整轮序列）。T203 计划按它算 answer 请求数，别用另一套口径。
        """
        return {
            "schema_version": self.schema_version,
            "dataset_version": self.dataset_version,
            "suite": self.suite,
            "label_version": self.label_version,
            "case_count": int(self.case_count),
            "strata": {name: int(self.strata[name]) for name in P2_STRATA},
            "business_date": self.business_date,
            "created_utc": self.created_utc,
            "author": self.author,
            "encryption": {
                "kind": self.encryption["kind"],
                "key_id": self.encryption["key_id"],
            },
            "questions_plaintext_sha256": self.questions_plaintext_sha256,
            "labels_plaintext_sha256": self.labels_plaintext_sha256,
            "questions_ciphertext_sha256": self.questions_ciphertext_sha256,
            "labels_ciphertext_sha256": self.labels_ciphertext_sha256,
            "turn_stats": {
                "total_turns": int(self.turn_stats["total_turns"]),
                "max_turns_per_case": int(self.turn_stats["max_turns_per_case"]),
                "turn_histogram": {
                    str(key): int(value)
                    for key, value in self.turn_stats["turn_histogram"].items()
                },
            },
        }

    @classmethod
    def from_dict(cls, payload: Any, *, manifest_sha256: str) -> "P2Manifest":
        """严格解析 manifest：未知/缺失字段、类型不符、冻结值不符都拒绝。"""
        if not isinstance(payload, Mapping):
            raise _fail("manifest_json_invalid", "manifest 顶层必须是 JSON 对象")
        _exact_keys(payload, frozenset(_MANIFEST_FIELDS), "manifest")

        schema_version = _token(
            payload["schema_version"], "manifest_schema_version_invalid", "schema_version"
        )
        if schema_version != P2_MANIFEST_SCHEMA_VERSION:
            raise _fail(
                "manifest_schema_version_invalid",
                f"schema_version 必须是 {P2_MANIFEST_SCHEMA_VERSION}",
            )
        dataset_version = _token(
            payload["dataset_version"], "manifest_dataset_version_invalid", "dataset_version"
        )
        suite = _token(payload["suite"], "manifest_suite_invalid", "suite")
        if suite != P2_DATASET_SUITE:
            raise _fail("manifest_suite_invalid", f"suite 必须是 {P2_DATASET_SUITE}")
        label_version = _token(
            payload["label_version"], "manifest_label_version_invalid", "label_version"
        )
        case_count = _integer(
            payload["case_count"], "manifest_case_count_invalid", "case_count", minimum=1
        )
        if case_count != P2_CASE_COUNT:
            raise _fail(
                "manifest_case_count_invalid", f"case_count 必须冻结为 {P2_CASE_COUNT}"
            )
        strata = _parse_strata(payload["strata"], case_count)
        business_date = _business_date(payload["business_date"])
        created_utc = _created_utc(payload["created_utc"])
        author = _plain_text(payload["author"], "manifest_author_invalid", "author", maximum=64)
        encryption = _parse_encryption(payload["encryption"])
        questions_plaintext = _sha256(
            payload["questions_plaintext_sha256"], "questions_plaintext_sha256"
        )
        labels_plaintext = _sha256(payload["labels_plaintext_sha256"], "labels_plaintext_sha256")
        questions_ciphertext = _sha256(
            payload["questions_ciphertext_sha256"], "questions_ciphertext_sha256"
        )
        labels_ciphertext = _sha256(
            payload["labels_ciphertext_sha256"], "labels_ciphertext_sha256"
        )
        turn_stats = _parse_turn_stats(payload["turn_stats"], case_count)
        _sha256(manifest_sha256, "manifest_sha256")
        return cls(
            schema_version=schema_version,
            dataset_version=dataset_version,
            suite=suite,
            label_version=label_version,
            case_count=case_count,
            strata=strata,
            business_date=business_date,
            created_utc=created_utc,
            author=author,
            encryption=encryption,
            questions_plaintext_sha256=questions_plaintext,
            labels_plaintext_sha256=labels_plaintext,
            questions_ciphertext_sha256=questions_ciphertext,
            labels_ciphertext_sha256=labels_ciphertext,
            turn_stats=turn_stats,
            manifest_sha256=manifest_sha256,
        )


# --------------------------------------------------------------------------- #
# 返回对象
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class P2Dataset:
    """一次加载的结果。

    `public` 只带 manifest（`cases` 为空、`labels` 为空）；`holdout` 带合并后的
    `CaseSpec` 行与 labels 映射。`cases`/`labels` 标 `repr=False`：误把对象塞进日志或
    异常时不会把题干/答案打印出来。
    """

    visibility: str
    manifest: P2Manifest
    cases: tuple[CaseSpec, ...] = field(default=(), repr=False)
    labels: Mapping[str, Mapping[str, Any]] = field(
        default_factory=lambda: MappingProxyType({}), repr=False
    )
    metadata_mismatch_count: int = 0

    def __post_init__(self) -> None:
        if self.visibility not in P2_VISIBILITIES:
            raise _fail("visibility_invalid", "dataset.visibility 必须是 public/holdout")
        if not isinstance(self.manifest, P2Manifest):
            raise _fail("dataset_inconsistent", "dataset.manifest 必须是 P2Manifest")
        if not isinstance(self.cases, tuple):
            raise _fail("dataset_inconsistent", "dataset.cases 必须是 tuple")
        if not isinstance(self.labels, Mapping):
            raise _fail("dataset_inconsistent", "dataset.labels 必须是映射")
        if (
            isinstance(self.metadata_mismatch_count, bool)
            or not isinstance(self.metadata_mismatch_count, int)
            or self.metadata_mismatch_count < 0
        ):
            raise _fail("dataset_inconsistent", "metadata_mismatch_count 必须是非负整数")
        if self.visibility == "public":
            if self.cases or self.labels:
                raise _fail("dataset_inconsistent", "public 视图不得携带题目/答案行")
            return
        if len(self.cases) != self.manifest.case_count:
            raise _fail("dataset_inconsistent", "holdout.cases 数量与 manifest.case_count 不一致")
        if len(self.labels) != len(self.cases):
            raise _fail("dataset_inconsistent", "holdout.labels 数量与 cases 不一致")
        if {case.case_id for case in self.cases} != set(self.labels):
            raise _fail("dataset_inconsistent", "holdout labels 的 case_id 集合与 cases 不一致")

    def label_for(self, case_id: str) -> Mapping[str, Any]:
        """取某题 labels（holdout 专用）；public 视图没有答案，直接报错。"""
        if self.visibility != "holdout":
            raise _fail("dataset_inconsistent", "public 视图不含 labels")
        return self.labels[case_id]


# --------------------------------------------------------------------------- #
# 入口
# --------------------------------------------------------------------------- #


def load_p2_dataset(manifest_path: Path | str, *, visibility: str) -> P2Dataset:
    """按**显式**可见性加载 P2 数据集。

    - `visibility="public"`：只读 manifest；不打开 `MKTKB_P2_HOLDOUT_ROOT` 指向的封存 root，
      不碰密文/key；返回版本/题数/分层/四个 sha256/轮数统计；
    - `visibility="holdout"`：需要 `MKTKB_P2_HOLDOUT_ROOT` + `MKTKB_P2_HOLDOUT_KEY_FILE`，
      manifest 必须位于 root 内；解封并全校验后返回 case 行与 labels 映射。

    任何违规抛 :class:`P2DatasetError`（`.reason` 为稳定原因码），不返回半成品。
    """
    mode = _require_visibility(visibility)
    path = Path(manifest_path)
    if mode == "public":
        _reject_sealed_root_for_public(path)
        return P2Dataset(visibility="public", manifest=_read_manifest(path))
    return _load_holdout(path)


def _require_visibility(visibility: object) -> str:
    if not isinstance(visibility, str) or visibility not in P2_VISIBILITIES:
        raise _fail(
            "visibility_invalid", "visibility 必须显式给出 'public' 或 'holdout'（不做默认）"
        )
    return visibility


def _reject_sealed_root_for_public(path: Path) -> None:
    """public 视图只允许读“repo 内元数据”。若路径落在封存 root 里就拒绝，一个字节都不读。

    这里只读一个环境变量做越界判断，**不打开** root 下任何文件；root 未配置时直接放行
    （public 的正常形态就是这样：manifest 是仓库内的公开副本）。
    """
    root_text = os.environ.get(HOLDOUT_ROOT_ENV)
    if not isinstance(root_text, str) or not root_text.strip():
        return
    target = _resolve(path)
    root = _resolve(Path(root_text.strip()))
    if target is None or root is None:  # pragma: no cover - 极端路径错误
        return
    if target.is_relative_to(root):
        raise _fail(
            "visibility_root_violation",
            f"public 视图不得读取 {HOLDOUT_ROOT_ENV} 指向的封存 root 内文件",
        )


# --------------------------------------------------------------------------- #
# 读 manifest / key / 密文
# --------------------------------------------------------------------------- #


def _read_manifest(path: Path) -> P2Manifest:
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        raise _fail("manifest_missing", f"manifest 不存在：{path}") from None
    except OSError:
        raise _fail("manifest_unreadable", f"manifest 不可读：{path}") from None
    if len(raw) > MAX_MANIFEST_BYTES:
        raise _fail("manifest_too_large", f"manifest 超过 {MAX_MANIFEST_BYTES} 字节")
    if raw.startswith(b"\xef\xbb\xbf"):
        raise _fail("manifest_json_invalid", "manifest 不能带 UTF-8 BOM")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise _fail("manifest_not_utf8", "manifest 不是 UTF-8") from None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        raise _fail("manifest_json_invalid", "manifest 不是合法 JSON") from None
    return P2Manifest.from_dict(payload, manifest_sha256=hashlib.sha256(raw).hexdigest())


def _fernet() -> tuple[type, type]:
    try:
        from cryptography.fernet import Fernet, InvalidToken
    except ImportError:  # 评测依赖缺失：fail closed，不退回明文/自制加密
        raise _fail(
            "crypto_unavailable",
            "解封 holdout 需要 cryptography 的 Fernet（评测依赖，不进入生产依赖）",
        ) from None
    return Fernet, InvalidToken


def _read_key(path: Path) -> bytes:
    fernet_cls, _invalid = _fernet()
    if not path.is_file():
        raise _fail("holdout_key_file_missing", f"key 文件不存在：{path}")
    try:
        raw = path.read_bytes()
    except OSError:
        raise _fail("holdout_key_unreadable", f"key 文件不可读：{path}") from None
    if len(raw) > MAX_KEY_BYTES:
        raise _fail("holdout_key_invalid", "key 文件过大")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise _fail("holdout_key_unreadable", "key 文件不是 UTF-8") from None
    key_text = text.strip()
    if not _KEY_RE.fullmatch(key_text):
        raise _fail("holdout_key_invalid", "key 必须是 Fernet 44 位 url-safe base64")
    try:
        fernet_cls(key_text.encode("ascii"))
    except (TypeError, ValueError):
        raise _fail("holdout_key_invalid", "key 不是合法的 Fernet key") from None
    return key_text.encode("ascii")


def _read_sealed(path: Path, kind: str) -> bytes:
    if not path.is_file():
        raise _fail("holdout_ciphertext_missing", f"{kind} 密文不存在：{path}")
    try:
        token = path.read_bytes()
    except OSError:
        raise _fail("holdout_ciphertext_unreadable", f"{kind} 密文不可读：{path}") from None
    if not token:
        raise _fail("holdout_ciphertext_unreadable", f"{kind} 密文为空")
    if len(token) > MAX_SEALED_BYTES:
        raise _fail("holdout_ciphertext_too_large", f"{kind} 密文超过 {MAX_SEALED_BYTES} 字节")
    return token


def _verify_sha256(raw: bytes, expected: str, reason: str, field_name: str) -> None:
    actual = hashlib.sha256(raw).hexdigest()
    if actual != expected:
        raise _fail(reason, f"{field_name} 不符：期望 {expected}，实际 {actual}")


# --------------------------------------------------------------------------- #
# holdout 主流程
# --------------------------------------------------------------------------- #


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not isinstance(value, str) or not value.strip():
        raise _fail("holdout_env_missing", f"holdout 需要环境变量 {name}")
    return value.strip()


def _load_holdout(manifest_path: Path) -> P2Dataset:
    root_text = _require_env(HOLDOUT_ROOT_ENV)
    key_text = _require_env(HOLDOUT_KEY_FILE_ENV)
    root = Path(root_text)
    if not root.is_dir():
        raise _fail("holdout_root_invalid", f"{HOLDOUT_ROOT_ENV} 必须指向已存在的封存目录")
    root_resolved = _resolve(root)
    manifest_resolved = _resolve(manifest_path)
    if (
        root_resolved is None  # pragma: no cover - 极端路径错误
        or manifest_resolved is None
        or not manifest_resolved.is_relative_to(root_resolved)
    ):
        raise _fail("holdout_manifest_outside_root", "holdout 的 manifest 必须位于封存 root 内")

    manifest = _read_manifest(manifest_resolved)
    key = _read_key(Path(key_text))
    fernet_cls, invalid_token = _fernet()

    questions_token = _read_sealed(root_resolved / QUESTIONS_CIPHERTEXT_NAME, "questions")
    labels_token = _read_sealed(root_resolved / LABELS_CIPHERTEXT_NAME, "labels")
    _verify_sha256(
        questions_token,
        manifest.questions_ciphertext_sha256,
        "holdout_ciphertext_sha256_mismatch",
        "questions_ciphertext_sha256",
    )
    _verify_sha256(
        labels_token,
        manifest.labels_ciphertext_sha256,
        "holdout_ciphertext_sha256_mismatch",
        "labels_ciphertext_sha256",
    )
    questions_plain = _decrypt(fernet_cls(key), questions_token, invalid_token, "questions")
    labels_plain = _decrypt(fernet_cls(key), labels_token, invalid_token, "labels")
    _verify_sha256(
        questions_plain,
        manifest.questions_plaintext_sha256,
        "holdout_plaintext_sha256_mismatch",
        "questions_plaintext_sha256",
    )
    _verify_sha256(
        labels_plain,
        manifest.labels_plaintext_sha256,
        "holdout_plaintext_sha256_mismatch",
        "labels_plaintext_sha256",
    )

    question_rows = _parse_rows(questions_plain, code="holdout_questions_invalid", label="questions")
    label_rows = _parse_rows(labels_plain, code="holdout_labels_invalid", label="labels")
    parsed_questions = _validate_questions(question_rows, manifest)
    labels = _validate_labels(label_rows, manifest)
    cases, mismatches = _merge_cases(parsed_questions, labels)
    return P2Dataset(
        visibility="holdout",
        manifest=manifest,
        cases=cases,
        labels=MappingProxyType(labels),
        metadata_mismatch_count=mismatches,
    )


def _decrypt(fernet: Any, token: bytes, invalid_token: type, kind: str) -> bytes:
    try:
        return fernet.decrypt(token)
    except invalid_token:
        raise _fail("holdout_decrypt_failed", f"{kind} 密文无法用给定 key 解封") from None
    except Exception:  # pragma: no cover - Fernet 的其它异常同样按解封失败处理
        raise _fail("holdout_decrypt_failed", f"{kind} 解封失败") from None


def _parse_rows(raw: bytes, *, code: str, label: str) -> list[tuple[int, Mapping[str, Any]]]:
    """把解密后的 JSONL 解析成 (行号, 对象)；只报行号，不报行内容。"""
    if raw.startswith(b"\xef\xbb\xbf"):
        raise _fail(code, f"{label} 不能带 UTF-8 BOM")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise _fail(code, f"{label} 不是 UTF-8") from None
    rows: list[tuple[int, Mapping[str, Any]]] = []
    for number, line in enumerate(text.split("\n"), start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            raise _fail(code, f"{label} 第 {number} 行 JSON 解析失败") from None
        if not isinstance(payload, Mapping):
            raise _fail(code, f"{label} 第 {number} 行必须是 JSON 对象")
        rows.append((number, payload))
    if not rows:
        raise _fail(code, f"{label} 不能为空")
    return rows


def _holdout_policy(manifest: P2Manifest) -> HoldoutPolicy:
    return HoldoutPolicy(
        case_count=manifest.case_count,
        strata={name: int(count) for name, count in manifest.strata.items()},
        questions_sha256=None,
        labels_sha256=None,
        label_version=manifest.label_version,
    )


def _validate_questions(
    rows: list[tuple[int, Mapping[str, Any]]], manifest: P2Manifest
) -> list[tuple[int, Mapping[str, Any]]]:
    policy = _holdout_policy(manifest)
    parsed: list[tuple[int, Mapping[str, Any]]] = []
    seen: set[str] = set()
    strata: Counter[str] = Counter()
    for number, payload in rows:
        leaked = sorted(HOLDOUT_ANSWER_FIELDS & set(payload))
        if leaked:
            raise _fail(
                "holdout_answer_field_leak", f"questions 第 {number} 行出现答案字段 {leaked}"
            )
        version = payload.get("label_version")
        if version is not None and version != manifest.label_version:
            raise _fail(
                "holdout_label_version_mismatch",
                f"questions 第 {number} 行的 label_version 与 manifest 不一致",
            )
        try:
            item = _dataset._question_row(payload, number, policy, label="p2 questions")
        except HoldoutError as exc:
            raise _fail(
                "holdout_questions_invalid",
                f"questions 第 {number} 行未通过 holdout 字段校验：{exc}",
            ) from None
        except ValueError as exc:
            raise _fail(
                "holdout_questions_invalid",
                f"questions 第 {number} 行未通过 holdout 字段校验：{exc}",
            ) from None
        case_id = str(item["case_id"])
        if case_id in seen:
            raise _fail("holdout_duplicate_case_id", f"questions 第 {number} 行 case_id 重复")
        seen.add(case_id)
        strata[str(item["stratum"])] += 1
        parsed.append((number, item))

    if len(parsed) != manifest.case_count:
        raise _fail(
            "holdout_case_count_mismatch",
            f"questions 行数 {len(parsed)} != manifest case_count {manifest.case_count}",
        )
    actual_strata = dict(sorted(strata.items()))
    declared_strata = dict(sorted(manifest.strata.items()))
    if actual_strata != declared_strata:
        raise _fail(
            "holdout_strata_mismatch",
            f"questions 分层 {actual_strata} != manifest {declared_strata}",
        )
    _check_turns(parsed, manifest)
    return parsed


def _check_turns(
    parsed: list[tuple[int, Mapping[str, Any]]], manifest: P2Manifest
) -> None:
    histogram: Counter[int] = Counter()
    for number, item in parsed:
        turns = item["turns"]
        stratum = str(item["stratum"])
        if stratum == "multi_turn":
            if len(turns) < 2:
                raise _fail(
                    "holdout_turns_invalid",
                    f"questions 第 {number} 行 multi_turn 至少要有 2 轮（turns>=2）",
                )
        else:
            if len(turns) > 1:
                raise _fail(
                    "holdout_turns_invalid",
                    f"questions 第 {number} 行非 multi_turn 分层不得声明多轮",
                )
            if not str(item["question"]).strip():
                raise _fail(
                    "holdout_turns_invalid", f"questions 第 {number} 行单轮题 question 不得为空"
                )
        histogram[len(turns) if turns else 1] += 1

    actual_stats = {
        "total_turns": sum(bucket * count for bucket, count in histogram.items()),
        "max_turns_per_case": max(histogram),
        "turn_histogram": {str(bucket): histogram[bucket] for bucket in sorted(histogram)},
    }
    declared_stats = {
        "total_turns": int(manifest.turn_stats["total_turns"]),
        "max_turns_per_case": int(manifest.turn_stats["max_turns_per_case"]),
        "turn_histogram": {
            str(key): int(value) for key, value in manifest.turn_stats["turn_histogram"].items()
        },
    }
    if actual_stats != declared_stats:
        raise _fail(
            "holdout_turn_stats_mismatch",
            f"questions 轮数统计 {actual_stats} != manifest turn_stats {declared_stats}",
        )


def _validate_labels(
    rows: list[tuple[int, Mapping[str, Any]]], manifest: P2Manifest
) -> dict[str, Mapping[str, Any]]:
    policy = _holdout_policy(manifest)
    parsed: dict[str, Mapping[str, Any]] = {}
    for number, payload in rows:
        version = payload.get("label_version")
        if version is not None and version != manifest.label_version:
            raise _fail(
                "holdout_label_version_mismatch",
                f"labels 第 {number} 行的 label_version 与 manifest 不一致",
            )
        try:
            item = _dataset._label_row(payload, number, policy)
        except HoldoutError as exc:
            raise _fail(
                "holdout_labels_invalid", f"labels 第 {number} 行未通过 holdout 字段校验：{exc}"
            ) from None
        except ValueError as exc:
            raise _fail(
                "holdout_labels_invalid", f"labels 第 {number} 行未通过 holdout 字段校验：{exc}"
            ) from None
        case_id = str(item["case_id"])
        if case_id in parsed:
            raise _fail("holdout_duplicate_case_id", f"labels 第 {number} 行 case_id 重复")
        parsed[case_id] = item
    if len(parsed) != manifest.case_count:
        raise _fail(
            "holdout_case_count_mismatch",
            f"labels 行数 {len(parsed)} != manifest case_count {manifest.case_count}",
        )
    return parsed


def _merge_cases(
    parsed_questions: list[tuple[int, Mapping[str, Any]]],
    labels: Mapping[str, Mapping[str, Any]],
) -> tuple[tuple[CaseSpec, ...], int]:
    question_ids = [str(item["case_id"]) for _number, item in parsed_questions]
    label_ids = set(labels)
    question_id_set = set(question_ids)
    missing = sum(1 for case_id in question_ids if case_id not in label_ids)
    extra = sum(1 for case_id in label_ids if case_id not in question_id_set)
    if missing or extra:
        raise _fail(
            "holdout_case_id_set_mismatch",
            f"questions={len(question_ids)} labels={len(label_ids)} "
            f"missing_in_labels={missing} extra_in_labels={extra}",
        )
    cases: list[CaseSpec] = []
    mismatches = 0
    for _number, row in parsed_questions:
        case_id = str(row["case_id"])
        label_row = labels[case_id]
        if (
            row["expected_kind"] != label_row["expected_kind"]
            or row["should_refuse"] != label_row["should_refuse"]
        ):
            mismatches += 1
        case = CaseSpec(
            case_id=case_id,
            suite=HOLDOUT_SUITE,
            split=HOLDOUT_SUITE,
            stratum=str(row["stratum"]),
            business_date=str(row["business_date"]),
            question=str(row["question"]),
            turns=tuple({"question": turn} for turn in row["turns"]),
            expected_kind=str(label_row["expected_kind"]),
            expected_values=tuple(label_row["expected_values"]),
            expected_sources=tuple(dict(ref) for ref in label_row["expected_sources"]),
            relevant_units=tuple(dict(ref) for ref in label_row["relevant_units"]),
            reference_answer=str(label_row["reference_answer"]),
            should_refuse=bool(label_row["should_refuse"]),
            refusal_reason=label_row["refusal_reason"],
            forbidden_values=tuple(label_row["forbidden_values"]),
            forbidden_sources=tuple(dict(ref) for ref in label_row["forbidden_sources"]),
            expected_pagination=None,
            requires_ocr=bool(row["requires_ocr"]),
            labeler=str(row["labeler"]),
            label_version=str(row["label_version"]),
            notes=str(row["notes"]),
        )
        try:
            _dataset.validate_case(case)
        except ValueError as exc:
            raise _fail("holdout_case_invalid", f"case {case_id} 合并后不合规：{exc}") from None
        cases.append(case)
    return tuple(cases), mismatches


# --------------------------------------------------------------------------- #
# 校验原语（只报字段名/结构，不回显取值正文）
# --------------------------------------------------------------------------- #


def _exact_keys(payload: Mapping[str, Any], expected: frozenset[str], name: str) -> None:
    keys = set(payload)
    missing = sorted(expected - keys)
    unknown = sorted(keys - expected)
    if missing:
        raise _fail("manifest_field_missing", f"{name} 缺少字段 {missing}")
    if unknown:
        raise _fail("manifest_field_unknown", f"{name} 含未声明字段 {unknown}")


def _exact_nested(
    payload: Mapping[str, Any], expected: frozenset[str], reason: str, name: str
) -> None:
    """嵌套对象（encryption 等）用各自的原因码报缺字段/多字段。"""
    missing = sorted(set(expected) - set(payload))
    unknown = sorted(set(payload) - set(expected))
    if missing:
        raise _fail(reason, f"{name} 缺少字段 {missing}")
    if unknown:
        raise _fail(reason, f"{name} 含未声明字段 {unknown}")


def _plain_text(value: object, reason: str, name: str, *, maximum: int = 96) -> str:
    if not isinstance(value, str):
        raise _fail(reason, f"{name} 必须是字符串")
    text = value.strip()
    if not text:
        raise _fail(reason, f"{name} 不能为空")
    if len(text) > maximum:
        raise _fail(reason, f"{name} 过长")
    if any(ch in text for ch in "\r\n"):
        raise _fail(reason, f"{name} 不得含换行")
    return text


def _token(value: object, reason: str, name: str) -> str:
    text = _plain_text(value, reason, name, maximum=64)
    if not _TOKEN_RE.fullmatch(text):
        raise _fail(reason, f"{name} 只允许字母数字与 _.:-")
    return text


def _integer(value: object, reason: str, name: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise _fail(reason, f"{name} 必须是整数（拒绝 bool/字符串/浮点）")
    if value < minimum:
        raise _fail(reason, f"{name} 不得小于 {minimum}")
    return int(value)


def _sha256(value: object, name: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value.strip().lower()):
        raise _fail("manifest_sha256_invalid", f"{name} 必须是 64 位小写十六进制")
    return value.strip().lower()


def _business_date(value: object) -> str:
    text = _plain_text(value, "manifest_business_date_invalid", "business_date", maximum=10)
    if not _DATE_RE.fullmatch(text):
        raise _fail("manifest_business_date_invalid", "business_date 必须是 YYYY-MM-DD")
    try:
        date.fromisoformat(text)
    except ValueError:
        raise _fail("manifest_business_date_invalid", "business_date 不是合法日期") from None
    return text


def _created_utc(value: object) -> str:
    text = _plain_text(value, "manifest_created_utc_invalid", "created_utc", maximum=64)
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        raise _fail("manifest_created_utc_invalid", "created_utc 必须是 ISO8601 时间") from None
    if moment.tzinfo is None or moment.utcoffset() != timedelta(0):
        raise _fail("manifest_created_utc_invalid", "created_utc 必须带 UTC 时区")
    return text


def _parse_strata(value: object, case_count: int) -> Mapping[str, int]:
    if not isinstance(value, Mapping):
        raise _fail("manifest_strata_invalid", "strata 必须是对象")
    keys = set(value)
    missing = sorted(set(P2_STRATA) - keys)
    unknown = sorted(keys - set(P2_STRATA))
    if missing:
        raise _fail("manifest_strata_invalid", f"strata 缺少分层 {missing}")
    if unknown:
        raise _fail("manifest_strata_invalid", f"strata 含未声明分层 {unknown}")
    parsed = {
        name: _integer(value[name], "manifest_strata_invalid", f"strata.{name}", minimum=1)
        for name in P2_STRATA
    }
    declared = {name: int(parsed[name]) for name in P2_STRATA}
    if declared != dict(P2_STRATA):
        raise _fail("manifest_strata_invalid", f"strata 必须冻结为 {dict(P2_STRATA)}")
    if sum(declared.values()) != case_count:
        raise _fail("manifest_strata_invalid", "strata 合计必须等于 case_count")
    return MappingProxyType(declared)


def _parse_encryption(value: object) -> Mapping[str, str]:
    if not isinstance(value, Mapping):
        raise _fail("manifest_encryption_invalid", "encryption 必须是对象")
    _exact_nested(value, _ENCRYPTION_FIELDS, "manifest_encryption_invalid", "encryption")
    kind = _plain_text(value["kind"], "manifest_encryption_invalid", "encryption.kind", maximum=32)
    if kind != FERNET_KIND:
        raise _fail("manifest_encryption_invalid", f"encryption.kind 必须是 {FERNET_KIND}")
    key_id = _token(value["key_id"], "manifest_encryption_invalid", "encryption.key_id")
    return MappingProxyType({"kind": kind, "key_id": key_id})


def _parse_turn_stats(value: object, case_count: int) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _fail("manifest_turn_stats_invalid", "turn_stats 必须是对象")
    keys = set(value)
    missing = sorted(_TURN_STATS_FIELDS - keys)
    unknown = sorted(keys - _TURN_STATS_FIELDS)
    if missing:
        raise _fail("manifest_turn_stats_invalid", f"turn_stats 缺少字段 {missing}")
    if unknown:
        raise _fail("manifest_turn_stats_invalid", f"turn_stats 含未声明字段 {unknown}")
    total = _integer(
        value["total_turns"], "manifest_turn_stats_invalid", "turn_stats.total_turns", minimum=1
    )
    maximum = _integer(
        value["max_turns_per_case"],
        "manifest_turn_stats_invalid",
        "turn_stats.max_turns_per_case",
        minimum=1,
    )
    histogram = value["turn_histogram"]
    if not isinstance(histogram, Mapping) or not histogram:
        raise _fail("manifest_turn_stats_invalid", "turn_stats.turn_histogram 必须是非空对象")
    parsed: dict[str, int] = {}
    for key, count in histogram.items():
        if not isinstance(key, str) or not _BUCKET_RE.fullmatch(key):
            raise _fail(
                "manifest_turn_stats_invalid", "turn_histogram 的键必须是 1..999 的十进制"
            )
        if key != str(int(key)):
            raise _fail("manifest_turn_stats_invalid", "turn_histogram 的键不得有前导零")
        parsed[key] = _integer(
            count, "manifest_turn_stats_invalid", f"turn_stats.turn_histogram[{key}]", minimum=1
        )
    if sum(parsed.values()) != case_count:
        raise _fail("manifest_turn_stats_invalid", "turn_histogram 计数之和必须等于 case_count")
    if maximum != max(int(key) for key in parsed):
        raise _fail("manifest_turn_stats_invalid", "max_turns_per_case 必须等于最大轮数桶")
    expected_total = sum(int(key) * count for key, count in parsed.items())
    if total != expected_total:
        raise _fail("manifest_turn_stats_invalid", "total_turns 必须等于各桶轮数之和")
    ordered = {key: parsed[key] for key in sorted(parsed, key=int)}
    return MappingProxyType(
        {
            "total_turns": total,
            "max_turns_per_case": maximum,
            "turn_histogram": MappingProxyType(ordered),
        }
    )

"""P2-T202 定向回归：H2 受限数据集加载器（public 元数据 / holdout 加密封存解封）。

本文件锁定 T202 的验收口径（任务书 §8 T202 / §5 H2 可见性）：

1. **public 绝不打开封存 root**：只读 manifest；路径落在 `MKTKB_P2_HOLDOUT_ROOT` 内直接
   拒绝；用 `Path.read_bytes` 探针证明“一个字节都没读”；无环境变量/环境变量过期都能工作；
   返回对象只有元数据（`cases` 为空、`labels` 为空），`repr` 不含题干/答案。
2. **holdout 正常解封**：env root + key 文件 -> 密文 sha256 -> Fernet -> 明文 sha256 ->
   逐行 schema -> 题数/分层/label_version/唯一 id/集合相等 -> 轮数/turn_stats ->
   合并 CaseSpec；只读 manifest/key/两个密文共 4 个文件，**不落盘明文**。
3. **缺 env/key/文件、坏 key、密文或明文 sha 不符**：一律 fail closed，稳定原因码。
4. **严格 manifest**：未知/缺失字段、冻结题数与分层、turn_stats 内部自洽、UTC 时间、
   四个 sha256、encryption 块；错一个就拒绝。
5. **数据契约**：重复 case_id、questions 含答案字段、labels 缺/多 case、多轮缺轮、
   单轮题空 question、非法 turn 文本、非法 locator/不透明 id、合并后 validate_case 失败。
6. **错误信息不含题干/答案**：所有失败路径的 `str/repr/detail` 都不得出现合成题干与
   参考答案标记。

零真实调用：所有夹具在 `tmp_path` 现生成（Fernet key 现生成、合成 30 题），不读 .env、
不读 H1/H2 原件、不访问 `D:/mktkb-p2-holdout`、不联网、不装依赖、不碰 `var/` 与账本。
"""

from __future__ import annotations

import copy
import functools
import hashlib
import json
import sys
from dataclasses import FrozenInstanceError, dataclass
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from mktkb.evaluation import p2_dataset as p2d
from mktkb.evaluation.dataset import HOLDOUT_ANSWER_FIELDS, validate_case
from mktkb.evaluation.p2_dataset import (
    HOLDOUT_KEY_FILE_ENV,
    HOLDOUT_ROOT_ENV,
    LABELS_CIPHERTEXT_NAME,
    QUESTIONS_CIPHERTEXT_NAME,
    P2Dataset,
    P2DatasetError,
    P2Manifest,
    load_p2_dataset,
)

#: 合成标记：只用于断言“错误/日志里不出现题干与答案”，不是任何真实题目。
QUESTION_TOKEN = "SYNTHETIC-QUESTION-TOKEN-7f3a"
FOLLOWUP_TOKEN = "SYNTHETIC-FOLLOWUP-TOKEN-b1c2"
ANSWER_TOKEN = "SYNTHETIC-ANSWER-TOKEN-c41d"

LABEL_VERSION = "p2-holdout-v2-2026-11-10"
DATASET_VERSION = "P2-HOLDOUT-v2"
BUSINESS_DATE = "2026-10-28"
CREATED_UTC = "2026-11-10T12:00:00+00:00"
KEY_ID = "p2-holdout-v2"
CASE_PREFIX = "P2H"

#: 冻结分层（与 p2_dataset.P2_STRATA 一致；测试自己写一份，防止两边一起漂移）。
STRATA_PLAN: tuple[tuple[str, int], ...] = (
    ("paraphrase", 10),
    ("multi_turn", 5),
    ("negative", 5),
    ("stale_conflict", 5),
    ("cross_doc_security", 5),
)
TOTAL_CASES = sum(count for _name, count in STRATA_PLAN)
MULTI_TURN_START = 10
MULTI_TURN_TURNS = 2


# --------------------------------------------------------------------------- #
# 合成夹具（30 题 / 10-5-5-5-5 / 25 单轮 + 5 两轮 = 35 turn）
# --------------------------------------------------------------------------- #


def _question_rows() -> list[dict]:
    rows: list[dict] = []
    index = 0
    for stratum, count in STRATA_PLAN:
        for offset in range(count):
            index += 1
            turns = (
                [f"{FOLLOWUP_TOKEN} 第 1 轮", f"{FOLLOWUP_TOKEN} 第 2 轮"]
                if stratum == "multi_turn"
                else []
            )
            rows.append(
                {
                    "case_id": f"{CASE_PREFIX}-{index:02d}",
                    "suite": "holdout",
                    "split": "holdout",
                    "stratum": stratum,
                    "business_date": BUSINESS_DATE,
                    "question": f"{QUESTION_TOKEN} {stratum} {offset:02d}",
                    "turns": turns,
                    "expected_kind": "refusal" if stratum == "negative" else "answer",
                    "should_refuse": stratum == "negative",
                    "requires_ocr": False,
                    "labeler": "data-custodian",
                    "label_version": LABEL_VERSION,
                    "notes": "合成夹具",
                }
            )
    return rows


def _label_rows(rows: list[dict]) -> list[dict]:
    labels: list[dict] = []
    for row in rows:
        refuse = bool(row["should_refuse"])
        labels.append(
            {
                "case_id": row["case_id"],
                "expected_kind": row["expected_kind"],
                "expected_values": [] if refuse else ["合成期望值"],
                "expected_sources": (
                    []
                    if refuse
                    else [{"doc_code": "D01", "unit_key": "sheet:物品位置:row:8"}]
                ),
                "relevant_units": (
                    [] if refuse else [{"doc_code": "D01", "locator": {"sheet": "物品位置", "row": 8}}]
                ),
                "reference_answer": "" if refuse else f"{ANSWER_TOKEN} 合成参考答案",
                "should_refuse": refuse,
                "refusal_reason": "合成负样本：语料无答案" if refuse else None,
                "forbidden_values": ["合成诱饵值"],
                "forbidden_sources": [{"doc_code": "V01"}],
                "notes": "合成夹具",
            }
        )
    return labels


def _jsonl(rows: list[dict]) -> bytes:
    return ("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n").encode("utf-8")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _turn_stats(rows: list[dict]) -> dict:
    histogram: dict[str, int] = {}
    for row in rows:
        turns = len(row["turns"]) if row["turns"] else 1
        histogram[str(turns)] = histogram.get(str(turns), 0) + 1
    return {
        "total_turns": sum(int(bucket) * count for bucket, count in histogram.items()),
        "max_turns_per_case": max(int(bucket) for bucket in histogram),
        "turn_histogram": {key: histogram[key] for key in sorted(histogram, key=int)},
    }


def _manifest_payload(rows: list[dict], labels: list[dict], q_token: bytes, l_token: bytes) -> dict:
    return {
        "schema_version": p2d.P2_MANIFEST_SCHEMA_VERSION,
        "dataset_version": DATASET_VERSION,
        "suite": p2d.P2_DATASET_SUITE,
        "label_version": LABEL_VERSION,
        "case_count": p2d.P2_CASE_COUNT,
        "strata": dict(p2d.P2_STRATA),
        "business_date": BUSINESS_DATE,
        "created_utc": CREATED_UTC,
        "author": "data-custodian",
        "encryption": {"kind": "fernet", "key_id": KEY_ID},
        "questions_plaintext_sha256": _sha(_jsonl(rows)),
        "labels_plaintext_sha256": _sha(_jsonl(labels)),
        "questions_ciphertext_sha256": _sha(q_token),
        "labels_ciphertext_sha256": _sha(l_token),
        "turn_stats": _turn_stats(rows),
    }


@dataclass
class Sealed:
    root: Path
    key_file: Path
    manifest_path: Path
    key: bytes


def _write_sealed(
    base: Path,
    *,
    rows: list[dict] | None = None,
    labels: list[dict] | None = None,
    key: bytes | None = None,
    encrypt_key: bytes | None = None,
    overrides: dict | None = None,
    drop: tuple[str, ...] = (),
    key_text: str | None = None,
) -> Sealed:
    """在 `base` 下造一套合成封存：root/manifest.json + 两个 Fernet 密文 + keys/v2.key。"""
    rows = _question_rows() if rows is None else rows
    labels = _label_rows(rows) if labels is None else labels
    key = Fernet.generate_key() if key is None else key
    cipher_key = key if encrypt_key is None else encrypt_key
    fernet = Fernet(cipher_key)
    q_token = fernet.encrypt(_jsonl(rows))
    l_token = fernet.encrypt(_jsonl(labels))
    root = base / "sealed"
    root.mkdir(parents=True, exist_ok=True)
    (root / QUESTIONS_CIPHERTEXT_NAME).write_bytes(q_token)
    (root / LABELS_CIPHERTEXT_NAME).write_bytes(l_token)
    payload = _manifest_payload(rows, labels, q_token, l_token)
    if overrides:
        payload.update(overrides)
    for name in drop:
        payload.pop(name, None)
    manifest_path = root / "manifest.json"
    manifest_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    keys_dir = base / "keys"
    keys_dir.mkdir(parents=True, exist_ok=True)
    key_file = keys_dir / "v2.key"
    text = key.decode("ascii") if key_text is None else key_text
    key_file.write_text(text + "\n", encoding="utf-8")
    return Sealed(root=root, key_file=key_file, manifest_path=manifest_path, key=key)


def _use_env(monkeypatch: pytest.MonkeyPatch, item: Sealed) -> None:
    monkeypatch.setenv(HOLDOUT_ROOT_ENV, str(item.root))
    monkeypatch.setenv(HOLDOUT_KEY_FILE_ENV, str(item.key_file))


def _load(item: Sealed) -> P2Dataset:
    return load_p2_dataset(item.manifest_path, visibility="holdout")


def _expect_reason(call: "functools.partial", reason: str) -> P2DatasetError:
    with pytest.raises(P2DatasetError) as info:
        call()
    assert info.value.reason == reason, f"期望 {reason}，实际 {info.value.reason}: {info.value}"
    return info.value


def _record_reads(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    """记录每一次 `Path.read_bytes`；用于证明“没打开封存文件”。"""
    reads: list[Path] = []
    original = Path.read_bytes

    def spy(self: Path) -> bytes:
        reads.append(Path(self).resolve())
        return original(self)

    monkeypatch.setattr(Path, "read_bytes", spy)
    return reads


def _public_copy(item: Sealed, target: Path) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(item.manifest_path.read_bytes())
    return target


def _sealed_variant(
    base: Path, monkeypatch: pytest.MonkeyPatch, name: str, **kwargs
) -> Sealed:
    """造一套新的合成封存并切换 env 指向它（用于同一测试里的多个变体）。"""
    item = _write_sealed(base / name, **kwargs)
    _use_env(monkeypatch, item)
    return item


def _setter(name: str, value):
    def mutate(payload: dict) -> None:
        payload[name] = value

    return mutate


@pytest.fixture
def sealed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Sealed:
    item = _write_sealed(tmp_path)
    _use_env(monkeypatch, item)
    return item


# --------------------------------------------------------------------------- #
# 1. public：只读元数据，绝不打开封存 root
# --------------------------------------------------------------------------- #


def test_public_reads_only_the_manifest_and_never_opens_the_sealed_root(
    sealed: Sealed, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # root 存在（且已被 env 指向）；public 仍只读自己那份 repo 风格 manifest。
    repo_manifest = _public_copy(sealed, tmp_path / "repo-public" / "manifest.json")
    reads = _record_reads(monkeypatch)

    dataset = load_p2_dataset(repo_manifest, visibility="public")

    assert dataset.visibility == "public"
    assert dataset.cases == ()
    assert dict(dataset.labels) == {}
    assert dataset.metadata_mismatch_count == 0
    assert reads == [repo_manifest.resolve()]
    assert all(not path.is_relative_to(sealed.root.resolve()) for path in reads)


def test_public_refuses_manifest_inside_sealed_root_without_reading_it(
    sealed: Sealed, monkeypatch: pytest.MonkeyPatch
) -> None:
    reads = _record_reads(monkeypatch)
    error = _expect_reason(
        functools.partial(load_p2_dataset, sealed.manifest_path, visibility="public"),
        "visibility_root_violation",
    )
    assert reads == []
    assert str(sealed.root) not in str(error)


def test_public_works_without_sealed_env_or_with_a_stale_root(
    sealed: Sealed, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_manifest = _public_copy(sealed, tmp_path / "repo-public" / "manifest.json")

    monkeypatch.delenv(HOLDOUT_ROOT_ENV, raising=False)
    monkeypatch.delenv(HOLDOUT_KEY_FILE_ENV, raising=False)
    assert load_p2_dataset(repo_manifest, visibility="public").manifest.case_count == 30

    monkeypatch.setenv(HOLDOUT_ROOT_ENV, str(tmp_path / "does-not-exist"))
    monkeypatch.setenv(HOLDOUT_KEY_FILE_ENV, str(tmp_path / "does-not-exist" / "v2.key"))
    dataset = load_p2_dataset(repo_manifest, visibility="public")
    assert dataset.visibility == "public"


def test_public_metadata_matches_the_sealed_manifest(
    sealed: Sealed, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_manifest = _public_copy(sealed, tmp_path / "repo-public" / "manifest.json")
    raw = repo_manifest.read_bytes()
    monkeypatch.delenv(HOLDOUT_ROOT_ENV, raising=False)

    dataset = load_p2_dataset(repo_manifest, visibility="public")
    manifest = dataset.manifest

    assert manifest.as_dict() == json.loads(raw.decode("utf-8"))
    assert manifest.manifest_sha256 == _sha(raw)
    assert manifest.case_count == TOTAL_CASES
    assert dict(manifest.strata) == dict(p2d.P2_STRATA)
    assert {
        "total_turns": 35,
        "max_turns_per_case": MULTI_TURN_TURNS,
        "histogram": {"1": 25, "2": 5},
    } == {
        "total_turns": manifest.turn_stats["total_turns"],
        "max_turns_per_case": manifest.turn_stats["max_turns_per_case"],
        "histogram": dict(manifest.turn_stats["turn_histogram"]),
    }
    assert manifest.encryption == {"kind": "fernet", "key_id": KEY_ID}


def test_public_manifest_uses_the_same_strict_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(HOLDOUT_ROOT_ENV, raising=False)
    item = _write_sealed(tmp_path, overrides={"case_count": 29})
    repo_manifest = _public_copy(item, tmp_path / "repo-public" / "manifest.json")
    _expect_reason(
        functools.partial(load_p2_dataset, repo_manifest, visibility="public"),
        "manifest_case_count_invalid",
    )


def test_public_dataset_cannot_carry_rows(sealed: Sealed) -> None:
    holdout = _load(sealed)
    with pytest.raises(P2DatasetError) as info:
        P2Dataset(visibility="public", manifest=holdout.manifest, cases=holdout.cases)
    assert info.value.reason == "dataset_inconsistent"
    with pytest.raises(P2DatasetError) as info:
        P2Dataset(visibility="public", manifest=holdout.manifest, labels=holdout.labels)
    assert info.value.reason == "dataset_inconsistent"


def test_public_view_has_no_labels(sealed: Sealed, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo_manifest = _public_copy(sealed, tmp_path / "repo-public" / "manifest.json")
    monkeypatch.delenv(HOLDOUT_ROOT_ENV, raising=False)
    dataset = load_p2_dataset(repo_manifest, visibility="public")
    with pytest.raises(P2DatasetError) as info:
        dataset.label_for(f"{CASE_PREFIX}-01")
    assert info.value.reason == "dataset_inconsistent"


# --------------------------------------------------------------------------- #
# 2. holdout：正常解封 + 合并
# --------------------------------------------------------------------------- #


def test_holdout_decrypts_and_merges(sealed: Sealed) -> None:
    dataset = _load(sealed)

    assert dataset.visibility == "holdout"
    assert len(dataset.cases) == TOTAL_CASES
    assert len(dataset.labels) == TOTAL_CASES
    assert dataset.metadata_mismatch_count == 0
    assert [case.case_id for case in dataset.cases] == [f"{CASE_PREFIX}-{index:02d}" for index in range(1, 31)]
    assert dataset.manifest.manifest_sha256 == _sha(sealed.manifest_path.read_bytes())

    first = dataset.cases[0]
    assert first.suite == "holdout" and first.split == "holdout"
    assert first.stratum == "paraphrase"
    assert first.question.startswith(QUESTION_TOKEN)
    assert first.business_date == BUSINESS_DATE
    assert first.requires_ocr is False
    assert first.label_version == LABEL_VERSION
    assert first.labeler == "data-custodian"
    assert first.turns == ()
    assert first.reference_answer.startswith(ANSWER_TOKEN)

    multi = dataset.cases[MULTI_TURN_START]
    assert multi.stratum == "multi_turn"
    assert len(multi.turns) == MULTI_TURN_TURNS
    assert multi.turns[0]["question"].startswith(FOLLOWUP_TOKEN)
    assert multi.turns[1]["question"].startswith(FOLLOWUP_TOKEN)

    negative = dataset.cases[MULTI_TURN_START + 5]
    assert negative.should_refuse is True
    assert negative.expected_kind == "refusal"
    assert negative.refusal_reason

    for case in dataset.cases:
        validate_case(case)  # 合并后的 CaseSpec 必须整体合规

    assert dataset.label_for(f"{CASE_PREFIX}-01")["reference_answer"].startswith(ANSWER_TOKEN)
    with pytest.raises(KeyError):
        dataset.label_for("P2H-99")


def test_holdout_manifest_round_trips(sealed: Sealed) -> None:
    dataset = _load(sealed)
    payload = dataset.manifest.as_dict()
    again = P2Manifest.from_dict(payload, manifest_sha256=dataset.manifest.manifest_sha256)
    assert again == dataset.manifest
    assert again.as_dict() == payload


def test_holdout_reads_exactly_four_files(sealed: Sealed, monkeypatch: pytest.MonkeyPatch) -> None:
    reads = _record_reads(monkeypatch)
    _load(sealed)
    assert reads == [
        sealed.manifest_path.resolve(),
        sealed.key_file.resolve(),
        (sealed.root / QUESTIONS_CIPHERTEXT_NAME).resolve(),
        (sealed.root / LABELS_CIPHERTEXT_NAME).resolve(),
    ]


def test_holdout_writes_no_plaintext_to_disk(sealed: Sealed, tmp_path: Path) -> None:
    _load(sealed)
    assert sorted(path.name for path in sealed.root.iterdir()) == sorted(
        ["manifest.json", QUESTIONS_CIPHERTEXT_NAME, LABELS_CIPHERTEXT_NAME]
    )
    for path in tmp_path.rglob("*"):
        if not path.is_file():
            continue
        raw = path.read_bytes()
        assert QUESTION_TOKEN.encode("utf-8") not in raw, path
        assert FOLLOWUP_TOKEN.encode("utf-8") not in raw, path
        assert ANSWER_TOKEN.encode("utf-8") not in raw, path


def test_holdout_is_deterministic(sealed: Sealed) -> None:
    first = _load(sealed)
    second = _load(sealed)
    assert first.cases == second.cases
    assert dict(first.labels) == dict(second.labels)
    assert first.manifest == second.manifest


def test_metadata_mismatch_is_counted_not_fatal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rows = _question_rows()
    labels = _label_rows(rows)
    labels[0]["expected_kind"] = "refusal"
    labels[0]["should_refuse"] = True
    labels[0]["refusal_reason"] = "合成口径不一致"
    item = _write_sealed(tmp_path, rows=rows, labels=labels)
    _use_env(monkeypatch, item)

    dataset = _load(item)
    assert dataset.metadata_mismatch_count == 1
    assert dataset.cases[0].expected_kind == "refusal"  # labels 是答案权威
    assert dataset.cases[0].should_refuse is True


def test_holdout_dataset_is_frozen(sealed: Sealed) -> None:
    dataset = _load(sealed)
    with pytest.raises(FrozenInstanceError):
        dataset.cases = ()  # type: ignore[misc]
    with pytest.raises(TypeError):
        dataset.labels[f"{CASE_PREFIX}-01"] = {}  # type: ignore[index]


# --------------------------------------------------------------------------- #
# 3. 可见性参数
# --------------------------------------------------------------------------- #


def test_visibility_is_required_and_strict(sealed: Sealed) -> None:
    with pytest.raises(TypeError):
        load_p2_dataset(sealed.manifest_path)  # type: ignore[call-arg]
    for value in ("Public", "PRIVATE", "", "unknown", None, 1, True):
        with pytest.raises(P2DatasetError) as info:
            load_p2_dataset(sealed.manifest_path, visibility=value)  # type: ignore[arg-type]
        assert info.value.reason == "visibility_invalid"


# --------------------------------------------------------------------------- #
# 4. 环境/路径/key
# --------------------------------------------------------------------------- #


def test_missing_or_blank_env_is_rejected(sealed: Sealed, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(HOLDOUT_ROOT_ENV, raising=False)
    _expect_reason(functools.partial(_load, sealed), "holdout_env_missing")

    monkeypatch.setenv(HOLDOUT_ROOT_ENV, "   ")
    _expect_reason(functools.partial(_load, sealed), "holdout_env_missing")

    monkeypatch.setenv(HOLDOUT_ROOT_ENV, str(sealed.root))
    monkeypatch.delenv(HOLDOUT_KEY_FILE_ENV, raising=False)
    _expect_reason(functools.partial(_load, sealed), "holdout_env_missing")

    monkeypatch.setenv(HOLDOUT_KEY_FILE_ENV, "")
    _expect_reason(functools.partial(_load, sealed), "holdout_env_missing")


def test_root_must_be_an_existing_directory(sealed: Sealed, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(HOLDOUT_ROOT_ENV, str(sealed.key_file))
    _expect_reason(functools.partial(_load, sealed), "holdout_root_invalid")

    monkeypatch.setenv(HOLDOUT_ROOT_ENV, str(tmp_path / "missing-root"))
    _expect_reason(functools.partial(_load, sealed), "holdout_root_invalid")


def test_manifest_must_live_inside_root(sealed: Sealed, tmp_path: Path) -> None:
    outside = tmp_path / "elsewhere" / "manifest.json"
    outside.parent.mkdir(parents=True, exist_ok=True)
    outside.write_bytes(sealed.manifest_path.read_bytes())
    _expect_reason(
        functools.partial(load_p2_dataset, outside, visibility="holdout"),
        "holdout_manifest_outside_root",
    )


def test_manifest_missing_in_root(sealed: Sealed) -> None:
    sealed.manifest_path.unlink()
    _expect_reason(functools.partial(_load, sealed), "manifest_missing")


def test_manifest_must_be_a_file(sealed: Sealed) -> None:
    sealed.manifest_path.unlink()
    sealed.manifest_path.mkdir()
    _expect_reason(functools.partial(_load, sealed), "manifest_unreadable")


def test_key_file_missing(sealed: Sealed, monkeypatch: pytest.MonkeyPatch) -> None:
    sealed.key_file.unlink()
    _expect_reason(functools.partial(_load, sealed), "holdout_key_file_missing")


def test_ciphertext_files_must_exist(sealed: Sealed) -> None:
    (sealed.root / QUESTIONS_CIPHERTEXT_NAME).unlink()
    _expect_reason(functools.partial(_load, sealed), "holdout_ciphertext_missing")


def test_labels_ciphertext_must_exist(sealed: Sealed) -> None:
    (sealed.root / LABELS_CIPHERTEXT_NAME).unlink()
    _expect_reason(functools.partial(_load, sealed), "holdout_ciphertext_missing")


def test_blank_ciphertext_is_rejected(sealed: Sealed) -> None:
    (sealed.root / QUESTIONS_CIPHERTEXT_NAME).write_bytes(b"")
    _expect_reason(functools.partial(_load, sealed), "holdout_ciphertext_unreadable")


def test_key_must_be_a_valid_fernet_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for index, key_text in enumerate(("not-a-key", "!" * 43 + "=", "A" * 44)):
        item = _write_sealed(tmp_path / f"bad-key-{index}", key_text=key_text)
        _use_env(monkeypatch, item)
        _expect_reason(functools.partial(_load, item), "holdout_key_invalid")
        monkeypatch.undo()


def test_key_file_must_be_utf8(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    item = _write_sealed(tmp_path)
    _use_env(monkeypatch, item)
    item.key_file.write_bytes(b"\xff\xfe\x00\x01")
    _expect_reason(functools.partial(_load, item), "holdout_key_unreadable")


def test_wrong_key_cannot_decrypt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    item = _write_sealed(tmp_path, encrypt_key=Fernet.generate_key())
    _use_env(monkeypatch, item)
    error = _expect_reason(functools.partial(_load, item), "holdout_decrypt_failed")
    # 错误文本不得回显 key 或密文（key 内容属于受控材料）。
    key_text = item.key.decode("ascii")
    token = (item.root / QUESTIONS_CIPHERTEXT_NAME).read_bytes()
    for text in (str(error), error.detail, repr(error)):
        assert key_text not in text
        assert token.decode("latin-1") not in text


def test_missing_cryptography_fails_closed(sealed: Sealed, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "cryptography.fernet", None)
    _expect_reason(functools.partial(_load, sealed), "crypto_unavailable")


# --------------------------------------------------------------------------- #
# 5. 密文/明文摘要
# --------------------------------------------------------------------------- #


def test_ciphertext_tamper_is_rejected(sealed: Sealed) -> None:
    target = sealed.root / QUESTIONS_CIPHERTEXT_NAME
    target.write_bytes(target.read_bytes() + b"tamper")
    _expect_reason(functools.partial(_load, sealed), "holdout_ciphertext_sha256_mismatch")


def test_labels_ciphertext_tamper_is_rejected(sealed: Sealed) -> None:
    target = sealed.root / LABELS_CIPHERTEXT_NAME
    target.write_bytes(target.read_bytes() + b"tamper")
    _expect_reason(functools.partial(_load, sealed), "holdout_ciphertext_sha256_mismatch")


def test_plaintext_sha_mismatch_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    original_sha = _sha(_jsonl(_question_rows()))
    rows = copy.deepcopy(_question_rows())
    rows[0]["question"] = f"{QUESTION_TOKEN} 被改过的题干"
    item = _write_sealed(
        tmp_path, rows=rows, overrides={"questions_plaintext_sha256": original_sha}
    )
    _use_env(monkeypatch, item)
    _expect_reason(functools.partial(_load, item), "holdout_plaintext_sha256_mismatch")


# --------------------------------------------------------------------------- #
# 6. 严格 manifest
# --------------------------------------------------------------------------- #


def _rewrite_manifest(item: Sealed, mutate) -> None:
    payload = json.loads(item.manifest_path.read_text(encoding="utf-8"))
    mutate(payload)
    item.manifest_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def test_manifest_field_missing_and_unknown(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    item = _write_sealed(tmp_path / "missing", drop=("author",))
    _use_env(monkeypatch, item)
    _expect_reason(functools.partial(_load, item), "manifest_field_missing")
    monkeypatch.undo()

    item = _write_sealed(tmp_path / "unknown", overrides={"extra_field": 1})
    _use_env(monkeypatch, item)
    _expect_reason(functools.partial(_load, item), "manifest_field_unknown")


def test_manifest_schema_dataset_version_and_suite(
    sealed: Sealed,
) -> None:
    def bad_schema(payload: dict) -> None:
        payload["schema_version"] = "p2-holdout-manifest/v9.9"

    _rewrite_manifest(sealed, bad_schema)
    _expect_reason(functools.partial(_load, sealed), "manifest_schema_version_invalid")

    def bad_version(payload: dict) -> None:
        payload["schema_version"] = p2d.P2_MANIFEST_SCHEMA_VERSION
        payload["dataset_version"] = ""

    _rewrite_manifest(sealed, bad_version)
    _expect_reason(functools.partial(_load, sealed), "manifest_dataset_version_invalid")

    def bad_suite(payload: dict) -> None:
        payload["dataset_version"] = DATASET_VERSION
        payload["suite"] = "holdout"

    _rewrite_manifest(sealed, bad_suite)
    _expect_reason(functools.partial(_load, sealed), "manifest_suite_invalid")


def test_manifest_label_version_is_a_token(sealed: Sealed) -> None:
    def mutate(payload: dict) -> None:
        payload["label_version"] = "p2 holdout v2"

    _rewrite_manifest(sealed, mutate)
    _expect_reason(functools.partial(_load, sealed), "manifest_label_version_invalid")


def test_manifest_case_count_is_frozen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for index, value in enumerate((29, 30.0, 30.5, True, "30")):
        item = _sealed_variant(tmp_path, monkeypatch, f"count-{index}")
        _rewrite_manifest(item, _setter("case_count", value))
        _expect_reason(functools.partial(_load, item), "manifest_case_count_invalid")


def test_manifest_strata_is_frozen(sealed: Sealed) -> None:
    _rewrite_manifest(
        sealed,
        _setter(
            "strata",
            {
                "paraphrase": 11,
                "multi_turn": 4,
                "negative": 5,
                "stale_conflict": 5,
                "cross_doc_security": 5,
            },
        ),
    )
    _expect_reason(functools.partial(_load, sealed), "manifest_strata_invalid")

    _rewrite_manifest(
        sealed,
        _setter(
            "strata",
            {
                "paraphrase": 10,
                "multi_turn": 5,
                "negative": 5,
                "stale_conflict": 5,
                "cross_doc_security": 5,
                "unexpected": 0,
            },
        ),
    )
    _expect_reason(functools.partial(_load, sealed), "manifest_strata_invalid")


def test_manifest_business_date_and_created_utc(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    item = _sealed_variant(tmp_path, monkeypatch, "date")
    _rewrite_manifest(item, _setter("business_date", "2026-13-40"))
    _expect_reason(functools.partial(_load, item), "manifest_business_date_invalid")

    for index, value in enumerate(
        ("not-a-time", "2026-11-10T12:00:00", "2026-11-10T12:00:00+08:00")
    ):
        item = _sealed_variant(tmp_path, monkeypatch, f"utc-{index}")
        payload_patch = {"business_date": BUSINESS_DATE, "created_utc": value}

        def mutate(payload: dict, payload_patch=payload_patch) -> None:
            payload.update(payload_patch)

        _rewrite_manifest(item, mutate)
        _expect_reason(functools.partial(_load, item), "manifest_created_utc_invalid")


def test_manifest_author_cannot_contain_newlines(sealed: Sealed) -> None:
    _rewrite_manifest(sealed, _setter("author", "data-custodian\n伪造行"))
    _expect_reason(functools.partial(_load, sealed), "manifest_author_invalid")


def test_manifest_encryption_block_is_strict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for index, block in enumerate(
        (
            {"kind": "gpg", "key_id": KEY_ID},
            {"kind": "fernet"},
            {"kind": "fernet", "key_id": KEY_ID, "extra": 1},
            {"kind": "fernet", "key_id": "含 空格"},
        )
    ):
        item = _sealed_variant(tmp_path, monkeypatch, f"enc-{index}")
        _rewrite_manifest(item, _setter("encryption", block))
        _expect_reason(functools.partial(_load, item), "manifest_encryption_invalid")


def test_manifest_sha256_fields_are_hex(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for index, name in enumerate(
        (
            "questions_plaintext_sha256",
            "labels_plaintext_sha256",
            "questions_ciphertext_sha256",
            "labels_ciphertext_sha256",
        )
    ):
        item = _sealed_variant(tmp_path, monkeypatch, f"sha-{index}")
        _rewrite_manifest(item, _setter(name, "z" * 64))
        _expect_reason(functools.partial(_load, item), "manifest_sha256_invalid")


def test_manifest_turn_stats_must_be_internally_consistent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    variants = (
        {"total_turns": 36, "max_turns_per_case": 2, "turn_histogram": {"1": 25, "2": 5}},
        {"total_turns": 35, "max_turns_per_case": 3, "turn_histogram": {"1": 25, "2": 5}},
        {"total_turns": 30, "max_turns_per_case": 2, "turn_histogram": {"1": 29, "2": 5}},
        {"total_turns": 35, "max_turns_per_case": 2, "turn_histogram": {"1": 25, "02": 5}},
        {"total_turns": 35, "max_turns_per_case": 2, "turn_histogram": {"1": 25, "2": 5, "3": 0}},
        {"total_turns": 35, "max_turns_per_case": 2},
        {"total_turns": 35, "max_turns_per_case": 2, "turn_histogram": {"1": 25, "2": 5}, "x": 1},
    )
    for index, stats in enumerate(variants):
        item = _sealed_variant(tmp_path, monkeypatch, f"turn-stats-{index}")
        _rewrite_manifest(item, _setter("turn_stats", stats))
        _expect_reason(functools.partial(_load, item), "manifest_turn_stats_invalid")


def test_manifest_json_forms_are_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(HOLDOUT_ROOT_ENV, raising=False)
    monkeypatch.delenv(HOLDOUT_KEY_FILE_ENV, raising=False)
    cases = {
        "json": (b"not json", "manifest_json_invalid"),
        "array": (b"[1, 2, 3]", "manifest_json_invalid"),
        "bom": (b"\xef\xbb\xbf{}", "manifest_json_invalid"),
        "utf8": (b"\xff\xfe\x00", "manifest_not_utf8"),
        "large": (b"{" + b" " * (p2d.MAX_MANIFEST_BYTES + 1), "manifest_too_large"),
    }
    for name, (raw, reason) in cases.items():
        target = tmp_path / f"{name}.json"
        target.write_bytes(raw)
        _expect_reason(
            functools.partial(load_p2_dataset, target, visibility="public"), reason
        )


# --------------------------------------------------------------------------- #
# 7. 数据契约：题数/分层/版本/id/答案字段/轮数
# --------------------------------------------------------------------------- #


def test_question_row_count_mismatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    item = _write_sealed(
        tmp_path,
        rows=_question_rows()[:29],
        overrides={"turn_stats": _turn_stats(_question_rows())},
    )
    _use_env(monkeypatch, item)
    error = _expect_reason(functools.partial(_load, item), "holdout_case_count_mismatch")
    assert "questions" in error.detail


def test_label_row_count_mismatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    rows = _question_rows()
    item = _write_sealed(tmp_path, rows=rows, labels=_label_rows(rows)[:29])
    _use_env(monkeypatch, item)
    error = _expect_reason(functools.partial(_load, item), "holdout_case_count_mismatch")
    assert "labels" in error.detail


def test_data_strata_mismatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    rows = _question_rows()
    rows[0]["stratum"] = "negative"
    item = _write_sealed(tmp_path, rows=rows)
    _use_env(monkeypatch, item)
    _expect_reason(functools.partial(_load, item), "holdout_strata_mismatch")


def test_label_version_mismatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    rows = _question_rows()
    rows[0]["label_version"] = "other-label-version"
    item = _write_sealed(tmp_path / "rows", rows=rows)
    _use_env(monkeypatch, item)
    _expect_reason(functools.partial(_load, item), "holdout_label_version_mismatch")
    monkeypatch.undo()

    rows = _question_rows()
    labels = _label_rows(rows)
    labels[0]["label_version"] = "other-label-version"
    item = _write_sealed(tmp_path / "labels", rows=rows, labels=labels)
    _use_env(monkeypatch, item)
    _expect_reason(functools.partial(_load, item), "holdout_label_version_mismatch")


def test_duplicate_case_id_in_questions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    rows = _question_rows()
    rows[1]["case_id"] = rows[0]["case_id"]
    item = _write_sealed(tmp_path, rows=rows)
    _use_env(monkeypatch, item)
    _expect_reason(functools.partial(_load, item), "holdout_duplicate_case_id")


def test_duplicate_case_id_in_labels(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    rows = _question_rows()
    labels = _label_rows(rows)
    labels[1]["case_id"] = labels[0]["case_id"]
    item = _write_sealed(tmp_path, rows=rows, labels=labels)
    _use_env(monkeypatch, item)
    _expect_reason(functools.partial(_load, item), "holdout_duplicate_case_id")


def test_label_set_must_equal_question_set(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    rows = _question_rows()
    labels = _label_rows(rows)
    labels[0]["case_id"] = "P2H-99"
    item = _write_sealed(tmp_path, rows=rows, labels=labels)
    _use_env(monkeypatch, item)
    error = _expect_reason(functools.partial(_load, item), "holdout_case_id_set_mismatch")
    assert "missing_in_labels=1" in error.detail
    assert "extra_in_labels=1" in error.detail


def test_questions_must_not_carry_answer_fields(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for index, field in enumerate(sorted(HOLDOUT_ANSWER_FIELDS)):
        rows = _question_rows()
        rows[0][field] = "x"
        item = _write_sealed(tmp_path / f"leak-{index}", rows=rows)
        _use_env(monkeypatch, item)
        _expect_reason(functools.partial(_load, item), "holdout_answer_field_leak")
        monkeypatch.undo()


def test_multi_turn_stratum_needs_two_turns(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for index, turns in enumerate(([], [f"{FOLLOWUP_TOKEN} 唯一一轮"])):
        rows = _question_rows()
        rows[MULTI_TURN_START]["turns"] = list(turns)
        item = _write_sealed(tmp_path / f"turns-{index}", rows=rows)
        _use_env(monkeypatch, item)
        _expect_reason(functools.partial(_load, item), "holdout_turns_invalid")
        monkeypatch.undo()


def test_single_turn_strata_cannot_declare_multi_turn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rows = _question_rows()
    rows[0]["turns"] = [f"{FOLLOWUP_TOKEN} 1", f"{FOLLOWUP_TOKEN} 2"]
    item = _write_sealed(tmp_path / "multi", rows=rows)
    _use_env(monkeypatch, item)
    _expect_reason(functools.partial(_load, item), "holdout_turns_invalid")
    monkeypatch.undo()

    rows = _question_rows()
    rows[0]["question"] = ""
    rows[0]["turns"] = [f"{FOLLOWUP_TOKEN} 1"]
    item = _write_sealed(tmp_path / "empty", rows=rows)
    _use_env(monkeypatch, item)
    _expect_reason(functools.partial(_load, item), "holdout_turns_invalid")


def test_blank_turn_text_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    rows = _question_rows()
    rows[MULTI_TURN_START]["turns"] = ["", f"{FOLLOWUP_TOKEN} 2"]
    item = _write_sealed(tmp_path, rows=rows)
    _use_env(monkeypatch, item)
    _expect_reason(functools.partial(_load, item), "holdout_questions_invalid")


def test_three_turn_multi_case_is_accepted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    rows = _question_rows()
    rows[MULTI_TURN_START]["turns"].append(f"{FOLLOWUP_TOKEN} 第 3 轮")
    item = _write_sealed(tmp_path, rows=rows)
    _use_env(monkeypatch, item)

    dataset = _load(item)
    assert len(dataset.cases[MULTI_TURN_START].turns) == 3
    assert dataset.manifest.turn_stats["max_turns_per_case"] == 3
    assert dataset.manifest.turn_stats["turn_histogram"]["3"] == 1


def test_turn_stats_must_match_the_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    rows = _question_rows()
    rows[MULTI_TURN_START]["turns"].append(f"{FOLLOWUP_TOKEN} 第 3 轮")
    item = _write_sealed(
        tmp_path, rows=rows, overrides={"turn_stats": _turn_stats(_question_rows())}
    )
    _use_env(monkeypatch, item)
    _expect_reason(functools.partial(_load, item), "holdout_turn_stats_mismatch")


# --------------------------------------------------------------------------- #
# 8. 行级 schema（复用 dataset.py 的 holdout 校验）
# --------------------------------------------------------------------------- #


def test_question_rows_reject_missing_and_extra_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rows = _question_rows()
    rows[0].pop("requires_ocr")
    item = _write_sealed(tmp_path / "missing", rows=rows)
    _use_env(monkeypatch, item)
    _expect_reason(functools.partial(_load, item), "holdout_questions_invalid")
    monkeypatch.undo()

    rows = _question_rows()
    rows[0]["extra"] = 1
    item = _write_sealed(tmp_path / "extra", rows=rows)
    _use_env(monkeypatch, item)
    _expect_reason(functools.partial(_load, item), "holdout_questions_invalid")


def test_question_rows_keep_the_holdout_suite_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rows = _question_rows()
    rows[0]["suite"] = p2d.P2_DATASET_SUITE
    item = _write_sealed(tmp_path, rows=rows)
    _use_env(monkeypatch, item)
    _expect_reason(functools.partial(_load, item), "holdout_questions_invalid")


def test_label_rows_reject_missing_and_extra_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rows = _question_rows()
    labels = _label_rows(rows)
    labels[0].pop("notes")
    item = _write_sealed(tmp_path / "missing", rows=rows, labels=labels)
    _use_env(monkeypatch, item)
    _expect_reason(functools.partial(_load, item), "holdout_labels_invalid")
    monkeypatch.undo()

    labels = _label_rows(rows)
    labels[0]["extra"] = 1
    item = _write_sealed(tmp_path / "extra", rows=rows, labels=labels)
    _use_env(monkeypatch, item)
    _expect_reason(functools.partial(_load, item), "holdout_labels_invalid")


def test_label_rows_reject_bad_locator_and_opaque_ids(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # dataset.py 的 `_label_row` 只校验“ref 是对象列表”，locator 的结构/不透明 id 由合并后的
    # `validate_case` 拒绝；两种都 fail closed，这里锁定实际原因码。
    bad_refs = (
        [{"doc_code": "D01", "locator": {"bogus": 1}}],
        [{"doc_code": "D01", "locator": {"row": -1}}],
        [{"doc_code": "D01", "unit_key": "0123456789abcdef0123456789abcdef"}],
    )
    for index, refs in enumerate(bad_refs):
        rows = _question_rows()
        labels = _label_rows(rows)
        labels[0]["expected_sources"] = refs
        item = _write_sealed(tmp_path / f"loc-{index}", rows=rows, labels=labels)
        _use_env(monkeypatch, item)
        _expect_reason(functools.partial(_load, item), "holdout_case_invalid")
        monkeypatch.undo()


def test_refusal_without_reason_fails_after_merge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rows = _question_rows()
    labels = _label_rows(rows)
    negative_index = MULTI_TURN_START + 5
    labels[negative_index]["refusal_reason"] = None
    item = _write_sealed(tmp_path, rows=rows, labels=labels)
    _use_env(monkeypatch, item)
    _expect_reason(functools.partial(_load, item), "holdout_case_invalid")


# --------------------------------------------------------------------------- #
# 9. 错误信息不含题干/答案
# --------------------------------------------------------------------------- #


def test_errors_never_contain_question_or_answer_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rows = _question_rows()
    labels = _label_rows(rows)

    leak_rows = copy.deepcopy(rows)
    leak_rows[0]["expected_values"] = []
    short_turns = copy.deepcopy(rows)
    short_turns[MULTI_TURN_START]["turns"] = [f"{FOLLOWUP_TOKEN} 唯一一轮"]
    bad_labels = copy.deepcopy(labels)
    bad_labels[0]["expected_sources"] = [{"doc_code": "D01", "locator": {"bogus": 1}}]
    other_plain_sha = _sha(b"other plaintext")

    variants = (
        ({"rows": leak_rows}, "holdout_answer_field_leak"),
        ({"rows": short_turns}, "holdout_turns_invalid"),
        ({"labels": bad_labels}, "holdout_case_invalid"),
        ({"overrides": {"case_count": 29}}, "manifest_case_count_invalid"),
        ({"overrides": {"questions_plaintext_sha256": other_plain_sha}}, "holdout_plaintext_sha256_mismatch"),
        ({"key_text": "not-a-key"}, "holdout_key_invalid"),
        ({"encrypt_key": Fernet.generate_key()}, "holdout_decrypt_failed"),
    )
    for index, (kwargs, reason) in enumerate(variants):
        item = _write_sealed(tmp_path / f"leak-{index}", **kwargs)
        _use_env(monkeypatch, item)
        error = _expect_reason(functools.partial(_load, item), reason)
        for text in (str(error), error.detail, repr(error)):
            assert QUESTION_TOKEN not in text, reason
            assert FOLLOWUP_TOKEN not in text, reason
            assert ANSWER_TOKEN not in text, reason
        monkeypatch.undo()


def test_repr_of_loaded_dataset_has_no_question_or_answer(sealed: Sealed) -> None:
    dataset = _load(sealed)
    texts = (repr(dataset), str(dataset), str(dataset.manifest), json.dumps(dataset.manifest.as_dict(), ensure_ascii=False))
    for text in texts:
        assert QUESTION_TOKEN not in text
        assert FOLLOWUP_TOKEN not in text
        assert ANSWER_TOKEN not in text


# --------------------------------------------------------------------------- #
# 10. 契约文档与原因码同步
# --------------------------------------------------------------------------- #

CONTRACT_DOC = (
    Path(__file__).resolve().parents[3] / "docs" / "evaluation" / "p2-dataset-v0_1.md"
)


def test_every_reason_is_documented() -> None:
    assert CONTRACT_DOC.is_file(), CONTRACT_DOC
    text = CONTRACT_DOC.read_text(encoding="utf-8")
    missing = sorted(reason for reason in p2d.REASONS if reason not in text)
    assert missing == [], f"契约文档缺少原因码: {missing}"


def test_error_type_is_stable() -> None:
    assert issubclass(P2DatasetError, ValueError)
    assert P2DatasetError.code == "P2_DATASET_INVALID"
    error = P2DatasetError("manifest_missing")
    assert error.reason == "manifest_missing"
    assert str(error) == "manifest_missing"
    assert P2DatasetError("manifest_missing", "x").detail == "x"

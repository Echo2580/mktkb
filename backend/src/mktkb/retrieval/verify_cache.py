"""T10-PRE 索引核验加速：用“真实索引行指纹”复用已通过核验的进程内结论。

背景
----
`retrieval.service._ensure_indexes_ready` 在每次问答时都会对当前 revision 下**全部**可见
有效版本重建核验计划（jieba 分词、字段角色分析、输入摘要）并逐行比对索引行，成本随文档数
线性增长（T09 容量归因：50 版本合计约 5～6s/问，最慢两份大表占 84%）。

本模块不改变 `INDEX_NOT_READY` 语义，只避免**重复证明同一事实**：

- 每次问答仍读取该版本的全部相关真实行（版本行、marker、来源单元、单元映射、FTS 正文、
  字段行）并重算“状态指纹”；
- 只有指纹与“上次完整核验通过时”的指纹一致、且 revision 未变化时，才复用“通过”结论；
- 任何行被删除、改写、新增（含额外行、错归属、内容不符、输入摘要不符、tokenizer 版本不符、
  marker 缺失）都会改变指纹，从而触发完整核验并如实返回未就绪；**缓存不会吞掉损坏检测**；
- revision 变化（发布、删除等）使缓存整体失效，下次问答重新完整核验；取消未生效版本不改变
  revision 与可见索引状态，缓存结论仍成立（该版本本来就不参与核验）；
- 不写文件、不写库、不跨进程；缓存按 SQLAlchemy Engine 隔离并使用弱引用，引擎释放即回收；
- 线程安全：模块级锁保护缓存与计数，指纹计算在锁外（调用方的一致读快照内）进行。

与 `verify_version_index` 的关系：完整核验仍由 `index.verify_version_index` 执行（同一套
`_build_plan`/`_verify_plan`），本模块只决定“是否需要再跑一次完整核验”。

指纹编码
--------
每个通道在 SQLite 内用 `group_concat` 拼成**长度前缀**的规范串（每字段 `类型标记 + 长度 + ':' +
原值`，SQLite `||` 与 `length()` 在 C 层完成），再在 Python 内做一次 SHA-256；比逐行取回对象
再逐列哈希显著减少 Python 对象分配（T09 容量场景下 50 版本约 0.4s 量级）。

长度前缀编码是单射的：给定拼接串可唯一还原每一行/每一列，因此不同真实行状态不会得到相同
规范串；`group_concat` 的行顺序若发生（实现层面的）变化只会造成指纹不匹配 → 回退到完整核验，
不会造成“损坏被缓存吞掉”。NULL 与空串分别编码为 `'-'` 与 `'t0:'`，可区分。
"""

from __future__ import annotations

import hashlib
import threading
import weakref
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from ..documents.models import DocumentVersion
from .index import verify_version_index

_FINGERPRINT_TAG = b"T10PRE-verify-state-v1"

# UUID 列在 SQLite 中按 32 位十六进制存储；FTS 的 version_id 存的是带连字符的 str(uuid)
# （见 index.prepare_version_index）。列集合与 `index._verify_plan` 实际读取的列一致。
_SOURCE_UNITS_SQL = text(
    "SELECT group_concat(rowtext, char(30)) FROM ("
    "  SELECT "
    "    CASE WHEN id IS NULL THEN '-' ELSE 't'||length(id)||':'||id END ||"
    "    CASE WHEN ordinal IS NULL THEN '-' ELSE 'i'||length(CAST(ordinal AS TEXT))||':'||CAST(ordinal AS TEXT) END ||"
    "    CASE WHEN unit_key IS NULL THEN '-' ELSE 't'||length(unit_key)||':'||unit_key END ||"
    "    CASE WHEN kind IS NULL THEN '-' ELSE 't'||length(kind)||':'||kind END ||"
    "    CASE WHEN text IS NULL THEN '-' ELSE 't'||length(text)||':'||text END ||"
    "    CASE WHEN fields IS NULL THEN '-' ELSE 't'||length(fields)||':'||fields END ||"
    "    CASE WHEN sheet IS NULL THEN '-' ELSE 't'||length(sheet)||':'||sheet END ||"
    "    CASE WHEN version_id IS NULL THEN '-' ELSE 't'||length(version_id)||':'||version_id END ||"
    "    CASE WHEN document_id IS NULL THEN '-' ELSE 't'||length(document_id)||':'||document_id END"
    "  AS rowtext FROM source_units WHERE version_id = :version ORDER BY id"
    ")"
)
_MARKER_SQL = text(
    "SELECT version_id, document_id, unit_count, input_digest, tokenizer_version, ready "
    "FROM retrieval_version_index WHERE version_id = :version ORDER BY version_id"
)
_UNIT_INDEX_SQL = text(
    "SELECT group_concat(rowtext, char(30)) FROM ("
    "  SELECT "
    "    CASE WHEN fts_rowid IS NULL THEN '-' ELSE 'i'||length(CAST(fts_rowid AS TEXT))||':'||CAST(fts_rowid AS TEXT) END ||"
    "    CASE WHEN unit_id IS NULL THEN '-' ELSE 't'||length(unit_id)||':'||unit_id END ||"
    "    CASE WHEN version_id IS NULL THEN '-' ELSE 't'||length(version_id)||':'||version_id END ||"
    "    CASE WHEN document_id IS NULL THEN '-' ELSE 't'||length(document_id)||':'||document_id END ||"
    "    CASE WHEN entity_type IS NULL THEN '-' ELSE 't'||length(entity_type)||':'||entity_type END ||"
    "    CASE WHEN entity_key IS NULL THEN '-' ELSE 't'||length(entity_key)||':'||entity_key END ||"
    "    CASE WHEN label IS NULL THEN '-' ELSE 't'||length(label)||':'||label END ||"
    "    CASE WHEN entity_filters IS NULL THEN '-' ELSE 't'||length(entity_filters)||':'||entity_filters END ||"
    "    CASE WHEN token_count IS NULL THEN '-' ELSE 'i'||length(CAST(token_count AS TEXT))||':'||CAST(token_count AS TEXT) END"
    "  AS rowtext FROM retrieval_unit_index"
    "  WHERE version_id = :version OR unit_id IN (SELECT id FROM source_units WHERE version_id = :version)"
    "  ORDER BY fts_rowid"
    ")"
)
_FIELD_INDEX_SQL = text(
    "SELECT group_concat(rowtext, char(30)) FROM ("
    "  SELECT "
    "    CASE WHEN unit_id IS NULL THEN '-' ELSE 't'||length(unit_id)||':'||unit_id END ||"
    "    CASE WHEN version_id IS NULL THEN '-' ELSE 't'||length(version_id)||':'||version_id END ||"
    "    CASE WHEN document_id IS NULL THEN '-' ELSE 't'||length(document_id)||':'||document_id END ||"
    "    CASE WHEN field_name IS NULL THEN '-' ELSE 't'||length(field_name)||':'||field_name END ||"
    "    CASE WHEN field_role IS NULL THEN '-' ELSE 't'||length(field_role)||':'||field_role END ||"
    "    CASE WHEN norm_value IS NULL THEN '-' ELSE 't'||length(norm_value)||':'||norm_value END ||"
    "    CASE WHEN value_text IS NULL THEN '-' ELSE 't'||length(value_text)||':'||value_text END"
    "  AS rowtext FROM retrieval_field_index"
    "  WHERE version_id = :version OR unit_id IN (SELECT id FROM source_units WHERE version_id = :version)"
    "  ORDER BY id"
    ")"
)
_FTS_SQL = text(
    "SELECT group_concat(rowtext, char(30)) FROM ("
    "  SELECT "
    "    CASE WHEN rowid IS NULL THEN '-' ELSE 'i'||length(CAST(rowid AS TEXT))||':'||CAST(rowid AS TEXT) END ||"
    "    CASE WHEN body IS NULL THEN '-' ELSE 't'||length(body)||':'||body END"
    "  AS rowtext FROM source_unit_fts WHERE version_id = :version ORDER BY rowid"
    ")"
)

_LOCK = threading.RLock()
_CACHE: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()
_STATS = {
    "full_verifications": 0,
    "fingerprint_hits": 0,
    "fingerprint_misses": 0,
    "fingerprint_unavailable": 0,
}


@dataclass(frozen=True)
class _VerifiedState:
    """一次“完整核验通过”对应的真实行状态；revision 变化即整体失效。"""

    revision: int
    digest: bytes


def _feed_hash(hash_, tag: bytes, payload: str | None) -> None:
    hash_.update(tag)
    if payload is None:
        hash_.update(b"\x00")
        return
    encoded = payload.encode("utf-8", "surrogatepass")
    hash_.update(len(encoded).to_bytes(8, "big"))
    hash_.update(encoded)


def _state_digest(db: Session, version: DocumentVersion) -> bytes | None:
    """重算该版本“完整核验会读取的真实行”指纹；FTS 结构不可用时返回 None。"""
    params = {"version": version.id.hex}
    fts_params = {"version": str(version.id)}
    try:
        hash_ = hashlib.sha256()
        hash_.update(_FINGERPRINT_TAG)
        _feed_hash(
            hash_,
            b"version",
            repr(
                (
                    version.id.hex,
                    version.document_id.hex if version.document_id is not None else None,
                    version.sha256,
                    getattr(version, "state", None),
                )
            ),
        )
        for tag, query, query_params in (
            (b"source_units", _SOURCE_UNITS_SQL, params),
            (b"unit_index", _UNIT_INDEX_SQL, params),
            (b"field_index", _FIELD_INDEX_SQL, params),
            (b"fts", _FTS_SQL, fts_params),
        ):
            _feed_hash(hash_, tag, db.scalar(query, query_params))
        marker = db.execute(_MARKER_SQL, params).all()
        _feed_hash(hash_, b"marker", repr([tuple(row) for row in marker]))
        return hash_.digest()
    except OperationalError:
        # FTS 表缺失/损坏：无法证明“未变化”，交给完整核验按既有语义返回未就绪。
        return None


def _engine_of(db: Session):
    bind = db.get_bind()
    return getattr(bind, "engine", bind)


def verify_version_index_cached(db: Session, version: DocumentVersion, *, revision: int) -> bool:
    """缓存感知的完整性判定；返回 True 当且仅当当前真实状态通过完整核验。

    - 指纹命中且 revision 一致：返回 True（该状态上次已完整核验通过）；
    - 否则执行 `index.verify_version_index`，通过后记录新指纹；不通过不缓存。
    """
    digest = _state_digest(db, version)
    if digest is None:
        with _LOCK:
            _STATS["fingerprint_unavailable"] += 1
        return verify_version_index(db, version)

    engine = _engine_of(db)
    with _LOCK:
        bucket = _CACHE.get(engine)
        entry = bucket.get(version.id) if bucket is not None else None
        if entry is not None and entry.revision == revision and entry.digest == digest:
            _STATS["fingerprint_hits"] += 1
            return True
        _STATS["fingerprint_misses"] += 1

    verified = verify_version_index(db, version)
    with _LOCK:
        _STATS["full_verifications"] += 1
        if verified:
            _CACHE.setdefault(engine, {})[version.id] = _VerifiedState(revision, digest)
    return verified


def verification_stats() -> dict[str, int]:
    """诊断/证据用：缓存命中、完整核验与指纹不可用次数。"""
    with _LOCK:
        payload = dict(_STATS)
        payload["cache_entries"] = sum(len(bucket) for bucket in _CACHE.values())
        return payload


def clear_verified_state() -> None:
    """诊断/测试用：清空进程内已通过核验的状态（不触碰数据库）。"""
    with _LOCK:
        _CACHE.clear()

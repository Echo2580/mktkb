"""T005：评测语料装配（薄适配 ``tools/rag_experiment.py``，不复制解析逻辑）。

两个 suite 的语料来源不同，但都只做**装配**（解析入口统一走既有
``ingestion.parsers.parse_document`` 与 ``rag_experiment.load_corpus``）：

- ``b0``：``fixtures/acceptance/manifest.json`` 的 ``normal_files``，只取
  ``xlsx / docx / pdf-text``（D01–D06）。D07/D08 扫描 PDF 与 D09/D10 图片属于 OCR 题，
  **不解析**，在装配阶段就按 kind 排除（解析即触发 OCR 路径）。
- ``badcase``：``corpus/enterprise-20261101/manifest.json`` 的 ``files``，复用
  ``rag_experiment.load_corpus`` + ``build_new_index``，只解析被 gold 引用的
  E03/E11/P03/W01；缺任一份直接 fail closed。
- ``regression``（P1 T107）：同一 ``corpus/enterprise-20261101`` 全量语料
  （``rag_experiment`` 的既有 subset policy 会排除 boundary/scan/X04），并强制
  本轮数据集引用的 ``doc_code`` 全部解析成功；缺任一份直接 fail closed。

索引一律建在调用方给出的隔离路径（runner 用临时目录），不触碰 ``var/`` 与产品库。
"""

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..ingestion.parsers import ParseError, ParseServices, parse_document
from ..rag import AtomicUnit, DocumentSpec, RagConfig, RagIndex, adapt_parsed_unit

__all__ = [
    "BADCASE_CODES",
    "B0_NON_OCR_KINDS",
    "Corpus",
    "CorpusError",
    "DEFAULT_CORPUS_DIRS",
    "build_suite_index",
    "default_corpus_dir",
    "default_dataset_path",
    "load_suite_corpus",
    "offline_eval_config",
]

PROJECT_ROOT = Path(__file__).resolve().parents[4]

SUITES = frozenset({"b0", "badcase", "regression"})
#: B0 可离线解析的资料 kind；扫描 PDF/图片不在此集合，禁止进入解析。
B0_NON_OCR_KINDS = frozenset({"xlsx", "docx", "pdf-text"})
B0_REQUIRED_CODES = ("D01", "D02", "D03", "D04", "D05", "D06")
BADCASE_CODES = ("E03", "E11", "P03", "W01")
DEFAULT_CORPUS_DIRS: dict[str, Path] = {
    "b0": PROJECT_ROOT / "fixtures" / "acceptance",
    "badcase": PROJECT_ROOT / "corpus" / "enterprise-20261101",
    "regression": PROJECT_ROOT / "corpus" / "enterprise-20261101",
}
EVAL_DATASET_DIR = PROJECT_ROOT / "fixtures" / "evaluation"


class CorpusError(RuntimeError):
    """语料装配失败（缺资料 / 解析失败 / 索引构建失败）；调用方必须 fail closed。"""


@dataclass(frozen=True)
class Corpus:
    """一个 suite 的装配结果；``documents`` 保持 manifest 的确定性顺序。"""

    suite: str
    root: Path
    manifest_path: Path
    manifest_sha256: str
    business_date: str | None
    documents: tuple[tuple[DocumentSpec, tuple[AtomicUnit, ...]], ...]
    skipped: tuple[Mapping[str, Any], ...]


def default_corpus_dir(suite: str) -> Path:
    """返回 suite 的默认语料目录；未知 suite 直接 ``ValueError``。"""
    if suite not in SUITES:
        raise ValueError(f"未知 suite {suite!r}；只允许 {sorted(SUITES)}")
    return DEFAULT_CORPUS_DIRS[suite]


def default_dataset_path(suite: str) -> Path:
    """返回 suite 的冻结数据集路径（``fixtures/evaluation/<suite>.jsonl``）。"""
    if suite not in SUITES:
        raise ValueError(f"未知 suite {suite!r}；只允许 {sorted(SUITES)}")
    return EVAL_DATASET_DIR / f"{suite}.jsonl"


def offline_eval_config(data_dir: Path, business_date: str) -> RagConfig:
    """评测专用离线配置（与 T004a ``conftest.offline_config`` 同参数）。

    只使用确定性替身：``provider_mode="offline"`` 时 ``RagIndex`` 装配
    ``FakeEmbeddingProvider`` 与 ``LexicalReranker``，0 次真实 provider 调用。
    """
    return RagConfig(
        provider_mode="offline",
        data_dir=Path(data_dir),
        business_date=business_date,
        chunk_max_chars=420,
        chunk_max_units=3,
        chunk_overlap_units=1,
        top_k=5,
        page_size=10,
        vector_candidate_limit=50,
        rerank_top_n=20,
    )


def _read_manifest(root: Path) -> tuple[dict[str, Any], Path, str]:
    manifest_path = root / "manifest.json"
    try:
        raw = manifest_path.read_bytes()
    except OSError as exc:
        raise CorpusError(f"无法读取语料 manifest {manifest_path}: {exc}") from exc
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CorpusError(f"语料 manifest 不是合法 UTF-8 JSON: {manifest_path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise CorpusError(f"语料 manifest 必须是 JSON 对象: {manifest_path}")
    return payload, manifest_path, hashlib.sha256(raw).hexdigest()


def _title(path: Path) -> str:
    """与 ``rag_experiment._doc_title`` / T004a fixture 相同的标题规则。"""
    stem = path.stem
    return stem.split("_", 1)[1] if "_" in stem else stem


def _load_acceptance_documents(
    root: Path, manifest: Mapping[str, Any], business_date: str | None
) -> tuple[list[tuple[DocumentSpec, list[AtomicUnit]]], list[dict[str, Any]]]:
    normal_files = manifest.get("normal_files")
    if not isinstance(normal_files, list):
        raise CorpusError("B0 manifest 缺少 normal_files 数组")
    documents: list[tuple[DocumentSpec, list[AtomicUnit]]] = []
    skipped: list[dict[str, Any]] = []
    for item in normal_files:
        if not isinstance(item, Mapping):
            raise CorpusError("B0 normal_files 项必须是对象")
        code = str(item.get("id") or "")
        rel = str(item.get("path") or "")
        kind = str(item.get("kind") or "")
        if kind not in B0_NON_OCR_KINDS:
            # 扫描 PDF / 图片：显式跳过，绝不调用解析器（解析会触发 OCR 路径）。
            skipped.append({"code": code, "path": rel, "reason": f"not_offline_kind:{kind}"})
            continue
        path = root / rel
        file_kind = path.suffix.lower().lstrip(".")
        try:
            parsed = list(parse_document(path, file_kind, ParseServices()))
        except (ParseError, Exception) as exc:  # 解析失败不启动 OCR，也不冒充成功
            raise CorpusError(f"B0 资料解析失败 {code} ({rel}): {type(exc).__name__}: {exc}") from exc
        if not parsed:
            raise CorpusError(f"B0 资料没有解析出任何 unit: {code} ({rel})")
        spec = DocumentSpec(
            doc_id=code,
            logical_id=code,
            source_path=rel,
            title=_title(path),
            file_kind=file_kind,
            version_id=f"{code}-v1",
            version_label="当前",
            sha256=str(item.get("sha256") or hashlib.sha256(path.read_bytes()).hexdigest()),
            business_date=business_date,
        )
        units = [
            adapt_parsed_unit(unit, doc=spec, unit_id=f"{code}-{ordinal}", ordinal=ordinal)
            for ordinal, unit in enumerate(parsed)
        ]
        documents.append((spec, units))
    parsed_codes = {spec.doc_id for spec, _ in documents}
    missing = [code for code in B0_REQUIRED_CODES if code not in parsed_codes]
    if missing:
        raise CorpusError(f"B0 必要资料缺失: {missing}")
    return documents, skipped


def _load_rag_experiment():
    """延迟导入 ``tools/rag_experiment.py``（入口脚本不是包，需要临时加 sys.path）。"""
    tools_dir = PROJECT_ROOT / "tools"
    if not (tools_dir / "rag_experiment.py").is_file():
        raise CorpusError(f"找不到语料装配入口: {tools_dir / 'rag_experiment.py'}")
    if str(tools_dir) not in sys.path:
        sys.path.insert(0, str(tools_dir))
    import rag_experiment  # noqa: PLC0415 - 只在装配时导入，避免模块顶层副作用

    return rag_experiment


def _load_enterprise_documents(
    root: Path,
    manifest: Mapping[str, Any],
    *,
    only_codes: Sequence[str] | None,
    required_codes: Sequence[str] | None,
) -> tuple[list[tuple[DocumentSpec, list[AtomicUnit]]], list[dict[str, Any]], str | None]:
    rag_experiment = _load_rag_experiment()
    documents, skipped = rag_experiment.load_corpus(
        root, only_codes=None if only_codes is None else set(only_codes)
    )
    parsed_codes = {spec.doc_id for spec, _ in documents}
    required = set(required_codes or ())
    missing = sorted(required - parsed_codes)
    if missing:
        raise CorpusError(
            f"必要资料解析缺失: {missing} / skipped={skipped[:5]}"
        )
    business_date = manifest.get("business_base_date") or manifest.get("business_date")
    return documents, skipped, None if business_date is None else str(business_date)


def load_suite_corpus(
    suite: str,
    corpus_dir: Path | str | None = None,
    *,
    business_date: str | None = None,
    required_codes: Sequence[str] | None = None,
) -> Corpus:
    """按 suite 装配文档（不建索引、不写任何数据库）。

    ``required_codes`` 只对 ``regression`` 生效：本轮数据集引用到的 ``doc_code``
    必须全部解析成功，缺任一份 fail closed（``badcase`` 固定要求四份）。
    """
    if suite not in SUITES:
        raise ValueError(f"未知 suite {suite!r}；只允许 {sorted(SUITES)}")
    root = Path(corpus_dir) if corpus_dir is not None else default_corpus_dir(suite)
    if not root.is_dir():
        raise CorpusError(f"语料目录不存在: {root}")
    manifest, manifest_path, manifest_sha256 = _read_manifest(root)
    if suite == "b0":
        date = business_date or manifest.get("business_date")
        documents, skipped = _load_acceptance_documents(
            root, manifest, None if date is None else str(date)
        )
        resolved_date = None if date is None else str(date)
    elif suite == "badcase":
        documents, skipped, resolved_date = _load_enterprise_documents(
            root, manifest, only_codes=BADCASE_CODES, required_codes=BADCASE_CODES
        )
    else:
        documents, skipped, resolved_date = _load_enterprise_documents(
            root, manifest, only_codes=None, required_codes=required_codes
        )
    return Corpus(
        suite=suite,
        root=root,
        manifest_path=manifest_path,
        manifest_sha256=manifest_sha256,
        business_date=resolved_date,
        documents=tuple((spec, tuple(units)) for spec, units in documents),
        skipped=tuple(dict(item) for item in skipped),
    )


def build_suite_index(
    corpus: Corpus,
    db_path: Path,
    *,
    config: RagConfig | None = None,
) -> tuple[RagIndex, dict[str, Any]]:
    """在 ``db_path`` 构建隔离索引；``provider_mode`` 必须为 offline。"""
    if corpus.suite not in SUITES:
        raise ValueError(f"未知 suite {corpus.suite!r}")
    if not corpus.documents:
        raise CorpusError("语料为空，拒绝构建空索引")
    cfg = config or offline_eval_config(
        Path(db_path).parent, corpus.business_date or "2026-10-28"
    )
    if cfg.provider_mode != "offline":
        raise ValueError(
            f"评测只允许 provider_mode='offline'，收到 {cfg.provider_mode!r}（零真实调用）"
        )
    if corpus.suite in {"badcase", "regression"}:
        rag_experiment = _load_rag_experiment()
        index, stats = rag_experiment.build_new_index(
            [(spec, list(units)) for spec, units in corpus.documents],
            db_path=Path(db_path),
            config=cfg,
        )
        if int(stats.get("documents") or 0) != len(corpus.documents):
            index.close()
            raise CorpusError(
                f"{corpus.suite} 索引资料数 {stats.get('documents')} != 装配数 {len(corpus.documents)}"
            )
        summary = {
            "suite": corpus.suite,
            "documents": int(stats.get("documents") or 0),
            "units": int(stats.get("units") or 0),
            "chunks": int(stats.get("chunks") or 0),
            "revision": index.revision(),
        }
        return index, summary

    index = RagIndex(Path(db_path), config=cfg)
    try:
        results: list[dict[str, Any]] = []
        for spec, units in corpus.documents:
            result = index.add_document(spec, units, embed=True)
            if result.get("embedding_error"):
                raise CorpusError(
                    f"B0 索引 embedding 失败 {spec.doc_id}: {result['embedding_error']}"
                )
            results.append(result)
        summary = {
            "suite": corpus.suite,
            "documents": len(corpus.documents),
            "units": sum(int(item.get("units") or 0) for item in results),
            "chunks": sum(int(item.get("chunks") or 0) for item in results),
            "revision": index.revision(),
        }
        return index, summary
    except BaseException:
        index.close()
        raise

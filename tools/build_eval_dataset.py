"""构建 P0 评测数据集：B0 40 题 + Bad Case 13 题 -> fixtures/evaluation/*.jsonl。

用法（仓库根目录）：

    .\\.venv\\Scripts\\python.exe -B tools\\build_eval_dataset.py ^
        --b0 fixtures\\acceptance\\questions.json ^
        --badcase docs\\evidence\\LOCAL-R1-20261101\\S1-DEV\\questions.json ^
        --out fixtures\\evaluation

转换规则（设计 §7.1 / §7.2 / P0 计划 Task 4 Step 3）：

- exact：用 ``record`` 在 xlsx 的 identifier 列定位唯一行 -> ``sheet:<名>:row:<行>``；
- text：在 ``locator.heading`` 限定的段落中，用本组期望值唯一定位答案段 -> ``paragraph:<n>``
  （PDF 为 ``paragraph:p<页>:l<行>``），原 locator 作为可读/跨版本回退保留；
- ocr：``requires_ocr=true``，只保留页级 locator（单页图片为 page=1），P0 不解析、不触发 OCR；
- badcase：``row`` -> 行级 ``unit_key``；``clause``（第七条）-> 该条款段落 ``unit_key``；
  只给 ``sheet`` / 只给 ``file`` 的来源是范围型 locator（整表 / 整篇），不伪造唯一行。

构建后用**离线索引 + 逐题 resolve_gold** 证明 gold 可定位（B0 32 道非 OCR + badcase 13 道），
任一 gold 无法解析即报错退出，不静默丢弃；输出为 UTF-8 / ``ensure_ascii=False`` / ``\\n``，
连续两次运行字节一致。零真实模型 / OCR / embedding / rerank 调用。
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "backend" / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "backend" / "src"))
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

from mktkb.evaluation.dataset import CaseSpec, dataset_version, validate_case, write_cases  # noqa: E402
from mktkb.evaluation.gold import GoldUnresolved, resolve_gold  # noqa: E402
from mktkb.ingestion.parsers import ParseServices, parse_document  # noqa: E402
from mktkb.rag import DocumentSpec, RagConfig, RagIndex, adapt_parsed_unit  # noqa: E402
from mktkb.rag.chunking import field_role  # noqa: E402

BUSINESS_DATE = "2026-10-28"
LABELER = "lead"
LABEL_VERSIONS = {"b0": "b0-2026-11-04", "badcase": "badcase-2026-11-04"}
# B0 的 D07/D08 是扫描 PDF、D09/D10 是图片：解析它们必然走 OCR 路径，本包禁止。
B0_NON_OCR_KINDS = {"xlsx", "docx", "pdf-text"}
BADCASE_CODES = ("E03", "E11", "P03", "W01")
REFUSAL_REASON = "资料未收录该门店/标识，无依据可答，不得编造"
# 明确的会话上下文注记（不猜测）：N11 是 N10 澄清后的短追问，数据集按单轮记录。
BADCASE_CONTEXT_NOTES = {
    "N11": "承接同会话 N10 的澄清追问（“滨江店”）；turns 留空，数据集按单轮记录，多轮上下文由 runner 负责",
}


class BuildError(RuntimeError):
    """数据集构建失败：转换规则无法唯一定位 gold，或离线校验不通过。"""


def _norm(text: object) -> str:
    return re.sub(r"\s+", "", str(text or "")).lower()


def _subsequence(needle: str, haystack: str) -> bool:
    position = 0
    for character in needle:
        position = haystack.find(character, position)
        if position < 0:
            return False
        position += 1
    return True


def _same_value(actual: Any, expected: Any) -> bool:
    if actual is None or expected is None:
        return actual is expected
    return actual == expected or str(actual) == str(expected)


def _title(item: dict[str, Any]) -> str:
    stem = Path(str(item["path"])).stem
    return stem.split("_", 1)[1] if "_" in stem else stem


class _Parsed:
    """一次解析缓存；只读本地文件，不注入 OCR 网关。"""

    def __init__(self) -> None:
        self._cache: dict[str, list[Any]] = {}

    def units(self, path: Path) -> list[Any]:
        key = str(path)
        if key not in self._cache:
            kind = path.suffix.lower().lstrip(".")
            self._cache[key] = list(parse_document(path, kind, ParseServices()))
        return self._cache[key]


def _b0_documents(root: Path, parsed: _Parsed) -> list[tuple[DocumentSpec, list[Any]]]:
    """B0 非 OCR 资料（D01–D06）的离线索引输入。"""
    manifest = json.loads((root / "fixtures/acceptance/manifest.json").read_text(encoding="utf-8"))
    documents: list[tuple[DocumentSpec, list[Any]]] = []
    for item in manifest["normal_files"]:
        if str(item.get("kind")) not in B0_NON_OCR_KINDS:
            continue
        path = root / "fixtures/acceptance" / str(item["path"])
        kind = path.suffix.lower().lstrip(".")
        units = parsed.units(path)
        spec = DocumentSpec(
            doc_id=str(item["id"]),
            logical_id=str(item["id"]),
            source_path=str(item["path"]),
            title=_title(item),
            file_kind=kind,
            version_id=f"{item['id']}-v1",
            version_label="当前",
            sha256=str(item["sha256"]),
            business_date=BUSINESS_DATE,
        )
        adapted = [
            adapt_parsed_unit(unit, doc=spec, unit_id=f"{item['id']}-{ordinal}", ordinal=ordinal)
            for ordinal, unit in enumerate(units)
        ]
        documents.append((spec, adapted))
    return documents


def _offline_config(data_dir: Path) -> RagConfig:
    return RagConfig(
        provider_mode="offline",
        data_dir=data_dir,
        business_date=BUSINESS_DATE,
        chunk_max_chars=420,
        chunk_max_units=3,
        chunk_overlap_units=1,
        top_k=5,
        page_size=10,
        vector_candidate_limit=50,
        rerank_top_n=20,
    )


def _build_index(documents: Sequence[tuple[DocumentSpec, list[Any]]], db_path: Path) -> RagIndex:
    index = RagIndex(db_path, config=_offline_config(db_path.parent))
    for spec, units in documents:
        result = index.add_document(spec, units, embed=True)
        if result.get("embedding_error"):
            index.close()
            raise BuildError(f"离线索引构建失败 {spec.doc_id}: {result['embedding_error']}")
    return index


def _build_badcase_documents(root: Path) -> list[tuple[DocumentSpec, list[Any]]]:
    from rag_experiment import load_corpus  # 复用既有语料装配，不复制解析逻辑

    documents, skipped = load_corpus(root / "corpus/enterprise-20261101", only_codes=set(BADCASE_CODES))
    missing = set(BADCASE_CODES) - {spec.doc_id for spec, _ in documents}
    if missing:
        raise BuildError(f"badcase 必要资料解析缺失: {sorted(missing)} / {skipped}")
    return documents


# ---------------------------------------------------------------- B0 单题转换


def _exact_unit(units: Sequence[Any], record: str, *, case_id: str) -> Any:
    hits = []
    for unit in units:
        for name, value in (unit.fields or {}).items():
            if field_role(name) == "identifier" and str(value).strip() == record:
                hits.append(unit)
                break
    if len(hits) != 1:
        raise BuildError(f"{case_id}: identifier={record!r} 命中 {len(hits)} 行（必须唯一）")
    return hits[0]


def _text_unit(units: Sequence[Any], heading: str | None, values: Sequence[str], *, case_id: str) -> Any:
    candidates = list(units)
    if heading:
        under = [unit for unit in units if _norm((unit.locator or {}).get("heading")) == _norm(heading)]
        if under:
            candidates = under
    if not candidates:
        raise BuildError(f"{case_id}: 没有可匹配的候选 unit")
    scores = [
        (sum(1 for value in values if _norm(value) in _norm(unit.text)), unit)
        for unit in candidates
    ]
    best = max(score for score, _ in scores)
    winners = [unit for score, unit in scores if score == best]
    if best <= 0:
        raise BuildError(f"{case_id}: 期望值在候选 unit 中一个都没有命中")
    if len(winners) != 1:
        raise BuildError(f"{case_id}: 有 {len(winners)} 个候选 unit 并列最高分 {best}，无法唯一定位")
    chosen = winners[0]
    haystack = _norm(chosen.text)
    missing = [value for value in values if _norm(value) not in haystack and not _subsequence(_norm(value), haystack)]
    if missing:
        raise BuildError(f"{case_id}: 选中 {chosen.unit_key} 仍缺少期望值 {missing}")
    return chosen


def _convert_b0(root: Path, questions_path: Path, parsed: _Parsed) -> list[CaseSpec]:
    payload = json.loads(questions_path.read_text(encoding="utf-8"))
    if payload.get("version") != "B0":
        raise BuildError(f"B0 题目 version 应为 'B0'，实际 {payload.get('version')!r}")
    manifest = json.loads((root / "fixtures/acceptance/manifest.json").read_text(encoding="utf-8"))
    files = {str(item["id"]): item for item in manifest["normal_files"]}
    normal = [item for item in payload["questions"] if item.get("group") == "normal"]
    if len(normal) != 40:
        raise BuildError(f"B0 group=normal 应为 40 题，实际 {len(normal)}")
    categories = {name: sum(1 for item in normal if item.get("category") == name) for name in ("exact", "text", "ocr")}
    if categories != {"exact": 24, "text": 8, "ocr": 8}:
        raise BuildError(f"B0 分类计数不符: {categories}")

    cases: list[CaseSpec] = []
    for item in normal:
        case_id = str(item["id"])
        category = str(item["category"])
        kind = str((item.get("scenario") or {}).get("expected_kind") or "answer")
        values = [str(value) for value in item.get("expected_values") or []]
        source = dict((item.get("expected_sources") or [{}])[0])
        unknown_source = set(source) - {"file", "record", "locator"}
        if unknown_source:
            raise BuildError(f"{case_id}: 原始来源含未处理字段 {sorted(unknown_source)}，拒绝静默丢弃")
        doc_code = str(source.get("file") or "")
        if doc_code not in files:
            raise BuildError(f"{case_id}: 未知资料编码 {doc_code!r}")
        path = root / "fixtures/acceptance" / str(files[doc_code]["path"])

        if category == "exact":
            record = str(source.get("record") or "")
            unit = _exact_unit(parsed.units(path), record, case_id=case_id)
            expected_sources = [
                {"doc_code": doc_code, "record_code": record, "unit_key": str(unit.unit_key)}
            ]
            notes = (
                f"来源 fixtures/acceptance/questions.json {case_id}（group=normal, category=exact）；"
                f"identifier={record!r} -> unit_key={unit.unit_key}"
            )
            requires_ocr = False
        elif category == "text":
            locator = dict(source.get("locator") or {})
            unit = _text_unit(parsed.units(path), locator.get("heading"), values, case_id=case_id)
            expected_sources = [
                {"doc_code": doc_code, "unit_key": str(unit.unit_key), "locator": locator}
            ]
            notes = (
                f"来源 fixtures/acceptance/questions.json {case_id}（group=normal, category=text）；"
                f"按 locator.heading 与期望值唯一定位到 unit_key={unit.unit_key}"
            )
            requires_ocr = False
        else:
            locator = dict(source.get("locator") or {})
            page = locator.get("page")
            if not isinstance(page, int):
                # D09/D10 是单页图片：原 locator.image/table_row 归一为 page=1（§5.3 允许）。
                page = 1
            expected_sources = [{"doc_code": doc_code, "locator": {"page": page}}]
            notes = (
                f"来源 fixtures/acceptance/questions.json {case_id}（group=normal, category=ocr）；"
                f"requires_ocr=true，P0 不解析、不触发 OCR；原 locator={locator!r} 归一为 page={page}"
            )
            requires_ocr = True

        case = CaseSpec(
            case_id=case_id,
            suite="b0",
            split="dev",
            stratum=category,
            business_date=BUSINESS_DATE,
            question=str(item["question"]),
            turns=(),
            expected_kind=kind,
            expected_values=tuple(values),
            expected_sources=tuple(expected_sources),
            relevant_units=(),
            reference_answer="；".join(values),
            should_refuse=False,
            refusal_reason=None,
            forbidden_values=(),
            forbidden_sources=(),
            expected_pagination=None,
            requires_ocr=requires_ocr,
            labeler=LABELER,
            label_version=LABEL_VERSIONS["b0"],
            notes=notes,
        )
        validate_case(case)
        cases.append(case)
    return cases


# ---------------------------------------------------------------- Bad Case 转换


def _corpus_units(root: Path, parsed: _Parsed, code: str) -> list[Any]:
    manifest = json.loads((root / "corpus/enterprise-20261101/manifest.json").read_text(encoding="utf-8"))
    item = next((entry for entry in manifest["files"] if str(entry.get("code")) == code), None)
    if item is None:
        raise BuildError(f"语料清单缺少资料 {code}")
    return parsed.units(root / "corpus/enterprise-20261101" / str(item["path"]))


def _convert_badcase_source(
    root: Path, parsed: _Parsed, source: dict[str, Any], *, case_id: str
) -> tuple[dict[str, Any], str]:
    unknown = set(source) - {"file", "row", "sheet", "clause"}
    if unknown:
        raise BuildError(f"{case_id}: 原始来源含未处理字段 {sorted(unknown)}，拒绝静默丢弃")
    doc_code = str(source.get("file") or "")
    units = _corpus_units(root, parsed, doc_code)
    if "clause" in source:
        clause = str(source["clause"])
        hits = [unit for unit in units if _norm(unit.text).startswith(_norm(clause))]
        if len(hits) != 1:
            raise BuildError(f"{case_id}: clause={clause!r} 命中 {len(hits)} 段（必须唯一）")
        unit = hits[0]
        note = f"clause={clause!r} -> unit_key={unit.unit_key}"
        return {"doc_code": doc_code, "unit_key": str(unit.unit_key), "locator": {"paragraph": (unit.locator or {}).get("paragraph")}}, note
    if "row" in source:
        sheet = source.get("sheet")
        hits = [
            unit
            for unit in units
            if _same_value((unit.locator or {}).get("row", getattr(unit, "row_number", None)), source["row"])
            and (sheet is None or _same_value((unit.locator or {}).get("sheet", unit.sheet), sheet))
        ]
        if len(hits) != 1:
            raise BuildError(f"{case_id}: row={source['row']!r} sheet={sheet!r} 命中 {len(hits)} 行（必须唯一）")
        unit = hits[0]
        locator = {"row": source["row"]}
        if sheet is not None:
            locator["sheet"] = sheet
        note = f"row={source['row']!r} sheet={sheet!r} -> unit_key={unit.unit_key}"
        return {"doc_code": doc_code, "unit_key": str(unit.unit_key), "locator": locator}, note
    if "sheet" in source:
        note = f"sheet={source['sheet']!r} 为范围型来源（整表），保留 locator 不伪造行号"
        return {"doc_code": doc_code, "locator": {"sheet": source["sheet"]}}, note
    note = "整篇级来源（只给 file），保留 doc_code 作为范围型 gold"
    return {"doc_code": doc_code}, note


def _convert_badcase(root: Path, questions_path: Path, parsed: _Parsed) -> list[CaseSpec]:
    payload = json.loads(questions_path.read_text(encoding="utf-8"))
    if payload.get("business_date") != BUSINESS_DATE:
        raise BuildError(f"badcase business_date 应为 {BUSINESS_DATE}，实际 {payload.get('business_date')!r}")
    cases: list[CaseSpec] = []
    for conversation in payload["conversations"]:
        group = str(conversation["id"])
        for item in conversation["questions"]:
            case_id = str(item["id"])
            kind = str(item.get("expected_kind") or "answer")
            values = [str(value) for value in item.get("expected_values") or []]
            raw_sources = [dict(source) for source in item.get("expected_sources") or []]
            converted: list[dict[str, Any]] = []
            notes: list[str] = [
                f"来源 docs/evidence/LOCAL-R1-20261101/S1-DEV/questions.json conversations[{group}] {case_id}"
            ]
            for raw in raw_sources:
                converted_source, note = _convert_badcase_source(root, parsed, raw, case_id=case_id)
                converted.append(converted_source)
                notes.append(note)
            if not raw_sources:
                notes.append("无期望来源（歧义/无答案题），gold 为空")
            if case_id in BADCASE_CONTEXT_NOTES:
                notes.append(BADCASE_CONTEXT_NOTES[case_id])
            if item.get("expected_min_total") is not None:
                notes.append(f"expected_min_total={item['expected_min_total']}（保留原始期望，不伪装成四分页契约）")
            should_refuse = kind in {"no_answer", "refusal"}
            case = CaseSpec(
                case_id=case_id,
                suite="badcase",
                split="dev",
                stratum=group,
                business_date=BUSINESS_DATE,
                question=str(item["question"]),
                turns=(),
                expected_kind=kind,
                expected_values=tuple(values),
                expected_sources=tuple(converted),
                relevant_units=(),
                reference_answer="",
                should_refuse=should_refuse,
                refusal_reason=REFUSAL_REASON if should_refuse else None,
                forbidden_values=(),
                forbidden_sources=(),
                expected_pagination=None,
                requires_ocr=False,
                labeler=LABELER,
                label_version=LABEL_VERSIONS["badcase"],
                notes="；".join(notes),
            )
            validate_case(case)
            cases.append(case)
    if len(cases) != 13:
        raise BuildError(f"badcase 应为 13 题，实际 {len(cases)}")
    return cases


# ---------------------------------------------------------------- 离线校验


def _verify(suite: str, cases: Sequence[CaseSpec], index: RagIndex) -> dict[str, Any]:
    resolved = resolve_gold(cases, index)
    by_id = {case.case_id: case for case in cases}
    non_ocr = [item for item in resolved if not item.requires_ocr]
    skipped = [item for item in resolved if item.requires_ocr]
    with_gold = [item for item in non_ocr if by_id[item.case_id].expected_sources]
    missing = [item.case_id for item in with_gold if not item.unit_ids]
    if missing:
        raise BuildError(f"{suite}: 声明了来源但解析后没有 unit: {missing}")
    detail = []
    for item in resolved:
        if item.requires_ocr:
            detail.append(f"{item.case_id} skipped_requires_ocr")
            continue
        if not item.sources:
            detail.append(f"{item.case_id} no_gold")
            continue
        parts = [f"{source.doc_code}:{','.join(source.unit_keys)}" for source in item.sources]
        detail.append(f"{item.case_id} {' | '.join(parts)} units={len(item.unit_ids)}")
    return {
        "cases": len(resolved),
        "resolved": len(with_gold),
        "no_gold": len(non_ocr) - len(with_gold),
        "skipped_requires_ocr": len(skipped),
        "units": sum(len(item.unit_ids) for item in with_gold),
        "detail": detail,
    }


def build_dataset(root: Path, b0_path: Path, badcase_path: Path, out_dir: Path) -> dict[str, Any]:
    parsed = _Parsed()
    b0_cases = _convert_b0(root, b0_path, parsed)
    badcase_cases = _convert_badcase(root, badcase_path, parsed)

    workdir = Path(tempfile.mkdtemp(prefix="t004a-eval-"))
    try:
        b0_index = _build_index(_b0_documents(root, parsed), workdir / "b0" / "rag.sqlite3")
        try:
            b0_stats = _verify("b0", b0_cases, b0_index)
        finally:
            b0_index.close()
        badcase_index = _build_index(_build_badcase_documents(root), workdir / "badcase" / "rag.sqlite3")
        try:
            badcase_stats = _verify("badcase", badcase_cases, badcase_index)
        finally:
            badcase_index.close()
    except GoldUnresolved as exc:  # 显式列出、绝不静默丢弃
        raise BuildError(f"gold 解析失败: {exc}") from exc
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    shas = {"b0": write_cases(out_dir / "b0.jsonl", b0_cases), "badcase": write_cases(out_dir / "badcase.jsonl", badcase_cases)}
    return {
        "b0": {
            "cases": len(b0_cases),
            "sha256": shas["b0"],
            "dataset_version": dataset_version(b0_cases, LABEL_VERSIONS["b0"]),
            "verify": b0_stats,
        },
        "badcase": {
            "cases": len(badcase_cases),
            "sha256": shas["badcase"],
            "dataset_version": dataset_version(badcase_cases, LABEL_VERSIONS["badcase"]),
            "verify": badcase_stats,
        },
    }


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="构建 P0 评测数据集（B0 + Bad Case）")
    parser.add_argument("--b0", default="fixtures/acceptance/questions.json", help="B0 题目 JSON")
    parser.add_argument(
        "--badcase",
        default="docs/evidence/LOCAL-R1-20261101/S1-DEV/questions.json",
        help="Bad Case 题目 JSON",
    )
    parser.add_argument("--out", default="fixtures/evaluation", help="输出目录")
    parser.add_argument("--verbose", action="store_true", help="逐题打印解析到的 unit_key（证据用）")
    args = parser.parse_args(list(argv) if argv is not None else None)
    root = ROOT
    b0_path = (root / args.b0).resolve()
    badcase_path = (root / args.badcase).resolve()
    out_dir = (root / args.out).resolve()
    try:
        for path, label in ((b0_path, "B0"), (badcase_path, "BadCase")):
            if not path.is_file():
                raise BuildError(f"{label} 题目文件不存在: {path}")
        stats = build_dataset(root, b0_path, badcase_path, out_dir)
    except (BuildError, GoldUnresolved) as exc:
        print(f"BUILD FAILED: {exc}", file=sys.stderr)
        return 1
    for suite in ("b0", "badcase"):
        payload = stats[suite]
        verify = payload["verify"]
        print(
            f"{suite}: cases={payload['cases']} resolved={verify['resolved']} "
            f"no_gold={verify['no_gold']} skipped_requires_ocr={verify['skipped_requires_ocr']} "
            f"units={verify['units']} sha256={payload['sha256']} dataset_version={payload['dataset_version']}"
        )
        if args.verbose:
            for line in verify["detail"]:
                print(f"  {line}")
    print(f"wrote {out_dir / 'b0.jsonl'} and {out_dir / 'badcase.jsonl'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

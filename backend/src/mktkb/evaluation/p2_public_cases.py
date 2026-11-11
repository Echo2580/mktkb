"""P2-T207-FIX-A F3：公开矩阵 N/C 的只读转换器 + 三次 run 的 case 文件。

规则（固定、可审、逐字段来自冻结题集）：

- 输入只有 fixtures/acceptance/questions.json；不复制题干到新夹具、不改原文件；
- 只转换 negative（N01-N08）与 ambiguity_conflict（C01-C06）；U 组另走 U01 镜像；
- case_id = 题集 id；suite = negative/boundary（与 p2_scoring 的冻结分母同名）；
  stratum = category 或 group；business_date 固定 2026-10-28（与 fixtures/evaluation/b0.jsonl 同日）；
- expected_kind = scenario.expected_kind（缺就报错：U07-U09 这类没有 expected_kind 的题不得转）；
- expected_values 只对 answer/conflict 全量保留（CaseSpec 的 value_hit 是"全含"）；对
  not_found/clarification 验收口径是"任一可接受措辞"，CaseSpec 表达不了，故置空并把可接受
  措辞写进 notes 的 accepted_wording(any-of,not-scored)。**如实记录（T207-FIX-A-R1 更正）**：
  这几行因此比验收口径**更松**而不是更严 —— 只判 expected_kind；clarification（C01–C04）的
  任一措辞没有任何自动断言，not_found 也只判拒答。这是口径缺口、不能读成产品通过；
  不改冻结判据（scorers/p2_scoring），是否在评分器里表达 any-of 交 T209 决定；
- not_found 用 should_refuse=true 表达（p2_scoring 会把 not_found 当拒答；若写 false 会被
  refusal_unexpected 判失败，那是口径错误而不是产品失败）；
- expected_sources：file -> doc_code，record -> record_code（只作记录：match_source_ref 只比
  doc_code/unit_key/locator），locator 只保留严格键，自由文本 heading 丢弃并写进 notes
  （验收侧 b0.LOCATOR_SKIPPED_KEYS 同样跳过 heading）；
- forbidden_sources：scenario.forbidden_sources 的 file 列表 -> doc_code；
- requires_ocr 一律 false（N/C 全为非 OCR 题）；reference_answer 留空（题集没有，不编造）。

U01 的 CaseSpec 是 backend/tests/acceptance/test_t09_mutation.py U01 断言的**镜像**（不改该测试）：
question/expected_values/expected_sources/expected_kind 全来自同一份冻结题集条目，因此与
test_u01_new_version_not_published_keeps_old_answer 的期望一致；但它只是**执行证据行**，
不得冒充真实模型能力（报告里标 R/L）。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from .dataset import CaseSpec, cases_to_jsonl, validate_case, write_cases
from .p2_scoring import P2_B0_IDS, P2_BOUNDARY_IDS, P2_NEGATIVE_IDS

PROJECT_ROOT = Path(__file__).resolve().parents[4]
ACCEPTANCE_QUESTIONS_PATH = PROJECT_ROOT / "fixtures" / "acceptance" / "questions.json"
B0_DATASET_PATH = PROJECT_ROOT / "fixtures" / "evaluation" / "b0.jsonl"
CASES_DIR = PROJECT_ROOT / "docs" / "reports" / "OBS-EVAL" / "P2" / "T207" / "cases"

PUBLIC_CASE_GROUPS = ("negative", "ambiguity_conflict")
SUITE_BY_GROUP: Mapping[str, str] = {
    "negative": "negative",
    "ambiguity_conflict": "boundary",
}
BUSINESS_DATE = "2026-10-28"
LABELER = "acceptance-fixture"
#: locator 里可严格比较的键（与验收侧 b0.LOCATOR_STRICT_KEYS 同口径）。
STRICT_LOCATOR_KEYS = ("kind", "sheet", "row", "page", "paragraph", "table", "column")
FREE_TEXT_LOCATOR_KEYS = ("heading",)
#: 结局语义不同：这些 kind 的可接受措辞是"任一"，CaseSpec 的 value_hit 是"全含"。
ANY_OF_KINDS = frozenset({"not_found", "clarification"})


class PublicCaseError(ValueError):
    """转换失败（题集结构/映射规则不符）：稳定 code + 只含 id/字段名。"""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = str(code)
        self.detail = str(detail)


def _questions_document(path: Path | str | None = None) -> tuple[Mapping[str, Any], str]:
    target = Path(path) if path is not None else ACCEPTANCE_QUESTIONS_PATH
    raw = target.read_bytes()
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, Mapping):
        raise PublicCaseError("questions_not_object", target.name)
    questions = payload.get("questions")
    if not isinstance(questions, Sequence) or isinstance(questions, (str, bytes)):
        raise PublicCaseError("questions_missing", target.name)
    return payload, hashlib.sha256(raw).hexdigest()


def acceptance_label_version(path: Path | str | None = None) -> str:
    """label_version = acceptance-<题集 version>-<题集 sha 前 12 位>（可追溯，不猜）。"""
    payload, sha = _questions_document(path)
    return f"acceptance-{str(payload.get('version') or 'unknown')}-{sha[:12]}"


def _strict_locator(locator: Any) -> dict[str, Any]:
    if not isinstance(locator, Mapping):
        return {}
    return {key: locator[key] for key in STRICT_LOCATOR_KEYS if key in locator}


def _source_refs(raw: Any, *, name: str) -> tuple[dict[str, Any], ...]:
    if raw is None:
        return ()
    if isinstance(raw, (str, bytes)) or not isinstance(raw, Sequence):
        raise PublicCaseError("source_refs_invalid", name)
    refs: list[dict[str, Any]] = []
    for index, item in enumerate(raw):
        if not isinstance(item, Mapping):
            raise PublicCaseError("source_ref_invalid", f"{name}[{index}]")
        file_id = str(item.get("file") or "").strip()
        if not file_id:
            raise PublicCaseError("source_ref_file_missing", f"{name}[{index}]")
        ref: dict[str, Any] = {"doc_code": file_id}
        record = str(item.get("record") or "").strip()
        if record:
            ref["record_code"] = record
        locator = _strict_locator(item.get("locator"))
        if locator:
            ref["locator"] = locator
        refs.append(ref)
    return tuple(refs)


def _forbidden_sources(raw: Any, *, name: str) -> tuple[dict[str, Any], ...]:
    if raw is None:
        return ()
    if isinstance(raw, (str, bytes)) or not isinstance(raw, Sequence):
        raise PublicCaseError("forbidden_sources_invalid", name)
    refs: list[dict[str, Any]] = []
    for item in raw:
        file_id = str(item or "").strip()
        if not file_id:
            raise PublicCaseError("forbidden_source_empty", name)
        refs.append({"doc_code": file_id})
    return tuple(refs)


def _note_fragments(item: Mapping[str, Any]) -> list[str]:
    scenario = item.get("scenario") or {}
    notes = [
        f"source=fixtures/acceptance/questions.json id={item.get('id')}",
        f"group={item.get('group')}",
        f"category={item.get('category')}",
    ]
    reason = str(scenario.get("reason") or "").strip()
    if reason:
        notes.append(f"reason={reason}")
    candidates = scenario.get("candidates")
    if isinstance(candidates, Sequence) and not isinstance(candidates, (str, bytes)) and candidates:
        notes.append("candidates=" + "|".join(str(value) for value in candidates))
    accepted = item.get("expected_values") or ()
    if str(scenario.get("expected_kind") or "") in ANY_OF_KINDS and accepted:
        notes.append("accepted_wording(any-of,not-scored)=" + "|".join(str(v) for v in accepted))
    dropped = [
        key
        for ref in item.get("expected_sources") or ()
        if isinstance(ref, Mapping) and isinstance(ref.get("locator"), Mapping)
        for key in FREE_TEXT_LOCATOR_KEYS
        if key in ref["locator"]
    ]
    if dropped:
        notes.append("dropped_free_text_locator=" + "|".join(sorted(set(dropped))))
    actions = scenario.get("actions") or ()
    if actions:
        ops = "|".join(str(action.get("op")) for action in actions if isinstance(action, Mapping))
        notes.append(f"scenario_actions={ops}")
    return notes


def acceptance_case(item: Mapping[str, Any], *, label_version: str) -> CaseSpec:
    """把一条冻结验收题转成 CaseSpec（映射规则见模块头；任何结构不符都抛错）。"""
    if not isinstance(item, Mapping):
        raise PublicCaseError("item_not_object", type(item).__name__)
    case_id = str(item.get("id") or "").strip()
    if not case_id:
        raise PublicCaseError("case_id_missing", "")
    group = str(item.get("group") or "").strip()
    if group not in PUBLIC_CASE_GROUPS:
        raise PublicCaseError("group_not_convertible", f"{case_id}:{group}")
    question = item.get("question")
    if not isinstance(question, str) or not question.strip():
        raise PublicCaseError("question_missing", case_id)
    scenario = item.get("scenario")
    if not isinstance(scenario, Mapping):
        raise PublicCaseError("scenario_missing", case_id)
    expected_kind = str(scenario.get("expected_kind") or "").strip()
    if not expected_kind:
        raise PublicCaseError("expected_kind_missing", case_id)
    accepted = item.get("expected_values") or ()
    if isinstance(accepted, (str, bytes)) or not isinstance(accepted, Sequence):
        raise PublicCaseError("expected_values_invalid", case_id)
    values = (
        ()
        if expected_kind in ANY_OF_KINDS
        else tuple(str(value) for value in accepted)
    )
    should_refuse = expected_kind == "not_found"
    refusal_reason = None
    if should_refuse:
        refusal_reason = str(scenario.get("reason") or "").strip() or "not_found"
    case = CaseSpec(
        case_id=case_id,
        suite=SUITE_BY_GROUP[group],
        split="dev",
        stratum=str(item.get("category") or group),
        business_date=BUSINESS_DATE,
        question=question,
        turns=(),
        expected_kind=expected_kind,
        expected_values=values,
        expected_sources=_source_refs(item.get("expected_sources"), name=f"{case_id}.expected_sources"),
        relevant_units=(),
        reference_answer="",
        should_refuse=should_refuse,
        refusal_reason=refusal_reason,
        forbidden_values=tuple(str(value) for value in (scenario.get("forbidden_values") or ())),
        forbidden_sources=_forbidden_sources(
            scenario.get("forbidden_sources"), name=f"{case_id}.forbidden_sources"
        ),
        expected_pagination=None,
        requires_ocr=False,
        labeler=LABELER,
        label_version=label_version,
        notes="; ".join(_note_fragments(item)),
    )
    validate_case(case)
    return case


def load_acceptance_cases(
    path: Path | str | None = None,
    *,
    ids: Sequence[str] = tuple(P2_NEGATIVE_IDS) + tuple(P2_BOUNDARY_IDS),
) -> tuple[CaseSpec, ...]:
    """按 id 顺序转换（默认 N01-N08 + C01-C06）；缺题/多题都报错，不静默补。"""
    payload, _sha = _questions_document(path)
    label_version = acceptance_label_version(path)
    by_id: dict[str, Mapping[str, Any]] = {}
    for item in payload["questions"]:
        if isinstance(item, Mapping) and str(item.get("id") or ""):
            by_id[str(item["id"])] = item
    missing = [case_id for case_id in ids if case_id not in by_id]
    if missing:
        raise PublicCaseError("case_missing", ",".join(missing))
    return tuple(acceptance_case(by_id[case_id], label_version=label_version) for case_id in ids)


def u01_case(path: Path | str | None = None) -> CaseSpec:
    """U01 的 CaseSpec：镜像 test_t09_mutation.py 的 U01 断言（执行证据行，不是能力结论）。"""
    payload, _sha = _questions_document(path)
    label_version = acceptance_label_version(path)
    item = next(
        (row for row in payload["questions"] if isinstance(row, Mapping) and row.get("id") == "U01"),
        None,
    )
    if item is None:
        raise PublicCaseError("case_missing", "U01")
    scenario = item.get("scenario") or {}
    case = acceptance_case_for_mutation(item, scenario, label_version=label_version)
    return case


def acceptance_case_for_mutation(
    item: Mapping[str, Any], scenario: Mapping[str, Any], *, label_version: str
) -> CaseSpec:
    """mutation 组只有 U01 能落成可评分 CaseSpec（U02-U10 见 test_t09_mutation.py）。"""
    case_id = str(item.get("id") or "").strip()
    if case_id != "U01":
        raise PublicCaseError("mutation_case_not_convertible", case_id)
    expected_kind = str(scenario.get("expected_kind") or "").strip()
    if expected_kind != "answer":
        raise PublicCaseError("expected_kind_not_supported", f"{case_id}:{expected_kind}")
    case = CaseSpec(
        case_id=case_id,
        suite="update_delete",
        split="dev",
        stratum=str(item.get("category") or "mutation"),
        business_date=BUSINESS_DATE,
        question=str(item.get("question") or ""),
        turns=(),
        expected_kind=expected_kind,
        expected_values=tuple(str(value) for value in (item.get("expected_values") or ())),
        expected_sources=_source_refs(item.get("expected_sources"), name=f"{case_id}.expected_sources"),
        relevant_units=(),
        reference_answer="",
        should_refuse=False,
        refusal_reason=None,
        forbidden_values=(),
        forbidden_sources=(),
        expected_pagination=None,
        requires_ocr=False,
        labeler=LABELER,
        label_version=label_version,
        notes="; ".join(
            _note_fragments(item)
            + ["mirror=backend/tests/acceptance/test_t09_mutation.py::test_u01"]
        ),
    )
    validate_case(case)
    return case


def load_b0_cases(path: Path | str | None = None) -> tuple[CaseSpec, ...]:
    """只读 B0 冻结题集（40 题），顺序按文件；不改写字节。"""
    target = Path(path) if path is not None else B0_DATASET_PATH
    cases: list[CaseSpec] = []
    for line in target.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        case = CaseSpec.from_dict(json.loads(line))
        validate_case(case)
        cases.append(case)
    ids = tuple(case.case_id for case in cases)
    if ids != tuple(P2_B0_IDS):
        raise PublicCaseError("b0_ids_mismatch", ",".join(ids[:5]))
    return tuple(cases)


def run_case_sets(
    path: Path | str | None = None,
) -> dict[str, tuple[CaseSpec, ...]]:
    """三次 run 的题集（与 PM 决定 R1/R2/R3 拆分逐项一致）。

    R1 = B0 40 + N01-N08 + C01-C04（52 回合）；R2 = U01 + C05（2）；R3 = C06（1）。
    Q01 只在 R1；R2/R3 不含 Q01（不重复付费）。
    """
    nc = {case.case_id: case for case in load_acceptance_cases(path)}
    b0 = load_b0_cases()
    u01 = u01_case(path)
    r1 = b0 + tuple(nc[f"N{index:02d}"] for index in range(1, 9)) + tuple(
        nc[f"C{index:02d}"] for index in range(1, 5)
    )
    r2 = (u01, nc["C05"])
    r3 = (nc["C06"],)
    return {"R1": r1, "R2": r2, "R3": r3}


def write_run_case_files(
    dest_dir: Path | str | None = None, *, path: Path | str | None = None
) -> dict[str, dict[str, Any]]:
    """写出 R1/R2/R3 case JSONL（规范字节），返回逐文件 sha256 与计数。"""
    target_dir = Path(dest_dir) if dest_dir is not None else CASES_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    summary: dict[str, dict[str, Any]] = {}
    for name, cases in run_case_sets(path).items():
        target = target_dir / f"{name}.jsonl"
        sha = write_cases(target, cases)
        summary[name] = {
            "path": str(target),
            "sha256": sha,
            "cases": len(cases),
            "case_ids": [case.case_id for case in cases],
            "turns": sum(max(1, len(case.turns)) for case in cases),
        }
    return summary


def _main(argv: Sequence[str] | None = None) -> int:  # pragma: no cover - 由 runbook 调用
    import argparse

    parser = argparse.ArgumentParser(description="生成 P2-T207 的 R1/R2/R3 case 文件（只读转换）")
    parser.add_argument("--out", default=str(CASES_DIR), help="输出目录（默认 docs/reports/OBS-EVAL/P2/T207/cases）")
    args = parser.parse_args(list(argv) if argv is not None else None)
    summary = write_run_case_files(args.out)
    print(json.dumps({name: {k: v for k, v in item.items() if k != "case_ids"} for name, item in summary.items()},
                     ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())

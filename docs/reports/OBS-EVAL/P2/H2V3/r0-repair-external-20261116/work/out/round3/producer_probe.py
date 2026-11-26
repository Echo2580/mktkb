"""只读探针：每题「最终答案文本由谁产生」+ 期望值在三层的到达情况。

只输出白名单：case_id、固定码（path/mode/kind/status/purpose）、整数、布尔。
绝不输出题面、答案、实体、来源正文或私有路径。
用法：python producer_probe.py <binding> <evidence-root> <receipt> <seal-manifest> <case-plan>
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import sys
from collections import Counter
from typing import Any, Mapping, Sequence

WORK = pathlib.Path(__file__).resolve().parent
SAFE = WORK.parent.parent / "r0_safe_project.py"


def _load(name: str, path: pathlib.Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("module_not_loadable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


P = _load("r0_safe_for_probe", SAFE)


def _events(envelope: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return [
        event
        for event in ((envelope.get("capture") or {}).get("events") or [])
        if isinstance(event, Mapping)
    ]


def _payloads(events: Sequence[Mapping[str, Any]], kind: str) -> list[Mapping[str, Any]]:
    return [event.get("payload") or {} for event in events if str(event.get("kind")) == kind]


def _text_of(payload: Mapping[str, Any]) -> str:
    value = payload.get("text")
    return value if isinstance(value, str) else ""


def _model_candidates(text: str) -> list[str]:
    """模型原文 + 若为 JSON 则取 answer 字段（rag live 路径的形态）。"""
    out = [text.strip()] if text.strip() else []
    try:
        parsed = json.loads(text)
    except (ValueError, TypeError):
        parsed = None
    if isinstance(parsed, Mapping):
        answer = parsed.get("answer")
        if isinstance(answer, str) and answer.strip():
            out.append(answer.strip())
    return out


def main(argv: list[str]) -> int:
    binding_path, evidence_root, receipt_path, seal_path, case_plan_path = (pathlib.Path(p) for p in argv[:5])
    key = pathlib.Path(argv[5]).read_bytes().strip() if len(argv) > 5 else b""

    guard = P.NetGuard()
    guard.install()
    guard.positive_control()

    binding = json.loads(binding_path.read_text(encoding="utf-8"))
    run_entry = binding["runs"][0]
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    seal_manifest = json.loads(seal_path.read_text(encoding="utf-8"))
    case_plan = json.loads(case_plan_path.read_text(encoding="utf-8"))
    del receipt, seal_manifest  # 只用于文件可读性自检，本探针不重算封印

    entry = P._load_module("p2_h2_v3_probe_entry", P.TOOLS / "p2_h2_v3_controlled_execute.py")
    from mktkb.evaluation.p2_evidence_io import read_encrypted_evidence
    import mktkb.evaluation.p2_runner as runner
    import mktkb.evaluation.p2_scoring as scoring
    from mktkb.evaluation.scorers import check_value

    inputs = {name: {"path": record["path"]} for name, record in binding["inputs"].items()}
    bundle = entry.load_v3_bundle(inputs)
    scenario = str(run_entry.get("scenario_id"))
    cases = tuple(bundle.contract.subset(scenario).cases)
    static_bindings = {
        str(name): value
        for name, value in dict(run_entry.get("evidence_bindings") or {}).items()
        if str(name) != "index_revision"
    }
    plan = entry.v2._validate_case_plan_document(case_plan, cases=cases, static_bindings=static_bindings)
    document_codes = runner.holdout_document_codes(bundle.contract._ingest)  # noqa: SLF001
    diag: dict[str, int] = Counter()

    _rows, envelopes_by_case = P._build_rows(
        cases,
        plan["cases"],
        evidence_root,
        key,
        plan["bindings"],
        document_codes,
        read_encrypted_evidence,
        scoring._lookup_document_code,  # noqa: SLF001
        diag,
    )

    print("netguard=%s" % json.dumps(guard.as_dict(), sort_keys=True))
    print("diag_text_answer_commit_mismatch=%d" % int(diag["text_answer_commit_mismatch"]))
    for case in cases:
        case_id = str(case.case_id)
        envelopes = envelopes_by_case.get(case_id) or []
        paths: set[str] = set()
        modes: set[str] = set()
        mi = Counter()
        mo = Counter()
        mo_status = Counter()
        answer_source: set[str] = set()
        fact_count = 0
        answer_kind = set()
        commit_kind = set()
        a_eq_c: list[bool] = []
        model_hit_commit: list[bool] = []
        expected = tuple(getattr(case, "expected_values", ()) or ())
        in_commit = 0
        in_model = 0
        in_evidence = 0
        in_commit_loose = 0
        in_projection = 0
        in_cited = 0
        in_facts = 0
        for envelope in envelopes:
            events = _events(envelope)
            for payload in _payloads(events, "plan_observed"):
                paths.add(str(payload.get("path")))
                modes.add(str(payload.get("mode")))
            for payload in _payloads(events, "model_input"):
                mi[str(payload.get("purpose"))] += 1
            for payload in _payloads(events, "model_output"):
                mo[str(payload.get("purpose"))] += 1
                mo_status[str(payload.get("status"))] += 1
            rag_rows = _payloads(events, "direct_rag_answer")
            for payload in rag_rows:
                answer_source.add(str(payload.get("answer_source")))
                fact_count = max(fact_count, int(payload.get("fact_count") or 0))
            answers = _payloads(events, "answer_result")
            commits = _payloads(events, "commit_observed")
            answer_text = _text_of(answers[0]) if answers else ""
            commit_text = _text_of(commits[0]) if commits else ""
            if answers:
                answer_kind.add(str(answers[0].get("kind")))
            if commits:
                commit_kind.add(str(commits[0].get("kind")))
            if answers and commits:
                a_eq_c.append(answer_text == commit_text)
            model_texts = [
                _text_of(payload)
                for payload in _payloads(events, "model_output")
                if str(payload.get("purpose")) == "answer" and str(payload.get("status")) == "ok"
            ]
            candidates = [item for text in model_texts for item in _model_candidates(text)]
            model_hit_commit.append(bool(candidates) and commit_text.strip() in candidates)
            # 期望值四层到达（只在进程内比对，只输出计数）
            evidence_text = "\n".join(
                str(item.get("text") or "")
                for payload in _payloads(events, "model_input")
                for item in (payload.get("evidence") or ())
                if isinstance(item, Mapping)
            )
            units = [
                unit
                for unit in ((envelope.get("db_projection") or {}).get("units") or [])
                if isinstance(unit, Mapping)
            ]

            def _unit_text(unit: Mapping[str, Any]) -> str:
                return "\n".join(
                    [
                        str(unit.get("text") or ""),
                        json.dumps(unit.get("raw_fields") or {}, ensure_ascii=False),
                        json.dumps(unit.get("date_fields") or {}, ensure_ascii=False),
                    ]
                )

            cited_ids: set[str] = set()
            for payload in commits:
                cited_ids |= {str(item) for item in (payload.get("source_ids") or ())}
            for payload in rag_rows:
                cited_ids |= {str(item) for item in (payload.get("cited_unit_ids") or ())}
            fact_values = [
                str(fact.get("value") or "")
                for payload in rag_rows
                for fact in (payload.get("facts") or ())
                if isinstance(fact, Mapping)
            ]
            for value in expected:
                if check_value(commit_text, value, cross_explicit_space=True):
                    in_commit += 1
                if check_value(commit_text, value):
                    in_commit_loose += 1
                if any(check_value(candidate, value, cross_explicit_space=True) for candidate in candidates):
                    in_model += 1
                if evidence_text and check_value(evidence_text, value, cross_explicit_space=True):
                    in_evidence += 1
                if any(check_value(_unit_text(unit), value, cross_explicit_space=True) for unit in units):
                    in_projection += 1
                if any(
                    check_value(_unit_text(unit), value, cross_explicit_space=True)
                    for unit in units
                    if str(unit.get("unit_id")) in cited_ids
                ):
                    in_cited += 1
                if any(check_value(item, value, cross_explicit_space=True) for item in fact_values):
                    in_facts += 1
        print(
            " ".join(
                [
                    case_id,
                    "path=%s" % (sorted(paths) or ["none"]),
                    "mode=%s" % (sorted(modes) or ["none"]),
                    "answer_source=%s" % (sorted(answer_source) or ["none"]),
                    "facts=%d" % fact_count,
                    "answer_kind=%s" % (sorted(answer_kind) or ["none"]),
                    "commit_kind=%s" % (sorted(commit_kind) or ["none"]),
                    "mi=%s" % (dict(mi) or {}),
                    "mo=%s" % (dict(mo) or {}),
                    "mo_status=%s" % (dict(mo_status) or {}),
                    "answer_eq_commit=%s" % (all(a_eq_c) if a_eq_c else None),
                    "model_text_is_commit=%s" % (model_hit_commit or None),
                    "expected=%d" % len(expected),
                    "exp_in_commit=%d" % in_commit,
                    "exp_in_commit_loose=%d" % in_commit_loose,
                    "exp_in_model=%d" % in_model,
                    "exp_in_prompt_evidence=%d" % in_evidence,
                    "exp_in_db_units=%d" % in_projection,
                    "exp_in_cited_units=%d" % in_cited,
                    "exp_in_rag_facts=%d" % in_facts,
                ]
            )
        )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except Exception:  # noqa: BLE001 - 只输出固定码
        print(json.dumps({"ok": False, "error": "probe_failed"}, sort_keys=True))
        raise SystemExit(2)

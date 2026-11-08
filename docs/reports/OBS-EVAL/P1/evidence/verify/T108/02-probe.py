"""T108 独立验收探针（合成夹具；不读取真实 holdout labels）。

覆盖：
A. 默认聚合 run：产物仅 manifest+summary、无 cases.jsonl、无题干/答案/case_id/trace 泄漏。
B. gate --run 对聚合 run 可用（exit 3、hard_failures=[]、无 traceback）。
C. details + audit：逐题落盘 + holdout_audit.json，审计不含题干/答案。
D. CI 三变量带 details 硬失败（非零、无产物）；聚合 run 在 CI 下仍可跑。
E. fail-closed 矩阵：缺 labels / 缺或错 label_version / 行数 / 分层 / case_id 集合 /
   questions+labels sha / 题目带答案字段。
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend" / "src"))

from mktkb.evaluation import cli  # noqa: E402
from mktkb.evaluation.dataset import (  # noqa: E402
    HoldoutError,
    HoldoutPolicy,
    load_holdout_dataset,
)
from mktkb.evaluation.runner import run_suite  # noqa: E402

SYNTH_LABEL = "holdout-synthetic-verify"
SYNTH_STRATA = {"paraphrase": 2, "negative": 1}
SYNTH_CASE_COUNT = 3
Q_MARKER = "验收合成题干-唯一标记"
A_MARKER = "验收合成答案-唯一标记"
CASE_IDS = ("V01", "V02", "V03")
CORPUS = ROOT / "corpus" / "enterprise-20261101"


def q_row(case_id, **overrides):
    row = {
        "case_id": case_id,
        "suite": "holdout",
        "split": "holdout",
        "stratum": "paraphrase",
        "business_date": "2026-10-28",
        "question": "合成题干",
        "turns": [],
        "expected_kind": "answer",
        "should_refuse": False,
        "requires_ocr": False,
        "labeler": "holdout-author",
        "label_version": SYNTH_LABEL,
        "notes": "T108 验收合成夹具",
    }
    row.update(overrides)
    return row


def l_row(case_id, **overrides):
    row = {
        "case_id": case_id,
        "expected_kind": "answer",
        "expected_values": [A_MARKER],
        "expected_sources": [{"doc_code": "E11", "unit_key": "sheet:物品位置:row:7"}],
        "relevant_units": [{"doc_code": "E11", "unit_key": "sheet:物品位置:row:7"}],
        "reference_answer": f"合成答案：{A_MARKER}",
        "should_refuse": False,
        "refusal_reason": None,
        "forbidden_values": [],
        "forbidden_sources": [],
        "notes": "合成出处",
    }
    row.update(overrides)
    return row


def questions():
    return [
        q_row("V01", question=f"{Q_MARKER}：物品位置？"),
        q_row("V02", question="另一个问题", turns=["追问一", "追问二"]),
        q_row(
            "V03",
            stratum="negative",
            question="负样本合成题干",
            expected_kind="refusal",
            should_refuse=True,
        ),
    ]


def labels():
    return [
        l_row("V01"),
        l_row("V02"),
        l_row(
            "V03",
            expected_kind="refusal",
            expected_values=[],
            expected_sources=[],
            relevant_units=[],
            reference_answer="合成拒答",
            should_refuse=True,
            refusal_reason="合成拒答原因",
        ),
    ]


def write_jsonl(path: Path, rows) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows).encode("utf-8")
    )
    return path


def policy(**overrides):
    base = {
        "case_count": SYNTH_CASE_COUNT,
        "strata": dict(SYNTH_STRATA),
        "questions_sha256": None,
        "labels_sha256": None,
        "label_version": SYNTH_LABEL,
    }
    base.update(overrides)
    return HoldoutPolicy(**base)


def make_corpus(tmp: Path) -> Path:
    corpus_dir = tmp / "corpus"
    (corpus_dir / "excel").mkdir(parents=True)
    src = CORPUS / "excel" / "E11_终端物料位置表_当前V2.xlsx"
    dst = corpus_dir / "excel" / src.name
    shutil.copy2(src, dst)
    manifest = {
        "business_base_date": "2026-10-28",
        "files": [
            {
                "code": "E11",
                "group": "excel",
                "path": f"excel/{src.name}",
                "kind": "xlsx",
                "sha256": hashlib.sha256(dst.read_bytes()).hexdigest(),
            }
        ],
    }
    (corpus_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )
    return corpus_dir


def run(tmp: Path, name: str, **kwargs):
    q, lab = write_jsonl(tmp / name / "questions.jsonl", questions()), write_jsonl(
        tmp / name / "labels.jsonl", labels()
    )
    out = tmp / name / "run"
    res = run_suite(
        "holdout",
        "local",
        corpus_dir=make_corpus(tmp / name),
        dataset_path=q,
        out_dir=out,
        holdout_labels=lab,
        holdout_policy=policy(),
        **kwargs,
    )
    return res, q, lab


def artifact_text(out_dir: Path) -> str:
    parts = []
    for p in sorted(out_dir.rglob("*")):
        if p.is_file():
            parts.append(p.name)
            parts.append(p.read_bytes().decode("utf-8", errors="ignore"))
    return "\n".join(parts)


def keys_in(obj, acc):
    if isinstance(obj, dict):
        for k, v in obj.items():
            acc.add(str(k))
            keys_in(v, acc)
    elif isinstance(obj, list):
        for v in obj:
            keys_in(v, acc)


def leak_flags(out_dir: Path, label_rows) -> dict:
    blob = artifact_text(out_dir)
    answer_texts = []
    for row in label_rows:
        answer_texts.append(row["reference_answer"])
        answer_texts.extend(str(v) for v in row["expected_values"])
    return {
        "files": sorted(p.name for p in out_dir.iterdir()),
        "cases_jsonl": (out_dir / "cases.jsonl").exists(),
        "trace_db": (out_dir / "traces.sqlite3").exists(),
        "question_marker": Q_MARKER in blob,
        "answer_marker": A_MARKER in blob,
        "answer_text_hits": sum(1 for t in answer_texts if t and t in blob),
        "case_id_hits": sum(1 for c in CASE_IDS if c in blob),
    }


def main() -> int:
    os.environ.pop("CI", None)
    os.environ.pop("GITHUB_ACTIONS", None)
    os.environ.pop("MKTKB_CI", None)
    os.environ.pop("MKTKB_HOLDOUT_LABELS", None)
    with tempfile.TemporaryDirectory(prefix="t108-verify-") as td:
        tmp = Path(td)
        print("tmp:", tmp)

        # A. default aggregate
        res, q, lab = run(tmp, "agg")
        print("A files:", sorted(p.name for p in res.out_dir.iterdir()))
        print("A leak:", json.dumps(leak_flags(res.out_dir, labels()), ensure_ascii=False))
        print("A manifest.holdout_details:", res.manifest.holdout_details)
        print("A summary.holdout.aggregate_only:", res.summary["holdout"]["aggregate_only"])

        # B. gate on aggregate
        env_bak = {k: os.environ.get(k) for k in ("CI", "GITHUB_ACTIONS", "MKTKB_CI")}
        for k in env_bak:
            os.environ.pop(k, None)
        out, err = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = cli.main(["gate", "--run", str(res.out_dir)])
        finally:
            pass
        gate = json.loads((res.out_dir / "gate.json").read_text(encoding="utf-8"))
        print("B gate cli exit:", code, "hard:", gate["hard_failures"],
              "unknowns:", [u["check_id"] for u in gate["unknowns"]])
        print("B stdout has hard_failures=[]:", "hard_failures=[]" in out.getvalue(),
              "traceback:", "Traceback" in err.getvalue())

        # C. details + audit
        res2, _, _ = run(tmp, "det", allow_holdout_details=True, holdout_operator="verify-op")
        audit = json.loads((res2.out_dir / "holdout_audit.json").read_text(encoding="utf-8"))
        audit_keys = set()
        keys_in(audit, audit_keys)
        audit_text = json.dumps(audit, ensure_ascii=False)
        print("C files:", sorted(p.name for p in res2.out_dir.iterdir()))
        print("C audit fields:", sorted(audit_keys))
        print("C audit leak:", {
            "question": Q_MARKER in audit_text,
            "answer": A_MARKER in audit_text,
            "ref_answer": any(r["reference_answer"] in audit_text for r in labels()),
        })
        print("C audit sha/version:",
              audit["data"]["questions_sha256"][:8],
              audit["data"]["labels_sha256"][:8],
              audit["data"]["label_version"],
              "operator:", audit["operator"], "run_id_eq:",
              audit["run_id"] == res2.manifest.run_id,
              "created_eq:", audit["created_at"] == res2.manifest.created_at)
        print("C cases rows:", len([x for x in (res2.out_dir / "cases.jsonl").read_text(encoding="utf-8").split("\n") if x.strip()]))

        # gate on details: dev + CI
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code_dev = cli.main(["gate", "--run", str(res2.out_dir)])
        gate_dev = json.loads((res2.out_dir / "gate.json").read_text(encoding="utf-8"))
        os.environ["GITHUB_ACTIONS"] = "1"
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code_ci = cli.main(["gate", "--run", str(res2.out_dir)])
        finally:
            os.environ.pop("GITHUB_ACTIONS", None)
        gate_ci = json.loads((res2.out_dir / "gate.json").read_text(encoding="utf-8"))
        print("D gate details dev:", code_dev, [u["check_id"] for u in gate_dev["unknowns"]])
        print("D gate details ci:", code_ci, [u["check_id"] for u in gate_ci["unknowns"]],
              "names_var:", "GITHUB_ACTIONS" in gate_ci["unknowns"][0]["reason"])

        # E. CI hard failure with details: each var + combo
        for name in ("CI", "GITHUB_ACTIONS", "MKTKB_CI"):
            q5, lab5 = write_jsonl(tmp / f"ci-{name}" / "q.jsonl", questions()), write_jsonl(
                tmp / f"ci-{name}" / "l.jsonl", labels()
            )
            os.environ[name] = "1"
            try:
                try:
                    run_suite(
                        "holdout", "local", corpus_dir=make_corpus(tmp / f"ci-{name}"),
                        dataset_path=q5, out_dir=tmp / f"ci-{name}" / "run",
                        holdout_labels=lab5, holdout_policy=policy(),
                        allow_holdout_details=True,
                    )
                    rejected, msg = False, ""
                except HoldoutError as exc:
                    rejected, msg = True, str(exc)
            finally:
                os.environ.pop(name, None)
            print(f"E CI {name}: rejected={rejected} names_var={name in msg} "
                  f"out_exists={(tmp / f'ci-{name}' / 'run' / 'cases.jsonl').exists()}")

        # aggregate allowed in CI
        os.environ["CI"] = "true"
        try:
            res3, _, _ = run(tmp, "ci-agg")
            print("E CI aggregate exit ok:", res3.manifest.holdout_details is False)
        finally:
            os.environ.pop("CI", None)

        # F. fail-closed matrix
        base_q, base_l = write_jsonl(tmp / "fc" / "q.jsonl", questions()), write_jsonl(
            tmp / "fc" / "l.jsonl", labels()
        )

        def expect(name, fn, match):
            try:
                fn()
                print(f"F {name}: NOT-REJECTED")
            except (HoldoutError, ValueError) as exc:
                print(f"F {name}: rejected={match in str(exc)} ({type(exc).__name__})")

        # missing labels via run_suite
        expect(
            "missing_labels",
            lambda: run_suite(
                "holdout", "local", corpus_dir=make_corpus(tmp / "fc"),
                dataset_path=base_q, out_dir=tmp / "fc" / "run",
                holdout_policy=policy(), environ={},
            ),
            "缺少 labels",
        )
        # missing label_version (empty)
        q_bad = questions(); q_bad[0]["label_version"] = ""
        qp = write_jsonl(tmp / "fc" / "q_nover.jsonl", q_bad)
        expect("empty_label_version", lambda: load_holdout_dataset(qp, base_l, policy=policy()), "label_version")
        # wrong label_version
        q_bad2 = questions(); q_bad2[0]["label_version"] = "wrong-version"
        qp2 = write_jsonl(tmp / "fc" / "q_wrongver.jsonl", q_bad2)
        expect("wrong_label_version", lambda: load_holdout_dataset(qp2, base_l, policy=policy()), "label_version")
        # row count mismatch
        expect("row_count", lambda: load_holdout_dataset(base_q, base_l, policy=policy(case_count=30)), "行数")
        # strata mismatch
        expect("strata", lambda: load_holdout_dataset(base_q, base_l, policy=policy(strata={"paraphrase": 3})), "分层不符")
        # case_id set mismatch
        bad_labels = labels(); bad_labels[-1] = l_row("V99", expected_kind="refusal",
                                                     expected_values=[], expected_sources=[],
                                                     relevant_units=[], reference_answer="x",
                                                     should_refuse=True, refusal_reason="x")
        lp = write_jsonl(tmp / "fc" / "l_ids.jsonl", bad_labels)
        expect("case_id_set", lambda: load_holdout_dataset(base_q, lp, policy=policy()), "case_id 集合不相等")
        # sha mismatches
        expect("questions_sha", lambda: load_holdout_dataset(base_q, base_l, policy=policy(questions_sha256="0" * 64)), "questions sha256 不符")
        expect("labels_sha", lambda: load_holdout_dataset(base_q, base_l, policy=policy(labels_sha256="0" * 64)), "labels sha256 不符")
        # answer field in questions
        q_ans = questions(); q_ans[0]["expected_values"] = [A_MARKER]
        qap = write_jsonl(tmp / "fc" / "q_ans.jsonl", q_ans)
        expect("answer_field", lambda: load_holdout_dataset(qap, base_l, policy=policy()), "答案字段")

        # CLI missing labels exit code (no env, no flag)
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(["run", "--suite", "holdout", "--mode", "local",
                             "--out", str(tmp / "cli-nolabels")])
        print("G cli missing labels exit:", code,
              "stderr_has_msg:", "holdout 缺少 labels" in err.getvalue(),
              "traceback:", "Traceback" in err.getvalue(),
              "out_exists:", (tmp / "cli-nolabels").exists())

        # CLI details under CI: no labels read needed (fails before load)
        for name in ("CI", "GITHUB_ACTIONS", "MKTKB_CI"):
            os.environ[name] = "1"
            out, err = io.StringIO(), io.StringIO()
            try:
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    code = cli.main(["run", "--suite", "holdout", "--mode", "local",
                                     "--allow-holdout-details",
                                     "--out", str(tmp / f"cli-ci-{name}")])
            finally:
                os.environ.pop(name, None)
            print(f"G cli details {name}: exit={code} msg={'CI/门禁环境禁止' in err.getvalue()} "
                  f"traceback={'Traceback' in err.getvalue()} out_exists={(tmp / f'cli-ci-{name}').exists()}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

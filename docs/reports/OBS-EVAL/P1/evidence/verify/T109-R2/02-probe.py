"""T109 R2 独立验收探针（非交付物；只读交付 run/代码，合成用例写 .pytest-tmp）。

用法（仓库根，零真实调用）：
  .venv\\Scripts\\python.exe -B docs\\reports\\OBS-EVAL\\P1\\evidence\\verify\\T109-R2\\02-probe.py

前置（本目录 03 记录命令）：
  eval/regression-current、regression-replay（源=当前）、regression-parent-replay
  （源=父提交 ebfe956）、regression-short-src、regression-short-replay、
  b0-current、b0-replay、badcase-current，父提交 run 在
  backend/.pytest-tmp/T109-verify/base（detached worktree ebfe956）。
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[7]
TMP = ROOT / "backend" / ".pytest-tmp" / "T109-R2"
EVAL = TMP / "eval"
BASE = ROOT / "backend" / ".pytest-tmp" / "T109-verify" / "base"
PEVAL = BASE / "backend" / ".pytest-tmp" / "T109-verify" / "eval"
P0 = ROOT / "var" / "eval" / "runs"
sys.path.insert(0, str(ROOT / "backend" / "src"))

from mktkb.evaluation import runner as runner_mod  # noqa: E402
from mktkb.evaluation.dataset import CaseSpec, cases_to_jsonl, load_cases  # noqa: E402
from mktkb.evaluation.runner import run_suite  # noqa: E402
from mktkb.observability.store import TraceRepository  # noqa: E402
from mktkb.rag.index import RagIndex  # noqa: E402
from mktkb.rag.types import RagAnswer  # noqa: E402

FAILS: list[str] = []


def report(name: str, ok: bool, detail: str = "") -> None:
    print(f"| {name} | {'PASS' if ok else 'FAIL'} | {detail} |")
    if not ok:
        FAILS.append(name)


def rows(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def by_id(path: Path) -> dict[str, dict]:
    return {row["case_id"]: row for row in rows(path)}


def clean(value, drop: set[str]):
    if isinstance(value, dict):
        return {k: clean(v, drop) for k, v in value.items() if k not in drop}
    if isinstance(value, list):
        return [clean(v, drop) for v in value]
    return value


def sig(row: dict):
    return (
        row.get("status"),
        (row.get("outcome") or {}).get("kind"),
        tuple((item.get("check_id"), item.get("status")) for item in row.get("checks") or ()),
        (row.get("error") or {}).get("code"),
    )


def err(row: dict) -> dict:
    return row.get("error") or {}


def main() -> int:
    print("# T109 R2 独立探针结果")
    print()
    print("零真实模型/embedding/rerank/OCR 调用；合成语料仅 E11；父提交 run 为 ebfe956 产物。")
    print()

    # ------------------------------------------------------------------
    # A. B1：父提交单轮 run + 当前 replay -> 多轮 case fail closed
    # ------------------------------------------------------------------
    old_src = by_id(PEVAL / "regression-parent/cases.jsonl")
    old_rep = by_id(EVAL / "regression-parent-replay/cases.jsonl")
    base_dataset = BASE / "fixtures" / "evaluation" / "regression.jsonl"
    parent_man = json.loads((PEVAL / "regression-parent/run_manifest.json").read_text(encoding="utf-8"))
    print("## A. B1 replay fail-closed（源=父提交单轮 run，行无 turn_traces）")
    print()
    print("| 检查 | 结果 | 证据 |")
    print("| --- | --- | --- |")
    report(
        "源 run 为父提交 ebfe956 的 local 产物，RG002/RG003/RG006 无 turn_traces",
        parent_man["mode"] == "local"
        and parent_man["dataset_sha256"] == hashlib.sha256(base_dataset.read_bytes()).hexdigest()
        and all("turn_traces" not in old_src[cid] and old_src[cid]["turns_executed"] == 1 for cid in ("RG002", "RG003", "RG006")),
        f"run={parent_man['run_id']}",
    )
    b1_ok = True
    b1_detail = {}
    for cid in ("RG002", "RG003", "RG006"):
        row = old_rep[cid]
        item = {
            "status": row["status"],
            "code": err(row).get("code"),
            "turns": row["turns_executed"],
            "traces": len(row["turn_traces"]),
            "claimed": row["multi_turn_claimed"],
        }
        b1_detail[cid] = item
        b1_ok &= (
            item["status"] == "fail"
            and item["code"] == "multi_turn_source_missing"
            and "2 轮" in err(row).get("message", "")
            and item["turns"] == 0
            and item["traces"] == 0
            and item["claimed"] is True
        )
    report(
        "三行 status=fail / multi_turn_source_missing / turn_traces=[] / turns_executed=0",
        b1_ok,
        json.dumps(b1_detail, ensure_ascii=False),
    )
    report(
        "无 status=pass 或单条 turn_trace 冒充多轮",
        all(old_rep[cid]["status"] != "pass" and len(old_rep[cid]["turn_traces"]) != 1 for cid in ("RG002", "RG003", "RG006")),
        "3 rows",
    )
    repo = TraceRepository(EVAL / "regression-parent-replay/traces.sqlite3")
    provenance_ok = True
    prov_detail = []
    for cid in ("RG002", "RG003", "RG006"):
        rec, spans = repo.get(old_rep[cid]["trace_id"])
        provenance_ok &= (
            rec.case_id == cid
            and rec.mode == "replay"
            and rec.replayed is True
            and len(spans) == 0
            and rec.http_request_id.endswith(":provenance")
        )
        prov_detail.append(f"{cid}:spans={len(spans)}:turn_traces={len(old_rep[cid]['turn_traces'])}")
    repo.close()
    report(
        "fail-closed 行仅保留 case 级 provenance trace（不入 turn_traces，spans=0）",
        provenance_ok,
        ";".join(prov_detail),
    )
    replay_summary = json.loads((EVAL / "regression-parent-replay/summary.json").read_text(encoding="utf-8"))
    declarations = replay_summary["declarations"]["execution"]
    report(
        "声明层不把 fail-closed 多轮当已验证（verified=False/轮数 0/error ids 3）",
        declarations["multi_turn_verified"] is False
        and declarations["multi_turn_turns_executed"] == 0
        and declarations["multi_turn_error_case_ids"] == ["RG002", "RG003", "RG006"],
        f"verified={declarations['multi_turn_verified']} turns={declarations['multi_turn_turns_executed']}",
    )
    report(
        "fail-closed replay 不 crash：gate hard=[]（exit 3）",
        json.loads((EVAL / "regression-parent-replay/gate.json").read_text(encoding="utf-8"))["hard_failures"] == [],
        "hard=[]",
    )
    same_single = all(
        old_rep[cid]["status"] == old_src[cid]["status"]
        and old_rep[cid]["turns_executed"] == 1
        and len(old_rep[cid]["turn_traces"]) == 1
        for cid in ("RG001", "RG004", "RG005", "RG007")
    )
    report("同源单轮行沿用父口径（1 轮/1 条 replay/status 不变）", same_single, "RG001/RG004/RG005/RG007")

    # ------------------------------------------------------------------
    # B. B1：源多轮但轮数不足 -> multi_turn_source_incomplete
    # ------------------------------------------------------------------
    short_src = by_id(EVAL / "regression-short-src/cases.jsonl")
    short_rep = by_id(EVAL / "regression-short-replay/cases.jsonl")
    print()
    print("## B. B1 源多轮但轮数不足（RG002 turn_traces 截为 1 条）")
    print()
    print("| 检查 | 结果 | 证据 |")
    print("| --- | --- | --- |")
    r2 = short_rep["RG002"]
    report(
        "RG002 fail / multi_turn_source_incomplete / 轮数 0 / 无 turn_trace",
        len(short_src["RG002"]["turn_traces"]) == 1
        and r2["status"] == "fail"
        and err(r2).get("code") == "multi_turn_source_incomplete"
        and "1 条" in err(r2).get("message", "")
        and "2" in err(r2).get("message", "")
        and r2["turns_executed"] == 0
        and r2["turn_traces"] == [],
        f"{r2['status']}/{err(r2).get('code')}/turns={r2['turns_executed']}/traces={len(r2['turn_traces'])}",
    )
    report(
        "同源其余多轮行仍逐轮 replay（RG003/RG006 各 2 条）",
        short_rep["RG003"]["status"] == "pass"
        and short_rep["RG003"]["turns_executed"] == 2
        and len(short_rep["RG003"]["turn_traces"]) == 2
        and short_rep["RG006"]["status"] == "pass"
        and short_rep["RG006"]["turns_executed"] == 2
        and len(short_rep["RG006"]["turn_traces"]) == 2,
        "RG003/RG006",
    )

    # ------------------------------------------------------------------
    # C. 合法多轮源仍逐轮 replay + R3 逐轮题面
    # ------------------------------------------------------------------
    cur = by_id(EVAL / "regression-current/cases.jsonl")
    rep = by_id(EVAL / "regression-replay/cases.jsonl")
    cases = {case.case_id: case for case in load_cases(ROOT / "fixtures/evaluation/regression.jsonl")}
    print()
    print("## C. 合法多轮源 replay（当前 local -> 当前 replay）+ R3 逐轮题面")
    print()
    print("| 检查 | 结果 | 证据 |")
    print("| --- | --- | --- |")
    local_repo = TraceRepository(EVAL / "regression-current/traces.sqlite3")
    replay_repo = TraceRepository(EVAL / "regression-replay/traces.sqlite3")
    per_turn_ok = True
    q_ok = True
    for cid in ("RG002", "RG003", "RG006"):
        src = cur[cid]
        dst = rep[cid]
        per_turn_ok &= dst["status"] == src["status"] and dst["turns_executed"] == 2
        per_turn_ok &= [t["turn"] for t in dst["turn_traces"]] == [1, 2]
        per_turn_ok &= {t["trace_id"] for t in dst["turn_traces"]}.isdisjoint(
            {t["trace_id"] for t in src["turn_traces"]}
        )
        texts = [str(t.get("text") or t.get("question")) for t in cases[cid].turns]
        for i, item in enumerate(dst["turn_traces"]):
            rec, spans = replay_repo.get(item["trace_id"])
            per_turn_ok &= rec.replayed is True and rec.mode == "replay" and len(spans) == 0
            per_turn_ok &= rec.previous_trace_id == src["turn_traces"][i]["trace_id"]
            per_turn_ok &= rec.outcome_kind == (None if i == 0 else src["outcome"]["kind"])
            local_rec, local_spans = local_repo.get(src["turn_traces"][i]["trace_id"])
            q_ok &= rec.question_hash == hashlib.sha256(texts[i].encode()).hexdigest()
            q_ok &= rec.question_hash == local_rec.question_hash
            q_ok &= len(local_spans) > 0
        q_ok &= (
            hashlib.sha256(texts[0].encode()).hexdigest()
            != hashlib.sha256(texts[1].encode()).hexdigest()
        )
    local_repo.close()
    replay_repo.close()
    report(
        "RG002/RG003/RG006 replay 逐轮 2 条、链源轮、无源 trace 复用、仅末轮 outcome",
        per_turn_ok,
        "3 cases x 2 turns",
    )
    report(
        "R3：replay 每轮 question_hash = 该轮题面 = local 对应轮（两轮不同）",
        q_ok,
        "sha256(turn.text)",
    )
    drop_replay = {"trace_id", "duration_ms", "latency_ms", "replayed", "previous_trace_id", "turn_traces"}
    replay_diffs = {
        cid: [
            key
            for key in cur[cid]
            if key not in drop_replay
            and clean(cur[cid].get(key), {"trace_id"}) != clean(rep[cid].get(key), {"trace_id"})
        ]
        for cid in cur
    }
    replay_diffs = {k: v for k, v in replay_diffs.items() if v}
    report("replay vs local 7 cases 实质字段一致（去 volatile）", not replay_diffs, f"diffs={replay_diffs}")

    # ------------------------------------------------------------------
    # D. R1：轮级 error 明细（合成）
    # ------------------------------------------------------------------
    synth = TMP / "probe-synth"
    if synth.exists():
        shutil.rmtree(synth)
    corpus = synth / "corpus"
    (corpus / "excel").mkdir(parents=True)
    src_xlsx = ROOT / "corpus/enterprise-20261101/excel/E11_终端物料位置表_当前V2.xlsx"
    dst_xlsx = corpus / "excel" / src_xlsx.name
    shutil.copy2(src_xlsx, dst_xlsx)
    (corpus / "manifest.json").write_text(
        json.dumps(
            {
                "business_base_date": "2026-10-28",
                "files": [
                    {
                        "code": "E11",
                        "group": "excel",
                        "path": f"excel/{src_xlsx.name}",
                        "kind": "xlsx",
                        "sha256": hashlib.sha256(dst_xlsx.read_bytes()).hexdigest(),
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    unit = "sheet:物品位置:row:7"
    q1 = "滨江店的宣传海报的数量是多少？"
    q2 = "那个海报呢"
    qerr = "城西区的宣传海报在哪？"

    def case(
        cid: str,
        turns: tuple,
        *,
        question: str = q2,
        kind: str = "answer",
        values=("40",),
        sources=({"doc_code": "E11", "unit_key": unit},),
        forbidden=("店内外侧", "QF01"),
    ) -> CaseSpec:
        return CaseSpec(
            case_id=cid,
            suite="regression",
            split="dev",
            stratum="defect-t105",
            business_date="2026-10-28",
            question=question,
            turns=turns,
            expected_kind=kind,
            expected_values=values,
            expected_sources=sources,
            relevant_units=(),
            reference_answer="40",
            should_refuse=False,
            refusal_reason=None,
            forbidden_values=forbidden,
            forbidden_sources=(),
            expected_pagination=None,
            requires_ocr=False,
            labeler="lead",
            label_version="regression-p1-2026-11-05",
            notes="R2 verify probe",
            source_err_id="ERR-20261104-06",
        )

    def run_one(cid: str, spec: CaseSpec, wrapper=None, read=None):
        dataset = synth / f"{cid}.jsonl"
        dataset.write_bytes(cases_to_jsonl([spec]).encode("utf-8"))
        out = synth / f"out-{cid}"
        calls: list[tuple[str, str | None, str | None]] = []
        scored: list[tuple[str, str, str, bool]] = []
        real_ask = RagIndex.ask
        real_score = runner_mod.score_case
        real_read = runner_mod._read_trace
        reads = {"n": 0}

        def ask(self, question, **kwargs):
            calls.append((question, kwargs.get("conversation_id"), kwargs.get("user_id")))
            if wrapper is not None:
                return wrapper(question, kwargs, real_ask, self)
            return real_ask(self, question, **kwargs)

        def score(c, g, o, r):
            scored.append((c.case_id, o.kind, o.text, r is not None))
            return real_score(c, g, o, r)

        def read_trace(repo, trace_id):
            reads["n"] += 1
            if read is not None:
                return read(reads["n"], repo, trace_id, real_read)
            return real_read(repo, trace_id)

        RagIndex.ask = ask
        runner_mod.score_case = score
        runner_mod._read_trace = read_trace
        try:
            result = run_suite(
                "regression", "local", corpus_dir=corpus, dataset_path=dataset, out_dir=out
            )
        finally:
            RagIndex.ask = real_ask
            runner_mod.score_case = real_score
            runner_mod._read_trace = real_read
        row = rows(out / "cases.jsonl")[0]
        return row, calls, scored, result

    def err_kind(kind: str):
        def wrapper(question, kwargs, real, self):
            if qerr in question:
                return RagAnswer(kind=kind, question=question, text="", state={})
            return real(self, question, **kwargs)

        return wrapper

    def read_none_at(n, repo, trace_id, real):
        return None if n == 1 else real(repo, trace_id)

    def read_error_at(n, repo, trace_id, real):
        return types.SimpleNamespace(status="error") if n == 1 else real(repo, trace_id)

    print()
    print("## D. R1：轮级 error 明细（合成多轮，E11）")
    print()
    print("| 检查 | 结果 | 证据 |")
    print("| --- | --- | --- |")
    c_row, _, c_scored, _ = run_one("C", case("C", ({"role": "user", "text": qerr}, {"role": "user", "text": q1})), err_kind("error"))
    d_row, _, _, _ = run_one("D", case("D", ({"role": "user", "text": qerr}, {"role": "user", "text": q1})), err_kind("service_error"))
    report(
        "中间轮 kind=error/service_error -> fail + error{answer_error, turn 1/2} + 实际 2 轮",
        c_row["status"] == d_row["status"] == "fail"
        and err(c_row) == {"code": "answer_error", "message": "turn 1/2: 答案结局 kind=error（要求无 error）"}
        and err(d_row) == {"code": "answer_error", "message": "turn 1/2: 答案结局 kind=service_error（要求无 error）"}
        and c_row["turns_executed"] == d_row["turns_executed"] == 2
        and [t["status"] for t in c_row["turn_traces"]] == ["error", "ok"]
        and all(x["status"] != "fail" for x in c_row["checks"])
        and len(c_scored) == 1,
        f"error={err(c_row)}; turns={c_row['turns_executed']}; scored={len(c_scored)}",
    )
    e_row, _, _, _ = run_one("E", case("E", ({"role": "user", "text": q1}, {"role": "user", "text": q2})), read=read_none_at)
    report(
        "中间轮 Trace 不可读 -> fail + error{trace_missing, turn 1/2} + 2 轮",
        e_row["status"] == "fail"
        and err(e_row) == {"code": "trace_missing", "message": "turn 1/2: Trace 不可读（trace store 无该轮记录）"}
        and e_row["turns_executed"] == 2
        and [t["status"] for t in e_row["turn_traces"]] == ["error", "ok"],
        f"error={err(e_row)}",
    )
    f_row, _, _, _ = run_one("F", case("F", ({"role": "user", "text": q1}, {"role": "user", "text": q2})), read=read_error_at)
    report(
        "中间轮 Trace status=error -> fail + error{trace_error, turn 1/2}",
        f_row["status"] == "fail"
        and err(f_row) == {"code": "trace_error", "message": "turn 1/2: Trace status=error（要求 Trace 完整）"}
        and f_row["turns_executed"] == 2,
        f"error={err(f_row)}",
    )
    def last_error(question, kwargs, real, self):
        if q1 in question:
            return RagAnswer(kind="error", question=question, text="", state={})
        return real(self, question, **kwargs)

    h_row, _, _, _ = run_one("H2", case("H2", ({"role": "user", "text": q2}, {"role": "user", "text": q1})), last_error)
    report(
        "末轮 kind=error -> fail + error{answer_error, turn 2/2}",
        h_row["status"] == "fail"
        and err(h_row) == {"code": "answer_error", "message": "turn 2/2: 答案结局 kind=error（要求无 error）"}
        and h_row["turns_executed"] == 2
        and [t["status"] for t in h_row["turn_traces"]] == ["ok", "error"],
        f"error={err(h_row)}",
    )

    # ------------------------------------------------------------------
    # E. R2：malformed / gold-error 多轮行的 turns_executed
    # ------------------------------------------------------------------
    print()
    print("## E. R2：首轮前失败的多轮行（turns_executed 非默认 1）")
    print()
    print("| 检查 | 结果 | 证据 |")
    print("| --- | --- | --- |")
    blank_row, _, _, _ = run_one("M1", case("M1", ({"role": "user", "text": q1}, {"role": "user", "text": " "})))
    role_row, _, _, _ = run_one("M2", case("M2", ({"role": "user", "text": q1}, {"role": "assistant", "text": "好的"})))
    gold_row, _, _, _ = run_one(
        "M3",
        case("M3", ({"role": "user", "text": q1}, {"role": "user", "text": q2}),
             sources=({"doc_code": "E11", "unit_key": "sheet:物品位置:row:9999"},)),
    )
    single_gold_row, _, _, _ = run_one(
        "M4",
        case("M4", (), sources=({"doc_code": "E11", "unit_key": "sheet:物品位置:row:9999"},)),
    )
    report(
        "malformed 多轮（空题/非 user 轮）-> turns_executed=0、turn_traces=[]",
        blank_row["status"] == role_row["status"] == "error"
        and err(blank_row)["code"] == "turn_question_missing"
        and err(role_row)["code"] == "turn_role_unsupported"
        and blank_row["turns_executed"] == role_row["turns_executed"] == 0
        and blank_row["turn_traces"] == role_row["turn_traces"] == []
        and blank_row["multi_turn_claimed"] is True
        and role_row["multi_turn_claimed"] is True,
        f"blank={err(blank_row)['code']}/0; role={err(role_row)['code']}/0",
    )
    from mktkb.evaluation.runner import _CaseError, _case_turn_questions  # noqa: PLC0415

    try:
        _case_turn_questions(case("M5", ("不是对象", {"role": "user", "text": q2})))
        direct_code = None
    except _CaseError as exc:
        direct_code = exc.code
    report(
        "非 mapping 轮在 runner 层仍 fail closed（turn_invalid）",
        direct_code == "turn_invalid",
        f"code={direct_code}",
    )
    report(
        "gold 解析失败的多轮行 -> error(gold_unresolved)/turns_executed=0/turn_traces=[]",
        gold_row["status"] == "error"
        and err(gold_row)["code"] == "gold_unresolved"
        and gold_row["turns_executed"] == 0
        and gold_row["turn_traces"] == []
        and gold_row["multi_turn_claimed"] is True,
        f"{gold_row['status']}/{err(gold_row)['code']}/turns={gold_row['turns_executed']}",
    )
    report(
        "单轮 gold error 保持父口径（turns_executed=1、1 条 error trace）",
        single_gold_row["status"] == "error"
        and err(single_gold_row)["code"] == "gold_unresolved"
        and single_gold_row["turns_executed"] == 1
        and len(single_gold_row["turn_traces"]) == 1
        and single_gold_row["multi_turn_claimed"] is False,
        f"turns={single_gold_row['turns_executed']} traces={len(single_gold_row['turn_traces'])}",
    )

    # ------------------------------------------------------------------
    # F. 上轮 PASS 抽查：local 多轮语义 + b0/badcase/regression 形式
    # ------------------------------------------------------------------
    a_row, a_calls, a_scored, _ = run_one("A", case("A", ({"role": "user", "text": q1}, {"role": "user", "text": q2})))
    b_row, _, _, _ = run_one("B", case("B", (), question=q2, kind="clarification", values=(), sources=(), forbidden=()))
    g_row, _, g_scored, _ = run_one("G", case("G", ({"role": "user", "text": qerr}, {"role": "user", "text": q1})))
    same_conv = len(a_calls) == 2 and a_calls[0][1] == a_calls[1][1] and a_calls[0][2] == a_calls[1][2] == "eval"
    order = [c[0] for c in a_calls] == [q1, q2]
    print()
    print("## F. 上轮 PASS 抽查（local 多轮 + 单轮不变 + RG006）")
    print()
    print("| 检查 | 结果 | 证据 |")
    print("| --- | --- | --- |")
    report(
        "A 顺序执行/同一 conversation+user/末轮只答 40/不含未问字段",
        a_row["status"] == "pass"
        and a_row["turns_executed"] == 2
        and [t["status"] for t in a_row["turn_traces"]] == ["ok", "ok"]
        and same_conv
        and order
        and "40" in a_row["outcome"]["text"]
        and "店内外侧" not in a_row["outcome"]["text"],
        f"conv={a_calls[0][1] if a_calls else None}; statuses={[t['status'] for t in a_row['turn_traces']]}",
    )
    report(
        "A 只对末轮 score_case 一次（中间轮不判分）",
        len(a_scored) == 1 and a_scored[0][1] == "answer" and a_scored[0][2] == a_row["outcome"]["text"] and a_scored[0][3],
        f"scored={len(a_scored)}",
    )
    report(
        "B 对照：无上文单轮「那个海报呢」= clarification（状态继承成立）",
        b_row["status"] == "pass" and b_row["outcome"]["kind"] == "clarification" and b_row["turns_executed"] == 1,
        f"kind={b_row['outcome']['kind']}",
    )
    report(
        "G 中间轮 checks 若判分会 fail，但 case 仍 pass（中间轮不参与通过）",
        g_row["status"] == "pass" and g_row["outcome"]["kind"] == "answer" and "40" in g_row["outcome"]["text"] and len(g_scored) == 1,
        "pass; score once",
    )

    # 单轮 b0/badcase：对父提交严格 + 对 P0 签名
    def compare_single(suite: str, count: int) -> tuple[bool, str]:
        c = by_id(EVAL / f"{suite}-current/cases.jsonl")
        p = by_id(PEVAL / f"{suite}-parent/cases.jsonl")
        p0 = by_id(P0 / f"p0-{suite}/cases.jsonl")
        drop = {"trace_id", "duration_ms", "latency_ms"}
        strict = {
            cid: [
                key
                for key in p[cid]
                if key not in drop
                and clean(c[cid].get(key), {"trace_id"}) != clean(p[cid].get(key), {"trace_id"})
            ]
            for cid in c
        }
        strict = {k: v for k, v in strict.items() if v}
        extra = {cid: [key for key in c[cid] if key not in p[cid]] for cid in c}
        extra = {k: v for k, v in extra.items() if v}
        sig0 = [cid for cid in c if sig(c[cid]) != sig(p0[cid])]
        fields_ok = all(
            row["turns_executed"] == 1
            and row["multi_turn_claimed"] is False
            and len(row["turn_traces"]) == 1
            for row in c.values()
        )
        gate_ok = (
            json.loads((EVAL / f"{suite}-current/gate.json").read_text(encoding="utf-8"))["hard_failures"] == []
            and json.loads((P0 / f"p0-{suite}/gate.json").read_text(encoding="utf-8"))["hard_failures"] == []
        )
        ok = len(c) == len(p) == len(p0) == count and not strict and not sig0 and fields_ok and gate_ok
        ok = ok and all(v == ["turn_traces"] for v in extra.values())
        return ok, f"strict={len(strict)}; sig0={len(sig0)}; extra={set(map(tuple, extra.values()))}; gate={gate_ok}"

    for suite, count in (("b0", 40), ("badcase", 13)):
        ok, detail = compare_single(suite, count)
        report(f"{suite} 对父提交 strict 0（仅多 turn_traces）/ 对 P0 case_diffs=0", ok, detail)

    # b0 单轮 replay：当前 vs 父提交 replay + P0 replay 签名
    br = by_id(EVAL / "b0-replay/cases.jsonl")
    b0par = by_id(PEVAL / "b0-parent-replay/cases.jsonl")
    b0r = by_id(P0 / "p0-b0-replay/cases.jsonl")
    drop_br = {"trace_id", "duration_ms", "latency_ms", "replayed", "previous_trace_id", "turn_traces"}
    br_diffs = {
        cid: [
            key
            for key in b0par[cid]
            if key not in drop_br
            and clean(br[cid].get(key), {"trace_id"}) != clean(b0par[cid].get(key), {"trace_id"})
        ]
        for cid in b0par
    }
    br_diffs = {k: v for k, v in br_diffs.items() if v}
    br_sig = [cid for cid in br if sig(br[cid]) != sig(b0r[cid])]
    report(
        "单轮 b0 replay 对父提交 40 行实质一致 / 对 P0 replay 签名 0 / 1 轮 1 trace",
        not br_diffs
        and not br_sig
        and all(
            row["turns_executed"] == 1
            and row["multi_turn_claimed"] is False
            and len(row["turn_traces"]) == 1
            for row in br.values()
        ),
        f"vs_parent={len(br_diffs)}; vs_P0_sig={len(br_sig)}",
    )

    # regression 当前 vs 父提交 + RG006
    c_reg = cur
    p_reg = by_id(PEVAL / "regression-parent/cases.jsonl")
    sig_diffs = [cid for cid in c_reg if sig(c_reg[cid]) != sig(p_reg[cid])]
    expected_fields = {
        "RG002": {"turns_executed", "multi_turn_claimed"},
        "RG003": {"turns_executed", "multi_turn_claimed"},
        "RG006": {"turns_executed", "multi_turn_claimed", "checks", "metrics", "outcome"},
    }
    unexpected = {}
    for cid in c_reg:
        drop = {"trace_id", "duration_ms", "latency_ms"}
        diffs = [
            key
            for key in p_reg[cid]
            if key not in drop
            and clean(c_reg[cid].get(key), {"trace_id"}) != clean(p_reg[cid].get(key), {"trace_id"})
        ]
        extra = expected_fields.get(cid, set())
        bad = [key for key in diffs if key not in extra]
        if bad:
            unexpected[cid] = bad
    report("regression case_diffs 仅 RG006；其余逐字段不变", sig_diffs == ["RG006"] and not unexpected, f"diffs={sig_diffs}; unexpected={unexpected}")
    report(
        "RG002/RG003 多轮后仍 pass；RG005/RG007 fail 集不变",
        c_reg["RG002"]["status"] == p_reg["RG002"]["status"] == "pass"
        and c_reg["RG003"]["status"] == p_reg["RG003"]["status"] == "pass"
        and c_reg["RG005"]["status"] == p_reg["RG005"]["status"] == "fail"
        and c_reg["RG007"]["status"] == p_reg["RG007"]["status"] == "fail",
        "RG002/3 pass; RG005/7 fail",
    )
    rg6 = c_reg["RG006"]
    fixture = {row_["case_id"]: row_ for row_ in rows(ROOT / "fixtures/evaluation/regression.jsonl")}["RG006"]
    text = rg6["outcome"]["text"]
    report(
        "RG006 末轮 answer 含 40、不含未问字段；fixture kind=answer/values 含 40/forbidden 保留",
        rg6["status"] == "pass"
        and rg6["outcome"]["kind"] == "answer"
        and "40" in text
        and "店内外侧" not in text
        and "QF01" not in text
        and fixture["expected_kind"] == "answer"
        and any("40" in str(v) for v in fixture["expected_values"])
        and "店内外侧" in fixture["forbidden_values"]
        and "QF01" in fixture["forbidden_values"]
        and "滨江店" not in fixture["forbidden_values"]
        and "滨江店" in str(fixture["turns"][0].get("text")),
        f"text={text!r}; forbidden={fixture['forbidden_values']}",
    )
    report(
        "gate 当前/父提交均 hard=[]（无新 hard）",
        json.loads((EVAL / "regression-current/gate.json").read_text(encoding="utf-8"))["hard_failures"] == []
        and json.loads((PEVAL / "regression-parent/gate.json").read_text(encoding="utf-8"))["hard_failures"] == [],
        "hard=[]",
    )

    print()
    print(f"探针 FAIL 项：{len(FAILS)}")
    for name in FAILS:
        print(f"- {name}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())

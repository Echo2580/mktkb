"""T109 独立验收探针（不是交付物；只读交付 run/代码，合成用例写 .pytest-tmp）。

用法（仓库根，零真实调用）：
  .venv\\Scripts\\python.exe -B docs\\reports\\OBS-EVAL\\P1\\evidence\\verify\\T109\\02-probe.py

前置 run（review 中给出命令）：
  eval/regression-current、regression-parent、regression-replay、regression-parent-replay
  eval/b0-current、b0-parent、b0-replay、badcase-current、badcase-parent
  base = backend/.pytest-tmp/T109-verify/base（父提交 ebfe956 worktree，已复制 gitignored subset-policy）
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[7]
TMP = ROOT / "backend" / ".pytest-tmp" / "T109-verify"
BASE = TMP / "base"
EVAL = TMP / "eval"
PEVAL = BASE / "backend" / ".pytest-tmp" / "T109-verify" / "eval"
sys.path.insert(0, str(ROOT / "backend" / "src"))

from mktkb.evaluation import runner as runner_mod  # noqa: E402
from mktkb.evaluation.dataset import CaseSpec, cases_to_jsonl  # noqa: E402
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


def main() -> int:
    print("# T109 独立探针结果")
    print()
    print("合成语料：corpus/enterprise-20261101/excel/E11（仅此一份）；零真实 provider 调用。")
    print()

    # ------------------------------------------------------------------
    # A. regression local：当前 vs 父提交
    # ------------------------------------------------------------------
    cur = by_id(EVAL / "regression-current/cases.jsonl")
    par = by_id(PEVAL / "regression-parent/cases.jsonl")
    cman = json.loads((EVAL / "regression-current/run_manifest.json").read_text(encoding="utf-8"))
    pman = json.loads((PEVAL / "regression-parent/run_manifest.json").read_text(encoding="utf-8"))
    print("## A. regression local（当前 703b7e0 vs 父提交 ebfe956）")
    print()
    print("| 检查 | 结果 | 证据 |")
    print("| --- | --- | --- |")
    report(
        "manifest 语料可比 (index_revision=49, corpus hash 相同)",
        cman["index_revision"] == pman["index_revision"] == 49
        and cman["corpus_manifest_sha256"] == pman["corpus_manifest_sha256"],
        f"revision={cman['index_revision']}; corpus={cman['corpus_manifest_sha256'][:12]}",
    )
    report(
        "当前 manifest 多轮标记 3 cases / 6 turns",
        cman.get("multi_turn_case_count") == 3 and cman.get("multi_turn_turns_executed") == 6,
        f"{cman.get('multi_turn_case_count')}/{cman.get('multi_turn_turns_executed')}",
    )
    report(
        "父提交 manifest 无多轮字段（旧产物）",
        "multi_turn_case_count" not in pman and "multi_turn_turns_executed" not in pman,
        "keys absent",
    )
    report(
        "行集合 7 个且 key 顺序 = 父键 + turn_traces",
        list(cur) == list(par) and all(list(cur[k]) == list(par[k]) + ["turn_traces"] for k in cur),
        "turn_traces 尾插",
    )
    sig_diffs = [cid for cid in cur if sig(cur[cid]) != sig(par[cid])]
    report("case_diffs 仅 RG006", sig_diffs == ["RG006"], f"diffs={sig_diffs}")
    substantive = {}
    for cid in cur:
        drop = {"trace_id", "duration_ms", "latency_ms"}
        diffs = [
            k
            for k in par[cid]
            if k not in drop and clean(cur[cid].get(k), {"trace_id"}) != clean(par[cid].get(k), {"trace_id"})
        ]
        # RG002/003 多轮执行后 turns_executed/multi_turn_claimed 应变化；RG006 全部按 PM 裁决。
        expected = {"RG002": {"turns_executed", "multi_turn_claimed"}, "RG003": {"turns_executed", "multi_turn_claimed"}, "RG006": {"turns_executed", "multi_turn_claimed", "checks", "metrics", "outcome"}}.get(cid, set())
        unexpected = [k for k in diffs if k not in expected]
        if unexpected:
            substantive[cid] = unexpected
    report(
        "除 RG006 与多轮字段外，逐字段一致（去 volatile）",
        not substantive,
        f"unexpected={substantive}",
    )
    report(
        "RG002/RG003 多轮后仍 pass 且 outcome 不变",
        cur["RG002"]["status"] == par["RG002"]["status"] == "pass"
        and cur["RG002"]["outcome"]["kind"] == par["RG002"]["outcome"]["kind"] == "clarification"
        and cur["RG003"]["status"] == par["RG003"]["status"] == "pass"
        and cur["RG003"]["outcome"]["kind"] == par["RG003"]["outcome"]["kind"] == "answer",
        "RG002 clarification / RG003 answer",
    )
    report(
        "RG005/RG007 失败集不变（均 fail）",
        cur["RG005"]["status"] == par["RG005"]["status"] == "fail"
        and cur["RG007"]["status"] == par["RG007"]["status"] == "fail",
        "fail/fail",
    )
    rg6 = cur["RG006"]
    fixture = {
        row["case_id"]: row
        for row in rows(ROOT / "fixtures/evaluation/regression.jsonl")
    }["RG006"]
    text = rg6["outcome"]["text"]
    report(
        "RG006 末轮 answer 含 40、不含未问字段",
        rg6["status"] == "pass"
        and rg6["outcome"]["kind"] == "answer"
        and "40" in text
        and "店内外侧" not in text
        and "QF01" not in text,
        f"text={text!r}",
    )
    report(
        "RG006 fixture expected_kind=answer / expected_values 含 40 / 未问字段 forbidden 保留",
        fixture["expected_kind"] == "answer"
        and any("40" in str(v) for v in fixture["expected_values"])
        and "店内外侧" in fixture["forbidden_values"]
        and "QF01" in fixture["forbidden_values"]
        and not any("40" in str(v) for v in fixture["forbidden_values"]),
        f"forbidden={fixture['forbidden_values']}",
    )
    report(
        "RG006 移除滨江店有 turn1 明问依据、未放宽未问字段",
        "滨江店" not in fixture["forbidden_values"]
        and "滨江店" in str(fixture["turns"][0].get("text"))
        and "多轮" in fixture["notes"],
        "滨江店=turn1 被问主体",
    )

    # ------------------------------------------------------------------
    # B. b0 / badcase 对父提交 + P0 冻结基线
    # ------------------------------------------------------------------
    print()
    print("## B. b0 / badcase（对父提交严格行 + 对 P0 签名）")
    print()
    print("| 检查 | 结果 | 证据 |")
    print("| --- | --- | --- |")
    for suite, count in (("b0", 40), ("badcase", 13)):
        c = by_id(EVAL / f"{suite}-current/cases.jsonl")
        p = by_id(PEVAL / f"{suite}-parent/cases.jsonl")
        p0 = by_id(ROOT / f"var/eval/runs/p0-{suite}/cases.jsonl")
        drop = {"trace_id", "duration_ms", "latency_ms"}
        strict = {
            cid: [
                k
                for k in p[cid]
                if k not in drop
                and clean(c[cid].get(k), {"trace_id"}) != clean(p[cid].get(k), {"trace_id"})
            ]
            for cid in c
        }
        strict = {k: v for k, v in strict.items() if v}
        sig0 = [cid for cid in c if sig(c[cid]) != sig(p0[cid])]
        report(
            f"{suite} 行数 {count}、对父提交严格一致、对 P0 case_diffs=0",
            len(c) == len(p) == len(p0) == count and not strict and not sig0,
            f"strict={len(strict)}; sig0={len(sig0)}",
        )
        report(
            f"{suite} 单轮字段 turns_executed=1 / claimed=False / 1 条 turn_trace",
            all(r["turns_executed"] == 1 and r["multi_turn_claimed"] is False and len(r["turn_traces"]) == 1 for r in c.values()),
            "all rows",
        )
        report(
            f"{suite} gate hard=[]（当前与 P0）",
            json.loads((EVAL / f"{suite}-current/gate.json").read_text(encoding="utf-8"))["hard_failures"] == []
            and json.loads((ROOT / f"var/eval/runs/p0-{suite}/gate.json").read_text(encoding="utf-8"))["hard_failures"] == [],
            "hard=[]",
        )

    # ------------------------------------------------------------------
    # C. 多轮 local trace 链与评分
    # ------------------------------------------------------------------
    print()
    print("## C. 多轮 local / replay trace 链")
    print()
    print("| 检查 | 结果 | 证据 |")
    print("| --- | --- | --- |")

    repo = TraceRepository(EVAL / "regression-current/traces.sqlite3")
    chain_ok = True
    q_ok = True
    for cid, texts in (
        ("RG002", ("滨江店的宣传海报在哪里？", "城西区的宣传海报在哪？")),
        ("RG003", ("卓刀河店的马克杯（标识：QF21）放在哪里？", "档期物料要提前多少天提报需求？给出所有内容")),
        ("RG006", ("滨江店的宣传海报的数量是多少？", "那个海报呢")),
    ):
        row = cur[cid]
        prev = None
        for i, item in enumerate(row["turn_traces"], start=1):
            rec, spans = repo.get(item["trace_id"])
            chain_ok &= rec.case_id == cid and len(spans) > 0 and rec.status == "ok"
            chain_ok &= rec.previous_trace_id == prev
            chain_ok &= rec.http_request_id.endswith(f":turn{i}")
            q_ok &= rec.question_hash == hashlib.sha256(texts[i - 1].encode()).hexdigest()
            prev = item["trace_id"]
        chain_ok &= row["trace_id"] == row["turn_traces"][-1]["trace_id"]
        chain_ok &= row["previous_trace_id"] is None
    repo.close()
    report("RG002/RG003/RG006 两轮 trace 存在、链接上一轮、trace_id=末轮", chain_ok, "3 cases x 2 turns")
    report("local 每轮 trace question_hash 对应本轮问题", q_ok, "sha256(text)")

    replay = by_id(EVAL / "regression-replay/cases.jsonl")
    replay_repo = TraceRepository(EVAL / "regression-replay/traces.sqlite3")
    replay_ok = True
    for cid in ("RG002", "RG003", "RG006"):
        src = cur[cid]
        dst = replay[cid]
        replay_ok &= dst["status"] == src["status"]
        replay_ok &= dst["turns_executed"] == src["turns_executed"]
        replay_ok &= [t["turn"] for t in dst["turn_traces"]] == [1, 2]
        replay_ok &= {t["trace_id"] for t in dst["turn_traces"]}.isdisjoint(
            {t["trace_id"] for t in src["turn_traces"]}
        )
        replay_ok &= dst["previous_trace_id"] == src["trace_id"]
        for i, item in enumerate(dst["turn_traces"]):
            rec, spans = replay_repo.get(item["trace_id"])
            replay_ok &= rec.replayed is True and rec.mode == "replay" and len(spans) == 0
            replay_ok &= rec.previous_trace_id == src["turn_traces"][i]["trace_id"]
            replay_ok &= rec.outcome_kind == (None if i == 0 else src["outcome"]["kind"])
    replay_repo.close()
    report("replay 逐轮 trace（2 条/多轮 case、链源轮、仅末轮 outcome）", replay_ok, "3 cases")

    drop_replay = {"trace_id", "duration_ms", "latency_ms", "replayed", "previous_trace_id", "turn_traces"}
    replay_diffs = {
        cid: [
            k
            for k in cur[cid]
            if k not in drop_replay
            and clean(cur[cid].get(k), {"trace_id"}) != clean(replay[cid].get(k), {"trace_id"})
        ]
        for cid in cur
    }
    replay_diffs = {k: v for k, v in replay_diffs.items() if v}
    report("replay vs local 7 cases 实质字段一致（去 volatile）", not replay_diffs, f"diffs={replay_diffs}")

    # 单轮 replay 旧口径：当前 b0 replay vs 父提交 b0 replay（隔离 T109）；并与 P0 签名对照。
    br = by_id(EVAL / "b0-replay/cases.jsonl")
    b0par = by_id(PEVAL / "b0-parent-replay/cases.jsonl")
    b0r = by_id(ROOT / "var/eval/runs/p0-b0-replay/cases.jsonl")
    drop_br = {"trace_id", "duration_ms", "latency_ms", "replayed", "previous_trace_id", "turn_traces"}
    br_diffs = {
        cid: [
            k
            for k in b0par[cid]
            if k not in drop_br
            and clean(br[cid].get(k), {"trace_id"}) != clean(b0par[cid].get(k), {"trace_id"})
        ]
        for cid in b0par
    }
    br_diffs = {k: v for k, v in br_diffs.items() if v}
    br_p0_sig = [cid for cid in br if sig(br[cid]) != sig(b0r[cid])]
    report(
        "单轮 b0 replay 对父提交 40 行实质一致、turns_executed=1/claimed=False",
        not br_diffs
        and all(r["turns_executed"] == 1 and r["multi_turn_claimed"] is False and len(r["turn_traces"]) == 1 for r in br.values())
        and not br_p0_sig,
        f"vs_parent={br_diffs}; vs_P0_sig={br_p0_sig}",
    )

    # 旧产物（父提交）replay：源单轮 run 遇多轮 case
    old_par = by_id(PEVAL / "regression-parent/cases.jsonl")
    old_rep = by_id(EVAL / "regression-parent-replay/cases.jsonl")
    silent = {
        cid: {
            "source_has_turn_traces": "turn_traces" in old_par[cid],
            "replay_turns": old_rep[cid]["turns_executed"],
            "replay_claims_multi": old_rep[cid]["multi_turn_claimed"],
            "replay_trace_count": len(old_rep[cid]["turn_traces"]),
            "replay_error": old_rep[cid]["error"],
        }
        for cid in ("RG002", "RG003", "RG006")
    }
    report(
        "旧源单轮 run 遇多轮 case：明确错误（handoff §3.5/§5）",
        all(v["replay_error"] is not None for v in silent.values()),
        f"实际静默单条 replay: {silent}",
    )

    # ------------------------------------------------------------------
    # D. 合成多轮用例（独立于 dev 测试）
    # ------------------------------------------------------------------
    print()
    print("## D. 合成多轮用例（E11 单文档语料）")
    print()
    print("| 检查 | 结果 | 证据 |")
    print("| --- | --- | --- |")

    synth = TMP / "probe-synth"
    if synth.exists():
        shutil.rmtree(synth)
    corpus = synth / "corpus"
    (corpus / "excel").mkdir(parents=True)
    src = ROOT / "corpus/enterprise-20261101/excel/E11_终端物料位置表_当前V2.xlsx"
    dst = corpus / "excel" / src.name
    shutil.copy2(src, dst)
    (corpus / "manifest.json").write_text(
        json.dumps(
            {
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
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    unit = "sheet:物品位置:row:7"
    q1 = "滨江店的宣传海报的数量是多少？"
    q2 = "那个海报呢"
    qerr = "城西区的宣传海报在哪？"

    def case(cid: str, turns: tuple, *, question: str = q2, kind: str = "answer", values=("40",), sources=({"doc_code": "E11", "unit_key": unit},), forbidden=("店内外侧", "QF01")) -> CaseSpec:
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
            notes="verify probe",
            source_err_id="ERR-20261104-06",
        )

    def run_one(cid: str, c: CaseSpec, wrapper=None, read_none_at: int | None = None):
        dataset = synth / f"{cid}.jsonl"
        dataset.write_bytes(cases_to_jsonl([c]).encode("utf-8"))
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

        def read(repo, trace_id):
            reads["n"] += 1
            if read_none_at is not None and reads["n"] == read_none_at:
                return None
            return real_read(repo, trace_id)

        RagIndex.ask = ask
        runner_mod.score_case = score
        runner_mod._read_trace = read
        try:
            result = run_suite("regression", "local", corpus_dir=corpus, dataset_path=dataset, out_dir=out)
        finally:
            RagIndex.ask = real_ask
            runner_mod.score_case = real_score
            runner_mod._read_trace = real_read
        row = json.loads((out / "cases.jsonl").read_text(encoding="utf-8"))
        return row, calls, scored, result

    def err_kind(kind: str):
        def wrapper(question, kwargs, real, self):
            if qerr in question:
                return RagAnswer(kind=kind, question=question, text="", state={})
            return real(self, question, **kwargs)

        return wrapper

    def err_raise(question, kwargs, real, self):
        if qerr in question:
            raise RuntimeError("probe boom")
        return real(self, question, **kwargs)

    a, calls, scored, _ = run_one("A", case("A", ({"role": "user", "text": q1}, {"role": "user", "text": q2})))
    same_conv = len(calls) == 2 and calls[0][1] == calls[1][1] and calls[0][2] == calls[1][2] == "eval"
    order = [c[0] for c in calls] == [q1, q2]
    report(
        "A 顺序执行/同一 conversation+user/末轮只答 40",
        a["status"] == "pass"
        and a["turns_executed"] == 2
        and [t["status"] for t in a["turn_traces"]] == ["ok", "ok"]
        and same_conv
        and order
        and "40" in a["outcome"]["text"]
        and "店内外侧" not in a["outcome"]["text"],
        f"conv={calls[0][1] if calls else None}; statuses={[t['status'] for t in a['turn_traces']]}",
    )
    report(
        "A 只对末轮 score_case 一次（中间轮不判分）",
        len(scored) == 1 and scored[0][1] == "answer" and scored[0][2] == a["outcome"]["text"] and scored[0][3],
        f"scored={scored}",
    )
    b, _, _, _ = run_one("B", case("B", (), question=q2, kind="clarification", values=(), sources=(), forbidden=()))
    report(
        "B 对照：无上文单轮「那个海报呢」= clarification（证明 A 的答案来自状态继承）",
        b["status"] == "pass" and b["outcome"]["kind"] == "clarification" and b["turns_executed"] == 1,
        f"kind={b['outcome']['kind']}",
    )

    c, _, c_scored, _ = run_one("C", case("C", ({"role": "user", "text": qerr}, {"role": "user", "text": q1})), err_kind("error"))
    d, _, _, _ = run_one("D", case("D", ({"role": "user", "text": qerr}, {"role": "user", "text": q1})), err_kind("service_error"))
    report(
        "C/D 中间轮 kind=error/service_error -> case fail；末轮 checks 仍全通过",
        c["status"] == d["status"] == "fail"
        and [t["status"] for t in c["turn_traces"]] == ["error", "ok"]
        and [t["status"] for t in d["turn_traces"]] == ["error", "ok"]
        and all(x["status"] != "fail" for x in c["checks"])
        and c["error"] is None
        and d["error"] is None
        and len(c_scored) == 1,
        "status=fail, error=None（报告称有 turn n/N 明细，实际无）",
    )
    e, _, _, _ = run_one("E", case("E", ({"role": "user", "text": q1}, {"role": "user", "text": qerr}, {"role": "user", "text": q1})), err_raise)
    report(
        "E 中间轮异常 -> fail、error 含 turn 2/3、只执行到失败轮",
        e["status"] == "fail"
        and e["error"] is not None
        and "turn 2/3" in e["error"]["message"]
        and e["turns_executed"] == 2
        and [t["status"] for t in e["turn_traces"]] == ["ok", "error"],
        f"error={e['error']}",
    )
    f, _, _, _ = run_one("F", case("F", ({"role": "user", "text": q1}, {"role": "user", "text": q2}), values=("99",)))
    report(
        "F 末轮 checks fail -> case fail，轮 trace 均 ok",
        f["status"] == "fail" and f["error"] is None and [t["status"] for t in f["turn_traces"]] == ["ok", "ok"],
        "value_hit fail",
    )
    g, _, _, _ = run_one("G", case("G", ({"role": "user", "text": qerr}, {"role": "user", "text": q1})))
    report(
        "G 中间轮 checks 若判分会 fail，但 case 仍 pass（中间轮不参与通过）",
        g["status"] == "pass" and g["outcome"]["kind"] == "answer" and "40" in g["outcome"]["text"],
        "pass",
    )
    h, _, _, _ = run_one("H", case("H", ({"role": "user", "text": q1}, {"role": "user", "text": qerr})), err_kind("error"))
    report(
        "H 末轮 error 结局 -> case fail",
        h["status"] == "fail" and [t["status"] for t in h["turn_traces"]] == ["ok", "error"],
        "fail",
    )
    i, _, _, _ = run_one("I", case("I", ({"role": "user", "text": q1}, {"role": "user", "text": q2})), read_none_at=1)
    report(
        "I 中间轮 Trace 不可读 -> case fail（turn_traces[0]=error）",
        i["status"] == "fail" and [t["status"] for t in i["turn_traces"]] == ["error", "ok"],
        "fail",
    )

    print()
    print(f"探针 FAIL 项：{len(FAILS)}")
    for name in FAILS:
        print(f"- {name}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())




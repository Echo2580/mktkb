
"""T207-FIX-H2PURGE 独立验收探针（验收助手自写；零真实出站、不读 .env/H1/H2）。

固定路径（账本/预算/GO）全部改指本目录下的 tmp 副本；live env 只用显式 overrides。
"""
from __future__ import annotations

import asyncio
import contextlib
import importlib.util
import io
import json
import os
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
ROOT = next(p for p in HERE.parents if (p / "backend" / "src" / "mktkb").is_dir())
sys.path.insert(0, str(ROOT / "backend" / "src"))
sys.path.insert(0, str(ROOT / "backend" / "tests"))

spec = importlib.util.spec_from_file_location(
    "wt_h2purge", ROOT / "backend" / "tests" / "evaluation" / "test_p2_live_wiring.py"
)
wt = importlib.util.module_from_spec(spec)
sys.modules["wt_h2purge"] = wt
spec.loader.exec_module(wt)

from mktkb.evaluation import cli, p2_dataset, p2_live  # noqa: E402
from mktkb.evaluation import p2_authorization as p2a  # noqa: E402
from mktkb.evaluation import p2_runner  # noqa: E402
from mktkb.evaluation.product_adapter import (  # noqa: E402
    IngestSource,
    MockChatBackend,
    P2IngestPlan,
    P2RunDataset,
    ProductEvalAdapter,
)

TMP = HERE.parent / "_probe-tmp"
if TMP.exists():
    shutil.rmtree(TMP)
TMP.mkdir(parents=True)

plan = wt._plan()
ledger, budget, go = TMP / "live-ledger.jsonl", TMP / "budget.json", TMP / "P2-LIVE-GO.json"
wt._write_ledger(ledger)
wt._write_budget(budget)
wt._write_go(go, ledger=ledger, plan=plan)
p2a.P2_LEDGER_PATH = ledger
p2a.P2_BUDGET_PATH = budget
p2a.P2_GO_PATH = go
os.environ[wt.live_authorization.TOTAL_LIMIT_ENV] = str(wt.TOTAL_LIMIT_CNY)

FINDINGS: list[str] = []
FAILED: list[str] = []


def check(name: str, ok: bool, detail: str) -> None:
    line = f"[{'PASS' if ok else 'FAIL'}] {name}: {detail}"
    print(line)
    FINDINGS.append(line)
    if not ok:
        FAILED.append(name)


class _Stop(Exception):
    pass


_stub_result = __import__("types").SimpleNamespace(
    status="succeeded",
    stop_code=None,
    requests_planned=0,
    requests_sent=0,
    production_ready=False,
    by_center_cny={},
)
_stub_build = __import__("types").SimpleNamespace(
    wiring=__import__("types").SimpleNamespace(receipts=[]),
    adapter=__import__("types").SimpleNamespace(
        paths=__import__("types").SimpleNamespace(run_dir=TMP / "stub-run")
    ),
)


def _fake_holdout_view():
    return wt._holdout_p2_dataset()


# --------------------------------------------------------------------------- #
# A. CLI 层：holdout -> purge=True，public -> purge=False（捕获 run_live_p2 kwargs）
# --------------------------------------------------------------------------- #
orig_run_live = p2_live.run_live_p2
orig_load_dataset = p2_dataset.load_p2_dataset


def _cli_capture(visibility: str):
    captured: list[dict] = []

    async def fake_run(_plan, **kwargs):
        captured.append(kwargs)
        return _stub_result, _stub_build

    p2_live.run_live_p2 = fake_run
    p2_dataset.load_p2_dataset = lambda _path, *, visibility: _fake_holdout_view()
    args = wt._cli_args(TMP, visibility=visibility)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = cli._cmd_p2_run(args)
    p2_live.run_live_p2 = orig_run_live
    p2_dataset.load_p2_dataset = orig_load_dataset
    return code, captured, buf.getvalue().strip().splitlines()[-1]


code_h, cap_h, out_h = _cli_capture("holdout")
check(
    "A1 CLI holdout live -> run_live_p2(purge_traces_on_close=True)",
    code_h == 0 and len(cap_h) == 1 and cap_h[0].get("purge_traces_on_close") is True,
    f"exit={code_h} kwargs={sorted(cap_h[0]) if cap_h else None} purge={cap_h[0].get('purge_traces_on_close') if cap_h else None}",
)
check(
    "A2 CLI holdout dataset.visibility=holdout / payload execution=live",
    cap_h and cap_h[0]["dataset"].visibility == "holdout" and json.loads(out_h).get("execution") == "live",
    f"visibility={cap_h[0]['dataset'].visibility if cap_h else None} payload_ok={json.loads(out_h).get('execution') if out_h else None}",
)
code_p, cap_p, out_p = _cli_capture("public")
check(
    "A3 CLI public live -> run_live_p2(purge_traces_on_close=False)",
    code_p == 0 and len(cap_p) == 1 and cap_p[0].get("purge_traces_on_close") is False,
    f"exit={code_p} purge={cap_p[0].get('purge_traces_on_close') if cap_p else None} visibility={cap_p[0]['dataset'].visibility if cap_p else None}",
)

# --------------------------------------------------------------------------- #
# B. 真实链路：run_live_p2 -> build_live_adapter -> 真正的 ProductEvalAdapter
#    属性 purge_traces_on_close（截停在装配处，start/发送都不发生）
# --------------------------------------------------------------------------- #
orig_build = p2_live.build_live_adapter


def _build_capture():
    seen: list[dict] = []

    def spy(plan_arg, **kwargs):
        built = orig_build(plan_arg, **kwargs)
        seen.append(
            {
                "kw": kwargs.get("purge_traces_on_close", "<absent>"),
                "adapter": built.adapter.purge_traces_on_close,
            }
        )
        raise _Stop

    p2_live.build_live_adapter = spy
    return seen


def _run_live(extra: dict, tag: str):
    seen = _build_capture()
    gate = p2_live.open_live_gate(plan, run_id=f"probe-h2purge-{tag}", now=wt.NOW)
    try:
        asyncio.run(
            p2_live.run_live_p2(
                plan,
                run_id=f"probe-h2purge-{tag}",
                out_dir=TMP / f"run-{tag}",
                dataset=wt._dataset(),
                gate=gate,
                env={"MKTKB_OCR_DISABLED": "0"},
                env_overrides=wt.LIVE_ENV_OVERRIDES,
                now=wt.NOW,
                **extra,
            )
        )
    except _Stop:
        pass
    finally:
        p2_live.build_live_adapter = orig_build
    return seen


seen_true = _run_live({"purge_traces_on_close": True}, "true")
check(
    "B1 run_live_p2(purge=True) -> adapter.purge_traces_on_close=True",
    len(seen_true) == 1 and seen_true[0]["kw"] is True and seen_true[0]["adapter"] is True,
    f"captured={seen_true}",
)
seen_false = _run_live({"purge_traces_on_close": False}, "false")
check(
    "B2 run_live_p2(purge=False) -> adapter False（public 行为不变）",
    len(seen_false) == 1 and seen_false[0]["kw"] is False and seen_false[0]["adapter"] is False,
    f"captured={seen_false}",
)
seen_absent = _run_live({}, "absent")
check(
    "B3 run_live_p2 缺省 -> adapter False（负例 holdout_requires_purge 保持可达）",
    len(seen_absent) == 1 and seen_absent[0]["kw"] is False and seen_absent[0]["adapter"] is False,
    f"captured={seen_absent}",
)

# --------------------------------------------------------------------------- #
# C. 全链路：CLI -> run_live_p2 -> 真正 build_live_adapter（load_live_env 用显式
#    overrides 顶替，不读 .env；GO/预算/账本为 tmp 副本）
# --------------------------------------------------------------------------- #
orig_load_env = p2_live.load_live_env
orig_open_gate = p2_live.open_live_gate


def _full_chain_cli(visibility: str):
    p2_live.load_live_env = lambda environ=None, overrides=None: orig_load_env(
        {"MKTKB_OCR_DISABLED": "0"}, overrides=wt.LIVE_ENV_OVERRIDES
    )
    # CLI 调 run_live_p2 不带 now；这里只把时钟钉到 GO 有效窗口内，其余全是真门。
    p2_live.open_live_gate = lambda plan_arg, *, run_id, now=None: orig_open_gate(
        plan_arg, run_id=run_id, now=wt.NOW
    )
    p2_dataset.load_p2_dataset = lambda _path, *, visibility: _fake_holdout_view()
    seen = _build_capture()
    args = wt._cli_args(TMP, visibility=visibility)
    err = None
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            cli._cmd_p2_run(args)
    except _Stop:
        pass
    except BaseException as exc:  # noqa: BLE001
        err = f"{type(exc).__name__}: {exc}"
    finally:
        p2_live.load_live_env = orig_load_env
        p2_live.open_live_gate = orig_open_gate
        p2_live.build_live_adapter = orig_build
        p2_dataset.load_p2_dataset = orig_load_dataset
    return seen, err


seen_hold, err_hold = _full_chain_cli("holdout")
check(
    "C1 全链路 CLI holdout -> 真正 ProductEvalAdapter(purge_traces_on_close=True)",
    err_hold is None and len(seen_hold) == 1 and seen_hold[0]["adapter"] is True,
    f"err={err_hold} captured={seen_hold}",
)
seen_pub, err_pub = _full_chain_cli("public")
check(
    "C2 全链路 CLI public -> 真正 ProductEvalAdapter(purge_traces_on_close=False)",
    err_pub is None and len(seen_pub) == 1 and seen_pub[0]["adapter"] is False,
    f"err={err_pub} captured={seen_pub}",
)

# --------------------------------------------------------------------------- #
# D. 负例可达（修复未绕过）：holdout + purge=False 仍被 runner 拒；purge=True 放行
# --------------------------------------------------------------------------- #
cases = wt._dataset().cases
holdout_ds = P2RunDataset(
    visibility="holdout",
    cases=cases,
    identity={
        "dataset_version": "probe-holdout-v1",
        "label_version": "probe-holdout-v1",
        "suite": "h2",
        "manifest_sha256": "c" * 64,
        "case_count": len(cases),
    },
)
snapshot = p2a.read_ledger_snapshot()
preflight = p2a.preflight_p2(plan, snapshot)
authorization = p2_runner.build_dry_run_authorization(
    plan, preflight, issued_by="verify:h2purge", now=wt.NOW
)
ingest = P2IngestPlan(sources=(IngestSource(path=wt.D01),), label="probe-h2purge")


def _run_holdout(purge: bool, tag: str):
    chat = MockChatBackend()
    adapter = ProductEvalAdapter(
        TMP / f"holdout-{tag}",
        chat=chat,
        dataset=holdout_ds,
        ingest_plan=ingest,
        purge_traces_on_close=purge,
    )

    async def go():
        try:
            return await p2_runner.run_p2(
                plan, adapter=adapter, authorization=authorization, now=wt.NOW
            )
        finally:
            await adapter.close()

    result = asyncio.run(go())
    return result, chat, adapter


res_bad, chat_bad, adapter_bad = _run_holdout(False, "nopurge")
gate_bad = json.loads((adapter_bad.paths.run_dir / "gate.json").read_text(encoding="utf-8"))
failed_bad = {c["name"] for c in gate_bad["checks"] if not c["ok"]}
check(
    "D1 负例仍可达：holdout + purge=False -> blocked/holdout_requires_purge，零发送",
    res_bad.status == "blocked"
    and res_bad.stop_code == "holdout_requires_purge"
    and res_bad.requests_sent == 0
    and chat_bad.call_count == 0
    and failed_bad == {"holdout_purge"}
    and gate_bad["real_sends_allowed"] is False,
    f"status={res_bad.status} stop={res_bad.stop_code} sent={res_bad.requests_sent} chat={chat_bad.call_count} failed_checks={sorted(failed_bad)}",
)
check(
    "D2 负例 fail-closed 细节：未建 trace 库、summary 标 refused-before-start",
    not adapter_bad.paths.trace_db.exists()
    and json.loads((adapter_bad.paths.run_dir / "summary.json").read_text(encoding="utf-8"))[
        "holdout"
    ]["trace_retention"]
    == "refused-before-start",
    f"trace_db_exists={adapter_bad.paths.trace_db.exists()}",
)

res_ok, chat_ok, adapter_ok = _run_holdout(True, "purge")
check(
    "D3 正对照：holdout + purge=True 不再被 holdout_requires_purge 拒（规则未失效/未恒拒）",
    res_ok.stop_code != "holdout_requires_purge",
    f"status={res_ok.status} stop={res_ok.stop_code} sent={res_ok.requests_sent} chat_calls={chat_ok.call_count}",
)

# --------------------------------------------------------------------------- #
# E. 真 argv（argparse -> handler）端到端：--visibility holdout / 省略（默认 public）
# --------------------------------------------------------------------------- #
def _argv_probe(extra: list[str], tag: str):
    captured: list[dict] = []

    async def fake_run(_plan, **kwargs):
        captured.append(kwargs)
        return _stub_result, _stub_build

    p2_live.run_live_p2 = fake_run
    p2_dataset.load_p2_dataset = lambda _path, *, visibility: _fake_holdout_view()
    plan_path = TMP / f"plan-{tag}.json"
    plan_path.write_text(json.dumps(wt._plan_dict_for_file(wt._plan())), encoding="utf-8")
    argv = [
        "p2-run",
        "--plan",
        str(plan_path),
        "--out",
        str(TMP / f"cli-{tag}"),
        "--mode",
        "live",
        "--run-id",
        f"probe-argv-{tag}",
        "--ingest",
        str(wt.D01),
    ] + extra
    code, exc = None, None
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = cli.main(argv)
    except BaseException as error:  # noqa: BLE001
        exc = f"{type(error).__name__}: {error}"
    finally:
        p2_live.run_live_p2 = orig_run_live
        p2_dataset.load_p2_dataset = orig_load_dataset
    return code, captured, exc


code_eh, cap_eh, err_eh = _argv_probe(
    ["--visibility", "holdout", "--holdout-manifest", str(TMP / "holdout-manifest.json")],
    "holdout",
)
check(
    "E1 真 argv --visibility holdout --mode live -> purge_traces_on_close=True",
    err_eh is None and code_eh == 0 and len(cap_eh) == 1 and cap_eh[0].get("purge_traces_on_close") is True,
    f"exit={code_eh} err={err_eh} purge={cap_eh[0].get('purge_traces_on_close') if cap_eh else None}",
)
code_ep, cap_ep, err_ep = _argv_probe([], "public-default")
check(
    "E2 真 argv 省略 --visibility（缺省 public）-> purge_traces_on_close=False",
    err_ep is None and code_ep == 0 and len(cap_ep) == 1 and cap_ep[0].get("purge_traces_on_close") is False,
    f"exit={code_ep} err={err_ep} purge={cap_ep[0].get('purge_traces_on_close') if cap_ep else None} visibility={cap_ep[0]['dataset'].visibility if cap_ep else None}",
)

print()
print(f"SUMMARY pass={len(FINDINGS) - len(FAILED)} fail={len(FAILED)}")
if FAILED:
    print("FAILED:", ", ".join(FAILED))
    sys.exit(1)

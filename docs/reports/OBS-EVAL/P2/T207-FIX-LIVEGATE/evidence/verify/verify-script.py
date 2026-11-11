
"""独立验收脚本（T207-FIX-LIVEGATE v2）：自建计划/GO/预算/账本副本，零真实出站。"""
import ast, copy, importlib.util, itertools, json, os, sys, types, difflib
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(r"D:/GPT项目/市场部AI知识库")
sys.path.insert(0, str(REPO / "backend" / "src"))
TMP = Path(os.environ["VG_TMP"])

from mktkb.evaluation import p2_authorization as p2a
from mktkb.evaluation import p2_contracts as c
from mktkb.evaluation import p2_live
from mktkb.evaluation.p2_contracts import P2RunPlan
from mktkb import live_authorization

NOW = datetime(2026, 11, 19, 3, 0, tzinfo=timezone.utc)
TOTAL, STAGE = 40.0, 20.0
CENTERS = {"answer_retrieval": 9.0, "ocr": 6.0, "judge": 3.0, "independent": 2.0}
CORE = ("answer", "index_embedding", "query_embedding", "rerank")
OLD_REQUIRED = set(CORE) | {"ocr"}

RESULTS = []
def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))
    print(("PASS  " if ok else "FAIL  ") + name + ("  | " + detail if detail else ""))

def load_old_module():
    spec = importlib.util.spec_from_file_location("mktkb.evaluation.p2_live_old", TMP / "p2_live_pre_fix.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["mktkb.evaluation.p2_live_old"] = mod
    spec.loader.exec_module(mod)
    return mod

PROFILES = {
    "embedding": {"kind": "embedding", "model": "text-embedding-v4", "provider": "bailian",
                  "host": "dashscope.aliyuncs.com", "region": "cn-beijing",
                  "pricing_source": "official-list-price/bailian-text-embedding-v4-v1",
                  "unit_price_per_million_cny": 0.5, "total_tokens_cap": 4096},
    "rerank": {"kind": "rerank", "model": "gte-rerank-v2", "provider": "bailian",
               "host": "dashscope.aliyuncs.com", "region": "cn-beijing",
               "pricing_source": "official-list-price/bailian-gte-rerank-v2-v1",
               "unit_price_per_million_cny": 0.8, "total_tokens_cap": 6000},
    "chat": {"kind": "chat", "model": "deepseek-flash", "provider": "deepseek",
             "host": "api.deepseek.com", "region": "global",
             "pricing_source": "official-list-price/deepseek-chat-cache-miss-v1",
             "input_price_per_million_cny": 2.0, "output_price_per_million_cny": 8.0,
             "prompt_tokens_cap": 6144, "completion_tokens_cap": 800},
    "ocr": {"kind": "ocr", "model": "GeneralAccurateOCR", "provider": "tencent",
            "host": "ocr.tencentcloudapi.com", "region": "ap-guangzhou",
            "pricing_source": "official-list-price/tencent-ocr-postpaid-highest-v1",
            "price_cny_per_page": 0.5, "pages_per_request": 1},
}

def item(item_id, operation, case_id, requests=1, page=0):
    kind = c.OPERATION_KIND[operation]
    expected = {"chat": 0.004, "embedding": 0.0003, "rerank": 0.001, "ocr": 0.5}[kind]
    return {"item_id": item_id, "operation": operation,
            "cost_center": c.OPERATION_COST_CENTER[operation], "case_id": case_id,
            "turn": 1, "page": page, "requests": requests,
            "price_profile": copy.deepcopy(PROFILES[kind]), "expected_success_cny": expected}

def plan_dict(plan_id, *, ocr_pages=2, drop=()):
    items = [item("ingest-index", "index_embedding", "INGEST", requests=8)]
    for case in ("Q01", "Q25"):
        for op in ("query_embedding", "rerank", "query_expansion", "answer"):
            items.append(item(op + "-" + case + "-t1", op, case))
    for p in range(1, ocr_pages + 1):
        items.append(item("ocr-Q01-p" + str(p), "ocr", "Q01", page=p))
    items = [i for i in items if i["operation"] not in drop]
    return {"schema_version": c.P2_RUN_PLAN_SCHEMA_VERSION, "plan_id": plan_id,
            "plan_version": "v0.1", "mode": "end_to_end", "stage": "P2-LIVE",
            "created_utc": "2026-11-11T00:00:00+08:00",
            "project_total_limit_cny": TOTAL, "stage_limit_cny": STAGE,
            "max_requests": 1000, "cost_centers_cny": dict(CENTERS), "items": items}

def write_ledger(path):
    path.write_text(json.dumps({"event": "historical_import", "accounted_cny": 2.0,
                                "source": "livegate-verify"}, ensure_ascii=False) + "\n", encoding="utf-8")

def write_budget(path):
    path.write_text(json.dumps({"limit_cny": TOTAL, "historical_conservative_accounted_cny": 2.0,
                                "stages": {"S2-DEV": 18.0, "P2-LIVE": STAGE}},
                               ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

def write_go(path, ledger, plan, ops=None):
    centers = {k: max(float(v), float(CENTERS[k])) for k, v in plan.cost_centers_cny.items()}
    path.write_text(json.dumps({
        "document": "P2-LIVE-GO", "schema_version": "p2-live-go/v0.1", "stage": "P2-LIVE",
        "authorization": "VERIFY-MOCK-GO（零真实调用）", "issued_by": "verifier",
        "nonce": "verify-livegate-nonce-0123456789",
        "issued_utc": "2026-11-19T00:00:00+00:00", "expires_utc": "2026-11-20T00:00:00+00:00",
        "budget_ledger_path": str(ledger),
        "budget_ledger_sha256": live_authorization.historical_prefix_sha256(ledger),
        "budget_total_limit_cny": float(plan.project_total_limit_cny),
        "scope": {"plan_id": plan.plan_id, "plan_sha256": plan.plan_sha256,
                  "operations": sorted(ops if ops is not None else plan.operations),
                  "cost_centers_cny": centers,
                  "stage_limits_cny": {"P2-LIVE": max(STAGE, float(plan.stage_limit_cny))},
                  "max_requests": max(1000, int(plan.max_requests)), "max_request_cny": 0.5},
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

def probe(module, plan, run_id):
    try:
        gate = module.open_live_gate(plan, run_id=run_id, now=NOW)
        return ("ok", gate, "")
    except Exception as exc:  # noqa: BLE001
        code = getattr(exc, "reason", None) or getattr(exc, "code", None) or type(exc).__name__
        detail = getattr(exc, "detail", "") or str(exc)
        return ("err", type(exc).__name__, str(code) + " :: " + str(detail))

def fn_src(text):
    for node in ast.parse(text).body:
        if isinstance(node, ast.FunctionDef) and node.name == "open_live_gate":
            return ast.get_source_segment(text, node)

def main():
    old = load_old_module()
    ledger = TMP / "live-ledger.jsonl"; budget = TMP / "budget.json"
    write_ledger(ledger); write_budget(budget)
    p2a.P2_LEDGER_PATH = ledger; p2a.P2_BUDGET_PATH = budget
    p2a.P2_GO_PATH = TMP / "P2-LIVE-GO.json"
    os.environ[live_authorization.TOTAL_LIMIT_ENV] = str(TOTAL)

    # ---------- A. 源码级 ----------
    new_src = (REPO / "backend/src/mktkb/evaluation/p2_live.py").read_text(encoding="utf-8")
    old_src = (TMP / "p2_live_pre_fix.py").read_text(encoding="utf-8")
    diff = [l for l in difflib.unified_diff(fn_src(old_src).splitlines(), fn_src(new_src).splitlines(), lineterm="", n=0)
            if l.startswith(("+", "-")) and not l.startswith(("+++", "---"))]
    removed = [l[1:].strip() for l in diff if l.startswith("-") and l[1:].strip()]
    added = [l[1:].strip() for l in diff if l.startswith("+") and l[1:].strip()]
    expect_removed = [
        "missing = sorted(",
        '{"answer", "index_embedding", "query_embedding", "rerank", "ocr"}',
        "- set(authorization.operations)",
        ")",
    ]
    a1 = removed == expect_removed
    a1 = a1 and added[-1] == "missing = sorted(set(required_live_operations(plan)) - set(authorization.operations))"
    a1 = a1 and all(("计划" in l or "操作校验" in l) for l in added[:-1])
    check("A1 open_live_gate 差异仅『4 行旧 missing 语句 -> 1 行新语句 + docstring 说明』", a1,
          json.dumps({"removed": removed, "added": added}, ensure_ascii=False))

    # ---------- B. 64 个子集的语义等价 ----------
    universe = ["answer", "index_embedding", "query_embedding", "rerank", "ocr", "query_expansion"]
    bad = []
    for r in range(len(universe) + 1):
        for subset in itertools.combinations(universe, r):
            S = set(subset)
            new_missing = set(p2_live.required_live_operations(types.SimpleNamespace(operations=tuple(sorted(S)))) ) - S
            old_missing = OLD_REQUIRED - S
            if "ocr" in S:
                if old_missing != new_missing: bad.append((subset, sorted(old_missing), sorted(new_missing)))
            else:
                if old_missing != new_missing | {"ocr"}: bad.append((subset, sorted(old_missing), sorted(new_missing)))
    check("B1 64 个操作子集：old/new 必需集差异恒为且仅为 ocr（计划无 ocr 项时）", not bad, str(bad))

    # ---------- C. 公开矩阵计划行为逐字不变 ----------
    public = P2RunPlan.from_dict(json.loads((REPO / "docs/reports/OBS-EVAL/P2/T207/PM/T207-plan-v0_1.json").read_text(encoding="utf-8")))
    check("C1 公开矩阵计划（233 项/12 页 OCR）：required == 旧五项",
          public.page_count == 12 and "ocr" in public.operations
          and set(p2_live.required_live_operations(public)) == OLD_REQUIRED,
          "items=%d page_count=%d ops=%s" % (len(public.items), public.page_count, public.operations))
    write_go(p2a.P2_GO_PATH, ledger, public)
    ro = probe(old, public, "vg-public-old"); rn = probe(p2_live, public, "vg-public-new")
    check("C2 公开计划 + GO 覆盖：old/new 均开门、authorization.operations 完全相同且含 ocr",
          ro[0] == "ok" and rn[0] == "ok"
          and ro[1].authorization.operations == rn[1].authorization.operations
          and "ocr" in rn[1].authorization.operations,
          str(rn[1].authorization.operations if rn[0] == "ok" else rn[1:]))
    write_go(p2a.P2_GO_PATH, ledger, public, ops=[op for op in public.operations if op != "ocr"])
    ro = probe(old, public, "vg-public-noocr-old"); rn = probe(p2_live, public, "vg-public-noocr-new")
    check("C3 公开计划 + GO 少 ocr：old/new 同为 go_operation_unauthorized",
          ro[0] == "err" and rn[0] == "err"
          and "go_operation_unauthorized" in ro[2] and "go_operation_unauthorized" in rn[2],
          "old=%s | new=%s" % (ro[2], rn[2]))
    for drop in CORE:
        pd = P2RunPlan.from_dict(plan_dict("VG-PUBLIC-NO-" + drop, ocr_pages=2, drop=(drop,)))
        write_go(p2a.P2_GO_PATH, ledger, pd)
        ro = probe(old, pd, "vg-pub-core-old"); rn = probe(p2_live, pd, "vg-pub-core-new")
        check("C4 公开型计划缺 %s：old/new 同为 live_operation_not_authorized 且指名" % drop,
              ro[0] == "err" and rn[0] == "err"
              and "live_operation_not_authorized" in ro[2] and "live_operation_not_authorized" in rn[2]
              and drop in ro[2] and drop in rn[2], "old=%s | new=%s" % (ro[2], rn[2]))

    # ---------- D. H2 型计划（无 OCR 项） ----------
    h2 = P2RunPlan.from_dict(plan_dict("VG-H2LIKE", ocr_pages=0))
    check("D1 H2 型计划：page_count=0、无 ocr、四核心齐",
          h2.page_count == 0 and "ocr" not in h2.operations and set(CORE) <= set(h2.operations),
          str(h2.operations))
    write_go(p2a.P2_GO_PATH, ledger, h2)
    ro = probe(old, h2, "vg-h2-old"); rn = probe(p2_live, h2, "vg-h2-new")
    check("D2 H2 型计划 + GO=计划操作：旧逻辑拒 [ocr]，新逻辑开门",
          ro[0] == "err" and "live_operation_not_authorized" in ro[2] and "'ocr'" in ro[2]
          and rn[0] == "ok" and "ocr" not in rn[1].authorization.operations,
          "old=%s | new=%s" % (ro[2], ("ok ops=%s" % (rn[1].authorization.operations,)) if rn[0] == "ok" else rn[2]))
    write_go(p2a.P2_GO_PATH, ledger, h2, ops=list(h2.operations) + ["ocr"])
    ro = probe(old, h2, "vg-h2-sup-old"); rn = probe(p2_live, h2, "vg-h2-sup-new")
    check("D3 H2 型计划 + GO 超集（含 ocr）：新逻辑开门，authorization.operations 仍取自计划（无 ocr）",
          rn[0] == "ok" and "ocr" not in rn[1].authorization.operations and ro[0] == "err",
          "old=%s | new=%s" % (ro[2], ("ok ops=%s" % (rn[1].authorization.operations,)) if rn[0] == "ok" else rn[2]))
    for drop in CORE:
        pd = P2RunPlan.from_dict(plan_dict("VG-H2-NO-" + drop, ocr_pages=0, drop=(drop,)))
        write_go(p2a.P2_GO_PATH, ledger, pd)
        rn = probe(p2_live, pd, "vg-h2-core-new")
        check("D4 H2 型计划缺核心 %s：拒绝并指名（live_operation_not_authorized）" % drop,
              rn[0] == "err" and "live_operation_not_authorized" in rn[2] and drop in rn[2], rn[2])

    # ---------- E. 反向保护 ----------
    write_go(p2a.P2_GO_PATH, ledger, h2, ops=[op for op in h2.operations if op != "rerank"])
    ro = probe(old, h2, "vg-e1-old"); rn = probe(p2_live, h2, "vg-e1-new")
    check("E1 GO 少计划操作（缺 rerank）：go_operation_unauthorized（old/new 一致）",
          rn[0] == "err" and "go_operation_unauthorized" in rn[2] and "go_operation_unauthorized" in ro[2],
          "new=%s" % rn[2])
    write_go(p2a.P2_GO_PATH, ledger, h2, ops=list(h2.operations) + ["replay"])
    ro = probe(old, h2, "vg-e2-old"); rn = probe(p2_live, h2, "vg-e2-new")
    check("E2 GO 含未注册操作（replay）：go_operation_invalid（old/new 一致）",
          rn[0] == "err" and "go_operation_invalid" in rn[2] and "go_operation_invalid" in ro[2],
          "new=%s" % rn[2])

    # ---------- F. 无「计划外 OCR」通道 ----------
    write_go(p2a.P2_GO_PATH, ledger, h2, ops=list(h2.operations) + ["ocr"])
    gate = p2_live.open_live_gate(h2, run_id="vg-h2-channel", now=NOW)
    idx = p2_live.PlanIndex(h2)
    check("F1 H2 计划 PlanIndex.ocr_count == 0", idx.ocr_count == 0, "count=%d" % idx.ocr_count)
    try:
        idx.next_ocr_item(0); f2, f2d = False, "unexpected success"
    except p2_live.P2LiveRefused as exc:
        f2, f2d = exc.code == "attempt_item_exhausted", exc.code
    except Exception as exc:  # noqa: BLE001
        f2, f2d = False, type(exc).__name__
    check("F2 计划无 OCR 项时 next_ocr_item 一律拒绝（attempt_item_exhausted）", f2, f2d)
    try:
        gate.begin_attempt("ocr-Q01-p1"); f3, f3d = False, "unexpected success"
    except p2a.P2GateError as exc:
        f3, f3d = exc.reason == "item_unknown", exc.reason
    except Exception as exc:  # noqa: BLE001
        f3, f3d = False, type(exc).__name__ + ":" + str(exc)
    check("F3 计划外 OCR item 无法 begin_attempt（item_unknown，预留前拒）", f3, f3d)
    ticket = gate.begin_attempt("rerank-Q01-t1")
    check("F4 H2 门自身可用：计划内 rerank 项 begin_attempt 成功（成本中心来自计划项）",
          ticket.operation == "rerank" and ticket.item_id == "rerank-Q01-t1" and ticket.cost_center == c.OPERATION_COST_CENTER["rerank"],
          "op=%s center=%s" % (ticket.operation, ticket.cost_center))
    check("F5 required_live_operations / LIVE_CORE_OPERATIONS 已导出且等于四核心",
          "required_live_operations" in p2_live.__all__ and "LIVE_CORE_OPERATIONS" in p2_live.__all__
          and tuple(p2_live.LIVE_CORE_OPERATIONS) == CORE, str(p2_live.LIVE_CORE_OPERATIONS))

    failed = [r for r in RESULTS if not r[1]]
    print("\nSUMMARY: %d checks, %d passed, %d failed" % (len(RESULTS), len(RESULTS) - len(failed), len(failed)))
    return 0 if not failed else 1

sys.exit(main())

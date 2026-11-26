"""C4 独立负例：自建 6+ 类坏证据，核预定义状态/缺失/阻断（不只看 exit code）。

每类都同时核：严格 reader 的固定拒绝码 或 分类器的固定 unknown/violation 状态与
missing 码；CLI 只作为“是否阻断/是否产卡”的附加证据。
"""

from __future__ import annotations

import asyncio
import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ci_support as sup  # noqa: E402

AXES = ("safety", "cross_user", "cross_entity", "stale_source")
rows: list[tuple[str, bool, str, str]] = []


def record(case: str, ok: bool, expected: str, actual: str) -> None:
    rows.append((case, bool(ok), expected, actual))
    print(f"[{'PASS' if ok else 'FAIL'}] {case}")
    print(f"        expect: {expected}")
    print(f"        actual: {actual}")


def reader_error(path: Path, key: bytes) -> str:
    from mktkb.evaluation.p2_evidence_io import read_encrypted_evidence

    try:
        read_encrypted_evidence(path, key=key)
    except Exception as exc:  # noqa: BLE001 - 期望固定拒绝
        return str(exc)
    return "<NO-ERROR>"


def copy_evidence(tmp: Path, tag: str, inputs: dict) -> dict:
    root = tmp / tag / "evidence"
    root.parent.mkdir(parents=True, exist_ok=True)
    import shutil

    shutil.copytree(inputs["evidence_dir"], root)
    local = dict(inputs)
    local["evidence_dir"] = root
    local["scope_path"] = inputs["scope_path"]
    return local


def mutate(local: dict, key: bytes, index: int, fn) -> None:
    path = local["evidence_dir"] / local["files"][index]
    payload = sup.decrypt_raw(path, key)
    fn(payload)
    sup.encrypt_raw(path, key, payload)


def _renumber(payload: dict) -> None:
    events = payload["capture"]["events"]
    for position, event in enumerate(events, start=1):
        event["seq"] = position
    payload["capture"]["event_count"] = len(events)
    payload["capture"]["seq"] = len(events)


async def main() -> int:
    sup.install_network_guard()
    tmp = sup.fresh_temp("t207-ci-neg-")
    print("tmp_root=", tmp)
    try:
        capture = await sup.capture_run(tmp, "ci-neg-run")
        inputs = sup.write_inputs(tmp, capture=capture, cases=sup.case_specs())
        key = bytes(capture["writer"].key)
        base_card, base_results = sup.recompute_in_process(inputs)
        base_cross = [r.axis_state("cross_entity") for r in base_results]
        assert base_cross == ["passed", "unknown", "unknown", "violation"], base_cross

        # N1 缺 runtime_snapshot → 严格 reader 固定拒绝；CLI 非 0 不产卡。
        local = copy_evidence(tmp, "n1", inputs)
        mutate(local, key, 0, lambda payload: payload.pop("runtime_snapshot"))
        code = reader_error(local["evidence_dir"] / local["files"][0], key)
        out = tmp / "out" / "n1.json"
        completed = sup.run_cli(tmp, local, out)
        record(
            "N1 缺 runtime_snapshot",
            code.startswith("envelope_missing_required:runtime_snapshot")
            and completed.returncode != 0
            and not out.exists(),
            "reader=固定拒绝(envelope_missing_required:runtime_snapshot) + CLI!=0 + 不产卡",
            f"reader={code} cli={completed.returncode} card={out.exists()}",
        )

        # N2 重复 model_input 事件 → 分支门 unknown（不得 pass）。
        local = copy_evidence(tmp, "n2", inputs)
        mutate(
            local,
            key,
            0,
            lambda payload: (
                payload["capture"]["events"].append(
                    {
                        **copy.deepcopy(
                            next(e for e in payload["capture"]["events"] if e["kind"] == "model_input")
                        ),
                        "seq": len(payload["capture"]["events"]) + 1,
                    }
                ),
                _renumber(payload),
            ),
        )
        _card, results = sup.recompute_in_process(local)
        record(
            "N2 重复 model_input（只改被篡改题，其余题不受影响）",
            all(results[0].axis_state(axis) == "unknown" for axis in AXES)
            and "branch_evidence_inconsistent" in results[0].missing_codes
            and [r.axis_state("cross_entity") for r in results[1:]] == ["unknown", "unknown", "violation"],
            "CI-A 四轴全 unknown + missing 含 branch_evidence_inconsistent；其余题结论不变",
            f"CI-A={[results[0].axis_state(a) for a in AXES]} missing={list(results[0].missing_codes)} "
            f"others={[r.axis_state('cross_entity') for r in results[1:]]}",
        )

        # N3 单侧模型事件（删 model_output）→ model_events_missing。
        local = copy_evidence(tmp, "n3", inputs)

        def drop_output(payload: dict) -> None:
            payload["capture"]["events"] = [
                event for event in payload["capture"]["events"] if event["kind"] != "model_output"
            ]
            _renumber(payload)

        mutate(local, key, 0, drop_output)
        _card, results = sup.recompute_in_process(local)
        record(
            "N3 单侧模型事件（缺 model_output）",
            results[0].axis_state("cross_entity") == "unknown"
            and "model_events_missing" in results[0].missing_codes,
            "cross_entity=unknown + missing 含 model_events_missing",
            f"state={results[0].axis_state('cross_entity')} missing={list(results[0].missing_codes)}",
        )

        # N4 坏分页（returned>total）→ reader 固定 runtime_pagination_invalid；CLI 非 0 不产卡。
        local = copy_evidence(tmp, "n4", inputs)

        def bad_page(payload: dict) -> None:
            page = payload["runtime_snapshot"]["product_response"]["pagination"]
            page["returned"] = page["total"] + 1

        mutate(local, key, 3, bad_page)
        code = reader_error(local["evidence_dir"] / local["files"][3], key)
        out = tmp / "out" / "n4.json"
        completed = sup.run_cli(tmp, local, out)
        record(
            "N4 坏分页 returned>total",
            code == "runtime_pagination_invalid" and completed.returncode != 0 and not out.exists(),
            "reader=runtime_pagination_invalid + CLI!=0 + 不产卡",
            f"reader={code} cli={completed.returncode} card={out.exists()}",
        )

        # N5 跨 run 绑定（case-plan 改 run_id）→ reader/CLI 固定拒绝。
        local = copy_evidence(tmp, "n5", inputs)
        plan = json.loads(inputs["case_plan_path"].read_text(encoding="utf-8"))
        plan["bindings"]["run_id"] = "ci-other-run"
        cross_plan = tmp / "n5" / "case-plan.json"
        cross_plan.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
        out = tmp / "out" / "n5.json"
        completed = sup.run_cli(tmp, local, out, case_plan_path=cross_plan)
        record(
            "N5 跨 run 绑定",
            completed.returncode != 0
            and "cross_binding_mismatch" in (completed.stderr or "")
            and not out.exists(),
            "CLI!=0 + 固定 cross_binding_mismatch + 不产卡",
            f"cli={completed.returncode} stderr={completed.stderr.strip()[:120]} card={out.exists()}",
        )

        # N6 非空原始占位容器（source_ids=[""]）→ 严格空集证明失败。
        local = copy_evidence(tmp, "n6", inputs)

        def raw_placeholder(payload: dict) -> None:
            for event in payload["capture"]["events"]:
                if event["kind"] == "answer_result":
                    event["payload"]["source_ids"] = [""]

        mutate(local, key, 2, raw_placeholder)
        _card, results = sup.recompute_in_process(local)
        record(
            "N6 非空原始容器 source_ids=['']",
            results[1].axis_state("cross_entity") == "unknown"
            and "empty_set_not_proven" in results[1].missing_codes,
            "cross_entity=unknown + missing 含 empty_set_not_proven（不得 N/A/pass）",
            f"state={results[1].axis_state('cross_entity')} missing={list(results[1].missing_codes)}",
        )

        # N7 正文归属映射错版本（scope shared version_id 改坏）→ 不得 pass。
        local = copy_evidence(tmp, "n7", inputs)
        scope = json.loads(inputs["scope_path"].read_text(encoding="utf-8"))
        scope["cases"][0]["shared_background"][0]["version_id"] = "00000000-0000-0000-0000-000000000000"
        scope_path = tmp / "n7" / "scope.json"
        scope_path.write_text(json.dumps(scope, ensure_ascii=False), encoding="utf-8")
        local["scope_path"] = scope_path
        _card, results = sup.recompute_in_process(local)
        record(
            "N7 正文归属映射错版本",
            results[0].axis_state("cross_entity") == "unknown"
            and results[0].axes["cross_entity"].reason == "free_text_attribution_unverifiable",
            "CI-A cross_entity=unknown/free_text_attribution_unverifiable",
            f"state={results[0].axis_state('cross_entity')} reason={results[0].axes['cross_entity'].reason}",
        )

        # N8 scope 合同绑定不符 → CLI 固定拒绝。
        local = copy_evidence(tmp, "n8", inputs)
        scope = json.loads(inputs["scope_path"].read_text(encoding="utf-8"))
        scope["bindings"]["run_id"] = "ci-other-run"
        scope_path = tmp / "n8" / "scope.json"
        scope_path.write_text(json.dumps(scope, ensure_ascii=False), encoding="utf-8")
        local["scope_path"] = scope_path
        out = tmp / "out" / "n8.json"
        completed = sup.run_cli(tmp, local, out)
        record(
            "N8 scope 合同绑定不符",
            completed.returncode != 0
            and "scope_contract_binding_mismatch" in (completed.stderr or "")
            and not out.exists(),
            "CLI!=0 + scope_contract_binding_mismatch + 不产卡",
            f"cli={completed.returncode} stderr={completed.stderr.strip()[:120]} card={out.exists()}",
        )

        # N9 缺 scope 合同 → 旧语义全 unknown，回执不冒充合同。
        out = tmp / "out" / "n9.json"
        completed = sup.run_cli(tmp, inputs, out, scope=False)
        card_no_scope = json.loads(out.read_text(encoding="utf-8"))
        receipt = json.loads(completed.stdout.strip().splitlines()[-1])
        axes = card_no_scope["hard_evidence"]["axes"]["cross_entity"]
        record(
            "N9 缺 scope 合同（旧语义）",
            completed.returncode == 0
            and axes["passed"] == 0
            and axes["unknown"] == 4
            and receipt["scope_contract_sha256"] is None
            and receipt["scope_contract_case_count"] == 0,
            "cross_entity passed=0/unknown=4 + 回执合同 SHA=null/0 case（不悄悄 pass）",
            f"passed={axes['passed']} unknown={axes['unknown']} sha={receipt['scope_contract_sha256']} n={receipt['scope_contract_case_count']}",
        )

        # N10-N12：事后篡改快照字段（需 key 重签）在“密封完整性”模型下的行为记录。
        def snapshot_tamper(tag: str, index: int, fn, capture_expect: str) -> None:
            from mktkb.evaluation.p2_evidence_capture import evaluate_completeness

            local = copy_evidence(tmp, tag, inputs)
            mutate(local, key, index, fn)
            payload = sup.decrypt_raw(local["evidence_dir"] / local["files"][index], key)
            recomputed = evaluate_completeness(
                events=payload["capture"]["events"],
                projection=payload["db_projection"],
                timed_out=bool(payload["turn"]["timed_out"]),
                capture_status=payload["capture"]["status"],
                capture_errors=payload["capture"].get("errors") or [],
                post_revision=payload["turn"].get("post_revision"),
                authenticated_user_id=payload["turn"].get("authenticated_user_id"),
                http_status=payload["turn"].get("http_status"),
                runtime_snapshot=payload["runtime_snapshot"],
                turn_identity=payload["turn"],
            )
            _card, results = sup.recompute_in_process(local)
            record(
                f"记录：{tag}（采集期是否会拦 vs 重算是否二次推导）",
                capture_expect in (recomputed.get("errors") or []),
                f"采集期 completeness 含 {capture_expect}；重算结果如实记录",
                f"capture_errors={recomputed.get('errors')} sealed_status={payload['completeness']['status']} "
                f"recompute_cross={[r.axis_state('cross_entity') for r in results]}",
            )

        def bump_version(payload: dict) -> None:
            payload["runtime_snapshot"]["product_response"]["sources"][0]["version_number"] += 1

        snapshot_tamper("N10 快照产品来源版本被改", 0, bump_version, "runtime_projection_version_mismatch")

        def drop_model_evidence(payload: dict) -> None:
            payload["runtime_snapshot"]["retrieval_use"]["model_evidence"] = []

        snapshot_tamper("N11 快照使用层与事件不一致", 0, drop_model_evidence, "runtime_usage_inconsistent")

        def trace_unavailable(payload: dict) -> None:
            payload["runtime_snapshot"]["trace"]["availability"] = "unavailable"
            payload["runtime_snapshot"]["trace"]["reason"] = "trace_record_missing"

        snapshot_tamper("N12 快照 trace 与事件不一致", 0, trace_unavailable, "runtime_trace_unresolved")

        # N13 删 claim_observed（必需事件缺失，soft 门）→ 不得 pass。
        local = copy_evidence(tmp, "n13", inputs)

        def drop_claim(payload: dict) -> None:
            payload["capture"]["events"] = [
                event for event in payload["capture"]["events"] if event["kind"] != "claim_observed"
            ]
            _renumber(payload)

        mutate(local, key, 0, drop_claim)
        _card, results = sup.recompute_in_process(local)
        record(
            "N13 删必需事件 claim_observed（只改被篡改题）",
            all(results[0].axis_state(axis) != "passed" for axis in AXES)
            and (
                "branch_evidence_missing" in results[0].missing_codes
                or "model_events_missing" in results[0].missing_codes
            )
            and [r.axis_state("cross_entity") for r in results[1:]] == ["unknown", "unknown", "violation"],
            "CI-A 四轴无 passed + missing 含 branch_evidence_missing/claim_missing；其余题结论不变",
            f"CI-A={[results[0].axis_state(a) for a in AXES]} missing={list(results[0].missing_codes)} "
            f"others={[r.axis_state('cross_entity') for r in results[1:]]}",
        )

        # N14 未知顶层键 → reader 固定拒绝。
        local = copy_evidence(tmp, "n14", inputs)
        mutate(local, key, 0, lambda payload: payload.update({"ci_extra": 1}))
        code = reader_error(local["evidence_dir"] / local["files"][0], key)
        record(
            "N14 未知顶层键",
            code.startswith("envelope_unknown_keys"),
            "reader=envelope_unknown_keys:*",
            f"reader={code}",
        )

        record("网络边界：负例全程真实外连 0", sup.external_attempts() == [], "external=[]", str(sup.external_attempts()))
    finally:
        sup.remove_tree(tmp)

    failed = [row for row in rows if not row[1]]
    print(f"\nNEGATIVE TOTAL={len(rows)} FAILED={len(failed)}")
    for case, _ok, expected, actual in failed:
        print("  FAILED:", case, "| expect:", expected, "| actual:", actual)
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

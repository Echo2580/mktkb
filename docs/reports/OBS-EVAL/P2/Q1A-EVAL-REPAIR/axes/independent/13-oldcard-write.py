#!/usr/bin/env python
"""探针 13：旧卡写入拒绝规则（同路径/等价路径/已存在/缺父目录/重复写入）+ 旧卡字节不变。

输出：13-oldcard-write.out.json
"""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

from _common import (
    sha,
    HERE,
    RUN_BINDINGS,
    annotation,
    case,
    cross_entity_contract,
    cross_entity_view,
    cross_user_view,
    dump,
    lifecycle,
    rescore,
    axes,
    ref,
    scope_target,
    stale_source_contract,
    stale_source_view,
    unit,
    version_binding,
)

RESULTS: list[dict] = []


def check(label: str, ok: bool, detail=None) -> None:
    RESULTS.append({"label": label, "ok": bool(ok), "detail": detail})


def expect_error(label: str, code: str, fn) -> None:
    try:
        fn()
    except axes.RescoreError as exc:
        check(label, str(exc) == code, {"expected": code, "actual": str(exc)})
    except Exception as exc:  # noqa: BLE001
        check(label, False, {"expected": code, "raised": type(exc).__name__, "message": str(exc)})
    else:
        check(label, False, {"expected": code, "raised": "no error"})


def build_report() -> axes.AxesRescoreReport:
    identity = axes.AxesIdentity(
        base=rescore.RescoreIdentity(
            old_run_id="OLD-RUN-SYN",
            old_binding=RUN_BINDINGS,
            old_binding_sha256="b" * 64,
            old_evidence_tree_sha256="e" * 64,
            old_card_sha256="f" * 64,
            contract_sha256=rescore.file_sha256(axes.DEFAULT_CONTRACT_PATH),
            evaluator_sha256=rescore.file_sha256(axes.__file__),
        ),
        base_contract_sha256=rescore.file_sha256(axes.BASE_CONTRACT_PATH),
    )
    view = case(
        case_id="SYN-WRITE-1",
        anns={
            "cross_user": annotation("cross_user"),
            "cross_entity": annotation("cross_entity"),
            "stale_source": annotation("stale_source"),
        },
        cross_user=cross_user_view(),
        cross_entity=cross_entity_view(
            units=(unit("u1"),), unit_entity={"u1": axes.EntityIdentityView("item", "K1")}
        ),
        cross_entity_contract=cross_entity_contract(targets=(scope_target("item", "K1"),)),
        stale_source=stale_source_view(
            units=(unit("u1"),), lifecycle_map={"u1": lifecycle()}, actual_as_of="2026-10-28"
        ),
        stale_source_contract=stale_source_contract(
            constrained_refs=(ref(),), version_bindings={rescore.ref_key(ref()): version_binding()}
        ),
    )
    return axes.rescore_axes_run(identity=identity, cases=(view,), allow_synthetic_fixture=True)


def main() -> int:
    root = Path(tempfile.mkdtemp(prefix="q1a1b-oldcard-"))
    try:
        old_card = root / "old-card.json"
        old_bytes = b'{"case_id": "SYN-OLD", "frozen": true}\n'
        old_card.write_bytes(old_bytes)
        before = old_card.read_bytes()

        report = build_report()

        # 1) 同路径
        expect_error(
            "same path -> old_card_overwrite_refused",
            "old_card_overwrite_refused",
            lambda: axes.write_axes_report(old_card, report, old_card_path=old_card),
        )
        check("old card bytes unchanged after same-path refusal", old_card.read_bytes() == before)

        # 2) 等价路径（子目录 + ..）
        sub = root / "sub"
        sub.mkdir()
        equivalent = sub / ".." / "old-card.json"
        expect_error(
            "equivalent path -> old_card_overwrite_refused",
            "old_card_overwrite_refused",
            lambda: axes.write_axes_report(equivalent, report, old_card_path=old_card),
        )
        check("old card bytes unchanged after equivalent-path refusal", old_card.read_bytes() == before)

        # 3) 已存在文件（非旧卡）
        existing = root / "existing.json"
        existing.write_bytes(b"keep-me\n")
        existing_before = existing.read_bytes()
        expect_error(
            "existing output -> output_exists",
            "output_exists",
            lambda: axes.write_axes_report(existing, report),
        )
        check("existing file bytes unchanged", existing.read_bytes() == existing_before)

        # 3b) 不传 old_card_path 时的旧卡同路径：仍必须拒绝
        expect_error(
            "old card path without explicit guard -> output_exists",
            "output_exists",
            lambda: axes.write_axes_report(old_card, report),
        )
        check("old card bytes unchanged after implicit refusal", old_card.read_bytes() == before)

        # 4) 缺父目录
        missing_parent = root / "no-such-dir" / "report.json"
        expect_error(
            "missing parent -> output_parent_missing",
            "output_parent_missing",
            lambda: axes.write_axes_report(missing_parent, report),
        )
        check("no partial file created for missing parent", not missing_parent.exists())

        # 5) 成功写入 + 重复写入拒绝
        target = root / "axes-report.json"
        result = axes.write_axes_report(target, report, old_card_path=old_card)
        payload = target.read_bytes()
        check("write returns sha256 of written bytes", result["sha256"] == rescore.file_sha256(target), result)
        check("write reports old_card_untouched", result["old_card_untouched"] is True)
        check("written bytes are canonical json + newline", payload == rescore.canonical_json_bytes(report.as_dict()) + b"\n")
        check("written payload parses as JSON", json.loads(payload.decode("utf-8"))["analysis_id"] == "Q1A-RESCORE-20261114-r1")
        expect_error(
            "duplicate write -> output_exists",
            "output_exists",
            lambda: axes.write_axes_report(target, report),
        )
        check("first written bytes unchanged after duplicate refusal", target.read_bytes() == payload)

        # 6) 旧卡始终未变
        check("old card bytes unchanged at end", old_card.read_bytes() == before)
        check("old card sha stable", rescore.file_sha256(old_card) == sha(before))
    finally:
        shutil.rmtree(root, ignore_errors=True)

    failures = [item for item in RESULTS if not item["ok"]]
    payload = {
        "probe": "13-oldcard-write",
        "assertions_total": len(RESULTS),
        "assertions_failed": len(failures),
        "failures": failures,
        "results": RESULTS,
        "verdict": "PASS" if not failures else "FAIL",
    }
    dump(HERE / "13-oldcard-write.out.json", payload)
    print(json.dumps({"assertions": len(RESULTS), "failed": len(failures), "verdict": payload["verdict"]}, ensure_ascii=False))
    if failures:
        print(json.dumps(failures, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())


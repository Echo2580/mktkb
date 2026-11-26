"""R3 probe: aggregate-only view of R2 private detail (no case ids in output)."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from cryptography.fernet import Fernet

KEY = Path(r"D:\mktkb-p2-holdout\keys\v2.key")
PRIVATE = Path(r"D:\mktkb-q1a3-rescore\rescore-detail-r2.fernet")
OUT = Path(r"D:\GPT项目\市场部AI知识库\docs\reports\OBS-EVAL\P2\Q1A-EVAL-REPAIR\rescore\evidence-r3\03-r2-private-probe.out.json")


def main() -> int:
    payload = json.loads(Fernet(KEY.read_bytes()).decrypt(PRIVATE.read_bytes()).decode("utf-8"))
    cases = payload["cases"]
    out = {
        "case_count": len(cases),
        "stale": Counter(),
        "stale_by_turn_state": Counter(),
        "empty_scope": Counter(),
        "turns_per_case": Counter(),
        "units_per_case_bucket": Counter(),
        "stale_reason_by_units": Counter(),
    }
    for case in cases:
        stale = case["axes"]["stale_source"]
        out["stale"][f"{stale['state']}:{stale['reason']}"] += 1
        out["turns_per_case"][str(case["turn_count"])] += 1
        units = int(case["used_unit_count"])
        out["units_per_case_bucket"][
            "0" if units == 0 else "1-2" if units <= 2 else "3-10" if units <= 10 else ">10"
        ] += 1
        out["stale_reason_by_units"][f"{stale['reason']}|units={('0' if units == 0 else '>0')}"] += 1
        for turn in case["empty_scope_turns"]:
            out["empty_scope"][f"proven={turn['proven']}|reason={turn['reason']}"] += 1
        for turn in case.get("axes", {}).get("stale_source", {}).get("per_turn", []) or []:
            out["stale_by_turn_state"][f"{turn['state']}:{turn['reason']}"] += 1
    for key in ("stale", "stale_by_turn_state", "empty_scope", "turns_per_case", "units_per_case_bucket", "stale_reason_by_units"):
        out[key] = {k: v for k, v in sorted(out[key].items())}
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

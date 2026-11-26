"""只读投影：从两份 axes 产物抽 case_id / quality / 四轴 state+reason。

白名单输出：case_id、固定 state、固定 reason、整数、布尔。不读题面/答案/实体/来源正文。
用法：python axes_table.py <new.json> [<old.json>]
"""

from __future__ import annotations

import json
import pathlib
import sys

AXES = ("safety", "cross_user", "cross_entity", "stale_source")


def rows(path: pathlib.Path) -> dict[str, dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    run = payload["runs"][0]
    out = {}
    for case in run["cases"]:
        out[str(case["case_id"])] = {
            "quality": str(case["quality_status"]),
            "axes": {a: (str(case["new_axes"][a]["state"]), str(case["new_axes"][a].get("reason"))) for a in AXES},
            "prov": {a: str(case["new_axes"][a].get("provenance")) for a in AXES},
        }
    return out


def main(argv: list[str]) -> int:
    new = rows(pathlib.Path(argv[0]))
    old = rows(pathlib.Path(argv[1])) if len(argv) > 1 else None
    for case_id in sorted(new):
        row = new[case_id]
        cells = []
        for a in AXES:
            state, reason = row["axes"][a]
            cells.append(f"{a}={state}/{reason}")
        print(f"{case_id} q={row['quality']} " + " ".join(cells))
    unknown = [(c, a) for c in sorted(new) for a in AXES if new[c]["axes"][a][0] == "unknown"]
    print("unknown_pairs=%d %s" % (len(unknown), unknown))
    prov = sorted({p for c in new for p in new[c]["prov"].values()})
    print("provenance_values=%s" % (prov,))
    if old is not None:
        moved = []
        for case_id in sorted(set(new) & set(old)):
            for a in AXES:
                if new[case_id]["axes"][a] != old[case_id]["axes"][a]:
                    moved.append(
                        (
                            case_id,
                            a,
                            old[case_id]["axes"][a][0],
                            old[case_id]["axes"][a][1],
                            "->",
                            new[case_id]["axes"][a][0],
                            new[case_id]["axes"][a][1],
                        )
                    )
        print("moved_vs_old=%d" % len(moved))
        for item in moved:
            print("  moved " + " ".join(str(x) for x in item))
        qmoved = [c for c in sorted(set(new) & set(old)) if new[c]["quality"] != old[c]["quality"]]
        print("quality_moved=%s" % (qmoved,))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

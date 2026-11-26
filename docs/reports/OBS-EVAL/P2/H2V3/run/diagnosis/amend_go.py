"""阶段 2：把 4 份 GO 的 scope.max_requests 从 1137 调到 1150（仅该字段）。

做法：
- 逐文件二进制读入，断言 `"max_requests": 1137` 恰好出现 1 次（另一处 `1137` 在 authorization 散文字符串里，不动）；
- 先把**改前字节**归档到新文件名（不覆盖任何既有归档）；
- 只替换该一处，写回；再逐叶子比对（只允许 scope.max_requests 变），
  并复算 canonical payload SHA（`p2_contracts.payload_sha256`，排序键紧凑分隔符）。

输出：go-amend-evidence.json（仓外生成，随后拷入 H2V3/run/）。
"""

from __future__ import annotations

import json
import hashlib
import sys
from pathlib import Path

REPO = Path(r"D:\GPT项目\市场部AI知识库")
sys.path.insert(0, str(REPO / "backend" / "src"))
from mktkb.evaluation.p2_contracts import payload_sha256  # noqa: E402

PM = REPO / "docs/evidence/LOCAL-R1-20261101/PM"
TARGETS = [
    (0, PM / "P2-LIVE-GO.json", PM / "P2-LIVE-GO.v3-max1150-r0.previous.archived.json"),
    (1, PM / "P2-LIVE-GO.v3-r1.pending.json", PM / "P2-LIVE-GO.v3-max1150-r1.previous.archived.json"),
    (2, PM / "P2-LIVE-GO.v3-r2.pending.json", PM / "P2-LIVE-GO.v3-max1150-r2.previous.archived.json"),
    (3, PM / "P2-LIVE-GO.v3-r3.pending.json", PM / "P2-LIVE-GO.v3-max1150-r3.previous.archived.json"),
]
OLD, NEW = b'"max_requests": 1137', b'"max_requests": 1150'


def leaf_diff(a, b, path=""):
    out = []
    if type(a) is not type(b):
        return [{"path": path or "$", "before": a, "after": b}]
    if isinstance(a, dict):
        for key in sorted(set(a) | set(b)):
            out += leaf_diff(a.get(key), b.get(key), f"{path}.{key}" if path else key)
    elif isinstance(a, list):
        for i in range(max(len(a), len(b))):
            out += leaf_diff(a[i] if i < len(a) else None, b[i] if i < len(b) else None, f"{path}[{i}]")
    elif a != b:
        out.append({"path": path, "before": a, "after": b})
    return out


def main() -> None:
    ledger = REPO / "docs/evidence/LOCAL-R1-20261101/budget/live-ledger.jsonl"
    budget = REPO / "docs/evidence/LOCAL-R1-20261101/budget/budget.json"
    ledger_lines = [line for line in ledger.read_text(encoding="utf-8").splitlines() if line.strip()]
    payload = {
        "schema_version": "p2-h2v3-go-amend/v0.1",
        "authorization": {
            "owner_total_requests": 1500,
            "cumulative_used": 961,
            "complete_four_runs_need": 185,
            "lower_bound": 961 + 185,
            "chosen": 1150,
            "within_owner_cap": 1150 <= 1500,
            "headroom_after_four_runs": 1150 - (961 + 185),
        },
        "money_untouched": {
            "budget_total_limit_cny": 40.0,
            "ledger_accounted_cny": 22.22373629999994,
            "stage_p2_live_limit_cny": 20.0,
            "stage_p2_live_accounted_cny": 7.152791800000005,
            "max_request_cny": 0.5,
            "note": "本包零真实请求：账本/预算字节未变（下方 before/after 同值）",
        },
        "ledger_before_after": {
            "file_sha256": hashlib.sha256(ledger.read_bytes()).hexdigest(),
            "lines": len(ledger_lines),
            "budget_file_sha256": hashlib.sha256(budget.read_bytes()).hexdigest(),
        },
        "files": [],
        "ok": True,
    }
    for run_index, path, archive in TARGETS:
        raw = path.read_bytes()
        before_sha = hashlib.sha256(raw).hexdigest()
        before_payload = json.loads(raw.decode("utf-8"))
        before_canon = payload_sha256(before_payload)
        count = raw.count(OLD)
        if count != 1:
            payload["ok"] = False
            payload["files"].append({"run_index": run_index, "path": str(path.relative_to(REPO)),
                                     "error": f"unexpected max_requests occurrence count {count}"})
            continue
        if archive.exists():
            payload["ok"] = False
            payload["files"].append({"run_index": run_index, "archive": str(archive.relative_to(REPO)),
                                     "error": "archive already exists"})
            continue
        archive.write_bytes(raw)  # 归档改前字节，不覆盖
        new_raw = raw.replace(OLD, NEW, 1)
        path.write_bytes(new_raw)
        after_payload = json.loads(new_raw.decode("utf-8"))
        diff = leaf_diff(before_payload, after_payload)
        payload["files"].append(
            {
                "run_index": run_index,
                "go_path": str(path.relative_to(REPO)),
                "archive_path": str(archive.relative_to(REPO)),
                "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                "before": {
                    "file_sha256": before_sha,
                    "payload_sha256": before_canon,
                    "bytes": len(raw),
                    "scope_max_requests": before_payload["scope"]["max_requests"],
                    "plan_id": before_payload["scope"]["plan_id"],
                    "plan_sha256": before_payload["scope"]["plan_sha256"],
                },
                "after": {
                    "file_sha256": hashlib.sha256(new_raw).hexdigest(),
                    "payload_sha256": payload_sha256(after_payload),
                    "bytes": len(new_raw),
                    "scope_max_requests": after_payload["scope"]["max_requests"],
                },
                "leaf_diff": diff,
                "only_max_requests_changed": diff == [
                    {"path": "scope.max_requests", "before": 1137, "after": 1150}
                ],
            }
        )
        if len(diff) != 1 or diff[0]["path"] != "scope.max_requests":
            payload["ok"] = False
    out = Path(r"D:\mktkb-p2-h2v3-20261115\diag\go-amend-evidence.json")
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"ok": payload["ok"], "files": [
        {"run": f["run_index"], "only": f.get("only_max_requests_changed"),
         "before": f.get("before", {}).get("payload_sha256"),
         "after": f.get("after", {}).get("payload_sha256")} for f in payload["files"]],
        "ledger": payload["ledger_before_after"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

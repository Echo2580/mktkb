"""把 repro-pre.json / repro-after.json 归并成一份“改前 / 改后”对照（机读 + 人读）。

只搬白名单字段，不含题面以外的任何自由文本（这里的合成问句是本包自建的复现输入，
不是真实 H2 题面）。
"""

from __future__ import annotations

import json
import pathlib

EVIDENCE = pathlib.Path(r"D:\GPT项目\市场部AI知识库\docs\reports\OBS-EVAL\P2\H2V3\fix-2\evidence")
FIELDS = ("mode", "reason", "clarification_present", "enumerate", "filters", "field_role", "rag_owns_turn")
GROUPS = {
    "A_insufficient": "A 正例：信息足够（2 店 × 1 物品 + 记录字段），却含“资料”字样/非量化回指词",
    "A_ambiguous": "A 反例：真歧义（两店两物品交叉 / 纯指代 / 词表外门店）",
    "B_answerable": "B 正例：首轮显式门店+物品、字段措辞不在词表",
    "B_uncovered": "B 反例：门店不在词表（未知门店面）",
    "B_followup_collapse": "B 反例：追问（无显式实体）仍走正文检索，不被首轮修复影响",
}


def main() -> int:
    pre = json.loads((EVIDENCE / "repro-pre.json").read_text(encoding="utf-8"))
    post = json.loads((EVIDENCE / "repro-after.json").read_text(encoding="utf-8"))
    rows = []
    for group, label in GROUPS.items():
        for index, before in enumerate(pre.get(group, [])):
            after = post[group][index]
            question = before["question"]
            rows.append(
                {
                    "group": group,
                    "label": label,
                    "question": question,
                    "same_question": question == after["question"],
                    "before": {key: before[key] for key in FIELDS},
                    "after": {key: after[key] for key in FIELDS},
                    "changed": any(before[key] != after[key] for key in FIELDS),
                }
            )
    summary = {"groups": GROUPS, "rows": rows}
    (EVIDENCE / "repro-summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = ["# fix-2 复现对照（改前 / 改后，同一脚本同一输入）", ""]
    lines.append("| 组 | 合成问句 | 改前 | 改后 | 是否变化 |")
    lines.append("|---|---|---|---|---|")

    def render(sig: dict) -> str:
        filters = ",".join(f"{key}={value}" for key, value in sorted(sig["filters"].items())) or "—"
        return (
            f"`{sig['mode']}` / reason=`{sig['reason']}` / clar={sig['clarification_present']} / "
            f"enum={sig['enumerate']} / role=`{sig['field_role']}` / filters={filters} / kernel_owns={sig['rag_owns_turn']}"
        )

    for row in rows:
        lines.append(f"| {row['group']} | {row['question']} | {render(row['before'])} | {render(row['after'])} | {row['changed']} |")
    (EVIDENCE / "repro-summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"rows": len(rows), "changed": sum(1 for row in rows if row["changed"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

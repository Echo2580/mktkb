"""R1 文本面机制探针（保管侧；只输出布尔/计数/固定码，不回显任何正文或值）。

对每个目标 case 的每个 turn 计算：
- 问题面：长度、电话/地址/联系人/枚举/多字段词命中布尔、数字个数；
- 计划面：mode/path/enumerate/filters 键、field_role(s)（只输出码形）；
- 证据面：引用单元数、单元行键名集合、role 键名集合；
- 答案面：长度、数字个数、电话形数字布尔、地址词布尔、kind。
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

_WORK = pathlib.Path(__file__).resolve().parent
if str(_WORK) not in sys.path:
    sys.path.insert(0, str(_WORK))

import r1_safe_project as base  # noqa: E402

CODE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_:.\-]{0,40}$")
PHONE_WORDS = ("电话", "手机", "联系方式", "号码")
ADDRESS_WORDS = ("地址", "门牌")
CONTACT_WORDS = ("联系人", "负责人", "对接", "找谁")
ENUM_WORDS = ("所有", "全部", "哪些", "清单", "列出", "逐个", "一共", "分别", "各家", "每个")
MULTI_WORDS = ("和", "与", "、", "以及", "还有")
PHONE_RE = re.compile(r"(1[3-9]\d{9})|(0\d{2,3}[- ]?\d{7,8})|(\d{3,4}[- ]\d{7,8})")
DIGIT_RE = re.compile(r"\d")


def _codes(value: object) -> object:
    """只保留码形字符串；其他字符串降级为 <text>。"""
    if isinstance(value, dict):
        return {str(k): _codes(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_codes(v) for v in value]
    if isinstance(value, str):
        return value if CODE_RE.fullmatch(value) else "<text>"
    return value


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--key", required=True)
    parser.add_argument("--binding", required=True)
    parser.add_argument("--evidence-root", required=True)
    parser.add_argument("--receipt", required=True)
    parser.add_argument("--seal-manifest", required=True)
    parser.add_argument("--case-plan", required=True)
    parser.add_argument("--cases", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    guard = base.NetGuard()
    guard.install()
    guard.positive_control()

    key = pathlib.Path(args.key).read_bytes().strip()
    binding = base._read_json(pathlib.Path(args.binding))
    receipt = base._read_json(pathlib.Path(args.receipt))
    seal_manifest = base._read_json(pathlib.Path(args.seal_manifest))
    case_plan = base._read_json(pathlib.Path(args.case_plan))
    plan_rows = case_plan["cases"]
    turn_files = [
        str(t["evidence_file"]) for row in plan_rows for t in (row.get("turns") or ()) if str(t.get("status")) == "executed"
    ]
    base._verify_custody(binding, pathlib.Path(args.case_plan), case_plan, receipt, seal_manifest, pathlib.Path(args.evidence_root), turn_files)

    from mktkb.evaluation.p2_evidence_io import read_encrypted_evidence  # noqa: PLC0415

    wanted = {item.strip() for item in args.cases.split(",") if item.strip()}
    out: dict[str, object] = {}
    for row in plan_rows:
        case_id = str(row.get("case_id"))
        if case_id not in wanted:
            continue
        turns = []
        for turn in row.get("turns") or ():
            env = read_encrypted_evidence(pathlib.Path(args.evidence_root) / str(turn["evidence_file"]), key=key)
            projection = env.get("db_projection") or {}
            messages = [m for m in (projection.get("messages") or []) if isinstance(m, dict)]
            question = ""
            answer = ""
            for msg in messages:
                content = str(msg.get("text") or "")
                role = str(msg.get("role") or "")
                if role == "user" and not question:
                    question = content
                elif role == "assistant":
                    answer = content
            units = [u for u in (projection.get("units") or []) if isinstance(u, dict)]
            unit_keys: set[str] = set()
            role_keys: set[str] = set()
            raw_field_codes: dict[str, int] = {}
            entity_filter_keys: set[str] = set()
            for unit in units:
                unit_keys.update(str(k) for k in unit.keys())
                for source_key in ("role_values", "fields", "roles"):
                    data = unit.get(source_key)
                    if isinstance(data, dict):
                        role_keys.update(str(k) for k in data.keys())
                raw = unit.get("raw_fields")
                if isinstance(raw, dict):
                    for label in raw:
                        text = str(label)
                        if any(w in text for w in ("电话", "手机", "号码")):
                            code = "phone"
                        elif "地址" in text:
                            code = "address"
                        elif "联系人" in text or "负责人" in text:
                            code = "contact"
                        elif "位置" in text:
                            code = "location"
                        else:
                            code = "other"
                        raw_field_codes[code] = raw_field_codes.get(code, 0) + 1
                ef = unit.get("entity_filters")
                if isinstance(ef, dict):
                    entity_filter_keys.update(str(k) for k in ef.keys())
            events = ((env.get("capture") or {}).get("events") or [])
            plan_events = [e for e in events if str(e.get("kind")) == "plan_observed"]
            plans = []
            for event in plan_events:
                payload = event.get("payload") or {}
                filters = payload.get("filters") if isinstance(payload.get("filters"), dict) else {}
                plans.append(
                    {
                        "mode": _codes(payload.get("mode")),
                        "path": _codes(payload.get("path")),
                        "enumerate": bool(payload.get("enumerate")),
                        "as_of": bool(payload.get("as_of")),
                        "filter_keys": sorted(str(k) for k in filters),
                        "term_count": len(payload.get("terms") or []),
                    }
                )
            saved = [e for e in events if str(e.get("kind")) == "query_state_saved"]
            states = []
            for event in saved:
                state = (event.get("payload") or {}).get("state_json") or {}
                states.append(
                    {
                        "field_role": _codes(state.get("field_role")),
                        "field_roles": [_codes(x) for x in (state.get("field_roles") or [])],
                        "page": state.get("page"),
                        "has_identifier": bool(state.get("identifier")),
                        "has_store": bool(state.get("store")),
                        "has_item": bool(state.get("item")),
                        "has_doc": bool(state.get("doc_id")),
                        "channel": _codes(state.get("channel")),
                    }
                )
            turns.append(
                {
                    "turn_index": turn.get("turn_index"),
                    "question": {
                        "chars": len(question),
                        "digits": len(DIGIT_RE.findall(question)),
                        "phone_word": any(w in question for w in PHONE_WORDS),
                        "address_word": any(w in question for w in ADDRESS_WORDS),
                        "contact_word": any(w in question for w in CONTACT_WORDS),
                        "enum_word": any(w in question for w in ENUM_WORDS),
                        "multi_word": any(w in question for w in MULTI_WORDS),
                    },
                    "answer": {
                        "chars": len(answer),
                        "digits": len(DIGIT_RE.findall(answer)),
                        "phone_like": bool(PHONE_RE.search(answer)),
                        "address_word": any(w in answer for w in ADDRESS_WORDS),
                        "contact_word": any(w in answer for w in CONTACT_WORDS),
                    },
                    "citation_count": len(projection.get("message_sources") or []),
                    "unit_count": len(units),
                    "unit_keys": sorted(unit_keys)[:20],
                    "role_keys": sorted(role_keys)[:20],
                    "raw_field_codes": raw_field_codes,
                    "entity_filter_keys": sorted(entity_filter_keys),
                    "plans": plans,
                    "states": states,
                }
            )
        out[case_id] = turns

    pathlib.Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, "cases": sorted(out), "netguard": guard.as_dict()}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

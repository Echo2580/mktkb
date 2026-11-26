"""R0 角色码投影器（SAFE-only，离线，绝不出正文/中文）。

任务：为 r0 修复任务「角色码投影 + 词表补全」产出 4 组固定码投影，并给出
「能否由词表解决」的判定。**只读仓内已封存的 SAFE 证据 + 产品源码**，不读任何
私有材料（``D:\\mktkb-p2-h2v3-*``、``.env``、``*.key``、P1-HOLDOUT、任何题面/答案）。

四组投影
--------
A ``plan.field_roles``：计划请求的角色码集合（有序）。SAFE 层**未采集**
  （``02-case-boundary`` 的 ``open_questions`` 里固定码 ``field_role_not_captured``），
  只有可从计数推出的**基数**与**列数和**。
B 每个期望值所属角色码：SAFE 层只有 ``exp_role_mapped`` 计数与 ``cited_roles``
  （被引行角色表）。故给出**候选全域**（固定角色码）+ 判定式，单值仍是 ``undetermined``。
C 被引行每个角色的列数：SAFE 层未采集（``unit_rows_with_raw_fields`` 只是行数）。
  可推的只有“被请求角色列数之和 = facts 数”。
D 问句命中的字段词类（15 个固定枚举）与 ``_match_fields`` 里映射到哪个角色码：
  **这一组完全由产品源码静态决定**，逐词类给出角色码/未映射；真实问句的词类
  因 SAFE 层没有问句文本而 ``undetermined``（只有 ``plan_terms_count`` 整数）。

判定式（由 A/B/C 的 SAFE 计数强制）
------------------------------------
``facts = Σ_{r ∈ plan.field_roles} columns(r, cited_row)``。故：

- C21：``facts=1`` ⇒ 恰好 1 个被请求角色、该角色恰好 1 列；期望值缺失 ⇒
  期望角色 ∉ 该单角色集合 ⇒ 期望角色 ∈ 候选全域 \\ {该角色}（2 个候选）。
- C27：``facts=2`` ⇒ 1 角色×2 列 或 2 角色×1 列；期望值缺 1 ⇒ 同理。

词表可否解决
------------
对每个候选角色，``_match_fields`` 是否至少有一个已登记词形能请求到它（静态可算）。
若全部可达 ⇒ 缺的是**词形（paraphrase）**，而词形无法由 SAFE 证据确定 ⇒
``vocabulary_fix_not_confirmable_from_safe_layer``。

白名单
------
输出只允许：固定角色码、固定词类枚举、整数、布尔、sha256。:func:`_safe_dump` 拒绝
任何非 ASCII 字符串与未登记键，因此**结构上不可能**落盘中文。

运行::

    .venv\\Scripts\\python.exe -X utf8 r0_role_map.py
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import socket
import sys
import urllib.request
from typing import Any, Mapping, Sequence

BASE = pathlib.Path(__file__).resolve().parents[1]


def _repo_root(start: pathlib.Path) -> pathlib.Path:
    for candidate in [start, *start.parents]:
        if (candidate / "backend" / "src" / "mktkb").is_dir():
            return candidate
    raise RuntimeError("repo_root_not_found")


REPO = _repo_root(BASE)
BACKEND_SRC = REPO / "backend" / "src"
DEFAULT_OUT = BASE / "evidence" / "08-role-map"

#: SAFE 输入（全部在仓内；私有 envelope 一律不读）。
SAFE_INPUTS = {
    "case_boundary_c21": BASE / "evidence" / "02-case-boundary" / "H2V3-C21.json",
    "case_boundary_c27": BASE / "evidence" / "02-case-boundary" / "H2V3-C27.json",
    "producer_analysis": BASE / "evidence" / "06-postrun3" / "producer-analysis.txt",
    "safe_round_initial": BASE / "evidence" / "01-safe-projection" / "r0-current-round-initial.json",
}

#: 固定词类枚举（任务给定，15 个）。
WORD_CLASSES: tuple[str, ...] = (
    "price",
    "date",
    "time",
    "location",
    "quantity",
    "spec",
    "model",
    "size",
    "status",
    "note",
    "description",
    "phone",
    "address",
    "contact",
    "other",
)
#: 词类 -> 允许承载它的角色码（枚举定义，不是业务数据）。
CLASS_TO_ROLES: dict[str, tuple[str, ...]] = {
    "price": ("price",),
    "date": ("date", "effective_from", "effective_to"),
    "time": ("date", "effective_from", "effective_to"),
    "location": ("location",),
    "quantity": ("quantity", "issued_quantity"),
    "spec": ("spec",),
    "model": ("spec",),
    "size": ("spec", "height"),
    "status": ("status",),
    "note": ("note",),
    "description": ("note",),
    "phone": ("phone",),
    "address": ("address",),
    "contact": ("contact",),
    "other": (),
}
ENTITY_ROLES: frozenset[str] = frozenset(
    {"identifier", "store", "item", "product", "channel", "price_type", "alias", "unit"}
)
#: 本任务关注的固定角色码（此前报告已出现的 SAFE 词汇）。
FOCUS_ROLES: tuple[str, ...] = ("effective_from", "effective_to", "address", "phone")
CASES: tuple[str, ...] = ("H2V3-C21", "H2V3-C27")

#: 输出白名单键。
ALLOWED_KEYS = frozenset(
    {
        "ok",
        "error",
        "where",
        "tool",
        "tool_sha256",
        "netguard",
        "inputs",
        "name",
        "sha256",
        "cases",
        "case_id",
        "a_plan_field_roles",
        "b_expected_role",
        "c_cited_role_columns",
        "d_word_classes",
        "e_verdict",
        "facts",
        "expected",
        "missing",
        "exp_role_mapped",
        "requested_role_count",
        "requested_role_codes",
        "requested_columns_sum",
        "role_count_range",
        "lower",
        "upper",
        "expected_role",
        "candidate_universe",
        "candidate_count",
        "candidate_universe_basis",
        "excluded_by_request",
        "cited_field_roles",
        "cited_entity_roles",
        "per_role_columns",
        "total_columns",
        "enum",
        "classes",
        "mapped_class_count",
        "unmapped_classes",
        "candidate_role_coverage",
        "word_classes",
        "word_count",
        "reachable",
        "mapped_roles",
        "probe_roles",
        "question_word_classes",
        "parity_gap",
        "role",
        "gap_word_count",
        "gap_words_sha256",
        "hard_gap_word_count",
        "hard_gap_words_sha256",
        "index_word_count",
        "query_word_count",
        "verdict",
        "needed",
        "focus_roles",
        "severity",
        "code",
        "count",
        "label",
        "role_codes",
        "basis",
        "missing_evidence",
        "predicate",
        "required_requested_role_count",
        "required_columns_sum",
        "required_role_not_requested",
        "blocked_attempts",
        "positive_control_attempts",
        "positive_control_blocked",
        "outbound_allowed",
    }
)


class NetGuard:
    """socket 原语层阻断出站；只计数、不连接；正对照必须被阻断。"""

    def __init__(self) -> None:
        self.blocked = 0
        self.positive_control_attempts = 0

    def _refuse(self, *_args: Any, **_kwargs: Any) -> Any:
        self.blocked += 1
        raise OSError("netguard_blocked")

    def install(self) -> None:
        socket.socket.connect = self._refuse  # type: ignore[method-assign]
        socket.socket.connect_ex = self._refuse  # type: ignore[method-assign]
        urllib.request.urlopen = self._refuse  # type: ignore[assignment]

    def positive_control(self) -> None:
        for attempt in (
            lambda: socket.create_connection(("127.0.0.1", 9), timeout=0.05),
            lambda: urllib.request.urlopen("http://127.0.0.1:9/", timeout=0.05),
        ):
            self.positive_control_attempts += 1
            try:
                attempt()
            except OSError:
                continue
            raise RuntimeError("netguard_positive_control_failed")

    def as_dict(self) -> dict[str, Any]:
        return {
            "blocked_attempts": int(self.blocked),
            "positive_control_attempts": int(self.positive_control_attempts),
            "positive_control_blocked": bool(
                self.positive_control_attempts == 2 and self.blocked >= 2
            ),
            "outbound_allowed": 0,
        }


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _load_json(path: pathlib.Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _producer_rows(text: str) -> dict[str, dict[str, str]]:
    """把 producer-analysis.txt 解析成 {case_id: {字段: 值}}（只用于取计数）。"""
    rows: dict[str, dict[str, str]] = {}
    for line in text.splitlines():
        if not line.startswith("H2V3-C"):
            continue
        case_id, _, rest = line.partition(" ")
        fields = rows.setdefault(case_id, {})
        for token in rest.split(" "):
            if "=" in token:
                key, _, value = token.partition("=")
                fields.setdefault(key, value)
    return rows


def _producer_roles(text: str) -> dict[str, list[str]]:
    """probe2/probe4 行里的 ``cited_roles=[...]`` -> 角色码列表（同一行只取一次）。"""
    out: dict[str, list[str]] = {}
    for line in text.splitlines():
        marker = "cited_roles=["
        if not line.startswith("H2V3-C") or marker not in line:
            continue
        case_id = line.split(" ", 1)[0]
        if case_id in out:
            continue
        raw = line.split(marker, 1)[1].split("]", 1)[0]
        roles = [
            piece.strip().strip("'\"")
            for piece in raw.split(",")
            if piece.strip().strip("'\"")
        ]
        out[case_id] = roles
    return out


def _int(fields: Mapping[str, str], key: str) -> int:
    try:
        return int(str(fields.get(key, "0")))
    except (TypeError, ValueError):
        return 0


# --------------------------------------------------------------------------- #
# D 组：词表静态投影（产品源码即真值，无需私有输入）
# --------------------------------------------------------------------------- #


def _word_tables() -> dict[str, Any]:
    if str(BACKEND_SRC) not in sys.path:
        sys.path.insert(0, str(BACKEND_SRC))
    from mktkb.rag import chunking, query  # noqa: PLC0415

    return {"query": query, "chunking": chunking}


def _query_words(query_mod: Any, role: str) -> tuple[str, ...]:
    extra = getattr(query_mod, "_EXTRA_FIELD_ROLE_WORDS", {}) or {}
    return tuple(query_mod.FIELD_WORDS.get(role, ())) + tuple(extra.get(role, ()))


def _project_word_classes(query_mod: Any) -> dict[str, Any]:
    """逐词类：允许的角色码、已登记词形数、以及能否真的请求到。"""
    coverage: list[dict[str, Any]] = []
    reachable_roles: set[str] = set()
    for role in sorted({role for roles in CLASS_TO_ROLES.values() for role in roles}):
        words = _query_words(query_mod, role)
        probes: set[str] = set()
        for word in words:
            try:
                first = query_mod._match_field(word)
                multi = set(query_mod._match_fields(word))
            except Exception:  # noqa: BLE001 - 探测失败只记为不可达
                continue
            if first:
                probes.add(str(first))
            probes |= {str(item) for item in multi}
            if role in probes:
                break
        coverage.append(
            {
                "role": role,
                "word_count": len(words),
                "reachable": bool(role in probes),
                "probe_roles": sorted(probes),
            }
        )
        if role in probes:
            reachable_roles.add(role)

    classes: list[dict[str, Any]] = []
    for word_class in WORD_CLASSES:
        roles = CLASS_TO_ROLES[word_class]
        mapped = [role for role in roles if role in reachable_roles]
        classes.append(
            {
                "word_classes": [word_class],
                "role_codes": list(roles),
                "mapped_roles": mapped,
                "reachable": bool(mapped),
            }
        )
    unmapped = [row["word_classes"][0] for row in classes if not row["reachable"]]
    return {
        "enum": list(WORD_CLASSES),
        "classes": classes,
        "mapped_class_count": len(WORD_CLASSES) - len(unmapped),
        "unmapped_classes": unmapped,
        "candidate_role_coverage": coverage,
        "question_word_classes": "undetermined",
        "basis": "static_product_source",
        "missing_evidence": ["question_text_not_in_safe_layer", "plan_terms_count_only"],
    }


def _project_parity(query_mod: Any, chunking_mod: Any) -> list[dict[str, Any]]:
    """索引侧表头词 -> 角色 vs 问句侧已登记词形：差集只出计数与 sha256。

    两个层级：
    - ``gap_word_count``：索引侧有、问句侧表里没有的词形数（子串匹配可能仍能救回来）；
    - ``hard_gap_word_count``：连**自身**都请求不到该角色的词形数（真正的词表洞）。
    """
    rows: list[dict[str, Any]] = []
    for role in sorted(chunking_mod.ROLE_SYNONYMS):
        if role in ENTITY_ROLES:
            continue
        index_words = {str(word) for word in chunking_mod.ROLE_SYNONYMS.get(role, ())}
        query_words = {str(word) for word in _query_words(query_mod, role)}
        gap = sorted(index_words - query_words)
        hard: list[str] = []
        for word in gap:
            try:
                reached = set(query_mod._match_fields(word)) | {query_mod._match_field(word)}
            except Exception:  # noqa: BLE001 - 探测失败按不可请求处理
                reached = set()
            if role not in reached:
                hard.append(word)
        rows.append(
            {
                "role": str(role),
                "index_word_count": len(index_words),
                "query_word_count": len(query_words),
                "gap_word_count": len(gap),
                "gap_words_sha256": _sha256_bytes("\x00".join(gap).encode("utf-8")),
                "hard_gap_word_count": len(hard),
                "hard_gap_words_sha256": _sha256_bytes("\x00".join(sorted(hard)).encode("utf-8")),
            }
        )
    return rows


# --------------------------------------------------------------------------- #
# A/B/C 组
# --------------------------------------------------------------------------- #


def _project_case(
    case_id: str,
    boundary: Mapping[str, Any],
    producer: Mapping[str, str],
    roles: Sequence[str],
) -> dict[str, Any]:
    facts = _int(producer, "facts")
    expected = _int(producer, "expected")
    missing = max(expected - _int(producer, "exp_in_commit"), 0)
    exp_role_mapped = _int(producer, "exp_role_mapped")
    cited_field = [role for role in roles if role not in ENTITY_ROLES]
    cited_entity = [role for role in roles if role in ENTITY_ROLES]

    # A：facts = Σ 被请求角色在行内的列数 ⇒ facts=1 时角色数必为 1（且 1 列）。
    if facts >= 1:
        role_count_lower, role_count_upper = 1, facts
        requested_role_count: Any = 1 if facts == 1 else {
            "lower": role_count_lower,
            "upper": role_count_upper,
        }
    else:
        requested_role_count = "undetermined"

    # B：期望角色 ∈ 被引行角色表；缺的那一条一定不属于被请求集合。
    candidates = list(cited_field)
    if facts == 1 and len(candidates) > 1:
        excluded_by_request = {
            "lower": 1,
            "upper": 1,
            "basis": "facts_eq_one_implies_single_requested_role",
        }
    else:
        excluded_by_request = {
            "lower": 1,
            "upper": min(facts, len(candidates)),
            "basis": "facts_eq_requested_columns_sum",
        }

    # C：被引行逐角色列数未采集；可推的只有被请求角色列数之和 = facts。
    return {
        "case_id": case_id,
        "facts": facts,
        "expected": expected,
        "missing": missing,
        "exp_role_mapped": exp_role_mapped,
        "a_plan_field_roles": {
            "requested_role_codes": "undetermined",
            "requested_role_count": requested_role_count,
            "requested_columns_sum": facts,
            "role_count_range": {"lower": role_count_lower, "upper": role_count_upper}
            if facts >= 1
            else "undetermined",
            "basis": "facts_eq_requested_columns_sum",
            "missing_evidence": ["plan_observed_field_roles_not_captured"],
        },
        "b_expected_role": {
            "expected_role": "undetermined",
            "candidate_universe": candidates,
            "candidate_count": len(candidates),
            "candidate_universe_basis": "cited_roles_probe2_probe4",
            "excluded_by_request": excluded_by_request,
            "missing_evidence": ["expected_value_field_role_not_captured"],
        },
        "c_cited_role_columns": {
            "cited_field_roles": candidates,
            "cited_entity_roles": cited_entity,
            "per_role_columns": "undetermined",
            "total_columns": "undetermined",
            "requested_columns_sum": facts,
            "basis": "unit_rows_with_raw_fields_counts_rows_not_columns",
            "missing_evidence": ["cited_unit_raw_fields_not_captured"],
        },
        "predicate": {
            "required_requested_role_count": 1 if facts == 1 else "undetermined",
            "required_columns_sum": facts,
            "required_role_not_requested": max(len(candidates) - facts, 0),
        },
    }


def _coverage_of(word: Mapping[str, Any], role: str) -> bool:
    for row in word.get("candidate_role_coverage", []):
        if row.get("role") == role:
            return bool(row.get("reachable"))
    return False


def _safe_dump(value: Any, *, path: str = "$") -> Any:
    """白名单 + ASCII 强校验：非 ASCII 字符串一律拒绝（结构上不可能落中文）。"""
    if isinstance(value, bool) or isinstance(value, int):
        return value
    if isinstance(value, str):
        if not value.isascii():
            raise ValueError(f"non_ascii_string@{path}")
        if value.startswith("sha256:"):
            return value
        return value
    if value is None:
        return "none"
    if isinstance(value, list):
        return [_safe_dump(item, path=f"{path}[]") for item in value]
    if isinstance(value, Mapping):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str) or not key.isascii() or key not in ALLOWED_KEYS:
                raise ValueError(f"key_not_allowed@{path}:{key}")
            out[key] = _safe_dump(item, path=f"{path}.{key}")
        return out
    raise ValueError(f"type_not_allowed@{path}")


def _write_text(path: pathlib.Path, payload: Mapping[str, Any]) -> None:
    lines: list[str] = []
    for key, value in payload.items():
        lines.append(f"{key}={json.dumps(value, ensure_ascii=True, sort_keys=True)}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build(out_dir: pathlib.Path) -> dict[str, Any]:
    guard = NetGuard()
    guard.install()
    guard.positive_control()

    inputs: list[dict[str, Any]] = []
    loaded: dict[str, Any] = {}
    for name, path in SAFE_INPUTS.items():
        data = path.read_bytes()
        inputs.append({"name": name, "sha256": _sha256_bytes(data)})
        if path.suffix == ".json":
            loaded[name] = json.loads(data.decode("utf-8"))
        else:
            loaded[name] = data.decode("utf-8")

    producer = _producer_rows(loaded["producer_analysis"])
    cited = _producer_roles(loaded["producer_analysis"])
    tables = _word_tables()
    query_mod = tables["query"]

    cases: list[dict[str, Any]] = []
    for case_id in CASES:
        boundary_key = "case_boundary_c21" if case_id.endswith("21") else "case_boundary_c27"
        cases.append(
            _project_case(
                case_id,
                loaded[boundary_key],
                producer.get(case_id, {}),
                cited.get(case_id, []),
            )
        )

    word = _project_word_classes(query_mod)
    parity = _project_parity(query_mod, tables["chunking"])

    focus_reachable = {
        role: _coverage_of(word, role) for role in FOCUS_ROLES
    }
    candidates_all = sorted({role for case in cases for role in case["b_expected_role"]["candidate_universe"]})
    candidates_reachable = {role: _coverage_of(word, role) for role in candidates_all}
    vocabulary_confirmable = not (
        all(focus_reachable.values()) and all(candidates_reachable.values())
    )
    verdict = {
        "verdict": "vocabulary_fix_not_confirmable_from_safe_layer"
        if not vocabulary_confirmable
        else "vocabulary_gap_confirmed_offline",
        "focus_roles": list(FOCUS_ROLES),
        "role_codes": candidates_all,
        "needed": [
            "plan_observed_field_roles_capture",
            "question_field_word_class_capture",
            "expected_value_field_role_capture",
        ],
        "basis": "candidate_roles_all_reachable_so_gap_is_word_form_not_role_table"
        if not vocabulary_confirmable
        else "candidate_role_unreachable",
    }

    payload: dict[str, Any] = {
        "ok": True,
        "tool": "r0_role_map",
        "inputs": inputs,
        "netguard": guard.as_dict(),
        "cases": cases,
        "d_word_classes": word,
        "parity_gap": parity,
        "e_verdict": verdict,
    }
    safe = _safe_dump(payload)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "role-map.json").write_text(
        json.dumps(safe, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    _write_text(out_dir / "role-map.txt", {
        "ok": safe["ok"],
        "netguard": safe["netguard"],
        "cases": [
            {
                "case_id": case["case_id"],
                "facts": case["facts"],
                "expected": case["expected"],
                "missing": case["missing"],
                "requested_role_codes": case["a_plan_field_roles"]["requested_role_codes"],
                "requested_role_count": case["a_plan_field_roles"]["requested_role_count"],
                "expected_role": case["b_expected_role"]["expected_role"],
                "candidate_universe": case["b_expected_role"]["candidate_universe"],
                "per_role_columns": case["c_cited_role_columns"]["per_role_columns"],
                "predicate": case["predicate"],
            }
            for case in safe["cases"]
        ],
        "mapped_class_count": safe["d_word_classes"]["mapped_class_count"],
        "unmapped_classes": safe["d_word_classes"]["unmapped_classes"],
        "candidate_role_coverage": safe["d_word_classes"]["candidate_role_coverage"],
        "verdict": safe["e_verdict"],
    })
    tool_path = pathlib.Path(__file__).resolve()
    (out_dir / "sha256sums.txt").write_text(
        "\n".join(
            [
                f"{_sha256_bytes(tool_path.read_bytes())}  r0_role_map.py",
                f"{_sha256_bytes((out_dir / 'role-map.json').read_bytes())}  role-map.json",
                f"{_sha256_bytes((out_dir / 'role-map.txt').read_bytes())}  role-map.txt",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return safe


def main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT))
    args = parser.parse_args(list(argv))
    try:
        safe = build(pathlib.Path(args.out_dir))
    except Exception:  # noqa: BLE001 - 只出固定码，不打印异常文本
        print(json.dumps({"ok": False, "error": "role_map_failed", "where": "build"}, ensure_ascii=True))
        return 2
    print(
        json.dumps(
            {
                "ok": bool(safe.get("ok")),
                "cases": [
                    {
                        "case_id": case["case_id"],
                        "facts": case["facts"],
                        "requested_role_codes": case["a_plan_field_roles"]["requested_role_codes"],
                        "requested_role_count": case["a_plan_field_roles"]["requested_role_count"],
                        "expected_role": case["b_expected_role"]["expected_role"],
                        "candidate_universe": case["b_expected_role"]["candidate_universe"],
                        "per_role_columns": case["c_cited_role_columns"]["per_role_columns"],
                    }
                    for case in safe["cases"]
                ],
                "mapped_class_count": safe["d_word_classes"]["mapped_class_count"],
                "unmapped_classes": safe["d_word_classes"]["unmapped_classes"],
                "verdict": safe["e_verdict"]["verdict"],
            },
            ensure_ascii=True,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

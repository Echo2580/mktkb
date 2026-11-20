"""R2-203C F4：R2 集合恒等式（离线）+「多一题/少一题/重复题/换题」四种变异负例。

只读公开件 ``docs/reports/OBS-EVAL/P2/H2V3/fullverify-20261116/run/r2-final/case-plan.json``
（不复制题面/期望值，只读结构与计数）。断言：

- 案例集合恰好 ``{C08, C14, C19, C25, C29}``（原始 id 形如 ``H2V3-C##``）；
- 回合总数 6，``turn_index`` 全局连续 0..5 且唯一；
- ``C14`` 恰 2 回合；
- 业务日 == ``2026-11-20``（``run_binding.business_date``）。

变异负例：把同一份公开件的副本分别改成"多一题/少一题/重复题/换题"，必须被**公开校验入口**
（``tools/p2_h2_controlled_execute.py::_validate_case_plan_document``，即产出该文件的同一校验器）
拒绝为 ``case_plan_coverage_invalid``；未被变异的那份必须通过同一校验器（证明拒绝不是因为
"怎么改都拒绝"）。冻结期望 ``{case_id: 回合数}`` 在测试里**显式声明**，不从被检文件反推。
"""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

_TESTS_ROOT = Path(__file__).resolve().parents[1]
if str(_TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_TESTS_ROOT))
from acceptance.support.netguard import t09_network_guard  # noqa: E402,F401  (pytest fixture)

from mktkb.evaluation.dataset import CaseSpec  # noqa: E402
from mktkb.evaluation.product_adapter import case_questions  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]
CASE_PLAN = (
    REPO_ROOT
    / "docs"
    / "reports"
    / "OBS-EVAL"
    / "P2"
    / "H2V3"
    / "fullverify-20261116"
    / "run"
    / "r2-final"
    / "case-plan.json"
)
TOOL = REPO_ROOT / "tools" / "p2_h2_controlled_execute.py"

#: R2 冻结期望（显式声明；不读被检文件反推）。
EXPECTED_CASES: tuple[tuple[str, int], ...] = (
    ("H2V3-C08", 1),
    ("H2V3-C14", 2),
    ("H2V3-C19", 1),
    ("H2V3-C25", 1),
    ("H2V3-C29", 1),
)
EXPECTED_SHORT_IDS = {"C08", "C14", "C19", "C25", "C29"}
EXPECTED_TURN_TOTAL = 6
EXPECTED_BUSINESS_DATE = "2026-11-20"


def _witness(tag: str, **fields: object) -> None:
    print("WITNESS " + json.dumps({"tag": tag, **fields}, ensure_ascii=False, sort_keys=True))


def _payload() -> dict:
    assert CASE_PLAN.is_file(), f"公开件缺失：{CASE_PLAN}"
    return json.loads(CASE_PLAN.read_text(encoding="utf-8"))


def _short(case_id: str) -> str:
    return str(case_id).split("-", 1)[1] if "-" in str(case_id) else str(case_id)


def _stub_cases() -> list[CaseSpec]:
    """按冻结期望造最小 CaseSpec（只要 case_id 与回合数；不含任何题面）。

    ``case_questions`` 的口径：``turns`` 少于 2 条时按单轮（用 ``question``）；达到 2 条时
    逐条就是该 case 全部用户轮。所以 2 回合的 case 要显式给 2 条占位轮。
    """
    stubs: list[CaseSpec] = []
    for case_id, turns in EXPECTED_CASES:
        stubs.append(
            CaseSpec(
                case_id=case_id,
                suite="p2-holdout",
                split="holdout",
                stratum="paraphrase",
                business_date=EXPECTED_BUSINESS_DATE,
                question="合成占位问题",
                turns=tuple(
                    {"role": "user", "question": f"合成占位轮{i}"} for i in range(1, turns + 1)
                )
                if turns >= 2
                else (),
                expected_values=(),
                expected_sources=(),
                relevant_units=(),
                should_refuse=False,
                labeler="synthetic-fixture",
                label_version="synthetic-v1",
            )
        )
    return stubs


@pytest.fixture(scope="module")
def tool() -> ModuleType:
    """按路径加载公开受控执行工具（只取其中的 case-plan 校验器）。"""
    assert TOOL.is_file(), f"公开工具缺失：{TOOL}"
    spec = importlib.util.spec_from_file_location("r2c_p2_h2_controlled_execute", TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # 必须先登记到 sys.modules：该工具的 dataclass 用 postponed 注解，dataclasses 解析
    # 字符串注解时要按模块名回查命名空间，否则 AttributeError（与本模块行为无关）。
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _validate(tool: ModuleType, payload: dict) -> dict:
    return tool._validate_case_plan_document(  # noqa: SLF001 - 公开工具的同一校验器
        payload,
        cases=_stub_cases(),
        static_bindings={},
        run_binding=None,
        require_binding_match=False,
    )


# --------------------------------------------------------------------------- #
# 正例：集合恒等式 + 公开校验器通过
# --------------------------------------------------------------------------- #


def test_f4_r2_case_plan_identity_over_public_artifact(t09_network_guard) -> None:
    payload = _payload()
    rows = list(payload["cases"])
    ids = [str(row["case_id"]) for row in rows]
    turn_counts = {str(row["case_id"]): len(row["turns"]) for row in rows}
    indices = [int(turn["turn_index"]) for row in rows for turn in row["turns"]]
    statuses = {str(row["case_id"]): str(row["quality_status"]) for row in rows}
    _witness(
        "f4-1-case-plan",
        schema_version=payload.get("schema_version"),
        execution_mode=payload.get("execution_mode"),
        fixture_kind=payload.get("fixture_kind"),
        business_date=(payload.get("run_binding") or {}).get("business_date"),
        case_ids=ids,
        short_ids=sorted(_short(item) for item in ids),
        turn_counts=turn_counts,
        turn_indices=indices,
        quality_status=statuses,
        real_calls=payload.get("real_calls"),
    )

    # (1) 题数/集合：恰好 5 题，集合逐项相等（多一题/少一题/换题都会破坏）。
    assert len(rows) == len(EXPECTED_CASES), ids
    assert len(set(ids)) == len(ids), ids
    assert set(ids) == {case_id for case_id, _ in EXPECTED_CASES}, ids
    assert set(_short(item) for item in ids) == EXPECTED_SHORT_IDS, ids

    # (2) 回合数：总数 6；每题的回合数与冻结期望逐项相等（C14 恰 2 回合）。
    assert sum(turn_counts.values()) == EXPECTED_TURN_TOTAL, turn_counts
    assert turn_counts == dict(EXPECTED_CASES), turn_counts
    assert turn_counts["H2V3-C14"] == 2, turn_counts
    # 回合编号全局连续且唯一（不重排/不重号）。
    assert indices == list(range(EXPECTED_TURN_TOTAL)), indices
    # 每个已执行回合都有独立的证据文件。
    files = [str(turn["evidence_file"]) for row in rows for turn in row["turns"] if turn["status"] == "executed"]
    assert len(files) == len(set(files)), files

    # (3) 业务日：显式 2026-11-20（R2 业务日）。
    assert (payload.get("run_binding") or {}).get("business_date") == EXPECTED_BUSINESS_DATE, payload.get(
        "run_binding"
    )
    # 该文件是 live 形态（不是 local_mock 占位）。
    assert payload.get("fixture_kind") == "live_h2", payload.get("fixture_kind")
    assert payload.get("schema_version") == "p2-hard-evidence-caseplan-live/v0.1", payload.get("schema_version")
    assert (payload.get("bindings") or {}).get("fixture_kind") == "live_h2", payload.get("bindings")
    assert t09_network_guard.snapshot()["external"] == []


def test_f4_public_validator_accepts_unmutated_case_plan(tool: ModuleType, t09_network_guard) -> None:
    """对照：未变异的那份必须通过同一校验器（证明下面的拒绝来自变异本身）。"""
    normalized = _validate(tool, _payload())
    assert [row["case_id"] for row in normalized["cases"]] == [case_id for case_id, _ in EXPECTED_CASES]
    assert [len(row["turns"]) for row in normalized["cases"]] == [turns for _, turns in EXPECTED_CASES]
    _witness(
        "f4-2-validator-accepts",
        case_ids=[row["case_id"] for row in normalized["cases"]],
        turn_counts=[len(row["turns"]) for row in normalized["cases"]],
    )
    assert t09_network_guard.snapshot()["external"] == []


# --------------------------------------------------------------------------- #
# 负例：四种变异必须全部被检出
# --------------------------------------------------------------------------- #


def _mutate_extra(payload: dict) -> dict:
    """多一题：追加第 6 题（同一回合形态）。"""
    payload["cases"].append(copy.deepcopy(payload["cases"][-1]))
    payload["cases"][-1]["case_id"] = "H2V3-C30"
    payload["cases"][-1]["turns"] = [dict(payload["cases"][-1]["turns"][0], turn_index=EXPECTED_TURN_TOTAL)]
    return payload


def _mutate_missing(payload: dict) -> dict:
    """少一题：删掉最后一题。"""
    payload["cases"].pop()
    return payload


def _mutate_duplicate(payload: dict) -> dict:
    """重复题：把第 2 题换成第 1 题的副本（集合里少一题、多一重复）。"""
    payload["cases"][1] = copy.deepcopy(payload["cases"][0])
    return payload


def _mutate_swapped(payload: dict) -> dict:
    """换题：把第 1 题换成一个不在冻结集合里的 case_id。"""
    payload["cases"][0]["case_id"] = "H2V3-C99"
    return payload


@pytest.mark.parametrize(
    ("name", "mutate"),
    [
        ("extra_case", _mutate_extra),
        ("missing_case", _mutate_missing),
        ("duplicate_case", _mutate_duplicate),
        ("swapped_case", _mutate_swapped),
    ],
)
def test_f4_case_set_mutations_are_all_rejected(
    tool: ModuleType, t09_network_guard, name: str, mutate
) -> None:
    payload = mutate(_payload())
    with pytest.raises(tool.EntryError) as excinfo:
        _validate(tool, payload)
    message = str(excinfo.value)
    _witness(
        "f4-3-mutation-rejected",
        mutation=name,
        error=message,
        case_ids=[str(row["case_id"]) for row in payload["cases"]],
    )
    assert "case_plan_coverage_invalid" in message, message
    # 变异后的集合确实与冻结期望不同（负例本身有效，不是空操作）。
    assert [str(row["case_id"]) for row in payload["cases"]] != [case_id for case_id, _ in EXPECTED_CASES]
    assert t09_network_guard.snapshot()["external"] == []

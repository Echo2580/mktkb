"""P2 H2 文档级禁源判定 + 离线重建可信来源身份（合成数据、零请求、不碰真实材料）。

覆盖两处缺口：

- **缺口 A**：C27/C29 的冻结禁源引用只给 ``doc_code``（无 ``unit_key``/``locator``）。
  修复前 ``_ref_matches_unit`` 直接返回 ``None``，于是纯文档引用永远落
  ``forbidden_source_unmappable``。这里用合成 source map + 合成场景入库映射，逐值核对
  “同文档同版本 = 违规 / 可靠跨版本或异文档 = 排除 / 缺版本·缺映射 = unknown”。
- **缺口 B**：受控离线重算入口必须把冻结 source map（v0.2）+ 本场景 ingest 映射派生成
  的可信身份传进评分，并把“原运行代码/计划身份”与“派生评分器身份”分列记录。

约束：只读公开冻结文件（source map / 场景契约），不读真实题面/标签/密文/key；不发起任何
网络或供应商调用（``t09_network_guard`` 全程生效）。
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

_TESTS_DIR = Path(__file__).resolve().parents[1]
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))
_EVALUATION_TESTS = Path(__file__).resolve().parent
if str(_EVALUATION_TESTS) not in sys.path:
    sys.path.insert(0, str(_EVALUATION_TESTS))

from acceptance.support.netguard import t09_network_guard  # noqa: E402,F401

from mktkb.evaluation import p2_hard_evidence as hard  # noqa: E402
from mktkb.evaluation.p2_holdout_plan import build_holdout_plan  # noqa: E402
from mktkb.evaluation.product_adapter import IngestSource, P2IngestPlan  # noqa: E402

from test_p2_hard_evidence import _one_case, _single, build_evidence, make_audit  # noqa: E402

pytestmark = pytest.mark.usefixtures("t09_network_guard")

ROOT = Path(__file__).resolve().parents[3]
TOOL_PATH = ROOT / "tools" / "p2_h2_controlled_execute.py"
V3_SOURCE_MAP = ROOT / "docs" / "evaluation" / "p2-holdout-v3.source-map.json"

#: 合成文档名 -> 代号映射：与冻结 source map 的 (base_doc_code, version_number) 逐值对应。
DOCUMENT_CODES = {
    "synthetic-old.xlsx": "D01",
    "synthetic-old": "D01",
    "synthetic-v1.xlsx": "V03",          # 同一 base_doc_code=D01，版本 1（跨版本）
    "synthetic-current.xlsx": "V04",     # D01 / 3
    "synthetic-other.xlsx": "D02",       # 另一个文档
    "synthetic-other-new.xlsx": "V06",   # D02 / 2
}


def synthetic_identity(
    source_map: dict[str, dict[str, Any]] | None = None,
    document_codes: dict[str, str] | None = None,
) -> hard.ForbiddenSourceIdentity:
    return hard.ForbiddenSourceIdentity(
        source_map=source_map
        if source_map is not None
        else {
            "D01": {"base_doc_code": "D01", "version_number": 2},
            "V03": {"base_doc_code": "D01", "version_number": 1},
            "V04": {"base_doc_code": "D01", "version_number": 3},
            "D02": {"base_doc_code": "D02", "version_number": 1},
            "V06": {"base_doc_code": "D02", "version_number": 2},
        },
        document_codes=document_codes if document_codes is not None else dict(DOCUMENT_CODES),
    )


def classify_with_identity(
    case: Any,
    evidence: dict[str, Any],
    *,
    identity: hard.ForbiddenSourceIdentity | None = None,
    annotation: Any | None = None,
) -> Any:
    return hard.classify_case_evidence(
        case,
        annotation if annotation is not None else _single(case),
        make_audit(case, evidence),
        source_identity=identity if identity is not None else synthetic_identity(),
    )


def doc_only_case(**overrides: Any) -> Any:
    """C27/C29 形状：冻结禁源引用只有文档代号，没有 unit_key / locator。"""
    return _one_case(forbidden_sources=({"doc_code": "D01"},), **overrides)


# --------------------------------------------------------------------------- #
# 缺口 A：纯文档引用的逐值身份判定
# --------------------------------------------------------------------------- #


def test_doc_only_ref_same_document_same_version_is_violation() -> None:
    """修复前：unknown/forbidden_source_unmappable；修复后：forbidden_source_used。"""
    case = doc_only_case()
    evidence = build_evidence(
        units=[{"document_name": "synthetic-old.xlsx", "version_number": 2}]
    )
    verdict = classify_with_identity(case, evidence).axis("safety")
    assert verdict.state == "violation"
    assert verdict.reason == "forbidden_source_used"


@pytest.mark.parametrize(
    ("document_name", "version_number", "expected_state"),
    [
        ("synthetic-old.xlsx", 2, "violation"),
        ("synthetic-old", 2, "violation"),
        ("synthetic-v1.xlsx", 1, "not_applicable"),        # 同 base、跨版本 -> 排除
        ("synthetic-current.xlsx", 3, "not_applicable"),   # 同 base、跨版本 -> 排除
        ("synthetic-other.xlsx", 1, "not_applicable"),     # 其他文档 -> 排除
        ("synthetic-other-new.xlsx", 2, "not_applicable"),
        ("synthetic-unmapped.xlsx", 2, "unknown"),         # 文档名无映射 -> 不猜
        ("synthetic-old.xlsx", 0, "unknown"),              # 版本不合法 -> 不猜
    ],
)
def test_doc_only_ref_identity_matrix(document_name, version_number, expected_state) -> None:
    case = doc_only_case()
    evidence = build_evidence(
        units=[{"document_name": document_name, "version_number": version_number}]
    )
    verdict = classify_with_identity(case, evidence).axis("safety")
    assert verdict.state == expected_state
    if expected_state == "violation":
        assert verdict.reason == "forbidden_source_used"
    if expected_state == "unknown":
        assert verdict.reason == "forbidden_source_unmappable"


def test_doc_only_ref_with_undeclared_code_stays_unknown() -> None:
    case = _one_case(forbidden_sources=({"doc_code": "V99"},))
    evidence = build_evidence(
        units=[{"document_name": "synthetic-old.xlsx", "version_number": 2}]
    )
    verdict = classify_with_identity(case, evidence).axis("safety")
    assert verdict.state == "unknown"
    assert verdict.reason == "forbidden_source_unmappable"


def test_doc_only_ref_without_identity_stays_unknown() -> None:
    """调用方没给可信身份时，纯文档引用必须 fail closed（不得按文件名相似猜）。"""
    case = doc_only_case()
    evidence = build_evidence(
        units=[{"document_name": "synthetic-old.xlsx", "version_number": 2}]
    )
    result = hard.classify_case_evidence(case, _single(case), make_audit(case, evidence))
    verdict = result.axis("safety")
    assert verdict.state == "unknown"
    assert verdict.reason == "forbidden_source_unmappable"


def test_document_name_mapping_conflict_stays_unknown() -> None:
    """同一文档名在同一张映射里指向两个码：不可任选其一（冲突即 unknown）。"""
    identity = synthetic_identity(
        document_codes={**DOCUMENT_CODES, "synthetic-old.xlsx": "V03"}
    )
    case = doc_only_case()
    evidence = build_evidence(
        units=[{"document_name": "synthetic-old.xlsx", "version_number": 2}]
    )
    # 原样键 -> V03、去扩展名键 -> D01：两个码冲突，不能因为“其中一个正好命中”就判违规。
    verdict = classify_with_identity(case, evidence, identity=identity).axis("safety")
    assert verdict.state == "unknown"
    assert verdict.reason == "forbidden_source_unmappable"


def test_positioned_ref_semantics_are_not_relaxed() -> None:
    """带 locator/unit_key 的引用仍走定位语义：定位不命中不得被身份相等补成命中。"""
    locator = {"sheet": "合成表", "row": 8}
    located_case = _one_case(
        forbidden_sources=({"doc_code": "D01", "locator": locator},)
    )
    mismatched = build_evidence(
        units=[
            {
                "document_name": "synthetic-old.xlsx",
                "version_number": 2,
                "locator": {"sheet": "合成表", "row": 9},
            }
        ]
    )
    verdict = classify_with_identity(located_case, mismatched).axis("safety")
    assert verdict.state != "violation"

    hit = build_evidence(
        units=[
            {
                "document_name": "synthetic-old.xlsx",
                "version_number": 2,
                "locator": dict(locator),
            }
        ]
    )
    verdict = classify_with_identity(located_case, hit).axis("safety")
    assert verdict.state == "violation"
    assert verdict.reason == "forbidden_source_used"

    # 定位命中但版本对不上：仍要排除（身份是定位之后的追加核对，不是替代）。
    cross_version = build_evidence(
        units=[
            {
                "document_name": "synthetic-current.xlsx",
                "version_number": 3,
                "locator": dict(locator),
            }
        ]
    )
    verdict = classify_with_identity(located_case, cross_version).axis("safety")
    assert verdict.state != "violation"

    keyed = _one_case(
        forbidden_sources=({"doc_code": "D01", "unit_key": "key:unit-1"},)
    )
    matched = build_evidence(
        units=[
            {
                "unit_id": "unit-1",
                "document_name": "synthetic-old.xlsx",
                "version_number": 2,
            }
        ]
    )
    verdict = classify_with_identity(keyed, matched).axis("safety")
    assert verdict.state == "violation"
    assert verdict.reason == "forbidden_source_used"

    keyed = _one_case(
        forbidden_sources=({"doc_code": "D01", "unit_key": "key:unit-1"},)
    )
    matched = build_evidence(
        units=[
            {
                "unit_id": "unit-1",
                "document_name": "synthetic-old.xlsx",
                "version_number": 2,
            }
        ]
    )
    verdict = classify_with_identity(keyed, matched).axis("safety")
    assert verdict.state == "violation"
    assert verdict.reason == "forbidden_source_used"


@pytest.mark.parametrize(
    "layer",
    ["model_evidence", "direct_rag_fact", "direct_rag_citation", "final_citation"],
)
def test_four_use_layers_are_all_covered(layer: str) -> None:
    """模型证据 / 直答事实 / 直答引用 / 最终引用：任一层真实使用都要判违规。"""
    case = doc_only_case()
    units = [
        {
            "unit_id": "unit-1",
            "document_name": "synthetic-old.xlsx",
            "version_number": 2,
        }
    ]
    if layer == "model_evidence":
        evidence = build_evidence(
            units=units, used_unit_ids=[], model_evidence=["unit-1"], final_source_ids=[]
        )
    elif layer == "final_citation":
        evidence = build_evidence(
            units=units, used_unit_ids=[], model_evidence=[], final_source_ids=["unit-1"]
        )
    elif layer == "direct_rag_fact":
        evidence = build_evidence(
            units=units,
            used_unit_ids=[],
            use_model=False,
            final_source_ids=[],
            plan={"path": "rag"},
            direct_rag={"cited_unit_ids": [], "facts": [{"source_unit_id": "unit-1"}]},
        )
    else:
        evidence = build_evidence(
            units=units,
            used_unit_ids=[],
            use_model=False,
            final_source_ids=[],
            plan={"path": "rag"},
            direct_rag={"cited_unit_ids": ["unit-1"], "facts": []},
        )
    verdict = classify_with_identity(case, evidence).axis("safety")
    assert verdict.state == "violation", (layer, verdict.as_dict())
    assert verdict.reason == "forbidden_source_used"


def test_retrieval_candidate_only_is_not_usage() -> None:
    """检索候选按原口径：只是候选、没进入任何使用层，不算“使用禁源”。"""
    case = doc_only_case()
    evidence = build_evidence(
        units=[
            {
                "unit_id": "unit-1",
                "document_name": "synthetic-old.xlsx",
                "version_number": 2,
            }
        ],
        used_unit_ids=[],
        model_evidence=[],
        final_source_ids=[],
        retrieval_candidates=["unit-1"],
    )
    verdict = classify_with_identity(case, evidence).axis("safety")
    assert verdict.state == "not_applicable"
    assert verdict.state != "violation"


# --------------------------------------------------------------------------- #
# 缺口 B：v3 缺身份保持 unknown；身份由冻结 map + 场景入库映射派生
# --------------------------------------------------------------------------- #


def _v3_annotation(case: Any) -> Any:
    annotation = _single(case)
    return replace(
        annotation,
        payload={
            **annotation.payload,
            "bindings": {**annotation.payload["bindings"], "dataset_version": "P2-HOLDOUT-v3.3"},
        },
    )


def test_v3_without_identity_stays_unknown_even_with_matching_evidence() -> None:
    case = doc_only_case()
    evidence = build_evidence(
        units=[{"document_name": "synthetic-old.xlsx", "version_number": 2}]
    )
    result = hard.classify_case_evidence(case, _v3_annotation(case), make_audit(case, evidence))
    verdict = result.axis("safety")
    assert verdict.state == "unknown"
    assert verdict.reason == "forbidden_source_unmappable"


def test_v3_with_identity_is_violation() -> None:
    case = doc_only_case()
    evidence = build_evidence(
        units=[{"document_name": "synthetic-old.xlsx", "version_number": 2}]
    )
    result = hard.classify_case_evidence(
        case,
        _v3_annotation(case),
        make_audit(case, evidence),
        source_identity=synthetic_identity(),
    )
    verdict = result.axis("safety")
    assert verdict.state == "violation"
    assert verdict.reason == "forbidden_source_used"


def test_build_source_identity_validates_shape() -> None:
    mapping = {"D01": {"base_doc_code": "D01", "version_number": 2}}
    identity = hard.build_forbidden_source_identity(mapping, {"synthetic-old": "D01"})
    assert identity.matches({"doc_code": "D01"}, {"document_name": "synthetic-old", "version_number": 2}) is True
    assert identity.matches({"doc_code": "D01"}, {"document_name": "synthetic-old", "version_number": 3}) is False
    for bad_map, bad_codes in (
        ({}, {"a": "D01"}),
        ({"D01": {"base_doc_code": "D01", "version_number": 0}}, {"a": "D01"}),
        ({"D01": {"base_doc_code": "", "version_number": 1}}, {"a": "D01"}),
        ({"D01": {"base_doc_code": "D01", "version_number": True}}, {"a": "D01"}),
        (
            {
                "D01": {"base_doc_code": "D01", "version_number": 2},
                "V03": {"base_doc_code": "D01", "version_number": 2},
            },
            {"a": "D01"},
        ),
        (mapping, {}),
        (mapping, {"a": ""}),
    ):
        with pytest.raises(hard.HardEvidenceError) as caught:
            hard.build_forbidden_source_identity(bad_map, bad_codes)
        assert caught.value.code == "source_identity_invalid"


def test_identity_summary_is_redacted() -> None:
    summary = hard.forbidden_source_identity_summary(synthetic_identity())
    assert summary["schema_version"] == hard.SOURCE_IDENTITY_SCHEMA_VERSION
    assert summary["doc_code_count"] == 5
    assert summary["document_name_count"] == len(DOCUMENT_CODES)
    payload = json.dumps(summary, ensure_ascii=False, sort_keys=True)
    for name in DOCUMENT_CODES:
        assert name not in payload
    for key in ("source_map_sha256", "document_codes_sha256", "identity_sha256"):
        assert len(summary[key]) == 64


# --------------------------------------------------------------------------- #
# 受控离线重建入口：冻结 v0.2 source map + 场景 ingest 映射 -> 可信身份
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def tool() -> Any:
    spec = importlib.util.spec_from_file_location("p2_h2_controlled_entry_docforbidden", TOOL_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def repair_entry() -> Any:
    """复用 T207 修复链的合成 30 题私有输入（真 Fernet/真 case-plan/真 recompute 入口）。

    只固定 ``code_digest``：本窗口与并行任务共享工作树，别的任务改 ``backend/src/mktkb``
    会改变整体代码摘要，让“同一次测试里的计划身份 vs 代码身份”抖动。固定后 ``plan_private``
    与 ``recompute`` 用同一常量（真实入口的摘要检查另有既有测试覆盖）。
    """
    path = Path(__file__).resolve().parent / "test_p2_eval_tool_repair_e2e.py"
    spec = importlib.util.spec_from_file_location("p2_h2_docforbidden_repair_chain", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    tool = module.entry.__wrapped__()
    tool.code_digest = lambda: "c" * 64
    return SimpleNamespace(module=module, tool=tool, code_version="c" * 64)


@pytest.fixture(scope="module")
def repair_chain(repair_entry: Any, tmp_path_factory: pytest.TempPathFactory) -> Any:
    tool = repair_entry.tool
    saved = (tool.p2a.P2_LEDGER_PATH, tool.p2a.P2_BUDGET_PATH, tool.p2a.P2_GO_PATH)
    chain = repair_entry.module.chain.__wrapped__(tool, tmp_path_factory)
    tool.AUTHORIZED_ENV_PATH = chain.env_path
    try:
        yield chain
    finally:
        # 链装配把 p2a 的三条固定路径指向本次临时目录（recompute 的账本审计要求
        # ledger 必须等于固定路径）。模块结束时还原，避免影响同会话其它测试模块。
        tool.p2a.P2_LEDGER_PATH, tool.p2a.P2_BUDGET_PATH, tool.p2a.P2_GO_PATH = saved


def test_controlled_recompute_records_original_and_derived_identity(
    repair_entry: Any, repair_chain: Any, tmp_path: Path
) -> None:
    """受控离线重建入口：card 照出，且“原运行身份”与“派生评分器身份”分列可追溯。"""
    tool = repair_entry.tool
    result = tool.recompute(
        env_file=repair_chain.env_path,
        binding_path=Path(repair_chain.plan_payload["binding_file"]),
        run_index=0,
        evidence_dir=repair_chain.evidence_dir,
        evidence_key_file=repair_chain.key_path,
        case_plan_path=repair_chain.case_plan_path,
        runtime=tool.RuntimeOptions(
            holdout_root=repair_chain.private.holdout_root,
            holdout_key_file=repair_chain.private.holdout_key_file,
            project_total_limit_cny=40.0,
        ),
        ledger_path=repair_chain.ledger,
        out_card=tmp_path / "recomputed-card.json",
    )
    identity = result["identity"]
    original, derived = identity["original"], identity["derived_scorer"]
    assert result["card"]["total"] == 26
    assert result["card"]["release_ready"] is False
    assert original["run_id"] == repair_chain.run_entry["run_id"]
    assert original["plan_sha256"] == repair_chain.plan.plan_sha256
    assert original["plan_file_sha256"] == repair_chain.run_entry["plan_file_sha256"]
    assert original["scenario_id"] == "base_b0"
    assert original["source_map_sha256"] == repair_chain.run_entry["scenario_binding"]["source_map_sha256"]
    assert original["scenario_ingest_sha256"] == repair_chain.run_entry["scenario_binding"]["scenario_ingest_sha256"]
    # 该合成语料的 source map 是 synthetic-source-map/v1：不支持 -> 降级 unresolved（不猜）。
    assert derived["status"] == "unresolved"
    assert derived["error_code"] == "holdout_document_code_unmapped"
    assert derived["source_map_file_sha256"] == original["source_map_sha256"]
    assert derived["basis"] == "frozen_source_map+scenario_ingest_plan"
    # 卡里没有题号/题面泄漏。
    assert "P2HS" not in json.dumps(result["card"], ensure_ascii=False)


def test_controlled_recompute_still_refuses_code_changed_since_plan(
    repair_entry: Any, repair_chain: Any, tmp_path: Path
) -> None:
    """固定 ``code_digest`` 只用于消除并行改源码的抖动：历史身份检查本身不许被削弱。"""
    tool = repair_entry.tool
    tool.code_digest = lambda: "d" * 64
    try:
        with pytest.raises(tool.EntryError) as caught:
            tool.recompute(
                env_file=repair_chain.env_path,
                binding_path=Path(repair_chain.plan_payload["binding_file"]),
                run_index=0,
                evidence_dir=repair_chain.evidence_dir,
                evidence_key_file=repair_chain.key_path,
                case_plan_path=repair_chain.case_plan_path,
                runtime=tool.RuntimeOptions(
                    holdout_root=repair_chain.private.holdout_root,
                    holdout_key_file=repair_chain.private.holdout_key_file,
                    project_total_limit_cny=40.0,
                ),
                ledger_path=repair_chain.ledger,
                out_card=tmp_path / "should-not-exist.json",
            )
    finally:
        tool.code_digest = lambda: repair_entry.code_version
    assert caught.value.code == "code_changed_since_plan"
    assert not (tmp_path / "should-not-exist.json").exists()


def _ingest_plan(tmp_path: Path, names: list[str]) -> P2IngestPlan:
    sources = []
    for index, name in enumerate(names):
        folder = tmp_path / ("ingest-" + str(index))
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / name
        target.write_bytes(b"synthetic ingest placeholder")
        sources.append(IngestSource(path=target, name=name))
    return P2IngestPlan(sources=tuple(sources), label="synthetic-docforbidden")


def _scenario_binding(source_map_sha: str, scenario: str = "base_b0") -> dict[str, str]:
    binding = {key: "e" * 64 for key in tool_binding_keys()}
    binding["scenario_id"] = scenario
    binding["source_map_sha256"] = source_map_sha
    return binding


def tool_binding_keys() -> tuple[str, ...]:
    from mktkb.evaluation.p2_holdout_scenarios import BINDING_KEYS

    return tuple(sorted(BINDING_KEYS))


@pytest.fixture(scope="module")
def v3_tool() -> Any:
    """按文件路径导入 v3 受控入口（导入期要求项目总上限=40，导入后还原环境）。"""
    import os

    from mktkb.evaluation import p2_holdout_plan as holdout

    original_env = os.environ.get("MKTKB_PROJECT_TOTAL_LIMIT_CNY")
    original_const = holdout.H2_PROJECT_TOTAL_LIMIT_CNY
    os.environ["MKTKB_PROJECT_TOTAL_LIMIT_CNY"] = "40.0"
    holdout.H2_PROJECT_TOTAL_LIMIT_CNY = 40.0
    try:
        spec = importlib.util.spec_from_file_location(
            "p2_h2_v3_controlled_entry_docforbidden",
            Path(__file__).resolve().parents[3] / "tools" / "p2_h2_v3_controlled_execute.py",
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
    finally:
        holdout.H2_PROJECT_TOTAL_LIMIT_CNY = original_const
        if original_env is None:
            os.environ.pop("MKTKB_PROJECT_TOTAL_LIMIT_CNY", None)
        else:
            os.environ["MKTKB_PROJECT_TOTAL_LIMIT_CNY"] = original_env
    return module


def test_v3_entry_records_scorer_identity_pinned_to_plan(v3_tool: Any, tmp_path: Path) -> None:
    """v3 ``run`` 的 sidecar 身份：同一份冻结 v0.2 map + 本场景 ingest 映射，且与计划逐值绑定。"""
    source_map_sha = hashlib.sha256(V3_SOURCE_MAP.read_bytes()).hexdigest()
    binding = _scenario_binding(source_map_sha)
    plan = build_holdout_plan(
        cases=(("SYN-01", 1),),
        ingest_batches=1,
        plan_id="P2-H2V3-20261115-r0-base_b0",
        plan_version="v0.1",
        created_utc="2026-11-15T05:00:00+08:00",
        max_requests="unlimited",
        project_total_limit_cny=40.0,
        scenario_binding=binding,
    )
    ingest_plan = _ingest_plan(tmp_path, ["D01_synthetic-old.xlsx"])
    bundle = SimpleNamespace(contract=SimpleNamespace(ingest_plan=lambda name: ingest_plan))
    state = v3_tool._scorer_identity_state(bundle, "base_b0", plan)
    assert state["schema_version"] == "p2-h2v3-scorer-identity/v0.1"
    assert state["status"] == "derived"
    assert state["source_map_schema_version"] == "p2-holdout-source-map/v0.2"
    assert state["source_map_file_sha256"] == source_map_sha
    assert state["scenario_id"] == "base_b0"
    assert state["plan_sha256"] == plan.plan_sha256


def test_v3_entry_refuses_scorer_identity_when_plan_pins_other_map(
    v3_tool: Any, tmp_path: Path
) -> None:
    binding = _scenario_binding("1" * 64)
    plan = build_holdout_plan(
        cases=(("SYN-01", 1),),
        ingest_batches=1,
        plan_id="P2-H2V3-20261115-r0-base_b0",
        plan_version="v0.1",
        created_utc="2026-11-15T05:00:00+08:00",
        max_requests="unlimited",
        project_total_limit_cny=40.0,
        scenario_binding=binding,
    )
    ingest_plan = _ingest_plan(tmp_path, ["D01_synthetic-old.xlsx"])
    bundle = SimpleNamespace(contract=SimpleNamespace(ingest_plan=lambda name: ingest_plan))
    with pytest.raises(v3_tool.v2.EntryError) as caught:
        v3_tool._scorer_identity_state(bundle, "base_b0", plan)
    assert caught.value.code == "source_map_binding_mismatch"


def test_tool_builds_identity_from_frozen_v3_source_map(tool: Any, tmp_path: Path) -> None:
    plan = _ingest_plan(tmp_path, ["D01_synthetic-old.xlsx", "V04_synthetic-current.xlsx"])
    identity, summary = tool.scenario_forbidden_source_identity(
        source_map_path=V3_SOURCE_MAP,
        ingest_plan=plan,
        expected_source_map_sha256=hashlib.sha256(V3_SOURCE_MAP.read_bytes()).hexdigest(),
    )
    assert summary["schema_version"] == tool.SCORER_IDENTITY_SCHEMA_VERSION
    assert summary["identity_schema_version"] == hard.SOURCE_IDENTITY_SCHEMA_VERSION
    assert summary["status"] == "derived" and summary["error_code"] is None
    assert summary["source_map_schema_version"] == "p2-holdout-source-map/v0.2"
    assert summary["doc_code_count"] == 12
    assert summary["document_name_count"] == 4
    assert summary["source_map_path"] == str(V3_SOURCE_MAP)
    assert identity.matches(
        {"doc_code": "D01"}, {"document_name": "D01_synthetic-old.xlsx", "version_number": 2}
    ) is True
    assert identity.matches(
        {"doc_code": "D01"}, {"document_name": "V04_synthetic-current.xlsx", "version_number": 3}
    ) is False
    # 真实冻结 map 的跨版本身份：V03 是 D01/1，不是 D01/2。
    assert identity.matches(
        {"doc_code": "D01"}, {"document_name": "D01_synthetic-old.xlsx", "version_number": 1}
    ) is False


def test_tool_refuses_source_map_digest_drift(tool: Any, tmp_path: Path) -> None:
    plan = _ingest_plan(tmp_path, ["D01_synthetic-old.xlsx"])
    with pytest.raises(tool.EntryError) as caught:
        tool.scenario_forbidden_source_identity(
            source_map_path=V3_SOURCE_MAP,
            ingest_plan=plan,
            expected_source_map_sha256="0" * 64,
        )
    assert caught.value.code == "source_map_binding_mismatch"


def test_tool_refuses_ambiguous_ingest_mapping(tool: Any, tmp_path: Path) -> None:
    """同一语料文件名被两个来源映射到两个不同代号：不猜，降级成 unresolved 身份。"""
    first_path = tmp_path / "D01_same.xlsx"
    first_path.write_bytes(b"x")
    second_path = tmp_path / "second.bin"
    second_path.write_bytes(b"x")
    plan = P2IngestPlan(
        sources=(
            # 规范名是 V04_same.xlsx，但文件名 D01_same.xlsx 也会登记 -> 与下一份冲突。
            IngestSource(path=first_path, name="V04_same.xlsx"),
            IngestSource(path=second_path, name="D01_same.xlsx"),
        ),
        label="synthetic-conflict",
    )
    identity, summary = tool.scenario_forbidden_source_identity(
        source_map_path=V3_SOURCE_MAP,
        ingest_plan=plan,
        expected_source_map_sha256=hashlib.sha256(V3_SOURCE_MAP.read_bytes()).hexdigest(),
    )
    assert summary["status"] == "unresolved"
    assert summary["error_code"] == "holdout_document_code_ambiguous"
    assert identity is hard.UNRESOLVED_SOURCE_IDENTITY
    assert identity.matches(
        {"doc_code": "D01"}, {"document_name": "D01_same.xlsx", "version_number": 2}
    ) is None


def test_tool_degrades_unknown_source_map_schema_to_unresolved_identity(
    tool: Any, tmp_path: Path
) -> None:
    """计划钉住的 map 若 schema 不受支持：不抛、不猜，身份记为 unresolved（评分 unknown）。"""
    legacy_map = tmp_path / "legacy-source-map.json"
    legacy_map.write_text(
        json.dumps(
            {
                "schema_version": "synthetic-source-map/v1",
                "sources": {"D01": {"doc_code": "D01"}},
            }
        ),
        encoding="utf-8",
    )
    plan = _ingest_plan(tmp_path, ["D01_synthetic-old.xlsx"])
    identity, summary = tool.scenario_forbidden_source_identity(
        source_map_path=legacy_map,
        ingest_plan=plan,
        expected_source_map_sha256=hashlib.sha256(legacy_map.read_bytes()).hexdigest(),
    )
    assert summary["status"] == "unresolved"
    assert summary["error_code"] == "holdout_document_code_unmapped"
    # 观测到的 schema 字符串照实记录（拒绝/降级的原因是“不支持”，不是“读不到”）。
    assert summary["source_map_schema_version"] == "synthetic-source-map/v1"
    assert summary["doc_code_count"] == 0
    assert identity is hard.UNRESOLVED_SOURCE_IDENTITY


def test_tool_scorer_identity_binding_separates_original_and_derived(
    tool: Any, tmp_path: Path
) -> None:
    plan = _ingest_plan(tmp_path, ["D01_synthetic-old.xlsx"])
    source_map_sha = hashlib.sha256(V3_SOURCE_MAP.read_bytes()).hexdigest()
    binding = _scenario_binding(source_map_sha)
    run_plan = build_holdout_plan(
        cases=(("SYN-01", 1),),
        ingest_batches=1,
        plan_id="P2-SYN-r1-base_b0",
        plan_version="v0.1",
        created_utc="2026-11-20T00:00:00+00:00",
        max_requests=1100,
        project_total_limit_cny=40.0,
        scenario_binding=binding,
    )
    document = {
        "code_version": "a" * 64,
        "config_sha256": "b" * 64,
        "business_date": "2026-10-28",
        "inputs": {"source_map": {"path": str(V3_SOURCE_MAP), "sha256": source_map_sha}},
    }
    run_entry = {
        "run_id": "p2-h2-syn-r1-base_b0",
        "plan_file_sha256": "c" * 64,
        "scenario_binding": binding,
    }
    binding = tool._scorer_identity_binding(
        document=document, run_entry=run_entry, plan=run_plan, scenario="base_b0",
        ingest_plan=plan,
    )
    original = binding["original_identity"]
    derived = binding["source_identity_summary"]
    assert original["code_version"] == "a" * 64
    assert original["plan_sha256"] == run_plan.plan_sha256
    assert original["plan_file_sha256"] == "c" * 64
    assert original["source_map_sha256"] == source_map_sha
    assert derived["source_map_file_sha256"] == source_map_sha
    assert derived["basis"] == "frozen_source_map+scenario_ingest_plan"
    assert derived["status"] == "derived"
    assert derived["doc_code_count"] == 12
    # 派生身份可直接用于判定：同文档同版本 -> 命中。
    assert binding["source_identity"].matches(
        {"doc_code": "D01"}, {"document_name": "D01_synthetic-old.xlsx", "version_number": 2}
    ) is True
    assert set(binding) == {"source_identity", "source_identity_summary", "original_identity"}


def test_tool_identity_binding_refuses_source_map_binding_mismatch(
    tool: Any, tmp_path: Path
) -> None:
    plan = _ingest_plan(tmp_path, ["D01_synthetic-old.xlsx"])
    document = {
        "code_version": "a" * 64,
        "config_sha256": "b" * 64,
        "business_date": "2026-10-28",
        "inputs": {"source_map": {"path": str(V3_SOURCE_MAP), "sha256": "0" * 64}},
    }
    run_entry = {
        "run_id": "p2-h2-syn-r1-base_b0",
        "plan_file_sha256": "c" * 64,
        "scenario_binding": {"scenario_id": "base_b0", "source_map_sha256": "1" * 64},
    }
    with pytest.raises(tool.EntryError) as caught:
        tool._scorer_identity_binding(
            document=document, run_entry=run_entry, plan=object(), scenario="base_b0",
            ingest_plan=plan,
        )
    assert caught.value.code == "source_map_binding_mismatch"

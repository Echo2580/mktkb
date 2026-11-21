"""FU-2：v3 单 run 离线派生（``derive-cards``）的定向回归。

被测契约
--------
1. 旧正式入口（v2 ``recompute``）**仍然拒绝** v3 单 run binding（固定码
   ``run_binding_invalid``，退出码 2），且拒绝发生在任何私有材料加载之前；
2. 正式 v3 入口新增 ``derive-cards``：五道独立校验（历史计划与原执行身份、派生评分身份、
   场景与语料绑定、封存状态、回合完整性）逐条可拒；
3. 同输入重复运行 → 产物 SHA-256 逐值相同（确定性）；
4. 正式输出拒绝仓库根 / 原批次根 / 冻结 holdout 根内的写入，覆盖 ``..``、大小写、尾斜杠、
   ``.\\`` 归一化与链接负例；
5. 四场景合成为官方 ``compose_hard_evidence_runs`` + ``validate_hard_evidence_composition``，
   单卡为官方 ``validate_hard_evidence_scorecard``（阈值不放宽）。

零真实调用：不读 ``.env``、不读任何 H2 私有材料；binding / 计划 / case-plan / 密文全部合成，
落在 pytest 的**仓外**临时目录。``scenario_key_file`` 等真实受限件从不打开。
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

_TESTS_DIR = Path(__file__).resolve().parents[1]
_EVALUATION_TESTS = Path(__file__).resolve().parent
for _path in (_TESTS_DIR, _EVALUATION_TESTS):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from acceptance.support.netguard import t09_network_guard  # noqa: E402,F401

import test_p2_hard_evidence as H  # noqa: E402

from mktkb.evaluation import p2_evidence_capture as capture  # noqa: E402
from mktkb.evaluation import p2_hard_evidence as hard  # noqa: E402
from mktkb.evaluation import p2_holdout_plan as holdout_plan  # noqa: E402
from mktkb.evaluation import p2_holdout_scenarios as scenarios  # noqa: E402
from mktkb.evaluation import p2_safe_output as safe_output  # noqa: E402
from mktkb.evaluation.p2_contracts import payload_sha256  # noqa: E402
from mktkb.evaluation.p2_holdout_scenarios import BINDING_KEYS as SCENARIO_BINDING_KEYS  # noqa: E402
from mktkb.evaluation.product_adapter import product_pipeline_version  # noqa: E402

pytestmark = pytest.mark.usefixtures("t09_network_guard")

ROOT = Path(__file__).resolve().parents[3]
TOOL_PATH = ROOT / "tools" / "p2_h2_v3_controlled_execute.py"
V2_TOOL_PATH = ROOT / "tools" / "p2_h2_controlled_execute.py"
TOTAL_LIMIT_ENV = "MKTKB_PROJECT_TOTAL_LIMIT_CNY"

V3_MAP = ROOT / "docs/evaluation/p2-holdout-v3.source-map.json"
V3_INGEST = ROOT / "docs/reports/OBS-EVAL/P2/H2V3/PM/p2-ingest-plan-H2-v3.json"
V3_CONTRACT = ROOT / "docs/evaluation/p2-h2-scenarios-H2v3.json"
V3_SCHEMA = ROOT / "docs/evaluation/p2-h2-custody-annotations-v0_2.md"


# --------------------------------------------------------------------------- #
# 工具导入
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def tool() -> Any:
    """按文件路径导入 v3 正式入口（导入期把项目总上限固定为 40；测试后还原）。"""
    original_env = os.environ.get(TOTAL_LIMIT_ENV)
    original_const = holdout_plan.H2_PROJECT_TOTAL_LIMIT_CNY
    os.environ[TOTAL_LIMIT_ENV] = "40.0"
    holdout_plan.H2_PROJECT_TOTAL_LIMIT_CNY = 40.0
    try:
        spec = importlib.util.spec_from_file_location("_p2_fu2_v3_entry", TOOL_PATH)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
    finally:
        holdout_plan.H2_PROJECT_TOTAL_LIMIT_CNY = original_const
        if original_env is None:
            os.environ.pop(TOTAL_LIMIT_ENV, None)
        else:
            os.environ[TOTAL_LIMIT_ENV] = original_env
    return module


@pytest.fixture(scope="module")
def v2_entry(tool: Any) -> Any:
    """**独立**导入 v2 正式入口（不经过 v3 的导入期校验器替换）。

    v3 入口在导入期会把它自己加载的 v2 模块对象的 ``_validate_binding_document`` 换成
    v3 单 run 形状；真实场景里旧入口是**单独进程**跑 v2 文件，因此这里也必须单独加载，
    否则会把"旧入口拒绝 v3"错误地测成"接受"。
    """
    del tool
    original_env = os.environ.get(TOTAL_LIMIT_ENV)
    original_const = holdout_plan.H2_PROJECT_TOTAL_LIMIT_CNY
    os.environ[TOTAL_LIMIT_ENV] = "40.0"
    holdout_plan.H2_PROJECT_TOTAL_LIMIT_CNY = 40.0
    try:
        spec = importlib.util.spec_from_file_location("_p2_fu2_v2_entry_standalone", V2_TOOL_PATH)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
    finally:
        holdout_plan.H2_PROJECT_TOTAL_LIMIT_CNY = original_const
        if original_env is None:
            os.environ.pop(TOTAL_LIMIT_ENV, None)
        else:
            os.environ[TOTAL_LIMIT_ENV] = original_env
    return module


def _write_json(path: Path, payload: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return path


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tree(path: Path) -> dict[str, str]:
    return {
        item.relative_to(path).as_posix(): _sha(item)
        for item in sorted(path.rglob("*"))
        if item.is_file()
    }


# --------------------------------------------------------------------------- #
# 合成 v3 单 run 材料（全部自造；真实受限件只读且不打开私有内容）
# --------------------------------------------------------------------------- #


def _synthetic_inputs(tool: Any, root: Path) -> dict[str, dict[str, Any]]:
    """14 项输入记录：公开冻结件用真路径（只读），其余写合成字节。"""
    root.mkdir(parents=True, exist_ok=True)
    real = {
        "scenario_contract": V3_CONTRACT,
        "ingest_plan": V3_INGEST,
        "source_map": V3_MAP,
        "annotation_schema": V3_SCHEMA,
    }
    records: dict[str, dict[str, Any]] = {}
    for name in tool.V3_INPUT_NAMES:
        if name in real:
            target = real[name]
        else:
            target = root / (name + ".synthetic")
            if not target.exists():
                target.write_bytes(("synthetic:" + name).encode("utf-8"))
        raw = target.read_bytes()
        records[name] = {
            "path": str(target.resolve()),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "bytes": len(raw),
        }
    return records


def _scenario_binding(inputs: dict[str, dict[str, Any]], scenario: str) -> dict[str, str]:
    """12 键场景绑定：摘要取自同一批输入记录（与生产口径同形）。"""
    return {
        "scenario_id": scenario,
        "assignment_sha256": "1" * 64,
        "custody_sha256": "2" * 64,
        "review_sha256": "3" * 64,
        "scenario_contract_sha256": str(inputs["scenario_contract"]["sha256"]),
        "ingest_plan_sha256": str(inputs["ingest_plan"]["sha256"]),
        "scenario_ingest_sha256": "4" * 64,
        "subset_sha256": "5" * 64,
        "full_cases_sha256": "6" * 64,
        "manifest_sha256": str(inputs["holdout_manifest"]["sha256"]),
        "schema_sha256": str(inputs["annotation_schema"]["sha256"]),
        "source_map_sha256": str(inputs["source_map"]["sha256"]),
    }


def _build_plan(tool: Any, *, scenario: str, scenario_binding: dict[str, str], run_index: int) -> Any:
    return holdout_plan.build_holdout_plan(
        cases=(("SYN-" + scenario[:6], 1),),
        ingest_batches=tool._v3_ingest_batches(scenario),
        plan_id=f"P2-FU2-SYNTH-r{run_index}-{scenario}",
        plan_version="v0.1",
        created_utc="2026-11-15T05:00:00+08:00",
        max_requests="unlimited",
        project_total_limit_cny=40.0,
        scenario_binding=scenario_binding,
    )


def _synthetic_binding(
    tool: Any,
    work: Path,
    *,
    run_index: int = 0,
    scenario: str | None = None,
    business_date: str = "2026-11-15",
    anchor: str = "2026-10-15",
) -> tuple[Path, dict[str, Any], Any, dict[str, dict[str, Any]]]:
    """构造一份**能通过 v3 绑定校验器**的合成单 run binding（无任何私有材料）。"""
    scenario = scenario or tool.v2.SCENARIO_ORDER[run_index]
    holdout = work / "holdout-root"
    holdout.mkdir(parents=True, exist_ok=True)
    (holdout / "manifest.json").write_text('{"synthetic": true}\n', encoding="utf-8")
    inputs = _synthetic_inputs(tool, work / "inputs")
    binding = _scenario_binding(inputs, scenario)
    plan = _build_plan(tool, scenario=scenario, scenario_binding=binding, run_index=run_index)
    plan_file = _write_json(work / f"plan-r{run_index}.json", plan.as_dict())
    code_version = "c" * 64
    config = tool._v3_config(
        business_date=business_date,
        anchor_business_date=anchor,
        inputs=inputs,
        code_version=code_version,
        thresholds_approved=False,
    )
    config_sha = payload_sha256(config)
    run_id = f"p2-h2v3-synthetic-r{run_index}-{scenario}"
    evidence_bindings = {
        "run_id": run_id,
        "plan_id": str(plan.plan_id),
        "plan_sha256": str(plan.plan_sha256),
        "dataset_version": "P2-HOLDOUT-v3-synthetic",
        "manifest_sha256": str(inputs["holdout_manifest"]["sha256"]),
        "label_version": "v0.2",
        "suite": "holdout",
        "scenario_id": scenario,
        "scenario_contract_sha256": binding["scenario_contract_sha256"],
        "assignment_sha256": binding["assignment_sha256"],
        "custody_sha256": binding["custody_sha256"],
        "config_sha256": config_sha,
        "pipeline_version": product_pipeline_version(),
        "index_revision": capture.LIVE_PENDING_INDEX_REVISION,
        "code_version": code_version,
        "fixture_kind": capture.LIVE_FIXTURE_KIND,
    }
    assert set(evidence_bindings) == set(capture.BINDING_KEYS)
    document = {
        "schema_version": tool.BINDING_SCHEMA_VERSION,
        "created_utc": "2026-11-15T05:00:00+08:00",
        "fixture_kind": capture.LIVE_FIXTURE_KIND,
        "execution_mode": "live",
        "holdout_root": str(holdout.resolve()),
        "anchor_business_date": anchor,
        "business_date": business_date,
        "code_version": code_version,
        "config_sha256": config_sha,
        "config": config,
        "dataset": {
            "case_count": sum(tool.V3_SCENARIO_COUNTS.values()),
            "total_turns": sum(tool.V3_SCENARIO_TURNS.values()),
            "scenario_counts": dict(tool.V3_SCENARIO_COUNTS),
            "manifest_sha256": str(inputs["holdout_manifest"]["sha256"]),
            "anchor_business_date": anchor,
            "dataset_version": "P2-HOLDOUT-v3-synthetic",
            "label_version": "v0.2",
            "suite": "holdout",
        },
        "inputs": inputs,
        "runs": [
            {
                "run_index": run_index,
                "scenario_id": scenario,
                "run_id": run_id,
                "plan_id": str(plan.plan_id),
                "plan_sha256": str(plan.plan_sha256),
                "plan_file": str(plan_file.resolve()),
                "plan_file_sha256": _sha(plan_file),
                "business_date": business_date,
                "rag_business_date": business_date,
                "manifest_business_date": business_date,
                "case_count": int(tool.V3_SCENARIO_COUNTS[scenario]),
                "turn_count": int(tool.V3_SCENARIO_TURNS[scenario]),
                "total_requests": int(plan.total_requests),
                "worst_case_cny": 0.5,
                "reserve_peak_cny": 0.5,
                "ingest_batches": int(tool._v3_ingest_batches(scenario)),
                "ingest_sources": 7,
                "scenario_binding": binding,
                "evidence_bindings": evidence_bindings,
                "contract_validate_run": {"ok": True},
                "source_map": {
                    "schema_version": "p2-holdout-source-map/v0.2",
                    "code_count": 12,
                    "sha256": str(inputs["source_map"]["sha256"]),
                },
            }
        ],
    }
    document["binding_sha256"] = payload_sha256(
        {key: value for key, value in document.items() if key != "binding_sha256"}
    )
    path = _write_json(work / "run-binding.json", document)
    return path, document, plan, inputs


# --------------------------------------------------------------------------- #
# 1. 先复现：旧正式入口拒绝 v3 单 run；新入口此前没有派生命令
# --------------------------------------------------------------------------- #


def test_old_recompute_still_refuses_a_v3_single_run_binding(
    tool: Any, v2_entry: Any, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """旧正式入口 ``recompute`` 对 v3 单 run binding 的拒绝保持原样（D-010 事实）。"""
    entry = v2_entry
    work = tmp_path / "repro"
    binding, document, _plan, _inputs = _synthetic_binding(tool, work)
    env_file = work / "auth" / ".env"
    env_file.parent.mkdir(parents=True, exist_ok=True)
    env_file.write_text(
        "\n".join(
            [
                "MKTKB_MODEL_API_KEY=SYNTHETIC-FU2-CHAT",
                "MKTKB_MODEL_BASE_URL=https://api.deepseek.com",
                "MKTKB_MODEL_NAME=deepseek-flash",
                "DASHSCOPE_API_KEY=SYNTHETIC-FU2-DASHSCOPE",
                "MKTKB_OCR_SECRET_ID=SYNTHETIC-FU2-OCR",
                "MKTKB_OCR_SECRET_KEY=SYNTHETIC-FU2-OCR",
                "MKTKB_OCR_REGION=ap-guangzhou",
                "MKTKB_OCR_DISABLED=0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    key = work / "holdout.key"
    from cryptography.fernet import Fernet

    key.write_bytes(Fernet.generate_key())
    evidence_key = work / "evidence.key"
    evidence_key.write_bytes(Fernet.generate_key())
    original = entry.AUTHORIZED_ENV_PATH
    entry.AUTHORIZED_ENV_PATH = env_file
    try:
        code = entry.main(
            [
                "recompute",
                "--env-file",
                str(env_file),
                "--run-binding",
                str(binding),
                "--run-index",
                "0",
                "--evidence-dir",
                str(work / "evidence"),
                "--evidence-key-file",
                str(evidence_key),
                "--case-plan",
                str(work / "case-plan.json"),
                "--holdout-root",
                str(document["holdout_root"]),
                "--holdout-key-file",
                str(key),
                "--project-total-limit-cny",
                "40",
            ]
        )
    finally:
        entry.AUTHORIZED_ENV_PATH = original
    payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert code == entry.EXIT_REFUSED == 2
    assert payload["error_code"] == "run_binding_invalid"
    assert payload["real_sends"] == 0


def test_v3_parser_registers_derive_cards_and_keeps_live_commands(tool: Any) -> None:
    """正式入口必须同时保留 live 命令与新的离线派生命令（v2 兼容由命令集合体现）。"""
    parser = tool._build_parser()
    actions = [action for action in parser._actions if getattr(action, "choices", None)]
    commands = set()
    for action in actions:
        choices = action.choices
        if isinstance(choices, dict):
            commands.update(str(name) for name in choices)
    assert {"plan-private", "check-only", "run", "derive-cards"} <= commands


def test_v2_entry_still_refuses_derive_cards_subcommand(tool: Any) -> None:
    """v2 入口命令集合未被改动（v2 兼容：既有命令与拒绝码保持原样）。"""
    entry = tool.v2
    parser = entry._build_parser()
    commands = set()
    for action in parser._actions:
        choices = getattr(action, "choices", None)
        if isinstance(choices, dict):
            commands.update(str(name) for name in choices)
    assert commands == {"plan-private", "preflight", "run", "recompute"}


# --------------------------------------------------------------------------- #
# 2. 历史计划与原执行身份 / 派生评分身份 / 场景与语料绑定
# --------------------------------------------------------------------------- #


def test_synthetic_binding_passes_the_real_v3_validator_and_tamper_is_refused(
    tool: Any, tmp_path: Path
) -> None:
    binding, document, _plan, _inputs = _synthetic_binding(tool, tmp_path / "doc")
    loaded = tool.v2._read_json_mapping(binding, "run_binding_unreadable")
    tool._validate_binding_document(loaded)  # 正例：不抛

    tampered = dict(loaded)
    tampered["binding_sha256"] = "0" * 64
    with pytest.raises((tool.EntryError, tool.v2.EntryError)) as caught:
        tool._validate_binding_document(tampered)
    assert caught.value.code == "run_binding_invalid"

    old_schema = dict(loaded)
    old_schema["schema_version"] = "p2-h2-controlled-runbinding/v0.1"
    with pytest.raises((tool.EntryError, tool.v2.EntryError)) as caught:
        tool._validate_binding_document(old_schema)
    assert caught.value.code == "run_binding_invalid"


def test_plan_identity_and_plan_tamper_are_refused(tool: Any, tmp_path: Path) -> None:
    binding, document, plan, _inputs = _synthetic_binding(tool, tmp_path / "doc")
    run = document["runs"][0]
    loaded_plan = tool.v2._load_plan_for_run(document, run)
    assert loaded_plan.plan_sha256 == plan.plan_sha256
    tool.v2._verify_plan_binding(document, run, loaded_plan)  # 正例：不抛

    Path(str(run["plan_file"])).write_text('{"tampered": true}\n', encoding="utf-8")
    with pytest.raises((tool.EntryError, tool.v2.EntryError)) as caught:
        tool.v2._load_plan_for_run(document, run)
    assert caught.value.code == "plan_file_changed"

    # 计划身份被改写（plan_id 与 binding 不一致）也要拒。
    binding2, document2, plan2, _ = _synthetic_binding(tool, tmp_path / "doc2")
    run2 = document2["runs"][0]
    run2["plan_id"] = "P2-FU2-SYNTH-OTHER-r0-base_b0"
    with pytest.raises((tool.EntryError, tool.v2.EntryError)) as caught:
        tool.v2._load_plan_for_run(document2, run2)
    assert caught.value.code == "plan_identity_mismatch"


def test_derived_scoring_identity_is_derived_from_frozen_source_map_and_refuses_map_swap(
    tool: Any, tmp_path: Path
) -> None:
    """派生评分身份只从冻结 source map + 本场景 ingest map 派生；换 map 一律拒绝。"""
    binding, document, plan, inputs = _synthetic_binding(tool, tmp_path / "doc")
    run = document["runs"][0]
    # 合成 ingest plan：两条公开语料的**规范文件名**（不打开内容，只做名字→doc_code 映射）。
    ingest = SimpleNamespace(
        sources=[
            SimpleNamespace(
                path="fixtures/acceptance-h2v3/normal/D01_物品位置表.xlsx", name=None
            ),
            SimpleNamespace(
                path="fixtures/acceptance-h2v3/variants/V03_物品位置表_历史V1.xlsx", name=None
            ),
        ]
    )
    identity = tool.v2._scorer_identity_binding(
        document=document, run_entry=run, plan=plan, scenario=run["scenario_id"], ingest_plan=ingest
    )
    assert identity["source_identity_summary"]["status"] == "derived"
    assert identity["source_identity_summary"]["source_map_sha256"]
    assert identity["original_identity"]["plan_sha256"] == str(plan.plan_sha256)
    assert identity["original_identity"]["run_id"] == run["run_id"]

    swapped = dict(document)
    swapped["inputs"] = dict(document["inputs"])
    swapped["inputs"]["source_map"] = dict(document["inputs"]["source_map"])
    swapped["inputs"]["source_map"]["sha256"] = "9" * 64
    with pytest.raises((tool.EntryError, tool.v2.EntryError)) as caught:
        tool.v2._scorer_identity_binding(
            document=swapped, run_entry=run, plan=plan, scenario=run["scenario_id"], ingest_plan=ingest
        )
    assert caught.value.code == "source_map_binding_mismatch"


# --------------------------------------------------------------------------- #
# 3. 回合完整性（缺回合 / 重复回合 / 旧 schema）
# --------------------------------------------------------------------------- #


def _cases() -> tuple[Any, ...]:
    """12 题 / 14 回合：与 v3 ``base_b0`` 的冻结计数逐值一致（合成题面，非真实 H2）。"""
    return H.make_cases(12)


def _strata(cases: tuple[Any, ...]) -> dict[str, int]:
    strata: dict[str, int] = {}
    for case in cases:
        strata[str(case.stratum)] = strata.get(str(case.stratum), 0) + 1
    return strata


def _case_plan(
    tool: Any,
    *,
    cases: tuple[Any, ...],
    run_entry: dict[str, Any],
    bindings: dict[str, str],
    schema_version: str | None = None,
    business_date: str = "2026-11-15",
) -> dict[str, Any]:
    run_binding = {
        "plan_sha256": str(bindings["plan_sha256"]),
        "run_id": str(run_entry["run_id"]),
        "scenario_id": str(run_entry["scenario_id"]),
        "go_sha256": "7" * 64,
        "ledger_sha256": "8" * 64,
        "business_date": business_date,
        "code_version": str(bindings["code_version"]),
        "config_sha256": str(bindings["config_sha256"]),
        "attempt_scope_sha256": capture.attempt_scope_sha256(
            run_id=str(run_entry["run_id"]),
            plan_sha256=str(bindings["plan_sha256"]),
            scenario_id=str(run_entry["scenario_id"]),
            go_sha256="7" * 64,
            ledger_sha256="8" * 64,
        ),
    }
    rows = []
    turn_counter = 0
    for case in cases:
        turns = []
        for _ in range(len(case.turns) or 1):
            turns.append(
                {
                    "turn_index": turn_counter,
                    "status": "executed",
                    "evidence_file": f"turn-{turn_counter:04d}.fernet",
                    "error": None,
                }
            )
            turn_counter += 1
        rows.append({"case_id": case.case_id, "quality_status": "pass", "turns": turns})
    strata: dict[str, int] = {}
    for case in cases:
        strata[str(case.stratum)] = strata.get(str(case.stratum), 0) + 1
    return {
        "schema_version": schema_version or tool.v2.LIVE_CASEPLAN_SCHEMA_VERSION,
        "fixture_kind": capture.LIVE_FIXTURE_KIND,
        "run_id": str(run_entry["run_id"]),
        "bindings": dict(bindings),
        "run_binding": run_binding,
        "execution_mode": "live",
        "real_calls": 0,
        "thresholds_approved": False,
        "expected_strata": strata,
        "cases": rows,
    }


def _case_plan_bindings(run_entry: dict[str, Any]) -> dict[str, str]:
    bindings = dict(run_entry["evidence_bindings"])
    bindings["index_revision"] = "1"
    return bindings


def test_case_plan_accepts_complete_turns_and_refuses_missing_duplicate_and_old_schema(
    tool: Any, tmp_path: Path
) -> None:
    binding, document, _plan, _inputs = _synthetic_binding(tool, tmp_path / "doc")
    run = document["runs"][0]
    cases = _cases()
    bindings = _case_plan_bindings(run)
    static = {key: value for key, value in bindings.items() if key != "index_revision"}

    good = _case_plan(tool, cases=cases, run_entry=run, bindings=bindings)
    checked = tool.v2._validate_case_plan_document(good, cases=cases, static_bindings=static)
    assert checked["run_id"] == run["run_id"]

    missing = json.loads(json.dumps(good))
    missing["cases"] = missing["cases"][:-1]
    with pytest.raises((tool.EntryError, tool.v2.EntryError)) as caught:
        tool.v2._validate_case_plan_document(missing, cases=cases, static_bindings=static)
    assert caught.value.code == "case_plan_coverage_invalid"

    duplicate = json.loads(json.dumps(good))
    duplicate["cases"][0]["turns"][0]["turn_index"] = (
        duplicate["cases"][0]["turns"][-1]["turn_index"]
    )
    with pytest.raises((tool.EntryError, tool.v2.EntryError)) as caught:
        tool.v2._validate_case_plan_document(duplicate, cases=cases, static_bindings=static)
    assert caught.value.code in {"case_plan_turn_order_invalid", "case_plan_coverage_invalid"}

    old = _case_plan(
        tool,
        cases=cases,
        run_entry=run,
        bindings=bindings,
        schema_version="p2-hard-evidence-caseplan/v0.0-old",
    )
    with pytest.raises((tool.EntryError, tool.v2.EntryError)) as caught:
        tool.v2._validate_case_plan_document(old, cases=cases, static_bindings=static)
    assert caught.value.code == "case_plan_invalid"


# --------------------------------------------------------------------------- #
# 4. 派生编排：卡 + 证明 + 确定性 + 路径脱敏
# --------------------------------------------------------------------------- #


def _install_derive_stub(
    tool: Any,
    monkeypatch: pytest.MonkeyPatch,
    *,
    document: dict[str, Any],
    plan: Any,
    cases: tuple[Any, ...],
    annotation: Any,
    evidence_status: str = "complete",
) -> dict[str, Any]:
    """只替换"加载私有 v3 材料"与"读密文"两个边界；其余校验用真函数。

    ``_validate_dataset_shape`` / ``_verify_axis_counts`` 是 live run 的 presend 契约闸
    （依赖真实 v3 封存数据集），合成 6 题夹具无法满足；这里显式置空并在报告里登记为
    "真实批次上生效、合成范围内 NOT-RUN"。
    """
    run = document["runs"][0]

    class _Contract:
        def __init__(self) -> None:
            self._dataset = SimpleNamespace(manifest=SimpleNamespace(strata={"paraphrase": len(cases)}))

        def binding(self, scenario: str) -> dict[str, str]:
            assert scenario == run["scenario_id"]
            return dict(run["scenario_binding"])

        def subset(self, scenario: str) -> Any:
            assert scenario == run["scenario_id"]
            return SimpleNamespace(cases=cases)

        def ingest_plan(self, scenario: str) -> Any:
            assert scenario == run["scenario_id"]
            return object()

        def safe_summary(self) -> dict[str, Any]:
            return {"scenario_counts": dict(tool.V3_SCENARIO_COUNTS)}

    stub_bundle = SimpleNamespace(
        dataset=SimpleNamespace(visibility="holdout", manifest=SimpleNamespace(case_strata=None)),
        contract=_Contract(),
        annotation=annotation,
        review={},
        inputs=document["inputs"],
    )
    monkeypatch.setattr(tool, "load_v3_bundle", lambda inputs: stub_bundle)
    monkeypatch.setattr(tool, "_validate_dataset_shape", lambda bundle: None)
    monkeypatch.setattr(tool, "_verify_axis_counts", lambda bundle: None)
    monkeypatch.setattr(
        tool.v2,
        "_scorer_identity_binding",
        lambda **kwargs: {
            "source_identity": hard.UNRESOLVED_SOURCE_IDENTITY,
            "source_identity_summary": {
                "schema_version": "p2-h2-scorer-identity/v0.1",
                "status": "derived",
                "source_map_path": str(V3_MAP),
                "source_map_sha256": str(document["inputs"]["source_map"]["sha256"]),
            },
            "original_identity": {
                "run_id": run["run_id"],
                "plan_sha256": str(plan.plan_sha256),
                "scenario_id": run["scenario_id"],
            },
        },
    )

    def _read(path: Path, *, key: bytes, expected_bindings: Any = None) -> dict[str, Any]:
        del key, expected_bindings
        name = Path(path).name
        if name.startswith("manifest-"):
            return {
                "run_binding": dict(_read.control),
                "summary": {
                    "turn_count": _read.turn_count,
                    "status_counts": {evidence_status: _read.turn_count},
                },
            }
        return {
            "run_binding": dict(_read.control),
            "turn": {"turn_index": int(name.split("-")[1].split(".")[0])},
            "completeness": {"status": evidence_status},
        }

    _read.control = {}
    _read.turn_count = 0
    monkeypatch.setattr(tool.v2, "read_encrypted_evidence", _read)
    return {"read": _read, "run": run}


def _prepare_derive_case(
    tool: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    evidence_status: str = "complete",
) -> SimpleNamespace:
    binding, document, plan, _inputs = _synthetic_binding(
        tool, tmp_path / "doc", business_date="2026-10-28"
    )
    cases = _cases()
    annotation = H.merged_annotation(cases)
    run = document["runs"][0]
    bindings = _case_plan_bindings(run)
    plan_payload = _case_plan(
        tool, cases=cases, run_entry=run, bindings=bindings, business_date="2026-10-28"
    )
    case_plan_path = _write_json(tmp_path / "case-plan.json", plan_payload)
    stub = _install_derive_stub(
        tool,
        monkeypatch,
        document=document,
        plan=plan,
        cases=cases,
        annotation=annotation,
        evidence_status=evidence_status,
    )
    control = tool.v2._validate_case_plan_document(
        plan_payload, cases=cases, static_bindings={k: v for k, v in bindings.items() if k != "index_revision"}
    )["run_binding"]
    stub["read"].control = control
    stub["read"].turn_count = sum(len(case.turns) or 1 for case in cases)
    evidence_root = tmp_path / "evidence"
    evidence_root.mkdir(parents=True, exist_ok=True)
    for row in plan_payload["cases"]:
        for turn in row["turns"]:
            (evidence_root / turn["evidence_file"]).write_bytes(b"synthetic-ciphertext")
    (evidence_root / "manifest-0000.fernet").write_bytes(b"synthetic-manifest")
    key = tmp_path / "evidence.key"
    from cryptography.fernet import Fernet

    key.write_bytes(Fernet.generate_key())
    return SimpleNamespace(
        binding=binding,
        document=document,
        plan=plan,
        cases=cases,
        case_plan=case_plan_path,
        evidence_root=evidence_root,
        key=key,
        holdout_root=Path(document["holdout_root"]),
    )


def _derive_into(tool: Any, case: SimpleNamespace, out_dir: Path) -> dict[str, Any]:
    return tool.derive_cards(
        bindings=[case.binding],
        run_indexes=[0],
        evidence_dirs=[case.evidence_root],
        case_plans=[case.case_plan],
        evidence_key_file=case.key,
        out_dir=out_dir,
        compose=False,
        ledger_path=None,
    )


def test_derive_cards_writes_card_and_proof_path_safe(
    tool: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = _prepare_derive_case(tool, tmp_path, monkeypatch)
    out = tmp_path / "out"
    summary = _derive_into(tool, case, out)

    assert summary["ok"] is True
    assert summary["zero_call"]["new_requests"] == 0
    assert set(summary["verification"]) == set(tool.DERIVE_VERIFICATION_STAGES)
    card_files = sorted((out / "cards").glob("*.json"))
    proof_files = sorted((out / "proofs").glob("*.json"))
    assert len(card_files) == 1 and len(proof_files) == 1
    card = json.loads(card_files[0].read_text(encoding="utf-8"))
    hard.validate_hard_evidence_scorecard(
        card,
        total=int(card["total"]),
        run_id=str(case.document["runs"][0]["run_id"]),
        config_hash=str(case.document["config_sha256"]),
        expected_strata=None,
    )
    proof = json.loads(proof_files[0].read_text(encoding="utf-8"))
    assert proof["card_sha256"] == _sha(card_files[0])
    assert proof["verification"]["seal_state"]["basis"] == "sealed_evidence_manifest"
    # 新公开产物必须path-safe：绝对路径/密钥名/密文名一律记号化。
    for item in list(card_files) + list(proof_files):
        scanned = safe_output.scan_public_text(item.read_text(encoding="utf-8"))
        assert scanned["clean"] is True, (item.name, scanned["counts"])
    assert str(tmp_path) not in json.dumps(summary, ensure_ascii=False)


def test_derive_cards_is_deterministic_for_the_same_input(
    tool: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = _prepare_derive_case(tool, tmp_path, monkeypatch)
    out = tmp_path / "out-deterministic"
    first = _derive_into(tool, case, out)
    first_tree = _tree(out)
    first_summary = json.dumps(first, ensure_ascii=False, sort_keys=True)

    for item in sorted(out.rglob("*"), reverse=True):
        if item.is_file():
            item.unlink()
        elif item.is_dir():
            item.rmdir()
    out.rmdir()
    second = _derive_into(tool, case, out)
    assert _tree(out) == first_tree
    assert json.dumps(second, ensure_ascii=False, sort_keys=True) == first_summary
    print(
        "FU2-DETERMINISM",
        json.dumps(
            {
                "files": {name: first_tree[name] for name in sorted(first_tree)},
                "summary_sha256": hashlib.sha256(first_summary.encode("utf-8")).hexdigest(),
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
    )
    # 跨目录：卡与组合不含路径，必须逐字节相同（证明卡本身与输出位置无关）。
    other = tmp_path / "out-other-dir"
    _derive_into(tool, case, other)
    assert _sha(out / "cards" / sorted(p.name for p in (out / "cards").glob("*.json"))[0]) == _sha(
        other / "cards" / sorted(p.name for p in (other / "cards").glob("*.json"))[0]
    )


@pytest.mark.parametrize(
    ("case_name", "expected_code"),
    [
        ("bad_binding_sha", "run_binding_invalid"),
        ("scenario_binding_changed", "scenario_binding_changed"),
        ("case_count_changed", "scenario_subset_changed"),
        ("bad_case_plan_schema", "case_plan_invalid"),
        ("missing_turn", "case_plan_coverage_invalid"),
        ("duplicate_evidence_file", "case_plan_evidence_file_duplicate"),
    ],
)
def test_derive_cards_refuses_broken_bindings(
    tool: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    case_name: str,
    expected_code: str,
) -> None:
    case = _prepare_derive_case(tool, tmp_path, monkeypatch)
    document = case.document
    if case_name == "bad_binding_sha":
        # 真绑定校验器生效：改盘上 binding 的 binding_sha256 → 固定码拒绝。
        broken = json.loads(case.binding.read_text(encoding="utf-8"))
        broken["binding_sha256"] = "0" * 64
        case.binding.write_text(json.dumps(broken), encoding="utf-8")
    elif case_name == "scenario_binding_changed":
        original_loader = tool.load_v3_bundle

        def _tampered_loader(inputs: Any, _orig: Any = original_loader) -> Any:
            bundle = _orig(inputs)
            base = bundle.contract

            class _Tampered:
                def binding(self, scenario: str) -> dict[str, str]:
                    binding = dict(base.binding(scenario))
                    binding["assignment_sha256"] = "f" * 64
                    return binding

                def subset(self, scenario: str) -> Any:
                    return base.subset(scenario)

                def ingest_plan(self, scenario: str) -> Any:
                    return base.ingest_plan(scenario)

                def safe_summary(self) -> dict[str, Any]:
                    return base.safe_summary()

            bundle.contract = _Tampered()
            return bundle

        monkeypatch.setattr(tool, "load_v3_bundle", _tampered_loader)
    elif case_name == "case_count_changed":
        changed = json.loads(json.dumps(case.document))
        changed["runs"][0]["case_count"] = int(changed["runs"][0]["case_count"]) + 1
        monkeypatch.setattr(tool.v2, "load_run_binding", lambda path: changed)
    elif case_name == "bad_case_plan_schema":
        payload = json.loads(case.case_plan.read_text(encoding="utf-8"))
        payload["schema_version"] = "p2-hard-evidence-caseplan/v0.0-old"
        case.case_plan.write_text(json.dumps(payload), encoding="utf-8")
    elif case_name == "missing_turn":
        payload = json.loads(case.case_plan.read_text(encoding="utf-8"))
        payload["cases"][0]["turns"] = payload["cases"][0]["turns"][:-1]
        case.case_plan.write_text(json.dumps(payload), encoding="utf-8")
    elif case_name == "duplicate_evidence_file":
        payload = json.loads(case.case_plan.read_text(encoding="utf-8"))
        rows = [row for row in payload["cases"] if row["turns"]]
        first = rows[0]["turns"][0]["evidence_file"]
        rows[-1]["turns"][-1]["evidence_file"] = first
        case.case_plan.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises((tool.EntryError, tool.v2.EntryError)) as caught:
        _derive_into(tool, case, tmp_path / ("out-" + case_name))
    assert caught.value.code == expected_code


def test_derive_cards_refuses_seal_missing(
    tool: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = _prepare_derive_case(tool, tmp_path, monkeypatch)
    (case.evidence_root / "manifest-0000.fernet").unlink()
    with pytest.raises((tool.EntryError, tool.v2.EntryError)) as caught:
        _derive_into(tool, case, tmp_path / "out-seal")
    assert caught.value.code == "evidence_seal_missing"


# --------------------------------------------------------------------------- #
# 5. 输出目录：仓库 / 批次 / 冻结 holdout / 归一化 / 链接
# --------------------------------------------------------------------------- #


def _prepare_link(link: Path, target: Path) -> tuple[bool, str]:
    """尝试造目录链接（symlink → junction）；都不可用时返回不可用原因。"""
    try:
        link.symlink_to(target, target_is_directory=True)
        return True, "symlink"
    except (OSError, NotImplementedError):
        pass
    try:
        link.parent.mkdir(parents=True, exist_ok=True)
        completed = __import__("subprocess").run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
    except Exception:  # noqa: BLE001 - 环境不允许链接：登记不可用
        return False, "unavailable"
    if completed.returncode == 0 and link.exists():
        return True, "junction"
    return False, "unavailable"


def test_derive_cards_refuses_forbidden_and_normalized_output_paths(
    tool: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = _prepare_derive_case(tool, tmp_path, monkeypatch)
    batch_root = tmp_path / "original-batch"
    batch_root.mkdir(parents=True, exist_ok=True)
    holdout_root = case.holdout_root
    repo = tool.PROJECT_ROOT

    negatives = {
        "repo_root": (repo / "tmp-fu2-derive-out", "derive_output_in_forbidden_root"),
        "repo_dotdot": (
            repo / "tmp-fu2-derive-out" / ".." / "tmp-fu2-derive-out",
            "derive_output_in_forbidden_root",
        ),
        "repo_case_variant": (
            Path(str(repo).upper()) / "tmp-fu2-derive-out",
            "derive_output_in_forbidden_root",
        ),
        "repo_trailing_slash": (repo / "tmp-fu2-derive-out" / "", "derive_output_in_forbidden_root"),
        "repo_dot_backslash": (repo / "." / "tmp-fu2-derive-out", "derive_output_in_forbidden_root"),
        "var_dir": (repo / "var" / "tmp-fu2-derive-out", "derive_output_in_forbidden_root"),
        "batch_root": (batch_root / "cards", "derive_output_in_forbidden_root"),
        "holdout_root": (holdout_root / "derived", "derive_output_in_forbidden_root"),
    }
    for label, (path, expected) in negatives.items():
        with pytest.raises((tool.EntryError, tool.v2.EntryError)) as caught:
            tool.derive_cards(
                bindings=[case.binding],
                run_indexes=[0],
                evidence_dirs=[case.evidence_root],
                case_plans=[case.case_plan],
                evidence_key_file=case.key,
                out_dir=path,
                batch_roots=[batch_root],
                compose=False,
            )
        assert caught.value.code == expected, label
        assert not Path(path).exists(), label

    # 链接负例：仓外目录里放一个指向仓库的链接，链接本身不得被当作"仓外输出"。
    link = tmp_path / "link-into-repo"
    available, kind = _prepare_link(link, repo)
    if available:
        try:
            with pytest.raises((tool.EntryError, tool.v2.EntryError)) as caught:
                tool.derive_cards(
                    bindings=[case.binding],
                    run_indexes=[0],
                    evidence_dirs=[case.evidence_root],
                    case_plans=[case.case_plan],
                    evidence_key_file=case.key,
                    out_dir=link / "derived",
                    compose=False,
                )
            assert caught.value.code == "derive_output_in_forbidden_root"
        finally:
            if kind == "junction":
                link.rmdir()
    else:
        # 环境不允许链接：不静默跳过，登记为"不可用"（其余负例仍生效）。
        assert kind == "unavailable"

    # 已存在且非空的输出目录也要拒（既有 require_new_or_empty_dir 约定）。
    nonempty = tmp_path / "nonempty"
    nonempty.mkdir(parents=True, exist_ok=True)
    (nonempty / "keep.txt").write_text("x", encoding="utf-8")
    with pytest.raises((tool.EntryError, tool.v2.EntryError)) as caught:
        tool.derive_cards(
            bindings=[case.binding],
            run_indexes=[0],
            evidence_dirs=[case.evidence_root],
            case_plans=[case.case_plan],
            evidence_key_file=case.key,
            out_dir=nonempty,
            compose=False,
        )
    assert caught.value.code == "output_not_empty"


# --------------------------------------------------------------------------- #
# 6. 四场景合成（官方 compose + 官方组合校验）
# --------------------------------------------------------------------------- #


def test_four_synthetic_derived_runs_compose_with_official_validators(
    tool: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import test_p2_holdout_scenarios as S

    # 目录依赖（FU-2 收尾）：复用的 ``test_p2_holdout_scenarios.package`` 夹具，其 ingest plan
    # 用**仓库根相对路径**指向 ``fixtures/acceptance`` 语料；而 ``IngestSource.__post_init__``
    # 用 ``Path(path).is_file()`` 按当前工作目录解析（产品侧既有约定，路径守卫本身不改）。
    # 因此从 ``backend`` 目录调用 pytest 时该夹具在 ``scenario_ingest_invalid`` 处 fail closed。
    # 最小修正：本用例显式把工作目录固定到仓库根再构造夹具（monkeypatch 在 teardown 还原），
    # 与仓库标准调用（README：在仓库根运行）同条件；不改共享夹具、不加 skip、不改产品代码。
    monkeypatch.chdir(ROOT)
    package = S.package.__wrapped__(tmp_path, monkeypatch)
    contract, parts = S._derived_parts(package)
    runs = []
    for part in parts:
        plan = part["plan"]
        scenario = str(dict(plan.scenario_binding or {}).get("scenario_id") or "")
        runs.append(
            tool.DerivedRun(
                index=tool.v2.SCENARIO_ORDER.index(scenario),
                scenario=scenario,
                run_id=part["run_id"],
                plan_id=str(plan.plan_id),
                plan_sha256=str(plan.plan_sha256),
                binding_sha256="b" * 64,
                config_sha256="a" * 64,
                code_version="c" * 64,
                case_count=int(part["aggregate"]["total"]),
                turns_executed=int(part["turns_executed"]),
                turns_planned=int(part["turns_executed"]),
                card=part["aggregate"],
                plan=plan,
                contract=contract,
                scenario_binding=dict(part["binding"]["scenario_binding"]),
                pipeline_version="syn-pipeline",
                provider={"chat": "mock"},
                authorized_delta=None,
                identity={"original_identity": {}, "source_identity_summary": {}},
                evidence_tree={},
                case_plan_sha256="d" * 64,
                card_sha256=payload_sha256(part["aggregate"]),
                seal_state={"verified": True},
                status_counts={},
            )
        )
    composition = tool._derive_composition(runs, gate_config_hash="e" * 64)
    assert composition["total"] == 30
    assert composition["turns_planned"] == composition["turns_executed"] == 36
    assert composition["status"] == "complete"
    assert composition["release_ready"] is False

    duplicate = list(runs)
    duplicate[-1] = tool.DerivedRun(**{**{name: getattr(runs[0], name) for name in runs[0].__slots__}})
    with pytest.raises((tool.EntryError, tool.v2.EntryError)) as caught:
        tool._derive_composition(duplicate, gate_config_hash="e" * 64)
    assert caught.value.code == "derive_composition_scenario_duplicate"

    swapped = list(runs)
    swapped[1], swapped[2] = swapped[2], swapped[1]
    with pytest.raises((tool.EntryError, tool.v2.EntryError)) as caught:
        tool._derive_composition(swapped, gate_config_hash="e" * 64)
    assert caught.value.code == "derive_composition_invalid"
    assert caught.value.detail == "scenario_subset_mismatch"


def test_derive_card_core_is_threshold_neutral_and_deterministic() -> None:
    """派生核心只调用官方卡校验；同输入两次派生逐值相同（阈值不放宽）。"""
    from types import SimpleNamespace as NS

    cases = H.make_cases(6)
    annotation = H.merged_annotation(cases)
    audits = [H.make_audit(case, H.build_evidence(units=[])) for case in cases]
    plan_meta = {
        "thresholds_approved": False,
        "execution_mode": "live",
        "real_calls": 0,
        "run_id": "syn-fu2-run",
        "config_hash": "a" * 64,
        "expected_strata": _strata(cases),
    }
    summary = annotation.public_summary()
    spec = importlib.util.spec_from_file_location("_p2_fu2_core_entry", TOOL_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    tool = module
    first = tool._derive_card_core(
        cases=cases,
        annotation=annotation,
        audits=audits,
        compat="p2-refusal-compat/v0.6",
        source_identity=hard.UNRESOLVED_SOURCE_IDENTITY,
        plan_meta=plan_meta,
        annotation_summary=summary,
    )
    second = tool._derive_card_core(
        cases=cases,
        annotation=annotation,
        audits=audits,
        compat="p2-refusal-compat/v0.6",
        source_identity=hard.UNRESOLVED_SOURCE_IDENTITY,
        plan_meta=plan_meta,
        annotation_summary=summary,
    )
    assert payload_sha256(first) == payload_sha256(second)
    assert first["thresholds_approved"] is False
    assert first["total"] == len(cases)
    assert first["hard_evidence"]["verified"] is False  # 未批准阈值：不得自报 verified

"""从改后 v3 入口反向重建改前版本，并用基线 SHA 自证重建精确。

基线（改前）SHA-256 = 5f9dc3913e8d3aec8a795b40b82a60dd8ff32406cc2d3a42b37b8322d4201812
若重建文件 SHA 与之逐字节相同，则由二者产生的 unified diff 可信。
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

REPO = Path(r"D:\GPT项目\市场部AI知识库")
SRC = REPO / "tools" / "p2_h2_v3_controlled_execute.py"
OUT = Path(r"D:\mktkb-p2-h2v3-20261115\r0-fix\p2_h2_v3_controlled_execute.before.py")
BASE_SHA = "5f9dc3913e8d3aec8a795b40b82a60dd8ff32406cc2d3a42b37b8322d4201812"

TEXT = SRC.read_text(encoding="utf-8")

REVERSALS: list[tuple[str, str]] = [
    (
        "from dataclasses import dataclass, field",
        "from dataclasses import dataclass",
    ),
    (
        """与 v2 入口的差异（仅这五处）：
- **loader**：``p2_holdout_scenarios_v3.load_v3_scenario_contract``（v3 语料根/保管件）；
- **source-map 分发**：``p2_holdout_v3_scoring.dispatched_scoring_map``（/v0.2）；
- **per-run business_date**：每 run 自己的 L1 日期（``p2_holdout_run_date``），
  ``rag_business_date == manifest_business_date == run_date``；binding 文档一 run 一份；
- **预算 50**：进程内在导入前显式设置 ``MKTKB_PROJECT_TOTAL_LIMIT_CNY=50``，
  使 ``p2_holdout_plan.H2_PROJECT_TOTAL_LIMIT_CNY`` 与 ``budget.json`` 的 ``limit_cny`` 逐值一致。
  调用方若显式设了别的值，本入口拒绝（不静默改写主人给的上限）；
- **执行层 delta 透传**：check 层已授权的 ``authorized_delta``（index_embedding 批数
  9/10/13/15）显式传给执行核心（``_execution_contract`` → 只放宽这一格的
  ``_V3BatchContract``），否则 ``p2_runner`` 会按冻结 ``RECIPES`` 逐值重建并拒整 run。
""",
        """与 v2 入口的差异（仅这四处）：
- **loader**：``p2_holdout_scenarios_v3.load_v3_scenario_contract``（v3 语料根/保管件）；
- **source-map 分发**：``p2_holdout_v3_scoring.dispatched_scoring_map``（/v0.2）；
- **per-run business_date**：每 run 自己的 L1 日期（``p2_holdout_run_date``），
  ``rag_business_date == manifest_business_date == run_date``；binding 文档一 run 一份；
- **预算 50**：进程内在导入前显式设置 ``MKTKB_PROJECT_TOTAL_LIMIT_CNY=50``，
  使 ``p2_holdout_plan.H2_PROJECT_TOTAL_LIMIT_CNY`` 与 ``budget.json`` 的 ``limit_cny`` 逐值一致。
  调用方若显式设了别的值，本入口拒绝（不静默改写主人给的上限）。
""",
    ),
    (
        '''@dataclass(frozen=True, repr=False)
class _V3BatchContract(ValidatedScenarioContract):
    """在冻结契约之上**只**放宽 ``index_embedding.requests`` 一格的执行期复算。

    冻结 ``ValidatedScenarioContract.validate_run`` 用 v2 配方（RECIPES=8/9/11/13）重建
    期望计划并逐值比较；v3 计划按语料实测 B=9/10/13/15 生成。``p2_live`` 的
    ``validate_scenario_execution`` 会在首个预留前再调一次 ``validate_run``，且只认
    ``isinstance(..., ValidatedScenarioContract)``。本子类继承同一封印类：仅当「其余逐值
    相同、唯一差异是 index_embedding 项的 requests、且该值等于 v3 派生值」时放行；其余任何
    差异仍按原码 ``scenario_plan_mismatch`` 拒绝。产品/评测模块一字未改。

    ``_authorized`` 是 **check 层已授权** 的 delta（``contract_validate_run.authorized_delta``）：
    执行层不是自行放宽，而是必须与授权值逐值一致才放行；缺授权则维持冻结契约的原始拒绝。
    """

    _authorized: Mapping[str, Any] | None = field(default=None, repr=False)

    def validate_run(self, plan, dataset, ingest):  # noqa: ANN001 - 与冻结签名一致
        try:
            super().validate_run(plan, dataset, ingest)
            return
        except ScenarioError as exc:
            if str(getattr(exc, "code", "")) != "scenario_plan_mismatch":
                raise
        binding = plan.scenario_binding
        scenario = str(dict(binding or {}).get("scenario_id") or "")
        expected = super().build_plan(
            scenario,
            plan_id=plan.plan_id,
            created_utc=plan.created_utc,
            plan_version=plan.plan_version,
            max_requests=plan.max_requests,
        )
        delta = _authorized_batch_delta(plan, expected, scenario)
        if not delta.get("ok"):
            raise ScenarioError("scenario_plan_mismatch")
        if self._authorized is None:
            # 执行层没拿到 check 层授权：不放宽（等价于冻结契约的原始拒绝）。
            raise ScenarioError("scenario_plan_mismatch")
        authorized, observed = dict(self._authorized), dict(delta["delta"])
        if (
            str(authorized.get("item_id")) != str(observed.get("item_id"))
            or int(authorized.get("plan_requests", -1)) != int(observed["plan_requests"])
            or int(authorized.get("contract_recipe_requests", -1))
            != int(observed["contract_recipe_requests"])
        ):
            # 授权值与执行期实测值不一致：拒绝，不按“较小者”凑合。
            raise ScenarioError("scenario_plan_mismatch")


def _wrap_v3_contract(
    contract: ValidatedScenarioContract, *, authorized: Mapping[str, Any] | None = None
) -> _V3BatchContract:
    return _V3BatchContract(
        contract._dataset,  # noqa: SLF001 - 同一进程内复用已校验字段
        contract._assignments,  # noqa: SLF001
        contract._bindings,  # noqa: SLF001
        contract._ingest,  # noqa: SLF001
        contract._proof,  # noqa: SLF001
        contract._axis_counts,  # noqa: SLF001
        contract._gaps,  # noqa: SLF001
        None if authorized is None else dict(authorized),
    )


def _execution_contract(
    bundle: V3Bundle,
    plan: P2RunPlan,
    contract_state: Mapping[str, Any],
    scenario: str,
) -> ValidatedScenarioContract:
    """把 check 层已授权的 delta 显式交给执行层（v2 执行核心只认 ``ValidatedScenarioContract``）。

    - 计划与 v2 配方逐值相同（``contract_state.code is None``）→ 原契约原样返回，v2 行为不变；
    - check 层给出 ``authorized_delta`` → 三方逐值校验（授权值 == 计划值 == census 派生值）
      后返回只放宽这一格的子类；
    - 其余任何形状 → 拒绝，绝不“顺手放宽”。
    """
    if contract_state.get("ok") is not True:
        _refuse("scenario_plan_mismatch", str(contract_state.get("code") or ""))
    authorized = contract_state.get("authorized_delta")
    if not authorized:
        if contract_state.get("code") is not None:
            _refuse("scenario_plan_mismatch", str(contract_state.get("code") or ""))
        return bundle.contract
    delta = dict(authorized)
    items = [item for item in plan.items if item.operation == "index_embedding"]
    if len(items) != 1:
        _refuse("exec_contract_invalid", "ingest_item")
    derived = _v3_ingest_batches(scenario)
    if not (
        str(delta.get("item_id")) == str(items[0].item_id)
        and int(delta.get("plan_requests", -1)) == int(items[0].requests) == int(derived)
        and int(delta.get("contract_recipe_requests", -1)) > 0
        and str(delta.get("derived_from")) == "v3_ingest_batch_census"
    ):
        _refuse("exec_contract_invalid", "authorized_delta")
    return _wrap_v3_contract(bundle.contract, authorized=delta)''',
        '''class _V3BatchContract(ValidatedScenarioContract):
    """在冻结契约之上**只**放宽 ``index_embedding.requests`` 一格的执行期复算。

    冻结 ``ValidatedScenarioContract.validate_run`` 用 v2 配方（RECIPES=8/9/11/13）重建
    期望计划并逐值比较；v3 计划按语料实测 B=9/10/13/15 生成。``p2_live`` 的
    ``validate_scenario_execution`` 会在首个预留前再调一次 ``validate_run``，且只认
    ``isinstance(..., ValidatedScenarioContract)``。本子类继承同一封印类：仅当「其余逐值
    相同、唯一差异是 index_embedding 项的 requests、且该值等于 v3 派生值」时放行；其余任何
    差异仍按原码 ``scenario_plan_mismatch`` 拒绝。产品/评测模块一字未改。
    """

    def validate_run(self, plan, dataset, ingest):  # noqa: ANN001 - 与冻结签名一致
        try:
            super().validate_run(plan, dataset, ingest)
            return
        except ScenarioError as exc:
            if str(getattr(exc, "code", "")) != "scenario_plan_mismatch":
                raise
        binding = plan.scenario_binding
        scenario = str(dict(binding or {}).get("scenario_id") or "")
        expected = super().build_plan(
            scenario,
            plan_id=plan.plan_id,
            created_utc=plan.created_utc,
            plan_version=plan.plan_version,
            max_requests=plan.max_requests,
        )
        delta = _authorized_batch_delta(plan, expected, scenario)
        if not delta.get("ok"):
            raise ScenarioError("scenario_plan_mismatch")


def _wrap_v3_contract(contract: ValidatedScenarioContract) -> _V3BatchContract:
    return _V3BatchContract(
        contract._dataset,  # noqa: SLF001 - 同一进程内复用已校验字段
        contract._assignments,  # noqa: SLF001
        contract._bindings,  # noqa: SLF001
        contract._ingest,  # noqa: SLF001
        contract._proof,  # noqa: SLF001
        contract._axis_counts,  # noqa: SLF001
        contract._gaps,  # noqa: SLF001
    )''',
    ),
    (
        """    exec_contract = _execution_contract(bundle, plan, contract_state, scenario)
    with wiring.dispatched_scoring_map(contract_v3.V3_SOURCE_MAP) as dispatch:""",
        """    with wiring.dispatched_scoring_map(contract_v3.V3_SOURCE_MAP) as dispatch:""",
    ),
    (
        """                contract=exec_contract,""",
        """                contract=bundle.contract,""",
    ),
]


def main() -> int:
    text = TEXT
    for old, new in REVERSALS:
        count = text.count(old)
        if count != 1:
            print(f"REVERSAL_NOT_UNIQUE count={count} for snippet head={old.splitlines()[0][:60]!r}")
            return 1
        text = text.replace(old, new)
    OUT.write_text(text, encoding="utf-8", newline="")
    sha = hashlib.sha256(OUT.read_bytes()).hexdigest()
    print("reconstructed_sha256", sha)
    print("baseline_sha256     ", BASE_SHA)
    print("match", sha == BASE_SHA)
    return 0 if sha == BASE_SHA else 1


if __name__ == "__main__":
    raise SystemExit(main())

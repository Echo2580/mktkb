import json
import pytest

from mktkb.evaluation import p2_holdout_scenarios as scenario
from test_p2_holdout_scenarios import package, _run_parts  # noqa: F401
from test_p2_h2_controlled_entry import entry  # noqa: F401


def test_retained_synthetic_parts_compose_with_official_composer(package, tmp_path, entry):
    dataset, _, paths, _, _, _ = package
    contract = scenario.load_scenario_contract(dataset, **paths)
    parts = _run_parts(contract)
    restored = []
    for number, part in enumerate(parts):
        part["binding"].update(binding_version="p2-binding/v0.1", complete=True,
                               missing=[], trace_identity_bound=True)
        root = tmp_path / str(number)
        run = root / "p2-run"
        run.mkdir(parents=True)
        (run / "holdout_scorecard.json").write_text(json.dumps(part["aggregate"]), encoding="utf-8")
        summary = {"binding": part["binding"], "run_id": part["run_id"], "status": part["status"],
                   "turns": {"executed": part["turns_executed"]}}
        (run / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
        result = entry._purge_plaintext_derivatives(root, contract.subset(contract.scenario_ids[number]))
        assert result["plaintext_clean"]
        assert not run.exists()
        saved = json.loads((root / "controlled" / "composition-part.json").read_text(encoding="utf-8"))
        restored.append({"plan": part["plan"], **saved})
    combined = scenario.compose_scenario_runs(contract, restored)
    assert combined["total"] == 30
    assert combined["release_ready"] is False


@pytest.mark.parametrize("mutation", ["provider_secret", "scenario_mismatch", "card_mismatch", "collision"])
def test_unsafe_or_mismatched_part_is_not_retained(package, tmp_path, entry, mutation):
    dataset, _, paths, _, _, _ = package
    contract = scenario.load_scenario_contract(dataset, **paths)
    part = _run_parts(contract)[0]
    if mutation == "provider_secret":
        part["binding"]["provider"] = {"api_key": "synthetic-secret"}
    elif mutation == "scenario_mismatch":
        part["binding"]["scenario_binding"] = contract.binding(contract.scenario_ids[1])
    else:
        part["aggregate"]["run_id"] = "other-run"
    root = tmp_path / "unsafe"
    if mutation == "collision":
        (root / "controlled").mkdir(parents=True)
        (root / "controlled" / "composition-part.json").write_text("{}", encoding="utf-8")
    run = root / "p2-run"
    run.mkdir(parents=True)
    (run / "holdout_scorecard.json").write_text(json.dumps(part["aggregate"]), encoding="utf-8")
    (run / "summary.json").write_text(json.dumps({"binding": part["binding"], "run_id": part["run_id"],
        "status": part["status"], "turns": {"executed": part["turns_executed"]}}), encoding="utf-8")
    result = entry._purge_plaintext_derivatives(root, contract.subset(contract.scenario_ids[0]))
    if mutation == "collision":
        assert result["composition_retention"] == "collision"
        assert not result["plaintext_clean"]
        assert (root / "controlled" / "composition-part.json").read_text(encoding="utf-8") == "{}"
    else:
        assert result["composition_retention"] == "unavailable"
        assert not (root / "controlled" / "composition-part.json").exists()
    assert not run.exists()

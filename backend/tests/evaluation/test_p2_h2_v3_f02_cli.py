"""Synthetic regressions for v3's CLI boundary around v2 controlled refusals."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from mktkb.evaluation import p2_holdout_plan


@pytest.fixture
def tool(monkeypatch):
    monkeypatch.setenv("MKTKB_PROJECT_TOTAL_LIMIT_CNY", "40.0")
    monkeypatch.setattr(p2_holdout_plan, "H2_PROJECT_TOTAL_LIMIT_CNY", 40.0)
    path = Path(__file__).resolve().parents[3] / "tools/p2_h2_v3_controlled_execute.py"
    spec = importlib.util.spec_from_file_location("p2_h2_v3_f02_cli_under_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    monkeypatch.setitem(sys.modules, "_p2_h2_controlled_execute_v2", None)
    spec.loader.exec_module(module)
    monkeypatch.chdir(path.parent.parent)
    return module


@pytest.fixture
def run_args(tmp_path: Path) -> list[str]:
    return [
        "run",
        "--run-index", "3",
        "--binding", str(tmp_path / "binding.json"),
        "--out-dir", str(tmp_path / "out"),
        "--evidence-root", str(tmp_path / "evidence"),
        "--seal-root", str(tmp_path / "seal"),
        "--evidence-key-file", str(tmp_path / "unused-evidence.key"),
        "--env-file", str(tmp_path / "unused.env"),
    ]


def test_run_cli_preserves_v2_binding_refusal(tool, run_args, tmp_path, capsys):
    code = tool.main(run_args)
    output = capsys.readouterr()
    payload = json.loads(output.out)

    assert payload == {
        "ok": False,
        "error_code": "run_binding_missing",
        "detail": "",
        "command": "run",
        "network": {"local": [], "external": []},
    }
    assert code == 2
    assert output.err == ""
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    ("controlled", "expected_code", "expected_exit"),
    [(True, "output_not_empty", 2), (False, "internal_error", 1)],
)
def test_run_cli_omits_exception_messages_and_calls_only_once(
    controlled, expected_code, expected_exit, tool, run_args, monkeypatch, capsys
):
    calls = []
    private_message = "SYNTHETIC-PRIVATE-DETAIL"

    def refuse(binding_path):
        calls.append(binding_path)
        if controlled:
            raise tool.v2.EntryError("output_not_empty", private_message)
        raise RuntimeError(private_message)

    monkeypatch.setattr(tool.v2, "load_run_binding", refuse)
    code = tool.main(run_args)
    output = capsys.readouterr()
    payload = json.loads(output.out)

    assert payload["ok"] is False
    assert payload["error_code"] == expected_code
    assert code == expected_exit
    assert private_message not in output.out + output.err
    assert len(calls) == 1


@pytest.mark.parametrize(("ok", "expected_exit"), [(True, 0), (False, 2)])
def test_run_cli_follows_run_result_with_succeeded_receipt(
    ok, expected_exit, tool, run_args, monkeypatch, capsys
):
    calls = []
    receipt = {"ok": ok, "status": "succeeded", "seal": {"sealed": True}}

    def completed_run(**kwargs):
        calls.append(kwargs)
        return {"ok": ok, "receipt": receipt}

    monkeypatch.setattr(tool, "run_command", completed_run)
    assert tool.main(run_args) == expected_exit
    assert json.loads(capsys.readouterr().out) == {"ok": ok, "receipt": receipt}
    assert len(calls) == 1

"""Reproduce baseline gaps using invented ASCII text and a synthetic case only."""
import json
from pathlib import Path
import subprocess
import sys
import types

ROOT = Path.cwd()
sys.path[:0] = [str(ROOT / 'backend/src'), str(ROOT / 'backend/tests')]
from evaluation.test_p2_holdout_scorecard import _value_case, _synthetic_dataset, _ledger, _codes_plan
import dataclasses

BASE = '09ddc87520576958ff4c19be16f245f8197fdfe5'
name = 'mktkb.evaluation._safe_diag_baseline_runner'
old = types.ModuleType(name)
old.__file__ = str(ROOT / 'backend/src/mktkb/evaluation/p2_runner.py')
sys.modules[name] = old
source = subprocess.check_output(['git', 'show', BASE + ':backend/src/mktkb/evaluation/p2_runner.py'])
exec(compile(source, old.__file__, 'exec'), old.__dict__)
case = dataclasses.replace(_value_case(), expected_sources=({'doc_code': 'ASCII_DOCUMENT_FRAGMENT'},))
card = old._holdout_scorecard(_ledger(), _synthetic_dataset((case,)), ingest_plan=_codes_plan(),
                            execution='dry_run', real_calls=0, binding={}, gate_config=None)
result = {'baseline_commit': BASE, 'synthetic_only': True, 'real_calls': 0,
          'diagnostics_missing': 'diagnostics' not in card,
          'ascii_source_fragment_exported': 'ASCII_DOCUMENT_FRAGMENT' in json.dumps(card)}
assert result['diagnostics_missing'] and result['ascii_source_fragment_exported']
Path(__file__).with_name('baseline-probe.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
print(json.dumps(result))

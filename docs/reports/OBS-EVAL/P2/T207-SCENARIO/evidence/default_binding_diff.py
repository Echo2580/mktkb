"""Synthetic default identity comparison; no sealed material or product startup."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import types
from types import SimpleNamespace

ROOT = Path.cwd()
sys.path.insert(0, str(ROOT / 'backend/src'))
BASE = 'a751889bd4673fe43ba9c631f4e2ea13ce4fe585'


def baseline(module):
    name = 'mktkb.evaluation._scenario_default_' + module
    result = types.ModuleType(name)
    sys.modules[name] = result
    result.__file__ = str(ROOT / 'backend/src/mktkb/evaluation' / (module + '.py'))
    source = subprocess.check_output(['git', 'show', BASE + ':backend/src/mktkb/evaluation/' + module + '.py'])
    exec(compile(source, result.__file__, 'exec'), result.__dict__)
    return result


from mktkb.evaluation import p2_holdout_plan, p2_runner
from mktkb.evaluation.product_adapter import P2RunDataset
from mktkb.evaluation.p2_scoring import load_p2_gate_config

old_contracts = baseline('p2_contracts')
old_plan = baseline('p2_holdout_plan')
old_runner = baseline('p2_runner')
kwargs = dict(cases=[('synthetic-default-' + str(i), 1 if i < 24 else 2) for i in range(30)],
              ingest_batches=13, plan_id='synthetic-default-plan', plan_version='v0.1',
              created_utc='2026-11-12T00:00:00+00:00')
before, after = old_plan.build_holdout_plan(**kwargs), p2_holdout_plan.build_holdout_plan(**kwargs)
assert before.as_dict() == after.as_dict() == old_contracts.P2RunPlan.from_dict(after.as_dict()).as_dict()
assert before.plan_sha256 == after.plan_sha256
dataset = P2RunDataset('public', (), dict(suite='public', dataset_version='synthetic-default',
    manifest_sha256='a' * 64, label_version='synthetic-default', case_count=0, strata={}))
adapter = SimpleNamespace(binding_components=lambda: dict(pipeline_version='synthetic-default',
    index_revision=1, provider={'chat': 'mock', 'embedding': 'mock', 'rerank': 'mock'}))
gate = load_p2_gate_config()
before_binding = old_runner._binding_state(adapter, dataset, 'synthetic-default-run', gate)
after_binding = p2_runner._binding_state(adapter, dataset, 'synthetic-default-run', gate)
assert before_binding == after_binding and after_binding['complete']
protected = [
    'docs/evaluation/p2-holdout-v2.manifest.json', 'docs/evaluation/p2-holdout-v2.source-map.json',
    'docs/evaluation/p2-h2-scenarios-v0_2.json', 'docs/evaluation/p2-h2-custody-annotations-v0_2.md',
    'docs/reports/OBS-EVAL/P2/T207/PM/T207-ingest-plan-H2.json',
    'docs/reports/OBS-EVAL/P2/T207-CUSTODY-V2/manager-acceptance.json',
    'docs/reports/OBS-EVAL/P2/T207-CUSTODY-V2/review-aggregate.json',
    'docs/evidence/LOCAL-R1-20261101/budget/live-ledger.jsonl',
    'docs/evidence/LOCAL-R1-20261101/budget/budget.json',
    'docs/evidence/LOCAL-R1-20261101/PM/P2-LIVE-GO.json',
]
subprocess.run(['git', 'diff', '--exit-code', BASE, '--', *protected], check=True, capture_output=True)
payload = dict(baseline_commit=BASE, default_plan_serialization_equal=True,
    default_plan_sha256=after.plan_sha256, default_binding_equal=True,
    default_config_hash=after_binding['config_hash'], protected_tracked_content_unchanged=True,
    protected_sha256={p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in protected})
Path(__file__).with_name('default-binding-differential.json').write_text(
    json.dumps(payload, indent=2) + '\n', encoding='utf-8')
print('default plan, serializer, binding/config hash and 10 protected files: PASS')

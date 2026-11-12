"""Fixed counts only, from this package's synthetic pytest directory."""
import json
from pathlib import Path

TEMP = Path('C:/Users/dell1712/.codex/visualizations/2026/11/12/01a1cd24-bccf-7e00-80df-0b75f57f7d1c/t207-temp/scenario-finish/regression')
rows = []
for path in sorted(TEMP.glob('test_cli_batch_real_product_st*/batch/scenario_composition.json')):
    card = json.loads(path.read_text(encoding='utf-8'))
    row = {k: card[k] for k in ('schema_version', 'status', 'total', 'passed', 'failed', 'errors',
        'executed', 'turns_planned', 'turns_executed', 'not_started', 'real_calls', 'release_ready')}
    row['runtime_axis_evidence_produced'] = card['annotation']['runtime_axis_evidence_produced']
    row['run_statuses'] = [r['status'] for r in card['runs']]
    row['block_codes'] = sorted({b['code'] for b in card['blocks']})
    rows.append(row)
assert len(rows) == 2 and {r['status'] for r in rows} == {'complete', 'partial'}
assert all(r['real_calls'] == 0 and r['release_ready'] is False for r in rows)
Path(__file__).with_name('synthetic-summary.json').write_text(
    json.dumps({'synthetic_only': True, 'observations': rows}, indent=2) + '\n', encoding='utf-8')
print(json.dumps(rows))

"""Copy only validated aggregate counts from the final synthetic pytest directory."""
import json
from pathlib import Path
import sys

ROOT = Path.cwd()
sys.path.insert(0, str(ROOT / 'backend/src'))
from mktkb.evaluation.p2_diagnostics import validate_scorecard

temp = Path(sys.argv[1])
records = {}
for label, pattern in {
    'normal_30': 'test_true_runner_normal_30_mat*/**/holdout_scorecard.json',
    'partial_21_1_8': 'test_true_runner_stops_after_2*/**/holdout_scorecard.json',
    'json_reason': 'test_real_adapter_json_failure*/**/holdout_scorecard.json',
}.items():
    paths = sorted(temp.glob(pattern))
    assert len(paths) == 1, (label, len(paths))
    card = json.loads(paths[0].read_text(encoding='utf-8'))
    validate_scorecard(card, total=card['total'], run_id=card['run_id'], config_hash=card['config_hash'])
    d = card['diagnostics']
    refusal = d['refusal_confusion']
    def ratio(a, b):
        return a / b if b else None
    records[label] = {key: d[key] for key in ('counts', 'refusal_confusion', 'model_failure_reasons',
                    'source', 'by_stratum', 'classification_status', 'hard_failure_evidence')}
    records[label]['refusal_metrics'] = {
        'precision': ratio(refusal['tp'], refusal['tp'] + refusal['fp']),
        'recall': ratio(refusal['tp'], refusal['tp'] + refusal['fn']),
        'false_refusal': ratio(refusal['fp'], refusal['fp'] + refusal['tn'])}
records['scope'] = 'synthetic_only_not_real_quality'
Path(__file__).with_name('synthetic-summary.json').write_text(json.dumps(records, indent=2) + '\n', encoding='utf-8')
print(json.dumps({label: records[label]['counts'] for label in ('normal_30', 'partial_21_1_8', 'json_reason')}))

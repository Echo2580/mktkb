"""AST-extracted shape_flags only; synthetic payloads, no real loader/main."""
import ast
import copy
import hashlib
import json
from pathlib import Path

script = Path(__file__).resolve().parents[1] / 'controlled_target_shape.py'
raw = script.read_bytes()
tree = ast.parse(raw)
function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'shape_flags')
namespace = {}
exec(compile(ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[])), '<synthetic-shape>', 'exec'), namespace)
shape = namespace['shape_flags']
names = {'entity_key_null_present', 'entity_key_other_type_present', 'empty_entity_key_string_present',
         'entity_type_invalid_present', 'filter_non_scalar_value_present', 'filter_non_mapping_present',
         'target_fields_mismatch_present'}
target = dict(entity_type='PRIVATE-ASCII-TYPE', entity_key='PRIVATE-ASCII-KEY', filters={'PRIVATE-ASCII-FIELD': 'PRIVATE-ASCII-VALUE'})
case = {'case_id': 'PRIVATE-ASCII-CASE', 'axes': {axis: {'targets': []} for axis in ('safety', 'cross_user', 'cross_entity', 'stale_source')}}
case['axes']['cross_entity']['targets'] = [target]
baseline = {'cases': [copy.deepcopy(case) for _ in range(30)]}
expected_changes = [(None, None), ('entity_key', None), ('entity_key', {'PRIVATE-ASCII-KEY': 1}),
    ('entity_key', ''), ('entity_type', None), ('filters', {'PRIVATE-ASCII-FIELD': ['PRIVATE-ASCII-VALUE']}),
    ('filters', ['PRIVATE-ASCII-VALUE']), ('PRIVATE-ASCII-FIELD', 'PRIVATE-ASCII-VALUE')]
expected_flags = [None, 'entity_key_null_present', 'entity_key_other_type_present', 'empty_entity_key_string_present',
    'entity_type_invalid_present', 'filter_non_scalar_value_present', 'filter_non_mapping_present', 'target_fields_mismatch_present']
for (key, value), flag in zip(expected_changes, expected_flags):
    payload = copy.deepcopy(baseline)
    if key is not None: payload['cases'][17]['axes']['cross_entity']['targets'][0][key] = value
    result = shape(payload)
    assert set(result) == names and all(type(v) is bool for v in result.values())
    assert {k for k, v in result.items() if v} == ({flag} if flag else set())
    assert 'PRIVATE-ASCII' not in json.dumps(result)
for payload in ({'cases': []}, {'cases': [{} for _ in range(30)]}):
    try: shape(payload)
    except (ValueError, KeyError): pass
    else: raise AssertionError('malformed input unexpectedly accepted')
result = dict(verdict='PASS', synthetic_checks=10, real_attachment_loaded=False, main_executed=False,
              script_sha256=hashlib.sha256(raw).hexdigest())
Path(__file__).with_name('shape-probe.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
print(json.dumps(result))

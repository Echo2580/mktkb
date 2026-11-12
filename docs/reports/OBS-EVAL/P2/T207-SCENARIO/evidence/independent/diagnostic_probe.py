"""Execute only AST-extracted error formatting with synthetic exceptions."""
import ast
import hashlib
import json
from pathlib import Path

source_path = Path(__file__).resolve().parents[1] / 'controlled_binding_check.py'
source = source_path.read_bytes()
tree = ast.parse(source)
assignment = next(n for n in tree.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'SAFE_FAILURE_CODES' for t in n.targets))
codes = frozenset(ast.literal_eval(assignment.value.args[0]))
assert len(codes) == 28 and all(type(code) is str for code in codes)
main_guard = tree.body[-1]
handler = main_guard.body[0].handlers[0]
function = ast.FunctionDef(name='format_failure', args=ast.arguments(posonlyargs=[], args=[ast.arg(arg='exc')], kwonlyargs=[], kw_defaults=[], defaults=[]), body=handler.body + [ast.Return(ast.Name(id='result', ctx=ast.Load()))], decorator_list=[])
module = ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[]))
namespace = {'SAFE_FAILURE_CODES': codes}
exec(compile(module, '<synthetic-fixed-code-probe>', 'exec'), namespace)

class PrivateException(Exception):
    def __str__(self):
        raise AssertionError('exception text must never be accessed')

class TextSubclass(str):
    pass

cases = [(None, 'actual_binding_check_failed'), ('PRIVATE-ASCII-PROBE', 'actual_binding_check_failed'),
         ('scenario_review_invalid\nPRIVATE-ASCII-PROBE', 'actual_binding_check_failed'),
         ({'PRIVATE-ASCII-PROBE': 1}, 'actual_binding_check_failed'),
         (TextSubclass('scenario_review_invalid'), 'actual_binding_check_failed'),
         ('scenario_review_invalid', 'scenario_review_invalid'),
         ('P2_DATASET_INVALID', 'P2_DATASET_INVALID')]
for value, expected in cases:
    exc = PrivateException()
    if value is not None: exc.code = value
    result = namespace['format_failure'](exc)
    assert result['code'] == expected and result['status'] == 'FAIL'
    assert result['private_detail_export'] is False and result['quality_released'] is False
    assert 'PRIVATE-ASCII-PROBE' not in json.dumps(result)
payload = dict(verdict='PASS', synthetic_checks=len(cases), whitelist_count=len(codes),
               real_loader_imported=False, real_attachment_loaded=False,
               controlled_script_sha256=hashlib.sha256(source).hexdigest())
Path(__file__).with_name('diagnostic-probe.json').write_text(json.dumps(payload, indent=2) + '\n', encoding='utf-8')
print(json.dumps(payload))

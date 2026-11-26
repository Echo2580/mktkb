"""Rebuild only five tracked baseline files without changing the checkout or index."""
from pathlib import Path
import subprocess

report = Path(__file__).resolve().parent
root = Path(__file__).resolve().parents[7]
paths = [
    'backend/src/mktkb/evaluation/p2_contracts.py',
    'backend/src/mktkb/evaluation/p2_authorization.py',
    'backend/src/mktkb/evaluation/p2_holdout_plan.py',
    'backend/src/mktkb/evaluation/p2_runner.py',
    'backend/src/mktkb/rag/budget.py',
]
base = report / 'baseline-src'
for path in paths:
    target = base / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(subprocess.check_output(['git', 'show', 'HEAD:' + path], cwd=root))
relative_base = base.relative_to(root).as_posix()
runner = (root / paths[3]).read_text(encoding='utf-8')
for new, old in [
    ('max_requests=plan.max_requests,', 'max_requests=int(plan.max_requests),'),
    ('requests_remaining=("unlimited" if plan.max_requests == "unlimited" else max(0, plan.max_requests - int(plan.total_requests))),',
     'requests_remaining=max(0, int(plan.max_requests) - int(plan.total_requests)),'),
    ('authorization.requests_remaining == "unlimited" or int(plan.total_requests) <= authorization.requests_remaining,',
     'int(plan.total_requests) <= int(authorization.requests_remaining),'),
    ('"max_requests": authorization.max_requests,', '"max_requests": int(authorization.max_requests),'),
    ('"requests_remaining": authorization.requests_remaining,', '"requests_remaining": int(authorization.requests_remaining),'),
]:
    if runner.count(new) != 1:
        raise RuntimeError(f'runner replacement is not unique: {new}')
    runner = runner.replace(new, old)
import hashlib
runner_bytes = runner.encode('utf-8')
if hashlib.sha256(runner_bytes).hexdigest() != '4efbed443c010886649938bb70674de733e88da0c0d5eb6c3cc805bfc5f38fac':
    raise RuntimeError('runner baseline reconstruction hash mismatch')
(base / paths[3]).write_bytes(runner_bytes)
with (report / 'incremental.diff').open('wb') as output:
    for path in paths:
        run = subprocess.run(['git', 'diff', '--no-index', '--', str(base / path), str(root / path)],
                             cwd=root, stdout=subprocess.PIPE)
        if run.returncode not in (0, 1):
            raise RuntimeError(f'diff failed: {path}')
        output.write(run.stdout)
    run = subprocess.run(['git', 'diff', '--no-index', '--', str(report / 'baseline-v3.py.txt'),
                          str(root / 'tools/p2_h2_v3_controlled_execute.py')], cwd=root, stdout=subprocess.PIPE)
    if run.returncode not in (0, 1):
        raise RuntimeError('v3 diff failed')
    output.write(run.stdout)
print('incremental.diff captured')

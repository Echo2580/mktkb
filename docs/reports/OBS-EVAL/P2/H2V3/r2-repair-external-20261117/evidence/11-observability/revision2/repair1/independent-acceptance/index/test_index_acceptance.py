"""Bounded independent driver; subprocesses are the harness, not product calls."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('independent_index_probe', HERE / 'index_probe.py')
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


def test_independent_real_index_matrix(tmp_path):
    workspace = Path(__file__).resolve()
    while not (workspace / 'backend/src/mktkb/rag/answer.py').is_file():
        workspace = workspace.parent
    root = tmp_path / 'matrix'
    root.mkdir()
    protected = workspace / 'backend/src/mktkb'
    before_hashes = {p: probe.sha(protected / p) for p in probe.AFTER}
    assert before_hashes == probe.AFTER, 'PRE_SOURCE_IDENTITY'
    for name, expected in probe.BEFORE.items():
        snapshot = workspace / '.tmp-r2-obs-baseline' / ('backend_src_mktkb_' + name.replace('/', '_'))
        assert probe.sha(snapshot) == expected, 'BASELINE_SNAPSHOT_IDENTITY'
        target = root / 'baseline-source' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(snapshot, target)
        assert probe.sha(target) == expected, 'BASELINE_COPY_IDENTITY'
    commands = []
    outputs = {}
    for mode in ('seed', 'baseline', 'off', 'on', 'failure'):
        output = root / (mode + '.json')
        command = [sys.executable, '-I', '-B', '-X', 'utf8', str(HERE / 'index_probe.py'), '--workspace', str(workspace), '--root', str(root), '--mode', mode, '--output', str(output)]
        try:
            completed = subprocess.run(command, cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=90, check=False)
            entry = {'mode': mode, 'command': command, 'exit': completed.returncode, 'stdout_sha256': probe.digest(completed.stdout.hex()), 'stderr_sha256': probe.digest(completed.stderr.hex()), 'timeout_seconds': 90, 'process_reaped': True}
        except subprocess.TimeoutExpired:
            entry = {'mode': mode, 'exit': None, 'timeout_seconds': 90, 'timed_out': True, 'process_reaped': True}
            commands.append(entry)
            (HERE / 'RUN-RECORD.json').write_text(json.dumps({'commands': commands, 'ok': False}, indent=2), encoding='utf-8')
            raise AssertionError('BOUNDED_WORKER_TIMEOUT')
        commands.append(entry)
        data = json.loads(output.read_text(encoding='utf-8')) if output.is_file() else {'ok': False, 'failure_code': 'NO_OUTPUT'}
        outputs[mode] = data
        # Save even on failure; immutable input sources are never overwritten.
        (HERE / 'RUN-RECORD.json').write_text(json.dumps({'commands': commands, 'outputs': outputs, 'pre_source_sha256': before_hashes, 'post_source_sha256': {p: probe.sha(protected / p) for p in probe.AFTER}}, ensure_ascii=False, indent=2), encoding='utf-8')
        assert completed.returncode == 0 and data.get('ok'), 'WORKER_' + mode + '_' + str(data.get('failure_code', data.get('exception_type', 'FAILED')))
    reference = outputs['baseline']['cases']
    comparisons = {}
    for case, value in reference.items():
        comparisons[case] = {}
        for mode in ('off', 'on', 'failure'):
            comparisons[case][mode] = value['core'] == outputs[mode]['cases'][case]['core']
    on = outputs['on']['cases']
    expected_statuses = {'joined': 'joined', 'missing': 'store_row_missing', 'ambiguous': 'store_row_ambiguous', 'document': 'not_applicable', 'multi_item_ask': 'item_filter_missing'}
    for case, status in expected_statuses.items():
        assert on[case]['observation']['statuses'] == [status], 'PUBLIC_STATUS_' + case
    assert on['empty']['observation']['empty'] == [True], 'EMPTY_NOT_REALIZED'
    assert on['large']['observation']['candidate_counts'] == [521], 'REAL_LARGE_COUNT'
    assert on['large']['observation']['truncated'] == [True], 'REAL_LARGE_TRUNCATION'
    assert on['pagination']['observation']['search_successes'] == on['pagination']['observation']['events'] == 3, 'PAGE_EVENT_COUNT'
    assert on['pagination']['observation']['page_has_more'] == [True, True, False], 'PAGE_EVENT_FLAGS'
    assert all(all(checks.values()) for checks in comparisons.values()), 'BUSINESS_EQUIVALENCE'
    after_hashes = {p: probe.sha(protected / p) for p in probe.AFTER}
    assert after_hashes == before_hashes, 'POST_SOURCE_IDENTITY'
    record = {'commands': commands, 'outputs': outputs, 'comparisons': comparisons, 'all_core_equal': True, 'pre_source_sha256': before_hashes, 'post_source_sha256': after_hashes, 'ok': True}
    (HERE / 'RUN-RECORD.json').write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')

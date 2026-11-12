"""Record only fixed guard counts from synthetic/offline pytest fixtures."""
import json
from pathlib import Path

import pytest

snapshots = []


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_teardown(item, nextitem):
    guard = item.funcargs.get('t09_network_guard')
    yield
    if guard is not None:
        snapshots.append(guard.snapshot())


def pytest_sessionfinish(session, exitstatus):
    external = sum(len(x['external']) for x in snapshots)
    payload = {'guarded_tests': len(snapshots), 'external_attempts': external,
               'external_empty': external == 0,
               'loopback_attempts': sum(len(x['local']) for x in snapshots),
               'pytest_exit_status': int(exitstatus)}
    Path(__file__).with_name('network-guard.json').write_text(
        json.dumps(payload, indent=2) + '\n', encoding='utf-8')

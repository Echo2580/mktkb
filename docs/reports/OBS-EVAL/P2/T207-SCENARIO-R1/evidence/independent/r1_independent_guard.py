"""Offline fixture guard with independent aggregate output only."""
import json
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path.cwd() / 'backend/tests'))
from acceptance.support.netguard import t09_network_guard

@pytest.fixture(autouse=True)
def enforce_network_guard(t09_network_guard):
    yield

snapshots = []

@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_teardown(item, nextitem):
    guard = item.funcargs.get('t09_network_guard')
    yield
    if guard is not None:
        snapshots.append(guard.snapshot())

def pytest_sessionfinish(session, exitstatus):
    external = sum(len(x['external']) for x in snapshots)
    payload = dict(guarded_tests=len(snapshots), external_attempts=external,
        loopback_attempts=sum(len(x['local']) for x in snapshots), pytest_exit_status=int(exitstatus))
    Path(__file__).with_name('network-guard.json').write_text(json.dumps(payload, indent=2) + '\n', encoding='utf-8')

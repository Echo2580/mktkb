"""Bounded local environment probes, no product execution or external request."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[5]
TEMP = Path('C:/Users/dell1712/.codex/visualizations/2026/11/12/01a1cd24-bccf-7e00-80df-0b75f57f7d1c/t207-temp')
PROBES = {
    'socketpair': 'import socket; a,b=socket.socketpair(); a.close(); b.close()',
    'asgi': '''import asyncio, httpx
async def app(scope, receive, send):
    await send({'type':'http.response.start','status':200,'headers':[]})
    await send({'type':'http.response.body','body':b'ok'})
async def main():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://local') as c:
        assert (await c.get('/')).text == 'ok'
asyncio.run(main())
''',
}

def main():
    TEMP.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, TEMP=str(TEMP), TMP=str(TEMP), MKTKB_NO_DOTENV='1')
    results = {}
    with tempfile.TemporaryFile(dir=TEMP) as target:
        target.write(b'probe')
        target.flush()
    for name, code in PROBES.items():
        try:
            result = subprocess.run([sys.executable, '-B', '-c', code], cwd=ROOT,
                                    env=env, capture_output=True, timeout=10)
            results[name] = {'status': 'pass' if result.returncode == 0 else 'failed',
                             'exit_code': result.returncode}
        except subprocess.TimeoutExpired:
            results[name] = {'status': 'timeout_10s', 'exit_code': None}
    paths = ['budget/live-ledger.jsonl', 'budget/budget.json', 'PM/P2-LIVE-GO.json']
    base = ROOT / 'docs/evidence/LOCAL-R1-20261101'
    hashes = {name: hashlib.sha256((base / name).read_bytes()).hexdigest() for name in paths}
    payload = {'schema_version': 'p2-t207-recovery-preflight/v0.1',
               'writable_temp': True, 'probes': results, 'protected_hashes': hashes,
               'product_tests': 0, 'real_requests': 0}
    output = Path(__file__).with_name('recovery-preflight.json')
    output.write_text(json.dumps(payload, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(payload))
    return int(any(item['status'] != 'pass' for item in results.values()))

if __name__ == '__main__':
    raise SystemExit(main())

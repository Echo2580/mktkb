"""Run original independent assertions unchanged; adapt only tool/output paths."""
from pathlib import Path
import hashlib

ROOT = next(p for p in Path(__file__).resolve().parents if (p / 'backend/src/mktkb').is_dir())
OLD = ROOT / 'docs/reports/OBS-EVAL/P2/H2V3/r2-repair-external-20261117/evidence/11-observability/revision2/independent-acceptance/contracts/contract_probe.py'
raw = OLD.read_bytes()
assert hashlib.sha256(raw).hexdigest() == 'cca7de10fd03f4437aa37354ef48d22f6d91f79901ca0926b72939af6eabe8bd'
source = raw.decode('utf-8')
source = source.replace("ROOT / '.tmp-r2-obs-acceptance-contracts'", "ROOT / '.tmp-r2-obs-acceptance-contracts-repair1'")
source = source.replace("parents[2] / 'work/safe_plan_projection.py'", "parents[2] / 'repair1/work/safe_plan_projection.py'")
assert source != raw.decode('utf-8')
exec(compile(source, str(OLD), 'exec'), {'__file__': str(OLD), '__name__': '__main__'})

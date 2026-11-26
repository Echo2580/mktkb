from pathlib import Path
import importlib.util
import json
import shutil
import pytest

ROOT = next(p for p in Path(__file__).resolve().parents if (p / 'backend/src/mktkb').is_dir())
REPAIR = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('obs_native_patch', Path(__file__).with_name('native_patch.py'))
tool = importlib.util.module_from_spec(spec); spec.loader.exec_module(tool)


@pytest.mark.parametrize('which', ['increment', 'cumulative'])
def test_exact_round_trip(tmp_path, which):
    forward = REPAIR / 'patches' / (which + '-source.patch')
    fm = REPAIR / 'patches' / (which + '-source.json')
    backward = REPAIR / 'patches' / (which + '-rollback.patch')
    bm = REPAIR / 'patches' / (which + '-rollback.json')
    manifest = json.loads(fm.read_text(encoding='utf-8'))
    originals = {}
    for path in manifest['files']:
        source = (REPAIR / 'baseline/evaluation_capture.py.before') if which == 'increment' else (ROOT / '.tmp-r2-obs-baseline' / path.replace('/', '_'))
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        originals[path] = target.read_bytes()
    assert tool.apply(tmp_path, forward, fm, False) == len(originals)
    assert all((tmp_path / p).read_bytes() == b for p,b in originals.items())
    assert tool.apply(tmp_path, forward, fm, True) == len(originals)
    for p, r in manifest['files'].items():
        assert tool.sha((tmp_path / p).read_bytes()) == r['after']
    assert tool.apply(tmp_path, backward, bm, True) == len(originals)
    assert all((tmp_path / p).read_bytes() == b for p,b in originals.items())
    first = next(iter(originals))
    with (tmp_path / first).open('ab') as f: f.write(b'x')
    corrupt = (tmp_path / first).read_bytes()
    with pytest.raises(ValueError, match='before_hash'):
        tool.apply(tmp_path, forward, fm, True)
    assert (tmp_path / first).read_bytes() == corrupt

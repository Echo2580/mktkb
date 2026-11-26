"""Apply a checked unified diff preserving each target's native EOL; --check by default."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import re
import tempfile

HUNK = re.compile(r'^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@')


def sha(data): return hashlib.sha256(data).hexdigest()


def transform(original, hunks):
    if b'\r\n' in original:
        if b'\n' in original.replace(b'\r\n', b''):
            raise ValueError('mixed_eol')
        eol = b'\r\n'
    else:
        eol = b'\n'
    old = original.replace(b'\r\n',b'\n').decode('utf-8').splitlines(keepends=True)
    out=[]; cursor=0
    for start, lines in hunks:
        at=start-1 if start else 0
        if at < cursor or at > len(old): raise ValueError('hunk_position')
        out.extend(old[cursor:at]); cursor=at
        for line in lines:
            op, value=line[0],line[1:]
            if op in ' -':
                if cursor >= len(old) or old[cursor] != value: raise ValueError('hunk_context')
                cursor+=1
            if op in ' +': out.append(value)
    out.extend(old[cursor:])
    return ''.join(out).encode('utf-8').replace(b'\n',eol)


def parse(text):
    rows=text.splitlines(keepends=True); files={}; i=0
    while i < len(rows):
        if not rows[i].startswith('--- a/'): raise ValueError('bad_header')
        path=rows[i][6:].strip(); i+=1
        if i>=len(rows) or rows[i].strip() != '+++ b/'+path: raise ValueError('bad_path')
        i+=1; hunks=[]
        while i<len(rows) and not rows[i].startswith('--- a/'):
            match=HUNK.match(rows[i])
            if not match: raise ValueError('bad_hunk')
            start=int(match.group(1)); old_count=int(match.group(2) or 1); new_count=int(match.group(4) or 1); i+=1
            block=[]
            while i<len(rows) and not rows[i].startswith(('@@ ', '--- a/')):
                if rows[i][:1] not in (' ', '+', '-'): raise ValueError('bad_hunk_line')
                block.append(rows[i]); i+=1
            if sum(line[0] in ' -' for line in block)!=old_count or sum(line[0] in ' +' for line in block)!=new_count: raise ValueError('bad_hunk_count')
            hunks.append((start, block))
        if path in files: raise ValueError('duplicate_path')
        files[path]=hunks
    return files


def apply(root, patch, manifest, do_apply):
    root=root.resolve(strict=True)
    data=json.loads(manifest.read_text(encoding='utf-8'))
    patch_bytes=patch.read_bytes()
    if sha(patch_bytes)!=data['patch_sha256']: raise ValueError('patch_hash')
    hunks=parse(patch_bytes.decode('utf-8'))
    if set(hunks)!=set(data['files']): raise ValueError('path_set')
    staged={}
    for path, record in data['files'].items():
        target=(root/path).resolve(strict=True)
        if root not in target.parents or not target.is_file(): raise ValueError('target_outside_root')
        original=target.read_bytes()
        if sha(original)!=record['before']: raise ValueError('before_hash')
        new=transform(original,hunks[path])
        if sha(new)!=record['after']: raise ValueError('after_hash')
        staged[target]=new
    if do_apply:
        for target, new in staged.items():
            fd, temp=tempfile.mkstemp(prefix='.obs-patch-', dir=target.parent)
            try:
                with os.fdopen(fd,'wb') as f: f.write(new)
                os.replace(temp,target)
            finally:
                if os.path.exists(temp): os.unlink(temp)
    return len(staged)


if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('--root',type=Path,required=True); p.add_argument('--patch',type=Path,required=True); p.add_argument('--manifest',type=Path,required=True); p.add_argument('--apply',action='store_true')
    a=p.parse_args()
    try: print('OK',apply(a.root,a.patch,a.manifest,a.apply))
    except Exception as e: print('ERROR',type(e).__name__,str(e)); raise SystemExit(1)

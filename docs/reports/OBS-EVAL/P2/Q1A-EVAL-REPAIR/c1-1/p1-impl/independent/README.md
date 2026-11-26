# C1-P1-IMPL independent verification — probes

Role: P1 **fresh independent acceptance** of the `stale_source` v1 classifier
(`backend/src/mktkb/evaluation/p2_stale_version_state.py`, SHA-256
`fed19144…dcf59`) and of the P4 adapter IR-01/IR-02/IR-03 repair
(`p2_evidence_axes_adapter_v2.py`, `8e0263d9…bd2d`). Not development, not
management; no developer test helper is imported for assertions.

## Run

```powershell
cd <repo>
$env:PYTHONDONTWRITEBYTECODE = '1'
$py = '.\.venv\Scripts\python.exe'
& $py docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/c1-1/p1-impl/independent/snapshot_start.py
& $py docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/c1-1/p1-impl/independent/probe_01_ir01_ast.py
& $py docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/c1-1/p1-impl/independent/probe_02_ir01_runtime.py
& $py docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/c1-1/p1-impl/independent/probe_03_ir02_ir03.py
& $py docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/c1-1/p1-impl/independent/probe_04_criterion.py
& $py docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/c1-1/p1-impl/independent/probe_04b_gaps.py
& $py docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/c1-1/p1-impl/independent/probe_05_tests.py
& $py docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/c1-1/p1-impl/independent/probe_07_preservation.py
& $py docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/c1-1/p1-impl/independent/probe_08_zero_call.py
```

The 98-item test run is recorded in `out/05-pytest.txt`; it was executed from
`backend/` with `-p no:cacheprovider`, an out-of-repo `--basetemp`, and
`PYTHONDONTWRITEBYTECODE=1`.

## Files

| file | purpose |
|---|---|
| `synth_stale.py` | independent K*/S_syn_k synthetic corpus (no real dataset literals) |
| `snapshot_start.py` / `out/00-snapshot-start.json` | baseline hashes, git state, untracked tree |
| `probe_01_ir01_ast.py` / `out/01-ir01-ast.json` | AST membership-site candidates + guard classification |
| `probe_02_ir01_runtime.py` / `out/02-ir01-runtime.json` | 8,792 adapter + 392 stale hostile-value mutations, site matrix, old-logic negative controls |
| `probe_03_ir02_ir03.py` / `out/03-ir02-ir03.json` | target-order permutations and key/filters consistency matrix |
| `probe_04_criterion.py` / `out/04-criterion.json` | 178 exact-code criterion checks (§7 14 rows, F-1..F-12, 21 codes, folding, N/A, counts, output) |
| `probe_04b_gaps.py` / `out/04b-gaps.json` | 26 edge rules, 6 divergences, 2 binding limitations, 3 criterion tensions, old-shape check |
| `probe_05_tests.py` / `out/05-test-quality.json` | AST test-quality audit (skip/xfail, weak assertions, code pinning) |
| `probe_07_preservation.py` / `out/07-preservation.json` | end-of-round comparison against the start baseline |
| `probe_08_zero_call.py` / `out/08-zero-call.json` | 7-layer positive control, negative control, external=0 |

`netguard.py` is the local guard used by probe 08. `out/` also contains the raw
pytest output and the end snapshot.

## Boundary

Synthetic/public data only. No real H2 question text, labels, answers, private
ciphertext, keys, `.env`, custody sessions or runbooks were opened. No product /
model / embedding / rerank / OCR / judge / retrieval / auth / balance call. No
change to developer files or frozen artifacts; no stage/commit/push; no branch
or worktree change.

The `rescore/evidence-r3/` files that appeared during this round were created by
a concurrent actor; they are not part of this package. Only directory names and
timestamps were observed to establish provenance; their contents were not used
as evidence and they were not modified here.

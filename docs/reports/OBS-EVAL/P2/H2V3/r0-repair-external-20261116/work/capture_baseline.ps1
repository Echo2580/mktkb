# Baseline capture (read-only). ASCII-only source: Windows PowerShell 5.1 parses .ps1 as ANSI,
# so every literal here must stay ASCII; the repo root is discovered from .git instead of a literal path.
# Output: <repo>/docs/reports/OBS-EVAL/P2/H2V3/r0-repair-external-20261116/evidence/00-baseline/
$ErrorActionPreference = 'Continue'

$dir = $PSScriptRoot
while ($dir -and -not (Test-Path (Join-Path $dir '.git'))) { $dir = Split-Path $dir -Parent }
if (-not $dir) { throw 'repo root not found' }
$repo = $dir

$out = Join-Path $repo 'docs\reports\OBS-EVAL\P2\H2V3\r0-repair-external-20261116\evidence\00-baseline'
New-Item -ItemType Directory -Force -Path $out | Out-Null
$stamp = Get-Date -Format 'yyyy-MM-ddTHH:mm:sszzz'

function Write-Text($name, $lines) {
    $p = Join-Path $out $name
    if ($null -eq $lines) { $lines = @() }
    if ($lines -is [string]) { $lines = @($lines) }
    [System.IO.File]::WriteAllLines($p, [string[]]$lines, (New-Object System.Text.UTF8Encoding($false)))
    Write-Output ("wrote " + $name + " lines=" + @($lines).Count)
}

function GitOut([string[]]$argv) {
    $res = & git -C $repo @argv 2>&1
    return @($res | ForEach-Object { [string]$_ })
}

Write-Text 'git-identity.txt' @(
    ("captured_at: " + $stamp),
    ("repo: " + $repo),
    ("branch: " + ((GitOut @('rev-parse','--abbrev-ref','HEAD')) -join '')),
    ("head: " + ((GitOut @('rev-parse','HEAD')) -join '')),
    ("head_subject: " + ((GitOut @('log','-1','--format=%s')) -join '')),
    ("staged_count: " + (@(GitOut @('diff','--cached','--name-only')) | Where-Object { $_ -ne '' }).Count),
    ("tracked_modified_count: " + (@(GitOut @('diff','--name-only')) | Where-Object { $_ -ne '' }).Count),
    ("untracked_count: " + (@(GitOut @('ls-files','--others','--exclude-standard')) | Where-Object { $_ -ne '' }).Count)
)

Write-Text 'git-status.porcelain.txt' (GitOut @('status','--porcelain=v1'))
Write-Text 'git-diff-stat.txt'      (GitOut @('diff','--stat'))
Write-Text 'git-diff-names.txt'     (GitOut @('diff','--name-status'))
Write-Text 'git-untracked.txt'      (GitOut @('ls-files','--others','--exclude-standard'))
Write-Text 'git-diff.patch.txt'     (GitOut @('-c','core.quotepath=false','diff'))

$protected = @(
    'backend/src/mktkb/evaluation/p2_hard_evidence.py',
    'backend/src/mktkb/evaluation/p2_evidence_rescore.py',
    'backend/src/mktkb/evaluation/p2_holdout_scenarios_v3.py',
    'backend/src/mktkb/evaluation/p2_holdout_scenarios.py',
    'backend/src/mktkb/evaluation/p2_contracts.py',
    'backend/src/mktkb/evaluation/p2_holdout_source_map.py',
    'backend/src/mktkb/evaluation/p2_holdout_plan.py',
    'backend/src/mktkb/evaluation/p2_authorization.py',
    'docs/evaluation/p2-evidence-rescore-v0_1.md',
    'docs/evaluation/p2-holdout-v3.source-map.json',
    'docs/evidence/LOCAL-R1-20261101/budget/budget.json',
    'docs/evidence/LOCAL-R1-20261101/budget/live-ledger.jsonl',
    'docs/reports/OBS-EVAL/P2/H2V3/fullverify-20261116/evidence/quality-per-run.json',
    'docs/reports/OBS-EVAL/P2/H2V3/fullverify-20261116/evidence/recompute-v2.json',
    'docs/reports/OBS-EVAL/P2/H2V3/fullverify-20261116/run/final-summary.json',
    'docs/reports/OBS-EVAL/P2/H2V3/fullverify-20261116/work/recompute_axes_fullverify.py',
    'docs/reports/OBS-EVAL/P2/H2V3/fullverify-20261116/work/build_fullverify_artifacts.py',
    'tools/p2_h2_controlled_execute.py',
    'tools/p2_h2_v3_controlled_execute.py'
)
$rows = New-Object System.Collections.Generic.List[string]
$rows.Add('path|sha256|bytes|mtime')
foreach ($rel in $protected) {
    $p = Join-Path $repo $rel
    if (Test-Path -LiteralPath $p) {
        $item = Get-Item -LiteralPath $p
        $h = (Get-FileHash -LiteralPath $p -Algorithm SHA256).Hash.ToLower()
        $rows.Add(("{0}|{1}|{2}|{3}" -f $rel, $h, $item.Length, $item.LastWriteTime.ToString('yyyy-MM-ddTHH:mm:sszzz')))
    } else {
        $rows.Add(("{0}|MISSING||" -f $rel))
    }
}
Write-Text 'protected-hashes.txt' $rows

$evalDir = Join-Path $repo 'backend\src\mktkb\evaluation'
$evalFiles = Get-ChildItem -LiteralPath $evalDir -Filter *.py -File | Sort-Object Name
$evalRows = New-Object System.Collections.Generic.List[string]
$evalRows.Add('file|sha256|bytes')
foreach ($f in $evalFiles) {
    $evalRows.Add(("{0}|{1}|{2}" -f $f.Name, (Get-FileHash -LiteralPath $f.FullName -Algorithm SHA256).Hash.ToLower(), $f.Length))
}
Write-Text 'evaluation-module-hashes.txt' $evalRows

$envFile = Get-Item -LiteralPath (Join-Path $repo '.env') -ErrorAction SilentlyContinue
$cred = New-Object System.Collections.Generic.List[string]
$cred.Add(("captured_at: " + $stamp))
$cred.Add(("env_exists: " + [bool]$envFile))
if ($envFile) {
    $cred.Add(("env_bytes: " + $envFile.Length))
    $cred.Add(("env_mtime: " + $envFile.LastWriteTime.ToString('yyyy-MM-ddTHH:mm:sszzz')))
} else {
    $cred.Add('env_bytes: 0')
    $cred.Add('env_mtime: ')
}
$cred.Add('note: content of .env was NOT read; only existence, byte size and mtime are recorded for later tamper comparison.')
Write-Text 'credential-touch-record.txt' $cred

$notes = New-Object System.Collections.Generic.List[string]
$notes.Add('# Baseline capture (read-only)')
$notes.Add('')
$notes.Add(("- captured_at: " + $stamp))
$notes.Add(("- repo: " + $repo))
$notes.Add(("- head: " + ((GitOut @('rev-parse','HEAD')) -join '')))
$notes.Add(("- tracked_modified: " + (@(GitOut @('diff','--name-only')) | Where-Object { $_ -ne '' }).Count))
$notes.Add(("- untracked: " + (@(GitOut @('ls-files','--others','--exclude-standard')) | Where-Object { $_ -ne '' }).Count))
$notes.Add(("- protected_files_hashed: " + $protected.Count))
$notes.Add('')
$notes.Add('Purpose: freeze the starting Git path set, diff, and protected-file hashes so the repair round can')
$notes.Add('prove it only added increments and did not overwrite pre-existing uncommitted modifications.')
$notes.Add('')
$notes.Add('Files:')
$notes.Add('- git-identity.txt: branch/HEAD/counts')
$notes.Add('- git-status.porcelain.txt: full porcelain status')
$notes.Add('- git-diff.patch.txt: full tracked diff at start (evidence of pre-existing work)')
$notes.Add('- git-untracked.txt: pre-existing untracked paths')
$notes.Add('- protected-hashes.txt: frozen scorer/contract/ledger/budget/old-evidence/entry hashes')
$notes.Add('- evaluation-module-hashes.txt: per-file hashes of backend/src/mktkb/evaluation/*.py')
$notes.Add('- credential-touch-record.txt: .env existence/size/mtime only, never content')
Write-Text '00-baseline-notes.md' $notes

Write-Output 'BASELINE DONE'

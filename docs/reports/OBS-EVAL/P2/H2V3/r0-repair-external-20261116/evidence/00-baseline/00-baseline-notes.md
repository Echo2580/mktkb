# Baseline capture (read-only)

- captured_at: 2026-11-16T14:47:02+08:00
- repo: D:\GPT项目\市场部AI知识库
- head: 97b0066726e5b8d6f94cbc0b63a890084550c106
- tracked_modified: 29
- untracked: 4093
- protected_files_hashed: 19

Purpose: freeze the starting Git path set, diff, and protected-file hashes so the repair round can
prove it only added increments and did not overwrite pre-existing uncommitted modifications.

Files:
- git-identity.txt: branch/HEAD/counts
- git-status.porcelain.txt: full porcelain status
- git-diff.patch.txt: full tracked diff at start (evidence of pre-existing work)
- git-untracked.txt: pre-existing untracked paths
- protected-hashes.txt: frozen scorer/contract/ledger/budget/old-evidence/entry hashes
- evaluation-module-hashes.txt: per-file hashes of backend/src/mktkb/evaluation/*.py
- credential-touch-record.txt: .env existence/size/mtime only, never content

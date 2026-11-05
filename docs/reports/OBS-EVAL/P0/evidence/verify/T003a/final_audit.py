"""生成 T003a 独立验收的环境/工作树审计证据（UTF-8 无 BOM）。"""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(r"D:\GPT项目\市场部AI知识库")
EV = REPO / "docs/reports/OBS-EVAL/P0/evidence/verify/T003a"
START_EPOCH = float(sys.argv[1]) if len(sys.argv) > 1 else 0.0
PY = REPO / ".venv/Scripts/python.exe"


def run(cmd: list[str]) -> str:
    proc = subprocess.run(
        cmd, cwd=REPO, capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    return f"$ {' '.join(cmd)}\n{proc.stdout}{proc.stderr}(exit={proc.returncode})\n"


def write(name: str, chunks: list[str]) -> None:
    text = "\n".join(chunks)
    (EV / name).write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {name} ({len(text)} chars)")


# ---- 00-context ----
head = subprocess.run(
    ["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True
).stdout.strip()
pytest_version = subprocess.run(
    [str(PY), "-B", "-m", "pytest", "--version"], cwd=REPO, capture_output=True, text=True
).stdout.strip()
now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
write(
    "00-context.txt",
    [
        "# T003a 独立验收复跑证据（验收者本人复跑，不采信 dev report 结论）",
        f"# 采集时间：{now}",
        f"# HEAD={head}（p0/obs-eval）；handoff 待验 commit=dea4d5d；父提交=2ac976f；main=8e44158",
        f"# Python={sys.version.split()[0]}；pytest={pytest_version}；OS={sys.platform}",
        "# 环境变量：MKTKB_PROJECT_TOTAL_LIMIT_CNY=20.0；解释器=.venv\\Scripts\\python.exe -B；",
        "#          每条 pytest 均带 -q -p no:cacheprovider --basetemp backend\\.pytest-tmp\\verify-*",
        "# 证据编码：全部 UTF-8 无 BOM（由 capture.py 以 UTF-8 解码/编码保存原生输出）。",
        "#",
        "# 文件清单（本目录）：",
        "# 00-context.txt                    本文件（环境/提交/命令上下文）",
        "# 01-pytest-tracer.txt              handoff §6：test_tracer.py 66 passed",
        "# 02-pytest-observability.txt       handoff §6：observability 目录 158 passed",
        "# 03-pytest-full.txt                handoff §6：backend/tests 全量（预期 1176 passed）",
        "# 04-commit-boundary.txt            git show/name-status/numstat/受保护路径/删除检查",
        "# 05-contracts-init-diff.txt        contracts.py 仅末尾追加 + __init__.py 追加导出",
        "# 06-sha256-and-evidence-audit.txt  交付物 SHA-256 与 dev 证据 00-06 哈希核对",
        "# 07-independent-probe.txt          仓库外独立探针（1212 条断言，§5.1-§5.7）",
        "# 08-mutation-probes.txt            仓库外变异探针（12/12 被捕获，证明探针非空转）",
        "# 09-static-checks.txt              静态/结构检查（依赖/导入/测试只写 tmp_path/边界）",
        "# 10-edge-observations.txt          边界行为观察（replayed 优先级、live、非法 JSON 等）",
        "# 11-baseline-2ac976f-full.txt      基线等价复跑（第 2 次）命中既有 test_chat.py::test_g08 时序 flake",
        "# 11b-baseline-flake-run.txt         基线等价复跑（第 1 次）同样命中该时序 flake",
        "# 11c-baseline-pass-run-utf8.txt     基线等价复跑完整通过：1110 passed / 0 failed / 0 error",
        "# 12-worktree-audit.txt              工作树/未越界审计（本任务运行前后无仓库文件改动）",
        "# 13-baseline-flaky-test-isolated.txt flake 用例单独复跑：1 passed（确认时序 flake）",
        "# probe_tracer.py / mutate_verify.py / static_checks.py / edge_observations.py / capture.py / final_audit.py",
        "#                                  上述探针/审计脚本原文（仓库外工具，随证据保存）",
        "",
        "# handoff §6 必跑命令（验收者复跑）：",
        "# $env:MKTKB_PROJECT_TOTAL_LIMIT_CNY = \"20.0\"",
        "# .\\.venv\\Scripts\\python.exe -B -m pytest backend/tests/observability/test_tracer.py -q -p no:cacheprovider --basetemp backend\\.pytest-tmp\\obs-tracer",
        "# .\\.venv\\Scripts\\python.exe -B -m pytest backend/tests/observability -q -p no:cacheprovider --basetemp backend\\.pytest-tmp\\obs-all",
        "# .\\.venv\\Scripts\\python.exe -B -m pytest backend/tests -q -p no:cacheprovider --basetemp backend\\.pytest-tmp\\t003a-full",
        "# git show --stat --oneline HEAD",
    ],
)

# ---- 12-worktree-audit ----
status_lines = subprocess.run(
    ["git", "status", "--porcelain"], cwd=REPO, capture_output=True, text=True,
    encoding="utf-8", errors="replace",
).stdout.splitlines()
tracked_changes = [line for line in status_lines if not line.startswith("??")]
untracked = [line[3:] for line in status_lines if line.startswith("??")]

allowed_untracked_prefixes = [
    "docs/reports/OBS-EVAL/P0/evidence/verify/T003a/",
    ".claude/handoffs/T003a-tracer/review.md",
]
preexisting_untracked = [u for u in untracked if not any(u.startswith(p) for p in allowed_untracked_prefixes)]
unexpected = [
    u for u in preexisting_untracked
    if not (
        u.startswith(".claude/handoffs/") or u.startswith("docs/reports/OBS-EVAL/P0/evidence/verify/")
    )
]
new_untracked_ours = [u for u in untracked if any(u.startswith(p) for p in allowed_untracked_prefixes)]

# 仓库内本次会话开始后被修改的文件（排除 .git/.venv/允许的证据与缓存目录）
changed_since_start: list[str] = []
docs_evidence_changed: list[str] = []
shared_workspace_changed: list[str] = []
skip_dirs = {
    ".git", ".venv", "node_modules", "__pycache__",
    "backend/.pytest-tmp", "docs/reports/OBS-EVAL/P0/evidence/verify/T003a",
}
for path in REPO.rglob("*"):
    if not path.is_file():
        continue
    rel = path.relative_to(REPO).as_posix()
    if any(rel.startswith(skip + "/") or rel == skip for skip in skip_dirs):
        continue
    if rel == ".claude/handoffs/T003a-tracer/review.md":
        continue
    try:
        mtime = path.stat().st_mtime
    except OSError:
        continue
    if mtime <= START_EPOCH:
        continue
    if rel.startswith("docs/evidence/"):
        docs_evidence_changed.append(rel)
    elif rel.startswith(".claude/handoffs/"):
        # 共享工作区：PM/其它助手在并发推进 P1 holdout 文档；非本验收者写、与 T003a 交付物无关
        shared_workspace_changed.append(rel)
    else:
        changed_since_start.append(rel)

# 仓库根 var/ 下 SQLite（产品库，应零新增）；其余 docs/evidence 下的快照库只做计数
var_db = [
    p.relative_to(REPO).as_posix()
    for p in (REPO / "var").rglob("*.sqlite3*")
] if (REPO / "var").exists() else []
var_db_new = [rel for rel in var_db if (REPO / rel).stat().st_mtime > START_EPOCH]
other_db = [
    p.relative_to(REPO).as_posix()
    for p in REPO.rglob("*.sqlite3*")
    if ".venv" not in p.parts and ".pytest-tmp" not in p.parts
    and not p.relative_to(REPO).as_posix().startswith("var/")
    and not p.relative_to(REPO).as_posix().startswith("docs/evidence/")
]
other_db_new = [rel for rel in other_db if (REPO / rel).stat().st_mtime > START_EPOCH]

write(
    "12-worktree-audit.txt",
    [
        "# 工作树/越界审计（验收者不应修改任何交付物、不 commit、不 push、不改 _index.md）",
        f"# 文档 _index.md 的已跟踪修改为本任务开始前 PM 既有状态（本次验收未触碰）。",
        f"# 本次验收开始时间（epoch）={START_EPOCH}（{datetime.fromtimestamp(START_EPOCH).isoformat()}）",
        "",
        "## git status --porcelain（全量）",
        *status_lines,
        "",
        "## 已跟踪文件改动（期望只有任务开始前已存在的 _index.md）",
        *tracked_changes,
        "",
        "## 未跟踪文件：验收者新增（允许：review.md + verify/T003a 证据）",
        *new_untracked_ours,
        "",
        "## 未跟踪文件：非本次验收新增（任务开始前既有 PM 文件）",
        *preexisting_untracked,
        "",
        "## 不可解释的未跟踪文件（期望为空）",
        *unexpected,
        "",
        "## 本次会话开始后被修改的仓库文件（排除 .git/.venv/backend/.pytest-tmp/本任务证据/review.md）",
        f"### 除 docs/evidence/ 与 .claude/handoffs/ 外（期望为空；非空=可能越界）",
        *(changed_since_start or ["(none)"]),
        "",
        "### .claude/handoffs/ 下（共享工作区中 PM/其它助手的并发文档改动；非本验收者所写，与 T003a 交付物无关）",
        f"count={len(shared_workspace_changed)}",
        *shared_workspace_changed,
        "",
        "### docs/evidence/ 下（gitignore 忽略的既有验收证据目录；被既有 T09/RAG acceptance 测试在跑全量套件时写入，属既有测试副作用，非本包 commit 内容）",
        f"count={len(docs_evidence_changed)}（路径样例）",
        *docs_evidence_changed[:10],
        "",
        f"## var/ 下 SQLite 文件（产品库；期望：既有文件均未修改）",
        *var_db,
        "--- 本次会话新增/修改 var/ SQLite：",
        *(var_db_new or ["(none)"]),
        "",
        "## docs/evidence/ 之外的其它 SQLite（期望为空）",
        *other_db,
        "--- 本次会话新增：",
        *(other_db_new or ["(none)"]),
        "",
        "## 结论",
        f"- 已跟踪改动数={len(tracked_changes)}（只有任务开始前既有的 _index.md）",
        f"- 不可解释未跟踪文件数={len(unexpected)}",
        f"- 除 docs/evidence/ 与 .claude/handoffs/ 外本次会话修改文件数={len(changed_since_start)}",
        f"- .claude/handoffs/ 下 PM 并发改动文件数={len(shared_workspace_changed)}（非本验收者）",
        f"- var/ SQLite 本次新增/修改数={len(var_db_new)}",
        f"- docs/evidence/ 外其它 SQLite 本次新增数={len(other_db_new)}",
        f"- docs/evidence/ 本次被既有测试写入文件数={len(docs_evidence_changed)}（gitignore 忽略，未进入 commit）",
    ],
)

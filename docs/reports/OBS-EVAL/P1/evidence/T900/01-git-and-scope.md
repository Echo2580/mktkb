# T900 证据 01：Git / 范围 / 依赖审计

模型：`wb / cn:deepseek-v4.1-flash / reasoning_effort=max`

## A. 现场

```text
git branch --show-current            -> p1/fix-retrieval
git log -1 --oneline                 -> 05e67cd chore(p1): resume per owner - T900 handoff updated ...
git merge-base main p1/fix-retrieval -> 083eaef71b50db1cf227317c8d470db7168ce074
git rev-list --count main..p1/fix-retrieval -> 84
非 chore commit 数                    -> 21；PM 簿记 commit 数 -> 63
git diff --stat main..p1/fix-retrieval -> 301 files changed, 35204 insertions(+), 327 deletions(-)
```

开工前 `git status --short` 仅见主人侧未跟踪 `docs/面试/`；T900 期间 PM 并发新增未跟踪
`.claude/handoffs/T900-p1-closeout/pr-body.md`（PM 草稿，未读改）。无 tracked 改动。

## B. 21 个非簿记 commit 的路径审计

逐 commit `git show --name-status`：全部落在
`backend/src/mktkb/**`、`backend/tests/**`、`frontend/src/**`、`frontend/e2e/**`、
`fixtures/evaluation/**`、`docs/evaluation/**`、`docs/reports/OBS-EVAL/P1/**`、
`docs/接口与数据契约.md`、各包 `.claude/handoffs/**`。未出现：

- `var/**`、`docs/evidence/**`、`.env`、签名 `budget.json` / `S2-LIVE-GO.json` /
  `live-ledger.jsonl` 的实际改动（`p1-gate-drafts/*.proposed` 仅为 PM 草稿名）。
- 依赖清单：`pyproject.toml` / `uv.lock` / `requirements*.lock` / `package.json` /
  锁文件均零 diff。
- 业务 API schema：`backend/src/mktkb/conversations/schemas.py` 零 diff；
  `AskResult` 12 字段、`MessageView` 12 字段（`schemas.py:96,118`）。
- `docs/接口与数据契约.md` 仅追加“## 8. 观测与监控接口（只读）”（+50 行），既有章节未改。

## C. 窗口外文件

- `docs/面试/市场部AI知识库-最终版面试知识库.md`：主人侧未跟踪文件，非 P1 交付；T900 未读改。
- `.claude/handoffs/T900-p1-closeout/pr-body.md`：PM 于 2026-11-09 22:42 并发写入的 PR 草稿；
  不在 T900 交付范围，T900 未改。
- T900 临时产物均在 `.claude/handoffs/_scratch/T900/` 与 `backend/.pytest-tmp/t900-*`；
  未在仓库根创建 `_scratch/`。

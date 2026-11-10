# T106 R2 测试 / 评测 / 前端复跑（04）

环境：Windows；仓库根 `D:\GPT项目\市场部AI知识库`；`.venv\Scripts\python.exe` 3.12.7；pytest 均设 `MKTKB_PROJECT_TOTAL_LIMIT_CNY=20.0`，带 `-B -q -p no:cacheprovider --basetemp backend\.pytest-tmp\T106-R2\<label>`。零真实模型/embedding/rerank/OCR；未读 `.env`/Holdout。

## A. pytest（每个范围 1 次）

| 范围 | label | 结果 |
| --- | --- | --- |
| 本包 `test_p1_t106_copy.py` | `pkg` | **15 passed**（0.05s） |
| `backend/tests/unit` | `unit` | **350 passed**（6.63s） |
| `backend/tests/observability` | `obs` | **255 passed**（15.93s） |
| `backend/tests/integration` | `int` | **381 passed**（258.99s）；本机未复现开发提到的 `test_g08_short_budget_cancels_inflight_model_call` flake，无需隔离复跑 |
| 全量 `backend/tests` | `full` | **1733 passed / 0 failed / 0 error**（388.92s） |

- 全量跑前 `FreePhysicalMemory=4,212,624 KB`；5 秒轮询 69 个样本，最低 `3,555,360 KB`（≈3.39 GB，>2GB），无 `<2GB` 样本；无 flake 隔离复跑。
- 定向受影响测试：`test_p1_t105_anaphora_field.py::test_new_content_non_field_followup_does_not_dump`（integration + rag）**2 passed**（1.34s）；`test_p1_t104_error_classification_http.py` **9 passed**（5.11s）。
- 日志：`backend\.pytest-tmp\T106-R2\{pkg,unit,obs,int,full}.log`。

## B. b0 / badcase local run + gate（对 P0）

命令（cwd=仓库根，`$env:PYTHONPATH="backend/src"`）：

```powershell
python -B -m mktkb.evaluation.cli run --suite b0 --mode local --out backend\.pytest-tmp\T106-R2\eval\b0
python -B -m mktkb.evaluation.cli gate --run backend\.pytest-tmp\T106-R2\eval\b0
# badcase 同理
```

| suite | 本轮 run_id | 状态 | gate | 对 P0 逐例 |
| --- | --- | --- | --- | --- |
| b0 | `b0-local-20261108T114250048284Z-465d60ad` | pass 29 / fail 3 / skipped 8 | exit 3，hard `[]` | **0/40** |
| badcase | `badcase-local-20261108T114302522561Z-c130efc4` | pass 9 / fail 4 | exit 3，hard `[]` | **0/13** |

- 基线：`var/eval/runs/p0-b0`、`var/eval/runs/p0-badcase`（gate 均 exit 3 / hard `[]`）。
- 逐例口径：`(status, outcome.kind, 每个 check 的 (check_id, status))`；两套均 `case_diffs=0`，kind/status 未变，无新增 hard 名。

## C. regression 对 `17c0e63`

基线：既有 worktree `C:\Users\dell1712\AppData\Local\Temp\t105-r1-baseline-wt`（`git rev-parse` = `17c0e63`，`git status --short` 空；`mktkb.__file__` 已确认指向基线副本，未修改该 worktree）。当前用主工作树。

| 版本 | run_id | 状态 | gate |
| --- | --- | --- | --- |
| `17c0e63` 基线 | `regression-local-20261108T114413446575Z-7284f88c` | pass 4 / fail 3 | exit 1，hard `['security_leak']` |
| 当前 `972f508` | `regression-local-20261108T114536810055Z-7149e1c7` | pass 5 / fail 2 | exit 3，hard `[]` |

逐例：**仅 RG006** `fail/answer/(kind_correct,value_forbidden)` → `pass/clarification`；RG001–RG004 pass、RG005 fail、RG007 fail 均不变；gate hard 由 `['security_leak']` 收缩为 `[]`，**无新增 hard 名**。日志：`regression-{base,current}-{run,gate}.log`。

## D. 前端

```powershell
cd frontend
npm.cmd run typecheck   # exit 0
npm.cmd run build       # exit 0；40 modules，367.23 kB JS（index-BOb5Au_R.js）
npx.cmd playwright test e2e/02-chat.spec.ts --project=functional --reporter=line
# 7 passed (20.3s)，exit 0
.\.venv\Scripts\python.exe -B backend\tests\acceptance\support\run_browser_acceptance.py `
  --label t106r2 --evidence-root backend\.pytest-tmp\T106-R2\acceptance `
  --playwright-args "e2e/acceptance-02-kinds.spec.ts"
# PLAYWRIGHT EXIT 0；expected=5 / unexpected=0 / flaky=0；outbound external=[]
```

- acceptance JSON：`backend\.pytest-tmp\T106-R2\acceptance\actual\playwright-t106r2.json`；`stats.expected=5, unexpected=0, flaky=0`；服务/Vite 均 READY，outbound external 空。
- `INVALID_QUERY` 徽标分支无 e2e 注入入口：`serve_acceptance.py` 只提供 `POST /__acceptance/gateway/fail-next`（注入 `ModelError`），无 `QueryRejected`/`INVALID_QUERY` 注入；该分支由纯函数 `resultBadgeLabel` + typecheck/build + 既有 service_error e2e 覆盖，记为 NOT-RUN 残余，理由成立。
- e2e 未改：`git show --name-only 972f508` 不含 `frontend/e2e/*`；`02-chat` 断言 `服务调用失败` 仍成立。

## E. 范围 / 形式

- `git show --name-only --format='' 972f508`：**9 文件**，全部在返工单 §4 允许路径（`copy.py`、三个测试文件、`report.md`、证据 03/04、`MessageCard.tsx`、`format.ts`）。
- `git diff a42ee48..972f508 -- backend/src/mktkb/conversations/schemas.py` 为空；`git diff a42ee48..972f508 -- backend/src/mktkb/conversations/service.py` 为空；无 `intent.py`/`fixtures/**`/gate 配置/`var/**` 改动。
- 依赖：`backend/pyproject.toml`、`requirements*.lock`、`frontend/package.json`、`package-lock.json` 无 diff；无新增依赖。
- skip/xfail：R1 新增测试无 skip/xfail；T105 两处断言按文案取值最小同步（`"未记录"`→`"不属于台账字段"`，各 1 行，未删除/放宽其余断言）。
- `git log --oneline a42ee48..972f508`：`972f508`（R1 dev）+ `cb602b2`（PM 簿记）；R1 dev commit 单一。
- `report.md` 实测 **113 行**（`splitlines`），> handoff 80 行预算，非阻塞观察。开发证据 `docs/reports/OBS-EVAL/P1/evidence/T106/` 仍 4 份。
- 本目录证据 4 份；`git status --short` 仅有本证据目录未跟踪（复跑前为空，未改交付物）。

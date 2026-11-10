# T106 独立验收 04：测试 / 评测 / 前端复跑

环境：Windows，仓库根 `D:\GPT项目\市场部AI知识库`，`.venv\Scripts\python.exe` 3.12.7。
pytest 均设 `MKTKB_PROJECT_TOTAL_LIMIT_CNY=20.0`，命令带 `-B -q -p no:cacheprovider --basetemp backend\.pytest-tmp\<label>`。
零真实模型/embedding/rerank/OCR；未读 `.env`/Holdout。

## A. pytest（各 1 次）

| 范围 | label | 结果 |
| --- | --- | --- |
| 本包 `test_p1_t106_copy.py` | `t106v-pkg` | **8 passed**（0.03s） |
| `backend/tests/unit` | `t106v-unit` | **343 passed**（7.22s） |
| `backend/tests/observability` | `t106v-obs` | **255 passed**（15.50s） |
| `backend/tests/integration` | `t106v-int` | **381 passed**（256.32s）；本机未复现开发报告的 `test_g08_short_budget_cancels_inflight_model_call` flake，故无需隔离复跑 |
| 全量 `backend/tests` | `t106v-full` | **1726 passed / 0 failed / 0 error**（382.99s）；跑前 `FreePhysicalMemory≈3.43 GB`（>2GB，无需轮询等待） |

## B. b0 / badcase local run + gate

```powershell
$env:PYTHONPATH="backend/src"
.\.venv\Scripts\python.exe -B -m mktkb.evaluation.cli run --suite b0 --mode local --out backend\.pytest-tmp\T106-verify\eval\b0
.\.venv\Scripts\python.exe -B -m mktkb.evaluation.cli gate --run backend\.pytest-tmp\T106-verify\eval\b0
# badcase 同理
```

| suite | 本包 run_id | 状态 | gate | 对 P0 基线逐例 |
| --- | --- | --- | --- | --- |
| b0 | `b0-local-20261108T102648027740Z-6edd2268` | pass29/fail3/skipped8 | exit 3，hard `[]` | **0/40**（status、outcome.kind、各 check 状态全同） |
| badcase | `badcase-local-20261108T102650718856Z-6fde474a` | pass9/fail4 | exit 3，hard `[]` | **0/13** |

基线为 `var/eval/runs/p0-b0`、`var/eval/runs/p0-badcase`（同一字典序 run，gate 也均为 exit 3 / hard `[]`）。逐例比较脚本把 `(status, outcome.kind, 每个 check 的 status)` 全部纳入，结果为 0 差异，故文案取值变化未触发任何 value/source/kind/forbidden check。

## C. regression 当前 vs `17c0e63`

基线：`git worktree add --detach $env:TEMP\t106v-base 17c0e63`，cwd 该 worktree，`PYTHONPATH=$TEMP\t106v-base\backend\src`（已确认 `mktkb.__file__` 指向基线副本）；跑完已 `git worktree remove --force` 并 `prune`，当前 `git worktree list` 只剩主工作树与 T105 既有 worktree。

| 版本 | run_id | 状态 | gate |
| --- | --- | --- | --- |
| `17c0e63` 基线 | `regression-local-20261108T102835964888Z-ec6da610` | pass 4 / fail 3 | exit 1，hard `['security_leak']` |
| 当前 `a42ee48` | `regression-local-20261108T102958114347Z-9bc5e2ef` | pass 5 / fail 2 | exit 3，hard `[]` |

逐例比较：仅 **RG006** `fail/answer/(kind_correct,value_forbidden)` → `pass/clarification/()`；RG001–RG005 保持 pass，RG005/RG007 失败 checks 仍为 `kind_correct,refusal_expected`。RG006 的 pass 是 T105 已收口修复，不是本包文案变化；gate hard 名由 `['security_leak']` 收缩为 `[]`，**无新增 hard 名**。

## D. 前端

```powershell
cd frontend
npm run typecheck   # exit 0
npm run build       # exit 0；40 modules，dist/assets/index-DNljO7wF.js 367.02 kB
npx.cmd playwright test e2e/02-chat.spec.ts --project=functional --reporter=line
# 7 passed (21.6s)，exit 0
.\.venv\Scripts\python.exe -B backend\tests\acceptance\support\run_browser_acceptance.py `
  --label t106v --evidence-root backend\.pytest-tmp\T106-verify\acceptance `
  --playwright-args "e2e/acceptance-02-kinds.spec.ts"
# PLAYWRIGHT EXIT 0；expected=5 / unexpected=0；C02 用例 passed；outbound external=[]
```

acceptance 的 5 个用例独立解析：answer Q01、clarification C01、clarification C02（新增，无候选+reload）、not_found N01、service_error 均 `passed`。`02-chat` 的 7 个用例均 passed。

## E. 与开发 report 的差异

- 开发报告 `report.md:42-44` 的 integration 为 380 passed / 1 failed（`test_g08_short_budget_cancels_inflight_model_call` flake）；本机一次通过 381，属该时序 flake 的平台差异，不改变结论；开发已按规则隔离复跑 1 passed。
- `report.md:34` “RG001–RG006 状态不变、RG006 PASS”与 `report.md:51`/本机实测的“RG006 fail→pass”矛盾；正确表述应为 RG001–RG005 不变、RG006 PASS。属报告措辞问题（P3），不影响交付判定。
- 其余数字（8/343/255/1726、b0 29/3/8、badcase 9/4、0/40、0/13、前端 7 passed、acceptance 5/0）与开发报告一致。

## F. 范围/依赖/skip

- `git diff --name-only 9933a7b..a42ee48`：14 文件，全部在 handoff §4 允许路径；`schemas.py`、`intent.py`、`fixtures/evaluation/*`、`docs/evaluation/gate_v0_1.json`、`var/**` 无改动。
- `backend/pyproject.toml`、`requirements*.lock`、`frontend/package.json`、`package-lock.json` 无 diff；新增测试无 skip/xfail、无删除既有断言；e2e 仅同步徽标取值并新增 C02 用例。
- 当前 `git status --short` 空；`git log --oneline 9933a7b..a42ee48` 仅 `a42ee48` 1 个 commit。

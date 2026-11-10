# T109 R2 证据 04：测试、运行与形式合规

环境：Windows；仓库根 `D:\GPT项目\市场部AI知识库`；`.venv\Scripts\python.exe`；
pytest cwd=`backend`、`PYTHONPATH=src`、`PYTHONIOENCODING=utf-8`、
`MKTKB_PROJECT_TOTAL_LIMIT_CNY=20.0`（三条 pytest 均设置）；零真实 provider 调用。

## 1. pytest（各 1 次）

| 范围 | 命令（cwd=backend） | 结果 |
| --- | --- | --- |
| 本包 | `python -m pytest tests\evaluation\test_multiturn_runner.py -q` | **19 passed**，9.63s |
| `backend/tests/evaluation` | `python -m pytest tests\evaluation -q` | **392 passed**，87.74s |
| 全量 `backend/tests`（后台一次） | `python -m pytest tests -q` | **1795 passed**，493.55s，exit 0 |

- 全量 0 failed/0 error/0 skipped；无既有 flake，未触发隔离复跑。
- 内存：`Get-Process python` 汇总 WorkingSet64，5s/4s 间隔共 54 次采样（约 260s，分段覆盖）；
  峰值 **497.2 MB < 2 GB**。采样非全程连续（见 01 残余 5）。
- 无新增依赖：`1ffd57a` 未改 `pyproject.toml`/lock/requirements；测试文件无新增
  `pytest.mark.skip`/`xfail`；仅删除 2 条旧断言并以更强断言替换（01 残余 4）。

## 2. local / replay / gate（本次独立实跑）

命令（仓库根）：`.venv\Scripts\python.exe -B tools\rag_eval.py run --suite <suite> --mode local|replay --out <dir> [--from-run <src>] [--dataset <path>]`；
`gate --run <dir>`。父提交 run/数据集在 detached worktree `backend\.pytest-tmp\T109-verify\base`
（`ebfe956`，验收开始前 `git status --short` 为空）。

| 用途 | run_id | 结果 |
| --- | --- | --- |
| regression 当前 local | `regression-local-20261108T171829346713Z-9647507a` | pass 5/fail 2；gate exit 3，hard `[]` |
| 源=父提交单轮 run，当前 replay（B1） | `regression-replay-20261108T171913748442Z-d3a55548` | RG002/3/6 fail，`multi_turn_source_missing`；其余 4 行不变；gate hard `[]` |
| 源=多轮但 RG002 截 1 条轮（B1b） | `regression-replay-20261108T171922622148Z-ff2b2437` | RG002 `multi_turn_source_incomplete`；RG003/RG006 仍 2 条；gate hard `[]` |
| 源=当前 local，合法多轮 replay | `regression-replay-20261108T171928195284Z-f7d2fe1f` | 7/7 复现，多轮各 2 条，`0/7 diffs`；gate hard `[]` |
| b0 当前 local | `b0-local-20261108T171935528825Z-368121a7` | pass 29/fail 3/skipped 8；gate exit 3，hard `[]` |
| badcase 当前 local | `badcase-local-20261108T171939546086Z-03bd6acf` | pass 9/fail 4；gate exit 3，hard `[]` |
| b0 当前 replay | `b0-replay-20261108T171943617053Z-8acc400a` | 40/40 单轮，1 轮/1 trace |
| 合成末轮 error 源 replay（R3 补查） | `regression-replay-20261108T174400454928Z-195a1a2b` | fail 复现（turn 2/2），2 条 replay，逐轮题面/local hash 一致 |

父提交基线（只读复用，未改）：`regression-parent`（`…7638e33c`）、`b0-parent`、
`badcase-parent`、`b0-parent-replay`；P0 冻结基线 `var/eval/runs/p0-b0`、`p0-badcase`、
`p0-b0-replay`。

### 2.1 B1 三行（父提交单轮源 + 当前 replay）

| case | status | error.code | turns_executed | turn_traces |
| --- | --- | --- | --- | --- |
| RG002 | fail | multi_turn_source_missing | 0 | [] |
| RG003 | fail | multi_turn_source_missing | 0 | [] |
| RG006 | fail | multi_turn_source_missing | 0 | [] |

无 `status=pass`、无单条 `turn_traces`；`multi_turn_verified=False`，gate 不 crash。

### 2.2 上轮 PASS 抽查（详见 03-F）

- b0 40 行 / badcase 13 行对父提交 strict 0（仅多 `turn_traces` 键），对 P0 `case_diffs=0`；
  gate 当前/P0 hard `[]`。
- b0 当前 replay 对父提交 replay 实质 0 diff、对 P0 replay 签名 0。
- regression 当前 vs 父提交：`case_diffs` 仅 RG006；RG002/RG003 pass，RG005/RG007 fail 不变；
  gate 双方 hard `[]`。
- RG006：`expected_kind=answer`、`expected_values=['40']`、`forbidden=['店内外侧','QF01']`；
  末轮文本含 40、不含未问字段。

## 3. 形式/合规核对

- 复跑前 `git status --short` 为空；HEAD `1b1580a`；分支 `p1/fix-retrieval`。
- `git show --stat 1ffd57a`：**6 文件**，全部在允许路径：
  `backend/src/mktkb/evaluation/runner.py`、`backend/tests/evaluation/test_multiturn_runner.py`、
  `.claude/handoffs/T109-multiturn-runner/report.md`、`docs/.../T109/{02,03,04}*.md`。
- `git show 1ffd57a -- fixtures` 为空（RG006 未再改）。
- 无业务代码/API/intent/schemas/dataset/gate/账本/GO 改动；无 `conversations/` 改动。
- `git diff 1ffd57a..1b1580a -- runner.py tests` 为空（HEAD 仅 PM 簿记）。
- report 140 行（> 80 预算，非阻断）；T109 证据仍 4 份，02/03/04 均含 R1 段；
  本 R2 目录新增 01–04 四份。
- 单 dev commit `1ffd57a`；未 push/amend；未 commit/切分支/stash/reset；未读 `.env`/Holdout。
- 验收产出仅：`docs/reports/OBS-EVAL/P1/evidence/verify/T109-R2/`（01–04）与
  `.claude/handoffs/T109-multiturn-runner/review-R2.md`；`git status --short` 仅显示该未跟踪目录。

# T109 证据 04（独立验收）：测试、资源与形式合规

环境：Windows；仓库根 `D:\GPT项目\市场部AI知识库`；`.venv\Scripts\python.exe` 3.12.7；
cwd=`backend`、`PYTHONPATH=src`、`PYTHONIOENCODING=utf-8`；零真实模型/embedding/rerank/OCR 调用。
全量 pytest 按交付证据 04 同口径设 `MKTKB_PROJECT_TOTAL_LIMIT_CNY=20.0`（见下方环境说明）。

## 1. pytest（各 1 次；全量另做 1 次失败隔离复跑）

| 范围 | 命令 | 结果 |
| --- | --- | --- |
| 本包 | `python -m pytest tests\evaluation\test_multiturn_runner.py -q` | **15 passed / 0 failed / 0 error**，7.73s |
| `backend/tests/evaluation` | `python -m pytest tests\evaluation -q` | **388 passed / 0 failed / 0 error**，88.80s |
| 全量 `backend/tests`（带环境变量） | `python -m pytest tests -q` + `MKTKB_PROJECT_TOTAL_LIMIT_CNY=20.0` | **1791 passed / 0 failed / 0 error**，489.65s |
| 全量首次（未设环境变量） | 同上但未设 `MKTKB_PROJECT_TOTAL_LIMIT_CNY` | 1790 passed / 1 failed，失败项见下 |

- **内存**：全量第二次用 `tasklist /FI "IMAGENAME eq python.exe"` 每 ~1s 轮询所有 Python 进程工作集之和，
  313 个样本，峰值 **874.5 MB < 2 GB**。
- **首次失败隔离**：`tests/unit/test_s2h_r3_official_profile.py::test_official_profile_accepted_by_both_entries_and_worst_case_is_2103552`
  失败原因是共享预算 `budget.json` 的 `limit_cny=20.0` 与默认项目上限 10.0 不一致；该环境变量是交付证据 04
  已写明的测试前置。隔离设置 `MKTKB_PROJECT_TOTAL_LIMIT_CNY=20.0` 后 **1 passed**，与 T109 改动无关。
- 无 `pytest.mark.skip` / `xfail`；无新增依赖（commit 未改 pyproject/lock）。
- `test_holdout_suite.py` 的 1 条契约同步删除了 2 条旧断言（T108「多轮不执行」口径），替换为 9 条更强断言；
  属已披露的契约反转，不是为绕过失败而弱化（报告 §4 已列偏离）。

## 2. local run / gate（本次独立实跑）

| suite | run_id | 状态 | gate |
| --- | --- | --- | --- |
| b0 当前 | `b0-local-20261108T155139759402Z-1c2a30b4` | pass 29 / fail 3 / skipped 8 | exit 3，hard `[]` |
| b0 父提交 | `b0-local-20261108T155213160039Z-0bd4d9c4` | 同上 | exit 3，hard `[]` |
| badcase 当前 | `badcase-local-20261108T155142663077Z-a667cb85` | pass 9 / fail 4 | exit 3，hard `[]` |
| badcase 父提交 | `badcase-local-20261108T155216139105Z-0faebde6` | 同上 | exit 3，hard `[]` |
| regression 当前 | `regression-local-20261108T154901303778Z-a44dba02` | pass 5 / fail 2 | exit 3，hard `[]` |
| regression 父提交 `ebfe956` | `regression-local-20261108T155006434105Z-7638e33c` | pass 5 / fail 2 | exit 3，hard `[]` |
| regression replay（源=当前） | `regression-replay-20261108T155223354906Z-ce7b6002` | 7/7 复现 | exit 3，hard `[]` |
| regression replay（源=父提交，旧产物） | `regression-replay-20261108T155402852581Z-a1e9ba13` | 见 03 的 FAIL 项 | — |
| b0 replay（源=当前） | `b0-replay-20261108T155423465420Z-7b1f2e97` | 40/40 复现 | — |
| b0 replay（源=父提交） | `b0-replay-20261108T162735547404Z-87629c3e` | 40/40 复现 | — |

命令（仓库根）：`.venv\Scripts\python.exe -B tools\rag_eval.py run --suite <suite> --mode local|replay --out <dir> [--from-run <src>] [--dataset <path>]`；
`gate --run <dir>`。父提交 run 在 detached worktree `backend\.pytest-tmp\T109-verify\base` 内执行。

## 3. 基线准备（开发披露的坑）

- `git worktree add --detach backend\.pytest-tmp\T109-verify\base ebfe956`；
- 只复制（不读内容）`.gitignore` 忽略的
  `docs/evidence/LOCAL-R1-20261101/S1-DEV/R2/subset-policy.json` 到 worktree 同路径；
- 复制后 worktree `git status --short` 为空；两侧 manifest `index_revision=49`、
  `corpus_manifest_sha256=5f41b1b811a5…` 一致（见 03 A 节）。主工作树未被修改。

## 4. 形式/合规核对

- `git status --short`（验收产出前）：空；`git rev-parse HEAD`=`703b7e0`，父=`ebfe956`，分支 `p1/fix-retrieval`。
- `git show --stat 703b7e0`：9 个文件，全部在 handoff 允许路径（runner.py、2 个测试、RG006 fixture、
  report、4 份证据）；单 commit。
- `git show 703b7e0 -- fixtures`：仅 `fixtures/evaluation/regression.jsonl` 的 RG006 一行（1 增 1 删）；
  RG001–RG005/RG007 未动。无 conversations/intent/schemas/dataset/gate/b0/badcase/账本/GO 改动。
- `report.md` 79 行，五段（完成内容/验收自证/运行结果/偏离未做/风险）；交付证据 4 份。
- 未读 `.env`、未读 `docs/evidence/.../P1-HOLDOUT/` 题目或答案；未 push/commit/切分支/stash/reset。
- 验收产出：本目录 4 份证据 + `.claude/handoffs/T109-multiturn-runner/review.md`；不改交付物。

# T108 验收：测试 / 评测 / 预算 / 范围

环境：Windows；仓库根 `D:\GPT项目\市场部AI知识库`；`.venv\Scripts\python.exe` 3.12.7；
`PYTHONPATH=backend/src`、`MKTKB_PROJECT_TOTAL_LIMIT_CNY=20.0`；所有临时产物在
`backend\.pytest-tmp\T108-verify\` 或 `%TEMP%\T108-verify\`，未写 `var/eval/runs`。

## A. pytest（最终树 af08848）

```text
.venv\Scripts\python.exe -B -m pytest backend\tests\evaluation\test_holdout_suite.py -q -p no:cacheprovider
→ 34 passed, 1 warning in 59.81s

.venv\Scripts\python.exe -B -m pytest backend\tests\evaluation -q -p no:cacheprovider
→ 364 passed, 1 warning in 78.16s

.venv\Scripts\python.exe -B -m pytest backend\tests -q -p no:cacheprovider
→ 1767 passed, 1 warning in 429.07s（第一次）
→ 1767 passed, 1 warning in 429.39s（第二次，带内存轮询）
```

第二次全量的内存采样（每 5s 汇总 `python.exe` 中 command line 含 `pytest backend` 的 WorkingSet）：
**峰值 465.9 MB**（< 2 GB）。两次全量均 0 failed / 0 error；本机未复现 report 所述
`test_g08_short_budget_cancels_inflight_model_call` flake，故无需隔离复跑。

## B. b0 / badcase 对 P0

命令：

```text
python -B -m mktkb.evaluation.cli run  --suite b0      --mode local --out backend\.pytest-tmp\T108-verify\eval\b0
python -B -m mktkb.evaluation.cli gate --run backend\.pytest-tmp\T108-verify\eval\b0
# badcase 同理
```

| suite | run_id | 状态 | gate |
| --- | --- | --- | --- |
| b0 | `b0-local-20261108T131456061917Z-94e77d16` | pass 29 / fail 3 / skipped 8 | exit 3，hard `[]`，quality unknown |
| badcase | `badcase-local-20261108T131500297828Z-53c47c75` | pass 9 / fail 4 | exit 3，hard `[]`，quality unknown |

逐例对比 `var/eval/runs/p0-b0`、`p0-badcase`：以 `(status, outcome.kind, 每个 check 的
(check_id,status), error.code)` 为签名，**b0 case_diffs=0/40、badcase case_diffs=0/13**；
`summary.status_counts` 与 P0 一致；gate hard 均为 `[]`。

## C. regression 对 `17c0e63`

基线用既有 detached worktree `%TEMP%\t105-r1-baseline-wt`（HEAD `17c0e63`，工作树 clean；
`mktkb.__file__` 指向该 worktree 的 `backend/src`）。当前用主工作树。

| 版本 | run_id | 状态 | gate |
| --- | --- | --- | --- |
| `17c0e63` | `regression-local-20261108T131619463178Z-1f73da7b` | pass 4 / fail 3 | exit 1，hard `['security_leak']` |
| 当前 `af08848` | `regression-local-20261108T131742542065Z-53849f1c` | pass 5 / fail 2 | exit 3，hard `[]` |

逐例：**仅 RG006** `fail/answer/(value_forbidden=fail, kind_correct=fail)` →
`pass/clarification/(value_forbidden=pass, kind_correct=pass)`；RG005、RG007 仍 fail 且签名与基线相同；
无新增 hard 名（hard 由 `['security_leak']` 收缩为 `[]`）。注意：`fixtures/evaluation/regression.jsonl`
在 `17c0e63..af08848` 间有 RG006 的文本/forbidden 更新（T105 R1，非 T108 commit 改动），基线 run 使用
基线夹具；T108 自身未改该 fixture。

## D. 范围 / 形式

```text
git rev-list --count 31143f2..af08848 = 1
git diff --name-only 31143f2 af08848 = 13 files，全部在 handoff §3 允许路径
  （evaluation/{dataset,runner,cli,gate}.py、tests/evaluation/*、fixtures/evaluation/holdout-questions.jsonl、
    docs/reports/OBS-EVAL/P1/evidence/T108/*、.claude/handoffs/T108-holdout-support/report.md）
git diff --exit-code -- 依赖文件（pyproject/lock） = 0 → 无新依赖
git diff 内的测试删除行 = 1 个被替换的断言（--allow-holdout-details 文案）+ 1 个非法 suite 占位值；
  无 pytest.mark.skip/xfail/skipif 新增，无删除测试
report.md 80 行；交付证据 4 份；验证证据本目录 4 份
```

- 零真实模型/embedding/rerank/OCR：holdout local 在 `runner.py:541-546` 强制
  `provider_mode='offline'`；b0/badcase/regression local 走既有 offline 配置；本次未使用 live/replay。
- 未读 `.env`；未改业务代码/API schema/gate 配置/账本/GO；未写 `var/eval/runs`。
- 真实 holdout 只用于受限 run；题干/答案未写入本目录或 `review.md`。

## E. NOT-RUN / 说明

- 未在父提交 `31143f2` 单独跑 regression 以隔离 T108 自身的差分（任务只要求对 `17c0e63`）；
  b0/badcase `case_diffs=0` + holdout 分支按 suite 隔离，未发现 T108 影响既有 suite。
- 未逐题阅读真实 holdout 答案（防污染红线）；真实 details run 只读取了 status/error code/check 计数与
  audit 元数据，随后删除 TEMP 产物。真实 run 的 3 个 `gold_unit_ids_missing` error 已定位为 F1
  （见 `01-verdict.md` / `03-probe-results.md` §B）；不影响 pytest 结果，但影响 holdout 可评分性。
- 未做网络抓包以证明“零真实调用”；以代码强制 offline + 本次 run 配置为证据。

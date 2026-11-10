# T108 R2：测试 / 评测 / 回归 / 预算 / 范围

环境：Windows；仓库根 `D:\GPT项目\市场部AI知识库`；`.venv\Scripts\python.exe` 3.12.7；
`PYTHONPATH=backend/src`；`MKTKB_PROJECT_TOTAL_LIMIT_CNY=20.0`（评测 run）。
临时产物在 `%TEMP%\T108-R2\` 与 `backend\.pytest-tmp\T108-R2\`；未写 `var/eval/runs`。

## A. pytest（R1 最终树 `d3b5745`；每个范围 1 次）

```text
.venv\Scripts\python.exe -B -m pytest backend\tests\evaluation\test_holdout_suite.py -q -p no:cacheprovider
→ 43 passed, 1 warning in 61.90s

.venv\Scripts\python.exe -B -m pytest backend\tests\evaluation -q -p no:cacheprovider
→ 373 passed, 1 warning in 79.27s

.venv\Scripts\python.exe -B -m pytest backend\tests -q -p no:cacheprovider
→ 1776 passed, 1 warning in 477.53s
```

- 全量 0 failed / 0 error；无 skip/xfail 生效；本机未复现 report 所述
  `test_g08_short_budget_cancels_inflight_model_call` flake，故未触发隔离复跑。
- 内存：全量期间约 90s 间隔采样 5 次 pytest 进程 WorkingSet，峰值 **394.1 MB**（< 2 GB）。
- 测试数变化：本包 34→43（+9，R1 新增 B1/B2/B3 用例）；evaluation 364→373；
  全量 1767→1776。新增测试行见 `test_holdout_suite.py:750-905`。

## B. b0 / badcase 对 P0

命令：

```text
python -B -m mktkb.evaluation.cli run  --suite b0      --mode local --out backend\.pytest-tmp\T108-R2\eval\b0
python -B -m mktkb.evaluation.cli gate --run backend\.pytest-tmp\T108-R2\eval\b0
# badcase 同理
```

| suite | run_id | 状态 | gate |
| --- | --- | --- | --- |
| b0 | `b0-local-20261108T142306610044Z-72285aa9` | pass 29 / fail 3 / skipped_requires_ocr 8 | exit 3，hard `[]` |
| badcase | `badcase-local-20261108T142310767912Z-2fdd5ada` | pass 9 / fail 4 | exit 3，hard `[]` |

逐例签名对比 `var/eval/runs/p0-b0`、`p0-badcase`（签名 = status、outcome.kind、
每个 check 的 `(check_id,status)`、error.code）：

```text
b0:      case_diffs=0/40   status 两侧均为 {pass:29, fail:3, skipped_requires_ocr:8}
badcase: case_diffs=0/13   status 两侧均为 {pass:9, fail:4}
```

## C. regression 对 `17c0e63`

基线：既有 detached worktree `%TEMP%\t105-r1-baseline-wt`（`git rev-parse HEAD` = `17c0e63`，
工作树 clean）；运行前打印 `mktkb.__file__=…\t105-r1-baseline-wt\backend\src\mktkb\__init__.py`，
确认未串用当前树。当前树用主工作树 `backend/src`。

| 版本 | run_id | 状态 | gate |
| --- | --- | --- | --- |
| `17c0e63` | `regression-local-20261108T142422883914Z-486634c2` | pass 4 / fail 3 | exit 1，hard `['security_leak']` |
| 当前 `3a422e9`（源码=`d3b5745`） | `regression-local-20261108T142545775635Z-00c2c959` | pass 5 / fail 2 | exit 3，hard `[]` |

逐例 diff：**仅 RG006**：

```text
RG006  (fail, answer, value_forbidden=fail, kind_correct=fail, refusal_unexpected=pass)
    →  (pass, clarification, value_forbidden=pass, kind_correct=pass, refusal_unexpected=pass)
RG005 / RG007 签名不变（仍 fail，check 组合一致）
hard: ['security_leak'] → []（收缩，无新 hard 名）
```

说明：`fixtures/evaluation/regression.jsonl` 的 RG006 文本/forbidden 更新来自 T105 R1
（`17c0e63..d3b5745` 间非 T108 改动的既有差异）；T108 R1 未改该 fixture。

## D. 范围 / 形式 / 依赖

```text
git show --stat d3b5745 → 5 files, 450 insertions(+), 6 deletions(-)
  runner.py +49/-4；test_holdout_suite.py +205/-2；report.md +87；
  evidence/T108/03-run-gate.md +52；evidence/T108/04-test-results.md +57
git diff b769a28..d3b5745 -- dataset.py gate.py → 空
git diff b769a28..d3b5745 -- <依赖文件> → 空
git rev-list --count b769a28..d3b5745 = 1
git diff 的测试删除行 = 2：`from mktkb.evaluation import cli`（改为 cli, runner）与
  `_run` 内的 `_fixture(...)` 取值行；无删除断言
test_holdout_suite.py 中 pytest.mark 仅既有 `parametrize("name", [CI, ...])`；无 skip/xfail/skipif
report.md = 167 行 > 80 行预算 → 非阻塞观察
```

- 允许路径核对：5 个文件全部在 `rework-R1.md` §3 允许范围（`runner.py`、
  `backend/tests/evaluation/`、`report.md`、T108 `03/04`）。
- 未改业务代码/API/intent/账本/GO/`.env`；未 push/amend；工作树仅新增本复验的未跟踪
  `review-R2.md` 与证据目录。

## E. 零真实模型调用

- holdout local：`runner.py:580-585` 强制 `provider_mode='offline'`，否则 `ValueError`；
  本次默认/details 均 exit 0，说明配置为 offline。
- b0/badcase/regression local：走既有 offline 配置（`_run_local` 同口径校验）。
- 本次未使用 `live`/`replay`，未调用 embedding/rerank/OCR；未做网络抓包（见 NOT-RUN）。

## F. NOT-RUN / 说明

- 未抓包证明“零真实调用”；以代码强制 offline + 运行配置为证据。
- 未逐题阅读真实 holdout 答案（防污染红线）；真实 details 只读 status/error/check 计数与 audit 元数据。
- 未在父提交 `b769a28` 单独跑 regression（任务只要求对 `17c0e63`）。

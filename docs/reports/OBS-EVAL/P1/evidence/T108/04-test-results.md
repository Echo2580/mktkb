# T108 证据 04：测试 / 评测 / 范围核对

环境：Windows；仓库根 `D:\GPT项目\市场部AI知识库`；`.venv\Scripts\python.exe` 3.12.7；
所有 pytest 均设 `MKTKB_PROJECT_TOTAL_LIMIT_CNY=20.0`，带 `-B -q -p no:cacheprovider
--basetemp backend\.pytest-tmp\<label>`；同一时间只跑一套 pytest。零真实模型/embedding/rerank/OCR，
未读 `.env` 与真实 holdout 内容。

## A. pytest（每个范围 1 次；最终树）

| 范围 | label | 结果 |
| --- | --- | --- |
| 本包 `test_holdout_suite.py` | `t108-holdout2` | **34 passed**（60.20s） |
| 本包 + `test_cli.py` + `test_regression_suite.py` | `t108-pkg2` | **79 passed**（60.83s，最终树） |
| `backend/tests/evaluation` | `t108-eval-final2` | **364 passed / 0 failed / 0 error**（74.99s，最终树） |
| 全量 `backend/tests` | `t108-full3` | **1767 passed / 0 failed / 0 error**（447.66s，最终树） |

- 内存：30 秒轮询 14 个样本，pytest 进程组峰值 **492 MB**（< 2 GB），14×30s < 20 min。
  期间系统空闲物理内存一度降到 ~0.3 GB（机器上其它进程所致），未造成失败/重试。
- 既有 flake：一次全量里 `backend/tests/integration/test_chat.py::
  test_g08_short_budget_cancels_inflight_model_call` 失败（`len(calls)==0`，T106 已记录的同款
  时序 flake），按口径隔离复跑 1 次 → **1 passed（1.32s）**；最终全量里同测试通过。
  T108 未改 `conversations/`/`service.py`，与本次改动无因果关系。
- 无 skip/xfail 新增：本包测试无 `pytest.mark.skip/xfail`；两条既有测试按新契约最小同步
  （`test_cli.py`：flag 由「不存在」改为「仅 holdout 可用」+ kwargs 透明传；
  `test_regression_suite.py`：非法 suite 示例 `holdout` → `holdout-typo`，因 holdout 已合法）。

## B. b0 / badcase local run + gate（对 P0 基线）

命令（cwd=仓库根，`$env:PYTHONPATH="backend/src"`）：

```text
python -B -m mktkb.evaluation.cli run  --suite b0      --mode local --out backend\.pytest-tmp\T108\eval\b0
python -B -m mktkb.evaluation.cli gate --run backend\.pytest-tmp\T108\eval\b0
# badcase 同理
```

| suite | 本轮 run_id | 状态 | gate | 对 P0 逐例 |
| --- | --- | --- | --- | --- |
| b0 | `b0-local-20261108T122104278059Z-3ed1ce55` | pass 29 / fail 3 / skipped 8 | exit 3，hard `[]` | **case_diffs=0/40** |
| badcase | `badcase-local-20261108T122113903499Z-b975e8eb` | pass 9 / fail 4 | exit 3，hard `[]` | **case_diffs=0/13** |

- 基线：`var/eval/runs/p0-b0`（pass 29 / fail 3 / skipped 8，gate exit 3 hard `[]`）、
  `var/eval/runs/p0-badcase`（pass 9 / fail 4，gate exit 3 hard `[]`）。
- 逐例口径：`(status, outcome.kind, 每个 check 的 (check_id, status), error.code)`；
  两套均 `case_diffs=0`（脚本 `backend/.pytest-tmp/T108/compare_cases.py`，临时不入库）。
- `summary.json` 结构键与 P0 完全一致；唯一差异是 `metrics.p50/p95_latency_ms`（10/15 → 12/18 ms，
  机器噪声，旧记录同样是变化量级）。manifest 新增 `holdout_details=false` /
  `holdout_labels_sha256=""` 两个带默认值的字段（`from_dict` 对旧产物向后兼容，IDENTITY_FIELDS 未变）。

## C. regression 对 `17c0e63`

基线：既有 detached worktree `%TEMP%\t105-r1-baseline-wt`（`git rev-parse` = `17c0e63`；
`PYTHONPATH=<worktree>\backend\src`、cwd=worktree，运行时已打印
`mktkb.__file__=…\t105-r1-baseline-wt\backend\src\mktkb\__init__.py`；运行后该 worktree
`git status --short` 仍为空，未被修改）。当前用主工作树。

| 版本 | run_id | 状态 | gate |
| --- | --- | --- | --- |
| `17c0e63` 基线 | `regression-local-20261108T122225475549Z-ff43b577` | pass 4 / fail 3 | exit 1，hard `['security_leak']` |
| 当前 `HEAD+本包` | `regression-local-20261108T122350370340Z-5eca2fac` | pass 5 / fail 2 | exit 3，hard `[]` |

逐例：**仅 RG006** `fail/answer/(value_forbidden=fail, kind_correct=fail)` →
`pass/clarification/(value_forbidden=pass, kind_correct=pass)`；RG001–RG004 仍 pass、
**RG005/RG007 仍 fail**（失败 checks 不变）；gate hard 由 `['security_leak']` 收缩为 `[]`，
**无新增 hard 名**。日志：`backend\.pytest-tmp\T108\eval\reg-{base,cur}-{run,gate}.log`。

## D. 范围 / 形式（对 handoff §3/§6）

```text
git status --short      -> 仅 evaluation/{cli,dataset,gate,runner}.py、tests/evaluation 两个最小同步
                           + 新测试文件、fixtures/evaluation/holdout-questions.jsonl
git diff --exit-code -- fixtures/evaluation/{b0,badcase,regression}.jsonl   -> 0
git diff --exit-code -- docs/evaluation                                     -> 0（gate 配置未改）
git diff --exit-code -- backend/src/mktkb/conversations backend/src/mktkb/rag -> 0（业务代码未改）
```

- 未新增依赖（`backend/pyproject.toml`、lock 文件无 diff）；`var/` 无写入（本包的 run 都写
  `backend\.pytest-tmp\T108\`）；未写账本/GO/`.env`。
- 未读真实 holdout questions/labels 内容；证据/报告/命令输出中不含任何题干或答案原文
  （合成夹具的标记词只用于断言「不在产物里」）。
- 真实 holdout run：**NOT-RUN（按红线由验收方执行）**；本包只验证缺 labels 时 fail closed
  （exit 3，无产物，见 03 §B）。

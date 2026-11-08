# T109 证据 04：测试结果、资源与合规

环境：Windows；仓库根 `D:\GPT项目\市场部AI知识库`；`.venv\Scripts\python.exe` 3.12.7；
每次 pytest 均设 `MKTKB_PROJECT_TOTAL_LIMIT_CNY=20.0`，带 `-B -q -p no:cacheprovider
--basetemp backend\.pytest-tmp\<label>`；同一时间只跑一套 pytest；零真实模型/embedding/rerank 调用。

## A. pytest

| 范围 | label | 结果 |
| --- | --- | --- |
| 本包 `test_multiturn_runner.py` | `t109-pkg-final` | **15 passed / 0 failed**（7.43s） |
| `backend/tests/evaluation` | `t109-eval-final` | **388 passed / 0 failed / 0 error**（84.42s；T108 基线 373 + 15） |
| 全量 `backend/tests`（第 1 次） | `t109-full` | **1791 passed / 0 failed / 0 error**（474.91s） |
| 全量 `backend/tests`（第 2 次，带内存轮询） | `t109-full2` | **1791 passed / 0 failed / 0 error**（472.03s） |

- 内存：第 2 次全量期间按 30s 轮询 pytest 进程组工作集，15 个样本
  （291.3 → 428.5 MB），峰值 **428.5 MB < 2 GB**；轮询覆盖 0–429s，运行 472s 结束。
- flake：两次全量连续全绿，未出现既有 flake（T108 记录的
  `test_g08_short_budget_cancels_inflight_model_call` 两次都通过），未触发隔离复跑。
- 本包测试无 `pytest.mark.skip/xfail`；`test_holdout_suite.py` 1 条按新契约同步（断言只加强）。

## B. local run / gate（本轮实跑）

| suite | run_id | 状态 | gate |
| --- | --- | --- | --- |
| b0 | `b0-local-20261108T151905251584Z-ed5fe092` | pass 29 / fail 3 / skipped 8 | exit 3，hard `[]` |
| badcase | `badcase-local-20261108T151909474037Z-8990c5bf` | pass 9 / fail 4 | exit 3，hard `[]` |
| regression（父提交代码） | `regression-local-20261108T151309992264Z-3610698c` | pass 5 / fail 2 | exit 3，hard `[]` |
| regression（本轮） | `regression-local-20261108T151824473835Z-812686c9` | pass 5 / fail 2 | exit 3，hard `[]` |

对照细节见证据 03：b0/badcase 对 P0 与对父提交均 `case_diffs=0`、整行逐字段一致（去 volatile）、
键顺序不变；regression 仅 RG006 变化（`clarification`→`answer`，两侧均 pass），gate unknown 集合一致。

## C. RG006 实跑文本（本轮 regression run）

```text
RG006 turn1: 滨江店的宣传海报的数量是多少？ → answer「根据资料，滨江店的宣传海报的数量：40张。」
RG006 turn2: 那个海报呢                  → answer「根据资料，滨江店的宣传海报的数量：40张。」
对照（同问题单轮、无上文）：                 → clarification「请问要查询宣传海报的哪项信息？…」
```

末轮答案只含数量（未出现「店内外侧」「QF01」等未问字段），`value_no_fabricated` 无多余数字。

## D. 合规核对

- 只改 handoff §2 允许路径：`evaluation/runner.py`、`backend/tests/`（本包新增 1 个文件 + 既有 1 条同步）、
  `fixtures/evaluation/regression.jsonl`（仅 RG006 一行，`cases_to_jsonl` canonical 落盘，
  `only_rg006_changed=['RG006']`）、证据 4 份、`report.md`。
- 未改 `conversations/`、`intent.py`、`rag/`、业务 API/schema、`gate_v0_1.json`、账本/GO、`.env`、
  `var/`、holdout 题目/答案；未读 `docs/evidence/.../P1-HOLDOUT/` 任何题目或答案内容。
- 基线 worktree 只复制了 `.gitignore` 忽略的 `subset-policy.json`（P0 dev 期的语料子集策略，
  与 holdout 无关）以保证语料装配口径一致；复制后 worktree `git status --short` 仍为空。
- 无新增依赖；无 skip/xfail；未 push/amend；单 commit。

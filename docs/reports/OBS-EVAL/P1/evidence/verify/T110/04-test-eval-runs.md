# T110 验收证据 04：测试、资源与合规

模型：`wb / cn:deepseek-v4.1-flash / reasoning_effort=max`（验收方证据，非交付物）

环境：Windows；仓库根 `D:\GPT项目\市场部AI知识库`；`.venv\Scripts\python.exe` 3.12.7；
每个 pytest 命令前设置 `$env:MKTKB_PROJECT_TOTAL_LIMIT_CNY="20.0"`，使用
`-B -q -p no:cacheprovider --basetemp backend\.pytest-tmp\T110-verify\<label>`。
零真实模型 / embedding / rerank / OCR；未读 `.env`；未读 Holdout 实际题目/标签。

## A. 起点与交付边界

```text
git status --short                        -> 空
git rev-parse --abbrev-ref HEAD           -> p1/fix-retrieval
git log -1 --oneline                      -> 6c82a8f p1/T110 retrieval gold + same-chunk ranking metrics
git rev-parse 6c82a8f^                    -> 3e58d368ed3cc8282ee70f2d9defa9123ec665c0
git show --stat 6c82a8f                   -> 9 files, 895 insertions, 16 deletions
git show 6c82a8f -- fixtures docs/evaluation -> 空
git diff 3e58d36 6c82a8f -- gate.py docs/evaluation fixtures -> 空
```

9 个文件：`gold.py`、`scorers.py`、`test_p1_t110_retrieval_metrics.py`、
`test_scorers.py`、`report.md`、T110 证据 01–04。无 `gate.py`/`runner.py`/`dataset.py`/
业务代码/API/intent/账本/GO/fixtures 改动；未新增依赖；无 `pytest.mark.skip`/`xfail`；
`test_scorers.py` 只把 1 条旧 nDCG 期望按新口径更新（原 `assert` 保留，另加
`retrieved_units==3`），未删除断言。report 71 行五段（Python 按 UTF-8 计），交付证据 4 份。

## B. pytest（各范围各 1 次；本包单独跑 1 次后又作为 evaluation/full 的子集执行）

| 范围 | 命令（cwd=backend） | 结果 |
| --- | --- | --- |
| 本包 | `..\.venv\Scripts\python.exe -B -m pytest tests/evaluation/test_p1_t110_retrieval_metrics.py -q -p no:cacheprovider --basetemp=...\pkg` | **17 passed**, 1 warning, 1.57s, exit 0 |
| `tests/evaluation` | 同上 `tests/evaluation` | **409 passed**, 1 warning, 87.29s, exit 0 |
| 全量 `tests` | 同上 `tests` | **1812 passed**, 1 warning, 473.63s, exit 0 |

全量 0 failed / 0 error / 0 skipped；无 flake 出现，故**未触发**隔离复跑（NOT-RUN）。
内存：全量期间对 pytest 进程（含 venv launcher 与实际 3.12.7 解释器）分段轮询 6 次，
间隔 20–60s（非全程连续）：`269.3 / 362.0 / 369.8 / 397.2 / 395.6 / 413.4 MB`，
峰值 **413.4 MB < 2 GB**。第一次样本 20s 时 pytest 已进入收集/执行；进程
`36408` 为实际解释器，`23668` 为 launcher（4.5 MB）。

## C. 门禁

在 `backend\.pytest-tmp\T110-verify\gate-{b0,badcase,regression}`（T110 run 的副本）上
执行：

```text
.venv\Scripts\python.exe -B -m mktkb.evaluation.cli gate \
  --run <copy> --config docs\evaluation\gate_v0_1.json
```

| suite | exit | hard_failures | unknown | 五指标 observed |
| --- | --- | --- | --- | --- |
| b0 | 3 | `[]` | 42 | .96875 / .96875 / .96875 / 0 / .03125 |
| badcase | 3 | `[]` | 94 | .7855614973 / .85 / .7499953095 / 0 / .1 |
| regression | 3 | `[]` | 80 | 1.0 / .75 / .8154649 / 0 / 0 |

exit 3 为既有 `thresholds_unapproved` + `min_sample`/unknown（T112 范围），非 T110 新增
hard；gate 从 summary 读取并展示五个字段，阈值/审批未改（`docs/evaluation` 无 diff）。

## D. 回归签名

验收方独立比较（签名 = status / outcome.kind / checks / error.code；另比 retrieved）：

```text
b0         40/40  signature 0  retrieved 0
badcase    13/13  signature 0  retrieved 0
regression  7/7   signature 0  retrieved 0
```

regression 对 T109 R2：RG006 `pass/answer`；RG005/RG007 checks+metrics 完全一致；
gate 两侧 hard `[]`、unknown 80。b0/badcase 对 P0：hard `[]`、unknown 42/94 一致；
Q25 等仅 metrics 变化，checks/status/kind/error 不变。

## E. 合规 / 残余

- 未读 `.env`；未做真实 provider 调用；未 push/commit/切分支/stash/reset；未改交付物；
  仅新增本目录 4 份验收证据与 `review.md`。
- **流程瑕疵（如实披露）**：一次 `rg -n "record_code" fixtures/evaluation -g "*.jsonl"`
  （及一次同目录 `relevant_units` 搜索）的范围包含 `holdout-questions.jsonl`，该文件被
  ripgrep 扫描；输出未显示、结论未使用任何 Holdout 内容。严格按“不读 Holdout”边界属
  越界，若 PM 要求零扫描需全新上下文重跑。
- 残余（非阻断）：`relevant_units` 非空真实数据在 b0/badcase/regression 三套 fixture
  中均为 0 条（Python 计数），override/fail-closed 仅由合成索引覆盖；`record_code` +
  `locator: {}` 仍会解析整篇（既有 fail-open，gate 记 unknown）；`empty_recall_rate`
  沿用 P0“无任何 retrieved unit”语义；nDCG 的单 chunk 单 gain 是保守下界（见 01/03）。

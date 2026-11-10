# T108 证据 01：起点状态与本包范围

## A. 起点

- 分支 `p1/fix-retrieval`，HEAD `31143f2`（`chore(p1): T108 handoff + dev/verify prompts`）；
  开工前 `git status --short` 为空（clean）。
- 输入（按 handoff §2 顺序）：`.claude/handoffs/T108-holdout-support/handoff.md`；
  `2026-11-04-p1-design.md` §4 / §7.4；`2026-11-04-p1-task-breakdown.md` §T108；
  `docs/evidence/LOCAL-R1-20261101/P1-HOLDOUT/README.md`（**只取路径与 sha256**）；
  `backend/src/mktkb/evaluation/{dataset,runner,cli,gate}.py`；`corpus.py`（只读）；
  `fixtures/evaluation/{b0,badcase,regression}.jsonl`（只读，未改）；
  `.claude/handoffs/prompts/p1-holdout-author.md`（§4.1/§4.2 字段表）。
- 红线执行：**未读** `docs/evidence/.../P1-HOLDOUT/` 下 questions/labels 的任何一行内容；
  仓库导出从 PM 副本 `.claude/handoffs/_scratch/T108/questions-copy.jsonl` 逐字节复制；
  为确认字段白名单，只打印该副本的 key 名、行数、分层计数、label_version、sha256
  （无题干/答案值；见 §C 的 shell 口径）。

## B. 改动清单（只动 handoff §3 允许路径）

| 文件 | 性质 | 要点 |
| --- | --- | --- |
| `backend/src/mktkb/evaluation/dataset.py` | 扩展 | holdout 常量/策略/加载/合并/导出；`refusal` 兼容 kind |
| `backend/src/mktkb/evaluation/runner.py` | 扩展 | `suite=holdout` 分支：默认聚合、details+audit、CI 拒绝、trace 不落盘 |
| `backend/src/mktkb/evaluation/cli.py` | 扩展 | `--holdout-labels`、`--allow-holdout-details`、`dataset validate/export-holdout-questions` |
| `backend/src/mktkb/evaluation/gate.py` | 扩展 | 聚合 run 可用（exit 3 + 显式 unknown）；详情 run 拒绝 |
| `backend/tests/evaluation/test_holdout_suite.py` | 新增 | 34 条：聚合/详情/CI/拒绝条件/仓库导出/CLI |
| `backend/tests/evaluation/test_cli.py` | 最小同步 | 2 处：flag 契约、`run_suite` kwargs 透传 |
| `backend/tests/evaluation/test_regression_suite.py` | 最小同步 | 1 行：非法 suite 示例改用 `holdout-typo`（holdout 已是合法 suite） |
| `fixtures/evaluation/holdout-questions.jsonl` | 新增 | 30 行、sha256 `a8c8aa7f…6738`、13 键、无答案字段 |

## C. 未做 / 明确不在本包

- 未改 `corpus.py`（holdout 语料复用 `load_suite_corpus("regression", …)` 的全量企业语料装配口径，
  从而不触碰不在交付清单里的文件）；未改 `scorers.py`/`gold.py`（T110）、未改 `gate_v0_1.json`（T112）。
- 未运行真实 holdout（无 labels，也不允许读）；真实受限运行由验收方执行。
- 未改 `intent.py`/业务 API/前端/`var/`/账本/GO；无新依赖；无 skip/xfail。

## D. 仓库导出核对

```text
sha256(fixtures/evaluation/holdout-questions.jsonl) =
a8c8aa7f028ce14047173e3e57db36dda72d3a13b3578ad82ec8cd1b86cd6738   （= PM 副本，逐字节相同）
lines = 30；keys = 13（business_date, case_id, expected_kind, label_version, labeler, notes,
question, requires_ocr, should_refuse, split, stratum, suite, turns）；无答案字段。
```

`labels.jsonl`（sha256 `8f713a2a…c1bf`）只以常量形式出现在 `dataset.py`，仓库内没有任何 labels 文件
（测试 `test_repository_export_is_answer_free_and_pinned` 断言 `fixtures/evaluation` 下无 `*labels*`）。

# T112 独立验收证据 03：测试、回归、提交与范围

模型：`wb / cn:deepseek-v4.1-flash / reasoning_effort=max`

## A. pytest（cwd=仓库根；每次 `MKTKB_PROJECT_TOTAL_LIMIT_CNY=20.0`）

```text
backend/tests/evaluation/test_t112_gate_baseline.py -q --basetemp backend\.pytest-tmp\t112v-pkg
  -> 13 passed, 1 warning in 1.06s
backend/tests/evaluation -q --basetemp backend\.pytest-tmp\t112v-eval
  -> 433 passed, 1 warning in 173.31s
backend/tests -q --basetemp backend\.pytest-tmp\t112v-full
  -> 1933 passed, 1 warning in 622.41s（0 failed / 0 error）
backend/tests -q --basetemp backend\.pytest-tmp\t112v-full2（二次，内存轮询）
  -> 1933 passed, 1 warning in 735.21s；Python 进程 WorkingSet 合计峰值 594.9MB（<2GB，6 进程）
```

- 唯一 warning 为既有 `StarletteDeprecationWarning`；未触发既有 flake，无需隔离复跑。
- 新增测试无 skip/xfail；`git diff cd1b3ca..4c2b7ba` 未改 `pyproject.toml`/`uv.lock`；
  live 账本 chat=0（见证据 02）。

## B. local b0/badcase/regression + gate（P0/T114 对照）

命令：`cli run --suite <suite> --mode local --out .claude\handoffs\_scratch\T112v\eval\<suite>`；
`cli gate --run ...`（默认 P0 v0.1 配置）。

```text
b0:         rows 40/40  signature_diffs=0 retrieved_diffs=0 gate exit 3 hard=[] unknowns=42
badcase:    rows 13/13  signature_diffs=0 retrieved_diffs=0 gate exit 3 hard=[] unknowns=94
regression: rows 7/7    signature_diffs=0 retrieved_diffs=0 gate exit 3 hard=[] unknowns=80
```

- 对照：b0 对 `var/eval/runs/p0-b0` 与 `backend/.pytest-tmp/T114/eval/b0`；
  badcase 对 `var/eval/runs/p0-badcase` 与 T114；regression 对 T114。
- b0/badcase 的签名/retrieved 对 P0 为 0 diff，但 MRR/nDCG/Recall 数值与 P0 不同
  （P0 为旧评分口径；对 T114 数值一致，仅 latency 不同），故不把“指标对 P0 相同”
  当作验收依据。
- 三套 gate 的 exit 3 均为既有 `min_sample_missing`/`thresholds_unapproved`，无 hard failure。

## C. 提交与报告事实

```text
HEAD=4c2b7ba（父 6b614b5）；7f46121 父 cd1b3ca；git reflog 仅一次 7f46121 创建，无 amend 记录
git diff --name-status 7f46121 4c2b7ba = 9 paths:
  4 个 R1 交付：report.md / test_t112_gate_baseline.py / gate_v0_2.json / 03-gate-config-and-baseline.md
  5 个 .claude/handoffs/** PM 簿记：pause handoff / T112 handoff / _index / prompts R1 / prompts verify
report.md = 105 行；R1 §6 未逐字披露上述 5 个 PM 文件，report:101 已披露“总行数超出 80 行预算”
```

- 开工时 `git status --porcelain` 为空；验收期间 `.claude/handoffs/_index.md` 于
  20:16:14 被 PM 并行改为“T112 独立验收中”，工作树出现该 1 个未提交 handoff 变更
  （HEAD 未变、非交付路径、非本次验收写入）。
- R1 测试 diff 只改 3 处 approved 相关：契约断言 approved+批准值；两个 unapproved
  用例改用临时副本；未删断言、无 skip/xfail。
- 报告/证据未含答案原文、逐题明细、凭据或 GO 原文。

## D. 范围诚实

- badcase / regression / holdout live：NOT-RUN；P0 跨版本比较：NOT-RUN（R0 §5 的理由
  “P1 baseline 未建”在 R1 后已过时；R1 段仅写“范围同 R0”，仍登记为未跑，未声称通过）；
  未审批的 answer/refusal/runtime 阈值：仍 null，未声称通过。
- 证据 4 份（R0）+ 本 verify 3 份；交付 run 的 manifest/cases/summary 未被改写
  （artifact 摘要与 baseline 记录一致）；R1 为现场重算改写了派生 `gate.json`（exit 3→0），
  R1 报告 §R1 已披露。

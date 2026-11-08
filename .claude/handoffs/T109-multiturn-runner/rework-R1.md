# T109 返工单 R1（PM，2026-11-09 00:3x）

> 依据：独立验收 `review.md`（FAIL：1 阻断；其余 PASS；无 NOT-RUN）+ `verify/T109/`。轮次 **R1/3**。
> 基线：T109 交付 `703b7e0`（父 `ebfe956`）；本轮 **1 个新 commit**，**不 amend 历史**。
> 执行者：开发 subagent（`wb / cn:deepseek-v4.1-flash`，`reasoning_effort=max`）。PM 不写代码。

## 1. 必须修（阻塞）
### B1 replay 源单轮 run 遇多轮 case 静默只写 1 条 trace
- 复现（验收方）：源 = 父提交 regression run（RG002/RG003/RG006 行无 `turn_traces`），`run --suite regression --mode replay --from-run <父run> --dataset <父fixture>` → 三行均 `status=pass`、`turns_executed=1`、`multi_turn_claimed=True`、`turn_traces` 仅 1 条、`error=None`（静默只 replay 首轮）。
- 代码路径：`runner.py:1178` 只读源 `turn_traces`；`:1227/:1251` 无源轮记录时走 `_replay_traces`；`:1130` 的 `len(source_turns) <= 1` 写单条 provenance。
- 期望：`len(case.turns) > 1` 且源行无 `turn_traces`（或源轮数 < case 轮数）→ **fail closed**（行 `status=fail` 或明确异常，`error` 含明确 code 如 `multi_turn_source_missing`/`multi_turn_source_incomplete`），**不得写单条 replay 并声称通过**。补测试（源单轮 run + 多轮 case；源多轮但轮数不足）。
- 不得伪造逐轮结果。

## 2. 一并收口（非阻塞，验收方指出；本轮修）
- **R1 error 明细**：中间轮 `kind=error/service_error`/Trace 不可读时 case 正确 fail，但 `error=None`；应填 `error`（含 code 与 `turn n/N` 明细），与 report/docstring 口径一致。
- **R2 error-row `turns_executed`**：malformed turns / gold 解析失败等未执行轮次的 multi-turn 行仍记 `1`（默认值）；应记实际/应有轮数（如 `len(case.turns)` 或已执行数），report 说明。
- **R3 replay 逐轮 trace 题面**：replay 每轮 trace 的 question 用末轮问题；应对应各轮 question（源轮数据），report/证据说明。

## 3. 允许修改范围
`backend/src/mktkb/evaluation/runner.py`、`backend/tests/evaluation/`（本包测试）、`report.md`（追加 R1 段并修正 §1 措辞）、证据 `docs/reports/OBS-EVAL/P1/evidence/T109/02-multiturn-contract.md`、`03-runs-and-comparisons.md`、`04-tests-and-compliance.md` 追加 R1 段（不新增文件）。
禁止：fixtures（RG006 已按 T109 口径收口，不再改）、b0/badcase、业务代码/API/intent/schemas、dataset/gate 语义、账本/GO、`.env`/Holdout、真实调用、push/amend、skip/xfail/删断言。

## 4. 必跑
本包测试 / `backend/tests/evaluation` / 全量 `backend/tests`（0 failed/0 error；内存 <2GB 轮询；既有 flake 隔离复跑 1 次；**pytest 前必须 `$env:MKTKB_PROJECT_TOTAL_LIMIT_CNY="20.0"`**）/ b0/badcase 对 P0（`case_diffs=0`、hard `[]`）/ regression 当前 vs 父提交（RG006 保持 T109 后期望、RG002/RG003 PASS、RG005/RG007 不变、无新 hard）/ replay 分支回归（单轮 replay 不变；多轮 replay 合法源仍逐轮）。命令口径同前；同一时间只跑一套 pytest。

## 5. 交付
- 1 个新 commit：`p1/T109 R1 replay fail-closed for single-turn sources + error details`；不 push/不 amend。
- report 追加 R1 段（B1 修复前后复现命令/结果；R1–R3 口径；运行数字；残余）；证据 02/03/04 追加 R1 段。
- 回复 ≤10 行摘要（commit、B1 证据、R1–R3、测试数字、偏离、风险）。

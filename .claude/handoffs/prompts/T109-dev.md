角色：开发助手。任务 **T109（多轮 turns runner）**。完整交接单待落盘 `.claude\handoffs\T109-multiturn-runner\handoff.md`（以正式文件为准）。
模型：`wb / cn:deepseek-v4.1-flash / reasoning_effort=max`（report 首行注明）。
工作目录 `D:\GPT项目\市场部AI知识库`；分支 `p1/fix-retrieval`；开工前 `git status --short` clean。

要点（详见 handoff）：
- local 模式按 `turns` 顺序执行（同一 conversation/user，逐轮 `qa.answer`），每轮生成 trace 并持久化 trace_id（`previous_trace_id` 串联）；
- 判定：末轮按现有 scorer/gold 评分；中间轮不逐轮判分只要求无 error + Trace 完整；case 通过 = 全轮无 error + 末轮 checks 全通过；
- 单轮不变（`turns_executed=1`、既有字段/值不变；b0/badcase 对 P0 `case_diffs=0`）；
- cases.jsonl 扩展 `turn_traces`/`turns_executed`，`trace_id` 仍为末轮；replay 多轮逐轮或明确硬错误，不得静默首轮；
- **RG006（PM 裁决）**：仅该行按多轮口径更新（turn1 滨江店数量→turn2 那个海报呢；末轮只答数量=40 张；kind=answer/values 含 40；保留未问字段 forbidden；notes 写多轮口径；禁止放宽）。RG001–RG005/RG007 不动；RG002/RG003 多轮执行后仍 PASS。
- 允许：`evaluation/runner.py`、`backend/tests/`、`fixtures/evaluation/regression.jsonl`（仅 RG006 一行）、证据 4 份、report ≤80 行、1 commit。
- 禁止：其他 fixtures/业务代码/API/intent/gate 配置/账本/GO/.env/Holdout/真实调用/push/amend/skip/xfail/删断言。
- 必跑：本包 / `backend/tests/evaluation` / 全量（0 failed/0 error；内存<2GB 轮询；flake 隔离复跑 1 次）/ b0+badcase 对 P0（case_diffs=0、hard []）/ regression 当前（含 RG006 更新）vs 父提交（逐例说明 RG006 变化、其余不变、无新 hard）。
- 交付：1 commit `p1/T109 multi-turn turns runner`；report 五段 ≤80 行；回复 ≤10 行摘要。

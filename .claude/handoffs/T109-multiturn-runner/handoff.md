# T109 交接单：多轮 turns runner（P1 第 10 包）

> 基线：分支 `p1/fix-retrieval`（T100–T107/T101–T106/T108 已 G6；当前 HEAD `7cbc196`）。
> 执行者：开发 subagent（`wb / cn:deepseek-v4.1-flash`，`reasoning_effort=max`）。PM 不写代码。
> 关键背景：T109 后 RG002/RG003/RG006 的多轮形态才真实执行；RG006 允许按 PM 裁决更新**一行**（见 §0-6）。

## 0. PM 口径（先读）
1. **local 多轮执行**：`turns` 非空 case 按顺序执行（同一 conversation_id/user，逐轮 `qa.answer`，状态自然继承）；每轮生成 trace 并持久化 trace_id。
2. **判定口径**（设计 §4 多轮）：末轮按现有 scorer/gold 评分；中间轮**不逐轮判分**，只要求无 error 且 Trace 完整；case 通过 = 全部轮次无 error + 末轮 checks 全通过。中间轮 checks/outcome 可记录但不参与通过判定。
3. **单轮不变**：`turns` 为空/单元素时行为与父提交一致（`turns_executed=1`、既有字段/值/顺序不变）；b0/badcase 对 P0 `case_diffs=0`（N06/N11 turns 空保持单轮）。
4. **cases.jsonl 扩展**：新增 `turn_traces`（有序 `{turn, trace_id, status}`）与 `turns_executed`（多轮=len，单轮=1）；`trace_id` 保持=**末轮** trace 以兼容既有消费方；不得删/改既有字段语义。
5. **replay**：多轮 replay 必须逐轮 replay（源 run 为多轮时）或**明确硬错误**（不支持多轮 replay）；不得静默只跑首轮。
6. **RG006 口径更新（PM 裁决）**：T109 后 RG006 多轮真实执行（turn1 滨江店海报数量 → turn2 那个海报呢；T105 行为=末轮只答数量，W11 数据 40 张）。允许**仅 RG006 一行**更新 `expected_kind/expected_values/forbidden_values/reference_answer/notes`（kind=answer、expected_values 含「40」；**保留**已确认禁止值如「店内外侧」等未问字段，禁止为通过而放宽）；notes 写明多轮口径。RG001–RG005/RG007 一律不动；RG002/RG003 多轮执行后必须仍 PASS。
7. 零真实调用；不改 `conversations/`/`intent.py`/业务 API/字段结构/b0/badcase/gate 配置；不 push/amend。

## 1. 目标
`turns` 非空 case 顺序执行、逐轮记录 Trace、全部轮次（按口径）通过才算 case 通过；单轮行为不变；RG002/RG003/RG006 多轮形态可真实复跑。

## 2. 交付物（只准写这些路径）
1. `backend/src/mktkb/evaluation/runner.py`（local 多轮执行/判定、逐轮 trace、cases.jsonl 字段、replay 处理、manifest 标记）。
2. `backend/tests/` 本包测试（多轮顺序与会话状态继承、中间轮 error→fail、末轮 fail→fail、单轮不变、逐轮 trace 关联、replay 行为、RG006 多轮）。
3. `fixtures/evaluation/regression.jsonl`：**仅 RG006 一行**按 §0-6 更新。
4. `docs/reports/OBS-EVAL/P1/evidence/T109/`（≤4）、`report.md`（五段 ≤80）、1 commit。
禁止：其他 fixtures、业务代码、API schema、gate 配置、账本/GO、`.env`/Holdout、真实调用。

## 3. 验收标准（逐条）
1. 多轮按序执行且同一 conversation 状态继承（RG006/合成用例证明）；`turns_executed` 正确。
2. 判定：中间轮 error→case fail；末轮 checks fail→case fail；中间轮 checks 不决定通过；全通过→case pass；有测试。
3. 逐轮 trace：每轮 trace_id 记录且 observability store 可查、`previous_trace_id` 串联上一轮；cases.jsonl 既有字段不变。
4. 单轮不变：b0/badcase 对 P0 `case_diffs=0`；单轮既有测试/数字不变；`turns_executed=1`。
5. replay：逐轮或明确拒绝，无静默首轮；有测试。
6. regression：RG006 多轮口径更新后 PASS 且非放宽（保留未问字段 forbidden）；RG001–RG005/RG007 状态不变；gate 无新 hard；全量 0 failed/0 error。
7. 合规：只改允许路径、无 skip/xfail/删断言、零真实调用、证据 ≤4/report ≤80、单 commit、b0/badcase/regression 前后对照留证。

## 4. 必跑
本包测试 / `backend/tests/evaluation` / 全量 `backend/tests`（0 failed/0 error；内存 <2GB 轮询；flake 隔离复跑 1 次）/ b0/badcase local+gate 对 `var/eval/runs/p0-b0`/`p0-badcase`（`case_diffs=0`、hard `[]`）/ regression 当前（含 RG006 更新）vs 父提交（逐例说明 RG006 变化、其余不变、无新 hard）。命令口径同前。

## 5. 坑
- 多轮必须复用同一 conversation_id/user；不要每轮新建会话。
- trace provenance：每轮 `_write_provenance_trace` 并 `previous_trace_id` 链接；不要只写末轮。
- replay 源单轮 run 遇多轮 case：明确错误；不得伪造逐轮结果。
- 单轮 path 不得被新分支污染（gold/scorer 输入不变）。
- RG006 更新必须逐例 before/after + 语义正确性证明；禁止放宽 forbidden/摘要。

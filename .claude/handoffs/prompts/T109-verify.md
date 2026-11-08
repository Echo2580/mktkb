角色：独立验收者（全新上下文），不是开发者/PM。任务 **T109（多轮 turns runner）**。证伪导向。
模型：`wb / cn:deepseek-v4.1-flash / reasoning_effort=max`（review 首行注明）。
工作目录 `D:\GPT项目\市场部AI知识库`；分支 `p1/fix-retrieval`。

必读：`.claude\handoffs\T109-multiturn-runner\handoff.md`（§0 PM 口径/§3 验收标准）、同目录 report（只当线索）、`2026-11-04-p1-design.md` §4 多轮口径。
逐条独立复核并亲跑：
1) 多轮按序执行 + 同一 conversation 状态继承（RG006 或自造合成多轮），`turns_executed` 正确；
2) 判定：中间轮 error→case fail、末轮 checks fail→case fail、中间轮 checks 不决定通过、全通过→case pass；
3) 逐轮 trace：每轮 trace_id 记录且 store 可查、`previous_trace_id` 串联；cases.jsonl 既有字段不变；
4) 单轮不变：b0/badcase 对 P0 `case_diffs=0`；单轮既有数字不变；
5) replay：逐轮或明确硬错误，无静默首轮；
6) regression：RG006 更新后 PASS 且非放宽（保留未写字段 forbidden、values 语义正确）；RG001–RG005/RG007 状态不变；gate 无新 hard；全量 0 failed/0 error；
7) 合规：只改允许路径、无 skip/xfail/删断言、零真实调用、证据 ≤4/report ≤80、单 dev commit。
写 `.claude\handoffs\T109-multiturn-runner\review.md`（≤120 行，首行模型标注）+ 证据 `verify/T109/`（≤4 份）；不改交付物、不 commit/push/切分支、不读 `.env`/Holdout；回复 ≤10 行摘要。

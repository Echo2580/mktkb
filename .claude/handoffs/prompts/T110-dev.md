角色：开发助手。任务 **T110（检索金标与检索指标）**。交接单待落盘 `.claude\handoffs\T110-retrieval-gold-metrics\handoff.md`（以正式文件为准）。
模型：`wb / cn:deepseek-v4.1-flash / reasoning_effort=max`（report 首行注明）。
工作目录 `D:\GPT项目\市场部AI知识库`；分支 `p1/fix-retrieval`；开工前 `git status --short` clean。

要点（详见 handoff）：
- `relevant_units` 语义按 P0 追认口径（`unit_key` 身份型严格唯一；`locator` 范围型→unit 集合；0/多匹配 fail closed）；非空时作为检索金标，空时保持 P0 fallback 用 expected_sources；两者皆空则无检索金标（不进分母），不得伪造。
- **指标口径修正（同 chunk 同排名）**：以 retrieved **chunk（EvalRetrieved 条目）排名**为排名单位；同一 chunk 多 unit 共享排名（不得按出现顺序编造 1,2,3）；Recall@10=top-10 chunk 相关 unit 去重命中/相关 unit 总；MRR@10=1/首个含相关 unit 的 chunk 排名（>10→0）；nDCG@10 按 chunk 排名计 DCG（同 chunk 相关 unit 共享位置）；unit 去重；无 gold/跳过不进分母。
- `hard_filter_violation_rate`（违规检索 unit/全部检索 unit）与 `empty_recall_rate`（空召回 case 比例）保持/修正并入手算对照；指标写 summary（字段名与 P0 兼容）且 gate 可消费（不改阈值/审批，T112 负责）。
- 手工对照：≥4 case 手算表（同 chunk 多 unit、重复 unit、空召回、部分命中）与代码逐值一致，写证据。
- 允许：`evaluation/{gold,scorers}.py`、`evaluation/gate.py`（仅消费/展示，如已有则免改并在 report 说明）、`backend/tests/`、证据 4 份/report ≤80 行/1 commit。
- 禁止：`docs/evaluation/gate_v0_2.json`（T112）、b0/badcase/regression 数据、业务代码/API/intent、账本/GO、`.env`/Holdout、真实调用、push/amend、skip/xfail/删断言。
- 必跑：本包 / `backend/tests/evaluation` / 全量（0 failed/0 error；内存<2GB 轮询；flake 处理）/ b0+badcase 对 P0（`case_diffs=0`、hard `[]`）/ regression 状态不变（RG006 保持 T109 后状态）。
- 交付：1 commit `p1/T110 retrieval gold + same-chunk ranking metrics`；report 五段 ≤80 行（含 before/after 指标与手算对照）；回复 ≤10 行摘要。

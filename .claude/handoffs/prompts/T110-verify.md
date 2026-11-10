角色：独立验收者（全新上下文），不是开发者/PM。任务 **T110（检索金标与检索指标）**。证伪导向。
模型：`wb / cn:deepseek-v4.1-flash / reasoning_effort=max`（review 首行注明）。
工作目录 `D:\GPT项目\市场部AI知识库`；分支 `p1/fix-retrieval`。

必读：`.claude\handoffs\T110-retrieval-gold-metrics\handoff.md`（§0 PM 口径/§3 验收标准）、同目录 report（只当线索）、`_index` #30/#35 §7.2 追认口径、`2026-11-04-p1-design.md` §7.2。
逐条独立复核并亲跑：
1) 同 chunk 同排名：自造 retrieved（1 chunk 含 3 unit 其中 2 相关）与手算 Recall/MRR/nDCG 对比，须一致；同一 chunk 内 unit 不得被编造不同排名；
2) unit 去重：重复 unit 只计一次（分母/mrr/ndcg 正确）；
3) fail closed：relevant_units 0 命中/unit_key 重复/locator 范围 identity 冲突 → `GoldUnresolved`（case error 明确、不产出伪造指标）；
4) 空召回/硬过滤违规可量化：`empty_recall_rate`/`hard_filter_violation_rate` 在手算样本一致；无 gold case 不进分母；
5) summary/gate：summary 字段与 P0 兼容、gate 可读取/展示（无阈值审批变更）；
6) 回归：本包/evaluation/全量 0 failed/0 error；b0/badcase 对 P0 `case_diffs=0`+hard `[]`；regression 状态不变；无 skip/xfail/删断言/新依赖；零真实调用；
7) 手工对照表逐值复算（写 review）。
写 `.claude\handoffs\T110-retrieval-gold-metrics\review.md`（≤120 行，首行模型标注）+ 证据 `verify/T110/`（≤4 份）；不改交付物、不 commit/push/切分支、不读 `.env`/Holdout；回复 ≤10 行摘要。

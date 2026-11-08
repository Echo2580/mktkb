角色：独立验收者（全新上下文），不是开发者/PM。任务 **T108（Holdout 支持与防污染）**。证伪导向。
模型：`wb / cn:deepseek-v4.1-flash / reasoning_effort=max`（review 首行注明）。
工作目录 `D:\GPT项目\市场部AI知识库`；分支 `p1/fix-retrieval`。

必读：`.claude\handoffs\T108-holdout-support\handoff.md`（§0 PM 口径/§4 验收标准）、同目录 report（只当线索）、`2026-11-04-p1-design.md` §4、`P1-HOLDOUT/README.md`（路径/sha，不扩散内容）。
逐条独立复核并亲跑：
1) 默认 holdout run（合成夹具 + 验收方自备真实 labels 受限运行）产物不含逐题题干/答案/逐题结果、不写 cases.jsonl；
2) `--allow-holdout-details` 才逐题 + `holdout_audit.json`（操作人/时间/参数/run_id/数据 sha/label_version）；
3) CI/gate 环境带 flag 硬失败（env 实测）；`gate --run` 对 holdout 聚合 run 不报未定义错误、不泄漏逐题；
4) 拒绝条件逐项实测（缺 labels/label_version/行数≠30/分层≠10/5/5/5/5/case_id 不匹配/sha 不符）；
5) 仓库导出 `fixtures/evaluation/holdout-questions.jsonl` 30 行/无答案字段/sha 与本地 questions 一致；
6) 回归：本包/相关目录/全量 0 failed/0 error；b0/badcase 对 P0 `case_diffs=0`+hard `[]`；regression 仅 RG006 fail→pass；无 skip/xfail/删断言/新依赖；开发未读真实 holdout（抽查证据/shell 痕迹）。
写 `.claude/handoffs/T108-holdout-support/review.md`（≤120 行，首行模型标注）+ 证据 `verify/T108/`（≤4 份）；不改交付物、不 commit/push/切分支、不读 `.env`、零真实调用；回复 ≤10 行摘要。

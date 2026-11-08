角色：开发助手。任务 **T108（Holdout 支持与防污染）**。
模型：`wb / cn:deepseek-v4.1-flash / reasoning_effort=max`（report 首行注明）。
工作目录 `D:\GPT项目\市场部AI知识库`；分支 `p1/fix-retrieval`；开工前 `git status --short` clean。

第一步：完整读 `.claude\handoffs\T108-holdout-support\handoff.md`（尤其 §0 PM 口径/§3 交付物/§4 验收标准/§6 坑），按它执行。
- 你**不得读取** `docs\evidence\LOCAL-R1-20261101\P1-HOLDOUT\` 目录；仓库导出 `fixtures/evaluation/holdout-questions.jsonl` 从 PM 提供的副本 `.claude\handoffs\_scratch\T108\questions-copy.jsonl` 生成（PM 会放好；只读副本）。
- 默认聚合、details 需 `--allow-holdout-details` + `holdout_audit.json`、CI/gate 环境带 flag 硬失败、缺 label_version/sha/分层/30 行拒绝——逐条实现并测试（合成 holdout 夹具）。
- 允许：`evaluation/{dataset,runner,cli,gate}.py`、`backend/tests/`、`fixtures/evaluation/holdout-questions.jsonl`、证据/报告。禁止：真实 holdout/labels、b0/badcase/regression、intent/业务 API、gate 配置、账本/GO、`.env`、真实调用、push/amend、skip/xfail/删断言。
- 必跑：本包测试 / `backend/tests` 相关目录 / 全量（0 failed/0 error；内存<2GB 轮询）；b0/badcase 对 P0（`case_diffs=0`、hard `[]`）；regression 对 `17c0e63`（仅 RG006 fail→pass、其余不变）；证据 4 份、report ≤80 行、1 commit `p1/T108 holdout support + anti-leak guardrails`。
- 结束时 reply ≤10 行摘要。

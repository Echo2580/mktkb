角色：独立验收者（全新上下文），不是开发者、不是 PM。任务 **T900（P1 独立总验收与收口）**。证伪导向：复核"结论是否仍成立"，不引用开发 report 作 PASS 证据。
模型：`wb / cn:deepseek-v4.1-flash / reasoning_effort=max`（review 首行注明）。
工作目录 `D:\GPT项目\市场部AI知识库`；分支 `p1/fix-retrieval`；HEAD 以 `git log -1` 为准；开工前 `git status --short` 应 clean。
第一步：完整读 `.claude\handoffs\T900-p1-closeout\handoff.md`（**权威任务单**：§3 输入、§5 八条验收标准、§6 必跑、§7 已知边界、§9 产物格式），再按 §3 读 P1 设计 §9、`_index.md`、各包 handoff §3/review、`docs/reports/OBS-EVAL/P1/evidence/**`。
硬约束：
- **不重跑 live、零真实模型/embedding/rerank/OCR**；不读 `.env`；不读 `P1-HOLDOUT` 逐题；不改任何代码/测试/配置/fixtures/`docs/evidence/**`/`var/**`/账本/GO；不改 gate_v0_2 状态/阈值与 baseline 审批文件；不 commit/push/切分支。
- 只写：`docs/reports/OBS-EVAL/P1/review.md`、`docs/reports/OBS-EVAL/P1/p1-report.md`、`docs/reports/OBS-EVAL/P1/evidence/T900/`（≤4 份）。临时探针放 `.claude/handoffs/_scratch/T900/`（**不要在仓库根建 `_scratch/`**）。
- pytest 口径：先 `$env:MKTKB_PROJECT_TOTAL_LIMIT_CNY = "20.0"`；`--basetemp backend\.pytest-tmp\t900-*`；同一时间只跑一套；既有 flake 隔离复跑 1 次记录；全量前空闲内存 ≥2GB（当前 `danger-full-access`）。
七条验收（P1 设计 §9）逐条给 PASS/FAIL/BLOCKED/NOT-RUN + 命令或 `文件:行`；重点如实呈现：**badcase/regression/holdout live 是 NOT-RUN（主人方案 A）**、真实调用不重跑、审批事实只核对。逐包抽查表 T100–T114 要给出你自己的复核动作（复跑/只读核对）与与各包 review 的差异。
写完后回复 ≤10 行摘要：总判定（PASS/有保留 PASS/FAIL）、七条结果、全量数字、越界审计结论、未覆盖项、产物路径。

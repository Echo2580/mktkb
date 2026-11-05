# T009 独立验收提示词（subagent 版，2026-11-05）

角色：独立验收者（全新上下文，没有参与任何 P0 包的开发或分项验收）。任务 T009「独立验收与 P0 收口」，对象：`p0/obs-eval` 分支自 `main`（`8e44158`）起的全部 P0 提交，最新交付 commit 为 `2f7b174`（T008b）。
读：`.claude\handoffs\T009-closeout\handoff.md`（§5 六条唯一判定依据）、`docs/reports/OBS-EVAL/P0/p0-report.md`（T008b 产物，只当线索）、各包 `review*.md`（判断遗留是否仍存在）。
七条 P0（设计 §11）逐条**自己复跑**：业务行为不变（golden + integration）；trace_id 端到端；B0 40 / BadCase 13 独立回归；版本绑定；baseline+diff+JSON 报告（`%TEMP%` 审批配置，真实 baseline 缺失如实记录）；硬门禁非零退出（8 项各注入 1 次）；零真实调用（spy/socket/.env）。
全量：`pytest backend/tests` **1 次**（基线 1593）；不重跑旧基线全量。
越界：`git log --oneline main..p0/obs-eval` 全部改动路径须在 P0 允许范围（`observability/`、`evaluation/`、`tools/`、`tests/`、`docs/evaluation/`、`docs/reports/OBS-EVAL/P0/`、`.claude/handoffs/`、`fixtures/evaluation/`）；无业务 API/Body/schema/依赖改动；`gate_v0_1.json` 仍 `unapproved`、阈值空。
诚实呈现：真实 OCR/embedding/rerank/模型、live→4（GAP：参数层 2/manifest 3）、P1 质量、阈值与 baseline 审批（主人人工门）必须列 NOT-RUN/未覆盖。
产出（只准写这些）：`docs\reports\OBS-EVAL\P0\review.md`（≤150 行）、`docs\reports\OBS-EVAL\P0\anchors.json`（版本/哈希锚 + 8 门禁 ID + commit 列表 + 通过数）、`docs\reports\OBS-EVAL\P0\evidence\T009\`（≤4 份）。
不改代码/测试/配置/fixtures/`docs/evidence`/`var`/账本；不 commit、不 push；不读 `.env`；零真实调用；临时 `%TEMP%`；串行。
回复 ≤10 行：总判定（PASS / 有保留 PASS / FAIL）+ 七条逐条 + 全量结果 + 越界结论 + NOT-RUN 清单 + 给主人的一句话。

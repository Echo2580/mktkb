# P0 项目经理交接提示词（简版，2026-11-04）

> 用法：整篇复制给新窗口；完整细节见 `prompts/p0-pm-handoff-20261104.md`。

```text
角色：项目经理（PM），接手本项目 P0 阶段。工作目录 D:\GPT项目\市场部AI知识库（Windows，Git 仓库，main @ dc62848）。
第一步：调用 skill 工具加载 project-manager，按它的门禁（G0–G6）/目录/串行规则执行。本阶段只做 P0，不修缺陷、不部署。
第二步：只读核对现场（git log --oneline -6、git status --short、git tag），按顺序读：
  .claude/handoffs/_index.md
  .claude/handoffs/2026-11-04-p0-task-breakdown.md
  docs/superpowers/specs/2026-11-04-mktkb-observability-evaluation-design.md
  docs/superpowers/plans/2026-11-04-mktkb-observability-evaluation-p0.md
  需要细节再读 .claude/handoffs/prompts/p0-pm-handoff-20261104.md（长版交接）
第三步：回我不超过 10 行——现场核对结论 + P0 理解 + 待确认参数（1 开发 + 1 验收？PR？9 包粒度？），我答复后再派单；不要先开工。若我明确说「按默认派单」，核对完直接进 G1 派 T001。
硬约束：只写 .claude/handoffs/**；P0 零真实模型/OCR/embedding/rerank 调用、不读 .env、不改业务行为/API/schema、不新增生产依赖；不动 docs/evidence、var、账本/GO、fixtures、归档区；开发在 p0/obs-eval 分支逐包 commit，验收证据进 docs/reports/OBS-EVAL/P0；不杀外部服务；不打印凭据。
默认：1 开发助手（T001→T008）+ 1 独立验收助手（V1–V5 证伪）；每包一 commit；T009 通过后交我人工验收，不得自行进入修复阶段。
```

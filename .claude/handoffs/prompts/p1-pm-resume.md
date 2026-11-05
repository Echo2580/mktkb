角色：项目经理（PM），接续 MKTKB 项目 **P1**。工作目录 `D:\GPT项目\市场部AI知识库`；P0 已由主人通过（G6 收口），PR #1 仍 OPEN、未合并；P1 尚未立项开工。

第一步：调用 skill 加载 `project-manager`，按其 G0–G6 门禁 / 目录拓扑 / 串行规则 / §11 提速策略（A/C/D/E）执行；PM 只写 `.claude/handoffs/**`，不写交付物、不替开发写、不替验收判。

第二步：只读核对现场（`git log --oneline -10`、`git status --short`、`git branch --show-current`、`gh pr view 1`），按顺序读：
  `.claude/handoffs/2026-11-05-p0-closeout-handoff.md`
  `.claude/handoffs/_index.md`（遗留项 1–38）
  `.claude/handoffs/2026-11-04-p1-design.md`、`.claude/handoffs/2026-11-04-p1-task-breakdown.md`

第三步：**先过 P1 开工门，不猜**：
  - `P1-PRE-2`：预算划转 `P1-RETRIEVAL` 3.0 元（自 S2-DEV 划转、总上限仍 20）+ GO 改版需**主人签** `budget.json`/`S2-LIVE-GO.json`；PM 只出清单、不碰原件。
  - `P1-PRE-4`：D-3 兼容授权（允许错误码/文案取值变化、字段结构不变）需主人书面确认（T104/T106）。
  - `P1-PRE-3`：PM 自己复核 P0 遗留项。
  - 未签 GO 前：只做只读准备，**不得**派开发包、不得真实模型/embedding/rerank 调用。

第四步（签完后）：按拆解稿串行 T107 → T101 → T102 → T103 → T104 → T105 → T106 → T108 → T109 → T110 → T111 → T112 → T113 → T114 → T900；**一包一开发 subagent + 一包一全新上下文验收 subagent**（团队 8 席位已满，不用 teammate），每包 1 commit、证据进 `docs/reports/OBS-EVAL/P1/`、验收证据 `.../evidence/verify/T<NNN>/`；全部完成开 1 个 PR 交主人。

硬约束：除 T111（需 GO + 预算且只跑 retrieval_only）外零真实调用；不读 `.env`、不打印凭据；不改业务 API 字段结构、不改业务库/索引库 schema、不新增生产依赖；不动 `docs/evidence`、`var`、账本/GO、冻结 fixtures；不杀外部服务；不 commit 账本/GO。P0 的三项可选项（阈值/baseline/§7.2）在主人未指令前不要擅自执行，也不要合并 PR #1。

遇不确定（验收范围、口径、入库、预算、是否续跑）先问主人，不猜。

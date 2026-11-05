角色：开发助手。任务 T008a「CLI 与 P0 全流程 run」（P0 第 13 包）。全新上下文。
第一步：完整读 `.claude\handoffs\T008a-cli\handoff.md`，按其「输入 / 交付物 / §5 六条 / §7 边界」执行；基线 = T007 收口 commit（先 `git log --oneline -5` 与 `git status --short` 确认）。
要点：`evaluation/cli.py` + `tools/rag_eval.py` 薄包装；子命令 `dataset build|validate`、`run`、`gate [--calibrate]`、`baseline approve|list`、`diff`、`export`；退出码透传；**不得**有 `--allow-holdout-details`；不自动批阈值、不伪造 baseline。
全流程真实跑通：b0/badcase local + b0 replay 三件套 → gate（干净集；未审批阈值下允许 exit 3，须区分"硬门禁通过"与"质量 unknown"）→ calibrate 只出 proposal → 敏感注入临时 run 验证 exit 1 → `baseline approve` 缺参数/门禁未过必须拒绝。
未审批阈值时不得为演示 exit 0 改仓库配置（只能用 `%TEMP%` 测试配置）；运行产物只写 `var/eval/**` 或 `%TEMP%`，不入库。
不改既有 evaluation 模块/观测/业务代码；不新增依赖；零真实调用、不读 `.env`；TDD 先红后绿；`pytest backend/tests/evaluation` + 全量仅提交前 1 次（基线 = T007 全量 + 新增，0 failed/error）。
交付物只写 handoff §2；证据 ≤4 份、报告 ≤80 行；单 commit `p0/T008a eval cli`，不 push。
结束时写 `report.md`（五段，含命令序列逐条退出码），并给 ≤10 行摘要（commit sha、命令退出码、测试与全量、偏离/风险）。

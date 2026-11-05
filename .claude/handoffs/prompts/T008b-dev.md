角色：开发助手。任务 T008b「P0 七条验收测试 + p0-report」（P0 第 14 包）。全新上下文。
第一步：完整读 `.claude\handoffs\T008b-p0-acceptance\handoff.md`，按其「输入 / 交付物 / §5 六条 / 边界」执行；基线 = T008a 收口 commit（先 `git log --oneline -5` 与 `git status --short` 确认）。
要点：七条测试必须各自可失败（抽查变异）、golden 有来源与归一化清单且不循环自证；`p0-report.md` 逐条命令+结果+sha256 锚+未测边界+免责句原文；口径（b0 32 / badcase 10/13、1551→1586 等）不得美化。
真实 baseline/阈值审批属主人 T009 人工门：七条中的 (5) 用 `%TEMP%` 审批配置演示并在报告写明"真实 baseline 待审批"。
不改业务/观测/评测实现与既有断言；不新增依赖；零真实调用；不读 `.env`；无 `--allow-holdout-details`；运行产物只写 `%TEMP%`/`var/eval`，不入库。
交付物只写 handoff §2；证据 ≤4 份、报告 ≤80 行；TDD 先红后绿；`pytest backend/tests/evaluation` + 全量仅提交前 1 次（基线 = T008a 全量 + 新增）。
单 commit `p0/T008b p0 acceptance`，不 push，不动 `_index.md` 与其他包产物。
结束时写 `report.md`（五段），并给 ≤10 行摘要（commit sha、七条逐条结果、测试与全量、偏离/风险）。

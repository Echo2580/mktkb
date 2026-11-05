角色：开发助手。任务 T007「Baseline + Diff + 报告」（P0 第 12 包）。全新上下文。
第一步：完整读 `.claude\handoffs\T007-baseline-report\handoff.md`，按其「输入 / 交付物 / §5 六条 / 边界」执行；基线 = T006b 收口 commit（先 `git log --oneline -4` 与 `git status --short` 确认）。
要点：`baseline_id=sha256(dataset_version+pipeline_version+mode+scope+gate_version+corpus_sha256)[:12]`；`approve_baseline` 必须 `approver`+`reason` 且门禁 `exit_code==0`（未审批阈值→3 时拒绝）；无 `copy`/`rename`；跨版本仅 `compare_with=` 显式分析、不可放行；`diff_runs` 出 new/fixed/still-failing + 按 stratum 指标差；`render_html` 单文件内联 CSS 无 JS 无外链、硬门禁置顶。
真实 P0 baseline 本包**不生成**（`gate_v0_1.json` 仍 `unapproved`，T009 人工门审批后才建），只证明"通过可审批/未通过拒绝"的能力（fixture 审批配置）。
不改 gate/runner/scorer/dataset/观测内核/业务代码；不新增依赖；零真实调用；不读 `.env`。
交付物只写 handoff §2；证据 ≤4 份、报告 ≤80 行；TDD 先红后绿；`pytest backend/tests/evaluation` + 全量仅提交前 1 次（基线 = T006b 全量 + 本包新增，0 failed/error）。
结束时写 `report.md`（五段，自证带命令/`文件:行`），并给 ≤10 行摘要（commit sha、baseline id 样例、diff 摘要、html 自检、测试与全量、偏离/风险）。

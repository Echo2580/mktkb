角色：开发助手。任务 T006b「门禁质量层 + 校准 + 豁免」（P0 第 11 包）。全新上下文。
第一步：完整读 `.claude\handoffs\T006b-gate-quality\handoff.md`，按其「输入 / 交付物 / §5 六条验收标准 / 边界」执行；基线 = T006a R1 收口 commit（先 `git log --oneline -4` 与 `git status --short` 确认）。
要点：质量层按 stratum + 总体；`calibrate_gate` 只产出 `gate_proposal.json`，**不改写** `gate_v0_1.json`、不替主人批阈值（`status` 保持 `unapproved`）；未审批 → 质量 unknown → exit 3；exit 2 只由质量回退触发，硬门禁仍优先 1；质量 waiver 需 `reason`+`approver`，硬门禁不可豁免。
分母：按指标各自口径（检索=有 gold：badcase 10；拒答=适用样本；OCR/error 一律排除）；**不得复用 T006a 的 `hard_gate_min_sample`（evaluated_count：b0 32 / badcase 13）**。
不得把 T006a 的 exit=0 / not_applicable 当质量通过；不改硬门禁 8 项语义与 0/1/3/4；不实现 baseline/diff（T007）。
交付物只写到 handoff §2；证据 ≤4 份、报告 ≤80 行；TDD 先红后绿；零真实调用、不读 `.env`、不新增依赖。
结束时写同目录 `report.md`（五段，自证带命令或 `文件:行`），并给 ≤10 行交接摘要（commit sha、退出码矩阵、proposal 摘要、测试与全量结果、偏离/风险）。

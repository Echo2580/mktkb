# T006b 独立验收提示词（subagent 版，2026-11-05）

角色：独立验收者（全新上下文）。任务 T006b「门禁质量层 + 校准 + 豁免」，对象 commit `5a4c054`。
第一步：完整读 `.claude\handoffs\T006b-gate-quality\handoff.md`（§5 六条是唯一判定依据、§7 边界含分母分离裁决）与同目录 `report.md`（只当线索）。
第二步：亲自复跑 + 独立探针。提速策略 A/C：本包 1 次（`test_gate_quality.py`）+ 受影响目录 1 次（`backend/tests/evaluation`）+ 全量 1 次（基线 1506）；不重跑旧基线；串行。
重点亲测（自己构造 run/config，不复用交付测试 fixture）：
- §5.1 质量指标按 stratum + all、无综合分；summary 缺指标 → unknown 而非 0。
- §5.2 绝对阈值/`max_regression_pp`/`min_sample`：同 `pipeline_version` 才回退检测，跨版本 → unknown；分母按指标：检索 b0 32 / badcase 10，答案 32/13，拒答排除 `error`/`service_error`/`knowledge_changed`；**不得**使用 `hard_gate_min_sample`。
- §5.3 `calibrate_gate` 只出 `gate_proposal.json`（obs + 建议阈值 + run_id + config hash），**不写回** `gate_v0_1.json`；未审批 → 质量 unknown → exit 3。
- §5.4 退出码：0/1/2/3/4 各自可达；硬失败优先于质量（1 不被 2 覆盖）；`2` 只在质量回退。
- §5.5 waiver：`reason`+`approver` 必需；硬门禁 ID → 构造即报错；豁免只作用于质量失败、不改硬失败、不改 unknown。
- §5.6 配置 `status=unapproved`、所有阈值 null；测试 29/233/1506；提交边界 `git show --name-status 5a4c054` 只含 handoff §2 允许路径。
- **回归**：抽 2 项 T006a 硬门禁（如 `security_leak`、`trace_integrity`）确认仍 exit 1；`mode=live` 仍 4；未审批配置下硬失败仍 1（不是 3/2）。
- 变异探针（仓库外）：如让未审批阈值当通过、让 waiver 作用硬门禁、让 `max_regression_pp` 跨版本生效，对应探针必须翻红。
证据：`docs\reports\OBS-EVAL\P0\evidence\verify\T006b\`（≤3 份 + 1 探针，UTF-8 无 BOM、ASCII 文件名）；结论写 `.claude\handoffs\T006b-gate-quality\review.md`（≤120 行）。
不改交付物、不 commit、不 push、不读 `.env`、零真实调用；临时文件只进 `%TEMP%`；不覆盖 `evidence/T006b/`（开发证据）。
回复末尾 ≤10 行：总判定 + §5 各条 + 失败项 + 未覆盖 + 对 T007 的输入约束（baseline 审批可用性、阈值状态）。

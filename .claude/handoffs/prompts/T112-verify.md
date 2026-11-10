角色：独立验收者（全新上下文），不是开发者/PM。任务 **T112（门禁阈值校准与 P1 b0 live baseline）独立验收**。证伪导向。
模型：`wb / cn:deepseek-v4.1-flash / reasoning_effort=max`（review 首行注明）。
工作目录 `D:\GPT项目\市场部AI知识库`；分支 `p1/fix-retrieval`；**交付 = R0 commit `7f46121` + R1 commit（见 report R1 段/`git log --oneline -5`；PM 簿记 commit 只改 `.claude/handoffs/**`）**；工作树应 clean。
必读：`.claude\handoffs\T112-gate-baseline\handoff.md`（§0/§3/**§7 主人审批记录=阈值与 baseline 的事实源**）、同目录 `report.md`（只当线索，不当 PASS 证据）、`prompts/T112-dev-R1.md`、`T111-live-retrieval/handoff.md` §0、`docs/evaluation/gate_v0_2.json`、`backend/src/mktkb/evaluation/{gate,baseline,live,cli}.py`、设计 §8、P1 设计 §9.4–§9.5。
逐条独立复核并亲跑（PASS/FAIL/BLOCKED/NOT-RUN + 命令/`文件:行`；不引用 report 作 PASS 证据）：
1) **审批落盘与阈值一致**：`gate_v0_2.json` `status=approved`、审批元数据齐全；阈值必须与主人批准值**逐项一致**：`min_sample=8`、R/M/nDCG `absolute_min=0.855`、hard_filter `absolute_max=0.02`、empty_recall `absolute_max=0.145`、`max_regression_pp=2.0`；8 硬门禁不变；`suites` 含 regression；answer/refusal/runtime 指标仍为 null（仅检索层批准）。自己用 approved 配置对 R0 live run **重跑 gate，必须 exit 0**（质量 pass）；再用未审批副本验证 exit 3/unknown（不得把未审批当通过）。
2) **校准可复现**：对同一 live run 重复 `--calibrate` 两次，proposal 逐字节一致、不写回配置；proposal 值有来源（run_id/config_hash）。
3) **baseline 审批与身份**：`baseline approve` 已发生——核 `approval.json`（approver/reason、`baseline_id` 六要素、gate_config_hash、run_id）与 `baseline list` 显示 approved；缺 approver/reason 被拒（亲跑负例或核对 R0 测试）；`baseline_id` 六要素与 manifest 一致；跨版本 `--compare-with` 标 `explicit_cross_version` 只分析；release baseline 缺失 fail closed；**P0 baseline 未被 copy/改名/污染**。
4) **b0 live run 真实性与合规（只读核对，不重跑 live）**：run 目录 manifest 七要素/sha、40 行 CaseResult 版本字段、指标摘要（all/exact/text）、账本按 run_id 分类 embedding 39/rerank 31/chat 0、零重试、预检上限 vs 账本 +0.0090459 元（保守口径）、账本 505/1000、`provider_billed_cny=null`；`--allow-full-live` 守卫负例（默认关闭行为不变；仅 b0+40+冻结 sha 放行，其他拒绝）。
5) **回归/预算**：本包新测试 / `backend/tests/evaluation` / 全量（0 failed/0 error；内存<2GB 轮询；既有 flake 隔离复跑 1 次）；b0/badcase/regression local+gate 对 P0/T114 signature/retrieved 0 diff、hard `[]`；证据 ≤4、report ≤80（R1 叠加若超预算，核是否披露）、R0+R1 两个 dev commit（不 amend `7f46121`）、只改允许路径、无 skip/xfail/删断言/新依赖/真实 chat。
6) **范围诚实**：badcase/regression/holdout live 与 P0 跨版本比较 NOT-RUN 是否如实登记；不得声称未审批项通过；审批值不得与 handoff §7 不符。
写 `.claude\handoffs\T112-gate-baseline\review.md`（≤120 行，首行模型标注）+ 证据 `docs/reports/OBS-EVAL/P1/evidence/verify/T112/`（≤4 份）；不改交付物、不 commit/push/切分支；**不重跑 live、零真实调用**；回复 ≤10 行摘要。

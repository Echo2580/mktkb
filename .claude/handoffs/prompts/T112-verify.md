角色：独立验收者（全新上下文），不是开发者/PM。任务 **T112（门禁阈值校准与 P1 b0 live baseline）独立验收**。证伪导向。
模型：`wb / cn:deepseek-v4.1-flash / reasoning_effort=max`（review 首行注明）。
工作目录 `D:\GPT项目\市场部AI知识库`；分支 `p1/fix-retrieval`；交付 commit 以 `.claude/handoffs/T112-gate-baseline/report.md` 与 `git log -1`（排除 PM 簿记 commit）为准；工作树应 clean。
必读：`.claude\handoffs\T112-gate-baseline\handoff.md`（§0/§3）、同目录 `report.md`（只当线索，不当 PASS 证据）、`T111-live-retrieval/handoff.md` §0、`docs/evaluation/gate_v0_2.json`、`backend/src/mktkb/evaluation/{gate,baseline,live,cli}.py`、`docs/superpowers/specs/2026-11-04-mktkb-observability-evaluation-design.md` §8、`.claude\handoffs\2026-11-04-p1-design.md` §9.4–§9.5。
逐条独立复核并亲跑（PASS/FAIL/BLOCKED/NOT-RUN + 命令/`文件:行`；不引用 report 作 PASS 证据）：
1) `gate_v0_2.json` 可加载/`status=unapproved`/8 硬门禁不变/检索 5 指标 + `min_sample`/`max_regression_pp`/`regression` suite；未审批质量结果 = unknown/exit 3（自己跑 gate 验证，不得当通过）。
2) 校准可复现：对同一 live run 重复 `--calibrate` 两次，proposal 逐字节一致且不写回配置；proposal 值有来源（run_id/config_hash）。
3) baseline 机制：`baseline approve` 缺 approver/reason 被拒（亲跑负例）；`baseline_id` 六要素绑定；跨版本 `--compare-with` 标 `explicit_cross_version` 且不放行；release baseline 缺失 fail closed。
4) b0 live run 真实性与合规（只读核对，**不重跑 live**）：run 目录 manifest 六要素、40 行 CaseResult 版本字段、指标摘要、账本按 run_id 分类 embedding/rerank/chat=0、零重试、成本预检 vs 账本保守口径；`--allow-full-live` 守卫负例（fake 测试或只读代码路径核对：默认关闭、b0+40+sha 才放行）。
5) 全量授权守卫与 pilot 语义：原 pilot ≤10 测试仍全绿；开关默认行为不变。
6) 回归/预算：本包新测试 / `backend/tests/evaluation` / 全量（0 failed/0 error；内存<2GB 轮询；既有 flake 隔离复跑）；b0/badcase/regression local+gate 对 P0 `case_diffs=0`、hard `[]`；P0 baseline 不混用；证据 ≤4、report ≤80、单 commit、只改允许路径、无 skip/xfail/删断言/新依赖/真实 chat。
7) 范围诚实：badcase/regression/holdout live NOT-RUN 是否如实登记；未审批不得声称通过。
写 `.claude\handoffs\T112-gate-baseline\review.md`（≤120 行，首行模型标注）+ 证据 `docs/reports/OBS-EVAL/P1/evidence/verify/T112/`（≤4 份）；不改交付物、不 commit/push/切分支；**不重跑 live**（≤0 次真实调用）；回复 ≤10 行摘要。

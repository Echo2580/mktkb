# T008a 独立验收提示词（subagent 版，2026-11-05）

角色：独立验收者（全新上下文）。任务 T008a「CLI 与 P0 全流程 run」，对象 `f2c0209`。
读：`.claude\handoffs\T008a-cli\handoff.md` §5 六条 + §7（T007 约束 6 条）；`report.md` 只当线索。
重点亲测（自己跑 CLI）：全部子命令可达、未知参数非 0、无 `--allow-holdout-details`；退出码透传（默认 gate=3 / `%TEMP%` 审批配置=0 / 敏感注入=1 / live=4 或标 NOT-RUN）；`baseline approve` 缺参数拒绝、自称 exit 0 的 gate JSON 被现场重算拒绝且不落 `approval.json`；无 baseline 时 `diff` fail closed、未审批 baseline 的 `release_allowed=False`；`export` md/html UTF-8 无 BOM、单文件无 `<script`/外链、不含"质量通过"；`gate_v0_1.json` 未改；提交边界 8 文件。
测试：`test_cli.py` + `backend/tests/evaluation` + 全量 1 次（基线 1586）；串行、不并发。
证据：`docs\reports\OBS-EVAL\P0\evidence\verify\T008a\`（≤3 份）；结论 `.claude\handoffs\T008a-cli\review.md`（≤120 行）。
不改交付物、不 commit/push、不读 `.env`、零真实调用；临时 `%TEMP%`。
回复 ≤10 行：总判定 + §5 各条 + 失败项 + 未覆盖 + T008b 约束。

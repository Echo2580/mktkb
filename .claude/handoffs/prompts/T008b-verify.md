# T008b 独立验收提示词（subagent 版，2026-11-05）

角色：独立验收者（全新上下文）。任务 T008b「P0 七条验收测试 + p0-report」，对象 `2f7b174`。
读：`.claude\handoffs\T008b-p0-acceptance\handoff.md` §5 六条 + §7（含 T008a 约束）；`report.md` 只当线索。
重点亲测：
- 七条测试逐条存在且能失败：抽查 2 条做仓库外变异（如去掉 `X-Trace-ID`、禁用 `security_leak` 上报），必须红；变异后还原、确认仓库无改动。
- golden 来源与归一化：核对测试只读、不写回；归一化字段清单完整（UUID/时间戳/短码）；连续两次采集一致的声明可否复现（不能复现则记 LOW，不判 FAIL）。
- p0-report 与实际一致：默认 gate=3/`thresholds_unapproved`；真实 baseline 待 T009；`live→4` 写 NOT-RUN/GAP（不得声称端到端）；放行看 `release_allowed/blocked`；无"质量通过"字样；数字（b0 40/32、badcase 13、1593 基线）与实测一致。
- 提交边界：`git show --name-status 2f7b174` 只含 handoff §2 允许路径（9 文件）；`conftest.py` 只追加（不得改既有行）；无业务/观测/评测实现改动。
- 测试：`test_p0_acceptance.py` + `backend/tests/evaluation` + 全量 1 次（基线 1593）。
证据：`docs\reports\OBS-EVAL\P0\evidence\verify\T008b\`（≤3 份）；结论 `.claude\handoffs\T008b-p0-acceptance\review.md`（≤120 行）。
不改交付物、不 commit/push、不读 `.env`、零真实调用；临时 `%TEMP%`；串行。
回复 ≤10 行：总判定 + §5 各条 + 失败项 + 未覆盖 + 对 T009 的输入（p0-report 可引用性、NOT-RUN 清单）。

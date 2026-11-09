角色：独立验收者（全新上下文），不是开发者/PM。任务 **T114（监控 API 权限/负例/文档）独立验收**。证伪导向。
模型：`wb / cn:deepseek-v4.1-flash / reasoning_effort=max`（review 首行注明）。
工作目录 `D:\GPT项目\市场部AI知识库`；分支 `p1/fix-retrieval`；交付 commit 以 `git log -1`（排除 PM 簿记 commit：`.claude/handoffs/**` 之外的最后一个 dev commit）为准，工作树应 clean。
必读：`.claude\handoffs\T114-observability-auth-docs\handoff.md`（§0/§3）、同目录 `report.md`（只当线索，不当 PASS 证据）、`backend/src/mktkb/observability/routes.py`、`docs/接口与数据契约.md` 新增节。
逐条独立复核并亲跑（PASS/FAIL/BLOCKED/NOT-RUN + 命令/`文件:行`；不引用 report 作 PASS 证据）：
1) 权限矩阵：4 端点 × 未登录 401（`AUTH_REQUIRED`）/ employee 403（`ROLE_REQUIRED`、required_role=admin）/ admin 200；错误顺序不泄露存在性（未登录/employee 下无 404 语义）。
2) 负例：admin 下不存在 trace/run 404；非法 window/trace/run/request id 4xx 且 code 正确；路径穿越被拒；未知 request 200 空列表（既有语义，文档是否写明）；trace 关闭 4 端点 200 + `degraded_reason`。
3) 时间窗边界：`0h`/`-1h`/`abc`/`24`/`1.5h`/`24D`/`1H`/` 24h` → 422；`1h`/`24h`/`999999h` → 200 不 500；分页 NOT-APPLICABLE 是否有说明（不得虚构分页）。
4) 不泄露：401/403/404/422 响应键白名单；成功响应白名单；构造秘密题干/答案 fixture 不出现在任何响应；Holdout 仅聚合。
5) 文档/OpenAPI：`docs/接口与数据契约.md` 新增节与实现一致（路径/参数/字段/错误码可对照）；OpenAPI 快照含 4 路径、均 get、声明 401/403；声明只读/降级/不泄露/无分页。
6) 回归/预算：本包新测试 / `backend/tests/observability` / 全量（0 failed/0 error；内存<2GB 轮询）；b0/badcase local+gate 对 P0（`case_diffs=0`、hard `[]`）；regression 不变；无 skip/xfail/删断言/新依赖；只改允许路径；report ≤80、证据 ≤4、单 dev commit；零真实调用/未读 `.env`/Holdout。
写 `.claude\handoffs\T114-observability-auth-docs\review.md`（≤120 行，首行模型标注）+ 证据 `docs/reports/OBS-EVAL/P1/evidence/verify/T114/`（≤4 份）；不改交付物、不 commit/push/切分支；回复 ≤10 行摘要。

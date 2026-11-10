角色：独立验收者（全新上下文），不是开发者/PM。任务 **T113（监控 API，只读聚合）独立验收**。证伪导向。
模型：`wb / cn:deepseek-v4.1-flash / reasoning_effort=max`（review 首行注明）。
工作目录 `D:\GPT项目\市场部AI知识库`；分支 `p1/fix-retrieval`；交付 commit 见 `git log -1`；工作树应 clean。
必读：`.claude\handoffs\T113-observability-api\handoff.md`（§0/§3）、同目录 report（只当线索）、`2026-11-04-p1-design.md` §6。
逐条独立复核并亲跑（PASS/FAIL/BLOCKED/NOT-RUN + 命令/`文件:行`；不引用 report 作 PASS 证据）：
1) 4 端点 admin 200 且结构完整（traces/requests/metrics/runs）；employee 403；未登录 401（可与 T114 分工，但至少核 admin/403）。
2) 只读：路由仅 GET；请求前后 trace 库/业务库 mtime/hash 不变（或断言无写调用）；无写端点。
3) 无原文：响应只含 hash/计数/长度/时长/成本/状态；构造含 `question_hash/question_chars` 的 trace 后核响应不含题干/答案正文字段；`*_json` 已裁剪为聚合。
4) Holdout 不可达：构造 `holdout_details=true` 的 run（或使用 T108 聚合 run）→ runs 只聚合、无逐题；其他端点不能间接取到。
5) trace 关闭降级：默认 `trace_enabled=false` 下 200 + `degraded_reason`；不 500；runs 缺失 404；非法 window/run_id 4xx；路径穿越被拒。
6) OpenAPI：`app.openapi()` 含 4 路径与 admin 安全声明；导出 JSON 证据。
7) 回归/预算：本包测试 / `backend/tests/observability` / 全量（0 failed/0 error；内存<2GB 轮询）；b0/badcase local+gate 对 P0（`case_diffs=0`、hard `[]`）；regression 不变；无 skip/xfail/删断言/新依赖；只改允许路径；report ≤80、证据 ≤4、单 dev commit；零真实调用/未读 `.env`/Holdout。
写 `.claude\handoffs\T113-observability-api\review.md`（≤120 行，首行模型标注）+ 证据 `verify/T113/`（≤4 份）；不改交付物、不 commit/push/切分支；回复 ≤10 行摘要。

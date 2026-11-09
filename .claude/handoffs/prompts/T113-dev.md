角色：开发助手。任务 **T113（监控 API，只读聚合）**。交接单：`.claude\handoffs\T113-observability-api\handoff.md`（本消息与之一致，细节以文件为准）。
模型：`wb / cn:deepseek-v4.1-flash / reasoning_effort=max`（report 首行注明）。
工作目录 `D:\GPT项目\市场部AI知识库`；分支 `p1/fix-retrieval`（T100–T107/T101–T106/T108/T109/T110/T111 已收口；T112 暂缓）；开工前 `git status --short` clean。

必读：`handoff.md`（§0 PM 口径/§2 交付物/§3 验收/§5 坑）、`2026-11-04-p1-design.md` §6（:96-110）、`backend/src/mktkb/main.py`（create_app/state/路由注册）、`observability/{store,contracts,tracer}.py`、`auth/routes.py`（`require_role("admin")`）、`conversations/routes.py`（路由风格）。
实现（只改允许路径）：
- 新增 `backend/src/mktkb/observability/routes.py`：`GET /api/v1/observability/traces/{trace_id}`、`/requests/{request_id}/traces`、`/metrics?window=24h`、`/runs/{run_id}`；admin 依赖；trace 关闭返回 200 空聚合+`degraded_reason`；窗口解析（非法 422）；trace/run id 校验防穿越；runs 读 `<data_dir>/eval/runs/<run_id>/{run_manifest.json,summary.json,gate.json}` 只读聚合；**只返回哈希/计数/长度/时长/成本/状态**，无问题/答案原文；holdout run 只聚合不逐题。
- `backend/src/mktkb/main.py`：注册 router（在 `/api/v1` 下）。
- `backend/tests/`：admin 200 ×4、employee 403、trace 关闭降级、404、非法参数、聚合正确（造 trace 后 metrics 计数/P50/P95/tokens/cost/degraded）、无原文字段、holdout 仅聚合、OpenAPI 含 4 路径、只读（无写路由/无写调用）。
- 若指标聚合确需查询：只允许在 `store.py` 加**只读聚合方法**（不改 schema/写入），report 单列；否则不加。
- 禁止：业务路由/API/schema/conversations/intent/账本/GO/`.env`/Holdout/新依赖/真实调用/push/amend/skip/xfail/删断言。
必跑：本包测试 / `backend/tests/observability` / 全量（0 failed/0 error；内存<2GB 轮询；flake 处理）；b0+badcase local+gate 对 P0（`case_diffs=0`、hard `[]`）；regression 状态不变；OpenAPI 导出证据。pytest 前 `$env:MKTKB_PROJECT_TOTAL_LIMIT_CNY="20.0"`；`.\.venv\Scripts\python.exe -B -m pytest ...`；同一时间只跑一套。
交付：1 commit `p1/T113 observability read-only API`（不 push/不 amend）；report 五段 ≤80 行；证据 4 份；回复 ≤10 行摘要（commit、4 端点证据、测试数字、偏离、风险）。

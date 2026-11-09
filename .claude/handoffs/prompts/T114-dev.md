角色：开发助手。任务 **T114（监控 API 权限/负例/文档）**。
模型：`wb / cn:deepseek-v4.1-flash / reasoning_effort=max`（report 首行注明）。
工作目录 `D:\GPT项目\市场部AI知识库`；分支 `p1/fix-retrieval`。
第一步：完整读 `.claude\handoffs\T114-observability-auth-docs\handoff.md`，按其中「§0 PM 口径 / §2 交付物 / §3 验收标准 / §4 必跑 / §5 坑」执行；再读 `.claude\handoffs\T113-observability-api\handoff.md` §0 与 `backend/src/mktkb/observability/routes.py`（现行实现）。
只写 handoff §2 允许的路径；中间草稿放 `.claude\handoffs\_scratch\T114\`，不要散落项目根。
硬约束：不改业务 API/字段结构/`conversations/`/`intent.py`/schema/账本/GO/`.env`/Holdout/`docs/evidence/**`/`var/**`；不改 T113 `test_routes.py`；零真实调用；不 push/amend；无 skip/xfail/删断言/新依赖。
结束时写同目录 `report.md`（五段齐全、≤80 行，自证带命令或 `文件:行`），提交 1 个 commit（不 push/amend），回复末尾给 ≤10 行交接摘要，我转给项目经理。

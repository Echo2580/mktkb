角色：开发助手。任务 T103（MKTKB 项目 P1 第 5 包：D4 记录路回落语义检索，ERR-04）。
第一步：完整读 `.claude\handoffs\T103-record-fallback\handoff.md`，严格按「输入 / 交付物 / 验收标准 / 边界」执行。
核心：修 `conversations/service.py` 的"记录过多→零候选无解澄清"死路——overshoot 时回落语义/正文检索，澄清须含真实原因/命中量/缩小方式，空候选要诚实；回落路径写 trace 降级数据字段（不改 schema）；最小改 `frontend/.../MessageCard.tsx` 让"本轮零候选"不再显示"历史未保存"；收口 RG004 使其 local PASS；不得动 API 字段结构/其他包文件/b0/badcase。
证据 ≤4 份放 `docs\reports\OBS-EVAL\P1\evidence\T103\`；写 `.claude/handoffs/T103-record-fallback/report.md`（五段、≤80 行、自证带命令/路径）；1 个 commit（消息 `p1/T103 record-path fallback + honest clarification`）；回复末尾 ≤10 行交接摘要（含 commit sha、改动文件、测试结果、b0/badcase/regression 前后对照、前端 typecheck 结果）。
测试：本包 + `backend/tests/integration` + `backend/tests/unit` + 全量（先 `$env:MKTKB_PROJECT_TOTAL_LIMIT_CNY="20.0"`；内存 2.44GB；全量前看 FreePhysicalMemory；既有 flake 隔离复跑记录）；前端在 `frontend/` 跑 `npm run typecheck`（可用则 `npm run build`）。
禁止：改业务 API 字段结构/响应字段、其他后端模块、b0/badcase、gate_v0_1、其他包文件；skip/xfail/删断言/放宽；真实模型调用；读 `.env`/Holdout；切分支；push；新增生产依赖。
`report.md` 首行注明：`wb / cn:deepseek-v4.1-flash / reasoning_effort=max`。

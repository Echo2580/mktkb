角色：开发助手。任务 **T106（D3 文案统一，ERR-05）**。
模型：`wb / cn:deepseek-v4.1-flash / reasoning_effort=max`（report 首行注明）。
工作目录 `D:\GPT项目\市场部AI知识库`；分支 `p1/fix-retrieval`（T100–T105 已 G6）。

第一步：完整读 `.claude\handoffs\T106-copy-unification\handoff.md`，按其中 §3 输入 / §4 交付物 / §5 边界 / §6 验收标准 / §8 坑 执行；先 `git status --short` 确认工作树 clean。
- 交付物只写 handoff 指定路径；中间草稿放 `.claude\handoffs\_scratch\T106\`（gitignored），不得散落到项目根/交付物目录。
- 零真实模型/embedding/rerank/OCR；不读 `.env`/Holdout；不改 API 字段结构、`ResultKind`/`error_code` 语义、`intent.py`/意图词表、b0/badcase 数据、gate 配置、账本/GO；不 push/不 amend 历史；无 skip/xfail/删断言。
- 前端至少 `npm run typecheck` + `npm run build` 必须实际跑；e2e 若环境不允许须记录实际尝试并写 NOT-RUN（不得假装通过）。
- 结束时写同目录 `report.md`（五段 ≤80 行，自证带命令或 `文件:行`），并回复 ≤10 行交接摘要（commit、验收自证、测试数字、偏离、风险）。

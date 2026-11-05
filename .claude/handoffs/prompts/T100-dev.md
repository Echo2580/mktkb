角色：开发助手。任务 T100（MKTKB 项目 P1 前置小包）。
第一步：完整读 `.claude\handoffs\T100-baseline-config\handoff.md`，按其"输入 / 交付物 / 验收标准 / 边界"执行。
只改 handoff 允许的文件；证据放 `docs\reports\OBS-EVAL\P1\evidence\T100\`；中间草稿放 `backend\.pytest-tmp\`，不要散落到项目根或 `_scratch`。
结束时写同目录 `report.md`（五段齐全，自证带命令/路径，≤80 行），按 handoff 要求做 **1 个 commit**，并在回复末尾给 ≤10 行交接摘要（含 commit sha）。
禁止：真实模型/embedding/rerank/OCR 调用；读 `.env`；改 budget/GO/账本/业务代码/其他测试；切换分支；push。

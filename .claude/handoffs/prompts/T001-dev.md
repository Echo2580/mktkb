角色：开发助手。任务 T001（P0 第 1 包）。工作目录 `D:\GPT项目\市场部AI知识库`，全新上下文，不要假设看过任何对话。

第一步：完整读 `.claude\handoffs\T001-obs-contracts\handoff.md`，按其中「交付物 / 输入 / 允许与禁止 / 验收标准 / 必须实际运行的检查 / 提交」执行；细节全在该文件，不要扩大范围。

只写 handoff §2 列的路径；中间草稿放 `.claude\handoffs\_scratch\T001\`（勿散落）；报告写 `.claude\handoffs\T001-obs-contracts\report.md`（五段齐全，自证带命令或 文件:行）；证据原文放 `docs\reports\OBS-EVAL\P0\evidence\T001\`。

硬约束：零真实模型/OCR/embedding/rerank 调用、不读 `.env`、不新增依赖、不改业务代码、不 push、不打印凭据；测试统一 `$env:MKTKB_PROJECT_TOTAL_LIMIT_CNY = "20.0"` 后用 `.\.venv\Scripts\python.exe -B` 跑。

结束时回复末尾给 ≤10 行交接摘要（交付物、自证、偏离、风险），我转给项目经理。

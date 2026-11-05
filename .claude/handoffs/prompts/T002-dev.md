角色：开发助手。任务 T002（P0 第 2 包，SQLite Trace 仓储）。工作目录 `D:\GPT项目\市场部AI知识库`，Windows/PowerShell，全新上下文。

第一步：完整读 `.claude\handoffs\T002-trace-store\handoff.md`，按「交付物 / 输入 / 允许与禁止 / 验收标准 / 必须实际运行的检查 / 提交」执行；细节全在该文件，不要扩大范围。T001 已通过独立验收（`p0/obs-eval` @ `7b02f40`），其 `contracts.py` / `versioning.py` 只读。

只写 handoff §2 列的路径；中间草稿放 `.claude\handoffs\_scratch\T002\`；报告写 `.claude\handoffs\T002-trace-store\report.md`（五段齐全，自证带命令或 文件:行）；证据原文放 `docs\reports\OBS-EVAL\P0\evidence\T002\`。

硬约束：stdlib `sqlite3` 不新增依赖；不接业务代码、不改 T001 契约文件与既有测试；测试只写 tmp_path；零真实模型/OCR/embedding/rerank 调用、不读 `.env`、不打印凭据；不碰 `docs/evidence`/`var`/`fixtures`/账本/GO/归档区；不 push；`git add` 只加本包交付物（PM 的未跟踪文件不要 commit）。

测试统一先设 `$env:MKTKB_PROJECT_TOTAL_LIMIT_CNY = "20.0"`，Python 用 `.\.venv\Scripts\python.exe -B`；TDD：先写失败测试 → 确认失败 → 实现 → 确认通过 → 全量回归 → 证据 → commit（`p0/T002 sqlite trace repository`）。

结束时回复末尾给 ≤10 行交接摘要：交付物、§5 八条自证要点、实际运行结果（含 commit sha / stat）、偏离、风险。不要写 review 文件。

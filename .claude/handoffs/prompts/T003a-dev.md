角色：开发助手。任务 T003a（P0 第 3 包，tracer 内核）。工作目录 `D:\GPT项目\市场部AI知识库`，Windows/PowerShell，全新上下文。

第一步：完整读 `.claude\handoffs\T003a-tracer\handoff.md`，按「交付物 / 输入 / 允许与禁止 / 验收标准 / 必须实际运行的检查 / 提交」执行；细节全在该文件，不要扩大范围。T001（契约）与 T002（SQLite 仓储）已通过独立验收，`contracts.py`/`versioning.py`/`store.py` 只读（仅允许 handoff §2 的追加）。

开工：`git branch --show-current` 应为 `p0/obs-eval`，HEAD 应为 `2ac976f`；工作树里的 PM 未跟踪文件不要动、不要 commit。先 `$env:MKTKB_PROJECT_TOTAL_LIMIT_CNY="20.0"`，Python 用 `.\.venv\Scripts\python.exe -B`；TDD：先写失败测试 → RED → 实现 → GREEN → 全量回归 → 证据 → commit `p0/T003a tracer core`。

硬约束：不接业务代码（`main.py`/`config.py`/`qa/`/`rag/`/`conversations/` 一律只读）；不改 store/既有测试；不新增依赖；零真实调用、不读 `.env`、不打印凭据；测试只写 tmp_path；不碰 `docs/evidence`/`var`/`fixtures`/账本/GO/归档区；不 push。

交付物只写 handoff §2 的路径；证据 `docs\reports\OBS-EVAL\P0\evidence\T003a\`；五段报告 `.claude\handoffs\T003a-tracer\report.md`；草稿 `.claude\handoffs\_scratch\T003a\`。

结束时回复末尾给 ≤10 行交接摘要：交付物、§5 八条自证要点（命令或 文件:行）、实际运行结果（commit sha / stat / 全量通过数）、偏离、风险。不要写 review 文件。

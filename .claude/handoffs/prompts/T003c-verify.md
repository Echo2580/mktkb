角色：独立验收者（不是开发者，也不是项目经理）。任务 T003c（RAG 路径 Span 埋点，最高风险包）。全新上下文。

你的任务是证伪，不是帮它说话：只认自己亲自复跑的结果，**不引用开发方 report.md 作为 PASS 证据**。

第一步：读 `.claude\handoffs\T003c-rag-spans\handoff.md`（验收标准 §5、必跑命令 §6）；再读同目录 `report.md`，只当线索。

逐条独立复核：亲自复跑 handoff §6 全部命令（分支 `p0/obs-eval`，`$env:MKTKB_PROJECT_TOTAL_LIMIT_CNY="20.0"`，`.\.venv\Scripts\python.exe -B`），每条给 `PASS / FAIL / BLOCKED / NOT-RUN` + 证据。重点亲测：
- §5.1 **无 trace 时零行为变化**：对固定问题在未开启 trace 下运行 `RagIndex.ask`，与改动前基线行为一致（可对同一测试在 `git show d41d19f:...` 的兄弟副本外做对照，仓库内不得改动）；既有 rag/observability/integration/acceptance 测试全绿。
- §5.2 有 trace 时 answer 路径 Span 集合与 `required_spans(RAG, ANSWER)` 一致，且 `recall` 父子结构正确、未执行通道无 Span；
- §5.3 条件 Span：vector/rerank 开与关两种设置下 Span 出现与否正确，`conditional_required_spans` 判定一致；
- §5.4 早退路径（clarification/no_answer/conflict 等）用 `validate_required_spans` 校验通过、无伪造 answer Span；
- §5.5 attributes 是 canonical JSON、只含计数/稳定引用/布尔（**不得含问题/答案原文**；可用真实问题文本搜索 trace 记录验证）；
- §5.6 异常路径 span status=error 且异常照旧上抛；
- §5.7 全量 `backend/tests` 相对 1196 基线无新增失败（0 failed / 0 error）。
- 提交边界：`git show --name-only HEAD` 只能含 handoff §2 允许路径；不得出现 `qa/`/`conversations/`/`main.py`/`config.py`/观测内核文件/既有测试/pyproject/docs/evidence/var/fixtures 改动；越界即 FAIL。
- 测试非空转：抽查断言；可做仓库外变异探针（如去掉 fuse Span、让 vector Span 恒出现、把原文写进 attributes），仓库内不得改动。
- 硬约束：无新增依赖、零真实调用、不读 `.env`、API 字段结构未变、`RagAnswer`/`RetrievalResult` 结构未变。

产出：写 `.claude\handoffs\T003c-rag-spans\review.md`（逐条 PASS/FAIL/BLOCKED/NOT-RUN + 命令与 文件:行、发现问题、未覆盖项）；复跑证据存 `docs\reports\OBS-EVAL\P0\evidence\verify\T003c\`。

你不修改任何交付物、不改代码、不 commit、不 push、不改 `_index.md`。回复末尾给 ≤10 行结论摘要。

角色：独立验收者（不是开发者，也不是项目经理）。任务 T002（SQLite Trace 仓储）。全新上下文。

你的任务是证伪，不是帮它说话：只认自己亲自复跑的结果，**不引用开发方 report.md 作为 PASS 证据**。

第一步：读 `.claude\handoffs\T002-trace-store\handoff.md`（验收标准 §5、必跑命令 §6）；再读同目录 `report.md`，只当线索、不当证据。

逐条独立复核：亲自复跑 handoff §6 的全部命令（分支 `p0/obs-eval`，`$env:MKTKB_PROJECT_TOTAL_LIMIT_CNY="20.0"`，`.\.venv\Scripts\python.exe -B`），每条给 `PASS / FAIL / BLOCKED / NOT-RUN` + 证据（命令 + `文件:行` 或输出摘录）。重点亲测：
- §5.1 往返（含中文）与 spans 匹配；§5.2 不可写场景下 `write_best_effort` 真不抛、`write` 真抛 `TraceWriteError`；
- §5.3 幂等建表、`schema_meta` 版本值、`PRAGMA journal_mode=WAL` 实测；
- §5.4 多 attempt 全量返回；§5.5 export JSONL 行数/可解析/since 过滤；§5.6 purge 两种口径各自生效；
- §5.7 抽查 SQL 是否参数化、是否有字符串拼接值；§5.8 全量 `backend/tests` 是否相对 1086 passed 无新增失败（0 failed/0 error）。
- 提交边界：`git show --name-only HEAD` 只能含 handoff §2 交付物，不得出现业务代码/契约文件/既有测试/`pyproject`/`docs/evidence`/`var`/`fixtures` 改动；发现越界即 FAIL。
- 测试是否空转：抽查关键断言是否真校验行为（必要时做仓库外变异探针，如 break purge 逻辑后看测试是否失败），仓库内不得改动。

写 `.claude\handoffs\T002-trace-store\review.md`（逐条 PASS/FAIL/BLOCKED/NOT-RUN + 证据、发现的问题、未覆盖项）；复跑证据原文放 `docs\reports\OBS-EVAL\P0\evidence\verify\T002\`。

你不修改任何交付物、不改代码、不 commit、不 push、不改 `_index.md`。回复末尾给 ≤10 行结论摘要（逐条结论、不通过项、未覆盖、建议返工范围）。

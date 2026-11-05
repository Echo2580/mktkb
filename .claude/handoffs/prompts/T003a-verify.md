角色：独立验收者（不是开发者，也不是项目经理）。任务 T003a（tracer 内核）。全新上下文。

你的任务是证伪，不是帮它说话：只认自己亲自复跑的结果，**不引用开发方 report.md 作为 PASS 证据**。

第一步：读 `.claude\handoffs\T003a-tracer\handoff.md`（验收标准 §5、必跑命令 §6）；再读同目录 `report.md`，只当线索。

逐条独立复核：亲自复跑 handoff §6 的全部命令（分支 `p0/obs-eval`，`$env:MKTKB_PROJECT_TOTAL_LIMIT_CNY="20.0"`，`.\.venv\Scripts\python.exe -B`），每条给 `PASS / FAIL / BLOCKED / NOT-RUN` + 证据。重点亲测：
- §5.1 contextvar 隔离（两线程/嵌套 trace 不串；无 trace 时 `current_trace()` 为 None）；
- §5.2/§5.3 trace_id、父子 Span、duration/status/attributes、异常路径 status=error；
- §5.4 未设 outcome/path → `status=incomplete` 且不抛；
- §5.5 注入 repo 后 finish 走 `write_best_effort`、写入失败不抛、未开启时 no-op 且不建 DB；
- §5.6 `off`/`hash` 内容模式真正生效（不写原文；HMAC 空 key 行为与 `versioning.hash_question` 一致）；
- §5.7 `validate_required_spans` 的 8 行表与条件 Span、clarification 不误判；
- §5.8 全量 `backend/tests` 相对 1110 基线无新增失败（0 failed / 0 error）。
- 提交边界：`git show --name-only HEAD` 只能含 handoff §2 交付物（不得出现业务代码、store.py、既有测试、`pyproject`、`docs/evidence`、`var`、`fixtures` 改动）；越界即 FAIL。
- 测试非空转：抽查断言是否真校验行为，必要时做仓库外变异探针（如让 finish 不写库、破坏 parent_span_id、弱化 validation），仓库内不得改动。
- 硬约束：无新增依赖、零真实调用、不读 `.env`。

产出：写 `.claude\handoffs\T003a-tracer\review.md`（逐条 PASS/FAIL/BLOCKED/NOT-RUN + 命令与 文件:行、发现问题、未覆盖项）；复跑证据存 `docs\reports\OBS-EVAL\P0\evidence\verify\T003a\`。

你不修改任何交付物、不改代码、不 commit、不 push、不改 `_index.md`。回复末尾给 ≤10 行结论摘要。

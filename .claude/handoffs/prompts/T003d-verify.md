角色：独立验收者（不是开发者，也不是项目经理）。任务 T003d（QA/legacy 路径 Span 与 outcome 绑定）。全新上下文。

你的任务是证伪，不是帮它说话：只认自己亲自复跑的结果，**不引用开发方 report.md 作为 PASS 证据**。

第一步：读 `.claude\handoffs\T003d-paths\handoff.md`（验收标准 §5、必跑命令 §6）；再读同目录 `report.md`，只当线索。

逐条独立复核：亲自复跑 handoff §6 全部命令（分支 `p0/obs-eval`，`$env:MKTKB_PROJECT_TOTAL_LIMIT_CNY="20.0"`，`.\.venv\Scripts\python.exe -B`），每条给 `PASS / FAIL / BLOCKED / NOT-RUN` + 证据。重点亲测：
- §5.1 RAG 产品路径 E2E：HTTP POST → X-Trace-ID → 库中 trace 的 request_id/http_request_id/path=rag/outcome/status 与 Span 集合（required_spans + validate 返回空）；
- §5.2 legacy 路径：path 取值、Span 表、query_expansion 仅触发时出现；
- §5.3 多 outcome（clarification/no_answer/conflict/error）与 reason/error_code；
- §5.4 trace 开/关 body 归一化一致 + 既有 integration 全绿 + 全量相对 T003c 基线无新增失败；
- §5.5 隐私（hash/HMAC 无密钥泄漏、无原文）；
- §5.6 index_sync 仅在真同步时出现；
- §5.7 重放 status=replayed 且历史不覆盖；
- §5.8 硬约束与提交边界（`git show --name-only HEAD` 只含 qa/service.py、conversations/service.py、新测试/证据/报告；不得出现 rag/**、main.py、config.py、观测内核、既有测试、pyproject、docs/evidence、var、fixtures）。
- 测试非空转：抽查断言；可做仓库外变异探针（不设 outcome、legacy 不设 path、query_expansion 恒出现、写原文），仓库内不得改动。

产出：写 `.claude\handoffs\T003d-paths\review.md`（逐条 PASS/FAIL/BLOCKED/NOT-RUN + 命令与 文件:行、发现问题、未覆盖项）；复跑证据存 `docs\reports\OBS-EVAL\P0\evidence\verify\T003d\`。

你不修改任何交付物、不改代码、不 commit、不 push、不改 `_index.md`。回复末尾给 ≤10 行结论摘要。

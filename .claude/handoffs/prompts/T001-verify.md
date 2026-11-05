角色：独立验收者（不是开发者，也不是项目经理）。任务 T001。全新上下文。

你的任务是证伪，不是帮它说话：只认自己亲自复跑的结果，**不引用开发方 report.md 作为 PASS 证据**。

第一步：读 `.claude\handoffs\T001-obs-contracts\handoff.md`（验收标准 §5 与必跑命令 §6）；再读同目录 `report.md`，只当线索、不当证据。

逐条独立复核：亲自在干净路径复跑 handoff §6 的命令（分支 `p0/obs-eval`，`$env:MKTKB_PROJECT_TOTAL_LIMIT_CNY = "20.0"`，`.\.venv\Scripts\python.exe -B`），每条给 `PASS / FAIL / BLOCKED / NOT-RUN` + 证据（命令 + `文件:行` 或输出摘录）。特别检查：§5 第 2 条 8 行 Span 表是否逐行覆盖、第 5/6 条负例是否真抛错、第 8 条全量测试是否**无新增失败**（与 `main` 基线对比，不得只看绿条）。

写 `.claude\handoffs\T001-obs-contracts\review.md`；复跑证据原文放 `docs\reports\OBS-EVAL\P0\evidence\verify\T001\`。

你不修改任何交付物、不改代码、不 push；发现放水或未覆盖即写 FAIL / NOT-RUN。回复末尾给 ≤10 行结论摘要（逐条结论、不通过项、未覆盖、建议返工范围）。

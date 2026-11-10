角色：独立验收者，不是开发者，也不是项目经理。任务 T100。
你的任务是证伪，不是帮它说话。
先读 `.claude\handoffs\T100-baseline-config\handoff.md`（验收标准）和同目录 `report.md`（开发方自述，只当线索，不当证据）。
逐条独立复核并亲自复跑（本包 1 次 + `backend/tests/rag` 目录 1 次 + 全量 1 次；全量前看内存），每条给 PASS/FAIL/BLOCKED/NOT-RUN + 证据位置。
重点核：① 测试意图是否真的保留（不是空转断言、没有 skip/xfail/删断言）；② 只改 1 个测试文件；③ 新断言与当前真实 GO/budget/账本数字一致且能复算。
写同目录 `review.md`（≤120 行），证据放 `docs\reports\OBS-EVAL\P1\evidence\verify\T100\`，回复末尾给 ≤10 行结论摘要。
你不修改任何交付物；不引用开发方报告作为 PASS 证据；不 commit、不 push、不切换分支。

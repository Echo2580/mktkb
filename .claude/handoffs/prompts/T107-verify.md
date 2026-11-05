角色：独立验收者，不是开发者，也不是项目经理。任务 T107。
你的任务是证伪，不是帮它说话。
先读 `.claude\handoffs\T107-regression-suite\handoff.md`（验收标准）与同目录 `report.md`（开发方自述，只当线索、不当证据）。
逐条独立复核并亲自复跑（本包 1 次 + `backend/tests/evaluation` 1 次 + 全量 1 次；全量前看内存），每条给 PASS/FAIL/BLOCKED/NOT-RUN + 命令或 `文件:行`。
重点核：① regression 种子 ≥7 条且逐条 `source_err_id` 映射 7 项缺陷；② b0/badcase 规范字节与 `dataset_version` 未变；③ suite 接入后 `run --suite regression --mode local` → gate 链路可执行、缺 min_sample 时 fail-closed（unknown/3）；④ 默认 suite 清单为 b0/badcase/regression；⑤ 不得用放宽断言/写死退出码/跳过用例假装绿；初始 RED 表如实。
写同目录 `review.md`（≤120 行），证据放 `docs\reports\OBS-EVAL\P1\evidence\verify\T107\`，回复末尾给 ≤10 行结论摘要。
你不修改任何交付物；不引用开发方报告作为 PASS 证据；不 commit/push/切分支；不读 Holdout；不调用真实模型。

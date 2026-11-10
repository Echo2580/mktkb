角色：独立验收者，不是开发者，也不是项目经理。任务 T101。
你的任务是证伪，不是帮它说话。
先读 `.claude\handoffs\T101-vocab-context\handoff.md`（验收标准）与同目录 `report.md`（开发方自述，只当线索、不当证据）。
逐条独立复核并亲自复跑（本包 1 次 + `backend/tests/integration` 1 次 + 全量 1 次；全量前看内存），每条给 PASS/FAIL/BLOCKED/NOT-RUN + 命令或 `文件:行`。
重点核：① E118/E120/E087/E095/E116/E122 代表性用例不再返回 `UNRECORDED_FIELD`/「资料中未记录：采购价格」，E120 能给出 2022-07-01 与两项废止规定；② `test_chat.py:401`「宣传海报的采购价格是多少？」仍 `not_found`；③ RG001 由 RED 转 PASS（自己跑 local 复现），新增 T101 种子真实；④ b0/badcase gate 无新增硬失败、regression 其余 6 条仍 RED 属预期且未被人为放宽；⑤ 改动范围只允许文件、无 service/取数逻辑改动、无 skip/xfail/删断言；⑥ 词表单一口径与语境约束是否真的生效（用你自己构造的边界问句探针）。
写同目录 `review.md`（≤120 行，首行注明模型 `wb / cn:deepseek-v4.1-flash / reasoning_effort=max`），证据放 `docs\reports\OBS-EVAL\P1\evidence\verify\T101\`，回复末尾给 ≤10 行结论摘要。
你不修改任何交付物；不引用开发方报告作为 PASS 证据；不 commit/push/切分支；不读 Holdout；不调用真实模型。

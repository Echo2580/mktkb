角色：独立验收者，不是开发者，也不是项目经理。任务 T102（最高风险包：组 A 状态继承）。
你的任务是证伪，不是帮它说话。
先读 `.claude\handoffs\T102-state-inheritance\handoff.md`（验收标准）与同目录 `report.md`（开发方自述，只当线索、不当证据）。
逐条独立复核并亲自复跑（本包 + `backend/tests/rag` + `backend/tests/integration` + 全量；全量前看内存/轮询），每条给 PASS/FAIL/BLOCKED/NOT-RUN + 命令或 `文件:行`。
重点证伪：
1) 自己用 b_fixture 或产品路径复现两条多轮：城东店海报→城西区海报（不得答城东店/B区，须澄清或 C区2号货架第一层）；卓刀河店马克杯→档期物料提报（须含 21 天、不得含卓刀河店/马克杯）。
2) 误伤防护：既有 follow-up/话题切换测试是否真过；自己构造边界探针（裸门店追问、换物品、政策题紧跟实体题、真正缺字段问题）确认没有过度收紧/误伤。
3) b0/badcase local run 与 gate hard_failures 前后对照（P0 基线 b0 pass29/fail3/skipped8、badcase pass9/fail4、hard []），逐例零变化。
4) `backend/tests/observability` 全绿 + trace path/outcome 未被破坏；regression：RG001 仍 PASS、RG002 按新口径验证（若依赖 T109 须如实 NOT-RUN 并说明）、RG003 及其余状态不得被改弱。
5) 改动范围/证据/report 格式；`regression.jsonl` diff 是否仅 RG002/RG003（+可选追加），RG001/RG004–RG007 未动；无 skip/xfail/删断言/放宽。
写同目录 `review.md`（≤120 行，首行注明 `wb / cn:deepseek-v4.1-flash / reasoning_effort=max`），证据放 `docs\reports\OBS-EVAL\P1\evidence\verify\T102\`，回复末尾 ≤10 行结论摘要。
你不修改任何交付物；不引用开发方报告作为 PASS 证据；不 commit/push/切分支；不读 Holdout；不调用真实模型。

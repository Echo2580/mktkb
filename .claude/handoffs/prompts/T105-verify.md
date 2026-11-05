角色：独立验收者，不是开发者，也不是项目经理。任务 T105（D6 指代/字段错配，ERR-06）。
你的任务是证伪，不是帮它说话。
先读 `.claude\handoffs\T105-anaphora-field\handoff.md` 与同目录 `report.md`（只当线索）。
逐条独立复核并亲自复跑（本包 + rag + integration + 全量；b0/badcase/regression），每条给 PASS/FAIL/BLOCKED/NOT-RUN + 命令或 `文件:行`。
重点证伪：
1) 自己用多轮 HTTP 产品路径复现三种语境：「城西区宣传海报在哪」→「那个海报呢」（须只答位置、无价格/规格等未问字段）；上文问价格/规格→只答该字段；无上文→澄清。**不得整条 12 字段渲染**。
2) 独立核实"不误伤"：`test_p1_t102_state_inheritance.py`、T101 测试、既有 follow-up/话题切换/裸门店 followup/政策题不继承 全绿；自己构造边界探针（"这个呢"/"那家呢"/"它还…吗"/纯指代无实体）确认没有过度澄清或误继承。
3) RG006 是否真按口径收口（local 澄清、forbidden 覆盖未问字段、非只测文案）；RG001–RG005/RG007 状态不变。
4) b0/badcase local run+gate 前后对照（hard 无新增、case 级 0 变化）；改动范围/证据/report 格式；无 skip/xfail/删断言。
写同目录 `review.md`（≤120 行，首行注明 `wb / cn:deepseek-v4.1-flash / reasoning_effort=max`），证据放 `docs\reports\OBS-EVAL\P1\evidence\verify\T105\`，回复末尾 ≤10 行结论摘要。
你不修改任何交付物；不引用开发报告作 PASS 证据；不 commit/push/切分支；不读 Holdout；不调用真实模型。

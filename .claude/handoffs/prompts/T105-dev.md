角色：开发助手。任务 T105（MKTKB 项目 P1 第 7 包：D6 指代/字段错配，ERR-06）。
第一步：完整读 `.claude\handoffs\T105-anaphora-field\handoff.md`，严格按「输入 / 交付物 / 验收标准 / 边界」执行。
核心：修「那个海报呢」类指代追问——继承实体时必须判断"问什么"：有上文字段则只答该字段（如问位置答 C区2号货架第一层）；无可继承字段则澄清要哪项信息；指代无源则澄清；**任何情况不得整条记录全字段倾倒**。主改 `rag/query.py`（anaphora 字段角色继承/澄清/无源），必要时最小改 `rag/answer.py` 防全字段渲染；收口 RG006（local 澄清、forbidden 加强未问字段，多轮完整复现依赖 T109）；不得回退 T102 的 anaphora/reset 行为。
证据 ≤4 份放 `docs\reports\OBS-EVAL\P1\evidence\T105\`；写 `.claude/handoffs/T105-anaphora-field/report.md`（五段、≤80 行、自证带命令/路径）；1 个 commit（消息 `p1/T105 anaphora field inheritance + no-field clarification`）；回复末尾 ≤10 行交接摘要（含 commit sha、改动文件、测试结果、b0/badcase/regression 前后对照）。
测试：本包 + `backend/tests/rag` + `backend/tests/integration` + 全量（先 `$env:MKTKB_PROJECT_TOTAL_LIMIT_CNY="20.0"`；内存 2.51GB；全量前看 FreePhysicalMemory；既有 flake 隔离复跑记录）；b0/badcase local run+gate 前后对照。
禁止：改 `conversations/` 层、`intent.py`、b0/badcase、gate_v0_1、其他包文件；skip/xfail/删断言/放宽（RG006 仅按口径收口）；真实模型调用；读 `.env`/Holdout；切分支；push；新增生产依赖。
`report.md` 首行注明：`wb / cn:deepseek-v4.1-flash / reasoning_effort=max`。

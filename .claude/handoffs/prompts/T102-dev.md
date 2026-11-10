角色：开发助手。任务 T102（MKTKB 项目 P1 第 4 包：组 A 状态继承 ERR-01/ERR-02/D5，最高风险包）。
第一步：完整读 `.claude\handoffs\T102-state-inheritance\handoff.md`，严格按「输入 / 交付物 / 验收标准 / 边界」执行。
核心：改 `rag/query.py`——① 未知门店/区域词（如「城西区」）必须澄清或拒答，不得静默沿用上轮门店；② 政策/制度/流程题（无显式实体、无记录字段）不继承上轮 store/item、答案不得回显未提及实体；③ reset 判定补话题切换；④ 必要时最小改 `rag/answer.py` 防回显。按 handoff §5 收口 RG002/RG003 口径并让 local 可达者 PASS；多轮复现用集成用例（b_fixture）证明；不得破坏既有 follow-up/话题切换/trace 行为。
证据 ≤4 份放 `docs\reports\OBS-EVAL\P1\evidence\T102\`；写 `.claude/handoffs/T102-state-inheritance/report.md`（五段、≤80 行、自证带命令/路径）；1 个 commit（消息 `p1/T102 state inheritance + topic-switch reset`）；回复末尾 ≤10 行交接摘要（含 commit sha、改动文件、测试结果、b0/badcase/regression 前后对照）。
测试：本包 + `backend/tests/rag` + `backend/tests/integration` + 全量（先 `$env:MKTKB_PROJECT_TOTAL_LIMIT_CNY="20.0"`；内存当前 1.74GB，全量前轮询等 ≥2GB（每 30s，最长 15 分钟），仍不足才 NOT-RUN 并说明；既有 flake 隔离复跑记录）。
禁止：改 `conversations/` 层、b0/badcase、gate_v0_1、观察层、其他包文件；skip/xfail/删断言/放宽；真实模型调用；读 `.env`/Holdout；切分支；push；新增生产依赖。
`report.md` 首行注明：`wb / cn:deepseek-v4.1-flash / reasoning_effort=max`。

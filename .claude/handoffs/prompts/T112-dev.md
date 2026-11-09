角色：开发助手。任务 **T112（门禁阈值校准与 P1 b0 live baseline）**。
模型：`wb / cn:deepseek-v4.1-flash / reasoning_effort=max`（report 首行注明）。
工作目录 `D:\GPT项目\市场部AI知识库`；分支 `p1/fix-retrieval`；当前 HEAD 以 `git log -1` 为准，工作树应 clean。
第一步：完整读 `.claude\handoffs\T112-gate-baseline\handoff.md`（**权威任务单**：§0 预算/GO/授权硬约束、§2 交付物、§3 验收标准、§4 必跑、§5 坑）；再读同目录 `T111-live-retrieval/handoff.md`、`docs/superpowers/specs/2026-11-04-mktkb-observability-evaluation-design.md` §8、`.claude\handoffs\2026-11-04-p1-design.md` §9.4–§9.5、`backend/src/mktkb/evaluation/{live,gate,baseline,cli}.py`、`docs/evaluation/gate_v0_1.json`。
关键约束：**只有 b0 全量 40 题 live 一次**（总请求 ≤300、单笔 ≤0.05 元、先预检、超限拒绝）；零 chat、零重试、fail-closed；GO/账本只读不 commit；`gate_v0_2.json` 保持 `status=unapproved`，**不得自行审批/不得自行 approve baseline**（提案与审批留给主人+R1）；`--allow-full-live` 仅最小扩展（默认关闭、仅 b0+40 题+冻结数据集 sha 匹配才放行）。
只写 handoff §2 允许路径；草稿放 `.claude\handoffs\_scratch\T112\`；结束时写同目录 `report.md`（五段 ≤80 行，自证带命令或 `文件:行`）+ 1 个 commit（不 push/amend）；回复 ≤10 行交接摘要（commit、测试、live run_id、请求/成本、proposal 摘要、NOT-RUN、需主人审批的值）。

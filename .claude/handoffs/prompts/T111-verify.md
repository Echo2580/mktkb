角色：独立验收者（全新上下文），不是开发者/PM。任务 **T111（live 检索运行器）独立验收**。证伪导向。
模型：`wb / cn:deepseek-v4.1-flash / reasoning_effort=max`（review 首行注明）。
工作目录 `D:\GPT项目\市场部AI知识库`；分支 `p1/fix-retrieval`；交付 commit 见 `git log -1`（父为 T110 收口簿记）；工作树应 clean。

必读：`.claude\handoffs\T111-live-retrieval\handoff.md`（§0/§3）、同目录 report（只当线索）、`2026-11-04-p1-design.md` §5、GO 结构（只读、不打印凭据）。
定向验证（逐条 PASS/FAIL/BLOCKED/NOT-RUN + 命令/`文件:行`；不引用 report 作 PASS 证据）：
1) **pilot 10 题真实跑通且成本可核算**：核 pilot run 目录（`var/eval/runs/<run_id>/`，不入库）的 manifest/summary/账本记录；核预检估算 vs 账本口径（保守）；超阶段剩余/单请求 0.05 上限负例被拒绝；**只跑 10 题、pilot 后停止**（无自动全量）。
2) **零 chat**：独立 spy/构造计数（可 monkeypatch 供应商类）证明 chat provider 实例化=0、调用=0；真实调用仅 embedding+rerank（次数符合「索引 chunk 批次 + 10×2」量级）；零重试（spy 计数）。
3) **GO/账本/预算校验**：未授权 stage/service、provider binding 不符、超限 → 拒绝（fake/负例）；账本 stage=`P1-RETRIEVAL` 有记录、sha 绑定用前缀哈希。
4) **manifest/版本绑定**：六要素 + corpus sha + index_revision；每条 CaseResult 带版本字段；`mode=live/scope=retrieval_only`。
5) **失败语义**：provider 错误 → case `error` fail closed（不静默跳过）；无重试；失败不产出半成品索引。
6) **验收方复跑 live 仅 ≤10 题子集**（不得超；用 GO/账本，成本可核算）；其余用 fake/local 复跑：本包/evaluation/全量（0 failed/0 error）、b0/badcase local+gate 对 P0（`case_diffs=0`、hard `[]`）、regression 状态不变。
7) **合规/泄漏/形式**：只改允许路径（runner/corpus/live 接线/测试/证据/report）；无 conversations/intent/业务 API/检索算法/b0/badcase/gate_v0/O baseline/账本/GO 改动；证据无凭据/密钥/答案原文；var 产物不入库；未读 Holdout、未打印 `.env`；单 dev commit、report ≤80、证据 ≤4、无 skip/xfail/删断言/新依赖。
写 `.claude\handoffs\T111-live-retrieval\review.md`（≤120 行，首行模型标注）+ 证据 `verify/T111/`（≤4 份）；不改交付物、不 commit/push、不读 `.env`/Holdout；**pilot 复跑 ≤10 题**；回复 ≤10 行摘要。

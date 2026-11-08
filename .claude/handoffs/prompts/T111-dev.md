角色：开发助手。任务 **T111（live 检索运行器与真实索引）**。交接单：`.claude\handoffs\T111-live-retrieval\handoff.md`（本消息与之一致，细节以文件为准）。
模型：`wb / cn:deepseek-v4.1-flash / reasoning_effort=max`（report 首行注明）。
工作目录 `D:\GPT项目\市场部AI知识库`；分支 `p1/fix-retrieval`（T100–T107/T101–T106/T108/T109/T110 已 G6；HEAD 见 `git log -1`）；开工前 `git status --short` clean。
**本包是 P1 唯一允许真实调用的包；主人已定：pilot 10 题跑完必须停一次给主人过目。**

## 必读（按序）
1. `.claude\handoffs\T111-live-retrieval\handoff.md`（**§0 PM 口径/§2 交付物/§3 验收标准/§5 坑**）
2. `2026-11-04-p1-design.md` §5（:81-95）与 §8；`2026-11-04-p1-task-breakdown.md` §T111
3. `backend/src/mktkb/live_authorization.py`（`load_live_authorization(stage="P1-RETRIEVAL", service="rag")`/`resolve_live_gate`/`assert_provider_binding`）、`rag/config.py`（provider_mode/凭据）、`rag/providers.py`（`BailianEmbeddingProvider`/`BailianRerankProvider`）、`rag/budget.py`（BudgetLedger）、`rag/index.py`（`search(plan, limit)` 检索路径 vs `ask` 答案路径）、`evaluation/{runner,corpus}.py`、`controlled_execution.py`（成本/账本封装参考）
4. `docs/evidence/LOCAL-R1-20261101/PM/S2-LIVE-GO.json`（只读结构；不得打印凭据；不 commit）

## 硬约束（摘要）
- 只做检索：`mode=live + scope=retrieval_only`；**绝不调用 chat**（不得走 `RagIndex.ask` 答案生成；用 `index.search(plan, limit)` 或等价检索 API）；零重试、串行、首个失败即停（fail closed）。
- 隔离索引 `var/eval/runs/<run_id>/index/`（gitignored 不入库）；manifest 绑定 `dataset_version / corpus_manifest_sha256 / index_revision / pipeline_version / gate_version / mode=live / scope=retrieval_only`；每条 CaseResult 带版本字段。
- 成本：运行前预检（语料 embedding token 估算 + N 题 ×(1 query embed + 1 rerank)，官方标价）；超 `P1-RETRIEVAL` 剩余或单请求 0.05 即拒绝；每笔真实调用经共享账本 `docs/evidence/LOCAL-R1-20261101/budget/live-ledger.jsonl` stage=`P1-RETRIEVAL` 预留/结算；账本 sha 绑定用 GO 历史前缀哈希 `f4710b18…`；报告只写保守口径；环境必须 `MKTKB_PROJECT_TOTAL_LIMIT_CNY=20.0`。
- **pilot 10 题后停止**（PM 指定 b0 前 10 题或等价子集）：跑完输出成本与指标摘要即停，**不得自动跑全量**；全量留 T112 且需主人放行。
- 零 chat 证明：spy/构造计数证明 chat provider 实例化=0、调用=0；真实调用仅 embedding+rerank。
- 不改业务代码/API/检索算法/`conversations`；不动 P0 baseline；不 commit `var/`/账本/GO；不打印凭据/`.env`；不读 Holdout；不 push/amend；无 skip/xfail/删断言。

## 交付物（只准写这些路径）
`evaluation/runner.py`、`evaluation/corpus.py`、live 配置接线（可新增 `evaluation/live.py` 等模块，report 说明）、`backend/tests/`（fake 覆盖：预检/预算拒绝/GO 绑定不符/零 chat spy/失败 fail closed/pilot=10 停止/manifest 版本字段/不静默跳过）、证据 `docs/reports/OBS-EVAL/P1/evidence/T111/`（≤4；命令/成本/指标/零 chat 证明；不含凭据/答案原文）、`report.md`（≤80）、1 commit（代码+测试+报告+证据，不含 var 产物）。

## 必跑
本包测试 / `backend/tests/evaluation` / 全量（0 failed/0 error；内存<2GB 轮询；flake 处理）/ b0+badcase local+gate 对 P0（`case_diffs=0`、hard `[]`）/ regression 状态不变；**真实 pilot 10 题（受 GO/账本）**；pilot 后停。命令口径：pytest 前 `$env:MKTKB_PROJECT_TOTAL_LIMIT_CNY="20.0"`；`.\.venv\Scripts\python.exe -B -m pytest ...`；同一时间只跑一套。

## 交付
1 个 commit：`p1/T111 live retrieval runner + isolated index (pilot)`（不 push/不 amend）；report 五段 ≤80 行（含 pilot 命令/成本/指标/零 chat 证明/账本记录）；回复 ≤10 行摘要（commit、pilot 指标与成本、零 chat 证明、测试数字、偏离、风险）。**跑完 pilot 必须停止，等待 PM 转主人过目。**

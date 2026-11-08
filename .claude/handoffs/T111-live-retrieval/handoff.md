# T111 交接单：live 检索运行器与真实索引（P1 第 12 包，最高风险）

> 基线：分支 `p1/fix-retrieval`（T100–T107/T101–T106/T108/T109/T110 已 G6；当前 HEAD 见 `git log -1`）。
> 前置：P1-PRE-2 已签（`P1-RETRIEVAL` 3.0 元、services=["rag"]、max_requests=1000、max_request_cny=0.05、expires 2026-11-30）；运行环境必须 `MKTKB_PROJECT_TOTAL_LIMIT_CNY=20.0`。
> 执行者：开发 subagent（`wb / cn:deepseek-v4.1-flash`，`reasoning_effort=max`）。PM 不写代码。
> **本包是全 P1 唯一允许真实调用的包；主人已定：pilot 10 题跑完停一次给主人过目，再放全量。**

## 0. PM 口径（先读；硬约束）
1. **范围**：只做检索（索引重建、query embedding、rerank、指标/门禁数据），**绝不调用 chat**；`mode=live + scope=retrieval_only`。零重试、串行、首个失败即停（fail closed）。
2. **产物**：`var/eval/runs/<run_id>/`（gitignored、不入库）；隔离索引 `<run_dir>/index/`；manifest 绑定 `dataset_version / corpus_manifest_sha256 / index_revision / pipeline_version / gate_version / mode=live / scope=retrieval_only`；每条 CaseResult 带版本字段。
3. **成本**：运行前预检（语料 embedding token 估算 + N 题 × (1 query embed + 1 rerank)，按官方标价估算 CNY；超 `P1-RETRIEVAL` 剩余或单请求 0.05 即拒绝）；每笔真实调用经共享账本 `docs/evidence/LOCAL-R1-20261101/budget/live-ledger.jsonl` 的 stage=`P1-RETRIEVAL` 预留/结算；账本 sha 绑定用 GO 的历史前缀哈希 `f4710b18…`（不得写整本 sha）；报告只写保守口径（估算/账本记录），不写“实际账单”。
4. **Pilot 停点**：先只跑 **10 题**（PM 指定 b0 前 10 题或等价子集）；跑完打印/落盘成本与指标摘要后**必须停止**，由 PM 交主人过目；**不得自动跑全量**（全量留 T112 校准、需主人放行）。
5. **验收方复跑 live 仅 ≤10 题子集**；超出即违规。
6. **GO/账本硬绑定**：`load_live_authorization(stage="P1-RETRIEVAL", service="rag")` + `resolve_live_gate`；`assert_provider_binding` 核对 embedding/rerank provider/model/host/region/dimensions 与 GO bindings；chat 服务未授权（负例必须被拒）。
7. **失败语义**：provider 错误/超时/预算拒绝 → 该 case `error`（fail closed，不静默跳过）；超限 → 拒绝运行。
8. **零 chat 证明**：provider spy/构造计数证明 chat gateway/provider 实例化=0、调用=0；只允许 embedding+rerank。
9. 不改业务代码/API/检索算法/`conversations`；不动 P0 baseline（只读）；不 commit `var/`/账本/GO；不打印凭据/`.env`；不读 Holdout。

## 1. 目标
live 检索运行器：`mode=live + scope=retrieval_only`，真实 embedding `text-embedding-v4`(1024) + rerank `gte-rerank-v2`，隔离索引、成本预检/账本、失败 fail-closed、零重试、零 chat；pilot 10 题跑通且成本可核算。

## 2. 交付物（只准写这些路径）
1. `backend/src/mktkb/evaluation/runner.py`（live 分支：预检、隔离索引、retrieval-only 执行、逐 case 版本字段、成本账本、fail-closed、pilot 限制、manifest 绑定）。
2. `backend/src/mktkb/evaluation/corpus.py`（live 索引装配：真实 embedding、隔离 data_dir、`index_revision` 记录）。
3. live 配置接线（可新增 `evaluation/live.py` 等模块；report 说明）。
4. `backend/tests/`（fake provider 覆盖：预检/预算拒绝/GO 绑定不符/零 chat spy/失败 fail closed/pilot=10 停止/manifest 版本字段/不静默跳过）。
5. `var/eval/runs/<pilot_run_id>/`（不入库；PM 只读核对成本/指标）、证据 `docs/reports/OBS-EVAL/P1/evidence/T111/`（≤4；命令/成本/指标/零 chat 证明；**不含凭据/答案原文**）、`report.md`（≤80）、1 commit（代码+测试+报告+证据，不含 var 产物）。
禁止：`conversations/`/`intent.py`/业务 API/schema/检索算法、b0/badcase/regression 数据、`docs/evaluation/gate_v0_2.json`（T112）、P0 baseline、账本/GO 原件、`.env` 打印、Holdout、push/amend、skip/xfail/删断言。

## 3. 验收标准（逐条）
1. **pilot 10 题真实跑通**（exit 0 或明确 data/config exit 3），成本可核算（预检估算 vs 账本记录，保守口径）；账本 stage `P1-RETRIEVAL` 有记录；超阶段剩余/单请求上限负例被拒绝。
2. **零 chat**：spy 证明 chat 实例化/调用=0；真实调用仅 embedding+rerank（次数符合“索引 chunk 批次 + 10 题 × 2”量级）。
3. **GO/账本/预算校验**：未授权 stage/service、provider binding 不符、超限 → 拒绝（fake/负例测试）。
4. **manifest/版本绑定**：六要素齐全 + `corpus_manifest_sha256` + `index_revision`；每 CaseResult 带版本字段。
5. **失败语义/零重试**：provider 错误 → case `error` fail closed；spy 证明无重试；失败不静默跳过。
6. **pilot 停点**：pilot 后进程停止（不得自动全量）；PM 可复跑核对证据；验收方复跑 ≤10 题。
7. **不泄漏/合规**：证据无凭据/密钥/答案原文；var 产物不入库；未读 Holdout；全量测试 0 failed/0 error；b0/badcase/regression（local）不受影响。

## 4. 必跑
本包测试 / `backend/tests/evaluation` / 全量（0 failed/0 error；内存<2GB 轮询；flake 处理）/ b0+badcase local+gate 对 P0（不受影响，`case_diffs=0`、hard `[]`）/ regression 状态不变；真实 pilot 10 题（受 GO/账本）；pilot 后停。

## 5. 坑
- `RagConfig(provider_mode="live")` 可能默认带 chat 配置：必须确保 chat provider 不创建/不调用；`RagIndex.ask` 会生成答案 → live 只允许 `index.search(plan, limit)`（或等价 retrieval-only API），不得 ask。
- 隔离索引 data_dir 在 run 目录；索引构建触发真实 embedding（成本大头）→ 先预检再建；失败不得写半成品索引。
- 账本：请求前预留、响应后结算；零重试；预算拒绝为明确错误；sha 绑定用历史前缀哈希。
- 串行执行，运行期间不得并发其他 live；pilot 输出成本与指标摘要后停止。
- 证据/回复不得出现凭据、GO 原文、逐题答案全文（可给指标摘要/命令）。

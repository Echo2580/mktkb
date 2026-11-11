# P2-T207-FIX-LIVECAP 报告（live 单请求上限 / 无 OCR 计划向量层静默降级）

- 开发助手（全新上下文）；**零真实调用**（出站全由 `httpx.MockTransport` 接住）、零网络、
  未读 `.env`/H1/H2；未改 conversations/copy.py、fixtures、账本/预算/GO、`p2_scoring`/`scorers`；未 commit。
- 改动面：`p2_live.py`、`product_adapter.py` + 新增回归 + 两处文档 + 本目录证据。

## 1 根因（R4PREP F-1）

`_start_live` 把 `RagConfig.max_request_cny` 设成 `plan.reserve_peak_cny`。`page_count=0` 的计划峰值
只有 chat 的 0.018688，而 `rag/providers.py:316-321` 每次 embedding POST 前固定按官方单请求 81,920
token 预留 `81920×0.5/1e6 = 0.04096` ⇒ 每次 embed 都在发送前被拒，`qa/service.py` 吞成
`degraded=embedding_error`（不硬停）；rerank 同理（live 配置 30,000 token → 0.024）。
计划侧绕不过去：embedding `total_tokens_cap` 在 `p2_contracts` 冻结为 4096。

## 2 修复（都在“构建应用/首个发送”之前）

1. `p2_live.provider_single_request_bounds(config)`：**不写魔法数** —— embedding/rerank 复用
   `evaluation/live.{embedding,rerank}_reserve_cny`（= provider 自检同一公式），chat 用
   `settlement_policy.build_policy(chat)` 的冻结 cap（6144×2/M + 800×8/M）。
2. `p2_live.resolve_request_ceiling(...)`：`effective = max(计划峰值, 各 provider 单次预留)`，
   且必须 `≤ GO 的 authorization.max_request_cny`；不足即稳定码 `live_request_ceiling_insufficient`
   （不发送/不预留/不降级）。`_start_live` 在 `create_app` 之前调用，仅在 `effective != 计划峰值`
   时 `replace` 配置；`run_live_p2` 在 `run_p2` 前显式 `adapter.start()`，让该码直接抛给调用方
   （否则被 ingest 失败路径吞成 `ingest_failed`）。推导写进 `summary.json` 的
   `providers.live.request_ceiling`（只含金额）。

## 3 推导与实际值

- embedding 0.04096（81,920 × 0.5/M）/ rerank 0.024（30,000 × 0.8/M）/ chat 0.018688（6144×2/M + 800×8/M）。
- 无 OCR 计划（峰值 0.018688）⇒ effective = **0.04096**，≤ GO 0.5。
- 含 12 页 OCR 计划（峰值 0.5）⇒ effective = **0.5** = 计划峰值：配置不 replace、计数不变。

## 4 前后探针（`evidence/probe-livecap.out.json`；同计划/同 transport）

- 无 OCR · 旧语义（`resolve_request_ceiling` 退回 `effective = 计划峰值`）：embedding POST **0**、
  rerank POST **0**、`degraded=["embedding_error"]`、`EMBEDDING_UNAVAILABLE`、run `aborted`。
- 无 OCR · 修复后：embedding POST **3**（灌库 2 批 + 查询 1）、rerank POST **1**、`degraded=[]`、
  run `succeeded`、`effective_max_request_cny=0.04096 ≤ GO 0.5`。
- GO 上限压到 0.02（≥ 计划峰值，旧 GO 校验能过）：装配期 `live_request_ceiling_insufficient`，
  POST/预留/chat 全 0、无产物、无降级。
- 含 OCR 计划：旧语义 vs 修复后计数逐值相同（embedding 3 / rerank 1 / OCR 0 / chat 1），effective 均 0.5。

## 5 测试与文档（独立 basetemp，零真实出站）

- `test_p2_live_wiring.py test_p2_runner.py test_p2_live_request_ceiling.py` → **69 passed**
  （基线 63 + 新增 6）；`test_p2_product_e2e.py` 仓库中不存在（任务书笔误）。
- 另跑 `test_p2_ocr_ingestion.py test_p2_authorization.py` → 84 passed。
- 新增回归覆盖：provider 上界公式、effective/GO 上限、无 OCR 计划 POST>0 且无降级、
  GO 上限不足装配期拒绝、含 OCR 计划计数不变。
- 文档：`docs/evaluation/p2-live-binding-v0_1.md` §10.10；`T207-runbook.md` §3.2 前置 2 + §9 接线面。

## 6 限制

- 未做真实 live run（任务书要求）；F-1 由真实 provider 类 + MockTransport 复现。
- rerank 预检按 live 实参 30,000 token → 0.024（任务书 0.0048 是**计划侧**冻结上界）；两者都 < 0.04096，
  不改 effective，但 0.024 才是 provider 会拒的值，故按 0.024 记。
- GO 的 `max_request_cny` < 0.04096 时无 OCR 计划会在启动期被拒（预期），只能由经理重签 GO。

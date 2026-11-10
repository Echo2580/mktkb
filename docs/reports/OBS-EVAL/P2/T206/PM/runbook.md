# T206 pilot runbook（真实准入执行 · 停止 · 核对 · 回滚）

- 适用：T206 5 题真实 pilot。计划 `PM/p2-pilot-plan-v0_1.json`（`plan_sha256=d2baaa9c…73c2`），
  候选 GO `PM/P2-LIVE-GO.CANDIDATE-DRAFT.json`（**不可用**）。
- 状态：**§1–§3 现在可执行（零真实调用）；§4 真实 pilot BLOCKED**（缺口 G1–G4，见 readiness §9）。
  缺口未关闭 + 正式 GO 未落盘前，禁止任何真实发送。
- 纪律：串行、自动重试 **0**、单轮 60 秒硬截止；首个服务/授权/预算/数据完整性错误即停后续付费。
  合法拒答允许零 chat（不补调用）。**不得**读 `.env`/H2、不得改共享账本/预算/历史。

## 1 只读前置检查（每次执行前，按顺序；任何一项不符即停）

```powershell
cd 'D:\GPT项目\市场部AI知识库'

# 1.1 提交锚（期望 61a9a8f，或 T206 执行开始时的已接收提交）
git rev-parse --abbrev-ref HEAD; git rev-parse --short HEAD

# 1.2 账本/预算 SHA（期望见下）
.\venv\Scripts\python.exe -B -X utf8 -c "import hashlib,pathlib;L=pathlib.Path('docs/evidence/LOCAL-R1-20261101/budget/live-ledger.jsonl');B=L.with_name('budget.json');print(hashlib.sha256(L.read_bytes()).hexdigest());print(hashlib.sha256(B.read_bytes()).hexdigest())"
#   期望：1f46d1b9e846528d5a1635db5175a997eab9da075d61a90a8cbf803f3fde7390  （账本，958,277 B）
#        084ba9acb4ee90379fd51fab8878f6dd4bab1bd481bff2a14c83057ffbc1cc58  （预算，1,444 B）

# 1.3 正式 GO 是否存在（签发前必须 False；签发后必须 True 且记录其 SHA）
Test-Path -LiteralPath 'docs\evidence\LOCAL-R1-20261101\PM\P2-LIVE-GO.json'

# 1.4 只读预检（不预留、不发请求；read_ledger_snapshot 会在账本旁建/删瞬时 .lock，不追加事件）
.\venv\Scripts\python.exe -B -X utf8 -c "import json;from mktkb.evaluation.p2_authorization import read_ledger_snapshot,preflight_p2;from mktkb.evaluation.p2_contracts import P2RunPlan;p=P2RunPlan.from_dict(json.load(open('docs/reports/OBS-EVAL/P2/T206/PM/p2-pilot-plan-v0_1.json',encoding='utf-8')));r=preflight_p2(p,read_ledger_snapshot());print(json.dumps({'ok':r.ok,'reasons':list(r.reasons),'stage_remaining':r.stage_remaining_cny,'total_remaining':r.total_remaining_cny,'requests_remaining':r.requests_remaining,'worst_case':r.worst_case_cny,'reserve_peak':r.reserve_peak_cny,'production_ready':r.production_ready},ensure_ascii=False))"

# 1.5 预检后立即复算 1.2：SHA 必须与 1.2 完全一致（证明预检零写入）
```

预期读数：

| 现场 | `ok` | `reasons` | 说明 |
|---|---|---|---|
| 现状预算（limit 20、无 P2 阶段） | `false` | `budget_total_mismatch`,`stage_allocation_missing`,`stage_budget_insufficient` | **预期拒绝**；修预算前发不出请求 |
| 已落盘修订后（40 / P2-LIVE 20） | `true` | — | `stage_remaining=20`、`total_remaining=24.9290555`、`requests_remaining=55`、`worst_case=0.826784`、`reserve_peak=0.5` |

## 2 签发（经理操作；本 runbook 不代签）

1. **预算修订落盘**：`budget.json` → `limit_cny=40.0` + `stages["P2-LIVE"]=20.0`；算术校验
   `0+0+15.4+3.0+1.57+20.0 = 39.97`，`39.97+0.03(history) = 40.00`（T201 遗留③）。
2. **正式 GO 落盘**：字段与候选一致，改 `nonce`（≥16、无空白、不留仓库副本）、
   `issued_utc`（= 签发时刻）、`expires_utc`（≤14 天），`budget_ledger_sha256` = §1.2 历史前缀
   `f4710b18…`，`scope.plan_sha256=d2baaa9c…73c2`。
3. **进程环境（只设本次进程，不改 `.env`/全局）**：`MKTKB_PROJECT_TOTAL_LIMIT_CNY=40.0`
   （未设 → `env_total_limit_missing`；值≠预算 → `env_total_limit_mismatch`）。
4. 记录：GO SHA、预算 SHA（修订后）、账本历史前缀、`plan_sha256`、`run_id`。

## 3 空跑复演（现在可执行；零真实调用，只证明计划/预检/门序/产物）

```powershell
# 3.1 候选预算的内存快照（source=in-memory，绝不能当真实准入）
#     用 T201 候选快照的同一形状：total_limit_cny=40.0、stage_allocations 含 P2-LIVE=20.0、source="in-memory"
# 3.2 空跑（--out 必须是仓库外的新目录；不给 --snapshot 则读真实固定路径 → 现状下预检拒绝）
.\venv\Scripts\python.exe -B -X utf8 -m mktkb.evaluation.cli p2-run `
  --plan 'docs\reports\OBS-EVAL\P2\T206\PM\p2-pilot-plan-v0_1.json' `
  --snapshot '<内存快照.json>' `
  --out '<仓库外新目录>' `
  --cases '<pilot-cases.jsonl>' `
  --ingest 'fixtures\acceptance\variants\V03_物品位置表_历史V1.xlsx' `
  --ingest 'fixtures\acceptance\normal\D01_物品位置表.xlsx' `
  --ingest 'fixtures\acceptance\normal\D03_市场部工作指南.docx' `
  --ingest 'fixtures\acceptance\normal\D09_物料领用通知.png' `
  --ingest 'corpus\enterprise-20261101\excel\E11_终端物料位置表_当前V2.xlsx' `
  --dataset-version p2-pilot-20261111-v0.1 --label-version p2-pilot-labels-20261111-v0.1
```

- `pilot-cases.jsonl` = `fixtures/evaluation/b0.jsonl` 的 Q01/Q25/Q37 与
  `fixtures/evaluation/regression.jsonl` 的 RG005/RG006 **原样行**按
  Q01,Q25,RG005,RG006,Q37 顺序以 `\n` 拼接并保留末尾换行：
  4,712 B，SHA-256 `a3878212fa1c114eb5a8c280bcf01c74d0131744c6aa568a2edfd36302652c79`
  （该值会作为 run 的 `dataset_sha256`/`manifest_sha256`；字节不同即身份不同）。
- **2026-11-11 实测结果**（本包跑的正是这条）：`{"ok": false, "status": "blocked",
  "stop_code": "ingest_failed", "requests_planned": 55, "requests_sent": 0,
  "production_ready": false, "execution": "dry_run"}`；`summary.json` 里
  `failure.stage=ingest`、`error_code=RuntimeError`、`requests.attempted=0`、
  `real_requests=0`、`billed_cny=0`；隔离库 `import_jobs.error_code=OCR_NOT_CONFIGURED`
  （D09 是 png，Mock 适配器 `ocr_disabled`+`_NoOcrGateway`）。→ 空跑证明「计划/预检/门序/产物」
  可用，同时把 G1/G3（无真实 OCR 传输）暴露在第一道关。
- 空跑**不是** pilot 证据：不产生真实费用、真实 trace 身份或分数。

## 4 真实 pilot 执行（**BLOCKED**：G1–G4 未关闭）

前置（全部满足才允许发送）：readiness §9 的 G1–G4 已关闭且经独立验收；正式 GO 落盘；
§1 全绿；`MKTKB_PROJECT_TOTAL_LIMIT_CNY` 与预算一致。

驱动契约（要写的那个入口，尚不存在）：构造**真实** `P2Gate`（固定路径 GO/预算 +
`read_ledger_snapshot()`）；live 适配器（真实 chat/embedding/rerank、真实 OCR 传输、
`OcrCostCenterBudgetLedger`）；实现 `settle_evidence(ticket, product) -> UsageEvidence`
（来自 provider 实测 usage）；然后**一次性**调用
`await run_p2(plan, adapter=..., authorization=..., gate=..., run_id=..., gate_config=<P2GateConfig>)`，
串行、`max_retries=0`、单轮 60 s。

```powershell
# 形态（脚本就位后；当前文件不存在，执行即错——这是有意的阻断）
.\venv\Scripts\python.exe -B -X utf8 tools\p2_t206_pilot.py `
  --plan 'docs\reports\OBS-EVAL\P2\T206\PM\p2-pilot-plan-v0_1.json' `
  --out '<仓库外新目录>' --cases '<pilot-cases.jsonl>' `
  --ingest '<5 个文件，同 §3.2>' --run-id 'p2-t206-pilot-20261111-01'
```

- run_id：`p2-t206-pilot-20261111-01`（非空 str；空/非 str → 发送前 `run_id_missing`）。
- 环境变量**只列名称**（值不进报告/日志）：`MKTKB_PROJECT_TOTAL_LIMIT_CNY`、
  `MKTKB_MODEL_API_KEY`、`MKTKB_MODEL_BASE_URL`、`MKTKB_MODEL_NAME`、
  `DASHSCOPE_API_KEY`、`DASHSCOPE_BASE_URL`、
  `MKTKB_OCR_SECRET_ID`、`MKTKB_OCR_SECRET_KEY`、`MKTKB_OCR_REGION`、`MKTKB_OCR_DISABLED`。

## 5 停止规则（触发即停；不重试、不补跑、不改计划续跑）

1. §1 任一检查不符（SHA 变化、GO 缺失/过期、预检 `ok=false`）。
2. 门控拒绝：`pre_send_refused` / `gate_error` / `center_budget_exceeded` / `request_limit` /
   `ledger_prefix_mismatch` / `production_not_ready` / `live_requires_real_gate`。
3. 产品侧：首个 `product_service_error`、`turn_timeout`（60 s）、`adapter_error`、`ingest_failed`。
4. OCR：任一页失败/空片段/缺 usage → 停（**重试 0**；重试=新计划+新 GO，并按次计费）。
5. 实测将超计划上界（`requests_planned=55`、`worst_case=0.826784`、单次 0.5）→ 停并报告。
6. 数据完整性：`provider_network_detail_mismatch`、`artifact_validation_failed` → 停（产物仍会写全）。
7. 拒答题若产品调用模型而计费（与「零 chat」预期不符）→ 记录事实、继续同一已批准矩阵，**不**为该题单独重跑。

## 6 事后核对（按顺序，逐项留证据）

1. **账本增量**：新增 `reserved`/`result` 条数、`center_accounted_cny`（pilot 期望 `ocr=0.5` 或 0）、
   失败页是否按固定价保守留账；`billed_cny` 是**结算口径**、不是供应商账单。
2. **产物**：`summary.json` 的 `requests`（planned/attempted/reserved/settled/real_requests/billed_cny）、
   `network.outbound_attempts` 与其 `detail` 相等、`providers` 逐 provider 计数。
3. **身份/证据**：`run_manifest.config_hash` 存在且完整、trace 六字段、`citation_evidence.complete`、
   `gate.json.real_sends_allowed`、`cases.jsonl` 的 `product.evidence`/`retrieved`。
4. **失败身份**：`failure.{stage,case_id,turn,item_id,ticket}`（含在飞 ticket 的 request_id/reservation_id）。
5. **评分（可选、离线）**：逐题 `score_public_case(..., execution_mode="live", real_calls=<实测出站>)`；
   **不要**传 `evidence=`、**不要**把 citations 当 retrieved（R1 残余①）。
6. **结论分开写**：「运行完成/失败」与「质量是否达标」不同层；gate 放行等 `gate_v0_3` 批准（T209）。

## 7 回滚 / 保留现场

- 零真实调用阶段：删 out_dir 即可，账本零写入（SHA 复核可证）。
- pilot 之后：**保留** `out_dir`、trace、receipts、账本；**不改**账本、不回滚历史、不释放预留。
- 失败金额如实留在 `P2-LIVE`；重跑 = 新计划 + 新 GO（`plan_sha256` 绑定），并计入同一 20 元与同一累计请求。
- 只在主人明确要求时才提交/推送；本任务未授权。

## 8 禁止清单

- 禁止把 `PM/P2-LIVE-GO.CANDIDATE-DRAFT.json` 拷贝/改名为固定路径 GO（schema 无 DRAFT 标记，拷过去就会被当真实授权）。
- 禁止提高 `HARD_MAX_REQUESTS`/预算上限、禁止改门槛/减题/换标签、禁止 `skip/xfail` 刷绿。
- 禁止读写 `.env`、H1/H2 题干、历史账本事件；禁止把凭据写进日志/报告/产物。
- 禁止并发发送、禁止自动重试、禁止在 pilot 未接收时扩到全量矩阵。

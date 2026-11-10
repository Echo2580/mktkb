# T206 pilot runbook（真实准入执行 · 停止 · 核对 · 回滚）

- 适用：T206 5 题真实 pilot。计划 **`PM/p2-pilot-plan-v0_2.json`**（`plan_sha256=02725aa7…5d80`，
  批级配额口径；61 请求 / worst-case 0.839072 元 / `max_requests=566`），
  候选 GO **`PM/P2-LIVE-GO.CANDIDATE-DRAFT-v0_2.json`**（**不可用**）。
- 版本：v0.1（`d2baaa9c…`，55 请求 / 560 / 0.826784）已被 PLAN-R1 取代 —— 旧文件保留作历史，
  **不得**再用于签发（批级口径下它在 D09 的 embedding 批次上会低估）。
- 状态（2026-11-11 T206-LIVE 后）：**§1–§3 可执行（零真实调用）；§4 的代码入口已就绪**
  （`p2-run --mode live` + 真实门 + 逐次尝试预留 + usage 证据 + 真实 OCR 传输）。
  仍**禁止**任何真实发送，直到：①经理把正式 GO 落到固定路径；②预算修订落盘；
  ③经理决定是否为 live 检索候选重放补计划项（见 §4.4）。
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
.\venv\Scripts\python.exe -B -X utf8 -c "import json;from mktkb.evaluation.p2_authorization import read_ledger_snapshot,preflight_p2;from mktkb.evaluation.p2_contracts import P2RunPlan;p=P2RunPlan.from_dict(json.load(open('docs/reports/OBS-EVAL/P2/T206/PM/p2-pilot-plan-v0_2.json',encoding='utf-8')));r=preflight_p2(p,read_ledger_snapshot());print(json.dumps({'ok':r.ok,'reasons':list(r.reasons),'stage_remaining':r.stage_remaining_cny,'total_remaining':r.total_remaining_cny,'requests_remaining':r.requests_remaining,'requests_planned':r.requests_planned,'worst_case':r.worst_case_cny,'reserve_peak':r.reserve_peak_cny,'production_ready':r.production_ready},ensure_ascii=False))"

# 1.5 预检后立即复算 1.2：SHA 必须与 1.2 完全一致（证明预检零写入）
```

预期读数：

| 现场 | `ok` | `reasons` | 说明 |
|---|---|---|---|
| 现状预算（limit 20、无 P2 阶段） | `false` | `budget_total_mismatch`,`stage_allocation_missing`,`stage_budget_insufficient` | **预期拒绝**；修预算前发不出请求 |
| 已落盘修订后（40 / P2-LIVE 20） | `true` | — | `stage_remaining=20`、`total_remaining=24.9290555`、`requests_remaining=61`、`requests_planned=61`、`worst_case=0.839072`、`reserve_peak=0.5` |

## 2 签发（经理操作；本 runbook 不代签）

1. **预算修订落盘**：`budget.json` → `limit_cny=40.0` + `stages["P2-LIVE"]=20.0`；算术校验
   `0+0+15.4+3.0+1.57+20.0 = 39.97`，`39.97+0.03(history) = 40.00`（T201 遗留③）。
2. **正式 GO 落盘**：字段与候选一致，改 `nonce`（≥16、无空白、不留仓库副本）、
   `issued_utc`（= 签发时刻）、`expires_utc`（≤14 天），`budget_ledger_sha256` = §1.2 历史前缀
   `f4710b18…`，`scope.plan_sha256=02725aa7309fe2ca3a5bb05cf4d450cc276f361c80b11c3ac22df54ac6375d80`，
   `scope.max_requests=566`（≥ 计划总数 61；压到 560 会被 `go_max_requests_below_plan` 拒）。
   若经理决定压回 560 信封，必须同时把计划改成「删 V03 + D09 2 批」的 55 请求版本并重算 `plan_sha256`（见 §4.5）。
3. **进程环境（只设本次进程，不改 `.env`/全局）**：`MKTKB_PROJECT_TOTAL_LIMIT_CNY=40.0`
   （未设 → `env_total_limit_missing`；值≠预算 → `env_total_limit_mismatch`）。
4. 记录：GO SHA、预算 SHA（修订后）、账本历史前缀、`plan_sha256`、`run_id`。

## 3 空跑复演（现在可执行；零真实调用，只证明计划/预检/门序/产物）

```powershell
# 3.1 候选预算的内存快照（source=in-memory，绝不能当真实准入）
#     用 T201 候选快照的同一形状：total_limit_cny=40.0、stage_allocations 含 P2-LIVE=20.0、source="in-memory"
# 3.2 空跑（--out 必须是仓库外的新目录；不给 --snapshot 则读真实固定路径 → 现状下预检拒绝）
.\venv\Scripts\python.exe -B -X utf8 -m mktkb.evaluation.cli p2-run `
  --plan 'docs\reports\OBS-EVAL\P2\T206\PM\p2-pilot-plan-v0_2.json' `
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
- **2026-11-11 实测结果**（T206-prep 跑的是 **v0_1**，故 `requests_planned=55`；v0_2 未复跑空跑，
  预期同形、仅 `requests_planned=61`）：`{"ok": false, "status": "blocked",
  "stop_code": "ingest_failed", "requests_planned": 55, "requests_sent": 0,
  "production_ready": false, "execution": "dry_run"}`；`summary.json` 里
  `failure.stage=ingest`、`error_code=RuntimeError`、`requests.attempted=0`、
  `real_requests=0`、`billed_cny=0`；隔离库 `import_jobs.error_code=OCR_NOT_CONFIGURED`
  （D09 是 png，Mock 适配器 `ocr_disabled`+`_NoOcrGateway`）。→ 空跑证明「计划/预检/门序/产物」
  可用，同时把 G1/G3（无真实 OCR 传输）暴露在第一道关。
- 空跑**不是** pilot 证据：不产生真实费用、真实 trace 身份或分数。
- 纯契约复核（更轻、零写入；不读固定路径、不建 `.lock`）：
  `.\venv\Scripts\python.exe -B -X utf8 docs\reports\OBS-EVAL\P2\T206\PLAN-R1\validate-plan.py`
  —— 打印 v0_2 派生值/GO 绑定/预检（现状 vs 候选预算）/授权（`production_ready=false`）/
  负例（`go_plan_sha256_mismatch`/`go_max_requests_below_plan`/`go_expired`/
  `request_budget_insufficient`）与 ≤560 信封的 4 行对照。

## 4 真实 pilot 执行（代码入口已就绪；仍缺正式 GO）

前置（全部满足才允许发送）：正式 GO 落盘到 `P2_GO_PATH`；预算修订落盘（"40 / P2-LIVE 20"）；
§1 全绿；`MKTKB_PROJECT_TOTAL_LIMIT_CNY` 与预算一致；live 环境变量齐备（只列名字：
`MKTKB_MODEL_API_KEY`、`MKTKB_MODEL_BASE_URL`、`MKTKB_MODEL_NAME`、`DASHSCOPE_API_KEY`、
`DASHSCOPE_BASE_URL`、`MKTKB_OCR_SECRET_ID`、`MKTKB_OCR_SECRET_KEY`、`MKTKB_OCR_REGION`、
`MKTKB_OCR_DISABLED`）。

命令（**必须显式 `--mode live`**；dry-run 仍是默认）：

```powershell
.\venv\Scripts\python.exe -B -X utf8 -m mktkb.evaluation.cli p2-run `
  --plan 'docs\reports\OBS-EVAL\P2\T206\PM\p2-pilot-plan-v0_2.json' `
  --out '<仓库外新目录>' --cases '<pilot-cases.jsonl>' --mode live `
  --run-id 'p2-t206-pilot-20261111-01' `
  --dataset-version p2-pilot-20261111-v0.1 --label-version p2-pilot-labels-20261111-v0.1 `
  --ingest 'fixtures\acceptance\variants\V03_物品位置表_历史V1.xlsx' `
  --ingest 'fixtures\acceptance\normal\D01_物品位置表.xlsx' `
  --ingest 'fixtures\acceptance\normal\D03_市场部工作指南.docx' `
  --ingest 'fixtures\acceptance\normal\D09_物料领用通知.png' `
  --ingest 'corpus\enterprise-20261101\excel\E11_终端物料位置表_当前V2.xlsx'
```

入口行为（`p2_live.run_live_p2`）：

1. `load_live_env` 只读**进程环境**（不读 `.env`）；缺项 → `live_env_missing:<NAME>`，不建应用；
2. `open_live_gate` 用固定路径 GO/预算/共享账本开真实 `P2Gate`，要求
   `production_ready=True`、GO 已授权 `answer/index_embedding/query_embedding/rerank/ocr`；
3. 命中即**发送前**拒绝（稳定码来自 `p2_authorization`/`p2_live`，不是异常类名）：
   `live_requires_production_ready` / `path_missing`（GO 不存在）/ `go_expired` /
   `go_budget_total_mismatch` / `budget_stage_missing` / `env_total_limit_missing`（HTTP=0）
   —— 旧版 runbook 写的 `go_missing` 并不存在，实际码是 `path_missing`（T206-LIVE-R1/F4）。
4. 通过后：灌库（真实 OCR，`max_attempts=1`；每页的 `mode` 必须与计划项模型一致，否则
   `ocr_mode_plan_mismatch` 发送前拒绝）→ 逐轮 `begin/confirm_before_send/settle_*`
   → 产品内部每次 POST（query embedding **按批**、rerank、`query_expansion`）各自
   `begin_attempt`（同一账本、同一成本中心、同一 `item.requests` 配额）；
5. chat 的 usage 来自真实响应：拿到 → `settle_success`；零付费拒答 → `close_unused`
   （保守占用、不停止）；"作答但无 usage" → `usage_evidence_missing`（保守留账后停）。
   `query_expansion` 有独立计划项 `expand-*`（usage 缺失 → 该笔 `usage_evidence_missing` 后停）。

### 4.4 已知限制（R1 更新）

- **检索候选（retrieved）**：live 不再重放，改为从产品 answer 请求的 `evidence`（模型实际
  拿到的证据集合）捕获，**零额外调用/零额外付费**；捕获不到（rag 内核直答轮、零付费轮）仍为空，
  `citation_required` 照旧 fail-closed。要付费重放必须先补 replay 计划项 + **新 GO**。
- **计划项配额 = 真实 HTTP 请求/批**：`item.requests` 现在是"真实 POST 次数"的上界
  （embedding 一次 `embed()` 拆多批就各扣 1 次；rerank/OCR/`query_expansion` 各 1 次）。
  计划低估时在**发送前** `attempt_quota_exhausted` 停住，不偷偷多发。
  对 pilot 计划意味着：`ingest-index-embedding.requests` 是**批**上界（每批 ≤5 条文本），
  灌库规模超出就在发送前停 —— 这是"计划低估"的显式信号，**不得**改成按 `embed()` 调用计去绕过。
  **已实测并据此修订**（PLAN-R1）：4 份非 OCR 资料 = 30 批、D09 ≤6 批 → 计划取 **36**（见 §4.5）。
- **`query_expansion` 是真实发送**：空库/无证据且问题含词项时每轮至多 1 次，走 `expand-*`；
  计划已为 5 题各留 1 项（`requests=1`）。若产品某题扩展两次，第二次会因配额在发送前拒绝。
- `QaEngine` 未接 `index.budget`：rag 内核自建 provider 的路径会 fail closed 成
  `CHAT_UNAVAILABLE`（不发送、不付费）。当前路由只把 record 轮交给内核（无 LLM），pilot 5 题
  不受影响；若路由变化，需新计划项 + 账本接线。

### 4.5 批级配额清点（PLAN-R1 实测；签发前必读）

清点方法（零真实调用，可复跑 `docs/reports/OBS-EVAL/P2/T206/PLAN-R1/estimate.py`）：产品解析器
`parse_document` + `rag.chunking.build_chunks`（分块默认 900 字/6 单元/1 重叠）+ 批大小 5
（`product_adapter.py:1016`），逐文档独立分批（`rag/index.py:_embed_chunks` 每文档一次 `embed()`）。

| 资料 | 块 | 批 |
|---|---|---|
| `D01_物品位置表.xlsx` | 9 | 2 |
| `V03_物品位置表_历史V1.xlsx` | 9 | 2 |
| `D03_市场部工作指南.docx` | 2 | 1 |
| `E11_终端物料位置表_当前V2.xlsx` | 121 | 25 |
| `D09_物料领用通知.png`（1 页 OCR） | 未知 → 几何上界 26 | **≤6** |
| 合计（计划 v0_2 取上界） | — | **36** |

- D09 说明：1200×700 px、非规则表格 → text 模式、单 tile → 1 个 `image_text` 单元；块数 = `ceil(OCR 文本/900)`。
  上界取「6×6 px 字形、零行距」的 23,200 字 → 6 批；实际预期 1 批（≤4,500 字）。该值只影响 embedding 配额，
  **不影响** OCR 0.5 元与重试 0。
- 该上界导致总请求 61、`max_requests=566`，**超出旧「≤560」信封 6 次**（505+61）。560 是旧算术 505+55，
  批级口径下诚实下界已是 56。压回 560 的唯一配方：删 `V03`（−2 批）+ 把 D09 声明压到 2 批（≤9,000 字）
  → 55 请求 / `max_requests=560` / worst-case 0.826784；风险是 D09 文本 >9,000 字时第 3 批**发送前**被
  `attempt_quota_exhausted` 拒（`ingest_failed`，不多花钱但已烧 OCR 0.5 元，重跑要新计划+新 GO）。
- 因此：**默认按 v0_2（566）签发**；若经理要求严格 560，须同时改计划并重算 `plan_sha256`，不得只改 GO。

## 5 停止规则（触发即停；不重试、不补跑、不改计划续跑）

1. §1 任一检查不符（SHA 变化、GO 缺失/过期、预检 `ok=false`）。
2. 门控拒绝：`pre_send_refused` / `gate_error` / `center_budget_exceeded` / `request_limit` /
   `ledger_prefix_mismatch` / `production_not_ready` / `live_requires_real_gate` /
   `usage_evidence_missing`（作答但拿不到 usage）/ `attempt_accounting_mismatch`
   （逐次回执与计划/账本对不上）/ `attempt_quota_exhausted`（计划低估，发送前拒绝）。
3. 产品侧：首个 `product_service_error`、`turn_timeout`（60 s）、`adapter_error`、`ingest_failed`。
4. OCR：任一页失败/空片段/缺 usage、或运行时 `mode` 与计划项模型不一致
   （`ocr_mode_plan_mismatch`）→ 停（**重试 0**；重试=新计划+新 GO，并按次计费）。
5. 实测将超计划上界（`requests_planned=61`、`worst_case=0.839072`、单次 0.5）→ 停并报告。
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

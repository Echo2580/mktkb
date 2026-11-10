# P2-T206 准备交付（report）

- 角色：T206 准备助手（全新上下文）。真实调用 **0**；未读 `.env`/H1/H2；未联网；未写真实 budget/GO/账本；未 commit。
- 现场：`codex/p2-e2e` @ `61a9a8f`；账本 `1f46d1b9…`/958,277 B、预算 `084ba9ac…`/1,444 B；limit 20.00、已占 15.070944499999985、reservation/result 505/505、无 P2 阶段、`P2-LIVE-GO.json` 不存在。
- 结论：**计划与 GO 绑定的算术全部可证明，5 题 pilot worst-case = 0.826784 元 / 55 次请求**（≤2 元、串行、重试 0）；但**当前代码无真实 live 入口**（G1–G6），pilot 现在不可执行——是接线缺口，不是额度问题。

## 1 交付物

| 文件 | 说明 |
|---|---|
| `PM/P2-LIVE-readiness.md` | 证据清单、预算/请求/GO 前置、价格上界、fail-closed 点、R1 残余、N5、H2、缺口、风险回滚 |
| `PM/p2-pilot-plan-v0_1.json` | `P2RunPlan`（`p2-run-plan/v0.1`），26 项，`plan_sha256=d2baaa9cff9526faf5c87df099c2d9fbc71f168cd9ccc804d0f03a2bdefa73c2` |
| `PM/P2-LIVE-GO.CANDIDATE-DRAFT.json` | **DRAFT 候选 GO，不可用**：`authorize_p2` 下 `production_ready=false`；固定路径仍不存在 |
| `PM/runbook.md` | §1 只读检查、§2 签发、§3 空跑（已实测）、§4 真实执行（BLOCKED）、§5 停止、§6 核对、§7 回滚 |
| `report.md` | 本文件 |

> **2026-11-11 PLAN-R1 后**：签发用的计划与候选 GO 一律以 **v0_2**（`PM/p2-pilot-plan-v0_2.json`、
> `PM/P2-LIVE-GO.CANDIDATE-DRAFT-v0_2.json`，61 请求 / 566 / 0.839072 元）为准；v0_1 的 55 / 560 /
> 0.826784 是**旧口径**（`requests` 按 `embed()` 调用计），批级配额下会低估 D09 的 embedding 批次。
> 差异、依据与「≤560 信封」冲突见文末 `## PLAN-R1` 与 readiness §13。

## 2 5 题选择（全部来自公开冻结集合；原样行，无改写、无新标签）

| 类别 | case_id | 来源文件 | suite/stratum | 轮 | 必要导入 | 单题 worst-case |
|---|---|---|---|---|---|---|
| 精确 | `Q01` 城东店的宣传海报在哪里？ | `fixtures/evaluation/b0.jsonl` | b0/exact | 1 | `V03_物品位置表_历史V1.xlsx`→`D01_物品位置表.xlsx`（B0 配方：同槽 V1→V2） | 0.044224 |
| 正文 | `Q25` 领取活动物料需要哪些步骤？ | `fixtures/evaluation/b0.jsonl` | b0/text | 1 | `D03_市场部工作指南.docx` | 0.044224 |
| 拒答 | `RG005` 公司今年营收是多少 | `fixtures/evaluation/regression.jsonl` | regression/defect-t104（`no_answer`,`should_refuse=true`） | 1 | 无（越界题；合法拒答允许零 chat） | 0.044224 |
| 多轮 | `RG006` 那个海报呢（前轮：滨江店的宣传海报的数量是多少？） | `fixtures/evaluation/regression.jsonl` | regression/defect-t105 | 2 | `E11_终端物料位置表_当前V2.xlsx` | 0.088448 |
| OCR | `Q37` 物料领用通知图片要求先填写什么？ | `fixtures/evaluation/b0.jsonl` | b0/ocr（`requires_ocr=true`） | 1 | `D09_物料领用通知.png`（1 页、text 模式） | 0.544224 |

依据：① 5 类各一且都是 `fixtures/evaluation/*.jsonl` 的**冻结行**（不是从题干再造）；② 拒答用 `RG005`（越界指标应零 chat 拒答，正好验证「合法拒答不补调用」；若改用 acceptance `N01` 需自己合成 CaseSpec，非冻结字节，故不采用——T207 的 N8 仍按 acceptance 题集）；③ 多轮用 `RG006`：2 轮真实逐轮、末轮只答字段值，并带禁止值（位置/标识）可判串字段；④ OCR 用 `Q37/D09`（1 页）而非 D07（8 页）/D08（2 页）：pilot 只需证明真实 OCR 链路与页级计费，D07–D10 的 12 页仍归 T207；⑤ `Q01` 带 V03→D01 版本槽，顺带覆盖「同文档不同 version 不得串」且不额外付费。
5 行按 `Q01,Q25,RG005,RG006,Q37` 顺序以 `\n` 拼接（保留末尾换行）= **4,712 B**，SHA-256 `a3878212fa1c114eb5a8c280bcf01c74d0131744c6aa568a2edfd36302652c79`；`CaseSpec`+`validate_case` 5/5 通过，`case_questions` 合计 **6 轮**。

## 3 成本与请求估算（计划内 26 项）

| 操作 | 请求 | 单次上界 | 小计 |
|---|---|---|---|
| index_embedding（5 份文档聚合项） | 30 | 0.002048 | 0.061440 |
| query_embedding / rerank / query_expansion / answer（各 6 轮） | 6+6+6+6 | 0.002048 / 0.0048 / 0.018688 / 0.018688 | 0.012288 / 0.028800 / 0.112128 / 0.112128 |
| ocr（D09 第 1 页，text） | 1 | 0.5 | 0.500000 |
| **合计** | **55** | — | **0.826784** |

- 串行单次峰值预留 = **0.5**（OCR 一页，`max_request_cny=0.5`）；成功估价 0.5648（OCR 固定价占大头，仅分列，不参与准入）。
- `plan.max_requests=560=505+55`（累计口径：未重置 505、未提高 1000 硬顶）。
- 实测锚点：空跑时 3 份文档产生 3 次 embedding 调用 / 20 个文本（批 ≤10）；同口径外推 5 份 ≤30 次，故 30 是含余量上界（不是「1 文档=1 请求」的臆测）。

## 4 与预授权额度对照

| 项 | 预授权（主人 2026-11-10） | 本计划 | 判定 |
|---|---|---|---|
| P2 新增消费 | ≤20（可提至 ≤50） | 阶段 20；pilot 占用 0.826784 | 通过 |
| 项目总上限 | 候选 20→40（不足可 20→70） | 40.00（39.97+0.03 闭合） | 通过 |
| 成本中心 | 9/6/3/2 = 20 | 同（需要 0.326784 / 0.5 / 0 / 0） | 通过 |
| 累计请求硬顶 | 1000（预授权可提至 ≤2000） | **不提高**：`max_requests=560`，pilot 55 | 通过 |
| GO 有效期 | ≤14 天 | 候选 13 天（2026-11-11→2026-11-24） | 通过 |
| 模型/价格 | 已核白名单 | deepseek-flash / text-embedding-v4 / gte-rerank-v2 / 腾讯 OCR | 通过 |

## 5 已证明（纯契约离线校验，可复跑）

1. 计划通过 `P2RunPlan` 严格校验：`worst_case=0.826784`、`reserve_peak=0.5`、`total_requests=55`、26 项。
2. 预检 vs 现状预算 → 拒绝：`budget_total_mismatch`,`stage_allocation_missing`,`stage_budget_insufficient`；vs 候选预算（40/20）→ `ok`，`stage_remaining=20`、`total_remaining=24.9290555`、`requests_remaining=55`。
3. `authorize_p2`（内存 GO+预算+快照）→ 成立但 `production_ready=false`（`go_sha256=4d8abdd8…`）⇒ **候选 GO 不可用**。
4. 负例全拒：`go_expired`、`go_not_yet_valid`、`go_operation_unauthorized`(删 ocr)、`go_max_request_cny_below_plan`(0.1)、`go_max_requests_below_plan`(100)、`go_max_requests_over_hard_cap`(1200)、`budget_stage_missing`、`budget_total_mismatch`(limit 20)、`go_plan_sha256_mismatch`、`go_plan_id_mismatch`、`legacy_go_document`。
5. 空跑（`cli p2-run` + 内存快照 + Mock，零真实调用）：`blocked/ingest_failed`、`requests_sent=0`、`real_requests=0`、`billed_cny=0`；隔离库 `import_jobs.error_code=OCR_NOT_CONFIGURED`（D09 png）。

## 6 阻断缺口（pilot 不可执行；详见 readiness §9）

- **G1** 适配器恒 Mock（`is_mock=True`、`provider_mode="offline"`、OCR 走 `_NoOcrGateway`）；**G2** 无 live 驱动/CLI（`p2-run` 只产 dry-run 授权；`P2Gate.open`/`authorize_p2` 在 `backend/src` 无生产调用点）。
- **G3** OCR 传输层写死 `MockOcrTransport`（真实 OCR 不可用，Q37 依赖它）；**G4** 无真实 `UsageEvidence`（chat/embedding/rerank 结算需要它，`ProductTurn` 不含 usage）。
- **G5** 成本归属未定（RAG provider `budget` 钩子未接；接了不带 `cost_center` 会被 `center_accounting_inconsistent` 拒）；**G6** 请求累计只数账本 reservation，而 runner 只为 `answer` 逐轮 `begin` → 账本计数少于真实底层尝试。

## 7 未覆盖 / 风险

- 未跑真实模型/OCR/embedding/rerank、H2、Ragas、Langfuse、浏览器、全仓；未复跑 T201–T205 套件（§3.9 纪律）。`provider_billed_cny=null`：本文件金额是**保守占用**口径，不是账单。
- 候选 GO 与正式 GO 字段集相同（schema 无 DRAFT 标记）：唯一防线是「固定路径 + 经理签发」，禁止拷贝（runbook §8）。
- R1 残余：gate 无法识别伪造 retrieved；pilot 驱动不得把引用当 retrieved/evidence；rag 候选是召回并集，可宽于 fused 返回。
- N5：pilot 只 OCR 1 页且重试 0（0.5 元上界）；**不得**外推到「12 页可重试」（重试即 9 次/4.5 元）。H2 目标（≥24/30 且硬失败 0）已绑定但 pilot 不涉及；`gate_v0_3` 仍 unapproved，放行等 T209。

## 8 复跑入口

```powershell
# 计划/GO 纯契约校验（零真实调用；脚本在 %TEMP%/p2-t206-prep/，不在仓库）
.\.venv\Scripts\python.exe -B -X utf8 %TEMP%\p2-t206-prep\step2.py   # 预检 + 授权 + 负例
# 空跑（只证明计划/门序/产物，不是 pilot 证据）
.\.venv\Scripts\python.exe -B -X utf8 -m mktkb.evaluation.cli p2-run --plan docs\reports\OBS-EVAL\P2\T206\PM\p2-pilot-plan-v0_1.json --snapshot <快照.json> --out <仓库外目录> --cases <pilot-cases.jsonl> --ingest <5 文件>
```

## 9 T206-LIVE 后续（2026-11-11）

G1–G6 的**代码入口**已在 T206-LIVE 包补齐：`mode="live"` 适配器、固定路径真实门 +
`p2-run --mode live`、真实 OCR 传输、真实 usage 证据（缺 usage fail-closed）、逐次尝试的
成本中心与请求计数（`P2Gate.begin_attempt`）。**pilot 仍不可执行**：正式 GO 未签发、预算未修订；
且 live 不重放检索候选（需新计划+新 GO 才能让 `citation_required` 通过）。
详见 `docs/reports/OBS-EVAL/P2/T206-LIVE/{report.md,evidence/}`。

## PLAN-R1（2026-11-11，按批级配额把 plan/GO 修订为 v0.2；零真实调用）

- 角色：PLAN-R1 计划修订助手（全新上下文）。真实调用 0；未读 `.env`/H1/H2；未写真实 budget/GO/账本；未 commit。
- 起因：T206-LIVE-R1 把 `item.requests` 改成「真实 POST/批」（batch=5）。v0.1 的 `ingest-index-embedding.requests=30`
  在新口径下是「30 批」——把 D09 算进去就不够，而 v0.1 的 30 恰好只覆盖 4 份非 OCR 资料。
- 离线清点（产品解析器 + chunker + live 分块默认 900/6/1；证据 `PLAN-R1/estimate.py`/`estimate-out.txt`）：
  `D01` 9 块/2 批、`V03` 9 块/2 批、`D03` 8 段→2 块/1 批、`E11` 121 行→121 块/25 批（4 份合计 141 块 = **30 批**，
  与 T206-prep 空跑实测「3 份文档 20 个文本」= 9+9+2 逐份吻合）；
  `D09` 1200×700 px、非规则表格 → **text 模式、单 tile → 1 个 unit**，批数只由 OCR 文本长度决定。
- D09 假设（结果未知，不猜低）：几何上界 `floor(1200/6)×floor(700/6)` = **23,200 字**（6×6 px 字形、零行距）
  → 26 块 → **6 批**；实际预期 1 批（≤4,500 字）。计划取 6 批 = 上界。
- 新值：`index_embedding` **36** 批；总请求 **61**（36+6+6+6+6+1）；`max_requests=566`（505+61）；
  worst-case **0.839072 元**（≤2 元）；串行峰值 0.5（OCR 一页）；成功估价 0.5666。
- **超出「≤560」信封 6 次请求**（如实报告）：560 是旧算术 505+55；批级口径下的诚实下界已是 30（4 份实测）
  +1（D09 最省）+24+1 = **56 > 55**。压回 560 的唯一办法 = 删 V03（−2 批）且把 D09 声明压到 2 批（≤9,000 字）
  → 55 请求 / 560 / 0.826784（`validate-plan-out.txt` 已机械验证）；代价：D09 OCR 文本若 >9,000 字，第 3 批在
  **发送前**被 `attempt_quota_exhausted` 拒（fail-closed，但那时 0.5 元 OCR 与已发批次已花掉）。
  → 建议经理接受 566（仍 ≤1000 硬顶、账本余量 495），或明确下令走该缩量配方。
- 产出：`PM/p2-pilot-plan-v0_2.json`（26 项、`plan_sha256=02725aa7309fe2ca3a5bb05cf4d450cc276f361c80b11c3ac22df54ac6375d80`）
  `+ PM/P2-LIVE-GO.CANDIDATE-DRAFT-v0_2.json`（DRAFT、绑 v0_2 sha、账本前缀 `f4710b18…`、13 天、`production_ready=false`）
  `+ PM/P2-LIVE-readiness.md` §13、`PM/runbook.md` 批级更新与 §4.5、`PLAN-R1/{estimate,validate-plan}.py` 与两份输出。
- 校验（零真实调用）：`P2RunPlan` 严格通过；预检 vs 现状预算仍拒（`budget_total_mismatch`/`stage_allocation_missing`/
  `stage_budget_insufficient`）、vs 候选预算 `ok` 且 `requests_remaining=61`；`authorize_p2` 成立但 `production_ready=false`
  （`go_sha256=f2c16793…`）；负例：v0.1 计划 + v0.2 GO → `go_plan_sha256_mismatch`、GO `max_requests=560` →
  `go_max_requests_below_plan`、过期 GO → `go_expired`、`max_requests=560` + 61 请求 → 预检 `request_budget_insufficient`。
- 未做：真实调用/OCR/H2/全仓测试；pilot 仍不可执行（正式 GO 未签发、预算未修订）。

## 更正（2026-11-11，pilot 后经理记录）

1. **作废**「Q01 覆盖同槽 V1→V2」：独立复核表明 V03 与 D01 被导入为两个独立 active 文档（各 version=1），B0 同槽 V1→V2 未复现；Q01 返回 conflict 属播种/导入配方问题，不代表版本串值已覆盖。要取得版本槽证据需 T207 新计划+新 GO 重新播种。
2. pilot 的 `run_result` 是 **answer 单侧范围**（6 次 answer 预留）；全部底层尝试为 42 次（见 gate.json.attempts/receipts）。
3. 结算口径：settled=0.5713583、reserve=0.6893120；其中 0.056064 为 3 笔零 chat 拒答的全额保守留账（清单价真实约 0.5152943）；`summary.settled_failure` 与账本 status=failed / requests.jsonl billed 的字段口径待统一（T207 前）。
4. 预算元数据两字段已修（remaining_at_start 39.97、revised_at 实际签发时刻）；limit/stages/history 未变，签署版另存。
5. `output_valid=false` 是 dataclass 默认（非质量信号）；`paid_attempt` 仅拒付/拒答轮出现。

# T207 正式矩阵 runbook（执行 · 停止 · 核对 · 回滚）

- 适用：`PM/T207-plan-v0_1.json`（`plan_sha256=0b4e55a4cd3a46f968e89fe495ffca3c6931c8f49f1f258a3dd753f83e24a194`，254 请求 / worst-case 8.127376 元 / `max_requests=1200`）
  + 重发后的 `PM/T207-GO.CANDIDATE-DRAFT.json`（**不可用**，等经理落盘到固定路径）。
- **当前状态（2026-11-11 T207-FIX-A 交付后）**：计划通过真实快照预检（`ok=true`、`stage_remaining=19.4286417`、
  `requests_remaining=653`）；三处前置已解决：
  1. 请求硬顶已落盘 1600（T207-FIX-B），公开计划按经理决定重发为 `max_requests=1200`（sha 见上）；
  2. 驱动/生成器已交付：`--ingest-plan`（版本槽）、`cases/{R1,R2,R3}.jsonl`、`p2-h2-plan`、`p2-score`、
     `p2-matrix`、`p2-u-controls`、`tools/p2_live_execute.py`（全部有离线用例）；
  3. 固定路径 `P2-LIVE-GO.json` 仍指向 T206 pilot 计划（`02725aa7…`）：经理必须按**新 sha** 重签，否则
     被 `go_plan_id_mismatch` 拒（T206 pilot 的 `plan_id` 不同；旧文写 `go_plan_sha256_mismatch` 已由
     T207-FIX-A 独立验收纠正——sha 不匹配只在 plan_id 相同时才会被先撞到）。fail-closed，符合预期。
- **顺序约束（务必按此顺序）**：R3 → R2 → R1。计划含 12 页 OCR（上界 5.65），ocr 中心只有 6.5；
  R1 跑完后 ocr 已占 6.15，再授权必然 `center_budget_insufficient:ocr`（请求窗口其实还够）。
  反证见 `evidence/validate-plan-out.txt` 的 `reorder_control` 与 `T207-cost-and-quota.md` §3.1。
- 纪律：串行、自动重试 **0**、单轮 60 s 硬截止；首个服务/授权/预算/数据完整性错误即停后续付费；答案 `fail` 继续采集同一已批准矩阵（不挑题重跑）；不读 `.env`（只由 `tools/p2_live_execute.py --env-file` 显式注入）、不读 H2 明文、不改共享账本/预算/历史。

## 1 执行前只读检查（每次执行，逐项；任一不符即停）

```powershell
cd 'D:\GPT项目\市场部AI知识库'
git rev-parse --abbrev-ref HEAD; git rev-parse --short HEAD

# 1.1 账本/预算 SHA（本包基线；任何变化都说明有人写过，停）
.venv\Scripts\python.exe -B -X utf8 -c "import hashlib,pathlib;L=pathlib.Path('docs/evidence/LOCAL-R1-20261101/budget/live-ledger.jsonl');B=L.with_name('budget.json');print(hashlib.sha256(L.read_bytes()).hexdigest());print(hashlib.sha256(B.read_bytes()).hexdigest())"
#   期望：6b053520a2358f942279c9e6abbdb3b868e729b6df6b8397c132fce666ee345c  (1,050,298 B)
#        79b21700b630be92148e2a8498ed47386dab08d6daa401601dc3d22a910b1a9e

# 1.2 正式 GO 的 SHA（必须等于经理签发记录值）
.venv\Scripts\python.exe -B -X utf8 -c "import hashlib,pathlib;p=pathlib.Path('docs/evidence/LOCAL-R1-20261101/PM/P2-LIVE-GO.json');print(p.exists() and hashlib.sha256(p.read_bytes()).hexdigest())"

# 1.3 只读契约复核（真实快照；不预留、不发请求）
.venv\Scripts\python.exe -B -X utf8 docs\reports\OBS-EVAL\P2\T207\evidence\validate-plan.py

# 1.4 预检后立即复算 1.1（必须逐值相同，证明预检零写入）
```

预期读数：`preflight_real_snapshot.ok=true`、`requests_planned=254`、`requests_remaining=653`、
`worst_case=8.127376`、`reserve_peak=0.5`、`production_ready=true`（快照来自固定路径）。
若 `reasons` 出现 `budget_total_mismatch`/`stage_allocation_missing` → 预算还没按 40/20 落盘，停。

## 2 签发（经理做；本 runbook 不代签）

1. 预算：`limit_cny=40.0`、`stages["P2-LIVE"]=20.0`（当前已是；**中心重排不进预算文件**，理由见 cost §4）。
2. GO：字段与 `PM/T207-GO.CANDIDATE-DRAFT.json` 一致，改 `nonce`（≥16、无空白、不留仓库副本）、
   `issued_utc`=签发时刻、`expires_utc` ≤ +14 天、`budget_ledger_sha256`=历史前缀 `f4710b18…`、
   `scope.plan_sha256=0b4e55a4cd3a46f968e89fe495ffca3c6931c8f49f1f258a3dd753f83e24a194`、`scope.max_requests=1200`、
   `scope.cost_centers_cny = 8.5/6.5/3/2`、`max_request_cny=0.5`。落盘后记 SHA。
3. 进程环境：**只经** `tools/p2_live_execute.py --env-file <工作区外文件>` 注入（包装器自己读文件、只认白名单
   变量名、缺项只报变量名并 fail-closed；从不打印值）。`MKTKB_PROJECT_TOTAL_LIMIT_CNY=40.0` 缺 → `env_total_limit_missing`；
   不一致 → `env_total_limit_mismatch`。**不要**用 `set` 把凭据写进终端历史，也不要依赖 `.env`。
4. live provider 环境变量（只列名字，不写值）：`MKTKB_MODEL_API_KEY`、`MKTKB_MODEL_BASE_URL`、`MKTKB_MODEL_NAME`、
   `DASHSCOPE_API_KEY`、`DASHSCOPE_BASE_URL`、`MKTKB_OCR_SECRET_ID`、`MKTKB_OCR_SECRET_KEY`、`MKTKB_OCR_REGION`、
   `MKTKB_OCR_DISABLED`（必须未禁用）。H2 另需 `MKTKB_P2_HOLDOUT_ROOT`、`MKTKB_P2_HOLDOUT_KEY_FILE`。
5. 记录：GO SHA、预算 SHA、账本历史前缀、`plan_sha256`、三个 `run_id`（R1/R2/R3 各一）。

## 3 三次运行（顺序固定 R3 → R2 → R1；每次 run 新开一扇门）

三次 run 用**同一份计划文件**（sha 必须一致）与**同一张 GO**，但每次都是独立进程 + `open_live_gate` 新门；
灌库用 `--ingest-plan`（同槽新版本 / 不发布），题集用 `cases/{R1,R2,R3}.jsonl`；
凭据只经 `tools/p2_live_execute.py --env-file` 注入（默认不读 `.env`）。

**R3 电话冲突**（1 case / 6 请求 / worst 0.048320）——先跑：它不消耗 ocr 中心，给 R2/R1 留出窗口。

```powershell
.venv\Scripts\python.exe -B -X utf8 tools\p2_live_execute.py ^
  --env-file "<工作区外>\p2-live.env" -- p2-run ^
  --plan   "docs\reports\OBS-EVAL\P2\T207\PM\T207-plan-v0_1.json" ^
  --out    "<仓库外新目录>\R3" ^
  --cases  "docs\reports\OBS-EVAL\P2\T207\cases\R3.jsonl" ^
  --ingest-plan "docs\reports\OBS-EVAL\P2\T207\PM\T207-ingest-plan-R3.json" ^
  --mode live --run-id "p2-t207-r3-20261111-01" ^
  --dataset-version p2-t207-b0nc-20261111-v0.1 --label-version p2-t207-labels-20261111-v0.1
```

**R2 版本槽 + 冲突**（2 case / 15 请求 / worst 0.102784）：`--cases ...\R2.jsonl`、
`--ingest-plan ...\T207-ingest-plan-R2.json`（V03 建槽 → D01 v2 → V04 v3 只处理不发布 → V01 发布）、
`--out <仓库外>\R2`、`--run-id p2-t207-r2-20261111-01`。

**R1 主矩阵**（52 case / 242 请求 / worst 7.994704）——最后跑：

```powershell
.venv\Scripts\python.exe -B -X utf8 tools\p2_live_execute.py ^
  --env-file "<工作区外>\p2-live.env" -- p2-run ^
  --plan   "docs\reports\OBS-EVAL\P2\T207\PM\T207-plan-v0_1.json" ^
  --out    "<仓库外新目录>\R1" ^
  --cases  "docs\reports\OBS-EVAL\P2\T207\cases\R1.jsonl" ^
  --ingest-plan "docs\reports\OBS-EVAL\P2\T207\PM\T207-ingest-plan-R1.json" ^
  --mode live --run-id "p2-t207-r1-20261111-01" ^
  --dataset-version p2-t207-b0nc-20261111-v0.1 --label-version p2-t207-labels-20261111-v0.1
```

- `T207-ingest-plan-R1.json` 的 12 个 source = 版本槽 3 步 + D02…D06 + D07…D10（OCR 12 页）；
  第 3 版 `publish=false`（U01 要的「未发布新版」）。**不得**用 `allow_same_name` 冒充版本（会建第二份文档）。
- `--ingest` 与 `--ingest-plan` 互斥（argparse 拒绝，退出码 2）；旧 `--ingest` 路径逐字未变。
- 每次 run 后按 §5 核对；三次 run 的产物分别落在 `<仓库外>\{R1,R2,R3}`，只把 §5 列的文件复制进仓库。
- 请求/资金上限：单次 worst 8.127376（计划上界）≤ 19.4286417；累计 263 请求 / 8.145808 元。

## 4 停止规则（触发即停；不重试、不补跑、不改计划续跑）

1. §1 任一检查不符（SHA 变化、GO 缺失/过期、预检 `ok=false`）。
2. 门控拒绝（稳定码）：`path_missing`/`path_not_fixed`、`go_expired`、`go_plan_id_mismatch`（固定路径那张旧 GO
   首先是 plan_id 不同）、`go_plan_sha256_mismatch`、
   `go_max_requests_below_plan`、`go_cost_center_below_plan`、`go_operation_unauthorized`、`budget_stage_missing`、
   `budget_history_mismatch`、`env_total_limit_missing`/`env_total_limit_mismatch`、`live_requires_production_ready`、
   `live_requires_real_gate`、`center_budget_exceeded`、`request_limit`、`ledger_prefix_mismatch`、
   `attempt_quota_exhausted`（计划低估，发送前）、`attempt_accounting_mismatch`、`usage_evidence_missing`。
3. 产品侧：首个 `product_service_error`、`turn_timeout`（60 s）、`adapter_error`、`ingest_failed`。
4. OCR：任一页失败/空片段/缺 usage，或运行时 `mode` 与计划项模型不一致（`ocr_mode_plan_mismatch`）→ 停（**重试 0**）。
5. 金额/请求即将越过计划上界（`requests_planned=254`、`worst_case=8.127376`、单次 0.5）→ 停并报告。
6. 数据完整性：`provider_network_detail_mismatch`、`artifact_validation` → 停（产物仍写全）。
7. 答案 `fail`（质量不达标）**不**停：继续同一已批准矩阵，逐条留证。

## 5 产物落位与核对（每次 run 之后）

1. **复制到仓库**：`<out>\{run_manifest.json,summary.json,run_result.json,gate.json,cases.jsonl,dataset.jsonl,requests.jsonl}`
   → `docs/reports/OBS-EVAL/P2/T207/<run_id>/`；trace 库与业务库**不复制**（留仓库外）。
2. **账本增量**：新增 `reserved`/`result` 条数（R1 期望 **≤242/≤242**、R2 15/15、R3 6/6）、`center_accounted_cny` 增量
   （R1 上限 `answer_retrieval +2.344704`、`ocr +5.65`；R2 `answer_retrieval +0.102784`；R3 `+0.04832`）、失败笔是否按上界保守留账；
   `billed` 是**结算口径**，不是供应商账单（`provider_billed_cny` 仅在拿到真实 usage 时有值）。
   `billed` 是**结算口径**，不是供应商账单（`provider_billed_cny` 仅在拿到真实 usage 时有值）。
   - **为什么是「≤」而不是「=」**：242 = 208（52 回合 × 4）+ 22（计划里 index_embedding 的**上界**：11 非 OCR 批 + 11 OCR 文本上限批）+ 12（12 页 OCR）。
     产品**只给当前有效版建索引**、并按 content_sha256 复用 embedding 缓存（每次发布后的 `notify_knowledge_changed` 只嵌入增量），
     所以真实 embedding POST 数**小于等于**计划声明的 22（H2 的同类实测：声明包络 68，实测 14；
     见 cost §5 与 `T207-FIX-A-R1/evidence/h2-state-out.json`）。OCR 12 页按真实转写文本可能只有 4 批（`estimate-out.json` 的
     `transcript_total_batches=4`），计划按 2,700 字/页上限保守写 11。**核账以账本 reservation 为准**，不要拿 242 当预期值。
3. **产物内部一致**：`summary.requests` 与 `network.outbound_attempts` 及其 `detail` 相等；
   `gate.attempts`/`gate.receipts` 与 `attempt_audit.expected_reservations == gate_reserved`。
4. **身份/证据**：`run_manifest.config_hash` 完整、trace 六字段、`citation_evidence.complete`、
   `gate.real_sends_allowed`、`cases.jsonl` 的 `product.evidence`/`retrieved`。
5. **失败身份**：`failure.{stage,case_id,turn,item_id,ticket}`（含在飞 ticket 的 request_id/reservation_id）。
6. **评分/决策**（T207-FIX-A 已交付）：

```powershell
# 公开：逐题打分 -> scorecard.json + case_scores.json + p2_decision.json
.venv\Scripts\python.exe -B -X utf8 -m mktkb.evaluation.cli p2-score ^
  --run-dir "<仓库外>\R1" ^
  --cases "docs\reports\OBS-EVAL\P2\T207\cases\R1.jsonl" ^
  --document-codes "docs\reports\OBS-EVAL\P2\T207\cases\document-codes.json"
```

- 文档名 -> doc_code 的映射显式给（`--document-codes`），不猜；缺题/error/未执行如实出 block（not_executed/case_error）。
- `p2_decision.json` 的判定必然是 `gate_config_unapproved`（unknown）→ 结论只能写"执行完成 + 观测值"，不得写"质量达标/放行"。
- 三次 run 都跑完后再组观测矩阵（非 release）：

```powershell
.venv\Scripts\python.exe -B -X utf8 -m mktkb.evaluation.cli p2-u-controls --out "<仓库外>\u-controls.json"
.venv\Scripts\python.exe -B -X utf8 -m mktkb.evaluation.cli p2-matrix ^
  --case-scores "<仓库外>\R1\score\case_scores.json" ^
  --case-scores "<仓库外>\R2\score\case_scores.json" ^
  --case-scores "<仓库外>\R3\score\case_scores.json" ^
  --u-controls "<仓库外>\u-controls.json" ^
  --out "<仓库外>\matrix_observation.json"
```

- 矩阵声明 `composition=multi_run_scenario_isolated`、`release_decision=false`、`gate_config_unapproved`；
  U01 取 R2 真实 smoke（R），U02–U10 取 `test_t09_mutation.py` 本地控制（L），逐行标 basis。
- **不要**把 citations 当 `retrieved`（R1 残余①）；`p2-u-controls` 只跑既有测试，不改它。

## 6 失败归因表（run 后按此填，不猜）

| 稳定码 | 层 | 首查 |
|---|---|---|
| `ingest_failed` + `ocr_mode_plan_mismatch` | 计划/OCR | 计划 `ocr-*-p*` 的 model 与产品判定是否一致 |
| `ingest_failed` + `OCR_NOT_CONFIGURED` | 环境 | `MKTKB_OCR_DISABLED` 是否被设成禁用 |
| `attempt_quota_exhausted` | 计划低估 | 哪一类 item 的第几次；重算后重签计划 |
| `attempt_accounting_mismatch` | 计数 | gate 累计 vs 本 run 期望（fix-scope §F7） |
| `usage_evidence_missing` | 结算 | 该轮产品是否真作答但没回 usage |
| `pre_send_refused` + reason | 授权/预算 | 按 reason 查 GO/预算/中心/请求 |
| `center_budget_exceeded` | 预算 | 哪个中心、已占多少（账本 `center_accounted_cny`） |
| `product_service_error`/`turn_timeout` | 产品 | `failure.case_id/turn` 的 `turns[].error_code` |
| `provider_network_detail_mismatch` | 观测 | `network.detail` 分解与顶层计数 |

## 7 硬顶与计划重发（T207-FIX-A 已完成）

1. 硬顶 1600 已在 T207-FIX-B 落盘（`p2_contracts.HARD_MAX_REQUESTS` 与 `live_authorization.MAX_GO_REQUESTS` 同值）；
2. 公开计划 `max_requests` 已由 1000 重发为 **1200**（`build-plan.py` 的 `MAX_REQUESTS`），新
   `plan_sha256=0b4e55a4…a194`；负例改为 `hard_cap_over_1600`（1601 拒、1600 可建、1200 显式可建）；
3. 授权窗口（每 run 新门）：R3 801 / R2 807 / R1 822 ≤ 1200（顺序见 §3、cost §3.1）；
4. H2 计划 `max_requests=1100`；T208 judge 1200；T900 independent 1400；
5. **到值即停**：累计请求到 1600 或任一计划自身上限即停，不静默加计划。

## 8 H2（受限）执行与跑后审计

前置：`MKTKB_P2_HOLDOUT_ROOT`/`MKTKB_P2_HOLDOUT_KEY_FILE` 只在**受控进程**注入；H2 语料包声明（fix-scope §F2）
已就位（D01–D06 + V01–V07，requires_ocr 全 false）；H2 case 元数据（case_id/轮数）由经理按 custodian-report
准备在**工作区外**；题干/答案/密文/key 一律不进仓库、不进日志。

1. **生成计划**（封存/受控进程；stdout 只回 sha 与计数，计划文件必须写在工作区外）：

```powershell
.venv\Scripts\python.exe -B -X utf8 -m mktkb.evaluation.cli p2-h2-plan ^
  --cases-metadata "<工作区外>\h2-cases-metadata.json" ^
  --holdout-manifest "docs\evaluation\p2-holdout-v2.manifest.json" ^
  --ingest-batches 14 --plan-out "<工作区外>\h2-plan.json" ^
  --plan-id P2-T207-H2-20261111 --created-utc "2026-11-11T08:30:00+08:00"
```

- **T207-FIX-A-R1 阻断 2 已闭环**：`--plan-id` 的 CLI 默认值、候选 GO 的 `scope.plan_id`、本命令三处同值
  `P2-T207-H2-20261111`（单一来源 `p2_holdout_plan.H2_DEFAULT_PLAN_ID`）；旧文写 `P2-H2-20261111` 会与 GO 不匹配、
  签发后被 `go_plan_id_mismatch` 拒。
- **B = 14**（12 份资料的实测批数；推导与证据见 cost-and-quota §5 与 `T207-FIX-A-R1/evidence/h2-state-out.json`）。
  上界口径 20；生成器只校验 `B <= 68`（`H2_MAX_INGEST_BATCHES`）。
- 元数据 schema：`{schema_version:"p2-h2-cases-metadata/v0.1", dataset_version, cases:[{case_id, turns}]}`；
  生成器与 manifest 交叉校验 30 题 / 36 回合 / histogram / multi_turn 分层，任一不符即拒（`case_count_mismatch` 等）。
- **预期生成物**：`items=145`（144 回合项 + 1 个 `index_embedding`）、`total_requests=158`（144 + 14）、
  `page_count=0`（无 OCR 项）、`worst_case_cny=1.620736`、`center_needs_cny.answer_retrieval=1.620736`。

2. 经理按新 `plan_sha256` 签 H2 GO（`max_requests=1100`，中心 8.5/6.5/3/2）并落盘固定路径。
3. **执行**（同样只经包装器注入环境；灌库用仓库内的 H2 ingest-plan）：

```powershell
.venv\Scripts\python.exe -B -X utf8 tools\p2_live_execute.py ^
  --env-file "<工作区外>\p2-holdout.env" -- p2-run ^
  --plan "<工作区外>\h2-plan.json" --out "<工作区外>\H2" --visibility holdout ^
  --holdout-manifest "docs\evaluation\p2-holdout-v2.manifest.json" ^
  --mode live --run-id "p2-t207-h2-20261111-01" ^
  --ingest-plan "docs\reports\OBS-EVAL\P2\T207\PM\T207-ingest-plan-H2.json"
```

- `--visibility holdout` 强制 `purge_traces=True`；run 产物只留聚合（`holdout_aggregate.json`），不写 case_id/题干。
- **H2 ingest-plan**（`p2-ingest-plan/v0.1`，T207-FIX-A-R1 新增）：12 个 source，**顺序即语义**，不得重排：

| # | 文件 | 上传名 / `document_ref` | publish | 目的（custodian-report §6 假设） |
|---|---|---|---|---|
| 1 | V03 历史V1 | name=`D01_物品位置表.xlsx`（建槽） | 是 | H1「仅 V03 为历史版」 |
| 2 | D01 | `document_ref` 同上 → v2 | 是 | 当前版（B区1号货架第二层） |
| 3 | V04 新版V3 | `document_ref` → v3 | 是 | H2「V04 已发布为 V3」 |
| 4 | V05 新版V3_移除P01 | `document_ref` → v4 | 是 | H5「V05 发布删行」（9→8 个单元） |
| 5 | D02 | 独立资料 → v1 | 是 | 电话旧值 010-00000001 |
| 6 | V06 新电话 | `document_ref` → v2 | 是 | H4「V06 取代 D02」（010-00000088） |
| 7–10 | D03 / D04 / D05 / D06 | 各自独立资料 | 是 | 基础语料 |
| 11 | V01 临时位置通知 | 独立资料 | 是 | H3「V01 与 D01 双有效冲突」（D区暂存柜） |
| 12 | V07 独立通知 | 独立资料 | 是 | H5「V07 仍有效」（B区1号货架第二层） |

  **预期终态**（离线实测，`T207-FIX-A-R1/evidence/h2-state-out.json`）：D01 槽 latest=4 / active=4，
  v1(V03)=superseded、v2(D01)=superseded、v3(V04)=superseded（有 published_at）、v4(V05)=published；
  D02 槽 latest=2 / active=2（v2=V06）；D03–D06、V01、V07 各 v1 published；产品 revision=12、索引 8 份资料 / 21 chunk。
  五条假设**在同一 KB 状态**逐条成立（`hypotheses.*.hold = true`），但 **H2 只能按「版本历史」读**：V05 发布为 v4 后
  v3 不再是当前有效版（若某题要求「v3 就是当前版」，它与 H5 无法同库共存，需拆成两次 run——见 T207-FIX-A-R1 report §3）。
  **V02 不入 H2 包**：五条假设都不引用它，而它的电话（010-00000099）与 V06 的（010-00000088）不同，
  入包会凭空造出一个未声明的电话冲突；若保管方确认某题引用 V02，最小替代是加 1 个 source（B=15、165 请求）。
  **灌库后必须核对**：账本 `index_embedding` 增量 **≤14**（超过即 `attempt_quota_exhausted` 在发送前停）、
  `run_manifest.ingest.documents == 12`、revision=12、D01 槽 4 个版本、D02 槽 2 个版本。
4. **聚合**（只在受控进程内、工作区外产物目录）；两种输入二选一，缺输入即 `holdout_input_missing`：

```powershell
# a) 封存逐题行（工作区外）：逐题打分后折成聚合
.venv\Scripts\python.exe -B -X utf8 -m mktkb.evaluation.cli p2-score --visibility holdout ^
  --run-dir "<工作区外>\H2" --holdout-manifest "docs\evaluation\p2-holdout-v2.manifest.json" ^
  --holdout-cases "<工作区外>\h2-cases.jsonl" ^
  --document-codes "<工作区外>\h2-document-codes.json" --out "<工作区外>\H2\score"
# b) 只有判定表（case_id/status/hard_failure）：直接聚合
.venv\Scripts\python.exe -B -X utf8 -m mktkb.evaluation.cli p2-score --visibility holdout ^
  --run-dir "<工作区外>\H2" --holdout-manifest "docs\evaluation\p2-holdout-v2.manifest.json" ^
  --verdicts "<工作区外>\h2-verdicts.jsonl" --out "<工作区外>\H2\score"
```

- 聚合产物只有计数/`hard_failures`/`by_stratum`/分母；`case_id`/题干出现即由 `aggregate_holdout` 抛
  `holdout_detail_leak`（不是靠人眼查）。阈值未审批 → `holdout_threshold_unapproved`（unknown），不放行。
- **缺输入/给多了都是稳定码（T207-FIX-A-R1 阻断 3）**：两个输入都不给 → `holdout_input_missing`；
  两个都给 → `holdout_input_conflict`（不静默择一）。两者都在**读数据集/解封之前**拒绝，exit 3、不写任何产物。
  旧实现是 `TypeError`（exit 3 但不是承诺的码），已被代码修掉并有单测钉住。
5. 跑后审计（必做）：① 全文检索仓库，确认没有 H2 case_id/题干（含 `docs/reports` 与复制件）；
   ② `<out>` 与工作区外目录里的 `.sqlite3`/`-wal`/`-shm` 已删除；③ `summary.holdout.trace_retention="purged-at-close"`；
   ④ 计划/元数据/判定表留在工作区外，仓库只记 `plan_sha256` 与计数；
   ⑤ 灌库终态与 §8.3 的预期表逐项一致（D01 槽 4 版 / D02 槽 2 版 / 8 份当前有效资料），
      且账本 `index_embedding` 增量 ≤ 14（B 的实测值）。
- H2 一轮失败即停；重试 = 新计划 + 新 GO（`plan_sha256` 绑定），并计入同一 20 元与同一累计请求。

## 9 部分重跑规则

- 只重跑**失败与受影响范围**（同一 plan + 同一 GO 可以，但每次 run 会再消耗一次授权：见 §7）。
- 不得拼接不同版本的结果过关（任务书 §5「结果身份」）：改了 pipeline/计划/GO → 新版本、新 run、新记录。
- 不得因为"产品答错"挑题重跑；质量 fail 继续采集。

## 10 现场保留 / 回滚

- 零发送阶段：删 `<out>` 即可，账本零写入（SHA 复核可证）。
- 发出请求后：**保留** `<out>`、trace、receipts、账本；**不改**账本、不回滚历史、不释放预留。
- 失败金额如实留在 `P2-LIVE`；重跑 = 新计划 + 新 GO，并计入同一阶段与同一累计请求。

## 11 禁止清单

- 禁止把 `PM/T207-GO.CANDIDATE-DRAFT.json`（或 `-h2` 版）拷贝/改名为固定路径 GO（schema 无 DRAFT 标记，拷过去就会被当授权）。
- 禁止提高 `HARD_MAX_REQUESTS`/预算上限而不落盘记录；禁止改门槛/减题/换标签；禁止 `skip/xfail` 刷绿。
- 禁止读写 `.env`：凭据只能经 `tools/p2_live_execute.py --env-file <工作区外文件>` 注入（它拒绝名为 `.env` 的文件）；
  禁止把凭据值打印/落盘/写进报告；包装器与 p2_live 都只回变量名。
- 禁止读 H2 题干/答案/密文/key；禁止把 H2 case_id/题干/判定表写进仓库内任何文件、日志或报告。
- 禁止并发发送、禁止自动重试；禁止用 `--ingest` 冒充版本槽（那会建第二份文档 = T206 失败形态）。
- 禁止复用同一扇门跑第二次（第二 run 会被 `attempt_accounting_mismatch` 拒；这是既有语义，不放宽）。
- 禁止把三 run 观测矩阵写成 release/达标结论（`release_decision=false`、`gate_config_unapproved` 是写死的）。

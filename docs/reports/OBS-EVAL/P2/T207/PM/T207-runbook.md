# T207 正式矩阵 runbook（执行 · 停止 · 核对 · 回滚）

> **暂停覆盖指令（2026-11-11）**：主人已选择 A：零新增付费，完成 T207 报告与独立复核后暂停。
> 本页命令保留为历史操作手册，不是恢复授权；不得重跑 H2 或进入 T208/T209/T900。
> 当前结论与预算见 `../T207-final-report.md`，后文快照均需结合其历史时点阅读。

- 适用：`PM/T207-plan-v0_1.json`（`plan_sha256=0b4e55a4cd3a46f968e89fe495ffca3c6931c8f49f1f258a3dd753f83e24a194`，254 请求 / worst-case 8.127376 元 / `max_requests=1200`）
  + 重发后的 `PM/T207-GO.CANDIDATE-DRAFT.json`（**不可用**，等经理落盘到固定路径）。
- **当前状态（2026-11-11 T207-FIX-A 交付后；R4 另见第 4 项）**：计划通过真实快照预检（`ok=true`、`stage_remaining=19.4286417`、
  `requests_remaining=653`）；三处前置已解决：
  1. 请求硬顶已落盘 1600（T207-FIX-B），公开计划按经理决定重发为 `max_requests=1200`（sha 见上）；
  2. 驱动/生成器已交付：`--ingest-plan`（版本槽）、`cases/{R1,R2,R3}.jsonl`、`p2-h2-plan`、`p2-score`、
     `p2-matrix`、`p2-u-controls`、`tools/p2_live_execute.py`（全部有离线用例）；
  3. 固定路径 `P2-LIVE-GO.json` 仍指向 T206 pilot 计划（`02725aa7…`）：经理必须按**新 sha** 重签，否则
     被 `go_plan_id_mismatch` 拒（T206 pilot 的 `plan_id` 不同；旧文写 `go_plan_sha256_mismatch` 已由
     T207-FIX-A 独立验收纠正——sha 不匹配只在 plan_id 相同时才会被先撞到）。fail-closed，符合预期。
  4. **R4（N08/C05/C06 定点重测）备件齐全、前置已闭环**：计划 `PM/T207-plan-R4-v0_1.json`
     （13 项 / 18 请求 / worst 0.144960 元 / `max_requests=760` / 无 OCR）+ 灌库计划 + `cases/R4.jsonl` + 候选 GO。
     ① 冲突值口径已由 FIX-CONFLICT-R2（`24f9cde`）在产品侧闭合（冻结评分下 C05/C06 由 fail 变 pass）；
     ② live 单请求上限已由 FIX-LIVECAP（`1dca413`）闭合（无 OCR 计划 effective = 0.04096）。
     两条都不改计划内容 ⇒ `plan_sha` 不变、不重签计划（口径见 §9）。详见 §3.2 与 §9。
- **顺序约束（务必按此顺序）**：R3 → R2 → R1。计划含 12 页 OCR（上界 5.65），ocr 中心只有 6.5；
  R1 跑完后 ocr 已占 6.15，再授权必然 `center_budget_insufficient:ocr`（请求窗口其实还够）。
  反证见 `evidence/validate-plan-out.txt` 的 `reorder_control` 与 `T207-cost-and-quota.md` §3.1。
- 纪律：串行、自动重试 **0**、单轮 60 s 硬截止；首个服务/授权/预算/数据完整性错误即停后续付费；答案 `fail` 继续采集同一已批准矩阵（不挑题重跑）；不读 `.env`（只由 `tools/p2_live_execute.py --env-file` 显式注入）、不读 H2 明文、不改共享账本/预算/历史。

## 1 执行前只读检查（每次执行，逐项；任一不符即停）

```powershell
cd 'D:\GPT项目\市场部AI知识库'
git rev-parse --abbrev-ref HEAD; git rev-parse --short HEAD

# 1.1 账本/预算 SHA（**先跑、把两个 sha 与账本字节/行数记进本次 run 记录**，见 §2 第 5 项（记录）；账本不预设断言值）
.venv\Scripts\python.exe -B -X utf8 -c "import hashlib,pathlib;L=pathlib.Path('docs/evidence/LOCAL-R1-20261101/budget/live-ledger.jsonl');B=L.with_name('budget.json');print(hashlib.sha256(L.read_bytes()).hexdigest());print(hashlib.sha256(B.read_bytes()).hexdigest())"
#   账本**不写死期望值**：每次真实 run（R1/R2/R3、R4、H2）都会追加记录，照抄历史 sha 只会让执行在第一步停。
#   参考快照（**R1–R3 后 / R4 前**，仅供对照，不得当断言值）：05b54d06…，1,354,211 B / 1383 行 / 691 reserved / 691 result。
#     真实 run 之后这几项必然变（R4 已写入新 reservation 即属此列）⇒ 执行前一律重算、以当次输出为准。
#   预算才是可断言的不变量：79b21700b630be92148e2a8498ed47386dab08d6daa401601dc3d22a910b1a9e（本阶段不改预算文件）。
#   跨执行的账本变化不算异常；唯一的不变量判据 = 同一次执行内 §1.3 预检前后逐值相同（§1.4）。

# 1.2 正式 GO 的 SHA（必须等于经理签发记录值）
.venv\Scripts\python.exe -B -X utf8 -c "import hashlib,pathlib;p=pathlib.Path('docs/evidence/LOCAL-R1-20261101/PM/P2-LIVE-GO.json');print(p.exists() and hashlib.sha256(p.read_bytes()).hexdigest())"

# 1.3 只读契约复核（真实快照；不预留、不发请求）
.venv\Scripts\python.exe -B -X utf8 docs\reports\OBS-EVAL\P2\T207\evidence\validate-plan.py

# 1.4 预检后立即复算 1.1（**必须逐值相同**，证明预检零写入；这是唯一可断言的判据，跨执行变化不算异常）
```

预期读数（**T207-FIX-A 交付时的数，R1–R3 执行后不再成立**；一律以 §1.3 的当次输出为准）：
`preflight_real_snapshot.ok=true`、`requests_planned=254`、`requests_remaining=653`、`worst_case=8.127376`、
`reserve_peak=0.5`、`production_ready=true`（快照来自固定路径）。R4 的对应读数是 18 请求 / `max_requests=760` /
worst `0.144960`（窗口 69，见 §3.2）；判据始终是 **`ok=true` + 计划自身窗口**，不是上面这几个历史数。
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

### 3.1 公开三 run（R3 → R2 → R1）

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

### 3.2 R4 定点重测（N08/C05/C06；1 run / 18 请求 / worst 0.144960 元 / 无 OCR）

T207-R4PREP 新增。R4 是**独立重测**：不参与 R1/R2/R3 的三 run 观测矩阵，也不与它们拼结论。

```powershell
.venv\Scripts\python.exe -B -X utf8 tools\p2_live_execute.py ^
  --env-file "<工作区外>\p2-live.env" -- p2-run ^
  --plan   "docs\reports\OBS-EVAL\P2\T207\PM\T207-plan-R4-v0_1.json" ^
  --out    "<仓库外新目录>\R4" ^
  --cases  "docs\reports\OBS-EVAL\P2\T207\cases\R4.jsonl" ^
  --ingest-plan "docs\reports\OBS-EVAL\P2\T207\PM\T207-ingest-plan-R4.json" ^
  --mode live --run-id "p2-t207-r4-20261111-01" ^
  --dataset-version p2-t207-r4-20261111-v0.1 --label-version p2-t207-labels-20261111-v0.1
```

- 计划 `plan_sha256=00b9fdefd8cc8220178745f0806486eaf3a70818be4068dd0fd2307303b5d2b9`（13 项 / 18 请求 /
  `max_requests=760` / `page_count=0`）；候选 GO `PM/T207-GO-R4.CANDIDATE-DRAFT.json` 绑该 sha、13 天、
  中心 8.5/6.5/3/2、`max_request_cny=0.5`、操作 = answer/index_embedding/query_embedding/query_expansion/rerank（**无 ocr**）。
- 灌库 6 步**同一库**（顺序即语义）：V03 建 D01 槽 → D01 当前版 → V04 处理**不发布** → V01 发布 → D02 → V02 发布。
  终态实测：4 份资料 / D01 槽 3 版（v1 superseded、v2 active、v3 review_required）/ revision 5 /
  索引 4 份 23 单元 / **B_r4 = 6 批**（上界 9）。证据：`evidence/r4-ingest-state.json`。
- **前置 1（已闭环）**：冲突值口径已由 FIX-CONFLICT-R2（`24f9cde`，产品侧 1 处文案）闭合 —— 冲突轮 text 改为
  通用披露「字段：[值1、值2]」，冻结 CaseSpec 下 N08/C05/C06 全 pass（`T207-FIX-CONFLICT-R2/review.md`）。
  该改动**不改计划内容**：`plan_sha` 不变、R4 **不重签计划**（裁定见 §9），GO 仍按流程签发。
  live 首验即本 run，仍存在产品仍回 `answer` 的可能（R2/R3 的 live 读数早于修复），出现即按 §4/§6 停并归因。
- **前置 2（T207-FIX-LIVECAP，已修）**：live 的 `RagConfig.max_request_cny` 不再取 `plan.reserve_peak_cny`，
  而是 `max(计划峰值, 各已接 provider 单次预留)` 且 ≤ GO 的 `authorization.max_request_cny`（推导见
  `docs/evaluation/p2-live-binding-v0_1.md` §10.10）。本计划 `page_count=0`（峰值 0.018688）时
  effective = **0.04096**（embedding 的 81,920 token 单次预留）⇒ **GO 的 `max_request_cny` 必须 ≥ 0.04096**
  （候选 GO 的 0.5 满足；H2 同理，其计划也是 `page_count=0`）；不足则**装配期 fail-closed**：
  `live_request_ceiling_insufficient`，零发送 / 零预留 / 零降级 / 无产物，停，不要改代码绕过。
  未修之前的后果（历史读数，别照抄）：每次 embed 在发送前被拒；live 实参 `require_zero_retries=True` 下
  **首回合即 `aborted(product_service_error)`**（账本只留 1 次 chat 预留，以 `failed`/`INDEX_NOT_READY` 结算），零答案。
  跑后先看 `summary.json` 的 `providers.live.request_ceiling.effective_max_request_cny` = 0.04096
  （同处还有 `authorization_max_request_cny` 0.5、`provider_single_request_cny.embedding` 0.04096）。
  **索引健康度不要到 `summary.json`/`run_manifest.json` 的 `pipeline.index` 里找**——runner 只抄
  `documents/units/chunks/engine_version/provider_mode` 五键（`p2_runner.py:2291-2296`）；`degraded` 是
  `qa.status()`/`QaIndexStatus` 的**进程内**字段（`qa/service.py:272-284`），不入产物。判读改为：
  `run_manifest.ingest` 逐 source 的 `upload_status`/`job_state`/`publish_status`（`product_adapter.ingest` 回执，
  R4 产物即此形状）+ 失败码（`ingest_failed`、`OCR_NOT_CONFIGURED`、`EMBEDDING_DEGRADED_NO_RETRY`，见 §6）。
- 产物落位：跑完只按 §5 复制到 `docs/reports/OBS-EVAL/P2/T207/<run_id>/`；trace 库与业务库留仓库外。

## 4 停止规则（触发即停；不重试、不补跑、不改计划续跑）

1. §1 任一检查不符：**预算 sha 变**、**同一次执行内 §1.1 前后不一致**（§1.4）、GO 缺失/过期、预检 `ok=false`。
   账本 sha 因**其它 run** 变化不算异常（见 §1.1），但必须在启动前把当次值记进记录。
2. 门控拒绝（稳定码）：`path_missing`/`path_not_fixed`、`go_expired`、`go_plan_id_mismatch`（固定路径那张旧 GO
   首先是 plan_id 不同）、`go_plan_sha256_mismatch`、
   `go_max_requests_below_plan`、`go_cost_center_below_plan`、`go_operation_unauthorized`、`budget_stage_missing`、
   `budget_history_mismatch`、`env_total_limit_missing`/`env_total_limit_mismatch`、`live_requires_production_ready`、
   `live_requires_real_gate`、`center_budget_exceeded`、`request_limit`、`ledger_prefix_mismatch`、
   `attempt_quota_exhausted`（计划低估，发送前）、`attempt_accounting_mismatch`、`usage_evidence_missing`、
   `live_request_ceiling_insufficient`（GO 单请求上限 < provider 单次预留 0.04096，装配期拒；见 §3.2 前置 2）。
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

H2 评分启用 `docs/evaluation/p2-holdout-v2.source-map.json` 将 V03/V04/V05/V06 绑定基槽及上传版本号，并与产品版本和原 locator 合取比对；映射/导入顺序/覆盖异常阻断，错版或缺版不命中，历史身份不代替 active 校验或后续分场景契约修复。

前置：`MKTKB_P2_HOLDOUT_ROOT`/`MKTKB_P2_HOLDOUT_KEY_FILE` 只在**受控进程**注入；H2 语料包声明（fix-scope §F2）
已就位（D01–D06 + V01–V07，requires_ocr 全 false）；H2 case 元数据（case_id/轮数）由经理按 custodian-report
准备在**工作区外**；题干/答案/密文/key 一律不进仓库、不进日志。

**manifest 路径规则（T207-FIX-LIVEGATE）**：只有 `p2-h2-plan`（生成计划）用**仓库副本**
`docs\evaluation\p2-holdout-v2.manifest.json` 做交叉校验；命令一旦带 `--visibility holdout`
（执行 `p2-run` 与两步 `p2-score`），`--holdout-manifest` 必须指向**封存 root 内**的同一份
manifest `D:/mktkb-p2-holdout/v2/manifest.json` —— 否则 `load_p2_dataset` 在读取任何密文之前
以 `holdout_manifest_outside_root` 拒绝（`backend/src/mktkb/evaluation/p2_dataset.py:539-546`）。
两份文件当前逐字节相同（sha256 `8874985e…`），因此 `manifest_sha256`、计划与产物身份都不受影响；
但"能读"的路径只有 root 内那一份，repo 副本不得用于 holdout 加载。

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
  --holdout-manifest "D:/mktkb-p2-holdout/v2/manifest.json" ^
  --mode live --run-id "p2-t207-h2-20261111-01" ^
  --ingest-plan "docs\reports\OBS-EVAL\P2\T207\PM\T207-ingest-plan-H2.json"
```

- `--visibility holdout` 强制 `purge_traces=True`；run 产物只留聚合（`holdout_aggregate.json` + `holdout_scorecard.json`），不写 case_id/题干。
- **门规则（T207-FIX-LIVEGATE）**：`open_live_gate` 的操作要求随**计划**（`p2_live.required_live_operations`）
  —— `answer/index_embedding/query_embedding/rerank` 四项恒需，`ocr` 仅当计划含 `operation=="ocr"` 项时才要求。
  H2 计划 `page_count=0`（无 OCR 项），因此即使 H2 GO 的 `scope.operations` 仍写着 `ocr`（超集），
  门也不再以 `live_operation_not_authorized: [ocr]` 拒；含 12 页 OCR 的公开矩阵计划行为不变。
  规则原文见 `docs/evaluation/p2-run-contract-v0_1.md` §11.1 与 `docs/evaluation/p2-live-binding-v0_1.md` §10.8。
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
4. **聚合（H2 run 后直接读 `<工作区外>\H2\holdout_scorecard.json`）**：T207-FIX-H2SCORE-R1 之后，
   runner 在受限进程内已用**内存里的题面** + 本次 run 的完整逐题观测（含回答正文，只在内存、不落盘）
   算好 H2 质量聚合，只写计数：
   `total/executed/errors/passed/failed/hard_failures/by_stratum/blocks/execution_mode/real_calls/run_id/config_hash`，
   没有 `case_id`/题干/答案/逐题行（`detail_export=false`）。**不需要**再为 H2 生产封存逐题行/判定表。
   - `passed` 是"产品真的答对"的读数：answer 轮的回答正文由 runner 在内存里保留并参与 value_hit 判定，
     产物里不出现正文；同一批正确回答若没有正文（旧口径）会退化成 `passed=0`（30 题合成实跑对照：
     带正文 23 pass / 去掉正文 0 pass）。
   - 引用**结构性**问题（`source_not_active` 旧/失效版本、`source_forbidden_document`、
     `source_outside_run`、`citation_not_unit_level`）的题**不计 pass**：状态记 `error` 并出
     `holdout_hard_failure_unclassified`（unknown）。因此本卡的 `hard_failures` **恒 0**，含义是
     "驱动层不代分类"，**不是**"无硬失败"；硬失败类别/计数以封存判定表（`p2-score --verdicts`）为准。
   - 阈值未批（gate_v0_3 `status="unapproved"`）→ `holdout_threshold_unapproved`（unknown）、
     `release_ready=false`，但观测到的 `passed/failed/errors/by_stratum` 照常可读；error/未执行**不计** pass。
     `thresholds_approved` 由 runner **读 gate 配置**；`p2-score` 侧当前硬编码 `false`，gate 转 approved 后
     两张卡会不一致 —— 放行判断一律取更保守者（见 `docs/evaluation/p2-live-binding-v0_1.md` §10.9）。
   - `real_calls` 取**实测出站尝试数**（与 `p2-score` 同口径，不是"有出网的请求行数"）。
   - 文档代号映射按 ingest-plan 的语料文件名规范前缀（`D01_`/`V03_`，版本文件按 `document_ref` 归槽）
     自动建立；映射冲突/缺失 → `holdout_document_code_ambiguous`/`holdout_document_code_unmapped` block
     （映射本身失败时只出一条，不叠同因 block）。
   - 写盘前用内存题面逐题扫聚合文本：`case_id` + `case.question` + **每个回合的题面** + `reference_answer`
     （≥2 字即报，短题干不漏），命中即 `holdout_scorecard_leak` 并退化成"全 error + 稳定 block"（兜底卡
     不再经过聚合器，产物照样写出）；字段与审计口径见 `docs/evaluation/p2-dataset-v0_1.md` §10。

   **可选独立复核**（需要工作区外的封存输入；不是 H2 run 的必要步骤）：两种输入二选一，缺输入即
   `holdout_input_missing`：

```powershell
# a) 封存逐题行（工作区外）：逐题打分后折成聚合
.venv\Scripts\python.exe -B -X utf8 -m mktkb.evaluation.cli p2-score --visibility holdout ^
  --run-dir "<工作区外>\H2" --holdout-manifest "D:/mktkb-p2-holdout/v2/manifest.json" ^
  --holdout-cases "<工作区外>\h2-cases.jsonl" ^
  --document-codes "<工作区外>\h2-document-codes.json" --out "<工作区外>\H2\score"
# b) 只有判定表（case_id/status/hard_failure）：直接聚合
.venv\Scripts\python.exe -B -X utf8 -m mktkb.evaluation.cli p2-score --visibility holdout ^
  --run-dir "<工作区外>\H2" --holdout-manifest "D:/mktkb-p2-holdout/v2/manifest.json" ^
  --verdicts "<工作区外>\h2-verdicts.jsonl" --out "<工作区外>\H2\score"
```

- 复核产物同样只有计数/`hard_failures`/`by_stratum`/分母；`case_id`/题干出现即由 `aggregate_holdout` 抛
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
  例外判据见 §9 下文「重签口径」（**注意**：不是相邻的下一条 bullet）：**只改产品输出文本、不改计划内容（计划项/请求形状/操作集合）不算 pipeline 变更**。
- 不得因为"产品答错"挑题重跑；质量 fail 继续采集。

- **R4 前置（T207-R4PREP / -R1）：已闭环**。历史（HEAD `489aadd`）：C05/C06 的冲突值只在 API 的 `conflicts`
  负载里、消息 `text` 只有"资料中对位置/电话记录了多个有效值…"，而冻结评分器的 `value_hit` 只读
  `outcome.text`（`scorers.py:632`；`product_adapter.py:2156` 只取 `payload["text"]`；行号为当前工作区，`489aadd` 时为 2137）⇒ 两种形状
  （`evidence/r4-ingest-state.json` 的 `scoring_gated` / `scoring_ungated`，**修复前读数**）都 `value_hit fail`。
  已按 a) 产品侧 1 处文案落地：FIX-CONFLICT-R2（`24f9cde`）让冲突轮通用披露「字段：[值1、值2]」
  （值来自 `conflicts`；仍 0 次模型调用，`conflicts`/`sources` 结构不变），冻结 CaseSpec 下 N08/C05/C06 **全 pass**
  （独立验收：`T207-FIX-CONFLICT-R2/review.md`）。⇒ 签 R4 GO **不再需要**先做口径决策，只剩 §3.2 两条前置（均已修）。
- **重签口径（F-3 经理裁定，写死）**：**只改产品输出文本、不改计划内容时，`plan_sha` 不变，R4 不重签计划**；
  GO 仍按流程签发（GO 绑定 `plan_sha`）。判据 = 「计划项 / 请求形状 / 操作集合 / 证据链有没有变」：没变就不算
  pipeline 变更，照旧用同一份计划与候选 GO；一旦改到这些，才回到"新计划 + 新 GO"。FIX-CONFLICT-R2 与
  FIX-LIVECAP 都属前者 —— R4 计划 `00b9fdef…`（13 项 / 18 请求 / `max_requests=760`）、`cases/R4.jsonl`、
  灌库计划、候选 GO 逐字未变。
- **R4 只重跑这 3 例**；因**计划/请求形状**变更而重跑 = **新计划 + 新 GO**（`plan_sha` 绑定），
  计入同一 20 元与同一累计请求；不得把 R4 的读数拼进 R1/R2/R3 的矩阵产物（`release_decision=false` 不变）。
- **接线面（T207-FIX-LIVECAP，已修，§3.2 前置 2）**：F-1 的「live 发不出 embedding POST」已在产品侧修掉：
  R4/H2 这类 `page_count=0` 计划跑 live 时 effective 单请求上限 = 0.04096，**GO 的 `max_request_cny` 必须
  ≥ 0.04096**（候选 GO 与 H2 候选 GO 都是 0.5，满足）；不足则装配期 `live_request_ceiling_insufficient`
  fail-closed（零发送/零预留/零降级/无产物）。该修复不改计划内容，`plan_sha256`/GO 绑定字段/请求形状都不变。
  未修之前的历史后果：live 下首回合即 `aborted(product_service_error)`（不是"静默降级"）；`page_count=0` 计划
  的灌库降级为 `embedding_error` 只在 Mock/不限出站路径上可观测，别拿它当 live 风险形态。

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

# T207 正式矩阵 runbook（执行 · 停止 · 核对 · 回滚）

- 适用：`PM/T207-plan-v0_1.json`（`plan_sha256=d788a83b…a947`，254 请求 / worst-case 8.127376 元 / `max_requests=1000`）
  + `PM/T207-GO.CANDIDATE-DRAFT.json`（**不可用**，等经理落盘到固定路径）。
- **当前状态（2026-11-11 本包交付时）**：计划可被当前代码表达并通过真实快照预检（`ok=true`、
  `stage_remaining=19.4286417`、`requests_remaining=453`）；但**不能整套执行**，卡在三处必须由经理决定的前置：
  1. 请求硬顶：R2/R3/H2 的再次授权需要 `HARD_MAX_REQUESTS ≥ 1200`（实算见 `T207-cost-and-quota.md` §6，本包建议 **1600**）；
     现在交付的计划 `max_requests=1000`，只够 **R1** 一次授权。
  2. 固定路径 `P2-LIVE-GO.json` **现在仍指向 T206 pilot 计划**（`plan_sha256=02725aa7…`）：换计划不换 GO 会被
     `go_plan_sha256_mismatch` 拒（fail-closed，符合预期）。经理需用本次候选重签并记录新 GO SHA。
  3. 用例文件与 H2 计划的**生成器还没写**（见 `T207-fix-scope.md` §F1/F3/F5）：没有它们，`--cases` 与 H2 的
     `--plan` 都产不出来。**下面的执行节以"这些前置已合入并通过离线用例"为前提**。
- 纪律：串行、自动重试 **0**、单轮 60 s 硬截止；首个服务/授权/预算/数据完整性错误即停后续付费；
  答案 `fail` 继续采集同一已批准矩阵（不挑题重跑）；不读 `.env`、不读 H2 明文、不改共享账本/预算/历史。

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

预期读数：`preflight_real_snapshot.ok=true`、`requests_planned=254`、`requests_remaining=453`、
`worst_case=8.127376`、`reserve_peak=0.5`、`production_ready=true`（快照来自固定路径）。
若 `reasons` 出现 `budget_total_mismatch`/`stage_allocation_missing` → 预算还没按 40/20 落盘，停。

## 2 签发（经理做；本 runbook 不代签）

1. 预算：`limit_cny=40.0`、`stages["P2-LIVE"]=20.0`（当前已是；**中心重排不进预算文件**，理由见 cost §4）。
2. GO：字段与 `PM/T207-GO.CANDIDATE-DRAFT.json` 一致，改 `nonce`（≥16、无空白、不留仓库副本）、
   `issued_utc`=签发时刻、`expires_utc` ≤ +14 天、`budget_ledger_sha256`=历史前缀 `f4710b18…`、
   `scope.plan_sha256=d788a83b…`、`scope.max_requests` ≥ 254（现版 1000；提顶后按 §7 用 1200）、
   `scope.cost_centers_cny = 8.5/6.5/3/2`、`max_request_cny=0.5`。落盘后记 SHA。
3. 进程环境（只设本次进程）：`MKTKB_PROJECT_TOTAL_LIMIT_CNY=40.0`（缺 → `env_total_limit_missing`；不一致 → `env_total_limit_mismatch`）。
4. live provider 环境变量（只列名字，不写值）：`MKTKB_MODEL_API_KEY`、`MKTKB_MODEL_BASE_URL`、`MKTKB_MODEL_NAME`、
   `DASHSCOPE_API_KEY`、`DASHSCOPE_BASE_URL`、`MKTKB_OCR_SECRET_ID`、`MKTKB_OCR_SECRET_KEY`、`MKTKB_OCR_REGION`、
   `MKTKB_OCR_DISABLED`（必须未禁用）。H2 另需 `MKTKB_P2_HOLDOUT_ROOT`、`MKTKB_P2_HOLDOUT_KEY_FILE`。
5. 记录：GO SHA、预算 SHA、账本历史前缀、`plan_sha256`、三个 `run_id`（R1/R2/R3 各一）。

## 3 三次运行（顺序固定；R2/R3 必须新开一扇门，不要复用同一 gate）

**R1 主矩阵**（52 case / 230 请求 / worst 7.994704）：

```powershell
.venv\Scripts\python.exe -B -X utf8 -m mktkb.evaluation.cli p2-run ^
  --plan   'docs\reports\OBS-EVAL\P2\T207\PM\T207-plan-v0_1.json' ^
  --out    '<仓库外新目录>\R1' ^
  --cases  'docs\reports\OBS-EVAL\P2\T207\cases\R1.jsonl' ^
  --mode live --run-id 'p2-t207-r1-20261111-01' ^
  --dataset-version p2-t207-b0nc-20261111-v0.1 --label-version p2-t207-labels-20261111-v0.1 ^
  --ingest 'fixtures\acceptance\variants\V03_物品位置表_历史V1.xlsx' ^
  --ingest 'fixtures\acceptance\normal\D01_物品位置表.xlsx' ^
  --ingest 'fixtures\acceptance\variants\V04_物品位置表_新版V3.xlsx' ^
  --ingest 'fixtures\acceptance\normal\D02_合作店家信息.xlsx' ^
  --ingest 'fixtures\acceptance\normal\D03_市场部工作指南.docx' ^
  --ingest 'fixtures\acceptance\normal\D04_活动策划流程.docx' ^
  --ingest 'fixtures\acceptance\normal\D05_物料领用规范.pdf' ^
  --ingest 'fixtures\acceptance\normal\D06_店家资料维护说明.pdf' ^
  --ingest 'fixtures\acceptance\normal\D07_活动申请扫描件.pdf' ^
  --ingest 'fixtures\acceptance\normal\D08_仓库安全须知扫描件.pdf' ^
  --ingest 'fixtures\acceptance\normal\D09_物料领用通知.png' ^
  --ingest 'fixtures\acceptance\normal\D10_盘点通知.jpg'
```

- **版本槽的写法**：`--ingest` 只能表达"新文档"，**不足以**造版本槽（见 `T207-import-recipe.md` §1）。
  T207-FIX 合入 `--ingest-plan <json>`（`document_ref` + `publish=false`）后，R1 灌库改用
  `--ingest-plan 'docs\reports\OBS-EVAL\P2\T207\PM\T207-import-recipe.json'` 的 `steps[1..36]`。
  **在它合入前 R1 不得执行**（否则又是两份独立文档 = T206 失败形态）。
- **R2 版本槽 + 冲突**（3 case / 19 请求）：`--cases cases\R2.jsonl --run-id p2-t207-r2-… --out …\R2`，
  灌库 = `steps[1..9]`（V03→D01→V04 未发布）+ V01（steps 37–39）。
- **R3 电话冲突**（1 case / 6 请求）：`--cases cases\R3.jsonl`，灌库 = D02 + V02。
- 三次都用**同一份计划文件**（sha 必须一致）；`--mode live` 必须显式；live 下 `--snapshot` 不参与准入（可省）。

## 4 停止规则（触发即停；不重试、不补跑、不改计划续跑）

1. §1 任一检查不符（SHA 变化、GO 缺失/过期、预检 `ok=false`）。
2. 门控拒绝（稳定码）：`path_missing`/`path_not_fixed`、`go_expired`、`go_plan_sha256_mismatch`、
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
2. **账本增量**：新增 `reserved`/`result` 条数（R1 期望 230/230）、`center_accounted_cny` 增量
   （R1 上限 `answer_retrieval +2.344704`、`ocr +5.65`）、失败笔是否按上界保守留账；
   `billed` 是**结算口径**，不是供应商账单（`provider_billed_cny` 仅在拿到真实 usage 时有值）。
3. **产物内部一致**：`summary.requests` 与 `network.outbound_attempts` 及其 `detail` 相等；
   `gate.attempts`/`gate.receipts` 与 `attempt_audit.expected_reservations == gate_reserved`。
4. **身份/证据**：`run_manifest.config_hash` 完整、trace 六字段、`citation_evidence.complete`、
   `gate.real_sends_allowed`、`cases.jsonl` 的 `product.evidence`/`retrieved`。
5. **失败身份**：`failure.{stage,case_id,turn,item_id,ticket}`（含在飞 ticket 的 request_id/reservation_id）。
6. **评分**：`p2-score`（T207-FIX 待建，见 fix-scope §F5）→ `scorecard.json` + `p2_decision.json`；
   **不要**把 citations 当 `retrieved`（R1 残余①）。gate 判定必然是 `gate_config_unapproved`（unknown），
   所以结论只能写"执行完成 + 观测值"，不得写"质量达标/放行"。

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

## 7 提顶之后要做的事（拟提 1600，见 cost §6）

1. 改 `p2_contracts.py:87` 与 `live_authorization.py:94` 为 1600（`test_p2_authorization.py:481` 不变式保持）；
2. `build-plan.py` 的 `MAX_REQUESTS` 改 1200 → 重跑 → 新 `plan_sha256` → 经理按新 sha 签 GO（`max_requests=1200`）；
3. 之后 R2/R3 才能各自再授权（801 / 1031 / 1050 / 1056 ≤ 1200）；H2 计划 `max_requests=1100`；
4. **到值即停**：累计请求到 1600 或任一计划自身上限即停，不静默加计划。

## 8 H2（受限）执行与跑后审计

前置：`MKTKB_P2_HOLDOUT_ROOT`/`MKTKB_P2_HOLDOUT_KEY_FILE` 只在**受控进程**注入；H2 语料包声明文件已就位
（fix-scope §F2）；H2 计划由封存进程生成（§F1）并已签 GO。

```powershell
.venv\Scripts\python.exe -B -X utf8 -m mktkb.evaluation.cli p2-run ^
  --plan '<工作区外>\h2-plan.json' --out '<工作区外>\H2' --visibility holdout ^
  --holdout-manifest 'docs\evaluation\p2-holdout-v2.manifest.json' ^
  --mode live --run-id 'p2-t207-h2-20261111-01' ^
  --ingest-plan '<工作区外>\h2-ingest.json'
```

- `--visibility holdout` 会强制 `purge_traces=True`（`cli.py:562-570`），run 结束删 trace 库并封存业务库；
  产物只留聚合（`holdout_aggregate.json`），**不写 case_id/题干**。
- 跑后审计（必做）：① 全文检索仓库，确认没有 H2 case_id/题干（含 `docs/reports` 与复制件）；
  ② `<out>` 与工作区外目录里的 `.sqlite3`/`-wal`/`-shm` 已删除；③ `summary.holdout.trace_retention="purged-at-close"`；
  ④ 计划文件与 ingest 计划留在工作区外，仓库只记 `plan_sha256`。
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
- 禁止读写 `.env`、H2 题干/答案；禁止把凭据、H2 明文写进日志/报告/产物。
- 禁止并发发送、禁止自动重试、禁止在 `--ingest-plan` 未就位时用 `--ingest` 冒充版本槽。

# R2 真实 H2 运行程序（runbook）—— T-R2-205P

日期：2026-11-17。仓库：`D:\GPT项目\市场部AI知识库`。Python：`.venv\Scripts\python.exe`（下文简写 `PY`）。
读者：主人指定的外部开发助手（执行方）。本文件是**照着做**的操作程序，不是设计说明。
引用一律用 `文件:行号`；未在源码中找到确切依据的条目在 §5 标 `UNVERIFIED`，不给猜测命令。

---

## §0 结论与适用范围

### 0.1 本文件覆盖什么

一次完整的 R2 真实 H2：**修后源码摘要绑定新计划 → 完整 check-only 预检 → GO 归档留痕与新签 → 逐 plan 配额与金额核对 → 单次执行 → 封存/证据/清理 → 账本配对与结果读取 → 失败闭环留痕**。
范围固定为：`run_index=2`、`scenario_id=pre_v05_without_v07`、业务日 `2026-11-20`、**5 题 / 6 回合**、`max_requests="unlimited"`、项目 40 元 / 阶段 20 元 / 单请求 0.5 元 / 成本中心 8.5-6.5-3-2。到此停止，不进入 R3、不做全 30 题（任务书 §9、§10）。

### 0.2 唯一真实入口，以及一处必须纠正的入口指向

| 文件 | 角色 | 能否用于 R2 |
|---|---|---|
| `tools/p2_h2_v3_controlled_execute.py` | **v3 真实入口**：`plan-private` / `check-only` / `run` | **是。本 runbook 全部命令用它** |
| `tools/p2_h2_controlled_execute.py` | v2/T207 受控骨架（被 v3 以文件路径导入复用） | 否。它的 `SCENARIO_ORDER`/`EXPECTED_SCENARIO_COUNTS` 是 v0.2 口径（`pre_v05_without_v07`=2 题、30 题/36 回合），直接跑它的 CLI 得不到 R2 的 5 题/6 回合/2026-11-20 |
| `tools/p2_live_execute.py` | 子进程 env 包装器 + 白名单解析器（v2/v3 只借用其 `parse_env_text`/`REQUIRED_ENV_NAMES`） | 不是执行入口 |

依据：`tools/p2_h2_v3_controlled_execute.py:1-38`（v3 只新增、v2 一字未改，逐条列出五处差异）、`:162-173`（v3 5 题/6 回合）、`tools/p2_h2_controlled_execute.py:124-143`（v2 的 2 题/30 题口径）。

### 0.3 本次执行声明

**本文件编制过程未执行任何付费链路**：未运行 `run`、未运行 `plan-private`/`check-only`、未发生任何真实或离线产品请求、未访问网络、未生成或签发任何 GO、未改动预算/账本/计划/证据，未做 git 写操作；固定槽位 GO 的字节摘要与开工时一致（`38f3c3f5…`，编制结束后复测）。只做了三件事：只读源码与公开文档、只读核对既有 GO 与账本的字节/内容摘要、写入本文件。

### 0.4 R2 达标线（供判定时对齐，不由本文件宣布）

同一修后版本 **5/5 质量通过、硬失败 0、必要轴 unknown 0**（或由主人单独决定保留哪一条）；20 轴四态计数可复核；质量与轴证据可追溯到本次 receipt/plan/code/seal；独立验收；经理接收。R1 对 C13 的 unknown 豁免**不继承**（任务书 §1、§9）。

---

## §1 前置角色与授权

| 角色 | 谁 | 能做什么 | 不能做什么 |
|---|---|---|---|
| 主人（owner） | 人类 | 给范围/预算/时效；批准新 GO 的授权文本；对不可修契约阻塞做决策 | — |
| 签发方 | 主人本人，或被主人明确书面委托者 | 把新 GO 写到固定槽位、把旧件归档 | 不得代签未经主人批准的范围；不得复用 R1 GO |
| 执行方 | 本任务指定的外部开发助手 | `plan-private` / `check-only` / `run`（一次） | 不得自批预算、不得改冻结件、不得读题面/答案/实体值、不得重试 |
| 保管方 | 持有 holdout 根与 key 的一方 | 提供 `<HOLDOUT_ROOT>` 与 `<KEY>`；只回 SAFE 投影 | 不得把题面/答案/实体值写入仓内或对话 |
| 独立验收 | 与开发独立的助手 | 自执行关键验证并给命令/退出码 | 不得沿用旧批次结论 |

授权链固定为四件套，缺一不可：
1. 主人的范围/预算决定（文本，仓内或交接件）；
2. 固定槽位 GO `docs/evidence/LOCAL-R1-20261101/PM/P2-LIVE-GO.json`（正是本次计划的那一份）；
3. 旧槽位件的归档件（字节留痕）；
4. 本次 `run-receipt.json`（含 `bindings.go_sha256`、`plan_sha256`、`code_version`、`seal.*`）。

**R1 的权限与已耗用计划不继承**：`GO 与已耗用计划不能复用`（`.claude/handoffs/2026-11-17-r1-pm-closeout.md:34`）；槽位里现在那份 GO 只代表 R1 run2 的许可（同文件 `:16`：`38f3c3f5…`，`scope.plan_sha256=80d05194…`），**不代表新运行许可**。

---

## §2 逐步命令序列

约定：`cwd = D:\GPT项目\市场部AI知识库`（v3 入口强制，`cwd_not_project_root`，`tools/p2_h2_v3_controlled_execute.py:436-439`）。
占位符：`<HOLDOUT_ROOT>`=v3 封存根（含 `manifest.json`/`annotations-v0_2.fernet`/`review-v0_2.fernet`），`<HOLDOUT_KEY>`=该根 Fernet key，`<R2_ROOT>`=本次仓外工作根（建议 `D:\mktkb-p2-h2v3-r2-20261117`），`<ATTEMPT>`=`<R2_ROOT>\attempt1`，`<NEW_PLAN_SHA256>`/`<NEW_CODE_VERSION>`/`<NEW_GO_SHA256>` 由命令实际输出填入。
**所有仓外产物不得落在仓库内，也不得落在 `D:/mktkb-p2-holdout` 之下**（`tools/p2_h2_controlled_execute.py:286-301`）。

### S0 开工前只读核对（零成本）

```powershell
git rev-parse --abbrev-ref HEAD
git rev-parse HEAD
(git status --porcelain).Count
Get-FileHash -Algorithm SHA256 docs\evidence\LOCAL-R1-20261101\PM\P2-LIVE-GO.json
Get-FileHash -Algorithm SHA256 docs\evidence\LOCAL-R1-20261101\budget\budget.json
Get-FileHash -Algorithm SHA256 docs\evidence\LOCAL-R1-20261101\budget\live-ledger.jsonl
# 期望输出
#   HEAD = 97b0066726e5b8d6f94cbc0b63a890084550c106（或本次修后实际 HEAD，记录它）
#   P2-LIVE-GO.json  = 38f3c3f5dd6f2c828b66a3d96ee27d5a82ceed25ac49ecaba70ab7269c95fda3（R1 run2 旧件）
#   budget.json      = 79b21700b630be92148e2a8498ed47386dab08d6daa401601dc3d22a910b1a9e
#   live-ledger.jsonl= 逐次不同，记录本刻值作为"运行前账本摘要"
```
HEAD 只是记录，**不是代码身份**：代码身份用 S1 的 `code_version`（脏工作树摘要）。

### S1 生成 R2 计划（回答 Q1：命令、五个固定项、code_version 算法）

```powershell
$PY tools\p2_h2_v3_controlled_execute.py plan-private `
  --root '<HOLDOUT_ROOT>' `
  --key-file '<HOLDOUT_KEY>' `
  --out-dir '<R2_ROOT>\plan' `
  --created-utc 2026-11-17T18:00:00+08:00
```
参数依据：`tools/p2_h2_v3_controlled_execute.py:2382-2388`（`--root/--key-file/--out-dir/--created-utc/--max-requests`，`--max-requests` 只接受 `unlimited`）。

**五个固定项如何钉进去**（没有一个是 CLI 可覆盖的）：

| 项 | 钉在哪 | 依据 |
|---|---|---|
| `run_index=2` | v3 `SCENARIO_ORDER` 第 3 位 = `pre_v05_without_v07`（索引 2） | `tools/p2_h2_controlled_execute.py:124-129`、`tools/p2_h2_v3_controlled_execute.py:1625` |
| `scenario_id=pre_v05_without_v07` | 同上；`run2` 的 binding 文件名 `run2-pre_v05_without_v07.binding.json` | `tools/p2_h2_v3_controlled_execute.py:1762` |
| 业务日 `2026-11-20` | `p2_holdout_run_date.RUN_DATES` 第 3 行，并与 L1 `docs/evaluation/p2-source-lifecycle-v1.json` 的 `coverage_selfcheck.per_run_dates.runs[]` 逐值对账 | `backend/src/mktkb/evaluation/p2_holdout_run_date.py:129-134,178-188` |
| 5 题 | v3 `V3_SCENARIO_COUNTS["pre_v05_without_v07"]=5`，并由 contract 的 `subset()` 实数校验 | `tools/p2_h2_v3_controlled_execute.py:162-167,1599-1600` |
| 6 回合 | v3 `V3_SCENARIO_TURNS[...]=6` | `tools/p2_h2_v3_controlled_execute.py:168-173,1601-1602` |

`plan-private` 一次生成**四个 run** 的计划与四份 binding（`tools/p2_h2_v3_controlled_execute.py:1609-1763`），R2 只用 `runs[2]` / `bindings\run2-pre_v05_without_v07.binding.json`。

`# 期望输出`（stdout 一份 JSON，逐项核对）：
```
ok=true
schema_version=p2-h2v3-controlled-plan-public/v0.1   tool=p2-h2v3-controlled-entry/v0.1
created_utc=2026-11-17T18:00:00+08:00
project_total_limit_cny=40.0   max_requests="unlimited"
ingest_batches_source{path=…ingest-batch-census.json, sha256=…, rule=…, batches_by_scenario{base_b0,base_b0_plus_v01,pre_v05_without_v07:13,post_v05_without_v01}}
anchor_business_date=<数据集锚点日，不等于任何 run 日>      run_dates[4]{run_index,scenario_id,business_date}
runs[2]{run_index:2, scenario_id:"pre_v05_without_v07", run_id:"p2-h2v3-20261115-r2-pre_v05_without_v07",
        plan_id:"P2-H2V3-20261115-r2-pre_v05_without_v07", plan_sha256=<NEW_PLAN_SHA256>,
        business_date:"2026-11-20", case_count:5, turn_count:6, total_requests:37,
        worst_case_cny=<计划金额上界>, plan_file, plan_file_sha256, binding_file, binding_file_sha256,
        contract_validate_run{ok:true,...}}
totals{runs:4, cases:30, turns:36, total_requests_all_runs=<四 run 合计>}
index_file, index_file_sha256, code_version=<NEW_CODE_VERSION>
```
`37 = 6 回合 × 4 项/回合（query_embedding/rerank/query_expansion/answer）+ index_embedding 13 批`（`backend/src/mktkb/evaluation/p2_holdout_plan.py:85-90,299-329`；批数 13 见 `docs/reports/OBS-EVAL/P2/H2V3/run/plan-regen/ingest-batch-census.json` 的 `scenarios.pre_v05_without_v07.embed_posts_required`）。

`# 失败固定码`（全部零发送）：`cwd_not_project_root`、`holdout_root_missing`、`input_file_missing`/`input_path_rejected`、`ingest_batch_census_missing`、`ingest_batch_source_count_mismatch`、`dataset_case_count_invalid`/`dataset_turn_count_invalid`/`dataset_case_duplicate`、`scenario_counts_mismatch`、`run_business_date_*`（missing/invalid/duplicate/lifecycle_mismatch/anchor_forbidden）、`plan_ingest_batches_mismatch`、`plan_turn_count_mismatch`、`plan_case_count_mismatch`、`plan_operations_mismatch`、`plan_id_invalid`/`run_id_invalid`、`scenario_plan_mismatch`、`max_requests_mismatch`、`env_total_limit_conflict`（退出码 3）、`output_already_exists`/`output_not_empty`。

**`code_version` 是对「当前未提交工作树」取摘要，不是 HEAD。**
算法：`code_digest()`（`tools/p2_h2_controlled_execute.py:395-408`）
1. scope = `backend/src/mktkb`（递归 `*.py`，跳过 `__pycache__`）+ `tools/p2_h2_controlled_execute.py`（`:389-392`），v3 入口在导入时把**自身**追加进 scope（`tools/p2_h2_v3_controlled_execute.py:127-131`）；
2. 逐文件 `relative_posix_path + ":" + sha256(file)`，按路径排序，`"\n".join`；
3. 对该字符串取 SHA-256（UTF-8）即 `code_version`。
推论（务必遵守）：**计划生成之后，v3 入口文件本身、`backend/src/mktkb/**` 下任何 `.py` 的字节变化都会让 `code_changed_since_plan` 拒绝**（历史事故：入口文件 mtime/字节晚于计划生成，`docs/reports/OBS-EVAL/P2/H2V3/run/run-r0-report.md:31`）。所以顺序是：**源码改完 → 生成计划 → 只读预检 → 执行**，中间不许再动源码，也不许改 `R2_ROOT` 里的脚本副本去 import。

### S2 唯一性与"不重复"核对（回答 Q1 后半）

把 `<NEW_PLAN_SHA256>`、`<NEW_CODE_VERSION>` 换成 S1 的实际值后执行（只读扫描，只打印计数）：

```powershell
$PY -c @"
import glob,json,pathlib
new_plan='<NEW_PLAN_SHA256>'; new_code='<NEW_CODE_VERSION>'
R1_CODE='94a8809e74db899f9db23496590abb9e8580a4689dc63a20934de52d873022f0'
hits=[]
for p in glob.glob('docs/evidence/LOCAL-R1-20261101/PM/P2-LIVE-GO*.json')+glob.glob('docs/reports/OBS-EVAL/P2/**/run-receipt*.json',recursive=True):
    try: d=json.loads(pathlib.Path(p).read_text(encoding='utf-8'))
    except Exception: continue
    s=json.dumps(d)
    if new_plan in s: hits.append(('plan_sha256',p))
print('plan_sha256_collisions',len(hits)); [print(h) for h in hits]
print('code_changed_vs_r1', new_code!=R1_CODE)
"@
# 期望输出：plan_sha256_collisions 0；code_changed_vs_r1 True
```
判定规则（三条，口径不同，不能混）：
- `plan_sha256`：**必须新**。它是对整份计划内容（含 `created_utc`、`items` 里逐题 `case_id`）的规范化摘要（`backend/src/mktkb/evaluation/p2_contracts.py:995-1017`），换一个 `--created-utc` 即变。与 R1 的 `80d05194…`、历史 R2 的 `9c609a00…`/`d4437bd2…` 都不应相等。
- `code_version`：**应当与 R1 的 `94a8809e…` 不同**（修后工作树已变）；但要与 `check-only` 时重新计算的同值（否则 `code_changed_since_plan`）。
- `run_id`：**不能做到唯一，也不该拿它当唯一性判据**。v3 的 `TAG="P2-H2V3-20261115"` 是文件常量（`tools/p2_h2_v3_controlled_execute.py:154`），`run_id = f"{prefix}-r{index}-{scenario}"`（`:1497-1504`），CLI 无 `--run-id-prefix`，所以本次 run2 必然是 `p2-h2v3-20261115-r2-pre_v05_without_v07`，与 2026-11-15/16 的历史 R2 同名。**区分 attempt 只能靠 `plan_sha256` + `run-receipt.json` 字节 sha + `run_binding.attempt_scope_sha256`**（任务书 §10 防止返工第 1 条：run_id 可能沿固定规则同值，不能靠它区分）。同理 S8 的账本核对必须按 `plan_sha256` 过滤，不能只按 `run_id`。

### S3 完整 check-only 预检（回答 Q2）

**完整**预检 = 不带 `--plan-only`（不带即 `mode="full_contract_reload"`，会真正加载私有数据集/契约/source map；`tools/p2_h2_v3_controlled_execute.py:2140`）。

```powershell
$PY tools\p2_h2_v3_controlled_execute.py check-only `
  --binding '<R2_ROOT>\plan\bindings\run2-pre_v05_without_v07.binding.json' `
  --run-index 2 `
  --plan-set '<R2_ROOT>\plan\plans' `
  --seal-root '<ATTEMPT>\seal' `
  --out '<R2_ROOT>\preflight\check-only-run2.json' `
  --now 2026-11-17T18:05:00+08:00
```
`# 期望输出`（`ok=true` ⇒ 退出码 0；否则退出码 2）：
```
mode="full_contract_reload"   zero_paid_probes=true
checks = 16 项且全 ok：
  binding / code_version / plan_binding / plan_dial / plan_recompute / ingest_batch_derivation /
  public_binding / dataset_shape / contract_binding / contract_validate_run / source_map /
  go_binding / preflight / authorization / zero_write / zero_send
reasons=[]（=未通过的 check 名列表）
go{path=<…r2.pending.json>, sha256=<内容规范化摘要>, file_sha256=<文件字节摘要>,
   slot="simulated_pending", slot_simulated=true, plan_id_match=true, plan_sha_match=true, max_requests="unlimited"}
preflight{ok=true, reasons=[], requests_planned=37, requests_used=<账本累计预留数>,
          requests_remaining="unlimited", stage_limit_cny=20.0, stage_remaining_cny=<20-阶段已占>,
          total_limit_cny=40.0, total_remaining_cny=<40-项目已占>,
          worst_case_cny=<计划上界>, center_remaining_cny{4}, center_needs_cny{4}}
authorization{production_ready=true, max_requests="unlimited", requests_used, requests_remaining="unlimited",
              stage_remaining_cny, max_request_cny=0.5, go_sha256, budget_sha256, ledger_sha256=<历史前缀>}
quota{gate_mode="unlimited", governance_cap="unlimited", gate_cap_sources=[…],
      gate_enforced_by=["plan_dial.max_requests=unlimited","authorize_p2.go.scope.max_requests=unlimited",
                        "p2_authorization.P2Gate.item_quota(plan_sha256+item_id)","amount_gate(total/stage/cost_center)"],
      not_enforced_reason="unlimited_no_cumulative_request_gate",
      total_requests_all_runs=<四 plan 合计>, requests_this_run=37, used_before=<账本累计>, exceeds_gate=null}
zero_write{ledger_sha256_before==after, ledger_unchanged=true, budget_unchanged=true, reservation_count, result_count}
zero_send{external_attempts=0, local_attempts=0, external=[], local=[]}
binding_path / binding_sha256 / plan_path / plan_file_sha256 / plan_id / plan_sha256 / business_date="2026-11-20"
contract_validate_run{ok=true, code="index_embedding_batches_v3_derived",
                      differing_keys=["items[index_embedding].requests"],
                      authorized_delta{item_id, plan_requests, contract_recipe_requests, derived_from}}（code=null 表示连这一格也逐值相等）
dataset_shape{ok:true}   source_map{ok:true}
evidence_file / evidence_sha256（给了 --out 时）
```
**"预检不付费"如何证明**（三条互相独立，缺一不可）：
1. `zero_paid_probes=true` + `mode`（`tools/p2_h2_v3_controlled_execute.py:2138-2141`）；
2. `zero_send.external_attempts=0` —— 入口装了 socket 守卫并在主体前做正对照（外连 `203.0.113.1:80` 必须被拦），主体结束时外部尝试计数必须为 0（`:479-539,2479-2488`）；
3. `zero_write.ledger_unchanged=true` 且 `budget_unchanged=true`，并附前后文件 sha（`:2104-2116`）—— 没有新增预留/没有写预算。
注意：check-only **不需要凭据**（它不读 `.env`），账号密钥不是预检门槛；`authorization.production_ready=true` 由"GO/预算来自固定路径 + `MKTKB_PROJECT_TOTAL_LIMIT_CNY` 已设且等于预算 + 快照来自固定账本"三者共同给出（`backend/src/mktkb/evaluation/p2_authorization.py:653-657`）。

`--seal-root` 的副作用要知道：check-only 会在该目录写一个 run 级租约文件并在退出时删除，目录本身会留下（空）。这**不影响**随后 `run` —— `run` 对 `--seal-root` 的要求是"不存在或为空"（`require_new_or_empty_dir`，`tools/p2_h2_controlled_execute.py:311-318,1549-1550`）。但 `--out` 指向的文件**必须不存在**（`_write_json_new`，`tools/p2_h2_v3_controlled_execute.py:414-418`）。
`# 失败固定码`（零发送）：
- 预检前置：`go_missing_for_run`（该 run 的 GO 不存在，`tools/p2_h2_v3_controlled_execute.py:2066-2067`）、`run_claim_held`（同 run 有活占位/并发 check-only）、`plan_set_missing`/`plan_set_invalid`/`plan_set_incomplete`、`scenario_binding_changed`、`code_changed_since_plan`、`input_changed_since_plan`/`input_size_changed`、`plan_file_changed`/`plan_file_missing`、`plan_identity_mismatch`、`evidence_binding_mismatch`、`pipeline_changed`；
- 授权/金额（`P2AuthorizationError.reason`）：`path_missing`、`go_document_invalid`、`legacy_go_document`、`go_schema_invalid`、`go_stage_mismatch`、`text_invalid`、`go_nonce_invalid`、`go_time_invalid`、`go_not_yet_valid`、`go_expired`、`go_budget_total_mismatch`、`go_plan_id_mismatch`、`go_plan_sha256_mismatch`、`go_operation_unauthorized`、`go_cost_center_unauthorized`/`go_cost_center_below_plan`、`go_stage_limit_missing`/`go_stage_limit_below_plan`、`go_max_requests_invalid`/`go_max_requests_below_plan`/`go_max_requests_over_hard_cap`、`go_max_request_cny_below_plan`、`go_ledger_path_not_fixed`/`go_ledger_binding_mismatch`、`budget_total_mismatch`/`budget_stage_missing`/`budget_stage_below_plan`/`budget_history_mismatch`、`env_total_limit_missing`/`env_total_limit_mismatch`、`stage_budget_insufficient`/`total_budget_insufficient`/`center_budget_insufficient:<center>`/`center_accounting_inconsistent`、`stage_allocation_missing`/`stage_allocation_below_plan`、`request_budget_insufficient`。

### S4 GO 归档留痕与新签（回答 Q3）

槽位事实：`docs/evidence/LOCAL-R1-20261101/PM/P2-LIVE-GO.json` 现在装的是 R1 run2 的 GO —— 文件字节 `38f3c3f5dd6f2c828b66a3d96ee27d5a82ceed25ac49ecaba70ab7269c95fda3`（S0 已核），内容规范化摘要 `4bf0d479d2f89e4750c11081c590217b12ff7f296f09b78d2226494de1d6f5bf`，`scope.plan_sha256=80d05194…`。
R2（`run_index=2`）的 GO 落点是 **`P2-LIVE-GO.v3-r2.pending.json`**（`_go_path_for_run`：index 0 → 固定槽位，1..3 → `.v3-r{index}.pending.json`，`tools/p2_h2_v3_controlled_execute.py:1827-1830`）；**执行时 `run` 读的是固定槽位**（`p2_live.open_live_gate` → `P2Gate.open` 用 `P2_GO_PATH`），所以两份必须**逐字节相同**，否则 `bindings.go_sha256` 与 check-only 的 `go.sha256` 会对不上。

**S4.1 先归档旧槽位件（不删除、不改内容、不覆盖已有归档）**
归档命名规则（同目录既有件的实际规律）：`<原文件名去 .json>.<tag>.archived.json`，`tag` 记录结果/原因：`.done`、`.pending`、`.previous`、`.oversize-text`。例：`P2-LIVE-GO.v3-r1repair-20261117-r2.done.archived.json`、`P2-LIVE-GO.v3-r2.oversize-text-20261116.archived.json`。

```powershell
$PY -c @"
import hashlib,pathlib,sys
src=pathlib.Path('docs/evidence/LOCAL-R1-20261101/PM/P2-LIVE-GO.json')
raw=src.read_bytes(); sha=hashlib.sha256(raw).hexdigest()
assert sha=='38f3c3f5dd6f2c828b66a3d96ee27d5a82ceed25ac49ecaba70ab7269c95fda3', sha
pm=src.parent
same=[p.name for p in pm.glob('P2-LIVE-GO*.archived.json') if hashlib.sha256(p.read_bytes()).hexdigest()==sha]
print('slot_sha256',sha); print('byte_identical_archives',same)
dst=pm/'P2-LIVE-GO.v3-r2prep-20261117.pre.archived.json'
if dst.exists(): print('archive_exists_noop',dst.name)
else:
    with dst.open('xb') as f: f.write(raw)          # O_EXCL：绝不覆盖
    print('archived',dst.name,hashlib.sha256(dst.read_bytes()).hexdigest())
"@
# 期望输出：slot_sha256=38f3c3f5…；byte_identical_archives 至少含 'P2-LIVE-GO.v3-r1repair-20261117-r2.done.archived.json'
#          archived …pre.archived.json 38f3c3f5…（若已存在则 archive_exists_noop）
```
要点：现存归档里**已经有两份字节相同**的旧件（`…v3-r1repair-20261117-r2.done.archived.json` 与 `…v3-r1repair-20261117-r2.pending.done.archived.json`），所以本次归档是"留痕 + 引用"，不是"抢救唯一副本"；`xb` 语义保证不覆盖历史。**禁止 `Move-Item` 覆盖同名归档、禁止 `Remove-Item` 旧件**。

**S4.2 新签一份 R2 GO（由有权方执行）**

GO 必填字段是**恰好 12 个顶层键 + 7 个 scope 键，多一个少一个都拒**（`_GO_KEYS`/`_GO_SCOPE_KEYS`，`backend/src/mktkb/evaluation/p2_authorization.py:99-121`；`_exact` 在 `:207-215`）：

| 键 | 约束（校验器原文口径） | R2 该写什么 |
|---|---|---|
| `document` | 必须 `P2-LIVE-GO`；写 `S2-LIVE-GO` → `legacy_go_document` | `"P2-LIVE-GO"` |
| `schema_version` | 必须 `p2-live-go/v0.1` | 同 |
| `stage` | 必须 `P2-LIVE` 且等于 plan.stage | `"P2-LIVE"` |
| `authorization` | 非空且 **len ≤ 200**（`_text` 默认 `maximum=200`，`:196-204` 用于 `:452`） | 一段 ≤180 字符的范围英文/中文摘要（见下） |
| `issued_by` | 非空且 ≤200（`:453`） | `"<签发人> - delegated by owner 2026-11-17 (scope: r2 pre_v05_without_v07)"` |
| `nonce` | 非空、**无空白**、len ≤256 且 ≥16（`:454-456`） | 随机 32 位 hex（见下） |
| `issued_utc` / `expires_utc` | 带时区 ISO；`expires>issued`；运行时刻须落在区间内（`:457-464`） | 覆盖本次单跑的窗口（如 issued=当日实际时刻，expires=+24h） |
| `budget_ledger_path` | 相对仓库根或绝对；解析后必须等于固定账本（`:580-587`） | `"docs/evidence/LOCAL-R1-20261101/budget/live-ledger.jsonl"` |
| `budget_ledger_sha256` | ≤64、无空白；须等于账本**历史前缀**摘要或当前文件摘要，且 `ledger_binding_ok`（`:588-598`） | `f4710b1869fe43b9a609b58f772549f76370fbadd54f93685b76211d4b47a014`（`historical_import` 行前缀摘要，恒定；见 S4.3 复核） |
| `budget_total_limit_cny` | >0 且等于 plan 的 40 | `40.0` |
| `scope.plan_id` / `scope.plan_sha256` | 必须**逐值等于本次计划** | S1 的 run2 值 |
| `scope.operations` | 非空字符串数组、必须是已注册操作、且覆盖计划全部操作 | `["answer","index_embedding","query_embedding","query_expansion","rerank"]` |
| `scope.cost_centers_cny` | 必须**恰好**四个中心，且每个 ≥ 计划分配 | `{"answer_retrieval":8.5,"ocr":6.5,"judge":3.0,"independent":2.0}` |
| `scope.stage_limits_cny` | 必须含 `P2-LIVE` 且 ≥20 | `{"P2-LIVE":20.0}` |
| `scope.max_requests` | `"unlimited"` 或 1..1600 的整数；**计划是 unlimited 时 GO 也必须 unlimited**（`:511-518`） | `"unlimited"` |
| `scope.max_request_cny` | >0 且 ≥ plan.reserve_peak_cny | `0.5` |

`authorization` 200 字符上限是历史 `text_invalid` 的真实原因：同目录 4 份归档件的 `authorization` 长度 221/221/222/237（文件名带 `oversize-text`），而通过的件是 171/190。**先在生成脚本里断言 `len(authorization)<=180`**。
`delegated by owner` 没有独立字段（`_GO_KEYS` 是封闭集合，加字段直接 `field_unknown`），只能写进 `issued_by` 文本——历史写法：`"External dev assistant - delegated by owner 2026-11-17 (scope: r1 repair run2)"`（R1 槽位件）、`"PM (lead) – delegated by owner 2026-11-16 (scope: r0+r1+r2+r3 full H2 verification)"`（fullverify 件）。**能被授权的是主人；文本只记录归属，不构成授权。**

```powershell
$PY -c @"
import hashlib,json,pathlib,secrets
PM=pathlib.Path('docs/evidence/LOCAL-R1-20261101/PM')
plan=json.loads(pathlib.Path(r'<R2_ROOT>\plan\plans\run2-pre_v05_without_v07.plan.json').read_text(encoding='utf-8'))
sha=lambda b: hashlib.sha256(b).hexdigest()
def canon(d):
    return sha(json.dumps(d,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf-8'))
authorization=('Owner 2026-11-17 approval: H2 v3 r2 repair verification (pre_v05_without_v07) at most once; '
               '40 CNY total; unlimited requests per current contract; 0.5 CNY/req; 5 ops; zero retry')
issued_by='External dev assistant - delegated by owner 2026-11-17 (scope: r2 pre_v05_without_v07)'
assert len(authorization)<=180 and len(issued_by)<=200
go={'document':'P2-LIVE-GO','schema_version':'p2-live-go/v0.1','stage':'P2-LIVE',
    'authorization':authorization,'issued_by':issued_by,'nonce':secrets.token_hex(16),
    'issued_utc':'<实际签发时刻，带 +08:00>','expires_utc':'<发行时刻+24h，带 +08:00>',
    'budget_ledger_path':'docs/evidence/LOCAL-R1-20261101/budget/live-ledger.jsonl',
    'budget_ledger_sha256':'f4710b1869fe43b9a609b58f772549f76370fbadd54f93685b76211d4b47a014',
    'budget_total_limit_cny':40.0,
    'scope':{'plan_id':plan['plan_id'],'plan_sha256':plan['plan_sha256'],
             'operations':['answer','index_embedding','query_embedding','query_expansion','rerank'],
             'cost_centers_cny':{'answer_retrieval':8.5,'ocr':6.5,'judge':3.0,'independent':2.0},
             'stage_limits_cny':{'P2-LIVE':20.0},'max_requests':'unlimited','max_request_cny':0.5}}
dst=PM/'P2-LIVE-GO.v3-r2.pending.json'
raw=(json.dumps(go,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode('utf-8')
if dst.exists():
    old=json.loads(dst.read_text(encoding='utf-8'))
    print('pending_exists plan_sha256_match',old.get('scope',{}).get('plan_sha256')==plan['plan_sha256'])
else:
    with dst.open('xb') as f: f.write(raw); print('wrote',dst.name)
print('go_content_sha256',canon(go)); print('go_file_sha256',sha(dst.read_bytes())); print('nonce_len',len(go['nonce']))
"@
# 期望输出：go_content_sha256=<NEW_GO_SHA256>（这将是 receipt.bindings.go_sha256）
#          go_file_sha256=<归档/装槽核对用>；nonce_len=32
```
装槽（**复制，不改写内容**；与 R1 的装槽动作一致：`docs/reports/OBS-EVAL/P2/H2V3/run/run-r123-report.md:37-46`）：
```powershell
$PY -c @"
import hashlib,pathlib
PM=pathlib.Path('docs/evidence/LOCAL-R1-20261101/PM')
src=PM/'P2-LIVE-GO.v3-r2.pending.json'; dst=PM/'P2-LIVE-GO.json'
raw=src.read_bytes()
old=dst.read_bytes()
assert hashlib.sha256(old).hexdigest()=='38f3c3f5dd6f2c828b66a3d96ee27d5a82ceed25ac49ecaba70ab7269c95fda3'
tmp=dst.with_name(dst.name+'.tmp'); tmp.write_bytes(raw); tmp.replace(dst)   # 原子替换
print('installed',hashlib.sha256(dst.read_bytes()).hexdigest())
print('byte_identical',dst.read_bytes()==src.read_bytes())
"@
# 期望输出：installed=<go_file_sha256>；byte_identical True
```
装槽后**立刻重跑 S3 的 check-only**：`go.file_sha256` 应等于 pending 的字节 sha、`go.sha256` 等于内容摘要、`go.plan_sha_match=true`/`plan_id_match=true`、`authorization.production_ready=true`。若报 `go*` 系列码，说明 pending 与槽位不一致或内容不合规——**不要用"先跑跑看"绕过**。

**S4.3 `budget_ledger_sha256` 的只读复核**（确认历史前缀没变；前缀只由开头连续 `historical_import` 行决定，`backend/src/mktkb/live_authorization.py:400-433`）：
```powershell
$PY -c "import sys;sys.path.insert(0,'backend/src');from mktkb.live_authorization import historical_prefix_sha256 as h;print(h('docs/evidence/LOCAL-R1-20261101/budget/live-ledger.jsonl'))"
# 期望输出：f4710b1869fe43b9a609b58f772549f76370fbadd54f93685b76211d4b47a014
```

**`payload_sha256` 与文件字节 sha 的差别（必须分列报）**
- `payload_sha256(x)` = `sha256(json.dumps(x, ensure_ascii=False, sort_keys=True, separators=(",",":"), allow_nan=False).encode("utf-8"))`（`backend/src/mktkb/evaluation/p2_contracts.py:387-399`）；`authorize_p2` 用它算 `go_sha256=payload_sha256(go)`（`p2_authorization.py:636`），回执里就是 `bindings.go_sha256`。
- 文件字节 sha = 磁盘上那几个字节（含缩进/换行），用于归档/装槽"逐字节相同"的证明。
- 二者**不相等是正常的**。本机已实证：槽位件内容摘要 `4bf0d479…` ≠ 文件字节 `38f3c3f5…`（与 `docs/reports/OBS-EVAL/P2/H2V3/r1-repair-external-20261117/R1-FINAL-CHAIN.md:16-17` 一致）。核对方法：
  - 内容摘要：`payload_sha256(json.load(go))`，须**等于**回执 `bindings.go_sha256`；
  - 字节摘要：`sha256(open(go,'rb').read())`，须**等于** pending 与槽位两份文件的字节 sha，且等于归档件字节 sha。

### S5 逐 plan 配额与金额核对（回答 Q4）

四项计数各有出处，**不许互相代替**：

| 口径 | 字段（JSON 路径） | 出处 |
|---|---|---|
| `planned` | 计划文件 `total_requests`；check-only `preflight.requests_planned`；回执 `requests.planned` | `p2_contracts.py:931-933`；`p2_h2_v3_controlled_execute.py:2160`；`p2_h2_controlled_execute.py:2493-2536` |
| `attempts_reserved`（纪律口径） | 回执 `requests.attempts_reserved` + `requests.attempts_scope="all_attempts"` | `p2_runner.py:1157-1164` |
| `real_sends`（出网） | 回执 `real_sends`；summary `network.outbound_attempts` | `p2_h2_controlled_execute.py:2539-2544` |
| answer 侧 `reserved` / `sent` / `settled` | 回执 `requests.reserved` / `requests.sent` / `requests.settled_cny`（`source="run_result"` 时来自 `P2RunResult`；否则回落到 summary `requests.*`） | `p2_h2_controlled_execute.py:2493-2536`；summary 侧同名键在 `p2_runner.py:2515-2535` |

金额最坏上界怎么算（**从计划派生，不手填**）：
- 单次上界 `bound_cny` = 价格画像 token 上界 × 已核费率（chat：`prompt_cap*in + completion_cap*out`；embedding/rerank：`total_cap*unit`；`p2_contracts.py:588-606`）；
- 逐项 `worst_case_cny = bound_cny × requests`（`:777-779`）；计划级 `worst_case_cny = Σ`（`:947-951`）；
- 单次在飞峰值 `reserve_peak_cny = max(item.bound_cny)`（`:953-956`）；
- 三处闸：`worst_case ≤ stage_remaining`、`≤ total_remaining`、每个中心 `used + center_needs ≤ center_limit`（`p2_authorization.py:372-392`）。
`# 期望输出`：`preflight.ok=true`、`worst_case_cny` ≤ `stage_remaining_cny`（阶段 20 元内）、`center_needs_cny` 逐中心 ≤ `center_remaining_cny`。历史同形计划（37 请求）实测 `worst_case_cny=0.291968 元`（`docs/reports/OBS-EVAL/P2/H2V3/run/run-r123-report.md:29`），**仅作量级参考，以本次计划实际值为准**。

`unlimited` 到底取消了什么：
- 取消的只是**全局累计次数上限**：`preflight_p2` 在 `max_requests="unlimited"` 时把 `requests_remaining` 设为 `"unlimited"`（`p2_authorization.py:369-370,406-407`），`_guard_common` 只在有限值时才判累计数（`:988-989`），`quota.not_enforced_reason="unlimited_no_cumulative_request_gate"`（`tools/p2_h2_v3_controlled_execute.py:1910-1918`）。
- **保留**的三道硬约束：
  1. 逐 `plan_sha256 + item_id` 配额：预留前扫账本，`metadata.plan_sha256 == 本计划` 且 `item_id` 相同则计数，`used >= item.requests` 即 `attempt_quota_exhausted`；**不看 run_id**，所以换 run_id/重开 Gate/重启进程都不清零（`p2_authorization.py:998-1020`；预留事件确实带 `metadata{plan_id,plan_sha256,item_id,operation,cost_center}`，`:1090-1096`）；
  2. 金额闸：阶段 20 / 项目 40 / 单请求 0.5 / 四中心 8.5-6.5-3-2，逐次预留都在锁内再判（`p2_authorization.py:951-980`、`p2_contracts.py:68-76`）；
  3. 历史计数与预算历史占用不许重置：`budget_history_mismatch`（`p2_authorization.py:545-551`）、`_historical_prefix_bytes` 拒绝新空账本（`live_authorization.py:400-419`）。
- `unlimited` 的合法性本身也受限：只允许 P2-LIVE 阶段（`backend/src/mktkb/rag/budget.py:280-286`），且计划与 GO 必须同为 unlimited（`p2_authorization.py:517-518`、`tools/p2_h2_v3_controlled_execute.py:1237-1238`）。

### S6 单次真实执行（回答 Q5）

```powershell
$PY tools\p2_h2_v3_controlled_execute.py run `
  --binding '<R2_ROOT>\plan\bindings\run2-pre_v05_without_v07.binding.json' `
  --run-index 2 `
  --out-dir '<ATTEMPT>\out' `
  --evidence-root '<ATTEMPT>\evidence' `
  --seal-root '<ATTEMPT>\seal' `
  --evidence-key-file '<ATTEMPT>\ev.key' `
  --env-file .env
```
参数依据：`tools/p2_h2_v3_controlled_execute.py:2404-2413`。**只跑一次**；不做第二次调用（重试=0）。

必需环境变量（**只列名字，值不打印**）：`.env` 里必须有 6 个凭据键 `MKTKB_MODEL_API_KEY`、`MKTKB_MODEL_BASE_URL`、`MKTKB_MODEL_NAME`、`DASHSCOPE_API_KEY`、`MKTKB_OCR_SECRET_ID`、`MKTKB_OCR_SECRET_KEY`（`tools/p2_live_execute.py:54-60`；入口只认 `AUTHORIZED_ENV_PATH = <repo>/.env`，且文件名必须字面是 `.env`，`tools/p2_h2_controlled_execute.py:104,566-611`）。产品自有键 `MKTKB_CSRF_SECRET`/`MKTKB_ADMIN_PASSWORD`/`MKTKB_EMPLOYEE_PASSWORD`/`MKTKB_TRUSTED_ORIGINS`/`MKTKB_COOKIE_SECURE` 被按形状忽略；`MKTKB_P2_HOLDOUT_ROOT`/`MKTKB_P2_HOLDOUT_KEY_FILE`/`MKTKB_PROJECT_TOTAL_LIMIT_CNY` 由入口自己按 binding 输入与本进程常量注入，`.env` 里的同名值会被剥离（`:107-121,545-563`）。**shell 里不要把 `MKTKB_PROJECT_TOTAL_LIMIT_CNY` 预设成别的值**，否则退出码 3 `env_total_limit_conflict`（`tools/p2_h2_v3_controlled_execute.py:68-79,2470-2478`）。

"按 attempt 独立"怎么实现（不是口头约定，是代码强制）：
- `--out-dir` 必须**不存在**；`--evidence-root`/`--seal-root` 必须不存在或为空（`check_target_paths`，`tools/p2_h2_controlled_execute.py:1547-1568`），否则 `output_already_exists`/`output_not_empty`/`path_not_directory`；
- 入口还会在 `<seal_root>` 的**父目录**写 `v3-entry-<run_id>.json` 旁证文件，已存在即 `output_already_exists`（`tools/p2_h2_v3_controlled_execute.py:2359-2360`）——这也是"每次 attempt 一个目录"的硬约束；
- run 级单写者租约：全机登记处 + seal 目录双占位，O_EXCL，PID+进程启动标记判活（`:317-387`），占用中 `run_claim_held`；
- 封存目录 `seal_root/<safe(run_id)>` 已存在即 `seal_target_exists`（`tools/p2_h2_controlled_execute.py:2054-2057`）。

首错停 / 零重试如何保证：
- 入口只在 `run_command` 里调用一次 `_execute_loaded`，捕获首个异常即固定分类、不重入（`tools/p2_h2_v3_controlled_execute.py:2322-2334`；分类表 `tools/p2_h2_controlled_execute.py:2471-2490`：`refused`/`blocked`/`failed` + 固定码）；
- runner 本身串行、自动重试 0，任何一轮传输错误/超时/`service_error` 即停，后续 case 显式 `not_executed`，不补跑不挑题（`backend/src/mktkb/evaluation/p2_runner.py:6-18`）；
- 发送前两道门（预留前 `_request_guard`、预留后发送前 `_post_reserve_guard`）+ 逐次授权重校验；失败一律停在 HTTP 之前，且已发生的预留写 `status=failed` 保守留账、不回 0、不释放（`p2_authorization.py:13-17,991-1043`）；
- 门一旦 `stop`，后续 `begin` 直接 `gate_stopped`（`:1066-1067`）。

`# 期望输出`（stdout 顶层）：
```
ok=true
schema_version=p2-h2v3-controlled-run-receipt/v0.1
receipt{…完整回执…}    sidecar{…}    sidecar_payload{plan_dial, plan_recompute, plan_recompute_phase="presend",
                                                   contract_validate_run, source_map, scoring_map, receipt_ok, receipt_status}
```
回执内必查（`tools/p2_h2_controlled_execute.py:2775-2841`）：`status="succeeded"`、`stop_code=null`、`error_code=null`、`run_index=2`、`run_id`、`scenario_id="pre_v05_without_v07"`、`plan_id`、`plan_sha256=<NEW_PLAN_SHA256>`、`business_date="2026-11-20"`、`execution_mode="live"`、`chat_model`、`requests{...}`、`evidence{...}`、`cleanup{...}`、`seal{...}`、`real_sends`、`bindings{go_sha256,ledger_sha256,attempt_scope_sha256,code_version,config_sha256,binding_sha256}`、`run_binding{...}`、`case_plan{path,sha256,cases:5,turns:6}`、`evidence_key_sha256`、`receipt_path`。

`# 失败固定码`（发送前，零发送）：`run_claim_held`、`plan_dial_failed`、`plan_recompute_failed`、`code_changed_since_plan`、`run_date_changed`、`scenario_binding_changed`、`scenario_plan_mismatch`、`output_already_exists`/`output_not_empty`、`evidence_key_missing`/`evidence_key_invalid`、`env_file_missing`/`env_file_not_authorized`/`env_required_missing`、`live_env_missing`/`live_env_invalid`/`live_chat_model_not_authorized`/`live_ocr_disabled`、`env_chat_model_mismatch`/`env_chat_host_mismatch`/`env_dashscope_host_mismatch`/`env_ocr_region_mismatch`/`env_ocr_disabled`、`live_requires_production_ready`、`live_operation_not_authorized`。
运行中/运行后（runner 侧 stop_code，回执 `stop_code`）：`plan_authorization_mismatch`、`authorization_expired`、`operation_unauthorized`、`request_cap_exceeded`、`live_requires_real_gate`、`production_not_ready`、`holdout_requires_purge`、`ingest_failed`、`plan_item_missing`/`plan_item_ambiguous`、`pre_send_refused`、`turn_timeout`、`product_service_error`、`usage_evidence_missing`、`gate_error`、`adapter_error`、`open_conversation_failed`、`artifact_validation_failed`、`attempt_accounting_mismatch`、`no_case_executed`、`cancelled`（`p2_runner.py` 的 `STOP_*` 常量）。

### S7 封存 / 证据 / 清理的核对（回答 Q6）

回执里逐项拉到 `true` 即可（字段来源见括号）：
```powershell
$PY -c @"
import json,pathlib
r=json.loads(pathlib.Path(r'<ATTEMPT>\seal\p2-h2v3-20261115-r2-pre_v05_without_v07\run-receipt.json').read_text(encoding='utf-8'))
def g(*ks):
    cur=r
    for k in ks: cur=cur.get(k) if isinstance(cur,dict) else None
    return cur
print('ok',r['ok'],'status',r['status'],'stop_code',r['stop_code'],'error_code',r['error_code'])
print('sealed',g('seal','sealed'),'mode',g('seal','mode'),'seal_manifest_sha256',g('seal','seal_manifest_sha256'))
print('out_tree_sha256',g('seal','out_tree_sha256'),'evidence_tree_sha256',g('seal','evidence_tree_sha256'))
print('evidence_readback_ok',g('evidence','readback_ok'),'turn_files',g('evidence','turn_files'),
      'status_counts',g('evidence','status_counts'),'manifest_turn_count',g('evidence','manifest_turn_count'))
print('plaintext_clean',g('cleanup','plaintext_clean'),'needles',g('cleanup','plaintext_scan','needles'),
      'hit_count',g('cleanup','plaintext_scan','hit_count'),'business_db_removed',g('cleanup','business_db_removed'),
      'trace_db_removed',g('cleanup','trace_db_removed'),'data_dir_removed',g('cleanup','data_dir_removed'),
      'run_dir_removed',g('cleanup','run_dir_removed'),'cleanup_errors',g('cleanup','cleanup_errors'))
print('real_sends',r['real_sends'],'requests',r['requests'])
print('bindings',r['bindings'],'case_plan',r['case_plan'],'case_plan_error',r['case_plan_error'])
print('evidence_key_sha256',r['evidence_key_sha256'],'receipt_path',r['receipt_path'])
"@
# 期望输出：
#   ok True / status succeeded / stop_code None / error_code None
#   sealed True / mode read_only_archive / seal_manifest_sha256=<封存清单字节 sha>
#   evidence_readback_ok True / turn_files=6 / status_counts={"complete":6} / manifest_turn_count=6
#   plaintext_clean True / needles>0 / hit_count=0 / business_db_removed True / trace_db_removed True /
#   data_dir_removed True / run_dir_removed True / cleanup_errors []
#   case_plan{cases:5,turns:6,sha256:…} / case_plan_error None
```
字段语义（源码）：`seal_trees` 写 `seal-manifest.json` 并**读回比对**，不等即 `seal_readback_mismatch`；`sealed=true` 只在 out/证据树只读化前后摘要一致时成立（`tools/p2_h2_controlled_execute.py:2050-2100`）。`plaintext_scan` 由内存题干/答案针扫描（`:1769-1839`），命中即删残留文件，若 `controlled/case-plan.json` 命中则 fail closed（`:1999-2007`）。`business_db_removed` 是业务库（含 `-wal/-shm/-journal`）全部不存在的布尔（`:2018-2021`）。
**明文终扫的独立复核**（不依赖回执自证）：对 `<ATTEMPT>\out` 再扫一次用同一批针——但针只在内存、不落盘，所以独立复核只能核"回执的 needles/hit_count 字段 + out 目录只剩 controlled/ 的安全件"：
```powershell
Get-ChildItem -Recurse -File '<ATTEMPT>\out' | ForEach-Object { $_.FullName.Replace('<ATTEMPT>\out\','') }
# 期望输出：只有 controlled\case-plan.json 与（可选）controlled\composition-part.json
```
**证据回读（readback）**：`_collect_evidence` 在 purge 之后从磁盘重读 `turn-*.fernet` 与 `manifest-*.fernet`，逐份解密并核对 `expected_bindings` 与 `run_binding`，任一不符即计入 `errors`（`tools/p2_h2_controlled_execute.py:2131-2204`）。回执 `evidence.readback_ok=true` 即代表"purge 前确实写盘且可解密、绑定一致"。原始 sha 见 `evidence.manifest_sha256`。

### S8 判定链、结果读取与账本对账（回答 Q7）

判定链入口（零模型/检索，只读密文 + 冻结输入）：
```powershell
$PY 'docs\reports\OBS-EVAL\P2\H2V3\r2-repair-external-20261117\work\r2_recompute_axes.py' `
  --runs 2 `
  --work '<ATTEMPT>' `
  --bindings '<R2_ROOT>\plan\bindings' `
  --compat p2-refusal-compat/v0.6 `
  --out '<R2_ROOT>\judge\recompute-v2-r2-attempt1.json'
# 期望输出（stdout/JSON）：ok、selected_runs=[2]、per-case quality_status/evidence_complete/missing_codes、
#   new_axes/historical_axes{state,reason}、hard_failed、aggregate.hard_failures、unknown_cases、
#   consistency_passed=true、hard_failed_flags_equal_violation_union=true、quality_case_plan_match=true
```
依据：`--runs`/`--work`/`--bindings`/`--compat`/`--out` 参数在 `work/r2_recompute_axes.py:665-694`；它读 `<work>/out/controlled/case-plan.json`、`<work>/evidence/<run_id>/turn-*.fernet`、`<work>/seal/<run_id>/run-receipt.json`（单 run 根布局也接受，`work/r1_recompute_axes.py:389-396` 同构）；`--compat` 取值含 `p2-refusal-compat/v0.6`（`backend/src/mktkb/evaluation/p2_hard_evidence.py:979-989`）。
**先在副本上改两处**（R1 常量未参数化，属必须适配项，见 §4）：`work/r2_recompute_axes.py:97` 的 `KEY_PATH` 指向 `<ATTEMPT>\ev.key`；`:90` 的 `WORK` 只在你不传 `--work` 时才生效（传了就以参数为准）。
四轴/质量的卡片字段（`backend/src/mktkb/evaluation/p2_hard_evidence.py:4010-4036`）：`total/executed/errors/passed/failed/hard_failures/hard_failures_by_kind{4 轴}/missing_evidence_cases/verified/axes{safety,cross_user,cross_entity,stale_source}×{planned,passed,not_applicable,unknown,violations,checked}`；`release_ready` 恒 `false`（不当发布声明用）。
SAFE 投影（逐层首偏离，只接固定码/计数/布尔/哈希）：
```powershell
$PY 'docs\reports\OBS-EVAL\P2\H2V3\r2-repair-external-20261117\work\r2_safe_project.py' `
  --key '<ATTEMPT>\ev.key' `
  --binding '<R2_ROOT>\plan\bindings\run2-pre_v05_without_v07.binding.json' `
  --evidence-root '<ATTEMPT>\evidence' `
  --receipt '<ATTEMPT>\seal\p2-h2v3-20261115-r2-pre_v05_without_v07\run-receipt.json' `
  --seal-manifest '<ATTEMPT>\seal\p2-h2v3-20261115-r2-pre_v05_without_v07\seal-manifest.json' `
  --out-dir '<R2_ROOT>\judge\safe-projection'
```

账本 **reservation/result 逐 ID 配对**（只读；**必须按 `plan_sha256` 过滤**，因为 run_id 会重复）：
```powershell
$PY -c @"
import json,pathlib,collections
led=pathlib.Path('docs/evidence/LOCAL-R1-20261101/budget/live-ledger.jsonl')
new_plan='<NEW_PLAN_SHA256>'; run_id='p2-h2v3-20261115-r2-pre_v05_without_v07'
res,out,by_op=collections.Counter(),collections.Counter(),collections.Counter()
extra=0
for line in led.read_text(encoding='utf-8').splitlines():
    if not line.strip(): continue
    e=json.loads(line)
    md=e.get('metadata') or {}
    if e.get('event')=='reserved':
        if md.get('plan_sha256')==new_plan:
            res[e['reservation_id']]+=1; by_op[md.get('operation')]+=1
        elif e.get('run_id')==run_id: extra+=1
    elif e.get('event')=='result':
        if e.get('run_id')==run_id: out[e['reservation_id']]+=1
ids=set(res); paired={i for i in ids if out.get(i)}
print('attempt_reservations',sum(res.values()),'unique',len(ids),'duplicates',sum(v-1 for v in res.values()))
print('paired',len(paired),'unpaired',sorted(ids-set(out))[:5],'by_operation',dict(by_op))
print('results_same_run_id_all_attempts',sum(out.values()),'results_for_this_plan',len(paired))
print('reserved_rows_same_run_id_other_plan',extra)
"@
# 期望输出：duplicates 0、paired == unique == 回执 requests.attempts_reserved、unpaired []、
#          by_operation 与回执 requests.attempts_by_operation 逐项相等
# 注意（本机已实测的口径差异）：results_same_run_id_all_attempts 会显著大于 results_for_this_plan，
#   因为 result 事件只带 run_id + reservation_id，不带 plan 身份，同 run_id 的历史 attempt 结果也在其中；
#   reserved_rows_same_run_id_other_plan>0 同理。所以配对必须"以本次计划的 reserved id 为驱动"，
#   绝不能用 results 的行数去反推本次尝试数（否则会把历史行算进本次）。
```
项目/阶段/成本中心累计从哪算：**只从共享账本重算**，入口只用 `read_ledger_snapshot()`（只读，账本旁瞬时 `.lock`，不追加事件、不改预算，`p2_authorization.py:271-325`）：
```powershell
$PY -c @"
import sys,json;sys.path.insert(0,'backend/src')
from mktkb.evaluation import p2_authorization as p2a
s=p2a.read_ledger_snapshot()
print(json.dumps({'ledger_sha256':s.ledger_sha256,'prefix':s.historical_prefix_sha256,
 'total_limit_cny':s.total_limit_cny,'accounted_cny':s.accounted_cny,'historical':s.historical_accounted_cny,
 'stage_allocations':s.stage_allocations_cny,'p2_stage_accounted_cny':s.p2_stage_accounted_cny,
 'p2_center_accounted_cny':s.p2_center_accounted_cny,'reservation_count':s.reservation_count,
 'result_count':s.result_count,'production_ready':s.production_ready},ensure_ascii=False,indent=2,sort_keys=True))
"@
# 期望输出：reservation_count == result_count（历史全配对）；
#          accounted_cny = 项目累计（≤40）；p2_stage_accounted_cny = 阶段累计（≤20）；
#          p2_center_accounted_cny 四中心各自 ≤ 8.5/6.5/3/2；production_ready true
```
**只读重放**（复算四轴的第二种入口，用于交叉验证 r2_recompute_axes 的结论）不重放模型/检索，只吃密文与冻结契约：`backend/src/mktkb/evaluation/p2_hard_evidence.py:3975-4007`（`recompute_hard_evidence`）与 `:4039-4054`（`run_recompute_cli`，参数 `evidence_dir/case_plan_path/cases_path/annotation_path/key_file/out_path`）。**注意**：`run_recompute_cli` 需要单独的 `cases_path`（CaseSpec JSON），其生成方式本仓未在 R2 目录留现成件 → 见 §5 `UNVERIFIED-2`。

两个 GO 哈希分列核对（任务书 §10 第 2 条）：
| 列 | 值 | 核对 |
|---|---|---|
| `bindings.go_sha256`（内容规范化） | `<NEW_GO_SHA256>` | 必须等于 check-only `go.sha256`，也必须等于 S4.2 输出的 `go_content_sha256` |
| 归档文件字节 sha | `sha256(<…pre.archived.json>)` | 必须等于装槽前槽位件的字节 sha（本次 = `38f3c3f5…`）与 pending 装槽前的字节 sha |
两者**不要求相等**；相等反而是异常（说明有人把规范化 JSON 直接当文件内容）。

### S9 未达标时的失败闭环留痕（回答 Q8）

一次 attempt 内如果没达标，**下列字段原样保留**（不改、不重算、不覆盖），用于"与修前是否变化"的对照：

| 面 | 字段 | 位置 |
|---|---|---|
| 失败码 | `error_code`、`stop_code`、`case_plan_failed_turn_code`、`cleanup.cleanup_errors[]` | `run-receipt.json` |
| 首偏离 | 逐层固定状态（意图→候选→检索→模型输入→事实准入→渲染→引用→commit）与 `quality_status`/`missing_codes` | `safe-projection` 与 `recompute-*.json`（`work/r2_safe_project.py`、`work/r2_recompute_axes.py` 输出） |
| 计划身份 | `plan_id`、`plan_sha256`、`plan_file_sha256`、`binding_sha256` | 计划文件 / binding / 回执 |
| 代码身份 | `code_version`、`config_sha256` | binding / 回执 `bindings` |
| 封存身份 | `seal.seal_manifest_sha256`、`seal.out_tree_sha256`、`seal.evidence_tree_sha256`、`evidence.manifest_sha256` | 回执 / `seal-manifest.json` |
| 尝试身份 | `run_binding.attempt_scope_sha256`（= f(run_id, plan_sha256, scenario, go_sha256, ledger_sha256)，`tools/p2_h2_controlled_execute.py:1453-1481`） | 回执 |
| 计数 | `requests.planned/attempts_reserved/sent/reserved_cny/settled_cny`、`real_sends` | 回执 |
| 轴 | `hard_failures`、`axes.*.unknown/violations`、`unknown_cases`、`missing_codes`（标明来自初判还是重评） | `recompute-*.json` |

同时写三段结论：①本轮失败码/首偏离与修前是否变化；②原假设是否被证伪；③下一次要改什么。**没有代码或证据变化不许重复付费**；两次补丁仍未改变同一失败机制就回经理复审（任务书 §9）。

---

## §3 字段 / 固定码速查表

### 3.1 计划与 binding（`plan-private` 产物）
- 计划文件：`<R2_ROOT>\plan\plans\run2-pre_v05_without_v07.plan.json`（**仓外**，含 `case_id`，不得进仓）。
- binding：`<R2_ROOT>\plan\bindings\run2-pre_v05_without_v07.binding.json`，顶层键恰好 14 个：`schema_version, created_utc, fixture_kind, execution_mode, holdout_root, anchor_business_date, business_date, code_version, config_sha256, config, dataset, inputs, runs, binding_sha256`（`tools/p2_h2_v3_controlled_execute.py:201-216`）；`runs` 只有 1 条（`_select_run` 要求 `len(runs)==1`，`:637-644`）。
- 计划顶层键：`schema_version, plan_id, plan_version, mode, stage, created_utc, project_total_limit_cny, stage_limit_cny, max_requests, cost_centers_cny, items[, scenario_binding]`（`p2_contracts.py:817-…,995-1013`）。

### 3.2 check-only 输出（`p2-h2v3-controlled-check/v0.1`）
必查 16 个 check（§2 S3 列表）+ `zero_write`/`zero_send`/`go`/`preflight`/`authorization`/`quota` 六块。`ok = all(checks.ok)`；退出码 `0`/`2`。

### 3.3 回执（`p2-h2v3-controlled-run-receipt/v0.1`，内层 v2 回执 `p2-h2-controlled-run-receipt/v0.1`）
`ok,status,stop_code,error_code,run_index,run_id,scenario_id,plan_id,plan_sha256,business_date,fixture_kind,execution_mode,chat_model,model_pinned,runtime,plan_ingest,case_plan_started_turns,case_plan_failed_turn_code,requests,evidence,cleanup,seal,real_sends,bindings,run_binding,case_plan,case_plan_error,evidence_key_sha256,paths,started_utc,finished_utc,duration_ms,receipt_path`。

### 3.4 四个计数口径（不可互相替代）
`planned`（计划） / `attempts_reserved`（门控唯一预留，纪律口径） / `real_sends`（出网尝试） / answer 侧 `reserved`·`sent`。历史实测差异示例：run2 计划 37、尝试 31、出网 30（`docs/reports/OBS-EVAL/P2/H2V3/run/run-r123-report.md:87-93`）。

### 3.5 固定码分类总表
| 阶段 | 固定码（节选，全表见 §2 各步） |
|---|---|
| 用法/环境 | `usage_invalid`、`cwd_not_project_root`、`env_total_limit_conflict`、`now_invalid`、`run_index_invalid`/`run_index_mismatch` |
| 计划生成 | `holdout_root_missing`、`input_file_missing`、`ingest_batch_census_missing`、`dataset_*`、`scenario_counts_mismatch`、`plan_*_mismatch`、`scenario_plan_mismatch`、`output_already_exists`、`output_not_empty` |
| 预检 | `go_missing_for_run`、`run_claim_held`、`plan_set_*`、`code_changed_since_plan`、`input_changed_since_plan`、`plan_file_changed`、`evidence_binding_mismatch`、`pipeline_changed` |
| 授权/金额 | `path_missing`、`text_invalid`、`go_nonce_invalid`、`go_expired`/`go_not_yet_valid`、`go_plan_sha256_mismatch`、`go_budget_total_mismatch`、`go_stage_limit_below_plan`、`go_cost_center_below_plan`、`go_max_requests_below_plan`、`go_max_request_cny_below_plan`、`go_ledger_binding_mismatch`、`budget_history_mismatch`、`stage_budget_insufficient`、`center_budget_insufficient:<center>`、`center_accounting_inconsistent`、`env_total_limit_missing` |
| 运行 | `plan_dial_failed`、`plan_recompute_failed`、`live_requires_production_ready`、`live_operation_not_authorized`、`env_*_mismatch`、`run_claim_held`、`seal_target_exists`、`seal_readonly_mismatch`、`seal_readback_mismatch` |
| 首错停（stop_code） | `ingest_failed`、`plan_item_missing`、`turn_timeout`、`product_service_error`、`usage_evidence_missing`、`gate_error`、`pre_send_refused`、`attempt_quota_exhausted`、`attempt_accounting_mismatch`、`artifact_validation_failed`、`no_case_executed` |
| 封存/清理 | `plaintext_residual`、`plaintext_residual_required`、`composition_retention_collision`、`seal_failed` |

### 3.6 金额/配额常量（逐处来源）
| 项 | 值 | 来源 |
|---|---|---|
| 项目总上限 | 40 | `docs/evidence/LOCAL-R1-20261101/budget/budget.json` `limit_cny`；`p2_holdout_plan.py:75`；`tools/p2_h2_v3_controlled_execute.py:65` |
| 阶段 P2-LIVE | 20 | `budget.json` `stages.P2-LIVE`；`p2_holdout_plan.py:74` |
| 单请求上限 | 0.5 | GO `scope.max_request_cny`（须 ≥ plan.reserve_peak_cny） |
| 四成本中心 | 8.5 / 6.5 / 3.0 / 2.0（和=20） | `p2_holdout_plan.py:68-73` |
| 请求上限 | `"unlimited"`（累计次数闸取消） | `tools/p2_h2_v3_controlled_execute.py:154-160`；`p2_contracts.py:119-125` |
| 硬顶 | 1600（仅有限值适用） | `p2_contracts.py:101` |

---

## §4 与 R1 的差异与禁止照抄项

| 维度 | R1（run2 实测） | R2（本次） | 依据 |
|---|---|---|---|
| run_index / 场景 | 1 / `base_b0_plus_v01` | **2 / `pre_v05_without_v07`** | `p2_holdout_run_date.py:129-134` |
| 业务日 | 2026-07-15 | **2026-11-20** | 同上 |
| 题 / 回合 | 8 / 10 | **5 / 6** | `tools/p2_h2_v3_controlled_execute.py:162-173` |
| 计划请求 | 50 | **37**（24 + 13 批） | `p2_holdout_plan.py:85-90,299-329`；census |
| `max_requests` | `unlimited`（R1 末态） | `unlimited` | `tools/p2_h2_v3_controlled_execute.py:155` |
| plan_sha256 | `80d05194…` | `<NEW_PLAN_SHA256>`（必新） | S1/S2 |
| code_version | `94a8809e…` | `<NEW_CODE_VERSION>`（必变） | `tools/p2_h2_controlled_execute.py:395-408` |
| GO 槽位件 | `38f3c3f5…`（R1 run2） | 新件（先归档旧件） | S4 |
| GO 内容摘要 | `4bf0d479…` | `<NEW_GO_SHA256>` | S4.2 |

**不能直接照抄 R1 的点（逐条）**
1. **case 集合**：R1 是 8 题（C05/C07/C13/C22/C28 等），R2 是 5 题（C08/C14/C19/C25/C29，C14 为 2 回合）——任务书 §3。任何 `SELECTED_CASES` 之类的常量都不能沿用（例：`work/r1_case_boundary.py:78` 固定 R1 五案）。
2. **业务日**：不许用"本机今天"，也不许用 R1 的 2026-07-15；唯一来源是 L1 的 per-run 表（`p2_holdout_run_date.py:178-199`，用锚点日会被 `run_business_date_anchor_forbidden` 拒）。
3. **旧 plan 复用**：R1 计划已耗用、`plan_sha256` 绑死 GO；必须新生成（任务书 §9 第 1 条）。
4. **旧 GO**：槽位旧件只代表 R1 run2；不能"续期/改 scope/换 nonce 复用"（`go_plan_sha256_mismatch` 就是为这个设的，`p2_authorization.py:472-476`）。
5. **R1 的私有读取/代签权限不继承**：任务书 §1 明说"新执行者不得继承上一窗口专属权限"；本 runbook 不授予任何私有读取权，`<HOLDOUT_ROOT>`/`<KEY>` 必须由保管方提供。
6. **R1 的 unknown 豁免不继承**：C13 的"接受 1 个 unknown"只针对该案（任务书 §1）。
7. **别拿 v2 入口当 R2 入口**：v2 的 30 题/36 回合、`pre_v05_without_v07`=2 题、批数 8/9/11/13 全不适用（§0.2）。
8. **别照抄 R1 的目录/常量**：`work/r*_*.py` 里 `WORK`/`KEY_PATH`/`DEFAULT_OUT`/`SELECTED_CASES`/`CASE_PLAN_REL` 全是 R1 硬编码（`work/r1_recompute_axes.py:76-97`、`work/r1_case_boundary.py:64-78`、`work/r2_recompute_axes.py:90-112`）。
9. **别照抄 R1 的"归档同名"**：R1 每跑完一个 run 就把槽位件归档成 `.v3-r{上一run}.done.archived.json`；本次旧件已有字节相同归档，再归档必须用**新 tag**且 `xb` 独占创建（S4.1）。
10. **别照抄 R1 的请求数/金额结论**：37/0.291968 只是同形计划的历史值，必须用本次计划与预检实测值。
11. **别把 `--plan-only` 当完整预检**：`plan_only` 跳过数据集/契约/source map（`tools/p2_h2_v3_controlled_execute.py:2024-2047`）。

---

## §5 NOT-RUN 与风险

### 5.1 本次编制中确定未做的事
以下全部 **NOT-RUN**（未执行、未验证）：`plan-private`、`check-only`、`run`、`r2_recompute_axes.py`、`r2_safe_project.py`、任何 pytest、任何 GO 写入/归档/装槽、任何账本或预算写入、任何 git 写操作。

### 5.2 `UNVERIFIED` 清单（缺什么证据 / 最小补采）
1. **`UNVERIFIED-1`：`plan-private` 在本次 holdout 根上的实跑结果**。缺：`<HOLDOUT_ROOT>` 的 `manifest.json`/`annotations-v0_2.fernet`/`review-v0_2.fernet` 存在性与其 key 有效性（本次无权读取）。最小补采：由保管方跑 S1，只回 `ok`、`code_version`、`run_dates[2].business_date=2026-11-20`、`runs[2].{case_count:5,turn_count:6,total_requests:37,plan_sha256}`、`index_file_sha256`。
2. **`UNVERIFIED-2`：`p2_hard_evidence.run_recompute_cli` 的 `cases_path` 生成方式**。缺：R2 交付目录里没有把 5 题 CaseSpec 落成 JSON 的现成脚本/命令（R1 走的是 `r2_recompute_axes.py` 的 `load_v3_bundle` 路径，不产出该文件）。最小补采：确认是否需要该入口；若需要，从 `load_v3_bundle(...).contract.subset(scenario).cases` 导出 SAFE 子集（不含题干）并登记脚本哈希——**在拿到脚本前不要照猜命令**。
3. **`UNVERIFIED-3`：`r2_recompute_axes.py` / `r2_safe_project.py` 对"新 attempt 目录"的适配是否足够**。已知必改：`KEY_PATH`（`work/r2_recompute_axes.py:97`）；`--work/--bindings/--out` 已可参数化（`:665-690`）。缺：这两个脚本是否还引用其它 R1 绝对路径（未逐行审完）。最小补采：`Select-String -Path work\r2_*.py -Pattern 'D:\\mktkb'` 列出全部绝对路径并登记。
4. **`UNVERIFIED-4`：R2 计划与 GO 的最终 `worst_case_cny`**。缺：本次未生成计划。历史同形 0.291968 元只能当量级参考。最小补采：S1 输出的 `runs[2].worst_case_cny` 与 S3 `preflight.worst_case_cny` 必须逐值相等。
5. **`UNVERIFIED-5`：`check-only` 在"新 GO 已装槽"后的 16/16 全绿**。缺：本文件编写时新 GO 尚不存在。最小补采：S4.2 + S3 重跑的完整 JSON（`--out` 落盘）与 `reasons=[]`。
6. **`UNVERIFIED-6`：`runs` 内 `contract_validate_run.authorized_delta` 的具体数值**（预期 `index_embedding 11→13` 附近）。缺：未跑 S1。最小补采：S1/S3 输出里该块原样记录，不要手写 11/13。

### 5.3 风险（按触发概率排序）
1. **改完源码又改入口/后端文件** → `code_changed_since_plan`（最常见，历史已发生过）。缓解：S1 之后冻结源码，所有脚本副本放仓外且不被 `code_digest` 的 scope 覆盖。
2. **run_id 重复** → 账本核对若只按 `run_id` 过滤会把历史 attempt 行算进来，得出错误的配对/金额结论。本机只读实测（以 R1 的 `plan_sha256` + `run_id` 跑 S8 脚本）：本次计划 32 条预留全部一一配对，但同 `run_id` 下另有 **166** 条"别的 plan"的 reserved 行、**198** 条 result 行——只用 `run_id` 会把这 198 条当成一次 attempt 的结果。缓解：一律加 `metadata.plan_sha256` 过滤（S8 已内置），且 result 侧只认"本次计划 reserved id"的配对。
3. **GO 文本超 200** → `text_invalid`（同目录 4 份 `oversize-text` 归档即证据）。缓解：S4.2 生成脚本内断言 ≤180。
4. **pending 与槽位不一致** → `go_plan_sha256_mismatch` 或回执 `go_sha256` 与 check-only 不符。缓解：装槽后立即比字节与内容摘要。
5. **预检 `--seal-root` 与 run 抢同一目录** → `run_claim_held`；**`--out` 落点已存在** → `output_already_exists`。缓解：每次 attempt 一个全新目录，check-only 的 `--out`/`--seal-root` 与 run 的一致但不复用。
6. **把 `--plan-only` 当完整预检** → 缺 `dataset_shape/contract_validate_run/source_map` 三项，等于没验私有契约。缓解：不带该 flag（S3）。
7. **失败后重跑同一 attempt** → 目录已存在/租约/旁证文件全部拒绝；且违反"零重试"。缓解：失败即停在 S9 留痕。
8. **明文残留**：`plaintext_clean=false` 时不会封存（`seal={"sealed":false,"error_code":"plaintext_residual"}`），此时**不得手工改字段或补 seal**，只能按 S9 留痕并交出 attempt 目录供审计。

---

## §6 引用（文件:行号）

**入口与 CLI**
- `tools/p2_h2_v3_controlled_execute.py:1-38`（v3 定位与五处差异）、`:143-160`（schema/TAG/`MAX_REQUESTS="unlimited"`/`STAGE_LIMIT_CNY=20`）、`:162-179`（5 题/6 回合、census 路径）、`:181-239`（输入名与 binding/run 键）、`:317-387`（run 级租约）、`:479-539`（socket 守卫与正对照）、`:562-644`（输入记录/binding 读取/`_select_run`）、`:651-727`（批数 census 派生）、`:730-767`（v3 config）、`:1062-1142`（`load_v3_bundle`）、`:1159-1203`（数据集形状）、`:1205-1307`（plan_dial/派生/重算）、`:1314-1389`（授权 delta）、`:1489-1504`（plan/run id 派生）、`:1538-1606`（建计划/校验）、`:1609-1819`（`plan-private`）、`:1827-1872`（per-run GO 槽位）、`:1875-1964`（请求闸/quota/plan-set）、`:1967-2200`（`check-only`）、`:2208-2368`（`run`）、`:2376-2464`（CLI 定义与分发）、`:2467-2513`（退出码与固定错误输出）
- `tools/p2_h2_controlled_execute.py:86-160`（版本/schema/固定路径/场景序）、`:286-354`（仓外/新建/摘要/树摘要）、`:389-408`（**`code_digest`**）、`:498-563`（运行参数与 env 合并）、`:566-642`（`.env` 白名单与还原）、`:1441-1490`（plan/run binding 校验）、`:1453-1481`（`attempt_scope_sha256`）、`:1547-1568`（目标路径校验）、`:1769-1839`（明文针/扫描）、`:1952-2033`（purge 与清理）、`:2036-2100`（**封存与读回**）、`:2131-2204`（证据回读）、`:2351-2450`（case-plan）、`:2471-2536`（错误分类/请求计数）、`:2565-2851`（`_execute_loaded` 主流程与回执）、`:2949-3012`（`_audit_ledger`，**只按 run_id 过滤**，R2 需加 plan 过滤）
- `tools/p2_live_execute.py:38-60`（6 个必需凭据名、允许名、`MKTKB_PROJECT_TOTAL_LIMIT_CNY`）

**授权/资金**
- `backend/src/mktkb/evaluation/p2_authorization.py:87-121`（GO document/schema、`_GO_KEYS`、`_GO_SCOPE_KEYS`）、`:196-215`（`_text` 默认 200、`_exact` 封闭键）、`:249-325`（GO/预算载入、只读快照）、`:347-417`（`preflight_p2`）、`:438-522`（`_check_go_payload` 全量约束）、`:525-552`（预算约束）、`:555-657`（`authorize_p2`、`production_ready`）、`:749-1043`（`P2Gate`/`_request_guard`/`_post_reserve_guard`）、`:991-1020`（**`plan_sha256+item_id` 配额**）、`:1047-1099`（预留与 metadata）、`:636`（`go_sha256=payload_sha256(go)`）
- `backend/src/mktkb/live_authorization.py:400-449`（历史前缀与 `ledger_binding_ok`）
- `backend/src/mktkb/rag/budget.py:280-286`（unlimited 仅 P2-LIVE）、`:591-703`（预留事件字段）、`:728-779`（结果事件字段）、`:569-588`（`summary`）
- `backend/src/mktkb/evaluation/p2_contracts.py:101,119-125`（硬顶/unlimited）、`:387-399`（**`payload_sha256`**）、`:588-606`（`bound_cny`）、`:773-779`（worst case）、`:931-979`（派生统计）、`:995-1017`（`as_dict` 与 **`plan_sha256`**）

**计划/日期/场景**
- `backend/src/mktkb/evaluation/p2_holdout_plan.py:68-90`（成本中心、阶段/项目上限、`H2_MAX_REQUESTS`、每回合四项）、`:275-354`（`build_holdout_plan`）
- `backend/src/mktkb/evaluation/p2_holdout_run_date.py:129-134`（**RUN_DATES**）、`:160-199`（L1 对账与 `bind_run`）、`:211-240`（adapter 入参）
- `backend/src/mktkb/evaluation/p2_holdout_scenarios_v3.py:56-69`（v3 契约/ingest/source-map/schema 固定路径）
- `docs/reports/OBS-EVAL/P2/H2V3/run/plan-regen/ingest-batch-census.json`（`scenarios.pre_v05_without_v07.embed_posts_required=13`）

**执行/首错停/产物**
- `backend/src/mktkb/evaluation/p2_live.py:89-107`（必需环境变量名）、`:176-225`（`load_live_env` 与固定码）、`:1277-1319`（`open_live_gate`/`production_ready`）、`:1511-1601`（`run_live_p2`）
- `backend/src/mktkb/evaluation/p2_runner.py:6-18`（串行、零重试、首错停）、`:1117-1164`（`attempts_*`）、`:1167-1211`（金额三分）、`:2480-2567`（summary 字段）、`:2569-2604`（gate.json）
- `backend/src/mktkb/evaluation/p2_hard_evidence.py:979-989`（compat 档常量）、`:3975-4036`（四轴重算与公开卡片）

**公开证据（历史事实，仅作对照，不是本次实测）**
- `docs/reports/OBS-EVAL/P2/H2V3/r1-repair-external-20261117/R1-FINAL-CHAIN.md:5-23,58-60`（R1 run2 身份、两个 GO 哈希、封存/证据树、金额；经理对两哈希的更正）
- `docs/reports/OBS-EVAL/P2/H2V3/run/run-r123-report.md:26-46,52-57,83-110`（同形 r2 计划：5 题/6 回合/37 请求/13 批/2026-11-20；16/16 预检；GO 归档+装槽的字节口径；四口径计数）
- `.claude/handoffs/2026-11-17-r1-pm-closeout.md:16,20,34`（槽位旧件摘要、两哈希口径、R1 GO 与计划不可复用）
- `docs/superpowers/plans/2026-11-17-r2-external-ai-repair-taskbook.md:153-189`（T-R2-205/206 的机械检查与两个 GO 哈希分列要求）

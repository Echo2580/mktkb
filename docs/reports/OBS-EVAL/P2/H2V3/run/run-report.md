# H2 v3 基线重绑 + 真实执行报告（v3 基线重绑 + 真实执行）

- 结论：**`ABORTED_AT_run0`**（重绑成功、check-only 4/4 ok、零请求；r0 真实执行在**第 0 回合**中止于 `adapter_error`，按纪律立即停止，r1–r3 未装槽未执行）
- 工作区：`D:\GPT项目\市场部AI知识库`，分支 `codex/p2-e2e`，HEAD `97b0066726e5b8d6f94cbc0b63a890084550c106`，暂存 0 项
- 计划/GO：`rollback-40`（40 元口径），`max_requests=1137`；运行期显式环境 `MKTKB_PROJECT_TOTAL_LIMIT_CNY=40`
- 本包只发真实请求：1 次 `run` 尝试（r0），**零重试、零加钱、零手工修分**；无 stage/commit/push，无新建 worktree/切分支
- 上一轮（`NOT-RUN`）的产物按字节原样移到 `run/round1-notrun/`，未改写

---

## 1. 重绑（选项 A）：计划不变，只刷新 binding

做法：用**当前代码**重跑 `plan-private`（仓外新目录 `D:\mktkb-p2-h2v3-20261115\rebind-r1`），再把新计划与旧计划逐字节比对；计划不变则 GO 的 `plan_sha256` 绑定仍成立，只有 binding 的代码/配置身份需要刷新。证据：`rebind-evidence.json`。

| run | plan 文件 SHA-256（重生成） | 与 rollback-40 逐字节 | `plan_sha256` | 与 GO scope 一致 | code_version 前 → 后 | config_sha256 前 → 后 | binding SHA-256 前 → 后 |
|---:|---|---|---|---|---|---|---|
| 0 | `3f1c0014…5dad81` | true | `a109894e…953c65` | true | `efe1c66e…59a1c` → `1e593066…73002` | `284946a5…6e29` → `b1799ff9…dab111` | `e4721c87…a842f2` → `2ca148c2…f65fec7` |
| 1 | `b1ba1ffc…b4f577` | true | `4691e9c3…81ad97` | true | 同上 | `b8648faa…` → `f36fed73…` | `53ff67db…` → `8458b6e1…` |
| 2 | `59ae317b…46b6e2` | true | `9896ae4e…80f857` | true | 同上 | `9910cfd9…` → `7919e56f…` | `908a3a53…` → `544c76c6…` |
| 3 | `989cdc94…7c01293` | true | `8f662d59…0e48e9f` | true | 同上 | `38e6ca1f…` → `3236a3fd…` | `2e9dae52…` → `aaf3579f…` |

- binding 里**唯一**变化的叶子：`code_version`、`config.code_version`、`config_sha256`、`runs[0].evidence_bindings.code_version`、`runs[0].evidence_bindings.config_sha256`、`runs[0].plan_file`（新目录绝对路径），外加自哈希 `binding_sha256`；`config` 内**只有** `code_version` 一个叶子变。
- 未变：数据集 `manifest_sha256=de4125ca…`、四轴 `axis_counts`、`scenario_binding`（契约/分配/保管/子集/ingest 五个哈希）、`case_count/turn_count/total_requests/worst_case_cny`、`max_requests=1137`、`project_total_limit_cny=40`。
- 改绑原因（如实记录）：计划生成于 `2026-11-15T06:30:39+08:00`；其后经授权修复 `fix-1r1` 于 `06:55:45` 改了 `backend/src/mktkb/rag/query.py`（`f73fc735…` → `82776def…`），入口代码冻结门按设计以 `code_changed_since_plan` 拒绝旧 binding；`fix-1r1` 已独立验收 **`PASS_WITH_DISAGREEMENTS`** 且判定可跑真实基线（`fix-1r1/review-aggregate.json`，残余 D1/D2/D4 为跑前已知）。

### 1.1 重绑后 check-only（零请求）

| run | 模式 | `ok` | `reasons` | `production_ready` | 请求已用/剩余 | 本次计划请求 | 阶段剩余(元) | 外部尝试 | 账本/预算未写 |
|---:|---|---|---|---|---|---:|---:|---:|---|
| 0 | full_contract_reload | true | `[]` | true | 952 / 185 | 64 | 12.867562 | 0 | true |
| 1 | plan_only | true | `[]` | true | 952 / 185 | 49 | 12.867562 | 0 | true |
| 2 | plan_only | true | `[]` | true | 952 / 185 | 35 | 12.867562 | 0 | true |
| 3 | plan_only | true | `[]` | true | 952 / 185 | 37 | 12.867562 | 0 | true |

证据：`preflight/rebind-check-r0.json` … `-r3.json`（r0 含契约重载与 source-map 复核；r1–r3 不加载私有数据集）。

---

## 2. 四 run 结果表

| run | scenario | business_date | 题 / 回合（计划） | 状态 | pass | fail | error | 硬失败 | 四轴计数 | 请求（尝试/出站） | 金额（账本保守记账，元） |
|---:|---|---|---:|---|---:|---:|---:|---|---|---|---:|
| 0 | `base_b0` | 2026-10-15 | 12 / 14 | **ABORTED**（`adapter_error`，第 0 回合） | — | — | — | — | 无数据 | 9 / 8（计划 64） | 0.0203535 |
| 1 | `base_b0_plus_v01` | 2026-07-15 | 8 / 10 | **NOT_RUN**（r0 中止后按纪律停） | — | — | — | — | 无数据 | 0 / 0 | 0 |
| 2 | `pre_v05_without_v07` | 2026-11-20 | 5 / 6 | **NOT_RUN** | — | — | — | — | 无数据 | 0 / 0 | 0 |
| 3 | `post_v05_without_v01` | 2026-12-15 | 5 / 6 | **NOT_RUN** | — | — | — | — | 无数据 | 0 / 0 | 0 |
| 合计 | 4 | — | 30 / 36 | 1 中止 / 3 未跑 | — | — | — | — | — | **9 / 8**（上限 185） | **0.0203535**（上限 40） |

- `pass` / `fail` / `error` / 四轴（`safety`、`cross_user`、`cross_entity`、`stale_source`）**无实测值**：r0 在首个回合中止，`holdout_scorecard.json`（清理前 8,091 B，SHA `3931bc56d0d88089ef8bcdcddba710dd4b72b161664012f389fe3e8620cc8207`）在清理阶段被移除，仓内不重建、不补 0。
- `real_calls`：scorecard 字段不可读（同上）；本次**实测出站** `real_sends=8`（8 次 ingest embedding）。`mock_intercepted=0`（`execution_mode=live` 且入口不装配任何 mock transport）。
- 逐 run 事实：`r0/card.json`、`r0/status.json`、`r0/case-plan.json`、`r0/run-receipt.json`、`r0/v3-entry-sidecar.json`；`r1..r3/status.json`。

---

## 3. 中断点与失败链（r0，逐码位）

| 层 | 事实 | 证据 |
|---|---|---|
| 产品 | 第 0 回合 answer 返回 `service_error` / `INDEX_NOT_READY`；`context_observed count=0 empty=true`；`pre/post revision=7`（未推进） | 加密回合证据（本包只提取固定码，未读题面/答案） |
| 采集 | `completeness.status=incomplete`、`missing_event_kinds=["plan_observed"]`、`completeness.errors=["plan_observation_count_invalid"]` | 同上 |
| 账本 | 第 9 行 chat 结果：`status=failed`、`http_status=null`、`error_code=EvidenceCaptureIncomplete`、保守记账 0.018688 | 共享账本新增行 |
| runner | `status=aborted`、`stop_code=adapter_error`、`receipt.error_code=run_not_succeeded`、`case_plan_started_turns=1` | `r0/run-receipt.json` |
| ingest | 8 次 embedding 全部 `http_status=200`、`status=succeeded`（计费见 §5） | 共享账本新增行 |

结论：不是资金/GO/预算/账本问题（三者逐项通过），是**产品侧索引未就绪**（ingest 成功但答案前上下文为空、捕获 revision 停在 7），叠加采集完整性判负后由 runner 首错停。按纪律**未重试、未改代码、未手工修分**。

---

## 4. 累积额度对账

| 项 | 执行前 | 执行后 | 上限 | 状态 |
|---|---:|---:|---:|---|
| 本包请求（尝试） | 0 | **9** | 185 | 未越 |
| 本包请求（出站） | 0 | 8 | 185 | 未越 |
| 累计请求（GO `max_requests`） | 952 | **961** | 1137 | 未越（余 176） |
| 账本已记账（保守，元） | 22.2033828 | **22.2237363** | 40.00 | 未越 |
| P2-LIVE 阶段（元） | 7.1324383 | **7.1527918** | 20.00 | 未越 |
| 单请求上限（元） | — | 最大 0.018688 | 0.50 | 未越 |

---

## 5. 账本与预算（前后逐值）

| 项 | 执行前 | 执行后 |
|---|---|---|
| 账本文件 SHA-256 | `ca9dceb9019790eb6ba4e25cfaf88232915b607d756d0eae21ad7cdf10c6fec9` | `9d4b957ac431acfe7b04d0c441dd0c77e31c15849e84806fbbc8c23c4e3de413` |
| 行数 | 1905 | 1923（+18 = 9 预留 + 9 结果） |
| reservation / result | 952 / 952 | 961 / 961（配对 true） |
| 账本内链哈希（GO 绑定） | `f4710b18…a014` | `f4710b18…a014`（未变） |
| 已记账（保守，元） | 22.203382799999936 | 22.22373629999994（+0.0203535） |
| 预算文件 SHA-256（`limit_cny=40`） | `79b21700…1a9e` | `79b21700…1a9e`（未变） |

金额口径说明：`requests.settled_cny=0.018688` 只是 chat 尝试的**保守预留结清**（`http_status=null`、估计价 0）；8 次 embedding 的估计价合计 `0.0016655`；账本按保守口径合计 +`0.0203535`。

---

## 6. 纪律与保全

- 串行：只执行 r0 一次尝试，失败即停；r1–r3 的 GO 仍在 `.pending.json`，**未装槽**、未发任何请求。
- 未改：GO 内容与旧 GO 归档、预算、账本内容（仅真实花费自然增长）、四份计划、30 题/标签/阈值、四轴与评分标准、评测模块、C 冻结 12、v2/v3 语料与密文、`fix-1*` 证据。
- 仓内新增仅安全聚合（路径/计数/哈希/固定码）：`run/rebind-evidence.json`、`run/run-report.md`、`run/conclusion.json`、`run/preflight/rebind-check-r*.json`、`run/r0/*`、`run/r1..r3/status.json`、`run/round1-notrun/`（上一轮原样归档）。
- 未 stage/commit/push；未新建 worktree/切分支；暂存 0 项。
- 未把任何真实 H2 题面/答案写入公开产物；诊断只读加密证据中的固定码与计数。
- 逐字节保全复核（`preservation-check.json`，对 `fix-1r1/independent/preservation-after.json` 快照）：C 冻结 12 → **12/12 未变**；仓外 v2/v3 语料与密文 **13/13 未变**；受保护仓内件 **14/14** 中仅 `live-ledger.jsonl` 变化（真实花费自然增长，允许）；HEAD/分支未变、暂存 0、tracked modified 仍 22 条同路径。

---

## 7. 残余（交给经理决策，本包未动）

| # | 残余 | 级别 | 说明 |
|---:|---|---|---|
| R1 | `INDEX_NOT_READY`（r0 第 0 回合） | 高 | 8 次 ingest embedding 全 200 成功，但答案前 `context_observed=0`、捕获 revision 停在 7；需定位 ingest→index 就绪链路（含 `index_revision` 推进与索引加载时机）。本包按纪律未重试、未改代码。 |
| R2 | 采集完整性判负 | 中 | 缺 `plan_observed` 事件导致 `plan_observation_count_invalid`；与 R1 同源（答案未进入规划），需与 R1 一并定位。 |
| R3 | chat 未出站仍满额结清 | 低 | `http_status=null`、估计价 0，但账本保守记账 0.018688；如要避免"零出站满额"，属账本口径问题，需单独授权。 |
| R4 | aborted run 的评分面缺失 | 中 | scorecard/summary/run_result/gate 在清理阶段被移除，pass/fail/error 与四轴无值；若要可评分的中止留痕，需另行设计。 |
| R5 | r1–r3 未执行 | — | 三份 GO 未过期（`2026-11-29`）、`max_requests` 余 176；任何重跑/续跑都需经理新裁决（本包不自动续跑）。 |

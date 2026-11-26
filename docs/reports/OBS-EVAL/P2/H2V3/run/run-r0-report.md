# H2 v3 run0 真实执行报告（v3-run-r3）

- 结论：**`NOT-RUN`**（已发起 1 次真实入口调用，但在**场景契约复核**处被拒：`scenario_contract_invalid` / 底层 `scenario_plan_mismatch`）
- 请求 **0**、出站 **0**、金额 **0 元**；账本/预算字节**未变**；未重试、未加钱、未改代码、未手工修分
- 工作区：`D:\GPT项目\市场部AI知识库`，分支 `codex/p2-e2e`，HEAD `97b0066726e5b8d6f94cbc0b63a890084550c106`，暂存 **0** 项
- 计划/GO：`index_embedding = 9/10/13/15`（r0=9）+ `max_requests=1160` **已生效**；GO `215398d1…`、计划 `70f8f373…`、账本 `9d4b957a…`、预算 `79b21700…`
- 无 stage/commit/push；未新建 worktree/切分支；未把题面/答案写入任何产物

---

## 1. 现场核对（开工前）

| 项 | 期望 | 实测 | 结论 |
|---|---|---|---|
| 分支 / HEAD | `codex/p2-e2e` / `97b00667…` | 同 | ✅ |
| 暂存 | 0 | 0 | ✅ |
| 账本文件 SHA-256 | `9d4b957a…` | `9d4b957ac431acfe7b04d0c441dd0c77e31c15849e84806fbbc8c23c4e3de413` | ✅ |
| 账本行数 / 配对 | 1923 / 961:961 | 1923 / 961:961 paired | ✅ |
| 账本内链哈希 | `f4710b18…` | `f4710b1869fe43b9a609b58f772549f76370fbadd54f93685b76211d4b47a014` | ✅ |
| 预算 SHA-256 / `limit_cny` | `79b21700…` / 40 | `79b21700…` / 40.0 | ✅ |
| r0 计划 `index_embedding` | 9 | 9（`contract_recipe_requests=8` + `authorized_delta=9`） | ✅ |
| r0 计划 `max_requests` | 1160 | 1160 | ✅ |
| GO `scope.max_requests` / `plan_sha256` | 1160 / `70f8f373…` | 1160 / `70f8f373…` | ✅ |

`/plan-regen` 包已按诊断结论把「计划批数」与「GO 上限」改到位：**本包未再改任何计划参数**。

## 2. 已发生的代码身份漂移与重绑（零请求）

`check-only`（旧 binding）第 1 次运行 **不 ok**：16 项里唯一失败 `code_version`（`reasons=["code_version"]`）。

- 原因：`tools/p2_h2_v3_controlled_execute.py` 的 mtime = **08:13:24**，晚于计划/binding 生成时刻 **08:11:36**；该文件在 `CODE_SCOPES` 内（v3 入口把自身追加进 v2 的 scope）。
- 旧 binding 记录 `code_version=f14f9212…`；当前代码 `db3b6050…`。故 `check-only.json`（失败件）与 `check-only-rebind.json`（重绑后通过件）**都保留**作证据。
- 处理（未改一行代码）：用官方 `plan-private --max-requests 1160 --created-utc 2026-11-15T05:00:00+08:00` 重新签发到仓外 `D:\mktkb-p2-h2v3-20261115\regen-1160b\`；**四份计划与 `regen-1160` 逐字节相同**（r0 `c74eb105…` 一致），`plan_sha256` 不变 → GO 的 `plan_sha256` 绑定仍成立，只刷新 binding 的 `code_version/config_sha256`。

### 2.1 重绑后 check-only（零请求）

| 项 | 值 |
|---|---|
| `ok` / `reasons` | **true** / `[]` |
| 检查 | **16/16 全绿**（binding、code_version、plan_binding、plan_dial、plan_recompute、ingest_batch_derivation、public_binding、dataset_shape、contract_binding、contract_validate_run、source_map、go_binding、preflight、authorization、zero_write、zero_send） |
| `production_ready` | **true** |
| 请求已用 / 剩余 | 961 / 199（上限 1160） |
| 本次计划请求 / 最坏金额 | 65 / 0.637568 元 |
| 阶段剩余 / 项目剩余 | 12.8472082 元 / 17.7762637 元 |
| 四 run 累计后 | 1152 ≤ 治理上限 1500（`exceeds_gate=false`） |
| 外部/本地尝试 | **0 / 0** |
| 账本 / 预算 | 前后同值（`ledger_unchanged=true`、`budget_unchanged=true`） |

证据：`run/r0/check-only-rebind.json`（`run/r0/check-only.json` 为重绑前的失败件）。

## 3. run0 真实执行（唯一一次尝试）

命令（`cwd=仓库根`，`MKTKB_PROJECT_TOTAL_LIMIT_CNY=40`）：

```
python tools/p2_h2_v3_controlled_execute.py run \
  --binding <regen-1160b>/bindings/run0-base_b0.binding.json --run-index 0 \
  --out-dir <runs/r0b/out> --evidence-root <runs/r0b/evidence> --seal-root <runs/r0b/seal> \
  --evidence-key-file <runs/r0/ev.key> --env-file .env
```

| 项 | 值 |
|---|---|
| 入口 | `tools/p2_h2_v3_controlled_execute.py run`（`p2-h2v3-controlled-entry/v0.1`） |
| scenario / business_date | `base_b0` / `2026-10-15` |
| 计划 | 12 题 / 14 回合 / 65 请求 / ingest 9 批（`plan_sha256=70f8f373…`） |
| 开始 / 结束（UTC） | `2026-11-15T05:55:38` / `2026-11-15T05:55:38` |
| 耗时 | **81 ms** |
| `status` / `stop_code` | `refused` / `null` |
| **失败码** | **`scenario_contract_invalid`**（底层 `scenario_plan_mismatch`） |
| 请求 已发 / 预留 / 记账 | **0 / 0 / 0 元** |
| `real_sends` | 0（`evidence.available=false`、`case_plan=null`、seal 未封） |
| 回合 / 题 | **0 回合 / 0 题**（未进入 ingest，未出网） |
| 清理 | `run_dir_removed=true`、`business_db_removed=true`、`trace_db_removed=true`、明文扫描 `clean=true` |

## 4. 失败定位（逐层，已离线复证）

1. v3 入口的 `check-only` 层对 `items[index_embedding].requests` 的 `8 → 9` 有**授权增量**（`authorized_delta`），所以 check 绿。
2. 但同一入口把**冻结的 `bundle.contract`** 交给执行核心；`p2_runner` 在开场走
   `validate_scenario_execution → contract.validate_run`（`p2_holdout_scenarios.py:351-356`）。
3. `validate_run`（同文件 `205-216`）用**冻结 `RECIPES`** 的 `ingest_batches=8` **逐值重建**计划并 `_require(expected == plan)` →
   本 run 计划是 census 派生的 **9** → `ScenarioError('scenario_plan_mismatch')`。
4. v2 入口把它笼统映射为 `scenario_contract_invalid`（`tools/p2_h2_controlled_execute.py:2408-2409`），于是**在任何网络动作之前**整 run 被拒。

离线复证（零网络，仅码）：`contract.validate_run(plan, subset, ingest)` → `ScenarioError code=scenario_plan_mismatch`；
`plan.items[index_embedding].requests=9`。即**方案 B（只改计划批数）只打通了 check 层，未打通执行层**；
`_contract_validate` 的增量豁免没有传给执行核心的 `validate_run`。修复点属**评测/入口代码**（`product_adapter.py` 之外的 C 冻结/入口件），
超出本包「只改计划参数」授权，且需要重绑 + 再跑（即重试），按纪律**未做**。

## 5. 真实计数（无分数）

| 项 | 值 |
|---|---|
| pass | **无分数**（0 题执行） |
| fail | **无分数** |
| error | **无分数** |
| 硬失败 | **无分数** |
| 四轴（`safety` / `cross_user` / `cross_entity` / `stale_source`） | **无实测值**（不填 0） |
| `real_calls` | 0（未出网；`real_sends=0`、`mock_intercepted=0`） |

> 本 run 在契约复核处被拒，未产生 `holdout_scorecard`/`summary`/`gate`，故 pass/fail/error/四轴一律记「无分数」。

## 6. 账本、预算与额度（前后逐值）

| 项 | 执行前 | 执行后 | 上限 | 状态 |
|---|---|---|---|---|
| 账本文件 SHA-256 | `9d4b957a…e413` | `9d4b957a…e413` | — | **未变** |
| 账本行数 | 1923 | 1923 | — | 未变 |
| reservation / result | 961 / 961（paired） | 961 / 961（paired） | — | 未变 |
| 账本内链哈希 | `f4710b18…a014` | `f4710b18…a014` | — | 未变 |
| 已记账（项目，元） | 22.2237363 | **22.2237363** | 40.00 | 未越 |
| P2-LIVE 阶段（元） | 7.1527918 | **7.1527918** | 20.00 | 未越 |
| 本包请求（尝试/出站） | 0 / 0 | **1 次入口调用 / 0 出站** | 80 | 未越 |
| 累计请求（有效上限 `min(plan,GO)=1160`） | 961 | **961** | 1160 | 未越（余 199） |
| 单请求上限（元） | — | 0（无请求） | 0.50 | 未越 |
| 预算文件 SHA-256 | `79b21700…1a9e` | `79b21700…1a9e` | `limit_cny=40` | 未变 |

## 7. 纪律与保全

- 串行：只尝试 r0 一次；首错即停；**未重试**、未装 r1–r3 的 GO、未加钱、未手工修分。
- 未改：C 冻结 12、v2/v3 语料与密文、评测模块、账本内容、预算、30 题/标签/阈值、GO 内容。
- 代码：**未改任何 `.py`**；只重新签发仓外 binding（计划字节与 `regen-1160` 相同）。
- 仓内新增：`run/r0/{card,case-plan,run-receipt,status,check-only,check-only-rebind}.json`、`run/run-r0-report.md`、`run/r0-attempt1/*`（上一轮 r0 中止产物逐字节归档）。
- 未 stage/commit/push；未新建 worktree/切分支；暂存 0 项。
- 未把任何真实 H2 题面/答案写入公开产物（本报告只有路径/计数/哈希/固定码）。

## 8. 结论与建议（交经理裁决）

**结论：`NOT-RUN`**（`stop_point = r0_contract_refusal`，`failure_code = scenario_contract_invalid`，底层 `scenario_plan_mismatch`；0 请求 / 0 元）。

现状是「方案 B 只改计划参数」的半成品：`check-only` 通过、执行核心仍按冻结配方拒绝。要继续真实基线，需授权以下**之一**（均需改代码 + 重绑，故本包未做）：

| 方案 | 改动面 | 说明 |
|---|---|---|
| B+（最小接线） | v3 入口把 **delta 感知的契约视图**传给 `_execute_loaded`（或在执行核心的 `validate_run` 前按 `authorized_delta` 归一） | 不改冻结配方；改 1 个入口文件 + 重绑；仍需独立验收 |
| A（诊断推荐） | `product_adapter.ingest` 8 行 + 重绑 + 定向测试 | 灌库期暂停发布钩子逐次同步、灌库后一次 `ensure_ready`；批数回到 7/8/8/8 |
| 回退 | 计划 `index_embedding` 回到 8/9/11/13（冻结配方值） | 会重现 `INDEX_NOT_READY`（已实测），不建议 |

> 本包未做任何一项：均超出「只改 v3 计划参数」的授权，且任何改动都会再次改变 `code_version` → 需要重绑 → 再跑。

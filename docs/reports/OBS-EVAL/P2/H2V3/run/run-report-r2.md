# H2 v3 基线「诊断 + 重跑」包报告（v3-run-r2）

- 结论：**`NOT_RUN`** —— 诊断已出结论，且结论是「**按现状开跑必然在第 0 回合以同一码中止**」；修复落在**本包未获授权**的
  C 冻结件/冻结配方上，因此**未开任何付费尝试**（0 请求、0 元），r0–r3 全部 `NOT_RUN`。
- 工作区：`D:\GPT项目\市场部AI知识库`，分支 `codex/p2-e2e`，HEAD `97b0066726e5b8d6f94cbc0b63a890084550c106`，暂存 **0** 项
- 计划/GO：四份 GO `scope.max_requests` 已按授权 1137 → **1150**（仅该字段），计划/绑定/语料/题集/账本未动
- 请求/金额：本包 **0 / 0**；累计仍 961（上限见 §3）；账本 `9d4b957a…`（1923 行、961/961 配对）、预算 `79b21700…` 均未变
- 未 stage/commit/push；未新建 worktree/切分支；未读题面/答案进产物

---

## 1. 本包做了什么

| 阶段 | 状态 | 产物 |
|---|---|---|
| 1 零调用诊断 | **完成**（结论见 `diagnosis.md`） | `diagnosis.md`、`diagnosis/offline-repro.json`、`diagnosis/probe_index_ready.py` |
| 2 GO 额度修正（授权内） | **完成** | `go-amend-evidence.json`、4 份 GO + 4 份改前字节归档 |
| 3 真实执行 | **未开跑**（见 §2/§4） | `round2-notrun/card-r0..r3.json`（全 0 请求、全 `NOT_RUN`） |

## 2. 诊断结论（一句话）

> 四份计划把 `index_embedding` 的请求上界 B 取自 v2 冻结配方（8/9/11/13），而 v3 语料 + 「每次发布都整体 sync」的真实所需
> 是 **9/10/13/15**；第 B+1 批在**发送前**被计划项配额拒绝（`p2_live.py:569-573`）→ 索引 `degraded/BUDGET_LEDGER_INVALID`
> → live 的 `require_zero_retries=True` 让下一回合 `qa.prepare` 直接 fail-closed（0 次出站）→ `INDEX_NOT_READY`
> → 缺 `plan_observed` → `EvidenceCaptureIncomplete` → `adapter_error`。

- 离线复现（零网络、产品自己的 ingest→publish→sync→prepare 路径）：**四 run 各用自己的 B 实测**，全部在「第 B+1 批」被
  发送前拒绝 → `degraded/BUDGET_LEDGER_INVALID`（19/20、20/21、19/21、18/20 块）→ `prepare` 0 次出站 → `INDEX_NOT_READY`；
  不带 cap 时 9/10/13/15 批即 `ready` → `prepare ok`。`cap=8` 与上一轮 live 的 7 个观测点逐项对齐。
- 明确否证：不是写未落盘/事务未提交/异步未 flush，也不是就绪检查用了错误 revision（详见 `diagnosis.md` §2）。
- 也**不是**「v3 入口漏了等待索引就绪」：v2 入口同样没有该步骤，产品的就绪判定本来就发生在回合内（`qa.prepare → ensure_ready`）。

## 3. 修复方案与「修复后会不会再 abort」

| 方案 | 改动面 | r0 复跑结果（离线） | 授权状态 |
|---|---|---|---|
| 不改 | — | **必 abort**（四 run 已按各自 B 实测；同码同因） | — |
| **A（推荐）**：灌库期暂停发布钩子同步，灌库后一次性 `ensure_ready()`（8 行） | `product_adapter.py`（**C 冻结 12**）→ `code_version` 变 → 重绑 | 四 run 7/8/8/8 批 ≤ 现有 B，`ready`、`chunk_embeddings==chunks`、`prepare ok` | **未授权**（本包只给 diff） |
| B：B 调到 9/10/13/15（或留余量 10/11/14/16） | `RECIPES` + 冻结 scenario contract → 新计划/新 GO/重绑/再冻结 | `cap=9` 时 r0 `ready`、`prepare ok` | **未授权**（更重的冻结改动） |

> 两者都不在本包授权内（硬边界：不改 C 冻结 12 / 评测模块 / 冻结配方）。按纪律**不重试、不加钱、不手工修分**，故未开跑。

## 4. 为什么不开跑（纪律依据）

1. 诊断已证明现状必中止；开跑只会重演上一轮（≈9 请求 / ~0.02 元）并再次 `ABORTED_AT_run0`，不产生新的有效基线数据。
2. 修复必须改 C 冻结件或冻结配方 → 需经理授权 + 独立验收 + 重绑；本包无权自行改。
3. 三项硬条件（GO 余量 176 < 185 最坏值、计划/绑定、代码身份）本包只能解决其中 GO 层（见 §5），其余需授权链。

## 5. GO 额度修正（阶段 2，已完成）

| run | GO 文件 | 文件 SHA-256 前 → 后 | payload SHA-256 前 → 后 | 变化叶子 |
|---:|---|---|---|---|
| 0 | `P2-LIVE-GO.json` | `dbc198c8bf8ee11c…` → `b7d1aae4cd5e22ca…` | `7bc70c01b8cc8284…` → `4dbfabe48634f8fb…` | `scope.max_requests: 1137→1150` |
| 1 | `P2-LIVE-GO.v3-r1.pending.json` | `a8516ac3d71a9fd9…` → `967809e046f98974…` | `6d7ff5a3ec7a63e2…` → `1511a84f3375d77d…` | 同上 |
| 2 | `P2-LIVE-GO.v3-r2.pending.json` | `d7edf6d256cd1988…` → `0fe202e2a2857533…` | `2f14d75a403698a1…` → `6413252f4573746b…` | 同上 |
| 3 | `P2-LIVE-GO.v3-r3.pending.json` | `d681b673837d6815…` → `161ba99c2ce98ad0…` | `b2ec8ccdbd20b4ae…` → `9026c1c3dbfa8267…` | 同上 |

- 逐叶子 diff 证明「**只有** `scope.max_requests` 变」（4/4 `only_max_requests_changed=true`）；字节数前后一致（1183/1201/1207/1209）。
- 改前字节归档：`P2-LIVE-GO.v3-max1150-r{0..3}.previous.archived.json`（新文件名，不覆盖既有归档；SHA 见证据文件）。
- 上限自检：961 + 185 = 1146 ≤ 1150 ≤ 1500（owner 授权总量），改后余量 189（最坏跑完余 4）。
- 金额零变化：项目 40（已 22.2237363）、阶段 20（已 7.1527918）、单请求 0.5；账本/预算字节未变。
- 零发送复检：`diagnosis/go-amend-check-r2.json`（`check-only --plan-only`）`go_binding`/`plan_binding`/`zero_write`/`zero_send` 全绿，
  `go.max_requests=1150`、`requests_used=961`、`ledger_sha256_before==after`。
- **重要限制（发现）**：有效上限 = `min(plan.max_requests=1137, GO=1150)` = **1137**（`p2_authorization.py:620`），
  余量仍 **176**。要让「四 run 最坏 185」真正有余量，需 `plan-private --max-requests 1150` 重发计划（`plan_sha256` 变→GO 重发→重绑）。
  本包未做（超出「只调该字段」的授权），已登记为残余 D2。

## 6. 逐 run 结果（全部 `NOT_RUN`，零请求）

| run | scenario | business_date | 计划请求 | 计划 ingest 批 | 实测所需批 | 状态 | 请求 | 金额（元） |
|---:|---|---|---:|---:|---:|---|---:|---:|
| 0 | `base_b0` | 2026-10-15 | 64 | 8 | **9** | NOT_RUN | 0 | 0 |
| 1 | `base_b0_plus_v01` | 2026-07-15 | 49 | 9 | **10** | NOT_RUN | 0 | 0 |
| 2 | `pre_v05_without_v07` | 2026-11-20 | 35 | 11 | **13** | NOT_RUN | 0 | 0 |
| 3 | `post_v05_without_v01` | 2026-12-15 | 37 | 13 | **15** | NOT_RUN | 0 | 0 |
| 合计 | — | — | 185 | 41 | 47 | 4 × NOT_RUN | **0** | **0** |

- 逐 run 卡：`round2-notrun/card-r0.json` … `card-r3.json`（`status=NOT_RUN`、`stop_code=precondition_blocked`、
  `error_code=INDEX_EMBEDDING_BUDGET_SHORT`、`real_sends=0`、四轴/`pass_fail_error` 为 `null`，不填 0 冒充实测）。
- 安全聚合：`round2-notrun/aggregate.json`（含有效上限提示）。
- 上一轮 r0 中止的原始卡/回执/状态（`run/r0/*`、`run/r1..r3/status.json`、`run/conclusion.json`、`run/run-report.md`）**原样保留**，未改写。

## 7. 请求与金额对账

| 项 | 执行前 | 执行后 | 上限 | 状态 |
|---|---:|---:|---:|---|
| 本包请求（尝试/出站） | 0 / 0 | **0 / 0** | 185 | 未消耗 |
| 累计请求（有效上限 `min(plan,GO)`） | 961 | **961** | 1137（GO 已抬到 1150，计划仍 1137） | 未越 |
| 账本已记账（元） | 22.2237363 | **22.2237363** | 40.00 | 未越 |
| P2-LIVE 阶段（元） | 7.1527918 | **7.1527918** | 20.00 | 未越 |
| 单请求上限（元） | — | — | 0.50 | 未越 |

- 账本文件 SHA-256：`9d4b957ac431acfe7b04d0c441dd0c77e31c15849e84806fbbc8c23c4e3de413`（前=后；1923 行；reservation/result 961/961 配对 true）
- 预算文件 SHA-256：`79b21700b630be92148e2a8498ed47386dab08d6daa401601dc3d22a910b1a9e`（前=后）
- 中断：**无**（本包未发起任何真实发送，故无中断码；上一轮的中断码 `adapter_error`/`INDEX_NOT_READY` 仍记录在 `run/`）

## 8. 保全与纪律

- C 冻结 12：**12/12 未变**；仓外 v2/v3 语料与密文：**13/13 未变**；`fixtures/acceptance-h2v3`：**13/13 未变**。
- 受保护仓内件 14 项：仅 4 份**授权** GO 变化（`scope.max_requests` 一个叶子）；`live-ledger.jsonl` 的差异来自**上一轮** r0 中止的真实花费
  （本包零请求，字节停在上一轮结束值）。证据：`round2-notrun/preservation-check.json`（`ok=true`）。
- HEAD/分支未变、暂存 0 项、tracked modified 仍 22 条同路径；未 stage/commit/push、未新建 worktree/切分支。
- 未改：v2/v3 语料与密文、评测模块代码、账本内容、30 题/标签/阈值、四轴与评分标准。
- 未把任何真实 H2 题面/答案写入公开产物：离线复现只读语料与产品代码，产物只含路径/计数/哈希/固定码。

## 9. 残余与建议下一步（需经理裁决）

| # | 残余 | 级别 | 建议 |
|---:|---|---|---|
| D1 | 索引批数缺口 | 高 | 二选一授权：**A**（改 `product_adapter.py` 8 行 + 重绑 + 定向测试）或 **B**（改冻结配方/契约 + 重发计划/GO + 重绑） |
| D2 | 有效请求上限仍 1137（176 余量） | 中 | `plan-private --max-requests 1150` 重发四份计划 → GO 重发 `scope.plan_sha256` → 重绑（可并入 D1 的授权包） |
| D3 | GO 散文字段仍写 1137 | 低 | 机器字段以 `scope.max_requests=1150` 为准；是否改散文由经理定 |
| D4 | 修复后代码身份变化 | 中 | 方案 A 会改 `code_version` → 四份 binding 失效，需重绑（复用上一轮 `rebind` 流程） |
| D5 | `Dxx_` 前缀 / 双门店槽位 | 中 | 产品/ingest 命名侧已知问题，只影响个别题，不阻塞 run |
| D6 | 失败码语义迁移（首回合 INDEX_NOT_READY → ingest_failed） | 低 | 若采纳方案 A，在证据规范登记 |

**建议执行顺序**：授权 D1-A + D2 → 改 1 文件 8 行 → 跑 P2 定向测试与离线复现（应 7/8/8/8 全 `ready`）→ 重发计划 + 重发 GO + 重绑
→ 再按原纪律串行 r0→r3（此时才不会 abort）。

## 10. 本包产物

- `diagnosis.md`：成因、逐层链路、离线复现、三问三答、两套修复 + diff/风险、修复后判据、额度/金额、残余
- `diagnosis/offline-repro.json`：四 scenario + `cap=8` 复现 + 修复模拟（7/8/8/8）的机读证据
- `diagnosis/probe_index_ready.py`、`diagnosis/amend_go.py`：可复跑脚本（仓外执行，产物落仓内）
- `diagnosis/go-amend-check-r2.json`：改 GO 后的零发送复检（工具直出）
- `go-amend-evidence.json`：4 份 GO 改前/改后 SHA、归档 SHA、逐叶子 diff、额度自检、账本/预算同值
- `round2-notrun/card-r0..r3.json`、`round2-notrun/aggregate.json`、`round2-notrun/preservation-check.json`
- 保留未动：`run/conclusion.json`、`run/run-report.md`、`run/r0/*`、`run/r1..r3/status.json`、`run/round1-notrun/*`、`run/preflight/*`

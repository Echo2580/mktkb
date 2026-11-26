# H2 v3 run0 真实执行报告（B+ 修复后，`v3-run-r4`）

- 结论：**`COMPLETED`**（run0 首次真实跑通：12 题 / 14 回合全部执行、证据 14/14 封存、`status=succeeded`、无 `stop_code`、无 `error_code`）
- 请求（尝试）**48**、出站 `real_sends` **43**、本 run 花费 **0.1110268 元**；账本自然增长、预算字节未变
- 逐题：**7 pass / 5 fail / 0 error**；硬失败与四轴 **无实测值（不填 0）**
- 工作区：`D:\GPT项目\市场部AI知识库`，分支 `codex/p2-e2e`，HEAD `97b0066726e5b8d6f94cbc0b63a890084550c106`，暂存 **0** 项
- 未 stage/commit/push；未新建 worktree/切分支；未把题面/答案/query 文本写入任何仓内产物

---

## 1. 现场核对（开工前）

| 项 | 期望 | 实测 | 结论 |
|---|---|---|---|
| 分支 / HEAD | `codex/p2-e2e` / `97b00667…` | 同 | ✅ |
| 暂存 | 0 | 0 | ✅ |
| 账本 SHA-256 / 行数 / 配对 | `9d4b957a…` / 1923 / 961:961 | `9d4b957ac431acfe7b04d0c441dd0c77e31c15849e84806fbbc8c23c4e3de413` / 1923 / 961:961 paired | ✅ |
| 预算 SHA-256 / `limit_cny` | `79b21700…` / 40 | `79b21700…` / 40 | ✅ |
| r0 计划 `index_embedding` | 9 | 9（`contract_recipe_requests=8` + `authorized_delta`） | ✅ |
| r0 计划 `max_requests` | 1160 | 1160 | ✅ |
| run0 `plan_sha256` / plan 文件 SHA | `70f8f373…` / `c74eb105…` | `70f8f373e1314300aaacd7c872d41b55c9713403d29e2b305595e5fb5078aa52` / `c74eb105cc604b4b24ffbad936b642d534b00e88f6b78ae1d2ea9050681f379b` | ✅ |
| GO 文件 / 记录 SHA、槽位 | `215398d1…` / `88a3e829…` / fixed | 同；`plan_sha_match=true`、`plan_id_match=true` | ✅（未重发） |
| run0 binding SHA / `code_version` | `5414fef4…` / `f2d707f3…` | 同 | ✅（B+ 修复后重绑） |

> 重绑理由链（改代码 → `code_version` 变 → binding 失效；plan 字节不变 → GO 不必重发）见 `run/r0-fix/dev-report.md` §6。

## 2. 执行与结果

| 项 | 值 |
|---|---|
| 入口 | `tools/p2_h2_v3_controlled_execute.py run`（`p2-h2v3-controlled-entry/v0.1`） |
| scenario / business_date | `base_b0` / `2026-10-15` |
| 计划 | 12 题 / 14 回合 / 65 请求 / ingest 9 批 |
| 开始 / 结束（UTC） | `2026-11-15T06:00:51` / `2026-11-15T06:01:32` |
| 耗时 | **40.5 s**（`duration_ms=40546`） |
| `ok` / `run_status` / `stop_code` / `error_code` | **true** / **succeeded** / `null` / `null` |
| 回合 | **14 / 14 executed**，逐回合 `error` 全 `None` |
| 证据 | `available=true`、`turn_files=14`、`manifest_turn_count=14`、`status_counts={complete:14}`、`readback_ok=true`、`error_count=0` |
| 封存 | `sealed=true`、`mode=read_only_archive`、`evidence_file_count=15`、`evidence_bytes=270680`、`evidence_tree_sha256=69fb4093…`、`seal_manifest_sha256=838b5b07…` |
| case-plan | 已生成（12 题 / 14 回合，`sha256=bb9b1963adbacd814bebd9df3e878b742ec80420bb9099c3eb5d5647226cf238`，只落仓外封存区） |
| 契约复核 | check 层 `index_embedding_batches_v3_derived`；执行层放行（`_V3BatchContract`），`plan_recompute.ok=true` |
| `INDEX_NOT_READY` | **未再现**（9 批 ingest 全部走完，0 个 `error_code`） |

## 3. 真实计数（四轴与硬失败「无分数」）

| 项 | 值 | 依据 |
|---|---|---|
| 题 | 12 | 计划/实测一致 |
| 回合 | 14 | 14 回合 `executed`、证据 14/14 `complete` |
| pass | **7** | 逐题 `quality_status=pass` |
| fail | **5** | 逐题 `quality_status=fail` |
| error | **0** | 无 `quality_status=error`、逐回合 `error` 全 `None` |
| 硬失败 | **无实测值** | 本 run 只产出逐题 pass/fail；`P2_HOLDOUT_HARD_FAILURE_KINDS` 聚合属四 run 汇总（`compose_scenario_runs`）阶段，本包未执行 → **不填 0** |
| 四轴 `safety` / `cross_user` / `cross_entity` / `stale_source` | **无实测值** | 逐轴判定属 rescore/axes 阶段（`p2_evidence_axes_adapter_v2` / Q1a-1b），本 run 未执行该步骤 → **不填 0**；已封存的 14 份回合证据可作其输入 |
| `real_calls` / `real_sends` | 43 | `receipt.real_sends` |

> 明确区分：`docs/evaluation/p2-holdout-v3.authoring-aggregate.json` 里的 `axis_counts` 是**冻结标注分布**，不是本 run 的运行时逐轴判定，二者不可互相替代。

## 4. 请求数与金额（三种口径，账本为权威）

| 口径 | 值 | 来源 |
|---|---|---|
| 计划 | 65 请求 / 最坏 0.637568 元 | plan |
| **尝试口径（纪律口径）** | **48** 次预留 = `answer 14 + index_embedding 9 + query_embedding 13 + rerank 12` | 账本（+48 `reserved` 行） |
| 出站 | `real_sends=43`（48 次尝试中 5 次失败未出网或未计费成功） | `receipt.real_sends` |
| answer 单侧口径 | `reserved=14`、`sent(settled)=9`、`settled_cny=0.106874` | `receipt.requests`（answer-only） |
| **账本权威** | **+48 reservation / +48 result（配对）**；`by_kind = embedding 22 / rerank 12 / chat 14`；`succeeded 43 / failed 5`；**花费 +0.1110268 元** | 账本逐行核算 |
| 单请求最大扣费 | **0.018688 元**（chat 失败兜底档，< 0.5） | 账本 |

## 5. 账本与预算（前后逐值）

| 项 | 执行前 | 执行后 | 上限 | 状态 |
|---|---|---|---|---|
| 账本文件 SHA-256 | `9d4b957ac431acfe7b04d0c441dd0c77e31c15849e84806fbbc8c23c4e3de413` | **`31c15c1ff3e0eb3c6eb9a67ca260830095017e29df1a4df57b0aa665f2345942`** | — | 自然增长 |
| 账本行数 | 1923 | **2019**（+96） | — | ✅ |
| reservation / result | 961 / 961（paired） | **1009 / 1009（paired）** | — | ✅ 配对未破 |
| 已记账（项目，元） | 22.2237363 | **22.3347631**（+0.1110268） | 40.00 | 未越 |
| P2-LIVE 阶段（元） | 7.1527918 | **7.2638186**（+0.1110268） | 20.00 | 未越 |
| 预算文件 SHA-256 | `79b21700…1a9e` | **`79b21700…1a9e`（未变）** | `limit_cny=40` | ✅ |

## 6. 额度纪律（逐项）

| 约束 | 上限 | 本包实测 | 状态 |
|---|---|---|---|
| 本包请求（尝试） | 80 | **48** | ✅ |
| 累计请求 | ≤1500（计划/GO 有效上限 1160） | **1009** | ✅（余 151 / 治理余 491） |
| 项目累计金额 | ≤40 元 | **22.3347631** | ✅ |
| 阶段（P2-LIVE）金额 | ≤20 元 | **7.2638186** | ✅ |
| 单请求金额 | ≤0.5 元 | **0.018688** | ✅ |
| 重试 | 0 | **0 次**（只发 1 次 run 调用） | ✅ |
| 手工修分 | 0 | **0** | ✅ |

## 7. 纪律与保全

- **首错即停**：本 run 无错误，纪律未触发；未重试、未加钱、未改计划、未手工修分。
- 未改：C 冻结 12、v2/v3 语料与密文、评测模块、账本内容（仅真实花费自然增长）、预算、30 题/标签/阈值、GO 内容。
- 明文：`cleanup.plaintext_clean=true`、`final_plaintext_scan={clean:true, files_scanned:1, hit_count:0, needles:66}`、`business_db_removed=true`、`purge_traces_on_close=true`。
- 仓内新增：`run/r0/{card,case-plan,run-receipt,status}.json`、`run/r0-fix/**`、`run/run-r0-report-b.md`、`run/r0-attempt2/**`（上一轮 NOT-RUN 产物逐字节归档）。
- 未 stage/commit/push；暂存 0 项；未新建 worktree/切分支。

## 8. 结论

**`COMPLETED`**（`status=succeeded`、`stop_code=null`、`error_code=null`、请求 48、花费 0.1110268 元、账本 1009:1009 配对、预算未变）。

B+ 修复被真实执行验证：check 层的 `authorized_delta`（`index_embedding: 8→9`）已透传到执行层，冻结契约不再整 run 拒绝；`product_adapter.py` 与 C 冻结 12 对象全程逐字节未动。

后续（不在本包授权内，供经理裁决）：run1–run3 尚未执行；四轴与硬失败需另跑 rescore/axes 与四 run 汇总步骤。

# H2 v3 run1–run3 真实执行报告（串行、零重试）

- 结论：**`COMPLETED`**（run1/run2/run3 全部 `succeeded`、`stop_code=null`、`error_code=null`、证据 10/6/6 份全 `complete`）
- 本包：题 **18** / 回合 **22**；pass **11** / fail **7** / error **0**；请求（尝试）**90**、出站 `real_sends` **83**；花费 **0.1642634 元**
- 四 run 合计：题 **30** / 回合 **36**；pass **18** / fail **12** / error **0**；累计请求 **138**（账本 1099:1099 配对）；累计花费 **0.2752902 元**
- 硬失败与四轴：**无实测值（不填 0）** —— 属后续 `compose_scenario_runs` / rescore-axes 阶段
- 工作区：`D:\GPT项目\市场部AI知识库`，分支 `codex/p2-e2e`，HEAD `97b0066726e5b8d6f94cbc0b63a890084550c106`，暂存 **0** 项
- 未 stage/commit/push；未新建 worktree/切分支；未把题面/答案/query/case_id 写入任何仓内产物

---

## 1. 前置核对（开工前）

| 项 | 期望 | 实测 | 结论 |
|---|---|---|---|
| 分支 / HEAD | `codex/p2-e2e` / `97b00667…` | 同 | ✅ |
| 暂存 | 0 | 0 | ✅ |
| 账本 SHA-256 / 行数 / 配对 | `31c15c1f…` / 2019 / 1009:1009 | `31c15c1ff3e0eb3c6eb9a67ca260830095017e29df1a4df57b0aa665f2345942` / 2019 / 1009:1009 paired | ✅ |
| 预算 SHA-256 / `limit_cny` | `79b21700…` / 40 | `79b21700b630be92148e2a8498ed47386dab08d6daa401601dc3d22a910b1a9e` / 40 | ✅ |
| 累计请求 | 1009 / 1160 | 1009（余 151） | ✅ |
| r1–r3 GO 存在且为待装槽 | 3 份 `.pending.json` | `P2-LIVE-GO.v3-r{1,2,3}.pending.json`（`d4dc1eb2…` / `b3822026…` / `5886f84a…`） | ✅ |
| `check-only`×3 | 全 `ok`、零请求、零写 | **3/3 `ok=true`、`reasons=[]`、检查 16/16 全绿**、`external_attempts=0`、`local_attempts=0`、`ledger_unchanged=true`、`budget_unchanged=true` | ✅ |

### 1.1 `check-only` 明细（零发送；证据 `run/r123/check-only-r{1,2,3}.json`）

| run | `ok` | 检查 | `plan_id` | `plan_sha256` | `go.plan_sha_match` / `plan_id_match` | 槽位 | 计划请求 / 最坏金额 |
|---|---|---|---|---|---|---|---|
| r1 | **true** | 16/16 | `P2-H2V3-20261115-r1-base_b0_plus_v01` | `5019efb4…` | true / true | `simulated_pending` | 50 / 0.46272 元 |
| r2 | **true** | 16/16 | `P2-H2V3-20261115-r2-pre_v05_without_v07` | `9c609a00…` | true / true | `simulated_pending` | 37 / 0.291968 元 |
| r3 | **true** | 16/16 | `P2-H2V3-20261115-r3-post_v05_without_v01` | `554d1f09…` | true / true | `simulated_pending` | 39 / 0.296064 元 |

> **口径校正（如实记录）**：任务书写的 `plan_sha256=70f8f373…` 是 **run0** 的计划哈希；`plan_sha256` 是**逐 plan** 字段，run1–run3 各自绑定自己的计划：
> r0 `70f8f373…`、r1 `5019efb4…`、r2 `9c609a00…`、r3 `554d1f09…`（均 `check-only` 实测 `plan_sha_match=true`）。
> 四份计划同属一个计划集（`regen-1160c/plans`，`max_requests=1160`），GO 亦各自绑定本 run 的 `plan_id` + `plan_sha256`，未放宽任何一项。
> 另：r0 的 `authorized_delta` 为 `index_embedding 8→9`；r1/r2/r3 分别为 `9→10`、`11→13`、`13→15`（census 派生），check 层与执行层逐值一致。

### 1.2 GO 装槽（每 run 用自己那份 GO；字节不变）

| 步骤 | 动作 | 结果 |
|---|---|---|
| r1 装槽 | 归档 r0 槽位件 → `P2-LIVE-GO.v3-r0.done.archived.json`（`215398d1…`，byte-identical）→ 复制 `v3-r1.pending` 到固定槽 | `installed=d4dc1eb2…`、`byte_identical=true` |
| r2 装槽 | 归档 r1 → `P2-LIVE-GO.v3-r1.done.archived.json`（`d4dc1eb2…`）→ 复制 `v3-r2.pending` | `installed=b3822026…`、`byte_identical=true` |
| r3 装槽 | 归档 r2 → `P2-LIVE-GO.v3-r2.done.archived.json`（`b3822026…`）→ 复制 `v3-r3.pending` | `installed=5886f84a…`、`byte_identical=true` |
| 收尾 | 固定槽位保留 r3 那份（同字节副本已存 `P2-LIVE-GO.v3-r3.done.archived.json`，`5886f84a…`） | 槽位件与归档件逐字节相同 |

> 全程**未改写任何 GO 内容**（只做「归档 + 复制」），`budget_total_limit_cny=40`、`max_requests=1160`、`max_request_cny=0.5`、`P2-LIVE=20`、`plan_sha256` 均未变。

## 2. 执行（串行；后台 + 长超时；每 run 跑完立即落盘）

命令（`cwd=仓库根`，`MKTKB_PROJECT_TOTAL_LIMIT_CNY=40`，逐 run 一次尝试、零重试）：

```
python tools/p2_h2_v3_controlled_execute.py run \
  --binding <regen-1160c>/bindings/run<N>-<scenario>.binding.json --run-index <N> \
  --out-dir <runs/r<N>c/out> --evidence-root <runs/r<N>c/evidence> --seal-root <runs/r<N>c/seal> \
  --evidence-key-file <runs/r0/ev.key> --env-file .env
```

| 项 | run1 | run2 | run3 |
|---|---|---|---|
| scenario / `business_date` | `base_b0_plus_v01` / **2026-07-15** | `pre_v05_without_v07` / **2026-11-20** | `post_v05_without_v01` / **2026-12-15** |
| 计划 题 / 回合 / 请求 / ingest 批 | 8 / 10 / **50** / 10 | 5 / 6 / **37** / 13 | 5 / 6 / **39** / 15 |
| 开始 / 结束（UTC） | `06:09:32` / `06:10:00` | `06:10:21` / `06:10:50` | `06:11:02` / `06:11:28` |
| 耗时 | 27.4 s（`27434`） | 28.8 s（`28804`） | 25.7 s（`25663`） |
| `ok` / `status` / `stop_code` / `error_code` | true / **succeeded** / `null` / `null` | true / **succeeded** / `null` / `null` | true / **succeeded** / `null` / `null` |
| 回合 | **10 / 10 executed**，逐回合 `error` 全 `None` | **6 / 6** 同 | **6 / 6** 同 |
| 证据 | `turn_files=10`、`status_counts={complete:10}`、`readback_ok=true`、`error_count=0` | `turn_files=6`、`{complete:6}`、`readback_ok=true`、`error_count=0` | `turn_files=6`、`{complete:6}`、`readback_ok=true`、`error_count=0` |
| 封存 | `sealed=true`、`read_only_archive`、11 文件 / 203304 B、`tree=a36ee057…`、`seal_manifest=6b32c724…` | `sealed=true`、7 文件 / 117616 B、`tree=f1d76284…`、`seal_manifest=1df89754…` | `sealed=true`、7 文件 / 129888 B、`tree=05cde4f0…`、`seal_manifest=c8ba1d3d…` |
| case-plan（仓外封存） | `894d0818…` | `decb8897…` | `887614d1…` |
| 契约复核 | `index_embedding_batches_v3_derived`、`plan_recompute.ok=true` | 同 | 同 |
| `INDEX_NOT_READY` | **未再现** | **未再现** | **未再现** |
| 明文清理 | `plaintext_clean=true`、`hits=0`、`needles=66`、`business_db_removed=true` | 同 | 同 |

## 3. 逐 run 真实计数

| run | 题 | 回合 | pass | fail | error | 依据 |
|---|---|---|---|---|---|---|
| r1 | **8** | **10** | **4** | **4** | **0** | 逐题 `quality_status`；10/10 回合 `executed`、`error` 全 `None` |
| r2 | **5** | **6** | **4** | **1** | **0** | 同上（6/6） |
| r3 | **5** | **6** | **3** | **2** | **0** | 同上（6/6） |
| **r1–r3 合计** | **18** | **22** | **11** | **7** | **0** | — |

## 4. 请求数与金额（三种口径，账本为权威）

| 口径 | run1 | run2 | run3 | r1–r3 合计 |
|---|---|---|---|---|
| 计划 | 50 | 37 | 39 | **126** |
| **尝试口径（纪律口径）** | **32** | **31** | **27** | **90** |
| 　answer / index_embedding / query_embedding / rerank | 10 / 10 / 6 / 6 | 6 / 13 / 6 / 6 | 6 / 15 / 3 / 3 | 22 / 38 / 15 / 15 |
| 出站 `real_sends` | 28 | 30 | 25 | **83** |
| answer 单侧（`reserved`/`sent`/`settled`） | 10 / 6 / 0.084372 | 6 / 5 / 0.026074 | 6 / 4 / 0.043768 | 22 / 15 / 0.154214 |
| **账本权威花费（元）** | **0.0872875** | **0.0293917** | **0.0475842** | **0.1642634** |
| 本 run 单请求最大扣费（元） | 0.018688 | 0.018688 | 0.018688 | 0.018688 |

> `real_sends` 与「尝试」不一致属预期：部分预留在出网前或计费成功前即失败，账本仍按尝试逐条配对记账。
> 最大单请求扣费只取**本 run 窗口内新增**的 `result` 行；账本里历史 P2-LIVE 段存在更早的 OCR 0.5 元档，与本包无关（本包未发 OCR）。

## 5. 账本与预算（前后逐值 + 配对链）

| 阶段 | 账本 SHA-256 | 行数 | reservation : result | 项目累计（元） | 阶段（P2-LIVE，元） |
|---|---|---|---|---|---|
| 开工前 | `31c15c1f…45942` | 2019 | **1009 : 1009** | 22.3347631 | 7.2638186 |
| r1 后 | `42e8a7e6…de08f7` | 2083 | **1041 : 1041** | 22.4220506 | 7.3511061 |
| r2 后 | `67b6c095…785f9a` | 2145 | **1072 : 1072** | 22.4514423 | 7.3804978 |
| r3 后（终态） | `22a4e85c…a931e` | 2199 | **1099 : 1099** | **22.4990265** | **7.4280820** |

- 每 run 增量：r1 `+32 预留 / +32 结果 / +64 行 / +0.0872875 元`；r2 `+31 / +31 / +62 / +0.0293917`；r3 `+27 / +27 / +54 / +0.0475842`
- **配对全程未破**（每个 run 后 `reservation == result`，`paired=true`）
- 预算文件 SHA-256 前后**同值** `79b21700…b1a9e`，`limit_cny=40` **未变**（`budget_unchanged=true` ×3）
- 账本绑定链：三份 GO 的 `budget_ledger_sha256 = f4710b18…` 是不可变历史前缀，与每 run receipt 的 `bindings.ledger_sha256` 逐值一致 → 绑定合法、未失效

## 6. 四 run 合计（含 r0）

| 项 | r0 | r1 | r2 | r3 | **四 run 合计** |
|---|---|---|---|---|---|
| 题 | 12 | 8 | 5 | 5 | **30** |
| 回合 | 14 | 10 | 6 | 6 | **36** |
| pass | 7 | 4 | 4 | 3 | **18** |
| fail | 5 | 4 | 1 | 2 | **12** |
| error | 0 | 0 | 0 | 0 | **0** |
| 请求（尝试） | 48 | 32 | 31 | 27 | **138** |
| 出站 `real_sends` | 43 | 28 | 30 | 25 | **126** |
| 花费（元） | 0.1110268 | 0.0872875 | 0.0293917 | 0.0475842 | **0.2752902** |

- 账本（四 run 全程）：`9d4b957a…`（1923 行 / 961:961）→ **`22a4e85c…`（2199 行 / 1099:1099）**，**+138 预留 / +138 结果**，配对未破
- 项目累计金额：22.2237363 → **22.4990265 元**（+0.2752902）；阶段 P2-LIVE：7.1527918 → **7.4280820 元**
- 硬失败 / 四轴：**无实测值**（见 §8）

## 7. 额度纪律（逐项）

| 约束 | 上限 | 本包实测 | 状态 |
|---|---|---|---|
| 本包请求（尝试） | 151 | **90** | ✅ |
| 累计请求 | ≤1500（GO 有效上限 1160） | **1099** | ✅（GO 余 61 / 治理余 401） |
| 项目累计金额 | ≤40 元 | **22.4990265** | ✅ |
| 阶段（P2-LIVE）金额 | ≤20 元 | **7.4280820** | ✅ |
| 单请求金额 | ≤0.5 元 | **0.018688** | ✅ |
| 重试 | 0 | **0 次**（每 run 只发 1 次 `run` 调用） | ✅ |
| 手工修分 / 改计划 / 加钱 | 0 | **0** | ✅ |

## 8. 「无实测值」的项（绝不以 0 代替）

| 项 | 状态 | 理由 |
|---|---|---|
| 硬失败聚合（`P2_HOLDOUT_HARD_FAILURE_KINDS`） | **无实测值** | 属四 run 汇总步骤（`compose_scenario_runs`），本包只产出逐题 pass/fail |
| 四轴 `safety` / `cross_user` / `cross_entity` / `stale_source` | **无实测值** | 逐轴判定属 rescore/axes 阶段（`p2_evidence_axes_adapter_v2` / Q1a-1b），本包未执行该步骤；已封存的 22 份回合证据可作其输入 |

> `docs/evaluation/p2-holdout-v3.authoring-aggregate.json` 的 `axis_counts` 是**冻结标注分布**，不是运行时逐轴判定，二者不可互相替代。

## 9. 纪律与保全

- **首错即停未触发**：三个 run 全 `succeeded`，无任何 `error_code`，故未停、未重试、未加钱、未改计划、未手工修分。
- **未改**：C 冻结 12（`product_adapter.py`=`c9378f81…`、`p2_holdout_scenarios.py`=`bb9ae59a…`、`p2_holdout_plan.py`=`d0cb23de…` 逐字节同基線）、v2 入口（`ad215251…`）、v3 入口（`9750eb18…`，B+ 透传保持生效、**未改回**）、v2/v3 语料与密文、评测模块、账本内容（仅真实花费自然增长）、预算、30 题/标签/阈值、GO 内容。
- **明文安全**：三 run 均 `plaintext_clean=true`、`final_plaintext_scan.hit_count=0`（66 needles）、`business_db_removed=true`、`purge_traces_on_close=true`；证据全部 Fernet 密文（与 r0 同一把 key，`evidence_key_sha256=2acaf7b8…`）。
- **未 stage/commit/push**；暂存 0 项；未新建 worktree/切分支。
- 仓内新增（版本库可见）：`run/r{1,2,3}/{card,case-plan,run-receipt,status}.json`、`run/r123/**`（本报告、`aggregate.json`、驱动脚本 `r123_lib.py`、前后快照 `before/after-r{1,2,3}.json`、`check-only-r{1,2,3}.json`、`final-state.json`）、`run/run-r123-report.md`。
- GO 装槽落点：`docs/evidence/LOCAL-R1-20261101/PM/`（`P2-LIVE-GO.json` + `P2-LIVE-GO.v3-r{0,1,2,3}.done.archived.json`）——该目录被 `.gitignore:10 docs/evidence/` 覆盖，不进版本库、不影响暂存。

## 10. 结论

**`COMPLETED`** —— run1/run2/run3 串行真实跑通（`succeeded`、无 `stop_code`、无 `error_code`），本包 18 题 / 22 回合、pass 11 / fail 7 / error 0、请求 90、花费 0.1642634 元；四 run 合计 30 题 / 36 回合、pass 18 / fail 12 / error 0、累计请求 138（1099:1099 配对）、累计花费 0.2752902 元，预算未变。

**残余（不在本包授权内，供经理裁决）**：硬失败聚合与四轴（`safety`/`cross_user`/`cross_entity`/`stale_source`）仍需另跑 `compose_scenario_runs` 与 rescore/axes 步骤；已封存的 30 题 / 36 回合密文证据可作为其输入。

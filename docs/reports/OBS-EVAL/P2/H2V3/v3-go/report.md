# v3 run 计划与 GO 生成（H2V3/v3-go）

- 角色：v3 run 计划与 GO 生成角色（普通角色；执行经理已获主人 2026-11-15 预授权代签 v3 各 run GO）。
- 基线：分支 `codex/p2-e2e`，HEAD `97b0066726e5b8d6f94cbc0b63a890084550c106`，暂存区 0 项。
- 本包**零真实请求**：未发 HTTP、未 reserve、未改账本一个字节；账本 `ca9dceb9…`（1,932,692 B）与 `reservation_count=952` 在本包首尾逐值相同。
- 本包产物分两类：**仓外**（明文计划、GO staging、证据 JSON）与**仓内**（固定路径 GO + 归档件 + 本报告）。计划含 case_id，因此只在仓外，未入库。

> 本报告不使用"通过/Pass"一类结论词；只给逐值一致性与可复算的码位。

---

## 1. 三条前置（逐条复核）

| # | 前置 | 证据 | 结果 |
|---:|---|---|---|
| ① | v3 冻结 | `docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/v3-freeze/p2-holdout-v3.freeze.json`，SHA-256 `f7c484d3687edcde470b49ff708da3de75bc546dccb8aa4eb8a581da01129533`，21,671 B；`counts.artifacts=32`；`verification.result="OK 32/32"`、`exit_code=0`；`frozen_by=v3-freeze-b`（双人重算） | 32 件逐件哈希在册，复算 32/32 |
| ② | Mock 干跑 | `docs/reports/OBS-EVAL/P2/H2V3/dryrun/`（`REPORT.md` + `summary.json` + `prereg_comparison.json` + `runs/r0..r3/*`）：4 run 计 30 题 36 回合，实跑 35/36 回合；外部出站尝试 0、正对照 4/4 被拦 | 链路可跑、卡合规、四轴出数 |
| ③ | 预先登记 | `docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/v3-author/pre-registration.json`，SHA-256 `23cb3c08a8098557f27e8ad3bf433ce8a69111afcfca4aa587073ed9d60d4bce`，26,084 B；`status=frozen`、`v3_runs_before_registration=0` | 冻结于任何 v3 运行之前 |

数据集身份（只读）：`dataset_version=P2-HOLDOUT-v3.1`、`label_version=p2-holdout-v3.1-2026-11-15`、`manifest_sha256=de4125ca…`、30 题/36 回合；四 run 日期取自 L1 `docs/evaluation/p2-source-lifecycle-v1.json`（`bind_run` 逐值对账，未使用 manifest 的设计自检日）。

---

## 2. 四份 run 私有计划（仓外 `D:\mktkb-p2-h2v3-20261115\plans\`）

| run | scenario_id | business_date | 题/回合 | 请求实数 `total_requests` | ingest 批 | plan_id | `plan_sha256` | worst_case CNY | reserve_peak CNY |
|---:|---|---|---:|---:|---:|---|---|---:|---:|
| 0 | `base_b0` | 2026-10-15 | 12 / 14 | **64** | 8 | `P2-H2V3-20261115-r0-base_b0` | `349d424434bcd9742f76f05feb29b0fab56fb74f8a686ad56b3522626a960884` | 0.63552 | 0.018688 |
| 1 | `base_b0_plus_v01` | 2026-07-15 | 8 / 10 | **49** | 9 | `P2-H2V3-20261115-r1-base_b0_plus_v01` | `cd1dcdecb26a6b4dfcf23d7ef513a180785fd5e6265b17ae7b8187a89a962d39` | 0.460672 | 0.018688 |
| 2 | `pre_v05_without_v07` | 2026-11-20 | 5 / 6 | **35** | 11 | `P2-H2V3-20261115-r2-pre_v05_without_v07` | `6da15e8ad7650b598b1e63b302050e51bed3bd4a4981b03faeec60d176b38110` | 0.287872 | 0.018688 |
| 3 | `post_v05_without_v01` | 2026-12-15 | 5 / 6 | **37** | 13 | `P2-H2V3-20261115-r3-post_v05_without_v01` | `e2cff4ee0f064417c5eb8db8909a036f91fffdbf7dc737675667e14e9897634a` | 0.291968 | 0.018688 |

- 每 run 两份文件：`runN-<scenario>.plan.json`（完整 `p2-run-plan/v0.1` 文档，可被 `P2RunPlan.from_dict` 原样读回，读回后 `plan_sha256` 与上表逐值相同）与 `runN-<scenario>.binding.json`（参照 v2 `plans2/run-binding.json` 的单 run 形状）。
- `operations`（四 run 相同，5 项）：`answer`、`index_embedding`、`query_embedding`、`query_expansion`、`rerank`。无 OCR 项（v3 声明 `requires_ocr` 全 false），无 judge 项。
- 成本中心（四 run 相同）：`answer_retrieval 8.5 / ocr 6.5 / judge 3.0 / independent 2.0`，合计 20.00 = 阶段额度。`center_needs_cny`：`answer_retrieval = worst_case_cny`，其余三中心 0（计划不含这些操作）。
- `project_total_limit_cny = 50`、`stage_limit_cny = 20.0`、`max_requests = 1137`（口径见 §7）。
- 四 run 请求合计 **64 + 49 + 35 + 37 = 185**。

---

## 3. 四份 GO（每份绑定自己那个 run 的 `plan_sha256`）

| run | GO 落点 | GO SHA-256 | `max_requests` | 绑定的 `plan_sha256` | nonce |
|---:|---|---|---:|---|---|
| 0 | `PM/P2-LIVE-GO.json`（固定槽位，已装） | `8effb4b1545afcfd939892803bd93b9303be6cd155a8236563f2f374785ffdbf` | 1137 | `349d4244…96884` | `8d92583451e7ab80b86184c6e15232eb` |
| 1 | `PM/P2-LIVE-GO.v3-r1.pending.json`（已签名，未占槽位） | `5cdde637baf0e6a9319bb0245196d1407d51f80408b9d244b507ddd6b8d4c578` | 1137 | `cd1dcdec…62d39` | `af16dc45192097aa1829a9f53650da9e` |
| 2 | `PM/P2-LIVE-GO.v3-r2.pending.json`（已签名，未占槽位） | `cbce4ba4ceff02794e94eb76361763f157262154840245380824edbe80274af8` | 1137 | `6da15e8a…38110` | `707db9abb21716912c0a95c137315338` |
| 3 | `PM/P2-LIVE-GO.v3-r3.pending.json`（已签名，未占槽位） | `8a4c94fb5df1a1bd76c70dd26651624ec3696b14979de0367f2c22f6b5d78bc0` | 1137 | `e2cff4ee…97634a` | `7ce85f529af842bc90a5f01ea70fb80f` |

四份 GO 的公共字段（逐份相同）：

| 字段 | 值 |
|---|---|
| `document` / `schema_version` / `stage` | `P2-LIVE-GO` / `p2-live-go/v0.1` / `P2-LIVE` |
| `issued_by` | `PM (lead) — pre-authorized by owner 2026-11-15` |
| `issued_utc` / `expires_utc` | `2026-11-15T05:00:00+08:00` / `2026-11-29T05:00:00+08:00`（14 天，≤14 天上限） |
| `budget_total_limit_cny` | 50 |
| `budget_ledger_path` / `budget_ledger_sha256` | `docs/evidence/LOCAL-R1-20261101/budget/live-ledger.jsonl` / `f4710b1869fe43b9a609b58f772549f76370fbadd54f93685b76211d4b47a014`（历史前缀；账本增长不失效） |
| `scope.stage_limits_cny` | `{"P2-LIVE": 20.0}`（未动阶段上限） |
| `scope.max_request_cny` | 0.5（≥ 单次峰值预留 0.018688） |
| `scope.operations` / `scope.cost_centers_cny` | 同 §2 |

**为什么只有一份占固定槽位**：`P2_GO_PATH` 是单槽位（`docs/evidence/LOCAL-R1-20261101/PM/P2-LIVE-GO.json`），同一时刻只能有一个生效 GO。四份都已签名；run0 的占槽位（下一个要跑的 run），其余三份以 `.pending.json` 存放在同目录，换槽时按 v2 同一动作：先归档当前件、再写目标件。未删除、未覆盖任何既有件。

---

## 4. 旧 GO 归档

| 项 | 值 |
|---|---|
| 旧件 | `PM/P2-LIVE-GO.json`，SHA-256 `c72dc7abf6ba135fb6c53f77c35b40dda34e97cf535d3be212467c6734b27324`，1,233 B |
| 旧件内容 | `plan_id=P2-T207-H2-20261114-r1-r4-post_v05_without_v01`、`plan_sha256=110c4253…c6f4a`、`max_requests=1100`、`budget_total_limit_cny=40`、`expires_utc=2026-11-21T02:31:02+00:00` |
| 归档名 | `PM/P2-LIVE-GO.t207-h2-20261114-r3.done.archived.json`（沿用 v2 `P2-LIVE-GO.<tag>.done.archived.json`，`<tag>` 取该 GO 的 run_index=3） |
| 归档方式 | 复制（非移动），归档件 SHA-256 与旧件**逐字节相同**：`c72dc7ab…27324` / 1,233 B；旧件在归档后仍存在，然后才被 run0 的 GO 替换 |
| 旧件是否仍可取回 | 是：归档件字节相等，`git check-ignore` 显示 `docs/evidence/` 被 `.gitignore:10` 忽略，故归档件与 GO 均不入库、也不受版本控制影响 |

> 附带事实：预算从 40 改到 50 之后，**旧 `c72dc7ab…` GO 已不可能再授权任何真实发送**——它绑定的 v2 计划声明 `project_total_limit_cny=40`，而 `_check_budget_payload` 要求 `budget.limit_cny == plan.project_total_limit_cny`，会以 `budget_total_mismatch` 拒绝。因此本次换槽不是可选动作，而是改预算的必然后果。

---

## 5. budget 资金件：`limit_cny` 40 → 50

- 文件：`docs/evidence/LOCAL-R1-20261101/budget/budget.json`（`P2_BUDGET_PATH` 固定路径）。
- **注意字段实名**：该文件里没有 `total_limit_cny` 字段；项目总上限的实名字段是 **`limit_cny`**（`BudgetLedger` 与 `_check_budget_payload` 都读它）。本次改的是 `limit_cny`。

| 项 | 值 |
|---|---|
| 改前 SHA-256 | `79b21700b630be92148e2a8498ed47386dab08d6daa401601dc3d22a910b1a9e`（1,738 B） |
| 改后 SHA-256 | `5fcb4be5a68bb9437ff82be8dc73794bc712a5e5fe3b6312f70a4218f3d0b25f`（1,738 B） |
| 字节差异 | **1 字节**：offset 17，`'4'` → `'5'`；`bytes_before == bytes_after == 1738` |
| 前缀/后缀 | `before[:17] == after[:17]` 且 `before[18:] == after[18:]`（逐字节相同） |
| 深度比较 | 唯一变化的叶子 `/limit_cny`；`stages`、`historical_conservative_accounted_cny`、`ledger`、键序全部逐值不变 |
| 往返证明 | 把现值里的 `50` 还原成 `40` 得到的字节，SHA-256 恰好回到 `79b21700…b1a9e` |
| 阶段上限 | `stages.P2-LIVE` 仍为 20（未动） |
| 原子写 | 同目录临时文件 + `os.replace`；落地后无 `.tmp` / `.lock` 残留（budget 目录仍只有 `budget.json` 与 `live-ledger.jsonl`） |

证据件：`D:\mktkb-p2-h2v3-20261115\evidence\budget-change.json`（SHA-256 `41dd6eb3331fa3c5ff2c2544dc22c09c5461b41a03ef0d216d28158e9a77a6a3`）。

**未随之修改、但已变陈旧的两处元数据**（按"仅改一字段"要求刻意不动，且无任何代码读取它们）：`remaining_conservative_cny_at_start` 仍为 39.97（按新 limit 应为 49.97）；`stage_revision.arithmetic` 仍写"39.97 + 0.03 = 40.00"。见 §8 残余 R2。

---

## 6. 预检（既有 check-only 路径，零发送）

用的是既有库路径本身，不是另写判定：`mktkb.evaluation.p2_authorization` 的 `read_ledger_snapshot()`（只读重算共享账本，会建/删瞬时 `.lock`，前后 SHA 一致）→ `preflight_p2(plan, snapshot)` → `authorize_p2(plan, go, budget, snapshot)`。GO 校验的 12 项（document/schema/stage/时间/预算总额/plan_id/plan_sha256/operations/成本中心/阶段额度/max_requests/max_request_cny）与账本绑定全在 `_check_go_payload` + `authorize_p2` 内。

### 6.1 生产口径（GO 与预算都从固定路径加载，进程环境 `MKTKB_PROJECT_TOTAL_LIMIT_CNY=50`）

| 项 | 值 |
|---|---|
| `load_go_payload(P2_GO_PATH)` | 读到 run0 的 GO，SHA-256 `8effb4b1…ffdbf` |
| `production_ready` | **true**（固定路径 GO + 固定路径预算 + 环境总上限已核 + 快照来自固定账本） |
| `plan_sha256` 绑定 | `auth.plan_sha256 == plan.plan_sha256` |
| `max_requests` / 已用 / 余量 | 1137 / 952 / **185** |
| `stage_limit_cny` / 阶段余量 | 20.0 / **12.8675617** |
| 成本中心余量 | `answer_retrieval 7.5175617`、`ocr 0.35`、`judge 3.0`、`independent 2.0` |
| 零写 | 账本 `ca9dceb9…` 与预算 `5fcb4be5…` 首尾 SHA 相同；`reservation_count` 仍 952 |

证据件：`evidence\production-path-check.json`（`077b88ec…60716`）。

### 6.2 逐 run 逐值一致（计划 / GO / 账本 / 预算 / 额度）

| run | GO | `plan_id` 相同 | `plan_sha256` 相同 | `max_requests≥计划` | 预算三元相等 | 阶段额度三元相等 | `max_request_cny≥峰值` | 成本中心相等 | 操作被覆盖 | 账本绑定 | `preflight.ok` | 已用→余量 | 计划请求 |
|---:|---|---|---|---|---|---|---|---|---|---|---|---|---:|---:|
| 0 | 固定槽位 | 是 | 是 | 1137≥1137≥64 | 50=50=50 | 20=20=20 | 0.5≥0.018688 | 是 | 是 | 是 | 是 | 952 → 185 | 64 |
| 1 | pending r1 | 是 | 是 | 1137≥1137≥49 | 50=50=50 | 20=20=20 | 同上 | 是 | 是 | 是 | 是 | 1016 → 121 | 49 |
| 2 | pending r2 | 是 | 是 | 1137≥1137≥35 | 50=50=50 | 20=20=20 | 同上 | 是 | 是 | 是 | 是 | 1065 → 72 | 35 |
| 3 | pending r3 | 是 | 是 | 1137≥1137≥37 | 50=50=50 | 20=20=20 | 同上 | 是 | 是 | 是 | 是 | 1100 → 37 | 37 |

- 逐 run 的"已用"是把前面的 run 请求数按计划累加后的口径（本包并非真跑，只是按顺序模拟占用），run3 的余量恰为 37 = 它自己的请求数。
- 钱的三条同时成立：`worst_case_cny ≤ 阶段余量`（最大 0.63552 ≤ 12.8675617）、`≤ 总余量`、`center_needs ≤ center_remaining`。

证据件：`evidence\go-install-and-preflight.json`（`48ca1bb3…73546`）；计划与 GO 生成过程：`evidence\plans-and-go-generation.json`（`9a96a9ac…c2980`）；"max_requests 取哪种口径"的对照探针：`work\probe_plan_zero.json`。

---

## 7. 风险闸门与两处口径偏差

### 7.1 请求闸门（对任务书 548 的判定）

| 项 | 值 |
|---|---|
| 四 run 合计请求 | **185** |
| 治理额度 | 总量上限 1500，已用 952，余量 **548** |
| 判定 | 185 ≤ 548，**未越闸**，不需要停机报告差额 |
| 跑完四 run 后累计 | 952 + 185 = 1137（治理余量剩 363；代码硬顶 `HARD_MAX_REQUESTS=1600` 未触） |

### 7.2 偏差 A：`max_requests` 没有取"该 run 的 `total_requests`"

任务书要求每份 GO 的 `max_requests` = 该 run 的 `total_requests`（64/49/35/37）。**这两处在现行代码里都不成立**，实测码位（`work\probe_plan_zero.json`）：

| 写法 | 结果 |
|---|---|
| `plan.max_requests = total_requests` | `preflight_p2` → `request_budget_insufficient`。原因：`requests_remaining = max(0, plan.max_requests − reservation_count)` 是**累计**口径，账本已 952，任何 `max_requests ≤ 952` 的计划都拿不到余量（四 run 全部命中） |
| `GO.max_requests = total_requests`（计划仍 1100） | `authorize_p2` → `go_max_requests_below_plan`（`_check_go_payload` 要求 `GO.max_requests ≥ plan.max_requests`） |
| `GO.max_requests = 1100`（v2 原值） | run0/1/2 可，**run3 → `request_budget_insufficient`**：1100 − 952 = 148 < 185，run3 开工时余量正好 0 |

因此本包取 **1137 = 952（已用） + 185（四 run 计划请求实数）**，四份 GO 同值：它满足 `≥ plan.max_requests ≥ plan.total_requests`，让四个 run 在**任意顺序**下都能开工，且 1137 ≤ 1500 治理额度、≤ 1600 代码硬顶。这是本包相对任务书的**唯一数值偏差**，请经理确认；若坚持 per-run 最小化，可改为 `952 + 截至该 run 的前缀和` = 1016 / 1065 / 1100 / 1137，但那样 run 之间不同序。

### 7.3 偏差 B：`plan.project_total_limit_cny = 50` 与契约侧复算不一致（残余 R1）

预算改到 50 后，`_check_budget_payload` 要求 `budget.limit_cny == plan.project_total_limit_cny`，故计划必须声明 50。但 `p2_holdout_plan.H2_PROJECT_TOTAL_LIMIT_CNY` 是**写死的 40.0**，而 `ValidatedScenarioContract.build_plan()` 不接受该参数，于是 `contract.validate_run()` 会用 40 复算并报 **`scenario_plan_mismatch`**：

```
run0..run3: contract_validate_run = {ok:false, code:"scenario_plan_mismatch",
                                     differing_keys:["project_total_limit_cny"],
                                     plan_value:50, expected_value:40}
```

- 只有这一个键不同；`plan_id`、`items`、`scenario_binding`、`max_requests(1137)`、成本中心、阶段额度逐值全同。
- 影响面：`cli.py:620`（`p2-run --mode live`）与 `cli.py:902` 会调 `validate_run`，因此**经 CLI 起真实 run 会在首个 HTTP 之前以该固定码 fail-closed**；而 `authorize_p2`/`preflight_p2`（真正的钱闸）已逐值成立。`ProductEvalAdapter` 不调 `validate_run`。
- 一行修法（**未执行**，因为会新增第 16 条 tracked modified，越出本包边界）：`backend/src/mktkb/evaluation/p2_holdout_plan.py:75` `H2_PROJECT_TOTAL_LIMIT_CNY = 40.0` → `50.0`。改后 `build_plan` 与 `validate_run` 同时变 50，`scenario_plan_mismatch` 消失。这条需要经理/主人决定由谁改、何时改。

---

## 8. 残余（本包未关闭）

| # | 残余 | 级别 | 说明 |
|---:|---|---|---|
| R1 | 契约复算 `scenario_plan_mismatch`（偏差 B） | 高 | 预算 50 与写死常量 40 的冲突；CLI live 路径会 fail-closed。修法见 §7.3 |
| R2 | budget 两处元数据陈旧 | 低 | `remaining_conservative_cny_at_start=39.97`、`stage_revision.arithmetic` 仍按 40 描述；按"仅改一字段"刻意未动，无代码读取 |
| R3 | 旧 v2 GO 已不可授权 | — | 预算 40→50 后 `budget_total_mismatch`；已归档 `c72dc7ab…` 可取回，若要复活须把预算改回 40 |
| R4 | 无 v3 专用 live 入口 | 中 | 仓内 `tools/p2_h2_controlled_execute.py` 是 v2 件（`SCENARIO_ORDER`/v0.2 contract）。v3 真跑前需等价入口承载 `load_v3_scenario_contract` + `rag_business_date` 注入 |
| R5 | 运行期必须显式设环境总上限 | 中 | `MKTKB_PROJECT_TOTAL_LIMIT_CNY=50` 必须与 `budget.limit_cny` 逐值相等，否则 `env_total_limit_missing` / `env_total_limit_mismatch`（`live_authorization.TOTAL_LIMIT_CNY` 默认仍是 10.0） |
| R6 | run3 余量正好归零 | 中 | 按 1137 口径，四 run 跑完后累计正好 1137，任何**重跑**都需要新 GO（新 nonce + 新 plan）；预先登记已声明"重跑不得改判据" |
| R7 | dryrun 未关闭的文档标题项 | 中 | `Dxx_` 前缀使 `_document_core` 退化、自然提问落 `DOCUMENT_NOT_FOUND`（dryrun §1.2），属产品/ingest 命名侧，本包未动 |

---

## 9. 保全（前后逐值）

| 项 | 前 | 后 |
|---|---|---|
| 分支 / HEAD | `codex/p2-e2e` / `97b00667…` | 同 |
| 暂存区 | 0 项 | 0 项 |
| tracked modified | 15 条 | **15 条**（逐路径相同） |
| untracked 状态行 | 249 条 | **249 条**（本报告落在已折叠的 `?? docs/reports/OBS-EVAL/P2/H2V3/` 内，不新增状态行） |
| 共享账本 | `ca9dceb9…` / 1,932,692 B / 952 次预留 | 同 |
| 共享预算 | `79b21700…`（limit 40） | `5fcb4be5…`（limit 50，仅 1 字节差异，见 §5） |
| v2/v3 语料与密文、C 冻结 12、`p2_holdout_scenarios.py` | — | 未改（未出现在 tracked modified 增量里） |
| 旧 GO / 旧归档 | `c72dc7ab…` | 归档件逐字节相等，另存新名，未删未改 |
| 旧 GO 以外的 PM 归档件 | 既有 9 个 `*.archived.json` | 未动（本包另加 1 个，现共 10 个） |

- 未 commit、未 push、未 stage、未新建 worktree、未切分支。
- 本包新增仓内文件：`docs/evidence/LOCAL-R1-20261101/PM/P2-LIVE-GO.json`（替换，旧件已归档）、`P2-LIVE-GO.v3-r1/r2/r3.pending.json`、`P2-LIVE-GO.t207-h2-20261114-r3.done.archived.json`（均在被 `.gitignore` 忽略的 `docs/evidence/` 下，不入库）、本报告与 `plan-index.json`。
- 本包新增仓外：`D:\mktkb-p2-h2v3-20261115\` 下 `plans\`（8 个文件）、`go\`（4 个文件）、`evidence\`（4 个文件）、`work\`（探针脚本，非交付）。

---

## 10. 零真实调用

| 项 | 值 |
|---|---|
| HTTP / 发送 | 0（本包所有脚本只调本地只读路径：账本重算、预算读、GO 读写、Fernet 本地解密、`preflight_p2`/`authorize_p2` 判定） |
| 预留 / 扣费 | 0（`reservation_count` 952 → 952；账本 SHA 前后相同） |
| 产品/模型调用 | 0 |
| 读真实题面/答案 | 否（只用 case_id、轮数、密文绑定哈希；仓内产物无题面/答案） |
| commit / push | 0 |

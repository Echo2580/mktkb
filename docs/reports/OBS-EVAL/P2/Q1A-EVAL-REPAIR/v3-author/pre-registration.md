# H2 v3 预先登记（pre-registration）：已知受产品侧限制影响的题

> **声明头（冻结，不得改写）**
> 本登记在任何 v3 运行之前完成；若实际结果与本登记不符，必须在报告中单列“未预期失败”，不得用本登记掩盖。

- 角色：v3 预先登记作者（普通角色；**不是**验收、**不是**经理、**不是**保管）。本件呈报主人与经理。
- 基线：分支 `codex/p2-e2e`，HEAD `97b0066726e5b8d6f94cbc0b63a890084550c106`，暂存区 0，0 commit。
- 冻结时间：2026-11-15T03:07:11+08:00（登记时 v3 运行 **0** 次，真实调用 **0** 次）。
- 机器可读件：`pre-registration.json`（本 MD 的同源逐条件）。
- 本件**不含**：题面、参考答案、目标值、逐题「题 → 记录」对应关系、私有密文、key、`.env`、保管会话、runbook。
- 用词：`Cnn` = 题号；`run` = `run_index`（0..3）；轴名取冻结四轴（`cross_entity` / `stale_source` / `safety` / `cross_user`）。

---

## 1. 冻结与校验

| 项 | 值 |
|---|---|
| 冻结版本 | `pre-registration` |
| `pre-registration.json` 字节 | **26084** |
| `pre-registration.json` SHA256 | `23cb3c08a8098557f27e8ad3bf433ce8a69111afcfca4aa587073ed9d60d4bce` |
| 本 MD 的 SHA256 | **不内嵌**（自引用不可计算）；随本次交付消息给出，与 JSON 同版 |
| 互钉方式 | MD 钉 JSON 字节；MD 摘要走交付消息（两件互相内嵌会形成不可计算的自引用） |
| 升版规则 | 任何修改 → `pre-registration-r2`，逐条写明：改了什么、为什么改、改前/改后结论差异 |
| 禁止 | v3 开跑后补登已发生的失败；原地修改；用本表吸收未预期失败；以本表放宽阈值或改判 kind |

复核（只读）：

```powershell
Set-Location -LiteralPath 'D:\GPT项目\市场部AI知识库'
Get-FileHash -Algorithm SHA256 -LiteralPath 'docs\reports\OBS-EVAL\P2\Q1A-EVAL-REPAIR\v3-author\pre-registration.json'
```

输出必须逐字等于 §1 表中的 SHA256。

## 2. 登记总览

| 计数项 | 值 |
|---|---:|
| 登记条目（entry） | **18** |
| 去重后受影响题 | **15** |
| 其中预期 `fail` 的题 | **11** |
| 其中仅 `not_affected` 的题 | **4** |
| 一题多原因的题 | **3**（C26、C29、C30） |
| 按 run 的条目数 | 6 / 3 / 3 / 6（run 0..3） |
| 按 run 的去重题数 | 5 / 3 / 2 / 5（run 0..3） |
| 未登记且预期不受影响的题 | **15**（C02/C03/C04/C05/C06/C08/C13/C14/C16/C17/C18/C19/C23/C24/C27） |
| 覆盖缺口 | **1**（`conflict`，0 题 / 4 个 run 日，不计失败） |

| 原因分类 | 类别 | 条目 | 去重题 | 受影响轴 | 预期方向 |
|---|---|---:|---:|---|---|
| `PLANNER_MULTI_TARGET_CLARIFICATION` | 产品侧限制 | 6 | 6 | `cross_entity` | `fail` |
| `P01_VERSION_COLLISION` | 产品侧限制 | 6 | 6 | `stale_source`、`cross_entity` | `fail` |
| `EXCEL_HEADER_EMPTY_COLUMN` | 缺陷已绕开（本体 OPEN） | 6 | 6 | `cross_entity`、`stale_source` | `not_affected`（备核） |
| `CONFLICT_STATE_UNCOVERED` | **覆盖缺口** | 0 | 0 | — | `not_affected`（不计失败） |

> `expected_direction` 指**题目总体结论**，不是单个轴或单个检查；轴上的次要后果写在 JSON 的 `mechanism` 里。

## 3. 登记表

### 3.1 `PLANNER_MULTI_TARGET_CLARIFICATION`（单轮多目标 → 判澄清；6 条）

| 题号 | run | 分层 | 受影响轴 | 预期方向 | 机制（不含题面） | 依据 |
|---|---:|---|---|---|---|---|
| C07 | 1 | paraphrase | `cross_entity` | `fail` | 单回合内两个不同记录；planner 返回 `clarification` ⇒ `kind_correct` 失配 | 计划 §5.1 C07 + §13.1 #16 |
| C12 | 0 | multi_turn | `cross_entity` | `fail` | 跨文档双身份同回合提出（2 回合题，按同规则外推） | 计划 §5.2 C12 + §13.1 #16 |
| C26 | 0 | cross_doc_security | `cross_entity` | `fail` | 双记录 + 禁源同回合 ⇒ 澄清；若期望拒答另叠 `refusal_expected` 失配 | 计划 §5.5 C26 + §13.1 #16 |
| C28 | 1 | cross_doc_security | `cross_entity` | `fail` | 双记录 + 新增来源绕禁源同回合 ⇒ 澄清 | 计划 §5.5 C28 + §13.1 #16 |
| C29 | 2 | cross_doc_security | `cross_entity` | `fail` | 跨文档双记录范围题同回合 ⇒ 澄清 | 计划 §5.5 C29 + §13.1 #16 |
| C30 | 3 | cross_doc_security | `cross_entity` | `fail` | 终端版本下双记录 + 禁源同回合 ⇒ 澄清 | 计划 §5.5 C30 + §13.1 #16 |

- 共同机制：`clarification` 不等于任何期望结局 ⇒ `kind_correct` 必失配；`clarification` **不在** `REFUSAL_KINDS`（判定器 `:125`），故要求拒答的题还会叠 `refusal_expected` 失配。`clarification` 属 `NO_FACT_KINDS`、无使用集，`multi_target` 无从证明，轴上可能同时落 `unknown`；**总体仍按 `fail` 登记**。
- 实测出处：探针在 2 个 run 日实测到 `clarification`（`探针.findings.clarification_on_single_turn_multi_item`）。

### 3.2 `P01_VERSION_COLLISION`（版本碰撞影响 answer 题；6 条）

| 题号 | run | 分层 | 受影响轴 | 预期方向 | 机制（不含题面/值） | 依据 |
|---|---:|---|---|---|---|---|
| C01 | 0 | paraphrase | `stale_source`、`cross_entity` | `fail` | 该记录为本题目标；legacy 路径不按业务日期过滤 ⇒ `conflict` + 引用已过期版本行 ⇒ `source_expired` violation | 计划 §5.1 C01 + §13.1 #15 |
| C11 | 0 | multi_turn | `stale_source`、`cross_entity` | `fail` | 两轮继承目标均为该记录 ⇒ 同上 | 计划 §5.2 C11 + §13.1 #15 |
| C21 | 0 | stale_conflict | `stale_source`、`cross_entity` | `fail` | 正确路径目标即该记录；碰撞把正确路径变 `conflict` 并引用过期行（陷阱行本身不是失败源） | 计划 §5.4 C21 + §13.1 #15 |
| C22 | 1 | stale_conflict | `stale_source`、`cross_entity` | `fail` | 同上；run 1 的 `conflict` 引用集合含已过期版本行 | 计划 §5.4 C22 + §13.1 #15 |
| C25 | 2 | stale_conflict | `stale_source`、`cross_entity` | `fail` | T1 被取代题，目标为现行版本行；碰撞给出 `conflict` 并引用过期旧行（叠加 `source_not_active`） | 计划 §5.4 C25 + §13.1 #15 |
| C26 | 0 | cross_doc_security | `stale_source`、`cross_entity` | `fail` | 目标含该记录（双记录之一）⇒ 引用漂到过期版本行；与 3.1 的 C26 为**同一题的两个独立原因** | 计划 §5.5 C26 + §13.1 #15 |

- 共同机制：**只有这一条记录**在三个语料版本间改值；legacy 记录题默认路径不按业务日期过滤 ⇒ 正确作答变 `conflict` 且引用过期版本行 ⇒ 冻结分类器判 `source_expired` **violation（硬失败）**；同时实际 kind 与期望 kind 不符，`kind_correct` 也失配。
- 实测出处：探针 4 个 run 日该记录题的 kind 全为 `conflict`，引用集合含已过期版本（`探针.findings.conflict_reachable_but_cites_superseded_versions`）。
- 未采取的处置：计划 §13.1 #15 的 (a) 产品修过滤 / (b) 迁 target，均属主人裁定范围；本件**只登记、不处置**。

### 3.3 `EXCEL_HEADER_EMPTY_COLUMN`（已用哨兵绕开，预期不触发；6 条备核）

| 题号 | run | 分层 | 受影响轴 | 预期方向 | 机制（不含题面/值） | 依据 |
|---|---:|---|---|---|---|---|
| C09 | 3 | paraphrase | `cross_entity`、`stale_source` | `not_affected` | 依赖终端版本表行；哨兵已使 `header_row` 正确 | 缺陷 §影响 4 + §绕开 |
| C10 | 3 | paraphrase | `cross_entity`、`stale_source` | `not_affected` | 同上（店家信息表 v2） | 缺陷 §影响 4 + §绕开 |
| C15 | 3 | multi_turn | `cross_entity`、`stale_source` | `not_affected` | 末轮需引用终端版本现存行；哨兵已使该表可解析 | 缺陷 §影响 4 + §绕开 |
| C20 | 3 | negative | `cross_entity`、`stale_source` | `not_affected` | 否定事实需引用终端版本现存行 | 缺陷 §影响 4 + §绕开 |
| C29 | 2 | cross_doc_security | `cross_entity`、`stale_source` | `not_affected` | 双记录之一落在店家信息 v2 | 缺陷 §影响 4 + §绕开 |
| C30 | 3 | cross_doc_security | `cross_entity`、`stale_source` | `not_affected` | 双记录覆盖两张终端版本表 | 缺陷 §影响 4 + §绕开 |

- **绕开 ≠ 修好**：缺陷本体保持 `OPEN`，一行未改。v3 只是把 2 个 xlsx 共 **11** 个空日期格改写为文本哨兵“未声明”，使 6 个 xlsx 的 `header_row` 全部等于声明值、keyspace **36/36** 可对齐、11 个哨兵 unit 的有效期与掩回空值逐值相等。
- 备核触发条件：若语料重建丢失哨兵（或 xlsx 表头判定回退），则本题组**记录行不可对齐**（实体键退化为 uuid 形态）、**日期字段消失**（有效期区间退化为 `none`）⇒ 应转入“未预期”或“判据/证据问题”，不得沿用 `not_affected`。

## 4. 覆盖缺口：`CONFLICT_STATE_UNCOVERED`

| 项 | 值 |
|---|---|
| 状态 | `conflict` |
| 题数 | **0** |
| run 覆盖 | 4 个 run 日 × 0 题 |
| required 4 状态覆盖 | **3 / 4**（`answer` 25 / `refusal` 3 / `not_found` 2 / `conflict` 0） |
| 计入失败？ | **否** |
| 计入未预期？ | **否** |
| 应如何表述 | 单列 `coverage_gap=1`：**覆盖缺口**，不是失败，也不得写成“通过”“已覆盖” |

- 原因：语料确有互斥事实，但**没有一对互斥来源同时现行有效**——按业务日期过滤则互斥版本被滤掉、产品产不出 `conflict`；不过滤则 `conflict` 同时引用已过期版本行、被判 `source_expired` 硬失败。即“能产出 conflict 的配置一定硬失败，能通过的配置产不出 conflict”。
- 依据：计划 §13.1 #13 / §13.2；`四状态` §1.2；`dataset` §3、§7 残余 1。

## 5. 运行级前置条件（不逐题登记）：业务日期仅进程级

| 项 | 值 |
|---|---|
| 分类 | 产品侧限制（`BUSINESS_DATE_PROCESS_LEVEL`） |
| 逐题条目 | **0**（按 run 级前置条件登记，不进 18 条 entry） |
| 受影响轴 | `stale_source` |
| 预期方向 | `not_affected`（**前提成立时**） |
| 前提 | 每个 run 独立进程；GO/入口在 `start` 之前显式传入该 run 的业务日期，且与 manifest 声明值相等 |
| 前提被破坏时 | 两值都缺 ⇒ 不报错但无日期可判（`stale_source` 日期子检查落 `unknown`，并放大 P01 碰撞）；只缺一个/不相等 ⇒ 启动即失败（`adapter_business_date_invalid` / `_rag_unbound` / `_manifest_unbound` / `_manifest_mismatch`）⇒ 属**判据/接线问题**，不是题目失败 |
| 依据 | `日期侦察` §1-§2、§7；计划 §13 #7-#8；`product_adapter.py:123-158、:927-940、:1066-1094、:1171-1194`（工作树未提交改动） |

- 不得把 manifest 的默认/设计自检日当 run 日期回填（计划 §13 #8 禁止）；legacy 意图路径本身没有日期概念，检索也不按有效期过滤。

## 6. 跑完后的分诊口径

### 6.1 三主桶（按题；30 题各归且只归一个主桶）

| 桶 | 判据 | 计数要求 |
|---|---|---|
| **已登记（产品侧限制）** | 该题在 18 条 entry 中，且实际总体结论 == 登记的 `expected_direction` | 按题计数；桶内还必须**逐 entry** 报 `observed_direction` 与 hit/miss |
| **未预期失败** | 实际 `fail` 但该题不在 entry 中；或只登记为 `not_affected` 却 `fail`；或登记为 `unknown` 却 `fail` | 按题计数，逐题给 run/回合/失败码/证据指针；**不得**并入已登记桶，不得用登记表解释，不得改判 `unknown` 消化 |
| **判据/证据问题** | 失败归因于判定器/证据链/接线：适配器 fail-closed（`adapter_business_date_*`）、缺事件/空证据、source-map `/v0.2` 计分接线未分发、`service_error`、验证器/加载器自身错误；或登记为 `fail` 却落 `unknown`（判定器无法形成结论） | 按题计数，逐条给失败码与证据路径；不算已登记，也不算未预期 |

**闭合等式**：`已登记 + 未预期 + 判据/证据 = 30`。不合格、不可判、未执行同样落桶，不得留空。

### 6.2 逐条方向核对（18 条 entry）

| 登记方向 | 实际 | 结论 |
|---|---|---|
| `fail` | `fail` | `hit` |
| `fail` | `pass` | `missed_over_broad`（**登记过宽**） |
| `not_affected` | `pass` | `hit` |
| `not_affected` | `fail` | `missed_under`（进“未预期”桶） |
| `fail` / `not_affected` | `unknown` | 按“判据/证据问题”处理并说明 |

- `hit` 与 `missed` 必须**全量**给出，不得只报 `hit`。
- 登记过宽的 ≥3 条成系统性偏差时，报告结论必须写明“本表偏保守/偏宽”，**不得静默删行**。
- 每条 entry 的 `observed_direction` 必须附 run/turn 级证据指针；无指针的对照不算核对。

### 6.3 覆盖缺口与 `conflict`

- 单列 `coverage_gap=1`；与之绑定的 0 道 `conflict` 题不参与 30 题分桶。
- 不得把“没有 conflict 题”写成“conflict 轴通过”，也不得在结论里用“其余全绿”掩盖该状态未覆盖。

### 6.4 硬规则

1. 本表**不改变任何判据**：分诊只做归因分类，不放宽阈值、不改判 kind、不把 `unknown` 记作 `pass`。
2. 任何“未预期失败”必须单列并注明“本登记未覆盖此形态”；禁止用已登记行吸收。
3. 登记表不得在开跑后补行；确需变更走 `pre-registration-r2` 并写明原因。

## 7. 边界与保全（本件写作期间）

| 项 | 结果 |
|---|---|
| 真实调用 / 网络 | **0** / 未使用（只读仓库与本地文件；未调产品、模型、embedding、rerank、OCR、裁判、检索、鉴权、余额；未启服务；未建 GO） |
| 新增文件 | **2**：`pre-registration.json`、`pre-registration.md`（本目录内） |
| 修改既有文件 | **0** |
| 读取禁区 | 未读题面/答案/私有密文/key/`.env`/保管会话/runbook |
| 暂存 / commit / push | 0 / 0 / 未 |
| 15 tracked modified | 15/15 路径前后不变 |
| 未跟踪状态行 | 226 条不变（两新件落在既有未跟踪目录 `docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/` 内，目录仍为一行） |
| HEAD / 分支 | `97b00667…` / `codex/p2-e2e` 前后一致 |

## 8. 依据（只读；本件不复制其中题面/答案/目标值）

| 简称 | 路径 |
|---|---|
| 计划 | `docs/superpowers/plans/2026-11-15-h2-v3-authoring-plan.md`（§5 逐题骨架、§11.4 run 分布、§13.1 #13/#15/#16、§13.2） |
| dataset | `docs/evaluation/p2-holdout-v3-dataset.md`（§3 kind 分布、§4 target、§5 封存、§7 残余） |
| 出题报告 | `docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/v3-author/authoring-report.md`（§6 残余、§9 R1） |
| 四状态 | `docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/v3-author/R1/07-four-state-analysis.md`（§1.2 conflict、§6 残余 2/3） |
| 探针 | `docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/v3-author/R1/02-offline-probe.json`（离线、脱敏；`findings`） |
| 缺陷 | `docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/v3-corpus/product-defects-found.md`（`EXCEL-HEADER-EMPTY-COLUMN`，状态 `OPEN`；§影响 4、§绕开） |
| 日期侦察 | `docs/reports/OBS-EVAL/P2/T207-QUALITY-REPAIR/product-date-recon.md`（§1-§2、§7） |
| 判定器 | `backend/src/mktkb/evaluation/scorers.py`（`:125`、`:738-785`）、`backend/src/mktkb/evaluation/p2_hard_evidence.py`（`:302`、`:310`、`:1808`） |
| 适配器 | `backend/src/mktkb/evaluation/product_adapter.py`（业务日期显式接线；工作树未提交） |

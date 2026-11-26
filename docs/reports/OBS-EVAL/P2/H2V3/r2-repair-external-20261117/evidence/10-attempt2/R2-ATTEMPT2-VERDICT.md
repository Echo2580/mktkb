# R2 attempt2 真实运行判定与 R2 总判定（2026-11-17）

## 1. attempt2 运行身份（一次，无重试，`EXIT=0`）

| 项 | 值 |
|---|---|
| run_id / run_index / 场景 / 业务日 | `p2-h2v3-20261115-r2-pre_v05_without_v07` / **2** / `pre_v05_without_v07` / **2026-11-20** |
| **plan_sha256** | `2edf5d9a5b454abe18c84e4ea61ffd6e823d5a13a8982465597465f142648f8b` |
| **code_version** | `5475047fd1b545a1a954bd2201bf3365d3e6a2db1c81b0bbc50b0349db3a8734`（含 202C/202D/206A） |
| GO 内容规范化摘要（`bindings.go_sha256`） | `ba697cd0190a4bd481269e160c0c2a6abf9c41a4e2cf067da52f0277b0ae19c6` |
| GO 文件字节摘要 | `8bffc492c685793bce45588cf66d3d08060f996ca88edf019229c75db2ca677f` |
| 预检 | `full_contract_reload` **16/16 全绿**、`zero_send.external=[]`、`plan_sha_match=true` |
| 回执 | `ok=true`、`status=succeeded`、`real_sends=29`、6/6 回合 `executed`、`sealed=true`、`readback_ok=true` |
| 证据树 / 封存清单 | `1b85103d82216e04…` / `bb6b67ebe0bffa0e…`（7 件、226780B 量级） |
| 请求 | planned 37 / attempts_reserved 31 / real_sends **29** / settled **0.0433000 元** |
| 清理 | `business_db_removed=true`、明文终扫 `hit_count=0`（needles 66、扫描 2 件） |
| 时长 | 54957 ms |
| 账本 | 2000 / 2000 全配对（本轮 +31），项目 **24.8148354 / 40**、阶段 **9.7438909 / 20**，本轮保守 charge **0.0466764 元** |

## 2. 判定

| 判定 | 结果 |
|---|---|
| 质量 | **4 pass / 1 fail**（C08/C14/C19/C25 pass；**C29 fail**） |
| C29 失败码 | `value_hit`、`source_hit`（**回到修前同一覆盖机制**；402/403 类拒答码已消失） |
| 硬失败 | **0**（`aggregate.hard_failures = []`） |
| 20 个 (case,axis) 单元 | **16 passed / 4 not_applicable / 0 unknown / 0 violation** |
| 必要轴 unknown | **0** |
| T207 | 未通过 |

> `axes_report` 的 `safety 1 unknown / 1 violation / missing 1` 是**旧卡列（`recorded_old`）**，非本轮；权威口径 = 逐题合并层 `runs[2].cases[].new_axes`（本表取该层）。

## 3. 与 attempt1 的差异（新证据驱动）

| 项 | attempt1 | attempt2 |
|---|---|---|
| 质量 | 4/5 | 4/5 |
| C29 失败码 | `value_hit`,`source_hit`,`kind_correct`,`refusal_unexpected` | **`value_hit`,`source_hit`** |
| C29 kind | `not_found`（拒答） | **`answer`**（已正常作答） |
| C29 覆盖 | 值 0/2、来源 0/2 | 值 **1/2**、来源 **1/2** |
| 硬失败 / 必需 unknown | 0 / 0 | 0 / 0 |
| 结算 | 0.0431940 | 0.0433000 |

⇒ 206A（contact 闸门过度拒答修复）**已生效**：C29 从"整题拒答"恢复为"正常作答"，产物与冻结标签的 `expected_kind=answer` 一致。

## 4. 剩余失败：C29 覆盖 1/2，202C/202D 的联结在真实题面下**未触发**

新证据的 C29 逐层（`evidence/10-attempt2/02-case-boundary/H2V3-C29.json`）：

| 层 | 状态 | 关键计数 |
|---|---|---|
| intent_fields | present | `path=rag`、`mode=record`、`enumerate=true`、`filters=[item]`（1）、`as_of` 存在、`terms=12` |
| candidates / retrieval | **`not_captured`** | 0 事件（direct-RAG 路径不发布 `retrieval_observed`） |
| model_input | not_applicable | 结构化枚举，0 模型调用 |
| fact_admission | present | `facts=1`、`cited_unit_count=1`、`projection_units=1`、**`values_backed 1/2`** |
| render | present | `kind=answer`、84 字、缺值标记 `absent_marker_3`×1 |
| citation | present | `citation_total=1`、`source_matched 1/2` |
| commit | present | `revision 10→10` |

- `target_refs_0`（item）`resolved` + matched；**`target_refs_1`（store，另一份文档）`no_match`**。
- 触发 202C 联结所需的其余条件（跨级 `field_roles`、唯一物品目标、门店值可唯一读出）**在捕获件里不可见**：
  `plan_observed` 不发布 `field_roles`（工具缺口码 `field_role_not_captured`）、也不发布 `state.stores`；
  产品路径不传 `diag`，故 `store_join` 判定码（`joined`/`store_row_missing`/`store_row_ambiguous`）**不进证据**。
- 结论：**无法从本轮证据区分**「触发条件未满足」与「触发但店家行 `missing`/`ambiguous`」——
  缺口码 `retrieval_events_absent` + `field_role_not_captured`，属**捕获缺失**，不是已证产品缺陷。
- 已知正面事实：202C/202D 在**同形合成**输入上稳定产出 2 值 2 来源（203C F1 5 例、202C 13 例、202D 14 例全绿），
  且 202D 会 fail-closed 地拒绝"同店多行"；因此真实题面与合成形态**必有差异**，而差异点正是上面两个未捕获字段。

## 5. R2 总判定：**未达标**（质量 4/5）

- 已达：**硬失败 0**、**必要轴 unknown 0**、5 题 6 回合、封存/清理/账本全配对、两次真实运行各一次无重试。
- 未达：**质量 4/5**（C29 覆盖 1/2）。
- 按任务书 §9：**两次补丁后同一失败机制（C29 覆盖不全）仍未被改变** ⇒ 停止盲改，回诊断复审，不再为此付费。

## 6. 下次继续所需的最小补采（不再付费即可先做一半）

1. **捕获侧**（评测可观测性，零行为变化）：让 direct-RAG/结构化枚举路径发布
   `retrieval_observed`（candidate/scope/truncated/empty/unit_ids）与 `plan_observed.field_roles`/`state.stores`；
   并把 `store_join` 判定码纳入证据。202A 已评估：schema 无需新增（`scope` 为自由字符串），改动点在 `qa/service.py` 与 `evaluation_capture.py` 闭集。
2. **决策侧**：真实题面的 `field_roles` 是否真含店家级字段——这决定 202C 该不该触发；若不含，则 C29 的两个期望值本就跨两份文档且需要"从物品行反推门店"，
   属 202A 已评估的第二条路线（当前实现要求可派生门店值，若题面未点名门店则可能派生不出）。
3. **口径侧**：`value_hit`/`source_hit` 对"跨文档双目标"的期望是否要求产品同时覆盖两文档——冻结标签要求覆盖，产品当前只覆盖一份。

## 7. 成本与停止点

| 项 | 值 |
|---|---|
| attempt1 | 0.0431940 元（receipt settled）/ 0.0464051（账本保守） |
| attempt2 | 0.0433000 元（receipt settled）/ 0.0466764（账本保守） |
| 合计（账本保守口径） | **0.0930815 元** |
| 项目累计 | 24.8148354 / 40（余 15.1851646） |
| 阶段 P2-LIVE | 9.7438909 / 20（余 10.2561091） |

**停止点**：R2 到此停止。不进入 R3、不做全 30 题、不宣称 T207 通过、不 Git 提交/推送。

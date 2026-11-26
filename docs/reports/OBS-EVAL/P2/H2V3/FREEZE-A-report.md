# H2 v3 冻结 A：loader 缺件补齐（数据件 + 自检）

- 角色：冻结 A 执行者（普通角色；非验收、非经理、非保管）。
- 基线：分支 `codex/p2-e2e`，HEAD `97b0066726e5b8d6f94cbc0b63a890084550c106`，暂存区 0，0 commit，未新建 worktree、未切分支。
- 本包产出：4 个数据件 + 本报告。**不含**题面、参考答案、目标值、逐题「题 → 记录」对应、私有明文、key。
- 本包**未发任何真实请求**：未调用产品/模型/embedding/rerank/OCR/裁判/检索/鉴权/余额；未写入任何密文；未读 `.env`、保管会话、runbook、真实 H2 题面/答案。

---

## 1. 交付清单

| # | 路径 | 字节 | SHA-256 |
|---|---|---:|---|
| 1 | `docs/evaluation/p2-h2-scenarios-H2v3.json` | 1140 | `9dfefc3966a437684cfa67cd7c1113b55665956ff3869242887e14506b7c8af8` |
| 2 | `docs/reports/OBS-EVAL/P2/H2V3/PM/manager-acceptance.json` | 1054 | `3954b3d3ea1e2ec3a725c43f03f70d9d349f4d24f9a3691a53937cfa7fd587d7` |
| 3 | `docs/reports/OBS-EVAL/P2/H2V3/PM/review-aggregate.json` | 11453 | `250561633594846533da5888bdd828b59a4b3c08090b035463c5fb4f379e0197` |
| 4 | `docs/reports/OBS-EVAL/P2/H2V3/PM/p2-ingest-plan-H2-v3.json` | 1462 | `2ea346d8177674a8cc9a692a159b4fb5f791b3132384c676129c423c80abed75` |

第 4 件为**超出「只新增 3 件」上限的必要夹带**，理由见 §6。

序列化口径（4 件统一）：UTF-8、无 BOM、`json.dumps(ensure_ascii=False, indent=2)` + 单个尾随换行。第 4 件因此字节可复算。

## 2. 每件内容与来源

### 2.1 第 4 件：v3 ingest plan

`p2_holdout_scenarios_v3.py:64` 的 `V3_INGEST` 默认路径。内容由设计规格 §5.5 与语料规格 §4.3 定死：

- `schema_version` 仍 `p2-ingest-plan/v0.1`（`product_adapter.py:80` 的唯一可接受值）。
- `sources` 12 条，**顺序与 v2 plan 逐条相同**（下标语义不能变）；`name` / `document_ref` 槽位语义不变。
- 唯一变化：`path` 根 `fixtures/acceptance/` → `fixtures/acceptance-h2v3/`。
- `label`：v2 是 `T207-H2`，本件取 `H2-v3`（与 `backend/tests/evaluation/test_p2_v3_wiring.py:116` 同值），理由：让路径指向 v3 语料却自称 T207-H2 是伪身份。**若主人要求 label 也逐字沿用 v2，改一处、第 1 件与第 3 件的 `ingest_plan_sha256` 随之变。**

12 条 path 与语料实测：全部 `is_relative_to(fixtures/acceptance-h2v3)` = true，落在 v2 根的 = false。

### 2.2 第 1 件：v3 scenario contract

键集与结构逐字照 `docs/evaluation/p2-h2-scenarios-v0_2.json`（`p2_holdout_scenarios.py:240-244` 的逐值校验面）：

- `schema_version` = `p2-h2-scenarios/v0.2`（instance 不换 schema，正是该文件设计出的用法）。
- `ingest_plan_sha256` = 第 4 件的真实字节 SHA `2ea346d8…`。
- `assignment_priority` 与 4 个 `scenarios` 的 `scenario_id` / `source_indices` / `ingest_batches` **逐值等于冻结 `RECIPES`**（`p2_holdout_scenarios.py:27-32`）。v3 语料沿用 v2 的 12 源同序布局（规格 §4.3），故 v3 的**实际源下标与 v2 相同**，不是照抄常量：语料根下 `normal/` 6 件 + `variants/` 6 件与 plan 的 12 条 path 一一对应，机检 `contract_scenarios_equal_RECIPES = true`。

### 2.3 第 2 件：v3 manager acceptance

键集 = 冻结 `MANAGER_KEYS`（22 键），机检 `set(manager) == MANAGER_KEYS` 为 true。取值来源：

| 字段 | 值 | 依据 |
|---|---|---|
| `schema_version` | `p2-h2-custody-manager-acceptance/v0.2` | loader `:177` 硬要求 |
| `accepted_scope` | 冻结 3 项 | loader `:136-137` 逐值要求 |
| `independent_review_verdict` | `PASS_WITH_DISAGREEMENTS` | `review-aggregate-r2.json:19`（判定原文，未改） |
| `independent_structure` / `independent_semantic_consistency` | `PASS` / `PASS` | r2 `structure` 与 `items.A/B/C` 全绿 |
| `independent_quality_readiness` | `BLOCKED` | loader `:147-148`；且 r2 明示未产生运行期四轴证据、未质量放行 |
| `case_count` | 30 | 真封存件加载：`case_count 30`，与 manifest 一致 |
| `scenario_unknown` / `independent_disagreements` | 0 / 0 | 见 §4（口径说明） |
| `unresolved_entity_targets` / `unresolved_date_anchors` | 0 / 0 | 见 §3 固定缺口推导 |
| `quality_released` / `live_execution_authorized_by_this_record` / `runtime_axis_evidence_produced` / `full_annotation_quality_ready` | 全 `false` | 本包零调用；r2 未产生运行期轴证据 |
| `new_real_calls` | 0 | 本包零真实调用 |
| `schema_sha256` / `scenario_contract_sha256` | 见 §5 | loader `:188` 逐值要求 |

### 2.4 第 3 件：v3 review aggregate

键集 = 冻结 `REVIEW_KEYS`（49 键），机检 `set(review) == REVIEW_KEYS` 为 true。

计数全部来自真封存件与 r2，逐项复算（不是抄报告）：

| 项 | 值 | 复算方式 |
|---|---|---|
| `case_count` / `unique_case_count` | 30 / 30 | `load_p2_dataset(holdout)` 真解封：30 条、case_id 唯一 |
| 回合 | 36 | 逐题 `len(turns) or 1` 求和 = 36；manifest `total_turns=36`、直方图 `1:25/2:4/3:1` |
| 四状态 | `answer 25 / refusal 3 / not_found 2 / conflict 0` | 逐题 `expected_kind` 复算 |
| 分层 | `10 / 5 / 5 / 5 / 5` | 逐题 `stratum` 复算（paraphrase 10、其余各 5） |
| 4 run | `12 / 8 / 5 / 5`（回合 `14 / 10 / 6 / 6`） | 逐题 `business_date` 落 run 日复算；4 个 run 日恰为 `2026-10-15/07-15/11-20/12-15`，无第 5 个取值 |
| `scenario_counts` | `base_b0 12 / base_b0_plus_v01 8 / pre_v05_without_v07 5 / post_v05_without_v01 5 / unknown 0` | v3 设计：run 与 scenario 一一对应（`p2-holdout-v3-dataset.md` §2），故等于 run 分布 |
| `same_order_coverage` / `coverage_*` | true / 0 / 0 / 0 | loader 同序 30 题逐条对账；本件不重排 |
| `annotation_schema_version` | `p2-h2-custody/v0.2` | loader `:263` 硬要求 |
| `quality_readiness` / `quality_released` / `runtime_axis_evidence_produced` | `BLOCKED` / false / false | loader `:262-268`；r2 未质量放行 |
| `bindings` | 见 §5 | loader `:190` 要求与内部重算逐值相等（已机检到达该行之后） |
| `checks` | 15 项全 true | 逐条对应 r2 的 A/B/C 与 structure 结论，无新增断言 |

`bindings` 8 键取真值：

- `manifest_sha256` = `de4125ca9c1d1f68baa30209a12047f1f7753d25a4aa6e8a0d33815dc6b536e8`（真 SHA 复算）
- `dataset_version` = `P2-HOLDOUT-v3.1`；`label_version` = `p2-holdout-v3.1-2026-11-15`（全 30 行唯一且等于 manifest）
- `cases_sha256` = `5c86fbfb7d076093d7487eef854f58ff893b622edd2ea778ac4c6b879a9c31d4`（`cases_to_jsonl` 真算）
- `source_map_sha256` = `03665c48…`；`ingest_plan_sha256` = `2ea346d8…`；`schema_sha256` = `9fbe4b33…`；`scenario_contract_sha256` = `9dfefc39…`

`input_hashes_before == input_hashes_after`，`input_hashes_unchanged = true`。其中 12 条 `corpus:<path>` 是对 `fixtures/acceptance-h2v3/**` 真文件现算的 SHA（loader `:171-176` 会逐条重算比对）；5 条封存件 SHA 同样现算。

## 3. 轴计数与固定缺口的推导链（本包最容易变成「编造」的地方，逐条给出）

冻结 loader 要求 `review['axis_counts']` 与解密后的保管载荷逐值相等（`:220-222`），而 **v3 保管标注密文尚不存在**。因此本件的 `axis_counts` 是**投影声明**，链条如下，每一步都可复核：

1. `docs/evaluation/p2-holdout-v3.authoring-aggregate.json:25-29`：`axis_attitudes = required 95 / not_applicable 25 / total 120`。120 = 30 题 × 4 轴 ⇒ **unknown 合计必为 0**（95+25=120）。
2. `p2-h2-custody-annotations-v0_2.md:24`：`cross_user` 与 `stale_source` **全部 required** ⇒ 各 30 required。
3. 同文件 `:24`：「无资料拒答不等于无实体要求」+ `p2-holdout-v3-dataset.md:52`「`targets.jsonl` 里这两题仍保留实体锚点」⇒ 2 条 `not_found` 题的 `cross_entity` 仍是 **required** ⇒ `cross_entity` 30 required / 0 N/A / 0 unknown。
4. 于是 `safety required = 95 − 30 − 30 − 30 = 5`，`safety N/A = 25`。机检两条独立约束同时成立：`5 == sum(should_refuse)`（真数据 5 条拒答：3 安全 + 2 查无），且合计回到 95/25。

**注意**：若第 3 步被推翻（把两条 `not_found` 的 `cross_entity` 记为 unknown），自由参数会变成 `safety 7 / cross_entity 28`，与 `not_applicable 25` 冲突，因此本投影在给定公开数据的约束下**唯一**。

固定缺口：`unresolved_entity_target = unresolved_date_anchor = 0`。依据：v3.1 把 2 条 `not_found` 改为**空集证明**而非未决锚点（`p2-holdout-v3-dataset.md:52`；r2 `items.B.effective_axes` 记 `28 target 匹配 + 2 空集`、`28 日期检查 + 2 空集`，且 `four_way_consistent=true`、`as_of_eq_business_date=30`）；`unresolved_scenario` 按 loader `:166` 恒 0。

## 4. 两个口径必须说清的地方

### 4.1 `verdict` 保留原文，分歧计数按标注级记

r2 判定为 `PASS_WITH_DISAGREEMENTS`，§9 列 7 项分歧。但冻结 loader 硬要求 `independent_review_disagreement_count == scenario_disagreement_count == 0`（`:191`）且 `manager.independent_disagreements == 0`（`:179`），否则拒收。

处理：`verdict` / `independent_review_verdict` 写 `PASS_WITH_DISAGREEMENTS`（判定未改）；分歧计数按 v0.2 语义记 **标注对标注** 的分歧数 = 0（v3 尚无保管标注，也就不存在标注级分歧）。r2 的 7 项**原文逐条**保留在 `review.process_deviations`，每条前置「r2 §9 分歧（非标注级；原文保留、未改判定）：」。

这是一处**字段语义与事实不完全对齐**的妥协：`process_deviations` 严格讲是「过程偏差」而非「分歧」。冻结 schema 没有 findings/disagreements 字段，且本包不得改 loader 与键集。**建议冻结 B 在产出 v3 保管复核时，按它自己的标注级分歧重写该字段，并考虑给 `/v0.3` aggregate 增加 `disagreements[]`。**

### 4.2 三处 `null`

`annotation_ciphertext_sha256`、`review_ciphertext_sha256`（manager + review）与 `review_ciphertext_path` 置 `null`：v3 保管标注/复核密文**尚未产生**，写任何 64 位十六进制都是伪造。loader 在读到这三个值的比对处（`:194`）必然停下，这是本包能达到的最远处，见 §5。

## 5. 自检记录（可复跑）

自检脚本只用真封存件 + 真 key（key 不打印、不复制、只在进程内存），跑 `load_v3_scenario_contract` 的**默认路径**，零真实调用：

| 检查 | 结果 |
|---|---|
| `set(manager) == MANAGER_KEYS` | true（22 / 22 键） |
| `set(review) == REVIEW_KEYS` | true（49 / 49 键） |
| scenario contract 键集 / `scenarios` / `assignment_priority` 逐值等于冻结 `RECIPES` | true / true / true |
| ingest plan：12 源、`ingest_plan_from_document` 解析成功、schema `/v0.1` | 12 / true / `p2-ingest-plan/v0.1` |
| 12 条 path 全在 v3 根下、无一在 v2 根下 | true / false-inside-v2 |
| **默认路径跑 loader** | 抵达固定码 **`scenario_ciphertext_mismatch`** |
| v3 loader + v2 语料根 | `scenario_corpus_binding_invalid`（闭集仍拒 v2） |
| 冻结 v2 loader + v3 plan | `scenario_corpus_binding_invalid`（不跨实例误绑） |

`scenario_ciphertext_mismatch` 这个终点的意义：它位于 `:193-196`，**在** `:190`「`review['bindings'] == expected` 且 structure/semantic 为 PASS」**之后**。也就是说以下各层在真数据上逐条走过：四件默认路径的 `_read`/`_json`/`_exact`、计数区间校验、固定缺口互校（`:165-167`）、`input_hashes_before == after`、**12 个语料源逐个现算 SHA 的语料绑定**（`:171-176`）、manager 的 schema/frozen/30 题/0 未知/0 分歧/PASS-PASS、以及 `bindings` 8 键与内部重算的逐值相等。没有出现 `scenario_input_unreadable`。

未被覆盖的一段：`:197` 起的解密、载荷 `bindings` 对账、30 题逐题 `axes` 校验、`scenario_counts`/`axis_counts` 与载荷对账（`:220-222`）。这段**只能**由 v3 保管标注包闭合，本包无法也不应代做。

## 6. 越界说明：为什么多出第 4 件

`p2_holdout_scenarios_v3.py` 的默认路径共 7 个：`V3_SOURCE_MAP`、`V3_SCHEMA` 已存在；`V3_SCENARIO_CONTRACT`、`V3_MANAGER`、`V3_REVIEW_AGGREGATE` 是本包三件；**`V3_INGEST` 是第 4 个缺失件**。

- loader 在读三件**之前**就先 `_read(ingest_path)`（`:125`）。缺它，三件永远不可达，抛的正是同一个 `scenario_input_unreadable`，与「三件缺失」不可区分。
- 第 1 件的 `ingest_plan_sha256` 按 briefing 要求是「v3 ingest plan 的真实 SHA」。plan 不落盘，这个 SHA 只能是占位或猜的。
- 因此第 4 件不是扩范围，而是「三件可读 + SHA 可复算」的前置条件。其内容被规格逐条定死（§2.1），字节可复算，无判断题。

同时声明**未做**（按 briefing）：冻结清单、双人脚本、接线（`p2_holdout_scenarios_v3.py` 一字未改）、账本/GO/阈值、v2/v3 语料与密文、C 冻结 12、已接收模块。

## 7. 残余

1. **v3 保管标注/复核密文未产出**：三处 `null`（§4.2）与 `:197` 之后的全部校验未闭合。这是本包唯一的硬缺口，属冻结 B。
2. **`axis_counts` / 固定缺口是投影**（§3）：与未来保管载荷必须逐值相等；若冻结 B 的标注推翻 §3 第 3 步，`safety`/`cross_entity` 需同步改（且会与 authoring-aggregate 的 95/25 冲突，须先解释冲突再改）。
3. **`independent_*` 与 `scenario_assignment_frozen: true` 是声明**：由 r2 的复核结论支撑，**不是** v3 保管复核的产物。冻结 B 落地时应以真复核记录替换，不得把本件当证据引用。
4. **分歧计数口径**（§4.1）：`process_deviations` 承载了 7 项非标注级分歧，字段语义不纯；建议 v0.3 aggregate 增设 `disagreements[]`。
5. **`conflict` 状态仍 0 题**（覆盖缺口，非漏配）：4 状态只覆盖 3 状态，见 `pre-registration.json` 的 `CONFLICT_STATE_UNCOVERED`；本件未把它写成「已覆盖」。
6. **计分侧 `/v0.2` source map 分发**仍未实现（`p2_score_run.load_holdout_source_map` 只收 `/v0.1`），属接线包，本包未碰。
7. **`label` 取值**（§2.1）`H2-v3` 是判断项，非规格逐字要求。

## 8. 零调用与保全

- 零真实调用、零真实请求：本包只做文件读写与本地纯计算；`load_p2_dataset(holdout)` 是本地解封与校验，不触网；未启服务；未建 GO。
- 未读：真实 H2 题面/答案、`.env`、保管会话、runbook、评分、trace。解封只取 `case_id` / `stratum` / `business_date` / `expected_kind` / `should_refuse` / `turns` 长度这些结构字段，**未取出也未写出任何题面或答案字符串**。
- 未改：`fixtures/acceptance/**`、`fixtures/acceptance-h2v3/**`、C 冻结 12、`p2_holdout_scenarios.py`、v2 件、账本/GO/阈值；未 stage/commit/push；未新建 worktree/切分支。
- 保全（前后对比）：分支 `codex/p2-e2e`、HEAD `97b00667…` 不变；暂存 0；15 条 tracked modified 路径不变（本包未编辑任何既有文件）；untracked 状态行 230 → 232（+`docs/evaluation/p2-h2-scenarios-H2v3.json` 一行、+`docs/reports/OBS-EVAL/P2/H2V3/` 一行；后者包含 4 件）。

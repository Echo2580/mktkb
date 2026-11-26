# Q1a-3-R2 真实 H2 只读重评分 + 11 fail 分诊（分析身份 `Q1A-RESCORE-20261114-r1`，第二版实现）

主人，本轮是 **Q1a-3-R2 纠偏返工**：经理认定 R1 的 `version_bindings` 置空属欠应用，另要求补查 `document_codes` 投影、只读复用 C 冻结空集原语、并如实处理 `shared_background`。R2 按 A/B/C/D 四项逐条执行；**没有**改冻结件、**没有**构造旧逐题值、**没有**派子助手。

- 角色：保管执行（新上下文）。非开发、非验收、非经理。
- 基线：分支 `codex/p2-e2e`、HEAD `97b0066726e5b8d6f94cbc0b63a890084550c106`、暂存区 0 项、0 commit。
- 零真实调用：network/socket/DNS/provider/model/embedding/rerank/OCR/judge/retrieval/鉴权/余额/real = 0；未新建 GO、未启动服务、零出站（socket 层拦截 + 正对照 `blocked`，见 `evidence-r2/06-netguard.json`）。

## 1. 新身份组件（字节实测，全部全等）

`identity.overall = MATCH`；10 项期望值逐值相等；4 个 run 的 evidence 树摘要与各自 `seal-manifest.evidence_root.tree_sha256` 交叉相等；与 R1 已发布的组件**逐项相等**（`cross_round.all_equal = true`）。

| 组件 | 实测值 |
|---|---|
| `old_run_binding_payload_sha256` | `291cfec9d99446c88f0063d533c92632cef15594c1f6ce3da2269cef98ae65d4` |
| `old_run_binding_file_sha256` | `3108b87b13373802bee6566999cd7196fcfbc5de1853707447e0356f07d775ee` |
| `old_evidence_tree_sha256`（4 run 合成） | `16420e903d13a47cc0cf9634323c18cea2442872b6cf0e35cacda1f89c7c8da5` |
| `old_card_sha256`（4 卡合成） | `53e4a82bfe8369b2e730a70a5cb7f7b4f0133003d8980c60dd825472a64ad25d` |
| 合同密文 | `467dbf7706df26f2069a79e2b344b53c0e10c03ff830ed62efff9b5dfd16f461` / 47012 B |
| 合同 schema | `cb1257fac56a68e5eef791c23cffba9d4e915e5e9a840abce7bde5b96e0e4690` |
| Q1a-1 模块 / 契约 | `d8260256…41f3e9` / `e0487f25…75588d` |
| Q1a-1b 模块 / 契约 | `57495943…00f08e` / `747e3656…4c8db5` |
| C 冻结 `p2_hard_evidence.py` | `fba6e606991cd4bcf06f9e2ef1a50b60fd5d302979844a53de3bfb45a843529b` |
| 包级绑定摘要（本包自定 canonical，防拼轮） | `7a2aacd3e93cdacc95f70117905be18d62bbbc440be20c5fd5a0fbb064de8f2e` |
| R2 输入绑定摘要（额外绑定公开结构输入） | `a3663389bd437347afc35964f6d7f1f6a038efd2060b87f5f60e99483646ae76` |

**未签发**模块的 `analysis_identity_sha256`：本包不经 `rescore_run` / `rescore_axes_run`（它们的输入要求含 `OldCardCase`），硬造该摘要等于伪造结论。

## 2. 四项纠正：执行结果

### A. `VersionBinding` 从批准来源确定性推导（纠正 R-Q1A3R1-03）

- 输入只用合同 schema §1 允许的公开件：scenario 合同 `p2-h2-scenarios-v0_2.json`（生效上传集）、原 12-source ingest plan（上传顺序）、source map（`base_doc_code`/`version_number`）、fixture manifest（正常文件/独立变体的 `business_version`）。
- 每个 scenario 的 active 版本 = 该 scenario 上传集中同一逻辑文档槽的最大版本；0 个 active / 歧义 / 显式变体码版本不 active → 该 ref `unresolved`。**没有**用“只剩一个版本”或答案反推补身份；公开结构输入 hash 与 active 表 canonical hash 已写入聚合。
- **可绑定 71 / 73**；仍 unresolved **2**（全部为 `ref_version_not_active`：2 个禁止源 ref 显式钉在历史变体(v1)，而所有 scenario 的位置表文档槽 active 版本均 ≥2；按规则不把历史版本当 active）。
- 归一化别名 **5**（变体码在对应 scenario 为 active 时才归一到其 base 文档槽；历史变体未 active 时不归一，避免与同 record/locator 的正常文件 ref 冲突）。
- 绑定来源：`ingest_order` 63、`source_map` 8；`hardcoded_version_literals = 0`。
- 可绑定不等于可匹配：逐 ref 走 matcher v2 的结果为 **match 20 / `unit_record_unresolved` 35 / `no_units` 13 / `doc_mismatch` 3 / `unbound` 2**。剩余 unknown 的**主因已从版本缺口转为 record_code 缺口**（见 R-Q1A3R2-07）。

### B. `document_codes` 投影重查（纠正 R1 只命中 2/12）

- 规则改为**产品身份**：产品文档名 = ingest `name`（若有）否则 path basename；同一产品名对应唯一逻辑文档槽；变体文件名经 source map 归一到 `base_doc_code`。
- R1 规则（前缀∈source_map base 全集）：12 个 ingest 名称命中 **2**；91 个实际使用 unit 命中 **22**。
- R2 规则：11 个不同产品名命中 **11/11**；91 个实际使用 unit 命中 **91/91**，unresolved **0**。
- 结构原因（R1 未命中的 10 个名称）：4 个正常文档前缀不在 source_map 的 2 个 base 里；4 个 source_map 变体文件名前缀是 V 码而不是 base 码；2 个独立通知变体没有 source_map 条目。R2 分别用 fixture manifest 正常文件 id、source map 的 `base_doc_code`、fixture manifest 变体 id 确定性补齐。
- 历史变体特殊点：ingest 的 `name` 是位置表文档槽的 display name，所以该变体的 unit 产品名是位置表文档槽、版本是 v1；R2 按“产品名→文档槽 + 版本区分”处理，没有把它当成独立产品名。

### C. 只读复用 C 冻结空集原语（纠正 R-Q1A3R1-06）

- 只读 import `backend/src/mktkb/evaluation/p2_hard_evidence.py::_empty_use_scope_proof`，只用于提供 `empty_scope_proven` 的 bool/reason。
- 模块前后 SHA 均为 `fba6e606991cd4bcf06f9e2ef1a50b60fd5d302979844a53de3bfb45a843529b`，**未改一字节**；`module_unchanged_during_run = true`。
- 36 个执行回合：**proven 2**（`empty_use_scope_ok`）、not proven 34（`empty_set_not_proven` 32、`model_events_missing` 2）、原语异常 0。
- 影响：2 条 `stale_source` 轴由 unknown 转 pass（C 类归因 2）；未用于生成旧 verdict、未替代 matcher/N-A 判定。
- 仍有 1 个 fail 题的 `empty_set_not_proven` 未被证明；C 的收益是“少数可判化”，不是“全部可判化”。

### D. `shared_background` 条目

- **未补齐，保留 unknown**：公开语料结构给不出冻结的 `unit_id`/`version_id`；用运行期 used units 反填等于用产品输出定义目标，越界。
- 固定 code：`shared_background_entries_missing`；公开侧 `projected_entries = 0`、`effective = false`。
- 该项对状态**无效**（no state change）；这是如实结论，不是遗漏。

## 3. 四轴：old（聚合）vs new（逐题算后聚合）

旧值 = 4 张卡 `hard_evidence.axes` 求和（已复算，与经理给的数字逐值一致：safety 30/1/24/3/2、cross_user 30/27/0/3/0、cross_entity 30/3/0/27/0、stale_source 30/25/0/5/0）。新值 = 本包逐题结果聚合。

| 轴 | 侧 | planned | checked | passed | not_applicable | unknown | violations |
|---|---|---:|---:|---:|---:|---:|---:|
| safety | old | 30 | 27 | 1 | 24 | 3 | **2** |
| safety | **new** | 30 | 29 | 1 | 28 | 1 | **0** |
| cross_user | old | 30 | 27 | 27 | 0 | 3 | 0 |
| cross_user | **new** | 30 | 30 | **30** | 0 | **0** | 0 |
| cross_entity | old | 30 | 3 | 3 | 0 | 27 | 0 |
| cross_entity | **new** | 30 | 1 | 1 | 0 | **29** | 0 |
| stale_source | old | 30 | 25 | 25 | 0 | 5 | 0 |
| stale_source | **new** | 30 | 13 | **13** | 0 | **17** | 0 |

- 自洽校验（四轴逐一通过，脚本内断言）：`planned = passed+NA+unknown+violations`；`checked = passed+NA+violations`；`planned = checked+unknown`。
- 新侧 reason 分布：safety `NA:benign…28 / pass:frozen_forbidden_checks_ok 1 / unknown:forbidden_source_unmappable 1`；cross_user `pass:all_user_contexts_ok 30`；cross_entity `pass 1 / targets_unresolved 19 / free_text_attribution_unverifiable 9 / model_events_missing 1`；stale_source `pass 13 / source_unresolved 13 / empty_set_not_proven 2 / model_events_missing 2`。
- `axes_provenance`：safety 与三轴均为 `rescored`；旧侧 `recorded_old_aggregate_only`；逐题 old→new 表 `NOT_AVAILABLE`（4 卡 `detail_export=false`，不构造旧逐题值）。
- 新判据方向：stale_source 的 9 条 unknown 变 pass 是**可判化**（violations 仍为 0）；cross_entity 仍有 29 unknown，主因是合同缺实体 targets + record_code 缺口 + 共享背景未投影，不是“产品答错”。

## 4. 11 fail 分诊（11/11 已归类）

题号来源 = `case-plan.json` 的逐题 `quality_status=fail`（**不在公开侧出现**）；按 run：r0=8 / r1=0 / r2=2 / r3=1。

| 枚举 | 计数 | 固定 code 分布 |
|---|---:|---|
| `annotation_or_criterion_issue` | **1** | `na_scope_benign_suppression` 1 |
| `product_error` | **0** | —（新侧四轴 violations 全为 0） |
| `evidence_insufficient` | **10** | `contract_entity_targets_missing` 6、`version_binding_missing` 3、`shared_background_entries_missing` 3、`empty_scope_closure_proof_not_reimplemented` 1、`other_input_gap` 2（一题可命中多因） |
| `undetermined` | **0** | — |

- 与 R1 相比：`empty_scope_closure_proof_not_reimplemented` 4→1；新增 `other_input_gap` 2（对应 3 条 `model_events_missing` 轴，按题去重后 2 题），来自 C 原语返回的新固定 reason。
- `product_error = 0` 是本批硬事实：新侧四轴 violations = 0/30。没有 `product_error` 不等于“产品没问题”，只能说**在新判据、本批输入下没有可确证的 violation**。

## 5. safety r0 / r2 重判

| run | 旧 safety（聚合） | 新 safety（逐题算后） | 结论 |
|---|---|---|---|
| r0 | 26 题：1 pass / 22 N/A / 2 unknown / **1 violation** | 24 N/A / 1 pass / 1 unknown / **0 violation** | **`false_positive_under_new_criteria`** |
| r2 | 2 题：0 pass / 1 N/A / 0 unknown / **1 violation** | **2 N/A** / 0 violation | **`undetermined`** |

- r0：R2 的显式 VersionBinding + document_codes 让 forbidden ref 可映射；新侧 0 violation，禁值/拒答检查与旧实现逐字节同源，旧 violation 只可能来自 matcher；`safety-n/a-scope/v1` 在 benign N/A 下抑制 unresolved。结论与 R1 一致（false positive under new criteria）。
- r2：新侧 0 violation 只说明“确定性匹配器没复现”；保管 A 的 `outbound_send` / `retrieval_or_use_scope_issue` 是语义主张（需读回答文本），保管 B 是 `mapping_or_annotation`；两者新判据都不能判 → 保留 `undetermined`，不表决、不择优。
- 未应用项：Q1a-1 §7 的 `old_verdict_preserved` / `missing_codes` 前置门依赖旧卡逐题值（`NOT_AVAILABLE`）→ R-Q1A3R2-01。

## 6. 27 个 cross_entity unknown

旧：`passed 3 / unknown 27 / violations 0 / N/A 0`（聚合）。新：`passed 1 / unknown 29 / violations 0 / **N/A 0**`。

| 计数 | 值 | 性质 |
|---|---|---|
| 转 pass | `0 … 1`（上界 1） | 旧 unknown 成员集 `NOT_AVAILABLE`，只能给界 |
| 转 fail | **0** | 新侧该轴 violations = 0，上界即 0 |
| 保留 unknown | `26 … 27` | 由 \|old unknown\|=27、\|new unknown\|=29 推出 |
| 改 N/A | **0**（精确） | 新侧该轴 `not_applicable = 0` |

另可断言：旧 3 个 pass 里**至少 2 个**在新判据下不再 pass。A/B 让 `target_ref_resolved` 从 0 升到 9、`target_ref_unresolved` 从 20 降到 13，但轴状态未变——实体 `targets` 缺失（R-Q1A3R2-04）仍是硬阻断。

## 7. 9 分歧敏感性带（两套都报、都标、谁也不选）

| 读数 | cross_entity required / N-A | cross_entity 新计数 | 四轴其余 | 合格题数 |
|---|---|---|---|---|
| **A：合同 v1** | 30 / 0 | pass 1、unknown 29、N/A 0 | safety 1/28/1、cross_user 30/0/0、stale 13/0/17（pass/N-A/unknown） | **1** |
| **B：保管 B（9 轴 N/A）** | 21 / 9 | 仅 D1 的 7 轴可结构唯一隔离：N/A 7、pass 1、unknown 22 | 同上（其余三轴不变） | **8**（D1-only）；含 D2/D3 的区间 **1 … 9** |

- D1 `shared_background` 7 条可由 `criterion` 精确隔离；D2 `multi_target_policy_compare` 是 4 条 `multi_target` 中的 1 条、D3 `document_artifact_target` 无结构字段，两者**不能逐条点出**，只给区间（4 个 D2 候选逐一试算：8/8/9/8）。
- R1→R2：B 读数从 2 升到 8，区间从 1…2 扩到 1…9。原因是 stale_source 可判化后，被 B 读法置为 N/A 的 cross_entity 轴不再拖累题级合格；这是**读数敏感带变宽**，不是本包选择了 B。本包不选任何一侧，也不改写合同。

## 8. D4–D7 残余标记（不声称 scope 已解决）

| 项 | 计数 | 标记 | 是否可逐轴定位 |
|---|---:|---|---|
| D4 `explicit_time_window_not_in_filters` | 2 | `scope_weak` | 否（需题面语义） |
| D5 `empty_entity_key` | 1 | `scope_weak` | **是**（结构实测 1 = 登记值 1） |
| D6 `stale_source_only_as_of` | 3 | `scope_weak` | 否（结构候选 5 条：required + 无 target_refs + as_of 非空） |
| D7 `historical_intent_uses_business_baseline_as_of` | 2 | `disclosed_limit` | **是**（结构实测 2 = 登记值 2） |

`claim_scope_fully_resolved = false`。逐轴定位结果只写入仓外私有密文，公开侧只有计数。

## 9. 干净分数（新口径）

| 项 | 值 |
|---|---:|
| 合格题数（required 轴全 pass、无 violation、无 required unknown） | **1** / 30 |
| hard failure 题数（任一轴 violation） | **0** / 30 |
| unknown 题数（无 violation 但存在 required/unknown 轴） | **29** / 30 |
| 是否 ≥ 24/30 | **否** |

只陈述数字与是否达标；**不写“通过”、不写 release**。

## 10. R1 vs R2 差异（必须交付）

### 10.1 逐轴变化量与原因

| 轴 | checked | passed | unknown | violations | 变化原因（主影响分类） |
|---|---:|---:|---:|---:|---|
| safety | 0 | 0 | 0 | 0 | 无状态变化；A/B 只增加可映射的 forbidden ref，未改变 safety 状态 |
| cross_user | 0 | 0 | 0 | 0 | 无状态变化 |
| cross_entity | 0 | 0 | 0 | 0 | 无状态变化；A/B 仅让 audit `target_ref_resolved 0→9`、`target_ref_unresolved 20→13`，被 R-Q1A3R2-04 阻断 |
| stale_source | **+9** | **+9** | **−9** | 0 | 9 条 `unknown→passed`：A 类 7、C 类 2（B 为必要使能，见下） |

- 逐题转移（R1 私有明细状态，无文本）：`stale_source: unknown→passed = 9`；其余轴 0。
- 纠正归类计数（主影响，一题多因按 C > A > B 记一次）：**A 7、B 0、C 2、D 0、other 0**。
- **A/B 耦合必须说清**：A 给版本、B 给 doc_code，任一缺失匹配仍 unresolved。B 自身作为“主影响”为 0，但 B 把实际使用 unit 的可映射数从 **22/91 提到 91/91**（+69），是 A 的 7 条 stale 转移能够落地的前提；把 B 记为“无效”会误导。
- **A/B 对 cross_entity 状态无效**：pass 1 / unknown 29 / violations 0 与 R1 完全相同，只改了 audit 覆盖；原因是合同 v1 对 structured/multi_target 只给 target_refs、未给实体 targets（R-Q1A3R2-04）。
- **D 无效**：`shared_background` 仍 0 条目、仍 unknown；固定 code `shared_background_entries_missing`。

### 10.2 `version_bindings` 覆盖

| 项 | R1 | R2 |
|---|---:|---:|
| 可绑定 ref | 0 / 73 | **71 / 73** |
| 仍 unresolved | 73 | **2**（`ref_version_not_active`） |
| 归一化别名 | 0 | 5 |
| 绑定来源 | 空映射 | `ingest_order` 63、`source_map` 8 |

- 2 个 unresolved 的歧义原因分布：`ref_version_not_active = 2`（禁止源 ref 钉在历史变体/v1；所有 scenario 的位置表文档槽 active ≥2）。
- 归一化冲突防护：若归一化让不同原始 ref 落到同一 key 且绑定不一致，则该 key 不绑定、fail closed；本次实际冲突 **0**。
- **绑定覆盖率不是匹配成功率**：71 个可绑定 ref 中，matcher v2 实际 match 20；35 个 `unit_record_unresolved`、13 个 `no_units`、3 个 `doc_mismatch`、2 个 `unbound`。record_code 缺口已是剩余 unknown 的主因（50/73 ref 带 record_code）。

### 10.3 `document_codes` 覆盖

| 项 | R1 | R2 |
|---|---:|---:|
| ingest 名称命中 | 2 / 12 | **11 / 11 个不同产品名** |
| 实际使用 unit 命中 | 22 / 91 | **91 / 91** |
| unresolved | 70 / 91 | **0** |

- R1 未命中的结构原因：4 个正常文档不在 source_map 的 2 个 base 全集、4 个 source_map 变体文件名是 V 码、2 个独立通知变体无 source_map 条目。
- R2 未命中为 0；历史变体的 display-name 与 v1 由“产品名 + 版本”区分，未伪造独立 doc_code。

### 10.4 空集原语

| 项 | R1 | R2 |
|---|---:|---:|
| 复用 | 否（禁止 import） | **是**（只读原语） |
| proven turns | 0 / 36 | **2 / 36** |
| not proven | 36 / 36 | 34 / 36（32 `empty_set_not_proven` + 2 `model_events_missing`） |
| 影响轴 | 0 | 2 条 stale_source（C 类归因） |

### 10.5 干净分数变化与方向

| 项 | R1 | R2 | 方向 |
|---|---:|---:|---|
| pass | 1 | **1** | 不变 |
| hard failure | 0 | **0** | 不变 |
| unknown | 29 | **29** | 不变 |

- **方向判定：`unknown_down_violations_same_decidable`（轴级）**。stale_source unknown −9、violations 不变；不是“变严”（没有新增 violation），也不是“洗 pass”（题级 pass 未变）。
- **题级分数不变的原因**：9 条 stale 转移所在题的 cross_entity 仍为 unknown（合同缺实体 targets / record_code 缺口），题级折叠仍为 unknown。轴级可判化没有自动变成题级合格。
- **B 读法敏感带变宽**（1…2 → 1…9）是方向异常，已在第 7 节点明；本包不选边。
- **无任何纠正造成 violations 增加**；也没有任何 unknown 被改成 N/A（`set_to_not_applicable = 0`）。

## 11. 保全与零调用

文件级核验见 `evidence-r2/04-protected-compare.json`（`verdict = unchanged`，`difference_count = 0`）与 `evidence-r2/07-preservation-check.json`（`PASS 21/21`）：

- **35 个保护项（28 个仓内文件 + 7 个外部树/密文；after 另含 R2 私有明细）**：C 冻结、Q1a-1/1b 模块与契约、受控入口、manifest/source-map/scenario、T207-CUSTODY-V2/V3、Q1a 各阶段 receipt、旧 run binding、旧 run 树（卡/evidence/seal/case-plan/台账/GO 均在树内）、holdout 根、custody 标注、合同密文、R1 产物（aggregate/report/evidence-r1 树）、NOT-RUN 产物（aggregate/report/evidence 树）before/after **逐项相等**。
- 旧卡 4 张字节不变（r0 `d055f1ac…`、r1 `df078a34…`、r2 `88ac5a4a…`、r3 `a291e5f2…`）；旧 evidence 树摘要不变（`16420e90…`）；旧 run 树摘要不变。
- R1 产物未动：`rescore-aggregate-r1.json` = `605c89cb…` / 31836 B；`rescore-detail-r1.fernet` = `2f6f4d85…` / 74488 B；`rescore-report-r1.md` 与 `evidence-r1/` 亦未改。
- 更早 NOT-RUN 产物未动：`rescore-aggregate.json`、`rescore-report.md`、`rescore/evidence/` 逐字节不变。
- git：`tracked_modified = 15`（路径逐条与 R1 起点一致）、`staged = 0`、`commits = 0`、HEAD `97b0066…` 与分支 `codex/p2-e2e` 不变；外来 untracked 文件树摘要不变（2086 个文件，排除本任务 `rescore/` 目录）。
- 未 import/未改 C 冻结；未改 Q1a-1/1b 模块与契约；未改账本/预算/GO/合同密文；未 stage/commit/push；未新建 worktree/切分支；未派子助手；未读 `.env`/runbook/scoring/他人会话。
- 零真实调用：`evidence-r2/06-netguard.json`（`verdict = zero_network_attempts`，socket 构造/连接/DNS/create_connection 全 0，正对照 `blocked`，inner `exit:0`）。
- 公开侧隐私自查：`evidence-r2/05-privacy-scan.json`（needles 含题号/题面/答案/目标值/实体键/记录码）命中 **0**。

## 12. 残余（本包不消除，逐条编号）

| id | 严重度 | 内容 |
|---|---|---|
| R-Q1A3R2-01 | medium | Q1a-1 §7 的 `old_verdict_preserved` / `missing_codes` 前置门未应用（依赖旧逐题值）。新侧是纯新判据计算，**不等于**合同完整重评分。 |
| R-Q1A3R2-02 | medium | 旧逐题四轴 `NOT_AVAILABLE`（4 卡 `detail_export=false`）：无逐题 old→new 表，也不声称做过。 |
| R-Q1A3R2-03 | medium | 2/73 个禁止源 ref 的 doc_code 显式钉在历史变体(v1)，所有 scenario 的位置表文档槽 active 版本 ≥2；按规则保留 unresolved，不把历史版本当 active。 |
| R-Q1A3R2-04 | high | 合同 v1 对 structured/multi_target 只给 target_refs、未给实体 targets；`entity_bound` 要求实体 targets → 该类轴仍无法进入实体判定。 |
| R-Q1A3R2-05 | medium | `shared_background` 条目未投影（公开语料给不出冻结 unit_id/version_id）→ 该 criterion 的轴仍只能 unknown。 |
| R-Q1A3R2-06 | medium | C 冻结空集原语已只读复用；36 回合中仅 2 个通过严格闭包（32 `empty_set_not_proven`、2 `model_events_missing`），故该纠正只对少数轴可判化。 |
| R-Q1A3R2-07 | **high** | 无冻结 unit_key→record_code 映射：`UnitView.record_code` 显式空。73 个 ref 中 50 个带 record_code；逐 ref 匹配 35 个 `unit_record_unresolved`，是 A/B 纠正后剩余 unknown 的**主因**。 |
| R-Q1A3R2-08 | low | D4/D6 只能给登记计数与结构候选，无法逐轴定位（需题面语义）。 |
| R-Q1A3R2-09 | medium | r2 场景出现公开 ingest 结构外的 `unit.version_number`（7 个 v3、1 个 v2）；本包按产品身份映射 doc_code，但版本比较仍按合同 active 版本，方向异常如实报告。 |

## 13. 产物

| 类型 | 路径 | SHA256 / 字节 |
|---|---|---|
| 公开聚合 | `docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/rescore/rescore-aggregate-r2.json` | `2447d945485fb89e75dc3dbf6553f68073ec467cf8cbc415b900143f7908daaf` / 46804 B |
| 本报告 | `docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/rescore/rescore-report-r2.md` | 本文件 |
| 证据（脚本+输出） | `docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/rescore/evidence-r2/` | 结构探针、未解析诊断、保护件快照、netguard、privacy scan、preservation |
| 私有逐题明细 | `D:\mktkb-q1a3-rescore\rescore-detail-r2.fernet` | `fef978b73a4bd7e5c51b39eebf759f35826492632d5509cead6126153b1072b1` / 108108 B（独占创建，同一 key 容器；仅状态/枚举码，无文本） |

## 14. 结论

**`COMPLETE_WITH_RESIDUALS`** —— 经理要求的 A/B/C 三项纠正均已执行并可复算：A 71/73 可绑定、B 91/91 unit 可映射、C 原语只读复用且模块字节不变；D 因公开结构不足而**如实不应用**。四轴逐题重算、11/11 分诊、r0/r2 重判、27 unknown 四计数、9 分歧两套、D 标记、干净分数、R1→R2 差异、保全与零调用均已产出。

残留为第 12 节已编号的 9 条输入缺口（record_code 缺口、合同实体 targets 缺失、shared_background 未投影、空集原语仅 2/36 通过、旧逐题值不可得等）；**没有**未完成的缺项，也**没有**把任何 unknown 改成 N/A。

本包**不构成** T207 通过、P2 完成、质量放行或阈值/发布依据；`verified` / `threshold_met` / `release_ready` / `T207_pass` 一律未主张。

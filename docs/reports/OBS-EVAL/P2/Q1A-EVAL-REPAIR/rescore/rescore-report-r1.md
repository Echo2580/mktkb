# Q1a-3-R1 真实 H2 只读重评分 + 11 fail 分诊（分析身份 `Q1A-RESCORE-20261114-r1`）

主人，本轮是 **Q1a-3 的返工（R1）**，按经理 2026-11-14 裁定重做：

- 旧逐题四轴值**不构造**（不建 `OldCardCase`、不补造、不伪造）；旧侧只用 4 张卡的**聚合**，标 `recorded_old_aggregate_only`；逐题 old 四轴 = `NOT_AVAILABLE`（R-Q1A3R1-02）。
- 新侧**逐题算出**（本包核心）：safety 用 Q1a-1 的 `_evaluate_turn` + `_fold_safety`（matcher v2 + `safety-n/a-scope/v1`）；`cross_user` / `cross_entity` / `stale_source` 用 Q1a-1b 的 `_rescore_cross_user` / `_rescore_cross_entity` / `_rescore_stale_source` + 合同 v1，逐回合算、题内按 `violation > unknown > not_applicable > passed` 折叠。
- 角色：保管执行（新上下文）。非开发、非验收、非经理；未派子助手；未改冻结件。
- 基线：分支 `codex/p2-e2e`、HEAD `97b0066726e5b8d6f94cbc0b63a890084550c106`、暂存区 0 项、0 commit。
- 零真实调用：network/socket/DNS/provider/model/embedding/rerank/OCR/judge/retrieval/鉴权/余额/real = 0；未新建 GO、未启动服务、零出站（socket 层拦截 + 正对照实测，见 `evidence-r1/03-netguard.json`）。

## 1. 新身份组件（字节实测，全部全等）

`identity.overall = MATCH`；10 项期望值逐值相等；4 个 run 的 evidence 树摘要与各自 `seal-manifest.evidence_root.tree_sha256` 交叉相等；与上一轮已发布的组件**逐项相等**（`cross_round.all_equal = true`）。

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

**未签发**模块的 `analysis_identity_sha256`：本包不经 `rescore_run` / `rescore_axes_run`（它们的输入要求含 `OldCardCase`），硬造该摘要等于伪造结论。

## 2. 合同 v1 消费与投影口径

- 合同密文先复算 SHA256（`467dbf77…f461` / 47012 B）再解密，严格 JSON（拒重复键），key 只在进程内存。
- `load_q1a2_contract_view(payload, expected_axes=合并后冻结标注)`：30 题 / 120 轴 7 字段**深度相等**，`basis` 合法，`unknown` 为 0，18 码权威 reason 表全部命中（`contract_consumer.*`）。
- 合并口径按合同 §2.3：v0.2 原值 + v0.3 addendum 的 4 个 `resolved` gap（2×`stale_source`、2×`cross_entity`；**无 safety gap**，这一点是 §5 推论链的前提）。
- 契约证据树：30 题 / **36 回合** / **91 个实际使用 unit**；全部 36 回合 `status=executed`、`completeness.status=complete`、`query_states_available=true`，故 `evidence_complete_derived=true`（30/30）。
- 适配层为**显式 required 校验**（缺键/坏类型 → 固定 `ProjectionError` 码，无 `getattr` fail-open）。

显式「不猜」的四处（都是本批输入的真实缺口，不是实现偏好）：

| 项 | 本包取值 | 依据 |
|---|---|---|
| `version_bindings` | 空映射（ref→版本 = unresolved） | 冻结 ref 只有 `doc_code`/`record_code`/`locator`，无 version 字段；source map 只能给「文件→(doc,version)」，无法把某个 ref 绑到某个版本；Q1a-1 §3 明令不得用「证据里只剩一个版本」补身份 |
| `record_codes` | 空映射 | 无冻结 `unit_key→record_code` 映射 |
| `shared_background` 条目 | 空元组 | 属公开语料结构投影；本包不伪造，缺失 → 该轴只能 unknown |
| 空使用集闭包证明 | 标 `empty_set_not_proven` | C 冻结模块的 `_empty_use_scope_proof` 禁止 import；不重写也不冒充 |

`document_codes`（产品文档名→doc_code）按公开结构显式建立：doc_code 全集取 source map 的 `base_doc_code`（公开件，2 个字面值；公开侧只记计数，不落字面值以免与实体键同形），名称取自 ingest plan 的 `name`/`document_ref`/path basename，前缀命中才映射（12 个名称中 2 个命中）。

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
| stale_source | **new** | 30 | 4 | 4 | 0 | **26** | 0 |

- 自洽校验（四轴逐一通过，脚本内断言）：`planned = passed+NA+unknown+violations`；`checked = passed+NA+violations`；`planned = checked+unknown`。
- 新侧 reason 分布：safety `NA:benign…28 / pass:frozen_forbidden_checks_ok 1 / unknown:forbidden_source_unmappable 1`；cross_user `pass:all_user_contexts_ok 30`；cross_entity `pass 1 / targets_unresolved 25 / free_text_attribution_unverifiable 3 / empty_set_not_proven 1`；stale_source `pass 4 / source_unresolved 20 / empty_set_not_proven 6`。
- `axes_provenance`：safety 与三轴均为 `rescored`；旧侧 `recorded_old_aggregate_only`。
- **逐题 old→new 表：`NOT_AVAILABLE`**。原因只有一条：4 张旧卡 `detail_export=false`，只留聚合计数；本包不构造旧逐题值，所以没有、也不声称有逐题对照。

**方向必须说清**：新判据在本批输入下**更严**（fail closed），cross_user/safety 的可判化变好（unknown 3→0、3→1），但 **cross_entity 27→29、stale_source 5→26 的 unknown 变多**。这不是"产品变差"，而是新判据要求旧判据不曾需要的输入（ref→版本绑定、实体 targets、共享背景条目、空集闭包证明）；缺这些输入时它只能 unknown。

## 4. 11 fail 分诊（11/11 已归类）

题号来源 = `case-plan.json` 的逐题 `quality_status=fail`（**不在公开侧出现**）；按 run：r0=8 / r1=0 / r2=2 / r3=1。

| 枚举 | 计数 | 固定 code 分布 |
|---|---:|---|
| `annotation_or_criterion_issue` | **1** | `na_scope_benign_suppression` 1 |
| `product_error` | **0** | —（新侧四轴 violations 全为 0，无任何 `product_error` 证据） |
| `evidence_insufficient` | **10** | `contract_entity_targets_missing` 6、`empty_scope_closure_proof_not_reimplemented` 4、`shared_background_entries_missing` 3、`version_binding_missing` 3（一题可命中多因） |
| `undetermined` | **0** | —（无矛盾、无不可判残留） |

- 那 1 题 `annotation_or_criterion_issue`：新侧 required 轴全过，转正机制是 `safety-n/a-scope/v1` 对 `not_applicable + benign_business` 作用域抑制了身份不可解析的 forbidden ref（`forbidden_source_suppressed_na_scope`）。
- 10 题 `evidence_insufficient` 的共同点：不是"答案对错"，而是**判据所需输入缺失**——合同对 `structured/multi_target` 只给 `target_refs`、没给实体 `targets`；ref→版本无显式绑定；共享背景条目未投影；空使用集闭包证明未重实现。
- `product_error` 为 0 是本批的硬事实：新侧四轴 violations = 0/30。没有 `product_error` 不等于"产品没问题"——只能说**在新判据、本批输入下没有可确证的 violation**。

## 5. safety r0 / r2 重判

| run | 旧 safety（聚合） | 新 safety（逐题算后） | 结论 |
|---|---|---|---|
| r0 | 26 题：1 pass / 22 N/A / 2 unknown / **1 violation** | 24 N/A / 1 pass / 1 unknown / **0 violation** | **`false_positive_under_new_criteria`** |
| r2 | 2 题：0 pass / 1 N/A / 0 unknown / **1 violation** | **2 N/A** / 0 violation | **`undetermined`** |

r0 的推论链（不依赖旧逐题值，逐条可查）：

1. 新侧 r0 safety violation = 0（`new_safety_audit_codes`：`forbidden_source_no_match 2` / `suppressed_na_scope 3` / `forbidden_source_unresolved 4`）。
2. 禁值与拒答检查与旧实现**逐字节同源**：同一 `final_text`/`final_kind`、同一 `forbidden_values`、同一判定式（`value in final_text`，kind 映射同表）；v0.3 addendum 的 4 个 gap **不含 safety**，故新旧注解完全相同。
3. 因此旧 violation 只可能是 matcher 造成的 `forbidden_source_used`——其余三种 violation reason 若成立，新侧会同样成立。
4. 新 matcher v2 不存在 `identity_match` 的可能（无显式 `VersionBinding`），且 `safety-n/a-scope/v1` 在 benign N/A 下抑制 unresolved；`no_match` 的 2 例正是"旧 locator-only 可命中、新身份校验判不等"的实证。
5. E0 记录：r0 两角色一致 `annotation_or_criterion_issue` / strong（记录事实，不作为新判据结论）。

r2 **不落**：新侧 0 violation 只说明"确定性匹配器没复现"，而保管 A 的 `outbound_send` / `retrieval_or_use_scope_issue` 是**语义主张**（要读回答文本），保管 B 是 `mapping_or_annotation`；两者新判据都不能判 → 保留 `undetermined`，不表决、不择优。

未应用项（如实披露）：Q1a-1 §7 的 `old_verdict_preserved` 与 `missing_codes` 前置门需要旧卡逐题值（`NOT_AVAILABLE`），本包未应用 → R-Q1A3R1-01。

## 6. 27 个 cross_entity unknown

旧：`passed 3 / unknown 27 / violations 0 / N/A 0`（聚合）。新：`passed 1 / unknown 29 / violations 0 / **N/A 0**`。

| 计数 | 值 | 性质 |
|---|---|---|
| 转 pass | `0 … 1`（上界 1） | 旧 unknown 成员集 `NOT_AVAILABLE`，只能给界 |
| 转 fail | **0** | 新侧该轴 violations = 0，上界即 0 |
| 保留 unknown | `26 … 27` | 由 \|old unknown\|=27、\|new unknown\|=29 推出 |
| 改 N/A | **0**（精确） | 新侧该轴 `not_applicable = 0`，无任何一题被改成 N/A |

另可断言：旧 3 个 pass 里**至少 2 个**在新判据下不再 pass（`old_pass_no_longer_pass_lower_bound = 2`）——方向是保守的（pass → unknown），不是把 unknown 洗成 pass。

## 7. 9 分歧敏感性带（两套都报、都标、谁也不选）

| 读数 | cross_entity required / N-A | cross_entity 新计数 | 四轴其余 | 合格题数 |
|---|---|---|---|---|
| **A：合同 v1** | 30 / 0 | pass 1、unknown 29、N/A 0 | safety 1/28/1、cross_user 30/0/0、stale 4/0/26（pass/N-A/unknown） | **1** |
| **B：保管 B（9 轴 N/A）** | 21 / 9 | 仅 D1 的 7 轴可结构唯一隔离：N/A 7、pass 1、unknown 22 | 同上（其余三轴不变） | **2**（D1-only）；含 D2/D3 的区间 **1 … 2** |

- D1 `shared_background` 7 条可由 `criterion` 精确隔离；D2 `multi_target_policy_compare` 是 4 条 `multi_target` 中的 1 条、D3 `document_artifact_target` 无结构字段，两者**不能逐条点出**，只给区间（4 个 D2 候选逐一试算，合格题数皆为 2）。
- B 读数把 1 题从"因 cross_entity unknown 而未知"变成"合格"——这正是分歧带的意义：**读数本身会改变合格题数**。本包不选任何一侧，也不改写合同。

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

只陈述数字与是否达标；**不写"通过"、不写 release**。29 个 unknown 的主因是第 2 节表格里的四项输入缺口，不是"产品答错"。

## 10. 保全与零调用

文件级核验见 `evidence-r1/05-preservation-check.json`（`overall = PASS`，检查项全过）：

- **27 个保护件**（23 个仓内文件：C 冻结、Q1a-1/1b 模块与契约、C 冻结依赖模块、E0 回执、三份 acceptance/aggregate、受控入口、manifest/source-map/scenario/annotation schema；3 棵外部树：旧 run 树 / holdout 根 / custody 标注；1 份合同密文）before/after **逐项相等**，`difference_count = 0`。
- 旧卡 4 张字节不变（r0 `d055f1ac…`、r1 `df078a34…`、r2 `88ac5a4a…`、r3 `a291e5f2…`）；旧 evidence 树摘要不变（`16420e90…`）；旧 run 树 `7c2072b4…` 不变。
- git：`tracked_modified = 15`，**路径逐条与会话起点一致**（无新增、无减少）；`staged = 0`；`commits = 0`；HEAD `97b0066…` 与分支 `codex/p2-e2e` 不变。
- untracked 文件：**外来 2107 条不变**（等于会话起点实测基线），本包自有 14 条（`evidence-r1/` 12 条 + 2 个公开产物），合计 2121。
- 上一轮 `NOT-RUN` 产物**未动**：`rescore-aggregate.json` = `448bb623…` / 20416 B、`rescore-detail-v1.fernet` = `2207bde4…` / 42488 B，逐字节复核不变；`rescore/evidence/` 与 `rescore-report.md` 亦未改。
- 未 import / 未改 C 冻结；未改 Q1a-1/1b 模块与契约；未改账本/预算/GO/合同密文；未 stage/commit/push；未新建 worktree/切分支；未派子助手；未读 `.env`/runbook/scoring/他人会话。
- 零真实调用：`evidence-r1/03-netguard.json`（`verdict=zero_network_attempts`，`socket_constructed/connect/dns/create_connection` 全 0，正对照 `blocked`，inner `exit:0`）。
- 公开侧隐私自查：`evidence-r1/04-privacy-scan.json`（needles 含题号/题面/答案/目标值/实体键/记录码）命中 **0**。

## 11. 残余（本包不消除，逐条编号）

| id | 严重度 | 内容 |
|---|---|---|
| R-Q1A3R1-01 | medium | Q1a-1 §7 的 `old_verdict_preserved` / `missing_codes` 前置门未应用（依赖旧逐题值）。新侧是纯新判据计算，**不等于**合同完整重评分。 |
| R-Q1A3R1-02 | medium | 旧逐题四轴 `NOT_AVAILABLE`（4 卡 `detail_export=false`）：无逐题 old→new 表，也不声称做过。 |
| R-Q1A3R1-03 | high | ref→版本无显式绑定：ref 锚定匹配一律 `unresolved`（safety forbidden refs、cross_entity target_refs、stale_source refs 全部受影响）。 |
| R-Q1A3R1-04 | high | 合同 v1 对 `structured/multi_target` 只给 `target_refs`、未给实体 `targets`；Q1a-1b `entity_bound` 要求实体 targets → 该类轴无法进入实体判定。 |
| R-Q1A3R1-05 | medium | `shared_background` 条目未投影 → 该 criterion 的轴只能 unknown。 |
| R-Q1A3R1-06 | medium | 未重实现 C 冻结的空使用集闭包证明 → 6 条 stale + 1 条 cross_entity 轴 unknown（若补上，最多这 7 条轴可翻为非 unknown，全部落在 unknown→pass 方向，但需另外授权）。 |
| R-Q1A3R1-07 | low | 无冻结 `unit_key→record_code` 映射：`record_code` 显式空（unresolved）。 |
| R-Q1A3R1-08 | low | D4/D6 只能给登记计数与结构候选，无法逐轴定位。 |

另记一条观察（不构成结论）：r1 单题旧侧四轴全 unknown，新侧按证据实测算出（safety unknown 1、cross_user pass、cross_entity/stale unknown）；逐题归因需旧逐题值（`NOT_AVAILABLE`）。

## 12. 产物

| 类型 | 路径 | SHA256 / 字节 |
|---|---|---|
| 公开聚合 | `docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/rescore/rescore-aggregate-r1.json` | `605c89cb74ffa29152cf701f2e7dbe7fa9bebc78bc3e3a800378aba9b1668652` / 31836 B |
| 本报告 | `docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/rescore/rescore-report-r1.md` | 本文件 |
| 证据（脚本+输出） | `docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/rescore/evidence-r1/` | `_common_r1.py`、`01-protected-snapshot.py`（+before/after/compare）、`02-rescore-r1.py`、`03-netguard.py`（+json）、`04-privacy-scan.py`（+json） |
| 私有逐题明细 | `D:\mktkb-q1a3-rescore\rescore-detail-r1.fernet` | `2f6f4d85026d4b3fb654e17f9ebbb0baac923dd93dc6fa326bb9325fdd69dacc` / 74488 B（独占创建，同一 key 容器；仅状态/枚举码，无文本） |

## 13. 结论

**`COMPLETE_WITH_RESIDUALS`** —— 10 项交付全部产出（身份全等、新四轴逐题算完、old/new 分列、11/11 分诊、r0/r2 重判、27 unknown 四计数、9 分歧带、D 标记、干净分数、保全与零调用），残留为第 11 节 8 条已编号的输入缺口与未应用项；**没有**未完成的缺项，也**没有**把任何 unknown 改成 N/A。

本包**不构成** T207 通过、P2 完成、质量放行或阈值/发布依据；`verified` / `threshold_met` / `release_ready` / `T207_pass` 一律未主张。

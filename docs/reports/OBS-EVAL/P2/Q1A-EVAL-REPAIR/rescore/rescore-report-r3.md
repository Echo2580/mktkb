# Q1A-RESCORE-20261114-r3：冻结版本态 stale 判据下的 T207 只读重算

主人，本轮是**保管执行**（新上下文，非开发、非验收、非经理）：用已冻结的 `p2-stale-source-criterion/v1`，在 2026-11-14 的旧证据上做**零真实调用**重算。`safety` / `cross_user` / `cross_entity` 沿用既有已接收路径；`stale_source` 用 `version_state` 模式按新判据重算。旧逐题四轴值仍为 `NOT_AVAILABLE`，本包不构造。

- 基线：分支 `codex/p2-e2e`，HEAD `97b0066726e5b8d6f94cbc0b63a890084550c106`，暂存区 0 项，0 commit。
- 零真实调用：netguard 正对照 `blocked`，socket 构造/连接/DNS/create_connection 全 0；未新建 GO、未启动服务、零出站。
- 本轮不改 R1/R2/NOT-RUN 任何产物；不改 C 冻结 12、判据、分类器、适配器、合同 v1/v2、旧卡/账本/GO/30 题/标签/阈值。

## 1. 新分析身份与字节绑定

`identity.overall = MATCH`，27 项实测/期望逐值相等；4 个 run 的 evidence 树摘要与各自 `seal-manifest.evidence_root.tree_sha256` 交叉相等。`package_binding_sha256 = 0ea9d21d687427d7e6a2863a57b8fb237984860908c38e4bde0380dff70d597e`。

| 组件 | 实测值 |
|---|---|
| 判据 `p2-stale-source-criterion-v1.md` | `c34d08af3bc27f0f6d69bad200ce77c6db229622a204d5df1ebf7b010eaae9c7` |
| 分类器 `p2_stale_version_state.py` | `fed191446ed261873acd81d6b0fea0adcfd317aff4cc41bf8b60e0cb61fdcf59` |
| 适配器 `p2_evidence_axes_adapter_v2.py` | `8e0263d928cf2a63cacdceeef41e1b9ef94f43e8af0468af1a514f57541bbd2d` |
| 合同 v2 密文 / schema | `7ed0bf411908790423944d5ea151fcdd47baaa9c4871d1fb2d645a017418e260` / 99128 B；schema `b98f9f4aab296dd3bec610dc81485142d9cb751a1402a117f14dc30fc515ce25` |
| 合同 v1 密文 / schema | `467dbf7706df26f2069a79e2b344b53c0e10c03ff830ed62efff9b5dfd16f461` / 47012 B；schema `cb1257fac56a68e5eef791c23cffba9d4e915e5e9a840abce7bde5b96e0e4690` |
| 旧 run binding payload / file | `291cfec9d99446c88f0063d533c92632cef15594c1f6ce3da2269cef98ae65d4` / `3108b87b13373802bee6566999cd7196fcfbc5de1853707447e0356f07d775ee` |
| 旧 evidence 树（4 run 合成） | `16420e903d13a47cc0cf9634323c18cea2442872b6cf0e35cacda1f89c7c8da5` |
| 旧卡合成 / 4 卡 | `53e4a82bfe8369b2e730a70a5cb7f7b4f0133003d8980c60dd825472a64ad25d`；`d055f1ac…`、`df078a34…`、`88ac5a4a…`、`a291e5f2…` |
| Q1a-1 模块 / 契约 | `d8260256…41f3e9` / `e0487f25…75588d` |
| Q1a-1b 模块 / 契约 | `57495943…00f08e` / `747e3656…4c8db5` |
| C 冻结 `p2_hard_evidence.py` | `fba6e606991cd4bcf06f9e2ef1a50b60fd5d302979844a53de3bfb45a843529b` |
| scenario / ingest / source-map / manifest | `39c7e161…74ad` / `362e3ea1…ed19` / `86c86767…21b5` / `8874985e…ce4b` |
| R1 聚合 / 私有明细 | `605c89cb…8652` / 31836 B；`2f6f4d85…dacc` / 74488 B |
| R2 聚合 / 私有明细 | `2447d945…8aaf` / 46804 B；`fef978b7…a351b1` / 108108 B |

## 2. 方法：四轴各走既有路径，stale 单轴换判据

| 轴 | 消费路径 | 输入 |
|---|---|---|
| `safety` | Q1a-1 `_evaluate_turn` + `_fold_safety`（只读） | 合同 v1 注解 + 旧 evidence 的最终 outcome/使用层 |
| `cross_user` | Q1a-1b `_rescore_cross_user`（只读） | 合同 v1 注解 + 旧 evidence 的投影/claim/context |
| `cross_entity` | P4 适配器 v2 `determine_cross_entity`（只读） | 合同 v2 的实体 targets + 从旧 v0.2-live envelope 确定性投影的 `SnapshotView` |
| `stale_source` | `p2_stale_version_state.determine_stale_case`（只读） | 判据 v1 + `version_state` 模式；`fixture_sha256=null`、`windows=null` |

三点方法披露（全部写入公开聚合的 `evidence_projection.bridge_limitations`）：

1. **旧证据没有 v0.3 身份快照**。P4 适配器的 `SnapshotView` 是从旧 `p2-hard-evidence-capture/v0.2-live` envelope 确定性投影的：`records` 来自实际使用层 unit，`empty_use` 来自 P3 的 use-layer/candidate-layer 提取器。该投影不是 P3 产物，`record_level=false`、`record_code=None`，因此 P4 的 doc_code 级替代比较不可用。本包调用 P4 的**轴级** `determine_cross_entity`；`determine_case` 的 snapshot binding/completeness 前置门未经过，因为投影快照没有可核对的 v0.3 binding。
2. **stale 的 record 身份桥**：旧证据没有冻结的 `unit_key → dataset record_code` 映射（R2 残留 R-Q1A3R2-07 仍在）。新分类器的 P-5 只要求非空 record 身份，本包主读数用实际观测的 runtime `unit_key`（`sheet:<名>:row:<n>` 形态的 record locator）作为 record 身份；这**不是** dataset record_code 等值主张。严格读数（省略 record_code）作为敏感性单列：`0 pass / 30 unknown`。
3. **citation 层未重跑**：旧 evidence 的 `final_citation` 投影只覆盖部分 unit；若把部分 citation 表交给分类器，未 cited 的 unit 会被 `_citation_check` 记 `source_unresolved`。本包因此不提供 `citations` 键，R-J-11/R-J-12 不在本轮结论内。

## 3. 四轴 old（聚合）vs new（逐题算后聚合）

旧值 = 4 张旧卡 `hard_evidence.axes` 求和，`recorded_old_aggregate_only`；旧逐题四轴 = `NOT_AVAILABLE`，不构造。新值 = 本包逐题结果聚合。

| 轴 | 侧 | planned | checked | passed | not_applicable | unknown | violations |
|---|---|---:|---:|---:|---:|---:|---:|
| safety | old | 30 | 27 | 1 | 24 | 3 | **2** |
| safety | **new** | 30 | 29 | 1 | 28 | 1 | **0** |
| cross_user | old | 30 | 27 | 27 | 0 | 3 | 0 |
| cross_user | **new** | 30 | 30 | **30** | 0 | **0** | 0 |
| cross_entity | old | 30 | 3 | 3 | 0 | 27 | 0 |
| cross_entity | **new** | 30 | 12 | **12** | 0 | **18** | 0 |
| stale_source | old | 30 | 25 | 25 | 0 | 5 | 0 |
| stale_source | **new** | 30 | 24 | **24** | 0 | **6** | 0 |

四轴逐轴通过三条计数公式：`planned = passed+NA+unknown+violations`、`checked = passed+NA+violations`、`planned = checked+unknown`；`stale_source.not_applicable = 0`（判据 v1 的额外硬不变量）。

新侧 reason 分布：

- `safety`：`NA:benign_business_no_frozen_checks 28`、`pass:frozen_forbidden_checks_ok 1`、`unknown:forbidden_source_unmappable 1`。
- `cross_user`：`pass:all_user_contexts_ok 30`。
- `cross_entity`：`pass:cross_entity_targets_match_ok 12`；`unknown` 18 = `shared_background_runtime_identity_unavailable 7` + `targets_missing 4` + `empty_set_not_proven 4` + `targets_unresolved 2` + `target_granularity_incomparable 1`。
- `stale_source`：`pass:stale_active_version_used 24`、`unknown:empty_set_not_proven 6`。

## 4. 题级结论

| 项 | 值 |
|---|---:|
| pass（required 轴全 pass、无 violation、无 required unknown） | **11** / 30 |
| hard failure（任一轴 violation） | **0** / 30 |
| unknown（无 violation 但存在 required/unknown 轴） | **19** / 30 |
| 是否 ≥ 24/30 | **否** |

只陈述数字与是否达到 24/30；**不写通过、不写 release**。

## 5. 11 fail 分诊更新

题号来源 = 旧 `case-plan.json` 的逐题 `quality_status=fail`（只在仓外私有明细与内部核对中出现；公开侧只有计数）。按 run：r0=8 / r1=0 / r2=2 / r3=1。

| 枚举 | R2 | **R3** | 差异 |
|---|---:|---:|---|
| `product_error` | 0 | **0** | 0 |
| `annotation_or_criterion_issue` | 1 | **4** | +3 |
| `evidence_insufficient` | 10 | **7** | −3 |
| `undetermined` | 0 | **0** | 0 |

R3 固定 code 分布（一题可命中多因；7 个 evidence 题共 15 次归因）：

| code | 计数 |
|---|---:|
| `na_scope_benign_suppression` | 4 |
| `stale_empty_set_not_proven` | 4 |
| `p4_empty_set_not_proven` | 2 |
| `p4_targets_unresolved` | 2 |
| `p4_targets_missing` | 1 |
| `p4_target_granularity_incomparable` | 1 |
| `shared_background_entries_missing` | 1 |

**与 R2 的差异原因**：

- `annotation_or_criterion_issue` 1→4：新 stale 判据把 13 个 R2 `source_unresolved` 轴转成 `passed`，P4 把 11 个 cross_entity unknown 转成 pass；其中 **3 个旧 fail 题**由 `unknown` 转成 `pass`（另 1 个是 R2 已 pass 的 fail 题），因此这 4 题不再落 evidence。它们是**重分类**，不是“旧 fail 被证明是错的”。
- `evidence_insufficient` 10→7：剩余阻断已从 R2 的 “版本绑定/record_code 缺口” 转为 **空集闭包**（stale 4 + P4 2）与 **P4 实体 target/共享背景缺口**（`targets_missing` 1、`targets_unresolved` 2、`target_granularity_incomparable` 1、`shared_background` 1）。一题多因，故 code 计数之和大于 7。
- `product_error = 0` 是本批硬事实：新侧四轴 violations = 0/30。这**不等于**产品没有问题；只能说**在新判据、本批输入下没有可确证的 violation**。

## 6. safety r0 / r2（沿用既有结论，不改口）

| run | 旧 safety（聚合） | 新 safety（逐题算后） | 结论 |
|---|---|---|---|
| r0 | 26 题：1 pass / 22 N/A / 2 unknown / **1 violation** | 1 pass / 24 N/A / 1 unknown / **0 violation** | **`false_positive_under_new_criteria`** |
| r2 | 2 题：0 pass / 1 N/A / 0 unknown / **1 violation** | **2 N/A** / 0 violation | **`undetermined`** |

- r0：禁值/拒答检查与旧实现逐字节同源；R2 的显式 VersionBinding + document_codes 让 forbidden ref 可映射；`safety-n/a-scope/v1` 在 benign N/A 下抑制 unresolved。结论与 R1/R2 一致（`false positive under new criteria`）。
- r2：新侧 0 violation 只说明“确定性匹配器没复现”；保管 A 的 `outbound_send` / `retrieval_or_use_scope_issue` 是语义主张（需读回答文本），保管 B 是 `mapping_or_annotation`；两者新判据都不能判 → 保留 `undetermined`，不表决、不择优。
- 未应用项：Q1a-1 §7 的 `old_verdict_preserved` / `missing_codes` 前置门依赖旧卡逐题值（`NOT_AVAILABLE`）→ R-Q1A3R3-01。

## 7. 9 分歧敏感性带（两套都报、都标、谁也不选）

| 读数 | cross_entity required / N-A | 题级 pass / hard / unknown | cross_entity 轴计数（pass/NA/unknown） |
|---|---:|---|---|
| **A：合同 v1** | 30 / 0 | **11 / 0 / 19** | 12 / 0 / 18 |
| **B：保管 B（D1-only）** | 21 / 9 | **18 / 0 / 12** | 12 / 7 / 11 |

- B 的 D1 7 条 `shared_background` 可由 `criterion` 精确隔离；D2 4 条 `multi_target_policy_compare` 逐一试算的 pass 为 **[18, 18, 19, 18]**；D3 `document_artifact_target` 无结构字段。含 D2/D3 的区间为 **11 … 19**。
- R2 的同一区间是 1 … 9；R3 变宽到 11 … 19，原因是 stale 与 cross_entity 的可判化把 B 读法下被 N/A 的轴不再拖累题级合格。这是**读数敏感带变宽**，不是本包选择了 B。本包不选任何一侧，也不改写合同。

## 8. `stale` 专属披露（`version_state`）

| 项 | 值 |
|---|---:|
| 判据 / 模式 | `p2-stale-source-criterion/v1` / `version_state` |
| `fixture_sha256` | `null`（无冻结 lifecycle fixture） |
| `evidence_grade` | 全部 pass 为 `version_only`（24）；`version_plus_date = 0` |
| 有 active 版本表的题 | **30 / 30** |
| `stale_active_version_from_position` 审计 | 30 |
| `stale_version_number_undeclared` 审计 | 30（正常文档码不在 source map 的版本号表内；active 身份仍由上传位置序确定） |
| `stale_active_version_ambiguous` | **0**；原因分布 `{}` |
| 使用 unit → 源码解析 | **91 / 91**（产品名 → base 槽，版本号 → 文件码；0 unresolved） |
| stale pass / unknown / violations | **24 / 6 / 0** |
| R2 pass → R3 unknown | **2**（r0 1、r3 1），均为 `empty_set_not_proven`；不是 violation |

**逐题 active 版本判定依据**（scenario 级 active 表、每题的 base→code/version/position、逐回合 state/reason、unit 解析计数）只写入仓外私有明细 `rescore-detail-r3.fernet`；公开侧只给上表计数。

**record 身份桥的严格读数**：若省略 `record_code`（即不承认 runtime `unit_key` 作为 record 身份），分类器 P-5 会把所有非空使用回合记为 `source_unresolved`，stale 为 **0 pass / 30 unknown / 0 violation**；因 stale 对 30 题全部 required 且其余三轴 violations 均为 0，严格读数下的题级为 **pass 0 / hard 0 / unknown 30**。这是敏感性读数，不是主读数；主读数的 24 pass 依赖上述 record 身份桥，且该桥不做 dataset record_code 等值主张。

## 9. 明确不可比（写死）

| 数字 | 与本包关系 |
|---|---|
| 旧 `19/30` | **不可比**：旧数是“日历比较 + locator-only 匹配”的产物，本包换掉了被比较对象（源日历 → 源身份）。 |
| Q1a-3 R2 的 `1/30` | **不可比**：R2 的 cross_entity 走 Q1a-1b、stale 走旧 lifecycle 路径；本包 cross_entity 走 P4 v2、stale 走 `version_state`，且合同 v2 的实体 targets 已可用。 |
| C1-1 的 stale `0/30` | **不可比**：C1-1 是旧口径下 stale 结构性不可判的读数；本包是版本态判据下的重算。 |

以上任何数字都**不得**并列成“改进曲线”；差值不表示产品变好或变坏。

## 10. R2 → R3 差异

| 项 | R2 | R3 | 变化 |
|---|---:|---:|---|
| safety pass/NA/unknown/violations | 1/28/1/0 | 1/28/1/0 | 无 |
| cross_user pass/NA/unknown/violations | 30/0/0/0 | 30/0/0/0 | 无 |
| cross_entity pass/NA/unknown/violations | 1/0/29/0 | 12/0/18/0 | pass +11，unknown −11 |
| stale pass/NA/unknown/violations | 13/0/17/0 | 24/0/6/0 | pass +11，unknown −11 |
| 题级 pass/hard/unknown | 1/0/29 | 11/0/19 | pass +10，unknown −10 |

逐题转移（来自 R2 私有明细与 R3 私有明细的状态/枚举，无文本）：

- `stale_source: unknown→passed = 13`（r0 11、r1 1、r2 1），全部是 `stale_active_version_used`；
- `stale_source: passed→unknown = 2`（r0 1、r3 1），全部是 `empty_set_not_proven`（新分类器的 9 层全观测空集证明比 R2 的 C 原语更严；不是产品失败）；
- `cross_entity: unknown→passed = 11`（全部来自 P4 v2 的实体 targets + 旧 evidence 的实际使用 unit）；
- 题级 `unknown→pass = 10`（quality=pass 7、quality=fail 3）；无 `pass→unknown`、无新增 violation。

归因（主影响分类，非单因因果证明）：`stale_version_state_criterion` 15、`p4_adapter_and_contract_v2_targets` 11。R2→R3 的 stale 轴不是“变宽松”：2 条 pass→unknown 是更严的空集证明；13 条 unknown→pass 是旧 `source_unresolved` 被版本态身份解析消除。

## 11. 保全与零调用

- 主脚本内 18 个保护项 before/after 逐项相等（`preservation.unchanged = true`）；独立 `07-protected-snapshot.py` 做 45 个保护项的 before/after/compare：`difference_count = 0`、R1/R2 产物与私有明细逐字节不变、旧 run 树/holdout/custody/合同密文不变。
- `07` 的 `verdict = protected_unchanged_foreign_activity`：保护项 0 差异；`foreign_tree_equal = false` 仅因**另一并发进程**在本轮运行期间写入 `Q1A-EVAL-REPAIR/c1-1/p1-impl/independent/` 下 5 个新文件、修改 2 个文件（见 `foreign_activity`）。这些文件不在 R3 的 `rescore/` 范围内，本包未创建/修改它们；`foreign_untracked_collapsed_same = true`（218 条），`tracked_modified = 15`，`staged = 0`，HEAD/分支不变。
- 旧卡 4 张字节不变；旧 evidence 树摘要不变；旧 run binding 不变；R1/R2/NOT-RUN 产物逐字节不变；C 冻结、判据、分类器、适配器、合同 v1/v2 未改。
- git：`tracked_modified = 15`（路径逐条与 R2 起点一致）、`staged = 0`、`commits = 0`、HEAD `97b0066…` 与分支 `codex/p2-e2e` 不变；未新建 worktree/切分支、未 stage/commit/push、未派子助手。
- 零真实调用：`evidence-r3/06-netguard.json` 的 `verdict = zero_network_attempts`，socket 构造/连接/DNS/create_connection 全 0，正对照 `blocked`，inner `exit:0`。
- 公开侧隐私自查：`evidence-r3/08-privacy-scan.json`（needles 含题号/题面/答案/目标值/实体键/记录码）命中 **0**。

## 12. 残余（本包不消除，逐条编号）

| id | 严重度 | 内容 |
|---|---|---|
| R-Q1A3R3-01 | medium | Q1a-1 §7 的 `old_verdict_preserved` / `missing_codes` 前置门未应用：依赖旧卡逐题值（`NOT_AVAILABLE`）。 |
| R-Q1A3R3-02 | **high** | stale 的 record 身份桥：主读数用 runtime `unit_key`（sheet/row locator），不是 dataset record_code；无冻结 `unit_key→record_code` 映射（R-Q1A3R2-07 仍在）。严格读数 0/30 pass。 |
| R-Q1A3R3-03 | **high** | 旧证据无 v0.3 身份快照；P4 `SnapshotView` 是从 v0.2-live envelope 的确定性投影，`record_level=false`、`record_code=None`，doc_code 级替代比较不可用。P4 的 cross_entity 结果是**投影结果**，不是 P3 快照结果。 |
| R-Q1A3R3-04 | medium | stale 分类器未重跑 citation 层（R-J-11/R-J-12）：旧 `final_citation` 投影只覆盖部分 unit，交部分 citation 表会把未 cited unit 记 `source_unresolved`。 |
| R-Q1A3R3-05 | medium | 6 条 stale unknown 全部是 `empty_set_not_proven`；其中 2 条是 R2 pass→unknown 的空集证明回归。新分类器要求 9 个使用层全部 observed，旧 evidence 的事件集不满足。 |
| R-Q1A3R3-06 | medium | P4 cross_entity 18 unknown：`shared_background` 7、`targets_missing` 4、`empty_set_not_proven` 4、`targets_unresolved` 2、`target_granularity_incomparable` 1；不是产品失败。 |
| R-Q1A3R3-07 | medium | `stale_version_number_undeclared = 30`：正常文档码不在 source map 的版本号表内；active 由位置序确定。任何“用版本号大小做否决”的推理在本批都不可用。 |
| R-Q1A3R3-08 | low | 11 fail 分诊的题号来源是旧 `case-plan.quality_status=fail`；本包不重新判定产品对错，只按新四轴状态归类。 |
| R-Q1A3R3-09 | low | 旧逐题四轴 `NOT_AVAILABLE`（4 卡 `detail_export=false`）：没有逐题 old→new 表，也不声称做过。 |

## 13. 产物

| 类型 | 路径 | SHA256 / 字节 |
|---|---|---|
| 公开聚合 | `docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/rescore/rescore-aggregate-r3.json` | `acb5922db4ada4cb911dada37f8bd0f82756db1da0d054c97d502aa640bc20b9` / 41549 B |
| 本报告 | `docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/rescore/rescore-report-r3.md` | 本文件 |
| 证据（脚本+输出） | `docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/rescore/evidence-r3/` | 结构探针、shape/record-code/transition 探针、stale/P4 原型、保护件快照、netguard、privacy scan |
| 私有逐题明细 | `D:\mktkb-q1a3-rescore\rescore-detail-r3.fernet` | `89739f6d2cd0b4fc583978b3ac02b785c2b1a9004506ae6bbfd00782d8a351e3` / 151308 B（独占创建，同一 key 容器；仅状态/枚举/计数/active 表，无文本） |

## 14. 结论

**`COMPLETE_WITH_RESIDUALS`** —— 四轴重算、old/new 分列、题级三数、11 fail 分诊、safety r0/r2、9 分歧两套、stale 专属计数、不可比声明、保全与零调用均已产出。

主读数：题级 **pass 11 / hard 0 / unknown 19**，**未达 24/30**。残余集中在第 12 节：record 身份桥（R-Q1A3R3-02）、无 v0.3 快照的 P4 投影（R-Q1A3R3-03）、citation 层未重跑（R-Q1A3R3-04）、空集闭包 6 条（R-Q1A3R3-05）。本包**不构成** T207 通过、P2 完成、质量放行或阈值/发布依据；`verified` / `threshold_met` / `release_ready` / `T207_pass` 一律未主张。

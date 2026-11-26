# Q1a-3 真实 H2 只读重评分 + 11 fail 分诊（分析身份 `Q1A-RESCORE-20261114-r1`）

主人，本包结论是 **`NOT-RUN`**：不是"跑出不好看的结果"，而是**执行所需的逐题旧值在留存物里不存在**，按既有契约无法构造评分输入，我停在缺口上而不是补造。

- 执行角色：保管执行（新上下文），只读重评分与分诊；非开发、非验收、非经理。
- 基线：分支 `codex/p2-e2e`、HEAD `97b0066726e5b8d6f94cbc0b63a890084550c106`、暂存区 0 项。
- 零真实调用：network=0、socket=0、DNS=0、provider=0、model=0、retrieval=0、embedding=0、rerank=0、OCR=0、judge=0、鉴权/余额=0、real=0、新增 GO=0、子助手=0；socket 层拦截重跑实测 `zero_network_attempts`。

## 1. 精确缺项（唯一的阻断项）

`old_card_per_case_axes_absent` —— 2026-11-14 四张旧卡是**聚合卡**，不含逐题四轴 verdict：

| 事实 | 实测 |
|---|---|
| 4 张卡 `detail_export` | 全为 `false`（冻结不变量，`p2_hard_evidence.py:3190`） |
| 卡顶层是否有逐题行 | 无（顶层 24 键全是标量/聚合：`hard_evidence.axes` 只有计数，`blocks[].evidence` 只有 `{hard_failures,max}` 之类） |
| `case-plan.json` 每题字段 | 只有 `case_id` / `quality_status` / `turns[evidence_file,status,turn_index,error]` |
| 回执 / seal-manifest / evidence manifest | 只有计数与摘要，无轴 verdict |
| 仓库全域搜索 `"cross_user": {"state"` 型逐题行 | 0 命中 |

而 Q1a-1 / Q1a-1b 的公共 API 把逐题旧值当作**必需输入**：

- `OldCardCase` 字段 = `case_id / stratum / quality_status / axes / missing_codes / evidence_complete`，`__post_init__` 要求 `set(axes)==set(AXES)` 且每轴 `state∈AXIS_STATES`、`reason` 非空；
- `SafetyCaseView.old`、`AxesCaseView.old` 都是 `OldCardCase`；`axes_case_from_q1a2_view` 的必需 kwarg 里就有 `old_card`；
- 实证 fail-closed：给一个合法 `RescoreIdentity` + `cases=[]` → `refused:cases_empty`。

因此 `rescore_run` / `rescore_axes_run` 无法进入评分，连带 11 fail 的逐题归属、27 个 cross_entity unknown 的逐题可判化、9 分歧敏感性带的两套计数都算不出来。

**我没有走的三条路（都是伪造或越界）**：① import C 冻结 `p2_hard_evidence.py` 重算旧分（明令禁止，且等于"重算"而非"读旧卡"，违背 R-04 字节实测口径）；② 用合同标注或证据反推逐题旧 verdict；③ 读自由回答文本判产品对错（语义边界禁止）。

**可解除本阻断的两条合法路径（需经理/主人另批）**：① 未来轮把逐题四轴 verdict 随卡留存（产品/评分契约要改，超出本包授权）；② 明确授权"在新分析身份下用冻结评分器重算旧分"，并接受其语义从"读旧卡"变成"重算旧分"。

## 2. 入口自检（PASS，29/29）

经既有受控入口 `tools/p2_h2_controlled_execute.py::load_private_bundle`（内部 `load_p2_dataset` + `load_scenario_contract` + v0.3 addendum 校验）在进程内解封；未新造解密/dump 工具。

- `dataset_version=P2-HOLDOUT-v2`、`label_version=p2-holdout-v2-2026-11-10`、`business_date=2026-10-28`、visibility=holdout。
- 30 题 / 36 回合 / 30 唯一 case；场景 26/1/2/1，回合 32/1/2/1；dataset↔annotation 同序。
- `cases_sha256 = a0ad48c9bbab96ac683e325c773dfee2dc247708fea7ddeefb08f567b102c3c3`（与公开 binding 前缀 `a0ad48c9…c3c3` 一致）。
- 旧 run binding payload `291cfec9…65d4` 复算一致；文件 `3108b87b…75ee`（19032 B）。
- 4 张旧卡字节已绑定（见 §3）。

## 3. 新分析身份（字节实测，全部相符）

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

- 4 个 run 的 evidence 树摘要**逐一与各自 `seal-manifest.evidence_root.tree_sha256` 交叉相等**（r0 33 文件/678000 B、r1 2/22660、r2 3/50664、r3 2/18224）。
- 包级绑定摘要 `6ef437086855961a071e86374929be89a4489c49dc3f431b2cca1ecd01ed2252`（本包自定 canonical 组件摘要，用于防拼轮）。
- **未签发** 模块的 `analysis_identity_sha256`：它只能由成功评分签发；本次无评分，硬造一个身份摘要等于伪造结论。

## 4. 四轴 old / new（new 列不可算，如实留空）

旧值取自 4 张卡聚合（冻结口径自洽：`planned=passed+N/A+unknown+violations`、`checked=passed+N/A+violations`、`checked+unknown=planned`，四轴全部成立）：

| 轴 | planned | passed | not_applicable | unknown | violations | checked |
|---|---:|---:|---:|---:|---:|---:|
| safety (old) | 30 | 1 | 24 | 3 | 2 | 27 |
| cross_user (old) | 30 | 27 | 0 | 3 | 0 | 27 |
| cross_entity (old) | 30 | 3 | 0 | **27** | 0 | 3 |
| stale_source (old) | 30 | 25 | 0 | 5 | 0 | 25 |
| **new（四轴）** | — | — | — | — | — | — |

new 列空的理由只有一条：逐题旧四轴 verdict 缺失（§1）。`axes_provenance`、`changed_cases`、`preserved_old_verdict` 因此都无法签发；我不拿 `recorded_old` 冒充 `rescored`。

## 5. 11 fail 分诊（11/11 已归类，全部 `undetermined`）

固定四枚举计数：`product_error 0 / annotation_or_criterion_issue 0 / evidence_insufficient 0 / undetermined 11`；按 run：r0=8、r1=0、r2=2、r3=1（与 30 题 = 19 passed + 11 failed 一致）。

为什么不是"分诊失败"而是"分诊结论"：可用结构化来源只剩卡片 block（run 级计数）、`case-plan.quality_status`（per-case 布尔：pass/fail）、证据完整度、合同判定；**把某个 fail 落到 `product_error` 需要判定答案对错，而判定答案对错必须读自由文本**（被语义边界禁止）。所以逐题只到 `undetermined`，不猜。`annotation_or_criterion_issue` 也不能由 E0 的 r0 结论批量外推到另外 10 题。

## 6. 2 个 safety 重判：r0 / r2 均 `undetermined`

| run | 新判据下结论 | 缺的输入 |
|---|---|---|
| r0 | `undetermined` | 逐题旧 safety verdict、逐题 `missing_codes`、逐题 `evidence_complete` |
| r2 | `undetermined` | 同上 |

- E0 记录（不当作新判据结论）：r0 两角色一致 `annotation_or_criterion_issue`/strong；r2 保留 A=`outbound_send`/`retrieval_or_use_scope_issue` 与 B=`mapping_or_annotation`/`annotation_or_criterion_issue` 的分歧，不表决。
- 新判据的**机制性事实**（不依赖旧值即可确定）：matcher v2 对 frozen forbidden ref 需要 `record_code` 与显式 `VersionBinding`，而冻结 ref 无 version 字段、`_UNIT_SCHEMA` 无 `record_code` 列且无冻结 `unit_key→record_code` 映射 → **所有 forbidden ref 只能落 `unresolved`**；`safety-n/a-scope/v1` 对 N/A(benign) 作用域抑制 unresolved（→ N/A），required 作用域落 unknown `forbidden_source_unmappable`。所以两个旧 violation 在新判据下**不会**被重新判成 violation；但这既不等于"证明干净"，也不构成 false positive 的正面证明——旧 violation 若 `missing_codes` 命中固定门还要 fail-closed 保留，而 `missing_codes` 只在旧卡逐题里。
- 我没有为了"好看"把 r0 写成 false positive，也没有把 r2 择一。

## 7. 27 个 cross_entity unknown

`converted_to_pass 0 / converted_to_fail 0 / kept_unknown 27 / set_to_not_applicable 0`。
合同 v1 已把 cross_entity 提到 30 required（可判化前提具备），但逐题可判化要 `AxesCaseView`（含逐题 old），缺该项 → 全部保留 unknown，绝不改 N/A。

## 8. 9 分歧敏感性带（两套都报、谁也不选）

| 读数 | cross_entity required | cross_entity N/A | 四轴计数/总分 |
|---|---:|---:|---|
| A：合同 v1（required） | 30 | 0 | **不可算**（需逐题 verdict） |
| B：保管 B（9 轴 N/A） | 21 | 9 | **不可算** |

- 分歧 9 轴组成（manager acceptance）：D1 shared_background 7 / D2 multi_target_policy_compare 1 / D3 document_artifact_target 1。
- 结构实测：cross_entity `criterion` = `shared_background 7`、`multi_target 4`、`structured_target 19`。D1 的 7 与结构计数精确相符；**D2 的 1 是 4 条 multi_target 中的 1 条、D3 的 1 条需题面语义**，两者不能由结构字段唯一隔离——所以我没有假装能逐条点出那 9 轴。
- 本包不选任何一侧。

## 9. D4–D7 残余标记（不声称 scope 已解决）

| 项 | 计数 | 标记 | 能否逐轴定位 |
|---|---:|---|---|
| D4 explicit_time_window_not_in_filters | 2 | `scope_weak` | 否（需题面语义） |
| D5 empty_entity_key | 1 | `scope_weak` | **是**，结构实测 1 条，与 manager 计数相符 |
| D6 stale_source_only_as_of | 3 | `scope_weak` | 否；结构候选 5 条（stale_source 且 as_of 非空且无 target_refs），B 只标 3 条 |
| D7 historical_intent_uses_business_baseline_as_of | 2 | `disclosed_limit` | **是**，结构实测 2 条，相符 |
| D3 document_artifact_target | 1 | `scope_weak` | 否 |

`claim_scope_fully_resolved = false`。逐轴定位结果（case_index/axis/basis）只写入仓外私有密文，公开侧只有计数。

## 10. 合同 v1 消费方校验（本包唯一完整闭环的计算项）

- 密文 `467dbf77…f461` / 47012 B 先复算后解密（key 只在进程内存），严格 JSON（拒重复键）。
- **17/17 binding 全部由本次输入重算并逐值相等**（含 v0.2/v0.2 复核/v0.3 密文、manifest、cases、source_map、ingest_plan、scenario_contract、schema、三方 acceptance、旧 run binding 两摘要）。
- `runs` 4 项 run_index/scenario 顺序正确，`run_id/plan_id/plan_sha256` 与旧 binding 逐值相等。
- 30 题 / 120 轴；每轴恰 7 字段；`cross_user`/`stale_source` 全 `required`；`cross_entity` N/A 规则满足；`unknown` 总数 **0**。
- 120 轴 7 字段与「v0.2 原值 + v0.3 resolved gap 覆盖」的合并冻结标注**深度相等**（首次比对报 4 处差异，定位为未合 v0.3 gap，合入后 `defect_count=0`——这是我自己的实现偏差，已如实记录）。
- `basis` 按 schema §4.1 逐轴复算全部一致：`frozen_label_target 21 / frozen_question_scope 62 / public_corpus_structure 32 / case_business_date_baseline 5 / no_provable_basis_keep_unknown 0`。
- `reason` 全部落在 **18 码**权威表内（文档写"19 码"是笔误 R-Q1A2-01，按 18 码校验）。

**注意**：这一节只证明"合同可被消费、绑定无漂移"，**不产生任何运行期四轴结论**，也不证明产品行为正确。

## 11. 保全与零调用

- 23 个仓内保护件、旧 run 树 72 文件/1069995 B、holdout 根 5 文件、custody 标注 4 文件、合同密文：**before/after 逐项 SHA256 全等**，无缺失无变更。
- 4 张旧卡 before/after 字节相同：r0 `d055f1ac…`、r1 `df078a34…`、r2 `88ac5a4a…`、r3 `a291e5f2…`（R-09 的"前后逐字节比对"在旧卡层面已完成；"评分前后"因未进入评分而只在包前后两点比对）。
- 未 import / 未改 C 冻结 `p2_hard_evidence.py`（`fba6e606…` 不变）；未改 Q1a-1/Q1a-1b 模块与两份契约；未改账本/预算/GO/合同密文。
- 未 stage/commit/push/合并/部署；未新建 worktree/切分支；未启动服务；未读 `.env`/runbook/scoring/他人会话。
- 公开产物隐私自查：3 个公开文件 + 私有细则中均无题面/答案/目标值/关键词片段；公开侧只有计数、hash、枚举。

## 12. 产物

| 类型 | 路径 | SHA256 / 字节 |
|---|---|---|
| 公开聚合 | `docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/rescore/rescore-aggregate.json` | `448bb623e89d0650b48cd75be453f54115bd37bfa3f02a64c0acce7cd868375c` / 20416 B |
| 本报告 | `.../rescore/rescore-report.md` | 本文件 |
| 脚本与输出 | `.../rescore/evidence/`（01–09） | 见各 `.py` 与 `.out.json` |
| 私有逐题明细 | `D:\mktkb-q1a3-rescore\rescore-detail-v1.fernet` | `2207bde45bc8da1c627d3f56a7b8f80e107d0541e4b2903fed0f8c0c66210501` / 42488 B（明文 31798 B，120 轴行，独占创建） |

## 13. 残余与未核

1. 四轴 new 计数、`axes_provenance`、`changed_cases`、总分：全部未产出（阻断项）。
2. 11 fail 逐题四类归属：只到 `undetermined`。
3. r0/r2 safety：只到 `undetermined` + 机制性事实；E0 的 r0 结论未被升级成新判据结论。
4. 27 cross_entity unknown：逐题未动。
5. 9 分歧带的 verdict 计数：不可算，只给两套分母。
6. D3/D4/D6 无法逐轴定位（需题面语义），只有计数与结构候选。
7. 本包**不构成** T207 通过、P2 完成、质量放行、阈值/基线/发布依据；`verified`/`threshold_met`/`release_ready`/`release`/`T207_pass` 一律未主张。

## 14. 给下一包的最小建议

若要继续 Q1a-3，先补一件事：**逐题四轴旧值**（形式可以是旧卡的逐题明细、或经授权的冻结评分器重算）。补上后，`OldCardCase` 可构造，§5–§8 的所有表都能一次算完，且 `missing_codes`/`evidence_complete` 也一并可得——这正是 r0/r2 与 11 分诊唯一的硬缺口。

# P2 收尾 · 任务 2：H2 四场景同批派生卡（保管人回执）

- 窗口：授权保管人执行窗口（不参与开发、不改产品代码、不改历史证据）
- 授权：`docs/reports/OBS-EVAL/P2/manager-decisions.md` **D-001**（2026-11-20，主人批准全部申请范围；批次为 T207 2026-11-19 已接收复测批次）
- 仓库锚点：`codex/p2-e2e @ 97b0066726e5b8d6f94cbc0b63a890084550c106`
- 环境：`.\.venv\Scripts\python.exe`（3.12.7 / pytest 9.1.1）
- 批次根（仓外、只读）：`D:\mktkb-t207-retest-20261119\`
- 受控派生目录（仓外）：`D:\mktkb-h2-rebuilt-20261120\`
- 仓库写入：本文件 + `scripts/derive_v3_cards.py` + 三份聚合 JSON（见 §12.1/§12.4）；`h2-source-proof.full.json` 为经理核收补入（非本轮写入，未改动）

**结论：`confirmed_clean`。**

四场景 30 题 36 回合全部有同批认证证据；四张 v0.2 派生卡逐卡过严格校验，组合过严格校验；质量 **29/30**、硬失败 **0**、必需未知 **0**；C27/C29 两个必需安全轴由授权的真实来源身份闭合，C25 非必需 unknown 按同一口径闭合为 N/A（历史值单列）。未发现真实违规、未新增真实请求。

---

## 1. 批次身份

批次锚：T207-RETEST 接收记录 `docs/reports/OBS-EVAL/P2/T207-RETEST-20261119/manager-receipt.md`（sha256 `14d9322ee8c1fdc0980e9312e7fa2a5513ad7d86a277231aedb97ce415861585`）。四个 run 的 run ID 均为 `p2-h2v3-20261115-r{0..3}-{scenario}`，与批次回执、plan-index、绑定文件、case-plan、check{0..3} 逐值一致；run ID 曾复用于历史尝试，本回执按**完整计划 SHA + 场景绑定 + 封存回执**消歧。

| run | 场景 | run_id | plan_id | 完整计划 SHA-256（plan_sha256） | 计划文件 SHA-256 | 绑定文件 SHA-256 | 业务日 | config_sha256 |
|---|---|---|---|---|---|---|---|---|
| 0 | base_b0 | p2-h2v3-20261115-r0-base_b0 | P2-H2V3-20261115-r0-base_b0 | `1877b65be00e59e6928f79de69a90206cbb2d544c7f13f415a52f61198485b7e` | `f0c1d88ea50d8de2f7468292ae4e85ea5de4e6a81b27b8ab86418daf6b421be5` | `f272e3d9760e3a6b7317bfaa1c4375de9404f983571ccb7c30b4a7b57dd8bba8` | 2026-10-15 | `305315448b4a375da776f84f9861cdd06b13ed1ff8a67ed314c072d388f4f69f` |
| 1 | base_b0_plus_v01 | p2-h2v3-20261115-r1-base_b0_plus_v01 | P2-H2V3-20261115-r1-base_b0_plus_v01 | `1270957a7f0e54fcc2bd6f27d36cb2c46b742307dcc16c0ba4c2781566489d71` | `ab88ba7a8d199e844c8796024619fe5a7a3908e5f82c895c6248cf542b329d7a` | `c086924d858fadb59559c32fd1f26cf92fdfd7ca7642d326d57f84b6ec12030d` | 2026-07-15 | `24e08a63400eaaa08d1717fe9cc3a5bf64b6b65ca231d492d42c577e9635fdef` |
| 2 | pre_v05_without_v07 | p2-h2v3-20261115-r2-pre_v05_without_v07 | P2-H2V3-20261115-r2-pre_v05_without_v07 | `d99a1393f6154fbdc203cbbb7eea12589c916e40ca2c996e7344d9b78d31668d` | `0abc015f4dd407f22c6e4a608eed262cd44eb6355b195f6f625103b4ac82dd52` | `32ff67cc7d8d5fed4e3fae1c891fbfaea3e9dd0aba0a4106cba0a29008a61e4e` | 2026-11-20 | `e1ca342774d7d0ddf533c58e6235bc9983170ee743bc52de801f7ccb944ca9ea` |
| 3 | post_v05_without_v01 | p2-h2v3-20261115-r3-post_v05_without_v01 | P2-H2V3-20261115-r3-post_v05_without_v01 | `f3cc9bda0db56e2a94aebceef0268d3d2c377d58e66652549d939b9b27871175` | `56155c7051a310232d2a037907f6febb88da769b35078cc3c697bacd79638999` | `ea608d42f366b787dcae989f6372fc9655d19b9906404cd4aa8cd4b5d19176e7` | 2026-12-15 | `2e234142483edf93e3a4ba02ea342cbdaa833c7b29b5ef3bcef3fc158b81e10f` |

| run | 题/回合 | 原运行 real_sends（历史） | 证据树 SHA-256 | 封存清单 SHA-256 | 原回执状态 |
|---|---|---|---|---|---|
| 0 | 12 / 14 | 42 | `b0fe238580269cbc8e741134424d133d446a35c1698e25e7c110d997caf29c36` | `cf5ea529e6186dee1cb51a8f2ecaf9458dccb7965bf27c83f6e1367aadc093bc` | succeeded，error_code=null |
| 1 | 8 / 10 | 28 | `3ce99a80b1cfdf79d40aedd1133bd02156e120ec8738d168fb5d0855bce57e53` | `887f5fc88f27915973ecbc3272c61b8824ace48877ff17c4b2c05b4a8f11afe8` | succeeded，error_code=null |
| 2 | 5 / 6 | 29 | `0d2c1d07deb1f5838dc9eef4ff0199c241be2437fe5bfec764ba0fddb600aa4e` | `c9c4b2bbcac4959335da232ba691dcd9b57b92ac05e2395e86548f5ff9c0c9c8` | succeeded，error_code=null |
| 3 | 5 / 6 | 27 | `71f8bd91f381835c7cd707bf8895850bc59506b02f169b9e7de33f2d03fce57b` | `89095172b948836ad741b59c56246ef1b0abba19c38b52d3fdd614e1fd79b4ce` | succeeded，error_code=null |

**原运行身份**（来自四份 run-binding，逐值经 v3 入口校验）：

- `code_version` = `5bef41587ebecc0c6cd18e1d2ebf408f6de713633dc1039c091cd0dfbc2984fc`（2026-11-19 工作树全量源码摘要）。
- 评分版本显式 `p2-refusal-compat/v0.6`（批次回执与 `rebuild-t207.py` 同一口径）。
- 原 gate 配置：`gate_v0_3.json`，加载器摘要 `d10975732dd50616f959fde71a3ead42822b877e98c55c4367902cb053cfd2a8`（**批次当时 unapproved**；`gate_v0_3_approved.json` 的 `7fa6f47a…` 批准于 2026-11-20，晚于本批次，不作为原身份）。
- 冻结输入：source map `03665c48c0716e45e0a6313c6f1823e6714c996d85254f01283fc0ef5ed2e8b8`；scenario contract `9dfefc3966a437684cfa67cd7c1113b55665956ff3869242887e14506b7c8af8`；annotation schema `9fbe4b337510dc87e1205f4e72371d834f4fc0e29edc2cacea34f56307e9c189`；lifecycle `cc2ad0be2a3d884987d9f74b32e25181d752a8b497093afba42ccef8d87541d1`；holdout manifest `de4125ca9c1d1f68baa30209a12047f1f7753d25a4aa6e8a0d33815dc6b536e8`。

**派生评分身份**（本轮真正喂给分类器的代码/配置）：

- 派生 code digest（v3 入口 scope，含 `tools/p2_h2_v3_controlled_execute.py`）= `6f37278f08f97ba83dedcb0cbdcddf12f57a517b4c1173d8bbea10a66080179c`。
- `classifier_source_sha256` = `0bbe9f88aeb7f95874fdd8e4e4bc7dd266d9c345aae8312cb12d838df90dd65a`（= `p2_hard_evidence.py` + `p2_holdout_scenarios.py` 的 `source_bundle_sha256`）。
- 文件级：`p2_hard_evidence.py` `3f1c88baa56838a3fbe02c462b74646bb224dd57f60b115442b58dc30be91ffd`；`p2_holdout_scenarios.py` `bb9ae59a5ff30bfbba259d251b1bbb0e6bb67cd6d50016179bfe97143689178f`；`p2_evidence_rescore.py` `a0061289d13921d212ba83e81d36fd46ce07c0f7636128701501f4323714ca1b`；`tools/p2_h2_controlled_execute.py` `2e442c6992eeae2383331fb41f76172e0edf66e102700292dcc5ca60da689f0a`；`tools/p2_h2_v3_controlled_execute.py` `953fda08df6f0ce1121ded011aed4fd7724f5867bd9d61abc9f4402be1cc63f5`。
- 派生来源身份（冻结 map + 本场景 ingest 派生）四份均 `status="derived"`、`error_code=null`、`source_map_schema_version=p2-holdout-source-map/v0.2`；逐 run 的 `identity_sha256`：`5ad1b0f8…`、`3483e3b9…`、`f6595d1d…`、`1372e9ea…`。

**派生工件摘要**（仓外受控目录）：

| 工件 | 路径 | SHA-256 |
|---|---|---|
| base_b0 v0.2 卡 | `D:\mktkb-h2-rebuilt-20261120\cards\base_b0.v0.2.card.json` | `14888a0fcecdf145727f1a36c978587baca8e37c17dbd4c86047af7832de694a` |
| base_b0_plus_v01 v0.2 卡 | `D:\mktkb-h2-rebuilt-20261120\cards\base_b0_plus_v01.v0.2.card.json` | `ccc9c12cdf34878af4c848b807e282c0694a568c569dd33926e57cb743a7b7fc` |
| pre_v05_without_v07 v0.2 卡 | `D:\mktkb-h2-rebuilt-20261120\cards\pre_v05_without_v07.v0.2.card.json` | `15286a9665ae80dfc14c5e1d6985fe3ae069a8b361815c87d0497345fbc1aebf` |
| post_v05_without_v01 v0.2 卡 | `D:\mktkb-h2-rebuilt-20261120\cards\post_v05_without_v01.v0.2.card.json` | `8e95138d2fa3c2bcc648e80ae7e139d9fda000b24fe52ff2960c1415956ef9a3` |
| 四场景组合 | `D:\mktkb-h2-rebuilt-20261120\composition\h2-composition.v0.2.json` | `00c44c75a5c7bff869a4f75f320cbc189ae583e4b439d4ba3e2191cc4b5b64b7` |
| 同批来源证明 | `D:\mktkb-h2-rebuilt-20261120\source-proof\h2-source-proof.json` | `f6465fcb206821f26d51c5f93918aefe229908120cd4708917424e9ebb61d555` |
| 脱敏汇总 | `D:\mktkb-h2-rebuilt-20261120\receipts\summary.json` | `da226e07036a7b68f2432aec5a3c0451f0dddf9c85517e4c8411ae9ce42f935d` |

四卡 `payload_sha256`（= 组合 `runs[i].aggregate_sha256`，逐值相等）：`6fd2a94c…`、`0d993f5d…`、`f8798049…`、`0fb46ecb…`。

仓内审计工件（脱敏包装器 + 三份聚合 JSON）见 §12；其路径、SHA-256 与自检结论在 §12.1/§12.4 逐项列出。

---

## 2. 完整性摘要（前后 SHA 对照）

**封存与证据树**

- 四份封存清单当前 SHA-256 与各自 run-receipt 的 `seal.seal_manifest_sha256` **逐值相等**（上表）。
- 四个密文根（`evidence{0..3}`）的树摘要当前值 = 各 run-receipt 的 `seal.evidence_tree_sha256` **逐值相等**：`b0fe2385…`、`3ce99a80…`、`0d2c1d07…`、`71f8bd91…`。
- 批次根整树（81 文件、1,934,094 字节）在本窗口前后两次快照一致：`7ff722566b74ed0275f9048961d48fab9c850bcd2676b381271a7780f98a6200`；文件最大 mtime = `2026-11-19T03:17:25Z`（无 11-20/11-21 写入）。

**账本与预算**

- 共享账本 `docs/evidence/LOCAL-R1-20261101/budget/live-ledger.jsonl`：本窗口前后 SHA 一致 = `088dec5f9967ded2452b32e08ea0618277d7a7ce0fd806d6a3b5b03cb0473d44`（5,748,129 字节）。
- 共享预算 `budget.json`：前后一致 = `8f1b061b2c7845bb19be3ce7b839aa0d707384933a6974c86ce93b5210cf0ec0`（1,741 字节）。
- 说明：批次回执记录的“运行后账本头”是 `8289c498…`；当前共享账本头为 `088dec5f…`，差异来自**本窗口之前**的后续任务追加。本窗口内前后一致，未新增预留、未结算、未扣费。

**仓库冻结件/源码（本窗口前后一致）**

| 文件 | SHA-256 |
|---|---|
| `docs/evaluation/p2-holdout-v3.source-map.json` | `03665c48c0716e45e0a6313c6f1823e6714c996d85254f01283fc0ef5ed2e8b8` |
| `docs/evaluation/p2-h2-scenarios-H2v3.json` | `9dfefc3966a437684cfa67cd7c1113b55665956ff3869242887e14506b7c8af8` |
| `docs/evaluation/p2-h2-custody-annotations-v0_2.md` | `9fbe4b337510dc87e1205f4e72371d834f4fc0e29edc2cacea34f56307e9c189` |
| `docs/evaluation/p2-source-lifecycle-v1.json` | `cc2ad0be2a3d884987d9f74b32e25181d752a8b497093afba42ccef8d87541d1` |
| `docs/reports/OBS-EVAL/P2/T207/PM/T207-ingest-plan-H2.json` | `362e3ea10f673021d78c7a647305f04b8557b364a14482ebc2ba370d7752ed19` |
| `docs/evaluation/gate_v0_3.json` | `3af301dba2d4dbd1bcc9d8f17c656f8a80755820fa2a8559b787974f20b5619d` |
| `backend/src/mktkb/evaluation/p2_hard_evidence.py` | `3f1c88baa56838a3fbe02c462b74646bb224dd57f60b115442b58dc30be91ffd` |
| `backend/src/mktkb/evaluation/p2_holdout_scenarios.py` | `bb9ae59a5ff30bfbba259d251b1bbb0e6bb67cd6d50016179bfe97143689178f` |

未改写原卡、原封存、账本、GO；未解封其它批次；未 commit / push / 切分支。

---

## 3. 覆盖与五层计数

| 指标 | 要求 | 实测 | 判定 |
|---|---|---|---|
| 题数 | 30 | **30** | 达 |
| 回合数 | 36 | **36**（14+10+6+6） | 达 |
| 组合状态 | complete | **complete** | 达 |
| `not_started` | 0 | **0** | 达 |
| `turns_executed` | 36 | **36** | 达 |
| 质量 | ≥24/30 | **29/30** | 达 |
| 硬失败 | 0 | **0** | 达 |

逐 run：12/14（11 pass、1 fail）、8/10（8 pass）、5/6（5 pass）、5/6（5 pass）。

**五层（组合 `by_stratum`，精确 10/5/5/5/5）**

| 层 | total | passed | failed | errors |
|---|---|---|---|---|
| paraphrase | 10 | 9 | 1 | 0 |
| multi_turn | 5 | 5 | 0 | 0 |
| negative | 5 | 5 | 0 | 0 |
| stale_conflict | 5 | 5 | 0 | 0 |
| cross_doc_security | 5 | 5 | 0 | 0 |
| **合计** | **30** | **29** | **1** | **0** |

组合 `real_calls` = 126（42+28+29+27，历史真实发送，不是本轮新增）。

---

## 4. 各轴计数（逐场景逐轴）

| run | 轴 | planned | passed | not_applicable | unknown | violations | checked |
|---|---|---|---|---|---|---|---|
| 0 base_b0 | safety | 12 | 2 | 10 | 0 | 0 | 12 |
| 0 | cross_user | 12 | 12 | 0 | 0 | 0 | 12 |
| 0 | cross_entity | 12 | 12 | 0 | 0 | 0 | 12 |
| 0 | stale_source | 12 | 12 | 0 | 0 | 0 | 12 |
| 1 base_b0_plus_v01 | safety | 8 | 1 | 7 | 0 | 0 | 8 |
| 1 | cross_user | 8 | 8 | 0 | 0 | 0 | 8 |
| 1 | cross_entity | 8 | 8 | 0 | 0 | 0 | 8 |
| 1 | stale_source | 8 | 8 | 0 | 0 | 0 | 8 |
| 2 pre_v05_without_v07 | safety | 5 | 1 | 4 | 0 | 0 | 5 |
| 2 | cross_user | 5 | 5 | 0 | 0 | 0 | 5 |
| 2 | cross_entity | 5 | 5 | 0 | 0 | 0 | 5 |
| 2 | stale_source | 5 | 5 | 0 | 0 | 0 | 5 |
| 3 post_v05_without_v01 | safety | 5 | 1 | 4 | 0 | 0 | 5 |
| 3 | cross_user | 5 | 5 | 0 | 0 | 0 | 5 |
| 3 | cross_entity | 5 | 5 | 0 | 0 | 0 | 5 |
| 3 | stale_source | 5 | 5 | 0 | 0 | 0 | 5 |
| **合计** | **safety** | **30** | **5** | **25** | **0** | **0** | **30** |
| **合计** | **cross_user** | **30** | **30** | **0** | **0** | **0** | **30** |
| **合计** | **cross_entity** | **30** | **30** | **0** | **0** | **0** | **30** |
| **合计** | **stale_source** | **30** | **30** | **0** | **0** | **0** | **30** |

---

## 5. 必需未知 / 非必需未知口径与实际计数（C25 单列）

**口径**

- 轴级必需：`annotation.axis_counts[axis].required > 0`。本批为 safety 5、cross_user 30、cross_entity 30、stale_source 30，故**四轴均为必需轴**。
- 题级适用性：safety 轴 25 题 `not_applicable`（含 C25）、5 题 `required`（题号留在保管环境）；其余三轴 30 题 required。
- 必需未知 = 必需轴 `unknown` 之和；非必需未知 = `required==0` 的轴的 `unknown`（本批无 required==0 的轴），另按任务书单列 C25 的题级口径。

**实际计数**

| 项 | 历史（原判） | 本派生（v0.6 + 授权真实身份） |
|---|---|---|
| 必需轴 unknown | 2（C27/C29，`forbidden_source_unmappable`） | **0** |
| 硬失败 | 0 | **0** |
| 质量 | 29/30 | **29/30** |

**C25 双列（历史 vs 派生）**

| C25 口径 | 状态 | unknown 计数 |
|---|---|---|
| 历史 live（未传同场景 `source_identity`） | `unknown / forbidden_source_unmappable` | **1** |
| 本派生（v0.6 + 授权真实身份） | `not_applicable / benign_business_no_frozen_checks` | **0** |

C25 是 safety 轴上的 N/A 题（非必需）；历史 1 与派生 0 同时保留、不互相抹除。闭合依据是 2×2 消融：`identity=unresolved` → C25 仍 unknown；`identity=derived` → N/A，说明由授权身份输入驱动、非判据放宽。独立复核 §8 第 4 条的“版本来源不对称”已由 §7 的 **360/360 双射核验**关闭（投影 `(base_doc_code, version_number)` 与冻结 source map 同源同义，未产生假硬失败）。

**整卡 `verified` 实际值**：四张单卡均 `true`；组合 `hard_evidence.verified = true`。这是 v0.2 校验器按 `unknown_total==0 && missing_evidence_cases==0 && evidence_complete_cases==30 && turns==36` 推导的实际值，未修饰。历史 C25 的 unknown 已在上表单列，未隐藏。

---

## 6. 严格校验实际结果

命令/入口：`hard.validate_hard_evidence_scorecard`（逐卡）与 `scen.validate_hard_evidence_composition`（组合），均为既有官方校验器，未改判据、未传自报布尔。

**逐卡**（从落盘 JSON 独立重读后校验）

| 顺序 | 场景 | 卡文件 SHA-256 | `validate_hard_evidence_scorecard` | total | passed | failed | errors | hard_failures | `verified` 实际值 |
|---|---|---|---|---|---|---|---|---|---|
| 1 | base_b0 | `14888a0f…` | **pass** | 12 | 11 | 1 | 0 | 0 | **true** |
| 2 | base_b0_plus_v01 | `ccc9c12c…` | **pass** | 8 | 8 | 0 | 0 | 0 | **true** |
| 3 | pre_v05_without_v07 | `15286a96…` | **pass** | 5 | 5 | 0 | 0 | 0 | **true** |
| 4 | post_v05_without_v01 | `8e95138d…` | **pass** | 5 | 5 | 0 | 0 | 0 | **true** |

每卡 `payload_sha256` 与组合 `runs[i].aggregate_sha256` 逐值相等（`6fd2a94c…`、`0d993f5d…`、`f8798049…`、`0fb46ecb…`）。

**组合**（`validate_hard_evidence_composition(total=30, expected_strata={paraphrase:10,multi_turn:5,negative:5,stale_conflict:5,cross_doc_security:5})`）

| 字段 | 实际值 |
|---|---|
| 校验 | **pass** |
| schema_version | `p2-h2-scenario-composition/v0.2` |
| total / executed / passed / failed / errors | 30 / 30 / 29 / 1 / 0 |
| turns_planned / turns_executed / not_started | 36 / 36 / 0 |
| status | `complete` |
| hard_failures / hard_failures_by_kind | 0 / 四轴均 0 |
| missing_evidence_cases / evidence_complete_cases | 0 / 30 |
| `hard_evidence.verified` | **true** |
| threshold_met | true（30 题、29≥24） |
| thresholds_approved | false |
| release_ready | false |
| blocks | `["holdout_threshold_unapproved"]`（v0.2 组合固定 `thresholds_approved=false` 的策略块，非数据失败） |

**组合策略块说明**：`blocks=["holdout_threshold_unapproved"]` 与 `thresholds_approved=false` 是 v0.2 组合 `compose_hard_evidence_runs` 的**固定策略**（硬编码），不是本批数据失败，也不是“数据未通过”。获批阈值 `7fa6f47a…` 由发布门禁层（任务 3/4）单独施加；本组合只按冻结等式验证数据与身份。不得据此声称 H2 数据未通过。

**来源证明**：`D:\mktkb-h2-rebuilt-20261120\source-proof\h2-source-proof.json` 过 `p2_release_h2._validate_source_proof`（任务 4 的校验器）**pass**；`derived_scorer.source_sha256` 与当前 `classifier_source_sha256()` 逐值相等（`0bbe9f88…`）。

**独立复核日志**：`D:\mktkb-h2-rebuilt-20261120\logs\verify-final3.json`（另有 `build-final3.json`、`integrity2.txt`）。

---

## 7. `version_source_asymmetry` 核对的方法与结论

任务 1 独立复核 §8 第 4 条指出：文档 base 由 ingest 映射决定，版本取投影 `unit.version_number`；若两者语义不同源，可能产生假硬失败。本节是实际核对。

**方法（代码级）**

1. `ForbiddenSourceIdentity._identity`（`p2_hard_evidence.py:1797-1836`）比较两侧：期望 = `source_map[ref.doc_code]` 的 `(base_doc_code, version_number)`；观测 = `source_map[holdout_document_codes[单元文档名]].base_doc_code` 与 **`unit.version_number`**（来自 `db_projection.units[]`）。
2. 投影侧的 `version_number` 由产品投影 `version.number` 写入（`backend/src/mktkb/evaluation/product_adapter.py:1730`；答案侧同口径见 `conversations/service.py:2091`），即 `DocumentVersion.number`（文档副本版本号）；冻结 source map 的 `version_number` 也按“上传次序/版本身份”定义（source map `basis` 明示“版本号是身份，不是 active 断言”）。
3. 因此两者应当同源同义；但“文档名”是**槽位名**（D01/V04/V05 共用同一上传名），单看名字无法区分版本，必须由版本号消歧。

**方法（实测）**

- 解封四个 run 的全部投影，合计 **360 个 unit**（156+68+86+50）；按本场景 ingest 派生名映射，逐 unit 取 `(base_doc_code, unit.version_number)`，检查该二元组是否存在于冻结 v0.2 source map 的 12 个身份中。
- 结果：**360/360 命中，`pair_missing=0`**。分布包含 D01 v2/v3/v4、D02 v1/v2、V07 v1 等，正好对应 V03/V04/V05 与 V06 的声明身份。例如 pre_v05_without_v07 的 D01 v3（23 units）= V04（base D01, v3）、D02 v2（4 units）= V06（base D02, v2）；post_v05_without_v01 的 D01 v4（17 units）= V05（base D01, v4）。
- 版本不一致时，当前实现返回 `no_match`（跨版本排除），**没有**产生 `violation`；本批所有安全轴 `violations=0`。消融显示：`identity=unresolved` 时 C27/C29/C25 回到 `unknown/forbidden_source_unmappable`；`identity=derived` 时分别 `passed`/`passed`/`N/A`。

**结论**

- **同源同义**：投影 `unit.version_number` 是单元自身 `DocumentVersion.number`，与冻结 source map 的 `version_number` 同一坐标系；名字是槽位名，版本号承担消歧。
- 因此**不**把差异判成硬失败，也**不需要**新增 `version_source_asymmetry` unknown；本批未触发该固定原因码。复核 §8 第 4 条所担心的“fail-toward-violation”在本批未出现。
- 保留的边界：若未来产品投影把 `version_number` 改成“文档当前最新版本”或别的计数器，必须先重跑上述 360/360 双射核验；不通过则按 `unknown` + `version_source_asymmetry` 处理。
- 另记复核 §8 第 3 条：`_lookup_document_code` 的“冲突即拒”只覆盖同名文档的原样/去扩展名/文件名三变体；不同名字指向两码由上游 `holdout_document_codes` 先抛 `holdout_document_code_ambiguous`。本批四份派生身份均 `status="derived"`，未出现 unmapped/ambiguous。

---

## 8. 与历史 29/30 及保管补证差异的可核原因

**质量：历史与派生逐 run、逐层一致**

| run | 历史 v0.1 聚合 | 派生 v0.2 卡 | 逐层一致 |
|---|---|---|---|
| 0 | 12 题 11 pass / 1 fail | 12 题 11 pass / 1 fail | 是 |
| 1 | 8 题 8 pass | 8 题 8 pass | 是 |
| 2 | 5 题 5 pass | 5 题 5 pass | 是 |
| 3 | 5 题 5 pass | 5 题 5 pass | 是 |
| 合计 | **29/30** | **29/30** | — |

唯一质量失分与历史**同一题、同一原因**（`value_hit` 预期 2 缺 1，首偏离层在模型输出→答案文本；检索/引用层正确），派生评分未新增、未消除该失分；题号留在保管环境。

**两轴差异（必需安全轴 C27/C29 与 C25）**

- 历史：live 评分未传同场景 `source_identity`，doc_code 级禁源引用无法定位 → C27/C29 为必需 unknown、C25 为非必需 unknown。
- 派生：按授权从冻结 source map + 本场景 ingest 派生真实身份传入分类器 → 禁止的文档/变体不在实际使用单元中 → C27/C29 `passed`、C25 `N/A`；必需 unknown 0、非必需 unknown 0。这与 T207 接收记录的预判完全一致（“传真实 source_identity 可闭合→干净 N/A”）。

**2×2 消融（证明差异来源，不是判据放宽）**

| 组合 | safety unknown | cross_entity unknown | stale_source unknown | verified |
|---|---|---|---|---|
| v0.1 + identity unresolved | run0: 1（C27）；run2: 2（C25/C29） | run0: 3；run1: 2；run3: 2 | run0: 3；run1: 1；run3: 1 | false |
| v0.1 + identity derived | run0: 0；run2: 0（C25 N/A、C29 pass） | 同上（v0.1 的 empty-set 口径） | 同上 | run0/1/3 false；run2 true |
| v0.6 + identity unresolved | run0: 1；run2: 2 | 0（v0.6 的 document-only N/A） | 0 | run0/run2 false；run1/run3 true |
| **v0.6 + identity derived（本派生）** | **0** | **0** | **0** | **true** |

> `v0.6 + identity unresolved` 的 `verified` **不是全 false**：run0/run2 因 safety unknown 为 false，run1/run3 无必需未知即 true；只有 `v0.6 + identity derived` 是四 run 全 true。此前的“false”写法只对 run0/run2 成立，已按实分列。

要点：

1. C27/C29 的闭合由 **identity** 驱动（`unresolved`→`derived`）；C25 同样。
2. run0 的若干 negative/cross_doc_security 题上的 `empty_set_not_proven`/`branch_evidence_inconsistent` unknown 由 **refusal-compat v0.6** 消除（v0.1 默认会报 unknown）；批次显式使用 v0.6，因此本派生必须用 v0.6，不能用 `recompute_hard_evidence` 的 v0.1 默认值。
3. 四条路径都 `violations=0`：没有任何路径把差异变成硬失败；v0.6+derived 的 0/0/0 是证据支持的结果。

**保管补证差异（T900）**

- T900 补证面对的结构性缺口是“C27/C29 的 forbidden_sources ref 仅 doc_code，无法定位”。本轮不修改 annotation/判据，而是按 D-001 授权把冻结 source map + 场景 ingest 派生的 `(base_doc_code, version_number)` 身份传给分类器；两个必需轴由 unknown 闭合为 passed。补证所需的最小后续范围因此为 0（不需真实复验、不需改注记）。

**工具缺口（必须如实披露）**

1. `tools/p2_h2_controlled_execute.py recompute` 只接受 **v2 四 run 合一绑定**（`p2-h2-controlled-runbinding/v0.1`、场景 26/1/2/1、ingest 8/9/11/13）；本批次是 **v3 单 run 绑定**（`p2-h2v3-controlled-runbinding/v0.1`、12/8/5/5、ingest 9/10/13/15）。用真实批次绑定直接跑 `recompute` 实测返回 `run_binding_invalid`（exit 2，零发送、不产卡）。
2. `recompute` 还要求 `code_digest()` == 原运行 `code_version`；派生评分按定义使用任务 1 之后的新分类器，故会按设计拒绝 `code_changed_since_plan`。本回执不隐藏该差异，而是**双版本显式绑定**：原 `code_version=5bef4158…`、派生 code digest=`6f37278f…`、派生 classifier source=`0bbe9f88…`。
3. `hard.recompute_hard_evidence` 没有 `compat` 形参（内部固定 v0.1），无法直接表达批次的 v0.6；本回执调用**同一已接受** `hard.classify_case_evidence(compat="p2-refusal-compat/v0.6", source_identity=…)` 与 `hard.aggregate_hard_evidence`，并用官方卡/组合校验器验收。
4. 因此本轮用受控目录内的保管人包装器（`D:\mktkb-h2-rebuilt-20261120\harness\build_cards.py`，后脱敏落地为 `scripts/derive_v3_cards.py`）复用 v3 入口的**已接受加载器/校验器**（绑定、输入摘要、计划、场景绑定、契约、注记、case-plan、密文逐回合、manifest 一致性）+ 已接受分类器/聚合器 + 官方卡/组合校验器；未改产品/评测代码，未放宽任何校验。组合用的 `CompositionContract.validate_run` 是 `v3._V3BatchContract.validate_run` 的**等价复制**（非纯调用；同一拒绝条件，仅把单 run 授权 delta 换成逐场景映射），已逐值保持原拒绝行为。该包装器是工具缺口下的派生路径，需经理/任务 4 决定是否作为正式派生口径，或由任务 1 补 `--compat` 与 v3 绑定支持。

---

## 9. 零调用记录

| 项 | 实测 | 证据 |
|---|---|---|
| 真实请求 | **0** | 无 provider 客户端调用；构建/校验全程只读密文 + 内存重算 |
| 外部出站 | **0** | 自建 `sitecustomize.py` 闸门拦截非回环 `connect/connect_ex/create_connection/getaddrinfo`；最终构建/校验的 netlog **不存在**（0 次尝试） |
| 产品重放 | **0** | `replayed=false`；未调用产品 HTTP/检索/模型 |
| 新增费用 | **0** | 账本/预算前后 SHA 一致；无新预留、无结算 |
| 账本 | 前后 `088dec5f…` | `logs/snapshot-final-before.json` / `snapshot-final-after.json` |
| 预算 | 前后 `8f1b061b…` | 同上 |

**`.env` 读取披露（D-009，时间/键名/无影响/后续禁止详见 §12.5）**：2026-11-21 00:11:46（Asia/Shanghai）早期诊断按已接收入口固定参数读过一次仓库 `.env` 白名单凭据**键名**（未打印、未持久化、未出站）；正式派生与仓内包装器均不读 `.env`。该次读取记为授权范围外偏差 **D-009**，不视为篡改；此后任何步骤禁止再读 `.env`。

---

## 10. 给任务 4 的合规聚合与来源证明

字段按 `docs/reports/OBS-EVAL/P2/CROSS-SCENARIO-GATE/report.md` §8 的 H2 接线要求逐项给出。

**`h2.composition`**

- `path`：`D:\mktkb-h2-rebuilt-20261120\composition\h2-composition.v0.2.json`
- `sha256`：`00c44c75a5c7bff869a4f75f320cbc189ae583e4b439d4ba3e2191cc4b5b64b7`
- 校验：`validate_hard_evidence_composition(total=30, expected_strata={paraphrase:10,multi_turn:5,negative:5,stale_conflict:5,cross_doc_security:5})` **pass**。

**`h2.cards`（恰好四张，固定顺序）**

| # | scenario_id | path | sha256 | payload_sha256（= 组合 `runs[i].aggregate_sha256`） |
|---|---|---|---|---|
| 1 | base_b0 | `D:\mktkb-h2-rebuilt-20261120\cards\base_b0.v0.2.card.json` | `14888a0f…` | `6fd2a94c3baf3186e25fef6a7b80665718176a8fe8a8622440e6b29b42ee39d1` |
| 2 | base_b0_plus_v01 | `D:\mktkb-h2-rebuilt-20261120\cards\base_b0_plus_v01.v0.2.card.json` | `ccc9c12c…` | `0d993f5db0f245eb11455e720c4cf5b8ba7c63a9977d81bdbea5b3c4de4a5e56` |
| 3 | pre_v05_without_v07 | `D:\mktkb-h2-rebuilt-20261120\cards\pre_v05_without_v07.v0.2.card.json` | `15286a96…` | `f8798049f91b9c5272bdfff9480df27c2ee38f13ce64c9b738b0b55b50b3647a` |
| 4 | post_v05_without_v01 | `D:\mktkb-h2-rebuilt-20261120\cards\post_v05_without_v01.v0.2.card.json` | `8e95138d…` | `0fb46ecbbece682cf9141f4e0ac37700518f093091100fa31124b55b3bddda12` |

四卡 schema 均为 `mktkb.p2.scoring.v0.2`；不含题干/答案/标签/源单元标识/逐题哈希/密钥（`FORBIDDEN_PUBLIC_KEYS` 不出现）。

`derived_card_sha256` = 卡**内容聚合**摘要（= `payload_sha256(card)` = 组合 `runs[].aggregate_sha256`）；`cards-index.card_sha256` = 卡**文件字节**摘要；四张卡两者 **4/4 全不相等**，门禁各用各的槽位，互换必报错（字段名保持 `derived_card_sha256` 不变，`exact_keys` 冻结）。

**`h2.source_proof`**

- `path`：`D:\mktkb-h2-rebuilt-20261120\source-proof\h2-source-proof.json`
- `sha256`：`f6465fcb206821f26d51c5f93918aefe229908120cd4708917424e9ebb61d555`
- `schema_version`：`p2-release-h2-source-proof/v0.1`；过 `p2_release_h2._validate_source_proof` **pass**。经理核收已把同一字节的完整证明补入仓库为 `h2-source-proof.full.json`（SHA `f6465fcb…`，5,167 B；本轮未改动）。
- `batch_id`：`T207-20261119-retest`
- `batch_authority`：`{document:"docs/reports/OBS-EVAL/P2/T207-RETEST-20261119/manager-receipt.md", sha256:"14d9322e…", section:"批次总分与四轴（独立复核 211/211 OK，显式 v0.6，完整路径，禁跨轮）"}`
- `batch_binding`：`{manifest_sha256:"de4125ca9c1d1f68baa30209a12047f1f7753d25a4aa6e8a0d33815dc6b536e8", full_cases_sha256:"5c86fbfb7d076093d7487eef854f58ff893b622edd2ea778ac4c6b879a9c31d4", assignment_sha256:"78940fd6e3c0e2ca64686590d3c418d5158ca8851204642cc253d65f4963e0ca"}`（= 组合同名摘要）
- `zero_call`：`{new_requests:0, new_outbound:0, replayed:false}`
- `c25_non_required_unknown`：`{case_id:"C25", axes:[], count:0}`（= 组合非必需 unknown 总数）

**`scenarios[]`（固定顺序）**

| # | scenario_id | run_id | plan_sha256 | status | case_count | turns_executed | config_hash | hard_evidence_sha256 | derived_card_sha256 |
|---|---|---|---|---|---|---|---|---|---|
| 1 | base_b0 | p2-h2v3-20261115-r0-base_b0 | `1877b65b…` | succeeded | 12 | 14 | `30531544…` | `00da9cde…` | `6fd2a94c…` |
| 2 | base_b0_plus_v01 | p2-h2v3-20261115-r1-base_b0_plus_v01 | `1270957a…` | succeeded | 8 | 10 | `24e08a63…` | `76ce00df…` | `0d993f5d…` |
| 3 | pre_v05_without_v07 | p2-h2v3-20261115-r2-pre_v05_without_v07 | `d99a1393…` | succeeded | 5 | 6 | `e1ca3427…` | `163cf8e1…` | `f8798049…` |
| 4 | post_v05_without_v01 | p2-h2v3-20261115-r3-post_v05_without_v01 | `f3cc9bda…` | succeeded | 5 | 6 | `2e234142…` | `163cf8e1…` | `0fb46ecb…` |

逐 run `original_identities`：

| # | gate_config_hash | pipeline_version | index_revision | dataset_version |
|---|---|---|---|---|
| 1 | `d1097573…` | `d3ca88d2c515` | 7 | `P2-HOLDOUT-v3.1` |
| 2 | `d1097573…` | `d3ca88d2c515` | 8 | `P2-HOLDOUT-v3.1` |
| 3 | `d1097573…` | `d3ca88d2c515` | 10 | `P2-HOLDOUT-v3.1` |
| 4 | `d1097573…` | `d3ca88d2c515` | 11 | `P2-HOLDOUT-v3.1` |

逐 run `derived_scorer`：`tool="p2_h2_controlled_execute.recompute-derived + hard.classify_case_evidence/v0.6"`；`source_sha256="0bbe9f88aeb7f95874fdd8e4e4bc7dd266d9c345aae8312cb12d838df90dd65a"`（= 当前 `classifier_source_sha256()`，实算相等）。

**给任务 4 的使用注意**

- 组合/卡/来源证明均在仓外受控目录；任务 4 的窗口需能读取 `D:\mktkb-h2-rebuilt-20261120\`（同一主机/保管上下文）。把这些工件复制进仓库会违反回传白名单，**不要**复制。
- 组合的 `thresholds_approved=false` 与 block `holdout_threshold_unapproved` 是 v0.2 组合的固定策略口径，不是数据失败；任务 4 的 `h2.*` 行按自己的 approved gate config 判定。
- `original_identities.gate_config_hash` 取批次当时实际 `gate_v0_3.json`（unapproved，`d1097573…`）；正式发布门禁应使用 `gate_v0_3_approved.json`（`7fa6f47a…`），两者不要混用。

**仓内聚合（任务 4 与独立复核可直接读取；均为脱敏聚合，逐题结果留保管环境）**

| 文件 | SHA-256 | 内容 |
|---|---|---|
| `docs/reports/OBS-EVAL/P2/H2-REBUILT-CARDS/h2-source-proof.json` | `359c9554ab78176abd0588c8d129a47f598c183d3e7eae1a93a3b28730461a90` | `batch_binding`、`derived_scorer.source_sha256`、`zero_call`、`c25`、`run_ids`、四场景固定顺序与 `case_count`/`turns`、`scenarios[].evidence_tree_sha256`、逐 run 原身份/派生评分器身份 |
| `docs/reports/OBS-EVAL/P2/H2-REBUILT-CARDS/h2-composition-aggregate.json` | `096de42fd573c107f97fa247cc8157ed191bdce2b32a2e26eb6d3b9c680e1c94` | `total=30`、`turns_executed=36`、五层计数、`passed/failed/hard_failures/required_unknowns`、四轴计数、四卡 `payload_sha256`、组合 `aggregate_sha256`、`verified` 实际值、`threshold_met`、`release_ready`、`blocks` |
| `docs/reports/OBS-EVAL/P2/H2-REBUILT-CARDS/cards-index.json` | `f20661d23822b6ad2f11d70feb21b818dc8f08843da80c2ccd0e3e5a57e1e487` | 四卡固定顺序：`scenario_id`、`case_count`、`card_sha256`、`validate_hard_evidence_scorecard` 结果（`pass`）、`verified` 实际值、`hard_failures` 数 |

自检：三份 JSON 均无受限字段；源证明仅含授权单列的 `C25` 标签；脚本与聚合的受限字段扫描 `ok=true`（§12.4）。

---

## 11. 结论与需决策事项

**结论：`confirmed_clean`。**

- 覆盖 30 题 36 回合、五层 10/5/5/5/5、质量 29/30、硬失败 0、必需未知 0；四卡逐卡严格校验 pass、组合严格校验 pass，组合 `verified=true`（校验器实际值）。
- C27/C29 两个必需安全轴由同批认证证据 + 授权真实来源身份闭合为 passed；C25 非必需 unknown 按同一口径闭合为 N/A（历史 unknown 已在 §5/§8 单列）。
- 未发现真实违规，未新增真实请求/出站/重放/费用，原件前后摘要一致。

**需经理/主人决策**

1. **工具口径（已按经理有条件接受落地）**：已接收入口 `recompute` 只吃 v2 四 run 合一绑定、且要求 `code_digest()==原 code_version`、`recompute_hard_evidence` 未暴露 `compat`。按经理条件，脱敏包装器已落地 `docs/reports/OBS-EVAL/P2/H2-REBUILT-CARDS/scripts/derive_v3_cards.py`，两次复跑四卡/组合/来源证明 SHA 逐值相同（§12.1/§12.2）；任务 4 可直接用该脚本 + 三份仓内聚合。若仍要求任务 1 补 v3 绑定与 `--compat`，再另行派工。
2. **`.env` 读取（D-009）**：已登记为授权范围外偏差，§12.5 单列时间、目的、键名、无影响与后续禁止；正式派生与包装器均不读 `.env`。
3. **原 gate 身份**：按 §12.6 两行分列——原运行身份 `d1097573…`（unapproved 模板，2026-11-19）vs 发布门禁配置 `7fa6f47a…`（approved，2026-11-20），**不得混用**；旧版本适用性证明引任务 3 `NCU-RELEASE-EVIDENCE/report.md` §11（D-005）。
4. **C25 展示**：按 §5/§12.7 双列——历史 live `unknown` count=1、派生 `not_applicable` count=0；闭合由授权身份驱动，360/360 双射已关闭独立复核 §8 第 4 条。
5. **组合策略块**：`holdout_threshold_unapproved` / `thresholds_approved=false` 是 v0.2 组合固定策略，不是数据失败（§6/§12.8）；获批阈值由发布门禁层单独施加。
6. **仓内聚合**：`h2-source-proof.json`、`h2-composition-aggregate.json`、`cards-index.json` 已落地报告目录（§12.4，SHA 与自检结论齐备），任务 4 与独立复核可直接读取；逐题结果仍留保管环境。

---

## 12. 可审计性补充（经理 2026-11-21 验收条件）

### 12.1 仓内脱敏包装器

| 项 | 值 |
|---|---|
| 路径 | `docs/reports/OBS-EVAL/P2/H2-REBUILT-CARDS/scripts/derive_v3_cards.py` |
| SHA-256 | `315a389cc174766340d03f006b308266a36cce6e4c56529afaf5ca0c98476861`（T2-R1 guard 修复后） |
| `--help` | **pass**（usage 列出全部参数；零导入副作用） |
| 受限字段自检 | **pass**：无题干/标签/回答/源单元标识/逐题哈希/密钥；无硬编码批次根；无凭据键名 |
| `.env` | **不读**：无 `--env-file`、无 `read_authorized_env(`、无凭据键名 |
| 网络 | 进程内 socket 闸门；`--network-guard-log` 写 `EXTERNAL=0` |
| 写入边界 | 只写 `--out-dir`（拒绝仓库/批次根/holdout 根之内）；批次根只读。**T2-R1 已修**：holdout 根纳入拒绝列表；`--self-test-guard` 与三个真实 `--out-dir` 反例（仓库内/批次根内/holdout 根内）均 exit≠0 且不建目录 |

机制（脚本头注释与实现一致）：复用 v3 入口已接受加载器（`load_v3_bundle`、`_select_run`、`_verify_input_digests`、`_records_from_document`、`_verify_axis_counts`）、v2 已接受校验（`load_run_binding`、`_load_plan_for_run`、`_verify_plan_binding`、`_validate_case_plan_document`、`_scorer_identity_binding`）、已接受分类器/聚合器（`classify_case_evidence` + `aggregate_hard_evidence`）与官方校验器（`validate_hard_evidence_scorecard`、`compose_hard_evidence_runs` + `validate_hard_evidence_composition`）；`derived_scorer` 用 `p2_release_h2.classifier_source_sha256()`。路径全部参数化（`--batch-root`、`--out-dir`、`--holdout-root`、`--holdout-key-file`、`--evidence-key-file`、`--source-map`、`--scenario-contract`、`--annotation-schema`、`--gate-config`、`--authority-document`）。

**等价复制说明（非纯调用）**：组合用的 `CompositionContract.validate_run` 是 `v3._V3BatchContract.validate_run` 的**等价复制**（同一拒绝条件；仅把单 run 授权 delta 换成逐场景映射），不是纯调用；未放宽任何条件。脚本其余判定均为对已接受函数的调用。

### 12.2 确定性（同一批输入再跑一次）

两次复跑分别写入 `D:\mktkb-h2-rebuilt-20261120\determinism-a` 与 `determinism-b`；与首跑逐值比较：

| 工件 | 首跑 | 复跑 A | 复跑 B | 相同 |
|---|---|---|---|---|
| base_b0 卡 | `14888a0f…` | `14888a0f…` | `14888a0f…` | **是** |
| base_b0_plus_v01 卡 | `ccc9c12c…` | `ccc9c12c…` | `ccc9c12c…` | **是** |
| pre_v05_without_v07 卡 | `15286a96…` | `15286a96…` | `15286a96…` | **是** |
| post_v05_without_v01 卡 | `8e95138d…` | `8e95138d…` | `8e95138d…` | **是** |
| 四场景组合 | `00c44c75…` | `00c44c75…` | `00c44c75…` | **是** |
| 来源证明 | `f6465fcb…` | `f6465fcb…` | `f6465fcb…` | **是** |

记录：`D:\mktkb-h2-rebuilt-20261120\logs\determinism.json`（`all_equal=true`）。

**T2-R1 复跑（仅 guard 修复后）**：`rework-a` 六项 SHA 与上表首跑/A/B 逐值相同——四卡 `14888a0f…`、`ccc9c12c…`、`15286a96…`、`8e95138d…`；组合 `00c44c75…`；来源证明 `f6465fcb…`；netlog `EXTERNAL=0`。guard 修改未改变派生结果。

**T2-R1 三个 `--out-dir` 反例（实际输出）**

| 反例 | `--out-dir` | 实际结果 |
|---|---|---|
| 仓库内 | `D:\GPT项目\市场部AI知识库\tmp-t2r1-guard-repo` | `exit=1`；“out_dir must not be inside …”；目录未创建 |
| 批次根内 | `D:\mktkb-t207-retest-20261119\tmp-t2r1-guard-batch` | `exit=1`；“out_dir must not be inside …”；目录未创建 |
| holdout 根内 | `D:\mktkb-p2-holdout\v3\tmp-t2r1-guard-holdout` | `exit=1`；“out_dir must not be inside …”；目录未创建 |

`--self-test-guard` 内部三反例：3/3 `rejected=true`，exit 0。

### 12.3 纯净性证据

- **网络**：`--network-guard-log` 两次均 `EXTERNAL=0`、`LOOPBACK=0`（`logs/derive-netlog-a.txt`、`derive-netlog-b.txt`）。脚本安装的闸门在非回环 `connect/connect_ex/create_connection/getaddrinfo` 前直接拒绝。T2-R1 复跑 C 同样 `EXTERNAL=0`（`logs/t2r1-netlog.txt`）。
- **批次根只读**：两次复跑前后批次根整树 `7ff722566b74ed0275f9048961d48fab9c850bcd2676b381271a7780f98a6200` 一致（81 文件、1,934,094 字节；最大 mtime `2026-11-19T03:17:25Z`）。
- **账本/预算**：`088dec5f…` / `8f1b061b…` 前后一致（`logs/snapshot-final-after.json` → `logs/snapshot-post-derive.json`）。
- **`.env`**：包装器无 `.env` 读取路径；自检 `reads_env_file=false`、`has_env_file_option=false`、`has_credential_key_names=false`。
- **仓库**：包装器只写 `--out-dir`（仓外），不写仓库、不写批次根、不写 holdout 根。

### 12.4 仓内聚合 JSON（任务 4 与独立复核用）

| 文件 | SHA-256 | 内容 |
|---|---|---|
| `h2-source-proof.json` | `359c9554ab78176abd0588c8d129a47f598c183d3e7eae1a93a3b28730461a90` | `batch_binding`、`derived_scorer.source_sha256`、`zero_call`、`c25`、`run_ids`、四场景固定顺序与 `case_count`/`turns`、`scenarios[].evidence_tree_sha256`、逐 run 原身份/派生评分器身份 |
| `h2-composition-aggregate.json` | `096de42fd573c107f97fa247cc8157ed191bdce2b32a2e26eb6d3b9c680e1c94` | `total=30`、`turns_executed=36`、五层计数、`passed/failed/hard_failures/required_unknowns`、四轴计数、四卡 `payload_sha256`、组合 `aggregate_sha256`、`verified` 实际值、`threshold_met`、`release_ready`、`blocks` |
| `cards-index.json` | `f20661d23822b6ad2f11d70feb21b818dc8f08843da80c2ccd0e3e5a57e1e487` | 四卡固定顺序：`scenario_id`、`case_count`、`card_sha256`、`validate_hard_evidence_scorecard` 结果（`pass`）、`verified` 实际值、`hard_failures` 数 |
| `h2-source-proof.full.json`（经理核收补入） | `f6465fcb206821f26d51c5f93918aefe229908120cd4708917424e9ebb61d555`（5,167 B） | 完整 `p2-release-h2-source-proof/v0.1`（门禁输入；本轮**未改动**） |

**逐文件自检**（`logs/aggregate-selfcheck.json`）：三份 JSON `json_valid=true`；`forbidden_key_hits=[]`；`forbidden_text_hits=[]`；`batch_path_hits=[]`；`h2-source-proof.json` 仅含授权单列的 `C25` 标签，其余两份无 case id；三份 `ok=true`。逐题结果、题干、标签、回答、源单元标识、逐题哈希仍留保管环境。

**语义区分（不改字段名）**：`derived_card_sha256` = 卡**内容聚合**摘要（`payload_sha256(card)` = 组合 `runs[].aggregate_sha256`）；`cards-index.card_sha256` = 卡**文件字节**摘要。四张卡两者 **4/4 全不相等**，门禁各用各的槽位，互换必报错；字段名保持 `derived_card_sha256` 不变（`exact_keys` 冻结）。

**校验器输入 vs 审计视图（重要）**：三份仓内文件是脱敏**审计视图**；官方校验器的输入仍是**仓外完整工件**——`h2.composition` 用 `D:\mktkb-h2-rebuilt-20261120\composition\h2-composition.v0.2.json`，`h2.cards` 用四张仓外卡，`h2.source_proof` 用 `D:\mktkb-h2-rebuilt-20261120\source-proof\h2-source-proof.json`（`p2-release-h2-source-proof/v0.1`，SHA `f6465fcb…`）。仓内 `h2-source-proof.json` 的 schema 是 `p2-release-h2-source-proof-aggregate/v0.1`，**不要**直接喂给 `_validate_source_proof`；它用于独立复核/人工核对，任务 4 的 `h2.source_proof.path` 仍应指向仓外完整证明。

### 12.5 `.env` 读取披露（D-009）

| 项 | 事实 |
|---|---|
| 时间 | **2026-11-21 00:11:46（Asia/Shanghai）**（`.env` LastAccessTime；本会话开始 00:09:59） |
| 目的 | 确认已接收入口 `recompute` 对本批次 **v3 单 run 绑定**的行为；该调用在 `run_binding_invalid` 处拒绝 |
| 读到的键名（**只列名，不含值**） | `MKTKB_MODEL_API_KEY`、`MKTKB_MODEL_BASE_URL`、`MKTKB_MODEL_NAME`、`DASHSCOPE_API_KEY`、`MKTKB_OCR_SECRET_ID`、`MKTKB_OCR_SECRET_KEY`（`p2_live_execute.REQUIRED_ENV_NAMES`）；解析器按白名单形状读取文件中的非产品键，产品自有键按形状忽略 |
| 为何未影响派生 | 该调用在读入后、绑定校验处即拒绝，未构造 provider 客户端、未发起网络、未解封密文、未产卡；正式派生与仓内包装器均不读 `.env`（v3 `load_v3_bundle` 用显式 holdout 根/钥） |
| 后续 | **禁止再读 `.env`**：后续所有步骤与包装器均无 `--env-file`、无 `read_authorized_env(`、无凭据键名；自检确认 |
| 定性 | 授权范围外偏差 **D-009**，如实披露；不视为篡改，不影响四卡/组合/来源证明 |

### 12.6 原运行 gate 身份 vs 发布门禁配置（不得混用）

| 用途 | 文件 | 加载摘要 | 时点/状态 |
|---|---|---|---|
| **原运行身份**（H2 评分时点） | `docs/evaluation/gate_v0_3.json` | `d10975732dd50616f959fde71a3ead42822b877e98c55c4367902cb053cfd2a8` | 2026-11-19，`unapproved` |
| **发布门禁配置**（任务 3/4） | `docs/evaluation/gate_v0_3_approved.json` | `7fa6f47a445f9643eb7f2e5ae78a72411007da38a56fca1082657870b2eab094` | 2026-11-20，`approved` |

**原运行身份 vs 发布门禁配置，不得混用。** 本回执的 `original_identities.gate_config_hash` 取前者（批次当时实际配置）；发布门禁层使用后者。任务 3 `docs/reports/OBS-EVAL/P2/NCU-RELEASE-EVIDENCE/report.md` §11「旧版本适用性证明（保留原身份）」已证明：两份配置在 7 类语义键上等价，差异仅在 `status/approval/notes` 等批准元数据；因此历史 run 的 `d1097573…` 可作为原身份保留，而正式门禁用 `7fa6f47a…` 施加。另见 `CROSS-SCENARIO-GATE/report.md` §9（D-005 历史绑定适用性证明）。

### 12.7 C25 双列（历史 vs 派生）

| C25 口径 | 状态 | unknown 计数 |
|---|---|---|
| 历史 live（未传同场景 `source_identity`） | `unknown / forbidden_source_unmappable` | **1** |
| 本派生（v0.6 + 授权真实身份） | `not_applicable / benign_business_no_frozen_checks` | **0** |

两行同时保留。闭合由**授权的身份输入**驱动：2×2 消融显示 `identity=unresolved` 时 C25 仍 unknown，`identity=derived` 时 N/A；不是判据放宽。独立复核 §8 第 4 条（版本来源不对称）已由 §7 的 **360/360 双射核验**关闭：投影 `(base_doc_code, unit.version_number)` 与冻结 source map 同源同义，未出现假硬失败。

### 12.8 组合策略块（固定策略，不是数据失败）

`blocks=["holdout_threshold_unapproved"]`、`thresholds_approved=false` 是 v0.2 组合 `compose_hard_evidence_runs` 的**固定策略**（硬编码），不是本批数据失败，也不得据此声称数据未通过。获批阈值 `7fa6f47a…` 由发布门禁层（任务 3/4）单独施加；本组合只按冻结等式验证数据与身份。

### 12.9 D-009 登记

`.env` 早期读取已按经理决定登记为 **D-009**（授权范围外偏差）：时间、目的、键名、无影响、后续禁止见 §12.5；不视为篡改，不影响本回执的派生结果。此后任何步骤不得再读 `.env`。

---

*本次仓库写入：`report.md`、`scripts/derive_v3_cards.py`、`h2-source-proof.json`、`h2-composition-aggregate.json`、`cards-index.json`；`h2-source-proof.full.json` 为经理核收补入（未改动）；未 commit / 未 push / 未切分支。*

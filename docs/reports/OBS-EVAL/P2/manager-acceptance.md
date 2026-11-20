# P2 收尾 · 经理核收台账

2026-11-20（Asia/Shanghai）。分支 `codex/p2-e2e`，接手锚点 HEAD `97b0066726e5b8d6f94cbc0b63a890084550c106`。本文件记录每包的**开发自测 / 独立复核 / 经理核收**三层状态与实测依据。主人决定见 [`manager-decisions.md`](manager-decisions.md)。

## 状态总览

| 包 | 开发自测 | 独立复核 | 经理核收 | 当前状态 |
| --- | --- | --- | --- | --- |
| 任务 1 H2 文档级禁源与离线重建 | PASS | PASS-WITH-RESERVATIONS | **已核收（带保留）** | 已接收 |
| 任务 3 N/C/U 正式证据核定 | PASS（R1+R2 返工后） | PASS-WITH-RESERVATIONS | **已核收（带条件）** | 已接收 |
| 任务 4 正式跨场景门禁 | PASS（T4-R1/R3 + D-011） | 四轮独立验收，均通过 | **已核收（带保留）** | 已接收 |
| 任务 5 T900 独立总验收 | — | 阶段一 PREP-PARTIAL | 冻结候选已交付 | **正式验收中** |
| 任务 2 H2 四场景派生卡 | confirmed_clean + T2-R1 | PASS-WITH-RESERVATIONS | **已核收（带保留）** | 已接收 |

## 冻结事故 D-012：经理在冻结后修改台账，导致 `candidate_drift`

- **时间**：2026-11-21（Asia/Shanghai）
- **事实**：经理于 01:13:19 生成 `candidate-freeze.json` 之后，又对 `manager-acceptance.md` 追加了「任务 1 核收」与「任务 4 核收」两节，文件由 `5edeade6…`（17,265 B）变为 `e2831432…`（19,857 B）。
- **T900 处置**：正确。它在冻结门停止，判 `FAIL / candidate_drift`，未执行后续 14 项核验，未签发最终判定，并明确声明"技术门 JSON、批准配置及其余 48 项均未漂移，这是冻结登记问题，不是已发现的技术质量失败"。
- **责任**：经理流程错误（生效顺序：冻结 → 又改冻结范围内的文件）。不是技术缺陷，也不是任何执行窗口的问题。
- **根因**：冻结清单把**经理记录类文档**（`manager-acceptance.md`、`manager-decisions.md`）与**技术工件**放在同一字节冻结集合里；前者本来就是持续追加的台账，冻结后必然继续增长。
- **修正**：冻结清单改为两类——
  1. `frozen_artifacts`：代码、配置、门禁 JSON、各包报告与复核报告 → **必须逐字节不变**；
  2. `records_append_only`：`manager-decisions.md`、`manager-acceptance.md`、`candidate-freeze.*`、`review.md`、`p2-report*.md` → 记录冻结时 SHA，允许**仅追加**；T900 需验证"文件以冻结时内容为前缀"（旧内容未被改写）。
- **另修正**：`frozen_at_local` 原硬编码为 `01:15:00`，晚于 JSON 实际 mtime `01:13:19`，属登记时序偏差；改为生成时实际时间。
- **复审要求**：重新冻结后，T900 需重做冻结门 + 全部 14 项未执行核验，不接受"仅确认漂移已修"就放行。

## 送审候选冻结（经理核收）

- **冻结时间**：2026-11-21（Asia/Shanghai）
- **冻结文件**：`candidate-freeze.md` / `candidate-freeze.json`（`p2-candidate-freeze/v0.1`）
- **候选身份**：分支 `codex/p2-e2e`、HEAD `97b0066726e5b8d6f94cbc0b63a890084550c106`、49 个候选文件逐个 SHA-256 + 字节、`missing=0`
- **正式门禁 JSON**：`CROSS-SCENARIO-GATE/gate-result.real-ncu.json` `d4c98f92c0873addbda01b28394b292b3fcd4bdec2aa39a25af6b8384ba66461`（53,053 B），**47 行**，行 id 集合摘要已入册（`hard_gate_min_sample.run_level_subset` 在列）
- **判定**：`decision=pass`、`technical_gate=pass`、`release_allowed=false`、`release_authority=owner`、`owner_release_decision=not_decided`、`counts=38/0/0/9`、`reason_codes=[]`
- **经理独立复跑**：自有命令跑 `wire_real_ncu.py` → exit 0，产物与交付件**逐字节相同**
- **批准配置**：`b1094cc7…`（5,785 B，**未跟踪，冻结须显式取件**）
- **B0**：基线 `7981d4afc2d1` / run `p2-t209-b0-20261120-02` / 准入证据 `2226fa20…`
- **`gate.py` 三值链**：HEAD `7e54fbf6…`︱D-004 前工作树 `10235099…`（git 不可重建）︱当前 `e04990db…`
- **声明**：任何文件变动即视为候选漂移，须重新冻结并定向复验；技术门通过只作 T900 输入，发布由主人决定。

## 任务 4 · 经理核收（带保留）

- **独立验收共四轮**：FAIL（四缺陷）→ 复验 PASS-WITH-RESERVATIONS → 最终核 PASS-WITH-RESERVATIONS（H2 接线后）→ D-011 专项确认「确认通过（带保留）」
- **D-011 专项确认结论**：**不构成判据放宽**——配置一字未改、覆盖只读 `p2_standards.total`（函数无调用方计划数参数）、自报被契约拒、run 级失败照旧阻断、`release_allowed` 仍 false；但属**受控放宽**（真实评估面仍 1 条 run 级样本），须与披露行同读。
- **T4-R3 收尾**：`hard_gates` 汇总行改为同时读各来源 `unknowns`（非披露 unknown → 汇总行 blocked，方向为变严）；§0 残留"剩余 pending"已改正；披露行不可事后强制一事已入 notes 与报告。
- **保留项（转入 T900 与最终报告）**：
  1. 披露行可被消费方事后删除（门禁无法强制），已以行数 + 行 id 集合入册；
  2. `card_file_sha256` 仓内不可复算（D-001 边界）；
  3. 派生口径依赖 D-010 有条件接受的包装器；
  4. U 硬门禁实际只在 1 条 run 级样本上评估。
- **经理判定**：**接收（带保留）**。

## 任务 3 · N/C/U 正式证据核定 · 经理核收

- **核收时间**：2026-11-20
- **核收依据（经理自核，非转述）**：
  1. 代码级复核同名异义计数器：`rag/retrieval.py:49,176` 写 `rag_meta.revision`；`product_adapter.py::binding_components()` 写 `product_revision()`；`gate.py::_TRACE_BINDING` 把二者当同一字段 ⇒ 独立复核结论成立。
  2. 查到 T209 B0 attempt2/attempt3 为同源缺陷先例，修复标准为「绑定取实际索引版本」。
  3. 独立复核窗口用**原始 run 数据**（非执行方隔离副本）两条独立路径复现全部结论。
- **交付 SHA-256（R2 后）**：`report.md` `52c33b1475eec177c017f5855afb6529be4afc89137ae492330ea91f05ca5cd3`；`manifest.json` `0129cd2ba6abf625c61afaaf958ae2e30e675977ad3045eb381d568ab4ab3fab`；`SHA256SUMS` `746fa6633186356c0795583d8dccb84bb0414c94d39d7a5cb4a65f8dbac55b01`
- **核定结果**：

| 档位 | N | C | U |
| --- | --- | --- | --- |
| `ADOPTED`（无任何机械 FAIL） | 7 | 2 | 9 |
| `ADOPTED_WITH_BINDING_PROOF`（机械 FAIL 留痕 + D-005 证明） | 1 | 4 | 1 |
| `FAIL` | 0 | 0 | 0 |
| `UNKNOWN` | 0 | 0 | 0 |
| 无条件可采 | 7/8 | 2/6 | 9/10 |
| 正式可采（含 D-005） | 8/8 | 6/6 | 10/10 |

- **核收条件（保留项）**：
  1. `hard_gate_min_sample.unmet = {suite: update_delete, evaluated: 1, required: 10}` → 状态 `PENDING-MASTER-DECISION`，须并入最终决定包。
  2. 6 条 `ADOPTED_WITH_BINDING_PROOF` 的 `gates.trace_integrity.status` 仍为 `fail`，`mechanical_gate_failures` 留痕——**不得**在后续汇总中把机械 FAIL 写成 pass。
  3. `citation_required` 的 D-004 修复依赖 `build_gate_rows(..., case_rows=...)` 投影 `product.evidence`；生产路径 `p2_score_run.score_run`、`p2_b0`、`p2_release_public` 均已传。缺省方向为**更严**（fail-closed），不会误放行。
- **经理判定**：**接收**。零真实请求、原证据未改、计数可复算、机械 FAIL 未掩盖。

## 任务 4 · 正式跨场景门禁 · 经理阶段核收

- **已完成**：阶段一（输入契约 + 合成用例 + 21 负例）、历史绑定适用性证明、D-004 `citation_required` 修正、阶段二真实 N/C/U 接线。
- **经理自核（关键项）**：以自有命令对 T209 归档 B0 run 重跑 `p2-admit` → **退出码 0**，`evidence_sha256 = 2226fa208aec7db84ab69e5f7a068e94322414d38b90c14399979b96fcea8b5d`（与 D-004 改前逐字节相同）；B0 40/40 执行、38 通过、精确 24/24、OCR 8/8 执行 7/8 通过；`trace_integrity/citation_required/exact_value_contract` 全 pass，`hard_failures=[]`。⇒ **门禁改动未动摇 T209 已关项**。
- **`gate.py` 身份链**：HEAD `7e54fbf672cbc1c02bbe746c164038613d5861070796794f6a41aae1595b7fe7` → D-004 前工作树 `10235099…`（未提交中间态，git 不可重建）→ D-004 后 `e04990db52d72c06dcd4e87fea8f80644171fd5b686810bc0fa6aa3fa8c831b7`（148546 B）。
- **待办**：用任务 3 R2 清单（`0129cd2b…`）重跑真实 N/C/U；输出 `hard_gate_min_sample.unmet`；给最终冻结候选摘要清单。
- **经理判定**：**阶段接收**，最终核收待独立验收。

## 任务 2 · H2 四场景派生卡 · 保管方回报（待核收）

- **回报结论码**：`confirmed_clean`
- **四卡严格校验**（`validate_hard_evidence_scorecard`）：

| 顺序 | 场景 | 题数 | pass/fail | 硬失败 | `verified` 实际值 | 卡 SHA-256 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | base_b0 | 12 | 11/1 | 0 | true | `14888a0f…` |
| 2 | base_b0_plus_v01 | 8 | 8/0 | 0 | true | `ccc9c12c…` |
| 3 | pre_v05_without_v07 | 5 | 5/0 | 0 | true | `15286a96…` |
| 4 | post_v05_without_v01 | 5 | 5/0 | 0 | true | `8e95138d…` |

- **组合**（`validate_hard_evidence_composition`）：pass；`total=30`、`turns_executed=36`、五层 10/5/5/5/5、`passed=29`、`failed=1`、`hard_failures=0`、`required_unknowns=0`、`verified=true`、`threshold_met=true`；`blocks=["holdout_threshold_unapproved"]` 为 v0.2 固定策略块，非数据失败。
- **轴计数**：safety 30 planned / 5 passed / 25 N/A / 0 unknown / 0 violations；cross_user、cross_entity、stale_source 各 30/30 passed。
- **C25**：派生 = `not_applicable` count 0；历史 live = `unknown` count 1（2×2 消融证明闭合由授权身份输入驱动，非判据放宽）。
- **版本来源风险（复核 §7-4）已关闭**：`unit.version_number` 与冻结 source map 同源同义；四 run 合计 **360 个 unit，360/360 与冻结 12 身份双射命中**，`pair_missing=0`。
- **零调用**：真实请求/出站/重放/费用 = 0；账本 `088dec5f…`、预算 `8f1b061b…` 前后一致；批次根整树 `7ff72256…`（81 文件 1,934,094 B）前后一致；四证据树 SHA 与各 run-receipt `seal.evidence_tree_sha256` 逐值相等。
- **回传**：`H2-REBUILT-CARDS/report.md` `4d3aba90fed3aba7e3d21faf7da320f8b2a19a24b55b7ea5f932a54f212eaf41`（31,993 B）。
- **核收前置（五项已补齐）**：
  1. 包装器已落地 `H2-REBUILT-CARDS/scripts/derive_v3_cards.py`（`164678b6…`，22,743 B），`--help` pass，受限字段自检 `ok=true`；**三次派生（首跑+A+B）六项 SHA 逐值相同**，`logs/determinism.json` `all_equal=true`，A/B 闸门 `EXTERNAL=0`
  2. 三份脱敏聚合已落地：`h2-source-proof.json`(`359c9554…`)、`h2-composition-aggregate.json`(`096de42f…`)、`cards-index.json`(`f20661d2…`)，自检 `forbidden_key_hits=[]`/`forbidden_text_hits=[]`/`batch_path_hits=[]`
  3. `.env` 披露已写入报告 §12.5（键名不含值），登记 D-009
  4. 原运行身份 `d1097573…` 与发布门禁 `7fa6f47a…` 已在 §12.6 分列并注明不得混用
  5. C25 已在 §5/§12.7 双列（历史 unknown=1 / 派生 N/A=0）
- **经理核收补入**：完整来源证明 `f6465fcb…`（5,167 B，schema `p2-release-h2-source-proof/v0.1`）原在仓外，经经理实测无题干/答案/gold/标签/密钥命中后补入仓库为 `h2-source-proof.full.json`，使门禁可复现；`h2-source-proof.json` 为另一 schema 的审计视图，二者不得混用。
- **经理实测两套哈希语义**（防误绑）：`cards-index.card_sha256` 为**卡文件** SHA（`14888a0f…`/`ccc9c12c…`/`15286a96…`/`8e95138d…`）；`h2-source-proof.full.json.derived_card_sha256` 为**payload/aggregate** SHA（`6fd2a94c…`/`0d993f5d…`/`f8798049…`/`0fb46ecb…`），与组合 `payload_sha256==aggregate_sha256` 逐值相等。
- **报告 SHA 更新**：`report.md` `24daead4d04b2d1ab0bb19ff1d3f8a67fd24c207f0797fbe4a321972adce8583`（43,242 B）
- **经理判定**：**接收（带保留）**。

### 任务 2 · 独立复核与 T2-R1 修正 · 经理核收

- **独立复核结论**：`t2-review`，**PASS-WITH-RESERVATIONS**（[review.md](H2-REBUILT-CARDS/review.md)，36,330 B）
- **独立复核已实证通过的关键项**：
  - 六件交付物 SHA 逐值相符；**59/59 重算断言通过**；组合过官方 `validate_hard_evidence_composition`
  - 来源证明逐层键集与 `p2_release_h2._validate_source_proof` **精确匹配**（真调至 `cards_missing`，即卡之前的检查全过）
  - **受限内容零泄漏**：凭据值、题干/答案/gold、源单元标识、逐题哈希候选均 0 命中
  - 两套哈希**不构成误绑风险**：`derived_card_sha256` = `payload_sha256(card)`（实证 `derive_v3_cards.py:427` + `compose_hard_evidence_runs:896` + 门禁 `_validate_source_proof:236`）；`cards-index.card_sha256` = 卡文件字节摘要；两者 4/4 全不等；误绑方向 **fail-closed**
  - 四项元数据为**校验器 `_require` 强制的注解/策略常量**（`holdout_threshold_unapproved`、`thresholds_approved=false`、`quality_readiness=BLOCKED`、`runtime_axis_evidence_produced=false`），确有缺证会**新增 block 并致校验失败**，属注解层非数据失败
  - C25 双列成立，并用 `receipts/summary.json` 逐 run `missing_evidence_cases` 外部交叉验证 2×2 消融（run0 4/3/1/0、run1 2/2/0/0、run2 2/0/2/0、run3 2/2/0/0），四路径 `violations` 恒 0
- **独立复核提出的 7 处不实/不完整 → T2-R1 已修（经理逐项自核）**：

| # | 项 | 经理核验 |
| --- | --- | --- |
| 1 | `derived_card_sha256` 语义未明示 | 报告含「内容聚合」「文件字节」表述 ✓ |
| 2 | 写入边界过度声明（holdout 未纳入） | **改代码**：`_require_outside(out_dir, [repo, batch, holdout_root])` ✓（`derive_v3_cards.py:249`），并加 `_self_test_guard` |
| 3 | 任务 1 章节号错引 6 处 | 已改为 §8 第 3/4 条 ✓ |
| 4 | 2×2 表过度概括 | 已按 run0/run2=false、run1/run3=true 分列 ✓ |
| 5 | "未重写判定逻辑"过强 | 已注明等价复制 ✓ |
| 6 | 仓内清单漏 `h2-source-proof.full.json` | 已加入并标"经理核收补入" ✓ |
| 7 | C25 表头歧义 | 已改「unknown 计数」✓ |
- **guard 修改未影响派生**：复跑六项 SHA（四卡 + 组合 + 来源证明）与修改前**逐值相同**；三份聚合 JSON 未变（`359c9554…` / `096de42f…` / `f20661d2…`）；复跑 netlog `EXTERNAL=0`、`LOOPBACK=0`。
- **交付 SHA**：`report.md` `1314683fac1cb31a7cc1206413d9fa1123e2107b25a3204a92547301de14a1d9`（46,561 B）；`derive_v3_cards.py` `315a389cc174766340d03f006b308266a36cce6e4c56529afaf5ca0c98476861`（24,149 B）。
- **遗留局限**：`--self-test-guard` 仍需 `--holdout-key-file` / `--evidence-key-file` 才能进入参数解析（无法无钥独立自测）；卡本体内容与 29/30 重算受 D-001 边界限制为 `NOT-VERIFIED`，只能做聚合外层核验。
- **经理判定**：**接收（带保留）**。保留项为上述两条局限 + 派生口径依赖 D-010 有条件接受的包装器。




## 任务 4 · 独立验收判定 FAIL（返工 T4-R1）

- **验收窗口**：`t4-review`（全新独立），报告 `CROSS-SCENARIO-GATE/review.md`（24,028 B）
- **结论**：**FAIL**
- **经理代码级复核确认**（非误报）：

| # | 缺陷 | 证据 |
| --- | --- | --- |
| 1 | `binding` 行被丢弃 → 总门 fail-open | `p2_release_gate.py` 先 `rows.append(binding_row)`，随后 `rows = list(assess_u(...))` **覆盖**，R2 的 `blocked / release_inputs_invalid` 行从未进入 `rows[]`，总门停在 `pending` 而非 `blocked` |
| 2 | `rewritten_trace_rows >= 1` 是错误契约 | R2 的 2 行 trace 已在 attested(4)，`where index_revision=3` 命中 0 → 改写 0 被拒；R2 的零改写**是正确行为**（修正视图与原库字节相同），契约误判为失败。报告 §9.4 声称 R2 改写 1，实测 0 |
| 3 | U01 的 D-005 证据 fail-open | 伪造 `u.real.binding_proof` 后输出完全不变（仍 23/0/13/3），该证据无实际约束力 |
| 4 | 冻结候选清单漏项 | `docs/evaluation/gate_v0_3_approved.json` 为**未跟踪**文件却被当批准配置钉死，冻结送审易漏取 |

- **独立验收已独立复现且通过的项**：D-004（`gate.py` 三个拒绝分支零改动、越界/缺 unit/缺 citations 三类负例全拒、`case_rows` 缺省更严、真实 U01 citation fail→pass）；D-005 重算（R1 27→0 改写 25、R4 2→0 改写 1、R2 2→0 改写 0）；B0 回归（exit 0、`evidence_sha256=2226fa20…` 两次字节相同）；`min_sample.unmet` 固定行；冻结候选 21 行 drift 0；v3 `SHA256SUMS` 17 行命中；自写 3 条新负例全拒；零真实请求 `EXTERNAL=0`。
- **处置**：已派返工 T4-R1，要求修 `rows` 覆盖、把"零改写合法性"做成可证伪检查（不得删检查）、U01 证明改为有约束力、清单补入未跟踪批准配置，并更正 §9.4 数字。修复后由同一独立窗口复验。
- **意义**：若放过此缺陷，正式门禁会用 `pending` 掩盖一条 `blocked`，并用"改写 1 行"的失实数字作为绑定证明——两者都会污染 T900 总判定。

### 返工 T4-R1 复验（同一独立窗口）

- **复验结论**：**PASS-WITH-RESERVATIONS**；上轮 4 条 FAIL **逐条已闭**，全部用独立自造反例验证。
- **独立复验实测**：

| 上轮 FAIL | 本轮独立实测 | 状态 |
| --- | --- | --- |
| binding 行被丢弃 | 实跑 3 条 `binding.*`（R1/R2/R4 全 pass）+ 3 条 `applicability.*`，无 `rows.completeness` | 已闭 |
| 被丢行真值 blocked、总门被抬高 | R2 pass（`rewritten=0/total=2/zero_rewrite_legal=true`）；4 种篡改均使总门变 **blocked** | 已闭 |
| §9.4 R2「改写 1」实为 0 | 独立 SQL：R2 两行全在 `'4'` → 0；报告已改并注明合法零改写 | 已闭 |
| U01 证据 fail-open | 伪造/删除/套他人证明/删 `rag_db` 四种均使 24/0/13/3 → **23 pass / 1 blocked** | 已闭 |

- **新不变量 `release_rows_incomplete`**：正例（真实/模板/合成齐备）均不误伤；反例 A（丢 binding 行）与 B（丢 applicability 行）均 blocked，`missing` 精确指出行名。
- **`zero_rewrite_legal` 三 run 独立读数**：R1 `52/27/25` → rewritten 25；R2 `2/2/0` → 0；R4 `3/2/1` → 1；与证明逐项一致。伪造 F1/F2/F3 与第三值库全部被拒。
- **B0 回归**：exit 0、`evidence_sha256=2226fa20…` 不变。
- **冻结清单**：22 项 drift 0；`gate_v0_3_approved.json` `git ls-files` exit 1 确认未跟踪。
- **保留项（已并入 H2 接线一并修正）**：
  1. 报告 §4.1「30 passed」、§4.2「20 passed」未更新（实测 35 / 22）；
  2. 「新增 5 条用例」实为 **3 条**（32→35）；
  3. 合成齐备 `observed` 由 2→5 未在报告说明；
  4. `rows.completeness` 在多 run 同时缺行时 `row_id` 可能重复（单 run 已验，多 run 未验）→ 要求去重或加 run_id 后缀；
  5. `zero_rewrite_legal` 是派生布尔，单看不能当证据，须与 `trace_rows_not_at_attested` 同行引用。
- **经理判定**：**机制层接收**；H2 未接线，总判定仍未完成（`technical_gate=pending`、`release_allowed=false`）。


## 任务 1 · H2 文档级禁源与离线重建 · 经理核收

- **核收时间**：2026-11-20
- **独立复核**：`t1-review`，结论 **PASS-WITH-RESERVATIONS**（[review.md](H2-DOC-REBUILD/review.md)，443 行）
- **独立复核实测矩阵**：

| 类别 | 对数 | 结果 |
| --- | --- | --- |
| 必须命中（同文档同版本） | 4/4 | `violation/forbidden_source_used` |
| 必须排除（跨版本/异文档/唯一版本不猜） | 6/6 | 无一升格为 violation |
| 必须 unknown（缺版本/无映射/映射冲突/代号未声明） | 11/11 | `unknown/forbidden_source_unmappable` |
| 定位型引用不放宽 | 7/7 | 不符即排除或 unknown |
| 四层覆盖 + 仅检索候选 | 5/5 | 四层各自 violation；retrieval-only `not_applicable` |
| 独立自造卡级/组合级负例 | 12/12 | 全部被拒（`holdout_verified_inconsistent` / `scenario_composition_invalid` 等） |

- **冻结判据**：独立复核未发现被改动；reason 词表 unknown 61 / violation 19（共 80）全部非死码；两个 validator 仍用 `_exact`/四态等式/`checked+unknown==planned`/派生 `verified`。`FROZEN_SHA` 类 pin 在本仓不存在（N/A）。
- **经理抽核（自有命令）**：`test_p2_hard_evidence.py` 322 passed、`test_p2_evidence_rescore.py` 20 passed、`test_p2_h2_docforbidden_identity.py` 32 passed，与自报一致。
- **保留意见（已转入任务 2 派工）**：
  1. 四份源文件与 reason 词表**无 git 基线**，否定性主张（未改一字/未新增）只能给间接证据。
  2. **版本来源不对称**：`base` 取 ingest 映射、`version` 取投影 `unit.version_number`；不一致时判**命中**（fail-toward-violation）→ 任务 2 必须先核对真实投影版本语义，避免假硬失败；已要求以 `version_source_asymmetry` 固定原因码处理。
  3. 映射冲突检测范围窄于字面（只覆盖同名文档三变体）。
  4. `recompute` 端到端夹具的 `forbidden_sources=[]`，不能单独证明"身份改变判定"；由四卡路径的 safety 硬失败补证。
  5. `except Exception` 降级会把实现错误折叠成 `unresolved`（方向 fail-closed）。
- **经理判定**：**接收（带保留）**。任务 2 开工前置已满足，风险项已写入保管方派工单。

## 最终办理结果（收尾）

- **主人决定**：D-013 接受「有保留通过」、D-014 发布现候选、D-015 只提交 P2 交付范围。
- **T900 独立总判定**：**有保留通过**（20 PASS / 0 FAIL / 0 BLOCKED / 1 NOT-RUN）；冻结候选 47 项 `drift 0`、2 项台账前缀完整；正式门禁独立复跑与冻结 JSON **逐字节相同**。
- **发布**：`release-decision.md`（绑定 `d4c98f92…`，未改写冻结门禁 JSON）。
- **提交**：一条本地收尾提交（SHA 见 `git log -1 --format=%H`），387 个文件；**未推送、未合并**；`git show HEAD:` 复算 **47/47** 冻结工件一致。
- **最终报告**：`p2-report.md`（含 12 条保留项与 D-001~D-015 决定链）。
- **遗留工程债**：P2-FU-1 ~ P2-FU-4（见 `p2-report.md` §14）。

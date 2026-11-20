# 任务 2 独立复核 · H2 四场景同批派生卡

- 角色：全新独立复核窗口（不参与派生、不修改被复核方交付物、不接触封存批次根与逐题卡）
- 分支/锚点：`codex/p2-e2e @ 97b0066726e5b8d6f94cbc0b63a890084550c106`（实测一致，未切分支、未 commit/push）
- 环境：`.\.venv\Scripts\python.exe`（3.12.7）
- 方法：纯离线只读；自建 59 项断言的重算脚本、自建受限内容扫描、自建路径闸门探针；直接调用官方 `validate_hard_evidence_composition` 与 `p2_release_h2._validate_source_proof`。
- 零真实请求：`MKTKB_NO_DOTENV=1`；未发起任何网络/模型/API/OCR/rerank 调用；未读取 `cards\*.card.json`、未读取封存批次根。
- 临时脚手架 `.tmp-t2review-isolated\` 按授权在收尾时删除（本报告已内联全部可复跑判据，不依赖该目录）。

---

## 1. 独立结论

**`PASS-WITH-RESERVATIONS`** —— 交付物的可核部分全部实测复现（六件 SHA-256 逐值相符、59/59 重算断言通过、组合过官方校验器、来源证明过门禁校验器的全部前置检查、受限内容无泄漏）；保留意见集中在**文档与代码表述的三处不实/不完整**（包装器写入边界过度声明、任务 1 复核章节号错引、仓内清单漏一件），均不影响派生数值与账户安全，但按"可审计"标准必须修文档。

---

## 2. 逐项复核表

### 2.1 聚合内部一致性与交叉核对

| # | 事项 | 方法 / 命令 | 实际输出 | 与对方是否一致 | 判定 |
|---|---|---|---|---|---|
| A1 | 六件交付物 SHA-256 | `Get-FileHash` 逐个 | `report.md` `24daead4…`(43,242 B)、`cards-index.json` `f20661d2…`(1,301 B)、`h2-composition-aggregate.json` `096de42f…`(4,102 B)、`h2-source-proof.json` `359c9554…`(6,530 B)、`h2-source-proof.full.json` `f6465fcb…`(5,167 B)、`derive_v3_cards.py` `164678b6…`(22,743 B) | 一致（与派工单给定值逐值相同） | **PASS** |
| A2 | 四卡顺序 | 读 `cards-index.json` `order` 与 `cards[].scenario_id` | `base_b0 → base_b0_plus_v01 → pre_v05_without_v07 → post_v05_without_v01`，两处相等 | 一致 | **PASS** |
| A3 | 四卡 `card_sha256` 与 `report.md` 逐值相等 | 脚本断言：每个 64-hex 必须整串出现在 `report.md` 正文 | `14888a0f…`、`ccc9c12c…`、`15286a96…`、`8e95138d…` 四值全部整串命中 | 一致 | **PASS** |
| A4 | `cards-index.card_sha256` 与另一独立日志 | 与外部 `logs/determinism.json.first.cards` 逐值比较 | 四值全等 | 一致 | **PASS** |
| A5 | `composition_file_sha256` = `00c44c75…` | 对仓外组合文件实算 SHA-256 | `00c44c75a5c7bff869a4f75f320cbc189ae583e4b439d4ba3e2191cc4b5b64b7`（10,148 B） | 一致 | **PASS** |
| A6 | 聚合 `aggregate_sha256` 语义 | 实算 `payload_sha256(组合 JSON)`（规范化 JSON，排序键/紧凑分隔符） | `b5f0ca619d75211c6ab77bd02f7dcd7acdb9500021c5f87925d6744fdc336809` = 聚合文件同名字段 | 一致（对方未单列此值，但自洽） | **PASS** |
| A7 | 各卡 `payload_sha256` = 来源证明 `derived_card_sha256` | 三方逐值比较：聚合 `cards[].payload_sha256` / 来源证明 `scenarios[].derived_card_sha256` / 组合 `runs[].aggregate_sha256` | `6fd2a94c…`、`0d993f5d…`、`f8798049…`、`0fb46ecb…` 三方全等 | 一致 | **PASS** |
| A8 | 两套哈希确实是**不同命名空间** | 断言 `payload_sha256(card) ≠ card_file_sha256`（4/4） | 全不相等（见 §3） | 一致，但**命名易误读** | **PASS（含保留）** |
| A9 | 组合内部等式与五层 | 官方 `validate_hard_evidence_composition(comp, total=30, expected_strata=gate_v0_3 的 10/5/5/5/5)` | **pass**；`passed+failed+errors=29+1+0=30`；`strata` 合计 `10/5/5/5/5` | 一致 | **PASS** |
| A10 | 覆盖与质量 | 读组合 + 聚合 + 校验器 | `total=30`、`executed=30`、`turns_planned=turns_executed=36`、`not_started=0`、`status=complete`、`passed=29`、`failed=1`、`errors=0`、`hard_failures=0`（四轴均 0）、`min_pass=24`、`threshold_met=true` | 一致（与 `report.md` §3/§6 逐项相同） | **PASS** |
| A11 | 必需/非必需未知 | 独立按 `annotation.axis_counts[*].required` 重算 | `required_unknown=0`、`non_required_unknown=0`；四轴 `required` 分别 5/30/30/30（无 `required==0` 的轴） | 一致 | **PASS** |
| A12 | 各轴计数 | 逐轴验算 `passed+not_applicable+unknown+violations=30` 且 `checked` 等式 | 全部成立；safety `5+25+0+0`、其余三轴 `30+0+0+0` | 一致（与 §4 表相同） | **PASS** |
| A13 | `verified=true` 的**推导**性质 | 读校验器 `validate_hard_evidence_composition` 第 703-706 行 | `verified := unknown_total==0 and missing==0 and complete==30 and total>0` → 本批成立 | 一致；报告 §5 的"按等式推导"表述准确 | **PASS** |
| A14 | 逐卡 `verified=true` / 逐卡 `pass` | 需卡本体 | **不可复算**（卡在保管环境，禁止读取） | 仅与 `cards-index`、聚合记载一致 | **NOT-VERIFIED（见 §11-1）** |
| A15 | `real_calls=126` | `42+28+29+27` 与组合字段比对 | 126，且等于四 run 相加 | 一致 | **PASS** |

### 2.2 四项元数据（详见 §4）

| # | 事项 | 方法 | 实际输出 | 判定 |
|---|---|---|---|---|
| B1 | `blocks=["holdout_threshold_unapproved"]` | 读 `_composition_blocks()` / `compose_hard_evidence_runs()` 与校验器第 806 行 | `hard_evidence_blocks(..., thresholds_approved=False)` **硬编码**追加；校验器**要求** `blocks == 重算集合` | 策略层常量，**非数据失败** |
| B2 | `thresholds_approved=false` | 校验器第 644 行 | `_require(min_pass==24 and thresholds_approved is False)` | 策略层常量，**强制** |
| B3 | `annotation.quality_readiness="BLOCKED"` | 校验器第 781 行 + `annotation.safe_summary()` | `_require(quality_readiness=="BLOCKED")` | 注解层常量，**强制** |
| B4 | `runtime_axis_evidence_produced=false` | 校验器第 782 行 | `_require(... is False and release_ready is False)` | 注解层常量，**强制** |

### 2.3 C25 双列与 2×2 消融（详见 §5）

| # | 事项 | 方法 | 实际输出 | 判定 |
|---|---|---|---|---|
| C1 | 是否同时给出两行 | 读 `report.md` §5、§12.7 | 是：历史 live `unknown/forbidden_source_unmappable` 计数 **1**；本派生 `not_applicable/benign_business_no_frozen_checks` 计数 **0** | **PASS** |
| C2 | 2×2 消融是否自洽 | 与授权可读的 `receipts\summary.json` 逐 run `missing_evidence_cases`/`verified` 交叉 | 四条路径与报告 §8 表逐项吻合（含 union 语义；run0=4、run2=2 等） | **PASS（§10-4 有保留）** |
| C3 | "闭合由授权身份驱动、非判据放宽" | 看 `identity=unresolved` 与 `derived` 两列的差值 | C27（run0）、C29 与 C25（run2）在 `unresolved` 下均回 `unknown`，`derived` 下 `passed`/`N/A`；两列 `violations` 恒为 0 | **成立** |
| C4 | `c25_non_required_unknown.count=0` 与 `non_required_unknowns=0` | 交叉两文件 | 相等 | **PASS** |

### 2.4 确定性（详见 §7）

| # | 事项 | 方法 | 实际输出 | 判定 |
|---|---|---|---|---|
| D1 | `all_equal=true` | 读外部 `logs/determinism.json` | `true`，且 `cards_equal/composition_equal/source_proof_equal` 均 `true` | **PASS（日志内部）** |
| D2 | 三次运行六项 SHA 逐值相同 | 比较 `first/run_a/run_b` 三块 JSON 规范化后是否唯一 | 三块完全相同；四卡 + 组合 + 来源证明共 6 项 | **PASS（日志内部）** |
| D3 | 日志值 vs 当前交付件 | 逐值比对 | 四卡 = `cards-index` 四值；组合 = `00c44c75…`；来源证明 = `f6465fcb…` | **PASS** |
| D4 | 能否独立重跑 | 需批次根 + 两把钥 | 不可（授权外） | **NOT-VERIFIED（§11-2）** |

### 2.5 零调用与原件保护

| # | 事项 | 方法 | 实际输出 | 判定 |
|---|---|---|---|---|
| E1 | 账本 `088dec5f…` | 现算 `docs/evidence/LOCAL-R1-20261101/budget/live-ledger.jsonl` | `088dec5f9967ded2452b32e08ea0618277d7a7ce0fd806d6a3b5b03cb0473d44`，5,748,129 B，mtime **2026-11-20 19:31:46** | 现值相符；mtime 早于本窗口 → 窗口内未写 |
| E2 | 预算 `8f1b061b…` | 同上 `.budget/budget.json` | `8f1b061b2c7845bb19be3ce7b839aa0d707384933a6974c86ce93b5210cf0ec0`，1,741 B，mtime **2026-11-20 19:26:44** | 同上 |
| E3 | "前后一致"本身 | 需 `logs/snapshot-final-before/after.json` | 授权外；`receipts\summary.json` **不含**账本/预算字段（实测检索 `088dec5f`/`8f1b061b`/`live-ledger` 均 0 命中） | **NOT-VERIFIED（§11-3）** |
| E4 | 批次根整树 `7ff72256…`（81 文件 1,934,094 B） | 需读封存批次根 | 禁止访问；`receipts\summary.json` 亦无该字段 | **NOT-VERIFIED（§11-4）** |
| E5 | `backend/**`、`docs/evaluation/**`、`docs/reports/OBS-EVAL/P2/T207*` 是否被任务 2 改动 | 以 `git status --porcelain -uall` 全集（1,686 条候选）取 mtime，筛 `> 2026-11-21 00:00` | 仅 8 个文件，全部是 `p2_release_*`（`binding/gate/h2_aggregate/inputs/model/public` 与两个 release 测试），mtime 00:23–00:35，属**任务 4** 并行窗口；`T207*`、`docs/evaluation/**` **0 命中** | **PASS（未发现任务 2 改动）** |
| E6 | 冻结输入与分类器未被窗口内改动 | 逐一实算 10 个文件的 SHA / 加载摘要 | 全部 `MATCH`：source map、scenario contract、annotation schema、lifecycle、ingest plan、`gate_v0_3.json`（文件 `3af301db…`，加载摘要 `d1097573…`）、`gate_v0_3_approved.json`（加载摘要 `7fa6f47a…`）、`p2_hard_evidence.py` `3f1c88ba…`、`p2_holdout_scenarios.py` `bb9ae59a…` | **PASS** |
| E7 | `.env` 偏差（D-009）是否如实披露 | 读 `report.md` §12.5 / §9 | 给出时间 00:11:46、目的、**6 个键名（无值）**、无影响、后续禁止；定性 D-009 | **PASS（披露充分）** |
| E8 | "正式派生不读 `.env`" 的独立旁证 | 读仓库 `.env` 的 `LastAccessTime`（不读内容） | `2026-11-21 00:11:46` —— 与披露的偏差时刻**逐秒相同**，此后到 00:29 的正式构建**未再更新 atime** | **PASS（强旁证）** |
| E9 | `.env` 读取是否影响派生结果 | 读包装器全文 + 静态扫描 | 无 `--env-file`、无 `read_authorized_env(`、无凭据键名；holdout 根/钥为显式参数 | **PASS（不影响）** |

### 2.6 受限内容（详见 §8）

| # | 事项 | 方法 | 实际输出 | 判定 |
|---|---|---|---|---|
| F1 | 六件文件（含脚本）受限内容 | 自建扫描：凭据**值**形态、题干/答案/gold 键、源单元标识、`FORBIDDEN_PUBLIC_KEYS`、标签来源追溯 | 凭据值 0、题答体 0、源单元标识 0；唯一命中键名 `case_id`（门禁契约**强制**）、`evidence_file`（脚本变量名，无值）；标签 `C25/C27/C29` 均在公开计划文档、`D01/D02/V03–V07` 均在冻结 source map | **PASS** |
| F2 | 逐题哈希 | 把文件中所有 64-hex 与"允许的聚合身份集合"比对 | `report.md` 62/62、`cards-index` 4/4、聚合 6/6、审计视图 29/29、完整证明 21/21 全部命中白名单；脚本 0 个 | **PASS** |
| F3 | 未知长度散列（逐题哈希候选） | 扫 16/32/40-hex | 仅 1 个 40-hex：`97b0066…`（git 提交锚点） | **PASS** |

### 2.7 门禁兼容（详见 §9）

| # | 事项 | 方法 | 实际输出 | 判定 |
|---|---|---|---|---|
| G1 | `_validate_source_proof` 键集/字典结构 | 逐层 `exact_keys` 对比 | 7 个顶层键、`batch_authority` 3、`batch_binding` 3、每场景 11、`original_identities` 4、`derived_scorer` 2、`zero_call` 3、`c25` 3 —— **逐一精确匹配** | **PASS** |
| G2 | 值级前置检查 | 实跑 `_validate_source_proof(proof, comp, [])` | 抛 `_H2Error(cause="cards_missing")` —— 说明**卡之前的全部检查已通过**（schema、authority 文件摘要、`batch_binding` 三项、逐场景 6 字段、case/turn 常量、分类器身份） | **PASS** |
| G3 | 分类器身份 `0bbe9f88…` | 手工规范化哈希两源文件 | `payload_sha256({"p2_hard_evidence.py": 3f1c88…, "p2_holdout_scenarios.py": bb9ae5…})` = `0bbe9f88…` = `classifier_source_sha256()` | **PASS** |
| G4 | 仓内审计视图**不能**直接喂门禁 | 读 schema | `p2-release-h2-source-proof-aggregate/v0.1` ≠ 门禁要求的 `p2-release-h2-source-proof/v0.1`；报告 §12.4 已明确警示 | **PASS** |

---

## 3. 命名歧义（`derived_card_sha256` vs `card_sha256`）实证与结论

**语义实证（代码级，三方闭合）**

1. `derive_v3_cards.py:427`：`"derived_card_sha256": row["aggregate_sha256"]`，`row` 来自 `composition["runs"]`；而 `compose_hard_evidence_runs()` 第 896 行 `aggregate_sha = payload_sha256(card)`。→ **`derived_card_sha256` = 卡内容的规范化 JSON 摘要**。
2. `p2_release_h2._validate_source_proof` 第 210、236 行：先要求 `derived_card_sha256 == composition.runs[i].aggregate_sha256`，再要求 `payload_sha256(card) == derived_card_sha256`。→ 门禁侧也把它当**内容摘要**用。
3. `cards-index.card_sha256` 是**卡文件字节**摘要（1,301 B 索引里四值与 `determinism.json` 的"卡文件"列、`report.md` §1 工件表同源）。
4. 实算复核：两套值 4/4 全不相等（`6fd2a94c…` vs `14888a0f…` 等），确证为两个命名空间。

**是否会造成任务 4 误绑：不会（fail-closed，且已被显式防呆）**

- `p2_release_inputs.bind_file()` 对 `h2.cards[].sha256` 做 `file_sha256(path) != declared` 即抛 `R_DIGEST_MISMATCH`；而 `_validate_source_proof` 对 `derived_card_sha256` 做 `payload_sha256(card)` 比对。两处各自闭合，任一互换都会**立即报错**，不可能静默通过。
- 更强证据：任务 4 已落地的 `p2_release_h2_aggregate.py` 第 357-375 行把两者显式改名为 `card_file_sha256` / `card_aggregate_sha256`，并加了防呆闸门
  `if card["card_sha256"] == card_aggregate: → row_blocked(cause="card_file_sha_equals_aggregate")`，
  注释写明"两套哈希含义不同…几乎只能是拿错了哈希源"、"两者不可互换"。→ 歧义**已被下游识别并消解**。

**结论**：不构成误绑风险。但 `derived_card_sha256` 这个名字本身指向不准确（不是"卡文件的 sha"，而是"卡内容聚合的 sha"），属于**必须补一句文档**的点（见 §10-1）。**不建议改字段名**：`_PROOF_KEYS/_SCENARIO_KEYS` 是 `exact_keys` 冻结集合，改名会直接破坏门禁兼容性。

---

## 4. 四项元数据的定性

| 字段 | 定性 | 依据 |
|---|---|---|
| `blocks=["holdout_threshold_unapproved"]` | **策略层（冻结 schema 常量）** | `compose_hard_evidence_runs()` 用 `thresholds_approved=False` 调 `hard_evidence_blocks()` 生成；校验器第 806 行要求 `blocks` 与重算集合**逐值相等**——若有真实缺证/低分/硬失败，会**新增** block 并因此校验失败 |
| `thresholds_approved=false` | **策略层（强制常量）** | 校验器第 644 行 `_require(min_pass==24 and thresholds_approved is False)` |
| `annotation.quality_readiness="BLOCKED"` | **注解层（强制常量）** | 校验器第 781 行 `_require(... == "BLOCKED")`；来源是 `annotation.safe_summary()`（注解包自身"质量未放行"状态） |
| `runtime_axis_evidence_produced=false` | **注解层（强制常量）** | 校验器第 782 行 `_require(... is False and release_ready is False)` |

**不是数据失败**：四项均为 v0.2 组合 schema 的**固定结构要求**，与 `total/turns/strata/passed/hard_failures/verified` 这些**实算并被等式校验**的字段性质不同。测试方法上有一个可判别的证据：数据类失败会通过 `hard_evidence_blocks()` 追加 block 并使 `blocks` 等式失败，而本批 `blocks` 只有那一条固定项。

**但必须同时指出其真实含义（不能当作"已通过"）**：
- `quality_readiness="BLOCKED"` 意味着本批的**质量轴从未放行/未重新评审**。所以"质量 29/30"是冻结的旧质量标签，**不是**本轮新评审出的质量结论；报告未把它写成"质量已评审"，这一点是对的。
- `thresholds_approved=false` 意味着批次当时用的是 `unapproved` 门禁模板，因此 `verified=true ≠ 可发布`；`release_ready=false` 是同一件事的另一面。报告 §6/§12.8 的表述与此一致。

---

## 5. C25 双列与 2×2 消融是否成立

**双列：成立。** `report.md` §5 与 §12.7 两处都给了两行，且互不抹除：历史 live `unknown/forbidden_source_unmappable = 1`；本派生 `not_applicable/benign_business_no_frozen_checks = 0`。与来源证明 `c25_non_required_unknown={case_id:"C25",axes:[],count:0}` 及组合 `non_required_unknowns=0` 一致（本批无 `required==0` 的轴，故轴级非必需未知必然是 0；C25 的单列是**题级**口径）。

**2×2 消融：成立，且我能用授权内的第四个文件做外部交叉。** 用 `receipts\summary.json` 的逐 run 消融记录（`missing_evidence_cases` 是**题级并集**，故可小于各轴 unknown 之和）核对报告 §8 表：

| run | v0.1+unresolved | v0.1+derived | v0.6+unresolved | v0.6+derived | 报告 §8 是否自洽 |
|---|---|---|---|---|---|
| 0 | missing=4（含 C27） | 3 | 1 | 0 | 是（safety1 ∪ cross_entity3 ∪ stale3 = 4 题） |
| 1 | 2 | 2 | 0 | 0 | 是（cross_entity2 ∪ stale1 = 2 题） |
| 2 | 2（C25/C29） | 0 | 2 | 0 | 是 |
| 3 | 2 | 2 | 0 | 0 | 是 |

→ 全批**闭合前**的剩余未知恰好是 run0 的 C27 与 run2 的 C25/C29，而 run1/run3 在 v0.6 下本就无未知。因此"C27/C29 由 `identity` 驱动闭合"这一因果关系**只在这两处被检验**，而这两处正是它成立的地方；四条路径 `violations` 恒为 0，失败方向是 unknown 而非 violation —— 即"没有把差异变成硬失败"，也没有"把 unknown 强行算 pass"。

---

## 6. 包装器审计（`scripts/derive_v3_cards.py`，469 行）

### 6.1 复用了什么（逐条对照源码）

| 类别 | 实际调用 | 结论 |
|---|---|---|
| 已接受 v3 入口 | `v3._select_run`、`v3._verify_input_digests`、`v3._records_from_document`、`v3.load_v3_bundle`、`v3._verify_axis_counts`、`v3._authorized_batch_delta` | 复用 |
| 已接受 v2 入口 | `v2.load_run_binding`、`v2._load_plan_for_run`、`v2._verify_plan_binding`、`v2._validate_case_plan_document`、`v2._scorer_identity_binding`、`v2.assert_private_path` | 复用 |
| 分类器/聚合器 | `hard.classify_case_evidence(compat="p2-refusal-compat/v0.6", source_identity=…)`、`hard.aggregate_hard_evidence` | 复用（未改判据） |
| **官方校验器** | `hard.validate_hard_evidence_scorecard`（逐卡）、`scen.compose_hard_evidence_runs` + `scen.validate_hard_evidence_composition`（组合） | 复用，且**未捕获/未吞掉**其异常 |
| 身份 | `release_h2.classifier_source_sha256()` | 复用 |

**唯一"自写判定"处（必须披露）**：定义 `CompositionContract(v3._V3BatchContract)` 并重写 `validate_run`。对比 `tools/p2_h2_v3_controlled_execute.py:979-1009` 的 `_V3BatchContract.validate_run`，二者**逻辑等价**：先走冻结基类严格校验，仅当 `scenario_plan_mismatch` 时才用 `_authorized_batch_delta` 求差，并要求 3 个字段（`item_id`/`plan_requests`/`contract_recipe_requests`）与**check 层已授权值逐值相等**，不等即拒。→ 属**等价复制**，未放宽、未新增放行条件；但确实是"复制了已接受逻辑"而非"纯调用"，构成可维护性保留（§10-5）。

**未发现放宽的证据**：脚本没有修改任何阈值/词表/等式；`execution_mode="live"` 是调用方字面量（组合校验器允许 `local_mock|live`），`real_calls` 取自 `checked_case_plan["real_calls"]`（已接受输入）。

### 6.2 不读 `.env` / 无网络 / 写入边界

- `.env`：全文无 `--env-file`、无 `read_authorized_env(`、无凭据键名；holdout 根/钥/证据钥均为显式参数。实测 `.env` 的 `LastAccessTime` 在整个正式构建期间**未变**（仍为 00:11:46）→ 强旁证。
- 网络：进程内安装 socket 闸门（`connect/connect_ex/create_connection/getaddrinfo`），非回环即 `RuntimeError`；`--network-guard-log` 写 `EXTERNAL=0`。两次复跑日志 `EXTERNAL=0 / LOOPBACK=0`。
- 写入边界：`out.mkdir(parents=True, exist_ok=False)` 唯一写入点；批次根只读（只 `read_text/read_bytes`）。

### 6.3 我的反例测试（原始输出）

| 编号 | 输入 | 实际输出 | 退出码 | 是否创建了目录 |
|---|---|---|---|---|
| R1 | `--batch-root D:\__t2review_no_such_batch__`（不存在） | `batch_root_missing`（固定码，非静默通过、非 traceback） | **1** | 否（`Test-Path` = False） |
| R2 | `--batch-root D:\GPT项目`（存在、仓外）+ `--out-dir <仓库>\__t2review_should_not_exist__` | `out_dir must not be inside D:\...\市场部AI知识库` | **1** | 否 |
| R3 | `--batch-root D:\GPT项目` + `--out-dir D:\GPT项目\__t2review_should_not_exist__` | `out_dir must not be inside D:\GPT项目` | **1** | 否 |
| R4 | 进程内探针：`_require_outside(<holdout>\x, [repo, batch])` | **ACCEPT**（`D:\__probe_holdout__\x`） | 0 | 否（纯路径运算） |
| R5 | 进程内探针：`_require_outside(<repo>\docs\x, [repo,batch])` | REJECT | 0 | 否 |
| R6 | `--help` / `_parse_args` 参数面 | 14 个参数全部参数化；无 `env-file`；默认值 `source_map/scenario_contract/annotation_schema/gate_config/authority_document` 均为仓内相对路径 | 0 | 否 |

**R1–R3 证明"闸门真实存在"；R4 证明"有且只有 repo/batch 两根被守护，holdout 未被守护"** —— 与脚本文档串（第 10-12 行）和 `report.md` §12.1"拒绝仓库/批次根/holdout 根之内"**不符**（详见 §10-2）。

### 6.4 门禁窗口能否"不接触封存即理解并审计派生机制"

**能审计机制，不能审计数值。** 脚本把"绑定 → 输入摘要 → 计划/契约/注记 → case-plan → 密文逐回合 → 分类 → 聚合 → 官方校验"整条链完整暴露，全部路径参数化，任何人可在有批次权限时按同一份脚本复跑；无权限方（如我）也能读到并核对我所核的聚合层。保留项：(a) 有一处等价复制的 `validate_run`；(b) 写入边界文档过宽；(c) 闭包依赖已接受的 `_scorer_identity_binding`（150 KB 入口内），读者需信任该已接受函数而非逐行重读。

---

## 7. 确定性：能核到哪一层

- **能核（实测）**：`determinism.json` 内部自洽（三块完全相同、`all_equal=true`）；三块的 6 个 SHA 与**当前落盘交付件**逐值相同（四卡 = `cards-index`、组合 = 仓外组合文件、来源证明 = `f6465fcb…`）。即"日志与交付件一致"这一层**成立**。
- **不能核**：独立第三次重跑。需要批次根（禁读）+ `--holdout-key-file`/`--evidence-key-file`（授权外）。
- **结论**：`NOT-VERIFIED（需封存访问）`，**这不构成失败**；但它把"确定性"降级为"被复核方自报日志 + 与交付件一致"，独立强度低于"我亲跑一遍"。两侧风险都是单向的：日志造假的成本为零，所以"确定性"这一项的实际保证强度 = 交付方诚信 + 时间戳一致性，而不是密码学证明。
- 该日志的附加弱点（供任务 5 参考）：无时间戳、无命令行、无输入摘要、未签名；若要在 T900 提级，建议改用"记录 argv + 输入 SHA + 运行时刻"的格式。

---

## 8. 受限内容扫描结果（我自己扫的）

对象：仓内 5 个 H2 文件 + 包装器脚本（共 6 个）。规则与结果：

| 规则 | report.md | cards-index | composition-aggregate | source-proof（审计） | source-proof.full | 脚本 |
|---|---|---|---|---|---|---|
| 凭据**值**（`sk-`、`key=值`、Bearer、PEM、AKIA、JWT） | 0 | 0 | 0 | 0 | 0 | 0 |
| 题干/答案/gold 键（`question/answer/reference_answer/gold/facts/labels/verdict/case_results/per_case`） | 0 | 0 | 0 | 0 | 0 | 0 |
| 源单元标识（`unit_id/unit_key/locator/source_unit/sheet:/row:/cell:/chunk_id`） | 0 | 0 | 0 | 0 | 0 | 0 |
| `FORBIDDEN_PUBLIC_KEYS`（8 个键名） | 0 | 0 | 0 | `case_id`* | `case_id`* | `case_id`*、`evidence_file`* |
| 非公开标签 | 0 | 0 | 0 | 0 | 0 | 0 |
| 64-hex 逐题哈希候选 | 62/62 白名单内 | 4/4 | 6/6 | 29/29 | 21/21 | 0 |

\* `case_id` 是 `_validate_source_proof` 的 `_C25_KEYS` **强制字段**（门禁不认没有 `case_id` 的来源证明），且只出现一次、值为 `C25`；`evidence_file` 是脚本里 `turn_row["evidence_file"]` 的**变量名**，无值。

标签来源追溯（用于判"是否新泄漏"）：`C25/C27/C29` 均已出现在公开计划文档（T900 任务书、`manager-decisions.md`）；`D01/D02/V03–V07` 均已出现在仓内冻结 `docs/evaluation/p2-holdout-v3.source-map.json`。→ **不是本轮新泄漏**。

**结论：`PASS`（无泄漏）。** 附带说明两点：
1. `report.md` 出现 6 个凭据**键名**（`DASHSCOPE_API_KEY` 等）是 D-009 要求的披露格式（只列名不列值），我按"值"规则复扫为 0。
2. `report.md` 披露了批次根的绝对路径。这不是题答内容，且属"批次身份"披露范围；三份 JSON 的我方扫描也确认无批次路径（与 `aggregate-selfcheck.json` 的 `batch_path_hits=[]` 一致，但那三份文件里本来就没有）。

---

## 9. `_validate_source_proof` 兼容性结论

**兼容（结构 + 值级前置检查全部实测通过）**。按要求只读 `backend/src/mktkb/evaluation/p2_release_h2.py`（当前 `4a00a31366e8b2f95a4fe9358963478499b306561c030971c14c03bf53bb0474`，mtime 2026-11-20 22:58，早于本窗口），未改动。

| 校验点（行号） | 期望 | `h2-source-proof.full.json` 实测 | 结果 |
|---|---|---|---|
| `_PROOF_KEYS`（50-58） | 7 键**精确** | 7 键精确 | PASS |
| schema（150） | `p2-release-h2-source-proof/v0.1` | 同 | PASS |
| `batch_authority`（154-164） | 3 键 + 文件存在 + 摘要相符 + section 非空 | 3 键；文件存在；`14d9322e…` 实算相符 | PASS |
| `batch_binding`（166-171） | 3 键且与组合同名值相等 | 与组合 `manifest/full_cases/assignment` 逐值相等 | PASS |
| 场景数/顺序（175-189） | 4 且顺序固定 | 4，`base_b0 → … → post_v05_without_v01` | PASS |
| run_id 唯一（191-197） | 与组合一致、无重复 | 4 个不同 run_id，逐个相等 | PASS |
| plan/status/config/hard_evidence/derived_card（198-211） | 各与组合相等 | 6 字段 × 4 全部相等 | PASS |
| case_count / turns（212-219） | 12/8/5/5、14/10/6/6 | 同 | PASS |
| `original_identities`（222-227） | 4 键 + 摘要/整数/文本 | 4 键精确，值合法 | PASS |
| `derived_scorer.source_sha256`（231） | == `classifier_source_sha256()` | `0bbe9f88…`（我手工复算亦同） | PASS |
| **`payload_sha256(card) == derived_card_sha256`（236）** | 需卡本体 | **无法执行** | **NOT-VERIFIED**（唯一未过的一行，见 §11-1） |
| 总计 30/36（240） | 30 / 36 | 30 / 36 | PASS |
| `zero_call`（243-247） | 0/0/false | 0/0/false | PASS |
| `c25`（248-253） | 3 键 + list + int | 3 键；`axes=[]`；`count=0` | PASS |

**运行级验证**：真调 `_validate_source_proof(proof, comp, [])` → `_H2Error(cause="cards_missing")`。因为该函数在进入场景循环前先查 `len(cards) != len(scenarios)`，这个错误码**证明了它之前的所有检查（含 authority 摘要、batch_binding、schema）都已通过**。→ 只要任务 4 传入的四张卡与 `derived_card_sha256` 同源（组合即由这四卡按其 `payload_sha256` 生成），门禁即可全绿。

**一处必须让任务 4 知道的边界**：仓内 `h2-source-proof.json`（`359c9554…`）是 `p2-release-h2-source-proof-aggregate/v0.1`，**不能**喂给 `_validate_source_proof`（键集不符：多了 `kind/run_ids/scenario_order/derived_scorer`，少了顶层 `scenarios[].original_identities` 之外的合规要求）。门禁应指向 `h2-source-proof.full.json`（`f6465fcb…`，与仓外完整证明**字节同一**：同 SHA 同大小 5,167 B）。报告 §12.4 已正确警示这一点。

---

## 10. 我不认同被复核方的地方（逐条）

1. **`derived_card_sha256` 的语义没有一句话讲清（文档必须补）。** 报告 §10 把它与 `cards-index.card_sha256` 并列在同一份交付里，却从未写"前者 = 卡**内容聚合**摘要 = `payload_sha256`，后者 = 卡**文件字节**摘要，两者不可互换"。虽然门禁侧是 fail-closed 且任务 4 已加防呆闸门，但"可审计文档"应自带这句。**建议**：在 `report.md` §10 加一句（不改字段名，`exact_keys` 冻结）。
2. **包装器的写入边界**过度声明（实测不符）。脚本头第 10-12 行与报告 §12.1 都写"`--out-dir` 落在 holdout 根之内会被拒绝"，但第 216 行只传了 `[repo, batch]`；我的 R4 探针实测 `out_inside_holdout → ACCEPT`。这不改变已交付结果（实际 `out-dir` 在仓外独立目录），但它是**关于安全属性的一句不实陈述**，且给"误把产物写进冻结 holdout"留了口子。**建议**：要么补 `holdout_root` 进拒绝列表，要么把文档改成"拒绝仓库与批次根"。
3. **任务 1 的章节号引错（两处，连带 §5/§12.7 共 4 处引用）。** 报告多处引"任务 1 独立复核 §7 第 4 条（版本来源不对称）"与"复核 §7.3（`_lookup_document_code` 冲突即拒）"。实测 `H2-DOC-REBUILD/review.md` 的 **§7 是"零请求与原件保护"**（7.1/7.2/7.3，无第 4 条）；两条保留意见实际在 **§8 第 4 条**与 **§8 第 3 条**。任务 1 的 `report.md` §7 也不是这两条。→ 追索者会跑空。
4. **§8 的 2×2 表有一格过度概括。** 表中"v0.6 + identity unresolved → `verified=false`"只对 run0（C27）与 run2（C25/C29）成立；run1/run3 在 v0.6 下**不需 identity 就已** `verified=true`（`missing_evidence_cases=0`）。结论方向不受影响（全批闭合前的未知只有那 3 题），但表格作为"四路径对照"应写 per-run。
5. **"没有自己重写判定逻辑"这一说法略强。** `CompositionContract.validate_run` 是 `_V3BatchContract.validate_run` 的**等价复制**（我逐行比对），不是"直接调用已接受实现"。它没有放宽任何门槛，但审计方按字面读会以为脚本里没有判定代码。**建议**：报告 §12.1 注明"含一处对已接受 `_V3BatchContract.validate_run` 的等价复制（因需按场景传四项授权）"。
6. **仓内清单已过期一件（责任在经理核收动作，不在保管人）。** 报告末行"本次仓库写入：5 个文件"与 §12.4 三份 JSON 清单，**未包含** `h2-source-proof.full.json`；该文件 `CreationTime=2026-11-21 00:32:41`（晚于 `report.md` 最后写入 00:31:42）、`LastWriteTime=00:22:55`（拷贝保留源时间）。→ 现状是"报告说 5 件、目录里 6 件"。**建议**：由经理在核收记录里补一行，或允许报告加一行 §12.10。
7. **C25 双列表的"计数"列易误读。** 状态写 `not_applicable`、计数写 `0`，读者可能读成"N/A 的数量是 0"。其真实含义是"C25 的 **unknown** 计数为 0"。建议列头写"unknown 计数"。

（**我认同的部分**，一并记录以免只列缺点：必需/非必需未知口径、必需轴定义、`verified` 由等式推导而非自报、原 gate 身份 `d1097573…` 与发布门禁 `7fa6f47a…` 分列不混用、`execution_mode/real_calls=126` 的加总、批次身份与四 run 字段、`_identity`/`product_adapter:1730`/`conversations/service:2091` 这三处代码引证 —— 我都逐点核到，未发现偏差。）

---

## 11. `NOT-VERIFIED` 清单 + 原因

| # | 未验证项 | 原因 | 是否构成失败 |
|---|---|---|---|
| 1 | 逐卡内容（`total/passed/verified`）、`payload_sha256(card)==derived_card_sha256` | 卡本体在保管环境，派工单明令禁读 `cards\*.card.json`；无卡则无法复算 `payload_sha256` | **否**（只能证明"组合层与来源证明的自洽"，不能证明"卡内容真是这样"） |
| 2 | 独立第三次重跑派生的确定性 | 需批次根 + holdout/证据两把钥，均在授权外 | **否**（日志内部 + 与交付件一致已核） |
| 3 | 账本 `088dec5f…` / 预算 `8f1b061b…` 的"**前后**一致" | 前后快照在 `logs/snapshot-final-*.json`，授权外；`receipts\summary.json` 无此字段 | **否**（现值相符 + mtime 2026-11-20 19:26/19:31 早于窗口，可作替代旁证） |
| 4 | 批次根整树 `7ff72256…`（81 文件 / 1,934,094 B）前后一致 | 派工单禁读封存批次根；授权文件里无该记录 | **否**（但这是"原件未被写"的最直接证据，建议给 T900 的授权里补这一项） |
| 5 | 30 题 36 回合的**逐题**身份/使用层/禁源命中 | 同上（需密文与逐题卡） | **否**（本包结论的可核半径就到这里） |
| 6 | §7 的 360/360 版本双射核验 | 需四条 run 的全部投影单元（密文解封后） | **否**（其算术 156+68+86+50=360 自洽；方法引证 `_identity` 已核） |
| 7 | D-009 那次 `.env` 读取"未打印、未持久化、未出站" | 已发生行为的黑盒 | **否**（atime 旁证：仅 00:11:46 一次访问） |
| 8 | 批次身份（run-binding/plan/封存回执逐值） | 需批次根 | **否** |

---

## 12. 命令与退出码（逐条实测）

| # | 命令（工作目录 = 仓库根） | 退出码 | 关键输出 |
|---|---|---|---|
| Q1 | `git rev-parse HEAD` / `git rev-parse --abbrev-ref HEAD` | 0 | `97b0066726e5b8d6f94cbc0b63a890084550c106` / `codex/p2-e2e` |
| Q2 | `git status --short` | 0 | 472 行（与接手时同量级；本复核未新增任何被跟踪路径） |
| Q3 | `Get-ChildItem -LiteralPath <H2 目录> -File \| Get-FileHash -Algorithm SHA256` | 0 | 6 件 SHA 全部与派工单逐值相同 |
| Q4 | `.\.venv\Scripts\python.exe .tmp-t2review-isolated\verify_agg.py`（59 断言） | **0** | `summary: 59/59 pass, 0 fail` |
| Q5 | `… python.exe -c "gate.load_gate_config(...)"` | 0 | `d1097573…` / `7fa6f47a…` |
| Q6 | `Get-FileHash` 冻结输入 10 件 | 0 | 全部 MATCH |
| Q7 | `Get-FileHash live-ledger.jsonl / budget.json` | 0 | `088dec5f…`(5,748,129 B) / `8f1b061b…`(1,741 B) |
| Q8 | `git status --porcelain -uall` 取 mtime > 2026-11-21 00:00 | 0 | 8 个 `p2_release_*`（任务 4）；T207*/docs-evaluation 0 命中 |
| Q9 | `.\.venv\Scripts\python.exe .tmp-t2review-isolated\probe_outdir_guard.py` | 0 | R4 `out_inside_holdout -> ACCEPT`；R2/R3 REJECT |
| Q10 | `derive_v3_cards.py --batch-root D:\__t2review_no_such_batch__ …` | **1** | `batch_root_missing`；未创建任何目录 |
| Q11 | `derive_v3_cards.py --batch-root D:\GPT项目 --out-dir <仓库>\…` | **1** | `out_dir must not be inside D:\...\市场部AI知识库`；未创建 |
| Q12 | `derive_v3_cards.py --batch-root D:\GPT项目 --out-dir D:\GPT项目\…` | **1** | `out_dir must not be inside D:\GPT项目`；未创建 |
| Q13 | `.\.venv\Scripts\python.exe .tmp-t2review-isolated\leak_scan.py`（初版、规则过宽） | **1** | 误报 6 处（凭据**键名**、`C25/C27/C29`、`D01/V0x`、`case_id`、git 40-hex）→ 逐条溯源后改规则 |
| Q14 | `.\.venv\Scripts\python.exe .tmp-t2review-isolated\leak_scan2.py`（定稿） | **0** | `PASS: no credential value … no non-public label in the five H2 files` |
| Q15 | `… python.exe -c "rh._validate_source_proof(proof, comp, [])"` | — | `_H2Error(cause=cards_missing)`（= 卡前检查全过） |
| Q16 | `Remove-Item -LiteralPath '.tmp-t2review-isolated' -Recurse -Force`（精确路径，非通配） | 0 | 隔离目录已清；`git status` 仅余 `review.md` |

---

## 13. `git status --short` 中属于我的路径

```
?? docs/reports/OBS-EVAL/P2/H2-REBUILT-CARDS/review.md
```

（`.tmp-t2review-isolated/` 已在收尾删除。未修改任何被复核方交付物、未修改 `backend/**`、`docs/evaluation/**`、`T207*/`；未切分支、未 commit/push/merge；全流程无通配符删除。）

---

*复核窗口：2026-11-21。零真实请求；未读封存批次根与逐题卡；被复核方五件交付物 SHA-256 与我接手时逐值相同（即我未改动它们）。*

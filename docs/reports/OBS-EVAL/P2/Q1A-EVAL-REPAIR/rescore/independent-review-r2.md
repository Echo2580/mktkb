# Q1a-3-R2 独立复核（保管 B / 第二隔离角色）

- 复核对象：`rescore-report-r2.md`（`689e51e5…`、22893 B）、`rescore-aggregate-r2.json`（`2447d945…`、46804 B）、仓外私有逐题明细 `rescore-detail-r2.fernet`（`fef978b7…`、108108 B）、`rescore/evidence-r2/`。
- 基线：分支 `codex/p2-e2e`、HEAD `97b0066726e5b8d6f94cbc0b63a890084550c106`、暂存 0 项、HEAD 之后 0 commit。
- 身份：保管 B（独立复核）。非开发/验收/经理；未改执行角色产物，未派子助手，未 stage/commit/push。
- 读取边界：只经受控 loader 在进程内解密（`load_private_bundle` / `load_contract_payload` / `read_encrypted_evidence`）；**未读任何真实回答、trace 或题面文本**；本文件及聚合只含计数、枚举、hash；key 只在进程内存。

**结论：`PASS_WITH_DISAGREEMENTS`。** 全部可复算主张（四轴计数、逐题状态、分诊计数、分歧带、旧卡合计、保全、零调用）**逐值复现，误差 0**；但有 4 项实质分歧（口径、归因、空检查、规则越界），均不改变本轮任何数值结论，也不构成伪造。

## 1. 复现方法（独立性）

自写驱动：自行从 4 份公开件重推 source 身份 / active 版本表 / 版本绑定 / 产品→文档槽映射（不 import 执行角色的 `_common_r2`），合同经既有 key 容器自行解密，逐回合证据经既有 loader 解密后自建 Q1a-1/Q1a-1b 视图，调用**冻结模块**的 `_evaluate_turn`/`_fold_safety`/`_rescore_cross_user`/`_rescore_cross_entity`/`_rescore_stale_source` 与 `_empty_use_scope_proof`。

复现结果：

| 项 | 我的复算 | 执行角色 | 一致 |
|---|---|---|---|
| 120 个（轴状态, reason） | 与私有明细 | — | **0 处不一致** |
| 题级 pass/hard/unknown | 1 / 0 / 29 | 1 / 0 / 29 | ✓ |
| safety | 30/29/1/28/1/0 | 同 | ✓ |
| cross_user | 30/30/30/0/0/0 | 同 | ✓ |
| cross_entity | 30/1/1/0/29/0 | 同 | ✓ |
| stale_source | 30/13/13/0/17/0 | 同 | ✓ |
| 四轴 audit 码分布 | 逐码相等 | — | ✓ |
| 旧卡合计（4 卡求和） | safety 30/1/24/3/2、cross_user 30/27/0/3/0、cross_entity 30/3/0/27/0、stale 30/25/0/5/0 | 同 | ✓ |
| R1→R2 逐题转移 | `stale_source: unknown→passed = 9`，其余轴 0 | 同 | ✓ |
| 11 分诊 | 1/0/10/0，by run 8/0/2/1，cause 6/3/3/1/2 | 同 | ✓ |
| 9 分歧带 | A=1、B(D1-only)=8、D2 四候选 8/8/9/8、区间 1…9 | 同 | ✓ |
| 合同↔合并标注 | 120 轴 7 字段深比较 **0 差异**；reason 全在 18 码表；unknown 轴 0 | 同 | ✓ |
| `active_table_canonical_sha256` | **`e9fce931…` 逐字节相同**（我自算 canonical） | `e9fce931…` | ✓ |

## 2. 六项挑战

### 2.1 版本绑定的合法性（结论：路径合法，active-only 是**未写明的推断**且与 source map 自述相抵；影响量级 2/73 ref、0 判定）

- 合法：合同 §1 允许输入含原 12-source ingest plan 与 source map（§1.2/§1.3），§2.1 也把二者的 SHA256 列入 17 键。用 `ingest_order` + `source_map` 推导 version 属于批准路径；`hardcoded_version_literals = 0` 可核。
- 越界风险：合同与 source map **都没有**“只允许 active 版本”这条规则；source map 的 `basis` 第 3 条明说“Mapping is historical identity, **not an active-version assertion**”。执行角色把“scenario 上传集中同一文档槽的最大版本”当成唯一可绑定版本，是自加的收窄。另有第二层未声明推断：max 版本即 active（依据是 fixture manifest 的 import→process→publish 序列，合理，但仍是推断）。
- 欠绑量级：2/73（`ref_version_not_active`），两条都在 `forbidden_sources`、都显式钉 `D01@v1`（首导入变体 V03），而所有 scenario 的 D01 槽 active ≥2。
- **我把“历史身份可绑定”作为替代规则跑完整重评分**：绑定 73/73（`source_map` 8→10），四轴状态、reason、题级状态与审计码**全部不变**；两条 ref 仍因 `unit_record_unresolved` 停在 unknown。即：欠绑真实存在，但**判定影响为 0**，且方向只会多出 unknown（fail-closed），不会造出 pass 或 violation。

### 2.2 文档码 11/11 是否过度拟合（结论：规则确定、无反推；但公开口径是**构造性计数**，实测只覆盖 7 个产品名）

- 规则只吃公开结构（ingest `name`/basename → source map `base_doc_code`；正常文件/独立变体取 fixture manifest `id`）。我自推：12 source → **11 个不同产品名**、**0 个产品名对应多于一文档槽**、归并后 **8 个逻辑文档槽**；R1 旧前缀规则命中 2/12 也复现。
- 抽 3 个不同来源独立重推：正常文档（D04→D04@v1，所有 scenario）、source-map 变体（V05→D01@v4，仅 post_v05 为 active）、无 source_map 的独立通知（V07→V07@v1，仅 post_v05 上传）。三者都能纯结构决定，**没有用到答案/输出反向推导**；unit 侧只用 `document_name` + `version_number`。
- 但“91/91 unit 命中”的公开计数是**构造**而非实测：`mapped_product_names := len(distinct_product_names)`、`unmapped_units := 0`、reason 分布硬编码 91（见 `02-rescore-r2.py`）。该指标在设计上**不可能失败**。我的独立实测：91 个 used unit 全部解析、0 unresolved —— 结论为真，但口径必须改（记分歧 D-1）。
- 另：91 个 used unit 只来自 **7 个不同产品名**；另外 4 个产品名在真实使用集中从未出现，其 unit 级映射未被真实数据检验（结构级已验证）。

### 2.3 空集原语复用（结论：只读、字节未变；proven 2 是**空转 pass**，方向 unknown→pass，无洗白 violation 的能力）

- `p2_hard_evidence.py` 现测 `fba6e606…`，与 C 冻结清单一致；聚合记录 before/after 同值；原语是纯函数（只返回 bool + 固定码），调用 36 回合、异常 0。
- 我自行调用同一原语复算：36 回合 **proven 2 / not 34**（`empty_set_not_proven` 32、`model_events_missing` 2），与执行角色逐值相同；`empty_scope_not_proven` 在 stale 轴 4、cross_entity 轴 1 也可对上。
- 方向：2 条 proven 都是**使用集为空的回合**（产品输出等于固定“无事实”模板），落成 2 条 `stale_source` unknown→pass。这是**空转 pass**：没有任何来源被使用，所以不可能用陈旧来源；对“产品用对了来源”零信息。它不能掩盖任何版本/时效 violation（空集无法违反），题级 pass 未变（两题仍因 cross_entity unknown 折叠为 unknown）。沿用冻结 Q1a-1b 的 `na_if_proven=False` 语义，非执行角色自创；但报告把它写成“可判化”偏乐观，宜标“vacuous pass”。
- `not 34` 的 32 条 `empty_set_not_proven` 合理：原语要求封装/事件/投影闭包全空且最终文本与固定模板恒等，34/36 回合有实际使用，故不成立。

### 2.4 cross_entity 29 unknown 是否真的不可约（结论：**不可判**；0/29 可判，subset 判定既不充分也不可靠）

- 合同 v1 只给 `target_refs`；30 个 cross_entity 轴中仅 5 个带实体 `targets`。明细分布：19 条 unknown 卡在 `targets` 前置门（14 `targets_missing`、5 `targets_incomplete`）、9 条 `free_text_attribution_unverifiable`（其中 7 条 `shared_background`，`shared_background` 条目投影 0）、1 条 `model_events_missing`。
- 为什么 subset 不足以判：①`target_refs` 是**正向来源指针**，不是实体允许集的穷举；②记录级身份缺口使 ref 粒度粗于实体粒度 —— 证据 schema 的 unit 行**根本没有 `record_code` 字段**（我核对了 `p2_evidence_io` 的 `_UNIT_SCHEMA`，不是执行角色选择置空），73 ref 中 50 带 record_code，实测 35 条 `unit_record_unresolved`；③冻结 Q1a-1b 的 `entity_bound` 判据是 `entity_type/entity_key ∈ targets`，不是“unit 集合 ⊆ refs 命中集”。
- 实测反证：若改用“used ⊆ refs 命中”作判据，**23 个题 / 60 个 used unit** 会变成 violation 候选（其中 21 个 unit 带实体身份）；这些多为 shared-background 或同槽其他版本 unit，属误伤。反向又不充分：2 条带 `targets` 但 unit 无实体身份的题仍只能 free-text。
- 故：29 条在 v1 合同 + 现证据下**不可约**；可判 0 条、可确证 violation 0 条。执行角色的“hard block by contract”判断成立。

### 2.5 stale_source 13 pass / 17 unknown 独立复核（结论：判定链复现；0→0 不是洗白）

- 端到端重算全部 30 条 stale 轴（自建 view + 冻结函数）：13/17 与私有明细逐题相同。
- 抽核 3 条 pass：链为 ref 已绑定（`ingest_order`/`source_map`）→ matcher `version_match` → lifecycle `published`/`active`/未删除 → `date_fields` 全空（`date_state=none`，无 `as_of` 比较）→ pass（其中 1 条为空集 proven 的 pass，1 条带 `version_match` 审计）。
- 抽核 3 条 unknown：链为 ref 解析成功、绑定存在、matcher 返回 unresolved（`unit_record_unresolved`）→ `source_unresolved`；这些题**没有** `version_binding_missing` 审计行，说明不是版本缺口。
- 17 = 13 `source_unresolved` + 2 `empty_set_not_proven` + 2 `model_events_missing`。
- `violations` 0→0 不是洗白：没有任何纠正把 violation 改成 pass/unknown；9 条 unknown→pass 全部是“ref 可匹配化”（A 类 7）+“空集 pass”（C 类 2），且 violations 两侧都为 0；无 unknown→N/A（新侧该轴 N/A = 0，精确）。

### 2.6 11 分诊与 safety（结论：分类计数站得住，但 1 条 safety pass 是**空检查**、3 条 cause 码误标；r2 判 undetermined 自洽）

- 10 条 `evidence_insufficient` 不是“回避判定”的兜底：逐题都能落到具体输入缺口（合同实体 targets 缺、shared_background 未投影、record 身份缺、`model_events_missing`、`empty_set_not_proven`）。但：
  - **3 条 cause 码误标**：标 `version_binding_missing`，而这些题的 stale 审计里没有绑定缺口（绑定存在）。我逐 ref 复算其 stale `target_refs`：5 个 ref 实例命中 `unit_record_unresolved`（另 2 个是 `doc_mismatch`，属 no_match、不产生 unknown），即真实原因是 unit record 身份缺口 —— 与报告自身 R-Q1A3R2-07（record_code 是剩余 unknown 主因）**互相矛盾**（分歧 D-2）。
  - **1 条 required safety 空检查**：唯一 `required` 的 `forbidden_content` 题，`forbidden_values=0`、`forbidden_sources=0`、`expected_sources=0`（`should_refuse=true`），产品该回合 final kind 为 `clarification`（非拒答）；冻结 Q1a-1 只对 `must_refuse_security` 强制拒答，故该轴“无东西可查”而判 pass（`frozen_forbidden_checks_ok`）。这正是 E0 残余 #2 警告的 vacuous pass，R2 **没有把该残余带过来**，反而在 §5 写“forbidden_value/refusal 检查与旧侧同源”并给 safety pass 1（分歧 D-3）。
  - 该题在分诊里被归 `evidence_insufficient`（因 cross_entity/stale unknown），掩盖了上述判据缺口。
- `product_error = 0` 在新判据下站得住：四轴 violations 全 0；近似信号（`target_ref_no_match` 5 个 unit）无法升格为实体级确证。**没有**一条“可确证 violation”。
- r2 判 `undetermined` 与新侧 violations=0 **自洽**：确定性匹配器不能检验保管 A 的语义主张（`outbound_send`）；E0 已记录 r2 的 A/B 分歧且要求不表决。r0 的 `false_positive_under_new_criteria` 由 E0 支撑（两角色均判 annotation/mapping、无禁值、无实际披露），**不是**仅凭 R2 复算；R2 复算本身对 r0 只给出“0 violation + 1 unknown”，旧违规题因旧卡 `detail_export=false` 无法逐题定位。

## 3. 聚合/报告字段核对

- 三公式逐轴成立：`planned = passed+NA+unknown+violations`、`checked = passed+NA+violations`、`planned = checked+unknown`。
- `axes_provenance` 120/120 = `rescored`；旧侧 `recorded_old_aggregate_only`；逐题 old→new `NOT_AVAILABLE`，私有明细无任何旧逐题字段，未构造 `OldCardCase` ✓。
- reason 全在 18 码表：合同 120 轴 `reason` 0 例外（合同文档标题写“19 码”是笔误，经理验收 R-Q1A2-01 已裁定 18；我核对了枚举实数 18）。
- D4–D7：D5（`empty_entity_key`）实测 1 = 登记 1；D7（historical + business_date）实测 2 = 登记 2；D6 结构候选 5（登记 3，差异需题面语义）；D4 只给登记计数 2（不可逐轴定位）；`claim_scope_fully_resolved=false` ✓。
- 分歧带 A/B 两套都报、`selection: "none"`，未选边、未改合同 ✓。
- 公开侧无逐题内容：聚合/报告内 `case_id` 取值 0 处（仅代码字符串与 run/evidence 目录名）；分诊逐题行只在仓外密文中。

## 4. 保全与零调用（独立复算）

- **C 冻结 12/12**：11 个 `[final-object-bytes]` + 1 个 `[C-new]` 现测全等于 `c-freeze.txt` 记录值（含 `p2_hard_evidence.py=fba6e606…`）；另 13 个对照件亦同。
- 仓内 28 个保护件：现测 SHA **等于 before 且等于 after**（0 差异）；R1 产物 `605c89cb…/31836`、`31afe411…`，NOT-RUN 产物 `448bb623…/20416`、`06867c36…/13714` 未变；R1 私有明细 `2f6f4d85…/74488` 未变。
- 外部树（用受控入口 `tree_digest` 复算）：旧 run 树 `7c2072b4…`(72)、holdout `5d628883…`(5)、custody `793a3f24…`(4)、R1 evidence 树 `a1487c70…`(13)、NOT-RUN evidence 树 `5e07b631…`(19)、合同密文 `467dbf77…/47012` —— 全部与 before/after 相同。
- 旧卡 4/4 字节不变（`d055f1ac…`、`df078a34…`、`88ac5a4a…`、`a291e5f2…`）；旧 evidence 树 4/4 摘要不变（`af3c6992…`/`43c287a3…`/`8ca2240b…`/`211b4cfa…`，合成 `16420e90…`）、卡合成 `53e4a82b…` 均与我自算一致。
- git：HEAD/分支不变、**暂存 0**、HEAD 后 0 commit、tracked modified **15 条路径逐条相同**、外来 untracked **2086 文件 / `f85dbe6a…`** 与 before 相同。
- 账本/预算/GO：现值与该包之前（evaluator `09-final-verify` 记录）相同，mtime 分别为 2026-11-14 10:31、2026-11-11，**早于** R2 运行窗口；它们与更早 `c-freeze.txt` 的 `[funding]` 参考值不同属既有状态（E0/验收已记录），非本轮造成。
- 零真实调用：`06-netguard.json` `verdict=zero_network_attempts`、正对照 `blocked`、socket/connect/DNS/create_connection 全 0；before/after `calls` 全 0；我的复核路径亦无网络调用。
- 公开隐私：`05-privacy-scan.json` 133 needles × 22 文件、`total_hits=0`；我另做 `h2-`/`case_id` 取值扫描，0 处。

## 5. 分歧清单（均不影响本轮数值结论）

| id | 级别 | 内容 | 方向/建议 |
|---|---|---|---|
| D-1 | medium | `document_codes` 覆盖是**构造性口径**：`mapped_product_names := distinct`、`unmapped_units := 0`、reason 硬编码；"11/11 / 91/91" 不可能失败 | 事实上为真（我实测 91/91、0 unresolved），但下轮须改实测计数并注明 only 7 个产品名被真实使用 |
| D-2 | medium | 3 条 fail 的 cause 码标 `version_binding_missing`，而这些题无绑定缺口；真实原因是 unit record 身份缺口 | 与 R-Q1A3R2-07 自相矛盾；建议改标 record 缺口码（或 `other_input_gap`） |
| D-3 | medium | safety 唯一 pass 是**空检查**（required `forbidden_content`、禁值/禁源/期望源全 0、产品为 `clarification` 非拒答）；E0 残余 #2 未带入，§5 措辞“refusal 检查同源”误导 | 建议下轮把该轴标 `vacuous_pass`/unknown 并补残余；本轮不改分 |
| D-4 | low | R-Q1A3R2-09 称 7 个 v3 是“公开 ingest 结构外”，但其自身 active 表在 pre_v05 的 D01 槽就是 3（V04 在 ingest 内）；且这 7 个 v3 unit **未被使用** | 表述需纠正；不改变任何判定 |

## 6. 未核（不构成反对）

- U-1 “禁值/拒答检查与旧侧逐字节同源”：旧实现未冻结、旧卡无逐题值，无法核；只能核“同一 final_text/kind 输入”。
- U-2 D4 登记计数 2：需读题面语义；报告自身已标不可定位。
- U-3 “旧 matcher 忽略 doc_code/record_code、无实际披露”：来自 E0 两角色记录，我无法重跑旧 matcher。
- U-4 隐私扫描 133 needles 的具体名单（可能含题面/答案，按边界不读），只核计数与公开侧无泄漏。
- U-5 旧逐题四轴值（`detail_export=false`）：结构上不可得；本包按规未构造。

## 7. 边界声明

- 本复核**零真实调用**；未新建/修改 GO、未写 release、未声称 “T207 通过/P2 完成/质量放行”。
- 未改 C 冻结 12、旧卡/旧证据/旧 seal/case-plan/receipt、账本/预算/GO、合同密文、Q1a-1/1b 模块与契约、三份 acceptance、R1 与 NOT-RUN 产物、执行角色 r2 产物；未 stage/commit/push；未新建 worktree/切分支；未读 `.env`/runbook/scoring/他人会话。
- 本文件只写计数、枚举与 hash；不含题号、题面、答案、目标值、逐题明细或 key。

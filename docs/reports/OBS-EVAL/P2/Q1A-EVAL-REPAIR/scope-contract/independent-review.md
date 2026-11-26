# Q1a-2 scope/targets 合同 v1：保管 B 独立复核

- 复核角色：保管 B（独立复核；非开发、非验收、非经理）
- 日期：2026-11-14
- 复核对象：`q1a-scope-targets-contract/v1`，私有密文 `D:\mktkb-q1a2-scope-contract\scope-targets-contract-v1.fernet`（47012 B，SHA256 `467dbf7706df26f2069a79e2b344b53c0e10c03ff830ed62efff9b5dfd16f461`）
- 结论：**PASS_WITH_DISAGREEMENTS**
- 独立判断冻结：先固定 B 的 applicability 向量（digest `15c2d28b3ff17d79e21b0b5c227e4324b572effdb01f0a2e0823d1a7b92da492`），之后才解密 A 的合同、读取 A 的公开聚合与报告。
- 边界：只读；零真实调用；未读产品回答/最终输出/trace/评分/runbook/scoring/`.env`/旧助手会话/经理会话；未派子助手；未 stage/commit/push/合并/部署；未新建 worktree/切分支；除本包 2 个公开文件外未改任何既有文件。

## 1. 入口与绑定

| 项 | B 复核值 | 结论 |
|---|---|---|
| dataset_version | `P2-HOLDOUT-v2` | 一致 |
| label_version | `p2-holdout-v2-2026-11-10` | 一致 |
| 题/回合 | 30 题、36 回合、25/4/1 直方图（1/2/3 回合） | 一致 |
| 题序 | 30/30 与冻结加载序同序；scenario_id 30/30 与 v0.2 同题一致 | 一致 |
| cases_sha256 | `a0ad48c9bbab96ac683e325c773dfee2dc247708fea7ddeefb08f567b102c3c3` | 一致 |
| old_run_binding_sha256 | `291cfec9d99446c88f0063d533c92632cef15594c1f6ce3da2269cef98ae65d4`（去 `binding_sha256` 后 canonical 复算） | 一致 |
| old_run_binding_file_sha256 | `3108b87b13373802bee6566999cd7196fcfbc5de1853707447e0356f07d775ee` | 一致 |
| 4 个旧 run | `run_index`/`scenario_id`/`run_id`/`plan_id`/`plan_sha256` 逐值等于 run-binding | 一致 |
| v0.2 密文 | `3d60c27364244a6ff8df76f66994ee50e5037649ea346c4b538f1fb9175ce4d0` | 一致 |
| v0.3 addendum | `80a8c4a11aa452cde86dc7887642ea05c374eaaf40b668a0692faa8ac37c9b2f` | 一致 |
| scenario 契约 | `39c7e16103acdac52741a48d895b29ff5675ee97e5691955ccebe5b21a1274ad` | 一致 |
| source_map | `86c86767ce5f4251ff52589cca9d02882aa7f47e23caf7cde654133b8ea821b5` | 一致 |
| ingest_plan | `362e3ea10f673021d78c7a647305f04b8557b364a14482ebc2ba370d7752ed19` | 一致 |
| manifest / v0.2 schema | `8874985e…` / `9fbe4b33…` | 一致 |
| 合同 bindings | 17/17 键从原始输入重算并逐值相等 | 一致 |

入口结论：PASS。A 的 17 个绑定、4 个旧 run 归属、30 题/36 回合与全部公开记录逐值一致；未发现旧 binding 改写或题集/场景错位。

## 2. 结构与 roundtrip

- 30/30 题、120/120 轴；每轴恰 7 字段（`applicability`/`criterion`/`reason`/`target_refs`/`targets`/`as_of`/`temporal_intent`）。
- 枚举、criterion、reason、temporal_intent、as_of 日期规范、target_refs 集合边界与去重、targets 三键/类型/filters 值类型：0 违规。
- 合同 `scenario_id` 30/30 与 v0.2 同题一致；`case_index` 连续；`case_id` 唯一且同序。
- v0.3 恰 4 个 gap 轴整体替换；其余 116 轴逐值不变；合并后 120 轴与合同逐轴深度相等（0 mismatch）。
- 解密→canonical 明文→重新 Fernet 加密→再解密，明文逐字节相等；canonical 明文 SHA256 `e231a1db4fbd8c9613d4e19f33765a466b02e1ca0a6deae1e5030b4db861320b`。
- `unknown` 总数 0；`unknown_downgraded=0`；未发现新增/删除轴或 unknown→N/A。
- A 的 `axes_120_exact_7_fields`、`axes_equal_merged_annotation`、`cases_30_same_order`、`gap_basis_verbatim`、`roundtrip_equal`、`unknown_downgraded=0` 均经 B 独立复算成立。

结构结论：PASS。

## 3. 独立重判（先冻结，后比对）

B 仅以冻结题面/原标签、公开语料、12-source 配方、source map、冻结业务基准日为判断依据。B 的独立 applicability：

| 轴 | B required / not_applicable / unknown | A required / not_applicable / unknown | 差异轴数 |
|---|---:|---:|---:|
| safety | 2 / 28 / 0 | 2 / 28 / 0 | 0 |
| cross_user | 30 / 0 / 0 | 30 / 0 / 0 | 0 |
| cross_entity | **21 / 9 / 0** | **30 / 0 / 0** | **9** |
| stale_source | 30 / 0 / 0 | 30 / 0 / 0 | 0 |

- 9 个差异全部在 `cross_entity` applicability：B 按“是否有明确业务实体目标/比较集合”的严格读法判 9 个 N/A；A 按 `shared_background`/`structured_target` 判 required。分歧保留，不表决。
- basis：按公开 schema §4.1 的确定性优先级复算，120/120 与 A 的 `basis` 逐值一致；分布为 `frozen_label_target 21`、`frozen_question_scope 62`、`public_corpus_structure 32`、`case_business_date_baseline 5`、`no_provable_basis_keep_unknown 0`。basis 差异 0。
- targets/scope：A 的 `target_refs` 均指向冻结的 expected/relevant/forbidden ref；5 个无 ref 的 cross_entity 轴使用 store/item/record_collection/document 身份；未发现运行期 record id、数据库 row id、record_code 字段或实体实例的臆造。
- 残余 scope 薄弱项 6 个（见 §5 D4–D6）：2 个显式时间窗未写入 filters、1 个实体键为空、3 个 stale 轴只有 as_of 而无 source target。另有 2 个历史意图轴以业务基准日作 as_of（A 已披露，见 §4c）。

## 4. 六项挑战逐条结论

### a) `cross_entity` 30/30 required、unknown 0 是否成立

结构上成立：19 个 `structured_target` + 4 个 `multi_target` + 7 个 `shared_background`，criterion 均在冻结枚举内；0 unknown 来自 v0.2+v0.3 合并标注，未见新增/降级。A 的 target 是“请求范围业务记录集合/实体身份”（冻结 ref、store/item/record_collection/document 身份），不是运行期实际记录身份：没有运行期 row id、数据库主键或索引实例。B 的严格读法则认为 7 个共享政策题、1 个政策对比题、1 个文档工件题没有“业务实体目标”，应为 N/A；这是 9 个差异的来源。运行期 27 个 cross_entity unknown 是运行期 owner/实体/记录快照缺失（证据缺口），不是标注 unknown（标注 unknown=0）；A 在报告 §7 第 3 项与聚合 `runtime_axis_evidence_produced=false` 中明确区分，未把两者混为一谈。结论：30/30 不是臆造运行期记录，但语义上并非无争议；B 保留 9 个 N/A 差异。

### b) `safety` 28 个 `not_applicable` 是否逐题有冻结依据

B 全量核对 28 个 N/A：均为良性业务问答，或“语料缺字段/缺记录/缺台账”的拒答；冻结题面/标签中没有安全、保密、越权、注入或禁值/禁源契约。2 个 required 轴分别有明确的未入库内容边界与最小必要披露/隐私契约。未发现因“难判”批量选 N/A，也未发现 unknown→N/A。A 的 28 个 N/A 继承自冻结标注，B 的独立复核确认其语义；结论：成立。备注：其中一个 required safety 轴的 criterion 也可读作 `must_refuse_security`，A 用 `forbidden_content` 仍在枚举内且有“不得输出其内容”的标签支持，不构成实质分歧。

### c) `stale_source` 25 个 `public_corpus_structure` 与 5 个 `case_business_date_baseline`

- 25 个 `public_corpus_structure`：B 抽查并交叉核对 12 个公开语料源的实际结构（表格的 sheet/row、文档标题、PDF 页、变体的行/页/版本），这些轴的 `target_refs` 均落在公开语料的真实单元上；source map 的版本映射也与公开记录一致。未发现把不存在的单元/版本写成语料结构依据。
- 5 个 `case_business_date_baseline`：5 个轴的 `as_of` 均为 `2026-10-28`；A 的 schema §1.4/§4 明说这是“产品应使用的业务基准日”，不是产品实际使用该日期的证明；报告 §7 第 3 项与聚合 `runtime_axis_evidence_produced=false` 再次声明运行期实际日期使用未验证。B 未发现 A 把该日期当成产品实际使用证据。
- 残余：5 个 baseline 轴中 2 个是历史意图（“当初”/“上个月”），业务基准日只是评估基准，不是历史事件日期；3 个轴没有 target_refs，只有 as_of。A 对历史意图作了披露，但合同未给出历史事件日期；这是残余 scope 薄弱项，不是伪造日期。

结论：25 个 corpus structure 依据成立；5 个 baseline 的 as_of 等于 2026-10-28 且未被冒充为产品实际使用证明；历史意图的 as_of 语义仍有残余风险，保留记录。

### d) `axes_equal_merged_annotation=true` 与“真实合同生成”

B 独立复算 120/120 轴与合并后的 v0.2+v0.3 逐值深度相等，A 的 `axes_equal_merged_annotation=true` 成立。A 的公开 schema §1.5 与 §2.4 明说本合同是“原样投影”，只补可消费结构与 basis；A 的报告 §3 也写“逐值等于冻结标注、未新增/删除/改写”。因此本合同实质是 v0.3 冻结标注的再投影，而不是从冻结题面/标签/语料独立重新生成的 scope/targets 合同。它作为 Q1a-1b/Q1a-3 的可消费结构是有效的，但“真实 scope/targets 合同生成”这一任务应降级为“忠实投影 + 可消费结构 + basis 来源分类”；本次没有新增独立的 scope/targets 语义证据。该偏差如实记录，不替 A 圆场；这是本复核不判 PASS 的主要原因之一。

### e) `privacy_scan` 3 处 substring 命中

B 用 194 个 needle（30 个 case_id、36 个题面/回合、30 个参考答案、21 个 expected value、9 个 forbidden value、12 个 doc_code、9 个 record_code、30 个 notes、target 类型/键/filter 键/值）扫描 3 个公开文件：总命中 3 个，均为 substring-only：

- 1 个 8 字符通用类型词出现在 schema（公开 schema 用词）；
- 2 个 4 字符通用类型/filter 键作为 `items` 等更长公开 token 的子串出现在聚合。

公开文件中：case_id 模式命中 0、题面/回合命中 0、参考答案命中 0、expected/forbidden 值命中 0、doc/record code 命中 0、notes 命中 0、target 键/值命中 0、key 材料精确命中 0；67 个 64-hex token 与逐题/逐轴 hash 碰撞 0。A 的 `sensitive_hits=0` 成立；A 的分类（1 label_value + 2 target_entity_type）与 B 的分类（1 target_entity_type + 2 target 类型/filter 子串）略有差异，但两者都确认 3 个命中非敏感。结论：公开文件无题号/题面/答案/目标值/逐题 hash/key 材料。

### f) basis 是否为“贴标签掩盖无依据”

B 按公开 §4.1 逐轴复算：120/120 basis 与 A 一致，0 mismatch；`no_provable_basis_keep_unknown` 计数为 0，没有发现本应保留 unknown 却被替换成其他 basis 的迹象。4 个 v0.3 gap 轴的 basis 逐值保留；其余 116 轴由确定性规则生成。5 个 baseline 轴中 2 个来自 v0.3 gap 例外，3 个是“无 ref、as_of=基准日”的规则回退；这 3 个轴只有 as_of、没有 source target，属于 scope 薄弱项，但 basis 本身是 `case_business_date_baseline`，不是伪造成 `public_corpus_structure` 或 `frozen_label_target`。单 basis 方案会掩盖“25 个 corpus_structure 轴的 as_of 也来自基准日”这一事实；A 的 schema 规则公开、报告也披露业务基准日，故不构成虚假陈述，但建议消费者同时读取 as_of 与 basis，不能只看 basis。

## 5. 分歧清单（保留，不表决）

| ID | 类别 | 轴数 | B 判断 | A 判断 | 状态 |
|---|---|---:|---|---|---|
| D1 | `cross_entity` 共享政策背景（`shared_background`） | 7 | N/A（无具体业务实体目标） | required（共享背景仍需实体边界检查） | 实质分歧，保留 |
| D2 | `cross_entity` 政策对比（`multi_target` 指向两份政策） | 1 | N/A（无业务实体目标） | required（比较集合） | 实质分歧，保留 |
| D3 | `cross_entity` 文档工件目标（`structured_target` 指向文档/sheet） | 1 | N/A（非业务实体） | required（结构化目标） | 实质分歧，保留 |
| D4 | `cross_entity` filters 未编码显式时间窗 | 2 | 应编码时间窗 | filters 为空，时间窗留给 stale_source | 残余 scope 薄弱项 |
| D5 | `cross_entity` 实体键为空 | 1 | 应有非空 canonical key | `entity_key=""`，靠 filters 承载 | 残余目标身份薄弱项 |
| D6 | `stale_source` 只有 as_of、无 source target | 3 | 应补 source ref/target | 仅 as_of | 残余 scope 薄弱项 |
| D7 | 历史意图轴以业务基准日作 as_of | 2 | 历史事件日期未知；基准日只是评估基准 | 已披露“非产品实际使用证明” | 已披露限制，保留 |

合计：**实质分歧 9 项**（D1 7 + D2 1 + D3 1），**残余 scope 薄弱项 6 项**（D4 2 + D5 1 + D6 3），**已披露限制 2 项**（D7）。不表决、不择优、不修改 A 的交付。

## 6. 未核项

1. 合同尚未被 Q1a-1b 的 matcher/适配器实际消费，也未在 Q1a-3 的真实旧 evidence 上运行；B 只验证了结构/字段/refs 的可消费性，未验证真实 adapter 消费。
2. 运行期 `cross_user` owner、`cross_entity` 实体/记录身份、`stale_source` 实际日期使用、全局禁值禁源：0 运行时证据；合同不产生 `checked`/`violations`。
3. A 的 `public_plaintext_written=false` 只能对 3 个公开文件与已知路径作扫描；无法证明 A 的进程从未在别处写明文。B 未发现公开文件泄漏，也未发现本包新增明文文件。
4. A 的开工前 216 条 status 计数无法由 B 独立复原；B 以复核开始时的 15 tracked modified + 2043 个 untracked 文件为基线。复核窗口内 15 个 modified 与 49 保护件不变；2043 个基线 untracked 文件中 2039 个不变，4 个 Q1a-1b 并行角色文件被外部改动（非 B），另有 5 个 Q1a-1b 并行新增文件；B 自身只新增本包 2 个文件。
5. A 的 `privacy_scan` needle 集为 135，B 的复扫为 194；3 个 substring-only 命中可复现，但分类口径略有差异（见 §4e）。
6. 2 个历史意图 stale 轴的历史事件日期、3 个 stale 轴的实际生命周期来源、2 个 cross_entity 时间窗的具体编码，均未在合同中明确；保留为残余缺口。

## 7. 保全与零真实调用

- C 冻结 12/12 一致（`c-freeze.txt` 的 12 个对象字节）。
- 49 项保护件（C 冻结 12、资金 3、H2 questions/labels/manifest、v0.2/v0.3 密文与公开报告、旧 run binding、4×card、4×case-plan、4×receipt、4×seal-manifest、4×evidence manifest）before/after 逐项 SHA256 全等；B 复算 49/49，0 mismatch。
- v0.2/v0.3 密文、旧卡/case-plan/回执/seal、ledger/budget/GO 未被本复核改动；A 的 3 个公开文件未被本复核改动。
- 15 个 tracked modified 的 SHA256 前后不变；49 保护件不变。复核窗口内 2043 个基线 untracked 文件中 2039 个不变，4 个 Q1a-1b 文件被并行角色改动（非 B）；B 自身只新增本包 2 个公开文件，另有 5 个 Q1a-1b 并行新增文件；当前 untracked 2050。暂存区空；HEAD 仍为 `97b0066726e5b8d6f94cbc0b63a890084550c106`；分支仍为 `codex/p2-e2e`；0 commit。
- 零真实调用：未调用产品/模型/embedding/rerank/OCR/裁判/检索/鉴权/余额；未新建 GO、未预留/付费、未启动服务、零出站网络。B 的受控进程在 socket/connect/connect_ex/create_connection/getaddrinfo 计数均为 0；未派子助手。
- key 只在受控进程内存读取；未打印、未复制、未写入报告；未把逐题明文写入仓库或未加密文件。其余仓外临时脚本只含索引码/路径/hash；复核过程中发现 2 个临时输出/探测脚本含目标值/语料值，已立即删除，未写入仓库，也未用于最终报告。

## 8. 裁决

**PASS_WITH_DISAGREEMENTS。**

- 不判 PASS：存在 9 个实质语义分歧（cross_entity applicability），6 个残余 scope 薄弱项；合同实质是 v0.3 冻结标注的忠实再投影，“真实 scope/targets 合同生成”应降级；合同消费与运行期证据仍未验证。
- 不判 FAIL：17/17 绑定、30/30 覆盖、120/120 轴、7 字段/枚举/refs/targets/日期全部通过；roundtrip 一致；无 unknown→N/A、无新增 unknown；未发现运行期记录身份臆造；公开文件无敏感逐题内容；49 保护件与 15 个 modified 文件前后不变；零真实调用。
- 本复核不修改 A 的交付、不冻结合同、不宣称质量通过/放行，也不进入 Q1a-3；是否返工、是否接受分歧由主人/经理决定。

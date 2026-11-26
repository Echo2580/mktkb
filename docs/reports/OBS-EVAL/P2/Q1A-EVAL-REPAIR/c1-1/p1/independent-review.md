# C1-P1 合同 v2：保管 B 独立复核

主人，以下是独立复核结论。本轮只读、零真实调用、未改 A 的交付与 v1 全套。

- 角色：保管 B（独立复核；非开发、非验收、非经理）
- 日期：2026-11-14；分支 `codex/p2-e2e`；HEAD `97b0066726e5b8d6f94cbc0b63a890084550c106`
- 复核对象：v2 schema `b98f9f4a…` / 26521 B；v2 聚合 `745f9c71…` / 26565 B；v2 报告 `ce9116c3…` / 17491 B；v2 密文 `7ed0bf41…` / 99128 B（明文 74282 B）
- 结论：**PASS_WITH_DISAGREEMENTS**

## 1. 硬结论

| 项 | 独立结果 |
|---|---|
| 30 题 / 36 回合 / 120 轴 | PASS；`cases_sha256=a0ad48c9…c3c3` 与冻结记录逐值相等 |
| 顶层 6 键 / `bindings` 17 键 / `runs` 4 项 / 30 case / 每 case 5 键 / 每轴 7 字段 / 每 target 3 键 | PASS |
| 17 binding：16 键与 v1 逐值相等，仅 `contract_schema_sha256` 变 | PASS；v2 schema 字节复算一致 |
| 6 个不可改字段 + `target_refs` + `basis` + `runs`/顺序 | PASS；120/120 轴 0 差异 |
| v1 `targets` 前缀 + 唯一原地改动 | PASS；恰 1 处空 `entity_key` 补全，`entity_type`/`filters` 不变，补全值可重算 |
| `unknown` 总数 / `unknown→N/A` / 新增 unknown | 0 / 0 / 0 |
| `cross_entity` 覆盖 16 + 3 + 11 | PASS；14 轴 refs 投影 + 2 轴 v1 目标修复；3 轴仅不可匹配；11 轴空 |
| `record_code` 76 条 ref | PASS；53 verified / 2 行不在记录索引 / 21 非记录级；76/76 与私有投影逐字段相等 |
| `shared_background` 语料级投影 6/7 | PASS；6 条逐字段可复算，1 条无正向 ref；消费侧条目 0 |
| 边界：无运行期 row id / 索引实例 / uuid | PASS；targets 与 filters 的 uuid/长 hex 命中 0；新增 target 仅 item/store |
| v1 三件 + v1 密文 / C 冻结 12 / 资金 3 / A 的 23 个输入绑定 | 全等；12/12、3/3、23/23 |
| 15 tracked modified / 外来 untracked / 暂存 / commit | 15 项路径与 R2 基线相同；1,974 个非会话外来文件逐字节不变；110 个 handoff 仅存在性（未读）；暂存 0；0 commit |
| 零真实调用 | netguard 正对照 `blocked`；socket/DNS/connect/create_connection 全 0；B 本轮无网络 |
| 公开文件敏感性 | 214 个 needle：题面/答案/目标值/记录码/单元码/长字符串/哈希碰撞/密钥材料命中 0；2 个 3 字符变体码示例命中；另有 4 个 gap 序号（见 D6） |

## 2. 六项挑战

### 2.1 共形性（A 自报风险①）

**判断：不是严格循环论证，但“身份形态”与产品共定义，受影响面 16/30 轴。**

- v2 的目标记录由冻结 refs 选择，不是从产品回答/输出反推；这一点成立。
- 身份三元组由公开纯函数 `mktkb.rag.chunking._entity` 作用于语料记录得到，而产品运行期也用同一函数给 unit 赋 `entity_type`/`entity_key`。因此匹配只能证明“产品实际使用的 unit 与目标记录在同一身份函数下同身份”，不能证明实体模型本身语义正确；若产品改投影分支而合同未换版，合同会失效（schema §13 已写 `entity_projection_rule_changed`）。
- 受影响的是全部 16 个可匹配轴：14 个由 refs 投影，2 个由 v1 目标修复。`stale_source` 的 14 个记录身份不依赖 `_entity`，不受此共形影响；`shared_background` 消费侧仍为空，也不受影响。
- 影响被本批语料限制：12 条记录在 `_entity` 下产生 **12 个不同实体身份**（8 item + 4 store，0 个重复组）；16 个可匹配轴的 17 条 ref 记录全部命中唯一身份。因此本批不存在“两个记录同身份、target 分不清”的歧义。共形性的实际代价是**无法发现 `_entity` 分支/字段角色语义错误**，不是“target 可随便匹配到别的记录”。
- 结论：方法学让步真实存在，但在本批语料下可接受；P4 不应把该匹配宣称为“语义正确”，只能宣称为“记录使用/身份投影一致”。

### 2.2 转换假象（A 自报风险②）

**判断：A 说“无法量化”不准确；可做结构量化，且风险面是全覆盖。**

- 19 个 `cross_entity` 非空目标轴中，16 个是 v2 新增可匹配目标（14 refs + 2 修复）；3 个是 v1 遗留的仅不可匹配目标（2 `record_collection` + 1 `document`），v2 没有给它们新增记录目标。
- 4 个 scenario 的上传集**全部**同时含 `docx`、`pdf-text`、`xlsx`；16/16 个可匹配轴的活动 scenario 都含非表格文档，**0/16 可结构排除**。3 个仅不可匹配轴同样含文本源，但其风险在 v1 已存在，不是 v2 新引入。
- 冻结 `_check_cross_entity` 对 `entity_type="document"` 的文本块会走 `other_entity_used` / `citation_entity_mismatch`（`p2_hard_evidence.py:2093-2099`），除非 unit 没有 entity_type/key（此时跳过）。产品 `chunking._text_chunks` 给文本块 `document|<runtime uuid>`，因此只要该轴实际用了文本块，就会出现 violation。v2 不授权把这类 unit 降级为 unknown。
- P4 处理建议（必须显式做，不能默认）：
  1. 先实现 §3.4 的 `matchable` 判定；不可匹配 target 不得当作“永不匹配”的证据。
  2. 对 `document` 级 unit：在没有经理批准的分类语义变更前，保持 `unknown`（固定码），不得判 violation；或等 C1-P3 快照把公开 `doc_code` 落盘后，用 doc_code 粒度比较，而不是运行期 uuid。
  3. 不得把 `shared_background_corpus` 的语料单元身份当运行期 `document_id`/`version_id`/`unit_ids`；消费侧仍应为空。
  4. 在 C1-2 前给一份逐轴“文本源暴露”清单；不能因为 16/30 可匹配就直接签 GO。

### 2.3 覆盖率 16/30 是否真实

**判断：16/30 真实；顶层 16 + 3 + 11 穷尽且互斥；但 A 的两处表述会误导。**

- 独立分类：16 轴至少一条 `matchable`；3 轴 `targets` 非空但均不可匹配；11 轴 `targets` 为空。
- 11 轴空 = 7 轴 `shared_background`（其中 6 轴有正向 ref、1 轴无正向 ref）∪ 4 轴正向 ref 非记录级（3 轴纯 `ref_not_record_level` + 1 轴与 `record_row_not_in_record_index` 合轴）。这两组不重叠，合计 11。
- 3 轴仅不可匹配 = 2 轴 `record_collection`（正是 2 个 v0.3 addendum 披露轴）+ 1 轴 `document`。因此 **2 个“永久阻断”是 3 个仅不可匹配的子集，不是第 4 个桶**；`4 非记录级` 是 11 个空轴的子集。把 11+3+4+2 相加会重复计数 6 轴；顶层只需 16+3+11=30。
- 但 A 报告 §6 的 `no_positive_refs 5` 不是“5 个仍缺目标轴”：独立枚举这 5 轴 = **2 个已由 v1 目标修复变为可匹配的轴 + 3 个仅不可匹配轴**。所以该原因表是跨类码表，不是分区表；不能据此说“还有 5 轴缺目标”。
- A 报告 §5/§10 的 “v1 可匹配 1/30” 与 v2 §3.4 自相矛盾：v1 那条 store 目标的 filters 含非角色键，按同一 §3.4 不满足 `matchable`；独立重算 **v1 严格可匹配 = 0/30**。v2 的 16/30 不受影响，改善量应为 +16 而不是 +15。
- 结论：16/30 与 16+3+11 成立；分类没有漏轴，但 A 的 v1 基线与 §6 原因表需要修正。

### 2.4 `record_code` 规则可重算性

**判断：确定性、可逐条重算、未用答案反推；76/76 一致。**

- 独立实现 R-RC-1..R-RC-5（不复用 A 的生成脚本）：对 120 轴的 76 条 ref（58 expected + 18 forbidden；cross_entity 29、stale 44、safety 3）逐条解析。
- 结果：`record_code_verified 53`、`record_row_not_in_record_index 2`、`ref_not_record_level 21`。与私有投影逐字段（`doc_code`/`base_doc_code`/`sheet`/`row`/`record_key`/`record_code`/`code`）比对 76/76 相等。
- 规则只使用冻结 ref + 公开语料 manifest/source-map；没有读产品回答、评分或 trace，也没有从答案反推 record_key。
- 两个边界：① schema §5 R-RC-1 把 `business_version` 列为记录身份的一部分，但 §3.5 与实际 `record_identities` 的 11 字段没有它；版本可从 `sources` 反查，53/2/21 不受影响，但“记录身份元组”交付不完整（D4）。② schema §5 说“本批 2 个变体 ref 均一致”，独立枚举实际有 **7 个变体码 ref**（2 个 cross_entity expected + 5 个 stale；6 个带 record_code，1 个非记录级），全部重算一致；`2` 是漏计（D5）。

### 2.5 语义零改动

**判断：成立，唯一原地改动不影响该轴判定。**

- 120/120 轴的 `applicability`/`criterion`/`reason`/`target_refs`/`as_of`/`temporal_intent` 与 v1 深度相等，0 差异；`basis` 0 差异；`runs`/`case_id`/`case_index`/`scenario_id`/顺序 0 差异。
- 独立把 v0.2 标注 + v0.3 resolved gap 合并后与 v1 轴对象比对：120/120 深度相等；v2 与 v1 相等，因此 v2 也等于合并标注。
- v1 `targets` 是 v2 前缀：唯一差异是 1 处空 `entity_key` 补全；补全值由该 target 自身 filters 按 §4.3 重算，`entity_type`/`filters` 逐值不变。`applicability`/`criterion`/`reason` 未变，因此该轴的判定语义不变；变的是“该 target 从空键变为非空、可进入匹配”，这是 schema 明示的机械修复。
- 新增 18 条：17 条 refs 投影 + 1 条 v1 非角色 filter 的规范身份追加；5 条 v1 保留。target 总数 6→24；`cross_entity` 5→23；safety 1→1；stale/cross_user 0→0。逐轴尾部集合与独立重算一致，排序也一致（`tail_ok=true`）。
- `unknown` 总数 0（v1 冻结态），`unknown→not_applicable` 0，新增 unknown 0。

### 2.6 是否越界成运行期身份

**判断：没有。新增 targets 是“请求范围记录集合身份”，不是运行期记录实例。**

- 24 条 target 的 `entity_key` 中 uuid 命中 0、32+ 位 hex 命中 0；filters 值中 uuid/长 hex 命中 0。
- 18 条新增 target 的 `entity_type` 只有 `item`/`store`（9 + 9）；`document`/`record_collection` 只出现在 v1 遗留 target（各 2/2），v2 未新建。
- `record_identities` 使用语料 `doc_code`/`sheet`/`row`/`record_key`，没有数据库 row id、索引实例、运行期 document/version id。
- `shared_background` 的 6 条语料级条目 `runtime_unit_ids=[]`、`runtime_identity_bound=false`；消费侧条目 0。没有用运行期 used units 反填目标。

## 3. 附加核项

### 3.1 `shared_background` 6 条

6/6 逐字段可复算：`doc_code`/`base_doc_code` 来自冻结 ref 的语料单元；`business_version` 来自 source-map 的 `version_number` 或 manifest 的 `business_version`；`scenario_active_version` = 该 case 的 scenario 上传集中同一 base 文档槽的最大版本；`locator_kind` 由 page/heading/sheet+row 确定；`unit_identity_code = "<base>@<version>:<kind>"`；运行期字段为空/False。7 个 `shared_background` 轴中 6 个完成、1 个无正向 ref，与 A 报告一致。

### 3.2 保全、仓库与零调用

- v1 密文 `467dbf77…`、v1 schema `cb1257fa…`、v1 聚合 `9abfa5f2…`、v1 报告 `b063a432…` 全部与 A 的 lineage、且当前字节未变。
- C 冻结 12/12 当前 SHA256 与 A 的 before/after 全等；资金 3/3 全等；A 的 23 个具名输入绑定（含 v1、v0.2/v0.3、holdout、fixtures、source map、ingest、scenario、chunking/tokenize）当前全等。
- R2 基线快照的 28 个 repo 文件、115 个外部文件、1,974 个非会话 untracked 文件逐字节全等；110 个 `.claude/handoffs` 文件只做存在性检查（边界不读他人会话）；2 个仓外 `%SystemDrive%` 条目跳过。
- 15 个 tracked modified 路径与 R2 基线逐条相同；其中 3 个（`cli.py`、`product_adapter.py`、`p2_holdout_scenarios.py`）在 A 的 59 项 before/after 中全等；其余 12 个无独立早期哈希，保留“路径集合 + 复核窗口内不变”的口径，不冒充全窗口字节证明。
- 暂存区空、0 commit、HEAD/分支不变；未新建 worktree/切分支；B 只新增本包 2 个公开文件。
- 零真实调用：R2 netguard 证据 `positive_control=blocked`，`socket_constructed/connect_attempts/dns_attempts/create_connection` 全 0，inner `exit:0`；A 的 `verify.out.txt` 也记录 socket/DNS/provider 0。B 本轮未调用产品/模型/embedding/rerank/OCR/裁判/检索/鉴权/余额，未启动服务、零出站。

### 3.3 公开敏感性

- 214 个长 needle（30 case_id、36 题面/回合、30 参考答案、30 notes、21 expected、9 forbidden、12 target key、9 filter value、12 record key、9 record code、12 doc code、4 unit code）扫描 3 个公开 v2 文件：**2 个命中**，均为 schema 规则说明里的 3 字符变体码示例（属公开语料词表，不是具体目标值）；题面/答案/expected/forbidden/target key/filter value/record code/unit code 命中 0。
- 69 个 64-hex token 与题面/参考答案哈希碰撞 0；Fernet key 形态命中 0；`key_material_hits=0`。
- 但公开报告在 §1 披露了 **4 个 gap 轴的 `case_index` 序号**（无题面/答案/目标值），与报告自称“无题号”不一致；如果 `case_index` 按“题号”计，这是公开边界泄漏。独立判断：这是可一行删改的元数据泄漏，不是合同载荷泄漏；见 D6。

## 4. 分歧（保留，不表决）

| ID | 严重度 | 内容 | 处置建议 |
|---|---|---|---|
| D1 | 实质（数值） | A 报告 §5/§10 的 v1 可匹配基线 1/30 与 v2 §3.4 不一致；严格重算 v1 = **0/30**，v2 16/30 不变，改善量 +16 而非 +15 | 报告改为 0/30，或明确“1/30 是宽松口径” |
| D2 | 实质（分类） | §6 的 `no_positive_refs 5` 跨类：2 个已修复为可匹配 + 3 个仅不可匹配；原因表不是分区表 | 把原因码按“可匹配/仅不可匹配/空”分组重列，不与 16+3+11 相加 |
| D3 | 实质（风险） | A 称转换风险“无法量化”；结构量化显示 16/16 可匹配轴均有非表格文档暴露，0/16 可排除；3 个遗留轴同样有文本源 | P4 必须先定 document 级 unit 的处置；C1-2 前不得把 16/30 当“可直接判” |
| D4 | 轻微（schema） | R-RC-1 把 `business_version` 列入记录身份，但 §3.5 与实际 `record_identities` 无此字段；76/76 的 record_key/record_code/code 重算仍通过 | 补字段或在 §5 说明版本由 sources 反查 |
| D5 | 轻微（文档） | R-RC-5 称“本批 2 个变体 ref”，实际 7 个变体码 ref（2 cross_entity + 5 stale；6 个带 record_code、1 个非记录级），全部重算一致 | 修正计数，不影响规则 |
| D6 | 合规（元数据） | 公开报告披露 4 个 gap 轴 `case_index` 序号；schema 用 2 个 3 字符变体码作示例，命中 doc-code needle；无题面/答案/目标值/长 needle/哈希/密钥命中 | 若 `case_index` 计题号：删除该行序号后再交经理；否则由经理明确记录“序号非题号” |

## 5. 对 C1-2 收益的独立预估

**前提：不读运行期回答/trace；以下只是合同侧结构上界，不是产品行为预测。**

| 轴 | R2 当前 unknown | v2 后最好情况 | 现实区间 | 依据 |
|---|---:|---:|---:|---|
| `cross_entity` | 29 | **13–14** | **16–20** | 16/30 轴有可匹配目标；30-16=14 个非可匹配轴仍会 unknown；现有 1 个 pass 是否落在这 16 轴内无法从合同侧判定，故给 13–14；若部分轴运行期没有 entity 身份，或 P4 把 document 级 unit 保持 unknown，实际会更高 |
| `stale_source` | 17 | **17（仅 P1）** | **6–10（P1+P3+P4）**；4–6 是 P1+P3+P4+P2 的绝对下界 | v2 刻意不给 stale 加 targets，冻结 `_check_stale_source` 不读 `axis.targets`；14 个轴的正向 ref 记录身份虽已解析，但运行期 `UnitView.record_code` 仍空（R-Q1A3R2-07）。P1 单独不降；P3 落盘 record_code 后，13 个 `source_unresolved` 才可能转 checked；2 个 `empty_set_not_proven` 还要 P2，2 个 `model_events_missing` 需重新采集 |

- A 的“`cross_entity` 可判轴数上界 16/30”算术成立；但“此前 1/30”应为 0/30，且 16/30 不等于“复跑后 unknown 直接降 16”。现有 1 个 pass 与 16 轴的关系未知；转换风险还可能把 unknown 变 violation（未知数下降但产品并不通过）。
- A 对 stale 的判断（P1 单独不能降、必须等 P3 快照）是准确的，不算乐观。
- 若只做 P1 + P4 最小适配、不处理 document 级 unit：`cross_entity` 可能降到 13–14，但其中一部分是 violation 而不是 pass；这不是 C1-2 的收益，是转换假象。必须先做 D3 的 P4 处置，再谈 GO。

## 6. 裁决

**PASS_WITH_DISAGREEMENTS。**

- 不判 PASS：D1/D2 是覆盖叙述与基线的实质不一致；D3 的转换风险是全覆盖而 A 未量化；D6 的公开序号披露与“无题号”自述不一致。
- 不判 FAIL：30/36/120、17 binding、120 轴 6 字段/`target_refs`/`basis`、v1 前缀、唯一补全、76/76 记录身份、16/30 覆盖、6/7 shared_background 语料投影、边界、v1/C 冻结/外来 untracked/零调用均独立通过；没有题面/答案/目标值/长 needle/哈希/密钥泄漏；合同载荷本身没有发现语义改动或运行期身份臆造。
- 建议：经理接收前先让 A 修 D6（若 `case_index` 计题号）并更正 D1/D2/D5 的叙述；D3/D4 由 C1-P4/P3 承接。C1-2 不得在本复核后直接签 GO。

## 7. 未主张

不主张 T207 通过、P2 完成、Q1A 质量放行、阈值/发布、运行期四轴证据、真实 H2 可复跑。本复核只读、零真实调用；未改 A 的 v2 交付、v1 全套、C 冻结 12、旧件；未 stage/commit/push；未新建 worktree/切分支；未派子助手；未读 `.env`/runbook/scoring/他人会话/产品回答/trace。

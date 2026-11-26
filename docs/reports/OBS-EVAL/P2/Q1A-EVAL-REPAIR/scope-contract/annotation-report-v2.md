# Q1a 合同 v2：生成报告（保管 A，C1-P1）

- 角色：保管 A（生成）。非开发、非验收、非经理；未派子助手；零真实调用。
- 日期：2026-11-14；分支 `codex/p2-e2e`；HEAD `97b0066726e5b8d6f94cbc0b63a890084550c106`；暂存区 0 项、0 commit。
- 合同版本：`q1a-scope-targets-contract/v2`（规则 `q1a-scope-targets-projection/v2`）。
- 本报告只含安全聚合；无题号、题面、答案、目标值、逐题 hash、交叉表。
- **结论：`PARTIAL_COVERAGE`**（理由见 §5 与 §10：`cross_entity` 16/30 轴获得可匹配目标，`stale_source` 14/30 轴获得记录身份但运行期侧仍缺 `record_code`）。

## 1. 入口自检（先做，后干活）

用既有受控入口 `tools/p2_h2_controlled_execute.py::load_private_bundle`（内部 `load_p2_dataset` + `load_scenario_contract`，并按 v0.3 manager acceptance 校验 addendum；未新写解密/dump 工具）。结果 PASS：

- `dataset_version=P2-HOLDOUT-v2`、`label_version=p2-holdout-v2-2026-11-10`；30 题 / 36 回合 / 30 唯一 case；`cases_sha256` 与公开记录一致。
- v0.2 标注 + v0.3 addendum 合并：120 轴；`unknown=0`；4 个 gap 轴整体替换（`case_index` 15/17/17/18，轴 = stale/stale/cross_entity/cross_entity）。
- 17 项 binding 中 16 项与 v1 逐值相等，仅 `contract_schema_sha256` 换为 v2 schema 字节；旧 run binding payload/file 复算一致；4 个旧 run 逐值等于 v1。
- 零真实调用：`socket_attempts=0`、`dns_attempts=0`、`provider_entry_attempts=0`（netguard 计数快照）；未读 `.env`/runbook/scoring/产品回答/trace/旧助手会话。

## 2. 交付物

| 类型 | 路径 | SHA256 / 字节 |
|---|---|---|
| 公开 schema | `docs/evaluation/q1a-scope-targets-contract-v2.md` | `b98f9f4aab296dd3bec610dc81485142d9cb751a1402a117f14dc30fc515ce25` |
| 公开聚合 | `docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/scope-contract/annotation-aggregate-v2.json` | `745f9c71ba84f284eafffe2e5d063083f630af1c4c36b0eccdd18a5abaee1992`；26565 B |
| 本报告 | `docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/scope-contract/annotation-report-v2.md` | 本文件 |
| 私有密文 | `D:\mktkb-q1a2-scope-contract\scope-targets-contract-v2.fernet` | `7ed0bf411908790423944d5ea151fcdd47baaa9c4871d1fb2d645a017418e260`；99128 B（明文 74282 B） |

密文为**独占创建**（`open(..., "xb")`，路径不存在才写），同一 H2 custody key 容器；明文只在受控进程内存，未写明文脚本/日志/JSON/临时文件/数据库。v1 三件公开产物与 v1 密文一律未动（§9 有 before/after 哈希）。

## 3. v1 → v2：语义零改动的实测证据

| 不变量 | 实测 |
|---|---|
| 120 轴 `applicability`/`criterion`/`reason`/`as_of`/`temporal_intent` 与 v1 逐值相等 | **是**（0 差异） |
| 120 轴 `target_refs` 与 v1 逐值相等 | **是**（0 差异） |
| 120 轴 `basis` 与 v1 逐值相等（含 4 个 gap 轴） | **是**（分布不变：`frozen_label_target 21`、`frozen_question_scope 62`、`public_corpus_structure 32`、`case_business_date_baseline 5`） |
| v1 `targets` 是 v2 `targets` 的前缀 | **是**（仅追加） |
| v1 target 对象的原地改动 | **恰 1 处**：一条 `entity_key` 为空的目标按 schema §6.4 用其自身 `filters` 补全（`entity_type`/`filters` 不变） |
| `bindings` | 16/17 逐值相等；仅 `contract_schema_sha256` 变 |
| `runs` / `case_count` / `case_id` / `case_index` / `scenario_id` | 与 v1 逐值相等 |
| `unknown` 总数 / `unknown→not_applicable` | 0 / 0 |
| 四轴适用性 | 不变：safety 2 required + 28 N/A、cross_user 30 required、cross_entity 30 required、stale_source 30 required |

新增目标条目共 **18 条**（17 条由 refs 投影、1 条为 v1 目标修复追加）；另有 1 条 v1 空键补全。

## 4. 新增内容（按轴）

| 轴 | `targets` 非空轴 v1 → v2 | target 条目 v1 → v2 | 说明 |
|---|---|---|---|
| `cross_entity` | **5 → 19** | 5 → 23 | 14 轴由 refs 投影；2 轴修复 v1 目标（1 补全空键、1 追加规范身份）；其余 14 轴无新增 |
| `stale_source` | 0 → 0 | 0 → 0 | **刻意不加**：冻结 `_check_stale_source` 不读 `axis.targets`，加了不产生可判性（schema §8.6） |
| `safety` | 1 → 1 | 1 → 1 | 本单不投影，零改动 |
| `cross_user` | 0 → 0 | 0 → 0 | 本单不投影，零改动 |

`cross_entity` 的 30 轴逐轴分类（互斥且穷尽）：

| 类 | 轴数 | 码/依据 |
|---|---:|---|
| 有可匹配目标（`matchable`） | **16** | 14 轴 `projected_from_refs` + 2 轴 `v1_target_repaired_only` |
| 只有不可匹配目标 | **3** | 2 轴 `record_collection`（非产品实体词表）+ 1 轴 `document`（运行期 uuid 身份，不可投影） |
| 仍为空 | **11** | 7 轴 `shared_background`（消费侧条目需运行期 id）+ 4 轴正向 ref 非记录级（page/heading） |

其中 **2 轴**另带 v0.3 addendum 的 `request_scoped_collection_no_runtime_record_identity` 披露 → 冻结分类器必然 `unknown`，任何合同投影都无法改判（已单独标记 `axis_blocked_by_addendum_disclosure`）。

`shared_background`：7 轴；**6 轴**完成语料级单元投影（`shared_background_corpus_units_projected`，含 `doc_code` / `business_version` / `scenario_active_version` / `unit_identity_code`），1 轴无正向 ref（`shared_background_no_positive_ref`）；**消费侧 `shared_background` 条目仍为 0**（`shared_background_runtime_identity_unavailable`，见 §7）。

## 5. 覆盖率自查（口径见 schema §10）

| 轴 | 口径 | v1 | v2 | 变化 |
|---|---|---:|---:|---|
| `cross_entity` | 有可匹配目标的轴 | 1（仅有 `store` 型 1 条，且 filters 含非角色键） | **16** | +15 |
| `cross_entity` | `targets` 非空轴 | 5 | **19** | +14 |
| `stale_source` | 正向 ref 全解出记录身份的轴 | 0（规则不存在） | **14** | +14 |
| `stale_source` | `targets` 非空轴 | 0 | 0 | 0（刻意为 0） |
| `shared_background` | 语料级单元投影 | 0 | 6/7 | +6 |
| `shared_background` | 消费侧条目 | 0 | 0 | 0 |
| `safety` / `cross_user` | 不投影 | — | — | 0 |

记录身份（`record_code` 投影）：全部 120 轴的 **76 条 ref** 逐条给出记录身份码 —— `record_code_verified` **53**、`record_row_not_in_record_index` **2**、`ref_not_record_level` **21**；`axes_all_positive_refs_resolved` = **14**（`cross_entity`）与 **14**（`stale_source`）。

## 6. 仍缺的轴与原因分类（不硬填）

| 原因码 | 轴数（`cross_entity`） | 为什么推不出 |
|---|---:|---|
| `shared_background_runtime_identity_unavailable` | 7 | 消费契约要 `document_id`/`version_id`/`unit_ids`，全是运行期 uuid / 索引 id；公开语料结构给不出，用运行期 used units 反填等于用产品输出定义目标 |
| `ref_not_record_level` | 3（+1 与 `record_row_not_in_record_index` 合轴） | ref 落在 `page`/`heading`（文档段落/页），不是表格记录，没有记录键 |
| `record_row_not_in_record_index` | 1 | ref 给 `sheet+row` 但该行不在语料 `sources` 记录索引里（表头/非记录行） |
| `no_positive_refs` | 5 | 该轴无 `expected_sources`/`relevant_units` 正向 ref（含 2 个 gap 轴） |
| `axis_blocked_by_addendum_disclosure` | 2 | addendum 披露「请求范围集合身份不是运行期记录身份」→ 冻结判据直接 `unknown` |
| `v1_target_entity_type_not_product_vocabulary` | 2 | v1 目标 `entity_type=record_collection`（台账/登记表这类逻辑集合），产品实体词表里没有，运行期无对应身份 |
| `v1_target_nonrole_filter_not_derivable` | 1 | v1 目标 `entity_type=document`、`entity_key` 为 doc_code、filter 为 `sheet`：文档身份是运行期 uuid，不可投影 |

`stale_source`：`stale_without_positive_refs` 6、`stale_positive_ref_not_record_level` 10、`stale_record_identity_resolved` 14。**其剩余不可判的主因不在合同**：运行期 `UnitView.record_code` 为空（Q1a-3-R2 R-Q1A3R2-07），需要 C1-P3 的采集快照把 `record_code` 落盘；v2 只提供可逐条重算的记录身份与规则。

## 7. `record_code` 投影规则的可重算性

规则全文在 schema §5（`R-RC-1..R-RC-5`），要点：

1. 记录身份 = `(doc_code, base_doc_code, sheet, row, record_key, record_code, business_version)`；变体码先经 source map 归一到 `base_doc_code`。
2. `record_code` 优先：带 `record_code` 时要求 `sources[record_code].file == base_doc_code` 且 `sheet`/`row` 一致；任何不一致 → 固定码 + **该轴整体不投影**（fail closed）。
3. 无 `record_code` 但带 `sheet+row` 时，用 `(base_doc_code, sheet, row)` 反查语料记录索引；无命中 → `record_row_not_in_record_index`。
4. 只有 `page`/`heading`/无 locator → `ref_not_record_level`（不产生记录身份）。
5. 每条身份写入私有密文 `projection.record_identities`，复核方可用公开语料 + 同题冻结 ref 逐条重算比对。

本包用**独立实现**（`verify_v2.py`，不复用生成脚本的函数）重算了 76/76 条记录身份、14 轴 `cross_entity` 目标集合、7 轴 `shared_background` 条目，与密文逐条相等（`record_identities_equal=true`、`cross_entity_targets_recomputed_equal=true`、`shared_background_recomputed_equal=true`）。

## 8. 未验证项、残余与风险（如实披露）

1. **实体身份形态与产品投影共形（独立性弱化）**：v2 的 `entity_type`/`entity_key`/`filters` 由公开纯函数 `mktkb.rag.chunking._entity` 作用于语料记录得到（模块 SHA256 已绑定）。这让身份可被运行期精确匹配，但代价是「身份形态」与产品实现共定义。因此 v2 下的 pass 只说明「实际使用单元与请求记录同身份」，**不**说明产品语义正确；若产品改投影分支，规则即失效（`entity_projection_rule_changed`）。这是本轮最重要的方法学让步，请复核方重点攻击。
2. **转换风险（unknown → violation）**：`entity_bound` 轴现在有了 `targets`，若运行期实际使用的单元是**非表格文档的文本块**（产品给 `entity_type="document"` / `entity_key="document|<uuid>"`），冻结分类器会判 `other_entity_used` / `citation_entity_mismatch`。v2 **不**授权把这类单元降级为 `unknown`（那是分类语义变更，须经理批准 + C1-P4 单独验收）。本轮无法量化该风险的规模（不允许读运行期回答/trace），只能给出机制与代码位置。
3. **v1 目标缺陷处理**：修复 2 处（空 `entity_key` 补全、`filters` 含非角色键 → 追加规范身份）；残留 3 轴不可修（2 个 `record_collection` + 1 个 `document`）；其中 1 条 v1 目标的 `entity_key` 与其 `filters` 互不一致，只做追加、不改写，属残余。
4. **2 轴永久不可判**：v0.3 addendum 自带 `request_scoped_collection_no_runtime_record_identity` 披露，冻结判据在 `targets` 检查之前就 `unknown`。这不是投影不足，是冻结语义的直接后果。
5. **`shared_background` 消费侧仍空**：即使语料级投影完成，运行期 `document_id`/`version_id`/`unit_ids` 仍缺；须 C1-P3 在采集 schema v0.3 中把 `doc_code` + 版本号 + unit 身份落盘（Q1a-3-R2 已证明 `doc_code` 映射可达 91/91）。在此之前 7 轴只能 `unknown`。
6. **未做消费验证**：v2 尚未被 Q1a-1b/Q1a-3 实跑（其 v1 常量会拒绝 v2，属预期）；P4 的最小改动清单在 schema §12.2。本合同不产生任何 `checked`/`passed`/`violations`。
7. **A/B 的 9 个 `cross_entity` applicability 分歧未表决**：v2 沿用 v1 的 30 required，未借新目标去支持或反对任何一方。
8. **D1–D7 残余项**：D4（显式时间窗未编码）2、D5（空实体键）1（已补全，不再阻塞）、D6（stale 只有 `as_of` 无 source target）3、D7（历史意图用业务基准日）2 —— 本包只消除 D5 的机械阻塞，其余保留原样。
9. **`targets` 与运行期语义的边界**：v2 的 `targets` 是「请求范围的记录集合身份」，不是「运行期实际使用了哪些记录」的证明，也不得当作产品应使用集的充分证据。

## 9. 保全与零真实调用（实测）

- **59 项保护件 before/after 逐项 SHA256 全等**：C 冻结 12（`p2_hard_evidence.py=fba6e606…` 等）、资金 3（ledger/budget/GO）、holdout questions/labels/manifest、v0.2/v0.3 密文与公开报告、合同 v1 密文/schema/聚合/报告、旧 run binding、4×card、4×case-plan、4×receipt、4×seal-manifest、4×evidence manifest、source map / ingest plan / scenario 契约 / fixtures manifest / `chunking.py` / `tokenize.py`。`changed=[]`、`missing=[]`。
- 仓库：分支 `codex/p2-e2e`、HEAD `97b0066…` 不变；暂存 0；commit 0；未新建 worktree/切分支；未 stage/commit/push。
- 新增文件仅 3 个公开件 + 仓外 1 个密文；v1 三件公开产物与 v1 密文字节未变（哈希见上表与聚合 `lineage`）。
- 零真实调用：network/socket/DNS/provider/model/retrieval/embedding/rerank/OCR/judge/real/reservation/new GO/子助手 = 0；未启动服务、零出站（netguard 计数 0）。
- 公开侧隐私自检：3 个公开文件、161 个 needle（case_id、题面、标签值、目标类型/键/filter 值、记录键、共享单元身份），`sensitive_hits=0`、`key_material_hits=0`；substring-only 命中全部是 schema 已公开的实体类型词表词（`item`/`store`/`document`/`record_collection`）、或同时出现在公开参照文档里的词，或更长公开 token 的子串；无题号/题面/答案/目标值/逐题 hash/key 材料命中（精确计数见 §12 复核脚本输出）。

## 10. 结论与对 C1-2 的预判（不签 GO）

**`PARTIAL_COVERAGE`。**

- **做成了**：`cross_entity` 16/30 轴有了可匹配的记录级实体目标（14 轴由冻结 refs + 公开语料结构确定性投影，2 轴修复 v1 目标缺陷）；`record_code` 投影规则可被复核方逐条重算（76/76 独立复算一致）；`shared_background` 7 轴中 6 轴完成语料级单元投影；语义零改动（6 字段 + `target_refs` + `basis` + 绑定 + 顺序全部逐值相等，唯一 1 处空键补全）；59 项保全与零调用。
- **没做成**：`stale_source` 的 `targets` 刻意为 0（加了也不被冻结判据消费，只会制造“看似可判”）；`shared_background` 消费侧条目仍为 0；3 轴只有不可匹配目标；2 轴被 addendum 披露永久阻断；4 轴正向 ref 非记录级；`cross_entity` 仍有 11 轴 `targets` 为空。
- **对“如果现在复跑”的诚实回答**：仅就合同侧，`cross_entity` 的可判轴数上界是 **16/30**（此前 1/30）；`stale_source` 仍会大面积 `unknown`，因为运行期 `record_code` 未采集（R-Q1A3R2-07）——**P1 单独无法把 stale 的 unknown 降下来**，必须等 C1-P3 的快照字段落盘，再由 C1-P4 消费 v2。此外还必须先决定 §8.2 的“文档级单元未投影”处置，否则 16 轴里的一部分可能从 `unknown` 变成 `violation`（不是产品失败，是转换假象）。
- 因此不建议以“合同已补”为理由直接签 GO 复跑；建议经理先看 §5/§6 的覆盖率与 §8.2 风险，再决定 C1-2 的收益口径。
- 本合同不证明 T207/Q1A 通过，不产生 release/threshold 结论，不进入阶段二。

## 11. 过程偏差

- 入口沿用既有 `load_private_bundle`（未新造解密/dump 工具）；`entity_from_filters` 的“角色名直写”识别是本次新增的规则（v1 目标的 `filters` 键用英文角色名而非语料字段名），已在 schema §4.2 明确定义。
- 首次试算把“空键补全”误当成“前缀不变”，已改为按 schema §6.4 的显式例外校验（聚合 `v1_target_objects_modified=1`）。
- 公开聚合最初把“可匹配”按“所有目标可匹配”统计，会低估可判性；已改为“存在一条可匹配目标”，并同时保留 `only_unmatchable_targets` 与 `invalid_target_axes` 两个口径。
- 密文路径按任务单字面落在 `D:\mktkb-q1a2-scope-contract\scope-targets-contract-v2.fernet`：该**目录**是 v1 已有的仓外目录（不是本轮新建），本轮只**独占创建**文件本身；v1 密文同目录共存、字节未变。

## 12. 复核脚本（仓外，非交付件）

生成与独立复核脚本都在仓外工作目录 `D:\mktkb-q1a2-scope-contract\work2\`（v1 的 `work\` 未被改动）：

| 脚本 | 作用 | 输出（仅计数/哈希，无明文） |
|---|---|---|
| `generate_v2.py` | 生成 v2 密文 + 公开聚合（含明文只在内存的断言、base/after 保护件快照、netguard） | `generate.out.txt` |
| `verify_v2.py` | **独立实现**重算：结构/绑定/lineage、6 字段与 `target_refs` 语义零改动、76 条记录身份、14 轴 `cross_entity` 目标、7 轴 `shared_background`、coverage 与聚合逐值相等、3 个公开件的隐私扫描、netguard 计数 | `verify.out.txt`（`all_pass=true`、`sensitive_hits=0`、`key_material_hits=0`） |
| `augment_aggregate.py` | 给公开聚合补 `status` / `quality_readiness` / `unverified` / `process_deviations` 四个非敏感字段（不改 coverage/bindings/哈希） | 无 |

复核方可以只读方式重跑 `verify_v2.py`：它不写任何文件、不打印任何逐题明文，只用既有 key 容器在进程内解密。

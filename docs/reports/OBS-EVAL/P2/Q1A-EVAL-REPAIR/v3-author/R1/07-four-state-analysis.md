# H2 v3 出题返工 R1：四状态与末轮实体（分析记录）

- 角色：v3 出题返工 R1（普通角色；非经理、非验收、非保管）。
- 基线：`codex/p2-e2e` / `97b0066726e5b8d6f94cbc0b63a890084550c106`；暂存 0；0 commit。
- 本文件**不含**题面、参考答案、目标值、逐题「题 → 记录」对应关系；只给计数、固定原因与证据指针。
- 证据：`01-selfcheck.json`（机检）、`02-offline-probe.json`（离线产品探针，脱敏）、`03-seal-r1.json`、`04-plaintext-purge-r1.json`、`05-netguard-positive-control-r1.json`、`06-preservation-r1.json`。

---

## 1. 裁定 A：四状态覆盖

| kind | R1 前 | R1 后 |
|---|---:|---:|
| `answer` | 27 | **25** |
| `refusal` | 3 | 3 |
| `not_found` | 0 | **2** |
| `conflict` | 0 | **0（阻塞）** |

### 1.1 `not_found`（2 题，C16/C17）

- **为什么是它们**：`negative` 层里这两题问的是「某店在`物品位置表`里的登记」，而 `物品位置表` 全部版本（D01/V03/V04/V05）只登记**城东店**与**城西店**两组行；C16 问城北店、C17 问滨河店，任何来源都没有对应登记行。它们本来就是**查无**，不是"有据的否定"。
- **不是硬改标签**：题面一字未改；改的是 `expected_kind`、`should_refuse`、`expected_*`/`relevant_units`（清空）与 `reference_answer`（改成"没有该登记行"）。私有 `authoring-record` 的 `evidence` 字段记录语料覆盖扫描（表内门店集合、目标门店行数 0）。
- **为什么必须 `should_refuse=true`**：`scorers._kind_checks` 里 `should_refuse=false` 且实际回 `not_found`（属拒答族）会触发 `refusal_unexpected` fail；`should_refuse=true` 时 value/source 检查按拒答跳过，`kind_correct` 仍要求实际 kind 恰为 `not_found`。
- **运行时可达性（离线探针实测）**：两题在 run 0 的语料上返回 `kind=not_found`、引用 **0** 条、无模型事件（候选为空 ⇒ 空使用集证明可成立，`cross_entity` 走 passed 而非 unknown）。探针在同一进程内还跑了两个"未知门店"对照，同样 `not_found`/0 引用。

### 1.2 `conflict`（0 题，阻塞）

**语料确实有互斥事实**：

- P01（城东店宣传海报）在 D01 v1（`A区3号货架第二层`）、D01 v2（`B区1号货架第二层`）、D01 v3（`D区暂存柜`）三个版本里位置不同；
- S01（城东店）电话在 D02 v1 与 V06 v2 两个版本里不同。

**但没有任何一对互斥来源同时"现行有效"，因此没有可过的 conflict 题**：

1. **产品按 `business_date` 过滤时（rag 路径）**：同一槽位版本窗口按 L1 S5 连续、互不重叠，任一日只有一版有效 ⇒ 互斥版本被过滤掉 ⇒ 只剩单值，产品不产出 `conflict`。
2. **产品不过滤时（legacy 路径，即单字段记录题的默认路径）**：`conflict` 会同时引用**已过期版本行**。冻结分类器 `_check_stale_source` 对每个 used unit 算 `effective_range`，`as_of > effective_to` 直接判 `source_expired` **violation（硬失败）**。离线探针在 4 个 run 日实测：P01 位置题**全部**返回 `conflict`，引用集合都含 V03（窗口 `[2026-01-05, 2026-04-30]`，在 4 个 run 日都已过期）。
3. 也就是说：**能产出 conflict 的配置一定硬失败，能通过的配置产不出 conflict**。给任何题硬写 `conflict` 都会 100% 失败，故按裁定要求**如实报告、不硬改**。

**最小语料调整建议**（详见计划 §13.2）：

- **方案 A（推荐，只改产品）**：让 legacy 记录证据面也按 `business_date` 过滤。改完后 run 1 仍有 1 个**可过**冲突（V01 临时通知无日期、恒有效 vs D01 v2 的 P01 行，两者互斥且都现行有效）；再把 V07 的内容改成对另一件跨版本同值物料给出不同位置，run 3 得到第 2 个可过冲突。改动面：1 个 PDF 内容 + 0 个窗口 + 0 个新源。
- **方案 B（只改语料）**：在现行版本里给某个**非 P01** 物料加一条同 `标识`、不同位置的重复行（两条行同属现行版本，不触发过期）；但旧版本同 `标识` 行仍会被 legacy 路径召回，仍需产品过滤，代价更大。
- 两方案都**不能新增第 13 个源**：`p2_holdout_scenarios.py` 的 `RECIPES` 与 `len(ingest.sources)==12` 已冻结。

### 1.3 逐题自洽核对（30/30）

- `questions.expected_kind == labels.expected_kind` 与 `should_refuse` 逐题一致：30/30。
- `answer`/`refusal`：`expected_sources` 与 `expected_values` 非空（`refusal` 按拒答跳过命中检查，但来源仍非空）。
- `not_found`：`should_refuse=true`、`refusal_reason=not_found`、`expected_values`/`expected_sources` 为空；私有 `evidence` 给出语料覆盖证明。
- 注释件（`targets.jsonl`）：30/30 有 id 型 target（共 36 条）；`not_found` 两题的 `stale_source.used_units=[]`，其余 28 题非空；`as_of` 与 `temporal_intent` 逐题与 `authoring_record` 一致。

---

## 2. 裁定 C：多轮只评末轮

- **结论：只把实体引用放进 `relevant_units` 不能判 `cross_entity`。** 冻结分类器的 `_used_unit_layers` 只认 4 类使用层：`model_input.evidence`、`direct_rag_answer.facts/cited_unit_ids`、`answer_result.source_ids`、`commit_observed.source_ids`；`relevant_units` 不参与。末轮若只引纯正文（无 entity_type/entity_key），`_check_cross_entity` 落到 `free_text_attribution_unverifiable` → **unknown**（不是 passed）。
- **处置**：C13（3 回合）把无日期对照（T5）移到**第 2 回合**、末轮改为引用现行登记行；C15（2 回合）把 T5 放到**第 1 回合**、末轮引用终端版本现存行。T5 覆盖计数仍为 2（C13-t2 / C15-t1）。
- **题面自然性取舍**：C13 的中间回合变成"政策追问"、C15 的首回合变成"登记表问题"，与相邻回合的业务语义仍连贯（同一业务角色的连续核对），但比"末轮补一句规范"略生硬。若坚持末轮纯正文，则必须接受该题 `cross_entity` 为 unknown；本轮的取舍是**优先可判**。

---

## 3. 裁定 B：`authoring-record` 不进仓

- 逐题出题记录已加密为封存件**第 6 件** `authoring-record.jsonl.fernet`（与 questions/labels/targets 同 root、同 key），仓内明文 `v3-author/authoring-record.jsonl` **已删除**。
- 仓内只留计数聚合 `docs/evaluation/p2-holdout-v3.authoring-aggregate.json`（题数、分层、轴姿态、kind、逐 run 题数/回合数；不含题号、题面、目标值、`business_date` 具体值）。
- 封存件读回逐字节相等（4/4），明文 SHA 与 manifest 逐值相等。

## 4. 裁定 D：`targets` 为第 5 件封存件

封存件固定顺序（与语料规格 §4/§6.3、dataset 文档一致）：

| # | 件 | 形态 |
|---:|---|---|
| 1 | `questions.jsonl.fernet` | 密文 |
| 2 | `labels.jsonl.fernet` | 密文 |
| 3 | `manifest.json` | 明文（repo-safe 元数据） |
| 4 | `source-map.json` | 明文（仓内有逐字节同件） |
| 5 | `targets.jsonl.fernet` | 密文（**第 5 件**） |
| 6 | `authoring-record.jsonl.fernet` | 密文（R1 新增） |

## 5. 机检（`01-selfcheck.json`）

| 检查 | 结果 |
|---|---|
| 30 题 / 36 回合 / 10-5-5-5-5 / run 12-8-5-5（回合 14-10-6-6） | 通过 |
| `expected_kind` | answer 25 / refusal 3 / not_found 2 / conflict 0 |
| 题面显式日期扫描 | 0（ISO、`YYYY年`、`M月D日`、相对日/星期词均为 0） |
| 题面评测词/固定码/轴名/分层名 | 0 |
| `record_code` / `entity_key` / 源代号泄漏 | 0 |
| questions ↔ labels ↔ authoring_record 一致性 | 0 mismatch |
| kind 自洽（`not_found` 空来源+should_refuse；answer/refusal 非空来源） | 30/30 |
| 加载器（封存件） | 30/30、36 回合、`metadata_mismatch_count=0` |

## 6. 残余（不隐瞒）

1. **`conflict` 仍为 0**（见 §1.2）：需要产品或语料二选一，属主人裁定范围。
2. **P01 版本碰撞（R1 新发现）**：四个 scenario 都上传 V03+D01(+V04/V05)，只有 P01 在版本间值不同；legacy 路径不过滤业务日 ⇒ 任何 P01 位置题都会变成 `conflict` 并引用过期行。受影响 `answer` 题 6 道（C01/C11/C21/C22/C25/C26）。建议：产品修过滤（首选）或把这 6 题的 target 迁到 P02–P08。
3. **单轮多目标与 planner 冲突（R1 新发现）**：探针实测"多物品单轮提问"被判 `clarification`；`multi_target` 的 6 题（C07/C12/C26/C28/C29/C30）在单回合内难以同时命中两条记录。需拆成两回合或改判 `clarification`。
4. **相似度回查未做**：需 v2 题面，本角色禁读（仍由保管在 S5 执行）。
5. **`p2_score_run.load_holdout_source_map` 只接受 source-map `/v0.1`**，v3 是 `/v0.2`（实现项，未改代码）。

# H2 v3 题库独立复核（保管 B）

主人，本轮对 **H2 v3 题库（30 题 / 36 回合 / labels / targets）** 做独立复核。只读 v3 题面、标签、anchors 与 v2 冻结题面（仅用于相似度回查）；未读产品回答、逐题 trace、产品输出；key 只在进程内存，未打印/复制/落盘；未写任何含题面/答案/目标值的临时明文。

**结论：FAIL（冻结阻断）。**
主因是 §6 的相似度回查在「复用 v2 语料」的加严门槛下不通过（字符级 max 0.649 > 0.5，超 0.5 的题 10 道 > 允许 3 道）；次因是 §4 的 2 道 `not_found` 题实际只走空使用集证明，与「30/30 题级行使日期子检查 / target 匹配」的声明不一致。若主人裁定相似度只以 3-gram Jaccard 为准，§6 可降为分歧，结论改为 **PASS_WITH_DISAGREEMENTS**；其余内容与冻结/接线阻断项仍见 §10。

- 复核时间（本地）：`2026-11-15T03:22:52+08:00`
- 基线：分支 `codex/p2-e2e`，HEAD `97b0066726e5b8d6f94cbc0b63a890084550c106`，暂存 0，172 commit，未新建 worktree/切分支。
- 角色：保管 B（独立复核）；不参与出题、标注、验收，不写 release/GO。

## 0. 对象与哈希（逐个复核）

| 件 | 字节 | SHA-256（前 8） | 结论 |
|---|---:|---|---|
| `v3/questions.jsonl.fernet` | 19980 | `2f55006c` | 与任务给定一致 |
| `v3/labels.jsonl.fernet` | 33080 | `5de0c125` | 一致 |
| `v3/targets.jsonl.fernet` | 45816 | `0cb9623c` | 一致 |
| `v3/authoring-record.jsonl.fernet` | 100088 | `7d52bb72` | 一致 |
| `v3/manifest.json` | 1066 | `54f9bb3e` | 一致 |
| `v3/source-map.json` | 2648 | `03665c48` | 一致 |
| L1 `docs/evaluation/p2-source-lifecycle-v1.json` | 35962 | `cc2ad0be` | 与 manifest/source-map 互钉一致 |
| 判据 v1.1 `p2-stale-source-criterion-v1_1.md` | 65883 | `0ec6c392` | 一致 |
| 语料 `fixtures/acceptance-h2v3/manifest.json` | 19435 | `1b3885a7` | 一致 |
| 设计规格 `2026-11-14-h2-v3-design-spec.md` | 55122 | `e179b583` | 与 L1 chain 的 `E179B583` 一致 |

- Fernet 解密回读 4/4 通过；questions/labels 明文 SHA 与 manifest 逐字相等（`d2aa0287…` / `82931a50…`），`metadata_mismatch_count = 0`。
- 仓库加载器 `p2_dataset.load_p2_dataset(..., visibility="holdout")` 在项目 `.venv` 下复跑通过：30 cases / 30 labels / 0 mismatch。
- 出题计划当前字节为 `ddbab338`（60364 B）；`authoring-inputs.json` 记录的读取 SHA 为 `ed5da038`（55448 B，R1/R3 前版本）。这是历史读取记录与当前计划的版本差，不是本次越界；复现时须注明版本。

## 1. 结构（逐项给结论）

| 项 | 要求 | 实测 | 结论 |
|---|---|---|---|
| 题数 | 30 | 30（questions/labels/targets/authoring 各 30 行，case_id 集合与行序四件全等） | PASS |
| 回合 | 36 | 36；直方图 `{1:25, 2:4, 3:1}`；multi_turn 的回合分配 `2/2/3/2/2`（11） | PASS |
| 分层 | 10/5/5/5/5 | 10/5/5/5/5 | PASS |
| 4 run 题数 | 12/8/5/5 | 12/8/5/5 | PASS |
| 4 run 回合 | 14/10/6/6 | 14/10/6/6 | PASS |
| 4 个 run 日期 | 互不相同、各 run 一个 | `2026-10-15 / 2026-07-15 / 2026-11-20 / 2026-12-15`；题面 `business_date` 与所属 run 逐题相等 30/30 | PASS |
| 四状态分布 | 见 §9 | `answer 25 / refusal 3 / not_found 2 / conflict 0` | PASS（但 conflict=0 是覆盖缺口，见 §9） |
| `should_refuse` | 与 kind 一致 | 25 false / 5 true；labels 与 questions 逐题一致 30/30；`refusal_reason`：null 25 / not_found 2 / must_refuse_security 3 | PASS |
| manifest | 严格 15 键 | 15 键；`case_count/strata/label_version/turn_stats` 复算全等；questions/labels 明文 SHA 全等 | PASS |
| 其他 | suite/split=holdout、requires_ocr=false | 30/30、30/30 | PASS |

## 2. 逐轴完备

姿态来源：`authoring-record.axes_required`（顺序按 `[cross_user, cross_entity, stale_source, safety]` 解读；C26–C30 全 required、其余题末位 not_applicable，语义与计划 §3 一致）。

| 轴 | 要求 | 实测 | 结论 |
|---|---|---|---|
| `cross_user` | 30 required | 30 required | PASS（仅姿态；targets 无 per-case cross_user 对象） |
| `cross_entity` | 30/30，id 型 3 键 + `record_code` + `version_number`，36 实例 | 30/30 required；24 单 + 6 双 = **36**；36/36 三元组恰为 `{entity_type, entity_key, filters}`；36/36 `entity_key` 形如 `item|id:`/`store|id:`；36/36 带 `record_code`/`version_number`/`locator{sheet,row}`；36/36 独立解析到唯一语料行且 **identity 全等**；0 记录碰撞；P05/P06 不作 target；P01 不出现在 V05 target | PASS |
| `stale_source` | 30/30，版本对/窗口与 L1 逐值一致 | 30/30 required；34 个 used unit（28 版本窗口 + 6 记录窗口）**34/34 窗口逐值与 L1 相等**、34/34 `covers_as_of=true`；`as_of == run business_date` 30/30；`interval=closed` 30/30；`temporal_intent=current` 30/30；端点题恰 2（C23 `to` / C24 `from`），其余最近端点最小 **4 天**（C29） | **28/30 真行使日期检查**；C16/C17 按 labels 与 `axis_rationale` 的零引用声明为空使用集，不产生日期检查（若产品实际引用 S03/S04 则恢复，但那与 labels 的 `expected_sources=[]` 不一致；见 §4/§9） |
| `safety` | 5 required / 25 N/A | required 5（`must_refuse_security` 3 + `forbidden_content` 2）/ N/A 25（全 `benign_business`）；`must_refuse_security` 3/3 对应 `should_refuse=true`；`forbidden_content` 2/2 为 answer | PASS |
| 4 个取代对 | 4/4 被行使 | D01 v1→v2（run0/1）、v2→v3（run2）、v3→v4（run3）、D02 v1→v2（run2/3）；按冻结 v2 契约 + plan 顺序重建的 27 个槽位检查 **position-active == window-active 27/27** | PASS（注：v3 自己的 contract/plan 不在仓内，见 §10） |

## 3. key 空间（独立解析，不复用出题方结论）

方法：用 `openpyxl` 直接读 `fixtures/acceptance-h2v3/**` 的可见工作表，按 `标识`/`门店`/`物品`/`店家` 表头复算 `entity_key = "{type}|id:{NFKC+空白折叠+casefold(标识)}"` 与 `filters`，再按 `(doc_code, version_number, record_code)` 与 36 个 target 逐条比对；不读任何出题方 keyspace 结论。

| 项 | 值 |
|---|---|
| target 实例 | 36（24 单 + 6 双：C07/C12/C26/C28/C29/C30） |
| 三元组恰 3 键 / id 型 | 36/36 / 36/36 |
| `record_code` / `version_number` / `locator` | 36/36 / 36/36 / 36/36 |
| 解析到唯一语料行 / identity 全等 / sheet,row 全等 | 36/36 / 36/36 / 36/36 |
| 记录身份唯一 / `record_code` 碰撞 | true / 0 |
| 被用作 target 的记录 | 10/12（P01–P04、P07、P08、S01–S04） |
| P05/P06 作 target | 0（只作 T2/T3 陷阱） |
| P01 出现在 V05 行 | false（V05 记录集 P02–P08） |
| V03/D01/V04 的 P01 值 | 三版本不同（与冲突事实一致；不在报告中列出值） |

**结论：key 空间同形可对齐，36/36。** 这是本包最强的一项。
**接线注意**：`targets.jsonl` 的 target 对象是「3 键身份 + 6 个 anchor 键」（`record_code/doc_code/source_code/version_number/locator`），而冻结 annotation 校验要求 target **恰 3 键**（`p2_hard_evidence.py:460`）、axis **恰 7 字段**（`:438-443`）。因此不能把 `targets.jsonl` 的 axis 对象原样当 annotation 提交；保管 A/实现方必须先投影为 7 字段 axis + 3 键 target，否则会在 annotation 加载期被拒（`annotation_targets_invalid` / `annotation_axis_invalid`）。这是**接线要求**，不是题库数据缺陷。

## 4. 标签自洽（逐项给结论）

| 检查 | 结果 |
|---|---|
| questions ↔ labels 的 `expected_kind` / `should_refuse` | 30/30 一致 |
| `answer` 题 `expected_sources` 非空 | 25/25 |
| `refusal` 题 `refusal_reason` | 3/3 `must_refuse_security`；均给出禁源/禁值依据 |
| `not_found` 题零引用 | 2/2（`expected_sources=0`、`relevant_units=0`、`refusal_reason=not_found`） |
| `not_found` 真无覆盖 | C16 问物品位置表中不存在的门店行、C17 问同一表中不存在的门店/物品行；D01 只有两个门店的 8 行，确无覆盖 → 结论成立 |
| `expected_values` 可落地 | 45/45 出现在 `reference_answer`，且 45/45 出现在所引 source 行的单元格中 |
| `forbidden_values` 真实性 | 12/12 可在语料中定位；0 个出现在 `reference_answer`；禁值均为真实诱饵/陷阱值 |
| `expected_sources` 版本重映射 | 42/42 条引用按 source map 重映射到 `(base_doc_code, version_number, record_code)` 后存在 |
| `forbidden_sources` | 8 条引用，均为该 run 未上传的禁源或同版本陷阱源；与 `forbidden_not_ingested` 一致 |
| 安全拒答依据 | C26/C28/C30 的请求分别涉及全部门店电话整表、合同+结算账号、内部结算价目表；禁源在对应 run 未上传 → 拒答有据 |

**发现（标签/anchors 不一致）**：C16/C17 的 labels 是 `not_found` + 零引用，但私有 `authoring-record.lifecycle_rows` 把 S03/S04 标为 `role="correct_path"`，`scenario_card.entity_scope` 也写 `store|id:s03/s04`；`axis_rationale` 同时写「空使用集证明判 passed」「不产生日期子检查」，而 `why_this_axis` 仍写着「有据的否定：结论必须由现存记录支撑」（这段文字与 C18–C20 的“有据否定”设计同源，未随 R1 改判更新）。这三点互相矛盾：**若正确路径零引用，则 target 不会被匹配、stale 不会真检查；若正确路径引 S03/S04，则 labels 的 `expected_sources` 应为非空。** 结论：C16/C17 的标签与 anchors 没有描述同一条正确路径；它们可以靠空集证明判过，但不能计入「cross_entity target 匹配 30/30 / stale 日期检查 30/30」。实际可判面为 **cross_entity 28/30 target 匹配（+2 空集）+ stale 28/30 日期检查（+2 空集）**。

## 5. 泄漏扫描

**题面（question + turns）**，30 题全文：

| 模式 | 命中 |
|---|---:|
| `YYYY-MM-DD` / `YYYY年M月D日` / `M月D日` / `20YY年` | 0 |
| 评测词/固定码（T207/T208/Q1A/rescore/unknown/pass/fail/not_applicable/violation/_missing/_unresolved/entity_scope_conflict/holdout） | 0 |
| 轴名/判据名（cross_user/cross_entity/stale_source/must_refuse_security/forbidden_content/benign_business） | 0 |
| `record_code`（P01–P08/S01–S04 形态） | 0 |
| `entity_key`（`|id:`） | 0 |
| 源代号（D01–D09/V01–V09 形态） | 0 |
| 分层名 / `P2-HOLDOUT` / `H2V3` | 0 |
| 「今天/现在/当前/目前/本月/…」 | 11 题含「现在」；`_as_of` 将其解析为 `business_date`（`rag/query.py` 的 `_as_of`），不是显式日期；R-RUN-1 允许，**不判泄漏** |

**公开/仓内件**（dataset 文档、plan、fixtures manifest、L1、判据、authoring-report/evidence、R1 报告、authoring aggregate）：

- 题面正文 / 参考答案正文：**0 条精确命中**；8 字归一化窗口只命中实体短语（门店+物品组合），不是题面泄漏。
- 目标值：`R1/07-four-state-analysis.md` **8 条**精确命中；旧 `eval_data_v0_1.md` **8 条**、旧 plan **8 条**；`fixtures/acceptance-h2v3/manifest.json` 另有 33 条（语料清单本身）。这些值都是**公开语料事实**（fixtures 与旧文档已有），不是新题面/答案文本；但若冻结规则字面要求「任何仓内件不得出现目标值」，则作者「112 needles exact 0」的说法对其自己的 R1 报告不成立（8 条）。严重度：低；建议在 freeze 清单中明确「语料事实值例外」或清理 R1 报告中的值。
- 未发现题面/参考答案/逐题「题→值」映射进入公开件。

## 6. 与 v2 相似度回查（出题方本轮禁做，由保管 B 执行）

方法：v3 每题文本（question；多轮为 turns）与 v2 的 30 题逐题比对；归一化 = NFKC + 去空白/标点 + casefold；每题取对 v2 的**最大**值。指标并列：字符级 SequenceMatcher、归一化 Levenshtein 相似度、字符 3-gram Jaccard、3-gram containment、2-gram Jaccard。只回聚合，不写题面。

| 指标 | min | median | max | >0.5 题数 | ≥0.6 题数 |
|---|---:|---:|---:|---:|---:|
| 字符级 SequenceMatcher | 0.2692 | 0.4394 | **0.6486** | **10** | 4 |
| 归一化 Levenshtein | 0.2000 | 0.3186 | **0.5882** | **4** | 0 |
| 3-gram Jaccard | 0.0417 | 0.1528 | 0.3500 | 0 | 0 |
| 3-gram containment | 0.1000 | 0.3787 | 0.6667 | 7 | 1 |
| 2-gram Jaccard | 0.1111 | 0.2090 | 0.4000 | 0 | 0 |

**阈值裁定**：v3 复用 v2 语料，按设计规格 §6.2 #4 / 语料规格 §6，门槛**加严为 `max < 0.5` 且 `count_over_0.5 <= 3`**。按字符级指标（SequenceMatcher 或 Levenshtein）**均不通过**：max 0.649 / 0.588 均 > 0.5；超 0.5 题数 10 / 4 均 > 3。只有 3-gram Jaccard 通过（max 0.35、0 题 >0.5）。规格同时要求「字符级相似度与 3-gram Jaccard」，故不能宣布门槛已满足。

超 0.5 的 10 题（按字符级 max）：C01、C02、C04、C05、C07、C08、C21、C24、C25、C29。最相近的 4 对：

| v3 题 | v2 题 | 字符级 | 3-gram Jaccard |
|---|---|---:|---:|
| C01 | h2-par-01 | 0.6486 | 0.3200 |
| C05 | h2-neg-02 | 0.6452 | 0.3500 |
| C04 | h2-par-10 | 0.6400 | 0.2917 |
| C02 | h2-par-02 | 0.6000 | 0.1500 |

这 4 对是**同一句式模板 + 实体替换**（同店/同物/近义问法），不是共享实体名导致的偶发重合；C01 与 v2 对应题只差少量措辞。结论：**反照抄门槛未过，构成冻结阻断**。

> 注：`p2-holdout-v3.authoring-aggregate.json` 的 `similarity.status="not_computed"` 与计划 §10.3 #6 要求的「语料复用声明」均未落；本复核结果需由保管/作者回填到聚合（不得回填具体题面）。

## 7. 反照抄（authoring-record 是否来自场景卡/语料，而非 T207 结果）

| 检查 | 结果 |
|---|---|
| `authoring-inputs.json` 读取路径 | 41 条；全部在声明白名单内；唯一 T207 路径是 `T207/PM/T207-ingest-plan-H2.json`（12 条上传序 + path/name/document_ref，无逐题/结果内容），已显式登记为例外 | 
| v2 私有题面/标签、`.env`、runbook、v2 key | 0 条读取 |
| rescore / partial-audit / manager-receipt / manager-acceptance / review-aggregate / independent-review / dev-report / old-card / failure-list / triage | 0 条读取 |
| authoring-record 的 `evidence_ref` | 全部 `authoring-inputs.json#/read` |
| `plan_ref` | 全部指向 `2026-11-15-h2-v3-authoring-plan.md §5 Cxx`（场景卡骨架），无 T207 结果引用 |
| scenario card | 30 个唯一 `scenario_card_id`；字段为 business_role/task/expected_output_shape/stratum/turn_count/scenario_id/corpus_slots/time_semantics/entity_scope；无 T207/Q1A/rescore/失败清单/分诊/旧卡 token |
| `review_status` / `disagreement_code` | 30/30 `pending_independent_review` / null |
| 语义 | 题面与 anchors 都能从场景卡 + 语料 + L1 推出；未发现「照着 11 fail/27 unknown/旧卡」出题的痕迹 |

**结论：反照抄干净。** 两个低severity 的过程偏差：(a) `axis_rationale` 使用了判定词「passed」，`scenario_card.entity_scope` 含 `item|id:`/`store|id:` 固定码；它们只在私有加密的 authoring-record 内，未入题面，但违反 S0「卡片不得出现评测词/固定码」的字面规则。(b) plan 的 SHA 从 `ed5da038` 漂到 `ddbab338`（R1/R3 增补），属历史版本差，不是越界，但复现须注明。

## 8. 保全与零真实调用

| 项 | 结果 |
|---|---|
| 分支 / HEAD | `codex/p2-e2e` / `97b00667…`（复核前后一致） |
| 暂存 / commit / push | 0 / 0 / 未；未新建 worktree、未切分支 |
| 15 tracked modified | 路径集合 15/15 与 `axes/evidence/04-protected-hashes-before.json` 逐条一致；逐文件 SHA 复核前后不变 |
| C 冻结 12 | 12/12 与基线逐项相等（含 `p2_hard_evidence.py`、`retrieval/index.py`、`rag/chunking.py`） |
| v2 语料 `fixtures/acceptance/**` | 35 个文件 SHA 前后不变 |
| v2 密文 | manifest `8874985e…`、questions `36d29ba5…`、labels `d51478fd…` 前后不变 |
| v3 密文/公开件 | 6 件 SHA 前后不变（见 §0） |
| 既有 untracked | 复核前 2458 条；复核后 2464 条 = 2458 + 本报告 2 件 + **另一角色并发新增 4 个未跟踪 backend 文件**（`p2_holdout_scenarios_v3.py`、`p2_holdout_source_map.py`、`p2_holdout_run_date.py`、`test_p2_v3_wiring.py`，mtime 03:14–03:23；非本轮产物，我未改未读）；其余逐条 SHA 不变（含 `v3-author/pre-registration.{md,json}`，同样非本轮产物） |
| 零真实调用 | 未调用产品/模型/embedding/rerank/OCR/裁判/检索/鉴权/余额；未启服务；未建 GO；只做本地读、哈希、openpyxl、内存解密与本地 Python 复算 |
| **零出站（独立确认）** | 全部分析进程在自建 netguard（拦 `connect`/`connect_ex`/`create_connection`/`getaddrinfo`/`http.client.connect`）下运行；正对照 **5/5 被拦**（含 `example.com:80/443`、本机代理跳点 `127.0.0.1:7897`、`urllib`），成功出站 **0**；netguard 日志 `real_connects=0`。本包前序的 1 次 example.com 探针出站不是本会话；本会话所有 example.com 尝试都只发生在正对照里，且在 connect 前被拦 |

> 历史漏出路径说明：前序 1 次 example.com 探针是**借道本机代理 `127.0.0.1:7897`**（并发新增的 `test_p2_v3_wiring.py` 头注亦如此记录）；本轮 guard 连**回环**与 `http.client.connect` 一并拦截，正对照显式覆盖该代理跳点，因此不会重演。

## 9. 四状态覆盖与可判性判断（必给）

### 9.1 计数

| 状态 | 题数 | 占比 | 可判性 |
|---|---:|---:|---|
| `answer` | 25 | 83.3% | 有据作答；expected_values 45/45 可落地；其中 3 道为“有据的否定”（C18–C20） |
| `refusal` | 3 | 10.0% | 有据拒答；禁源在 run 内未上传；但 C26/C28/C30 的「一题多请求」有 planner 澄清风险（见 9.3） |
| `not_found` | 2 | 6.7% | 可判，但只走空集证明；不测试 target 匹配/日期检查 |
| `conflict` | 0 | 0% | 未覆盖 |

### 9.2 `conflict = 0` 是否可接受

**作为标签选择可接受；作为覆盖不可接受。** 语料确有互斥事实（P01 在 V03/D01/V04 三个位置；S01 电话在 D02/V06 两个值），但四个 run 的 `business_date` 下，同一槽位只有一个版本窗口覆盖（L1 连续、闭区间），日期过滤后只剩单值；若走不过滤的 legacy 路径，`conflict` 会引用已过期版本行，被冻结分类器判 `source_expired` 硬失败。因此「任一 conflict 标签都会 100% 硬失败」的结构性理由成立，作者不硬改标签是对的。但这也意味着 **conflict 状态在 v3 中完全未测**。

### 9.3 缺哪个状态会削弱 T207 结论 / 是否建议补题

- **缺 `conflict`（0）**：任何关于「产品能否识别/呈现来源冲突」的 T207 结论都没有证据；这是最大的语义缺口。
- **`not_found`（2）只看空集**：C16/C17 的 cross_entity 靠 strict empty proof、stale 靠「无 dated unit 自动 pass」，与 v2 的「无日期自动 pass」机制同型；它们不证明实体目标或日期窗口可判。若 T207 需要「not_found 也不误引实体/不误用过期源」，这 2 题给不出证据。
- **`refusal`（3）有 planner 澄清风险**：C20/C21/C22 是 stale_conflict 题，单回合里问了**两个物品**；`rag/query.py:1495-1512` 在 `len(item_hits) > 1` 时直接返回 `ITEM_AMBIGUOUS`（不检索）。若产品先澄清，`expected_kind=answer` 会失败，stale 陷阱也测不到。C26/C28/C30 是一 item + 一敏感请求，风险较低但仍需实测。作者 residual #16 只列了 6 道 `multi_target`，**漏计 C20/C21/C22** 这 3 道 stale 题。
- **`answer` 占 25/30**：题库重心是 answer 正确性；四状态行为（尤其 conflict）覆盖不足。

**补题建议（不原地改 v3；走 v3.1 新 dataset_version/label_version/新密文）**：
1. 至少 2 道 `conflict`：方案 B（同版本内加一条同 `标识`、不同值的重复行，避免 `source_expired`）或方案 A（产品 legacy 路径也按 `business_date` 过滤，再用 V01/V07 两份互斥通知构造可过冲突）。不要新增第 13 个源（会撞 `len(ingest.sources)==12` 冻结）。
2. 修 C16/C17：二选一——(a) 让正确路径引用 S03/S04 作为否定证据并把 `expected_sources` 填为非空；或 (b) 把 `cross_entity`/`stale_source` 显式改为可解释的 N/A（空集证明），并在公开聚合里把「30/30 target/date」改成 28/30+2 空集。当前“labels 零引用 + anchors correct_path + why_this_axis 说有据否定”三者必须统一。
3. 把 C20/C21/C22 拆成两回合或改成单物品问法，避开 `ITEM_AMBIGUOUS`。
4. 对 §6 超阈值的 10 题（尤其 C01/C02/C04/C05）重写问法；重跑相似度到 `max < 0.5` 且 `count_over_0.5 <= 3`。
5. 公开聚合补「语料复用声明」+ 相似度实际分桶（不回填题面）。

## 10. 阻断项与建议（按优先级）

**内容/冻结阻断（必须先处理）**
1. **相似度门槛未过**（§6）：字符级 max 0.649/0.588 > 0.5，超 0.5 题 10/4 > 3；4 对为模板级复用。→ 重写 10 题后重跑。
2. **C16/C17 标签与 anchors 不一致**（§4）：labels 零引用 vs anchors `correct_path` + `why_this_axis` 有据否定；实际 cross_entity/stale 为 28/30+2 空集，不是 30/30。→ 统一标签或改锚点。
3. **C20/C21/C22 多物品澄清风险**（§9.3）：`ITEM_AMBIGUOUS` 会使 answer/stale 不可判。→ 拆回合或改单物品。

**接线/冻结前置（实现或保管动作，不属题库内容）**
4. v3 自己的 scenario contract 与 ingest plan 不在仓内（作者 residual #11）。本复核只能用冻结 v2 契约 + plan 顺序重建 27 槽位；冻结前必须把 v3 的 contract/plan 落盘并做 SHA 绑定。
5. `p2_score_run.load_holdout_source_map` 只接受 `p2-holdout-source-map/v0.1`（`p2_score_run.py:499`），v3 是 `/v0.2`；不补版本分发则 v3 无法计分。作者 residual #4 已披露，本复核确认。
6. `targets.jsonl` 的 axis 对象不是可直接提交的 v0.2 annotation（axis 7 字段 / target 恰 3 键，`p2_hard_evidence.py:438-443,460`）；annotation builder 必须投影，否则加载期拒绝。
7. L1 `corpus_manifest_sha256` 仍为 null（语料已生成，source map 已绑 `1b3885a7`）；`label_version_placeholder` 仍是模板值。冻结前应补 L1 的 corpus manifest 绑定，或明确该字段由 source map 承担并在 freeze 清单说明。
8. 公开聚合缺「语料复用声明」与相似度结果（§6 注）；`similarity.status` 仍是 `not_computed`。
9. `R1/07-four-state-analysis.md` 含 8 条目标值字符串（语料事实，非题面/答案正文）；若 freeze 规则字面禁止，需清理或在清单登记例外。

**复核期间并发新增（非本轮产物，未验证）**：另一角色在本复核对 03:14–03:23 新增了 4 个未跟踪文件 `backend/src/mktkb/evaluation/p2_holdout_scenarios_v3.py`、`p2_holdout_source_map.py`、`p2_holdout_run_date.py`、`backend/tests/evaluation/test_p2_v3_wiring.py`；它们看起来正是补 §10 #4/#5 与 per-run `business_date` 接线。但它们**未跟踪、未提交、未被本复核验证**，不能据此关闭 #4/#5；若主人要采用，需另走独立验收与冻结。

## 附录 A：复算方法与证据

- 解密/加载：Fernet（key 只在进程内存）；`p2_dataset.load_p2_dataset`（项目 `.venv`）；`openpyxl` 直读 12 个语料文件；`cryptography` + Python 标准库。
- 结构/分层/回合：独立复算，不读作者结论；`turn_histogram` 复算公式 `len(turns) if turns else 1`（与 `p2_dataset.py:715` 一致）。
- key 空间：按 `retrieval/index.py:110-137` 的 `analyze_fields` 口径手写复算（`normalize_value` = NFKC+空白折叠+casefold，`retrieval/tokenize.py:62-66`）。
- 生命周期：按 L1 `sources[]`/`records[]` 逐值比对；闭区间 `[from, to]`，null 侧跳过；端点距离按日历日差复算。
- 相似度：见 §6 方法；原始逐题数值保存在复核进程内存/临时聚合（不含题面），报告只给分布与题号。
- 零调用：netguard 正对照 5/5 被拦、`real_connects=0`；每个分析进程都先装 guard 再导入第三方库。

## 附录 B：与上一轮报告的分歧（保留不表决）

1. 上一轮 §3 的「stale 30/30」「题级行使日期子检查 30/30」：本复核为 **28/30 + 2 空集**（C16/C17）。依据：labels 零引用 + `axis_rationale` 自述「不产生日期子检查」。
2. 上一轮 §5 的「112 needles exact 0」：本复核对 `R1/07-four-state-analysis.md` 找到 8 条**目标值**精确命中（均为语料事实）；题面/参考答案正文仍为 0。建议把该结论限定为「题面/参考答案 0」。
3. 上一轮 §6 的「相似度回查未做」：本复核已做，结论见 §6；门槛未过。
4. 上一轮 residual #16 的 multi_target 清单：本复核新增 C20/C21/C22 三道 stale 题的单回合多物品澄清风险。

---

**最终结论：FAIL（冻结阻断）**。若主人裁定相似度只以 3-gram Jaccard 为准，则 §6 降为分歧，结论改为 **PASS_WITH_DISAGREEMENTS**；此时仍需处理 C16/C17（内容）与 §10 第 4–8 项（接线/冻结前置）。

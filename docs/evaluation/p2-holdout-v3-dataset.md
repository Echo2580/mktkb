# P2 holdout v3.1 数据集（结构与校验说明，公开件）

- 状态：**v3.1 返工版**（v3 独立复核 FAIL 后的三项必修已处理）；不是题面、不是标签、不是判定结果、不是 GO。本文件**不含**任何题面文本、参考答案、目标值，也不含「题 → 记录」的逐题对应关系。
- 角色：H2 v3.1 出题返工作者（普通角色；非验收、非经理、非保管）。
- 基线：分支 `codex/p2-e2e`，HEAD `97b0066726e5b8d6f94cbc0b63a890084550c106`，暂存区 0，0 commit，未新建 worktree、未切分支。
- 上游依据：`docs/superpowers/plans/2026-11-15-h2-v3-authoring-plan.md`（当前字节 `DDBAB338…`，60364 B；复核记录的读取版本为 `ED5DA038…`，属历史版本差）、`docs/superpowers/plans/2026-11-15-h2-v3-corpus-modification-spec.md`（`6D64EE79…`）、`docs/evaluation/p2-source-lifecycle-v1.json`（`CC2AD0BE…`，窗口唯一真相源，下称 **L1**）、`docs/evaluation/p2-stale-source-criterion-v1_1.md`（`0EC6C392…`）、`fixtures/acceptance-h2v3/manifest.json`（`1B3885A7…`）、`docs/evaluation/p2-holdout-v3.source-map.json`（`03665C48…`）。
- 交付报告与计数聚合：`docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/v3-author/`（`authoring-report.md` / `authoring-inputs.json` / `evidence/` / `R2/`）与 `docs/evaluation/p2-holdout-v3.authoring-aggregate.json`。**题面、答案与逐题出题记录（`authoring-record`）都不在仓库内任何位置**，只在封存 root 的 Fernet 密文里（R1 起 `authoring-record` 也已移入封存；v3.1 重新加密）。

---

## 1. 身份

| 项 | 取值 |
|---|---|
| `dataset_version` | `P2-HOLDOUT-v3.1` |
| `label_version` | `p2-holdout-v3.1-2026-11-15` |
| holdout manifest schema | `p2-holdout-manifest/v0.1`（严格 15 字段，**未升版**） |
| questions 行 schema | dataset.py holdout **13 键** |
| labels 行 schema | dataset.py holdout **11 键** |
| source map schema | `p2-holdout-source-map/v0.2`（12 码全声明 + `lifecycle_ref` + `corpus_ref`） |
| 语料根 | `fixtures/acceptance-h2v3/`（12 个被 ingest 源 + `manifest.json`；v3.1 **未改语料**） |
| 生命周期 | `docs/evaluation/p2-source-lifecycle-v1.json`（`interval=closed`，`declaration.kind=design_fixture`） |

## 2. 规模与分组（与 v3 相同）

| 项 | 取值 |
|---|---:|
| case | **30** |
| 回合 | **36**（`1:25 / 2:4 / 3:1`；multi_turn 5 题共 11 回合，按 `2/2/3/2/2`） |
| 分层 | **10 / 5 / 5 / 5 / 5**（`paraphrase` / `multi_turn` / `negative` / `stale_conflict` / `cross_doc_security`） |
| run | **4**（`run_index 0..3`，与 4 个 scenario 一一对应） |

| run | scenario | `business_date`（唯一取值来源 = L1） | 题数 | 回合 |
|---:|---|---|---:|---:|
| 0 | `base_b0` | `2026-10-15` | 12 | 14 |
| 1 | `base_b0_plus_v01` | `2026-07-15` | 8 | 10 |
| 2 | `pre_v05_without_v07` | `2026-11-20` | 5 | 6 |
| 3 | `post_v05_without_v01` | `2026-12-15` | 5 | 6 |
| Σ | 4 | — | **30** | **36** |

- 每题 `questions.business_date` = 该题所属 run 的 `business_date`；同一 run 内逐字相同，跨 run 不比较。v3.1 未改任何题号、run、分层、回合数或 `business_date`。
- holdout manifest 的 `business_date` 仍为 `2026-10-28`，语义是**数据集默认/设计自检日**（L1 的 `business_date_anchor`），**不是**任何 run 的实际日期；run 日期从 cases 聚合（`p2_runner.py:2376-2383`）。

## 3. 行字段与四状态

`questions.jsonl`（13 键，**无答案字段**）：`case_id`、`suite=holdout`、`split=holdout`、`stratum`、`business_date`、`question`、`turns`、`expected_kind`、`should_refuse`、`requires_ocr`、`labeler`、`label_version`、`notes`。多轮题的题干在 `turns[]`，`question` 为空串；单轮题 `turns=[]` 且 `question` 非空。

`labels.jsonl`（11 键）：`case_id`、`expected_kind`、`expected_values`、`expected_sources`、`relevant_units`、`reference_answer`、`should_refuse`、`refusal_reason`、`forbidden_values`、`forbidden_sources`、`notes`。

- `expected_kind` 分布（v3.1 不变）：`answer` 25 / `refusal` 3 / **`not_found` 2** / **`conflict` 0**。5 条 `should_refuse=true`（3 条安全拒答 + 2 条查无）均带 `refusal_reason`。
- `expected_sources` **28/30 非空**：有据作答与安全拒答题一律非空引用；2 条 `not_found` 题问的事实**任何来源都没有覆盖**（`物品位置表` 只登记城东店/城西店），正确路径零引用，靠冻结分类器的空使用集证明判 passed。
- **v3.1 起不再把 `not_found` 计入 target/日期匹配**：可判面为 `cross_entity` **28/30 target 匹配 + 2 空集**、`stale_source` **28/30 日期检查 + 2 空集**。`targets.jsonl` 里这两题仍保留“问题所问门店”的实体锚点，但 `authoring-record.lifecycle_rows` 已清空（`correct_path=[]`），`why_this_axis` 明写“语料无覆盖”，与 `expected_kind=not_found`、零引用 `reference_answer` 四处一致。**不得再把它们算作 30/30。**
- **`conflict` 为 0 是阻塞项，不是遗漏**：语料确有互斥事实（P01 三版位置、S01 两版电话），但没有一对互斥来源同时现行有效；产品过滤业务日时互斥版本被滤掉，不过滤时会引用过期版本行并被冻结分类器判 `source_expired` 硬失败。见 `v3-author/R1/07-four-state-analysis.md` §1.2。
- 引用形状：表行 = `{doc_code, record_code, locator{sheet, row}}`；纯正文 = `{doc_code}`。`locator` 只使用冻结键集，**不写** `version_number`——版本由 `doc_code` 承载，H2 计分侧在内存 `remap_holdout_case` 里折回基槽并合并 `version_number`（`p2_score_run.py:523-543`）。

## 4. 实体 target 与生命周期锚点（内容不变）

逐题锚点在私有件 `targets.jsonl`（封存为 `targets.jsonl.fernet`）与 `authoring-record.jsonl` 内，形状：

```text
target = {entity_type, entity_key, filters}            # 轴注解的恰 3 键
       + {record_code, doc_code, source_code, version_number, locator{sheet,row}}   # 私有锚点
```

- `entity_key = "{entity_type}|id:{normalize_value(标识)}"`，`normalize_value` 与 `retrieval/tokenize.py:54-66` 逐字同口径（NFKC → 空白折叠 → `casefold`）；`filters` 保运行期原值（`retrieval/index.py:110-137`）。
- 两条 target 来源表：`物品位置`（`D01`，记录 `P01–P08`）与 `店家信息`（`D02`，记录 `S01–S04`）。`备用物料表`（无 `标识` 列）与 `旧草稿`（标记「不得入库」）**不作** target。
- target 实例 **36**（24 单 + 6 双：C07/C12/C26/C28/C29/C30），36/36 三元组恰 3 键、36/36 带 `record_code`/`version_number`/`locator`；v3.1 **逐字节未改** `targets.jsonl` 明文（明文 SHA `4cda7e09…`，与 v3 相同）。
- 版本对/窗口：4 条被取代对（`D01` v1→v2、v2→v3、v3→v4；`D02` v1→v2）全部被行使；记录级窗口行 4 条（`P02`/`P05`/`P06`/`P08`，均 `D01` v2）。`P05`/`P06` 只作陷阱，不作 target。
- 同日边界断言恰 2 条，均落在**记录级**窗口（一条 `effective_to`、一条 `effective_from`，闭区间下均有效）；其余 28 题离其所引窗口端点 ≥3 天（实测最小 4 天）。
- v3.1 只改题面措辞与 C16/C17 私有锚点；**未改** targets、版本对、窗口、run 归属或判定目标。

## 5. 封存布局与逐件摘要（v3.1 新密文）

封存件固定 6 件：

```text
D:\mktkb-p2-holdout\
├── keys\v3.key                     # 本地生成，44 字节 Fernet key；未打印、未复制、未入库
└── v3\
    ├── questions.jsonl.fernet       # ①
    ├── labels.jsonl.fernet          # ②
    ├── manifest.json                # ③ 明文元数据（严格 15 字段）
    ├── source-map.json              # ④ 明文，与仓内件逐字节相同
    ├── targets.jsonl.fernet         # ⑤ 实体/生命周期锚点
    └── authoring-record.jsonl.fernet# ⑥ 逐题出题记录
```

| 文件 | 字节 | SHA-256 |
|---|---:|---|
| `questions.jsonl.fernet` | 20708 | `26c637cc1f5045150e7060673703f6eb57e2b95e7f8d127893f477261649f2a0` |
| `labels.jsonl.fernet` | 33080 | `4503701b7c96a6d2a4212e3c32a0ac591311d76ed76dab003a8041e4b43b332f` |
| `targets.jsonl.fernet` | 45816 | `70fc58620a36a00ba02635c6a9517d64e24ba55bee5061ba6d506e86df148e2b` |
| `authoring-record.jsonl.fernet` | 100172 | `009131579409a92dca0e2b2989467793f3e3f30e96162d9387c36ce9b433695f` |
| `manifest.json` | 1039 | `de4125ca9c1d1f68baa30209a12047f1f7753d25a4aa6e8a0d33815dc6b536e8` |
| `source-map.json` | 2648 | `03665c48c0716e45e0a6313c6f1823e6714c996d85254f01283fc0ef5ed2e8b8`（未变） |

- 加密后逐件**读回**（Fernet 解密 → 与明文逐字节比较 → 明文/密文 SHA 与 manifest 逐值相等）：**4/4 `verified`**。
- 明文工作目录 `D:\mktkb-h2v3-authoring\plain\` 在加密并校验读回成功后**已删除**（R2 清单与逐件 SHA 见 `v3-author/R2/06-plaintext-purge.json`；R1 清单见 `v3-author/R1/04-plaintext-purge-r1.json`）。
- 被取代的 v3 旧密文已复制到仓外 `D:\mktkb-h2v3-authoring\superseded-v3\` 备查；`D:\mktkb-p2-holdout\v3\` 只保留 v3.1 六件。
- key 只经 `MKTKB_P2_HOLDOUT_KEY_FILE` 注入评测进程；本仓库与任何报告均不含 key 内容。

## 6. 校验（仓库自己的加载器）

`mktkb.evaluation.p2_dataset.load_p2_dataset(manifest_path, visibility="holdout")` 在 v3.1 封存件上通过，读数：

| 项 | 值 |
|---|---|
| `case_count` / `labels_count` | 30 / 30 |
| `strata` | 10 / 5 / 5 / 5 / 5 |
| `turn_stats` 复算 | `total_turns=36`、`max_turns_per_case=3`、`histogram {1:25,2:4,3:1}` |
| `metadata_mismatch_count` | 0（questions 与 labels 的 `expected_kind`/`should_refuse` 逐题一致） |
| `label_version` | 全行唯一且等于 manifest（`p2-holdout-v3.1-2026-11-15`） |
| `dataset_version` | `P2-HOLDOUT-v3.1` |
| `expected_kind` 复算 | `answer 25` / `refusal 3` / `not_found 2` / `conflict 0` |
| 引用版本锚点（`remap_holdout_case` 内存合并后） | 30/30 题带正确 `version_number`，无未映射代号 |

证据：`v3-author/R2/04-post-seal-verify.json`、`v3-author/R2/02-consistency.json`。

## 7. 相似度回查（v3.1 返工的核心）

方法：v3.1 每题文本（`question`；多轮为 `turns` 拼接）与 **v2 冻结的 30 题**逐题比对；归一化 = NFKC + 去空白/标点 + casefold；每题取对 v2 的**最大**值。指标并列：字符级 `SequenceMatcher`、归一化 Levenshtein 相似度、字符 3-gram Jaccard、3-gram containment、2-gram Jaccard。只回聚合，不写题面。

| 指标 | min | median | max | >0.5 题数 | ≥0.6 题数 |
|---|---:|---:|---:|---:|---:|
| 字符级 SequenceMatcher | 0.2545 | 0.3711 | **0.4444** | **0** | 0 |
| 归一化 Levenshtein | 0.1667 | 0.2709 | **0.3500** | **0** | 0 |
| 3-gram Jaccard | 0.0278 | 0.0990 | **0.1951** | **0** | 0 |
| 3-gram containment | 0.1000 | 0.3063 | 0.6667 | 3 | 1 |
| 2-gram Jaccard | 0.0541 | 0.1482 | 0.2500 | 0 | 0 |

- `containment3` 只作并列观测，**不是门槛**：它是非对称指标，v2 的短题可被 v3 长题完全包含而显得高；本轮门槛按设计规格/复核裁定只看字符级（`char_seq`/`char_lev`）与 `jaccard3`。

- 冻结前门槛（v3 复用 v2 语料加严）：`max < 0.5` 且 `count_over_0.5 <= 3`。v3.1 三项主指标全部满足，字符级 max 0.4444 也低于余量目标 0.45；**0 题 > 0.5**。
- 改写范围：复核列出的 **10 道超阈题**全部重写措辞（题号、run、分层、判定目标、四轴依赖、targets/版本对均不变）；另对 3 道边界题（C27 字符级恰 0.5000、C28 0.4667、C15 0.4651）与 2 道多物品题（C20/C22，见 §8）做了同义改写，使 max 进入 0.45 以内。全部 30 题重跑，不是只跑改动题。
- 未发现“无法在不改题意下降阈”的题；无题需要保留超阈并说明理由。
- 反照抄：v2 题面只在本轮**去重例外**下解密到仓外内存/临时明文，未抄用、未写入 v3.1 任何密文或公开件；`authoring-inputs.json` 已登记该例外。

## 8. v3.1 三项必修的处置

1. **10 道超阈题重写**：见 §7。只改措辞，不改题意；10 题的 `targets`、`labels`、`authoring-record` 逐条与 v3 相同（`R2/02-consistency.json` 的 `rewrite10_targets_authoring_unchanged=true`）。
2. **C16/C17 自洽**：维持 `expected_kind=not_found`（不改成 answer，避免丢失 `not_found` 状态覆盖）。`reference_answer` 与 `expected_sources=[]` 保持“语料无覆盖”；`authoring-record.lifecycle_rows` 清空（`correct_path=[]`）；`why_this_axis` 改为“语料无覆盖/查无判定”，并明确 `targets`/`entity_scope` 只是问题所问实体、不是引用证据。四处一致；有效轴计数改述为 28/30 + 2 空集。
3. **C20/C21/C22 的 `ITEM_AMBIGUOUS` 风险**：逐题确认三题原文都在单回合里点了**两个物品名**；`rag/query.py:1495-1512` 在 `len(item_hits) > 1` 时直接澄清、不检索。仅加门店限定不能降低 `item_hits` 数量，因此把第二件物品改为**行级指代**（按门店与行状态描述，不再出现第二个词典物品名），每题只保留一个词典物品名；回合数仍为 1，targets/labels/run 不变。陷阱记录仍由 `forbidden_sources`/`forbidden_values` 约束，T2/T3/移除行的判定目标不变。代价：题面不再点名第二件物品，产品需从“门店 + 行状态”推断该行；这是为了避免 planner 澄清而做的有意取舍。

## 9. 零真实调用与保全

- 零真实调用：未调用产品/模型/embedding/rerank/OCR/裁判/检索/鉴权/余额；未启服务；未建 GO。全部脚本在**严格 netguard** 下运行：`socket.connect`/`connect_ex`/`create_connection`/`getaddrinfo`/`http.client.connect`/`urllib.urlopen` 全部拦截，**含回环与本机代理跳点** `127.0.0.1:7897`。正对照 **6/6 被拦**、成功出站 **0**（`R2/05-netguard-positive-control.json`）。
- 未读：T207 失败清单/旧卡/分诊/产品输出/重评分报告/旧标签；v2 题面仅按 §7 的去重例外读取，未读 v2 标签或 v2 key 之外的 v2 私有件。读入清单与 SHA256 见 `authoring-inputs.json`。
- 未改：`fixtures/acceptance/**`、`fixtures/acceptance-h2v3/**`、C 冻结 12、`p2_holdout_scenarios.py`、账本/GO/阈值；未 stage/commit/push；未新建 worktree/切分支。
- 保全：HEAD/分支/暂存/commit 数与基线一致；15 tracked modified 路径与逐文件 SHA 前后一致；既有 untracked 除本轮更新的公开件/证据外逐条 SHA 不变；C 冻结 12 逐项一致。
- 残余：
  1. `conflict` 仍为 0，原因与最小语料建议见 `v3-author/R1/07-four-state-analysis.md` §1.2 与计划 §13.2。
  2. C16/C17 只走空集证明，不测试 target 匹配/日期检查；可判面是 28/30 + 2 空集，不是 30/30。
  3. 多目标题（C07/C12/C26/C28/C29/C30）仍可能在 planner 处触发 `ITEM_AMBIGUOUS`；本轮任务只要求核 C20–C22，未改这 6 题的结构。
  4. `p2_score_run.load_holdout_source_map` 只接受 `/v0.1`，v3 的 source map 是 `/v0.2`；计分接线需另立实现项。
  5. P01 版本碰撞（6 题）与单轮多目标的历史残余仍在；见 `authoring-report.md` §6。

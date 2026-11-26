# H2 v3 出题与标签交付报告（30 题 / 36 回合）

> **R2（2026-11-15）**：本报告 §1–§9 是 v3/R1 的首轮交付记录；v3.1 返工结果见 §10。v3.1 已重新加密并更新 manifest，§1/§9 中的旧 SHA 仅作历史记录，当前 SHA 以 §10 与 `docs/evaluation/p2-holdout-v3-dataset.md` §5 为准。

- 角色：H2 v3 出题与标签作者（普通角色；**不是**验收、**不是**经理、**不是**保管）。
- 基线：分支 `codex/p2-e2e`，HEAD `97b0066726e5b8d6f94cbc0b63a890084550c106`，暂存区 0，0 commit。
- 本轮做了什么：按已批准计划（`ED5DA038…`）的 30 题骨架产出**题面 + 标签 + 实体/生命周期锚点**，加密封存到仓外 root，并删除仓外明文工作目录；仓内只新增本目录、`docs/evaluation/p2-holdout-v3-dataset.md` 与既有未跟踪/已跟踪件之外**没有**其它写入。
- 本文件**不含**题面、参考答案、目标值、逐题「题 → 记录」对应关系；这些在封存密文与（按经理要求的）`authoring-record.jsonl` 内。

---

## 1. 交付物

| 交付物 | 位置 | 可见性 |
|---|---|---|
| 题面（30 行 × 13 键） | `D:\mktkb-p2-holdout\v3\questions.jsonl.fernet` | 密文 |
| 标签（30 行 × 11 键） | `D:\mktkb-p2-holdout\v3\labels.jsonl.fernet` | 密文 |
| 实体/生命周期锚点（30 行） | `D:\mktkb-p2-holdout\v3\targets.jsonl.fernet` | 密文 |
| holdout manifest（严格 15 字段） | `D:\mktkb-p2-holdout\v3\manifest.json` | 明文、repo-safe 元数据 |
| source map v0.2（与仓内件逐字节相同） | `D:\mktkb-p2-holdout\v3\source-map.json` | 明文（仓内已有同件） |
| Fernet key | `D:\mktkb-p2-holdout\keys\v3.key` | **未打印、未复制、未入库** |
| 出题输入清单（白名单 + 逐件 SHA） | `authoring-inputs.json` | 入仓 |
| 逐题出题记录（含场景卡与轴理由） | `authoring-record.jsonl.fernet`（封存件第 6 件） | **R1 起密文**；仓内只留 `docs/evaluation/p2-holdout-v3.authoring-aggregate.json` |
| 结构说明（公开件） | `docs/evaluation/p2-holdout-v3-dataset.md` | 入仓 |
| 证据 | `evidence/01..10` + `R1/01..07` | 入仓（只含计数与摘要） |

明文工作目录 `D:\mktkb-h2v3-authoring\` 在加密 + 读回校验通过后已删除：**31 个文件 / 316256 字节**，删除时间 `2026-11-14T18:30:07Z`，删除后目录不存在、残留文件 0；删除前逐件 SHA256/字节数与删除后核验在 `evidence/07-plaintext-purge.json`。

## 2. 计数与分组（机检）

| 项 | 值 | 对上 |
|---|---:|---|
| case | 30 | `P2_CASE_COUNT` |
| 回合 | 36 | `25×1 + 4×2 + 1×3` |
| 回合直方图 | `{1:25, 2:4, 3:1}` | manifest `turn_stats` |
| 分层 | 10 / 5 / 5 / 5 / 5 | `P2_STRATA` |
| run 题数 | 12 / 8 / 5 / 5 | 计划 §11.4 |
| run 回合数 | 14 / 10 / 6 / 6 | 计划 §11.5 |
| multi_turn | 5 题 / 11 回合（`2/2/3/2/2`） | 计划 §5.2 |

## 3. 逐轴完备（任务要求的三组数）

| 轴 | 完备计数 | 判据 |
|---|---:|---|
| `cross_entity` | **30 / 30** | 每题 ≥1 条 id 型 target：`entity_type ∈ {item,store}`、`entity_key == "{type}\|id:{NFKC+折叠+casefold(标识)}"`、带 `record_code` + `version_number` + `locator{sheet,row}`；target 实例 **36**（30 单 + 6 双）；36/36 在语料里按 `locator` 行解析出同一 `record_code` |
| `stale_source` | **30 / 30** | 每题至少 1 条 used unit 的窗口从 L1 逐值重算并**逐字相等**，且闭区间覆盖该 run 的 `business_date`；4 条被取代对全部行使；4 条记录级窗口行就位；T1/T2/T3/T4L/T4R 各 1/1/1/1/1；无日期对照 2 回合（回合级） |
| `safety` | required **5** / N/A **25** | required 只在 `cross_doc_security`（`must_refuse_security` 3、`forbidden_content` 2）；其余 25 题 `not_applicable` + `benign_business`，全局禁值/禁源检查已执行且干净 |
| `cross_user` | required **30** | 冻结校验器强制（`:447-448`） |

> **R2 修正**：C16/C17 在 v3.1 中维持 `not_found` 零引用；本表的 `cross_entity 30/30` / `stale_source 30/30` 是 R1 的锚点/姿态计数，**不是** target 匹配/日期检查计数。v3.1 的实际可判面为 **28/30 + 2 空集**；见 §10。

- 端点脆弱性：端点题**恰 2 道**（记录级 `effective_to` / `effective_from` 各一）；其余 28 题离所引窗口端点 **≥3 天**（实测最小 **4** 天）。
- `P01` 不出现在 `post_v05_without_v01` 的任何 target 上；`P05`/`P06` 只作陷阱引用，不作 target。
- `entity_key` 与 v3 语料同 key 空间：`filters` 与运行期 `entity_filters` 逐值相等（`store`/`item`/`item_id` 或 `store`/`store_id`），无不透明 id。

## 4. `expected_kind` 分布

| kind | 题数（首轮） | 题数（R1） | 说明 |
|---|---:|---:|---|
| `answer` | 27 | **25** | 有据作答（含 3 道"有据的否定"） |
| `refusal` | 3 | 3 | 3 条 `should_refuse=true`，`refusal_reason=must_refuse_security` |
| `not_found` | 0 | **2** | C16/C17 按语料实际覆盖正确归类（查无）；`should_refuse=true`、零引用 |
| `conflict` | 0 | **0** | **阻塞**：语料有互斥事实但无一对同时现行有效；任何 conflict 标签都会硬失败。见 `R1/07-four-state-analysis.md` §1.2 |

## 5. 自检（全部机检，`evidence/01-selfcheck.json`）

| 检查 | 结果 |
|---|---|
| 30 题 / 36 回合 / 分层 10-5-5-5-5 / 4 run 12-8-5-5 与 14-10-6-6 | **通过**（逐值） |
| 每题 target 与版本对完备（逐轴） | **通过**（见 §3） |
| **题面机检：显式日期** | `YYYY-MM-DD` 0、`YYYY年M月D日` 0、`M月D日` 0、`20YY年` 0、今天/明天/本月/去年/星期类 **0** |
| **题面机检：评测词/固定码/分层名** | `T207/T208/Q1A/rescore/unknown/pass/fail/not_applicable/violation/_missing/_unresolved/entity_scope_conflict/holdout` **0**；四个轴名与 `must_refuse_security`/`forbidden_content`/`benign_business` **0** |
| **题面机检：锚点泄漏** | `record_code`（`P01`–`P08`/`S01`–`S04`）0、`entity_key`（`…|id:`）0、源代号（`D01`/`V04` 等）0 |
| `questions` 与 `labels` 逐题 `expected_kind`/`should_refuse` 一致 | 30/30 一致 |
| `expected_sources` 非空 / `reference_answer` 非空 | **28/30** / 30/30（C16/C17 为 `not_found` 零引用；R2 已与锚点统一） |
| 答案可落地：每个 `expected_value` 出现在被引语的语料单元里 | **30/30 题**（逐值） |
| 禁值不落在本题正确路径的单元里 | 30/30 干净 |
| `authoring_record.as_of == business_date` | 30/30 |
| 仓库加载器 `load_p2_dataset(visibility=holdout)` | **通过**：30/30、36 回合、`metadata_mismatch_count=0` |
| 计分侧版本合并（`remap_holdout_case`） | 30/30 题得到正确 `version_number`；未映射代号 **0** |
| `authoring-inputs` 白名单核对 | 37 条读入路径**全部**在白名单内；黑名单命中 **0** |
| 仓内新增件泄漏扫描 | 对 **14** 个新增仓内文件（本目录 3 件 + `evidence/` 10 件 + 结构说明 1 件）扫 112 条 needle（30 条题干 + 30 条参考答案 + 42 条目标值）：精确命中 **0**；再对每条题干做 6 字滑窗**全窗**扫描：命中 **0**（`evidence/09-leak-scan.json`，清除后从密文内存解封重扫） |

## 6. 残余与需复核项（不隐瞒）

1. **`not_found` 已补齐 2 题（R1）；`conflict` 仍为 0 题（阻塞，非未做）**：R1 把 C16/C17 按语料实际覆盖正确归类为 `not_found`。`conflict` 的阻塞原因、证据与最小语料建议见 `R1/07-four-state-analysis.md` §1.2 与出题计划 §13.1–§13.2：语料确有互斥事实，但没有一对互斥来源同时现行有效；产品不过滤业务日时会引用过期版本行，被冻结分类器判 `source_expired` 硬失败。
2. **`negative` 层的 kind 选择有主观性**：`answer` vs `not_found` 取决于产品把「表里没有这一行」判作答还是判查无。本轮按 R-AX-3 取 `answer`（保住非空引用与实体身份），逐题理由写在 `labels.notes`；请独立复核（S4）可否决。
3. **~~多轮题只看末轮 + 末轮只引正文~~ → R1 已修**：`relevant_units` 不参与冻结分类器的 `_used_unit_layers`，末轮只引纯正文会让 `cross_entity` 落 unknown。C13/C15 已改为**末轮引用现行登记行**，T5 无日期对照移到非末轮（C13 第 2 回合 / C15 第 1 回合）；T5 覆盖计数仍为 2。取舍与自然性说明见 `R1/07-four-state-analysis.md` §2。
4. **`p2_score_run.load_holdout_source_map` 只接受 `/v0.1`**（`p2_score_run.py:498-500`），而 v3 的 source map 是 `/v0.2`。H2 v3 计分侧因此需要新增版本分发（实现项，属另一计划/GO/验收范围）；本轮**未改任何代码**。这会影响 v3 首跑的计分接线，建议在冻结前排期。
5. **~~`authoring-record.jsonl` 入仓与计划 §9.1「私有件」有张力~~ → R1 已闭合**：逐题记录已加密为封存件**第 6 件**（`authoring-record.jsonl.fernet`，与 questions/labels/targets 同 root、同 key），仓内明文已删除，只保留 `docs/evaluation/p2-holdout-v3.authoring-aggregate.json`（计数聚合，不含题号/题面/目标值）。
6. **C25 与临时通知同值**：`pre_v05` 场景里位置表现行行与一份临时通知指向同一存放点；该题题干已显式把依据限定在位置表这一份来源上（不点名任何其它来源），以避免「答对但引另一份来源」被 `source_hit` 误判。
7. **端点题依赖闭区间**：2 道端点题按判据 v1.1 的闭区间判为有效；任何半开实现都会在这两题上系统性错一天（I-8 non-conformant），不是题面缺陷。
8. **相似度回查未做**：计划 §10.3 #5 的「v3 vs v2 题面相似度」由保管在 S5 执行，且需要 v2 题面；本轮禁止读 v2 题面/标签，故未做、也不能自证。
9. **封存目录件数**：任务清单首轮列 4 件，实际 `v3\` 下首轮 5 件（多出的 `targets.jsonl.fernet` 是语料规格 §4 / §6.3 明列的第三件密文）；R1 起固定 **6 件**（`targets` 为第 5 件、`authoring-record` 为第 6 件）。未新增任何其它文件。
10. **输入清单里含 T207 ingest plan**：`docs/reports/OBS-EVAL/P2/T207/PM/T207-ingest-plan-H2.json` 是 L1 `chain_of_authority.inputs_read_only` 与判据 §3.1 明列的结构输入（只有 12 条上传序与 `path`/`name`/`document_ref`）；它不是 T207 的失败清单/分诊/旧卡/逐题输出/重评分报告。已在 `authoring-inputs.json` 中单独标注 `basis` 与 `blacklist.exception`。
11. **v3 ingest plan 与 scenario 契约由本角色生成**：计划 §10.1 期望的 `docs/reports/OBS-EVAL/P2/H2V3/PM/p2-ingest-plan-H2-v3.json` 与 `docs/evaluation/p2-h2-scenarios-H2v3.json` 在工作树里**不存在**（目录也不存在）。按语料规格 §4.3 生成：`schema_version` 不变、12 条顺序逐条不变、只有 `path` 换根；scenario 契约只换 `ingest_plan_sha256`。两者按「仓外明文 → 随明文目录删除」处理，**未入仓**；若保管要按 §4.3 落地到仓内，需要单独确认（本轮任务清单未列该两件为仓内新增）。

## 7. 零真实调用与保全

| 项 | 结果 |
|---|---|
| 出站/真实调用 | **0**：全部脚本在自建 netguard（`sitecustomize` 拦 `connect`/`connect_ex`/`create_connection`/`getaddrinfo`）下运行；正对照 3/3 尝试被拦、成功 0（`evidence/05`） |
| 产品/模型/embedding/rerank/OCR/裁判/检索/鉴权/余额 | 未调用；未启服务；未建 GO |
| HEAD / 分支 | `97b0066726e5b8d6f94cbc0b63a890084550c106` / `codex/p2-e2e`（前后一致） |
| 暂存 / commit / push | 0 / 0 / 未 |
| 15 tracked modified | 15/15 路径逐条不变（`evidence/06` 与 `evidence/10` 前后比对，路径集合逐条相等） |
| untracked | 224 → **225**：新增的顶层条目只有 `docs/evaluation/p2-holdout-v3-dataset.md`；`v3-author/` 落在既有未跟踪目录 `docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/` 内，因此不新增状态行（内容已增加，见 `evidence/10` 的 `untracked_new_entries`） |
| 明文清除 | 仓外工作目录 31 文件 / 316256 字节已删除，删除后残留 0 |
| 未改 | `fixtures/acceptance/**`、`fixtures/acceptance-h2v3/**`、C 冻结 12、`p2_holdout_scenarios.py`、账本/GO/阈值；未新建 worktree/切分支 |

## 8. 复现路径（不依赖明文）

1. 用 `MKTKB_P2_HOLDOUT_ROOT=D:\mktkb-p2-holdout\v3` + `MKTKB_P2_HOLDOUT_KEY_FILE=D:\mktkb-p2-holdout\keys\v3.key` 调 `load_p2_dataset(..., visibility="holdout")`；
2. 逐件 SHA 对 `evidence/04-seal-report.json` 与本目录 §1 表；
3. `targets.jsonl.fernet` 解封后逐条 target 的 `record_code` 应能在 `locator` 指到的语料行（`标识` 列）解析出同名记录；
4. 生命周期逐值复算按判据 v1.1 §3.4 的 V-1..V-6 对 L1 重算（`interval=closed`）。

## 9. R1 返工（2026-11-15，按经理四条裁定）

| 裁定 | 结果 |
|---|---|
| A 四状态 | `answer 25 / refusal 3 / not_found 2 / conflict 0`。`not_found` 由 C16/C17 正确归类（题面未改；语料确实无覆盖；离线探针实测产品返回 `not_found` 且零引用）。`conflict` 仍是 0：**语料有互斥事实但无一对同时现行有效**，产品过滤日期则产不出 conflict、不过滤则引用过期行 → 冻结分类器 `source_expired` 硬失败；已给最小语料/产品修法建议（计划 §13.2），**未硬改标签**。 |
| B `authoring-record` 不进仓 | 已加密为第 6 件封存件，仓内明文删除；只留 `docs/evaluation/p2-holdout-v3.authoring-aggregate.json`。 |
| C 多轮只评末轮 | 确认 `relevant_units` 不参与 `_used_unit_layers`；C13/C15 改为**末轮带实体引用**，T5 移到 C13-t2 / C15-t1（计数不变）。 |
| D `targets` 第 5 件 | 封存件固定顺序已写入语料规格 §4/§6.3 与 dataset 文档 §5：①questions ②labels ③manifest ④source-map ⑤targets ⑥authoring-record。 |

- 新密文逐件 SHA：questions `2f55006c…4c49`（19980 B）、labels `5de0c125…94a7`（33080 B）、targets `0cb9623c…b3d3`（45816 B）、authoring-record `7d52bb72…7b24`（100088 B）、manifest `54f9bb3e…c16e`；source-map 未变 `03665c48…e8b8`。
- 读回 4/4 逐字节相等；仓库加载器复跑 30/30、36 回合、`metadata_mismatch_count=0`。
- 题面机检重跑：显式日期 **0**、评测词/固定码 **0**、`record_code`/`entity_key` **0**（`R1/01-selfcheck.json`）。
- 零真实调用：R1 全部脚本在 netguard 下运行，正对照 **4/4** 被拦（含本机代理跳点）；另在 netguard 下跑 4 个场景的离线产品探针（进程内 ASGI + offline provider，0 真实调用）。
- 保全：HEAD/分支不变、暂存 0、0 commit、tracked modified 15 条路径不变、未新建 worktree/切分支；明文目录删除后不存在。
- 残余：`conflict` 阻塞；P01 版本碰撞（6 题）；单轮多目标与 planner 冲突（6 题）；source-map `/v0.2` 计分接线。详见 `R1/07-four-state-analysis.md` §6。

---

## 10. R2 / v3.1 返工（2026-11-15，按保管 B FAIL 三项必修）

- 输入：`v3-author/independent-review.md`（`FCBABF21…`）与 `review-aggregate.json`（`CE2E634C…`）；v2 冻结题面仅按去重例外解密，未抄用（见 `authoring-inputs.json#/r2_rework`）。
- 结果：`dataset_version=P2-HOLDOUT-v3.1`、`label_version=p2-holdout-v3.1-2026-11-15`；30 题 / 36 回合 / 分层 10-5-5-5-5 / 四 run 12-8-5-5 与 14-10-6-6 / 四状态 25-3-2-0 **全部不变**；labels 与 targets 明文**逐字节未改**（`82931a50…` / `4cda7e09…`）。

| 必修 | 处置 | 证据 |
|---|---|---|
| A 10 道超阈题 | 10 题只改措辞；另对 3 道边界题（C27 0.5000、C28 0.4667、C15 0.4651）与 2 道多物品题（C20/C22）做同义改写；30 题全部重跑。字符级 max **0.4444**、>0.5 **0 题**、Levenshtein max **0.3500**、3-gram Jaccard max **0.1951**。10 题的 targets/authoring 逐条与 v3 相同。 | `R2/03-similarity-final.json`、`R2/02-consistency.json` |
| B C16/C17 自洽 | 维持 `not_found`；`reference_answer`/`expected_sources=[]` 不变；`authoring-record.lifecycle_rows` 清空、`why_this_axis` 改为“语料无覆盖/查无判定”，并写明 targets/entity_scope 只是所问实体、不是引用证据。四处一致；有效轴计数改述为 28/30 + 2 空集。 | `R2/02-consistency.json` 的 `c16_c17` |
| C C20/C21/C22 | 三题原文均在单回合点两个物品名；`rag/query.py:1495-1512` 会 `ITEM_AMBIGUOUS`。仅加门店限定不能降低 `item_hits` 数量，故把第二件改成行级指代（按门店与行状态描述，不再出现第二个词典物品名），每题只留一个物品名；回合数、targets、labels、run 不变。代价是第二件不再点名，需由“门店+行状态”推断。 | `R2/02-consistency.json` 的 `c20_c22` |

### 10.1 新密文（逐件）

| 文件 | 字节 | SHA-256 |
|---|---:|---|
| `questions.jsonl.fernet` | 20708 | `26c637cc1f5045150e7060673703f6eb57e2b95e7f8d127893f477261649f2a0` |
| `labels.jsonl.fernet` | 33080 | `4503701b7c96a6d2a4212e3c32a0ac591311d76ed76dab003a8041e4b43b332f` |
| `targets.jsonl.fernet` | 45816 | `70fc58620a36a00ba02635c6a9517d64e24ba55bee5061ba6d506e86df148e2b` |
| `authoring-record.jsonl.fernet` | 100172 | `009131579409a92dca0e2b2989467793f3e3f30e96162d9387c36ce9b433695f` |
| `manifest.json` | 1039 | `de4125ca9c1d1f68baa30209a12047f1f7753d25a4aa6e8a0d33815dc6b536e8` |
| `source-map.json` | 2648 | `03665c48c0716e45e0a6313c6f1823e6714c996d85254f01283fc0ef5ed2e8b8`（未变） |

- 明文 SHA：questions `3ca61357…`、labels `82931a50…`、targets `4cda7e09…`、authoring-record `00adb5ec…`。读回 4/4 逐字节相等；`load_p2_dataset(..., visibility="holdout")` 复跑 30/30、36 回合、`metadata_mismatch_count=0`、label_version 唯一且等于 manifest（`R2/04-post-seal-verify.json`）。
- 被取代的 v3 旧密文已复制到仓外 `D:\mktkb-h2v3-authoring\superseded-v3\` 备查。

### 10.2 零调用、明文清除、保全

- 零真实调用：严格 netguard 拦截全部 `connect`/`connect_ex`/`create_connection`/`getaddrinfo`/`http.client.connect`/`urllib.urlopen`，**含回环与本机代理跳点 127.0.0.1:7897**；正对照 **6/6 被拦**、成功出站 **0**（`R2/05-netguard-positive-control.json`）。未调用产品/模型/embedding/rerank/OCR/裁判/检索/鉴权/余额；未启服务；未建 GO。
- 明文：仓外 `D:\mktkb-h2v3-authoring\plain\`、`worksheet.json`、`selected.json` 已删除；删除前逐件 SHA/字节数与删除后不存在核验见 `R2/06-plaintext-purge.json`。key 未打印、未复制、未入库。
- 保全：分支 `codex/p2-e2e`、HEAD `97b00667…`、暂存 0、0 commit；15 tracked modified 路径与逐文件 SHA 前后一致；C 冻结 12 逐项一致；`fixtures/acceptance/**` 与 `fixtures/acceptance-h2v3/**` 未改；既有 untracked 除本轮更新的 dataset 文档/聚合/本报告/`authoring-inputs.json` 与新增 `R2/` 证据外，逐条 SHA 不变（`R2/07-preservation.json`）。
- 残余：`conflict` 仍 0（结构原因未变）；C16/C17 只走空集证明；6 道 multi_target（C07/C12/C26/C28/C29/C30）仍有 planner 澄清风险；`p2_score_run.load_holdout_source_map` 仍只接受 `/v0.1`；P01 版本碰撞（6 题）仍在。

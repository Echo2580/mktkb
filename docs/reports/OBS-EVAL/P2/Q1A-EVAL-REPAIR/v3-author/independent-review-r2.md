# H2 v3.1 独立复检（保管 B / R2）

主人，本轮只做 **v3.1 复检**：核上一轮 FAIL 的三项是否真修好，并独立重算相似度。

**结论：PASS_WITH_DISAGREEMENTS。**
三项内容阻断（A 去重、B C16/C17、C C20–C22 的 `ITEM_AMBIGUOUS`）均已解除；剩余为低/中风险分歧与冻结前置条件，见 §9–§10。**是否可进入冻结：可（有条件）**，条件见 §10。

- 复核时间（本地）：`2026-11-15T03:53:17+08:00`
- 基线：分支 `codex/p2-e2e`，HEAD `97b0066726e5b8d6f94cbc0b63a890084550c106`，暂存 0，172 commit；未新建 worktree/切分支。
- 角色：保管 B（独立复核）；不参与出题、标注、验收，不写 release/GO，不 stage/commit/push。
- 只读 v3.1 密文、v2 冻结题面（仅去重）、语料与公开件；为核对 schema，v2 labels 仅在进程内解封读取字段名，未读取/未使用任何标签值；key 只在进程内存，未打印/复制/落盘；未写任何含题面/答案/目标值的临时明文。

## 0. 对象与哈希（逐个复核）

| 件 | 字节 | SHA-256（前 16） | 结论 |
|---|---:|---|---|
| `v3/questions.jsonl.fernet` | 20708 | `26c637cc1f504515` | 与任务给定一致 |
| `v3/labels.jsonl.fernet` | 33080 | `4503701b7c96a6d2` | 一致 |
| `v3/targets.jsonl.fernet` | 45816 | `70fc58620a36a00b` | 一致 |
| `v3/authoring-record.jsonl.fernet` | 100172 | `009131579409a92d` | 一致 |
| `v3/manifest.json` | 1039 | `de4125ca9c1d1f68` | 一致 |
| `v3/source-map.json` | 2648 | `03665c48c0716e45` | 未变 |
| `v2/questions.jsonl.fernet` | 16420 | `36d29ba59671487d` | 未变 |
| `v2/labels.jsonl.fernet` | 26360 | `d51478fdc28960cf` | 未变 |
| `v2/manifest.json` | 1037 | `8874985ef8f4aacc` | 未变 |

- Fernet 解密回读 4/4 通过；v3.1 明文 SHA：questions `3ca61357…`、labels `82931a50…`、targets `4cda7e09…`、authoring-record `00adb5ec…`，与 manifest/R2 声明逐字相等。
- 仓库加载器 `load_p2_dataset(..., visibility="holdout")` 在项目 `.venv` 下复跑通过：30 cases / 30 labels / `metadata_mismatch_count=0`；未启服务、未调用产品。
- 被取代的 v3 旧密文（仓外 `superseded-v3`）逐件解密比对：旧 questions `d2aa0287…`、旧 authoring-record `12f20fc1…`；旧 labels/targets 与 v3.1 明文**逐字节相同**（`82931a50…` / `4cda7e09…`）。这是本轮判断“labels/targets 未变”的直接证据，不依赖出题方数字。

## 1. A. 去重是否真达标（独立重算）

方法：v3.1 每题文本（`question`；多轮为 `turns` 拼接）对 v2 冻结 30 题逐一比对，每题取最大值；归一化 = NFKC + 去空白/标点 + casefold。指标独立实现：`difflib.SequenceMatcher`（字符级）、归一化 Levenshtein（`1 - dist/max(len)`）、字符 3-gram Jaccard。未使用出题方脚本、阈值文件或中间结果。

| 指标（全文本） | min | median | max | **>0.5 题数** | ≥0.5 题数 |
|---|---:|---:|---:|---:|---:|
| 字符级 SequenceMatcher | 0.2545 | 0.3712 | **0.4444** | **0** | 0 |
| 归一化 Levenshtein | 0.1667 | 0.2708 | **0.3500** | **0** | 0 |
| 字符 3-gram Jaccard | 0.0278 | 0.0990 | **0.1951** | **0** | 0 |

- 判定标准：字符级 **max < 0.5** 且 **>0.5 题数为 0**。实测 **max 0.4444 / 0 题**，**PASS**。
- 最大 5 对（仅题号）：C19↔h2-par-01 0.4444（Lev 0.2963 / J3 0.0513）；C26↔h2-sec-01 0.4412（0.3191 / 0.1429）；C06↔h2-par-03 0.4375（0.2941 / 0）；C06↔h2-sec-03 0.4324（0.3500 / 0.1379）；C03↔h2-par-04 0.4324（0.3158 / 0.0313）。
- 上一轮 10 道超阈题（C01/C02/C04/C05/C07/C08/C21/C24/C25/C29）本轮字符级最大值分别约 0.4000/0.2979/0.3600/0.4255/0.2727/0.3077/0.4000/0.3750/0.3673/0.3871，全部 < 0.5。
- 稳健性：保留标点时字符级 max **0.4583**、>0.5 **0**；只保留字母/数字时 max **0.4444**、>0.5 **0**；只看 `question` 字段时 max **0.4444**、>0.5 **0**。最长公共子串 max **11** 字符（<12），无整句复用迹象。
- 辅助指标：3-gram containment 的 max **0.6667**、>0.5 **3**（C30/C26/C22）；这是包含度、不在本轮门槛内，仅记录，不作为通过/失败依据。
- 出题方 R2 声明（字符级 0.4444、Levenshtein 0.3500、Jaccard 0.1951、>0.5 0 题）与本复算逐值一致；本报告数字仍以本次独立进程为准。

## 2. B. C16/C17 是否四处一致、零引用且语料无覆盖

| 检查 | C16 | C17 |
|---|---|---|
| questions / labels `expected_kind` | not_found / not_found | not_found / not_found |
| `should_refuse` / `refusal_reason` | true / not_found | true / not_found |
| `expected_sources` / `relevant_units` / `expected_values` | 0 / 0 / 0 | 0 / 0 / 0 |
| `reference_answer` 含否定覆盖语义 | true（34 字符） | true（32 字符） |
| `why_this_axis` 含“语料无覆盖/空使用集”且无“有据” | true / true | true / true |
| `lifecycle_rows` / `correct_path` 行数 | 0 / 0 | 0 / 0 |
| `cross_entity` target 数（仅身份） | 1 | 1 |
| target 行可解析到语料且身份一致 | true | true |
| 四个位置表版本中该门店的登记行数 | 0/0/0/0 | 0/0/0/0 |
| `stale_source.used_units` | 0 | 0 |
| `no_corpus_coverage` / `four_way_consistent` | true / true | true / true |

- 四处（`expected_kind`、`reference_answer`、`expected_sources`、锚点 `why`/`correct_path`/`lifecycle_rows`）现在描述同一条“查无”正确路径：题面问的门店在四个位置表版本中均无登记行；labels 零引用；`reference_answer` 明确否定覆盖；`why_this_axis` 明确“语料无覆盖、正确路径零引用、targets/entity_scope 仅标识所问实体、不是引用证据”；`lifecycle_rows=[]`、无 `correct_path`。`axis_rationale.stale_source` 另写明“无 dated 使用单元、不产生日期子检查”，与空集证明一致。
- **有效轴口径**：`cross_entity` 为 **28/30 target 匹配 + 2 空集**，`stale_source` 为 **28/30 日期检查 + 2 空集**，不再是 30/30。公开 aggregate 与 dataset 文档已按此口径改写；本轮认可该口径。
- 保留项：两题的 `cross_entity`/`stale_source` `applicability` 仍是 `required`（结构字段未改为 `not_applicable`），实际依赖冻结分类器的空使用集证明。若冻结校验器不接受“required + 0 used unit”的空集通过，则这两题会从“28/30 + 2 空集”变成不可判；这是冻结前置的验证点，不是 labels/anchors 自相矛盾。
- **结论：B PASS**（四处一致、零引用、语料确无覆盖；28/30 + 2 空集口径成立）。

## 3. C. C20/C21/C22 是否单物品、item_count=1、targets/labels/run 未变、ITEM_AMBIGUOUS 是否消除

| 项 | C20 | C21 | C22 |
|---|---:|---:|---:|
| 回合数 | 1 | 1 | 1 |
| 词典物品名命中（新） | 1 | 1 | 1 |
| 词典物品名命中（旧 v3） | 2 | 2 | 2 |
| `item_count`（新/旧） | 1 / 2 | 1 / 2 | 1 / 2 |
| `cross_entity` target 数 / item target 数 | 1 / 1 | 1 / 1 | 1 / 1 |
| labels 逐字节与旧相同 | true | true | true |
| targets 逐字节与旧相同 | true | true | true |
| run / stratum 与旧相同 | true / true | true / true | true / true |
| 静态 `parse_query`（旧；标题=纯中文名） | `ITEM_AMBIGUOUS` | `ITEM_AMBIGUOUS` | `ITEM_AMBIGUOUS` |
| 静态 `parse_query`（新；标题=纯中文名） | `None`；filters 仅 item | `None`；filters store+item | `None`；filters 仅 item |
| 题面命中的门店数（新/旧） | 2 / 2 | 1 / 1 | 2 / 2 |

- 三题都已从“单回合两个词典物品名”改为“只保留一个词典物品名，第二件用门店 + 行状态作行级指代”；回合数、targets、labels、run、分层均未变。**`ITEM_AMBIGUOUS` 在 planner 层已消除**：旧文本三题均命中 >1 个 item，新文本均为 1 个。
- 残余（不是 `ITEM_AMBIGUOUS`，但会影响答案落地）：C20/C22 仍点名两个门店，`rag/query.py:1720` 在 `len(state.stores) > 1` 时**丢弃 store filter**；C20 的物品名唯一，C22 的同名物品在两个门店都有现行行，检索可能同时命中两店。C21 只有单门店，filters 为 store+item，最干净。该门店过滤行为旧题也存在，不是本轮新引入；但冻结前应做一次真实索引的离线冒烟，确认 C20/C22 的答案不会拿错门店。
- 文档名敏感性（同一冒烟一起验）：`qa/service.py:232` 用 `document.name` 作标题，`documents/service.py:766` 的 `name=filename` 来自上传名；`query.py` 的 `_document_core` 在标题含 `Dxx_` 前缀时只取前缀。若 v3 ingest plan 的 `name` 保留 `Dxx_` 前缀（冻结 v2 plan 如此），C20/C22 可能在 `DOCUMENT_NOT_FOUND` 处提前澄清；若使用纯中文标题，则本轮静态复现为 `None`。这是产品/ingest 接线条件，不是题库数据缺陷；本轮不以未验证的产品行为判题库 FAIL。
- **结论：C PASS（就“单物品/ITEM_AMBIGUOUS”这项任务而言）**；门店过滤/文档标题作为冻结冒烟条件列入 §10。

## 4. 结构（未变）

| 项 | 要求 | 实测 | 结论 |
|---|---|---|---|
| 题数 | 30 | 30（questions/labels/targets/authoring 各 30 行，case_id 集合与行序四件全等） | PASS |
| 回合 | 36 | 36；直方图 `{1:25, 2:4, 3:1}`；multi_turn 分配 `2/2/3/2/2` | PASS |
| 分层 | 10/5/5/5/5 | 10/5/5/5/5 | PASS |
| 4 run 题数 | 12/8/5/5 | 12/8/5/5 | PASS |
| 4 run 回合 | 14/10/6/6 | 14/10/6/6 | PASS |
| 4 个 run 日期 | 互不相同、各 run 一个 | 4 个互异；题面 `business_date` 与所属 run 逐题相等 30/30 | PASS |
| 四状态 | 25/3/2/0 | `answer 25 / refusal 3 / not_found 2 / conflict 0` | PASS（conflict=0 仍是已知覆盖缺口，不在本轮三项内） |
| `should_refuse` | 与 kind 一致 | 25 false / 5 true；labels 与 questions 逐题一致 30/30；原因 null 25 / not_found 2 / must_refuse_security 3 | PASS |
| target | 36 实例 | 36（24 单 + 6 双）；三元组 36/36；anchor 36/36；36/36 独立解析到唯一语料行且 identity/filters/source-version 全等 | PASS |
| manifest | 15 键 | 15 键；case_count/strata/turn_stats/明文 SHA/密文 SHA 复算全等；label_version 唯一 | PASS |
| 其他 | suite/split=holdout、requires_ocr=false | 30/30、30/30 | PASS |
| `case_index` | 1..30 | 1..30 连续；`turn_count` 与题面 30/30 一致 | PASS |

## 5. 重写的 15 题是否真的只改措辞

- 旧/新 questions 逐题 diff：文本变化恰 **15 题**：C01/C02/C04/C05/C07/C08/C15/C20/C21/C22/C24/C25/C27/C28/C29，与声明集合逐项相等。
- 变化字段只有 `label_version` + `question` 或 `turns`（C15 改 turns，其余改 question）；C01/C21 另改 `question.notes`。**没有任何**非文本、非 `label_version` 字段变化。
- 旧/新 **labels 明文逐字节相同**（30/30），旧/新 **targets 明文逐字节相同**（30/30）。因此 15 题的 `expected_sources`、`forbidden_values`、`forbidden_sources`、版本对/窗口、run、分层、targets 全部未变；`lifecycle_rows` 逐题相同。
- 旧/新 authoring-record 只有 **C16/C17** 两题变化（`axis_rationale`、`lifecycle_rows`、`why_this_axis`），其余 28 题逐字节相同；这正是 B 项修复的范围。
- **结论：PASS**。唯一需要披露的是 C01/C21 的 `question.notes` 也改了；它不在题面/标签判定路径上，不影响“只改措辞”的主体结论。

## 6. 泄漏扫描（题面 + turns，30 题全文）

| 模式 | 命中 |
|---|---:|
| `YYYY-MM-DD` / `YYYY年M月D日` / `M月D日` / `20YY年` | 0 |
| 评测词/固定码（T207/T208/Q1A/rescore/unknown/pass/fail/not_applicable/violation/entity_scope_conflict/holdout） | 0 |
| 轴名/判据名（cross_user/cross_entity/stale_source/must_refuse_security/forbidden_content/benign_business） | 0 |
| `record_code`（P/S + 两位数字形态） | 0 |
| `entity_key` / `record_key` / `|id:` | 0 |
| 源代号（D/V + 两位数字形态） | 0 |
| 分层名 / `P2-HOLDOUT` / `H2V3` | 0 |

**结论：题面泄漏 0。** 未发现日期、评测词、固定码、record_key、源代号进入题面。

## 7. 反照抄

| 检查 | 结果 |
|---|---|
| `authoring-inputs.json` 读取 | 37 条；白名单违规 0；黑名单命中 0 |
| 读取哈希 | 35/37 与记录相等；仅 2 份计划文档漂移（authoring plan `ed5da038→ddbab338`、corpus spec `6d64ee79→5f06eed1`，均为 R1/R3 增补后的历史读取差，不是 v3.1 材料） |
| v3 语料读取记录 | 13/13 哈希相等；L1、source-map、corpus manifest、判据 v1.1 逐件相等 |
| v2 读取例外 | 仅 `v2/questions.jsonl.fernet`（`36d29ba5…`，16420 B）用于去重；`copied_into_v31=false`；未读 v2 labels/key |
| authoring-record 失败/旧卡/分诊痕迹 | T207/T208/Q1A/rescore/partial-audit/manager-*/review-aggregate/independent-review/dev-report/oldcard/old-card/failure-list/triage/失败清单/分诊/旧卡/fail/unknown = **0** |
| 私有理由中的评测词（低） | `passed` 6 次（C16/C17）、`有据` 3 次（C18/C19/C20）；只在私有 authoring-record，不在题面/公开件 |
| scenario_card | 9 个字段恰为 business_role/task/expected_output_shape/stratum/turn_count/scenario_id/corpus_slots/time_semantics/entity_scope；30 个唯一 id；无 T207/Q1A/旧卡/分诊 token |
| review 状态 | 30/30 `pending_independent_review`；`disagreement_code` 全 null |
| 证据 / 计划引用 | `evidence_ref` 全为 `authoring-inputs.json#/read`；`plan_ref` 全为计划 §5 Cxx |
| 与 v2 文本复用 | 最长公共子串 11 字符；无整句复用；字符级 max 0.4444（见 §1） |

**结论：反照抄干净。** 两个低severity 记录项：(a) 私有 authoring-record 仍含 `passed`/`有据` 判定词（上一轮已提示，R2 未清）；(b) `authoring-inputs.declared_not_read` 仍写“v2 私有密文与 v2 key 均未打开”，与 `r2_rework.dedup_exception` 的“v2 questions 仅去重读取”矛盾。两者都不改变“未抄用”的结论，但建议在冻结清单登记/修正。

## 8. 保全与零真实调用

| 项 | 结果 |
|---|---|
| 分支 / HEAD | `codex/p2-e2e` / `97b0066726e5b8d6f94cbc0b63a890084550c106`（复核前后一致） |
| 暂存 / commit / push | 0 / 0 / 未；未新建 worktree、未切分支 |
| 15 tracked modified | 路径集合 15/15、逐文件 SHA 15/15 与 `axes/evidence/04-protected-hashes-before.json` 相等 |
| C 冻结 12 | 12/12 逐项相等（含 `p2_hard_evidence.py`、`product_adapter.py`、`cli.py`、capture 契约与 readiness 测试） |
| v2 密文 | manifest `8874985e…`、questions `36d29ba5…`、labels `d51478fd…` 前后不变 |
| v2 语料 `fixtures/acceptance/**` | 35 个文件；工作树对 HEAD 无改动 |
| v3 语料 | 13/13 读取记录哈希相等；`fixtures/acceptance-h2v3/**` 本轮未改 |
| v3.1 密文/公开件 | 6 件 SHA 前后不变（见 §0） |
| 本轮产物 | 仅本报告与 `review-aggregate-r2.json`；未改既有文件 |
| 零真实调用 | 未调用产品/模型/embedding/rerank/OCR/裁判/检索/鉴权/余额；未启服务；未建 GO |
| 零出站（独立确认） | 全部分析进程在自建 netguard 下运行；正对照 **6/6 被拦**（`example.com:80/443`、本机代理跳点 `127.0.0.1:7897`、`urllib`、`http.client`、`getaddrinfo`），成功出站 **0**；16 个带 guard 的分析进程 `attempts=0`、`real_connects=0`。负对照（`python -S` 无 guard，连本机关闭端口）返回 `TimeoutError` 而非 `NetworkBlocked`，证明拦截来自 guard 而非网络栈 |
| 代理 | 环境确有 `HTTP(S)_PROXY/ALL_PROXY=127.0.0.1:7897`；正对照显式覆盖该跳点并被拦，分析进程 0 次尝试，未借道代理 |

## 9. 分歧与残余（保留不表决）

1. **C20/C22 的门店过滤（中）**：两题仍点名两个门店；`query.py:1720` 在 `len(state.stores)>1` 时丢弃 store filter。`ITEM_AMBIGUOUS` 已消除，但 C22 的同名物品在两店都有现行行，检索可能同时命中；C20 物品名唯一，风险较低。旧题同样如此，不是本轮引入；冻结前需真实索引离线冒烟确认答案不拿错门店。
2. **文档标题敏感性（中，接线）**：`Document.name` 来自上传名；若 v3 ingest plan 的 `name` 保留 `Dxx_` 前缀，`_document_core` 只取前缀，C20/C22 可能在 `DOCUMENT_NOT_FOUND` 处提前澄清；纯中文标题则本轮静态复现为 `None`。这是产品/ingest 接线条件，需与第 1 条一起冒烟。
3. **C16/C17 的 `applicability=required`（低）**：结构字段仍为 required，实际靠空集证明；公开 aggregate/dataset 文档已改述为 28/30 + 2 空集。若冻结校验器不接受 required + 0 used unit，需在冻结前显式确认分类器行为。
4. **私有评测词（低）**：authoring-record 内 `passed` 6 次、`有据` 3 次；未入题面/公开件。上一轮已提示，R2 未清。
5. **`declared_not_read` 与 `r2_rework` 矛盾（低）**：前者称 v2 私有密文/key 未打开，后者登记 v2 questions 仅去重读取；建议修正文案。
6. **计划文档漂移（低）**：authoring-inputs 读取记录中 2 份计划文档 SHA 与当前不同（历史读取版本），不是越界；复现需注明版本。
7. **`conflict=0`（已知）**：四状态仍为 25/3/2/0；conflict 覆盖缺口未在本轮三项内处理，仍是 T207 语义缺口。

## 10. 是否可进入冻结

**可进入冻结（有条件）。** A/B/C 三项内容阻断已解除；冻结前需：

1. 用**真实产品索引**做一次 C20/C22 离线冒烟：确认文档标题不触发 `DOCUMENT_NOT_FOUND`，并确认两门店提及不会让检索/答案拿错门店（C21 作为单门店对照）。
2. 关闭上一轮 §10 的接线/冻结前置：`p2_score_run` 的 source-map `/v0.2` 分发、`targets.jsonl` → v0.2 annotation 的 7 字段 axis/3 键 target 投影、v3 自己的 scenario contract/ingest plan 落盘与 SHA 绑定、L1 `corpus_manifest_sha256` 绑定（或明确由 source map 承担并在 freeze 清单说明）。
3. 公开聚合保持 `similarity.status="computed"` 与 `28/30 + 2 空集` 口径；`authoring-inputs` 的 `declared_not_read` 文案修正；冻结清单登记 `passed/有据` 私有词与计划文档漂移。

上述条件不改变本轮三项的 PASS 结论；它们是冻结前的接线/文案/冒烟条件。

## 附录 A：复算方法与证据

- 解密/加载：Fernet（key 只在进程内存）；`load_p2_dataset(..., visibility="holdout")`（项目 `.venv`）；`openpyxl` 直读 12 个语料文件。
- 相似度：自写 `SequenceMatcher`/Levenshtein/3-gram Jaccard；30×30 全配对；报告只给题号与数值，不写题面。
- 结构/分层/回合：独立复算；`turn_count = len(turns) if turns else 1`。
- key 空间：按 target 的 `source_code` + `locator` 解析到具体语料行，独立复算 `entity_key`/`filters`；36/36 identity/filters/source-version 全等。
- labels：34 条 expected_sources 全部解析；45 个 expected_values 全部出现在 reference_answer 与所引 source 行；12 个 forbidden_values 可在语料定位且 0 个进入 reference_answer；8 条 forbidden_sources（3 条行级 + 5 条文档级）。
- 生命周期：34 个 used unit 的闭区间全部覆盖 `as_of`；`as_of == business_date` 30/30。
- 零调用：17 个 guard 日志（16 个分析进程 + 1 个正对照）`real_connects=0`；正对照 6/6 被拦；负对照无 guard 时 `TimeoutError`。

## 附录 B：与上一轮报告的关系

- 上一轮 FAIL 的三项：A 相似度（字符级 max 0.6486、10 题 >0.5）→ 本轮 max 0.4444、0 题；B C16/C17（labels 零引用 vs anchors correct_path/有据否定）→ 本轮四处一致、无 correct_path、无“有据”；C C20–C22（多物品 `ITEM_AMBIGUOUS`）→ 本轮 item_count=1、旧文本三题 `ITEM_AMBIGUOUS`、新文本均 `None`。
- 上一轮 §10 的接线/冻结前置未在本轮三项内，仍按 §10 条件保留。
- 本报告不改变上一轮对 `conflict=0` 覆盖缺口的判断；该缺口仍存在。

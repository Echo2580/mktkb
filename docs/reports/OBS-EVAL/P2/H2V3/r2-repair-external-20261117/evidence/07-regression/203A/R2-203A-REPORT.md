# R2-203A 副作用复核报告（T-R2-203C 跨实体取数联结）

- 任务：`T-R2-203A 202C 副作用复核（最高优先）`
- 仓库：`D:\GPT项目\市场部AI知识库`
- 解释器：`.venv\Scripts\python.exe -X utf8`（Python 3.12.7）
- 基线时间：2026-11-17
- basetemp：`D:\mktkb-p2-h2v3-r2-20261117\basetemp-203a\*`（仓库外）
- 本报告目录：`docs/reports/OBS-EVAL/P2/H2V3/r2-repair-external-20261117/evidence/07-regression/203A/`

## 0. 复核对象与只读声明

本批（2026C）三个文件的字节与任务书一致（复核时实测）：

| 文件 | sha256（前 16） | 字节 |
|---|---|---|
| `backend/src/mktkb/rag/retrieval.py` | `aee14c827578fa79` | 34458 |
| `backend/src/mktkb/rag/answer.py` | `b89622beb20f0d73` | 58877 |
| `backend/src/mktkb/rag/facts.py` | `cf795cfd16fe15fd` | 28961 |

只读纪律执行情况：

- `backend/src/**`：**一行未改**；未执行任何 git 写操作（无 checkout/restore/stash/commit）。
- 未改任何既有测试文件、`docs/evidence/**`、`fixtures/**`、`docs/evaluation/**`、账本/预算/GO 槽位。
- 未触碰 `work/**`、`evidence/04-mechanism/**`、`evidence/05-fix/**`。
- 新建文件仅本目录：`R2-203A-REPORT.md`、`R2-203A-SUMMARY.json`、`conftest.py`、
  `probe_203a_multirow_multipage.py`、`probe_203a_value_no_fabricated_layers.py`、`probe-artifacts/*.json`。
- 复核 104 探针时用 `-p no:cacheprovider` + `PYTHONDONTWRITEBYTECODE=1`，事后确认
  `work/r1_104_probes/` 下**没有**新增 `__pycache__`。

---

## 1. 分页 / 结构数字是否被本批改变

### 1.1 节点执行（离线层）

工作目录 `backend/`，统一追加 `-q -p no:cacheprovider --basetemp=D:\mktkb-p2-h2v3-r2-20261117\basetemp-203a\<node>`：

| # | 节点 | 命令（`python -X utf8 -m pytest …`） | 退出码 | 结果 |
|---|---|---|---|---|
| 1 | 102d 分页 | `tests/evaluation/test_r1_102d_turn_pagination.py` | 0 | **8 passed** |
| 2 | 102a 结构数字 | `tests/evaluation/test_r1_102a_structural_numbers.py` | 0 | **9 passed** |
| 3 | 103 HTTP 结构数字 | `tests/integration/test_r1_103_http_structural_numbers.py` | 0 | **3 passed** |
| 4 | 103 HTTP 范围/拒答 | `tests/integration/test_r1_103_http_scope_and_refusal.py` | 0 | **3 passed** |
| 5 | 104 评分探针 | `…\r1-repair-external-20261117\work\r1_104_probes\test_r1_104_scoring_probes.py` | 0 | **9 passed** |
| 6 | 104 范围/拒答探针 | `…\r1_104_probes\test_r1_104_scope_refusal_probes.py` | 0 | **10 passed** |
| 7 | 202C 本批自带 | `tests/integration/test_r2_202c_c29_join_rag.py` | 0 | **13 passed** |
| 8 | 202A 机制合成 | `tests/integration/test_r2_202a_c29_mechanism_synthetic.py` | 0 | **13 passed** |
| 9 | R2 回归 | `tests/rag/test_r2_regressions.py` | 0 | **6 passed** |
| 10 | 本报告探针·行/页 | `…\203A\probe_203a_multirow_multipage.py` | 0 | **7 passed** |
| 11 | 本报告探针·两层口径 | `…\203A\probe_203a_value_no_fabricated_layers.py` | 0 | **6 passed** |

四节点合计 **23 passed / 0 failed**；104 探针合计 **19 passed / 0 failed**。
仓库内**不存在** `backend/tests/**/test_r1_104_*.py`（实测：`tests` 下 104 相关只有
`test_p1_t104_error_classification{,_http}.py`，那是另一个任务 T104，与本题无关；
真正的 104 对抗探针只在 R1 执行者的 `work/r1_104_probes/`）。

### 1.2 `value_no_fabricated` 的结构 token 到底来自哪里（代码定位）

- `backend/src/mktkb/evaluation/p2_scoring.py:828-834` `P2_PAGINATION_NUMBER_KEYS = ("total","page","page_size","returned","next_page")`
- `backend/src/mktkb/evaluation/p2_scoring.py:837-853` `_pagination_number_keys()`：**只认这 5 个键、且值必须是 `int`**（`bool`、字符串数字一律不进）。
- `backend/src/mktkb/evaluation/p2_scoring.py:1003-1013`：`structural_keys = citation_structural_number_keys(citations) | _pagination_number_keys(outcome.pagination)`，然后传给 `score_case(..., structural_number_keys=structural_keys)`。
- `backend/src/mktkb/evaluation/scorers.py:718-735` `_value_checks`：`allowed = _gold_number_keys(case) | evidence_keys | structural_keys`；答案文本里任何不在 `allowed` 的数字 → `value_no_fabricated=fail`，`evidence["extra"]` 列出。
- `backend/src/mktkb/evaluation/scorers.py:447-451 / 494-509`：结构 token 归一化与「引用 locator 整数」。

### 1.3 新出现的 `2` 有没有出处：**有出处（P2 层，离线可证）**

链路上「页头文字」与「`pagination` 下发」是**结构性绑定**的，不是巧合：

1. 「共 N 条…显示 N 条」全仓**只有一处**产生：`backend/src/mktkb/rag/answer.py:917`
   （`_enumerate_answer` 内），其返回对象固定 `answer_source="structured_enumeration"`
   （`answer.py:955`）。
2. 产品下发 `pagination` 的唯一入口 `backend/src/mktkb/conversations/service.py:2401-2412`，
   条件是 `kind == "answer" and (answer.answer_source == "structured_enumeration" or diagnostics["enumeration"])`
   ⇒ **只要正文里出现页头，就一定同时下发 `pagination`**（`total/page/page_size/returned/has_more/next_page`）。
   若 `_enumerate_answer` 提前走 `_no_answer`/`_reject`（`answer.py:896-901 / 946-947`），
   则正文里根本没有页头，也就没有"新数字"问题。
3. `total` 的来源：`answer.py:902` `total = int(result.total)`；`result.total` 来自
   `backend/src/mktkb/rag/retrieval.py:115-116` `base = _enumerate_base(exact_chunks, …); total = len(base)`，
   而联结店家行在 `retrieval.py:340-350` 已被并入 `exact_chunks` ⇒ 这正是 `1 → 2` 的机制。
4. 采集侧：`backend/src/mktkb/evaluation/product_adapter.py:812-827 _pagination_of()`
   把产品响应里的 `pagination` 原类型收进 `ProductTurn.pagination`；
   `p2_scoring.py:577` `pagination = turn.get("pagination") or product.get("pagination") or {}`
   ⇒ 进入 `outcome.pagination`，再被 `_pagination_number_keys` 归一成允许 key。

**实测（离线可证，全部合成数据）**——`probe_203a_value_no_fabricated_layers.py`：

| 用例 | 文本 | `pagination` | `value_no_fabricated` |
|---|---|---|---|
| `test_p2_after_text_is_grounded_by_product_pagination` | 改后「共 2 条…显示 2 条」 | 有（total=2,returned=2,page=1） | **pass**，`structural_numbers>=2` |
| `test_p2_before_text_is_grounded_too` | 改前「共 1 条…显示 1 条」 | 有（total=1,returned=1） | **pass**（改前也是靠分页，不是"改后才放水"） |
| `test_p2_after_text_without_pagination_is_fabricated` | 改后同样文本 | **无** | **fail**，`extra == ["1","2"]` |
| `test_pagination_key_whitelist_is_exactly_five_int_keys` | — | `total="2"` / `has_more=1` / `revision=42` / `total=True` | 只有合规 int 进集合（负例，未被放宽） |
| `test_p1_layer_ignores_pagination_entirely` | 改前/改后 | 有 | **两者都 fail**（`extra` 分别 `["1"]` / `["1","2"]`） |
| `test_p1_layer_flips_pass_to_fail_only_if_gold_contains_the_old_count` | 金标含 `"1"` | 有 | 改前 **pass** → 改后 **fail**（`extra==["2"]`） |

单页实测（`probe_203a_multirow_multipage.py`，真实上传→解析→发布→问答）：
改后正文 `共 2 条，当前第 1 页显示 2 条。`，产品 `pagination={"page":1,"page_size":10,"total":2,"returned":2,"has_more":false,"next_page":null}`
⇒ 数字 `2`/`1` 都在 `pagination` 里，有出处。

### 1.4 「`total` 与渲染行数不一致」会不会新增 fail 风险：**不会（多页形态已实测）**

多页（`page_size=1`，同门店 2 条店家行）实测：`total=3`、`returned=1`、`has_more=true`、`next_page=2`，
正文 `共 3 条，当前第 1 页显示 1 条`。`returned != total` 是**合法分页**，且 `3`（total）与
`1`（returned/page）**都在** `pagination` 里 ⇒ 仍然有出处，不产生 `extra`。

### 1.5 结论（离线层 / 真实层分开）

- **离线测试层结论：本批不改变任何既有分页/结构数字断言。**
  - 23 个既有节点断言 + 19 个 104 对抗探针 + 32 个邻接回归（202A/202C/R2）全绿。
  - 102d/102a 的 M2 形态（`共 2 条…显示 2 条`）本来就是"靠分页计数拿出处"的用例；
    本批把真实产品输出的 `total` 由 1 变 2 后，走的仍是同一条 `pagination → structural_keys`
    通道，且页头文字与 `pagination` 在代码上强制同生同灭（`answer.py:917/955` +
    `conversations/service.py:2401-2412`）。
  - 唯一能让 `2` 变成"无出处"的条件是**分页不下发**；该条件在"正文出现页头"的前提下
    不可达（见 §1.3 第 1-2 条），故不是新增风险面。
- **真实链路层：NOT-RUN。** 未跑 P2 live/holdout（需真实语料 + GO 槽位 + 出站配额），
  也未跑 P1 live（需索引 + 模型）。真实层的最终判据仍是下一次 P2 run 的
  `value_no_fabricated` 与 `pagination_*` 检查；离线已把它压缩成"分页是否随答案下发"这一条
  可执行条件。
- **P1 口径的独立风险（非本批引入、但会被本批触发的方向）：**
  `backend/src/mktkb/evaluation/runner.py` 的五处 `score_case(...)`
  （`runner.py:1578/1622/1802/2112/2119`）**都不传** `allowed_number_keys` /
  `structural_number_keys`，因此 P1 口径下 `value_no_fabricated` 只认
  `_gold_number_keys`（`scorers.py:422-429`）。若存在这样一条 P1 用例：形态触发联结、
  且金标/题面里恰好含旧计数 `1`、不含 `2`，则本批会把该用例的 `value_no_fabricated`
  由 pass 变 fail（已用合成用例
  `test_p1_layer_flips_pass_to_fail_only_if_gold_contains_the_old_count` 固定）。是否为
  实际问题取决于 P1 数据集里是否存在该形态 —— **未验证（NOT-RUN，需索引）**。

---

## 2. `diag` 消费方核查

### 2.1 `filter_miss` 的全部落点（源码 grep，共 4 处）

| 位置 | 角色 |
|---|---|
| `backend/src/mktkb/rag/retrieval.py:610-612` | **唯一生产点**：`if diag is not None and filter_stats["candidates"] > filter_stats["passed"]: diag["filter"] = "filter_miss"` |
| `backend/src/mktkb/qa/service.py:56-63` | `CANDIDATE_DROP_PRIORITY`：`kind_miss > term_miss > vector_unavailable > filter_miss > dedup_dropped > limit_dropped` |
| `backend/src/mktkb/qa/service.py:66-86` | `_merge_candidate_drop_reason` / `_face_candidate_drop_reason`：把两面 diag 按优先级折成**一个**枚举码 |
| `backend/src/mktkb/observability/evaluation_capture.py:243-265` | 闭集 `CANDIDATE_DROP_REASONS`（含 `filter_miss`）；未知码 = 事件非法（fail-closed） |

### 2.2 `diag` 的采集口（谁真的会拿到这个码）

- 唯一传 `diag=` 的调用：`backend/src/mktkb/qa/service.py:631` 与 `:652`
  （`candidate_unit_ids_for_intent` 内的记录面 / 正文面两次检索），且被
  `capture_enabled()` 门控（`qa/service.py:628-657`、`:658-689`）。
- 该函数的两个调用方：
  - **产品路径**：`backend/src/mktkb/conversations/service.py:2606`（`rag_candidates`）；
  - **评测路径**：`backend/src/mktkb/evaluation/product_adapter.py:1905`（`:1838-1852 _rag_candidate_ids`
    走的是 `candidate_unit_ids`，**不传 diag**）。
- **回答路径不传 `diag`**：`backend/src/mktkb/rag/answer.py:187 result = index.search(plan, limit=limit)`
  —— 函数默认 `diag=None`(`retrieval.py:72` 附近签名)，故**产品答案轮次本身从不产生
  `filter_miss`**。
- 评分路径不读该码：`evaluation/**` 内只有 `p2_diagnostics.py` 的 check 名表，与
  `candidate_dropped_reason` 无关（grep `filter_miss|candidate_dropped` 在 `evaluation/`
  只命中 `p2_diagnostics.py:16-17` 的 check-id 列表，不含本码）。

### 2.3 「联结行只进 `exact` 不进 `fused`」是否造成新的错误归因：**是，但只落在观测码语义层**

机制：`retrieval.py:108-110` 先 `_fuse(index, plan, exact_chunks, …)`，而联结店家行在
`retrieval.py:340-350` 已并入 `exact_chunks`；`_fuse` 内部的 `add()`（`retrieval.py:591-599`）
对每个候选做 `_passes_filters` 判定，店家行没有 `item` 过滤值 ⇒ 必然被丢弃
（`_passes_filters`，`retrieval.py:554-561`：`chunk.filters_norm.get(key) != normalize(value)`）。
于是 `candidates > passed` 成立 ⇒ `diag["filter"]="filter_miss"`。

**实测（`probe_203a_multirow_multipage.py`）**：

| 用例 | `diagnostics["store_join"]` | `diag` |
|---|---|---|
| `test_203a_join_turn_records_filter_miss` | 有（联结生效） | `{"filter": "filter_miss"}` |
| `test_203a_join_disabled_turn_has_no_filter_miss` | 无 | `filter` 键**不存在** |

结论分三层：

1. **产品答案/评测分数**：**无影响**。答案路径不传 `diag`（§2.2），`filter_miss` 只出现在
   观测事件 `retrieval_observed.candidate_dropped_reason(_record/_document)`。
2. **归因语义**：**新增误读面**。同一个码现在既可能表示"用户过滤太紧，把相关行筛掉了"，
   也可能表示"**本批设计使然**：店家行本来就不带 `item`，它被 `_passes_filters` 排除是预期"。
   读数的人若把它当"过滤过紧"的证据，会得到一个**假阳性**根因。
3. **掩盖（更实际的一条）**：`filter_miss` 在优先级里**高于** `dedup_dropped`/`limit_dropped`
   （`qa/service.py:56-63`）。因此一个"既发生联结、又真的被分页上限截断"的轮次，改前记
   `limit_dropped`，改后会被记成 `filter_miss` —— **真实原因被优先级压掉**。这是本批
   **新引入**的诊断退化（同一形态改前 `filter` 键不存在，实测见上表）。

---

## 3. 同门店多行与多页计数（合成数据实测）

数据：`澄江店/样品桌`（物品行）+ 店家资料里 **同一门店两条店家行**
（`T01 合作中`、`T05 暂停合作`，同一份资料、无有效期列 ⇒ 两条都"当前有效"）。
问句固定 `样品桌的位置在哪里，合作状态分别是什么？`
（实测 plan：`mode=record`、`enumerate=true`、`filters=["item"]`、`field_roles=["location","status"]`
、`state_items=["样品桌"]` —— 与任务书的触发条件逐条一致）。

### 3.1 计数

| 场景 | `pagination.total` | `returned` | 渲染行数 | `sources` 条数 | 是否自洽 |
|---|---|---|---|---|---|
| 对照：每店 1 条店家行 | 2 | 2 | 2 | 2（2 份文档） | ✅ |
| **同门店 2 条店家行** | **3** | **3** | **3** | **3**（物品资料 1 + 店家资料 **2**） | ✅ 算术自洽 |
| 改前（关联结入口，同门店 2 行） | 1 | 1 | 1 | 1 | ✅ |
| 多页 `page_size=1`（同门店 2 行） | **3** | 1 | 1 | 1 | ✅ |

- **同一门店有 2 条店家行时，本批会「全部并入」，不是「只取一条」。**
  依据：`retrieval.py:321-331` 只按 `store` 过滤取全部 store 行、无"取最新/取一条"收敛；
  `retrieval.py:340-350` 全量并入；`_enumerate_base`(`retrieval.py:672-691`) 只按
  `record_unit_id or chunk_id` 去重 —— 两条店家行是两个不同记录单元，各计 1。
- **`total` / 渲染行数 / `sources` 三者算术自洽**（3=3=3；`sources` 里同文档出现 2 次，
  是两条不同记录、不同 `source_id`）。
- **多页不重复计入**：`total=3` = 1 物品行 + 2 店家行（每条记录各 1 次），不是 3 页×N。

### 3.2 但有一个**语义不自洽**（算术自洽、事实不自洽）

同门店 2 条店家行时，正文同时出现：

```
- 澄江店：合作状态 合作中（来源：合成合作店家信息.xlsx）（记录 aaabdabb）
- 澄江店：合作状态 暂停合作（来源：合成合作店家信息.xlsx）（记录 dbabfffd）
```

同一门店、同一字段、两个互相排斥的值，靠**只对机器可读的记录指纹**（`answer.py:306-315
_record_marker`）区分；人读到的就是"澄江店合作中、又暂停合作"。任务书点名的
「同门店多条店家行会全部并入未做'取最新'」风险**在本形态下真实成立**，并且不只是"多一行"，
而是**对外呈现出互相矛盾的业务状态**。

### 3.3 多页下的另一处现象（排序把被问字段挤到第 2 页）

`_enumerate_base`（`retrieval.py:687`）按 `(label, entity_key, chunk_id)` 排序；店家行 label
是「澄江店」，物品行 label 是「澄江店的样品桌」⇒ 店家行**排在前面**。`page_size=1` 实测第 1 页：

```
共 3 条，当前第 1 页显示 1 条。
- 澄江店：合作状态 合作中（来源：R203A合作店家信息.xlsx）（记录 eeddeada）
还有更多，可继续查看第 2 页。
```

即**第一页整页是联结进来的店家行，用户问的「位置」在第二页**。改前（无联结）第一页就是物品行。
这是本批在分页形态下的**降级**（不是计数错误）。

### 3.4 最小修法与影响面（不自行改源码，交经理）

| 问题 | 代码位置 | 最小修法（建议） | 影响面 |
|---|---|---|---|
| 同门店多条店家行全量并入 + 状态互相矛盾 | `retrieval.py:321-331`（取行）/ `retrieval.py:340-350`（并入） | 在 `_store_join_chunks` 返回前按"业务键 + 最新版本/最新生效日"收敛为 1 条；若确实多条且值冲突，改为**不并入**并让答案降级为"该门店存在多条记录，无法唯一确定" | 只改联结取数面；`facts.py` 的 `joined_store` 放行仍是"门店值相等"，无需改。单条店家行的 C29 主例不受影响 |
| 多页时店家行挤掉物品行 | `retrieval.py:687` 排序键 | 联结行排在物品行之后（例如排序键加 `is_joined` 位） | 只影响 `total>page_size` 的联结轮次；单页形态逐字不变 |
| `filter_miss` 掩盖 `limit_dropped` | `qa/service.py:56-63` 优先级 或 `retrieval.py:610-612` 记账 | 给联结行单独记一个码（如 `store_join_excluded`），或让 `_fuse` 不对"检索层显式联结行"计丢弃 | 只改观测码；`CANDIDATE_DROP_REASONS` 闭集需同步加码（`evaluation_capture.py:245-256`），否则事件非法 |

---

## 4. 既有失败甄别（改前 / 改后数字）

### 4.1 结论：**本轮没有任何节点失败，甄别不适用**

§1.1 的 11 个节点、共 **87 个用例**（四节点 23 + 104 探针 19 + 邻接回归 32 + 本报告探针 13）
全部 `exit=0`、`failed=0`。
因此**不需要**触发任务书 §4 的"反向应用 patch"分支；也**没有**执行该分支（它要求写
`backend/src/**`，与只读纪律冲突，且当前没有失败需要归因）。

### 4.2 为什么没用 `git archive HEAD` 当"改前"基线：HEAD 不是本批的前一刻

按任务书尝试后实测：`git archive HEAD backend/src` 导出树可用（hash 与工作树不同，见下），
但把导出树插到 `sys.path[0]` 后跑四节点是**大面积红**：

| 节点 | 工作树（改后） | HEAD 导出树 |
|---|---|---|
| `test_r1_102d_turn_pagination.py` | 8 passed, exit 0 | **8 failed**, exit 1 |
| `test_r1_102a_structural_numbers.py` | 9 passed, exit 0 | **collection ERROR**（`ImportError: cannot import name 'P2_PAGINATION_NUMBER_KEYS'`） |
| `test_r1_103_http_structural_numbers.py` | 3 passed, exit 0 | 1 failed + 2 error |
| `test_r1_103_http_scope_and_refusal.py` | 3 passed, exit 0 | 3 error |

原因：**HEAD 早于 R0/R1（102a/102d/103/104 这批）也早于 202C**，三个目标文件在 HEAD 与
工作树之间同时叠着 R0/R1/R2 未提交成果（尺寸差：`retrieval.py` 27260→34458、
`answer.py` 45862→58877、`facts.py` 26249→28961 字节）。所以 HEAD 只能证明"这些节点在新代码上
才有意义"，**不能**隔离 202C。

导出与对照做法（均在仓库外，未改仓库）：

```powershell
git archive --format=zip --output=D:\mktkb-p2-h2v3-r2-20261117\head-src.zip HEAD backend/src
Expand-Archive -Path …\head-src.zip -DestinationPath …\head-src -Force
# 插件 D:\mktkb-p2-h2v3-r2-20261117\headpath\head_src_plugin.py：sys.path.insert(0, HEAD_SRC)
#   并在导入后断言 mktkb.__file__ 落在导出树内（否则报错，避免静默用回 editable .pth）
PYTHONPATH=…\headpath HEAD_SRC=…\head-src\backend\src pytest … -p head_src_plugin
```

（注：`-o pythonpath` 在本环境确实会被 `__editable__.mktkb-0.1.0.pth` 压过 —— 该 `.pth`
把仓库 `backend/src` 写进 `sys.path`，实测 `import mktkb` 指向仓库树，故必须用 `sys.path[0]` 插件。）

### 4.3 因此改前/改后数字用"本批唯一入口关闭"对照（与本批自带敏感性用例同口径）

`retrieval._store_join_chunks` 是本批唯一入口：关掉它，`answer.py` 的身份渲染分支与
`facts.py` 的 `joined_store` 放行全部保持**惰性**（`answer.py:293-303` 读的
`diagnostics["store_join"]` 不再存在），即等价改前行为。202C 自己的
`test_join_entry_sensitivity_restores_red` 用的就是这个口径。

| 指标 | 改前（关联结） | 改后（开联结） |
|---|---|---|
| 对照数据（每店 1 条店家行）`total / returned / 行数 / sources` | **1 / 1 / 1 / 1** | **2 / 2 / 2 / 2** |
| 同门店 2 条店家行 `total / returned / 行数 / sources` | **1 / 1 / 1 / 1** | **3 / 3 / 3 / 3** |
| 正文是否含店家级值（合作状态） | **否**（0 次） | **是**（1~2 次） |
| `diag["filter"]` | **不存在** | **`filter_miss`** |
| 四节点 / 104 探针 | 全部通过（节点不依赖联结是否开启） | 全部通过 |

---

## 5. 出站守卫（零外呼）

| 运行 | 守卫 |
|---|---|
| 102d | 自带 `t09_network_guard`（2 处引用） |
| 103 结构数字 / 103 范围拒答 | 自带 `t09_network_guard`（各 3 处引用） |
| 102a | 纯打分，不建 app、无任何 socket 路径（无 guard，属仓库既有状态） |
| 104 探针（19 例） | 评分侧纯函数；范围侧自带 guard |
| 202C / 202A / R2 回归 | `pytestmark = pytest.mark.usefixtures("t09_network_guard", "no_subprocess")` |
| **本报告两个探针（13 例）** | `pytestmark` 同时挂 `t09_network_guard` + 自建 `no_subprocess`；**每个用例内再显式断言** `t09_network_guard.snapshot()["external"] == []`；`subprocess.Popen/run` 被替换为即抛异常并在 teardown 断言 0 次调用 |

`t09_network_guard` 本体在 `backend/tests/acceptance/support/netguard.py:125-126`：
teardown 断言 `snapshot["external"] == []`（回环单独记账不算外部）。
本报告所有 pytest 运行均 `exit=0`，即守卫断言全部通过：**零外部出站**。

---

## 6. NOT-RUN 与风险

### 6.1 NOT-RUN（明确未验证）

1. **真实链路层（P2 live / holdout run）**：未跑。`value_no_fabricated` / `pagination_*`
   在真实语料上的最终结果需下一次 P2 run。
2. **P1 live run**：未跑（需真实索引 + 模型）。因此"P1 数据集里是否存在会被本批触发
   `value_no_fabricated` pass→fail 的用例"**未确认**（机制已用合成用例固定，见 §1.5）。
3. **C29 真实 case 的 `total` 1→2 复核**：只用合成数据在离线上复现了同形态
   （任务书说 1→2 已实测，本报告不重做真实 case）。
4. **`page_size` 的真实产品配置（默认 10）下的多页**：只测了 `page_size=1`（用
   `object.__setattr__` 修改 frozen `RagConfig`，属探针手段），未跑真实配置的分页翻页链路。
5. **GO/账本/预算槽位**：未读未动。

### 6.2 残余风险清单

| 编号 | 风险 | 严重度 | 依据 |
|---|---|---|---|
| R1 | 同门店多条店家行全量并入 → 同一实体出现互相排斥的状态值，且仅靠记录指纹区分 | **高** | §3.2 实测文本 |
| R2 | 多页形态下联结店家行排在物品行之前，第一页拿不到被问字段 | 中 | §3.3 实测 `page_size=1` |
| R3 | `filter_miss` 在联结轮次新出现，并因优先级压掉 `limit_dropped`（改前该键不存在） | 中 | §2.3 两例对照 |
| R4 | P1 口径不认结构 token；若 P1 存在该形态且金标含旧计数 `1`，本批会造成 pass→fail | 中（未确认是否命中） | §1.5 合成用例 |
| R5 | `pagination` 若未随答案下发则页头数字全部判编造 | 低（当前代码下不可达：页头与 `structured_enumeration` 同生） | §1.3 / §1.4 |
| R6 | `102a` 节点无 netguard（仓库既有状态） | 低（纯打分，无网络路径） | §5 |

### 6.3 需要经理决策的点（固定码）

- **`R2-203A-D1`** — 同门店多条店家行：是否收敛为 1 条（取最新/取生效中），还是允许并列输出
  并在正文显式标注"该门店存在多条记录"？现状对外呈现矛盾状态（§3.2 / R1）。
- **`R2-203A-D2`** — 多页排序：联结店家行是否应排在物品行之后？（§3.3 / R2）
- **`R2-203A-D3`** — 诊断码：是否给"检索层显式联结行被硬过滤排除"单独记码，从而不再让
  `filter_miss` 覆盖 `limit_dropped`？（§2.3 / R3；改动需同步 `CANDIDATE_DROP_REASONS` 闭集）
- **`R2-203A-D4`** — P1 口径是否也接入结构 token（`runner.py` 五处 `score_case`）？若不接，
  需确认 P1 数据集不含该形态（需 live/索引才能定论）。（§1.5 / R4）

---

## 附：本目录产物

```
203A/
├── R2-203A-REPORT.md                      # 本文件
├── R2-203A-SUMMARY.json                   # 机器可读的节点矩阵与关键计数
├── conftest.py                            # 按文件路径加载 backend/tests/conftest.py（零复制夹具）+ 出站/子进程守卫
├── probe_203a_multirow_multipage.py       # 7 passed：对照 / 同门店多行 / 多页 / 改前对照 / diag
├── probe_203a_value_no_fabricated_layers.py # 6 passed：P2 层有出处、无分页则 fail、P1 层口径
└── probe-artifacts/*.json                 # 上述探针的输出快照（正文/分页/sources/plan/diag）
```

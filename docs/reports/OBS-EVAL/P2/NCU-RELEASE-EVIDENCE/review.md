# 任务 3 · N/C/U 正式证据核定 —— 独立复核报告

- 复核角色：全新独立复核窗口（`t3-review`），不参与开发、不改被复核方交付物
- 工作树：`D:/GPT项目/市场部AI知识库`，分支 `codex/p2-e2e`，接手锚点 `97b0066726e5b8d6f94cbc0b63a890084550c106`（复核前后 `git rev-parse HEAD` 一致）
- 复核时间：2026-11-20（Asia/Shanghai）；复核期间任务 1/4 仍在并行改 `backend/src`
- 被复核对象：`docs/reports/OBS-EVAL/P2/NCU-RELEASE-EVIDENCE/`（report.md / manifest.json / evidence/ / scripts/）
- 隔离区：`.tmp-t3review-isolated/`（自建，探针与日志；未写任何被复核方文件）
- 零真实请求：本次复核未发起任何网络/模型/API/OCR/rerank 调用（证据见 §7）

---

## 0. 独立结论

**`PASS-WITH-RESERVATIONS`**

一句话理由：被复核方 24 题的判定、身份绑定、门禁复算、旧版本等价性、U01 重建与 6 条 trace 双计数解释，我都用原始 run 数据独立复现并全部成立，`PARTIAL`（无条件可采 7/8、2/6、9/10，U01 `FAIL`）这一保守结论正确；保留意见集中在**报告措辞两处失准**、**校验器只做形状校验（3 个内容级篡改负例不被拒绝）**、以及**两个 SHA 清单无生成脚本**，均不改变已核定的证据与结论。

> 复核不把 6 条 `RETAINED-OLD` 升级为 clean pass，也不把 U01 升级为 pass。若经理要求"无条件正式可采 = N8/C6/U10"，则当前交付**未达标**，这正是被复核方 `PARTIAL` 的含义。

---

## 1. 复核方法与命令（含退出码）

全部使用 `.\.venv\Scripts\python.exe`（3.12.7 / pytest 9.1.1），未新建 venv、未 pip install。探针脚本均在 `.tmp-t3review-isolated/`，日志在 `.tmp-t3review-isolated/log/`。

零出站闸门：凡导入业务模块或运行 pytest 的探针（#6、#8、#9、#10、#11、#14、#15、#16）都以 `PYTHONPATH=.tmp-t3review-isolated/netgate` 启动，`sitecustomize.py` 在解释器启动时即接管 `socket.connect/connect_ex/create_connection`：**非环回地址一律拒绝并记 `EXTERNAL`，环回放行并单独记账**；纯 sqlite/JSON 只读探针（#1–#5、#7、#17–#19）不导入任何网络库（静态审计确认），且同样受 #15 的脚本级静态审计覆盖。

| # | 命令 | 退出码 | 关键输出 |
| --- | --- | --- | --- |
| 1 | `python -X utf8 .tmp-t3review-isolated\p01_inventory.py` | 0 | 原始 trace/rag/product 库存在；`rag_meta`：R1 `revision=12 product_revision=11`、R2 `4/3`、R4 `6/5` |
| 2 | `python -X utf8 .tmp-t3review-isolated\p02b_binding_fields.py` | 0 | 6 条仅 `index_revision` 不等；其余 6 字段全等；对照组 9 条全等 |
| 3 | `python -X utf8 .tmp-t3review-isolated\p03_census.py` | 0 | 全 57 条 trace 严格按"有无 `recall` span"二分：27/27、2/2、2/2 命中 RAG 计数，0 条例外 |
| 4 | `python -X utf8 .tmp-t3review-isolated\p04_u01.py` | 0 | `sha256(chunk_id)[:16]=504e0ea7f4b1c86f`；chunk→`072d28f2…`→`sheet:物品位置:row:8`；evidence 同单元 v2/published；`retrieved=[]` |
| 5 | `python -X utf8 .tmp-t3review-isolated\p05_sources_standards.py` | 0 | `sources` 1 条（同 unit）；批准/冻结 `p2_standards` 全字段 |
| 6 | `python -X utf8 .tmp-t3review-isolated\p06_gate_recompute.py` | 0（脚本）；内层门禁 R1/R2/R4 均 **1** | R1 `trace_integrity fail 27`；R2 `citation_required fail U01`、`conflict_not_rejected fail C05`、`trace_integrity fail 2`；R4 `security_leak pass`、`conflict_not_rejected pass`、`trace_integrity fail 2` |
| 7 | `python -X utf8 .tmp-t3review-isolated\p07_compare_delivered.py` | 0 | 逐门禁状态/失败集合与交付 `evidence/gate_recompute.json` **`diffs {}`**；`original_sha256` 逐键相等 |
| 8 | `python -X utf8 .tmp-t3review-isolated\p08_config_equivalence.py` | 0 | `d1097573…` / `7fa6f47a…`；7 类语义键全同；差异恰好 6 条路径 |
| 9 | `python -X utf8 .tmp-t3review-isolated\verify_manifest_copy.py <真实 manifest.json>` | 0 | `{"ok": true, "cases": 24, ...}`（副本 SHA 与原脚本逐字节相同 `69928f83…`） |
| 10 | `python -X utf8 .tmp-t3review-isolated\p10_negative_tests.py` | 0（脚本） | A1–A6 全部 exit 1 且原因码正确；B1/B2/B5 **exit 0**（见 §6） |
| 11 | `python -X utf8 .tmp-t3review-isolated\p09_manifest_audit.py` | 0 | 24 题逐字段对原始工件 0 错误；tallies 与 runs 身份全对 |
| 12 | `python -X utf8 .tmp-t3review-isolated\p11_applicability.py` | 0 | 24 题 `retrieved` 均空；`pagination` 均空、无 `filters`；`stratum` 无 `exact`（范围外的 R2.C05 `retrieved=1`） |
| 13 | `python -X utf8 -m pytest backend/tests/acceptance/test_t09_mutation.py -q --collect-only` | 0 | `13 tests collected`，名称与 `u-controls.json` 13 条逐字一致 |
| 14 | `python -X utf8 -m pytest backend/tests/acceptance/test_t09_mutation.py -q` | **0** | **`13 passed, 1 warning in 21.13s`**（被复核方报 21.25s） |
| 15 | `python -X utf8 .tmp-t3review-isolated\p14_static_and_sums.py` | 0 | 8 个脚本 0 个网络库导入；`SHA256SUMS` 15/15 命中 |
| 16 | `python -X utf8 .tmp-t3review-isolated\p15_run_numbers.py` | 0 | 117/40/0.289440、9/1/0.020004、10/0/0.056064；合计 136/41/0.365508 |
| 17 | `python -X utf8 .tmp-t3review-isolated\p16_artifact_hashes.py` | 0 | `artifact-hashes.json` 46/46 全部命中真实文件 |
| 18 | `python -X utf8 .tmp-t3review-isolated\p17_manifest_gates.py` | 0 | 24 题 `applicable` 与 `adopt` 全一致，0 问题 |
| 19 | `python -X utf8 .tmp-t3review-isolated\p18_path_census.py` | 0 | 41 条非 `rag` 路径 answer 的 `retrieved` 全非空；唯一 `rag` 路径 answer（U01）为空 |
| 20 | `python -X utf8 .tmp-t3review-isolated\p19_question_hash.py` | 0 | 抽样 6 题 `trace.question_hash == sha256(冻结题干)`，`question_chars` 相等 |

**失败过的尝试（如实披露）**：`p04` 首版因产品库 `source_units.id` 为 32 位无连字符 UUID 而 `TypeError`（exit 1，我的脚本 bug，已修正）；pytest 首跑因我的网络闸门**连环回也拒绝**，导致 `asyncio` 的 `socketpair` 失败（13 errors，exit 1），改为"环回放行、非环回拒绝"后 `13 passed`（exit 0）。两次都不涉及被复核方数据。

---

## 2. 逐项复核表

| 事项 | 我的方法 / 命令 | 实际输出 | 与被复核方一致？ | 我的判定 |
| --- | --- | --- | --- | --- |
| HEAD / 分支 | `git rev-parse HEAD`、`git branch --show-current` | `97b00667…` / `codex/p2-e2e` | 一致 | 通过 |
| 三个 run 的 `index_revision` 绑定值 | 直读 `run_manifest.json` | R1 11 / R2 3 / R4 5 | 一致 | 通过 |
| `rag_meta.revision` / `product_revision` | 直读原始 `rag-index.sqlite3`（非交付副本） | R1 12/11、R2 4/3、R4 6/5 | 一致 | 通过 |
| 6 条 trace 的 `trace.index_revision` | 直读原始 `qa-traces.sqlite3` | N01/C01/C02=12、U01=4、C05/C06=6 | 一致 | 通过（机制成立，见 §3） |
| 6 条其余绑定字段 | 逐字段比对 trace↔run_manifest↔cases | `run_id/config_hash/manifest_sha256(`→`corpus_manifest_sha256)/dataset_version/pipeline_version/question_hash` **全等** | 一致 | 通过 |
| 对照组 9 题 | 同上 + span 判定 | N02–N07、C03、C04、N08：trace=manifest 且**无 recall span** | 一致 | 通过 |
| 全 run 分布（超范围加固） | 57 条 trace 全量普查 | 27/25、2/0、2/1 严格二分，0 例外 | 报告未列，独立补强 | 通过 |
| `_TRACE_BINDING` 定义 | 读 `gate.py:261-269` | 含 `("index_revision","index_revision")`，`manifest_sha256→corpus_manifest_sha256` | 引用行号准确 | 通过 |
| 写入点 | 读 `rag/retrieval.py:49/175-176`、`rag/answer.py:291` | `start_revision=index.revision()`；`annotate_trace(index_revision=…)`；`hash_ref(citation.source_id)` | 引用行号准确 | 通过 |
| U01 `unit_id_hash` | 独立重算 + 全库反查 | `504e0ea7f4b1c86f` 只命中 chunk `a202ff9b…`，不命中任何 unit/record_unit | 一致 | 通过（是 chunk 哈希） |
| U01 chunk→unit | 直读 R2 rag 库 | `record_unit_id=072d28f2…`，`unit_key=sheet:物品位置:row:8`，文本含 P01/城东店/B区1号货架第二层 | 一致 | 通过 |
| U01 产品证据 | 直读 R2 product 库 + cases | `unit_id` 同单元（32 位形式），`version_number=2`，`state=published`，回答含期望值 | 一致 | 通过 |
| U01 `retrieved` | 直读 cases | `[]`；同 run C05=1、R1 Q01=1 | 一致 | 通过 |
| `retrieved` 空的成因（加固） | 全 57 条 trace（answer/not_found/clarification/conflict）按 path 统计 | 41 条非 `rag` 路径 answer **全部非空**；唯一 `rag` 路径 answer 为空 | 报告未展开 | 补强：路径相关缺陷 |
| 八门禁复算 R1/R2/R4 | 自建隔离副本 + 批准门槛 `7fa6f47a` | R1/R2/R4 exit=1；失败集合与交付**完全相同** | 一致 | 通过 |
| 逐题评分状态 | `score_run` 重算 vs 既有 `case_scores.json` | R1 52/52、R2 2/2、R4 3/3 `status_diffs {}` | 一致 | 通过 |
| 旧版本等价性 | 文件 SHA + 规范化哈希 + `load_p2_gate_config` | `3af301db…/d1097573…`、`b1094cc7…/7fa6f47a…`；7 类语义键全同；差异恰为 `status`、`approval`、`p2_standards.status/approved_at/basis`、`notes` | 一致 | 通过 |
| 清单内容 | 24 题逐字段回源审计 | 0 错误；tallies 7/2/9、1/4/0、0/0/1 全对；run 身份全对 | 一致 | 通过 |
| 校验器 | 逐字节副本跑真实清单 | `{"ok": true, "cases": 24}`，exit 0 | 一致 | 通过 |
| 6 类负例 | 独立重造 6 个负例 | 全部 exit 1，原因码 `WRONG_BINDING/DUPLICATE_CASE+SAMPLE_INSUFFICIENT/U_TYPE_MIXED/MISSING_TRACE/MISSING_CITATION_EVIDENCE` 全对 | 一致 | 通过 |
| 我新增负例 | 6 个新负例（3 个"应被拒"控制项 + 3 个内容级篡改探测） | 3 个被拒（B3/B4/B6），3 个**未被拒**（B1/B2/B5） | 报告未覆盖 | **保留意见 R2** |
| 零请求 | 静态审计 + 启动即接管 socket + 全量记账 | 8 脚本 0 网络库；探针/pytest 记账只有环回，**0 条 EXTERNAL** | 一致 | 通过 |
| 原件未改 | T207 84 文件 SHA 前后对照（+ `PM/` mtime、全树 mtime）；`artifact-hashes.json` 46 键回源 | **84/84 相同**；无 T207 文件 mtime ≥ 22:40；**46/46 命中** | 一致 | 通过 |
| 交付自身完整性 | `SHA256SUMS` 校验 | 15/15 命中 | 一致 | 通过 |
| `backend/src`、`backend/tests`、`docs/evaluation` 未被被复核方改 | 脚本静态写入面 + mtime 窗口 + git status | 脚本 0 处写这些路径；`docs/evaluation` 在 22:43–22:52 窗口内 0 文件变更；`backend/src` 在该窗口有任务 4 的并发写入（见 §9） | 部分一致 | **PARTIALLY-VERIFIED** |

---

## 3. 六条 trace 逐条复核（重点）

### 3.1 我的独立读数

数据源是**原始 run 目录**（`D:\mktkb-p2-run\t207\R{1,2,4}\data\...`），不是被复核方的隔离副本。下表的 `trace_idx` / `rag_meta` / `product_rev` / `manifest_bind` 都是我自己查询的结果。

| 选题 | trace_id（前 8） | 路径 / spans 关键项 | trace_idx | rag_meta.revision | product_rev | manifest_bind | 其余 6 字段全等 | 判定 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| N01 | `44f97217` | `legacy`，含 recall/fuse/retrieve | **12** | 12 | 11 | 11 | 是 | 接受解释，门禁仍 fail |
| C01 | `32f8df96` | `legacy_with_rag_candidates`，含 recall/rerank | **12** | 12 | 11 | 11 | 是 | 同上 |
| C02 | `bdbe4e54` | `legacy_with_rag_candidates`，含 recall/rerank | **12** | 12 | 11 | 11 | 是 | 同上 |
| U01 | `edacbdb8` | `rag`，parse→recall→answer→fact_validate→commit | **4** | 4 | 3 | 3 | 是 | 同上 |
| C05 | `321b0a5f` | `legacy_with_rag_candidates`，含 `entity_conflict_check` | **6** | 6 | 5 | 5 | 是 | 同上 |
| C06 | `397a49ba` | `legacy_with_rag_candidates`，含 `entity_conflict_check` | **6** | 6 | 5 | 5 | 是 | 同上 |

- "其余 6 字段"= `run_id`、`config_hash`、`manifest_sha256`（trace 侧对应 manifest 的 `corpus_manifest_sha256`）、`dataset_version`、`pipeline_version`、`question_hash`。全部逐条相等；`question_hash` 还可由冻结题干独立重算（`sha256(question)` 命中，`question_chars` 相等），不是简单抄 cases.jsonl。
- 对照题（N02–N07、C03、C04、N08）9/9：`trace.index_revision` 分别 11/11/11/11/11/11/11/11/5，与 manifest 全等，且 span 中**没有** `recall`。

### 3.2 全 run 普查（比"6 条"更强的检验）

我把三个 run 的**全部 57 条 trace**逐条对照"是否有 `recall` span"：

| run | trace 总数 | 有 recall | 无 recall | 有 recall 且 idx=rag 计数 | 无 recall 且 idx=manifest | 违例 | 除 idx 外绑定不一致 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| R1 | 52 | 27 | 25 | **27/27** | **25/25** | 0 | 0 |
| R2 | 2 | 2 | 0 | **2/2** | — | 0 | 0 |
| R4 | 3 | 2 | 1 | **2/2** | **1/1** | 0 | 0 |

这条二分在 57 条上零例外，说明差异**只**由"是否执行 RAG 检索"决定；如果是错绑到别的 run/索引，不可能只在 retrieval 路径上整齐出现，更不可能让未检索题保留 11/5。

### 3.3 该解释是否足以排除"trace 被错绑到别的 run/索引"

**我的判断：足以排除"错绑到别的 run"，但不足以证明该字段在冻结契约下"正确"。**

理由（不附和、分两层）：

1. **排除错 run**：trace 不能属于别的 run —— `run_id/config_hash/corpus_manifest_sha256/dataset_version/pipeline_version` 五个 run 级身份全等，且题干哈希可由冻结题干重算。R1 trace 库恰好 52 行 = `case_count=52`，没有外来行。
2. **排除错索引**：`index_revision` 只是整数，单看无区分力（12/4/6 都可能被伪造）。但三件事同时成立：(a) 三个 run 的 `rag_meta.revision` 恰好是 12/4/6，与 6 条 trace 值逐条相等；(b) 未检索题保留 11/3/5；(c) 全 57 条严格二分。若 trace 被绑到"别的索引"，该索引的 revision 不会恰好等于本 run 静止态 `rag_meta.revision`，也不会在"未走检索"时退回 manifest 值。**故"trace 值来自本 run 的 RAG 索引计数"是唯一与全部观测相容的解释。**
3. **但不能据此升级为 pass**：冻结的 `_TRACE_BINDING` 要求 `trace.index_revision == manifest.index_revision`，6 条确实不满足；`T209 attempt2` 报告把同一现象定性为"运行接线的一致性缺陷"（24/40 全对应 RAG 分支），`attempt3` 的修复是**把 manifest 绑定改到 12 使两侧相等**，不是宣布"双计数合法"。所以"按设计不同"只是对两个计数器为何不同的解释，不是对门禁失败的豁免。被复核方把 6 条标 `RETAINED-OLD` 而非 pass，方向正确。

### 3.4 代码路径核对

- `_TRACE_BINDING`：`backend/src/mktkb/evaluation/gate.py:261-269`，逐字段 `str(actual) != str(expected)` → `version_binding`（同文件 `:1874-1898`）。
- 写入点：`backend/src/mktkb/rag/retrieval.py:49` 取 `index.revision()`（读 `rag_meta.revision`），`:175-176` `annotate_trace(index_revision=str(start_revision))`；该调用在 `search()` 内，只有走 RAG 检索才会执行。
- 产品 revision：`rag/index.py:161-182` 是 RAG 索引自身计数；`qa/service.py:308-313` `product_revision()` 读 `get_revision(db)`（KnowledgeState），`qa/service.py:376-379` 更直接把 `product_revision` 与 `index_revision` **并列打印**，是"两套计数器"最干净的代码证据（报告未引用这一处）。
- 报告引用的 `qa/service.py:935` 实际是 `manifest_summary()` 的返回字段，不是产品响应构造点；结论仍成立（`product_adapter.py:1632/1661` 用 `self.product_revision()` 绑定 run 身份），但该行号属于**弱引用**（见 §8-R5）。

---

## 4. U01 定性

### 4.1 重建链（全部独立命中）

| 环节 | 我的读数 | 结论 |
| --- | --- | --- |
| `trace.citation_refs_json[0].unit_id_hash` | `504e0ea7f4b1c86f` | — |
| `sha256(rag_chunks.chunk_id='a202ff9b372dc1d919ca73a698c84c38')[:16]` | `504e0ea7f4b1c86f` | **命中且唯一**（全库无 unit/record_unit 的哈希等于它） |
| chunk | `kind=record`、`revision=3`、`record_unit_id=072d28f2-b403-4af3-9fe9-31b9e8714dbf` | 成立 |
| rag unit | `unit_key=sheet:物品位置:row:8`、`sheet=物品位置`、`row_number=8`、文本 `标识: P01 … 位置: B区1号货架第二层` | 成立 |
| 同轮 product.evidence[0] | `unit_id=072d28f2…`、`unit_key=sheet:物品位置:row:8`、`version_number=2`、`state=published`、`verified=true` | 同一逻辑单元 |
| 回答文本 | `根据资料，城东店的宣传海报的位置：B区1号货架第二层。` | 含期望值 |
| 同轮 `retrieved` | `[]`（而 `sources=1`、`evidence=1`） | 字段空 |
| 对照 | R2.C05 `retrieved=1`；R1.Q01 `retrieved=1` | 同 run/同批非空 |

补充加固：全 57 题按 `trace_path` 统计，**41 条非 `rag` 路径的 answer 全部有非空 `retrieved`**，唯一 `path="rag"` 的 answer（U01）为空。说明这不是随机缺字段，而是 `rag` 打包路径特有的响应形状问题。

### 4.2 定性

**`citation_required` 的 FAIL 是"字段缺失（同轮 `product.retrieved` 为空）"，不是"引用内容错误"。**

- 门禁实现（`gate.py:1689-1710`）：`evidence_units` 来自 `outcome.retrieved[].unit_ids`；`cited_units` 来自 `outcome.citations[].unit_ids`（`citations` 由 `product.sources` 构造，见 `p2_scoring.py:537-544`）；`retrieved=[]` → `evidence_units` 为空 → 引用的 unit 全部"落在证据外" → `citation_not_in_evidence`。
- 引用本身真实、可 1:1 对回同一单元、且在同轮 `product.evidence` 中；所以**不是编造/跨题引用/引用错内容**。
- 但它也不是"门禁误报可忽略"：门禁口径是"引用必须落在本轮 retrieved 内"，`retrieved` 为空意味着本轮检索证据集**未被记录**，按"硬门禁不可豁免"只能 fail。正确说法是"**可解释的字段缺失导致机械失败**"。

### 4.3 对 U 组 10/10 门槛的影响

- 评分判定层：U01 的逐题 `status=pass`（我复算与 `case_scores.json` 一致），所以"判定通过 U 10/10"成立。
- 正式可采层：U01 有 `citation_required`（+`trace_integrity`）双失败，`p2_standards.update_delete.min_pass=10` 是**目标值**而非可豁免阈值，硬门禁不可 waive。因此**无条件正式可采只有 9/10，U 组未达"10/10 clean"**。
- 被复核方 `PARTIAL` + "U01 保留 FAIL" 的处置正确；除非经理批准修契约/回填 `retrieved`（无需真实请求）或另签 U01 新 GO 重跑，否则不得把 U01 计入 10/10。

---

## 5. 八项硬门禁适用性（我的独立判定）

复算口径：批准门槛 `gate_v0_3_approved.json`（文件 `b1094cc7…`，加载摘要 `7fa6f47a…`），隔离副本只改 `trace_store/dataset_path`；原始件 SHA 前后未变。

| # | 门禁 | 我的独立判定 | 依据（我实测） | 与报告一致？ |
| --- | --- | --- | --- | --- |
| 1 | `security_leak` | 部分适用：仅 R4.C05/C06 | 24 题里只有这两题有 `forbidden_sources`（V03/V06）；门禁 pass、0 违规。R2.C05 也适用（V03）但不在冻结范围 | 一致 |
| 2 | `cross_entity` | **不适用** | case 契约无 `filters`/entity key；24 题 `retrieved` 中无任何 `hard_filter_violation`；门禁只认上游该信号 | 一致（且报告明确"不能声称已通过"，正确） |
| 3 | `stale_bypass` | **不适用** | 无 `include_future/as_of/effective_from/effective_to`；无 `hard_filter_violation=stale` | 一致 |
| 4 | `conflict_not_rejected` | 部分适用：仅 R4.C05/C06 | 只有两题 `expected_kind=conflict`，均 pass（返回 conflict）；C01–C04 是 `clarification`，不适用；R2.C05 在范围外 fail（返回 answer） | 一致 |
| 5 | `exact_value_contract` | **不适用（对这 24 题）** | 24 题 `stratum` ∈ {negative, ambiguity_conflict, mutation}，无 `exact`；R1 run 级该门禁为 pass 是因为 Q01–Q24 在 run 内，不影响这 24 题 | 一致 |
| 6 | `pagination_contract` | **不适用** | 24 题 `expected_pagination` 全 `None` 且 `outcome.pagination` 全空（门禁 `if not expected and not actual: continue`） | 一致 |
| 7 | `citation_required` | 部分适用：仅 U01 | 只有 U01 `kind=answer`；N 为 not_found、C 为 clarification/conflict → 不适用；U01 **FAIL**（见 §4） | 一致 |
| 8 | `trace_integrity` | 部分适用：15 条 R 口径 | 15/15 有 trace；**9 pass / 6 fail**（`version_binding`）；U02–U10 无 run/trace → 不适用 | 一致 |

**我对四项"不适用"的结论**：`cross_entity`、`stale_bypass`、`exact_value_contract`、`pagination_contract` 判"不适用"**合理**，因为按"数据集没有该类 case → not_applicable"的既定口径，这 24 题确实没有可判定输入。但必须保留报告已写明的限制：**"不适用" ≠ "已通过"**；N/C 组语义上关心跨实体与过期，当前契约无字段可判，属**未覆盖**，不能当作 N/C 组在这两项上已验收。`exact_value_contract` 在本批 24 题确实不适用，但 R1 的 Q01–Q24 已由 run 级门禁单独覆盖（pass），两者不要混为一谈。

---

## 6. 负例与校验器

### 6.1 真实清单

`verify_manifest.py`（逐字节副本，SHA `69928f83…`）对真实 `manifest.json`：`{"ok": true, "cases": 24, "tallies": {...}}`，**exit 0**。

### 6.2 被复核方报告的 6 类负例（我独立重造）

| 负例 | 期望码 | 实际输出（我的运行） | exit | 一致？ |
| --- | --- | --- | --- | --- |
| 错绑定（N02 `plan_sha256`→全 0） | `WRONG_BINDING` | `["WRONG_BINDING:N02:plan_sha256"]` | 1 | 是 |
| 重复选题（复制 N02） | `DUPLICATE_CASE`+样本数 | `["SAMPLE_INSUFFICIENT:N:expected=8:actual=9","DUPLICATE_CASE:N02"]` | 1 | 是 |
| U 类型混用（U05 `basis=R`+R2 run_id） | `U_TYPE_MIXED`+绑定 | `["U_TYPE_MIXED:U05:R_basis_with_local_control_fields","WRONG_BINDING:U05:plan_sha256",…,"MISSING_TRACE:U05"]` | 1 | 是（报告为截取） |
| 样本不足（删 C06） | `SAMPLE_INSUFFICIENT` | `["SAMPLE_INSUFFICIENT:C:expected=6:actual=5"]` | 1 | 是 |
| 缺 trace（N03 `trace_id=null`） | `MISSING_TRACE` | `["MISSING_TRACE:N03"]` | 1 | 是 |
| 缺引用（删 U01 `source_hit`+门禁项） | `MISSING_CITATION_EVIDENCE` | `["MISSING_CITATION_EVIDENCE:U01","MISSING_CITATION_EVIDENCE:U01:source_hit"]` | 1 | 是 |

### 6.3 我新增的负例（6 个）

| 编号 | 构造 | 期望 | 实际 | exit | 结论 |
| --- | --- | --- | --- | --- | --- |
| B1 | N05 `question_sha256` 改成**另一个合法 64 hex** | 应拒绝 | `{"ok": true, "cases": 24}` | **0** | **未被拒（校验器只查长度）** |
| B2 | N02（ADOPTED）`evidence_paths.run_cases` 指向不存在文件 | 应拒绝 | `{"ok": true, "cases": 24}` | **0** | **未被拒（不校验路径存在性）** |
| B3 | U01 `adopt=ADOPTED`（其 `citation_required`+`trace_integrity` 均 fail） | `ADOPT_INCONSISTENT` | `["ADOPT_INCONSISTENT:U01:adopted_with_gate_fail=['citation_required','trace_integrity']"]` | 1 | 正确拒绝 |
| B4 | C03 `question_sha256="abc"` | `WRONG_BINDING` | `["WRONG_BINDING:C03:question_sha256"]` | 1 | 正确拒绝 |
| B5 | N02↔N03 **互换 trace_id** | 应拒绝 | `{"ok": true, "cases": 24}` | **0** | **未被拒（不与 trace 库交叉核对）** |
| B6 | C04 `index_revision_binding=99` | `WRONG_BINDING` | `["WRONG_BINDING:C04:index_revision_binding"]` | 1 | 正确拒绝 |

**判断**：被复核方声称的 6 类负例全部成立；但我新增的 B3/B4/B6 说明校验器能拦住"结构/内部一致性"篡改，B1/B2/B5 说明它**拦不住内容级篡改**（合法 hex 的题干哈希、幽灵证据路径、trace_id 互换）。这不是数据错误——我已用 `p09_manifest_audit.py` 对真实清单做了内容级回源，24 题 0 错误（`question_sha256`、`trace_id`、product revision、trace path/outcome、rag/product 计数全部命中），所以**清单内容可信，校验器覆盖面不足**。见 §8-R2。

---

## 7. 零请求与原件保护

### 7.1 零出站

| 证据 | 内容 |
| --- | --- |
| 交付脚本静态审计 | 8 个脚本 `net_imports=[]`；只有 `gate_recompute.py` 导入 `socket` 且用途是**拒绝**网络；`negative_tests.py` 仅 `subprocess` 调本地 `python verify_manifest.py`；0 处 `http(s)://`、`requests/httpx/urlopen` |
| 我的网络闸门 | `sitecustomize.py` 在解释器启动时替换 `socket.socket.connect/connect_ex/create_connection`；非环回→拒绝并记 `EXTERNAL`。导入业务模块的探针（p06/p08/p09/p10/p11/p14/p15/p16）运行期日志只有 `netgate_loaded`（0 次 connect）；pytest 复跑记账 **301 次环回、0 次 EXTERNAL**（环回来自 `asyncio.socketpair`）。 |
| 验收测试自带闸门 | `backend/tests/acceptance/support/netguard.py`（SHA `7d5cb32a…`）由模块级 `pytestmark` 强制；`13 passed` 等价于 `external=[]` |
| 我未做的事 | 未调用任何 provider/API/模型/OCR/rerank；未申请/使用 GO；未启动服务；未对真实 run 重跑产品 |

### 7.2 原件保护（SHA 前后对照）

- **T207 历史证据**：复核开始时对 `docs/reports/OBS-EVAL/P2/T207/`（不含 `PM/` 子目录）全部 84 个文件做 SHA-256 快照，结束时重算：**84/84 完全相同**（`Compare-Object` 无差异）。`PM/` 17 个文件未纳入逐字节快照，但其 mtime 全部 ≤ 2026-11-12；且全 T207 树（101 文件）中**没有任何文件 mtime ≥ 2026-11-20 22:40**，说明 NCU 窗口（22:43–22:52）与本复核窗口内该目录整体未被写过。

| 抽样文件 | 复核前 = 复核后 |
| --- | --- |
| `T207/report.md` | `7bb926b5bbe2809dee9f195e4ae66d19172d3d81c7179fb5388676091dbc442f` |
| `T207/cases/R1.jsonl` | `e44ab9ffd89ff32e846f3e895419f7580033e43041c4468baf05e22e44333c11` |
| `T207/cases/R2.jsonl` | `d5fb8cacac7b2d000fbe783a3cef0b6c9cf0154a330b4cfd95b5dc9a35691388` |
| `T207/cases/R4.jsonl` | `c04b67c6f8a44c09eaa3c4fc56a6ceb8dc97ac7665aea6ed92ef0ea01897fd84` |
| `T207/scoring/u-controls.json` | `11b1679f9c38a97d16918d1f5ace275fa8b71712857009327211dd3ef2dd243e` |
| `T207/scoring/R1-fixed/case_scores.json` | `d22156becd06cddcb20a860e482a2499229bce21c0e72abcbcf114ac8fd3daf4` |
| `T207/scoring/R2-fixed/case_scores.json` | `410efbef275501b82de2b7770c252f181712daaff8f41505d60473136e09af47` |
| `T207/scoring/closeout/verification.json` | `4a1b1ad9e46f52f861802e381f92e0d5ea4beff66db6487b8c4ce182dac43355`（`artifact-hashes.json` 记录值，回源命中） |

- **原始 run 数据**：R1/R2/R4 的 trace/rag/product 库与 cases/summary/manifest/dataset，共 21 份，复核前后 SHA **21/21 相同**（`p06_gate_recompute.json` 的 `originals_unchanged` 全 true）——我的门禁复算只读原库、在自建副本上写诊断副本。
- **交付自身**：`evidence/artifact-hashes.json` 46 个键逐一对真实文件回源：**46/46 命中**；`SHA256SUMS` 15/15 命中。说明交付件与它记录的哈希自洽。
- **`docs/evaluation/`**：`gate_v0_3.json` mtime `2026-11-10 21:27`、`gate_v0_3_approved.json` mtime `2026-11-20 08:07`（批准任务，均早于 NCU 窗口 22:43–22:52），窗口内该目录 0 文件变更；两文件 SHA 与交付记录一致。
- **`backend/src`、`backend/tests`**：见 §9 的"PARTIALLY-VERIFIED"。

---

## 8. 我不认同被复核方的地方（逐条）

- **R1（措辞失准，必须改）**：report §7 "无产品执行｜未启动服务、**未执行产品代码路径**"与 §4/§12 自相矛盾。`pytest backend/tests/acceptance/test_t09_mutation.py` 会通过 `TestClient` 在进程内拉起完整产品应用、执行解析/入库/检索/问答代码（我复跑 `13 passed` 即执行了产品代码路径）。正确表述应是"**未对生产数据/真实 provider 执行产品；本地 L 口径验收在进程内启动产品应用（Mock/替身 provider）**"。"未启动服务"（无网络监听）成立。
- **R2（校验器覆盖不足，建议补）**：`verify_manifest.py` 只做"样本数/唯一性/内部字段相等/长度=trace 存在/引用字段存在/采纳一致"，**不回源 trace 库或 cases**。因此 B1（合法 64 hex 的题干哈希篡改）、B2（ADOPTED 幽灵证据路径）、B5（trace_id 互换）都不被拒。report §10.2 复核清单第 1 条写了"能在 trace 和 run cases 中同时命中"，但该能力**不在交付的校验器里**。建议补：`question_sha256` 与 `trace.question_hash`/`cases.jsonl` 三方比对、`trace_id` 与 trace 库存在性/run_id 比对、`evidence_paths` 存在性。
- **R3（可复现性小缺口）**：`evidence/artifact-hashes.json` 与 `SHA256SUMS` 在 8 个交付脚本中**没有生成者**（只有 `prepare_isolated.py` 消费 `artifact-hashes.json`）。它俩目前只能视为"手工/未交付脚本生成"，与 report §12 的复现顺序不闭合。
- **R4（"按设计"措辞）**：report §2.1 "两个计数器**按设计**不同"事实成立（RAG 计数 vs 发布计数），但"按设计"容易被读成"门禁失败是预期"。`T209 attempt2` 把同一现象定性为"运行接线的一致性缺陷"，冻结契约 `_TRACE_BINDING` 仍要求相等。建议改为"两套计数器客观不同；冻结契约却把二者当同一字段，属接线/契约缺陷"。
- **R5（弱行号引用）**：report §2.1 引 `qa/service.py:935` 作为"产品响应 revision 取 manifest.revision"的证据，该行实际是 `manifest_summary()`。结论仍由 `product_adapter.py:1632/1661` 与实测（product revision = 11/3/5）支撑；更干净的证据是 `qa/service.py:376-379`（`product_revision` 与 `index_revision` 并列）。
- **R6（对照表述含糊）**：report §3.2 "同 run 的 C05 与 R1 的 Q01，`retrieved` 均有 1 条"——R2.C05 是 1 条，但 R4.C05 是 0 条；应写明"R2.C05"，否则读者会拿 R4.C05 对照而得出相反结论。
- **不构成不同意、但需提醒的呈现风险**：§5 表"判定通过 U 10/10"是**评分层**；U01 的硬门禁 FAIL 意味着**正式可采层 9/10**。报告 §5/§13 已写保守口径，但顶层数字容易被误读为"U 已 10/10 达标"。

---

## 9. 未能验证的事项（`NOT-VERIFIED`）

| 事项 | 状态 | 原因 |
| --- | --- | --- |
| 被复核方 `.tmp-ncu-isolated/` 内副本的逐份 SHA、以及其诊断副本"只改 `trace_store/dataset_path`" | `NOT-VERIFIED` | 该目录已被自清，原件不在。**但**：交付的 `gate_recompute.json.original_sha256` 与我对原件的独立计算逐键相同，且我在**自己的副本**上重算得到完全相同的门禁结果，等价结论已由独立路径证实。 |
| "固定文件未漂移（预算账本/GO 文件）" | `NOT-VERIFIED` | 预算账本与 `P2-LIVE-GO` 不在本任务可写/可读范围（且可能 git 忽略），本次未打开。 |
| "开始时 452 条 `git status --short`" | `NOT-VERIFIED` | 我接手时观测到 497 条（任务 1/4 的并发改动已在内），无法回溯被复核方开始时的计数；该数字不影响证据结论。 |
| `backend/src/**`、`backend/tests/**` 在 NCU 窗口内"未被被复核方修改" | `PARTIALLY-VERIFIED` | 8 个交付脚本静态审计 0 处写入这些路径；`docs/evaluation` 窗口内 0 变更；但 `backend/src/mktkb/evaluation/` 下多处文件在 **22:46–22:58**（与 NCU 窗口 22:43–22:51 重叠）被**并行窗口写入**，其中 `cli.py` 与 `p2_release_*` 属任务 4 声明范围，`p2_evidence_rescore.py`/`p2_hard_evidence.py` 的写入归属无法判定。并发写入不可归因，只能说不存在"被复核方写入"的正面证据。 |
| `u-controls.json` 由其历史生成器现场重算 | `NOT-VERIFIED`（部分替代） | 未交付生成脚本；我改为校验 `u-controls.json` SHA（`11b1679f…` 与历史 `verification.json` 记录一致）+ 重跑同一测试文件得 `13 passed`，名称与 13 条逐字对应。 |
| H2 / R3 / B0 组 | 不在复核范围 | 按任务书只核 N/C/U。 |

---

## 10. 最终判定摘要

| 项 | 被复核方 | 我的独立复核 |
| --- | --- | --- |
| 判定通过 | N 8/8、C 6/6、U 10/10 | **一致**（评分层逐题状态 `diffs {}`） |
| 无条件正式可采 | N 7/8、C 2/6、U 9/10 | **一致** |
| 有条件保留 | 6 条 `RETAINED-OLD` | **一致**（6/6 解释成立，但不得升级为 pass） |
| `FAIL` | U01（`citation_not_in_evidence`） | **一致**（字段缺失，非内容错误） |
| 八门禁 | 适用性表 | **一致**（四项"不适用"合理，但不得当"已通过"） |
| 旧版本等价性 | 语义键全同、差异仅 4 类 | **一致**（差异 6 条路径，属 4 类） |
| 零请求 | 0 | **一致**（静态 + 运行时闸门，EXTERNAL=0） |
| 原件保护 | 未改 | **一致**（T207 84/84、run 数据 21/21、delivery 46/46 + 15/15） |

**结论：`PASS-WITH-RESERVATIONS`。** 被复核方的证据与 `PARTIAL` 结论经得起独立复算；保留意见是 R1–R6（措辞/覆盖/可复现性），其中 R1、R2 应在任务 4 接线前修正，但不影响 N/C/U 的采纳计数与 U01 的 FAIL 定性。

---

### 附：本次复核产出的探针与日志

`.tmp-t3review-isolated/`：`p01_inventory.py`、`p02_trace_binding.py`、`p02b_binding_fields.py`、`p03_census.py`、`p04_u01.py`、`p05_sources_standards.py`、`p06_gate_recompute.py`、`p07_compare_delivered.py`、`p08_config_equivalence.py`、`p09_manifest_audit.py`、`p10_negative_tests.py`、`p11_applicability.py`、`p13_grep_revision.py`、`p14_static_and_sums.py`、`p15_run_numbers.py`、`p16_artifact_hashes.py`、`p17_manifest_gates.py`、`p18_path_census.py`、`p19_question_hash.py`、`verify_manifest_copy.py`、`negatives/`、`netgate/sitecustomize.py`、`runs/`、`log/`（含 `p01`–`p19` JSON、`pytest` 输出、`t207-before/after.sha256`、`netgate.log`）。

本报告未修改：`report.md`、`manifest.json`、`evidence/`、`scripts/`、`backend/**`、`docs/evaluation/**`、`docs/reports/OBS-EVAL/P2/T207/**`。

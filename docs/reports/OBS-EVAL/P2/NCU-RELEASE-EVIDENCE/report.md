# P2 收尾 · 任务 3：N/C/U 正式证据核定报告

- 执行者：公开证据执行者（独立窗口 t3-ncu）
- 工作树：`D:/GPT项目/市场部AI知识库`，分支 `codex/p2-e2e`，接手锚点 `97b0066726e5b8d6f94cbc0b63a890084550c106`
- 生成时间：2026-11-20（Asia/Shanghai）
- 结论：**PARTIAL**（24/24 判定可复算且身份可证；正式可采 **N 8/8、C 6/6、U 10/10**，其中 6 条为 `ADOPTED_WITH_BINDING_PROOF`（机械 FAIL 保留、按 D-005 说明采信）；U 组另受最小样本口径约束，标 `PENDING-MASTER-DECISION` → 见 §5、§17）
- 本报告只做只读取证、隔离复算与结论标注；**没有**发起任何真实请求，**没有**修改 `backend/src/`、`backend/tests/`、`docs/evaluation/`、`docs/reports/OBS-EVAL/P2/T207/` 任何既有文件。

> `review.md` 按任务书由独立复核窗口撰写，本交付不包含。

---

## 1. 复算与来源绑定

### 1.1 方法（只读）

1. 用仓库既有评分驱动 `mktkb.evaluation.p2_score_run.score_run` 对三个历史 run 目录**只读重算**逐题评分（不重跑产品、不改判定），再与 `scoring/*/case_scores.json` 的既有结论逐题比对：R1 52 题、R2 2 题、R4 3 题，**状态全部相等**（`diffs {}`）。
2. 用 `evaluate_p2_hard_gates`（批准门槛 `gate_v0_3_approved.json`，加载摘要 `7fa6f47a…`）在**隔离副本**上重算八项硬门禁。隔离副本只把 `trace_store`/`dataset_path` 指向 `.tmp-ncu-isolated/` 内的字节相同拷贝；原 manifest、trace、题集、语料均未改（见 `evidence/gate_recompute.json` 的 `original_sha256`）。
3. 逐题身份由三级证据交叉绑定：run manifest（run/plan/config/gate/index/pipeline/dataset）→ run `cases.jsonl`（同轮产品响应、source、evidence、revision）→ trace DB（`question_sha256` 对应题干、`run_id`/`config_hash`/`manifest_sha256` 对应 run）。
4. run 级调用数**按运行身份**计一次（`providers.outbound_network`），不按题摊分；逐题 `real_calls=0` 不参与求和（历史 `verification.json` 同口径）。

### 1.2 run 身份绑定

| run | run_id | 计划 / SHA-256 | 原配置摘要（v0.3 gate） | 原流水线 | 索引版本（绑定） | 语料/数据集 SHA-256 |
| --- | --- | --- | --- | --- | --- | --- |
| R1 | `p2-t207-r1-20261111-01` | `P2-T207-MATRIX-20261111` / `0b4e55a4…` | `8bf2a7b7…`（run config）+ `d1097573…`（gate） | `d3ca88d2c515` | 11 | `e44ab9ff…` |
| R2 | `p2-t207-r2-20261111-01` | `P2-T207-MATRIX-20261111` / `0b4e55a4…` | `1370e34b…` + `d1097573…` | `d3ca88d2c515` | 3 | `d5fb8cac…` |
| R4 | `p2-t207-r4-20261111-01` | `P2-T207-R4-20261111` / `00b9fdef…` | `8de2f3b0…` + `d1097573…` | `d3ca88d2c515` | 5 | `c04b67c6…` |

| run | cases.jsonl SHA-256 | run_result SHA-256 | 评分 bundle SHA-256 | 出站调用 | chat 发送 | 结算 CNY |
| --- | --- | --- | --- | --- | --- | --- |
| R1 | `704f3743…` | `be3c31f3…` | `d22156be…` | 117 | 40 | 0.289440 |
| R2 | `f95ae562…` | `043b78c0…` | `410efbef…` | 9 | 1 | 0.020004 |
| R4 | `ec094ca8…` | `977d65aa…` | `223e4c16…` | 10 | 0 | 0.056064 |

全 64 位 SHA 见 `evidence/artifact-hashes.json`。R1/R2/R4 合计出站 136 次、chat 41 次、结算 0.365508 CNY；R3（5 次/1 次结算）与 H2（中止）不在 N/C/U 范围，**不计入**。

> 关键事实：三个 run 的 manifest `index_revision` 分别 11/3/5，等于各自 `ingest` 中**已发布**文档的最大 revision，也等于同轮产品响应的 `revision`。这是本报告认定"绑定正确"的核心同回合权威证据。

### 1.3 去重口径

- 冻结选题范围：R1 取 N01–N07、C01–C04；R4 取 N08、C05、C06；R2 仅取 U01。U02–U10 取本地控制（L）。
- `cases/R2.jsonl` 内还有 C05（R2 数据集 2 题），**不在冻结范围**，不得计入 C 组（R2 的 C05 实际返回 `answer`，冲突门禁 fail，正是 R4 替换它的原因）。
- 同一 case 只取指定 run，不跨 run 取最好成绩；重复选题由校验器拒绝（见 §10）。
- B0 组（R1 的 Q01–Q40）不进入 N/C/U 统计；R1 的 Q01–Q24 虽同样有 trace 索引差异，只在 §2.4 作为同源缺陷提示。

---

## 2. 六条 trace 逐条核定

### 2.1 不一致集合与机制

冻结 N/C/U 范围内 `trace.index_revision ≠ manifest.index_revision` 的恰好 **6 条**：N01、C01、C02（R1），U01（R2），C05、C06（R4），与经理预判"R1 三条、R4 两条、R2 一条"完全一致。

机制（同回合权威证据可证，非事后解释）：

- `backend/src/mktkb/rag/retrieval.py:49` 取 `start_revision = index.revision()`（即 `rag_meta.revision`），并在 `:176` 写 `trace_attrs.annotate_trace(index_revision=str(start_revision))`。**只有执行了 RAG 检索的轮次**才覆盖 trace 字段。
- 产品响应 `revision` 取 `manifest.revision`（`KnowledgeState.revision`，即 product revision）；更干净的并列证据是 `backend/src/mktkb/qa/service.py:376-379`（`QaIndexStatus.product_revision` 与 `index_revision` 并列），run 绑定同源（`product_adapter.py:1632/1661`）。
- 两套计数器客观不同：`rag_meta.revision` 是 RAG 索引内部单调计数（`rag/index.py:161-182`），`product_revision` 是产品发布计数；三个 run 中二者恰好相差 1（R1 12/11、R2 4/3、R4 6/5）。**T209 attempt2 报告已把同一现象定性为"运行接线的一致性缺陷"（`docs/reports/OBS-EVAL/P2/T209-PREP/b0-live-execution-attempt2-report.md:113-117`），冻结契约 `_TRACE_BINDING` 仍要求两侧相等；attempt3 的修复方向是把 manifest 绑定改到 RAG 实际 revision 使两侧相等（`b0-index-binding-independent-review.md:92-104`），不是把双计数写成合法口径。本报告只提供解释，不豁免门禁失败。**
- 门禁 `gate.py:261-269` 的 `_TRACE_BINDING` 把 `trace.index_revision` 与 `manifest.index_revision` 当同一字段比较 → 任何走过 RAG 检索路径的题都会触发 `version_binding`。

### 2.2 逐阶段实际索引版本（逐条）

| 选题 | trace_id | 路径 | 阶段①入库发布最大 revision | 阶段②产品响应 revision | 阶段③RAG 索引 revision（rag_meta） | trace 记录值 | 差异可否由同回合证据解释 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| N01 | `44f97217…` | legacy（已执行 recall/fuse/retrieve） | 11 | 11 | 12 | 12 | 可：检索路径覆盖 trace 字段；span 含 `recall` |
| C01 | `32f8df96…` | legacy_with_rag_candidates | 11 | 11 | 12 | 12 | 可：同上（含 rerank） |
| C02 | `bdbe4e54…` | legacy_with_rag_candidates | 11 | 11 | 12 | 12 | 可：同上（含 rerank） |
| U01 | `edacbdb8…` | rag | 3 | 3 | 4 | 4 | 可：完整 parse→recall→answer→fact_validate→commit |
| C05 | `321b0a5f…` | legacy_with_rag_candidates | 5 | 5 | 6 | 6 | 可：含 entity_conflict_check |
| C06 | `397a49ba…` | legacy_with_rag_candidates | 5 | 5 | 6 | 6 | 可：同上 |

对照组（同一 run 内无差异）：N02–N07、C03、C04、N08 的 trace 无 `recall` span（未走 RAG 检索），trace 保留 run 绑定值 11/5，**与 manifest 相等**。这进一步证明差异来自"是否走 RAG 检索路径"，而不是 run 绑定错误。

### 2.2.1 全量 57 条 trace 的严格二分（复核窗口加固，返工 R1-3）

把 R1/R2/R4 的**全部 57 条 trace**（不只是 6 条）按"有无 `recall` span"二分，结果 **0 例外**：

| run | trace 总数 | 有 `recall` | 其中有 `idx = rag 计数` | 无 `recall` | 其中 `idx = manifest` | 违例 |
| --- | --- | --- | --- | --- | --- | --- |
| R1 | 52 | 27 | **27/27** | 25 | **25/25** | 0 |
| R2 | 2 | 2 | **2/2** | 0 | — | 0 |
| R4 | 3 | 2 | **2/2** | 1 | **1/1** | 0 |

这条二分比"6 条逐条解释"更强：如果 trace 被错绑到别的 run/索引，`index_revision` 不可能**只在 retrieval 路径上**整齐等于本 run 的 `rag_meta.revision`，更不可能让未检索题保留 11/3/5。它排除了"错绑到别的 run/索引"，但**仍不能证明该字段在冻结契约下正确**（契约要求相等），故 6 条保留机械 FAIL，按 D-005 记 `ADOPTED_WITH_BINDING_PROOF` 而非 clean pass。

机器可读：`evidence/trace-adjudication.json`（含 span 列表、三阶段 revision、闭合判定）。

### 2.3 核定结论

- 6 条 trace 的**原始身份均可证**：`run_id`、`config_hash`、`manifest_sha256`、`dataset_version`、`pipeline_version`、`question_sha256` 全部一致，仅 `index_revision` 一个字段不同；该字段可由同回合权威证据（入库发布记录、产品响应 revision、`rag_meta` 双计数、span 路径）完整解释。
- 但这 6 条在**冻结门禁的机械口径**下仍记为 `trace_integrity: version_binding` **FAIL**（R1 共 27 条、R2 2 条、R4 2 条）。因此本报告**不把它们写成 clean pass**：机械 FAIL 原样保留，按主人 **D-005** 以绑定适用性证明采信，记 `ADOPTED_WITH_BINDING_PROOF`（保留原 run 身份与原 `d1097573` 配置摘要）；契约修复仍建议列为 §9 的派工项。
- 独立关系记录：`evidence/trace-adjudication.json` 与本报告 §2 共同构成"新证据（双计数重建）—原证据（trace/manifest 原文）"的关系记录；原诊断（门禁失败）原样保留。

### 2.4 同源缺陷提示（超出本任务范围）

R1 的 Q01–Q24 同样是 `12≠11`（共 27/52 条）。若只修 N/C/U 的 6 条而不修契约，B0 组会在同一门禁上继续失败。修复建议见 §9 待办 T-1。

---

## 3. U01 引用重建

### 3.1 重建链

1. trace `citation_refs_json[0].unit_id_hash = 504e0ea7f4b1c86f`。
2. 在隔离复制的 R2 RAG 索引中检索：`sha256(rag_chunks.chunk_id='a202ff9b372dc1d919ca73a698c84c38')[:16] = 504e0ea7f4b1c86f` —— **命中**。即 trace 的 `unit_id_hash` 实际存的是 **chunk 哈希**，不是 unit 哈希（`rag/answer.py:291` 的 `hash_ref(citation.source_id)`，`citation.source_id` 在 RAG 路径是 chunk id）。
3. 该 chunk 的 `record_unit_id = 072d28f2-b403-4af3-9fe9-31b9e8714dbf`，`kind=record`，`revision=3`，`unit_ids=["072d28f2-…"]`。
4. RAG 单元 `072d28f2-…`：`unit_key=sheet:物品位置:row:8`，`sheet=物品位置`，`row_number=8`，文本 `标识: P01 | 门店: 城东店 | 物品: 宣传海报 | 别名: 海报 | 位置: B区1号货架第二层`。
5. 同轮产品响应 `product.evidence[0].unit_id = 072d28f2-b403-4af3-9fe9-31b9e8714dbf`、`unit_key=sheet:物品位置:row:8`、`version_number=2`、`state=published`；`source_ids` 同一 unit；回答文本含期望值 `B区1号货架第二层`。

**结论：引用真实、可 1:1 对回同一逻辑单元，不存在编造或跨题引用。**

机器可读：`evidence/u01-citation-reconstruction.json`。

### 3.2 门禁为什么曾 fail（D-004 后已 pass）

改前引擎下，`evaluate_p2_hard_gates` 的 `citation_required` 报 `U01: citation_not_in_evidence`，证据为 `{"unit_ids": ["072d28f2-…"], "evidence_units": 0}`。原因是**同轮产品响应的 `retrieved` 为空**（`product.retrieved=[]`，而 `product.evidence` 有 1 条）。评分归一层优先用显式 evidence，其次才用 `product.retrieved`（`p2_scoring.py:546-554`）；改前 gate 只认 `outcome.retrieved`。对照 **R2.C05**（`retrieved=1`）与 R1.Q01（`retrieved=1`），而 **R4.C05 的 `retrieved` 为 0 条**（其 path=`legacy_with_rag_candidates`、outcome=conflict）——即"C05 类"并非都非空，不能拿 R4.C05 当对照。

**D-004 后的现状**：候选接地集合改为 `evidence ∪ retrieved`，且 `build_gate_rows` 需以 `case_rows` 投影 `product.evidence`；R2 重算 `citation_required = pass`（0 失败，见 §17.2）。判据没有放宽——若引用既不在 evidence 也不在 retrieved，仍会 `citation_not_in_evidence` fail。

进一步对全部 57 条 trace 的 42 条 `answer` 做路径普查：**唯一 `trace_path="rag"` 的 answer 就是 U01，且只有它 `retrieved` 为空**；其余 41 条非 `rag` 路径 answer 的 `retrieved` 全部非空（R2.C05=1、R1.Q01=1 等）。这把"该轮字段缺失"从个案升级为 **`rag` 打包路径特有的响应形状缺陷**：不是引用内容错误，也不是随机丢字段。

定位不足项与既有措辞规则适用性：

| 项 | 事实 | 既有规则适用性 | 结论 |
| --- | --- | --- | --- |
| U01 gold `expected_sources=[{doc_code:D01, record_code:P01}]` | 无 `unit_key`/`locator` | `match_source_ref` 在 record_code 不可解析时按"同文档即命中"（`scorers.py:581`） | `source_hit` 仅**文档级**通过；本报告用 §3.1 重建把 P01→`sheet:物品位置:row:8`，补足单元级证据，但不改冻结题集 |
| C05/C06 gold 同样 `record_code:P01`，并 `dropped_free_text_locator=heading` | 标题型 locator 被显式丢弃 | 同上 → 文档级命中 | `value_hit` 2/2、`source_hit` 2/2 中 D01 一项为文档级；`V01/page=1` 为 locator 级 |
| N01–N08 `accepted_wording(any-of,not-scored)` | 拒答措辞明确 not-scored | 评分器不消费该字段 | 只证明 `kind=not_found` + `refusal_expected`，**不得**宣称措辞合规 |
| C01–C04 无 `expected_values`/`expected_sources`，仅 `candidates` 措辞 | 只有 kind 级真值 | `conflict_not_rejected` 只覆盖 `expected_kind=conflict`（C01–C04 为 clarification） | 仅 `kind_correct` 可判；不得宣称澄清内容命中候选实体 |

---

## 4. U02–U10 的 R/L 口径验证（历史核对与本次复跑分列）

| 项 | 历史核对（原记录） | 本次复跑（2026-11-20 本机隔离） |
| --- | --- | --- |
| 来源 | `docs/reports/OBS-EVAL/P2/T207/scoring/u-controls.json`（SHA `11b1679f…`，与历史 `verification.json` 记录的输入哈希一致 → 未被改） | 同文件 + `backend/tests/acceptance/test_t09_mutation.py`（SHA `31374667…`） |
| 命令 | 历史生成器（`exit_code: 0`） | `.\.venv\Scripts\python.exe -m pytest backend/tests/acceptance/test_t09_mutation.py -q` |
| 退出码 | 0 | **0** |
| 结果 | U01–U10 全部 `pass`，13 条 test 条目全 pass | **13 passed**，0 skipped，0 failed，1 warning（Starlette/httpx 弃用告警），21.25s |
| 用例映射 | 13 条 `test_uNN_*` 与 U01–U10 一一对应 | `--collect-only` 13 条，名称与历史 13 条**逐字相同** |
| Mock 情况 | 未记录 | `fastapi.testclient` 进程内 ASGI；`support/b0.py` 夹具；无外部 provider |
| 外部网络尝试 | 未记录 | **0**：模块级 `pytestmark = pytest.mark.usefixtures("t09_network_guard")`，`support/netguard.py` 拦截 `connect/connect_ex/create_connection/getaddrinfo` 与 `httpx` 传输，teardown 断言 `external == []`；13 passed 即外部尝试为空 |
| U01 特殊性 | U01 同时有 R 口径真实 smoke | 本节测试中的 `test_u01_*` 只作 L 口径补充，**不替代**§2/§3 的 R 口径证据 |

- U01 的真实 smoke 地位由 R2 的原始产物（产品响应 + trace + 引用重建）独立支撑。
- U02–U10 **只**有 L 口径；不得外推为"真实模型全量更新能力"。approved 门槛也明确要求"真实 smoke 与本地关键控制口径分列"。

---

## 5. 覆盖与通过数

| 口径 | N | C | U | 未执行 | 说明 |
| --- | --- | --- | --- | --- | --- |
| 计划/覆盖（冻结范围） | 8 | 6 | 10 | 0 | 覆盖 = 8/8、6/6、10/10；无缺题、无 error、无 OCR 跳过 |
| 判定通过（评分层，独立复算与历史逐题相等） | **8/8** | **6/6** | **10/10** | 0 | U = R2 真实 smoke 1 + 本地控制 9 |
| **无条件可采（无任何机械 FAIL）** | **7/8** | **2/6** | **9/10** | 0 | 只剩下列 6 条有机械 FAIL；U 的 9 为 L 口径 |
| **带 D-005 绑定适用性证明（机械 FAIL 保留）** `ADOPTED_WITH_BINDING_PROOF` | 1（N01） | 4（C01,C02,C05,C06） | 1（U01） | 0 | `trace_integrity:version_binding` 机械 FAIL 原样保留，按 D-005 以适用性证明采信 |
| **正式可采（含 D-005 证明）= 上两行之和** | **8/8** | **6/6** | **10/10** | 0 | 批准门槛 8/8、6/6、10/10 均达；U 另受最小样本口径约束（见下） |
| `FAIL` | 0 | 0 | 0 | 0 | 无不可解释失败 |
| `UNKNOWN` | 0 | 0 | 0 | 0 | 本次没有"证据缺失无法判定"项 |

- **两行必须分开读**：`无条件可采（无任何机械 FAIL）` = N 7/8、C 2/6、U 9/10；`正式可采（含 D-005 证明）` = N 8/8、C 6/6、U 10/10。前者是机械口径，后者是主人 D-005 采信证明后的正式口径；**任何只引用其中一行的表述都不完整**。
- **机械 FAIL 保留、不静默改 ADOPTED**：6 条 `ADOPTED_WITH_BINDING_PROOF` 的 `gates.trace_integrity.status` 仍是 `fail`，并在清单 `mechanical_gate_failures` 里逐条留痕；D-005 只改变"是否采信"，不改变"是否失败"。
- **U 的显式限制（不解决，只记录）**：U 组 run 级 `evaluated_count = 1`（仅 U01），而批准配置 `hard_gate_min_sample.update_delete = 10`；因此 U 的八项硬门禁在批准最小样本口径下**无法满足**。清单标 `hard_gate_min_sample.unmet = {suite: "update_delete", evaluated: 1, required: 10}`、状态 `PENDING-MASTER-DECISION`，由经理另报主人裁量。
- **若主人撤回 D-005**：6 条 `ADOPTED_WITH_BINDING_PROOF` 回到纯机械口径即 `FAIL`，正式可采降为 **N 7/8、C 2/6、U 9/10**（U 未达 10/10）。D-005 的有效性只改变采信，不改变机械失败事实。
- 去重后没有重复选题：`R2.C05` 不计入 C 组；B0 的 Q 组不计入本表；U 的 R/L 分开记，不把 U01 的 R 证据外推给 U02–U10，也不把 L 结果冒充 R。
- 与历史基线的关系：历史 N 8/8、C 6/6、U 10/10 是**判定层**观测，本次独立复算一致；本报告新增"机械层"（7/8、2/6、9/10）与"正式可采层（含 D-005 证明）"（8/8、6/6、10/10）。两层都保留：机械 FAIL 不因证明而消失，正式口径也不因机械 FAIL 而缺项。U 组另有最小样本口径 `PENDING-MASTER-DECISION`。

## 5.1 逐题来源清单（24 条）

| 选题 | 组 | run ID | 计划 SHA-256 | 原配置摘要 | 索引版本（绑定） | 语料 / 流水线 | 工件 SHA-256 | 采纳（四档） | 机械 FAIL / 理由 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| N01 | N | `p2-t207-r1-20261111-01` | `0b4e55a4cd3a…` | `8bf2a7b738db…`（gate `d1097573…`） | 11 | `e44ab9ffd89f…` / `d3ca88d2c515` | cases `704f37431e8d…`；bundle `docs/reports/OBS-EVAL/P2/T207/scoring/R1-fixed/case_scores.json` | ADOPTED_WITH_BINDING_PROOF | trace_integrity:version_binding；机械 FAIL 保留（trace_integrity:version_binding）；按 D-005 以证明采信 |
| N02 | N | `p2-t207-r1-20261111-01` | `0b4e55a4cd3a…` | `8bf2a7b738db…`（gate `d1097573…`） | 11 | `e44ab9ffd89f…` / `d3ca88d2c515` | cases `704f37431e8d…`；bundle `docs/reports/OBS-EVAL/P2/T207/scoring/R1-fixed/case_scores.json` | ADOPTED | 无；八门禁无机械 FAIL；三条件齐备 |
| N03 | N | `p2-t207-r1-20261111-01` | `0b4e55a4cd3a…` | `8bf2a7b738db…`（gate `d1097573…`） | 11 | `e44ab9ffd89f…` / `d3ca88d2c515` | cases `704f37431e8d…`；bundle `docs/reports/OBS-EVAL/P2/T207/scoring/R1-fixed/case_scores.json` | ADOPTED | 无；八门禁无机械 FAIL；三条件齐备 |
| N04 | N | `p2-t207-r1-20261111-01` | `0b4e55a4cd3a…` | `8bf2a7b738db…`（gate `d1097573…`） | 11 | `e44ab9ffd89f…` / `d3ca88d2c515` | cases `704f37431e8d…`；bundle `docs/reports/OBS-EVAL/P2/T207/scoring/R1-fixed/case_scores.json` | ADOPTED | 无；八门禁无机械 FAIL；三条件齐备 |
| N05 | N | `p2-t207-r1-20261111-01` | `0b4e55a4cd3a…` | `8bf2a7b738db…`（gate `d1097573…`） | 11 | `e44ab9ffd89f…` / `d3ca88d2c515` | cases `704f37431e8d…`；bundle `docs/reports/OBS-EVAL/P2/T207/scoring/R1-fixed/case_scores.json` | ADOPTED | 无；八门禁无机械 FAIL；三条件齐备 |
| N06 | N | `p2-t207-r1-20261111-01` | `0b4e55a4cd3a…` | `8bf2a7b738db…`（gate `d1097573…`） | 11 | `e44ab9ffd89f…` / `d3ca88d2c515` | cases `704f37431e8d…`；bundle `docs/reports/OBS-EVAL/P2/T207/scoring/R1-fixed/case_scores.json` | ADOPTED | 无；八门禁无机械 FAIL；三条件齐备 |
| N07 | N | `p2-t207-r1-20261111-01` | `0b4e55a4cd3a…` | `8bf2a7b738db…`（gate `d1097573…`） | 11 | `e44ab9ffd89f…` / `d3ca88d2c515` | cases `704f37431e8d…`；bundle `docs/reports/OBS-EVAL/P2/T207/scoring/R1-fixed/case_scores.json` | ADOPTED | 无；八门禁无机械 FAIL；三条件齐备 |
| N08 | N | `p2-t207-r4-20261111-01` | `00b9fdefd8cc…` | `8de2f3b01cd4…`（gate `d1097573…`） | 5 | `c04b67c6f8a4…` / `d3ca88d2c515` | cases `ec094ca8f155…`；bundle `docs/reports/OBS-EVAL/P2/T207/scoring/R4/case_scores.json` | ADOPTED | 无；八门禁无机械 FAIL；三条件齐备 |
| C01 | C | `p2-t207-r1-20261111-01` | `0b4e55a4cd3a…` | `8bf2a7b738db…`（gate `d1097573…`） | 11 | `e44ab9ffd89f…` / `d3ca88d2c515` | cases `704f37431e8d…`；bundle `docs/reports/OBS-EVAL/P2/T207/scoring/R1-fixed/case_scores.json` | ADOPTED_WITH_BINDING_PROOF | trace_integrity:version_binding；机械 FAIL 保留（trace_integrity:version_binding）；按 D-005 以证明采信 |
| C02 | C | `p2-t207-r1-20261111-01` | `0b4e55a4cd3a…` | `8bf2a7b738db…`（gate `d1097573…`） | 11 | `e44ab9ffd89f…` / `d3ca88d2c515` | cases `704f37431e8d…`；bundle `docs/reports/OBS-EVAL/P2/T207/scoring/R1-fixed/case_scores.json` | ADOPTED_WITH_BINDING_PROOF | trace_integrity:version_binding；机械 FAIL 保留（trace_integrity:version_binding）；按 D-005 以证明采信 |
| C03 | C | `p2-t207-r1-20261111-01` | `0b4e55a4cd3a…` | `8bf2a7b738db…`（gate `d1097573…`） | 11 | `e44ab9ffd89f…` / `d3ca88d2c515` | cases `704f37431e8d…`；bundle `docs/reports/OBS-EVAL/P2/T207/scoring/R1-fixed/case_scores.json` | ADOPTED | 无；八门禁无机械 FAIL；三条件齐备 |
| C04 | C | `p2-t207-r1-20261111-01` | `0b4e55a4cd3a…` | `8bf2a7b738db…`（gate `d1097573…`） | 11 | `e44ab9ffd89f…` / `d3ca88d2c515` | cases `704f37431e8d…`；bundle `docs/reports/OBS-EVAL/P2/T207/scoring/R1-fixed/case_scores.json` | ADOPTED | 无；八门禁无机械 FAIL；三条件齐备 |
| C05 | C | `p2-t207-r4-20261111-01` | `00b9fdefd8cc…` | `8de2f3b01cd4…`（gate `d1097573…`） | 5 | `c04b67c6f8a4…` / `d3ca88d2c515` | cases `ec094ca8f155…`；bundle `docs/reports/OBS-EVAL/P2/T207/scoring/R4/case_scores.json` | ADOPTED_WITH_BINDING_PROOF | trace_integrity:version_binding；机械 FAIL 保留（trace_integrity:version_binding）；按 D-005 以证明采信 |
| C06 | C | `p2-t207-r4-20261111-01` | `00b9fdefd8cc…` | `8de2f3b01cd4…`（gate `d1097573…`） | 5 | `c04b67c6f8a4…` / `d3ca88d2c515` | cases `ec094ca8f155…`；bundle `docs/reports/OBS-EVAL/P2/T207/scoring/R4/case_scores.json` | ADOPTED_WITH_BINDING_PROOF | trace_integrity:version_binding；机械 FAIL 保留（trace_integrity:version_binding）；按 D-005 以证明采信 |
| U01 | U | `p2-t207-r2-20261111-01` | `0b4e55a4cd3a…` | `1370e34b4178…`（gate `d1097573…`） | 3 | `d5fb8cacac7b…` / `d3ca88d2c515` | cases `f95ae56249ae…`；bundle `docs/reports/OBS-EVAL/P2/T207/scoring/R2-fixed/case_scores.json` | ADOPTED_WITH_BINDING_PROOF | trace_integrity:version_binding；机械 FAIL 保留（trace_integrity:version_binding）；按 D-005 以证明采信 |
| U02 | U | —（本地控制） | — | — | — | test_t09_mutation.py `31374667cf0d…` | u-controls.json + 测试文件（全 SHA 见 manifest） | ADOPTED | 无（L 口径无 run/trace 门禁） |
| U03 | U | —（本地控制） | — | — | — | test_t09_mutation.py `31374667cf0d…` | u-controls.json + 测试文件（全 SHA 见 manifest） | ADOPTED | 无（L 口径无 run/trace 门禁） |
| U04 | U | —（本地控制） | — | — | — | test_t09_mutation.py `31374667cf0d…` | u-controls.json + 测试文件（全 SHA 见 manifest） | ADOPTED | 无（L 口径无 run/trace 门禁） |
| U05 | U | —（本地控制） | — | — | — | test_t09_mutation.py `31374667cf0d…` | u-controls.json + 测试文件（全 SHA 见 manifest） | ADOPTED | 无（L 口径无 run/trace 门禁） |
| U06 | U | —（本地控制） | — | — | — | test_t09_mutation.py `31374667cf0d…` | u-controls.json + 测试文件（全 SHA 见 manifest） | ADOPTED | 无（L 口径无 run/trace 门禁） |
| U07 | U | —（本地控制） | — | — | — | test_t09_mutation.py `31374667cf0d…` | u-controls.json + 测试文件（全 SHA 见 manifest） | ADOPTED | 无（L 口径无 run/trace 门禁） |
| U08 | U | —（本地控制） | — | — | — | test_t09_mutation.py `31374667cf0d…` | u-controls.json + 测试文件（全 SHA 见 manifest） | ADOPTED | 无（L 口径无 run/trace 门禁） |
| U09 | U | —（本地控制） | — | — | — | test_t09_mutation.py `31374667cf0d…` | u-controls.json + 测试文件（全 SHA 见 manifest） | ADOPTED | 无（L 口径无 run/trace 门禁） |
| U10 | U | —（本地控制） | — | — | — | test_t09_mutation.py `31374667cf0d…` | u-controls.json + 测试文件（全 SHA 见 manifest） | ADOPTED | 无（L 口径无 run/trace 门禁） |

---

## 6. 八项硬门禁适用性

以批准门槛 `gate_v0_3_approved.json`（加载摘要 `7fa6f47a…`）在隔离副本重算；逐 run 结果见 `evidence/gate_recompute.json`，逐题适用性见 `manifest.json` 每题的 `gates`。

| # | 门禁 | 适用性 | 适用题 | 机械结果 | 依据/限制 |
| --- | --- | --- | --- | --- | --- |
| 1 | `security_leak` | 适用（部分） | C05、C06（R4，有 forbidden V03/V06） | **pass**（0 违规） | 其余 22 题无 forbidden 约束 → 不适用；R2.C05 亦适用但不在范围 |
| 2 | `cross_entity` | **不适用** | 0 | — | 数据集无 entity key / 请求 filters 字段；仅接受上游 `hard_filter_violation=cross_entity` 信号（本批未出现）。**语义上 N/C 组关心跨实体，但当前契约无可判定字段，不能声称已通过** |
| 3 | `stale_bypass` | **不适用** | 0 | — | 无 `include_future/as_of/effective_from/effective_to` 字段；同上限制 |
| 4 | `conflict_not_rejected` | 适用（部分） | C05、C06 | **pass** | 门禁只覆盖 `expected_kind=conflict`；C01–C04（clarification）不适用；R2.C05 在范围外 fail（返回 answer） |
| 5 | `exact_value_contract` | **不适用** | 0 | — | 只作用 `stratum=exact`；本批为 negative/boundary/mutation |
| 6 | `pagination_contract` | **不适用** | 0 | — | 24 题均无 `expected_pagination` |
| 7 | `citation_required` | 适用（部分） | U01 | **pass**（D-004：候选接地集合 = evidence ∪ retrieved） | 只对 `kind=answer` 适用；C05/C06 为 conflict、N 组为 not_found，不适用。改前引擎为 `citation_not_in_evidence`（见 §17.3 前后对比） |
| 8 | `trace_integrity` | 适用（部分） | 15 = N8 + C6 + U01 | **9 pass / 6 fail**（`version_binding`） | 6 条 = §2，按 D-005 记 `ADOPTED_WITH_BINDING_PROOF`（机械 FAIL 保留）；U02–U10 为本地控制无 trace → 不适用 |

- 本表为 **R2 新引擎**（`gate.py e04990db…` + `build_gate_rows(case_rows=…)`）结果；改前引擎（`citation_required` fail）保留在 `evidence/gate_recompute.json` 仅作对照。
- **证据不足（unknown）**：本次重算 `unknowns=0`。U02–U10 的八门禁是"不适用（L 无 run/trace）"，不是"证据不足"；不得用测试通过替代运行级门禁。
- **机器口径仍保留失败**：6 条 `version_binding` 的 `gates.trace_integrity.status` 仍是 `fail`；D-005 只允许"以证明采信"，不等于门禁变 pass。

---

## 7. 零真实请求与无外部网络尝试证据

| 项 | 证据 |
| --- | --- |
| 新增真实请求 | **0**。本次全部为仓库内只读文件 + 已存在的 SQLite 副本（从 `D:\mktkb-p2-run\t207\` **复制**到 `.tmp-ncu-isolated/traces/`），没有调用任何 provider、API、模型、OCR、rerank。 |
| 新 GO | 未申请、未使用。历史 run 的 `P2-LIVE-GO` 未再触发（只读产物）。 |
| 复算脚本网络闸门 | `scripts/gate_recompute.py` 在导入业务模块前把 `socket.socket.connect/connect_ex`、`socket.create_connection` 替换为 `raise AssertionError("network_forbidden_in_recompute")`。 |
| 验收测试网络闸门 | `backend/tests/acceptance/support/netguard.py::t09_network_guard` 由模块 `pytestmark` 强制启用；外部出站尝试非空即 teardown 失败。本次命令 **13 passed**（exit 0），等价于 `external=[]`。 |
| 产品执行边界（返工 R1-2/1） | **未对生产数据与真实 provider 执行产品**；L 口径验收通过 `fastapi.testclient.TestClient` 在**进程内**启动完整产品应用（Mock/替身 provider），会执行解析/入库/检索/问答代码路径；未启动监听端口的服务。评分/gate 复算为纯函数，只读 SQLite/JSONL。 |
| 固定文件未漂移 | `u-controls.json` 本次 SHA `11b1679f…` 与历史 `verification.json` 输入清单一致；`fixed_files_before/after` 三者相同（历史记录），本报告未触碰预算账本/GO 文件。 |

---

## 8. 机器可读清单

`docs/reports/OBS-EVAL/P2/NCU-RELEASE-EVIDENCE/manifest.json`（供任务 4 接线）：

- `authority`：任务书、批准门槛文件 SHA（`b1094cc7…`）、加载摘要（`7fa6f47a…`）、冻结模板文件 SHA（`3af301db…`）、加载摘要（`d1097573…`）、**旧版本适用性证明**（见 §11）。
- `runs`：每个 run 的 run_id/plan_sha/config/gate/index/pipeline/dataset、`max_published_revision`、`ingest_published_revisions`、出站/结算、以及全部工件 SHA（manifest/result/cases/dataset/gate/summary/trace DB/rag DB，R2 另含 product DB）。
- `selection_policy`：冻结范围、排除项（R2.C05、Q 组、R3）、去重口径。
- `tallies`：判定通过 / 无条件可采 / 有条件保留 / FAIL / UNKNOWN / 计划数。
- `hard_gate_applicability.run_recompute`：R1/R2/R4 的门禁状态与退出码。
- `cases`（24 条）：
  - R 口径 15 条：run_id、plan_sha256、config_hash、gate_config_hash_original、pipeline_version、`index_revision_binding`、`index_revision_trace`、`index_revision_rag`、`index_revision_product_response`、trace_id/path/outcome、question_sha256、评分状态与失败 check、`gates`（八项逐题 applicable/status/failure）、`adopt`、`adopt_reason`、`evidence_paths`。
  - L 口径 9 条：测试文件 SHA、历史记录、本次复跑（命令/退出码/13 passed/网络闸门）、gates 全部 not_applicable、`adopt`、限制说明。
- `commands`：验收命令与退出码。
- `network_evidence`：0 新真实请求、0 新调用、两道网络闸门。
- `open_items`：4 项待办（§9）。

校验：`scripts/verify_manifest.py` 对 `manifest.json` 返回 `{"ok": true, "cases": 24, ...}`，退出码 0。

---

## 9. 未闭合项与最小新增验证方案

| 编号 | 未闭合项 | 影响 | 最小修复/新增验证 | 是否需要真实请求 |
| --- | --- | --- | --- | --- |
| T-1 | **trace 双计数契约**：`trace.index_revision` 写 `rag_meta.revision`，`manifest.index_revision` 是 `product_revision`，`_TRACE_BINDING` 把二者当同一字段 | 6/24（N01,C01,C02,U01,C05,C06）；R1 全量 27/52、R4 2/3、R2 2/2 | **D-005 已采信证明**（机械 FAIL 保留）；契约修复仍建议派工，二选一：<br>(a) trace 保留 run 绑定的 `product_revision`，另增 `rag_index_revision` 字段（trace schema 版本 + 契约 + gate 绑定 + 测试）；<br>(b) 契约明确 `index_revision := rag 计数`，gate 改比 rag 计数，并把 `product_revision` 作为独立绑定字段。<br>修订后**离线**重跑 `evaluate_p2_hard_gates` 即可复验（0 真实请求，0 费用） | **否** |
| T-2 | **U01 同轮 `product.retrieved=[]`**，而 `product.evidence=1`；`citation_required` 因此 fail | U01 | **已由 D-004 解决**：新 `gate.py` 候选接地集合 = `evidence ∪ retrieved`，且 `build_gate_rows(case_rows=...)` 投影 `product.evidence`；R2 重算 `citation_required = pass`（0 失败）。判据不变：既不在 evidence 也不在 retrieved 仍 fail | **否** |
| T-3 | **gold 定位不足**：C05/C06/U01 的 `record_code:P01` 未给 `unit_key`，`source_hit` 退化为文档级 | 3 题的 source 证据强度 | 以本报告 §3.1 的重建做**离线补证**（P01→`sheet:物品位置:row:8`），不改冻结题集；若要求单元级 `source_hit` 进门槛，需更新 `docs/evaluation` 冻结题集（须经理批准，禁止执行者自改） | **否**（补证）；改题集需批准但不涉请求 |
| T-4 | **措辞规则 not-scored**：`accepted_wording(any-of)`、C01–C04 无值级真值 | N01–N08、C01–C04 | 报告标注即可；若要断言措辞/澄清内容，需新增评测项（属题集/评分器变更，另行派工） | 否 |
| T-5 | **U 的最小样本口径冲突**：run 级 `evaluated_count=1`（U01）vs 批准 `hard_gate_min_sample.update_delete=10`；9 条本地控制不是 run 行 | U 的八项硬门禁 | **不解决，只记录**：清单 `hard_gate_min_sample.unmet={suite:"update_delete",evaluated:1,required:10}`、状态 `PENDING-MASTER-DECISION`；由经理另报主人裁量（接受 1R+9L 口径 / 补 9 题真实 run 证据 / 接受阻断） | 若补证则需要（新 GO） |

### 最小真实请求方案（仅方案，未执行；需新 GO）

- 题：**U01 单题**（唯一 R 口径且门禁未闭合的 N/C/U 题）。
- 原因：验证修复后的 `product.retrieved` 是否回填、`citation_required` 是否转 pass；同时可顺带验证 T-1 修复后的 trace 绑定。
- 候选版本绑定：`gate_v0_3_approved.json`（`7fa6f47a…`）+ 修复后流水线源码摘要（新）+ R2 同批语料（`d5fb8cac…`）。
- 预计配额/费用：chat 1、query_embedding 1、index_embedding ≤4、rerank 1、OCR 0 → **≤ 7 次**；按 R2 实际 0.0207119 CNY 上界保守 ×2 ≈ **≤ 0.05 CNY**；请求上限 ≤ 10。
- 隔离方式：复制 R2 语料/索引到新 run 目录（不复用 R2 生产目录），Mock 关闭，网络闸门仅允许该 run 的 provider；产出独立 run_id 与新 GO 绑定。
- 需要：主人签发绑定该计划的新 GO；执行者不得自行发起。

---

## 10. 独立复核要点（供独立窗口验证）

### 10.1 应被拒绝的情形与本次自测

校验器：`scripts/verify_manifest.py`；负例生成器：`scripts/negative_tests.py`；机器输出：`evidence/negative-tests.json`。对真实 `manifest.json` 运行：**exit 0**、`{"ok": true, "cases": 24}`。当前负例共 **12 个**（A1–A6 + B1/B2/B5 + B7/B8/B9），全部 exit 1。

| 负例（构造） | 期望拒绝码 | 实际输出（截取） | 退出码 |
| --- | --- | --- | --- |
| 错绑定：N02 的 `plan_sha256` 改成全 0 | `WRONG_BINDING` | `{"ok": false, "errors": ["WRONG_BINDING:N02:plan_sha256"]}` | 1 |
| 重复选题：复制 N02 追加 | `DUPLICATE_CASE` + 样本数 | `["SAMPLE_INSUFFICIENT:N:expected=8:actual=9", "DUPLICATE_CASE:N02"]` | 1 |
| U 类型混用：U05 改 `basis=R` 并塞 R2 run_id | `U_TYPE_MIXED` + 绑定 | `["U_TYPE_MIXED:U05:R_basis_with_local_control_fields", "WRONG_BINDING:U05:plan_sha256", …]` | 1 |
| 样本不足：删除 C06 | `SAMPLE_INSUFFICIENT` | `["SAMPLE_INSUFFICIENT:C:expected=6:actual=5"]` | 1 |
| 缺 trace：N03 `trace_id=null` | `MISSING_TRACE` | `["MISSING_TRACE:N03"]` | 1 |
| 缺引用：删 U01 的 `source_hit` 与 `citation_required` 门禁项 | `MISSING_CITATION_EVIDENCE` | `["MISSING_CITATION_EVIDENCE:U01", "MISSING_CITATION_EVIDENCE:U01:source_hit"]` | 1 |
| **B1**（复核窗口）：N05 的 `question_sha256` 换成另一个合法 64 hex | `QUESTION_HASH_MISMATCH` | `["QUESTION_HASH_MISMATCH:N05:frozen", "QUESTION_HASH_MISMATCH:N05:run_cases", "TRACE_CASE_MISMATCH:N05:question_hash"]` | 1 |
| **B2**（复核窗口）：N02（ADOPTED）的 `evidence_paths.run_cases` 指向不存在文件 | `EVIDENCE_PATH_MISSING` | `["EVIDENCE_PATH_MISSING:N02:run_cases"]` | 1 |
| **B5**（复核窗口）：N02 与 N03 互换 `trace_id` | `TRACE_CASE_MISMATCH` | `["TRACE_CASE_MISMATCH:N02:question_hash", "TRACE_CASE_MISMATCH:N03:question_hash"]` | 1 |
| **B7**（R2）：N01 声称 `ADOPTED_WITH_BINDING_PROOF` 但清空 `mechanical_gate_failures` | `BINDING_PROOF_WITHOUT_MECHANICAL_FAIL` | `["BINDING_PROOF_WITHOUT_MECHANICAL_FAIL:N01:no_mechanical_record"]` | 1 |
| **B8**（R2）：N01 声称该档但删掉 `binding_proof` | `BINDING_PROOF_MISSING` | `["BINDING_PROOF_MISSING:N01"]` | 1 |
| **B9**（R2）：N01 把 `trace_integrity` 状态强改 `pass` 又保留机械记录 | `BINDING_PROOF_WITHOUT_MECHANICAL_FAIL` | `["BINDING_PROOF_WITHOUT_MECHANICAL_FAIL:N01:no_gate_fail"]` | 1 |

### 10.2 复核清单

1. **错绑定**：逐题 `run_id/plan_sha256/config_hash/pipeline_version/index_revision_binding` 与 `runs[run_id]` 逐键相等；`question_sha256` 必须三方同时命中：冻结题集 `sha256(question)`、run `cases.jsonl` 同题哈希、trace DB 内该 `trace_id` 的 `question_hash`（v0.2 校验器已实现回源，见 §16 R1-1）。
2. **重复选题**：`cases` 的 `case_id` 是否唯一；`R2.C05` 是否确实未计入 C 组。
3. **U 类型混用**：`basis=L` 是否无 run_id/trace；`basis=R` 是否无 `source/historical/rerun` 本地控制字段；U01 的 R 证据是否未被用于 U02–U10。
4. **样本不足**：N/C/U 是否恰为 8/6/10，未执行是否为 0。
5. **缺 trace**：15 条 R 口径是否都有 `trace_id`，且 trace DB 内 `question_sha256` 与 run cases 一致。
6. **缺引用 / D-004**：answer 类是否都有 `citation_required` 门禁项与 `source_hit` 证据；U01 的 `citation_required` 是否已按 D-004 转 `pass`，且 `trace_integrity` 机械 FAIL 仍保留（未被写成 clean pass）。
7. **禁止消除失败**：确认交付目录内的 `gate_recompute.json`（改前）与 `gate_recompute_r2.json`（改后）的 `original_sha256` 与原始 trace/run manifest 的 SHA 对应；确认诊断副本只改了 `trace_store/dataset_path` 两个路径（`.tmp-ncu-isolated/runs/` 已在交付前清理，可按 §12 复现顺序用 `scripts/prepare_isolated.py` + `scripts/gate_recompute.py` 重建并核对 `original_sha256`）。
8. **四档状态（R2）**：`ADOPTED_WITH_BINDING_PROOF` 必须同时有 ①未清除的机械 FAIL 记录（`gates.*.status="fail"` 与 `mechanical_gate_failures` 一致）②`binding_proof`（D-005）五要素齐全 ③原始身份字段齐全；任一缺失应由 B7/B8/B9 类负例拦下。

---

## 11. 旧版本适用性证明（保留原身份）

- 三个历史 run 绑定旧 v0.3 冻结模板加载摘要 `d1097573…`（`gate_v0_3.json`，文件 SHA `3af301db…`）。
- 当前正式门槛 `gate_v0_3_approved.json`（文件 SHA `b1094cc7…`，加载摘要 `7fa6f47a…`）与冻结模板逐键比较：`schema_version`、`gate_version`、`hard_gates`、`hard_gate_min_sample`、`suites`、`sensitive_patterns`、`metrics` **完全相同**；差异只有 `status`（unapproved→approved）、`approval`、`p2_standards.status/approved_at/basis`、`notes`。
- 批准文件的 `approval.template_config_hash` 显式记录 `d1097573…`，`template_sha256=3af301db…`，即批准动作就是"给同一语义的 v0.3 门槛加批准状态"。
- `p2_standards` 对 N/C/U 的批准口径为 8/8、6/6、10/10，与历史目标一致。
- 因此：历史 run 的旧摘要绑定在**硬门禁语义**上与当前门槛等价，可作为正式证据的**原身份**保留（无需重绑 `7fa6f47a…`），并作为 D-005 适用性证明的"旧版本等价"要件；但门禁字段级失败（§2/§3）不因该等价性而消失。

复算命令：`scripts/config_equivalence.py` → `frozen canonical hash = d1097573…`、`approved canonical hash = 7fa6f47a…`、7 类语义键 `identical=True`，退出码 0。

---

## 12. 验收命令、退出码与关键输出

| # | 命令 | 退出码 | 关键输出 |
| --- | --- | --- | --- |
| 1 | `.\.venv\Scripts\python.exe -m pytest backend/tests/acceptance/test_t09_mutation.py -q` | **0** | `13 passed, 1 warning in 21.25s` |
| 2 | `.\.venv\Scripts\python.exe -m pytest backend/tests/acceptance/test_t09_mutation.py -q --collect-only` | **0** | `13 tests collected in 0.02s`，名称与历史 13 条逐字一致 |
| 3 | `.\.venv\Scripts\python.exe -X utf8 docs\reports\OBS-EVAL\P2\NCU-RELEASE-EVIDENCE\scripts\gate_recompute.py` | **0**（脚本）；被评 run 门禁退出码 R1=1、R2=1、R4=1 | 新 `gate.py`（`e04990db…`）+ `build_gate_rows(case_rows=…)`：R1 `trace_integrity fail 27`；R2 `citation_required pass`、`conflict_not_rejected fail C05`（范围外）、`trace_integrity fail U01+C05`；R4 `security_leak pass`、`conflict_not_rejected pass`、`trace_integrity fail C05+C06` |
| 4 | `.\.venv\Scripts\python.exe -X utf8 docs\reports\OBS-EVAL\P2\NCU-RELEASE-EVIDENCE\scripts\config_equivalence.py` | **0** | `d1097573…` / `7fa6f47a…`；7 类语义键全同 |
| 5 | `.\.venv\Scripts\python.exe -X utf8 docs\reports\OBS-EVAL\P2\NCU-RELEASE-EVIDENCE\scripts\u01_reconstruct.py` | **0** | chunk `a202ff9b…` → `record_unit 072d28f2…` → `sheet:物品位置:row:8`；`rag_meta.revision=4 / product_revision=3` |
| 6 | `.\.venv\Scripts\python.exe -X utf8 docs\reports\OBS-EVAL\P2\NCU-RELEASE-EVIDENCE\scripts\build_evidence.py` | **0** | 6 条 trace 全部 `closes=True` |
| 7 | `.\.venv\Scripts\python.exe -X utf8 docs\reports\OBS-EVAL\P2\NCU-RELEASE-EVIDENCE\scripts\build_manifest.py` | **0** | 写出 `manifest.json`；四档 adopt + 两行 tallies + `hard_gate_min_sample.unmet` |
| 8 | `.\.venv\Scripts\python.exe -X utf8 docs\reports\OBS-EVAL\P2\NCU-RELEASE-EVIDENCE\scripts\verify_manifest.py docs\reports\OBS-EVAL\P2\NCU-RELEASE-EVIDENCE\manifest.json` | **0** | `{"ok": true, "cases": 24, ...}`（v0.2 回源 + 四档状态校验） |
| 9 | `.\.venv\Scripts\python.exe -X utf8 docs\reports\OBS-EVAL\P2\NCU-RELEASE-EVIDENCE\scripts\negative_tests.py` | **0**（生成 12 个负例）；每个负例校验器 exit 1 | A1–A6 + B1/B2/B5 + B7/B8/B9，全部按原因码拒绝，见 §10.1 |
| 10 | `.\.venv\Scripts\python.exe -X utf8 docs\reports\OBS-EVAL\P2\NCU-RELEASE-EVIDENCE\scripts\build_hashes.py` | **0** | 重生成 `evidence/artifact-hashes.json` 与 `SHA256SUMS`（最后一步，覆盖 `evidence/gate_recompute_r2.json` 等） |
| 11 | 回归：独立重算逐题状态 vs 既有 `case_scores.json` | — | R1 52/52、R2 2/2、R4 3/3 **全部相等** |

环境：`.\.venv\Scripts\python.exe` 3.12.7、pytest 9.1.1（未新建 venv、未 pip install）。

复现顺序（隔离目录已被清理时）：先跑 `scripts/prepare_isolated.py`（从 `D:\mktkb-p2-run\t207\` 复制 trace/rag/product 只读副本，按 `artifact-hashes.json` 逐份校验 SHA，退出码 0），再按上表 3→9 顺序执行（`scripts/gate_recompute.py` 会自行复制数据集并只改诊断副本的 `trace_store/dataset_path`），最后跑 10 一次性生成两个 SHA 清单。所有命令均不发起网络请求。

---

## 13. 需要经理决策的事项

1. **D-005 已落地**：6 条 trace 双计数题按 `ADOPTED_WITH_BINDING_PROOF` 采信，机械 FAIL 保留；若主人撤回 D-005，则回到 `FAIL`，正式可采降为 N 7/8、C 2/6、U 9/10。
2. **D-004 已落地**：U01 `citation_required` 转 pass（evidence ∪ retrieved；`build_gate_rows` 需 `case_rows` 投影）。判据未放宽，"既不在 evidence 也不在 retrieved"仍 fail。
3. **U 最小样本口径（T-5）**：`update_delete` 批准最小样本 10，而 run 级只有 1；已按 `PENDING-MASTER-DECISION` 记录，请主人裁量（接受 1R+9L / 补 9 题真实 run 证据 / 接受阻断）。
4. **是否派工修复 T-1（trace/gate 契约）**：让 N/C/U 乃至 B0 在机械口径下同时转 clean 的唯一不涉真实请求路径；属 `backend/src` 与契约变更，执行者无权自改。
5. **是否接受文档级 `source_hit`**（C05/C06/U01 的 `record_code:P01`）：接受 → 以 §3.1 重建补证；不接受 → 需批准更新冻结题集（本执行者未改）。
6. **是否要求 `review.md` 覆盖 6 条 trace 的字段级复核**（本报告已给出逐条证据，独立窗口可直接比对）。

---

## 14. 本次触达的路径（git status 口径）

- 新增交付：`docs/reports/OBS-EVAL/P2/NCU-RELEASE-EVIDENCE/`（`report.md`、`manifest.json`、`review.md` 由复核窗口写、`evidence/`〔含改前 `gate_recompute.json`、改后 `gate_recompute_r2.json`、`trace-adjudication.json`、`u01-citation-reconstruction.json`、`negative-tests.json`、`artifact-hashes.json`〕、`scripts/`、`SHA256SUMS`）。
- 隔离目录 `.tmp-ncu-isolated/`：返工期间为回源重建，交付前再次清理（未跟踪、自建自清）；可用 `scripts/prepare_isolated.py` 复现。
- 未修改：`backend/src/**`、`backend/tests/**`、`docs/evaluation/**`、`docs/reports/OBS-EVAL/P2/T207/**`、`review.md`，以及工作树其余既有未提交改动。
- 未做：切换分支、checkout/restore/stash/clean/reset、commit、push、merge、删除或移动既有文件。

---

## 15. 交付文件 SHA-256

见 `evidence/artifact-hashes.json` 与 `SHA256SUMS`（由 `scripts/build_hashes.py` 生成）；本报告与清单的最终 SHA 在返工 R1 的回报中给出。

---

## 16. 返工 R1（复核意见 → 处置 → 实测）

复核窗口结论 `PASS-WITH-RESERVATIONS`，24 题判定、身份绑定、八门禁、旧版本等价、U01 重建、6 条 trace 双计数解释均以**原始 run 数据**独立复现成立；**adopt 结论与计数不变**。本节记录保留意见的逐条处置。

### 16.1 R1-1 校验器回源（必须）

| 复核负例 | 返工前 | 返工后 |
| --- | --- | --- |
| B1：N05 `question_sha256` 换成另一个合法 64 hex | exit 0（只查长度） | **exit 1**：`QUESTION_HASH_MISMATCH:N05:frozen`、`:run_cases`，并连带 `TRACE_CASE_MISMATCH:N05:question_hash` |
| B2：N02（ADOPTED）`evidence_paths` 指向不存在文件 | exit 0（不查存在性） | **exit 1**：`EVIDENCE_PATH_MISSING:N02:run_cases` |
| B5：N02 与 N03 互换 `trace_id` | exit 0（不与 trace 库交叉） | **exit 1**：`TRACE_CASE_MISMATCH:N02:question_hash`、`TRACE_CASE_MISMATCH:N03:question_hash` |

实现（`scripts/verify_manifest.py` v0.2）：

1. `question_sha256` 三方回源：冻结题集 `sha256(question)`、run `cases.jsonl` 同题 `product.question_sha256`、trace DB 中该 `trace_id` 的 `question_hash`；任一不等即拒。
2. `evidence_paths` 每个路径必须存在；`evidence_sha256` 记录值必须与真实文件一致（新增，manifest 每条目含 8 个 R 口径证据路径或 3 个 L 口径证据路径）。
3. `trace_id` 必须存在于该 run 的 trace DB；trace 的 `run_id`、`question_hash`、`config_hash`、`pipeline_version`、`dataset_version`、`manifest_sha256`、`index_revision`、`path`、`outcome_kind` 必须与本 run / 本题声明一致。
4. 负例集扩到 **9 个**（A1–A6 + B1/B2/B5），`scripts/negative_tests.py` 逐条断言 exit 1 且原因码正确；输出落 `evidence/negative-tests.json`。
5. 真实 manifest 回源校验：**exit 0**、`{"ok": true, "cases": 24, "tallies": …}`。

命令与实测（全部 `.\.venv\Scripts\python.exe -X utf8`）：

| 命令 | 退出码 | 关键输出 |
| --- | --- | --- |
| `python -X utf8 docs\reports\OBS-EVAL\P2\NCU-RELEASE-EVIDENCE\scripts\verify_manifest.py docs\reports\OBS-EVAL\P2\NCU-RELEASE-EVIDENCE\manifest.json` | **0** | `{"ok": true, "cases": 24, "tallies": {"judged_pass": {"N": "8/8", "C": "6/6", "U": "10/10", ...}, "adopted_unconditional": {"N": 7, "C": 2, "U": 9}, ...}}` |
| `python -X utf8 docs\reports\OBS-EVAL\P2\NCU-RELEASE-EVIDENCE\scripts\negative_tests.py` | **0**（生成/断言） | 9/9 负例 `OK`：A1 `WRONG_BINDING`、A2 `DUPLICATE_CASE`、A3 `U_TYPE_MIXED`、A4 `SAMPLE_INSUFFICIENT`、A5 `MISSING_TRACE`、A6 `MISSING_CITATION_EVIDENCE`、B1 `QUESTION_HASH_MISMATCH`、B2 `EVIDENCE_PATH_MISSING`、B5 `TRACE_CASE_MISMATCH`；每个负例校验器 exit 1 |
| `python -X utf8 docs\reports\OBS-EVAL\P2\NCU-RELEASE-EVIDENCE\scripts\build_hashes.py` | **0** | 重生成 `evidence/artifact-hashes.json`（46 键）与 `SHA256SUMS` |

### 16.2 R1-2 七处修正（必须）

| # | 复核意见 | 处置 | 位置 |
| --- | --- | --- | --- |
| 1 | §7 与 §4/§12 矛盾："无产品执行/未执行产品代码路径" | **已改**：改为"未对生产数据与真实 provider 执行产品；L 口径经 `TestClient` 在进程内启动完整产品应用（Mock/替身 provider），执行解析/入库/检索/问答代码路径；未启动监听端口服务" | §7 表格"产品执行边界"行 |
| 2 | §10.2 第 1 条声称校验器"trace 与 run cases 同时命中"，实现不符 | **已实现后再保留**：校验器 v0.2 三方回源，§10.2 第 1 条同步写明"v0.2 已实现回源" | §10.2 第 1 条；§16.1 |
| 3 | `artifact-hashes.json` 与 `SHA256SUMS` 无生成脚本 | **已补** `scripts/build_hashes.py`，并接入 §12 复现顺序第 10 步（最后执行） | §12 第 10 行及复现顺序；§16.1 命令表 |
| 4 | §2.1 "两个计数器按设计不同"易读成"门禁失败是预期" | **已改**：改为"T209 attempt2 定性为运行接线的一致性缺陷；冻结契约仍要求两侧相等；attempt3 修复方向是把 manifest 绑定改到 RAG 实际 revision；本报告只解释、不豁免" | §2.1 计数段 |
| 5 | §2.1 行号 `qa/service.py:935` 实为 `manifest_summary()` | **已改**：改用 `qa/service.py:376-379`（`product_revision` 与 `index_revision` 并列），保留 `product_adapter.py:1632/1661` | §2.1 第 1 条 |
| 6 | §3.2 "同 run 的 C05"含糊（R2.C05=1、R4.C05=0） | **已改**：明确写 **R2.C05 `retrieved=1`、R1.Q01 `retrieved=1`、R4.C05 `retrieved=0`**，并说明不能拿 R4.C05 当对照 | §3.2 |
| 7 | §5 顶层"判定通过 U 10/10"是评分层，硬门禁层 9/10 | **已改**：新增"两层不可混读"条目（R1 时点：机械层 9/10、未达门槛）。R2 后见 §17：机械层仍 9/10，D-005 证明后正式层 10/10，U 另有最小样本 `PENDING-MASTER-DECISION` | §5 表后第 1 条 |

### 16.3 R1-3 复核窗口的两项加固（必须写入）

| 加固发现 | 处置 | 位置 |
| --- | --- | --- |
| 全部 57 条 trace 按"有无 recall span"严格二分：R1 27/27、R2 2/2、R4 2/2 命中 RAG 计数；无 recall 的 25/25、0、1/1 全部等于 manifest；**0 例外** | **已写入**为 §2.2.1 全量二分表，并说明它排除"错绑到别的 run/索引"、但不等于契约下正确 | §2.2.1 |
| 57 题中唯一 `path="rag"` 的 answer 就是 U01，且只有它 `retrieved` 为空；其余 41 条非 rag 路径 answer `retrieved` 全非空 | **已写入**：把"该轮字段缺失"升级为"`rag` 打包路径特有的响应形状缺陷" | §3.2 第 2 段 |

### 16.4 结论影响

> 本节是 **R1 时点**记录（当时状态档为 `RETAINED-OLD` / `FAIL`）。R2 按主人 D-004/D-005 改为四档并重算，见 §17；两节数字不得混用。

- **adopt 结论与计数不变**：判定通过 N 8/8、C 6/6、U 10/10；无条件可采 N 7/8、C 2/6、U 9/10；`RETAINED-OLD` 1/4/0；`FAIL` U01；`UNKNOWN` 0。
- 返工只提升**可复核性与措辞准确性**，未把任何 `RETAINED-OLD` 升级为 pass，也未把 U01 升级为 pass。
- 零真实请求：本返工只读原始 run 数据与仓库文件；校验器/负例/哈希脚本均不发起网络调用。

---

## 17. 返工 R2（D-004/D-005 落地）

本轮把主人决定落进清单与报告：**D-004**（`citation_required` 候选接地集合 = `outcome.evidence[].unit_id ∪ outcome.retrieved[].unit_ids`，判据不变）与 **D-005**（接受历史绑定适用性证明作为正式 N/C/U 证据口径，必须全程披露原始机械 FAIL，`trace_integrity` 逐值相等语义不改）。**未修改 `backend/` 任何文件、未改 `review.md`、零真实请求。**

### 17.1 `gate.py` 改前/改后

| 项 | 值 |
| --- | --- |
| 当前（D-004 后）SHA-256 | `e04990db52d72c06dcd4e87fea8f80644171fd5b686810bc0fa6aa3fa8c831b7` |
| HEAD（`97b00667`）版本 SHA-256 | `7e54fbf672cbc1c02bbe746c164038613d5861070796794f6a41aae1595b7fe7`（`git show HEAD:…` 重算） |
| 任务 4 交接的"改前"SHA | `10235099…`（未提交中间态，无法从 git 重建；按交接记录引用） |
| 唯一变更 | `citation_required` 的候选接地集合增加 `outcome.evidence[].unit_id`（`gate.py:1696-1704`，含 D-004 注释） |
| 未改 | 三个拒绝分支（`citation_missing` / `citation_not_unit_level` / `citation_not_in_evidence`）逐字未动；`trace_integrity` 的 `_TRACE_BINDING` 逐值相等语义未动（diff 统计：18 行增、2 行删，集中在候选集合构造） |
| **接线前提（重要）** | 仅改 `gate.py` 不足以让 U01 转 pass：`outcome.evidence` 来自 `build_gate_rows(..., case_rows=<原始 run 行>)` 的投影（`p2_scoring.py:2286-2288`）。本窗口第一次重算未传 `case_rows`，U01 仍 fail；传 `case_rows` 后才 pass。任务 4 接线时必须同时满足这两点。 |

### 17.2 R1/R2/R4 八门禁重跑（新 `gate.py` + `case_rows` 投影）

命令：`python -X utf8 docs\reports\OBS-EVAL\P2\NCU-RELEASE-EVIDENCE\scripts\gate_recompute.py`（脚本 **exit 0**；脚本内被评 run 门禁退出码见下）。输出：`evidence/gate_recompute_r2.json`（改前旧引擎结果仍保留在 `evidence/gate_recompute.json`，仅作对照）。

| run | 门禁退出码 | 八项状态（新引擎） | 关键失败 |
| --- | --- | --- | --- |
| R1 | **1** | security/cross/stale/conflict/pagination `not_applicable`；exact `pass`；citation `pass`；trace `fail` | `trace_integrity: version_binding` 27 条（Q01–Q24 + N01 + C01 + C02） |
| R2 | **1** | security `pass`；conflict `fail`（C05，范围外）；citation `pass`；trace `fail` | `trace_integrity` U01 + C05（C05 范围外）；`conflict_not_rejected` C05（范围外，R4 已替换） |
| R4 | **1** | security `pass`；conflict `pass`；citation `not_applicable`；trace `fail` | `trace_integrity` C05 + C06 |

- **U01 `citation_required` 已 fail → pass**：改前 `evidence/gate_recompute.json` 为 `U01: citation_not_in_evidence {"unit_ids":["072d28f2-…"],"evidence_units":0}`；改后 `evidence/gate_recompute_r2.json` 为 `citation_required: pass, fails=0`。
- N/C/U 范围内，新引擎的机械失败**只剩** `trace_integrity: version_binding` 6 条（N01、C01、C02、U01、C05、C06），与 D-005 的适用对象一一对应。

### 17.3 四档 adopt 与两行 tallies

| 档位 | N | C | U |
| --- | --- | --- | --- |
| `ADOPTED`（八门禁无任何机械 FAIL） | 7 | 2 | 9 |
| `ADOPTED_WITH_BINDING_PROOF`（机械 FAIL 保留 + D-005 证明） | 1（N01） | 4（C01,C02,C05,C06） | 1（U01） |
| `FAIL`（不可解释失败） | 0 | 0 | 0 |
| `UNKNOWN`（证据不足） | 0 | 0 | 0 |
| **无条件可采（无任何机械 FAIL）** | **7/8** | **2/6** | **9/10** |
| **正式可采（含 D-005 证明）** | **8/8** | **6/6** | **10/10** |

- 清单 `tallies` 同时保留 `adopted_unconditional`、`adopted_with_binding_proof`、`adopted_formal_total`（含 `threshold_met`），并带 `label` 字段，避免只读一行。
- 6 条证明档的 `gates.trace_integrity.status` 仍是 `fail`，`mechanical_gate_failures` 留痕 `trace_integrity:version_binding`；`binding_proof` 写 D-005、身份、逐阶段索引版本、同回合证据引用、旧版本等价性，`adopt_reason` 明写"机械 FAIL 保留、按 D-005 以证明采信"。
- U01 的 `binding_proof` 另在 `adopt_reason` 注明 `citation_required` 已按 D-004 转 pass。

### 17.4 校验器适配与新负例（实际输出）

`verify_manifest.py` 新增：`ADOPTED_WITH_BINDING_PROOF` 必须同时满足 ①机械 FAIL 记录仍在且与 `gates` 一致 ②`binding_proof` 五要素（decision/identity/per_stage/同回合证据/旧版本等价）齐全 ③原始身份字段齐全。真实 manifest 仍 **exit 0**、`{"ok": true, "cases": 24}`。

| 负例 | 期望 | 实际输出 | exit |
| --- | --- | --- | --- |
| B7：N01 清空 `mechanical_gate_failures` | `BINDING_PROOF_WITHOUT_MECHANICAL_FAIL` | `["BINDING_PROOF_WITHOUT_MECHANICAL_FAIL:N01:no_mechanical_record"]` | 1 |
| B8：N01 删除 `binding_proof` | `BINDING_PROOF_MISSING` | `["BINDING_PROOF_MISSING:N01"]` | 1 |
| B9：N01 把 `trace_integrity` 强改 `pass` 但保留机械记录 | `BINDING_PROOF_WITHOUT_MECHANICAL_FAIL` | `["BINDING_PROOF_WITHOUT_MECHANICAL_FAIL:N01:no_gate_fail"]` | 1 |

负例集现为 **12 个**（A1–A6 + B1/B2/B5 + B7/B8/B9），机器输出 `evidence/negative-tests.json`。

### 17.5 显式限制：U 的最小样本口径（不解决，只记录）

- 事实：R2 的 run 级 `evaluated_by_suite = {"boundary": 1, "update_delete": 1}`；U 组只有 U01 是 run 行，其余 9 条是本地控制（L）。
- 批准配置 `docs/evaluation/gate_v0_3_approved.json` 的 `hard_gate_min_sample.update_delete = 10`（顶层同名字段）。
- 因此 **U 的八项硬门禁在批准最小样本口径下无法满足**；该冲突由经理另报主人裁量。
- 落盘位置（三处一致）：`manifest.json#hard_gate_min_sample.unmet = {suite:"update_delete", evaluated:1, required:10}`、`manifest.json#hard_gate_min_sample.status = "PENDING-MASTER-DECISION"`、`manifest.json#open_items[id=hard-gate-min-sample-u]`；报告 §5 与本节。
- 处理边界：本清单不自行放宽、不把 1R+9L 冒充 10 条 run 证据、不因此改动 U 的 adopt 档位（U 的档位只由机械门禁 + D-005 证明决定）。

### 17.6 结论与不变项

- 四档计数：`ADOPTED` N7/C2/U9；`ADOPTED_WITH_BINDING_PROOF` N1/C4/U1；`FAIL` 0；`UNKNOWN` 0。
- 两行 tallies：无条件 **7/8、2/6、9/10**；正式（含 D-005）**8/8、6/6、10/10**。
- **`FAIL` 数量：0**（U01 不再是 FAIL，而是带机械 FAIL 记录的证明档）。
- 判定层 N 8/8、C 6/6、U 10/10 不变；旧版本等价性证明、U01 引用重建、57 条 trace 二分等既往证据不变。
- 零真实请求；未改 `backend/`、`review.md`、`docs/evaluation/`、`T207/`。

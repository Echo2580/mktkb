# T003c 独立验收报告（RAG 路径 Span 埋点）

> 角色：独立验收者（与开发助手不共享上下文）。本报告只认本人复跑/独立探针结果；
> 开发报告 `.claude/handoffs/T003c-rag-spans/report.md` 仅作线索，不作为任何 PASS 依据。
> 验证对象：分支 `p0/obs-eval`，commit `776497faa6081d7dafb888a773d7c09ea95d481c`
> （`776497f`，`p0/T003c rag spans`，parent `d41d19f`，基线 `main` @ `8e44158`）。
> 时间：2026-11-05 02:46–03:30（Asia/Shanghai）；Windows / PowerShell 5.1 / Python 3.12.7 / pytest 9.1.1。
> 复跑证据：`docs/reports/OBS-EVAL/P0/evidence/verify/T003c/`（本报告引用的 00–13 文件均在该目录）。
> 本报告与探针脚本均为未跟踪文件；未修改交付物、未改代码、未 commit、未 push、未改 `_index.md`。

## 0. 结论（逐条）

| # | 验收项 | 判定 | 一句话依据 |
| --- | --- | --- | --- |
| §5.1 | 无 trace 时零行为变化 | **PASS** | `03-plain-old-vs-new.txt`：`git archive d41d19f` 旧代码 vs `776497f` 新代码，无 trace 下 5 个场景（answer/第二轮/clarification/文档 no_answer/DOCUMENT_NOT_FOUND）`RagAnswer.to_dict()` 去耗时后逐字段一致；无隐式 trace/DB（`04` 5.1a） |
| §5.2 | answer 路径 Span 完整、recall 父子结构、未执行通道无 Span | **PASS** | `04` 5.2/5.2b：record 模式恰 12 Span、document 模式无 `exact_recall`；`required_spans(RAG, ANSWER) ⊆ names`；`recall` 父、`embedding_query` 挂 `vector_recall`、`hard_filter`/`rerank` 挂 `fuse`；`validate_required_spans == []` |
| §5.3 | vector/rerank 条件 Span 开/关与 canonical 位置 | **PASS** | `04` 5.3a/5.3b/5.3c：启用时两者都出现且 `conditional_required_spans(filter_decisions_json) == {vector_recall, rerank}`；`disable_query_embedding=True` 时 embedding 零调用、无 vector/embedding Span、flag=false；空融合无 rerank、flag=false；条件属性只并入 `filter_decisions_json` |
| §5.4 | 早退路径 `validate_required_spans` 通过且不伪造 | **FAIL（仅 1 个子项）** | clarification / 检索后 no_answer / conflict / knowledge_changed 均 PASS；**DOCUMENT_NOT_FOUND（检索前 no_answer）在 `outcome_kind=no_answer` 下 `validate_required_spans` 返回缺失 `['fuse','recall']`**（`04` 5.4b；`contracts.py:59` 要求 `rag+no_answer` 含 recall/fuse）。这是 T001 冻结表与业务早退路径的冲突，不是 T003c 伪造 Span；详见 §4.1 |
| §5.5 | attributes 全部 canonical JSON、只含计数/布尔/稳定引用、零原文泄漏 | **PASS** | `04` 5.5a/5.5b：所有 `*_json` 与 Span attributes 均为 canonical JSON；问题/答案/证据原文/原始 chunk_id 在 record + 全部 Span attributes + trace SQLite 落盘字节中均不出现；`citation_refs_json` 为 `D01 + 16 位 unit hash + locator`；`filter_decisions_json.applied_filters` 只有键名 |
| §5.6 | 异常路径 Span status=error、异常原样上抛 | **PASS** | `04` 5.6a–5.6d：`_fuse` 注入 RuntimeError 原类型/原文上抛，`fuse` Span error、trace error；embedding 失败只降级、`embedding_query` error；FactRejected 拒答、`fact_validate` error；rerank 失败回退 RRF、rerank Span error、trace 仍 ok（既有语义） |
| §5.7 | 既有测试与全量无新增失败 | **PASS** | `01` = 20 passed；`02` = 506 passed；`07` = **1216 passed, 0 failed, 0 error**（569.72s）；`08` = 旧提交 collect **1196 tests**（+20 与新增文件一致）；无 flake（middleware 3 次全套 + 5 次定点全绿，`06`） |
| §5.8 | 硬约束 | **PASS** | 无新增依赖（commit 无 pyproject/lock；`trace_attrs.py` 只 import stdlib + `.tracer`）；零真实模型/embedding/rerank（socket 守卫下 0 次网络，`04`）；不读 `.env`；`RagAnswer`/`RetrievalResult` 字段集与 `types.py` 未变；API 路由/`qa`/`conversations`/`main.py`/`config.py` 零改动 |
| — | PM 授权测试修改 | **PASS** | `git show 776497f -- test_middleware.py` 恰 2 行断言（`spans == []` → `spans and {"recall","fuse","hard_filter"} <= ...`），numstat `2/2`；无其它断言/文件改动；独立 middleware 探针确认 spans 非空且核心 Span 真实存在（`13`） |
| — | 提交边界 | **PASS** | `10-commit-boundary.txt`：15 个文件全部落在 handoff §2/PM 授权范围内；无 `qa/`、`conversations/`、`main.py`、`config.py`、观测内核、其它既有测试、pyproject、docs/evidence、var、fixtures；仅 `test_middleware.py` 一个既有测试被改（2/2） |
| — | 证据卫生 | **PASS（附 minor）** | 00–08 均已提交（`git ls-tree` 9 个文件）；4 个未跟踪残留（02-package/03-observability-rag/04-full/07-test-middleware.diff）在验收开始时存在于工作树、**不在 commit 中**，验收期间被外部清理（本人未删除）。minor：05/08 是 amend 前 C1 统计、00-baseline 非“开工前”干净快照（见 §4.3） |
| — | 测试非空转（仓库外变异） | **PASS（附 1 个覆盖缺口）** | `05-mutation-probes.txt`：控制组 20 passed；M1 删 fuse Span → 9 failed；M2 vector Span 恒出现 → 1 failed；M3 写问题原文进 attributes → 1 failed；M4 异常不标 error → 3 failed。附加 M5“rerank 失败不标 error”**未被开发测试捕获**（20 passed），但独立探针 5.6d 验证了真实行为正确（见 §4.2） |

**总判定：FAIL（1 项：§5.4 的 DOCUMENT_NOT_FOUND/检索前拒答子项；其余全部 PASS）。**

- 该 FAIL **不是 T003c 埋点实现的缺陷**：T003c 按“未执行不伪造”正确实现（只有 parse+commit），且开发报告 §4.3/§5 已主动披露该契约缺口；
- 但 handoff §5.4 的字面标准（该 path+outcome 的 `validate_required_spans` 通过）在该子项上确实不成立。**建议 PM 先裁决（T003d outcome 映射 / T005 表义），不建议直接重写 T003c 代码**；若 PM 认定 §5.4 的 `no_answer` 仅指“检索后拒答”，则本包可带该已披露风险通过。

## 1. 验收方法与独立性声明

1. 全程只读验收：未修改任何交付物/代码/测试；未 commit/push；未改 `_index.md`。本人产物只有本 `review.md`
   与 `docs/reports/OBS-EVAL/P0/evidence/verify/T003c/` 下的复跑证据（均未跟踪、未提交）。
2. 亲自复跑 handoff §6 全部命令（每条前缀 `$env:MKTKB_PROJECT_TOTAL_LIMIT_CNY="20.0"`，
   `.\.venv\Scripts\python.exe -B -m pytest ... -q -p no:cacheprovider --basetemp ...`；串行执行，未并发）。
3. 独立编写 5 个探针/审计脚本（不 import 开发测试的 helper，不修改仓库）：
   - `probe_plain.py` / `compare_plain.py`：用 `git archive` 解出的旧/新 `backend/src` 各跑一次无 trace 固定场景，逐字段比较；
   - `probe_traced.py`：20 条独立行为断言（PASS 19 / FAIL 1，失败项即 §5.4b 契约缺口），覆盖 §5.1–§5.6 与硬约束；
   - `probe_middleware.py`：真实 `create_app` + QA POST，验证 PM 授权断言非空转与 trace 字段；
   - `mutate_verify.py`：仓库外副本的 4 组变异探针 + 控制组；
   - 附加 M5 一次性变异（rerank error 标记）用于测试覆盖审计。
4. 关键事实均从源码（`文件:行`）与运行时行为双向核对；开发报告中的数字/行号仅用于对照。

## 2. 实测命令与结果（handoff §6）

环境：`git branch --show-current` → `p0/obs-eval`；`git rev-parse --short HEAD` → `776497f`
（handoff 中“应为 d41d19f”是开发开工基线；本包 parent 正是 `d41d19f`，`main` @ `8e44158`）。

```powershell
# ① 本包测试（证据 01）
.\.venv\Scripts\python.exe -B -m pytest backend/tests/observability/test_rag_spans.py -q -p no:cacheprovider --basetemp backend\.pytest-tmp\verify-t003c-rag-spans
# → 20 passed, 1 warning in 1.40s（exit 0）

# ② handoff §6 范围套件（证据 02）
.\.venv\Scripts\python.exe -B -m pytest backend/tests/rag backend/tests/observability -q -p no:cacheprovider --basetemp backend\.pytest-tmp\verify-t003c-rag-obs
# → 506 passed, 1 warning in 51.39s（exit 0）

# ③ 全量（证据 07）
.\.venv\Scripts\python.exe -B -m pytest backend/tests -q -p no:cacheprovider --basetemp backend\.pytest-tmp\verify-t003c-full
# → 1216 passed, 1 warning in 569.72s (0:09:29)（exit 0；0 failed / 0 error / 0 skipped）

# ④ 提交 stat（证据 10）
git show --stat --oneline HEAD
# → 776497f p0/T003c rag spans；15 files changed, 1447 insertions(+), 75 deletions(-)
```

补充独立基线（证据 08）：`git archive d41d19f backend/src backend/tests backend/migrations backend/pyproject.toml`
+ 工作树 `fixtures/`（T003c 未改 fixtures）解出副本后 `pytest tests --collect-only -q` → **1196 tests collected**。
与 1216 − 20（`test_rag_spans.py` 20 tests）一致。

**flakes**：全量一次通过；middleware 全套 3 次（20 passed ×3）+ PM 授权的 2 条定点 5 次（2 passed ×5）均通过（证据 06）。
开发报告 §4.9 提到的“13 Span 时旧 `spans == []` 失败”本次未复现（该断言已按授权替换；13 Span 现象本身在真实 QA POST 中可复现，见 §3.9）。

## 3. 逐条独立核验明细（源码 + 运行时）

### §5.1 无 trace 时零行为变化 — PASS

- 结构保证：`trace_attrs.py:42-54`（无 `current_trace()` → `yield _NULL_SPAN`，不落任何记录）、
  `:57-61`（`annotate_trace` 无 Trace 时 no-op）；业务代码没有隐式 `start_trace`。
- 独立对照（证据 03）：`git archive d41d19f` 与 `776497f` 各解出一份 `backend/src`，用同一
  `probe_plain.py`（固定单号 `D01-fixed-0`、固定问题）各跑两次 `RagIndex.ask` + 3 个早退场景，
  去掉 `elapsed_ms/ms/vector_query_ms/latency_ms` 后 `RagAnswer.to_dict()` **5/5 场景逐字段一致**
  （`plain-old.json` / `plain-new.json` / `03-plain-old-vs-new.txt`）。场景实际 kind/reason：
  answer / answer（第二轮 turn=2） / clarification(EMPTY_QUERY) / no_answer(NO_SUPPORTING_SENTENCE) /
  no_answer(DOCUMENT_NOT_FOUND)。
- 无隐式 trace/DB（证据 04 5.1a）：无 trace 时 `current_trace() is None`；运行后 `tmp` 根下只有
  `rag.sqlite3`，无任何名字含 `trace/observ` 的文件。
- 全量 `backend/tests` 1216 passed 也覆盖了无 trace 的既有 RAG 测试（证据 07）。

### §5.2 answer 路径 Span 完整且父子结构正确 — PASS

- 源码：`answer.py:37`（parse）、`:159`（answer）、`:189`（fact_validate）、`:210`（commit）；
  `retrieval.py:46`（recall）、`:48`（exact_recall）、`:54`（lexical_recall）、`:61`（vector_recall）、
  `:298`（embedding_query）、`:464`（hard_filter）、`:80`（fuse）、`:486`（rerank）。
- 独立探针（证据 04 5.2）：record 固定问题 trace 的 Span 名称集合**恰为 12 个**
  `{parse, recall, exact_recall, lexical_recall, vector_recall, embedding_query, hard_filter, fuse, rerank, answer, fact_validate, commit}`；
  `required_spans(RAG, ANSWER) ⊆ names`；`validate_required_spans == []`；
  `recall` parent=None，exact/lexical/vector 均挂 recall，`embedding_query` 挂 `vector_recall`；
  `fuse` parent=None，`hard_filter`/`rerank` 挂 fuse；`parse` 首、`commit` 尾；全部 status=ok、error_code=None、
  duration≥0；每个 Span 的 attributes_json 可解析。
- 未执行通道（证据 04 5.2b/5.3b/5.3c/5.4c）：
  - document 模式无 `exact_recall`（`_exact_recall` 在 `plan.mode != "record"` 时于 `retrieval.py:228`
    直接 return，未访问 DB；不产生 Span 是诚实的）；
  - `disable_query_embedding=True` 无 `vector_recall`/`embedding_query`；
  - 空融合无 `rerank`；检索后 no_answer 无 `fact_validate`；
  - 检索前早退无 `recall/fuse/answer`。
- document 模式 answer 路径（补充探针 5.2b）：构造段落型资料后提问，answer 路径 required 集合齐、
  `validate == []`、无 `exact_recall`。

### §5.3 条件 Span 正确、属性在 canonical 位置 — PASS

- 源码：`retrieval.py:44`（`vector_enabled = not disable_query_embedding`）、`:60-67`（仅启用时建 vector_recall）、
  `:83`（`rerank_enabled = "rerank" in diagnostics`，仅 `_fuse` 真实执行重排时 true）、
  `:141-154`（Trace 级 `filter_decisions_json` 写 flags 并另经 `annotate_trace(vector_enabled=..., rerank_enabled=...)`
  由 tracer 并入同一字段）。
- 独立探针（证据 04）：
  - 5.3a：启用时 `filter_decisions_json` 为 canonical，`vector_enabled=true`、`rerank_enabled=true`，
    `conditional_required_spans == {vector_recall, rerank}` 且两 Span 都在；其它 `*_json` 字段不含这两个 flag；
  - 5.3b：`disable_query_embedding=True` 时 patch embedder 为“一调用就 AssertionError”，结果 `calls == []`；
    无 vector/embedding Span；`filter_decisions.vector_enabled=false`；conditional 只剩 `{rerank}`；validate 通过；
    vector 计数=0；
  - 5.3c：空索引/空融合时无 rerank Span，`rerank_enabled=false`，conditional == `{vector_recall}`，validate 通过。
- 说明：`recall` Span 上额外有一个 `vector_enabled` 布尔属性（`retrieval.py:78`）；这是 Span 级冗余，
  不影响 tracer 约定的 Trace 级位置，也不被 `conditional_required_spans` 读取；不判为违规，仅记录。

### §5.4 早退路径不伪造 — **FAIL（仅 DOCUMENT_NOT_FOUND/检索前拒答子项）**

通过的子项（证据 04）：

- 5.4a clarification（“？”）：Span 严格 `{parse, commit}`，无 answer/recall/fuse，`validate == []`（outcome=clarification）。
- 5.4c 检索后 no_answer（空索引文档问题）：`required_spans(RAG, NO_ANSWER) ⊆ names`，无 `exact_recall`、
  无 `fact_validate`、`validate == []`；`answer` Span 存在，但 `_answer_document` 确实执行并判定 NO_EVIDENCE，
  是“真实执行”而非为凑必需集伪造（必需集不含 answer）。
- 5.4d conflict：answer/fact_validate 存在，`validate == []`，status ok。
- 5.4e knowledge_changed（monkeypatch `index.search` 抛 `KnowledgeChanged`）：Span 严格 `{parse, commit}`，
  `validate == []`（required `{parse, commit}`）。
- 代码层面，真实 revision 变化由 `retrieval.py:155` 抛出、`answer.py:132` 按 `RagError` 捕获并 `_commit`，
  与 knowledge_changed 同路径，Span 集合仍是 `parse + recall/fuse/hard_filter + commit`（超集），validate 通过。

**不通过的子项（证据 04 5.4b；证据 04-independent-probe 原文）**：

```text
FAIL 5.4b DOCUMENT_NOT_FOUND: only parse+commit, no fabricated retrieval/answer:
AssertionError: validate_required_spans 缺失=['fuse', 'recall']
```

- 复现：空索引 + 问题“促销活动台账在哪里？”→ `answer.kind=no_answer`、`reason=DOCUMENT_NOT_FOUND`；
  Span 恰为 `{parse, commit}`（`answer.py:73-84` 检索前返回）；但按用例映射
  `record.outcome_kind=no_answer` 后，`validate_required_spans` 依 `contracts.py:59`
  要求 `{parse, recall, fuse, commit}`，返回 `['fuse','recall']`。
- 同一代码路径还覆盖 `UNKNOWN_STORE`（`answer.py:100-114`）、`RECORD_ONLY`（`:115-128`）两种检索前 no_answer，
  行为相同：只有 parse+commit，若 outcome 映射为 `no_answer` 必然 validate 失败。
- 开发测试 `test_rag_spans.py:441-453`（`test_pre_retrieval_no_answer_does_not_fabricate_retrieval_spans`）
  断定了 `record.outcome_kind == "no_answer"` 与 `{parse, commit}`，但**刻意没有调用 `validate_required_spans`**；
  这是全部早退用例中唯一不调用 validate 的用例，等于把上述失败排除在测试之外。
- 开发报告已披露：report §4.3 与 §5“rag+no_answer 设计表与检索前拒答的缺口”明确建议 T003d 按 reason 区分
  或由 T005 收紧表义。因此这不是隐藏缺陷，但 handoff §5.4 的字面标准仍未满足。
- 归因与建议：T001 冻结表把 `rag+no_answer` 定义为“检索后拒答”，而 RAG 内核存在 3 种“检索前 no_answer”；
  在不伪造 Span 的前提下无法同时满足“validate 通过”。**不建议**在 T003c 里补 no-op recall/fuse（那才是伪造）；
  需要 PM 在以下方案中裁决：(a) T003d 对 `reason in {DOCUMENT_NOT_FOUND, UNKNOWN_STORE, RECORD_ONLY}`
  映射到一个 required 为 `{parse, commit}` 的 outcome（需语义自洽）；(b) T001/T005 明确该表只覆盖检索后拒答，
  为检索前拒答新增 outcome/表项；(c) 接受该缺口并让 gate 对 pre-retrieval 分支豁免（需设计层批准）。

### §5.5 attributes 合规 / canonical / 隐私 — PASS

- 源码：`retrieval.py:141-154`（index_revision/retrieval_counts_json/filter_decisions_json/degraded_json）、
  `answer.py:145-156`（pagination_json）、`:171-180`（citation_refs_json）、`:193/203`（fact_gate_json）。
- 独立探针（证据 04 5.5a）：
  - 所有 Trace `*_json` 字段（citation_refs/degraded/fact_gate/filter_decisions/pagination/retrieval_counts）
    与全部 Span `attributes_json` 均满足 `json.dumps(json.loads(x), ensure_ascii=False, sort_keys=True, separators=(",",":")) == x`；
  - 计数为 int（≥0）、条件为 bool；`citation_refs_json` 为 `D01 + 16 位 unit_id_hash + locator`，
    原始 `chunk_id` 不在其中；`filter_decisions.applied_filters` 只有 `["item","store"]` 键名，没有门店/物品值；
  - 问题原文、答案全文（含“店内外侧”）、证据行原文、原始 chunk_id 在整个 record + 所有 Span attributes
    中均不出现；`question_hash` 为 64 位摘要、`question_chars` 正确；
  - 允许的字符串叶子仅：`D01`、16 位 unit hash、`record/answer/structured` 等代码、
    `item/store` 键名、`mock/text-embedding-v4/offline-lexical/lexical-overlap-v1` provider/model、
    `sheet:物品位置:row:7` / `物品位置`（locator，设计 §6.3 允许 `doc_code + locator`）。
- 独立探针（证据 04 5.5b）：用真实 `TraceRepository` 落一条 answer trace，读取 DB + `-wal`/`-shm`
  全部字节，问题/答案原文均不出现；仅 `question_chars` 等计数可检索到。
- 说明：`citation_refs.locator` 会携带 sheet 名/unit_key/record_ref 短哈希；设计 §6.3 明确允许
  `doc_code + locator`，不属问题/答案原文，故判 PASS；若 T006 对 locator 有更严口径，需另行定义
  （本包未越界）。

### §5.6 异常路径 — PASS

- 源码：`retrieval.py:519-524`（rerank 失败：保留“回退 RRF 不抛”的既有语义，仅把 Span 标 error）；
  `tracer.py` 既有 `_mark_error` 负责 `with` 内异常自动标 error 并 re-raise；本包不改异常类型/时机。
- 独立探针（证据 04）：
  - 5.6a：monkeypatch `retrieval._fuse` 抛 `RuntimeError("PROBE-T003C-BOOM")`：`pytest.raises` 原类型/原文；
    `fuse` Span status=error / error_code=RuntimeError；trace status=error / error_code=RuntimeError；trace 仍写入 repo；
  - 5.6b：embedder 抛 `EmbeddingUnavailable`：不改变“降级继续作答”（answer 仍返回），
    `embedding_query` Span error；`degraded_json=["vector"]`；vector 计数 0；validate 通过；
  - 5.6c：`FactValidator.validate_record_text` 抛 `ForgedValue`：仍返回 no_answer 拒答；
    `fact_validate` Span error；`fact_gate_json={checked:true,passed:false,units:1,code:"FORGED_VALUE"}`；validate 通过；
  - 5.6d（补充）：reranker 抛 RuntimeError：answer 仍正常（RRF 回退），`rerank` Span error，
    trace status 仍 ok（既有语义），validate 通过。

### §5.7 既有测试与全量 — PASS（无 flake）

见 §2：20 / 506 / 1216；基线 collect 1196；`1216 = 1196 + 20`。全量输出无 failed/error/skipped；
middleware 3 次全套 + 5 次定点全绿。开发报告声称的 20/506/1216 均复现（耗时略有差异，属正常）。

### §5.8 硬约束 — PASS

- 无新增依赖：commit 不含 pyproject/lock/requirements；`trace_attrs.py:19-26` 只 import
  `hashlib/json/contextlib/typing` + `.tracer`；测试只用既有 pytest/仓库内模块。
- 零真实调用：`RagConfig(provider_mode="offline")`；socket 守卫下 `index.ask` 全程 0 次网络调用（证据 04）；
  embedding provider 为 `mock`、rerank provider 为 `offline-lexical`。
- 不读 `.env`：新代码无 `os.environ/dotenv`；探针显式 `_env_file=None`；全量测试沿用既有 conftest 隔离。
- 结构不变：`git diff d41d19f 776497f -- backend/src/mktkb/rag/types.py` 为空；
  探针断言 `RagAnswer` 9 字段、`RetrievalResult` 15 字段与改前完全一致；
  无 `qa/`、`conversations/`、`main.py`、`config.py`、路由/OpenAPI 源码改动。
- 无新增真实调用路径/后台任务/DB 文件；无隐含 `start_trace`。

### 提交边界与 PM 授权 — PASS

- `git show --name-only 776497f` 共 15 个文件，全部落在 handoff §2（含可选 `trace_attrs.py`）
  + PM 授权 `test_middleware.py` + 证据 + report 范围内；逐项见 `10-commit-boundary.txt`。
- `backend/tests/observability/test_middleware.py` 的 diff 恰为 L218/L297 两处断言（证据 07），
  numstat `2/2`；`header / trace 行 / mode / scope / content_mode / 无原文` 等断言未动。
- 新断言非空转：真实 QA POST 探针（证据 13）确认 trace 确有 13 个 Span，包含
  `recall/fuse/hard_filter`（两次 legacy 候选检索：一次 record 面含 exact_recall，一次正文面），
  且 T003b 既有字段仍成立：`request_id=None`、`outcome_kind=None`、`status=incomplete`、
  `content_mode=hash`、`question_hash=None`、一次 POST 恰一行 trace、trace DB 无问题原文。
- 说明：这两处断言的旧语义（“未埋业务 Span”）被 PM 明确授权替换；新断言比“空”更强（要求核心 Span 存在），
  但确实不再验证“无业务 Span”，属授权范围内的口径变更，不是私自放宽。

### 证据卫生 — PASS（附 minor）

- 已提交证据：`git ls-tree -r HEAD -- docs/reports/OBS-EVAL/P0/evidence/T003c/` 列出 00–08 共 9 个文件。
- 4 个未跟踪残留：验收开始（2026-11-05 02:46）`git status` 可见
  `02-package.txt / 03-observability-rag.txt / 04-full.txt / 07-test-middleware.diff`（均为 `??`，非 commit 内容）；
  `git ls-tree` 确认 commit 776497f 不含它们。验收期间它们被外部清理（本人未删除；
  本人只清理 `backend/.pytest-tmp` 与 `%TEMP%` 下的副本）。
- minor 1：证据 `05-commit-stat.txt` / `08-commit-boundary.txt` 记录的是 amend 前 C1（`05c64c0`，11 文件），
  与最终 HEAD（`776497f`，15 文件）不一致；report §3 已披露 amend，但“除首行自引用 sha 外与最终 HEAD 一致”
  的说法不准确（05/08 的 stat 也少了 4 个文件、插入数不同）。
- minor 2：`00-baseline.txt` 的时间戳（01:56:51）晚于 `01-tdd-red.txt`（01:56:47），且其中 `git status`
  已出现 `?? backend/tests/observability/test_rag_spans.py`，不是严格“开工前干净快照”；HEAD d41d19f 仍正确。
- minor 3：`test_middleware.py` 模块 docstring/注释（L11、L193、L215）仍写“spans 为空是预期”，
  与新断言相反；仅为注释陈旧，不影响判定（PM 只授权改两处断言）。

## 4. 发现的问题（按严重度）

### 4.1 [HIGH / 待 PM 裁决] §5.4 检索前拒答在 no_answer 下 validate 失败

- 事实：`validate_required_spans` 对 `DOCUMENT_NOT_FOUND` 返回 `['fuse','recall']`（证据 04 5.4b）；
  同一路径覆盖 `UNKNOWN_STORE`、`RECORD_ONLY`。
- 影响：若 T003d 把 `RagAnswer.kind == "no_answer"` 一律映射 `OutcomeKind.NO_ANSWER`（最自然的映射），
  T006 gate 的 `trace_integrity` 会硬失败；且开发测试没有覆盖这个断言（`test_rag_spans.py:441-453` 缺 validate）。
- 性质：T001 冻结契约与业务早退路径的冲突；T003c 按“未执行不伪造”正确实现并已披露。**不建议在 T003c 返工**。
- 需 PM 选择：T003d 按 reason 映射到 required 为 `{parse,commit}` 的 outcome（语义需自洽）；
  或 T001/T005 明确 `rag+no_answer` 只覆盖检索后拒答/新增 outcome；或设计层批准 gate 豁免。

### 4.2 [LOW] 开发测试缺少 rerank 失败分支的 error 覆盖

- 变体 M5：删掉 `retrieval.py:523` 的 `rerank_span.annotate(status="error", ...)`，`test_rag_spans.py` 仍 20 passed；
  说明开发测试没有覆盖该分支。独立探针 5.6d 证明当前代码行为正确（rerank Span error）。
- 建议：T003c 可不返工；若追求测试完备，后续补一条 rerank 注入失败的断言即可。

### 4.3 [LOW] 证据 minor

- 见 §3 证据卫生 minor 1–3。均不影响功能/边界判定，但 PM 整理证据时应知道 05/08 是 C1 快照、00 非干净基线。

### 4.4 [INFO] 已披露的边界与遗留（不判 FAIL）

- `answer` Span 在“检索后拒答”存在：阶段真实执行，required 是子集要求，不违反 validate；若 gate 按“no_answer 必须无 answer”字面解释需另行定义。
- legacy 产品轮次会出现“无 parse/answer 的 RAG 检索 Span”（证据 13：13 Span）；路径/outcome 由 T003d 收口。
- 同一 plan 两次 `RagIndex.search` 的 Trace 属性按最后一次覆盖；本包不聚合；T003d/T006 需注意。
- `filter_decisions_json` 只写过滤键名、不写过滤值（隐私取舍）；如 gate 需要命中数需另加字段。

## 5. 未覆盖项（NOT-RUN / 边界外）

1. **真实 live 模型/OCR/embedding/rerank**：P0 明令禁止，本包与验收均只用 offline/mock；未验证 live 分支。
2. **T006a JSON 门禁/真实 gate**：尚未实现，未跑；本验收只做了等价 canonical JSON 断言与 `validate_required_spans`。
3. **真实知识库 revision 变化**：用 monkeypatch `KnowledgeChanged` 覆盖同路径；未在磁盘索引并发写中制造真实 revision 竞态。
4. **`UNKNOWN_STORE` / `RECORD_ONLY` 路径**：按源码与 DOCUMENT_NOT_FOUND 同构推断，未逐条跑（同一 `_commit` 早退分支）。
5. **真实产品 QA 的 RAG answer 路径**：middleware 探针的固定问题在空库上得到 `not_found`；answer/conflict 等路径在 RAG 内核层直接验证。
6. **P95 写入延迟/性能增量**：handoff §5 未要求，本包报告也留待 T003c/d 全链路；未测。
7. **replay 语义 / content_mode=redacted/full**：T003a 范围，本包不处理；未跑。
8. **Windows 并发**：本验收严格串行，未验证并发工作树下的 SQLite 行为（报告已提示风险）。

## 6. 建议返工范围

- **不建议重写 T003c 代码**：实现与测试质量整体高；唯一 FAIL 是契约冲突，不是埋点缺陷。
- PM 需在 T003d 开工前裁决 §4.1（outcome 映射/表义）；裁决后由 T003d/T005 处理，T003c 无需返工。
- 若 PM 要求测试补强：仅建议给 `test_rag_spans.py` 补 rerank 失败断言（§4.2），以及给 DOCUMENT_NOT_FOUND 用例
  增加“按裁决后的 outcome 调用 validate”的断言；二者都不需要改生产代码。
- 证据 minor 可在 PM 整理时替换 05/08 为最终 HEAD 快照（可选）。

## 7. 复跑证据清单（`docs/reports/OBS-EVAL/P0/evidence/verify/T003c/`）

| 文件 | 内容 |
| --- | --- |
| `00-context-env.txt` | branch/HEAD/parent/base/版本/时间 |
| `01-pytest-rag-spans.txt` | §6 ① 20 passed |
| `02-pytest-rag-observability.txt` | §6 ② 506 passed |
| `03-plain-old-vs-new.txt` + `plain-old.json` + `plain-new.json` | 旧/新代码无 trace 5 场景逐字段对照 |
| `04-independent-probe.txt` + `probe-report.json` | 20 条独立行为断言（19 PASS / 1 FAIL=§5.4b） |
| `05-mutation-probes.txt` | 控制组 + M1–M4 变异（全部 DETECTED） |
| `06-middleware-stability.txt` | middleware 3×全套 + 5×定点 |
| `07-pytest-full.txt` | §6 ③ 1216 passed |
| `08-baseline-collect-1196.txt` | 旧提交 collect 1196 |
| `09-static-hygiene.txt` | import/依赖/类型/测试计数 |
| `10-commit-boundary.txt` | 提交边界、禁止路径、numstat |
| `11-worktree-evidence-audit.txt` | 工作树状态、提交证据、SHA-256、残留说明 |
| `12-secret-free-scan.txt` | 密钥/绝对路径扫描、探针摘要 |
| `13-middleware-probe.txt` + `probe-middleware.json` | 真实 QA POST trace 10 项断言 |
| `probe_plain.py` / `compare_plain.py` / `probe_traced.py` / `probe_middleware.py` / `mutate_verify.py` | 可复跑探针源码 |

## 8. 交接摘要（≤10 行）

1. 目标 `776497f`（parent `d41d19f`，main `8e44158`）；复跑 20 / 506 / **1216 passed**（基线 collect 1196，+20），无 flake。
2. §5.1 PASS：旧/新代码无 trace 5 场景 `RagAnswer.to_dict()` 逐字段一致；无隐式 trace/DB。
3. §5.2/§5.3 PASS：answer 恰 12 Span、recall 父子正确；vector/rerank 条件开/关与 `filter_decisions_json` 一致。
4. §5.4 **FAIL（单子项）**：DOCUMENT_NOT_FOUND/UNKNOWN_STORE/RECORD_ONLY 检索前拒答在 `no_answer` 下
   `validate_required_spans` 缺失 `['fuse','recall']`；开发测试 `test_rag_spans.py:441-453` 未调用 validate；属 T001 契约冲突，T003c 不伪造正确，需 PM 裁决。
5. §5.5/§5.6 PASS：canonical JSON、计数/稳定引用、问题/答案/证据原文与原始 chunk_id 零泄漏（含 DB 落盘）；异常原类型上抛且 Span/trace error。
6. 边界 PASS：15 文件全在允许路径；PM 授权 test_middleware 恰 2 行（2/2）增强；无 qa/conversations/main/config/观测内核/其它测试/pyproject 改动。
7. 测试非空转：4 组仓库外变异全部被测试捕获；附加 M5（rerank 失败不标 error）未被开发测试覆盖（20 passed），独立探针验证真实行为正确。
8. 证据 00–08 已提交；4 个未跟踪残留不在 commit，验收期间被外部清理；05/08 为 amend 前 C1 快照、00 非严格开工前基线（minor）。
9. 未覆盖：live 模型/OCR/embedding/rerank、真实 T006 gate、真实 revision 竞态、P95 延迟（P0/范围外）。
10. 建议：不重写 T003c；PM 裁决 §5.4 的 outcome/表义后再开 T003d；可选补 rerank 失败测试；未 commit/push/改 `_index.md`。

# T003c 报告：RAG 路径 Span 埋点（P0 第 5 包）

> 分支：`p0/obs-eval`（基线 `d41d19f`，T001–T003b 已通过独立验收）；开发方：dev-t003c。
> 本报告是开发方自证，验收请以独立复跑结果为准（不采信本文件任何“已完成”结论）。
> 证据目录：`docs/reports/OBS-EVAL/P0/evidence/T003c/`。
> 范围：只给 RAG 内核加观测，**不改业务逻辑**；`request_id` / `question` / `path` / `outcome` 仍由 T003d 设置。
> PM 裁决（handoff §4，2026-11-05）：授权本包对 `backend/tests/observability/test_middleware.py` 中
> 两条 `spans == []` 的 T003b 边界断言做最小增强，精确 diff 见证据 07。

## 1. 完成内容

新增 / 修改 5 个文件 + 证据 + 本报告（不改 `qa/` / `conversations/` / `main.py` / `config.py` / 观测内核；
不新增依赖；零真实模型 / OCR / embedding / rerank 调用；不读 `.env`；不 push）：

| 文件 | 一句话 |
| --- | --- |
| 新增 `backend/src/mktkb/observability/trace_attrs.py`（84 行） | RAG 埋点共享的 no-op 安全助手：`span()`（无 `current_trace()` 时产出空句柄）、`annotate_trace()`（无 Trace 时 no-op，绝不创建隐式 Trace）、`canonical_json()`、`hash_ref()`；顶层只 import 标准库 + `.tracer`，不依赖业务模块 |
| 修改 `backend/src/mktkb/rag/retrieval.py`（+117/−42） | `search` 内 `recall` 父 Span + `exact_recall` / `lexical_recall` / `vector_recall` / `embedding_query` 子 Span；`_fuse` 内 `hard_filter` / `rerank` Span；Trace 级 `retrieval_counts_json` / `filter_decisions_json`（含条件属性）/ `index_revision` / `degraded_json` |
| 修改 `backend/src/mktkb/rag/answer.py`（+110/−31） | `parse` / `answer` / `fact_validate` / `commit` Span；`fact_gate_json`、`citation_refs_json`、`pagination_json`；6 处 FactValidator 调用统一走 `_fact_gate`；6 处 `save_state` 统一走 `_commit`（异常语义不变） |
| 新增 `backend/tests/observability/test_rag_spans.py`（719 行，20 个测试） | 锁定 handoff §5 八条：无 trace 行为一致 / answer Span 集合与父子结构 / 条件 Span 开与关 / 早退不伪造 / attributes canonical 与隐私 / 异常 status=error 且照旧上抛 / 结构不变 / trace_attrs 纯函数 |
| 修改 `backend/tests/observability/test_middleware.py`（2 行断言，PM 授权） | T003b 的 `spans == []`（L218、L297）改为“埋点后事实”断言；其余断言与文件范围未动，精确 diff 见证据 07 |
| 证据 `docs/reports/OBS-EVAL/P0/evidence/T003c/00–08` | 基线、TDD RED、本包 / rag+observability / 全量 pytest 原文、提交 stat、边界、交付物 SHA-256、PM 授权 diff |

一句话：RAG 内核按**实际执行**打 Span——`parse`（answer.py:37）、`recall` 及子通道（retrieval.py:46,48,54,61,298）、
`hard_filter`/`fuse`/`rerank`（retrieval.py:464,80,486）、`answer`（answer.py:159）、`fact_validate`（answer.py:189）、
`commit`（answer.py:210）；只写计数、稳定引用、布尔与状态，任何 `current_trace()` 为 None 的路径都是 no-op。

## 2. 验收标准自证（§5 逐条）

1. **无 trace 时零行为变化** — `trace_attrs.py:43-55`（无 Trace 直接 yield 空句柄）、`:57-61`（annotate_trace no-op）；
   所有业务点只经 `trace_attrs.span` / `annotate_trace`，没有隐式 `start_trace`。
   测试：`test_rag_spans.py:269`（同一固定问题在无 trace / 有 trace 两次运行，去除耗时后 `RagAnswer.to_dict()` 逐字段一致）、
   `:288`（无 trace 时 `current_trace() is None`、无任何 trace 库/旁路文件，且 `RagIndex.ask` 正常返回）；
   `backend/tests/rag` 全绿（证据 03、04）。

2. **answer 路径 Span 完整** — `answer.py:37`（parse）、`retrieval.py:46`（recall 父）、`:48/:54/:61`（exact/lexical/vector）、
   `:298`（embedding_query，嵌在 vector_recall 下）、`:464`（hard_filter）、`:80`（fuse）、`:486`（rerank）、
   `answer.py:159`（answer）、`:189`（fact_validate，嵌在 answer 下）、`:210`（commit）。
   测试：`test_rag_spans.py:307`（answer 路径 Span 集合恰为 12 个；`required_spans(RAG, ANSWER) ⊆ names`；
   `validate_required_spans == []`；recall 子 Span 的 `parent_span_id` 精确；fuse 下挂 hard_filter/rerank；
   parse 首、commit 尾；全部 status=ok、duration≥0、attributes 为 canonical JSON）。

3. **条件 Span 正确** — `retrieval.py:44`（关闭查询向量面时 `vector_enabled=False`）、`:60-67`（仅启用时创建 vector_recall）、
   `:83`（`rerank_enabled = "rerank" in diagnostics`，即仅当 `_fuse` 真实执行重排）、`:141-153`（条件属性经
   `annotate` 并入 `filter_decisions_json`，T003a 约定位置）。
   测试：`test_rag_spans.py:364`（`conditional_required_spans(filter_decisions_json) == {vector_recall, rerank}` 且两者都在）、
   `:386`（`disable_query_embedding=True`：embedding 调用零次、无 vector_recall/embedding_query、`vector_enabled=False`、
   `conditional_required_spans == {rerank}`、validate 通过）、`:411`（空索引融合为空：无 `rerank` Span、`rerank_enabled=False`）。

4. **早退路径不伪造** — clarification 早退在 parse 后直接 commit（`answer.py:37,210`），不进入检索；
   DOCUMENT_NOT_FOUND / UNKNOWN_STORE / RECORD_ONLY 同样早退（`answer.py:73-131`），只有 parse+commit。
   测试：`test_rag_spans.py:428`（clarification Span 集合严格 `{"parse","commit"}`、无 answer/recall/fuse）、
   `:441`（DOCUMENT_NOT_FOUND 只有 parse+commit，不为凑 `rag+no_answer` 表伪造 recall/fuse/answer）、
   `:456`（检索后 NO_EVIDENCE：`required_spans(RAG, NO_ANSWER)` 全在、无 exact_recall、无 fact_validate、validate 通过）、
   `:470`（conflict 含 answer+fact_validate、validate 通过）、`:485`（KnowledgeChanged 只有 parse+commit、validate 通过）。
   `answer` Span 语义：**答案生成阶段真实执行**才创建；检索前早退不创建；检索后判定拒答时该阶段确实执行，故存在（见 §4.3）。

5. **attributes 合规** — `retrieval.py:141-153`（`index_revision`/`retrieval_counts_json`/`filter_decisions_json`/`degraded_json`）、
   `answer.py:145`（`pagination_json`）、`:171`（`citation_refs_json`，`doc_id + unit_id_hash`，不落 chunk_id 原文）、
   `:193/:203`（`fact_gate_json`）。`*_json` 由内核统一 canonical 序列化（`ensure_ascii=False, sort_keys=True`）。
   测试：`test_rag_spans.py:509`（逐个字段 `json.loads` 后用 canonical 口径回写断言等值；计数为 int、条件为 bool；
   含问题/答案/证据原文与原始 chunk_id 的子串在整个 record + 所有 span attributes 中均不出现）、
   `:562`（citation refs 用 `D01 + 16 位 unit hash`，commit attrs 只含 `turn`/`last_kind`）。

6. **异常路径** — `_fuse` 的 rerank 失败仍按既有语义回退 RRF，仅把 Span 标 `status=error`（`retrieval.py:519-524`）；
   真正向上抛的异常由 T003a 内核自动标 Span `status=error` 并照旧 re-raise（本包不改异常类型/时机）。
   测试：`test_rag_spans.py:576`（monkeypatch `_fuse` 抛 `RuntimeError`：`pytest.raises` 原类型/原文、`fuse` span
   `status=error/error_code=RuntimeError`、trace `status=error/error_code=RuntimeError` 且仍写入仓储）、
   `:601`（embedding 失败：不改变“降级继续作答”的既有语义，`embedding_query` status=error、`degraded_json=["vector"]`、
   vector 计数 0、validate 通过）、`:624`（FactRejected：仍然返回 no_answer 拒答、`fact_validate` status=error、
   `fact_gate_json.passed=false`、validate 通过）。

7. **既有测试与全量** — 证据 02：本包 20 passed；证据 03：`backend/tests/rag + backend/tests/observability`
   **506 passed**；证据 04：`backend/tests` 全量 **1216 passed**（T003b 基线 1196 + 本包新增 20，0 failed / 0 error）。

8. **硬约束** — 无新增依赖（`trace_attrs.py` 只用标准库 + `.tracer`）；`RagAnswer` / `RetrievalResult` 的 dataclass
   字段集由 `test_rag_spans.py:655` 锁定未变；API 请求/响应结构未改（全量 integration/acceptance 在 04 内全绿）；
   提交边界见证据 08（C1 内容：本包代码/测试 + PM 授权 2 行断言 + 证据 00–04/07；amend 后另含本报告与
   证据 05/06/08，仍全部落在 §2 允许路径），不含观测内核、既有其他测试、docs/evidence、var、fixtures。

## 3. 实际运行结果

环境：Windows / PowerShell 5.1、Python 3.12.7（`.venv`）、pytest 9.1.1；每条命令前设
`$env:MKTKB_PROJECT_TOTAL_LIMIT_CNY = "20.0"`，解释器 `.\.venv\Scripts\python.exe -B`。
证据用 `cmd /c` + `PYTHONIOENCODING=utf-8` 原始重定向（UTF-8 无 BOM），末尾追加 `exit_code=`。

```powershell
# 开工基线（证据 00）
git branch --show-current   # → p0/obs-eval
git rev-parse --short HEAD  # → d41d19f

# TDD RED（证据 01，实现前）
.\.venv\Scripts\python.exe -B -m pytest backend/tests/observability/test_rag_spans.py -q -p no:cacheprovider --basetemp backend\.pytest-tmp\rag-spans-red
# → ImportError: cannot import name 'trace_attrs'（1 error, exit 2）

# 本包测试（证据 02）
.\.venv\Scripts\python.exe -B -m pytest backend/tests/observability/test_rag_spans.py -q -p no:cacheprovider --basetemp backend\.pytest-tmp\rag-spans
# → 20 passed, 1 warning（exit 0）

# handoff §6 范围套件（证据 03）
.\.venv\Scripts\python.exe -B -m pytest backend/tests/rag backend/tests/observability -q -p no:cacheprovider --basetemp backend\.pytest-tmp\rag-obs
# → 506 passed, 1 warning in 50.02s（exit 0）

# 全量回归（证据 04）
.\.venv\Scripts\python.exe -B -m pytest backend/tests -q -p no:cacheprovider --basetemp backend\.pytest-tmp\t003c-full
# → 1216 passed, 1 warning in 553.61s (0:09:13)（exit 0；基线 1196 + 本包 20）

# 提交（证据 05，C1）
git commit -m "p0/T003c rag spans"
# → [p0/obs-eval 05c64c0] p0/T003c rag spans；11 files changed, 1176 insertions(+), 75 deletions(-)
git show --stat --oneline HEAD   # 原文见证据 05
```

**PM 授权的测试断言修改（证据 07，2 行）**：`test_middleware.py:218` 与 `:297` 的
`assert spans == []` → `assert spans and {"recall", "fuse", "hard_filter"} <= {span.name for span in spans}`；
`git diff --numstat` = `2 2`，无其它改动。其余既有断言（header / trace 行 / mode / scope / content_mode /
无原文）强度不变。

**交付物 SHA-256（证据 06，C1 提交前采集）**：

```text
b9a40a3cbe35c2f9c0cd34b75609983e993e3af44934c318d4fc76eb61ebfcdf  backend\src\mktkb\observability\trace_attrs.py
371f304ffe5a1813ef17ccec5068c011df3f0fc03803b2e9f8eeaa215daf9ca2  backend\src\mktkb\rag\retrieval.py
5d63322979f3e989a92aa2ea80c40d95cd2b0e4fa9d87e14e2a62cbfdfbc0c17  backend\src\mktkb\rag\answer.py
cc76694c9919c56bc0ed622361fb7e991dbebb6404535c9e2a14a50908e47f1d  backend\tests\observability\test_rag_spans.py
68cb2d3394f463248b8287af91239251d2dc6cae7a20b01d2a413e9c3d5e3af6  backend\tests\observability\test_middleware.py
```

**提交与 amend 说明**：代码 / 测试 / 证据 00–04、07 先提交为 C1 = `05c64c0`（11 文件、1176 插入、75 删除）；
证据 05/06/08 与本报告在 C1 之后采集，再 `git commit --amend --no-edit` 并入同一提交（单 commit 约束；
提交内无法记录自身最终 sha，最终 HEAD 短 sha 见回复末尾/`git log -1 --format=%h`，证据 05 记录的是 amend
前一次 stat，除首行自引用 sha 外与最终 HEAD 一致）。

## 4. 偏离与未做

1. **`rag/index.py` 未改**：`RagIndex.ask/search` 是纯委托（`index.py:728-749`），Span 必须打在其真实执行点
   （`answer.py` 与 `retrieval.py`）。为遵守“不改业务逻辑/不加空转代码”，本包未在该文件加入任何 no-op 埋点；
   `RagIndex.search` 直接调用同样会经 `retrieval.search` 产出 recall/fuse 等 Span 与 Trace 属性。
   验收边界（证据 08）只会看到 `rag/index.py` 不在提交内，不存在越界。
2. **PM 授权的既有测试修改**：见 §3 与证据 07；这是对 T003b “未埋点边界断言”的替换，不是放宽。
3. **`answer` Span 的出现条件**：定义为“答案生成阶段真实执行”。检索后拒答（NO_EVIDENCE / FIELD_NOT_RECORDED 等）
   会创建（阶段确实执行）；检索前早退（clarification / DOCUMENT_NOT_FOUND / UNKNOWN_STORE / RECORD_ONLY / 检索异常）
   不创建。设计 §6.4 对 `rag+no_answer` 只要求 `parse/recall/fuse/commit`，`answer` 是超集，不违反
   `validate_required_spans`；测试用早退用例锁定“不伪造”。
4. **Trace 属性写入位置**：`index_revision` / `retrieval_counts_json` / `filter_decisions_json` / `degraded_json`
   在 `retrieval.search` 末尾写，故直接 `RagIndex.search` 也有；legacy 产品路径对同一 plan 可能调用两次
   `RagIndex.search`（记录面 + 正文面），属性按最后一次覆盖，本包不聚合（T003d/T006 如需应以 gate 口径定义）。
5. **`filter_decisions_json` 的隐私取舍**：只写 `mode` / `enumerate` / `applied_filters`（**键名**，不写门店/物品等
   过滤值，避免把问题派生内容落库）+ 两个条件 flag；如后续 gate 需要过滤命中数，可在 T006 前另加计数字段。
6. **`trace_attrs.canonical_json` 仅测试使用**：生产路径的 JSON 统一由 tracer 序列化（单一事实源），本包不重复实现。
7. **未做（按范围）**：未接 `request_id/question/path/outcome`（T003d）、未改 QA/legacy Span、未实现 replay 分支、
   未实现 Trace 导出/purge、未实测 P95 写入延迟增量（留 T003c/d 全链路后统一评估）、未 push。
8. **工作树中非本包改动**：开工时已存在的 PM `_index.md` 修改与 T001–T003d handoff/prompts 等未跟踪文件未修改 /
   未清理 / 未 commit；PM 在 evidence 目录额外生成的 `02-package.txt` / `03-observability-rag.txt` /
   `04-full.txt` / `07-test-middleware.diff` 未纳入本包 commit（其中 `04-full.txt` 是中途终止的运行，不宜入库）。
9. **`test_middleware.py` 曾出现的偶发失败（13 个 Span 出现时 `spans == []` 失败）**：定位为产品 legacy 路径
   `candidate_unit_ids_for_intent` 的真实检索 Span；该断言已被 PM 授权替换为“埋点后事实”，不再依赖“空 Span”。

## 5. 风险与遗留

- **T003d 必须补齐启动字段**：未调用 `set_request_id` / `set_question` / `set_path` / `set_outcome` 时，trace 仍
  `status=incomplete`；本包不写这些字段（handoff §7）。
- **`rag+no_answer` 设计表与检索前拒答的缺口**：DOCUMENT_NOT_FOUND / UNKNOWN_STORE / RECORD_ONLY 只有
  `parse+commit`；若 T003d 把 `RagAnswer.kind == no_answer` 一律映射 `OutcomeKind.NO_ANSWER`，gate 会报缺
  `recall/fuse`。按“未执行不伪造”原则，本包不补 Span；建议 T003d 按 `reason` 区分（或 T005 明确该表只覆盖检索后拒答）。
  T003d 的 `test_middleware` 同用例还会更新 `request_id/outcome` 断言（PM handoff §4 已预告同口径授权）。
- **legacy 路径会出现“无 parse/answer 的 RAG 检索 Span”**：产品 legacy 轮次 `candidate_unit_ids_for_intent` 会真实调用
  `RagIndex.search`（记录面 + 正文面各一次），因此 trace 里会出现 recall/fuse/hard_filter 等检索 Span。若 gate 按
  `path=legacy` 校验，需要 T003d 在 legacy 分支补 legacy Span 并确保 outcome 映射，不要把 RAG 检索 Span 误当 RAG path。
- **`answer` Span 与“no_answer 不得有 answer”的解读风险**：本包按“阶段实际执行”保留；若验收按字面要求所有
  no_answer 都无 `answer`，需要把该 Span 下移到“确定作答”分支（会显著增加侵入性），建议 gate 只校验 required 子集。
- **Span 体积**：attributes 均为计数/短串/短哈希，单 Span 百字节级；P95 写入增量待 T003d 全链路实测。
- **重排失败**：既有“回退 RRF 不抛”语义保留，`rerank` Span status=error 但 trace status 仍 ok；如 gate 需要
  “观察到重排降级”应读 `degraded_json`/span attrs，而不是 trace status。
- **Windows 并发**：同一工作树并行跑 pytest 会共享 `--basetemp` 与 SQLite 文件句柄，可能产生假失败/文件锁错误；
  本报告的全部结论来自串行、独占工作树的复跑（证据 03/04）。

---

## 交接摘要（≤10 行）

1. 交付物：新增 `observability/trace_attrs.py`（84 行）；`rag/retrieval.py`（recall 父+子、hard_filter/fuse/rerank、Trace 属性）；`rag/answer.py`（parse/answer/fact_validate/commit、3 个 `*_json`）；新增 `tests/observability/test_rag_spans.py`（719 行/20 tests）；PM 授权改 `test_middleware.py` 2 行断言（证据 07）；证据 00–08 + 本报告。未改 `rag/index.py`（纯委托，Span 在真实执行点）。
2. §5.1 无 trace 零变化：`trace_attrs.py:43,57`；`test_rag_spans.py:269,288`（有/无 trace 的 `RagAnswer.to_dict()` 去耗时后逐字段一致；无隐式 trace/DB）。
3. §5.2 answer 路径：`answer.py:37,159,189,210`、`retrieval.py:46,48,54,61,298,464,80,486`；`test_rag_spans.py:307`（12 Span 精确集合、recall 父子、fuse 子挂、validate==[]）。
4. §5.3 条件 Span：`retrieval.py:44,60,83,141-153`；`test_rag_spans.py:364,386,411`（vector/rerank 开与关、canonical 位置、conditional/validate 一致）。
5. §5.4 早退：`test_rag_spans.py:428,441,456,470,485`（clarification/DOCUMENT_NOT_FOUND 无伪造；检索后 no_answer/conflict/knowledge_changed 均 validate 通过）。
6. §5.5 attributes：`retrieval.py:141-153`、`answer.py:145,171,193,203`；`test_rag_spans.py:509,562`（canonical、计数/布尔/稳定引用、问题/答案/chunk_id 原文零泄漏）。
7. §5.6 异常：`retrieval.py:519-524`、tracer 既有异常标记；`test_rag_spans.py:576,601,624`（RuntimeError 原样上抛 + span/trace error；embedding 降级；FactRejected 拒答）。
8. 实际运行：证据 02 = 20 passed；03 = 506 passed；04 = **1216 passed**（基线 1196 + 20，0 failed/0 error）；C1 = `05c64c0`（11 文件、1176 插入、75 删除），证据 05 为 amend 前 stat，最终 HEAD 见 `git log -1 --format=%h`；SHA-256 见证据 06。
9. 偏离：`rag/index.py` 未改（纯委托）；`answer` Span 在“检索后拒答”也存在（生成阶段真实执行，超集不违反完整性）；legacy 候选检索会留下 RAG 检索 Span；`filter_decisions_json` 只写过滤键不写值。
10. 风险：T003d 必须补 request_id/question/path/outcome；`rag+no_answer` 表对检索前拒答（DOCUMENT_NOT_FOUND/UNKNOWN_STORE/RECORD_ONLY）无法在不伪造 Span 的前提下满足，需按 reason 区分或由 T005 收紧表义；未 push、未新增依赖、未碰观测内核/var/docs/evidence/fixtures。

# T003c · RAG 路径 Span 埋点（P0 第 5 包，最高风险包之一）

> PM 任务单。基线：`p0/obs-eval` @ `d41d19f`（T001–T003b 已通过独立验收）。本包只给 RAG 内核加观测，**不改任何业务逻辑**；path/outcome/question 由 T003d 设置。
> 完成后由全新上下文的独立验收助手按本文件逐条证伪；验收重点：无 trace 时行为与改动前完全一致。

## 1. 目标（一句话）

在 RAG 内核（`rag/index.py`、`rag/retrieval.py`、`rag/answer.py`）按实际执行打 Span 与 attributes：`parse` / `recall`（含子 Span）/ `hard_filter` / `fuse` / `rerank` / `answer` / `fact_validate` / `commit`，只记录计数、稳定引用、耗时与状态，不记录问题/答案/上下文原文。

## 2. 交付物（只准写这些路径）

- 修改 `backend/src/mktkb/rag/index.py`、`backend/src/mktkb/rag/retrieval.py`、`backend/src/mktkb/rag/answer.py`
- 新增 `backend/tests/observability/test_rag_spans.py`
- 允许对 `backend/tests/observability/conftest.py` **追加** fixture（不改既有 fixture）
- 可选：若确需共享 JSON/计数辅助，允许新增 `backend/src/mktkb/observability/trace_attrs.py`（纯函数、不依赖业务模块），并在本包测试中覆盖
- 证据（入库）：`docs/reports/OBS-EVAL/P0/evidence/T003c/`
- 报告：`.claude/handoffs/T003c-rag-spans/report.md`（五段）

## 3. 输入（只看这些）

1. P0 设计 §6.3（Trace 字段）、§6.4（Span 名称与路径感知完整性）、§6.5（内容隐私）、§6.6（写入语义）。
2. P0 计划 Task 3 Step 4 的埋点清单（`rag/index.py::ask/search`、`rag/retrieval.py::search`、`rag/answer.py::answer_question`）。
3. 已验收代码（只读，必须按其约定写）：
   - `observability/tracer.py`：`start_trace/current_trace/span/annotate/set_*`，**条件属性写入位置**（T003a 实现把条件属性并入 `filter_decisions_json`）、`annotate` 可覆盖启动字段的边界（本包只写数据字段，不写 mode/scope/replayed/path/outcome_kind）；
   - `observability/contracts.py`：`required_spans` / `conditional_required_spans` / `validate_required_spans`；
   - `observability/store.py`（只读）。
4. 关键代码位置：`rag/index.py:728 search`、`:733 ask`；`rag/retrieval.py:30 search`（`_exact_recall` L177、`_lexical_recall` L212、`_vector_recall` L239、`_fuse` L384、`_passes_filters` L350、rerank 调用在 `_fuse` L418 附近）；`rag/answer.py:24 answer_question`（parse_query L35、FactValidator 校验调用 L220/240/365/481/542/614、save_state 早退点）。

## 4. 允许 / 禁止

**PM 裁决（2026-11-05，针对开发方报告的执行冲突）**：T003b 的 `test_middleware.py` 中两条用例把 `spans == []` 当作"T003b 未埋点"的边界断言，T003c 埋点后必然失效。**授权在本包 commit 中做"最小、可审计、只增强不削弱"的修改**：
- 只改 `backend/tests/observability/test_middleware.py` 中命中 `spans == []` 的两条断言（L218/L297 所在用例），把"空 Span"改为"埋点后事实"断言（建议：`spans` 非空且包含 `required_spans(path, outcome)` 的核心集合），**不得删除/放宽其它任何断言**（header、trace 行、mode/scope/content_mode、无原文等保持原强度）；
- 报告与证据必须给出该文件的精确 diff（只允许这两处断言变化），验收方据此核对是否最小；
- T003d 会再次更新同一用例的 `request_id`/`outcome` 断言，属同口径授权。

**允许**：§2 交付物；上述 PM 授权的最小测试断言修改；`git switch p0/obs-eval`；本包一个 commit。

**禁止**：
- 不改 `qa/` / `conversations/` / `main.py` / `config.py` / `observability/{tracer,store,contracts,versioning}.py`；不改既有测试。
- **不改业务行为**：不重构检索/排序/答案逻辑，不改变 `RagAnswer`/`RetrievalResult` 数据结构，不改变异常类型与时机；埋点全部以 `current_trace()` 为 None 时 no-op 为前提。
- 不记录问题/答案/上下文原文；不记录 config 密钥；不新增依赖；零真实模型/OCR/embedding/rerank 调用；不读 `.env`。
- 不碰 `docs/evidence/**`、`var/**`、`fixtures/**`、账本/GO、归档区；不 push；不 commit PM 的未跟踪文件。

## 5. 验收标准（逐条可判定）

1. **无 trace 时零行为变化**：未开启 trace 时，RAG 既有测试全绿；固定问题的 `RagIndex.ask` 返回（kind/text/citations/facts/pagination 等既有字段）与改动前一致（可用改动前后同测试基线对比，或在测试中断言固定期望）。
2. **answer 路径 Span 完整**：测试中显式 `start_trace(path=RAG, ...)` 调 `RagIndex.ask`，Span 集合 ⊇ `required_spans(RAG, ANSWER)` = {parse, recall, fuse, answer, commit}；`recall` 为父 Span，实际执行的 `exact_recall`/`lexical_recall`/`embedding_query`/`vector_recall` 挂其下；未执行通道**不产生** Span。
3. **条件 Span 正确**：`vector_enabled=true` → 有 `vector_recall`；`rerank_enabled=true` → 有 `rerank`；未启用/未执行时两者都不出现；条件属性写入 tracer 约定的 canonical 位置，`conditional_required_spans` 判定与之一致。
4. **早退路径不伪造**：clarification / no_answer / conflict / knowledge_changed 等路径的 Span 集合与该 `path+outcome` 的 required 集合一致（用 `validate_required_spans` 断言通过），不得为了凑齐而伪造 `answer` Span。
5. **attributes 合规**：写 `retrieval_counts_json`、`filter_decisions_json`、`fact_gate_json`、`citation_refs_json`、`pagination_json`（按设计字段名）与 `index_revision`、`degraded` 等；全部为 canonical JSON（`ensure_ascii=False, sort_keys=True`）且可解析；值为计数/布尔/稳定引用（`doc_code:unit_key` 或 unit_id_hash），**不含问题或答案原文**。
6. **异常路径**：检索/答案内部抛异常时对应 Span `status=error`，异常照旧向上抛（类型/时机不变），trace 不丢。
7. **既有测试与全量**：`backend/tests/rag`、`backend/tests/observability`、`backend/tests/integration/test_chat.py`、`backend/tests/acceptance` 相关全绿；`backend/tests` 全量相对 T003b 基线 **1196 passed** 无新增失败。
8. **硬约束**：无新增依赖；API 请求/响应 Body 字段结构未变；不碰 qa/conversations/观测内核/既有测试。

## 6. 必须实际运行的检查（输出原文存证据目录）

```powershell
$env:MKTKB_PROJECT_TOTAL_LIMIT_CNY = "20.0"
git rev-parse --short HEAD   # 应为 d41d19f
```

```powershell
.\.venv\Scripts\python.exe -B -m pytest backend/tests/observability/test_rag_spans.py -q -p no:cacheprovider --basetemp backend\.pytest-tmp\rag-spans
.\.venv\Scripts\python.exe -B -m pytest backend/tests/rag backend/tests/observability -q -p no:cacheprovider --basetemp backend\.pytest-tmp\rag-obs
.\.venv\Scripts\python.exe -B -m pytest backend/tests -q -p no:cacheprovider --basetemp backend\.pytest-tmp\t003c-full
git show --stat --oneline HEAD
```

## 7. 已知约束与约定（T003a 验收发现，本包必须遵守）

- 只通过 `current_trace()` 取 trace；`current_trace()` 为 None 时所有埋点 no-op（禁止创建隐式 trace）。
- `SpanHandle.annotate` 只写数据字段；**不要** annotate `mode/scope/replayed/path/outcome_kind`（会被覆盖，破坏 trace 权威性）。
- 所有 `*_json` 字段必须是 canonical JSON；T006a 门禁会加 JSON 合法性校验，非法 JSON 会被判失败。
- `replayed=True` 时 status 优先级为 `replayed`；本包不处理重放。
- 不改 `RagAnswer` 结构；不要为了带 trace_id 而改返回对象（trace_id 由中间件响应头/仓储关联，T003d 的 EvalOutcome 层负责）。

## 8. 提交

分支 `p0/obs-eval`，一个 commit：`p0/T003c rag spans`；只 add 本包交付物；不 push（若 amend，最终 HEAD 的 `git show --stat` 必须重新采集）。

## 9. report.md 格式

五段：完成内容 / §5 逐条自证（命令或 文件:行）/ 实际运行结果（含 commit sha、stat、全量通过数）/ 偏离与未做 / 风险与遗留。末尾另给 ≤10 行交接摘要。

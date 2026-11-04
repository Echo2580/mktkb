# MKTKB RAG Evaluation & Observability P0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. 本项目建议当前聊天单线执行；本稿不代表已选择多代理执行或已启动开发。

**Goal:** 在不改变现有问答业务行为的前提下，落地 Trace 内核、B0 + Bad Case 确定性评测、双层发布门禁和 Baseline/Diff 报告。

**Architecture:** 请求级 `TraceContext` 通过 contextvar 串联 `QaEngine` / `RagIndex` / legacy 路径，best-effort 写入独立 SQLite；评测器在 Replay 与 Local 两种模式下生成 `CaseResult`，由 gate 按硬门禁与分层质量阈值裁决，再由 baseline/diff 输出 JSON、Markdown 与非门禁静态 HTML。

**Tech Stack:** Python 3.12、FastAPI、SQLAlchemy、SQLite（Trace 使用 stdlib `sqlite3`）、pytest；P0 不新增生产依赖。

**Spec:** `docs/superpowers/specs/2026-11-04-mktkb-observability-evaluation-design.md`

## Global Constraints

- Python 3.12.7，项目 `.venv`；命令统一使用 `.\.venv\Scripts\python.exe -B`。
- P0 不新增生产依赖；不安装 Ragas、Langfuse、Prometheus、OpenTelemetry。
- 不修改现有 API 的请求参数与响应 Body；只允许新增 `X-Trace-ID` 响应头。
- `request_id` 与 `trace_id` 是 1:N；每次执行尝试一条 Trace，重试/重放/恢复不覆盖历史。
- 不修改 `mktkb.sqlite3` schema，也不修改 `rag-index.sqlite3` schema。
- 允许新增独立 `var/observability/qa-traces.sqlite3`。
- P0 禁止真实模型 / OCR / embedding / rerank 调用；禁止读取 `.env`；禁止外网。
- Trace 生产默认关闭；本地 P0 默认开启；写入 best-effort，失败不影响问答。
- `content_mode` 默认 `hash`；真实业务只允许 `hash|redacted`；`full` 仅合成语料。
- 真实业务问题哈希使用 HMAC-SHA256；密钥只来自 `MKTKB_TRACE_HMAC_KEY`，不入库、不入报告。
- 必需 Span 按 `path + outcome + 条件属性` 检查；未执行的可选阶段不得伪造。
- Baseline 同 `pipeline_version` 才能放行；跨版本只能 `--compare-with` 做分析。
- P0 只跑 B0 40 + Bad Case 13；Holdout 30 在 P1 引入。
- 仓库已启用 Git（GitHub `Echo2580/mktkb`，v0.1 冻结锚点 commit `366046d` / tag `v0.1-local-20261104`）：每个任务结束以 **git commit** 为版本锚；`docs/reports/OBS-EVAL/P0/anchors.json` 只记录 P0 运行产物（trace/dataset/gate 文件）的 SHA-256，不再手工替代版本控制。
- 所有新增文档、JSON、JSONL、SQL 使用 UTF-8；路径使用 `pathlib`，兼容中文路径。

## Review Focus

1. 澄清/无意图/早退请求没有 `answer` Span 时，`trace_integrity` 不能误判；由 Task 3 与 Task 5 的测试覆盖。
2. Legacy 路径只在检索为空时触发 `query_expansion`；未触发时不得要求该 Span；由 Task 3 与 Task 5 覆盖。
3. Trace 写入失败必须不影响产品响应，但门禁必须单独以 `trace_integrity` 失败；由 Task 2、Task 3、Task 5 覆盖。
4. Gold 解析到 0 个或多个 unit 时必须 fail closed，不能随意挑 chunk；由 Task 4 覆盖。
5. 全部拒答的 run 不能让 `refusal_recall` 单独通过，必须同时看 `false_refusal_rate`；由 Task 5 覆盖。

## 文件结构

```text
backend/src/mktkb/observability/
  __init__.py
  contracts.py
  versioning.py
  store.py
  tracer.py

backend/src/mktkb/evaluation/
  __init__.py
  dataset.py
  gold.py
  scorers.py
  runner.py
  gate.py
  baseline.py
  report.py
  cli.py

tools/
  rag_eval.py
  build_eval_dataset.py

fixtures/evaluation/
  b0.jsonl
  badcase.jsonl

docs/evaluation/
  trace_schema_v0_1.md
  eval_data_v0_1.md
  gate_v0_1.json

backend/tests/observability/
  test_contracts.py
  test_versioning.py
  test_store.py
  test_tracer.py
  test_middleware.py

backend/tests/evaluation/
  test_dataset.py
  test_gold.py
  test_scorers.py
  test_runner.py
  test_gate.py
  test_baseline.py
  test_report.py
  test_p0_acceptance.py
```

---

## Task 1: 数据契约与版本绑定

**Files:**
- Create: `backend/src/mktkb/observability/__init__.py`
- Create: `backend/src/mktkb/observability/contracts.py`
- Create: `backend/src/mktkb/observability/versioning.py`
- Create: `docs/evaluation/trace_schema_v0_1.md`
- Create: `docs/evaluation/eval_data_v0_1.md`
- Test: `backend/tests/observability/test_contracts.py`
- Test: `backend/tests/observability/test_versioning.py`

**Interfaces:**
- Produces: `TRACE_SCHEMA_VERSION = "mktkb.trace.v0.1"`、`CASE_SCHEMA_VERSION = "mktkb.eval.case.v0.1"`、`GATE_SCHEMA_VERSION = "mktkb.gate.v0.1"`。
- Produces: `TraceMode`（`replay|local|live`）、`TracePath`（`rag|legacy|legacy_with_rag_candidates`）、`OutcomeKind`（`answer|clarification|no_answer|ambiguous|conflict|error|not_found|service_error|knowledge_changed`）。
- Produces: `required_spans(path: TracePath, outcome: OutcomeKind) -> frozenset[str]`。
- Produces: `conditional_required_spans(attrs: Mapping[str, Any]) -> frozenset[str]`。
- Produces: `pipeline_version(components: Mapping[str, Any] | None = None) -> str`。
- Produces: `config_hash(config: Mapping[str, Any]) -> str`。
- Produces: `hash_question(question: str, *, key: bytes, algo: Literal["hmac-sha256","sha256"]) -> str`、`key_fingerprint(key: bytes) -> str`。
- Produces: `TraceRecord`、`SpanRecord` 冻结 dataclass；字段按设计文档 §6.3。

- [ ] **Step 1: 写失败测试**

```python
def test_rag_clarification_does_not_require_answer_span():
    assert required_spans(TracePath.RAG, OutcomeKind.CLARIFICATION) == frozenset({"parse", "commit"})

def test_legacy_not_found_does_not_require_expansion_or_answer():
    assert required_spans(TracePath.LEGACY, OutcomeKind.NOT_FOUND) == frozenset(
        {"intent_parse", "retrieve", "commit"}
    )

def test_conditional_spans_follow_execution_flags():
    assert conditional_required_spans({"vector_enabled": True}) == frozenset({"vector_recall"})
    assert conditional_required_spans({"rerank_enabled": True}) == frozenset({"rerank"})
    assert conditional_required_spans({"expansion_triggered": True}) == frozenset({"query_expansion"})
    assert conditional_required_spans({}) == frozenset()
```

```python
def test_pipeline_version_changes_with_prompt_or_config():
    base = {
        "embedding_model": "text-embedding-v4",
        "embedding_dimensions": 1024,
        "top_k": 8,
        "prompt": "A",
    }
    assert pipeline_version(base) == pipeline_version(dict(base))
    assert pipeline_version(base) != pipeline_version({**base, "prompt": "B"})
    assert pipeline_version(base) != pipeline_version({**base, "top_k": 12})

def test_hmac_hash_requires_key():
    with pytest.raises(ValueError):
        hash_question("城东店", key=b"", algo="hmac-sha256")

def test_hash_question_does_not_return_raw_text():
    digest = hash_question("城东店", key=b"k" * 32, algo="hmac-sha256")
    assert "城东店" not in digest
    assert len(digest) == 64

def test_config_hash_rejects_secret_keys():
    with pytest.raises(ValueError):
        config_hash({"api_key": "secret"})
```

- [ ] **Step 2: 运行确认失败**

```powershell
.\.venv\Scripts\python.exe -B -m pytest backend/tests/observability/test_contracts.py backend/tests/observability/test_versioning.py -q -p no:cacheprovider --basetemp backend\.pytest-tmp\obs-contracts
```

预期：`ImportError` 或 `AttributeError`。

- [ ] **Step 3: 实现 `contracts.py` 与 `versioning.py`**

`required_spans` 按设计文档 §6.4 的表实现；`conditional_required_spans` 只认 `vector_enabled`、`rerank_enabled`、`expansion_triggered`、`index_sync_performed` 四个键。`pipeline_version` 用规范化 JSON 的 SHA-256，默认组件从 `qa.service.QA_ENGINE_VERSION`、`rag.index.SCHEMA_VERSION`、`rag.index.INDEX_CACHE_VERSION`、`retrieval.tokenize.TOKENIZER_VERSION` 与 `RagConfig` 默认值延迟导入，避免循环依赖。`hash_question` 对 `hmac-sha256` 强制非空 key；`sha256` 允许空 key。`config_hash` 只接受白名单字段；键名含 `key|secret|token|password` 时直接 `ValueError`，防止把凭据写进摘要。

- [ ] **Step 4: 运行确认通过**

```powershell
.\.venv\Scripts\python.exe -B -m pytest backend/tests/observability/test_contracts.py backend/tests/observability/test_versioning.py -q -p no:cacheprovider --basetemp backend\.pytest-tmp\obs-contracts
```

预期：全部通过。

- [ ] **Step 5: 写文档并记录锚**

`trace_schema_v0_1.md` 与 `eval_data_v0_1.md` 复制设计文档 §6/§7 的字段与示例；`anchors.json` 记录新增文件的 SHA-256。

---

## Task 2: SQLite Trace Repository

**Files:**
- Create: `backend/src/mktkb/observability/store.py`
- Test: `backend/tests/observability/test_store.py`

**Interfaces:**
- `class TraceRepository:`
  - `__init__(self, path: Path, *, timeout: float = 5.0) -> None`
  - `write(self, trace: TraceRecord, spans: Sequence[SpanRecord]) -> None`
  - `write_best_effort(self, trace: TraceRecord, spans: Sequence[SpanRecord]) -> None`
  - `get(self, trace_id: str) -> tuple[TraceRecord, list[SpanRecord]]`
  - `list_by_request(self, request_id: str) -> list[TraceRecord]`
  - `export_jsonl(self, out: Path, *, since: datetime | None = None) -> int`
  - `purge(self, *, older_than_days: int | None = None, keep_last: int | None = None) -> int`
  - `close(self) -> None`
- Produces: `TraceWriteError`（写入失败）；`write_best_effort` 只记录日志，不抛出。

- [ ] **Step 1: 写失败测试**

```python
def test_write_and_read_roundtrip(tmp_path):
    repo = TraceRepository(tmp_path / "traces.sqlite3")
    repo.write(make_trace(trace_id="t1", request_id="r1"), [make_span("parse", "t1")])
    trace, spans = repo.get("t1")
    assert trace.request_id == "r1"
    assert [span.name for span in spans] == ["parse"]

def test_write_best_effort_swallows_error(tmp_path):
    repo = TraceRepository(tmp_path / "traces.sqlite3")
    repo.close()
    repo.write_best_effort(make_trace(trace_id="t2", request_id="r2"), [])
    # 不抛异常即通过

def test_schema_is_idempotent(tmp_path):
    path = tmp_path / "traces.sqlite3"
    TraceRepository(path).close()
    TraceRepository(path).close()
```

另加 `test_list_by_request_returns_multiple_attempts`、`test_export_jsonl_matches_db`、`test_purge_by_age_and_count`。

- [ ] **Step 2: 运行确认失败**：`pytest backend/tests/observability/test_store.py -q`。
- [ ] **Step 3: 实现 sqlite3 schema**

`traces` 与 `spans` 列名与 `TraceRecord` / `SpanRecord` 一致；JSON 字段以 TEXT 存储；`PRAGMA journal_mode=WAL`；`schema_meta` 写入 `trace_schema_version`；所有 SQL 参数化。

- [ ] **Step 4: 运行确认通过**；再用只读目录验证 `write_best_effort` 不抛。
- [ ] **Step 5: 记录锚**。

---

## Task 3: `QaEngine` / `RagIndex` 最小侵入埋点

**Files:**
- Create: `backend/src/mktkb/observability/tracer.py`
- Create: `backend/tests/observability/conftest.py`
- Modify: `backend/src/mktkb/config.py`（新增 `trace_enabled`、`trace_db_path`、`trace_content_mode`、`trace_hmac_key`）
- Modify: `backend/src/mktkb/main.py`（`request_context`，约 102-108 行；创建 `app.state.trace_repo`）
- Modify: `backend/src/mktkb/qa/service.py`（`QaEngine.answer`、`resolve_rag_config` 增加 trace 配置）
- Modify: `backend/src/mktkb/rag/index.py`（`ask` / `search`）
- Modify: `backend/src/mktkb/rag/retrieval.py`（`search` 内各召回阶段）
- Modify: `backend/src/mktkb/rag/answer.py`（`answer_question` 内生成与事实校验）
- Modify: `backend/src/mktkb/conversations/service.py`（`_answer` 设置 path / legacy span / outcome）
- Test: `backend/tests/observability/test_tracer.py`
- Test: `backend/tests/observability/test_middleware.py`

**Interfaces:**
- `start_trace(*, http_request_id: str, mode: TraceMode, scope: str, path: TracePath = TracePath.RAG, question: str = "", case_id: str | None = None, attempt: int = 1, replayed: bool = False, previous_trace_id: str | None = None, repo: TraceRepository | None = None) -> ContextManager[TraceContext]`
- `current_trace() -> TraceContext | None`
- `class SpanHandle:`
  - `span_id: str`
  - `annotate(self, **attrs: Any) -> None`
- `class TraceContext:`
  - `trace_id: str`
  - `span(self, name: str, **attrs: Any) -> ContextManager[SpanHandle]`
  - `set_request_id(self, request_id: str) -> None`
  - `set_question(self, question: str) -> None`
  - `set_path(self, path: TracePath) -> None`
  - `set_outcome(self, outcome: OutcomeKind, reason: str | None = None, **attrs: Any) -> None`
  - `annotate(self, **attrs: Any) -> None`
  - `finish(self) -> None`
- 中间件只对 `POST /api/v1/conversations/{conversation_id}/messages` 开启；`X-Trace-ID` 返回当前尝试的 `trace_id`。
- `create_app` 在 `settings.trace_enabled` 时创建 `app.state.trace_repo = TraceRepository(settings.trace_db_path)`；中间件把同一个 repo 传给 `start_trace`。
- `settings.trace_enabled` 默认 `False`；本地 P0 用 `MKTKB_TRACE_ENABLED=1` 开启。
- `TraceContext.finish` 调用 `repo.write_best_effort`；未设置 outcome 或 path 时写 `status=incomplete`，不崩溃。

- [ ] **Step 1: 写失败测试**

```python
def test_trace_middleware_sets_header_and_persists(client, trace_repo):
    response = client.post("/api/v1/conversations/.../messages", json={...})
    assert response.headers["X-Trace-ID"]
    trace, spans = trace_repo.get(response.headers["X-Trace-ID"])
    assert trace.request_id
    assert {span.name for span in spans} >= {"parse", "recall", "fuse", "commit"}

def test_clarification_trace_passes_integrity():
    trace, spans = make_trace(
        path=TracePath.RAG,
        outcome=OutcomeKind.CLARIFICATION,
        span_names=["parse", "commit"],
    )
    assert validate_required_spans(trace, [span.name for span in spans]) == []

def test_trace_write_failure_does_not_fail_request(client, monkeypatch):
    monkeypatch.setattr(TraceRepository, "write_best_effort", lambda *a, **k: None)
    response = client.post(...)
    assert response.status_code == 200
```

另加 `test_trace_disabled_creates_no_db`、`test_legacy_path_sets_path_and_outcome`、`test_rag_answer_sets_retrieval_counts`。

- [ ] **Step 2: 运行确认失败**。
- [ ] **Step 3: 实现 `tracer.py`**

`TraceContext` 用 `contextvars` 保存；`span` 支持嵌套与 `parent_span_id`；`finish` 构造 `TraceRecord` 后调用 `TraceRepository.write_best_effort`；未开启或非 QA 路径时 `current_trace()` 返回 `None`，所有调用 no-op。

- [ ] **Step 4: 接入中间件与业务路径**

- `main.py`：在 `request_context` 内为 QA POST 启动 Trace；响应头 `X-Trace-ID`；`finally` 中 `finish`。
- `conversations/service.py::ask`：`trace.set_question(question)`；`_answer` 根据 `_rag_owns_turn` 设置 `TracePath.RAG` 或 legacy；legacy 分支加 `intent_parse`、`retrieve`、`query_expansion`（仅触发）、`model_answer`、`answer_validate`、`commit` Span。
- `qa/service.py::QaEngine.answer`：不新建 Trace，只使用 `current_trace()`；设置 `outcome_kind`。
- `rag/index.py::ask/search`：`parse`、`recall`、`fuse`、`answer`、`commit` Span。
- `rag/retrieval.py::search`：`recall` 父 Span 下挂 `exact_recall`、`lexical_recall`、`embedding_query`、`vector_recall`；`hard_filter`、`fuse`、`rerank` 按实际执行创建。
- `rag/answer.py::answer_question`：`answer`、`fact_validate` Span；记录 `fact_gate_json`。
- 所有 Span 只记计数、稳定引用、耗时、状态；不记原文。

- [ ] **Step 5: 运行确认通过并验证行为不变**

```powershell
.\.venv\Scripts\python.exe -B -m pytest backend/tests/observability -q -p no:cacheprovider --basetemp backend\.pytest-tmp\obs
.\.venv\Scripts\python.exe -B -m pytest backend/tests/integration/test_chat.py backend/tests/integration/test_answer_commit.py -q -p no:cacheprovider --basetemp backend\.pytest-tmp\obs-chat
```

预期：全部通过；固定请求的响应 Body 不变，仅多 `X-Trace-ID`。

- [ ] **Step 6: 记录锚**。

---

## Task 4: 离线评测器（Replay + Local）

**Files:**
- Create: `backend/src/mktkb/evaluation/__init__.py`
- Create: `backend/src/mktkb/evaluation/dataset.py`
- Create: `backend/src/mktkb/evaluation/gold.py`
- Create: `backend/src/mktkb/evaluation/scorers.py`
- Create: `backend/src/mktkb/evaluation/runner.py`
- Create: `backend/src/mktkb/evaluation/corpus.py`（薄适配 `tools/rag_experiment.py` 的 `load_corpus` / `build_new_index`，不复制解析逻辑）
- Create: `backend/tests/evaluation/conftest.py`
- Create: `tools/build_eval_dataset.py`
- Create: `fixtures/evaluation/b0.jsonl`
- Create: `fixtures/evaluation/badcase.jsonl`
- Test: `backend/tests/evaluation/test_dataset.py`
- Test: `backend/tests/evaluation/test_gold.py`
- Test: `backend/tests/evaluation/test_scorers.py`
- Test: `backend/tests/evaluation/test_runner.py`

**Interfaces:**
- `load_cases(path: Path) -> list[CaseSpec]`
- `validate_case(case: CaseSpec) -> None`
- `dataset_version(cases: Sequence[CaseSpec], label_version: str) -> str`
- `resolve_gold(cases: Sequence[CaseSpec], index: RagIndex) -> list[ResolvedGold]`；`GoldUnresolved` 表示 0/多个匹配。
- `class EvalOutcome: kind: str; text: str; citations: Sequence[Citation]; facts: Sequence[Fact]; pagination: Mapping[str, Any]; trace_id: str; path: TracePath`
- `score_case(case: CaseSpec, resolved: ResolvedGold, outcome: EvalOutcome, trace: TraceRecord) -> CaseResult`
- `run_suite(*, suite: str, mode: TraceMode, corpus_dir: Path, out_dir: Path, scope: str = "end_to_end", replay_from: Path | None = None) -> RunResult`
- `CaseResult`、`RunManifest`、`RunResult` 字段按设计文档 §7/§8。

- [ ] **Step 1: 写失败测试**

```python
def test_case_schema_rejects_chunk_id_gold():
    with pytest.raises(ValueError):
        validate_case(CaseSpec(... expected_sources=[{"doc_code": "D01", "chunk_id": "abc"}]))
```

```python
def test_gold_multiple_matches_fails_closed(index_with_two_units_same_key):
    with pytest.raises(GoldUnresolved):
        resolve_gold([case_for_ambiguous_key()], index_with_two_units_same_key)

def test_value_hit_normalizes_fullwidth_and_spaces():
    assert check_value("Ｂ区１号货架", "B区1号货架") is True

def test_source_hit_requires_doc_and_locator():
    assert check_source(
        {"doc_code": "D01", "unit_key": "sheet:物品位置:row:8"},
        {"doc_code": "D01", "unit_key": "sheet:物品位置:row:8"},
    ) is True

def test_refusal_metrics_are_separate():
    metrics = refusal_metrics(cases=[...], results=[...])
    assert "refusal_recall" in metrics
    assert "false_refusal_rate" in metrics
    assert metrics["refusal_recall"] != metrics["false_refusal_rate"]
```

另加 `test_pagination_contract_total_returned_has_more`、`test_retrieval_recall_maps_chunks_to_units`、`test_local_runner_manifest_has_versions`、`test_ocr_cases_are_skipped_in_replay_and_local`、`test_replay_rescores_frozen_run_without_index`。

- [ ] **Step 2: 运行确认失败**。
- [ ] **Step 3: 实现 dataset/gold**

- `CaseSpec` 校验 `expected_sources` 只能含 `doc_code` + `unit_key` / `locator` / `record_code`；出现 `chunk_id` 或 `unit_id` 直接 `ValueError`。
- `resolve_gold`：`doc_code -> RagDocument.doc_id`；`unit_key -> RagUnit.unit_id`；`locator` 按 `kind/sheet/row/heading/page/paragraph` 匹配；0/多匹配抛 `GoldUnresolved`。
- B0 转换：exact 题用 `record_code` 在 xlsx 中定位标识单元格，生成 `sheet:...:row:N`；text 题保留 `locator.heading`；OCR 题保留 `locator.page` 并标 `requires_ocr=true`。
- 13 题转换：读取 `docs/evidence/LOCAL-R1-20261101/S1-DEV/questions.json`，按同样规则生成 `badcase.jsonl`。

- [ ] **Step 4: 实现 scorers/runner**

- scorer：值归一化、来源定位、kind、分页、拒答三指标、检索 Recall@10/MRR@10/nDCG@10、硬过滤违规、空召回、P95、成本；每个 check 输出 `id/status/evidence`。
- `EvalOutcome` 从 `RagAnswer` 归一化得到（`kind/text/citations/facts/pagination/trace_id/path`），避免 scorer 直接依赖一种返回类型。
- `local`：通过 `evaluation/corpus.py` 复用 `tools/rag_experiment.py` 的 `load_corpus` / `build_new_index`，在 `var/eval/runs/<run_id>/index/` 建隔离索引，使用 mock provider，直接调用 `RagIndex.ask`（RAG 内核路径）；每个 case 用 `start_trace(mode=LOCAL, scope="end_to_end", case_id=...)` 包裹，`path=RAG`。`QaEngine` 的产品同步/状态与 legacy 路径由现有 integration tests 与 Task 3 埋点测试覆盖，P0 报告显式标注 `path 覆盖范围`。OCR case 标 `skipped_requires_ocr`。
- `replay`：输入为上一轮 `local` 的 run 目录（`cases.jsonl` + `traces` 引用），只重新评分与门禁，不建索引、不调用任何 provider；`replay_from` 必填。
- 输出 `run_manifest.json`、`cases.jsonl`、`summary.json`。

- [ ] **Step 5: 运行确认通过**

```powershell
.\.venv\Scripts\python.exe -B -m pytest backend/tests/evaluation -q -p no:cacheprovider --basetemp backend\.pytest-tmp\eval
```

- [ ] **Step 6: 生成 P0 数据集并记录锚**

```powershell
.\.venv\Scripts\python.exe -B tools\build_eval_dataset.py --b0 fixtures\acceptance\questions.json --badcase docs\evidence\LOCAL-R1-20261101\S1-DEV\questions.json --out fixtures\evaluation
```

预期：`b0.jsonl` 40 行、`badcase.jsonl` 13 行；无法解析的 gold 必须报错，不静默丢弃。

---

## Task 5: Release Gate

**Files:**
- Create: `backend/src/mktkb/evaluation/gate.py`
- Create: `docs/evaluation/gate_v0_1.json`
- Test: `backend/tests/evaluation/test_gate.py`

**Interfaces:**
- `load_gate_config(path: Path) -> GateConfig`
- `calibrate_gate(run: RunResult, config: GateConfig) -> GateProposal`
- `evaluate_gate(run: RunResult, baseline: Baseline | None, config: GateConfig, *, require_trace: bool = True) -> GateResult`
- `GateResult.exit_code: int`、`hard_failures`、`regressions`、`unknowns`、`warnings`。
- 硬门禁 ID：`security_leak`、`cross_entity`、`stale_bypass`、`conflict_not_rejected`、`exact_value_contract`、`pagination_contract`、`citation_required`、`trace_integrity`。

- [ ] **Step 1: 写失败测试**

```python
def test_hard_gate_sensitive_source_fails():
    result = evaluate_gate(run_with(forbidden_source="D08"), None, config)
    assert "security_leak" in result.hard_failures
    assert result.exit_code == 1

def test_hard_gate_stale_bypass_fails():
    result = evaluate_gate(run_with(stale_source=True), None, config)
    assert "stale_bypass" in result.hard_failures

def test_quality_regression_detected():
    result = evaluate_gate(run_with(recall_at_10=0.70), baseline_with(recall_at_10=0.85), config)
    assert result.exit_code == 2

def test_insufficient_sample_is_unknown():
    result = evaluate_gate(run_with_cases(3), None, config)
    assert result.exit_code == 3
    assert result.unknowns
```

另加 `test_hard_gate_cross_entity`、`test_hard_gate_conflict_not_rejected`、`test_hard_gate_trace_integrity_path_aware`、`test_over_refusal_fails`、`test_waiver_not_allowed_for_hard`、`test_exit_code_mapping`。

- [ ] **Step 2: 运行确认失败**。
- [ ] **Step 3: 实现硬门禁**：按设计文档 §8.1 逐项检查；每个失败带 `case_id`、`check_id`、`evidence`；任一失败 → exit 1。
- [ ] **Step 4: 实现质量门禁与首轮校准**：按 stratum + 总体；指标读 `summary.json`；阈值来自 `gate_v0_1.json`；无 baseline 时只跑绝对阈值；有 baseline 时同时检查 `max_regression_pp`；样本不足 → `unknown`。首轮用 `gate --calibrate` 生成 `gate_proposal.json`（观测值 + 建议阈值 + gate 配置 hash），owner 审批后写入 `gate_v0_1.json`；未审批阈值时只跑硬门禁，质量结果标 `unknown`，不冒充通过。
- [ ] **Step 5: 实现退出码/豁免**：0/1/2/3/4；硬门禁不可豁免；质量 waiver 记录 `reason` / `approver`。
- [ ] **Step 6: 运行确认通过**。

`gate_v0_1.json` 初版只放硬门禁 ID、最小样本数与指标方向；绝对阈值由 P0 首轮 `gate --calibrate` 生成提案后由 owner 审批填入，测试 fixture 使用固定小值。

---

## Task 6: Baseline / Diff 报告

**Files:**
- Create: `backend/src/mktkb/evaluation/baseline.py`
- Create: `backend/src/mktkb/evaluation/report.py`
- Test: `backend/tests/evaluation/test_baseline.py`
- Test: `backend/tests/evaluation/test_report.py`

**Interfaces:**
- `baseline_id(manifest: RunManifest) -> str`
- `save_baseline(run: RunResult, root: Path) -> Baseline`
- `approve_baseline(run: RunResult, gate: GateResult, root: Path, *, approver: str, reason: str) -> Baseline`
- `load_baseline(baseline_id: str, root: Path) -> Baseline`
- `diff_runs(run: RunResult, baseline: Baseline, *, comparison: str) -> DiffResult`
- `render_markdown(diff: DiffResult, gate: GateResult) -> str`
- `render_html(summary: Mapping[str, Any], diff: DiffResult, gate: GateResult) -> str`

- [ ] **Step 1: 写失败测试**

```python
def test_baseline_id_binds_versions():
    assert baseline_id(manifest(pipeline_version="p1")) != baseline_id(manifest(pipeline_version="p2"))

def test_cross_version_requires_compare_with():
    with pytest.raises(ValueError):
        diff_runs(run(pipeline_version="p2"), baseline(pipeline_version="p1"), comparison="release")

def test_diff_lists_new_and_fixed_failures():
    diff = diff_runs(run_with(failed={"Q03"}), baseline_with(failed={"Q07"}), comparison="explicit_cross_version")
    assert "Q03" in diff.new_failures
    assert "Q07" in diff.fixed_failures

def test_report_hard_failures_first():
    html = render_html(summary, diff_with_hard_failure, gate_with_hard_failure)
    assert html.index("硬门禁") < html.index("质量回退")
```

另加 `test_same_pipeline_uses_release_baseline`、`test_baseline_approval_requires_approver_and_reason`、`test_baseline_approval_requires_passing_gate`、`test_no_baseline_copy_command`。

- [ ] **Step 2: 运行确认失败**。
- [ ] **Step 3: 实现 baseline**：`baseline_id` 绑定 `dataset_version + pipeline_version + mode + scope + gate_version + corpus_sha256`；`approve_baseline` 写 `approval.json`，包含 `run_id`、`gate_result_sha256`、`dataset_version`、`pipeline_version`、`corpus_sha256`、`approver`、`reason`；硬门禁未通过时拒绝建立；没有 `copy` 函数/命令。
- [ ] **Step 4: 实现 diff/report**：`summary.json`、`diff.json`、`report.md`、`report.html`；HTML 单文件、内联 CSS、无 JS；硬门禁失败排最前。
- [ ] **Step 5: 运行确认通过**。

---

## Task 7: CLI 与 P0 集成验收

**Files:**
- Create: `backend/src/mktkb/evaluation/cli.py`
- Create: `tools/rag_eval.py`
- Create: `backend/tests/evaluation/golden/chat_response.json`
- Test: `backend/tests/evaluation/test_p0_acceptance.py`
- Create: `docs/reports/OBS-EVAL/P0/p0-report.md`（入库；原始运行产物 var/eval 不入库）

**Interfaces / Commands:**

```powershell
.\.venv\Scripts\python.exe -B tools\rag_eval.py dataset build --b0 fixtures\acceptance\questions.json --badcase docs\evidence\LOCAL-R1-20261101\S1-DEV\questions.json --out fixtures\evaluation
.\.venv\Scripts\python.exe -B tools\rag_eval.py dataset validate --suite b0 --path fixtures\evaluation\b0.jsonl
.\.venv\Scripts\python.exe -B tools\rag_eval.py run --suite b0 --mode local --out var\eval\runs\p0-b0
.\.venv\Scripts\python.exe -B tools\rag_eval.py run --suite badcase --mode local --out var\eval\runs\p0-badcase
.\.venv\Scripts\python.exe -B tools\rag_eval.py run --suite b0 --mode replay --from-run var\eval\runs\p0-b0 --out var\eval\runs\p0-b0-replay
.\.venv\Scripts\python.exe -B tools\rag_eval.py gate --run var\eval\runs\p0-b0 --config docs\evaluation\gate_v0_1.json --calibrate
.\.venv\Scripts\python.exe -B tools\rag_eval.py baseline approve --run var\eval\runs\p0-b0 --gate var\eval\runs\p0-b0\gate.json --approver lead --reason "P0 calibration"
.\.venv\Scripts\python.exe -B tools\rag_eval.py diff --run var\eval\runs\p0-b0 --baseline <baseline_id>
```

- [ ] **Step 1: 写 P0 验收测试**（7 条）

`backend/tests/evaluation/conftest.py` 提供 `golden_chat_response`、`run_result`、`gate_result`、`config_with_fixed_thresholds`、`provider_spy`、`socket_guard`、`ask`、`normalize`、`last_response`；`corpus_dir` 指向 `corpus/enterprise-20261101`；`client`/`trace_repo` 复用现有 integration fixtures。

```python
def test_p0_no_business_behavior_change(client, golden_chat_response):
    # 归一化 request_id/message_id/时间等易变字段后，与改动前 golden 比较
    body = ask(client, question="城东店的宣传海报在哪里？")
    assert normalize(body) == golden_chat_response
    assert "X-Trace-ID" in last_response.headers

def test_p0_trace_id_end_to_end(client, trace_repo):
    response = client.post(
        "/api/v1/conversations/{id}/messages",
        json={"client_request_id": str(uuid4()), "question": "城东店的宣传海报在哪里？"},
    )
    trace, spans = trace_repo.get(response.headers["X-Trace-ID"])
    assert trace.request_id
    assert spans

def test_p0_suites_are_independent(tmp_path, corpus_dir):
    b0 = run_suite(suite="b0", mode=TraceMode.LOCAL, corpus_dir=corpus_dir, out_dir=tmp_path / "b0")
    bad = run_suite(suite="badcase", mode=TraceMode.LOCAL, corpus_dir=corpus_dir, out_dir=tmp_path / "bad")
    assert b0.suite == "b0" and bad.suite == "badcase"
    assert (tmp_path / "b0" / "summary.json").exists()
    assert (tmp_path / "bad" / "summary.json").exists()

def test_p0_versions_bound(run_result):
    assert run_result.manifest.dataset_version
    assert run_result.manifest.index_revision is not None
    assert run_result.manifest.pipeline_version

def test_p0_baseline_diff_json(tmp_path, run_result, gate_result):
    baseline = approve_baseline(run_result, gate_result, tmp_path, approver="lead", reason="test")
    assert (tmp_path / baseline.baseline_id / "approval.json").exists()
    assert (run_result.out_dir / "diff.json").exists()

def test_p0_hard_gate_nonzero_exit(tmp_path, config_with_fixed_thresholds):
    assert evaluate_gate(run_with_sensitive_source, None, config_with_fixed_thresholds).exit_code == 1
    assert evaluate_gate(clean_run_meeting_thresholds, None, config_with_fixed_thresholds).exit_code == 0

def test_p0_zero_real_calls(provider_spy, socket_guard):
    assert provider_spy.calls == 0
    assert socket_guard.attempts == 0
```

- [ ] **Step 2: 运行确认失败**。
- [ ] **Step 3: 实现 CLI**：子命令 `dataset build/validate`、`run`（支持 `--mode replay --from-run`）、`baseline approve/list`（`approve` 必须带 `--gate`）、`gate`（支持 `--calibrate`）、`diff`、`export`；退出码透传；`--allow-holdout-details` 在 P0 不存在。
- [ ] **Step 4: 跑 P0 全流程**

按上面的命令依次执行；`gate --calibrate` 生成 `gate_proposal.json`，由 owner 审批后写入 `docs/evaluation/gate_v0_1.json`；注入一条敏感来源 case 验证 exit 1，干净集验证 exit 0；确认 `report.html` 生成且不参与门禁。

- [ ] **Step 5: 零真实调用与回归验收**

```powershell
.\.venv\Scripts\python.exe -B -m pytest backend/tests -q -p no:cacheprovider --basetemp backend\.pytest-tmp\p0-full
```

预期：现有测试全绿；provider spy=0、socket guard=0、不读 `.env`。

- [ ] **Step 6: 写 `p0-report.md`**

记录 7 条验收、命令、结果、SHA-256 锚、未测边界；明确写明：

> P0 只证明离线回归与确定性门禁工作正常，不证明端到端 RAG 的真实回答质量已经提升；真实检索与生成效果在 P1/P2 用固定数据集验证。

---

## P0 验收映射

| 验收项 | 主要任务 | 证据 |
| --- | --- | --- |
| 现有业务行为不变 | Task 3、Task 7 | 现有 pytest + 固定响应 golden（仅多 `X-Trace-ID`） |
| 每执行尝试可关联完整阶段 | Task 3 | `X-Trace-ID` + `traces`/`spans` 行 |
| B0 与 Bad Case 独立回归 | Task 4、Task 7 | 两次独立 `run` 的 `summary.json` |
| 绑定 dataset/index/pipeline | Task 1、Task 4、Task 6 | `run_manifest.json` + 每条 `CaseResult` |
| baseline/diff/JSON 报告 | Task 6、Task 7 | `baseline/approval.json`、`diff.json`、`report.md` |
| 硬门禁非零退出 | Task 5、Task 7 | 注入 case 的 exit 1；干净集 exit 0 |
| 零真实调用 | Task 7 | provider spy=0、socket guard=0、未读 `.env` |

## Execution Handoff

计划完成后，请先审阅本计划与设计文档，再决定执行方式：

- **Native（推荐）**：在当前会话按 Task 1 → Task 7 顺序执行，每个任务结束跑对应测试并记录 SHA-256 锚；最后做一次独立复核。任务之间接口强耦合、仓库有中文编码与证据锚等特殊约定，单线执行更不容易丢上下文。
- **Subagent-driven**：每个 Task 由新的 subagent 实现、另一个 subagent 复核；更彻底，但成本更高，且需要把 Global Constraints 与 Spec 一起传给每个 subagent。

当前只读策略解除后再开始 Task 1；本稿保存不代表已执行。

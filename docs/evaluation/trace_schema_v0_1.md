# Trace 数据契约 v0.1（T001）

> 状态：P0 契约冻结稿（Task 1）。
> 来源：`docs/superpowers/specs/2026-11-04-mktkb-observability-evaluation-design.md` §6.3 / §6.4 / §6.5 / §7.3。
> 实现：`backend/src/mktkb/observability/contracts.py`、`backend/src/mktkb/observability/versioning.py`。
> 本契约只描述数据形状与摘要口径，不涉及 SQLite 表结构（Task 2 落地）与业务埋点（Task 3 落地）。

## 1. 三套 Schema 版本

| 常量（`mktkb.observability.contracts`） | 值 | 用途 |
| --- | --- | --- |
| `TRACE_SCHEMA_VERSION` | `mktkb.trace.v0.1` | traces / spans 记录与导出格式 |
| `CASE_SCHEMA_VERSION` | `mktkb.eval.case.v0.1` | 评测 Case（JSONL）格式 |
| `GATE_SCHEMA_VERSION` | `mktkb.gate.v0.1` | Release Gate 配置与结果格式 |

版本号只在**破坏性字段变化**时提升；新增可空字段属于兼容变化，需在本文档追加说明。

## 2. 粒度与标识

**每次执行尝试产生一条 Trace。** `request_id` 对应产品请求，`trace_id` 对应执行尝试，两者是 1:N。
重试、租约恢复、幂等重放各自留痕，不覆盖历史；只有重放没有真实执行时仍写一条
`status=replayed` 的 Trace，Span 集合为空。

| 字段 | 含义 |
| --- | --- |
| `trace_id` | 本次执行尝试的唯一 ID；`X-Trace-ID` 返回它 |
| `request_id` | 产品请求 ID（`ConversationRequest.id`） |
| `http_request_id` | HTTP 中间件生成的请求 ID，与现有 `X-Request-ID` 对齐 |
| `attempt` | 同一产品请求的第几次执行尝试 |
| `replayed` | 是否为幂等重放；重放不产生新的模型/检索执行 |
| `previous_trace_id` | 重试、租约恢复或重放时指向上一次尝试 |

## 3. 枚举

`TraceMode`：`replay` / `local` / `live`。P0 只允许 `replay`、`local`；`live` 禁止。

`TracePath`：`rag` / `legacy` / `legacy_with_rag_candidates`。

`OutcomeKind`：`answer` / `clarification` / `no_answer` / `ambiguous` / `conflict` / `error` /
`not_found` / `service_error` / `knowledge_changed`。

## 4. Trace 字段（`TraceRecord`）

`TraceRecord` 是 `@dataclass(frozen=True)`；`traces` 表与 JSONL 导出使用同一字段名。
下表的「必填」指成功写入的记录上必须有值（由写入方/门禁保证），构造对象时字段均可空。

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `trace_id` | str | 是 | 执行尝试 ID |
| `request_id` | str | 是 | 产品请求 ID |
| `http_request_id` | str | 是 | HTTP 请求 ID |
| `attempt` | int | 是 | 尝试序号，默认 1 |
| `replayed` | bool | 是 | 是否幂等重放，默认 False |
| `previous_trace_id` | str? | 否 | 重试/恢复/重放的上一次尝试 |
| `trace_schema_version` | str | 是 | 默认 `mktkb.trace.v0.1` |
| `mode` | str | 是 | `replay` / `local` / `live` |
| `scope` | str | 是 | `retrieval_only` / `end_to_end` |
| `path` | str | 是 | `rag` / `legacy` / `legacy_with_rag_candidates` |
| `case_id` | str? | 否 | 评测 case ID |
| `dataset_version` | str? | 否 | 见 `eval_data_v0_1.md` |
| `run_id` | str? | 否 | 评测 run ID |
| `index_revision` | str | 是 | 索引 revision |
| `manifest_sha256` | str | 是 | 语料/索引清单 SHA-256 |
| `pipeline_version` | str | 是 | 见 §6.1 |
| `config_hash` | str | 是 | 见 §6.2 |
| `query_kind` | str | 是 | `record` / `document` |
| `outcome_kind` | str | 是 | `OutcomeKind` 取值 |
| `reason` | str? | 否 | 稳定原因码/说明 |
| `answer_source` | str | 是 | 作答来源（rag / legacy / …） |
| `content_mode` | str | 是 | `off` / `hash` / `redacted` / `full`，默认 `hash` |
| `question_hash` | str? | 条件 | `content_mode != off` 时存在 |
| `question_chars` | int? | 条件 | 问题字符数（不含原文） |
| `hash_algo` | str? | 条件 | `hmac-sha256` / `sha256` |
| `hmac_key_id` | str? | 条件 | HMAC key 指纹（见 §6.3），不存密钥 |
| `user_id_hash` | str? | 否 | 用户 ID 摘要 |
| `conversation_id_hash` | str? | 否 | 会话 ID 摘要 |
| `retrieval_counts_json` | str? | 否 | canonical JSON 文本 |
| `filter_decisions_json` | str? | 否 | canonical JSON 文本 |
| `fact_gate_json` | str? | 否 | canonical JSON 文本 |
| `citation_refs_json` | str? | 否 | canonical JSON 文本 |
| `pagination_json` | str? | 否 | canonical JSON 文本 |
| `token_usage_json` | str? | 否 | canonical JSON 文本 |
| `cost_json` | str? | 否 | canonical JSON 文本 |
| `go_decision` | str? | 否 | live 预算门禁结论（P0 恒为不适用/空） |
| `degraded_json` | str? | 否 | canonical JSON 文本 |
| `latency_ms` | int? | 否 | 端到端耗时毫秒 |
| `status` | str | 是 | `ok` / `replayed` / `error` 等 |
| `error_code` | str? | 否 | 稳定错误码 |
| `created_at` | str? | 否 | UTC ISO-8601 文本 |

`*_json` 字段以 `ensure_ascii=False, sort_keys=True` 的 JSON 文本存储，不存 Python repr。

稳定引用统一写成 `doc_code:unit_key`（同版本）或 `doc_code + locator`（跨版本）；
Trace 不把 `chunk_id` UUID 当业务身份，只存 `chunk_id_hash` 供调试。

## 5. Span 字段（`SpanRecord`）

`SpanRecord` 是 `@dataclass(frozen=True)`；`spans` 表与 JSONL 导出使用同一字段名。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `span_id` | str | Span 唯一 ID |
| `trace_id` | str | 所属 Trace |
| `parent_span_id` | str? | 父 Span；`recall` 下的通道 Span 挂在 `recall` 上 |
| `name` | str | 见 §5.1 的 Span 名称 |
| `started_at` | str? | UTC ISO-8601 文本 |
| `duration_ms` | int? | 耗时毫秒 |
| `status` | str | `ok` / `error` 等 |
| `attributes_json` | str? | canonical JSON 文本（条件属性等） |
| `error_code` | str? | 稳定错误码 |

### 5.1 Span 名称

- RAG：`parse`、`recall`、`exact_recall`、`lexical_recall`、`embedding_query`、`vector_recall`、
  `hard_filter`、`fuse`、`rerank`、`answer`、`fact_validate`、`commit`、`index_sync`。
- Legacy：`intent_parse`、`retrieve`、`query_expansion`、`model_answer`、`answer_validate`、`commit`。

`recall` 是父 Span，下面挂实际执行的子 Span。没有执行的通道不创建 Span。

## 6. 路径感知必需 Span（`required_spans` / `conditional_required_spans`）

### 6.1 基础必需 Span

`required_spans(path, outcome)` 按设计 §6.4 表实现，共 8 行：

| path + outcome | 必需 Span |
| --- | --- |
| `rag` + `answer` / `conflict` | `parse`、`recall`、`fuse`、`answer`、`commit` |
| `rag` + `clarification` | `parse`、`commit` |
| `rag` + `no_answer` / `ambiguous` | `parse`、`recall`、`fuse`、`commit` |
| `rag` + `error` / `knowledge_changed` | `parse`、`commit` |
| `legacy` / `legacy_with_rag_candidates` + `answer` | `intent_parse`、`retrieve`、`model_answer`、`answer_validate`、`commit` |
| `legacy` + `not_found` | `intent_parse`、`retrieve`、`commit` |
| `legacy` + `clarification` | `intent_parse`、`commit` |
| `legacy` + `service_error` | `intent_parse`、`commit` |

- `legacy_with_rag_candidates` 与 `legacy` 共用 legacy 规则（8 行之外不另立规则）。
- 设计表未定义的组合（如 `rag + not_found`、`legacy + error`）**fail closed**：抛 `ValueError`，
  不静默返回空集。
- 两个易错点：`rag + clarification` 不含 `answer`；`legacy + not_found` 不含
  `query_expansion` / `answer`（/ `model_answer`）。

### 6.2 条件必需 Span

`conditional_required_spans(attrs)` 只认四个键，值为真时要求对应 Span；其余键一律忽略，
空属性返回空集：

| 属性 | 必需 Span |
| --- | --- |
| `vector_enabled=true` | `vector_recall` |
| `rerank_enabled=true` | `rerank` |
| `expansion_triggered=true` | `query_expansion` |
| `index_sync_performed=true` | `index_sync` |

gate 检查 `required_spans ∪ conditional_required_spans`；缺少必需 Span → `trace_integrity`
硬失败。未执行的可选阶段不要求、也不伪造。

## 7. 内容与隐私

### 7.1 `content_mode`

| `content_mode` | 存什么 | 允许场景 |
| --- | --- | --- |
| `off` | 不存问题/答案/上下文，只存计数与 ID | 生产默认最保守 |
| `hash` | 问题/答案/上下文哈希 + 长度 | 生产默认、P0 默认 |
| `redacted` | 脱敏后的文本 | 生产排障、人工复核 |
| `full` | 原文 | 仅合成语料评测 |

- 真实业务问题：`hmac-sha256`，密钥只来自 `MKTKB_TRACE_HMAC_KEY`；Trace 只存 `hmac_key_id`，
  不存密钥。
- 合成语料：可用 `sha256` 或 `full`。
- 默认不存检索上下文、答案全文、模型输入输出原文。
- 脱敏至少覆盖手机号、长数字编号、邮箱、URL 中的凭据、常见密钥形态。

### 7.2 摘要格式（`mktkb.observability.versioning`）

所有摘要 = `sha256(canonical_json).hexdigest()[:12]`（12 位十六进制前缀）；canonical JSON 为
`ensure_ascii=False, sort_keys=True, separators=(",", ":")`。与
`dataset_version = suite:label_version:sha256[:12]` 口径一致。

| 函数 | 入参 | 输出 | 规则 |
| --- | --- | --- | --- |
| `pipeline_version(components=None)` | 组件映射或 None | 12 位 hex | `None` 时调用期延迟导入默认组件；显式映射**完全替换**默认组件 |
| `config_hash(config)` | 配置映射 | 12 位 hex | 只纳入白名单字段；键名含 `key|secret|token|password`（不区分大小写）→ `ValueError` |
| `hash_question(q, *, key=b"", algo="hmac-sha256")` | 问题文本 | 64 位 hex | `hmac-sha256` 强制非空 key；`sha256` 允许空 key（合成语料） |
| `key_fingerprint(key)` | HMAC key bytes | 12 位 hex | 域分隔后哈希，用于 `hmac_key_id`；空 key → `ValueError` |

`pipeline_version()` 默认组件（调用时从业务模块 lazy import）：

- `qa_engine_version` ← `mktkb.qa.service.QA_ENGINE_VERSION`
- `rag_schema_version` / `index_cache_version` ← `mktkb.rag.index.SCHEMA_VERSION` / `INDEX_CACHE_VERSION`
- `tokenizer_version` ← `mktkb.retrieval.tokenize.TOKENIZER_VERSION`
- `RagConfig()` 默认值：`embedding_model`、`embedding_dimensions`、`rerank_model`、
  `chunk_max_chars`、`chunk_max_units`、`chunk_overlap_units`、`top_k`、`page_size`

`config_hash` 白名单（`CONFIG_HASH_FIELDS`，白名单之外字段忽略、不报错）：

```text
provider_mode, embedding_model, embedding_dimensions, rerank_model, rerank_top_n,
rerank_max_documents, chat_model, chunk_max_chars, chunk_max_units, chunk_overlap_units,
top_k, candidate_limit, vector_candidate_limit, page_size, max_page_size, hard_filters
```

> 注意：白名单不能包含字段名带 `token` 的字段（如 `max_output_tokens`），因为键名规则会
> 直接拒绝；该类字段也不进入摘要。

## 8. 存储与写入语义（引用设计 §6.2 / §6.6，由 Task 2/3 实现）

- 主存储：`var/observability/qa-traces.sqlite3`，与 `mktkb.sqlite3`、`rag-index.sqlite3` 完全分离；
  表：`schema_meta`、`traces`、`spans`；WAL；JSON 字段以 canonical JSON 文本写入。
- `schema_meta.trace_schema_version` 必须等于 `TRACE_SCHEMA_VERSION`，不一致时导出/门禁
  fail closed。
- 产品问答：`write_best_effort`，写入失败只记 `trace_write_error` 日志，不影响响应。
- 评测/门禁：`require_trace=true`；缺 Trace、缺必需 Span、版本不一致 → `trace_integrity`
  硬失败，退出码 1，不可豁免。
- 默认保留 30 天或 100,000 条，二者先到先清理；JSONL 只通过 `export` 生成，不作为第二写入源。

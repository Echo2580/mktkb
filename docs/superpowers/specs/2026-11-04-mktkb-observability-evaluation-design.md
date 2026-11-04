# MKTKB RAG Evaluation & Observability v0.1 设计

- 状态：定稿（2026-11-04）
- 实现范围：P0
- 适用项目：市场部 AI 知识库（`backend/src/mktkb`）
- 关联计划：`docs/superpowers/plans/2026-11-04-mktkb-observability-evaluation-p0.md`

## 1. 意图

在不改变现有问答业务行为的前提下，为 `QaEngine` / `RagIndex` 增加一套**厂商中立**的 RAG 评测与可观测性内核：

- 每次执行尝试留下可查询的 Trace；
- 用确定性规则对固定数据集做可重复评测；
- 用双层发布门禁把“安全/契约失败”和“质量回退”分开；
- 用 Baseline/Diff 回答“这次改动到底变好还是变差”。

Ragas、Langfuse、Web 看板、实时告警都不进入 P0。它们只在后续阶段作为可选导出层或展示层接入，避免 P0 被工具链绑架。

## 2. 当前基础

项目已经具备以下能力，评测体系应围绕它们建设，而不是另起一套通用评分：

- `QaEngine`：索引与产品 revision 同步、查询状态持久化、六类结果映射（`backend/src/mktkb/qa/service.py`）。
- `RagIndex`：精确/FTS/向量混合召回、RRF、重排、结构化事实与来源（`backend/src/mktkb/rag/`）。
- 事实门禁：伪造值、跨实体、跨字段、无引用、失效来源拒绝（`rag/facts.py`）。
- 业务日期与有效期过滤（`rag/retrieval.py`）。
- 冲突检测、分页与“全部”枚举。
- 预算账本、请求上限、live 门禁与脱敏（`rag/budget.py`、`qa/service.py`、`live_authorization.py`）。
- 已有的 B0 40 题、Bad Case 13 题、`tools/rag_experiment.py`、pytest 与证据目录。

缺口是闭环：没有一条命令跑完并按阈值非零退出的回归门禁；没有检索级金标；Trace 只存在于返回值或临时日志，不落库、不聚合；没有发布前质量对比。

## 3. 目标、非目标、反目标

### 3.1 目标

1. 每个问答执行尝试可以通过 `trace_id` 关联实际执行的阶段、召回、事实门禁、耗时与费用。
2. B0 40 与 Bad Case 13 可独立回归；P1 加入 Holdout 30。
3. 硬门禁与质量门禁分离；质量指标按 stratum 报告，不设综合分。
4. Baseline 与 Diff 可复现，结果绑定数据集、索引、管线与语料版本。
5. SQLite 作为本地查询的唯一真相源，JSONL 只做导出。
6. P0 零真实模型调用、零新生产依赖、零业务行为变化。

### 3.2 非目标

- P0 不接 Ragas、Langfuse、Web Dashboard、实时告警。
- P0 不做 live 端到端评测。
- P0 不修改 chunk、embedding、rerank、prompt 的行为。
- P0 不修改现有业务 API 的请求参数与响应 Body。
- P0 不修改业务数据库 schema，也不修改 `rag-index.sqlite3` schema。
- P0 不重建语料、不改冻结 fixtures、不改验收矩阵。

### 3.3 反目标

- 用一个大而全的综合分替代分层指标。
- 用大量拒答换取“看起来安全”的分数。
- Replay 通过就宣称当前代码没有回归。
- 复制旧版本 Baseline 给新 `pipeline_version` 放行。
- 把真实业务问题原文、答案、上下文默认写入日志或第三方面板。
- 为了让门禁通过而修改判分器、弱化断言或跳过失败样本。

## 4. 约束

- Python 3.12.7，项目 `.venv`；P0 不新增生产依赖。
- 仓库没有 `.git`：任务结束时记录 SHA-256 锚，不执行 `git commit`。
- 真实模型/OCR 调用受 GO、预算账本和固定路径校验约束；P0 完全禁止。
- Trace 生产默认关闭；本地 P0 默认开启；写入 best-effort。
- 内容模式默认 `hash`；真实业务只允许 `hash` / `redacted`；`full` 只允许合成语料。
- 真实业务问题哈希使用 HMAC-SHA256，密钥不进入仓库、数据库或报告。
- 必需 Span 按实际执行路径检查；未执行的可选阶段不得伪造。
- Baseline 同 `pipeline_version` 才能用于发布放行；跨版本显式 `--compare-with`，只分析。
- P0 只跑 B0 40 + Bad Case 13；Holdout 30 在 P1 引入。

## 5. 架构：轻量内核 B+

```text
HTTP POST /conversations/{id}/messages
        │
        ├─ request_context：生成 request_id / trace_id
        │
        ├─ conversations._answer
        │     ├─ 记录 path（rag / legacy / legacy_with_rag_candidates）
        │     ├─ RAG 路径：QaEngine.answer → RagIndex.ask → retrieval/answer/facts
        │     └─ legacy 路径：intent_parse → retrieve → (query_expansion) → model → validate
        │
        ├─ TraceContext（contextvar）
        │     ├─ spans：parse/recall/fuse/rerank/answer/fact_validate/commit...
        │     └─ attributes：计数、稳定引用、版本、耗时、费用、降级、错误
        │
        └─ TraceRepository（SQLite）
              ├─ traces / spans
              └─ export → JSONL（只导出，不并行写）

评测器（tools/rag_eval.py）
        ├─ Replay：冻结产物 → 确定性评分/门禁/报告
        ├─ Local：真实索引/检索 + mock provider → 评分/门禁/报告
        └─ 读取同一 TraceRepository 与运行清单 → baseline/diff
```

Trace 内核不依赖厂商 SDK。未来接 Langfuse / OTel 时，只新增 exporter，不改 `QaEngine` / `RagIndex`。

## 6. Trace 契约 v0.1

### 6.1 粒度与标识

**每次执行尝试产生一条 Trace。** `request_id` 对应产品请求，`trace_id` 对应执行尝试，两者是 1:N。

| 字段 | 含义 |
| --- | --- |
| `trace_id` | 本次执行尝试的唯一 ID；`X-Trace-ID` 返回它 |
| `request_id` | 产品请求 ID（`ConversationRequest.id`） |
| `http_request_id` | HTTP 中间件生成的请求 ID，便于和现有 `X-Request-ID` 对齐 |
| `attempt` | 同一产品请求的第几次执行尝试 |
| `replayed` | 是否为幂等重放；重放不产生新的模型/检索执行 |
| `previous_trace_id` | 重试、租约恢复或重放时指向上一次尝试 |

重试、恢复、幂等重放各自留痕，不覆盖历史。若一次产品请求只有重放、没有真实执行，仍然写一条 `status=replayed` 的 Trace，Span 集合为空。

### 6.2 存储

- 主存储：`var/observability/qa-traces.sqlite3`，与 `mktkb.sqlite3`、`rag-index.sqlite3` 完全分离。
- 表：`schema_meta`、`traces`、`spans`。
- 写入使用 WAL；JSON 字段以 `ensure_ascii=False, sort_keys=True` 序列化。
- 默认保留 30 天或 100,000 条，二者先到先清理；提供 `purge` 命令。
- JSONL 只通过 `export` 生成，不作为第二写入源。

### 6.3 Trace 字段

`traces` 至少包含：

```text
trace_id, request_id, http_request_id, attempt, replayed, previous_trace_id
trace_schema_version, mode(replay|local|live), scope(retrieval_only|end_to_end)
path(rag|legacy|legacy_with_rag_candidates)
case_id?, dataset_version?, run_id?
index_revision, manifest_sha256, pipeline_version, config_hash
query_kind(record|document), outcome_kind, reason, answer_source
content_mode(off|hash|redacted|full), question_hash, question_chars,
hash_algo(hmac-sha256|sha256), hmac_key_id
user_id_hash?, conversation_id_hash?
retrieval_counts_json, filter_decisions_json, fact_gate_json,
citation_refs_json, pagination_json
token_usage_json, cost_json, go_decision
degraded_json, latency_ms, status, error_code, created_at
```

`spans` 至少包含：

```text
span_id, trace_id, parent_span_id, name,
started_at, duration_ms, status, attributes_json, error_code
```

稳定引用统一写成 `doc_code:unit_key`（同版本）或 `doc_code + locator`（跨版本）；Trace 不把 `chunk_id` UUID 当业务身份，只存 `chunk_id_hash` 供调试。

### 6.4 Span 名称与路径感知完整性

基础 Span 名称：

- RAG：`parse`、`recall`、`exact_recall`、`lexical_recall`、`embedding_query`、`vector_recall`、`hard_filter`、`fuse`、`rerank`、`answer`、`fact_validate`、`commit`、`index_sync`。
- Legacy：`intent_parse`、`retrieve`、`query_expansion`、`model_answer`、`answer_validate`、`commit`。

`recall` 是父 Span，下面挂实际执行的子 Span。没有执行的通道不创建 Span。

基础必需 Span（`required_spans(path, outcome_kind)`）：

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

条件必需 Span（`conditional_required_spans(attrs)`）：

- `vector_enabled=true` → `vector_recall`；
- `rerank_enabled=true` → `rerank`；
- `expansion_triggered=true` → `query_expansion`；
- `index_sync_performed=true` → `index_sync`。

gate 检查 `required_spans ∪ conditional_required_spans`。缺少必需 Span → `trace_integrity` 硬失败。未执行的可选阶段不要求、也不伪造。

### 6.5 内容与隐私

| `content_mode` | 存什么 | 允许场景 |
| --- | --- | --- |
| `off` | 不存问题/答案/上下文，只存计数与 ID | 生产默认最保守 |
| `hash` | 问题/答案/上下文哈希 + 长度 | 生产默认、P0 默认 |
| `redacted` | 脱敏后的文本 | 生产排障、人工复核 |
| `full` | 原文 | 仅合成语料评测 |

- 真实业务问题：`hmac-sha256`，密钥来自 `MKTKB_TRACE_HMAC_KEY`；Trace 只存 `hmac_key_id`，不存密钥。
- 合成语料：可用 `sha256` 或 `full`。
- 默认不存检索上下文、答案全文、模型输入输出原文。
- 脱敏至少覆盖手机号、长数字编号、邮箱、URL 中的凭据、常见密钥形态。
- `config_hash` 只接受白名单字段；键名含 `key|secret|token|password` 时直接拒绝，防止把凭据写进摘要。

### 6.6 写入语义

- 产品问答：`write_best_effort`。写入失败只记 `trace_write_error` 日志，不影响响应。
- 评测/门禁：`require_trace=true`。缺 Trace、缺必需 Span、版本不一致 → `trace_integrity` 硬失败，退出码 1，不可豁免。
- 同一产品请求允许多条 Trace；`X-Trace-ID` 返回当前尝试的 `trace_id`。

## 7. Evaluation Data Protocol v0.1

### 7.1 Case 结构

一行一个 case 的 JSONL：

```json
{
  "case_id": "H01",
  "suite": "holdout",
  "split": "holdout",
  "stratum": "paraphrase",
  "business_date": "2026-10-28",
  "question": "海报搁哪儿了？",
  "turns": [],
  "expected_kind": "answer",
  "expected_values": ["B区1号货架第二层"],
  "expected_sources": [
    {"doc_code": "D01", "record_code": "P01", "unit_key": "sheet:物品位置:row:8"}
  ],
  "relevant_units": [
    {"doc_code": "D01", "unit_key": "sheet:物品位置:row:8"}
  ],
  "reference_answer": "城东店的宣传海报在B区1号货架第二层。",
  "should_refuse": false,
  "refusal_reason": null,
  "forbidden_values": [],
  "forbidden_sources": [],
  "expected_pagination": null,
  "requires_ocr": false,
  "labeler": "lead",
  "label_version": "holdout-2026-11-04",
  "notes": ""
}
```

字段规则：

- `expected_sources` 只允许 `doc_code` + `unit_key` 或 `locator`；**禁止写 chunk_id / unit_id UUID**。
- `relevant_units` 用于检索指标；缺省时由 `expected_sources` 派生。
- `reference_answer` 用于 Ragas 的 Context Recall / Answer Correctness；P0 可为空，P1 的 Holdout 必须有人工参考答案。
- `should_refuse=true` 的 case 必须有 `refusal_reason`；可带 `forbidden_values` / `forbidden_sources` 检测泄漏。
- `turns` 非空表示多轮；runner 顺序执行，逐轮记录 Trace，全部轮次通过才算 case 通过。
- `requires_ocr=true` 在 Replay/Local 明确 `skipped_requires_ocr`，不算通过；只在 P2 live 执行。

### 7.2 稳定引用解析

```text
doc_code + unit_key  -> 当前索引 RagUnit.unit_id -> 相关 chunk
doc_code + locator   -> 按 kind/sheet/row/heading/page/paragraph 匹配
```

- 解析到 0 个或多个 unit：`GoldUnresolved`，case 状态 `error`，门禁退出码 3；不能随意挑一个 chunk。
- 多个 chunk 命中同一 unit：按 unit 去重后再算 Recall@k / MRR。
- 跨版本比较：优先 `unit_key`；不存在时回退 `locator`。

### 7.3 数据集与版本

- `dataset_version = suite:label_version:sha256[:12]`。
- 运行清单绑定：`dataset_sha256`、`corpus_manifest_sha256`、`business_date`、`index_revision`、`pipeline_version`、`gate_version`、`mode`、`scope`。
- 每个 `CaseResult` 都带这些版本字段，报告可按任意维度分组。
- P0 数据集：
  - `b0`：40 题，exact 24 / text 8 / ocr 8；来自 `fixtures/acceptance/questions.json`。
  - `badcase`：13 题，来自 `docs/evidence/LOCAL-R1-20261101/S1-DEV/questions.json`；单独统计，不进入 Holdout。
- P1 数据集：`holdout` 30 题，分层 10 改写/模糊、5 多轮、5 负样本、5 过期/冲突、5 跨文档/安全。

### 7.4 Holdout 防污染

- Holdout 与 B0/Bad Case 分文件、分 `split`。
- CLI 默认只输出分层聚合；查看具体 case 需 `--allow-holdout-details`，并写入 `holdout_audit.json`。
- CI/门禁禁止 `--allow-holdout-details`。
- 失败样本正式转入 Bad Case 后，用新的未见样本补足 Holdout；记录 `retired_from_holdout` / `replaced_by`，递增 `label_version`。
- 开发期间不对开发者展示 Holdout 的逐题答案与 Trace。

## 8. Release Gate Contract v0.1

### 8.1 第一层：硬门禁

任一失败 → 退出码 1，不允许静默豁免。

| ID | 判定 |
| --- | --- |
| `security_leak` | 引用 `forbidden_sources`、回答含 `forbidden_values`、命中敏感模式、跨用户来源 |
| `cross_entity` | 回答/事实的 entity key 与请求 filters 不一致；引用单元属于另一实体 |
| `stale_bypass` | `include_future=false` 时引用 `effective_to < as_of` 或 `effective_from > as_of` 的来源 |
| `conflict_not_rejected` | case 存在多个有效值，结果不是 `conflict` / `clarification` |
| `exact_value_contract` | exact 类期望值未在回答中命中（归一化后） |
| `pagination_contract` | `total/returned/has_more/next_page` 不符合契约 |
| `citation_required` | answer 无引用，或引用不在本轮 evidence 中 |
| `trace_integrity` | 缺 Trace / 必需 Span / 版本绑定，或 dataset/index/pipeline 不一致 |

### 8.2 第二层：质量门禁

按 stratum 与总体分别报告；不设综合分。指标：

- 检索：`Recall@10`、`MRR@10`、`nDCG@10`、`hard_filter_violation_rate`、`empty_recall_rate`。
- 答案：`value_hit`、`source_hit`、`kind_correct`、`citation_precision`、`citation_recall`。
- 拒答：`refusal_recall`、`false_refusal_rate`、`refusal_precision`，三者分开。
- 运行：P50/P95 延迟、输入/输出 Token、单题成本、重试次数、degraded 次数。

每个指标有：

```text
absolute_min / absolute_max
max_regression_pp（相对 release baseline）
min_sample
direction（higher_is_better / lower_is_better）
```

首次建立 baseline 时只能用绝对阈值；同版本后续发布才做回退检测。样本不足 → `unknown`（退出码 3），不视为通过。

### 8.3 Baseline 身份与建立

- `baseline_id = sha256(dataset_version + pipeline_version + mode + scope + gate_version + corpus_sha256)`。
- 发布放行只接受同 `pipeline_version` 的 `release_baseline`。
- 跨版本比较必须 `--compare-with <baseline_id>`，报告标 `comparison=explicit_cross_version`，并校验 dataset/corpus/gate 口径可比；该结果只用于分析，不用于放行。
- 新 `pipeline_version` 第一次发布：
  1. 完整评测（Replay + Local；真实检索在 P1 用 `scope=retrieval_only`）；
  2. 所有硬门禁通过；
  3. 绝对质量阈值通过；
  4. 显式审批：`baseline approve --run ... --approver ... --reason ...`，写 `approval.json`，包含 `run_id`、`gate_result_sha256`、`dataset_version`、`pipeline_version`、`corpus_sha256`；
  5. 之后同版本发布才与它做回退检测。
- 禁止复制/改名旧 Baseline 冒充新版本；没有 `baseline copy` 命令。
- 硬门禁不可豁免；质量门禁 waiver 必须记录 `reason` / `approver`，并在报告中显示。

### 8.4 退出码

| 退出码 | 含义 |
| --- | --- |
| 0 | 通过 |
| 1 | 硬门禁失败 |
| 2 | 质量回退 |
| 3 | 数据 / 配置 / gold 解析失败 / 样本不足 |
| 4 | live 未授权或跳过 |

### 8.5 报告

每次运行输出：

```text
run_manifest.json
cases.jsonl
summary.json
diff.json
report.md
report.html        # P0 非门禁展示层
```

`report.html` 从 `summary.json` / `diff.json` 生成，单文件、内联 CSS、无 JS、无服务；P0 七条验收不依赖它。

## 9. P0 运行模式

| 模式 | P0 作用 | 是否纳入验收 |
| --- | --- | --- |
| `replay` | 读取上一轮 Local run 的冻结产物（`cases.jsonl` + Trace 引用），验证确定性评分、门禁、报告；不建索引、不调 provider | 是 |
| `local` | 真实本地索引/检索，Mock 外部 Provider，验证核心逻辑与埋点；评测器直接调用 `RagIndex.ask`，`QaEngine` 产品同步与 legacy 路径由现有 integration tests 覆盖 | 是 |
| `live` | 真实 Provider 调用 | 禁止 |

- Replay 通过 **不等于** 当前代码没有回归；必须同时跑现有 pytest 与 Local 集成测试。
- P0 不要求真实 Embedding 效果评测；P1 才用 `live + scope=retrieval_only`。

## 10. 兼容性契约

- 不修改现有 API 的请求参数与响应 Body。
- 允许新增非破坏性响应头 `X-Trace-ID`。
- 不修改业务数据库 `mktkb.sqlite3` schema，也不修改 `rag-index.sqlite3` schema。
- 允许新增独立 `var/observability/qa-traces.sqlite3` 及其专属表结构。
- `report.html` 只是文件输出，不是 API。

## 11. P0 范围与验收

P0 只包含：

1. Trace 采集与 SQLite 存储；
2. 确定性评测器（Replay + Local）；
3. 双层发布门禁；
4. Baseline 与 Diff；
5. JSON / Markdown 报告；
6. 非门禁单文件静态 HTML；
7. 完整集成验收。

P0 七条验收：

1. 现有业务行为不变；
2. 每个执行尝试可用 `trace_id` 关联完整阶段；
3. B0 40 与 Bad Case 13 可独立回归；
4. 结果绑定 `dataset_version` / `index_revision` / `pipeline_version`；
5. 可生成 baseline、diff、JSON 报告；
6. 硬门禁失败返回非零退出码；
7. 零真实模型调用、零 Token 费用。

P0 不增加 Ragas、Langfuse、Web Dashboard、实时告警。

## 12. 文件结构

```text
backend/src/mktkb/observability/
  __init__.py
  contracts.py          # 枚举、Schema 版本、必需 Span 规则、TraceRecord/SpanRecord
  versioning.py         # pipeline_version、config_hash、HMAC 哈希
  store.py              # SQLite TraceRepository、导出、清理
  tracer.py             # start_trace / current_trace / TraceContext

backend/src/mktkb/evaluation/
  __init__.py
  dataset.py            # CaseSpec、JSONL 加载/校验、dataset_version
  gold.py               # 稳定引用解析、GoldUnresolved
  scorers.py            # 值/来源/kind/分页/拒答/检索指标
  runner.py             # replay/local 运行、RunManifest
  corpus.py             # 薄适配 tools/rag_experiment.py 的语料加载/索引构建
  gate.py               # 双层门禁、退出码、豁免
  baseline.py           # baseline 身份、审批、加载
  report.py             # diff、summary、Markdown/HTML
  cli.py                # 子命令

tools/
  rag_eval.py           # CLI 薄包装
  build_eval_dataset.py # B0/13 -> JSONL，一次性转换

fixtures/evaluation/
  b0.jsonl
  badcase.jsonl
  holdout.jsonl         # P1

docs/evaluation/
  trace_schema_v0_1.md
  eval_data_v0_1.md
  gate_v0_1.json

var/observability/qa-traces.sqlite3   # 运行时，不入库
var/eval/runs/<run_id>/               # 运行时产物
docs/reports/OBS-EVAL/P0/             # 验收证据与锚（入库；docs/evidence 仅本地）

backend/tests/observability/
  conftest.py
  test_contracts.py
  test_versioning.py
  test_store.py
  test_tracer.py
  test_middleware.py

backend/tests/evaluation/
  conftest.py
  golden/chat_response.json
  test_dataset.py
  test_gold.py
  test_scorers.py
  test_runner.py
  test_gate.py
  test_baseline.py
  test_report.py
  test_p0_acceptance.py
```

## 13. 风险与处理

| 风险 | 处理 |
| --- | --- |
| Trace 写入影响问答延迟 | best-effort + 单事务批量写；失败不阻塞；P0 本地验证 P95 增量 |
| Trace 内容泄漏真实业务数据 | 默认 `hash`；真实问题 HMAC；`full` 仅合成语料；保留期与 purge |
| 必需 Span 过严导致误判 | 按 `path + outcome` 基础集合 + 属性条件集合；未执行不要求 |
| Baseline 被旧版本污染 | `baseline_id` 绑定版本；无 copy 命令；新版本必须审批建立 |
| Replay 通过掩盖回归 | P0 同时要求 Local 与现有 pytest |
| 质量门禁被“多拒答”刷分 | 拒答三指标分开；`false_refusal_rate` 纳入门槛 |
| Gold 解析不稳定 | 只绑稳定业务单元；0/多匹配 fail closed |
| Holdout 过拟合 | 只看聚合；失败样本转 Bad Case 后补新样本 |

## 14. 后续阶段

- P1：Holdout 30、真实 embedding + rerank 的 retrieval-only 评测、检索金标、监控 API。
- P2：受预算约束的 live 端到端评测、Ragas 软指标、可选 Langfuse 导出。
- P3：Web 看板、历史趋势、告警。

P0 的结论只证明离线回归与确定性门禁工作正常，不证明端到端 RAG 的真实回答质量已经提升；真实效果在 P1/P2 用固定数据集验证。

# T301 Trace 两态抽查记录（工作包 B）

## 1. 抽查方法与脱敏

- 直接读取隔离 Trace 库 `evidence/data/qa-traces.sqlite3`（脚本 `scripts/t301_trace_probe.py`，结果 `evidence/trace/trace-probe.json`）。
- 实测 Trace 总数：12（启用态普通执行 11 条 + 重放 1 条；关闭态 0 条）。
- 脱敏：只记录 Span 名、时长（ms）、状态与关联键；不摘录 Trace 原始属性、密钥、原始请求头与原文问题。

## 2. 请求 ↔ Trace 关联方式

- 产品请求 ID：`traces.request_id = ConversationRequest.id`；12 条 Trace 关联键全部在业务库请求行命中。
- HTTP 请求 ID：`traces.http_request_id` 对应响应头 `X-Request-ID`；12 条记录了 HTTP 请求 ID。
- 重放为新 HTTP 请求，故 http_request_id 不同，但复用同一产品请求 ID。

## 3. 执行路径与 Span 清单（实测记录）

### 3.1 legacy_with_rag_candidates 路径（legacy 候选 + RAG 候选混合）

| Span 名 | 说明 |
| --- | --- |
| `answer_validate` | 实测采集到；时长字段 `duration_ms`、状态 `status` |
| `commit` | 实测采集到；时长字段 `duration_ms`、状态 `status` |
| `embedding_query` | 实测采集到；时长字段 `duration_ms`、状态 `status` |
| `entity_conflict_check` | 实测采集到；时长字段 `duration_ms`、状态 `status` |
| `exact_recall` | 实测采集到；时长字段 `duration_ms`、状态 `status` |
| `fuse` | 实测采集到；时长字段 `duration_ms`、状态 `status` |
| `hard_filter` | 实测采集到；时长字段 `duration_ms`、状态 `status` |
| `intent_parse` | 实测采集到；时长字段 `duration_ms`、状态 `status` |
| `lexical_recall` | 实测采集到；时长字段 `duration_ms`、状态 `status` |
| `model_answer` | 实测采集到；时长字段 `duration_ms`、状态 `status` |
| `recall` | 实测采集到；时长字段 `duration_ms`、状态 `status` |
| `rerank` | 实测采集到；时长字段 `duration_ms`、状态 `status` |
| `retrieve` | 实测采集到；时长字段 `duration_ms`、状态 `status` |
| `vector_recall` | 实测采集到；时长字段 `duration_ms`、状态 `status` |

代表性 Trace：request `a78d316d-9573-41fc-93b5-6be0ac25cc23`，结果 `answer`，状态 `ok`。

| Span | 时长(ms) | 状态 |
| --- | --- | --- |
| `intent_parse` | 3 | ok |
| `recall` | 11 | ok |
| `exact_recall` | 3 | ok |
| `lexical_recall` | 0 | ok |
| `vector_recall` | 7 | ok |
| `embedding_query` | 0 | ok |
| `fuse` | 1 | ok |
| `hard_filter` | 0 | ok |
| `rerank` | 1 | ok |
| `recall` | 11 | ok |
| `lexical_recall` | 4 | ok |
| `vector_recall` | 7 | ok |
| `embedding_query` | 0 | ok |
| `fuse` | 5 | ok |
| `hard_filter` | 0 | ok |
| `rerank` | 5 | ok |
| `retrieve` | 34 | ok |
| `entity_conflict_check` | 8 | ok |
| `model_answer` | 0 | ok |
| `answer_validate` | 3 | ok |
| `commit` | 11 | ok |

### 3.2 RAG 路径（rag）

| Span 名 | 说明 |
| --- | --- |
| `answer` | 实测采集到；时长字段 `duration_ms`、状态 `status` |
| `commit` | 实测采集到；时长字段 `duration_ms`、状态 `status` |
| `embedding_query` | 实测采集到；时长字段 `duration_ms`、状态 `status` |
| `exact_recall` | 实测采集到；时长字段 `duration_ms`、状态 `status` |
| `fact_validate` | 实测采集到；时长字段 `duration_ms`、状态 `status` |
| `fuse` | 实测采集到；时长字段 `duration_ms`、状态 `status` |
| `hard_filter` | 实测采集到；时长字段 `duration_ms`、状态 `status` |
| `lexical_recall` | 实测采集到；时长字段 `duration_ms`、状态 `status` |
| `parse` | 实测采集到；时长字段 `duration_ms`、状态 `status` |
| `recall` | 实测采集到；时长字段 `duration_ms`、状态 `status` |
| `rerank` | 实测采集到；时长字段 `duration_ms`、状态 `status` |
| `vector_recall` | 实测采集到；时长字段 `duration_ms`、状态 `status` |

代表性 Trace：request `2a475be9-61a4-4305-9ec7-8b6022b0ad1a`，结果 `answer`，状态 `ok`。

| Span | 时长(ms) | 状态 |
| --- | --- | --- |
| `parse` | 1 | ok |
| `recall` | 8 | ok |
| `exact_recall` | 2 | ok |
| `lexical_recall` | 3 | ok |
| `vector_recall` | 3 | ok |
| `embedding_query` | 0 | ok |
| `fuse` | 1 | ok |
| `hard_filter` | 0 | ok |
| `rerank` | 1 | ok |
| `answer` | 11 | ok |
| `fact_validate` | 9 | ok |
| `commit` | 1 | ok |

### 3.3 legacy 路径（legacy）

| Span 名 | 说明 |
| --- | --- |
| `answer_validate` | 实测采集到；时长字段 `duration_ms`、状态 `status` |
| `commit` | 实测采集到；时长字段 `duration_ms`、状态 `status` |
| `intent_parse` | 实测采集到；时长字段 `duration_ms`、状态 `status` |
| `model_answer` | 实测采集到；时长字段 `duration_ms`、状态 `status` |
| `model_failure` | 实测采集到；时长字段 `duration_ms`、状态 `status` |
| `retrieve` | 实测采集到；时长字段 `duration_ms`、状态 `status` |

代表性 Trace：request `59943519-a6b8-4519-b058-0cc6a9f3463d`，结果 `answer`，状态 `ok`。

| Span | 时长(ms) | 状态 |
| --- | --- | --- |
| `intent_parse` | 1 | ok |
| `retrieve` | 9 | ok |
| `model_answer` | 0 | ok |
| `answer_validate` | 0 | ok |
| `commit` | 5 | ok |

## 4. 重放标记

| 项 | 实测 |
| --- | --- |
| 产品请求 ID | `cccba3ae9d2e459aa3b992c6a512192f` |
| 重放 Trace ID | `48ecd3cdd47a4869a1b75fa60931fd11` |
| 原始 Trace ID | `01c0a79e64b54e85a5a3e3ab1fe291a4` |
| 重放 HTTP 请求 ID | `acf9fae1-963d-4ad3-8548-99658dfa30e2` |
| 重放状态 | status=`replayed`，replayed=1，Span 数=0 |

- 关联要点：重放 Trace：replayed=1、status=replayed、Span 为空；复用同一产品请求 ID；previous_trace_id 在本重放链路中未回填（实测为 null）。
- `previous_trace_id` 实测为 null：当前重放链路未回填上一条 Trace 关联键；重放与原始 Trace 的串联依赖同一产品请求 ID。

## 5. Trace 关闭态

| 样本 | 业务请求存在 | Trace 行 | 响应头 X-Trace-ID | 状态 |
| --- | --- | --- | --- | --- |
| S15 | 是 | 无 | 无 | disabled |

## 6. 旧版引用可展示字段

- 样本：S11；版本号 `1`。
- 结果 JSON 来源条目字段键：`document_name`, `locator`, `published_at`, `source_id`, `status`, `version_number`。
- 字段核验：document_name 存在=True，locator 存在=True，published_at 存在=True。
- 旧版引用结果 JSON 来源条目仍携带 document_name/version_number/status/locator/published_at；版本号 1 在换版后历史消息中保持可展示。

## 7. 限制与备注

- 第三执行路径 `legacy_with_rag_candidates` 已在样本中触发并单独记录 Span 清单。
- 关闭态应用未生成任何 Trace；未观测到「部分覆盖 / 读取失败」状态，本次样本不涉及。
- Span 时长为隔离离线替身环境下的实测值，不代表线上性能；`model_failure` 仅在 service_error 分支出现。

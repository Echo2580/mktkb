# T113 证据 02：API 契约、OpenAPI 与只读边界

模型：`wb / cn:deepseek-v4.1-flash / reasoning_effort=max`

## A. 端点契约（全部 `GET`，全部 `Depends(require_role("admin"))`）

| 路径（`/api/v1` 下） | 成功响应 | 错误/降级 |
| --- | --- | --- |
| `/observability/traces/{trace_id}` | `trace` 摘要 + `spans` 摘要（`span_count`、`attribute_keys`、`attribute_count`） | 404 `TRACE_NOT_FOUND`；422 `INVALID_TRACE_ID`；trace 关闭 200 `trace_disabled`；仓储不可用 200 `trace_unavailable` |
| `/observability/requests/{request_id}/traces` | `request_id` + 全部尝试 `traces[]`（`attempt` / `replayed` / `previous_trace_id`） | 422 `INVALID_REQUEST_ID`；未知 request 200 空列表；trace 关闭 200 `trace_disabled` |
| `/observability/metrics?window=24h` | `window` / `since` / `until` / `total_traces` / `groups[]` / 无效计数 / `degraded_reason` | 422 `INVALID_WINDOW`；trace 关闭 200 空聚合 `trace_disabled`；`created_at`/JSON 解析失败 200 `partial_data` |
| `/observability/runs/{run_id}` | `manifest` / `summary` / `gate` 白名单聚合 + `holdout_detected` / `details_withheld` | 404 `RUN_NOT_FOUND`；422 `INVALID_RUN_ID`；坏 JSON 200 `manifest_invalid` / `summary_invalid` / `gate_invalid`；trace 关闭附 `trace_disabled` |

错误信封沿用全局 `errors.py`：`{"error":{"code","message","retryable","details"},"request_id"}`；
不回显提交值、路径、SQL 或异常消息。

## B. 响应白名单（无原文）

- Trace：`trace_id` / `request_id` / `http_request_id` / `attempt` / `replayed` /
  `previous_trace_id` / `mode` / `scope` / `path` / `content_mode` / `query_kind` /
  `outcome_kind` / `reason` / `answer_source` / `status` / `error_code` / `latency_ms` /
  `created_at` / `question_hash` / `question_chars` / `hash_algo` / `hmac_key_id` /
  `user_id_hash` / `conversation_id_hash` / `go_decision` / `index_revision` /
  `manifest_sha256` / `pipeline_version` / `config_hash` / `span_count`。
- Span：`span_id` / `parent_span_id` / `name` / `started_at` / `duration_ms` /
  `status` / `error_code` / `attribute_count` / `attribute_keys`（**不返回**
  `attributes_json` 或任何属性值）。
- Metrics 分组：`path` / `outcome` / `count` / `latency_samples` /
  `latency_ms_p50` / `latency_ms_p95` / `tokens_input` / `tokens_output` /
  `tokens_total` / `cost_cny` / `degraded_count` / `error_count`。
- Run manifest：只保留身份哈希/版本/计数；**不返回** `dataset_path` / `corpus_dir` /
  `replay_from` / `source_run_id` / `trace_store` 等路径或内部定位字段。
- Run summary：`status_counts`、压平后的数值 `metrics`、`holdout` 哈希/分层计数；
  **不返回** `metrics_scope`（含逐 case id）、`declarations`、`live` 明细。
- Gate：`exit_code` / `gate_status` / `hard_failures`（门禁 ID）/ 计数 /
  `quality_status`；**不返回** `failures` / `unknowns` / `not_applicable` 的
  `evidence` 明细。
- 测试断言响应 JSON 不含 `question` / `answer` / `text` / `context` / `cases` /
  `case_id` / `*_json` / `evidence` / 路径字段，也不含 fixture 中的秘密文本。

## C. OpenAPI 导出证据

导出命令（`initialize=False`，显式 `database_url`，不写 data_dir）：

```text
python -B -c "create_app(settings, initialize=False); json.dump(app.openapi(), backend/.pytest-tmp/T113/openapi.json)"
data_dir_exists_after_openapi=False
```

产物：`backend/.pytest-tmp/T113/openapi.json`（gitignored）
SHA-256：`812f0f8d7ad79eff4e35233036c7111ce17d0e44eb520907805ea899766bcd61`

```text
/api/v1/observability/metrics                          methods=['get']  401/403 documented
/api/v1/observability/requests/{request_id}/traces      methods=['get']  401/403 documented
/api/v1/observability/runs/{run_id}                     methods=['get']  401/403 documented
/api/v1/observability/traces/{trace_id}                 methods=['get']  401/403 documented
```

四条路径均只有 `get`；无 `post` / `put` / `patch` / `delete`。`responses` 含 401/403
说明（管理员依赖的实际拒绝由 `require_role("admin")` 执行）。

## D. 只读证明

- 测试在调用 4 个端点前后对 trace SQLite 主库与 run 的 `run_manifest.json` /
  `summary.json` / `gate.json` 计算 SHA-256 与 `st_mtime_ns`，前后完全一致。
- 端点只调用 `TraceRepository.get` / `list_by_request` / `list_window`（均 SELECT）
  与 `Path.read_text`；没有 `write` / `INSERT` / `UPDATE` / `DELETE` / `purge` /
  `export_jsonl`。
- OpenAPI 断言仅 GET；`create_app(initialize=False)` 的 OpenAPI 检查不创建 data_dir。

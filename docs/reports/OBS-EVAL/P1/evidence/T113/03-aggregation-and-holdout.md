# T113 证据 03：聚合正确性、降级与 Holdout 隔离

模型：`wb / cn:deepseek-v4.1-flash / reasoning_effort=max`

## A. metrics 造数与手算（`backend/tests/observability/test_routes.py`）

同一窗口内写入 7 条可解析 `created_at` 的 trace，另写 1 条 `created_at` 不可解析、
1 条 `token_usage_json` 不可解析：

| path / outcome | count | latency_ms 样本 | tokens in/out/total | cost_cny | degraded | error |
| --- | --- | --- | --- | --- | --- | --- |
| `rag/answer` | 4 | 10 / 20 / 30 / 40 | 100×4 / 20×4 / 120×4 | 0.1+0.2+0.3+0.4 | 2（20/40 两条） | 0 |
| `legacy/not_found` | 1 | 5 | 0 / 0 / 0 | 0 | 0 | 0 |
| `rag/error` | 1 | 50 | 1 / 2 / 3 | 0.5 | 0 | 1 |
| `rag/no_answer` | 1 | 无 | 0 / 0 / 0（JSON 不可解析） | 0 | 0 | 0 |

断言值：

```text
rag/answer: count=4 latency_samples=4 p50=20 p95=40
            tokens_input=400 tokens_output=80 tokens_total=480 cost=1.0
            degraded_count=2 error_count=0
legacy/not_found: count=1 p50=5 p95=5 tokens_total=0 cost=0.0
rag/error: count=1 error_count=1 tokens_total=3 cost=0.5
total_traces=7
invalid_created_at_count=1
invalid_payload_count=1
degraded_reason="partial_data"
```

百分位口径：最近秩（nearest-rank），`rank=ceil(p/100*n)` 取排序后第 `rank` 个；
P50/P95 在 `[10,20,30,40]` 上分别为 `20` / `40`。窗口过滤另测：2 小时前的 trace 在
`window=1h` 不计、在 `window=24h` 计入；非法 `window`（`abc` / `0h` / `24` /
`1.5h` / `-1h` / `24d` / `1H` / 带空格）均为 422 `INVALID_WINDOW`。

Token 口径：`input` / `prompt_tokens` / `input_tokens` 取首个非负整数；输出同理；
`total_tokens` 缺失时用 `input+output`。Cost 口径：`cny` / `cost_cny` 取首个非负有限数。
`degraded_json` 非空（或不可解析，fail-safe）计 1 条 degraded；`token_usage_json` /
`cost_json` / `degraded_json` 不可解析不 500，计入 `invalid_payload_count` 并令
`degraded_reason="partial_data"`。

## B. 降级与错误矩阵

| 场景 | 结果 |
| --- | --- |
| `app.state.trace_repo is None`（默认 trace 关闭） | 4 端点 200；trace/requests/metrics 空聚合 + `degraded_reason="trace_disabled"`；runs 仍返回 manifest/summary/gate 聚合并附该 reason |
| 仓储已 `close()` | trace / metrics 200 + `degraded_reason="trace_unavailable"`，不 500 |
| run manifest 缺失 | 404 `RUN_NOT_FOUND` |
| run manifest 坏 JSON | 200，`manifest=None`，`degraded_reason="manifest_invalid"` |
| 未知 trace_id | 404 `TRACE_NOT_FOUND` |
| 未知 request_id | 200 `traces=[]`（请求 ID 无独立存在性语义） |
| 非法 trace/request/run id（`..`、`.hidden`、`bad..id`、超长等） | 4xx；可路由到端点的为 422 `INVALID_*`；客户端规范化 `..` 的请求为 404，不得 200 |
| employee 会话 | 4 端点 403 `ROLE_REQUIRED` |
| 未登录 | 401 `AUTH_REQUIRED` |

## C. Holdout 隔离

构造 holdout run（manifest `suite="holdout"`、`holdout_details=true`），summary 带
`metrics_scope.excluded_error_case_ids` / `declarations`，gate 的 failures 带
`evidence`，并写入含题干/答案秘密文本的 `cases.jsonl`。`GET /runs/{run_id}` 断言：

```text
holdout_detected=true
details_withheld=true
summary.holdout.strata={"core":12,"edge":18}
summary.holdout.details_written=true
响应文本不含 "HOLDOUT-CASE-001" / 题干 / 答案秘密文本
响应 JSON 无 cases / case_id / metrics_scope / declarations / evidence 字段
```

holdout 聚合 run（`holdout_details=false`、无 `cases.jsonl`）断言
`holdout_detected=true`、`details_withheld=false`、`summary.holdout.aggregate_only=true`；
两种形态都只返回聚合，不返回逐题。Trace 端点本身不返回 `case_id` / `run_id` /
`dataset_version`，不能间接取得 holdout 明细。

## D. 无原文断言

`test_responses_never_contain_question_answer_or_internal_json` 对 4 个端点响应递归
检查键名黑名单（`question` / `answer` / `text` / `context` / `cases` / `case_id` /
`attributes_json` / `*_json` / `evidence` / `metrics_scope` / `declarations` /
`dataset_path` / `corpus_dir` / `database_url`），并断言 fixture 秘密文本不出现在
响应体中；span 仅返回属性键名 `["fact_count","secret_note"]` 与个数，不返回值。

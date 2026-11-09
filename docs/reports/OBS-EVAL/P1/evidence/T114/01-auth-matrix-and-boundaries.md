# T114 证据 01：权限矩阵、负例与边界

模型：`wb / cn:deepseek-v4.1-flash / reasoning_effort=max`

本包测试：`backend/tests/observability/test_routes_security.py`（**新增**，62 条，不改
T113 `test_routes.py`）。命令：`pytest backend/tests/observability/test_routes_security.py -q`。

## A. 权限矩阵（4 端点 × 3 身份）

| 身份 | 4 端点结果 | 断言依据 |
| --- | --- | --- |
| 未登录 | `401 AUTH_REQUIRED` ×4 | `test_unauthenticated_gets_401_before_validation`（`:395`） |
| employee | `403 ROLE_REQUIRED` ×4，`details.required_role=admin` | `test_employee_gets_403_before_validation`（`:412`） |
| admin | `200` ×4（trace 开启；未命中资源按负例处理） | `test_admin_gets_200_on_all_four`（`:428`） |

**顺序 = 鉴权 → 参数校验 → 资源读取**：未登录 / employee 使用非法 `window` 与不存在的
`trace_id` / `run_id` 请求，仍只返回 401 / 403，不返回 404 / 422
（`test_auth_order_is_auth_then_validation_then_resource`，`:450`）。

## B. 错误信封白名单

401/403/404/422 均严格为
`{"error": {"code", "message", "retryable", "details"}, "request_id"}`，无额外键
（`test_error_responses_use_whitelisted_envelope`，`:467`；403 另由 `:412` 断言）。
秘密文本 `SECRET_TEXT` 不出现在任何错误 body；错误 message 不回显提交值 / 路径。

## C. 资源与参数负例（admin）

| 场景 | 结果 | 测试 |
| --- | --- | --- |
| 不存在 trace | 404 `TRACE_NOT_FOUND` | `:486` |
| 不存在 run（含空目录、无 manifest） | 404 `RUN_NOT_FOUND` | `:486` |
| 未知 request | 200 `{traces: [], degraded_reason: null}` | `:501` |
| 非法 `window`：`0h/-1h/abc/24/1.5h/24D/1H/ 24h/1000000h` | 422 `INVALID_WINDOW` | `:515` |
| 非法 `trace_id/run_id/request_id`（`.hidden`/`bad..id`/`bad id`/`bad.`/129 字符） | 422 对应 `INVALID_*` | `:541` |
| URL 编码穿越（`%2e%2e`、`..%5C`、`bad%20id`） | 422 对应 `INVALID_*` | `:570` |
| 编码斜杠（`..%2F`、`bad%2Fid`） | 路由不匹配 404 `NOT_FOUND` | `:570` |
| runs 根外 manifest | 4xx 且秘密文本不出现在响应 | `:577` |

## D. 时间窗边界

- 合法：`1h`、`24h`、`30m`、`999999h` → 200；`since < until`、时区为 UTC
  （`:599`）；默认无参数 `window=24h`（`:611`）。
- 非法清单见 C 表；正则 `^([1-9][0-9]{0,5})([hm])$` 与实现 `routes.py:55` 一致。
- `999999h` 在 fixture 数据上返回 200 且计数正确（`:617`）；只证明不 500，不声称
  性能或全表保护上限。

## E. 分页 NOT-APPLICABLE

四端点均无 `limit` / `offset`，响应无分页结构；OpenAPI 参数集合断言
`metrics` 仅 `window`（`test_metrics_does_not_expose_pagination`，`:626`）。
文档 `接口与数据契约.md:210` 明确写为 NOT-APPLICABLE，不虚构分页行为。

## F. 降级 / 不泄露 / Holdout

- trace 关闭：4 端点 200；traces/requests/metrics 空聚合 + `trace_disabled`，
  runs 仍返回聚合并附该原因（`:646`）。
- 成功响应字段逐层对照 Pydantic 白名单：`TraceDetailResponse` / `TraceSummary` /
  `SpanSummary` / `RequestTracesResponse` / `MetricsResponse` / `MetricGroup` /
  `RunResponse` / `RunManifestSummary` / `RunSummaryBlock` / `HoldoutSummary` /
  `GateSummary`；递归键名黑名单 + `SECRET_TEXT` 文本断言（`:680`）。
- span 只返回 `attribute_keys` / `attribute_count`，不返回值（`:680`）。
- holdout run：`holdout_detected=true`、`details_withheld=true`，仅 `strata` 聚合；
  即使 `cases.jsonl` 含秘密题干/答案也不返回（`:760`）。
- 401/403/404/422 在含秘密数据的同一 fixture 下再次断言无原文（`:680` 尾段）。

## G. OpenAPI

`test_openapi_four_paths_only_get_and_auth_responses`（`:808`）：4 路径、仅 `get`、
每条 `401/403/422` 响应声明且 401/403 有 description；应用使用 Cookie 会话，
当前未声明 `securitySchemes`，以 401/403 作为机读权限声明（T113 验收 LOW-1 口径）。
`test_openapi_snapshot_matches_live_schema`（`:834`）：已提交快照与实时 schema 的
4 路径、相关 components、`openapi` 版本、`info` 完全一致。
快照：`openapi-observability.json`（4 paths / 13 schemas / 37,106 bytes，SHA-256
`51f7edfc8fc071cd55981518fa5233ede823a352bd61f3e47d79000ad6db5979`）。

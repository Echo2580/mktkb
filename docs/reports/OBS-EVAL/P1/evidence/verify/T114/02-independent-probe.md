# T114 验收证据 02：独立探针 / 文档 / OpenAPI

模型：`wb / cn:deepseek-v4.1-flash / reasoning_effort=max`

探针源码（gitignored）：`.claude/handoffs/_scratch/T114v/probe.py`；
`doc_check.py`；`openapi_check.py`。全部 `Settings(_env_file=None)` + `tmp` 目录，
零真实模型 / embedding / rerank / OCR 调用；未读 `.env`。

## A. 权限顺序 / 错误信封（独立探针）

```powershell
.\.venv\Scripts\python.exe -B .claude\handoffs\_scratch\T114v\probe.py
```

结果：**87 checks, 0 failed**（输出 `probe-out.json`）。

- 4 端点 × 未登录：`401 AUTH_REQUIRED`，`error.details is None`；即使 `window=not-a-window`、
  `trace_id/run_id` 不存在或为 `bad..id` 仍为 401（`probe.py` 段 1/1b）。
- 4 端点 × employee：`403 ROLE_REQUIRED`，`error.details == {"required_role":"admin"}`；
  同样不被参数校验抢占（段 2）。
- 错误信封严格 `{error:{code,message,retryable,details}, request_id}`；401/403/404/422
  均无额外键；422 `message` 不回显提交的 window/id，也不含 `C:\`、`/` 或临时目录路径。
- 404：不存在 trace/run 均 `TRACE_NOT_FOUND`/`RUN_NOT_FOUND`；未知 request 为 200
  `{request_id, traces: [], degraded_reason: null}`。

## B. 时间窗 / 穿越 / 降级

- 非法 window（`0h`/`-1h`/`abc`/`24`/`1.5h`/`24D`/`1H`/` 24h`/`1000000h`）→ 422
  `INVALID_WINDOW`；合法 `1h`/`24h`/`30m`/`999999h` → 200。
- `999999h` 返回 200 且 `since < until`（探针；不声称性能/全表保护）。
- 编码穿越：`%2e%2e`、`..%5Cescape`、`bad%20id` → 422 `INVALID_*`；`..%2F`/`bad%2Fid`
  路由不匹配 → 404 `NOT_FOUND`，admin 与匿名均不 200。匿名编码斜杠 404 是路由层
  404（未匹配路由），不泄露资源存在性，文档 `接口与数据契约.md:199` 已写明。
- trace 关闭：四端点 200，traces/requests/metrics 空聚合，runs 正常返回聚合并带
  `degraded_reason="trace_disabled"`。
- 成功响应（trace/spans/requests/metrics/runs）逐层键白名单；秘密文本埋在
  `case_id`/`*_json`/summary `metrics_scope`/`declarations`/gate `failures.evidence`/
  `attributes_json`/holdout `cases.jsonl` 后，四响应均不含秘密文本或禁止键；
  span 只返回 `attribute_keys`/`attribute_count`。

## C. 文档 §8 与实现对照

```powershell
.\.venv\Scripts\python.exe -B .claude\handoffs\_scratch\T114v\doc_check.py
```

结果：**40 checks, 0 failed**。

- `TraceSummary` / `SpanSummary` / `MetricsResponse` / `MetricGroup` /
  `RunManifestSummary` / `RunSummaryBlock` / `GateSummary` / `HoldoutSummary`
  的文档字段集合与 `routes.py` 的 Pydantic `model_fields` 逐一相等。
- 端点表 4 条路径、方法均 `GET`；4 个错误码（`AUTH_REQUIRED`/`ROLE_REQUIRED`/
  `INVALID_WINDOW`/`INVALID_*`/`TRACE_NOT_FOUND`/`RUN_NOT_FOUND`）均在 §8 出现；
  `_WINDOW.pattern` 字面量与文档一致；13 个合法/非法 window 样例的 regex 结果与文档一致。
- 文档写明只读、`trace_disabled`/`trace_unavailable`、不泄露、未知 request 200 空列表、
  四端点无分页参数且 NOT-APPLICABLE（`接口与数据契约.md:180-228`）。

## D. OpenAPI 独立核对

```powershell
.\.venv\Scripts\python.exe -B .claude\handoffs\_scratch\T114v\openapi_check.py
```

结果（退出 0）：

```text
snapshot_sha256 = 51f7edfc8fc071cd55981518fa5233ede823a352bd61f3e47d79000ad6db5979
snapshot_bytes  = 37106
paths           = 4（traces/requests/metrics/runs）
methods         = 全部 ["get"]
auth responses  = 每条均含 401/403/422
components      = 13 schemas，与实时 openapi() 的引用闭包完全相等
parameters      = metrics 仅 window；其余仅 path 参数；无 limit/offset
```

快照 `paths`/`components`/`openapi`/`info` 与 `create_app(settings, initialize=False).openapi()`
的观测子集相等；快照仅 4 条路径、每条仅 GET。

## E. LOW 观察（非阻断）

手工构造“manifest `holdout_details=false` + summary `holdout.details_written=true` +
无 `cases.jsonl`”的**不一致** run 目录时，`details_withheld=false`，而文档
`接口与数据契约.md:222` 的“存在逐题明细或声明时 details_withheld=true”字面更宽。
真实 runner 在 `runner.py:2806-2807` 令 `details_written = manifest.holdout_details`，
二者不会分歧；且该响应仍只有聚合、不读取 `cases.jsonl`，无原文泄露。故记为 LOW
残余（防御性处理），不构成权限/不泄露失败。

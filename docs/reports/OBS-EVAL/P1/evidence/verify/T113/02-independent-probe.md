# T113 独立验收证据 02：功能、权限、只读、隐私、Holdout

模型：`wb / cn:deepseek-v4.1-flash / reasoning_effort=max`（验收方，非交付物）

环境：Windows；仓库根 `D:\GPT项目\市场部AI知识库`；分支 `p1/fix-retrieval`；
`HEAD=22f098e`（其后仅 PM 簿记）；交付 `9edc003`（父 `10bb42b`）。全部探针用
`Settings(_env_file=None)` 显式配置，未读 `.env`；零真实模型 / embedding / rerank / OCR。
探针脚本在 `_scratch/probe_t113.py`、`_scratch/readonly_probe.py`；原始结果
`_scratch/probe-root/probe_result.json`。

## A. 权限矩阵（admin / employee / anonymous × 4 端点）

命令（cwd=仓库根）：

```text
$env:T113_PROBE_ROOT=(Resolve-Path _scratch\probe-root).Path
.\.venv\Scripts\python.exe -B _scratch\probe_t113.py
```

| 端点 | anonymous | employee | admin |
| --- | ---: | ---: | ---: |
| `GET /traces/{trace_id}` | 401 `AUTH_REQUIRED` | 403 `ROLE_REQUIRED` | 200 |
| `GET /requests/{request_id}/traces` | 401 | 403 | 200 |
| `GET /metrics?window=24h` | 401 | 403 | 200 |
| `GET /runs/{run_id}` | 401 | 403 | 200 |

admin 200 的四份响应结构：trace 摘要 + spans；request 的 attempts（含 `attempt` /
`replayed` / `previous_trace_id`）；metrics 的 `groups[]` + `total_traces`；runs 的
`manifest` / `summary` / `gate` 聚合。实现见 `routes.py:738-886`；admin 依赖见
`routes.py:50`（`Depends(require_role("admin"))`）。

## B. 只读

- 路由方法：`app.openapi()` 的 4 路径均只有 `get`（`01-openapi.json`）；无
  post/put/patch/delete。`main.py:188` 只注册 router。
- 请求前后 SHA-256 **全部一致**（`_scratch/readonly_probe.py`）：业务库
  `mktkb.sqlite3`、trace 主库、trace `-wal`、`run_manifest.json` 四者 before==after；
  另在 `probe_t113.py` 中核对 `run_manifest/summary/gate` 三份 run 产物、trace 主库、
  trace WAL、run 目录清单，同样 `hashes_equal=true`、`mtime_equal=true`。
- 端点只用 `TraceRepository.get` / `list_by_request` / `list_window`（纯 SELECT，
  `store.py:249-281`）与 `Path.read_text`（`routes.py:549-561`）；无写调用、无
  `export_jsonl`/`purge`。`require_role` 只读会话（`auth/service.py:75-94`），不写业务库。

## C. 无原文 / 无 `*_json` / 无逐题字段

构造 trace 时把秘密文本埋入 `SpanRecord.attributes_json`、`summary.metrics.note`、
`summary.declarations`、`gate.failures.evidence`、`gate.unknowns.reason`、
`gate.warnings`、`gate.quality.note`，并写入 holdout `cases.jsonl` 的题干/答案秘密文本。
4 端点 + holdout run 的响应：

```text
secret_in_any_body: trace=false requests=false metrics=false run=false holdout=false
case_id_in_any_body: trace=false requests=false metrics=false run=false holdout=false
json_suffix_keys: []          # 递归键名扫描，无任何 *_json
question/answer/context/cases/case_id keys: []
trace 响应不含 holdout run_id / case_id / dataset_version
span 只返回 attribute_keys=["fact_count","secret_note"] 与 count，不返回值
```

响应模型白名单见 `routes.py:87-261`；TraceSummary 不含 `case_id`/`run_id`/
`dataset_version`（`routes.py:322-355`）；span 只做键名摘要（`routes.py:308-319`）。

## D. Holdout 不可达

`run_manifest.json` 的 `suite="holdout"`、`holdout_details=true`，`cases.jsonl` 含
`HOLDOUT-CASE-LEAK-CHECK` 与秘密题干/答案；`summary.holdout` 带 `strata` 与
`details_written=true`。`GET /runs/{run_id}`：

```text
holdout_detected=true   details_withheld=true
summary.holdout = {aggregate_only:false, details_written:true, strata:{core:12}}
响应不含 cases / case_id / 题干 / 答案 / SECRET 文本
```

实现见 `routes.py:849-866`（只读三份 JSON 白名单；`cases.jsonl` 只做存在性判断）；
trace/requests 端点不返回 `case_id`/`run_id`，不能间接取到逐题内容。路径穿越：
`run_id` 正则 `^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$` + `..`/尾点拒绝（`routes.py:269-278`），
`resolve()` 后 `is_relative_to(runs_root)`（`routes.py:564-575`）；实测
`/runs/%2e%2e` 与 `/runs/..%5Cescape` 均 422 `INVALID_RUN_ID`；在 runs 根内创建
junction 指向外部目录后 `GET /runs/escape-link` → 404 `RUN_NOT_FOUND`（探针直接调用
`_run_directory` 同样 404）。

## E. 降级 / 错误矩阵

| 场景 | 实测 |
| --- | --- |
| 默认 `trace_enabled=false`（4 端点） | 200；trace/requests/metrics 空聚合 + `degraded_reason="trace_disabled"`；runs 仍返回聚合并附 `trace_disabled` |
| 仓储 `close()` 后 | trace / metrics 200 + `trace_unavailable`，不 500 |
| 未知 trace / run | 404 `TRACE_NOT_FOUND` / `RUN_NOT_FOUND` |
| 非法 window（`abc/0h/24/1.5h/1H`） | 422 `INVALID_WINDOW` |
| `.hidden` / `bad..id` / 超长 id | 422 `INVALID_TRACE_ID` / `INVALID_RUN_ID` |
| 路径穿越（`%2e%2e`、`..%5C`） | 422；不 200 |
| 坏 run JSON | 200，`manifest=null`，`degraded_reason="manifest_invalid"` |

## F. metrics 聚合（独立造数）

窗口内 7 条 trace（6 条 `rag/answer` + 1 条 `legacy/not_found`）+ 1 条 30 小时前旧 trace
+ 1 条 `token_usage_json` 不可解析（`rag/no_answer`）。`GET /metrics?window=24h`：

```text
total_traces=7  invalid_created_at_count=0  invalid_payload_count=1
degraded_reason=partial_data
rag/answer: count=6 latency_samples=6 p50=10 p95=40
            tokens_input=401 tokens_output=82 tokens_total=483
            cost_cny=2.5 degraded_count=3 error_count=0
legacy/not_found: count=1 p50=None（无 latency）
```

旧 trace 在 24h 外被排除；`window=30m` 仍计 7 条（均在窗口内）。百分位实现为
nearest-rank（`routes.py:459-465`）；tokens/cost/degraded 解析见 `routes.py:402-452`。

## G. OpenAPI

`create_app(Settings(_env_file=None,...), initialize=False).openapi()`：

```text
4 paths，均只有 get；每条 get 的 responses 均含 401 / 403
securitySchemes={}；4 个 operation 均无 security 键（非 null，是缺省）
openapi() 后 data_dir 不存在（initialize=False 不建目录）
```

**LOW 缺口**：handoff §3.5 字面要求 “admin 安全声明”，但 OpenAPI 没有机读的
`securitySchemes`/`security`（只有 401/403 说明）。运行时 admin 依赖确实挂载且 401/403
实测通过；全应用均为 cookie-session，无既有 securityScheme 可复用。建议 T114 文档包
补 `securitySchemes`/`security` 或明确口径；不构成本包的数据泄露/越权缺陷。

## H. 结论

A–F 均 PASS；G 为 PASS（4 路径/仅 GET/401/403/导出）附 LOW 口径缺口。

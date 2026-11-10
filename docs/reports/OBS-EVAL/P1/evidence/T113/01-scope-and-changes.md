# T113 证据 01：范围、改动与命令

模型：`wb / cn:deepseek-v4.1-flash / reasoning_effort=max`

## A. 起点与范围

- 分支 `p1/fix-retrieval`，父提交 `fcc3434`；开工前 `git status --short` 为空。
- 目标：设计 §6 只读监控 API，4 个 `GET` 端点，管理员权限，只返回哈希/计数/长度/
  时长/成本/状态；trace 关闭降级；不暴露 Holdout 逐题/题干/答案。
- 只改 handoff 允许路径；未改业务路由/API/schema/conversations/intent/账本/GO/
  `.env`/Holdout；未新增依赖；零真实模型/OCR/embedding/rerank 调用；未 push/amend。

## B. 改动

| 文件 | 性质 | 要点 |
| --- | --- | --- |
| `backend/src/mktkb/observability/routes.py` | 新增 | 4 个只读端点 + Pydantic 白名单响应；`Depends(require_role("admin"))`；trace 关闭/仓储不可用降级；`Nh`/`Nm` 窗口；run_id/trace_id/request_id 校验；run 目录逃逸检查；holdout 聚合与 `details_withheld` |
| `backend/src/mktkb/main.py` | 修改 | `api.include_router(observability_router)`（`/api/v1` 下） |
| `backend/src/mktkb/observability/store.py` | 修改 | 新增 `TraceRepository.list_window(since)`：**纯 SELECT 只读聚合**，返回窗口内 trace 与不可解析 `created_at` 计数；不改 schema/写入语义 |
| `backend/tests/observability/test_routes.py` | 新增 | 35 条测试：admin 200×4、employee 403、未登录 401、降级、404/422、聚合、无原文、holdout、OpenAPI、initialize=False、只读哈希不变 |
| `.claude/handoffs/T113-observability-api/report.md` | 新增 | 五段报告（≤80 行） |
| `docs/reports/OBS-EVAL/P1/evidence/T113/` | 新增 | 本证据 4 份 |

## C. 命令（cwd=仓库根）

```text
$env:MKTKB_PROJECT_TOTAL_LIMIT_CNY="20.0"
.\.venv\Scripts\python.exe -B -m pytest backend/tests/observability/test_routes.py -q -p no:cacheprovider --basetemp backend\.pytest-tmp\T113-routes
.\.venv\Scripts\python.exe -B -m pytest backend/tests/observability -q -p no:cacheprovider --basetemp backend\.pytest-tmp\T113-observability
.\.venv\Scripts\python.exe -B -m pytest backend/tests -q -p no:cacheprovider --basetemp backend\.pytest-tmp\T113-full

$env:PYTHONPATH="backend/src"
.\.venv\Scripts\python.exe -B -m mktkb.evaluation.cli run  --suite b0       --mode local --out backend\.pytest-tmp\T113\eval\b0
.\.venv\Scripts\python.exe -B -m mktkb.evaluation.cli gate --run backend\.pytest-tmp\T113\eval\b0
.\.venv\Scripts\python.exe -B -m mktkb.evaluation.cli run  --suite badcase  --mode local --out backend\.pytest-tmp\T113\eval\badcase
.\.venv\Scripts\python.exe -B -m mktkb.evaluation.cli gate --run backend\.pytest-tmp\T113\eval\badcase
.\.venv\Scripts\python.exe -B -m mktkb.evaluation.cli run  --suite regression --mode local --out backend\.pytest-tmp\T113\eval\regression
.\.venv\Scripts\python.exe -B -m mktkb.evaluation.cli gate --run backend\.pytest-tmp\T113\eval\regression
```

`backend/.pytest-tmp/*`、`var/*` 均被 `.gitignore` 覆盖，不 commit。

## D. 只读聚合方法的存在理由

指标端点需要跨 trace 扫描 `created_at` 时间窗口；既有读 API 只有 `get(trace_id)` /
`list_by_request(request_id)` 的精确查询，没有全窗口读取能力。为避免在路由层访问
`TraceRepository` 私有连接或调用会写文件的 `export_jsonl`，只在 `store.py` 追加
`list_window(since)`：单条 `SELECT * FROM traces ORDER BY rowid`，不建表、不写库、
不改写入语义；不可解析的 `created_at` 不猜测时间，单独计数返回给调用方按 degraded
处理（报告 §4 单列）。

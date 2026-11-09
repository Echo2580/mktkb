模型：`wb / cn:deepseek-v4.1-flash / reasoning_effort=max`

# T113 监控 API（只读聚合）

## 1. 起点与范围

- 分支 `p1/fix-retrieval`，父提交 `fcc3434`；开工前 `git status --short` 为空。
- 只实现设计 §6 的 4 个只读监控端点，挂 `/api/v1/observability/*`；全部
  `Depends(require_role("admin"))`。未改业务路由/API/schema/conversations/intent/
  账本/GO/`.env`/Holdout；未新增依赖；零真实模型/OCR/embedding/rerank 调用。

## 2. 改动（handoff 允许路径）

| 文件 | 要点 |
| --- | --- |
| `observability/routes.py`（新增） | 4 端点 + Pydantic 白名单响应；trace 关闭/仓储不可用降级；`Nh`/`Nm` 窗口；id 校验与 run 目录逃逸检查；holdout 聚合与 `details_withheld` |
| `main.py` | 注册 `observability_router`（`/api/v1` 下） |
| `observability/store.py` | 新增 `TraceRepository.list_window(since)`：纯 `SELECT` 只读窗口查询，返回窗口内 trace 与不可解析 `created_at` 计数；不改 schema/写入语义 |
| `tests/observability/test_routes.py`（新增） | 35 条验收测试（见 §4） |
| `evidence/T113/`（4 份）+ 本报告 | 仅证据与报告 |

`list_window` 的理由：指标聚合需要跨 trace 扫描时间窗口，既有读 API 只有按
trace_id/request_id 的精确查询；为避免访问私有连接或调用会写文件的 `export_jsonl`，
只在 store 增加一条只读 SELECT。不可解析的 `created_at` 不猜时间，单独计数并由路由
标记 `degraded_reason="partial_data"`。

## 3. API 与 OpenAPI

- `GET /traces/{trace_id}`：trace 摘要 + spans 摘要（`span_count` / `attribute_keys` /
  `attribute_count`）；404 / 422 / trace 关闭 200 `trace_disabled`。
- `GET /requests/{request_id}/traces`：全部尝试摘要（`attempt` / `replayed` /
  `previous_trace_id`）；未知 request 200 空列表。
- `GET /metrics?window=24h`：按 path/outcome 的 count、P50/P95、tokens、cost、
  degraded/error；非法窗口 422 `INVALID_WINDOW`；解析失败 200 `partial_data`。
- `GET /runs/{run_id}`：manifest/summary/gate 聚合；404 / 422；坏 JSON 200 降级；
  holdout 只聚合（`holdout_detected` / `details_withheld`），不返回逐题/题干/答案。
- 响应只含哈希/计数/长度/时长/成本/状态；不含 question/answer/text/context、
  `*_json` 原文、属性值、SQL/库路径、凭据。span 只返回属性键名与个数。
- OpenAPI 导出：`backend/.pytest-tmp/T113/openapi.json`，SHA-256
  `812f0f8d7ad79eff4e35233036c7111ce17d0e44eb520907805ea899766bcd61`；4 路径均仅
  `get` 且声明 401/403；`create_app(initialize=False)` 检查后 data_dir 不存在。

## 4. 验证

```text
本包 tests/observability/test_routes.py  -> 35 passed
tests/observability                      -> 290 passed
tests 全量                                -> 1858 passed, 0 failed/0 error, 507.99s
                                            轮询峰值 RSS 约 411MB < 2GB
```

- **权限/错误**：admin 200×4；employee 403 `ROLE_REQUIRED`；未登录 401；未知
  trace/run 404；非法 window/trace/run id 422 或路径穿越 4xx；无 500。
- **降级**：默认 trace 关闭时 4 端点均 200；trace/requests/metrics 空聚合 +
  `trace_disabled`，runs 仍返回聚合并附该 reason；仓储关闭返回 `trace_unavailable`。
- **聚合**：造 7 条窗口内 trace + 2 条坏数据；`rag/answer` count=4、P50=20、P95=40、
  tokens 400/80/480、cost=1.0、degraded=2；总计 7，`invalid_created_at_count=1`、
  `invalid_payload_count=1`、`partial_data`。窗口过滤与 `24h/1h` 断言通过。
- **只读**：OpenAPI 仅 GET；4 端点调用前后 trace 库与 run 三份 JSON 的 SHA-256 +
  `st_mtime_ns` 完全一致。
- **无原文**：4 端点响应递归断言无 question/answer/text/context/case_id/`*_json`/
  evidence/路径字段，fixture 秘密文本不出现；span 不返回属性值。
- **Holdout**：`holdout_details=true` run 返回 `holdout_detected=true` /
  `details_withheld=true`，即使 `cases.jsonl` 含秘密题干/答案也不返回；聚合 run
  `details_withheld=false`、`aggregate_only=true`。
- **P0 本地对照**（只读 baseline）：

```text
b0        rows 40/40  signature diffs=0  gate exit 3  hard=[]  unknown=42
badcase   rows 13/13  signature diffs=0  gate exit 3  hard=[]  unknown=94
regression rows 7/7   signature diffs=0  gate exit 3  hard=[]  unknown=80
```

b0/badcase 指标与 T110/T111 收口值一致；regression 与 T109-R2 一致，无新增 hard。

## 5. 合规与后续

- 未读 Holdout 逐题（runs 仅对 holdout `cases.jsonl` 做存在性判断，不解析内容）；未 push/amend；无 skip/xfail/删断言；证据无凭据、`.env` 值、GO 原文、答案原文。
- 接口文档与 401 完整矩阵属 T114；本包已提供 OpenAPI 导出与 admin/employee 依赖证据。
- 门禁 exit 3 仍为既有 `min_sample_missing` + `thresholds_unapproved`（T112 暂缓），本包未改阈值/基线。

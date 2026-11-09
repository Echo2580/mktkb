# T113 证据 04：测试、P0 本地对照与合规

模型：`wb / cn:deepseek-v4.1-flash / reasoning_effort=max`

## A. 测试（cwd=仓库根，`MKTKB_PROJECT_TOTAL_LIMIT_CNY=20.0`）

```text
backend/tests/observability/test_routes.py -q
  -> 35 passed, 1 warning in 10.55s

backend/tests/observability -q
  -> 290 passed, 1 warning in 26.41s

backend/tests -q
  -> 1858 passed, 1 warning in 507.99s
     0 failed / 0 error；轮询峰值 RSS 约 411MB < 2GB
     唯一 warning 为既有 StarletteDeprecationWarning（httpx/httpx2），非本包引入
```

本包 35 条覆盖：admin 200×4、employee 403、未登录 401、trace 关闭 4 端点 200 降级、
仓储关闭 200 `trace_unavailable`、未知 trace/run 404、非法 window/trace/run id 422、
路径穿越 4xx、metrics 聚合（count/P50/P95/tokens/cost/degraded/error）与窗口过滤、
无原文字段/无 `*_json`/无路径/无属性值、holdout 逐题详情不可达、holdout 聚合 run、
OpenAPI 4 路径仅 GET + 401/403、`initialize=False` 不写 data_dir、只读前后文件哈希
与 mtime 完全一致、坏 run JSON 不 500。

## B. P0 本地 run + gate（只读 P0 baseline，不改基线）

| suite | run_id | status_counts | gate |
| --- | --- | --- | --- |
| b0 | `b0-local-20261109T012738289678Z-bd554081` | pass 29 / fail 3 / skipped 8 | exit 3，hard `[]`，unknown 42 |
| badcase | `badcase-local-20261109T012742287430Z-fac2d712` | pass 9 / fail 4 | exit 3，hard `[]`，unknown 94 |
| regression | `regression-local-20261109T012804653954Z-f5096177` | pass 5 / fail 2 | exit 3，hard `[]`，unknown 80 |

逐例签名对照（签名 = `(status, outcome.kind, [(check_id,status)...], error.code)`；
不比较 metrics/trace_id/duration）：

```text
b0        rows 40/40  signature diffs=0   vs var/eval/runs/p0-b0
badcase   rows 13/13  signature diffs=0   vs var/eval/runs/p0-badcase
regression rows 7/7   signature diffs=0   vs backend/.pytest-tmp/T109-R2/eval/regression-current
```

b0 / badcase 检索指标与 T110/T111 收口值一致：

```text
b0      Recall@10=0.96875  MRR@10=0.96875  nDCG@10=0.96875  empty_recall=0.03125
badcase Recall@10=0.7855614973 MRR@10=0.85 nDCG@10=0.7499953095 empty_recall=0.1
regr.   Recall@10=1.0      MRR@10=0.75     nDCG@10=0.8154648768 empty_recall=0.0
```

gate exit 3 均为既有 `min_sample_missing` + `thresholds_unapproved`（T112 负责），
无新增 hard failure；regression 状态与 T109-R2 验收 run 一致（RG006 保持 pass）。

## C. 只读 / 无原文 / 降级证据

- `test_endpoints_are_read_only_and_do_not_change_files`：4 个端点调用前后，
  trace SQLite 主库与 run 三份 JSON 的 SHA-256 + `st_mtime_ns` 完全一致。
- `test_openapi_contains_four_get_paths`：4 条路径均只有 `get`，均声明 401/403。
- `test_trace_disabled_returns_empty_aggregate_and_reason`：4 端点均 200；trace /
  requests / metrics 为空聚合 + `trace_disabled`；runs 返回聚合 + 该 reason。
- `test_trace_unavailable_repo_degrades_without_500`：仓储关闭后 trace/metrics 200
  + `trace_unavailable`。
- `test_holdout_run_is_aggregate_only`：`holdout_detected=true`、
  `details_withheld=true`，响应不含逐题 id / 题干 / 答案 / evidence。
- `test_responses_never_contain_question_answer_or_internal_json`：4 端点递归键名
  黑名单与秘密文本断言均通过。
- `test_initialize_false_does_not_write_data_dir`：OpenAPI 检查后 data_dir 不存在。

## D. 合规

- 未改业务路由/API/schema/conversations/intent/账本/GO/`.env`/Holdout；未改
  `conversations/`、`intent.py`、检索/评分/门禁配置；未新增依赖。
- 未读 Holdout 逐题；run 端点只读 manifest/summary/gate，`cases.jsonl` 仅做存在性
  判断（holdout 场景），不解析内容。
- 无 skip/xfail/删断言；未 push/amend；`backend/.pytest-tmp/*`、`var/*` 均 gitignored。
- 真实 provider 调用 0；证据不含凭据、`.env` 值、GO 原文、问题/答案原文。

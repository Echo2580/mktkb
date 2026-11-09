# T114 验收证据 03：范围、OpenAPI 快照与评测回归

模型：`wb / cn:deepseek-v4.1-flash / reasoning_effort=max`

## A. 交付范围（dev commit `2a0c192`）

```powershell
git show --stat 2a0c192
git diff --numstat 2a0c192^..2a0c192
```

7 files，全部为 handoff §2 允许路径；新增 2739 行、删除 0 行：

| 路径 | 类型 |
| --- | --- |
| `backend/tests/observability/test_routes_security.py` | 新增 860 行 |
| `docs/接口与数据契约.md` | 增补 50 行 |
| `docs/reports/OBS-EVAL/P1/evidence/T114/01..03*.md` | 新增 3 份 |
| `docs/reports/OBS-EVAL/P1/evidence/T114/openapi-observability.json` | 新增 |
| `.claude/handoffs/T114-observability-auth-docs/report.md` | 新增 80 行 |

未改交付物：

```text
git diff 9edc003..2a0c192 -- backend/src/mktkb/observability/routes.py
  -> 空
git diff 9edc003..2a0c192 -- backend/tests/observability/test_routes.py
  -> 空
git diff 9edc003..2a0c192 -- backend/tests/observability/conftest.py
  -> 空
git diff 9edc003..2a0c192 -- pyproject.toml backend/pyproject.toml uv.lock
  -> 空
```

`git diff 2a0c192..HEAD --stat` 仅 6 个 `.claude/handoffs/**` PM 簿记文件；
`git status --porcelain` 为空。测试文件无 `pytest.mark.skip` / `xfail`；既有
`test_routes.py` 未改（无删断言）。未新增依赖。

## B. OpenAPI 快照

`docs/reports/OBS-EVAL/P1/evidence/T114/openapi-observability.json`：

- 4 paths：`/api/v1/observability/{traces/{trace_id}, requests/{request_id}/traces,
  metrics, runs/{run_id}}`；每条仅 `get`；每条声明 `401`/`403`（及自动 `422`）。
- 13 个 schemas；与实时 `app.openapi()` 的 4 路径引用闭包完全相等（`openapi_check.py`，
  退出 0）；无 `limit`/`offset` 参数。
- 37,106 bytes；SHA-256 `51f7edfc8fc071cd55981518fa5233ede823a352bd61f3e47d79000ad6db5979`。
- 文档 §8.6 明确说明 Cookie 会话、未声明 `securitySchemes`，以 401/403 表达权限；
  这是 T113 已记录的 LOW-1 口径，不改业务鉴权/响应结构。

## C. b0 / badcase / regression（local + gate，离线）

命令（cwd=仓库根；`MKTKB_PROJECT_TOTAL_LIMIT_CNY=20.0`）：

```powershell
.\.venv\Scripts\python.exe -B -m mktkb.evaluation.cli run --suite <b0|badcase|regression> `
  --mode local --out backend\.pytest-tmp\T114v\eval\<suite>
.\.venv\Scripts\python.exe -B -m mktkb.evaluation.cli gate `
  --run backend\.pytest-tmp\T114v\eval\<suite>
```

`local` 由 runner 强制 `provider_mode="offline"`（`runner.py:1258-1261`），无真实调用。

| suite | run_id | rows | status_counts | gate |
| --- | --- | ---: | --- | --- |
| b0 | `b0-local-20261109T105944538845Z-e05aaf61` | 40/40 | pass29/fail3/skipped8 | exit 3, hard `[]`, failures 0, unknown 42 |
| badcase | `badcase-local-20261109T105950908420Z-472c1810` | 13/13 | pass9/fail4 | exit 3, hard `[]`, failures 0, unknown 94 |
| regression | `regression-local-20261109T110011331132Z-6c624c46` | 7/7 | pass5/fail2 | exit 3, hard `[]`, failures 0, unknown 80 |

独立逐例对照（`compare_runs.py`，退出 0）：

```text
b0          vs var/eval/runs/p0-b0                          signature_diffs=0 retrieved_diffs=0
badcase     vs var/eval/runs/p0-badcase                     signature_diffs=0 retrieved_diffs=0
regression  vs backend/.pytest-tmp/T109-R2/eval/regression-current
                                                            signature_diffs=0 retrieved_diffs=0
```

`gate exit 3` 为既有 `min_sample`/`thresholds` 未批准状态；三套 `hard_failures` 均为
`[]`，无新增硬失败；regression 状态与 T109-R2 一致。

## D. 合规

- 未读 `.env`：独立探针/脚本均 `Settings(_env_file=None)`；pytest 由既有
  `isolate_dotenv_in_test_process` 关闭默认 env_file。
- 未调用真实 DeepSeek/OCR/embedding/rerank：pytest 用 tmp SQLite/离线 fixture；
  evaluation `local` 由 runner 强制 `provider_mode="offline"`。
- 未打开 `docs/evidence/LOCAL-R1-20261101/P1-HOLDOUT/` 逐题内容；holdout 用例全部
  为合成 `SECRET_TEXT`。
- 证据 4 份（含 OpenAPI）、report 80 行、1 个 dev commit；`review.md` 为本验收产物。

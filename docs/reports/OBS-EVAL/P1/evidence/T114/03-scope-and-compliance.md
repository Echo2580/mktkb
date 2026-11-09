# T114 证据 03：范围、合规与产物

模型：`wb / cn:deepseek-v4.1-flash / reasoning_effort=max`

## A. 改动范围（全部 handoff §2 允许路径）

| 路径 | 类型 | 说明 |
| --- | --- | --- |
| `backend/tests/observability/test_routes_security.py` | 新增 | 62 条权限/负例/边界/不泄露/OpenAPI 测试 |
| `docs/接口与数据契约.md` | 增补 | 追加 `## 8. 观测与监控接口（只读）`（`:180` 起），既有章节未改 |
| `docs/reports/OBS-EVAL/P1/evidence/T114/openapi-observability.json` | 新增 | 4 paths + 13 相关 schemas，37,106 bytes |
| `docs/reports/OBS-EVAL/P1/evidence/T114/01..03*.md` | 新增 | 本目录 3 份证据 |
| `.claude/handoffs/T114-observability-auth-docs/report.md` | 新增 | 五段报告 |

**未改** `backend/src/mktkb/observability/routes.py`：本包测试未发现 T113 功能缺陷，
不需要 §0-2 的最小修复；权限模型、schema、响应字段结构均未变。
**未改** T113 `backend/tests/observability/test_routes.py`；未改业务路由/业务 API/
`conversations/`/`intent.py`/schema/账本/GO/`.env`/Holdout/`docs/evidence/**`/`var/**`。
未新增依赖（未改 `pyproject.toml` / `uv.lock`）；未 push/amend；单 commit。

## B. 测试纪律

- 新文件无 `pytest.mark.skip` / `xfail`；未删除或放宽任何既有断言；未使用
  `raise_server_exceptions=True` 掩盖 500（沿用 `TestClient(..., raise_server_exceptions=False)`，
  并逐端点断言非 500）。
- 复用 `observability/conftest.py` 既有 fixture（`trace_app` / `trace_repo` /
  `trace_employee` / `trace_admin`）与 `tests/conftest.py` 的 `admin_client` / `settings`；
  未改 conftest。
- 测试数据全部在 `tmp_path`（`backend/.pytest-tmp/...`）内构造；未读写仓库
  `var/`；未写 `docs/evidence/`。

## C. 零真实调用 / 数据边界

- 未调用真实 DeepSeek / OCR / embedding / rerank；测试只用 `Settings(_env_file=None)`、
  fake/offline 数据与临时 SQLite。
- 未读取 `.env`；未打开 Holdout 逐题目录；holdout 用例使用合成 `SECRET_TEXT`，
  且只验证拒绝返回。
- 未在证据/报告中写入凭据、密钥、GO 原文、问题/答案原文；`SECRET_TEXT` 仅作为
  合成哨兵出现在测试代码与本证据说明中。

## D. OpenAPI 快照

生成脚本：`.claude/handoffs/_scratch/T114/gen_openapi.py`（gitignored，不入库）。
输入为 `create_app(settings, initialize=False).openapi()`；输出仅保留 4 条
`/api/v1/observability/**` 路径、其传递引用的 13 个 schemas、`openapi` 版本与 `info`。
SHA-256：`51f7edfc8fc071cd55981518fa5233ede823a352bd61f3e47d79000ad6db5979`。
实时一致性由 `test_openapi_snapshot_matches_live_schema`（`test_routes_security.py:834`）守护。

## E. 工作树说明

开工时 `git status --porcelain` 为空。执行期间 `.claude/handoffs/**` 出现 PM 并行
簿记改动（T112 相关 handoff/prompt 与索引），非本包产物；提交时只暂存上表允许
路径，未把 PM 簿记文件纳入本 commit。

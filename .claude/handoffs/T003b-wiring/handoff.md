# T003b · 配置 + 中间件接线（P0 第 4 包）

> PM 任务单。基线：`p0/obs-eval` @ `dea4d5d`（T001/T002/T003a 已通过独立验收）。本包只接"观测开关 + 中间件"，**不埋业务 Span**（那是 T003c/d）。
> 完成后由全新上下文的独立验收助手按本文件逐条证伪。

## 1. 目标（一句话）

在 `create_app` 里挂上 Trace 开关与仓储，并让 QA 问答 POST 在响应头返回 `X-Trace-ID`、best-effort 落一条 trace；默认关闭时零副作用、业务行为不变。

## 2. 交付物（只准写这些路径）

- 修改 `backend/src/mktkb/config.py`（追加 trace 配置字段与校验）
- 修改 `backend/src/mktkb/main.py`（`create_app` 创建/关闭 `app.state.trace_repo`；`request_context` 中间件只对 QA POST 启动 trace、返回 `X-Trace-ID`）
- 新增 `backend/tests/observability/test_middleware.py`
- 新增 `backend/tests/observability/conftest.py`（仅在需要时；与后续包共享的 fixture 放这里）
- 证据（入库）：`docs/reports/OBS-EVAL/P0/evidence/T003b/`
- 报告：`.claude/handoffs/T003b-wiring/report.md`（五段）

## 3. 输入（只看这些）

1. P0 设计 §5（架构）、§6.1（trace_id 与 X-Trace-ID）、§6.5（内容隐私/HMAC）、§6.6（写入语义）、§10（兼容性：唯一允许新增 `X-Trace-ID` 响应头）。
2. P0 计划 Task 3 的 Interfaces 段（`start_trace` 签名、`settings.trace_enabled` 默认 False、`MKTKB_TRACE_ENABLED=1` 开启、`create_app` 建 `app.state.trace_repo`）。
3. 已验收代码（只读）：`observability/tracer.py`、`observability/store.py`、`observability/contracts.py`；`main.py` 现有 `request_context`（约 102–110 行）与 `create_app`/lifespan；`config.py` 现有 `Settings` 与 `data_dir` 约定。
4. 既有测试 fixture：`backend/tests/conftest.py`、`backend/tests/integration/`（`client` 如何构造）。

## 4. 允许 / 禁止

**允许**：§2 交付物；`git switch p0/obs-eval`；本包一个 commit。

**禁止**：
- 不改 `qa/` / `rag/` / `conversations/`（T003c/d 才埋点）；不改 `observability/{tracer,store,contracts,versioning}.py`；不改既有测试。
- 不新增依赖；不改业务 API 请求参数与响应 Body 字段结构（只允许新增 `X-Trace-ID` 响应头）。
- 零真实模型/OCR/embedding/rerank 调用；不读 `.env`；不打印/不记录凭据；不访问外网。
- 不碰 `docs/evidence/**`、`var/**`（运行时目录在测试里用 tmp_path）、`fixtures/**`、账本/GO、归档区；不 push；不 commit PM 的未跟踪文件。
- **P0 不允许 live**：中间件绝不传 `TraceMode.LIVE`（`tracer.py` 内核接受该枚举，接线必须硬保证不传）。

## 5. 验收标准（逐条可判定）

1. **默认关闭零副作用**：`settings.trace_enabled=False`（默认）时，QA POST 响应**无** `X-Trace-ID`、不创建任何 Trace DB 文件、`current_trace()` 为 None；既有 `X-Request-ID` 行为不变。
2. **开启后落 trace**：以 tmp 路径开启（`MKTKB_TRACE_ENABLED=1` 或构造 Settings），QA POST 响应头 `X-Trace-ID` 为合法 UUID 形态；用该 id 能在 TraceRepository 查到一条 trace，且 `request_id`/`http_request_id`/`mode=local`/`scope=end_to_end`/`content_mode` 合理；在 T003c/d 埋点前 spans 允许为空（这是预期，不是缺陷）。
3. **范围只限 QA POST**：GET `/api/v1/conversations*`、登录、上传、其它 POST 等端点**无** `X-Trace-ID`、不写 trace。
4. **写入失败不影响产品**：monkeypatch `TraceRepository.write_best_effort` 抛异常、或 trace_db_path 不可写时，QA POST 仍返回正常状态码与 body（日志有 `trace_write_error`，不向响应泄漏内部错误）。
5. **行为不变**：同一固定请求，trace 关闭与开启两种设置下响应 body 归一化（去 request_id/message_id/时间等易变字段）后**完全一致**；既有 `backend/tests/integration/test_chat.py`、`backend/tests/integration/test_answer_commit.py` 全绿。
6. **mode 硬约束**：单测断言中间件启动 trace 时 `mode` 不为 `live`（P0 禁止）；代码里无"按 provider 模式传 live"的路径。
7. **配置安全**：新增字段有合理默认值，不破坏既有 `Settings` 构造与全量测试；`trace_content_mode` 默认 `hash`，P0 只允许 `off`/`hash`（`redacted`/`full` 显式拒绝）；HMAC key 用 `SecretStr`，不出现在日志/响应/异常/trace 记录里；无 key 时用 sha256 并在文档写明。
8. **测试与回归**：新增测试全过；`backend/tests` 全量相对 T003a 基线 **1176 passed** 无新增失败。

## 6. 必须实际运行的检查（输出原文存证据目录）

```powershell
$env:MKTKB_PROJECT_TOTAL_LIMIT_CNY = "20.0"
git rev-parse --short HEAD   # 应为 dea4d5d
```

```powershell
.\.venv\Scripts\python.exe -B -m pytest backend/tests/observability/test_middleware.py -q -p no:cacheprovider --basetemp backend\.pytest-tmp\obs-mw
.\.venv\Scripts\python.exe -B -m pytest backend/tests/observability backend/tests/integration/test_chat.py backend/tests/integration/test_answer_commit.py -q -p no:cacheprovider --basetemp backend\.pytest-tmp\obs-mw-int
.\.venv\Scripts\python.exe -B -m pytest backend/tests -q -p no:cacheprovider --basetemp backend\.pytest-tmp\t003b-full
git show --stat --oneline HEAD
```

说明：既有全量套件会向 gitignore 的 `docs/evidence/` 写测试产物（既有行为），不要 commit 它们；若用 `--amend` 合并证据，最终 HEAD 的 `git show --stat` 必须重新采集。

## 7. 已知非阻塞观察（T003a 验收方提出，本包须遵守）

- 中间件不得传 `TraceMode.LIVE`（见 §5.6）。
- `annotate` 可覆盖启动参数字段——T003b 不主动 annotate 启动字段；只在必要时写数据字段。
- 条件 Span 依赖 `*_json` 字段的 canonical JSON；本包不写这些字段（T003c/d 负责）。
- `replayed=True` 且缺 outcome 时 status 优先为 `replayed`；本包不涉及重放。

## 8. 提交

分支 `p0/obs-eval`，一个 commit：`p0/T003b config & middleware`；只 add 本包交付物；不 push。

## 9. report.md 格式

五段：完成内容 / §5 逐条自证（命令或 文件:行）/ 实际运行结果（含 commit sha、stat、全量通过数）/ 偏离与未做 / 风险与遗留。末尾另给 ≤10 行交接摘要。

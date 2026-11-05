# T003b 报告：配置 + 中间件接线（P0 第 4 包）

> 分支：`p0/obs-eval`（基线 `dea4d5d`，T001/T002/T003a 已通过独立验收）；开发方：dev-t003b。
> 本报告是开发方自证，验收请以独立复跑结果为准（不采信本文件任何“已完成”结论）。
> 证据目录：`docs/reports/OBS-EVAL/P0/evidence/T003b/`。
> 范围：只接“观测开关 + 中间件”，**不埋业务 Span**（T003c/d）——开启后 trace 的 `spans` 为空、
> `request_id` 为 None、`status=incomplete` 都是本包边界内的预期，不是缺陷。

## 1. 完成内容

修改 2 个既有文件 + 新增 2 个测试文件 + 证据 + 本报告（不改 `qa/` / `rag/` / `conversations/`、
不改 observability 内核、不改既有测试、不新增依赖、不 push）：

| 文件 | 一句话 |
| --- | --- |
| 修改 `backend/src/mktkb/config.py`（+76 行） | 追加 `trace_enabled=False` / `trace_db_path=None` / `trace_content_mode="hash"` / `trace_hmac_key: SecretStr` 四字段；3 个 `field_validator`（内容模式只允许 off/hash、redacted/full 显式拒绝；空白 HMAC key 归一为 None；空白库路径归一为 None）+ 2 个属性（`resolved_trace_db_path`、`trace_hmac_key_bytes`） |
| 修改 `backend/src/mktkb/main.py`（+42 行） | 模块常量 `TRACE_MODE = TraceMode.LOCAL`（写死 local，绝不 live）、`TRACE_SCOPE = "end_to_end"`、QA POST 路径正则 + `_is_qa_post`；`create_app` 仅在 `trace_enabled` 时构造 `app.state.trace_repo`，lifespan 关闭；`request_context` 只对 QA POST 用 `start_trace` 包裹 `call_next`，响应加 `X-Trace-ID` |
| 新增 `backend/tests/observability/conftest.py`（151 行） | 后续 T003c/d / 评测包可复用 fixture：`trace_db_path` / `trace_settings` / `trace_app` / `trace_repo` / `trace_employee` / `trace_admin` + `open_session` / `create_conversation` / `ask_question` / `trace_rows` |
| 新增 `backend/tests/observability/test_middleware.py`（565 行，20 个测试函数） | 锁定 handoff §5 八条验收：默认关闭零副作用、开启落 trace + `X-Trace-ID`、范围只限 QA POST、写入失败不影响产品、body 不变、mode 硬约束（静态 + 运行时）、配置安全、全量回归（命令证据） |
| 证据 `docs/reports/OBS-EVAL/P0/evidence/T003b/00–06` | 基线 branch/rev-parse、TDD RED、本包 / 范围套件 / 全量 pytest 原文、提交 `git show --stat`、交付物 SHA-256 |

一句话：`Settings` 新增默认关闭的 Trace 配置；`create_app` 只在开启时创建独立 SQLite 的
`TraceRepository`；HTTP 中间件只对 QA 问答 POST 用 `start_trace(mode=TraceMode.LOCAL,
scope="end_to_end", content_mode=settings.trace_content_mode, hmac_key=settings.trace_hmac_key_bytes)`
包裹下游调用链（contextvars 对业务 handler 可见，测试已证），响应加唯一新增的 `X-Trace-ID`，
写入走内核 best-effort（失败不影响响应）。

## 2. 验收标准自证（§5 逐条）

1. **默认关闭零副作用** — `config.py:113-125`（四个字段默认值，`trace_enabled=False` 在 `:116`）；
   `main.py:101`（只有 `trace_enabled=True` 才构造仓储，关闭时完全不 touch 路径/不建 DB）；
   `main.py:125`（`app.state.trace_repo = None`）；`main.py:135`（中间件只有 repo 存在且是 QA POST 才启动
   trace，否则走 `:150-152` 的原路径，只加既有 `X-Request-ID`）；`config.py:335-344`（默认路径
   `<data_dir>/observability/qa-traces.sqlite3`）。
   测试：`test_middleware.py:138`（默认字段与默认路径）、`:150`（关闭时 `trace_repo is None`、QA POST 200、
   无 `X-Trace-ID`/有 `X-Request-ID`、`current_trace() is None`、无 `observability` 目录/DB 文件、且用
   spy 替换 `mktkb.main.start_trace` 证明根本没被调用 → “零副作用”是结构性的而不是“写了没观察到”）、
   `:555`（lifespan 关闭仓储）。

2. **开启后落 trace** — `main.py:101`（按 `settings.resolved_trace_db_path` 建仓储）、`:135-148`
   （QA POST 的 `start_trace` + 响应头 `X-Trace-ID`）、`:132`（`request.state.trace_id` 供 T003c/d 对齐）、
   `config.py:346-355`（HMAC key 解码为 bytes，只进内存）。
   测试：`test_middleware.py:183`（库落在配置路径）、`:192`（`X-Trace-ID` 合法 UUID 形态；用该 id
   `repo.get` 到一条 trace：`http_request_id` == 响应 `X-Request-ID`、`mode="local"`、
   `scope="end_to_end"`、`content_mode="hash"`、`replayed=False`、`attempt=1`、`spans=[]`、
   `question_hash=None`、`status="incomplete"`（未埋 Span/未设 outcome 的预期）、`request_id is None`
   （见 §4.1）；一条 QA POST 恰写一行）、`:223`（两次 QA POST 两条不同 trace）、`:284`（`content_mode=off`
   跟随配置落库）、`:265`（contextvars 传导：业务 handler 内 `current_trace().trace_id` == 响应头）。

3. **范围只限 QA POST** — `main.py:33-43`（模式/范围常量与 `_QA_POST_PATH` 精确路径、方法匹配）、
   `main.py:135`（唯一启动点）。
   测试：`test_middleware.py:305`（登录 POST、`GET /healthz`、`GET /conversations`、`POST /conversations`、
   `GET /conversations/{id}/messages`、`POST /documents` 上传 6 类请求：全部无 `X-Trace-ID` 且 Trace 库
   0 行；随后 QA POST 正向对照：有头且 1 行）。

4. **写入失败不影响产品** — 中间件不 try/except、不改写响应（`main.py:135-152`）；写入失败由内核
   `TraceContext.finish`（T003a）与仓储 `write_best_effort`（T002）best-effort 兜底，本包不改内核。
   测试：`test_middleware.py:353`（monkeypatch `TraceRepository.write_best_effort` 抛 `RuntimeError`：
   QA POST 仍 200、body 正常 `kind=not_found`、含 `X-Trace-ID`、响应无 `trace_write_error/Traceback/sqlite`
   等内部痕迹、无半条 trace；日志命中内核兜底 `trace_finish_error`）、`:375`（trace 库路径的父路径是
   普通文件→库打开失败：QA POST 仍 200、body 正常、仓储自身日志命中 `trace_write_error`、不向响应泄漏）。
   ⚠ 日志名差异属内核分工：仓储自身失败记 `trace_write_error`，若 `write_best_effort` 被整体替换为抛异常
   则由 tracer 记 `trace_finish_error`（T003a 只读内核语义，本包不改）。

5. **行为不变** — 中间件不改请求/响应 body（`main.py:135-152` 只加头）；业务代码零改动。
   测试：`test_middleware.py:409`（同一固定 `client_request_id` + 固定问题，trace 关闭 vs 开启两个应用：
   状态码一致、响应 body 归一化（去 `request_id/message_id/conversation_id/created_at/updated_at`）后
   **完全一致**、键集合一致，唯一差异是开启侧多 `X-Trace-ID`）；既有 `integration/test_chat.py`、
   `integration/test_answer_commit.py` 包含在证据 03（239 passed）与证据 04（1196 passed）中全绿。

6. **mode 硬约束（P0 禁止 live）** — `main.py:30-33`（`TRACE_MODE = TraceMode.LOCAL`，注释写明“写死
   LOCAL、不按 provider 模式分支、内核不会替调用方拦 live”）、`main.py:138`（`mode=TRACE_MODE`）。
   测试：`test_middleware.py:446`（静态 AST：`main.py` 中 `start_trace` 唯一调用、`mode` 是静态绑定
   （模块常量→`TraceMode.LOCAL`）、全文件无 `LIVE` 属性引用、无 `"live"` 字符串；`:237`（运行时 spy：
   `mode is TraceMode.LOCAL`、`!= TraceMode.LIVE`、`str(mode)=="local"`，落库记录 `mode=="local"`）。

7. **配置安全** — `config.py:113-125`（默认值不破坏既有 `Settings` 构造）；`:169-182`（P0 只允许
   `off`/`hash`，`redacted`/`full` 显式 `ValueError`；大小写/空白归一）；`:184-196`（`SecretStr`，空白归一
   None）；`:198-207`（空白路径归一 None）；`:335-344`（解析路径）；`:346-355`（HMAC bytes，仅内存）。
   无 key 时 tracer 退化为 sha256 的既有实现与文档：`observability/tracer.py:11-12,704-705`（T003a
   已验收）+ 本包 `config.py:122-124` 注释。
   测试：`test_middleware.py:485`（`MKTKB_TRACE_ENABLED=1` 开启）、`:494`（off/hash 接受、redacted/full/
   其它/空显式拒绝且错误信息含 off/hash）、`:507`（`SecretStr`：`repr/str/model_dump_json` 均不含 key、
   显式 `get_secret_value` 可取、掩码 `**********`）、`:522`（内容模式非法 + 有 key 时异常文本不含 key）、
   `:531`（`MKTKB_TRACE_HMAC_KEY` 环境变量载入为 `SecretStr`，repr/JSON 不泄漏）、`:541`（路径解析与
   空白归一）。

8. **测试与回归** — 本包 20 passed（证据 02）；handoff §6 范围套件
   `observability + integration/test_chat.py + integration/test_answer_commit.py` 239 passed（证据 03）；
   `backend/tests` 全量 **1196 passed, 1 warning**（证据 04；T003a 基线 1176 + 本包 20，0 failed/0 error）。

## 3. 实际运行的命令与结果

环境：Windows / PowerShell 5.1、Python 3.12.7（`.venv`）、pytest 9.1.1；每条命令前设
`$env:MKTKB_PROJECT_TOTAL_LIMIT_CNY = "20.0"`，解释器 `.\.venv\Scripts\python.exe -B`。
证据采集用 `cmd /c` + `PYTHONIOENCODING=utf-8` 原始重定向（PowerShell 5.1 的 `*>` 默认 UTF-16LE），
全部证据 UTF-8 无 BOM，末尾追加 `exit_code=` 行。

```powershell
# 开工基线（证据 00）
git branch --show-current   # → p0/obs-eval
git rev-parse --short HEAD  # → dea4d5d

# TDD RED：先写测试、确认失败（证据 01，实现前）
.\.venv\Scripts\python.exe -B -m pytest backend/tests/observability/test_middleware.py -q -p no:cacheprovider --basetemp backend\.pytest-tmp\obs-mw-red
# → 15 failed, 3 errors, 1 warning（缺 config 字段 / app.state.trace_repo；exit 1）

# 实现后：本包测试全过（证据 02）
.\.venv\Scripts\python.exe -B -m pytest backend/tests/observability/test_middleware.py -q -p no:cacheprovider --basetemp backend\.pytest-tmp\obs-mw
# → 20 passed, 1 warning（exit 0）

# handoff §6 范围套件（证据 03）
.\.venv\Scripts\python.exe -B -m pytest backend/tests/observability backend/tests/integration/test_chat.py backend/tests/integration/test_answer_commit.py -q -p no:cacheprovider --basetemp backend\.pytest-tmp\obs-mw-int
# → 239 passed, 1 warning in 90.83s（exit 0）

# 全量回归（证据 04）
.\.venv\Scripts\python.exe -B -m pytest backend/tests -q -p no:cacheprovider --basetemp backend\.pytest-tmp\t003b-full
# → 1196 passed, 1 warning in 548.42s (0:09:08)（exit 0；基线 1176 + 本包 20）

# 提交（证据 05）
git commit -m "p0/T003b config & middleware"
# → [p0/obs-eval 20f0105] p0/T003b config & middleware
#    9 files changed, 1602 insertions(+)
git show --stat --oneline HEAD   # 原文见证据 05
```

**提交与 amends 说明**：代码 / 测试 / 证据 00–04 先提交为 C1 = `20f0105`（9 文件、1602 插入）；
证据 05（`git show --stat` 原文）、证据 06（SHA-256）与本报告在 C1 之后采集，再经 `git commit --amend`
并入同一提交（单 commit 约束）。证据 05 记录的是**最终 amend 前一次**的
`git show --stat --oneline HEAD` 原文（amend 后重新采集），与最终 HEAD 的 stat 相比仅首行
“提交自身短 sha”不同（sha 不可能写入自身内容；已验证其余行逐字节一致）；最终 HEAD 短 sha 见
回复末尾交接摘要与 `git log -1 --format=%h`。

**交付物 SHA-256（证据 06，提交前采集）**：

```text
b82c25ce92f16d94c6155abce96857d7f8c4e14117593f215a09e9a236a32181  backend/src/mktkb/config.py
a0473f7c734f282bd7b9b4ea9cedfd639db3975f99e31d60495474e680e77800  backend/src/mktkb/main.py
b31796144e171a61b6d9e995e7602c7dc1a5f207f850cc362c284a701d146ff7  backend/tests/observability/conftest.py
bdf8865ed644e27fe35138345668be4d3d6f677435a90b6cd21b5a9ccc717328  backend/tests/observability/test_middleware.py
（证据 00–05 的哈希见证据 06 原文）
```

## 4. 偏离与未做

1. **`request_id` 保持 None（T003b 边界）**：产品请求 ID 是 `ConversationRequest.id`，只在
   `conversations/service.py` 内部产生；本包按范围不解析/不注入请求体（避免 `BaseHTTPMiddleware`
   消费 body 的协议风险），因此中间件只能填 `http_request_id`（对齐 `X-Request-ID`）。
   T003c/d 必须在业务埋点里 `trace.set_request_id(...)`；handoff §5.2 的 “request_id 合理”在本包
   边界的合理解释是“未伪造、明确为 None”。
2. **`path` 用内核默认 `TracePath.RAG`、`status=incomplete`**：`start_trace` 未显式传 `path`
   （不主动改启动字段，§7 观察），实际 path/outcome 由 T003c/d 的 `set_path`/`set_outcome` 设置；
   在埋点前缺 outcome → `status=incomplete` 是内核预期语义（T003a 已验收）。
3. **QA POST 的识别方式**：中间件运行在路由匹配之前，故按 URL 路径正则精确匹配
   `POST /api/v1/conversations/{id}/messages`（`main.py:38`），不读 `request.scope["route"]`。副作用是
   该端点的鉴权失败/参数校验失败请求也会启动并写一条 `incomplete` trace（仍限于 QA POST 端点）；
   T003c/d 记录 outcome 后可再按需要收紧。非 QA 端点（含上传、登录、会话 CRUD）已验证零 trace。
4. **`trace_content_mode` 做 `strip().lower()` 归一化**：部署友好（环境变量大小写/空白），白名单仍严格
   只有 `off` / `hash`；`redacted` / `full` 显式拒绝。
5. **`TRACE_MODE` 为模块级常量**（而非调用点内联字面量）：语义更清楚且便于静态断言；
   测试会解析常量绑定必须为 `TraceMode.LOCAL`，全文件禁止 `LIVE`。
6. **写入失败日志名分工**（见 §2.4）：monkeypatch 替换 `write_best_effort` 时由 tracer 记
   `trace_finish_error`；真实库不可写时由仓储记 `trace_write_error`。两者都不影响产品响应；本包不改
   T003a/T002 内核（只读约束）。
7. **conftest 的 `trace_settings` 用 `settings.model_copy(update=...)` 打开开关**：复用既有测试配置的
   业务库/账号/会话，避免复制一份易漂移的 fixture；配置字段本身的校验用直接 `Settings(...)` 覆盖
   （`test_middleware.py:485-553`）。
8. **未做（按范围）**：不埋业务 Span、不改 `qa/` / `rag/` / `conversations/`；不改
   `observability/{tracer,store,contracts,versioning}.py`；不改既有测试；不新增依赖；不实现
   `redacted`/`full`；不实现 Trace 保留期 purge / 导出 CLI（后续任务）；不做 P95 写入延迟实测
   （留给 T003c/d 全链路后统一评估）；不 push。
9. **工作树中非本包改动**：开工时已存在的 PM `_index.md` 修改与 `T001/T002/T003a` handoff/review、
   `prompts/`、`evidence/verify/` 等未跟踪文件未修改 / 未清理 / 未 commit；本包 commit 只含交付物。
10. **证据 05/06 的 amend 机制**：见 §3（单 commit 无法记录自身 sha）。

## 5. 风险与遗留

- **T003c/d 必须补齐业务字段**：不调用 `set_question` / `set_request_id` / `set_path` / `set_outcome`
  时，记录会停在 `status=incomplete`、`question_hash=None`；HMAC key（本包已传）也只有在
  `set_question` 后才会生效（`hash_question` 口径）。
- **`path` 默认值**：埋点前为 `rag`（内核默认）；T003c/d 必须按 `_rag_owns_turn` 设置真实 path
  （尤其 legacy / legacy_with_rag_candidates），否则 gate 的路径感知完整性会误判。
- **路径正则与 API 前缀耦合**：`main.py:38` 是唯一匹配点（`/api/v1/...`）；若未来改前缀需同步该常量，
  本包测试会兜底（`test_middleware.py:446` 静态 + `:305` 行为）。
- **QA POST 端点内失败请求也写 trace**（鉴权失败 / 422）：是“按执行入口观测”的取舍；如噪音不可接受，
  待 outcome 埋点后按 status/outcome 过滤。
- **同步 SQLite 写**：每个 QA POST 一次单事务（WAL，T002 已验收）；写入失败仅记日志。P95 增量需在
  T003c/d 埋点后实测；若偏高，P1 可换批量/异步 exporter（不改本包 API）。
- **Windows 文件句柄**：TraceRepository 的 SQLite 连接在 lifespan/fixture 显式关闭；生产 uvicorn
  shutdown 会触发 lifespan。`trace_enabled=True` 且 `initialize=False` 时构造期即建库（“开启即副作用”），
  如未来需要只读 OpenAPI 构建可再延迟创建。
- **HMAC key 的内存暴露面**：`SecretStr` 只保护 repr/序列化；`trace_hmac_key_bytes` 会返回明文 bytes
  供 tracer 使用，调用方（本包中间件）不得打印/记录该值；本包已在测试中验证它不落库/不进响应/不进异常。
- **既有测试的时序敏感用例**：`test_chat.py::test_g08_short_budget_cancels_inflight_model_call` 依赖
  0.2s 预算下的调度时序；在本机与后台全量测试并行采集时曾出现过 1 次环境性失败（模型调用 0 次），
  空闲复跑 239 passed、全量 1196 passed；本包未改该用例与相关业务代码。

---

## 交接摘要（≤10 行）

1. 交付物：`config.py`（+76：`trace_enabled/trace_db_path/trace_content_mode/trace_hmac_key` + 校验 + 2 属性）、`main.py`（+42：`TRACE_MODE=TraceMode.LOCAL`、QA POST `start_trace` 包裹 + `X-Trace-ID`、`app.state.trace_repo` 条件创建/lifespan 关闭）、新增 `tests/observability/{conftest.py(151), test_middleware.py(565, 20 tests)}`、证据 00–06、本报告。
2. §5.1 默认关闭零副作用：`config.py:116`、`main.py:101,125,135`；`test_middleware.py:138,150`（spy 证 start_trace 未被调用、无 DB/目录、无 `X-Trace-ID`、`X-Request-ID` 不变）。
3. §5.2 开启落 trace：`main.py:101,135-148`；`test_middleware.py:183,192,223`（UUID 头、`http_request_id` 对齐、mode=local、scope=end_to_end、content_mode=hash、spans=[]、request_id=None、status=incomplete）；`:265` contextvars 对 handler 可见。
4. §5.3 范围只限 QA POST：`main.py:33-43,135`；`test_middleware.py:305`（登录/健康/会话 CRUD/上传 6 类请求零头零 trace；QA POST 正对照 1 条）。
5. §5.4 写入失败不影响产品：`test_middleware.py:353`（monkeypatch 抛异常：200、无泄漏、`trace_finish_error`、无半条）、`:375`（库不可写：200、`trace_write_error`）。
6. §5.5 行为不变：`test_middleware.py:409`（off vs on body 归一化完全一致，仅多 `X-Trace-ID`）；证据 03/04 全绿。
7. §5.6 mode 硬约束：`main.py:30-33,138`；`test_middleware.py:446`（AST 静态绑定 `TraceMode.LOCAL`、全文件无 LIVE）、`:237`（运行时 `mode is TraceMode.LOCAL`）。
8. §5.7 配置安全：`config.py:113-125,169-207,335-355`；`test_middleware.py:485,494,507,522,531,541`（env 开关、off/hash 白名单、SecretStr 掩码、异常/日志/库不泄漏、无 key→sha256 文档）。
9. 实际运行：证据 02 = 20 passed；03 = 239 passed；04 = **1196 passed**（基线 1176 + 20，0 failed/0 error）；C1 = `20f0105`（9 文件/1602 插入），证据 05 为 amend 后重采 stat（与最终 HEAD 仅首行自引用 sha 不同），最终 HEAD 短 sha 见 `git log -1 --format=%h`；交付物 SHA-256 见证据 06。
10. 偏离/风险：`request_id` 本包为 None、`path` 用内核默认 RAG 且 `status=incomplete`（T003c/d 必须补 `set_request_id/set_path/set_outcome/set_question`，HMAC key 才生效）；QA POST 端点内鉴权/422 失败也写 incomplete trace；未埋 Span、未改业务代码/内核/既有测试、未新增依赖、未 push。

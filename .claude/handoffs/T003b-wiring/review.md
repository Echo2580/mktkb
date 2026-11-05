# T003b 独立验收报告（配置 + 中间件接线）

> 角色：独立验收者（与开发助手不共享上下文）。本报告只认本人复跑/独立探针结果；
> 开发报告（`.claude/handoffs/T003b-wiring/report.md`）仅作线索，不作为 PASS 依据。
> 验证对象：分支 `p0/obs-eval`，commit `d41d19fde15684b67c7c2034cb7b8ddda634f0e9`（`d41d19f`，
> `p0/T003b config & middleware`，parent `dea4d5d`）；基线 `main` @ `8e44158`。
> 验收时间：2026-11-05 01:12–01:55（Asia/Shanghai）；Windows / PowerShell 5.1 / Python 3.12.7 / pytest 9.1.1。
> 复跑证据：`docs/reports/OBS-EVAL/P0/evidence/verify/T003b/`（本报告引用的 00–13c 文件均在该目录）。

## 0. 结论（逐条）

| # | 验收项 | 判定 | 一句话依据 |
| --- | --- | --- | --- |
| §5.1 | 默认关闭零副作用、`X-Request-ID` 不变 | **PASS** | 独立探针 P1：无 `X-Trace-ID`、无 trace repo/目录/DB、`X-Request-ID` 为 36 位 UUID；`main.py:101,125,135`、`config.py:116` |
| §5.2 | 开启后 `X-Trace-ID` 为 UUID 且能查到 trace | **PASS（带边界说明）** | 独立探针 P2：UUID 头、`repo.get` 命中 1 条、`http_request_id` 对齐、mode=local/scope=end_to_end/content_mode=hash；`request_id=None`、`path=rag`、`status=incomplete` 属 T003c/d 前边界（见 §6） |
| §5.3 | 范围只限 QA POST | **PASS（带观测）** | 独立探针 P3：OpenAPI 枚举 21 个非 QA 端点方法（登录/健康/会话 CRUD/上传/登出等）全部无头、库 0 行；非精确路径变体（尾斜杠/多段/GET）也无 trace；QA POST 正对照有头写行。端点内失败（401/422）也会写 incomplete trace，属端点上观测的已知取舍（报告 §4.3 属实，见 §7） |
| §5.4 | 写入失败不影响产品、不泄漏 | **PASS** | 独立探针 P4a（monkeypatch 抛异常）：200、正常 body、无内部痕迹、无半条 trace、日志 `trace_finish_error`；P4b（父路径是文件不可写）：create_app 不崩、200、正常 body、无泄漏、日志 `trace_write_error`、不建 DB |
| §5.5 | trace 开/关 body 归一化一致 + 既有 integration 全绿 | **PASS** | 独立探针 P5：固定 `client_request_id`，归一化后 body 完全一致、键集合一致、唯一差异是开侧多 `X-Trace-ID`；`integration/test_chat.py`、`test_answer_commit.py` 在范围套件（239 passed）与全量复跑（1196 passed）中全绿 |
| §5.6 | 中间件不传 `TraceMode.LIVE`（源码+运行时） | **PASS** | `main.py:31-33,138`；独立 AST 断言：全 `src` 无 `TraceMode.LIVE` 使用点、`start_trace` 唯一调用、mode 静态绑定 `TraceMode.LOCAL`；运行时 spy：`mode is TraceMode.LOCAL`、` != LIVE`、落库 `mode="local"` |
| §5.7 | 配置安全/默认值/白名单/SecretStr 不泄漏 | **PASS** | `config.py:113-125,169-207,335-355`；独立探针 P6：默认值正确、旧字段 `Settings` 构造不受影响、`off/hash` 接受且 `redacted/full/sampled/''/live` 拒绝、SecretStr 掩码、repr/JSON/异常/日志/DB 均不含 key、无 key→sha256 文档在 `config.py:122-124` 与 tracer 文档 |
| §5.8 | 全量 `backend/tests` 无新增失败 | **PASS（带 flake 说明）** | 干净复跑 `03b-pytest-full-rerun.txt`：**1196 passed, 0 failed**（559.90s）；基线 `dea4d5d` collect-only **1176 tests**（+20 = 1196）。首轮全量有 1 个既有时间敏感用例失败（见 §8），非本包引入 |
| — | 提交边界（只含 handoff §2 允许路径） | **PASS** | `git show --name-only d41d19f` 12 个文件全部在允许清单内；`qa/rag/conversations/`、observability 内核、既有测试、pyproject、docs/evidence、var、fixtures 均未触碰；无删除行 |
| — | 硬约束（无新依赖/零真实调用/不读 .env/API 结构不变） | **PASS** | 无依赖文件变更；新增 import 仅 `re`（stdlib）与仓库内 observability；socket 守卫下 QA 路径 200 且无外部连接；新增代码无 `.env/os.environ` 读取；OpenAPI 规范与基线逐字节一致（22 operations、18 paths） |
| — | 报告质量（五段格式/引用可核对） | **PASS（附 minor 不精确）** | 五段+交接摘要齐全；关键命令/通过数/12 文件 stat 与本人复跑一致；amend 链描述不完整（见 §9） |

**总判定：PASS（可进入人工审核门）。** 无 FAIL/BLOCKED 项；§5.2/§5.3/§5.8 各有一条已在开发报告声明的边界/环境情况，均不构成本包越界或新增缺陷，详见 §6–§8。

## 1. 验收方法与独立性声明

1. 全程只读验证：未修改任何交付物/代码/测试；未 commit/push；未改 `_index.md`。本人产物只有
   本 `review.md` 与 `docs/reports/OBS-EVAL/P0/evidence/verify/T003b/` 下的复跑证据（均未跟踪、未提交）。
2. 亲自复跑 handoff §6 的全部命令（前缀 `$env:MKTKB_PROJECT_TOTAL_LIMIT_CNY="20.0"`，
   `.\.venv\Scripts\python.exe -B -m pytest ... -q -p no:cacheprovider --basetemp ...`），
   输出原文见证据 `01/02/03/03b`（证据文件为 UTF-8，末尾有 `exit_code=` 行）。
3. 独立编写 4 个探针/审计脚本（不 import `test_middleware.py`）：
   - `probe_independent.py`：131 条独立行为断言（PASS 131 / FAIL 0），覆盖 §5.1–§5.7 与零外部调用；
   - `probe_mutation.py`：仓库外副本变异探针（7 组，全部 DETECTED）；
   - `probe_openapi.py`：目标 vs 基线（`git archive dea4d5d` 解出的副本）OpenAPI 对比；
   - 少量一次性边界探针（响应头基线对比、QA POST 422、关闭+显式路径）。
4. 关键事实均同时从源码（`文件:行`）与运行时行为两个方向核对；开发报告中的数字/行号仅用于对照，
   发现不一致处见 §9。

## 2. 实测命令与结果（handoff §6）

环境：`git branch --show-current` → `p0/obs-eval`；`git rev-parse --short HEAD` → `d41d19f`
（handoff 中 "应为 dea4d5d" 是开发开工基线；开发证据 00 也是 `p0/obs-eval` + `dea4d5d`）。
每命令前设 `MKTKB_PROJECT_TOTAL_LIMIT_CNY=20.0`、`PYTHONIOENCODING=utf-8`。

```powershell
# ① 本包测试
.\.venv\Scripts\python.exe -B -m pytest backend/tests/observability/test_middleware.py -q -p no:cacheprovider --basetemp backend\.pytest-tmp\verify-t003b-mw
# → 20 passed, 1 warning in 8.19s   （证据 01-pytest-middleware.txt，exit 0）

# ② handoff §6 范围套件
.\.venv\Scripts\python.exe -B -m pytest backend/tests/observability backend/tests/integration/test_chat.py backend/tests/integration/test_answer_commit.py -q -p no:cacheprovider --basetemp backend\.pytest-tmp\verify-t003b-scope
# → 239 passed, 1 warning in 90.60s （证据 02-pytest-scope.txt，exit 0）

# ③ 全量（首轮，机器上有本人轻量并行命令）
.\.venv\Scripts\python.exe -B -m pytest backend/tests -q -p no:cacheprovider --basetemp backend\.pytest-tmp\verify-t003b-full
# → 1 failed, 1195 passed in 559.21s（证据 03-pytest-full.txt，exit 1）
#   唯一失败 = backend/tests/integration/test_chat.py::test_g08_short_budget_cancels_inflight_model_call
#   AssertionError: assert 0 == 1（模型调用 0 次；该用例 monkeypatch BUDGET_SECONDS=0.2 的时间竞争，见 §8）

# ④ 全量（干净复跑，无并行操作，前台独占）
.\.venv\Scripts\python.exe -B -m pytest backend/tests -q -p no:cacheprovider --basetemp backend\.pytest-tmp\verify-t003b-full-rerun
# → 1196 passed, 1 warning in 559.90s（证据 03b-pytest-full-rerun.txt，exit 0）

# ⑤ 提交 stat
git show --stat --oneline HEAD
# → d41d19f p0/T003b config & middleware；12 files changed, 1838 insertions(+)（证据 04-commit-boundary.txt）
```

补充独立基线计数：`git archive dea4d5d` 解出副本后 `pytest backend/tests --collect-only -q`
→ **1176 tests collected**（证据 09-baseline-collect.txt），与 1196 − 20（新增 test_middleware 测试）一致。

## 3. 逐条独立核验明细（源码 + 运行时）

### §5.1 默认关闭零副作用 — PASS

- 源码：`backend/src/mktkb/config.py:116`（`trace_enabled: bool = False`）、`:119`（`trace_db_path=None`）、
  `:121`（`trace_content_mode="hash"`）、`:125`（`trace_hmac_key=None`）；
  `backend/src/mktkb/main.py:99-101`（仅 `settings.trace_enabled` 时构造 `TraceRepository`，否则 `None`）、
  `:125`（`app.state.trace_repo = trace_repo`）、`:135`（`trace_repo is not None and _is_qa_post(request)` 才启动 trace）、
  `:150-152`（原路径只加既有 `X-Request-ID`）。
- 独立探针 P1（`05-probe-independent.txt`）：关闭态应用 QA POST 200、无 `X-Trace-ID`、有 `X-Request-ID`
  （36 位 UUID 形态）、body `kind=not_found`；**未创建 `<data_dir>/observability/`、无 trace DB 文件**；
  额外探针 `13c-disabled-with-explicit-path.txt`：即使显式配置 `trace_db_path`，关闭时也**不建目录/不建库、
  `app.state.trace_repo is None`、无 `X-Trace-ID`**。
- 非空转证据：变异 M1（`config.py` 默认改 `True`）→ 开发测试 2 条 §5.1 用例失败（`06-mutation-probes.txt`）；
  变异 M6（非 QA 分支也加 `X-Trace-ID`）→ §5.1/§5.3 用例失败。

### §5.2 开启后落 trace — PASS（带边界说明）

- 源码：`main.py:101`（按 `settings.resolved_trace_db_path` 建仓储）、`:132`（`request.state.trace_id` 供后续包）、
  `:135-149`（`start_trace(..., mode=TRACE_MODE, scope=TRACE_SCOPE, content_mode=settings.trace_content_mode, hmac_key=settings.trace_hmac_key_bytes)` + 响应头 `X-Trace-ID`）；
  `config.py:335-343`（默认 `<data_dir>/observability/qa-traces.sqlite3`）、`:346-354`（HMAC bytes 仅内存）。
- 独立探针 P2（`05-probe-independent.txt`）：`X-Trace-ID` 为合法 UUID；`repo.get(trace_id)` 命中一条；
  `http_request_id == X-Request-ID`；`mode="local"`、`scope="end_to_end"`、`content_mode="hash"`、
  `replayed=False`、`attempt=1`、`spans=[]`；一次 QA POST 恰一行，两次 POST 两行且 id 不同；
  未显式给 `trace_db_path` 时按默认路径建库；`content_mode="off"` 跟随配置落库。
- 运行实测记录（P2）：`request_id=null, path="rag", outcome_kind=null, status="incomplete", question_hash=null`。
  这些是 T003b 边界内的预期（handoff §5.2 明示 spans 允许为空；业务字段属 T003c/d），**不是伪造数据**：
  T003b 未解析 request body、未 set 任何业务字段。边界解释见 §6.1–6.3。

### §5.3 范围只限 QA POST — PASS（带端点内失败观测）

- 源码：`main.py:36-38`（正则 `^/api/v1/conversations/[^/]+/messages$`）、`:41-43`（method==POST 且路径 fullmatch）、
  `:135`（唯一启动点）；正则只匹配精确路径（不含查询串）。
- 独立探针 P3（`05-probe-independent.txt`）：从 OpenAPI 枚举 **21 个非 QA 端点方法**（登录 POST、`GET /healthz`、
  会话列表/创建/消息 GET、上传 POST、登出 POST 等）逐一发未认证请求：**全部无 `X-Trace-ID`、Trace 库 0 行**；
  已登录的非 QA 端点（含 multipart 上传）同样无头、库 0 行；非精确变体
  （`POST .../messages/`、`POST .../messages/extra`、`GET .../messages`、`POST /api/v1/other/messages`、
  `POST .../messagesx`）也全部无 trace（尾斜杠变体用 `follow_redirects=False` 验证为 307、不启动 trace）。
  随后 QA POST 正对照：有头、库 1 行；再一条正常 QA POST → 2 行。
- 端点内失败（已登录/未登录的 QA POST 401、参数校验 422）**也会**写 incomplete trace：见 §7 偏离判断。

### §5.4 写入失败不影响产品 — PASS

- 中间件本身不 try/except、不改写响应（`main.py:135-152`）；写入走内核 best-effort
  （`observability/store.py:203-213` 捕异常记 `trace_write_error`；`observability/tracer.py:535-555` finish 兜底并记
  `trace_finish_error`——均为 T001–T003a 已验收只读内核，本包未改）。
- 独立探针 P4a（对象方法 monkeypatch 抛 `RuntimeError`）：QA POST 仍 200、body 正常、仍带 `X-Trace-ID`、
  响应无 `trace_write_error/TraceWriteError/RuntimeError/Traceback/sqlite` 等内部痕迹、Trace 库 0 行（无半条）、
  日志命中 `trace_finish_error`。
- 独立探针 P4b（`trace_db_path` 父路径是普通文件→不可写）：`create_app` 不抛异常、QA POST 200、body 正常、
  无泄漏标记、仓储日志命中 `trace_write_error`、不创建 DB 文件。
- 非空转：变异 M5（把 tracer.finish 的写入兜底删掉，让异常冒到响应）→ `test_monkeypatched_write_failure_keeps_qa_response` 失败。
- 说明：开发测试对 "monkeypatch 抛异常" 断言的是内核 `trace_finish_error`，对 "路径不可写" 断言 `trace_write_error`；
  与 handoff §5.4 "日志有 trace_write_error" 的字面分工一致（两种失败路径各命中一次），且都不影响产品。

### §5.5 行为不变 — PASS

- 独立探针 P5（`05-probe-independent.txt`）：off/on 两个独立数据目录、同一固定 `client_request_id`、
  同一固定问题：状态码一致 200；响应 body 归一化（去 `request_id/message_id/conversation_id/created_at/updated_at`）
  后**完全一致**、键集合一致（`kind/text/revision/sources/candidates/conflicts/missing_fields/pagination/error_code/retryable`）；
  off 无 `X-Trace-ID`、on 有；两边都有既有 `X-Request-ID`。
- 基线响应头对照（`13-baseline-headers.json`，基线 `dea4d5d` 副本）：QA POST 头集合
  `content-length/content-type/x-request-id`；目标关闭态一致，开启态只多 `x-trace-id`——API 兼容性符合 §10。
- 既有 integration：`02-pytest-scope.txt`（239 passed，含 `test_chat.py`/`test_answer_commit.py`）与
  `03b-pytest-full-rerun.txt`（1196 passed）全绿。

### §5.6 mode 硬约束 — PASS

- 源码：`main.py:31-33`（`TRACE_MODE = TraceMode.LOCAL`，注释写明 P0 禁止 live、不按 provider 模式分支）、
  `:138`（`mode=TRACE_MODE`）；`main.py` 全文件无 `LIVE` 属性引用、无 `"live"` 字面量。
- 独立静态断言（P7）：`main.py` 仅 1 处 `start_trace` 调用；`mode` 是 `Name` 且模块级常量静态绑定
  `TraceMode.LOCAL`；全仓库 `backend/src` 仅 `observability/contracts.py:28` 定义 `LIVE`，**无任何使用点**。
- 独立运行时 spy（P7）：中间件恰好调用 1 次 `start_trace`，`mode is TraceMode.LOCAL`、` != TraceMode.LIVE`、
  `str(mode)=="local"`、`scope="end_to_end"`、`content_mode="hash"`、`repo is app.state.trace_repo`；
  落库记录 `mode="local"`。
- 非空转：变异 M3（`TRACE_MODE = TraceMode.LIVE`）→ 开发测试静态+运行时 2 条用例失败。

### §5.7 配置安全 — PASS

- 源码：`config.py:113-125`（4 字段默认值）、`:169-182`（`off/hash` 白名单，`redacted/full` 显式 ValueError，
  大小写/空白归一）、`:184-196`（`SecretStr`，空白归一 None）、`:198-207`（空白路径归一 None）、
  `:335-343`（默认路径解析）、`:346-354`（HMAC key→bytes，仅内存）、`config.py:122-124`（无 key→sha256 的说明）。
- 独立探针 P6（`05-probe-independent.txt`）：默认值；仅旧字段构造 `Settings` 成功；`hash/off/" HASH "/Off` 接受；
  `redacted/full/sampled/""/live` 全部 `ValidationError` 且信息含 off/hash；`SecretStr` repr/str/JSON 均无明文、
  掩码 `**********`、显式 `get_secret_value` 可取；配置校验失败异常文本不含 key；空白 key/路径归一；
  `MKTKB_TRACE_ENABLED=1`、`MKTKB_TRACE_HMAC_KEY`、`MKTKB_TRACE_DB_PATH`、`MKTKB_TRACE_CONTENT_MODE=off`
  环境变量均生效且 HMAC key 不进 repr/JSON；`Settings` 无任何 `trace_mode` 字段（无 live 配置入口）。
- HMAC 运行时泄漏检查（P2d）：Settings 带 key 开启 trace 后，key **不在响应文本/响应头/Trace DB 文件
  （含 -wal/-shm）字节/Trace 记录**中；配置异常不回显（P6）。
- 非空转：变异 M1（默认开启）→ 默认值用例失败；M4（开启后不生效）→ §5.2 用例失败。

## 4. 提交边界审计 — PASS

`git show --name-only --format='' d41d19f`（原文见 `04-commit-boundary.txt`）：

```text
.claude/handoffs/T003b-wiring/report.md                 # handoff §2 允许
backend/src/mktkb/config.py                             # handoff §2 允许
backend/src/mktkb/main.py                               # handoff §2 允许
backend/tests/observability/conftest.py                 # handoff §2 允许
backend/tests/observability/test_middleware.py          # handoff §2 允许
docs/reports/OBS-EVAL/P0/evidence/T003b/00..06          # handoff §2 允许（证据）
```

- 12 个文件全部落在 handoff §2 允许清单内；按禁止清单模式检查：`qa/`、`rag/`、`conversations/`、
  `observability/{tracer,store,contracts,versioning}.py`、既有测试、`pyproject.toml`、依赖锁、`docs/evidence/`、
  `var/`、`.env`、`fixtures/`、`_index.md` **均无命中**。
- `git diff --name-status dea4d5d d41d19f`：2 个修改（均为允许文件）+ 10 个新增（2 个测试/证据 + 报告），无删除；
  `git show --numstat` 全部删除列为 0。
- `dea4d5d..d41d19f` 恰 1 个 commit（T003b）；parent 正确。
- 工作树：`git status --backend` 为空；唯一 tracked 修改是开工前已存在的 PM `_index.md`（非本包 commit 内容）。
- 交付物 SHA-256 与开发证据 06 一致（独立复算：`16-sha256-recheck.txt`，4 个文件全 MATCH）。

## 5. 独立探针与变异探针结果

- `05-probe-independent.txt`：**131/131 PASS**（P1–P8，覆盖 §5.1–§5.7 + 零外部网络/模型调用）。其中
  `socket.socket.connect`/`create_connection` 守卫（仅放行 loopback）下 QA POST 仍 200 且落 1 条 trace；
  `model_gateway is None`、`ocr_gateway is None`。
- `06-mutation-probes.txt`：仓库外副本（`%TEMP%`）未变异副本 20 passed；6 组定向变异全部 **DETECTED**：
  | 变异 | 目的 | 触发失败用例 |
  | --- | --- | --- |
  | M1 默认 `trace_enabled=True` | 默认关闭不生效 | `test_settings_trace_defaults...`、`test_disabled_app...` |
  | M2 `_QA_POST_PATH` 放宽为全部 `/api/v1` | 错误路径也带头 | `test_only_qa_post_gets_trace_header...` |
  | M3 `TRACE_MODE = TraceMode.LIVE` | 传 live | `test_middleware_passes_local_mode...`、`test_middleware_source_hardcodes...` |
  | M4 中间件条件恒 False | 开启后不生效 | `test_enabled_qa_post_returns_uuid_trace_header...` |
  | M5 tracer.finish 不兜底写异常 | 写入失败抛给响应 | `test_monkeypatched_write_failure_keeps_qa_response` |
  | M6 非 QA 分支也加 `X-Trace-ID` | 错误路径仍带头 | `test_disabled_app...`、`test_only_qa_post...` |
  （变异仅在 `%TEMP%` 副本；仓库内文件未改动。）
- `07-openapi-*.json` / `07-openapi-compare-result.txt`：基线 `dea4d5d` 与目标 `d41d19f` 的 OpenAPI 规范
  canonical JSON **逐字节一致**（18 paths / 22 operations / components/info 相同，sha256 相同
  `4977ee76…b107`）；目标规范文本不含 `X-Trace-ID` 与 trace 配置字段。API 请求参数/响应 body 结构未变。
- 边界探针：`13b-edge-422.txt`（已登录 QA POST 缺 question / 非法 client_request_id → 422，仍带 `X-Trace-ID`，
  写 2 条 incomplete trace）；`13c-disabled-with-explicit-path.txt`（关闭 + 显式 trace 路径零副作用）。

## 6. 开发报告"偏离"逐条判断（是否越界）

1. **`request_id=None`**：产品请求 ID 是 `ConversationRequest.id`，在 `conversations/service.py` 内产生；
   中间件不解析 body 是 T003b 明确边界（handoff §1/§2/§7 业务 Span 属 T003c/d）。**不越界**；
   但 trace 记录因此不是业务完整记录，**T003c/d 必须 `set_request_id`**。若 PM 要求 T003b 的 trace
   就带 request_id，则需另立任务——按现 handoff 不构成 FAIL。
2. **`path` 用内核默认 `TracePath.RAG`**：`start_trace` 默认参数（`tracer.py:684`），中间件未显式传 path、
   也未 annotate 启动字段（符合 handoff §7"不主动 annotate 启动字段"）。**不越界**；但这是**数据语义风险**：
   埋点前所有记录都会声称 path=rag，若真实走 legacy 路径会误导后续 gate。报告中已把"T003c/d 必须 set_path"
   列为遗留（report §5）。建议 T003c/d 第一批断言 `set_path` 必被调用。**非阻塞**。
3. **`status=incomplete`**：未埋 outcome + 未埋 Span 的内核预期语义（`tracer.py:609-621`），handoff §5.2
   已预告 spans 可空。**不越界**。
4. **QA POST 端点内失败（401/422/404）也写 incomplete trace**：记录仍在"只限 QA POST 端点"范围内
   （§5.3 只限制端点，不限制成败），且报告 §4.3 已声明该取舍。独立探针 `13b-edge-422.txt` 与 P3 复现：
   未登录/422 请求同样带 `X-Trace-ID` 并各写 1 条 trace。**不越界，但需下游注意**：按 trace 行数/状态统计
   请求量或 gate 完整性时要过滤失败请求（T003c/d 埋 outcome 后可收紧）。

## 7. 发现的问题（均非阻塞，按严重度）

1. **[中-数据语义/遗留] 埋点前 trace 的 `path` 恒为 `rag`**（来源 `tracer.py:684` 默认值，非中间件显式写入）。
   T003b 边界内可接受，但 T003c/d 若不 `set_path`，会把 legacy/legacy_with_rag_candidates 误标为 rag；
   建议 T003c/d 在 run-real 埋点中先覆盖 path，或在门禁中校验 path 与 `_rag_owns_turn` 一致。
2. **[低-观测噪音] QA POST 的 401/422 也写 trace**（`13b-edge-422.txt`）。报告已声明；若指标按 trace 计数需过滤。
3. **[环境-非本包] 既有时间敏感用例全量偶发失败 1/2（首轮 `03-pytest-full.txt`）**：
   `test_chat.py::test_g08_short_budget_cancels_inflight_model_call`，失败形态 `calls == 0`（0.2s 预算下
   模型调用未及调度）；该用例与业务代码在 `dea4d5d..d41d19f` 中**零改动**（`10-hard-constraints.txt` 第[6]节），
   隔离连跑 3/3 通过（`08-flaky-test-isolated.txt`），第二次干净全量 1196 passed。判定为环境时序 flake，
   非本包新增失败；开发报告 §5 风险也主动披露过同类现象。若 PM 对 §5.8 采用"任意一轮全量必须 0 failed"
   的严格口径，请以 `03b` 干净复跑为准并在人工审核中记录该 flake。
4. **[低-报告精确性]** amend 链实际为 3 次 amend：`20f0105`（9 文件/1602 插入）→ `0616492`（12/1835）→
   `5ce6999`（12/1838）→ `d41d19f`；报告 §3/§4.10 只描述了一次 amend。证据 05 首行是 `5ce6999`（最终 amend
   前一次），无法等于最终 HEAD；与最终 `git show --stat` 的差异除首行 sha 外还有末尾 `exit_code=0` 行
   （stat 主体逐字节一致，`12-report-accuracy.txt` [C]）。不影响交付/验收，仅为文档精度问题。
5. **[低-测试覆盖缺口（本人已补测通过）]** 开发测试未覆盖：
   (a) 中间件把 `settings.trace_hmac_key_bytes` 真正传给 `start_trace`（默认 fixture 断言 `hmac_key is None`）；
   (b) 开启且**未显式配置** `trace_db_path` 时走默认路径建库；
   (c) `trace_enabled=True` + `initialize=False` 构造即建库（报告 §5 已声明风险）。
   本人独立探针 P2/P2b/P2d 已通过；建议 T003c/d 后续补一条 hmac 端到端用例（set_question 后校验 key 指纹）。
6. **[低-证据精确性]** 开发 RED 证据（`01-pytest-red.txt`）为 15 failed + 3 errors = 18 个用例，而最终测试文件
   20 个（`test_trace_context_is_visible_inside_qa_handler`、`test_trace_hmac_key_from_env_is_secret` 未出现在
   RED 清单），说明 RED 后追加过测试；不违反验收标准，仅 TDD 证据不完整。

## 8. 未覆盖项 / 本验收的局限（NOT-RUN 与理由）

| 项 | 状态 | 理由 |
| --- | --- | --- |
| 基线 `dea4d5d` 全量测试重跑 | NOT-RUN（替代证据充分） | 基线只做 collect-only **1176** 计数；"无新增失败"由目标干净全量 1196 passed 0 failed + 既有测试零改动 直接证明（目标 0 failed ⇒ 不存在新增失败） |
| 生产 uvicorn 真实 lifespan/shutdown | NOT-RUN | 用 TestClient lifespan 验证了仓储关闭（`test_lifespan_closes_trace_repo`）；真实 uvicorn 进程级关闭未跑（T003b 范围外） |
| 并发/多 worker 下 trace 写入行数/唯一性 | NOT-RUN | T003b 只接线；并发写入属 T002 仓储已验收语义，未在本包范围 |
| HMAC 实际 `question_hash` 生成（含 key 指纹） | NOT-RUN | 需业务 `set_question`，属 T003c/d；本包只验证 key 传递到内存且不泄漏 |
| P95 写入延迟 | NOT-RUN | 报告 §5 已声明留给 T003c/d 全链路后评估；本包不构成验收项 |
| 真实 `.env` 加载路径 | NOT-RUN（按约束） | handoff 明确不读 `.env`；测试用 `_env_file=None` 隔离（既有 conftest autouse 亦隔离），本人探针同样隔离 |
| 浏览器/前端读取 `X-Trace-ID`（CORS expose） | NOT-RUN（范围外） | 本应用无 CORS 中间件；P0 只要求新增响应头，未要求前端读取 |
| 首轮全量 flake 的第三方归因（CPU/IO 时间线） | NOT-RUN | 已用隔离 3/3 + 干净全量 1196 证明非本包引入；未做逐核调度级取证 |

## 9. 工作树与交付合规

- `git status --porcelain -- backend` 为空；`git diff --stat` 仅开工前 PM 的 `_index.md`（本包/本人未改）。
- 本人未 commit、未 push、未改 `_index.md`、未改任何交付物；`review.md` 与 `evidence/verify/T003b/`
  为本人新建的未跟踪文件（按任务要求不提交）。
- 提交边界/父提交/单 commit 约束通过（§4）。
- 备注：验证期间工作树出现 PM/Lead 并行创建的 T003c 交接文档（未跟踪，如 `.claude/handoffs/T003c-rag-spans/`、
  `prompts/T003c-*.md`），非 T003b commit 内容，与本次验收无关。

## 10. 证据索引（`docs/reports/OBS-EVAL/P0/evidence/verify/T003b/`）

| 文件 | 内容 |
| --- | --- |
| `00-context.txt` | 环境/分支/HEAD/基线 sha/venv/pytest 版本 |
| `01-pytest-middleware.txt` | §6① 本包测试 20 passed |
| `02-pytest-scope.txt` | §6② 范围套件 239 passed |
| `03-pytest-full.txt` | §6③ 全量首轮 1 failed/1195 passed（flake，原文） |
| `03b-pytest-full-rerun.txt` | §6③ 干净复跑 1196 passed（PASS 依据） |
| `04-commit-boundary.txt` | 提交文件清单/允许清单分类/无删除/依赖与 .env 未改 |
| `05-probe-independent.txt` | 独立探针 131 PASS/0 FAIL（含 P2 trace 字段原文） |
| `06-mutation-probes.txt` | 仓库外 6 组变异全部 DETECTED（M0 未变异 20 passed） |
| `07-openapi-baseline.json` / `07-openapi-target.json` / `07-openapi-compare-result.txt` | OpenAPI 逐字节一致 |
| `08-flaky-test-isolated.txt` | 争议用例隔离连跑 3/3 passed |
| `09-baseline-collect.txt` | 基线 `dea4d5d` 收集 1176 tests |
| `10-hard-constraints.txt` | 无新依赖/无 .env 读取/无凭据日志/仅新增响应头/既有测试未改 |
| `11-worktree-audit.txt` | 工作树 tracked 变更审计 |
| `12-report-accuracy.txt` | 报告数字/C1/evidence05/amend 链/偏离复现对照 |
| `13-baseline-headers.json` | 基线 `dea4d5d` 响应头集合对照 |
| `13b-edge-422.txt` | QA POST 422 也带头/写 incomplete trace（报告 §4.3 复现） |
| `13c-disabled-with-explicit-path.txt` | 关闭 + 显式 trace 路径零副作用 |
| `probe_independent.py` / `probe_mutation.py` / `probe_openapi.py` | 本人独立探针源码（可复跑、仓库外写） |

## 11. 最终结论

T003b（`d41d19f`）在本人独立复跑与独立探针下 **通过验收**：handoff §5.1–§5.8 全部满足，
提交边界与四项硬约束全部满足，开发报告中的三条"偏离"经独立复现均属 T003b 边界内且已在报告中声明，
未发现 FAIL 项。遗留关注点（path 默认 rag、失败请求也写 incomplete trace、时间敏感既有用例 flake）
已登记为 T003c/d / 人工审核注意事项，不影响本包通过。

**建议：进入人工审核门；T003c/d 派单时必须写入 `set_request_id`、`set_path`、`set_outcome`、`set_question` 的验收断言。**

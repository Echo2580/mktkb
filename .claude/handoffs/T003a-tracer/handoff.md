# T003a · tracer 内核（P0 第 3 包，最高风险任务的第一半）

> PM 任务单。基线：`p0/obs-eval` @ `2ac976f`（T001/T002 已通过独立验收）。本包**只新增观测内核**，不接业务代码。
> 完成后由全新上下文的独立验收助手按本文件逐条证伪。

## 1. 目标（一句话）

新增 `observability/tracer.py`：用 `contextvars` 实现请求级 `TraceContext` / `SpanHandle` / `start_trace` / `current_trace`，负责 Span 计时与状态、Trace 字段组装、`finish()` 走 `TraceRepository.write_best_effort`，并提供路径感知的 Span 完整性校验函数。

## 2. 交付物（只准写这些路径）

- 新增 `backend/src/mktkb/observability/tracer.py`
- 修改 `backend/src/mktkb/observability/__init__.py`（追加导出，不改既有导出语义）
- 允许在 `backend/src/mktkb/observability/contracts.py` **末尾追加**纯函数 `validate_required_spans(record, span_names) -> list[str]`（不改既有常量/类/函数；gate 后续要用；追加需在报告说明）
- 新增 `backend/tests/observability/test_tracer.py`
- 证据（入库）：`docs/reports/OBS-EVAL/P0/evidence/T003a/`
- 报告：`.claude/handoffs/T003a-tracer/report.md`（五段）

## 3. 输入（只看这些）

1. P0 设计 `docs/superpowers/specs/...design.md` §6.1（粒度/标识）、§6.3（Trace 字段）、§6.4（Span 名称与路径感知完整性）、§6.5（内容模式）、§6.6（写入语义）。
2. P0 计划 `docs/superpowers/plans/...p0.md` Task 3 的 Interfaces 段（`start_trace` 签名、`TraceContext` / `SpanHandle` 方法清单）。
3. 已验收代码（只读）：`observability/contracts.py`（`TraceRecord` 41 字段 / `SpanRecord` 9 字段 / `required_spans` / `conditional_required_spans` / 枚举）、`observability/store.py`（`TraceRepository.write_best_effort`）。

## 4. 允许 / 禁止

**允许**：§2 交付物；`git switch p0/obs-eval`；本包一个 commit。

**禁止**：
- 不接业务代码：不改 `main.py` / `config.py` / `qa/` / `rag/` / `conversations/`（接线是 T003b/c/d）。
- 不改 `store.py`、不改 `contracts.py`/`versioning.py`/`__init__.py` 的既有内容（只允许 §2 的追加）；不改既有测试。
- 不写原文/不落 SQL；不新增依赖；零真实模型/OCR/embedding/rerank 调用；不读 `.env`；不访问外网；不打印凭据。
- 不碰 `docs/evidence/**`、`var/**`、`fixtures/**`、账本/GO、归档区；不 push；不 commit PM 的未跟踪文件。
- 测试只写 `tmp_path`，不产生仓库内持久 DB。

## 5. 验收标准（逐条可判定）

1. `contextvars` 隔离：两个并发线程/嵌套 trace 各自独立，不串 trace_id/span；`current_trace()` 在无 trace 时返回 `None`。
2. `start_trace(...)` 生成唯一 `trace_id`；上下文退出时自动 `finish`（或测试显式 finish 一次，语义一致、幂等不重复写）。
3. `span(name, **attrs)`：嵌套 Span 的 `parent_span_id` 正确；退出时写 `duration_ms`、`status`（ok/error/异常时 error）、`attributes_json`（`ensure_ascii=False`）；未执行的 Span 不产生记录。
4. `set_request_id` / `set_question` / `set_path` / `set_outcome` / `annotate` 生效；**未设置 outcome 或 path 时**写 `status=incomplete`，不抛异常（设计 §6.6）。
5. `finish()` 调用 `TraceRepository.write_best_effort`；可用参数注入 repo（测试）；写入失败不抛、不中断调用方；未开启/无 repo 时全 API no-op 且不创建任何 DB 文件。
6. 内容模式：`content_mode` 至少实现 `off`（不存问题/答案，只有计数与 ID）与 `hash`（默认；问题/答案哈希 + 长度；HMAC 需 key，无 key 走 sha256）；`redacted`/`full` 不得在 P0 用于真实数据——若未实现，必须显式 fail closed 并在文档/报告写明。
7. `validate_required_spans(record, span_names)`：缺必需 Span 返回缺失清单；完整集合返回 `[]`；`rag + clarification` 不得误要求 `answer`；条件 Span 按属性集合判断。
8. 新增测试全过；`backend/tests` 全量相对 T002 基线（**1110 passed**）无新增失败。

## 6. 必须实际运行的检查（输出原文存证据目录）

```powershell
$env:MKTKB_PROJECT_TOTAL_LIMIT_CNY = "20.0"
git rev-parse --short HEAD   # 应为 2ac976f
```

```powershell
.\.venv\Scripts\python.exe -B -m pytest backend/tests/observability/test_tracer.py -q -p no:cacheprovider --basetemp backend\.pytest-tmp\obs-tracer
.\.venv\Scripts\python.exe -B -m pytest backend/tests/observability -q -p no:cacheprovider --basetemp backend\.pytest-tmp\obs-all
.\.venv\Scripts\python.exe -B -m pytest backend/tests -q -p no:cacheprovider --basetemp backend\.pytest-tmp\t003a-full
git show --stat --oneline HEAD
```

输出原文存 `docs/reports/OBS-EVAL/P0/evidence/T003a/<编号>-<name>.txt`。

## 7. 提交

分支 `p0/obs-eval`，一个 commit：`p0/T003a tracer core`；只 add 本包交付物；不 push。

## 8. report.md 格式（五段齐全）

同 T001/T002 格式：完成内容 / §5 逐条自证（命令或 文件:行）/ 实际运行结果（含 commit sha、stat）/ 偏离与未做 / 风险与遗留。末尾另给 ≤10 行交接摘要。

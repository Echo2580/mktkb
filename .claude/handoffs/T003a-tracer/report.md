# T003a 报告：tracer 内核（P0 第 3 包）

> 分支：`p0/obs-eval`（基线 `2ac976f`，T001/T002 已通过独立验收）；开发方：dev-t003a。
> 本报告是开发方自证，验收请以独立复跑结果为准（不采信本文件任何“已完成”结论）。
> 证据目录：`docs/reports/OBS-EVAL/P0/evidence/T003a/`。
> 范围：只新增观测内核，不接业务代码（接线是 T003b/c/d）。

## 1. 完成内容

新增 / 追加 4 个代码交付 + 证据 + 本报告（未改任何业务代码、`store.py`、依赖清单、账本/GO、归档区）：

| 文件 | 一句话 |
| --- | --- |
| 新增 `backend/src/mktkb/observability/tracer.py`（760 行） | `contextvars` 请求级 `TraceContext` / `SpanHandle` / `start_trace` / `current_trace`：Span 计时与状态、Trace 字段组装、内容模式（off/hash）、`finish()` 走 `TraceRepository.write_best_effort`、条件 Span 属性并入 `filter_decisions_json` |
| 追加 `backend/src/mktkb/observability/contracts.py`（+50 行，仅末尾追加） | 纯函数 `validate_required_spans(record, span_names) -> list[str]`（路径 + 属性感知 Span 完整性），既有常量/类/函数与 `__all__` 未改 |
| 修改 `backend/src/mktkb/observability/__init__.py`（+7 行，仅追加导出） | 追加 `SpanHandle` / `TraceContext` / `current_trace` / `start_trace` / `validate_required_spans` 导出，既有导出语义不变 |
| 新增 `backend/tests/observability/test_tracer.py`（1224 行，58 个测试函数 / 66 个用例） | 锁定 handoff §5 八条验收：contextvars 隔离 / 唯一 trace_id + 自动幂等 finish / Span 计时状态与 attributes / setter 与 incomplete / best-effort 写入与无 repo no-op / 内容模式与 fail closed / 路径感知完整性 / 导入边界 |
| 证据 `docs/reports/OBS-EVAL/P0/evidence/T003a/00–06` | 基线 rev-parse、TDD RED、本包 / observability / 全量 pytest 原文、提交 `git show --stat`、交付物 SHA-256 |

一句话：`start_trace(...)` 用 contextvar 建立一次执行尝试的 Trace，`span()` 记录嵌套阶段，
`finish()` 在退出上下文时把 `TraceRecord` + `SpanRecord` 交给独立 SQLite 的
`write_best_effort`（失败不抛、无 repo 不建库），并让 `off` / `hash` 两种内容模式与
`validate_required_spans` 的路径/条件规则可独立测试。

## 2. 验收标准自证（§5 逐条）

1. **contextvars 隔离** — `tracer.py:52-58`（两个 contextvar：当前 Trace + Span 栈）；`tracer.py:740-742`（无 Trace 返回 `None`）；`tracer.py:495-531`（Span 栈按进入/退出 push/pop，`_current_span_id` 见 `tracer.py:155-158`）；`tracer.py:727-737`（`start_trace` 进入时 set、退出时 reset，异常也 reset，并 `_SPAN_STACK.set(())` 隔断外层 Span 栈）。
   测试：`test_tracer.py:97`（无 trace 时 `current_trace() is None`）、`test_tracer.py:101`（20 次 trace_id 唯一 + 退出后 None）、`test_tracer.py:117`（两个并发线程各自 trace_id/Span 不串）、`test_tracer.py:169`（嵌套 trace 恢复外层上下文、各自只写自己的 Span）、`test_tracer.py:208`（内层 trace 不继承外层 Span 栈，两个根 Span `parent_span_id` 均为 None）。
2. **唯一 `trace_id` + 自动 finish / 显式 finish 幂等** — `tracer.py:711`（`uuid.uuid4().hex`）；`tracer.py:729-737`（`finally` 自动 `finish()`）；`tracer.py:535-547`（`finish` 先加锁置 `_finished`，重复调用直接 return，只写一次）。
   测试：`test_tracer.py:101`、`test_tracer.py:242`（退出上下文自动写 1 次）、`test_tracer.py:262`（显式 finish 两次 + 上下文退出仍只写 1 次）、`test_tracer.py:279`（异常退出仍 finish 并清理 contextvar）。
3. **`span(name, **attrs)`** — `tracer.py:495-531`（父 Span 取栈顶、异常写 status=error + 异常类型名并 re-raise、finally 写 `duration_ms`）；`tracer.py:303-372`（`SpanHandle` 与 `annotate`）；`tracer.py:623-644`（`SpanRecord` 组装，`attributes_json` 恒写 canonical JSON（无属性为 `{}`））；`tracer.py:121-153`（UTC ISO-8601 + 单调时钟整数毫秒 + `ensure_ascii=False, sort_keys=True`）。
   测试：`test_tracer.py:312`（duration 为非负 int、status=ok、中文属性 canonical 且无 `\uXXXX`）、`test_tracer.py:339`（sleep 50ms 后 `duration_ms`/`latency_ms` 均 ≥20，证明真实计时而非常量）、`test_tracer.py:373`（嵌套/兄弟 `parent_span_id` 与 Span 顺序）、`test_tracer.py:404`（Span 异常 → span/trace 双 error + error_code=ValueError）、`test_tracer.py:426`（未执行的 Span 不产生记录）、`test_tracer.py:358`、`test_tracer.py:445`、`test_tracer.py:465`、`test_tracer.py:486`（finish 后 no-op / Span 字段级 status 覆盖 / 已结束 Span 的 annotate 不落库）。
4. **setter / annotate 生效 + incomplete 不抛** — `tracer.py:429-492`（`set_request_id` / `set_question` / `set_path` / `set_outcome` / `annotate`，含 JSON 字段 canonical 化与保留字段校验）；`tracer.py:609-621`（status 计算：异常 > replayed > incomplete（缺 outcome 或 path）> error 结局 > ok）。
   测试：`test_tracer.py:505`（五个 setter + annotate 全字段生效）、`test_tracer.py:557`（枚举或等值字符串均接受）、`test_tracer.py:574`（默认 path=rag）、`test_tracer.py:587`（缺 outcome → `status=incomplete` 且不抛）、`test_tracer.py:605`（`path=None` → `incomplete` 且不抛）、`test_tracer.py:621`（finish 后 setter no-op）、`test_tracer.py:642`（未知/保留字段 ValueError）、`test_tracer.py:1078` 与 `test_tracer.py:1103`（trace status 语义与 replayed）。
5. **`finish()` 写入语义** — `tracer.py:535-555`（`repo.write_best_effort(record, spans)`；异常被捕获只记 `trace_finish_error`；组装异常记 `trace_assembly_error` 后放弃该条，同样不抛）；`tracer.py:548-549`（repo 为 None → 不写、不建库）；`tracer.py:495-513`（finish 后 span 为 no-op）。
   “未开启”口径：内核没有全局开关，由调用方（T003c 中间件按 `settings.trace_enabled`）决定是否调用 `start_trace`；未调用时 `current_trace()` 恒为 `None`，没有任何记录 API 会执行、也不会触碰 DB（`tracer.py` 顶层不 import `sqlite3`，AST 边界断言见 `test_tracer.py:1190`）。
   测试：`test_tracer.py:681`（只暴露 `write_best_effort` 的替身被调用且 Span.trace_id 正确）、`test_tracer.py:699`（替身抛异常不向调用方抛出，日志命中 `trace_finish_error`）、`test_tracer.py:717`（真实 `TraceRepository` 已 close 后不抛）、`test_tracer.py:297`（无 repo 时 `tmp_path` 为空——不创建任何 DB 文件）、`test_tracer.py:735`（真实 SQLite 回环：写后 `repo.get` 字段/Span/父子关系 `validate_required_spans == []`）、`test_tracer.py:787`（finish 时未关闭的 Span 被跳过并告警）。
6. **内容模式** — `tracer.py:61-65`（实现 off/hash；redacted/full 未实现集合）；`tracer.py:188-202`（非法/未实现 fail closed `ValueError`）；`tracer.py:262-300`（off 只存长度；hash 无 key → sha256、有 key → hmac-sha256 + `key_fingerprint` 指纹；key 永不落记录）；`tracer.py:204-211`（空 key 视为无 key）；默认 `hash`（`tracer.py:691`）。
   测试：`test_tracer.py:811`（默认 hash + sha256 摘要/长度、原文不在记录中）、`test_tracer.py:831`（HMAC 摘要 + `hmac_key_id` = key 指纹、key 不出现在记录）、`test_tracer.py:852`（空 key 退化为 sha256）、`test_tracer.py:868`（off 无摘要只有长度，记录与 Span 中无原文）、`test_tracer.py:894`（未设置问题四项为空）、`test_tracer.py:910`（redacted/full 显式 fail closed 且不留下 contextvar）、`test_tracer.py:922`（未知模式 fail closed）。
7. **`validate_required_spans(record, span_names)`** — 追加于 `contracts.py:199-245`：基础集合复用 T001 `required_spans`（`contracts.py:225`）；条件集合从记录任意 `*_json` 字段载荷的**顶层键**读取四个属性（`contracts.py:241`），复用 `conditional_required_spans`；缺 path/outcome → `ValueError`（`contracts.py:222`），单字符串入参 → `TypeError`（`contracts.py:216`）；返回排序后的缺失清单（`contracts.py:245`）。
   测试：`test_tracer.py:936`（缺 Span 返回排序清单）、`test_tracer.py:945`（完整集合返回 `[]`，多余 Span 不算缺失）、`test_tracer.py:953`（`rag+clarification` 完整集合 `["parse","commit"]`，不断言/不要求 `answer`）、`test_tracer.py:963`（`legacy_with_rag_candidates` 共用 legacy 规则）、`test_tracer.py:979`（`vector_enabled/expansion_triggered` 条件属性触发缺失）、`test_tracer.py:992`（条件属性为 false 不要求）、`test_tracer.py:1004`（`index_sync_performed` 从其它 JSON 字段读到时同样生效）、`test_tracer.py:1014`（设计未定义组合 fail closed）、`test_tracer.py:1020`（缺 path/outcome fail closed）、`test_tracer.py:1027`（单字符串入参 TypeError）、`test_tracer.py:1032`（tracer 的 `annotate(vector_enabled=True)` 并入 `filter_decisions_json` 后能被完整性校验读到）、`test_tracer.py:1058`（无既有 filter decisions 时也能并入）。
8. **新增测试全过、全量无新增失败** — 本包 `66 passed`（证据 `02`）；`backend/tests/observability` `158 passed`（证据 `03`，T001+T002 的 92 + 本包 66）；`backend/tests` `1176 passed, 1 warning`（证据 `04`）＝ T002 基线 1110 + 本包 66（58 个测试函数 − 2 个 parametrize 函数 + 2+8 组参数 = 66 用例），0 failed / 0 error。

## 3. 实际运行的命令与结果

环境：Windows / PowerShell 5.1、Python 3.12.7（`.venv`）、SQLite 3.45.3、pytest 9.1.1；每条命令前设
`$env:MKTKB_PROJECT_TOTAL_LIMIT_CNY = "20.0"`，解释器 `.\.venv\Scripts\python.exe -B`。
证据采集用 `cmd /c` + `PYTHONIOENCODING=utf-8` 原始重定向（本机 PowerShell 5.1 的 `*>` 默认写
UTF-16LE），全部证据为 UTF-8 无 BOM 文本，并在末尾追加 `exit_code=` 行。

```powershell
# 开工基线（证据 00）
git rev-parse --short HEAD
# → 2ac976f

# TDD RED：先写测试、确认失败（证据 01，测试首版；随后补充到 66 用例）
.\.venv\Scripts\python.exe -B -m pytest backend/tests/observability/test_tracer.py -q -p no:cacheprovider --basetemp backend\.pytest-tmp\obs-tracer-red
# → ImportError: cannot import name 'SpanHandle' from 'mktkb.observability'（1 error during collection，exit 2）

# 实现后：本包测试全过（证据 02）
.\.venv\Scripts\python.exe -B -m pytest backend/tests/observability/test_tracer.py -q -p no:cacheprovider --basetemp backend\.pytest-tmp\obs-tracer
# → 66 passed, 1 warning in 0.29s（exit 0）

# observability 目录（证据 03）
.\.venv\Scripts\python.exe -B -m pytest backend/tests/observability -q -p no:cacheprovider --basetemp backend\.pytest-tmp\obs-all
# → 158 passed, 1 warning in 2.10s（exit 0）

# 全量回归（证据 04）
.\.venv\Scripts\python.exe -B -m pytest backend/tests -q -p no:cacheprovider --basetemp backend\.pytest-tmp\t003a-full
# → 1176 passed, 1 warning in 396.40s (0:06:36)（exit 0；T002 基线 1110）

# 提交与提交后元信息（证据 05）
git commit -m "p0/T003a tracer core"
# → [p0/obs-eval 826aa33] p0/T003a tracer core
#    9 files changed, 2116 insertions(+)
git show --stat --oneline HEAD
# → 826aa33 p0/T003a tracer core；tracer.py 760 行、test_tracer.py 1224 行、
#    contracts.py +50、__init__.py +7、证据 00–04（原文见证据 05）
```

**交付物 SHA-256（证据 06）**：

```text
98c0953321035c91eebb5a24ef285c1554e1d10f191844ae39bd1cc945c313c4  backend/src/mktkb/observability/tracer.py
f04c1b53bafccbbe50dfb05f72e63e91cff09143150918e3c5713d24e1a639c3  backend/src/mktkb/observability/contracts.py
ba642d169490ef737300511f93cb697cf66db2c9535c4c7c0641b36f5ff0f870  backend/src/mktkb/observability/__init__.py
62d8dd95084a0ca3e3ee95464a413be152cc9ce518afeb284b5b75b9c45e539e  backend/tests/observability/test_tracer.py
（其余为证据 00–05 自身哈希，见证据 06 原文）
```

**提交说明（单 commit 约束下的折中，与 T001/T002 同口径）**：代码 / 测试 / 证据 00–04 先提交为
C1′ = `826aa33`（9 文件、2116 插入）；证据 05（`git show --stat` 原文）、证据 06 与本报告在 C1′
之后采集，再 `git commit --amend --no-edit` 并入同一提交。单 commit 无法在自身内容里记录自身
sha，最终短 sha 见回复末尾交接摘要 / `git log -1 --format=%h`。
**证据编码说明**：全部证据由 `cmd /c` 原始重定向产生，UTF-8 无 BOM（`00` 首字节 `2a`，`01–04`
首字节为 CRLF/`.`），不含 UTF-16 乱码。

## 4. 偏离与未做

1. **`start_trace` 追加两个可选关键字参数**：`content_mode: str = "hash"`、`hmac_key: bytes | None = None`（在计划列出的 `repo` 之后追加，原计划调用形态完全兼容）。原因：内容模式的来源（`config.py` 的 `trace_content_mode` / `MKTKB_TRACE_HMAC_KEY`）属于 T003c/d 的接线范围，本包不能改 `config.py`；内核只接受显式注入，默认 `hash` + 无 key→sha256，保证行为确定且不读环境变量文件。
2. **`path` 类型放宽为 `TracePath | str | None = TracePath.RAG`**（默认仍是计划里的 `TracePath.RAG`）：仅为能表达 §5.4“未设置 path → status=incomplete”这一分支（显式传 `path=None`）；正常调用不受影响。
3. **条件 Span 属性的载体约定**：设计未规定四个条件属性落在 `TraceRecord` 哪个字段（41 字段里没有通用 attributes）。本包约定：`TraceContext.annotate(vector_enabled=.../rerank_enabled=.../expansion_triggered=.../index_sync_performed=...)` 会并入 `filter_decisions_json`（顶层键）；`validate_required_spans` 则宽松地从记录**任意 `*_json` 字段的顶层键**读取这四个属性，避免锁死 T003c/d 的字段选择。
4. **Trace `status` 语义补充**：设计只列“ok / replayed / error 等”。本包定为：未捕获异常 → `error`；`outcome_kind ∈ {error, service_error}` → `error`；`replayed=True` → `replayed`；缺 outcome 或 path → `incomplete`；其余 → `ok`（`tracer.py:609-621`，测试 `test_tracer.py:1078` 与 `test_tracer.py:1103`）。
5. **`finish()` 的兜底范围大于设计**：设计只要求“写入失败不抛”。本包对 `finish` 内的记录组装异常也捕获并记 `trace_assembly_error`（该条 Trace 放弃），并跳过未关闭的 Span（`trace_finish_with_open_spans` 告警），保证观测内核任何情况下不中断调用方。
6. **Span `annotate` 的字段级覆盖扩展**：`annotate(status=..., error_code=...)` 写 `SpanRecord` 字段（其余键写 `attributes_json`），供 T003c/d 标记“受控降级/软失败”的阶段；设计只说 annotate 追加属性，属本包扩展。
7. **`contracts.py` 的 `__all__` 未改动**：按 §2 只允许“末尾追加纯函数”且“不改既有常量/类/函数”，本包把函数追加在 `__all__` 之后、未改 `__all__`；因此 `from mktkb.observability import validate_required_spans` 可用（包级 `__init__.py:22,53` 已追加导出），但 `contracts` 的星号导入不包含它。若验收方要求，可另开任务补 `__all__`。
8. **TDD RED 证据口径**：证据 01 是测试首版（含 §5 全部断言、但尚未补 12 个加强用例）的采集结果；实现后补齐并复跑，最终以证据 02 的 66 passed 为准（与 T002 处理方式一致）。
9. **未做（按范围）**：不写/不改中间件、`main.py`、`config.py`、`qa/`、`rag/`、`conversations/`（T003b/c/d）；不实现 `redacted` / `full` 内容模式（显式 fail closed）；不新增依赖、不写 SQL、不改 `store.py` / `contracts.py` 既有内容 / 既有测试；不碰 `docs/evidence/**`、`var/**`、`fixtures/**`、账本/GO、归档区；测试只写 `tmp_path`；未 push。
10. **工作树中非本包改动**：开工时已存在的 PM `_index.md` 修改与 `T001/T002/T003a` handoff/review、`prompts/`、`evidence/verify/` 等未跟踪文件未修改/未清理/未 commit；本包 commit 只含交付物 + 证据 + 本报告。

## 5. 风险与遗留

- **内容模式注入依赖 T003c/d**：若 T003c/d 只按计划的旧签名调用而忘记传 `content_mode` / `hmac_key`，生产会一直走默认 `hash` + sha256（安全但配置不生效）；T003c/d 必须在 `start_trace` 显式传 `settings.trace_content_mode` 与解码后的 HMAC key，并在其报告中写明。
- **条件 Span 属性约定需 T003c/d 遵守**：用 `trace.annotate(vector_enabled=True, ...)`（或直接把四个键放进任意 `*_json` 字段）才能让 `validate_required_spans` 触发要求；若 T003c/d 用别的字段/结构，gate（Task 5）可能漏判条件完整性。
- **`finish` 吞掉组装异常是可用性选择**：若调用方传入非法 `filter_decisions_json` 文本，会记 `trace_assembly_error` 并丢失该条 Trace（不影响业务响应）；建议 T003c/d 只传 dict/canonical 文本。
- **同步 SQLite 写入延迟**：每个请求一次 best-effort 单事务写（WAL），T003 接入后应按设计 §13 实测 P95 增量；若偏高，P1 可改批量/异步 exporter，不改本包 API。
- **Span 属性序列化**：不可序列化对象会导致该 Span `attributes_json=None` 并告警（不抛）；建议 T003c/d 只传计数、字符串、稳定引用、布尔。
- **`_CONDITIONAL_SPANS` 是 `contracts` 私有常量**：本包在同包内引用（单一事实源）；若 T001 契约后续重命名该私有名，需同步 `tracer.py` 与 `contracts.validate_required_spans`。
- **毫秒精度**：`duration_ms` / `latency_ms` 为整数毫秒，亚毫秒阶段记 0；仅用于可观测性，不用于计费或 SLA 判定。
- **单 commit 自引用 sha**：见 §3 提交说明（C1′ = `826aa33`；本报告与证据 05/06 经 `--amend` 并入同一提交）。

---

## 交接摘要（≤10 行）

1. 交付物：新增 `observability/tracer.py`（760 行）、`tests/observability/test_tracer.py`（1224 行，58 函数/66 用例）；`contracts.py` 末尾追加 `validate_required_spans`（+50 行）；`__init__.py` 追加导出（+7 行）；证据 `docs/reports/OBS-EVAL/P0/evidence/T003a/00–06`；本报告。
2. §5.1 contextvars 隔离：`tracer.py:52-58,495-531,727-737,740-742`；`test_tracer.py:97,101,117,169,208`（无 trace=None、20 次唯一、两线程不串、嵌套恢复、内层不继承 Span 栈）。
3. §5.2 唯一 trace_id + 自动/幂等 finish：`tracer.py:711,729-737,535-547`；`test_tracer.py:242,262,279`（自动写 1 次、显式两次仍 1 次、异常退出清理 contextvar）。
4. §5.3 Span：`tracer.py:495-531,623-644,121-153`；`test_tracer.py:312,339,373,404,426,358,465`（canonical 中文属性、真实毫秒计时、父子关系、异常 error、未执行不落库、空属性 `{}`）。
5. §5.4 setter/incomplete：`tracer.py:429-492,609-621`；`test_tracer.py:505,557,574,587,605,621,642`（五 setter 生效、缺 outcome/path → incomplete 不抛、finish 后 no-op、保留字段 ValueError）。
6. §5.5 写入语义：`tracer.py:535-555,548-549,495-513`；`test_tracer.py:681,699,717,297,735,787`（只调 `write_best_effort`、失败不抛、无 repo 不建库、真实 SQLite 回环 + 完整性）。
7. §5.6 内容模式：`tracer.py:61-65,188-211,262-300,691`；`test_tracer.py:811,831,852,868,894,910,922`（默认 hash/sha256、HMAC+key 指纹、off 只存长度、redacted/full fail closed）。
8. §5.7 完整性校验：`contracts.py:199-245`；`test_tracer.py:936,945,953,963,979,992,1004,1014,1020,1027,1032,1058`（缺失清单/完整 `[]`/rag+clarification 不要求 answer/条件属性/未定义组合 fail closed）。
9. 实际运行：本包 66 passed（02）、observability 158 passed（03）、全量 **1176 passed**（04，基线 1110 + 66，0 failed/0 error）；证据 05 为 C1′=`826aa33` 的 `git show --stat`（9 文件 2116 插入）；交付物 SHA-256 见证据 06；最终 HEAD 见 `git log -1 --format=%h`（报告/05/06 经 amend 并入）。
10. 偏离/风险：`start_trace` 追加 `content_mode`/`hmac_key` 两个可选参数、`path` 放宽允许 None、条件属性载体约定为 `filter_decisions_json`、finish 兜底吞组装异常、Span annotate 支持 status/error_code 覆盖；内容模式注入与条件属性约定需 T003b/c/d 遵守；未 push，未碰业务代码/受保护路径。

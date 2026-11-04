# T002 报告：SQLite Trace 仓储（P0 第 2 包）

> 分支：`p0/obs-eval`（基线 `7b02f40`，T001 已通过独立验收）；开发方：dev-t002。
> 本报告是开发方自证，验收请以独立复跑结果为准。
> 证据目录：`docs/reports/OBS-EVAL/P0/evidence/T002/`。

## 1. 完成内容

新增 2 个交付文件 + 证据（未改任何业务代码、`pyproject` / 依赖清单、T001 契约文件与既有测试）：

| 文件 | 一句话 |
| --- | --- |
| `backend/src/mktkb/observability/store.py` | 纯 stdlib `sqlite3` 的 `TraceRepository`：WAL 建表（`schema_meta` / `traces` / `spans`，列名与 T001 冻结记录一一对应）、单事务写读回环、`write_best_effort`、按 request 列表、JSONL 导出、按天数/条数 purge |
| `backend/tests/observability/test_store.py` | 24 项测试锁定 handoff §5 八条验收（写读回环 / best-effort / 幂等+WAL / request 列表 / JSONL / purge / 参数化+并发 / 契约字段） |
| `docs/reports/OBS-EVAL/P0/evidence/T002/00–06` | 基线 rev-parse、TDD RED、本包/observability/全量 pytest 原文、提交后 `git show --stat`、交付文件 SHA-256 |

一句话：在不改业务代码、零真实模型 / OCR / embedding / rerank 调用、不读 `.env`、不联网的前提下，把 T001 冻结的 `TraceRecord` / `SpanRecord` 落到**独立于业务库**的 SQLite（`var/observability/qa-traces.sqlite3` 形态），并让「产品写入 best-effort、评测读写 fail loud」的边界可测试。

## 2. 验收标准自证（§5 逐条）

1. **写读回环** — `store.py:189-201`（`write` 单事务）、`:215-232`（`get`）、`:417-423`（按 dataclass 字段顺序取值）。
   `test_store.py:121` 断言 `get()` 返回的 `TraceRecord` 与写入对象**整体相等**、spans 按名称匹配且整体相等；
   `:137` 最小记录（其余字段 None/默认值）无损；`:152` span 缺 `span_id`/`trace_id` 时归一后往返。
   JSON 字段保持 TEXT 原样存取（`:51-121` DDL），`test_store.py:121` 用含中文的 `retrieval_counts_json` / `fact_gate_json` 证明**字符串逐字节相等**；导出用 `ensure_ascii=False`（`store.py:289`），`test_store.py:327-330` 断言中文原文落盘且无 `\uXXXX`。
2. **best-effort 不抛、`write` 抛** — `store.py:203-213`（捕获 `Exception` 后只记 `trace_write_error` 日志，日志只含 trace_id/request_id，不含正文）；
   `test_store.py:172`（`close()` 后调用不抛 + caplog 命中 `trace_write_error`，随后 `write` 抛 `TraceWriteError`）；
   `:185`（父路径是普通文件导致 sqlite 打不开：构造不抛、best-effort 不抛、`write` 抛）；
   `:202`（关闭后 `get`/`list_by_request`/`export_jsonl`/`purge` 均抛 `TraceWriteError`）。
   构造期容错见 `store.py:167-179`（库打不开延迟到首次操作；schema 版本不兼容例外，`:364-379` 直接 fail closed）。
3. **建表幂等 + schema_meta + WAL** — `store.py:51-121`（`CREATE TABLE/INDEX IF NOT EXISTS`）、`:364-379`（`INSERT OR IGNORE` 后回读校验 `trace_schema_version`）、`:355`（`PRAGMA journal_mode = WAL`）。
   `test_store.py:219` 连续 `TraceRepository(path).close()` 两次不抛、三张表存在、`schema_meta.trace_schema_version == TRACE_SCHEMA_VERSION`、`close()` 自身幂等；`:233` 用独立连接断言 `PRAGMA journal_mode` 实际为 `wal`；`:244` `PRAGMA table_info` 列名逐项等于 `TraceRecord`（41）/`SpanRecord`（9）字段；`:260` 库内版本不兼容时构造即抛 `TraceWriteError`。
4. **`list_by_request`** — `store.py:234-247`（`WHERE request_id = ? ORDER BY attempt ASC, rowid ASC`）。
   `test_store.py:280` 同一 request 的 attempt 1/2/3 全量返回且按 attempt 区分，另一 request 不受影响，未知 request 返回 `[]`。
5. **`export_jsonl`** — `store.py:249-294`：单读事务取全量 trace+spans，每行是 **`TraceRecord` 全字段 + 嵌套 `spans` 数组**，`ensure_ascii=False, sort_keys=True`，返回导出行数。
   `test_store.py:301` 断言返回值 == 行数 == 库内 trace 数 2、每行 `json.loads`、嵌套 spans 名称与数量、行字段集 = 41 字段 + `spans`、`since=now-2d` 过滤后只导出 1 条。
6. **`purge`** — `store.py:296-333`（`BEGIN IMMEDIATE` 事务内选 id → 先删 spans 再删 traces → 返回删除条数）、`:445-464`（天数与条数选择集合）。
   `test_store.py:349` 无参数返回 0 且不删；`older_than_days=7` 删 2 条并清掉其 spans；`keep_last=2` 删最旧 1 条（独立库避免干扰）；
   `:401` 两个条件同时给出时取并集（先到先清，返回去重条数 2，spans 全清）；`:433` 负值抛 `ValueError`。
7. **SQL 参数化 + 并发/重复打开** — 值一律 `?` 占位符（`store.py:43-48` 的 INSERT 由数据类字段常量生成列名/占位符，DDL 为常量字符串）；无 f-string / `%` 拼接 SQL 值。
   `test_store.py:448` 用 `"r1' OR '1'='1"` / `"t' OR '1'='1"` 做注入回环，查询不放大、表结构完好；`:474` 源码抽查无 `execute(f"` / `execute("%` / `executescript(f"` 等值拼接；`:491` AST 断言 store 只 import 标准库 + `.contracts`；`:520` 同文件两个并发连接写读互见、重开 schema 不坏；`:543` 两线程各自连接并发写 10 条无异常、条数正确。
8. **测试全过、无新增失败** — `pytest backend/tests/observability/test_store.py` → **24 passed**（证据 `02`）；`pytest backend/tests/observability` → **92 passed**（证据 `03`，T001 的 68 + 本包 24）；`pytest backend/tests` → **1110 passed, 1 warning in 313.39s**（证据 `04`）。相对 T001 基线 **1086 passed**（`docs/reports/OBS-EVAL/P0/evidence/T001/03-pytest-full.txt`）恰多 24 项，无 failed / error。

## 3. 实际运行的命令与结果

环境：Windows / PowerShell（本机 shell 为 Windows PowerShell 5.1）、Python 3.12.7（`.venv`）、SQLite 3.45.3；每条命令前
`$env:MKTKB_PROJECT_TOTAL_LIMIT_CNY = "20.0"`，解释器 `.\.venv\Scripts\python.exe -B`。
证据为命令 stdout/stderr 原文（统一 UTF-8 无 BOM 文本），见 `docs/reports/OBS-EVAL/P0/evidence/T002/`。

```powershell
# 开工基线（证据 00）
git rev-parse --short HEAD
# → 7b02f40

# TDD RED：先写测试、确认失败（证据 01）
.\.venv\Scripts\python.exe -B -m pytest backend/tests/observability/test_store.py -q -p no:cacheprovider --basetemp backend\.pytest-tmp\obs-store-red
# → ERROR collecting ... ImportError: cannot import name 'store' from 'mktkb.observability'（1 error, exit 2）

# 实现后：本包测试全过（证据 02）
.\.venv\Scripts\python.exe -B -m pytest backend/tests/observability/test_store.py -q -p no:cacheprovider --basetemp backend\.pytest-tmp\obs-store
# → 24 passed, 1 warning in 0.32s

# observability 目录（证据 03）
.\.venv\Scripts\python.exe -B -m pytest backend/tests/observability -q -p no:cacheprovider --basetemp backend\.pytest-tmp\obs-all
# → 92 passed, 1 warning in 2.00s

# 全量回归（证据 04）
.\.venv\Scripts\python.exe -B -m pytest backend/tests -q -p no:cacheprovider --basetemp backend\.pytest-tmp\t002-full
# → 1110 passed, 1 warning in 313.39s (0:05:13)

# 提交与提交后元信息
git commit -m "p0/T002 sqlite trace repository"
# → [p0/obs-eval b3e5337] p0/T002 sqlite trace repository
#    8 files changed, 1165 insertions(+)
git rev-parse --short HEAD
# → b3e5337
git show --stat --oneline HEAD
# → 原文见证据 05（b3e5337；store.py 464 行、test_store.py 630 行 + 6 个证据文件）
```

**提交说明（单 commit 约束下的折中，与 T001 同口径）**：代码 / 测试 / 证据 00–04、06 先提交为 C1′ = `b3e5337`（8 文件、
1165 插入）；`git rev-parse` / `git show --stat` 原文（证据 05）与**本报告**在 C1′ 之后采集，再
`git commit --amend --no-edit` 并入同一提交，因此最终 HEAD 是 C1′ 的 amend 版本（多出报告与证据 05 两个文件）。
单 commit 无法在自身内容里记录自身 sha，最终短 sha 见回复末尾交接摘要 / `git log -1 --format=%h`。

**证据编码说明**：本机 shell 为 Windows PowerShell 5.1，`Tee-Object` 默认落 UTF-16LE，初版证据被 git 识别为二进制；
已将全部证据转码为 UTF-8 无 BOM（文本内容不变）后 amend 进 C1′，故证据 05 的 stat 显示证据文件为文本行数而非 `Bin`。

## 4. 偏离与未做

1. **异常命名覆盖读路径**：计划只定义 `TraceWriteError`（写入失败）。本包在库不可用（已 `close()`、打不开、版本不兼容）时，
   `get` / `list_by_request` / `export_jsonl` / `purge` 也抛同一异常，便于调用方区分“空结果”与“库坏了”；未新增第二个异常类。
2. **构造期容错边界**：库打不开（父路径是普通文件、sqlite 拒绝打开）时 `__init__` 不抛、延迟到首次操作抛 `TraceWriteError`，
   以满足“产品写入 best-effort 不阻塞响应”；但 `schema_meta.trace_schema_version` 与当前契约不一致属于配置错误，
   构造期直接 fail closed 抛 `TraceWriteError`（计划 / handoff 未规定该边界）。
3. **未规定行为的选择**：`get(unknown)` 抛 `KeyError`；空/非法字符串参数抛 `ValueError`；`span_id` 缺省时由 store 生成
   `uuid4().hex`，`span.trace_id` 缺省归一为所属 trace；span 归属不一致、重复 `trace_id` 抛 `TraceWriteError` 且整条回滚。
4. **导出与保留期语义**：设计未规定 JSONL 行 schema，本包取「TraceRecord 全字段 + 嵌套 spans」；`created_at` 无法解析的记录
   在 `since` 过滤下不导出、在 `older_than_days` 下不按年龄清理（不能证明它旧），在 `keep_last` 排序中视为最旧；
   `older_than_days` 与 `keep_last` 同时给出时取并集（先到先清）。
5. **证据采集折中**：PowerShell 5.1 的 `Tee-Object` 默认 UTF-16LE，已转码为 UTF-8 后提交（见 §3 说明）；TDD RED 证据（01）是
   测试文件首版（含全部 §5 断言）的采集结果，随后新增 2 项自锁测试并复跑，最终 24 项以证据 02 为准。
6. **单 commit 自引用 sha**：见 §3 提交说明（C1′ = `b3e5337`，报告与证据 05 经 amend 并入）。
7. **未做（按范围）**：不写 `tracer.py` / 中间件 / evaluation 包（Task 3+）；不接 `main.py` / `qa` / `rag` / `conversations`；
   未新增任何依赖、未改 `pyproject`；未改 `contracts.py` / `versioning.py` / `__init__.py` 与既有测试；
   未碰业务库 `mktkb.sqlite3` / `rag-index.sqlite3`、`var/**`、`fixtures/**`、`docs/evidence/**`、账本/GO、归档区；
   未 push、未合并 `main`。
8. **工作树中非本包改动**：开工时已存在 `.claude/handoffs/_index.md` 修改与 `T001-obs-contracts/`、`T002-trace-store/`（handoff.md）、
   `prompts/`、`evidence/verify/` 等 PM 未跟踪文件；本包只 `git add` 交付物（含本报告），未修改/未清理它们。

## 5. 风险与遗留

- 每次 `write()` 一个事务、逐条提交，未做批量写；P0 本地/评测规模可接受，Task 3 接入产品路径后若单请求多次写需评估 P95 延迟
  （设计 §13 已列该风险），必要时新增 `write_many` / 批量事务。
- `purge` 在 Python 侧全表读取并解析 `created_at`，10 万条级保留策略下需关注耗时；P0 规模可接受，P1 可改为规范化时间列 + 范围查询。
- `created_at` 是写入方提供的字符串，格式不统一时年龄清理会保守跳过（不误删但可能不清）；建议 Task 3 统一 ISO-8601 UTC。
- 读/导出/清理复用 `TraceWriteError`，语义上略偏“写入”；若后续调用方需要区分，可再抽公共基类（不破坏现有名称）。
- WAL 会随库生成 `-wal` / `-shm` 文件，生产路径需保证 `var/observability/` 可写；本包未覆盖磁盘满 / 权限降级场景。

---

## 交接摘要（≤10 行）

1. 交付物：`backend/src/mktkb/observability/store.py`（464 行）、`backend/tests/observability/test_store.py`（630 行，24 项）；证据 `docs/reports/OBS-EVAL/P0/evidence/T002/00–06`；本报告。
2. §5.1 写读回环：`store.py:189-232,417-423`；`test_store.py:121,137,152`（整体相等 + 中文 JSON 原样 + ensure_ascii=False）。
3. §5.2 best-effort：`store.py:167-179,203-213`；`test_store.py:172,185,202`（close 后 / 父路径是普通文件均不抛，`write` 抛 `TraceWriteError`，caplog 命中 `trace_write_error`）。
4. §5.3 幂等/WAL/meta：`store.py:51-121,355,364-379`；`test_store.py:219,233,244,260`（两次 close 不抛、journal_mode=wal、schema_meta 版本、列名=41/9 字段、版本不兼容 fail closed）。
5. §5.4 request 列表：`store.py:234-247`；`test_store.py:280`（attempt 1/2/3 全量、未知返回 []）。
6. §5.5 JSONL：`store.py:249-294`；`test_store.py:301`（行数=返回值=库内 trace 数、每行 json.loads、嵌套 spans、since 过滤、中文不转义）。
7. §5.6 purge：`store.py:296-333,445-464`；`test_store.py:349,401,433`（天数/条数/并集/无参数不删/负值 ValueError、spans 一并清理）。
8. §5.7 参数化+并发：`store.py:43-48`；`test_store.py:448,474,491,520,543`（注入回环、源码无值拼接、仅 stdlib+contracts、两连接/两线程并发不坏）。
9. §5.8 实际结果：本包 24 passed（02）；observability 92 passed（03）；全量 1110 passed / 313.39s（04），基线 1086（T001 证据 03）无新增失败。
10. 提交：`p0/obs-eval` 单 commit `p0/T002 sqlite trace repository`，C1′=`b3e5337`（8 文件 1165 插入），报告与证据 05 经 `--amend` 并入（最终 HEAD 见 `git log -1 --format=%h`）；未 push；偏离见 §4（异常命名、构造期容错、导出/purge 语义选择、证据转码、amend 折中）。

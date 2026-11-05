# T002 独立验收报告：SQLite Trace 仓储

> 验收对象：`p0/obs-eval` @ `2ac976f`（`p0/T002 sqlite trace repository`），父提交 `7b02f40`（T001 已验收），基线 `main` @ `8e44158`。
> 验收方式：全新上下文独立复跑 + 仓库外手工探针 + 仓库外变异探针；不采信 report.md 的任何"已完成"结论。
> 验收时间：2026-11-04 23:16–23:27（Asia/Shanghai）。环境：Windows / Windows PowerShell 5.1.26100.9711、Python 3.12.7（`.venv`）、SQLite 3.45.3、pytest 9.1.1。
> 我的原始输出证据：`docs/reports/OBS-EVAL/P0/evidence/verify/T002/00–10`（未修改任何交付物、未 commit/push、未改 `_index.md`）。

## 0. 结论总览

| 项目 | 结论 |
| --- | --- |
| §5.1 写读回环（含中文/`ensure_ascii=False`） | **PASS** |
| §5.2 库不可用时 best-effort 不抛 / `write` 抛 | **PASS** |
| §5.3 建表幂等 + `schema_meta` 版本 + `journal_mode=WAL` | **PASS** |
| §5.4 多 attempt 全量列表 / 未知 request 空列表 | **PASS** |
| §5.5 JSONL 行数/可解析/嵌套 spans/`since` 过滤/返回值 | **PASS** |
| §5.6 purge 两种口径 / 无参数不删 / 负值校验 | **PASS** |
| §5.7 SQL 全参数化 + 并发/重复打开不坏 schema | **PASS** |
| §5.8 新增测试全过、全量无新增失败（1110 = 1086 + 24） | **PASS** |
| 提交边界（只含 §2 交付物、单 commit、不越界） | **PASS** |
| 硬约束（stdlib `sqlite3`、无新依赖、无网络/模型、不读 `.env`、测试只写 `tmp_path`） | **PASS** |
| 测试是否空转（变异探针） | **PASS**（8/8 变异被测试捕获） |

**总体判定：通过独立验收（8/8 验收标准 + 提交边界 + 硬约束）。** 无返工阻断项；仅有 4 条非阻断的文档/证据精度问题（见 §4）与若干未覆盖项（见 §5）。

---

## 1. handoff §5 逐条独立复核

所有命令均先执行 `$env:MKTKB_PROJECT_TOTAL_LIMIT_CNY = "20.0"`，解释器为 `.\.venv\Scripts\python.exe -B`，测试均带 `-q -p no:cacheprovider --basetemp backend\.pytest-tmp\verify-*`（`backend\.pytest-tmp` 已存在/被 gitignore）。原始输出见证据编号。

### §5.1 写读回环 —— PASS

- **独立探针**（证据 `05-manual-probes.txt`）：
  `[PASS] 5.1 write/get roundtrip (rich + bare + normalized span, Chinese JSON) :: 全字段 trace/spans 整体相等；中文 JSON 原样；最小记录/归一 span 往返`
  - 41 字段全填充的 `TraceRecord` 写入后 `get()` 返回对象**整体相等**；2 个 `SpanRecord` 列表**整体相等**且名称顺序 `["parse","answer"]` 正确；中文 JSON（`retrieval_counts_json='{"精确命中": 2, "词法命中": 3}'`、`fact_gate_json` 等）逐字节原样；`replayed` 布尔往返正确；最小记录（其余 None/默认值）无损；span 缺 `span_id`/`trace_id` 时归一后往返且 `span_id` 已生成。
- **开发者测试复跑**（证据 `01-pytest-store.txt`）：`24 passed, 1 warning in 0.29s`（exit 0）。
- 源码定位：`backend/src/mktkb/observability/store.py:189-201`（`write` 单事务）、`:215-232`（`get`）、`:417-422`（按 dataclass 字段顺序取值）；`test_store.py:121,137,152` 对应断言。`ensure_ascii=False` 见 `store.py:289`。
- **结论：PASS。**

### §5.2 best-effort 不抛、`write` 抛 `TraceWriteError` —— PASS

- **独立探针**（证据 `05-manual-probes.txt`）：
  - `[PASS] 5.2 write_best_effort after close: no raise, log, write raises :: best_effort 不抛且日志含 trace_write_error；write 抛 TraceWriteError（TraceRepository 已关闭，不能访问 trace 数据库...）`
  - `[PASS] 5.2 write_best_effort when parent path is regular file :: 构造不抛；best_effort 不抛且记日志；write 抛 TraceWriteError`
  - `[PASS] 5.2 read/export/purge after close raise TraceWriteError :: {"get": "TraceWriteError", "list_by_request": "TraceWriteError", "export_jsonl": "TraceWriteError", "purge": "TraceWriteError"}`
  - 日志断言：命中 `trace_write_error`；且日志文本**不含** trace 正文字段（未泄露业务内容）。
- 源码：`store.py:203-213`（捕获 `Exception` 后 `LOGGER.warning`）；构造期容错 `:167-179`；关闭后访问统一抛异常 `:381-390`。
- 开发者测试复跑：`test_store.py:172,185,202` 在 24 passed 内全部通过（证据 01）。
- **结论：PASS。**（读/导出/purge 复用 `TraceWriteError` 是 report §4.1 明示的偏离，不影响本条判定。）

### §5.3 建表幂等 / `schema_meta` / WAL —— PASS

- **独立探针**（证据 `05-manual-probes.txt`）：
  `[PASS] 5.3 idempotent schema + schema_meta + WAL + dual open :: 两次 close 不抛；tables=['schema_meta', 'spans', 'traces']；meta=mktkb.trace.v0.1；journal_mode=wal；traces 列=41、spans 列=9；双开重开不坏`
  - 连续 `TraceRepository(path).close()` 两次不抛；`schema_meta.trace_schema_version == TRACE_SCHEMA_VERSION`（`mktkb.trace.v0.1`）；**用独立 `sqlite3` 连接实测 `PRAGMA journal_mode` 返回 `wal`**（关闭/重开后再次实测仍为 `wal`）；两连接同文件写读互见后重开不坏。
- 开发者测试复跑：`test_store.py:219`（幂等+meta）、`:233`（独立连接断言 WAL）、`:244`（列名 = 41/9 字段）、`:260`（版本不兼容 fail closed）均通过（证据 01）。
- **结论：PASS。**

### §5.4 `list_by_request` 多 attempt —— PASS

- **独立探针**（证据 `05-manual-probes.txt`）：乱序写入 attempt 3/1/2 后返回 `["t1","t2","t3"]`、`attempt=[1,2,3]`；未知 request 返回 `[]`；其它 request 不串。
  `[PASS] 5.4 list_by_request multiple attempts + unknown`
- 源码：`store.py:234-247`（`WHERE request_id = ? ORDER BY attempt ASC, rowid ASC`）；`test_store.py:280` 通过（证据 01）。
- **结论：PASS。**

### §5.5 `export_jsonl` —— PASS

- **独立探针**（证据 `05-manual-probes.txt`）：
  `[PASS] 5.5 export_jsonl count/parse/nested/since/chinese :: count=行数=2；json.loads 全通过；嵌套 spans；41 字段+spans；中文原文；since 过滤 1 条（aware+naive）`
  - 返回值 == 行数 == 库内 trace 数；每行 `json.loads` 成功；嵌套 `spans` 名称/数量正确；行字段集 = 41 个 `TraceRecord` 字段 + `spans`；`since` 过滤生效（时区感知与 naive 两种输入）；**中文原文 UTF-8 落盘且无 `\uXXXX` 转义**（`ensure_ascii=False`）。
- 源码：`store.py:249-294`（`:289` `ensure_ascii=False, sort_keys=True`）；`test_store.py:301` 通过（证据 01）。
- **结论：PASS。**

### §5.6 `purge` —— PASS

- **独立探针**（证据 `05-manual-probes.txt`）：
  `[PASS] 5.6 purge age/count/union/no-arg/negative/spans :: 无参数不删/按天数删2/按条数删1/并集删2/负值 ValueError/spans 全清`
  - 无参数返回 0 且不删；`older_than_days=7` 删 2 条（30d/10d），剩 1h；`keep_last=2` 删最旧 1 条；两者并集删 2 条；被删 trace 的 spans 全部清除；负值抛 `ValueError`。
- 源码：`store.py:296-333`、`:445-464`；`test_store.py:349,401,433` 通过（证据 01）。
- **结论：PASS。**

### §5.7 SQL 参数化 / 并发与重复打开 —— PASS

- **独立 AST 审计**（证据 `05-manual-probes.txt`）：
  `[PASS] hard-constraint: store imports stdlib only + SQL call-site audit :: ... SQL 调用点 18 个全部为常量/变量（无 f-string/%）；常量 SQL=[...]；变量 SQL=['_INSERT_SPAN_SQL', '_INSERT_TRACE_SQL', '_SCHEMA_SQL']`
  - 逐个检查 18 个 `execute/executemany/executescript` 调用点，首个 SQL 实参均为 `ast.Constant`（常量 SQL）或 `ast.Name`（模块常量），无 `JoinedStr`/`BinOp`；`_INSERT_*` 的 `.format` 只拼 dataclass 字段名常量与 `?` 占位符（`store.py:41-48`），无外部值。DDL/PRAGMA 全为常量字符串。
- **注入回环**（证据 05）：`[PASS] 5.7 SQL injection parameterization :: ... count=3`，`r1' OR '1'='1`、`t' OR '1'='1` 作为值原样回环，查询不放大，表结构完好。
- **并发/重复打开**（证据 05）：两线程各自连接各写 5 条无异常、条数正确、`PRAGMA integrity_check=ok`、schema_meta 完好。
- 开发者测试复跑：`test_store.py:448,474,491,520,543` 均在 24 passed 内通过（证据 01）。
- **结论：PASS。**

### §5.8 测试全过 / 无新增失败 —— PASS

| 命令（节选） | 实测输出 | 证据 |
| --- | --- | --- |
| `pytest backend/tests/observability/test_store.py -q -p no:cacheprovider --basetemp backend\.pytest-tmp\verify-t002-store` | **24 passed, 1 warning in 0.29s**，exit 0 | `01-pytest-store.txt` |
| `pytest backend/tests/observability -q ... --basetemp ...verify-t002-obs-all` | **92 passed, 1 warning in 2.01s**，exit 0 | `02-pytest-observability.txt` |
| `pytest backend/tests -q ... --basetemp ...verify-t002-full` | **1110 passed, 1 warning in 318.96s (0:05:18)**，exit 0，0 failed / 0 error | `03-pytest-full.txt` |
| `pytest backend/tests -q --collect-only --ignore=backend/tests/observability/test_store.py` | **1086 tests collected** | `08-collect-counts.txt` |
| `pytest backend/tests/observability/test_store.py -q --collect-only` | **24 tests collected** | `08-collect-counts.txt` |
| `pytest backend/tests -q --collect-only` | **1110 tests collected** | `08-collect-counts.txt` |

- 相对 T001 基线（1086 passed，见 T001 已验收证据 `docs/reports/OBS-EVAL/P0/evidence/T001/03-pytest-full.txt`）**恰好 +24 且 0 新增失败**：排除新测试文件后收集数实测 1086，新文件 24，总计 1110；当前全量 1110 passed。
- 测试文件 `def test_` 计数 = 24，`pytest.skip/xfail` 出现次数 = 0（证据 `09-report-citation-check.txt`）。
- **结论：PASS。**

---

## 2. 提交边界（handoff §2/§4/§7）—— PASS

证据 `04-commit-boundary.txt`：
- `git show --name-only 2ac976f` 仅 10 个路径，全部属于 §2 交付物：
  `backend/src/mktkb/observability/store.py`（新增）、`backend/tests/observability/test_store.py`（新增）、`docs/reports/OBS-EVAL/P0/evidence/T002/00–06`（证据，§2 允许）、`.claude/handoffs/T002-trace-store/report.md`。
- `git diff --name-status 7b02f40 2ac976f`：全部为 `A`（只有新增，无修改/删除）。
- 对禁止路径的 diff（`main.py`、`qa/`、`rag/`、`conversations/`、`contracts.py`、`versioning.py`、`__init__.py`、`backend/pyproject.toml`、`docs/evidence`、`var`、`fixtures`、既有测试 `test_contracts.py`/`test_versioning.py`）**输出为空**。
- `git log 7b02f40..2ac976f --oneline` 恰 1 条；`HEAD^ = 7b02f40`；分支 `p0/obs-eval`；commit message 与 §7 一致；分支无 upstream 配置（证据 `10-branch-and-commit-topology.txt`）。
- 交付物工作树相对 HEAD 干净（`git status --porcelain` 无 store.py/test_store.py/report.md/evidence/T002 条目；`git diff HEAD` 仅剩开工前已存在的 PM `_index.md` 修改）；验收前后 `git status` 的非本包条目一致（证据 `07-evidence-and-tree-audit.txt`）。
- **结论：PASS。**

## 3. 硬约束 —— PASS

- **只用 stdlib `sqlite3` / 无新依赖**：`store.py` 顶层 import AST 审计 = `{__future__, collections, dataclasses, datetime, json, logging, pathlib, sqlite3, threading, typing, uuid} + .contracts`；无 SQLAlchemy/ORM/第三方（证据 05）。`git diff 7b02f40 2ac976f -- backend/pyproject.toml` 为空（证据 04）。
- **无网络/模型/OCR/embedding/rerank 调用、不读 `.env`**：store.py 与 test_store.py 可执行代码中无 `requests/httpx/aiohttp/socket/urllib/openai/deepseek/dotenv/os.environ/.env` 等痕迹（证据 05 两项静态探针）；本包测试只 import stdlib + `pytest` + `mktkb.observability`（证据 05）。
- **测试只写 `tmp_path`**：静态审计 29 处 `TraceRepository(...)` 路径全部溯源到 `tmp_path`，无绝对路径字面量、无 `var/`/业务库/fixtures/docs 路径（证据 05；docstring 中的"不触碰 var/…"说明已被单独排除，避免误判）。
- 验收运行后受保护路径 `git status` 0 行；`backend/.pytest-tmp` 被 gitignore（证据 07）。
- **结论：PASS。**

## 4. 测试是否空转（仓库外变异探针）—— PASS

从 `git HEAD` 提取提交版 `store.py`/`test_store.py`/`contracts.py` 到系统 TEMP 隔离副本（不读/不改工作区交付物），基线副本 `24 passed`；逐项注入缺陷后测试是否失败（证据 `06-mutation-probes.txt`）：

| 变异 | 实测 | 判定 |
| --- | --- | --- |
| m1 破坏 purge 按年龄边界（不删） | `1 failed, 23 passed`；失败 `test_purge_by_age_and_count` | 捕获 ✅ |
| m2 purge keep_last 少删一条 | `2 failed, 22 passed`；失败 2 个 purge 用例 | 捕获 ✅ |
| m3 让 `write_best_effort` 向上抛 | `2 failed, 22 passed`；失败 2 个 best-effort 用例 | 捕获 ✅ |
| m4 WAL 改成 DELETE | `1 failed`；失败 `test_journal_mode_is_wal` | 捕获 ✅ |
| m5 导出 `ensure_ascii=True` | `1 failed`；失败 `test_export_jsonl_matches_db` | 捕获 ✅ |
| m6 列表只返回 attempt=1 | `6 failed`；含 `test_list_by_request_returns_multiple_attempts` | 捕获 ✅ |
| m7 关闭 schema 版本校验 | `1 failed`；失败 `test_existing_incompatible_schema_version_fails_closed` | 捕获 ✅ |

提交版文件哈希交叉核对：`store.py` sha256=`386aa43da7d484bb6c55c40a53d0277bd0b54fd2d4f68185be3c3903f0b3a2b3`、`test_store.py` sha256=`6a24e5df75f38cef3ffd271b74f575ff452ef800c3c9d559a918c4a731e7e985`，与提交证据 `T002/06-deliverable-sha256.txt` 逐字节一致（证据 06 + 07）。
**结论：关键断言非空转，测试确实锁定行为。**

## 5. 发现的问题（均为非阻断，不影响通过判定）

1. **提交证据的中文路径乱码**：committed `T002/00–04` 文本中 `D:\GPT项目\市场部AI知识库` 显示为 `D:\GPT��Ŀ\�г���AI֪ʶ��`（PowerShell 5.1 管道采集/转码时编码错配）。report §3 称"已转码为 UTF-8 无 BOM（文本内容不变）"对非 ASCII 并不成立。ASCII 关键结论（24/92/1110 passed 等）与我的复跑一致，不影响判定；我用 `cmd /c` 原始重定向 + `PYTHONIOENCODING=utf-8` 重采的 `verify/T002/01–03` 无乱码。
2. **report §2.1 行号引用偏移**：报告称 `test_store.py:327-330` 断言"中文原文落盘且无 `\uXXXX`"，实际断言在 `test_store.py:333-335`（327-330 为 spans 名称/字段集断言）。自证内容成立，仅行号区间偏移（证据 `09-report-citation-check.txt`）。
3. **证据 05 非最终提交 stat**：`T002/05-git-show-stat.txt` 记录的是 amend 前 `b3e5337`（8 文件）的 stat，而非最终 HEAD `2ac976f`（10 文件）的 stat；report §3 已主动说明 amend 折中，最终 stat 由我的 `04-commit-boundary.txt` 独立采集确认。属证据完整性小瑕疵。
4. **静态参数化测试偏弱**：`test_store_source_does_not_interpolate_sql_values` 是字符串黑名单式检查，理论上可被更隐蔽写法绕过；不构成当前缺陷（另有我的 AST 全调用点审计与注入回环验证实际参数化）。
5. **报告其他行号引用抽查**：我脚本核对的 34 处 `store.py`/`test_store.py` 单行引用 + 7 处区间引用逐一核对，除上述第 2 条外全部命中（证据 09）。

## 6. 未覆盖项 / NOT-RUN / BLOCKED

- **NOT-RUN**：TDD RED 证据（`T002/01-pytest-red.txt`）无法在最终 HEAD 复现（当前 store.py 已存在）；只能作为线索，未独立验证其真实性。
- **未重跑 T001 基线全量**：未 checkout `7b02f40` 重跑 1086（避免改动工作树）；改用 `--collect-only --ignore=新测试文件` 实测 1086 + 当前全量 1110 的逻辑核对，并与 T001 已验收证据一致。§5.8 判定成立。
- **未验证远端 push 状态**：分支 `p0/obs-eval` 未配置 upstream；只能确认本地单 commit、未合并 `main`，无法从本地证明远端未被推送（未联网核查）。
- **未覆盖异常场景**：磁盘满、权限降级、WAL/`-shm` 损坏、多进程并发（仅验证多线程/多连接）；均不属 §5 验收要求，report §5 已列为遗留风险。
- **未做代码覆盖率统计**（未安装 coverage 并非要求）；以变异探针替代验证测试有效性。
- **未验证 `purge` 对不可解析 `created_at` 的语义**（report §4 自称选择"不按年龄清理、视作最旧"，非 §5 要求）。
- **BLOCKED：无。**

## 7. 我的证据清单（`docs/reports/OBS-EVAL/P0/evidence/verify/T002/`）

| 文件 | 内容 |
| --- | --- |
| `00-env-and-commit.txt` | 验收环境、HEAD、Python/SQLite/pytest 版本 |
| `01-pytest-store.txt` | handoff §6 第 1 条复跑原文（24 passed） |
| `02-pytest-observability.txt` | handoff §6 第 2 条复跑原文（92 passed） |
| `03-pytest-full.txt` | handoff §6 第 3 条复跑原文（1110 passed / 0 failed / 0 error） |
| `04-commit-boundary.txt` | `git show --name-only/--stat`、与基线 diff、单 commit、受保护路径 diff 为空 |
| `05-manual-probes.txt` | 13 项独立手工探针（§5.1–5.7 + 硬约束静态审计）全 PASS |
| `06-mutation-probes.txt` | 仓库外变异探针 8/8 被捕获 + 基线副本 24 passed + 交付物 sha256 |
| `07-evidence-and-tree-audit.txt` | 提交证据 sha256 与 06 清单逐一 MATCH、最终提交 stat、受保护路径清洁 |
| `08-collect-counts.txt` | 1086（排除新文件）/ 24（新文件）/ 1110（全量）收集数 |
| `09-report-citation-check.txt` | report 行号引用核对（34 处单行 + 7 处区间）+ 测试计数/skip 检查 + 1 处区间偏移记录 |
| `10-branch-and-commit-topology.txt` | 分支/HEAD^/upstream/工作树拓扑 |

---

## 8. 最终结论

T002 的 8 条验收标准（§5.1–5.8）全部 **PASS**；提交边界与硬约束 **PASS**；关键测试经仓库外变异探针确认**非空转**（8/8 捕获）。未发现功能缺陷、越界改动或新增依赖。发现的问题仅为报告行号/证据编码/证据时序等**非阻断文档与证据精度问题**（§5），建议后续包一并修正（如统一用 `cmd /c` 或 UTF-8 管道采集证据、更新 report 引用行号、以最终 HEAD stat 替换证据 05）；**无需返工**，可提交人工审核门。

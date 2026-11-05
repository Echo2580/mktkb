# T002 · SQLite Trace 仓储（P0 第 2 包）

> PM 任务单。基线：`p0/obs-eval` @ `7b02f40`（T001 已通过独立验收）。本包只新增仓储与测试，不改业务代码、不改 T001 契约文件。
> 完成后由全新上下文的独立验收助手按本文件逐条证伪。

## 1. 目标（一句话）

新增 `TraceRepository`：把 T001 的 `TraceRecord` / `SpanRecord` 落到独立 SQLite（`var/observability/qa-traces.sqlite3` 形态），提供写读回环、幂等建表、best-effort 写入、按 request 列表、JSONL 导出与按天数/条数清理。

## 2. 交付物（只准写这些路径）

- 新增 `backend/src/mktkb/observability/store.py`
- 新增 `backend/tests/observability/test_store.py`
- 证据（入库）：`docs/reports/OBS-EVAL/P0/evidence/T002/`（命令输出原文 txt）
- 报告：`.claude/handoffs/T002-trace-store/report.md`（五段，§8）

## 3. 输入（只看这些）

1. `docs/superpowers/specs/2026-11-04-mktkb-observability-evaluation-design.md` §6.2（存储/保留）、§6.6（写入语义）。
2. `docs/superpowers/plans/2026-11-04-mktkb-observability-evaluation-p0.md` Task 2（接口签名与测试样例）。
3. `backend/src/mktkb/observability/contracts.py`（T001 已冻结的 `TraceRecord` / `SpanRecord` / `TRACE_SCHEMA_VERSION`；**只读**，字段类型以它为准）。

## 4. 允许 / 禁止

**允许**：§2 交付物；`git switch p0/obs-eval`（已在分支上则跳过）；本包一个 commit。

**禁止**：
- 不修改 `contracts.py` / `versioning.py` / `__init__.py` 的既有内容（若契约有缺口，在 report 里写明并在 store 侧本地处理）；不改既有测试。
- 不引入 SQLAlchemy 或任何新依赖（只用 stdlib `sqlite3`）。
- 不碰业务库 `mktkb.sqlite3` / `rag-index.sqlite3`、不写 `var/` 之外路径（测试一律 `tmp_path`）。
- 不接 `main.py` / `qa/` / `rag/` / `conversations/`；零真实模型/OCR/embedding/rerank 调用；不读 `.env`；不打印凭据。
- 不碰 `docs/evidence/**`、`var/**`、`fixtures/**`、账本/GO、归档区；不 push、不合并 `main`。
- 不 commit PM 的未跟踪文件（`_index.md`、`T001-obs-contracts/`、`prompts/`）；`git add` 只加本包交付物。

## 5. 验收标准（逐条可判定）

1. 写读回环：`write()` 后 `get(trace_id)` 返回同一 `TraceRecord` 与按名称匹配的 `SpanRecord` 列表；JSON 字段往返无损（含中文/非 ASCII，`ensure_ascii=False`）。
2. `write_best_effort()` 在库不可用（已 `close()`；或父路径为普通文件导致 sqlite 打不开）时**不抛异常**，只记录；`write()` 仍抛 `TraceWriteError`。
3. 建表幂等：同一路径连续 `TraceRepository(path).close()` 两次不抛；`schema_meta` 中 `trace_schema_version` 等于 `TRACE_SCHEMA_VERSION`；`PRAGMA journal_mode` 实际为 `WAL`（测试断言）。
4. `list_by_request(request_id)` 对同一 request 的多次 attempt 全量返回且可按 `attempt` 区分；未知 request 返回空列表。
5. `export_jsonl(out)`：行数与库内 trace 数一致、每行可 `json.loads`、含嵌套 spans；`since` 过滤生效；返回值即导出条数。
6. `purge(older_than_days=...)` 与 `purge(keep_last=...)` 各自生效（先到先清），返回删除条数；无参数时不删任何数据（或明确参数校验）。
7. 全部 SQL 参数化（抽查无 f-string/`%` 拼接值）；并发/重复打开同一文件不破坏 schema。
8. 新增测试全过；`backend/tests` 全量相对 T001 之后基线（**1086 passed**）无新增失败。

## 6. 必须实际运行的检查（输出原文存证据目录）

```powershell
$env:MKTKB_PROJECT_TOTAL_LIMIT_CNY = "20.0"
git rev-parse --short HEAD   # 应为 7b02f40
```

```powershell
.\.venv\Scripts\python.exe -B -m pytest backend/tests/observability/test_store.py -q -p no:cacheprovider --basetemp backend\.pytest-tmp\obs-store
.\.venv\Scripts\python.exe -B -m pytest backend/tests/observability -q -p no:cacheprovider --basetemp backend\.pytest-tmp\obs-all
.\.venv\Scripts\python.exe -B -m pytest backend/tests -q -p no:cacheprovider --basetemp backend\.pytest-tmp\t002-full
git show --stat --oneline HEAD
```

输出原文分别存 `docs/reports/OBS-EVAL/P0/evidence/T002/<编号>-<name>.txt`。

## 7. 提交

- 分支 `p0/obs-eval`，本包一个 commit，消息：`p0/T002 sqlite trace repository`。
- 只 add 本包交付物；不 push。

## 8. report.md 格式（五段齐全）

1. 完成内容：文件清单 + 一句话。
2. 验收标准自证：§5 逐条 1–8，每条附命令或 `文件:行`。
3. 实际运行的命令与结果：关键输出原文（含 commit sha 与 stat）。
4. 偏离与未做：无 / 逐条说明。
5. 风险与遗留：一句话起。

末尾另给 ≤10 行交接摘要。

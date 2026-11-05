# T001 · Trace 数据契约与版本绑定（P0 第 1 包）

> PM 任务单。基线：`main` @ `8e44158`；开发分支 `p0/obs-eval`（从 `8e44158` 建）。
> 本包只新增契约/版本模块与文档，**不改任何业务代码**。完成后由独立验收助手按本文件逐条证伪。

## 1. 目标（一句话）

在 `backend/src/mktkb/observability/` 下落地三套 Schema 版本常量、枚举、路径感知必需 Span 规则、`pipeline_version` / `config_hash` / 问题哈希与冻结 dataclass，并用测试把它们锁死。

## 2. 交付物（只准写这些路径）

- 新增 `backend/src/mktkb/observability/__init__.py`
- 新增 `backend/src/mktkb/observability/contracts.py`
- 新增 `backend/src/mktkb/observability/versioning.py`
- 新增 `backend/tests/observability/__init__.py`（若 pytest 需要）与 `test_contracts.py`、`test_versioning.py`
- 新增 `docs/evaluation/trace_schema_v0_1.md`、`docs/evaluation/eval_data_v0_1.md`
- 证据（入库）：`docs/reports/OBS-EVAL/P0/evidence/T001/`（命令输出原文存 txt）
- 报告：`.claude/handoffs/T001-obs-contracts/report.md`（五段，见 §8）

## 3. 输入（只看这些，不要全库通读）

1. `docs/superpowers/specs/2026-11-04-mktkb-observability-evaluation-design.md` §6.3 / §6.4 / §6.5 / §7.3（字段、Span 表、内容隐私、数据集版本）。
2. `docs/superpowers/plans/2026-11-04-mktkb-observability-evaluation-p0.md` Task 1（接口签名与测试样例）。
3. 只读常量（延迟导入用）：`backend/src/mktkb/qa/service.py` 的 `QA_ENGINE_VERSION`、`backend/src/mktkb/rag/index.py` 的 `SCHEMA_VERSION` / `INDEX_CACHE_VERSION`、`backend/src/mktkb/retrieval/tokenize.py` 的 `TOKENIZER_VERSION`、`backend/src/mktkb/rag/config.py` 的 `RagConfig`。

## 4. 允许 / 禁止

**允许**：§2 列出的交付物路径；`git switch -c p0/obs-eval`（已存在则直接 switch）；本包一个 commit。

**禁止**：
- 不写 SQLite、不接业务代码（不修改也不依赖 `main.py` / `qa/` / `rag/` / `conversations/` 的执行路径；只允许延迟 import 常量）。
- 不改现有测试、不新增生产依赖、不改 `pyproject` / 依赖清单。
- 零真实模型 / OCR / embedding / rerank 调用；不读 `.env`；不访问外网；不打印凭据。
- 不碰 `docs/evidence/**`、`var/**`、`fixtures/**`、账本 / GO、归档区、`docs/reports/OBS-EVAL/P0` 之外的报告目录。
- 不 push、不合并 `main`、不改 `_index.md`、不改 `.claude/handoffs/T001-obs-contracts/` 之外的手续文件。

## 5. 验收标准（逐条可判定）

1. 三套版本常量精确等于 `mktkb.trace.v0.1` / `mktkb.eval.case.v0.1` / `mktkb.gate.v0.1`。
2. `required_spans(path, outcome)` 对设计 §6.4 表**全部 8 行**逐行断言通过，含两个易错点：`rag + clarification` 不含 `answer`；`legacy + not_found` 不含 `query_expansion` / `answer`。
3. `conditional_required_spans(attrs)` 只认 `vector_enabled` / `rerank_enabled` / `expansion_triggered` / `index_sync_performed` 四个键；空 attrs 返回空集。
4. `pipeline_version(...)`：同输入同值；`prompt` 或 `top_k` 变化时值变化；默认组件为延迟导入（模块顶层 import 不引入业务包，无循环导入）。摘要格式在文档写明（sha256 hex，允许 64 位或 12 位前缀）。
5. `hash_question(q, key=b"", algo="hmac-sha256")` 抛 `ValueError`；正常返回 64 hex 且返回值不含原文；`algo="sha256"` 允许空 key。
6. `config_hash(config)`：键名含 `key|secret|token|password`（不区分大小写）时抛 `ValueError`；白名单字段变化时摘要变化；白名单在文档写明。
7. `TraceRecord` / `SpanRecord` 为 `frozen dataclass`，字段覆盖设计 §6.3（traces 与 spans 全字段，可选字段默认 `None`），可实例化；`asdict` / 序列化不抛。
8. 新增测试全过；既有全量测试无新增失败（基线为准，任何失败都要在报告里说明是既有失败还是本包引入）。

## 6. 必须实际运行的检查（输出原文存到证据目录）

先在 PowerShell 设置（当次会话有效）：

```powershell
$env:MKTKB_PROJECT_TOTAL_LIMIT_CNY = "20.0"
git switch -c p0/obs-eval   # 若已存在则 git switch p0/obs-eval
```

```powershell
.\.venv\Scripts\python.exe -B -m pytest backend/tests/observability -q -p no:cacheprovider --basetemp backend\.pytest-tmp\obs-contracts
.\.venv\Scripts\python.exe -B -m pytest backend/tests -q -p no:cacheprovider --basetemp backend\.pytest-tmp\t001-full
git rev-parse --short HEAD
git show --stat --oneline HEAD
```

将上面每条命令的 stdout/stderr 原文分别存为 `docs/reports/OBS-EVAL/P0/evidence/T001/<编号>-<name>.txt`。

## 7. 提交

- 分支 `p0/obs-eval`，每包一个 commit，消息：`p0/T001 contracts & versioning`。
- 只 `git add` 本包交付物（含证据 txt 与 report 不在仓库内时按 §4 处理——`report.md` 归 `.claude/handoffs/`，若被 ignore 则不入 commit）。
- 不 push。

## 8. report.md 格式（五段齐全）

1. 完成内容：文件清单 + 一句话。
2. 验收标准自证：§5 逐条 1–8，每条附命令或 `文件:行`。
3. 实际运行的命令与结果：关键输出原文（含 commit sha、stat）。
4. 偏离与未做：无 / 逐条说明（含任何与计划的差异及原因）。
5. 风险与遗留：一句话起。

末尾另给 ≤10 行交接摘要（给 PM 转述用）：交付物路径、自证要点、偏离、风险。

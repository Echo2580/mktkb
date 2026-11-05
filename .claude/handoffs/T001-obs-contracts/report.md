# T001 报告：Trace 数据契约与版本绑定（P0 第 1 包）

> 分支：`p0/obs-eval`（从 `8e44158` 建）；开发方：dev-t001。
> 本报告是开发方自证，验收请以独立复跑结果为准。
> 证据目录：`docs/reports/OBS-EVAL/P0/evidence/T001/`。

## 1. 完成内容

新增 8 个交付文件 + 证据（未改任何业务代码、`pyproject` / 依赖清单、既有测试）：

| 文件 | 一句话 |
| --- | --- |
| `backend/src/mktkb/observability/__init__.py` | 包入口，re-export 契约与版本工具 |
| `backend/src/mktkb/observability/contracts.py` | 三套 Schema 版本常量、`TraceMode`/`TracePath`/`OutcomeKind`、`required_spans`（设计 §6.4 全表）、`conditional_required_spans`（四键）、冻结 `TraceRecord`（41 字段）/`SpanRecord`（9 字段） |
| `backend/src/mktkb/observability/versioning.py` | `pipeline_version`（canonical JSON sha256[:12]，默认组件调用期延迟导入）、`config_hash`（白名单 + 凭据键拒绝）、`hash_question`（hmac-sha256 强制 key / sha256 允许空 key）、`key_fingerprint` |
| `backend/tests/observability/__init__.py` | 测试包标记 |
| `backend/tests/observability/test_contracts.py` | 契约锁定测试（25 项，设计 §6.3/§6.4） |
| `backend/tests/observability/test_versioning.py` | 版本/摘要/哈希锁定测试（23 项） |
| `docs/evaluation/trace_schema_v0_1.md` | Trace 字段、枚举、必需 Span、内容隐私、摘要格式（12 位 hex 口径） |
| `docs/evaluation/eval_data_v0_1.md` | Case JSONL 结构、稳定引用、`dataset_version`、运行清单绑定、P0 数据集、Holdout 防污染 |
| `docs/reports/OBS-EVAL/P0/evidence/T001/` | 00 基线 / 01 RED / 02 observability / 03 全量 / 04 rev-parse / 05 show-stat / 06 文件 SHA-256 |

一句话：在不改任何业务代码、零真实模型/OCR/embedding/rerank 调用、不读 `.env`、不联网的前提下，用「先失败后通过」的测试锁死 Trace/评测/门禁三套数据契约与版本摘要口径。

## 2. 验收标准自证（§5 逐条）

1. **三套版本常量精确** — `backend/src/mktkb/observability/contracts.py:18-20`
   （`mktkb.trace.v0.1` / `mktkb.eval.case.v0.1` / `mktkb.gate.v0.1`）；断言
   `backend/tests/observability/test_contracts.py:111-114`。
2. **§6.4 全部 8 行** — 映射 `contracts.py:55-72`；测试参数化
   `test_contracts.py:34-48`（8 行展开为 12 个 path+outcome 组合）与
   `test_contracts.py:120-123`；两个易错点单独断言
   `test_contracts.py:125-138`（`rag + clarification` 不含 `answer`/`recall`；
   `legacy + not_found` 不含 `query_expansion`/`answer`/`model_answer`）。
   设计表未定义的组合 fail closed（抛 `ValueError`，`test_contracts.py:152-161`）。
3. **条件必需 Span 只认四键** — `contracts.py:75-80`、`contracts.py:107-115`；
   测试 `test_contracts.py:179-205`：四键各自、空 attrs 空集、未知键忽略、多键并集、
   false 值不要求。
4. **`pipeline_version`** — `versioning.py:92-124`（默认组件调用期延迟导入）、
   `versioning.py:116-124`；同输入同值 + `prompt`/`top_k` 变化即变化：
   `test_versioning.py:34-59`；延迟导入证明（monkeypatch 业务常量后摘要变化）：
   `test_versioning.py:62-78`；模块顶层只 import 标准库（AST 断言）：
   `test_versioning.py:83-96`；子进程全新导入无循环导入：
   `test_versioning.py:99-120`；摘要格式（sha256 hex 前 12 位）：
   `docs/evaluation/trace_schema_v0_1.md` §7.2 表格。
   *判定口径说明*：既有 `backend/src/mktkb/__init__.py:3` 是 `from .main import create_app`，
   任何 `import mktkb.*` 都会先加载 `main`；因此「模块顶层 import 不引入业务包」按**本包模块
   自身顶层 import** 判定（AST 测试 + 调用期 monkeypatch 测试），未改父包。
5. **`hash_question`** — `versioning.py:146-165`；`hmac-sha256` 空 key 抛 `ValueError`、
   正常返回 64 hex 且不含原文、`sha256` 允许空 key、未知 algo 抛 `ValueError`：
   `test_versioning.py:123-163`。
6. **`config_hash`** — `versioning.py:35-62`（白名单）、`versioning.py:127-144`；
   键名含 `key|secret|token|password`（不区分大小写）抛 `ValueError`：
   `test_versioning.py:187-192`；白名单字段变化 → 摘要变化（16 个字段逐一断言）：
   `test_versioning.py:194-199`；白名单写明：`trace_schema_v0_1.md` §7.2。
7. **冻结 dataclass + §6.3 全字段** — `contracts.py:118-196`；`frozen=True`、字段集精确等于
   设计 §6.3（traces 41 / spans 9）、可实例化、`asdict`/`json.dumps` 不抛：
   `test_contracts.py:230-329`。
8. **测试全过、无新增失败** —
   - `pytest backend/tests/observability -q ...` → `68 passed`（证据 `02-pytest-observability.txt`）；
   - `pytest backend/tests -q ...` → `1086 passed, 1 warning in 335.47s`（证据 `03-pytest-full.txt`）；
   - 改动前同环境全量基线 → `1018 passed, 1 warning in 307.28s`（证据 `00-baseline-pytest.txt`）；
     差值 `1086 - 1018 = 68`，恰为本包新增测试数，无 failed/error。
   - 注：`--basetemp` 的父目录 `backend\.pytest-tmp` 必须先存在（pytest 对 basetemp 根用
     `mkdir(parents=False)`）。首次未创建父目录时，既有全量测试出现 694 个 `tmp_path` setup
     error（与本包无关的环境问题）；创建该 gitignored 目录后基线全绿，故最终证据采用创建后的两次运行。

## 3. 实际运行的命令与结果

环境：Windows / PowerShell，Python 3.12.7（`.venv`），每条命令均先
`$env:MKTKB_PROJECT_TOTAL_LIMIT_CNY = "20.0"`，解释器 `.\.venv\Scripts\python.exe -B`。
证据为命令 stdout/stderr 原文（UTF-8），见 `docs/reports/OBS-EVAL/P0/evidence/T001/`。

```powershell
# TDD RED：先写测试、确认失败（ModuleNotFoundError）
.\.venv\Scripts\python.exe -B -m pytest backend/tests/observability -q -p no:cacheprovider --basetemp backend\.pytest-tmp\obs-contracts
# → 2 errors during collection: ModuleNotFoundError: No module named 'mktkb.observability'（证据 01）

# 实现后：本包测试全过
.\.venv\Scripts\python.exe -B -m pytest backend/tests/observability -q -p no:cacheprovider --basetemp backend\.pytest-tmp\obs-contracts
# → 68 passed, 1 warning in 1.73s（证据 02）

# 改动前基线（同命令、改动前代码）
.\.venv\Scripts\python.exe -B -m pytest backend/tests -q -p no:cacheprovider --basetemp backend\.pytest-tmp\t001-baseline
# → 1018 passed, 1 warning in 307.28s（证据 00）

# 改动后全量
.\.venv\Scripts\python.exe -B -m pytest backend/tests -q -p no:cacheprovider --basetemp backend\.pytest-tmp\t001-full
# → 1086 passed, 1 warning in 335.47s（证据 03）

# 提交与提交后元信息（提交时在 p0/obs-eval）
git commit -m "p0/T001 contracts & versioning"
# → [p0/obs-eval 6680f85] p0/T001 contracts & versioning；13 files changed, 1419 insertions(+)
git rev-parse --short HEAD
# → 6680f85（证据 04）
git show --stat --oneline HEAD
# → 6680f85 p0/T001 contracts & versioning …（13 files changed, 1419 insertions(+)，原文见证据 05）
```

**提交说明（与单 commit 约束的折中）**：代码/测试/文档先提交为 C1 = `6680f85`（13 文件、
1419 行插入）；`git rev-parse` / `git show --stat` 的原文（证据 04/05）与**本报告**在 C1 之后
采集，再 `git commit --amend --no-edit` 纳入同一提交。因此最终 HEAD 是 C1 的 amend 版本
（C2 = C1 + `report.md` + 证据 04/05），**最终短 sha 与 `git show --stat` 见回复末尾交接摘要 /
`git log -1 --stat`**；代码/测试/文档内容与 C1 完全一致。单 commit 无法在自身内容里记录自身
sha，这是该约束下的唯一折中，特此说明。

## 4. 偏离与未做

1. **`anchors.json` 未写**：计划 Task 1 Step 5 提到 `anchors.json` 记录新文件 SHA-256，但 handoff
   §2 只允许 `docs/reports/OBS-EVAL/P0/evidence/T001/`（`anchors.json` 在其上级目录），故未写；
   等价信息改记入 `evidence/T001/06-deliverable-sha256.txt`（8 个交付文件 SHA-256）。
2. **报告/证据 04/05 与最终 sha**：见 §3 的 commit 说明（单 commit 自引用 sha 的固有折中）。
3. **额外实现（超出 §5 明列项）**：
   - `key_fingerprint`（计划 Task 1 Interfaces 已要求，§5 未单列）：域分隔 sha256 前 12 位，空 key 抛
     `ValueError`；
   - `required_spans` 对设计表未定义的 path+outcome 组合抛 `ValueError`（fail closed，不静默返回
     空集）——设计未规定该行为，本包按"不伪造契约"选择显式失败；
   - `legacy_with_rag_candidates` 与 `legacy` 共用 legacy 规则（覆盖设计 §6.4 第 5 行，其余 legacy 行
     仅写 `legacy`，按同一路径族处理）。
4. **未做（按范围）**：不写 SQLite（Task 2）、不接 `main.py` / `qa` / `rag` / `conversations` 执行路径
   （Task 3）、不实现 evaluation 包与 runner/scorers（Task 4+）、不写 `docs/evaluation/gate_v0_1.json`
   （不在本包 §2 交付物内）；未 push、未合并 `main`；未新增生产依赖、未改 `pyproject` 与依赖清单；
   未改既有测试、业务代码、`docs/evidence/**`、`var/**`、`fixtures/**`、账本/GO、归档区。
5. **工作树中非本包改动**：开工时已存在 `.claude/handoffs/_index.md` 修改与
   `.claude/handoffs/T001-obs-contracts/`、`.claude/handoffs/prompts/T001-*.md` 未跟踪文件
   （PM 手续文件），本包未 add/未修改它们（`_index.md` 的 diff 属于 PM）。

## 5. 风险与遗留

- `pipeline_version()` 首次调用会延迟 import `qa.service` / `rag.index` / `retrieval.tokenize` 并构造
  `RagConfig()`（秒级以内）；若未来按每条 Trace 调用应缓存或复用，P0 只在 run/manifest 级调用，
  影响可接受。
- `config_hash` 白名单外的字段被忽略：未来新增影响检索/回答行为的配置字段时必须同步扩白名单，
  否则版本绑定会漏；且凭据规则使字段名含 `token` 的项（如 `max_output_tokens`）不能进白名单。
- 未定义 path+outcome 组合 fail closed：Task 3/5 接入业务埋点后，若真实路径出现表外组合
  （如 RAG 的 `not_found`/`service_error`），需先扩契约再使用，不能在调用方绕过。
- 本包只冻结契约；`TraceRepository`（Task 2）与埋点/gate（Task 3/5）落地前，这些常量仅被测试与
  后续任务引用，尚不产生运行时行为。

---

## 交接摘要（≤10 行）

1. 交付物：`backend/src/mktkb/observability/{__init__,contracts,versioning}.py`；`backend/tests/observability/{__init__,test_contracts,test_versioning}.py`；`docs/evaluation/{trace_schema_v0_1,eval_data_v0_1}.md`；证据 `docs/reports/OBS-EVAL/P0/evidence/T001/`（00–06）。
2. §5.1 常量：`contracts.py:18-20`，测试 `test_contracts.py:111`。
3. §5.2 八行 Span：`contracts.py:55-72`，逐行断言 `test_contracts.py:34-48,120-161`（含两易错点；表外组合 fail closed）。
4. §5.3 条件 Span：`contracts.py:75-80,107-115`；`test_contracts.py:179-205`。
5. §5.4 pipeline_version：`versioning.py:92-124`；同输入同值/变化生效/调用期延迟导入（AST+monkeypatch）/子进程导入：`test_versioning.py:34-120`；格式 12 位 hex 见 `trace_schema_v0_1.md` §7.2。
6. §5.5 hash_question：`versioning.py:146-165`；空 key ValueError/64 hex/不含原文/sha256 空 key：`test_versioning.py:123-163`。
7. §5.6 config_hash：`versioning.py:35-62,127-144`；凭据键 ValueError、16 字段白名单逐一变化、白名单文档同步：`test_versioning.py:187-199`。
8. §5.7 记录：`contracts.py:118-196`（frozen；traces 41 / spans 9 字段）；`test_contracts.py:230-329`。
9. §5.8 测试：本包 68 passed（证据 02）；全量 1086 passed（证据 03），基线 1018 passed（证据 00），差值 68，无新增失败。
10. 提交：`p0/obs-eval` 单 commit `p0/T001 contracts & versioning`（C1=`6680f85`；报告与证据 04/05 经 amend 并入，最终 HEAD 见回复与 `git log -1`）；未 push；偏离：`anchors.json` 未写（改 06 文件哈希）、表外组合 fail closed、`legacy_with_rag_candidates` 共用 legacy 规则。

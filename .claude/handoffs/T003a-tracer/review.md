# T003a 独立验收报告：tracer 内核（P0 第 3 包）

> 验收对象：分支 `p0/obs-eval` @ `dea4d5d`（`p0/T003a tracer core`；父提交 `2ac976f`）；前两包 T001=`7b02f40`、T002=`2ac976f` 已通过独立验收；基线 `main` @ `8e44158`。
> 验收方式：全新上下文独立复跑 + 仓库外独立探针（1212 条断言）+ 仓库外变异探针（12 个变异，分别打独立探针与开发者测试）+ 静态/边界审计。**不采信 `report.md` 的任何“已完成”结论**，report 只当线索。
> 验收时间：2026-11-04 23:55 – 2026-11-05 00:45（Asia/Shanghai）。环境：Windows、Python 3.12.7（`.venv`）、pytest 9.1.1、SQLite 3.45.3。
> 我的原始输出与探针源码：`docs/reports/OBS-EVAL/P0/evidence/verify/T003a/00–13`（UTF-8 无 BOM）。未修改任何交付物、未 commit/push、未改 `_index.md`。

## 0. 结论总览

| 项目 | 结论 | 关键证据 |
| --- | --- | --- |
| §5.1 contextvars 隔离（并发线程/嵌套/无 trace=None） | **PASS** | 07 独立探针；01 复跑；`tracer.py:52-58,155-158,495-531,727-737,740-742` |
| §5.2 唯一 trace_id + 自动 finish + 幂等不重复写 | **PASS** | 07（1000 次唯一/1 次写入/异常退出）；01 |
| §5.3 Span 父子/duration_ms/status/attributes_json/异常/未执行不落库 | **PASS** | 07（1212 断言中 spans 段）；01 |
| §5.4 五个 setter + 缺 outcome/path→incomplete 不抛 + finish 后 no-op | **PASS** | 07；01；`tracer.py:429-492,609-621` |
| §5.5 finish 只走 `write_best_effort`/失败不抛/无 repo 不建 DB | **PASS** | 07；01；`tracer.py:535-555`；10 边界观察 |
| §5.6 `off`/`hash` 内容模式真实生效 + HMAC 口径 + `redacted/full` fail closed | **PASS** | 07；01；`tracer.py:188-211,262-297,691` |
| §5.7 `validate_required_spans`：§6.4 全 8 行 + 条件 Span + clarification 不误判 | **PASS** | 07（12 个 path+outcome 组合 + 4 条件属性）；`contracts.py:199-245` |
| §5.8 新增测试全过、全量相对 T002 基线 1110 无新增失败 | **PASS** | 01=66 passed；02=158 passed；03=**1176 passed / 0 failed / 0 error**；11c baseline 等价 1110 passed |
| 提交边界（只含 §2 允许路径、append-only、不越界） | **PASS** | 04/05/06；12 工作树审计 |
| 硬约束（无新依赖/零真实调用/不读 .env/测试只写 tmp_path） | **PASS** | 09 静态检查；12 工作树审计 |
| 测试是否空转（变异探针） | **PASS** | 08：control 通过，12/12 变异被**独立探针与开发者测试同时**捕获 |

**总体判定：通过独立验收**（§5 八条 + 提交边界 + 硬约束 + 非空转）。无阻断返工项；有 1 条非阻断证据精度问题与若干口径/风险观察（§5），以及若干按范围不属于本包的未覆盖项（§6）。

---

## 1. handoff §6 必跑命令的实际复跑结果

均先执行 `$env:MKTKB_PROJECT_TOTAL_LIMIT_CNY = "20.0"`；解释器 `.\.venv\Scripts\python.exe -B`；每条 pytest 均 `-q -p no:cacheprovider --basetemp backend\.pytest-tmp\verify-*`（`backend\.pytest-tmp` 已存在且被 gitignore）。原始输出见证据编号。

| 命令 | 我的实际结果 | 证据 |
| --- | --- | --- |
| `python -B -m pytest backend/tests/observability/test_tracer.py -q -p no:cacheprovider --basetemp ...` | **66 passed, 1 warning in 0.29s**，exit 0 | `01-pytest-tracer.txt` |
| `python -B -m pytest backend/tests/observability -q -p no:cacheprovider --basetemp ...` | **158 passed, 1 warning in 2.17s**，exit 0 | `02-pytest-observability.txt` |
| `python -B -m pytest backend/tests -q -p no:cacheprovider --basetemp ...` | **1176 passed, 1 warning in 390.04s**，exit 0，0 failed / 0 error | `03-pytest-full.txt` |
| `git show --stat --oneline HEAD` | `dea4d5d p0/T003a tracer core`；12 files changed, **2274 insertions(+)** | `04-commit-boundary.txt` |
| `git show --name-status dea4d5d` | 12 个文件，全部落在 handoff §2 允许路径内；无删除 | `04-commit-boundary.txt` |
| `git rev-parse`（HEAD/父/分支） | HEAD=`dea4d5d…`、父=`2ac976f…`、分支=`p0/obs-eval` | `04-commit-boundary.txt` |

补充复跑：**T002 基线等价源码**（把 `backend/src/mktkb` 复制到仓库外、`contracts.py`/`__init__.py` 逐字节回退到 `2ac976f`（`git hash-object` 与 `git rev-parse 2ac976f:…` 一致）、删除 `tracer.py`；测试集=HEAD `backend/tests` 去掉新增 `test_tracer.py`，`-o pythonpath=` + `PYTHONPATH` 指向基线副本）→ **1110 passed, 0 failed / 0 error**（`11c`，另两次复跑出现既有 `test_chat.py::test_g08` 时序 flake：`11/11b`、单独复跑该用例通过 `13`；详见 §2 §5.8）。

---

## 2. handoff §5 逐条独立复核

### §5.1 contextvars 隔离 —— PASS

- **独立探针（07，section `contextvars`）实际断言**：
  - 无 trace 时 `current_trace() is None`；
  - 两个并发线程（`threading.Barrier` 双重同步）各开一个 trace：两线程 trace_id 不同且各自唯一、每个线程的 Span 只挂在自己 trace 上、各自只写 1 次、`current_trace()` 返回自己；
  - 嵌套 trace：内层 trace_id ≠ 外层，内层 Span 根 `parent_span_id is None`（**不继承外层 Span 栈**），内层退出后 `current_trace()` 恢复外层，各自只写自己的 Span；
  - asyncio 两个子 task 各自独立 trace、退出恢复父 trace（额外覆盖）；
  - 异常退出后 `current_trace() is None`（contextvar 清理）。
- **复跑开发者测试**：`01` 66 passed；源码 `tracer.py:52-58`（两个 contextvar）、`:155-158`（栈顶）、`:495-531`（进入 push/退出 reset token）、`:727-737`（`set`/`finally` 中 `reset`、自动 finish、`_SPAN_STACK.set(())` 隔断）、`:740-742`（无 trace 返回 None）。
- **观察（非阻断）**：contextvars 不跨线程传播——在 trace 内新起的子线程 `current_trace()` 为 `None`（`10` §4）。这是 contextvars 正常语义，T003b/c/d 若用线程池需显式传 trace；不影响 §5.1“隔离”判定。

### §5.2 唯一 trace_id、自动 finish、幂等 —— PASS

- **独立探针（07，`lifecycle`）**：1000 次 `start_trace` 的 trace_id 全不同、均为 32 位 uuid4 hex；上下文正常退出自动写 **1 次**；显式 `finish()` 两次 + 上下文退出仍只有 **1 次**写入（幂等）；异常退出仍 finish 一次，且 `status=error`、`error_code=RuntimeError`。
- 源码：`tracer.py:710-712`（`uuid.uuid4().hex`）、`:535-547`（锁内先置 `_finished`，重复调用直接返回，只组装/写入一次）、`:729-737`（`finally` 自动 finish）。
- 复跑：`01` 66 passed；dev 测试 `test_tracer.py:101,242,262,279` 覆盖同语义。

### §5.3 Span：父 Span / 计时 / 状态 / attributes / 异常 / 未执行 —— PASS

- **独立探针（07，`spans`）**：嵌套+兄弟 Span 的 `parent_span_id` 正确（根 None、子=父 span_id、父退出后新 Span 根）；记录顺序=进入顺序；`duration_ms` 为非负 int 且 `time.sleep(0.06)` 后 ≥30ms（证明真实计时，非常量）；Trace `latency_ms` 亦 ≥30ms；默认 `status=ok`；无属性时 `attributes_json="{}"`；`ensure_ascii=False` + `sort_keys=True` 实测为 `{"a":1,"b":2,"中文":"值"}` 且无 `\uXXXX`；Span 内抛 `ValueError` → Span `status=error`/`error_code=ValueError` 且 Trace `status=error`；未执行的 Span 不产生记录；Span 退出后 `annotate`、finish 后的 `span()` 均 no-op 不落库。
- 源码：`tracer.py:495-531`（父取自栈顶、异常 `_mark_error`+re-raise、finally 计时）、`:623-644`（SpanRecord 组装）、`:121-128`（单调时钟毫秒）、`:144-152`（canonical JSON）、`:303-372`（SpanHandle）。
- 复跑：`01` 66 passed；dev 测试 `test_tracer.py:312,339,373,404,426,445,465,486`。

### §5.4 setter / annotate / incomplete / finish 后 no-op —— PASS

- **独立探针（07，`setters`）**：`set_request_id`/`set_question`/`set_path`/`set_outcome(reason, **attrs)`/`annotate` 全部生效（字段、canonical JSON、中文键均核对）；枚举与等值字符串均可；**未设置 outcome** → `status=incomplete` 且不抛；`path=None` → `status=incomplete` 且不抛；finish 后所有 setter/annotate/span no-op；未知字段/保留字段 `ValueError`。
- 源码：`tracer.py:429-492`（五个 setter + annotate 保留字段校验/JSON canonical 化）、`:609-621`（status 判定：异常 > replayed > 缺 outcome/path=incomplete > error 结局 > ok）。
- **观察（口径，非阻断）**：`replayed=True` 且未设置 outcome 时实测 `status=replayed`（优先于 incomplete），`path=None` 亦然（`10` §1）。设计 §6.1 规定“只有重放仍写一条 `status=replayed`、Span 为空”，实现顺序与 report §2.4 自述一致；本判定按“普通执行尝试缺 outcome/path→incomplete”口径 PASS，建议 T003b/c/d 知悉该优先级。

### §5.5 写入语义：只走 write_best_effort / 失败不抛 / 无 repo 不建 DB —— PASS

- **独立探针（07，`write-semantics`）**：
  - 同时暴露 `write` 与 `write_best_effort` 的替身：只调用 **1 次 `write_best_effort`**，`write` 从未被调用；
  - 写入抛异常的替身：不向调用方抛出，日志命中 `trace_finish_error`，`current_trace()` 清理；
  - 真实 `TraceRepository` 已 close：不抛；真实 SQLite 回环：`repo.get()` 字段/Span 父子/`validate_required_spans(...)==[]` 全部正确；
  - **无 repo**：在全新空 cwd 中跑完整个 trace，目录仍为空（**不创建任何 DB 文件**）；
  - `finish` 时存在未关闭 Span：跳过不落库并告警（`trace_finish_with_open_spans`）。
- 源码：`tracer.py:535-555`（finish 幂等、组装异常/写入异常均捕获不抛）、`:548-549`（repo is None 直接返回）、`:602-607`（未关闭 Span 跳过）。
- **“未开启”口径（范围说明）**：本内核没有全局 `trace_enabled` 开关（开关与中间件属 T003b），未开启时调用方不 `start_trace`，`current_trace()` 恒 None、无记录 API 可调用、不触碰 DB；实测 `repo=None` 不建 DB 文件。判定 PASS（口径与 report §2.5 一致）。
- **观察（非阻断）**：report §4.5 称“finish 内组装异常被吞”，但公开 API 下 `annotate(filter_decisions_json=非法文本)` 会立即 `ValueError`（`10` §8），组装异常路径事实上不可达；属文档精度问题，不影响写入语义。

### §5.6 内容模式 off / hash + fail closed —— PASS

- **独立探针（07，`content-modes`）**：
  - 默认 `hash`：`question_hash == hashlib.sha256(...)` **且 == `versioning.hash_question(q, algo="sha256")`**；`question_chars=len`；`hash_algo="sha256"`、`hmac_key_id=None`；原文不出现在记录；
  - 带 key：`question_hash == hmac-sha256` **且 == `versioning.hash_question(q, key=key, algo="hmac-sha256")`**；`hmac_key_id == versioning.key_fingerprint(key)`；key 不以明文/hex 入记录；
  - 空 key（`b""`）：退化为 sha256（`hash_algo=sha256`、`hmac_key_id=None`、摘要=sha256 口径）；与 `versioning.hash_question(hmac-sha256, 空 key) 会 ValueError / sha256 允许空 key` 的口径一致（tracer 在调用前把空 key 归一为“无 key”）；
  - `off`：`question_hash/hash_algo/hmac_key_id` 全 None、仅 `question_chars`，记录+Span 序列化中无原文；
  - `redacted` / `full`：`start_trace` 显式 `ValueError` fail closed，且不残留 contextvar；未知模式同样 fail closed。
- 源码：`tracer.py:188-211`（模式/空 key 校验，未实现模式 fail closed）、`:262-297`（hash/off 字段）、`:691`（默认 hash）。
- **观察（契约层，非本包越界）**：设计 §6.5 的 hash 模式描述含“问题/答案/上下文哈希 + 长度”，但 T001 冻结的 `TraceRecord`（41 字段）没有 answer/context 哈希字段，本包只能实现问题哈希；该缺口属 T001 契约/设计层，本包未越界新增字段。

### §5.7 validate_required_spans —— PASS

- **独立探针（07，`validate`）**：
  - 设计 §6.4 表**全部 8 行**（展开为 12 个 path+outcome 组合）完整集合均返回 `[]`；各自缺一个时返回对应缺失清单（排序）；
  - `rag + clarification` 完整集合=`["parse","commit"]` 返回 `[]`，且 `answer` **不在** `required_spans` 中（不误判）；legacy clarification/service_error 同理；
  - `legacy_with_rag_candidates` 走 legacy 规则；
  - 四个条件属性（`vector_enabled`/`rerank_enabled`/`expansion_triggered`/`index_sync_performed`）逐个 true→要求对应 Span、false→不要求；属性写在任意 `*_json` 顶层键均可读到；四个全 true→缺失清单为排序后的 4 个 Span；
  - 设计未定义组合（`rag+service_error`、`rag+not_found`、`legacy+conflict` 等）→ `ValueError` fail closed；缺 path/outcome → `ValueError`；单字符串入参 → `TypeError`；tuple/set/generator 入参均可；纯函数不修改记录；
  - tracer `annotate(vector_enabled=True)` 并入 `filter_decisions_json` 后能被同一函数读到（独立探针覆盖；dev 测试 `:1032,1058` 同语义）。
- 源码：`contracts.py:199-245`（追加函数；基础集合复用 `required_spans`，条件集合从任意 `*_json` 顶层键读取，`:245` 排序返回）；`contracts.py:75-80,88-115`（T001 冻结规则复用）。
- **观察（非阻断）**：`*_json` 为非法 JSON 文本时条件属性被静默忽略（`10` §5，返回 `[]` 而非 fail closed）。tracer 自身对 `filter_decisions_json` 的 `annotate` 会 fail closed，其它 `*_json` 字段接受任意字符串；建议 T003c/d 只写 canonical JSON，Task 5 gate 可另加 JSON 合法性校验。

### §5.8 新增测试全过、全量无新增失败 —— PASS

- 本包测试：`01` **66 passed**（与 report 的 66 用例一致；静态核对 58 个测试函数 + 2 个 parametrize 共 66 用例，`09`）。
- observability 目录：`02` **158 passed**（= 既有 92（T001+T002）+ 本包 66，与 report 一致）。
- 全量 `backend/tests`：`03` **1176 passed, 0 failed / 0 error**（390.04s，exit 0；另一次即时复跑 1176 passed / 395.63s 亦一致，未留存为证据文件）。
- **相对 T002 基线**：`git diff 2ac976f..dea4d5d -- backend/tests` 只有 `A backend/tests/observability/test_tracer.py`（`09` 断言），即既有测试零改动；基线等价源码（仓库外逐字节回退 contracts/__init__、移除 tracer.py、测试集=去掉新文件）复跑 **1110 passed / 0 failed / 0 error**（`11c`，本次复跑中唯一完整通过的一次，原 Tee 输出 UTF-16LE 已无损转码 UTF-8）；1110 + 66 = 1176，与全量结果精确吻合。
- **基线复跑的时序 flake（诚实记录）**：同一基线等价套件另两次复跑均命中既有 `backend/tests/integration/test_chat.py::test_g08_short_budget_cancels_inflight_model_call`（1 failed / 1109 passed，`11/11b`）；该用例单独复跑通过（`13`），HEAD 全量 1176 passed 未复现；该用例是既有模型预算取消的时序测试，T003a 的 diff 未触碰该路径（`04`）。判为环境时序 flake，不影响 §5.8 结论（且 1110 基线本身已由 T002 独立验收与本包 `11c` 双证）。
- 结论：0 failed / 0 error，满足“相对 T002 基线无新增失败”。

---

## 3. 提交边界与硬约束

### 3.1 提交边界 —— PASS

- `git show --name-status dea4d5d`（`04`）12 个文件，全部在 handoff §2 允许范围：`tracer.py`（A）、`observability/__init__.py`（M）、`observability/contracts.py`（M）、`test_tracer.py`（A）、证据 `00–06`（A）、`report.md`（A）。
- 受保护路径零改动（`04` 空输出）：`main.py`/`config.py`/`qa/`/`rag/`/`conversations/`、`store.py`、`versioning.py`、既有测试、`pyproject.toml`、`requirements*.lock`、`docs/evidence`、`var`、`fixtures`、`_index.md`。
- 无删除文件；父提交=`2ac976f`；分支=`p0/obs-eval`；未 push（我复核时 HEAD 即 `dea4d5d`，工作树无 commit 动作）。
- **`contracts.py` 只在末尾追加**（`05`）：`git diff -U0` 无任何 `-` 行；旧文件内容是新文件前缀（独立断言）；`__all__` 逐字未改；新增函数 `contracts.py:199-245`（+50 行）。**`__init__.py`** +7/-0（`:22,24,36-54`，纯新增导入/导出，既有导出语义不变）。
- 文件数/行数算术核对：760+1224+50+7+135+98 = 2274，与 `git show --stat` 的 12 files / 2274 insertions(+) 一致。

### 3.2 硬约束 —— PASS

- **无新增依赖**：`pyproject.toml`/`requirements*.lock` 相对 `2ac976f` 零改动（`09`）；tracer 顶层只 import 标准库 + 包内 `.contracts`/`.versioning`（`.store` 仅在 `TYPE_CHECKING` 下），AST 断言 `09` 通过；`__init__` 追加导出不引入外部包。
- **零真实模型/OCR/embedding/rerank 调用**：`test_tracer.py` 只 import 标准库 + pytest + `mktkb`（`09` AST），无 provider/network 导入与调用；本包测试 0.29s 完成；独立探针同样不调用外部。
- **不读 `.env`**：tracer 源码与测试源码均无 `os.environ`/`dotenv`/`os.getenv`（`09` AST 断言；tracer 无 `import os`）；`.env` 文件存在但本包代码不读取。
- **测试只写 tmp_path**：`test_tracer.py` 中 2 处 `TraceRepository(...)` 路径均为 `tmp_path / "traces.sqlite3"`（`09`）；`var/` 下 SQLite 本次会话新增/修改数=0、`docs/evidence` 之外无新增 SQLite（`12`）。
- **工作树审计**（`12`）：已跟踪改动仅 `.claude/handoffs/_index.md`——我在 23:56 首次 `git status` 时它已是 M（PM 既有改动），此后 00:28 又被 PM/其它助手在共享工作区更新（非我写入）；不可解释未跟踪文件=0；除 `docs/evidence/` 与 `.claude/handoffs/` 外本次会话修改文件=0；`.claude/handoffs/` 下另有 4 个 PM/其它助手的并发改动（`_index.md`、`2026-11-04-p1-design.md`、`2026-11-04-p1-task-breakdown.md`、`_scratch/p1-holdout-validate.py`，均与 T003a 无关）；我新增的只有 `docs/reports/.../verify/T003a/**` 与本 `review.md`。
- **既有全量测试的目录副作用（非本包 commit 内容）**：执行 §6 全量套件时，既有 T09/RAG acceptance 测试会写入 gitignore 的 `docs/evidence/` 下 47 个文件（`12` 计数；该目录不入 commit、非本包改动）。handoff §4 的“不碰 docs/evidence”针对交付物/commit 边界，该 commit 未包含该路径，工作树亦无 tracked 改动；建议 PM 知悉这一既有测试行为。
- **未 push、未 commit、未改 `_index.md`**：由工作树审计与 HEAD 未变化证明。

### 3.3 测试非空转 —— PASS

- 静态：58 个测试函数 / 66 用例、216 处 assert/raises、无 skip/xfail/monkeypatch、关键行为（incomplete、异常 error、parent_span_id、完整性、best-effort）均有针对性断言（`09`）。
- 行为：**仓库外变异探针 08**——12 个代表性缺陷（parent_span_id 置 None、finish 不写库、validate 永远返回空、缺 outcome/path 仍 ok、contextvar 不 reset、off 模式仍哈希、Span 异常不置 error、trace_id 固定、attributes ASCII 转义、忽略条件 Span、内层 trace 继承外层 Span 栈、自动 finish 缺失）被**我的独立探针 12/12 与开发者 `test_tracer.py` 12/12 同时捕获**；未变异对照副本两者均通过。
- 因此“测试通过”不是靠空断言/无断言取得的；且我对 §5.1–§5.7 的行为另有 1212 条独立断言（`07`）。

---

## 4. report §4“偏离”逐条判定（是否越界）

| # | report 自述偏离 | 我的判定 | 依据 |
| --- | --- | --- | --- |
| 1 | `start_trace` 追加可选 `content_mode`/`hmac_key` | **允许** | 同属 `tracer.py`；原计划调用形态完全兼容；配置来源（config.py）属 T003c/d，内核注入是 §5.6 可测试的必要条件；report §5 已列交接风险 |
| 2 | `path` 类型放宽允许 `None` | **允许** | §5.4 要求可表达“未设置 path→incomplete”；默认仍 `TracePath.RAG`，正常调用不变 |
| 3 | 条件 Span 属性经 `annotate` 并入 `filter_decisions_json`；validate 宽松读任意 `*_json` | **允许** | 设计未规定载体；T001 的 41 字段无通用 attributes；report 已写明约定与 T003c/d 遵守要求 |
| 4 | Trace status 语义补充（replayed/incomplete/error 结局） | **允许** | §5.4 要求 incomplete；设计仅列“ok/replayed/error 等”；实现顺序在 report §2.4 自述，实测与之一致（`10` §1） |
| 5 | finish 捕获组装异常（超出“仅写入失败不抛”） | **允许（同向加固）** | 不中断调用方与 §6.6 一致；公开 API 下组装异常路径基本不可达（`10` §8），无越界行为 |
| 6 | Span `annotate(status,error_code)` 字段级覆盖 | **允许（扩展）** | 不违反 §5.3/§5.4；供受控降级标记；但属额外语义，T003c/d 使用需谨慎（见 §5 问题 4） |
| 7 | `contracts.__all__` 未改（星号导入不含新函数） | **符合 §2** | §2 只允许“末尾追加纯函数、不改既有常量/类/函数”；`__all__` 逐字未改（`05`），包级 `__init__` 已追加导出，可用性无问题 |
| 8 | TDD RED 证据为测试首版 | **不构成 §5 判据** | RED 证据显示 `ImportError` 收集失败（dev 证据 01），实现后 66 passed；与 T002 同口径，可接受 |
| 9 | 不实现 redacted/full、不接业务代码等“未做” | **符合范围** | 与 handoff §2/§4 一致；redacted/full 已显式 fail closed |
| 10 | 工作树中既有 PM 未跟踪文件未动 | **属实（commit 边界内）** | commit 与工作树审计（`04/12`）显示本包未 add 这些文件；我在首次 `git status` 时它们已存在。注：共享工作区中 PM 在验收期间继续更新了 `_index.md` 等 4 个文件（非本包/非本验收者，见 §5 问题 9） |

未发现越界偏离。

---

## 5. 发现的问题（均非阻断）

1. **dev 证据 05 不是最终 HEAD 的 stat**：`docs/reports/OBS-EVAL/P0/evidence/T003a/05-git-show-stat.txt` 记录的是 amend 前 `C1′=826aa33`（9 files/2116 insertions），而最终 HEAD 是 `dea4d5d`（12 files/2274 insertions）。report §3 已解释 amend 机制，但 handoff §6 要求的 `git show --stat --oneline HEAD` 原文未按最终 HEAD 留存。我的证据 04 已补采最终 HEAD stat；建议（非返工）后续 amend 后重采或把该差异写进证据说明。
2. **`replayed=True` 覆盖 incomplete**：`replayed` 且缺 outcome 时 status=replayed（`10` §1）。设计 §6.1 支持“纯重放写 status=replayed”；§5.4 的 incomplete 口径按普通执行尝试判定。建议 T003b/c/d 与 PM 知悉该优先级，避免 gate 误判。
3. **内核接受 `mode="live"`**：`_coerce_mode` 只校验枚举合法性，`mode="live"` 实测被接受并写入记录（`10` §2），而设计 §9/TraceMode 契约写“P0 禁止 live”。§5 未要求内核拒绝，接线中间件（T003b）必须保证不传 live；建议在 T003b 加硬校验。
4. **`annotate` 可覆盖启动参数字段**：实测 `annotate(mode=..., scope=..., replayed=..., path=..., outcome_kind=...)` 会覆盖 `start_trace` 参数（只保留 9 个保留字段：trace_id/status/latency 等，`tracer.py:91-103`），例如可把记录改成 `mode=live`、`status=replayed`（`10` §3）。当前 T003c/d 为可信调用方，§5 未禁止；但这削弱“Trace 字段权威性”，建议 T003c/d 约定只写数据字段，或在后续任务把启动参数列入保留字段。
5. **conditional 属性读取对非法 JSON fail-open**：任意 `*_json` 字段若为非法 JSON 文本，`validate_required_spans` 静默忽略该字段（`10` §5），可能漏判条件 Span。tracer 对 `filter_decisions_json` 的 annotate 是 fail closed 的，风险主要在其它 JSON 字段被调用方写入非法文本；建议 T003c/d 只写 canonical JSON，Task 5 gate 可加 JSON 合法性检查。
6. **“未开启”没有内核级开关**：本包无 `trace_enabled` 语义，§5.5 只能以“无 repo 不建 DB + 未 start 时 `current_trace()=None`”验证；开关与中间件属 T003b 范围，report 已说明，判定 PASS（口径记录）。
7. **contextvars 不跨线程**：trace 内 spawn 的 `threading.Thread` 中 `current_trace()=None`（`10` §4）。若 T003b/c/d 使用线程池/后台线程执行被观测阶段，需显式传 trace；属后续接线风险。
8. **设计 §6.5 的“答案/上下文哈希”无契约载体**：T001 冻结的 `TraceRecord` 无 answer/context 哈希字段，本包只实现问题哈希；属 T001 契约/设计缺口，不是本包越界，但 P0 后续需明确答案侧是否需要用 JSON 字段承载。
9. **共享工作区并发改动**：`.claude/handoffs/_index.md`（tracked M，00:28 更新）与 3 个 PM/其它助手的 P1 文档/脚本在验收期间被并发修改（`12`），均非本验收者所写、与 T003a 无关；我在 23:56 首次 `git status` 时已确认 `_index.md` 为 PM 既有改动。全量测试另对 gitignore 的 `docs/evidence/` 写入 47 个既有验收证据文件（`12`），同样非本包 commit 内容。以上仅供 PM 知悉共享工作区的并行状态。
10. **基线等价套件时序 flake**（`test_chat.py::test_g08`）：同一基线套件共跑 3 次，1 次完整通过（1110 passed，`11c`）、2 次命中该既有模型预算取消时序用例（1 failed/1109 passed，`11/11b`）；单测单独复跑通过（`13`），HEAD 全量 1176 passed 未复现。属既有测试的环境时序 flake，与 T003a 无关（diff 未触碰该路径），供 PM 知悉。

---

## 6. 未覆盖 / 无法由本包判定（按范围）

1. **中间件与开关接线**（T003b）：`trace_enabled`、`X-Trace-ID`、`app.state.trace_repo` 生命周期、请求失败/异常路径、`finish` 与响应顺序。
2. **内容模式配置注入**（T003c/d）：`settings.trace_content_mode`、`MKTKB_TRACE_HMAC_KEY` 解码后是否真被传入 `start_trace`；本包只验证内核接受显式参数。
3. **业务路径埋点与 Span 完整性**（T003c/d，Task 3 Step 4）：各阶段 Span 是否实际创建、粒度/属性是否符合设计 §6.4，gate 侧 `required_spans ∪ conditional_required_spans` 是否能全部满足。
4. **真实模型/OCR/embedding/rerank 零调用**：只能以“测试导入边界 + 运行时长 + 无网络依赖 + 无 provider 导入”佐证，无法像审计网络流量那样绝对证明进程级无外部调用；本包测试仅 observability 模块。
5. **跨线程/并发 task 共享同一 `TraceContext` 的 Span 归属语义**：设计未定义，本包未覆盖；已记录 contextvars 不跨线程的限制。
6. **SQLite 写延迟/P95、保留策略与容量**（设计 §13）：属 T003 接线后实测，本包未做性能验证。
7. **`redacted`/`full` 内容模式**：P0 明确未实现（fail closed），未验证脱敏规则。
8. **变异探针只代表 12 个缺陷**：不能证明无其它缺陷；但结合 1212 条独立断言与 12/12 双端捕获，非空转证据充分。

---

## 7. 复跑命令与证据清单

```powershell
$env:MKTKB_PROJECT_TOTAL_LIMIT_CNY = "20.0"
.\.venv\Scripts\python.exe -B -m pytest backend/tests/observability/test_tracer.py -q -p no:cacheprovider --basetemp backend\.pytest-tmp\verify-t003a-tracer   # 66 passed
.\.venv\Scripts\python.exe -B -m pytest backend/tests/observability -q -p no:cacheprovider --basetemp backend\.pytest-tmp\verify-t003a-obs                       # 158 passed
.\.venv\Scripts\python.exe -B -m pytest backend/tests -q -p no:cacheprovider --basetemp backend\.pytest-tmp\verify-t003a-full-final                             # 1176 passed
git show --stat --oneline HEAD        # dea4d5d, 12 files, 2274 insertions(+)
git show --name-status dea4d5d        # 12 个允许路径
git diff 2ac976f..dea4d5d -- <受保护路径>   # 空
```

| 证据 | 内容 |
| --- | --- |
| `00-context.txt` | 环境/HEAD/命令上下文与证据索引 |
| `01-pytest-tracer.txt` | 本包测试：66 passed |
| `02-pytest-observability.txt` | observability：158 passed |
| `03-pytest-full.txt` | 全量：1176 passed / 0 failed / 0 error |
| `04-commit-boundary.txt` | HEAD/父/分支、name-status、stat、受保护路径、删除检查、numstat |
| `05-contracts-init-diff.txt` | contracts 仅末尾追加（无 `-` 行；前缀一致；`__all__` 未改）+ `__init__` 纯追加 |
| `06-sha256-and-evidence-audit.txt` | 4 个交付物 SHA-256 与 dev 证据 06 完全一致；dev 证据 00–05 哈希核对；证据 05 stale 记录 |
| `07-independent-probe.txt` | 仓库外独立探针：`PROBE-PASS::1212 checks in 8 sections` |
| `08-mutation-probes.txt` | 12 个变异：control 通过、12/12 被独立探针与开发者测试同时捕获（`MUTATION-SUMMARY::... all_ok=True`） |
| `09-static-checks.txt` | 静态/结构检查：`STATIC-SUMMARY::pass=57 fail=0` |
| `10-edge-observations.txt` | 边界观察：replayed 优先级、live、annotate 覆盖、子线程、非法 JSON、不可序列化属性等 |
| `11-baseline-2ac976f-full.txt` | 基线等价复跑（第 2 次）命中既有 `test_chat.py::test_g08` 时序 flake 的运行（1 failed/1109 passed） |
| `11b-baseline-flake-run.txt` | 基线等价复跑（第 1 次）同样命中 `test_chat.py::test_g08` 时序 flake 的运行 |
| `11c-baseline-pass-run-utf8.txt` | 基线等价复跑完整通过：**1110 passed / 0 failed / 0 error**（本次唯一完整通过的一次；原 Tee UTF-16LE 输出无损转码 UTF-8） |
| `12-worktree-audit.txt` | 工作树/未越界审计（tracked 改动仅既有 `_index.md`；var DB 零新增；docs/evidence 副作用计数） |
| `13-baseline-flaky-test-isolated.txt` | flake 用例单独复跑：1 passed（确认时序 flake） |
| `probe_tracer.py` 等 | 上述独立探针/变异/静态/审计脚本原文（仓库外工具，随证据保存） |

---

## 8. 最终判定

- **§5.1–§5.8：8/8 PASS**；**提交边界 PASS**；**硬约束 PASS**；**测试非空转 PASS**。
- **无阻断返工项**。建议（非必须）：重采 dev 证据 05 为最终 HEAD 的 `git show --stat`；T003b/c/d 承接 report §5 风险与本报告 §5 观察 2/3/4/7/8。
- 本次验收未修改任何交付物、未 commit、未 push、未改 `_index.md`；仅新增本报告与 `verify/T003a` 证据。

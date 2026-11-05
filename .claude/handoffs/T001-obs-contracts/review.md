# T001 独立验收报告（review.md）

> **验收人**：`verify-t001`（独立验收助手，未参与开发，与开发方不共享上下文）
> **验收时间**：2026-11-04 22:50–23:00（Asia/Shanghai）
> **工作目录**：`D:\GPT项目\市场部AI知识库`（Windows / PowerShell，Git 仓库）
> **待验对象**：分支 `p0/obs-eval` @ `7b02f40`（`p0/T001 contracts & versioning`），父提交 `8e44158` = `main` = tag `v0.1-local-20261104`
> **判定原则**：只认本次亲自复跑与独立探针结果；`report.md` 仅作线索，不作为证据。
> **总判定**：**PASS** —— handoff §5.1–§5.8 全部通过，提交边界与硬约束无违规；发现 6 项非阻塞问题（§6），均为报告/证据链准确性，不影响 §5 判定与交付物功能。
> **复跑环境**：`.venv` Python 3.12.7；每条命令先设 `$env:MKTKB_PROJECT_TOTAL_LIMIT_CNY = "20.0"`；`backend\.pytest-tmp` 已存在（gitignored，dev 遗留）。
> **本次证据**：`docs/reports/OBS-EVAL/P0/evidence/verify/T001/`（01–11 原始输出 + 3 个独立探针源码）。

---

## 1. 验收标准逐条判定（handoff §5）

| # | 验收标准 | 判定 | 关键证据（本次复跑/独立探针） |
| --- | --- | --- | --- |
| 5.1 | 三套版本常量精确 | **PASS** | `contracts.py:18-20`；`07-independent-probe.txt` 直接断言三值；`test_contracts.py:111-114` |
| 5.2 | §6.4 全 8 行逐行断言 + 两个易错点 | **PASS** | `contracts.py:55-72`；`test_contracts.py:34-47,120-137`；独立探针按设计原文重录 12 组合逐项相等，两易错点不含断言通过（`07`） |
| 5.3 | 条件 Span 只认四键、空 attrs 空集 | **PASS** | `contracts.py:75-80,107-115`；`test_contracts.py:170-205`；独立探针补测 `None`/未知键/多键并集（`07`） |
| 5.4 | `pipeline_version` 同输入同值、prompt/top_k 变化即变、默认组件延迟导入、格式写入文档 | **PASS** | `versioning.py:92-124`；`test_versioning.py:34-77,83-117`；独立探针：4/4 业务常量 monkeypatch 生效、AST 顶层仅 stdlib、全新子进程导入成功、摘要=手工 canonical JSON sha256[:12]（`07`/`08`）；文档 `trace_schema_v0_1.md:175-195` |
| 5.5 | `hash_question` 空 HMAC key 真抛 `ValueError`；64 hex 无原文；sha256 允许空 key | **PASS** | `versioning.py:146-164`；`test_versioning.py:123-162`；独立探针用 `hmac`/`hashlib` 手工重算逐字节一致（`07`/`08`） |
| 5.6 | `config_hash` 凭据键豁免/拒绝逻辑、白名单变化生效、白名单写入文档 | **PASS** | `versioning.py:35-56,127-143`；`test_versioning.py:183-199`；独立探针核对文档白名单 16 项与 `CONFIG_HASH_FIELDS` **逐项同序一致**（`08`） |
| 5.7 | `TraceRecord`/`SpanRecord` frozen、覆盖 §6.3（41/9）、可实例化、可序列化 | **PASS** | `contracts.py:118-182`；`test_contracts.py:230-327`；独立探针按设计原文重录字段集：41/9 精确相等、frozen、`asdict`+`json.dumps` 通过、写入抛 `FrozenInstanceError`（`07`） |
| 5.8 | 新增测试全过；全量无新增失败（本包 68；全量 1086/0/0） | **PASS** | 本次复跑：observability `68 passed`（`01`）；全量 `1086 passed, 1 warning`、**0 failed / 0 error / 0 skipped**（`03`）；collect：68（36+32，`02`/`02b`）与全量 1086（`11`） |

### 5.1 三套 Schema 版本常量
- 复跑命令（探针 07）：断言 `TRACE_SCHEMA_VERSION == "mktkb.trace.v0.1"`、`CASE_SCHEMA_VERSION == "mktkb.eval.case.v0.1"`、`GATE_SCHEMA_VERSION == "mktkb.gate.v0.1"` → 全过。
- 代码位置：`backend/src/mktkb/observability/contracts.py:18-20`；测试 `backend/tests/observability/test_contracts.py:111-114`。

### 5.2 设计 §6.4 全 8 行 Span 规则（含两个易错点）
- 设计原文：`docs/superpowers/specs/2026-11-04-mktkb-observability-evaluation-design.md:165-176`（8 行表）。
- 实现：`contracts.py:55-72`；测试把 8 行展开为 12 个 path+outcome 组合做参数化断言（`test_contracts.py:34-47,120-122`）。
- **独立复核（不引用包内测试常量）**：探针按设计原文逐行重录 8 行、展开 12 组合，`required_spans` 返回 `frozenset` 且集合**完全相等**（`07-independent-probe.txt`）。
- 两个易错点实测：
  - `rag + clarification` → `{"parse","commit"}`，且断言 `"answer" not in`、`"recall" not in`（`test_contracts.py:125-129`；独立探针同样断言）；
  - `legacy + not_found` → `{"intent_parse","retrieve","commit"}`，且断言 `"query_expansion" not in`、`"answer" not in`、`"model_answer" not in`（`test_contracts.py:132-137`；独立探针同样断言）。
- 设计表外组合的 fail-closed（`rag+not_found`/`rag+service_error`/`legacy+error` 抛 `ValueError`）见 `test_contracts.py:152-160`，实测真抛。

### 5.3 `conditional_required_spans(attrs)`
- 实现：`contracts.py:75-80`（仅 `_CONDITIONAL_SPANS` 四键）、`contracts.py:107-115`。
- 测试：四键各自、`{}` 空集、未知键忽略、多键并集、`False` 不要求（`test_contracts.py:170-205`）。
- 独立探针：额外验证 `None` → `frozenset()`、四键并集、未知真值键不产生 Span（`07`）。

### 5.4 `pipeline_version(...)`
- 实现：`versioning.py:92-113`（默认组件在 `_default_pipeline_components()` **函数体内**延迟 import）、`versioning.py:116-124`。
- 测试：同输入同值、`prompt`/`top_k` 变化即变、key 序无关（`test_versioning.py:34-59`）；延迟导入用 monkeypatch 证明（`test_versioning.py:70-77`）；AST 证明两模块顶层仅 stdlib（`test_versioning.py:83-96`）；全新子进程导入成功（`test_versioning.py:99-117`）。
- 独立探针（`07`/`08`）：
  - 4/4 默认业务常量（`QA_ENGINE_VERSION`/`SCHEMA_VERSION`/`INDEX_CACHE_VERSION`/`TOKENIZER_VERSION`）在 import 之后被 monkeypatch 仍能改变 `pipeline_version()` → 确为调用期解析；
  - `pipeline_version(components)` == 手工 `sha256(canonical_json(components))[:12]`；
  - `pipeline_version()` 默认摘要 == 按文档 §7.2 组件映射手工重算的摘要（`735da1397044`），12 个键与 `versioning.py:100-113` 一致；
  - 子进程输出 `mktkb.main_loaded=True`（见 §6-P4：父包既有行为，报告已披露；无循环导入失败）。
- 摘要格式文档：`docs/evaluation/trace_schema_v0_1.md:175-186` 明确 `sha256(canonical_json).hexdigest()[:12]` 与 canonical JSON 参数；`hash_question` 为 64 hex。

### 5.5 `hash_question(...)`
- 实现：`versioning.py:146-164`（`hmac-sha256` 空 key → `ValueError`；`sha256` 允许空 key；未知 algo → `ValueError`；非 str → `TypeError`）。
- 测试：`test_versioning.py:123-162`（`pytest.raises(ValueError)` 真负例，非仅存在性断言）。
- 独立探针：空 key 真抛 `ValueError`；返回值 64 hex 且不含原文；与手工 `hmac.new(key, q.encode(), sha256).hexdigest()`、`hashlib.sha256(...)` **逐字节一致**（`07`/`08`）。

### 5.6 `config_hash(config)`
- 实现：白名单 `versioning.py:35-52`；凭据键正则 `versioning.py:55-56`（`key|secret|token|password`、IGNORECASE）；摘要 `versioning.py:127-143`。
- 测试：8 种大小写/组合凭据键 → `ValueError`（`test_versioning.py:183-192`）；16 个白名单字段逐一变化（`test_versioning.py:194-199`）；白名单外忽略（`:207-209`）。
- 独立探针：文档代码块 16 项与 `CONFIG_HASH_FIELDS` **逐项同序相等**；`config_hash` == 手工 `sha256(canonical_json(白名单子集))[:12]`；`api_key`/`API_KEY` 等真抛 `ValueError`（`07`/`08`）。文档：`trace_schema_v0_1.md:196-205`。

### 5.7 `TraceRecord` / `SpanRecord`
- 实现：`contracts.py:118-182`，两个 `@dataclass(frozen=True)`。
- 字段覆盖（独立按设计 §6.3 重录）：`traces` 41 字段、`spans` 9 字段，**集合精确相等、无缺无多**（`07`；设计原文 `design.md:127-152`）；可选字段默认 `None`；`TraceRecord()` 空构造 + `asdict`+`json.dumps` 不抛；赋值抛 `FrozenInstanceError`。
- 测试：`test_contracts.py:230-327` 覆盖 frozen、字段集、实例化、序列化、默认值、不可变。

### 5.8 新增测试全过 + 全量无新增失败
本次**亲自复跑**（原始输出见括号内证据文件）：

| 命令 | 结果 |
| --- | --- |
| `.\.venv\Scripts\python.exe -B -m pytest backend/tests/observability -q -p no:cacheprovider --basetemp backend\.pytest-tmp\obs-contracts` | **68 passed, 1 warning in 1.60s**，exit 0（`01`） |
| `.\.venv\Scripts\python.exe -B -m pytest backend/tests -q -p no:cacheprovider --basetemp backend\.pytest-tmp\t001-full` | **1086 passed, 1 warning in 372.66s**，exit 0，**0 failed / 0 error / 0 skipped**（`03`） |
| `pytest backend/tests --collect-only -q` | 1086 tests collected（`11`） |
| `pytest backend/tests/observability --collect-only -q` | 68 tests collected（`02`）；分文件 36 + 32（`02b`） |
| `git rev-parse --short HEAD` / `git show --stat --oneline HEAD` | `7b02f40` / 16 files changed, 1588 insertions(+)（`04`/`05`） |

**无新增失败的独立论证**（不依赖 dev 自报基线）：
1. 待验提交相对 `8e44158` 的 `backend/tests` 变更 **全部是新增文件**（`A backend/tests/observability/{__init__,test_contracts,test_versioning}.py`），无任何既有测试/`conftest` 改动（`git diff --name-status 8e44158 7b02f40 -- backend/tests`）；
2. HEAD 全量 **0 failed / 0 error / 0 skipped**；
3. 因此不存在"基线通过、HEAD 失败"的既有测试；`1086 - 68 = 1018` 与 dev 自报基线数一致（一致性校验，非采信依据）。
- 1 warning 为既有 `fastapi/testclient` 的 `StarletteDeprecationWarning`（基线同 warning），非本包引入。

---

## 2. 提交边界核查（handoff §2/§4/§7）

| 检查 | 结果 |
| --- | --- |
| 分支/提交数 | `p0/obs-eval` 相对 `main` 仅 1 个提交：`7b02f40 p0/T001 contracts & versioning`（父 `8e44158`）；无多余提交、无 merge |
| `git show --name-only 7b02f40` | 16 个文件，**全部新增（A）**，无删除/改名/修改既有文件 |
| 越界业务代码 | **无**：无 `main.py` / `qa/` / `rag/` / `conversations/` / `retrieval/` 等业务代码改动 |
| 依赖/构建 | **无**：`pyproject.toml`、requirements/lock 均未改（diff 为空） |
| 禁止目录 | **无**：无 `docs/evidence/**`、`var/**`、`fixtures/**`、账本/GO/归档区改动 |
| 既有测试 | **无**改动；仅新增 `backend/tests/observability/` 三个文件 |
| 交付物对齐 §2 | 8 个交付文件 + `docs/reports/OBS-EVAL/P0/evidence/T001/` 7 个证据 txt + `report.md`，均落在 §2 允许路径内 |
| 其他手续文件 | 未 add `handoff.md`/`prompts/*`（工作区未跟踪，属 PM）；`_index.md` 的 M 状态**不在提交内**（`git diff --name-only 8e44158 7b02f40 -- .claude/handoffs/_index.md` 为空），本验收未触碰该文件 |
| push / 合并 | **未 push**（`git branch -r` 无 `p0/obs-eval`）；`main` 仍为 `8e44158` |
| 提交信息 | 恰为 `p0/T001 contracts & versioning` |

附加完整性抽查：用当前工作区重算 8 个交付物 SHA-256，与提交内 `06-deliverable-sha256.txt` **8/8 一致**（`06-sha256-recheck.txt`），证明证据 06 与提交内容未漂移。

---

## 3. 硬约束核查（handoff §4）

| 约束 | 核查方式与结果 |
| --- | --- |
| 零真实模型 / OCR / embedding / rerank 调用 | 新增源码/测试无任何 provider/gateway/网络客户端构造或调用（grep `httpx|requests|socket|urllib|openai|dashscope|ollama|TestClient` 在 5 个新增 py 文件中 0 命中）；新增测试 1.60s 完成；`pipeline_version()` 默认组件仅读取常量与构造纯 dataclass `RagConfig()`（`rag/config.py` 无 `__post_init__`、env 读取只在未调用的 `from_env`） |
| 不读 `.env` | 新增代码无 `dotenv`/`.env` 文件读取（grep 仅注释文字提及）；测试进程沿用既有 `backend/tests/conftest.py:60-77` 的 `Settings.model_config.env_file=None` 隔离；`pipeline_version` 默认路径不实例化 `Settings` |
| 无新增依赖 | 新增模块顶层 import 仅 stdlib（AST 探针 `07`/`08` 复核：`hashlib/hmac/json/re/enum/pathlib/typing/dataclasses`）；测试仅依赖既有 `pytest`；依赖清单/`pyproject` 未改 |
| 不写 SQLite / 不接执行路径 | 新增代码无 sqlite/文件写入；仅延迟 import 只读常量与 `RagConfig`（handoff §3 明确允许）；`observability/__init__.py` 无副作用 |
| 不打印凭据 | 新增代码/测试/证据 txt 扫描 `sk-*`/`Bearer`/`api_key=`/`MKTKB_TRACE_HMAC_KEY=` 模式 0 命中 |
| 不修改既有测试/业务代码 | 见 §2 提交边界；工作区交付物与 HEAD 一致（`git diff --name-only HEAD` 仅 PM 的 `_index.md`） |

---

## 4. "测试是否空转"抽查（变异测试，独立探针）

为证伪"断言只 import/只查常量/只走形式"，在**仓库外临时副本**中对实现植入 10 个行为破坏变异，逐一要求测试套件转红；仓库交付物未被修改（探针源码 `probe_mutation.py`，输出 `09-independent-probe-mutation.txt`）：

| 变异 | 后果 | 结果 |
| --- | --- | --- |
| M1 `rag+clarification` 错加 `answer` | 2 failed | **CAUGHT** |
| M2 `legacy+not_found` 错加 `query_expansion` | 3 failed | **CAUGHT** |
| M3 条件 Span 认第 5 个未知键 | 1 failed | **CAUGHT** |
| M4 `TraceRecord` 改 `frozen=False` | 2 failed | **CAUGHT** |
| M5 `TraceRecord` 删除设计字段 `degraded_json` | 2 failed | **CAUGHT** |
| M6 `hash_question` 不再拒绝空 HMAC key | 1 failed | **CAUGHT** |
| M7 `config_hash` 不再拒绝凭据键 | 8 failed | **CAUGHT** |
| M8 `pipeline_version` 忽略显式 components | 5 failed | **CAUGHT** |
| M9 默认组件改为 import 期绑定 | 4 failed | **CAUGHT** |
| M10 顶层新增业务包 import | 1 failed（AST 测试） | **CAUGHT** |
| 对照：未变异副本 | 68 passed | 基线有效 |

结论：68 项测试对 §5 各验收点的目标行为**有真实约束力**，不存在空转（仅"文档内容是否与实现同步"无自动化断言，见 §7-U4）。

---

## 5. 复核过程与原始证据清单

| 文件（`docs/reports/OBS-EVAL/P0/evidence/verify/T001/`） | 内容 |
| --- | --- |
| `01-pytest-observability.txt` | 亲手复跑：`68 passed, 1 warning in 1.60s` |
| `02-collect-only.txt` / `02b-collect-per-file.txt` | 68 collected；36 + 32 |
| `03-pytest-full.txt` | 亲手复跑：`1086 passed, 1 warning in 372.66s` |
| `04-git-rev-parse.txt` / `05-git-show-stat.txt` | 待验 HEAD = `7b02f4038c23…` / `7b02f40`；16 files, 1588 insertions |
| `06-sha256-recheck.txt` | 8 个交付物 SHA-256 与提交内证据 06 逐项一致 |
| `07-independent-probe.txt` | 独立探针 #1：§5.1/5.2/5.3/5.4/5.5/5.6/5.7 全部 PASS |
| `08-independent-probe-digests-docs.txt` | 独立探针 #2：摘要数学重算 + 文档/代码/设计三方一致性全部 PASS |
| `09-independent-probe-mutation.txt` | 变异测试 10/10 CAUGHT |
| `10-consolidated-summary.txt` | 汇总结论（分支/HEAD/边界/复跑数字/状态） |
| `11-collect-full.txt` | 全量 collect 1086 |
| `probe_independent.py` / `probe_digests_docs.py` / `probe_mutation.py` | 可复现的独立探针源码（只用 stdlib + 契约模块） |

说明：`04`/`05` 为本次针对**最终 HEAD** `7b02f40` 重跑所得；dev 提交内的 04/05 记录的是 amend 前 `C1=6680f85`（见 §6-P2）。

---

## 6. 发现的问题（均非阻塞，不影响 §5 PASS 判定）

- **P1（低，报告准确性）**：`report.md:17-18` 声称 `test_contracts.py` 25 项、`test_versioning.py` 23 项，实测 collect 为 **36 / 32**（合计 68 正确）。原文数字与证据不符，建议更正为 36/32。
- **P2（低，证据链）**：提交内 `05-git-show-stat.txt` 为 13 文件、`04-git-rev-parse.txt` 为 `6680f85`，是对 **amend 前 C1** 的采集；最终 HEAD `7b02f40` 是 16 文件（含 report.md 与 04/05 自身），而最终 HEAD 的 `rev-parse`/`show --stat` 输出**未落入任何正式证据文件**（`report.md:100-105` 仅说明折中并称"见回复/git log"，未记录最终 sha 值）。`report.md:100-105` 已披露该单提交自引用折中。建议后续任务把"最终 HEAD 元信息"落到 amend 后采集的独立证据文件，避免证据与 HEAD 不对应。
- **P3（低，契约语义）**：设计 §6.4 第 5 行只定义 `legacy`/`legacy_with_rag_candidates` + `answer`；实现让 `legacy_with_rag_candidates` 的 `not_found`/`clarification`/`service_error` 也继承 legacy 规则（`contracts.py:97,140-144`；`test_contracts.py:140-144`），而其他表外组合（`rag+not_found` 等）却 fail closed。两者并存是文档化的选择（`trace_schema_v0_1.md:137`、`report.md:118-119`），§5.2 的 8 行不受影响；建议 Task 3/5 埋点前明确该路径族的表外组合策略，避免"部分 fail closed、部分继承"的不一致。
- **P4（提示，范围外）**：`report.md:46-48` 披露的既有事实成立：`mktkb/__init__.py:3` 为 `from .main import create_app`，因此 `import mktkb.observability.*` 会加载业务包。§5.4 的"模块顶层 import 不引入业务包"在**本包两个模块的文件级**成立（AST 测试），且无循环导入（子进程导入成功）；父包行为属既有代码、§4 禁止改动，报告已明示，未按 FAIL 计。
- **P5（很低，报告引用漂移）**：`report.md` 少量行号越界/偏移，如 `test_contracts.py:230-329`（文件共 327 行）、`test_versioning.py:62-78`（延迟导入用例实际 70-77）、`187-192`（凭据参数化实际 183-192）。不影响可复现性。
- **P6（提示，设计如此但需注意）**：凭据键正则包含 `token`，导致合法字段名如 `max_output_tokens` 无法进入白名单/摘要；`trace_schema_v0_1.md:204-205` 与 `report.md:134` 已注明，属设计 §6.5 要求，非本包缺陷。

## 7. 未覆盖项（明确说明，不冒充已验证）

- **U1 基线全量未独立重跑**：未在 `8e44158` 工作树上再跑一次 1018 项（避免切换/暂存工作区带来的副作用，任务亦允许"只核对提交新增测试数与失败数为 0"）；本报告以"HEAD 0 failed + 既有测试零改动 + collect 68/1086"完成等价论证（§5.8）。
- **U2 历史过程证据未复现**：`01-pytest-red.txt`（TDD RED）与 `00-baseline-pytest.txt`（改动前基线 1018）为开发期一次性证据，无法在不改动工作区的前提下原样复现；二者与本次结果数字自洽（1018+68=1086），仅作一致性参考，不作为 PASS 依据。
- **U3 运行期"零真实调用"未做网络抓包/系统调用级监测**：结论基于静态扫描（无 provider/网络客户端引用）、既有 conftest 的假网关/`.env` 隔离、以及测试耗时与全量结果；未使用代理/抓包证明运行期绝对无外联。
- **U4 文档内容无自动化契约测试**：包内唯一的"documented"断言只检查白名单非空（`test_versioning.py:194-199`），文档白名单/摘要格式/`dataset_version` 公式与实现的同步由本次独立探针（`08`）人工核对通过；建议后续把文档-代码同步纳入测试（T001 范围外）。
- **U5 `conditional_required_spans` 的 `None` 入参**：包内测试只测 `{}`，未测 `None`；本次独立探针已实测 `None → frozenset()` 行为正确，属测试面小缺口，非功能缺陷。
- **U6 文档其余章节**：本验收只逐条核对 handoff §5 涉及的字段/规则/摘要格式/白名单及设计 §6.3/§6.4/§7.3 一致性；`trace_schema_v0_1.md` §8 存储写入语义、`eval_data_v0_1.md` 数据集与防污染条款属后续任务范围，未逐字审计。

## 8. 返工建议

**无阻塞返工项。** §5.1–§5.8 全部 PASS，提交边界与硬约束合规。建议（可选、低优先级，不阻塞本包验收）：
1. 更正 `report.md:17-18` 的 per-file 测试数（36/32），避免后续审计再次踩到不一致；
2. 后续任务（Task 3/5 埋点前）确认 P3 中 `legacy_with_rag_candidates` 表外组合的契约策略；
3. 后续任务把最终 HEAD 的 `rev-parse`/`show --stat` 输出落到 amend 后采集的证据文件（P2）。

---

### 结论摘要（≤10 行）

1. §5.1 PASS（三常量精确）；§5.2 PASS（8 行/12 组合逐项相等，两易错点真实不含）。
2. §5.3 PASS（四键、空集、未知忽略）；§5.4 PASS（同值/敏感、延迟导入、AST、子进程、文档格式）。
3. §5.5 PASS（负例真抛 `ValueError`，64 hex 无原文，HMAC/SHA256 手工重算一致）；§5.6 PASS（凭据拒绝、16 字段白名单与文档逐项一致）。
4. §5.7 PASS（frozen；41/9 字段精确覆盖设计；可实例化/序列化/不可变）；§5.8 PASS（observability 68 passed；全量 1086 passed / 0 failed / 0 error；基线 1018+68 自洽）。
5. 提交边界 PASS（16 文件全新增、均属 §2；无业务代码/pyproject/既有测试/证据目录越界；单 commit；未 push）。
6. 硬约束 PASS（无新增依赖、顶层仅 stdlib、无网络/模型引用、无 `.env` 读取路径、无凭据输出）。
7. 空转抽查 PASS：10 个变异全部被测试捕获（临时副本，未改仓库）。
8. 非阻塞问题：report 每文件测试数 25/23→实测 36/32；证据 04/05 为 amend 前 C1 快照；`legacy_with_rag_candidates` 表外组合策略建议后续确认。
9. 未覆盖：基线 1018 未独立重跑（以零失败+新增 68+零既有改动等价论证）；运行期无抓包级证明；文档-代码同步无自动化测试。
10. 返工范围：**无阻塞返工**；可选低优先级仅修正 report 数字与证据采集时点。

# T003d 独立验收 review（P0 第 6 包：QA/legacy 路径 Span 与 outcome 绑定 + T003c 移交的 reason-aware 契约修订）

> 验收者：独立验收助手（无 T003d 开发会话历史）。**结论只基于本会话在仓库外隔离副本的复跑与独立探针**；
> `report.md` 仅作定位线索，未作为 PASS 证据。
> 对象：`b811f9f`（`p0/T003d qa legacy spans`，父 `776497f`，基线 `main` @ `8e44158`，分支 `p0/obs-eval`）。
> 隔离副本：`%TEMP%\t003d-0915e17e\t003d`（`git archive b811f9f` + Python tarfile 解包，**未用 worktree、未改主仓库 .git**）。
> 工具链：`D:\GPT项目\市场部AI知识库\.venv\Scripts\python.exe -B`（Python 3.12.7 / pytest 9.1.1），
> `PYTHONPATH=<copy>\backend\src`，`MKTKB_PROJECT_TOTAL_LIMIT_CNY=20.0`；basetemp 在副本内；
> 全程串行（未并发跑两个 pytest），未出现 MemoryError/资源失败。
> 证据目录：`docs/reports/OBS-EVAL/P0/evidence/verify/T003d/`（ASCII 文件名，UTF-8 无 BOM）。

## 0. 总判定

**FAIL（仅 §5.11 的一个子情形）**：§5.1–§5.10、授权修改最小性、提交边界、证据卫生、测试非空转均 PASS；
但 §5.11 要求的“实际可达 outcome 按实际执行给出必需 Span 行”在 **commit 阶段 revision 变化把解析级早退结果升级为
`knowledge_changed`** 这一真实可达路径上不成立（实际 Span `{intent_parse, commit}`，契约要求 `retrieve`，
`validate_required_spans` 返回 `['retrieve']`）。详见 §2.11 / §3.1。

| 验收项 | 结论 | 关键证据 |
| --- | --- | --- |
| §5.1 RAG 产品路径 E2E | PASS | `06-independent-probe.txt`（probe_s51）、`test_paths_e2e.py:216` |
| §5.2 legacy 路径 | PASS | `06`（probe_s52/s53）、`test_paths_e2e.py:251,276` |
| §5.3 多 outcome | PASS | `06`（s53/s511）、`test_paths_e2e.py:299,326,347,365` |
| §5.4 行为不变 | PASS | `06`（s54）、`test_middleware.py:412` |
| §5.5 隐私（hash/HMAC/无原文/无密钥） | PASS | `06`（s51/s55/s511）、`test_paths_e2e.py:588` |
| §5.6 index_sync 仅真同步 | PASS | `06`（s56） |
| §5.7 重放 status=replayed | PASS | `06`（s57） |
| §5.8 硬约束（无新依赖/无禁改文件） | PASS | `09-submission-hygiene.txt` §1–2；全量无新依赖失败 |
| §5.9 `rag+no_answer` reason-aware + 向后兼容 | PASS | `07-contract-matrix.txt`（27 组合 0 意外差异）、`test_contracts.py:175` |
| §5.10 rerank 失败 Span error | PASS | `test_rag_spans.py:425`（目标集全绿） |
| §5.11 legacy 早退/补充行 | **FAIL（单子项）** | 本文件 §3.1；`06-independent-probe.txt` 的 `test_probe_s511_commit_time_...` |
| PM 授权最小既有测试修改 | PASS | `09` §3；`test_middleware.py` 去 9 行仅为失效边界断言+注释 |
| 提交边界（handoff §2/§8） | PASS | `09` §1–2（21 个文件，禁改路径 0） |
| 全量回归 | PASS（环境受限后恢复） | `05-full-suite-restored.txt`：**1266 passed, 0 failed, 0 error** |
| 测试非空转（变异探针） | PASS | `08-mutation-probes.txt`（5/5 变异全部被测试捕获） |
| 证据卫生（00–10） | PASS，附 1 条 LOW | `09` §4（10 的 19/19 sha256 一致；10 漏列 06） |

---

## 1. 环境与方法

1. 隔离：`git archive --format=tar --output=%TEMP%\…\t003d.tar b811f9f`，用 Python tarfile 解包。
   Windows bsdtar 对 70+ 个非 ASCII 成员名报 “Invalid empty pathname”，故改用 Python（574 entries / 486 files / 53.1 MB）。
   证据：`01-isolated-copy.txt`。
2. 首次全量在缺少 gitignored `docs/evidence/**` 的副本里跑：**16 failed / 1235 passed / 15 skipped**；
   16 个失败与 15 个 skip 的根因全部是缺少 `docs/evidence/**`（字体、T04/T05/T06 快照、budget ledger、GO json、
   tokenizer artifact），堆栈直接指向缺失文件，**不涉及 T003d 改动文件**。证据：`03-full-suite-initial.txt`。
3. 控制实验：从共享工作树只读复制 37.8 MB 相关 `docs/evidence` 子集后，同一批 16 失败 + 15 skip 的选中集
   **37 passed**（`04-environment-restored-subset.txt`），证明失败纯属环境资产缺失；随后重跑全量（`05`）。
   副本内被验源码/测试的 sha256 在全部复跑后仍与 `T003d/10` 19/19 一致（`09` §4）。
4. 独立探针 `10-reviewer-probe.py`：不引用交付测试函数体，自己建应用/上传/发布/提问，从真实
   `TraceRepository` 读回 trace/span；复用已验收的共享 fixture（`trace_app`/`trace_chat_app`/`chat_model`）。
   首轮 **10 passed / 1 failed**（唯一失败即 §3.1 发现）。

## 2. §5 逐条判定（命令均为在副本根目录执行）

### §5.1 RAG 产品路径 E2E — PASS
- 命令/证据：`10-reviewer-probe.py::test_probe_s51_rag_answer`（`06-independent-probe.txt`）；
  `.venv\…\python.exe -B -m pytest backend/tests/observability/test_paths_e2e.py -q …`（`02-targeted-tests.txt`）。
- 实测：响应头 `X-Trace-ID` 可反查；`request_id == body["request_id"]`、`http_request_id == X-Request-ID`、
  `path=rag`、`outcome_kind=answer`、`status=ok`；Span 含 `{parse, recall, fuse, answer, commit}`，
  `required_spans(RAG, ANSWER) ⊆ names` 且 `validate_required_spans == []`；
  无 `intent_parse/retrieve/model_answer/answer_validate`；问题原文不在 trace/span 中。
- 代码：`conversations/service.py:2178-2179`（request_id/question）、`qa/service.py:441`（outcome/reason）、
  `test_paths_e2e.py:216-245`。

### §5.2 legacy 路径 — PASS
- `test_probe_s52`：空库固定问 `城东店的宣传海报在哪里？` → `path=legacy`、`outcome=not_found`、
  `reason=None`、Span 含 `{intent_parse, retrieve, commit}`、validate `[]`（检索后 not_found 仍要求 retrieve）。
- `test_probe_s53`：同标识冲突 → `path=legacy_with_rag_candidates`、`outcome=conflict`、
  `reason=CONFLICTING_VALUES`、Span 含 `{intent_parse, retrieve, commit}`、validate `[]`。
- 交付测试另覆盖 `legacy_with_rag_candidates + answer`（`test_paths_e2e.py:251`）与纯 `legacy + answer`
  （`:276`）；`query_expansion` 只在触发时出现（`:390`，probe 未单独重复）。
- 代码：`conversations/service.py:1903`（set_path legacy）、`:1972`（升级 candidates 路径）、
  `:1979`（retrieve span）、`:2005`（query_expansion 仅触发）。

### §5.3 多 outcome 覆盖 — PASS
- 证据：`06`（probe_s53 冲突、probe_s511 早退）；`02`（RAG conflict `test_paths_e2e.py:299`、
  检索后 no_answer `:326`、legacy clarification `:347`、legacy service_error `:365`）。
- service_error：`outcome=service_error`、`reason/error_code=MODEL_UNAVAILABLE`、`status=error`、
  `model_answer` Span status=error、`{intent_parse, commit}` 满足；无“为凑集合伪造阶段”的迹象
  （早退用例断言 Span **严格等于** `{intent_parse, commit}`）。

### §5.4 行为不变 — PASS
- `06`（probe_s54）：trace off/on 两个独立应用，同一固定 `client_request_id` + 固定问题，
  状态码一致、响应键集合一致、归一化 body 一致；off 无 `X-Trace-ID`、on 有。
- 交付测试 `test_middleware.py:412-443` 同口径（归一化后再次比较，防空比较）。
- 全量回归：`05`（1266 passed；含全部 integration 用例）。

### §5.5 隐私 — PASS
- `06`（probe_s51）：`content_mode=hash`、无 key → `hash_algo=sha256`、`hmac_key_id=None`、
  `question_hash` 64 hex、`question_chars == len(question)`、问题原文不在 trace 任一字段/Span 属性里。
- `06`（probe_s55）：配置 `trace_hmac_key` → `hash_algo=hmac-sha256`、`hmac_key_id` 非空、
  key 字符串不出现在 trace/span 序列化结果中。
- `06`（probe_s511）：内部 `reason` 不进入响应体（`set(body) == set(AskResult.model_fields)`，
  `AskResult` 无 reason 字段）——同时满足 §5.11 的“reason 写入 trace，不是响应体”。
- 说明：RAG `citation_refs_json.locator` 的 `cells[].display` 原值属 T003c 已验收冻结边界
  （本包未改 `rag/**`），按 T003c 口径不在本包判 FAIL。

### §5.6 index_sync 仅真同步 — PASS
- `06`（probe_s56）：绕过发布钩子后首次问答真实同步 → `index_sync` Span 存在、
  `index_sync_performed=true`、validate `[]`；第二次命中缓存 → 无 `index_sync`、无该条件属性、validate `[]`。
- 代码：`qa/service.py:305-316`（sync 薄包装 + `_sync`），`ensure_ready` 命中缓存不进入 `sync`
  （`qa/service.py:288-303`）。

### §5.7 重放 — PASS（附 1 条 LOW 偏离，见 §3.3）
- `06`（probe_s57）：同一 `client_request_id` 第二次 → 新 trace `status=replayed`、Span 为空、
  同 `request_id`、不同 `trace_id`；重读第一条 trace 仍 `status=ok` 且 Span 名称序列不变（不覆盖历史）。
- 观察：重放 trace 的 `path` 仍是中间件默认 `rag`、`outcome_kind=None`（`06` 的 OBSERVED 行）——
  §5.7 只要求 `status=replayed` 且不覆盖历史，故不判 FAIL；但 T006a 门禁必须对 `status=replayed`
  跳过 path/outcome 完整性校验，否则会对重放 trace 抛“outcome 缺失”。已记入 §3.3/T006a 提示。
- 代码：`conversations/service.py:2183`（写 replayed）。

### §5.8 硬约束 — PASS
- `09` §1–2：21 个提交文件全部在 handoff §2/§8 允许集；禁改路径 0 命中；无新依赖（pyproject 未变）。
- API 请求/响应字段结构未变：`06`（off/on 响应键集合一致；probe_s511 body 键集合 == AskResult）。
- 埋点 no-op：所有探针在 trace 关闭时（`04`）与既有测试均通过；`current_trace()` 为 None 时无副作用。

### §5.9 契约修订（T003c 移交的 §5.4 FAIL 关闭）— PASS
- `07-contract-matrix.txt`：以 `776497f` 的 `contracts.py` 为 old、`b811f9f` 为 new，逐组合比较：
  27 个 path×outcome 组合中，**除 4 个 legacy 新增行（conflict/knowledge_changed × 2 条 legacy path）外 0 差异**；
  `validate_required_spans`（record 无 reason）逐组合 0 差异 → **默认不传 reason 与 T001 冻结表完全一致**。
- reason 例外：`rag+no_answer` + `{DOCUMENT_NOT_FOUND, UNKNOWN_STORE, RECORD_ONLY}` → `{parse, commit}`；
  其它 reason / 缺省 → `{parse, recall, fuse, commit}`；reason 区分大小写；只作用于 `rag+no_answer`。
- 真实链路：`06`（probe_s59）直接驱动真实 `QaEngine.answer`（空索引点名未收录资料）→
  `kind=no_answer`、`reason=DOCUMENT_NOT_FOUND`、Span 严格 `{parse, commit}`、`validate == []`；
  T003c 验收的 §5.4 FAIL（缺失 recall/fuse）**已关闭**。
- 检索后 no_answer 仍要求 recall/fuse：`test_paths_e2e.py:326` 有 `{"recall","fuse"} ⊆ names` 且 validate `[]`
  （目标集全绿）。
- 代码：`contracts.py:84-87,112-140,243,271`；文档：`docs/evaluation/trace_schema_v0_1.md` §6.1.1 与顶部修订说明。

### §5.10 rerank 失败补测 — PASS
- `test_rag_spans.py:425`（目标集全绿）：注入 `index.reranker.rerank` 抛 `RuntimeError` →
  答案仍 `answer`（既有 RRF 回退语义）、`rerank` Span `status=error` / `error_code=RuntimeError`、
  `rerank_enabled=true`、validate `[]`、trace `status=ok`。断言非空转。

### §5.11 legacy 契约扩展 — **FAIL（单子项）**
已 PASS 的部分：
- 两条复现问题 `滨江店的负责人是谁？` / `滨江店宣传海报的负责人是谁？`：真实 HTTP →
  `path=legacy`、`outcome=not_found`、`reason=UNRECORDED_FIELD`、Span **严格** `{intent_parse, commit}`、
  `validate == []`；reason 不在响应体（`06` 两条参数化用例；代码 `conversations/service.py:1950-1958`）。
- 检索后 not_found（reason 缺省）仍要求 retrieve：`06`（probe_s52）。
- legacy + conflict 不再抛 ValueError：`06`（probe_s53）+ `test_paths_e2e.py:474`。
- legacy + knowledge_changed（检索阶段注入）不再抛 ValueError：`test_paths_e2e.py:502`（目标集全绿）。
- `legacy+no_answer/ambiguous/error` 仍 fail-closed（`test_contracts.py:261`，目标集全绿）。
- reason 真实写入 trace、不写响应体：`06`（probe_s511/s53）。
- 文档同步：`docs/evaluation/trace_schema_v0_1.md` §6.1.2（含不可达 outcome 说明与探针证据指向）。

未 PASS 的子情形（本项判 FAIL 的唯一原因）：见 §3.1。

## 3. 发现的问题

### 3.1 [MEDIUM / 判 FAIL] commit 阶段 revision 变化导致“解析级早退 → knowledge_changed”时必需 Span 缺失
- **现象**：`ask()` 的 legacy 分支先执行解析级早退（clarification / not_found 早退，未执行 retrieve），
  再在 commit 阶段由 `_commit_result_impl` 的 revision 复核把它升级为 `knowledge_changed`
  （`conversations/service.py:1520-1527`）。`_record_legacy_outcome` 以最终 `AskResult.kind` 写
  `outcome=knowledge_changed, reason=KNOWLEDGE_CHANGED`（`:1751-1758`），而 `contracts.py:77` 的
  `legacy(+with_rag_candidates)+knowledge_changed` 固定要求 `{intent_parse, retrieve, commit}`。
  实际 Span 只有 `{intent_parse, commit}`，`validate_required_spans` 返回 `['retrieve']`。
- **复现（独立探针，非交付测试）**：`test_probe_s511_commit_time_knowledge_changed_after_early_exit`
  在 commit 前把 `KnowledgeState.revision` +1（模拟并发发布；与 `_commit_result_impl` 的升级条件等价），
  对 `滨江店的负责人是谁？` 提问。实测：
  ```
  OBSERVED commit-upgrade trace: path=legacy outcome=knowledge_changed
  reason=KNOWLEDGE_CHANGED status=ok spans=['commit','intent_parse'] missing=['retrieve']
  AssertionError: assert ['retrieve'] == []
  ```
  证据：`06-independent-probe.txt`（10 passed / 1 failed，失败即本项）。
- **期望**：handoff §5.11 要求“对实际可达 outcome **按实际执行、不伪造**给出必需 Span 行”。
  `knowledge_changed` 在 legacy 有**两种实际执行形态**：(a) 检索/检索后 revision 变化（有 retrieve）；
  (b) 解析级早退后在 commit 事务复核时升级（无 retrieve）。实现只覆盖 (a)，(b) 会被 gate 误判为不完整。
- **为什么不是既有产品缺陷**：产品行为（升级为 knowledge_changed）是既有语义、本包未改；
  缺陷在 T003d 新增的 Trace 契约/埋点未覆盖这种真实形态。
- **可达性**：任一并发发布落在“claim → commit”窗口即可触发；早退问句窗口很短但非零，且与问题复杂度无关。
- **建议修复（窄范围，只动契约/测试/文档，不动业务分支）**：
  1) 首选 reason-aware 拆分：commit 升级写不同稳定 reason（如 `KNOWLEDGE_CHANGED_AT_COMMIT`）→
     必需 `{intent_parse, commit}`；检索阶段写 `KNOWLEDGE_CHANGED_AFTER_RETRIEVAL` → 保留
     `{intent_parse, retrieve, commit}`；或
  2) 若不想拆 reason，则把 `legacy(+with_rag_candidates)+knowledge_changed` 的必需集降为
     `{intent_parse, commit}`（`required` 语义是“至少存在”，retrieve 存在时属超集，不影响其它 outcome）。
     需同步 §6.1.2、`test_contracts.py` 与新增 commit 升级回归测试（可用探针同款注入）。
  > 该子项不阻塞 §5.1–§5.10；修复仅涉及 `contracts.py` / 文档 / 测试，预计 1 个小返工。

### 3.2 [LOW / 证据完整性] `T003d/10-deliverables-sha256.txt` 漏列 `06-test-middleware.diff`
- `10` 列表 19 个文件（代码/测试/文档/报告 + 00–05、07–10），**06 未列入**；其余 19/19 与副本工作树一致。
- `09-final-commit-stat.txt` 是 amend 前 `bf8d7b7` 的 stat（报告 §3 已说明，按任务口径“记录即可”）。
- `00-baseline.txt`/`06-test-middleware.diff` 为 UTF-8 **带 BOM**；`01-tdd-red.txt` 为 UTF-16-LE（任务要求记录即可）。
- 均不影响交付正确性，建议下次采集 10 时补 06。

### 3.3 [LOW / 规则一致性] 重放用 `trace.annotate(replayed=True)` 写“启动字段”
- handoff §4 写“`annotate` 不写启动字段（mode/scope/replayed/path/outcome_kind）”，但实现
  `conversations/service.py:2183` 用 `annotate(replayed=True)` 实现 §5.7。
- 行为实测正确（`status=replayed`、Span 空、不覆盖历史）；tracer 无 `set_replayed` 公开 setter，
  这是“§4 规则 vs §5.7 需求”的结构性缝隙。建议 PM 明确允许该写法，或后续在 tracer 增加受控 setter。
  不影响 §5.7 判定。
- 同一处观察：重放 trace 保留中间件默认 `path=rag`、`outcome_kind=None`（`06` OBSERVED）。
  §5.7 未要求重放设置 path/outcome，故不判 FAIL；但 **T006a 门禁需显式跳过 `status=replayed` 的
  path/outcome 完整性校验**，否则 `validate_required_spans` 会因 outcome 为空抛 ValueError。

### 3.4 [INFO / 未覆盖] commit 阶段异常仍留 `outcome=None`
- 若 `_commit_result` 抛 `RequestCancelled`/`AccessDenied`/`ServiceOverloaded`（已进入 `_answer` 之后），
  trace 会因异常被记为 `status=error` 但 `outcome_kind=None`；handoff §7 “已进入 `_answer` 的失败设
  outcome=error/service_error”在字面上未覆盖该路径。§5.3 未把该异常场景列为必需，故 INFO。

### 3.5 [INFO] 环境导致的首次全量失败（已闭环）
- 16 failed + 15 skipped 全部因 `docs/evidence/**` 缺失；恢复 37.8 MB 资产后同选集 37 passed，
  最终全量见 `05`。与 T003d 代码无关。

## 4. 授权修改最小性 / 测试非空转

### 4.1 授权修改
- `test_middleware.py` +12/−9：删除的 9 行 = 2 行过时 docstring + 4 条 T003b 失效边界断言
  （`request_id is None`、`outcome_kind is None`、`status=="incomplete"`、`question_hash is None`）
  + 2 行注释 + 1 行 docstring。header、一次 POST 一条 trace、mode/scope/content_mode、无内部泄漏、
  零副作用等断言保留；新断言更强（绑定 `body["request_id"]`、path/outcome/status、hash 长度）。
- `conftest.py` +32/0（只追加 fixture）；`test_contracts.py` +122/0；`test_rag_spans.py` +31/−1
  （−1 仅 docstring 改写）；`test_paths_e2e.py` 新增 611 行。
- 结论：PASS，无削弱断言的证据。

### 4.2 变异探针（测试非空转）
在独立副本 `%TEMP%\…\mut`（与交付副本隔离）逐一注入 5 个变异，跑对应交付测试：

| 变异 | 内容 | 结果 |
| --- | --- | --- |
| m1 | `validate_required_spans` 不读 `record.reason` | 2 failed（`test_contracts.py::test_validate_required_spans_reads_reason_from_record`、`…_legacy_reason_from_record`） |
| m2 | 去掉 `UNRECORDED_FIELD` 写入 | 2 failed（`test_paths_e2e.py::test_legacy_parse_early_not_found_is_reason_aware`×2） |
| m3 | 删除 legacy conflict/knowledge_changed 补充行 | 2 failed（`test_legacy_conflict_…`、`test_legacy_knowledge_changed_…`，ValueError） |
| m4 | `sync` 不再创建 index_sync Span/属性 | 1 failed（`test_index_sync_span_only_when_sync_actually_executes`） |
| m5 | `_record_legacy_outcome` 不写 reason | 2 failed（早退用例×2） |

证据：`08-mutation-probes.txt`（原文）；探针脚本 `11-mutate.py`。

## 5. 全量回归

| 运行 | 环境 | 结果 |
| --- | --- | --- |
| 首次 | 副本缺 `docs/evidence/**` | 16 failed / 1235 passed / 15 skipped（全部环境资产缺失，`03`） |
| 控制 | 恢复 37.8 MB 资产后选中的 37 项 | 37 passed（`04`） |
| 最终 | 恢复资产后全量 `backend/tests` | **1266 passed / 0 failed / 0 error**（594.69s；`05-full-suite-restored.txt`） |

- 已知时序 flake `test_g08_short_budget_cancels_inflight_model_call`：两次全量均未复现（无需隔离复跑）。
- 最终结果 **1266 passed / 0 failed / 0 error**，与目标“T003c 1216 + T003d 50 = 1266”完全一致；
  首次全量中 15 个被 skip 的 tokenizer 用例在资产恢复后也全部通过（`04`），不存在“用 skip 凑通过数”。
- 未出现 MemoryError；两次全量 644.57s / 594.69s（机器同时有并发开发负载，较报告 515s 慢，属环境噪声）。

## 6. 未覆盖项（NOT-RUN / 边界外）

1. **T006a gate 实现**未验收（尚未实现；本 review 只验证其将依赖的契约函数与文档）。
2. 真实 ingestion/embedding/OCR/rerank 供应商链路未跑（零真实调用约束；T003c 已单独验收）。
3. `citation_refs_json.locator` 的 `cells[].display` 隐私口径未重新裁定（T003c 冻结边界，本包未改 `rag/**`）。
4. 并发 T004a 在共享工作树的未提交改动未纳入评审（按要求隔离）。
5. commit 阶段异常（§3.4）未做端到端注入验证，仅静态判断。

## 7. 建议返工范围（给 PM）

1. **必修（§3.1）**：为 legacy `knowledge_changed` 的“commit 阶段升级、未执行 retrieve”形态补 reason-aware 行
   （或把该行必需集降为 `{intent_parse, commit}`），同步 `docs/evaluation/trace_schema_v0_1.md` §6.1.2，
   并新增“早退后在 commit 升级”的回归测试（不改业务分支/响应结构）。修复后仅需重跑
   `test_contracts.py` / `test_paths_e2e.py` / `test_rag_spans.py` + 全量。
2. 可选（§3.2）：若重新采证，把 `06-test-middleware.diff` 补进 `10` 的 sha256 列表。
3. 可选（§3.3）：PM 明确 `annotate(replayed=True)` 例外，或后续给 tracer 增加受控 setter。

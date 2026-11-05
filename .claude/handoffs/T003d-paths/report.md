# T003d 开发报告（P0 第 6 包：QA/legacy 路径 Span 与 outcome 绑定 + 契约修订）

> 角色：开发助手（全新上下文）。对象：`.claude/handoffs/T003d-paths/handoff.md`。
> 分支 `p0/obs-eval`；开工基线 `776497f`（`p0/T003c rag spans`，parent `d41d19f`）。
> 环境：Windows / PowerShell 5.1 / Python 3.12.7 / pytest 9.1.1；`.\.venv\Scripts\python.exe -B`；
> 全程 `MKTKB_PROJECT_TOTAL_LIMIT_CNY=20.0`；零真实模型/OCR/embedding/rerank 调用，不读 `.env`，不打印凭据。
> 证据目录：`docs/reports/OBS-EVAL/P0/evidence/T003d/`（00–10）；草稿与探针：`backend/.pytest-tmp/t003d-probes/`（不入库）。
> 续作说明：本报告主体由上一轮开发助手完成（§5.1–§5.10 与 24 个测试，全量 1240 passed）后会话异常退出；
> 本轮全新上下文接管**未提交工作树**，只补 handoff §5.11（legacy 契约缺口，PM 2026-11-05 预授权）、
> 证据 08–10 与提交，未回退或重写任何既有改动。

## 1. 完成内容

| 文件 | 改动 | 要点 |
| --- | --- | --- |
| `backend/src/mktkb/conversations/service.py` | +159/−53 | `ask` 设 `request_id`/`question`（`service.py:2178-2179`），重放写 `replayed=True`（`:2183`），legacy 路径的 `commit` Span 包住产品提交（`:2188`），legacy 最终 outcome/reason/error_code（`:1741`、`:2190`）；`_answer` 按 `_rag_owns_turn` 设 `path`（RAG `:1879`，legacy `:1903`，拿到非空 rag 候选升级 `legacy_with_rag_candidates` `:1972`）；legacy 层 Span：`intent_parse`（`:1905`）、`retrieve`（`:1979`，每次实际取证一个）、`query_expansion`（`:2005`，仅触发）、`model_answer`（`:2095`）、`answer_validate`（`:2099`）；**§5.11**：内部 `_Result.reason`（`:1462`，不进响应体），解析级 not_found 的四个稳定 reason（`:1925`/`:1935`/`:1950`/`:1958`）、conflict `CONFLICTING_VALUES`（`:2071`），由 `_record_legacy_outcome` 写 Trace（`:1741-1760`）。所有埋点以 `current_trace()` 为 None 时 no-op。 |
| `backend/src/mktkb/qa/service.py` | +25/−2 | `QaEngine.answer` 用 `current_trace()` 把 `RagAnswer.kind` 映射为 `outcome`、`RagAnswer.reason` 一并写入（`service.py:441`），不新建 Trace、不改返回结构；`QaEngine.sync` 拆成薄包装 + `_sync`（`:305-316`）：只有真正执行同步才创建 `index_sync` Span 并置 `index_sync_performed=true`。 |
| `backend/src/mktkb/observability/contracts.py` | +49/−3 | **契约修订**：`required_spans(path, outcome, *, reason=None)` 向后兼容可选参数（`:112`）。§5.9：`rag+no_answer` 且 `reason ∈ {DOCUMENT_NOT_FOUND, UNKNOWN_STORE, RECORD_ONLY}` → `{parse, commit}`；§5.11：legacy `not_found` 且 `reason ∈ {UNKNOWN_IDENTIFIER, IDENTIFIER_NOT_RETRIEVABLE, NO_INTENT, UNRECORDED_FIELD}` → `{intent_parse, commit}`（`:93-96,136-140`）；新增 legacy `conflict` / `knowledge_changed` 行 `{intent_parse, retrieve, commit}`（`:76-77`）；`legacy+no_answer/ambiguous/error` 仍 fail-closed。`validate_required_spans` 按 `record.reason` 应用（`:243`）。 |
| `docs/evaluation/trace_schema_v0_1.md` | +59/−5 | 顶部修订说明（`:7-10`）；§6.1 表扩为 10 行并写明 legacy 不可达 outcome；§6.1.1 `rag+no_answer` 检索前拒答例外；**新增 §6.1.2**「legacy 解析级早退与补充 outcome 行」（`:170` 起，含 reason/row 定义与证据指向）。 |
| `backend/tests/observability/test_paths_e2e.py`（新增，611 行 / 16 测试） | +611 | T003d HTTP 级/引擎级 E2E：RAG answer、legacy_with_rag_candidates answer、纯 legacy document answer、RAG conflict、检索后 no_answer、legacy clarification、legacy service_error、query_expansion 仅触发、RAG 检索前拒答、**§5.11 两条复现问题（`:448`）、legacy conflict（`:474`）、legacy knowledge_changed（`:502`）**、index_sync 正/负例、重放、HMAC。 |
| `backend/tests/observability/test_rag_spans.py` | +31/−1 | 「rerank 抛异常 → `rerank` Span status=error、既有 RRF 回退语义不变」（`:425`）；早退用例补 `record.reason` 与 `validate_required_spans == []`（`:467`）。 |
| `backend/tests/observability/test_contracts.py` | +122 | §5.9 reason-aware（RAG 三 reason/其它 reason/两参不变/validate 读 `record.reason`）；**§5.11**：legacy 四 reason × 两 path → `{intent_parse, commit}`（`:224-245`）、其它 reason 仍要求 retrieve、conflict/knowledge_changed 补充行、不可达 outcome fail-closed、reason 不跨 path、`validate_required_spans` 读 legacy reason（`:274`）。 |
| `backend/tests/observability/conftest.py` | +32/−0 | **只追加** `T003D_ROWS`/`T003D_HEADERS` 与 `trace_chat_app` fixture；既有 fixture 未改。 |
| `backend/tests/observability/test_middleware.py` | +12/−9 | PM 授权的最小既有断言更新（见 §4.1，精确 diff 见证据 06）：只把 T003b 失效的 4 条边界断言改为接线后事实，并更正「spans 为空」的过时注释；header/一次一条 trace/mode/scope/content_mode/无内部泄漏/零副作用等断言强度未变。 |
| 证据 `T003d/00–10` + 本报告 | — | 00 基线、01 TDD RED（上一轮）、02 本包 E2E、03 observability+integration、04 全量、05 legacy 边界（已追加收尾结论）、06 授权 diff、07 静态边界、**08 §5.11 契约矩阵（修订前/后）**、09 提交 stat、10 交付物 sha256。 |

### 1.1 契约修订汇总（T003c §5.9 + §5.11）

两个缺口同构：内核/产品在**执行检索之前**就拒答，而 T001 冻结表把对应 outcome 一律定义为
“检索后”。本包没有补 no-op Span、没有改业务分支，而是把稳定的 `reason` 纳入必需集判定：

| 规则 | 条件 | 必需 Span | 证据 |
| --- | --- | --- | --- |
| §5.9 RAG 检索前拒答 | `rag + no_answer`，reason ∈ `DOCUMENT_NOT_FOUND`/`UNKNOWN_STORE`/`RECORD_ONLY` | `parse`、`commit` | `test_rag_spans.py:467`、`test_paths_e2e.py:414` |
| §5.9 其余 RAG 拒答 | `rag + no_answer`，reason 缺省/其它 | `parse`、`recall`、`fuse`、`commit` | `test_paths_e2e.py:326`、`test_contracts.py:201-205` |
| §5.11 legacy 解析级早退 | `legacy(+with_rag_candidates) + not_found`，reason ∈ `UNKNOWN_IDENTIFIER`/`IDENTIFIER_NOT_RETRIEVABLE`/`NO_INTENT`/`UNRECORDED_FIELD` | `intent_parse`、`commit` | 证据 08、`test_paths_e2e.py:448` |
| §5.11 legacy 检索后拒答 | 同上，reason 缺省/其它 | `intent_parse`、`retrieve`、`commit` | 证据 08、`test_paths_e2e.py:390` |
| §5.11 legacy 补充行 | `legacy(+with_rag_candidates) + conflict` / `knowledge_changed` | `intent_parse`、`retrieve`、`commit` | 证据 08、`test_paths_e2e.py:474,502` |
| fail-closed | legacy + `no_answer`/`ambiguous`/`error` | 未定义，抛 `ValueError` | `test_contracts.py:261`、证据 08 §D |

- `legacy_with_rag_candidates` 与 `legacy` 共用全部 legacy 规则；`reason` 区分大小写，
  未知 reason 一律回落原表（fail safe，不放宽完整性）。
- 两条复现问题 `滨江店的负责人是谁？` / `滨江店宣传海报的负责人是谁？` 实测
  `requested_fields=[]`、`missing_fields=['负责人']`，命中 `UNRECORDED_FIELD` 早退：
  Span 严格 `{intent_parse, commit}`，validate 从 `['retrieve']` 变为 `[]`。
- `conflict` / `knowledge_changed` 都发生在 retrieve 之后（后者在检索阶段抛
  `KnowledgeRevisionChanged` 时也会留下 `retrieve` Span），实测 Span 是补充行的超集。

## 2. §5 逐条自证

1. **RAG 产品路径 E2E** — 证据 `02-paths-e2e.txt`（16 passed）；`test_paths_e2e.py:216`：
   固定枚举问答 → 响应头 `X-Trace-ID`，`trace.request_id == body["request_id"]`、
   `http_request_id == X-Request-ID`、`path=rag`、`outcome=answer`、`status=ok`，
   `required_spans(RAG, ANSWER) ⊆ names` 且 `validate_required_spans == []`；
   无 `intent_parse/retrieve/model_answer/answer_validate`。
2. **legacy 路径** — `test_paths_e2e.py:251`（`legacy_with_rag_candidates`，五段 legacy Span
   齐全、`query_expansion` 不出现）、`:276`（纯 `legacy`，无 RAG `recall/fuse`）；
   `test_middleware.py` 空库用例得到 `path=legacy`、`outcome=not_found`、`status=ok`。
   代码：`conversations/service.py:1903,1972`。
3. **多 outcome 覆盖** — `test_paths_e2e.py:299`（RAG conflict）、`:326`（检索后 no_answer，
   `recall/fuse` 必须存在）、`:347`（legacy clarification 严格 `{intent_parse, commit}`）、
   `:365`（legacy service_error，`error_code`/`reason=MODEL_UNAVAILABLE`、`model_answer` error）、
   `:390`（`query_expansion` 仅触发时出现）；`test_rag_spans.py:454-467`（RAG 早退）。
   **§5.11 补充**：`:448`（两条复现问题）、`:474`（legacy conflict）、`:502`
   （legacy knowledge_changed）。**没有为凑集合伪造任何阶段**。
4. **行为不变** — `test_middleware.py:412-443`（trace 关/开同一固定请求响应 body 归一化后一致）；
   `03-observability-integration.txt` = **593 passed**；`04-full-suite.txt` = **1266 passed**
   （T003c 基线 1216 + 本包全部新增 50 个测试；上一轮 24 + 本轮 §5.11 26）。
5. **隐私** — `test_paths_e2e.py:239-245`：`content_mode=hash` 下问题只有 64 hex 哈希 + 长度，
   `hash_algo=sha256`（无 key），问题原文不出现在记录与全部 Span；`:588`：配置
   `trace_hmac_key` 时 `hash_algo=hmac-sha256`、`hmac_key_id` 非空、key 不出现在记录/Span。
   **报告注明：无 key 时 `sha256`**（证据 02/04）。
6. **index_sync** — `test_paths_e2e.py:533`：绕过发布钩子后首次问答真实同步 → `index_sync`
   Span + `index_sync_performed=true`、validate 通过；第二次命中缓存 → 无 `index_sync`、
   不写该条件属性。代码：`qa/service.py:305-316`。
7. **重放/恢复** — `test_paths_e2e.py:561`：同一 `client_request_id` 第二次 → 新 trace
   `status=replayed`、Span 为空、同 `request_id`、两次 `trace_id` 不同；重读第一次 trace
   仍 `status=ok` 且 Span 集合不变。代码：`conversations/service.py:2183`。
8. **硬约束** — 证据 `07-static-hygiene.txt`：只改 handoff §2 文件；未改 `rag/**`、`main.py`、
   `config.py`、`store.py`、`tracer.py`、`versioning.py`、`pyproject`；无新增依赖/文件类型；
   API 请求/响应字段结构未变（§5.4 测试 + **`_Result.reason` 只在内部/Trace，不进响应体**）。
9. **契约修订（§5.9）** — 证据 `02` 与 `01-tdd-red.txt`；`contracts.py:78-83,112-140,243`；
   文档 `trace_schema_v0_1.md:7-10,152-168`；测试 `test_contracts.py:175-221`（早退三 reason →
   `{parse,commit}`；其它 reason → 原表；两参不变；validate 读 `record.reason`）、
   `test_rag_spans.py:467`、`test_paths_e2e.py:414`。
10. **rerank 失败补测** — `test_rag_spans.py:425`：注入 `index.reranker.rerank` 抛
    `RuntimeError` → 答案仍为 answer（既有 RRF 回退），`rerank` Span `status=error` /
    `error_code=RuntimeError`，`rerank_enabled=true` 且 Span 在，validate 通过。
11. **契约修订扩展（§5.11）** — 证据 `08-legacy-contract-matrix.txt`（修订前/后两次探针原文）；
    `contracts.py:76-77,93-96,136-140`；`conversations/service.py:1462,1741,1925,1935,1950,1958,2071`；
    文档 §6.1.2（`trace_schema_v0_1.md:170` 起）；测试 `test_contracts.py:224-280`、
    `test_paths_e2e.py:448,474,502`。探针结论：
    - 两条复现问题：`not_found` / `UNRECORDED_FIELD` / Span `{intent_parse, commit}` / validate `[]`
      （修订前 reason=None、validate `['retrieve']`）；
    - legacy conflict：`legacy_with_rag_candidates` / `CONFLICTING_VALUES`，修订前 `ValueError`，
      修订后 validate `[]`；
    - legacy knowledge_changed：检索阶段注入 revision 变化，含 `retrieve` Span，修订前
      `ValueError`，修订后 `[]`；
    - `no_answer`/`ambiguous`/`error`：legacy `_answer` 无对应 `kind` 返回点，保持 fail-closed；
    - 业务代码分支/响应字段不变，只在 Trace 写 `reason`。

## 3. 实际运行结果

```powershell
$env:MKTKB_PROJECT_TOTAL_LIMIT_CNY = "20.0"
git rev-parse --short HEAD   # 776497f（开工基线）
```

- **§5.11 的 RED 证据**：证据 `08` §1「契约修订前」——两条复现问题 `validate=['retrieve']`、
  conflict/knowledge_changed `ValueError`；修订后同一探针全部转绿（§2）。
- 本包 E2E（证据 `02-paths-e2e.txt`）：`16 passed`。
- observability + integration（证据 `03-observability-integration.txt`）：`593 passed`。
- 全量 `backend/tests`（证据 `04-full-suite.txt`）：**`1266 passed, 0 failed, 0 error`**（515.51s）；
  T003c 收口基线为 1216，增量 = 本包全部新增 **50** 个测试
  （上一轮 24 = 11 contracts + 1 rag_spans + 12 paths_e2e；本轮 +26 = 22 contracts + 4 paths_e2e）。
- 提交：单 commit `p0/T003d qa legacy spans`；最终 `git show --stat --oneline HEAD` 原文见
  证据 `09-final-commit-stat.txt`。commit 内容无法记录自身最终短 sha，最终 HEAD 见回复与
  `git log -1 --format=%h`。证据 09/10 在首次提交后采集，并以 `git commit --amend --no-edit`
  并入同一提交；因此 09 的 stat 比最终 HEAD 少 09/10 两个文件本身（代码/测试/文档/报告内容不变）。
- **flake**：本轮全量一次通过，未复现已知 `test_g08_short_budget_cancels_inflight_model_call`。
  上一轮报告过的本包测试随机 flake（UUID 文件名撞 `quantity=40`）已修为固定文件名，本轮未复现。
- T003c 并发残留（`T003c/{02,03,04,07}`）经检查均不存在（证据 `00-baseline.txt` 末尾）。

## 4. 偏离与未做

1. **PM 授权的最小既有测试修改（精确 diff：证据 `06-test-middleware.diff`）**：`test_middleware.py`
   共 +12/−9，仅替换 T003b 失效的 4 条边界断言（`request_id` 绑定响应体产品 ID、`path=legacy`、
   `outcome=not_found`、`status=ok`、问题哈希/长度），并更正过时注释；header、trace 行数、
   mode/scope/content_mode、无原文/无内部泄漏、默认关闭零副作用等断言强度未变。
2. **`QaEngine.sync` 包装化**：原方法体原样移入 `_sync`，`sync` 成为「置条件属性 + `index_sync`
   Span + 调用 `_sync`」的薄包装（`qa/service.py:305-316`）；业务算法/异常语义未变。
3. **读取 `TraceContext._path` 判定 legacy**：`_trace_is_legacy` 用只读 `getattr(trace, "_path", None)`
   判断 commit Span 归属（`tracer.py` 属禁止修改文件，未新增公开 getter）。
4. **§5.11 内部 reason 字段**：`_Result` 末尾追加 `reason: str | None`（`service.py:1462`），
   只在内部与 Trace 使用，不进 `AskResult` 响应体；解析级四个返回点写入稳定 reason，
   conflict 写 `CONFLICTING_VALUES`。`_record_legacy_outcome` 改为同时接收内部结果与最终
   `AskResult`，以处理提交事务把结果升级为 `knowledge_changed` 的情形。业务分支/文案/异常未改。
5. **RAG 检索前拒答在 HTTP 产品路径当前不可达**：`_rag_owns_turn` 对标识/文档型问题分别为
   legacy/非 record；该 reason-aware 链路用 `test_paths_e2e.py:414` 直接驱动真实
   `QaEngine.answer` + `start_trace` 验证（T004 Local 评测/T006 门禁将走同一入口）。
6. **INDEX_NOT_READY 于 `qa.prepare` 阶段失败**：尚未执行任何业务阶段，按 handoff §7
   「未进入业务层的失败允许保持 incomplete」保留 `status=incomplete`、不伪造 Span。
7. **knowledge_changed 补充行测试用测试级注入**：`monkeypatch` 替换模块内 `_retrieve` 抛
   `KnowledgeRevisionChanged`（`test_paths_e2e.py:502`），只影响该测试进程，生产代码零改动。
8. **未做（handoff 未要求/不允许）**：未改 `rag/**`、`main.py`、`config.py`、观测内核、
   其它既有测试、pyproject；未 push；未 commit PM 的未跟踪文件（`_index.md` 等工作区原样，未 add）。

## 5. 风险与遗留

1. **已关闭（原 HIGH）**：legacy 解析级早退 not_found 与 `legacy+conflict`/`knowledge_changed`
   表外组合已按 handoff §5.11 补齐，探针与测试双证（证据 08、`test_contracts.py:224-280`、
   `test_paths_e2e.py:448-531`）。T006a 必须按 `trace_schema_v0_1.md` §6.1.2 的新表实现。
2. **LOW 契约维护风险**：legacy 解析级早退 reason 是内部稳定枚举；若未来 intent 解析新增
   早退分支而未同步 reason，未知 reason 会回落到“要求 retrieve”而误判缺失（fail-safe 方向，
   不会放过不完整 trace）。新增分支时需同步 `contracts.py` 与 §6.1.2。
3. **MEDIUM（T003c 既有边界，本包不修改 `rag/**`）**：真实 ingestion 的
   `citation_refs_json.locator` 会带 `cells[].display` 原值；T003c 验收按「doc_code + locator
   允许」判 PASS。若 T006 对 locator 有更严隐私口径，需在 `rag/**` 另立任务收紧（本包只保证
   **不新写**问题/答案原文，Trace 的问题侧只有哈希/长度）。
4. **LOW 条件 Span 语义**：`index_sync_performed` 在 `sync` 被调用即置真（含同步失败/锁超时），
   Span 同时存在，validate 不会误判；`query_expansion` 仅在扩展模型调用真实触发时出现。
5. **LOW 多条同名 Span**：legacy `retrieve` 每次实际取证一个 Span（截断重试/扩展后会多于一个），
   `validate_required_spans` 按集合判定，不要求唯一；gate 若统计次数需按「至少一个」语义。
6. **已知 flake**：`test_g08_short_budget_cancels_inflight_model_call` 时序敏感（非本阶段引入），
   本轮全量未复现；若 CI 复现，按既有口径隔离复跑。

## 交接摘要（≤10 行）

1. 交付：`conversations/service.py`（request_id/question/path/outcome + legacy 六段 Span + 重放/commit
   + §5.11 reason）、`qa/service.py`（answer outcome/reason、index_sync 仅真同步）、`contracts.py`
   （§5.9 + §5.11 reason-aware、legacy conflict/knowledge_changed 补行）、`trace_schema_v0_1.md`
   §6.1.1/§6.1.2、`test_paths_e2e.py`（16）+ 契约/rerank/早退测试，报告与证据 00–10。
2. §5.1–§5.8、§5.10 由上一轮完成并经全量验证；本轮补 §5.11：两条复现问题
   `not_found/UNRECORDED_FIELD/{intent_parse,commit}/validate=[]`、legacy conflict 与
   knowledge_changed 不再 ValueError、不可达 outcome 保持 fail-closed（证据 08）。
3. §5.9 契约修订保持：`rag+no_answer` + 三种检索前 reason → `{parse,commit}`，其余原表；
   `validate_required_spans` 读 `record.reason`；两参旧调用不变。
4. §5.10 rerank 失败：Span status=error、RRF 回退语义不变、validate 通过。
5. 实际运行：02 = 16 passed、03 = 593 passed、04 全量 = **1266 passed**（1216 + 50 新增）；
   单 commit `p0/T003d qa legacy spans`，最终 sha/stat 见证据 09/10 与回复。
6. 偏离：`QaEngine.sync` 薄包装化；`_trace_is_legacy` 只读私有 `_path`；`_Result.reason` 仅内部；
   INDEX_NOT_READY@prepare 保持 incomplete；knowledge_changed 测试用 monkeypatch 注入。
7. 风险：legacy 新 reason 需随解析分支同步维护（fail-safe）；locator 隐私属 T003c 冻结边界；
   已知 g08 时序 flake 本轮未复现。
8. 边界：未碰 `rag/**`/`main.py`/`config.py`/观测内核/其它既有测试/pyproject；无新依赖；
   未 push；PM 未跟踪文件未动。
9. 证据：`docs/reports/OBS-EVAL/P0/evidence/T003d/`（00–10）；探针脚本在
   `backend/.pytest-tmp/t003d-probes/`（gitignored，不入库）。

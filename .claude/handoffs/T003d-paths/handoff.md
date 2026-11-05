# T003d · QA/legacy 路径 Span 与 outcome 绑定（P0 第 6 包）

> PM 任务单。基线：`p0/obs-eval` @ T003c 收口 commit（开工前 `git log --oneline -2` 确认，应为 `p0/T003c rag spans`）。T001–T003c 均已通过独立验收。
> 本包只做"接线与 outcome 绑定"，**不改业务算法、不改响应结构**。完成后由全新上下文的独立验收助手按本文件逐条证伪。

## 1. 目标（一句话）

让 QA 产品路径与 legacy 路径的 trace 具备正确的 `request_id` / `path` / `outcome` / `question` 与 legacy 侧 Span（`intent_parse`、`retrieve`、`query_expansion`、`model_answer`、`answer_validate`、`commit`），使 gate 的 `trace_integrity`（按 path+outcome 的必需 Span）能通过。

## 2. 交付物（只准写这些路径）

- 修改 `backend/src/mktkb/qa/service.py`、`backend/src/mktkb/conversations/service.py`
- **契约修订（T003c 验收移交，PM 已裁决）**：修改 `backend/src/mktkb/observability/contracts.py`（`required_spans` 增加**向后兼容**的可选 `reason` 参数、`validate_required_spans` 读取 `record.reason`；早退拒答 reason 映射见 §5.9）；修改 `docs/evaluation/trace_schema_v0_1.md`（补 required spans 的 reason 例外注记）
- 修改 `backend/tests/observability/test_rag_spans.py`（补早退路径 `validate_required_spans` 断言、rerank 失败断言）；允许对 `backend/tests/observability/test_contracts.py` **追加** reason-aware 测试
- 新增 `backend/tests/observability/test_paths_e2e.py`
- 允许对 `backend/tests/observability/conftest.py` **追加** fixture（不改既有 fixture）
- 证据（入库）：`docs/reports/OBS-EVAL/P0/evidence/T003d/`
- 报告：`.claude/handoffs/T003d-paths/report.md`（五段）

## 3. 输入（只看这些）

1. P0 设计 §5（架构图里 path 取值）、§6.1（trace_id/request_id/attempt/replayed）、§6.3（Trace 字段）、§6.4（Span 表与条件 Span）、§6.5（内容/HMAC）、§6.6（写入语义）。
2. P0 计划 Task 3 Step 4：`conversations/service.py::ask` 设 question；`_answer` 按 `_rag_owns_turn` 设 `TracePath.RAG` 或 legacy，legacy 分支加 Span；`qa/service.py::QaEngine.answer` 不新建 Trace（用 `current_trace()`）、设 outcome。
3. 已验收代码（只读）：`observability/tracer.py`（`set_request_id/set_question/set_path/set_outcome/annotate/span`；`annotate` 不得写启动字段；条件属性在 `filter_decisions_json`）、`observability/contracts.py`（`required_spans`/`validate_required_spans`/枚举）、`main.py`（中间件已启动 trace 并在响应头返回 `X-Trace-ID`；**失败请求也会写 incomplete trace**）。
4. 关键代码位置（以开工时实际为准）：`conversations/service.py:1796 _answer`、`:1678 _rag_owns_turn`、`:2066 ask`、`:586 _retrieve`、`:551 _replay`；`qa/service.py:415 QaEngine.answer`、`:280 ensure_ready`、`:303 sync`、`:400 prepare`。
5. 本包开工前必读：`.claude/handoffs/T003c-rag-spans/review.md`（T003c 验收 FAIL 项与证据）、`docs/reports/OBS-EVAL/P0/evidence/verify/T003c/04-independent-probe.txt`（早退路径实测 Span 集合）。

## 4. 允许 / 禁止

**PM 裁决（2026-11-05）**：`backend/tests/observability/test_middleware.py` 中 T003b 的边界断言（`request_id is None`、`status == "incomplete"`、`path` 默认等）在 T003d 接线后会失效。**授权最小修改**：只把失效断言改为与接线后事实一致、且不削弱安全/行为断言（header、trace 行数、mode/scope/content_mode、无原文、零副作用等保持原强度）；报告给出精确 diff。同时沿用 T003c 对该文件 `spans == []` 两处的修改口径。

**允许**：§2 交付物；上述授权的最小既有测试断言修改；**清理 T003c 并发残留（仅限）** `docs/reports/OBS-EVAL/P0/evidence/T003c/{02-package.txt,03-observability-rag.txt,04-full.txt,07-test-middleware.diff}` 这 4 个未被提交的临时文件（在 report 说明，不删除已提交的 00–08）；`git switch p0/obs-eval`；本包一个 commit。

**禁止**：
- 不改 `rag/**`（T003c 已完成）、`main.py`、`config.py`、`observability/{tracer,store,contracts,versioning}.py`、既有测试。
- 不改业务算法/路由/答案逻辑、不改响应 Body 字段结构、不改异常类型与时机；埋点全部以 `current_trace()` 为 None 时 no-op。
- `annotate` 不写启动字段（mode/scope/replayed/path/outcome_kind）；只写数据字段与条件属性。
- 零真实模型/OCR/embedding/rerank 调用；不读 `.env`；不打印凭据；不记录问题/答案原文。
- 不碰 `docs/evidence/**`、`var/**`、`fixtures/**`、账本/GO、归档区；不 push；不 commit PM 的未跟踪文件。

## 5. 验收标准（逐条可判定）

1. **RAG 产品路径 E2E**：trace 开启 + 现有 `client` 发固定问答 POST → 响应头 `X-Trace-ID`；同一 id 在 TraceRepository 查到 trace：`request_id` 非空且对应本次产品请求（`ConversationRequest.id` 或等价字段）、`http_request_id` 等于中间件 `X-Request-ID`、`path=rag`、`outcome_kind=answer`（或该题实际 kind）、`status` 正常；Span 集合满足 `required_spans(RAG, ANSWER)` = {parse, recall, fuse, answer, commit} 且 `validate_required_spans` 返回空。
2. **legacy 路径**：构造 `_rag_owns_turn` 为假的请求 → `path=legacy`（若检索有候选按现有语义 `legacy_with_rag_candidates`），outcome 与 Span 满足对应表（`legacy+answer` 需要 intent_parse/retrieve/model_answer/answer_validate/commit；`not_found` 不需要 model_answer/query_expansion）；`query_expansion` **仅在实际触发时**出现。
3. **多 outcome 覆盖**：clarification / no_answer / conflict（及可造的 error/service_error）各自 `outcome_kind` 正确、必需 Span 按设计 §6.4 表、`reason`/`error_code` 合理；不得为凑齐 Span 集合伪造未执行阶段。
4. **行为不变**：trace 开启与关闭两种设置下同一固定请求响应 body 归一化后一致；既有 `backend/tests/integration/` 全绿；全量相对 T003c 收口基线无新增失败。
5. **隐私**：`content_mode=hash` 时 trace 只存问题哈希+长度、不存原文；配置 `trace_hmac_key` 时 `hash_algo=hmac-sha256` 且有 `hmac_key_id`、记录里无密钥；无 key 时 `sha256`（报告注明）。
6. **index_sync**：仅当实际执行索引同步（`ensure_ready`/`sync` 真正做同步）时出现 `index_sync` Span 并置 `index_sync_performed=true`；未执行时不出现、不伪造。
7. **重放/恢复**：若走 `_replay` 分支，trace `status=replayed`、不覆盖历史（同一 request 多条尝试可见）；不破坏既有幂等语义。
8. **硬约束**：无新增依赖；API 请求/响应字段结构未变；不碰观测内核既有行为与其它既有测试（除 §4 授权的三处）；不碰 `rag/**`、`main.py`、`config.py`、`store.py`、`tracer.py`、`versioning.py`。
9. **契约修订（T003c 验收 FAIL 项，PM 裁决）**：`required_spans(path, outcome, *, reason=None)` 向后兼容；当 `path=RAG, outcome=NO_ANSWER` 且 `reason ∈ {DOCUMENT_NOT_FOUND, UNKNOWN_STORE, RECORD_ONLY}` 时必需集为 `{parse, commit}`（检索前拒答，无 recall/fuse）；其余 `rag+no_answer` 仍为 `{parse, recall, fuse, commit}`；`validate_required_spans(record, span_names)` 按 `record.reason` 应用该规则。必须补测试：早退路径 `validate_required_spans == []`、检索后 no_answer 仍要求 recall/fuse、`docs/evaluation/trace_schema_v0_1.md` 同步更新。T006a 门禁将按此实现，不得再依赖 `rag+no_answer` 的旧单一口径。
10. **rerank 失败补测**：补一条"rerank 抛异常 → `rerank` Span status=error、异常/降级按既有语义"的断言（T003c 验收 M5 覆盖缺口，实现已被独立探针证明正确）。
11. **契约修订扩展（PM 裁决 2026-11-05，与 §5.9 同构）**：legacy 解析级早退（未执行 retrieve）的 `legacy+not_found` 采用 reason-aware：reason 命中实际枚举（如 NO_INTENT/UNRECORDED_FIELD 等）→ `{intent_parse, commit}`；执行过 retrieve 的 not_found 仍 `{intent_parse, retrieve, commit}`。同时对 legacy 路径**实际可达**但 T001 未定义的 outcome（conflict / knowledge_changed / no_answer / ambiguous / error 等，以探针实测为准）逐一给出"按实际执行、不伪造"的必需 Span 行；不可达组合保持 fail-closed。每行必须有探针证据并写入 `docs/evaluation/trace_schema_v0_1.md` 的例外/补充表；补测试（复现问题 `滨江店的负责人是谁？`、`滨江店宣传海报的负责人是谁？` 转绿；legacy+conflict 不得再抛 ValueError）；业务代码不变；T001 测试允许追加。T006a 将按新表实现。

## 6. 必须实际运行的检查（输出原文存证据目录）

```powershell
$env:MKTKB_PROJECT_TOTAL_LIMIT_CNY = "20.0"
git rev-parse --short HEAD
```

```powershell
.\.venv\Scripts\python.exe -B -m pytest backend/tests/observability/test_paths_e2e.py -q -p no:cacheprovider --basetemp backend\.pytest-tmp\paths
.\.venv\Scripts\python.exe -B -m pytest backend/tests/observability backend/tests/integration -q -p no:cacheprovider --basetemp backend\.pytest-tmp\obs-integration
.\.venv\Scripts\python.exe -B -m pytest backend/tests -q -p no:cacheprovider --basetemp backend\.pytest-tmp\t003d-full
git show --stat --oneline HEAD
```

## 7. 已知边界（必须遵守）

- T003c 验收（`review.md`）唯一 FAIL 项为"检索前拒答的 Span 必需集与冻结表冲突"：本包按 §5.9 用 reason-aware 契约修订解决，**不重写 T003c 代码**（其"不伪造 Span"实现正确）。
- **legacy 同构缺口（PM 2026-11-05 已预授权，见 §5.11）**：legacy 解析级早退 `not_found` 只有 `{intent_parse, commit}`；`legacy+conflict`/`legacy+knowledge_changed` 在 T001 表中未定义。按 §5.11 在本包内补齐，**不得以"HIGH 风险现状"交付**；若本包已按报告披露风险交付，则后续返工轮按 §5.11 补齐（不改业务代码，只补契约/文档/测试）。
- 中间件已先写 `path=rag`、`request_id=None`、`status=incomplete`；本包必须用 `set_path/set_request_id/set_outcome` 覆盖，不得新增第二个 trace。
- 端点内失败（401/422）会留下 incomplete trace；本包对"已进入 `_answer` 的失败"设 `outcome=error`/`service_error` 并记录 `error_code`；未进入业务层的失败允许保持 incomplete（在报告说明）。
- 既有 flake `test_g08_short_budget_cancels_inflight_model_call`（时序敏感，非本阶段引入）复跑可过；全量以重跑为准并记录。
- 所有 `*_json` 字段写 canonical JSON（T006a 门禁会校验合法性）。
- T003c 证据目录残留已由外部清理；`test_middleware.py` 注释若仍写"spans 为空"，本包顺手更正注释（不改断言强度，diff 留证）。

## 8. 提交

分支 `p0/obs-eval`，一个 commit：`p0/T003d qa legacy spans`；只 add 本包交付物；不 push（amend 后重采最终 HEAD stat）。

## 9. report.md 格式

五段：完成内容 / §5 逐条自证（命令或 文件:行）/ 实际运行结果（含 commit sha、stat、全量通过数）/ 偏离与未做 / 风险与遗留。末尾另给 ≤10 行交接摘要。

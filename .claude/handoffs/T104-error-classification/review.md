wb / cn:deepseek-v4.1-flash / reasoning_effort=max

# T104 独立验收 review

- 对象：`p1/fix-retrieval` @ `e7ee804deea5ab6b300690d6212e6bf5c4a8c0d5`；`git status --short` 空；未切分支/未 commit/push。
- 结论：**PASS**（7/7 必检项通过；无 FAIL/BLOCKED；必跑项无 NOT-RUN）。
- 口径：handoff/report 只作线索；下表 PASS 只引用本目录 `docs/reports/OBS-EVAL/P1/evidence/verify/T104/` 的自跑输出、`git diff/show` 与源码；未把开发 report 当证据。
- 环境：`.venv\Scripts\python.exe` 3.12.7；cwd=项目根；每条 pytest 前 `$env:MKTKB_PROJECT_TOTAL_LIMIT_CNY="20.0"`；`-B -p no:cacheprovider --basetemp backend\.pytest-tmp\<label>`；零真实模型/embedding/rerank/OCR。

## 复跑总览

| 范围 | 结果 |
| --- | --- |
| T104 本包（unit 29 + integration 9） | **38 passed**（6.19s） |
| `backend/tests/unit` | **335 passed**（6.78s） |
| `backend/tests/observability` | **255 passed**（17.63s） |
| `backend/tests/integration` | **361 passed / 1 failed**（270.13s） |
| 全量 `backend/tests` | **1678 passed / 0 failed / 0 error**（403.90s） |
| b0 local + gate | pass 29 / fail 3 / skipped 8；exit 3；hard `[]`；对 p0-b0 `case_diffs=0` |
| badcase local + gate | pass 9 / fail 4；exit 3；hard `[]`；对 p0-badcase `case_diffs=0` |

- integration 唯一失败 `test_chat.py::test_g08_short_budget_cancels_inflight_model_call`（`len(facts["calls"]) 0 != 1`，1.2s 总预算时序 flake）；隔离复跑 1 次 **1 passed**；全量同用例通过。
- 与 report 声明的 38 / 335 / 255 / 361+1 / 1678 逐项一致。

## 逐项证伪

1. **分类可区分 — PASS**。自写探针 `02-probe.py`（非开发测试）真实 HTTP 逐类触发，**147/147 checks passed**：配置 `MODEL_NOT_CONFIGURED`/False（零 gateway 调用）、预算 `MODEL_BUDGET_REFUSED`/False、provider `MODEL_UNAVAILABLE`/True、超时 `MODEL_TIMEOUT`/True（`ModelTimeout` 与 `asyncio.TimeoutError`）、输出校验 `MODEL_OUTPUT_INVALID`/True、未知 `MODEL_CALL_FAILED`/True、内部 `QA_INTERNAL_ERROR`/False。六个非 provider 类逐类断言 `!= MODEL_UNAVAILABLE`；与 report §3 矩阵及 `service.py:1432-1439` 一致。证据：`03-probe-results.md` §A。

2. **领域异常未被吞 — PASS**。新增 `except Exception` 仅在 `service.py:2182-2183`（query expansion 调用/校验）与 `:2317-2318`（answer 调用/校验）；检索 `:2163-2168`、扩展检索 `:2204-2211`、`qa.prepare` `:2031-2044`、`qa.answer` `:2050-2061` 的既有分支原样保留且在新捕获之外。第二处 try 内 `_validate_answer`（`:794-843`）、`_record_units`（`:910-955`）、`_record_facts`（`:1227-1285`）均为纯函数，不触库/qa/retrieve，不产生领域异常；`_call_model` 已先包非 `ModelError`。探针四路径最终结果未变：`KnowledgeRevisionChanged`→`knowledge_changed`；`IndexNotReady`→`INDEX_NOT_READY`/True；`QueryRejected`→`INVALID_QUERY`/False；`QaNotReady`→`INDEX_NOT_READY`/True（`03-probe-results.md` §B）。

3. **响应结构 / trace / 语义 — PASS**。`git diff e7ee804^ e7ee804 -- backend/src` 仅 `conversations/service.py`；`conversations/schemas.py:118-130` 的 `AskResult` 12 字段与父提交逐字相同。探针：每个 service_error 响应键集合恰为 12 字段、`AskResult.model_fields` 同集合；7 类均 `trace.outcome_kind=service_error` 且 `trace.reason == trace.error_code == body.error_code`、`validate_required_spans==[]`；observability 255 passed。`retryable` 旧路径（`except ModelOutputInvalid` True、`except ModelError` 用 `exc.retryable`）与新表对已知五码逐一相同，未注册码保留 `exc.retryable`。

4. **文案模板 — PASS（含 1 处 P2）**。8 个码（7 类 + `MODEL_POST_SEND_AUTH_DENIED`）均含“这是服务调用失败，不是资料中没有答案”与“服务端不会因重试而重复保存同一条回答。”；True 含“可稍后重新提问”且不含“重试不会自行恢复”，False 反之；配置/预算/内部均不含“可稍后重新提问”，无“配置错误说可稍后重试”的误导；provider 仍以“模型服务暂不可用”开头。`MODEL_BUDGET_REFUSED` 的“本次未发送请求”+统一句“这是服务调用失败”按产品级解读成立，重试建议明确为“重试不会自行恢复”，不构成可重试性误导。D-3：仅取值变化，字段未增删。**P2**：未注册码且 `retryable=False`（如 `_VendorSpecific`、基类 `MODEL_ERROR`）走 `_MODEL_ERROR_FALLBACK`，文案固定“可稍后重新提问”，与 `retryable=False` 不自洽；当前生产无该码路径（`MODEL_POST_SEND_AUTH_DENIED` 已登记），不影响七类/当前可达码，建议后续按 `retryable` 选 hint 或登记码值。`03-probe-results.md` §C/§E。

5. **既有断言同步 — PASS**。`git show e7ee804 -- backend/tests/unit/test_conversations.py` 仅 `:186` 一处精确文案期望扩为含三要素全文（`assert text == (...)` 仍逐字相等，未改子串/集合/删除），另 1 行注释；report §4 的同步清单与该 diff 完全一致（仅 1 处）。其余“预算或授权额度不足”子串、`MODEL_UNAVAILABLE` 前缀断言原样通过。

6. **范围 / 证据 / report — PASS**。`git show --stat e7ee804` 9 文件均在 handoff §4 允许路径；`git diff` 对 providers/、`schemas.py`、frontend/、`fixtures/evaluation/regression.jsonl`、`docs/evaluation/gate_v0_1.json`、b0/badcase 数据均为空；无 skip/xfail 新增；新测试只用受控 fake，评测 `runner.py:314-318` 强制 offline；证据 4 份、report 50 行 5 段、1 commit、分支正确。非阻塞：report §3 未内嵌 SHA（写“sha 见交付回复”），commit 可核为 `e7ee804`。

7. **ERR-07「营收未短路」残余 — PASS**。report §4 第 46 行明确记录（`intent.py` 缺失字段词表不含“营收”，RG005 仍 `kind=answer`，本包不改词表/短路）；`regression.jsonl` 未改；开发临时 regression 产物 pass4/fail3、hard `['security_leak']`、RG005 `kind_correct,refusal_expected` fail，与 report 一致。

## 非阻塞残余（不改变 PASS）

1. `budgeted.py:283/:293` 本地输入/单请求上限仍抛 `ModelUnavailable`；`deepseek.py:146-147` 任意非 200（含 401/403）→`ModelUnavailable` retryable=True。网关按 handoff 只读，T104 未改；部分配置/鉴权原因仍显示 provider 不可用。
2. 内部兜底只覆盖两处模型调用/校验窗口；`_answer` 更早的意图/取证/排序异常仍 HTTP 500，不归 `QA_INTERNAL_ERROR`。
3. `frontend/src/features/chat/MessageCard.tsx:64` 历史消息重试徽标仍按 `error_code !== 'MODEL_OUTPUT_INVALID'`；新增 `QA_INTERNAL_ERROR` 历史消息会显示重试按钮（实时响应用 `live.retryable` 正确）。report §4 已披露，留 T106。
4. report 未内嵌自身 SHA（见 6）。
5. 未注册码 + `retryable=False` 的兜底文案固定为“可稍后重新提问”（`service.py:1786`、`:1789-1794`），与 `retryable` 不自洽；当前无生产路径触发（基类 `ModelError` 未被任何 adapter 直接抛），P2，建议 T106 前按 `retryable` 选 hint。若验收口径要求“任意 `ModelError` 子类文案都必须与 retryable 一致”，此项可升级为 item 4 的 FAIL；按本包七类/当前可达码口径为 P2。

## NOT-RUN

- regression 全量 fresh run：NOT-RUN（非本包要求；以 `git diff` 空 + 开发临时产物 + RG005 明细交叉核对）。
- 前端构建/E2E：NOT-RUN（T104 不改前端；徽标不一致已按残余披露）。
- 真实模型/embedding/rerank/OCR：NOT-RUN（禁止项；均用受控替身/offline）。

## 证据（本目录，≤4）

- `01-verdict.md`：逐项判定与残余。
- `02-probe.py`：可重跑的独立探针（147 checks）。
- `03-probe-results.md`：探针输出摘要（分类矩阵/领域异常/文案/结构/幂等）。
- `04-test-eval-runs.md`：pytest 复跑、b0/badcase+gate、开发前后产物交叉核对、范围与残余。

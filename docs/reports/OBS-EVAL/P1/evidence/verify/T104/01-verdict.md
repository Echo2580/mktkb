# T104 独立验收：结论与逐项判定

- 对象：`p1/fix-retrieval` @ `e7ee804deea5ab6b300690d6212e6bf5c4a8c0d5`（`git status --short` 空；未切分支/未 commit/push）。
- 结论：**PASS**。7/7 必检项通过；无 FAIL / BLOCKED；必跑项无 NOT-RUN。
- 证据口径：本目录 02–04 均为验收者本机自跑；开发 `report.md` 只作线索，未用作 PASS 证据。
- 环境：Windows；`.venv\Scripts\python.exe` 3.12.7；所有 pytest 前设 `MKTKB_PROJECT_TOTAL_LIMIT_CNY=20.0`；cwd=项目根；`-B -p no:cacheprovider --basetemp backend\.pytest-tmp\<label>`。零真实模型 / embedding / rerank / OCR 调用。

## 判定表

| # | 检查项 | 判定 | 关键证据 |
| --- | --- | --- | --- |
| 1 | 分类可区分 + 非 provider 不报 `MODEL_UNAVAILABLE` | PASS | `02-probe.py` 147/147；`03-probe-results.md` §A |
| 2 | 既有领域异常未被 `except Exception` 吞 | PASS | 源码 `service.py:2163-2168/:2204-2211/:2031-2044/:2317`；探针四路径 |
| 3 | 响应字段结构不变、trace 一致、retryable 语义不变 | PASS | `git diff e7ee804^ e7ee804 -- backend/src` 仅 service.py；`schemas.py:118-130`；探针字段集/trace |
| 4 | ERR-07 文案模板逐类成立（含 1 处 P2：未注册码 + retryable=False 的兜底 hint 不自洽） | PASS | `03-probe-results.md` §C/§E；8 个码逐条核对 |
| 5 | 既有断言同步只限取值、无放宽 | PASS | `git show e7ee804 -- backend/tests/unit/test_conversations.py`；report §4 清单一致 |
| 6 | 范围/证据/report/无 skip/xfail/真实调用 | PASS | `git show --stat e7ee804`；`04-test-eval-runs.md` §C；report 50 行 5 段 |
| 7 | ERR-07「营收未短路」残余已记录 | PASS | report §4 第 46 行；evidence 04 §E；regression.jsonl 未改 |

## 1) 分类可区分（PASS）

探针（非开发测试）逐类触发真实 HTTP 路径（`02-probe.py`，147/147 checks passed）：

| 原因类别 | 触发方式 | error_code | retryable |
| --- | --- | --- | --- |
| 配置 | `app.state.model_gateway=None`（零模型调用） | `MODEL_NOT_CONFIGURED` | False |
| 预算·授权 | 网关抛 `ModelBudgetRefused` | `MODEL_BUDGET_REFUSED` | False |
| provider | 网关抛 `ModelUnavailable` | `MODEL_UNAVAILABLE` | True |
| 超时 | `ModelTimeout` / `asyncio.TimeoutError` | `MODEL_TIMEOUT` | True |
| 输出校验 | 网关抛 `ModelOutputInvalid` | `MODEL_OUTPUT_INVALID` | True |
| 未知 | 网关抛 `RuntimeError` → `_call_model` 兜底 | `MODEL_CALL_FAILED`（新增） | True |
| 内部 | monkeypatch `_validate_answer` 抛 `RuntimeError` | `QA_INTERNAL_ERROR`（新增） | False |

- 六个非 provider 类逐类断言 `error_code != "MODEL_UNAVAILABLE"`；配置类零模型调用。
- 与 report §3 矩阵、`service.py:1432-1439` 表逐项一致。

## 2) 领域异常未被吞（PASS）

- 新增两处 `except Exception` 仅在 `service.py:2182-2183`（query expansion 模型调用/校验窗口）与 `:2317-2318`（answer 模型调用/校验窗口）；检索段 `:2163-2168`、扩展检索 `:2204-2211`、`qa.prepare` `:2031-2044`、`qa.answer` `:2050-2061` 的既有异常分支原样保留、且位于新捕获之外。
- 第二处 try 内调用的 `_validate_answer`（`:794-843`）、`_record_units`（`:910-955`）、`_record_facts`（`:1227-1285`）均为纯函数，不触库、不调 qa/retrieve，不产生领域异常；`_call_model` 已把非 `ModelError` 包成 `ModelCallFailed`，领域异常不会走到 `except Exception`。
- 探针四路径（`02-probe.py`）：`KnowledgeRevisionChanged` → `kind=knowledge_changed`；`IndexNotReady` → `INDEX_NOT_READY`/True；`QueryRejected` → `INVALID_QUERY`/False；`QaNotReady` → `INDEX_NOT_READY`/True。均与改动前一致，未被归为 `QA_INTERNAL_ERROR`。

## 3) 响应结构 / trace / 语义（PASS）

- `git diff e7ee804^ e7ee804 -- backend/src` 只有 `conversations/service.py`；`conversations/schemas.py:118-130` 的 `AskResult` 12 字段与父提交逐字相同。
- 探针：每个 `service_error` 响应 JSON 键集合恰为 12 字段；`AskResult.model_fields` 同集合；成功回答路径未改 schema。
- 探针：7 类均满足 `trace.outcome_kind == "service_error"` 且 `trace.reason == trace.error_code == body["error_code"]`；`validate_required_spans == []`。`tests/observability` 255 passed。
- `retryable` 语义：旧 `except ModelOutputInvalid` 显式 True、旧 `except ModelError` 用 `exc.retryable`；新表 `service.py:1432-1439` 对五类已知码取值与旧路径逐一相同（config/budget False，provider/timeout/output True），未注册码保留 `exc.retryable`（`MODEL_POST_SEND_AUTH_DENIED` 仍 True）。

## 4) 文案模板（PASS）

- 8 个码（7 类 + `MODEL_POST_SEND_AUTH_DENIED`）均含“这是服务调用失败，不是资料中没有答案”与“服务端不会因重试而重复保存同一条回答。”；retryable=True 的码含“可稍后重新提问”、不含“重试不会自行恢复”，False 的码反之；配置/预算/内部均不含“可稍后重新提问”，不存在“配置错误说可稍后重试”的误导。
- provider 文案仍以“模型服务暂不可用”开头，保留 ERR-07 正面样本语义。
- `MODEL_BUDGET_REFUSED` 同时含“本次未发送请求”与统一句“这是服务调用失败”：按产品级“本次问答服务调用失败”解读成立，且重试建议明确为“重试不会自行恢复”，不构成可重试性误导（非阻塞观察，见 04 §D）。
- **P2（非当前可达生产码）**：未注册码 + `retryable=False`（`_VendorSpecific`/基类 `MODEL_ERROR`）走 `_MODEL_ERROR_FALLBACK`，文案固定“可稍后重新提问”，与 `retryable=False` 不自洽；七类矩阵与 `MODEL_POST_SEND_AUTH_DENIED` 不受影响。见 `03-probe-results.md` §E。
- D-3：仅错误码/文案取值变化，无字段增删。

## 5) 既有断言同步（PASS）

- `git show e7ee804 -- backend/tests/unit/test_conversations.py`：`test_conversations.py:186` 的逐字相等期望由旧短文案扩为含三要素的新全文；断言仍是 `assert text == (...)` 精确相等，未改为子串/集合或删除；另仅改 1 行注释。
- 其余“预算或授权额度不足”子串（`test_s2c_paygate_http.py:297`、`test_s2d_post_guard_http.py:333`）与 `MODEL_UNAVAILABLE` 前缀（`test_conversations.py:193`）原样通过；report §4 的同步清单与该 diff 一致（仅 1 处）。

## 6) 范围 / 证据 / report（PASS）

- `git show --stat e7ee804`：9 文件（report、service.py、2 个新测试、test_conversations.py、4 证据），均在 handoff §4 允许路径；`git diff` 对 `providers/`、`schemas.py`、`frontend/`、`fixtures/evaluation/regression.jsonl`、`docs/evaluation/gate_v0_1.json`、b0/badcase 数据均为空。
- `git show e7ee804` 无 `pytest.mark.skip/xfail/skipif` 新增；新测试全部走 `EvidenceEchoGateway`/自造 fake；评测 `runner.py:314-318` 强制 `provider_mode="offline"`。
- 证据 4 份；report 50 行 5 段；1 commit `e7ee804`；分支 `p1/fix-retrieval`。
- 非阻塞观察：report §3 写“sha 见交付回复”而未内嵌 SHA（handoff §8 要求 commit sha）；commit 本身可核为 `e7ee804deea5ab6b300690d6212e6bf5c4a8c0d5`。

## 7) ERR-07「营收未短路」残余（PASS）

- report §4 第 46 行明确记录：`intent.py` 缺失字段词表仍不含“营收”，RG005 本地仍 `kind=answer`，本包不做意图词表/检索短路。
- `git diff e7ee804^ e7ee804 -- fixtures/evaluation/regression.jsonl` 为空；开发临时 regression 产物（`%TEMP%\t104-post\regression`）为 pass4/fail3、hard `['security_leak']`、RG005 `kind=answer` + `kind_correct,refusal_expected` fail，与 report §3/§4 一致。

## 非阻塞残余（不改变 PASS）

1. `budgeted.py:283/:293` 的本地“输入超上界/单请求超 GO 上限”仍抛 `ModelUnavailable`；`deepseek.py:146-147` 把任意非 200（含 401/403）映射为 `ModelUnavailable` 且 retryable=True。网关按 handoff 只读，T104 未改；这会让部分配置/鉴权原因仍显示为 provider 不可用，属网关契约残余（见 04 §D）。
2. 内部兜底只覆盖两处模型调用/校验窗口；`_answer` 更早的意图/取证/排序非预期异常仍走 HTTP 500，不归 `QA_INTERNAL_ERROR`。满足本包“可触发、不冒充 provider”的口径，但“编排内全覆盖”不成立。
3. 前端历史消息重试徽标 `frontend/src/features/chat/MessageCard.tsx:64` 仍按 `error_code !== 'MODEL_OUTPUT_INVALID'` 推导；新增 `QA_INTERNAL_ERROR` 历史消息会显示重试按钮（实时响应使用 `live.retryable` 正确）。report §4 已披露，留 T106。
4. report 未内嵌自身 SHA（见 6）。
5. 未注册码 + `retryable=False` 的兜底文案固定“可稍后重新提问”（`service.py:1786`、`:1789-1794`），与 `retryable` 不自洽；当前无生产路径触发，P2，建议 T106 前按 `retryable` 选 hint。

## NOT-RUN

- regression 全量 fresh run：NOT-RUN（非本包要求；以 `git diff` 空 + 开发临时产物 + RG005 明细交叉核对）。
- 前端构建/E2E：NOT-RUN（T104 不改前端；徽标不一致已按残余披露）。
- 真实模型/embedding/rerank/OCR：NOT-RUN（禁止项；测试均用受控替身/离线模式）。

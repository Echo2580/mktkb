wb / cn:deepseek-v4.1-flash / reasoning_effort=max

# T104 报告：D1 异常原因透传（ERR-07 产品侧）

## 1. 完成内容
- `backend/src/mktkb/conversations/service.py`：新增 `ModelCallFailed`（未知，`:1418`）、码→可重试表（`:1432`）、`_classify_model_error`（`:1446`）、`_model_failure_result` / `_internal_failure_result`（`:1754`/`:1760`）、ERR-07 统一文案模板（`:1767`）。
- `_call_model` 兜底 `except Exception` 由 `ModelUnavailable` 改为 `ModelCallFailed`（`:1476-1478`）：无法归因的调用期异常不再冒充 provider。
- `_answer` 两处模型调用块（query_expansion `:2180-2183`、answer `:2315-2318`）改为按真实原因映射，并新增本地异常→`QA_INTERNAL_ERROR` 兜底；移除已被统一分类覆盖的 `except ModelOutputInvalid` 分叉。
- 文案统一：`{原因句}。这是服务调用失败，不是资料中没有答案；{重试建议}。服务端不会因重试而重复保存同一条回答。`；provider 类保留 ERR-07 正面样本语义。
- 新增 `backend/tests/unit/test_p1_t104_error_classification.py`（29 条）与 `backend/tests/integration/test_p1_t104_error_classification_http.py`（9 条）；仅同步 1 处既有取值断言（§4）。
- 证据 4 份：`docs/reports/OBS-EVAL/P1/evidence/T104/01..04`。未改网关/schema/前端/b0/badcase/gate/regression 文件。

## 2. 验收标准自证
1. **分类矩阵完整**：七类均由 monkeypatch/真实路径触发，码值互不相同（矩阵见 §3）；单元断言 `test_p1_t104_error_classification.py:44`、`:141`；HTTP 断言 `test_p1_t104_error_classification_http.py:191`。
2. **不再一律 MODEL_UNAVAILABLE**：配置/预算/超时/输出校验/内部/未知逐类断言 `!= MODEL_UNAVAILABLE`（单测 `:150`，HTTP `:191`）；provider 子类自定义码 `MODEL_POST_SEND_AUTH_DENIED` 保留（单测 `:169`，既有 `test_s2d_post_guard_http.py:303` 通过）。
3. **文案模板一致**：每类文案都含“不是资料中没有答案 / 可否重试 / 不重复落库”三要素（`test_p1_t104_error_classification.py:192`）；provider 仍以“模型服务暂不可用”开头（`:205`）；实际全文见证据 02 §B。
4. **响应结构不变**：每个 service_error 断言字段集合恰为既有 12 字段（`test_p1_t104_error_classification_http.py:44`、`:144`）；trace `reason == error_code == 响应码` 且 `validate_required_spans==[]`（`:158`）；`tests/observability` 255 passed。
5. **不误伤**：b0/badcase local 前后逐例 `0` 差异、hard `[]`（§3）；既有错误码测试仅 1 处取值同步（§4）；全量 `backend/tests` 1678 passed，0 failed/0 error。
6. **合规**：证据 4 份、report 五段、1 commit、仅改允许路径；无 skip/xfail/删断言/真实模型调用。

## 3. 实际运行结果
- 本包：`pytest tests/unit/test_p1_t104_error_classification.py tests/integration/test_p1_t104_error_classification_http.py -q` → **38 passed**，8.89s。
- 受影响目录：`tests/unit` **335 passed**；`tests/observability` **255 passed**；`tests/integration` **361 passed / 1 failed**（已知 flake：`test_chat.py::test_g08_short_budget_cancels_inflight_model_call`，隔离复跑 **1 passed**，全量通过）。
- 全量：`pytest tests -q` → **1678 passed**，432.64s，0 failed/0 error；全量前 `FreePhysicalMemory=2.98 GB`。
- b0：`b0-local-…359ed37c` pass29/fail3/skipped8 → `b0-local-…ede10da1` 同；gate exit 3、hard `[]`；`case_diffs=0`。
- badcase：`badcase-local-…c1aad3e1` pass9/fail4 → `badcase-local-…018e3089` 同；gate exit 3、hard `[]`；`case_diffs=0`。
- regression（未改文件）：`regression-local-…4a2f2f3c` pass4/fail3，hard `['security_leak']`，与 T103 收口一致；RG005 仍为 `kind=answer`（§4）。
- 异常分类矩阵（生产代码实际调用产生，证据 02 §A）：

| 原因类别 | error_code | retryable |
| --- | --- | --- |
| 配置 / 网关未注入 | `MODEL_NOT_CONFIGURED` | False |
| 预算·授权 | `MODEL_BUDGET_REFUSED` | False |
| provider | `MODEL_UNAVAILABLE` | True |
| 超时 | `MODEL_TIMEOUT` | True |
| 输出校验 | `MODEL_OUTPUT_INVALID` | True |
| 未知（调用期无法归类） | `MODEL_CALL_FAILED`（新增） | True |
| 内部（本地校验/编排） | `QA_INTERNAL_ERROR`（新增） | False |

- commit：`p1/T104 model error cause classification`（sha 见交付回复）；改动 2 文件 +94/−20（`service.py` +88/−18、`test_conversations.py` +6/−2）+ 新增 2 测试文件 + 4 证据 + 本报告。

## 4. 偏离或未做
- **既有断言取值同步清单（仅 1 处）**：`backend/tests/unit/test_conversations.py:186` 的 `_model_error_text("MODEL_BUDGET_REFUSED")` 由旧短文案同步为新全文（仍逐字相等，未放宽）；其余“预算或授权额度不足”子串断言与 `MODEL_UNAVAILABLE` 前缀断言原样通过。
- **内部 retryable=False 的理由**：失败点在模型返回后的本地校验/编排，同一构建+同一输入确定复现；重试只会重复消耗已付费调用，需告警修复（§3 矩阵）。未知 retryable=True：不排除暂态，但不冒充 provider。
- **regression 种子**：未新增/未改 RG005——它已是 `stratum=defect-t104`、`source_err_id=ERR-20261104-07` 的 T104 种子；dataset 层只能表达 kind/notes/forbidden，无法表达“按异常类型映射不同 error_code”，异常矩阵由本包 monkeypatch 测试承担（证据 04 §D）。
- **ERR-07“营收未短路”词表残余**：`intent.py` 缺失字段词表仍不含“营收”，RG005 本地仍 `kind=answer`（`kind_correct,refusal_expected` fail）。本包只做异常原因透传，不改意图词表/检索短路（证据 04 §E）。
- 新增码值 `MODEL_CALL_FAILED` / `QA_INTERNAL_ERROR` 尚未同步接口文档与前端取值枚举；前端历史消息可重试徽标仍按 `MODEL_OUTPUT_INVALID` 推导（`MessageCard.tsx:64`），留待 T106（证据 04 §F）。

## 5. 风险
- “未知”类别仍无法区分上游暂态与本地网关缺陷（只是不再冒充 `MODEL_UNAVAILABLE`）；内部异常转为 200 service_error 后，需依赖 trace span 的原始异常类名与告警发现代码缺陷。

# T104 证据 02：异常分类矩阵、可区分错误码与 ERR-07 文案

本表由生产代码实际调用产生（不是手写推断）。命令：

```powershell
$env:PYTHONPATH="backend/src"
.venv\Scripts\python.exe -B -c "from mktkb.conversations import service as s; from mktkb.providers.types import *; ..."
```

等价可复现断言见 `backend/tests/unit/test_p1_t104_error_classification.py:44`（`MATRIX`）与 `:141`。

## A. 分类矩阵（`_classify_model_error` / `_internal_failure_result` 实际返回值）

| 原因类别 | 触发（monkeypatch / 真实路径） | error_code | retryable | 说明 |
| --- | --- | --- | --- | --- |
| 配置 | `model=None`（网关未注入）/ `ModelNotConfigured` | `MODEL_NOT_CONFIGURED` | False | 重试无用，需管理员配置 |
| 预算·授权 | 网关抛 `ModelBudgetRefused`（预留/授权阶段拒绝） | `MODEL_BUDGET_REFUSED` | False | 请求未发出；需补额度或重签 GO |
| provider | 网关抛 `ModelUnavailable`（deepseek 网络/5xx/429 已归类） | `MODEL_UNAVAILABLE` | True | 保持既有 provider 码 |
| 超时 | `ModelTimeout` / `asyncio.TimeoutError` / 总预算用尽 | `MODEL_TIMEOUT` | True | 单次调用硬截止 |
| 输出校验 | `ModelOutputInvalid`（来源/字段/事实准入不过） | `MODEL_OUTPUT_INVALID` | True | 与既有行为一致 |
| 内部 | 本地校验/编排抛非预期异常（`_internal_failure_result`） | `QA_INTERNAL_ERROR` | False | 同一构建+同一输入确定性复现；重试只会重复消耗预算，需告警修复 |
| 未知 | 调用期抛出未分类异常（`_call_model` 兜底 → `ModelCallFailed`） | `MODEL_CALL_FAILED` | True | 无法归因（本地网关/依赖/上游均可能），不冒充 provider；不排除暂态 |
| provider 子类（既有） | `ModelPostSendDenied`（预留后/真实 POST 前授权复核拒绝） | `MODEL_POST_SEND_AUTH_DENIED` | True | 保留网关既有自定义码（`backend/tests/integration/test_s2d_post_guard_http.py:303` 既有断言） |

- 代码位置：`backend/src/mktkb/conversations/service.py:1418`（`ModelCallFailed`）、`:1432`（码→可重试表）、`:1446`（`_classify_model_error`）、`:1476-1478`（未知兜底）、`:1754`（`_model_failure_result`）、`:1760`（`_internal_failure_result`）。
- 非 provider 原因不再报 `MODEL_UNAVAILABLE`：单测 `backend/tests/unit/test_p1_t104_error_classification.py:150` 逐类断言；HTTP 单测 `backend/tests/integration/test_p1_t104_error_classification_http.py:191` 逐类走真实 API 断言。

## B. 文案（`_model_error_text` 实际输出，逐字）

统一模板：`{原因句}。这是服务调用失败，不是资料中没有答案；{重试建议}。服务端不会因重试而重复保存同一条回答。`

| error_code | 实际文案 |
| --- | --- |
| MODEL_UNAVAILABLE | 模型服务暂不可用，本次回答未完成。这是服务调用失败，不是资料中没有答案；可稍后重新提问。服务端不会因重试而重复保存同一条回答。 |
| MODEL_TIMEOUT | 模型服务响应超时，本次回答未完成。这是服务调用失败，不是资料中没有答案；可稍后重新提问。服务端不会因重试而重复保存同一条回答。 |
| MODEL_NOT_CONFIGURED | 问答模型尚未配置，请联系管理员。这是服务调用失败，不是资料中没有答案；重试不会自行恢复，需管理员完成配置。服务端不会因重试而重复保存同一条回答。 |
| MODEL_BUDGET_REFUSED | 当前预算或授权额度不足，本次未发送请求，请联系管理员处理。这是服务调用失败，不是资料中没有答案；重试不会自行恢复，需管理员补足额度或重新授权。服务端不会因重试而重复保存同一条回答。 |
| MODEL_OUTPUT_INVALID | 模型输出未通过来源与字段校验，已拒绝本次回答。这是服务调用失败，不是资料中没有答案；可稍后重新提问。服务端不会因重试而重复保存同一条回答。 |
| MODEL_CALL_FAILED | 模型调用失败且原因未能归类，本次回答未完成。这是服务调用失败，不是资料中没有答案；可稍后重新提问。服务端不会因重试而重复保存同一条回答。 |
| QA_INTERNAL_ERROR | 问答服务内部处理异常，本次回答未完成。这是服务调用失败，不是资料中没有答案；重试不会自行恢复，请联系管理员排查。服务端不会因重试而重复保存同一条回答。 |
| MODEL_POST_SEND_AUTH_DENIED | 预算或授权复核未通过，本次请求未发出，请联系管理员处理。这是服务调用失败，不是资料中没有答案；可稍后重新提问，但需先由管理员恢复授权。服务端不会因重试而重复保存同一条回答。 |

- ERR-07 正面样本语义保留：`MODEL_UNAVAILABLE` 文案以“模型服务暂不可用”开头，同时含“不是资料中没有答案 / 可稍后重新提问 / 不会重复保存同一条回答”三段（`backend/tests/unit/test_p1_t104_error_classification.py:205`）。

## C. 响应结构不变（D-3）

- 集成测试对每个 `service_error` 响应断言字段集合恰为 `request_id, message_id, kind, text, revision, sources, candidates, conflicts, missing_fields, pagination, error_code, retryable`（`backend/tests/integration/test_p1_t104_error_classification_http.py:44`、`:144`）；未新增/删除任何字段。
- Trace 的 `outcome=service_error`、`reason == error_code == 响应 error_code`，`validate_required_spans == []`（同类测试 `_assert_trace_matches`，`:158-164`）。

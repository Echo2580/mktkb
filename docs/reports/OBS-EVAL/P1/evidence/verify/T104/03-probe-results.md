# T104 独立验收证据：分类探针结果（147/147）

命令（cwd=项目根）：

```powershell
$env:MKTKB_PROJECT_TOTAL_LIMIT_CNY="20.0"
$env:PYTHONPATH="backend/src;backend/tests"
.\.venv\Scripts\python.exe -B docs\reports\OBS-EVAL\P1\evidence\verify\T104\02-probe.py
```

输出末行：`SUMMARY 147/147 checks passed; 0 failed`（退出码 0；stderr 仅 StarletteDeprecationWarning）。验收者已用本目录副本复跑一次，结果同。

探针不建真实 provider、不读 `.env`、不联网：用自造 `ProbeGateway` 注入 app，D01 经真实上传/worker/发布，逐类跑真实 HTTP `POST /conversations/{id}/messages`，并读 `trace_repo` 校验 trace。

## A. 七类原因实际返回值

| 原因类别 | 注入 | error_code | retryable | 观察到的关键检查 |
| --- | --- | --- | --- | --- |
| 配置 | `app.state.model_gateway=None` | `MODEL_NOT_CONFIGURED` | False | 200 service_error；零 gateway 调用；文案含“尚未配置”；trace 一致 |
| 预算·授权 | `ModelBudgetRefused` | `MODEL_BUDGET_REFUSED` | False | 200；`!= MODEL_UNAVAILABLE`；文案含“预算/授权/未发送请求”；trace 一致 |
| provider | `ModelUnavailable` | `MODEL_UNAVAILABLE` | True | 200；文案以“模型服务暂不可用”开头；trace 一致 |
| 超时 | `ModelTimeout` | `MODEL_TIMEOUT` | True | 200；trace 一致 |
| 超时 | `asyncio.TimeoutError` | `MODEL_TIMEOUT` | True | `_call_model` 转换；trace 一致 |
| 输出校验 | `ModelOutputInvalid` | `MODEL_OUTPUT_INVALID` | True | 200；`!= MODEL_UNAVAILABLE`；trace 一致 |
| 未知 | `RuntimeError` | `MODEL_CALL_FAILED` | True | `_call_model` 兜底；`!= MODEL_UNAVAILABLE`；文案含“原因未能归类”；trace 一致 |
| 内部 | monkeypatch `_validate_answer` 抛 `RuntimeError("T104-PROBE-INTERNAL-SECRET")` | `QA_INTERNAL_ERROR` | False | 200；`!= MODEL_UNAVAILABLE`；响应不含异常文本/RuntimeError；trace 一致 |

每个码均断言：HTTP 200；响应键集合恰为 12 字段；`kind=service_error`；`sources/candidates/conflicts` 为空；ERR-07 两句固定模板；retryable=True 含“可稍后重新提问”且不含“重试不会自行恢复”，False 反之；trace `outcome=service_error`、`reason == error_code == body.error_code`、`validate_required_spans == []`。

## B. 既有领域异常最终码（探针）

| 注入点 | 异常 | 最终结果 |
| --- | --- | --- |
| `service._retrieve` | `KnowledgeRevisionChanged` | `kind=knowledge_changed`，`error_code=None` |
| `service._retrieve` | `IndexNotReady` | `kind=service_error`，`INDEX_NOT_READY`，`retryable=True` |
| `service._retrieve` | `QueryRejected` | `kind=service_error`，`INVALID_QUERY`，`retryable=False` |
| `app.state.qa.prepare` | `QaNotReady` | `kind=service_error`，`INDEX_NOT_READY`，`retryable=True` |

四条路径均未被新 `except Exception` 归为 `QA_INTERNAL_ERROR`。

## C. 文案逐类

| error_code | 含“不是资料中没有答案” | 含“不会重复保存” | 重试建议 |
| --- | --- | --- | --- |
| `MODEL_NOT_CONFIGURED` | 是 | 是 | “重试不会自行恢复” |
| `MODEL_BUDGET_REFUSED` | 是 | 是 | “重试不会自行恢复” |
| `MODEL_UNAVAILABLE` | 是 | 是 | “可稍后重新提问” |
| `MODEL_TIMEOUT` | 是 | 是 | “可稍后重新提问” |
| `MODEL_OUTPUT_INVALID` | 是 | 是 | “可稍后重新提问” |
| `MODEL_CALL_FAILED` | 是 | 是 | “可稍后重新提问” |
| `QA_INTERNAL_ERROR` | 是 | 是 | “重试不会自行恢复” |
| `MODEL_POST_SEND_AUTH_DENIED`（未注册码保留网关 retryable=True） | 是 | 是 | “可稍后重新提问，但需先由管理员恢复授权” |

配置/预算/内部三类均不含“可稍后重新提问”；provider 文案以“模型服务暂不可用”开头。

## D. 结构与幂等

- `AskResult.model_fields` 与响应键集合均为：`request_id, message_id, kind, text, revision, sources, candidates, conflicts, missing_fields, pagination, error_code, retryable`（恰 12 个）。
- 新码 `MODEL_CALL_FAILED` 的重放：同 `client_request_id` 第二次请求 `message_id` 相同、gateway 调用数不变、历史消息数仍为 2（不重复落库）。

## E. 未注册码兜底的 P2（非当前可达生产码）

`_VendorSpecific(ModelError, code="MODEL_VENDOR_SPECIFIC", retryable=False)` 与基类 `ModelError`（`MODEL_ERROR`，retryable=False）：

```text
_model_failure_result(...).retryable = False
text = 模型服务调用失败且原因未能归类，本次回答未完成。这是服务调用失败，不是资料中没有答案；
       可稍后重新提问。服务端不会因重试而重复保存同一条回答。
```

即 `retryable=False` 但文案说“可稍后重新提问”；`_MODEL_ERROR_FALLBACK`（`service.py:1786`）未按 `retryable` 选择 hint。当前生产 adapter 未直接抛基类 `ModelError`，`MODEL_POST_SEND_AUTH_DENIED` 已登记，故七类/当前可达码不受影响；归为 P2，建议按 `retryable` 选 hint 或登记码值。

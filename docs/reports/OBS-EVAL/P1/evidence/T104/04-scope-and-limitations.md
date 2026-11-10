# T104 证据 04：范围、断言同步清单与残余声明

## A. 改动文件（仅允许路径）

| 文件 | 改动 |
| --- | --- |
| `backend/src/mktkb/conversations/service.py` | 新增 `ModelCallFailed` / 码→可重试表 / `_classify_model_error` / `_model_failure_result` / `_internal_failure_result` / ERR-07 统一文案模板；`_call_model` 兜底由 `ModelUnavailable` 改为 `ModelCallFailed`；`_answer` 两个模型调用块改为按原因映射并新增“内部”兜底 |
| `backend/tests/unit/test_p1_t104_error_classification.py` | 新增 29 条：七类原因矩阵、`_call_model` 透传、非 provider 不报 `MODEL_UNAVAILABLE`、provider 子类自定义码、ERR-07 文案三要素 |
| `backend/tests/integration/test_p1_t104_error_classification_http.py` | 新增 9 条：真实 HTTP 逐类码值/可重试性/字段集合/Trace 一致/幂等重放 |
| `backend/tests/unit/test_conversations.py` | 仅同步 1 处“取值断言”（见 B） |

未改：模型网关模块、`conversations/schemas.py` / 任何 API 字段结构、前端、b0/badcase 数据集、`gate_v0_1`、其他包文件、`fixtures/evaluation/regression.jsonl`。

## B. 既有断言“取值同步”清单（仅此 1 处）

- `backend/tests/unit/test_conversations.py:186`：`_model_error_text("MODEL_BUDGET_REFUSED")` 由旧短文案
  `当前预算或授权额度不足，本次未发送请求，请联系管理员处理。`
  同步为含 ERR-07 三要素的新全文（断言方式仍是**逐字相等**，未放宽）。
- 其余取值断言保持不变且通过：`MODEL_UNAVAILABLE` 仍以“模型服务暂不可用”开头（`test_conversations.py:193`）；
  `test_s2c_paygate_http.py:297`、`test_s2d_post_guard_http.py:333` 的“预算或授权额度不足”子串仍成立。
- 结构/行为断言零改动：`test_t09_security.py` 错误码矩阵、`test_chat.py` 超时/幂等、`test_paths_e2e.py` trace reason/error_code 均原样通过。

## C. 内部 / 未知的可重试性口径（handoff 要求写理由）

- **内部**（`QA_INTERNAL_ERROR`，retryable=False）：发生在模型已返回后的本地校验/编排（`_validate_answer` / `_record_facts` 等），同一构建 + 同一输入确定复现；失败点不是外部依赖，重试只会重复消耗已付费的模型调用，需告警修复。与 HTTP 500 信封的 `INTERNAL_ERROR` 分名，避免遥测口径混淆。
- **未知**（`MODEL_CALL_FAILED`，retryable=True）：异常从网关调用内逸出且无法归因（本地网关/依赖/上游均可能），不排除暂态，因此允许用户稍后重试，但不冒充 provider 不可用。

## D. regression 种子说明（dataset 层能力边界）

- `fixtures/evaluation/regression.jsonl` 的 RG005 已存在：`stratum=defect-t104`、`source_err_id=ERR-20261104-07`、`expected_kind=no_answer`、`forbidden_values=["MODEL_UNAVAILABLE","服务暂不可用"]`，本包未改其状态，也未新增重复种子。
- dataset 层只能表达 `kind / forbidden_values / notes`，**无法表达“同一响应按异常类型映射不同 error_code/retryable”**；该映射由本包 monkeypatch 单测（29 条）与真实 HTTP 集成（9 条）承担，避免用一条弱断言假装覆盖矩阵。

## E. ERR-07“营收未短路”词表残余声明

- `intent.py` 的缺失字段词表仍不含“营收”，因此“公司今年营收是多少”在本地仍落到模型路径，regression RG005 仍为 `kind=answer`（`kind_correct,refusal_expected` fail）。
- 本包只做**异常原因透传**，不改意图词表/检索短路；该残余属于 T105（指代/字段错配）与 T106（文案统一）之后的词汇治理，未在本包扩大范围。

## F. 已知限制

- 错误码/文案为取值变化（D-3 已授权），字段结构与 `retryable` 语义不变；新增码值 `MODEL_CALL_FAILED`、`QA_INTERNAL_ERROR` 需在后续接口文档/前端展示层（T106）同步取值枚举，本包按边界未改前端。
- 前端历史消息的可重试徽标仍按 `error_code != MODEL_OUTPUT_INVALID` 推导（`frontend/src/features/chat/MessageCard.tsx:64`），新码值的历史回放展示可能与实时响应不同；不影响实时响应与 API 契约，留待 T106。
- “未知”类别无法区分 provider 暂态与本地代码缺陷，仅能保证不再冒充 `MODEL_UNAVAILABLE`；trace span 的 `error_code` 保留原始异常类名用于诊断。

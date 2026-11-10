# T106 证据 01：reason→文案唯一映射

实现：`backend/src/mktkb/copy.py`（新增）。所有用户可见 reason 经
`REASON_COPY_KEY` 解析到一个 copy key；语义相同的 reason 只在
`REASON_ALIASES` 显式登记，不复制第二份文案（`copy.py:547/584/640`）。

## A. 交接单 §4-1 覆盖（33 个 reason）

| reason | copy key | retryable | material_related | 需用户补充 |
| --- | --- | --- | --- | --- |
| UNKNOWN_IDENTIFIER | UNKNOWN_IDENTIFIER | true | true | true |
| IDENTIFIER_NOT_RETRIEVABLE | IDENTIFIER_NOT_RETRIEVABLE | true | false | true |
| NO_INTENT | NO_INTENT | true | true | true |
| UNRECORDED_FIELD | FIELD_NOT_RECORDED（别名） | false | true | true |
| CONFLICTING_VALUES | CONFLICTING_VALUES | false | true | true |
| DOCUMENT_NOT_FOUND | DOCUMENT_NOT_FOUND | true | true | true |
| UNKNOWN_STORE | UNKNOWN_STORE | true | true | true |
| RECORD_ONLY | RECORD_ONLY | false | false | true |
| MULTIPLE_ENTITIES | MULTIPLE_ENTITIES | false | false | true |
| DOCUMENT_AMBIGUOUS | DOCUMENT_AMBIGUOUS | false | false | true |
| PRODUCT_AMBIGUOUS | PRODUCT_AMBIGUOUS | false | false | true |
| ITEM_AMBIGUOUS | ITEM_AMBIGUOUS | false | false | true |
| CHANNEL_AMBIGUOUS | CHANNEL_AMBIGUOUS | false | false | true |
| PRICE_TYPE_AMBIGUOUS | PRICE_TYPE_AMBIGUOUS | false | false | true |
| CLARIFICATION_REQUIRED | CLARIFICATION_REQUIRED | true | false | true |
| NO_EVIDENCE | NO_EVIDENCE | true | true | true |
| NO_SUPPORTING_SENTENCE | NO_SUPPORTING_SENTENCE | true | false | true |
| NOT_YET_EFFECTIVE | NOT_YET_EFFECTIVE | true | true | true |
| EFFECTIVE_WINDOW_CONFLICT | EFFECTIVE_WINDOW_CONFLICT | false | true | true |
| EFFECTIVE_WINDOW_EXPIRED | EFFECTIVE_WINDOW_EXPIRED | true | true | true |
| ANAPHORA_NO_ENTITY | ANAPHORA_NO_ENTITY | true | false | true |
| ANAPHORA_NO_FIELD | ANAPHORA_NO_FIELD | true | false | true |
| ANAPHORA_NEW_CONTENT | ANAPHORA_NEW_CONTENT | true | true | true |
| POLICY_FOLLOWUP | NO_EVIDENCE（别名；plan reason 保持内部） | true | true | true |
| NO_RECORD_FOR_ENTITY | NO_RECORD_FOR_ENTITY | true | true | true |
| NO_ENUMERABLE_RECORD | NO_ENUMERABLE_RECORD | false | true | true |
| PAGE_OUT_OF_RANGE | PAGE_OUT_OF_RANGE | false | true | true |
| FIELD_NOT_RECORDED | FIELD_NOT_RECORDED | false | true | true |
| INDEX_NOT_READY | INDEX_NOT_READY（服务错误模板） | true | false | false |
| KNOWLEDGE_CHANGED | KNOWLEDGE_CHANGED | true | true | false |
| EMPTY_QUERY | EMPTY_QUERY | true | false | true |
| UNKNOWN_REGION | UNKNOWN_REGION | true | true | true |
| MISSING_SLOT | MISSING_SLOT | true | false | true |

- 三要素自证：`material_related=false` 的文案均含“不是资料中没有答案”；
  `retryable=true` 的文案均含重试/改问提示；需要用户补充的文案均含“请/可选”。
  由 `backend/tests/unit/test_p1_t106_copy.py::test_every_entry_states_three_elements` 枚举断言。
- 唯一性：`COPY` 53 条模板无重复串；每个 reason 解析到的模板唯一
  （`test_every_copy_entry_is_unique` / `test_required_reasons_render_distinct_user_text`）。

## B. T104 服务错误矩阵（逐字未回退）

`copy.service_error_text()` 返回 T104 定稿文案；`_model_failure_result` 传真实
`retryable`，未登记码按 `retryable` 选提示（修复 T104 复核残余 5）。

| code | retryable | 关键提示 |
| --- | --- | --- |
| MODEL_NOT_CONFIGURED | false | 重试不会自行恢复，需管理员完成配置 |
| MODEL_BUDGET_REFUSED | false | 重试不会自行恢复，需管理员补足额度或重新授权 |
| MODEL_TIMEOUT | true | 可稍后重新提问 |
| MODEL_UNAVAILABLE | true | 可稍后重新提问 |
| MODEL_OUTPUT_INVALID | true | 可稍后重新提问 |
| MODEL_CALL_FAILED | true | 可稍后重新提问 |
| QA_INTERNAL_ERROR | false | 重试不会自行恢复，请联系管理员排查 |
| MODEL_POST_SEND_AUTH_DENIED | true | 可稍后重新提问，但需先由管理员恢复授权 |

所有条目均含“这是服务调用失败，不是资料中没有答案”与“服务端不会因重试而重复保存同一条回答。”
（`test_t104_service_error_matrix_is_unchanged`；既有 T104 单测/HTTP 测试全通过）。

## C. 关键文案取值变化（D-3 允许）

- `NO_INTENT`：不再只写“资料中未找到…”，补充“如果确认资料中存在，请改用更具体问法”。
- `IDENTIFIER_NOT_RETRIEVABLE`：保留“资料中未找到标识…”以满足验收可接受的缺失措辞，
  同时明确“本次未按标识检索，不能据此判断该记录不存在”。
- `RECORD_ONLY` / `CHAT_UNAVAILABLE` / `CHAT_ERROR` / `RETRIEVAL_ERROR` / `FACT_REJECTED`：
  统一声明“不是资料中没有答案”并给出重试/管理员路径。
- `MULTIPLE_ENTITIES`（RAG）与 `LEGACY_MULTIPLE_ENTITIES`（legacy）分开：legacy 保留
  “存在多个可能对象，请选择要查询的对象。”后追加“这不是资料中没有答案”，避免 e2e 断言漂移。
- 记录型冲突保留 FactValidator 可验证的既有句式（不追加额外说明句）。

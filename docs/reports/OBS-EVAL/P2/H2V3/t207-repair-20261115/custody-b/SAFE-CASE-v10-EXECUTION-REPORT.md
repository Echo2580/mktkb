# SAFE-CASE-v10-EXECUTION-REPORT

四个 case 的投影与 B 受控内存复跑一致；使用同一 loader 和投影实现，并非不同实现的交叉验证。脚本、来源哈希与已有审查及执行回执一致；复跑通过 case/run、plan/run、turn index 与收据日期检查。

以下仅列每轮 case_diagnostic 的固定字段及安全值：

## H2V3-C13

- turn 1: `{"bare_entity_followup":"unknown","dimension_uniqueness":"unknown","entity_reference_source_count":"unknown","explicit_switch_word":false,"observed_entity_inheritance_event_count":0,"policy_question":false,"two_dimensions_same_source":"unknown"}`
- turn 2: `{"bare_entity_followup":"unknown","dimension_uniqueness":"unknown","entity_reference_source_count":"unknown","explicit_switch_word":false,"observed_entity_inheritance_event_count":2,"policy_question":false,"two_dimensions_same_source":"unknown"}`
- turn 3: `{"bare_entity_followup":"unknown","dimension_uniqueness":"unknown","entity_reference_source_count":"unknown","explicit_switch_word":false,"observed_entity_inheritance_event_count":0,"policy_question":false,"two_dimensions_same_source":"unknown"}`

## H2V3-C22

- turn 1: `{"direct_rag":{"cited_count":2,"fact_count":2,"fact_source_count":2,"observed_confirmed_non_target_min":"unknown"},"saved_stores_count":2,"saved_stores_equal_constrained_targets":"unknown"}`

## H2V3-C26

- turn 1: `{"final_kind":"not_found","final_kind_is_not_found":true,"frozen_forbidden_value_match":false,"frozen_outcome_same_event_as_v8":true,"frozen_outcome_same_kind_as_v8":true,"frozen_outcome_text_equals_security_copy":true,"old_verdict_preserved":true}`

## H2V3-C28

- turn 1: `{"captured_field_role_empty":false,"direct_rag":{"cited_count":1,"fact_count":1,"fact_source_count":1,"observed_confirmed_non_target_min":"unknown"},"direct_result_row_bound":true,"explicit_identifier":"unknown","explicit_item":"unknown","identifier_shape_detected":false,"policy_question":false,"question_address":false,"question_contact":false,"question_phone":false,"restricted_role_present":false}`

- 数量是已捕获事实或已验证保存状态的计数；不代表所有运行时槽位、来源或实体均完整。`identifier_shape_detected` 仅表示形态匹配，不能证明已知标识命中。
- 目标集合关系、各阶段目标关系及无法确定的字段保持 `unknown`；布尔比较相同不证明跨轮继承。C26 旧安全判定标记不代表新产品复测或重新打分。
- 完整的各 case 安全字段见 `SAFE-CASE-v10-EXECUTION-CHECK.json`；白名单逐层校验通过。出站拦截正对照 3/3，账本和预算哈希一致。结论仅限安全元数据，不是产品验收。

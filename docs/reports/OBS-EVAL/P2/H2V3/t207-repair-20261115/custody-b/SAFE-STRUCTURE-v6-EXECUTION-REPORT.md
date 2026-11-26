# SAFE-STRUCTURE-v6-EXECUTION-REPORT

- 四个 case 的安全投影与 B 在受控内存中复现的结果一致；复现沿用同一既有 loader 和投影代码，故不是不同实现的交叉验证。复现过程未输出或保存私有中间内容。
- 脚本 SHA256 `957043e6b49bc23dbcabe4d2fa6bc5f37defbd84f46952d0075c18d0b5b2da81` 与 A 回执、B 先前审查记录一致；固定码来源 SHA256 `1987dfcf5920513aa639fe2da4c459f8ac28658fe64eaea5d34487690e3a97cd` 一致。受控复现完成了来源、case/run、plan/run、turn index 与收据日期检查。
- 可提供开发的逐 case 固定码见 `SAFE-STRUCTURE-v6-EXECUTION-CHECK.json`；允许字段和枚举校验通过。`target_count` 是标注 `targets` 的数量，不证明实际运行时槽位数量。`clarification` 仅为对应计划事件字段；`final_kind` 是所选事件的原始枚举，不等同于独立确认 `refusal_detected` 或 `answer_state`。
- 四个 case 的 `multi_target_present`、`actual_product_call_path`、每 turn 的 `entity_inheritance_observed`、`answer_state`、`refusal_detected` 和 `old_record_identity_inherited` 均为 `unknown`；不得据此推断肯定或否定。
- 来源既有 C26/C28 的安全轴标记 `preserved_old_verdict`；本次结构投影不改变该来源标记，不构成新的产品复测或打分。
- 本机出站拦截正对照 3/3；账本和预算哈希一致。核对仅涉及安全元数据，不是产品验收。

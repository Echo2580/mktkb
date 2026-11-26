# SAFE-EVENTS-v7-REPORT

状态：`blocked`；以下是本次审查发现的具体修正项。只检查源码与纯合成数据，未读取真实证据。

1. **重复与不完整身份**：`stage_relation` 未拒绝重复 stage ID；`_units_by_id` 将重复 unit ID 后值覆盖；必需过滤键存在但值为 `None` 时仍输出可比较和非目标确定值。合成反例均已复现。应在保留原始 rows 时检测重复，对所需身份及过滤值不完整输出 `unknown`，不能先压成字典而丢失冲突。
2. **截断与未解析**：当前只检查 `retrieval_observed.truncated`，未向阶段比较传入 `db_projection.truncations` 和 `unresolved_unit_ids` 等完整性信息。应按涉及阶段和字段保守处理相关截断、未解析及冲突，不能依据部分数据输出确定布尔。
3. **直接 RAG 阶段不完整**：capture schema 中 `direct_rag_answer` 同时有 `cited_unit_ids` 和 `facts[*].source_unit_id`，v7 只比较前者却将结果命名为整个阶段。合成反例中引用是目标、事实来自另一目标外单位，v7 仍返回 `any_non_target=false`。应分别标注引用层和事实层并各自核对，或完整合并后明确语义；缺失、不完整时 `unknown`。
4. **空阶段语义**：空 ID 列表当前返回 `all_comparable=true`、`any_non_target=false`。应明确区分“已证实空集合”和“缺失/截断/未收集”，不得把空比较当作目标身份已核对；输出应使用明确枚举或 `unknown`。对于多条检索/模型事件，明确分 scope/purpose 处理，重复或不能证明完整时保留 `unknown`。
5. **状态冲突**：`state_projection` 未检查 `row_present`。合成反例中 `row_present=false` 但 `state_json` 含值，仍输出存在 `true`；应将不一致及身份无法确认的状态/跨轮比较保留 `unknown`，不能把相等解释为继承。

核对通过的范围：v6 的来源哈希、case/run、plan/run、收据日期、turn index 和 key 初始化检查保留；计划路径、过滤键、reason/source 输出只用固定集合和值全等，非白名单映射 `other`。两组白名单字面量均可在声明的产品源码中找到。阶段字段路径与 capture schema 对应，但直接 RAG 事实层遗漏如上；目标构造遍历已有 `targets`，其完整性仍须与单位、阶段证据完整性一起判断，不能用于版本身份或评分结论。

自带合成自检退出码 0；独立合成反例已复现上述问题。网络拦截正对照 3/3，账本与预算哈希前后一致。结论仅限数据出口，不是产品验收。

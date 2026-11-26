# 保管侧最小零调用诊断契约

输入仅由已获相应授权的保管角色在受控内存中加载同一回合的真实事件与完整性绑定；普通开发不读取题答、实体、密文、key、私有计划或合同。核对身份、回合与代码绑定；禁止把新代码运行结果写回旧封存。

分别读取 prepared `plan_observed` 与实际检索后的 `retrieval_observed(scope=direct_rag_retrieval)`。新 SAFE 投影只返回角色白名单、状态码、非负数量、布尔与绑定哈希；原始候选 ID 仅留受控捕获，不出公开材料。先检查事件、字段及 sink 完整性；缺失、失败或不适用不可合成空集合或成功结论。角色投影必须识别 `role_unknown_count`；stores unknown 与 available/0 分开；候选列表截断、召回范围限制 unknown、分页 has_more 三者分开。

只有真实观测到的 `joined`、`already_present`、missing、ambiguous 或具体条件早退才能用于推断同次执行；缺事件或旧版无状态记 not_captured/unknown。若原封存本就无必要信息，不能靠旧聚合码推导。受控零调用重放如另获授权，只是派生诊断，须独立标识输入版本，不冒充原事件。当前没有私有证据，尚不具备定位真实 C29 的条件。

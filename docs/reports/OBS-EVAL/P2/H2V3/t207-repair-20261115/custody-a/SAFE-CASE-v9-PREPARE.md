# SAFE-CASE-v9-PREPARE

状态：待 B 核查数据出口；未读取真实证据或 key。

- 沿用 v8 受控 loader、case/run/turn/日期/来源绑定和固定异常出口；只增加受控内存纯计算，未执行真实投影、真实请求或重打分。
- C13：对受控问题使用现有 `SWITCH_WORDS` 与 `is_policy_question`；只计捕获到的 `entity_inheritance` 事件，不能视为完整引用来源数。裸追问需门店及 lexicon，引用来源唯一性和双维同源无法从该事件集合证明，均保留 `unknown`。
- C22/C28：直接 RAG 的事实、可解析事实来源、引用计数仅在字段类型及内部计数一致时输出；目标外单位下界仍为 `unknown`，未重新构造 matcher 或阶段完整性结论。C22 的已验证 saved stores 数量只在类型与唯一性成立时输出；与标注目标集合的比较仅在每个 target 明确有单值 `filters.store` 约束时进行，否则为 `unknown`。
- C28：使用现有 `is_policy_question`、`field_roles_for_question` 和 `identifier_shape`；字段角色在有无实体两种上下文判定一致时才输出布尔。标识形态不等于已知标识命中，物品与已知标识命中保留 `unknown`。直接 RAG 的事实与引用单位集合一致、投影和 capture 完整、单位 ID 唯一且 raw_fields 非空时，才用现有 `role_values` 输出受限角色存在性；不能绑定或字段缺失为 `unknown`。`field_role` 仅取 v8 已校验的 saved 状态。
- C26：调用冻结 `_final_outcome`，比较其与 v8 选取事件的对象身份及 kind；仅在事件无歧义且相同时做固定文案逐字比较。禁值检查在内存完整复用冻结 `p2_hard_evidence.py` 的 `value and str(value) in final_text` 表达式，只输出布尔，不产生 verdict；旧结果是否保留取最新安全工件中的 `violation/security_refusal_missing/preserved_old_verdict` 固定字段。文本和禁值不会输出或计算内容哈希。
- `SAFE-CASE-v9-SELFTEST.json` 覆盖合成重复事件、缺字段、任意文本、错 run、日期错配、无约束/不完整目标、禁值纯比较、单位绑定和截断反例；本机正对照 3/3。实际依赖的其他原生输出渠道仍待 B 核查。

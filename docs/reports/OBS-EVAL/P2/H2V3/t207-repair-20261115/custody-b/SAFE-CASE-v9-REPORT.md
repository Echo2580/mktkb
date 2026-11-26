# SAFE-CASE-v9-REPORT

状态：`blocked`。只核查源码和纯合成数据，尚不能执行真实投影。

必要修正：`saved_store_projection` 只检查每个 target 的 `filters.store`，不检查 target 的完整实体身份、重复或目标集合完整性。合成反例中 `entity_key` 为空仍返回集合比较 `false`，重复 target 仍返回 `true`。既有 `p2_hard_evidence.py:458-475` 的标注校验允许空 `entity_key`，因此不能依赖该校验排除前一个反例。应仅在目标身份完整、集合无歧义且可证明覆盖完整时输出比较；否则保留 `unknown`，并补相应合成反例。`saved_stores_count` 可按其独立来源检查保留。

其余核对：v8 的来源、case/run、plan/run、收据日期、turn index、key 初始化、输出屏蔽和网络防护代码保持；冻结最终事件选择和 `value and str(value) in final_text` 的纯比较式保留，未见其生成新 verdict。结果行判定检查完整性、事实和引用 ID 集合、单位唯一性及 raw_fields；公开捕获代码将所用 ID 对应至 `SourceUnit`。对同命名空间和完整性的意见仅限已检查代码及合成证据。问题函数只输出固定布尔、枚举、数量或 `unknown`；未发现直接输出原文、key、过滤值或单位 ID 的路径。

自带合成自检退出码 0；独立反例复现上述目标集合问题。网络拦截正对照 3/3，账本和预算哈希前后一致。未进行私有读取或产品测试；这不是产品验收。

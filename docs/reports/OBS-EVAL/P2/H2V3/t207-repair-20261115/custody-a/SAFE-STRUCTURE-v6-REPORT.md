# SAFE-STRUCTURE-v6-REPORT

状态：等待 B 复核；未读取真实证据。

- `safe_structure_v6.py` 补齐最终重算入口原有的 run receipt `business_date` 与 case-plan `run_binding.business_date` 比较；不一致直接失败，不写逐题结果。纯合成日期一致和不一致反例均通过。
- 对照原入口，沿用同批 key 初始化、`load_v3_bundle`、case-plan 与静态 bindings 校验、原 v1 run 题数一致性检查、`read_encrypted_evidence` 及全部 plan bindings；另保留逐 case/run、安全工件 SHA、plan/run 和 turn index 校验。v1 只用于原入口的题数检查，不取其轴结果或改分。
- 原重算入口中版本来源构造、旧卡重算身份和证据树摘要用于 matcher 重算及其报告；本包装器不运行 matcher 或重打分，不声称完成这些评分来源的重算校验。receipt 日期之外不额外推断 receipt 中的结果。
- 自测回执：`SAFE-STRUCTURE-v6-SELFTEST.json`；包含既有纯合成出口反例，网络正对照 3/3。仅 Python 流及 C 运行时标准输出描述符的屏蔽做了合成检查，其他原生输出渠道仍需 B 评估。
- 本次未运行真实入口，未读取私有证据或 key，未调用真实请求、重打分或产品验收。

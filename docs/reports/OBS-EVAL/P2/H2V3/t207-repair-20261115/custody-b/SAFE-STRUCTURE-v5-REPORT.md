# SAFE-STRUCTURE-v5-REPORT

状态：`blocked`。按要求与本批既有最终重算入口对照，v5 缺少一项既有来源绑定核对，补齐后再核查。

- 必要修改：`final/work/recompute_axes_final.py:825-832` 读取对应 run 的收据，并要求其 `business_date` 与 case-plan 的 `run_binding.business_date` 一致；`custody-a/safe_structure_v5.py:project` 未执行该检查。应复用该只读核对，在不一致时固定码失败且不写逐题结果，并加纯合成不一致反例。此处只确认检查被遗漏，未读取收据，也不声称实际日期不一致。
- 已检查包装器沿用同批次 key 初始化，调用现有 `load_v3_bundle`、case-plan 验证及 `read_encrypted_evidence`；逐 case/run、plan/run 和 turn index 有显式核对。按当前授权，既有 loader 在内存中处理题库与合同本身不作为阻塞。
- 包装器直接构造固定字段、枚举、布尔和计数；未知值保持 `unknown`，目标数量的来源为标注 `targets`。代码内未见直接调用 runner、重打分或 HTTP。错误出口使用固定码；源码包含 Python 与 C 运行时标准输出屏蔽，不对其他未实证渠道作绝对保证。
- 自带 `--self-test` 退出码 0；独立合成检查覆盖重复冲突、无效或缺失高优先级字段、重复计划、禁止文本不进入投影、错误 run 和缺失 target。网络拦截正对照 3/3。
- 未运行真实投影，未读取真实证据；账本和预算哈希在本次写出前后相同。结论仅限数据出口，不是产品验收。

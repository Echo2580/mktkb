# SAFE-PLAN-PRELIMINARY-REPORT

状态：`preliminary_blocked_pending_final_freeze`。本次为公开代码初审，A 的准备物尚未确认最终冻结；不可将本结论当作执行许可。

当前审查脚本 SHA256：

- `custody-a/prepare_plan.py`：`dc6f9b0a18ab2e4061b412f6e146e0e6d5b93fee2cd3b6c271b0fab4c9dc5cbd`
- `custody-a/execute_plan.py`：`089080863e6897791bca98bffc0719f03473bde95662bccdebd318b7b402de14`

需处理：

1. **环境值读取**：`prepare_plan.py:load_prior` 导入的既有 v3 入口在模块初始化时读取进程中的总预算环境变量，并可能在内存保留其原值；这与本次“不读环境值”边界不一致。应在不读取原值的前提下提供确定的受控运行环境，再确认既有入口及其依赖不会读取其他未授权环境值；不得读取或输出 `.env` 内容。
2. **冻结基线校验**：包装器明确比较了现有 ingest 哈希，但未看到在调用 `plan-private` 前，把当前场景契约和冻结清单文件分别与既有冻结基线的预期哈希作直接比较。既有 loader 对场景契约与公开审核绑定有检查，但不能据此证明冻结清单本身未变化。应在不输出私有材料的情况下完成对应基线校验，首错停。
3. **最终版本**：A 完成后应同时固定并复核执行脚本及其导入的准备脚本 SHA；本初审快照不能批准后续改动。

已检查：代码中仅一次 `plan-private` 派发，调用参数 `max-requests=1500`，未见 `run` 或 `check-only` 调用；有一次尝试标记，新计划目录检查仓外且原不存在。私有处理置于 Python 流及 C 运行时标准输出描述符屏蔽区，异常出口为固定码；公开回执字段按请求单构造。代码按当前工作树字节计算摘要并在调用后复核；r0/r1 请求上界、四场景批数、预算值及历史前缀均有检查。代码不会故意输出私有路径、题面、答案、key 或逐题内容。

本机 Python socket / urllib / httpx 拦截正对照 3/3；账本全文 SHA `e007fee3456e5d13f737a82ed29af45eb4707e3576c444e3520d9ca941dc2899` 与预算 SHA `79b21700b630be92148e2a8498ed47386dab08d6daa401601dc3d22a910b1a9e` 前后一致。账本历史前缀预期 SHA `f4710b1869fe43b9a609b58f772549f76370fbadd54f93685b76211d4b47a014` 为不同口径，未与全文 SHA 混用。B 未读取私有输入、未调用 `plan-private`。本意见不是产品验收。

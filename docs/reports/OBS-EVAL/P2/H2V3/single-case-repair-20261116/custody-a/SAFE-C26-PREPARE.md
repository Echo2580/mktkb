# SAFE-C26-PREPARE

状态：待 B 核查新出口；本次未读取本轮真实封存证据，未执行冻结初判。

- 已定位合法逐案初判：`backend/src/mktkb/evaluation/p2_hard_evidence.py:2755` 的 `classify_case_evidence`，内部逐回合走 `:2631` 并按 `:2725` 折叠。该入口直接接受本轮 case、冻结 annotation 和本轮 audit，不使用历史 oldcard。
- `c26_current.py` 为待审 C26 单案包装器，采用本轮既有受控入口的输入、key 初始化和 `read_encrypted_evidence`；验证本轮 run/plan/date、封存树与本轮公开回执一致、turn 绑定，以及依赖快照和账本/预算前后一致。脚本哈希与依赖快照见 `SAFE-C26-PREPARE.json`。
- 只投影 safety 的固定 state/reason、criterion、完整性码、事件 kind、固定文案相等及冻结禁值/禁源安全布尔。冻结初判禁源匹配沿用冻结 locator 口径，**不是 matcher v2**；禁源缺少可证明的正命中时保留 `unknown`。不改旧卡、旧分或评分逻辑。
- 合成检查验证安全状态投影和拒绝非枚举原因码；本机网络正对照 3/3。真实执行入口未运行，需 B 先核查新出口及封存绑定，不构成产品验收。
- 保密事故：准备时一次源码定位的脱敏输出不完整，工具输出包含一段私有路径片段，未输出 key、题面或答案；随后改用常量全量遮蔽，不在本报告复述路径。

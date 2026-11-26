# 受控保管侧输入输出契约

新入口：`revision2/repair1/work/safe_plan_projection.py` 的 `project_authenticated_turn(path, key, expected_bindings=...)`。仅获授权的保管角色可在受控环境调用；开发或经理不得因此打开真实题面、答案、实体、计划、binding、合同、密文或 key。`project_validated_turn` 只检查结构，不证明来源已认证；`project_plan` / `project_retrieval` 仅处理 payload，本身不能判断 sink，不能直接作为完整验收入口。旧 revision2 工具保留供审计，不作为新入口。

保管方必须先按既有程序核验来源权限、封存树/manifest/receipt、回合和源码身份，然后传入完整预期 binding。入口使用现有受控密文读取器认证 Fernet 与 binding，调用既有 turn validator，再检查 sink sealed、错误为空、完整性 complete、非 replay、非 timeout。它不会自行验证历史树/receipt，也不会修改封存或执行产品请求。

输出：固定状态、角色码、计数及布尔；不输出原始候选身份、题答、路径或密钥。failed/unsealed/incomplete/invalid 与 not_captured 分开。没有直答检索事件时通常 execution=unknown；只有确凿的固定前置拒绝 reason 才记 not_executed。事件存在时，空候选是显式观察值；未知角色、字段缺失和非法值独立标示。候选计数为本次返回并集，列表截断与分页有无下一页分别表达；不能推断全库覆盖。

历史事件缺字段仍保持缺失。若原封存不能提供信息，不能补写、反推根因或把任何后续派生重放冒充原事件。本轮未打开真实私有封存，当前尚不能定位真实 C29。

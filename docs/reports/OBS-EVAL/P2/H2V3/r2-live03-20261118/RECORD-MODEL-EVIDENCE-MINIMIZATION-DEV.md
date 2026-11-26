# 记录型回答模型证据最小化开发验证

2026-11-18。传统记录型回答按请求角色筛选模型证据中的联系字段，并移除逐行原文副本。本地原始 `SourceUnit` 仍用于事实校验和来源核对。

- 改前通过产品 HTTP 入口和 DeepSeek `MockTransport` 捕获真实序列化请求。只问状态、联系人、电话、地址的四条合成用例均因证据包含未请求的联系值而失败，退出码 1。合成数据中，联系值同时出现于 `evidence.fields` 和 `evidence.text`。
- 改后开发定向回归 `test_r2_206b_contact_gate_increment.py`、`test_c29_reverify_20261118_independent.py`、`test_source_access.py`、`test_chat.py` 合计 96 项通过，退出码 0。测试使用本地 TestClient、离线模型替身和 MockTransport。审查发现的凭据用例零模型调用断言误放已恢复，最终工作树由独立验收继续核对。
- 修改集中在 `conversations/service.py` 的 `_model_input` 和共用联系角色集合。新增测试覆盖未请求的联系值和显式请求单个角色时的实际 POST 载荷。本包验收范围是传统记录型答案的模型证据。用户输入与历史问题、文档证据及其他供应商链路按各自授权范围核对。

真实 R2 attempt5 暂停。本轮无真实供应商发送，真实基线为 attempt4 的 4/5。

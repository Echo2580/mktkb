# C-1 引用摘要脱敏开发复验

2026-11-18。项目经理选择先脱敏。此次开发复验覆盖 `sources[].locator.cells` 的整行快照暴露面。

`SourceSummary` 在构造引用摘要时移除 `locator.cells`，保留工作表、行号、文档版本等定位信息。问答响应、会话历史和冲突来源摘要共用这一模型。原始 `SourceUnit` 与经鉴权打开的来源详情属于原件查看范围。

- 改前，两条 C-1 合成 HTTP 断言在电话、地址和联系人值检查处复现，pytest 退出码 1。
- 改后，`test_r2_206b_contact_gate_increment.py`、`test_c29_reverify_20261118_independent.py`、`test_source_access.py`、`test_conversation_recovery.py` 合计 34 项通过，退出码 0。复跑既有独立探针由本修复窗口执行，属于开发复验。
- 模型探针确认引用行号和正文段落定位仍可用，调用者提供的原始定位对象字节对应值保持完整，来源详情继续走其独立模型。

没有新报价、预算或账本写入。未新签 GO，未执行真实 R2。attempt5 保持停在授权前置条件，最近真实结果仍为 attempt4 的 4/5。

# T-R2-OBS 开发报告：接线受范围约束

## 结论

本轮未修改产品源码，未实现直答检索事件、计划门店状态或联结判定捕获。原因是直答检索实际发生在授权文件之外；仅靠授权文件不能真实取得完整检索结果，也不能区分未满足条件与未捕获。没有重复检索、推断状态或伪造事件。真实 C29 根因仍未知，当前条件不足以定位。此报告是开发诊断，不是独立验收或 R2/T207 完成结论。

## 来源与最小接线缺口

- `conversations/service.py` 的 `qa.prepare()` 返回计划并在 `plan_observed` 发出 `field_role`/`field_roles`；事件 schema 本身已有这两个可选字段。历史报告称未捕获不能反证当前源码没有发射，历史捕获的具体缺失环节未经私有材料核验。当前这里没有 `state.stores` 数量，计划角色也应按 `RECORD_FIELD_ROLES` 与 `DOCUMENT_FIELD_ROLES` 白名单投影，未知值记 unknown，不写入原始字符串。最小接线需在该事件发射点增加 `stores_count`、可用性，配合 capture schema 的可选字段；计数不可将缺失默认为零。
- 直答通过 `qa/service.py:answer` 调 `RagIndex.ask`，实际检索在 `rag/answer.py:answer_question` 的 `index.search`；QA 的 `search` 方法不会被调用。`RagAnswer.diagnostics` 的 `_result_diagnostics` 仅含聚合计数和证据 chunk ID，缺完整候选 unit IDs、原始 `RetrievalResult.diagnostics.store_join`。不能把 citations 或 evidence IDs 冒充完整候选。最小接线需授权在 `rag/answer.py` 真正的 search 返回后观察 `RetrievalResult`，使用现有 `retrieval_observed` 契约发送候选单位身份，仅进入既有受控捕获；枚举分页截断应按真实结果定义，不能默认为未截断。检索前拒答、异常和未进入路径不得发成功事件。
- `rag/retrieval.py:_exact_recall` 对真实执行的判定只在 `store_row_missing`、`store_row_ambiguous` 或实际加入时的 `joined` 写入 result diagnostics。record 路径但未产生该键可能是条件未满足、已存在行未新增、或替身未提供状态；非 record 路径则未执行该精确召回。因而缺键只能记 `not_captured_or_not_recorded`，不可断言条件未满足。若要准确分离这些分支，需要另行授权对 `rag/retrieval.py` 增加纯观测固定码，包括执行点与未满足条件；不能据空值合成。结果应只在真实执行点产生。
- 结果固定码、布尔和计数经严格白名单校验；用户可读材料不得含原始候选 ID、门店、联系人、题面、答案。新增字段还须验证证据 IO 与消费者的向后兼容性，不能将失败事件当作空事件。

## 后续保管侧零调用诊断契约（尚未执行）

输入须由获授权保管角色在受控内存路径提供同一回合的已封存事件、版本/完整性绑定和上述真实存在的检索/计划观测；仅当原始材料确含所需事实时可做派生投影，不能修改旧事件或把重放伪称旧捕获。输出仅允许固定状态码、白名单角色码、存在布尔、数量和绑定哈希。每项显式区分 observed、not_applicable、not_executed、not_captured、unknown；没有直接证据不输出 joined/missing/ambiguous。禁止输出实体值、题答、原始 unit ID。当前历史材料缺关键字段；未证实受控重放能恢复这些字段，故尚不具备定位条件。

## 验证

实际命令、结果与限制见 `VALIDATION.md`。本轮既无真实 provider、付费模型、OCR、judge 或外部业务调用，也未读取私有材料。没有完成覆盖所有分支的本轮合成观测或开启/关闭对照；不把既有测试通过当成接线已验证。没有可回滚源码改动，因此不生成空回滚补丁。四个保护文件的开始与结束摘要见 `PROTECTION.md`。

本轮未安排真实付费运行；无本轮 settled 或保守费用记录，账本未复核。历史两次 settled 分别 0.0431940 / 0.0433000 元，历史保守合计 0.0930815 元，均来自既有报告，未重新对账。

## 独立验收建议和停止点

先决定是否授权最小增量：`conversations/service.py` 的计划事件接线、`rag/answer.py` 的检索返回点，以及确需区分前置条件时 `rag/retrieval.py` 的执行状态；`evaluation_capture.py` 负责可选字段与闭集。独立验收应覆盖成功、missing、ambiguous、条件不满足、非适用、未执行、未捕获，严格核对同输入开关前后 kind/text/sources/facts/pagination，一并验证网络与子进程守卫的反证。若不扩大源码范围，维持未捕获。locator.cells 已按主人决定接受登记，静默剔除 phone/address 和 s2b 均不在本次范围。本轮至此停止，不安排真实运行、R3 或全题验证。

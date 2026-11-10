# T105 证据 04：口径、偏离与限制

## A. RG006 收口口径（仅改该行）

- local 单轮执行会忽略 `turns`（P0 runner 声明 `execution.mode=single_turn`），因此 RG006 的 local 等价于“无上文问「那个海报呢」”，期望是澄清“要哪项信息”，不是多轮继承位置。
- 修复前实际返回 W11 正文摘要：`根据资料，滨江店的宣传海报（标识：QF01）位于店内外侧，数量 40 张。`，暴露了未问的门店/标识/位置/数量。
- 因此 `forbidden_values` 由 `["店内外侧","40 张"]` 加强为 `["店内外侧","40 张","QF01","滨江店"]`（四项均来自修复前实际输出，至少覆盖位置/数量/标识/门店）；`expected_kind=clarification` 保持不变；`notes`/`reference_answer` 写明“local 单轮等价无上文、多轮由 integration 证明”。
- 多轮完整复现仍依赖 T109 的 multi-turn runner；本包不以修改 RG006 的 `turns` 或 dataset 结构来冒充多轮，由 `backend/tests/integration/test_p1_t105_anaphora_field.py` 的真实 HTTP 多轮用例承担。

## B. 为什么必须改 `answer.py`（+13/−1）

- `parse_query` 对“只继承一个记录字段”的指代追问置 `enumerate=True`，这是产品层 `conversations.service._rag_owns_turn` 的既有入口（否则该轮落到 legacy 措辞层，后者按整条记录渲染）。
- 但 `_answer_record` 看到 `enumerate=True` 会进 `_enumerate_answer`，按记录逐条输出全字段/多字段，正是 ERR-06。
- 改动只在 `_answer_record` 入口：当 `plan.enumerate` 且本轮是“指代 + 单字段 + 非显式全部/列出/翻页”时，复制计划并把 `enumerate` 置 False，再走既有单字段渲染；`plan.state.enumerate` 与对外 `state` 均为 False。没有改 `conversations/`、`intent.py`、枚举/分页契约或正文路径。
- 代价：检索阶段 trace 的 `plan.enumerate` 仍为 True（路由标记），答案阶段才翻转；观察层测试 255 passed，未新增 trace 断言破坏。

## C. 接续说明（前序失败与本轮处置）

- 前序 T105 开发 subagent 于 2026-11-06 04:19 前后执行失败、无收尾消息、未 commit；工作树保留 `query.py`(+102)/`answer.py`(+14) 与 2 个测试文件。本轮未丢弃、未重做。
- 保留：anaphora 字段继承 / 无字段澄清 / 无源判定主体逻辑、`ANAPHORA_NO_ENTITY`/`ANAPHORA_NO_FIELD` 文案、`_RAG_OWNED_CLARIFICATION_FILTER` 复用、13 条既有测试。
- 修正：删除死代码 `is_anaphora_question`；`_anaphora_residual_terms` 过滤“前面/刚才/上述/这家…”等纯指代词（否则产品层对“刚才那个呢”落到 legacy 后答 `not_found`）；`is_anaphora_field_followup` 增加“第 N 页”守卫；新增 2 条测试（多字段上文→澄清、HTTP“刚才那个呢”只答继承字段）。
- 本轮补做：RG006 收口、b0/badcase/regression 前后对照、observability/rag/integration/全量、4 份证据、report、单 commit。

## D. 边界与残余限制

- 未改：`conversations/` 层、`intent.py`、b0/badcase 数据集、`gate_v0_1` 配置、其他包文件；未切分支/未 push/未 amend；无 skip/xfail/删断言；无真实模型调用；未读 `.env`/Holdout；未新增生产依赖。
- “带新内容的指代追问”（如“那个海报的打印材质呢”）在 `2306aaa` 不进入本分支、仍走既有正文/legacy 检索（避免抢正文）；**R1 已收窄**：非台账字段直接给“未记录”提示，见 §E。
- 指代词表沿用既有 `ANAPHORA_WORDS`；“上面那个呢”等未列入该表的说法不在本包覆盖范围。
- 文档型字段追问（高度/条款）保留既有正文路径，不强制澄清“哪项信息”。
- 本轮全量未复现既有 `test_g08_short_budget_cancels_inflight_model_call` flake；该 flake 的隔离复跑流程仍按既有包记录执行。

## E. R1 返工口径与残余（B1/B2）

- **B1（分页优先）**：`query.py` 的 T105 指代分支入口增加 `not (page_request is not None and previous.enumerate)` 守卫，`第N页/下一页` 在枚举后不再进入指代澄清；分页/枚举契约与单独 `第2页`（无指代）行为不变。
- **B2（不倾倒）**：①含记录字段的指代追问（本轮显式实体）→ `enumerate=True`，答案层按单字段渲染；②非台账字段的新内容（打印材质/陈列要求）→ `reason=ANAPHORA_NEW_CONTENT`，`answer.py:230-238` 在 `_answer_record` 入口直接 `_no_answer`（产品层 `not_found`，文案「资料中未记录这项信息…」），不先走正文/legacy、不输出记录字段。未改 `conversations/`、`intent.py`、fixtures。
- **P2 残余（非阻塞）**：该收窄对“正文语料确含该内容”的问题存在保守误判（答“未记录”而非正文答案）；相对基线（整条倾倒）属“不倾倒”而非误答，由 R2 探针按 `rework-R1.md` §5-3 证伪条件核验。
- **观察项（R2 已证伪并修复）**：~~新增 `elif`（显式实体+记录字段+指代）未显式排除“政策题+实体+字段词+指代”的组合，T101/T102 定向 44 未覆盖该组合；现有测试与探针未见回退。~~ 该判断不成立：R2 独立探针实测 C5 系列返回继承的位置/规格（27/29 字），C3/C6 被压成 35 字 `not_found`；已在 R2 修复，见 §F。
- **接续说明**：R1 代码与全套实测由暂停前开发上下文完成；本证据 R1 段由接续上下文补记，未改代码，仅补 1 个 commit（4 文件代码/测试 + 本报告 + 证据 03/04）。

## F. R2 返工口径与残余（政策/法规指代拦截）

- **判据边界**：`is_policy_followup` 与 `is_policy_question` 同口径（含 `is_regulation_question`），只排除「要求/规则」这两个同时是台账字段名的词。理由：若直接用 `is_policy_question`，B2 点名项「那个海报的陈列要求呢」会被改判成政策题而回退（实测 55/62，B2-display 变 576 字倾倒）；排除后 B2 保持 35 字 `not_found`。
- **路由口径**：仅 `指代 + 政策/法规 + 本轮显式实体 + 无自身字段角色` 进入 `POLICY_FOLLOWUP`；无显式实体的 `那个流程要提前几天提报`（C8）不进，保持 legacy 139 字。该轮清继承 `field_role/field_roles`、保留实体状态，置 `enumerate` 作为产品层既有入口；`terms` 改用 `_anaphora_residual_terms`（指代实体不是检索过滤条件）。
- **答案口径**：`answer.py:_policy_document_plan` 把该轮换回 document 计划（清实体过滤，保留问题显式点名的 `doc_id`），走既有 `_answer_document`；`POLICY_FOLLOWUP` 跳过制度/法规标题句与换行截断半句。C7 在 `_answer_record` 末尾用 `lexical`（record 计划下已按门店/物品过滤）判定“记录存在、缺字段”，文案「资料中未记录日期（记录存在，但缺少该字段）。」，不再称“没有匹配记录”。
- **未改**：`conversations/` 层、`intent.py`、fixtures/b0/badcase/gate、检索/枚举/分页契约；无 skip/xfail/删断言；无真实模型调用；未读 `.env`/Holdout；未新增生产依赖；未 push/amend。
- **残余（非阻塞）**：①C3/C4/C5/C6 由内核 offline 抽取式正文作答，产品 `sources` 为空（`_rag_turn_result` 只从 `facts` 取来源；文档答案只有 citations；未改 conversations，故保留）；②回答比 legacy 的 C1/C2（518/861 字多条证据回显）短，为抽取式单段既有行为；③词面启发式仍有同形未覆盖（如其它“字段名+政策词”组合）；④未跑真实模型/live/Holdout。

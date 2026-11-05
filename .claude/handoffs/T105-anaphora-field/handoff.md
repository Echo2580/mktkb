# T105 交接单：D6 指代/字段错配（ERR-06，P1 第 7 包）

> 基线：分支 `p1/fix-retrieval`（自 `main@083eaef`；T100/T107/T101/T102/T103/T104 已收口）。**注意 T102 刚改过 `query.py` 的 anaphora/reset/区域词逻辑**，本包在其之上最小增量，不得回退 T102 行为。
> 执行者：开发 subagent（`wb / cn:deepseek-v4.1-flash`，`reasoning_effort=max`）。PM 不写代码。

## 1. 目标（一句话）
修「那个海报呢」类指代追问：**继承了实体就不要再倾倒整条记录全字段**——有上文问某字段时继承"问什么"并只答该字段；没有可继承的字段时澄清"要哪项信息"；指代无源时澄清，不得整条渲染。

## 2. 背景（ERR-06，依据 `错误记录-20261104.md` §ERR-20261104-06）
- 现象：问「那个海报呢」→ 返回 `WL-2026-0001 宣传海报` 整条主数据（物料编码/名称/分类/规格/型号/单位/品牌/存储/渠道/参考供价/仓库/生命周期/创建日期 共 12 个字段）。数值都对，但"答的不是那个问题"。
- 根因（推断）：`那个` 命中 `ANAPHORA_WORDS`；系统继承/匹配到 `item=宣传海报`，但新问题 `field_role=None`，既不澄清也不报"无字段"，走了"渲染命中记录全部角色值"的路径 —— **继承了实体，没继承"要问什么"**。
- 待确认语境（设计 §3 采纳口径）：
  - 上文问「城西区宣传海报**在哪**」→ 应只答位置（`C区2号货架第一层`）；
  - 上文没提过海报 → 指代无源，应澄清；
  - 上文问规格/价格 → 只答该字段（不再啰嗦倾倒）。
- 当前代码（T102 后，函数名定位）：`query.py` `ANAPHORA_WORDS`(:88)、字段角色解析（`field_role` 附近）、`_new_state` 继承（:679 起）、anaphora/reset 判定（:1014-1043）；`answer.py` 渲染记录答案的 `_record_answer_text`/`_record_facts`（"全字段倾倒"发生在 `field_role=None` 的记录渲染路径）。

## 3. 输入（先读这些）
1. `.claude\handoffs\2026-11-04-p1-design.md` §3（T105 行）、任务拆解 T105 段。
2. `错误记录-20261104.md` §ERR-20261104-06（:270-302）。
3. `backend/src/mktkb/rag/query.py`：`ANAPHORA_WORDS`、`field_role/field_roles` 解析、`_new_state`/继承、anaphora+reset（:1014-1043）、`parse_query` 返回结构。
4. `backend/src/mktkb/rag/answer.py`：记录型答案渲染/字段选取（只读理解；仅在必须时最小改）。
5. 既有测试：`backend/tests/rag/test_query_state.py`、`backend/tests/integration/test_s2b_intent_semantics.py`（bare store followup 等）、`backend/tests/rag/test_query_*` 里 anaphora/字段角色用例；**T102 新增的 `test_p1_t102_state_inheritance.py` 必须保持通过**。
6. `fixtures/evaluation/regression.jsonl` RG006（本包收口；多轮完整复现依赖 T109，见 §5）。

## 4. 交付物（只准写这些路径）
1. `backend/src/mktkb/rag/query.py`（主改：anaphora 追问的字段角色继承/澄清/无源判定）。
2. `backend/src/mktkb/rag/answer.py`（**仅必要**：避免 `field_role=None` 时渲染全字段；改动最小，report §4 单列）。
3. `backend/tests/` 本包测试（rag 单测 + integration 多轮；必须覆盖"上文问位置→只答位置""无上文→澄清""上文问价格→只答价格"）。
4. `fixtures/evaluation/regression.jsonl`：**仅**收口 RG006（按实现口径更新 `expected_kind`/`forbidden_values`（如保留/加强"不得出现规格/价格等未问字段"）/`notes`），可追加 T105 种子；**禁止动 RG001–RG005/RG007**。
5. `docs/reports/OBS-EVAL/P1/evidence/T105/`（≤4 份证据）
6. `.claude/handoffs/T105-anaphora-field/report.md`（五段，≤80 行）
7. 1 个 commit（见 §7）
**不要写**：`conversations/` 层、`intent.py`、b0/badcase、gate 配置、其他包文件、`.claude/handoffs` 其他文件。

## 5. regression.jsonl 收口（RG006）
- 目标：local 单轮（turns 被忽略，等价于无上文）「那个海报呢」应输出**澄清**（要哪项信息），不得整条渲染；`expected_kind=clarification` 保持；`forbidden_values` 应覆盖"整条记录字段"（如物料编码/规格型号/参考供价/仓库 等至少 2 个未问字段，具体按现有 forbidden + 加强）；`notes` 写明"多轮完整复现依赖 T109；本包用 integration 多轮证明"。
- 允许为口径更新修改该行；**不得**改弱为只测文案；RG001–RG005/RG007 一律不动。

## 6. 验收标准（逐条可判定）
1. **不倾倒全字段**：`那个海报呢`（无上文 / 有上文）任何路径都不得返回 12 字段整条渲染；答案只含被问字段（或无字段时澄清）。
2. **有上文问位置→只答位置**：多轮（先「城西区宣传海报在哪」→「那个海报呢」）应给出位置（C区2号货架第一层/P02 或等价），不得夹带价格/规格等未问字段。
3. **有上文问价格/规格→只答该字段**；**指代无源→澄清**（问清哪项信息或澄清对象不存在）。
4. **不误伤 T102/T101**：`test_p1_t102_state_inheritance.py`、`test_p1_t101_*`、既有 follow-up/topic-switch 用例全绿；裸门店 followup 行为不变；政策题不继承实体行为不变。
5. **regression**：RG006 按 §5 收口后 local PASS；RG001–RG005 仍 PASS、RG007 状态/失败集不变；gate 无新 hard failure 名称。
6. **回归**：本包测试 + `backend/tests/rag` + `backend/tests/integration` + 全量 `backend/tests` 0 failed/0 error（§11A 各 1 次；内存当前 2.51GB；既有 flake 隔离复跑 1 次）；b0/badcase local run+gate 前后对照：`hard_failures` 无新增、case 级 0 变化（P0 基线 b0 pass29/fail3/skipped8、badcase pass9/fail4）。
7. 证据 ≤4 份、report 五段、1 commit、只改允许文件、无 skip/xfail/删断言。

## 7. 提交要求
- 分支 `p1/fix-retrieval`；**1 个 commit**，消息：`p1/T105 anaphora field inheritance + no-field clarification`；不 push/不 amend 历史。
- 提交前 `git status --short` 只含允许路径；report 记录 commit 信息（sha 写交付回复即可）。

## 8. 报告格式（五段，≤80 行）
1) 完成内容；2) 验收标准自证（每条 ≤2 行，带命令/`文件:行`）；3) 实际运行结果（本包/rag/integration/全量 + b0/badcase/regression 前后对照 + commit sha + stat）；4) 偏离或未做（含 RG006 口径理由、answer.py 改动理由、多轮依赖 T109 声明）；5) 风险（一句话）。

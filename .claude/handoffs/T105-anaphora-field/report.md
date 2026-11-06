wb / cn:deepseek-v4.1-flash / reasoning_effort=max

# T105 报告：D6 指代/字段错配（ERR-06，P1 第 7 包）

## 1. 完成内容

- `backend/src/mktkb/rag/query.py`（+100）：指代追问分支（:1272-1318）、`_anaphora_residual_terms`（:774）、`_anaphora_field_text`（:792）、`is_anaphora_field_followup`（:323）；三类语境：继承唯一字段只答该字段 / 无可继承字段澄清“哪项信息” / 无源澄清对象。
- `backend/src/mktkb/rag/answer.py`（+13/−1）：仅在 `_answer_record`（:230-234）把“指代 + 单字段 + 非显式枚举”的路由标记 `enumerate` 在渲染前置 False，避免 `_enumerate_answer` 倾倒整条记录。
- `backend/tests/rag/test_p1_t105_anaphora_field.py`（9 条）、`backend/tests/integration/test_p1_t105_anaphora_field.py`（6 条）：覆盖位置/数量/价格/规格、无上文、无实体、多字段、显式枚举、另一指代词。
- `fixtures/evaluation/regression.jsonl`：仅 RG006（`forbidden_values` 加强为 4 项、notes/reference_answer 更新）；RG001–RG005/RG007 未动。
- 证据 4 份 `docs/reports/OBS-EVAL/P1/evidence/T105/01-prefix-status.md`～`04-scope-and-limitations.md`；本报告；单 commit。

## 2. 验收标准自证

1. **不倾倒全字段**：无上文 `那个海报呢` → `clarification/ANAPHORA_NO_FIELD`、文案只问“哪项信息”（`test_p1_t105_anaphora_field.py:119`，HTTP `:150`）；有上文多字段 → 澄清（`:151`）；产品路径断言无规格/价格/数量/标识（HTTP `:94`）。
2. **上文问位置→只答位置**：单测 `:60` 断言仅 `C区2号货架第一层`、无 `A2 铜版纸 157g/2.6/20`；HTTP `:94` 另断言无分页契约、有来源。
3. **价格/规格（及数量）→只答该字段**：单测 `:77/:91/:105`，HTTP `:108/:122/:136`；**无源→澄清**由 `:131`（无实体）与 `:119`（无字段）覆盖。
4. **不误伤 T101/T102**：`tests/rag` 335 passed、`tests/integration` 368 passed；`test_p1_t102_state_inheritance.py`、`test_p1_t101_vocab_context.py`、既有 follow-up/topic-switch 全绿；政策题守卫 `is_policy_question` 未改。
5. **regression**：RG006 local `fail/answer/(kind_correct,value_forbidden)` → `pass/clarification/()`；RG001–RG004/RG006 pass，RG005/RG007 失败集与基线逐项相同；gate hard `['security_leak']` → `[]`（无新增名称）。
6. **回归**：本包 15、rag 335、integration 368、observability 255、全量 1693 passed（0 failed/0 error）；b0/badcase 逐例 0 差异（pass29/fail3/skipped8、pass9/fail4，hard `[]`）。
7. **合规**：证据 4 份、report 五段、1 commit、仅允许路径；无 skip/xfail/删断言/真实模型调用/新依赖。

## 3. 实际运行结果

- 本包：15 passed（17.97s）；rag 335（45.05s）；observability 255（37.95s）；integration 368（401.50s）；全量 1693（最终树 437.48s，运行前 `FreePhysicalMemory=5.10 GB`，无需轮询等待）。
- 本轮无既有 flake 复现（`test_g08_short_budget_cancels_inflight_model_call` 在 integration/全量均通过）。
- b0：`b0-local-20261105T090359232489Z-6e3eb84c` pass29/fail3/skipped8 → `b0-local-20261106T002138228442Z-e4560569` **同数同例**，gate exit 3、hard `[]`，`case_diffs=0`。
- badcase：`badcase-local-20261105T090409960294Z-f03d4b5f` pass9/fail4 → `badcase-local-20261106T002142276281Z-7a9b4bd5` **同数同例**，gate exit 3、hard `[]`，`case_diffs=0`。
- regression：基线 `regression-local-20261106T001846178302Z-e584b08e` pass4/fail3、hard `['security_leak']` → 收口后 `regression-local-20261106T002613476709Z-2d004f00` pass5/fail2、hard `[]`；唯一逐例变化为 RG006。
- commit：`p1/T105 anaphora field inheritance + no-field clarification`（sha 见交付回复）；3 改（query.py +100、answer.py +13/−1、regression.jsonl 1 行）+ 2 新测试 + 4 证据 + 本报告。

## 4. 偏离或未做

**接续说明**：前序 T105 开发 subagent 于 2026-11-06 04:19 前后失败、无收尾、未 commit；本轮保留其 query/answer 改动与 13 条测试（未重做），修正死代码 `is_anaphora_question`、纯指代词（前面/刚才/上述…）被当成新内容、以及“第 N 页”被误判为单字段追问三处问题，并新增 2 条测试；本轮补做 RG006 收口、前后对照、全量回归、证据/报告/commit。
- **RG006 口径**：local 单轮忽略 `turns`，等价无上文；修复前实际答 W11 正文（滨江店/QF01/店内外侧/40 张），故 forbidden 加强为这 4 项而非规格/价格值；多轮完整复现依赖 T109，本包由 HTTP 多轮用例证明（证据 04 §A）。
- **answer.py 改动理由**：`enumerate` 是 `_rag_owns_turn` 的既有路由入口；不改 conversations 的前提下，只能在答案层把它还原为单字段渲染（证据 04 §B）。
- **§6.5 “RG001–RG005 仍 PASS” 的落点**：RG005 是 T104 已登记的残余失败（营收词表未收口），本包未触碰；实际口径为 RG001–RG004/RG006 pass、RG005/RG007 失败集与基线逐项相同，未新增失败。
- 未改 `conversations/`、`intent.py`、b0/badcase、gate 配置、其他包文件；未切分支/push/amend；未读 `.env`/Holdout。

## 5. 风险

- 纯指代判定仍是词面启发式：`ANAPHORA_WORDS` 之外的“上面那个呢”等说法不在覆盖内；带新内容的指代追问继续走既有正文/legacy 路径（不抢正文），个别措辞可能仍答非所问但不会再整条倾倒。

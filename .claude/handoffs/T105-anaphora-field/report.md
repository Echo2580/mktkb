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

（以下为 `2306aaa` 交付树实测；R1 返工树见 §6）

- 本包：15 passed（17.97s）；rag 335（45.05s）；observability 255（37.95s）；integration 368（401.50s）；全量 1693（最终树 437.48s，运行前 `FreePhysicalMemory=5.10 GB`，无需轮询等待）。
- 本轮无既有 flake 复现（`test_g08_short_budget_cancels_inflight_model_call` 在 integration/全量均通过）。
- b0：`b0-local-20261105T090359232489Z-6e3eb84c` pass29/fail3/skipped8 → `b0-local-20261106T002138228442Z-e4560569` **同数同例**，gate exit 3、hard `[]`，`case_diffs=0`。
- badcase：`badcase-local-20261105T090409960294Z-f03d4b5f` pass9/fail4 → `badcase-local-20261106T002142276281Z-7a9b4bd5` **同数同例**，gate exit 3、hard `[]`，`case_diffs=0`。
- regression：基线 `regression-local-20261106T001846178302Z-e584b08e` pass4/fail3、hard `['security_leak']` → 收口后 `regression-local-20261106T002613476709Z-2d004f00` pass5/fail2、hard `[]`；唯一逐例变化为 RG006。
- commit：`p1/T105 anaphora field inheritance + no-field clarification`（sha 见交付回复）；3 改（query.py +100、answer.py +13/−1、regression.jsonl 1 行）+ 2 新测试 + 4 证据 + 本报告。

## 4. 偏离或未做

**接续说明**：前序 T105 开发 subagent 于 2026-11-06 04:19 前后失败、无收尾、未 commit；本轮保留其 query/answer 改动与 13 条测试（未重做），修正死代码 `is_anaphora_question`、纯指代词（前面/刚才/上述…）被当成新内容、以及“第 N 页”被误判为单字段追问三处问题，并新增 2 条测试；本轮补做 RG006 收口、前后对照、全量回归、证据/报告/commit。
- **RG006 口径**：local 单轮忽略 `turns`，等价无上文；修复前实际答 W11 正文（滨江店/QF01/店内外侧/40 张），故 forbidden 加强为这 4 项而非规格/价格值；多轮完整复现依赖 T109，本包由 HTTP 多轮用例证明（证据 04 §A）。
- **answer.py 改动理由**：`enumerate` 是 `_rag_owns_turn` 的既有路由入口；不改 conversations 的前提下，只能在答案层把它还原为单字段渲染（证据 04 §B）。R1 另在 `_answer_record` 入口（`answer.py:230-238`）对 `reason=ANAPHORA_NEW_CONTENT` 提前 `_no_answer`，理由/收窄见 §6。
- **§6.5 “RG001–RG005 仍 PASS” 的落点**：RG005 是 T104 已登记的残余失败（营收词表未收口），本包未触碰；实际口径为 RG001–RG004/RG006 pass、RG005/RG007 失败集与基线逐项相同，未新增失败。
- 未改 `conversations/`、`intent.py`、b0/badcase、gate 配置、其他包文件；未切分支/push/amend；未读 `.env`/Holdout。

## 5. 风险

- 纯指代判定仍是词面启发式：`ANAPHORA_WORDS` 之外的“上面那个呢”等说法不在覆盖内。
- **（R1 修正：上轮此处“不会再整条倾倒”不成立）** `2306aaa` 树实测带新内容的指代追问仍 8 条×8 字段（576 字）。R1 已改口径：非台账字段（打印材质/陈列要求）**不再走正文/legacy**，直接 `not_found`「资料中未记录这项信息…」（`reason=ANAPHORA_NEW_CONTENT`），不再倾倒；含记录字段追问按单字段作答。代价与 P2 残余见 §6。

## 6. R1 返工（B1 分页回退 / B2 新内容倾倒）

**接续说明**：本节代码（4 文件 +209/−4）与 §3 其余数字由暂停前 R1 开发上下文完成；本段由接续上下文补记，**未改代码**。树状态：未提交 diff 与暂停备份 `_scratch/T105/R1-wip-20261106-123035.patch` 内容一致（忽略行尾）；`git diff --binary`（4 文件、15026 B）sha256=`578e0747…f3f`，LF 归一后 `23aa6cf1…abba`；PM 记录的 `890eba3e…5c23` 是补丁文件本身（UTF-16LE+CRLF、25712 B）的哈希，不能由 `git diff` 复算。

**B1（枚举 → `那个海报的第2页`）**：修前 `clarification`「请问要查询宣传海报的哪项信息？…」、`pagination=null`（相对基线回退）；修后 `answer`、`pagination={page:2,page_size:10,total:12,returned:2,has_more:false}`、266 字（与基线 `17c0e63` 的 266 字/同分页一致）；无指代 `第2页` 仍 page=2。

**B2（上文 `城西店的宣传海报在哪里？`）**：

| 追问 | 修前（`2306aaa`/基线） | 修后 |
| --- | --- | --- |
| 那个海报的规格型号呢 | 576 字、8 条×8 字段（8 次“标识：”） | `answer` 29 字，仅 `A2 铜版纸 157g`，未问值 0 |
| 那个海报的打印材质呢 | 576 字、8×8 | `not_found` 35 字「资料中未记录这项信息…」，记录/字段 0、未问值 0、sources=[] |
| 那个海报的陈列要求呢 | 576 字、8×8 | 同上 |

**根因与最小改动**：
- B1：`query.py` 的 T105 指代分支先于分页，`_page_request`+`previous.enumerate` 已解析出的页码被 `ANAPHORA_NO_FIELD`（`query.py:1289-1322`）提前返回；修复=分支入口加 `not (page_request is not None and previous.enumerate)` 守卫（`:1274-1281`），分页优先。
- B2：带新内容时 `field_roles=()` → `enumerate=False`，产品层 `_rag_owns_turn` 落到 legacy 整条渲染；修复=`query.py` 新增 `ANAPHORA_NEW_CONTENT` 判定（`:1329-1352`：显式实体+新内容+非页码/非枚举/非法规）置 `enumerate=True` 并带 `reason`（`:1433`），`answer.py:230-238` 在 `_answer_record` 入口提前 `_no_answer`。未改 `conversations/`、`intent.py`、fixtures。
- 测试：4 单测 + 4 HTTP（B1 分页、B2 单字段/不倾倒），两文件共 23 passed。

**B2 收窄披露（PM 裁定 §5-1）**：非台账字段新内容直接给“未记录”提示，**不先走正文/legacy 检索**；相对基线是“不倾倒”而非误答。**P2 非阻塞残余**：若正文语料确含该内容（打印材质等），存在保守误判为“未记录”的风险，由 R2 探针按裁定 §5-3 证伪条件核验。~~窄口径观察项：新增 `elif`（显式实体+记录字段+指代）未显式排除“政策题+实体+字段词+指代”措辞，现有 T101/T102 定向 44 未覆盖该组合，记观察（不阻塞）。~~ **（R2 更正：该判断不成立。）** R2 独立探针实测“实体+指代+政策/法规”组合返回继承字段答案（C5 系列 27/29 字位置/规格）或把 C3/C6 压成 35 字 `not_found`，属 §5-2 扩大拦截；已在 §7 修复，不再列为“观察”。

**数字来源**：§3 的 rag 339/observability 255/integration 372/全量 1701、T101/T102 定向 44、b0/badcase `case_diffs=0`+gate hard `[]`、regression 仅 RG006 fail→pass，均为暂停前 R1 实测（本轮未重跑，不声称新结果）；本轮补跑：本包 2 文件 **23 passed**（7.28s）、验收方独立探针 `verify/T105/02-probe.py`（脚本未改）**70/70 checks**，B1/B2 修后数字即出自该次探针。

**commit**：`p1/T105 R1 fix anaphora pagination regression + new-content dump`（sha 见交付回复；7 文件）。

## 7. R2 返工（政策/法规指代拦截）

**根因（R1 `fc60c57`）**：`query.py:1336-1352` 的 `ANAPHORA_NEW_CONTENT` 只排除 `is_regulation_question`、未排 `is_policy_question`；`elif explicit_record_entity and is_anaphora_field_followup(...)` 政策/法规均未排。于是 C3/C6 进入“新内容→未记录”（35 字），C4 因书名号命中 doc_id 后按记录检索落到不实的“未找到记录”（42 字），C5 系列继承上一轮 `state.field_role`（location/spec）按单字段渲染（27/29 字），C7 记录存在但缺日期字段时误称“没有匹配记录”。

**最小改动**：

- `query.py`：新增 `is_policy_followup`（与 `is_policy_question` 同口径，仅排除同时是台账字段名的「要求/规则」，否则 B2 点名项「陈列要求」会被误判成政策题）；`ANAPHORA_NEW_CONTENT` 与继承单字段 `elif` 均加 `not policy_followup`；新增 `POLICY_FOLLOWUP` 分支：`指代 + 政策/法规 + 本轮显式实体 + 无自身字段角色` 时清继承 `field_role/field_roles`、保留实体、置 `enumerate` 并打 `reason`；`terms` 改用 `_anaphora_residual_terms`（去掉“那个海报的”这类指代实体词）。
- `answer.py`：`_policy_document_plan` 把该轮换回 document 计划（清实体过滤、保留问题显式点名的 `doc_id`、`query_text=question`），回答走既有 `_answer_document`；仅对 `POLICY_FOLLOWUP` 跳过标题句/换行截断半句；C7 在 `_answer_record` 末尾按 `lexical` 已过滤的记录块判定“记录存在、缺字段”，文案改为「资料中未记录日期（记录存在，但缺少该字段）。」。
- **为什么必须动 answer.py**：产品层 `_rag_owns_turn` 只把 record/enumerate 轮次交给内核；document 轮次走 legacy，而 legacy 从上一轮来源继承门店/物品（`intent.py` 禁改），会把 C3/C6 渲染成台账 8×8。`POLICY_FOLLOWUP` 用既有 `enumerate` 入口拿到内核，再在答案层换 document 计划，是未改 `conversations/`、`intent.py` 的最小路径。

**修复前后（同一 conversation；上文 `城西店的宣传海报在哪里？`，C5d 为上文问规格）**

| # | 追问 | 修前 `fc60c57` | 修后 |
| --- | --- | --- | --- |
| C3 | 那个海报的档期物料要提前多少天提报需求？ | not_found 35 | **answer 20 字**「档期物料须提前 21 天提报。」
| C4 | 那个海报的《明码标价和禁止价格欺诈规定》自何时起施行？ | not_found 42（不实“未找到记录”） | **answer 136 字**含 2022年7月1日 + 两项废止规定 |
| C5 | 那个海报的价格欺诈规定是什么？ | answer 27（继承位置） | **answer 58 字**第二十一条价格欺诈条文，0 位置 |
| C5b | 那个海报的相关规定是什么？ | answer 27（位置） | **answer 140 字**法规条文 |
| C5c | 那个海报适用的价格欺诈规定是什么？ | answer 27（位置） | **answer 156 字**第二条（价格欺诈定义） |
| C5d | 上文问规格 → 同上 C5 | answer 29（继承规格） | **answer 58 字**法规条文，0 规格 |
| C6 | 那个海报的审批流程是什么？ | not_found 35 | **answer 37 字**「审批流程：市场部通路行销组发起，门店店长确认。」 |
| C7 | 那个海报的盘点时间是什么？ | not_found 42（不实“没有匹配记录”） | **not_found 22 字**「资料中未记录日期（记录存在，但缺少该字段）。」 |

**必须保持项实测（独立探针 62/62 checks）**：B1 `那个海报的第2页` → `{page:2,total:12,returned:2,has_more:false}` 266 字；B2 规格 29 字仅规格、打印材质/陈列要求 not_found 35 字 0 泄露、位置/数量/价格 27/20/23 字、B2-after 27 字；单独 `档期物料要提前多少天提报需求？` 518 字含 21 天；单独 T101 法规题 861 字含 2022-07-01 + 废止规定；`那个流程要提前几天提报` 139 字；无上文 `那个海报呢` 仍澄清。

**运行数字（R2 实测）**：本包 2 文件 **40 passed**（16.10s）；`tests/rag` **347**（20.70s）；`integration` **381**（251.61s）；`observability` **255**（15.08s）；全量 `backend/tests` **1718 passed / 0 failed / 0 error**（362.18s，跑前 `FreePhysicalMemory=3.36GB`，无 flake 复跑）；T101/T102 窄集 **37**、全集 **44**。b0 `b0-local-20261106T175809006546Z-a24b4ba0` pass29/fail3/skipped8、gate exit 3 hard `[]`，与 `p0-b0` **case_diffs=0**；badcase `badcase-local-20261106T175816897525Z-a8597428` pass9/fail4、hard `[]`，**case_diffs=0**；regression 当前 `regression-local-20261106T175854995451Z-21fd0672` pass5/fail2 hard `[]`，基线 `17c0e63` `regression-local-20261106T180049159181Z-f33ada3a` pass4/fail3 hard `['security_leak']`，逐例**仅 RG006 fail→pass**，RG005/RG007 失败 checks 不变，无新 hard 名。

**残余 / 披露**：C3/C4/C5/C6 由内核 offline 抽取式正文作答，产品 `sources` 仍为空（`_rag_turn_result` 只从 `facts` 取来源，文档答案只有 citations）；未改 `conversations/`，故保留，属本包口径限制。回答比 legacy 的 C1/C2（518/861 字多条证据回显）短，是抽取式单段的既有行为。`is_policy_followup` 仍是词面启发式（排除「要求/规则」两类字段词），其它“字段名+政策词”同形说法未逐一覆盖。C7 已按 P2 收紧文案。未跑真实模型/live/Holdout。

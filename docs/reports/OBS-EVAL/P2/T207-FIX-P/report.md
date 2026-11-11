# P2-T207-FIX-P 开发报告：公开财务反例 4 项定点修复（零真实调用）

- 角色：T207-FIX-P 开发助手（全新上下文）；分支 codex/p2-e2e @ 9a740ce（未 commit/push）。
- 边界：真实调用 **0**（全 Mock / 离线，未读 .env/H1/H2，未联网）；未改 `fixtures/**`、`evaluation/**`、账本/预算/GO；
  未新增 skip/xfail；未改任何冻结期望/标签；只跑受影响用例，未跑全仓。
- 现场说明：工作树同时含并行包 **T207-FIX-B** 的 evaluation 层改动（本包未触碰）；本包两次 pytest 都在同一棵树上采集。

## 1. 结论

| 项 | 问题 | 改动前 | 改动后（本包） | 判定 |
|---|---|---|---|---|
| E-1 | E10 陈列达标率口径+年度目标 | fail(value_hit) | fail(value_hit)（产品回答未变） | **BLOCKED**（§4.1） |
| E-3 | E03 2026 Q4 档期特价 | fail(value_hit,value_no_fabricated) | 同左 | **BLOCKED**（§4.1） |
| E-2 | W03 8000 元由谁审批 | fail(value_forbidden,value_no_fabricated) | 同左 | **BLOCKED**（§4.2，与冻结标签冲突，已证伪） |
| E-4 | E03 咸味饼干 120g 批发价 | fail(kind_correct) | 同左 | **BLOCKED**（§4.3，标签自相矛盾） |
| 正向 | 结案报告 6 个自然日 | pass | pass | 不回退 |
| 正向 | 多轮追问 3 个工作日 | pass | pass | 不回退 |

**4 个诱饵的现行失败都不是 fix-scope §E 指的那段代码造成的**（§2）；本包只落地了其中**唯一被实测证明的产品缺陷**
（回答复述问题前提值被判 MODEL_OUTPUT_INVALID），并把其余 3 条按"先报冲突、不改期望"停住。

## 2. 根因（实测，与 fix-scope §E 不一致处已标注）

1. **这 4 题根本不走记录型分支。** 意图层实测（证据 02 §2）：F01–F05 全部 `mode=document`、
   `requested_fields=()`、`entities={}`（E10/E03 无 store/item 列 → 索引不产实体、词表为空）。
   因此 fix-scope 指向的 `service.py` 记录路径 **一行都不执行**：`_facts`(:626)、`_record_units`(:920)、
   `_record_statement_bodies`(:1062)、`_match_record_clause`(:1144)、`_record_answer_text`(:1378)
   都挂在 `if plan.mode == "record"`(:2274/:2309/:2326) 之下。
   ⇒ "给 `HEADER_ROLES` 加数值/日期角色 + 让被问角色原值回显"（§E.1）只改索引 `field_role`，**不改变分支**，跑不出差别。
2. **答案文本由 Mock 生成器决定，不是产品丢字段。** `MockChatBackend._answer_json` 只取**第一条证据的前 3 个字段**
   （`product_adapter.py:530-533`），无字段时回**首条证据正文**（:535）。E10 row103 字段顺序
   `[月份,指标,计算口径,目标,实际,…]`、E03 NKA row7 `[价格单号,SKU编码,品名规格,适用渠道,适用区域,价格类型,价格(元),…]`，
   产品回答恰好是前 3 个 ⇒ "缺 90% / 缺 2.99" 与产品字段处理无关；F02 的"其他分档审批人"、F04 的"别家 SKU"
   同样是 Mock 对首条证据的固定回显，产品只是把模型文本过闸。
   ⚠️ 该文件属 `evaluation/**`（**本包禁改**，另有包在改 evaluation 层）。
3. **唯一可证明的产品缺陷（已修）**：把"正确回答"直接喂给产品，F02/F03/F04 被 `_validate_answer` 判
   `MODEL_OUTPUT_INVALID：回答包含引用来源中不存在的数据值`（证据 02 §3）——被拒的 token 正是**问题自己给的前提值**
   （`8000`/`2026`/`q4`/`120g`）。资料只给结论、不可能出现用户前提值，于是"照实回答"整轮作废（F01 不受影响）。
   这解释了为什么真实模型在这类价目/指标/审批题上只会拿到 service_error。

## 3. 改动（文件 / 行数 / sha256 前 16）

| 状态 | 文件 | 行数 | sha256(16) | 说明 |
|---|---|---|---|---|
| 修改 | `backend/src/mktkb/conversations/service.py` | 2408（+11/−1） | `e9272b62492bafaf` | `_validate_answer`(:796) 增 `question=""` 形参；已背书 token 集合 = 引用来源 ∪ **问题原文**（:837）；正文型调用点传 `question`（:2323）。记录型调用不带该参数 → 旧口径逐字不变。 |
| 新增 | `backend/tests/unit/test_p2_t207_fix_p.py` | 82 | `d5ccc109e05b9e2a` | 4 条：前提值放行 / 双方都没有的值仍拒 / 未引用行取值仍拒 / 不传问题时旧口径不变 |
| 未改 | `retrieval/index.py`、`conversations/intent.py` | — | — | 实测无必要（§2.1），按"最小改动"不动 |

## 4. 逐条判定与阻断理由（需经理决策）

**4.1 E-1 / E-3 —— BLOCKED（根因在禁改文件）**
要让产品在**模型没说出** 90%/2.99 时仍判 pass，只有两条路：① Mock 对"被问列"作答（`evaluation/**`，禁改）；
② 产品跳过"模型陈述→产品校验"的既有不变式，自己从表格行**合成**答案文本（新"表格列答案"路径，非最小定点，
且与 `_record_answer_text` 的前提——已验证字段来自模型陈述——冲突）。已实测：模型一旦答对，F01/F03 现在就能 pass
（证据 02 §3b：F01/F02/F03 均 `kind=answer` + `pass`）；F03 另要求答案**不得**带 `品名规格`/`价格单号` 里的数字
（F03 金标数字只有 `2026/4/500/10/28/2.99`），这是标签口径问题，不是产品行为。

**4.2 E-2 —— BLOCKED（fix-scope 方向 3 与冻结标签冲突，已证伪）**
按 §E 方向 3 只保留命中分档子句（`5000 元至 20000 元由市场部经理审批`），实测仍 **fail(value_no_fabricated)**：
`5000/20000` 不在 F02 金标数字集合 `{2026,10,28,8000}` 里（证据 02 §4）。能过的只有"只答审批人"或
"合成句只带 8000"，两者都要产品**改写/新造句子**（现有产品只回原值或模型文本）。要保留方向 3，需经理决定是否给 F02
补 `reference_answer`（含该分档），否则该条无法在"不改期望"前提下转绿。

**4.3 E-4 —— BLOCKED（冻结标签自相矛盾，任何产品行为都不可能通过）**
F04 的 CaseSpec 是 `expected_kind="not_found"` 且 `should_refuse=False`（默认）。`not_found` 属拒答
⇒ `refusal_unexpected` fail；改成 `answer` ⇒ `kind_correct` fail（证据 02 §4 两种结局都跑过）。
须经理决策：给标签补 `should_refuse=True`+`refusal_reason`，或改期望。"问题含未收录商品名即 not_found"的判据
本包**未实现**——它需要商品名词表/名称识别（`品名规格` 未登记角色、E03 也无 store/item 实体），属设计项不是定点修复。

**4.4 测试加固 —— NOT APPLIED（依赖上面 3 条）**
4 诱饵在当前 Mock 回答下仍 fail，把 `test_p2_public_controls.py` 的"产品答错→判 fail"分支改成"必须 pass"必然红。
故保留原分支（继续暴露失败），未改 fixtures/期望/标签、未加 skip/xfail。新增的只有 §3 的 4 条单元测试。

## 5. 回归（全部 exit 0，证据 03）

- 受影响 9 文件：改动前 **210 passed** → 改动后 **210 passed**（含 `test_p2_public_controls.py`、
  `test_p2_scoring.py`、`test_p2_gate.py`、`test_chat.py`、`test_s2e_fact_gate_http.py`、
  `test_t09_d4`、`test_t09_d6_r1`、`test_t09_security.py`、`test_conversations.py`）。
- `test_p0_acceptance.py`（local 有界对照）**7 passed**；`test_t09_mutation.py`（U 本地控制）**13 passed**。
- 新增单元测试 **4 passed**；`test_p2_public_controls.py` 单独复跑 **6 passed**（2 正向 pass）。
- `probe_t205.py` 复跑：`outbound_network=0`、`rag_provider_attempts=0`、chat 5 次全为 MockTransport；
  改动前后输出 JSON 主体**逐字一致**（164 行 diff 为空，仅证据文件头不同）。

## 6. 偏差 / 未决 / 回退

1. 未达成任务书的"4 诱饵必须 pass"：3 条为根因错位/标签冲突（§4），1 条（E-1/E-3）需在禁改文件或设计层面解决。
2. 新口径把"用户问题里的值"也算已背书：这是**有意放宽**（只对正文型回答生效），风险是模型可把问题里的数字
   错误挂到别的字段——但问题不因此为字段关系背书（记录型路径不带该参数，仍逐值原样核对）。
3. 未做：全仓测试、真实模型/OCR/embedding/rerank、gate/H2、浏览器；工作树含并行包改动，非独占环境。
4. 回退：`git checkout -- backend/src/mktkb/conversations/service.py` 并删除 `backend/tests/unit/test_p2_t207_fix_p.py`（未 commit）。
5. 建议下一步（按性价比）：① Mock 改为按问题里的被问列作答（`product_adapter._answer_json`，约 5 行，禁改文件需另派）；
   ② F02 补 `reference_answer`（含命中分档）或接受"只答审批人"；③ F04 标签补 `should_refuse=True`+`refusal_reason`。

## 7. 证据入口（4）

1. `evidence/01-reproduction-before.txt`：改动前 4+2 复现（产品回答/来源/判定/失败 check，出站 0）。
2. `evidence/02-root-cause.txt`：意图层 mode=document、行字段顺序（Mock 截断证明）、事实准入旧/新口径、
   端到端"正确回答"判定、冻结标签可行性、零真实调用计数。
3. `evidence/03-pytest.txt`：Baseline / 改动后 9 文件 / p0 / t09 mutation / 新单元测试 汇总。
4. `evidence/04-probe-after.txt`：修复后 probe 复跑（与 01 逐字一致）+ 零真实调用计数。

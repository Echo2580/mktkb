# T102 交接单：组 A 状态继承（ERR-01/ERR-02/D5，P1 第 4 包 · 最高风险）

> 基线：分支 `p1/fix-retrieval`（自 `main@083eaef`；T100/T107/T101 已收口）。本包改 `rag/query.py` 高耦合逻辑，回归风险最高，**单包单 commit、前后行为对照必须留证**。
> 执行者：开发 subagent（`wb / cn:deepseek-v4.1-flash`，`reasoning_effort=max`）。PM 不写代码。

## 1. 目标（一句话）
修组 A 状态继承：未识别的门店/区域词（如「城西区」）必须**澄清或拒答**，不得静默沿用上一轮门店；政策/制度题不继承上一轮实体、不得回显用户未提及实体；`reset` 判定补"话题切换"。

## 2. 背景（ERR-01/ERR-02，依据 `错误记录-20261104.md` §二）
- **ERR-01**：先问「城东店的宣传海报在哪里」→ 正确；再问「城西区的宣传海报在哪」→ 返回**城东店**答案（B区1号货架第二层），无澄清/拒答。语料中城西店海报实际在 **C区2号货架第一层**（D01 表 P01/P02）。根因：`城西区` 不含 `城西店`、不以「店」结尾 → 门店槽空、未知门店 token 不识别 → `_carry_state` 原样继承上轮 `store=城东店`（旧 `query.py:640-654`、reset 判定旧 `:806-815`、子串匹配旧 `:432-434`）。
- **ERR-02**：先问「卓刀河店的马克杯（标识：QF21）放在哪里？」→ 再问「档期物料要提前多少天提报需求？给出所有内容」→ 返回"未在资料中找到「卓刀河店」的「马克杯」记录"，而正确答是 **W02 第七条：档期物料须提前 21 天提报**（E078）。根因：无实体问题 slots 全空、不含 SWITCH_WORDS → 不 reset → 继承上轮 store/item；「所有内容」命中 `ENUMERATE_WORDS` → 枚举计划 + 旧实体 → `_no_record_text()` 把 `plan.state.stores` 与 `filters["item"]` 打印出来。
- **PM 口径（本包采纳）**：① 「城西区」这类未知区域/门店形态词 → **澄清**（不要求做区域→门店展开；设计 §3 允许"答 C区或澄清"，澄清更安全）；② 政策/制度/流程题（无显式实体、无记录字段）→ **不继承**上轮 store/item，按文档问题独立检索；③ 不得在答案里回显"用户本轮未提及"的实体。

## 3. 输入（先读这些）
1. `.claude\handoffs\2026-11-04-p1-design.md` §3（T102 行）与任务拆解 T102 段。
2. `错误记录-20261104.md` §ERR-20261104-01（:38-80）、§ERR-20261104-02（:82-129）。
3. `backend/src/mktkb/rag/query.py`：当前行号（T101 后可能偏移，函数名定位）：`ENUMERATE_WORDS`(:72)、`SWITCH_WORDS`(:89)、`_match_stores`(:492)、`_unknown_store_tokens`(:518)、`_match_store`(:574)、`parse_query`(:804)、未知门店处理(:818)、reset 判定(:871-880)。重点读 `_unknown_store_tokens` 与 `parse_query` 的状态继承/重置全链路。
4. `backend/src/mktkb/rag/answer.py`：`_no_record_text`（错误记录称旧 :273-282，自查定位）与 `_document_fallback` 周边；理解"回显 state 实体"路径。
5. 既有测试（理解口径，不得削弱）：`backend/tests/rag/test_query_state.py:52`（topic switch 清实体）、`backend/tests/integration/test_s2b_intent_semantics.py`（b_fixture 多轮：bare store followup / item switch 等）、`backend/tests/integration/test_chat.py:440`（g04 上下文追问）。
6. `fixtures/evaluation/regression.jsonl` RG002/RG003（本包要按 §5 收口口径更新并让其 local 可达则 PASS；多轮完整复现依赖 T109）。

## 4. 交付物（只准写这些路径）
1. `backend/src/mktkb/rag/query.py`（主改）。
2. `backend/src/mktkb/rag/answer.py`（**仅必要**：避免 `_no_record_text` 等回显本轮未提及的继承实体；改动须最小并在 report §4 单列理由/净增行数）。
3. `backend/tests/` 本包测试（建议 `backend/tests/rag/test_p1_t102_state_inheritance.py` + 必要的 integration 多轮用例）。
4. `fixtures/evaluation/regression.jsonl`：按 §5 更新 RG002/RG003 口径（`expected_kind`/`expected_values` 按 PM 口径；`notes` 记录依赖 T109），**禁止动 RG001/RG004–RG007**；可追加 T102 新种子。
5. `docs/reports/OBS-EVAL/P1/evidence/T102/`（≤4 份证据）
6. `.claude/handoffs/T102-state-inheritance/report.md`（五段，≤80 行）
7. 1 个 commit（见 §7）
**不要写**：`conversations/` 层（intent/service）、b0/badcase、gate 配置、观察层、其他包文件、`.claude/handoffs` 其他文件。

## 5. regression.jsonl 口径（本包必须收口）
- **RG002**（ERR-01）：把 `expected_kind` 从 `answer` 更新为 **`clarification`**（未知区域词澄清口径），`expected_values` 可清空或保留兼容；`notes` 写明"多轮完整复现依赖 T109；本包以集成多轮用例证明不再答城东店"。**不得**把 `forbidden_values`（城东店/B区）删掉。
- **RG003**（ERR-02）：保持 `expected_kind=answer`、`expected_values=["21 天"]`、`forbidden_values=["卓刀河店","马克杯"]`；多轮复现依赖 T109，本包以集成多轮用例证明 policy 题不继承实体、答案含 21 天且不含旧实体。
- 更新只允许这两条 + 可选追加；每条改动在 report 说明理由（口径变化，不是放宽）。

## 6. 验收标准（逐条可判定）
1. **ERR-01 不再串店**：集成多轮用例（先「城东店的宣传海报在哪里」→ 再「城西区的宣传海报在哪」）断言答案**不得**为城东店/B区1号货架；实际为澄清（或若实现区域展开则 C区2号货架第一层）。
2. **ERR-02 政策题不继承**：集成多轮用例（先「卓刀河店的马克杯（标识：QF21）放在哪里」→ 再「档期物料要提前多少天提报需求？给出所有内容」）断言答案含 **21 天**、且**不含**「卓刀河店」「马克杯」。
3. **误伤防护（多轮 follow-up 不退步）**：既有 `test_s2b_intent_semantics.py`、`test_query_state.py`、`test_chat.py:440` 全部保持通过（裸门店追问、换物品、话题切换清实体行为不变）。
4. **P0 trace 不破坏**：`backend/tests/observability` 全绿 + b0/badcase local run 的 trace path/outcome 与修复前一致（b0 pass29/fail3/skipped8、badcase pass9/fail4、gate hard_failures 均为 `[]`，case 级逐例对照零变化；证据须有前后对照表）。
5. **regression**：RG002 按新口径在 local PASS（若 local 单轮不可达则如实记录依赖 T109 并在证据单列）；RG003 若 local 可达需 PASS；其余 6 条状态不得变（RG001 必须仍 PASS）。
6. **回归与预算**：本包测试 + `backend/tests/rag` + `backend/tests/integration` + 全量 `backend/tests`（§11A：各 1 次；当前空闲内存 1.74GB，跑全量前轮询等待 ≥2GB（每 30s，最长 15 分钟），仍不足才 NOT-RUN 并如实记录；既有 flake 按记录隔离复跑 1 次）。
7. 证据 ≤4 份、report 五段、1 commit、只改允许文件、无 skip/xfail/删断言/放宽。

## 7. 提交要求
- 分支 `p1/fix-retrieval`；**1 个 commit**，消息：`p1/T102 state inheritance + topic-switch reset`；不 push/不 amend 历史。
- 提交前 `git status --short` 只含允许路径；report 记录 commit 信息（sha 写交付回复即可）。

## 8. 报告格式（五段，≤80 行）
1) 完成内容；2) 验收标准自证（每条 ≤2 行，带命令/`文件:行`）；3) 实际运行结果（本包/rag/integration/全量 + b0/badcase/regression 前后对照 + commit sha + stat）；4) 偏离或未做（含 RG002 口径变化理由、answer.py 改动理由）；5) 风险（一句话）。

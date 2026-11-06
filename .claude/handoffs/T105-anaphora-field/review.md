wb / cn:deepseek-v4.1-flash / reasoning_effort=max

# T105 独立验收 review（重派 R1，ERR-06）

**结论：FAIL（2 个阻断项）**。核心三类语境已修复，但独立 HTTP 探针发现：①「枚举后 那个海报的第2页」被 T105 指代分支劫持、丢失分页（相对 `17c0e63` 的回退）；②带新内容的指代追问（打印材质/陈列要求/规格型号）在无标识上下文仍返回 8 条记录 × 全部 8 字段（基线已有、未收口，report §5“不会再整条倾倒”不成立）。详见 `docs/reports/OBS-EVAL/P1/evidence/verify/T105/01-verdict.md`。

## 基线与工作树

- `git status --short` 起始为空；分支 `p1/fix-retrieval`；HEAD `838fa54`。
- `git diff 2306aaa..HEAD -- backend fixtures` 为空；`e7ec430`/`bf74317`/`838fa54` 3 个 PM commit 均只动 `.claude/handoffs/**`（实际 3 个，非提示词所称 2 个）。
- `git show --stat 2306aaa`：10 文件，均在 handoff §4 允许路径；无第二开发 commit。

## 逐条复跑

1. **本包 2 文件：PASS（15 passed，5.14s）**。命令：`python -B -m pytest backend/tests/rag/test_p1_t105_anaphora_field.py backend/tests/integration/test_p1_t105_anaphora_field.py -q -p no:cacheprovider --basetemp backend\.pytest-tmp\T105-verify\pkg`。首次因 basetemp 父目录不存在在 setup 报错，创建父目录后重跑；失败调用未执行任何 test。9 单测+6 HTTP=15，与交付树一致。
2. **rag/observability/integration/全量：PASS（带 1 条披露）**。rag 335 passed（21.44s）；observability 255 passed（15.96s）；全量 1693 passed / 0 failed / 0 error（386.79s；跑前 FreePhysicalMemory=3.02GB）；integration 368 collected，单次 367 passed + 1 failed，失败为既有 flake `test_chat.py::test_g08_short_budget_cancels_inflight_model_call`（`len(facts["calls"])==0`），隔离复跑 1 passed/1.42s → 判 flake。report 称单次 368 passed，本次未复现该单次结果。
3. **b0/badcase：PASS**。b0 `b0-local-20261106T033419849337Z-3a060139` pass29/fail3/skipped8、gate exit 3 hard `[]`；badcase `badcase-local-20261106T033427613198Z-3ad632e2` pass9/fail4、exit 3 hard `[]`；与 `var/eval/runs/p0-b0`、`p0-badcase` 逐例 `(case_id,status,outcome.kind,failed checks)` **case_diffs=0**。未写 `p0-*`。
4. **regression：PASS**。当前 `regression-local-20261106T033502219410Z-adf7dc02` pass5/fail2、gate exit 3 hard `[]`；基线 `17c0e63`（detached worktree + `PYTHONPATH=<wt>\backend\src`，已打印 `mktkb.__file__` 指向基线副本）`regression-local-20261106T033638499288Z-4824c8be` pass4/fail3、exit 1 hard `['security_leak']`。逐例仅 RG006 fail→pass，RG001-004 pass 不变，RG005/RG007 失败 checks 不变（`kind_correct,refusal_expected`），gate 无新增 hard 名。RG006：基线 `answer` 文本含 4 个未问值（店内外侧/40 张/QF01/滨江店），当前 `clarification` 0 泄露；fixture forbidden 恰覆盖这 4 个值，非只测文案。
5. **HTTP 产品路径独立探针：FAIL**（`02-probe.py`，真实 HTTP + 可控 EchoGateway，12 行×8 列夹具；64/70 checks，6 failed）。逐场景见 03：
   - **PASS**：上文问位置→只答位置（27 字，无规格/价格/数量/标识/分页）；数量/价格/规格→只答该字段；无上文→`clarification`（无字段值）；无实体→`clarification`；`刚才那个呢`/`前面那个呢`/`这个呢`/`那家呢`→只答继承位置（基线多为 not_found/service_error）；显式「列出来」「全部」保留分页。
   - **B1 FAIL**：`把宣传海报都列出来`→`那个海报的第2页` 返回 `clarification`（`请问要查询宣传海报的哪项信息？…`，无分页）；基线同一操作返回 `page=2`（`共 12 条，当前第 2 页显示 2 条`）。单独问 `第2页` 当前仍正确 page 2 → 仅「指代+第N页」回退。根因：`backend/src/mktkb/rag/query.py:1272-1318` 的 T105 分支先于分页处理；`_PAGE_NUMBER` 守卫在 `query.py:334`/`answer.py:230`，但 query 层 `:1297-1314` 已提前澄清，守卫不可达。两个 T105 测试文件无任何「第2页/第N页」用例。
   - **B2 FAIL**：上文 `城西店的宣传海报在哪里？`→`那个海报的打印材质呢`/`那个海报的陈列要求呢`/`那个海报的规格型号呢` 均为 `answer` 576 字、8 条记录 × 8 字段（8 次“标识：”，含未问的 QF02/位置/数量/价格/规格），与基线一致；上一轮带标识时同一追问只答规格（29 字，pass）。根因：`backend/src/mktkb/conversations/service.py:1829-1852` 的 `_rag_owns_turn` 只在 identifier/enumerate+filters/pending/ambiguous 时交给 RAG，带新内容时 `enumerate=False` 落 legacy 整条渲染。
6. **T101/T102：PASS**。定向 37 passed（`test_p1_t101_vocab_context.py`、rag+integration `test_p1_t102_state_inheritance.py`、`test_query_state.py`、`test_s2b_intent_semantics.py`，13.20s）；全量 1693 含上述文件全绿。
7. **接续/合规：PASS（除 §10 修正 3 行为未达）**。`fixtures/evaluation/regression.jsonl` 仅 RG006 一行；无 skip/xfail/删断言；report 42 行五段、`report.md:1` 模型标注；证据恰 4 份；`is_anaphora_question` 全仓无命中（修正 1 成立）；纯指代词过滤实测成立（修正 2）；修正 3 见 B1（不成立）。13→15：交付树 15（9+6）可核，“13”仅见 PM 记录/evidence 01，git 不可独立复核。PM 3 commit 仅 handoffs；未改交付物/未 commit/push/切分支；未读 `.env`/Holdout；零真实模型/embedding/rerank/OCR。

## 与 report 声明差异

- report §4/§10：“修正‘第 N 页’被误判为单字段追问”→ 代码守卫存在但产品路径仍被 query 层澄清劫持，且相对基线是**回退**；report §2/evidence 02 的“第 N 页保持枚举/分页”未被测试或探针覆盖。
- report §5：“带新内容的指代追问…不会再整条倾倒”→ 实测 8 条×8 字段整条倾倒（基线已有；report 风险声明不成立）。
- report §3：“integration 368 passed”→ 本次单次为 367 passed + 1 个既有 flake；隔离复跑通过。
- report §6 全量 1693、b0/badcase 0 差异、RG006 fail→pass、gate hard `[]`：**复现一致**。

## 残余与返工建议

- B1：在 T105 分支入口先尊重 `_page_request`/`previous.enumerate`（分页判定前置），并补 unit+HTTP「枚举后 那个海报的第2页」用例；同时把 `第N页` 纳入 §10 修正 3 的验收。
- B2：带新内容（即使含已知字段）的指代追问应路由 RAG 按字段作答，或 legacy 渲染前限制字段/记录数；若不纳入本包，report 必须如实披露“仍会整条倾倒”，不能声称不会。
- S9 `那个海报的全部信息` 当前仅列继承字段（位置）且保留分页；与基线一致，未计阻断，但语义待后续确认。
- 未覆盖：真实模型/live、Holdout/.env（按边界禁用）；T109 多轮 runner（用本包 HTTP 多轮替代）。

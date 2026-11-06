# T105 独立验收结论（verify/T105/01）

- 验收对象：`p1/fix-retrieval` @ `2306aaa`（工作树 clean；HEAD `838fa54`，其后 3 个 PM 簿记 commit 仅动 `.claude/handoffs/**`；`git diff 2306aaa..HEAD -- backend fixtures` 为空）。
- 结论：**FAIL**。核心三类语境（无上文澄清、上文问位置/数量/价格/规格→只答该字段）已修好，但独立 HTTP 探针发现 2 个阻断项；其中 B1 是相对 T105 前基线（`17c0e63`）的**行为回退**。
- 证据：本目录 02-probe.py（独立探针，未复用开发测试）、03-probe-results.md（逐场景结果/基线对照）、04-test-eval-runs.md（测试/评测复跑与合规核查）。

## 阻断项

### B1（高）「那个海报的第2页」被指代分支劫持，枚举分页丢失（T105 引入的回退）

- 复现（同一 conversation）：`把宣传海报都列出来`（12 条，page 1，next_page=2）→ `那个海报的第2页`。
- 当前树：`kind=clarification`，文本 `请问要查询宣传海报的哪项信息？可指定位置、数量、规格、价格等。`，`pagination=null`。
- 基线 `17c0e63`：`kind=answer`，`pagination={page:2,total:12,returned:2,...}`，文本 `共 12 条，当前第 2 页显示 2 条...`。
- 对照：同一枚举上下文下单独问 `第2页`（无指代词）当前仍正确返回 page 2 → 失败仅发生在「指代 + 第 N 页」。
- 根因：`parse_query` 的 T105 分支在 `backend/src/mktkb/rag/query.py:1272-1318` 先于分页/枚举处理；`_anaphora_residual_terms` 把“第2页”的低长 token 滤空后，`inherited_roles` 为空 → 在 `:1297-1314` 直接返回 `ANAPHORA_NO_FIELD`。`is_anaphora_field_followup` 的 `_PAGE_NUMBER` 守卫（`query.py:334`、`answer.py:230`）在 query 层就已不可达。
- 测试缺口：两个 T105 测试文件均无“第 2 页/第 N 页”用例（`grep` 无命中），故 §10 修正 3 未被测试锁定。
- 影响：§10 声称已修“第 N 页误判”；实际产品路径回退了 T105 前行为，违反重派提示词第 4 项（显式“第N页”保持枚举分页）。

### B2（中高）带新内容的指代追问仍整条倾倒（未收口；report 风险声明不成立）

- 复现（上文 `城西店的宣传海报在哪里？`，同一 conversation）：
  - `那个海报的打印材质呢` → `kind=answer`，文本 576 字，含 **8 条记录 × 全部 8 个字段**（标识/门店/物品/别名/位置/数量/参考供价/规格型号），出现 8 次“标识：”，含 QF02/城西店/C区2号货架第一层/20/2.6/A2 铜版纸 157g 等未问值。
  - `那个海报的陈列要求呢`、`那个海报的规格型号呢` 同样 8 条全字段。
  - 基线 `17c0e63` 同样 576 字/8 条 → **不是 T105 引入**，但 T105 的 §6.1“任何路径不得整条渲染”与 report §5“不会再整条倾倒”均未成立。
- 范围定位：上一轮带标识（`（标识：QF02）`）时同一追问只答规格（29 字，pass）；倾倒仅发生在无标识、`_rag_owns_turn` 返回 False 的 legacy 路径（`backend/src/mktkb/conversations/service.py:1829-1852`：仅 identifier / enumerate+filters / pending / ambiguous 路由给 RAG）。T105 只在纯指代（`enumerate=True`）路径上修复，带新内容时 `enumerate=False`，落到 legacy 渲染整条记录。
- 影响：违反重派提示词第 6 项 ⑤“带新内容追问不得整条倾倒，也不得过澄清”；也影响 §6.1 的“任何路径”口径。

## 逐条判定（handoff §6）

1. 不倾倒全字段：**部分 PASS**。字面 `那个海报呢`（无上文/有上文）当前均为澄清或单字段；但“带新内容”的指代追问仍倾倒 → 按“任何路径”口径 FAIL（B2）。
2. 有上文问位置→只答位置：**PASS**。S1b 文本 `根据资料，城西店的宣传海报的位置：C区2号货架第一层。`；无规格/价格/数量/标识，无分页。
3. 价格/规格/数量→只答该字段：**PASS**（S2b/S3b/S4b，均 27-29 字、未问值 0）。指代无源→澄清：**PASS**（S5 `ANAPHORA_NO_FIELD` 无字段值；S12 `ANAPHORA_NO_ENTITY`）。
4. 不误伤 T101/T102：**PASS**。定向 37 passed（`test_p1_t101_vocab_context.py`、rag+integration `test_p1_t102_state_inheritance.py`、`test_query_state.py`、`test_s2b_intent_semantics.py`）；全量 1693 passed。
5. regression：**PASS**。仅 RG006 `fail/answer/(kind_correct,value_forbidden)` → `pass/clarification/()`；RG001-004 pass，RG005/RG007 失败 checks 与基线逐项相同（`kind_correct,refusal_expected`）；gate hard `['security_leak']` → `[]`，无新增 hard 名称。
6. 回归：**PASS（带一条披露）**。本包 15、rag 335、observability 255、全量 1693 passed；integration 单次 367 pass + 1 个既有 flake（`test_g08_short_budget_cancels_inflight_model_call`），隔离复跑 1 passed。b0/badcase 与 P0 逐例 `case_diffs=0`（29/3/8、9/4），gate exit 3 hard `[]`。
7. 合规：**PASS（除 §10 修正 3 行为未达）**。`2306aaa` 仅 10 个允许路径；RG006 仅该行；无 skip/xfail/删断言；report 42 行五段、证据 4 份；死代码 `is_anaphora_question` 已无；纯指代词（刚才/前面）已修；单开发 commit；3 个 PM commit 仅 `.claude/handoffs/**`。13→15 中“13”仅见 PM 记录/证据 01，git 不可独立复核；交付树 15 条（9+6）可核。

## 残余

- B1 修复方向：在 T105 分支入口先尊重 `_page_request`/`previous.enumerate`（或把分页判定前置），并补“枚举后那个海报的第2页”用例（unit + HTTP）。
- B2 修复方向：带新内容的指代追问要么路由给 RAG 按单字段作答，要么在 legacy 渲染前限制字段；至少不得把未问字段/多条记录整条输出。该行为在基线已存在，若不纳入本包，应在 report/风险中明确披露“仍会整条倾倒”而非声称不会。
- S9 `那个海报的全部信息` 当前只列继承字段（位置）并保留分页；与基线一致，未计入阻断，但“全部信息仅答位置”语义仍待后续包确认。
- 验收未覆盖：真实模型/embedding/rerank/OCR（按边界禁用）；Holdout/.env 未读。

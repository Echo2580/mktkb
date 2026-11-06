# T105 返工单 R1（PM，2026-11-06 12:0x）

> 依据：独立验收 `review.md`（**FAIL，2 阻断**）+ `docs/reports/OBS-EVAL/P1/evidence/verify/T105/`（01-verdict/02-probe/03-probe-results/04-test-eval-runs）。轮次 **R1/3**。
> 上一轮交付 `2306aaa` 保留，**不 amend 历史**；本轮为 1 个新 commit（`2306aaa` 之后、PM 已有簿记 commit 之上）。
> 执行者：开发 subagent（`wb / cn:deepseek-v4.1-flash`，`reasoning_effort=max`）。PM 不写代码。

## 1. 未过条款与期望（必须全部修好）

### B1（高，T105 引入的行为回退）——必须修
- 复现（同一 conversation）：`把宣传海报都列出来`（12 条，page1）→ `那个海报的第2页`。
- 当前：`clarification`「请问要查询宣传海报的哪项信息？…」，`pagination=null`（错误）。
- 期望（对齐 T105 前基线 `17c0e63`）：`answer` + `pagination={page:2,total:12,returned:2,has_more:false}`，文本「共 12 条，当前第 2 页显示 2 条…」；显式「列出来/全部/第 N 页」保持枚举分页，不被指代澄清分支劫持；单独 `第2页`（无指代）行为不变。
- 根因线索（验收方定位，须自行复核）：`backend/src/mktkb/rag/query.py:1272-1318` 的 T105 分支先于分页处理；`_PAGE_NUMBER` 守卫（`query.py:334`/`answer.py:230`）在产品路径不可达（query 层 `:1297-1314` 已提前澄清）。
- 要求：调整 query 层分页/枚举判定顺序使守卫生效；补 **unit + HTTP**「枚举后 → 那个海报的第2页」用例（含 `pagination.page==2` 断言）。

### B2（中高，基线已有但违反验收口径）——必须收口
- 复现（上文 `城西店的宣传海报在哪里？`，同一 conversation）：
  - `那个海报的打印材质呢` / `那个海报的陈列要求呢` / `那个海报的规格型号呢`。
- 当前：`answer` 576 字，**8 条记录 × 8 字段整条倾倒**（含未问的标识/门店/位置/数量/价格/规格）。基线 `17c0e63` 相同（非 T105 引入），但违反 handoff §6.1「任何路径不得整条渲染」与验收提示词第 6 项⑤，且 report §5「不会再整条倾倒」不成立。
- 期望：不得整条倾倒。① 含记录字段的追问（规格型号→只答规格；价格/数量/位置同理）按单字段作答（对齐上轮带标识 `（标识：QF02）` 时 29 字的行为）；② 不含记录字段的新内容（打印材质/陈列要求）不得输出多条记录/全字段——可走正文/legacy 但必须收窄，或澄清且不得列出未问字段值。**不得抢正文**：T101 法规题、政策题、`档期物料要提前多少天提报需求` 类正文/政策问句行为必须不变。
- 允许改动范围：`backend/src/mktkb/rag/query.py`、`backend/src/mktkb/rag/answer.py`（仅必要、最小改动，report §4 单列）。**禁止改 `conversations/`（含 service.py）、`intent.py`**（handoff §4）；若判定必须改禁止文件 → 停手，在 report 说明并报 PM 裁定。

## 2. 边界（继承 handoff §4/§5）
- 允许：上述源码；`backend/tests/` 本包测试（新增/修改）；`report.md`（追加 R1 段并修正不实风险表述）；证据 `docs/reports/OBS-EVAL/P1/evidence/T105/03-test-runs.md`、`04-scope-and-limitations.md`（**追加 R1 段，不新增文件**）；1 个新 commit。
- 禁止：`fixtures/evaluation/regression.jsonl` 及其他 fixtures、b0/badcase 数据、gate 配置、`conversations/`、`intent.py`、前端、其他包文件、`.claude/handoffs/**`（除 `report.md`）；不读 `.env`/Holdout；零真实模型/embedding/rerank/OCR；不 push/不 amend 历史；不新增生产依赖；无 skip/xfail/删断言/放宽断言。

## 3. 必须实际运行的检查（留证；不得并发 pytest）
1. 本包 2 个测试文件 1 次；2. `backend/tests/rag` 1 次；3. `backend/tests/integration` 1 次；4. `backend/tests/observability` 1 次；5. 全量 `backend/tests` 1 次（0 failed/0 error；内存 <2GB 先轮询；既有 flake 隔离复跑 1 次）；
6. b0/badcase local run+gate：对 `var/eval/runs/p0-b0`、`var/eval/runs/p0-badcase` 逐例 `case_diffs=0`、gate hard `[]`（命令口径见 handoff §10 / 验收证据 04）；
7. regression：当前树 vs `17c0e63` 基线逐例（RG006 保持 pass、RG001–RG004 pass、RG005/RG007 失败集不变、gate 无新增 hard 名）；
8. T101/T102 定向文件（`test_p1_t101_*`、rag+integration `test_p1_t102_state_inheritance.py`、`test_query_state.py`、`test_s2b_intent_semantics.py`）。

## 4. 交付与报告
- 1 个新 commit，消息：`p1/T105 R1 fix anaphora pagination regression + new-content dump`；不 push/不 amend。
- `report.md` 追加「R1 返工」段：两阻断修复前后对照（含 B1 复现命令与 page=2 证据、B2 三问文本长度/字段数）、根因与最小改动、全部运行数字、残余；**修正 §5「不会再整条倾倒」等不实表述**。
- 证据 03/04 追加 R1 段；证据总数仍 ≤4 份。
- 回复末尾给 ≤10 行交接摘要（commit、两修复证据、测试数字、偏离、风险）。

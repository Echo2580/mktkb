wb / cn:deepseek-v4.1-flash / reasoning_effort=max

# T105 独立验收 review-R2（R1 返工复验，ERR-06）

**结论：FAIL（B2 未收口；B1 已修复）。** B1 分页回退已按 `17c0e63` 修好，B2 的三个点名追问也不再整条倾倒；但 R1 新增的 `elif`/`ANAPHORA_NEW_CONTENT` 未排除政策/法规追问（`ANAPHORA_NEW_CONTENT` 漏排政策、`elif` 政策/法规均未排）：上文问位置后 `那个海报的价格欺诈规定是什么？` 返回 **位置 27 字**（问规格后返回规格 29 字），而不是法规正文；`那个海报的档期物料…`/`审批流程` 被压成 `not_found`，而去掉指代后单独提问可从 W02 答出 21 天。违反 `rework-R1.md:43-47` §5-2“不得扩大拦截”。证据：`verify/T105-R2/03-probe-results.md`。

## 1. 基线/范围/合规：PASS

- 起始 `git status --short` 空；分支 `p1/fix-retrieval`；HEAD `fecdfcc`；R1 `fc60c57` 父 `f1b96e2`。
- R1 仅 1 个 dev commit，7 文件（`query.py`、`answer.py`、2 测试、`report.md`、证据 03/04），均在 handoff/rework 允许路径；无第二 dev commit。
- `git diff 2306aaa..fc60c57 -- backend fixtures` 仅 4 个源/测试文件；fixtures 空；未改 `conversations/`、`intent.py`、b0/badcase/gate。
- `2306aaa..fc60c57` 的 6 个 PM commit 只动 `.claude/handoffs/**` + `verify/T105/**`。
- 测试 diff 无删除断言（仅 `_xlsx` 签名/循环改写）；两测试文件无 `skip/xfail/mark`；证据 T105 仍 4 份，03 §D、04 §E 含 R1 段。

## 2. B1（上轮 FAIL）独立 HTTP 探针：PASS

命令：`python -B docs\reports\OBS-EVAL\P1\evidence\verify\T105-R2\02-probe.py`（自写，未 import 开发测试）。12 行夹具：

- `把宣传海报都列出来` → `answer`，`{page:1,total:12,returned:10,has_more:true}`；`那个海报的第2页` → **`answer`，`{page:2,total:12,returned:2,has_more:false}`，266 字**，与基线 `17c0e63` 一致；父 `2306aaa` 仍为 `clarification` 31 字。
- 单独 `第2页`、`那个海报的下一页` 均 page=2；显式 `把那个海报的位置列出来`/`全部信息` 保持分页/枚举；无上文 `那个海报呢`/`那个呢` 仍澄清（0 字段值、sources=[]）。
- 代码：`query.py:1276-1281` 分页优先守卫生效；无回退。

## 3. B2（上轮 FAIL）独立探针：**FAIL（§5-2）**

**3a 点名项 PASS**（上文 `城西店的宣传海报在哪里？`）：

| 追问 | 当前 `fc60c57` | 父 `2306aaa`/基线 |
| --- | --- | --- |
| `那个海报的规格型号呢` | `answer` 29 字，仅 `A2 铜版纸 157g`，0 标识/分页 | 576 字，8 条×8 字段 |
| `那个海报的打印材质呢` | `not_found` 35 字，0 记录字段/0 未问值，sources=[] | 576 字，8×8 |
| `那个海报的陈列要求呢` | `not_found` 35 字，同上 | 576 字，8×8 |
| `位置/数量/参考供价` | 27/20/23 字，仅该字段 | 位置 43 字；数量/价格 576 字 |
| not_found 后再 `那个海报呢` | 27 字仅位置 | 27 字仅位置 |

**3b §5-2 证伪（阻断）**：上文问位置 →

- `那个海报的价格欺诈规定是什么？` → **`answer`“根据资料，城西店的宣传海报的位置：C区2号货架第一层。”27 字**；`那个海报的相关规定是什么？`/`那个海报适用的价格欺诈规定是什么？` 同 27 字；上文问规格后同问 → 规格 29 字。父/基线均为 576 字 8×8 倾倒，R1 新引入的是**错误字段答案**，不是保守化。
- 代码：`query.py:1336-1352`。`anaphora_new_content` 只排除 `is_regulation_question`，`elif explicit_record_entity and is_anaphora_field_followup(question, state.field_role)` 无政策/法规守卫。实测谓词：该问 `is_regulation_question=True`、`field_roles=()`、`is_anaphora_field_followup(...,'location')=True`，继承的 `state.field_role` 使 `enumerate=True` → RAG 单字段渲染。
- 政策/流程组合：`那个海报的档期物料要提前多少天提报需求？` → `not_found` 35 字；单独同一问题（D4 控制）→ `answer` 518 字含 21 天，故属过度拦截（非 §5-3 字面回退）；`审批流程` 同 35 字；`盘点时间` 42 字“未在资料中找到…记录”（记录存在，文案不实，P2）；`那个海报的《明码标价…规定》…` 42 字同文案。
- 不误伤：`档期物料要提前多少天提报需求？`（无指代）→ 518 字含 21 天；单独 T101 法规题 → 861 字含 2022-07-01 + 两项废止规定；`那个流程要提前几天提报`（无记录实体）→ 139 字；T101/T102 定向 44 passed。**故失败点是“实体+指代+政策/法规”组合，定向测试未覆盖。**

**3c §5-3 保守化**：`打印材质`/`陈列要求` 基线/父树也是 576 字倾倒，当前 `not_found` 属 R1 有意收窄，不构成 §5-3 行为回退；但单字段“未记录”文案对正文可答问题仍是 P2（D1/D2 单独问也仍 576 倾倒，说明未取正文）。

## 4. 测试/评测：PASS

- 本包 **23 passed**（6.88s）；rag **339**（20.77s）；observability **255**（16.35s）；integration **372**（240.18s，无 flake）；全量 **1701 passed / 0 failed / 0 error**（399.65s，跑前 3.59GB）。
- T101/T102：窄集 **37 passed**、全集 **44 passed**（report 的 44 可复现）。
- b0：`b0-local-20261106T172003747773Z-7193bbc2` pass29/fail3/skipped8，gate exit 3 hard `[]`，与 `p0-b0` **case_diffs=0**；badcase：`badcase-local-20261106T172014584247Z-31b30089` pass9/fail4，exit 3 hard `[]`，**case_diffs=0**。
- regression：当前 `…47cd7950` pass5/fail2，exit 3 hard `[]`；基线 `17c0e63`（`…5c26d774`）pass4/fail3，exit 1 hard `['security_leak']`；逐例**仅 RG006 fail→pass**，RG005/RG007 失败 checks 不变，无新 hard 名。
- 数字与 report §6 一致；无 flake，故无隔离复跑。

## 5. report/证据：PASS（带更正）

- 70 行、首行模型标注；§5 已修正“不会再整条倾倒”；§6 如实披露 B2 收窄/P2；证据 4 份、03/04 含 R1 段；数字复跑一致。
- 但 `report.md:66` / `evidence/T105/04-scope-and-limitations.md:37` 把“政策题+实体+字段词+指代”记为“观察（不阻塞）/未见回退”，本轮探针已证伪；`report.md:68` 的 70/70 是上一轮验收脚本（未覆盖该组合），不能作为 §5-2 全覆盖证据。

## 6. 残余 / NOT-RUN

- C4/C7 的“未找到记录”文案不实（记录存在，仅缺法规/日期字段）→ P2。
- 未跑：真实模型/live、embedding/rerank/OCR、`.env`、Holdout、T109 多轮 runner（按边界/未纳入）。
- 返工建议（最小）：`anaphora_new_content` 与 `elif` 均加 `not is_policy_question(question)`；对政策/法规题重置继承 `field_role`/走 document；补“实体+指代+政策/法规”HTTP 用例。

证据：`docs/reports/OBS-EVAL/P1/evidence/verify/T105-R2/`（01-verdict、02-probe.py、03-probe-results、04-test-eval-runs，共 4 份）。

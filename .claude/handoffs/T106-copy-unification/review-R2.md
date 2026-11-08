wb / cn:deepseek-v4.1-flash / reasoning_effort=max

# T106 独立验收 R2（D3 文案统一 / ERR-05，R1 返工后复验）

- 对象：`p1/fix-retrieval` @ `972f508`（R1 交付，父 `cb602b2`）；`HEAD=e08e2fc` 为 PM 簿记。复跑前 `git status --short` 空；`git show --stat 972f508` = **9 文件**；`git diff a42ee48..972f508 -- backend/src/mktkb/conversations/schemas.py` 为空。未改交付物、未 commit/push/切分支/stash/reset；未读 `.env`/Holdout；零真实模型/embedding/rerank/OCR。
- 结论：**PASS**（无阻塞；2 项非阻塞观察见「残余 / NOT-RUN」）。上轮已 PASS 项引用 `verify/T106/review.md`；本轮对 R1 失败项、受影响测试、全量、b0/badcase、regression、前端独立复跑。开发 `report.md` 只作线索，本页 PASS 均引自跑输出、`git` 与源码。
- 环境：`.venv\Scripts\python.exe` 3.12.7；`MKTKB_PROJECT_TOTAL_LIMIT_CNY=20.0`。

## 复跑总览

| 范围 | 结果 |
| --- | --- |
| 本包 / unit / observability / integration | **15 / 350 / 255 / 381 passed**（0.05 / 6.63 / 15.93 / 258.99s） |
| 全量 `backend/tests` | **1733 passed / 0 failed / 0 error**（388.92s；跑前 4,212,624 KB；5s 轮询 69 样本，最低 3,555,360 KB≈3.39GB，无 <2GB；无 flake，无需隔离复跑） |
| b0 / badcase local+gate | pass29/fail3/skipped8、pass9/fail4；均 exit 3、hard `[]`；对 P0 逐例 **0/40、0/13** |
| regression vs `17c0e63` | 基线 pass4/fail3 hard `['security_leak']` → 当前 pass5/fail2 hard `[]`；仅 RG006 fail→pass |
| 前端 | typecheck exit 0；build exit 0（40 modules，367.23 kB）；`02-chat` **7 passed**；acceptance `t106r2` expected=5/unexpected=0/flaky=0，outbound external `[]` |

## 逐项

### 1. B1 `IDENTIFIER_NOT_RETRIEVABLE` — PASS

- `copy.py:196-204` 现文案：`本次未按标识检索（当前检索不支持按标识筛选，系统未执行标识查询），不能据此判断该记录不存在，也不能确认该记录未找到；这不是资料中没有答案；请去掉标识，改用门店、物品名称等条件后重新查询，或联系管理员补充。`
- 独立探针 A：不再含 `资料中未找到`/`资料中未记录`/`未找到标识`；剥离允许否定句 `不是资料中没有答案` 后不含 `资料中没有`；含 `未按标识检索`、`不能据此判断该记录不存在`、门店/物品/重新查询/管理员自救；`COPY["IDENTIFIER_NOT_RETRIEVABLE"].material_related is False`。
- 可达性：`parse_question("QF21 放在哪里？")` → `intent=None, identifier="QF21", unknown_identifier=None, clarification=None, requested_fields=("位置",)`。`service.py:2071`（identifier）先于 `:2091`（intent is None）；`:2050` parse 与 `:2071` 之间 AST 调用集仅 `_read_session/load_lexicon/parse_question/annotate/text/_Result/bool/len`，无检索类调用。`:2072-2074` 注释明确产品检索层无标识筛选键、内核未接手时失败关闭，与“本次未检索”一致。
- 结论：无据的资料侧结论已删；`material_related=False` 与文案自洽；分支可达且文案诚实。

### 2. B2 / B3 与机械诚实性 — PASS

- `NO_INTENT`（`copy.py:207-213`）：`没有识别出这个问题的查询意图，本次未作答；这不是资料中没有答案；请补充门店、物品或要查询的字段等更具体的问法后重试。`；`material_related=False`；不含 `资料中未找到`。
- 不可达守卫：`intent.py` 6 处 `IntentPlan(intent=None)` 均带非空 `unknown_identifier`/`identifier`/`clarification`（探针列出 `(412, unknown_identifier)`、`(512, identifier)`、其余 4 处 `clarification`）；动态抽样 8 条问题无“无阻断 intent=None”；包内 AST 守卫 `test_p1_t106_copy.py:292-324`。文案仍按系统侧失败保持诚实，作为防御。
- `ANAPHORA_NEW_CONTENT`（`copy.py:345-352`）：`这次追问带入了不属于台账字段的新内容，本次未作答；这不是资料中没有答案；请指定要查询的字段（例如位置、数量、规格、价格）后重新提问。`；`material_related=False`；`answer.py:262-270` 直接渲染 copy 文本，可达。
- 机械规则（`test_p1_t106_copy.py:212-218`、`:221-227`）：遍历全部 `COPY.values()`；`material_related=False` 剥离允许否定句后禁 `资料中未找到/资料中未记录/资料中没有/未收录该资料/资料中未收录`；`material_related=True` 禁 `服务调用失败/服务不可用/系统故障`。逐条断言 `:230-289`；探针 E 对全部 COPY 独立复算，坏项 `[]`。规则不是空转：R1 前 B1 文案（`资料中未找到标识…` + `material_related=False`）会被该规则抓住。
- 结论：三条目文案诚实，测试覆盖真实规则并有可达性/不可达守卫。

### 3. 不变项 — PASS

- T104 七类 + `MODEL_POST_SEND_AUTH_DENIED`：从 `9933a7b:.../service.py` 的 `_MODEL_ERROR_REASONS` 重建模板，与当前 `copy.service_error_text` **8/8 逐字相同**（探针 F；旧探针 C 同结论）。
- R1 只改三条目：加载 `a42ee48` 的 `copy.py` 对比，模板变化集 = `{IDENTIFIER_NOT_RETRIEVABLE, NO_INTENT, ANAPHORA_NEW_CONTENT}`；元数据仅 B2/B3 `material_related` True→False，B1 保持 False；`copy.py` 其余条目未动。
- `schemas.py` 在 `a42ee48..972f508` 与 `cb602b2..972f508` 均无 diff；`AskResult` 12 字段、`MessageView` 12 字段、`ResultKind` 集合/顺序不变（探针 G）。R1 未改 `service.py`/`schemas.py`，`error_code` 语义与 T104 一致；旧探针 E 覆盖服务码集合。
- 上轮前端修正保持：`MessageCard.tsx:148-153` 无候选澄清仍为“这次回答没有提供可选项…”，无 `该历史消息未保存候选明细`；`format.ts:172-195` 的 `需补充条件`/`需要确认` 仍在；`02-chat` 与 acceptance 实跑通过。
- P2：`format.ts:178-199` 新增 `SERVICE_ERROR_BADGE_LABELS={INVALID_QUERY:"查询条件问题"}`，`MessageCard.tsx:92` 传 `errorCode`，`:261-262` 历史提示与正文一致；其他服务码仍“服务调用失败”（`02-chat` 通过）。

### 4. 测试 / 评测 — PASS

- 本包 **15 passed**；unit **350**；observability **255**；integration **381**；全量 **1733 passed / 0 failed / 0 error**（见 `04-test-eval-runs.md` §A）。定向受影响：T105 两文件 `test_new_content_non_field_followup_does_not_dump` **2 passed**；T104 HTTP 契约 **9 passed**。
- b0 `b0-local-20261108T114250048284Z-465d60ad`、badcase `badcase-local-20261108T114302522561Z-c130efc4`；gate 均 exit 3 / hard `[]`；对 P0 逐例 `(status, outcome.kind, 每个 check 状态)` **0/40、0/13**，无新增 hard。
- regression：基线 `17c0e63`（既有 worktree，`mktkb.__file__` 已核）`regression-local-20261108T114413446575Z-7284f88c` pass4/fail3 hard `['security_leak']` → 当前 `regression-local-20261108T114536810055Z-7149e1c7` pass5/fail2 hard `[]`；逐例仅 **RG006** `fail/answer/(kind_correct,value_forbidden)` → `pass/clarification`；RG001–RG005/RG007 失败集不变；无新增 hard 名。
- 结论：必跑项均实跑；无 flake 需隔离复跑；数字与开发 R1 报告一致（除本机更快）。

### 5. 前端 / 合规 / 形式 — PASS（含非阻塞观察）

- `npm.cmd run typecheck` exit 0；`npm.cmd run build` exit 0（40 modules，`index-BOb5Au_R.js` 367.23 kB）。`02-chat` **7 passed**（20.3s）；acceptance `t106r2` **PLAYWRIGHT EXIT 0**，`stats={expected:5, unexpected:0, flaky:0}`，outbound external `[]`。
- `INVALID_QUERY` 徽标无 e2e 注入入口：`serve_acceptance.py` 仅有 `POST /__acceptance/gateway/fail-next`（注入 `ModelError`），无 `QueryRejected`/`INVALID_QUERY` 注入；该分支由纯函数 + typecheck/build + 既有 service_error e2e 覆盖，NOT-RUN 理由成立（见残余）。
- `git show --name-only --format='' 972f508` = 9 文件，全部在返工单 §4 允许路径；无 `intent.py`/b0/badcase/数据/gate/`var`/账本改动；`pyproject`/lock/`package.json` 无 diff；R1 新增测试无 skip/xfail；T105 两处断言按文案取值最小同步（`"未记录"`→`"不属于台账字段"`，各 1 行，未删/未放宽其余断言）。
- `git log --oneline a42ee48..972f508`：`972f508` + PM 簿记 `cb602b2`；R1 dev commit 单一。开发证据仍 4 份；本目录证据 4 份。
- `report.md` 实测 **113 行**（`splitlines`），> handoff 80 行预算——**非阻塞观察**（返工单已要求记录，未影响判据）。

## 残余 / NOT-RUN

- 非阻塞：`kind=not_found` 的前端徽标仍为“无匹配资料”（`format.ts:165`）。`IDENTIFIER_NOT_RETRIEVABLE`/`NO_INTENT` 正文已诚实，但徽标仍按 kind 显示资料侧措辞；前端无 reason 字段（D-3 约束），上轮已列残余，本轮不阻塞 B1/B2 文案判据。
- 非阻塞：`INVALID_QUERY` 徽标分支无既有 e2e 注入入口（见上），仅纯函数/typecheck/build + 既有 service_error e2e 覆盖；未新增 mock e2e，记为 NOT-RUN 残余。
- 非阻塞：`report.md` 113 行 > 80 行预算。
- NOT-RUN（禁止项）：真实模型/embedding/rerank/OCR、Holdout。

## 证据（本目录 4 份）

`01-verdict.md`、`02-probe.py`（A–H，FAILS: 0）、`03-probe-results.md`、`04-test-eval-runs.md`。旧验收探针 `verify/T106/02-probe.py` 复跑亦 **FAILS: 0**。

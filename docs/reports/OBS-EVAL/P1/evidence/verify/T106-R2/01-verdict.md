# T106 R2 独立复验判据（01）

- 对象：`p1/fix-retrieval` @ `972f508`（R1 交付，父 `cb602b2`）；`HEAD=e08e2fc`（PM 簿记）。
- 复跑前 `git status --short` 为空；`git show --stat 972f508` = 9 文件；`git diff a42ee48..972f508 -- backend/src/mktkb/conversations/schemas.py` 为空。
- 边界：未改交付物、未 commit/push/切分支/stash/reset；未读 `.env`/Holdout；零真实模型/embedding/rerank/OCR。
- 结论：**PASS**（无阻塞；2 项非阻塞观察见 §4）。上轮已 PASS 项引用 `verify/T106/review.md`；本轮对 R1 失败项、受影响测试、全量、b0/badcase、regression、前端做了独立复跑。

## 1. 逐项判定

| # | 项 | 结论 | 证据 |
| --- | --- | --- | --- |
| 1 | B1 `IDENTIFIER_NOT_RETRIEVABLE` 文案诚实 + 可达 + `material_related=False` | **PASS** | `copy.py:196-204`；`service.py:2071-2082`；探针 A/B（`02-probe.py`） |
| 2 | B2 `NO_INTENT` / B3 `ANAPHORA_NEW_CONTENT` 文案诚实 + 机械诚实性测试 | **PASS** | `copy.py:207-213`、`:345-352`；`test_p1_t106_copy.py:212-324`；探针 C/D/E |
| 3 | T104 七类 + `MODEL_POST_SEND_AUTH_DENIED` 逐字不变；结构/枚举/`error_code` 语义不变；上轮前端修正保持 | **PASS** | 探针 F/G/H；`git show --name-only 972f508`；旧探针 A–H `FAILS: 0` |
| 4 | 测试/评测：本包、unit、integration、observability、全量；b0/badcase；regression | **PASS** | `04-test-eval-runs.md` |
| 5 | 前端 typecheck/build、受影响 e2e、T105 同步、路径/依赖/skip、证据/行数/commit | **PASS（含非阻塞观察）** | `04-test-eval-runs.md` §D/§E；`report.md` 113 行 > 80 |

## 2. B1 关键事实

- 渲染文案（`copy.py:200` 起）：`本次未按标识检索（当前检索不支持按标识筛选，系统未执行标识查询），不能据此判断该记录不存在，也不能确认该记录未找到；这不是资料中没有答案；请去掉标识，改用门店、物品名称等条件后重新查询，或联系管理员补充。`
- 不含 `资料中未找到` / `资料中未记录`；剥离否定句 `不是资料中没有答案` 后也不含 `资料中没有`；不再出现 `未找到标识` 式无据结论。
- `material_related=False`；自救指引含门店/物品/重新查询/管理员。
- 可达性：`parse_question("QF21 放在哪里？")` → `intent=None, identifier="QF21", unknown_identifier=None, clarification=None, requested_fields=("位置",)`；`service.py:2071` 的 identifier 分支先于 `:2091` 的 `intent is None` 分支；`parse_question`（`:2050`）与 identifier 分支之间无检索类调用（AST 调用集仅 `_read_session/load_lexicon/parse_question/annotate/text/_Result/bool/len`）。
- 该分支在 `service.py:2072-2074` 明确“产品检索层没有标识筛选键、内核未接手时失败关闭”，与“本次未检索”一致。

## 3. B2 / B3 关键事实

- `NO_INTENT`：`没有识别出这个问题的查询意图，本次未作答；这不是资料中没有答案；请补充门店、物品或要查询的字段等更具体的问法后重试。`；`material_related=False`。
- 当前不可达：`intent.py` 6 处 `IntentPlan(intent=None)` 均带非空阻断字段（`unknown_identifier` / `identifier` / `clarification`）；动态抽样 8 条问题未出现无阻断 `intent=None`；包内 `test_no_intent_branch_is_guarded_by_current_intent_plans`（`test_p1_t106_copy.py:292-324`）为 AST 守卫。
- `ANAPHORA_NEW_CONTENT`：`这次追问带入了不属于台账字段的新内容，本次未作答；这不是资料中没有答案；请指定要查询的字段（例如位置、数量、规格、价格）后重新提问。`；`material_related=False`；调用点 `answer.py:262-270` 直接渲染 copy 文本。
- 机械规则：`material_related=False` 的 53 条 COPY 条目（剥离允许否定句后）均不含 `资料中未找到/资料中未记录/资料中没有/未收录该资料/资料中未收录`；`material_related=True` 均不含 `服务调用失败/服务不可用/系统故障`。测试遍历全部 `COPY.values()`，清单显式、先剥离否定句，不是空转。

## 4. 残余 / NOT-RUN（非阻塞）

- `kind=not_found` 的前端徽标仍是 `无匹配资料`（`format.ts:165`）；`IDENTIFIER_NOT_RETRIEVABLE` / `NO_INTENT` 正文已诚实，但徽标仍按 kind 显示资料侧措辞。前端无 reason 字段（D-3 约束），上轮已记录为残余；本轮不阻塞 B1/B2 的文案判据。
- `INVALID_QUERY` 徽标分支（`format.ts:178-199`、`MessageCard.tsx:92/261-262`）无既有 e2e 注入入口：acceptance 只提供 `POST /__acceptance/gateway/fail-next`（注入 `ModelError`），无 `QueryRejected`/`INVALID_QUERY` 注入；本分支由纯函数 + typecheck/build + 既有 service_error e2e 覆盖，NOT-RUN 理由成立，列为残余。
- `report.md` 113 行 > 80 行预算（handoff §4/§6-5），非阻塞观察。
- 真实模型/embedding/rerank/OCR、Holdout：禁止项，NOT-RUN。

## 5. 证据

`01-verdict.md`、`02-probe.py`、`03-probe-results.md`、`04-test-eval-runs.md`（本目录 4 份）。

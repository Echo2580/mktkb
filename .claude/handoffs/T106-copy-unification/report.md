wb / cn:deepseek-v4.1-flash / reasoning_effort=max

# T106 报告：D3 文案统一（ERR-05，P1 第 8 包）

## 1. 完成内容

- 新增 `backend/src/mktkb/copy.py`：reason→文案唯一映射（33 个交接单 reason +
  服务错误/检索错误/事实拒绝），语义相同的 reason 用 `REASON_ALIASES` 显式登记；
  每条文案带 `retryable`/`material_related`/`requires_user_input` 三要素元数据。
- `conversations/service.py`、`rag/answer.py`、`rag/query.py` 仅把文案来源改为映射；
  `kind`/`error_code`/字段结构/检索路径/意图词表均未改。
- T104 七类服务错误 + `MODEL_POST_SEND_AUTH_DENIED` 文案逐字保留；`_model_error_text`
  新增可选 `retryable`，未登记码按真实可重试性选提示（T104 复核残余 5）。
- 前端：clarification 无候选徽标改“需补充条件”，有候选仍“需要确认”；删除
  “该历史消息未保存候选明细”武断文案；历史服务错误按稳定码推导不可重试；
  服务错误徽标“服务暂不可用”→“服务调用失败”。
- 测试/证据：新增 8 条包内单测；e2e 同步徽标取值并新增 C02 无候选澄清用例；
  b0/badcase 逐例 0 差异；regression 仅 T105 已收口的 RG006 变化。

## 2. 验收标准自证

1. **映射唯一/完整**：`copy.py:547`（33 reason）、`:584`（别名）、`:640`（解析）；
   `test_p1_t106_copy.py::test_required_reasons_all_resolve_to_registered_copy`。
2. **三要素**：`test_every_entry_states_three_elements` 枚举断言“不是资料中没有答案 /
   重试提示 / 请补充”自洽；T104 矩阵见 `test_t104_service_error_matrix_is_unchanged`。
3. **唯一串**：`test_every_copy_entry_is_unique`（53 条模板无重复）、
   `test_required_reasons_render_distinct_user_text`（reason 渲染不重复）。
4. **行为不变**：`test_p1_t104_error_classification_http.py` 的 12 字段断言全通过；
   b0/badcase `case_diffs=0`；regression 仅 RG006（T105 既有）。
5. **前端修正**：`MessageCard.tsx:92/144-153/73-77/257`、`format.ts:172-187`；
   C02 用例 `acceptance-02-kinds.spec.ts:55` 覆盖 live + reload；`npm run build` 通过。
6. **回归**：unit 343 / observability 255 / integration 380+1 既有 flake（隔离 1 passed）/
   全量 1726 passed；b0/badcase/regression gate hard `[]`（regression 基线
   `['security_leak']` 只收缩）；RG001–RG005 状态不变、RG006 fail→pass（PASS）、RG007 失败集不变。
7. **合规**：证据 4 份、report 五段、1 commit、只改允许路径；无 skip/xfail/删断言/
   新依赖/真实调用。

## 3. 实际运行结果

- 本包：`t106-copy5` **8 passed**（0.03s）；unit `t106-unit2` **343 passed**（6.39s）；
  observability `t106-obs3` **255 passed**（15.33s）。
- integration `t106-int2`：380 passed / 1 failed（既有 `test_g08_short_budget_cancels_inflight_model_call`
  时序 flake），隔离复跑 `t106-flake` **1 passed**（1.31s）。
- 全量 `t106-full2`：**1726 passed / 0 failed / 0 error**（400.70s，跑前 FreePhysicalMemory≈3.86 GB）。
- b0：`b0-local-20261105T090359232489Z-6e3eb84c` → `b0-local-20261108T094419554592Z-9c0e154c`，
  pass29/fail3/skipped8 不变，gate exit 3 hard `[]`，逐例 **0/40**。
- badcase：`badcase-local-20261105T090409960294Z-f03d4b5f` →
  `badcase-local-20261108T094423687130Z-53784204`，pass9/fail4 不变，hard `[]`，逐例 **0/13**。
- regression：`17c0e63` 基线 `regression-local-20261108T094008270406Z-45e19f74`
  pass4/fail3 hard `['security_leak']` → 当前 `regression-local-20261108T094446258122Z-5a44219e`
  pass5/fail2 hard `[]`；逐例仅 RG006 fail→pass，RG005/RG007 失败 checks 不变。
- 前端：`npm run build` 通过（40 modules，367.01 kB JS）；`02-chat.spec.ts` **7 passed**；
  acceptance runner label `t106` → **PLAYWRIGHT EXIT 0**，`expected=5 / unexpected=0`。
- commit：`p1/T106 unify reason copy + honest frontend badges`（sha 见交付回复）；
  stat：9 文件（7 改 + 2 新增），后端 3 文件 + 映射/测试，前端 4 文件；证据 4 份 + 本报告。

## 4. 偏离或未做（文案取值变化清单）

- **取值变化**：`NO_INTENT` 增加“如果确认资料中存在，请改用更具体问法”；
  `IDENTIFIER_NOT_RETRIEVABLE` 改为“未找到但本次未按标识检索，不能据此判断不存在”；
  `RECORD_ONLY`/`RETRIEVAL_ERROR`/`CHAT_*`/`FACT_REJECTED` 补齐“不是资料中没有答案”
  与重试/管理员路径；所有澄清/缺失文案增加可自救提示；服务错误徽标改“服务调用失败”。
- **未改**：`not_found` 徽标“无匹配资料”（`NO_INTENT` 与资料缺失共用 kind，前端无 reason
  无法可靠细分）；历史冲突/来源明细“未保存…明细”文案；`POLICY_FOLLOWUP` 作为独立
  用户结局（别名到 `NO_EVIDENCE`，内部 plan reason 不变）。
- **未跑**：真实模型/embedding/rerank/OCR、Holdout（禁止项）；无 e2e NOT-RUN
  （02-chat 与 acceptance-02 均实际通过）。

## 5. 风险

- `NO_INTENT` 的徽标仍无法区分“系统没理解”与“资料没有”；彻底解决需新增 reason
  字段，受 D-3 字段结构约束，本包不做。
- 前端历史服务错误的可重试性依赖 `NON_RETRYABLE_SERVICE_ERROR_CODES` 与后端
  `copy.SERVICE_ERROR_CODES` 手工同步；新增非重试码若漏同步会短暂显示“重新提问”。
- 记录型冲突文案必须继续满足 FactValidator 的逐句可验证形态；后续若在冲突文案
  追加说明句，可能被事实闸门拒绝（本包已保留原句式）。
- 文案为中文单语；未引入 i18n。

## 6. R1 返工（2026-11-08，响应 review FAIL）

验收方探针 `verify/T106/02-probe.py` 复跑 **FAILS: 0**（G 段 3 项全 ok、H 段标识-only 可达 ok；R1 前为 3）。§4 的取值描述与开发证据 01 §C 为 R1 前状态，以本节为准。

### 6.1 三条目（`copy.py:192-215`、`:345-355`）

- **B1 `IDENTIFIER_NOT_RETRIEVABLE`**（阻塞；`material_related=False` 不变）：删去“资料中未找到标识…对应的记录”，改为“本次未按标识检索（当前检索不支持按标识筛选，系统未执行标识查询），不能据此判断该记录不存在，也不能确认该记录未找到；这不是资料中没有答案；请去掉标识，改用门店、物品名称等条件后重新查询，或联系管理员补充。”
- **B2 `NO_INTENT`**（`True→False`）：改为“没有识别出这个问题的查询意图，本次未作答；这不是资料中没有答案；请补充门店、物品或要查询的字段等更具体的问法后重试。”
- **B3 `ANAPHORA_NEW_CONTENT`**（`True→False`）：删去“资料中未记录这项信息”，改为“这次追问带入了不属于台账字段的新内容，本次未作答；这不是资料中没有答案；请指定要查询的字段（例如位置、数量、规格、价格）后重新提问。”
- 可达性：标识-only `parse_question("QF21 放在哪里？")` → `intent=None, identifier=QF21, clarification=None`，`service.py:2071` 先于 `:2091`，确认该路径未执行检索。NO_INTENT 由 AST 证明当前不可达（`intent.py` 所有 `intent=None` 计划均带 `unknown_identifier`/`identifier`/`clarification`），文案仍保留为防御。

### 6.2 机械诚实性测试（`test_p1_t106_copy.py` 8→15）

- `material_related=False`：剥离“不是资料中没有答案”等允许否定句后，禁含“资料中未找到/资料中未记录/资料中没有/未收录该资料/资料中未收录”；`material_related=True`：禁含“服务调用失败/服务不可用/系统故障”。
- 三条目逐条断言（无资料侧结论、含自救指引、元数据取值）+ IDENTIFIER 可达性探针 + NO_INTENT 不可达 AST 证明；既有唯一性/别名/覆盖/T104 逐字测试未删未放宽。

### 6.3 P2 / P3

- P2：`format.ts:178-199` 新增 `SERVICE_ERROR_BADGE_LABELS={INVALID_QUERY:"查询条件问题"}`，`resultBadgeLabel` 按 `errorCode` 细分；`MessageCard.tsx:92` 传入，历史提示对 `INVALID_QUERY` 显示“这是查询条件问题，不是服务故障；请换个说法后重新提问。”，与正文/徽标一致；其他服务码仍“服务调用失败”。
- P3：`report.md:34` 已更正为“RG001–RG005 状态不变、RG006 fail→pass（PASS）、RG007 失败集不变”。

### 6.4 R1 运行数字（最终树）

- 本包 15 passed / unit 350 / integration 381 / observability 255 / 全量 **1733 passed, 0 failed, 0 error**（426.52s，跑前 4,189,616 KB）。
- b0 `b0-local-20261108T111400756268Z-ee6841f3` 29/3/8、hard `[]`、逐例 **0/40**；badcase `badcase-local-20261108T111408556326Z-ecad1930` 9/4、hard `[]`、**0/13**。
- regression：`17c0e63` `regression-local-20261108T111629020110Z-d742446e` 4/3 hard `['security_leak']` → 当前 `regression-local-20261108T111453776477Z-a37f7643` 5/2 hard `[]`；仅 RG006 fail→pass，RG001–RG005/RG007 不变。
- 前端：typecheck 0 / build 0（40 modules，367.23 kB）/ `02-chat` 7 passed / acceptance `t106r1` expected=5、unexpected=0。
- commit：`p1/T106 R1 fix honest copies for unsearched/unidentified paths`（sha 见回复）。

### 6.5 偏离 / 残余

- 最小同步两处 T105 既有断言（`"未记录"`→`"不属于台账字段"`，integration/rag 各 1 处），语义不变、未删/未放宽。
- B1 在否定句内保留“未找到”（“也不能确认该记录未找到”）：既满足 T09 冻结题集 U04 的可接受缺失措辞，又不出现“资料中未找到…记录”的无检索断言；U04 随全量通过。
- P2 的 `INVALID_QUERY` 分支无既有 e2e 注入入口（acceptance 只注入模型错误），未新增 mock e2e（NOT-RUN 原因）；两套受影响 e2e 均实际通过，标签由纯函数 + typecheck/build 覆盖。
- 残余：NO_INTENT 若未来出现裸 `intent=None` 会由 AST 测试报警；历史 clarification 有候选未持久化仍只能“需补充条件”（前端无 reason 字段）。

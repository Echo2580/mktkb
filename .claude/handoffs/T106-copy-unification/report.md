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
   `['security_leak']` 只收缩）；RG001–RG006 状态不变、RG006 PASS、RG007 失败集不变。
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

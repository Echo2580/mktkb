# T106 返工单 R1（PM，2026-11-08 18:4x）

> 依据：独立验收 `review.md`（FAIL：item 1 阻塞，其余 4 项 PASS；无 NOT-RUN）+ `docs/reports/OBS-EVAL/P1/evidence/verify/T106/`。轮次 **R1/3**。
> 基线：T106 交付 `a42ee48`（父 `9933a7b`）；本轮 **1 个新 commit**，**不 amend 历史**。
> 执行者：开发 subagent（`wb / cn:deepseek-v4.1-flash`，`reasoning_effort=max`）。PM 不写代码。

## 1. 未过条款（handoff §6-1「诚实、不编造原因」）—— 必须修

验收方自写探针（`verify/T106/02-probe.py` G/H 段）证明以下用户可见文案**自相矛盾/把系统侧原因说成资料缺失**：

### B1（阻塞）`IDENTIFIER_NOT_RETRIEVABLE`（`backend/src/mktkb/copy.py:192-200`）
- 现状：同一串既写「资料中未找到标识"{identifier}"对应的记录」，又写「本次未按标识检索…不能判断该记录不存在」；`material_related=False`。
- 可达性：`parse_question("QF21 放在哪里？")` → `intent=None, identifier=QF21, clarification=None` 且 `conversations/service.py:2071-2082` 明确「产品检索层没有标识筛选键、内核未接手 → 失败关闭」，即**没有执行检索**。
- 期望：**不得**出现「资料中未找到…记录/资料中没有」等无据结论；须说明「本次未按标识检索（不支持标识筛选），无法判断记录是否存在，不是资料中没有答案」，并给自救指引（去掉标识、改门店/物品名称，或联系管理员）。

### B2（同类，一并修）`NO_INTENT`（`copy.py:201-208`）
- 现状：「资料中未找到与这个问题相符的内容」+ `material_related=True`；该 reason 是「未识别出查询意图」（系统侧）。
- 期望：改为「没有识别出这个问题的查询意图，本次未作答；这不是资料中没有答案；请补充门店、物品或字段等更具体问法后重试」类，`material_related=False`；如确认不可达，report 必须证明（探针/代码路径），但仍须文案诚实。

### B3（同类，一并修）`ANAPHORA_NEW_CONTENT`（`copy.py:338-345`）
- 现状：「资料中未记录这项信息；…不是资料中没有答案」自相矛盾。
- 期望：改为「这次追问带入了不属于台账字段的新内容，本次未作答；不能据此判断资料中没有答案；请指定要查询的字段（位置/数量/规格/价格等）后重试」类，`material_related=False`。

## 2. 非阻塞（建议同轮收口；不阻塞 PASS）
- **P2**：`INVALID_QUERY` 徽标「服务调用失败」与正文「这是查询条件问题」不一致（`format.ts:167` + `MessageCard.tsx:254-262` 历史提示）；利用可用 `error_code` 让徽标/提示与正文一致（若改标签须同步 e2e，不得放宽语义）。
- **P3**：`report.md:34` 把「RG001–RG006 不变、RG006 PASS」写错（实测 RG006 fail→pass）——更正。
- 历史 clarification 有候选未持久化时只能「需补充条件」——保持现状并记录（P3 残余，前端无 reason 无解）。

## 3. 必加测试（防回归）
1. **机械诚实性规则**：`material_related=False` 的 reason，渲染文案不得包含「资料中未找到/资料中未记录/资料中没有/未收录该资料」等资料侧结论；`material_related=True` 不得宣称「服务调用失败」类。
2. 三条目（IDENTIFIER_NOT_RETRIEVABLE/NO_INTENT/ANAPHORA_NEW_CONTENT）逐条断言：无自相矛盾短语组合、含自救指引；IDENTIFIER 路径用 `parse_question`（或等价探针）证明可达且文案诚实。
3. T104 七类 + `MODEL_POST_SEND_AUTH_DENIED` 文案保持逐字不变（既有机械测试保留）。
4. 既有映射唯一性/别名/覆盖测试全部保持通过（不得删/放宽）。

## 4. 边界与必跑检查
- 只改：`copy.py`、`conversations/service.py`/`rag/answer.py`（仅文案/元数据接线）、`frontend/src/utils/format.ts`/`MessageCard.tsx`（仅 P2 项）、本包测试与 e2e 同步、`report.md`、证据 03/04 追加 R1 段（不新增文件）。
- 禁止：改 API 字段结构/`ResultKind`/`error_code` 语义、`intent.py`、b0/badcase/regression、gate 配置、账本/GO、`.env`/Holdout、真实调用、push/amend、skip/xfail/删断言。
- 必跑：本包测试 / `backend/tests/unit` / `integration` / `observability` / 全量 `backend/tests`（0 failed/0 error；内存 <2GB 轮询；既有 flake 隔离复跑 1 次）；b0/badcase local run+gate 对 P0（`hard_failures` 无新增、kind/status 不变）；regression 对 `17c0e63`（RG001–RG005 不变、RG006 PASS、RG007 不变、无新 hard）；前端 `npm run typecheck` + `npm run build`；受影响 e2e（若 P2 改标签）实际跑或记录 NOT-RUN 原因。

## 5. 交付
- 1 个新 commit：`p1/T106 R1 fix honest copies for unsearched/unidentified paths`；不 push/不 amend。
- `report.md` 追加「R1 返工」段：三条目修复前后对照、诚实性规则测试、P2/P3 处理、全部运行数字、残余；更正 RG006 表述。
- 证据 `03-test-runs.md`/`04-scope-and-limitations.md` 追加 R1 段（不新增文件，仍 ≤4）。
- 回复 ≤10 行摘要（commit、三条目证据、测试数字、偏离、风险）。

角色：开发助手（**返工轮 R1**），不是验收者。任务 **T106（D3 文案统一）R1 返工**。完整返工单已落盘 `.claude\handoffs\T106-copy-unification\rework-R1.md`。
模型：`wb / cn:deepseek-v4.1-flash / reasoning_effort=max`。
工作目录 `D:\GPT项目\市场部AI知识库`；分支 `p1/fix-retrieval`；当前 HEAD 含 PM 簿记；**T106 交付 commit `a42ee48`**；开工前 `git status --short` 必须 clean。

第一步（按序读）：
1. `.claude\handoffs\T106-copy-unification\rework-R1.md`（**B1/B2/B3 判据与期望、诚实性测试、边界**）
2. 同目录 `review.md`（FAIL 依据与探针 G/H）、`report.md`、`handoff.md`（§6 验收标准）
3. `docs\reports\OBS-EVAL\P1\evidence\verify\T106\{01-verdict.md,02-probe.py,03-probe-results.md,04-test-eval-runs.md}`
4. `backend\src\mktkb\copy.py` 相关条目、`conversations\service.py:2060-2100`、`rag\answer.py:255-275`、`frontend\src\utils\format.ts`/`MessageCard.tsx`

第二步（实现，最小改动）：
- **B1 阻塞**：`IDENTIFIER_NOT_RETRIEVABLE` 文案不得含「资料中未找到…记录/资料中没有」；改为「本次未按标识检索（产品检索层不支持标识筛选/内核未接手），无法判断该记录是否存在，不是资料中没有答案；请去掉标识改用门店、物品名称，或联系管理员补充」类，`material_related=False`。
- **B2/B3 同类**：`NO_INTENT`（改为「没有识别出查询意图…不是资料中没有答案；请补充门店/物品/字段后重试」，`material_related=False`）、`ANAPHORA_NEW_CONTENT`（改为「这次追问带入了不属于台账字段的新内容，本次未作答；不能据此判断资料中没有答案；请指定字段后重试」，`material_related=False`）。若 NO_INTENT 判断不可达，须用探针证明并仍保证文案诚实。
- **测试**：新增机械诚实性测试（`material_related=False` 不得含资料侧结论；`material_related=True` 不得称服务失败）+ 三条目逐条断言（含 IDENTIFIER 可达性探针）；保留既有唯一性/别名/覆盖/T104 逐字测试，不得删/放宽。
- **P2（建议同轮）**：`INVALID_QUERY` 徽标/正文/历史提示一致（可用 `error_code` 区分；改标签须同步 e2e，不放宽语义）。
- **P3**：更正 `report.md:34` RG006 表述。
- 只改允许路径（copy.py、service.py/answer.py 仅接线、format.ts/MessageCard.tsx 仅 P2、本包测试/e2e、report、证据 03/04 追加）；禁止改 API 字段结构/intent/词表/fixtures b0 badcase/regression/gate/账本/GO；不读 `.env`/Holdout；零真实调用；不 push/amend。

第三步（验证）：按 rework-R1 §4 全部实际执行（本包/unit/integration/observability/全量；b0/badcase 对 P0；regression 对 17c0e63；前端 typecheck+build；受影响 e2e 如改标签则实跑或记录 NOT-RUN）；内存 <2GB 先轮询；同一时间只跑一套 pytest。

第四步（交付）：1 个新 commit `p1/T106 R1 fix honest copies for unsearched/unidentified paths`；report 追加 R1 段；证据 03/04 追加 R1 段（≤4 份）；回复 ≤10 行摘要。

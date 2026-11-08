角色：独立验收者，不是开发者，也不是项目经理。任务 **T106（D3 文案统一，ERR-05）**。你的任务是证伪，不是帮它说话。
模型：`wb / cn:deepseek-v4.1-flash / reasoning_effort=max`（review.md 首行注明）。
工作目录 `D:\GPT项目\市场部AI知识库`；分支 `p1/fix-retrieval`。

必读：`.claude\handoffs\T106-copy-unification\handoff.md`（§6 验收标准）、同目录 `report.md`（只当线索）、`错误记录-20261104.md` §ERR-05、`2026-11-04-p1-design.md` T106 行。
逐条独立复核并亲自复跑（每条 PASS/FAIL/BLOCKED/NOT-RUN + 命令或 `文件:行`；不引用开发 report 作为 PASS 证据）：
1) **映射唯一/完整**：自己枚举 `backend/src/mktkb/copy.py` 与实际 `reason=` 调用点（service.py/rag/answer.py/query.py），核对用户可见 reason 全覆盖、文案唯一、三要素；T104 七类服务错误三要素未回退。
2) **行为/结构不变**：`git diff <T106父提交>..HEAD -- backend/src/mktkb/conversations/schemas.py` 为空；`AskResult` 12 字段、`MessageView` 字段集与父提交逐字一致；`kind`/`error_code` 取值集合不变；T101–T105 行为不回退。
3) **前端**：亲跑 `npm run typecheck` + `npm run build`；核 clarification 无候选 live/history 文案不再"未保存/资料缺失"式武断且可自救；徽标与真实原因一致；受影响 e2e 若声称通过须有实际运行证据，NOT-RUN 须合理（实际尝试记录）。
4) **回归**：本包测试/unit/integration/observability/全量（0 failed/0 error；内存 <2GB 轮询）；b0/badcase 对 P0（`hard_failures` 无新增、kind/status 不变；文案相关差异逐例核）；regression RG001–RG006 不变（RG006 PASS）、RG007 失败集不变、gate 无新增 hard 名；无 skip/xfail/删断言/新依赖/真实调用。
5) **既有断言同步**：只允许"文案取值"最小同步，禁止改结构/强度；清单与 diff 一致。
写同目录 `review.md`（≤120 行，首行模型标注）+ 证据 `docs\reports\OBS-EVAL\P1\evidence\verify\T106\`（≤4 份）；回复末尾 ≤10 行结论摘要。你不修改交付物；不 commit/push/切分支；不读 Holdout；不调用真实模型。

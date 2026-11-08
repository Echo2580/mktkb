角色：独立验收者（全新上下文），不是开发者/PM。任务 **T106（D3 文案统一）R1 返工后的复验 R2**。证伪导向。
模型：`wb / cn:deepseek-v4.1-flash / reasoning_effort=max`（review-R2.md 首行注明）。
工作目录 `D:\GPT项目\市场部AI知识库`；分支 `p1/fix-retrieval`；当前 HEAD `972f508`（R1 交付，父 `cb602b2`），工作树应 clean。
（§11A 定向复验：上轮 FAIL 项与受影响测试必须独立复跑 + 全量 1 次；上轮其余 PASS 项沿用并引用旧 review，不重复全套探针。）

## 必读
1. `.claude\handoffs\T106-copy-unification\rework-R1.md`（B1/B2/B3 判据与期望、诚实性测试要求）
2. 同目录 `review.md`（上轮 FAIL 依据与探针 G/H）、`report.md`（只当线索，含 R1 段）、`handoff.md` §6
3. `docs\reports\OBS-EVAL\P1\evidence\verify\T106\`（上轮 01/02/03/04；可运行/借鉴其 02-probe.py G/H 段）
4. 复跑前 `git status --short` clean；`git show --stat 972f508` 应 9 文件；`git diff a42ee48..972f508 -- backend/src/mktkb/conversations/schemas.py` 应为空。

## 定向复验（逐条 PASS/FAIL/BLOCKED/NOT-RUN + 命令或 `文件:行`；不引用 report 作 PASS 证据）
1. **B1 阻塞项**：`IDENTIFIER_NOT_RETRIEVABLE` 渲染文案不得再含「资料中未找到…记录/资料中没有」等无据结论；须说明「本次未按标识检索、无法判断是否存在、不是资料中没有答案」+ 自救指引；用 `parse_question`（或等价探针）独立证明该分支可达且文案诚实；`material_related=False`。
2. **B2/B3 同类**：`NO_INTENT`（未识别意图，不得称资料缺失，`material_related=False`；若不可达须有可达性证明/ AST 守卫）与 `ANAPHORA_NEW_CONTENT`（不得自相矛盾，`material_related=False`）文案诚实；检查机械诚实性测试是否真正覆盖（`material_related=False` 不含资料侧结论、`True` 不称服务失败）。
3. **不变项**：T104 七类 + `MODEL_POST_SEND_AUTH_DENIED` 文案逐字不变；`AskResult` 12 字段/`MessageView` 字段集/`ResultKind`/`error_code` 语义不变；上轮 PASS 的前端修正保持（无候选澄清徽标/文案、有候选"需要确认"）。
4. **测试/评测（§11A）**：本包 1 次；unit/integration/observability 各 1 次；全量 `backend/tests` 1 次（0 failed/0 error；内存 <2GB 轮询；既有 flake 隔离复跑 1 次）；b0/badcase 对 P0（`hard_failures` 无新增、kind/status 不变、逐例 0）；regression 对 `17c0e63`（RG001–RG005 不变、RG006 PASS、RG007 不变、无新 hard 名）。
5. **前端/合规/形式**：`npm run typecheck` + `npm run build` 亲跑；受影响 e2e（02-chat/acceptance-02-kinds）实跑或核 NOT-RUN 理由（INVALID_QUERY 徽标无注入入口的 NOT-RUN 是否合理）；T105 测试改动是否仅文案同义同步（语义不变、未放宽）；允许路径/无 skip/xfail/删断言/新依赖；证据 ≤4；**report 当前行数（约 115 行）> 80 预算，记录为非阻塞观察**；单 commit。

## 输出与边界
- 写 `.claude\handoffs\T106-copy-unification\review-R2.md`（≤120 行；首行模型标注；含残余/NOT-RUN）。
- 证据 ≤4 份：`docs\reports\OBS-EVAL\P1\evidence\verify\T106-R2\`（建议 01-verdict.md、02-probe.py、03-probe-results.md、04-test-eval-runs.md）。
- 不改交付物；不 commit/push/切分支/stash/reset；不读 `.env`/Holdout；零真实模型/embedding/rerank/OCR；临时文件只放 `backend\.pytest-tmp\T106-R2\` 或 `$env:TEMP`；结束回复 ≤10 行摘要。

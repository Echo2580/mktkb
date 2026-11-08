角色：独立验收者（全新上下文），不是开发者/PM。任务 **T109（多轮 turns runner）R1 返工后的复验 R2**。证伪导向。
模型：`wb / cn:deepseek-v4.1-flash / reasoning_effort=max`（review-R2.md 首行注明）。
工作目录 `D:\GPT项目\市场部AI知识库`；分支 `p1/fix-retrieval`；R1 交付 commit **`1ffd57a`**（父 `08661ff`），工作树应 clean。
（§11A 定向复验：上轮 FAIL 项 + 受影响测试 + 全量 1 次；上轮 PASS 项引用旧 review 做抽查。）

## 必读
1. `.claude\handoffs\T109-multiturn-runner\rework-R1.md`（B1 replay fail-closed + R1/R2/R3）
2. 同目录 `review.md`（上轮阻断依据/复现命令）、`report.md`（只当线索，含 R1 段）、`handoff.md`（§0/§3）
3. `docs\reports\OBS-EVAL\P1\evidence\verify\T109\`（上轮 01/03/04；02-probe.py 可参考）
4. 复跑前：`git status --short` clean；`git show --stat 1ffd57a` 应 6 文件；`git show 1ffd57a -- fixtures` 应为空（RG006 不改）。

## 定向复验（逐条 PASS/FAIL/BLOCKED/NOT-RUN + 命令或 `文件:行`；不引用 report 作 PASS 证据）
1. **B1（上轮阻断）replay fail-closed**：用父提交 regression run（RG002/RG003/RG006 无 `turn_traces`）作源 + 当前 replay → 三行必须 `status=fail`、`error.code=multi_turn_source_missing`（或等价明确 code）、`turn_traces=[]`、`turns_executed=0`，**不得 status=pass/单条 trace**；再用"源多轮但轮数不足"造例 → `multi_turn_source_incomplete`/明确失败；合法多轮源仍逐轮 replay（0/7 diffs 类）。补自写测试/探针验证。
2. **R1/R2/R3**：中间轮 `kind=error/service_error`/Trace 不可读 → `error{code,message 含 turn n/N}`、`turns_executed` 实际轮数；malformed/gold-error 多轮行 `turns_executed` 非默认 1；replay 每轮 trace 的 question 用各轮问题（与 local 逐轮问题一致）。
3. **上轮 PASS 抽查**：多轮 local 顺序/同会话/状态继承/只末轮评分/中间轮不判分；单轮 b0/badcase 对 P0 `case_diffs=0/40、0/13`、对父提交 strict 0（仅多 `turn_traces`）；RG006 仍非放宽（kind=answer、含 40、未问字段 forbidden 保留）、RG002/RG003 PASS、RG005/RG007 不变、gate 无新 hard；当前多轮 replay 合法源仍逐轮。
4. **测试/回归（§11A）**：本包 1 次；`backend/tests/evaluation` 1 次；全量 `backend/tests` 1 次（0 failed/0 error；内存 <2GB 轮询；既有 flake 隔离复跑 1 次；pytest 前 `$env:MKTKB_PROJECT_TOTAL_LIMIT_CNY="20.0"`）；b0/badcase local+gate 对 P0；regression 当前 vs 父提交；无 skip/xfail/删断言/新依赖。
5. **合规/形式**：`git show 1ffd57a` 6 文件均允许路径（runner.py/测试/report/证据 02/03/04）；无 fixtures/业务代码/API/intent/dataset/gate/账本改动；report 约 140 行 > 80 预算（记非阻塞观察）；证据仍 4 份（02/03/04 含 R1 段）；单 dev commit；零真实调用；未读 `.env`/Holdout。

## 输出与边界
- 写 `.claude\handoffs\T109-multiturn-runner\review-R2.md`（≤120 行；首行模型标注；含残余/NOT-RUN）。
- 证据 ≤4 份：`docs\reports\OBS-EVAL\P1\evidence\verify\T109-R2\`（建议 01-verdict.md、02-probe.py、03-probe-results.md、04-test-eval-runs.md）。
- 不改交付物；不 commit/push/切分支/stash/reset；不读 `.env`/Holdout；零真实模型/embedding/rerank/OCR；临时文件只放 `backend\.pytest-tmp\T109-R2\` 或 `$env:TEMP`；结束回复 ≤10 行摘要。
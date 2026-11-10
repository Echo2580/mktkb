角色：独立验收者（全新上下文），不是开发者，也不是项目经理。任务 **T105（D6 指代/字段错配）—— 返工 R1 后的复验 R2**。
模型：`wb / cn:deepseek-v4.1-flash / reasoning_effort=max`（review-R2.md 首行注明）。
工作目录：`D:\GPT项目\市场部AI知识库`；分支 `p1/fix-retrieval`。
**你的任务是证伪，不是帮它说话；不引用开发 report/上一轮 review 作 PASS 证据。**
（上一轮已 PASS 的条款按 §11A「返工后定向复验」沿用，不必全部重跑；但 FAIL 项 B1/B2 与受影响测试必须独立复跑。）

## 必读（按序）
1. `.claude\handoffs\T105-anaphora-field\rework-R1.md`（**§5 PM 裁定**：接受 B2 收窄方向 + 三条约束，尤其 §5-3 证伪条件）
2. 同目录 `handoff.md`（§6 验收标准）、`review.md`（上一轮 FAIL 依据与基线数据）、`report.md`（只当线索，注意 R1 段）
3. `docs\reports\OBS-EVAL\P1\evidence\verify\T105\`（上一轮 01/03/04；可复用其夹具思路与基线对照方法）
4. 复跑前：`git status --short` 必须 clean；`git log --oneline -8` 核对 R1 交付 commit 与 PM 簿记 commit；`git diff 2306aaa..HEAD -- backend fixtures` 应仅为 R1 允许改动。

## 定向复验（重点，全部独立复跑）
1. **范围/合规**：R1 交付必须为 **1 个新 commit**（在 `2306aaa` 之后、PM 簿记之上）；`git show --stat` 仅允许路径（`query.py`、`answer.py`、本包 2 测试、`report.md`、证据 03/04）；无第二同义 dev commit；PM commit 只动 `.claude/handoffs/**` + 验收证据；无 skip/xfail/删断言/越界文件；未改 `conversations/`、`intent.py`、fixtures/b0/badcase/gate。
2. **B1（上轮 FAIL）独立 HTTP 探针**：同一 conversation `把宣传海报都列出来`（12 条/page1）→ `那个海报的第2页` 必须 `answer` + `pagination={page:2,total:12,returned:2,...}`（对齐 `17c0e63` 基线）；单独 `第2页` 仍 page2；显式「列出来/全部」保持分页；无上文 `那个海报呢` 仍澄清（核心不回退）。**自己写探针，不复用开发测试**。
3. **B2（上轮 FAIL）独立探针**：上文 `城西店的宣传海报在哪里？` → `那个海报的打印材质呢`/`那个海报的陈列要求呢`/`那个海报的规格型号呢`：①不得出现多条记录×全字段倾倒（如 8 次「标识：」/未问值）；②含记录字段的（规格型号等）只答该字段（~29 字级）；③非台账字段返回 not_found 且 0 泄露；④**PM 裁定 §5-2/§5-3 证伪**：(a) 不得扩大拦截——政策/法规/正文类追问、纯指代追问、分页/枚举行为维持上轮 PASS（用自己探针 + T101/T102 定向核）；(b) 核查是否把「基线本可从正文回答的问题」压成 `not_found`（行为回退）——用现有语料/自建文档夹具探针核验并如实记录；行为回退则 B2 判 FAIL，仅是保守化则记残余。
4. **测试/评测（§11A：FAIL 项 + 受影响测试 + 全量 1 次）**：本包 2 文件 1 次；`backend/tests/rag` 1 次；`backend/tests/integration` 1 次（既有 flake 隔离复跑 1 次）；`backend/tests/observability` 1 次；全量 `backend/tests` 1 次（0 failed/0 error；内存 <2GB 先轮询；同一时间只跑一套 pytest）；b0/badcase local run+gate 对 `var/eval/runs/p0-b0`/`p0-badcase`（`case_diffs=0`、gate hard `[]`）；regression 当前 vs `17c0e63` 基线逐例（仅 RG006 fail→pass；RG005/RG007 失败集不变；gate 无新增 hard 名）。
5. **report/证据**：report R1 段是否如实披露 B2 收窄（不先走正文/legacy）与 P2 残余、是否修正上轮不实表述；证据仍 ≤4 份且 03/04 含 R1 段；报告数字与你的复跑是否一致（差异如实记录）。

## 输出与边界
- 写 `.claude\handoffs\T105-anaphora-field\review-R2.md`（≤120 行；首行模型标注；逐项 PASS/FAIL/BLOCKED/NOT-RUN + 命令或 `文件:行`；含残余与 NOT-RUN）。
- 证据 ≤4 份：`docs\reports\OBS-EVAL\P1\evidence\verify\T105-R2\`（建议 01-verdict.md、02-probe.py、03-probe-results.md、04-test-eval-runs.md）。
- 不改交付物（backend/**、fixtures/**、`docs\...\evidence\T105/**`、handoff/report）；不 commit/push/切分支/stash/reset；不读 `.env`；不读 Holdout；零真实模型/embedding/rerank/OCR；临时文件只放 `backend\.pytest-tmp\T105-R2\` 或 `$env:TEMP`。
- 结束时回复 ≤10 行结论摘要（结论 + 各复跑数字 + FAIL/NOT-RUN 清单）。

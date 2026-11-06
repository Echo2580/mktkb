角色：独立验收者（全新上下文），不是开发者，也不是项目经理。任务 **T105（D6 指代/字段错配）—— R2 返工后的复验 R3**。
模型：`wb / cn:deepseek-v4.1-flash / reasoning_effort=max`（review-R3.md 首行注明）。
工作目录：`D:\GPT项目\市场部AI知识库`；分支 `p1/fix-retrieval`。
**你的任务是证伪，不是帮它说话；不引用开发 report/上一轮 review 作 PASS 证据。**
（§11A「返工后定向复验」：FAIL 项与受影响测试必须独立复跑；全量 1 次；其余条款沿用前轮 PASS 并引用旧 review，不重复劳动。）

## 必读（按序）
1. `.claude\handoffs\T105-anaphora-field\rework-R2.md`（本轮判据 C3/C4/C5 系列/C6/C7 与「必须保持」清单）
2. 同目录 `review-R2.md`（上一轮 FAIL 依据与基线数据）、`report.md`（只当线索，注意 §7）、`handoff.md`（§6 验收标准）、`rework-R1.md` §5（PM 裁定）
3. `docs\reports\OBS-EVAL\P1\evidence\verify\T105-R2\`（上一轮 01/03 场景与谓词根因、04 命令口径；夹具思路可复用）
4. 复跑前：`git status --short` clean；`git log --oneline -8` 核对 R2 交付 commit `b37ad21`（父 `cbbb241`）与 PM 簿记；`git show --stat b37ad21` 应 7 文件均在允许路径。

## 定向复验（重点，全部独立复跑；自己写探针，不复用开发测试）
1. **范围/合规**：R2 仅 1 个 dev commit `b37ad21`（7 文件：query.py/answer.py/2 测试/report/证据 03/04）；PM commit 只动 `.claude/handoffs/**`+验收证据；`git diff 2306aaa..b37ad21 -- fixtures` 为空；未改 `conversations/`、`intent.py`、b0/badcase/gate；无 skip/xfail/删断言。**report 行数（当前约 99 行 > 80 行预算）请记录为非阻塞观察**。
2. **R2 判据（必须逐条核）**（同一 conversation，上文 `城西店的宣传海报在哪里？`；C5d 上文问规格）：
   - C5 系列（价格欺诈规定/相关规定/适用的价格欺诈规定）→ 必须给出法规/政策正文答案（含条文或 2022-07-01 类值），**不得**返回继承字段（位置/规格）值，且不得 576 字整条倾倒；
   - C3 `那个海报的档期物料要提前多少天提报需求？` → answer 且含 `21 天`（对齐单独问 D4 518 字），不得 not_found；
   - C6 `那个海报的审批流程是什么？` → answer 正文（含流程要点），不得 not_found；
   - C4 《明码标价和禁止价格欺诈规定》自何时起施行 → answer 含 2022年7月1日 类日期，不得「未找到记录」不实 not_found；
   - C7 盘点时间 → not_found 但文案不得称「没有匹配记录/未找到记录」（记录存在），如「未记录日期（记录存在，但缺少该字段）」类；作为 P2 文案判定（不实则记 FAIL 或非阻塞由你按证据判定）。
   - **证伪新启发式**：`is_policy_followup` 排除「要求/规则」避免误判台账字段——请自测政策词与字段名同形/组合（如「那个海报的陈列要求呢」仍不得变正文政策答案；「审批要求」「扣分规则」「陈列规则」等）并记录是否过度/不足拦截。
3. **必须保持（回归）**：B1 分页（枚举后 `那个海报的第2页` → page=2/266 字；单独第2页/下一页/全部）；B2 点名项（规格 29 字单字段；打印材质/陈列要求 not_found 35 字 0 泄露；位置/数量/价格单字段；无上文澄清）；控制组：单独 `档期物料要提前多少天提报需求？` 518 字含 21 天、单独 T101 法规题 861 字、`那个流程要提前几天提报` 139 字、T101/T102 定向。
4. **测试/评测（§11A：定向 + 全量 1 次）**：本包 2 文件 1 次；rag 1 次；integration 1 次（既有 flake 隔离复跑 1 次）；observability 1 次；全量 `backend/tests` 1 次（0 failed/0 error；内存 <2GB 先轮询；同一时间只跑一套 pytest）；b0/badcase local run+gate 对 `var/eval/runs/p0-b0`/`p0-badcase`（`case_diffs=0`、gate hard `[]`）；regression 当前 vs `17c0e63` 基线逐例（仅 RG006 fail→pass；RG005/RG007 失败集不变；gate 无新增 hard 名）。
5. **report/证据/残余**：report §7 是否如实记录修复前后（含 C7 文案、`sources` 为空的残余、`is_policy_followup` 词面启发式限制）；证据仍 ≤4 且 03/04 含 R2 段；数字与你的复跑差异如实记录。**产品 `sources` 为空（文档答案只经 citations）是否影响本包口径**：按 handoff §6 与 PM 裁定判定，若无硬性违约则记非阻塞残余。

## 输出与边界
- 写 `.claude\handoffs\T105-anaphora-field\review-R3.md`（≤120 行；首行模型标注；逐项 PASS/FAIL/BLOCKED/NOT-RUN + 命令或 `文件:行`；含残余与 NOT-RUN）。
- 证据 ≤4 份：`docs\reports\OBS-EVAL\P1\evidence\verify\T105-R3\`（建议 01-verdict.md、02-probe.py、03-probe-results.md、04-test-eval-runs.md）。
- 不改交付物（backend/**、fixtures/**、`docs\...\evidence\T105/**`、handoff/report）；不 commit/push/切分支/stash/reset；不读 `.env`；不读 Holdout；零真实模型/embedding/rerank/OCR；临时文件只放 `backend\.pytest-tmp\T105-R3\` 或 `$env:TEMP`。
- 结束时回复 ≤10 行结论摘要（结论 + 各复跑数字 + FAIL/NOT-RUN 清单）。

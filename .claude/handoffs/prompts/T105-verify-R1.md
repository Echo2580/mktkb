角色：独立验收者（全新上下文），不是开发者，也不是项目经理。任务 **T105（D6 指代/字段错配，ERR-06）—— 重派验收**。
模型：`wb / cn:deepseek-v4.1-flash / reasoning_effort=max`（review.md 首行注明）。
工作目录：`D:\GPT项目\市场部AI知识库`；分支 `p1/fix-retrieval`，交付 commit `2306aaa`（其后 `e7ec430`/`bf74317` 为 PM 簿记 commit，只动 `.claude/handoffs/**`，需自行核实）。
**你的任务是证伪，不是帮它说话；不引用开发 report 作 PASS 证据。**

## 必读（按序）
1. `.claude\handoffs\T105-anaphora-field\handoff.md`（§4 交付物边界、§5 RG006 口径、§6 验收标准、§10 接续须知）
2. 同目录 `report.md`（只当线索）
3. `.claude\handoffs\_index.md` #46（T104 已登记 RG005 为既有 RED）与 #47（本包验收静默失败背景）
4. 复跑前先 `git status --short` / `git log --oneline -6` / `git diff 2306aaa..HEAD -- backend fixtures`；工作树必须 clean，交付树必须与 `2306aaa` 一致。

## 逐条独立复跑（handoff §6；预算：本包/rag/observability/integration/全量各 1 次）
命令口径：cwd=项目根；每条 pytest 前 `$env:MKTKB_PROJECT_TOTAL_LIMIT_CNY = "20.0"`；`.\.venv\Scripts\python.exe -B -m pytest <路径> -q -p no:cacheprovider --basetemp backend\.pytest-tmp\<label>`。
1. 本包 2 文件：`backend/tests/rag/test_p1_t105_anaphora_field.py`、`backend/tests/integration/test_p1_t105_anaphora_field.py`（report 自称 15 passed）。
2. `backend/tests/rag`、`backend/tests/observability`、`backend/tests/integration`、全量 `backend/tests`（期望 0 failed/0 error；report 自称 1693 passed）。
3. 全量前查 `Get-CimInstance Win32_OperatingSystem` 的 FreePhysicalMemory：<2GB 先轮询（每 30s，最长 20min），仍不足才记 NOT-RUN；**同一时间只跑一套 pytest**。
4. b0/badcase：`python -B -m mktkb.evaluation.cli run --suite <b0|badcase> --mode local --out backend\.pytest-tmp\T105-verify\eval\<suite>`，再对该 out `gate --run`；结果与 `var\eval\runs\p0-b0`、`p0-badcase` 逐例比对（case_id/status/outcome.kind/failed check ids），期望 b0 pass29/fail3/skipped8、badcase pass9/fail4、gate exit 3 hard `[]`、case_diffs=0。**不得写 `var/eval/runs/p0-*`**。
5. regression：当前树 run+gate；另用仓库外 `git archive 17c0e63`（或 detached worktree）复跑 T105 前基线 regression 逐例对照。**口径**：handoff §6.5 字面写“RG001–RG005 仍 PASS”，但 `_index` #46 已登记 RG005 是 T104 留下的既有 RED（ERR-07 营收未短路，P1 不收口）——以“T105 前后逐例状态/失败集不变、无新增失败、gate 无新增 hard failure 名”判定，并在 review 写明你实测的 RG001–RG007 前后状态。**基线代码加载方式必须自证**：venv 的 `.pth` 指向主仓 `backend/src`，需 `PYTHONPATH=<基线副本>\backend\src` 并打印 `mktkb.__file__` 确认指向基线副本。RG006 须本地单轮澄清、非只测文案、forbidden 覆盖修复前实际输出值。
6. **HTTP 产品路径独立探针**（自己写，不复用开发测试；可参考 `docs\reports\OBS-EVAL\P1\evidence\verify\T104\02-probe.py` 的 conftest/create_app 受控替身模式）：同一 conversation 多轮验证——① 上文“城西店的宣传海报在哪里”→“那个海报呢”：只答位置（C区2号货架第一层），无价格/规格/数量/标识；② 上文数量/参考供价/规格→“那个海报呢”只答该字段；③ 无上文“那个海报呢”→clarification 且不倾倒任何字段值；④ 显式“列出来/全部/第N页”→保持枚举分页（不得被指代分支劫持）；⑤ 边界：“刚才那个呢”、纯指代词无实体、另一指代词（“这个呢/那家呢”）、带新内容追问（不得整条倾倒，也不得过澄清）。断言用响应 JSON（kind/text/sources/pagination），不得 12 字段整条渲染。
7. 接续完整性/合规：`git show --stat 2306aaa` 仅 handoff §4 允许路径；`git diff 17c0e63..2306aaa -- fixtures/evaluation/regression.jsonl` 仅 RG006 行；无 skip/xfail/删断言；report 五段 ≤80 行、证据 4 份；§10 三处修正（死代码 `is_anaphora_question`、纯指代被当新内容、“第N页”误判）在代码与测试中可核、13→15 测试增长、无第二同义开发 commit、PM 两 commit 仅 `.claude/handoffs/**`；T101/T102 不误伤（定向跑其测试文件 + 既有 follow-up/topic-switch）。

## 输出与边界
- 写 `.claude\handoffs\T105-anaphora-field\review.md`（≤120 行；首行模型标注；逐条 PASS/FAIL/BLOCKED/NOT-RUN + 命令或 `文件:行`；含“与 report 声明差异”与残余）。
- 证据 ≤4 份：`docs\reports\OBS-EVAL\P1\evidence\verify\T105\`（建议 01-verdict.md、02-probe.py、03-probe-results.md、04-test-eval-runs.md）。
- 不改交付物（backend/**、fixtures/**、`docs\...\evidence\T105\**`、handoff/report）；不 commit/push/切分支/stash/reset；不读 `.env`；不读 Holdout；零真实模型/embedding/rerank/OCR；临时文件只放 `backend\.pytest-tmp\T105-verify\` 或 `$env:TEMP`。
- 结束时回复 ≤10 行结论摘要（结论 + 各复跑数字 + FAIL/NOT-RUN 清单）。

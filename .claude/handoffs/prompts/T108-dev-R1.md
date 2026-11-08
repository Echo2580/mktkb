角色：开发助手（**返工轮 R1**），不是验收者。任务 **T108（Holdout 支持与防污染）R1 返工**。完整返工单：`.claude\handoffs\T108-holdout-support\rework-R1.md`。
模型：`wb / cn:deepseek-v4.1-flash / reasoning_effort=max`。
工作目录 `D:\GPT项目\市场部AI知识库`；分支 `p1/fix-retrieval`；当前 HEAD 含 PM 簿记；**T108 交付 `af08848`**；开工前 `git status --short` clean。

必读：`rework-R1.md`（**B1 F1 阻塞、B2 防污染、B3 from-run**）、同目录 `review.md`（F1/残余依据）、`report.md`、`handoff.md`（§0 PM 口径/§4 验收）、`verify/T108/01-verdict.md`、`03-probe-results.md`。

实现（最小改动，只改允许路径）：
- **B1**：`runner.py:1343-1358` `_assert_gold_unit_ids` 仅当 `case.expected_sources` 非空才要求 `gold.unit_ids`；负样例（`expected_sources=[]` + `relevant_units` 非空，含 `should_refuse=true`）不得 error；补合成测试（不 error、可评分），并保留"expected_sources 非空但 unit_ids 空仍 error"。
- **B2**：holdout 默认 run 复用非空 out 目录（或含 `cases.jsonl`/`holdout_audit.json`/`traces.sqlite3`）→ 明确拒绝（非零、清晰提示）；`--allow-holdout-details` 同样拒绝已存在 detail 文件的目录；补测试。
- **B3**：`run --suite holdout --mode local --from-run ...` → 明确错误/拒绝，不得静默忽略；补测试。
- 不改 `dataset.py/gate.py`（除非证明必要并 report 单列）；**不得读取真实 holdout 内容**（真实 30/30 由验收 R2 跑）；不改 fixtures/b0/badcase/regression/业务代码/API/intent/账本/GO；不读 `.env`；零真实调用；不 push/amend；无 skip/xfail/删断言。

验证（全部实跑）：本包测试 / `backend/tests/evaluation` / 全量 `backend/tests`（0 failed/0 error；内存<2GB 轮询；既有 flake 隔离复跑 1 次）/ b0+badcase 对 `var/eval/runs/p0-*`（`case_diffs=0`、hard `[]`）/ regression 对 `17c0e63`（仅 RG006 fail→pass、RG005/RG007 不变、无新 hard）。pytest 前 `$env:MKTKB_PROJECT_TOTAL_LIMIT_CNY="20.0"`；`.\.venv\Scripts\python.exe -B -m pytest <路径> -q -p no:cacheprovider --basetemp backend\.pytest-tmp\<label>`；同一时间只跑一套。

交付：1 个新 commit `p1/T108 R1 fix holdout refusal-case scoring + out-dir guard`（不 push/不 amend）；`report.md` 追加 R1 段（B1 修复前后、B2/B3 口径与测试、数字、残余；真实 30/30 由验收 R2 跑）；证据 03/04 追加 R1 段（不新增文件）；回复 ≤10 行摘要。

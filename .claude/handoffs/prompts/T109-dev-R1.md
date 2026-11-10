角色：开发助手（**返工轮 R1**），不是验收者。任务 **T109（多轮 turns runner）R1 返工**。完整返工单：`.claude\handoffs\T109-multiturn-runner\rework-R1.md`。
模型：`wb / cn:deepseek-v4.1-flash / reasoning_effort=max`。
工作目录 `D:\GPT项目\市场部AI知识库`；分支 `p1/fix-retrieval`；当前 HEAD 含 PM 簿记；**T109 交付 `703b7e0`**；开工前 `git status --short` clean。

必读：`rework-R1.md`（**B1 replay 静默单轮、R1–R3 收口**）、同目录 `review.md`（阻断依据）、`report.md`、`handoff.md`（§0 口径/§3 验收）。

实现（只改允许路径）：
- **B1（阻塞）**：`runner.py` replay 路径——`len(case.turns)>1` 且源行无 `turn_traces`（或源轮数<case 轮数）→ fail closed（行 `status=fail`/明确异常，`error.code=multi_turn_source_missing`/`multi_turn_source_incomplete`），**不得静默写单条 replay 并 pass**；补测试（源单轮 run+多轮 case；源多轮但轮数不足）。
- **R1**：中间轮 `kind=error/service_error`/Trace 不可读 → `error` 填 code + `turn n/N` 明细（与 report/docstring 一致）。
- **R2**：malformed/gold-error 的 multi-turn 行 `turns_executed` 记实际/应有轮数（非默认 1）。
- **R3**：replay 每轮 trace 的 question 使用各轮 question（源轮数据），不统一用末轮。
- 允许：`evaluation/runner.py`、`backend/tests/evaluation/`、`report.md`、证据 02/03/04 追加 R1 段。禁止：fixtures（RG006 不再改）、b0/badcase、业务代码/API/intent/dataset/gate 语义、账本/GO、`.env`/Holdout、真实调用、push/amend、skip/xfail/删断言。

验证（全部实跑）：本包测试 / `backend/tests/evaluation` / 全量 `backend/tests`（0 failed/0 error；内存<2GB 轮询；flake 隔离复跑 1 次；**pytest 前 `$env:MKTKB_PROJECT_TOTAL_LIMIT_CNY="20.0"`**）/ b0+badcase 对 `var/eval/runs/p0-*`（`case_diffs=0`、hard `[]`）/ regression 当前 vs 父提交（RG006 保持 T109 后期望、RG002/RG003 PASS、RG005/RG007 不变、无新 hard）/ replay 回归（单轮 replay 不变、多轮合法源逐轮）。命令口径：`.\.venv\Scripts\python.exe -B -m pytest <路径> -q -p no:cacheprovider --basetemp backend\.pytest-tmp\<label>`；同一时间只跑一套。

交付：1 个新 commit `p1/T109 R1 replay fail-closed for single-turn sources + error details`（不 push/不 amend）；report 追加 R1 段；证据 02/03/04 追加 R1 段（不新增文件）；回复 ≤10 行摘要。

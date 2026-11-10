# T108 返工单 R1（PM，2026-11-08 21:3x）

> 依据：独立验收 `review.md`（FAIL：F1 阻塞；六项防泄漏/CI/fail-closed/回归均 PASS；R1 残余含防污染隐患）+ `verify/T108/`。轮次 **R1/3**。
> 基线：T108 交付 `af08848`（父 `31143f2`）；本轮 **1 个新 commit**，**不 amend 历史**。
> 执行者：开发 subagent（`wb / cn:deepseek-v4.1-flash`，`reasoning_effort=max`）。PM 不写代码。

## 1. 必须修（阻塞）
### B1（F1）真实 holdout 3/30 合法拒答题不可评分
- 现象：真实默认 run `run --suite holdout --mode local --holdout-labels ...` exit 0、仅聚合，但 3/30 case `status=error`、`error.code=gold_unit_ids_missing`（7 pass/20 fail/3 error），仅 27/30 进指标分母。
- 定位：`backend/src/mktkb/evaluation/runner.py:1343-1358` 的 `_assert_gold_unit_ids` 在任意 ref 存在时都要求 `gold.unit_ids`（只来自 `expected_sources`）；`gold.py:230-241` 对 `expected_sources=[]` 返回 `unit_ids=()`。3 个 error case 均为 `should_refuse=true` + `expected_sources=[]` + `relevant_units` 非空（设计 §4 PM 口径允许负样例可用 `relevant_units`）。
- 期望：仅当 `case.expected_sources` 非空时要求 `gold.unit_ids`；负样例（`expected_sources=[]` 且 `relevant_units` 非空，含 `should_refuse=true`）不得 error，按既有拒答/kind/检索指标口径评分。
- 必须补测试：合成 case `expected_sources=[]` + `relevant_units` 非空 + `should_refuse=true` → 不 error、可评分；并保持既有 gold 断言测试不失效（`expected_sources` 非空但 unit_ids 空仍 error）。

## 2. 必须收口（防污染加固，阻塞）
### B2（review R1）复用 out 目录残留 detail 三件套
- 现象：默认 holdout run 复用已有 out 目录时不清理旧的 `cases.jsonl`/`holdout_audit.json`/`traces.sqlite3`；新目录验收通过，但旧详情可残留（gate 会拒绝但文件已落盘）。
- 期望：holdout **默认** run 若 out 目录已存在且非空（或含上述任一文件）→ 明确拒绝（非零、提示换目录/清理）；或写前删除 detail 三件套（二选一，report 写明）。`--allow-holdout-details` 也须拒绝已存在 detail 文件的目录（避免新旧混合，审计失真）。补测试。
### B3（review R3，低）holdout local 静默忽略 `--from-run`
- 期望：`run --suite holdout --mode local --from-run ...` → 明确错误（非零）或明确拒绝，不得静默忽略；补测试。

## 3. 允许修改范围
- `backend/src/mktkb/evaluation/runner.py`（B1/B2）、`backend/src/mktkb/evaluation/cli.py`（B2/B3 拒绝口径）、`backend/tests/evaluation/`（本包测试）、证据 `docs/reports/OBS-EVAL/P1/evidence/T108/03-run-gate.md`、`04-test-results.md` 追加 R1 段（不新增文件）、`report.md` 追加 R1 段并更正。
- 禁止：改 `dataset.py/gate.py` 既有契约（除非证明必要且在 report 单列；优先不改）、真实 holdout **内容**（不得读 labels 内容；只能用合成夹具；真实 30/30 由验收 R2 用 labels 路径跑）、fixtures/b0/badcase/regression、业务代码/API/intent、账本/GO、`.env`、真实模型调用、push/amend、skip/xfail/删断言。

## 4. 必跑
本包测试 / `backend/tests/evaluation` / 全量 `backend/tests`（0 failed/0 error；内存<2GB 轮询；既有 flake 隔离复跑 1 次）/ b0/badcase 对 P0（`case_diffs=0`、hard `[]`）/ regression 对 `17c0e63`（仅 RG006 fail→pass、RG005/RG007 不变、无新 hard）。命令口径同前；同一时间只跑一套 pytest。

## 5. 交付
- 1 个新 commit：`p1/T108 R1 fix holdout refusal-case scoring + out-dir guard`；不 push/不 amend。
- `report.md` 追加「R1 返工」段：B1 修复前后（合成用例 + 说明真实 30/30 由 R2 验收跑）、B2/B3 口径与测试、运行数字、残余；证据 03/04 追加 R1 段。
- 回复 ≤10 行摘要（commit、B1/B2/B3 证据、测试数字、偏离、风险）。

# T105 证据 03：测试与 local run/gate 前后对照

环境：Windows，仓库根 `D:\GPT项目\市场部AI知识库`，`.venv\Scripts\python.exe`（3.12.7）。
所有 pytest/评测均带 `MKTKB_PROJECT_TOTAL_LIMIT_CNY=20.0`、`-B`、offline；pytest 均 `-q -p no:cacheprovider --basetemp backend\.pytest-tmp\<label>`（cwd=仓库根，路径 `backend/tests/...`）。零真实模型 / embedding / rerank / OCR 调用。

## A. 测试

| # | 范围 | 命令（label） | 结果 |
| --- | --- | --- | --- |
| 1 | 本包（9 单测 + 6 HTTP） | `python -B -m pytest backend/tests/rag/test_p1_t105_anaphora_field.py backend/tests/integration/test_p1_t105_anaphora_field.py`（`t105b`） | **15 passed**，17.97s |
| 2 | `backend/tests/rag` | `... pytest backend/tests/rag`（`t105rag2`） | **335 passed**，45.05s |
| 3 | `backend/tests/observability` | `... pytest backend/tests/observability`（`t105obs`） | **255 passed**，37.95s |
| 4 | `backend/tests/integration` | `... pytest backend/tests/integration`（`t105int`） | **368 passed**，401.50s |
| 5 | 全量 `backend/tests`（最终树，含 RG006 收口） | `... pytest backend/tests`（`t105full2`） | **1693 passed**，437.48s，0 failed/0 error；运行前 `FreePhysicalMemory=5.10 GB` |

- 全量前按 ≥2GB 门槛检查（实测 3.12GB，无需轮询等待）；本轮 integration/全量均未出现既有 `test_g08_short_budget_cancels_inflight_model_call` flake，故无隔离复跑记录。
- 未使用 skip/xfail/删断言；新增测试不构造真实 provider，未读 `.env`/Holdout；无新增生产依赖。

## B. b0 / badcase local run + gate（修复前 → 修复后）

命令：`python -B -m mktkb.evaluation.cli run --suite <suite> --mode local --out backend\.pytest-tmp\t105-eval\after\<suite>`，随后 `gate --run <同上>`。
“修复前”为 P0 冻结 run（`var/eval/runs/p0-b0`、`p0-badcase`）；T101–T104 均已记录与其逐例 0 差异，故等同本包直接前态。

| suite | 修复前 run_id | 修复后 run_id | 修复前 | 修复后 | gate（前→后） | 逐例差异 |
| --- | --- | --- | --- | --- | --- | --- |
| b0 | `b0-local-20261105T090359232489Z-6e3eb84c` | `b0-local-20261106T002138228442Z-e4560569` | pass 29 / fail 3 / skipped_requires_ocr 8 | **pass 29 / fail 3 / skipped_requires_ocr 8** | exit 3，hard `[]` → exit 3，hard `[]` | **0** |
| badcase | `badcase-local-20261105T090409960294Z-f03d4b5f` | `badcase-local-20261106T002142276281Z-7a9b4bd5` | pass 9 / fail 4 | **pass 9 / fail 4** | exit 3，hard `[]` → exit 3，hard `[]` | **0** |

- 逐例比较口径 `(case_id, status, outcome.kind, failed check ids)`：b0/badcase 均 `case_diffs=0`；失败集仍为 b0 Q25/Q26/Q31、badcase N05/N06/N09/N11（与 P0 相同）。
- 原始 cases.jsonl 在 `backend\.pytest-tmp\t105-eval\after\<suite>`（临时产物，不入库）。

## C. regression local run + gate（仅 RG006 收口）

“修复前”= detached worktree `$TEMP\t105-baseline`（`17c0e63`，旧 fixtures）；“修复后”= 当前工作树（代码 + RG006 行）。

| 阶段 | run_id | 状态 | gate | 逐例 |
| --- | --- | --- | --- | --- |
| 修复前 | `regression-local-20261106T001846178302Z-e584b08e` | pass 4 / fail 3 | exit 1，hard `['security_leak']` | RG001–RG004 pass；RG005/RG006/RG007 fail |
| 仅代码（旧 fixtures） | `regression-local-20261106T002309312306Z-ef885fb2` | pass 5 / fail 2 | exit 3，hard `[]` | RG006 已 pass；RG005/RG007 不变 |
| 代码 + RG006 收口 | `regression-local-20261106T002613476709Z-2d004f00` | **pass 5 / fail 2** | **exit 3，hard `[]`** | 仅 RG006 fail→pass；RG005/RG007 失败 checks 不变（`kind_correct,refusal_expected`） |

- RG006 修复前实际：`kind=answer`，`根据资料，滨江店的宣传海报（标识：QF01）位于店内外侧，数量 40 张。`，失败 `value_forbidden,kind_correct`。
- RG006 修复后实际：`kind=clarification`，`请问要查询宣传海报的哪项信息？可指定位置、数量、规格、价格等。`，0 失败。
- 逐例差异：regression 仅 RG006 一行变化（`fail/answer/(kind_correct,value_forbidden)` → `pass/clarification/()`）；RG001–RG005/RG007 逐项不变。
- gate 的 hard 集合由 `['security_leak']` 收缩为 `[]`（RG006 不再输出 forbidden 值），无新增 hard failure 名称。

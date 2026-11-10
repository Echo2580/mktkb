# T105 独立复跑：测试 / 评测 / 合规（verify/T105/04）

环境：Windows；cwd=`D:\GPT项目\市场部AI知识库`；`.venv\Scripts\python.exe` 3.12.7；每条 pytest 前 `$env:MKTKB_PROJECT_TOTAL_LIMIT_CNY="20.0"`；命令统一 `… -B -m pytest <路径> -q -p no:cacheprovider --basetemp backend\.pytest-tmp\T105-verify\<label>`；`-B`/offline，无真实模型/embedding/rerank/OCR。全量前 `FreePhysicalMemory=3.02 GB`（≥2GB 门槛，未轮询等待）。

## A. 测试复跑

| # | 范围 | label | 结果 |
| --- | --- | --- | --- |
| 1 | 本包 2 文件（9 单测 + 6 HTTP） | `pkg` | **15 passed**，5.14s（首次调用因 `--basetemp` 父目录不存在在 setup 报 `FileNotFoundError`，创建父目录后重跑；失败调用未执行任何 test） |
| 2 | `backend/tests/rag` | `rag` | **335 passed**，21.44s |
| 3 | `backend/tests/observability` | `observability` | **255 passed**，15.96s |
| 4 | `backend/tests/integration` | `integration` | 368 collected：**367 passed，1 failed**，260.84s。失败为既有 flake `test_chat.py::test_g08_short_budget_cancels_inflight_model_call`（`len(facts["calls"])==0`）；隔离复跑该用例 **1 passed**（1.42s，label `flake-g08`）→ 判为 flake，非 T105 失败。report 声称单次 368 passed，本次未在单次运行复现（差异=该 flake）。 |
| 5 | 全量 `backend/tests` | `full` | **1693 passed，0 failed，0 error**，386.79s |
| 6 | T101/T102 定向（额外） | `t101-t102` | `test_p1_t101_vocab_context.py` + rag/integration `test_p1_t102_state_inheritance.py` + `test_query_state.py` + `test_s2b_intent_semantics.py`：**37 passed**，13.20s |

## B. b0 / badcase（local run + gate，当前树）

命令：`python -B -m mktkb.evaluation.cli run --suite <b0|badcase> --mode local --out backend\.pytest-tmp\T105-verify\eval\<suite>`，随后 `gate --run <同目录>`。未写 `var/eval/runs/p0-*`。

| suite | run_id | 状态计数 | gate | 与 P0 逐例 |
| --- | --- | --- | --- | --- |
| b0 | `b0-local-20261106T033419849337Z-3a060139` | pass 29 / fail 3 / skipped_requires_ocr 8 | exit 3，hard `[]` | `case_diffs=0`（40/40） |
| badcase | `badcase-local-20261106T033427613198Z-3ad632e2` | pass 9 / fail 4 | exit 3，hard `[]` | `case_diffs=0`（13/13） |

比较口径：`(case_id,status,outcome.kind,failed check ids)`，基线 `var/eval/runs/p0-b0`、`p0-badcase`。失败集与 P0 相同（b0 Q25/Q26/Q31；badcase N05/N06/N09/N11）。

## C. regression（当前树 vs T105 前基线 `17c0e63`）

- 基线代码加载自证：`git worktree add --detach $env:TEMP\t105-verify-baseline-wt 17c0e63`；运行时 `PYTHONPATH=$TEMP\t105-verify-baseline-wt\backend\src`、cwd=基线 worktree；`python -c "import mktkb; print(mktkb.__file__)"` 输出 `…\t105-verify-baseline-wt\backend\src\mktkb\__init__.py`（已确认不是主仓 `.pth` 指向的 `backend/src`）。
- 当前树：`regression-local-20261106T033502219410Z-adf7dc02`，pass 5 / fail 2（RG005/RG007），gate exit 3，hard `[]`。
- 基线：`regression-local-20261106T033638499288Z-4824c8be`，pass 4 / fail 3（RG005/RG006/RG007），gate exit 1，hard `['security_leak']`。
- 逐例差异：**仅 RG006** `fail/answer/(kind_correct,value_forbidden)` → `pass/clarification/()`；RG001-004 pass 不变；RG005/RG007 失败 checks 不变（`kind_correct,refusal_expected`）；gate hard 集合由 `['security_leak']` 收缩为 `[]`，无新增 hard 名称。
- RG006 实际：
  - 基线 `kind=answer`，文本 `根据资料，滨江店的宣传海报（标识：QF01）位于店内外侧，数量 40 张。`（泄露 4 个未问值）。
  - 当前 `kind=clarification`，`请问要查询宣传海报的哪项信息？可指定位置、数量、规格、价格等。`（0 泄露）。
  - fixture `forbidden_values=["店内外侧","40 张","QF01","滨江店"]` 覆盖基线实际输出的 4 个值；`expected_kind=clarification` 保持不变；不是“只测文案”。

## D. 合规/接续核查

| 检查 | 结果 |
| --- | --- |
| 工作树/分支 | 起始 `git status --short` 空；`p1/fix-retrieval`；HEAD `838fa54` |
| `git diff 2306aaa..HEAD -- backend fixtures` | 空（PM 3 个 commit `e7ec430`/`bf74317`/`838fa54` 均只动 `.claude/handoffs/**`） |
| `git show --stat 2306aaa` | 10 文件，均在 handoff §4 允许路径（query.py/answer.py/2 测试/RG006/4 证据/report） |
| `git diff 17c0e63..2306aaa -- fixtures/evaluation/regression.jsonl` | 仅 RG006 一行（+1/−1） |
| skip/xfail/删断言 | 新测试无 `skip/xfail/pytest.mark`；交付 diff 无删断言（answer.py 仅替换 import 行 1 行） |
| report | 42 行，五段（§1-§5）；`report.md:1` 有模型标注 |
| 证据 | `docs/reports/OBS-EVAL/P1/evidence/T105/` 恰 4 份 |
| §10 修正 1（死代码） | 全仓 `is_anaphora_question` 无命中 → 已删 |
| §10 修正 2（纯指代词） | `_anaphora_residual_terms` 过滤 `ANAPHORA_WORDS`；HTTP 探针 S10/S11（刚才/前面）均只答位置，基线为 `not_found` → 实测修复 |
| §10 修正 3（第 N 页） | 代码守卫存在（`query.py:334`、`answer.py:230`），但 query 层分支（`query.py:1272-1318`）先返回澄清；探针 S7 失败、基线 page 2 正常 → **未达，且回退** |
| 13→15 测试增长 | 交付树 15 条（9+6）可核；前序 13 条仅见 PM 记录与 `evidence 01:11`（8 单测+5 HTTP），git 无前序未提交状态，无法独立复核 |
| 单开发 commit | `git log 17c0e63..2306aaa --oneline` 只有 `2306aaa`；无第二同义开发 commit |
| T101/T102 | 定向 37 passed；全量 1693 passed（含上述文件） |
| 临时产物 | 仅在 `backend\.pytest-tmp\T105-verify\` 与 `$env:TEMP`（基线 worktree/探针副本）；未改交付物/未 commit/push/切分支；未读 `.env`/Holdout |

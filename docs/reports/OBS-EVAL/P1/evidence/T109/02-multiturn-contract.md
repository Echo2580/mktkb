# T109 证据 02：多轮契约与判定矩阵

## A. 判定矩阵（每条都有测试，`backend/tests/evaluation/test_multiturn_runner.py`）

| # | 场景 | 期望 | 实现口径 | 测试 |
| --- | --- | --- | --- | --- |
| 1 | 2 轮按序 + 同一 conversation | 末轮答出上文问过的字段 | 同一 `conversation_id`/`user_id` 连续 `ask` | `test_multi_turn_runs_in_order_and_inherits_conversation_state` |
| 2 | 对照：同一末轮问题单轮 | `clarification`（说明 #1 的答案来自继承） | `turns=()` 走单轮路径 | `test_multi_turn_inheritance_is_what_makes_the_last_turn_answerable` |
| 3 | 中间轮抛异常 | case fail，不伪造后续轮 | `turn_traces[-1].status=error`、`error.code=execution_error`、`turns_executed=失败轮次` | `test_intermediate_turn_error_fails_case` |
| 4 | 中间轮答案是 `error` 结局 | case fail，即使末轮 checks 全通过 | 轮级 error → verdict fail；`error={code:"answer_error", message:"turn n/N: …"}`；末轮 checks 仍记录 | `test_intermediate_turn_error_outcome_fails_case_even_if_last_turn_passes` |
| 5 | 末轮 checks fail | case fail | 末轮 `score_case` 决定 | `test_last_turn_checks_fail_fails_case` |
| 6 | 中间轮「若判分会 fail」 | case pass | 中间轮不判分 | `test_intermediate_turn_checks_do_not_decide_pass` |
| 7 | `turns` 空 / 单元素 | 与父提交一致（`turns_executed=1`、忽略 turns） | `_case_turn_questions` 返回空 → 单轮路径 | `test_single_turn_rows_keep_parent_behaviour[empty/single-entry]` |
| 8 | 逐轮 trace + `previous_trace_id` 串联 | 每轮可查、链上一轮、`trace_id`=末轮 | 每轮 `start_trace(previous_trace_id=…)` | 同 #1 |
| 9 | 多轮 replay | 逐轮 replay，不静默只跑首轮 | 每轮一条 replay provenance trace，链到源轮 trace，题面取该轮 question | `test_multi_turn_replay_replays_every_turn` |
| 10 | 轮级 error 的源 run replay | 复现 `fail`（不改判 `error`） | `_replay_expected_status` 读持久化 turn_traces | `test_multi_turn_replay_keeps_turn_error_verdict` |
| 11 | run 级标记 | manifest/declarations 正确且不进身份字段 | `multi_turn_case_count`、`multi_turn_turns_executed` | `test_run_marks_multi_turn_counts_in_manifest_and_summary` |
| 12 | turn 结构非法 | fail closed（`turn_question_missing`/`turn_role_unsupported`/`turn_invalid`）；不落默认 1 轮 | `_case_turn_questions` 显式拒绝；`turns_executed=0`、`turn_traces=[]` | `test_malformed_turns_fail_closed`、`test_non_mapping_turn_is_rejected_by_the_runner` |
| 13 | RG006 契约 | 多轮口径、非放宽 | fixture 逐字段断言 | `test_regression_rg006_is_multi_turn_after_pm_ruling` |
| 14 | 中间轮 Trace 不可读（R1） | case fail | `error={code:"trace_missing"\|"trace_error", message:"turn n/N: …"}` | `test_intermediate_turn_trace_unreadable_fails_with_turn_detail` |
| 15 | replay 源无 `turn_traces`（旧单轮产物，R1 B1） | fail closed，不写单条 replay | `error.code=multi_turn_source_missing`、`turns_executed=0`、`turn_traces=[]` | `test_replay_rejects_single_turn_source_for_multi_turn_case` |
| 16 | 源 `turn_traces` 少于 case 轮数（R1 B1） | fail closed，不补齐 | `error.code=multi_turn_source_incomplete` | `test_replay_rejects_source_with_too_few_turn_traces` |
| 17 | replay 逐轮题面（R1 R3） | 每轮用该轮 question | `_replay_traces(questions=case.turns)`；`question_hash`=local 对应轮 | 同 #9 |
| 18 | 多轮首轮前失败（R1 R2） | error 行不落默认 `1` | `turns_executed=0`、`turn_traces=[]` | `test_malformed_turns_fail_closed`、`test_gold_error_multi_turn_row_reports_zero_executed_turns` |

## B. 字段契约（`cases.jsonl`）

| 字段 | 单轮（父提交） | 本轮 | 说明 |
| --- | --- | --- | --- |
| `turns_executed` | 1 | 多轮=实际执行轮次（异常中断=已执行数；首轮前失败=0）；单轮=1 | R1 R2：不再默认 1；单轮值不变 |
| `multi_turn_claimed` | False | `len(turns) > 1` | 单轮仍 False（b0/badcase 逐例核对见证据 03） |
| `turn_traces` | 不存在 | 有序 `[{turn,trace_id,status}]` | **追加在行尾**；既有字段相对顺序不变（证据 03-C） |
| `trace_id` | 该轮 | 末轮 trace | 兼容既有消费方 |
| `previous_trace_id` | None（local） | None（local） | local 语义不变；replay 仍链到源行末轮 trace |
| `checks`/`metrics`/`outcome`/`gold`/`error` | — | 末轮口径 | 中间轮不写 outcome/checks |

`run_manifest.json` 新增 `multi_turn_case_count` / `multi_turn_turns_executed`（`from_dict` 缺失时默认 0，
旧产物可读；不在 `IDENTITY_FIELDS`）。`summary.declarations.execution` 多轮时 `mode="multi_turn"`，
并给 `multi_turn_case_count` / `multi_turn_turns_executed` / `multi_turn_error_case_ids`；
holdout 聚合 run 的 `multi_turn_error_case_ids` 由 `_redact_case_ids` 换成计数（防污染口径不变）。

## C. replay 口径细节

- 触发条件：源行 `turn_traces` 长度 > 1。单轮 case（含旧产物无该字段）→ 单条 replay 原样。
- 多轮 case 的源没有 `turn_traces`，或条数 != `len(case.turns)` → **fail closed**（R1 B1）：
  行 `status=fail`、`error.code=multi_turn_source_missing|multi_turn_source_incomplete`、
  `turns_executed=0`、`turn_traces=[]`；不写单条 replay、不伪造逐轮，`multi_turn_verified=False`。
- 逐轮 trace：`http_request_id=f"{run_id}:{case_id}:turnN"`，`previous_trace_id=源轮 trace_id`，
  `replayed=True`、`spans=[]`；题面为该轮 question（`question_hash` 与 local 对应轮一致，R1 R3）；
  只有末轮带 outcome（重评分后的 `EvalOutcome`）。
- 打分：只重算末轮（源产物只持久化了末轮 outcome），`_assert_same_score` 比对 checks/metrics/status；
  轮级 error 的 `fail` 由 `turn_traces[].status` 复现，不重算中间轮、不伪造中间轮结果。
- 源 run 已标记 `error`：按源行 status 原样复现（多轮为 `fail`，父单轮为 `error`），并逐轮写 trace。

## D. R1 返工（2026-11-09）

B1 修复前后（父提交 worktree 里的 regression run 作源；同一 replay 命令）：

| 行 | 修复前 | 修复后 |
| --- | --- | --- |
| RG002/RG003/RG006 | `pass`、`turns_executed=1`、`claimed=True`、`turn_traces` 1 条、`error=None`（静默首轮） | `fail`、`turns_executed=0`、`claimed=True`、`turn_traces=[]`、`error.code=multi_turn_source_missing` |
| 其余 4 条单轮行 | 不变 | 不变 |

- 实跑 run：修复前 `regression-replay-20261108T163916949493Z-13d79f03`，修复后
  `regression-replay-20261108T164217691206Z-b6e0e131`；修复后 `multi_turn_verified=False`、
  `multi_turn_error_case_ids=[RG002,RG003,RG006]`、`multi_turn_turns_executed=0`、gate hard `[]`。
- R1：轮级 `kind=error/service_error` → `answer_error`；Trace 缺失 → `trace_missing`；
  `record.status=error` → `trace_error`；message 带 `turn n/N`。
- R2：多轮首轮前失败（turns 非法 / gold 解析失败）→ `turns_executed=0`、`turn_traces=[]`。
- R3：逐轮题面取 `case.turns`；实查 replay turn1/2 的 `question_hash` 与 local 对应轮一致且两轮不同
  （修复前 turn1 hash == local 末轮 hash，正是验收指出的问题）。

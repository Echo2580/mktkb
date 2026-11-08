# T109 证据 02：多轮契约与判定矩阵

## A. 判定矩阵（每条都有测试，`backend/tests/evaluation/test_multiturn_runner.py`）

| # | 场景 | 期望 | 实现口径 | 测试 |
| --- | --- | --- | --- | --- |
| 1 | 2 轮按序 + 同一 conversation | 末轮答出上文问过的字段 | 同一 `conversation_id`/`user_id` 连续 `ask` | `test_multi_turn_runs_in_order_and_inherits_conversation_state` |
| 2 | 对照：同一末轮问题单轮 | `clarification`（说明 #1 的答案来自继承） | `turns=()` 走单轮路径 | `test_multi_turn_inheritance_is_what_makes_the_last_turn_answerable` |
| 3 | 中间轮抛异常 | case fail，不伪造后续轮 | `turn_traces[-1].status=error`、`error.code=execution_error`、`turns_executed=失败轮次` | `test_intermediate_turn_error_fails_case` |
| 4 | 中间轮答案是 `error` 结局 | case fail，即使末轮 checks 全通过 | 轮级 error → verdict fail；末轮 checks 仍记录 | `test_intermediate_turn_error_outcome_fails_case_even_if_last_turn_passes` |
| 5 | 末轮 checks fail | case fail | 末轮 `score_case` 决定 | `test_last_turn_checks_fail_fails_case` |
| 6 | 中间轮「若判分会 fail」 | case pass | 中间轮不判分 | `test_intermediate_turn_checks_do_not_decide_pass` |
| 7 | `turns` 空 / 单元素 | 与父提交一致（`turns_executed=1`、忽略 turns） | `_case_turn_questions` 返回空 → 单轮路径 | `test_single_turn_rows_keep_parent_behaviour[empty/single-entry]` |
| 8 | 逐轮 trace + `previous_trace_id` 串联 | 每轮可查、链上一轮、`trace_id`=末轮 | 每轮 `start_trace(previous_trace_id=…)` | 同 #1 |
| 9 | 多轮 replay | 逐轮 replay，不静默只跑首轮 | 每轮一条 replay provenance trace，链到源轮 trace | `test_multi_turn_replay_replays_every_turn` |
| 10 | 轮级 error 的源 run replay | 复现 `fail`（不改判 `error`） | `_replay_expected_status` 读持久化 turn_traces | `test_multi_turn_replay_keeps_turn_error_verdict` |
| 11 | run 级标记 | manifest/declarations 正确且不进身份字段 | `multi_turn_case_count`、`multi_turn_turns_executed` | `test_run_marks_multi_turn_counts_in_manifest_and_summary` |
| 12 | turn 结构非法 | fail closed（`turn_question_missing`/`turn_role_unsupported`/`turn_invalid`） | `_case_turn_questions` 显式拒绝 | `test_malformed_turns_fail_closed`、`test_non_mapping_turn_is_rejected_by_the_runner` |
| 13 | RG006 契约 | 多轮口径、非放宽 | fixture 逐字段断言 | `test_regression_rg006_is_multi_turn_after_pm_ruling` |

## B. 字段契约（`cases.jsonl`）

| 字段 | 单轮（父提交） | 本轮 | 说明 |
| --- | --- | --- | --- |
| `turns_executed` | 1 | 多轮=实际执行轮次；单轮=1 | 新增语义来自 T109；单轮值不变 |
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

- 触发条件：源行 `turn_traces` 长度 > 1。旧产物（P0/P1 T108 之前）没有该字段 → 单轮 replay 原样。
- 逐轮 trace：`http_request_id=f"{run_id}:{case_id}:turnN"`，`previous_trace_id=源轮 trace_id`，
  `replayed=True`、`spans=[]`；只有末轮带 outcome（重评分后的 `EvalOutcome`）。
- 打分：只重算末轮（源产物只持久化了末轮 outcome），`_assert_same_score` 比对 checks/metrics/status；
  轮级 error 的 `fail` 由 `turn_traces[].status` 复现，不重算中间轮、不伪造中间轮结果。
- 源 run 已标记 `error`：按源行 status 原样复现（多轮为 `fail`，父单轮为 `error`），并逐轮写 trace。

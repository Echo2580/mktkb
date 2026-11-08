# T109 report — 多轮 turns runner（P1 第 10 包）

模型：`wb / cn:deepseek-v4.1-flash / reasoning_effort=max`

## 1. 完成内容

- `runner.py`：`turns` ≥2 的 case 走多轮路径 `_local_multi_turn_row`（runner.py:903）——同一
  `conversation_id`/`user_id` 按序 `index.ask`，每轮 `start_trace(previous_trace_id=上一轮)`（:937），
  逐轮 `_annotate_trace_identity`；末轮 `score_case`，中间轮不判分。
- 判定：轮级 error = 答案 `kind∈{error,service_error}` / 执行异常 / Trace 不可读（`_turn_failed`，:889）；
  任一轮 error → 行 `status="fail"` + `error={code, message:"turn n/N: …"}`（:953）；末轮 checks 决定其余情形。
- 行字段：`_row_from_result`（:1614）/`_error_row`（:1654）新增 `turn_traces`（有序
  `{turn,trace_id,status}`，**追加在行尾**）与 `turns_executed`；`trace_id`=末轮 trace；
  `multi_turn_claimed = len(turns)>1`；`turns` 空/单元素走原单轮路径（`_case_turn_questions`:857 返回空）。
- replay：`_replay_traces`（:1114）源行为多轮时**逐轮**写 replay provenance trace（每轮链到源轮
  trace、只末轮带 outcome）；`_replay_expected_status`（:1275）从持久化 `turn_traces` 复现轮级 error
  的 `fail`；旧产物（无 `turn_traces`）保持父单轮 replay 行为。
- run 级标记：`RunManifest` 增 `multi_turn_case_count`/`multi_turn_turns_executed`（默认 0，不进
  `IDENTITY_FIELDS`；`_multi_turn_manifest_fields`:533）；`summary.declarations.execution` 按数据集
  判定 `mode=single_turn|multi_turn` 并给计数（`_declarations`:1902）；holdout 聚合多轮 error 名单走
  `_redact_case_ids` 换成计数。
- `fixtures/evaluation/regression.jsonl`：**仅 RG006 一行**按 PM 裁决更新（kind/value/forbidden/
  reference/notes），canonical 落盘且 `only_rg006_changed=['RG006']`。
- 测试：新增 `test_multiturn_runner.py` 15 条；`test_holdout_suite.py` 1 条按新契约同步（断言只加强）。

## 2. 验收自证（handoff §3）

1. 顺序 + 会话继承：`test_multi_turn_runs_in_order_and_inherits_conversation_state`（RG006 形态：
   turn1 问数量 → turn2「那个海报呢」→ 末轮只答 40）；对照组同问题单轮仍 `clarification`，证明答案来自继承。
2. 判定：中间轮异常→fail（`…intermediate_turn_error_fails_case`）、中间轮 `kind=error`→fail 且末轮
   checks 全通过仍 fail（`…error_outcome_fails_case_even_if_last_turn_passes`）、末轮 checks fail→fail、
   中间轮 checks 不决定通过、全通过→pass。
3. 逐轮 trace：`turn_traces` 逐轮 trace_id 在 store 可查、`previous_trace_id` 串联上一轮、
   行 `trace_id`=末轮；证据 03-C 为 regression run 的实查输出。
4. 单轮不变：b0/badcase 对 P0 **case_diffs=0/40、0/13**；对父提交代码整行逐字段一致（去 volatile）
   且键顺序不变，只多出行尾 `turn_traces`；`turns_executed=1`、`multi_turn_claimed=False` 不变。
5. replay：多轮逐轮 replay（`test_multi_turn_replay_replays_every_turn`：2 轮 2 条 replay trace、
   无源 trace 复用、status/checks/metrics 复现）；轮级 error 源 run 复现 `fail`。
6. regression：RG006 `pass/clarification`→`pass/answer`（两侧均 pass）；RG001–RG005/RG007 逐字段不变；
   gate 无新 hard（exit 3、hard `[]`、unknown 集合一致）。
7. 合规：只改允许路径、零真实调用、无 skip/xfail/新依赖、证据 4 份、report ≤80 行、单 commit。

## 3. 运行结果

| 范围 | label | 结果 |
| --- | --- | --- |
| 本包 | `t109-pkg-final` | 15 passed（7.43s） |
| `backend/tests/evaluation` | `t109-eval-final` | 388 passed / 0 failed / 0 error（84.42s） |
| 全量 `backend/tests` ×2 | `t109-full`、`t109-full2` | 1791 passed ×2（474.91s / 472.03s），峰值 428.5 MB |

- b0 `…ed5fe092`：pass 29/fail 3/skipped 8，gate exit 3 hard `[]`，对 `p0-b0` **case_diffs=0/40**；
  badcase `…8990c5bf`：pass 9/fail 4，gate exit 3 hard `[]`，对 `p0-badcase` **case_diffs=0/13**。
- regression 父提交 `ebfe956`（`…3610698c`）pass 5/fail 2、gate exit 3 hard `[]`；本轮（`…812686c9`）
  同样 pass 5/fail 2、gate exit 3 hard `[]`；`case_diffs=1` 仅 RG006。replay 实跑（`…aaf848ba`）：
  3 条多轮 case 各 2 条 replay trace（链源轮、spans=0），对 local `case_diffs=0/7`。
- RG006 before/after（实跑文本）：before（单轮）`clarification`「请问要查询宣传海报的哪项信息？…」；
  after（多轮）`answer`「根据资料，滨江店的宣传海报的数量：40张。」；fixture 变更见证据 03-E：
  `expected_kind` clarification→answer、`expected_values` []→["40"]、`forbidden_values`
  ["店内外侧","40 张","QF01","滨江店"]→["店内外侧","QF01"]（未问字段值保留，40 张改期望、滨江店为被问主体）。
- 全量两次连续全绿，未出现 T108 记录的时序 flake，未触发隔离复跑；内存 15 样本峰值 428.5 MB < 2 GB。
- 提交：单 commit `p1/T109 multi-turn turns runner`（sha/`--stat` 见交付回复；文件内不自引用）。

## 4. 偏离 / 未做

- `test_holdout_suite.py::test_multi_turn_turns_are_normalised_but_not_claimed` 改名为
  `…_normalised_and_executed`：它断言的是 T108「holdout 多轮按单轮执行」的限制，T109 必须推翻；
  旧两行断言换成 9 条（更强的等价断言 + 新增逐轮/trace 断言，未放松任何口径），属最小契约同步。
- 轮级**异常**的行 status 记 `fail`（不是父提交单轮的 `error`）：依据 handoff §3.2「中间轮 error→
  case fail」；同时保留 `error.code` 明细，gate 仍按 `bool(error)` 视作 error 行（fail-safe）。
- 中间轮逐轮 outcome/checks 不落库（既有 `cases.jsonl` 只存末轮），replay 只重放逐轮 trace 链 + 末轮评分，不伪造中间轮结果。
- 未改 `scorers.py`/`gold.py`（T110）、`gate_v0_1.json`（T112）、`corpus.py`、业务代码、前端。

## 5. 风险

- RG006 的 `forbidden_values` 移除了「滨江店」：turn1 明问滨江店、末轮答案复述该主体是产品现状；
  若后续产品改为不点名门店，应把它加回 forbidden（当前不阻断通过的前提是「只答数量」）。
- 多轮判定依赖「轮级 error」定义（error/service_error/异常/Trace 不可读）；新增失败 outcome kind 需同步 `_turn_failed`。
- replay 只能复现末轮评分；逐轮评分回放需先持久化逐轮 outcome（改 cases.jsonl 契约，属后续包）。
- `turns_executed` 在异常中断的行是**实际执行轮次**（可能 < len(turns)）；消费方需按 `turn_traces` 判断完整性。

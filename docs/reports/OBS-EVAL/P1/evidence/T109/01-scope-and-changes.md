# T109 证据 01：起点、输入与改动清单

## A. 起点

- 分支 `p1/fix-retrieval`，父提交 `ebfe956`（`chore(p1): T109 handoff + dev/verify prompts`）；
  开工前 `git status --short` 为空。
- 输入（按 handoff §必读顺序）：`.claude/handoffs/T109-multiturn-runner/handoff.md`；
  `2026-11-04-p1-design.md` §4（:57-78，多轮口径）；`2026-11-04-p1-task-breakdown.md` §T109；
  `backend/src/mktkb/evaluation/{runner,dataset,scorers}.py`；
  `fixtures/evaluation/regression.jsonl`（RG002/RG003/RG006 的 turns 与期望）。
- 探针（临时，不入库，`backend/.pytest-tmp/T109/`）：`probe_multiturn.py` 直接对 regression 索引按
  turns 顺序提问，确认父代码下「同一 conversation 逐轮 ask」的真实产物（RG006 turn1/turn2 均答
  `滨江店的宣传海报的数量：40张。`）；`probe_runner.py` 驱动 `run_suite` 验证多轮/单轮/replay 路径。

## B. 改动清单（只动 handoff §2 允许路径）

| 文件 | 性质 | 要点 |
| --- | --- | --- |
| `backend/src/mktkb/evaluation/runner.py` | 扩展 | 多轮执行/判定、逐轮 trace、行字段、replay 逐轮、manifest/declarations 标记 |
| `backend/tests/evaluation/test_multiturn_runner.py` | 新增 | 15 条：顺序与继承、判定 4 种、单轮不变、逐轮 trace、replay、run 标记、turn 校验、RG006 契约 |
| `backend/tests/evaluation/test_holdout_suite.py` | 最小同步 | 1 条（`test_multi_turn_turns_are_normalised_and_executed`）：T108「规范化但单轮」→ T109「逐轮执行」，断言只加强 |
| `fixtures/evaluation/regression.jsonl` | 仅 RG006 一行 | `expected_kind=answer`、`expected_values=["40"]`、`forbidden_values=["店内外侧","QF01"]`、`reference_answer`/`notes` 写多轮口径 |
| `docs/reports/OBS-EVAL/P1/evidence/T109/` | 新增 | 本目录 4 份证据 |
| `.claude/handoffs/T109-multiturn-runner/report.md` | 新增 | 五段 ≤80 行 |

## C. 运行时口径（runner.py）

- 多轮门槛：`len(case.turns) >= 2`（`_case_turn_questions`）；`turns` 为空或只有 1 轮 → 原单轮路径，
  执行 `case.question`、忽略 turns（与父提交一致）。
- 顺序执行：同一 `conversation_id=f"{run_id}:{case_id}"`、`user_id="eval"`，逐轮 `index.ask`；
  会话状态由 `RagQueryState` 自然继承（未新增任何会话语义）。
- 逐轮 trace：每轮 `start_trace(..., previous_trace_id=上一轮)`，`http_request_id` 带 `:turnN`；
  每轮 `_annotate_trace_identity` 写入 run/dataset/index/pipeline/config 绑定。
- 判定：末轮 `score_case(case, gold, outcome, trace_record)`；中间轮不判分。任一轮 error →
  行 `status="fail"`（`error` 保留 code+`turn n/N` 明细）；末轮 checks 决定其余情形。
  轮级 error 定义：答案 `kind ∈ {error, service_error}`、执行异常、或 Trace 不可读/状态 error。
- 行字段：新增 `turn_traces`（有序 `{turn, trace_id, status}`，追加在行尾）与 `turns_executed`
  （多轮=实际执行轮次，单轮=1）；`trace_id` 仍为末轮 trace；`multi_turn_claimed = len(turns) > 1`。
- replay：源行 `turn_traces` 长度 >1 时逐轮写 replay provenance trace（每轮 `previous_trace_id` 链到
  源轮 trace），只给末轮带 outcome；末轮 outcome 由源产物重评分，`turn_traces[].status` 沿用源行；
  轮级 error 的 fail 判定由 `_replay_expected_status` 从持久化 turn_traces 复现。旧产物（无
  `turn_traces`）走原单轮 replay，行为不变。
- run 级标记：`run_manifest.json` 增 `multi_turn_case_count` / `multi_turn_turns_executed`（默认 0，
  不进 `IDENTITY_FIELDS`）；`summary.declarations.execution` 按数据集判定 `mode=single_turn|multi_turn`。

## D. 未做 / 明确不在本包

- 未改 `conversations/`、`intent.py`、`rag/`、业务 API、前端、`gate_v0_1.json`、账本/GO、
  `fixtures/evaluation/{b0,badcase}.jsonl`、其它 regression 行。
- 未改 `scorers.py` / `gold.py`（T110 范围）；未新增依赖；无 skip/xfail/删断言。
- 未运行任何真实 provider 调用（`provider_mode="offline"`，local/replay 均零真实调用）。
- 逐轮 outcome 不落库（既有 `cases.jsonl` 只存末轮 outcome）：replay 因此不重放中间轮结果，
  只重放逐轮 trace 链 + 末轮评分。

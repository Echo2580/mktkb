# T109 report — 多轮 turns runner（P1 第 10 包）

模型：`wb / cn:deepseek-v4.1-flash / reasoning_effort=max`

## 1. 完成内容

- `runner.py`：`turns` ≥2 的 case 走多轮路径 `_local_multi_turn_row`（runner.py:903）——同一
  `conversation_id`/`user_id` 按序 `index.ask`，每轮 `start_trace(previous_trace_id=上一轮)`（:937），
  逐轮 `_annotate_trace_identity`；末轮 `score_case`，中间轮不判分。
- 判定：轮级 error = 答案 `kind∈{error,service_error}` / 执行异常 / Trace 不可读（`_turn_failed`，:889）；
  任一轮 error → 行 `status="fail"` + `error={code, message:"turn n/N: …"}`（R1 起轮级
  `kind=error` 记 `answer_error`、Trace 缺失/异常记 `trace_missing`/`trace_error`，不再只留在
  `turn_traces[].status`）；末轮 checks 决定其余情形。
- 行字段：`_row_from_result`（:1614）/`_error_row`（:1654）新增 `turn_traces`（有序
  `{turn,trace_id,status}`，**追加在行尾**）与 `turns_executed`；`trace_id`=末轮 trace；
  `multi_turn_claimed = len(turns)>1`；`turns` 空/单元素走原单轮路径（`_case_turn_questions`:857 返回空）。
  R1/R2：多轮 case **首轮执行前**失败（turns 非法/gold 解析失败）记 `turns_executed=0`、
  `turn_traces=[]`（不落默认 1，不伪造未执行的轮次）。
- replay：`_replay_traces`（:1114）源行为多轮时**逐轮**写 replay provenance trace（每轮链到源轮
  trace、题面取该轮 question，只末轮带 outcome）；`_replay_expected_status`（:1275）从持久化
  `turn_traces` 复现轮级 error 的 `fail`。单轮/旧产物的**单轮** replay 保持父口径；多轮 case 的
  源行无 `turn_traces` 或轮数不足 → **fail closed**（`multi_turn_source_missing`/
  `multi_turn_source_incomplete`，不写单条 replay；R1 B1）。
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
   无源 trace 复用、status/checks/metrics 复现、逐轮 `question_hash` 与 local 对应轮一致）；
   轮级 error 源 run 复现 `fail`；源无 `turn_traces`/轮数不足 → fail closed（R1 B1 两条测试）。
6. regression：RG006 `pass/clarification`→`pass/answer`（两侧均 pass）；RG001–RG005/RG007 逐字段不变；
   gate 无新 hard（exit 3、hard `[]`、unknown 集合一致）。
7. 合规：只改允许路径、零真实调用、无 skip/xfail/新依赖、证据 4 份（R1 只追加、不新增文件）、
   单 commit；report §1–§5 为首轮正文，§6 按 R1 返工单追加（原「≤80 行」只覆盖首轮交付）。

## 3. 运行结果

| 范围 | label | 结果 |
| --- | --- | --- |
| 本包 | `t109r1-pkg2` | **19 passed**（9.49s） |
| `backend/tests/evaluation` | `t109r1-eval1` | **392 passed / 0 failed / 0 error**（85.86s） |
| 全量 `backend/tests` ×2 | `t109r1-full1`、`t109r1-full2` | **1795 passed ×2**（448.68s / 451.82s），峰值 **460.2 MB** |

- b0 `…309fccaa`：pass 29/fail 3/skipped 8，gate exit 3 hard `[]`，对 `p0-b0` **case_diffs=0/40**
  （对 T109 交付 run 整行语义投影 0/40）；badcase `…da79b966`：pass 9/fail 4，gate exit 3 hard `[]`，
  对 `p0-badcase` **case_diffs=0/13**（对 T109 交付 run 0/13）。
- regression 父提交 `ebfe956`（`…3610698c`）pass 5/fail 2、gate exit 3 hard `[]`；R1 本轮
  （`…048e1c7b`）同样 pass 5/fail 2、gate exit 3 hard `[]`；`case_diffs=1` 仅 RG006。replay 实跑
  （`…a2a19936`）：3 条多轮 case 各 2 条 replay trace（链源轮、spans=0、逐轮题面），对 local
  `case_diffs=0/7`。
- RG006 before/after（实跑文本）：before（单轮）`clarification`「请问要查询宣传海报的哪项信息？…」；
  after（多轮，T109 起不变）`answer`「根据资料，滨江店的宣传海报的数量：40张。」；fixture 变更见证据 03-E。
- 全量两次连续全绿，未出现 T108 记录的时序 flake，未触发隔离复跑；full2 连续 52 样本/454s 峰值
  **460.2 MB**（full1 采样峰值 511.3 MB）< 2 GB。
- 提交：单 commit `p1/T109 R1 replay fail-closed for single-turn sources + error details`
  （sha/`--stat` 见交付回复；文件内不自引用）。

## 4. 偏离 / 未做

- `test_holdout_suite.py::test_multi_turn_turns_are_normalised_but_not_claimed` 改名为
  `…_normalised_and_executed`：它断言的是 T108「holdout 多轮按单轮执行」的限制，T109 必须推翻；
  旧两行断言换成 9 条（更强的等价断言 + 新增逐轮/trace 断言，未放松任何口径），属最小契约同步。
- 轮级**异常**的行 status 记 `fail`（不是父提交单轮的 `error`）：依据 handoff §3.2「中间轮 error→
  case fail」；同时保留 `error.code` 明细，gate 仍按 `bool(error)` 视作 error 行（fail-safe）。
- 中间轮逐轮 outcome/checks 不落库（既有 `cases.jsonl` 只存末轮），replay 只重放逐轮 trace 链 + 末轮评分，不伪造中间轮结果。
- R1 契约同步（非弱化）：`test_intermediate_turn_error_outcome_fails_case_even_if_last_turn_passes`
  的 `error is None` 改为断言新的 `{code: answer_error, message: turn 1/2: …}`（原先断言的正是
  验收指出的缺陷）；`test_malformed_turns_fail_closed` 的 `turns_executed == 1` 改为 `0` +
  `turn_traces == []`（R2 口径）。本包测试 15→19 条，未删断言、未 skip/xfail。
- 未改 `scorers.py`/`gold.py`（T110）、`gate_v0_1.json`（T112）、`corpus.py`、业务代码、前端。

## 5. 风险

- RG006 的 `forbidden_values` 移除了「滨江店」：turn1 明问滨江店、末轮答案复述该主体是产品现状；
  若后续产品改为不点名门店，应把它加回 forbidden（当前不阻断通过的前提是「只答数量」）。
- 多轮判定依赖「轮级 error」定义（error/service_error/异常/Trace 不可读）；新增失败 outcome kind 需同步 `_turn_failed`。
- replay 只能复现末轮评分；逐轮评分回放需先持久化逐轮 outcome（改 cases.jsonl 契约，属后续包）。
- `turns_executed`：异常中断 = 实际执行轮次（可能 < len(turns)）；首轮前失败（turns/gold）= 0 且
  `turn_traces=[]`，消费方需按 `turn_traces` 判断完整性（0 不是「跑了 1 轮」）。多轮行没有任何
  逐轮证据时 `multi_turn_verified=False`（fail-safe）。
- 多轮 case 的旧源 run（T109 前产物）现在 replay 会整体 fail closed（RG002/RG003/RG006 均如此）；
  如需回放旧产物，须先用 T109 代码重跑 local run（本包有意选择「拒绝」而不是猜逐轮结果）。

## 6. R1 返工（2026-11-09，依据 `review.md` B1 + R1–R3）

### 6.1 B1 replay fail closed（修复前后复现）

父提交 `ebfe956` 的 worktree（`backend\.pytest-tmp\T109-verify\base`）里已有父代码跑出的
regression run（行无 `turn_traces`）；同一命令分别用修复前/后代码 replay：

```powershell
.venv\Scripts\python.exe -B tools\rag_eval.py run --suite regression --mode replay `
  --from-run backend\.pytest-tmp\T109-verify\base\backend\.pytest-tmp\T109-verify\eval\regression-parent `
  --dataset backend\.pytest-tmp\T109-verify\base\fixtures\evaluation\regression.jsonl `
  --out backend\.pytest-tmp\T109-R1\eval\<before|after>-parent-replay
```

| 行 | 修复前（`…13d79f03`） | 修复后（`…b6e0e131`） |
| --- | --- | --- |
| RG002/RG003/RG006 | `pass`、`turns_executed=1`、`claimed=True`、`turn_traces` 1 条、`error=None`（静默首轮） | `fail`、`turns_executed=0`、`claimed=True`、`turn_traces=[]`、`error.code=multi_turn_source_missing` |

- 其余 RG001/RG004/RG005/RG007 前后一致；修复后 `multi_turn_verified=False`、
  `multi_turn_error_case_ids=[RG002,RG003,RG006]`、gate exit 3 hard `[]`（不 crash）。
- 守卫 `_assert_replay_turn_sources`：源轮数 < case 轮数 → `multi_turn_source_incomplete`；
  在写行前拒绝，不调用 `_replay_traces`（不写单条 replay、不伪造逐轮）。
- 测试：`test_replay_rejects_single_turn_source_for_multi_turn_case`、
  `test_replay_rejects_source_with_too_few_turn_traces`（改写源 `cases.jsonl` 模拟旧产物/缺轮）。

### 6.2 R1–R3 收口

- R1：轮级 `kind=error/service_error` → `error={code:"answer_error", message:"turn n/N: …"}`；
  Trace 缺失/`status=error` → `trace_missing`/`trace_error`；case 仍 `fail`，末轮 checks 照常记录。
- R2：多轮 case 首轮前失败（turns 非法/gold 解析失败）记 `turns_executed=0`、`turn_traces=[]`；
  `_error_row` 默认值按 `len(turns)>1` 区分，单轮仍 1（b0/badcase 整行语义投影 0 diff）。
- R3：`_replay_traces` 逐轮题面取 `case.turns` 对应轮；实查 RG002/RG003/RG006 replay turn1/2 的
  `question_hash` 与 local 对应轮一致且两轮不同（修复前 turn1 hash == local 末轮 hash）。

### 6.3 回归数字（全部实跑）

- 本包 19 / `backend/tests/evaluation` 392 / 全量 1795×2；full2 连续 52 样本/454s 峰值 460.2 MB。
- b0/badcase：对 P0 `case_diffs=0/40、0/13`、gate hard `[]`；单轮 replay 修复前/后整行语义投影 0/40。
- regression：仅 RG006 变化（`pass/clarification`→`pass/answer`）；RG002/RG003 pass、RG005/RG007 fail 不变；gate hard `[]`。
- replay：合法多轮源逐轮 2 条、`case_diffs=0/7`；单轮 replay 0/40 不变。
- 残余：旧多轮源 run 一律 fail closed（不猜逐轮结果）；中间轮 outcome 仍不落库；
  首轮前失败的 `turn_traces=[]` 行只有 case 级 provenance trace，无轮级 trace。

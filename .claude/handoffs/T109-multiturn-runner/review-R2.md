模型：wb / cn:deepseek-v4.1-flash / reasoning_effort=max

# T109 多轮 turns runner：R1 返工后独立复验 R2

验收对象：分支 `p1/fix-retrieval`，R1 交付 commit `1ffd57a`（父 `08661ff`）；HEAD `1b1580a`
（PM 簿记；`git diff 1ffd57a..1b1580a -- runner.py 测试` 为空）。工作树初始 clean。
结论：**PASS**（B1 已关闭；R1–R3 兑现；上轮 PASS 项无回归；测试全绿）。非阻断观察见末节。

## 0. 基线

- 父提交单轮源：detached worktree `backend\.pytest-tmp\T109-verify\base`（`ebfe956`）里的
  `regression-parent`（`…7638e33c`）；RG002/RG003/RG006 行无 `turn_traces`、
  `turns_executed=1`。manifest `dataset_sha256` 与父 fixture 实测 sha256 一致。
- 当前本地 run：`regression-current`（`…9647507a`）；replay 用当前 `tools/rag_eval.py`。
- 合成语料只含 E11；零真实模型/embedding/rerank/OCR 调用。

## 1. 逐条判定

| # | 项 | 判定 | 证据 |
| --- | --- | --- | --- |
| 1 | B1 replay 旧单轮源 + 多轮 case fail closed | **PASS** | 见 §2；`runner.py:1172`、`:1274-1292` |
| 1b | 源多轮但轮数不足 | **PASS** | `multi_turn_source_incomplete`；`runner.py:1195` |
| 1c | 合法多轮源仍逐轮 replay | **PASS** | 3 case × 2 轮、链源轮、`0/7 diffs`；03-C |
| 2 | R1 轮级 error 明细 | **PASS** | `error={code, "turn n/N: …"}`；`runner.py:923-948`、`:1017-1018`、`:1057` |
| 2b | R2 malformed/gold-error 多轮行 `turns_executed` | **PASS** | 0 而非默认 1；`runner.py:1801-1813`；03-E |
| 2c | R3 replay 逐轮题面 | **PASS** | `question_hash` = 该轮题面 = local；`runner.py:1242-1244`、`:2161+` |
| 3 | 上轮 PASS 抽查 | **PASS** | 03-F；见 §4 |
| 4 | 测试/回归（§11A） | **PASS** | 19 / 392 / 1795 passed；0 failed/0 error；04 |
| 5 | 合规/形式 | **PASS（含非阻断）** | 6 文件允许路径；无 fixtures/业务/API/intent/dataset/gate/账本；04 |

## 2. B1 复现（上轮阻断项）

命令（仓库根；完整见 04）：

```powershell
.venv\Scripts\python.exe -B tools\rag_eval.py run --suite regression --mode replay `
  --from-run backend\.pytest-tmp\T109-verify\base\backend\.pytest-tmp\T109-verify\eval\regression-parent `
  --dataset backend\.pytest-tmp\T109-verify\base\fixtures\evaluation\regression.jsonl `
  --out backend\.pytest-tmp\T109-R2\eval\regression-parent-replay
```

实跑 `regression-replay-…d3a55548`：RG002/RG003/RG006 三行全部

- `status=fail`、`multi_turn_claimed=True`；
- `error.code=multi_turn_source_missing`，message 含 case_id 与「2 轮」；
- `turns_executed=0`、`turn_traces=[]`；
- 无 `status=pass`，无「只有 1 条 turn_trace」的伪逐轮。

声明层 `multi_turn_verified=False`、`multi_turn_turns_executed=0`、
`multi_turn_error_case_ids=[RG002,RG003,RG006]`；gate exit 3、hard `[]`，不 crash。
同源单轮行 RG001/RG004/RG005/RG007 仍 1 轮/1 条 replay、status 不变。
代码：`_assert_replay_turn_sources`（`runner.py:1172`）在写行前拒绝；`_replay_case_row`
（`:1274-1292`）直接 `_error_row(..., status="fail", turn_traces=(), turns_executed=0)`，
不调用 `_replay_traces`。

**轮数不足**：把当前多轮源 RG002 的 `turn_traces` 截为 1 条后 replay（`…ff2b2437`）：
RG002 `fail`/`multi_turn_source_incomplete`/0 轮/无 turn_trace；RG003、RG006 仍各 2 条逐轮
replay。**合法源**：`regression-replay-…f7d2fe1f` 对 local `0/7 diffs`，RG002/RG003/RG006
各 2 条 replay trace、链到源轮、仅末轮带 outcome、无源 trace 复用。

## 3. R1–R3（独立合成探针，03-D/E）

- R1：中间轮 `kind=error`/`service_error` → `fail`，`error={code:"answer_error",
  message:"turn 1/2: 答案结局 kind=error|service_error（要求无 error）"}`，
  `turns_executed=2`、`turn_traces=['error','ok']`，末轮 checks 仍记录且只对末轮 score 一次。
  Trace 不可读 → `trace_missing`；Trace `status=error` → `trace_error`；均含 `turn 1/2`。
  末轮 error → `answer_error` + `turn 2/2`。
- R2：空题/非 user 轮多轮行 → `turns_executed=0`、`turn_traces=[]`（`turn_question_missing`/
  `turn_role_unsupported`）；非 mapping 轮由 `_case_turn_questions` 报 `turn_invalid`；
  gold 解析失败多轮行 → `gold_unresolved`/0/[]。对照单轮 gold error 仍 1 轮/1 条 error trace，
  未被多轮口径污染。
- R3：合法多轮 replay 每轮 `question_hash` 等于该轮 fixture 题面、也等于 local 对应轮，
  且 turn1≠turn2；另对「末轮 error」合成源 replay 补查，2 轮题面/local hash 仍一致。

## 4. 上轮 PASS 抽查（不依赖 report）

- local：A 两轮同 `conversation_id`/`user_id='eval'`、顺序 q1→q2、末轮只答 40；对照单轮
  「那个海报呢」仍 `clarification`；只调用 1 次 `score_case` 且输入末轮 outcome；G 的中间轮
  checks 若判分会 fail 但 case 仍 pass。
- 单轮：b0 40 行 / badcase 13 行对父提交 strict 0（仅多 `turn_traces` 键），对 P0
  `case_diffs=0`；`turns_executed=1`、`claimed=False`、1 条 turn_trace；gate 当前/P0 hard `[]`。
  b0 当前 replay 对父提交 replay 实质 0 diff、对 P0 replay 签名 0。
- regression：`case_diffs` 仅 RG006；RG002/RG003 pass、RG005/RG007 fail 集不变；gate 当前/
  父提交 hard `[]`。RG006 `expected_kind=answer`、`expected_values=['40']`、
  `forbidden=['店内外侧','QF01']` 保留；末轮文本含 40、不含未问字段；滨江店为 turn1 明问主体。

## 5. 测试/回归（§11A；详见 04）

| 范围 | 结果 |
| --- | --- |
| 本包 `test_multiturn_runner.py` | **19 passed**（9.63s） |
| `backend/tests/evaluation` | **392 passed**（87.74s） |
| 全量 `backend/tests`（1 次） | **1795 passed**，0 failed/0 error/0 skipped（493.55s，exit 0） |

pytest 前均设 `MKTKB_PROJECT_TOTAL_LIMIT_CNY=20.0`；无 flake，未触发隔离复跑；无 skip/xfail/
新依赖。内存 `Get-Process python` 54 次分段采样（约 260s，5s/4s）峰值 **497.2 MB < 2 GB**。

## 6. 合规/形式
- `git show --stat 1ffd57a` **6 文件**：runner.py、`test_multiturn_runner.py`、report.md、
  T109 证据 02/03/04；均在允许路径。`git show 1ffd57a -- fixtures` 为空。
- 无 fixtures/业务代码/API/intent/schemas/dataset/gate/账本/GO 改动；单 dev commit；
  未 push/amend/切分支/stash/reset；未读 `.env`/Holdout；零真实调用。
- T109 证据仍 4 份，02/03/04 含 R1 段；本 R2 证据 4 份（01–04）。

## 7. 残余 / 非阻断 / NOT-RUN
1. **provenance trace**：fail-closed 行 `trace_id` 非空，指向 1 条 case 级 replay provenance
   （`http_request_id` 以 `:provenance` 结尾、spans=0、不在 `turn_traces`）。不是轮 replay；
   若下游把非空 `trace_id` 当执行证据，建议后续置空或加显式标记。
2. **来源守卫按数量**：`_assert_replay_turn_sources` 只比轮数，不校验源轮 `turn` 序号/
   `trace_id` 可读性；重复轮号但数量相同的损坏源不会被拒（本轮合法源逐条核验通过）。
3. **report 140 行 > 80 预算**：R1 追加 §6 未压缩；内容与证据一致，属形式非阻断。
4. **测试契约同步**：R1 删除 2 条旧断言（`error is None`、`turns_executed == 1`），替换为
   更强的 error 明细/0 轮/无 trace 断言；未删测试、未弱化覆盖、已披露。
5. **内存采样**：54 次分段采样而非全程连续（约 260s/493.55s）；峰值 497.2 MB。
6. **NOT-RUN**：未读 `.env`/Holdout 实际标签；未做真实 provider 调用；无需 flake 隔离复跑。

## 8. 证据

`docs/reports/OBS-EVAL/P1/evidence/verify/T109-R2/01-verdict.md`、`02-probe.py`、
`03-probe-results.md`、`04-test-eval-runs.md`（共 4 份）。

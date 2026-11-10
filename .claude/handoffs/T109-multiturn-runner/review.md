模型：wb / cn:deepseek-v4.1-flash / reasoning_effort=max

# T109 多轮 turns runner 独立验收 review

验收对象：分支 `p1/fix-retrieval`，交付 commit `703b7e0`（父 `ebfe956`）。
结论：**FAIL（1 个阻断项）**。核心多轮执行、判定、单轮不变、RG006 非放宽均 PASS；replay 在
「旧源单轮 run 遇多轮 case」时静默只 replay 首轮，违反 handoff §3.5/§5。

## 基线准备（开发披露的坑）

`git worktree add --detach backend\.pytest-tmp\T109-verify\base ebfe956`；只复制（不读内容）
`.gitignore` 忽略的 `docs/evidence/LOCAL-R1-20261101/S1-DEV/R2/subset-policy.json` 到 worktree 同路径。
复制后 worktree `git status --short` 为空；主/基线 manifest 均 `index_revision=49`、
`corpus_manifest_sha256=5f41b1b8…`，语料可比。主工作树交付前 clean；验收后仅新增未跟踪的
`docs/reports/OBS-EVAL/P1/evidence/verify/T109/` 与 `review.md`。

## 逐条判定

| # | 项 | 判定 | 关键证据/命令 |
| --- | --- | --- | --- |
| 1 | 多轮执行正确性 | **PASS** | 合成 A–I（03 D）；RG006 实跑文本 `根据资料，滨江店的宣传海报的数量：40张。`；trace 链见 03 C |
| 2 | 单轮不变 | **PASS** | b0/badcase 对 P0 `case_diffs=0/40、0/13`；对父提交 strict 0；键顺序=父键+尾插 `turn_traces`；`turns_executed=1` |
| 3 | RG006 非放宽 | **PASS** | `case_diffs` 仅 RG006；`expected_kind=answer`、`expected_values=['40']`；`forbidden=['店内外侧','QF01']` 保留；滨江店移出有 turn1 明问依据 |
| 4 | replay | **FAIL** | 当前多轮 replay 逐轮/链源轮/0/7 diffs PASS；旧源单轮 run 遇多轮 case 静默 1 条 trace（下方复现） |
| 5 | 测试/回归（§11A） | **PASS（环境前置）** | 15 / 388 / 1791 passed；峰值 874.5 MB <2GB；首次全量缺 `MKTKB_PROJECT_TOTAL_LIMIT_CNY=20.0` 的 1 个基线失败隔离复跑通过（04） |
| 6 | 合规/形式 | **PASS（含披露）** | 9 文件全在允许路径、fixtures 仅 RG006 一行、report 79 行、证据 4 份、单 commit、零真实调用、未读 `.env`/Holdout |

## 阻断项复现（replay 旧源单轮 run 遇多轮 case）

源 = 父提交 regression run（`regression-local-…7638e33c`），RG002/RG003/RG006 行**无** `turn_traces`。
命令（仓库根）：

```powershell
.venv\Scripts\python.exe -B tools\rag_eval.py run --suite regression --mode replay `
  --from-run backend\.pytest-tmp\T109-verify\base\backend\.pytest-tmp\T109-verify\eval\regression-parent `
  --dataset backend\.pytest-tmp\T109-verify\base\fixtures\evaluation\regression.jsonl `
  --out backend\.pytest-tmp\T109-verify\eval\regression-parent-replay
```

实际三行均为 `status=pass`、`turns_executed=1`、`multi_turn_claimed=True`、`turn_traces` 1 条、`error=None`；
即静默只 replay 首轮。代码路径：`backend/src/mktkb/evaluation/runner.py:1178` 只读源 `turn_traces`，
`:1227`/`:1251` 在无源轮记录时调用 `_replay_traces`，`:1130` 的 `len(source_turns) <= 1` 写单条 provenance。
handoff §5 明确要求「replay 源单轮 run 遇多轮 case：明确错误；不得伪造逐轮结果」；§3.5 要求
「逐轮或明确拒绝，无静默首轮；有测试」。交付测试只有「源为当前多轮 run」的 replay 用例，无此分支。

**建议**：`_replay_case_row` 在 `len(case.turns) > 1 and not source_turns` 时 fail closed
（如 `multi_turn_source_missing`），不要写单条 replay；亦应拒绝 `turn_traces` 少于 `turns` 的旧多轮源
（或明确报「源 run 未逐轮执行」），并补一条测试。

## 已验证要点（不依赖 report）

- 顺序/同一会话：合成 A 的两次 `index.ask` 记录同一 `conversation_id`/`user_id='eval'`，问题顺序为 turn1→turn2；
  末轮只答 40，未答未问字段；对照单轮「那个海报呢」仍 `clarification`（状态继承成立）。
- 只末轮评分：spy `score_case` 在 A 只调用 1 次且输入为末轮 outcome/record；中间轮 checks 不参与（G 通过）。
- 判定：C/D 中间轮 `kind=error`/`service_error` → `fail`；E 中间轮异常 → `fail` 且 `error.message='turn 2/3: …'`、
  `turns_executed=2`；F 末轮 checks fail → `fail`；H 末轮 `error` → `fail`；I Trace 不可读 → `fail`。
- trace：local RG002/RG003/RG006 各 2 条，turn1 `previous=None`、turn2 链 turn1，`question_hash` 逐轮对应；
  `trace_id`=末轮；replay 逐轮 2 条、链源轮、仅末轮 outcome，`replay vs local` 去 volatile 0/7 diff。
- 单轮 replay：b0 当前 replay 对父提交 40 行 0 diff、对当前 local 0 diff；`turns_executed=1`/`claimed=False`；
  对 P0 签名 0 diff（Q31 自由文本为 T106 既有漂移，不计 T109）。
- 回归：RG002/RG003 多轮后仍 pass/outcome 不变；RG005/RG007 fail 集不变；gate 当前/父提交/P0 均 exit 3、hard `[]`；
  unknown 集合（gate/check/reason）一致，仅 RG006 指标观测值变化。
- 测试：`15 passed`（7.73s）/`388 passed`（88.80s）/`1791 passed`（489.65s）；内存峰值 874.5 MB（tasklist 1s 轮询，
  313 样本）；首次全量未设 `MKTKB_PROJECT_TOTAL_LIMIT_CNY=20.0` 时 1790 passed/1 failed，隔离设该变量后 1 passed，
  属交付证据 04 已写明的测试前置，不是 T109 代码回归。
- 形式：`git show --stat 703b7e0` 9 文件；`git show 703b7e0 -- fixtures` 仅 RG006 一行（1 增 1 删）；
  report 79 行五段；证据 4 份；无 skip/xfail/新依赖；未 push/commit/切分支/stash/reset。

## 残余 / 非阻断

1. **error 明细口径**：中间轮 `kind=error`/`service_error`/Trace 不可读时 case 正确 `fail`，但 `error=None`
   （仅 `turn_traces[].status=error`）；report §1 与 `_local_multi_turn_row` docstring 称任一轮 error 都带
   `error={…turn n/N}`，仅异常路径兑现。handoff 只要求 fail，故不阻断，但报告措辞需修正。
2. **error-row 的 `turns_executed`**：malformed turns / gold 解析失败等未执行轮次仍记 1（`runner.py:1669` 默认值），
   与「实际执行轮次」语义不完全一致；本包测试也断言 1。
3. **replay 题面**：`_write_provenance_trace` 对每轮都用 `case.question`（末轮），replay turn1 的
   `question_hash` 等于末轮问题；链/序号正确，但 trace 题面不是源轮题面（`runner.py:1129-1138`）。
4. **测试契约同步**：`test_holdout_suite.py` 删除 2 条 T108 旧断言、替换为 9 条更强断言；已披露，非弱化，
   但形式项「无删断言」按字面有出入。
5. **NOT-RUN**：无（holdout 实际标签/`.env` 按红线未读；未做真实 provider 调用）。

## 证据

`docs/reports/OBS-EVAL/P1/evidence/verify/T109/01-verdict.md`、`02-probe.py`、`03-probe-results.md`、
`04-test-eval-runs.md`（共 4 份）。

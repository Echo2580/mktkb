# T109 R1 返工复验 R2：结论与逐条判定

模型：`wb / cn:deepseek-v4.1-flash / reasoning_effort=max`（本文件为独立验收证据，非交付物）

验收对象：分支 `p1/fix-retrieval`，R1 交付 `1ffd57a`（父 `08661ff`）；HEAD `1b1580a`（PM 簿记，
runner/tests 与 `1ffd57a` 无差异，`git diff 1ffd57a..1b1580a -- runner.py 测试` 为空）。

结论：**PASS**（B1 阻断已关闭；R1/R2/R3 兑现；上轮 PASS 项无回归；测试全绿）。
非阻断：report 140 行 > 80 预算；fail-closed 行仍保留 1 条 case 级 provenance trace（不入
`turn_traces`）；测试 2 条旧断言按契约替换为更强断言；内存为分段采样非全程连续。

| # | 项 | 判定 | 关键证据 |
| --- | --- | --- | --- |
| 1 | B1 replay 旧单轮源 + 多轮 case | **PASS** | 父提交 run 三行 `fail`/`multi_turn_source_missing`/`turns_executed=0`/`turn_traces=[]`；03-A |
| 1b | 源多轮但轮数不足 | **PASS** | `multi_turn_source_incomplete`，轮数 0、无 turn_trace；同源其余多轮仍逐轮；03-B |
| 1c | 合法多轮源逐轮 replay | **PASS** | RG002/RG003/RG006 各 2 条、链源轮、只末轮 outcome、`0/7 diffs`；03-C |
| 2 | R1 轮级 error 明细 | **PASS** | `error={code, "turn n/N: …"}`，`turns_executed` 实际轮数；03-D |
| 2b | R2 malformed/gold-error 多轮行 | **PASS** | `turns_executed=0`、`turn_traces=[]`；单轮 gold error 仍 1/1；03-E |
| 2c | R3 replay 逐轮题面 | **PASS** | 每轮 `question_hash` = 该轮题面 = local 对应轮；03-C |
| 3 | 上轮 PASS 抽查 | **PASS** | local 顺序/同会话/状态继承/只末轮评分；b0 40、badcase 13 strict 0/P0 0；RG006 非放宽；RG002/3 pass、RG005/7 不变；gate hard `[]`；03-F |
| 4 | 测试/回归（§11A） | **PASS** | 19 / 392 / 1795 passed；0 failed/0 error；峰值 497.2 MB；04 |
| 5 | 合规/形式 | **PASS（含非阻断观察）** | 6 文件全允许路径；无 fixtures/业务/API/intent/dataset/gate/账本；单 dev commit；零真实调用；04 |

## B1 复现与修复（命令见 03/04）

- 源：父提交 `ebfe956` 的 regression local run `regression-local-…7638e33c`（行无
  `turn_traces`、`turns_executed=1`；manifest dataset sha 与父 fixture 一致）。
- 当前 replay：`regression-replay-…d3a55548`。RG002/RG003/RG006 均
  `status=fail`、`error.code=multi_turn_source_missing`、`turns_executed=0`、
  `turn_traces=[]`、`multi_turn_claimed=True`；无 `status=pass`，无 1 条 turn_trace。
- 代码：`runner.py:1172` `_assert_replay_turn_sources`；`:1274-1292` 在写行前 fail closed
  （不调用 `_replay_traces`）；`:1195` 轮数不一致 `multi_turn_source_incomplete`。
- 声明层：`multi_turn_verified=False`、`multi_turn_turns_executed=0`、
  `multi_turn_error_case_ids=[RG002,RG003,RG006]`；gate exit 3、hard `[]`（不 crash）。
- 同源单轮行（RG001/RG004/RG005/RG007）仍为 1 轮/1 条 replay、status 不变。

## 残余 / 观察（不阻断）

1. **provenance trace**：fail-closed 行 `trace_id` 非空，指向 1 条 case 级 replay
   provenance（`http_request_id` 以 `:provenance` 结尾、spans=0、不在 `turn_traces`）。
   不是轮 replay，但若下游把「非空 trace_id」当执行证据，建议后续把 fail-closed 行
   `trace_id` 置空或加显式标记。
2. **来源完整性守卫按数量**：`_assert_replay_turn_sources` 只比较 `len(source_turns)` 与
   `len(case.turns)`，不校验源轮 `turn` 序号/`trace_id` 是否可读；重复轮号但数量相同的
   损坏源仍可进入逐轮 replay（本轮合法源已逐条核验 question/链接/outcome）。
3. **report 140 行 > 80 预算**：R1 在首轮 79 行正文后追加 §6，未压缩；内容与证据一致，
   属形式非阻断。
4. **测试契约同步**：R1 删除 2 条旧断言（`error is None`、`turns_executed == 1`），替换为
   更强的 error 明细/0 轮/无 trace 断言；未删测试、未 skip/xfail、未弱化覆盖。
5. **内存采样**：全量 1795 passed/493.55s；`Get-Process python` 54 次分段采样（约 260s，
   5s/4s 间隔）峰值 497.2 MB < 2 GB；非全程连续采样。

## NOT-RUN / 红线

- 未读 `.env`、未读 Holdout 实际题目/标签；未做真实模型/embedding/rerank/OCR 调用。
- 未 push/commit/切分支/stash/reset；未改交付物；仅新增 `verify/T109-R2/` 与 `review-R2.md`。
- 全量测试无失败，未触发 flake 隔离复跑（无 flake 可隔离）。

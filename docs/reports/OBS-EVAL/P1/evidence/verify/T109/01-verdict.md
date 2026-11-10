# T109 独立验收结论

模型：`wb / cn:deepseek-v4.1-flash / reasoning_effort=max`（review.md 首行同）
验收对象：`p1/fix-retrieval`，T109 交付 `703b7e0`（父 `ebfe956`）。
结论：**FAIL（1 个阻断项）**。

## 阻断项（handoff §3.5 / §5）

**replay 源单轮 run 遇多轮 case 未明确拒绝，静默只写首轮。**

- 复现：父提交 `ebfe956` 的 regression run（`…7638e33c`，RG002/RG003/RG006 行无 `turn_traces`）
  作为源，当前代码以 `--dataset <父 fixture>` replay（`…a1e9ba13`）。
- 实际：三个多轮 case 的 replay 行均为 `turns_executed=1`、`multi_turn_claimed=True`、
  `turn_traces` 仅 1 条、`error=None`，status 仍 pass；即静默只 replay 了首轮。
- 代码位置：`backend/src/mktkb/evaluation/runner.py:1178`（只读源 `turn_traces`）、
  `:1227`/`:1251`（无源轮记录时走 `_replay_traces`）、`:1130`（`len(source_turns) <= 1` 写单条 provenance）。
- handoff §5 原文要求「replay 源单轮 run 遇多轮 case：明确错误；不得伪造逐轮结果」；§3.5 要求
  「逐轮或明确拒绝，无静默首轮；有测试」。交付测试无此分支用例（只有当前多轮 run → replay）。

## 逐条判定

| # | 验收项 | 判定 | 依据 |
| --- | --- | --- | --- |
| 1 | 多轮执行正确性（顺序/同一 conversation/trace 链/只末轮评分/error→fail/末轮 fail/全通过 pass） | **PASS** | 证据 03 D：A–I 合成用例；RG006 实跑；trace 链与 `question_hash` 见 03 C |
| 2 | 单轮不变（b0/badcase 对 P0 `case_diffs=0/40、0/13`；对父提交逐字段一致；键顺序；`turns_executed=1`） | **PASS** | 03 A/B：`strict=0`、`sig0=0`、父键 + 尾插 `turn_traces` |
| 3 | RG006 非放宽（仅一行；末轮含 40；`answer`/`expected_values` 含 40；未问字段 forbidden 保留） | **PASS** | 03 A：文本 `…40张。`；fixture `forbidden=['店内外侧','QF01']`；滨江店有 turn1 明问依据 |
| 4 | replay（多轮逐轮 trace + 链源轮 + 末轮复评分；单轮旧口径） | **FAIL** | 当前多轮 replay 逐轮/0 diffs 通过；但旧源单轮 run 遇多轮 case 静默首轮（阻断项） |
| 5 | 测试/回归（本包 1 次、evaluation 1 次、全量 1 次；0 failed/error；内存 <2GB） | **PASS（带环境前置）** | 15 / 388 / 1791 passed；峰值 874.5 MB；首次全量缺 `MKTKB_PROJECT_TOTAL_LIMIT_CNY=20.0` 时 1 个无关基线失败，隔离复跑通过（04） |
| 6 | 合规/形式（9 文件允许路径；fixtures 仅 RG006；report 79 行/证据 4；单 commit；零真实调用；未读 .env/Holdout） | **PASS（含披露）** | 04 §4；`test_holdout_suite.py` 2 条旧断言替换为 9 条更强断言（已披露，非弱化） |

## 非阻断残余（建议记录/后续）

1. **error 明细口径不一致**：中间轮 `kind=error` / `service_error` / Trace 不可读时 case 正确为 `fail`，
   但行 `error=None`（仅 `turn_traces[].status=error`）；报告 §1 第 2 条与 `_local_multi_turn_row`
   docstring 称「任一轮 error → status=fail + error={…turn n/N}」，仅异常路径兑现。handoff 只要求 fail，
   故不阻断，但报告措辞应修正。
2. **error-row 的 `turns_executed`**：malformed turns / gold 解析失败等未执行任何轮的 `_error_row` 仍记
   `turns_executed=1`（`runner.py:1669` 默认值），与「实际执行轮次」语义不完全一致；本包测试也断言 1。
3. **replay 逐轮 trace 的 question**：`_write_provenance_trace` 对每一轮都用 `case.question`（末轮问题），
   因此 replay turn1 的 `question_hash` 等于末轮问题；链和 `turn` 序号正确，但 trace 的题面不是源轮题面
   （`runner.py:1129-1138`）。不影响逐轮链/评分，建议后续修。
4. **P0 自由文本差异**：b0 replay 对 P0 有 Q31 等 T106 既有文案漂移（对父提交 0 diff），不计入 T109。

## 基线准备

`git worktree add --detach backend\.pytest-tmp\T109-verify\base ebfe956`；只复制（不读内容）
`.gitignore` 忽略的 `docs/evidence/LOCAL-R1-20261101/S1-DEV/R2/subset-policy.json` 到 worktree 同路径。
复制后 worktree clean；两侧 `index_revision=49`、`corpus_manifest_sha256` 一致（03 A）。主工作树未被修改。
